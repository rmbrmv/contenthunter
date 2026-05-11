# Чекер аккаунтов соцсетей — карта переиспользуемого кода

**Дата:** 2026-05-04
**Контекст:** новая фича — скрипт заходит в профиль аккаунта на устройстве и проверяет его по набору признаков.
**Репо:** `GenGo2/delivery-contenthunter`, ветка `main` (приватный, доступ — `~/secrets/github-gengo2.env`).

---

## TL;DR

В репо **уже есть** два файла, которые делают почти ровно то, что описано в задаче:

- [`social_audit.py`](https://github.com/GenGo2/delivery-contenthunter/blob/main/social_audit.py) (1015 строк) — IG/TT/YT-аудит профиля через ADB+AI
- [`profile_inspector.py`](https://github.com/GenGo2/delivery-contenthunter/blob/main/profile_inspector.py) (701 строка) — IG-only, более глубокий

**Прежде чем давать ТЗ — посмотрите эти два файла.** Возможно, задача уже на 70% решена и нужно только: (а) расширить набор «признаков», (б) добавить новый платформенный навигатор, (в) подцепить к UI.

---

## Готовые модули, делающие ровно то, что нужно

| Файл | Что делает | Ссылка |
|---|---|---|
| **`social_audit.py`** (1015) | **Главный кандидат — IG/TT/YT-аудит профиля через ADB+AI.** Уже есть: `audit_profile(account, platform)`, `audit_project_batch(project_name)`, `open_profile_instagram/tiktok/youtube`, `extract_profile_data`, `score_profile` (1-10 + сравнение с брифом из Airtable), `save_to_db` → таблица `social_audit_snapshots`, `find_device_for_account`. | [social_audit.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/social_audit.py) |
| **`profile_inspector.py`** (701) | IG-only, более глубокий: шапка профиля + 3 последних поста с открытием каждого для caption, оценка 1-10 по критериям через LaoZhang/Gemini-vision. | [profile_inspector.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/profile_inspector.py) |

### Public surface `social_audit.py` (по строкам)

```
84:  find_device_for_account(account, platform)
116: get_any_online_device()
138: get_project_accounts(project_name)
169: fetch_airtable_projects()
240: build_brief_context(project)
273: adb / adb_pull / tap / swipe_up / back / screenshot
383: open_profile_instagram(serial, port, account)
397: open_profile_tiktok(serial, port, account)
412: open_profile_youtube(serial, port, account)
467: call_ai(prompt, images_b64)
557: extract_profile_data(platform, screenshots)
596: score_profile(platform, profile, brief)
649: save_to_db(result) → social_audit_snapshots
714: audit_profile(account, platform, serial, port, project_name)
840: audit_project_batch(project_name, platforms)
```

---

## Навигация: открыть аккаунт на устройстве

| Файл | Что переиспользуем | Ссылка |
|---|---|---|
| `account_switcher.py` (3765) | Ядро переключения IG/TT/YT-аккаунта на телефоне. Любой чекер должен через него гарантированно сесть на нужный аккаунт перед проверкой. | [account_switcher.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/account_switcher.py) |
| `account_revision.py` (625) | Тонкий CLI-wrapper над switcher — пример как вызывать switcher отдельно от publisher'а. Шаблон для нового CLI «check-account». | [account_revision.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/account_revision.py) |
| `id_parser.py` (304) | Парсинг user_id по username (IG/YT/TT/VK/Pinterest/Dzen/Rutube/Likee/Wibes) — **через web/Apify**, без устройства. Полезно как pre-flight: «существует ли вообще такой профиль». | [id_parser.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/id_parser.py) |

---

## ADB / UI-примитивы

| Файл | Что | Ссылка |
|---|---|---|
| `adb_utils.py` (198) | tap/swipe/screenshot/dump_ui над `adb -H 82.115.54.26 -P <port> -s <serial>`. | [adb_utils.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/adb_utils.py) |
| `publisher_base.py` (3634) | Proxy-API: `log_event`, `dump_ui`, `adb`, `capture_screen` — основной фасад. Helper'ы у switcher'а вызывают именно его (memory `reference_publisher_proxy_api`). | [publisher_base.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/publisher_base.py) |
| `publisher_helpers.py` (87) | UI-утилиты поверх dump_ui. | [publisher_helpers.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/publisher_helpers.py) |

---

## AI / vision-анализ скриншотов

| Файл | Что | Ссылка |
|---|---|---|
| `vision_analyzer.py` (695) | Vision-анализ дампов/скриншотов через LaoZhang (gemini-2.5-flash). Используется publisher'ом и audit'ом. | [vision_analyzer.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/vision_analyzer.py) |

---

## Per-platform навигация в профиль (вторая точка переиспользования)

| Файл | Что | Ссылка |
|---|---|---|
| `archiver_base.py` (190) | Базовый класс — общий контракт навигации в профиль и сбора. | [archiver_base.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/archiver_base.py) |
| `instagram_archiver.py` (578) | IG: проход по постам/Reels с устройства. | [instagram_archiver.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/instagram_archiver.py) |
| `tiktok_archiver.py` (301) | TT: проход по видео. | [tiktok_archiver.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/tiktok_archiver.py) |
| `youtube_archiver.py` (384) | YT: канал и видео. | [youtube_archiver.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/youtube_archiver.py) |

---

## Распознавание «признаков» проблем

| Файл | Что | Ссылка |
|---|---|---|
| `account_blocks.py` | Единый API заморозки per-platform (`ig_block/tt_block/yt_block` JSONB на `factory_reg_accounts`): `human_verification_required`, `sms_verification_required`, `email_verification_required`, `account_banned`, `rate_limited`. **Если чекер обнаружил признак — пишите сюда, не плодите новые таблицы.** | [account_blocks.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/account_blocks.py) |
| `obstacle_kb.py` | Свежий obstacle-KB (отгружен 2026-05-02): 12 паттернов B1.x. | [obstacle_kb.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/obstacle_kb.py) |
| `obstacle_signatures.py` | Signatures-матчер для UI-препятствий. | [obstacle_signatures.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/obstacle_signatures.py) |
| `obstacle_actions.py` | Действия по обнаруженным препятствиям. | [obstacle_actions.py](https://github.com/GenGo2/delivery-contenthunter/blob/main/obstacle_actions.py) |

---

## Рекомендации в ТЗ

1. **Базовый сценарий — extension `social_audit.py`**, не новый файл. Список «признаков» добавляется в `extract_profile_data` / `score_profile` + новые поля в `social_audit_snapshots` (миграция).
2. **Навигация** — `social_audit.open_profile_<platform>`, если хватает; switcher — только если нужен корректный foreground-аккаунт перед проверкой.
3. **Сигналы блокировки/ban** → пишутся через `account_blocks.set_block(...)`, **не плодить новые таблицы**.
4. **Распознавание UI-препятствий** (captcha, human-verify) — через `obstacle_signatures.match()`.
5. **Frontend** — паттерн `delivery.contenthunter.ru/<page>.html` (memory `reference_delivery_frontend_deploy`), если нужен UI чекера.
6. **Миграции** — в `<repo>/migrations/`, без implicit DDL (memory `feedback_migrations_for_writers`).
7. **JS-обёртки** (если будет endpoint в `server.js`) — обязательно `if (r.ok)` ветка после execFile→Python+JSON.parse (memory `feedback_js_wrapper_ok_check`).

---

## Открытые вопросы для уточнения с автором ТЗ

- Какой именно набор признаков нужно проверять? (бан / shadowban / ограничение видимости / отсутствие аватара / несоответствие брифу / что-то ещё)
- Триггер запуска: cron / по событию publish-fail / ручной из UI / batch по проекту?
- Требуется ли UI на `delivery.contenthunter.ru`, или достаточно CLI + БД?
- Платформы: только IG/TT/YT (как сейчас в `social_audit.py`) или нужно расширение?
