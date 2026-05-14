# TT account-switcher — settings-nested path (Pattern B iter#2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the 13/day `tt_account_menu_unknown_layout` TikTok publish failures by teaching the account-switcher orchestrator to follow the new TikTok layout — the account switcher moved one level deeper, from the «Меню профиля» drawer into «Настройки и конфиденциальность» → «Управление аккаунтами».

**Architecture:** Pure additive change to the existing Pattern B orchestrator `_open_tt_account_switcher` in `account_switcher.py`. When the drawer search (`_find_tt_account_switcher_anchor_in_drawer`) finds no account trigger, fall through to a **single** settings hop: find a settings row in the drawer, tap it, re-dump under step `tt_3_open_list_settings`, re-run the same drawer search on the settings page. The existing tap-and-verify block (`_has_tt_bottomsheet_signature` discriminator) is reused unchanged by reassigning `drawer_anchor`. Capped at one hop — no recursion. A wrong layout assumption fails gracefully as the same `tt_account_menu_unknown_layout` code, now enriched with `settings_labels[]` for the next iteration.

**Tech Stack:** Python 3, pytest, uiautomator XML dumps. No new dependencies.

**Triage evidence:** `docs/evidence/2026-05-14-tt-publish-failures-triage.md` — 13/45 TT fails today, identical `drawer_labels[]` across 4 sampled tasks, drawer XML + screencast 5722 confirm «Настройки и конфиденциальность» is a clickable row and «Управление аккаунтами» is absent from the drawer.
**iter#2 design source:** `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` § "Iteration #2 design".
**OpenProject:** WP [#60](https://openproject.contenthunter.ru/work_packages/60).

## Known assumption (smoke-gated)

We have **not** captured a UI dump of the TikTok settings page itself — the failing tasks all stop at the drawer. The settings-page contents (label «Управление аккаунтами», single hop depth) are inferred from the iter#2 design. The existing `TT_DRAWER_ACCOUNT_TRIGGERS` list is broad (7 RU/EN variants), and the failure mode is graceful: a wrong assumption yields `tt_account_menu_unknown_layout` again with a `settings_labels[]` payload — the exact same iterate-via-evidence loop as Pattern B iter#1, no worse. Final verification is the production smoke run (Task 4), consistent with the Pattern B iter#1 known limitation.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `account_switcher.py` | TT account-switcher orchestrator + helpers | Modify: add `TT_DRAWER_SETTINGS_TRIGGERS` constant (near `TT_DRAWER_ACCOUNT_TRIGGERS`, ~line 148); add `triggers` kwarg to `_find_tt_account_switcher_anchor_in_drawer` (~line 3547); add settings-nested fallback block in `_open_tt_account_switcher` (~line 3760) |
| `tests/test_tt_account_switcher_open.py` | Unit tests for the orchestrator + helpers | Modify: 1 existing test (`test_open_tt_account_switcher_unknown_layout`); add 5 new tests |

No changes needed in `publisher_kernel.py` (`_SWITCHER_STEP_TO_CATEGORY`) or the `_switch_tiktok` callsite (`_TT_ERR_TO_STEP`): the failure path still emits the **same** error code `tt_account_menu_unknown_layout`, which already maps to step `tt_3_open_list_drawer`. The new `tt_3_open_list_settings` is only a `_save_dump` artifact step name — it is never passed to `_fail`.

---

### Task 1: Settings-trigger constant + generalize the drawer-anchor finder

**Files:**
- Modify: `account_switcher.py:140-148` (add constant), `account_switcher.py:3547-3597` (`_find_tt_account_switcher_anchor_in_drawer`)
- Test: `tests/test_tt_account_switcher_open.py` (add 3 tests after the T3 block, ~line 239)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tt_account_switcher_open.py` after `test_find_drawer_anchor_smallest_clickable_wins_over_outer_frame` (~line 239). Also add `TT_DRAWER_SETTINGS_TRIGGERS` to the import block at the top (line 14-20):

```python
def test_tt_drawer_settings_triggers_priority_order():
    # Specific two-word RU/EN strings must precede the bare fallbacks so a
    # drawer containing both «Настройки и конфиденциальность» and «Настройки»
    # matches the more specific row (the gear-icon row that opens full
    # settings), and all entries are lowercase for label.lower() matching.
    assert TT_DRAWER_SETTINGS_TRIGGERS[0] == 'настройки и конфиденциальность'
    assert (TT_DRAWER_SETTINGS_TRIGGERS.index('настройки') >
            TT_DRAWER_SETTINGS_TRIGGERS.index('настройки и конфиденциальность'))
    assert (TT_DRAWER_SETTINGS_TRIGGERS.index('settings') >
            TT_DRAWER_SETTINGS_TRIGGERS.index('settings and privacy'))
    assert all(t == t.lower() for t in TT_DRAWER_SETTINGS_TRIGGERS)


def test_find_drawer_anchor_custom_triggers_settings_clickable_direct():
    # The finder must accept a custom trigger list and match against it
    # instead of the default account triggers.
    sw = _make_switcher()
    el_match = make_el(text='Настройки и конфиденциальность', clickable=True,
                       bounds=(50, 1254, 1030, 1444))
    elements = [
        make_el(text='Баланс', clickable=True, bounds=(50, 400, 1030, 460)),
        el_match,
    ]
    out = sw._find_tt_account_switcher_anchor_in_drawer(
        elements, triggers=TT_DRAWER_SETTINGS_TRIGGERS)
    assert out is el_match


def test_find_drawer_anchor_custom_triggers_settings_text_with_parent():
    # Pass 2 with custom triggers: «Настройки и конфиденциальность» on a
    # non-clickable text child, clickable row container at overlapping
    # bounds — mirrors the real TT drawer XML (text node inside a
    # clickable row container with no own label).
    sw = _make_switcher()
    text_node = make_el(text='Настройки и конфиденциальность', clickable=False,
                        bounds=(319, 1293, 950, 1405))
    clickable_row = make_el(text='', clickable=True,
                            bounds=(201, 1254, 1041, 1444))
    elements = [text_node, clickable_row]
    out = sw._find_tt_account_switcher_anchor_in_drawer(
        elements, triggers=TT_DRAWER_SETTINGS_TRIGGERS)
    assert out is clickable_row


def test_find_drawer_anchor_default_triggers_unchanged():
    # Calling without the triggers kwarg must still use the account
    # triggers — backward-compatible default.
    sw = _make_switcher()
    el_match = make_el(text='Управление аккаунтами', clickable=True,
                       bounds=(50, 500, 1030, 560))
    settings_decoy = make_el(text='Настройки и конфиденциальность',
                             clickable=True, bounds=(50, 1254, 1030, 1444))
    out = sw._find_tt_account_switcher_anchor_in_drawer(
        [settings_decoy, el_match])
    assert out is el_match
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -k "settings_triggers or custom_triggers or default_triggers_unchanged" -v`
Expected: FAIL — `ImportError: cannot import name 'TT_DRAWER_SETTINGS_TRIGGERS'` (collection error on the whole file).

- [ ] **Step 3: Add the `TT_DRAWER_SETTINGS_TRIGGERS` constant**

In `account_switcher.py`, immediately after the `TT_DRAWER_ACCOUNT_TRIGGERS` list (after line 148, before the blank line and `def _top_labels`):

```python

# [TT Pattern B iter#2 2026-05-14] Settings-nested fallback triggers.
# Newer TikTok moved the account-switcher entry out of the «Меню профиля»
# drawer into «Настройки и конфиденциальность» → «Управление аккаунтами».
# When TT_DRAWER_ACCOUNT_TRIGGERS yields nothing in the drawer, the
# orchestrator hops one level into settings using this list. Specific
# two-word strings precede bare fallbacks (same priority discipline as
# TT_DRAWER_ACCOUNT_TRIGGERS). Lowercase — matched against label.lower().
TT_DRAWER_SETTINGS_TRIGGERS = [
    'настройки и конфиденциальность',
    'settings and privacy',
    'настройки',
    'settings',
]
```

- [ ] **Step 4: Add the `triggers` parameter to `_find_tt_account_switcher_anchor_in_drawer`**

In `account_switcher.py`, change the signature at line 3547 and the two loop headers (lines 3568, 3575) that reference `TT_DRAWER_ACCOUNT_TRIGGERS`. The new signature and docstring:

```python
    def _find_tt_account_switcher_anchor_in_drawer(self, elements: list,
                                                   triggers: list = None):
        """Find a tappable element in the «Меню профиля» drawer whose label
        matches one of `triggers` — the row that advances toward the
        account-switcher bottomsheet.

        `triggers` defaults to TT_DRAWER_ACCOUNT_TRIGGERS (the direct
        account-switcher row). The orchestrator also calls this with
        TT_DRAWER_SETTINGS_TRIGGERS to locate the «Настройки и
        конфиденциальность» row for the iter#2 settings-nested fallback,
        then again with the default triggers on the settings page.

        Two-pass algorithm:
          1. Clickable-direct: first clickable element whose label.lower()
             contains a trigger, scanning triggers in priority order.
          2. Text-with-clickable-ancestor: for each trigger, find any
             matching label element, then find the SMALLEST-area clickable
             element whose bounds contain the text's center (row-overlap
             pattern, mirrors find_yt_row_by_gmail at account_switcher.py:451).
             Smallest-area picks the closest row container over outer
             click-capture frames.

        Assumes the uiautomator XML dump order is depth-first (text
        children precede or are adjacent to their clickable parent rows).
        Holds for stock Android uiautomator dumps.

        Returns the clickable UIElement to tap, or None.
        """
        if triggers is None:
            triggers = TT_DRAWER_ACCOUNT_TRIGGERS
        # --- Pass 1: clickable-direct ---
        for trigger in triggers:
            for el in elements:
                if not el.clickable:
                    continue
                if trigger in (el.label or '').lower():
                    return el
        # --- Pass 2: text node + clickable ancestor/sibling at overlapping bounds ---
        for trigger in triggers:
            text_el = None
            for el in elements:
                if trigger in (el.label or '').lower():
                    text_el = el
                    break
            if text_el is None:
                continue
            cx, cy = text_el.center
            best = None
            best_area = None
            for el in elements:
                if not el.clickable:
                    continue
                x1, y1, x2, y2 = el.bounds
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    area = (x2 - x1) * (y2 - y1)
                    if best is None or area < best_area:
                        best = el
                        best_area = area
            if best is not None:
                return best
        return None
```

(Only three lines change versus the current body: the signature, the new `if triggers is None:` default-binding, and the two `for trigger in TT_DRAWER_ACCOUNT_TRIGGERS:` → `for trigger in triggers:`. The two-pass logic is otherwise identical — reproduced in full here because the engineer may read tasks out of order.)

- [ ] **Step 5: Add `TT_DRAWER_SETTINGS_TRIGGERS` to the test import block**

In `tests/test_tt_account_switcher_open.py`, line 14-20, add the name to the existing `from account_switcher import (...)` block:

```python
from account_switcher import (
    AccountSwitcher,
    SwitchResult,       # noqa: F401 — used in Task 8 callsite test
    TT_DRAWER_ACCOUNT_TRIGGERS,
    TT_DRAWER_SETTINGS_TRIGGERS,
    UIElement,
    _top_labels,
)
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -k "settings_triggers or custom_triggers or default_triggers_unchanged" -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full T3 block to verify no regression**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -k "find_drawer_anchor" -v`
Expected: PASS (all `test_find_drawer_anchor_*` tests — the 6 pre-existing + the 3 new).

- [ ] **Step 8: Commit**

```bash
git add account_switcher.py tests/test_tt_account_switcher_open.py
git commit -m "feat(tt-switcher): TT_DRAWER_SETTINGS_TRIGGERS + triggers param on drawer anchor finder"
```

---

### Task 2: Settings-nested fallback in the orchestrator

**Files:**
- Modify: `account_switcher.py:3758-3763` (the `drawer_anchor is None` branch inside `_open_tt_account_switcher`)
- Test: `tests/test_tt_account_switcher_open.py` — modify `test_open_tt_account_switcher_unknown_layout` (~line 530), add 3 new orchestrator tests after it

- [ ] **Step 1: Write the failing tests**

First, **modify** `test_open_tt_account_switcher_unknown_layout` (~line 530). Its current `drawer_els` uses `text='Settings'`, which will now match `TT_DRAWER_SETTINGS_TRIGGERS` and trigger the settings hop, breaking the test's intent and exhausting its `parse_calls` iterator. Replace its `drawer_els` with neutral labels and assert no settings hop happened:

```python
def test_open_tt_account_switcher_unknown_layout(monkeypatch):
    """Phase 2: drawer has neither an account trigger NOR a settings
    trigger → (None, 'tt_account_menu_unknown_layout') with drawer_labels[]
    and NO settings_labels (the iter#2 hop must not fire)."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>'],
        tap_returns=[True],
    )
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    drawer_els = [
        make_el(text='Баланс', clickable=True, bounds=(50, 100, 600, 180)),
        make_el(text='Logout', clickable=True, bounds=(50, 200, 600, 280)),
        make_el(text='Ваш QR-код', clickable=True, bounds=(50, 300, 600, 380)),
    ]
    import account_switcher as mod
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
    assert err_events[0]['meta']['drawer_labels']
    # iter#2: no settings trigger in the drawer → no hop, no settings_labels
    assert 'settings_labels' not in err_events[0]['meta']
    saved_steps = [s for s, _ in sw.p.saved_dumps]
    assert 'tt_3_open_list_settings' not in saved_steps
```

Then **add** three new tests after it:

```python
def test_open_tt_account_switcher_settings_nested_happy(monkeypatch):
    """iter#2 happy: drawer has no account trigger but has a settings
    row → tap settings → settings page exposes «Управление аккаунтами»
    → tap → sheet with positive signature. Returns (anchor_bounds, None);
    the settings dump is saved under tt_3_open_list_settings."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>',
                    '<settings/>', '<sheet/>'],
        tap_returns=[True],  # menu tap
    )
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    # Drawer: no account trigger, but a clickable settings row.
    settings_row = make_el(text='Настройки и конфиденциальность',
                           clickable=True, bounds=(201, 1254, 1041, 1444))
    drawer_els = [make_el(text='Баланс', clickable=True,
                          bounds=(50, 400, 1030, 460)),
                  settings_row]
    # Settings page: the account-switcher entry.
    account_row = make_el(text='Управление аккаунтами', clickable=True,
                          bounds=(50, 600, 1030, 680))
    settings_els = [make_el(text='Конфиденциальность', clickable=True,
                            bounds=(50, 500, 1030, 560)),
                    account_row]
    sheet_els = [
        make_el(text='@user1', bounds=(50, 800, 300, 880)),
        make_el(text='@user2', bounds=(50, 900, 300, 980)),
        make_el(text='+ Добавить аккаунт', clickable=True,
                bounds=(50, 1900, 1030, 1980)),
    ]
    import account_switcher as mod
    parse_calls = iter([stories, [], drawer_els, settings_els, sheet_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    fab_calls = iter([None, (50, 800, 300, 880)])
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: next(fab_calls))

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err is None, f'expected success, got {err}'
    assert tuple(anchor) == (50, 800, 300, 880)
    # settings row was tapped (center of (201,1254,1041,1444) = (621, 1349))
    assert (621, 1349) in sw.p.adb_taps
    # account row on the settings page was tapped (center = (540, 640))
    assert (540, 640) in sw.p.adb_taps
    saved_steps = [s for s, _ in sw.p.saved_dumps]
    assert 'tt_3_open_list_settings' in saved_steps


def test_open_tt_account_switcher_settings_nested_still_unknown(monkeypatch):
    """iter#2: drawer has a settings row, but the settings page still
    exposes no account trigger → (None, 'tt_account_menu_unknown_layout')
    with BOTH drawer_labels[] and settings_labels[] for the next
    iteration. One hop only — no recursion."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>',
                    '<settings/>'],
        tap_returns=[True],
    )
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    settings_row = make_el(text='Настройки и конфиденциальность',
                           clickable=True, bounds=(201, 1254, 1041, 1444))
    drawer_els = [settings_row]
    # Settings page: still nothing account-related.
    settings_els = [make_el(text='Уведомления', clickable=True,
                            bounds=(50, 500, 1030, 560)),
                    make_el(text='Конфиденциальность', clickable=True,
                            bounds=(50, 600, 1030, 680))]
    import account_switcher as mod
    parse_calls = iter([stories, [], drawer_els, settings_els])
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
    meta = err_events[0]['meta']
    assert meta['category'] == 'tt_account_menu_unknown_layout'
    assert meta['drawer_labels']
    assert meta['settings_labels']  # enriched for iter#3
    assert 'Уведомления' in meta['settings_labels']
    saved_steps = [s for s, _ in sw.p.saved_dumps]
    assert 'tt_3_open_list_settings' in saved_steps


def test_open_tt_account_switcher_settings_nested_one_hop_only(monkeypatch):
    """iter#2 recursion cap: even when the settings page itself contains
    another settings row, the orchestrator must NOT hop a second time —
    it does a single re-search and stops. Exactly one settings dump."""
    sw = _make_sw_with_proxy(
        dump_queue=['<probe/>', '<back/>', '<menu/>', '<drawer/>',
                    '<settings/>'],
        tap_returns=[True],
    )
    stories = [make_el(cd='Закрыть', bounds=(900, 200, 1080, 300)),
               make_el(cd='Еще', bounds=(900, 2080, 1080, 2200))]
    settings_row = make_el(text='Настройки и конфиденциальность',
                           clickable=True, bounds=(201, 1254, 1041, 1444))
    drawer_els = [settings_row]
    # Settings page contains ANOTHER settings row but no account trigger.
    settings_els = [make_el(text='Настройки', clickable=True,
                            bounds=(50, 500, 1030, 560))]
    import account_switcher as mod
    parse_calls = iter([stories, [], drawer_els, settings_els])
    monkeypatch.setattr(mod, 'parse_ui_dump',
                        lambda xml: next(parse_calls))
    monkeypatch.setattr(mod, 'find_anchor_bounds',
                        lambda els, anchors: None)

    anchor, err = sw._open_tt_account_switcher(
        elements=[], cfg=_TT_CFG, target='someone',
        step_base='tt_3_open_list')

    assert err == 'tt_account_menu_unknown_layout'
    settings_dumps = [s for s, _ in sw.p.saved_dumps
                      if s == 'tt_3_open_list_settings']
    assert len(settings_dumps) == 1, (
        f'expected exactly one settings hop, got {len(settings_dumps)}')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -k "settings_nested or unknown_layout" -v`
Expected: FAIL — `test_open_tt_account_switcher_unknown_layout` fails its new `'settings_labels' not in ...` / `'tt_3_open_list_settings' not in ...` assertions are actually satisfied by old code, but the 3 new `settings_nested` tests fail: the happy path returns `err == 'tt_account_menu_unknown_layout'` instead of `None` (no fallback exists yet), and `still_unknown` / `one_hop_only` fail on the missing `tt_3_open_list_settings` dump. (If `parse_ui_dump`'s iterator over-runs in a test, that is also an expected pre-fix failure.)

- [ ] **Step 3: Implement the settings-nested fallback**

In `account_switcher.py`, replace the current block at lines 3758-3763:

```python
        drawer_anchor = self._find_tt_account_switcher_anchor_in_drawer(
            drawer_elements)
        if drawer_anchor is None:
            return _emit_error(
                'tt_account_menu_unknown_layout',
                {'drawer_labels': _top_labels(drawer_elements, 30)})
```

with:

```python
        drawer_anchor = self._find_tt_account_switcher_anchor_in_drawer(
            drawer_elements)

        # [TT Pattern B iter#2 2026-05-14] Settings-nested fallback. Newer
        # TikTok moved the account-switcher entry out of the «Меню профиля»
        # drawer into «Настройки и конфиденциальность» → «Управление
        # аккаунтами». If the drawer exposes no direct account trigger but
        # does have a settings row, hop ONE level into settings and
        # re-search with the same account triggers. Capped at one hop — no
        # recursion. A wrong layout assumption falls through to the same
        # tt_account_menu_unknown_layout below, enriched with
        # settings_labels[] for the next iteration.
        # Triage: docs/evidence/2026-05-14-tt-publish-failures-triage.md
        settings_labels = None
        if drawer_anchor is None:
            settings_trigger = self._find_tt_account_switcher_anchor_in_drawer(
                drawer_elements, triggers=TT_DRAWER_SETTINGS_TRIGGERS)
            if settings_trigger is not None:
                self.p.adb_tap(*settings_trigger.center)
                time.sleep(POST_TAP_WAIT_S + 0.8)
                settings_dump = self.p.dump_ui(retries=1)
                self._save_dump(f'{step_base}_settings', settings_dump)
                self._maybe_screenshot(f'{step_base}_settings')
                settings_elements = (
                    parse_ui_dump(settings_dump) if settings_dump else [])
                settings_labels = _top_labels(settings_elements, 30)
                drawer_anchor = (
                    self._find_tt_account_switcher_anchor_in_drawer(
                        settings_elements))

        if drawer_anchor is None:
            extra = {'drawer_labels': _top_labels(drawer_elements, 30)}
            if settings_labels is not None:
                extra['settings_labels'] = settings_labels
            return _emit_error('tt_account_menu_unknown_layout', extra)
```

The existing tap-and-verify block immediately below (`self.p.adb_tap(*drawer_anchor.center)` … `_has_tt_bottomsheet_signature` discriminator) is reused unchanged: `drawer_anchor` now holds either the direct drawer anchor or the settings-page account anchor.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -k "settings_nested or unknown_layout" -v`
Expected: PASS (4 tests: 1 modified + 3 new).

- [ ] **Step 5: Run the full orchestrator + canonical-event suite**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v`
Expected: PASS (all tests — the pre-existing ~40 + 8 new/modified). In particular `test_open_tt_account_switcher_canonical_event_per_error_code[tt_account_menu_unknown_layout]` still passes (its scenario drawer uses `text='Random'` — no settings trigger — so the hop does not fire and the dump queue is not over-run).

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_tt_account_switcher_open.py
git commit -m "feat(tt-switcher): settings-nested fallback for tt_account_menu_unknown_layout (Pattern B iter#2)"
```

---

### Task 3: Full regression sweep + lint

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full TT switcher test file**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -v`
Expected: PASS, 0 failures.

- [ ] **Step 2: Run the broader account_switcher / publisher test suite**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/ -k "switcher or tiktok or tt_ or publisher_kernel" -q`
Expected: PASS for all switcher/TT tests. Pre-existing unrelated DB-mock baseline failures (noted in `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` as "14 baseline failures elsewhere unchanged") are acceptable **only if** the identical set fails on `origin/main` — confirm by stashing or comparing against a clean checkout if any non-switcher failure appears.

- [ ] **Step 3: Lint the changed file**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pyflakes account_switcher.py tests/test_tt_account_switcher_open.py`
Expected: no new warnings (pre-existing `# noqa` lines excepted).

- [ ] **Step 4: Verify no kernel-mapper drift**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_tt_account_switcher_open.py -k "tt_err_to_step_consistent or canonical_event" -v`
Expected: PASS — confirms the unchanged `tt_account_menu_unknown_layout` → `tt_3_open_list_drawer` mapping still resolves correctly and no new step name leaked into `_fail`.

---

### Task 4: Production smoke (verification gate)

**Files:** none — live verification. Run after the PR is merged and the PM2 `autowarm` service is restarted on the prod checkout.

- [ ] **Step 1: Re-queue one affected task via `publish_queue`**

Pick an account from the 13 affected (e.g. `clickpay_go`, task 5732). Per memory `reference_publish_requeue_path`: `UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE ...` — do NOT touch `publish_tasks`. `dispatchPublishQueue` (5-min cron) creates a fresh `publish_task`.

- [ ] **Step 2: Watch the new task's events**

Query the new `publish_task` row. Expected on the new layout: `account_switch` events showing `tt_3_open_list_settings` dump saved, the settings hop, then either `tt_menu_path_opened_bottomsheet` (success) or — if the settings page assumption is wrong — `tt_account_menu_unknown_layout` with a populated `settings_labels[]` payload (→ iter#3 from that evidence).

- [ ] **Step 3: 24h soak SQL**

Re-run the soak query from `docs/evidence/2026-05-13-tt-pattern-b-shipped.md`. Acceptance: `tt_account_menu_unknown_layout` falls from 13/24h toward 0; no new error code spikes.

- [ ] **Step 4: Write the evidence doc + update OpenProject WP #60**

Create `docs/evidence/2026-05-14-tt-account-switcher-settings-nested-shipped.md`; update WP #60 with the house comment style (Что было не так → Что сделано → Что осталось) and move status as appropriate.

---

## Self-Review

**1. Spec coverage** — the iter#2 design (`docs/evidence/2026-05-13-tt-pattern-b-shipped.md` § "Iteration #2 task") requires: (a) fallback when `_find_tt_account_switcher_anchor_in_drawer` returns None → Task 2 Step 3; (b) second lookup against settings trigger strings → Task 1 (constant) + Task 2 (call); (c) tap → re-dump → re-run finder → Task 2 Step 3; (d) cap nesting at 1 level → single non-looping block, guarded by `test_open_tt_account_switcher_settings_nested_one_hop_only`. All covered.

**2. Placeholder scan** — no TBD/TODO; every code step shows complete code; every command shows expected output.

**3. Type consistency** — `TT_DRAWER_SETTINGS_TRIGGERS` (list[str]) defined Task 1 Step 3, imported Task 1 Step 5, used Task 2 Step 3. `_find_tt_account_switcher_anchor_in_drawer(elements, triggers=None)` — new kwarg defined Task 1 Step 4, called with `triggers=TT_DRAWER_SETTINGS_TRIGGERS` and with default in Task 2 Step 3. `settings_labels` local: `None` sentinel vs populated list — consistent across the assignment and the `is not None` guard. Dump step name `tt_3_open_list_settings` consistent between Task 2 Step 3 (`_save_dump`) and the Task 2 test assertions. `_emit_error(code, extra)` signature matches existing usage at `account_switcher.py:3653`.

**4. Backward compatibility** — `_find_tt_account_switcher_anchor_in_drawer` gains an optional kwarg with a default; the orchestrator's existing positional call at line 3758 and all 6 pre-existing T3 tests stay valid. Only `test_open_tt_account_switcher_unknown_layout` needed editing — it used `text='Settings'`, which now matches the new settings trigger; flagged and fixed in Task 2 Step 1.
