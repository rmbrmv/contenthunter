# Sub-project A — Scheduler→Uniqueness Pickup Sweep

**Date:** 2026-05-07
**Author:** brainstorming session (Claude Opus 4.7 + Danil)
**Status:** Design — pending implementation plan

## Problem

Клиенты планируют контент в `client.contenthunter.ru/scheduler`, но запланированные видео не подбираются на этап уникализации и поэтому не доходят до публикации. Production-блокер.

### Root cause (подтверждён по коду)

Pipeline сегодня:

1. Validator при approve контента вызывает webhook
   `POST http://localhost:3848/api/unic/trigger-immediate {"content_id": <id>}`
   (`validator-contenthunter/backend/src/services/delivery_webhook.py:14-37`)
2. autowarm `/api/unic/trigger-immediate` (`autowarm/server.js:5299-5344`) выполняет
   ```sql
   SELECT ... FROM validator_schedule_slots s
   JOIN validator_content c ON c.id = s.content_id
   WHERE s.content_id = $1
     AND s.slot_date = $today           -- ← timezone-aware, GMT+4
     AND s.status = 'filled'
     AND c.status = 'approved'
     AND c.moderation_status = 'passed'
     AND NOT EXISTS (... unic_tasks ...)
   ```
3. Если строка нашлась → вызывает `runAutoUnicForDate(today, settings)` —
   INSERT в `unic_tasks` + UPDATE `validator_content.status='in_uniqualization'`.
4. Если не нашлась → `triggered=false`, тихо выходит.

`unic-worker` (`autowarm/unic-worker/worker.py:67-74`) поллит `unic_tasks WHERE current_status='pending'` каждые 3 секунды — игнорируя `slot_date`. То есть worker сам по себе работает корректно, но **никто не положит запись в `unic_tasks`, если на момент approve `slot_date != today`**.

`assignUnicResultsToQueue` (`autowarm/server.js:5784`) — `setInterval(..., 30 * 60 * 1000)` — это уже `unic_results → publish_queue`. До него очередь даже не доходит.

Никакого ежедневного крона на `runAutoUnicForDate(today)` нет. Поэтому:

| Сценарий | Сегодня |
|---|---|
| approve в день slot_date | ✅ работает (trigger-immediate матчится) |
| approve **раньше** slot_date | ❌ trigger=false; больше никто не дёрнет |
| approve **позже** slot_date | ❌ trigger=false; per-policy не лечим |

## Goals

- Любой `(approved + filled)` слот на сегодняшнюю дату должен попасть в `unic_tasks` максимум через 5 минут после того, как оба условия выполнены.
- In-day flow (upload до 15:00 → approve → публикация сегодня) сохраняется без регрессии — мгновенный отклик через `trigger-immediate` остаётся.
- Без новых таблиц, миграций, изменений в validator-стороне.

## Non-goals

- Не лечим стрэндед-слоты прошлых дней. Per user policy: клиенты переносят вручную.
- Не делаем cancellation удалённого контента (это под-проект C).
- Не enqueue'им future-слоты (это пересекается с C — отложенное состояние требует отмены).
- Не меняем `trigger-immediate` или validator-сторону.

## Approach

Один `setInterval` в `autowarm/server.js`, рядом с существующим `assignUnicResultsToQueue`. Тикает каждые **5 минут**. Внутри вызывает существующую `runAutoUnicForDate(today, settings)` — функция уже идемпотентна благодаря `NOT EXISTS (... unic_tasks ...)`.

```
[validator approve] ─trigger-immediate─→ [autowarm runAutoUnicForDate(today)] ──→ unic_tasks
                                                  ▲
                              (NEW) every 5 min ──┘  ← закрывает gap для approve != slot_date
```

### Pseudo-code

```javascript
// autowarm/server.js, рядом со строкой 5784

let unicSweepRunning = false;

async function runScheduledUnicSweep() {
  if (unicSweepRunning) {
    console.log('[unic-sweep] previous tick still running, skipping');
    return;
  }
  unicSweepRunning = true;
  const t0 = Date.now();
  try {
    const settings = await loadAutoUnicSettings();
    const result = await runAutoUnicForDate(/* today */ null, settings);
    console.log(
      `[unic-sweep] ok picked=${result.picked} skipped=${result.skipped} ` +
      `took=${Date.now() - t0}ms`
    );
  } catch (e) {
    console.error('[unic-sweep] error:', e);
  } finally {
    unicSweepRunning = false;
  }
}

setInterval(runScheduledUnicSweep, 5 * 60 * 1000);
// один immediate tick через 30 сек после старта сервера, чтобы не ждать первые 5 мин:
setTimeout(runScheduledUnicSweep, 30 * 1000);
```

`runAutoUnicForDate` уже принимает `targetDate` и сама вычисляет `today` если null — нужно проверить контракт во время реализации; если сигнатура иная — передаём явный `today` тем же способом, что и trigger-immediate.

### Re-entrancy guard

`unicSweepRunning` boolean. Если предыдущий тик ещё в работе (медленный SQL, deadlock, длинный JOIN) — пропускаем текущий, чтобы не получить два конкурирующих INSERT. Дубликаты и так защищены SQL-ом (`NOT EXISTS`), но guard уменьшает нагрузку и шум в логах.

### Initial backfill

Отдельный скрипт **не нужен**. Первый `setTimeout` через 30 сек после деплоя — это и есть backfill для сегодняшних застрявших слотов. Идемпотентность гарантирована.

## Error handling

- Per-slot ошибки уже ловит `runAutoUnicForDate` внутри (по существующей логике). Ничего нового.
- На уровне sweep: `try/catch` + `console.error('[unic-sweep] error:', e)`. Не падать процесс. Следующий тик попробует снова.
- Если БД недоступна → `runAutoUnicForDate` бросит, sweep залогирует, продолжит. Без ретраев — следующий тик через 5 мин.

## Observability

- Console-логи в PM2 outputs (формат `[unic-sweep] ok picked=N skipped=M took=Xms`).
- Метрика для мониторинга: количество `[unic-sweep] picked > 0` в час. Если вдруг растёт — это сигнал что trigger-immediate перестал работать или клиенты массово approve'ят за день вперёд.
- Если в `autowarm` есть централизованная таблица логов (`parsing_logs` или аналог) — добавить туда запись с `tag='unic_sweep'`. Проверим во время реализации; если нет — оставляем только console.

## Testing (TDD)

Integration-тесты против real testbench DB (без mocks). Pattern проверим в `autowarm/tests/` во время реализации (Jest или Mocha).

| Тест | Setup | Expect |
|---|---|---|
| **T1** | slot=`today`, content `approved+passed`, нет записи в `unic_tasks` (имитируем «approve вчера, slot сегодня») | После одного тика: 1 запись в `unic_tasks` с этим `content_id`, `slot_date=today`, `current_status='pending'` |
| **T2** | slot=`today`, content `approved+passed`, **уже есть** `unic_tasks` row с `current_status='pending'` | После тика: количество строк не изменилось (idempotency) |
| **T3** | slot=`today+1` (завтра), content `approved+passed` | После тика: 0 новых строк (sweep смотрит только today) |
| **T4** | slot=`today-1` (вчера), content `approved+passed` | После тика: 0 новых строк |
| **T5** | Re-entrancy: `unicSweepRunning=true` (имитируем длинный предыдущий тик) → вызываем `runScheduledUnicSweep` | Лог `previous tick still running, skipping`; функция возвращается без вызова `runAutoUnicForDate` |
| **T6** | DB недоступна (моким `runAutoUnicForDate` чтобы бросить) | Sweep пишет error в console и не падает; `unicSweepRunning` сбрасывается |

Использовать seed-данные из существующего testbench. Проверить через `git grep` есть ли уже тесты на `runAutoUnicForDate` — переиспользовать fixtures.

## Rollout

1. **dev (testbench):** реализация в `autowarm-testbench/server.js`, прогон тестов локально.
2. **smoke:** на seed-данных создать слот `today` + approved content **без** `unic_tasks` row → подождать 30 сек → проверить что тик создал запись.
3. **prod:** cherry-pick в prod main → auto-push hook доставит на VPS → `pm2 restart <autowarm-server-process>` (имя процесса проверим через `pm2 list` перед деплоем; вероятно `autowarm-server` или `delivery`).
4. **monitoring (T+30 мин):** смотрим логи `pm2 logs <process> | grep unic-sweep`, считаем `picked` за первые тики. Если `picked > 0` на первом тике после деплоя — backfill отработал.
5. **monitoring (T+24 ч):** проверить что новые approve'ы за день вперёд начинают подбираться.
6. **rollback:** удалить `setInterval` + commit → cherry-pick. Никаких миграций откатывать не надо.

## Risks

| Риск | Вероятность | Митигация |
|---|---|---|
| Конкурентный INSERT trigger-immediate vs sweep даст дубликат в `unic_tasks` | Низкая | SQL-уровень: `NOT EXISTS` уже защищает. Guard на JS-уровне — дополнительная защита от лишней работы, не корректности. |
| `runAutoUnicForDate` медленнее 5 мин при большом backlog | Низкая | Re-entrancy guard скипает следующий тик. На реальных объёмах (десятки слотов/день) функция отработает за секунды. |
| Sweep делает лишнюю работу даже когда trigger-immediate всё подобрал | Низкая (не баг — оверхед) | NOT EXISTS возвращает 0 строк → `runAutoUnicForDate` отработает мгновенно (один SELECT, ноль INSERT). |
| После рестарта server.js окно `[start, start+30s]` без sweep | Низкая | `setTimeout(runScheduledUnicSweep, 30000)` — один immediate tick. |
| Имя процесса PM2 / расположение `runAutoUnicForDate` отличается от описания | Средняя (по памяти, не свежим kодом) | Pre-flight на этапе реализации: `pm2 list`, `grep -n "runAutoUnicForDate" server.js`. |

## Open questions для этапа реализации

- Точная сигнатура `runAutoUnicForDate(targetDate, settings)` — принимает ли null или нужно явно `today`? (Пре-флайт grep.)
- Существует ли `loadAutoUnicSettings()` или settings приходят из другого места? (Пре-флайт.)
- Имя PM2-процесса: `autowarm-server`, `delivery`, или иное? (Пре-флайт `pm2 list`.)
- Существует ли `parsing_logs`-аналог в autowarm для structured-логов? (Пре-флайт `\dt` в БД.)

Эти вопросы не блокируют дизайн — это runtime-детали. Решаются на этапе writing-plans.
