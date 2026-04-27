# Diagnosis: `/client/analytics` пустая — pipeline `factory_inst_reels_stats` мёртв с 2026-03-16

**Created:** 2026-04-27
**Branch (plan):** `feature/farming-testbench-phone171` (plan-only — никакого кода в этом плане)
**Target repos to investigate:**
- `/root/.openclaw/workspace-genri/validator/` (analytics endpoints — read-only)
- `/root/.openclaw/workspace-genri/autowarm/` (posts_parser.py, потенциальный owner pipeline — read-only)
**Reporter:** Danil → "нет данных в https://client.contenthunter.ru/client/analytics, возможно привязка через старую таблицу"
**Reanimation plan:** будет написан **после** этого диагностического плана, на основе D9 evidence-файла

---

## Settings

| | |
|---|---|
| Testing | n/a — это диагностический плана, никакого кода не пишем. Реанимационный план (после D9) → smoke + integration (по выбору пользователя) |
| Logging | n/a (read-only). Реанимационный план → verbose DEBUG (по выбору) |
| Docs | n/a в этом плане. Реанимационный план → обновить `validator/docs/` или `autowarm/README.md` (по выбору) |
| Roadmap | n/a — нет `.ai-factory/ROADMAP.md` |

---

## TL;DR — что мы УЖЕ знаем (до начала диагностики)

Эта секция фиксирует доказательства, собранные в /aif-plan-сессии 2026-04-27, чтобы каждая задача имела общий starting point и не повторяла работу.

### 1. Бэкенд `analytics.py` — НЕ ВИНОВАТ

Round 2 миграция account_packages → factory_pack_accounts (commit `7c03c58`, merge `c3467c0`, 2026-04-24) выполнена корректно:

```
$ grep -rn "account_packages" /root/.openclaw/workspace-genri/validator/backend/src/
→ только 3 строки-комментария ("после DROP 2026-04-22"). Ни одной реальной ссылки на таблицу.
$ git log --oneline -10 -- backend/src/routers/analytics.py
→ последнее изменение — 7c03c58, после этого тронуто только тестами.
```

Запросы джойнят через корректный путь:
```sql
factory_inst_reels_stats firs
  JOIN factory_inst_reels r        ON r.ig_media_id  = firs.ig_media_id
  JOIN factory_inst_accounts fia   ON fia.instagram_id = r.account_id
  JOIN factory_pack_accounts fpa   ON fpa.id = fia.pack_id
  WHERE fpa.project_id = :pid
    AND firs.collected_at >= CURRENT_DATE - :days
```

### 2. Фронтенд `AnalyticsPage.vue` — НЕ ВИНОВАТ

`frontend/src/pages/client/AnalyticsPage.vue:505,526` корректно вызывает `/analytics/client/summary` и `/analytics/client/top-posts` с заголовком `X-Project-Id: <int>` (через `projectStore.projectHeaders()` в `frontend/src/stores/project.ts:28`).

### 3. Виновата мёртвая data-pipeline

| Таблица | Последняя строка | Возраст | Кто пишет |
|---|---|---|---|
| `public.factory_inst_reels_stats.collected_at` (MAX) | **2026-03-16** | 41 день | `autowarm/posts_parser.py:135` (INSERT) |
| `public.factory_inst_reels.timestamp` (MAX) | **2026-03-15** | 42 дня | `autowarm/posts_parser.py:110` (INSERT) |
| `factory.factory_inst_reels.timestamp` (MAX) | **2026-03-02** | 56 дней | (схема factory — owner неизвестен, см. D5) |
| `account_audience_snapshots` | **0 строк** в принципе | вечность | (writer неизвестен, см. D5) |
| `factory_parsing_logs` | **таблица не существует** | n/a | посмотреть посто_парсер pisat sjuda бы | n/a (см. D7) |

**Дефолтное окно `analytics.py`** = `days=30`. Сегодня 2026-04-27 → последние данные `firs` 41 день назад → запрос всегда возвращает пустоту по умолчанию.

### 4. PM2 НЕ запускает posts_parser

```
$ sudo pm2 list
→ автоwarm, autowarm-farming-{orchestrator,testbench,triage}, autowarm-testbench,
  ch-auth, producer, validator. НЕТ posts_parser, НЕТ stats-collector, НЕТ analytics-sync.
```

### 5. Пользовательская гипотеза («старая неактуальная таблица»)

Частично верна, но смещена: **таблицы правильные, данные в них устарели.** Не нужна замена reference, нужна реанимация писателя.

---

## Tasks

### Phase D — Diagnostic (read-only)

Все задачи в этом плане **диагностические**. Никаких изменений кода / БД / PM2 не делаем — это сбор доказательств для следующего (реанимационного) плана.

- [x] **D1. Воспроизвести пустой /client/analytics на проде**
  - Открыть `https://client.contenthunter.ru/client/analytics` под реальным клиентским логином (или через project-switcher как admin).
  - DevTools → Network: статус, тело, заголовки запросов `/api/analytics/client/summary`, `/api/analytics/client/top-posts`, `/api/analytics/client/publications`.
  - Скриншот пустой страницы.
  - Хотя бы 2 проекта: один с пакетами (например `project_id=9 Relisme — 14 packs / 57 accounts`), один без (например `project_id=85 ClickPay — 0 packs`).
  - Файл: `.ai-factory/evidence/analytics-empty-pipeline-diagnosis-20260427.md` (создать раздел "1. Симптом").
  - Logging: read-only.
  - Blocks: D2, D9.

- [x] **D2. Карта источников данных каждого analytics-эндпоинта**
  - Прочитать `backend/src/routers/analytics.py` целиком (591 строка).
  - Для каждого роутера-функции выписать таблицы + `SELECT/JOIN` файлы с line-numbers.
  - Эндпоинты: `/audience/latest` (l. 25), `/client/summary` (l. ~195), `/client/top-posts` (l. ~440), `/client/publications` (l. ~480).
  - Для каждой таблицы выполнить freshness-SQL:
    ```sql
    -- через psql -U openclaw -d openclaw на хосте localhost:5432, password в memory
    SELECT MAX(<ts_col>), MIN(<ts_col>), COUNT(*) FROM <table>;
    ```
  - Уже известны (см. TL;DR §3): `factory_inst_reels_stats`, `public.factory_inst_reels`, `factory.factory_inst_reels`, `account_audience_snapshots`. Дополнительно проверить: `factory_inst_accounts`, `factory_pack_accounts`, `validator_projects`, `factory_inst_publications` (если ссылается).
  - Deliverable: freshness-матрица таблицей в evidence (раздел "3. Freshness matrix").
  - Logging: read-only SQL.
  - Blocked by: D1.

- [x] **D3. Археология — когда/почему остановился posts_parser.py**
  - `cd /root/.openclaw/workspace-genri/autowarm && git log --all --oneline -- posts_parser.py` — даты последних правок.
  - Поискать признаки прошлых запусков:
    - `~/.bash_history` и (если доступно) `/root/.bash_history`.
    - `~/.pm2/dump.pm2*` бэкапы (существовала ли когда-нибудь PM2-запись `posts_parser`).
    - Логи cron в `/var/log/syslog*` (best-effort, sudo NOPASSWD не покрывает grep по системным логам — пробовать pasta-mode и fallback'ом просить пользователя).
  - Прочитать `posts_parser.py` целиком: env-зависимости (`APIFY_API_KEY`, `YOUTUBE_API_KEY`, `VK_TOKEN`), как он узнаёт «кого парсить» (без аргументов `python3 posts_parser.py` — где список аккаунтов?), self-loop vs scheduler.
  - Подтвердить: `factory_parsing_logs` отсутствует в БД (см. TL;DR §3) → `posts_parser.py:174` всегда падает на `log_result`.
  - Deliverable: timeline в evidence "4. Pipeline death timeline".
  - Logging: read-only.
  - Blocks: D9.

- [x] **D4. Проверить upstream'ы — Apify / YouTube API / VK живы?**
  - Прочитать ключи из `/root/.openclaw/workspace-genri/autowarm/.env`.
  - Один Apify run-sync на IG-аккаунт из `factory_inst_accounts.username` для `project_id=9` (Relisme, 57 аккаунтов гарантированно есть).
  - Один YouTube API call для канала из тех же 57.
  - VK — по наличию токена.
  - Зафиксировать: HTTP-код, размер ответа, sample item.
  - **НЕ ПИСАТЬ В БД.** Цель — «живой ли источник?»
  - Сверить с memory `project_id_parser_ig_broken.md` (Apify 403 + IG mobile 429): Apify Instagram-актор сейчас живой/мёртвый? Если мёртвый — это major блокер для реанимационного плана.
  - Deliverable: раздел "5. Upstream health" в evidence.
  - Logging: stdout HTTP-ответы.
  - Blocks: D9.

- [x] **D5. Cross-repo / cross-schema audit — кто-нибудь ещё пишет в эти таблицы?**
  - Объяснить расхождение: `public.factory_inst_reels` (text-typed) последняя 2026-03-15 vs `factory.factory_inst_reels` (proper-typed) последняя 2026-03-02. Похоже на ETL-снапшот → grep по всему `workspace-genri/` для `INSERT INTO factory.factory_inst_reels` и `INSERT INTO public.factory_inst_reels`.
  - Аналогично — кто пишет `account_audience_snapshots`, `factory_inst_reels_stats`, `factory_accounts_fans`.
  - Грепы: validator, autowarm, producer, producer-copilot, ch-auth, kira; SQL и Python.
  - Бонус: проверить, есть ли *новая* таблица (созданная после 2026-03-16) с похожими данными (паттерн имени `*reels*`, `*stat*`, `*publication*`, `*media*`) — возможно, данные мигрировали в новый источник, а analytics остался на старом.
  - `farming-testbench` / `autowarm-testbench` — пишут ли что-то analytics-релевантное?
  - Deliverable: раздел "6. Cross-repo writers map" в evidence.
  - Logging: read-only.
  - Blocks: D9.

- [x] **D6. Quantify — какие проекты получили бы данные, если pipeline ожил**
  - Для каждого из 38 проектов с `factory_pack_accounts > 0`:
    - кол-во аккаунтов
    - кол-во аккаунтов с `instagram_id IS NOT NULL` (memory: id_parser IG broken — 2026-04-23 → новые аккаунты NULL)
    - есть ли вообще исторические рилы в `public.factory_inst_reels` за этот project
  - Сегментировать: `would-resume-today` / `still-empty-NULL-instagram_id` / `historical-only-no-new-content`.
  - Это критично для решения «стоит ли реанимация на сегодняшний роестр клиентов».
  - SQL one-liners + результат-таблица в evidence (раздел "7. Per-project impact").
  - Logging: read-only.
  - Blocked by: D2.
  - Blocks: D9.

- [x] **D7. `factory_parsing_logs` — silent-crash hypothesis**
  - Подтвердить: `SELECT table_schema, table_name FROM information_schema.tables WHERE table_name='factory_parsing_logs'` → пусто.
  - Прочитать `posts_parser.py` целиком: где вызывается `log_result()` (строка 172), внутри ли try/except, оборачиваются ли все INSERT'ы в одну транзакцию или per-account commit.
  - Это определяет: «парсер падает в самом начале и НИЧЕГО не пишет» vs «парсер пишет reels/stats и крашится только на лог-строке (но коммит уже прошёл)».
  - Если за-один-раз-всё-в-одной-транзакции → 0 inserts при отсутствии log-таблицы → объясняет 41-дневный gap БЕЗ необходимости предположения «парсер не запускался».
  - Если per-account commit → значит парсер реально не запускался (т.к. иначе reels/stats были бы свежие, а лог-строки — пропущены).
  - Deliverable: однозначный вывод в evidence "4. Pipeline death timeline" → "actual root cause: <not scheduled> или <silent crash>".
  - Logging: код-ревью + 1-2 SQL.
  - Blocks: D9.

- [x] **D8. Фронтенд UX — «пусто» vs «ошибка»**
  - `AnalyticsPage.vue`: при `summary={0,0,...}` UI показывает «Нет данных» или просто пустые графики? `BrandPage.vue`, `PublicationsPage.vue` (если делят источник).
  - Проверить, не глотает ли Vue 4xx/5xx ответ молча.
  - 5-bullet summary в evidence "8. Frontend behavior".
  - Logging: none.
  - Blocks: D9.

### Phase E — Recommendations (на основе D1-D8)

- [x] **D9. Сводный evidence-файл + рекомендации для реанимационного плана**
  - Файл: `.ai-factory/evidence/analytics-empty-pipeline-diagnosis-20260427.md`.
  - Структура:
    1. Симптом (D1)
    2. Невиновность кода (analytics.py post-2026-04-24 чист)
    3. Freshness-матрица (D2)
    4. Pipeline death timeline (D3 + D7)
    5. Upstream health (D4)
    6. Cross-repo writers (D5)
    7. Per-project impact (D6)
    8. Frontend behavior (D8)
    9. **Recommendations** — варианты реанимационного плана, ранжированные по effort×impact:
       - **A.** Полная реанимация posts_parser → PM2 cron + создать `factory_parsing_logs` + бэкфилл за 41 день. Effort: 2-3 дня; impact: highest (analytics реально работает).
       - **B.** Только staleness-banner на /client/analytics: «Данные устарели на N дней». Effort: <1 день; impact: косметика, корень не лечится.
       - **C.** Если D5 нашёл другой свежий источник — переключить analytics.py на него. Effort: TBD; impact: возможно highest без реанимации parsing.
       - **D.** Defer всего analytics-блока до фикса `id_parser.py IG broken` (memory). Effort: 0 (только коммуникация клиентам); impact: −. Только если D6 покажет, что у большинства проектов всё равно instagram_id NULL.
    10. Open questions для пользователя ДО написания реанимационного плана.
  - Logging: только сам файл.
  - Blocked by: D1, D2, D3, D4, D5, D6, D7, D8.

---

## Commit Plan

- **Commit 1** (после D9, в agent-workspace `feature/farming-testbench-phone171`):
  ```
  docs(plan+evidence): analytics empty diagnosis — pipeline dead since 2026-03-16

  Plan: .ai-factory/plans/analytics-empty-pipeline-diagnosis-20260427.md
  Evidence: .ai-factory/evidence/analytics-empty-pipeline-diagnosis-20260427.md
  Backend SQL clean (Round 2 was correct). Root cause: posts_parser.py
  not scheduled / writes to non-existent factory_parsing_logs table.
  Reanimation plan to follow.
  ```

Атомарный коммит: план + evidence + memory-апдейт идут вместе. Никаких изменений в `/root/.openclaw/workspace-genri/*` в этом плане.

---

## Risks & notes

- **Read-only гарантия:** ни одна задача в этом плане не модифицирует код, БД, PM2, cron. Если в D4 при тестировании Apify захочется записать результат «для проверки» — НЕ записывать. Цель плана — собрать факты, не лечить.
- **Memory `feedback_user_diagnosis_is_signal.md`:** пользовательская гипотеза «старая таблица» — сигнал, не диагноз. Реальная причина — мёртвый writer, а не неправильная reference. Verify both independently in D2/D3/D7.
- **Memory `feedback_execution_judgment.md`:** scope диагностики (read-only) не имеет рисков — выполнять автономно. AskUserQuestion после D9 для выбора варианта (A/B/C/D) — там уже substantive решение.
- **Memory `id_parser.py IG broken since 2026-04-23`:** D6 должен явно сегментировать проекты, у которых `instagram_id IS NULL` (новые после 2026-04-23) — для них реанимация posts_parser НЕ поможет, нужна сначала починка id_parser.
- **Cross-repo grep granularity** (memory `feedback_cross_repo_schema_changes.md`): D5 grep'ает БЕЗ `| head` и аудитит каждый hit — это рекомендация из инцидента 2026-04-24.
- **`factory.factory_inst_reels` (другая схема) — открытый вопрос:** может оказаться что её пишет какой-то ETL за пределами `workspace-genri/`. D5 должен явно зафиксировать «не нашли writer» если так.
- **AnalyticsPage.vue admin project-switcher** (commit `860f9d4`): D1 удобнее воспроизводить под admin-логином с переключением проектов, без необходимости создавать второго клиентского пользователя.
- **PM2 dump path drift** (memory `feedback_pm2_dump_path_drift.md`): D3, при чтении `~/.pm2/dump.pm2*` бэкапов, помнить что paths могли дрифтить — надо смотреть исторические записи cwd.

---

## Links

- Round 2 plan (предыдущая итерация — backend SQL fix): `.ai-factory/plans/validator-schemes-account-packages-20260424.md`
- Evidence соседнего фикса: `.ai-factory/evidence/validator-schemes-account-packages-fix-20260424.md`
- Памяти, релевантные плану:
  - `project_account_packages_deprecation.md` — DROP'нута 2026-04-22, factory = single source
  - `feedback_cross_repo_schema_changes.md` — grep cross-repo
  - `project_id_parser_ig_broken.md` — Apify 403 + IG mobile 429 с 2026-04-23 (D4 / D6 критично)
  - `feedback_user_diagnosis_is_signal.md` — гипотеза vs факт
  - `feedback_execution_judgment.md` — read-only диагностика без AskUserQuestion на каждый шаг
  - `feedback_deploy_scope_constraints.md` — реанимационный план должен использовать PM2, не systemd
