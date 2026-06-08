# Переезд ContentHunter — статус на конец 08.06.2026 (handoff для следующей сессии)

## TL;DR
**Фаза 0.5 ЗАВЕРШЕНА.** Блокер publisher-runtime закрыт, **канарейка публикации с нового сервера зелёная** (реальный IG-рил опубликован), реквизиты воспроизводимы, последний код-блокер (DB-креды python) исправлен и **задеплоен на prod-delivery**. Старый сервер в строю, не тронут. **Следующий шаг — повтор окна переезда (Фаза 1-2)**: пере-дамп БД → смоук → канарейка → 301-редирект. Перед окном — 2 хвоста (unic-worker repoint, проверка SIGTERM). Окно открывать под контролем Данила (заморозка писателей + редирект = наружу-действия).

## Текущее состояние
- **OLD `72.56.107.157`** (`fra-1-vm-y49r`, на нём же эта сессия) — В СТРОЮ как прежде. pm2 35/36/33/26/28/29/24 online, Caddy в норме, `client/delivery.contenthunter.ru` отдают рабочий интерфейс. Данные OLD НЕТРОНУТЫ (только read-only pg_dump). cron не менялся. testbench снимали с паузы после канарейки (`system_flags.testbench_paused=false`).
- **NEW `46.225.145.245`** (cpx62 Hetzner) — стенды подняты:
  - `prod-delivery` (:3848, ветка main `ec9b847`, БД `contenthunter`, **TEST_MODE=1** → публикация выключена) — **полностью готов к cutover**.
  - `prod-client` (:8000, main, `contenthunter`) — работает.
  - `test-delivery` (:3948, develop) / `test-client` (:8100) — живые.
  - Caddy на NEW: prod-delivery/prod-client/test-delivery/test-client.contenthunter.ru (TLS LE).
  - БД-контейнер `contenthunter-postgres` (pgvector): базы `contenthunter` (снимок окна #1) + `contenthunter_test`.
  - **НЕТ редиректа** OLD→NEW.

## Доступы / факты
- OLD: claude-user, **sudo NOPASSWD ALL** (`/etc/sudoers.d/claude-user-migration`).
- NEW: `ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245` (алиас `cpx62`). Caddy `/etc/caddy/Caddyfile`, стенды `/opt/contenthunter/*`, БД `cd /opt/contenthunter/_ops/db && docker compose exec -T postgres psql -U contenthunter -d <db>`. Пароль роли — `/opt/contenthunter/_ops/db/db.env` (+ `PGPASSWORD` в каждом `<stand>/.env`).
- gh: **GenGo2**, scopes `repo, workflow, read:org, gist`. Авто-деплой GitHub Actions: `develop`→test, `main`→prod (`/opt/contenthunter/_ops/deploy.sh <stand>`). NEW→GitHub через read-only deploy-keys.
- Репо: `GenGo2/delivery-contenthunter`, `GenGo2/validator-contenthunter`.
- **Тест-вход:** test-delivery `admin/test12345`; test-client `admin/hunter2025`; prod-* `admin/hunter2025`.
- IP Данила (allowlist при окне): `192.177.26.113`.
- **Канарейка: phone #19 = serial `RF8YA0W57EP`, Pi #7, ADB `147.45.251.85:15068`, проект «Тестовый проект_19»** (выделенный тест-телефон, НЕ в живой прод-ротации). Запуск: пауза OLD-testbench (`system_flags.testbench_paused='true'` в openclaw) → `testbench_orchestrator.py --once` (env DB_*←PG*) создаёт задачу в contenthunter → `cd /opt/contenthunter/prod-delivery && python3 -u publisher.py <task_id>`. seed-медиа на NEW: `/home/claude-user/testbench-seed/{instagram,tiktok,youtube}/*.mp4`.

## Сделано в эту сессию (08.06) — Фаза 0.5
1. **publisher-runtime на NEW** — поставлены python-пакеты (psycopg2/dotenv/lxml/pillow/numpy/anthropic; boto3/botocore позже до 1.43.24). **КЛЮЧЕВОЕ: публикация работает на ЧИСТОМ ADB, Appium НЕ нужен** (appium только в gmail_factory_appium.py = фарм-регистрация, отдельный неактивный путь). Все 12 спавн-скриптов server.js импортируются.
2. **🐤 Канарейка ЗЕЛЁНАЯ** — реальный IG-рил опубликован с NEW на phone#19 (task #16116, акк inakent06), `✅ публикация прошла`, статус `awaiting_url` (IG API 429 на захвате permalink = известный published_no_url, не ошибка). Скриншот рила в ленте подтверждён.
3. **requirements-runtime.txt** в repo + **deploy.sh** на NEW ставит его (`pip install --break-system-packages`) + гарантирует ffmpeg (`apt`). Проверено end-to-end деплоем test-delivery (HTTP 200).
4. **ffmpeg + boto3/botocore 1.43.24** на NEW (канарейка вскрыла: старый botocore ломал S3-аплоад артефактов `request_checksum_calculation`; ffmpeg отсутствовал). **РЕШЕНИЕ Данила: ffmpeg ОСТАВЛЯЕМ** — он НЕ дублирует внешний уникализатор (`FFMPEG_HOST=91.98.180.103` = тяжёлая уникализация ролика), а нужен publisher'у локально для probe/ремукса медиа перед заливкой на телефон (ffprobe длительность/потоки, `-movflags +faststart` чинит moov), видео-триажа падений (triage_classifier/vision_analyzer phash+frames), скрин-рекордов и соц-аудита. Паритет со старым сервером.
5. **Код-фикс DB-креды python→env (db_env)** — PR#170/#166 перенесли на env только server.js (node); **37 python-скриптов хардкодили `openclaw/openclaw123`** → на NEW (роль contenthunter) publisher_kernel/triage_classifier не коннектились. Введён `db_env.py` (читает PG*→DB_*→DATABASE_URL, fallback legacy openclaw), 37 файлов переведены на импорт, 6 unit-тестов. delivery develop `dbc22ee` → **PR#172 merged в main `ec9b847`** (авто-деплой main→prod SUCCESS). ВЕРИФ: test-delivery `db_env→contenthunter_test`, prod-delivery `db_env→contenthunter` + `publisher import OK`, TEST_MODE=1 сохранён. На старом сервере env не задан → дефолты openclaw, поведение прежнее.

Чекаут для правок delivery: `/home/claude-user/ch-migration-runtime` (на develop). Снимок deploy.sh: `_artifacts/deploy.sh.snapshot`.

## ОСТАЛОСЬ до повтора окна (Фаза 1-2)
1. **Репойнт standalone unic-worker `91.98.180.103`** → БД NEW. Делит unic-очередь с delivery. Выяснить, как коннектится к БД (БД NEW слушает только localhost → нужен доступ/туннель/перенос воркера). Это resolve_logo рендер (см. [[project_unic_project_logo_priority]]).
2. **Перепроверить post-publish SIGTERM.** На канарейке publisher был убит SIGTERM-ом ПОСЛЕ успешной публикации (статус БД awaiting_url корректен). Источник не установлен: `timeout 540` ручного запуска ИЛИ watchdog NEW-scheduler (`pkill -f publisher.py`, server.js:3216)? Убедиться, что NEW-scheduler не валит свои publisher при живой выкладке (в нормальном спавне через scheduler.js этого быть не должно, но проверить на первом реальном диспатче).
3. **Окно (Фаза 1-2)** — план `2026-06-07-contenthunter-migration-cutover.md`, отрепетирован в окне #1. Отличия повтора:
   - Код уже на main (db_env + requirements) → prod-delivery готов, лишь обновить (`deploy.sh prod-delivery`) + переснять данные.
   - Шаги: плашка 503 на OLD (allowlist IP Данила) → заморозка писателей OLD (стоп pm2 35/36/33/26/28/29 + cron) → финальный выборочный дамп openclaw→contenthunter на NEW (РЕАЛЬНЫЕ данные, **обезличивание снять**) + views.sql + factory_hashtags → alembic head → смоук prod (рекоменд. сперва TEST_MODE=1) → **канарейка phone#19** → снять TEST_MODE (пуск публикации) → 301-редирект OLD client/delivery.contenthunter.ru→prod-*.contenthunter.ru → снять плашку → наблюдение → стоп CH-сервисов на OLD (др.продукты остаются) → удаление внешней factory-БД 193.124.112.222.
   - Caddy-блоки OLD для редиректа сохранены (см. handoff 07.06).

## Артефакты
`_artifacts/`: phase0-recon.md, phase0-external-audit.md, phase0-farming-repos.md, phase0-device-status.md, migration-status-2026-06-07.md, **этот файл**, deploy.sh.snapshot.
