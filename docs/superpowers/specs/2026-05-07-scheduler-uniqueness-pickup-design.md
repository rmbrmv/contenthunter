# Sub-project A — Scheduler→Uniqueness Pickup Sweep

**Date:** 2026-05-07
**Status:** Design — pending implementation plan
**Revision:** v3 (post-Codex v2 review — applied inline)

## Problem

Клиенты планируют контент в `client.contenthunter.ru/scheduler`, но запланированные видео не подбираются на этап уникализации и поэтому не доходят до публикации. Production-блокер.

### Pipeline сегодня (verified от кода `autowarm-testbench/server.js`)

Уникализация запускается из **двух** мест:

1. **`POST /api/unic/trigger-immediate`** (line 5299–5344) — webhook от validator при approve контента. Жёстко фильтрует `slot_date = today` (GMT+4). Если approve не в день slot_date — `triggered=false`, тихо выходит.

2. **`triggerAutoUnic()`** (line 5500–5549) — `setInterval(..., 30 * 60 * 1000)` на line 5551. **НО** внутри проверяется узкое временное окно:
   ```javascript
   if (diff < 0 || diff > 30) return; // только в 30-min окне после (publish_start - prep_hours)
   if (autoUnicLastTriggeredDate === slotDate) return; // только 1 раз в день
   ```
   Срабатывает один раз в день в окне ~05:00 GMT+4 (если `publish_start='09:00'` и `prep_hours=4`). После окна — никаких повторов.

`autoUnicLastTriggeredDate` — переменная **в памяти процесса**. Перезапуск сервера сбрасывает её, но ловить нечего, если день уже прошёл.

`unic-worker` (`autowarm/unic-worker/worker.py:67-74`) поллит `unic_tasks WHERE current_status='pending'` каждые 3 секунды — игнорируя `slot_date`. Worker корректен; проблема исключительно в том, что в `unic_tasks` ничего не INSERTится.

### Сценарии разрыва pipeline'а

| approve | slot_date | trigger-immediate | morning-batch (05:00) | Итог сегодня |
|---|---|---|---|---|
| день N, slot=N | то же | ✅ срабатывает | ✅ резерв | ✅ |
| день N–1, slot=N | завтра на момент approve | ❌ today != slot | ✅ ловит утром N | условно ✅ (ждёт утра) |
| день N–1, slot=N, **сервер рестартанул в окне 05:00–05:30** на N | — | ❌ | ❌ окно прошло (или window-guard сбросил, но все равно miss) | ❌ |
| день N+1, slot=N | вчера | ❌ | ❌ N уже прошёл | ❌ (per-policy не лечим) |
| день N, slot=N, transient DB-сбой в 05:00 | — | ❌ (ещё не approve) | ❌ окно ушло | ❌ |
| день N, slot=N, approve в 14:00 | — | ✅ | — | ✅ |
| день N, slot=N, **большой объём slots в окне → таймаут** | — | ❌ | ❌ частично, остаток теряется | ❌ |

### Concurrency-риск (Codex finding #1, verified против схемы)

Схема `unic_tasks` (`\d unic_tasks`):

- PRIMARY KEY (id)
- Partial **non-unique** index `ix_unic_tasks_content_id` (content_id) WHERE content_id IS NOT NULL
- **НЕТ unique constraint на `(content_id, slot_date)`**

Текущая защита от дублей в SQL:
```sql
NOT EXISTS (SELECT 1 FROM unic_tasks ut
            WHERE ut.content_id = c.id AND ut.slot_date = $1
            AND ut.current_status IN ('pending','processing','done'))
```

Это **read-modify-write race**: при default Postgres READ COMMITTED две одновременные транзакции (trigger-immediate + sweep) могут оба прочитать «not exists» и оба заинсертить.

**Blast radius дубликата**: дубль в `unic_tasks` → worker отрабатывает обе → 2× `unic_results` → `assignUnicResultsToQueue` пушит обе → **двойная публикация на телефонах**. Не ОК.

## Goals

- Любой `(content.status='approved' AND moderation_status='passed' AND slot.status='filled' AND slot_date=today)` слот должен попасть в `unic_tasks` обычно в пределах одного sweep-интервала (≤5 мин после момента, когда оба условия выполнены).
- In-day flow остаётся быстрым: `trigger-immediate` не трогаем, отклик 1–2 сек.
- При concurrency двух источников (trigger-immediate vs sweep) дубликаты в `unic_tasks` физически невозможны.
- Ничего не ломается в существующем morning-batch (`triggerAutoUnic`).

## Non-goals

- Не лечим стрэндед-слоты прошлых дней. Per user policy: клиенты переносят вручную.
- Не делаем cancellation удалённого контента (это под-проект C).
- Не enqueue'им future-слоты заранее (пересекается с C).
- Не переписываем validator-сторону.
- Не убираем `triggerAutoUnic` (морин-батч остаётся как историческая семантика; sweep его дополняет, а не заменяет — см. Open question Q3 ниже).

## Approach

Два изменения, каждое маленькое:

### Change 1 — миграция: уникальный partial index на `unic_tasks`

Деплой делится на **два шага**, потому что `CREATE INDEX CONCURRENTLY` не может выполняться внутри транзакции, а живой dedup мутирует прод-данные при работающем worker'е (Codex BLOCKER #3). Воркер придётся остановить на короткое окно дедупа.

**Step 1 — read-only audit (до деплоя):** скрипт `autowarm/scripts/audit_unic_tasks_duplicates.sql`:

```sql
SELECT content_id, slot_date,
       array_agg(id ORDER BY id) AS task_ids,
       array_agg(current_status ORDER BY id) AS statuses,
       array_agg(created_at ORDER BY id) AS created_ats
FROM unic_tasks
WHERE content_id IS NOT NULL
  AND slot_date IS NOT NULL
  AND current_status IN ('pending','processing','done')
GROUP BY content_id, slot_date
HAVING COUNT(*) > 1;
```

Если дубликатов нет (ожидаемое состояние) — переходим к Step 2 без cleanup. Если есть — отдельная ручная процедура: остановить `pm2 stop unic-worker`, провести сверку с `unic_results` для каждого спорного `(content_id, slot_date)`, ops решает какие оставить, какие пометить `error` через явные SQL (с PRINT'ом затронутых ID до изменения). Не автоматизируем — слишком много политики (что лучше: сохранять `processing` или `done` если есть оба).

**Step 2 — миграция:** `autowarm/migrations/<next>_unic_tasks_unique_active_slot.sql`. Файл стандартный одноразовый SQL, выполняется напрямую через psql, не через runner с tx-обёрткой:

```sql
-- Запускать напрямую через psql, НЕ через migration runner с автотранзакцией.
-- CREATE INDEX CONCURRENTLY запрещён внутри tx.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_unic_tasks_active_slot
  ON unic_tasks (content_id, slot_date)
  WHERE current_status IN ('pending','processing','done')
    AND content_id IS NOT NULL
    AND slot_date IS NOT NULL;
```

После применения — проверить `\d unic_tasks` и подтвердить присутствие индекса. Если миграция падает с `could not create unique index ... duplicate key value` — значит audit пропустил дубль; rollback `DROP INDEX CONCURRENTLY` и заново через ручную процедуру.

Partial unique index: пока задача жива (`pending|processing|done`), нельзя создать вторую с тем же `(content_id, slot_date)`. После `error` — можно повторно (например, sweep подберёт после ручного reset).

### Change 2 — добавить sweep-loop в `autowarm/server.js`

Self-scheduling recursive `setTimeout` (стабильнее `setInterval` под event-loop задержками — Codex MINOR #17). Date вычисляется явно (Codex BLOCKER #2). INSERT защищён `ON CONFLICT DO NOTHING` поверх нового индекса (Codex BLOCKER #1).

```javascript
// autowarm/server.js, новый блок после строки 5555 (рядом с setInterval(triggerAutoUnic))

const UNIC_SWEEP_INTERVAL_MS = 5 * 60 * 1000;
const UNIC_SWEEP_INITIAL_DELAY_MS = 30 * 1000;
let unicSweepRunning = false;
let unicSweepTimer = null;

// DST-aware (Codex IMPORTANT #6). Использует Intl, который учитывает DST.
function computeBusinessDate(timezone, baseTime = Date.now()) {
  const tz = timezone || 'Asia/Dubai';
  try {
    const fmt = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz,
      year: 'numeric', month: '2-digit', day: '2-digit',
    });
    return fmt.format(new Date(baseTime));  // 'YYYY-MM-DD'
  } catch (e) {
    console.error(JSON.stringify({
      tag: 'unic-sweep', ok: false,
      error: `unknown timezone '${tz}', falling back to Asia/Dubai`,
    }));
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Dubai', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date(baseTime));
  }
}

// Возвращает [today, yesterday] business-dates для grace-window после midnight (Codex IMPORTANT #5)
function computeBusinessDateWindow(timezone) {
  const today = computeBusinessDate(timezone);
  const yesterdayMs = Date.now() - 24 * 3600 * 1000;
  const yesterday = computeBusinessDate(timezone, yesterdayMs);
  return [today, yesterday];
}

async function runScheduledUnicSweep() {
  if (unicSweepRunning) {
    console.warn(JSON.stringify({
      tag: 'unic-sweep', ok: true, skipped: true,
      reason: 'previous tick still running',
    }));
    scheduleNextSweep();
    return;
  }
  unicSweepRunning = true;
  const t0 = Date.now();
  let targetDates = [];
  try {
    const { rows } = await pool.query('SELECT * FROM unic_settings WHERE id=1');
    const settings = rows[0] || {};
    targetDates = computeBusinessDateWindow(settings.timezone);  // [today, yesterday]

    let totalInserted = 0;
    for (const date of targetDates) {
      // runAutoUnicForDate возвращает {inserted, skipped, errors} (см. изменение ниже)
      const r = await runAutoUnicForDate(date, settings);
      totalInserted += r.inserted;
      console.log(JSON.stringify({
        tag: 'unic-sweep', ok: true,
        target_date: date,
        inserted: r.inserted, skipped: r.skipped, errors: r.errors,
      }));
    }

    console.log(JSON.stringify({
      tag: 'unic-sweep', ok: true,
      summary: true,
      target_dates: targetDates,
      total_inserted: totalInserted,
      took_ms: Date.now() - t0,
    }));
  } catch (e) {
    console.error(JSON.stringify({
      tag: 'unic-sweep', ok: false,
      target_dates: targetDates,
      error: e.message,
      took_ms: Date.now() - t0,
    }));
  } finally {
    unicSweepRunning = false;
    scheduleNextSweep();
  }
}

function scheduleNextSweep() {
  if (unicSweepTimer) clearTimeout(unicSweepTimer);
  unicSweepTimer = setTimeout(runScheduledUnicSweep, UNIC_SWEEP_INTERVAL_MS);
}

// Запускать только в production-режиме. В тестах используем module.exports {start, stop} (Codex MINOR #11)
function startUnicSweepLoop() {
  if (unicSweepTimer) return;  // idempotent
  unicSweepTimer = setTimeout(runScheduledUnicSweep, UNIC_SWEEP_INITIAL_DELAY_MS);
}

function stopUnicSweepLoop() {
  if (unicSweepTimer) { clearTimeout(unicSweepTimer); unicSweepTimer = null; }
}

if (process.env.NODE_ENV !== 'test') {
  startUnicSweepLoop();
}

module.exports = {
  ...module.exports,  // или эквивалентная пристройка для server.js export-style
  startUnicSweepLoop, stopUnicSweepLoop, runScheduledUnicSweep, computeBusinessDate,
};
```

И **изменение в `runAutoUnicForDate`** (line 5355–5481) — две вещи:

1. INSERT с правильным `ON CONFLICT` index-inference syntax (Codex BLOCKER #1):

```javascript
// line 5456 — заменить INSERT
const insertResult = await pool.query(`
  INSERT INTO unic_tasks
    (input_video_url, input_video_name, project_name, schemes, schemes_total,
     current_status, project_id, content_id, slot_date, meta, created_at, updated_at)
  VALUES ($1,$2,$3,$4,$5,'pending',$6,$7,$8,$9,NOW(),NOW())
  ON CONFLICT (content_id, slot_date)
  WHERE current_status IN ('pending','processing','done')
  DO NOTHING
  RETURNING id
`, [...]);

const inserted = insertResult.rowCount > 0;
if (inserted) {
  await pool.query(
    `UPDATE validator_content SET status='in_uniqualization', unic_queued_at=NOW(), updated_at=NOW() WHERE id=$1`,
    [slot.content_id]
  );
  console.log(`[auto-unic] ✅ task created: slot=${slot.slot_id} ...`);
} else {
  console.log(JSON.stringify({
    tag: 'auto-unic', skipped: true, reason: 'race-conflict',
    slot_id: slot.slot_id, content_id: slot.content_id, slot_date: slotDate,
  }));
}
```

2. **Возвращать count из `runAutoUnicForDate`** (Codex IMPORTANT #9):

```javascript
async function runAutoUnicForDate(slotDate, settings) {
  let inserted = 0, skipped = 0, errors = 0;
  // ... existing body ...
  for (const slot of slots) {
    try {
      // existing select packs/schemes
      if (!packs.length || !approvedSchemes.length || ...) { skipped++; continue; }
      // INSERT with ON CONFLICT
      if (insertResult.rowCount > 0) { inserted++; }
      else { skipped++; }
    } catch (e) {
      console.error(`[auto-unic] error on slot=${slot.slot_id}:`, e.message);
      errors++;
    }
  }
  return { inserted, skipped, errors };
}
```

**Все INSERT'ы в `unic_tasks` идут через `runAutoUnicForDate`** (Codex IMPORTANT #7) — `trigger-immediate` (line 5337) и `triggerAutoUnic` (line 5547) оба её вызывают. Один patch покрывает все пути.

## Pseudo-flow после фикса

```
[validator approve] ─trigger-immediate─→ [autowarm runAutoUnicForDate(today)]
                                                  ▲   ▲
       morning-batch (existing) ────────────────┘   │
       (NEW) sweep every 5 min ───────────────────┘
                                                  │
                                  ON CONFLICT DO NOTHING
                                                  │
                                                  ▼
                                          unic_tasks (no dup)
```

## Error handling

- На уровне sweep: `try/catch` + структурированный JSON-error log. Не падать процесс.
- На уровне slot inside `runAutoUnicForDate`: существующая логика (`continue` при отсутствии паков/схем) сохраняется. Добавить структурированный warn-лог если ON CONFLICT случился (видимый сигнал что race реально происходит).
- Если БД недоступна 5+ мин подряд → процесс продолжит писать ошибки в лог; следующий тик попробует снова.

## Observability

JSON-логи (один объект на тик) с полями: `tag, ok, target_date, picked, took_ms, error`. PM2 уже агрегирует stdout в файл; внешний дашборд (если будет) парсит JSON. Дополнительно — структурированный warn `[auto-unic] skipped (race-conflict)` укажет, есть ли реально concurrent INSERT'ы; если их 0 за неделю — guard избыточен, но disabling его несёт нулевой downside.

Health-метрика (запускать через скрипт, который сам вычисляет business-date в нужном TZ — Codex IMPORTANT #10): `SELECT COUNT(*) FROM validator_schedule_slots s JOIN validator_content c ON c.id=s.content_id WHERE s.slot_date = $1 AND s.status='filled' AND c.status='approved' AND c.moderation_status='passed' AND NOT EXISTS (SELECT 1 FROM unic_tasks ut WHERE ut.content_id=c.id AND ut.slot_date=s.slot_date AND ut.current_status IN ('pending','processing','done'))` где `$1 = computeBusinessDate(timezone)` (тот же помощник, что и в sweep'е). НЕ использовать `CURRENT_DATE` — даст ложные алерты на UTC midnight.

## Testing (TDD)

Тесты делятся на **unit** (sweep-обёртка, guard, error path, computeBusinessToday) и **integration** (DB-eligibility, ON CONFLICT semantics).

### Unit (Jest, моки `pool` и `runAutoUnicForDate`)

| ID | Сценарий | Expect |
|---|---|---|
| **U1** | `computeBusinessToday('Asia/Dubai')` при mock'нутом `Date.now()=2026-05-07T20:30:00Z` | `'2026-05-08'` (UTC 20:30 + 4ч = 00:30 GMT+4) |
| **U2** | `computeBusinessToday('UTC')` при том же mock'е | `'2026-05-07'` |
| **U3** | `computeBusinessToday('America/New_York')` (offset −5) при `2026-05-07T03:00:00Z` | `'2026-05-06'` |
| **U4** | `runScheduledUnicSweep` когда `unicSweepRunning=true` | warn-лог, нет вызова `runAutoUnicForDate`, recursive setTimeout запланирован |
| **U5** | `runAutoUnicForDate` бросает → sweep пишет error-JSON, не падает, `unicSweepRunning` сброшен, следующий тик запланирован |
| **U6** | sweep успешен, `pickedAfter - pickedBefore = 3` | JSON-лог с `picked=3` |

### Integration (real testbench DB, fixture engine)

Setup: создать `validator_content` rows + `validator_schedule_slots` rows с явным `slot_date`. Вызывать `runScheduledUnicSweep()` напрямую с замоканным `Date.now()`.

| ID | Setup | Expect |
|---|---|---|
| **I1** | slot=`'2026-05-07'`, content `approved+passed`, нет `unic_tasks`. Mock `Date.now()` = 2026-05-07T08:00 GMT+4 | После tick: 1 строка в `unic_tasks`, `slot_date='2026-05-07'`, `current_status='pending'`. `validator_content.status='in_uniqualization'`. |
| **I2** | как I1, но **уже есть** `unic_tasks(content_id, slot_date, current_status='pending')` | Ровно 1 строка остаётся (idempotency через ON CONFLICT). validator_content.status НЕ меняется. |
| **I3** | как I1, но `unic_tasks` row в `current_status='processing'` | По-прежнему 1 строка, no insert. |
| **I4** | как I1, но `unic_tasks` row в `current_status='done'` | 1 строка, no insert. |
| **I5** | как I1, но `unic_tasks` row в `current_status='error'` | **2 строки** после tick: старая ('error') + новая ('pending'). Re-enqueue после fail разрешён by-design. |
| **I6** | slot=`'2026-05-08'` (завтра в GMT+4), mock `Date.now()` соответствует 2026-05-07 | 0 новых строк. |
| **I7** | slot=`'2026-05-06'` (вчера), mock соответствует 2026-05-07 | 0 новых строк. |
| **I8** | Midnight rollover: mock `Date.now() = 2026-05-07T19:59 UTC` (= 2026-05-07T23:59 GMT+4). slot=`'2026-05-07'`. | Tick #1 берёт slot=2026-05-07. Затем mock Date.now() = 2026-05-07T20:01 UTC (= 2026-05-08T00:01 GMT+4). slot=`'2026-05-08'` создан. Tick #2 берёт slot=2026-05-08. (Проверяет, что date вычисляется на каждый tick.) |
| **I9** | slot=`'2026-05-07'`, **content.status='validating'** (не approved) | 0 новых строк. |
| **I10** | slot=`'2026-05-07'`, content approved, **slot.status='empty'** | 0 новых строк. |
| **I11** | slot=`'2026-05-07'`, content `status='approved'`, **moderation_status='pending'** | 0 новых строк. |
| **I12a** | Race против partial unique index напрямую: открыть **два отдельных PG client'a** на pool, оба `BEGIN`, оба `INSERT INTO unic_tasks ... ON CONFLICT (content_id, slot_date) WHERE current_status IN (...) DO NOTHING` для одного и того же `(content_id, slot_date)`. Затем оба commit одновременно. (Codex IMPORTANT #8 — тест проверяет физический index, не app-таймнинг.) | Один INSERT возвращает `rowCount=1`, другой `rowCount=0`. Финально в БД ровно 1 row. |
| **I12b** | Application race: barrier-driven harness. Два инстанса runAutoUnicForDate, оба после SELECT phase ждут на shared barrier, потом одновременно идут к INSERT. | Ровно 1 строка после; counts корректные. |
| **I13** | Migration cleanup: предзагрузить две дубликатные `unic_tasks` ('pending'+'pending') на тот же `(content_id, slot_date)`. Применить миграцию. | Один остался 'pending', другой 'error' с `error_message LIKE '%dedup-by-migration%'`. |

Использовать существующий `engine.dispose` fixture pattern (см. memory `feedback_validator_test_engine_dispose.md` — для validator side; autowarm проверим аналог в `autowarm/tests/conftest.*` или Jest setup).

## Rollout

1. **dev (testbench):** ветка `feature/unic-sweep-2026-05-07` (worktree). Применить миграцию → прогон unit + integration → smoke на seed-данных.
2. **smoke (testbench-stage box):** запустить server.js, подождать 30с → проверить логи `unic-sweep ok target_date=...` и `picked` count > 0 для подложенного слота.
3. **prod migration:** применить миграцию через psql на prod БД (CONCURRENTLY безопасно). Проверить что dedup-cleanup затронул разумное число строк (вероятно 0 или единицы).
4. **prod code:** cherry-pick в prod main → auto-push → `pm2 restart <process>` (имя проверим перед деплоем).
5. **monitoring T+30 мин:** `pm2 logs ... | grep unic-sweep | head -10`. Здоровый сигнал: `picked` падает к 0 после первого тика.
6. **monitoring T+24 ч:** один день с health-metric SQL раз в час. Ожидаем что значение всегда =0 после первого утреннего тика.
7. **rollback кода:** удалить блок sweep + commit → cherry-pick → restart. Уже-enqueued задачи остаются (data side остаётся как есть; это нормально — они валидные).
8. **rollback миграции:** `DROP INDEX CONCURRENTLY ux_unic_tasks_active_slot;` Дедуп нельзя откатить — но он по построению только убирает дубликаты, а не данные.

## Risks (после фикса)

| Риск | Вероятность | Митигация |
|---|---|---|
| Существующий dedup-cleanup в миграции пометит как 'error' нужную запись | Низкая | ORDER BY current_status priority (done > processing > pending) сохраняет «более продвинутую» из двух. Дедуп case-insensitive логируется в `error_message`. |
| ON CONFLICT синтаксис на partial unique index не поддерживается | Низкая (pg ≥9.5 supports) | Тест I12 поймает на dev до прода. Fallback: использовать `INSERT ... WHERE NOT EXISTS (...)` внутри одной транзакции с advisory lock. |
| Sweep-loop работает в нескольких PM2-инстансах одновременно | Средняя (если кластер) | Pre-flight: подтвердить single-instance. Даже при кластере unique index гарантирует корректность; только лишние тики ON CONFLICT. |
| Морин-батч `triggerAutoUnic` после фикса избыточен | Низкая (не баг, оверхед) | Sweep ловит то же подмножество. Удаление morning-batch — отдельный follow-up, чтобы не расширять текущий PR. |
| Новый sweep увеличит DB-нагрузку в 6× (5min vs 30min) | Низкая | Один SELECT с индексом + `runAutoUnicForDate` early-exits на пустом результате. Базы хватит. |

## Open questions для writing-plans

| Q | Что проверить |
|---|---|
| **Q1** | ~~Синтаксис `ON CONFLICT`~~ ✅ resolved: `ON CONFLICT (cols) WHERE <predicate> DO NOTHING` (index-inference, не constraint-name). Pg ≥ 9.5 поддерживает. |
| **Q2** | Имя PM2-процесса прод-сервера (`pm2 list` на VPS). Имя файла server.js — он же `delivery` или `autowarm-server`? |
| **Q3** | Удалять ли `triggerAutoUnic` (line 5500–5555) после стабилизации sweep'а? Не сейчас. Через 2 недели логов смотрим overlap; если sweep ловит всё, что ловил morning-batch — удаляем отдельным PR. |
| **Q4** | Существуют ли уже unit-тесты на `runAutoUnicForDate` в `autowarm/tests/`? Если есть — использовать fixture-pattern; если нет — создать с нуля. |
| **Q5** | Есть ли `parsing_logs`-аналог для structured log-стрима в autowarm? Если есть — INSERT в неё дополнительно к console; если нет — только JSON-в-stdout (его pm2 уже агрегирует). |
| **Q6** | Pre-flight на проде: запустить audit_unic_tasks_duplicates.sql ПЕРЕД миграцией. Если результат непустой — миграция блокируется до ручного резолва ops'ом. |

## Decisions captured (этой сессии)

- Подход #1 (cron + сохраняем trigger-immediate) — выбран
- Backfill: только today, прошлые дни — клиенты вручную
- Cron interval: 5 минут
- Sweep target: **[business_today, business_yesterday]** (grace window для midnight rollover)
- DST: используем `Intl.DateTimeFormat` (не fixed offsets) — корректно для всех IANA-TZ
- ON CONFLICT: index-inference syntax (`ON CONFLICT (col1, col2) WHERE <predicate> DO NOTHING`)
- Migration: read-only audit script + ручной резолв дублей + чистая `CREATE INDEX CONCURRENTLY` миграция (без in-line cleanup)
- Codex review iterations:
  - v1: 2 BLOCKER + 10 IMPORTANT + 5 MINOR — переписали v2
  - v2: 3 BLOCKER + 7 IMPORTANT + 2 MINOR — применили инлайн-патчем (v3 = текущий документ)
  - Открытые из v2-ревью: MINOR #11 (start/stop exports — учтено в Change 2), MINOR #12 (consistent JSON logs — учтено)
