# Brief: Publish testbench + agent fix-loop (24/7)

**Создан:** 2026-04-21
**Статус:** brief (input для следующего `/aif-plan full`, кодинг НЕ в scope brief'а)
**Инициатор:** пользователь (решение 2026-04-21 — bold-вариант, старт сразу с агентом)
**Память:** `project_publish_testbench.md`

## 0. TL;DR

Круглосуточный контур автоисправления публикатора. На жертвенном устройстве (phone №19, пак «Тестовый проект_19», проект «Тестовый проект») постоянно гоняются попытки публикации → каждое падение → fixture в S3 → триаж-агент пишет диагноз → для узких классов (сместился селектор, нужен timeout bump) агент сам правит код за feature-flag → метрика успеха за последний час автоматически проверяет результат → при регрессии — авто-rollback. Сложные баги идут пользователю на аппрув.

**Цель фазы 1:** довести публикацию до рабочего состояния за счёт систематического потока данных и быстрых итераций.
**Цель фазы 2 (после стабилизации):** оптимизация алгоритма под изменения соц. сетей, регресс-корпус в CI.

## 1. Что уже есть (факт, не строим заново)

| Что | Где | Комментарий |
|---|---|---|
| Публикатор | `publisher.py` (autowarm, external repo `GenGo2/delivery-contenthunter`) | IG/TT/YT. Функции `_check_account_device_mapping`, `_open_instagram_camera`, `_mark_task_failed_by_guard`. |
| Таблица попыток | `publish_tasks` (DB `openclaw:openclaw123@localhost:5432`) | `id, platform, account, device_serial, status, events (JSONB), log, screen_record_url, started_at, updated_at`. |
| Категоризация ошибок | `events[].meta.category` в JSONB | **Freeform-строки**, не enum. ~12 распознанных категорий, часть со значением NULL. |
| Запись экрана | S3 `autowarm/screenrecords/farming/{platform}/...` | Ссылка в `publish_tasks.screen_record_url`. |
| XML-дампы | `/tmp/autowarm_ui_dumps` | Не связаны с `publish_tasks.id` жёстко (по таймстампу). |
| Медиа попытки | `/tmp/publish_media` | Аналогично — по таймстампу. |
| Telegram-бот | `@contenthunter_bugs_catcher_bot` (systemd, `~/contenthunter_bugs_bot`) | Работает. Умеет принимать баг-репорты, пушит в knowledge repo. Можно расширить на notification от триаж-агента. |
| Manual-retry marker | `events` с `manual_retry_after_deploy` | Уже используется при hotfix-деплоях. |

## 2. Чего не хватает (строим)

1. **Реестр кодов ошибок** — таблица `publish_error_codes (code, severity, retry_strategy, is_known, description)`. Категории из `events[].meta.category` маппятся на enum. Новый неизвестный код → `unknown` + сигнал.
2. **Fixture-бандл** — один `s3://…/fixtures/{task_id}.tar.gz`: события + XML-дампы + запись экрана + использованные медиа + снимок device state + `git_sha` publisher + `publisher_version`. Жёсткая связка по `task_id`.
3. **Testbench-оркестратор** — systemd/PM2-сервис на VPS, ставит попытки в `publish_tasks` с меткой `testbench=true`, каденс 20–40 мин на платформу, ротация content_type, seed-медиа.
4. **Триаж-триггер** — PostgreSQL `LISTEN/NOTIFY` на смену `status=failed` → spawn агента (с cap concurrency).
5. **Дедупликатор** — таблица `publish_investigations (error_code, opened_at, status, fixture_ids[], report_path)`. Новый failure со старым кодом = инкремент в активное расследование, агент не зовётся повторно.
6. **Агент-диагност** (Tier 2) — читает fixture, пишет `evidence/publish-triage/{code}-{date}.md` в формате `{симптом, гипотеза, scope фикса, предлагаемое изменение}`, нотификация в bugs-bot.
7. **Агент-автофикс** (Tier 3, узкие классы) — registry `publisher_fixes (code, fix_module, enabled, applied_at)`. Классы для auto-apply на старте:
   - **selector_drift**: координаты элемента в XML сдвинулись — обновить из свежего дампа.
   - **timeout_bump**: элемент появляется позже ожидаемого — +500ms к таймауту этого шага.
   - **retry_transient**: известная transient-ошибка (сетевой flap) — retry с backoff.
   НЕ авто-фиксим: `adb_push_timeout` (физический, см. память `project_adb_push_network_issue`), `ig_camera_open_failed` (повторяющаяся регрессия — эскалация), любой unknown код.
8. **Метрика успеха per code** — rolling 1h success rate per `error_code × platform`. CLI + микро-страница `delivery.contenthunter.ru/#publishing/testbench`.
9. **Auto-rollback** — после auto-fix окно 30–60 мин. Если success rate не вырос (или упал) → revert коммита + feature-flag disable + эскалация.
10. **Регресс-корпус** — `publisher_regression_corpus/` в autowarm: по 1 fixture на закрытый error_code. CI-gate прогоняет publisher против корпуса перед merge.

## 3. Архитектура — кто кого зовёт

```
[cron/systemd: testbench_orchestrator]
   │  (каждые 20–40 мин per IG/TT/YT)
   ▼
[publish_tasks INSERT row с testbench=true]
   │
   ▼
[publisher.py выполняет попытку на phone #19]
   │
   ├── success → UPDATE status=completed → 1h-metric пересчитывается
   │
   └── failure  → UPDATE status=failed
         │
         ├── [fixture_dumper hook] → собирает .tar.gz → S3
         │
         └── [PostgreSQL NOTIFY] → слушает [triage_dispatcher]
                  │
                  ├── известный code в активном расследовании? → INC counter, stop.
                  │
                  └── новый code / нет открытого расследования?
                        │
                        ├── [classifier] → error_code (или 'unknown')
                        │
                        ├── [agent_diagnose] → evidence/publish-triage/*.md → bugs-bot ping
                        │
                        └── код в auto-fix registry (selector/timeout/retry)?
                              │
                              └── [agent_apply] → commit в feature branch publisher
                                    → deploy через pm2 reload → 1h наблюдение
                                    → rollback если success_rate не вырос
```

## 4. T-breakdown (предварительно, уточняется в `/aif-plan full`)

### Фаза A — рига крутится (~1–2 дня работы)
- **T1.** Enum-таблица `publish_error_codes` + backfill 12 known категорий из существующих `events[].meta.category` (выборка за 30 дней).
- **T2.** Функция `dump_fixture(task_id) → s3_url` — хук на terminal-status в publisher, собирает все артефакты.
- **T3.** Testbench-оркестратор: новый сервис `autowarm_testbench.py` (systemd-unit), очередь на phone #19, каденс per platform, ротация content_type.
- **T4.** Telegram-нотификация на failure — расширение bugs-bot (или отдельный бот).

### Фаза B — агент-диагност (~2–3 дня сверху)
- **T5.** `publish_investigations` таблица + `triage_dispatcher.py` (LISTEN/NOTIFY слушатель с concurrency cap = 2).
- **T6.** `classifier.py` — маппинг `meta.category` → `error_code` (по regex + точному совпадению; unknown → 'unknown').
- **T7.** `agent_diagnose.py` — субагент, тянет fixture, пишет `evidence/publish-triage/{code}-{date}.md`. Контракт отчёта: `{симптом, гипотеза, scope, предлагаемое изменение, confidence 1-10}`.
- **T8.** Дедупликатор — при LISTEN смотрит `publish_investigations (status='open')`, решает spawn vs increment.

### Фаза C — агент-автофикс (~3–5 дней сверху)
- **T9.** Таблица `publisher_fixes` + runtime-loader feature-flag'ов в publisher (hot-reload через SIGHUP или poll).
- **T10.** Fix-module `selector_drift`: сравнивает XML в fixture с предыдущим известным → если элемент сдвинулся на >N px и только он → патч координат.
- **T11.** Fix-module `timeout_bump`: инкрементирует таймаут шага на 500ms, cap 3 последовательных bump.
- **T12.** Fix-module `retry_transient`: registry известных transient-ошибок с backoff.
- **T13.** `agent_apply.py` — создаёт feature branch `auto-fix/{code}-{date}`, коммит, push, `pm2 reload autowarm`, стартует окно наблюдения.
- **T14.** Auto-rollback: если 1h success rate не вырос на ≥10% или упал → `git revert` + `pm2 reload` + disable flag + нотификация.

### Фаза D — регресс-корпус + UI (~2 дня сверху)
- **T15.** `publisher_regression_corpus/` — структура `{error_code}/fixture.tar.gz + expected_outcome.json`. Каждый закрытый код → 1 fixture.
- **T16.** CI-gate: `pytest corpus/` в publisher — прогоняет XML-replay (без устройства) перед merge.
- **T17.** UI `delivery.contenthunter.ru/#publishing/testbench`: таблица `error_code × platform × 1h success rate` + drill-down (timeline + screen record + fixture download).

## 5. Scope и границы

**In scope:**
- Платформы IG/TT/YT (per memory `project_autowarm_scope`).
- Один жертвенный стенд: phone #19 / пак «Тестовый проект_19» / проект «Тестовый проект».
- Auto-fix только для `selector_drift`, `timeout_bump`, `retry_transient`.
- Feature-flag для ВСЕХ auto-fix'ов (единый kill-switch).

**Out of scope:**
- VK/FB/X (per memory).
- Авто-фикс физических багов (ADB packet loss → hop4 TimeWeb, user-owned).
- Авто-фикс бизнес-логики (расписание, лимиты аккаунтов).
- Параллельные стенды на нескольких устройствах (позже, если MVP взлетит).

## 6. Риски и контрмеры

| # | Риск | Контрмера |
|---|---|---|
| R1 | Выжиг тест-аккаунтов (шадоубан от частых публикаций) | Каденс 20–40 мин/платформа (не чаще), реалистичный контент, раз в сутки health-probe (ручная проверка через UI); при шадоубане — ротация в следующий аккаунт из пака, старый на cooldown. |
| R2 | Петли триаж-агента (один код = 100 агентов за час) | Дедуп через `publish_investigations`, concurrency cap = 2, budget cap по стоимости агент-ранов в сутки. |
| R3 | Auto-fix закрепляет неправильную гипотезу на сломанном фоне | Auto-rollback по метрике, только узкие классы, единый feature-flag kill-switch, агент не трогает unknown коды. |
| R4 | Физические баги не воспроизводятся на одном устройстве | Явный list «не авто-фиксим» в classifier; для этих кодов агент пишет только диагноз. |
| R5 | Agent loop «fix → same failure → new agent → same fix» | Invalidation: после 2 неудачных auto-apply одного кода — кластер замораживается, эскалация пользователю. |
| R6 | Объём S3 (GB/сутки записей) | TTL: fixture для failed — 14 дней, для success — 48ч; lifecycle rule в S3. |
| R7 | Агент правит код на главной ветке → ломает прод | Auto-fix только в feature branch → pm2 reload на autowarm — НЕ в delivery; merge в main только по ручному аппруву. Актуальный публикатор — тестбенч-копия в параллельной ветке? Уточнить в full plan. |

## 7. Открытые вопросы к пользователю (нужны ДО `/aif-plan full`)

1. **Ветка для auto-fix:** агент коммитит в `auto-fix/{code}-{date}` feature branch и сразу `pm2 reload` прод autowarm? Или у нас должна быть отдельная инстанция publisher для testbench (параллельный pm2-процесс на phone #19), а merge в прод — только ручной?
   *Рекомендую второй вариант — две инстанции publisher, тестбенч-копия правится агентом, прод копия правится только после ручного промоушена. Чуть дороже по инфре, но radically безопаснее.*

2. **Budget cap на агент-раны:** приемлемый потолок в $/сутки для агент-диагноста + агент-автофикса? Без cap петля может стать дорогой.

3. **Критерий «аккаунт умер»:** что считаем шадоубаном на тест-аккаунте? Пост не набирает X просмотров за Y часов? Или явный флаг от платформы? От ответа зависит health-probe.

4. **Notification channel:** расширяем существующий `@contenthunter_bugs_catcher_bot` новым типом сообщений `publish_triage`? Или отдельный канал/бот для триажа? Отдельный чище, но лишняя инфра.

5. **Telegram-нотификация тишины:** если агент успешно закрыл класс — молчим или шлём «✅ класс X закрыт»? Молчание экономит внимание, но теряется обратная связь.

6. **Дедлайн на Фазу A:** к какому числу вам нужно, чтобы тестбенч уже гнал попытки и копил fixtures (даже без агента)?

## 8. Next step

Пользователь отвечает на открытые вопросы (§7) → запускаем `/aif-plan full` → получаем конкретный PLAN.md с sub-task'ами и exact file paths → кодим по T1 → T17.

**Явно НЕ делаем до аппрува:** создание таблиц в проде, деплой сервисов, правку publisher'а. Бриф — только текст.

## 9. Ответы пользователя (2026-04-21)

1. **Две параллельные ветки publisher'а** — ОК. Branch `main` → prod PM2 app `autowarm`; branch `testbench` → PM2 app `autowarm-testbench`. Каждый инстанс фильтрует `publish_tasks` по `testbench` флагу; агент правит только `testbench`-ветку, merge в `main` — ручной.
2. **Budget на агент-раны** — безлимитный (публикация критична). Телеметрия расходов всё равно нужна — чтобы видеть «сколько жжём», но hard-cap не ставим.
3. **Критерий «аккаунт умер»** — явный баннер/диалог от соцсети о запрете публикации. Health-probe будет искать в XML-дампе характерные сигналы («Your account has been restricted», «Действие заблокировано», аналоги на TT/YT). Косвенные признаки (падение охвата) — не считаем.
4. **Notification bot** — существующий `@ffmpeg_notificator_gengo_bot`. Токен сохранён в `/home/claude-user/secrets/tg-notifier.env` (не в git, `chmod 600`). На VPS будет подгружен в `.env` autowarm-testbench при деплое T4. Расширяем этого бота, новый не создаём.
5. **Notification policy** — слать и падения, и успехи (закрытие класса). Пользователь хочет полную обратную связь.
6. **Дедлайн** — как можно быстрее. Фаза A (T1–T4) в приоритете, внутри дня-двух.

## 10. Уточнения плана после ответов

- **Архитектура двух инстансов** (ответ 1):
  - `publish_tasks` получает новую колонку `testbench BOOLEAN NOT NULL DEFAULT FALSE`.
  - Воркер-диспатчер (или существующий scheduler) читает с фильтром per-instance: prod `WHERE testbench = FALSE`, testbench `WHERE testbench = TRUE`.
  - `auto-fix` коммитит в ветку `testbench`, `pm2 restart autowarm-testbench`. Merge `testbench → main` — руками.
- **Health-probe класс** (ответ 3) — отдельный error_code `account_banned_by_platform` + detector в XML. Попадание в этот код = pause всего testbench-цикла, эскалация (а не просто замена аккаунта).
- **Telemetry для агент-расходов** (ответ 2) — таблица `agent_runs (started_at, agent, task_id, cost_usd, tokens_in, tokens_out)`. Нет hard-cap, но dashboard.
- **Success-notification** (ответ 5) — формат: «✅ класс `{code}` закрыт после `{N}` попыток, rolling success rate `{X}%` за последний час». Дедуп: одно сообщение на закрытие, не на каждую успешную попытку.
- **Скорость** (ответ 6) — параллелим T1 (DDL), T2 (fixture-dumper) и T3 (testbench-оркестратор) в Фазе A. T4 (Telegram) — зависит от T5 (триггер), но минимальный вариант «пинг при failure» можно сделать сразу после T3.

## 11. Security notes

- **Bot token**: хранится в `/home/claude-user/secrets/tg-notifier.env` (`chmod 600`, вне git). В plan-документах и коде — только ссылка на env var `TESTBENCH_NOTIFIER_BOT_TOKEN`, не литерал. При деплое на VPS: копия файла в `~/.openclaw/workspace-genri/autowarm-testbench/.env` (или аналог) с тем же chmod.
- **DB credentials** (`openclaw:openclaw123`) — уже в публичных файлах `publisher_legacy.py:43`; не в scope данного контура, не трогаем.
- **Агент-доступ к коммитам**: auto-fix коммитит от имени `claude-user@fra-1-vm-y49r`, только в ветку `testbench` (branch protection на `main` рекомендуется, но опционально).

## 12. Статус brief'а

**✅ Ответы получены, бриф заморожен. Переход к full plan**: `.ai-factory/plans/publish-testbench-agent-20260421.md` (создаётся этой же сессией).
