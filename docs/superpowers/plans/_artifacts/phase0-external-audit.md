# Phase 0 — Аудит внешних обращений ContentHunter (READ-ONLY)

Дата: 2026-06-07. Сервер OLD `72.56.107.157` (hostname `fra-1-vm-y49r`).
Код: delivery `/root/.openclaw/workspace-genri/autowarm`, client `/root/.openclaw/workspace-genri/validator`.
БД CH: pgvector контейнер localhost:5432, БД `openclaw`.

Правило: CH должен работать ТОЛЬКО со схемой `public` своей БД `openclaw`. Любое обращение в чужую
схему (`factory`, `hr`, `team`, `finance`, …) или во внешнюю БД = баг для переезда.

## Контекст БД

В одной БД `openclaw` живут чужие схемы других систем (одна общая Postgres-инстанция):

| схема | таблиц |
|---|---|
| factory | 35 |
| hr | 12 |
| team | 6 |
| finance | 4 |
| client_service, drive, knowledge, knowledge_base, meetings, mymeet, analytics_auth | по 1–2 |

CH-код пересекает границу **только в схему `factory`** (5 мест). Обращений в `hr`/`team`/`finance`/
прочие из кода CH НЕ найдено. В `public` уже существует устоявшаяся конвенция локальных синк-копий с
префиксом `factory_*` (`factory_device_numbers`, `factory_pack_accounts`, `factory_inst_reels`,
`factory_accounts_fans`, …), которыми пользуется почти весь код. Кросс-схемные `factory.` —
это оставшиеся «хвосты».

## 1. Таблица внешних обращений

| место (файл:строка) | тип | объект | public-аналог | предлагаемый фикс |
|---|---|---|---|---|
| `autowarm/sim_scanner.py:117` | чужая схема | `factory.device_numbers` (LEFT JOIN) | ДА — `public.factory_device_numbers` (те же колонки + `synced_at`; 181 vs 179 строк, public свежее) | переключить на `public.factory_device_numbers` |
| `autowarm/sim_scanner.py:118` | чужая схема | `factory.raspberry_port` (LEFT JOIN) | ДА — `public.raspberry_port` (идентичные колонки + `synced_at`; 10 = 10 строк) | переключить на `public.raspberry_port` |
| `autowarm/server.js:8767` | чужая схема | `factory.device_numbers` (LEFT JOIN в `/api/sim-cards`) | ДА — `public.factory_device_numbers` | переключить на `public.factory_device_numbers`. NB: в этом же запросе строка ниже уже использует public `raspberry_port` — несогласованность |
| `autowarm/warmer.py:1198` | чужая схема | `factory.hashtags` (SELECT, fallback-источник ключевых слов) | НЕТ public-аналога (в public нет ни `hashtags`, ни `factory_hashtags`; 628 строк только в `factory.hashtags`) | требует решения: либо синк в новую `public.factory_hashtags`, либо убрать fallback (первичный источник — `public.validator_brand_profiles`) |
| `autowarm/warmer.py:2478` | чужая схема | `factory.hashtags` (SELECT COUNT, проверка наличия ключевых слов) | НЕТ (то же) | то же, что выше |

Ложные срабатывания (НЕ баги, для прозрачности): `factory.run(...)` в `gmail_factory_appium.py:588`
и `account_factory.py:4193` — вызовы метода Python-объекта с именем `factory`, не SQL. `search_path`
в `warmer.py:2621/2649` — локальная переменная (путь к скриншоту), не SET search_path. В
validator/backend все совпадения `FROM ...` — это `from sqlalchemy...` импорты.

## 2. Внешние БД-подключения (кроме основной localhost:5432/openclaw)

| место | хост/БД | назначение | статус |
|---|---|---|---|
| `validator/backend/.env:19-23` (+ 4 бэкап-файла `.env.bak*`) | `193.124.112.222:49002` БД `factory`, user `roman_ai_readonly` (readonly) | внешняя factory-БД | **МЁРТВАЯ КОНФИГУРАЦИЯ**: переменные `FACTORY_DB_HOST/PORT/NAME/USER/PASSWORD` НЕ читаются нигде в коде validator (`src/` чисто; нет psycopg/asyncpg.connect по ним; `config.py` их не объявляет). `docs/sla.md` подтверждает: `distPool`/внешняя factory DB удалены. → удалить из `.env` |

Все реальные подключения CH идут на localhost/openclaw:
- delivery server.js: `sessionPool` (server.js:73) и `pool` (server.js:210) — оба `localhost:5432/openclaw`.
- delivery Python (publisher.py, account_switcher.py, sim_scanner.py, posts_parser.py,
  profile_inspector.py, screen_recovery.py, obstacle_promoter.py, register_social.py,
  publisher_kernel.py, farming_orchestrator.py, tools/fixture_triage.py, …): `DB_CONFIG`/`DB_URL`
  = `localhost:5432/openclaw`.
- client validator: `config.py:7` `database_url = postgresql+asyncpg://openclaw:openclaw123@localhost:5432/openclaw`;
  скрипты `scripts/*.py` — тот же localhost.

Внешних БД-подключений, реально используемых кодом, НЕ найдено. Единственная внешняя строка
подключения — мёртвый `FACTORY_DB_*` в validator `.env`.

## 3. Проверка public-аналогов (факты из БД)

```
factory.device_numbers        = 179 строк   |  public.factory_device_numbers = 181 (public свежее)
factory.raspberry_port        =  10 строк   |  public.raspberry_port         =  10 (идентично)
factory.hashtags              = 628 строк   |  public-аналога НЕТ
```

Структура колонок:
- `factory.device_numbers` (id, device_number, active, device_id, raspberry, warmup_end_date) ⊂
  `public.factory_device_numbers` (те же 6 + `synced_at`). Используемые в SQL колонки
  (`device_number`, `raspberry`) присутствуют → drop-in.
- `factory.raspberry_port` (id, raspberry_number, adb, host, scr, port) = `public.raspberry_port`
  (те же 6 + `synced_at`). Используемые (`raspberry_number`, `adb`, `host`) присутствуют → drop-in.
- `factory.hashtags` — public-копии нет вообще.

## Итог

Всего внешних обращений из кода CH: **5 в чужую схему `factory`** + **1 мёртвая внешняя
БД-конфигурация** (`FACTORY_DB_*` в validator `.env`, кодом не используется).

Тривиально чинятся переключением на public (drop-in, данные уже синкаются, колонки совпадают): **3**
- sim_scanner.py:117 → `public.factory_device_numbers`
- sim_scanner.py:118 → `public.raspberry_port`
- server.js:8767 → `public.factory_device_numbers`

Тривиально (удалить мёртвую конфигурацию): **1**
- validator `.env` `FACTORY_DB_*` (+ бэкапы) — удалить; кодом не читается.

Требует решения / переноса данных: **2 (одна таблица)**
- warmer.py:1198 и :2478 `factory.hashtags` — public-аналога нет (628 строк). Это fallback-источник
  ключевых слов (первичный — `public.validator_brand_profiles`). Варианты: (а) завести синк в новую
  `public.factory_hashtags` по образцу остальных `factory_*` и переключить код; (б) выпилить fallback,
  оставив только validator_brand_profiles. Нужен выбор Данила/владельца данных.

Неясного/невыясненного: нет. Обращений в `hr`/`team`/`finance` и прочие чужие схемы из кода CH не
обнаружено. Все рабочие подключения — localhost/openclaw.
