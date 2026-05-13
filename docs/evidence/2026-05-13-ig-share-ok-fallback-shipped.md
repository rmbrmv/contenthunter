# IG share `action_bar OK` fallback — SHIPPED ✅ 2026-05-13

**PR:** [GenGo2/delivery-contenthunter#49](https://github.com/GenGo2/delivery-contenthunter/pull/49)
**Squash-merge commit:** `7b3e5f62c156ee5d7f4a707df5598330626dd04b`
**Merged at:** 2026-05-13 11:45:34 UTC
**Deployed to prod tree:** `/root/.openclaw/workspace-genri/autowarm/` via `git pull --ff-only` (fast-forward from `ec91909`)
**PM2 restart:** not required (publisher.py spawned subprocess-per-task by server.js)

**Spec:** `docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md` (commits `f00545613`, `c0b36ae05`)
**Plan:** `docs/superpowers/plans/2026-05-13-ig-share-ok-fallback-plan.md` (commit `8d900588f`)

## What

Three edits, all in `publisher_instagram.py`, plus two new test files:

- **Edit 1** — new helper `_tap_ig_action_bar_ok(ui_xml) -> bool` at `publisher_instagram.py:944` next to `_long_press_share_button`. Finds `action_bar_button_text` resource-id with text/desc in `{'ОК', 'OK'}` and clickable=true → dispatches `input tap` at node centre. Robust against empty/malformed XML, missing label, non-clickable node, malformed bounds, adb exceptions.
- **Edit 2** — Tier 1.5 wiring in `_wait_instagram_upload` at lines 2670-2685, inserted between the share-button retry loop and the existing fail-fast emit. Gates on `not progressed and self._is_ig_editor_still_visible(...)` so it only fires when the share retries already failed. `ok_tap_dispatched` local flips True only when the helper actually dispatched a tap.
- **Edit 3** — `meta.ok_fallback_attempted` on the existing `ig_share_tap_no_progress` event, set from `ok_tap_dispatched`. Distinguishes "OK tap dispatched but didn't rescue" from "helper aborted (no match / no clickable / etc.)" in the 24h rollout query.

New event-category `ig_share_ok_button_attempted` (info) emitted whenever the OK tap is dispatched.

## Why

`ig_share_tap_no_progress` was the top Instagram failure pattern as of 2026-05-13:

| Day | Count |
|---|---:|
| 2026-05-09 | 1 |
| 2026-05-10 | 2 |
| 2026-05-11 | 4 (PR #31 merged 09:50 UTC — added Tier 2 long-press) |
| 2026-05-12 | 18 (full day post-PR #31; PR #37 reverted Tier 2 at 12:27 UTC, 0/19 rescue) |
| 2026-05-13 (pre-deploy, 9h) | 11 (projected ~30/day) |

Distribution at the 24h sample: 11 fails across 8 raspberries and 11 distinct devices — systemic, not device-specific.

UI-dump inspection of 5 fresh failing tasks (5208, 5215, 5220, 5237, 5277) showed every failure was stuck on the standard Reels editor screen (`com.instagram.modal.ModalActivity` + `caption_input_text_view` + `action_bar_title='Новое видео Reels'`) with the share button clickable and at the expected coordinates. **IG silently ignores the tap.** Re-tapping the same button — Tier 1's strategy — never helps. PR #31's Tier 2 long-press (same button, different gesture) rescued 0/19 and was reverted.

The action-bar `OK` button at the top-right of the same screen is a structurally distinct control. If IG accepts it where it ignores `share_button`, rescue rate will be positive. The acceptance band is `ok_rescued_24h / ok_attempted_24h ≥ 30%`.

## How

- **8 helper unit tests** in `tests/test_ig_share_ok_fallback.py` cover locale (RU/EN), clickable guard, locale-restriction (rejects `Готово`), empty XML, malformed bounds, adb exception swallow, and no-match returns False. All RED with `AttributeError` pre-Edit-1, all GREEN after.
- **3 integration tests** in `tests/test_publisher_instagram_share_retry.py` cover the Tier 1.5 wiring: rescue path (OK helper succeeds → editor disappears → progressed → no fail event), no-rescue path (OK helper dispatches but editor stays → fail event with `ok_fallback_attempted=True`), anti-regression (share retry progresses naturally → OK fallback NOT triggered, no event emitted). 2 RED before Edit 2, 1 PASS by accident as a baseline; all 3 GREEN after.
- Existing IG share suite (`test_share_retry_progresses_after_first_retry`, `test_share_retry_exhausted_emits_no_progress`) untouched and still GREEN.
- Full IG-suite run found 1 pre-existing failure (`test_reopen_via_home_taps_plus_then_reels_on_success_path` in a different code path); verified to fail on `origin/main` pre-this-PR, unrelated.

### Codex review history

| Round | Artifact | Findings | Outcome |
|---|---|---|---|
| spec round 1 | design doc | 1 P3 (ok_fallback_attempted flag conflated tap-dispatched with conditional-entered) | Fixed inline — added `ok_tap_dispatched` local boolean |
| plan round 1 | implementation plan | 0 findings | Clean |
| PR diff round 1 | full cumulative diff | 0 findings | Clean |

All gating per [[feedback_codex_review_specs]] (0 P1 across all artifacts) met.

## Baseline (pre-deploy, 2026-05-13 09:00 UTC)

```
ig_share_tap_no_progress / 24h (rolling): 11-18 (spiked 2026-05-12)
Distribution: 8 raspberries × 11 devices — systemic
5d trend: 1 → 2 → 4 → 18 → 11 (today, 9h in)
```

## Acceptance criteria

- ✅ All 11 new tests (8 helper + 3 integration) GREEN.
- ✅ Existing IG share suite remains GREEN.
- ✅ Codex on spec → 0 P1 (round 1).
- ✅ Codex on plan → 0 findings (round 1).
- ✅ Codex on PR diff → 0 findings (round 1).
- ⏳ **24h post-deploy (2026-05-14 ≥ 11:45 UTC): `ok_rescued_24h / ok_attempted_24h ≥ 30%`** — see "24h verify" section below.

## 24h verify (run at 2026-05-14 ≥ 11:45 UTC)

```sql
-- 1. Rescue rate (the primary acceptance metric)
WITH share_fails AS (
  SELECT id, status, events
  FROM publish_tasks
  WHERE platform='Instagram' AND testbench=false
    AND created_at >= '2026-05-13 11:45:34+00'
)
SELECT
  COUNT(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(events) e
    WHERE e->'meta'->>'category' = 'ig_share_ok_button_attempted'
  )) AS ok_attempted_24h,
  COUNT(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(events) e
    WHERE e->'meta'->>'category' = 'ig_share_ok_button_attempted'
  ) AND status = 'done') AS ok_rescued_24h,
  COUNT(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(events) e
    WHERE e->'meta'->>'category' = 'ig_share_tap_no_progress'
  )) AS still_failed_24h
FROM share_fails;

-- 2. Overall ig_share_tap_no_progress count (baseline 11-18/24h)
SELECT COUNT(*) FROM publish_tasks
WHERE error_code='ig_share_tap_no_progress'
  AND testbench=false
  AND created_at >= '2026-05-13 11:45:34+00';

-- 3. Spike-check (catch shifted failure modes)
SELECT error_code, COUNT(*) FROM publish_tasks
WHERE platform='Instagram' AND status='failed' AND testbench=false
  AND created_at >= '2026-05-13 11:45:34+00'
GROUP BY error_code ORDER BY 2 DESC LIMIT 10;
```

### Acceptance bands

- **`ok_rescued_24h / ok_attempted_24h ≥ 30%`** → 🎯 close; design successful.
- **10-30% rescue** → keep; document partial win; plan a Variant C (keyevent ENTER) follow-up.
- **`ok_attempted_24h > 0` and rescue < 10%** → revert + escalate. Right screen but wrong action; investigate AI-badge-side mitigation or alternating retries.
- **`ok_attempted_24h == 0`** → design premise wrong. Investigate why the helper never matches in prod (locale? resource-id changed? code path not reached?).

## Rollback plan

Single `git revert <merge-commit>` on `rmbrmv/contenthunter` main; auto-push hook deploys the revert. No DB migration, no flag, no PM2 state. Rollback time: minutes.

## Related memory

- [[project_ig_share_tier2_design]] — PR #31 (Tier 2 long-press) — context for prior attempt
- [[project_ig_share_regression_post_pr31_2026_05_12]] — PR #37 (revert) — spike that motivated this PR
- [[feedback_publish_fail_analysis_video_first]] — the triage discipline that surfaced the editor-screen evidence
- [[feedback_codex_review_specs]] — codex review rule applied at every artifact
- [[feedback_ui_dump_app_recognition]] — caution against trusting step names without UI verification
- [[project_watchdog_ping_regression_shipped]] — sibling P1 fix shipped earlier same day (PR #48)
