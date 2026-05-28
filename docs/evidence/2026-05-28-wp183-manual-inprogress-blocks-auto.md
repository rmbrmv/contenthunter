# WP #183 — `manual operator_status='in_progress'` блокирует автодиспатч на том же `device_serial`

**Статус:** код готов в ветке `fix/wp-manual-inprogress-blocks-auto` (worktree autowarm-testbench), 64/64 тестов GREEN, codex review pending, PR/деплой ждут согласования.

## Что было не так

- Диспатчер автовыкладки `dispatchPublishQueue()` в `autowarm-testbench/server.js` вычислял множество «занятых устройств» только из `publish_tasks(status IN ('pending','running','delegated'))`.
- Ручная очередь `validator_manual_publish_queue` (WP#107 / WP#128) — отдельная таблица. При «Взять в работу» (`manual_publish_queue.js:78-85` `takeItem`, `:166-180` `takeGroup`) обновляется `operator_status='in_progress', taken_at`, в `publish_tasks` ничего не появляется.
- Следствие: оператор начинает работать на телефоне X → автодиспатч на этом же `device_serial` продолжает диспатчить → ADB-конфликт / порча сценария оператора.
- Существующая защита `slotIsEffectivelyManual` (WP#125, `server.js:6156`, `client_manual_filter.js:27`) отменяет автозадачу только когда слот/проект помечены `manual_publish=true` целиком. Ситуацию «оператор лично взял конкретную задачу» она не покрывает.

## Что сделано

### Код (`autowarm-testbench`, ветка `fix/wp-manual-inprogress-blocks-auto`)

**Слой 1: snapshot-проверка через `fetchBusyDevices(client)`** (рядом с `isPiConcurrencyLimitReached`, экспортирован):

  ```sql
  -- ветка по умолчанию (MANUAL_INPROGRESS_BLOCKS_AUTO_DISPATCH_ENABLED != 'false')
  SELECT DISTINCT device_serial FROM publish_tasks
    WHERE status IN ('pending','running','delegated')
      AND device_serial IS NOT NULL AND device_serial <> ''
  UNION
  SELECT DISTINCT device_serial FROM validator_manual_publish_queue
    WHERE operator_status = 'in_progress'
      AND cancelled_at IS NULL
      AND device_serial IS NOT NULL AND device_serial <> '';
  ```

  Kill-switch `MANUAL_INPROGRESS_BLOCKS_AUTO_DISPATCH_ENABLED='false'` оставляет только первую ветку (старое поведение). `dispatchPublishQueue()` (бывший инлайн-`busyDevices`) заменён на `const busy = await fetchBusyDevices(pool);`.

**Слой 2 (P2.1 codex review): атомарный INSERT-гард через `insertPublishTaskRaceSafe(client, fields)`** — закрывает race-окно между snapshot и INSERT в publish_tasks:

  ```sql
  INSERT INTO publish_tasks (...)
  SELECT $1,$2,...,$14
  WHERE NOT EXISTS (
    SELECT 1 FROM validator_manual_publish_queue
    WHERE device_serial = $1
      AND operator_status = 'in_progress'
      AND cancelled_at IS NULL
  )
  RETURNING id;
  ```

  Если `RETURNING` пуст → возвращает `null` → `dispatchPublishQueue` логирует `pq=X race: manual in_progress зашёл на device=Y после snapshot, откат` и откатывает publish_queue → pending + bump scheduled_at +5 мин.
  Kill-switch тот же `MANUAL_INPROGRESS_BLOCKS_AUTO_DISPATCH_ENABLED` (single switch для обоих слоёв).

### TDD (`tests/test_manual_inprogress_blocks_dispatch.test.js`, 9 тестов)

`fetchBusyDevices` (слой 1):

1. `publish_tasks(pending)` → device в `busy` (sentinel — не сломали базовую ветку).
2. `validator_manual_publish_queue(operator_status='in_progress')` → device в `busy`.
3. `operator_status='queued'` (не взято в работу) → device НЕ в `busy`.
4. `operator_status='published'` (завершено) → device НЕ в `busy`.
5. `device_serial = NULL/''` → отфильтрован.
6. Kill-switch `=false` → manual queue игнорируется, `publish_tasks` продолжает учитываться.

`insertPublishTaskRaceSafe` (слой 2):

7. manual `in_progress` на том же device → `INSERT` блокирован, helper возвращает `null`.
8. на «свободном» device → `INSERT` проходит, возвращает `id`.
9. Kill-switch `=false` → гард выключен, `INSERT` проходит даже при manual `in_progress`.

Также обновлён `test_client_publish_id.test.js` (WP#108/#147 source-contract): после рефакторинга INSERT в helper, контракт «`client_publish_id` не теряется» разнесён на (a) helper-body и (b) передачу `item.client_publish_id` в вызов helper из `dispatchPublishQueue`.

Фикстуры (`PID=9912600`, `SLOT=9912600`, `MPQ_BASE=9912600`) изолированы от остальных suites, использован house-style prefix `WPBLOCK_*` в `device_serial`.

### Verify

- Suite WP#183: **9/9 GREEN**.
- Регресс-сосед: `tests/test_dispatch_publish_queue_concurrency.test.js`, `test_dispatch_manual_guard.test.js`, `test_client_manual_filter.test.js`, `tests/test_manual_publish_queue.test.js`, `test_manual_publish_queue.test.js`, `tests/test_manual_queue_assign.test.js`, `test_client_publish_id.test.js` — **60/60 GREEN, 0 регрессий**.
- Итого: **69/69 pass, 0 fail**.

### codex review (1-й раунд, `codex review --uncommitted` через stdin-обход)

- **0 P1**.
- **P2.1**: «atomic race-safe INSERT» — **закрыто** в этом же PR (helper `insertPublishTaskRaceSafe` + WHERE NOT EXISTS + откат publish_queue в pending + bump 5 мин).
- **P2.2**: «side-effect-ful test import (`require('../server')`)» — **follow-up tech-debt всего тестбенча** (тот же паттерн у `test_dispatch_manual_guard.test.js` и др.). Не блокирующее.

## Что осталось

- Коммит на `fix/wp-manual-inprogress-blocks-auto`, push в `GenGo2/delivery-contenthunter`, PR в `main`.
- Деплой: PM2 подхватит после `git pull` — миграций нет, только code change + env-flag (`MANUAL_INPROGRESS_BLOCKS_AUTO_DISPATCH_ENABLED`, default=on).
- Прод-smoke 24ч:
  - оператор берёт реальную задачу в работу → диспатчер логирует `[dispatch-queue] pq=… device=… занят, откладываем` для других pending в том же `device_serial`;
  - при race (оператор берёт задачу между snapshot и INSERT) — лог `[dispatch-queue] pq=… race: manual in_progress зашёл на device=… после snapshot, откат`;
  - счётчик «авто+ручная одновременно на одном device» = 0.
- Follow-up (codex P2.2): вынести `fetchBusyDevices` / `insertPublishTaskRaceSafe` в отдельный side-effect-free модуль `dispatch_busy.js`, чтобы юнит-тесты могли требовать только helper-модуль, не запуская фоновых loops `server.js`. Это общий tech-debt тестбенча (тот же паттерн у `test_dispatch_manual_guard.test.js` и др.), отдельная задача.
- Возможно тот же гейт нужен и в соседних путях диспатча (`handleTriggerImmediate` / testbench-публикатор). Pending до WP-разведки.
