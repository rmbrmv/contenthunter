# YT picker-state guard — Implementation Plan v1

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Реализовать spec `2026-05-12-yt-picker-state-guard-design.md` — picker-state detector + scroll exit-reason + bounded re-open + RC split.

**Spec:** Codex CLEAN after 5 rounds. Path: `docs/superpowers/specs/2026-05-12-yt-picker-state-guard-design.md`.

**Path conventions:**
- Code: `/root/.openclaw/workspace-genri/autowarm/` branch `fix-yt-picker-state-guard-20260512` (already created from main HEAD).
- Docs: `/home/claude-user/contenthunter/.claude/worktrees/yt-stab-20260512/` branch `yt-stab-20260512`.
- **NO --force push, NO main edits, NO PM2/deploy actions.**

**Pre-existing baseline:** 15 fails on main (canary, ig_camera_recovery, switcher_read_only, testbench_orchestrator, vision_analyzer, canonical_error_codes, publish_guard, canary_inserter). Не наш scope.

---

## Task 1: Branch + baseline

- [ ] `cd /root/.openclaw/workspace-genri/autowarm && git rev-parse --abbrev-ref HEAD` → expect `fix-yt-picker-state-guard-20260512`.
- [ ] `pytest tests/ -q --ignore=tests/test_canary_inserter.py 2>&1 | tail -5` → ≈963 passed / ≈14 failed (baseline).
- [ ] Confirm key landmarks:
  ```
  grep -n "def _scroll_picker_for_target\|def _find_and_tap_account\|def _yt_open_via_settings_activity\|def _yt_try_accounts_btn_with_retries\|yt_target_not_in_picker_after_scroll" account_switcher.py | head -15
  ```
  Expect: `_scroll_picker_for_target` at ~4256, `_find_and_tap_account` at ~3337, `_yt_open_via_settings_activity` exists, target_not_in_picker emit at ~2657.

## Task 2: Module-level helpers (top of `account_switcher.py`)

Append after existing module-level constants:

```python
_YT_PICKER_MARKERS = ('управление аккаунтами', 'другие аккаунты', 'аккаунт google')

def _is_yt_picker_present(elements: list) -> bool:
    """Detect if current UI dump is YT account picker.

    Heuristic — ANY of:
      • marker phrase from _YT_PICKER_MARKERS in any element's label
      • ≥ 2 elements with '@gmail' in label (account gmails visible)
    """
    if not elements:
        return False
    labels = [(e.label or '').lower() for e in elements if e.label]
    if not labels:
        return False
    joined = ' '.join(labels)
    if any(m in joined for m in _YT_PICKER_MARKERS):
        return True
    gmail_count = sum(1 for l in labels if '@gmail' in l)
    return gmail_count >= 2


def _sample_picker_diag(elements: list) -> dict:
    """Extract picker content snapshot for evidence/triage.

    Returns dict with up to 10 entries each for gmails / handles / displays.
    Used in error event meta for both yt_picker_dismissed and yt_picker_target_absent.
    """
    gmails, handles, displays = [], [], []
    for e in elements:
        lbl = (e.label or '').strip()
        if not lbl:
            continue
        l_lower = lbl.lower()
        if '@gmail' in l_lower:
            gmails.append(lbl[:120])
        if lbl.startswith('@'):
            handles.append(lbl[:80])
        if e.clickable:
            displays.append(lbl[:80])
    return {
        'gmails': gmails[:10],
        'handles': handles[:10],
        'displays': displays[:10],
    }
```

## Task 3: Recovery helper inside `AccountSwitcher`

Найти удобное место (near `_scroll_picker_for_target`) и добавить method:

```python
def _yt_try_reopen_picker(self, cfg: dict, step: str) -> bool:
    """One-shot bounded re-open YT picker via existing fallback paths.

    Tries (in order): (1) navigate to profile-tab and re-tap "Аккаунты" button,
    (2) Shell_SettingsActivity intent fallback (per memory
    reference_yt_accounts_settings_path). Returns True iff fresh dump shows
    picker present (_is_yt_picker_present).
    """
    self.p.log_event('info', f'yt_try_reopen_picker: step={step}',
                     meta={'reason': 'yt_try_reopen_picker', 'step': step})
    # Path 1 — re-tap profile + Аккаунты button
    try:
        self._go_to_profile_tab(cfg, f'{step}_reopen_profile')
    except Exception as e:
        log.warning(f'[switcher] reopen path1 _go_to_profile_tab raised: {e}')
    # short wait + dump
    import time as _t
    _t.sleep(POST_TAP_WAIT_S + 0.5)
    elements, _, _ = self._read_screen_hybrid(f'{step}_reopen_post_profile')
    if not elements:
        elements = []
    accts = self._yt_try_accounts_btn_with_retries(elements, cfg)
    if accts.get('found'):
        _t.sleep(POST_TAP_WAIT_S + 0.8)
        ui_after = self.p.dump_ui(retries=2)
        if _is_yt_picker_present(parse_ui_dump(ui_after) if ui_after else []):
            self.p.log_event('info', f'yt_picker_reopened: via=accounts_btn',
                             meta={'reason': 'yt_picker_reopened', 'via': 'accounts_btn'})
            return True
    # Path 2 — Shell_SettingsActivity intent
    try:
        if self._yt_open_via_settings_activity(target_handle=None, cfg=cfg):
            ui_after = self.p.dump_ui(retries=2)
            if _is_yt_picker_present(parse_ui_dump(ui_after) if ui_after else []):
                self.p.log_event('info', f'yt_picker_reopened: via=settings_activity',
                                 meta={'reason': 'yt_picker_reopened', 'via': 'settings_activity'})
                return True
    except Exception as e:
        log.warning(f'[switcher] reopen path2 settings_activity raised: {e}')
    self.p.log_event('warning', f'yt_picker_reopen_failed: step={step}',
                     meta={'reason': 'yt_picker_reopen_failed', 'step': step})
    return False
```

> **Note:** `_yt_open_via_settings_activity` signature — verify by grep. If `target_handle` is positional/named и required — adjust call. If method doesn't accept None — refactor minimally или use only path 1.

## Task 4: Patch `_scroll_picker_for_target`

Change signature (add `cfg: dict, step: str`):
```python
def _scroll_picker_for_target(self, target_handle: str, cfg: dict, step: str,
                              max_stale: int = 3,
                              swipe_y_start: int = 1800,
                              swipe_y_end: int = 600,
                              ) -> tuple:
    """Returns (found: bool, reason: str).
    Reasons: 'found', 'exhausted', 'max_iter_no_stale', 'dismissed_unrecovered'.
    """
```

Body changes (at start of loop body, after `elements = parse_ui_dump(xml)`):

```python
reopened = False  # outside loop

for attempt in range(1, max_stale * 3 + 1):
    xml = self.p.dump_ui(retries=2)
    if not xml:
        continue
    elements = parse_ui_dump(xml)

    # --- NEW: picker-state guard ---
    if not _is_yt_picker_present(elements):
        self.p.log_event(
            'warning',
            f'yt_picker_dismissed_during_scroll: attempt={attempt}',
            meta={'reason': 'yt_picker_dismissed_during_scroll',
                  'attempt': attempt,
                  'picker_diag': _sample_picker_diag(elements)},
        )
        if reopened:
            return (False, 'dismissed_unrecovered')
        reopened = True
        if self._yt_try_reopen_picker(cfg, step):
            stale_rounds = 0
            seen_keys = set()
            continue
        return (False, 'dismissed_unrecovered')

    # ... existing target-match / scroll logic unchanged ...
    # Replace existing `return True/False` с:
    # return (True, 'found')  on match
    # return (False, 'exhausted')  on stale_rounds >= max_stale
return (False, 'max_iter_no_stale')   # after for-loop fall-through
```

## Task 5: Patch caller — split RC

В `account_switcher.py` около line 2648-2669 (где `yt_target_not_in_picker_after_scroll` emit), заменить:

```python
ok = self._find_and_tap_account(target, cfg, step='yt_4_pick_account')
if not ok:
    is_youtube = cfg.get('package') == 'com.google.android.youtube'
    if is_youtube:
        found, scroll_reason = self._scroll_picker_for_target(
            target, cfg, step='yt_4_pick_account_after_scroll')
        if found:
            ok = self._find_and_tap_account(
                target, cfg, step='yt_4_pick_account_after_scroll')

    if not ok:
        # Split umbrella RC per spec.
        fresh_xml = self.p.dump_ui(retries=1)
        fresh_elements = parse_ui_dump(fresh_xml) if fresh_xml else []
        picker_present_after = _is_yt_picker_present(fresh_elements)
        diag = _sample_picker_diag(fresh_elements) if fresh_elements else {}
        scroll_reason = locals().get('scroll_reason', 'not_attempted')

        if is_youtube and scroll_reason == 'exhausted' and picker_present_after:
            self.p.log_event(
                'error',
                f'yt_picker_target_absent: target={target!r} '
                f'gmails={diag.get("gmails", [])[:3]}',
                meta={'category': 'yt_picker_target_absent',
                      'reason': 'yt_picker_target_absent',
                      'target': target,
                      'gmail': self._yt_target_gmail or None,
                      'scroll_reason': scroll_reason,
                      'picker_diag': diag},
            )
        elif is_youtube and scroll_reason == 'dismissed_unrecovered':
            self.p.log_event(
                'error',
                f'yt_picker_dismissed: target={target!r}',
                meta={'category': 'yt_picker_dismissed',
                      'reason': 'yt_picker_dismissed',
                      'target': target,
                      'gmail': self._yt_target_gmail or None,
                      'scroll_reason': scroll_reason,
                      'picker_diag': diag},
            )
        else:
            # Legacy catch-all: max_iter_no_stale, not_attempted (non-YT or fast-fail),
            # exhausted-but-picker-not-present, etc.
            self.p.log_event(
                'error',
                f'yt_target_not_in_picker_after_scroll: target={target!r} '
                f'gmail={self._yt_target_gmail or None}',
                meta={'category': 'yt_target_not_in_picker_after_scroll',
                      'reason': 'yt_target_not_in_picker_after_scroll',
                      'target': target,
                      'gmail': self._yt_target_gmail or None,
                      'scroll_reason': scroll_reason,
                      'picker_present_after': picker_present_after,
                      'picker_diag': diag},
            )
        return self._fail(
            f"аккаунт {target!r} не привязан к устройству",
            step='yt_4_pick_account',
        )
```

## Task 6: Unit tests

**`tests/test_yt_picker_state_guard.py`** — pure logic, no ADB. 8 tests per spec Test Plan section 1-8. Fixtures: real XML from /tmp/task3970_acc_retry.xml (picker), /tmp/task3970_picker.xml (video player), /tmp/task5054_pick.xml (recents). Inline strings OK if file paths flaky.

**`tests/test_yt_picker_dismissed_recovery.py`** — integration. 6 tests (9-14 in spec):
- Mock dump_ui sequence returning video XML → assert reopen called.
- Mock reopen → True + picker XML on next → assert (True, 'found').
- Mock reopen → False → assert (False, 'dismissed_unrecovered').
- Caller: scroll returns ('exhausted', picker present) → assert `yt_picker_target_absent` event with picker_diag meta.
- Caller: scroll returns 'dismissed_unrecovered' → assert `yt_picker_dismissed` event.
- Caller: scroll returns 'max_iter_no_stale' → assert legacy `yt_target_not_in_picker_after_scroll` event.

## Task 7: Suite green

```bash
pytest tests/ -q --ignore=tests/test_canary_inserter.py 2>&1 | tail -5
```
Expected: baseline + 14 new = ≈977 passed / ≈14 failed (no regressions).

## Task 8-11: Parent handles
- 8: stage + commit
- 9: codex review on patches (rounds до 0 P1)
- 10: PR create в GenGo2/delivery-contenthunter
- 11: evidence file в docs

## Out of scope (backlog)
- Real RC discovery: что dismisses picker в 23-second window (3970) / triggers recents tray (5054). Hypothesis: spurious navigation / system overlay. Defensive guard первичен.
- `Lead_Content_1` handle/display mismatch — data drift, fix in `account_revision` or manual deactivation.
- 24h soak SQL queries for new RC counts.
