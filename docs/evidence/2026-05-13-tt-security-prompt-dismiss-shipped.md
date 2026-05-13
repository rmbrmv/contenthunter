# TT `Быстрая проверка безопасности` dismiss — SHIPPED ✅ 2026-05-13

**PR:** [GenGo2/delivery-contenthunter#50](https://github.com/GenGo2/delivery-contenthunter/pull/50)
**Squash-merge commit:** `c4a8406a82a3934fcc6db91ee24802a851507f4b`
**Merged at:** 2026-05-13 13:24:44 UTC
**Deployed to prod tree:** `/root/.openclaw/workspace-genri/autowarm/` via `git pull --ff-only` (fast-forward `7b3e5f6..c4a8406`)
**PM2 restart:** not required (publisher.py spawned subprocess-per-task by server.js)

**Spec:** `docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md` (commit `c9282da41`)
**Plan:** `docs/superpowers/plans/2026-05-13-tt-security-prompt-dismiss-plan.md` (commit `39a432853`)

## What

Two edits to `account_switcher.py`, plus two new test files:

- **Edit 1** — new helper `_tt_dismiss_security_prompt(ui_xml) -> bool` at `account_switcher.py:1922`. Locale-restricted: requires BOTH the bottom-sheet desc `Нижняя шторка` AND the title text `Быстрая проверка безопасности`. Taps the top-right `Закрыть` close-X button (not `Продолжить`, which would engage the security flow). Robust against empty/malformed XML, missing markers, non-clickable close, malformed bounds, and adb exceptions.

- **Edit 2** — wiring at the TOP of `_switch_tiktok`'s retap loop (lines ~2071-2080), BEFORE all state classifiers. If dismiss returns True: log `tt_security_prompt_dismissed`, sleep ~POST_TAP_WAIT_S + 0.5s for the animation, and re-probe `dump_ui` so `_tt_is_own_profile` / `_tt_is_logged_out` / `_tt_is_reauth_prompt` / `_tt_is_foreign_profile` see the post-dismiss screen.

The "before all classifiers + re-probe" ordering is the codex P2 fix from round 1: a prior version of the wiring put dismiss AFTER `_tt_is_own_profile`, which would miss the case where the prompt is a bottom-sheet over the profile (underlying own-profile markers still in the dump → own_profile=True → loop breaks → downstream switcher steps run against the still-visible prompt).

## Why

`tt_profile_tab_broken` emerged as a brand-new TT failure pattern on 2026-05-13:

| Day | Count |
|---|---:|
| 2026-05-06 to 2026-05-12 | 0 |
| 2026-05-13 (pre-deploy, 9h) | 5 (projected ~13/day) |

Distribution: 4 raspberries × 5 distinct devices — systemic.

UI-dump inspection of the latest failure (task 5319, ~52596 → 8804-byte collapse) confirmed the failure mode:

| Class | Bounds | Clickable | Text/Desc |
|---|---|---|---|
| `FrameLayout` | `[0,1266][1080,2205]` | false | desc=`Нижняя шторка` (Bottom sheet) |
| `Button` | `[945,1277][1058,1401]` | **true** | desc=`Закрыть` (Close X) |
| `TextView` | `[90,1682][990,1834]` | false | text=`Быстрая проверка безопасности` |
| `TextView` | `[90,1834][990,1946]` | false | text=`Повысьте безопасность своего аккаунта с ...` |
| `Button` | `[45,2016][1035,2160]` | true | text=`Продолжить` (Continue) |

TikTok shows an anti-automation security prompt that covers the profile screen entirely. The existing retap loop just re-taps the profile tab — that tap lands on the same prompt overlay, so nothing changes. After 3 retries the flow fails as `tt_profile_tab_broken`.

The Закрыть close-X is a structurally distinct control that dismisses the prompt without engaging the security flow. If TT accepts it (high confidence based on standard Android bottom-sheet semantics), the underlying profile screen reappears and the existing retap loop's per-iteration probe finds own-profile markers naturally.

## How

- **8 helper unit tests** in `tests/test_tt_security_prompt_dismiss.py` cover locale, anti-false-positive (both markers required), clickable guard, empty XML, malformed bounds, adb exception swallow, missing close button. All RED with `AttributeError` pre-Edit-1, all GREEN after.
- **2 integration tests** in `tests/test_tt_profile_tab_retap_security.py` exercise the actual `_switch_tiktok` retap loop with mocked dump_ui sequences: rescue path (prompt → dismiss → re-probe → own_profile → break) and anti-regression (no prompt → no dismiss + no event). 1 RED + 1 baseline-PASS before, both GREEN after.
- The integration test fixture needed extra mocks (`_ensure_app_foregrounded`, `_ensure_foreground`) to satisfy `_switch_tiktok`'s prelude foreground guards — these were added in Task 5 alongside the wiring commit.
- Existing TT switcher suite (`tests/test_account_switcher_tt.py` + `tests/test_account_switcher.py`) remained 83/83 GREEN through every commit.

### Codex review history

| Round | Artifact | Findings | Outcome |
|---|---|---|---|
| spec round 1 | design doc | 0 findings | Clean |
| plan round 1 | implementation plan | 0 findings | Clean |
| PR diff round 1 | full cumulative diff | 1 P2 (dismiss ordering before state classifiers) | Restructured wiring + re-probe; commit `fc3de4c` |
| PR diff round 2 | post-fix diff | 0 findings | Clean |

All gating per [[feedback_codex_review_specs]] (0 P1 across all artifacts) met. P2 was non-blocking but fixed inline for design integrity.

## Baseline (pre-deploy, 2026-05-13 12:00 UTC)

```
tt_profile_tab_broken (24h): 5 (in 9h pre-deploy; projected ~13/day)
Distribution: 4 raspberries × 5 distinct devices — systemic
0 occurrences across 2026-05-06 to 2026-05-12 (entirely new pattern)
```

Out-of-scope same-day patterns (will need separate spec/plan):
- `tt_account_sheet_closed_before_parse` (19/24h, profile-screen layout change → `_tap_profile_header` lands on video preview card)

## Acceptance criteria

- ✅ All 10 new tests (8 helper + 2 integration) GREEN.
- ✅ Existing TT switcher suite remains 83/83 GREEN.
- ✅ Codex on spec → 0 findings.
- ✅ Codex on plan → 0 findings.
- ✅ Codex on PR diff → 0 P1 (round 1 P2 fixed in round 2 = 0 findings).
- ⏳ **24h post-deploy (2026-05-14 ≥ 13:25 UTC): `tt_profile_tab_broken < 2 / 24h` AND `tt_security_prompt_dismissed > 0`** — see "24h verify" section below.

## 24h verify (run at 2026-05-14 ≥ 13:25 UTC)

```sql
-- 1. Dismiss helper fire rate
SELECT COUNT(*) FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'tt_security_prompt_dismissed'
  AND pt.created_at >= '2026-05-13 13:25:00+00';

-- 2. tt_profile_tab_broken drop (baseline 5 in 9h, projected ~13/day pre-fix)
SELECT COUNT(*) FROM publish_tasks
WHERE error_code='tt_profile_tab_broken'
  AND testbench=false
  AND created_at >= '2026-05-13 13:25:00+00';

-- 3. Rescue rate (dismiss fired AND task completed)
WITH dismissed AS (
  SELECT pt.id, pt.status
  FROM publish_tasks pt,
       jsonb_array_elements(pt.events) e
  WHERE e->'meta'->>'category' = 'tt_security_prompt_dismissed'
    AND pt.created_at >= '2026-05-13 13:25:00+00'
)
SELECT
  COUNT(*) AS dismissed_total,
  COUNT(*) FILTER (WHERE status = 'done') AS rescued,
  ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'done') / NULLIF(COUNT(*),0), 1) AS pct
FROM dismissed;

-- 4. Spike-check (catch shifted failure modes)
SELECT error_code, COUNT(*) FROM publish_tasks
WHERE platform='TikTok' AND status='failed' AND testbench=false
  AND created_at >= '2026-05-13 13:25:00+00'
GROUP BY error_code ORDER BY 2 DESC LIMIT 10;
```

### Acceptance bands

- **`tt_profile_tab_broken < 2 / 24h` AND `tt_security_prompt_dismissed > 0`** → 🎯 close; fix successful.
- **`tt_security_prompt_dismissed > 0` AND rescue rate < 30%** → keep but iterate.
- **`tt_security_prompt_dismissed == 0` AND `tt_profile_tab_broken` unchanged** → design premise wrong; investigate.
- **New TT error_code spike** > 5 / 24h → document follow-up.

## Rollback plan

Single `git revert <merge-commit>` on `rmbrmv/contenthunter` main; auto-push hook deploys revert. No DB migration, no flag, no PM2 state. Rollback time: minutes.

## Related memory

- [[reference_tt_activities_observed]] — TT activity landscape baseline
- [[feedback_ui_automation_edge_cases]] — universal banner pre-dismiss pattern precedent
- [[project_revision_phone171_backlog]] — TT-stuck-state context (its hypothesis may now be partially related to security prompts)
- [[feedback_codex_review_specs]] — codex review rule applied
- [[feedback_silent_crash_layered]] — TT outage today had multiple layers; this PR closes one of them
- [[project_watchdog_ping_regression_shipped]] — sibling P1 closed earlier same day (PR #48)
- [[project_ig_share_ok_fallback_shipped]] — sibling P1 closed earlier same day (PR #49)
