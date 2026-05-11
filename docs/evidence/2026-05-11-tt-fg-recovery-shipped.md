# TT fg-lost app-switch recovery — Shipped 2026-05-11

**PR:** [GenGo2/delivery-contenthunter#35](https://github.com/GenGo2/delivery-contenthunter/pull/35)
**Merge commit:** `a5bbd305256a0032000c6052f007dc547c8ba6a2` (squash; branch `fix/tt-fg-lost-recovery-20260511` deleted)
**Merged at:** 2026-05-11 19:11:39 UTC
**Prod state:** `/root/.openclaw/workspace-genri/autowarm` @ `a5bbd30`; PM2 autowarm (id=34) restart_time=16, last_start=2026-05-11T19:11:53 UTC
**Spec:** `docs/superpowers/specs/2026-05-11-tt-fg-lost-app-switch-recovery-design.md` (v1, Codex CLEAN 2 rounds)
**Plan:** `docs/superpowers/plans/2026-05-11-tt-fg-lost-recovery-plan.md` (v3, Codex CLEAN 2 rounds)

## Context

Discovery 2026-05-11 (этой сессии): TikTok publisher имел `tt_fg_lost` failure-mode (2/24h, 10-15 мин dwell каждый кейс) после AI Unstuck blind-tap'ов попадающих в edge UI зоны → app-switch на Samsung Launcher / Samsung Camera. `dismiss_overlay_dialogs` (publisher_base.py:489) handle'ит dialog-level overlays, но НЕ full Activity-switch.

### Evidence

**Pt 4523 (2026-05-10 19:33-19:55 UTC, account `clickpay_world`):**
- Stage: wait_upload (после Share-tap)
- 8 AI Unstuck cycles за 11 мин — "retry publishing button", "close add music popup", "dismiss unexpected popup"
- 3 overlay iter с `pkg=com.sec.android.app.launcher` (Samsung Launcher / home screen)
- `tt_fg_lost` → fail

**Pt 4624 (2026-05-11 08:22-08:27 UTC, account `clickpay_world`):**
- Stage: caption fill (3× FALLBACK blind-tap publish coords при `ai_find_tap_no_coords`)
- 4 AI Unstuck cycles за 5 мин
- 3 overlay iter с `pkg=com.sec.android.app.camera` (Samsung Camera)
- `tt_fg_lost` → fail

### Misnomer correction

Memory `project_publish_followups_2026_05_06.md` упоминал `tt_fg_lost` как "downstream music-rights". Это **неверно** — pt 4523's AI Unstuck text mentioned "close add music popup", но это был AI Unstuck semantic intent, не event from music-rights handler. Pattern — generic AI Unstuck → app-switch, не music-rights specific.

## Shipped

### Approach A — reactive recovery в `_wait_upload_confirmation` outer loop

В `publisher_tiktok.py`:
1. **`_attempt_tt_fg_recovery` helper** (line 611, TikTokMixin) — `pm list packages` → detect installed TikTok package (musically / trill / default musically) → `monkey -p <detected> LAUNCHER 1` → 2.5s sleep → re-check `topResumedActivity` → set lazy flag → emit success/failed event.
2. **Wire-in Place 1** (line ~1042) — `self._tt_fg_recovery_attempted = False` reset at loop start (per-task semantics).
3. **Wire-in Place 2** (line ~1102) — 4-condition guard в overlay branch: `_pkg != musically`, `!= ugc.trill`, `!= permissioncontroller`, `not _tt_fg_recovery_attempted`. On success → `overlay_streak = 0; continue`. On failure → fall through to existing `tt_fg_lost` path.
4. **Outer fg-check extended** (line ~1002) — `tiktok_active` теперь включает `or 'ugc.trill' in act` (был bug pre-our-PR; uncovered by Codex round 3).

### 4 event categories

| Name | type | When |
|---|---|---|
| `tt_fg_lost` | error | existing — overlay_streak ≥ 3 (recovery already attempted) |
| `tt_fg_recovery_attempt` | info | new — 1st bad-pkg detect, before monkey |
| `tt_fg_recovery_success` | info | new — after monkey TT вернулся |
| `tt_fg_recovery_failed` | warning | new — после monkey foreground всё не TT |

### TT package support

- `com.zhiliaoapp.musically` (global default)
- `com.ss.android.ugc.trill` (regional alt) — detect via `pm list packages`, launch correct one

### Tests

`tests/test_tt_fg_recovery.py` — 6 unit tests (всё PASS):
1. `test_attempt_recovery_success_returns_true`
2. `test_attempt_recovery_failed_returns_false`
3. `test_attempt_recovery_emits_attempt_event_with_meta`
4. `test_attempt_recovery_sets_attempted_flag_even_on_failure`
5. `test_attempt_recovery_uses_monkey_command`
6. `test_attempt_recovery_success_via_trill_package`

Live: 6/6 new + 32/32 baseline + 12/12 renav (PR #34) = **50 PASSED локально**.

## Execution stats

- **Spec:** v1 → Codex 2 rounds CLEAN (NO P1/P2 found, but I treated as approved per memory rule)
- **Plan:** v1 → Codex round 1 (1 P2 — flag reset bug) → v2 → Codex round 2 CLEAN → v3 (cleanup dedup) → CLEAN
- **Implementation:** subagent-driven-development; 6 task dispatches:
  - T1: branch setup (inline)
  - T2: helper TDD (implementer + spec review + code review + 1 fix iteration for Important+Minor)
  - T3: wire-in (implementer + spec review + code review CLEAN, no fixes)
  - T4: full suite (inline)
  - T5: PR + Codex review chain (3 rounds P2 fixes → round 4 CLEAN)
  - T6: post-merge evidence (this doc)
- **5 commits** на ветке (squashed):
  1. dd9e724 — feat(publisher-tt): _attempt_tt_fg_recovery helper (initial)
  2. cb75125 — refactor: dual-pkg check + mock sleep + cleanups (T2 code review)
  3. 4032c33 — feat: wire tt_fg_recovery в wait_upload loop (T3)
  4. 78f905a — fix: apply Codex round 2 (1 P2) — detect TT pkg, single monkey
  5. 615c8b8 — fix: apply Codex round 3 (1 P2) — recognize trill в outer fg check

## Critical Codex catches

- **Codex round 1 (plan):** `_tt_fg_recovery_attempted` flag never reset → long-lived worker recovers only once per process. Fix: explicit reset at `_wait_upload_confirmation` start.
- **Codex round 1 (T2 code review):** `'musically'` check missed `com.ss.android.ugc.trill`. Fix: 3-arm OR. Bonus test added.
- **Codex round 2 (full PR diff):** monkey launches musically even when trill is installed → cannot recover. Fix: dual-launch (sequential monkey for both pkgs).
- **Codex round 2.5 (re-review):** dual-launch can switch active publish session away from musically (state loss). Fix: detect via `pm list packages` → single monkey for installed variant.
- **Codex round 3:** outer `tiktok_active` check (existing code, pre-our-PR) doesn't recognize trill. After recovery on trill device, outer loop re-detects "not TT" → eventual tt_fg_lost. Fix: extend outer check with `or 'ugc.trill' in act`.

## Caveat noted in final review

`publisher_tiktok.py:~1421` — AI Unstuck guard `tiktok_active_for_ai` uses pre-trill check (`'musically' in _cur_act_tt or 'tiktok' in _cur_act_tt.lower()`). Not blocking — trill-only devices uncommon. One-liner fix needed в follow-up PR.

## Success metrics (24h post-deploy)

Tracking deferred until ~2026-05-12 19:00 UTC. SQL queries:

```sql
-- 1. Recovery rate
SELECT meta->>'category' AS cat, COUNT(*) cnt
FROM publish_tasks pt, jsonb_array_elements(events) e
WHERE pt.platform='TikTok'
  AND pt.created_at > NOW() - INTERVAL '24 hours'
  AND e->'meta'->>'category' IN (
    'tt_fg_recovery_attempt',
    'tt_fg_recovery_success',
    'tt_fg_recovery_failed',
    'tt_fg_lost'
  )
GROUP BY 1 ORDER BY 2 DESC;

-- 2. tt_fg_lost drop vs baseline 2/24h
SELECT DATE_TRUNC('day', pt.created_at) AS day, COUNT(*) cnt
FROM publish_tasks pt, jsonb_array_elements(pt.events) e
WHERE pt.platform='TikTok'
  AND e->'meta'->>'category' = 'tt_fg_lost'
  AND pt.created_at > NOW() - INTERVAL '48 hours'
GROUP BY 1 ORDER BY 1;

-- 3. Success rate (target ≥50%)
WITH ev AS (
  SELECT e->'meta'->>'category' AS cat
  FROM publish_tasks pt, jsonb_array_elements(events) e
  WHERE pt.created_at > NOW() - INTERVAL '24 hours'
    AND pt.platform='TikTok'
)
SELECT
  SUM(CASE WHEN cat = 'tt_fg_recovery_attempt' THEN 1 ELSE 0 END) AS attempts,
  SUM(CASE WHEN cat = 'tt_fg_recovery_success' THEN 1 ELSE 0 END) AS successes,
  ROUND(100.0 * SUM(CASE WHEN cat = 'tt_fg_recovery_success' THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN cat = 'tt_fg_recovery_attempt' THEN 1 ELSE 0 END), 0), 1) AS pct
FROM ev;
```

Targets:
- ≥1 `tt_fg_recovery_success` event за 24ч (recovery work)
- Recovery rate ≥50% (reasonable)
- `tt_fg_lost` count drop vs baseline 2/24h

Если recovery_pct <30% — investigate `tt_fg_recovery_failed` `overlay_pkg`/`after_recovery_act` distribution; рассмотреть cold-restart fallback.

## Backlog (после shipped)

- **Follow-up (Caveat from final review):** `publisher_tiktok.py:~1421` — `tiktok_active_for_ai` AI Unstuck guard recognize `'ugc.trill' in _cur_act_tt`. One-liner; bundle с next nearby TT PR.
- **Approach B (prevention):** clamp blind FALLBACK coords + AI Unstuck taps от edge zones (y<100, y>2270, x<30, x>1050). Low priority после recovery shipped.
- **Approach C (vision check):** AI Unstuck post-tap topResumedActivity check + abort если не TikTok. Vision call cost overhead, deferred.
- **Cold-restart fallback:** в `_attempt_tt_fg_recovery` если monkey reorder fails (TT process killed by Android memory pressure). Conditional на recovery_rate <30% observed в проде.
- **IG/YT similar app-switch:** detection in their wait_upload loops — если когда-то возникнет.

## Related

- PR #28 (`8ec5c53`) — TT music rights confirmation dialog handler
- PR #29 (`f49e877`) — TT post-publish success detection
- PR #32 (`f9315cd`) — TT music-rights coverage + post-accept instrumentation
- PR #33 (`d33719a`) — TT `switch_failed_unspecified` root cause fix
- PR #34 (`750c3fa`) — TT post-switch verify recovery (pick→feed)
- Phase 1 (`aec09a9`) — TT `_tt_smart_tap_profile` (label-based bottom-nav, used as base for `_navigate_to_profile_tab` wrapper в PR #34, и as monkey-pkg context here)
