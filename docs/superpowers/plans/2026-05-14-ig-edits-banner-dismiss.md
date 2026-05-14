# IG "Edits" Banner Dismissal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Instagram "Edits" promo bottom-sheet from breaking Reels publishing by detecting and dismissing it at every UI-dump point in the picker + editor stages, with honest fail-fast for the residual Play-Store-hijack case.

**Architecture:** Two new pure/instance helpers in `publisher_instagram.py` — `_is_ig_edits_promo` (detection) and a rewritten `_dismiss_ig_edits_promo` (3-rung dismissal ladder) — plus an orchestration helper `_ig_handle_edits_promo_at_picker` that the picker/editor loops call. All additive, single-file, no schema changes.

**Tech Stack:** Python 3, `pytest` + `unittest.mock`, Android `uiautomator` XML dumps over ADB.

**Spec:** `docs/superpowers/specs/2026-05-14-ig-edits-banner-dismiss-design.md`
**OpenProject:** #61. **Triage evidence:** `docs/evidence/2026-05-14-ig-publish-failure-triage.md`.

---

## Setup

The publisher code lives in the `GenGo2/delivery-contenthunter` repo, checked out at the prod tree `/root/.openclaw/workspace-genri/autowarm/`. **Do not commit on `main` in the prod tree** — its `post-commit` hook auto-pushes. Work on a feature branch.

- [ ] **S1: Create the feature branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git status            # expect clean; if not, stop and report
git checkout -b fix-ig-edits-banner-dismiss-20260514 origin/main
```

If the prod tree is not on a clean `main` (a parallel session may be using it), instead create an isolated worktree and work there:
```bash
git worktree add /root/.openclaw/workspace-genri/autowarm/.worktrees/ig-edits-banner fix-ig-edits-banner-dismiss-20260514 origin/main
cd /root/.openclaw/workspace-genri/autowarm/.worktrees/ig-edits-banner
```
All file paths below are relative to whichever working directory you chose.

- [ ] **S2: Verify baseline tests pass**

Run: `python3 -m pytest tests/test_ig_share_ok_fallback.py tests/test_ig_gallery_mode_c_d_hardening.py -q`
Expected: all pass (the suite is green; a pre-existing unrelated TT-switcher failure may exist elsewhere — not our concern).

---

## Task 1: `_is_ig_edits_promo` — detection function

**Files:**
- Create: `tests/test_ig_edits_banner_dismiss.py`
- Modify: `publisher_instagram.py` — insert a module-level function + 2 constants immediately before `def _ig_classify_pre_picker_state(` (currently line 350), after `_ig_collect_state_markers` ends (line 348).

- [ ] **Step 1: Write the failing test file with fixtures + `_is_ig_edits_promo` tests**

Create `tests/test_ig_edits_banner_dismiss.py`:

```python
"""Unit tests for IG "Edits" promo banner detection + dismissal.

Spec: docs/superpowers/specs/2026-05-14-ig-edits-banner-dismiss-design.md
Bug:  OpenProject #61.

Banner fixture is derived from a real UI dump (task 5031,
gallery_blind_tap_after_step4): a Compose bottom-sheet carrying the promo
copy `… с помощью Edits`, an install button `Установить приложение`, and a
content-desc-addressable close affordance `Закрыть панель`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_instagram import _is_ig_edits_promo, InstagramMixin  # noqa: E402


# ─── Fixtures ──────────────────────────────────────────────────────────────

def _ui_edits_banner(with_close: bool = True) -> str:
    """Real-derived Edits promo bottom-sheet. `with_close=False` drops the
    `Закрыть панель` affordance (simulates builds without it)."""
    close_node = (
        '<node class="android.widget.Button" content-desc="Закрыть панель" '
        'clickable="true" bounds="[0,0][1080,1338]"/>'
        if with_close else ''
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?><hierarchy rotation=\"0\">"
        '<node class="android.widget.FrameLayout" '
        'resource-id="com.instagram.android:id/compose_bottom_sheet_container" '
        'bounds="[0,0][1080,2340]">'
        f'{close_node}'
        '<node class="android.widget.ImageView" '
        'content-desc="Рестайлинг этого видео сделан с помощью Edits — новом '
        'приложении от Instagram." clickable="false" bounds="[45,1446][203,1604]"/>'
        '<node class="android.widget.TextView" '
        'resource-id="com.instagram.android:id/ig_text" '
        'text="Сделайте свои видео лучше с помощью Edits" '
        'clickable="false" bounds="[237,1417][782,1633]"/>'
        '<node class="android.view.View" '
        'resource-id="com.instagram.android:id/igds_button" '
        'clickable="true" bounds="[45,2031][1035,2166]">'
        '<node class="android.widget.TextView" text="Установить приложение" '
        'clickable="false" bounds="[314,2075][766,2122]"/>'
        '</node></node></hierarchy>'
    )


def _ui_plain_picker() -> str:
    """Reels gallery picker with only the composer `Edits` TAB — no banner."""
    return (
        "<?xml version='1.0' encoding='UTF-8'?><hierarchy rotation=\"0\">"
        '<node class="android.widget.FrameLayout" '
        'resource-id="com.instagram.android:id/gallery_picker" bounds="[0,0][1080,2340]">'
        '<node class="android.widget.Button" text="Edits" clickable="true" '
        'bounds="[40,180][180,280]"/>'
        '<node class="android.widget.Button" text="Черновики" clickable="true" '
        'bounds="[200,180][420,280]"/>'
        '<node class="android.widget.TextView" text="Недавние" clickable="true" '
        'bounds="[40,320][240,400]"/>'
        '<node class="android.widget.ImageView" '
        'resource-id="com.instagram.android:id/gallery_grid_item_thumbnail" '
        'content-desc="видео, создано 12 мая 2026 г." clickable="true" '
        'bounds="[370,300][700,700]"/>'
        '</node></hierarchy>'
    )


def _make_ig_stub() -> InstagramMixin:
    """Bare InstagramMixin instance with the BasePublisher I/O leaves mocked.

    `_dismiss_ig_edits_promo` calls `tap_element` / `adb_swipe` / `adb` —
    BasePublisher methods not present on a bare InstagramMixin — so they are
    mocked here. `dump_ui` and `_current_foreground_package` are intentionally
    left unset: tests that exercise them set them per-case with the exact
    return values / side_effects the scenario needs.
    """
    stub = InstagramMixin.__new__(InstagramMixin)
    stub.platform = 'Instagram'
    stub.adb = MagicMock(return_value='')
    stub.adb_swipe = MagicMock()
    stub.tap_element = MagicMock(return_value=False)  # default: close affordance not found
    stub.log_event = MagicMock()
    stub._save_debug_artifacts = MagicMock()
    stub._safe_kb_probe = MagicMock()
    return stub


# ─── _is_ig_edits_promo ────────────────────────────────────────────────────

def test_is_edits_promo_positive_banner():
    assert _is_ig_edits_promo(_ui_edits_banner()) is True


def test_is_edits_promo_positive_banner_without_close_affordance():
    assert _is_ig_edits_promo(_ui_edits_banner(with_close=False)) is True


def test_is_edits_promo_negative_plain_picker_with_edits_tab():
    """Regression guard: the ever-present `Edits` composer TAB must NOT match."""
    assert _is_ig_edits_promo(_ui_plain_picker()) is False


def test_is_edits_promo_negative_empty_and_none():
    assert _is_ig_edits_promo('') is False
    assert _is_ig_edits_promo(None) is False


def test_is_edits_promo_negative_malformed_xml():
    assert _is_ig_edits_promo('<hierarchy><node unclosed') is False


def test_is_edits_promo_requires_both_markers():
    """Phrase alone or install-text alone is not enough."""
    phrase_only = '<hierarchy><node text="видео с помощью Edits"/></hierarchy>'
    install_only = '<hierarchy><node text="Установить приложение"/></hierarchy>'
    assert _is_ig_edits_promo(phrase_only) is False
    assert _is_ig_edits_promo(install_only) is False
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `python3 -m pytest tests/test_ig_edits_banner_dismiss.py -q`
Expected: `ImportError: cannot import name '_is_ig_edits_promo'` (collection error).

- [ ] **Step 3: Implement `_is_ig_edits_promo`**

In `publisher_instagram.py`, insert immediately before `def _ig_classify_pre_picker_state(ui_xml, foreground_package):` (line 350):

```python
# IG "Edits" promo bottom-sheet markers. Confirmed against a real UI dump
# (task 5031, gallery_blind_tap_after_step4): a Compose bottom-sheet carrying
# the promo copy `… с помощью Edits` and an install button `Установить
# приложение`. `с помощью Edits` is the primary anchor — it is banner copy
# that never appears as a tab/control label (the composer "Edits" tab is just
# text="Edits"). `Закрыть панель` is the content-desc of the scrim Button
# above the sheet — the primary dismissal target. OpenProject #61.
_IG_EDITS_PROMO_PHRASE = 'с помощью Edits'
_IG_EDITS_PROMO_INSTALL = 'Установить приложение'
_IG_EDITS_PROMO_CLOSE_DESC = 'Закрыть панель'


def _is_ig_edits_promo(ui_xml):
    """True only for the IG "Edits" promo bottom-sheet, never the composer tab.

    Requires BOTH the promo phrase and the install-button text. Substring
    match is sufficient (consistent with the file's other detection helpers);
    malformed XML simply won't contain the markers. Empty / None → False.

    Spec: docs/superpowers/specs/2026-05-14-ig-edits-banner-dismiss-design.md §2.1
    """
    if not ui_xml:
        return False
    return _IG_EDITS_PROMO_PHRASE in ui_xml and _IG_EDITS_PROMO_INSTALL in ui_xml
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `python3 -m pytest tests/test_ig_edits_banner_dismiss.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ig_edits_banner_dismiss.py publisher_instagram.py
git commit -m "feat(ig): _is_ig_edits_promo banner detection helper (OpenProject #61)"
```

---

## Task 2: Rewrite `_dismiss_ig_edits_promo` + update the camera call site

**Files:**
- Modify: `publisher_instagram.py:1111-1155` — replace the `_dismiss_ig_edits_promo` method body; add 1 constant near it.
- Modify: `publisher_instagram.py:1481-1482` — update the camera-loop call site for the new return type.
- Modify: `tests/test_ig_edits_banner_dismiss.py` — add dismissal tests.

The current helper returns `bool`, dismisses via `back` ×2 + `force-stop`, and is confirmed only against month-old UI. The rewrite: 3-state return, ladder `Закрыть панель` → swipe-down → `back`, no force-stop, accepts a pre-fetched dump.

- [ ] **Step 1: Write the failing dismissal tests**

Append to `tests/test_ig_edits_banner_dismiss.py`:

```python
# ─── _dismiss_ig_edits_promo ───────────────────────────────────────────────
#
# tap_element is mocked (it is BasePublisher's, with its own tests) — these
# tests assert on which patterns the dismissal ladder *targets*, not on
# tap_element's internal adb dispatch. Its return value is driven per-test:
# True = the rung's element was found+tapped, False = not found.

def _close_desc_pattern_calls(stub):
    """tap_element calls whose pattern list is the close-affordance desc.

    `c[0]` = positional args tuple, `c[1]` = kwargs dict — indexing form
    works on every Python 3 (the `.args`/`.kwargs` attributes are 3.8+ only).
    """
    return [c for c in stub.tap_element.call_args_list
            if len(c[0]) >= 2 and c[0][1] == ['Закрыть панель']]


def test_dismiss_absent_when_no_banner():
    stub = _make_ig_stub()
    result = stub._dismiss_ig_edits_promo(_ui_plain_picker())
    assert result == 'absent'
    stub.tap_element.assert_not_called()
    stub.adb_swipe.assert_not_called()
    stub.adb.assert_not_called()


def test_dismiss_via_close_button():
    """Banner present; `Закрыть панель` tap clears it on the re-dump."""
    stub = _make_ig_stub()
    stub.tap_element = MagicMock(return_value=True)            # close affordance found
    stub.dump_ui = MagicMock(return_value=_ui_plain_picker())  # post-tap re-dump: gone
    with patch('publisher_instagram.time.sleep'):
        result = stub._dismiss_ig_edits_promo(_ui_edits_banner())
    assert result == 'dismissed'
    # rung 1 targeted the close affordance with exact + clickable_only
    assert _close_desc_pattern_calls(stub)
    assert stub.tap_element.call_args_list[0][1] == {
        'exact': True, 'clickable_only': True}
    stub.adb_swipe.assert_not_called()
    stub.log_event.assert_called_once()
    assert stub.log_event.call_args[1]['meta']['method'] == 'close_button'


def test_dismiss_via_swipe_when_no_close_affordance():
    """No `Закрыть панель` (tap_element returns False); swipe-down rung clears it."""
    stub = _make_ig_stub()  # tap_element default return_value=False
    stub.dump_ui = MagicMock(return_value=_ui_plain_picker())  # post-swipe: gone
    with patch('publisher_instagram.time.sleep'):
        result = stub._dismiss_ig_edits_promo(_ui_edits_banner(with_close=False))
    assert result == 'dismissed'
    stub.adb_swipe.assert_called_once_with(540, 1450, 540, 2300, duration=500)
    assert stub.log_event.call_args[1]['meta']['method'] == 'swipe_down'


def test_dismiss_via_back_last_resort():
    """Close affordance absent, swipe doesn't clear it, `back` does."""
    stub = _make_ig_stub()
    # re-dump after swipe: still banner; re-dump after back: gone
    stub.dump_ui = MagicMock(side_effect=[
        _ui_edits_banner(with_close=False),  # after swipe — still present
        _ui_plain_picker(),                  # after back — gone
    ])
    with patch('publisher_instagram.time.sleep'):
        result = stub._dismiss_ig_edits_promo(_ui_edits_banner(with_close=False))
    assert result == 'dismissed'
    stub.adb.assert_any_call('input keyevent 4')
    assert stub.log_event.call_args[1]['meta']['method'] == 'back'


def test_dismiss_still_present_when_ladder_exhausted():
    """Banner survives every rung → 'still_present', no dismissed event."""
    stub = _make_ig_stub()
    stub.dump_ui = MagicMock(return_value=_ui_edits_banner(with_close=False))
    with patch('publisher_instagram.time.sleep'):
        result = stub._dismiss_ig_edits_promo(_ui_edits_banner(with_close=False))
    assert result == 'still_present'
    stub.log_event.assert_not_called()


def test_dismiss_never_targets_install_button():
    """No rung ever taps a pattern referencing the install control."""
    stub = _make_ig_stub()
    stub.dump_ui = MagicMock(return_value=_ui_edits_banner(with_close=False))
    with patch('publisher_instagram.time.sleep'):
        stub._dismiss_ig_edits_promo(_ui_edits_banner(with_close=False))
    for c in stub.tap_element.call_args_list:
        assert all('Установить' not in p for p in c[0][1])


def test_dismiss_dumps_ui_when_not_given():
    """ui_xml=None → helper fetches its own dump."""
    stub = _make_ig_stub()
    stub.dump_ui = MagicMock(return_value=_ui_plain_picker())
    with patch('publisher_instagram.time.sleep'):
        result = stub._dismiss_ig_edits_promo()
    assert result == 'absent'
    stub.dump_ui.assert_called_once()
```

- [ ] **Step 2: Run the new tests, verify they fail**

Run: `python3 -m pytest tests/test_ig_edits_banner_dismiss.py -q -k dismiss`
Expected: failures — old helper returns `bool`, takes no `ui_xml` arg, calls `force-stop`.

- [ ] **Step 3: Replace the `_dismiss_ig_edits_promo` method**

In `publisher_instagram.py`, replace the entire current method (lines 1111-1155, from `def _dismiss_ig_edits_promo(self) -> bool:` through its final `return False`) with the following. It uses the module-level `_is_ig_edits_promo` and `_IG_EDITS_PROMO_CLOSE_DESC` from Task 1:

```python
    def _dismiss_ig_edits_promo(self, ui_xml: str = None) -> str:
        """Clear the IG "Edits" promo bottom-sheet if present.

        Returns one of:
          'absent'        — no banner in the given (or freshly dumped) UI
          'dismissed'     — banner was present and is now gone
          'still_present' — banner present and survived the full ladder

        Ladder, re-checked after each rung: tap `Закрыть панель` →
        swipe-down in the sheet region → single `back`. Never taps the
        install control. No force-stop on this path — the picker/editor
        stages cannot afford a relaunch (camera stage keeps its own).

        Spec: docs/superpowers/specs/2026-05-14-ig-edits-banner-dismiss-design.md §2.2
        """
        try:
            ui = ui_xml if ui_xml else self.dump_ui()
            if not _is_ig_edits_promo(ui):
                return 'absent'

            # Rung 1 — tap the content-desc-addressable close affordance.
            if self.tap_element(ui, [_IG_EDITS_PROMO_CLOSE_DESC],
                                exact=True, clickable_only=True):
                time.sleep(2)
                ui = self.dump_ui()
                if not _is_ig_edits_promo(ui):
                    self.log_event('info', 'IG: Edits-промо закрыто (Закрыть панель)',
                                   meta={'category': 'ig_edits_promo_dismissed',
                                         'method': 'close_button',
                                         'platform': self.platform})
                    return 'dismissed'

            # Rung 2 — swipe the bottom-sheet down and off-screen.
            self.adb_swipe(540, 1450, 540, 2300, duration=500)
            time.sleep(2)
            ui = self.dump_ui()
            if not _is_ig_edits_promo(ui):
                self.log_event('info', 'IG: Edits-промо закрыто (swipe-down)',
                               meta={'category': 'ig_edits_promo_dismissed',
                                     'method': 'swipe_down',
                                     'platform': self.platform})
                return 'dismissed'

            # Rung 3 — single back, last resort (no repeat, no force-stop).
            self.adb('input keyevent 4')
            time.sleep(2)
            ui = self.dump_ui()
            if not _is_ig_edits_promo(ui):
                self.log_event('info', 'IG: Edits-промо закрыто (back)',
                               meta={'category': 'ig_edits_promo_dismissed',
                                     'method': 'back',
                                     'platform': self.platform})
                return 'dismissed'

            log.warning('[FIX: IG-edits-promo] промо пережило весь ladder')
            return 'still_present'
        except Exception as e:
            log.warning(f'[FIX: IG-edits-promo] error: {e}')
            return 'absent'
```

- [ ] **Step 4: Update the camera-loop call site**

In `publisher_instagram.py`, the camera-wait loop currently has (line 1481-1482):
```python
            # [FIX: IG-edits-promo] Meta промо Edits блокирует камеру — снимаем первым.
            if self._dismiss_ig_edits_promo():
```
Replace those two lines with:
```python
            # [FIX: IG-edits-promo] Meta промо Edits блокирует камеру — снимаем первым.
            _edits_status = self._dismiss_ig_edits_promo(ui)
            if _edits_status != 'absent':
```
(`ui` is the dump already taken at the top of the loop iteration — `ui = self.dump_ui()`, currently line 1477. The rest of the block — `last_detected_state = 'edits_promo'` … `continue` — is unchanged; `'dismissed'` and `'still_present'` both correctly mean "banner was here", preserving the existing streak/escalation behaviour.)

- [ ] **Step 5: Run the dismissal tests + the camera-recovery regression test**

Run: `python3 -m pytest tests/test_ig_edits_banner_dismiss.py tests/test_publisher_ig_camera_recovery.py -q`
Expected: all `test_ig_edits_banner_dismiss.py` tests pass (13 total). For `test_publisher_ig_camera_recovery.py` — if it was green at S2 it stays green; if it references `_dismiss_ig_edits_promo`'s old `bool` contract, update those assertions to the 3-state return and note it in the commit.

- [ ] **Step 6: Commit**

```bash
git add publisher_instagram.py tests/test_ig_edits_banner_dismiss.py
git commit -m "feat(ig): rewrite _dismiss_ig_edits_promo — 3-state, close-button ladder (OpenProject #61)"
```

---

## Task 3: `_ig_handle_edits_promo_at_picker` — orchestration helper

**Files:**
- Modify: `publisher_instagram.py` — add an instance method next to `_dismiss_ig_edits_promo` (after its closing line).
- Modify: `tests/test_ig_edits_banner_dismiss.py` — add orchestration tests.

This helper is the single decision point the picker/editor loops call: it does the Play-Store-foreground check, then the banner dismissal, and emits the right fail event so call sites stay thin.

- [ ] **Step 1: Write the failing orchestration tests**

Append to `tests/test_ig_edits_banner_dismiss.py`:

```python
# ─── _ig_handle_edits_promo_at_picker ──────────────────────────────────────

def test_handle_playstore_hijack_fails_fast():
    stub = _make_ig_stub()
    stub._current_foreground_package = MagicMock(return_value='com.android.vending')
    result = stub._ig_handle_edits_promo_at_picker(_ui_plain_picker(), 'gallery_select')
    assert result == 'failed'
    cats = [c[1]['meta']['category'] for c in stub.log_event.call_args_list]
    assert 'ig_edits_promo_playstore_hijack' in cats
    stub._save_debug_artifacts.assert_called_once()


def test_handle_clear_when_nothing_blocking():
    stub = _make_ig_stub()
    stub._current_foreground_package = MagicMock(return_value='com.instagram.android')
    stub.dump_ui = MagicMock(return_value=_ui_plain_picker())
    result = stub._ig_handle_edits_promo_at_picker(_ui_plain_picker(), 'gallery_select')
    assert result == 'clear'
    stub.log_event.assert_not_called()


def test_handle_dismissed_when_banner_cleared():
    stub = _make_ig_stub()
    stub._current_foreground_package = MagicMock(return_value='com.instagram.android')
    stub.dump_ui = MagicMock(return_value=_ui_plain_picker())  # post-dismiss: gone
    with patch('publisher_instagram.time.sleep'):
        result = stub._ig_handle_edits_promo_at_picker(_ui_edits_banner(), 'gallery_select')
    assert result == 'dismissed'


def test_handle_undismissable_fails_fast():
    stub = _make_ig_stub()
    stub._current_foreground_package = MagicMock(return_value='com.instagram.android')
    stub.dump_ui = MagicMock(return_value=_ui_edits_banner(with_close=False))  # never clears
    with patch('publisher_instagram.time.sleep'):
        result = stub._ig_handle_edits_promo_at_picker(
            _ui_edits_banner(with_close=False), 'editor_loop')
    assert result == 'failed'
    cats = [c[1]['meta']['category'] for c in stub.log_event.call_args_list]
    assert 'ig_edits_promo_undismissable' in cats
```

- [ ] **Step 2: Run the new tests, verify they fail**

Run: `python3 -m pytest tests/test_ig_edits_banner_dismiss.py -q -k handle`
Expected: `AttributeError: 'InstagramMixin' object has no attribute '_ig_handle_edits_promo_at_picker'`.

- [ ] **Step 3: Implement `_ig_handle_edits_promo_at_picker`**

In `publisher_instagram.py`, immediately after the `_dismiss_ig_edits_promo` method (after its final `return 'absent'` line), add:

```python
    def _ig_handle_edits_promo_at_picker(self, ui_xml: str, step: str) -> str:
        """Edits-promo blocker check for a picker/editor UI-dump point.

        Returns one of:
          'clear'     — no Play Store, no banner; caller proceeds normally
          'dismissed' — banner was cleared; caller should re-dump + retry
          'failed'    — caller must abort (return False); a fail event has
                        already been emitted (ig_edits_promo_playstore_hijack
                        or ig_edits_promo_undismissable)

        Spec: docs/superpowers/specs/2026-05-14-ig-edits-banner-dismiss-design.md §2.3-2.4
        """
        # Play Store takeover — honest fail-fast, no recovery (spec decision).
        fg = self._current_foreground_package()
        if fg == 'com.android.vending':
            try:
                self._save_debug_artifacts('ig_edits_promo_playstore_hijack')
            except Exception:
                pass
            self._safe_kb_probe(ui_xml, step='ig_edits_promo_playstore_hijack')
            self.log_event('error',
                           'IG: Google Play открылся (промо Edits) — fail-fast',
                           meta={'category': 'ig_edits_promo_playstore_hijack',
                                 'platform': self.platform,
                                 'step': step,
                                 'foreground_package': fg})
            return 'failed'

        status = self._dismiss_ig_edits_promo(ui_xml)
        if status == 'dismissed':
            return 'dismissed'
        if status == 'still_present':
            try:
                self._save_debug_artifacts('ig_edits_promo_undismissable')
            except Exception:
                pass
            self._safe_kb_probe(ui_xml, step='ig_edits_promo_undismissable')
            self.log_event('error',
                           'IG: промо Edits не удалось закрыть — fail-fast',
                           meta={'category': 'ig_edits_promo_undismissable',
                                 'platform': self.platform,
                                 'step': step})
            return 'failed'
        return 'clear'
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python3 -m pytest tests/test_ig_edits_banner_dismiss.py -q`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add publisher_instagram.py tests/test_ig_edits_banner_dismiss.py
git commit -m "feat(ig): _ig_handle_edits_promo_at_picker orchestration + fail-fast codes (OpenProject #61)"
```

---

## Task 4: Wire the helper into Шаг 5 retry loop + video-candidate parse loop

**Files:**
- Modify: `publisher_instagram.py` — two insertions inside `publish_instagram_reel` (the Шаг 5 retry loop ~line 1959 and the video-candidate parse loop ~line 1995).

Wiring inside the ~600-line `publish_instagram_reel` is verified by full-suite regression + the live-smoke in §4 of the spec — the behavioural coverage lives in the Task 1-3 helper tests.

- [ ] **Step 1: Insert into the Шаг 5 gallery-open retry loop**

In `publish_instagram_reel`, the retry loop currently reads (line 1959-1969):
```python
        for attempt in range(5):
            ui = self.dump_ui()
            if self.dismiss_location_dialog(ui): time.sleep(0); continue
            # Camera permission dialog must be granted BEFORE the generic
            # tap-list and BEFORE the gallery-open break-check, otherwise
            # the IG header «Добавление к видео Reels» visible behind the
            # overlay satisfies the break and we proceed with the dialog
            # still blocking gallery thumbnails (post-mortem 2026-05-10).
            if self._dismiss_camera_permission_dialog(ui): continue
            if self.tap_element(ui, ['ОК', 'OK', 'Понятно', 'Разрешить']):
```
Insert three lines between the `_dismiss_camera_permission_dialog` line and the `tap_element(['ОК', ...])` line:
```python
            if self._dismiss_camera_permission_dialog(ui): continue
            # [FIX: IG-edits-promo 2026-05-14] Banner can overlay the picker —
            # clear it (or fail-fast on Play Store hijack) before the
            # gallery-open break-check. OpenProject #61.
            _edits = self._ig_handle_edits_promo_at_picker(ui, 'gallery_open')
            if _edits == 'failed':
                return False
            if _edits == 'dismissed':
                continue
            if self.tap_element(ui, ['ОК', 'OK', 'Понятно', 'Разрешить']):
```

- [ ] **Step 2: Insert into the video-candidate parse loop**

The parse loop currently reads (line 1995-1998):
```python
        for parse_attempt in range(5):
            raw_ui = self.dump_ui()
            try:
                root_el = ET.fromstring(raw_ui)
```
Insert the guard between `raw_ui = self.dump_ui()` and `try:`:
```python
        for parse_attempt in range(5):
            raw_ui = self.dump_ui()
            # [FIX: IG-edits-promo 2026-05-14] Clear the promo banner (or
            # fail-fast on Play Store hijack) before parsing video candidates:
            # the banner's promo ImageView desc contains the word "видео" and
            # would otherwise be mis-picked as a candidate. OpenProject #61.
            _edits = self._ig_handle_edits_promo_at_picker(raw_ui, 'gallery_select')
            if _edits == 'failed':
                return False
            if _edits == 'dismissed':
                continue
            try:
                root_el = ET.fromstring(raw_ui)
```

- [ ] **Step 3: Run the full IG test suite for regression**

Run: `python3 -m pytest tests/test_ig_edits_banner_dismiss.py tests/test_ig_gallery_picker_hardening.py tests/test_ig_gallery_mode_c_d_hardening.py tests/test_publisher_ig_editor.py -q`
Expected: all pass. (If `test_ig_gallery_picker_hardening.py` exercises the parse loop with a fixture, confirm the new guard returns `'clear'` for non-banner fixtures — it should, since `_current_foreground_package` on a stub returns a mock and `_is_ig_edits_promo` is `False`. If a test stub lacks `_current_foreground_package`, add it as a `MagicMock(return_value='com.instagram.android')` in that test's setup and note it in the commit.)

- [ ] **Step 4: Verify the call sites by inspection**

Run: `git diff --stat && grep -n "_ig_handle_edits_promo_at_picker" publisher_instagram.py`
Expected: 3 hits — the method definition, plus the two new call sites at `gallery_open` and `gallery_select`.

- [ ] **Step 5: Commit**

```bash
git add publisher_instagram.py
git commit -m "feat(ig): wire Edits-promo guard into Шаг 5 picker + parse loop (OpenProject #61)"
```

---

## Task 5: Wire the helper into the editor-loop re-select paths

**Files:**
- Modify: `publisher_instagram.py` — two insertions inside `publish_instagram_reel`'s editor loop (`editor_loop_1` ~line 2234 and `editor_loop_2` ~line 2459).

- [ ] **Step 1: Insert into `editor_loop_1`**

In the editor loop, `editor_loop_1` currently reads (line 2233-2236):
```python
                    return False

                _resel = False
                _resel_all_clickable = []
```
Insert the guard immediately before `_resel = False`:
```python
                    return False

                # [FIX: IG-edits-promo 2026-05-14] banner / Play Store guard
                # before the editor-loop re-select parse. OpenProject #61.
                _edits = self._ig_handle_edits_promo_at_picker(ui, 'editor_loop')
                if _edits == 'failed':
                    return False
                if _edits == 'dismissed':
                    ui = self.dump_ui()
                _resel = False
                _resel_all_clickable = []
```
(On `'dismissed'` we re-dump `ui` so the existing `_resel` parse below runs on the cleared screen; no `continue` — the parse block is the next thing and works on fresh `ui`.)

- [ ] **Step 2: Insert into `editor_loop_2`**

`editor_loop_2` currently reads (line 2457-2460):
```python
                        return False

                    _resel2 = False
                    _resel2_all_clickable = []
```
Insert the guard immediately before `_resel2 = False` (note the deeper indentation — this block is one level further nested):
```python
                        return False

                    # [FIX: IG-edits-promo 2026-05-14] banner / Play Store guard
                    # before the editor-loop re-select parse. OpenProject #61.
                    _edits = self._ig_handle_edits_promo_at_picker(ui, 'editor_loop')
                    if _edits == 'failed':
                        return False
                    if _edits == 'dismissed':
                        ui = self.dump_ui()
                    _resel2 = False
                    _resel2_all_clickable = []
```

- [ ] **Step 3: Run the full IG test suite**

Run: `python3 -m pytest tests/ -q -k "ig or instagram"`
Expected: all pass except any pre-existing unrelated failure noted at S2. Confirm no new failures.

- [ ] **Step 4: Verify all call sites and final diff**

Run: `grep -n "_ig_handle_edits_promo_at_picker" publisher_instagram.py && git diff --stat`
Expected: 5 hits total — 1 definition + 4 call sites (`gallery_open`, `gallery_select`, `editor_loop` ×2). `git diff --stat` shows only `publisher_instagram.py` and `tests/test_ig_edits_banner_dismiss.py` changed.

- [ ] **Step 5: Commit**

```bash
git add publisher_instagram.py
git commit -m "feat(ig): wire Edits-promo guard into editor-loop re-select paths (OpenProject #61)"
```

---

## After the plan

1. **`codex review`** the full branch diff: `git diff origin/main | ~/.local/bin/codex review -` — apply feedback, rounds until 0 P1.
2. **PR** to `GenGo2/delivery-contenthunter`; squash-merge once green + 0 P1.
3. **Deploy:** on the prod tree `/root/.openclaw/workspace-genri/autowarm/`, confirm it is on a clean `main`, then `git pull --ff-only`. No PM2 reload (publisher.py is spawned per-task). No force-push.
4. **Live verify (24h):** per spec §5 — `ig_edits_promo_dismissed` events present; combined `ig_picker_wrong_candidate` + `ig_gallery_no_video_candidate`(Play-Store) down to ≤20% of the pre-fix daily rate; `ig_edits_promo_playstore_hijack` / `ig_edits_promo_undismissable` low.
5. **Update OpenProject #61** — status comment (house style: Что было не так → Что сделано → Что осталось) and move status; write a `docs/evidence/2026-05-14-ig-edits-banner-dismiss-shipped.md`.
