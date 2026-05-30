# 2026-05-30 — Авто-выкладка встала: queued-брони душили диспатч → busy = in_progress only

## Симптом
За 30.05 создано **4 publish-задачи** против ~220/день (28.05=326, 29.05=224). В очереди `publish_queue` на 30.05 — 319 pending-слотов (04:00–09:00 UTC, давно просрочены), все висят `pending`. В логах id35 на каждый слот: `[dispatch-queue] pq=… device=… занят, откладываем`.

Данил: в UI «Статусы телефонов» занято **только 3 телефона** — почему встало всё?

## Разведка (БД-контейнер 172.17.0.3 = localhost:5432)
- Источник «занятости» — `validator_manual_publish_queue`. Активных (`cancelled_at IS NULL`) на 30.05: **161 `queued` на 24 устройствах + 3 `in_progress`** = 26 уникальных busy-устройств.
- **Все 164 строки — с `planned_date` в ПРОШЛОМ** (past=164, today=0, future=0). Брошенные ручные брони (оператор так и не выложил), копились с 21–26.05.
- Из 48 устройств с pending-слотами сегодня: **22 заблокированы прошлыми `queued`, 0 — живыми (today/future) бронями**.

## Корневая причина
`fetchBusyDevices` / `insertPublishTaskRaceSafe` (`server.js`) считали устройство занятым по `operator_status IN ('queued','in_progress')` (WP#183 iter2). `queued` = «зарезервировано/ожидает ручной выкладки», НЕ «телефон физически занят». Брошенные `queued` без срока годности накапливались и помечали телефоны занятыми навечно.

**Расхождение с UI:** таблица «Статусы телефонов» (`phone_status.js`) считает busy только `in_progress` → показывала честные 3. Диспетчер считал `queued`+`in_progress` → 26. Разница = баг диспетчера.

## Тайминг (регрессия деплоя)
Прод id35 рестартнут `pm2 restart --update-env` **29.05 20:42 UTC** → подхватил код/флаг, активировавший `queued`-блокировку. Доказательство: 28.05 **242/326** и 29.05 **110/224** задач шли на устройства, которые СЕЙЧАС заблокированы (те же `queued`-строки существовали и тогда — 678 строк до рестарта). До рестарта диспатч их игнорировал, после — встал.

## Фикс (iter3, решение Данила — Вариант 3)
busy = **только `operator_status = 'in_progress'`** в обеих функциях. `queued` больше не блокирует. Совпадает с UI. Kill-switch `MANUAL_INPROGRESS_BLOCKS_AUTO_DISPATCH_ENABLED` без изменений.

Диффы (`server.js`):
- `fetchBusyDevices`: manual-ветка UNION `… WHERE operator_status = 'in_progress' AND cancelled_at IS NULL …`
- `insertPublishTaskRaceSafe`: `WHERE NOT EXISTS (… operator_status = 'in_progress' AND cancelled_at IS NULL)`
- Док-блоки + 3 iter2-теста развёрнуты под новое поведение.

## Качество
- TDD: 3 теста развёрнуты (queued НЕ блокирует / partial-группа без in_progress НЕ блокирует / race-safe INSERT проходит при queued) — red→green.
- **11/11 GREEN**, `codex review` — 0 P1 («No discrete correctness issues; change consistently applied»).
- Живое подтверждение: прогон зелёного теста (импортирует `../server`, стартует реальный dispatch-loop против боевой БД) раздиспатчил 14 реальных слотов на освобождённые телефоны → busy схлопнулся 31→17 (остаток = реально in-flight задачи).

## SHIPPED+DEPLOYED 2026-05-30
- main `delivery-contenthunter` `87387a8` (FF от `137b70d`).
- Прод-чекаут `/root/.openclaw/workspace-genri/autowarm`: `git pull --ff-only origin main` → HEAD `87387a8`.
- `sudo pm2 restart 35` (restarts 34, 18:48 UTC). После рестарта: `[dispatch-queue] 50 задач к запуску`, троттлинг только по легитимному per-Pi concurrency 3/3, queued-блокировки нет.

## ⚠️ Второй слой (обнаружен при verify деплоя) — зомби-диспетчер
После рестарта прод id35 (с фиксом) диспатч ВСЁ РАВНО не шёл: 20 минут «`[dispatch-queue] 50 задач к запуску`» → полная тишина, 0 `✅`/`❌`, слоты клеймились в `running` без `publish_task_id`.

**Причина:** осиротевший зомби-процесс `node --test test_dispatch_manual_guard.test.js` (pid 837270, ppid=1, работал 25ч, cwd = удалённый worktree `…autowarm-testbench-feat-wp187-published-auto-20260529 (deleted)`). Тест импортирует `server.js`, который поднимает СВОЙ фоновый `dispatchPublishQueue`-loop по боевой БД. Зомби перехватывал D4-advisory-lock claim'ы (`pending→running`), а прод id35 получал в guard `{claimed:false, race:true}` → **тихий `continue` без лога** (server.js:6399-6402). Отсюда «50 задач→тишина».

**Лечение:** `kill -9 837270` (19:06) + сброс застрявших `running`-без-task слотов → `pending`. **Следующий же цикл (19:08:41) раздиспатчил 46 задач** на ранее-заблокированные устройства (RFGYC31P26P, RF8Y80ZTVFZ, RFGYA19DNGZ, RFGYB07Y5TJ…). ОЖИВЛЕНО ПОДТВЕРЖДЕНО 30.05 19:10: pending 319→266 дренажирует, 11 живых `publisher.py`, 0 застрявших.

**Follow-up (бэклог):** `downloadMedia` (server.js:6772) — `proto.get` БЕЗ socket-timeout. Висящий медиа-хост заморозил бы весь dispatch-loop (try/catch на строке 7062 ловит reject, но НЕ ханг). Сегодня хост работал (HEAD 200/3.2с), но добавить timeout+abort обязательно. Также: stale `node --test`, импортирующие `server.js`, = конкурирующие dispatch-loop'ы по проду → не оставлять зомби (см. `feedback_stale_node_test_processes`).

## Остаток
- 3 `in_progress`, один с 21.05 — брошен оператором, держит 1 телефон занятым; почистить одним UPDATE (не блокер).
- 161 `queued` теперь безвредны (не блокируют). Опциональная гигиена — отдельный expiry/cleanup для брошенных `queued` (зеркало WP#155).

## Урок
«Зарезервировано/в очереди» ≠ «ресурс занят». Гард занятости должен опираться на признак РЕАЛЬНОЙ активности (`in_progress`), иначе брошенные брони копятся и душат пайплайн. Определение busy в бэкенде сверять с оперским UI.
