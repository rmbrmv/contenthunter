# Design — TT `Быстрая проверка безопасности` prompt dismissal

**Date:** 2026-05-13
**Branch (planned):** `fix-tt-security-prompt-dismiss-20260513`
**Scope:** minimal additive — detect and dismiss the TikTok "Быстрая проверка безопасности" bottom-sheet that intercepts profile-tab taps in the account-switcher flow.
**Memory cross-links:** [[reference_tt_activities_observed]] (TT activity landscape), [[feedback_ui_automation_edge_cases]] (universal banner pre-dismiss pattern precedent), [[project_revision_phone171_backlog]] (prior TT-stuck-state context), [[feedback_codex_review_specs]] (codex review rule).

## 1. Problem

`error_code='tt_profile_tab_broken'` is a brand-new TikTok failure pattern that emerged 2026-05-13:

| Day | Count |
|---|---:|
| 2026-05-06 to 2026-05-12 | 0 |
| 2026-05-13 | 5 (in 9h, projected ~13/day) |

Distribution: 4 raspberries × 5 distinct devices — systemic, not device-specific.

### Failure pattern (verified on task 5319)

Switcher flow:
1. `tt_1_feed` reached — full TT feed UI dumped (69605 bytes XML)
2. `tt_2_profile_tab_fg_guard` — foreground confirmed
3. **Profile tab tap dispatched** via `tt_bound_nav: tap_method=xml_bounds coords=(972,2136)` — coordinate sourced from the actual profile tab node bounds, so the tap target itself is correct
4. `tt_2_profile_tab` ui_dump captured (52596 bytes — full profile screen visible)
5. **`not_own_profile retap=1`** — the existing retap loop detects "not on own profile" and prepares to retry
6. The dump probed BEFORE the retry decision (xml_probe at line 2108) collapses to 8804 bytes
7. Three subsequent retap dumps all stay at 8804 bytes (10× collapse)
8. After three retaps `tt_2_not_own_profile` fail emitted → canonical `tt_profile_tab_broken`

### Root cause confirmed by ui_dump inspection (task 5319 retap1 dump)

The 8804-byte XML contains exactly 24 nodes, all in `com.zhiliaoapp.musically` package:

| Class | Bounds | Clickable | Text/Desc |
|---|---|---|---|
| `FrameLayout` | `[0,1266][1080,2205]` | false | desc=`Нижняя шторка` (Bottom sheet) |
| `Button` | `[945,1277][1058,1401]` | **true** | desc=`Закрыть` (Close) |
| `TextView` | `[90,1682][990,1834]` | false | text=`Быстрая проверка безопасности` |
| `TextView` | `[90,1834][990,1946]` | false | text=`Повысьте безопасность своего аккаунта с ...` |
| `Button` | `[45,2016][1035,2160]` | true | text=`Продолжить` (Continue) |

**TikTok shows an anti-automation security prompt** that covers the profile screen entirely after the profile tab tap. Our existing retap loop just re-taps the profile tab — that tap lands on the security prompt's underlying area (already showing the prompt), so it doesn't dismiss anything. Retry produces the same dump. After 3 retries the flow fails as `tt_profile_tab_broken`.

The prompt has two safe-side outcomes:
- **Top-right `Закрыть`** (X button): dismisses the prompt without engaging the security flow. After dismiss, profile screen should reappear (this is the standard TikTok behavior for dismissable prompts).
- **Bottom `Продолжить`** (full-width CTA): engages the security flow, which can lead to additional screens we have no automation for.

We want **Закрыть** — skip security, return to profile.

## 2. Fix

### 2.1 New helper `_tt_dismiss_security_prompt`

In `account_switcher.py`, alongside the existing TT helpers (next to `_tt_smart_tap_profile`):

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

### 2.2 Wire into the profile-tab retap loop

In `account_switcher.py:2112-2134` (the existing retap loop body), insert dismiss check **after** the `not_own_profile` log_event and `_save_dump` call, **before** the per-retap action (`retap == 0` plain tap, `retap == 1` smart_tap, `retap == 2` cold-start):

```python
log.warning(f'[FIX: TT-own-profile] не на своём профиле (retap {retap+1}/3)')
self.p.log_event('account_switch',
                 f'not_own_profile step=tt_2_profile_tab retap={retap+1}')
self._save_dump(f'tt_2_not_own_retap{retap+1}', xml_probe)

# NEW: Detect and dismiss the TT security prompt that covers the profile screen.
# If dismissed, the upcoming retap action will land on the real profile tab.
security_dismissed = self._tt_dismiss_security_prompt(xml_probe)
if security_dismissed:
    self.p.log_event(
        'account_switch',
        f'tt_security_prompt_dismissed step=tt_2_profile_tab retap={retap+1}',
        meta={'category': 'tt_security_prompt_dismissed',
              'retap': retap + 1,
              'platform': 'TikTok'},
    )
    time.sleep(POST_TAP_WAIT_S + 0.5)  # let TT animate the sheet out

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

### 2.3 Design rationale

- **Detection requires BOTH markers**, not just title. Anti-false-positive: the title `Быстрая проверка безопасности` is one phrase; we additionally require the bottom-sheet container desc `Нижняя шторка` so we only dismiss when this specific sheet is rendered. Without both, return False — leave control to the existing retap.
- **Tap is on the top-right close (`Закрыть`)**, NOT the bottom `Продолжить`. Continue would engage TikTok's security flow (potentially adding screens we don't automate). Close = skip security, return to profile. This is the only safe-default choice.
- **Dismiss runs before each retap (not just the first)** because the prompt may re-appear. Each retap iteration starts with a fresh check. If TT continues to show the prompt past the third retap, the existing cold-start fallback still fires and the task fails as before — no regression.
- **The retap-action code is unchanged.** Dismiss is purely additive: a side-effect tap before the existing per-retap action. If dismiss returns False (no prompt visible), the loop behaves exactly as it does today.
- **POST_TAP_WAIT_S + 0.5s sleep** after dismiss matches the dismiss animation duration observed in TT (~500-800ms for sheet slide-out).

## 3. Test plan (TDD, RED → GREEN)

New file `tests/test_tt_security_prompt_dismiss.py`:

1. `test_dismiss_finds_close_button_and_taps_centre`
   - Fixture XML with full prompt (sheet desc + title + clickable `Закрыть` at `[945,1277][1058,1401]`).
   - Mock `pub.adb`; call `_tt_dismiss_security_prompt(xml)`.
   - Assert returns True; assert `pub.adb` called with `input tap 1001 1339` (centre of `[945,1277][1058,1401]`).

2. `test_dismiss_no_prompt_markers_returns_false`
   - XML with neither title nor sheet desc.
   - Assert False; `pub.adb` not called.

3. `test_dismiss_partial_markers_only_title_returns_false`
   - XML contains `Быстрая проверка безопасности` text but no `Нижняя шторка` desc anywhere.
   - Assert False; `pub.adb` not called.
   - Guards against false-positives on unrelated screens that happen to mention the phrase.

4. `test_dismiss_close_button_missing_returns_false`
   - Title + sheet desc present, but no node with desc `Закрыть`.
   - Assert False; `pub.adb` not called.

5. `test_dismiss_close_non_clickable_returns_false`
   - Title + sheet desc present, `Закрыть` node present but `clickable="false"`.
   - Assert False; `pub.adb` not called.

6. `test_dismiss_empty_xml_returns_false`
   - `''` input. Assert False; no exception; `pub.adb` not called.

7. `test_dismiss_malformed_bounds_returns_false`
   - Title + sheet desc + clickable `Закрыть`, but `bounds="invalid"`.
   - Assert False; `pub.adb` not called.

8. `test_dismiss_adb_exception_does_not_propagate`
   - All markers correct; `pub.adb.side_effect = RuntimeError('boom')`.
   - Assert returns False; no exception propagates.

Integration test in `tests/test_tt_profile_tab_retap_security.py` (new file alongside the existing TT switcher tests):

9. `test_profile_tab_retap_calls_security_dismiss_when_prompt_visible`
   - Construct a minimal `AccountSwitcher` stub mirroring the pattern in existing TT switcher tests.
   - Mock `xml_probe` to return the prompt XML on retap=0.
   - Mock `_go_to_profile_tab` and `_tt_smart_tap_profile`.
   - Drive one iteration of the retap loop.
   - Assert `_tt_dismiss_security_prompt` was called.
   - Assert `pub.log_event` was called with `category='tt_security_prompt_dismissed'`.

10. `test_profile_tab_retap_no_dismiss_when_no_prompt`
    - Same setup but `xml_probe` returns prompt-free XML.
    - Assert `_tt_dismiss_security_prompt` returned False (no dismiss).
    - Assert no `tt_security_prompt_dismissed` event emitted.
    - Existing retap-action still fires (anti-regression).

All ten tests use `unittest.mock.MagicMock` and pytest. No real ADB, no real DB. Existing TT switcher tests remain GREEN.

## 4. Rollout

- Worktree: `/home/claude-user/autowarm-fix-tt-security-prompt-dismiss-20260513/` on branch `fix-tt-security-prompt-dismiss-20260513` off `origin/main`.
- TDD-first commits:
  1. `test(tt): RED tests for security prompt dismiss helper + wiring`
  2. `fix(tt): dismiss 'Быстрая проверка безопасности' prompt before profile-tab retap`
- Codex review on spec → 0 P1; plan → 0 P1; PR diff → 0 P1. Per [[feedback_codex_review_specs]].
- PR to `GenGo2/delivery-contenthunter` main.
- Auto-deploy: `git pull --ff-only` on prod tree via post-commit hook ([[reference_autowarm_git_hook]]).
- No PM2 restart — publisher.py is subprocess-per-task ([[project_ig_publish_cross_project_leak_2026_05_12]]).

## 5. Live verify (24h post-deploy)

```sql
-- Dismiss helper fire rate
SELECT COUNT(*) FROM publish_tasks pt,
     jsonb_array_elements(pt.events) e
WHERE e->'meta'->>'category' = 'tt_security_prompt_dismissed'
  AND pt.created_at >= '<deploy-ts>';

-- tt_profile_tab_broken drop (baseline 5/24h, projected ~13/day pre-fix)
SELECT COUNT(*) FROM publish_tasks
WHERE error_code='tt_profile_tab_broken'
  AND testbench=false
  AND created_at >= '<deploy-ts>';

-- Rescue rate: tasks where dismiss fired AND task completed
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
  ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'done') / NULLIF(COUNT(*),0), 1) AS pct
FROM dismissed;

-- Spike-check: any new error_code spiked unexpectedly?
SELECT error_code, COUNT(*) FROM publish_tasks
WHERE platform='TikTok' AND status='failed' AND testbench=false
  AND created_at >= '<deploy-ts>'
GROUP BY error_code ORDER BY 2 DESC LIMIT 10;
```

### Acceptance bands

- **`tt_profile_tab_broken < 2 / 24h` AND `tt_security_prompt_dismissed > 0`** → 🎯 close; fix successful.
- **`tt_security_prompt_dismissed > 0` AND rescue rate < 30%** → keep but iterate (security prompt re-appears or TT doesn't return to profile after dismiss).
- **`tt_security_prompt_dismissed == 0` AND `tt_profile_tab_broken` unchanged** → design premise wrong; prompt either rare or doesn't have these markers. Investigate fresh evidence before next attempt.
- **New TT error_code spike** > 5 / 24h that wasn't in baseline → document follow-up; do not claim success on this metric alone.

## 6. Rollback plan

Single `git revert <merge-commit>` on `rmbrmv/contenthunter` main; auto-push hook deploys revert. No DB migration, no flag, no PM2 state. Rollback time: minutes.

## 7. Risks and limitations

- **Pattern B (`tt_account_sheet_closed_before_parse`, 19/24h) NOT in scope.** That pattern has a different root cause (profile-screen layout change causing tap to land on a video preview card) and a separate fix. Backlog item.
- **Prompt may re-appear after dismiss.** Mitigation: dismiss runs at each retap iteration; up to 3 dismiss attempts in the worst case. If TT shows the prompt past 3 retaps, the existing cold-start path engages and the task fails as before — no regression.
- **Locale dependency.** Markers are Russian (`Нижняя шторка`, `Быстрая проверка безопасности`, `Закрыть`). If a device runs TT in English, the helper returns False — same as today's behavior on those devices, no regression. Operator review can add locales later.
- **Dismiss may skip a real security flow on rare accounts that need it.** Those accounts already fail today with `tt_profile_tab_broken`; dismiss does not make them worse. If a specific account requires the security flow to be completed, autowarm cannot solve that in code — that is an operator/manual-recovery problem.
- **The wider TT outage today (88% TT fail rate)** includes other patterns we are NOT addressing: `tt_account_sheet_closed_before_parse=19`, `tt_post_switch_verify_unrecoverable=6`, `tt_upload_confirmation_timeout=7` (PR #44 reduced this from 27 yesterday). Separate items.

## 8. Out of scope (deferred to backlog)

- Pattern B (`tt_account_sheet_closed_before_parse=19/24h`) — profile-screen layout change. Needs a separate spec.
- Additional locale support for the dismiss helper (English / other).
- Tapping `Продолжить` to engage the security flow (would need an automation pipeline for whatever screens follow).
- Universal "TT modal dismisser" that handles other promotional / banner modals beyond this specific security prompt. May be useful if more such modals appear; revisit when evidence justifies it.

## 9. Acceptance criteria summary

- ✅ All 8 helper-unit tests in `tests/test_tt_security_prompt_dismiss.py` GREEN.
- ✅ 2 integration tests in `tests/test_tt_profile_tab_retap_security.py` GREEN.
- ✅ Existing TT switcher suite remains GREEN.
- ✅ Codex review on this spec → 0 P1.
- ✅ Codex review on the implementation plan → 0 P1.
- ✅ Codex review on the PR diff → 0 P1.
- ⏳ 24h post-deploy: `tt_profile_tab_broken < 2 / 24h` AND `tt_security_prompt_dismissed > 0`.
