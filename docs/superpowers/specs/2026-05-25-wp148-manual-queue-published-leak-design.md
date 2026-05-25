# WP #148 — Опубликованная автовыкладка ушла в ручную

**Дата:** 2026-05-25
**Тип:** Ошибка (P1, клиентский фидбэк от Анастасии)
**Репозиторий фикса:** autowarm / `GenGo2/delivery-contenthunter`
**Ветка спеки:** `wp148-manual-queue-published-leak`

## Симптом (как описал менеджер)

Клиент **Art Estate**, телефоны 63, 64, 65, 103, 104, 108. Всё выложено автовыкладкой
(кроме тел. 43 — «файл не читается»), но при этом **всё** упало ещё и в ручную выкладку
за сегодняшний день. Ожидание: в ручную должно было отправиться **только то, что не
выложилось автоматически**.

## Root cause (подтверждён прод-данными 2026-05-25)

Контент 2317, слот `11029`, дата 25.05. Фактическое состояние `publish_queue`:

| status | skip_reason | кол-во |
|---|---|---|
| `done` | — | 21 |
| `cancelled` | `manual_publish` | 5 |
| `cancelled` | `retry_handoff:structural_error` | 1 |

Цепочка событий:

1. Один YouTube-аккаунт (`EliteCornersSpb`) упал с `error_class=ui_changed`
   (`error_code=yt_editor_upload_timeout`). Это «структурная» ошибка.
2. `retry_controller.handoffToManual` на структурную ошибку помечает **весь слот**
   `validator_schedule_slots.manual_publish=true`. Подтверждение программного, а не
   ручного происхождения: `manual_publish_set_by_id = NULL`.
3. Как только слот стал «эффективно ручным», dispatch-chokepoint guard (WP #125,
   `server.js`) отменил **5** ещё не отправленных строк (`skip_reason=manual_publish`),
   включая тел. 43 («файл не читается»).
4. `manual_queue_assign.js` (cron, scope = `slot.manual_publish OR project.manual_publish`)
   залил в `validator_manual_publish_queue` **все 27** комбинаций аккаунт×платформа слота —
   **включая 21 уже успешно опубликованную автоматом**.

Оператор (user id=3) затем вручную «взял» и отметил `published` 23 из 27 строк — ровно та
лишняя ручная работа, на которую жалуется клиент.

### Суть бага — несовпадение гранулярности

Падение публикации происходит на уровне **аккаунт×платформа** (строка `publish_queue`),
а перевод в ручную и заливка в очередь — на уровне **слота** (весь пак клиента). Одно
падение утягивает в ручную весь пак, в том числе уже опубликованное.

### Масштаб (вся система, на 2026-05-25)

Из **722** живых строк `validator_manual_publish_queue` (`cancelled_at IS NULL`) **311 (43%)**
дублируют уже успешную авто-публикацию (`publish_queue.status='done'` по тому же
`unic_result_id + account_username + platform`):

- **174** в статусе `queued` (операторы ещё не трогали — активный шум);
- **137** в статусе `published` (операторы уже прокликали).

Загрязнение идёт **двумя путями**:
- **авто-клиенты** (Art Estate и др.) — через retry-handoff (флип слота);
- **ручные клиенты** (Ambassadori, Feminista) — через `manual_queue_assign`, когда часть
  пака успела выйти автоматом до перевода клиента в ручной режим / до простановки флага.

## Целевое поведение

`validator_manual_publish_queue` содержит **только** те комбинации аккаунт×платформа,
которые **не вышли** автоматически. Уже опубликованное (`publish_queue.status='done'`) не
попадает в ручную очередь никогда — ни через retry-handoff, ни через `manual_queue_assign`.

При структурном/терминальном падении одной публикации:
- в ручную уходит **только** упавшая комбинация аккаунт×платформа;
- остальные аккаунты пака **продолжают авто-выкладку** как обычно;
- слот целиком **не** помечается ручным.

## Изменения в коде

### A. `retry_controller.js` — `handoffToManual` становится per-account

- **Убрать** флип `validator_schedule_slots.manual_publish=true`. Слот остаётся авто →
  остальные аккаунты пака продолжают авто-выкладку, dispatch-guard их не отменяет.
- **Добавить** точечную вставку одной строки в `validator_manual_publish_queue` именно
  для упавшей `(account_username, platform)`, с дедупликацией
  `ON CONFLICT (unic_result_id, account_username, platform) WHERE cancelled_at IS NULL DO NOTHING`.
- Отмену самой строки `publish_queue` (`status='cancelled'`, `manual_handoff_at=now()`,
  `skip_reason='retry_handoff:<reason>'`) оставить как есть.
- Расширить SELECT в `retryFailedPublishes`, чтобы тянуть `pq.pack_id, pq.account_username,
  pq.platform, pq.unic_result_id` (нужны для вставки).
- Данные для строки ручной очереди собрать из упавшей строки + джоины:
  - `slot_id`, `content_id`, `slot_date(planned_date)`, `project_id`, `project_name`
    — через `unic_tasks.meta->>'slot_id'` → `validator_schedule_slots` → `validator_projects`;
  - `scheme_id` — из `unic_results`/`unic_tasks`;
  - `phone_number`, `device_serial`, `raspberry_number` — `resolveDevice(pack_id)`;
  - `account_id` — `resolvePackAccounts(pack_id)`, матч по `username + platform`.
- Поведение применяется к обоим terminal-решениям контроллера: `structural_error` и
  `window_exhausted` (оба уже итерируются по строкам `publish_queue`, т.е. естественно
  per-account).

### B. Общий хелпер `enqueueManualRow(client, {...})`

Вынести INSERT-колонки `validator_manual_publish_queue` в одну функцию, используемую и
`manual_queue_assign.js`, и `handoffToManual`. Один источник правды по списку колонок и
по `ON CONFLICT`. Снижает риск дрейфа схемы между двумя путями вставки.

### C. `manual_queue_assign.js` — исключать уже опубликованное

В выборку результатов уникализации добавить условие: не заливать комбинацию
`(unic_result_id, account_username, platform)`, у которой уже есть строка
`publish_queue` со `status='done'`. Это defense-in-depth: закрывает загрязнение по ручным
клиентам, где часть пака успела выйти автоматом до перевода в ручной режим.

> Проверку выполнять на уровне per-account внутри цикла (после `resolvePackAccounts`), а
> не в верхнем SELECT по `unic_results`, т.к. `done` определяется по конкретному
> `account_username + platform`, а не по всему `unic_result`.

## Ретро-зачистка (one-off)

Идемпотентный скрипт/SQL: отменить (`cancelled_at = now()`, `updated_at = now()`)
**только** строки `validator_manual_publish_queue` где:
- `operator_status = 'queued'` И `cancelled_at IS NULL`;
- существует совпадающая `publish_queue` (`unic_result_id`, `LOWER(account_username)`,
  `LOWER(platform)`) со `status = 'done'`.

Ожидаемо затрагивает **174** строки. `published` (137) **не трогаем** (исторические,
там проставлены `matched_post_url`; их отмена сломала бы статистику «выложено вручную»).
Скрипт печатает `count` целевых строк до и после для верификации.

## Kill-switches (env; PM2, без правки systemd)

- `RETRY_HANDOFF_PER_ACCOUNT=false` → откат к старому поведению (флип `slot.manual_publish`).
- `MANUAL_QUEUE_EXCLUDE_PUBLISHED=false` → откат фильтра «исключать done» в `manual_queue_assign`.

Существующие флаги не трогаем: `RETRY_MANUAL_HANDOFF_ENABLED`, `RETRY_ENGINE_ENABLED`,
`MANUAL_QUEUE_POPULATE_ENABLED`, `CLIENT_MANUAL_PUBLISH_ENABLED`,
`DISPATCH_MANUAL_RECHECK_ENABLED`.

## Тесты (node --test)

1. **handoff per-account:** упавшая строка → ровно 1 новая строка в
   `validator_manual_publish_queue` по этому `(account_username, platform)`; `slot.manual_publish`
   остаётся `false`; прочие строки слота **не** отменяются.
2. **handoff идемпотентность:** повторный tick не создаёт дубль (срабатывает `ON CONFLICT`).
3. **handoff kill-switch:** при `RETRY_HANDOFF_PER_ACCOUNT=false` — старое поведение (флип слота).
4. **manual_queue_assign exclude-done:** аккаунт с `done` в `publish_queue` пропускается;
   не-вышедший — заливается.
5. **manual_queue_assign kill-switch:** при `MANUAL_QUEUE_EXCLUDE_PUBLISHED=false` — старое
   поведение (заливает всё).
6. **cleanup-скрипт:** отменяет только `queued`-дубли; `published`-дубли и не-дубли не трогает;
   повторный запуск — no-op.

Live-DB тесты — с изоляцией по тестовым `client_publish_id`/`unic_result_id` (паттерн
`retry_controller` `onlyClientPublishId`), чтобы не мутировать реальные строки.

## Что НЕ трогаем

- Admin-тогл ручной выкладки (WP #85) и client-manual флаг (WP #115) — намеренный флип
  слота/проекта остаётся; весь пак уходит в ручную, но теперь без уже-`done`.
- `slot_matcher_cron.js`, dispatch-chokepoint guard (WP #125), RBAC, фронт — без изменений.

## Риски и связи

- **Низкий риск:** фикс **сужает** попадание в ручную очередь, не расширяет. Полный откат —
  два env-флага без передеплоя.
- **WP #128** (UI-правки ручной выкладки, ветка `wp128-manual-publish-edits`) — другой слой
  (фронт/UX); пересечения по `retry_controller.js` / `manual_queue_assign.js` нет.
- **Cross-repo:** изменений схемы БД нет (только новые строки/cancel в существующих таблицах),
  поэтому grep по другим сервисам не требуется. Колонки `validator_manual_publish_queue`
  и `publish_queue` не меняются.

## Деплой

1. Мердж в `main` autowarm → `git pull` в `/root/.openclaw/workspace-genri/autowarm/` →
   `pm2 restart autowarm` (подхват `retry_controller.js` / `manual_queue_assign.js`).
   Проверить `pm2 describe autowarm | grep "exec cwd"` (drift к testbench).
2. Прогнать one-off cleanup-скрипт на прод-БД, сверить `count` до/после (ожидаемо 174).
3. Мониторить `[retry-controller] handoff` и `[manual-queue]` логи первые сутки на отсутствие
   повторного залива уже-`done`.
4. Обновить WP #148 в OpenProject (house-style комментарий), статус → «Тестирование».
