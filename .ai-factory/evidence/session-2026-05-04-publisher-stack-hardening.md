# Session 2026-05-04 — publisher stack hardening

Большая сессия по публишеру: ship всех 5 фаз W3 obstacle KB framework, fix трёх root causes (Layer 1+2+3 silent hangs), W5 Promoter, Flip 1 (Anthropic vision), YT title/description carry-over из IG caption fix.

## 14 commits в prod main (chronological)

| SHA | What |
|---|---|
| `7ef28a6` | test(obstacle-kb): module-scope re-seed teardown — prevent prod KB blackout |
| `165a493` | fix(watchdog): write error event + error_code on subprocess silent hang (Layer 1) |
| `130ded4` | fix(switcher): progress step name out of fg_guard after _open_app (Layer 2) |
| `4cc16aa` | feat(vision): add _call_anthropic_vision + VISION_PROVIDER switch (W3.1) |
| `107adc0` | feat(ai_unstuck): KB shim — shadow always, apply gated by lookup_only (W3.2) |
| `49cb621` | feat(ai_unstuck): post-LLM auto-learn experimental obstacles (W3.3) |
| `93ad8ea` | feat(recovery): KB pre-check before nuclear recents-restart (W3.5) |
| `5a10991` | test(obstacle-kb): drop per-test DELETE — preserve outcomes via CASCADE |
| `70469fb` | diag(publisher): faulthandler stack-trace dump on silent hang |
| `f8a2618` | cleanup(ig-editor): drop last_action noise + align loop=20 (IG #6+#7) |
| `8d0a214` | feat(obstacle-promoter): T1/T2/T3 logic + 10 tests (W5 Task 28) |
| `f207c2e` | fix(watchdog): overwrite error_code='unknown' on silent hang detection |
| `f5ac8c7` | fix(triage): NULLIF guard — don't overwrite existing error_code |
| `e71657a` | feat(server): wire obstacle_promoter.tick() into hourly cron (W5 Task 30) |
| `69cf64b` | fix(publisher): catch BaseException in run_publish_task — Layer 3 root cause |
| `934d7aa` | feat(yt): title/description fill verification (carry-over from IG fix) |

Plus env edits (W4 Flip 1: VISION_PROVIDER=anthropic).

## Final flag state в `system_flags`

| Flag | Value | Effect |
|---|---|---|
| `obstacle_kb_disabled` | `false` | KB lookup активен (probes fire) |
| `obstacle_kb_lookup_only` | `true` | **Shadow mode** — no apply yet |
| `obstacle_promoter_disabled` | `true` | Promoter не работает |
| `obstacle_curator_bot_disabled` | `true` | Bot отключён |
| `obstacle_kb_anthropic_disabled` | `false` | Anthropic вызовы разрешены |
| `obstacle_kb_learn_disabled` | (default true) | Auto-learn не активирован |

`.env`:
| Var | Value |
|---|---|
| `VISION_PROVIDER` | `anthropic` (Sonnet 4.6) ← **активирован сегодня** |
| `ANTHROPIC_API_KEY` | Console `sk-ant-api03-...` (testbench fixed: was OAuth) |

## Three triads completed

### Triad 1 — `error_code='unknown'` attribution loophole (CLOSED)

181 silent IG fail/неделю показывались как `error_code=NULL` или `'unknown'`. Триада фиксов закрывает все 3 уровня:

- **Cause** (`69cf64b`): `run_publish_task` ловил только `Exception`, не `BaseException`. SIGINT (от pm2 reload или scheduler kill timer) → `KeyboardInterrupt` → except clause не матчил → status stays 'claimed'/'running'. Status update не выполняется.
- **Mapping protection** (`f5ac8c7`): `triage_classifier.process_failed_task` `UPDATE error_code` без `NULLIF` check — перезаписывал уже выставленный `'switch_failed_unspecified'` на `'unknown'` (когда нет error events с meta.category).
- **Fallback** (`f207c2e`): server.js watchdog — CASE expression overwrite `'unknown'` → `'watchdog_subprocess_hang'` для legacy случаев когда первые 2 фикса не сработали.

### Triad 2 — Layer 1+2+3 silent hangs (CLOSED)

`ig_2_profile_tab_fg_guard` 181 fail/неделю с empty error_code. Три уровня:

- **Layer 1** (`165a493`): server.js watchdog теперь пишет error event в events JSONB + SET error_code напрямую. Раньше Python `_set_error_code_from_events` не вызывался (subprocess мёртв). Live evidence 2026-05-04: 6 hangs за 06:00-08:00 UTC получили `error_code='watchdog_subprocess_hang'`.
- **Layer 2** (`130ded4`): set_step после `_open_app` (`_tap_phase`) + в `_read_screen_hybrid` (`switcher: <step>`). Stale step name `_fg_guard` через всю post-`_open_app` фазу больше не держится. Live evidence: task #2952 показал `yt_5_post_switch_to_profile_tap_phase`.
- **Layer 3** (`69cf64b` + `f5ac8c7`): root cause = `except Exception` не ловит BaseException. Original hypothesis (frozen subprocess) была неверна — subprocess exits cleanly без UPDATE status.

### Triad 3 — caption/title/description reliability (CLOSED)

Текстовый ввод теперь надёжен на всех 3 платформах (IG, TT, YT):

- **Root cause** (PR #15 `eaf724c` 2026-05-03 ранее): `adb_utils.adb_text` → `ADB_INPUT_B64` instead of `ADB_INPUT_TEXT`. Base64 alphabet shell escape невозможно сломать.
- **IG defense** (`ebd52f0`, `ef25d98`, `8303047` 2026-04-30 + 05-03 ранее): caption verify + surgical focus + tight retry.
- **YT defense** (`934d7aa` сегодня): title/description verify + structured logging (yt_<label>_filled / yt_<label>_fill_failed). Carry-over from IG pattern.

## W3 obstacle KB framework — complete code-side

5 фаз отгружены в shadow mode. Ничего не активируется автоматом.

- W3.1 (`4cc16aa`): Anthropic vision provider через VISION_PROVIDER env switch.
- W3.2 (`107adc0`): `_kb_unstuck_shim` в ai_unstuck — probe always, apply when not lookup_only.
- W3.3 (`49cb621`): post-LLM auto-learn experimental obstacles, gated на `obstacle_kb_learn_disabled`.
- W3.4 (skipped): уже wired в IG/TT/YT.
- W3.5 (`93ad8ea`): KB pre-check в `_force_clean_restart_via_recents`.

W4 cutover (3 sequenced flips) — backlog для следующих сессий после soak.

## W5 — Promoter готов, не активирован

- Task 28 (`8d0a214`): obstacle_promoter.tick() с T1/T2/T3 logic. Kill-switch off → tick() returns zeros.
- Task 30 (`e71657a`): wire через server.js setInterval(1h) execFile python3 obstacle_promoter.py.
- Task 29 (Telegram bot handlers) — отдельный repo, backlog.
- Task 31 (B2 mining) — нужна live Sonnet 4.6 vision quality, backlog после Flip 2/3.

## Layer 1 evidence (live)

Round 2 testbench tasks (2957-2960) с активным fix:
- 4/4 → `error_code='adb_push_chunked_failed'` (правильная категория)
- Round 1 (до фиксов) tasks 2953/2954 имели `error_code='unknown'`.

## Test coverage

**79 новых тестов**, all TDD RED→GREEN:
- test_switcher_step_progress (3) — Layer 2
- test_vision_provider_switch (6) — W3.1
- test_kb_unstuck_shim (8) — W3.2
- test_kb_learn_from_unstuck (9) — W3.3
- test_kb_pre_recents_shim (6) — W3.5
- test_obstacle_promoter (10) — W5 Task 28
- test_publisher_baseexception_handling (4) — Layer 3 root cause
- test_yt_text_fill_verification (12) — YT carry-over
- test_ig_editor_timeout_meta (10/10 updated) — IG #6+#7

Pre-existing baseline 1 fail в test_publisher_ig_camera_recovery.py (MagicMock issue, не моя регрессия).

## Open backlog для следующих сессий

| # | Что | Priority |
|---|---|---|
| W4 Flip 2 | `obstacle_kb_learn_disabled=false` | medium — после soak Flip 1 |
| W4 Flip 3 | `obstacle_kb_lookup_only=false` (apply mode) | high — main goal of W3 framework |
| W5 Task 29 | Telegram bot handlers | medium — отдельный repo `contenthunter_bugs_bot` |
| W5 Task 31 | B2 mining `mine_events` | medium — после Flip 1 vision quality validate |
| W6 | Admin UI `obstacles.html` + 5 endpoints | low |
| IG account audit | 8 проблемных IG accounts | medium — manual discovery |
| ADB packet loss | VPS↔proxy hop 4 throughput 0.1 MB/s | high — INFRA, вне моего scope |
| `farm#*` 401 | farming uses old OAuth Anthropic key | low — отдельный env file |
| Pre-existing test fails | test_publisher_ig_camera_recovery + test_publish_guard | low |

## PM2 reload counts

- prod autowarm: #241 → #254 (13 reloads)
- testbench: #15 → #21 (6 reloads)
- All 19 reloads: 0 unstable restarts

## Memory updates

- `project_publisher_obstacle_kb.md` — W3 ship + W4 cutover sequence
- `project_ig_switch_silent_hang_backlog.md` — Layer 1+2+3 closed
- `project_obstacle_promoter.md` — new file, W5 Task 28 status
- `project_ig_caption_fill_persistent_bug.md` — отсылка на YT carry-over
- `project_publisher_modularization_wip.md` — backlog updates
- `MEMORY.md` — index updated

Evidence references:
- `silent-hangs-discovery-20260504.md` — Layer 1+2+3 root cause analysis
- `session-2026-05-04-publisher-stack-hardening.md` (this file) — final summary
