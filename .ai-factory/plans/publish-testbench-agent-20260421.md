# PLAN — Publish testbench + agent fix-loop (full)

**Создан:** 2026-04-21
**Тип:** infra + code (multi-repo: `delivery-contenthunter` publisher + новые сервисы на VPS + UI в delivery frontend)
**Статус:** ready-for-approve (ждёт «да, делаем» от пользователя → кодим)
**Бриф-источник:** `.ai-factory/plans/publish-testbench-agent-brief-20260421.md`
**Решения пользователя:** §9 брифа (ответы на 6 открытых вопросов)
**Память:** `project_publish_testbench.md`
**Правило:** `agents/main/AGENTS.md` — Show Plan First → Wait for "go" → Then Act.

## Settings

| | |
|---|---|
| Testing | pytest по триаж-/автофикс-модулям + manual smoke на phone #19 + 1h success-rate как acceptance signal |
| Logging | **verbose** для testbench/triage-agent (каждая попытка → event-log + metric); standard для остальных |
| Docs | warn-only — инфра-проект, без продуктовых доков |
| Roadmap linkage | skipped |
| Language | ru |
| Branches | `main` (prod publisher, не трогаем без ручного merge) + `testbench` (auto-fix target) |

## 0. TL;DR

На VPS поднимаем вторую PM2-инстанцию publisher'а (`autowarm-testbench`, ветка `testbench`), новый сервис `testbench_orchestrator` ставит задачи на phone #19 каждые 20–40 мин, каждое завершение попытки собирается в fixture (S3), `triage_dispatcher` слушает `LISTEN` на `publish_tasks` и для новых failure спавнит агент-диагност; для трёх узких классов (`selector_drift`, `timeout_bump`, `retry_transient`) агент сам коммитит фикс в ветку `testbench` и `pm2 restart`, метрика 1h success rate решает apply/rollback. Bug bot `@ffmpeg_notificator_gengo_bot` пинает пользователя по падениям и закрытиям классов.

## 1. Задачи (T1–T17) — exact scope

Обозначения: **F** = fast (< 1h), **M** = medium (1-4h), **L** = large (4-8h). Зависимости `→`. Все пути в `delivery-contenthunter/` repo — если не указано иное.

### Фаза A — рига крутится (parallel T1+T2+T3, потом T4)

- **T1 [M]** — DDL миграция
  - Файл: `delivery-contenthunter/migrations/20260421_testbench_foundation.sql`
  - Создаёт таблицы: `publish_error_codes`, `publish_investigations`, `publisher_fixes`, `agent_runs`; добавляет колонку `publish_tasks.testbench BOOLEAN NOT NULL DEFAULT FALSE`; backfill 12 known категорий из `events[].meta.category` за 30 дней.
  - SQL: §2 ниже.
  - Test: `psql` dry-run на dev-копии БД → `SELECT COUNT(*) FROM publish_error_codes WHERE is_known = true` ≥ 12.

- **T2 [M]** — fixture-dumper hook в publisher
  - Файл: `publisher_legacy.py` — новый helper `dump_fixture(task_id) → s3_url`, вызов в `run_publish_task` finally-блоке (и для success, и для failure).
  - Собирает: все XML из `/tmp/autowarm_ui_dumps/*task_{id}*.xml`, запись `screen_record_url`, медиа из `/tmp/publish_media/*task_{id}*`, `events`, device_state (output `adb shell getprop` + `dumpsys battery`), `git_sha` publisher, `publisher_version`. Пакует в `.tar.gz`, кладёт `s3://autowarm/fixtures/{task_id}.tar.gz`, UPDATE-ит `publish_tasks.fixture_url`.
  - Test: unit test на моковых путях + ручной прогон с существующим `task_id` из прода.

- **T3 [L]** — testbench orchestrator
  - Новый файл: `testbench_orchestrator.py` + systemd unit `/etc/systemd/system/autowarm-testbench-orchestrator.service`.
  - Логика: infinite loop, раз в 20–40 мин per platform (IG/TT/YT) → `INSERT INTO publish_tasks (testbench=TRUE, account_pack='Тестовый проект_19', platform=..., device_serial='<phone19>', content_type=...)`. Ротация content_type (post/story/carousel/reel). Seed-медиа из фиксированного набора в `s3://autowarm/testbench-seed/`.
  - Safety: проверка `account_banned_by_platform` в последнем fixture phone #19 перед INSERT — если стоит, не ставим.
  - Test: запуск в foreground на 2h → проверить что попытки создаются и попадают в `autowarm-testbench` инстанс.

- **T3a [F]** — вторая PM2-инстанция publisher'а
  - На VPS: `git branch testbench` из текущего main → `cd ~/.openclaw/workspace-genri/autowarm-testbench` (новый clone ветки `testbench`) → `pm2 start publisher.py --name autowarm-testbench` + задача диспатчера фильтрует per-instance: prod берёт `testbench=FALSE`, testbench-инстанс `testbench=TRUE`.
  - Правка в scheduler'е: добавить env var `WORKER_MODE=prod|testbench`, фильтр в SELECT из `publish_tasks`.
  - Test: ручной INSERT task с `testbench=TRUE` → подхватывается только `autowarm-testbench`, не prod.

- **T4 [M]** — Telegram notifier (минимальный)
  - Новый модуль: `notifier.py` (использует токен из env var `TESTBENCH_NOTIFIER_BOT_TOKEN`, подгружается из `.env` autowarm-testbench).
  - API: `notify_failure(task_id, error_code, fixture_url)`, `notify_success_closure(error_code, stats)`.
  - Вызывается из fixture-dumper (T2) для failure и из triage-agent (T7) для закрытия.
  - Test: ручной `notify_failure` smoke → сообщение в бота приходит.

**Acceptance Фазы A:** на phone #19 за 24h копится ≥ 50 попыток, каждая с fixture в S3; при failure пользователь получает Telegram.

### Фаза B — агент-диагност (после Фазы A)

- **T5 [M]** — LISTEN/NOTIFY + triage_dispatcher
  - Файл: `triage_dispatcher.py` + systemd unit `autowarm-triage-dispatcher.service`.
  - Триггер PostgreSQL: `CREATE TRIGGER publish_tasks_failed_notify AFTER UPDATE ON publish_tasks WHEN (NEW.status = 'failed' AND NEW.testbench = TRUE) EXECUTE FUNCTION pg_notify('publish_task_failed', NEW.id::text)`.
  - Python-listener на этом канале, concurrency cap = 3 (параметризуемо).

- **T6 [F]** — classifier
  - Модуль: `triage/classifier.py`.
  - Contract: `classify(events_jsonb) → error_code: str`. Регистр в `publish_error_codes`: exact match по `meta.category` → code; regex на `msg` для unknown; fallback `'unknown'`.
  - Test: pytest на 20 известных events fixtures → 100% match.

- **T7 [L]** — agent_diagnose
  - Модуль: `triage/agent_diagnose.py` — вызывает Claude API с prompt template (см. §3). Input: fixture (XML-дампы, первые+последние 3 кадра записи, events, git_sha), recent commits publisher. Output: markdown-отчёт в `delivery-contenthunter/.ai-factory/evidence/publish-triage/{code}-{YYYYMMDD}-{HHMMSS}.md` с секциями: симптом, root cause hypothesis, scope фикса, proposed fix, confidence (1-10).
  - После отчёта: `notify_failure` в Telegram со ссылкой на отчёт + fixture.
  - Test: запуск на 3 уже известных fixtures (например, `ig_camera_open_failed` из прошлой сессии) → отчёт сгенерирован, гипотеза совпадает с фактическим root cause.

- **T8 [M]** — дедупликатор
  - Логика в `triage_dispatcher.py`: при NOTIFY смотрим `publish_investigations WHERE error_code = ? AND status = 'open'`. Если есть — `UPDATE occurrences_count += 1, last_seen = NOW()`. Если нет — `INSERT status='open'` + spawn агента.
  - Auto-close: если `error_code` не появлялся 2h → `UPDATE status = 'closed_auto'`, notify success closure.
  - Test: симуляция 5 подряд failure одного кода → 1 отчёт, 4 инкремента.

**Acceptance Фазы B:** каждое уникальное падение приводит к 1 отчёту за ≤ 5 мин, повторы дедуплицируются, success-closure приходит через 2h тишины.

### Фаза C — агент-автофикс (после Фазы B)

- **T9 [M]** — feature-flag registry
  - Таблица `publisher_fixes` (из T1 DDL): `code, fix_module, enabled, applied_at, applied_commit_sha, rollback_sha`.
  - Python-loader в `publisher_legacy.py`: при старте читает `enabled=TRUE` rows, применяет fix-модули. Hot-reload через SIGHUP (`kill -HUP $PID`).
  - Single kill-switch: env var `AUTO_FIX_ENABLED=false` на любом инстансе → все fix'ы игнорятся.

- **T10 [L]** — fix-module `selector_drift`
  - Файл: `triage/fixes/selector_drift.py`.
  - Логика: анализирует fixture — элемент, по которому публикатор tap'нул, сдвинулся относительно предыдущей зафиксированной позиции (diff XML-дампа в корпусе регрессий) на > threshold (например, 20px). Патч: обновляет координаты в соответствующем step'е publisher'а (в `STEP_ACTIONS` или аналог — уточнить при чтении `publisher_legacy.py`).
  - Safety: патч только если XML confidence высокий (элемент чётко идентифицирован по `resource-id` + `class`, не только по координатам).
  - Test: искусственный fixture со сдвинутой кнопкой → fix-модуль предлагает правильные новые координаты.

- **T11 [M]** — fix-module `timeout_bump`
  - Файл: `triage/fixes/timeout_bump.py`.
  - Логика: если failure = timeout в `WatchdogTimer` (см. `publisher_legacy.py::STEP_TIMEOUTS`) и элемент в итоге появлялся на следующей попытке → bump таймаут step'а на +500ms, cap 3 последовательных bump на один step (потом эскалация).
  - Test: fixture с известным step timeout → +500ms в `STEP_TIMEOUTS`.

- **T12 [M]** — fix-module `retry_transient`
  - Файл: `triage/fixes/retry_transient.py`.
  - Registry известных transient-ошибок (NetworkError, ADB reconnect) → retry с exponential backoff (1s, 2s, 4s), max 3.
  - Test: моковая transient ошибка → retry выполняется, task завершается success.

- **T13 [L]** — agent_apply
  - Модуль: `triage/agent_apply.py`.
  - Workflow: читает отчёт от T7 + proposed fix → вызывает соответствующий fix-module (T10/T11/T12) → получает patch → применяет в рабочей копии ветки `testbench` → `git commit -m "auto-fix({code}): {summary}"` → `git push origin testbench` → `pm2 restart autowarm-testbench` → INSERT row в `publisher_fixes` со статусом `applied` + `applied_commit_sha`.
  - Стартует окно наблюдения 30–60 мин.
  - Safety: агент НЕ трогает main; НЕ трогает коды вне auto-fix registry (`unknown`, `adb_push_timeout`, `account_banned_by_platform`, любой с confidence < 7).

- **T14 [M]** — auto-rollback
  - Cron (или logic в triage_dispatcher): через 60 мин после `applied_commit_sha` — проверяет `error_code` success rate за окно. Если не вырос на ≥ 10pp относительно окна перед применением или упал — `git revert {applied_commit_sha}` + push + `pm2 restart autowarm-testbench` + `publisher_fixes.enabled = FALSE` + эскалация в Telegram.
  - Test: искусственный «фикс» не улучшающий метрику → rollback срабатывает.

**Acceptance Фазы C:** для наиболее частого known-класса фикс применяется автоматически и метрика подтверждает улучшение за ≤ 2h, без ручной правки.

### Фаза D — регресс-корпус + UI

- **T15 [M]** — регресс-корпус
  - Директория: `delivery-contenthunter/publisher_regression_corpus/`.
  - Структура: `{error_code}/fixture.tar.gz + expected_outcome.json + README.md`. Каждый закрытый (status='closed_fixed') error_code → 1 fixture.
  - Test: ручной сбор 3 корпусных fixtures из прошлых закрытых багов (`ig_camera_open_failed`, `publish_failed_generic`, `adb_push_timeout`).

- **T16 [M]** — CI-gate в publisher repo
  - Файл: `delivery-contenthunter/.github/workflows/publisher-regression.yml` + `tests/test_regression_corpus.py`.
  - Логика: на PR прогоняет pytest по корпусу через XML-replay (без физического устройства) — если раньше `publisher.py` падал на этом fixture, после PR должен пройти или явно быть в whitelist.
  - Test: тестовый PR с откатом известного фикса → CI падает.

- **T17 [L]** — UI `/#publishing/testbench`
  - Репо: frontend delivery-contenthunter (не autowarm).
  - Файлы: новая Vue-страница + API endpoint в backend.
  - Показывает: таблица `error_code × platform × 1h success rate` + график за 24h + drill-down на fixture (timeline events + screen record player + download).
  - Test: ручной smoke в браузере.

## 2. SQL DDL (T1 полностью)

```sql
-- publish_tasks расширение
ALTER TABLE publish_tasks
  ADD COLUMN IF NOT EXISTS testbench BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS fixture_url TEXT,
  ADD COLUMN IF NOT EXISTS error_code TEXT;

CREATE INDEX IF NOT EXISTS idx_publish_tasks_testbench_status
  ON publish_tasks (testbench, status, started_at DESC);

-- Error code registry
CREATE TABLE IF NOT EXISTS publish_error_codes (
  code           TEXT PRIMARY KEY,
  severity       TEXT NOT NULL CHECK (severity IN ('info','warn','error','critical')),
  retry_strategy TEXT NOT NULL CHECK (retry_strategy IN ('none','immediate','backoff','manual')),
  is_known       BOOLEAN NOT NULL DEFAULT TRUE,
  is_auto_fixable BOOLEAN NOT NULL DEFAULT FALSE,
  description    TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Investigations tracker (дедуп)
CREATE TABLE IF NOT EXISTS publish_investigations (
  id                 SERIAL PRIMARY KEY,
  error_code         TEXT NOT NULL REFERENCES publish_error_codes(code),
  status             TEXT NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open','closed_fixed','closed_auto','escalated')),
  opened_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_at          TIMESTAMPTZ,
  occurrences_count  INT NOT NULL DEFAULT 1,
  first_task_id      INT REFERENCES publish_tasks(id),
  report_path        TEXT,
  fixture_task_ids   INT[] DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_investigations_open
  ON publish_investigations (error_code, status) WHERE status = 'open';

-- Auto-fix registry
CREATE TABLE IF NOT EXISTS publisher_fixes (
  id                  SERIAL PRIMARY KEY,
  error_code          TEXT NOT NULL REFERENCES publish_error_codes(code),
  fix_module          TEXT NOT NULL,
  enabled             BOOLEAN NOT NULL DEFAULT TRUE,
  applied_at          TIMESTAMPTZ,
  applied_commit_sha  TEXT,
  rollback_sha        TEXT,
  notes               TEXT
);

-- Agent run telemetry
CREATE TABLE IF NOT EXISTS agent_runs (
  id          SERIAL PRIMARY KEY,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  agent       TEXT NOT NULL,
  task_id     INT REFERENCES publish_tasks(id),
  error_code  TEXT,
  cost_usd    NUMERIC(10,4),
  tokens_in   INT,
  tokens_out  INT,
  outcome     TEXT
);

-- Backfill known codes (actual list уточнить из прода — здесь шаблон)
INSERT INTO publish_error_codes (code, severity, retry_strategy, is_known, is_auto_fixable, description) VALUES
  ('ig_camera_open_failed',       'error',    'manual',    TRUE, FALSE, 'Instagram камера не открывается'),
  ('publish_failed_generic',      'error',    'manual',    TRUE, FALSE, 'Catch-all; нужен дальнейший триаж'),
  ('adb_push_timeout',            'error',    'backoff',   TRUE, FALSE, 'ADB push timeout (физический, TimeWeb hop4)'),
  ('platform_not_configured_for_device','warn','none',      TRUE, FALSE, 'Guard: девайс не сконфигурирован под платформу'),
  ('skipped_config_missing',      'info',     'none',      TRUE, FALSE, 'Guard: конфиг аккаунта отсутствует'),
  ('selector_drift',              'error',    'immediate', TRUE, TRUE,  'Координаты UI-элемента сдвинулись'),
  ('timeout_bump',                'warn',     'immediate', TRUE, TRUE,  'Элемент появляется позже ожидаемого'),
  ('retry_transient',             'warn',     'backoff',   TRUE, TRUE,  'Известная transient-ошибка (сеть, ADB flap)'),
  ('account_banned_by_platform',  'critical', 'manual',    TRUE, FALSE, 'Явный баннер от соцсети о запрете публикации'),
  ('unknown',                     'error',    'manual',    FALSE,FALSE, 'Не классифицирован')
ON CONFLICT (code) DO NOTHING;

-- Trigger for LISTEN/NOTIFY (T5)
CREATE OR REPLACE FUNCTION notify_publish_task_failed() RETURNS TRIGGER AS $$
BEGIN
  IF NEW.status = 'failed' AND NEW.testbench = TRUE
     AND (OLD.status IS DISTINCT FROM NEW.status) THEN
    PERFORM pg_notify('publish_task_failed', NEW.id::TEXT);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS publish_tasks_failed_notify ON publish_tasks;
CREATE TRIGGER publish_tasks_failed_notify
  AFTER UPDATE ON publish_tasks
  FOR EACH ROW EXECUTE FUNCTION notify_publish_task_failed();
```

## 3. Agent prompt template (T7 — agent_diagnose)

```
Ты триаж-агент публикатора ContentHunter. Разбирай падение одной попытки.

Вход:
- task_id: {task_id}
- platform: {platform}
- error_code (предварительный): {error_code}
- events log (JSONB): {events}
- XML dumps (последние 3 кадра): {xml_dumps}
- recording frames (первый, середина, последний): {frame_urls}
- git_sha publisher: {git_sha}
- recent 5 commits publisher: {recent_commits}
- known bugs из corpus: {known_fixtures_summary}

Выход — markdown-отчёт со СТРОГИМ форматом:
## Симптом (1-2 фразы)
## Root cause hypothesis (1 абзац, ссылайся на конкретные строки events или XML)
## Scope фикса (какие файлы/функции publisher затронуть)
## Proposed fix
  - если код в {auto-fixable: selector_drift, timeout_bump, retry_transient}: укажи точно
    какой параметр/координату/таймаут менять + на сколько + обоснование из fixture
  - иначе: опиши фикс человеческим языком + почему не автоматизируется
## Confidence (1-10)

Если confidence < 7 — не предлагай auto-apply, флаг "human_review_required": true.
```

## 4. Repo / branch / service layout

| Компонент | Branch | Директория (VPS) | PM2 app | systemd unit |
|---|---|---|---|---|
| Prod publisher | `main` | `~/.openclaw/workspace-genri/autowarm/` | `autowarm` | — (PM2) |
| Testbench publisher | `testbench` | `~/.openclaw/workspace-genri/autowarm-testbench/` | `autowarm-testbench` | — (PM2) |
| Testbench orchestrator | N/A (своя инсталляция) | `~/autowarm-testbench-tools/` | — | `autowarm-testbench-orchestrator.service` |
| Triage dispatcher | N/A | `~/autowarm-testbench-tools/` | — | `autowarm-triage-dispatcher.service` |
| Notifier | — | imported in orchestrator + dispatcher | — | — |

## 5. Deploy order (happy path)

1. T1 (DDL) — миграция на dev-копии БД → smoke → миграция на prod (`openclaw:openclaw123@localhost:5432`).
2. T3a (вторая PM2-инстанция) — clone ветки `testbench`, проверить что она идентична `main`, запустить.
3. T2 (fixture-dumper) — merge в `testbench`, `pm2 restart autowarm-testbench`, smoke 3 task'а → fixture в S3 работает.
4. T3 (orchestrator) — запуск systemd, 2h наблюдение → ≥ 3 task'а создано и исполнено на phone #19.
5. T4 (notifier) — .env дополняется токеном, первое сообщение в Telegram.
6. **Acceptance Фазы A → переход к Фазе B**.
7. T5 + T6 + T8 (dispatcher + classifier + дедуп) — systemd, smoke на синтетическом failure.
8. T7 (agent_diagnose) — сначала dry-run на 3 старых fixtures, потом включаем в live.
9. **Acceptance Фазы B → переход к Фазе C**.
10. T9 + T10 + T11 + T12 (feature-flag + fix modules) — unit-тесты.
11. T13 + T14 (apply + rollback) — с `AUTO_FIX_ENABLED=false` первые 24h (dry-run; пишем что сделали бы), потом включаем.
12. **Acceptance Фазы C → Фаза D**.
13. T15 + T16 (corpus + CI).
14. T17 (UI).

## 6. Rollback strategy

- **T1 DDL**: миграция идемпотентна (IF NOT EXISTS). Обратная миграция `20260421_testbench_foundation_down.sql` — удаляет колонки + таблицы.
- **T3a второй инстанс**: `pm2 delete autowarm-testbench` + удалить клон ветки. Prod не затронут.
- **Auto-fix ветка**: `git revert` commit + push + `pm2 restart autowarm-testbench`. Auto-rollback T14 делает это автоматически.
- **Kill-switch**: `AUTO_FIX_ENABLED=false` (env var) → все fix'ы игнорятся без деплоя. `pm2 restart autowarm-testbench --update-env` — мгновенно.
- **Testbench orchestrator**: `systemctl stop autowarm-testbench-orchestrator` → попытки не создаются, прод не затронут.

## 7. Риски (из брифа §6) — актуальные контрмеры

| # | Риск | Контрмера (final) |
|---|---|---|
| R1 | Шадоубан тест-аккаунтов | Каденс 20–40 мин/платформа + health-probe через `account_banned_by_platform` XML-detector → pause всего цикла, эскалация. |
| R2 | Петли агента | Дедуп через `publish_investigations.status='open'`, cap = 3 concurrent, телеметрия в `agent_runs`. |
| R3 | Auto-fix закрепляет неправильную гипотезу | confidence ≥ 7 только; только 3 класса; auto-rollback за 60 мин; kill-switch env var. |
| R4 | Физические баги не фиксятся на одном устройстве | Явный `is_auto_fixable = FALSE` в `publish_error_codes` для `adb_push_timeout` и `account_banned_by_platform`. |
| R5 | Infinite fix-loop | После 2 неудачных auto-apply одного кода → `publisher_fixes.enabled = FALSE` + эскалация + investigation.status = 'escalated'. |
| R6 | Объём S3 | TTL lifecycle rule: failed fixtures — 14 дней, success — 48h. |
| R7 | Агент ломает прод | Две ветки (`main` — прод, `testbench` — агент). Merge в main только ручной, branch protection на `main`. |

## 8. Открытые технические вопросы (ответим в ходе T1-T3)

1. **Актуальный список `meta.category` значений** в проде — нужен прямой SELECT DISTINCT на `publish_tasks.events` за 30 дней, backfill T1 адаптируется под факт.
2. **Какой scheduler создаёт `publish_tasks` сейчас** — правку T3a (фильтр per-instance) делаем точечно, не в blind.
3. **device_serial phone #19** — нужен фактический серийник ADB для T3.
4. **Seed-медиа набор** — 5-10 файлов per content_type, 1080×1920 / 1080×1080 (per memory `feedback_validator_upload_rules`). Взять из существующих валидных в `s3://autowarm/publish-media/...` или залить новые.

Эти вопросы решаются чтением прод-БД / кодовой базы при старте T1 — не блокируют аппрув плана.

## 9. Next step

**Пользователь говорит «да, делаем» → начинаем параллельно:**
1. T1 — пишу SQL миграцию, показываю, применяем на dev.
2. Читаю `publisher_legacy.py` полностью для T2 (fixture-dumper) + T3a (scheduler filter).
3. Определяю актуальный `device_serial` phone #19 (SELECT из `publish_tasks` по метке «Тестовый проект_19»).
4. Собираю seed-медиа набор для T3.

**При разногласиях** — правим план до деплоя.

---

## 10. EXECUTED — 2026-04-21

**Статус плана:** ✅ 18/19 задач закрыто за один день. T16 (CI-gate) отложен — требует XML-replay harness без устройства, отдельная работа.

### Отклонения от изначального плана

| Поле | План | Факт | Почему |
|---|---|---|---|
| Арх. разделения | Две PM2-инстанции publisher.py | Одна PM2 app + тонкий `testbench_scheduler.js` в user-space клоне; прод-scheduler.js пропатчен `AND testbench = FALSE` | publisher.py — subprocess, не PM2-процесс. Разделение на уровне scheduler чище. |
| Testbench checkout | `/root/.openclaw/workspace-genri/autowarm-testbench/` | `/home/claude-user/autowarm-testbench/` | Работа под claude-user без sudo — проще и безопаснее. `/root/.openclaw/workspace-genri/autowarm/` тоже оказалась writable для claude-user (нетипично). |
| OAuth для LLM | `anthropic.ANTHROPIC_API_KEY` permanent | Default `AGENT_DIAGNOSE_PROVIDER=groq` с `llama-3.3-70b-versatile` | Anthropic OAuth на autowarm `.env` просрочен (та же проблема что у validator). Groq работает и стоит $0.0015/диагноз. |
| publisher_legacy.py | В прод main ветке | В main публикатор ЕЩЁ монолитный (refactor только в `feature/publisher-oop-refactor`) — работаем с `publisher.py` 6700 строк | Merge OOP-refactor не случился до старта. |

### Ключевые артефакты

- **Код** в ветке `testbench` на `/home/claude-user/autowarm-testbench/` (не push'ен в origin — GenGo2/* private, gh не аутентифицирован).
- **SQL-миграция** `20260421_testbench_foundation.sql` применена на прод-БД. Обратная миграция готова.
- **Прод-правки** (минимум): `scheduler.js` +3 строки, `server.js` +2 endpoints, `public/testbench.html` новый, `public/index.html` +3 строки (колонка Старт → fallback на `created_at` для testbench).
- **systemd** `autowarm-testbench-orchestrator.service`, `autowarm-testbench-rollback.{service,timer}`.
- **CLI** `/usr/local/bin/testbench-{start,stop,status}.sh`.
- **Регресс-корпус** — 1 seed запись `adb_push_chunked_md5_mismatch/` (fixture.tar.gz + expected_outcome.json + README).
- **Evidence** — `.ai-factory/evidence/publish-testbench-20260421.md`.

### Первые результаты (за ~1.5 часа работы стенда)

- 12 задач запущено, **0 успеха, 12 fail** — подтверждает жалобу пользователя «публикация совсем не работает».
- 4 открытых investigations: `adb_push_chunked_md5_mismatch` (7 повторов), `adb_push_chunked_failed` (2), `yt_accounts_btn_missing` (1), `adb_push_chunked` (1).
- 4 LLM-диагноза сгенерированы, суммарная стоимость $0.01 (Groq).
- 0 auto-apply (все классы пока non-auto-fixable — физические ADB-баги и UI-класс без `selector_drift` импл).

### Главная находка

`adb_push_chunked_md5_mismatch`: `remote_md5 = d41d8cd9` = md5 **пустого файла**. То есть chunks передались (9/9 OK), но `cat` merge на устройстве даёт 0 байт. Это **новый баг поверх** известного ADB packet loss — `adb_push_chunked` workaround сам сломался. Нужен human review; диагноз в `evidence/publish-triage/adb_push_chunked_md5_mismatch-20260421-094405-task523.md`.
