# TT Pattern B — profile-header tap pivots to "Меню профиля" path

**Date:** 2026-05-13
**Author:** Claude (Opus 4.7)
**Status:** Draft — design brief
**Plan:** _to be written via writing-plans after spec approval_
**Memory refs:** [[project_tt_publish_phases_shipped]], [[project_tt_switcher_bool_return_fixed]], [[project_error_code_mapper_fail_event_fix]], [[reference_publish_requeue_path]], [[feedback_user_diagnosis_is_signal]]

## Problem

On 2026-05-13, TikTok publishes started failing at the account-switcher step with `error_code = tt_account_sheet_closed_before_parse`. 19 fails / 24h; **single-day spike** (1→4→5→5→2→1→19 over 2026-05-05 .. 2026-05-13). Distribution: 13/19 on Pi 9 (Samsung A17 RFGYC31P*), 2/19 Pi 7, rest singletons. Sample tasks: 5331, 5332, 5334, 5335, 5338.

### Evidence (task 5338, account `clickpay_under`)

Dump `tt_2_profile_screen` (52KB) — TT profile screen has a **clickable Button** with `text='clickpay_under'` at `y=[503,565]`, resource-id suffix `r4r`. `_looks_like_username('clickpay_under')` returns True → existing `_tap_profile_header` loop matches it and taps `el.center = (540, 534)`.

Dump immediately after the tap (`tt_3_open_list`, 33KB) — content reduced to **only**:
- `content-desc='Закрыть'` at `y=[181,293]` (top-right close X)
- `content-desc='Еще'` at `y=[2065,2188]` (bottom more-button)
- `content-desc='activebadgeis_active'` at `y=[241,281]`
- `text='clickpay_under'` + `text='· 13 ч. назад'` + `text='0 зрителей'`

This is a **TikTok Stories / LIVE viewer**, not the account-switcher bottomsheet. `find_anchor_bounds` for `ACCOUNT_LIST_ANCHORS['TikTok']` (`'Управление аккаунтами'`, etc.) finds nothing → `anchor_missing` → 2 retries fail the same way → `_fail` with `tt_account_sheet_closed_before_parse`.

The BACKLOG entry hypothesised "tap landed on fallback `(540, 180)` on a video card". XML evidence refutes this — the tap lands on a **legitimate username Button** whose behaviour TT has changed in a recent release. Per [[feedback_user_diagnosis_is_signal]], the user-facing diagnostic is a signal, not ground truth; investigation must verify the symptom and the named component independently.

### Cross-account layout stability

Four `tt_2_profile_screen` dumps (5338 / 5331 / 5207 / 5158) compared:

| task | account | "Меню профиля" bounds | center |
|---|---|---|---|
| 5338 | clickpay_under | [945,112][1058,225] | (1001, 168) |
| 5331 | just_clickpay | [945,112][1058,225] | (1001, 168) |
| 5207 | luni_link | [922,112][1035,225] | (978, 168) |
| 5158 | feminista.beauty | [945,112][1058,225] | (1001, 168) |

`content-desc="Меню профиля"` is stable across all four; bounds vary by ~23px on one sample (selector MUST be cd-based, not coord-based).

### Why no live-device verification

No successful TT publish in the last 7 days has touched a "Меню профиля" drawer (zero events containing the literal). We have **no archived dumps** of the drawer content. The spec therefore designs the menu-path **with defensive diagnostics** so the first real failure under the new code gives us actionable evidence for the next iteration — rather than blocking on manual live-device exploration.

## Goals

1. Close the 19/24h `tt_account_sheet_closed_before_parse` spike caused by the TT username-tap behaviour change.
2. **Do not regress** TT phones on older versions where username-tap still opens the bottomsheet directly.
3. Produce structured forensic evidence (`drawer_labels[]`) on the first failure of the new path, so iteration #2 can be data-driven instead of guess-driven.

## Non-goals

- IG/YT switcher behaviour. `_tap_profile_header` is shared but its signature and behaviour are preserved.
- The legacy semantic `tt_account_sheet_closed_before_parse = "single-account device, target not added"` (still a legitimate failure when there is genuinely only one TT account on the device — kept as-is for callsite mapping).
- Pi 7 / Pi 5 singletons in this batch (2/19 + 4 singletons). They are subsumed by the same fix; no per-device path.
- Vision-based fallback. Out of scope for this iteration.

## Approach

**Probe-and-pivot with diagnostic logging.**

1. Extract a new method `_open_tt_account_switcher(elements, cfg, target, step_base) -> tuple[anchor_bounds | None, error_code | None]` from the inline `tt_3_open_list` retry loop in `_switch_tiktok` (`account_switcher.py:2262-2305`).
2. Inside the new method:
   - **Phase 1 (probe).** Call the existing `_tap_profile_header(elements, header_y_max, '<step>_probe', fallback_coords=(540, 180))`. Dump. If `find_anchor_bounds(ACCOUNT_LIST_ANCHORS['TikTok'])` finds the sheet → success (old happy path, no behaviour change).
   - If sheet absent **and** `_detect_tt_stories_viewer(probe_elements)` is True → `adb keyevent KEYCODE_BACK` → re-dump → assert back on own profile.
   - If sheet absent **and** Stories not detected → return `tt_probe_unknown_post_state` (mapped at callsite to legacy `tt_account_sheet_closed_before_parse`).
3. **Phase 2 (menu).** Tap element with `content-desc="Меню профиля"` → dump drawer → search for a broad-anchor trigger (`'Управление аккаунтами'`, `'Manage accounts'`, `'Switch account'`, `'Сменить аккаунт'`, `'Переключить аккаунт'`, `'Аккаунты'`, `'Accounts'`). Tap the first match → dump → expect `find_anchor_bounds` to succeed (bottomsheet open) → continue with normal `_find_and_tap_account` flow.
4. **Failure mode:** if drawer search returns nothing → fail-fast with `tt_account_menu_unknown_layout` and embed `drawer_labels[]` (top 30 unique `el.label[:40]`) in `meta`, plus the S3 dump URL — so the first real fail yields a precise post-mortem.

`_tap_profile_header` itself is **not modified**. The cfg key `profile_title_header_y_range[1]=700` for TikTok is unchanged.

### Alternatives rejected

- **Always-menu path (no probe).** Faster on the new layout but risks regressing phones still on the old TT version where username-tap works. Sample size for "older layout still in production" is unknown; probe is cheap insurance.
- **Single hard-coded anchor `'Управление аккаунтами'`** (no broad list). Smaller test surface but fragile against language packs / variant strings. The broad list with priority ordering only adds 6 short strings.
- **Feature-flag rollout per device serial.** Bureaucratic; the probe-pivot pattern already gives same-effect safety (old phones never hit the menu path).

## Components

All in `account_switcher.py` (single file), private methods of `AccountSwitcher`.

### `_detect_tt_stories_viewer(elements: list) -> bool`

Pure function (testable on synthetic XML-derived element lists). Returns True if **≥2 of 3** markers present (case-insensitive comparison; RU and EN locale markers both supported):

- `content-desc in {'Закрыть', 'Close'}` where `y_top < 300`.
- `content-desc in {'Еще', 'Ещё', 'More'}` where `y_top > 1900`.
- Any element `text` matches regex `r'(\d+\s*ч\.?\s*назад|\d+\s*мин\.?\s*назад|\d+\s*hours?\s*ago|\d+\s*minutes?\s*ago|\d+\s*зрителей|\d+\s*viewers?)'`.

The trigger sets here are extensible — if a third TT locale appears in production, add markers without touching the orchestrator logic.

### Menu tap (inline in orchestrator — no separate helper)

The orchestrator owns the pre-tap dump itself, then calls `self.p.tap_element` directly. This ensures the forensic dump and `profile_top_labels` diagnostic both reflect the **post-BACK / pre-menu** state (not stale `elements` from before the probe). See orchestrator pseudocode below.

### `_find_tt_account_switcher_anchor_in_drawer(elements: list) -> Optional[UIElement]`

Module-level constant:
```python
TT_DRAWER_ACCOUNT_TRIGGERS = [
    'управление аккаунтами',
    'manage accounts',
    'switch account',
    'сменить аккаунт',
    'переключить аккаунт',
    'аккаунты',
    'accounts',
]
```

Algorithm — two-pass to handle the common Android pattern where text lives on a non-clickable child while the clickable handler sits on the parent row:

1. **Pass 1 (clickable-direct).** For each trigger in priority order: return the first element with `clickable=True` whose `label.lower()` contains the trigger.
2. **Pass 2 (text-with-clickable-ancestor-or-sibling).** If pass 1 returned None: for each trigger in priority order, find a (possibly non-clickable) element matching the label. Look for a clickable element whose `bounds` **contain or overlap** the text element's center (use the same row-bounding logic as `find_yt_row_by_gmail` in `account_switcher.py:415-441`). If found, return that clickable element. Else continue.
3. Return None if no trigger produces a tappable target after both passes.

The two-pass design avoids missing legitimate matches when TT wraps the drawer entry text in a non-clickable `TextView` inside a clickable row container.

### `_open_tt_account_switcher(elements, cfg, target, step_base) -> tuple[Optional[tuple], Optional[str]]`

Orchestrator. Returns `(anchor_bounds, error_code)` where exactly one is non-None.

Pseudocode (see Section "Data Flow" in conversation transcript for full control flow):

**Invariants enforced by the orchestrator:**

1. **Every non-success return path emits exactly one `error`-type `log_event` whose `meta.category` equals the returned `error_code`.** This is what the canonical-error-code mapper reads (see [[project_error_code_mapper_fail_event_fix]]). The callsite does **not** re-log a category; it only calls `_fail`. The plan MUST also add every new code (`tt_header_tap_failed`, `tt_stories_back_failed`, `tt_profile_menu_not_found`, `tt_account_menu_unknown_layout`, `tt_drawer_tap_did_not_open_sheet`) to the resolver's recognised-category set in `error_codes.py` so the mapper picks them up from `events[].meta.category` instead of falling back to `_SWITCHER_STEP_TO_CATEGORY`.
2. **Every `dump_ui(retries=1)` is paired with `self._save_dump(step, dump_xml)` under a stable step name** (`<step_base>_probe`, `<step_base>_probe_retry`, `<step_base>_back`, `<step_base>_menu`, `<step_base>_drawer`, `<step_base>_sheet`). These step names are the test-contract artifacts referenced by unit tests below and by post-mortem S3 URLs.
3. **Sheet-vs-drawer discriminator after the drawer tap.** Detect the bottomsheet using a **positive** signal (add-account row OR multiple `@`-prefixed handle rows) in addition to anchor-bounds checks. The discriminator MUST satisfy **all** of:
   - `find_anchor_bounds(sheet_elements, ACCOUNT_LIST_ANCHORS['TikTok'])` returns a non-empty match with `bounds != drawer_anchor.bounds`, AND
   - **Positive sheet signal** — `_has_tt_bottomsheet_signature(sheet_elements)` returns True: either ≥1 element whose text/label matches regex `r'^\+\s*(Добавить|Add)\s+(аккаунт|account)'` (case-insensitive — note grouping with the second `(аккаунт|account)` is required; without grouping, `|` precedence would match a bare `account` substring anywhere), OR ≥2 elements with text starting `@` whose `y_top > 600` (account-row signature).
   - If any condition fails → return `tt_drawer_tap_did_not_open_sheet`.

   This positive signal is robust to bottomsheet layouts that legitimately include a clickable `'Управление аккаунтами'` row or footer — the failure mode flagged by codex review round 3. If the positive signal is present, the sheet is open regardless of what else the dump contains.
4. **Probe retry.** Old code did 2 attempts of `_tap_profile_header + dump + find_anchor_bounds`. Preserve that retry budget by attempting the probe **up to 2 times** before pivoting to the menu path. The retry helps the old TT layout where a single tap occasionally fails to open the bottomsheet (transient UI state). Pivot to menu path only triggers when **either** attempt produces a Stories viewer (definitive signal of the new layout).
5. **Terminal `_fail` event semantics.** `_fail(...)` appends a `failed`-type event WITHOUT `meta.category`. The canonical error-code resolver MUST scan `events[]` backwards for the most recent `error`-type event with `meta.category` set (NOT just `events->-1`). The soak SQL in this spec (Testing section) therefore reads `events->-1` only for breakdown by category — for correctness, it relies on the orchestrator's error event being the last `error` event before `_fail`'s terminal `failed`-event.

```python
def _open_tt_account_switcher(self, elements, cfg, target, step_base):
    header_y_max = cfg['profile_title_header_y_range'][1]
    anchors = ACCOUNT_LIST_ANCHORS.get('TikTok', [])

    def _emit_error(code, extra=None):
        meta = {'category': code}
        if extra:
            meta.update(extra)
        self.p.log_event('error', code, meta=meta)
        return None, code

    # --- Phase 1: probe (up to 2 attempts, invariant #4) ---
    probe_elements = []
    stories_seen = False
    for attempt in range(2):
        suffix = '' if attempt == 0 else f'_retry{attempt}'
        step = f'{step_base}_probe{suffix}'
        if not self._tap_profile_header(elements, header_y_max,
                                        step, fallback_coords=(540, 180)):
            return _emit_error('tt_header_tap_failed')
        time.sleep(POST_TAP_WAIT_S + 0.8)
        probe_dump = self.p.dump_ui(retries=1)
        self._save_dump(step, probe_dump)
        probe_elements = parse_ui_dump(probe_dump) if probe_dump else []

        anchor_bounds = find_anchor_bounds(probe_elements, anchors)
        if anchor_bounds:
            self.p.log_event('account_switch',
                f'tt_probe_opened_bottomsheet bounds={anchor_bounds} attempt={attempt+1}',
                meta={'category': 'tt_probe_opened_bottomsheet',
                      'attempt': attempt + 1})
            return anchor_bounds, None
        if self._detect_tt_stories_viewer(probe_elements):
            stories_seen = True
            break
        # Otherwise: transient state — try once more before pivoting.
        elements = probe_elements  # feed latest screen for next probe

    if not stories_seen:
        # Legacy semantic: target not added to this single-account TT
        # device. Emit the canonical legacy code DIRECTLY from the
        # orchestrator — keeps invariant #1 strict, no callsite re-log.
        reason = ('bottomsheet со списком аккаунтов не открылся — '
                  'вероятно, в TikTok на этом устройстве залогинен '
                  f"только один аккаунт (target {target!r} не добавлен)")
        self.p.log_event(
            'error',
            f'tt_account_sheet_closed_before_parse: {reason}',
            meta={'category': 'tt_account_sheet_closed_before_parse',
                  'reason': 'tt_account_sheet_closed_before_parse',
                  'target': target,
                  'probe_top_labels': _top_labels(probe_elements, 30)})
        return None, 'tt_account_sheet_closed_before_parse'

    # --- Pivot: Stories detected → BACK then menu ---
    self.p.log_event('account_switch',
        'tt_username_tap_opened_stories — reverting + menu path',
        meta={'category': 'tt_username_tap_opened_stories'})
    self.p.adb_shell('input keyevent KEYCODE_BACK')
    time.sleep(POST_TAP_WAIT_S)
    back_dump = self.p.dump_ui(retries=1)
    self._save_dump(f'{step_base}_back', back_dump)
    if not self._is_tt_own_profile(back_dump):
        return _emit_error('tt_stories_back_failed',
                           {'back_top_labels': _top_labels(
                               parse_ui_dump(back_dump) if back_dump else [], 30)})

    # --- Phase 2: menu (inline — orchestrator owns pre-tap dump) ---
    menu_dump = self.p.dump_ui()
    self._save_dump(f'{step_base}_menu', menu_dump)
    menu_elements = parse_ui_dump(menu_dump) if menu_dump else []
    tapped = self.p.tap_element(menu_dump, ['Меню профиля'], clickable_only=True)
    if not tapped:
        return _emit_error('tt_profile_menu_not_found',
                           {'profile_top_labels': _top_labels(menu_elements, 30)})
    self._maybe_screenshot(f'{step_base}_menu')

    time.sleep(POST_TAP_WAIT_S + 0.8)
    drawer_dump = self.p.dump_ui(retries=1)
    self._save_dump(f'{step_base}_drawer', drawer_dump)
    drawer_elements = parse_ui_dump(drawer_dump) if drawer_dump else []
    drawer_anchor = self._find_tt_account_switcher_anchor_in_drawer(drawer_elements)
    if drawer_anchor is None:
        return _emit_error('tt_account_menu_unknown_layout',
                           {'drawer_labels': _top_labels(drawer_elements, 30)})

    self.p.adb_tap(*drawer_anchor.center)
    time.sleep(POST_TAP_WAIT_S + 0.8)
    sheet_dump = self.p.dump_ui(retries=1)
    self._save_dump(f'{step_base}_sheet', sheet_dump)
    sheet_elements = parse_ui_dump(sheet_dump) if sheet_dump else []

    # Discriminator (invariant #3): positive sheet signal + anchor-bounds check.
    anchor_bounds = find_anchor_bounds(sheet_elements, anchors)
    sheet_open = self._has_tt_bottomsheet_signature(sheet_elements)
    if (not anchor_bounds
            or tuple(anchor_bounds) == tuple(drawer_anchor.bounds)
            or not sheet_open):
        return _emit_error('tt_drawer_tap_did_not_open_sheet',
                           {'drawer_anchor_label': drawer_anchor.label[:50],
                            'sheet_open_signal': sheet_open,
                            'sheet_top_labels': _top_labels(sheet_elements, 30)})

    self.p.log_event('account_switch',
        f'tt_menu_path_opened_bottomsheet bounds={anchor_bounds}',
        meta={'category': 'tt_menu_path_opened_bottomsheet'})
    return anchor_bounds, None
```

### `_has_tt_bottomsheet_signature(elements: list) -> bool` (new helper)

Positive sheet signal — pure function. Returns True if **either**:
- ≥1 element whose `label` matches regex `r'^\+\s*(Добавить|Add)\s+(аккаунт|account)'` (case-insensitive). This is the bottomsheet's add-account row, which is distinctive of the opened sheet.
- ≥2 elements where `text.startswith('@')` AND `y_top > 600` (signature of account-row list in a bottomsheet).

If neither marker present → return False. The function is independent of any specific anchor label and is therefore robust to bottomsheet layouts that legitimately contain `'Управление аккаунтами'` or other broad-anchor strings.


### `_top_labels(elements: list, n: int) -> list[str]` (helper, module-level)

Iterates `elements`, extracts `el.label[:40]` (strip whitespace, skip empty), dedupes preserving insertion order, returns the first `n`. Used for forensic `meta` payloads — bounded so events table rows stay small (≤1.2KB per event for n=30).

### `_is_tt_own_profile(xml: str) -> bool`

Reuse the existing TT own-profile marker check (the function/marker used by `_go_to_profile_tab` for the TT bottom-nav verification step — see existing code in `account_switcher.py` around L876–L900). If a single helper does not already exist, lift the marker check (text contains "Подписчиков" AND "Подписки" AND "Лайки") into a small helper. **Implementation task** decides whether to wrap or inline; the design just requires the assertion.

### Callsite change in `_switch_tiktok`

Replace the inline 2-attempt retry loop (`account_switcher.py:2262-2305`) with a single orchestrator call:

```python
anchor_bounds, err = self._open_tt_account_switcher(
    elements, cfg, target, step_base='tt_3_open_list')
if err:
    # Orchestrator has ALREADY emitted exactly one error-type log_event
    # with meta.category == err. Callsite only translates to _fail with
    # a human-readable reason — NO second event.
    return self._fail(f'tt_3_open_list: {err}', step='tt_3_open_list')
# anchor_bounds is set — continue with existing _find_and_tap_account call.
```

The orchestrator emits **all** canonical `error`-type events itself (with `meta.category == returned_code`), including the legacy `tt_account_sheet_closed_before_parse` when probe yields neither sheet nor Stories. The callsite does **not** re-log — this maintains invariant #1 (exactly one canonical event per failure) and matches the pattern in [[project_error_code_mapper_fail_event_fix]].

## Error Handling Taxonomy

| `error_code` (= `meta.category`) | Condition | `meta` extra |
|---|---|---|
| `tt_account_sheet_closed_before_parse` | Probe didn't open sheet AND didn't open Stories (legacy "single-account device" semantic). **Emitted by orchestrator, not callsite.** | `target`, `reason`, `probe_top_labels[]` |
| `tt_header_tap_failed` | `_tap_profile_header` returned False — defensive (should be impossible given current impl) | (none) |
| `tt_stories_back_failed` | BACK after Stories did not return to own profile | `back_top_labels[]` |
| `tt_profile_menu_not_found` | `cd='Меню профиля'` not tappable in current dump | `profile_top_labels[]` |
| `tt_account_menu_unknown_layout` | Drawer has no broad-anchor trigger | `drawer_labels[]` (top 30) |
| `tt_drawer_tap_did_not_open_sheet` | Drawer trigger tapped, but no sheet anchor / same bounds as tapped entry / no positive bottomsheet signature | `drawer_anchor_label`, `sheet_open_signal`, `sheet_top_labels[]` |

All new codes must be added to the resolver mapping in `error_codes.py` so the canonical-error-code mapper picks them up from `events[].meta.category` on `fail`-events (per [[project_error_code_mapper_fail_event_fix]]).

## Testing

### Unit tests — new file `tests/test_tt_account_switcher_open.py`

1. `test_detect_tt_stories_viewer_yes` — synth elements with `cd=Закрыть y=200`, `cd=Еще y=2080`, `text='· 13 ч. назад'` → True.
2. `test_detect_tt_stories_viewer_no_account_sheet` — synth elements containing `'Управление аккаунтами'` and handle rows → False.
3. `test_detect_tt_stories_viewer_no_blank` — only one of three markers present → False.
4. `test_find_drawer_anchor_ru` — synth drawer with `'Управление аккаунтами'` → returns that element.
5. `test_find_drawer_anchor_en` — synth drawer with only `'Manage accounts'` → returns that element.
6. `test_find_drawer_anchor_fallback_аккаунты` — drawer with only `'Аккаунты'` → fallback hit.
7. `test_find_drawer_anchor_none` — drawer with irrelevant content → None.
8. `test_open_tt_account_switcher_legacy_path` — probe immediately yields bottomsheet (mock `dump_ui` to return XML with `'Управление аккаунтами'`) → `(anchor_bounds, None)`, menu-tap code path NOT exercised (verify via assertion on `_find_tt_account_switcher_anchor_in_drawer` mock not called).
9. `test_open_tt_account_switcher_menu_path_happy` — mocked sequence: probe→Stories, BACK→profile, menu→drawer-with-anchor, tap→sheet **with different bounds than drawer_anchor AND positive sheet signal (`+ Добавить аккаунт` row OR ≥2 `@handle` rows)**. Verify `(anchor_bounds, None)` and that **5 dumps are saved** with step names `tt_3_open_list_probe`, `tt_3_open_list_back`, `tt_3_open_list_menu`, `tt_3_open_list_drawer`, `tt_3_open_list_sheet` (exact names are part of the test contract — they become S3 forensics).
10. `test_open_tt_account_switcher_unknown_layout` — drawer without any trigger → `(None, 'tt_account_menu_unknown_layout')`, exactly one `error`-type `log_event` with `meta.category=='tt_account_menu_unknown_layout'` and `meta.drawer_labels` non-empty.
11. `test_open_tt_account_switcher_single_account_legacy_semantic` — probe yields neither sheet nor Stories → `(None, 'tt_account_sheet_closed_before_parse')`, **exactly one** `error`-type `log_event` from the orchestrator with `meta.category=='tt_account_sheet_closed_before_parse'`. Companion test for the **callsite** verifies the callsite does NOT emit a second `error` event for this case (invariant #1 — exactly one canonical event per failure).
12. `test_open_tt_account_switcher_back_failed` — Stories detected, but BACK does not return to own profile → `(None, 'tt_stories_back_failed')` and `error`-type event with that category + `back_top_labels[]`.
13. `test_open_tt_account_switcher_drawer_noop_identical_bounds` — drawer trigger found, post-tap `sheet_elements` returns identical bounds anchor → `(None, 'tt_drawer_tap_did_not_open_sheet')`.
14. `test_open_tt_account_switcher_drawer_noop_no_sheet_signature` — post-tap dump has different-bounds anchor but no positive sheet signature (no add-account row, no `@`-handles below y=600) → `(None, 'tt_drawer_tap_did_not_open_sheet')` with `meta.sheet_open_signal=False`. Guards against the "legitimate bottomsheet contains broad-anchor row" false-positive flagged by codex.
15. `test_has_tt_bottomsheet_signature_add_account` — synth element `'+ Добавить аккаунт'` → True; synth element `'+ Add account'` → True; synth element `'Управление аккаунтами'` alone → False.
16. `test_has_tt_bottomsheet_signature_at_handles` — 2 `@user1`, `@user2` at y=800/900 → True; 1 `@user1` at y=800 → False (need ≥2); 2 `@user1` `@user2` at y=200/300 → False (need y>600).
17. `test_open_tt_account_switcher_canonical_event_per_error` — parametrised over every non-success error_code: for each, verify exactly **one** `error`-type `log_event` is emitted with `meta.category == <error_code>`, and that the callsite does NOT emit a competing canonical event. Guards invariant #1.
18. `test_open_tt_account_switcher_menu_dump_saved_on_failure` — `tap_element` returns False for menu → verify `_save_dump` was called with step name `tt_3_open_list_menu` (invariant #2 — dump saved regardless of tap outcome).
19. `test_open_tt_account_switcher_probe_retry_old_layout_recovery` — first probe yields neither sheet nor Stories; second probe yields sheet → `(anchor_bounds, None)` after 2 probe attempts. Guards invariant #4 (preserved retry budget for old layout).
20. `test_open_tt_account_switcher_two_failed_probes_no_stories` — both probe attempts yield neither sheet nor Stories → `(None, 'tt_account_sheet_closed_before_parse')` with `meta.probe_top_labels[]`. Guards the legacy single-account semantic after retry exhaustion.
21. `test_find_drawer_anchor_text_with_clickable_parent` — synth tree: non-clickable `TextView` text='Управление аккаунтами' at bounds [100,500,500,560], with clickable container at [50,490,1080,580] (overlaps text) → returns the clickable container, not the text node. Guards two-pass design (pass 2).
22. `test_detect_tt_stories_viewer_english_locale` — synth elements with `cd='Close' y=200`, `cd='More' y=2080`, `text='13 hours ago'` → True. Guards EN locale extension.

### Signature-level regression test

23. `test_tap_profile_header_signature_unchanged` — uses `inspect.signature(AccountSwitcher._tap_profile_header)` to assert parameter names `[self, elements, header_y_max, step, fallback_coords]` and return annotation `bool`. Mirrors the pattern from [[project_tt_switcher_bool_return_fixed]]. Guards against accidental refactor breakage for IG/YT-RO callsites.

### Integration smoke (post-deploy)

1. Per [[reference_publish_requeue_path]]: `UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE id=<a recent clickpay_* publish_queue row>`. The dispatcher picks it up within 5 min.
2. Expected outcomes:
   - **Happy path** (most likely on Pi 9 if our drawer hypothesis is correct): task succeeds; `events[].meta.category` includes `tt_menu_path_opened_bottomsheet`.
   - **First iteration failure on real device**: task fails with `tt_account_menu_unknown_layout`; `events[].meta.drawer_labels` lists the real drawer content — feed straight into iteration #2 spec without further smoke.
3. 24h soak SQL. Per invariant #5 the terminal `failed` event has no `meta.category`; the canonical category lives on the most recent `error`-type event before it. The acceptance query MUST scan backwards for that event:
   ```sql
   WITH last_err AS (
     SELECT pt.id, MAX(ev.idx) AS idx
     FROM publish_tasks pt,
          jsonb_array_elements(pt.events) WITH ORDINALITY AS ev(value, idx)
     WHERE pt.platform = 'TikTok'
       AND pt.created_at >= '<deploy_ts>'
       AND pt.status = 'failed'
       AND ev.value->>'type' = 'error'
       AND ev.value->'meta'->>'category' IS NOT NULL
     GROUP BY pt.id
   )
   SELECT (pt.events->(le.idx::int - 1)->'meta'->>'category') AS cat,
          COUNT(*) AS n
   FROM publish_tasks pt
   JOIN last_err le ON le.id = pt.id
   GROUP BY 1 ORDER BY 2 DESC;
   ```
   (`WITH ORDINALITY` is 1-based; `events` is 0-based, hence `idx - 1`.)

   Acceptance: `tt_account_sheet_closed_before_parse` falls from 19/24h pre-deploy to ≤5/24h. New codes (`tt_account_menu_unknown_layout`, `tt_drawer_tap_did_not_open_sheet`) ≤3/24h combined. If `tt_account_menu_unknown_layout > 3/24h` — start iteration #2 from the `drawer_labels` evidence.

## Risk / Rollout

- **Unverified drawer content** — the largest unknown. Mitigated by `drawer_labels` forensic logging on the first failure under the new code; no need for a manual smoke before deploy.
- **Old-TT regression risk** — mitigated by Phase 1 probe (old happy path is unchanged; phones on older TT versions never enter Phase 2).
- **Extra latency on new layout** ≈9s (probe + BACK + menu + drawer dump + drawer tap + sheet dump). On the old-layout path with a transient first probe, +probe-retry adds another ≈3s. Acceptable — TT publish task already runs many minutes; cumulative addition <2% of total runtime.
- **No feature-flag.** The probe-pivot pattern is itself a self-gating safety: if username-tap opens the sheet directly (old layout), we never touch the new code path. Adding a `TT_PROFILE_MENU_PATH_ENABLED` env-var would be observability dead-weight here, not safety.
- **No DB migration.** Pure code change. Per [[feedback_migrations_for_writers]]: this fix writes only to the existing `publish_tasks.events` JSONB column, no new table.

## Out of scope follow-ups

- If `tt_account_menu_unknown_layout` recurs after the broad-anchor list — extend `TT_DRAWER_ACCOUNT_TRIGGERS` with the real drawer label found in `meta.drawer_labels`, or add a second-step drawer navigation (e.g. "Settings → Account → Switch") if TT nested it deeper.
- Performance optimisation (version-detect to skip probe) — only after sample size proves it's worth it.
- Vision-based fallback if `cd="Меню профиля"` selector itself drifts — defer until evidence appears.
