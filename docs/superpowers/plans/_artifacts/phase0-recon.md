# Фаза 0 — Разведка переезда ContentHunter (Task 1–2)

Дата: 2026-06-07. Режим: read-only. Секреты замаскированы (только имена переменных).

- OLD = `72.56.107.157` (hostname `fra-1-vm-y49r`), пользователь claude-user (sudo NOPASSWD).
- NEW = `46.225.145.245` (`cpx62-fsn1`, Ubuntu 24.04.4 LTS, root).
- Ключ к NEW скопирован: `/home/claude-user/.ssh/cpx62_key` (600, claude-user). SSH проверен — OK.

---

## Блок A — NEW: инвентарь

**Железо/ОС:** 16 vCPU, 30 GiB RAM (swap 0B!), диск `/` = 601G (использовано 1.8G, свободно 575G). Ubuntu 24.04.4 LTS.

**Установленные пакеты:**
- `python3`: /usr/bin/python3 — ЕСТЬ
- `git`: /usr/bin/git — ЕСТЬ
- `ufw`: /usr/sbin/ufw — ЕСТЬ (но firewall выключен)
- `caddy`: MISSING
- `psql`: MISSING
- `node`: MISSING
- `npm`: MISSING
- `pip3`: MISSING
- `adb`: MISSING
- `pm2`: MISSING
- `docker` / `docker compose`: MISSING

**Слушающие порты:** только sshd (22) и systemd-resolve (53). Ничего прикладного.

**Firewall:** ufw `inactive`; iptables политики ACCEPT/ACCEPT/ACCEPT (пусто). То есть фаервол не настроен.

**/opt:** пустой (только `.`/`..`). Чистый сервер.

---

## Блок B — конфиги OLD

### B1. Версии рантаймов на OLD (что воспроизвести на NEW)
- Node `v22.22.0`, npm `10.9.4`
- Python `3.12.3`
- Caddy `2.6.2`
- PostgreSQL CH = в Docker, образ `pgvector/pgvector:pg16` (НЕ ванильный postgres — нужен pgvector!)

### B2. delivery `.env` — список ключей (`/root/.openclaw/workspace-genri/autowarm/.env`)
ANTHROPIC_API_KEY, OPENCLAW_GATEWAY_URL, OPENCLAW_GATEWAY_TOKEN, ALERT_CHAT_ID, YOUTUBE_API_KEY,
LAOZHANG_API_KEY, LAOZHANG_BASE_URL, GROQ_API_KEY, TELEGRAM_BOT_TOKEN, APIFY_API_KEY,
ANDROID_HOME, ANDROID_SDK_ROOT, S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION,
S3_PUBLIC_URL, FFMPEG_HOST, FFMPEG_SSH_PASS, VISION_PROVIDER, TT_DUMP_POST_MUSIC_RIGHTS_XML,
TT_MUSIC_RIGHTS_FALLBACK_ENABLED, TT_SEED_HARDENING_SAASCENE_ENABLED, DAILY_REPORT_ENABLED,
DAILY_REPORT_TIME_MSK, DAILY_REPORT_COMMENTS_ENABLED, DAILY_REPORT_LLM_MODEL, DAILY_REPORT_BOT_TOKEN,
DAILY_REPORT_CHAT_ID, DAILY_REPORT_THREAD_ID, DAILY_REPORT_MENTIONS, IG_PICKER_FG_GUARD_ENABLED,
TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED, TT_CREATE_STORY_COLLISION_FIX_ENABLED

> ВАЖНО: в delivery `.env` НЕТ переменных подключения к БД — соединение с БД **захардкожено в server.js** (см. B4). Прочие kill-switch'и (`*_ENABLED`) живут НЕ в этом .env (видимо в коде/prod .env), здесь только часть.

### B3. client (validator) `.env` — список ключей
`/root/.openclaw/workspace-genri/validator/.env`:
DATABASE_URL, ALEMBIC_DATABASE_URL, S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION,
S3_PUBLIC_URL, JWT_SECRET, ADMIN_LOGIN, ADMIN_PASSWORD, FACTORY_DB_HOST, FACTORY_DB_PORT,
FACTORY_DB_NAME, FACTORY_DB_USER, FACTORY_DB_PASSWORD, BACKEND_HOST, BACKEND_PORT, FFPROBE_PATH

`/root/.openclaw/workspace-genri/validator/backend/.env` (это тот, что реально грузится pm2 id24) — то же + дополнительно:
LAOZHANG_API_KEY, TELEGRAM_BOT_TOKEN, GROQ_API_KEY, ANTHROPIC_API_KEY, LOGO_BG_REMOVAL_URL,
LOGO_BG_REMOVAL_TOKEN, LOGO_BG_REMOVAL_ENABLED, LOGO_IMAGE_API_URL, LOGO_IMAGE_MODEL,
LOGO_VARIANTS_GENERATION_ENABLED

Бэкап-файлы env присутствуют (`.env.bak.*`, `.env.example`) — мигрировать НЕ нужно.

**Как задаётся имя БД в client:** через env, строка подключения (значения маскированы, db-имя видно):
- `DATABASE_URL=postgresql+asyncpg://openclaw:<PW>@localhost:5432/openclaw`
- `ALEMBIC_DATABASE_URL=postgresql://openclaw:<PW>@localhost:5432/openclaw`
- То есть client ходит в ТУ ЖЕ БД `openclaw` (localhost:5432 = docker-proxy → контейнер).
- Отдельно `FACTORY_DB_HOST=193.124.112.222`, `FACTORY_DB_PORT=49002`, `FACTORY_DB_NAME=factory` — ВНЕШНЯЯ БД (IG-фабрика), НЕ переезжает, нужна сетевая достижимость с NEW.

### B4. delivery — как задаётся БД (ХАРДКОД в server.js)
`/root/.openclaw/workspace-genri/autowarm/server.js`:
```
73: const sessionPool = new Pool({
74:   host: 'localhost', port: 5432, database: 'openclaw',
75:   user: 'openclaw', password: 'openclaw123'
210: const pool = new Pool({
211:   host: 'localhost',
213:   database: 'openclaw',
214:   user: 'openclaw', password: 'openclaw123'
```
- Имя БД, пользователь и пароль ЗАХАРДКОЖЕНЫ (`openclaw`/`openclaw`/`openclaw123`), порт 5432, host localhost. НЕ из env.
- Аутентификация: пароль (md5/scram), не peer/socket — через TCP localhost:5432 (docker-проброс).
- На NEW либо сохранить те же креды/порт, либо пропатчить server.js (захардкожено — grep по env не поймает).

### B5. Caddyfile (`/etc/caddy/Caddyfile`) — только блоки ContentHunter
> Файл общий для МНОГИХ проектов на хосте. CH-релевантные блоки:
```
client.contenthunter.ru {
    encode gzip zstd
    handle /api/* {
        reverse_proxy localhost:8000
    }
    handle {
        root * /var/www/validator
        try_files {path} /index.html
        file_server
    }
}

delivery.contenthunter.ru {
    encode gzip zstd
    reverse_proxy localhost:3848
}
```
> Прочие домены в этом Caddyfile (office2/auth/dashboard/producer/carousel/hr/tasks/handoff/api.systematika/pixel/systematika/analytics/summary) — ДРУГИЕ проекты, НЕ переезжают в рамках CH.

### B6. Команды запуска сервисов (pm2)
- **delivery** (pm2 id35 `autowarm`): script `server.js`, interpreter `node`, cwd `/root/.openclaw/workspace-genri/autowarm`. Порт 3848.
- **client backend** (pm2 id24 `validator`): script `/usr/bin/bash`, args:
  `-c 'set -a; source .env; set +a; uvicorn src.main:app --host 0.0.0.0 --port 8000'`,
  cwd `/root/.openclaw/workspace-genri/validator/backend`. Модуль приложения = **`src.main:app`**, порт **8000**. Venv-каталога НЕТ → uvicorn ставится глобально через pip для root.
- **unic-worker** (pm2 id36 `unic-worker`): python3 `unic-worker/worker.py`, cwd autowarm/unic-worker — рендер логотипов, делит unic-очередь.
- Прочие pm2 на хосте, относящиеся к CH-инфраструктуре фарминга/тестбенча: id28 `autowarm-farming-triage` (bash loop), id29 `autowarm-farming-orchestrator` (python3), id33 `autowarm-testbench` (node), id26 `autowarm-farming-testbench` (node, cwd `/home/claude-user/autowarm-testbench`).
- НЕ-CH pm2: id0 `ch-auth`, id2 `producer` (producer-copilot).
- client фронт = статика в `/var/www/validator` (Vue build). validator docker-compose файлы есть в каталоге (`docker-compose.yml`, `docker-compose.prod.yml`), но pm2 запускает БЕЗ docker.

---

## Блок C — БД `openclaw`

### КРИТИЧНО: две разные инстанции PostgreSQL на OLD
1. **Системный кластер 16/main, порт 5433** (`sudo -u postgres psql` попадает СЮДА через сокет) — содержит ДРУГОЙ проект (meeting/CRM: telegram_messages, transcriptions, sim_cards, meetings, people…), всего 35 MB. **Это НЕ БД ContentHunter.**
2. **Docker-контейнер `openclaw-postgres`** (`pgvector/pgvector:pg16`), проброшен на **0.0.0.0:5432** → ЭТО настоящая БД ContentHunter. Подключение: `psql -h 127.0.0.1 -p 5432 -U openclaw -d openclaw`. Volume `openclaw_pgdata` (`/var/lib/docker/volumes/openclaw_pgdata/_data`). Запущен через `docker run` (БЕЗ compose-меток).

> Урок: инструкция «подключайся `sudo -u postgres psql`» ведёт в НЕВЕРНЫЙ кластер (5433). Реальная БД CH — docker на 5432.

### Параметры БД CH (openclaw на 5432)
- Размер БД: **1955 MB (~1.9 GB)**.
- Таблиц в public: **153**. Доп. схемы (НЕ public): factory(35), hr(12), team(9), finance(4), drive(3), mymeet(3), meetings(2), client_service(2), knowledge(2), analytics_auth(1), knowledge_base(1).
- Роли: `openclaw` (superuser, владелец), `analytics_ro`, `anastasia`, `nika`, `plan_sync` + системные pg_*.

### Топ таблиц по строкам
| таблица | строк |
|---|---|
| autowarm_device_metrics | 4 104 620 |
| factory_inst_reels | 79 743 |
| factory_accounts_fans | 48 393 |
| factory_parsing_logs | 47 871 |
| factory_inst_reels_stats | 29 581 |
| validator_schedule_slots | 22 843 |
| unic_results | 15 149 |
| publish_queue | 10 938 |
| publish_tasks | 10 520 |
| autowarm_tasks | 7 886 |
| unic_result_assignments | 3 440 |
| validator_content | 2 260 |
| unic_tasks | 2 117 |
| validator_manual_publish_queue | 1 843 |
| validator_scheme_previews | 1 827 |

### Таблицы ContentHunter (public — мигрировать)
autowarm_* (autowarm_device_metrics, autowarm_tasks, autowarm_users, autowarm_settings, autowarm_day_logs, autowarm_llm_spend, autowarm_protocols, autowarm_token_logs),
publish_* (publish_queue, publish_tasks, publish_project_limits, publish_error_codes, publish_investigations),
publisher_* (publisher_obstacles, publisher_obstacle_outcomes, publisher_fixes),
validator_* (validator_content, validator_unic_content, validator_projects, validator_users, validator_brand_profiles, validator_schedule_slots, validator_scheme_previews, validator_scheme_preferences, validator_manual_publish_queue, validator_carousel_images, validator_moderation_rules, validator_virality_rules, validator_audit_log, validator_support_history),
unic_* (unic_results, unic_result_assignments, unic_tasks, unic_schemes, unic_settings),
factory_* (factory_inst_accounts/reels/reels_stats, factory_accounts_fans, factory_parsing_logs, factory_pack_accounts, factory_reg_accounts, factory_reg_tasks, factory_device_numbers, factory_sync_exclusions, factory_users),
logo_* (logo_generation_tasks, logo_selections, logo_variants),
farming_* (farming_error_codes, farming_fixes, farming_investigations),
device_state, raspberry_port, sim_cards, install_queue, installer_logs, phone_warm_tasks, tg_warm_tasks, wa_warm_tasks, tg_accounts, wa_accounts, warmup_daily_marks, warmup_entries, child_packs, account_audience_snapshots, account_daily_delta, account_purchases, social_audit_snapshots, social_credentials, user_permissions, user_sessions, system_flags, daily_report_runs, approval_notify_runs, agent_runs, agent_task_queue, ad_hoc_runs, archive_log, archive_tasks, backup_logs, incidents, fw_interest_clicks, alembic_version.

### ⚠️ ЧУЖИЕ (НЕ-CH) таблицы в той же БД — НЕ переносить как CH
- **LiteLLM_*** — 57 таблиц (LiteLLM proxy/биллинг LLM): LiteLLM_SpendLogs, LiteLLM_UserTable, LiteLLM_TeamTable, … — отдельная инфраструктура.
- **systematika_*** — проект Systematika (api.systematika.pro): systematika_clients, systematika_packages, systematika_billing_alerts, systematika_client_frameworks, systematika_token_usage.
- **billing_*** (billing_events, billing_spend_watermarks, billing_watermarks) — вероятно общий биллинг (уточнить владельца).
- **meeting/CRM**: meetings, meeting_chunks, people, people_ratings, client_messages, transcriptions, telegram_messages — проект встреч/CRM (дублирует имена из кластера 5433; принадлежность CH под вопросом — telegram_messages может быть алертами CH, остальное — нет).
- **Все НЕ-public схемы** (factory, hr, team, finance, drive, mymeet, meetings, client_service, knowledge, analytics_auth, knowledge_base) — отдельные проекты/срезы.

> ВЫВОД: БД `openclaw` — ОБЩАЯ мульти-проектная. Полный `pg_dump openclaw` притащит чужое (LiteLLM, Systematika, CRM, прочие схемы). Нужен **табличный отбор** CH-таблиц (dump по списку `-t public.<table>`), а не дамп всей БД. Внешние FK между CH и чужими таблицами надо проверить отдельно (open item).

### Аутентификация сервисов в БД
- delivery: TCP localhost:5432, креды захардкожены `openclaw/openclaw123` (B4).
- client: TCP localhost:5432, креды из `DATABASE_URL`/`ALEMBIC_DATABASE_URL` (user openclaw, db openclaw).
- Способ = пароль по TCP (НЕ peer/socket). Роль приложения = `openclaw` (superuser).

---

## Блок D — сетевая достижимость С НОВОГО сервера (NEW → внешние зависимости)
Все проверки прошли:
- **S3 Beget** (`https://s3.ru1.storage.beget.cloud`): HTTP **200** — OK.
- **ffmpeg-хост** `91.98.180.103:22` (SSH): **OPEN** — OK.
- **Шлюз устройств** `147.45.251.85` (ADB), порты `15017`, `15028`: **OPEN** — OK.
- **FACTORY_DB** `193.124.112.222:49002`: **OPEN** — OK.

Источник списка устройств: таблица `raspberry_port` (колонки: id, raspberry_number, adb, host, scr, port, synced_at). Все устройства за одним шлюзом `147.45.251.85`, adb-порты диапазона ~15017–15108. (Также в server.js встречается дефолтный host `82.115.54.26` для отдельной ветки — проверить отдельно при необходимости.)

> С NEW все внешние сетевые зависимости достижимы — whitelist нового IP, похоже, НЕ требуется (но подтвердить, что ADB-шлюз/фабрика не фильтруют по IP при реальном хендшейке, а не только TCP-connect).

---

## ИТОГ / РИСКИ

### Готово
- NEW доступен по SSH, чистый (пустой /opt, нет прикладных портов), 16 CPU / 30 GB / 575 GB свободно.
- Снят полный инвентарь NEW, конфиги OLD, состав БД, сетевая достижимость.
- Все внешние зависимости (S3, ffmpeg, устройства, factory-DB) достижимы с NEW по TCP.

### Чего не хватает на NEW (провижн)
- Поставить: Docker + docker compose (БД в контейнере pgvector), Node 22.x + pm2, Caddy 2.x, Python 3.12 + pip + uvicorn, Android platform-tools (adb), psql-client.
- Swap на NEW = 0 — желательно добавить swap (особенно при сборках/дампах).
- Настроить ufw (сейчас выключен) — открыть только нужное (22/80/443; 5432 НЕ наружу!).

### Риски / блокеры
1. **БД общая, мульти-проектная (1.9 GB, 153 public-таблицы + 11 чужих схем).** Полный дамп притащит LiteLLM (57 табл.), Systematika, CRM/meetings и чужие схемы. Нужен табличный отбор CH-таблиц. РИСК: внешние FK / общие справочники между CH и чужими таблицами (`billing_*`, `telegram_messages`, схема `factory`) — требует проверки перед селективным дампом. **Открытый вопрос: договориться, что именно из «пограничных» (billing_*, telegram_messages, схема factory) принадлежит CH.**
2. **Две инстанции Postgres на OLD.** Реальная БД CH = Docker `openclaw-postgres` на 5432 (НЕ системный кластер 5433). Инструкция `sudo -u postgres psql` ведёт в чужой кластер — мигрировать данные надо из docker-контейнера (`pg_dump -h 127.0.0.1 -p 5432 -U openclaw`).
3. **Образ БД = pgvector/pgvector:pg16**, не ванильный postgres — на NEW нужен pgvector (расширение vector используется). Контейнер запущен `docker run` без compose — compose-манифест для воспроизведения придётся написать (volume `openclaw_pgdata`).
4. **delivery: креды БД ЗАХАРДКОЖЕНЫ в server.js** (`openclaw/openclaw123`, localhost:5432). grep по env их не найдёт. На NEW сохранить те же креды/порт ЛИБО пропатчить server.js.
5. **`autowarm_device_metrics` = 4.1M строк** — основной объём дампа; учесть время копирования в окне переезда (можно мигрировать без него или догрузить отдельно — уточнить, нужна ли история метрик).
6. **client фронт = статика `/var/www/validator`** (вне репо-каталога) — нужно собрать заново на NEW или скопировать build.
7. **client backend uvicorn — без venv** (глобальный pip root). На NEW лучше завести venv по `requirements.txt`.
8. **Внешняя FACTORY_DB** (193.124.112.222:49002) и ADB-шлюз могут фильтровать по IP при реальном хендшейке — TCP-connect прошёл, но реальную аутентификацию/ADB-connect надо проверить с NEW в окне переезда.

### Статус: **DONE_WITH_CONCERNS**
Разведка выполнена полностью. Главный concern — БД общая и нетривиальна для переноса (табличный отбор + две PG-инстанции + pgvector + захардкоженные креды). Открытые вопросы помечены выше.

---

## Разведка по коду: CH-таблицы и FK

> Метод: полный список public-таблиц из БД (`openclaw-postgres` :5432) пересечён с грепом обеих кодовых баз — delivery `/root/.openclaw/workspace-genri/autowarm` (raw SQL в JS/PY) и client `/root/.openclaw/workspace-genri/validator/backend` (SQLAlchemy `__tablename__` + raw `text()` + alembic). Для пограничных таблиц проверены ИМЕНА ФАЙЛОВ-потребителей (живой publish/validator vs farming/warming/testbench). READ-ONLY, в БД ничего не менялось.

### Сводка по схемам БД
public = 152 табл. Чужие схемы (НЕ трогаем): `factory`(35), `hr`(12), `pg_catalog`(64), `team`(6), `finance`(4), `information_schema`(4), `analytics_auth`,`client_service`,`drive`,`knowledge`,`knowledge_base`,`meetings`,`mymeet`. Все FK внутри этих схем замкнуты на себя.

> ВАЖНО: схема `factory` (35 табл: `factory.factory_inst_accounts`, `factory.device_numbers`, `factory.content` …) — это ОТДЕЛЬНЫЙ продукт (account/creator factory), НЕ CH. Не путать с public-таблицами `factory_*`, которые ЯВЛЯЮТСЯ инвентарём аккаунтов CH (живой `publisher.py` читает `FROM factory_pack_accounts JOIN factory_inst_accounts` БЕЗ схемы → public). Единственное обращение CH-кода к чужой схеме: `server.js` читает `factory.device_numbers` (cross-schema, НЕ FK) — рантайм-связь, см. concern ниже.

### Классификация 152 public-таблиц

**CH-CORE — 65 табл. (переносим).** Кандидат на `-t`-список:

_delivery (publish/autowarm/инвентарь аккаунтов), 47:_
`account_audience_snapshots, account_daily_delta, ad_hoc_runs, agent_runs, agent_task_queue, approval_notify_runs, archive_log, archive_tasks, autowarm_day_logs, autowarm_device_metrics, autowarm_llm_spend, autowarm_protocols, autowarm_settings, autowarm_tasks, autowarm_token_logs, autowarm_users, child_packs, daily_report_runs, factory_accounts_fans, factory_device_numbers, factory_inst_accounts, factory_inst_reels, factory_inst_reels_stats, factory_pack_accounts, factory_parsing_logs, factory_reg_accounts, factory_reg_tasks, factory_sync_exclusions, publish_error_codes, publish_investigations, publish_project_limits, publish_queue, publish_tasks, publisher_fixes, publisher_obstacle_outcomes, publisher_obstacles, raspberry_port, social_audit_snapshots, social_credentials, system_flags, unic_result_assignments, unic_results, unic_schemes, unic_settings, unic_tasks, user_permissions, user_sessions`

_client (validator/FastAPI), 18:_
`alembic_version, logo_generation_tasks, logo_selections, logo_variants, validator_audit_log, validator_brand_profiles, validator_carousel_images, validator_content, validator_manual_publish_queue, validator_moderation_rules, validator_projects, validator_schedule_slots, validator_scheme_preferences, validator_scheme_previews, validator_support_history, validator_unic_content, validator_users, validator_virality_rules`

> ⚠️ ГРЕЙ-ЗОНА внутри CH-CORE: `factory_reg_accounts` / `factory_reg_tasks` создаются продуктом регистрации аккаунтов (`account_factory.py`, `gmail_factory_appium.py`, `register_social.py` — это farming-сторона), НО их читают ЖИВЫЕ publish-файлы `account_switcher.py`, `publisher_base.py`, `account_blocks.py`, `slot_matcher_cron.js` (проверка блокировок/готовности аккаунта). Оставлены в CORE на всякий случай; подтвердить с человеком — нужны ли реально для публикации, или это только для регистрации (тогда LEGACY).
> `alembic_version` грепом не находится (управляется библиотекой Alembic), но это таблица версий миграций validator (`backend/alembic/versions/001..010`) → структурно CH-CORE-client.

**CH-LEGACY — 12 табл. (НЕ переносим: farming/warming/testbench).**
| Таблица | Почему legacy (файлы-потребители) |
|---|---|
| `farming_error_codes`, `farming_fixes`, `farming_investigations` | только `farming_*.py/js` (триаж фермы) + server.js-админка фермы |
| `phone_warm_tasks` | `phone_warmer.py`, `phone_status.js`, `scheduler.js` — прогрев телефонов |
| `tg_accounts`, `tg_warm_tasks` | `telegram_warmer.py` — прогрев Telegram |
| `wa_accounts`, `wa_warm_tasks` | `whatsapp_warmer.py` — прогрев WhatsApp |
| `sim_cards` | `sim_scanner.py` + `whatsapp_warmer.py` — sim-инфра прогрева |
| `warmup_daily_marks`, `warmup_entries` | 0 живых ссылок, FK-пара «warmup» (прогрев) |
| `incidents` | ссылки ТОЛЬКО в `tests/` (фикстура), живого кода нет |

**FOREIGN — 71 табл. (чужие продукты).**
`LiteLLM_*` (57), `systematika_*` (5: billing_alerts, client_frameworks, clients, packages, token_usage), `billing_events`, `billing_spend_watermarks`, `billing_watermarks` (0 ссылок CH), `telegram_messages` (0 ссылок CH, 15 MB CRM), `client_messages` (CRM), `people`, `people_ratings` (CRM), `backup_logs` (FK→systematika_clients), `factory_users` (продукт account-factory, 0 ссылок CH).

**UNKNOWN — 4 табл. (0 упоминаний нигде, разобрать с человеком).**
`account_purchases`, `fw_interest_clicks`, `install_queue`, `installer_logs` — пустых/неиспользуемых имён нет в коде ни delivery, ни client. Скорее всего мёртвые/чужие; по умолчанию НЕ переносить, но подтвердить.

Итог: 65 CORE + 12 LEGACY + 71 FOREIGN + 4 UNKNOWN = 152 ✓.

### Анализ внешних ключей (Шаг 4)
Все 66 FK в БД перечислены и сопоставлены с классификацией. Результат:

- **Межпродуктовых FK CH-CORE ↔ FOREIGN — НЕТ.** Ни одна CH-CORE-таблица не ссылается на чужую и наоборот.
- **Межсхемных FK из public CH в `factory`/`hr`/`team`/`finance` — НЕТ.** FK этих схем замкнуты внутри себя.
- Единственный FK CORE ↔ LEGACY: `farming_investigations`(LEGACY) → `autowarm_tasks`(CORE). Так как `farming_investigations` мы НЕ переносим, ссылающаяся таблица просто отсутствует в дампе; цель (`autowarm_tasks`) переносится. **Безопасно** (sink есть, source выкинут).
- FK CORE ↔ CORE через границу delivery/client: `validator_manual_publish_queue` → `autowarm_users` (×2, published_by/taken_by) и validator_content/projects/slots → validator_users. Все участники в CH-CORE → попадают в один дамп. **Безопасно.**

**ВЕРДИКТ FK: выборочный дамп CH-CORE безопасен — межпродуктовых и межсхемных FK у CH нет.** Все FK CH-CORE замкнуты внутри множества CH-CORE.

### Вердикт по пограничным (Шаг 5)
- **`billing_*`** (billing_events / billing_spend_watermarks / billing_watermarks): **0 ссылок** ни в delivery, ни в client → **FOREIGN (billing-продукт). Не переносим.**
- **`telegram_messages`**: **0 ссылок** в CH-коде (15 MB, CRM/мессенджер) → **FOREIGN. Не переносим.**
- **`factory_inst_reels`** и public `factory_*`: используются ЖИВЫМ CH (publisher.py, validator analytics/contract/accounts_service) → **CH-CORE (инвентарь аккаунтов + аналитика рилсов).** Переносим.
- **схема `factory` (35 табл.)**: чужой продукт (account/creator factory). CH-код к ней почти не обращается, кроме одного `factory.device_numbers` в server.js → **FOREIGN-схема, не переносим**, но см. рантайм-concern.

### Рекомендация по дампу (Шаг 6)
Окружение: расширения в БД — `vector 0.8.1`, `pg_trgm 1.6`, `pgcrypto 1.3`, `plpgsql`. Кастомные enum-типы в public: `contentniche, contentstatus, contenttype, moderationstatus, schemepreferencestatus, slotstatus, slottype, userrole` (все принадлежат `validator_*` → нужны для CH) + `JobStatus` (LiteLLM, безвреден). **vector-колонок в CH-CORE-таблицах НЕТ** (vector нужен только чужим LiteLLM/knowledge); для CH достаточно `pg_trgm` + `pgcrypto`.

**ГОТЧА выборочного дампа:** `pg_dump -t <table>` НЕ выгружает CREATE TYPE (enum) и CREATE EXTENSION — они уровня схемы/БД. При чистом `-t`-листе restore validator-таблиц упадёт на отсутствующих enum-типах.

**Рекомендуемая стратегия — schema-level с исключениями (типы/расширения подтянутся сами):**
```bash
pg_dump -h 127.0.0.1 -p 5432 -U openclaw -d openclaw \
  --schema=public --no-owner --no-privileges \
  -T 'LiteLLM_*' \
  -T 'systematika_*' \
  -T 'billing_*' \
  -T people -T people_ratings -T client_messages -T telegram_messages -T backup_logs -T factory_users \
  -T 'farming_*' -T phone_warm_tasks -T tg_accounts -T tg_warm_tasks \
  -T wa_accounts -T wa_warm_tasks -T sim_cards -T warmup_daily_marks -T warmup_entries -T incidents \
  -T account_purchases -T fw_interest_clicks -T install_queue -T installer_logs \
  --exclude-table-data=autowarm_device_metrics \
  --exclude-table-data=factory_inst_reels_stats \
  --exclude-table-data=factory_inst_reels \
  --exclude-table-data=factory_parsing_logs \
  -Fc -f /tmp/ch_public.dump
```
Плюсы: enum-типы validator и `CREATE EXTENSION` попадут автоматически; останется лишний enum `JobStatus` (безвреден). Минус: список `-T` длинный, но он по семействам.

На целевой БД ДО restore: `CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS vector;` (vector — т.к. образ pgvector и на случай чужих остатков).

**Альтернатива — явный `-t`-вайтлист 65 CH-CORE** (надёжнее против утечки чужих данных, но руками донести 8 enum-типов + 2 extension перед restore). Подходит, если нужен максимально чистый CH-дамп без чужих строк.

**Таблицы-тяжеловесы (кандидаты на дамп без истории, `--exclude-table-data`):**
| Таблица | Размер | Строк | Решение |
|---|---|---|---|
| `factory_inst_reels_stats` | 896 MB | 29.6k | аналитика трендов — структура без истории (догрузить при нужде) |
| `autowarm_device_metrics` | 701 MB | 4.1M | телеметрия устройств — структура без истории |
| `factory_inst_reels` | 53 MB | 79.7k | аналитика рилсов — по желанию урезать |
| `factory_parsing_logs` | 10 MB | 47.9k | логи парсинга — урезать |

Без этих историй дамп CH-CORE сжимается с ~1.6 GB до ~единиц-десятков MB.

### Рантайм-concern (не дамп, но связность)
`server.js` исполняет запрос к `factory.device_numbers` (чужая схема factory, которую НЕ мигрируем) + есть внешняя FACTORY_DB `193.124.112.222:49002` (см. п.8 выше). Если CH в рантайме реально читает локальную схему `factory` — на NEW её не будет. Проверить: это рудимент (account-factory) или живая зависимость публикации. Скорее всего инвентарь аккаунтов уже унифицирован в public `factory_*` (комментарий в accounts_service.py: «factory unification, 2026-04-22»), а `factory.device_numbers` в server.js — легаси-чтение. Подтвердить перед отключением OLD.
