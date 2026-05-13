# Watchdog Ping Regression Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the `log_event → _watchdog.ping()` activity-extension that was severed by the 2026-04-26 modularization refactor, plus add an explicit per-chunk ping inside `_adb_push_chunked` to cover ≥180s push durations observed on slow Pi 3+5 networks.

**Architecture:** Three small edits to `publisher_base.py` (add ping in `log_event`, delete orphan dead-code block in `_resolve_publish_fail_category`, add explicit ping after each successful chunk in `_adb_push_chunked`). Six new pytest tests TDD-first in `tests/test_publisher_log_event_ping.py`. Codex review on every artifact per [[feedback_codex_review_specs]].

**Tech Stack:** Python 3, pytest, unittest.mock; production target `/root/.openclaw/workspace-genri/autowarm/`. PRs land in `GenGo2/delivery-contenthunter`. Source-of-truth repo: `rmbrmv/contenthunter`.

**Spec:** `docs/superpowers/specs/2026-05-13-watchdog-ping-regression-fix-design.md` (commits `c0fa23274`, `9bc53800d`, `24d778a8a` — codex round 1 P1 fixed, round 2 P2 fixed).

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `publisher_base.py:576-591` | Modify | Add ping block at end of `log_event` (Edit 1) |
| `publisher_base.py:1725-1732` | Modify (delete) | Remove orphan dead-code ping block (Edit 2) |
| `publisher_base.py:1043-1068` | Modify | Add explicit `self._watchdog.ping()` after each successful chunk push (Edit 3) |
| `tests/test_publisher_log_event_ping.py` | Create | Six new unit tests (5 for log_event ping + 1 for per-chunk ping) |
| `docs/evidence/2026-05-13-watchdog-ping-regression-shipped.md` | Create | Post-deploy evidence doc (after live verify) |

Worktree convention: per [[feedback_parallel_claude_sessions]] + [[feedback_plan_full_mode_branch]], all work happens in a git worktree off branch `fix-watchdog-ping-regression-20260513` so `main` in `/root/.openclaw/workspace-genri/autowarm/` is not blocked for parallel sessions.

---

## Task 1: Set up worktree + branch

**Files:**
- New worktree dir: `/home/claude-user/autowarm-fix-watchdog-ping-20260513/`
- Branch: `fix-watchdog-ping-regression-20260513` off `main`

- [ ] **Step 1: Fetch latest main**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git fetch origin main
```

Expected: fetch completes, prints either no updates or `From .../delivery-contenthunter * branch main → FETCH_HEAD`.

- [ ] **Step 2: Confirm main is clean**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git status --short
```

Expected: empty output. If there are local changes belonging to a parallel session, **abort and notify the user** — do not stash or discard.

- [ ] **Step 3: Create worktree on a new branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm && \
  git worktree add -b fix-watchdog-ping-regression-20260513 \
    /home/claude-user/autowarm-fix-watchdog-ping-20260513 origin/main
```

Expected: `Preparing worktree (new branch 'fix-watchdog-ping-regression-20260513')` then `HEAD is now at <sha> <subject>`.

- [ ] **Step 4: Verify worktree**

```bash
cd /home/claude-user/autowarm-fix-watchdog-ping-20260513 && \
  git rev-parse --abbrev-ref HEAD && \
  git log --oneline -1
```

Expected: prints `fix-watchdog-ping-regression-20260513` then the latest origin/main commit. Stay in this worktree directory for all subsequent tasks.

---

## Task 2: Write all 6 unit tests (RED first)

**Files:**
- Create: `tests/test_publisher_log_event_ping.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_publisher_log_event_ping.py` with this exact content:

```python
"""Unit tests for BasePublisher.log_event watchdog.ping integration
and explicit per-chunk pings in _adb_push_chunked.

Regression: commit bcb5a2d8 (publisher.py 3203→661 refactor, 2026-04-26)
moved the ping block to dead code after a `return fallback` in
_resolve_publish_fail_category. See spec
docs/superpowers/specs/2026-05-13-watchdog-ping-regression-fix-design.md.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_base import BasePublisher  # noqa: E402


def _make_pub(watchdog=None):
    """Build a BasePublisher without running the heavy __init__.

    BasePublisher.__init__ starts a heartbeat thread and builds an
    AccountSwitcher. For pure unit tests of log_event/ping wiring we
    only need a couple of attributes set, so we bypass __init__.
    """
    pub = BasePublisher.__new__(BasePublisher)
    pub.task_id = 9999
    pub._watchdog = watchdog
    return pub


# ─── Test 1: primary RED — ping fires on a normal event ────────────────────

@patch('publisher_base.psycopg2.connect')
def test_log_event_pings_watchdog_on_info_event(mock_connect):
    mock_connect.return_value.cursor.return_value = MagicMock()
    wd = MagicMock()
    pub = _make_pub(watchdog=wd)

    pub.log_event('info', 'msg')

    assert wd.ping.called, 'log_event must extend the per-step watchdog'


# ─── Test 2: anti-loop guard — fired event must not re-ping ────────────────

@patch('publisher_base.psycopg2.connect')
def test_log_event_does_not_ping_on_watchdog_fired_event(mock_connect):
    mock_connect.return_value.cursor.return_value = MagicMock()
    wd = MagicMock()
    pub = _make_pub(watchdog=wd)

    pub.log_event('watchdog_fired', 'step stuck')

    assert not wd.ping.called, (
        'watchdog_fired log must NOT ping (would loop with _on_watchdog_fired)'
    )


# ─── Test 3: None watchdog (FAILED-prefixed steps) — no crash ──────────────

@patch('publisher_base.psycopg2.connect')
def test_log_event_no_crash_when_watchdog_is_none(mock_connect):
    mock_connect.return_value.cursor.return_value = MagicMock()
    pub = _make_pub(watchdog=None)

    # Must not raise.
    pub.log_event('info', 'msg')


# ─── Test 4: ping exception swallowed ──────────────────────────────────────

@patch('publisher_base.psycopg2.connect')
def test_log_event_ping_exception_does_not_propagate(mock_connect):
    mock_connect.return_value.cursor.return_value = MagicMock()
    wd = MagicMock()
    wd.ping.side_effect = RuntimeError('boom')
    pub = _make_pub(watchdog=wd)

    # Must not raise — log_event contract is "never raises into caller".
    pub.log_event('info', 'msg')


# ─── Test 5: ping still happens when DB write fails ────────────────────────

@patch('publisher_base.psycopg2.connect', side_effect=Exception('db down'))
def test_log_event_pings_even_if_db_write_fails(mock_connect):
    wd = MagicMock()
    pub = _make_pub(watchdog=wd)

    pub.log_event('info', 'msg')

    assert wd.ping.called, (
        'ping must be outside the DB-write try/except; a transient '
        'Postgres outage must not stop watchdog extension'
    )


# ─── Test 6: explicit per-chunk ping inside _adb_push_chunked ──────────────

def test_chunked_push_pings_watchdog_per_chunk(tmp_path):
    pub = _make_pub(watchdog=MagicMock())
    # Required attributes for _adb_push_chunked code path.
    pub.adb_host = '127.0.0.1'
    pub.adb_port = 5555
    pub.device_serial = 'TESTSERIAL'

    # Isolate per-chunk pings: log_event must not contribute pings.
    pub.log_event = MagicMock()

    # Stub split into exactly 3 chunks (paths just need to be sortable strings).
    fake_chunks = [
        str(tmp_path / 'media.tag.chunk.0001'),
        str(tmp_path / 'media.tag.chunk.0002'),
        str(tmp_path / 'media.tag.chunk.0003'),
    ]
    for p in fake_chunks:
        Path(p).write_bytes(b'x')  # cleanup helper expects files to exist

    pub._split_file_into_chunks = MagicMock(return_value=fake_chunks)
    pub._adb_push_single_chunk = MagicMock(return_value=(True, None))
    pub._cleanup_chunks_local = MagicMock()
    pub._cleanup_chunks_on_device = MagicMock()
    # cat-merge + md5 verify steps use self.adb — return any non-None to mark
    # success; md5sum stub returns a hex string so local==remote.
    pub._local_md5 = MagicMock(return_value='deadbeef' * 4)
    pub.adb = MagicMock(return_value='deadbeefdeadbeefdeadbeefdeadbeef')

    local = tmp_path / 'media.mp4'
    local.write_bytes(b'x' * 1024)

    ok, err = pub._adb_push_chunked(
        str(local), '/sdcard/media.mp4',
        reason='test', size_mb=0.001, canary_ms=None,
    )

    assert ok is True, f'expected push success, got err={err!r}'
    assert pub._watchdog.ping.call_count == 3, (
        f'expected exactly 1 explicit ping per successful chunk (3 total), '
        f'got call_count={pub._watchdog.ping.call_count}'
    )
```

- [ ] **Step 2: Run the new test file — confirm RED**

```bash
cd /home/claude-user/autowarm-fix-watchdog-ping-20260513 && \
  pytest tests/test_publisher_log_event_ping.py -v
```

Expected output:
- `test_log_event_pings_watchdog_on_info_event` — **FAIL** (`assert wd.ping.called` is False; ping is dead code)
- `test_log_event_does_not_ping_on_watchdog_fired_event` — PASS (dead code never called → guard accidentally holds)
- `test_log_event_no_crash_when_watchdog_is_none` — PASS (no crash either way; pre-fix path simply does nothing)
- `test_log_event_ping_exception_does_not_propagate` — PASS (ping never called → no exception path)
- `test_log_event_pings_even_if_db_write_fails` — **FAIL** (`assert wd.ping.called` is False; ping is dead code)
- `test_chunked_push_pings_watchdog_per_chunk` — **FAIL** (no per-chunk pings yet; `call_count == 0`)

If a passing test fails or a failing test passes, **stop and investigate** before adding code.

- [ ] **Step 3: Commit the RED tests**

```bash
git add tests/test_publisher_log_event_ping.py
git commit -m "$(cat <<'EOF'
test(publisher): RED tests for log_event watchdog.ping + per-chunk ping

Six TDD-first tests covering BasePublisher.log_event ping wiring (5) and
explicit per-chunk pings in _adb_push_chunked (1). Three FAIL on current
main, three PASS by accident; see plan for expected verdicts.

Spec: docs/superpowers/specs/2026-05-13-watchdog-ping-regression-fix-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: clean commit on `fix-watchdog-ping-regression-20260513`.

---

## Task 3: Apply Edit 1 — restore ping in `log_event`

**Files:**
- Modify: `publisher_base.py:576-591` (`log_event`)

- [ ] **Step 1: Locate the current `log_event` body**

```bash
sed -n '576,591p' publisher_base.py
```

Expected: prints the function exactly as quoted in the spec § 2.1 ("before" state).

- [ ] **Step 2: Apply the edit**

Replace the body of `log_event` (lines 576-591) with the version below. The only difference is the ping block appended at the end, outside the existing `try/except`.

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
        # Skip 'watchdog_fired' to avoid ping ↔ fire loop (_on_watchdog_fired
        # itself calls log_event). Skip when watchdog is None (FAILED-prefixed
        # steps disable the timer at publisher_base.py:428).
        if self._watchdog is not None and event_type != 'watchdog_fired':
            try:
                self._watchdog.ping()
            except Exception:
                pass
```

- [ ] **Step 3: Run tests — Tests 1, 4, 5 should now pass; 6 still red**

```bash
pytest tests/test_publisher_log_event_ping.py -v
```

Expected:
- `test_log_event_pings_watchdog_on_info_event` — PASS
- `test_log_event_does_not_ping_on_watchdog_fired_event` — PASS (still)
- `test_log_event_no_crash_when_watchdog_is_none` — PASS (still)
- `test_log_event_ping_exception_does_not_propagate` — PASS
- `test_log_event_pings_even_if_db_write_fails` — PASS
- `test_chunked_push_pings_watchdog_per_chunk` — **FAIL** (Edit 3 not yet applied)

- [ ] **Step 4: Run existing watchdog suite — must remain green**

```bash
pytest tests/test_watchdog_timer.py -v
```

Expected: all existing tests PASS.

- [ ] **Step 5: Commit Edit 1**

```bash
git add publisher_base.py
git commit -m "$(cat <<'EOF'
fix(publisher): restore watchdog.ping in log_event (Edit 1)

Regression from bcb5a2d8 refactor (2026-04-26): ping block ended up as
dead code at publisher_base.py:1725-1732 after `return fallback` inside
_resolve_publish_fail_category. log_event activity no longer extended
the per-step watchdog, killing legitimate 130-180s chunked pushes on
Pi 3+5 slow networks (23 cross-platform switch_failed_unspecified/24h).

Spec: docs/superpowers/specs/2026-05-13-watchdog-ping-regression-fix-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Apply Edit 2 — remove orphan dead-code ping block

**Files:**
- Modify: `publisher_base.py:1725-1732` (delete the orphan ping block)

- [ ] **Step 1: Print the soon-to-be-deleted block + 3 lines of surrounding context**

```bash
sed -n '1722,1735p' publisher_base.py
```

Expected output (line numbers may have shifted by Edit 1's net change of +5 LOC — confirm against pattern, not absolute line numbers):

```
        log.debug('[category-resolve] no switcher-fail or prior-error with category → fallback')
        return fallback
        # T4: активность в pipeline — продлеваем per-step timeout.
        # Если watchdog уже fired, ping — no-op (см. WatchdogTimer.ping).
        # Исключаем watchdog_fired event от ping'а, чтобы не создать loop.
        if self._watchdog is not None and event_type != 'watchdog_fired':
            try:
                self._watchdog.ping()
            except Exception:
                pass

    # ─── Account switch (pre-publish) ─────────────────────────────────────
```

- [ ] **Step 2: Delete the eight-line dead block (comment lines + if/try block)**

Using `Edit` tool with this exact `old_string`:

```python
        log.debug('[category-resolve] no switcher-fail or prior-error with category → fallback')
        return fallback
        # T4: активность в pipeline — продлеваем per-step timeout.
        # Если watchdog уже fired, ping — no-op (см. WatchdogTimer.ping).
        # Исключаем watchdog_fired event от ping'а, чтобы не создать loop.
        if self._watchdog is not None and event_type != 'watchdog_fired':
            try:
                self._watchdog.ping()
            except Exception:
                pass
```

Replace with:

```python
        log.debug('[category-resolve] no switcher-fail or prior-error with category → fallback')
        return fallback
```

- [ ] **Step 3: Re-run full test suite — no regression expected**

```bash
pytest tests/test_publisher_log_event_ping.py tests/test_watchdog_timer.py -v
```

Expected: same verdicts as Task 3 Step 3 (5 PASS, 1 FAIL on test 6) — Edit 2 changes only dead code, behavior unchanged.

- [ ] **Step 4: Commit Edit 2**

```bash
git add publisher_base.py
git commit -m "$(cat <<'EOF'
fix(publisher): remove orphan dead-code ping block (Edit 2)

Eight lines after `return fallback` in _resolve_publish_fail_category
were unreachable. Removing them avoids future-reader confusion about
which copy of the ping logic is authoritative (now: log_event only).

Spec: docs/superpowers/specs/2026-05-13-watchdog-ping-regression-fix-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Apply Edit 3 — explicit per-chunk ping in `_adb_push_chunked`

**Files:**
- Modify: `publisher_base.py` `_adb_push_chunked` — inside the per-chunk loop at line ~1043-1068

- [ ] **Step 1: Locate the per-chunk loop**

```bash
grep -n 'successful_remote.append(remote_chunk)' publisher_base.py
```

Expected: one match — the line that records a successful single-chunk push (line ~1068 pre-edit).

- [ ] **Step 2: Insert the ping before `successful_remote.append`**

Using `Edit` tool with this exact `old_string` (the trailing context comment and append line):

```python
                successful_remote.append(remote_chunk)
                # retries_total = sum of (attempts - 1) per successful chunk —
                # не считаем тут, т.к. chunked-success meta не требует это строго.
```

Replace with:

```python
                # T4: extend per-step watchdog after each successful chunk.
                # log_event activity only fires on chunked_started/success, leaving
                # a window where 180s+ pushes (observed: 184s on slow Pi networks)
                # cross the timeout. Explicit ping here is the per-chunk safety net.
                if self._watchdog is not None:
                    try:
                        self._watchdog.ping()
                    except Exception:
                        pass
                successful_remote.append(remote_chunk)
                # retries_total = sum of (attempts - 1) per successful chunk —
                # не считаем тут, т.к. chunked-success meta не требует это строго.
```

- [ ] **Step 3: Run tests — all six must now pass**

```bash
pytest tests/test_publisher_log_event_ping.py tests/test_watchdog_timer.py -v
```

Expected:
- All six tests in `test_publisher_log_event_ping.py` — PASS.
- All tests in `test_watchdog_timer.py` — PASS (unchanged).

- [ ] **Step 4: Run the full repo test suite to catch incidental regressions**

```bash
pytest tests/ -x --ignore=tests/test_publisher_obstacle_kb.py -q 2>&1 | tail -30
```

(The obstacle-KB suite needs a live DB; skip it here. Other DB-heavy suites that already exist on main may have pre-existing failures — see [[project_validator_stale_generate_description_tests]] for the equivalent pattern in validator. If you encounter failures unrelated to `watchdog`/`log_event`/`adb_push`, treat them as pre-existing and document the names, do not try to fix them in this PR.)

Expected: green or pre-existing failures only (none touching `log_event`, `watchdog`, `adb_push_chunked`).

- [ ] **Step 5: Commit Edit 3**

```bash
git add publisher_base.py
git commit -m "$(cat <<'EOF'
fix(publisher): explicit per-chunk watchdog.ping in _adb_push_chunked (Edit 3)

Edit 1 (log_event ping) resets timer only at chunked_started + chunked_success,
leaving a single 180s window. Production task 5175 showed a 184.1s push that
exceeded the window before the success log_event fired. Per-chunk ping
keeps the timer alive at ~3s granularity (~58 chunks for a 55MB media).

Spec: docs/superpowers/specs/2026-05-13-watchdog-ping-regression-fix-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Codex review on the full diff

**Files:** none modified; codex review run only.

- [ ] **Step 1: Generate the cumulative diff**

```bash
git diff origin/main...HEAD -- publisher_base.py tests/test_publisher_log_event_ping.py > /tmp/watchdog-ping-diff.patch
wc -l /tmp/watchdog-ping-diff.patch
```

Expected: a non-empty patch file, on the order of 150-200 lines.

- [ ] **Step 2: Pipe diff into codex review (per [[feedback_codex_sandbox_broken]] — `--base main` is broken)**

```bash
cat /tmp/watchdog-ping-diff.patch | ~/.local/bin/codex review - 2>&1 | tail -80
```

- [ ] **Step 3: Triage codex findings**

- If output is `0 P1` (or no review comments at all): proceed to Task 7.
- If output contains `[P1]`: apply the fix in-tree (new commit, NOT amend), then re-run Step 2. Repeat until 0 P1.
- `[P2]` and below are non-blocking per [[feedback_codex_review_specs]], but trivial single-line strengthenings should be addressed inline before moving on.

- [ ] **Step 4: Record codex outcome in commit history**

If codex returned non-zero findings, ensure each fix lands as its own commit with the message format:

```
fix(publisher): <subject> (codex round N P1)
```

so the audit trail matches the patten established in [[project_session_2026_05_11_shipped]].

---

## Task 7: Push branch and open PR

**Files:** none.

- [ ] **Step 1: Pull main to detect drift**

```bash
git fetch origin main && git log --oneline origin/main..HEAD
```

Expected: only the commits from Tasks 2-6 (RED tests, Edit 1, Edit 2, Edit 3, optional codex fix commits).

If `git log --oneline HEAD..origin/main` is non-empty, a parallel session moved main forward — rebase (`git rebase origin/main`) and re-run Task 5 Step 3 before pushing.

- [ ] **Step 2: Push the branch**

```bash
. ~/secrets/github.env 2>/dev/null || . ~/secrets/github-gengo2.env
git push -u origin fix-watchdog-ping-regression-20260513
```

Expected: branch pushed; URL for opening a PR printed.

- [ ] **Step 3: Open PR against `GenGo2/delivery-contenthunter` main**

```bash
gh pr create --title "fix(publisher): watchdog ping regression — Pi 3+5 chunked-push race" \
  --body "$(cat <<'EOF'
## Summary

- Restore `_watchdog.ping()` in `BasePublisher.log_event` (Edit 1) — fixes regression from `bcb5a2d8` (2026-04-26) where ping ended up as dead code after `return fallback`.
- Remove the orphan dead-code ping block (Edit 2).
- Add explicit per-chunk `_watchdog.ping()` inside `_adb_push_chunked` (Edit 3) — covers observed 184s push case on slow Pi 3+5 networks.

## Why

Pi 3 + Pi 5 = 23 cross-platform `switch_failed_unspecified` / 24h, all matching the pattern: chunked push completes (130-184s), but watchdog fires mid-push because activity no longer extends the timer → `watchdog_relaunch` → 2nd push → `relaunch_skipped` → fail.

Spec (with full RC analysis): `docs/superpowers/specs/2026-05-13-watchdog-ping-regression-fix-design.md`
Plan: `docs/superpowers/plans/2026-05-13-watchdog-ping-regression-fix-plan.md`

## Test plan

- [x] 6 new TDD-first tests in `tests/test_publisher_log_event_ping.py` (RED before fixes, GREEN after).
- [x] Existing `tests/test_watchdog_timer.py` remains GREEN.
- [x] Codex review on spec → 0 P1 (rounds 1+2).
- [x] Codex review on plan → 0 P1.
- [x] Codex review on PR diff → 0 P1.
- [ ] 24h post-deploy: Pi 3 + Pi 5 combined `switch_failed_unspecified` < 5 / 24h.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Save it for the evidence doc.

---

## Task 8: Auto-deploy via post-commit hook

**Files:** none in this worktree (deploy is automatic).

- [ ] **Step 1: Merge the PR**

When the PR is approved (codex review at PR-diff level should already be clean), merge it via `gh pr merge --squash`. Per [[reference_autowarm_git_hook]], the `rmbrmv/contenthunter` post-commit hook will auto-fast-forward `/root/.openclaw/workspace-genri/autowarm/` on `main`.

```bash
gh pr merge <pr-number> --squash --delete-branch
```

Expected: PR closed, branch deleted, GitHub Actions / hook fires.

- [ ] **Step 2: Verify the prod tree picked up the change**

```bash
cd /root/.openclaw/workspace-genri/autowarm && \
  git log --oneline -3 && \
  grep -n 'self._watchdog.ping()' publisher_base.py
```

Expected: top commit is the squash-merge (or a follow-up), and `grep` shows the `ping()` call inside `log_event` (around line 593-596 after Edit 1) AND inside `_adb_push_chunked` (around line 1043-1050 after Edit 3).

- [ ] **Step 3: No PM2 restart**

`publisher.py` is spawned subprocess-per-task by `server.js` ([[project_ig_publish_cross_project_leak_2026_05_12]]) — new spawns auto-pick up the changes. In-flight tasks finish on the old code and do not regress.

- [ ] **Step 4: Remove the worktree**

```bash
git worktree remove /home/claude-user/autowarm-fix-watchdog-ping-20260513
```

Expected: worktree directory deleted; `git worktree list` no longer shows it.

---

## Task 9: 24h live verify

**Files:**
- Create: `docs/evidence/2026-05-13-watchdog-ping-regression-shipped.md`

- [ ] **Step 1: Schedule a 24h follow-up**

Record the deploy timestamp (when `git pull --ff-only` actually ran in prod, not the PR merge UTC). The verify queries should target `created_at >= <deploy-ts>`.

- [ ] **Step 2: At deploy + 24h, run all three SQL queries from spec § 5**

```sql
-- Pi 3+5 switch_failed_unspecified drop (acceptance: combined < 5 / 24h)
SELECT raspberry, platform, COUNT(*) AS failures
FROM publish_tasks
WHERE error_code='switch_failed_unspecified'
  AND testbench=false
  AND created_at >= '<deploy-ts>'
GROUP BY raspberry, platform ORDER BY raspberry, 3 DESC;

-- watchdog_fired on adb push step (acceptance: ≈ 0)
SELECT COUNT(*) AS fired_pushes
FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'watchdog_fired'
  AND e->'meta'->>'step' LIKE 'adb push%'
  AND pt.created_at >= '<deploy-ts>';

-- relaunch_skipped on media phase (acceptance: drop on Pi 3+5)
SELECT raspberry, COUNT(*) FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'relaunch_skipped'
  AND e->'meta'->>'phase' = 'media'
  AND pt.created_at >= '<deploy-ts>'
GROUP BY raspberry ORDER BY 2 DESC;
```

- [ ] **Step 3: Spike-check for shifted failure modes**

```sql
-- New error_code that wasn't in the top 5 pre-deploy?
SELECT error_code, COUNT(*) FROM publish_tasks
WHERE status='failed' AND testbench=false
  AND created_at >= '<deploy-ts>'
GROUP BY error_code ORDER BY 2 DESC LIMIT 10;
```

Compare against baseline (see [[project_session_2026_05_12_evening_shipped]] queries) — if a new category spikes >5/24h that wasn't there pre-deploy, document it as a follow-up (do NOT claim the fix succeeded just because `switch_failed_unspecified` dropped).

- [ ] **Step 4: Write the evidence doc**

Create `docs/evidence/2026-05-13-watchdog-ping-regression-shipped.md` covering:
- PR number + squash-merge commit + auto-deploy timestamp
- Baseline numbers (from this plan's Task 9 Step 2 pre-deploy run, captured today 2026-05-13 06:46 UTC)
- Post-deploy numbers (Step 2 at +24h)
- Verdict: acceptance criteria met / partial / fail
- Any spike-check findings from Step 3

Commit to `rmbrmv/contenthunter` main.

- [ ] **Step 5: Update memory**

Add a new memory file `project_watchdog_ping_regression_shipped.md` (type=project) with the one-line summary + link to the evidence doc. Update `MEMORY.md` with one line under ~150 chars: `- [Watchdog ping regression — shipped 2026-05-13](project_watchdog_ping_regression_shipped.md) — Pi 3+5 chunked-push race, 23/24h closed`.

Per [[feedback_silent_crash_layered]], also touch any memory entries that point at "switch_failed_unspecified" as a root cause (e.g., `project_tt_switch_failed_unspecified_fixed.md`) — note that one branch of the mystery class was a separate root cause (watchdog), now closed.

---

## Self-Review

### Spec coverage

| Spec § | Plan task |
|---|---|
| § 2.1 Edit 1 (log_event ping) | Task 3 |
| § 2.2 Edit 2 (remove orphan) | Task 4 |
| § 2.3 Edit 3 (per-chunk ping) | Task 5 |
| § 2.4 Design rationale | Embedded in Task 3 Step 2 inline comment |
| § 3 Tests 1-6 | Task 2 (all six in one file, written together TDD-style) |
| § 4 Rollout (branch, commits, codex, PR, auto-deploy, no PM2 restart) | Tasks 1, 6, 7, 8 |
| § 5 Live verify SQL (24h) | Task 9 |
| § 6 Rollback plan (single revert) | Implicit — single PR, squash-merge → one revert commit suffices |
| § 7 Risks (coupling, silent hangs, long pushes) | Spec is the rationale doc; plan inherits |
| § 8 Out of scope | Not a plan task |
| § 9 Acceptance criteria (6 tests green, watchdog suite green, codex 0 P1 x3, Pi 3+5 < 5/24h) | Tasks 2, 3, 5, 6, 9 |

### Placeholder scan

No "TBD/TODO/implement later"; no generic "add error handling"; no "similar to Task N". The only intentional placeholder is `<deploy-ts>` in Task 9 Step 2, which is filled in at verify time and labelled explicitly.

### Type consistency

- `self._watchdog` typed `Optional[WatchdogTimer]` consistently in spec § 2.1, plan Task 3 Step 2, and existing `BasePublisher.__init__:383`.
- `event_type` is `str` in `log_event` signature and in the ping guard.
- `_adb_push_chunked` returns `tuple` `(ok: bool, err: dict|None)` — Task 5 test 6 asserts `ok is True` and unpacks both fields.

### Scope check

Single subsystem (publisher's per-step watchdog interaction with chunked-push). One spec → one plan → one PR. No decomposition needed.
