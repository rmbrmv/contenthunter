# IG Share `action_bar OK` Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Tier 1.5 fallback in `_wait_instagram_upload` that taps the editor's top-right `action_bar_button_text` (`ОК` / `OK`) once after the existing share-button retries fail, before declaring `ig_share_tap_no_progress`.

**Architecture:** One new helper `_tap_ig_action_bar_ok(ui_xml) -> bool` in `publisher_instagram.py` alongside the existing `_long_press_share_button`. One small edit in `_wait_instagram_upload` inserts the helper call between the share-button retry loop and the fail-fast emit. One new metadata flag (`ok_fallback_attempted`) on the existing `ig_share_tap_no_progress` event so the rollout SQL can distinguish "OK tap dispatched but didn't rescue" from "OK helper aborted (no match)". Eleven new tests TDD-first.

**Tech Stack:** Python 3, pytest, unittest.mock; production target `/root/.openclaw/workspace-genri/autowarm/`. PRs land in `GenGo2/delivery-contenthunter`. Source-of-truth repo: `rmbrmv/contenthunter`.

**Spec:** `docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md` (commits `f00545613`, `c0b36ae05` — codex round 1 0 P1).

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `publisher_instagram.py` (around line 904) | Modify | Add `_tap_ig_action_bar_ok` helper next to `_long_press_share_button` |
| `publisher_instagram.py:2594-2637` | Modify | Insert Tier 1.5 OK-fallback between share-button retry loop and fail-fast emit; set `ok_fallback_attempted` meta flag from `ok_tap_dispatched` local |
| `tests/test_ig_share_ok_fallback.py` | Create | 8 unit tests for the helper (locale, clickable guard, malformed bounds, adb error swallow, no-match returns False) |
| `tests/test_publisher_instagram_share_retry.py` | Modify | Add 3 integration tests covering the Tier 1.5 wiring (rescue, no-rescue, anti-regression) |

Worktree convention per [[feedback_parallel_claude_sessions]] + [[feedback_plan_full_mode_branch]]: all work happens in a git worktree off branch `fix-ig-share-ok-fallback-20260513` so prod `main` is not blocked.

---

## Task 1: Set up worktree + branch

**Files:**
- New worktree dir: `/home/claude-user/autowarm-fix-ig-share-ok-fallback-20260513/`
- Branch: `fix-ig-share-ok-fallback-20260513` off `origin/main`

- [ ] **Step 1: Fetch latest main**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git fetch origin main
```

Expected: prints either no updates or `From .../delivery-contenthunter * branch main → FETCH_HEAD`.

- [ ] **Step 2: Confirm main is clean**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git status --short
```

Expected: empty output. If non-empty (a parallel session has uncommitted changes), **abort and report BLOCKED** — do not stash or discard.

- [ ] **Step 3: Create worktree on a new branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm && \
  git worktree add -b fix-ig-share-ok-fallback-20260513 \
    /home/claude-user/autowarm-fix-ig-share-ok-fallback-20260513 origin/main
```

Expected: `Preparing worktree (new branch 'fix-ig-share-ok-fallback-20260513')` then `HEAD is now at <sha> <subject>`.

- [ ] **Step 4: Verify worktree**

```bash
cd /home/claude-user/autowarm-fix-ig-share-ok-fallback-20260513 && \
  git rev-parse --abbrev-ref HEAD && \
  git log --oneline -1
```

Expected: prints `fix-ig-share-ok-fallback-20260513` followed by the latest origin/main commit (currently `ec91909` from PR #48).

---

## Task 2: Write 8 helper unit tests (RED first)

**Files:**
- Create: `tests/test_ig_share_ok_fallback.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_ig_share_ok_fallback.py` with exactly this content:

```python
"""Unit tests for _tap_ig_action_bar_ok helper (Tier 1.5 fallback).

When IG silently ignores share_button taps, the editor's top-right
`action_bar_button_text` (ОК / OK) is the alternative finalize control.
This helper finds and taps it.

Spec: docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md §2.1
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _ui_with_ok(label: str = 'ОК',
                bounds: str = '[930,117][1057,253]',
                clickable: str = 'true',
                rid_suffix: str = ':id/action_bar_button_text') -> str:
    rid = f'com.instagram.android{rid_suffix}' if rid_suffix else ''
    return (
        "<?xml version='1.0'?><hierarchy>"
        f'<node text="{label}" content-desc="{label}" '
        f'resource-id="{rid}" '
        f'bounds="{bounds}" clickable="{clickable}"/>'
        '</hierarchy>'
    )


def _ui_empty() -> str:
    return "<?xml version='1.0'?><hierarchy/>"


def _make_publisher_stub():
    from publisher import DevicePublisher
    stub = DevicePublisher.__new__(DevicePublisher)
    stub.adb = MagicMock(return_value='')
    return stub


# ─── Test 1: Russian label matches and centre coords are correct ───────────

def test_tap_ig_action_bar_ok_finds_ru_label():
    """bounds=[930,117][1057,253] → centre=(993, 185), adb command exact."""
    stub = _make_publisher_stub()

    result = stub._tap_ig_action_bar_ok(_ui_with_ok(label='ОК'))

    assert result is True
    stub.adb.assert_called_once_with('input tap 993 185')


# ─── Test 2: English label also matches ────────────────────────────────────

def test_tap_ig_action_bar_ok_finds_en_label():
    stub = _make_publisher_stub()

    result = stub._tap_ig_action_bar_ok(_ui_with_ok(label='OK'))

    assert result is True
    stub.adb.assert_called_once()


# ─── Test 3: No matching node returns False, no adb dispatch ───────────────

def test_tap_ig_action_bar_ok_no_button_returns_false():
    stub = _make_publisher_stub()

    result = stub._tap_ig_action_bar_ok(_ui_empty())

    assert result is False
    stub.adb.assert_not_called()


# ─── Test 4: Non-clickable matching node returns False ─────────────────────

def test_tap_ig_action_bar_ok_non_clickable_returns_false():
    stub = _make_publisher_stub()

    result = stub._tap_ig_action_bar_ok(
        _ui_with_ok(label='ОК', clickable='false'),
    )

    assert result is False
    stub.adb.assert_not_called()


# ─── Test 5: Other-locale label (e.g. Готово) returns False ────────────────

def test_tap_ig_action_bar_ok_other_text_returns_false():
    """Locale guard: tap_element should not match arbitrary action-bar text."""
    stub = _make_publisher_stub()

    result = stub._tap_ig_action_bar_ok(_ui_with_ok(label='Готово'))

    assert result is False
    stub.adb.assert_not_called()


# ─── Test 6: Empty XML returns False ───────────────────────────────────────

def test_tap_ig_action_bar_ok_empty_xml_returns_false():
    stub = _make_publisher_stub()

    result = stub._tap_ig_action_bar_ok('')

    assert result is False
    stub.adb.assert_not_called()


# ─── Test 7: Malformed bounds returns False ────────────────────────────────

def test_tap_ig_action_bar_ok_malformed_bounds_returns_false():
    stub = _make_publisher_stub()

    result = stub._tap_ig_action_bar_ok(
        _ui_with_ok(label='ОК', bounds='invalid-bounds'),
    )

    assert result is False
    stub.adb.assert_not_called()


# ─── Test 8: adb exception swallowed, returns False ────────────────────────

def test_tap_ig_action_bar_ok_adb_exception_returns_false():
    stub = _make_publisher_stub()
    stub.adb = MagicMock(side_effect=RuntimeError('boom'))

    result = stub._tap_ig_action_bar_ok(_ui_with_ok(label='ОК'))

    assert result is False
    stub.adb.assert_called_once()
```

- [ ] **Step 2: Run the new tests — confirm 8 FAIL (helper not defined yet)**

```bash
cd /home/claude-user/autowarm-fix-ig-share-ok-fallback-20260513 && \
  pytest tests/test_ig_share_ok_fallback.py -v
```

Expected: all 8 tests FAIL with `AttributeError: 'DevicePublisher' object has no attribute '_tap_ig_action_bar_ok'`. If any test passes pre-implementation, **stop and investigate**.

- [ ] **Step 3: Commit the RED helper tests**

```bash
git add tests/test_ig_share_ok_fallback.py
git commit -m "$(cat <<'EOF'
test(ig): RED tests for _tap_ig_action_bar_ok helper (Tier 1.5 fallback)

8 TDD-first tests covering action_bar OK button helper: locale (RU/EN),
clickable guard, malformed bounds, empty XML, adb exception swallow,
other-text-locale guard, no-match returns False. All fail with
AttributeError pre-implementation.

Spec: docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: clean commit on `fix-ig-share-ok-fallback-20260513`.

---

## Task 3: Implement `_tap_ig_action_bar_ok` helper

**Files:**
- Modify: `publisher_instagram.py` (insert new method right after `_long_press_share_button`)

- [ ] **Step 1: Locate `_long_press_share_button` end-of-body**

```bash
grep -n 'def _long_press_share_button\|def _is_ig_editor_still_visible' publisher_instagram.py
```

Expected: two line-number matches for the existing methods. The new helper goes between them.

- [ ] **Step 2: Insert the new helper after `_long_press_share_button`'s closing `return False`**

Find the existing `_long_press_share_button` (around line 904). It ends with a `return False` after the `for` loop's final `except` branch. Insert the new method directly after — keeping a blank line for readability.

Use the `Edit` tool with this exact `old_string` (the tail of `_long_press_share_button`):

```python
        for n in root.iter('node'):
            rid = n.get('resource-id', '')
            if rid.endswith(':id/share_button') and n.get('clickable') == 'true':
                bounds = n.get('bounds', '')
                m = _re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if not m:
                    return False
                x1, y1, x2, y2 = (int(m.group(i)) for i in (1, 2, 3, 4))
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                try:
                    self.adb(f'input swipe {cx} {cy} {cx} {cy} {hold_ms}')
                    return True
                except Exception:
                    return False
        return False
```

Replace with:

```python
        for n in root.iter('node'):
            rid = n.get('resource-id', '')
            if rid.endswith(':id/share_button') and n.get('clickable') == 'true':
                bounds = n.get('bounds', '')
                m = _re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if not m:
                    return False
                x1, y1, x2, y2 = (int(m.group(i)) for i in (1, 2, 3, 4))
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                try:
                    self.adb(f'input swipe {cx} {cy} {cx} {cy} {hold_ms}')
                    return True
                except Exception:
                    return False
        return False

    def _tap_ig_action_bar_ok(self, ui_xml: str) -> bool:
        """Find and tap the editor's top-right action-bar `OK` button.

        On the IG Reels editor/share screen the top-right confirm is a
        clickable node with resource-id ending in `:id/action_bar_button_text`
        and text=='ОК' (Russian locale) or 'OK' (English locale). Used as a
        Tier 1.5 fallback when `share_button` re-taps are ignored by IG.

        Spec: docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md §2.1

        Returns:
            True if a matching node was found and the tap command was sent.
            False if no match, malformed bounds, or adb dispatch raised.
        """
        if not ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        import re as _re
        for n in root.iter('node'):
            rid = n.get('resource-id', '')
            if not rid.endswith(':id/action_bar_button_text'):
                continue
            if n.get('clickable') != 'true':
                continue
            label = (n.get('text', '') or n.get('content-desc', '')).strip()
            if label not in ('ОК', 'OK'):
                continue
            bounds = n.get('bounds', '')
            m = _re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
            if not m:
                return False
            x1, y1, x2, y2 = (int(m.group(i)) for i in (1, 2, 3, 4))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            try:
                self.adb(f'input tap {cx} {cy}')
                return True
            except Exception:
                return False
        return False
```

- [ ] **Step 3: Run the helper tests — all 8 must pass**

```bash
pytest tests/test_ig_share_ok_fallback.py -v
```

Expected: 8 / 8 PASS. If any test still fails, the helper implementation has a bug — fix and re-run before continuing.

- [ ] **Step 4: Sanity-check no other IG test broke**

```bash
pytest tests/test_ig_long_press_helper.py tests/test_ig_editor_visible_helper.py -v
```

Expected: all PASS (these test sibling helpers — the new helper must not have edited or shadowed them).

- [ ] **Step 5: Commit the helper**

```bash
git add publisher_instagram.py
git commit -m "$(cat <<'EOF'
fix(ig): add _tap_ig_action_bar_ok helper (Tier 1.5 fallback)

New helper finds the editor's top-right `action_bar_button_text` OK button
(locale-restricted to ОК / OK) and dispatches a single `input tap` at the
node's centre. Used as alternative-action fallback when IG silently
ignores share_button taps on the Reels editor screen.

8 unit tests GREEN.

Spec: docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Write 3 integration tests for Tier 1.5 wiring (RED first)

**Files:**
- Modify: `tests/test_publisher_instagram_share_retry.py` (append 3 tests + helper XML)

- [ ] **Step 1: Locate the existing test file's helper section**

```bash
grep -n '^def _editor_xml\|^def _post_publish_xml\|^def _make_publisher_stub\|^def test_' \
  tests/test_publisher_instagram_share_retry.py
```

Expected: three helper functions (`_editor_xml`, `_post_publish_xml`, `_make_publisher_stub`) followed by the two existing tests (`test_share_retry_progresses_after_first_retry`, `test_share_retry_exhausted_emits_no_progress`).

- [ ] **Step 2: Append a new XML helper with the OK button present**

Find the existing `_post_publish_xml()` function's closing `)` (around line 50). Insert this new helper function immediately after it (before `_make_publisher_stub`):

```python
def _editor_xml_with_ok() -> str:
    """Editor XML — caption_input_text_view + clickable share_button + clickable action_bar OK.

    Same structure as _editor_xml but includes the top-right `OK` action-bar button
    so _tap_ig_action_bar_ok can find a matching node.
    """
    return (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="caption text" content-desc="" '
        'resource-id="com.instagram.android:id/caption_input_text_view" '
        'bounds="[100,100][900,200]" clickable="true"/>'
        '<node text="ОК" content-desc="ОК" '
        'resource-id="com.instagram.android:id/action_bar_button_text" '
        'bounds="[930,117][1057,253]" clickable="true"/>'
        '<node text="" content-desc="" bounds="[0,300][100,400]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,400][100,500]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,500][100,600]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,600][100,700]" clickable="false"/>'
        '<node text="" content-desc="Поделиться" '
        'resource-id="com.instagram.android:id/share_button" '
        'bounds="[563,2025][1035,2149]" clickable="true"/>'
        '</hierarchy>'
    )
```

- [ ] **Step 3: Append the 3 integration tests at the end of the file**

Append this block to the end of `tests/test_publisher_instagram_share_retry.py`:

```python
# ─── Tier 1.5: action_bar OK fallback ──────────────────────────────────────

def test_ok_fallback_rescues_after_share_retries_exhausted():
    """Share retries exhausted → OK fallback tap dispatched → editor disappears → progressed.

    dump_ui sequence:
      1. iter0 diag → editor_xml_with_ok
      2. retry 1 check → editor_xml_with_ok → True → tap_element → log retry_n=1
      3. retry 2 check → editor_xml_with_ok → True → tap_element → log retry_n=2
      4. post-retry-loop visibility check → editor_xml_with_ok → True → enter OK branch
      5. ok_ui dump → editor_xml_with_ok → _tap_ig_action_bar_ok returns True → ok_tap_dispatched=True
      6. post-OK visibility check → post_publish_xml → False → progressed=True
      7. final fail-path check skipped (progressed=True)
      8. main 30-iter loop continues on post_publish_xml — irrelevant to this test
    """
    dump_responses = [
        _editor_xml_with_ok(),  # iter0
        _editor_xml_with_ok(),  # retry 1 check
        _editor_xml_with_ok(),  # retry 2 check
        _editor_xml_with_ok(),  # post-retry-loop visibility check (in OK fallback gate)
        _editor_xml_with_ok(),  # ok_ui (helper inspects this)
        _post_publish_xml(),    # post-OK visibility check — progressed
    ] + [_post_publish_xml()] * 100

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    ok_attempted = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_ok_button_attempted'
    ]
    no_progress = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
    ]

    assert len(ok_attempted) == 1, \
        f'expected 1 ig_share_ok_button_attempted, got {len(ok_attempted)}'
    assert len(no_progress) == 0, \
        f'expected 0 ig_share_tap_no_progress (rescued), got {len(no_progress)}'


def test_ok_fallback_fails_emits_share_no_progress_with_flag():
    """OK fallback fires but editor still visible → fail-fast with ok_fallback_attempted=True.

    dump_ui sequence:
      1-3: editor_xml_with_ok (iter0 + 2 retry checks)
      4: editor_xml_with_ok (OK gate)
      5: editor_xml_with_ok (ok_ui)
      6: editor_xml_with_ok (post-OK check — still visible)
      7: editor_xml_with_ok (final fail-path check)
    """
    dump_responses = [_editor_xml_with_ok()] * 50

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)

    with patch('time.sleep'):
        result = stub._wait_instagram_upload()

    ok_attempted = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_ok_button_attempted'
    ]
    no_progress = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
    ]

    assert len(ok_attempted) == 1, \
        f'expected 1 ig_share_ok_button_attempted, got {len(ok_attempted)}'
    assert len(no_progress) == 1, \
        f'expected 1 ig_share_tap_no_progress (OK did not rescue), got {len(no_progress)}'
    assert no_progress[0].kwargs['meta'].get('ok_fallback_attempted') is True, \
        'ok_fallback_attempted must be True when helper dispatched a tap'
    assert result is False


def test_ok_fallback_not_called_when_share_retry_progresses():
    """Share retry 1 progressed → OK fallback NOT triggered (anti-regression on success path).

    dump_ui sequence:
      1: editor_xml (iter0 — uses the OLD editor XML without OK button to be extra-strict;
         even if OK were present, the gating `if not progressed` would skip it after success)
      2: editor_xml (retry 1 check)
      3: post_publish_xml (retry 2 check — progressed=True, break)
    """
    dump_responses = [
        _editor_xml(),       # iter0
        _editor_xml(),       # retry 1 check before re-tap
        _post_publish_xml(), # retry 2 check — progressed
    ] + [_post_publish_xml()] * 100

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    ok_attempted = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_ok_button_attempted'
    ]
    no_progress = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
    ]

    assert len(ok_attempted) == 0, \
        f'expected 0 ig_share_ok_button_attempted (share retry progressed), got {len(ok_attempted)}'
    assert len(no_progress) == 0, \
        f'expected 0 ig_share_tap_no_progress, got {len(no_progress)}'
```

- [ ] **Step 4: Run the three new tests — confirm RED**

```bash
pytest tests/test_publisher_instagram_share_retry.py -v
```

Expected verdicts:
- `test_share_retry_progresses_after_first_retry` — PASS (existing, unchanged)
- `test_share_retry_exhausted_emits_no_progress` — **may FAIL on the `ok_fallback_attempted` field expectation** (this assertion was added by Edit 3 below; the existing test may not check it). Read its current body first; if it doesn't reference `ok_fallback_attempted`, leave it as-is.
- `test_ok_fallback_rescues_after_share_retries_exhausted` — **FAIL** (Tier 1.5 wiring not in code yet; either no `ig_share_ok_button_attempted` event is emitted or `dump_ui` runs out and raises StopIteration)
- `test_ok_fallback_fails_emits_share_no_progress_with_flag` — **FAIL** (same reason)
- `test_ok_fallback_not_called_when_share_retry_progresses` — **PASS by accident** (Tier 1.5 absent → never fires regardless of progressed flag, so assertion holds; this is the anti-regression baseline)

If the existing `test_share_retry_exhausted_emits_no_progress` regresses unexpectedly, stop and investigate before continuing.

- [ ] **Step 5: Commit the RED integration tests**

```bash
git add tests/test_publisher_instagram_share_retry.py
git commit -m "$(cat <<'EOF'
test(ig): RED integration tests for OK fallback Tier 1.5 wiring

3 tests covering OK fallback rescue path, no-rescue + ok_fallback_attempted
flag, and anti-regression on share-retry-progresses path. Two FAIL pre-fix,
one PASS by accident (anti-regression baseline).

Spec: docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Apply Tier 1.5 wiring in `_wait_instagram_upload`

**Files:**
- Modify: `publisher_instagram.py:2594-2637` (the existing Tier 1 retry block)

- [ ] **Step 1: Locate the existing fail-fast emit line**

```bash
grep -n "ig_share_tap_no_progress" publisher_instagram.py | head -5
```

Expected: at least one match in `_wait_instagram_upload` (the existing emit). Confirm the surrounding context matches §2 of the spec (the `if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):` gate before `self.log_event('error', 'Instagram: Share tap не прогрессировал ...')`).

- [ ] **Step 2: Apply the wiring edit**

Use the `Edit` tool with this exact `old_string`:

```python
                if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
                    self.log_event('error',
                                   'Instagram: Share tap не прогрессировал после retries',
                                   meta={'category': 'ig_share_tap_no_progress',
                                         'platform': self.platform,
                                         'step': 'wait_upload',
                                         'retries_exhausted': 2})
                    try:
                        self._save_debug_artifacts('instagram_share_no_progress')
                    except Exception as _art_e:
                        log.warning(f'_save_debug_artifacts failed: {_art_e}')
                    share_no_progress = True
```

Replace with:

```python
                # Tier 1.5 — one fallback tap on action_bar OK before failing.
                # `ok_tap_dispatched` is the source of truth for the rollout query:
                # True ONLY if the helper actually found a matching node and ADB
                # accepted the tap. False on no-match / malformed bounds / ADB error.
                ok_tap_dispatched = False
                if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
                    ok_ui = self.dump_ui()
                    if self._tap_ig_action_bar_ok(ok_ui):
                        ok_tap_dispatched = True
                        self.log_event('info',
                                       'Instagram: action_bar OK fallback tap',
                                       meta={'category': 'ig_share_ok_button_attempted',
                                             'platform': self.platform})
                        time.sleep(3)
                        if not self._is_ig_editor_still_visible(self.dump_ui()):
                            progressed = True

                if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
                    self.log_event('error',
                                   'Instagram: Share tap не прогрессировал после retries',
                                   meta={'category': 'ig_share_tap_no_progress',
                                         'platform': self.platform,
                                         'step': 'wait_upload',
                                         'retries_exhausted': 2,
                                         'ok_fallback_attempted': ok_tap_dispatched})
                    try:
                        self._save_debug_artifacts('instagram_share_no_progress')
                    except Exception as _art_e:
                        log.warning(f'_save_debug_artifacts failed: {_art_e}')
                    share_no_progress = True
```

- [ ] **Step 3: Run the integration test file — all 5 tests must pass**

```bash
pytest tests/test_publisher_instagram_share_retry.py -v
```

Expected verdicts:
- `test_share_retry_progresses_after_first_retry` — PASS
- `test_share_retry_exhausted_emits_no_progress` — PASS
- `test_ok_fallback_rescues_after_share_retries_exhausted` — PASS
- `test_ok_fallback_fails_emits_share_no_progress_with_flag` — PASS
- `test_ok_fallback_not_called_when_share_retry_progresses` — PASS

If any test fails, the wiring has a bug — fix and re-run before continuing.

- [ ] **Step 4: Run the helper tests too — must remain GREEN**

```bash
pytest tests/test_ig_share_ok_fallback.py tests/test_ig_editor_visible_helper.py tests/test_ig_long_press_helper.py -v
```

Expected: 8 helper tests + 2 editor-visible tests + 4 long-press tests, all PASS.

- [ ] **Step 5: Run the full IG-suite for incidental regressions**

Run pytest first (so its exit status is visible), then look at the tail for context:

```bash
pytest tests/ -x -k "ig_ or instagram" -q > /tmp/ig-suite.log 2>&1
status=$?
tail -30 /tmp/ig-suite.log
echo "pytest exit=$status"
```

Do NOT use `pytest ... | tail` — the pipe hides pytest's exit code behind `tail`'s success.

Decision rule:
- `pytest exit=0` → proceed.
- `pytest exit=1` and the failures touch `_wait_instagram_upload`, `_tap_ig_action_bar_ok`, or `_is_ig_editor_still_visible` → **stop and fix**.
- `pytest exit=1` but the failures match pre-existing names that already fail on `origin/main` → verify by checking `origin/main` separately, then document the failing test names in the next commit message and proceed. See [[project_validator_stale_generate_description_tests]] for the precedent.

- [ ] **Step 6: Commit the wiring**

```bash
git add publisher_instagram.py
git commit -m "$(cat <<'EOF'
fix(ig): Tier 1.5 action_bar OK fallback in _wait_instagram_upload

After 2 share-button re-taps fail and the editor is still visible, attempt
one tap on the top-right action_bar OK button before declaring
ig_share_tap_no_progress. Emits ig_share_ok_button_attempted (info) on
dispatch; sets meta.ok_fallback_attempted on the existing fail event so
the rollout SQL can distinguish "tap dispatched but didn't rescue" from
"helper aborted (no match)".

11 tests GREEN (8 helper + 3 integration). Existing IG share suite GREEN.

Spec: docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Codex review on the full diff

**Files:** none modified; review-only.

- [ ] **Step 1: Generate the cumulative diff vs origin/main**

```bash
git diff origin/main...HEAD -- publisher_instagram.py tests/test_ig_share_ok_fallback.py \
  tests/test_publisher_instagram_share_retry.py > /tmp/ig-share-ok-diff.patch
wc -l /tmp/ig-share-ok-diff.patch
```

Expected: a non-empty patch on the order of 200-300 lines.

- [ ] **Step 2: Pipe diff into codex review (per [[feedback_codex_sandbox_broken]] — `--base main` is broken)**

```bash
cat /tmp/ig-share-ok-diff.patch | ~/.local/bin/codex review - 2>&1 | tail -80
```

- [ ] **Step 3: Triage codex findings**

- `0 P1` (or no review comments) → proceed to Task 7.
- `[P1]` findings → apply fixes as new commits (NOT `--amend`), re-run Step 2, repeat until 0 P1. Per the rule in [[feedback_codex_review_specs]].
- `[P2]` / `[P3]` findings → non-blocking, but trivial fixes are worth applying inline before moving on.

- [ ] **Step 4: Record codex outcome in commit history**

If codex returned non-zero findings, ensure each fix lands as its own commit with the message format:

```
fix(ig): <subject> (codex round N P1|P2|P3)
```

so the audit trail matches the pattern established in [[project_session_2026_05_11_shipped]] and [[project_watchdog_ping_regression_shipped]].

---

## Task 7: Push branch and open PR

**Files:** none modified.

- [ ] **Step 1: Pull main to detect drift**

```bash
git fetch origin main && git log --oneline origin/main..HEAD
```

Expected: only the commits from Tasks 2-6 (helper RED tests, helper impl, integration RED tests, wiring, optional codex fix commits).

If `git log --oneline HEAD..origin/main` is non-empty, a parallel session moved main forward — rebase (`git rebase origin/main`) and re-run Task 5 Step 5 (full IG-suite) before pushing.

- [ ] **Step 2: Push the branch**

```bash
. ~/secrets/github.env 2>/dev/null || . ~/secrets/github-gengo2.env
git push -u origin fix-ig-share-ok-fallback-20260513
```

Expected: branch pushed. (Note: due to the post-commit auto-push hook on the shared `.git/`, the branch may already be on the remote — `Everything up-to-date` is acceptable per [[reference_autowarm_git_hook]].)

- [ ] **Step 3: Open PR against `GenGo2/delivery-contenthunter` main**

```bash
export GH_TOKEN=$(. ~/secrets/github-gengo2.env && echo "$GITHUB_TOKEN_GENGO2")
gh pr create --repo GenGo2/delivery-contenthunter \
  --title "fix(ig): action_bar OK fallback after share retries (Tier 1.5)" \
  --body "$(cat <<'EOF'
## Summary

- Add helper `_tap_ig_action_bar_ok` that finds and taps the editor's top-right `action_bar_button_text` (`ОК` / `OK`) — alternative finalize control on the IG Reels editor screen.
- Wire it into `_wait_instagram_upload` as a Tier 1.5 fallback: after the existing 2 share-button re-taps, one tap on OK before declaring `ig_share_tap_no_progress`.
- New `ig_share_ok_button_attempted` info event for triage; `ok_fallback_attempted` flag on the existing fail event reflects whether a tap was actually dispatched.

## Why

`ig_share_tap_no_progress` is the top IG failure pattern: 11-18/24h post-PR #37 revert (which removed the Tier 2 long-press that rescued 0/19). UI dumps from 5 fresh failing tasks all show the same Reels editor screen with the share button clickable and at the expected coordinates — IG silently ignores the tap. The OK button is a structurally distinct control on the same screen; if IG accepts it, rescue rate will be positive.

Spec (full RC analysis): `docs/superpowers/specs/2026-05-13-ig-share-ok-fallback-design.md`
Plan: `docs/superpowers/plans/2026-05-13-ig-share-ok-fallback-plan.md`

## Test plan

- [x] 8 new helper tests in `tests/test_ig_share_ok_fallback.py` (RED before fix, GREEN after).
- [x] 3 new integration tests in `tests/test_publisher_instagram_share_retry.py` (RED + 1 baseline-PASS before, GREEN after).
- [x] Existing IG share suite remains GREEN.
- [x] Codex review on spec → 0 P1 (round 1).
- [x] Codex review on plan → 0 P1.
- [x] Codex review on PR diff → 0 P1.
- [ ] 24h post-deploy: `ok_attempted_24h > 0` and `ok_rescued_24h / ok_attempted_24h ≥ 30%`. (Acceptance bands in spec § 5.)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Save it for the evidence doc.

---

## Task 8: Auto-deploy via PR squash-merge

**Files:** none in this worktree.

- [ ] **Step 1: Merge the PR**

Once codex on PR diff returns 0 P1 (Task 6) and the PR is ready, the user authorises the merge. The squash-merge command:

```bash
export GH_TOKEN=$(. ~/secrets/github-gengo2.env && echo "$GITHUB_TOKEN_GENGO2")
gh pr merge <pr-number> --repo GenGo2/delivery-contenthunter --squash --delete-branch
```

Expected: PR closed, branch deleted.

- [ ] **Step 2: Pull the merge commit into the prod tree**

```bash
cd /root/.openclaw/workspace-genri/autowarm && \
  git fetch origin main && \
  git pull --ff-only origin main
```

Expected: fast-forward of `a7e591f..ec91909` style line listing the squash commit as the new HEAD.

- [ ] **Step 3: Verify the new code is in prod**

```bash
grep -n "_tap_ig_action_bar_ok\|action_bar OK fallback tap\|ig_share_ok_button_attempted" \
  /root/.openclaw/workspace-genri/autowarm/publisher_instagram.py | head -8
```

Expected: at least 4 matches — the helper definition, the helper call site, the info log msg, and the `ig_share_ok_button_attempted` meta category.

- [ ] **Step 4: No PM2 restart**

`publisher.py` is spawned subprocess-per-task by `server.js` ([[project_ig_publish_cross_project_leak_2026_05_12]]) — new spawns auto-pick up the changes. In-flight tasks finish on the old code without regression.

- [ ] **Step 5: Remove the worktree**

```bash
cd /root/.openclaw/workspace-genri/autowarm && \
  git worktree remove /home/claude-user/autowarm-fix-ig-share-ok-fallback-20260513 && \
  git branch -D fix-ig-share-ok-fallback-20260513 2>/dev/null || true
```

Expected: worktree directory deleted; `git worktree list` no longer shows it; local branch removed (it has already been deleted on the remote by `--delete-branch`).

---

## Task 9: 24h live verify + evidence

**Files:**
- Create: `docs/evidence/2026-05-13-ig-share-ok-fallback-shipped.md`
- Create: `~/.claude/projects/-home-claude-user-contenthunter/memory/project_ig_share_ok_fallback_shipped.md`
- Modify: `~/.claude/projects/-home-claude-user-contenthunter/memory/MEMORY.md` (add one-line index entry)

- [ ] **Step 1: Record the deploy timestamp**

When the prod `git pull --ff-only` in Task 8 Step 2 succeeds, capture the wall-clock UTC time. This is `<deploy-ts>` for the verify SQL. Acceptable forms: `2026-05-14 09:15:00+00` (ISO with TZ).

- [ ] **Step 2: At deploy + 24h, run rescue-rate SQL from spec § 5**

```sql
WITH share_fails AS (
  SELECT id, status, events
  FROM publish_tasks
  WHERE platform='Instagram' AND testbench=false
    AND created_at >= '<deploy-ts>'
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
```

- [ ] **Step 3: Cross-check overall `ig_share_tap_no_progress` count**

```sql
SELECT COUNT(*) FROM publish_tasks
WHERE error_code='ig_share_tap_no_progress'
  AND testbench=false
  AND created_at >= '<deploy-ts>';
```

Baseline pre-deploy (2026-05-13 09:00 UTC): 11 over preceding 9h; full-day projection ~30.

Acceptance: count drops by at least `ok_rescued_24h` (i.e., the OK rescues take a corresponding bite out of the fail count).

- [ ] **Step 4: Spike-check for shifted failure modes**

```sql
SELECT error_code, COUNT(*) FROM publish_tasks
WHERE platform='Instagram' AND status='failed' AND testbench=false
  AND created_at >= '<deploy-ts>'
GROUP BY error_code ORDER BY 2 DESC LIMIT 10;
```

If a new error_code category appears in the top 5 that was not present in the pre-deploy baseline (see [[project_session_2026_05_12_evening_shipped]] for the pre-deploy IG-fails table), document it as a follow-up. Do NOT claim success based on a single metric drop.

- [ ] **Step 5: Apply the acceptance band**

From spec § 5:
- **`ok_rescued_24h / ok_attempted_24h ≥ 30%`** → 🎯 close; design successful.
- **10-30% rescue** → keep; document partial win; plan a Variant C (keyevent ENTER) follow-up.
- **`ok_attempted_24h > 0` and rescue < 10%** → revert + escalate. The OK fallback fires but doesn't rescue — indicates the right screen but wrong action. Next step: AI-badge-side investigation or Variant B alternating retries.
- **`ok_attempted_24h == 0`** → no fallback ever fired; the design's premise was wrong. Investigate why the helper never matches in prod (locale? resource-id changed? code path not reached?).

- [ ] **Step 6: Write the evidence doc**

Create `docs/evidence/2026-05-13-ig-share-ok-fallback-shipped.md` covering:
- PR number + squash-merge commit + auto-deploy timestamp
- Baseline numbers (pre-deploy, captured in Task 8 Step 2 or earlier)
- 24h post-deploy numbers from Steps 2-4
- Verdict per Step 5's acceptance bands
- Spike-check findings (any new categories?)

Commit to `rmbrmv/contenthunter` main.

- [ ] **Step 7: Update memory**

Create `~/.claude/projects/-home-claude-user-contenthunter/memory/project_ig_share_ok_fallback_shipped.md` (type=project) with:
- Status (shipped / 24h verify outcome)
- Spec + plan + PR + evidence links
- Baseline + post-deploy numbers
- "How to apply" pointer for future sessions

Add a one-line index entry in `MEMORY.md` under 150 chars:
```
- [IG share OK fallback ✅ SHIPPED 2026-05-13 PR #NN](project_ig_share_ok_fallback_shipped.md) — Tier 1.5 alt-button after share retries; rescue rate X/Y/24h
```

Also cross-link the sibling memories:
- Append a "follow-up" line to `project_ig_share_regression_post_pr31_2026_05_12.md` noting that the post-PR-37-revert spike was further addressed by this PR.
- Append a similar pointer to `project_ig_share_tier2_design.md` so the Tier-2/Tier-1.5 history is connected.

Commit the memory updates to `rmbrmv/contenthunter` main.

---

## Self-Review

### Spec coverage

| Spec § | Plan task |
|---|---|
| § 2.1 New helper `_tap_ig_action_bar_ok` | Task 3 Step 2 (impl) + Task 2 Steps 1-3 (RED tests) |
| § 2.2 Tier 1.5 fallback wiring + ok_fallback_attempted flag | Task 5 Step 2 (impl) + Task 4 Steps 2-5 (RED tests) |
| § 2.3 Design rationale (locale guard, success-path no-op, helper-preserved) | Embedded in Task 3 Step 2 docstring + Task 5 Step 2 inline comment |
| § 3 Tests 1-8 (helper) | Task 2 (in `tests/test_ig_share_ok_fallback.py`) |
| § 3 Tests 9-11 (integration) | Task 4 (extends `tests/test_publisher_instagram_share_retry.py`) |
| § 4 Rollout (branch, commits, codex, PR, auto-deploy, no PM2 restart) | Tasks 1, 6, 7, 8 |
| § 5 Live verify SQL (24h) + acceptance bands | Task 9 |
| § 6 Rollback plan (single revert) | Implicit — single squash-merge PR → one revert commit |
| § 7 Risks (OK semantics unknown, locale, AI badge, account soft-blocks) | Spec is the rationale doc; plan inherits |
| § 8 Out of scope | Not a plan task |
| § 9 Acceptance criteria (11 tests GREEN, watchdog suite GREEN, codex 0 P1 × 3, 24h ≥30% rescue) | Tasks 2-5 (tests), Task 6 (codex), Task 9 (verify) |

### Placeholder scan

No "TBD/TODO/implement later"; no generic "add error handling"; no "similar to Task N". The only intentional placeholders are `<deploy-ts>` (Task 9, filled at verify time) and `<pr-number>` (Task 8 Step 1, filled when the PR is opened).

### Type consistency

- `self._watchdog` is not touched here — orthogonal to the watchdog fix (PR #48).
- `self._tap_ig_action_bar_ok(ui_xml: str) -> bool` — matches the helper signature in Task 3 Step 2, Task 2 Steps 1-3 (test calls), and the integration tests in Task 4.
- `ok_tap_dispatched: bool` — local in Task 5 Step 2 wiring; the field name surfaces in Task 4 Step 3 (`ok_fallback_attempted` meta key, written from `ok_tap_dispatched`).
- `meta['category']` event names: `ig_share_retry`, `ig_share_tap_no_progress`, `ig_share_ok_button_attempted` — used consistently in spec § 2.2, Task 4 integration tests, Task 5 wiring, and Task 9 verify SQL.
- `_editor_xml`, `_editor_xml_with_ok`, `_post_publish_xml`, `_make_publisher_stub` — fixture function names used consistently in Task 4 Steps 2-3 and matching the existing convention in `tests/test_publisher_instagram_share_retry.py`.

### Scope check

Single subsystem (IG share Tier 1.5 fallback in `_wait_instagram_upload`). One spec → one plan → one PR. No decomposition needed.
