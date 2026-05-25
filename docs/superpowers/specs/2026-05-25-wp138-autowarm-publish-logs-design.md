# WP #138 — Логи и статусы автовыкладки (ретрай / перевод на ручную)

- **Дата:** 2026-05-25
- **OpenProject:** Content Hunter #138 «Добавить логи по автовыкладке» (автор — Анастасия, исполнитель — Данил)
- **Тип:** Задача / observability
- **Репозиторий кода:** `GenGo2/delivery-contenthunter` (autowarm), прод `/root/.openclaw/workspace-genri/autowarm/`, ветка `main`
- **Поверхность:** дашборд autowarm на `delivery.contenthunter.ru` (Caddy → `localhost:3848`), фронт `public/index.html`

## 1. Задача (как сформулировано)

В лог задачи автовыкладки дописывать:
- что сработал ретрай и задача была перезапущена + причина / правило, по которому она перезапущена;
- что она отправлена на ручную выкладку + причина / правило, почему именно эта задача переведена на ручную.

Также нужны дополнительные статусы, которые отображали бы:
- что произошла ошибка и задача переведена на ручную выкладку;
- что произошла ошибка и задача перезапущена (ретрай).

## 2. Контекст: что уже есть в коде

Логика ретраев и авто-перевода на ручную **уже реализована и работает в проде** (WP #108, retry engine). Эта задача — **только видимость** (observability) поверх неё. Поведение (когда ретраить, когда переводить на ручную) **не меняем**.

- `retry_controller.js` — `retryFailedPublishes(pool)` вызывается `setInterval` каждые `RETRY_INTERVAL_MINUTES` (деф. 5 мин) из `server.js:6969-6973`. Kill-switch `RETRY_ENGINE_ENABLED=false`.
- Контроллер на каждом тике выбирает `publish_queue` со `status='failed' AND manual_handoff_at IS NULL`, по последней упавшей попытке (`publish_tasks` через LATERAL) и считалкам попыток/окна принимает решение через `retry_decision.js` → `decideRetry()`.
- **Решения и их правила** (`retry_decision.js`):
  - `requeue` (перезапуск):
    - `transient_within_limits` — временная ошибка (`network` / `rate_limited` / `unknown`) в пределах дневного лимита;
    - `fixed_at_reanimated` — баг в системе починен после падения (`publish_error_codes.fixed_at > last_failed_at`).
  - `handoff` (перевод на ручную):
    - `structural_error` — `banned` / `ui_changed`;
    - `window_exhausted` — исчерпано окно `RETRY_WINDOW_DAYS` (деф. 2 дня).
  - `wait` — `after_cutoff`, `daily_limit_wait_tomorrow`, `unclassified` (ничего не делаем, статуса не требует).
- **На `requeue`** (`retry_controller.js:80-87`): `UPDATE publish_queue SET status='pending', publish_task_id=NULL` + `console.log`.
- **На `handoff`** (`handoffToManual`, `retry_controller.js:96-128`): в транзакции — `validator_schedule_slots.manual_publish=true`, `publish_queue SET status='cancelled', skip_reason='retry_handoff:<rule>', manual_handoff_at=now()` + `console.log`.

**Проблема:** причины ретрая уходят только в `console.log`, причина перевода на ручную — в `skip_reason` (техническим текстом `retry_handoff:window_exhausted`). В **логе задачи**, который оператор открывает в дашборде (модалка 📋, `publish_tasks.events`), этого нет; человеческим языком — тем более. Колонка «Попытка» в таблице очереди есть в вёрстке, но бэкенд её не заполняет.

### Где оператор смотрит (`public/index.html` + `server.js`)
- **Таблица очереди** — `/api/publish/queue` (server.js ~2033, `PUBLISH_QUEUE_SELECT` ~1658 возвращает `pq.*` + `pt.status`, `post_url`, `task_log` и т.д.). В рендере очереди уже показывается `skip_reason` мелким серым (`public/index.html` ~11267) и есть пустая колонка «Попытка» (~11306).
- **Таблица задач** «Опубликовано» — `/api/publish/tasks` (server.js ~2581, `PUBLISH_TASKS_SELECT` ~2509). Бейдж статуса задачи — `UPT_STATUS_BADGE` (~11104).
- **Модалка лога** 📋 — `upShowEvents(taskId)` (~11414) → `/api/publish/tasks/:id/events` (server.js ~2756) рендерит таймлайн `events` + текст `log`. Иконки событий по типам (~11438): `start/info/error/warning/day_done/success`.
- **Карточки планировщика** (недельный календарь) — `/api/publish/planner` (server.js ~5793, `publish_planner.js getPlannerCards`). Карточка несёт `attempts[]`, `queue_status`, `manual_handoff_date`, `state`, `mode` (`auto`/`manual`). Рендер — `public/index.html` ~10906-10985.

*(Номера строк — ориентир на момент написания; перед правкой свериться `grep -n`, файл большой и быстро меняется.)*

## 3. Объём

**В объёме:**
- Запись человекочитаемых событий о ретрае и переводе на ручную в лог задачи (`publish_tasks.events`).
- Два новых статуса-бейджа в дашборде: «Повтор после ошибки» и «Ошибка → ручная выкладка», в таблицах очереди/задач и на карточках планировщика.
- Заполнение причины/правила и счётчика попыток (через крошечную миграцию — Подход B).

**Не в объёме:**
- Любые изменения логики `retry_decision.js` / `retry_controller.js` по части *когда* ретраить и *когда* переводить на ручную.
- Вывод в Vue-валидатор `client.contenthunter.ru` (другое приложение, не та поверхность).
- Дневной Telegram-отчёт.

## 4. Правила → человеческий текст

Единый словарь (правится в одном месте). Тексты — в стиле наших комментариев для не-технарей: без жаргона.

**Перезапуск (событие `type:'retry'`, иконка 🔁):**
| rule | текст |
|---|---|
| `transient_within_limits` | «Временный сбой публикации (сеть или ограничение площадки). Задача автоматически перезапущена. Попытка {N}.» |
| `fixed_at_reanimated` | «Ошибку в системе устранили — задача автоматически перезапущена.» |

**Перевод на ручную (событие `type:'handoff'`, иконка 🤚):**
| rule (+ error_class) | текст |
|---|---|
| `structural_error` + `banned` | «Аккаунт заблокирован площадкой — задача передана на ручную выкладку.» |
| `structural_error` + `ui_changed` | «Изменился интерфейс приложения — задача передана на ручную выкладку.» |
| `structural_error` (прочее) | «Серьёзная ошибка — задача передана на ручную выкладку.» |
| `window_exhausted` | «За 2 дня опубликовать автоматически не удалось — задача передана на ручную выкладку.» |

К каждому событию добавляется исходная ошибка: «Исходная ошибка: {человеческое описание `error_code` или сам код}.» (используем существующий в дашборде словарь подписей ошибок, если он есть; иначе — сырой код).

## 5. Решение по компонентам (Подход B)

### 5.1. Миграция (`autowarm/migrations/20260525_wp138_retry_visibility.sql`)
Добавочные nullable-поля в `publish_queue` (безопасно для `SELECT *` в других потребителях; cross-repo grep перед деплоем — `publish_queue` читают autowarm + валидатор-бэкенд + аналитика):
```sql
ALTER TABLE publish_queue
  ADD COLUMN IF NOT EXISTS last_retry_reason text,
  ADD COLUMN IF NOT EXISTS last_retried_at   timestamptz;
```
**Уточнение по `attempt_count` (найдено при планировании):** отдельная колонка `retry_count` НЕ нужна. `publish_planner.attachQueueTransferColumns` уже вычисляет `attempt_count` (число реальных попыток из `publish_tasks`, без `process_interrupted`) и `transferred_to` (= дата перевода на ручную) — колонка «Попытка» в таблице очереди уже заполняется при `QUEUE_TRANSFER_COLUMNS_ENABLED`. Новое здесь — только **причина/правило** (`last_retry_reason`), которой нет нигде.

Перевод на ручную **новых полей не требует** — `skip_reason` (`retry_handoff:<rule>`) + `manual_handoff_at` уже персистятся.

### 5.2. `retry_controller.js`
- В основной `SELECT` добавить `lt.id AS last_task_id` (id последней упавшей попытки), чтобы было куда писать событие.
- **Атомарность (важно):** запись события в `publish_tasks.events` и переход статуса `publish_queue` должны быть **в одной транзакции**. Иначе падение между ними оставит задачу перезапущенной/переведённой на ручную *без* записи в логе, а контроллер её больше не выберет (после requeue строка не `failed`; после handoff стоит `manual_handoff_at`) — backfill невозможен, и теряется ровно та видимость, ради которой делается задача.
- **На `requeue`** — обернуть в транзакцию (`BEGIN`…`COMMIT` через `client`), внутри:
  - `UPDATE publish_queue SET status='pending', publish_task_id=NULL, updated_at=NOW(), last_retry_reason = CASE WHEN $visibility THEN $reason ELSE last_retry_reason END, last_retried_at = CASE WHEN $visibility THEN NOW() ELSE last_retried_at END WHERE id=$1 AND status='failed' AND manual_handoff_at IS NULL` — поля видимости пишем только при включённом kill-switch (см. 5.5); событие — только если `rowCount===1` (переход реально состоялся; идемпотентность);
  - в той же транзакции — `UPDATE publish_tasks SET events = COALESCE(events,'[]'::jsonb) || $evt::jsonb WHERE id = $last_task_id`, где `$evt = {ts, type:'retry', msg:<человеческий текст>, meta:{rule, error_class, error_code, attempt}}`;
  - `COMMIT`. (При `rowCount===0` — `ROLLBACK`, строку увели под нами.)
- **На `handoff`** — событие `type:'handoff'` (`{ts, msg, meta:{rule, error_class, error_code}}`) в `publish_tasks` по `r.last_task_id` писать **внутри существующей транзакции `handoffToManual`, до `COMMIT`** (рядом с `UPDATE publish_queue ... skip_reason`), чтобы переход и лог фиксировались атомарно.
- `ts` события — формат `HH:MM:SS` МСК, как у существующих событий (`new Date().toLocaleTimeString('ru-RU',{timeZone:'Europe/Moscow',hour12:false})`).
- Всё под общим kill-switch (см. 5.5): при выключенном — контроллер по-прежнему делает requeue/handoff (поведение!), но НЕ пишет события и НЕ трогает поля `retry_*`.

**Почему событие пишется в *упавшую* попытку, а не в новую:** ретрай обнуляет `publish_task_id`, новая попытка создаётся позже диспетчером. Решение «после этого падения — перезапуск/перевод» логически принадлежит именно упавшей попытке; там его и видно в модалке 📋. Все попытки видны в таблице задач и в `attempts[]` карточки.

### 5.3. Бэкенд-эндпоинты
- `/api/publish/queue` — `PUBLISH_QUEUE_SELECT` уже отдаёт `pq.*` → новое поле `last_retry_reason` приедет автоматически; `skip_reason`, `attempt_count`, `transferred_to` уже есть. Доп. правок не требует.
- `/api/publish/tasks` — **правок НЕ требует.** Бейджи в таблице задач строим из `pt.events` (он уже в `pt.*`): после `requeue` `pq.publish_task_id` обнулён, а эндпоинт джойнит `pq` по `pq.publish_task_id = pt.id` → для упавшей задачи `pq.*` пришёл бы `null`. Наша запись `type:'retry'/'handoff'` лежит на самой упавшей задаче — её и читаем.
- `/api/publish/planner` (`publish_planner.js`, `buildPlannerCards`) — финальный объект карточки сейчас НЕ несёт `attempts`/`manual_handoff_date` (они есть только на `intents`). Поэтому в `buildPlannerCards` вычислить на уровне цепочки два флага и положить в карточку: `had_retry` (любой intent имеет ≥2 реальных попыток) и `auto_handoff` (любой intent имеет `manual_handoff_date`).

### 5.4. UI (`public/index.html`) — «и там, и там»
Логика бейджей (правила вывода):
- **«🔁 Повтор после ошибки · попытка N»** — когда `last_retry_reason` не пуст (точный сигнал авто-ретрая); число `N` берём из уже существующего `attempt_count`; подсказка (`title`) = человеческий текст `last_retry_reason`.
- **«❗→✋ Ошибка → ручная»** — когда `status='cancelled' AND skip_reason LIKE 'retry_handoff:%'`; подсказка = человеческий текст правила. Отличается от ручной, которую включил оператор сам (та — без `retry_handoff` в `skip_reason`, бейдж «👋 вручную»).

Точки правок:
- Таблица очереди (`upqRenderRow`) — бейджи в ячейке статуса (рядом с `badge`+`skipNote`). Колонка «Попытка» уже заполнена (`attempt_count`), не трогаем.
- Таблица задач (`uptRenderRow`) — бейджи рядом со `UPT_STATUS_BADGE`, выводятся из `row.events` (наличие события `type:'retry'`/`'handoff'`), а не из `pq.*` (см. §5.3 — join рвётся после requeue).
- Карточки планировщика (`plannerCardHtml`) — маркер `🔁` при `c.had_retry` и маркер `❗→✋` при `c.auto_handoff` (отдельно от обычного `👋 вручную`).
- Модалка 📋 (`typeIcon`/`typeBg` ~ строка с `start:'🚀'...`) — добавить `retry:'🔁'`, `handoff:'🤚'` + фон.
- Единый JS-словарь `RETRY_RULE_LABEL` / `HANDOFF_RULE_LABEL` + парсер `skip_reason='retry_handoff:<rule>'` → подпись (как в §4).

### 5.5. Kill-switch
`RETRY_VISIBILITY_ENABLED` (деф. `true`). При `false` `retry_controller.js` пропускает запись событий и полей `retry_*` (логика ретраев/перевода не страдает). Новые бейджи аддитивны и read-only — при отсутствии данных просто не показываются.

## 6. Краевые случаи
- `last_task_id` может быть `NULL` для легаси-строк без линии намерения — такие строки контроллер и так пропускает (`r.no_intent || !r.error_class`); запись события защитить `if (last_task_id)`.
- Дубли событий: запись события — в одной транзакции с переходом и только при `rowCount===1` UPDATE-перехода (и для requeue, и для handoff); при `ROLLBACK` событие не остаётся.
- Многократные ретраи: каждая упавшая попытка получает ровно одно событие; `last_retry_reason`/`last_retried_at` отражают ПОСЛЕДНИЙ авто-перезапуск (число попыток — в `attempt_count`).
- Идемпотентность тика сохраняется: после requeue строка уже не `failed`, повторный инкремент в том же тике невозможен (guard `WHERE status='failed'`).

## 7. Тесты
- `test_retry_controller.test.js` (live-DB, изоляция через `onlyClientPublishId`): добавить проверки —
  - после `requeue`: `last_retry_reason`/`last_retried_at` проставлены, в `events` упавшей попытки есть запись `type:'retry'` с нужным `rule`;
  - после `handoff`: в `events` упавшей попытки есть запись `type:'handoff'`; `skip_reason`/`manual_handoff_at` проставлены (как и раньше).
- Если словарь правил → текст вынесем в чистую функцию — отдельный unit-тест на маппинг (включая `structural_error` × `banned`/`ui_changed`).

## 8. Координация и деплой
- **Параллельная сессия WP #128** правит `public/index.html` (чекбоксы статусов, точечный рефреш, «Ручная дата», ширина). Зона пересечения — рендер карточек/статусов. Работаю в отдельной ветке `wp138-autowarm-publish-logs`, правки держу точечными и аддитивными (новые render-функции бейджей, единый словарь), перед PR — rebase на свежий `main`; порядок merge с WP #128 согласовать.
- **Деплой:** применить миграцию (по принятому в autowarm способу) → `git pull` main в прод-checkout → `sudo -n pm2 restart autowarm`. Поля аддитивные; откат фичи — `RETRY_VISIBILITY_ENABLED=false` (данные перестают накапливаться) + при необходимости скрыть бейджи.
- Авто-push hook autowarm: коммит в этом репо = публичный push; имя ветки feature прод не тянет (тянет только `main`).

## 9. Связанные памяти
- `reference_publish_requeue_path` — жизненный цикл `publish_queue` / `publish_tasks`.
- `project_wp85_manual_publish_shipped` — `manual_publish` (ручная оператором) vs авто-handoff.
- `feedback_publisher_error_code_misleading` — группировать по финальной категории; `error_code` может врать.
- `feedback_cross_repo_schema_changes` — grep `publish_queue` по всем сервисам до деплоя миграции.
- `feedback_openproject_practice` — статус-комментарий и перевод статуса по мере отгрузки.
- `reference_delivery_frontend_deploy` / `project_autowarm_code` — деплой и раскладка autowarm.
