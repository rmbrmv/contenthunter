# Переезд ContentHunter — статус на конец 07.06.2026 (handoff для следующей сессии)

## TL;DR
Окно переезда #1 **открывали и откатили**. Данные/веб/деплой — доказаны. Заблокировались на том, что **runtime публикации (python-пакеты + Appium) не провижен на NEW**. OLD возвращён в строй, работает штатно. **Следующий шаг — Фаза 0.5: поднять publisher-runtime на NEW + канарейка на телефоне №19, без простоя.** Затем повторить окно.

## Текущее состояние
- **OLD `72.56.107.157`** — В СТРОЮ как прежде. pm2 35/36/33/26/28/29/24 online, Caddy восстановлен из бэкапа (плашка снята), `client/delivery.contenthunter.ru` отдают рабочий интерфейс. Данные OLD НЕТРОНУТЫ (делали только read-only pg_dump). cron не менялся.
- **NEW `46.225.145.245`** — прод-стенды подняты, оставлены для подготовки:
  - `prod-delivery` (:3848, ветка main, БД contenthunter, **TEST_MODE=1** → публикация выключена)
  - `prod-client` (:8000, main, contenthunter) — работает
  - `test-delivery` (:3948) / `test-client` (:8100) — тест-стенды живые
  - Caddy на NEW: `prod-delivery/prod-client/test-delivery/test-client.contenthunter.ru` (TLS LE)
  - БД-контейнер `contenthunter-postgres` (pgvector): базы `contenthunter` (снимок из окна #1) + `contenthunter_test`
  - **НЕТ редиректа** OLD→NEW (откатили).

## Доступы / факты
- OLD: claude-user, **sudo NOPASSWD ALL** (`/etc/sudoers.d/claude-user-migration`).
- NEW: `ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245` (алиас `cpx62`). Внутри Caddy `/etc/caddy/Caddyfile`, стенды `/opt/contenthunter/*`, БД `cd /opt/contenthunter/_ops/db && docker compose exec -T postgres psql -U contenthunter -d <db>`. Пароль роли БД: `/opt/contenthunter/_ops/db/db.env`.
- gh: авторизован как **GenGo2**, scopes `repo, workflow, read:org, gist`. git-helper настроен. На NEW NEW→GitHub через SSH-алиасы `github-delivery`/`github-validator` (read-only deploy-keys).
- Репо: `GenGo2/delivery-contenthunter`, `GenGo2/validator-contenthunter`. Ветки `develop`(→test) и `main`(→prod), авто-деплой GitHub Actions (`/opt/contenthunter/_ops/deploy.sh <stand>`).
- **Тест-вход:** test-delivery `admin/test12345`; test-client `admin/hunter2025`. prod-* `admin/hunter2025` (на NEW я сбрасывал admin prod-delivery).
- IP Данила (для плашки allowlist при повторе окна, если нужно): `192.177.26.113`.
- Канарейка: **телефон №19**.

## Что СДЕЛАНО и доказано (переиспользуется при повторе)
- Провижн NEW: docker/compose, node20, caddy2.11, swap8G, ufw, psql16, adb.
- БД pgvector в docker-compose, 2 базы + pg_trgm/pgcrypto.
- Деплой-пайплайн GitHub Actions (develop→test, main→prod) — РАБОТАЕТ end-to-end.
- Код-фиксы в `main` обоих репо: креды БД из env, `factory.*`→public, **полный гард TEST_MODE** (PR#170, scheduler.init+bootstrap), device_state поверх локальной `autowarm_device_metrics` (отвязка от схемы factory), validator requirements (anthropic+bcrypt4.0.1) + alembic env из .env.
- Выборочный дамп: `--schema=public` с `-T` исключениями (DROP=75 чужих/ничейных, KEEP=77 CH). На окне #1 row counts сошлись 1:1 с baseline, чужих 0. factory_hashtags (628) + device_state(view) применяются из `/opt/contenthunter/_ops/db/views.sql`.
- ADB-устройства С NEW достижимы (`adb -H 147.45.251.85 -P <port> devices` = живой список); collectDeviceMetrics на NEW пишет свежие метрики.

## БЛОКЕР, который надо закрыть (Фаза 0.5, без простоя) — Task #6
Публикация: `server.js` спавнит `python3 publisher.py`. На OLD это **системный `/usr/bin/python3`** с ~270 глобальными пакетами + **Appium-сервер** (`/usr/bin/appium`). На NEW не поставлено → `ModuleNotFoundError: psycopg2`.
Ключевые пакеты (из OLD `pip freeze`): `psycopg2-binary==2.9.9`, `Appium-Python-Client==5.3.0`, `selenium==4.41.0`, `boto3==1.35.0`, `lxml==5.2.1`, `numpy==2.4.2`, `pillow==10.2.0`, `requests==2.31.0`, `urllib3==2.6.3` (+ остальные из 270-строчного freeze).

**План Фазы 0.5:**
1. Снять актуальный `sudo python3 -m pip freeze` с OLD.
2. На NEW поставить пакеты в системный python3 (`pip install --break-system-packages -r ...`; Ubuntu 24.04 PEP668).
3. Поставить/настроить **Appium-сервер** на NEW (как на OLD — выяснить точный способ запуска: глобальный `appium`, драйвер `uiautomator2`, порт/оркестрация; на OLD `which appium`=/usr/bin/appium, persistent-сервер на :4723 НЕ подтверждён — проверить, спавнится ли per-device).
4. **Воспроизводимость:** зафиксировать requirements в репо `delivery-contenthunter` (напр. `requirements-runtime.txt`) + `deploy.sh` ставит их; Appium — в провижн-скрипт/доку.
5. 🐤 **Канарейка:** реальный тест-пост с NEW на телефоне №19 (взять задачу/аккаунт безопасно; убедиться, что публикует и видно в ленте). Только после зелёной канарейки считать publisher-runtime готовым.
6. Репойнт standalone unic-worker `91.98.180.103` (FFMPEG_HOST, делит unic-очередь) на NEW-БД — выяснить, как он коннектится (NEW-БД сейчас слушает только localhost → нужен доступ/туннель/перенос).

## Повтор окна (Фаза 1-2) — после зелёной канарейки
План в `docs/superpowers/plans/2026-06-07-contenthunter-migration-cutover.md`. Уже отрепетировано. Отличия при повторе:
- Дамп переснять заново (OLD пишет после разморозки) — БД `contenthunter` на NEW пере-restore.
- prod-стенды уже подняты; нужно лишь обновить код (`main`), перелить свежий дамп, проверить смоук + **канарейку**, затем 301-редирект и снять плашку.
- Исходные Caddy-блоки OLD для редиректа (сохранены):
  - `client.contenthunter.ru` → `/api/*`→localhost:8000 + статика `/var/www/validator`
  - `delivery.contenthunter.ru` → reverse_proxy localhost:3848
  - Редирект: `redir https://prod-client.contenthunter.ru{uri} permanent` / `prod-delivery`.

## Артефакты разведки (в этой ветке)
`_artifacts/phase0-recon.md`, `phase0-external-audit.md`, `phase0-farming-repos.md`, `phase0-device-status.md`, этот файл.
