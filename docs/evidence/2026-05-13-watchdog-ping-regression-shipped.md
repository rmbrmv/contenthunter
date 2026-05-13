# Watchdog ping regression — SHIPPED ✅ 2026-05-13

**PR:** [GenGo2/delivery-contenthunter#48](https://github.com/GenGo2/delivery-contenthunter/pull/48)
**Squash-merge commit:** `ec91909ab0b9cf7463ca11cd51ade833cde5a5cd`
**Merged at:** 2026-05-13 08:39:45 UTC
**Deployed to prod tree:** `/root/.openclaw/workspace-genri/autowarm/` via `git pull --ff-only` (fast-forward from `a7e591f`)
**PM2 restart:** not required (publisher.py spawned subprocess-per-task by server.js)

**Spec:** `docs/superpowers/specs/2026-05-13-watchdog-ping-regression-fix-design.md` (commits `c0fa23274`, `9bc53800d`, `24d778a8a`)
**Plan:** `docs/superpowers/plans/2026-05-13-watchdog-ping-regression-fix-plan.md` (commits `18ce22c52`, `30fc193d6`)

## What

Three edits to `publisher_base.py` restoring the architectural intent that `log_event` activity extends the per-step watchdog timer, plus an explicit per-chunk safety net inside `_adb_push_chunked`:

- **Edit 1** — Append a ping block at the end of `BasePublisher.log_event` (outside the DB-write `try/except`). Restores the link between pipeline activity and watchdog timer reset that was severed by the 2026-04-26 modularization refactor (`bcb5a2d8`).
- **Edit 2** — Remove the orphan 8-line ping block that ended up as dead code after `return fallback` in `_resolve_publish_fail_category`.
- **Edit 3** — Explicit `self._watchdog.ping()` after each successful single-chunk push in `_adb_push_chunked`. Uses `getattr(self, '_watchdog', None)` for robustness against existing test stubs (e.g. `tests/test_adb_push_chunked.py::_make_stub` uses `DevicePublisher.__new__()` without `__init__`).

## Why

Pi 3 + Pi 5 = **23 cross-platform `switch_failed_unspecified` / 24h** (Instagram + TikTok + YouTube) as of 2026-05-13 06:46 UTC, all matching one pattern:

| Task | Push duration | Watchdog fired | Outcome |
|---|---|---|---|
| 5170 (YT, content.hunter1) | 138s | 103s into chunked_started | `relaunch_skipped` after 2nd push |
| 5174 (YT, autopostfactory) | 161s | 116s into chunked_started | `relaunch_skipped` after 2nd push |
| 5175 (YT, content_expert) | 184s | 116s into chunked_started | `relaunch_skipped` after 2nd push |
| 5176 (YT, procontent_lab) | 132s | 116s into chunked_started | `relaunch_skipped` after 2nd push |
| 5177 (IG, gengo_sales) | 166s | 116s into chunked_started | `relaunch_skipped` after 2nd push |
| 5178 (IG, 1content_hunter) | 132s | 103s into chunked_started | `relaunch_skipped` after 2nd push |

Push succeeded each time. Watchdog fired because the per-step timer (180s, `STEP_TIMEOUTS['adb push']`) was not being extended by activity — `log_event` no longer called `_watchdog.ping()`. The ping block was present in source but unreachable: it sat after `return fallback` inside `_resolve_publish_fail_category` (publisher_base.py:1734-1741), 17 days after the `bcb5a2d8` refactor (2026-04-26) misplaced it during the publisher.py 3203 → 661 LOC split.

The error masqueraded as `switch_failed_unspecified` via the downstream category mapper. PR #33 (TT `@staticmethod` fix) and PR #40 (error_code mapper fix) had each closed a different branch of the same mystery class — this PR closes the largest branch (slow-network chunked push). Per [[feedback_silent_crash_layered]] this is the third layer of the silent crash discovered to date.

## How

Six TDD-first unit tests in `tests/test_publisher_log_event_ping.py`:

1. `test_log_event_pings_watchdog_on_info_event` — primary RED test (FAIL pre-fix, PASS after Edit 1)
2. `test_log_event_does_not_ping_on_watchdog_fired_event` — anti-loop guard
3. `test_log_event_no_crash_when_watchdog_is_none` — FAILED-step path
4. `test_log_event_ping_exception_does_not_propagate` — robustness
5. `test_log_event_pings_even_if_db_write_fails` — ping outside DB try/except
6. `test_chunked_push_pings_watchdog_per_chunk` — per-chunk ping count (FAIL pre-fix, PASS after Edit 3)

All six GREEN post-fix. Existing `tests/test_watchdog_timer.py` remains 25/25 GREEN. Full-suite run found one pre-existing failure (`tests/test_publish_guard.py::test_guard_allow_on_match`) verified to fail on `origin/main` without our changes.

### Codex review history

| Round | Artifact | Findings | Outcome |
|---|---|---|---|
| spec round 1 | design doc | 1 P1 (180s pathological case not covered) | Added Edit 3 (per-chunk ping) |
| spec round 2 | design doc | 1 P2 (test 6 assertion weak) | Strengthened test 6 to mock log_event + assert exact count |
| plan round 1 | implementation plan | 1 P2 (`pytest \| tail` masks exit status) | Rewrote Task 5 Step 4 with explicit `$?` capture + decision rule |
| PR diff round 1 | full cumulative diff | 1 P2 (re-discovery of single-chunk >180s edge case already noted in spec § 7) | Acknowledged; no action — already documented as out-of-scope pathological hang |

All gating criteria (0 P1 per [[feedback_codex_review_specs]]) met.

### Implementer deviation from plan

Task 5 implementer used `getattr(self, '_watchdog', None)` instead of the literal `self._watchdog is not None` from the spec. Reason: existing `tests/test_adb_push_chunked.py::_make_stub` constructs `DevicePublisher` via `__new__()` without `__init__`, so `self._watchdog` would `AttributeError` (then be swallowed by the outer try/except in `_adb_push_chunked`, surfacing as `adb_push_chunked_exception` instead of correct behavior). For prod code (`__init__` always runs) the two forms are semantically identical. Accepted with DONE_WITH_CONCERNS status; codex review found no issue with the form.

## Baseline (pre-deploy, 2026-05-13 06:46 UTC)

```
Pi 3 switch_failed_unspecified (24h): 14  (IG: 6, TT: 4, YT: 4)
Pi 5 switch_failed_unspecified (24h):  9  (IG: ?, TT: ?, YT: ?)
Pi 9 switch_failed_unspecified (24h):  2  (TT)
Pi 2 switch_failed_unspecified (24h):  1  (IG)
Combined Pi 3+5: 23

watchdog_fired events on 'adb push%' (4h sample):  14 visible across tasks 5170-5178
relaunch_skipped events on phase='media' (24h):   ~20 distributed Pi 3+5
```

## Acceptance criteria

- ✅ All six new tests in `tests/test_publisher_log_event_ping.py` GREEN.
- ✅ Existing `tests/test_watchdog_timer.py` 25/25 GREEN.
- ✅ Codex on spec → 0 P1 (rounds 1+2).
- ✅ Codex on plan → 0 P1 (round 1).
- ✅ Codex on PR diff → 0 P1 (round 1).
- ⏳ **24h post-deploy (2026-05-14 08:39 UTC): Pi 3 + Pi 5 combined `switch_failed_unspecified` < 5 / 24h** — see "24h verify" section below.

## 24h verify (run at 2026-05-14 ≥ 08:40 UTC)

```sql
-- 1. Pi 3+5 switch_failed_unspecified drop
SELECT raspberry, platform, COUNT(*) AS failures
FROM publish_tasks
WHERE error_code='switch_failed_unspecified'
  AND testbench=false
  AND created_at >= '2026-05-13 08:40:00+00'
GROUP BY raspberry, platform ORDER BY raspberry, 3 DESC;

-- 2. watchdog_fired on adb push step (expect ≈ 0)
SELECT COUNT(*) AS fired_pushes
FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'watchdog_fired'
  AND e->'meta'->>'step' LIKE 'adb push%'
  AND pt.created_at >= '2026-05-13 08:40:00+00';

-- 3. relaunch_skipped on media phase (expect drop on Pi 3+5)
SELECT raspberry, COUNT(*) FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'relaunch_skipped'
  AND e->'meta'->>'phase' = 'media'
  AND pt.created_at >= '2026-05-13 08:40:00+00'
GROUP BY raspberry ORDER BY 2 DESC;

-- 4. Spike-check (catch shifted failure modes)
SELECT error_code, COUNT(*) FROM publish_tasks
WHERE status='failed' AND testbench=false
  AND created_at >= '2026-05-13 08:40:00+00'
GROUP BY error_code ORDER BY 2 DESC LIMIT 10;
```

Decision: if combined Pi 3+5 `switch_failed_unspecified` <5 → 🎯 close. If any new category spikes >5/24h that wasn't in pre-deploy top 5 → document follow-up.

## Related memory

- [[project_publisher_modularization_wip]] — the refactor that introduced this regression
- [[feedback_silent_crash_layered]] — pattern: PR #33, PR #40, PR #48 each close a different branch of the same mystery class
- [[project_adb_push_network_issue]] — slow Pi proxy network is the trigger condition
- [[feedback_codex_review_specs]] — codex review rule applied at every artifact
- [[project_tt_switch_failed_unspecified_fixed]] — sibling branch closed earlier
- [[project_error_code_mapper_fail_event_fix]] — sibling branch closed earlier
