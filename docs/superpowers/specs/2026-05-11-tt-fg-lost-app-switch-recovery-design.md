# TT fg-lost app-switch recovery — design spec v1

**Date:** 2026-05-11
**Status:** Draft (awaiting Codex review)
**Related:** PR #28 (music-rights handler), PR #34 (post-switch recovery)

## Problem

В `publisher_tiktok.py:984+` outer wait-upload loop (после `Share`-tap) детектит overlay-package — package, занимающий foreground, отличный от `com.zhiliaoapp.musically`. Используется `dismiss_overlay_dialogs` (publisher_base.py:489) — но он handle'ит только **dialog-level overlays** (Rate/Review, Samsung "Добавить виджет", обновления). Когда foreground улетает в **full Activity** (Samsung Launcher / Samsung Camera / etc.) — dismiss НЕ помогает, overlay_streak растёт до 3, фейл с категорией `tt_fg_lost` (`publisher_tiktok.py:1048`).

### Evidence (2026-05-11 discovery)

2 hit за 24ч, каждый — 10-15 минут dwell в AI Unstuck loop:

**Pt 4523 (2026-05-10 19:33 → 19:55 UTC, account `clickpay_world`):**
- Stage: wait_upload (после Share-tap)
- 8 AI Unstuck cycles (11 мин) — "retry publishing button", "close add music popup", "dismiss unexpected popup"
- 3 overlay iter с `pkg=com.sec.android.app.launcher` (Samsung Launcher / home screen)
- `tt_fg_lost` → fail

**Pt 4624 (2026-05-11 08:22 → 08:27 UTC, account `clickpay_world`):**
- Stage: caption fill (3× FALLBACK blind-tap publish coords при `ai_find_tap_no_coords`)
- 4 AI Unstuck cycles (5 мин)
- 3 overlay iter с `pkg=com.sec.android.app.camera` (Samsung Camera)
- `tt_fg_lost` → fail

**Common mechanism:**
1. AI Unstuck / blind FALLBACK coords тапают в edge UI зону (status bar / nav buttons / shortcuts)
2. Tap триггерит app-switch → Samsung Launcher / Samsung Camera / etc выходит на foreground
3. `dismiss_overlay_dialogs` не handle'ит app-switch (это не dialog) — overlay_streak grows
4. После 3 iter → `tt_fg_lost` фейл (с потерей всех TikTok publish state).

### Misnomer note

Memory `project_publish_followups_2026_05_06.md` упоминал `tt_fg_lost` как "downstream music-rights" — это **неверно**. Pt 4523's AI Unstuck text mentioned "close add music popup" но это была попытка AI Unstuck (semantic intent), не event from music-rights handler. Pattern — generic AI Unstuck → app-switch, не music-rights specific.

## Goals

1. **Reactive recovery:** при detection foreground = non-TikTok pkg → попытаться вернуть TT через `monkey -p com.zhiliaoapp.musically ... LAUNCHER 1` (reorder-to-front, без cold-start). 1 attempt per task, reset overlay_streak.
2. **Observability:** новые event categories `tt_fg_recovery_attempt` (info) и `tt_fg_recovery_success` (info) / `tt_fg_recovery_failed` (warning) для measuring recovery rate.
3. **Preserve existing fail path:** если recovery used & failed (overlay_streak опять достигает 3 после recovery) → existing `tt_fg_lost` fail сохраняется.

## Non-goals

- Не trying to **prevent** root cause (edge-zone blind taps) — это Approach B/C из brainstorming, отложено в backlog.
- Не cold-restart TikTok (force-stop + start) — это потеряет publish state. Только reorder-to-front.
- Не менять `dismiss_overlay_dialogs` (publisher_base.py) — он handle'ит dialogs корректно, наш recovery — отдельный layer.
- Не вводить feature flag — recovery low-risk (worst case: NOOP если pkg уже TikTok через timing race).

## Approach A — reactive recovery в wait_upload loop

В `publisher_tiktok.py:984+` outer loop, в ветке "TikTok не активен" (~line 1000-1054), ПОСЛЕ existing `dismiss_overlay_dialogs` call и ПЕРЕД `overlay_streak >= 3` final-fail check:

1. Если overlay detected (`_pkg != 'com.zhiliaoapp.musically'`) И `_pkg != self._foreground_recovery_pkg_skip` (см. exceptions) И recovery ещё не attempted в этом task:
   - Log `tt_fg_recovery_attempt` event с meta {`overlay_pkg`: _pkg, `overlay_streak`: <current>, `step`: 'wait_upload'}.
   - Exec `monkey -p com.zhiliaoapp.musically -c android.intent.category.LAUNCHER 1`.
   - Sleep 2.5 секунды (TT redraws).
   - Re-check foreground через `_read_foreground_pkg()`.
   - Если `_pkg == 'com.zhiliaoapp.musically'`:
     - Log `tt_fg_recovery_success` event.
     - Reset `overlay_streak = 0`.
     - Set `_tt_fg_recovery_attempted = True` (per-task flag).
     - `continue` outer loop.
   - Если recovery не подтвердился (`_pkg` всё ещё non-TT):
     - Log `tt_fg_recovery_failed` event.
     - Set `_tt_fg_recovery_attempted = True`.
     - Не reset streak — продолжаем в текущий iter; если опять overlay → `tt_fg_lost` fail.

2. Если recovery уже attempted в этом task — skip recovery, обычное behavior (dismiss + streak count).

### Exclusion (`_foreground_recovery_pkg_skip`)

Если `_pkg == 'com.android.permissioncontroller'` — это Android runtime permission dialog (могут быть legitimate cases). Recovery не пытается тут — позволяем existing Tier 1 retry (или AI Unstuck) handle. Это narrow exception; могут добавиться в backlog.

## File map

**Modify (deploy tree):**
- `publisher_tiktok.py` — расширить overlay branch в outer wait_upload loop (~line 1000-1054). Добавить state attr `_tt_fg_recovery_attempted` в class init (или lazy `if not hasattr...`). Добавить helper `_attempt_tt_fg_recovery(overlay_pkg, overlay_streak) -> bool`.

**Create (deploy tree):**
- `tests/test_tt_fg_recovery.py` — TDD tests.

**No changes:**
- `publisher_base.py:dismiss_overlay_dialogs` — остаётся как есть.
- `publisher_kernel.py` — `tt_fg_lost` уже мапится корректно (existing).
- AI Unstuck logic — за scope этого spec.

## Pseudo-code

```python
# publisher_tiktok.py, в outer wait_upload loop около line 1019-1052

# (existing dismiss_overlay_dialogs call осталось как есть)

# NEW [tt_fg_recovery 2026-05-11]: app-switch recovery перед streak fail-out.
if (_pkg != 'com.zhiliaoapp.musically'
    and _pkg != 'com.android.permissioncontroller'
    and not getattr(self, '_tt_fg_recovery_attempted', False)):
    if self._attempt_tt_fg_recovery(_pkg, overlay_streak):
        overlay_streak = 0
        continue
    # recovery failed → fall through to existing streak >= 3 check

# existing final-fail check
if overlay_streak >= 3:
    ...
    self.log_event('error', f'TikTok: не активен {overlay_streak} итераций, overlay pkg={_pkg}',
                    meta={'category': 'tt_fg_lost', ...})
    break
```

### Helper

```python
def _attempt_tt_fg_recovery(self, overlay_pkg: str, overlay_streak: int) -> bool:
    """[tt_fg_recovery 2026-05-11] Попытаться вернуть TT на foreground.

    Используется в wait_upload loop когда foreground улетел в non-TT pkg
    (Samsung Launcher / Camera / etc) после AI Unstuck / blind-tap. Один
    attempt per task. Не делает cold-restart (publish state сохраняется).

    Returns: True если TT вернулся на foreground, False иначе.
    """
    self.log_event(
        'info', f'TikTok fg-lost: recovery attempt (pkg={overlay_pkg})',
        meta={'category': 'tt_fg_recovery_attempt',
              'platform': self.platform, 'step': 'wait_upload',
              'overlay_pkg': overlay_pkg, 'overlay_streak': overlay_streak},
    )
    self.adb('monkey -p com.zhiliaoapp.musically '
             '-c android.intent.category.LAUNCHER 1')
    time.sleep(2.5)
    fg_pkg = self._read_foreground_pkg() or ''
    self._tt_fg_recovery_attempted = True

    if fg_pkg == 'com.zhiliaoapp.musically':
        self.log_event(
            'info', 'TikTok fg-lost: recovery success — TT back on foreground',
            meta={'category': 'tt_fg_recovery_success',
                  'platform': self.platform, 'step': 'wait_upload',
                  'recovered_from_pkg': overlay_pkg},
        )
        return True

    self.log_event(
        'warning', f'TikTok fg-lost: recovery failed — fg={fg_pkg!r}',
        meta={'category': 'tt_fg_recovery_failed',
              'platform': self.platform, 'step': 'wait_upload',
              'overlay_pkg': overlay_pkg, 'after_recovery_pkg': fg_pkg},
    )
    return False
```

`_read_foreground_pkg` уже существует (publisher_tiktok.py — есть аналог в `_read_foreground_pkg_full` в account_switcher.py:3452). Если нет в `publisher_tiktok.py` directly — добавить thin wrapper или использовать existing `topResumedActivity` parsing аналогично текущей code.

## Event taxonomy

| Name (= category) | type | When emitted | Meta fields |
|---|---|---|---|
| `tt_fg_lost` | error | existing — overlay_streak ≥ 3 (recovery already attempted or non-bad-pkg case) | overlay_pkg, overlay_streak, platform |
| `tt_fg_recovery_attempt` | info | new — recovery triggered (1st bad-pkg detection) | overlay_pkg, overlay_streak, step |
| `tt_fg_recovery_success` | info | new — `monkey` reorder вернул TT на foreground | recovered_from_pkg, step |
| `tt_fg_recovery_failed` | warning | new — после `monkey` TT всё ещё не на foreground | overlay_pkg, after_recovery_pkg, step |

## Tests (TDD order)

`tests/test_tt_fg_recovery.py`:

1. **test_attempt_recovery_success_returns_true** — mock `adb` (для monkey), `_read_foreground_pkg` returns 'com.zhiliaoapp.musically' после; assert returns True, `tt_fg_recovery_success` event emitted, `_tt_fg_recovery_attempted=True`.

2. **test_attempt_recovery_failed_returns_false** — `_read_foreground_pkg` всё ещё returns 'com.sec.android.app.launcher' после monkey; assert returns False, `tt_fg_recovery_failed` event emitted.

3. **test_attempt_recovery_emits_attempt_event** — assert `tt_fg_recovery_attempt` event emitted с правильными meta (overlay_pkg, overlay_streak).

4. **test_attempt_recovery_sets_attempted_flag** — после call, `_tt_fg_recovery_attempted == True` (даже если failed).

5. **test_attempt_recovery_monkey_command_used** — assert `adb` mock called с string containing `'monkey -p com.zhiliaoapp.musically'`.

Integration loop test deferred (existing wait_upload loop тяжело unit-тестировать; smoke on phone #19 в Definition of Done).

## Rollout

**No feature flag** — это reactive recovery (worst case: NOOP). Straight deploy:
1. PR merge → auto-push hook → prod (PM2 restart).
2. Через 24h SQL queries (см. ниже).

**Verify path (24h post-deploy):**
- ≥1 event `tt_fg_recovery_success` за 24h → recovery работает на real traffic
- Доля: `tt_fg_recovery_success / tt_fg_recovery_attempt` (recovery rate)
- `tt_fg_lost` count за 24h vs baseline 2/24h — expect drop

**Rollback:** `git revert` 1 коммита если recovery вызывает unexpected regressions (very unlikely — additive, no behavior change в happy path).

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `monkey` reorder fails (TT process killed by Android memory pressure) | Low | Recovery returns False → existing tt_fg_lost fail path. Cold-restart НЕ в scope (теряем state). |
| `_read_foreground_pkg` returns stale data — false-positive success | Low-Med | 2.5s sleep даёт TT redraw. Если flaky → расширим sleep или add 2-iter check в follow-up. |
| Recovery race condition: TT уже сам вернулся к моменту monkey call | Very Low | `monkey` to existing TT process is NOOP-like (reorder same activity). Не ломает. |
| Per-task flag `_tt_fg_recovery_attempted` persist между tasks через class re-use | None | Сбрасываем в loop start (или explicit init в publish-method start). Подтвердить в TDD. |
| `monkey` команда зависит от Samsung shell quirks | Low | Pattern уже используется широко в codebase. Если phone-specific fail — task-specific issue, not recovery. |

## Success metrics (24h post-deploy)

- ≥1 `tt_fg_recovery_success` event (recovery работает)
- `tt_fg_recovery_success` rate ≥ 50% от `tt_fg_recovery_attempt` (target reasonable)
- `tt_fg_lost` count за 24h drop > 0 (baseline 2/24h pre-deploy)

Если recovery_success ниже 30% — investigate: TT process killed too aggressively, может нужен cold-restart fallback (отдельный spec round).

## Open questions

Нет blocker'ов. Все ключевые решения зафиксированы в обсуждении 2026-05-11:
- Approach A (recovery в loop) — выбран
- 1 attempt + reset streak — выбран
- Monkey reorder (НЕ cold-start) — выбран

## References

- Memory:
  - `feedback_publisher_error_code_misleading.md` (error_code врёт без events.meta.category)
  - `feedback_codex_review_specs.md` (Codex round до 0 P1)
  - `reference_tt_activities_observed.md` (TT activity names)
- Evidence: pt 4523 events (clickpay_world, launcher overlay), pt 4624 events (clickpay_world, camera overlay)
- Code:
  - `publisher_tiktok.py:984-1054` — wait_upload loop (target wire-in)
  - `publisher_base.py:489` — `dismiss_overlay_dialogs` (unchanged)
  - `account_switcher.py:3452` — `_read_foreground_pkg_full` (similar pattern for ref)
