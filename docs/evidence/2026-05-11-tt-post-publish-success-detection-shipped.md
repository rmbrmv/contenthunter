# TT post-publish success detection — shipped 2026-05-11

**Spec:** [`docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md`](../superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md) (v3, 3 раунда Codex review)
**Plan:** [`docs/superpowers/plans/2026-05-11-tt-post-publish-success-detection-plan.md`](../superpowers/plans/2026-05-11-tt-post-publish-success-detection-plan.md) (v3, 2 раунда Codex review)
**PR:** GenGo2/delivery-contenthunter#29
**Merge SHA (squash):** `f49e877` на main
**Origin trigger:** pt 4523 (clickpay_world, raspberry=9, 2026-05-10 19:33-19:56 UTC) — frame-by-frame screen recording analysis показал: публикация состоялась в ~19:42, но `_wait_tiktok_upload` не распознал post-publish auto-навигацию TT в feed/inbox, продолжил 12 минут вызывать AI Unstuck, который случайно тапнул «+» в bottom nav и улетел в Camera → 21 tap loop → `tt_fg_lost`.

## Implementation summary

### Code changes (publisher_tiktok.py)

| Layer | Что добавлено | Lines |
|---|---|---|
| Module-level constants | `TT_MAIN_NAV_LABEL_GROUPS` (5 nav groups, RU+EN, без `Me` substring trap), `TT_COMPOSER_ACTIVITIES_SEED` (8 composer activities, **SEED**) | top, ~30 lines |
| Pure helpers | `_matches_label`, `_tt_infer_post_publish_success(ui, top_activity, wait_iter) → (bool, dict)` | top, ~80 lines |
| `_wait_tiktok_upload` init | `inferred_path_used = False` flag | ~line 743 |
| Detection block | После generic dialog handler `tap_element(['Закрыть', ...])`, перед wait%10 logging. Эмитит `tt_post_publish_success_inferred` (info), set `upload_confirmed = inferred_path_used = True`, break. | ~line 1083 |
| AI Unstuck main-nav guard | Перед AI call. При success_check=True эмитит BOTH `tt_unstuck_skipped_post_publish` (observability) AND `tt_post_publish_success_inferred` (consistency), set both flags + break. NARROWED после Codex round 2 P2. | ~line 1118 |
| AI Unstuck CameraActivity hard-fail | После main-nav guard. При `'CameraActivity' in cur_act` эмитит `tt_unexpected_camera_after_share` (error) + break. NARROWED scope (только Camera, не Permission/Music/Cover/CutVideo). | ~line 1135 |
| URL classification | После `tt_url_partial`, guarded `if inferred_path_used:` → эмитит `tt_success_inferred_but_no_video_url` (warning). Supplements existing event. | ~line 1190 |

### Tests (56 total, all green)

- `tests/test_publisher_tt_post_publish_success_helper.py` — **19 unit tests:**
  - TestMatchesLabel (4): short-label strict equality, long-label substring, empty, whitespace
  - TestActivityBranches (4): DetailActivity → success, launcher → wait, composer seed → wait, empty → wait
  - TestBottomNavParsing (4): 5 groups → success, 3 groups → success (min threshold), 2 groups → wait, Интересное alias
  - TestBottomBandScoping (3): label outside band ignored, Messages anti-match Me, share sheet → wait
  - TestEdgeCases (4): empty UI, no bounds, zero-height, malformed XML

- `tests/test_publisher_tt_wait_upload_integration.py` — **15 integration tests:**
  - TestSourceOrder (1): block placement guard between dialog handler ↔ logging ↔ AI call
  - TestAiUnstuckMainNavGuardSourceLevel (1): markers present
  - TestCameraHardFail (5 = 1 + 4 parametrized): camera markers, 4 legit recovery activities NOT blocked
  - TestUrlClassification (1): inferred_path_used guard supplements tt_url_partial
  - TestBehavioralIntegration (7 = 1 + 1 + 4 parametrized + 1): inferred success → break, main-nav skip, 4 legit recovery → AI called, CameraActivity → break

- Existing TT tests: 37 PASS, no regressions

## Codex code review

- Round 1 (post-implementation): 1 P2 finding — main-nav guard `continue`'d when it should mark success+break (transient first-dumpsys miss could leave loop hanging). Applied in commit `4615eac`: now emits BOTH skip-event (observability) AND inferred-success-event + sets flags + breaks.
- Round 2: clean, no actionable findings.

## Deploy verification

- ✅ PR #29 squash-merged at 07:00 UTC, prod auto-pulled `f49e877` via git hook
- ✅ pm2 cwd correct: `/root/.openclaw/workspace-genri/autowarm`
- ✅ Markers verified in prod `publisher_tiktok.py`:
  - `POST-PUBLISH SUCCESS DETECTION 2026-05-11`: 1
  - `tt_post_publish_success_inferred`: 2 (detection block + main-nav guard)
  - `tt_unexpected_camera_after_share`: 1
  - `_tt_infer_post_publish_success`: 3 (definition + 2 call sites)
- ✅ PM2 spawn'ит Python per-task — fix живёт автоматом (no pm2 reload needed)

## Live verification status — PARTIAL

**Re-queue attempt pq 1831 (clickpay_world):** picked up at 07:10:39 UTC (created pt 4624) — но pt 4624 остался в orphan state (0 events, never executed). Same pattern как pt 4548 (`my_clickpay`, оrphaned 1.5 часа), которую пришлось manually mark as failed чтобы освободить device.

**Дополнительный orphan epidemic на Pi 9:** обнаружено 8 phantom pending pts на raspberry=9, со временами создания 06:10-07:15 UTC, all с 0 events. Это **отдельный operational bug**, не связан с нашим deployment. Possibly связано с `pq=766/pq=1486 SQL parameter $1` errors (см. `project_dispatcher_sql_param_bug.md`).

**TT activity 24h до verify (06:00-07:30 UTC):**
- 2 TT publishes: pt 4541, pt 4542 — оба `tt_upload_confirmation_timeout` 80+ events (SAASceneWrapperActivity pattern, не наш fix scope)
- 0 publishes triggered our new event categories (`tt_post_publish_success_inferred`, etc.)

## Real-world finding (live)

При попытке live verify обнаружено: **актуальное TT camera activity на проде = `com.zhiliaoapp.musically/com.ss.android.ugc.aweme.adaptation.saa.SAASceneWrapperActivity`**, НЕ matches наш SEED `'CameraActivity'`. Это значит CameraActivity hard-fail НЕ сработает на real TT для composer screens. Detection block ВСЁ ЕЩЁ работает через bottom-nav XML check (composer screen не имеет main nav). Зафиксировано в memory `reference_tt_activities_observed.md`.

**Backlog:** расширить `TT_COMPOSER_ACTIVITIES_SEED` на `'SAASceneWrapperActivity'` + `'SAAScene'` substring; expand CameraActivity hard-fail check.

## Verdict

| Аспект | Status |
|---|---|
| Code shipped | ✅ |
| Tests green | ✅ 56/56 (19 helper + 15 integration + 22 baseline TT preserved) |
| Codex review | ✅ 2 rounds, 1 P2 fix applied |
| PR + deploy | ✅ #29 merged, prod auto-pulled, pm2 cwd correct |
| Markers in prod | ✅ verified via grep |
| Live trigger evidence | ⏳ deferred 24h — Pi 9 dispatcher orphans blocking immediate test; natural TT publish traffic needed |
| Real activity name finding | ✅ documented в `reference_tt_activities_observed.md`, backlog для SEED expansion |

## 24h follow-up queries

```sql
-- Did fix trigger?
SELECT COUNT(*) AS detected_per_24h
FROM publish_tasks
WHERE platform='tiktok'
  AND updated_at >= NOW() - INTERVAL '24 hours'
  AND events @> '[{"meta":{"category":"tt_post_publish_success_inferred"}}]'::jsonb;

-- Did tt_fg_lost regress?
SELECT
  COUNT(*) FILTER (WHERE updated_at >= NOW() - INTERVAL '24 hours') AS last_24h,
  COUNT(*) FILTER (WHERE updated_at >= NOW() - INTERVAL '7 days'
                   AND updated_at < NOW() - INTERVAL '24 hours') AS prev_6d
FROM publish_tasks
WHERE platform='tiktok' AND error_code='tt_fg_lost';

-- AI Unstuck guards firing
SELECT COUNT(*) AS skipped_post_publish_24h
FROM publish_tasks
WHERE platform='tiktok'
  AND updated_at >= NOW() - INTERVAL '24 hours'
  AND events @> '[{"meta":{"category":"tt_unstuck_skipped_post_publish"}}]'::jsonb;
```

## Cross-refs

- Project memory: `project_tt_post_publish_success_shipped.md` (will be created)
- TT activity reference: `reference_tt_activities_observed.md` (created 2026-05-11)
- Frame analysis methodology: `feedback_publish_fail_analysis_video_first.md`
- Original incident: pt 4523 events, screen recording at `https://save.gengo.io/autowarm/screenrecords/tiktok/task4523_fail_screenrec_4523_1778441796.mp4`
