# WP#44 — TikTok honest+reliable caption fill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TikTok auto-publish must never post without a description: type the caption only when the field is confirmed focused, otherwise fail honestly (`tt_caption_field_not_focused`) and route the task to the manual queue.

**Architecture:** The TikTok caption field is Canvas-rendered and invisible to UIAutomator (no `EditText`/`focused`/text nodes), so the only Canvas-independent honesty signal is the IME state (`dumpsys input_method … mInputShown`). We extract the inline "Шаг 4" caption block out of the monolithic `publish_tiktok` into a testable `_fill_tiktok_caption` helper that gates `adb_text` on confirmed focus, emits honest telemetry, and is guarded by a kill-switch. The error code is mapped to the manual-routing path via the existing `_set_error_code_from_events` + `publish_error_codes` catalog (mirrors IG's `ig_caption_screen_not_reached`).

**Tech Stack:** Python (publisher mixins), pytest (+ `tt_mixin_stub` fixture), PostgreSQL (`publish_error_codes` catalog via `migrations/*.sql`), env kill-switch read at spawn.

---

## ⚠️ Repo & branch note (read first)

Two repos are involved:
- **Docs (this plan + spec):** `/home/claude-user/contenthunter`, branch `wp44-tt-caption-honest-fill` (worktree at `.claude/worktrees/wp44-tt-caption-honest-fill`).
- **CODE:** `/home/claude-user/autowarm-testbench` — a **separate** git repo (`origin = GenGo2/delivery-contenthunter`, currently on `main`). All code/migration/test edits below happen HERE.

**Before any code edit, create an isolated branch in the code repo** so parallel sessions are not disturbed:

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin && git checkout -b wp44-tt-caption-honest-fill origin/main
```

Do NOT commit on `main`, do NOT `--amend` shared HEAD, do NOT force-push. Deploy is a separate, explicit step (Task 7) via PM2 — `git push` to this remote reaches prod.

---

## File structure

| File | Repo | Responsibility |
|------|------|----------------|
| `migrations/20260529_wp44_tt_caption_field_not_focused.sql` (+ `__rollback.sql`) | autowarm-testbench | Add `tt_caption_field_not_focused` to `publish_error_codes` (class `ui_changed`, manual). |
| `publisher_tiktok.py` | autowarm-testbench | New `_tiktok_caption_field_focused()` + `_fill_tiktok_caption()` helpers; `publish_tiktok` Шаг-4 block replaced by a call that aborts on honest fail. |
| `tests/test_publisher_tt_caption_focus_gate.py` | autowarm-testbench | Unit tests for the focus-gate decision (focused→types; not-focused→honest fail, no `adb_text`; kill-switch OFF→legacy). |
| `.env.example` (if present) | autowarm-testbench | Document `TT_CAPTION_FOCUS_GATE_ENABLED`. |

---

## Task 1: Error-code catalog entry

**Files:**
- Create: `migrations/20260529_wp44_tt_caption_field_not_focused.sql`
- Create: `migrations/20260529_wp44_tt_caption_field_not_focused__rollback.sql`

- [ ] **Step 1: Write the forward migration**

```sql
-- WP #44: honest error code for TikTok caption fill — field never focused.
-- error_class=ui_changed → retry-engine routes straight to manual (operator
-- posts with description). Mirrors ig_caption_screen_not_reached (WP#140).
-- Idempotent: ON CONFLICT (code) DO UPDATE.
BEGIN;
INSERT INTO publish_error_codes
  (code, error_class, severity, retry_strategy, is_known, is_auto_fixable, description)
VALUES
  ('tt_caption_field_not_focused','ui_changed','error','manual',true,false,
   'Поле описания TikTok не сфокусировалось — описание не введено (честный фейл вместо слепой печати)')
ON CONFLICT (code) DO UPDATE
  SET error_class = EXCLUDED.error_class,
      severity = EXCLUDED.severity,
      retry_strategy = EXCLUDED.retry_strategy,
      is_known = EXCLUDED.is_known,
      is_auto_fixable = EXCLUDED.is_auto_fixable,
      description = EXCLUDED.description;
COMMIT;
```

- [ ] **Step 2: Write the rollback migration**

```sql
-- Rollback WP #44 caption error code.
BEGIN;
DELETE FROM publish_error_codes WHERE code = 'tt_caption_field_not_focused';
COMMIT;
```

- [ ] **Step 3: Apply forward migration to the autowarm DB**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /home/claude-user/autowarm-testbench/migrations/20260529_wp44_tt_caption_field_not_focused.sql
```
Expected: `INSERT 0 1` (or `UPDATE 1`), then `COMMIT`.

- [ ] **Step 4: Verify the row + class**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -t -c \
  "SELECT code, error_class, retry_strategy FROM publish_error_codes WHERE code='tt_caption_field_not_focused';"
```
Expected: `tt_caption_field_not_focused | ui_changed | manual`

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add migrations/20260529_wp44_tt_caption_field_not_focused.sql migrations/20260529_wp44_tt_caption_field_not_focused__rollback.sql
git commit -m "feat(wp44): add tt_caption_field_not_focused to publish_error_codes (ui_changed/manual)"
```

---

## Task 2: `_tiktok_caption_field_focused` focus-signal helper

**Files:**
- Modify: `publisher_tiktok.py` (add method to `TikTokMixin`, near `_is_keyboard_shown`/Шаг-4 area)
- Test: `tests/test_publisher_tt_caption_focus_gate.py`

- [ ] **Step 1: Write the failing test**

```python
"""WP#44 — TikTok caption focus-gate: type only when the field is confirmed
focused (IME shown). Canvas-rendered field is invisible to UIAutomator, so
IME state is the only Canvas-independent focus signal."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import publisher_tiktok  # noqa: E402


def test_focused_true_when_keyboard_node_present(tt_mixin_stub):
    s = tt_mixin_stub
    s._is_keyboard_shown = MagicMock(return_value=True)
    assert s._tiktok_caption_field_focused() is True


def test_focused_true_when_ime_dumpsys_reports_shown(tt_mixin_stub):
    s = tt_mixin_stub
    s._is_keyboard_shown = MagicMock(return_value=False)
    s.adb = MagicMock(return_value='mInputShown=true')
    assert s._tiktok_caption_field_focused() is True


def test_focused_false_when_neither_signal_present(tt_mixin_stub):
    s = tt_mixin_stub
    s._is_keyboard_shown = MagicMock(return_value=False)
    s.adb = MagicMock(return_value='mInputShown=false')
    assert s._tiktok_caption_field_focused() is False


def test_focused_false_when_other_true_flag_on_same_line(tt_mixin_stub):
    """mInputShown=false but another flag on the line is true → must NOT be
    treated as focused (codex P1: parse mInputShown specifically)."""
    s = tt_mixin_stub
    s._is_keyboard_shown = MagicMock(return_value=False)
    s.adb = MagicMock(return_value='mInputShown=false mSystemReady=true')
    assert s._tiktok_caption_field_focused() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_publisher_tt_caption_focus_gate.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_tiktok_caption_field_focused'`

- [ ] **Step 3: Write minimal implementation**

Add to `TikTokMixin` in `publisher_tiktok.py` (place just above `publish_tiktok`, near line 1684):

```python
    def _tiktok_caption_field_focused(self) -> bool:
        """True if the caption field is focused (soft keyboard / IME shown).

        TikTok renders the description field via Canvas/obfuscated classes —
        UIAutomator sees no EditText/focused/text node, so the IME state is
        the only Canvas-independent focus signal. Checks the UI dump for a
        keyboard package, then falls back to `dumpsys input_method`.
        """
        ui = self.dump_ui()
        if self._is_keyboard_shown(ui):
            return True
        ime = self.adb(
            'dumpsys input_method 2>/dev/null | grep -i "mInputShown" | head -1',
            timeout=5,
        ) or ''
        # Parse the mInputShown value specifically — a bare `true in line`
        # check false-positives when another `...=true` flag shares the line
        # (codex P1). Normalize spaces + case before matching.
        return 'minputshown=true' in ime.lower().replace(' ', '')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_publisher_tt_caption_focus_gate.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add publisher_tiktok.py tests/test_publisher_tt_caption_focus_gate.py
git commit -m "feat(wp44): _tiktok_caption_field_focused IME focus-signal helper + tests"
```

---

## Task 3: `_fill_tiktok_caption` — gate, honest fail, kill-switch

**Files:**
- Modify: `publisher_tiktok.py` (add `_fill_tiktok_caption` to `TikTokMixin`)
- Test: `tests/test_publisher_tt_caption_focus_gate.py` (append)

This method holds the navigation/field-tap logic moved out of `publish_tiktok` Шаг-4, but replaces the **unconditional** `adb_text` with a focus gate.

- [ ] **Step 1: Write the failing tests (append to the test file)**

```python
def _desc_screen_xml():
    # Minimal stand-in: contains a description-screen marker so the
    # navigation loop recognizes the screen on the first attempt.
    return '<hierarchy><node text="Добавьте описание" bounds="[40,240][1000,340]"/></hierarchy>'


def _fill_stub(tt_mixin_stub, monkeypatch, *, focused, caption='Описание ролика #тег'):
    s = tt_mixin_stub
    s.build_full_caption = lambda: caption
    s.dump_ui = MagicMock(return_value=_desc_screen_xml())
    s.tap_element = MagicMock(return_value=True)
    s._is_keyboard_shown = MagicMock(return_value=False)
    s._save_debug_artifacts = MagicMock()
    s._tiktok_caption_field_focused = MagicMock(return_value=focused)
    monkeypatch.setattr(publisher_tiktok.time, 'sleep', lambda _: None)
    return s


def test_fill_types_caption_when_focused(tt_mixin_stub, monkeypatch):
    s = _fill_stub(tt_mixin_stub, monkeypatch, focused=True)
    result = s._fill_tiktok_caption()
    assert result is True
    assert s.adb_text.called, 'adb_text должен вызываться при подтверждённом фокусе'


def test_fill_does_not_type_blindly_when_not_focused(tt_mixin_stub, monkeypatch):
    s = _fill_stub(tt_mixin_stub, monkeypatch, focused=False)
    result = s._fill_tiktok_caption()
    assert result is False, 'Должен честно вернуть False без фокуса'
    assert not s.adb_text.called, 'adb_text НЕ должен вызываться вслепую'


def test_fill_emits_honest_error_code_when_not_focused(tt_mixin_stub, monkeypatch):
    s = _fill_stub(tt_mixin_stub, monkeypatch, focused=False)
    s._fill_tiktok_caption()
    cats = [
        (c.kwargs.get('meta') or {}).get('category')
        for c in s.log_event.call_args_list
    ]
    assert 'tt_caption_field_not_focused' in cats, (
        f'Ожидали честный код в meta.category, получили: {cats}'
    )
    error_types = [c.args[0] for c in s.log_event.call_args_list if c.args]
    assert 'error' in error_types, 'Честный фейл должен быть событием типа error'


def test_fill_empty_caption_is_not_a_failure(tt_mixin_stub, monkeypatch):
    s = _fill_stub(tt_mixin_stub, monkeypatch, focused=False, caption='')
    result = s._fill_tiktok_caption()
    assert result is True, 'Пустой caption — нечего вводить, не фейл'
    assert not s.adb_text.called


def test_fill_killswitch_off_keeps_legacy_blind_type(tt_mixin_stub, monkeypatch):
    monkeypatch.setenv('TT_CAPTION_FOCUS_GATE_ENABLED', 'false')
    s = _fill_stub(tt_mixin_stub, monkeypatch, focused=False)
    result = s._fill_tiktok_caption()
    assert result is True, 'OFF → legacy: не валим задачу'
    assert s.adb_text.called, 'OFF → legacy: печатаем как раньше (экран описания найден)'


def test_fill_fails_when_focused_but_desc_screen_not_found(tt_mixin_stub, monkeypatch):
    """codex P1: IME может быть открыт на ДРУГОМ экране (поиск/иное поле).
    Без распознанного экрана описания печатать нельзя даже при focused=True."""
    s = _fill_stub(tt_mixin_stub, monkeypatch, focused=True)
    s.dump_ui = MagicMock(return_value='<hierarchy/>')  # нет маркеров экрана описания
    result = s._fill_tiktok_caption()
    assert result is False, 'Фокус без экрана описания → честный фейл'
    assert not s.adb_text.called, 'Не печатаем вне экрана описания'
    cats = [(c.kwargs.get('meta') or {}).get('category') for c in s.log_event.call_args_list]
    assert 'tt_caption_field_not_focused' in cats
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_publisher_tt_caption_focus_gate.py -v`
Expected: the 6 new tests FAIL — `AttributeError: ... '_fill_tiktok_caption'`

- [ ] **Step 3: Write the implementation**

Add to `TikTokMixin` in `publisher_tiktok.py` (just below `_tiktok_caption_field_focused`). This preserves the existing geolocation handling, description-screen detection, field tap (`tap_element`) and the fixed-coord fallback, but adds: kill-switch, a final **focus gate** before typing, and an honest failure path.

```python
    def _fill_tiktok_caption(self) -> bool:
        """Fill the TikTok description field. Returns True on success (or when
        nothing to type / kill-switch OFF), False on honest failure.

        WP#44: never type blindly. Type the caption ONLY when the field is
        confirmed focused (`_tiktok_caption_field_focused`). If focus is never
        confirmed, emit `tt_caption_field_not_focused` and return False so the
        caller aborts before sharing → task fails → manual queue.
        Kill-switch TT_CAPTION_FOCUS_GATE_ENABLED (default ON); OFF restores
        the legacy blind-type behavior for instant rollback.
        """
        import os
        gate_enabled = (
            os.environ.get('TT_CAPTION_FOCUS_GATE_ENABLED', 'true').lower() == 'true'
        )
        caption = self.build_full_caption()
        self.set_step('TikTok: экран описания (caption)')
        log.info(f'  Шаг 4: экран описания, caption={bool(caption)}, gate={gate_enabled}')

        if not caption:
            log.warning('  ⚠️ TikTok: caption пустой — описание не введено')
            self.log_event('warning', 'TikTok: caption пустой')
            return True  # nothing to fill — not a failure

        desc_found = False
        for attempt in range(6):
            ui = self.dump_ui()
            # Геолокация — закрываем
            if any(kw in ui for kw in ['Добавить местоположение', 'Искать места',
                                        'Функция недоступна', 'недоступна в вашем регионе']):
                log.warning(f'  ⚠️ Геолокация (попытка {attempt}) — Назад')
                self.adb('input keyevent KEYCODE_BACK')
                time.sleep(2); continue
            # Экран описания
            if any(kw in ui for kw in ['Добавьте описание', 'Caption', 'Описание',
                                        'Поделиться', 'Post', 'Приватность', 'Публично']):
                log.info(f'  ✅ Экран описания (попытка {attempt})')
                desc_found = True
                # clickable_only=False — поле рисуется через Canvas/WebView.
                field_tapped = self.tap_element(
                    ui, ['Добавьте описание', 'Caption', 'Описание'], clickable_only=False)
                if not field_tapped:
                    for _dc in [(540, 290), (540, 350), (540, 400), (540, 250)]:
                        log.warning(f'  Поле описания не найдено UIAutomator — fallback tap {_dc}')
                        self.log_event('info', f'TikTok: поле описания — fallback tap {_dc}')
                        self.adb_tap(*_dc)
                        time.sleep(1.5)
                        if self._tiktok_caption_field_focused():
                            log.info(f'  ✅ Поле сфокусировано (tap {_dc})')
                            break
                        log.warning(f'  Клавиатура не открылась после tap {_dc}')
                else:
                    time.sleep(1.5)
                break
            log.info(f'  Шаг 4 попытка {attempt}: UI={ui[:80]}')
            time.sleep(2)

        # === WP#44 focus gate ===
        # Success requires BOTH: the description screen was recognized AND the
        # field is confirmed focused. Focus alone is insufficient — the IME may
        # be open on another screen (search/other field), which would recreate
        # the blind-type bug (codex P1).
        focused = self._tiktok_caption_field_focused()
        if desc_found and focused:
            self.adb_text(caption)
            time.sleep(1)
            log.info(f'  ✅ TikTok: caption введён (фокус подтверждён, {len(caption)} символов)')
            self.log_event('info', f'TikTok: caption введён (фокус подтверждён, {len(caption)} символов)')
            return True

        if not gate_enabled:
            # Legacy behavior (kill-switch OFF): restore the prior path —
            # typed when the desc screen was found (regardless of focus) and
            # never aborted publishing.
            if desc_found:
                self.adb_text(caption)
                time.sleep(1)
                log.warning(f'  ⚠️ TikTok: caption введён БЕЗ подтверждения фокуса (gate OFF, {len(caption)} символов)')
                self.log_event('warning', 'TikTok: caption введён без подтверждения фокуса (gate OFF)')
            else:
                log.warning('  Шаг 4: экран описания не найден — продолжаем без caption (gate OFF)')
            return True

        # Gate ON and not (desc_found AND focused) → honest fail, no blind type.
        log.error('  ❌ TikTok: экран описания/фокус не подтверждены — НЕ печатаем вслепую (честный фейл)')
        self.log_event(
            'error',
            'TikTok: поле описания не сфокусировано — описание не введено',
            meta={
                'category': 'tt_caption_field_not_focused',
                'desc_screen_found': desc_found,
            },
        )
        try:
            self._save_debug_artifacts()
        except Exception:
            pass
        return False
```

> Note: if `_save_debug_artifacts` does not exist on `TikTokMixin`, drop the `try/_save_debug_artifacts` block — it is best-effort post-mortem evidence only and not required for the gate. Verify with `grep -n "_save_debug_artifacts" publisher_tiktok.py publisher_base.py` before keeping it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_publisher_tt_caption_focus_gate.py -v`
Expected: 10 passed (4 from Task 2 + 6 here)

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add publisher_tiktok.py tests/test_publisher_tt_caption_focus_gate.py
git commit -m "feat(wp44): _fill_tiktok_caption focus-gate + honest tt_caption_field_not_focused + kill-switch"
```

---

## Task 4: Wire the helper into `publish_tiktok` (abort on honest fail)

**Files:**
- Modify: `publisher_tiktok.py:1872-1928` (the inline Шаг-4 block)

- [ ] **Step 1: Replace the inline Шаг-4 block with a call + abort**

Delete the entire current block from `# === Шаг 4: Заполняем описание ===` (line ~1872) through `log.warning('  Шаг 4: экран описания не найден — продолжаем без caption')` (line ~1928), and replace with:

```python
        # === Шаг 4: Заполняем описание (WP#44 focus-gated) ===
        if not self._fill_tiktok_caption():
            # Honest fail already logged (tt_caption_field_not_focused).
            # Abort BEFORE share so we never post without a description.
            log.error('  ❌ TikTok: описание не введено — прерываем публикацию (в ручную)')
            return False
```

Leave the existing `# === Шаг 5: ...` block immediately after, untouched.

- [ ] **Step 2: Verify the module imports and no syntax error**

Run: `cd /home/claude-user/autowarm-testbench && python -c "import publisher_tiktok; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: Verify the old unconditional-type path is gone**

Run: `cd /home/claude-user/autowarm-testbench && grep -n "продолжаем без caption" publisher_tiktok.py`
Expected: no output (the old silent-continue path is removed).

- [ ] **Step 4: Run the focus-gate test suite again (regression check)**

Run: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_publisher_tt_caption_focus_gate.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add publisher_tiktok.py
git commit -m "feat(wp44): wire _fill_tiktok_caption into publish_tiktok — abort before share on honest fail"
```

---

## Task 5: Document the kill-switch

**Files:**
- Modify: `.env.example` (autowarm-testbench) — only if the file exists

- [ ] **Step 1: Check whether `.env.example` exists**

Run: `cd /home/claude-user/autowarm-testbench && ls .env.example 2>/dev/null && grep -n "TT_.*_ENABLED" .env.example | head`
If it does not exist, SKIP this task (the flag defaults to ON in code; no doc file to update).

- [ ] **Step 2: Append the flag with its default**

Add near the other `TT_*` flags:

```bash
# WP#44: focus-gate for TikTok caption. ON = never type blindly; honest fail
# (tt_caption_field_not_focused) -> manual queue when field is not focused.
# OFF = legacy blind-type behavior (instant rollback without redeploy).
TT_CAPTION_FOCUS_GATE_ENABLED=true
```

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add .env.example
git commit -m "docs(wp44): document TT_CAPTION_FOCUS_GATE_ENABLED kill-switch"
```

---

## Task 6: codex review + broader test run

- [ ] **Step 1: Run the full TT publisher test subset**

Run:
```bash
cd /home/claude-user/autowarm-testbench
python -m pytest tests/ -k "tiktok or tt_ or caption" -q
```
Expected: all pass (no regressions in neighboring TT/caption suites).

- [ ] **Step 2: codex review the diff (rounds until 0 P1)**

Run:
```bash
cd /home/claude-user/autowarm-testbench
git diff origin/main...HEAD | ~/.local/bin/codex review -
```
Address any P1 findings, re-run, repeat until 0 P1. (Bubblewrap warning is benign; `--base main` is known-broken — use the `git diff | codex review -` form.)

- [ ] **Step 3: Commit any review fixes**

```bash
cd /home/claude-user/autowarm-testbench
git add -A && git commit -m "fix(wp44): address codex review findings"
```

---

## Task 7: Deploy (PM2) + verify

> Operational, not TDD. Requires the prod autowarm checkout, not the testbench. Deploy = prod pull, NOT a push to a dev remote. Confirm prod path before acting.

- [ ] **Step 1: Apply the migration to prod DB** (same autowarm DB — already done in Task 1 Step 3 if this DB is prod; otherwise run the forward migration against the prod openclaw DB).

- [ ] **Step 2: Land the code on prod autowarm** per the project's standard flow (merge `wp44-tt-caption-honest-fill` → `main`, prod pulls; or cherry-pick). Verify the running PM2 process picks up the new module (`pm2 describe <app> | grep "exec cwd"` to confirm path; restart the autowarm app so the module reloads).

- [ ] **Step 3: Confirm the flag is ON in prod `.env`** (default ON; explicit `TT_CAPTION_FOCUS_GATE_ENABLED=true` optional — read at spawn via `load_dotenv`).

- [ ] **Step 4: Verify on the morning batch**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
WITH t AS (
  SELECT id, events::text AS et, error_code FROM publish_tasks
  WHERE created_at >= CURRENT_DATE AND platform='TikTok')
SELECT
  count(*) AS tt_tasks,
  count(*) FILTER (WHERE et ILIKE '%фокус подтверждён%') AS caption_confirmed,
  count(*) FILTER (WHERE error_code='tt_caption_field_not_focused') AS honest_fail,
  count(*) FILTER (WHERE et ILIKE '%caption введён%' AND et NOT ILIKE '%фокус подтверждён%') AS legacy_blindtype
FROM t;"
```
Success criteria: `legacy_blindtype = 0`; `caption_confirmed + honest_fail` ≈ all TT tasks; Anastasia spot-checks real posts → descriptions present. Watch `honest_fail` volume — if it floods the manual queue, that confirms the field-targeting needs more work (next iteration), but no posts go out without a description.

---

## Self-review notes

- **Spec coverage:** focus-gate (§1)→Task 2/3; better targeting (§2, tap_element + fallback retained, focus-checked per coord)→Task 3; honest fail→manual (§3)→Task 1+3+4; telemetry truth (§4)→Task 3 (focus-confirmed vs error events; old unconditional log removed in Task 4); kill-switch (§5)→Task 3+5; tests+codex (§6)→Task 2/3/6; deploy (§7)→Task 7. All spec sections mapped.
- **Type/name consistency:** `_tiktok_caption_field_focused()` and `_fill_tiktok_caption()` used identically in Tasks 2/3/4; error code `tt_caption_field_not_focused` identical in migration (Task 1), helper (Task 3), and verify query (Task 7); flag `TT_CAPTION_FOCUS_GATE_ENABLED` identical in Task 3/5/7.
- **Scope:** TikTok only — IG/YT untouched.
