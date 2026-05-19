# YT create-menu foreground guard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть массовый YT publish-фейл `yt_create_menu_not_reached` (sourcedata 35/39 fails 2026-05-19) через 3-layer defense-in-depth в `_tap_plus_and_verify`: правильные координаты «+», pre-tap foreground recovery, post-tap foreground guard.

**Architecture:** Изменения локализованы в `/home/claude-user/autowarm-testbench/account_switcher.py` (1 cfg-строка + `_tap_plus_and_verify` инсерты). Используются существующие хелперы `_yt_ensure_foreground`, `_detect_foreground_pkg`, `_fail`. Kill-switch — env-var `YT_CREATE_MENU_GUARD_ENABLED` (default on). Tests — новый файл `tests/test_yt_create_menu_fg_guard.py` по существующему MagicMock pattern из `tests/test_yt_create_menu_strict_verify.py`.

**Tech Stack:** Python 3, pytest, unittest.mock.MagicMock; git/PR в `GenGo2/delivery-contenthunter`.

**Spec:** `docs/superpowers/specs/2026-05-19-yt-create-menu-fg-guard-design.md`

**Working directory for code changes:** `/home/claude-user/autowarm-testbench` (this is a SEPARATE git repo from contenthunter). All `git` and `pytest` commands below must be run with `cd /home/claude-user/autowarm-testbench`. Plan and spec markdown live in the contenthunter worktree.

---

## File Structure

**Modify (in /home/claude-user/autowarm-testbench):**
- `account_switcher.py:100` — YT `plus_button.coords` `(540, 2320)` → `(540, 2240)` (Layer A)
- `account_switcher.py:~205` (after `POST_TAP_WAIT_S = 1.2`) — add module-level helper `_guard_enabled()`
- `account_switcher.py:4156-4201` — `_tap_plus_and_verify`: Layer B pre-tap recovery, Layer C post-tap fg-guard

**Create (in /home/claude-user/autowarm-testbench):**
- `tests/test_yt_create_menu_fg_guard.py` — 6 unit tests (Layer B happy, Layer B fallback, Layer C recovery success, Layer C fail-fast, kill-switch, IG/TT regression-guard)

**Don't touch:**
- `tests/test_yt_create_menu_strict_verify.py` — existing tests must stay green (regression-guard against breaking the strict_verify legacy path)
- `tests/test_yt_post_switch_verify.py` — existing tests must stay green
- IG/TT cfg blocks in `UI_CONSTANTS` (only YT line 100 changes)

---

## Task 0: Branch setup in autowarm-testbench

**Files:** none (git only)

- [ ] **Step 1: Fetch & branch**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git status --short  # должно быть clean
git checkout -b feat/yt-create-menu-fg-guard origin/main
```

Expected: clean tree, new branch tracking from latest origin/main.

- [ ] **Step 2: Baseline pytest green**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_strict_verify.py tests/test_yt_post_switch_verify.py -v
```

Expected: all tests PASS. If any baseline test fails — STOP and report (don't fix pre-existing failures inside this work).

---

## Task 1: Layer A — fix YT plus_button coords (TDD)

**Files:**
- Modify: `account_switcher.py:100`
- Test: `tests/test_yt_create_menu_fg_guard.py` (create)

- [ ] **Step 1: Create test file with the failing assert**

Create `/home/claude-user/autowarm-testbench/tests/test_yt_create_menu_fg_guard.py`:

```python
"""WP #87 — Layer A/B/C tests for YT create-menu foreground guard."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

import account_switcher as _asw

PLATFORM_CFG = _asw.UI_CONSTANTS


def test_layer_a_yt_plus_button_coords_not_in_samsung_home():
    """Координаты YT '+' должны быть выше Samsung HOME (y=2317)."""
    coords = PLATFORM_CFG["YouTube"]["plus_button"]["coords"]
    assert coords == (540, 2240), (
        f"YT plus_button.coords должны быть (540, 2240), не {coords!r} "
        "((540, 2320) попадает в Samsung navigation HOME)"
    )
```

- [ ] **Step 2: Run test → FAIL**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_layer_a_yt_plus_button_coords_not_in_samsung_home -v
```

Expected: FAIL — current coords are `(540, 2320)`.

- [ ] **Step 3: Apply Layer A in `account_switcher.py:100`**

Replace:
```python
        'plus_button': {'coords': (540, 2320), 'desc': ['Создать', 'Create']},
```
with:
```python
        'plus_button': {'coords': (540, 2240), 'desc': ['Создать', 'Create']},
```

- [ ] **Step 4: Run test → PASS**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_layer_a_yt_plus_button_coords_not_in_samsung_home -v
```

Expected: PASS.

- [ ] **Step 5: Run existing tests → still green**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_strict_verify.py tests/test_yt_post_switch_verify.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add account_switcher.py tests/test_yt_create_menu_fg_guard.py
git commit -m "fix(yt): WP #87 Layer A — plus_button coords (540,2320)→(540,2240) — не в Samsung HOME"
```

---

## Task 2: Helper `_guard_enabled()` (TDD)

**Files:**
- Modify: `account_switcher.py` — add helper after `POST_TAP_WAIT_S` (~line 205)
- Test: `tests/test_yt_create_menu_fg_guard.py` (append)

- [ ] **Step 1: Add failing test**

Append to `tests/test_yt_create_menu_fg_guard.py`:

```python
def test_layer_d_guard_enabled_default_on(monkeypatch):
    """По умолчанию (env не задан) guard включён."""
    monkeypatch.delenv("YT_CREATE_MENU_GUARD_ENABLED", raising=False)
    assert _asw._guard_enabled() is True


def test_layer_d_guard_disabled_via_env(monkeypatch):
    monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", "0")
    assert _asw._guard_enabled() is False


def test_layer_d_guard_enabled_truthy_values(monkeypatch):
    """Любая непустая строка кроме '0' = on."""
    for v in ("1", "true", "yes"):
        monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", v)
        assert _asw._guard_enabled() is True, f"value={v!r} должен быть on"
```

- [ ] **Step 2: Run → FAIL (module-level _guard_enabled not defined)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py -v -k guard_enabled
```

Expected: FAIL with AttributeError.

- [ ] **Step 3: Add helper after `POST_TAP_WAIT_S = 1.2` (~line 204)**

Insert into `account_switcher.py` immediately after the `POST_TAP_WAIT_S` constant block (before next dataclass/section):

```python
def _guard_enabled() -> bool:
    """[WP #87] Kill-switch для yt_6_create_menu Layer B/C foreground guard.

    Default ON. Установите `YT_CREATE_MENU_GUARD_ENABLED=0` чтобы откатиться к
    legacy-behaviour (только Layer A — coord-fix — сохраняется, он не покрыт).
    """
    return os.environ.get('YT_CREATE_MENU_GUARD_ENABLED', '1') != '0'
```

- [ ] **Step 4: Run → PASS**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py -v -k guard_enabled
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add account_switcher.py tests/test_yt_create_menu_fg_guard.py
git commit -m "feat(yt): WP #87 Layer D — env kill-switch YT_CREATE_MENU_GUARD_ENABLED helper"
```

---

## Task 3: Layer B — pre-tap fg-recovery (TDD)

**Files:**
- Modify: `account_switcher.py:4167-4174` (block внутри `_tap_plus_and_verify`)
- Test: `tests/test_yt_create_menu_fg_guard.py` (append)

- [ ] **Step 1: Add helper for richer fake-proxy stub**

Append to `tests/test_yt_create_menu_fg_guard.py` (above tests, ~after imports):

```python
def _stub_switcher(dump_ui_returns=("<hierarchy/>",),
                   tap_element_returns=(True,),
                   ensure_fg_return=True,
                   detect_fg_return="com.google.android.youtube"):
    """Полноценный fake-proxy с side_effect-очередями.

    dump_ui_returns / tap_element_returns — кортежи возвращаемых значений;
    последний элемент остаётся sticky (MagicMock side_effect автоматом
    остановится; для устойчивости используем factory).
    """
    sw = _asw.AccountSwitcher.__new__(_asw.AccountSwitcher)
    sw.p = MagicMock()

    dump_iter = iter(dump_ui_returns)
    last_dump = dump_ui_returns[-1]
    def _dump(*a, **kw):
        try:
            return next(dump_iter)
        except StopIteration:
            return last_dump
    sw.p.dump_ui = MagicMock(side_effect=_dump)

    tap_iter = iter(tap_element_returns)
    last_tap = tap_element_returns[-1]
    def _tap(*a, **kw):
        try:
            return next(tap_iter)
        except StopIteration:
            return last_tap
    sw.p.tap_element = MagicMock(side_effect=_tap)

    sw.p.adb_tap = MagicMock()
    sw.p.log_event = MagicMock()
    sw.p.adb = MagicMock(return_value="")
    sw._save_dump = MagicMock()
    sw._maybe_screenshot = MagicMock()
    sw._yt_ensure_foreground = MagicMock(return_value=ensure_fg_return)
    sw._detect_foreground_pkg = MagicMock(return_value=detect_fg_return)
    sw._attempts = 0
    sw._screenshots = []
    sw._dumps = []
    return sw
```

- [ ] **Step 2: Add failing test for Layer B happy path**

Append:

```python
def test_layer_b_tap_element_miss_triggers_fg_recovery_then_retap(monkeypatch):
    """tap_element False → _yt_ensure_foreground → second tap_element True; нет fallback на coords."""
    monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", "1")
    # 3 dump_ui calls ожидаемы (initial, after ensure_fg, post-tap verify-pre + verify)
    # У нас side_effect — sticky на последнем; мы возвращаем валидный create-menu XML с триггером 'Видео'.
    create_menu_xml = '<hierarchy><node text="Видео"/></hierarchy>'
    sw = _stub_switcher(
        dump_ui_returns=(create_menu_xml,),
        tap_element_returns=(False, True),  # 1st miss, 2nd hit after recovery
        ensure_fg_return=True,
    )
    cfg = PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    assert sw._yt_ensure_foreground.called, "Layer B: _yt_ensure_foreground должен вызваться при miss"
    assert sw.p.tap_element.call_count == 2, "Должно быть 2 tap_element-попытки"
    assert sw.p.adb_tap.call_count == 0, "Не должно быть fallback на adb_tap при successful retap"
    # log_event для yt_plus_button_element_missing_fallback НЕ должен сработать
    for call in sw.p.log_event.call_args_list:
        cat = (call.kwargs.get("meta") or {}).get("category")
        assert cat != "yt_plus_button_element_missing_fallback", (
            "fallback-warning не должен генериться при successful retap"
        )
    assert result.success is True
```

- [ ] **Step 3: Run → FAIL (Layer B not implemented)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_layer_b_tap_element_miss_triggers_fg_recovery_then_retap -v
```

Expected: FAIL — `_yt_ensure_foreground.called` is False (current code skips it).

- [ ] **Step 4: Implement Layer B in `_tap_plus_and_verify`**

Replace lines `account_switcher.py:4167-4174` (the original `plus = cfg[...]` ... `self.p.adb_tap(*plus['coords'])` block) with:

```python
        plus = cfg['plus_button']
        ui = self.p.dump_ui()
        tapped = False
        if ui:
            tapped = self.p.tap_element(ui, plus['desc'], clickable_only=True)

        # Layer B [WP #87 2026-05-19]: при strict_verify (YT only) промах
        # tap_element означает что create-button недоступен на текущем экране.
        # Перед слепым fallback на coords попробуем восстановить YT foreground
        # и повторить element-tap; снижает шанс тапа по системному navbar.
        if not tapped and strict_verify and _guard_enabled():
            if self._yt_ensure_foreground(cfg, f'{step_prefix}_pre_tap_fg_recovery'):
                ui_retry = self.p.dump_ui(retries=1)
                if ui_retry:
                    tapped = self.p.tap_element(
                        ui_retry, plus['desc'], clickable_only=True)

        if not tapped:
            if strict_verify:
                # Observability: знаем что fallback на coords случился, даже после
                # recovery. Layer C ниже всё равно проверит foreground.
                self.p.log_event(
                    'warning', 'yt_plus_button_element_missing_fallback',
                    meta={'category': 'yt_plus_button_element_missing_fallback',
                          'step': f'{step_prefix}_plus',
                          'coords': list(plus['coords'])},
                )
            log.debug(f'[switcher] {step_prefix}_plus: fallback coords {plus["coords"]}')
            self.p.adb_tap(*plus['coords'])
```

- [ ] **Step 5: Run → PASS**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_layer_b_tap_element_miss_triggers_fg_recovery_then_retap -v
```

Expected: PASS.

- [ ] **Step 6: Run existing tests (regression)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_strict_verify.py -v
```

Expected: all PASS (Layer B has no effect when `tap_element` returns True — existing fixture).

- [ ] **Step 7: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add account_switcher.py tests/test_yt_create_menu_fg_guard.py
git commit -m "feat(yt): WP #87 Layer B — pre-tap _yt_ensure_foreground recovery до fallback на coords"
```

---

## Task 4: Layer B fallback observability (TDD)

**Files:**
- Test: `tests/test_yt_create_menu_fg_guard.py` (append)
- (Layer B implementation already in place from Task 3 — this task validates the fallback branch)

- [ ] **Step 1: Add failing test for the double-miss fallback path**

Append:

```python
def test_layer_b_double_miss_falls_back_to_safe_coords_with_warning(monkeypatch):
    """tap_element False оба раза → adb_tap(540, 2240) + warning event."""
    monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", "1")
    sw = _stub_switcher(
        dump_ui_returns=("<hierarchy/>",),
        tap_element_returns=(False,),  # always miss
        ensure_fg_return=True,
        detect_fg_return="com.google.android.youtube",  # fg ok, no Layer C fail
    )
    cfg = PLATFORM_CFG["YouTube"]
    sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    # adb_tap должен быть вызван с (540, 2240), не (540, 2320)
    sw.p.adb_tap.assert_called_with(540, 2240)
    # event yt_plus_button_element_missing_fallback должен быть залогирован
    cats = [
        (call.kwargs.get("meta") or {}).get("category")
        for call in sw.p.log_event.call_args_list
    ]
    assert "yt_plus_button_element_missing_fallback" in cats, (
        f"Expected fallback warning in events, got categories={cats!r}"
    )
```

- [ ] **Step 2: Run → PASS (Layer B already implemented)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_layer_b_double_miss_falls_back_to_safe_coords_with_warning -v
```

Expected: PASS (this validates the implementation from Task 3 also covers the fallback branch; if FAIL — diagnose before commit).

- [ ] **Step 3: Commit (test-only)**

```bash
cd /home/claude-user/autowarm-testbench
git add tests/test_yt_create_menu_fg_guard.py
git commit -m "test(yt): WP #87 Layer B fallback observability — adb_tap(540,2240) + warning event"
```

---

## Task 5: Layer C — post-tap fg-guard recovery success (TDD)

**Files:**
- Modify: `account_switcher.py:4175-4180` (block после `time.sleep(POST_TAP_WAIT_S + 1.0)`)
- Test: `tests/test_yt_create_menu_fg_guard.py` (append)

- [ ] **Step 1: Add failing test**

Append:

```python
def test_layer_c_post_tap_fg_drift_triggers_recovery_and_retap(monkeypatch):
    """После tap'а fg=launcher → _yt_ensure_foreground → retap → verify видит триггеры."""
    monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", "1")
    create_menu_xml = '<hierarchy><node text="Видео"/><node text="Прямой эфир"/></hierarchy>'
    sw = _stub_switcher(
        dump_ui_returns=(create_menu_xml,),
        tap_element_returns=(True, True),  # initial tap ok, retap after recovery ok
        ensure_fg_return=True,
        detect_fg_return="com.sec.android.app.launcher",  # drift!
    )
    cfg = PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    # _detect_foreground_pkg должен был вызваться (Layer C entry)
    assert sw._detect_foreground_pkg.called, "Layer C: fg-check должен выполняться"
    # _yt_ensure_foreground вызвался для post-tap recovery (хотя бы 1 раз с post_tap step)
    post_tap_calls = [
        c for c in sw._yt_ensure_foreground.call_args_list
        if 'post_tap' in (c.args[1] if len(c.args) > 1 else '')
    ]
    assert post_tap_calls, (
        f"Layer C должен вызвать _yt_ensure_foreground(*, '*post_tap*'), "
        f"got calls={sw._yt_ensure_foreground.call_args_list}"
    )
    # Должен быть warning event yt_create_menu_app_not_foregrounded
    cats = [
        (call.kwargs.get("meta") or {}).get("category")
        for call in sw.p.log_event.call_args_list
    ]
    assert "yt_create_menu_app_not_foregrounded" in cats
    # И в итоге success (recovery+retap+verify worked)
    assert result.success is True
```

- [ ] **Step 2: Run → FAIL (Layer C not implemented)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_layer_c_post_tap_fg_drift_triggers_recovery_and_retap -v
```

Expected: FAIL.

- [ ] **Step 3: Implement Layer C in `_tap_plus_and_verify`**

Find this block in `account_switcher.py` (right after Layer B; was around line 4175):

```python
        time.sleep(POST_TAP_WAIT_S + 1.0)
        self._save_dump(final_step, self.p.dump_ui(retries=1))
        self._maybe_screenshot(final_step)
```

Replace with:

```python
        time.sleep(POST_TAP_WAIT_S + 1.0)

        # Layer C [WP #87 2026-05-19]: при strict_verify проверяем что YT в
        # foreground'е перед чтением create-menu dump'а. Если drift на launcher
        # / другой app — пробуем recovery + один retap. Иначе fail-fast с
        # осмысленным error_code (не маскарад yt_create_menu_not_reached).
        if strict_verify and _guard_enabled():
            fg = self._detect_foreground_pkg()
            yt_pkg = cfg['package']
            if fg and fg != yt_pkg:
                self.p.log_event(
                    'warning', 'yt_create_menu_app_not_foregrounded',
                    meta={'category': 'yt_create_menu_app_not_foregrounded',
                          'step': final_step,
                          'foreground_pkg': fg,
                          'attempt': 1},
                )
                recovered = self._yt_ensure_foreground(
                    cfg, f'{final_step}_post_tap_fg_recovery')
                if recovered:
                    ui_r = self.p.dump_ui(retries=1)
                    retapped = False
                    if ui_r:
                        retapped = self.p.tap_element(
                            ui_r, plus['desc'], clickable_only=True)
                    if not retapped:
                        self.p.adb_tap(*plus['coords'])
                    time.sleep(POST_TAP_WAIT_S + 1.0)
                else:
                    return self._fail(
                        f'{final_step}: foreground={fg} после tap «+», '
                        f'_yt_ensure_foreground recovery не помог',
                        step=f'{final_step}_app_not_foregrounded',
                    )

        self._save_dump(final_step, self.p.dump_ui(retries=1))
        self._maybe_screenshot(final_step)
```

- [ ] **Step 4: Run → PASS**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_layer_c_post_tap_fg_drift_triggers_recovery_and_retap -v
```

Expected: PASS.

- [ ] **Step 5: Regression — existing strict_verify tests still green**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_strict_verify.py -v
```

Expected: PASS. In particular, `test_strict_verify_passes_when_triggers_present_on_create_menu` proves Layer C is no-op when fg=YouTube (existing fixture loads dump where the test stub returns `True` from `tap_element` and the cfg `package` matches the default mock).

Note: existing test stub uses `MagicMock()` for `sw.p`, and `_detect_foreground_pkg` is an instance method — if existing test exercises the new Layer C path, you may need to add `sw._detect_foreground_pkg = MagicMock(return_value='com.google.android.youtube')` to `_stub_switcher_with_dump` in `tests/test_yt_create_menu_strict_verify.py`. Allowed surgical edit ONLY if regression breaks — otherwise leave untouched.

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add account_switcher.py tests/test_yt_create_menu_fg_guard.py
git commit -m "feat(yt): WP #87 Layer C — post-tap foreground guard + recovery retap"
```

---

## Task 6: Layer C — fail-fast when recovery fails (TDD)

**Files:**
- Test: `tests/test_yt_create_menu_fg_guard.py` (append)
- (Layer C implementation already covers this — task validates the fail branch)

- [ ] **Step 1: Add failing test for the fail branch**

Append:

```python
def test_layer_c_recovery_fail_returns_fail_fast_with_new_error_code(monkeypatch):
    """fg=launcher и _yt_ensure_foreground False → _fail с шагом *_app_not_foregrounded."""
    monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", "1")
    sw = _stub_switcher(
        dump_ui_returns=("<hierarchy/>",),
        tap_element_returns=(True,),
        ensure_fg_return=False,  # recovery не помог
        detect_fg_return="com.sec.android.app.launcher",
    )
    cfg = PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    assert result.success is False
    assert result.final_step == "yt_6_create_menu_app_not_foregrounded", (
        f"Expected fail step yt_6_create_menu_app_not_foregrounded, got {result.final_step!r}"
    )
    # warning event тоже должен быть
    cats = [
        (call.kwargs.get("meta") or {}).get("category")
        for call in sw.p.log_event.call_args_list
    ]
    assert "yt_create_menu_app_not_foregrounded" in cats
```

- [ ] **Step 2: Run → PASS (Layer C from Task 5 covers this branch)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_layer_c_recovery_fail_returns_fail_fast_with_new_error_code -v
```

Expected: PASS. If FAIL — re-check Layer C implementation in Task 5 (specifically the `else: return self._fail(...)` branch and the `step=` value).

- [ ] **Step 3: Commit (test-only)**

```bash
cd /home/claude-user/autowarm-testbench
git add tests/test_yt_create_menu_fg_guard.py
git commit -m "test(yt): WP #87 Layer C fail-fast branch — yt_6_create_menu_app_not_foregrounded"
```

---

## Task 7: Kill-switch behaviour (TDD)

**Files:**
- Test: `tests/test_yt_create_menu_fg_guard.py` (append)

- [ ] **Step 1: Add failing test (если kill-switch off — Layer B/C ветки не выполняются)**

Append:

```python
def test_kill_switch_off_skips_layer_b_and_c(monkeypatch):
    """YT_CREATE_MENU_GUARD_ENABLED=0 → Layer B (fg-recovery) и Layer C (fg-check) skipped."""
    monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", "0")
    sw = _stub_switcher(
        dump_ui_returns=("<hierarchy/>",),
        tap_element_returns=(False,),  # promahnulsya — но recovery НЕ вызовется
        ensure_fg_return=True,
        detect_fg_return="com.sec.android.app.launcher",  # drift — но check skipped
    )
    cfg = PLATFORM_CFG["YouTube"]
    sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False, strict_verify=True,
    )
    assert sw._yt_ensure_foreground.call_count == 0, (
        "Layer B/C off: _yt_ensure_foreground не должен вызываться"
    )
    assert sw._detect_foreground_pkg.call_count == 0, (
        "Layer C off: _detect_foreground_pkg не должен вызываться"
    )
    # Layer A coord-fix всё равно применился: fallback на (540, 2240)
    sw.p.adb_tap.assert_called_with(540, 2240)
```

- [ ] **Step 2: Run → PASS (since helpers gated by `_guard_enabled()`)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_kill_switch_off_skips_layer_b_and_c -v
```

Expected: PASS.

- [ ] **Step 3: Commit (test-only)**

```bash
cd /home/claude-user/autowarm-testbench
git add tests/test_yt_create_menu_fg_guard.py
git commit -m "test(yt): WP #87 kill-switch off — Layer B/C skipped, Layer A applied"
```

---

## Task 8: IG/TT regression-guard (TDD)

**Files:**
- Test: `tests/test_yt_create_menu_fg_guard.py` (append)

- [ ] **Step 1: Add regression-guard test**

Append:

```python
def test_ig_tt_path_strict_verify_false_unchanged(monkeypatch):
    """strict_verify=False → ни Layer B, ни Layer C НЕ должны срабатывать (IG/TT legacy)."""
    monkeypatch.setenv("YT_CREATE_MENU_GUARD_ENABLED", "1")
    sw = _stub_switcher(
        dump_ui_returns=("<hierarchy/>",),
        tap_element_returns=(False,),  # miss
        ensure_fg_return=True,
        detect_fg_return="com.sec.android.app.launcher",  # drift
    )
    cfg = PLATFORM_CFG["YouTube"]
    sw._tap_plus_and_verify(
        cfg, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False,
        strict_verify=False,  # IG/TT path
    )
    assert sw._yt_ensure_foreground.call_count == 0, (
        "strict_verify=False (IG/TT): Layer B fg-recovery не должен вызываться"
    )
    assert sw._detect_foreground_pkg.call_count == 0, (
        "strict_verify=False (IG/TT): Layer C fg-check не должен вызываться"
    )
    # Также: НЕ должно быть warning event для fallback (только под strict_verify)
    cats = [
        (call.kwargs.get("meta") or {}).get("category")
        for call in sw.p.log_event.call_args_list
    ]
    assert "yt_plus_button_element_missing_fallback" not in cats, (
        "Warning event только под strict_verify"
    )
```

- [ ] **Step 2: Run → PASS**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_yt_create_menu_fg_guard.py::test_ig_tt_path_strict_verify_false_unchanged -v
```

Expected: PASS.

- [ ] **Step 3: Commit (test-only)**

```bash
cd /home/claude-user/autowarm-testbench
git add tests/test_yt_create_menu_fg_guard.py
git commit -m "test(yt): WP #87 IG/TT regression-guard — strict_verify=False bypasses Layer B/C"
```

---

## Task 9: Full pytest + codex review + push

**Files:** none (validation + git)

- [ ] **Step 1: Run all tests in repo (regression sweep)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/ -v 2>&1 | tail -40
```

Expected: all tests PASS. If any pre-existing test starts failing — STOP and diagnose (may indicate Layer B/C side-effect).

- [ ] **Step 2: Codex review of the full diff (per memory feedback_codex_review_specs)**

```bash
cd /home/claude-user/autowarm-testbench
git diff origin/main..HEAD | codex review -
```

Iterate (apply fixes as new commits, NOT amend) until codex returns 0 P1 findings or you can justify each P1 with explicit reasoning.

- [ ] **Step 3: Push branch**

```bash
cd /home/claude-user/autowarm-testbench
git push -u origin feat/yt-create-menu-fg-guard
```

- [ ] **Step 4: Open PR in GenGo2/delivery-contenthunter**

```bash
cd /home/claude-user/autowarm-testbench
set -a; . ~/secrets/github-gengo2.env; set +a
gh pr create --repo GenGo2/delivery-contenthunter \
  --base main --head feat/yt-create-menu-fg-guard \
  --title "fix(yt): WP #87 create-menu fg-guard — Layer A coord + Layer B/C foreground recovery" \
  --body "$(cat <<'EOF'
## Что было не так

35 из 39 YT publish-задач 2026-05-19 упали с `yt_create_menu_not_reached` (26) / `yt_editor_not_reached` (7).  Video-evidence (task 7726): после tap «+» YouTube свернулся в Samsung launcher, strict_verify прочитал дамп лончера и не нашёл create-menu triggers.

Root cause: `account_switcher.py:100` имел `'plus_button': {'coords': (540, 2320), ...}` — координата попадает в Samsung navigation HOME (y=2317), а не в YT bottom-nav «+» (y≈2240). При промахе `tap_element` fallback тапал по HOME.

## Что сделано

3-layer defense-in-depth в `_tap_plus_and_verify`:

- **Layer A:** YT `plus_button.coords` (540, 2320) → (540, 2240). Применяется всегда.
- **Layer B:** при `strict_verify` (YT only) промах tap_element → `_yt_ensure_foreground` + retry element-tap до fallback на coords. Если всё-таки fallback — warning event `yt_plus_button_element_missing_fallback`.
- **Layer C:** после tap'а проверяем foreground; если drift → recovery + один retap, или fail-fast с новым error_code `yt_create_menu_app_not_foregrounded`.
- **Layer D (kill-switch):** env `YT_CREATE_MENU_GUARD_ENABLED=0` откатывает Layer B/C (Layer A остаётся).

IG/TT (`strict_verify=False`) — поведение не меняется (regression-guard test).

## Test plan

- [ ] pytest tests/test_yt_create_menu_fg_guard.py — 9 новых тестов, все PASS
- [ ] pytest tests/test_yt_create_menu_strict_verify.py tests/test_yt_post_switch_verify.py — existing tests PASS
- [ ] Live smoke: после merge re-queue 3 свежих YT-fail задач, мониторить error_code на новые/исчезающие категории

EOF
)"
```

- [ ] **Step 5: Commit PR-URL into worktree evidence**

(Optional — only if PR opens successfully)

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/yt-publish-triage-2026-05-19
# Append PR URL to existing evidence file
```

---

## Task 10: Live smoke after merge

**Files:** none (DB + observation)

- [ ] **Step 1: Confirm prod deploy**

After PR merged into main, the autowarm prod auto-push hook deploys (memory: `reference_autowarm_git_hook`).

```bash
ls -la /root/.openclaw/workspace-genri/autowarm/account_switcher.py
grep "plus_button" /root/.openclaw/workspace-genri/autowarm/account_switcher.py | head -5
```

Expected: file modified time recent; coords `(540, 2240)`.

- [ ] **Step 2: PM2 restart**

```bash
sudo pm2 restart autowarm
sudo pm2 logs autowarm --lines 20 --nostream
```

Expected: clean restart, no traceback.

- [ ] **Step 3: Pick 3 stable YT-fail tasks for re-queue**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT pt.id, pt.account, pt.raspberry, pt.error_code
FROM publish_tasks pt
WHERE pt.platform='YouTube' AND pt.status='failed'
  AND pt.created_at >= '2026-05-19 00:00:00'::timestamp
  AND pt.error_code IN ('yt_create_menu_not_reached','yt_editor_not_reached')
ORDER BY pt.id DESC
LIMIT 3;
"
```

Pick the 3 returned task ids. Confirm raspberries are online and not OTA-blocked (memory: `feedback_ota_screen_blocks_adb_preflight`).

- [ ] **Step 4: Re-queue via publish_queue (memory: reference_publish_requeue_path)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
UPDATE publish_queue
SET status='pending', publish_task_id=NULL
WHERE publish_task_id IN (<id1>, <id2>, <id3>);
"
```

(Replace `<id1>`, `<id2>`, `<id3>` with the actual ids from Step 3. Do NOT update `publish_tasks` directly — dispatcher creates new pt on the 5-min poll.)

- [ ] **Step 5: Monitor outcomes (15-20 min)**

```bash
# Watch for new publish_tasks generated by dispatcher (5min poll)
watch -n 60 'PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "SELECT pt.id, pt.account, pt.status, pt.error_code, pt.post_url FROM publish_tasks pt WHERE pt.platform=\"YouTube\" AND pt.created_at >= NOW() - INTERVAL \"30 minutes\" ORDER BY pt.id DESC LIMIT 10;"'
```

Document outcomes:
- `done` + post_url not null — фикс работает.
- `failed` + `yt_create_menu_app_not_foregrounded` — Layer C сработал, root cause подтверждён, но recovery не вытащил (отдельный triage).
- `failed` + `yt_create_menu_not_reached` — Layer A/B/C обошлись, dialog/modal перекрыл create-menu (новый виток).
- `failed` + new category — investigate.

- [ ] **Step 6: Update OpenProject WP #87 with results**

Comment на WP #87 в house-style (memory: `feedback_openproject_practice`):
- Что было не так — повтор из triage
- Что сделано — PR # link + краткое описание layers
- Что осталось — outcome live smoke + следующие шаги (например, изучить остатки `yt_create_menu_app_not_foregrounded` если они есть)

```bash
# Сформировать комментарий по образцу docs/evidence/2026-05-19-yt-publish-triage.md
# POST на /api/v3/work_packages/87/activities (как в triage-этапе)
```

- [ ] **Step 7: Memory updates**

If smoke confirms fix:
- Add a new shipped-project memory `project_yt_create_menu_fg_guard_shipped.md` (per house pattern, see `project_yt_foreign_foreground_guard_shipped.md`).
- Mark `feedback_yt_post_switch_handle_unknown_precursor.md` as potentially obsolete or update it with the post-fix correlation rate.

---

## Self-Review checklist (run after writing the plan)

- [x] **Spec coverage:** Layer A → Task 1; helper → Task 2; Layer B → Tasks 3+4; Layer C → Tasks 5+6; kill-switch → Tasks 2+7; IG/TT regression-guard → Task 8; tests file (6 scenarios from spec) → covered by Tasks 1,2,3,4,5,6,7,8 (the spec listed 6 scenarios; this plan has 9 distinct test methods + the trivial Layer A coord assert). PR + deploy → Tasks 9-10. **No gaps.**
- [x] **Placeholder scan:** no "TBD" / "TODO" / "similar to" / "add appropriate" patterns. Every code block is complete and runnable.
- [x] **Type consistency:** `_guard_enabled()` defined Task 2, used Tasks 3+5. `_yt_ensure_foreground(cfg, step_name)` matches existing signature `account_switcher.py:3466`. `_detect_foreground_pkg()` matches existing signature `account_switcher.py:3203`. `final_step` and `step_prefix` parameter names match `_tap_plus_and_verify` signature.
- [x] **Live smoke gating:** explicit step to STOP if pre-existing tests regress (Task 9 Step 1) or kill-switch behaviour (Task 10 Step 5 outcomes table).
