# T8 — File-to-file mapping: чужие модули ↔ наш код

**Our-side root:** `/root/.openclaw/workspace-genri/autowarm/`
**LOC our side (modules involved in farming):**

| File | LOC |
|---|---:|
| publisher.py | 6120 |
| server.js | 5981 |
| account_factory.py | 4193 |
| warmer.py | 2692 |
| account_switcher.py | 1742 |
| account_revision.py | 1052 |
| scheduler.js | 508 |
| adb_utils.py | 198 |
| **Total** | **22486** |

Наш стек: Python (publisher/warmer/account_*) + Node.js (server.js + scheduler.js). Их стек — Python only + Celery.

## Полная матрица (30 строк)

| # | Чужой модуль | LOC | Наш аналог | Наш LOC (метод/блок) | Статус | Приоритет reuse |
|--:|---|--:|---|--:|---|---|
| 1 | autowarm_worker/app/celery.py (Celery config) | 32 | scheduler.js tick loop + pm2 process | ≈40 | **альтернативная архитектура** (Celery vs pm2 custom) | LOW (инфра-миграция) |
| 2 | autowarm_worker/app/entrypoints/worker.py (Celery task wrapper) | 148 | scheduler.js `spawnFarmTask()` + pm2 | ≈80 | **альтернативная архитектура** | LOW |
| 3 | autowarm_worker/app/entrypoints/cmd.py (CLI entry) | 97 | python-скрипт `warmer.py --task-id N` (эквивалент) | ≈30 | эквивалент | NONE |
| 4 | **autowarm_worker/app/modules/humanize_with_coords.py::`_cleanup_device`** | 30 | (отсутствует) | 0 | **reuse-ready** | **HIGH** |
| 5 | autowarm_worker/app/modules/humanize_with_coords.py::`type_text` (Yosemite broadcast) | 10 | не смотрели; вероятно `input text` | ≈5 | **альтернативный подход** | MED |
| 6 | autowarm_worker/app/modules/humanize_with_coords.py::`tap(image, zone_percentage)` | 50 | warmer.py/publisher.py inline `adb input tap X Y` | n/a | альтернативный подход (image-based) | MED |
| 7 | autowarm_worker/app/modules/humanize_with_coords.py::`swipe_next_video` + `watch_search_results` + `humanize_like/comment` | 200 | warmer.py::run_day_scenario + protocol days_config jsonb | ≈300 | паттерны похожие, декларативность отличается | MED (LOW если оставить наш jsonb) |
| 8 | autowarm_worker/app/modules/humanize_with_coords.py::`check_auth` (image-based) | 25 | warmer.py::verify_and_switch_account (XML regex) :730 | ≈80 | альтернативный подход | LOW (наш умнее) |
| 9 | autowarm_worker/app/modules/{ig,tt,yt}/dayN.py | 22-60 каждый | autowarm_protocols.days_config jsonb в DB | n/a в коде | **альтернативная декларативность** | MED (для починки TT/YT протоколов) |
| 10 | autowarm_worker/app/modules/tiktok/publish_video.py | 138 | publisher.py::publish_tiktok (часть 6120) | ≈400 | похожие flow | LOW (наш richer) |
| 11 | autowarm_worker/app/repositories/autowarm_tasks.py (SQLAlchemy DAO) | 15 | scheduler.js inline SQL + warmer.py psycopg2 | ≈50 | **рефактор-кандидат** | LOW (не fix, а рефактор) |
| 12 | autowarm_worker/app/repositories/raspberry.py | ≈20 | autowarm_settings / devices table, device host resolved inline | ≈15 | эквивалент | NONE |
| 13 | autowarm_worker/app/services/subject_service.py | ≈20 | account_packages.thematic inline | n/a | эквивалент | NONE |
| 14 | autowarm_worker/app/logging_setup.py (structured JSON) | ≈30 | logging в publisher.py (stdlib) | ≈20 | **рефактор-кандидат** | MED |
| 15 | autowarm_worker/app/exceptions.py | 4 | publisher.py inline exceptions | n/a | эквивалент | NONE |
| 16 | Celery soft/hard timeout (SoftTimeLimitExceeded + process.kill) | 15 | scheduler.js::watchdogStuckTasks (DB-only) :118 | 35 | **упущенная функциональность** — нет kill | **HIGH** (через pid + SIGTERM) |
| 17 | Celery worker_max_tasks_per_child + worker_max_memory_per_child | 5 | pm2 max_restarts + max_memory_restart (ecosystem.config.js) | n/a? | **missing config** | MED |
| 18 | **auto_public/uploader/base.py::`connect_and_restart_app` (stop_app+start_app+sleep 8)** | 20 | (отсутствует) — warmer.py сразу делает `adb input tap` на профиль | 0 | **reuse-ready** | **HIGH** (ДУБЛИРУЕТ #4) |
| 19 | auto_public/uploader/base.py::`upload_video_template` (template method) | 80 | publisher.py::publish_* (flat) | ≈800 | рефактор-кандидат | LOW |
| 20 | auto_public/uploader/base.py::`init_poco` + `_restart_uiautomator` | 45 | (нет — мы не используем Poco) | 0 | не нужно | SKIP |
| 21 | auto_public/uploader/{instagram,tiktok,vk,youtube}.py | 85-139 | publisher.py::publish_* (flat) | 4000+ из 6120 | у них проще, у нас много эвристик | LOW |
| 22 | auto_public/by_images.py::`_get_first_frame` + Template matching | 174 | publisher.py использует XML dumps + content-desc | n/a | **альтернативный подход** (image fallback) | LOW-MED |
| 23 | **auto_public/services/llm_manager.py::`handle_step` (screen→LLM→touch/confirm/alert)** | 136 | (отсутствует) | 0 | **новая фича** | **HIGH** (для unknown-screen recovery) |
| 24 | auto_public/llm_providers/open_router.py | 80 | (отсутствует) | 0 | новая фича | MED (можно заменить на Anthropic SDK) |
| 25 | auto_public/prompts/system_rare.txt (touch/confirm/alert prompt) | 35 | (отсутствует) | 0 | **новый артефакт** | HIGH (в связке с #23) |
| 26 | auto_public/utils/draw.py (cv2 touch overlay on screenshot) | ≈40 | (отсутствует) | 0 | для Telegram-alert — новая фича | LOW |
| 27 | auto_public/utils/database.py (SQLAlchemy + dotenv + URL-encode) | ≈30 | psycopg2 inline с hardcoded creds (DB_CONFIG :41 в publisher.py) | ≈15 | рефактор-кандидат (SECURITY: сейчас пароль в коде) | MED-HIGH |
| 28 | (оба репо) структурное разделение entrypoint/core/repositories/services | layout | publisher.py + warmer.py (flat) | 22486 total LOC | рефактор-кандидат | LOW (ломает слишком много) |
| 29 | (наш) `events jsonb` + `meta.category` в publisher.py | ≈50 мест | warmer.py **не использует** meta.category | 0 | **технический долг** нашего кода | **HIGH** |
| 30 | (наш) factory_reg_tasks pid-tracking + process.kill (server.js:3547) | ≈5 | autowarm_tasks **без** pid column + watchdog только DB UPDATE | 0 | **pattern already exists in our code** | **HIGH** |

## Группы по приоритету reuse

### HIGH — прямые фиксы баз фейлов (из T1-T5 baseline)

- **#4 / #18** (duplicate signal): `_cleanup_device` / `connect_and_restart_app` → force-stop всех соцсетей + 8s settle ДО `verify_and_switch_account()`. Фикс T2 root-cause.
- **#16 + #30**: `pid` column + `process.kill(pid, SIGTERM/SIGKILL)` + in-process SIGTERM handler. Фикс T3 root-cause.
- **#23 + #25**: LLM-based screen-state recovery — generalization of наши `_is_ig_highlights_empty_state` handler'ов. Дополнение к существующему rigid detector-chain'у.
- **#29**: добавить `meta.category` во все warmer.log_event — баг нашего кода, отмеченный в T1.

### MED — архитектурный upgrade

- **#5** Yosemite IME для type_text — если у нас есть проблемы с русским текстом в комментариях
- **#9** Декларативные daily modules для TT/YT (протоколы `autowarm_protocols.id=2,3` сейчас 0/100 success)
- **#14** Structured JSON logging (logging_setup.py) — упрощает monitoring
- **#17** pm2 max_memory_restart + max_restarts config — эквивалент Celery worker recycling
- **#27** Secure DB creds — вынести из DB_CONFIG в .env (сейчас hardcoded)

### LOW — опциональные улучшения

- #6 image-based tap (требует Airtest или cv2 integration)
- #11/#28 DAO-рефактор (не фикс, стилистика)
- #22 image-first-frame-as-template трюк (нишевый)

### SKIP

- Poco-stack (#20): мы на ADB, Poco даст больше dependencies чем benefit
- Celery migration (#1/#2): переписывание scheduler.js + pm2 стоит LOT, benefit сомнителен

## Сводный размер нашего vs их

- **Наш farming-related код:** ≈22486 LOC Python + Node.js
- **Чужой autowarm_worker:** ≈1000 LOC total (в т.ч. 635 в humanize_with_coords.py)
- **Чужой auto_public:** ≈1500 LOC total

**Соотношение:** наш код в 8-9 раз больше по объёму, но охватывает существенно большую функциональность (publish + warming + switcher + account factory + revision). Чужие репо делают узкую задачу проще.

## Ссылки на наши файлы (для follow-up плана)

Конкретные точки интеграции HIGH-кандидатов:

| Task | Наш файл | Точка интеграции |
|---|---|---|
| #4/#18 force-stop pre-verify | warmer.py :730 `verify_and_switch_account` | добавить `_reset_app_state()` helper в начале метода + в начало каждого retry-attempt |
| #16/#30 pid-tracking | scheduler.js :118-154 `watchdogStuckTasks` + `autowarm_tasks` schema | ALTER TABLE + UPDATE watchdog-callback |
| #23/#25 LLM recovery | publisher.py (уже есть handlers) + warmer.py | новый модуль `llm_screen_recovery.py` (Anthropic SDK) + integration points в publisher.py after 3 failed attempts |
| #29 meta.category | warmer.py :739, :770, :785, etc. (все log_event) | добавить `category='wa_...'` во все error/warning events |
