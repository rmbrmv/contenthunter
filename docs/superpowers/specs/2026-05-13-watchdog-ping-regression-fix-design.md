# Design — Watchdog ping regression fix (publisher_base.log_event)

**Date:** 2026-05-13
**Branch (planned):** `fix-watchdog-ping-regression-20260513`
**Scope:** minimal — restore architectural intent that `log_event` activity extends per-step watchdog timer
**Memory cross-links:** [[project_publisher_modularization_wip]] (the refactor that introduced the regression), [[feedback_silent_crash_layered]], [[project_adb_push_network_issue]]

## 1. Problem

`BasePublisher.log_event` (`publisher_base.py:576-591`) **does not call** `self._watchdog.ping()` when events are logged. The architectural intent — documented in `WatchdogTimer.ping` docstring (`publisher_kernel.py:344`) and inline comments at `publisher_base.py:1725-1727` — is that any pipeline activity extends the per-step timeout (rescheduling the underlying `threading.Timer`).

A ping block does exist in source (`publisher_base.py:1725-1732`), but it is **dead code**: positioned immediately after `return fallback` on line 1724 inside `_resolve_publish_fail_category`. The function exits before reaching it. No other path calls `_watchdog.ping()` from `log_event` or its callers.

### How the regression was introduced

Commit `bcb5a2d8` (2026-04-26, "refactor(publisher): cleanup publisher.py — orchestrator-only") moved 50 shared-infra methods from `DevicePublisher` to `BasePublisher` (3203 → 661 LOC). During the move, the ping block was misplaced after a `return` statement, becoming unreachable. The regression lived in production for ~17 days before observation.

### Observed impact

- **Pi 3 + Pi 5 = 23 cross-platform `switch_failed_unspecified` / 24h** (Instagram + TikTok + YouTube).
- Pattern (sample task 5170, YouTube):
  - `05:40:02` `adb_push_chunked_started` (57.5 MB → 58 chunks)
  - `05:41:45` `watchdog_fired` ("step stuck >180s: adb push медиафайла") — fires mid-push
  - `05:42:20` `adb_push_chunked_success` (138s — push actually succeeded)
  - `05:42:27` `watchdog_relaunch` — `_check_watchdog` raises `StepStuckException` after push returns; first retry path
  - `05:43:53` `adb_push_chunked_started` (2nd attempt)
  - `05:45:44` `watchdog_fired` again
  - `05:46:08` `adb_push_chunked_success` (135s — 2nd push also succeeded)
  - `05:46:20` `relaunch_skipped` — `_relaunch_count == 1`, no more retries → `update_status('failed')` + `error_code='switch_failed_unspecified'` via downstream mapper

The pushes themselves succeed; the watchdog kills legitimate slow-network operations because the timer is no longer being extended by activity.

### Why other platforms are not equally affected

`'adb push'` `STEP_TIMEOUT` is 180s (`publisher_kernel.py:241`). On fast networks the chunked-push of typical media (55–78 MB) finishes in ≪180s, so the dead ping does not matter. Pi 3 and Pi 5 have slower proxy throughput (per [[project_adb_push_network_issue]] — packet loss on hop 4), pushing the duration into the 130–184s range and crossing the watchdog threshold.

## 2. Fix

### 2.1 Edit 1 — restore ping in `log_event`

In `publisher_base.py:576-591`, append a ping block at the **end** of the function, **outside** the existing `try/except` for the DB write:

```python
def log_event(self, event_type: str, message: str, meta: dict = None):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        event = {'ts': time.strftime('%H:%M:%S'), 'type': event_type, 'msg': message}
        if meta:
            event['meta'] = meta
        cur.execute(
            "UPDATE publish_tasks SET events = COALESCE(events,'[]'::jsonb) || %s::jsonb WHERE id=%s",
            (json.dumps([event]), self.task_id)
        )
        conn.commit()
        conn.close()
        log.info(f'[{event_type}] {message}')
    except Exception as e:
        log.warning(f'log_event error: {e}')
    # T4: pipeline activity → extend per-step watchdog timer.
    # Skip 'watchdog_fired' event-type to avoid ping ↔ fire loop.
    # Skip when watchdog is None (FAILED-prefixed steps disable timer per publisher_base.py:428).
    if self._watchdog is not None and event_type != 'watchdog_fired':
        try:
            self._watchdog.ping()
        except Exception:
            pass
```

### 2.2 Edit 2 — remove the orphan ping block

In `publisher_base.py:1725-1732`, delete the orphan dead-code block (currently positioned after `return fallback` in `_resolve_publish_fail_category`). Leaving the dead code creates future-reader confusion about which copy is authoritative.

### 2.3 Edit 3 — explicit ping per chunk in chunked-push hot path

`log_event` is only called at chunked-push start (`adb_push_chunked_started`) and end (`adb_push_chunked_success`). Per-chunk pushes in `_adb_push_single_chunk` emit no `log_event` on success (only on retry/failure). Restoring the `log_event` ping alone resets the timer ONCE at chunked-push start, giving a fresh 180s window — but production samples show pushes lasting up to 184s after that start point (e.g., task 5175: 184.1s `chunked_started → chunked_success`). Those pathological cases would still cross the 180s window before success.

In `_adb_push_chunked` (`publisher_base.py:1043-1067`), after each successful single-chunk push (`if not ok` branch falls through to `successful_remote.append(remote_chunk)`), add an explicit watchdog ping:

```python
# T4: extend per-step watchdog after each successful chunk push.
# log_event activity only fires on chunked_started/success, leaving a window
# for 180s+ pushes (observed: 184s on slow Pi networks).
if self._watchdog is not None:
    try:
        self._watchdog.ping()
    except Exception:
        pass
successful_remote.append(remote_chunk)
```

This is the only intra-push hot path that needs explicit ping; the post-cat `cat`/`md5`/cleanup steps reach `log_event('adb_push_chunked_success')` quickly and are covered by Edit 1.

### 2.4 Design rationale

**Why ping is outside the DB-write `try/except`:** the act of calling `log_event` proves that the pipeline thread is still progressing, regardless of whether the DB write succeeded. A transient Postgres outage should not stop watchdog extension and trigger spurious relaunches.

**Why `event_type != 'watchdog_fired'` guard:** `_on_watchdog_fired` (`publisher_base.py:436`) itself calls `log_event('watchdog_fired', ...)`. Without this guard the fire-event would ping the just-fired watchdog. The guard is a defensive measure; `WatchdogTimer.ping` is also a no-op when `_fired` is set (`publisher_kernel.py:347-348`), so this is belt-and-suspenders.

**Why the own `try/except` around `ping()`:** the existing `log_event` contract is "never raises into caller". A `threading.Timer` operation under lock theoretically could raise; swallowing keeps that contract.

## 3. Test plan (TDD, RED → GREEN)

New file `tests/test_publisher_log_event_ping.py`:

1. `test_log_event_pings_watchdog_on_info_event`
   - Set `pub._watchdog = MagicMock()`; call `pub.log_event('info', 'msg')`; assert `pub._watchdog.ping.called`.
   - This is the **primary RED test** — fails on current code.

2. `test_log_event_does_not_ping_on_watchdog_fired_event`
   - Anti-loop guard: `log_event('watchdog_fired', ...)` must NOT call ping.

3. `test_log_event_no_crash_when_watchdog_is_none`
   - `pub._watchdog = None` (FAILED-prefixed step state); `log_event` must not raise.

4. `test_log_event_ping_exception_does_not_propagate`
   - `pub._watchdog.ping.side_effect = RuntimeError('boom')`; `log_event` must not raise.

5. `test_log_event_pings_even_if_db_write_fails`
   - Patch `psycopg2.connect` to raise `psycopg2.OperationalError`; assert `pub._watchdog.ping.called` (ping is outside DB try/except).

All five tests use `unittest.mock.MagicMock` for `self._watchdog`; no real threading.Timer needed. Existing `tests/test_watchdog_timer.py` continues to test the timer in isolation and must remain green.

Additional test for Edit 3 in the same file:

6. `test_chunked_push_pings_watchdog_per_chunk`
   - Mock `pub.log_event` to a no-op `MagicMock` so log-event-driven pings are isolated out of the assertion.
   - Mock `_adb_push_single_chunk` to always return `(True, None)`; supply a fake local file that splits into exactly 3 chunks; set `pub._watchdog = MagicMock()`; call `_adb_push_chunked`.
   - Assert `pub._watchdog.ping.call_count == 3` — exactly one explicit ping per successful single-chunk push (Edit 3), with no log-event pings counted.

## 4. Rollout

- Branch: `fix-watchdog-ping-regression-20260513` off `main` in `rmbrmv/contenthunter`.
- Commits:
  1. `test(publisher): RED test for log_event watchdog ping regression` (failing tests first per TDD).
  2. `fix(publisher): restore watchdog.ping in log_event` (the 5-LOC edit + dead-code removal).
- Codex review on spec (this doc) → 0 P1; then plan → 0 P1; then implementation → 0 P1 per [[feedback_codex_review_specs]].
- PR to `GenGo2/delivery-contenthunter` main.
- Auto-deploy: `git pull --ff-only` on `/root/.openclaw/workspace-genri/autowarm/` via the post-commit hook on `rmbrmv/contenthunter` ([[reference_autowarm_git_hook]]).
- **No PM2 restart needed** — `publisher.py` is spawned as subprocess per task by `server.js`; new spawns auto-pick fresh code ([[project_ig_publish_cross_project_leak_2026_05_12]]).
- In-flight tasks at deploy time continue on old code; no regression risk introduced for them.

## 5. Live verify (24h post-deploy)

Run at deploy + 24h:

```sql
-- Drop in switch_failed_unspecified for Pi 3 and Pi 5 across all platforms
SELECT raspberry, platform, COUNT(*) AS failures
FROM publish_tasks
WHERE error_code='switch_failed_unspecified'
  AND testbench=false
  AND created_at >= NOW() - INTERVAL '24 hours'
GROUP BY raspberry, platform ORDER BY raspberry, 3 DESC;

-- Watchdog-fired events on the 'adb push медиафайла' step (should drop near zero)
SELECT COUNT(*) AS fired_pushes
FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'watchdog_fired'
  AND e->'meta'->>'step' LIKE 'adb push%'
  AND pt.created_at >= NOW() - INTERVAL '24 hours';

-- relaunch_skipped (= legitimate watchdog kills) — should drop
SELECT raspberry, COUNT(*) FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'relaunch_skipped'
  AND e->'meta'->>'phase' = 'media'
  AND pt.created_at >= NOW() - INTERVAL '24 hours'
GROUP BY raspberry ORDER BY 2 DESC;
```

**Acceptance:**
- Pi 3 + Pi 5 combined `switch_failed_unspecified` < 5 / 24h (baseline 23).
- `watchdog_fired` events on `'adb push%'` step ≈ 0 / 24h (baseline ~14 visible in samples 5170–5178 over 4h).
- No new error_code categories spike (sanity check that we haven't shifted the failure mode rather than fixing it).

## 6. Rollback plan

Single `git revert <fix-commit>` on `rmbrmv/contenthunter` main; auto-push hook deploys the revert. No DB migrations, no feature flag, no PM2 state to undo.

## 7. Risks and limitations

- **Coupling between `log_event` and `WatchdogTimer`.** Intentional: `log_event` IS the activity signal. The coupling existed pre-refactor and is the documented design (see `WatchdogTimer.ping` docstring + comments at `publisher_base.py:1725-1727`).
- **Masking of genuine silent hangs.** If a push hangs without ever calling `log_event` (e.g., a thread blocked deep in `subprocess.communicate`), the watchdog still fires correctly — `set_step` is called before push, starting a fresh 180s timer; if no activity happens, no ping, timer fires. The post-op `_check_watchdog(phase='media')` on `publisher_base.py:4024` retains its role: catching push that returned without raising but is reported stuck by the timer.
- **Coverage of long pushes.** Edit 1 (log_event ping) covers any push that emits at least one `log_event` within each 180s window. Edit 3 (per-chunk ping in `_adb_push_chunked`) covers chunked pushes specifically — every successful single-chunk push extends the timer, so a 58-chunk push at ~3s/chunk keeps resetting every 3s. Pathological hangs that produce no chunk progress (single chunk stuck >180s in `_adb_push_single_chunk`'s own retries) will still fire watchdog correctly — that is the desired behavior.

## 8. Out of scope (deferred to backlog)

- Skip `_check_watchdog(phase='media')` when `remote_path` was returned successfully (Option C from brainstorming). Defer until evidence shows Edits 1+3 are insufficient.
- Auditing other dead-code blocks from the same `bcb5a2d8` refactor for similar regressions.
- Increasing `STEP_TIMEOUTS['adb push']` above 180s. Not needed once ping is restored across both general (Edit 1) and chunked-push hot path (Edit 3).

## 9. Acceptance criteria summary

- ✅ All six new tests in `tests/test_publisher_log_event_ping.py` are GREEN.
- ✅ Existing `tests/test_watchdog_timer.py` remains GREEN.
- ✅ Codex review on this spec → 0 P1 (this round and any follow-up).
- ✅ Codex review on the implementation plan → 0 P1.
- ✅ Codex review on the PR diff → 0 P1.
- ✅ 24h post-deploy: Pi 3 + Pi 5 combined `switch_failed_unspecified` < 5 / 24h.
- ✅ Pre-deploy in-flight tasks not regressed (they finish on old code).
