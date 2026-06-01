# Вытеснение автовыкладки при «Взять в работу» + UX освобождения телефона

**Дата:** 2026-06-01
**Контекст:** follow-up WP#209/#183 (фарминг- и publish-гейты по `operator_status='in_progress'`)
**Репозитории:** код — `delivery-contenthunter` (autowarm, pm2 #35); спека — `contenthunter`

## Проблема

Гейты WP#183/#209 — **превентивные**: не дают НОВЫМ авто-действиям (publish, фарминг)
стартовать на телефоне, который оператор уже взял в работу (`in_progress`). Но они
**не прерывают** авто-задачу, которая уже бежит на телефоне в момент взятия.

Кнопка «Взять в работу» (`takeItem`/`takeGroup` в `manual_publish_queue.js`) — это чистый
`UPDATE operator_status='in_progress'`; она не проверяет и не останавливает бегущий
`publisher.py`. Тот продолжает гонять телефон через ADB до естественного завершения.

**Замер (7 дней):** 48 из 312 взятий (15,4%, сегодня 24%) попали на телефон с уже бегущей
автовыкладкой. Ожидание освобождения: медиана 7,4 мин, среднее 15,6 мин, максимум 68,8 мин.
Всё это время оператор и автопубликатор дерутся за один телефон по ADB. Операторы жалуются,
что «заходят на телефон, а там хозяйничает автовыкладка».

## Цель

1. При «Взять в работу» — **вытеснять** (preempt) бегущую автовыкладку на этом телефоне,
   освобождая его за секунды вместо минут.
2. Показывать оператору честное состояние **«телефон освобождается…»** (спиннер + элапсед-таймер),
   пока телефон реально не свободен, с блокировкой действий платформы до готовности.

Не цель (YAGNI): мультидевайс-вытеснение (пак = всегда 1 телефон, проверено: 433/433 недавних
пака имеют ровно 1 `device_serial`); эскалация неубиваемых задач; авто-сброс зависших `in_progress`
(отдельная тема).

## Поведение (UX)

Оператор жмёт «Взять в работу» на паке, телефон которого занят авто:

```
┌─────────────────────────────────────────────┐
│ Пак #18363 · @clickbriz · TikTok · 📱 SM-A175 │
│  🔄  Телефон освобождается…                   │
│      идёт остановка автовыкладки · 12 сек     │
│  [Выложить] [На доработку]   ← заблокированы  │
└─────────────────────────────────────────────┘
        ↓ авто-процесс умер, телефон свободен
┌─────────────────────────────────────────────┐
│ Пак #18363 · ✅ В работе — телефон готов      │
│  [Выложить] [На доработку]   ← активны        │
└─────────────────────────────────────────────┘
```

- Спиннер + элапсед-таймер, тикающий клиентски от `taken_at`.
- Кнопки платформ (Выложить / На доработку) заблокированы, пока `device_auto_busy=true`.
- Если авто на телефоне не было — карточка сразу «В работе, готов», без спиннера.

## Архитектура (3 части)

### (A) Вытеснение — `scheduler.js`

Scheduler владеет child-процессом авто-задачи (`running`-Map: `publish:<id>` →
`{pid, device_serial, child, ...}`) и его exit-обработчиком, поэтому вытеснение живёт здесь
(иначе гонка статусов: мы ставим `pending`, а exit-обработчик пишет `failed`).

Новая экспортируемая `preemptForDevice(deviceSerial, claimedUnicResultId)`:

1. Найти в `running`-Map все entry с `type==='publish' && device_serial===deviceSerial`.
2. Для каждой: пометить `entry.preempting = true`, послать `child.kill('SIGTERM')`;
   через `PREEMPT_SIGKILL_GRACE_MS` (~15с) — если процесс жив, `SIGKILL`.
3. **Судьба в БД — в exit-обработчике** (он уже срабатывает на смерть child; читает флаг `preempting`):
   - если `(unic_result_id, platform)` задачи совпадает с `claimedUnicResultId`-паком,
     взятым/выложенным оператором вручную → **cancel**:
     `UPDATE publish_tasks SET status=<терминальный>, error_class='preempted_by_manual'`
     (анти-двойная-публикация). **Требование:** статус должен ИСКЛЮЧАТЬ авто-ретрай
     (иначе double-post вернётся через retry-механизм); выбор `failed` vs `cancelled`
     и проверка retry-путей — в плане. Также пометить upstream `publish_queue`-строку
     (по `publish_task_id`), чтобы её не передиспатчили заново.
   - иначе → **requeue**: `UPDATE publish_tasks SET status='pending', started_at=NULL`
     (другой проект — стартует позже; гейт `in_progress` держит до отпускания телефона).
   - В обоих случаях НЕ засчитывать как «честный фейл публикации» (preempted ≠ ошибка).
4. Задачи **без in-memory handle** (status `delegated`, или процесс спавнил другой инстанс,
   напр. testbench-публикатор #33) убить нельзя → `killTask` вернёт false → НЕ трогаем БД,
   оставляем доживать; `device_auto_busy` честно остаётся `true`, спиннер крутится.

`preemptForDevice` возвращает `{ killed: [ids], skipped_no_handle: [ids] }` для логов/ответа.

### (B) Триггер — роут-хендлеры take (`server.js`)

У `server.js` есть и `mpq`, и `scheduler`. После успешного claim:

- `/api/publishing/manual-queue/:id/take` → `mpq.takeItem` → затем `preempt`.
- `/api/publishing/manual-queue/group/:unicResultId/take` → `mpq.takeGroup` → затем `preempt`.

`device_serial` берём из результата claim (`listGroup`/`getItem` его возвращают).
**Не ждём** смерти процесса — выстрелили `preemptForDevice` и сразу вернули ответ
(UI узнает о готовности через `device_auto_busy` в поллинге).

Под kill-switch `MANUAL_TAKE_PREEMPT_AUTO_ENABLED` (default ON; `=false` → старое поведение).

### (C) Детект готовности — GET списка (`server.js`)

`/api/publishing/manual-queue` (и `/:id`, `/group/:id`): добавить в каждый item/row флаг
`device_auto_busy` (boolean):

```sql
EXISTS (
  SELECT 1 FROM publish_tasks pt
  WHERE pt.device_serial = q.device_serial
    AND pt.status IN ('running','delegated')
)
```

UI: спиннер пока `(агрегат in_progress) && device_auto_busy`; переключение на «готов»
когда `device_auto_busy=false`. Поллинг ускорять до ~2с пока на экране есть релизинг-карточка,
иначе штатные 5с (`MPQ_POLL_MS`).

### UI (`public/index.html`)

- Чистый предикат (в стиле `mpq_pure.js`): `mpqIsReleasing(card)` =
  `mpqAgg(rows) === 'in_progress' && card.device_auto_busy === true`.
- Рендер карточки/строки: если releasing → спиннер + «Телефон освобождается… NN сек»
  (NN = now − taken_at, тикает клиентски), кнопки платформ `disabled`.
- При `device_auto_busy=false` и `in_progress` → штатная «В работе», кнопки активны.
- Поллинг: если есть хоть одна releasing-карточка → интервал ~2с, иначе 5с.

## Граничные случаи

- **Нет handle** (delegated / чужой процесс): не убиваем, не реквьюим — спиннер ждёт
  естественного завершения. Логируем `skipped_no_handle`.
- **Оператор «Вернул» пак** до завершения авто: телефон освобождается штатно (авто добегает
  или его уже вытеснили).
- **Идемпотентность**: повторный take / частый поллинг безопасны (claim уже `in_progress` →
  preempt не находит бегущих или находит те же → SIGTERM повторно безвреден).
- **SIGTERM→SIGKILL**: на случай, если `publisher.py` не завершается по TERM
  (проверить обработку TERM в publisher; SIGKILL гарантирует освобождение телефона).
- **Same-content редкость**: проверено — бывает (1 живой случай: `unic_result_id=18363`
  TikTok в обоих пайплайнах, `manual_handoff_at=NULL`). Cancel-guard закрывает риск
  двойной публикации именно для этого случая; в остальных (другой проект) — requeue.

## Тестирование (TDD, backend-first)

Unit (`node --test`, реальная БД-фикстура как `test_manual_inprogress_blocks_*.test.js`):
- `preemptForDevice`: requeue не-совпадающих по контенту; cancel same-content; пропуск
  неубиваемых (нет handle); no-op когда на телефоне нет бегущих publish; kill-switch off → no-op.
- exit-обработчик: при `preempting=true` пишет `pending` (requeue) / `preempted_by_manual`
  (cancel), а НЕ `failed`-как-ошибку.
- take-флоу: `/take` и `/group/:id/take` зовут `preemptForDevice` с верными
  `device_serial` + `unic_result_id`; при kill-switch off — не зовут.
- GET payload: `device_auto_busy` корректен (running/delegated → true; терминальные → false;
  нет задач → false).

Pure-function (Node, без БД): `mpqIsReleasing(card)` истинно/ложно по комбинациям
агрегата и `device_auto_busy`.

UI: ручная проверка спиннера/таймера/блокировки кнопок + перехода в «готов».

## Kill-switch / откат

`MANUAL_TAKE_PREEMPT_AUTO_ENABLED=false` → take как сейчас (без вытеснения). Флаг
`device_auto_busy` продолжает считаться (только индикация занятости — безвредно даже
при выключенном вытеснении: оператор хотя бы видит, что телефон занят авто).

## Деплой

- PR в `delivery-contenthunter` → main; прод `/root/.openclaw/workspace-genri/autowarm`
  `git pull` + `sudo pm2 restart #35` (scheduler + server в одном процессе).
- Без миграций БД (флаг `device_auto_busy` вычисляется на лету; `error_class` — существующая колонка).
- codex review перед мержем.
- Verify: повтор замера коллизий через сутки — медиана ожидания должна упасть к ~секундам;
  проверить отсутствие двойных публикаций и брошенных requeue.
