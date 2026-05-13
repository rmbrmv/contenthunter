# Design — IG share `action_bar OK` fallback (Tier 1.5)

**Date:** 2026-05-13
**Branch (planned):** `fix-ig-share-ok-fallback-20260513`
**Scope:** minimal additive layer to `_wait_instagram_upload` Tier 1 ladder. After the existing two share-button re-taps fail, attempt one tap on the editor's top-right action-bar `OK` button before declaring `ig_share_tap_no_progress`.
**Memory cross-links:** [[project_ig_share_tier2_design]] (the long-press attempt that was reverted), [[project_ig_share_regression_post_pr31_2026_05_12]] (the spike that triggered the revert), [[feedback_publish_fail_analysis_video_first]] (the triage discipline that surfaced the editor-screen evidence), [[feedback_ui_dump_app_recognition]].

## 1. Problem

`error_code='ig_share_tap_no_progress'` is the top Instagram failure pattern as of 2026-05-13:

| Day | Count |
|---|---:|
| 2026-05-09 | 1 |
| 2026-05-10 | 2 |
| 2026-05-11 | 4 (PR #31 merged at 09:50 UTC — added Tier 2 long-press) |
| 2026-05-12 | 18 (full day post-PR #31; PR #37 reverted Tier 2 at 12:27 UTC, 0/19 rescue) |
| 2026-05-13 | 11 (in 9h, projected ~30) |

Distribution at 24h sample: 11 failures across **8 raspberries and 11 distinct devices** — systemic, not device-specific.

### Failure pattern (verified across 12 sample tasks)

Every failed task follows the same wall-clock cadence:

| Marker | Offset | Source |
|---|---|---|
| Share button first tap | T+0 | `Instagram: кнопка Поделиться нажата` |
| `wait_upload_iter0_diag` capture | T+9..26s | `meta.category='wait_upload_iter0_diag'` |
| Tier 1 retry 1 (re-tap share) | T+42s | `meta.category='ig_share_retry'` `retry_n=1` |
| Tier 1 retry 2 (re-tap share) | T+60s | `meta.category='ig_share_retry'` `retry_n=2` |
| `ig_share_tap_no_progress` emitted | T+74s | `meta.category='ig_share_tap_no_progress'` |
| `watchdog_fired` (90s step timeout) | T+90s | the wait_upload step watchdog |

Compare with a successful tap (task 5279 at 2026-05-13 08:40:52):
- Share button tap at T+0
- `wait_upload_iter0_diag` at T+9s — editor already gone
- `MainTabActivity` confirmed at T+20s — task `done`

### Root cause confirmed by ui_dump inspection

For task 5237 (`task5237_publish_5237_wait_upload_iter0_*.xml`):

- `topResumedActivity = com.instagram.modal.ModalActivity` (the editor lives under ModalActivity at this stage — confirmed across 3 of 5 sampled iter0 dumps; the other 2 had an empty dumpsys, not contradictory)
- `caption_input_text_view` resource-id present, populated with our caption text
- `action_bar_title text='Новое видео Reels'` — this IS the Reels metadata/share screen, NOT a cross-post sheet
- `id/share_button` clickable=true at bounds `[563,2025][1035,2149]`, content-desc='Поделиться' — the standard share button
- `id/save_draft_button` clickable=true at `[45,2025][518,2149]`, content-desc='Сохранить черновик'
- **`id/action_bar_button_text` clickable=true at `[930,117][1057,253]`, text=`ОК`, content-desc=`ОК`** — top-right confirm button on the same screen

The share button is correctly identified and dispatched (the `tap_element(['Поделиться'], clickable_only=True)` matches `id/share_button` whose `content-desc='Поделиться'`). **IG silently ignores the tap.** Retrying the same button produces no progress.

### Hypothesis re-tap doesn't help

- PR #31's Tier 2 long-press (200ms hold on same share_button) rescued 0/19 → repeat-same-button is exhausted as a strategy.
- The `OK` button at the top-right of the action bar (`action_bar_button_text`) is a structurally distinct control on the same screen. In standard IG Reels editor flow it serves as the alternative finalize/confirm. Tapping it has not yet been attempted by autowarm.

This is a one-button hypothesis: **if IG accepts an `OK`-tap when it ignores `share_button` taps on the same screen, the rescue rate will be positive.** If it does not, we fall through to the same fail-path with one extra logged attempt and zero behavior change for the success path.

## 2. Fix

### 2.1 New helper `_tap_ig_action_bar_ok`

In `publisher_instagram.py`, add a helper next to `_long_press_share_button` (around line 904; `_long_press_share_button` itself is unused since PR #37 revert and is left untouched per the original revert PR's "no cleanup" decision):

```python
def _tap_ig_action_bar_ok(self, ui_xml: str) -> bool:
    """Find and tap the editor's top-right action-bar `OK` button.

    On the IG Reels editor/share screen the top-right confirm is a
    clickable node with resource-id ending in `:id/action_bar_button_text`
    and text=='ОК' (Russian locale) or 'OK' (English locale). Used as a
    Tier 1.5 fallback when `share_button` re-taps are ignored by IG.

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

### 2.2 Tier 1.5 fallback in `_wait_instagram_upload`

In `publisher_instagram.py:2594-2637` (the existing Tier 1 retry block), insert a single OK-tap attempt between the loop exit and the existing fail-path:

```python
# Existing Tier 1 retry block:
share_no_progress = False
try:
    if self._is_ig_editor_still_visible(iter0_ui_xml):
        progressed = False
        for retry_n in range(1, 3):
            time.sleep(3)
            retry_ui = self.dump_ui()
            if not self._is_ig_editor_still_visible(retry_ui):
                progressed = True
                break
            if self.tap_element(retry_ui, ['Поделиться', 'Share', 'Опубликовать'],
                                exact=False, clickable_only=True):
                self.log_event('info', f'Instagram: Share re-tap retry {retry_n}',
                               meta={'category': 'ig_share_retry',
                                     'platform': self.platform,
                                     'retry_n': retry_n})
                time.sleep(2)
            else:
                log.warning(f'wait_upload retry {retry_n}: tap_element no share match — break to final check')
                break

        # NEW: Tier 1.5 — one fallback tap on action_bar OK.
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
            # Unchanged: fail-fast emit.
            # ok_fallback_attempted reflects only whether a tap was actually
            # dispatched (helper returned True), not whether the conditional
            # was entered.
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
except Exception as _retry_e:
    log.warning(f'wait_upload share retry block failed: {_retry_e}')
```

Note the additional `'ok_fallback_attempted': True` field on the existing `ig_share_tap_no_progress` event so a single SQL query can distinguish fails that did NOT exercise the new path (pre-deploy or hypothetical OK-helper-aborts) from fails that did.

### 2.3 Design rationale

- **Single new tap, single new event-category.** Triage stays cheap: one new `ig_share_ok_button_attempted` event tells you the fallback ran; `ok_fallback_attempted` flag on `ig_share_tap_no_progress` tells you it ran but didn't rescue.
- **Locale match `('ОК', 'OK')` only.** Avoids false matches on other action_bar buttons (e.g., `Готово`, `Skip`, `Назад`) that may share the `action_bar_button_text` resource-id pattern. If IG ships a third locale later, we add it explicitly.
- **No share-flow behavior change on the success path.** The new code only runs inside the `if self._is_ig_editor_still_visible(iter0_ui_xml):` branch, which gates the existing Tier 1 retries — i.e., only when iter0 already proved IG ignored the original tap.
- **Tier 2 long-press helper `_long_press_share_button` is left in place.** PR #37 reverted the Tier 2 *call site* but kept the helper. We do not re-introduce a call here; that would re-create the regression PR #37 closed.

## 3. Test plan (TDD-first)

New file `tests/test_ig_share_ok_fallback.py`.

1. `test_tap_ig_action_bar_ok_finds_ru_label`
   - XML fixture with one `action_bar_button_text` node, text='ОК', clickable=true, bounds `[930,117][1057,253]`.
   - Mock `pub.adb`; call `_tap_ig_action_bar_ok(xml)`.
   - Assert returns True; assert `pub.adb` called with command containing `input tap 993 185`.

2. `test_tap_ig_action_bar_ok_finds_en_label`
   - Same fixture but text='OK' instead of 'ОК'.
   - Assert returns True.

3. `test_tap_ig_action_bar_ok_no_button_returns_false`
   - XML with no action_bar_button_text node.
   - Assert returns False; assert `pub.adb` not called.

4. `test_tap_ig_action_bar_ok_non_clickable_returns_false`
   - action_bar_button_text present with text='ОК' but `clickable="false"`.
   - Assert returns False; `pub.adb` not called.

5. `test_tap_ig_action_bar_ok_other_text_returns_false`
   - action_bar_button_text present with text='Готово' (a different action-bar label).
   - Assert returns False; `pub.adb` not called. Guards locale-restrict.

6. `test_tap_ig_action_bar_ok_empty_xml_returns_false`
   - Empty string XML; assert False; no exception.

7. `test_tap_ig_action_bar_ok_malformed_bounds_returns_false`
   - Node present, clickable=true, text='ОК', `bounds="invalid"`.
   - Assert False; no exception.

8. `test_tap_ig_action_bar_ok_adb_exception_returns_false`
   - `pub.adb.side_effect = RuntimeError('boom')`.
   - Assert returns False; no exception propagated.

For the integration of Tier 1.5 into `_wait_instagram_upload`, the existing 26-test IG suite supplemented with the following three new tests (in the existing `tests/test_publisher_instagram.py` or a sibling file, whichever is consistent with the project — confirm by reading current IG-suite layout):

9. `test_wait_upload_ok_fallback_fires_after_share_retries_exhausted`
   - Mock `_is_ig_editor_still_visible` to return True for iter0, True after each retry, True before OK fallback.
   - Mock `tap_element` to return True (share retries dispatch).
   - Mock `_tap_ig_action_bar_ok` to return True; mock `_is_ig_editor_still_visible` to return False after OK tap.
   - Assert `pub.log_event` was called with `category='ig_share_ok_button_attempted'`.
   - Assert NO `ig_share_tap_no_progress` event emitted.

10. `test_wait_upload_ok_fallback_failure_falls_through_to_fail`
    - Same setup as #9 but `_is_ig_editor_still_visible` remains True after OK tap.
    - Assert `ig_share_ok_button_attempted` event was emitted (helper ran).
    - Assert `ig_share_tap_no_progress` event was emitted with `meta.ok_fallback_attempted == True`.

11. `test_wait_upload_no_ok_fallback_when_progressed_naturally`
    - `_is_ig_editor_still_visible` returns True for iter0 then False after retry 1.
    - Assert `_tap_ig_action_bar_ok` was NOT called.
    - Assert NO `ig_share_ok_button_attempted` event emitted.

All eleven tests use `unittest.mock.MagicMock`; no real ADB or real DB. The existing 26-test IG share suite remains green.

## 4. Rollout

- Worktree: `/home/claude-user/autowarm-fix-ig-share-ok-fallback-20260513/` on branch `fix-ig-share-ok-fallback-20260513` off `origin/main`.
- TDD-first commits:
  1. `test(ig): RED tests for action_bar OK fallback helper + Tier 1.5 wiring`
  2. `fix(ig): action_bar OK fallback after share retries exhaust (Tier 1.5)`
- Codex review on spec → 0 P1; plan → 0 P1; PR diff → 0 P1. Per [[feedback_codex_review_specs]].
- PR to `GenGo2/delivery-contenthunter` main.
- Auto-deploy: `git pull --ff-only` on prod tree via post-commit hook ([[reference_autowarm_git_hook]]).
- No PM2 restart — publisher.py is subprocess-per-task ([[project_ig_publish_cross_project_leak_2026_05_12]]).
- In-flight tasks finish on old code; no regression vector.

## 5. Live verify (24h post-deploy)

```sql
-- Rescue rate: OK fallback fired vs OK rescued
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

```sql
-- Overall ig_share_tap_no_progress drop (baseline 11-18/24h)
SELECT COUNT(*) FROM publish_tasks
WHERE error_code='ig_share_tap_no_progress'
  AND testbench=false
  AND created_at >= '<deploy-ts>';
```

```sql
-- Spike-check (catch shifted failure modes)
SELECT error_code, COUNT(*) FROM publish_tasks
WHERE platform='Instagram' AND status='failed' AND testbench=false
  AND created_at >= '<deploy-ts>'
GROUP BY error_code ORDER BY 2 DESC LIMIT 10;
```

### Acceptance bands

- **`ok_rescued_24h / ok_attempted_24h ≥ 30%`** → keep; design successful.
- **10-30% rescue** → keep; document partial win; plan Tier 2 follow-up (e.g., longer wait between retries, keyevent ENTER as Variant C).
- **<10% rescue (incl. 0%)** → revert + escalate to investigation: collect more `wait_upload_iter0_diag` evidence, consider account-side audit, design Variant B alternating retries or Variant C keyevent path.

## 6. Rollback plan

Single `git revert <fix-commit>` on `rmbrmv/contenthunter` main. Auto-push hook deploys the revert. No DB migration, no flag, no PM2 state. Total rollback time: ~minutes.

## 7. Risks and limitations

- **`OK` may be a different control than I think.** The IG Reels editor screen presents `action_bar_button_text` with text='ОК' on iter0_diag XMLs from failed tasks, but I have not yet observed what tapping `OK` actually does in production. Tests #9 + #10 cover both outcomes (rescue and non-rescue); production behavior will tell us within the 24h window.
- **Locale dependency.** Restricting to `{'ОК', 'OK'}` is a deliberate guard against tapping unrelated action-bar buttons. If a device runs IG in a third locale where this control is labelled differently (e.g., `Hecho` in Spanish), the fallback won't fire on that device — same as today's behavior, no regression. Operator review can add locales explicitly.
- **AI badge / content-disclosure dialog.** ui_dump for failed tasks shows the AI badge nudge ("Вы должны отмечать значком определенный..."). It is not yet known whether this prompt blocks share completion silently. If so, OK fallback may not rescue, and we will see `ok_attempted_24h > 0` with `ok_rescued_24h ≈ 0`. That is the signal to investigate AI-badge-side mitigation, out of scope here.
- **Account-side soft blocks.** Some failing accounts may be IG-side rate-limited or shadow-suspended. Fallback won't rescue those. Distribution evidence shows the issue is not account-specific (11 distinct accounts), so this is unlikely to be the dominant root cause, but it cannot be ruled out from in-tree evidence alone.

## 8. Out of scope (deferred to backlog)

- Variant B (alternating share / OK retries) — only consider if Variant A rescue rate is 10-30% and the data suggests order-sensitivity.
- Variant C (`adb shell input keyevent KEYCODE_ENTER` as final fallback) — only consider if Variant A rescue rate < 10%.
- Removing the unused `_long_press_share_button` helper (left from PR #31). Keeping per the PR #37 revert's "no cleanup" stance.
- AI badge auto-toggle. Needs separate investigation of which accounts/content trigger the prompt.
- Account-side audit of repeating-fail accounts. Separate Discovery task per [[project_ig_failing_accounts_audit_backlog]].

## 9. Acceptance criteria summary

- ✅ All eight new helper tests (`tests/test_ig_share_ok_fallback.py` tests 1-8) GREEN.
- ✅ Three new integration tests (tests 9-11) GREEN.
- ✅ Existing 26-test IG share suite remains GREEN.
- ✅ Codex review on this spec → 0 P1.
- ✅ Codex review on the implementation plan → 0 P1.
- ✅ Codex review on the PR diff → 0 P1.
- ⏳ 24h post-deploy: `ok_attempted_24h > 0` and `ok_rescued_24h / ok_attempted_24h ≥ 30%`.
- ✅ Pre-deploy in-flight tasks not regressed.
