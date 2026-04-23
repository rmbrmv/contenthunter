# Farming Testbench — Phone #171 (полный аналог autowarm-testbench для фарминга)

**Branch:** `feature/farming-testbench-phone171`
**Plan date:** 2026-04-23
**Target repo:** `/root/.openclaw/workspace-genri/autowarm/` (branch `testbench` в autowarm)
**Reference:** publish-testbench (ecosystem.testbench.config.js + testbench_orchestrator.py + testbench.html) — скопирован структурой, адаптирован под фарминг

## Settings

- **Testing:** yes — unit-тесты orchestrator/scheduler + integration smoke на #171
- **Logging:** verbose — все фазы warmer, orchestrator tick, scheduler dispatch, triage/diagnose/apply/rollback пишут DEBUG с `task_id`/`platform`/`account`
- **Docs:** yes — мандаторный чекпойнт на финальной фазе (evidence-файл, обновление `docs/autowarm.md`)
- **Roadmap:** нет `ROADMAP.md` — линкаж пропущен

## Цель

Построить полный изолированный контур тестового стенда для подсистемы **фарминга** на phone #171, по аналогии с публикационным стендом на phone #19. Стенд должен:

1. Автономно создавать фарминг-задачи (аналог `publish_tasks.testbench=TRUE`) на #171 по конфигурируемому кадансу.
2. Собирать ошибки, классифицировать их (triage-classifier), диагностировать (agent_diagnose), применять патчи (agent_apply), откатывать при деградации (auto_rollback) — **полный auto-fix loop**.
3. Отдавать UI на новой странице `/farming-testbench.html` с категориями ошибок, списком последних задач, открытыми investigations, и кнопками start/stop.
4. Быть полностью изолированным от прод-фарминга (`scheduler.js` на других телефонах продолжает работать без вмешательства).

## Ключевые архитектурные решения (зафиксировано с пользователем 2026-04-23)

| Вопрос | Решение |
|---|---|
| UI | Новый файл `public/farming-testbench.html` (параллельно `testbench.html`). URL: `https://delivery.contenthunter.ru/farming-testbench` |
| Изоляция | Полная: новый PM2 app `autowarm-farming-testbench` + новый systemd `autowarm-farming-orchestrator` + флаг `system_flags.farming_testbench_paused` |
| Каданс | Конфигурируемо через `system_flags.farming_orchestrator_cadence_min` (default 240 = 4ч, делится на 3 платформы → ~80 мин на платформу) |
| Auto-fix | Полный аналог: `triage_classifier` ветка для фарминга + `agent_diagnose_farming` + `agent_apply` (переиспользуем если возможно) + `auto_rollback_farming` |
| Аккаунты | Пользователь предоставит список реально залогиненных аккаунтов на #171 — план включает задачу их внесения в factory_inst_accounts и распределения по пакам 308 (171a) / 309 (171b) |
| Кол. тегов | `autowarm_tasks.testbench BOOLEAN DEFAULT FALSE` — добавляется миграцией, стенд пишет с `testbench=TRUE` |

## Текущее состояние (обнаружено при разведке 2026-04-23)

- **Phone #171**: `device_id=RF8Y90GCWWL`, `raspberry_number=8`, ADB `82.115.54.26:15088` (port_scr `27830`)
- **Паки**: factory_pack_accounts id=308 «Тестовый проект_171a», id=309 «Тестовый проект_171b» — оба пустые
- **factory_inst_accounts** на #171: **0 записей** (миграция 20260422_split_phone171_legacy_pack.sql переименовала паки, но ivana/google там отсутствуют)
- **autowarm_tasks** с `device_serial='RF8Y90GCWWL'`: **0 записей** — фарминга на #171 никогда не было
- **warmer.py**: единственная точка входа (`run_task(task_id)` ~line 2760). `BanDetectedException` — единственный explicit exception. Ошибки хранятся в `autowarm_tasks.events` (JSONB), `preflight_errors`, `log` (TEXT).
- **Farming orchestrator**: не существует (публикационный orchestrator `testbench_orchestrator.py` захардкожен под phone #19 / project «Тестовый проект_19»)
- **Taxonomy**: `publish_error_codes` + `publish_investigations` у публикации, у фарминга — ничего, только JSONB inline-логи
- **Scheduler**: прод `scheduler.js` (60s tick) обрабатывает ВСЕ `autowarm_tasks` с priority `publish > farm`. Тестовый scheduler для фарминга отсутствует.

## Known risks (памятью подтверждено)

- **Phone #171 частично сломан**: IG починен 2026-04-22, TT залип в чужом аккаунте `@rahat.mobile.agncy.31`, YT bottom-nav `(972,2320)` не открывает профиль. Стенд на TT/YT первыми же прогонами поймает эти баги — это ожидаемо и даже полезно для auto-fix loop.
- **ADB packet loss VPS↔proxy**: 20% потерь на hop 4, чанкнутый push уже обсуждался в другом плане. Фарминг меньше зависит от media, но screencast upload может страдать — закладываем retry.
- **pytest-discipline для параллельных сессий**: перед commit гонять зелёный pytest (memory feedback_parallel_claude_sessions).

## Tasks

### Phase 0 — Provisioning аккаунтов (БЛОКИРУЕТ всё ниже)

#### T1. ✅ Собрать с пользователя список залогиненных аккаунтов на phone #171
- **Status:** DONE 2026-04-23
- **Evidence:** `.ai-factory/evidence/farming-testbench-accounts-phone171-input-20260423.md`
- **Итог:** 6 аккаунтов в factory_inst_accounts (3 на 171a + 3 на 171b):
  - 171a (pack 308): IG=ivana.world.class · TT=user899847418 · YT=Ivana-o3j
  - 171b (pack 309): IG=born.trip90 · TT=born7499 · YT=Born-i6i3n

#### T2. ✅ Миграция: добавить колонку `autowarm_tasks.testbench`
- **Status:** DONE 2026-04-23
- **Evidence:** `.ai-factory/evidence/farming-testbench-t2-migration-20260423.md`
- **Applied:** ALTER TABLE + partial index (idx_autowarm_tasks_testbench on id DESC WHERE testbench=TRUE). 140 прод-строк = testbench=FALSE, 0 тестбенч-строк пока.

#### T3. ✅ Smoke-проверка сессий на устройстве (partial, ожидаемо)
- **Status:** DONE 2026-04-23
- **Evidence:** `.ai-factory/evidence/farming-testbench-t3-preflight-20260423.md`
- **Итог preflight:**
  - IG ✅ found: `['ivana.world.class', 'born.trip90']`
  - TT ❌ `app_not_launched` — зависание на SplashActivity после ручного ре-логина (возможно network/OAuth). **Ожидаемое first-investigation для testbench.**
  - YT ❌ `anchor_suspicious_position` — известный баг #171 bottom-nav. **Ожидаемое first-investigation для testbench.**
- **Решение:** идём дальше. MVP orchestrator round-robin'ит все 3 платформы, TT/YT будут первыми кейсами для auto-fix loop (T13-T16).

**→ Commit 1 после T3: `feat(farming-testbench): phone #171 accounts provisioned + autowarm_tasks.testbench col + preflight evidence`**

---

### Phase 1 — Farming taxonomy + investigation schema

#### T4. ✅ Миграция: таблицы `farming_error_codes` + `farming_investigations`
- **Status:** DONE 2026-04-23
- **Applied:** migrations/20260423_farming_taxonomy.sql + rollback. Обе таблицы + 2 индекса (last_seen × status, UNIQUE error_code WHERE status='open') созданы. Схема 1-в-1 с publish_error_codes/publish_investigations.
- **Deliverable:** SQL-миграция (reverse-engineer схему из `publish_error_codes` / `publish_investigations`, один-в-один адаптировать под фарминг)
- **Contents:**
  ```sql
  CREATE TABLE farming_error_codes (
    code TEXT PRIMARY KEY,
    severity TEXT CHECK (severity IN ('info','warn','error','critical')),
    retry_strategy TEXT CHECK (retry_strategy IN ('none','immediate','backoff','skip_platform')),
    is_known BOOLEAN DEFAULT TRUE,
    is_auto_fixable BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE TABLE farming_investigations (
    id SERIAL PRIMARY KEY,
    error_code TEXT REFERENCES farming_error_codes(code),
    platform TEXT, -- instagram/tiktok/youtube
    severity TEXT,
    is_auto_fixable BOOLEAN,
    occurrences_count INT DEFAULT 1,
    last_seen_at TIMESTAMPTZ,
    fixture_task_ids INT[], -- references autowarm_tasks
    report_path TEXT,
    status TEXT DEFAULT 'open', -- open/in_progress/resolved
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
  );
  ```
- **Files:** `migrations/20260423_farming_taxonomy.sql` + rollback
- **Log:** verbose на применение миграции

#### T5. ✅ Seed начального набора известных error codes
- **Status:** DONE 2026-04-23
- **Applied:** 23 кода засеяны (2 critical / 14 error / 5 warn / 2 info). Покрывают BanDetected, infrastructure (ADB), platform-specific bugs (tt_foreign_profile_stuck, yt_bottom_nav_unresponsive, yt_anchor_suspicious_position, yt_no_channel), и state-management codes.
- **Migration:** migrations/20260423_farming_error_codes_seed.sql + rollback
- **Known #171 bugs все учтены** — станут auto-fix кандидатами.

#### T5_original. (legacy description, заархивировано)
- **Deliverable:** SQL-insert с ~15-20 известными кодами (выжатыми из warmer.py `BanDetectedException` + status enum в `autowarm_tasks`)
- **Codes (draft):**
  - `ban_detected` (critical, skip_platform, auto_fixable=false)
  - `adb_disconnect` (error, backoff, auto_fixable=true)
  - `adb_push_timeout` (warn, immediate, auto_fixable=true)
  - `app_init_failed` (error, backoff, auto_fixable=true)
  - `account_not_active` (warn, none, auto_fixable=false)
  - `screen_locked_pin` (warn, none, auto_fixable=false)
  - `ig_bottom_nav_missing` (error, backoff, auto_fixable=true) — известный bug на #171
  - `yt_bottom_nav_unresponsive` (error, backoff, auto_fixable=true) — известный bug на #171
  - `tt_foreign_account_stuck` (error, backoff, auto_fixable=true) — известный bug на #171
  - `warmer_preflight_failed` (warn, none, auto_fixable=false)
  - `screen_record_upload_failed` (warn, immediate, auto_fixable=true)
  - ... (расширить при анализе warmer.py)
- **Files:** `migrations/20260423_farming_error_codes_seed.sql` + rollback
- **Log:** verbose, counts inserted

#### T6. ✅ farming_errors.py + патчи warmer.py
- **Status:** DONE 2026-04-23
- **Deliverables:**
  - `farming_errors.py` — emit_farming_error(task_id, code, context) + close_investigation(code, resolution). Upsert-семантика (existing open investigation → ++occurrences_count + dedup fixture_task_ids; new code → INSERT). Smoke-test ✅ с 2 emit'ами + cleanup.
  - warmer.py patches в 3 критичных местах: `handle_ban` (→ ban_detected), `preflight_check` failure block (→ farming_preflight_failed), `run_task` Exception catchall (→ warmer_exception_uncaught).
- **Note:** остальная классификация событий пойдёт через triage_classifier (T13) — LLM пост-фактум классифицирует generic events JSONB в farming_error_codes. Hardcoded сайты в warmer.py покрывают ТОЛЬКО детерминированные критичные случаи.

#### T6_original. Extend warmer.py — emit типизированные error codes
- **Deliverable:** в `warmer.py` и связанных модулях все места, где сейчас пишется inline-string в events/log, получить явный `error_code` из `farming_error_codes`
- **Action:** добавить helper `emit_farming_error(task_id, code, context_dict)` → INSERT в events + UPDATE last_seen_at в investigations + INSERT/UPDATE investigations (increment occurrences_count, update fixture_task_ids)
- **Files:** `/root/.openclaw/workspace-genri/autowarm/farming_errors.py` (новый), патчи в `warmer.py` (~10-15 мест вызовов)
- **Log:** каждый emit — DEBUG с code+task_id+platform

**→ Commit 2 после T6: `feat(farming): error taxonomy (farming_error_codes + investigations + emit helper)`**

---

### Phase 2 — Farming orchestrator (core loop)

#### T7. ✅ Новый модуль `farming_orchestrator.py`
- **Status:** DONE 2026-04-23
- **Deliverable:** `/root/.openclaw/workspace-genri/autowarm/farming_orchestrator.py` (355 строк)
- **Verified dry-runs:**
  - Tick 1: IG → ivana.world.class@171a · ADB 82.115.54.26:15088 · protocol=1
  - Tick 2: TT → user899847418@171a · protocol=2
  - Tick 3: YT → Ivana-o3j@171a · protocol=3
  - Cursor rotation работает: платформа+аккаунт через DB-persistent курсоры в system_flags
- **Kill-switches:** farming_testbench_paused + check_ban_open (auto-pause + TG-эскалация при open ban_detected investigation)
- **Cadence:** динамическое чтение из system_flags.farming_orchestrator_cadence_min (default 240)

#### T7_orig. Новый модуль `farming_orchestrator.py`
- **Deliverable:** Python-модуль, запускаемый как systemd service, аналог `testbench_orchestrator.py`
- **Constants:**
  - `PROJECT_NAME = 'Тестовый проект_171a'` + `'Тестовый проект_171b'` (round-robin между паками)
  - `PHONE_171_SERIAL = 'RF8Y90GCWWL'`
  - `RASPBERRY_NUM = 8`
  - `ADB_HOST = '82.115.54.26'`, `ADB_PORT = '15088'`
  - `SYSTEM_FLAG_PAUSED = 'farming_testbench_paused'`
  - `SYSTEM_FLAG_CADENCE = 'farming_orchestrator_cadence_min'` (default 240)
- **Main loop `tick()`:**
  1. Проверить `system_flags.farming_testbench_paused = 'true'` → skip
  2. Round-robin по платформам IG → TT → YT через cursor `system_flags.farming_orchestrator_platform_cursor`
  3. Выбрать активный аккаунт для платформы (round-robin через `factory_inst_accounts` на packs 308/309, исключить `factory_reg_accounts.<platform>_block IS NOT NULL`)
  4. Выбрать протокол фарминга (`autowarm_protocols WHERE protocol_type='farming' AND platform=<X>`) — round-robin через другой cursor
  5. INSERT в `autowarm_tasks` с `testbench=TRUE`, `status='pending'`, `device_serial='RF8Y90GCWWL'`, `adb_port='15088'`, `current_day=1`
  6. Auto-pause safeguard: если 10 последних `autowarm_tasks WHERE testbench=TRUE` имеют `error_code='ban_detected'` → SET `farming_testbench_paused='true'` + notify
- **CLI:** `--dry-run`, `--once`
- **Signal handling:** SIGTERM/SIGINT graceful
- **Logging:** stdout (→ systemd journal), format `%(asctime)s [%(levelname)s] [orchestrator] %(message)s`, verbose DEBUG
- **Files:** `/root/.openclaw/workspace-genri/autowarm/farming_orchestrator.py`

#### T8. ✅ Unit-тесты orchestrator round-robin
- **Status:** DONE 2026-04-23
- **Deliverable:** `tests/test_farming_orchestrator.py` (11 тестов, все зелёные)
- **Coverage:**
  - Round-robin visits both accounts [A,B,A,B]
  - Cursor persists в system_flags (2 calls → wrap-around)
  - All blocked returns None (factory_reg_accounts.ig_block)
  - is_paused true/false/missing (3 теста)
  - cadence_min default + read from flag
  - check_ban_open: none/open/only-closed (3 теста)
- **Изоляция:** autocommit=False + ROLLBACK в teardown, fake id 99980+, fake платформы `_test_farming_rr_*`

#### T8_orig. Unit-тесты orchestrator round-robin
- **Deliverable:** `tests/test_farming_orchestrator.py` (по образу `test_testbench_orchestrator.py`)
- **Coverage:** round-robin cursor read/write, account filter по blocks, auto-pause логика, kill-switch, протокол выбор
- **Fixtures:** реальный DB с ROLLBACK isolation, фейковые аккаунты id=99990+, PACK_ID_PHONE_171A=308, PACK_ID_PHONE_171B=309

**→ Commit 3 после T8: `feat(farming): orchestrator with round-robin + kill-switch + auto-pause`**

---

### Phase 3 — Scheduler + process management

#### T9. ✅ farming_testbench_scheduler.js — Node.js dispatcher
- **Status:** DONE 2026-04-23 · syntax OK
- **Deliverable:** `farming_testbench_scheduler.js` (271 строка). Poll autowarm_tasks WHERE testbench=TRUE + tick 15s + flock lock + stuck cleanup (2h timeout → failed + farming_stuck_timeout investigation upsert).

#### T10. ✅ ecosystem.farming-testbench.config.js — PM2 app `autowarm-farming-testbench`

#### T11. ✅ Systemd unit autowarm-farming-orchestrator.service (в autowarm/systemd/)
- User=claude-user, WorkingDirectory=/home/claude-user/autowarm-testbench
- MemoryMax=200M CPUQuota=30%

#### T12. ✅ Shell-скрипты farming-testbench-{start,stop,status}.sh в scripts/farming-testbench/
- Все три следуют паттерну публикационных (step_systemctl_{start,stop} helper, pipefail-safe `systemctl cat` вместо `list-unit-files | grep`, PGPASSWORD env для psql, --force для stop, цветной status с isolation-check prod+publish-testbench).

#### T9_orig. Новый `farming_testbench_scheduler.js`
- **Deliverable:** Node.js scheduler, polls `autowarm_tasks WHERE testbench=TRUE AND status='pending'`
- **Behavior:**
  - Tick interval: 15 sec (быстрее прода, медленнее publish testbench 10s — фарминг-run длинный)
  - Max concurrent: 1 (phone #171)
  - Lock file: `/var/lock/autowarm-farming-testbench-scheduler.lock`
  - Kill-switch: при `system_flags.farming_testbench_paused='true'` — не диспатчит
  - Spawn subprocess: `python3 /root/.openclaw/workspace-genri/autowarm/warmer.py --task-id <id>`
  - Stuck cleanup: каждые 20 тиков (~5 мин) сбрасывать `status='running'` с `started_at < NOW() - INTERVAL '2 hours'` → `'failed'` с `error_code='farming_stuck_timeout'`
- **DB:** та же connection что у прода, через `.env`
- **Logging:** stdout с timestamps, DEBUG-фаза для каждого poll
- **Files:** `/root/.openclaw/workspace-genri/autowarm/farming_testbench_scheduler.js`

#### T10. PM2 ecosystem config `ecosystem.farming-testbench.config.js`
- **Deliverable:** конфиг для PM2 app `autowarm-farming-testbench`
- **Параметры:** 1 instance, fork mode, autorestart, max_memory 500M, NODE_ENV=farming-testbench, log files `/var/log/autowarm-farming-testbench-{err,out}.log`
- **Files:** `/root/.openclaw/workspace-genri/autowarm/ecosystem.farming-testbench.config.js`

#### T11. Systemd unit `autowarm-farming-orchestrator.service`
- **Deliverable:** systemd unit-файл для farming orchestrator
- **Зависимости:** After=network.target postgresql.service; ExecStart=`python3 /root/.../farming_orchestrator.py`; Restart=on-failure; RestartSec=30; User=root (per current convention)
- **Log:** journald capture
- **Files:** `/root/.openclaw/workspace-genri/autowarm/systemd/autowarm-farming-orchestrator.service` + инструкция в PUBLISH-NOTES.md или новом `FARMING-NOTES.md`

#### T12. Shell-скрипты start/stop/status
- **Deliverable:** три скрипта аналогично `/usr/local/bin/testbench-{start,stop,status}.sh`
- **`/usr/local/bin/farming-testbench-start.sh`** (4 шага, идемпотентно):
  1. `pm2 start ecosystem.farming-testbench.config.js` (если не запущен)
  2. `systemctl start autowarm-farming-triage-dispatcher` (добавится в фазе 4 — пока что stub/опционально)
  3. `systemctl start autowarm-farming-orchestrator`
  4. SQL: `UPDATE system_flags SET value='false' WHERE key='farming_testbench_paused'`
  - Log: `/var/log/farming-testbench-start.log` (fallback `/tmp/`)
- **`/usr/local/bin/farming-testbench-stop.sh`** (defensive, flag `--force` для UI):
  1. SQL: `farming_testbench_paused='true'`
  2. systemctl stop autowarm-farming-orchestrator
  3. systemctl stop autowarm-farming-triage-dispatcher (если существует)
  4. pm2 stop autowarm-farming-testbench
- **`/usr/local/bin/farming-testbench-status.sh`** (diagnostic, цветной):
  - Флаг paused, PM2 app state + restart count, systemd units active, orchestrator 1h activity, open investigations top 5
  - Проверка prod `scheduler.js` online (isolation check)
- **Files:** три файла в `/usr/local/bin/` (создать через sudo — у claude-user есть NOPASSWD sudo для нужных операций)

**→ Commit 4 после T12: `feat(farming): scheduler + pm2 + systemd + shell ops scripts`**

---

### Phase 4 — Auto-fix loop (triage + diagnose + apply + rollback)

#### T13. ✅ farming_triage_classifier.py (new module, regex-fallback classifier)
- Deliverable: `/root/.openclaw/workspace-genri/autowarm/farming_triage_classifier.py` (211 строк). 19 regex-правил для known farming-паттернов (splash hang, TT foreign stuck, YT anchor suspicious, ADB disconnect, ban, no_channel, etc.). CLI: --task-id + --scan-recent. Внутренние 4/4 unit-теста зелёные.

#### T14. ✅ farming_agent_diagnose.py (new module, LLM-диагност)
- Deliverable: `/root/.openclaw/workspace-genri/autowarm/farming_agent_diagnose.py` (275 строк). Переиспользует `agent_diagnose.call_llm` + `MODEL_PRICES`. Farming-specific SYSTEM_PROMPT (warmer.py knowledge, known #171 bugs). Reports в evidence/farming-triage/. UPDATE farming_investigations.report_path + INSERT agent_runs.

#### T15. ✅ farming_agent_apply.py + farming_auto_rollback.py + farming_fixes table (REVIEW-MVP)
- Migration `20260423_farming_fixes.sql` applied (mirror publisher_fixes).
- `farming_agent_apply.py` — REVIEW-MODE: stages proposal в farming_fixes.enabled=FALSE с confidence≥7 guard. Kill-switch `system_flags.farming_auto_apply_enabled`. Реальный file_edit + git commit — upgrade в следующей итерации (безопасность phone #171 с частично сломанными TT/YT).
- `farming_auto_rollback.py` — ALERT-ONLY: пишет warning в notes при success_rate deg ≥30pp. Не revert'ит автоматически.

#### T16. ✅ systemd autowarm-farming-triage-dispatcher.{service,timer}
- Timer: OnBootSec=2min + каждые 15 мин.
- Service: oneshot цепочка `farming_triage_classifier --scan-recent && farming_auto_rollback --dry-run`.
- Depends on: autowarm-farming-orchestrator.service (After=).

**→ Commit 5 после T16: `feat(farming): full auto-fix loop (triage+diagnose+apply+rollback)`**

---

### Phase 5 — Frontend (farming-testbench.html + backend routes)

#### T17. ✅ Backend routes /api/farming/testbench/{dashboard,report,start,stop}
- 4 endpoint'а под requireAuth middleware. Параллельно /api/publish/testbench/*.
- dashboard возвращает 8 полей: flags, recent_tasks (30), hourly_rates, open_investigations, error_codes, categories (aggregated), agent_stats_7d, farming_fixes.
- report whitelist: 2 allowed roots (testbench-home + workspace-genri).
- start/stop: execFile shell-скрипты с timeout 60s.

#### T18. ✅ public/farming-testbench.html — standalone страница
- 445 строк, синяя палитра (отличить от публикации).
- 6 секций: Kill-switches + agent stats, Error Categories (aggregated table), Open investigations, Hourly rates, Farming fixes (review mode), Recent 30 tasks.
- Report viewer modal с markdown render.
- Auto-refresh 30s.
- Start/Stop кнопки с confirm-диалогом.

#### T19. ✅ SPA-ссылка на Testbench из index.html
- Добавлена в sidebar-farming после "Прогрев телефонов".
- `<a href="/farming-testbench.html" target="_blank">` — открывается в новом табе, не ломает SPA hash-routing.

#### T17_orig. Backend routes в `server.js`
- **Deliverable:** 4 новых endpoint'а, параллельных публикационным
- **Routes:**
  - `GET /api/farming/testbench/dashboard` — агрегация (`system_flags` с farming_* ключами; последние 30 `autowarm_tasks WHERE testbench=TRUE` с join на `farming_error_codes` через events/error_code; hourly success rates; open `farming_investigations`; agent runs 7d; error codes taxonomy)
  - `GET /api/farming/testbench/report?path=...` — чтение markdown отчёта из whitelist `/home/claude-user/autowarm-farming-testbench/evidence/farming-triage/`
  - `POST /api/farming/testbench/start` — вызов `/usr/local/bin/farming-testbench-start.sh`, timeout 60s, лог user/IP
  - `POST /api/farming/testbench/stop` — `/usr/local/bin/farming-testbench-stop.sh --force`
- **Middleware:** `requireAuth`
- **Files:** server.js (~+150 строк, модельно после publish-testbench endpoints ~line 1947)
- **Log:** verbose на каждый запрос + ошибки

#### T18. Новая HTML-страница `public/farming-testbench.html`
- **Deliverable:** статическая страница, структурно копирует `testbench.html`, но:
  - Вызывает `/api/farming/testbench/*` endpoint'ы
  - Заголовок «Фарминг Testbench — Phone #171»
  - Секция «Категории ошибок» — таблица `farming_error_codes` × platform × occurrences с цветовой кодировкой по severity
  - Секция «Open investigations» — как у публикации, но с ссылкой на farming-specific report_path
  - Секция «Последние задачи» — 30 последних `autowarm_tasks WHERE testbench=TRUE`
  - Секция «Hourly rates» — success/fail per platform × 1h окно
  - Кнопки **Start Testbench** (disabled если paused=false) / **Stop Testbench** (disabled если paused=true), confirm-диалог
  - Auto-refresh 30s
- **Visual:** собственная цветовая схема (чтобы визуально не путать с publish-testbench) — например синяя акцентная палитра вместо оранжевой
- **Files:** `/root/.openclaw/workspace-genri/autowarm/public/farming-testbench.html`

#### T19. SPA-интеграция + ссылка из главного приложения
- **Deliverable:** `public/index.html` — добавить в сайдбар или admin-секцию ссылку «Фарминг Testbench» → `/farming-testbench.html` (открывается в новом табе или как отдельная страница, чтобы не смешивать с SPA hash-routing)
- **Files:** патч в `public/index.html`

**→ Commit 6 после T19: `feat(farming-testbench): UI page + backend routes + SPA link`**

---

### Phase 6 — Tests + integration verification

#### T20. Unit-тесты scheduler + farming_errors helper
- **Deliverable:** `tests/test_farming_testbench_scheduler.py` (минимум smoke — проверка lock, skip при paused, stuck cleanup), `tests/test_farming_errors.py` (emit helper, investigation dedup/upsert)
- **Files:** два файла в `tests/`

#### T21. Integration dry-run на #171
- **Deliverable:** запуск orchestrator с `--dry-run --once` → проверить что создаётся `autowarm_tasks` с правильными полями; потом без --dry-run запустить один полный tick → warmer подбирает task, запускается на устройстве, пишет events; triage_classifier обрабатывает fail; evidence-файл с полным прогоном
- **Files:** `.ai-factory/evidence/farming-testbench-integration-20260423.md`

#### T22. Документация
- **Deliverable:** обновить `/root/.openclaw/workspace-genri/autowarm/docs/autowarm.md` (секция Farming Testbench — команды старт/стоп/статус, список systemd units + PM2 apps, описание таблиц, runbook «как добавить новый error code», «как вернуть phone #171 в исходное состояние при критическом сбое»)
- **Files:** docs/autowarm.md

**→ Commit 7 после T22: `test(farming-testbench): units + integration evidence + runbook`**

---

### Phase 7 — Prod deploy + acceptance

#### T23. Deploy на prod VPS
- **Deliverable:** применить миграции, задеплоить код на `/root/.openclaw/workspace-genri/autowarm/` (push в ветку testbench или merge в testbench через PR, auto-push git-hook подхватит), скопировать shell-скрипты в `/usr/local/bin/`, зарегистрировать systemd units (`systemctl daemon-reload && systemctl enable autowarm-farming-orchestrator autowarm-farming-triage-dispatcher`), `pm2 start ecosystem.farming-testbench.config.js && pm2 save`
- **Risk:** PM2 символические ссылки ломаются при merge — по memory `autowarm_testbench_deploy`: requires restart systemd+pm2 после merge
- **Verify:** выполнить `/usr/local/bin/farming-testbench-status.sh` — все зелёные; открыть `/farming-testbench` в браузере, start, ждать один tick, увидеть задачу, остановить
- **Files:** evidence `.ai-factory/evidence/farming-testbench-deploy-20260423.md`

#### T24. Live smoke-test (5 прогонов)
- **Deliverable:** запустить стенд на 6-8 часов → зафиксировать первые ошибки (ожидаемые: TT foreign account stuck, YT bottom-nav unresponsive), убедиться что triage классифицирует, diagnose пишет отчёт, apply применяет (если auto_fixable=TRUE), metric в UI показывает изменения
- **Files:** evidence `.ai-factory/evidence/farming-testbench-live-smoke-20260423.md`

**→ Commit 8 после T24: `docs(farming-testbench): prod deploy + live smoke evidence`**

---

## Commit Plan Summary

| # | Commit | After task | Scope |
|---|---|---|---|
| 1 | `feat(farming-testbench): phone #171 accounts provisioned + autowarm_tasks.testbench col` | T3 | Phase 0 |
| 2 | `feat(farming): error taxonomy (farming_error_codes + investigations + emit helper)` | T6 | Phase 1 |
| 3 | `feat(farming): orchestrator with round-robin + kill-switch + auto-pause` | T8 | Phase 2 |
| 4 | `feat(farming): scheduler + pm2 + systemd + shell ops scripts` | T12 | Phase 3 |
| 5 | `feat(farming): full auto-fix loop (triage+diagnose+apply+rollback)` | T16 | Phase 4 |
| 6 | `feat(farming-testbench): UI page + backend routes + SPA link` | T19 | Phase 5 |
| 7 | `test(farming-testbench): units + integration evidence + runbook` | T22 | Phase 6 |
| 8 | `docs(farming-testbench): prod deploy + live smoke evidence` | T24 | Phase 7 |

## Open questions / гипотезы, которые решатся в процессе

- **Переиспользование `triage_classifier.py`/`agent_diagnose.py` vs новые модули**: решается в T13-T14 при чтении кода. Если обе функции явно захардкожены под `publish_tasks`/`publish_error_codes` — создаём новые, иначе добавляем domain-switch.
- **Auto-fix на известных бугах #171 (TT stuck, YT bottom-nav)**: это по сути уже готовые issue для auto-fix loop — первые же прогоны должны их поймать. Если patch сработает автоматически — отличное доказательство концепции. Если не сработает — заводим investigation вручную, agent_diagnose пишет отчёт, user решает руками.
- **Screencast upload в S3**: warmer.py уже имеет `SCREEN_RECORD_ENABLED`. Включаем для testbench — даёт видеодоказательство каждого прогона. Retry на upload-fail через `ad_hoc_logger` или `notifier`.
- **Каданс defaults**: 240 мин (4 часа) может быть слишком редко для auto-fix loop — если в первые сутки eng рост investigations медленный, понижаем до 120 или 60 через system_flags без перезапуска.

## Dependency graph

```
T1 → T2 → T3 → [commit 1]
                ↓
              T4 → T5 → T6 → [commit 2]
                             ↓
                           T7 → T8 → [commit 3]
                                      ↓
                                    T9 → T10 → T11 → T12 → [commit 4]
                                                            ↓
                                                          T13 → T14 → T15 → T16 → [commit 5]
                                                                                    ↓
                                                                                  T17 → T18 → T19 → [commit 6]
                                                                                                    ↓
                                                                                                  T20 → T21 → T22 → [commit 7]
                                                                                                                    ↓
                                                                                                                  T23 → T24 → [commit 8]
```

Всего: **24 задачи, 8 коммитов, 8 фаз**.
