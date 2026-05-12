# YT picker-state guard — split `yt_target_not_in_picker_after_scroll` umbrella — design spec v1

**Date:** 2026-05-12
**Status:** Draft (awaiting Codex review)
**Related:** Live evidence from tasks 3970 / 5054 / 4889 (clickpay_team / clickpay_go / Lead_Content_1).

## Problem

Error code `yt_target_not_in_picker_after_scroll` (21 fails/7d) — зонтик над **минимум 2 разными root causes**, что мешает целевому фиксу:

1. **Picker dismissed mid-flight (race):** picker открывается, switcher успевает сделать 1-2 dump'а, потом UI уходит на video player / recents tray / другой экран. `_scroll_picker_for_target` 9 раундов swipe-up по не-picker'у, eventually stale → exit. Финальный dump капчит не-picker, отчёт говорит «target not in picker», диагностика misleading.

2. **Target absent in picker (data drift):** picker остаётся открытым, но handle из `factory_inst_accounts` не присутствует в picker'е (account удалён/renamed/logout на phone). Switcher честно не находит → fail с тем же error code, что и race. На отслеживании impossible понять что чинить.

В обоих случаях operator видит идентичную ошибку `yt_target_not_in_picker_after_scroll` и не может приоритизировать.

## Evidence

### Sample 1 — picker → video player race (task 3970, clickpay_team)

S3 dumps (timestamps в filename, в секундах с начала switch):
- `yt_3_open_accounts_retry1` at +42s: **picker open** with all 3 accounts (clickpay_life / clickpay_team / paint&art), gmails visible, `find_yt_row_by_gmail("clickpay.team26@gmail.com")` → `(540, 676)` (verified offline).
- `yt_4_pick_account` at +65s: **video playback** (`text="Описание"`, `text="54 мин"`). Picker dismissed.
- 23-секундное dead-time между retry-1 dump и финальным pick_account dump.
- 9 scroll rounds (`yt_picker_scroll_exhausted`) — все swipe'ы happened on video player, не picker.

### Sample 2 — picker → recents tray race (task 5054, clickpay_go)

- `yt_3_open_accounts` at +20s: **picker open** with clickpaygo / clickpay officia / VitalVelvet / etc., gmails visible.
- `yt_4_pick_account` at +40s: **recents tray** (`text="1 активное приложение"`, `text="Творческая студия YouTube"`, `text="Закрыть все"`).
- Recents app switcher overlay opened during scroll loop — possibly via spurious gesture.

### Sample 3 — data drift (task 4889, Lead_Content_1)

- `yt_3_open_accounts` at +14s: picker open. Visible texts: `lera090426@gmail.com`, `lora090426@gmail.com`, `pon0656752578@gmail.com`, `@KiraNelson-cosmo`, `Lead_Content ` (trailing NBSP, **no** `@Lead_Content_1` handle).
- `yt_4_pick_account` at +17s: **identical content**, picker still open.
- БД hand-le `Lead_Content_1`, gmail=NULL (backfill no-match сегодня). На phone имя кана-ла — `Lead_Content` (без `_1` suffix), а handle в picker'е отсутствует совсем (только display name + другая gmail).

### Why current code conflates

`_scroll_picker_for_target` (`account_switcher.py:4256`):
- Принимает любой UI dump, iterates elements, matches `target_lc in label` OR `gmail_hint in label`.
- На picker-state — корректно ищет, на video/recents — никогда не найдёт, но это не distinguishes.
- Exit на stale без context — "exhausted" вместо "wrong screen entirely".

`_find_and_tap_account` YT-path (`account_switcher.py:3337`):
- Парсит elements, вызывает `find_yt_row_by_gmail` / `find_account_in_list`.
- Если visible list пуст AND source=uiautomator AND dump usable → FAIL (line 3378-3381). Тоже не distinguishes wrong-screen vs target-absent.

Поэтому два очень разных RC получают один error code.

## Goals

1. **Разделить error codes** на distinguishable RCs:
   - `yt_picker_dismissed_during_scroll` — picker исчез (текущий dump НЕ picker).
   - `yt_picker_target_absent` — picker present, но target отсутствует в visible list (data drift / wrong picker page).
   - Существующий `yt_target_not_in_picker_after_scroll` остаётся как catch-all для exhausted-after-true-scroll (e.g. picker present с 50 accounts, target ещё ниже за swipe limit).

2. **Recovery for dismissed-mid-flight:** при detection — log + одна попытка re-open picker через текущий fallback path (`Аккаунты` button / `Shell_SettingsActivity`); если re-open ok — продолжить scroll loop с fresh state.

3. **Observability for data-drift:** при detection picker-present-but-target-absent — записывать визуализируемый list (`picker_accounts: ['display1@gmail.com', ...]`) в meta, чтобы analyst could match against БД и решить какие записи деактивировать.

4. **Никаких false-positives** — guard НЕ должен срабатывать когда picker нормально открыт.

## Non-goals

- **НЕ менять matcher logic** — `find_yt_row_by_gmail` / `find_account_in_list` корректны на тех XML'ях, где picker present.
- **НЕ chasing 23-sec dead-time root cause** — что именно сбрасывает picker (video tap / system overlay / etc) — отдельное investigation. Defensive guard первичен.
- **НЕ менять IG/TT switchers** — evidence показывает только YT.
- **НЕ менять `account_blocks` / БД ингест** — data drift (`Lead_Content_1`) лечится отдельной maintenance task (deactivate stale).

## Approach

**3 layered defense:**

### Layer 1: Picker-state detector (start of scroll + before parse)

Функция `_is_yt_picker_present(elements: list) -> bool` (или на raw `xml: str`) проверяет markers:

```
markers (any one match → picker present):
  - 'Управление аккаунтами' in any element label
  - 'Другие аккаунты' in any element label
  - ≥ 2 elements с '@gmail' в label (account gmails)
  - 'Аккаунт Google' header element
```

Используется в начале `_scroll_picker_for_target` (новая short-circuit) и в начале `_find_and_tap_account` YT-path.

### Layer 2: Dismissed-during-scroll detection + recovery

В `_scroll_picker_for_target` (line 4261), перед каждым iteration:
```python
if not _is_yt_picker_present(elements):
    # Picker dismissed — log + try re-open
    log_event('warning', 'yt_picker_dismissed_during_scroll: attempt=%d screen_marker=%s',
              meta={'category': 'yt_picker_dismissed_during_scroll',
                    'attempt': attempt,
                    'screen_markers': sample_markers_for_diag(elements)})
    if not reopened:  # at most one re-open per scroll
        reopened = True
        if self._yt_try_reopen_picker(...):
            # fresh state, continue loop
            stale_rounds = 0; seen_keys = set()
            continue
    # re-open failed or already used → exit with explicit RC
    return False  # caller logs yt_picker_dismissed_post_scroll
```

Caller (line 2657, `yt_target_not_in_picker_after_scroll` event) обновлён:
- Если scroll returned False AND saw `yt_picker_dismissed_during_scroll` event → log `yt_picker_dismissed` final RC.
- Если scroll returned False AND picker present at end (exhausted) → log new `yt_picker_target_absent` с диагностикой visible accounts.
- Existing `yt_target_not_in_picker_after_scroll` остаётся для path где `_find_and_tap_account` first-attempt failed без entering scroll loop (very fast fail).

### Layer 3: Picker-content diagnostic

`_sample_picker_diag(elements) -> dict` собирает (для evidence):
```python
{
    'gmails': [labels containing '@gmail'][:10],
    'displays': [clickable rows top:10 labels][:10],
    'handles': [labels starting with '@'][:10],
}
```

Append в meta when emitting `yt_picker_target_absent` AND `yt_picker_dismissed_during_scroll`.

### Recovery helper `_yt_try_reopen_picker`

Использует уже существующие `_yt_open_via_settings_activity` (line 2604) fallback и/или повторный `_yt_try_accounts_btn_with_retries` (line 2602 area). Single retry only — если оба пути проваливаются, fail fast (avoid infinite loop).

### Scroll-exit reason → distinct error codes

`_scroll_picker_for_target` возвращает `(found: bool, reason: str)` вместо просто `bool`. Reasons:
- `'found'` — target обнаружен (success path).
- `'exhausted'` — `stale_rounds >= max_stale` достигнут с picker present (true list-end reached).
- `'max_iter_no_stale'` — for-loop достигнул max-iteration cap без `stale_rounds >= max_stale` (long list, не доскролили). НЕ list-end proven.
- `'dismissed_unrecovered'` — picker dismissed (на любой iteration включая first), re-open attempted и не помог (или already used).

Caller mapping в emit-event branch:

| Scroll reason | Picker present after scroll? | Emitted RC |
|---|---|---|
| `'exhausted'` | ✓ yes | **`yt_picker_target_absent`** (data drift — list-end proved by stale=max_stale) |
| `'dismissed_unrecovered'` | ✗ no | **`yt_picker_dismissed`** (race, even на first iter — codex round 3 fix) |
| `'max_iter_no_stale'` | (any) | **`yt_target_not_in_picker_after_scroll`** (codex round 5 P2: max-iter ≠ list-end) |
| any other / fall-through | (any) | **`yt_target_not_in_picker_after_scroll`** (legacy catch-all; degraded mode, e.g. exhausted-but-picker-not-present) |

Codex round 1 P2 (2026-05-12): без proof-of-list-end (stale=max_stale), picker-present + target-absent могло бы быть **long list ещё не до конца проскролили**. Стало бы misleading triage. Теперь `yt_picker_target_absent` emit'ится **только** при `reason='exhausted'` — что guarantees stale-detection passed → list-end reached → target действительно absent.

## Implementation outline

```
account_switcher.py:

+ _YT_PICKER_MARKERS = ('Управление аккаунтами', 'Другие аккаунты', 'Аккаунт Google')

+ def _is_yt_picker_present(elements: list) -> bool:
      labels = [e.label.lower() for e in elements if e.label]
      txt = ' '.join(labels)
      if any(m.lower() in txt for m in _YT_PICKER_MARKERS):
          return True
      gmail_count = sum(1 for l in labels if '@gmail' in l)
      return gmail_count >= 2

+ def _sample_picker_diag(elements: list) -> dict:
      gmails, displays, handles = [], [], []
      for e in elements:
          lbl = e.label
          if not lbl: continue
          if '@gmail' in lbl.lower(): gmails.append(lbl[:120])
          if lbl.startswith('@'): handles.append(lbl[:80])
          if e.clickable: displays.append(lbl[:80])
      return {'gmails': gmails[:10], 'handles': handles[:10], 'displays': displays[:10]}

# inside class AccountSwitcher:

+ def _yt_try_reopen_picker(self, cfg: dict, step: str) -> bool:
      """One-shot re-open picker via fallback paths.
      
      Tries: (1) profile-tab navigate + Аккаунты button + dismiss login modal,
             (2) Shell_SettingsActivity intent fallback (per memory
                 reference_yt_accounts_settings_path).
      Returns True if picker visible after retry.
      """
      ...

# patch _scroll_picker_for_target (line 4261):
  + signature ADDS `cfg: dict, step: str` параметры (required для _yt_try_reopen_picker).
    Caller на line 2653 переходит на `self._scroll_picker_for_target(target, cfg, step='yt_4_pick_account_after_scroll')`.
  + return now (found: bool, reason: str)
  + reasons: 'found' | 'exhausted' | 'dismissed_unrecovered'
  + state: reopened = False, scroll-iteration loop unchanged otherwise
  + at start of each iteration (incl. first) — after parse_ui_dump:
        if NOT _is_yt_picker_present(elements):
            log_event('warning', f'yt_picker_dismissed_during_scroll: attempt={attempt}',
                      meta={'category': 'yt_picker_dismissed_during_scroll',
                            'attempt': attempt,
                            'picker_diag': _sample_picker_diag(elements)})
            if reopened:
                # bounded — already used our one reopen attempt
                return (False, 'dismissed_unrecovered')
            reopened = True
            if self._yt_try_reopen_picker(cfg, step):
                stale_rounds = 0; seen_keys = set()
                continue        # fresh state, loop again
            return (False, 'dismissed_unrecovered')
        # picker present — normal find/scroll logic continues
  + on target match → return (True, 'found')
  + on stale_rounds >= max_stale exit → return (False, 'exhausted')   # list-end proven
  + on for-loop fall-through (max-iter cap, list still moving) → return (False, 'max_iter_no_stale')
    # Codex round 5 P2: max-iter ≠ list-end. Caller treats этот reason как legacy
    # `yt_target_not_in_picker_after_scroll`, не data drift.

Codex round 3 P2 fix: первый dump НЕ off-picker special-case'ится более. Любая dismissed state (на first iter или later) проходит через unified reopen path. Tests 9-11 (mock video-player на attempt 1) expect reopen attempt — unified path обеспечивает это.

# patch caller at line 2648-2669 (after scroll loop, before yt_target_not_in_picker_after_scroll):
  is_youtube = cfg.get('package') == 'com.google.android.youtube'
  if is_youtube:
      found, scroll_reason = self._scroll_picker_for_target(
          target, cfg, step='yt_4_pick_account_after_scroll')
      if found:
          ok = self._find_and_tap_account(target, cfg, step='yt_4_pick_account_after_scroll')
      else:
          # split umbrella error по reason
          fresh_xml = self.p.dump_ui(retries=1)
          fresh_elements = parse_ui_dump(fresh_xml) if fresh_xml else []
          picker_present_after = _is_yt_picker_present(fresh_elements)
          diag = _sample_picker_diag(fresh_elements) if fresh_elements else {}

          if scroll_reason == 'exhausted' and picker_present_after:
              # Codex round 1 P2 + round 2 P2 (gate target_absent на reason+picker presence)
              self.p.log_event('error',
                  f'yt_picker_target_absent: target={target!r} '
                  f'picker_accounts={diag.get("gmails",[])[:3]}',
                  meta={'category': 'yt_picker_target_absent',
                        'reason': 'yt_picker_target_absent',
                        'target': target,
                        'gmail': self._yt_target_gmail or None,
                        'scroll_reason': scroll_reason,
                        'picker_diag': diag})
          elif scroll_reason == 'dismissed_unrecovered':
              self.p.log_event('error',
                  f'yt_picker_dismissed: target={target!r} scroll_reason={scroll_reason}',
                  meta={'category': 'yt_picker_dismissed',
                        'reason': 'yt_picker_dismissed',
                        'target': target,
                        'gmail': self._yt_target_gmail or None,
                        'scroll_reason': scroll_reason,
                        'picker_diag': diag})
          else:
              # Legacy catch-all: exhausted-but-picker-not-present, or fall-through
              # (shouldn't normally happen, but degrade-to-pass instead of silence).
              self.p.log_event('error',
                  f'yt_target_not_in_picker_after_scroll: target={target!r} '
                  f'gmail={self._yt_target_gmail or None}',
                  meta={'category': 'yt_target_not_in_picker_after_scroll',
                        'reason': 'yt_target_not_in_picker_after_scroll',
                        'target': target,
                        'gmail': self._yt_target_gmail or None,
                        'scroll_reason': scroll_reason,
                        'picker_present_after': picker_present_after,
                        'picker_diag': diag})
          return self._fail(f"аккаунт {target!r} не привязан к устройству",
                            step='yt_4_pick_account')
```

## Test plan

### Unit tests (`test_yt_picker_state_guard.py`)

1. `test_is_picker_present_with_marker` — element с 'Управление аккаунтами' → True.
2. `test_is_picker_present_with_2_gmails` — 2 elements с @gmail labels → True.
3. `test_is_picker_present_with_1_gmail` — 1 @gmail only → False.
4. `test_is_picker_present_empty` — empty elements → False.
5. `test_is_picker_present_video_player` — fixture from task 3970 fail dump → False.
6. `test_is_picker_present_recents_tray` — fixture from task 5054 fail dump → False.
7. `test_is_picker_present_picker_open` — fixture from task 3970 retry1 (real picker) → True.
8. `test_sample_picker_diag_extracts_gmails_handles_displays` — fixture проверяет shape `{gmails, handles, displays}`.

### Integration tests (`test_yt_picker_dismissed_recovery.py`)

9. `test_scroll_detects_dismissed_logs_event` — mock dump_ui returning video-player XML on attempt 1 → expect `yt_picker_dismissed_during_scroll` event + `_yt_try_reopen_picker` called (Codex round 3 P2: даже на first iteration, reopen attempted).
10. `test_scroll_recovers_after_reopen` — first dump = video player; mocked reopen returns True; second dump = picker with target → expect `('found', 'found')` return.
11. `test_scroll_fails_after_failed_reopen` — first dump video; reopen → False → expect `(False, 'dismissed_unrecovered')` (no 9 wasted scrolls).
12. `test_caller_emits_target_absent_when_picker_present_but_target_not` — picker dump без target → expect `yt_picker_target_absent` event with `picker_diag` meta.
13. `test_caller_emits_dismissed_when_picker_not_present_at_end` — final dump = video → expect `yt_picker_dismissed` event.
14. `test_legacy_yt_target_not_in_picker_after_scroll_kept_for_edge_cases` — both new conditions false (degenerate fixture) → legacy event still emitted (degrade-to-old).

### Live verify

- Sample task replay (на тех же phones) если phones available — посмотреть что новые error codes появляются. Идеально — induce picker dismiss via `am start com.android.settings/.RecentsActivity` shortly after Аккаунты tap.
- 24h soak: SQL count
  ```sql
  SELECT events->-1->'meta'->>'category', COUNT(*)
  FROM publish_tasks
  WHERE platform='YouTube'
    AND created_at >= NOW() - INTERVAL '24 hours'
    AND status='failed'
  GROUP BY 1 ORDER BY 2 DESC;
  ```
  Expected: `yt_target_not_in_picker_after_scroll` count drops (replaced by new RCs), `yt_picker_dismissed*` + `yt_picker_target_absent` появляются.

## Rollout / kill-switch

- **Single PR** в prod-репо ветке `fix-yt-picker-state-guard-20260512`.
- **No feature flag** — defensive logging/event-split fix. Re-open attempts is bounded (max 1 per scroll), so worst-case extra latency = одна tap + 1 dump_ui (~3s) и фейл не хуже current.
- **Rollback:** `git revert` + auto-push.
- **Mid-flight kill:** даже не нужен — без feature flag, fail-modes только лучше observable.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `_is_yt_picker_present` false-positive (другие YT screens с 2+ gmails) | Low | Marker 'Управление аккаунтами' / 'Другие аккаунты' — YT-picker-specific. 2-gmails fallback покрывает edge cases. Tests 5-7 — fixture coverage. |
| `_yt_try_reopen_picker` infinite loop с broken phone | Low | `reopened=True` flag — at most 1 re-open per scroll call. |
| Existing tests depending на `yt_target_not_in_picker_after_scroll` event сломаются | Low | Legacy event kept для degenerate path (Layer 2 condition match). Cross-grep tests/ для name occurrence — likely 0 matches (event-name based assertions редко в текущих тестах). |
| Operator dashboards / triage tools tracking `yt_target_not_in_picker_after_scroll` потеряют traffic | Low | Document new RCs в evidence + triage docs. Server-side counter — `unique(category)` over time; analytics natural. |

## Open questions for Codex

1. Better marker для picker detection — есть ли resource-id который unambiguous (e.g. `com.google.android.youtube:id/account_picker_*`)?
2. Recovery — попытка только через `Аккаунты` button OR fall back на `Shell_SettingsActivity` если первая не сработала? Я склоняюсь к: try button first (preserves Аккаунты flow), fallback на Settings-Activity.
3. Diagnostic meta size — `picker_diag` каждое поле [:10] @120 chars — ~1.5KB. OK для events JSONB? (memory `project_publish_guard_schema` — events freely accumulate, no field-size limit).
4. Event count — emitting both `yt_picker_dismissed_during_scroll` (mid) AND `yt_picker_dismissed` (final) on same race → double counting. OR использовать только final?
