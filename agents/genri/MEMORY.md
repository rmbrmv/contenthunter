
## publisher.py — Instagram аудиодиалог + YouTube заголовок (2026-03-25, Юра+Даниил)

### Instagram: диалог «Название аудиодорожки» (коммит `3c0a09a`)
**Баг:** после нажатия «Поделиться» появлялся ModalActivity с диалогом аудиодорожки. Код нажимал `KEYCODE_BACK` → это **отменяло публикацию** → возврат на caption screen с пустым полем → публиковалось без описания.

**Фикс:** убраны `Назад`/`KEYCODE_BACK` из обработчика аудиодиалога. Теперь ищем только `Пропустить`/`Skip`/`Не сейчас` — эти кнопки продолжают публикацию.

**Страховка:** если возврат на caption screen всё же произошёл — caption вводится заново автоматически перед повторным «Поделиться».

**Правило:** в диалоге аудиодорожки Instagram **никогда** не использовать BACK — только Skip/Пропустить.

### YouTube: заголовок/описание не заполнялось (коммит `053e904`)
**Баг:** на экране с полем «Название» одновременно видна кнопка «Загрузить». Код проверял `Загрузить` первым → нажимал без заполнения.

**Фикс:** блок `['Название', 'Title', 'Add a title']` теперь идёт **первым** в цикле редактора, до общего `Загрузить`. Порядок нарушать нельзя.

**Правило:** YouTube publisher — Title/Description check всегда перед Upload check.

---

## autowarm — счётчик лайков фарминга (2026-03-25)

`progress.likes` = ВСЕГДА суммарные лайки (Фаза 0 поиск + Фаза 2 лента).
`progress.search_likes` = лайки только Фазы 0 (для аналитики).
`self._search_likes_today` — атрибут Warmer, инициализируется в `run()`, задаётся после `run_search_phase()`, суммируется в `_update_progress` основного цикла.

**Симптом бага:** `likes=0` при наличии лайков в логе → проверить `search_likes` в progress.
**Коммит:** `ac129be`

---

## Инфраструктура: внешний сервер 91.98.180.103

**Политика**: ресурсоёмкие задачи (ffmpeg, обработка видео) — на 91.98.180.103, он мощнее.

- SSH по паролю: `sshpass -p 'MNcwMPCiyiYtM5' ssh root@91.98.180.103`
- SSH по ключу: `ssh -i ~/.ssh/id_backup root@91.98.180.103` ← предпочтительный способ
- **unic-worker** работает ТОЛЬКО там — `/root/unic-worker/`, PM2
- Локально unic-worker НЕ запускать — конкурирует и роняет задачи
- Внешний IP основного сервера для БД: `72.56.107.157:5432`
- PostgreSQL в Docker: `host all all all scram-sha-256` — внешние коннекты разрешены

### unic-worker: таблица validator_unic_content (2026-03-23)
Worker.py на 91.98.180.103 обращается к `validator_unic_content` (НЕ `unic_content`).
Было: `FROM unic_content` → Стало: `FROM validator_unic_content` (5 мест в worker.py).
Коммит: `workspace-genri/autowarm/unic-worker/worker.py` обновлён и запушен.
**Правило:** любые запросы к overlay-контенту в unic-worker используют `validator_unic_content`.

---

## validator (client.contenthunter.ru) — Auth

### JWT и авторизация (2026-03-22)
- JWT TTL: **168ч (7 дней)** — было 24ч. Файл: `validator/backend/src/config.py`, `jwt_expire_hours`
- Telegram авторизация настроена для admin: `telegram_id=242574724` (Даниил Павлов @Danil_Pavlov_123)
- Пароль admin: `hunter2025` (хранится в `validator/backend/.env`, поле ADMIN_PASSWORD)
- PM2 процесс `validator`: запущен, порт 8000. **⚠️ Правильный запуск (с подгрузкой .env):**
  ```bash
  cd /root/.openclaw/workspace-genri/validator/backend
  pm2 delete validator
  pm2 start bash --name validator -- -c "set -a; source .env; set +a; uvicorn src.main:app --host 0.0.0.0 --port 8000"
  ```
  `pm2 restart validator` — НЕ подгружает переменные окружения из .env!

## validator (client.contenthunter.ru)

### Массовый импорт стоп-слов (добавлен 2026-03-21)
- Кнопка `⬆ Импорт` в разделе /admin/moderation
- Frontend компонент: `validator/frontend/src/components/ImportModerationModal.vue`
- 3 шага: источник (CSV или Google Sheets) → маппинг колонок → результат с деталями
- API: `POST /api/admin/moderation-rules/import/preview` + `POST /api/admin/moderation-rules/import/run`
- Дедупликация по `word` (case-insensitive), `category` остаётся пустым если не задан, `severity` дефолт `block`
- Google Sheets: нужен публичный доступ (Читатель), парсится через `export?format=csv`
- Таблица в БД: `validator_moderation_rules` (поля: id, category, word, severity, recommendation, is_active, created_at)

### Фикс JSONB asyncpg (2026-03-21)
asyncpg не принимает Python list/dict в JSONB — нужен явный `json.dumps()`.
Правило: все JSONB-поля (keywords, social_links, extra, и любые dict/list → JSONB) сериализовать через `json.dumps(value) if value else None`.
Git: `eb77e9f` → GenGo2/validator-contenthunter

### Фикс генерации превью схем (2026-03-23)
`POST /api/schemes/generate-previews/{project_id}` падал с 500 — неверное имя таблицы `unic_content` вместо `validator_unic_content`.
Файл: `validator/backend/src/routers/schemes.py` — два запроса исправлены.
**Правило:** в validator БД все таблицы проекта имеют префикс `validator_`. `unic_schemes`, `unic_tasks` и т.д. — исключения (они общие с autowarm).

### Фикс хромокея в превью схем (2026-03-23)
Хромокей (#00ff30) не вырезался в превью — в `validator_unic_content.chromakey_color` был неверный цвет `0x19af3e`.
Исправлено: `UPDATE validator_unic_content SET chromakey_color = '0x00ff30' WHERE content_type = 'video'` (10 записей).
**Правило:** цвет хромокея всех оверлей-видео = `0x00ff30`. FFmpeg: `chromakey=0x00ff30:0.12:0.02` + `format=rgba`.

### Фикс account_audience_snapshots: snapshot_date (2026-03-23)
Колонка даты в `account_audience_snapshots` — **`snapshot_date`** (НЕ `collected_at`).
`collected_at` есть только в `factory_inst_reels_stats`.
Исправлено в: `analytics.py` (client_analytics_summary), `accounts_service.py` (get_project_accounts).
**Правило:** `account_audience_snapshots` → `ORDER BY snapshot_date DESC`, фильтрация по `snapshot_date`.

### BrandPage: автосохранение (2026-03-23)
**Фикс:** `textarea` поля (`description`, `target_audience`, `usp`, `content_goals`, `stop_words`) не имели обработчиков и не триггерили автосохранение. Данные откатывались при переходе в другой раздел.
**Решение:** добавлены `watch`-наблюдатели с guard `if (!loading.value)` на `form` (deep), `keywordsInput`, `selectedVoices`, `selectedFormats`, `socialLinks`.
**Правило:** в Vue 3 для форм — `watch(form, ..., { deep: true })`, не полагаться только на `@blur`.
После `POST /brand/upload-image` вызывается `scheduleAutoSave()`.
Файл: `validator/frontend/src/pages/client/BrandPage.vue`

### Компонент HelpDrawer (добавлен 2026-03-20)
- Файл: `validator/frontend/src/components/HelpDrawer.vue`
- Универсальная контекстная справка — кнопка `?` (fixed bottom-right) + выдвижная панель
- По умолчанию видна только ролям `admin` и `manager`, скрыта для `client`
- Кнопка позиционирована `bottom: 88px` — выше чат-виджета SupportChat (чтобы не перекрывались)
- Поддерживает Markdown, drag-to-resize, Teleport to body
- Первое подключение: `ModerationRules.vue` (раздел /admin/moderation)
- При добавлении нового раздела — импортировать HelpDrawer, передать `title` и `content` (Markdown)

---

## AutoWarm — Глобальные настройки и timezone (2026-03-20)

Добавлен модуль **⚙️ Настройки** в горизонтальное верхнее меню delivery.contenthunter.ru.

**Ключ:** `farm_timezone` в `autowarm_settings` (дефолт: `Asia/Dubai`)

### Что изменилось:
- `loadNewTaskForm()` — при открытии подставляет текущее время по `farm_timezone` (не UTC браузера)
- `createTask()` — конвертирует введённое время из `farm_timezone` → UTC ISO перед отправкой (функция `tzLocalToUTC`)
- `scheduler.js isWorkingHours()` — теперь читает `farm_timezone` из настроек вместо хардкода МСК UTC+3

### Правило для разработчиков:
> Все новые datetime-поля в формах фарминга должны:
> 1. Подставлять дефолт через `toLocalDatetimeString(new Date(), await getFarmTimezone())`
> 2. Конвертировать перед отправкой через `tzLocalToUTC(rawValue, tz)`

**Коммиты:** `85ea345`, `f7b0ba3` в `GenGo2/delivery-contenthunter`

---

## AutoWarm — adb_utils.py + ADBKeyBoard (2026-03-20)

Создан общий модуль **`autowarm/adb_utils.py`** для ввода текста и управления IME.

### Функции:
- `ensure_adbkeyboard(serial, port, host)` — проверяет/устанавливает ADBKeyBoard APK (`apks/ADBKeyboard.apk`), активирует IME
- `adb_text(serial, port, host, text)` — ввод текста: ADBKeyBoard → clipboard → ASCII fallback

### Подключено:
- `publisher.py` — `ensure_adbkeyboard` в `run()`, `adb_text()` делегирует в модуль
- `warmer.py` — `ensure_adbkeyboard` в `initialize()`, `_type_cyrillic()` делегирует в модуль

### Фикс TikTok (задача #254):
Поле описания TikTok не заполнялось — `tap_element(clickable_only=True)` не находил элемент в Canvas/WebView. Исправлено: `clickable_only=False` + fallback tap `(540, 290)`.

**Коммит:** `ae7f479` в `GenGo2/delivery-contenthunter`

---

## unic-worker: фикс зависания задач в processing (2026-03-23)

**Симптом:** задачи уникализации висят в `processing` бесконечно, `schemes_error` ненулевой.

**Причина:** `mark_task_error` (worker.py строка 86) падала с `ValueError` — asyncpg возвращал JSONB `meta` как строку, `dict(строка)` = итерация по символам → исключение → задача не переходила в `error`.

**Фикс (коммит `3352057`):** безопасный парсинг: `isinstance(raw_meta, str) → json.loads`.

**Диагностика / сброс зависших задач:**
```sql
SELECT id, current_status FROM unic_tasks WHERE current_status='processing';
UPDATE unic_tasks SET current_status='pending', schemes_done=0, schemes_error=0, error_message=NULL WHERE id IN (...);
```
+ `pm2 restart unic-worker` на 91.98.180.103.

---

## validator — генерация описания переключена на Groq (2026-03-23)

**Эндпоинт:** `POST /api/upload/generate-description` (в `UploadModal.vue`, кнопка «✨ Сгенерировать»)

**Было:** LaoZhang API, модель `gpt-4o-mini` — периодически падал с `KeyError: 'choices'` (ответ без `choices` при rate limit/сбое → 500)

**Стало:** Groq API, модель `llama-3.1-8b-instant`
- Переменная: `GROQ_API_KEY` в `validator/backend/.env`
- Файл: `validator/backend/src/routers/upload.py`

**Улучшения:**
- Обработка ошибок: нет `choices` в ответе → 502 с деталями вместо 500-краша
- Фронт (`UploadModal.vue`): пустой заголовок блокирует генерацию; ошибки отображаются в UI

## validator — async background validation (2026-03-23)

### Проблема
`POST /api/upload/file` давал 502 — валидация (Groq Whisper + OCR + модерация) занимала 60–120 сек, Caddy таймаутил.

### Решение
- **Бэкенд:** `POST /api/upload/file` возвращает сразу (`status=validating`), валидация бежит в `asyncio.create_task` с отдельной сессией `AsyncSessionLocal`
- **Новый endpoint:** `GET /api/upload/status/{content_id}` — `{is_done, status, validation}`
- **Фронт:** polling каждые 3 сек с анимированными стадиями, таймаут 5 мин

**Правило:** длинные задачи → `asyncio.create_task` + **новая** `async with AsyncSessionLocal()`, никогда не переиспользовать request-сессию.
**Коммит:** `8095ec8`

---

## validator — UsersManagement (/admin/users) — обновление (2026-03-23)

### Sticky header + сортировка + фильтры
Файл: `validator/frontend/src/pages/admin/UsersManagement.vue`

- **Sticky header**: таблица в `overflow-auto max-h-[calc(100vh-180px)]`, `<thead>` → `sticky top-0 z-10`
- **Сортировка**: `sortCol` / `sortDir` ref, `toggleSort(col)`, компонент `SortIcon` (render fn). Столбцы: `name`, `role`, `project`, `status`
- **Фильтры** (строка под заголовками):
  - Пользователь — input, по login + first_name
  - Роль — select enum
  - Проект — select из sortedProjects, фильтр по `project_id` / `project_ids[]`
  - Статус — select active/inactive
  - Кнопка «✕ Сбросить» при `hasFilters`
- Коммиты: `defb4f3`, `f7ce54a` → GenGo2/validator-contenthunter

### Создание client-пользователей (2026-03-23)
Скрипт: `scripts/create_client_users.py`
Создано 38 пользователей (все активные проекты). Логин = `api_name`, пароль = `123456789`, `role=client`, `project_id` привязан.

## validator — аккаунты тестового проекта + отключение factory_sync (2026-03-23)

**Проблема:** на `/accounts` тестового проекта не отображались аккаунты.

**Причина:** `factory_inst_accounts` (public) для pack_id=249 был пустым.

**Решение:**
1. Добавлены вручную 3 аккаунта (id=1528–1530, pack_id=249):
   - YouTube: `Инакент-т2щ` | Instagram: `inakent06` | TikTok: `user70415121188138`
2. Защищены через `factory_sync_exclusions`
3. Исправлен `accounts_service.py` — платформа из `fia.platform` (COALESCE/NULLIF), не из `instagram_id`
4. **factory_sync.py отключён** (строка из crontab удалена) — работа через локальную public-схему

**Правило:** при ручном добавлении аккаунтов — обязательно `factory_sync_exclusions`. Платформу писать явно.

## autowarm — url-poller Instagram: curl вместо https.get (2026-03-23)

**Проблема:** Instagram-задачи зависали в `awaiting_url` на часы. url-poller (server.js `checkProcessingTasks`) получал от Instagram API **429** при запросе через Node.js `https.get` — блокировка по TLS fingerprint.

**Фикс (коммит `4a20727`):** В `scrapeAllVideos` (platform === 'Instagram') заменили `axios_fetch` на `curl` через `child_process.exec`:
```js
require('child_process').exec(
  `curl -s -m 15 -H "User-Agent: Mozilla/5.0 (iPhone; ...Instagram/311.0.0" -H "X-IG-App-ID: 936619743392459" ...`,
  { timeout: 20000 }, ...
)
```

**Правило:** для Instagram API в server.js **всегда использовать curl**. `https.get`, `axios`, `node-fetch` → 429. curl с iPhone UA → 200. Поллер теперь закрывает Instagram awaiting_url за ≤ 2 минуты.

## autowarm — Правило: HELP_CONTENT и backtick (2026-03-23)

В `public/index.html` HELP_CONTENT — JS template literal (`\`...\``).
**Нельзя использовать backtick внутри текста HELP_CONTENT** — это ломает template literal → SyntaxError → `helpSetSection` не определяется → весь `nav()` перестаёт работать → все сайдбары молчат.

Симптом: верхнее меню (switchModule) работает, сайдбары и кнопка `?` — нет.

Правило: вместо `` `path` `` писать просто `path`; вместо `` `code` `` использовать `\\\`code\\\`` (экранирование).

Коммиты-фиксы: `4911b96`, `6f7066c`, `6a690cd` (2026-03-23 — Instagram caption диагностика в HELP_CONTENT['publishing'])

---

## autowarm — ETag кэширование статики (2026-03-23)

`express.static` отдавал ETag + `Cache-Control: no-cache` — браузер всё равно получал 304 и старый файл.
Исправлено: `etag: false, lastModified: false` в настройках `express.static` (`server.js`).
Коммит: `dacf92f`

---

## autowarm — global-settings в списках сайдбаров (2026-03-23)

При добавлении нового модуля в верхнее меню — нужно добавить его ID во **все три** списка скрытия сайдбаров:
1. `switchModule()` — уже был
2. `nav()` — строка ~3722
3. `openEditor()` — строка ~4105

Иначе сайдбар нового модуля не скрывается при переходах → два сайдбара → клики мимо.
Коммит-фикс: `eb134bd`

---

## autowarm — запись экрана фарминга (screen recording)

**Как работает:** `warmer.py` → `start_screen_record()` запускает `screenrecord` на Android-устройстве, при завершении `stop_and_upload_screen_record()` делает `adb pull`, заливает в S3 Beget (`1cabe906ea6e-gengo`, prefix `autowarm/screenrecords/farming/`), URL сохраняется в `autowarm_tasks.screen_record_url` и в `events` JSONB. После загрузки файл удаляется с устройства.

**Важно:** директория `/sdcard/debug_screenshots/` создаётся автоматически командой `mkdir -p` перед `screenrecord`. Без этого запись молча падает.

**Отключить:** env var `FARM_SCREEN_RECORD=false`, затем `pm2 restart autowarm`.

**Диагностика:** если `pull failed` — проверить что директория `/sdcard/debug_screenshots/` создалась на устройстве. Если нет — убедиться что `mkdir -p` выполняется в `start_screen_record()`.

## autowarm — фикс publish_tasks: отсутствующие колонки (2026-03-23)

**Проблема:** все задачи публикации падали: `column pt.pre_warm_protocol_id does not exist`.

**Причина:** таблица `publish_tasks` не имела колонок `pre_warm_protocol_id` и `post_warm_protocol_id`, которые `publisher.py` запрашивает в `run_publish_task()`.

**Фикс (уже применён):**
```sql
ALTER TABLE publish_tasks
  ADD COLUMN IF NOT EXISTS pre_warm_protocol_id INTEGER,
  ADD COLUMN IF NOT EXISTS post_warm_protocol_id INTEGER;
```

**Смысл колонок:** ID протоколов прогрева аккаунта до/после публикации. `NULL` = используется только `pre_warm_videos`/`post_warm_videos` (количество видео по умолчанию).

**Правило:** при разворачивании autowarm на новом сервере — проверить наличие этих колонок. Если нет — выполнить ALTER TABLE выше.

**Диагностика задач со статусом failed:** сбросить в pending:
```sql
UPDATE publish_tasks SET status='pending', log='', started_at=NULL WHERE id=<id>;
```

## autowarm — Массовое создание задач фарминга: фикс account (2026-03-23)

**Проблема:** `POST /api/tasks/bulk` не существовал — `submitBulkCreate()` слал POST `/api/tasks` без поля `account` → задачи создавались с `account=NULL` → `preflight_failed`.

**Решение:**
- Новый endpoint `POST /api/tasks/bulk` (server.js) — принимает `{device_serials[], protocol_id, start_day}`, сам подбирает аккаунт из `factory_inst_accounts` по платформе протокола
- `submitBulkCreate()` (index.html) переписан — один запрос вместо N, отображает детали ошибок

**Правило:** аккаунт в bulk-задачах подбирается автоматически по платформе протокола. Endpoint: `POST /api/tasks/bulk`.
**Коммит:** `6844bb8` в GenGo2/delivery-contenthunter

## publisher.py — фикс Instagram caption (2026-03-23, Юра+Даниил)

**Проблема:** задача #11 (`inakent06`, Instagram Reel) опубликовала видео без описания — поле caption оставалось пустым.

**Причина:** `_fill_instagram_caption_and_publish` искал поле по тексту «подпись»/«caption» — это placeholder `TextView`, не `EditText`. Тап не фокусировал поле → клавиатура не открывалась → `adb_text` уходил в пустоту.

**Фикс (коммит `eab1bb6`):**
1. Поиск поля: сначала `EditText` по классу, fallback — по тексту «подпись»/«caption»
2. Ожидание фокуса: после тапа ждём клавиатуру или `focused="true"` на EditText (до 5 попыток × 1с)
3. Если фокус не появился — повторный тап чуть ниже (+30px)
4. Верификация: после `adb_text` делаем `dump_ui` и проверяем `caption[:20] in ui`. Если нет — повтор
5. `log_event` на каждом шаге — отладка без скриншотов

**Дополнительно:**
- `stop_and_upload_screen_record`: `log_event` при ошибках `adb pull` и S3 upload
- `run()`: `mkdir -p /tmp/publish_media` в начале каждой задачи

**Правило:** поле caption в Instagram — всегда искать по классу `EditText`, не по placeholder-тексту.
**Геотеги Instagram:** не реализованы (TODO).

## validator — генерация описания переключена на Claude Haiku (2026-03-24)

**Эндпоинт:** `POST /api/upload/generate-description` (кнопка «✨ Сгенерировать» в UploadModal)

**Было:** Groq API, модель `llama-3.1-8b-instant` → GROQ_API_KEY
**Стало:** Anthropic Claude `claude-haiku-4-5` через OpenClaw-подписку → ANTHROPIC_API_KEY

- ~~Ключ: `anthropic_genri`~~ → **⚠️ ПРОТУХ 2026-03-25**
- **Актуально:** использовать `anthropic_default` из `/root/.openclaw/secrets.json`
- Файл: `validator/backend/src/routers/upload.py`
- SDK: `anthropic==0.84.0` (уже установлен)
- Коммит: `2be7924` → GenGo2/validator-contenthunter

**Статус ключей Anthropic (2026-03-25):** `anthropic_default` ✅, `anthropic_genri` ❌, `anthropic_manual` ❌, `anthropic_systematika` ❌

**Правило:** все задачи AI-генерации текста в validator → Claude Haiku через ANTHROPIC_API_KEY. При 401 — проверить ключи, использовать `anthropic_default`.

## delivery — раздел «Исходники» (unic-sources): рефакторинг фильтров (2026-03-24)

**Что изменилось в `workspace-genri/autowarm/public/index.html`:**
- Заголовки и строка фильтров таблицы — **sticky** при скролле (убран `overflow-hidden` с контейнера, добавлен `overflow-auto + max-height` на внутренний div)
- Блок фильтров **над** таблицей — **удалён полностью**
- Поле «Проект» в строке фильтров: текстовый input → **`<select>`** (заполняется динамически из `srcData`)
- Колонки «Загружено» и «Дата публ.» — добавлен фильтр **по диапазону дат** (два date-input «с / по» в ячейке)
- В строке фильтров в колонке «Действия» — кнопка **✕ Сброс** (`srcClearFilters()`)
- Плашка **«Показано X из Y»** + кнопка «↻ Обновить» перенесены в заголовочную строку
- Справочная помощь (`HELP_CONTENT['unic-sources']`) — обновлена в соответствии с новым интерфейсом
- README.md автоварма — добавлен раздел «Раздел Исходники»

**Новые поля фильтрации в `srcFilter()`:** `src-cf-created-from`, `src-cf-created-to`, `src-cf-pub-from`, `src-cf-pub-to`
**Удалены старые поля:** `src-f-date-from`, `src-f-date-to`, `src-f-project` (из верхнего блока)
**Коммит:** см. GenGo2/delivery-contenthunter

## warmer.py — preflight ADB + retry initialize + AI Unstuck (2026-03-25)

**Коммиты:** `b036262`, `e896809` → GenGo2/delivery-contenthunter

### Проблема
Задачи фарминга падали с `failed: Не удалось запустить/перезапустить приложение` когда:
- Телефон был офлайн или ADB не отвечал (задачи 16/17/18/20)
- TikTok/Instagram показывал попап после фазы поиска (задача 67)

### Фикс 1: Preflight ADB-проверка (`e896809`)
`preflight_check()` теперь первым делом вызывает `is_online()`.
Если ADB мёртв → сразу `preflight_failed: Устройство <serial> недоступно по ADB`
Нет смысла делать дальнейшие проверки БД при недоступном устройстве.

### Фикс 2: Retry + AI Unstuck в `initialize()` (`b036262`)
`_wait_for_app` timeout: 30 → 60 сек.
`initialize()` теперь 3 попытки:
1. Стандартный запуск + 60 сек ожидания
2. BACK + HOME + force-stop + restart (сброс попапов)
3. `_ai_unstuck_initialize()` — скриншот → Groq Vision → закрыть что мешает

Новый метод `_ai_unstuck_initialize(package, max_attempts=4)`:
- Отдельный от publisher `ai_unstuck`, заточен на задачу «выйти в foreground»
- Скриншот → Groq llama-4-scout-17b → JSON action(tap/keyevent/wait) → выполнить
- До 4 итераций, проверка foreground после каждого шага

**Правило диагностики:**
- `preflight_failed: Устройство ... недоступно по ADB` → физически проверить подключение телефона
- `failed: Не удалось перезапустить приложение после фазы поиска` → в логе должны быть строки `🤖 AI Unstuck (initialize)` — смотреть reason
- Если AI Unstuck тоже не помог → что-то серьёзное (бан, полная блокировка приложения)

## autowarm — pre-commit защита index.html (2026-03-25)

**Корневая причина 3 инцидентов:** неэкранированные backtick в HELP_CONTENT (template literal).
- Инцидент 1: одиночный `` ` `` → `ac129be`
- Инцидент 2: `` ``` `` (закрытие code block) → `9ac7e8c`
- Инцидент 3: `` ```sql `` (открытие code block с языком) → `b2f1e79`

**Защита установлена:**
- `autowarm/scripts/validate_html_js.js` — валидирует все `<script>` блоки + делает lint HELP_CONTENT
- Pre-commit хук в `autowarm/.git/hooks/pre-commit` — блокирует коммит при ошибке
- `scripts/install_git_hooks.sh` обновлён — ставит pre-commit только для autowarm

**Правило кодирования в HELP_CONTENT:**
- `` ` `` → `\\\``
- ` ``` ` → `\\\`\\\`\\\``
- ` ```sql ` → `\\\`\\\`\\\`sql`

**README.md autowarm** — обновлён (таблица + секция про хук).

**Диагностика:** `node autowarm/scripts/validate_html_js.js autowarm/public/index.html`

## autowarm — фикс фильтров таблицы задач фарминга (2026-03-25, Юра+Даниил)

**Проблема:** фильтры по столбцам в разделе «Задачи» (#farming/tasks) сбрасывались каждые 10 сек — авто-обновление вызывало `loadTasks()` → прямой `renderTasksTable(_tasksAll, _tasksPage)` без учёта активных фильтров.

**Фикс (коммит `39647b1`):**
- `loadTasks()` теперь вызывает `filterTasksTable(_tasksPage)` вместо прямого рендера
- `filterTasksTable(page?)` получил опциональный параметр `page` — передаётся в `renderTasksTable`
- Активные фильтры (устройство, проект, пак, аккаунт, соцсеть, статус) применяются при каждом авто-обновлении
- Страница пагинации сохраняется

**Правило:** `loadTasks()` **никогда** не рендерит таблицу напрямую — только через `filterTasksTable()`.

---

## publisher.py — фикс публикации Instagram/TikTok/YouTube (2026-03-25, Юра)

**Коммит:** `07d47f7` в GenGo2/delivery-contenthunter

### Instagram — аудио-диалоги после Поделиться

Два разных экрана, два разных обработчика:

| Экран | Маркеры | Действие |
|---|---|---|
| «Название аудиодорожки» | `Название аудиодорожки`, `Оригинальное аудио`, `Дайте своей аудиодорожке уникальное название` | `KEYCODE_BACK` → пропускает, публикация продолжается |
| «Редактировать связанное видео Reels» | `Редактировать связанное`, `Название этого видео Reels появится` | `KEYCODE_BACK` → возврат на caption screen |

**Не делать:** ✓ (справа вверху) — это «Изменить видео Reels» → открывает галерею. ✕ (слева) — «Закрыть» → отменяет публикацию.

**_caption_markers** нельзя включать `Хэштеги`/`Связать видео Reels` — они есть в XML даже когда открыт аудио-диалог (слои рендерятся вместе). Использовать только уникальные: `Новое видео Reels`, `Добавьте подпись`.

**Кнопка Поделиться:** `bounds=[563,2025][1035,2149]` → fallback `(799, 2087)`.

### TikTok — фокус поля описания

Canvas/WebView → `clickable=false`. Перебираем `(540,290)/(540,350)/(540,400)/(540,250)`, проверяем `dumpsys input_method | grep mInputShown`.

### YouTube — «Добавьте информацию»

Новые версии Shorts показывают поля `Название`/`Описание` прямо здесь. Заполняем перед нажатием «Загрузить».

### Диагностика

При проблемах: `adb pull /sdcard/debug_screenshots/screenrec_<id>_*.mp4` — показывает точный момент ошибки.
