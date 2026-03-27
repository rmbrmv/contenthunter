# MEMORY.md — Long-term Memory

*This is distilled memory. Raw logs live in `memory/YYYY-MM-DD.md`. Update this weekly.*

---

## User
- Роман (@rmbrmv, 295230564) — owner
- Даниил Павлов (@Danil_Pavlov_123, 242574724) — работает над уникализацией и выкладкой (delivery.contenthunter.ru)


---

## Key Decisions
*Important decisions made, why, and what we chose*

<!-- Format:
## YYYY-MM-DD — {decision title}
Chose: {option}
Why: {reason}
-->

## 2026-03-25 — warmer.py: фикс фарминга Instagram (Генри+Даниил)

**Коммиты:** `978fa98`, `a43e9d9`, `e1a1d6b`, `29ef1f5` → GenGo2/delivery-contenthunter

### Что сломано было и как починили:

**1. Переключение аккаунтов** (`switch_instagram_account`, `get_current_instagram_account`):
- `Y<200` не захватывал username с y2=254 → исправлено на `Y<300`
- Координаты профиля: `(990, 2140)` → `(972, 2137)` (кнопка `content-desc="Профиль"`)
- В switcher: новый формат `content-desc="slimvi_1, 7 уведомлений"` не обрабатывался — добавлен
- Всего 5 паттернов поиска + верификация после тапа

**2. Лайки не засчитывались** (`_verify_like`):
- Instagram Reels = SurfaceView, uiautomator dump = <86 байт → `False`
- Теперь: `len(ui) < 200` → `True` (пустой дамп = SurfaceView = доверяем тапу)

**3. Скринкаст при падении**:
- `start_screen_record()` теперь до `verify_and_switch_account`
- При failed → видео в S3, URL в `screen_record_url`

### Правила:
- «не удалось переключиться» → PM2: `Instagram switcher: найдены аккаунты: [...]`
- Лайков = 0 при работающем боте → проверить `search_likes` в progress
- После `pm2 restart autowarm` — задачи в `running` > 5 мин без `updated_at` → сбросить вручную (watchdog 2ч)

## 2026-03-20 — Дедупликация выкладки в autowarm
Chose: проверка дублей по `(content_id, account_username, platform)`
Why: старая проверка по `(content_id, pack_id)` блокировала весь пак — нельзя было публиковать на Instagram/TikTok если видео уже выложили на YouTube внутри того же пака
Files: `workspace-genri/autowarm/server.js` — `assignUnicResultsToQueue()` и `POST /api/publish/queue`

---

## Infrastructure
*Services, paths, ports relevant to this agent*

| What | Where | Notes |
|------|-------|-------|
| autowarm | workspace-genri/autowarm, port 3849 | Publishing pipeline, уникализация |
| delivery frontend | delivery.contenthunter.ru | Раздел uniqualization/unic-results |
| unic-worker | 91.98.180.103, PM2 unic-worker | Воркер уникализации видео |
| validator backend | workspace-genri/validator/backend, port 8000 | FastAPI, uvicorn (без PM2 — nohup) |
| validator frontend | client.contenthunter.ru, /var/www/validator/ | Vue 3 + Vite, билд: npm run build |

---

## Lessons Learned
*Distilled from anti-patterns. Things to always remember.*

- {lesson 1}
- {lesson 2}

---

## Rules Discovered
*Patterns learned from experience that aren't in SOUL.md yet*

- {rule 1}
- {rule 2}

---

## validator — импорт стоп-слов (2026-03-21)

**Что сделано:**
- `POST /api/admin/moderation-rules/import/preview` — загружает CSV/Google Sheets, возвращает заголовки + строки. Параметр `full=true` — все строки
- `POST /api/admin/moderation-rules/import/run` — маппинг + вставка в БД с дедупликацией
- Frontend: `ImportModerationModal.vue` — 3-шаговый флоу (источник → маппинг → результат)
- Кнопка `⬆ Импорт` добавлена в `ModerationRules.vue`
- Дедупликация по `word` (case-insensitive), `category` пустой если не задан, `severity` дефолт `block`
- Коммит: `d65ca55` в GenGo2/validator-contenthunter

## unic-worker — фикс таблицы validator_unic_content (2026-03-23)

**Проблема:** `unic-worker` на сервере `91.98.180.103` падал с ошибкой `relation "unic_content" does not exist` на всех задачах.

**Причина:** в `worker.py` 5 SQL-запросов обращались к `unic_content`, но таблица называется `validator_unic_content`.

**Фикс:** `sed -i 's/FROM unic_content/FROM validator_unic_content/g' /root/unic-worker/worker.py` на удалённом сервере + синхронизирован локальный `workspace-genri/autowarm/unic-worker/worker.py`.

**Правило:** все overlay-контент запросы в `unic-worker` используют таблицу `validator_unic_content` (не `unic_content`).

**SSH доступ к 91.98.180.103:** ключ `~/.ssh/id_backup` (не `id_ed25519`).

---

## validator — фикс генерации превью схем (2026-03-23)

**Проблема:** `POST /api/schemes/generate-previews/{project_id}` → 500, `UndefinedTableError: relation "unic_content" does not exist`

**Причина:** в `backend/src/routers/schemes.py` два SQL-запроса обращались к `unic_content`, но в validator БД эта таблица называется `validator_unic_content`.

**Фикс:** заменено `unic_content` → `validator_unic_content` в двух местах (строки 215 и 221).

**Правило:** все таблицы validator-проекта имеют префикс `validator_`. Исключения — общие таблицы с autowarm: `unic_schemes`, `unic_tasks`, `unic_results`, `unic_settings`.

## validator — генерация описания (2026-03-23)

**Что сделано:**
- `POST /api/upload/generate-description` переключён с LaoZhang (gpt-4o-mini) на **Groq (llama-3.1-8b-instant)**
- Переменная: `GROQ_API_KEY` в `validator/backend/.env`
- Добавлена обработка ошибок: если API вернул ответ без `choices` → 502 вместо 500-краша
- Фронт (`UploadModal.vue`): блокировка если заголовок пустой; ошибки отображаются в UI
- **⚠️ PM2 и .env:** при рестарте через `pm2 restart` — переменные окружения НЕ подгружаются. Нужно: `pm2 delete validator` + `pm2 start bash --name validator -- -c "set -a; source .env; set +a; uvicorn src.main:app --host 0.0.0.0 --port 8000"`

## validator — аккаунты тестового проекта + отключение factory_sync (2026-03-23)

**Проблема:** на странице `/accounts` тестового проекта не отображались аккаунты.

**Причина:** в `factory_inst_accounts` (public schema) для pack_id=249 не было записей. Сам пак существовал в `factory_pack_accounts` и `account_packages`.

**Решение:**
1. Добавлены вручную 3 аккаунта в `public.factory_inst_accounts` (id=1528/1529/1530, pack_id=249):
   - YouTube: `Инакент-т2щ`
   - Instagram: `inakent06`
   - TikTok: `user70415121188138`
2. Защищены через `factory_sync_exclusions` от перезаписи
3. Исправлен `accounts_service.py` — платформа теперь берётся из колонки `platform` (NULLIF/COALESCE), а не угадывается из `instagram_id`
4. **factory_sync.py отключён** — удалена строка из crontab. Работа переведена на локальную public-схему через client.contenthunter.ru и delivery.contenthunter.ru

**Правило:** при ручном добавлении аккаунтов — всегда добавлять в `factory_sync_exclusions`. Платформу писать явно в колонку `platform`.

## validator — фикс account_audience_snapshots (2026-03-23)

**Проблема:** аналитика подписчиков не работала — SQL-запросы обращались к `collected_at` вместо `snapshot_date`.

**Фикс:**
- `backend/src/routers/analytics.py` — `client_analytics_summary()`: 3 места `collected_at` → `snapshot_date`
- `backend/src/services/accounts_service.py` — `get_project_accounts()`: 1 место

**Правило:** `account_audience_snapshots` → колонка даты `snapshot_date`. Не путать с `factory_inst_reels_stats` где `collected_at`.

---

## validator — фикс пустого стоп-слова (2026-03-23)

**Проблема:** `validator_moderation_rules` содержала запись с `word=''` (category `fly agaric`, id=172). Пустая строка всегда содержится в любом тексте → все видео получали статус `blocked`.

**Фикс:**
- `DELETE FROM validator_moderation_rules WHERE id = 172`
- `moderation_service.py`: `if not rule.word or not rule.word.strip(): continue`
- `admin.py` POST + PATCH: HTTP 400 на пустое слово

**Правило:** всегда валидируй `word` перед записью в таблицы стоп-слов. Пустая подстрока — это паттерн, который матчит всё.

---

## validator — BrandPage автосохранение (2026-03-23)

**Фикс:** `textarea` поля (`description`, `target_audience`, `usp`, `content_goals`, `stop_words`) не триггерили автосохранение — только `input` с `@blur` работали. Добавлены `watch`-наблюдатели с guard `if (!loading.value)` на `form` (deep), `keywordsInput`, `selectedVoices`, `selectedFormats`, `socialLinks`.

**Правило:** в Vue 3 для форм — всегда `watch(form, ..., { deep: true })`, не только `@blur` на полях.

После загрузки логотипа (`POST /brand/upload-image`) вызывается `scheduleAutoSave()`.
Файл: `frontend/src/pages/client/BrandPage.vue`

---

## publisher.py — фикс Instagram caption + screen record (2026-03-23)

**Правило:** Instagram caption-поле ищем по классу `EditText`, не по тексту. После тапа — ждём клавиатуру/фокус до 5 попыток. Верификация: `caption[:20] in dump_ui()`.

**Геотеги Instagram:** не реализованы — TODO.

**Screen record ошибки:** теперь пишутся в `events` задачи с деталями.

**Коммит:** `eab1bb6` в GenGo2/delivery-contenthunter

---

## unic-worker — asyncpg JSONB как строка (2026-03-23)

**Правило:** asyncpg иногда возвращает JSONB-колонки как строку. Вызов `dict(str)` итерирует по символам → `ValueError`. Всегда проверять: `if isinstance(val, str): val = json.loads(val)` перед `dict(val)`.

**Диагностика зависших unic_tasks:** `SELECT id, current_status FROM unic_tasks WHERE current_status = 'processing'` — processing >10 мин = зависание. Сброс: UPDATE + `pm2 restart unic-worker` на 91.98.180.103.

---

## autowarm — фаза поиска для обучения ленты (2026-03-24)

**Проблема:** задачи фарминга с 23 марта ставили 0 лайков.
**Причина:** `detect_thematic()` возвращал False на всех видео — лента новых аккаунтов не обучена → нерелевантный контент → нет матча по ключевым словам.
**Решение:** добавлена Фаза 0 (`run_search_phase`) — поиск по ключевым словам в YouTube/TikTok/Instagram в начале каждой сессии (первые 5 дней).

**Новый порядок фаз:**
0. `run_search_phase()` — поиск + лайки в результатах поиска (обучение ленты)
1. `run_competitor_phase()` — конкуренты
2. `watch_content()` — лента рекомендаций

**Правило:** без поиска прогрев неэффективен на новых аккаунтах. Фаза поиска обязательна.
**Коммит:** `9d275ca`, файл: `workspace-genri/autowarm/warmer.py`

---

## TODO
- [ ] Реализовать геотеги для Instagram в `_fill_instagram_caption_and_publish`

---

## 2026-03-20 — Timezone-настройки в AutoWarm (farming)

**Что сделано:**
- Добавлен таб «⚙️ Настройки» в горизонтальное верхнее меню (module: `global-settings`)
- Страница с выбором часового пояса (дефолт: `Asia/Dubai` UTC+4), сохраняется как `farm_timezone` в `autowarm_settings`
- `loadNewTaskForm()` подставляет текущее время в выбранном timezone (не UTC браузера)
- `createTask()` конвертирует введённое время из farm_timezone → UTC ISO перед отправкой на сервер (функция `tzLocalToUTC`)
- `scheduler.js isWorkingHours()`: заменён хардкод МСК на `farm_timezone` из настроек (Intl.DateTimeFormat)

**Коммиты:** `85ea345`, `f7b0ba3` в `GenGo2/delivery-contenthunter`

---

## 2026-03-20 — HelpDrawer в validator

**Что:** добавлен универсальный компонент контекстной справки для admin-раздела validator.

**Файлы:**
- `validator/frontend/src/components/HelpDrawer.vue` — новый компонент
- `validator/frontend/src/pages/admin/ModerationRules.vue` — подключён HelpDrawer

**Детали:**
- Кнопка `?` fixed bottom-right, `bottom: 88px` (выше чат-виджета)
- Роли: только `admin` и `manager` (prop `roles`, по умолчанию `['admin', 'manager']`)
- Рендерит Markdown, поддерживает drag-to-resize, `<Teleport to="body">`
- Паттерн для других разделов: импортировать HelpDrawer, передать title + content (md-строка)

---

## 2026-03-20 — autowarm: фикс YouTube title/description

**Проблема:** ручное добавление задачи YouTube через UI — название видео бралось из description вместо title.

**Решение (GenGo2/delivery-contenthunter, коммиты a713828, 84603d6):**
- `server.js POST /api/publish/queue/manual` — при `unic_result_id` подтягивает поля через `unic_result → unic_task → validator_content`
- YouTube: caption = title (≤100), content_description = description + hashtags отдельно
- Instagram/TikTok: caption = description + hashtags строкой
- `publisher.py` — убран fallback caption→description для YouTube

**Правило:** для YouTube caption = title, description = description. Не смешивать.


---

## AutoWarm — adb_utils.py + ADBKeyBoard (2026-03-20)

Создан общий модуль **`autowarm/adb_utils.py`**:
- `ensure_adbkeyboard(serial, port, host)` — проверяет/устанавливает ADBKeyBoard, активирует IME. Вызывается в `publisher.py` (`run()`) и `warmer.py` (`initialize()`)
- `adb_text(serial, port, host, text)` — ADBKeyBoard → clipboard → ASCII fallback
- APK: `apks/ADBKeyboard.apk` v2.4-dev

Фикс TikTok (задача #254): описание не вводилось из-за `clickable_only=True` — исправлено на `clickable_only=False` + fallback `(540,290)`.

**Коммит:** `ae7f479` в `GenGo2/delivery-contenthunter`

## autowarm — url-poller Instagram: фикс зависания awaiting_url (2026-03-23, Генри)

**Правило:** Instagram API в `server.js` (`scrapeAllVideos`) — только через `curl` (`child_process.exec`). `https.get`/`axios`/`fetch` → 429 из-за блокировки по TLS fingerprint.
Заголовки: `User-Agent: Mozilla/5.0 (iPhone; ...) Instagram/311.0.0`, `X-IG-App-ID: 936619743392459`.
Коммит: `4a20727` в GenGo2/delivery-contenthunter.

## autowarm — фикс записи экрана фарминга (2026-03-23)

**Проблема:** `stop_and_upload_screen_record` в `warmer.py` падал с `pull failed` (пустая ошибка).
**Причина:** `/sdcard/debug_screenshots/` не существовала на телефоне → `screenrecord` не создавал файл.
**Фикс:** добавлен `mkdir -p /sdcard/debug_screenshots &&` перед `screenrecord` в `start_screen_record()`.
**Правило:** всегда создавать целевую директорию на Android перед `screenrecord`.


## validator — async upload validation (2026-03-23, Генри)

POST /api/upload/file теперь возвращает ответ сразу (status=validating), без ожидания транскрипции/OCR.
Валидация бежит в фоне через asyncio.create_task.
Новый endpoint: GET /api/upload/status/{content_id} — для опроса готовности.
Фронт сам делает polling каждые 3 сек и показывает стадии.
Это фикс 502 при загрузке видео через планировщик.
Коммит: 8095ec8 в GenGo2/validator-contenthunter


## autowarm — фикс publish_tasks: отсутствующие колонки (2026-03-23)

**Проблема:** все задачи публикации падали: `column pt.pre_warm_protocol_id does not exist`.

**Причина:** таблица `publish_tasks` в БД не имела колонок `pre_warm_protocol_id` и `post_warm_protocol_id`.

**Фикс:**
```sql
ALTER TABLE publish_tasks
  ADD COLUMN IF NOT EXISTS pre_warm_protocol_id INTEGER,
  ADD COLUMN IF NOT EXISTS post_warm_protocol_id INTEGER;
```

**Правило:** при разворачивании на новом сервере — проверить наличие этих колонок. При ошибке `column ... does not exist` в publish — это первое что проверять.

**Сброс задачи из failed → pending:**
```sql
UPDATE publish_tasks SET status='pending', log='', started_at=NULL WHERE id=<id>;
```

---

## 📅 2026-03-23 — autowarm: фикс массового создания задач фарминга

**От:** Генри (genri-dev)

### Что изменилось в delivery.contenthunter.ru

**Проблема:** «📋 Массовое создание» задач фарминга создавало задачи с пустым полем `account` → все задачи падали в `preflight_failed`.

**Фикс (коммит 6844bb8):**
- Новый endpoint: `POST /api/tasks/bulk` (server.js)
  - Принимает: `{ device_serials[], protocol_id, start_day }`
  - Автоматически определяет платформу из выбранного протокола
  - Для каждого устройства находит нужный аккаунт из `factory_inst_accounts` по платформе
  - Возвращает `{ created[], errors[], total }` с деталями по каждому устройству
- `submitBulkCreate()` в index.html переписан — один запрос вместо N отдельных

**Правило:** при диагностике задач с `preflight_failed` + `account=''` — причина в старом bulk-create или прямом INSERT без account.

## unic-worker: баг с зависанием задач (2026-03-23)

**Файл:** `autowarm/unic-worker/worker.py`, функция `mark_task_error`

**Баг:** при ошибке всех схем задача зависала в `processing` навсегда.
Причина: `dict(row['meta'])` → ValueError когда asyncpg возвращал JSONB как строку.

**Фикс (коммит `3352057`):** безопасный парсинг — isinstance str → json.loads.

**Диагностика зависших задач:**
```sql
SELECT id, current_status FROM unic_tasks WHERE current_status='processing';
-- Если висит >10 мин — сброс:
UPDATE unic_tasks SET current_status='pending', schemes_done=0, schemes_error=0 WHERE id=<id>;
```
Затем `pm2 restart unic-worker` на 91.98.180.103.

## validator — генерация описания переключена на Claude Haiku (2026-03-24)

**Эндпоинт:** `POST /api/upload/generate-description` (кнопка «✨ Сгенерировать» в UploadModal)

**Было:** Groq API, модель `llama-3.1-8b-instant` → GROQ_API_KEY
**Стало:** Anthropic Claude `claude-haiku-4-5` через OpenClaw-подписку → ANTHROPIC_API_KEY

- Ключ: `anthropic_genri` из `/root/.openclaw/secrets.json` (`providers.anthropic.anthropic_genri`)
- Файл: `validator/backend/src/routers/upload.py`
- SDK: `anthropic==0.84.0` (уже установлен)
- Коммит: `2be7924` → GenGo2/validator-contenthunter

**Правило:** все задачи AI-генерации текста в validator → Claude Haiku через ANTHROPIC_API_KEY (OpenClaw-подписка).

## delivery — раздел «Исходники» (unic-sources): рефакторинг фильтров (2026-03-24)

**Что изменилось в `workspace-genri/autowarm/public/index.html`:**
- Sticky-шапка таблицы: убран `overflow-hidden` с контейнера, добавлен `overflow-auto + max-height: calc(100vh - 180px)` на внутренний div
- Строка фильтров `sticky top-[40px]` (было 45px — подогнано под реальную высоту заголовка)
- Блок фильтров над таблицей — **удалён**
- Поле «Проект»: input → `<select id="src-cf-project">` (заполняется в `loadUnicSources()`)
- Новые date-фильтры: `src-cf-created-from/to` (Загружено), `src-cf-pub-from/to` (Дата публ.)
- Кнопка «✕ Сброс» в строке фильтров → `srcClearFilters()`
- «Показано X из Y» + «↻ Обновить» — в заголовочной строке секции
- `srcFilter()` — убраны `src-f-date-from/to`, `projTop`; добавлены 4 date-фильтра + точное сравнение по проекту
- `srcClearFilters()` — обновлены id полей
- `HELP_CONTENT['unic-sources']` — обновлена справка в интерфейсе
- `README.md` автоварма — добавлен блок про раздел Исходники

**Правило sticky в таблицах:** `overflow-hidden` на родителе ломает position:sticky. Скролл-контейнер должен быть один — с `overflow-auto` + `max-height`.

## publisher.py — AI Unstuck agent + Instagram caption fix (2026-03-24)

**Сервис:** autowarm, файл `workspace-genri/autowarm/publisher.py`
**Коммиты:** `432a6b8`, `9c7238d`, `52dfdb8`, `aac31c0` → GenGo2/delivery-contenthunter

### Фикс Instagram caption
Instagram Reels рендерит поле описания через WebView — EditText не виден UIAutomator. Тап по placeholder «Добавьте подпись» не фокусировал поле → текст не вводился.
**Теперь:** тапаем по 5 координатам-кандидатам пока не появится клавиатура. XML-верификация убрана (false negative для WebView).

### AI Unstuck Agent
Новый метод `ai_unstuck(goal, max_attempts)` — когда publisher зависает на неизвестном экране, отправляет скриншот + историю шагов в Groq Vision → получает одно действие (tap/keyevent/wait) → выполняет.

Работает для Instagram, TikTok, YouTube. Каждое решение AI логируется в events задачи.

**Диагностика:** если видишь в логе задачи строки `🤖 AI Unstuck` — значит сработал AI-агент для разблокировки. Смотри reason чтобы понять что происходило на экране.

### Правило: Instagram dump_ui ≠ текст из WebView
Никогда не проверять наличие введённого текста через `dump_ui` для Instagram caption. WebView не отдаёт введённый текст в XML — всегда false negative.

## warmer.py — preflight ADB + retry initialize + AI Unstuck (2026-03-25)

**Коммиты:** `b036262`, `e896809` → GenGo2/delivery-contenthunter
**Файл:** `workspace-genri/autowarm/warmer.py`

### Что сделано
1. **`preflight_check()`** — добавлен шаг #0: `is_online()` перед всеми проверками.
   При недоступном ADB → ранний return с `preflight_failed`.

2. **`_wait_for_app()`** — timeout 30 → **60 сек**

3. **`initialize()`** — теперь 3 попытки:
   - Попытка 1: стандартный запуск (60 сек)
   - Попытка 2: BACK + HOME + force-stop + restart
   - Попытка 3: `_ai_unstuck_initialize()` — Groq Vision разбирает что на экране

4. **`_ai_unstuck_initialize(package, max_attempts=4)`** — новый метод.
   Скриншот → Groq llama-4-scout-17b-16e-instruct → JSON {action, x, y / key / secs, reason} → выполнить.

**Правило:** при ошибке `preflight_failed: Устройство ... недоступно` — физически проверить ADB-подключение. При `failed: Не удалось перезапустить` — смотреть события задачи на строки `🤖 AI Unstuck (initialize)`.

## autowarm — фикс счётчика лайков фарминга (2026-03-25)

**Проблема:** задача фарминга ставила лайки (10 штук в Фазе 0 — поиск), но в UI и БД показывалось `likes=0`.

**Причина:** `watch_content()` (Фаза 2) писал `progress.likes = likes_done` где `likes_done=0` (в ленте только реклама) → перезаписывал накопленные `search_likes=10` нулём.

**Фикс (коммит `ac129be`):**
- `run()`: инициализирует `self._search_likes_today = 0`
- После Фазы 0: `self._search_likes_today = search_likes`
- Основной цикл `_update_progress`: `likes = likes_done + self._search_likes_today`
- Summary Фазы 2: `total_likes = likes_done + search_likes` + разбивка в логе `(лента=N, поиск=M)`

**Правило:** `progress.likes` = ВСЕГДА суммарные лайки (Фаза 0 поиск + Фаза 2 лента). `progress.search_likes` = только поиск. При `likes=0` при наличии лайков в логе → смотреть `search_likes` в progress.

## validator — фикс ANTHROPIC_API_KEY (2026-03-25)

**Проблема:** `POST /api/upload/generate-description` падал с `401 invalid x-api-key`.

**Причина:** ключ `anthropic_genri` из `/root/.openclaw/secrets.json` протух.

**Решение:** в `validator/backend/.env` заменён ключ `ANTHROPIC_API_KEY` на `anthropic_default` (рабочий).

**Статус ключей Anthropic (2026-03-25):**
- `anthropic_default` → ✅ рабочий (используется в validator)
- `anthropic_genri` → ❌ протух
- `anthropic_manual` → ❌ протух
- `anthropic_systematika` → ❌ протух

**Правило:** при 401 в generate-description — проверить все ключи через curl, использовать первый рабочий. Перезапустить PM2 с `source .env` (не просто `pm2 restart`).

---

## autowarm delivery.contenthunter.ru — pre-commit защита JS (2026-03-25)

**Проблема (3 инцидента):** неэкранированные backtick (`` ` `` и `` ``` ``) внутри `HELP_CONTENT` в `autowarm/public/index.html` ломали JS template literal → сайдбары и кнопка Help переставали работать.

**Что такое HELP_CONTENT:** большой JS-объект в конце `public/index.html`, все значения — template literal (обёрнуты в backtick). Markdown-текст справки для каждого раздела интерфейса.

**Правило:** внутри HELP_CONTENT нельзя:
- Писать `` ` `` → нужно `\\\``
- Писать ` ``` ` или ` ```sql ` → нужно `\\\`\\\`\\\`` / `\\\`\\\`\\\`sql`

**Решение:**
- Создан `autowarm/scripts/validate_html_js.js` — валидирует JS + делает lint HELP_CONTENT
- Установлен **pre-commit хук**: блокирует коммит с невалидным `index.html`

**Ручная проверка:**
```bash
node /root/.openclaw/workspace-genri/autowarm/scripts/validate_html_js.js \
  /root/.openclaw/workspace-genri/autowarm/public/index.html
```

**Симптом сломанного сайдбара:** верхнее меню работает, боковые пункты не кликаются, кнопка `?` не реагирует.

## autowarm — фикс фильтров таблицы задач фарминга (2026-03-25)

**Проблема:** фильтры по столбцам в разделе «Задачи» сбрасывались каждые 10 сек — авто-обновление (`setInterval loadTasks`) перерисовывало таблицу со всеми данными, игнорируя установленные значения дропдаунов.

**Фикс (коммит `39647b1`, файл `autowarm/public/index.html`):**
- `loadTasks()` → вместо `renderTasksTable(toRender, _tasksPage)` теперь вызывает `filterTasksTable(_tasksPage)`
- `filterTasksTable(page?)` получил опциональный параметр `page` → передаётся в `renderTasksTable`
- Фильтры: устройство (`tf-device`), проект (`tf-project`), пак (`tf-pack`), аккаунт (`tf-account`), соцсеть (`tf-network`), статус (`tf-status`)

**Правило:** при авто-обновлении таблиц с фильтрами — всегда прогонять через функцию фильтрации, никогда не рендерить `_all` массив напрямую.

## autowarm — 4 баг-фикса надёжности фарминга (2026-03-25)

**Коммит:** `7d145f5` → GenGo2/delivery-contenthunter  
**Файлы:** `warmer.py`, `scheduler.js`

### Суть изменений:

**1. `detect_ad` — ужесточён (warmer.py)**
Раньше искал слово «реклам» в весь XML дамп → ложные срабатывания на системные строки.
Теперь: только `text=` / `content-desc=` атрибуты. Счётчик `_consecutive_ads`: >4 подряд → сброс + warning.
Симптом до фикса: 6–11 подряд «Реклама — пропуск» при нормальном контенте.

**2. `like_content` — верификация через UI (warmer.py)**
Добавлен `_verify_like()`: после тапа проверяем что лайк отобразился в UI (Unlike/selected=true).
Лайк не засчитывается если UI не подтвердил. Устраняет ложные «Лайк поставлен» когда бот был в неправильном приложении.

**3. `verify_and_switch_account` — retry 3×5с (warmer.py)**
Раньше: не смог прочитать аккаунт → тихий continue → бот работал вслепую.
Теперь: 3 попытки с паузой 5с. Провал всех → задача завершается с `failed`.

**4. Watchdog зависших задач (scheduler.js)**
`watchdogStuckTasks()` в каждом `tick()` (1 раз/мин): `running` > 2ч без `updated_at` → `failed` + запись в events.

### Правило диагностики:
- «Лайков нет, хотя в логе есть» → до фикса: не было верификации. После фикса: смотреть «Лайк не подтверждён» в events
- «Реклама 10+ раз подряд» → смотреть «Аномальная серия рекламы» в events
- Задача в running >2ч → watchdog переведёт в failed, не нужно сбрасывать вручную

---

## publisher.py — фикс публикации Instagram/TikTok/YouTube (2026-03-25, Юра)

**Коммит:** `07d47f7` в GenGo2/delivery-contenthunter

### Instagram — аудио-диалоги после Поделиться

Два разных экрана, два разных обработчика:

| Экран | Маркеры | Действие |
|---|---|---|
| «Название аудиодорожки» | `Название аудиодорожки`, `Оригинальное аудио`, `Дайте своей аудиодорожке уникальное название` | `KEYCODE_BACK` → пропускает, публикация продолжается |
| «Редактировать связанное видео Reels» | `Редактировать связанное`, `Название этого видео Reels появится` | `KEYCODE_BACK` → возврат на caption screen |

**Не делать:** не тапать ✓ (справа вверху) — там «Изменить видео Reels» → открывает галерею.

**_caption_markers** не должны содержать `Хэштеги`/`Связать видео Reels` — эти слова есть в XML одновременно с аудио-диалогом. Используем только: `Новое видео Reels`, `Добавьте подпись`, `Нажмите дважды, чтобы изменить фото обложки`.

**Кнопка Поделиться fallback:** `(799, 2087)` — из XML `bounds=[563,2025][1035,2149]`.

### TikTok — фокус поля описания

Поле рендерится через Canvas/WebView → не `clickable=true` в XML. Перебираем координаты `(540,290)/(540,350)/(540,400)/(540,250)` пока не откроется клавиатура (проверяем через `dumpsys input_method | grep mInputShown`).

### YouTube — экран «Добавьте информацию»

В новых версиях YouTube Shorts поля `Название`/`Описание` показываются прямо на экране «Добавьте информацию». Старый код сразу жал «Загрузить» → публикация без названия. Теперь сначала заполняем поля, потом Загрузить.

### Диагностика публикации

**Правило:** при проблемах с публикацией — тянуть скринкаст с устройства: `adb -H <host> -P <port> -s <serial> pull /sdcard/debug_screenshots/screenrec_<id>_*.mp4`. Видео показывает точный экран в момент ошибки.
