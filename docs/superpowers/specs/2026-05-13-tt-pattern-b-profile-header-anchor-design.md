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

Pure function (testable on synthetic XML-derived element lists). Returns True if **≥2 of 3** markers present:

- `content-desc == 'Закрыть'` where `y_top < 300`.
- `content-desc == 'Еще'` where `y_top > 1900`.
- Any element `text` matches regex `r'(\d+\s*ч\.\s*назад|\d+\s*мин\.\s*назад|\d+\s*зрителей|\d+\s*виден)'`.

### `_tap_tt_profile_menu(step: str) -> bool`

Fresh `dump_ui()` → `self.p.tap_element(ui, ['Меню профиля'], clickable_only=True)`. Returns the helper's bool. On True: save dump under `step`, take screenshot. On False: `log_event` `tt_profile_menu_button_not_found` (forensic) and return False.

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

For each trigger in priority order: return the first `clickable=True` element whose `label.lower()` contains the trigger. Else `None`.

### `_open_tt_account_switcher(elements, cfg, target, step_base) -> tuple[Optional[tuple], Optional[str]]`

Orchestrator. Returns `(anchor_bounds, error_code)` where exactly one is non-None.

Pseudocode (see Section "Data Flow" in conversation transcript for full control flow):

```python
def _open_tt_account_switcher(self, elements, cfg, target, step_base):
    header_y_max = cfg['profile_title_header_y_range'][1]
    anchors = ACCOUNT_LIST_ANCHORS.get('TikTok', [])

    # --- Phase 1: probe ---
    if not self._tap_profile_header(elements, header_y_max,
                                    f'{step_base}_probe',
                                    fallback_coords=(540, 180)):
        return None, 'tt_header_tap_failed'
    time.sleep(POST_TAP_WAIT_S + 0.8)
    probe_dump = self.p.dump_ui(retries=1)
    probe_elements = parse_ui_dump(probe_dump) if probe_dump else []

    anchor_bounds = find_anchor_bounds(probe_elements, anchors)
    if anchor_bounds:
        self.p.log_event('account_switch',
            f'tt_probe_opened_bottomsheet bounds={anchor_bounds}',
            meta={'category': 'tt_probe_opened_bottomsheet'})
        return anchor_bounds, None

    if not self._detect_tt_stories_viewer(probe_elements):
        self.p.log_event('error',
            'tt_probe_unknown_post_state',
            meta={'category': 'tt_probe_unknown_post_state',
                  'probe_top_labels': _top_labels(probe_elements, 30)})
        return None, 'tt_probe_unknown_post_state'

    self.p.log_event('account_switch',
        'tt_username_tap_opened_stories — reverting + menu path',
        meta={'category': 'tt_username_tap_opened_stories'})
    self.p.adb_shell('input keyevent KEYCODE_BACK')
    time.sleep(POST_TAP_WAIT_S)
    back_dump = self.p.dump_ui(retries=1)
    if not self._is_tt_own_profile(back_dump):
        return None, 'tt_stories_back_failed'

    # --- Phase 2: menu ---
    if not self._tap_tt_profile_menu(f'{step_base}_menu'):
        return None, 'tt_profile_menu_not_found'
    time.sleep(POST_TAP_WAIT_S + 0.8)
    drawer_dump = self.p.dump_ui(retries=1)
    drawer_elements = parse_ui_dump(drawer_dump) if drawer_dump else []
    drawer_anchor = self._find_tt_account_switcher_anchor_in_drawer(drawer_elements)
    if drawer_anchor is None:
        self.p.log_event('error',
            'tt_account_menu_unknown_layout',
            meta={'category': 'tt_account_menu_unknown_layout',
                  'drawer_labels': _top_labels(drawer_elements, 30)})
        return None, 'tt_account_menu_unknown_layout'

    self.p.adb_tap(*drawer_anchor.center)
    time.sleep(POST_TAP_WAIT_S + 0.8)
    sheet_dump = self.p.dump_ui(retries=1)
    sheet_elements = parse_ui_dump(sheet_dump) if sheet_dump else []
    anchor_bounds = find_anchor_bounds(sheet_elements, anchors)
    if not anchor_bounds:
        self.p.log_event('error',
            'tt_drawer_tap_did_not_open_sheet',
            meta={'category': 'tt_drawer_tap_did_not_open_sheet',
                  'drawer_anchor_label': drawer_anchor.label[:50]})
        return None, 'tt_drawer_tap_did_not_open_sheet'

    self.p.log_event('account_switch',
        f'tt_menu_path_opened_bottomsheet bounds={anchor_bounds}',
        meta={'category': 'tt_menu_path_opened_bottomsheet'})
    return anchor_bounds, None
```

### `_top_labels(elements: list, n: int) -> list[str]` (helper, module-level)

Iterates `elements`, extracts `el.label[:40]` (strip whitespace, skip empty), dedupes preserving insertion order, returns the first `n`. Used for forensic `meta` payloads — bounded so events table rows stay small (≤1.2KB per event for n=30).

### `_is_tt_own_profile(xml: str) -> bool`

Reuse the existing TT own-profile marker check (the function/marker used by `_go_to_profile_tab` for the TT bottom-nav verification step — see existing code in `account_switcher.py` around L876–L900). If a single helper does not already exist, lift the marker check (text contains "Подписчиков" AND "Подписки" AND "Лайки") into a small helper. **Implementation task** decides whether to wrap or inline; the design just requires the assertion.

### Callsite change in `_switch_tiktok`

Replace the inline 2-attempt retry loop (`account_switcher.py:2262-2305`) with a single orchestrator call:

```python
anchor_bounds, err = self._open_tt_account_switcher(
    elements, cfg, target, step_base='tt_3_open_list')
if err == 'tt_probe_unknown_post_state':
    # Legacy semantic: single-account device (target not bound).
    reason = ('bottomsheet со списком аккаунтов не открылся — '
              'вероятно, в TikTok на этом устройстве залогинен '
              f"только один аккаунт (target {target!r} не добавлен)")
    self.p.log_event(
        'error',
        f'tt_account_sheet_closed_before_parse: {reason}',
        meta={'reason': 'tt_account_sheet_closed_before_parse',
              'category': 'tt_account_sheet_closed_before_parse',
              'target': target},
    )
    return self._fail(reason, step='tt_3_open_list')
if err:
    return self._fail(
        f'tt_3_open_list: {err}',
        step='tt_3_open_list',
        # category already log_event-ed inside the orchestrator
    )
# anchor_bounds is set — continue with existing _find_and_tap_account call.
```

The orchestrator handles its own `log_event` calls for the new error codes (with `meta.category` set), so the callsite does **not** re-log; this matches the pattern in [[project_error_code_mapper_fail_event_fix]] where `meta.category` on the most recent `error`-type event is the canonical source for the mapper.

## Error Handling Taxonomy

| `error_code` (= `meta.category`) | Condition | `meta` extra |
|---|---|---|
| `tt_account_sheet_closed_before_parse` | Probe didn't open sheet AND didn't open Stories (legacy "single-account device" semantic) | `target` |
| `tt_header_tap_failed` | `_tap_profile_header` returned False — should be impossible given current impl; defensive | (none) |
| `tt_stories_back_failed` | BACK after Stories did not return to own profile | (none — back_dump saved on disk path is enough) |
| `tt_profile_menu_not_found` | `cd='Меню профиля'` not tappable in current dump | (none) |
| `tt_account_menu_unknown_layout` | Drawer has no broad-anchor trigger | `drawer_labels[]` (top 30) |
| `tt_drawer_tap_did_not_open_sheet` | Drawer trigger tapped, but bottomsheet anchor absent | `drawer_anchor_label` |

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
8. `test_open_tt_account_switcher_legacy_path` — probe immediately yields bottomsheet (mock `dump_ui` to return XML with `'Управление аккаунтами'`) → `(anchor_bounds, None)`, `_tap_tt_profile_menu` not invoked.
9. `test_open_tt_account_switcher_menu_path_happy` — mocked sequence: probe→Stories, BACK→profile, menu→drawer-with-anchor, tap→sheet. Verify `(anchor_bounds, None)` and that **4 dumps are saved** with step names `tt_3_open_list_probe`, `tt_3_open_list_menu`, `tt_3_open_list_drawer`, `tt_3_open_list_sheet` (exact names are part of the test contract — they become S3 forensics).
10. `test_open_tt_account_switcher_unknown_layout` — drawer without any trigger → `(None, 'tt_account_menu_unknown_layout')` and the corresponding `log_event` call has `meta.drawer_labels` non-empty.
11. `test_open_tt_account_switcher_single_account_legacy_semantic` — probe yields neither sheet nor Stories → `(None, 'tt_probe_unknown_post_state')`. Companion test for the **callsite** in `_switch_tiktok` verifies this is mapped to a `_fail(...)` with the legacy `tt_account_sheet_closed_before_parse` event/category.
12. `test_open_tt_account_switcher_back_failed` — Stories detected, but BACK does not return to own profile → `(None, 'tt_stories_back_failed')`.

### Signature-level regression test

13. `test_tap_profile_header_signature_unchanged` — uses `inspect.signature(AccountSwitcher._tap_profile_header)` to assert parameter names `[self, elements, header_y_max, step, fallback_coords]` and return annotation `bool`. Mirrors the pattern from [[project_tt_switcher_bool_return_fixed]]. Guards against accidental refactor breakage for IG/YT-RO callsites.

### Integration smoke (post-deploy)

1. Per [[reference_publish_requeue_path]]: `UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE id=<a recent clickpay_* publish_queue row>`. The dispatcher picks it up within 5 min.
2. Expected outcomes:
   - **Happy path** (most likely on Pi 9 if our drawer hypothesis is correct): task succeeds; `events[].meta.category` includes `tt_menu_path_opened_bottomsheet`.
   - **First iteration failure on real device**: task fails with `tt_account_menu_unknown_layout`; `events[].meta.drawer_labels` lists the real drawer content — feed straight into iteration #2 spec without further smoke.
3. 24h soak SQL:
   ```sql
   SELECT events->-1->'meta'->>'category' AS cat, COUNT(*) AS n
   FROM publish_tasks
   WHERE platform='TikTok'
     AND created_at >= '<deploy_ts>'
     AND status='failed'
   GROUP BY 1 ORDER BY 2 DESC;
   ```
   Acceptance: `tt_account_sheet_closed_before_parse` falls from 19/24h pre-deploy to ≤5/24h. New codes (`tt_account_menu_unknown_layout`, `tt_drawer_tap_did_not_open_sheet`) ≤3/24h combined. If `tt_account_menu_unknown_layout > 3/24h` — start iteration #2 from the `drawer_labels` evidence.

## Risk / Rollout

- **Unverified drawer content** — the largest unknown. Mitigated by `drawer_labels` forensic logging on the first failure under the new code; no need for a manual smoke before deploy.
- **Old-TT regression risk** — mitigated by Phase 1 probe (old happy path is unchanged; phones on older TT versions never enter Phase 2).
- **Extra latency on new layout** ≈9s (probe + BACK + menu + drawer dump + drawer tap + sheet dump). Acceptable — TT publish task already runs many minutes; this adds <1% to total runtime.
- **No feature-flag.** The probe-pivot pattern is itself a self-gating safety: if username-tap opens the sheet directly (old layout), we never touch the new code path. Adding a `TT_PROFILE_MENU_PATH_ENABLED` env-var would be observability dead-weight here, not safety.
- **No DB migration.** Pure code change. Per [[feedback_migrations_for_writers]]: this fix writes only to the existing `publish_tasks.events` JSONB column, no new table.

## Out of scope follow-ups

- If `tt_account_menu_unknown_layout` recurs after the broad-anchor list — extend `TT_DRAWER_ACCOUNT_TRIGGERS` with the real drawer label found in `meta.drawer_labels`, or add a second-step drawer navigation (e.g. "Settings → Account → Switch") if TT nested it deeper.
- Performance optimisation (version-detect to skip probe) — only after sample size proves it's worth it.
- Vision-based fallback if `cd="Меню профиля"` selector itself drifts — defer until evidence appears.
