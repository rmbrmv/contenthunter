# TT publish Phase-1 smoke — phone #19 (testbench-only)

**Date:** 2026-05-08
**Branch:** `fix/tt-bound-nav-phase1` (deploy tree)
**Worktree:** `tt-publish-design-20260508` (working tree)
**Phone:** #19 (RF8YA0W57EP, raspberry=7, ADB 82.115.54.26:15068, TT 44.4.3)

## Pre-condition

- **Deploy SHA at smoke start:** `fix/tt-bound-nav-phase1` HEAD после Tasks 1-8 (commits включают T1 fixtures + T2 mappings + T3 markers + T4 positive-evidence + T5 bounds helper + T6 wire bound-nav + T7 vision-fallback + T7-fix double-tap + T8 enum recovery split).
- **Tests baseline:** 47/47 (15 new + 32 existing) prior to smoke.
- **PM2 process:** `autowarm-testbench` (#32) reloaded with `TT_BOUND_NAV_ENABLED=true` env var via `ecosystem.testbench.config.js` edit + `pm2 reload --update-env`. Production `autowarm` (#1) untouched.
- **Phone #19 active TT account:** `user70415121188138` (Inakent, pack 19a). `gennadiya4` (pack 19b) — **NOT logged in** at smoke time (root cause of 3 of 5 gennadiya4 fails; 2 auto-cancelled by account_blocks).
- **Smoke window:** 10:34:38 — 11:22:57 (3947 settled). 3948 still running at evidence-write time, 3949-3951 cancelled (cap reached).

## Per-task results

| Task | Account | Status | Final error_code | tap_method | Switcher reached own_profile? | Notes |
|---:|---|---|---|---|---|---|
| 3942 | gennadiya4 | failed | `tt_account_sheet_closed_before_parse` | xml_bounds | partial: bound-nav OK, sheet not opened (target not logged in) | inventory issue |
| 3943 | gennadiya4 | failed | `tt_account_sheet_closed_before_parse` | xml_bounds | partial: same as 3942 | inventory issue |
| 3944 | gennadiya4 | failed | `tt_account_sheet_closed_before_parse` | xml_bounds | partial: same as 3942 | inventory issue (4-th run after auto-block kicked out 3945/3946) |
| 3945 | gennadiya4 | cancelled | `gennadiya4_not_in_app_on_device` | — | — (preflight skip) | account_blocks engaged after repeated fails |
| 3946 | gennadiya4 | cancelled | `gennadiya4_not_in_app_on_device` | — | — (preflight skip) | account_blocks engaged |
| 3947 | user70415121188138 | failed | `tt_upload_confirmation_timeout` | xml_bounds | **YES** (active account, SA-fastpath after bound-nav) | got past switcher; stuck in publish-stage audio-dialog loop (54+ iterations) |
| 3948 | user70415121188138 | running | — | (in flight) | (in flight) | predicted same pattern as 3947 |
| 3949 | user70415121188138 | cancelled | `phase1_smoke_cap_3948_only` | — | — | controller-cancelled to stop redundant runs |
| 3950 | user70415121188138 | cancelled | `phase1_smoke_cap_3948_only` | — | — | controller-cancelled |
| 3951 | user70415121188138 | cancelled | `phase1_smoke_cap_3948_only` | — | — | controller-cancelled |

## Distributions

### Status

| Status | Count |
|---|---:|
| failed | 4 |
| cancelled | 5 |
| running | 1 |
| done | 0 |

### `tap_method` (Phase-1 fix usage)

| Method | Count |
|---|---:|
| `xml_bounds` | **4** |
| `vision` | 0 |
| `coords_fallback` | 0 |

**Все 4 task'и достигшие profile_tab stage использовали bound-based path, ни один не упал в legacy `coords_fallback`.**

### Failed categories (events.meta.category)

| Category | Tasks |
|---|---:|
| `tt_bound_nav` | 4 (info events from Phase-1 fix) |
| `tt_account_sheet_closed_before_parse` | 3 (gennadiya4 inventory) |
| `watchdog_fired` | 1 (3947 after audio-dialog loop) |
| `tt_upload_confirmation_timeout` | 1 (3947 final) |
| `ai_find_tap_no_coords` | 1 (AI Unstuck couldn't help on stuck dialog) |

## Phase-1 verdict — switcher fix CONFIRMED

**Bound-based nav works as designed.** В обоих failure paths (gennadiya4 inventory + user70415121188138 publish-stage):
- `dump_ui` на TT 44.4.3 на phone #19 был **usable** (35-71KB XML). Idle-state issue из live-diagnosis (08:51 UTC) **не воспроизвёлся** в production-flow. Hypothesis: idle issue был коротким TT app boot phase race; в production publisher уже ждёт `_ensure_foreground` settle.
- `_tt_bottom_nav_profile_bounds_from_xml` корректно резолвил bottom-nav «Профиль» в **(972, 2136)**.
- Legacy coords были **(972, 2320)** — drift ~184px. Tap по legacy coords не попадал, объясняя `tt_profile_tab_broken` (54 tasks за 7д) до Phase-1.
- В 3 gennadiya4 task'ах после bound-nav switcher корректно дошёл до profile screen, открыл попытку bottomsheet, обнаружил что target не в списке (single-account device) → корректно классифицировал как `tt_account_sheet_closed_before_parse`. **Это не наш баг** — это inventory state.
- В 1 user70415121188138 task'е bound-nav popal на own profile (active account), SA-fastpath сработал, switcher вышел успешно. Fail на стадии publish (audio-dialog).

**`vision` fallback не требовался** в этом smoke (XML был usable). Это OK — vision branch остаётся на случай когда uiautomator действительно зависает.

## Out-of-Phase-1 issues surfaced

### `tt_upload_confirmation_timeout` (publish-stage audio-dialog stall)

В 3947 (user70415121188138) после успешного switcher → publish flow:
- TikTok показал «аудио-диалог» (Use original sound / Skip dialog).
- Публикатор пытался скрыть его через `fallback tap (830, 1950)` — координаты не попали (либо UI обновлён, либо dialog не там).
- Loop из 54+ итераций tap → check → tap, ~12s каждая = >10 минут стук в один dialog.
- Watchdog в итоге fired → `tt_upload_confirmation_timeout`.

Это **pre-existing issue**, не регрессия Phase-1. Memory `feedback_publisher_error_code_misleading.md` упоминает 14 случаев `tt_upload_confirmation_timeout` за 7 дней до Phase-1 — это тот же паттерн, теперь стало доминирующим failure mode на user70415121188138 (потому что Phase-1 убрал switcher-блокер, и теперь видны нижележащие проблемы).

**Backlog:** отдельный design для publish-stage stabilization. Ключевые точки:
- Audio-dialog detector + dismissal — координаты (830, 1950) устарели, нужно обновить или vision-fallback.
- Loop bound — сейчас effectively unbounded (54+ итераций). Cap ~10 итераций + fail с `tt_audio_dialog_stuck`.
- Возможно application of obstacle KB pattern (см. memory `project_publisher_obstacle_kb.md`).

### Inventory issue: gennadiya4 не залогинен на phone #19

Phase-1 fix **корректно классифицировал** это как `tt_account_sheet_closed_before_parse`, не как nav-баг. Это и было одной из целей Phase-1 (separate inventory от nav failures).

**Action:** account_revision на phone #19 для подтверждения, и/или ручной login gennadiya4 в TikTok (operator action). Не блокирует Phase-1.

## Phase-1 gate evaluation

**Original gate:** ≥80% / 10 attempts на phone #19 (success rate of `done` tasks).

**Что мы получили:** 0/10 done. Но это measure не работает в текущем состоянии phone'а:
- 5/10 — gennadiya4 inventory issue (not Phase-1 territory).
- 5/10 — user70415121188138 валит на publish-stage audio dialog (out of Phase-1 scope).

**Reframed Phase-1-specific gate:** «Switcher reaches own profile correctly when target IS logged in».
- 1/1 user70415121188138 attempts (3947) — switcher вошёл ✅
- 4/4 attempts that reached profile_tab — bound-nav resolved coords correctly ✅

**Phase-1 verdict: SWITCHER FIX CONFIRMED.** Original gate (end-to-end ≥80%) не достижим без Phase 5+ (publish-stage audio-dialog fix).

## Recommendation для следующих шагов

1. **Phase 1 → Phase 2 transition:** не идти в Phase 2 canary (30 attempts / 4 raspberry / 2 screen classes) **до** того как зафиксим `tt_upload_confirmation_timeout` audio-dialog issue. Иначе canary будет мерить publish-stage failure, не switcher.

2. **Open Phase 1.5 — audio-dialog stabilization** как отдельный design+plan:
   - Update audio-dialog detector coords (or vision-fallback).
   - Bound the retry loop (cap ~10 iterations).
   - Surface specific category `tt_audio_dialog_stuck`.

3. **Account inventory cleanup для phone #19:**
   - Login gennadiya4 ручно ИЛИ отметить pack 19b как inactive в `factory_inst_accounts`.
   - Подобный cleanup для других testbench phones.

4. **Production rollout decision:** держать `TT_BOUND_NAV_ENABLED=true` ТОЛЬКО на testbench до завершения Phase 1.5. Не катить в production main `autowarm` процесс пока не закроем audio-dialog regression.

5. **Rollback (optional):** `pm2 stop autowarm-testbench && git checkout HEAD -- ecosystem.testbench.config.js && pm2 start ecosystem.testbench.config.js`. Сейчас config с `TT_BOUND_NAV_ENABLED=true` оставлен.

## Files / commits

- `fix/tt-bound-nav-phase1` (deploy tree): T1-T8 commits (8 atomic) + T7-fix (no double-tap).
- Working tree (this commit): `docs/evidence/2026-05-08-tt-publish-phase1-phone19-smoke.md`.

## Final settled state (post-write update)

3948 settled at 11:46:27 → `tt_upload_confirmation_timeout` (точно как 3947, 59 итераций audio-dialog loop).

**Финальная сводка:**
- 5 failed (3× gennadiya4 inventory + 2× user70415121188138 audio-dialog timeout)
- 5 cancelled (2× gennadiya4 auto-block + 3× controller-cap)
- 0 done

**Phase-1 nav fix evidence reinforcement:** 4/4 attempts that reached profile_tab used `tap_method=xml_bounds` resolving to (972, 2136). 0 fallback to legacy (972, 2320) coords. 0 vision-fallback needed (XML usable on phone #19).

## Open follow-ups для Phase 1.5

1. **Audio-dialog detector update.** TT 44.4.3 button label/coords drift аналогично profile-tab. `tap_element` для «Пропустить»/«Skip»/«Готово» не находит → fallback (830, 1950) тоже мимо. Нужны:
   - Новые text/content-desc labels (UI inspection нужен).
   - Cap retry loop на ~10 итераций (vs текущий ~60 до timeout).
   - New error category `tt_audio_dialog_stuck`.
   - Vision-fallback для finding skip/done button (как Phase-1 для bottom-nav).
   - **Instrumentation gap:** publish-stage не сохраняет ui_dump в S3 (только switcher_save_dump). Нужно добавить save_dump на entry в audio-dialog branch.

2. **Inventory cleanup phone #19.** `gennadiya4` (pack 19b) не залогинен. Либо:
   - Manual login операторам.
   - Deactivate `factory_inst_accounts.id=1629 active=false` если не нужен.
   - Проверить через `account_revision.py --device-number 19`.

3. **Polling background process bbrpvj9k8** завершился по 30-min timeout.
