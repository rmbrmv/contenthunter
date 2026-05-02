# Publisher Obstacle KB — Probe Coverage Expansion (Stage A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand obstacle KB shadow probes from 5 narrow call-sites to comprehensive coverage of all publisher fail-paths, so KB starts collecting `shadow_match` outcomes on every real production failure (currently 0 outcomes after 24h — KB is blind to actual obstacle distribution).

**Architecture:** Two-tier probe strategy:
1. **Tier-final** — single probe inside `_fail_task` (publisher_base.py:1504). Catches every fail-path the publisher takes, regardless of platform/category. One edit, comprehensive coverage.
2. **Tier-intermediate** — extract `_safe_kb_probe(xml, step)` helper (W2 follow-up dedup) and wire it into ~17 intermediate `meta.category` log sites where recovery is still attempting but UI is stuck. Gives early-stage signal before the task escalates to fail.

Both tiers are kill-switch gated (`obstacle_kb_disabled`), exception-isolated (probe failures NEVER break recovery), and write to `publisher_obstacle_outcomes` with `outcome='shadow_match'`.

**Tech Stack:** Python 3.11, pytest+mocks, postgres `openclaw` DB. No new modules — all changes in existing publisher files. Branch `feature/obstacle-kb-probe-coverage-20260502` from main `8cd58de`.

**Working tree:** `/home/claude-user/autowarm-testbench` (worktree on main, GenGo2/delivery-contenthunter remote).

---

## Pre-flight

- [ ] **Step P.1: Sync main and create branch**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git checkout main
git pull --ff-only origin main
git checkout -b feature/obstacle-kb-probe-coverage-20260502
```

Expected: branch created from `8cd58de` (or newer if main moved). Worktree clean.

- [ ] **Step P.2: Verify pytest baseline green**

```bash
cd /home/claude-user/autowarm-testbench
python3 -m pytest tests/test_obstacle_kb.py tests/test_obstacle_signatures.py tests/test_obstacle_seed.py tests/test_obstacle_kill_switches.py -v
```

Expected: all green (W2 invariant). If anything red, STOP and re-seed:
```bash
python3 obstacle_seed.py from-constants
```

- [ ] **Step P.3: Snapshot baseline KB metrics (for end-of-stage diff)**

```bash
psql -h localhost -U openclaw -d openclaw -c "
SELECT
  (SELECT count(*) FROM publisher_obstacle_outcomes WHERE outcome='shadow_match') AS shadow_matches,
  (SELECT count(*) FROM publisher_obstacle_outcomes) AS total_outcomes,
  (SELECT count(*) FROM publisher_obstacles WHERE source LIKE 'manual_seed%') AS seed_obstacles,
  NOW() AS ts;
"
```

Save output to evidence file `/home/claude-user/contenthunter/.ai-factory/evidence/probe-coverage-baseline-20260502.md`. Expected baseline: `shadow_matches=0`, `total_outcomes=0`, `seed_obstacles=8`.

---

## File Structure

| File | Role | Changes |
|---|---|---|
| `publisher_base.py` | Defines `_obstacle_kb_shadow_probe` + `_fail_task`. Added: `_safe_kb_probe` helper. | New helper at ~L390. Modified `_fail_task` at L1504. |
| `publisher_instagram.py` | InstagramMixin. Existing probe at L927. | Refactor L927 to use helper + add 8 intermediate probes. |
| `publisher_tiktok.py` | TikTokMixin. No probes today. | Add 4 intermediate probes. |
| `publisher_youtube.py` | YouTubeMixin. No probes today. | Add 3 intermediate probes. |
| `account_switcher.py` | Existing 4 probes at L1222/1309/1835/3169. | Refactor 4 sites to use helper. |
| `tests/test_obstacle_kb_safe_probe.py` | NEW — unit tests for `_safe_kb_probe`. | Created. |
| `tests/test_publisher_fail_task_probe.py` | NEW — unit tests for tier-final probe. | Created. |
| `tests/test_publisher_intermediate_probes.py` | NEW — integration tests for tier-intermediate sites. | Created. |

---

## Task 1: `_safe_kb_probe(xml, step)` helper + dedup 5 existing sites

**Files:**
- Modify: `publisher_base.py:~390` (add helper after `_obstacle_kb_shadow_probe`)
- Modify: `publisher_instagram.py:927` (refactor existing call)
- Modify: `account_switcher.py:1222, 1309, 1835, 3169` (refactor 4 calls)
- Create: `tests/test_obstacle_kb_safe_probe.py`

**Why this task first:** All subsequent tasks call this helper. Existing 5 sites give us a refactor-without-behavior-change validation: tests for those sites must remain green.

- [ ] **Step 1.1: Write failing test for `_safe_kb_probe` helper**

```python
# tests/test_obstacle_kb_safe_probe.py
"""Unit tests for BasePublisher._safe_kb_probe — wrapper around shadow probe.

Goal: helper must be a no-op when xml is empty/None, must call inner probe
when xml is provided, and must NEVER raise — exception isolation is the
whole point of the wrapper.
"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def fake_publisher():
    """Build minimal BasePublisher-like object for helper test."""
    from publisher_base import BasePublisher
    pub = BasePublisher.__new__(BasePublisher)
    pub.platform = 'instagram'
    pub.task_id = 42
    return pub


def test_safe_kb_probe_with_empty_xml_is_noop(fake_publisher):
    fake_publisher._obstacle_kb_shadow_probe = MagicMock()
    fake_publisher._safe_kb_probe(xml='', step='step1')
    fake_publisher._obstacle_kb_shadow_probe.assert_not_called()


def test_safe_kb_probe_with_none_xml_is_noop(fake_publisher):
    fake_publisher._obstacle_kb_shadow_probe = MagicMock()
    fake_publisher._safe_kb_probe(xml=None, step='step1')
    fake_publisher._obstacle_kb_shadow_probe.assert_not_called()


def test_safe_kb_probe_with_valid_xml_calls_inner(fake_publisher):
    fake_publisher._obstacle_kb_shadow_probe = MagicMock()
    fake_publisher._safe_kb_probe(xml='<hierarchy>...</hierarchy>', step='step1')
    fake_publisher._obstacle_kb_shadow_probe.assert_called_once_with(
        '<hierarchy>...</hierarchy>', publisher_step='step1'
    )


def test_safe_kb_probe_swallows_exceptions(fake_publisher):
    fake_publisher._obstacle_kb_shadow_probe = MagicMock(
        side_effect=RuntimeError('boom'))
    # MUST NOT raise
    fake_publisher._safe_kb_probe(xml='<hierarchy/>', step='step1')
    fake_publisher._obstacle_kb_shadow_probe.assert_called_once()
```

- [ ] **Step 1.2: Run test, expect import-fails or AttributeError**

```bash
cd /home/claude-user/autowarm-testbench
python3 -m pytest tests/test_obstacle_kb_safe_probe.py -v
```

Expected: 4 fails with `AttributeError: '_safe_kb_probe'`.

- [ ] **Step 1.3: Implement `_safe_kb_probe` helper**

Add to `publisher_base.py` immediately after `_obstacle_kb_shadow_probe` (~L388):

```python
    def _safe_kb_probe(self, xml: Optional[str], step: str) -> None:
        """Thin wrapper around _obstacle_kb_shadow_probe — exception-isolated,
        skips on empty xml. Used for wiring probes into many call-sites
        without repeating None/exception guards everywhere.
        """
        if not xml:
            return
        try:
            self._obstacle_kb_shadow_probe(xml, publisher_step=step)
        except Exception as e:
            log.warning(f'[obstacle-kb-safe] probe failed: {e}')
```

- [ ] **Step 1.4: Run helper tests, expect green**

```bash
python3 -m pytest tests/test_obstacle_kb_safe_probe.py -v
```

Expected: 4 passed.

- [ ] **Step 1.5: Refactor existing 5 call-sites**

Use `Read` + `Edit` for each. Each existing site looks like:

```python
self._obstacle_kb_shadow_probe(xml, publisher_step='X')
```

Replace with:
```python
self._safe_kb_probe(xml, step='X')
```

For switcher (calls via `self.p.`):
```python
self.p._obstacle_kb_shadow_probe(...)  # OLD
self.p._safe_kb_probe(xml, step='X')  # NEW
```

Sites to edit:
1. `publisher_instagram.py:927` — `publisher_step='open_camera'` → `step='open_camera'`
2. `account_switcher.py:1222` — `publisher_step='ig_human_check'` → `step='ig_human_check'`  (verify exact step name in current code)
3. `account_switcher.py:1309` — same area, second IG human-check site
4. `account_switcher.py:1835` — TT retap site, `step='tt_retap'`
5. `account_switcher.py:3169` — overlay dismiss, already takes `publisher_step=step_name or 'overlay_dismiss'` — keep semantics

For #5, replacement is:
```python
self.p._safe_kb_probe(ui, step=step_name or 'overlay_dismiss')
```

- [ ] **Step 1.6: Run full obstacle test suite, expect green**

```bash
python3 -m pytest tests/test_obstacle_kb_safe_probe.py tests/test_publisher_obstacle_kb_shadow.py tests/test_switcher_obstacle_kb.py tests/test_obstacle_kb.py -v 2>&1 | tail -30
```

Expected: all passed. If `test_publisher_obstacle_kb_shadow.py` or `test_switcher_obstacle_kb.py` doesn't exist, search for relevant probe tests:

```bash
ls tests/ | grep -iE "obstacle|probe|shadow"
python3 -m pytest tests/ -k 'obstacle or probe or shadow' -v 2>&1 | tail -40
```

If existing probe tests assert call-args explicitly with `_obstacle_kb_shadow_probe` (mock), they'll fail after refactor — update those tests to mock `_safe_kb_probe` instead.

- [ ] **Step 1.7: Commit**

```bash
git add tests/test_obstacle_kb_safe_probe.py publisher_base.py publisher_instagram.py account_switcher.py
git commit -m "$(cat <<'EOF'
refactor(obstacle-kb): extract _safe_kb_probe helper, dedup 5 call-sites

W2 follow-up — dedup 5 existing probe call-sites into single helper that
swallows exceptions and skips on empty xml. Prepares for fan-out to
intermediate obstacle states (tasks 2-7).

No behavior change at runtime (helper is a thin wrapper; inner
_obstacle_kb_shadow_probe identical).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Tier-final probe inside `_fail_task`

**Files:**
- Modify: `publisher_base.py:1504` (`_fail_task`)
- Create: `tests/test_publisher_fail_task_probe.py`

**Why critical:** This single edit gives KB visibility into EVERY publisher failure regardless of platform or where in the code-path the fail originated. Closes the comprehensive-coverage gap in one edit.

- [ ] **Step 2.1: Write failing test**

```python
# tests/test_publisher_fail_task_probe.py
"""Tests for tier-final shadow probe inside BasePublisher._fail_task.

Contract: when _fail_task is called, it must invoke _safe_kb_probe with
(xml, step) where xml is current dump_ui() and step is the failure step.
"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def fail_task_publisher():
    """Build BasePublisher with stubs for DB/log calls so _fail_task is
    callable in isolation."""
    from publisher_base import BasePublisher
    pub = BasePublisher.__new__(BasePublisher)
    pub.platform = 'instagram'
    pub.task_id = 1234
    pub._collected_ui_dumps = []
    pub._collected_screenshots = []
    pub.set_step = MagicMock()
    pub._save_debug_ui_dump = MagicMock(return_value='/tmp/dump.xml')
    pub.log_event = MagicMock()
    pub._set_error_code_from_events = MagicMock()
    pub.dump_ui = MagicMock(return_value='<hierarchy/>')
    pub._safe_kb_probe = MagicMock()
    return pub


def test_fail_task_invokes_safe_kb_probe(fail_task_publisher):
    """_fail_task must call _safe_kb_probe once with current xml + step."""
    with patch('publisher_base.psycopg2.connect') as mock_conn:
        mock_conn.return_value.cursor.return_value.execute = MagicMock()
        mock_conn.return_value.commit = MagicMock()
        mock_conn.return_value.close = MagicMock()
        fail_task_publisher._fail_task(reason='test failure', step='ig_caption_fill_failed')

    fail_task_publisher._safe_kb_probe.assert_called_once()
    call_kwargs = fail_task_publisher._safe_kb_probe.call_args
    # Either positional (xml, step=...) or both kwargs.
    assert 'ig_caption_fill_failed' in str(call_kwargs)


def test_fail_task_probe_runs_even_when_dump_ui_fails(fail_task_publisher):
    """If dump_ui throws, probe should still be called with None — _safe_kb_probe
    handles the empty-xml case (no-op)."""
    fail_task_publisher.dump_ui = MagicMock(side_effect=RuntimeError('adb dead'))
    with patch('publisher_base.psycopg2.connect') as mock_conn:
        mock_conn.return_value.cursor.return_value.execute = MagicMock()
        mock_conn.return_value.commit = MagicMock()
        mock_conn.return_value.close = MagicMock()
        fail_task_publisher._fail_task(reason='test', step='step_x')

    fail_task_publisher._safe_kb_probe.assert_called_once()
```

- [ ] **Step 2.2: Run test, expect fail**

```bash
python3 -m pytest tests/test_publisher_fail_task_probe.py -v
```

Expected: 2 fails — `_safe_kb_probe.assert_called_once()` fails because no probe is wired yet.

- [ ] **Step 2.3: Wire probe into `_fail_task`**

Edit `publisher_base.py:_fail_task`. After `final_dump = self._save_debug_ui_dump(...)` block (around L1530-1532), add:

```python
        # ─── Tier-final shadow probe ───────────────────────────────────────
        # Pre-fail UI snapshot is the most reliable signal for obstacle KB:
        # whatever recovery did/didn't do, THIS is the screen we lost on.
        # Best-effort dump_ui — wrapped in try because adb may already be
        # dead at this point (the very reason we're failing).
        try:
            xml_at_fail = self.dump_ui()
        except Exception:
            xml_at_fail = None
        self._safe_kb_probe(xml_at_fail, step=step or 'unknown')
```

Place this BEFORE `meta = {'step': step}` (L1533), so the probe fires even if downstream meta-construction fails.

- [ ] **Step 2.4: Run test, expect green**

```bash
python3 -m pytest tests/test_publisher_fail_task_probe.py -v
```

Expected: 2 passed.

- [ ] **Step 2.5: Run full publisher_base tests for regression check**

```bash
python3 -m pytest tests/ -k 'publisher_base or fail_task or screencast' -v 2>&1 | tail -30
```

Expected: no new fails. If pre-existing fails surface (memory: 12 pre-existing fails on main), verify they match the documented baseline; do not "fix" them.

- [ ] **Step 2.6: Commit**

```bash
git add tests/test_publisher_fail_task_probe.py publisher_base.py
git commit -m "$(cat <<'EOF'
feat(obstacle-kb): tier-final shadow probe inside _fail_task

Wire _safe_kb_probe(dump_ui(), step) into _fail_task right after final
debug-dump capture. This single edit gives KB visibility into ALL
publisher failures regardless of platform or where the fail originated
(IG/TT/YT/switcher all call _fail_task eventually).

dump_ui wrapped in try because adb may be dead at this point — probe
helper handles None gracefully (no-op).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: IG caption-fill probes (горящий bug 2026-05-01)

**Files:**
- Modify: `publisher_instagram.py:1996, 2016, 2074, 2088`
- Add to: `tests/test_publisher_intermediate_probes.py`

**Why this task before others:** 5/5 IG retries 2026-05-01 failed at `ig_caption_fill_failed` and KB recorded zero outcomes — this is the signal-deficit driving the whole probe expansion. Closing this path first proves end-to-end probe → outcome → analytics chain works.

- [ ] **Step 3.1: Read each call-site to confirm xml-source available**

```bash
cd /home/claude-user/autowarm-testbench
sed -n '1985,2095p' publisher_instagram.py
```

For each meta.category event below, identify the local `xml`/`ui` variable that holds the current dump:

| Line | Category | Expected local xml var |
|---|---|---|
| 1996 | caption_focus_node_missing | dump from `_focus_caption_input_surgical` |
| 2016 | caption_focus_failed | similar |
| 2074 | caption_verify_failed | post-paste dump |
| 2088 | ig_caption_fill_failed | final-attempt dump |

Document the actual variable names found in evidence file (skip if straightforward).

- [ ] **Step 3.2: Write failing test (one test per site)**

Create `tests/test_publisher_intermediate_probes.py`:

```python
"""Integration tests for intermediate-tier obstacle KB probes.

Each test exercises one publisher path that logs meta.category=<obstacle>
and asserts _safe_kb_probe is invoked with appropriate (xml, step) args.

Tests use heavy mocking — adb/dump_ui/log_event all stubbed. Goal is
wiring verification, not behavior verification.
"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def ig_publisher():
    """Build a DevicePublisher-like instance with InstagramMixin methods
    accessible. Most internal state stubbed for isolation."""
    from publisher import DevicePublisher
    pub = DevicePublisher.__new__(DevicePublisher)
    pub.platform = 'instagram'
    pub.task_id = 9999
    pub._collected_ui_dumps = []
    pub._collected_screenshots = []
    pub._safe_kb_probe = MagicMock()
    pub.log_event = MagicMock()
    pub.set_step = MagicMock()
    pub.adb = MagicMock(return_value='')
    pub.dump_ui = MagicMock(return_value='<hierarchy>caption_input</hierarchy>')
    return pub


def test_caption_focus_node_missing_invokes_probe(ig_publisher):
    """When _focus_caption_input_surgical can't find caption_input_text_view,
    publisher logs caption_focus_node_missing — probe should fire on that xml."""
    # Simulate the focus-failure code path by directly exercising the helper
    # method that contains the log_event(caption_focus_node_missing) site.
    # Implementation note: actual entry-point depends on file structure;
    # if helper is private, call it directly via _Class__method or
    # exercise the public _fill_caption flow with mocked inner methods.
    pytest.skip("TODO: pin entry-point after reading L1996 context in step 3.1")


def test_caption_verify_failed_invokes_probe(ig_publisher):
    pytest.skip("TODO: similar to above for L2074")


def test_ig_caption_fill_failed_invokes_probe(ig_publisher):
    """ig_caption_fill_failed fires after 3 retries; probe must fire on
    final dump before fail-event."""
    pytest.skip("TODO: similar to above for L2088")
```

NOTE: this is a scaffold. Pin actual entry-points in step 3.1 by reading code, then de-skip and finish.

- [ ] **Step 3.3: De-skip tests with real entry-points**

After reading code in step 3.1, replace `pytest.skip(...)` lines with actual flow exercise. Pattern:

```python
def test_caption_verify_failed_invokes_probe(ig_publisher):
    # Mock dump_ui to return a "caption empty after paste" xml
    ig_publisher.dump_ui = MagicMock(return_value='<hierarchy><node text="" resource-id="caption_input_text_view"/></hierarchy>')
    # Force the verify-fail branch (text doesn't match expected)
    with patch.object(ig_publisher, '_caption_input_has_text', return_value=False):
        # Call the verifier method that contains L2074 log_event
        ig_publisher._verify_caption_filled('expected text')  # actual method TBD step 3.1
    
    # Probe must have been called with caption-related step
    assert ig_publisher._safe_kb_probe.called
    call_args = ig_publisher._safe_kb_probe.call_args
    assert 'caption' in str(call_args).lower()
```

- [ ] **Step 3.4: Run tests, expect 3 fails**

```bash
python3 -m pytest tests/test_publisher_intermediate_probes.py -k caption -v
```

Expected: 3 fails on `assert ig_publisher._safe_kb_probe.called`.

- [ ] **Step 3.5: Wire probes into 4 caption-fill sites**

For each site, insert `self._safe_kb_probe(xml, step='<category>')` IMMEDIATELY BEFORE the `self.log_event(...)` call. Use the local xml variable identified in step 3.1.

L1996 area (caption_focus_node_missing) — probe with the xml that lacks caption-input node.

L2016 area (caption_focus_failed) — probe with post-tap-attempts xml.

L2074 area (caption_verify_failed) — probe with post-paste xml that has empty/placeholder caption.

L2088 area (ig_caption_fill_failed) — probe with final-attempt xml. NOTE: this is the last log before returning False to caller; tier-final probe in `_fail_task` will ALSO fire on the eventual fail. Tier-intermediate site here gives signal even when retries succeed (caption-state visible mid-loop).

- [ ] **Step 3.6: Run tests, expect green**

```bash
python3 -m pytest tests/test_publisher_intermediate_probes.py -k caption -v
```

Expected: 3 passed (verify, fill_failed, focus_failed) + 1 caption_focus_node_missing.

- [ ] **Step 3.7: Commit**

```bash
git add tests/test_publisher_intermediate_probes.py publisher_instagram.py
git commit -m "$(cat <<'EOF'
feat(obstacle-kb): probe IG caption-fill obstacle states (4 sites)

Wire _safe_kb_probe at 4 intermediate sites in _fill_caption flow:
  - caption_focus_node_missing (L1996)
  - caption_focus_failed (L2016)
  - caption_verify_failed (L2074)
  - ig_caption_fill_failed (L2088)

Driver: 5/5 IG retries 2026-05-01 failed with ig_caption_fill_failed
and KB had zero outcomes — caption-fill path was unobserved by W2 KB.
This closes the signal gap; KB will start matching seeded patterns
on caption screens (and bugs_catcher_bot promoter, when wired in W5,
can suggest new patterns).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: IG critical intermediate probes (camera/editor)

**Files:**
- Modify: `publisher_instagram.py` lines 522, 711, 736, 759, 786, 858, 892, 1002, 1085, 1096, 1186, 1437, 1847
- Extend: `tests/test_publisher_intermediate_probes.py`

**Why:** These are the meta.category sites where IG recovery is mid-flight (escalation, draft modal, highlights state, gallery picker, wrong camera mode, About-account modal, upload timeout, etc.). Existing L927 probe covers `open_camera` start, but downstream obstacle states fall through.

**Sites to wire** (group by physical proximity in code; exclude success-marker sites like L96 ig_create_reels_tile_strict_match):

| Line | Category | step kwarg |
|---|---|---|
| 475 | ig_create_tile_strict_miss | `'ig_create_tile_strict_miss'` |
| 522 | ig_camera_escalation_attempted | `'ig_camera_escalation'` |
| 656 | ig_create_tile_strict_miss | `'ig_create_tile_strict_miss'` (recovery) |
| 711 | ig_draft_continuation_dismissed | `'ig_draft_continuation'` |
| 736 | ig_highlights_empty_state_seen | `'ig_highlights_empty_state'` |
| 759 | ig_gallery_picker_in_camera_loop | `'ig_gallery_picker_in_camera'` |
| 786 | ig_stuck_on_profile | `'ig_stuck_on_profile'` |
| 858 | ig_wrong_camera_mode | `'ig_wrong_camera_mode'` |
| 873 | ig_create_reels_tile_strict_miss | `'ig_create_reels_tile_miss'` |
| 892 | ig_about_account_modal | `'ig_about_account_modal'` |
| 1002 | ig_camera_open_reset_attempted | `'ig_camera_reset'` |
| 1085 | ig_wrong_camera_mode | `'ig_wrong_camera_mode'` |
| 1096 | ig_reels_tab_not_found_but_mode_ok | `'ig_reels_tab_missing'` |
| 1186 | ig_gallery_video_not_found_ui | `'ig_gallery_video_not_found'` |
| 1437 | gallery_shown_no_camera_option | `'gallery_no_camera_option'` |
| 1847 | ig_upload_confirmation_timeout | `'ig_upload_confirmation'` |

- [ ] **Step 4.1: Read each site to confirm xml var name**

```bash
for ln in 475 522 656 711 736 759 786 858 873 892 1002 1085 1096 1186 1437 1847; do
  echo "=== L$ln ==="
  sed -n "$((ln-8)),$((ln+3))p" publisher_instagram.py
done
```

Tabulate xml-var per line in evidence note. Common names: `ui`, `xml`, `dump`, `current_ui`. If a site has no nearby dump, use `self.dump_ui()` inline (slower, but still bounded — acceptable in obstacle-state).

- [ ] **Step 4.2: Write 3 representative integration tests**

Add to `tests/test_publisher_intermediate_probes.py`:
- `test_ig_upload_confirmation_timeout_probes()` — most frequent fail-state on prod
- `test_ig_wrong_camera_mode_probes()` — exercises Reels↔Stories detection
- `test_ig_about_account_modal_probes()` — recovery dialog handler

(Don't write 16 tests; representative sample is enough — refactor patterns can rely on tier-final probe + spot-checks.)

- [ ] **Step 4.3: Run tests, expect 3 fails**

```bash
python3 -m pytest tests/test_publisher_intermediate_probes.py -v
```

- [ ] **Step 4.4: Wire all 16 sites**

For each site, insert `self._safe_kb_probe(<xml-var>, step='<step>')` IMMEDIATELY BEFORE the `self.log_event(...)` line. Use exact `step=` values from table above.

If two sites in same code-block log to same category (L475 + L656 + L873 — strict-miss variants), each still gets its own probe call — they're at different points in the flow.

- [ ] **Step 4.5: Run tests, expect green**

```bash
python3 -m pytest tests/test_publisher_intermediate_probes.py tests/test_publisher_ig_camera_recovery.py -v 2>&1 | tail -30
```

Expected: new tests green; existing IG camera tests no regression.

- [ ] **Step 4.6: Commit**

```bash
git add tests/test_publisher_intermediate_probes.py publisher_instagram.py
git commit -m "$(cat <<'EOF'
feat(obstacle-kb): probe IG camera+editor intermediate obstacle states

Wire _safe_kb_probe at 16 meta.category sites in publisher_instagram.py
covering camera-loop, gallery picker, wrong-mode detection, draft-continuation
recovery, About-account modal, upload-confirmation timeout.

Together with task 3 (caption sites) and task 2 (tier-final), KB now
has signal coverage across the entire IG publish flow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: TT obstacle probes

**Files:**
- Modify: `publisher_tiktok.py:89, 458, 502, 661`
- Extend: `tests/test_publisher_intermediate_probes.py`

**Sites:**

| Line | Category | step kwarg |
|---|---|---|
| 89 | tt_share_activity_not_opened | `'tt_share_activity_not_opened'` |
| 458 | tt_fg_lost | `'tt_fg_lost'` |
| 502 | tt_notifications_modal_dismissed | `'tt_notifications_modal'` |
| 661 | tt_upload_confirmation_timeout | `'tt_upload_confirmation'` |

- [ ] **Step 5.1: Read each site**

```bash
for ln in 89 458 502 661; do
  echo "=== L$ln ==="
  sed -n "$((ln-6)),$((ln+3))p" publisher_tiktok.py
done
```

- [ ] **Step 5.2: Write 1 representative test for tt_upload_confirmation_timeout**

(Most frequent TT fail per memory.)

- [ ] **Step 5.3: Run, expect fail**

```bash
python3 -m pytest tests/test_publisher_intermediate_probes.py -k tt_upload -v
```

- [ ] **Step 5.4: Wire 4 sites**

Insert `self._safe_kb_probe(<xml-var>, step='<step>')` before each log_event.

- [ ] **Step 5.5: Run, expect green**

```bash
python3 -m pytest tests/test_publisher_intermediate_probes.py tests/test_publisher_tiktok.py -v 2>&1 | tail -20
```

- [ ] **Step 5.6: Commit**

```bash
git add tests/test_publisher_intermediate_probes.py publisher_tiktok.py
git commit -m "$(cat <<'EOF'
feat(obstacle-kb): probe TT publish obstacle states (4 sites)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: YT obstacle probes

**Files:**
- Modify: `publisher_youtube.py:147, 427, 642, 662`
- Extend: `tests/test_publisher_intermediate_probes.py`

**Sites:**

| Line | Category | step kwarg |
|---|---|---|
| 147 | yt_url_phone_verify_required | `'yt_phone_verify_required'` |
| 427 | yt_editor_stuck_detected | `'yt_editor_stuck'` |
| 642 | yt_editor_upload_timeout | `'yt_editor_upload_timeout'` |
| 662 | yt_editor_upload_timeout | `'yt_editor_upload_timeout'` |

- [ ] **Step 6.1: Read each site**

```bash
for ln in 147 427 642 662; do
  echo "=== L$ln ==="
  sed -n "$((ln-6)),$((ln+3))p" publisher_youtube.py
done
```

- [ ] **Step 6.2: Write 1 representative test for yt_editor_upload_timeout**

- [ ] **Step 6.3: Run, expect fail**

- [ ] **Step 6.4: Wire 4 sites**

- [ ] **Step 6.5: Run, expect green**

```bash
python3 -m pytest tests/test_publisher_intermediate_probes.py tests/test_publisher_youtube.py -v 2>&1 | tail -20
```

- [ ] **Step 6.6: Commit**

```bash
git add tests/test_publisher_intermediate_probes.py publisher_youtube.py
git commit -m "$(cat <<'EOF'
feat(obstacle-kb): probe YT publish obstacle states (4 sites)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Smoke + push + 60-min soak verification

**Files:**
- Create: `.ai-factory/evidence/probe-coverage-stage-a-20260502.md`

- [ ] **Step 7.1: Run full pytest suite**

```bash
cd /home/claude-user/autowarm-testbench
python3 -m pytest tests/ -v 2>&1 | tail -40
```

Expected: all new tests green. Pre-existing fails documented in `project_publisher_obstacle_kb` memory (12 fails on main: test_publish_guard, test_testbench_orchestrator, etc.) MUST match pre-fix count — no NEW pre-existing fails introduced by refactor.

If new fails surface: STOP, investigate. Tier-final `_fail_task` modification touches a hot path — most likely regression site.

- [ ] **Step 7.2: Re-seed obstacle KB if pytest cleared it**

```bash
psql -h localhost -U openclaw -d openclaw -c "SELECT count(*) FROM publisher_obstacles WHERE source LIKE 'manual_seed%';"
# if 0:
python3 obstacle_seed.py from-constants
```

- [ ] **Step 7.3: Push branch + open PR**

```bash
git push -u origin feature/obstacle-kb-probe-coverage-20260502
gh pr create --title "Obstacle KB Stage A: probe coverage expansion" --body "$(cat <<'EOF'
## Summary
- Tier-final probe in `_fail_task` (catches all platforms' fail-paths)
- Tier-intermediate `_safe_kb_probe` helper + 24 probe call-sites (IG/TT/YT)
- 4 IG caption-fill sites (closes 2026-05-01 ig_caption_fill_failed signal gap)

## Test plan
- [ ] `python3 -m pytest tests/test_obstacle_kb_safe_probe.py tests/test_publisher_fail_task_probe.py tests/test_publisher_intermediate_probes.py -v` green
- [ ] Pre-existing 12 failures on main unchanged (no new regressions)
- [ ] After merge: `psql -c "SELECT count(*) FROM publisher_obstacle_outcomes WHERE outcome='shadow_match' AND created_at >= NOW() - INTERVAL '1 hour'"` > 0 within 60 min of deploy

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 7.4: Merge to main + auto-deploy**

After PR review:
```bash
gh pr merge --squash --delete-branch
```

Auto-push hook will sync to `/root/.openclaw/workspace-genri/autowarm/`. Then PM2 restart:

```bash
sudo -n pm2 restart autowarm autowarm-testbench
sudo -n pm2 save
```

- [ ] **Step 7.5: 60-min soak — verify shadow_match outcomes appear**

Wait 60 minutes for natural publish-traffic to flow through publishers. Then:

```bash
psql -h localhost -U openclaw -d openclaw -c "
SELECT
  o.obstacle_id,
  obs.platform,
  obs.publisher_step,
  count(*) AS matches,
  max(o.created_at) AS last_match
FROM publisher_obstacle_outcomes o
JOIN publisher_obstacles obs ON obs.obstacle_id = o.obstacle_id
WHERE o.outcome='shadow_match'
  AND o.created_at >= NOW() - INTERVAL '1 hour'
GROUP BY 1, 2, 3
ORDER BY matches DESC
LIMIT 20;
"
```

Expected: ≥1 row. If 0 rows after 60 min:
- Check pm2 logs for `[obstacle-kb-shadow]` warnings
- Verify `obstacle_kb_disabled = false` in system_flags
- Verify probes actually called: add temp DEBUG log inside `_safe_kb_probe` and re-deploy

- [ ] **Step 7.6: Document evidence**

Create `/home/claude-user/contenthunter/.ai-factory/evidence/probe-coverage-stage-a-20260502.md`:

```markdown
# Stage A Evidence — Probe Coverage Expansion

**Branch:** feature/obstacle-kb-probe-coverage-20260502 → main `<merge-sha>`
**PR:** #<num>
**Deploy:** `<timestamp>`, PM2 restart #<n>

## Coverage delta
| Tier | Sites before | Sites after | Δ |
|---|---|---|---|
| Final (_fail_task) | 0 | 1 | +1 |
| Intermediate | 5 | ~29 | +24 |

## 60-min soak
| Obstacle | Platform | Step | Matches |
|---|---|---|---|
| ... | ... | ... | ... |

## Pre-existing failures (unchanged baseline)
- 12 fails per memory `project_publisher_obstacle_kb` ✓
```

- [ ] **Step 7.7: Update memory**

Update `project_publisher_obstacle_kb.md`:
- Note Stage A shipped (W2.E follow-up).
- New baseline: ~29 probe sites instead of 5.
- shadow_match count after 60 min for next-session anchor.

If `ig_caption_fill_failed` matches appeared → memory `project_ig_caption_fill_persistent_bug.md` can mark "KB now observing" status; next step is seeding caption-specific obstacle patterns from the matched signatures.

---

## Self-review — spec coverage check

| Spec requirement | Task coverage |
|---|---|
| Single helper extracted (W2 follow-up) | Task 1 |
| 5 existing sites refactored (no behavior change) | Task 1 |
| Tier-final probe (catches all fail-paths) | Task 2 |
| ig_caption_fill_failed coverage (горящий bug) | Task 3 |
| IG intermediate camera/editor probes | Task 4 |
| TT obstacle probes | Task 5 |
| YT obstacle probes | Task 6 |
| Smoke + soak verification | Task 7 |

Out-of-scope (defer to Stage B):
- Switcher additional fail-paths beyond existing 4 (no urgent signal-gap)
- Promoter T1/T2/T3 (W5 in master plan)
- Anthropic switch (W3 in master plan)
- Apply-mode flip (W4 in master plan)
- bugs_catcher_bot extension for obstacle suggestions (W5)
