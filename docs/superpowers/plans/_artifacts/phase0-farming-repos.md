# Phase 0 — Карта системы «фарминг + регистрация аккаунтов» (READ-ONLY разведка)

Сервер OLD `72.56.107.157` (host `fra-1-vm-y49r`). Дата: 2026-06-07.
БД: pgvector контейнер `localhost:5432`, db `openclaw`, user `openclaw`.
Каталог проектов: `/root/.openclaw/workspace-genri/`.

> ВАЖНО (вывод вперёд): кода «фарминга и регистрации аккаунтов» как **отдельного
> репозитория НЕТ**. Реальная регистрация/прогрев живёт ВНУТРИ репо
> `delivery-contenthunter` (каталог `autowarm`). Отдельные внешние сущности — это
> внешний продукт **factory** (БД `193.124.112.222`, владелец «roman», вне нашего
> контроля) и вспомогательный дашборд `farm-platform`.

---

## 1. Репозитории / каталоги-кандидаты

| Каталог | Git remote (GenGo2/…) | Ветка | Назначение |
|---|---|---|---|
| `autowarm` | `delivery-contenthunter.git` | `main` | **delivery + ВСЯ логика фарминга/регистрации/прогрева** (см. §2). Это тот же репо, куда мы шипим публикацию. |
| `farm-platform` | `farm-platform.git` | `main` (1 коммит «Initial commit», `cc57608`) | Express-дашборд (порт 3853) для управления фермой 170 телефонов: прогрев, здоровье устройств, инциденты, закупки. Читает factory DB (readonly) + локальную `openclaw`. **СЕЙЧАС НЕ ЗАПУЩЕН** (нет в pm2). |
| `autowarm-lobster` | — (НЕ git-репо) | — | Каталог из 5 мелких shell/`.lobster` скриптов (`publish-status.sh`, `reset-stuck.sh` и т.п.). Оперативные хелперы для очереди публикации, не фарминг. |
| `producer-copilot` | `agent-office.git`? нет — `producer-copilot` (pm2 id2) | `main` | Аналитика рилсов: коннектится к внешней factory DB (193.124.112.222) И читает локальные `factory_inst_reels*`/`factory_inst_accounts`. Потребитель данных, не регистратор. |
| `validator` | `validator-contenthunter.git` | `main` | Клиентский кабинет. Читает `factory_inst_accounts`/`factory_pack_accounts`/`account_packages` (пакеты аккаунтов проекта). Потребитель, не регистратор. |
| `scripts/` | (часть workspace, без своего .git) | — | `factory_sync.py` — мост внешняя factory DB → локальная `openclaw` (§3). `device_monitor.py` — пишет `factory.device_state`. |

Прочие каталоги (`ch-auth`, `carousel-maker`, `agent-office`, `hr-*`, `model-router`, `task-tracker`, `proxy-research` и т.д.) к фармингу/регистрации отношения не имеют.

### Код регистрации/фарминга внутри `autowarm` (delivery-contenthunter)
Регистрация аккаунтов (UI-автоматизация телефонов через ADB/Appium):
- `account_factory.py` — авто-регистрация Gmail + Instagram + TikTok + YouTube через UI телефона.
- `register_social.py` — регистрация соцсетей на готовый Gmail (наследует `AccountFactory`).
- `gmail_factory_appium.py` — регистрация Gmail, пишет `factory_reg_tasks`/`factory_reg_accounts`.
- `account_switcher.py`, `account_blocks.py`, `account_revision.py` — управление аккаунтами.

Прогрев (warmup/farming):
- `phone_warmer.py`, `warmer.py`, `telegram_warmer.py`, `sim_scanner.py` — прогрев устройств/Telegram/SIM.
- `farming_orchestrator.py`, `farming_triage_classifier.py`, `farming_agent_diagnose.py`,
  `farming_agent_apply.py`, `farming_auto_rollback.py`, `farming_errors.py`,
  `farming_testbench_scheduler.js` — фарминг-тестбенч и авто-триаж ошибок фарминга.

Итого по grep имён таблиц фарминга/регистрации (`*.py`,`*.js`, без node_modules/.git):
**autowarm = 60 файлов, validator = 9, scripts = 2, producer-copilot = 1, farm-platform = 1.**
Подавляющая масса — в `autowarm`.

---

## 2. Схема `factory` и внешняя FACTORY_DB

### Внешняя FACTORY_DB
- `193.124.112.222:49002`, db `factory`, user `roman_ai_readonly` (READONLY, пароль захардкожен в `scripts/factory_sync.py`).
- Это **внешний продукт «factory» — фабрика регистрации/прогрева аккаунтов, владелец сторонний («roman»)**. НЕ наш репозиторий, доступ только на чтение.
- Реальная массовая регистрация и первичные данные устройств/аккаунтов/рилсов рождаются ТАМ.

### Мост: `scripts/factory_sync.py`
Односторонняя синхронизация **factory DB → локальная openclaw (public-схема)**:
- factory.`factory_projects` → `validator_projects`
- factory.`device_numbers` → `factory_device_numbers`
- factory.`pack_accounts` → `factory_pack_accounts` (+ `account_packages`)
- factory.`factory_inst_accounts` → `factory_inst_accounts`
- factory.`factory_inst_reels` / `factory_inst_reels_stats` → одноимённые
- Upsert `ON CONFLICT … synced_at=NOW()`; защита локальных правок через `factory_sync_exclusions`
  (delivery `server.js:4522+` добавляет row_id в exclusions, чтобы sync не перезатёр).

### Локальная схема `factory` (35 таблиц) — ОТДЕЛЬНО от public
- В `openclaw` есть отдельная схема `factory` с 35 таблицами (`factory.factory_inst_accounts`=1133,
  `factory.pack_accounts`=183, `factory.device_numbers`=179, плюс `hashtags`, `raspberry_port`,
  `device_state`, `factory_unic_*`, `factory_creators*` и др.).
- Это **НЕ FDW и НЕ logical replication** (нет foreign servers, нет pg_subscription). Похоже на
  прямой снимок/дамп внешней factory DB в локальную схему (исторический/референсный набор).
- Используется кодом ЛЕГКО (4 файла): `autowarm/sim_scanner.py` (`factory.device_numbers`,
  `factory.raspberry_port`), `autowarm/warmer.py` (`factory.hashtags`), `autowarm/server.js:8767`
  (`factory.device_numbers`), `scripts/device_monitor.py` (пишет `factory.device_state`).
- ⚠️ НЕЯСНО: чем и когда наполняется локальная схема `factory` (механизм снимка не найден).
  Public-таблицы (`factory_inst_accounts` synced_at=2026-06-04, 1560 строк) — свежее и активнее,
  чем схема `factory` (1133). Рабочий путь delivery = public-таблицы, не схема `factory`.

---

## 3. Карта связи с delivery

Связь **только через локальную БД `openclaw` (public-схема)** — НЕ HTTP, НЕ общий код с внешним factory.

```
[Внешний продукт factory]            [autowarm = delivery-contenthunter]
193.124.112.222:49002 (RO)           ── регистрация/прогрев пишет:
   │                                     factory_reg_tasks, factory_reg_accounts
   │ factory_sync.py (1-сторонний)       (account_factory/register_social/gmail_factory_appium)
   ▼                                  
public.factory_device_numbers  ◄────────── delivery server.js ЧИТАЕТ (~130 ссылок):
public.factory_pack_accounts                выбор аккаунта/устройства под publish-задачу
public.factory_inst_accounts                (factory_pack_accounts + factory_device_numbers +
public.factory_inst_reels(_stats)            factory_inst_accounts; account_packages)
public.account_packages
   ▲                                  
   └─ читают также: validator (кабинет клиента), producer-copilot (аналитика рилсов)
```

Ключевые общие таблицы (public, БД `openclaw`) — это «шина»:
- `factory_inst_accounts`, `factory_pack_accounts`, `factory_device_numbers` — delivery берёт из них
  аккаунт+устройство для публикации (server.js строки ~1074, 2657-5265, и т.д.).
- `factory_reg_accounts`, `factory_reg_tasks` — пишет САМ autowarm (регистрация), читает delivery/тестбенч.
- `account_packages` — пакеты аккаунтов проекта (мост validator↔delivery).
- `phone_warm_tasks`, `warmup_entries`, `warmup_daily_marks`, `farming_*`, `sim_cards`,
  `tg_accounts/tg_warm_tasks`, `wa_accounts/wa_warm_tasks` — прогрев, в той же public-БД.

Вывод по связности: фарминг/регистрация и delivery — **один процесс БД и во многом один репозиторий
(autowarm)**. Они делят и код (импорты `account_factory` из `register_social`), и БД (public-схема).

---

## 4. Процессы (pm2)

| id | name | cwd | script | Роль |
|---|---|---|---|---|
| 35 | autowarm | `…/autowarm` | server.js | **ПРОД delivery** (читает factory-аккаунты, публикует). Нужен. |
| 36 | unic-worker | `…/autowarm/unic-worker` | worker.py | ПРОД уникализация. Нужен. |
| 24 | validator | `…/validator/backend` | bash→uvicorn | ПРОД кабинет клиента. Нужен. |
| 2 | producer | `…/producer-copilot` | server.js | ПРОД аналитика рилсов (читает factory DB+public). |
| 0 | ch-auth | `…/ch-auth` | server.js | ПРОД авторизация. Не фарминг. |
| 29 | autowarm-farming-orchestrator | `…/autowarm` | farming_orchestrator.py | **ТЕСТБЕНЧ**: 24/7 ставит farming-задачи на phone #171 (packs 308/309). По докстрингу — «orchestrator для farming-testbench». QA, не везти в прод как есть. |
| 28 | autowarm-farming-triage | `…/autowarm` | farming-triage-loop.sh | Авто-триаж ошибок фарминга (`farming_*`-таблицы). Сопутствует тестбенчу. |
| 26 | autowarm-farming-testbench | `/home/claude-user/autowarm-testbench` | farming_testbench_scheduler.js | **ТЕСТБЕНЧ фарминга** (из НЕ-прод дерева). QA, не везти. |
| 33 | autowarm-testbench | `…/autowarm` | testbench_scheduler.js | **ТЕСТБЕНЧ публикации** (phone #19). QA, не везти. |

systemd (все inactive/dead): `autowarm-testbench-orchestrator/rollback`, `autowarm-publish-media-sweeper`,
а также упомянутый в докстринге `autowarm-farming-orchestrator.service` — фактически крутится через pm2.

**farm-platform (порт 3853) НЕ запущен** (нет ни в pm2, ни активным сервисом) — дашборд-дефолт/архив.

`factory_sync.py` — **НЕ найден в cron/pm2/systemd**, при этом данные свежие (`synced_at=2026-06-04`),
а оба лог-файла (`scripts/factory_sync.log`, `/var/log/factory_sync.log`) обрываются в марте.
⚠️ Механизм/расписание запуска синка сейчас НЕИЗВЕСТНЫ — требует уточнения перед миграцией.

QA-тестбенчи (можно НЕ везти как прод): id 26, 28(частично), 29, 33.
ПРОД-нужное: id 35, 36, 24, 2, 0 + механизм factory_sync.

---

## 5. Предварительная оценка связности (merge vs separate)

- **Регистрация + фарминг кода = это и есть `autowarm` (delivery-contenthunter).** Отдельного репо
  «farming/registration» НЕ существует. Файлы регистрации (`account_factory.py`,
  `register_social.py`, `gmail_factory_appium.py`) и прогрева (`phone_warmer.py`, `warmer.py`,
  `telegram_warmer.py`, `farming_*`) лежат в одном дереве с delivery и импортируют друг друга
  (например `register_social` → `from account_factory import …`).
- **БД общая (public-схема openclaw).** delivery и регистрация делят те же таблицы
  (`factory_reg_*`, `factory_inst_accounts`, `factory_pack_accounts`, `factory_device_numbers`).
- **Внешняя зависимость одна — продукт factory** (193.124.112.222, чужой, RO) + мост `factory_sync.py`.
  Её НЕ «сливать» — её надо просто перенацелить (DSN/доступ) и обеспечить запуск синка на новом хосте.
- `farm-platform` — отдельный лёгкий репо-дашборд, слабо связан (читает те же public/ factory DB),
  можно везти отдельно или не везти (сейчас не запущен).
- `producer-copilot` / `validator` — отдельные репо-потребители, общая БД.

**Рекомендация для решения merge vs separate:**
Фарминг+регистрация уже физически ВНУТРИ репо delivery (autowarm) — «сливать» нечего, они и так едины;
отделять их в отдельный репо было бы дополнительной работой без выгоды на этом этапе.
Что реально надо при переезде:
1. Перенести репо `delivery-contenthunter` (autowarm) целиком (он несёт и delivery, и регистрацию, и фарминг).
2. Поднять локальную БД `openclaw` со ВСЕМИ public factory_*/farming_*/warmup_*/`*_warm_tasks`
   таблицами + схемой `factory` (35 таблиц) + `account_packages`.
3. Перенацелить и восстановить расписание `factory_sync.py` (доступ к внешней factory DB
   193.124.112.222 с нового хоста) — **критический внешний зависимый канал**.
4. Тестбенч-процессы (id 26/28/29/33, phone #171/#19) — опционально, как QA, не блокируют прод.

---

## Открытые вопросы / неясности (НЕ выдумано — помечено)
- Чем наполняется ЛОКАЛЬНАЯ схема `factory` (35 таблиц)? Снимок/дамп — механизм не найден.
- Кто/что запускает `factory_sync.py` сейчас (данные свежие 2026-06-04, но cron/pm2/systemd/логи молчат с марта)?
- `farm-platform` — нужен ли вообще на новом хосте (сейчас не запущен, 1 коммит).
