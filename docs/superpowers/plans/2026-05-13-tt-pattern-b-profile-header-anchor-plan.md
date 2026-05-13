# TT Pattern B — profile-header tap pivots to «Меню профиля» path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 19/24h `tt_account_sheet_closed_before_parse` spike caused by the new TT username-tap behaviour (opens Stories/LIVE viewer instead of account-switcher bottomsheet) by adding a probe-and-pivot orchestrator that falls back to «Меню профиля» drawer with diagnostic logging.

**Architecture:** Add a new orchestrator method `_open_tt_account_switcher` to `AccountSwitcher` that wraps the existing `_tap_profile_header` (Phase 1 probe), detects Stories, reverses with KEYCODE_BACK, and pivots to a «Меню профиля» drawer search (Phase 2). Three new pure-function helpers (`_detect_tt_stories_viewer`, `_find_tt_account_switcher_anchor_in_drawer`, `_has_tt_bottomsheet_signature`) make the logic testable. Existing `_tt_is_own_profile` is reused for BACK-recovery verification. The callsite in `_switch_tiktok` (L2262-L2305) is collapsed to a single orchestrator call with a thin error-to-`_fail` mapping. New error codes are added to `_SWITCHER_STEP_TO_CATEGORY` in `publisher_kernel.py` so the canonical-error-code resolver picks them up.

**Tech Stack:** Python 3.12, pytest, regex/xml.etree, uiautomator dumps. No DB migrations. Deploy via auto-push hook to GenGo2/delivery-contenthunter.

**Spec:** `docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md` (commit `25af6bd86`, codex-reviewed clean over 6 rounds).

---

## File Structure

**Modified files:**
- `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` — module-level constant `TT_DRAWER_ACCOUNT_TRIGGERS`, module-level helper `_top_labels`, four new `AccountSwitcher` methods (`_detect_tt_stories_viewer`, `_find_tt_account_switcher_anchor_in_drawer`, `_has_tt_bottomsheet_signature`, `_open_tt_account_switcher`), refactored callsite block at L2262-L2305 inside `_switch_tiktok`.
- `/root/.openclaw/workspace-genri/autowarm/publisher_kernel.py` — extend `_SWITCHER_STEP_TO_CATEGORY` (currently L76-end) with 5 new TT step→category entries; existing `'tt_3_open_list'` mapping stays (it now serves as fallback for the legacy semantic).

**New files:**
- `/root/.openclaw/workspace-genri/autowarm/tests/test_tt_account_switcher_open.py` — 23 unit tests covering helpers, orchestrator branches, invariants, signature regression.

**Untouched:**
- `_tap_profile_header` (L3474) — shared with IG/YT-RO; signature must remain `(self, elements, header_y_max, step, fallback_coords) -> bool`.
- `_tt_is_own_profile` (L1616) — reused as BACK-verification predicate.
- Any IG/YT switcher code.

---

## Task 1: Module-level helpers — `TT_DRAWER_ACCOUNT_TRIGGERS` + `_top_labels`

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (add at module level after `ACCOUNT_LIST_ANCHORS` definition, around L130)
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_tt_account_switcher_open.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_tt_account_switcher_open.py`:

```python
"""Unit tests for TT Pattern B fix — probe-and-pivot account-switcher path.

Spec: docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from account_switcher import (
    AccountSwitcher,
    SwitchResult,
    TT_DRAWER_ACCOUNT_TRIGGERS,
    UIElement,
    _top_labels,
)


def make_el(text='', cd='', clickable=False, bounds=(0, 0, 1080, 100)):
    return UIElement(text=text, content_desc=cd, clickable=clickable, bounds=bounds)


def test_top_labels_dedupes_and_truncates():
    elements = [
        make_el(text='Главная'),
        make_el(cd='Профиль'),
        make_el(text='Главная'),  # dup
        make_el(text=''),  # empty, skipped
        make_el(text=' Подписки '),  # whitespace stripped
    ] + [make_el(text=f'x{i}') for i in range(40)]
    out = _top_labels(elements, 30)
    assert len(out) == 30
    assert out[:3] == ['Главная', 'Профиль', 'Подписки']
    assert all(s for s in out)  # no empties


def test_top_labels_label_length_capped():
    long_label = 'A' * 100
    out = _top_labels([make_el(text=long_label)], 30)
    assert out == ['A' * 40]


def test_tt_drawer_account_triggers_priority_order():
    # Priority order must put exact RU/EN account-management strings BEFORE
    # the broader fallbacks ('аккаунты', 'accounts') so a drawer containing
    # both 'Управление аккаунтами' and 'Аккаунты' matches the more specific.
    assert TT_DRAWER_ACCOUNT_TRIGGERS[0] == 'управление аккаунтами'
    assert TT_DRAWER_ACCOUNT_TRIGGERS.index('аккаунты') > \
           TT_DRAWER_ACCOUNT_TRIGGERS.index('управление аккаунтами')
    assert TT_DRAWER_ACCOUNT_TRIGGERS.index('accounts') > \
           TT_DRAWER_ACCOUNT_TRIGGERS.index('manage accounts')
    # All entries lowercase (matched against label.lower())
    assert all(t == t.lower() for t in TT_DRAWER_ACCOUNT_TRIGGERS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `/root/.openclaw/workspace-genri/autowarm`:

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v
```

Expected: 3 tests FAIL with `ImportError: cannot import name 'TT_DRAWER_ACCOUNT_TRIGGERS'` / `_top_labels`.

- [ ] **Step 3: Implement constant + helper**

In `account_switcher.py`, after `ACCOUNT_LIST_ANCHORS = {...}` definition (around L142, before `_TT_FEED_MARKERS`), insert:

```python
# ─────────────────────────────────────────────────────────────────────────────
# TT Pattern B (2026-05-13) — drawer-trigger constants and forensic helper.
# Spec: docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md
# ─────────────────────────────────────────────────────────────────────────────
TT_DRAWER_ACCOUNT_TRIGGERS = [
    'управление аккаунтами',
    'manage accounts',
    'switch account',
    'сменить аккаунт',
    'переключить аккаунт',
    'аккаунты',
    'accounts',
]


def _top_labels(elements: list, n: int) -> list:
    """Return up to `n` unique non-empty `el.label[:40]` strings, insertion order.

    Used for forensic `meta` payloads on switcher failures so the first
    real failure under a new code yields actionable evidence without an
    extra round-trip to the device. Bounded to keep events table rows
    small (≤1.2 KB per event for n=30).
    """
    seen: set = set()
    out: list = []
    for el in elements:
        label = (el.label or '').strip()[:40]
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
        if len(out) >= n:
            break
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v
```

Expected: all tests in `test_tt_account_switcher_open.py` pass (pytest exit 0).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add account_switcher.py tests/test_tt_account_switcher_open.py
git commit -m "feat(tt-switcher): add TT_DRAWER_ACCOUNT_TRIGGERS + _top_labels

Module-level constant and forensic helper for the TT Pattern B fix —
prep for the probe-and-pivot orchestrator. See spec
docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md"
```

---

## Task 2: `_detect_tt_stories_viewer` helper

**Files:**
- Modify: `account_switcher.py` (add as `AccountSwitcher` method, after `_tap_profile_header` at ~L3494)
- Test: `tests/test_tt_account_switcher_open.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tt_account_switcher_open.py`:

```python
def _make_switcher() -> AccountSwitcher:
    """Build an AccountSwitcher with all p.* mocked — for pure-method tests."""
    p = MagicMock()
    return AccountSwitcher(p)


def test_detect_tt_stories_viewer_ru_yes():
    sw = _make_switcher()
    elements = [
        make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
        make_el(cd='Еще', bounds=(900, 2080, 1080, 2200)),
        make_el(text='clickpay_under · 13 ч. назад',
                bounds=(50, 1000, 700, 1080)),
    ]
    assert sw._detect_tt_stories_viewer(elements) is True


def test_detect_tt_stories_viewer_no_account_sheet():
    sw = _make_switcher()
    elements = [
        make_el(text='Управление аккаунтами', bounds=(50, 100, 600, 180)),
        make_el(text='@user1', bounds=(50, 300, 200, 380)),
        make_el(text='@user2', bounds=(50, 400, 200, 480)),
    ]
    assert sw._detect_tt_stories_viewer(elements) is False


def test_detect_tt_stories_viewer_no_blank_only_one_marker():
    sw = _make_switcher()
    elements = [
        make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
        # only one of three signals — must NOT classify as Stories
    ]
    assert sw._detect_tt_stories_viewer(elements) is False


def test_detect_tt_stories_viewer_english_locale():
    sw = _make_switcher()
    elements = [
        make_el(cd='Close', bounds=(900, 200, 1080, 300)),
        make_el(cd='More', bounds=(900, 2080, 1080, 2200)),
        make_el(text='13 hours ago', bounds=(50, 1000, 700, 1080)),
    ]
    assert sw._detect_tt_stories_viewer(elements) is True


def test_detect_tt_stories_viewer_close_outside_top_band_ignored():
    sw = _make_switcher()
    # 'Закрыть' at y=400 (below 300 threshold) — should not count.
    elements = [
        make_el(cd='Закрыть', bounds=(900, 400, 1080, 500)),
        make_el(cd='Еще', bounds=(900, 2080, 1080, 2200)),
    ]
    assert sw._detect_tt_stories_viewer(elements) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py::test_detect_tt_stories_viewer_ru_yes -v
```

Expected: FAIL — `AttributeError: 'AccountSwitcher' object has no attribute '_detect_tt_stories_viewer'`.

- [ ] **Step 3: Implement helper**

In `account_switcher.py`, add as `AccountSwitcher` method (insert after `_tap_profile_header`, ~L3494, before `_tap_by_triggers`):

```python
    # Module-level regex compiled once for hot paths.
    _TT_STORIES_TIMETEXT_RE = re.compile(
        r'(\d+\s*ч\.?\s*назад|\d+\s*мин\.?\s*назад'
        r'|\d+\s*hours?\s*ago|\d+\s*minutes?\s*ago'
        r'|\d+\s*зрителей|\d+\s*viewers?)',
        re.IGNORECASE,
    )

    def _detect_tt_stories_viewer(self, elements: list) -> bool:
        """True if elements look like a TT Stories / LIVE viewer.

        Detection: ≥2 of 3 markers must be present
          - content-desc in {'Закрыть','Close'} where y_top < 300
          - content-desc in {'Еще','Ещё','More'} where y_top > 1900
          - any text matches stories-timetext regex (hours/mins/viewers)

        Pure function over UIElement list — safe to test in isolation.
        """
        close_markers = {'закрыть', 'close'}
        more_markers = {'еще', 'ещё', 'more'}
        hit_close = hit_more = hit_time = False
        for el in elements:
            cd = (el.content_desc or '').strip().lower()
            txt = el.text or ''
            y_top = el.bounds[1] if el.bounds else 0
            if cd in close_markers and y_top < 300:
                hit_close = True
            elif cd in more_markers and y_top > 1900:
                hit_more = True
            elif txt and self._TT_STORIES_TIMETEXT_RE.search(txt):
                hit_time = True
        return sum([hit_close, hit_more, hit_time]) >= 2
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v
```

Expected: all tests pass (pytest exit 0).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add account_switcher.py tests/test_tt_account_switcher_open.py
git commit -m "feat(tt-switcher): _detect_tt_stories_viewer (RU+EN locale)

TT Stories / LIVE viewer detection — ≥2 of 3 markers (Закрыть/Close
top, Еще/More bottom, time-text 'N hours ago'/'N ч назад'). Spec
invariant — RU+EN coverage. 5 unit tests."
```

---

## Task 3: `_find_tt_account_switcher_anchor_in_drawer` (two-pass)

**Files:**
- Modify: `account_switcher.py` (new `AccountSwitcher` method, after `_detect_tt_stories_viewer`)
- Test: `tests/test_tt_account_switcher_open.py`

- [ ] **Step 1: Write failing tests**

```python
def test_find_drawer_anchor_ru_clickable_direct():
    sw = _make_switcher()
    el_match = make_el(text='Управление аккаунтами', clickable=True,
                       bounds=(50, 500, 1030, 560))
    elements = [
        make_el(text='Настройки', clickable=True, bounds=(50, 400, 1030, 460)),
        el_match,
    ]
    out = sw._find_tt_account_switcher_anchor_in_drawer(elements)
    assert out is el_match


def test_find_drawer_anchor_en_clickable_direct():
    sw = _make_switcher()
    el_match = make_el(text='Manage accounts', clickable=True,
                       bounds=(50, 500, 1030, 560))
    elements = [el_match,
                make_el(text='Logout', clickable=True,
                        bounds=(50, 600, 1030, 660))]
    out = sw._find_tt_account_switcher_anchor_in_drawer(elements)
    assert out is el_match


def test_find_drawer_anchor_fallback_аккаунты():
    sw = _make_switcher()
    el_match = make_el(text='Аккаунты', clickable=True,
                       bounds=(50, 500, 1030, 560))
    elements = [el_match]
    out = sw._find_tt_account_switcher_anchor_in_drawer(elements)
    assert out is el_match


def test_find_drawer_anchor_none_irrelevant_content():
    sw = _make_switcher()
    elements = [
        make_el(text='Настройки', clickable=True, bounds=(0, 0, 100, 100)),
        make_el(text='Логин', clickable=True, bounds=(0, 100, 100, 200)),
    ]
    out = sw._find_tt_account_switcher_anchor_in_drawer(elements)
    assert out is None


def test_find_drawer_anchor_text_with_clickable_parent():
    """Pass 2: text on non-clickable child, clickable parent at overlapping bounds."""
    sw = _make_switcher()
    text_node = make_el(text='Управление аккаунтами', clickable=False,
                        bounds=(100, 500, 500, 560))
    clickable_row = make_el(text='', clickable=True,
                            bounds=(50, 490, 1080, 580))
    elements = [text_node, clickable_row,
                make_el(text='Other', clickable=True,
                        bounds=(50, 700, 1080, 780))]
    out = sw._find_tt_account_switcher_anchor_in_drawer(elements)
    assert out is clickable_row


def test_find_drawer_anchor_priority_order_specific_beats_generic():
    """When both 'Управление аккаунтами' and 'Аккаунты' exist as clickables,
    the more specific (earlier in priority list) wins."""
    sw = _make_switcher()
    specific = make_el(text='Управление аккаунтами', clickable=True,
                       bounds=(50, 500, 1030, 560))
    generic = make_el(text='Аккаунты', clickable=True,
                      bounds=(50, 700, 1030, 760))
    out = sw._find_tt_account_switcher_anchor_in_drawer([generic, specific])
    assert out is specific
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py::test_find_drawer_anchor_ru_clickable_direct -v
```

Expected: FAIL — method missing.

- [ ] **Step 3: Implement helper**

Add after `_detect_tt_stories_viewer`:

```python
    def _find_tt_account_switcher_anchor_in_drawer(self, elements: list):
        """Find a tappable element in the «Меню профиля» drawer that opens
        the account-switcher bottomsheet.

        Two-pass algorithm:
          1. Clickable-direct: first clickable element whose label.lower()
             contains a trigger, scanning triggers in priority order.
          2. Text-with-clickable-ancestor: for each trigger, find any
             matching label element, then find a clickable element whose
             bounds contain the text's center (row-overlap pattern, mirrors
             find_yt_row_by_gmail at account_switcher.py:415).

        Returns the clickable UIElement to tap, or None.
        """
        # --- Pass 1: clickable-direct ---
        for trigger in TT_DRAWER_ACCOUNT_TRIGGERS:
            for el in elements:
                if not el.clickable:
                    continue
                if trigger in (el.label or '').lower():
                    return el
        # --- Pass 2: text node + clickable ancestor/sibling at overlapping bounds ---
        for trigger in TT_DRAWER_ACCOUNT_TRIGGERS:
            text_el = None
            for el in elements:
                if trigger in (el.label or '').lower():
                    text_el = el
                    break
            if text_el is None:
                continue
            cx, cy = text_el.center
            for el in elements:
                if not el.clickable:
                    continue
                x1, y1, x2, y2 = el.bounds
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    return el
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v
```

Expected: all tests pass (pytest exit 0).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add account_switcher.py tests/test_tt_account_switcher_open.py
git commit -m "feat(tt-switcher): _find_tt_account_switcher_anchor_in_drawer (two-pass)

Two-pass broad-anchor search: clickable-direct first, then text-node +
clickable-ancestor (Android pattern where text is on non-clickable
child). Priority order: specific RU/EN triggers > 'аккаунты'/'accounts'
fallbacks. 6 unit tests."
```

---

## Task 4: `_has_tt_bottomsheet_signature` + reuse `_tt_is_own_profile`

**Files:**
- Modify: `account_switcher.py` (new method after `_find_tt_account_switcher_anchor_in_drawer`)
- Test: `tests/test_tt_account_switcher_open.py`

- [ ] **Step 1: Write failing tests**

```python
def test_has_tt_bottomsheet_signature_add_account_ru_with_plus():
    sw = _make_switcher()
    elements = [
        make_el(text='+ Добавить аккаунт', clickable=True,
                bounds=(50, 1900, 1030, 1980)),
    ]
    assert sw._has_tt_bottomsheet_signature(elements) is True


def test_has_tt_bottomsheet_signature_add_account_ru_without_plus():
    """TT often renders the '+' icon as a separate node, leaving the
    text as plain 'Добавить аккаунт'. Must still match."""
    sw = _make_switcher()
    elements = [
        make_el(text='Добавить аккаунт', clickable=True,
                bounds=(50, 1900, 1030, 1980)),
    ]
    assert sw._has_tt_bottomsheet_signature(elements) is True


def test_has_tt_bottomsheet_signature_add_account_en():
    sw = _make_switcher()
    elements = [
        make_el(text='+ Add account', clickable=True,
                bounds=(50, 1900, 1030, 1980)),
    ]
    assert sw._has_tt_bottomsheet_signature(elements) is True


def test_has_tt_bottomsheet_signature_add_account_en_without_plus():
    sw = _make_switcher()
    elements = [
        make_el(text='Add account', clickable=True,
                bounds=(50, 1900, 1030, 1980)),
    ]
    assert sw._has_tt_bottomsheet_signature(elements) is True


def test_has_tt_bottomsheet_signature_two_at_handles_below_y600():
    sw = _make_switcher()
    elements = [
        make_el(text='@user1', bounds=(50, 800, 300, 880)),
        make_el(text='@user2', bounds=(50, 900, 300, 980)),
    ]
    assert sw._has_tt_bottomsheet_signature(elements) is True


def test_has_tt_bottomsheet_signature_only_one_handle_false():
    sw = _make_switcher()
    elements = [make_el(text='@user1', bounds=(50, 800, 300, 880))]
    assert sw._has_tt_bottomsheet_signature(elements) is False


def test_has_tt_bottomsheet_signature_handles_above_y600_false():
    sw = _make_switcher()
    elements = [
        make_el(text='@user1', bounds=(50, 200, 300, 280)),
        make_el(text='@user2', bounds=(50, 300, 300, 380)),
    ]
    assert sw._has_tt_bottomsheet_signature(elements) is False


def test_has_tt_bottomsheet_signature_broad_anchor_alone_false():
    """Spec invariant: 'Управление аккаунтами' alone (the broad anchor)
    must NOT count as a sheet signature — only positive sheet markers."""
    sw = _make_switcher()
    elements = [
        make_el(text='Управление аккаунтами', clickable=True,
                bounds=(50, 500, 1030, 560)),
    ]
    assert sw._has_tt_bottomsheet_signature(elements) is False


def test_has_tt_bottomsheet_signature_word_account_substring_does_not_leak():
    """Regex precedence guard: 'r"^\+\s*(Добавить|Add)\s+(аккаунт|account)"' —
    bare 'account' substring elsewhere must not trigger."""
    sw = _make_switcher()
    elements = [make_el(text='Manage account settings',
                       bounds=(50, 100, 600, 180))]
    assert sw._has_tt_bottomsheet_signature(elements) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v -k bottomsheet_signature
```

Expected: 7 FAIL — method missing.

- [ ] **Step 3: Implement helper**

Add after `_find_tt_account_switcher_anchor_in_drawer`:

```python
    _TT_ADD_ACCOUNT_RE = re.compile(
        # Plus prefix optional (TT often renders the icon as a separate
        # node, leaving plain "Добавить аккаунт"); grouping with the
        # second (аккаунт|account) prevents bare-'account' substring leak.
        r'^\+?\s*(Добавить|Add)\s+(аккаунт|account)\b',
        re.IGNORECASE,
    )

    def _has_tt_bottomsheet_signature(self, elements: list) -> bool:
        """Positive sheet detection: distinct markers of the opened
        account-switcher bottomsheet.

        True if either:
          - ≥1 element whose label matches '+ Добавить аккаунт' / '+ Add account'
            (grouped regex — bare 'account' substring elsewhere must NOT match)
          - ≥2 elements with text starting '@' AND y_top > 600 (handle-row
            signature in the bottom area of the screen)

        Robust to bottomsheets that legitimately contain a clickable
        broad-anchor row.
        """
        handle_count = 0
        for el in elements:
            label = (el.label or '').strip()
            if self._TT_ADD_ACCOUNT_RE.match(label):
                return True
            txt = (el.text or '').strip()
            if txt.startswith('@') and el.bounds[1] > 600:
                handle_count += 1
                if handle_count >= 2:
                    return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v
```

Expected: all tests pass (pytest exit 0).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add account_switcher.py tests/test_tt_account_switcher_open.py
git commit -m "feat(tt-switcher): _has_tt_bottomsheet_signature positive detector

Distinguishes opened account-switcher bottomsheet from still-open
drawer with broad-anchor row. Markers: '+ Добавить/Add аккаунт/account'
row (grouped regex — no bare-'account' substring leakage) OR ≥2
@handles below y=600. 7 unit tests including regex-precedence guard."
```

---

## Task 5: `_open_tt_account_switcher` orchestrator — Phase 1 (probe + retry + Stories pivot)

**Files:**
- Modify: `account_switcher.py` (new method after `_has_tt_bottomsheet_signature`)
- Test: `tests/test_tt_account_switcher_open.py`

This task implements the orchestrator scaffolding through the end of Phase 1 (probe retry, Stories detection, BACK recovery). The menu/drawer/sheet path is stubbed to raise — Phase 2 is Task 6.

- [ ] **Step 1: Write failing tests**

```python
# ─── Orchestrator Phase 1 tests ───────────────────────────────────────────

class _FakeProxy:
    """Minimal mock of the publisher proxy `self.p` used by AccountSwitcher.

    Records all log_event / save_dump / adb_shell / dump_ui / adb_tap
    calls. dump_ui returns the next pre-set XML from `dump_queue`.
    """
    def __init__(self, dump_queue=None, tap_returns=None):
        self.dump_queue = list(dump_queue or [])
        self.tap_returns = list(tap_returns or [])  # for tap_element
        self.events = []
        self.saved_dumps = []
        self.adb_taps = []
        self.adb_shells = []

    def log_event(self, kind, msg='', meta=None):
        self.events.append({'kind': kind, 'msg': msg, 'meta': meta or {}})

    def dump_ui(self, retries=1):
        return self.dump_queue.pop(0) if self.dump_queue else ''

    def adb_tap(self, x, y):
        self.adb_taps.append((x, y))

    def adb_shell(self, cmd, **kw):
        self.adb_shells.append(cmd)

    def tap_element(self, xml, desc, clickable_only=True):
        return self.tap_returns.pop(0) if self.tap_returns else False


def _make_sw_with_proxy(dump_queue=None, tap_returns=None):
    p = _FakeProxy(dump_queue=dump_queue, tap_returns=tap_returns)
    sw = AccountSwitcher(p)
    sw._save_dump = MagicMock(wraps=lambda label, xml: sw.p.saved_dumps.append((label, xml)))
    sw._maybe_screenshot = MagicMock()
    sw._tap_profile_header = MagicMock(return_value=True)
    sw._tt_is_own_profile = MagicMock(return_value=True)
    return sw


_TT_CFG = {
    'package': 'com.zhiliaoapp.musically',
    'launch_activity': 'com.zhiliaoapp.musically/com.ss.android.ugc.aweme.main.MainActivity',
    'profile_title_header_y_range': (120, 700),
    'plus_button': {'desc': ['+'], 'coords': (540, 2200)},
    'editor_triggers': ['Дальше', 'Next'],
}


# Synthetic XML snippets that produce predictable parsed elements when
# fed through parse_ui_dump. We bypass parse_ui_dump by stubbing it
# instead; see helper below.

def _stub_parse(sw, queue):
    """Replace parse_ui_dump globally for the duration of one test.

    Each call pops the next list from `queue`.
    """
    import account_switcher as mod
    orig = mod.parse_ui_dump
    q = list(queue)
    mod.parse_ui_dump = lambda xml: q.pop(0) if q else []
    return lambda: setattr(mod, 'parse_ui_dump', orig)


def test_open_tt_account_switcher_legacy_path_probe_opens_sheet(monkeypatch):
    """Phase 1 happy: first probe yields the bottomsheet directly
    (old TT version). Returns (anchor_bounds, None) immediately, no
    Phase-2 calls."""
    sw = _make_sw_with_proxy(dump_queue=['<sheet/>'])
    sheet_elements = [
        make_el(text='Управление аккаунтами', clickable=False,
                bounds=(50, 100, 1030, 180)),
        make_el(text='@user1', bounds=(50, 800, 300, 880)),
        make_el(text='@user2', bounds=(50, 900, 300, 980)),
    ]
    import account_switcher as mod
    monkeypatch.setattr(mod, 'parse_ui_dump', lambda xml: sheet_elements)
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: (50, 100, 1030, 180))

    sw._find_tt_account_switcher_anchor_in_drawer = MagicMock()  # must not be called

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err is None
    assert anchor == (50, 100, 1030, 180)
    sw._find_tt_account_switcher_anchor_in_drawer.assert_not_called()
    # Forensic dump saved under correct step
    assert ('tt_3_open_list_probe', '<sheet/>') in sw.p.saved_dumps


def test_open_tt_account_switcher_single_account_legacy_semantic(monkeypatch):
    """Phase 1: both probe attempts yield neither sheet nor Stories →
    legacy 'single-account device' semantic. Returns
    (None, 'tt_account_sheet_closed_before_parse') with one error event."""
    sw = _make_sw_with_proxy(dump_queue=['<x1/>', '<x2/>'])
    blank_elements = [make_el(text='Random', bounds=(50, 100, 200, 180))]
    import account_switcher as mod
    monkeypatch.setattr(mod, 'parse_ui_dump', lambda xml: blank_elements)
    monkeypatch.setattr(mod, 'find_anchor_bounds', lambda els, anchors: None)

    anchor, err = sw._open_tt_account_switcher(
        elements=blank_elements, cfg=_TT_CFG, target='ghost',
        step_base='tt_3_open_list')

    assert err == 'tt_account_sheet_closed_before_parse'
    assert anchor is None
    # Exactly one error-type event with the canonical category.
    err_events = [e for e in sw.p.events if e['kind'] == 'error']
    assert len(err_events) == 1
    assert err_events[0]['meta']['category'] == 'tt_account_sheet_closed_before_parse'
    assert err_events[0]['meta']['target'] == 'ghost'
    assert 'probe_top_labels' in err_events[0]['meta']
    # Two probe dumps saved (retry budget preserved).
    assert ('tt_3_open_list_probe', '<x1/>') in sw.p.saved_dumps
    assert ('tt_3_open_list_probe_retry1', '<x2/>') in sw.p.saved_dumps


def test_open_tt_account_switcher_phase1_handles_only_sheet_synthesised(
        monkeypatch):
    """Phase 1: first probe opens a sheet that has @handles but no
    ACCOUNT_LIST_ANCHORS text. Must succeed with synthesised anchor_bounds —
    mirrors the Phase 2 handles-only synthesis path."""
    sw = _make_sw_with_proxy(dump_queue=['<sheet/>'])
    first_handle = make_el(text='@user1', bounds=(50, 800, 300, 880))
    sheet_els = [first_handle,
                 make_el(text='@user2', bounds=(50, 900, 300, 980))]
    import account_switcher as mod
    monkeypatch.setattr(mod, 'parse_ui_dump', lambda xml: sheet_els)
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: None)

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err is None
    assert tuple(anchor) == tuple(first_handle.bounds)


def test_open_tt_account_switcher_probe_retry_recovers_old_layout(monkeypatch):
    """Phase 1: first probe yields blank, second yields sheet
    (transient old-layout state). Returns (anchor, None) on attempt 2.
    Guards invariant #4."""
    sw = _make_sw_with_proxy(dump_queue=['<x1/>', '<sheet/>'])
    blank = [make_el(text='', bounds=(0, 0, 1, 1))]
    sheet = [make_el(text='Управление аккаунтами', clickable=False,
                     bounds=(50, 100, 1030, 180))]
    import account_switcher as mod
    parse_calls = iter([blank, sheet])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    anchor_calls = iter([None, (50, 100, 1030, 180)])
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: next(anchor_calls))

    anchor, err = sw._open_tt_account_switcher(
        elements=blank, cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err is None
    assert anchor == (50, 100, 1030, 180)
    assert sw._tap_profile_header.call_count == 2  # retry exercised
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py::test_open_tt_account_switcher_legacy_path_probe_opens_sheet -v
```

Expected: FAIL — `_open_tt_account_switcher` missing.

- [ ] **Step 3: Implement Phase 1 of orchestrator**

Add after `_has_tt_bottomsheet_signature`:

```python
    def _open_tt_account_switcher(self, elements: list, cfg: dict,
                                  target: str, step_base: str):
        """Open the TT account-switcher bottomsheet — probe-and-pivot.

        Returns (anchor_bounds, error_code) where exactly one is non-None.

        Phase 1: probe via _tap_profile_header up to 2 times. On any
        attempt yielding the bottomsheet anchor → success. On either
        attempt yielding a Stories viewer → BACK + pivot to Phase 2.
        Both attempts yielding neither → legacy
        'tt_account_sheet_closed_before_parse'.

        Phase 2 (Task 6): tap «Меню профиля» → search drawer for a
        broad-anchor trigger → tap → verify bottomsheet via positive
        signature.

        Spec: docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md
        """
        header_y_max = cfg['profile_title_header_y_range'][1]
        anchors = ACCOUNT_LIST_ANCHORS.get('TikTok', [])

        def _emit_error(code, extra=None):
            meta = {'category': code}
            if extra:
                meta.update(extra)
            self.p.log_event('error', code, meta=meta)
            return None, code

        # --- Phase 1: probe (up to 2 attempts) ---
        probe_elements: list = []
        stories_seen = False
        for attempt in range(2):
            suffix = '' if attempt == 0 else f'_retry{attempt}'
            step = f'{step_base}_probe{suffix}'
            if not self._tap_profile_header(
                    elements, header_y_max,
                    step, fallback_coords=(540, 180)):
                return _emit_error('tt_header_tap_failed')
            time.sleep(POST_TAP_WAIT_S + 0.8)
            probe_dump = self.p.dump_ui(retries=1)
            self._save_dump(step, probe_dump)
            probe_elements = parse_ui_dump(probe_dump) if probe_dump else []

            # Sheet detection: anchor-text OR positive signature with
            # synthesised anchor_bounds (mirrors Phase 2 discriminator —
            # legacy sheets may expose ACCOUNT_LIST_ANCHORS, newer ones
            # may show only @handles / + Добавить аккаунт).
            anchor_bounds = find_anchor_bounds(probe_elements, anchors)
            sheet_open = self._has_tt_bottomsheet_signature(probe_elements)
            if sheet_open and not anchor_bounds:
                for el in probe_elements:
                    if (el.text or '').strip().startswith('@') \
                            and el.bounds[1] > 600:
                        anchor_bounds = tuple(el.bounds)
                        break
            if anchor_bounds:
                self.p.log_event(
                    'account_switch',
                    f'tt_probe_opened_bottomsheet bounds={anchor_bounds} '
                    f'attempt={attempt + 1}',
                    meta={'category': 'tt_probe_opened_bottomsheet',
                          'attempt': attempt + 1,
                          'sheet_open_signal': sheet_open},
                )
                return anchor_bounds, None
            if self._detect_tt_stories_viewer(probe_elements):
                stories_seen = True
                break
            elements = probe_elements  # feed latest screen to next probe

        if not stories_seen:
            reason = ('bottomsheet со списком аккаунтов не открылся — '
                      'вероятно, в TikTok на этом устройстве залогинен '
                      f"только один аккаунт (target {target!r} не добавлен)")
            self.p.log_event(
                'error',
                f'tt_account_sheet_closed_before_parse: {reason}',
                meta={'category': 'tt_account_sheet_closed_before_parse',
                      'reason': 'tt_account_sheet_closed_before_parse',
                      'target': target,
                      'probe_top_labels': _top_labels(probe_elements, 30)},
            )
            return None, 'tt_account_sheet_closed_before_parse'

        # --- Pivot: Stories detected → BACK to profile, then Phase 2 ---
        self.p.log_event(
            'account_switch',
            'tt_username_tap_opened_stories — reverting + menu path',
            meta={'category': 'tt_username_tap_opened_stories'},
        )
        self.p.adb_shell('input keyevent KEYCODE_BACK')
        time.sleep(POST_TAP_WAIT_S)
        # Use retries=3 to avoid the known TT dump race that produces
        # empty/stale dumps immediately after a keyevent — same retry
        # budget the surrounding profile verification uses (see
        # _switch_tiktok above).
        back_dump = self.p.dump_ui(retries=3)
        self._save_dump(f'{step_base}_back', back_dump)
        if not self._tt_is_own_profile(back_dump):
            return _emit_error(
                'tt_stories_back_failed',
                {'back_top_labels': _top_labels(
                    parse_ui_dump(back_dump) if back_dump else [], 30)})

        # --- Phase 2: menu path (implemented in Task 6) ---
        return _emit_error(
            'tt_account_menu_unknown_layout',
            {'drawer_labels': []})  # placeholder — superseded by Task 6
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v
```

Expected: all tests pass (pytest exit 0) — 3 new Phase-1 tests now green.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add account_switcher.py tests/test_tt_account_switcher_open.py
git commit -m "feat(tt-switcher): _open_tt_account_switcher Phase 1 (probe + retry + Stories pivot)

Probe up to 2 times (preserves old code's retry budget). On bottomsheet
anchor in either attempt → success (old TT layout). On Stories viewer
in either attempt → BACK + pivot. Both attempts blank → canonical
tt_account_sheet_closed_before_parse (legacy single-account semantic,
emitted by orchestrator — no callsite re-log). Phase 2 stubbed.
3 Phase-1 unit tests."
```

---

## Task 6: `_open_tt_account_switcher` — Phase 2 (menu → drawer → sheet)

**Files:**
- Modify: `account_switcher.py` (replace Phase 2 stub from Task 5)
- Test: `tests/test_tt_account_switcher_open.py`

- [ ] **Step 1: Write failing tests**

```python
def test_open_tt_account_switcher_menu_path_happy(monkeypatch):
    """Phase 2 happy: probe→Stories, BACK→profile, menu→drawer-with-anchor,
    tap→sheet (different bounds + positive signature). Returns
    (anchor_bounds, None) and 5 dumps saved with named steps."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>', '<sheet/>'],
        tap_returns=[True],  # menu tap
    )
    # parse_ui_dump call sequence on the happy path:
    #   1) probe_dump → stories markers
    #   2) menu_dump (pre-tap) → menu_els (back_dump NOT parsed — _tt_is_own_profile mocked True)
    #   3) drawer_dump → drawer_els (has clickable Управление аккаунтами)
    #   4) sheet_dump → sheet_els (positive bottomsheet signature)
    stories = [
        make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
        make_el(cd='Еще', bounds=(900, 2080, 1080, 2200)),
        make_el(text='13 ч. назад', bounds=(50, 1000, 700, 1080)),
    ]
    menu_els = [make_el(cd='Меню профиля', clickable=True,
                        bounds=(945, 112, 1058, 225))]
    drawer_anchor = make_el(text='Управление аккаунтами', clickable=True,
                            bounds=(50, 500, 1030, 560))
    drawer_els = [drawer_anchor,
                  make_el(text='Logout', clickable=True,
                          bounds=(50, 700, 1030, 760))]
    sheet_els = [
        make_el(text='Управление аккаунтами', clickable=False,
                bounds=(50, 100, 1030, 180)),
        make_el(text='@user1', bounds=(50, 800, 300, 880)),
        make_el(text='@user2', bounds=(50, 900, 300, 980)),
        make_el(text='+ Добавить аккаунт', clickable=True,
                bounds=(50, 1900, 1030, 1980)),
    ]
    import account_switcher as mod
    parse_calls = iter([stories, menu_els, drawer_els, sheet_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    # find_anchor_bounds: None for probe (Stories), then real bounds for sheet
    fab_calls = iter([None, (50, 100, 1030, 180)])
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: next(fab_calls))

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err is None
    assert anchor == (50, 100, 1030, 180)
    # Drawer trigger was tapped at its center
    assert (540, 530) in sw.p.adb_taps  # center of (50,500,1030,560)
    # BACK was issued
    assert any('KEYCODE_BACK' in c for c in sw.p.adb_shells)
    # 5 forensic dumps saved with named steps
    saved_steps = [s for s, _ in sw.p.saved_dumps]
    for step in ['tt_3_open_list_probe', 'tt_3_open_list_back',
                 'tt_3_open_list_menu', 'tt_3_open_list_drawer',
                 'tt_3_open_list_sheet']:
        assert step in saved_steps


def test_open_tt_account_switcher_unknown_layout(monkeypatch):
    """Phase 2: drawer has no broad-anchor trigger →
    (None, 'tt_account_menu_unknown_layout') with drawer_labels[]."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>'],
        tap_returns=[True],
    )
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    drawer_els = [
        make_el(text='Settings', clickable=True, bounds=(50, 100, 600, 180)),
        make_el(text='Logout', clickable=True, bounds=(50, 200, 600, 280)),
        make_el(text='Privacy', clickable=True, bounds=(50, 300, 600, 380)),
    ]
    import account_switcher as mod
    # parses: probe → stories; (back NOT parsed); menu → []; drawer → drawer_els
    parse_calls = iter([stories, [], drawer_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: None)

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err == 'tt_account_menu_unknown_layout'
    assert anchor is None
    err_events = [e for e in sw.p.events if e['kind'] == 'error']
    assert len(err_events) == 1
    assert err_events[0]['meta']['category'] == 'tt_account_menu_unknown_layout'
    assert err_events[0]['meta']['drawer_labels']  # non-empty


def test_open_tt_account_switcher_back_failed(monkeypatch):
    sw = _make_sw_with_proxy(dump_queue=['<probe/>', '<back/>'])
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    import account_switcher as mod
    parse_calls = iter([stories, []])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: None)
    sw._tt_is_own_profile = MagicMock(return_value=False)

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err == 'tt_stories_back_failed'
    assert anchor is None
    err_events = [e for e in sw.p.events if e['kind'] == 'error']
    assert len(err_events) == 1
    assert err_events[0]['meta']['category'] == 'tt_stories_back_failed'
    assert 'back_top_labels' in err_events[0]['meta']


def test_open_tt_account_switcher_menu_tap_en_locale(monkeypatch):
    """Menu pivot must accept both 'Меню профиля' and 'Profile menu'.
    On EN TikTok the cd is 'Profile menu' — must not return
    tt_profile_menu_not_found just because of locale."""
    captured_patterns = []
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>', '<sheet/>'])
    # Intercept tap_element to record what patterns were passed.
    def fake_tap_element(xml, patterns, clickable_only=True):
        captured_patterns.append(list(patterns))
        return True  # menu tap succeeds
    sw.p.tap_element = fake_tap_element

    stories = [
        make_el(cd='Close', bounds=(900, 200, 1080, 300)),
        make_el(cd='More', bounds=(900, 2080, 1080, 2200)),
    ]
    drawer_anchor = make_el(text='Manage accounts', clickable=True,
                            bounds=(50, 500, 1030, 560))
    drawer_els = [drawer_anchor]
    sheet_els = [
        make_el(text='+ Add account', clickable=True,
                bounds=(50, 1900, 1030, 1980)),
        make_el(text='@user1', bounds=(50, 800, 300, 880)),
        make_el(text='@user2', bounds=(50, 900, 300, 980)),
    ]
    import account_switcher as mod
    parse_calls = iter([stories, [], drawer_els, sheet_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    fab_calls = iter([None, (50, 1900, 1030, 1980)])
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: next(fab_calls))

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err is None
    # Menu tap patterns include both locales
    assert any('Меню профиля' in p and 'Profile menu' in p
               for p in captured_patterns), captured_patterns


def test_open_tt_account_switcher_handles_only_sheet_anchor_synthesised(
        monkeypatch):
    """If find_anchor_bounds returns None but positive sheet signature
    is True (e.g. sheet shows @handles but no ACCOUNT_LIST_ANCHORS
    label), the orchestrator must synthesise anchor_bounds from the
    first @handle — otherwise it would falsely emit
    tt_drawer_tap_did_not_open_sheet."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>', '<sheet/>'],
        tap_returns=[True],
    )
    stories = [
        make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
        make_el(cd='Еще', bounds=(900, 2080, 1080, 2200)),
    ]
    drawer_anchor = make_el(text='Управление аккаунтами', clickable=True,
                            bounds=(50, 500, 1030, 560))
    drawer_els = [drawer_anchor]
    first_handle = make_el(text='@user1', bounds=(50, 800, 300, 880))
    sheet_els = [first_handle,
                 make_el(text='@user2', bounds=(50, 900, 300, 980))]
    import account_switcher as mod
    parse_calls = iter([stories, [], drawer_els, sheet_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    # find_anchor_bounds returns None for both probe AND sheet.
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: None)

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err is None, f'expected success, got {err}'
    # anchor_bounds synthesised from first @handle
    assert tuple(anchor) == tuple(first_handle.bounds)


def test_open_tt_account_switcher_menu_dump_saved_on_failure(monkeypatch):
    """Invariant #2: menu pre-tap dump is saved BEFORE the tap, so a
    button-not-found failure still produces forensic artifact."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>'],
        tap_returns=[False],  # menu tap FAILS
    )
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    menu_els = [make_el(text='Settings', clickable=True,
                       bounds=(50, 100, 600, 180))]
    import account_switcher as mod
    # parses: probe → stories; (back NOT parsed); menu → menu_els
    parse_calls = iter([stories, menu_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: None)

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err == 'tt_profile_menu_not_found'
    saved_steps = [s for s, _ in sw.p.saved_dumps]
    assert 'tt_3_open_list_menu' in saved_steps  # saved despite tap fail
    err_events = [e for e in sw.p.events if e['kind'] == 'error']
    assert len(err_events) == 1
    assert err_events[0]['meta']['category'] == 'tt_profile_menu_not_found'
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v -k "menu_path_happy or unknown_layout or back_failed or menu_dump"
```

Expected: 4 FAIL — Phase 2 currently returns placeholder `tt_account_menu_unknown_layout` for everything.

- [ ] **Step 3: Replace Phase 2 stub with full implementation**

In `account_switcher.py`, find the `# --- Phase 2: menu path (implemented in Task 6) ---` block at the end of `_open_tt_account_switcher` and replace the `return _emit_error('tt_account_menu_unknown_layout', {'drawer_labels': []})` placeholder with the full Phase 2:

```python
        # --- Phase 2: menu path (inline tap; orchestrator owns pre-tap dump) ---
        menu_dump = self.p.dump_ui(retries=1)
        self._save_dump(f'{step_base}_menu', menu_dump)
        menu_elements = parse_ui_dump(menu_dump) if menu_dump else []
        # RU + EN aliases for the «Меню профиля» content-desc — matches the
        # locale coverage already present for Stories detection and drawer
        # triggers (TT_DRAWER_ACCOUNT_TRIGGERS).
        tapped = self.p.tap_element(
            menu_dump,
            ['Меню профиля', 'Profile menu'],
            clickable_only=True,
        )
        if not tapped:
            return _emit_error(
                'tt_profile_menu_not_found',
                {'profile_top_labels': _top_labels(menu_elements, 30)})
        self._maybe_screenshot(f'{step_base}_menu')

        time.sleep(POST_TAP_WAIT_S + 0.8)
        drawer_dump = self.p.dump_ui(retries=1)
        self._save_dump(f'{step_base}_drawer', drawer_dump)
        drawer_elements = parse_ui_dump(drawer_dump) if drawer_dump else []
        drawer_anchor = self._find_tt_account_switcher_anchor_in_drawer(
            drawer_elements)
        if drawer_anchor is None:
            return _emit_error(
                'tt_account_menu_unknown_layout',
                {'drawer_labels': _top_labels(drawer_elements, 30)})

        self.p.adb_tap(*drawer_anchor.center)
        time.sleep(POST_TAP_WAIT_S + 0.8)
        sheet_dump = self.p.dump_ui(retries=1)
        self._save_dump(f'{step_base}_sheet', sheet_dump)
        sheet_elements = parse_ui_dump(sheet_dump) if sheet_dump else []

        sheet_open = self._has_tt_bottomsheet_signature(sheet_elements)
        anchor_bounds = find_anchor_bounds(sheet_elements, anchors)
        # Discriminator (invariant #3): positive signature is sufficient.
        # When the signature confirms the sheet but find_anchor_bounds
        # returns nothing (sheet has @handles or '+ Добавить' but no
        # ACCOUNT_LIST_ANCHORS text), synthesise anchor_bounds from the
        # first @handle element so the downstream container_y_range
        # computation in _find_and_tap_account still works.
        if sheet_open and not anchor_bounds:
            for el in sheet_elements:
                if (el.text or '').strip().startswith('@') \
                        and el.bounds[1] > 600:
                    anchor_bounds = tuple(el.bounds)
                    break
        if (not anchor_bounds
                or tuple(anchor_bounds) == tuple(drawer_anchor.bounds)
                or not sheet_open):
            return _emit_error(
                'tt_drawer_tap_did_not_open_sheet',
                {'drawer_anchor_label': (drawer_anchor.label or '')[:50],
                 'sheet_open_signal': sheet_open,
                 'sheet_top_labels': _top_labels(sheet_elements, 30)})

        self.p.log_event(
            'account_switch',
            f'tt_menu_path_opened_bottomsheet bounds={anchor_bounds}',
            meta={'category': 'tt_menu_path_opened_bottomsheet'})
        return anchor_bounds, None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v
```

Expected: all tests pass (pytest exit 0) — 4 new Phase-2 tests now green.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add account_switcher.py tests/test_tt_account_switcher_open.py
git commit -m "feat(tt-switcher): _open_tt_account_switcher Phase 2 (menu path)

Menu tap inlined (orchestrator owns pre-tap dump → menu_elements
diagnostic reflects current state, not stale entry elements). Drawer
search via two-pass _find_..._anchor_in_drawer. Bottomsheet verified
via positive _has_tt_bottomsheet_signature AND anchor-bounds mismatch
with drawer trigger. Each non-success path emits exactly one
error-event with canonical meta.category. 4 Phase-2 unit tests."
```

---

## Task 7: Discriminator & canonical-event invariant tests

**Files:**
- Test only: `tests/test_tt_account_switcher_open.py`

These tests probe edge cases of the discriminator and the per-error invariant; no production code changes — they backstop the Task-6 implementation.

- [ ] **Step 1: Write tests**

```python
def test_open_tt_account_switcher_drawer_noop_identical_bounds(monkeypatch):
    """Discriminator: drawer trigger tapped but post-tap dump returns
    anchor at the SAME bounds → tt_drawer_tap_did_not_open_sheet."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>', '<sheet/>'],
        tap_returns=[True],
    )
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    drawer_anchor = make_el(text='Управление аккаунтами', clickable=True,
                            bounds=(50, 500, 1030, 560))
    drawer_els = [drawer_anchor]
    # Post-tap dump still has anchor at SAME bounds (no-op tap)
    sheet_els = [drawer_anchor]
    import account_switcher as mod
    # parses: probe → stories; (back NOT parsed); menu → []; drawer → drawer_els; sheet → sheet_els
    parse_calls = iter([stories, [], drawer_els, sheet_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    # find_anchor_bounds: None for probe (Stories), then same bounds for sheet
    fab_calls = iter([None, (50, 500, 1030, 560)])
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: next(fab_calls))

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err == 'tt_drawer_tap_did_not_open_sheet'
    err_events = [e for e in sw.p.events if e['kind'] == 'error']
    assert len(err_events) == 1
    assert err_events[0]['meta']['sheet_open_signal'] is False


def test_open_tt_account_switcher_drawer_noop_no_sheet_signature(monkeypatch):
    """Discriminator: post-tap dump has different-bounds anchor BUT no
    positive sheet signature → tt_drawer_tap_did_not_open_sheet.
    Guards against drawer relayout + legitimate broad-anchor row false-positive."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>', '<sheet/>'],
        tap_returns=[True],
    )
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    drawer_anchor = make_el(text='Управление аккаунтами', clickable=True,
                            bounds=(50, 500, 1030, 560))
    drawer_els = [drawer_anchor]
    # Post-tap dump: anchor at DIFFERENT bounds but no '+ Добавить' / no @handles
    sheet_els = [make_el(text='Управление аккаунтами', clickable=True,
                         bounds=(50, 100, 1030, 180))]
    import account_switcher as mod
    # parses: probe → stories; (back NOT parsed); menu → []; drawer → drawer_els; sheet → sheet_els
    parse_calls = iter([stories, [], drawer_els, sheet_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    # find_anchor_bounds: probe (None — Stories detected), sheet (different bounds)
    fab_calls = iter([None, (50, 100, 1030, 180)])
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: next(fab_calls))

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err == 'tt_drawer_tap_did_not_open_sheet'
    err_events = [e for e in sw.p.events if e['kind'] == 'error']
    assert len(err_events) == 1
    assert err_events[0]['meta']['sheet_open_signal'] is False


@pytest.mark.parametrize('code', [
    'tt_account_sheet_closed_before_parse',
    'tt_header_tap_failed',
    'tt_stories_back_failed',
    'tt_profile_menu_not_found',
    'tt_account_menu_unknown_layout',
    'tt_drawer_tap_did_not_open_sheet',
])
def test_open_tt_account_switcher_canonical_event_per_error_code(code, monkeypatch):
    """Invariant #1: for every non-success error_code, the orchestrator
    emits exactly ONE error-type log_event with meta.category == code."""
    # We construct each scenario minimally — common helper builds the
    # right dump queue and parse_ui_dump sequence per code.
    scenarios = {
        'tt_account_sheet_closed_before_parse': dict(
            dumps=['<x1/>', '<x2/>'],
            parses=[[], []],
            anchors=[None, None],
            tap_returns=[],
            own_profile=True,
        ),
        'tt_header_tap_failed': dict(
            # _tap_profile_header returns False — orchestrator emits immediately.
            dumps=[],
            parses=[],
            anchors=[],
            tap_returns=[],
            own_profile=True,
            header_tap_returns_false=True,
        ),
        'tt_stories_back_failed': dict(
            dumps=['<probe/>', '<back/>'],
            parses=[
                [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
                 make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))],
                [],
            ],
            anchors=[None, None],
            tap_returns=[],
            own_profile=False,
        ),
        'tt_profile_menu_not_found': dict(
            # parses: probe → stories; (back NOT parsed); menu → menu_els
            dumps=['<probe/>', '<back/>', '<menu/>'],
            parses=[
                [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
                 make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))],
                [make_el(text='Settings', clickable=True,
                         bounds=(50, 100, 600, 180))],
            ],
            anchors=[None],  # probe → None (Stories detected)
            tap_returns=[False],
            own_profile=True,
        ),
        'tt_account_menu_unknown_layout': dict(
            # parses: probe → stories; (back NOT parsed); menu → []; drawer → irrelevant
            dumps=['<probe/>', '<back/>', '<menu/>', '<drawer/>'],
            parses=[
                [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
                 make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))],
                [],
                [make_el(text='Random', clickable=True,
                         bounds=(50, 100, 600, 180))],
            ],
            anchors=[None],  # probe → None
            tap_returns=[True],
            own_profile=True,
        ),
        'tt_drawer_tap_did_not_open_sheet': dict(
            # parses: probe → stories; (back NOT parsed); menu → []; drawer → drawer_els; sheet → drawer_els (same bounds)
            dumps=['<probe/>', '<back/>', '<menu/>', '<drawer/>', '<sheet/>'],
            parses=[
                [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
                 make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))],
                [],
                [make_el(text='Управление аккаунтами', clickable=True,
                         bounds=(50, 500, 1030, 560))],
                [make_el(text='Управление аккаунтами', clickable=True,
                         bounds=(50, 500, 1030, 560))],
            ],
            anchors=[None, (50, 500, 1030, 560)],  # probe → None; sheet → same bounds
            tap_returns=[True],
            own_profile=True,
        ),
    }
    s = scenarios[code]
    sw = _make_sw_with_proxy(dump_queue=s['dumps'],
                             tap_returns=s['tap_returns'])
    sw._tt_is_own_profile = MagicMock(return_value=s['own_profile'])
    if s.get('header_tap_returns_false'):
        sw._tap_profile_header = MagicMock(return_value=False)
    import account_switcher as mod
    parse_iter = iter(s['parses'])
    anchor_iter = iter(s['anchors'])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_iter, []))
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: next(anchor_iter, None))

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err == code, f'expected {code}, got {err}'
    err_events = [e for e in sw.p.events
                  if e['kind'] == 'error'
                  and e['meta'].get('category') == code]
    assert len(err_events) == 1, (
        f'expected exactly 1 canonical event for {code}, '
        f'got {[e["meta"].get("category") for e in sw.p.events if e["kind"] == "error"]}')


def test_tap_profile_header_signature_unchanged():
    """Regression: _tap_profile_header signature must stay
    (self, elements, header_y_max, step, fallback_coords) -> bool
    so IG/YT-RO callsites in account_switcher.py do not break."""
    import inspect
    sig = inspect.signature(AccountSwitcher._tap_profile_header)
    params = list(sig.parameters.keys())
    assert params == ['self', 'elements', 'header_y_max',
                      'step', 'fallback_coords']
    # Return annotation might not be set on existing method — only assert
    # parameter shape, which is enough to catch IG/YT-RO breakage.
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v
```

Expected: all tests pass (pytest exit 0) — 2 discriminator tests + the parametrised canonical-event test (6 cases) + the signature regression test now green.

- [ ] **Step 3: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add tests/test_tt_account_switcher_open.py
git commit -m "test(tt-switcher): discriminator + canonical-event + signature regression

2 discriminator edge-case tests (identical-bounds no-op, no-signature
relayout), 5 parametrised tests for invariant #1 (exactly one
canonical error event per error_code), 1 signature regression
guarding IG/YT-RO _tap_profile_header callers."
```

---

## Task 8: Callsite refactor in `_switch_tiktok` + extend `_SWITCHER_STEP_TO_CATEGORY`

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (L2262-L2305 — TT callsite)
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_kernel.py` (extend `_SWITCHER_STEP_TO_CATEGORY` near L92)
- Test: `tests/test_tt_account_switcher_open.py`

- [ ] **Step 1: Write failing source-inspection test for callsite**

This test enforces the refactor invariant by inspecting `_switch_tiktok` source. It catches a future regression where someone re-adds an `error`-event emit between the orchestrator call and the matching `_fail`.

```python
def test_switch_tiktok_callsite_does_not_re_emit_canonical_event():
    """After Task 8 refactor, the tt_3_open_list block in _switch_tiktok
    must call _open_tt_account_switcher and then _fail directly — no
    `log_event('error', ...)` between them. The orchestrator owns
    canonical error emission (invariant #1). Source-level guard."""
    import inspect
    src = inspect.getsource(AccountSwitcher._switch_tiktok)

    # Find the orchestrator call line
    assert '_open_tt_account_switcher(' in src, \
        'refactor missing — orchestrator not called from _switch_tiktok'

    # Extract the block from the orchestrator call to the next blank-line
    # boundary (or end of function), and assert NO log_event('error', ...)
    # appears in that block.
    import re
    block_match = re.search(
        r'_open_tt_account_switcher\(.*?\n.*?(?=\n\n|\Z)',
        src, re.DOTALL)
    assert block_match is not None
    block = block_match.group(0)
    # Permit `account_switch` log_events; forbid `error`-kind log_events.
    assert "log_event('error'" not in block, (
        'tt_3_open_list callsite must not emit a second error event — '
        'the orchestrator already emitted the canonical category.\n'
        'Block:\n' + block
    )
    assert 'log_event("error"' not in block
```

And a consistency test that asserts each `_TT_ERR_TO_STEP` value resolves to its corresponding error_code via `_SWITCHER_STEP_TO_CATEGORY` (catches future drift between the two mappings):

```python
def test_tt_err_to_step_consistent_with_kernel_mapper():
    """The step name the callsite passes to _fail for each orchestrator
    err must, via _SWITCHER_STEP_TO_CATEGORY (publisher_kernel.py),
    resolve to the SAME err. Guards against drift between the callsite
    dict and the kernel mapping."""
    from publisher_kernel import _SWITCHER_STEP_TO_CATEGORY
    expected = {
        'tt_account_sheet_closed_before_parse': 'tt_3_open_list',
        'tt_header_tap_failed':                 'tt_3_open_list_probe',
        'tt_stories_back_failed':               'tt_3_open_list_back',
        'tt_profile_menu_not_found':            'tt_3_open_list_menu',
        'tt_account_menu_unknown_layout':       'tt_3_open_list_drawer',
        'tt_drawer_tap_did_not_open_sheet':     'tt_3_open_list_sheet',
    }
    for err, step in expected.items():
        assert _SWITCHER_STEP_TO_CATEGORY.get(step) == err, (
            f'step {step!r} → {_SWITCHER_STEP_TO_CATEGORY.get(step)!r}, '
            f'expected {err!r}. _TT_ERR_TO_STEP / mapper out of sync.'
        )
    # Also assert the probe-retry alias maps to header_tap_failed.
    assert (_SWITCHER_STEP_TO_CATEGORY.get('tt_3_open_list_probe_retry1')
            == 'tt_header_tap_failed')
```

And a positive end-to-end-on-resolver test that exercises the actual resolver `publisher_base._set_error_code_from_events` against synthetic `events[]`:

```python
def test_set_error_code_from_events_picks_canonical_category(monkeypatch):
    """The existing resolver _set_error_code_from_events (publisher_base)
    must pick our new error_codes from meta.category on error-type events.
    No error_codes.py registration needed — resolver accepts any string."""
    # We can't easily import _set_error_code_from_events without a full
    # publisher instance. Instead, assert the resolver source contains
    # the pattern that consumes meta.category. This is a smoke-level
    # source check; real-end-to-end via Task 9 production smoke.
    from publisher_base import PublisherBase
    import inspect
    src = inspect.getsource(PublisherBase._set_error_code_from_events)
    # Pass 1 of the resolver looks for `error`-type events and reads
    # `meta.get('reason') or meta.get('category')`. Verify this pattern.
    assert "ev.get('type') == 'error'" in src
    assert "meta.get('reason')" in src or "m.get('reason')" in src
    assert "meta.get('category')" in src or "m.get('category')" in src
```

- [ ] **Step 2: Run tests to verify they FAIL (before refactor)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v -k "callsite_does_not_re_emit or set_error_code"
```

Expected: `callsite_does_not_re_emit` FAILS — old block at L2262-L2305 still contains `log_event('error', f'tt_account_sheet_closed_before_parse: ...'`. The resolver-source test should PASS (existing code already supports `meta.category`).

- [ ] **Step 3: Refactor TT callsite**

In `account_switcher.py`, find the block starting at L2262 (`header_y_max = cfg['profile_title_header_y_range'][1]`) and ending at L2305 (`return self._fail(reason, step='tt_3_open_list')`). Replace the **entire block** with:

```python
        # [TT Pattern B 2026-05-13] Probe-and-pivot orchestrator —
        # extracted from prior 2-attempt inline retry. Orchestrator emits
        # exactly one canonical error-event per failure; callsite only
        # maps to _fail. Distinct step name per error so the publisher's
        # _resolve_publish_fail_category() Pass-2 fallback (step → category
        # via _SWITCHER_STEP_TO_CATEGORY) still yields the canonical code
        # even if the error event is lost to a logging race. Spec:
        # docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md
        anchor_bounds, err = self._open_tt_account_switcher(
            elements, cfg, target, step_base='tt_3_open_list')
        if err:
            _TT_ERR_TO_STEP = {
                'tt_account_sheet_closed_before_parse': 'tt_3_open_list',
                'tt_header_tap_failed':                 'tt_3_open_list_probe',
                'tt_stories_back_failed':               'tt_3_open_list_back',
                'tt_profile_menu_not_found':            'tt_3_open_list_menu',
                'tt_account_menu_unknown_layout':       'tt_3_open_list_drawer',
                'tt_drawer_tap_did_not_open_sheet':     'tt_3_open_list_sheet',
            }
            return self._fail(
                f'tt_3_open_list: {err}',
                step=_TT_ERR_TO_STEP.get(err, 'tt_3_open_list'))
```

Verify no orphan references — grep for the variables used by the old loop (`for attempt in range(2)`, `anchor_bounds_retry`, etc.) inside `_switch_tiktok` to make sure nothing downstream depends on the loop's local vars. The new `anchor_bounds` is in scope, which is what the downstream `_find_and_tap_account` call needs.

- [ ] **Step 4: Extend `_SWITCHER_STEP_TO_CATEGORY`**

**Spec discrepancy note:** the spec mentions `error_codes.py` as the resolver's "recognised-category set" — that file does not exist. The actual resolver is `PublisherBase._set_error_code_from_events` in `publisher_base.py:1921`, which reads `meta.reason` or `meta.category` from any `error`-type event (no registration list required). The `_SWITCHER_STEP_TO_CATEGORY` extension below is a **fallback** for the Pass-2 path that fires when no `error` event with a category is found (e.g. update_status('failed') race per the comment at publisher_base.py:1949).

In `publisher_kernel.py`, locate `_SWITCHER_STEP_TO_CATEGORY` at L76.

After L92 (`'tt_3_open_list': 'tt_account_sheet_closed_before_parse'`), add new fallback step entries:

```python
    # [TT Pattern B 2026-05-13] Probe-and-pivot fallback step→category
    # mappings. Resolver prefers meta.category set by the orchestrator;
    # these are step-based fallbacks when meta is absent.
    # Note: the bare 'tt_3_open_list' step (already at L92) maps to
    # tt_account_sheet_closed_before_parse — that handles the legacy
    # single-account-device case. The new sub-step entries below cover
    # the more specific orchestrator failure modes; they must match the
    # _TT_ERR_TO_STEP dict in account_switcher._switch_tiktok callsite.
    'tt_3_open_list_probe': 'tt_header_tap_failed',
    'tt_3_open_list_probe_retry1': 'tt_header_tap_failed',
    'tt_3_open_list_back': 'tt_stories_back_failed',
    'tt_3_open_list_menu': 'tt_profile_menu_not_found',
    'tt_3_open_list_drawer': 'tt_account_menu_unknown_layout',
    'tt_3_open_list_sheet': 'tt_drawer_tap_did_not_open_sheet',
```

These augment (not replace) `'tt_3_open_list'`.

- [ ] **Step 5: Run full test suite to verify nothing regressed**

```bash
cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/ -v --no-header 2>&1 | tail -30
```

Expected: All tests in `test_tt_account_switcher_open.py` pass + all pre-existing TT tests (`test_account_switcher_tt.py`, `test_tt_bound_based_nav.py`, `test_tt_audio_dialog.py`, `test_tt_fg_recovery.py`, `test_canonical_error_codes.py`) still pass. Acceptance: green pytest exit code.

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add account_switcher.py publisher_kernel.py tests/test_tt_account_switcher_open.py
git commit -m "refactor(tt-switcher): wire orchestrator into _switch_tiktok callsite

Old inline 2-attempt loop (L2262-L2305) replaced by single
_open_tt_account_switcher call. Callsite only maps return error_code
to _fail — no canonical event re-log (invariant #1). New error codes
registered in _SWITCHER_STEP_TO_CATEGORY as step-based fallbacks for
when meta.category is missing.

Closes 19/24h tt_account_sheet_closed_before_parse spike from new TT
profile-username tap behaviour (opens Stories/LIVE viewer).

Spec: docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md"
```

---

## Task 9: Pre-deploy verification + production smoke + soak

**Files:**
- No code changes. Verification + deploy via auto-push hook.
- Evidence: `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` (new, written after verify).

- [ ] **Step 1: Full pytest run in autowarm + check git log**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python -m pytest tests/ --tb=short 2>&1 | tail -15
```

Expected: all green. Required before continuing. If any pre-existing tests fail (e.g. `test_account_switcher_tt.py`), open `git log -p account_switcher.py | head -100` to inspect the refactor and resolve. **Do NOT proceed if any test fails.**

Verify commits are clean:
```bash
git log --oneline -10
```

Expected: 8 new commits from Tasks 1-8.

- [ ] **Step 2: Auto-push verification**

```bash
git push origin main 2>&1 | tail -5  # if not auto-pushed yet — usually post-commit hook pushes
```

Or check hook status:
```bash
ls -la .git/hooks/post-commit && cat .git/hooks/post-commit | head -10
```

If the post-commit hook is configured (per memory `reference_autowarm_git_hook`), pushes happen automatically. **NO `--force` or `--force-with-lease`** per memory `feedback_subagent_force_push_risk`.

- [ ] **Step 3: Verify PM2 picked up the new code**

```bash
pm2 describe publisher 2>&1 | grep -E "exec cwd|restart" | head -3
pm2 restart publisher
sleep 3
pm2 logs publisher --lines 30 --nostream 2>&1 | tail -15
```

Expected: `exec cwd` = `/root/.openclaw/workspace-genri/autowarm`. Per memory `feedback_pm2_dump_path_drift`, if cwd points elsewhere, fix the ecosystem config before continuing.

- [ ] **Step 4: Re-queue one failed clickpay_* task for smoke**

Per memory `reference_publish_requeue_path`, pick a recent `tt_account_sheet_closed_before_parse` failure:

```sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT pq.id AS pq_id, pq.publish_task_id, pt.account
FROM publish_queue pq
JOIN publish_tasks pt ON pt.id = pq.publish_task_id
WHERE pt.platform='TikTok'
  AND pt.error_code='tt_account_sheet_closed_before_parse'
  AND pt.created_at > NOW() - INTERVAL '6 hours'
ORDER BY pt.created_at DESC LIMIT 3;
"
```

Pick one row (say `pq_id=NNNN`), then:

```sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
UPDATE publish_queue
SET status='pending', publish_task_id=NULL
WHERE id=NNNN;
"
```

Wait up to 5 min for the dispatcher to pick it up. Then watch:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, account, status, error_code, created_at
FROM publish_tasks
WHERE platform='TikTok' AND created_at > NOW() - INTERVAL '10 minutes'
ORDER BY id DESC LIMIT 5;
"
```

- [ ] **Step 5: Inspect smoke task events for canonical event chain**

Once the smoke task completes (success OR failure both useful):

```sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tA -c "
SELECT jsonb_pretty(events) FROM publish_tasks WHERE id=<smoke_task_id>;
" | grep -E '"msg":|"category":|"step":|tt_3_open_list' | head -30
```

Expected outcomes:
- **Happy path:** events include `tt_username_tap_opened_stories` (Stories detected) + `tt_menu_path_opened_bottomsheet` + subsequent normal `_find_and_tap_account` flow → status=`done`.
- **First-iteration evidence:** if status=`failed` with `error_code='tt_account_menu_unknown_layout'`, the `meta.drawer_labels[]` is now in `events` — that's our actionable evidence for iteration #2; no manual smoke needed.

- [ ] **Step 6: Write evidence doc**

Create `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` with:
- Spec/plan refs + final commit SHAs.
- Smoke task ID + outcome (success / actionable failure).
- Pre-deploy 24h `tt_account_sheet_closed_before_parse` count vs post-deploy 4-hour preliminary count.
- 24h verify SQL (the corrected `jsonb_array_elements WITH ORDINALITY` version from spec § Testing) and a deadline timestamp 24h after PM2 restart for full soak.

- [ ] **Step 7: Commit evidence doc**

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/2026-05-13-tt-pattern-b-shipped.md
git commit -m "docs(evidence): TT Pattern B — SHIPPED 2026-05-13

Probe-and-pivot orchestrator deployed via PR <PR#>. Pre-deploy 19/24h
tt_account_sheet_closed_before_parse → post-deploy 4h <preliminary
number>. 24h soak deadline: <UTC timestamp>.

Smoke task <id>: <happy / actionable-fail>."
```

- [ ] **Step 8: Schedule 24h soak SQL run**

Set a wake-up or cron 24h after PM2 restart to run the soak SQL (spec § Testing — the `jsonb_array_elements WITH ORDINALITY` query) and update evidence doc with verdict (close / iterate).

---

## Self-Review

After writing the full plan, the author of this plan must:

1. **Spec coverage:** Walk every section of `docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md` — confirm every requirement maps to a task.
2. **Placeholder scan:** Search this plan for "TBD", "TODO", "implement later", "similar to" — fix inline.
3. **Type consistency:** Method names, parameter signatures, error-code strings, `step_base` step suffixes must match exactly across Tasks 1–9 and the spec.
4. **Frequent commit cadence:** Each task ends with a focused commit; no task batches multiple concerns into one commit.

If any drift found → fix inline, no need to re-review.
