# Sub-project A — Scheduler→Uniqueness Pickup Sweep

**Date:** 2026-05-07
**Status:** Design — pending implementation plan
**Revision:** v2 (post-Codex review)

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

Файл: `autowarm/migrations/<next>_unic_tasks_unique_active_slot.sql`

```sql
-- Cleanup any pre-existing duplicates first (defensive — production may already have some)
WITH ranked AS (
  SELECT id, content_id, slot_date, current_status,
         ROW_NUMBER() OVER (
           PARTITION BY content_id, slot_date
           ORDER BY (current_status='done') DESC,
                    (current_status='processing') DESC,
                    (current_status='pending') DESC,
                    id ASC
         ) AS rn
  FROM unic_tasks
  WHERE content_id IS NOT NULL
    AND slot_date IS NOT NULL
    AND current_status IN ('pending','processing','done')
)
UPDATE unic_tasks SET current_status = 'error',
                     error_message = COALESCE(error_message,'') || ' [dedup-by-migration]'
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- The actual constraint
CREATE UNIQUE INDEX CONCURRENTLY ux_unic_tasks_active_slot
  ON unic_tasks (content_id, slot_date)
  WHERE current_status IN ('pending','processing','done')
    AND content_id IS NOT NULL
    AND slot_date IS NOT NULL;
```

Partial unique index: пока задача жива (`pending|processing|done`), нельзя создать вторую с тем же `(content_id, slot_date)`. После `error` — можно повторно (например, sweep подберёт после ручного reset). `CONCURRENTLY` — без долгого блока на проде.

### Change 2 — добавить sweep-loop в `autowarm/server.js`

Self-scheduling recursive `setTimeout` (стабильнее `setInterval` под event-loop задержками — Codex MINOR #17). Date вычисляется явно (Codex BLOCKER #2). INSERT защищён `ON CONFLICT DO NOTHING` поверх нового индекса (Codex BLOCKER #1).

```javascript
// autowarm/server.js, новый блок после строки 5555 (рядом с setInterval(triggerAutoUnic))

const UNIC_SWEEP_INTERVAL_MS = 5 * 60 * 1000;
const UNIC_SWEEP_INITIAL_DELAY_MS = 30 * 1000;
let unicSweepRunning = false;
let unicSweepTimer = null;

function computeBusinessToday(timezone) {
  const tzOffsets = {
    'Asia/Dubai': 4, 'Europe/Moscow': 3, 'UTC': 0,
    'Europe/London': 0, 'America/New_York': -5, 'Asia/Bangkok': 7,
  };
  const offset = tzOffsets[timezone] ?? 4;
  return new Date(Date.now() + offset * 3600000).toISOString().slice(0, 10);
}

async function runScheduledUnicSweep() {
  if (unicSweepRunning) {
    console.warn('[unic-sweep] previous tick still running; skipping');
    scheduleNextSweep();
    return;
  }
  unicSweepRunning = true;
  const t0 = Date.now();
  let targetDate = null;
  let pickedBefore = 0, pickedAfter = 0;
  try {
    const { rows } = await pool.query('SELECT * FROM unic_settings WHERE id=1');
    const settings = rows[0] || {};
    targetDate = computeBusinessToday(settings.timezone);

    const { rows: before } = await pool.query(
      `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE slot_date=$1`, [targetDate]);
    pickedBefore = before[0].n;

    await runAutoUnicForDate(targetDate, settings);

    const { rows: after } = await pool.query(
      `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE slot_date=$1`, [targetDate]);
    pickedAfter = after[0].n;

    console.log(JSON.stringify({
      tag: 'unic-sweep',
      ok: true,
      target_date: targetDate,
      picked: pickedAfter - pickedBefore,
      took_ms: Date.now() - t0,
    }));
  } catch (e) {
    console.error(JSON.stringify({
      tag: 'unic-sweep',
      ok: false,
      target_date: targetDate,
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

// kickoff
setTimeout(runScheduledUnicSweep, UNIC_SWEEP_INITIAL_DELAY_MS);
```

И **минимальный патч в `runAutoUnicForDate`** на line 5456: добавить `ON CONFLICT (content_id, slot_date) WHERE current_status IN ('pending','processing','done') DO NOTHING` к INSERT'у. Это защищает оба пути (trigger-immediate и sweep) от race без меняния логики выше.

```javascript
// line 5456 (изменение), оставшийся UPDATE validator_content только если INSERT действительно произошёл
const { rowCount } = await pool.query(`
  INSERT INTO unic_tasks
    (input_video_url, input_video_name, project_name, schemes, schemes_total,
     current_status, project_id, content_id, slot_date, meta, created_at, updated_at)
  VALUES ($1,$2,$3,$4,$5,'pending',$6,$7,$8,$9,NOW(),NOW())
  ON CONFLICT ON CONSTRAINT ux_unic_tasks_active_slot DO NOTHING
`, [...]);

if (rowCount > 0) {
  await pool.query(
    `UPDATE validator_content SET status='in_uniqualization', unic_queued_at=NOW(), updated_at=NOW() WHERE id=$1`,
    [slot.content_id]
  );
  console.log(`[auto-unic] ✅ task created: slot=${slot.slot_id} ...`);
} else {
  console.log(`[auto-unic] skipped (race-conflict): slot=${slot.slot_id} content=${slot.content_id}`);
}
```

(Уточнение по `ON CONFLICT ON CONSTRAINT <partial-unique-index>` — синтаксис в pg допускает `ON CONFLICT (content_id, slot_date) WHERE current_status IN (...)`; точная форма проверится тестом перед применением.)

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

Health-метрика: `SELECT COUNT(*) FROM validator_schedule_slots s JOIN validator_content c ON c.id=s.content_id WHERE s.slot_date=CURRENT_DATE AND s.status='filled' AND c.status='approved' AND c.moderation_status='passed' AND NOT EXISTS (SELECT 1 FROM unic_tasks ut WHERE ut.content_id=c.id AND ut.slot_date=s.slot_date AND ut.current_status IN ('pending','processing','done'))` — сколько слотов на сегодня всё ещё не enqueued. Это alert-source: ожидаемо 0 после первого тика.

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
| **I12** | Concurrency: запустить два `runAutoUnicForDate(today, settings)` параллельно (Promise.all) на одном content_id | После: ровно 1 строка в `unic_tasks` (защита через unique constraint + ON CONFLICT). Второй вызов пишет skip-лог. |
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
| **Q1** | Точный синтаксис `ON CONFLICT` на partial unique index в Postgres. Сделать smoke-test на pg ≥ 13 локально (testbench) до миграции прода. |
| **Q2** | Имя PM2-процесса прод-сервера (`pm2 list` на VPS). Имя файла server.js — он же `delivery` или `autowarm-server`? |
| **Q3** | Удалять ли `triggerAutoUnic` (line 5500–5555) после стабилизации sweep'а? Решить через 1–2 недели после деплоя на основе логов. Сейчас оставляем как backup. |
| **Q4** | Существуют ли уже unit-тесты на `runAutoUnicForDate` в `autowarm/tests/`? Использовать существующий fixture-pattern. |
| **Q5** | Есть ли `parsing_logs`-аналог для structured log-стрима в autowarm? Если есть — INSERT в неё дополнительно к console; если нет — только JSON-в-stdout. |

## Decisions captured (этой сессии)

- Подход #1 (cron + сохраняем trigger-immediate) — выбран
- Backfill: только today, прошлые дни — клиенты вручную
- Cron interval: 5 минут
- Codex review v1: 2 BLOCKER + 10 IMPORTANT + 5 MINOR — все BLOCKER и большинство IMPORTANT учтены в этой ревизии. Подробности в `.codex-review-2026-05-07-A-v1.txt` (если решим коммитить артефакт).
