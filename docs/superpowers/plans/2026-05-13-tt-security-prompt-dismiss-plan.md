# TT Security Prompt Dismiss Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new helper `_tt_dismiss_security_prompt` in `account_switcher.py` and wire it into the existing TT profile-tab retap loop so the "Быстрая проверка безопасности" bottom-sheet is dismissed before each retry attempt.

**Architecture:** One additive helper method and one insertion of ~10 lines into the existing `_switch_tiktok` retap loop. The helper detects two required text/desc markers (anti-false-positive), finds a clickable "Закрыть" close button, and dispatches a single `input tap`. The wiring runs before each per-retap action so the prompt is dismissed BEFORE the retry tap fires. Ten new tests cover the helper (8) and the integration (2), all TDD-first. Codex review on spec/plan/PR per [[feedback_codex_review_specs]].

**Tech Stack:** Python 3, pytest, unittest.mock; production target `/root/.openclaw/workspace-genri/autowarm/`. PRs land in `GenGo2/delivery-contenthunter`. Source-of-truth repo: `rmbrmv/contenthunter`.

**Spec:** `docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md` (commit `c9282da41` — codex round 1 0 findings).

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `account_switcher.py` (next to `_tt_smart_tap_profile`) | Modify | Add `_tt_dismiss_security_prompt(ui_xml) -> bool` helper |
| `account_switcher.py:2112-2118` (after `_save_dump`, before per-retap action) | Modify | Insert dismiss-check + log_event for `tt_security_prompt_dismissed` |
| `tests/test_tt_security_prompt_dismiss.py` | Create | 8 unit tests for the helper (markers, locale, clickable guard, malformed bounds, adb exception, empty XML, partial markers) |
| `tests/test_tt_profile_tab_retap_security.py` | Create | 2 integration tests for the wiring (dismiss-fires, no-prompt-no-dismiss) |

Worktree convention per [[feedback_parallel_claude_sessions]] + [[feedback_plan_full_mode_branch]]: all work happens in a git worktree off branch `fix-tt-security-prompt-dismiss-20260513` so prod `main` is not blocked.

---

## Task 1: Set up worktree + branch

**Files:**
- New worktree dir: `/home/claude-user/autowarm-fix-tt-security-prompt-dismiss-20260513/`
- Branch: `fix-tt-security-prompt-dismiss-20260513` off `origin/main`

- [ ] **Step 1: Fetch latest main**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git fetch origin main
```

Expected: prints either no updates or `From .../delivery-contenthunter * branch main → FETCH_HEAD`.

- [ ] **Step 2: Confirm main is clean**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git status --short
```

Expected: empty output. If non-empty (parallel session uncommitted), **abort and report BLOCKED** — do not stash or discard.

- [ ] **Step 3: Create worktree on a new branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm && \
  git worktree add -b fix-tt-security-prompt-dismiss-20260513 \
    /home/claude-user/autowarm-fix-tt-security-prompt-dismiss-20260513 origin/main
```

Expected: `Preparing worktree (new branch 'fix-tt-security-prompt-dismiss-20260513')` then `HEAD is now at <sha> <subject>`.

- [ ] **Step 4: Verify worktree**

```bash
cd /home/claude-user/autowarm-fix-tt-security-prompt-dismiss-20260513 && \
  git rev-parse --abbrev-ref HEAD && \
  git log --oneline -1
```

Expected: prints `fix-tt-security-prompt-dismiss-20260513` followed by the latest origin/main commit (currently `7b3e5f6` from PR #49 IG share OK fallback).

---

## Task 2: Write 8 helper unit tests (RED first)

**Files:**
- Create: `tests/test_tt_security_prompt_dismiss.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_tt_security_prompt_dismiss.py` with exactly this content:

```python
"""Unit tests for _tt_dismiss_security_prompt helper.

When TT shows a 'Быстрая проверка безопасности' bottom-sheet on profile tap,
this helper finds the top-right close X and dispatches a single tap.

Spec: docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md §2.1
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _ui_with_security_prompt(
    close_bounds: str = '[945,1277][1058,1401]',
    close_clickable: str = 'true',
    include_title: bool = True,
    include_sheet_desc: bool = True,
) -> str:
    title_node = (
        '<node text="Быстрая проверка безопасности" content-desc="" '
        'bounds="[90,1682][990,1834]" clickable="false"/>'
        if include_title else ''
    )
    sheet_node = (
        '<node text="" content-desc="Нижняя шторка" '
        'bounds="[0,1266][1080,2205]" clickable="false"/>'
        if include_sheet_desc else ''
    )
    return (
        "<?xml version='1.0'?><hierarchy>"
        f'{sheet_node}'
        f'{title_node}'
        '<node text="" content-desc="Закрыть" '
        f'bounds="{close_bounds}" clickable="{close_clickable}"/>'
        '<node text="Продолжить" content-desc="" '
        'bounds="[45,2016][1035,2160]" clickable="true"/>'
        '</hierarchy>'
    )


def _ui_empty() -> str:
    return "<?xml version='1.0'?><hierarchy/>"


def _make_switcher():
    """AccountSwitcher with mock publisher (mirrors tests/test_account_switcher_tt.py)."""
    from account_switcher import AccountSwitcher
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.adb = MagicMock(return_value='')
    publisher.dump_ui = MagicMock(return_value='')
    publisher.log_event = MagicMock()
    sw = AccountSwitcher(publisher)
    return sw


# ─── Test 1: Full prompt → close-tap at centre of bounds ──────────────────

def test_dismiss_finds_close_button_and_taps_centre():
    """bounds=[945,1277][1058,1401] → centre=(1001, 1339), adb command exact."""
    sw = _make_switcher()

    result = sw._tt_dismiss_security_prompt(_ui_with_security_prompt())

    assert result is True
    sw.p.adb.assert_called_once_with('input tap 1001 1339')


# ─── Test 2: No prompt markers at all → False ─────────────────────────────

def test_dismiss_no_prompt_markers_returns_false():
    sw = _make_switcher()

    result = sw._tt_dismiss_security_prompt(_ui_empty())

    assert result is False
    sw.p.adb.assert_not_called()


# ─── Test 3: Title present but sheet desc missing → False ─────────────────

def test_dismiss_partial_markers_only_title_returns_false():
    """Anti-false-positive: both markers required."""
    sw = _make_switcher()

    result = sw._tt_dismiss_security_prompt(
        _ui_with_security_prompt(include_sheet_desc=False)
    )

    assert result is False
    sw.p.adb.assert_not_called()


# ─── Test 4: Title + sheet present, no 'Закрыть' node → False ─────────────

def test_dismiss_close_button_missing_returns_false():
    """Markers present but the close button is absent."""
    sw = _make_switcher()
    xml = (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="" content-desc="Нижняя шторка" '
        'bounds="[0,1266][1080,2205]" clickable="false"/>'
        '<node text="Быстрая проверка безопасности" content-desc="" '
        'bounds="[90,1682][990,1834]" clickable="false"/>'
        '<node text="Продолжить" content-desc="" '
        'bounds="[45,2016][1035,2160]" clickable="true"/>'
        '</hierarchy>'
    )

    result = sw._tt_dismiss_security_prompt(xml)

    assert result is False
    sw.p.adb.assert_not_called()


# ─── Test 5: Close button present but non-clickable → False ───────────────

def test_dismiss_close_non_clickable_returns_false():
    sw = _make_switcher()

    result = sw._tt_dismiss_security_prompt(
        _ui_with_security_prompt(close_clickable='false')
    )

    assert result is False
    sw.p.adb.assert_not_called()


# ─── Test 6: Empty XML → False, no exception ──────────────────────────────

def test_dismiss_empty_xml_returns_false():
    sw = _make_switcher()

    result = sw._tt_dismiss_security_prompt('')

    assert result is False
    sw.p.adb.assert_not_called()


# ─── Test 7: Malformed bounds on close node → False ───────────────────────

def test_dismiss_malformed_bounds_returns_false():
    sw = _make_switcher()

    result = sw._tt_dismiss_security_prompt(
        _ui_with_security_prompt(close_bounds='invalid-bounds')
    )

    assert result is False
    sw.p.adb.assert_not_called()


# ─── Test 8: adb dispatch raises → swallowed, returns False ───────────────

def test_dismiss_adb_exception_does_not_propagate():
    sw = _make_switcher()
    sw.p.adb = MagicMock(side_effect=RuntimeError('boom'))

    result = sw._tt_dismiss_security_prompt(_ui_with_security_prompt())

    assert result is False
    sw.p.adb.assert_called_once()
```

- [ ] **Step 2: Run the new tests — confirm 8 FAIL (helper not defined yet)**

```bash
cd /home/claude-user/autowarm-fix-tt-security-prompt-dismiss-20260513 && \
  pytest tests/test_tt_security_prompt_dismiss.py -v
```

Expected: all 8 tests FAIL with `AttributeError: 'AccountSwitcher' object has no attribute '_tt_dismiss_security_prompt'`. If any test passes pre-implementation, **stop and investigate**.

- [ ] **Step 3: Commit the RED helper tests**

```bash
git add tests/test_tt_security_prompt_dismiss.py
git commit -m "$(cat <<'EOF'
test(tt): RED tests for _tt_dismiss_security_prompt helper

8 TDD-first tests covering TT security-prompt dismiss helper: locale markers
(full prompt → close-tap), anti-false-positive (partial markers, missing
close button, non-clickable close), robustness (empty XML, malformed
bounds, adb exception swallow). All FAIL with AttributeError
pre-implementation.

Spec: docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: clean commit on `fix-tt-security-prompt-dismiss-20260513`.

---

## Task 3: Implement `_tt_dismiss_security_prompt` helper

**Files:**
- Modify: `account_switcher.py` (insert new method right after `_tt_smart_tap_profile`)

- [ ] **Step 1: Locate `_tt_smart_tap_profile`**

```bash
grep -n 'def _tt_smart_tap_profile' account_switcher.py
```

Expected: one match in `account_switcher.py`. The new helper goes immediately after this method's body.

- [ ] **Step 2: Find the closing return of `_tt_smart_tap_profile` to use as anchor**

```bash
sed -n '<smart_tap_line>,+25p' account_switcher.py
```

(replace `<smart_tap_line>` with the line number from Step 1)

Inspect the output to find the last line of `_tt_smart_tap_profile` — typically `return ...` or the final block's last statement at the same indent level as `def _tt_smart_tap_profile`. The new helper is inserted directly after this method (before the next method's `def` line).

- [ ] **Step 3: Insert the helper using a unique-anchor Edit**

Locate the line immediately preceding the next method definition after `_tt_smart_tap_profile`. The `Edit` tool's `old_string` must capture the last line of `_tt_smart_tap_profile` (whatever it is — pick a unique line at the correct indent) plus the next method's `def` line. Replace with the same lines plus the new helper between them.

Concrete pattern: find the unique last line of `_tt_smart_tap_profile` (the file currently has it as a `return` or similar). For each commit-time, the agent must inspect the actual code and choose an anchor that uniquely identifies the insertion point. The inserted block is exactly:

```python

    def _tt_dismiss_security_prompt(self, ui_xml: str) -> bool:
        """Detect and dismiss TikTok 'Быстрая проверка безопасности' prompt.

        TT shows this bottom-sheet prompt instead of the profile screen on
        suspicious access patterns. The sheet has desc='Нижняя шторка' plus
        a title text 'Быстрая проверка безопасности'. We tap the top-right
        'Закрыть' (close X) to dismiss without engaging the security flow.

        Spec: docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md §2.1

        Returns:
            True if the prompt was detected and the close-tap was dispatched.
            False if any marker is missing, the close node is non-clickable,
            bounds are malformed, or adb dispatch raised.
        """
        if not ui_xml:
            return False
        SECURITY_TITLE = 'Быстрая проверка безопасности'
        SHEET_DESC = 'Нижняя шторка'
        CLOSE_DESC = 'Закрыть'
        if SECURITY_TITLE not in ui_xml or SHEET_DESC not in ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        import re as _re
        for n in root.iter('node'):
            if n.get('content-desc', '').strip() != CLOSE_DESC:
                continue
            if n.get('clickable') != 'true':
                continue
            bounds = n.get('bounds', '')
            m = _re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
            if not m:
                return False
            x1, y1, x2, y2 = (int(m.group(i)) for i in (1, 2, 3, 4))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            try:
                self.p.adb(f'input tap {cx} {cy}')
                return True
            except Exception:
                return False
        return False
```

Indentation must match the surrounding method definitions (4 spaces for class body, 8 spaces inside method). The blank line at the start of the inserted block separates the new method from the preceding one.

- [ ] **Step 4: Run the helper tests — all 8 must pass**

```bash
pytest tests/test_tt_security_prompt_dismiss.py -v
```

Expected: 8 / 8 PASS. If any test still fails, the helper implementation has a bug — fix and re-run before continuing.

- [ ] **Step 5: Sanity-check no other switcher test broke**

```bash
pytest tests/test_account_switcher_tt.py tests/test_account_switcher.py -v --tb=short 2>&1 | tail -40
```

Expected: existing TT/switcher tests all PASS (no test currently references `_tt_dismiss_security_prompt`, so adding the helper cannot break anything).

- [ ] **Step 6: Commit the helper**

```bash
git add account_switcher.py
git commit -m "$(cat <<'EOF'
fix(tt): add _tt_dismiss_security_prompt helper

New helper detects TT 'Быстрая проверка безопасности' bottom-sheet
(markers: desc='Нижняя шторка' + title text) and dispatches a single
`input tap` on the top-right 'Закрыть' close button. Locale-restricted
to Russian markers. Robust against empty XML, missing markers,
non-clickable close, malformed bounds, and adb exceptions.

8 unit tests GREEN.

Spec: docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Write 2 integration tests for the retap wiring (RED first)

**Files:**
- Create: `tests/test_tt_profile_tab_retap_security.py`

- [ ] **Step 1: Write the integration test file**

Create `tests/test_tt_profile_tab_retap_security.py` with exactly this content:

```python
"""Integration tests for TT profile-tab retap loop security-prompt wiring.

Validates that `_switch_tiktok`'s retap loop calls `_tt_dismiss_security_prompt`
and emits a `tt_security_prompt_dismissed` log_event when the prompt is
visible, and does NOT call/emit when the prompt is absent.

Spec: docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md §2.2
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from account_switcher import AccountSwitcher, UI_CONSTANTS  # noqa: E402


def _security_prompt_xml() -> str:
    """Minimal XML carrying both markers + clickable Закрыть."""
    return (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="" content-desc="Нижняя шторка" '
        'bounds="[0,1266][1080,2205]" clickable="false"/>'
        '<node text="Быстрая проверка безопасности" content-desc="" '
        'bounds="[90,1682][990,1834]" clickable="false"/>'
        '<node text="" content-desc="Закрыть" '
        'bounds="[945,1277][1058,1401]" clickable="true"/>'
        '</hierarchy>'
    )


def _plain_not_own_xml() -> str:
    """Minimal XML with NO security-prompt markers (so dismiss returns False)."""
    return (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="some other content" content-desc="" '
        'bounds="[0,0][1080,2340]" clickable="false"/>'
        '</hierarchy>'
    )


def _own_profile_xml() -> str:
    """Minimal XML that satisfies _tt_is_own_profile (forces loop exit on next iter)."""
    return (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="Сообщение" content-desc="" '
        'bounds="[100,300][500,400]" clickable="true"/>'
        '<node text="Изменить профиль" content-desc="" '
        'bounds="[100,500][500,600]" clickable="true"/>'
        '</hierarchy>'
    )


def _make_switcher_for_retap_loop():
    """AccountSwitcher with mock publisher, ready to drive _switch_tiktok retap loop."""
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.adb = MagicMock(return_value='')
    publisher.log_event = MagicMock()
    publisher.set_step = MagicMock()
    publisher.ensure_unlocked = MagicMock()
    publisher.adb_tap = MagicMock()
    publisher.tap_element = MagicMock(return_value=False)
    publisher._safe_kb_probe = MagicMock()
    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    sw._maybe_screenshot = MagicMock()
    sw._go_to_profile_tab = MagicMock()
    sw._tt_smart_tap_profile = MagicMock(return_value=False)
    sw._tt_is_logged_out = MagicMock(return_value=False)
    sw._tt_is_reauth_prompt = MagicMock(return_value=False)
    sw._tt_is_foreign_profile = MagicMock(return_value=False)
    return sw


def test_profile_tab_retap_calls_security_dismiss_when_prompt_visible():
    """Iteration 0: prompt XML → dismiss fires + log event. Iteration 1: own_profile → exit."""
    sw = _make_switcher_for_retap_loop()
    cfg = UI_CONSTANTS['TikTok']

    sw.p.dump_ui = MagicMock(side_effect=[
        _security_prompt_xml(),  # retap=0 probe → not own, prompt present
        _own_profile_xml(),      # retap=1 probe → own profile, loop exits
        _own_profile_xml(),      # extra safety if loop calls dump_ui again
    ])
    sw._tt_is_own_profile = MagicMock(side_effect=[False, True, True])

    with patch('time.sleep'):
        # Skip the prelude of _switch_tiktok by driving the loop logic via
        # the public entry. We tolerate downstream calls returning early via
        # mocks already configured (e.g. _go_to_profile_tab no-ops).
        try:
            sw._switch_tiktok('clickpay_under', cfg)
        except Exception:
            # Downstream paths after the loop exits may raise on missing
            # mocks (e.g. _read_screen_hybrid). The wiring assertions below
            # are what this test cares about; we ignore terminal exceptions.
            pass

    # Assert dismiss helper was invoked at least once on the security XML.
    # (We can detect this via the publisher.adb mock — dismiss calls
    # self.p.adb with 'input tap 1001 1339' for the close button.)
    tap_calls = [
        c for c in sw.p.adb.call_args_list
        if c.args and isinstance(c.args[0], str) and c.args[0].startswith('input tap 1001 1339')
    ]
    assert len(tap_calls) >= 1, (
        f'expected at least one close-tap dispatch via adb, got '
        f'{sw.p.adb.call_args_list!r}'
    )

    # Assert log_event was called with the new category.
    dismiss_log_calls = [
        c for c in sw.p.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'tt_security_prompt_dismissed'
    ]
    assert len(dismiss_log_calls) == 1, \
        f'expected 1 tt_security_prompt_dismissed event, got {len(dismiss_log_calls)}'


def test_profile_tab_retap_no_dismiss_when_no_prompt():
    """Iteration 0: prompt-free not-own XML → dismiss NOT fired, no event. Iteration 1: own_profile → exit."""
    sw = _make_switcher_for_retap_loop()
    cfg = UI_CONSTANTS['TikTok']

    sw.p.dump_ui = MagicMock(side_effect=[
        _plain_not_own_xml(),
        _own_profile_xml(),
        _own_profile_xml(),
    ])
    sw._tt_is_own_profile = MagicMock(side_effect=[False, True, True])

    with patch('time.sleep'):
        try:
            sw._switch_tiktok('clickpay_under', cfg)
        except Exception:
            pass

    # Anti-regression: no close-tap dispatched (no prompt visible).
    close_tap_calls = [
        c for c in sw.p.adb.call_args_list
        if c.args and isinstance(c.args[0], str) and c.args[0].startswith('input tap 1001 1339')
    ]
    assert len(close_tap_calls) == 0, \
        f'expected 0 close-tap dispatches (no prompt), got {len(close_tap_calls)}'

    # Anti-regression: no dismiss-event emitted.
    dismiss_log_calls = [
        c for c in sw.p.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'tt_security_prompt_dismissed'
    ]
    assert len(dismiss_log_calls) == 0, \
        f'expected 0 tt_security_prompt_dismissed events, got {len(dismiss_log_calls)}'
```

- [ ] **Step 2: Run the integration tests — confirm 2 FAIL pre-wiring**

```bash
pytest tests/test_tt_profile_tab_retap_security.py -v
```

Expected:
- `test_profile_tab_retap_calls_security_dismiss_when_prompt_visible` — **FAIL** (the wiring is not yet in `_switch_tiktok`, so dismiss helper is never called and no `tt_security_prompt_dismissed` event is emitted)
- `test_profile_tab_retap_no_dismiss_when_no_prompt` — **PASS** (anti-regression baseline; without wiring, no dismiss happens anyway)

If `test_profile_tab_retap_no_dismiss_when_no_prompt` somehow FAILS pre-wiring, **stop and investigate** — a stray helper call somewhere in the loop would be a real bug.

- [ ] **Step 3: Commit the RED integration tests**

```bash
git add tests/test_tt_profile_tab_retap_security.py
git commit -m "$(cat <<'EOF'
test(tt): RED integration tests for security-prompt retap-loop wiring

2 tests covering the new dismiss-and-log wiring inside _switch_tiktok's
profile-tab retap loop: prompt visible → dismiss fires + event emitted,
prompt absent → no dismiss + no event (anti-regression).

Test 1 FAILs pre-wiring; Test 2 PASSes by accident as anti-regression
baseline.

Spec: docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Wire dismiss into the retap loop

**Files:**
- Modify: `account_switcher.py:2112-2118` (the existing retap-loop body)

- [ ] **Step 1: Locate the current retap-loop wiring point**

```bash
grep -n "log.warning(f'\[FIX: TT-own-profile\] не на своём профиле" account_switcher.py
```

Expected: one match — the `log.warning` call that prints `[FIX: TT-own-profile] не на своём профиле (retap {retap+1}/3)`. This is the anchor for the insert.

- [ ] **Step 2: Apply the wiring edit**

Use the `Edit` tool with this exact `old_string`:

```python
            log.warning(f'[FIX: TT-own-profile] не на своём профиле (retap {retap+1}/3)')
            self.p.log_event('account_switch',
                             f'not_own_profile step=tt_2_profile_tab retap={retap+1}')
            self._save_dump(f'tt_2_not_own_retap{retap+1}', xml_probe)
            if retap == 0:
                # Обычный tap
                self._go_to_profile_tab(cfg, f'tt_2_retap{retap+1}')
            elif retap == 1:
                # Умный tap: найти «Профиль/Me» в bottom-nav по label
                log.info('[FIX: TT-own-profile] retap2 → smart_tap по label')
                if not self._tt_smart_tap_profile():
                    log.warning('[FIX: TT-own-profile] smart_tap не нашёл иконку, fallback coords')
                    self._go_to_profile_tab(cfg, f'tt_2_retap{retap+1}')
            else:
                # Последняя надежда: cold-start
                log.warning('[FIX: TT-own-profile] retap3 → force_stop + relaunch')
                self.p.adb(f'am force-stop {cfg["package"]}')
                time.sleep(2)
                self.p.adb(f'am start -n {cfg["launch_activity"]}')
                time.sleep(OPEN_APP_WAIT_S + 2)
                if not self._tt_smart_tap_profile():
                    self._go_to_profile_tab(cfg, f'tt_2_retap{retap+1}')
            time.sleep(POST_TAP_WAIT_S + 1)
```

Replace with:

```python
            log.warning(f'[FIX: TT-own-profile] не на своём профиле (retap {retap+1}/3)')
            self.p.log_event('account_switch',
                             f'not_own_profile step=tt_2_profile_tab retap={retap+1}')
            self._save_dump(f'tt_2_not_own_retap{retap+1}', xml_probe)

            # Detect and dismiss the TT security prompt that covers the profile
            # screen. If dismissed, the upcoming retap action will land on the
            # real profile tab on the next iteration's probe.
            if self._tt_dismiss_security_prompt(xml_probe):
                self.p.log_event(
                    'account_switch',
                    f'tt_security_prompt_dismissed step=tt_2_profile_tab retap={retap+1}',
                    meta={'category': 'tt_security_prompt_dismissed',
                          'retap': retap + 1,
                          'platform': 'TikTok'},
                )
                time.sleep(POST_TAP_WAIT_S + 0.5)

            if retap == 0:
                # Обычный tap
                self._go_to_profile_tab(cfg, f'tt_2_retap{retap+1}')
            elif retap == 1:
                # Умный tap: найти «Профиль/Me» в bottom-nav по label
                log.info('[FIX: TT-own-profile] retap2 → smart_tap по label')
                if not self._tt_smart_tap_profile():
                    log.warning('[FIX: TT-own-profile] smart_tap не нашёл иконку, fallback coords')
                    self._go_to_profile_tab(cfg, f'tt_2_retap{retap+1}')
            else:
                # Последняя надежда: cold-start
                log.warning('[FIX: TT-own-profile] retap3 → force_stop + relaunch')
                self.p.adb(f'am force-stop {cfg["package"]}')
                time.sleep(2)
                self.p.adb(f'am start -n {cfg["launch_activity"]}')
                time.sleep(OPEN_APP_WAIT_S + 2)
                if not self._tt_smart_tap_profile():
                    self._go_to_profile_tab(cfg, f'tt_2_retap{retap+1}')
            time.sleep(POST_TAP_WAIT_S + 1)
```

- [ ] **Step 3: Run the integration tests — both must pass**

```bash
pytest tests/test_tt_profile_tab_retap_security.py -v
```

Expected verdicts:
- `test_profile_tab_retap_calls_security_dismiss_when_prompt_visible` — PASS
- `test_profile_tab_retap_no_dismiss_when_no_prompt` — PASS

If either fails, the wiring has a bug — fix and re-run before continuing.

- [ ] **Step 4: Run the helper tests — must remain GREEN**

```bash
pytest tests/test_tt_security_prompt_dismiss.py -v
```

Expected: 8 / 8 PASS (unchanged).

- [ ] **Step 5: Run the full TT-switcher suite for incidental regressions**

Run pytest first (so its exit status is visible), then look at the tail for context:

```bash
pytest tests/test_account_switcher_tt.py tests/test_account_switcher.py -v --tb=short > /tmp/sw-suite.log 2>&1
status=$?
tail -30 /tmp/sw-suite.log
echo "pytest exit=$status"
```

Do NOT use `pytest ... | tail` — the pipe hides pytest's exit code behind `tail`'s success.

Decision rule:
- `pytest exit=0` → proceed.
- `pytest exit=1` and the failures touch `_tt_dismiss_security_prompt`, `_switch_tiktok`, or the retap loop → **stop and fix**.
- `pytest exit=1` but the failures match pre-existing names that already fail on `origin/main` (verify by checking out `origin/main` in a scratch worktree or by `git stash` + re-run) → document the failing test names in the next commit message and proceed.

- [ ] **Step 6: Commit the wiring**

```bash
git add account_switcher.py
git commit -m "$(cat <<'EOF'
fix(tt): wire security-prompt dismiss into profile-tab retap loop

When the retap-loop probe detects 'not own profile', also check for the
'Быстрая проверка безопасности' bottom-sheet via _tt_dismiss_security_prompt.
If detected and tap dispatched, log a tt_security_prompt_dismissed event
and sleep ~POST_TAP_WAIT_S + 0.5s for the dismiss animation. Existing
per-retap action (tap / smart_tap / cold-start) then fires unchanged on
the dismissed screen.

10 tests GREEN (8 helper + 2 integration). Existing TT switcher suite GREEN.

Spec: docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Codex review on the full diff

**Files:** none modified; review-only.

- [ ] **Step 1: Generate the cumulative diff vs origin/main**

```bash
git diff origin/main...HEAD -- account_switcher.py \
  tests/test_tt_security_prompt_dismiss.py \
  tests/test_tt_profile_tab_retap_security.py \
  > /tmp/tt-security-dismiss-diff.patch
wc -l /tmp/tt-security-dismiss-diff.patch
```

Expected: non-empty patch on the order of 250-350 lines.

- [ ] **Step 2: Pipe diff into codex review (per [[feedback_codex_sandbox_broken]] — `--base main` is broken)**

```bash
cat /tmp/tt-security-dismiss-diff.patch | ~/.local/bin/codex review - 2>&1 | tail -80
```

- [ ] **Step 3: Triage codex findings**

- `0 P1` (or no review comments) → proceed to Task 7.
- `[P1]` findings → apply fixes as new commits (NOT `--amend`), re-run Step 2, repeat until 0 P1. Per [[feedback_codex_review_specs]].
- `[P2]` / `[P3]` findings → non-blocking, but trivial fixes are worth applying inline before moving on.

- [ ] **Step 4: Record codex outcome in commit history**

If codex returned non-zero findings, ensure each fix lands as its own commit with the message format:

```
fix(tt): <subject> (codex round N P1|P2|P3)
```

so the audit trail matches the pattern established in [[project_session_2026_05_11_shipped]] and [[project_watchdog_ping_regression_shipped]].

---

## Task 7: Push branch and open PR

**Files:** none modified.

- [ ] **Step 1: Pull main to detect drift**

```bash
git fetch origin main && git log --oneline origin/main..HEAD
```

Expected: only the commits from Tasks 2-6 (RED helper tests, helper impl, RED integration tests, wiring, optional codex fix commits).

If `git log --oneline HEAD..origin/main` is non-empty, a parallel session moved main forward — rebase (`git rebase origin/main`) and re-run Task 5 Step 5 (full switcher suite) before pushing.

- [ ] **Step 2: Push the branch**

```bash
. ~/secrets/github.env 2>/dev/null || . ~/secrets/github-gengo2.env
git push -u origin fix-tt-security-prompt-dismiss-20260513
```

Expected: branch pushed. (Note: due to the post-commit auto-push hook on the shared `.git/`, the branch may already be on the remote — `Everything up-to-date` is acceptable per [[reference_autowarm_git_hook]].)

- [ ] **Step 3: Open PR against `GenGo2/delivery-contenthunter` main**

```bash
export GH_TOKEN=$(. ~/secrets/github-gengo2.env && echo "$GITHUB_TOKEN_GENGO2")
gh pr create --repo GenGo2/delivery-contenthunter \
  --head fix-tt-security-prompt-dismiss-20260513 --base main \
  --title "fix(tt): dismiss 'Быстрая проверка безопасности' security prompt before profile-tab retap" \
  --body "$(cat <<'EOF'
## Summary

- New helper `_tt_dismiss_security_prompt` finds and taps the top-right `Закрыть` close button on the TT "Быстрая проверка безопасности" bottom-sheet.
- Wired into the `_switch_tiktok` profile-tab retap loop: before each per-retap action, the helper is called on the existing `xml_probe`. If a tap is dispatched, a `tt_security_prompt_dismissed` event is logged and the loop sleeps ~POST_TAP_WAIT_S + 0.5s for the dismiss animation.
- Locale-restricted to Russian markers (`Нижняя шторка`, `Быстрая проверка безопасности`, `Закрыть`). Anti-false-positive: both the title text AND the sheet desc must be present to fire.

## Why

`error_code='tt_profile_tab_broken'` emerged as a brand-new TT failure pattern on 2026-05-13 (0 → 5 in 9h, projected ~13/day). UI dumps from task 5319 confirm the failure mode: TT shows a security bottom-sheet covering the profile screen after the profile-tab tap. The existing retap loop just re-taps the same coords, which doesn't dismiss anything. The new wiring dismisses the prompt before retrying.

Spec (full RC analysis): `docs/superpowers/specs/2026-05-13-tt-security-prompt-dismiss-design.md`
Plan: `docs/superpowers/plans/2026-05-13-tt-security-prompt-dismiss-plan.md`

## Test plan

- [x] 8 new helper tests in `tests/test_tt_security_prompt_dismiss.py` (RED before fix, GREEN after).
- [x] 2 new integration tests in `tests/test_tt_profile_tab_retap_security.py` (1 RED + 1 baseline-PASS before, both GREEN after).
- [x] Existing TT switcher suite remains GREEN.
- [x] Codex review on spec → 0 findings.
- [x] Codex review on plan → 0 P1.
- [x] Codex review on PR diff → 0 P1.
- [ ] 24h post-deploy: `tt_profile_tab_broken < 2 / 24h` AND `tt_security_prompt_dismissed > 0`. (Acceptance bands in spec § 5.)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Save it for the evidence doc.

---

## Task 8: Squash-merge and deploy

**Files:** none in this worktree.

- [ ] **Step 1: Confirm PR is clean and mergeable**

```bash
export GH_TOKEN=$(. ~/secrets/github-gengo2.env && echo "$GITHUB_TOKEN_GENGO2")
gh pr view <pr-number> --repo GenGo2/delivery-contenthunter \
  --json state,mergeable,mergeStateStatus
```

Expected: `mergeStateStatus="CLEAN"`, `mergeable="MERGEABLE"`, `state="OPEN"`.

- [ ] **Step 2: Squash-merge with branch deletion**

```bash
gh pr merge <pr-number> --repo GenGo2/delivery-contenthunter --squash --delete-branch
```

Expected: PR closed, branch deleted on remote.

- [ ] **Step 3: Pull the merge commit into the prod tree**

```bash
cd /root/.openclaw/workspace-genri/autowarm && \
  git fetch origin main && \
  git pull --ff-only origin main
```

Expected: fast-forward, the squash commit lands at HEAD.

- [ ] **Step 4: Verify the new code is in prod**

```bash
grep -n "_tt_dismiss_security_prompt\|tt_security_prompt_dismissed" \
  /root/.openclaw/workspace-genri/autowarm/account_switcher.py | head -8
```

Expected: at least 3 matches — the helper definition, the wiring call site, and the `tt_security_prompt_dismissed` meta category.

- [ ] **Step 5: No PM2 restart needed**

`publisher.py` (which imports `account_switcher.py`) is spawned subprocess-per-task by `server.js` ([[project_ig_publish_cross_project_leak_2026_05_12]]). New spawns auto-pick up the changes. In-flight tasks finish on the old code without regression.

- [ ] **Step 6: Remove the worktree and local branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm && \
  git worktree remove /home/claude-user/autowarm-fix-tt-security-prompt-dismiss-20260513 && \
  git branch -D fix-tt-security-prompt-dismiss-20260513 2>/dev/null || true
```

Expected: worktree directory deleted; `git worktree list` no longer shows it; local branch removed (the remote branch was deleted by `--delete-branch` in Step 2).

---

## Task 9: 24h live verify + evidence + memory

**Files:**
- Create: `docs/evidence/2026-05-13-tt-security-prompt-dismiss-shipped.md`
- Create: `~/.claude/projects/-home-claude-user-contenthunter/memory/project_tt_security_prompt_dismiss_shipped.md`
- Modify: `~/.claude/projects/-home-claude-user-contenthunter/memory/MEMORY.md` (add one-line index entry)

- [ ] **Step 1: Record the deploy timestamp**

When the prod `git pull --ff-only` in Task 8 Step 3 succeeds, capture the wall-clock UTC time. This is `<deploy-ts>` for the verify SQL. Acceptable forms: `2026-05-14 14:30:00+00` (ISO with TZ).

- [ ] **Step 2: At deploy + 24h, run the dismiss fire-rate SQL from spec § 5**

```sql
-- Helper fire rate over 24h
SELECT COUNT(*) FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'tt_security_prompt_dismissed'
  AND pt.created_at >= '<deploy-ts>';
```

- [ ] **Step 3: Cross-check `tt_profile_tab_broken` drop**

```sql
SELECT COUNT(*) FROM publish_tasks
WHERE error_code='tt_profile_tab_broken'
  AND testbench=false
  AND created_at >= '<deploy-ts>';
```

Baseline pre-deploy (2026-05-13 morning): 5 failures in 9h, projected ~13/day. Acceptance: count < 2 / 24h.

- [ ] **Step 4: Compute rescue rate**

```sql
WITH dismissed AS (
  SELECT pt.id, pt.status
  FROM publish_tasks pt,
       jsonb_array_elements(pt.events) e
  WHERE e->'meta'->>'category' = 'tt_security_prompt_dismissed'
    AND pt.created_at >= '<deploy-ts>'
)
SELECT
  COUNT(*) AS dismissed_total,
  COUNT(*) FILTER (WHERE status = 'done') AS rescued,
  ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'done') / NULLIF(COUNT(*), 0), 1) AS pct
FROM dismissed;
```

- [ ] **Step 5: Spike-check for shifted failure modes**

```sql
SELECT error_code, COUNT(*) FROM publish_tasks
WHERE platform='TikTok' AND status='failed' AND testbench=false
  AND created_at >= '<deploy-ts>'
GROUP BY error_code ORDER BY 2 DESC LIMIT 10;
```

Compare against the 2026-05-13 baseline table in the spec § 7. If a new error_code category appears in the top 5 that wasn't present before (e.g., >5 / 24h on something previously rare), document it as a follow-up. Do NOT claim success based on a single metric drop.

- [ ] **Step 6: Apply the acceptance band**

From spec § 5:
- **`tt_profile_tab_broken < 2 / 24h` AND `tt_security_prompt_dismissed > 0`** → 🎯 close; design successful.
- **`tt_security_prompt_dismissed > 0` AND rescue rate < 30%** → keep but iterate (security prompt re-appears or TT doesn't return to profile after dismiss).
- **`tt_security_prompt_dismissed == 0` AND `tt_profile_tab_broken` unchanged** → design premise wrong; investigate fresh evidence.
- **New TT error_code spike** > 5 / 24h → document follow-up.

- [ ] **Step 7: Write the evidence doc**

Create `docs/evidence/2026-05-13-tt-security-prompt-dismiss-shipped.md` covering:
- PR number + squash-merge commit + auto-deploy timestamp
- Baseline numbers (pre-deploy, 5 / 9h projected ~13/day)
- 24h post-deploy numbers from Steps 2-5
- Verdict per Step 6's acceptance bands
- Spike-check findings (any new categories?)

Commit to `rmbrmv/contenthunter` main.

- [ ] **Step 8: Update memory**

Create `~/.claude/projects/-home-claude-user-contenthunter/memory/project_tt_security_prompt_dismiss_shipped.md` (type=project) with:
- Status (shipped / 24h verify outcome)
- Spec + plan + PR + evidence links
- Baseline + post-deploy numbers
- "How to apply" pointer for future sessions

Add a one-line index entry to `MEMORY.md` under 150 chars:
```
- [TT security prompt dismiss ✅ SHIPPED 2026-05-13 PR #NN](project_tt_security_prompt_dismiss_shipped.md) — tt_profile_tab_broken 5/24h → <2; pattern B (account_sheet) — backlog
```

Cross-link the sibling memory `project_revision_phone171_backlog.md` if relevant (its TT-stuck-state hypothesis may now be related to security prompts).

Commit the memory updates to `rmbrmv/contenthunter` main.

---

## Self-Review

### Spec coverage

| Spec § | Plan task |
|---|---|
| § 2.1 New helper `_tt_dismiss_security_prompt` | Task 3 Step 3 (impl) + Task 2 Steps 1-3 (RED tests) |
| § 2.2 Wiring in `_switch_tiktok` retap loop | Task 5 Step 2 (impl) + Task 4 Steps 1-3 (RED tests) |
| § 2.3 Design rationale (markers anti-false-positive, locale guard, close-not-continue, dismiss per retap) | Embedded in Task 3 Step 3 docstring + Task 5 Step 2 inline comment |
| § 3 Tests 1-8 (helper) | Task 2 (in `tests/test_tt_security_prompt_dismiss.py`) |
| § 3 Tests 9-10 (integration) | Task 4 (in `tests/test_tt_profile_tab_retap_security.py`) |
| § 4 Rollout (branch, commits, codex, PR, auto-deploy, no PM2 restart) | Tasks 1, 6, 7, 8 |
| § 5 Live verify SQL (24h) + acceptance bands | Task 9 |
| § 6 Rollback plan (single revert) | Implicit — single squash-merge PR → one revert commit |
| § 7 Risks (Pattern B out of scope, locale, prompt re-appears, security flow skipped) | Spec is the rationale doc; plan inherits |
| § 8 Out of scope | Not a plan task |
| § 9 Acceptance criteria (10 tests GREEN, switcher suite GREEN, codex 0 P1 × 3, 24h `tt_profile_tab_broken < 2`) | Tasks 2-5 (tests), Task 6 (codex), Task 9 (verify) |

### Placeholder scan

No "TBD/TODO/implement later"; no generic "add error handling"; no "similar to Task N". The only intentional placeholders are `<deploy-ts>` (Task 9, filled at verify time), `<pr-number>` (Task 8 Step 1, filled when the PR is opened), and `<smart_tap_line>` (Task 3 Step 2, the agent reads the line number from grep output in Step 1). All three are labelled inline.

### Type consistency

- `self.p` is the publisher attribute on `AccountSwitcher` (matches the existing test pattern `_make_switcher()` and the helper body in Task 3).
- `_tt_dismiss_security_prompt(self, ui_xml: str) -> bool` — signature matches the helper definition in Task 3 Step 3, the test calls in Task 2 Steps 1, and the integration tests in Task 4 Step 1.
- `meta['category']` event name: `tt_security_prompt_dismissed` — used consistently in spec § 2.2, Task 4 integration tests, Task 5 wiring, and Task 9 verify SQL.
- `xml_probe`, `retap`, `cfg`, `target`, `POST_TAP_WAIT_S` — names match the existing `_switch_tiktok` body and the test helpers.

### Scope check

Single subsystem (TT profile-tab security-prompt dismiss in `_switch_tiktok` retap loop). One spec → one plan → one PR. No decomposition needed.
