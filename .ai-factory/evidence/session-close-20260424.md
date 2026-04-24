# Session close — 2026-04-24

**Session:** backlog P2 → P4 → P1 + 2 bonus fixes
**Branch:** `feature/farming-testbench-phone171`
**Relates to plan:** `.ai-factory/plans/backlog-prioritized-review-20260424.md`

## Что сделано

### 1. P4 — Farming triage автоматизация (cdd0fba)
- PM2 app `autowarm-farming-triage` с wrapper-loop `scripts/farming-testbench/farming-triage-loop.sh`
- `TRIAGE_INTERVAL_SEC=1800` (30 мин), `TRIAGE_WINDOW_MIN=60`
- Заменяет ненаставленный systemd-таймер (`autowarm-farming-triage-dispatcher.service` — не установлен из-за NOPASSWD scope)
- Online 0 restarts, первый scan подтверждён

### 2. P1 — IG switch failure taxonomy split (77bc44c + 527ee2e)
- Разведка 6 fixture tasks в `farming_investigations.account_mismatch_after_switch`:
  - 5 случаев: target account не в dropdown (foreign sessions reels/store/google/dr.maratovna01)
  - 1 случай (task 262): target найден, но `get_current_instagram_account()` вернул None после tap
- Код-фикс `warmer.py::switch_instagram_account`:
  - Retry verify 3×2s после tap (было: одна попытка + 3s settle)
  - Emit `type=error` с `meta.category='ig_target_not_in_switcher'` или `='ig_switch_verify_failed'`
- Classifier `farming_triage_classifier.py`:
  - 2 new regex (priority ↑ generic mismatch)
  - `canonical_codes` dedup расширен
  - **Idempotency fix**: `already_emitted` pre-filter (инцидент — stale investigations re-open цикл)
- SQL seed `migrations/20260424_ig_switch_error_codes_seed.sql` + rollback
- Tests `tests/test_farming_triage_classifier.py` — 7/7 passed (+ 19 regression)

### 3. P2 — Phone #171 cleanup (manual user action + verification)
- `pm clear com.zhiliaoapp.musically` + `com.instagram.android`
- ADB через remote server mode: `adb -H 82.115.54.26 -P 15088 -s RF8Y90GCWWL`
- User выполнил re-login → IG verified: task #341 (born.trip90) успешно за 11с
- `ig_target_not_in_switcher` investigation → `closed_fixed`
- TT всё ещё падает на splash hang (не связано с релогином — устройство-специфичная задержка)

### 4. Bonus — Sequential orchestrator guard (af18a70)
- User заметил видимую параллель tasks в UI
- Корень: orchestrator тикал по таймеру не глядя на очередь, scheduler сериализовал, в БД/UI копились `scheduled` tasks
- Фикс: `farming_orchestrator.py::tick()` skip при `COUNT(status IN pending/scheduled/claimed/running) > 0`
- 41 stale scheduled task → cancelled manually
- Guard LIVE-verified (Monitor event `skip tick: 2 active testbench task(s) in queue (sequential mode)`)

### 5. Bonus — PM2 dump path drift discovery
- Обнаружено при живом тесте guard'а: `autowarm-farming-orchestrator` работал из dev-path `/home/claude-user/autowarm-testbench/`, а фиксы коммитились в prod `/root/.openclaw/workspace-genri/autowarm/`
- Корень: исторический `pm2 start` был сделан напрямую до существования `ecosystem.farming-testbench.config.js`, `pm2 save` поймал dev-cwd, `pm2 restart` не обновляет cwd
- Fix: `pm2 delete + pm2 start ecosystem.farming-testbench.config.js --only <app>` (из prod dir)
- Saved in memory `feedback_pm2_dump_path_drift.md`

## Commits

### autowarm prod (GenGo2/delivery-contenthunter, branch testbench)
- `cdd0fba` feat(farming-testbench): PM2 app autowarm-farming-triage — 30m loop
- `77bc44c` fix(warmer+triage): разделить IG switch failure cases (B1 target not logged-in vs B3 post-tap verify None)
- `527ee2e` fix(triage): idempotent classify_events — skip codes уже эмитированные ранее
- `af18a70` fix(farming-orchestrator): sequential guard — skip tick если в очереди active task

### contenthunter (rmbrmv/contenthunter, branch feature/farming-testbench-phone171)
- `c7d0dea` docs(plan+evidence): backlog review + P2/P4/P1 execution (2026-04-24)
- `6fcff3d` docs(evidence): P2 re-login verify + sequential orchestrator guard

## Tests

- `pytest tests/test_farming_triage_classifier.py -v` → **7 passed** (new)
- `pytest tests/test_farming_errors.py tests/test_farming_orchestrator.py -q` → **19 passed** (regression clean)

## Live verification

- Task #341 (IG born.trip90) — **18.5 мин farming день 1**, 40 видео, S3 recording, день 2 запланирован
- Task #342 (TT born7499) — expected fail `tt_account_read_fail` — phone #171 splash hang, отдельный open issue
- Sequential guard — Monitor event: `14:58:30 skip tick: 2 active testbench task(s) in queue (sequential mode)`
- Triage PM2 loop — первый scan прошёл через wrapper, next в 15:20

## DB state after session

Open `farming_investigations`:

| error_code | occurrences | n_tasks | note |
|---|---|---|---|
| `yt_account_read_fail` | 51 | 19 | phone #171 YT bottom-nav — независимый bug |
| `tt_account_read_fail` | 48 | 18 | phone #171 TT splash hang — независимый bug |
| `farming_app_launch_failed` | 23 | 12 | smoke artefact |
| `ig_switch_verify_failed` | 2 | 2 | 1 historical (262) + 1 старый (172); **новые не добавляются после patch** |
| `ig_account_read_fail` | 3 | 1 | outlier |
| `farming_preflight_failed` | 2 | 2 | — |

Closed via session:
- `account_mismatch_after_switch` — 3 investigations (ids 15, 19, 30) → `closed_fixed`
- `ig_target_not_in_switcher` — 1 investigation (id 31) → `closed_fixed` после re-login verified

## Memory updates

- `feedback_pm2_dump_path_drift.md` — NEW
- `reference_adb_remote_server_mode.md` — NEW (ADB -H/-P pattern vs `adb connect`)
- `project_farming_testbench.md` — обновлён (triage auto, 3 PM2 apps, IG split taxonomy, idempotency note)
- `MEMORY.md` — index обновлён

## Out of scope

Остаются открытые пункты из плана `backlog-prioritized-review-20260424.md`:
- **P3** id_parser IG (Apify 403 + IG 429) — 4/288 NULL, не горит
- **P5** YT Settings-activity primary path — workaround существует, nobody bleeding
- **P6** Revision partial_result на child exit != 0 — ждёт метрики
- **P7-P10** — low priority / тriggered-by-request
- **Phone #171 TT splash hang** — открытый bug, не в scope этой сессии (пользователь согласился отложить)

Следующую сессию стоит начинать с проверки `farming_investigations` open / closed delta за сутки — если `tt_account_read_fail` продолжает расти при явно работающем релогине, это сигнал что phone #171 TT требует физического reboot или warmer settle_s tuning.
