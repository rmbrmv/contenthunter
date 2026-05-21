# WP #108 — Движок ретраев для выкладок — Design Spec

- **Дата:** 2026-05-21
- **OpenProject:** WP #108 «Ретраи для выкладок» (тип «Задача», автор Анастасия, assignee Данил, приоритет «Немедленно»)
- **Ветка (docs):** `docs/wp108-publish-retries-2026-05-21`
- **Базируется на / переиспользует:** WP #85 (послотовый `manual_publish` + матчер), WP #107 (очередь ручной выкладки), WP #115 (клиентский флаг + `effective_manual`), WP #125 (гард «ручной слот не уезжает в авто»), WP #86 (ловля `post_url`), WP #77 (хэш видео)

## 1. Постановка задачи

Сейчас публикации либо проходят, либо падают терминально — **авто-ретраев нет** (упавшее перевыкладывается только вручную; watchdog лишь сбрасывает зависшее). Нужно: ретраить с понятным лимитом, не дублировать при перезапуске, разделять «временные сбои» от «постоянных проблем» и при исчерпании отдавать на ручную выкладку.

Исходные 10 пунктов задачи. По согласованию с заказчиком (Данил) **scope #108 = движок ретраев, пункты 1–7**. Пункты 8–9 (ручная выкладка блокирует автоматику / возврат в авто после ручной) уже покрыты сагой #85/#107/#115/#125. Пункт 10 (возврат ручная→авто на следующий день, если ручная не сделана) вынесен **отдельно, вне #108**.

## 2. Решения, согласованные с заказчиком

| Пункт | Решение |
|---|---|
| Scope | Движок ретраев (1–7). Ручную выкладку (8–9) переиспользуем. Пункт 10 — отдельно |
| 1 — идемпотентность | **Гибрид:** основной — внутренний трекинг по `client_publish_id`; точечный скрейп последних N постов аккаунта только при неоднозначном прошлом состоянии |
| 2 — error_class | Колонка `error_class` в `publish_error_codes` + маппинг известных кодов, дефолт `unknown` |
| 4 — лог фиксов | **Реестр `fixed_at`** на `publish_error_codes`: разработчик помечает код исправленным; крон реанимирует упавшие до фикса задачи |
| 4/5 — цикл | **Календарные дни:** 2 дня авто-попыток, ≤ 3 ретрая/сутки на один `error_class`, счётчик сбрасывается на старте дневной партии; 3-й день → ручная. `banned`/`ui_changed` → сразу ручная. `fixed_at` реанимирует |
| 6 — время | **Перейти на МСК** (`Europe/Moscow`): старт партии 05:00, отсечка ретраев 23:00. Деплой-проверка: не сдвинет ли слоты |
| 7 — параллелизм | Env-лимит на малинку, дефолт 3, поднимать постепенно (тюнинг без передеплоя) |
| Архитектура | **Подход 1:** крон-контроллер ретраев поверх `publish_queue` + минимальная схема |

## 3. Текущее состояние (grounding по коду autowarm)

Проверено в `/root/.openclaw/workspace-genri/autowarm` (прод-чекаут) на 2026-05-21. Номера строк индикативные — реализатор сверяется с актуальным `server.js`.

- **Очередь и диспатч:** `publish_queue` (статусы `pending`/`running`/`done`/`failed`/`skipped`/`cancelled`); `dispatchPublishQueue` (каждые 5 мин, LIMIT 50) создаёт `publish_task` и линкует `publish_task_id`. `syncQueueStatuses` синхронит статусы обратно. **Ретрая нет** — упавшая строка остаётся `failed`.
- **Watchdog re-queue** (server.js ~6906–6948): при зависании пишет `error_code='watchdog_subprocess_hang'` и `UPDATE publish_queue SET status='pending', publish_task_id=NULL` — единственный существующий примитив возврата в очередь. Наш контроллер использует тот же примитив.
- **Справочник ошибок — `publish_error_codes`** (НЕ farming-зеркало `farming_error_codes`). Колонки: `code`, `severity`, `retry_strategy` (CHECK `none`/`immediate`/`backoff`/`manual`), `is_known`, `is_auto_fixable`, `description`. `triage_classifier.py` авто-регистрирует неизвестные коды (`is_known=FALSE`). `auto_rollback.py` умеет ставить `retry_strategy='manual'`. Есть авто-фикс-петля (`agent_diagnose.py`/`agent_apply.py` по `is_auto_fixable`).
- **Установка `error_code`** — `publisher_base.py` ~2110–2193 (`_set_error_code_from_events`): резолвит из `events[].meta.category/reason`, фолбэк `switch_failed_unspecified`.
- **Счётчик попыток — прецедент есть:** `publish_tasks.url_capture_attempts INT` (миграция 20260518). Каждая попытка публикации = отдельная строка `publish_tasks` (персистится).
- **Ловля ссылки (#86):** статус `published_no_url` для исчерпанного `awaiting_url`; `publish_tasks.url_capture_attempts`/`url_capture_last_attempt_at`.
- **Ручная выкладка:** `validator_schedule_slots.manual_publish` (послотово, #85) + `validator_projects.manual_publish` (клиент, #115); `effectiveManualSql()` в `client_manual_filter.js`; наполнитель `assignManualPublishQueue` (`manual_queue_assign.js`) → `validator_manual_publish_queue`; гард на диспатче #125 (re-check флага). Слот резолвится из `unic_task.meta.slot_id`.
- **Тайминги:** `unic_settings.publish_start` (дефолт `09:00:00`) + `timezone` (дефолт `Asia/Dubai`); `PUBLISH_INTERVAL_MINUTES=20`. Бизнес-дата считается `computeBusinessDate(timezone)`.
- **Параллелизм:** `MAX_CONCURRENT_PUBLISHES_PER_RASPBERRY` (дефолт 3) — лимит на малинку; на телефон неявно 1. Снижали до 3 из-за роста ошибок при высоком параллелизме.

## 4. Модель данных (минимум — 3 ALTER, без новых таблиц)

Каждая попытка публикации уже = отдельная строка `publish_tasks`, поэтому **отдельный леджер попыток не нужен** — считаем по `publish_tasks`.

```sql
-- 1) publish_queue: стабильный ID намерения + отметка передачи в ручную
ALTER TABLE publish_queue
  ADD COLUMN IF NOT EXISTS client_publish_id uuid,
  ADD COLUMN IF NOT EXISTS manual_handoff_at timestamptz NULL;
-- DEFAULT gen_random_uuid() → любой путь вставки получает ID (нельзя «опт-аут» из ретраев);
-- затем backfill существующих строк и SET NOT NULL (контракт «у каждой строки есть ID»).
-- index: CREATE INDEX ON publish_queue (client_publish_id);

-- 2) publish_tasks: копия ID намерения + класс ошибки (леджер попыток)
ALTER TABLE publish_tasks
  ADD COLUMN IF NOT EXISTS client_publish_id uuid,
  ADD COLUMN IF NOT EXISTS error_class text NULL;
-- index: CREATE INDEX ON publish_tasks (client_publish_id, error_class, created_at);

-- 3) publish_error_codes: таксономия + реестр фиксов
ALTER TABLE publish_error_codes
  ADD COLUMN IF NOT EXISTS error_class text NOT NULL DEFAULT 'unknown',
  ADD COLUMN IF NOT EXISTS fixed_at timestamptz NULL;
-- CHECK error_class IN ('network','ui_changed','banned','rate_limited','unknown')
-- seed: маппинг известных кодов → классы (см. §5)
```

- **`client_publish_id`** = «намерение выложить контент X в аккаунт Y на платформу Z». Присваивается при создании строки `publish_queue`, **стабилен через ре-queue** (строка переиспользуется, как у watchdog). Копируется в `publish_task` при диспатче.
- **`error_class` на `publish_tasks`** проставляется при завершении задачи (рядом с `error_code`).
- **`error_class`/`fixed_at` на `publish_error_codes`** — таксономия и реестр фиксов на уровне кода.
- **Deploy-time backfill (обязателен):** существующим `publish_tasks` проставить `client_publish_id` (из их строки `publish_queue.publish_task_id`) и `error_class` (из справочника по `error_code`) — иначе уже-упавшие на момент деплоя выкладки не подхватятся движком (контроллер джойнит по `client_publish_id` и пропускает строки без класса). Выполняется после сида `error_class`.

## 5. Таксономия error_class и связь с retry_strategy

`error_class` (ПОЧЕМУ упало) и существующий `retry_strategy` (ЧТО делать) — комплементарны. Сид-маппинг (примерный, финальный — на этапе плана по фактическим кодам в БД):

| error_class | Примеры кодов | Поведение ретрая |
|---|---|---|
| `network` | `adb_devices_unreachable`, `adb_push_timeout`, `watchdog_subprocess_hang` | ретраить (3/сутки, окно 2 дня) |
| `rate_limited` | коды про лимиты/«попробуйте позже» | ретраить с backoff |
| `ui_changed` | `*_target_not_in_picker`, `*_editor_not_reached`, `caption_fill_failed` | **сразу в ручную** (кроме `fixed_at`) |
| `banned` | `account_blocks`-связанные, «аккаунт заблокирован» | **сразу в ручную** |
| `unknown` | всё авто-зарегистрированное `triage_classifier` (is_known=FALSE) | ретраить как временное (консервативно) |

- Неизвестные коды получают `error_class='unknown'` по дефолту и ретраятся (с лимитом) — безопасно: новый код вряд ли структурный с первого падения, а лимит/окно ограничат ущерб.
- Реклассификация — данными (UPDATE `publish_error_codes`), без передеплоя.

## 6. Компоненты

### 6.1 Классификатор (publisher / completion)
Там, где сейчас ставится `error_code` (`publisher_base.py:_set_error_code_from_events`), дополнительно резолвить `error_class` из `publish_error_codes` по коду и писать в `publish_tasks.error_class`. Если кода ещё нет в справочнике — `triage_classifier` его регистрирует (is_known=FALSE), класс = `unknown`.

### 6.2 Хук идемпотентности (publisher, перед Share) — пункт 1
Гибрид. Перед нажатием Share:
1. **Внутренняя проверка (основная):** есть ли по этому `client_publish_id` уже терминально-опубликованная задача с пойманным `post_url` (`status IN ('done','published')` и `post_url IS NOT NULL`)? → **пропуск** (уже выложено в прошлом ретрае).
2. **Скрейп при сомнении (редкий путь):** если прошлая попытка в неоднозначном состоянии — `published_no_url` или краш в момент Share — точечно скрейпим последние N постов аккаунта и сверяем (медиа-хэш #77 / эвристика свежести), чтобы не задвоить. Если нашли → пропуск; не нашли → публикуем.
3. Иначе — публикуем как обычно.

Под kill-switch `IDEMPOTENCY_CHECK_ENABLED`. Скрейп — только в ветке сомнения (экономит Apify-квоту).

### 6.3 Крон-контроллер `retryFailedPublishes` — пункты 3, 4, 5
Тик каждые `RETRY_INTERVAL_MINUTES` (3–5 мин), **только в окне старт-партии … 23:00 МСК**. Берёт `publish_queue` со `status='failed'` без `manual_handoff_at`, по каждой строке применяет логику §7. Изолирован от `dispatchPublishQueue` (отдельная функция/интервал) — легко kill-switch и тестировать.

## 7. Жизненный цикл (решение контроллера на упавшую строку)

```
Упавшая строка publish_queue (status='failed', manual_handoff_at IS NULL)
   │  resolve error_class (последняя publish_task намерения), last_failed_at
   ▼
error_class ∈ {banned, ui_changed}  И НЕ (fixed_at > last_failed_at) ?
   ├─ ДА ─▶ ПЕРЕДАТЬ В РУЧНУЮ (структурная — сразу, в любое время)
   └─ НЕТ
        ▼
время ≥ RETRY_CUTOFF (23:00 МСК) ?  (проверяем ДО действий)
   ├─ ДА ─▶ WAIT (контроллер ничего не делает вне окна дня)
   └─ НЕТ
        ▼
   fixed_at > last_failed_at ? ── ДА ─▶ РЕАНИМАЦИЯ: ре-queue (баг починен, даже ui_changed)
        │ НЕТ
   окно RETRY_WINDOW_DAYS (2 календ. дня от first_attempt) исчерпано ? ── ДА ─▶ ПЕРЕДАТЬ В РУЧНУЮ (give-up)
        │ НЕТ
   попыток сегодня по этому классу ≥ RETRY_MAX_PER_CLASS_PER_DAY (3) ? ── ДА ─▶ WAIT (завтра счётчик сбросится)
        │ НЕТ
   ─▶ РЕ-QUEUE (status='pending', publish_task_id=NULL)
```

> **Важно:** исчерпание **дневного** лимита (3/класс) ≠ передача в ручную. Это «на сегодня хватит» → ждём до завтра, счётчик сбросится, окно 2 дней ещё активно. В ручную уводит только **исчерпание окна 2 дней** (или структурная ошибка banned/ui_changed). Отсечка 23:00 проверяется до ветвей с действиями: после неё контроллер бездействует (WAIT) по всем ветвям, кроме немедленного структурного handoff — он проверяется ещё до отсечки.

- **Счётчик «3/сутки/класс»:** `SELECT count(*) FROM publish_tasks WHERE client_publish_id=$1 AND error_class=$2 AND (created_at AT TIME ZONE 'Europe/Moscow')::date = (now() AT TIME ZONE 'Europe/Moscow')::date AND status IN ('failed','preflight_failed') AND error_code <> 'process_interrupted'`. Сбрасывается естественно сменой календарной даты (партия стартует 05:00 МСК).
  - ⚠️ **Все вычисления «календарного дня» — в `Europe/Moscow`**, а не в TZ сессии БД (которая может остаться UTC/Asia/Dubai). Иначе у границы суток попытки засчитаются не в тот день. Везде применяем `(<ts> AT TIME ZONE 'Europe/Moscow')::date` (либо `SET LOCAL timezone='Europe/Moscow'` в транзакции контроллера).
- **Окно 2 дня:** от `first_attempt` = `min(created_at)` задач намерения до текущей даты, обе границы — в `Europe/Moscow`-дате: `((now() AT TIME ZONE 'Europe/Moscow')::date - (min(created_at) AT TIME ZONE 'Europe/Moscow')::date) >= RETRY_WINDOW_DAYS` → ручная. На 3-й календарный день → ручная.
- **Ре-queue:** тот же примитив, что watchdog (`status='pending'`, `publish_task_id=NULL`); `dispatchPublishQueue` создаст новый `publish_task` (см. практику re-queue).

## 8. Передача в ручную (handoff) — переиспользуем сагу

При решении «в ручную»:
1. Резолвим слот намерения через `unic_task.meta.slot_id`.
2. `UPDATE validator_schedule_slots SET manual_publish=true` для этого слота + аудит **системного** актора (зеркало `manual_publish_set_by_id`/`set_at`, но `set_by`=system-маркер, причина `retries_exhausted` либо `structural_error`/код).
3. Терминально гасим строку `publish_queue` (`status='cancelled'`/`skipped` по существующему соглашению) + `manual_handoff_at=now()`.
4. Дальше — **существующий** механизм: гард #125 не пустит слот в авто, наполнитель #107 (`assignManualPublishQueue`) заведёт его в `validator_manual_publish_queue`.

Под kill-switch `RETRY_MANUAL_HANDOFF_ENABLED` (при `false` — контроллер только ре-queue в пределах лимитов, без handoff, чтобы откатить связку с сагой ручной выкладки).

## 9. Тайминги (пункт 6) — переход на МСК

- `unic_settings.timezone='Europe/Moscow'`, `publish_start='05:00:00'`.
- Отсечка ретраев `RETRY_CUTOFF_HOUR_MSK=23` — контроллер не ре-queue-ит после 23:00 МСК.
- **⚠️ Деплой-проверка (риск сдвига слотов):** убедиться, что времена слотов хранятся как абсолютные `timestamptz` и смена `timezone` влияет только на вычисление «бизнес-дня»/окна партии, а не реинтерпретирует существующие слоты. Если времена хранятся наивно (локально) — переход Дубай→Москва сдвинет всё на −1ч; тогда нужен отдельный шаг (либо остаёмся в Asia/Dubai и ставим эквивалент `06:00`, либо мигрируем времена). Решается на этапе плана чтением `computeBusinessDate`/`computePublishStart` и схемы слотов.

## 10. Параллелизм (пункт 7)

Отдельный мелкий рычаг, без новой логики: `MAX_CONCURRENT_PUBLISHES_PER_RASPBERRY` остаётся env-настройкой, дефолт 3. «Малинки не простаивают» = поднятие лимита (Рома допускает до 8), но **постепенно с мониторингом fail-rate** (раньше снижали до 3 именно из-за роста ошибок). На телефон — по-прежнему 1. Анти-простой логика как таковая в этой задаче не пишется — это тюнинг числа.

## 11. Edge cases

- **Строка без `slot_id`/линии (легаси):** в ручную передать некуда → оставляем как есть (нет регресса авто-пайплайна), либо просто прекращаем ретраи по исчерпании окна.
- **Гонка с #125 / уже-ручной слот:** контроллер пропускает строки, чей слот уже `effective_manual` (не дублируем handoff).
- **`published_no_url` — это успех без ссылки, НЕ падение.** Не считается failed-попыткой, не ретраится; идемпотентность-хук разрулит при возможном будущем диспатче.
- **`process_interrupted` (PM2 deploy-kill) — не баг.** Исключать из счётчика падений (как и из fail-rate метрик).
- **Гонка ре-queue ↔ watchdog:** оба пишут `status='pending'`; идемпотентно (повторный pending безвреден).
- **`fixed_at` в прошлом для давно-упавших:** реанимация срабатывает только если `fixed_at > last_failed_at` конкретного намерения — старые исчерпанные задачи не воскресают массово без нового падения после фикса (или явной операции).

## 12. Kill-switches

| Флаг | Дефолт | Назначение |
|---|---|---|
| `RETRY_ENGINE_ENABLED` | true | Весь контроллер ретраев (жёсткий стоп) |
| `RETRY_MANUAL_HANDOFF_ENABLED` | true | Передача в ручную (откат на «только ре-queue») |
| `IDEMPOTENCY_CHECK_ENABLED` | true | Pre-Share хук дедупа |
| `RETRY_INTERVAL_MINUTES` | 5 | Каденс контроллера (3–5) |
| `RETRY_MAX_PER_CLASS_PER_DAY` | 3 | Лимит ретраев/сутки/класс |
| `RETRY_WINDOW_DAYS` | 2 | Окно авто-попыток |
| `RETRY_CUTOFF_HOUR_MSK` | 23 | Отсечка ретраев |
| `MAX_CONCURRENT_PUBLISHES_PER_RASPBERRY` | 3 | Параллелизм на малинку (есть) |

## 13. Тестирование

- **autowarm `node --test` (mock-pool):**
  - классификатор: код → правильный `error_class`; неизвестный → `unknown`;
  - контроллер: `network` с <3 попыток в окне → ре-queue; ≥3 → ручная; вне окна 2 дней → ручная; `banned`/`ui_changed` → сразу ручная; `fixed_at > last_failed_at` → реанимация даже для `ui_changed`; после 23:00 МСК → не ре-queue;
  - handoff ставит `slot.manual_publish=true` + `manual_handoff_at`, гасит строку; уже-ручной слот пропускается;
  - kill-switches: `RETRY_ENGINE_ENABLED=false` — контроллер no-op; `RETRY_MANUAL_HANDOFF_ENABLED=false` — только ре-queue.
- **Идемпотентность:** терминально-опубликованный `client_publish_id` → pre-Share пропуск; `published_no_url` → ветка скрейпа (мок скрейпера: нашёл → пропуск, не нашёл → публикуем).
- **Live-DB smoke (testbench):** реальная упавшая строка → тик контроллера → ре-queue/handoff; счётчик «3/сутки» соблюдается; миграции применяются/откатываются.

## 14. Зависимости и деплой

- **Реализация гейтится на мёрдж #125** (общая `dispatchPublishQueue`; handoff строится поверх рабочего гарда #125).
- **Cross-repo grep перед деплоем** (общая БД `openclaw`): `client_publish_id`, `error_class`, `manual_publish`, `publish_error_codes` по валидатору и delivery — нет ли коллизий имён/схемы.
- Деплой: миграции (3 ALTER + seed) → `pm2 restart autowarm`; env-флаги по умолчанию включены (числа — дефолтами). Прод-чекаут — с одобрения Данила; без force-push.
- Раскатка осторожная: первый день мониторить, что нет ложных handoff и циклов ре-queue; контроллер за kill-switch.

## 15. Non-goals / YAGNI

- Возврат ручная→авто на следующий день (пункт 10) — **отдельно, вне #108**.
- Отдельные таблицы `publish_intents`/`publish_attempts` (леджер) — не нужны, `publish_tasks` уже служит леджером.
- Смена модели ручной выкладки на phone-level (задача формулирует «телефон», система работает «слот»; слот-уровень покрывает пункты 8–9).
- Третий режим выкладки; авто-балансировка задач между малинками сверх env-лимита.

## 16. Открытые вопросы (решаются на этапе плана)

1. **Хранение времён слотов** (timestamptz vs наивное) — определяет, безопасен ли переход на МСК или нужен шаг миграции времён (§9).
2. **Точная сигнатура скрейпа последних N постов** для ветки сомнения идемпотентности (медиа-хэш #77 vs эвристика) — редкий путь, на дизайн не влияет.
3. **Где именно ставить `client_publish_id`** при создании строки `publish_queue` (auto-path `assignUnicResultsToQueue` + manual force-enqueue endpoint) — все точки вставки.
4. **Финальный сид-маппинг `error_class`** по фактическому содержимому `publish_error_codes` в проде.
