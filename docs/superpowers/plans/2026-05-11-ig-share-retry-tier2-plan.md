# IG Share Tier 2 — long-press escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) или superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Добавить Tier 2 long-press escalation ladder в `_wait_instagram_upload` чтобы поднять IG Share rescue rate с текущих 0% (0/6 за 7 дней).

**Architecture:** Один новый instance helper `_long_press_share_button` в `publisher_instagram.py` (рядом с `_is_ig_editor_still_visible:400`). Tier 2 ladder wrap'ит существующий `if share_no_progress: return False` (line 1921-1922). Tier 1 final emit downgrade'нут с `error/ig_share_tap_no_progress` на `warning/ig_share_tier1_exhausted` для cleaner triage semantics.

**Tech Stack:** Python 3.11, ADB `input swipe`, pytest, MagicMock.

**Spec:** `docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md` v5 (3 P1 + 8 P2 + 1 P3 closed across 4 Codex rounds).

---

## Task 0: Setup worktree branch

**Files:** none yet — git ops.

- [ ] **Step 1: Verify autowarm-testbench main clean + fetch (Codex P1.1 fix)**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin main
# Safety guard: abort если есть uncommitted changes на main
git status --porcelain | head -5
# Expected empty output. Если непустой — stash или resolve manually ДО продолжения.
git checkout main
git pull --ff-only origin main
```

Expected: `git status --porcelain` empty before checkout, no merge conflict on `git pull`.

- [ ] **Step 2: Create feature branch + worktree**

```bash
cd /home/claude-user/autowarm-testbench
git worktree add -b feat/ig-share-tier2-20260511 ../autowarm-testbench-feat-ig-share-tier2-20260511 main
cd /home/claude-user/autowarm-testbench-feat-ig-share-tier2-20260511
git branch --show-current  # → feat/ig-share-tier2-20260511
```

- [ ] **Step 3: Verify base state** (existing tests green before changes)

```bash
cd /home/claude-user/autowarm-testbench-feat-ig-share-tier2-20260511
pytest tests/test_publisher_instagram_share_retry.py -v 2>&1 | tail -20
```

Expected: All existing Tier 1 tests PASS (baseline для regression detection).

---

## Task 1: Helper `_long_press_share_button` (TDD, 4 tests)

**Files:**
- Modify: `publisher_instagram.py` — добавить method ПОСЛЕ существующего `def _is_ig_editor_still_visible(self, ui_xml: str) -> bool:` (использовать grep-anchor, не line number: `grep -n 'def _is_ig_editor_still_visible' publisher_instagram.py` — текущая позиция ≈ line 400, может сдвинуться при предыдущих правках). **Codex P1.2 fix: anchor by symbol name, not numeric line.**
- Create: `tests/test_ig_long_press_helper.py`

### Test 1.1: cmd shape

- [ ] **Step 1: Write failing test 1 — cmd shape**

Создать `tests/test_ig_long_press_helper.py` со следующим содержимым:

```python
"""Unit tests for _long_press_share_button helper (Tier 2 long-press escalation).

Spec: docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md §3.1
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _ui_with_share_button(bounds: str = "[563,2025][1035,2149]", clickable: str = "true") -> str:
    return (
        "<?xml version='1.0'?><hierarchy>"
        f'<node text="" content-desc="Поделиться" '
        f'resource-id="com.instagram.android:id/share_button" '
        f'bounds="{bounds}" clickable="{clickable}"/>'
        '</hierarchy>'
    )


def _make_publisher_stub():
    from publisher import DevicePublisher
    stub = DevicePublisher.__new__(DevicePublisher)
    stub.adb = MagicMock(return_value='')
    return stub


def test_long_press_helper_cmd_shape():
    """bounds=[563,2025][1035,2149] → center=(799,2087), swipe cmd correct."""
    stub = _make_publisher_stub()
    result = stub._long_press_share_button(_ui_with_share_button(), hold_ms=200)
    assert result is True
    stub.adb.assert_called_once_with('input swipe 799 2087 799 2087 200')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/claude-user/autowarm-testbench-feat-ig-share-tier2-20260511
pytest tests/test_ig_long_press_helper.py::test_long_press_helper_cmd_shape -v
```

Expected: FAIL with `AttributeError: 'DevicePublisher' object has no attribute '_long_press_share_button'`.

- [ ] **Step 3: Write minimal implementation**

В `publisher_instagram.py` после метода `_is_ig_editor_still_visible` (locate via `grep -n '^    def _is_ig_editor_still_visible\|^    def ' publisher_instagram.py` чтобы найти следующий method и вставить перед ним) добавить:

```python
    def _long_press_share_button(self, ui_xml: str, hold_ms: int = 200) -> bool:
        """Найти clickable id/share_button и сделать long-press tap через
        `input swipe cx cy cx cy <hold_ms>`.

        Long-press на одной точке (start==end) интерпретируется Android как
        DOWN→hold(hold_ms)→UP — даёт layout время финализироваться (B.1/B.3)
        и не выглядит как zero-duration synthetic tap (B.2 anti-bot).

        hold_ms=200 < context-menu threshold (~500ms).

        Returns:
            True если button найден и swipe-команда отправлена;
            False иначе (no button / malformed bounds / adb exception).
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
            if rid.endswith(':id/share_button') and n.get('clickable') == 'true':
                bounds = n.get('bounds', '')
                m = _re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if not m:
                    return False
                x1, y1, x2, y2 = (int(m.group(i)) for i in (1, 2, 3, 4))
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                try:
                    self.adb(f'input swipe {cx} {cy} {cx} {cy} {hold_ms}')
                    return True
                except Exception:
                    return False
        return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_ig_long_press_helper.py::test_long_press_helper_cmd_shape -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ig_long_press_helper.py publisher_instagram.py
git commit -m "feat(ig-share-tier2): add _long_press_share_button helper + cmd-shape test"
```

### Test 1.2-1.4: Helper edge cases

- [ ] **Step 6: Add 3 more tests**

Append в `tests/test_ig_long_press_helper.py`:

```python
def test_long_press_helper_returns_true_on_success():
    """Same scenario as cmd_shape → returns True (also covered above but explicit assert)."""
    stub = _make_publisher_stub()
    assert stub._long_press_share_button(_ui_with_share_button(), hold_ms=200) is True


def test_long_press_helper_returns_false_no_button():
    """UI без share_button → returns False, adb не зовётся."""
    stub = _make_publisher_stub()
    empty_ui = "<?xml version='1.0'?><hierarchy></hierarchy>"
    result = stub._long_press_share_button(empty_ui, hold_ms=200)
    assert result is False
    stub.adb.assert_not_called()


def test_long_press_helper_returns_false_malformed_bounds():
    """share_button присутствует, bounds bad-format → returns False, no adb call."""
    stub = _make_publisher_stub()
    ui = (
        "<?xml version='1.0'?><hierarchy>"
        '<node resource-id="com.instagram.android:id/share_button" '
        'bounds="invalid" clickable="true"/>'
        '</hierarchy>'
    )
    result = stub._long_press_share_button(ui, hold_ms=200)
    assert result is False
    stub.adb.assert_not_called()
```

- [ ] **Step 7: Run all 4 helper tests**

```bash
pytest tests/test_ig_long_press_helper.py -v
```

Expected: 4 PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/test_ig_long_press_helper.py
git commit -m "test(ig-share-tier2): helper edge cases (no button / malformed bounds)"
```

---

## Task 2: Tier 1 telemetry downgrade (1-line mod + 1 test)

**Files:**
- Modify: `publisher_instagram.py` — Tier 1 final emit block (locate via `grep -n "'ig_share_tap_no_progress'" publisher_instagram.py` — should return единственный match в `_wait_instagram_upload`, line ≈1907 на текущем main). **Codex P1.2 fix: locate by string content, not numeric line.**
- Create: `tests/test_ig_tier1_telemetry_downgrade.py`

### Test 2.1: Tier 1 emit assertion

- [ ] **Step 1: Write failing test**

Создать `tests/test_ig_tier1_telemetry_downgrade.py`:

```python
"""Regression test для Codex round 2 P2.1 mitigation.

Tier 1 final emit downgrade'нут с error/'ig_share_tap_no_progress' на
warning/'ig_share_tier1_exhausted'. Final 'ig_share_tap_no_progress' теперь
эмитится только из Tier 2 fail.

Spec: docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md §3.3
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Reuse fixtures from test_publisher_instagram_share_retry
from tests.test_publisher_instagram_share_retry import _editor_xml, _make_publisher_stub


def test_tier1_exhausted_emits_warning_not_error():
    """After Tier 1 retries fail and final check confirms editor, emit
    warning/'ig_share_tier1_exhausted' (NOT error/'ig_share_tap_no_progress').

    Codex P3.1 fix: Note — этот тест run'ится в Task 2 ДО реализации Tier 2 ladder.
    На том этапе `if share_no_progress: return False` всё ещё активен, Tier 2 helper
    ещё не вызывается. Тест ассертит ТОЛЬКО Tier 1 emit (warning category).
    Mock helper установлен заранее на случай если test run'ится также после Task 3
    (Tier 2 ladder уже на месте) — в этом сценарии helper вернёт False, ladder
    пойдёт в button_not_found path, итог error ig_share_tap_no_progress будет,
    но тест проверяет только что Tier 1 эмитит warning (separate assertion).
    """
    dump_responses = [_editor_xml()] * 50
    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    # Pre-emptive mock — после Task 3 ladder появится; при run в Task 2 mock не
    # используется (helper ещё не invoked в коде).
    stub._long_press_share_button = MagicMock(return_value=False)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    # Assert Tier 1 emit:
    tier1_warns = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tier1_exhausted'
    ]
    assert len(tier1_warns) == 1, f'expected 1 tier1_exhausted warning, got {len(tier1_warns)}'
    assert tier1_warns[0].args[0] == 'warning', f"expected level='warning', got {tier1_warns[0].args[0]!r}"

    # Assert Tier 1 НЕ эмитит старый ig_share_tap_no_progress (тот теперь Tier 2-only):
    tier1_errors = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
           and c.args[0] == 'error'
           and not c.kwargs.get('meta', {}).get('tier2_attempted')
    ]
    assert len(tier1_errors) == 0, f'Tier 1 не должен эмитить error ig_share_tap_no_progress, got {len(tier1_errors)}'
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest tests/test_ig_tier1_telemetry_downgrade.py -v
```

Expected: FAIL — текущий код эмитит `error/ig_share_tap_no_progress`, не `warning/ig_share_tier1_exhausted`.

- [ ] **Step 3: Apply Tier 1 mod**

В `publisher_instagram.py`, найти блок через `grep -B 1 -A 6 "'ig_share_tap_no_progress'" publisher_instagram.py` (должен возвращать ровно 1 match — Tier 1 final emit). Заменить:

```python
                if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
                    self.log_event('error',
                                   'Instagram: Share tap не прогрессировал после retries',
                                   meta={'category': 'ig_share_tap_no_progress',
                                         'platform': self.platform,
                                         'step': 'wait_upload',
                                         'retries_exhausted': 2})
```

На:

```python
                if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
                    # Codex round 2 P2.1 mitigation: downgrade Tier 1 final emit на warning.
                    # Final error 'ig_share_tap_no_progress' теперь эмитится только из Tier 2 fail.
                    self.log_event('warning',
                                   'Instagram: Tier 1 Share retries exhausted — escalating to Tier 2',
                                   meta={'category': 'ig_share_tier1_exhausted',
                                         'platform': self.platform,
                                         'step': 'wait_upload',
                                         'retries_exhausted': 2})
```

- [ ] **Step 4: Re-run test**

```bash
pytest tests/test_ig_tier1_telemetry_downgrade.py -v
```

Expected: PASS (но Tier 2 ladder ещё не реализован — `_wait_instagram_upload` всё ещё return False сразу. Это OK для этого теста, он только проверяет Tier 1 emit).

Также проверить что existing Tier 1 tests не сломались — конкретно тесты в `tests/test_publisher_instagram_share_retry.py`, которые могут ассертить `ig_share_tap_no_progress`:

```bash
pytest tests/test_publisher_instagram_share_retry.py -v
```

Expected: некоторые ассерты сломаются (любой тест, ассертирующий event category `ig_share_tap_no_progress` от Tier 1 path).

- [ ] **Step 5: Update specific Tier 1 test (Codex P2.1 fix — named test, not "if asserts break")**

Конкретно затрагивается `tests/test_publisher_instagram_share_retry.py::test_share_retry_exhausted_emits_no_progress` (verified `grep -n 'ig_share_tap_no_progress' tests/test_publisher_instagram_share_retry.py` returns эту функцию). После Tier 1 downgrade сценарий «editor visible везде» эмитит `warning/ig_share_tier1_exhausted` — но тест ещё ассертит `ig_share_tap_no_progress` (count=1). Поскольку Tier 2 ladder в этой Task ещё НЕ реализован, поведение: Tier 1 эмитит `tier1_exhausted` (warning), затем `_wait_instagram_upload` возвращает False БЕЗ Tier 2 (поскольку Task 3 ещё не сделан) → НО Tier 2 ladder WRAP'ит `if share_no_progress: return False` (Task 3). Сейчас (после Task 2 только) код всё ещё имеет `if share_no_progress: return False`, поэтому test всё ещё проходит чтобы возвращало False, но ассерт category поменялся.

Заменить в `test_share_retry_exhausted_emits_no_progress` (около line 145-155 файла):

```python
# было:
no_progress_calls = [
    c for c in stub.log_event.call_args_list
    if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
]
assert len(no_progress_calls) == 1
# стало (Task 2):
tier1_warns = [
    c for c in stub.log_event.call_args_list
    if c.kwargs.get('meta', {}).get('category') == 'ig_share_tier1_exhausted'
]
assert len(tier1_warns) == 1
# NOTE: после Task 3 (Tier 2 ladder) этот же сценарий продолжит fail в Tier 2 →
# дополнительно появится 1 error 'ig_share_tap_no_progress' с tier2_attempted=True.
# Тогда же добавим:
# tier2_errs = [c for c in stub.log_event.call_args_list
#               if c.args[0] == 'error'
#                  and c.kwargs.get('meta',{}).get('category') == 'ig_share_tap_no_progress'
#                  and c.kwargs.get('meta',{}).get('tier2_attempted')]
# assert len(tier2_errs) == 1
```

(После Task 3 финальный update этого ассерта — см. Task 3 Step 7.)

- [ ] **Step 6: Re-run all share-retry tests**

```bash
pytest tests/test_publisher_instagram_share_retry.py tests/test_ig_tier1_telemetry_downgrade.py -v
```

Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add publisher_instagram.py tests/test_ig_tier1_telemetry_downgrade.py tests/test_publisher_instagram_share_retry.py
git commit -m "$(cat <<'EOF'
feat(ig-share-tier2): Tier 1 final emit downgrade — warning/ig_share_tier1_exhausted

Per spec §3.2 + Codex round 2 P2.1 mitigation. Tier 1 final emit меняется с
error/'ig_share_tap_no_progress' на warning/'ig_share_tier1_exhausted'. Final
error 'ig_share_tap_no_progress' теперь только из Tier 2 fail block (Task 3).
EOF
)"
```

---

## Task 3: Tier 2 ladder integration (6 ladder tests + 2 regression + 1 retry telemetry test)

**Files:**
- Modify: `publisher_instagram.py` — `if share_no_progress: return False` block (locate via `grep -n 'if share_no_progress' publisher_instagram.py` — должен возвращать единственный match в `_wait_instagram_upload`). **Codex P1.2 fix.**
- Create: `tests/test_ig_share_tier2_ladder.py`

### Test 3.1: Ladder behavior tests (6 tests)

- [ ] **Step 1: Write all 6 failing tests + 2 regression в новом файле**

Создать `tests/test_ig_share_tier2_ladder.py`:

```python
"""Behavior tests для Tier 2 long-press escalation ladder.

Spec: docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md §3.2, §4.2-4.3
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_publisher_instagram_share_retry import _editor_xml, _post_publish_xml, _make_publisher_stub


def _meta_categories(stub):
    """Helper: список (level, category) для всех log_event calls."""
    return [
        (c.args[0], c.kwargs.get('meta', {}).get('category'))
        for c in stub.log_event.call_args_list
    ]


# ============ §4.2 Ladder behavior (6 tests) ============

def test_tier2_progressed_on_attempt_1_pre_check():
    """Pre-attempt-1 check sees editor gone (без long-press) →
    ig_share_progressed_pre_long_press с attempts_used=0.
    """
    # Tier 1 baseline (T) → 2 retries (T,T) → final (T) → Tier 2 attempt 1 pre-check (F)
    dump_responses = [
        _editor_xml(),  # iter0 diag (Tier 1 baseline)
        _editor_xml(),  # retry 1 check
        _editor_xml(),  # retry 2 check
        _editor_xml(),  # Tier 1 final check (sets share_no_progress=True)
        _post_publish_xml(),  # Tier 2 attempt 1 pre-check → progressed
    ] + [_post_publish_xml()] * 50  # main loop остатки

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(return_value=True)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    pre_lp = [c for c in stub.log_event.call_args_list
              if c.kwargs.get('meta', {}).get('category') == 'ig_share_progressed_pre_long_press']
    assert len(pre_lp) == 1
    assert pre_lp[0].kwargs['meta']['attempts_used'] == 0
    # Long-press helper НЕ должен зваться:
    stub._long_press_share_button.assert_not_called()


def test_long_press_retry_telemetry():
    """Codex round 1 plan-review P2.2: assert ig_share_long_press_retry event emitted
    per fired long-press с правильными meta keys (attempt, hold_ms, platform, step).
    """
    dump_responses = [
        _editor_xml(),  # iter0
        _editor_xml(), _editor_xml(),  # Tier 1 retries
        _editor_xml(),  # Tier 1 final
        _editor_xml(),  # Tier 2 attempt 1 pre-check (visible → fire long-press)
        _editor_xml(),  # Tier 2 attempt 2 pre-check (visible → fire long-press)
        _editor_xml(),  # post-loop final check (still visible → fail)
    ] + [_editor_xml()] * 30

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(return_value=True)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    retry_events = [c for c in stub.log_event.call_args_list
                    if c.kwargs.get('meta', {}).get('category') == 'ig_share_long_press_retry']
    assert len(retry_events) == 2, f'expected 2 retry events, got {len(retry_events)}'
    for i, ev in enumerate(retry_events, start=1):
        meta = ev.kwargs['meta']
        assert meta['attempt'] == i
        assert meta['hold_ms'] == 200
        assert meta['platform'] == 'Instagram'
        assert meta['step'] == 'wait_upload'


def test_tier2_progressed_on_attempt_2_after_long_press():
    """Attempt 1: editor visible → long-press fired → attempt 2 pre-check: editor gone →
    ig_share_long_press_progressed с attempts_used=1.
    """
    dump_responses = [
        _editor_xml(),  # iter0 diag
        _editor_xml(), _editor_xml(),  # 2 Tier 1 retries
        _editor_xml(),  # Tier 1 final check
        _editor_xml(),  # Tier 2 attempt 1 pre-check (still visible)
        _post_publish_xml(),  # Tier 2 attempt 2 pre-check → progressed
    ] + [_post_publish_xml()] * 50

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(return_value=True)  # successful tap

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    lp_prog = [c for c in stub.log_event.call_args_list
               if c.kwargs.get('meta', {}).get('category') == 'ig_share_long_press_progressed']
    assert len(lp_prog) == 1
    assert lp_prog[0].kwargs['meta']['attempts_used'] == 1
    # Long-press fired ровно 1 раз:
    assert stub._long_press_share_button.call_count == 1


def test_tier2_progressed_on_postloop_check():
    """All pre-checks visible, both long-presses sent, post-loop check: editor gone →
    ig_share_long_press_progressed с attempts_used=2 (round 2 P1.1 fix coverage).
    """
    dump_responses = [
        _editor_xml(),  # iter0
        _editor_xml(), _editor_xml(),  # Tier 1 retries
        _editor_xml(),  # Tier 1 final
        _editor_xml(),  # Tier 2 attempt 1 pre-check
        _editor_xml(),  # Tier 2 attempt 2 pre-check
        _post_publish_xml(),  # Post-loop final check → progressed
    ] + [_post_publish_xml()] * 50

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(return_value=True)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    lp_prog = [c for c in stub.log_event.call_args_list
               if c.kwargs.get('meta', {}).get('category') == 'ig_share_long_press_progressed']
    assert len(lp_prog) == 1
    assert lp_prog[0].kwargs['meta']['attempts_used'] == 2
    assert stub._long_press_share_button.call_count == 2


def test_tier2_exhausted_fail():
    """Editor visible везде (включая post-loop) → ig_share_tap_no_progress error
    с tier2_attempted=True. _last_push_err НЕ ставится (consistent с Tier 1).
    """
    dump_responses = [_editor_xml()] * 50  # always visible

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(return_value=True)

    with patch('time.sleep'):
        result = stub._wait_instagram_upload()

    assert result is False

    err_calls = [c for c in stub.log_event.call_args_list
                 if c.args[0] == 'error'
                    and c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress']
    assert len(err_calls) == 1
    meta = err_calls[0].kwargs['meta']
    assert meta['tier2_attempted'] is True
    assert meta['lp_attempts'] == 2
    assert meta['long_press_sent_count'] == 2
    assert meta['hold_ms'] == 200
    assert meta['step'] == 'wait_upload'
    assert meta['retries_exhausted'] == 2
    # `_last_push_err` НЕ должен быть установлен — consistent с Tier 1 (verified publisher_instagram.py:1907-1922)
    assert getattr(stub, '_last_push_err', None) is None or stub._last_push_err is None


def test_tier2_button_not_found_all():
    """_long_press_share_button returns False на ВСЕХ attempts (UI без button) →
    fail с tier2_button_not_found=True.
    """
    dump_responses = [_editor_xml()] * 50
    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(return_value=False)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    err_calls = [c for c in stub.log_event.call_args_list
                 if c.args[0] == 'error'
                    and c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress']
    assert len(err_calls) == 1
    meta = err_calls[0].kwargs['meta']
    assert meta['tier2_button_not_found'] is True
    assert meta['long_press_sent_count'] == 0


def test_tier2_button_not_found_partial():
    """_long_press_share_button returns [False, True] → flag НЕ в meta (only when ALL fail).
    Codex round 1 P2.1 fix coverage.
    """
    dump_responses = [_editor_xml()] * 50
    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(side_effect=[False, True])

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    err_calls = [c for c in stub.log_event.call_args_list
                 if c.args[0] == 'error'
                    and c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress']
    assert len(err_calls) == 1
    meta = err_calls[0].kwargs['meta']
    assert 'tier2_button_not_found' not in meta or meta['tier2_button_not_found'] is not True
    assert meta['long_press_sent_count'] == 1


# ============ §4.3 Regression (2 tests) ============

def test_tier1_success_skips_tier2():
    """Tier 1 retry-1 progressed → _long_press_share_button НЕ зовётся."""
    dump_responses = [
        _editor_xml(),       # iter0
        _editor_xml(),       # retry 1 check before re-tap
        _post_publish_xml(), # retry 2 check → progressed
    ] + [_post_publish_xml()] * 50

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(return_value=True)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    stub._long_press_share_button.assert_not_called()


def test_no_stuck_skips_both_tiers():
    """Editor not visible на iter0 → ни Tier 1 ни Tier 2 не invoked."""
    dump_responses = [_post_publish_xml()] * 50

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)
    stub._long_press_share_button = MagicMock(return_value=True)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    stub._long_press_share_button.assert_not_called()
    # ig_share_retry events тоже не должны быть (Tier 1 retry loop не entered)
    retries = [c for c in stub.log_event.call_args_list
               if c.kwargs.get('meta', {}).get('category') == 'ig_share_retry']
    assert len(retries) == 0
```

- [ ] **Step 2: Run all 9 tests, verify expected split (Codex P1.3 fix)**

```bash
pytest tests/test_ig_share_tier2_ladder.py -v
```

**Expected baseline (Tier 2 ladder NOT yet implemented):**
- **6 FAIL** — ladder behavior tests (1, 2, 3, 4, 5, 6 в файле — assertions ladder events ladder events не появятся): `test_tier2_progressed_on_attempt_1_pre_check`, `test_tier2_progressed_on_attempt_2_after_long_press`, `test_tier2_progressed_on_postloop_check`, `test_tier2_exhausted_fail`, `test_tier2_button_not_found_all`, `test_tier2_button_not_found_partial`.
- **1 FAIL** — `test_long_press_retry_telemetry` (новый retry-telemetry test — Codex P2.2 fix).
- **2 PASS** — regression tests (`test_tier1_success_skips_tier2`, `test_no_stuck_skips_both_tiers`) — они проверяют что Tier 2 *не* invoked в этих сценариях. До Task 3 ladder helper не зовётся вообще → assertions сразу green.

Это валидный TDD-RED state: 7 fail (ladder logic missing), 2 pass (negative-path regressions).

- [ ] **Step 3: Implement Tier 2 ladder**

В `publisher_instagram.py`, заменить block (примерно lines 1921-1922):

```python
        if share_no_progress:
            return False
```

На полный Tier 2 ladder (содержание из spec §3.2):

```python
        if share_no_progress:
            # === Tier 2 long-press escalation ===
            # Spec: docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md §3.2
            TIER2_LP_ATTEMPTS = 2
            TIER2_LP_HOLD_MS = 200
            TIER2_LP_PRE_DELAY_S = 3
            TIER2_LP_POST_DELAY_S = 2

            tier2_progressed = False
            tier2_button_not_found_count = 0
            long_press_sent_count = 0

            for lp_attempt in range(1, TIER2_LP_ATTEMPTS + 1):
                time.sleep(TIER2_LP_PRE_DELAY_S)
                lp_ui = self.dump_ui()
                if not self._is_ig_editor_still_visible(lp_ui):
                    tier2_progressed = True
                    if long_press_sent_count == 0:
                        category = 'ig_share_progressed_pre_long_press'
                    else:
                        category = 'ig_share_long_press_progressed'
                    self.log_event(
                        'info',
                        f'Instagram: Share PROGRESSED before attempt {lp_attempt} '
                        f'(long_press_sent={long_press_sent_count})',
                        meta={'category': category,
                              'platform': self.platform,
                              'step': 'wait_upload',
                              'attempts_used': long_press_sent_count,
                              'hold_ms': TIER2_LP_HOLD_MS},
                    )
                    break
                if not self._long_press_share_button(lp_ui, hold_ms=TIER2_LP_HOLD_MS):
                    tier2_button_not_found_count += 1
                    continue
                long_press_sent_count += 1
                self.log_event(
                    'info',
                    f'Instagram: long-press Share retry {lp_attempt}',
                    meta={'category': 'ig_share_long_press_retry',
                          'platform': self.platform,
                          'step': 'wait_upload',
                          'attempt': lp_attempt,
                          'hold_ms': TIER2_LP_HOLD_MS},
                )
                time.sleep(TIER2_LP_POST_DELAY_S)

            # Post-loop final progress check (Codex round 2 P1.1 fix)
            if not tier2_progressed:
                final_ui = self.dump_ui()
                if not self._is_ig_editor_still_visible(final_ui):
                    tier2_progressed = True
                    if long_press_sent_count == 0:
                        category = 'ig_share_progressed_pre_long_press'
                    else:
                        category = 'ig_share_long_press_progressed'
                    self.log_event(
                        'info',
                        f'Instagram: Share PROGRESSED post-loop '
                        f'(long_press_sent={long_press_sent_count})',
                        meta={'category': category,
                              'platform': self.platform,
                              'step': 'wait_upload',
                              'attempts_used': long_press_sent_count,
                              'hold_ms': TIER2_LP_HOLD_MS},
                    )

            if not tier2_progressed:
                err_meta = {
                    'category': 'ig_share_tap_no_progress',
                    'platform': self.platform,
                    'step': 'wait_upload',
                    'retries_exhausted': 2,
                    'tier2_attempted': True,
                    'lp_attempts': TIER2_LP_ATTEMPTS,
                    'long_press_sent_count': long_press_sent_count,
                    'hold_ms': TIER2_LP_HOLD_MS,
                }
                if tier2_button_not_found_count == TIER2_LP_ATTEMPTS:
                    err_meta['tier2_button_not_found'] = True
                self.log_event(
                    'error',
                    'Instagram: Tier 2 long-press exhausted — abort',
                    meta=err_meta,
                )
                return False
            # tier2_progressed: fall through в existing main wait loop ниже
```

- [ ] **Step 4: Run all 9 tests, verify they pass**

```bash
pytest tests/test_ig_share_tier2_ladder.py -v
```

Expected: 9 PASS (6 ladder behavior + 1 retry telemetry + 2 regression).

- [ ] **Step 5: Run full IG test suite (regression check)**

```bash
pytest tests/test_publisher_instagram_share_retry.py tests/test_ig_long_press_helper.py tests/test_ig_tier1_telemetry_downgrade.py tests/test_ig_share_tier2_ladder.py tests/test_ig_editor_visible_helper.py tests/test_ig_share_candidates.py -v
```

Expected: всё PASS. Конкретно: 4 helper + 1 Tier 1 mod + 8 Tier 2 ladder + existing 5 Tier 1 retry + ~20 other = ~38+ tests green.

- [ ] **Step 6: Commit**

```bash
git add publisher_instagram.py tests/test_ig_share_tier2_ladder.py
git commit -m "$(cat <<'EOF'
feat(ig-share-tier2): Tier 2 long-press escalation ladder

Wrap'ит existing `if share_no_progress: return False` в полный ladder:
2 long-press attempts × 200ms hold через `_long_press_share_button` + post-loop
final progress check. Telemetry: ig_share_long_press_retry / _progressed /
_progressed_pre_long_press + Tier 2 fail обогащает существующий
ig_share_tap_no_progress meta'ой tier2_attempted/long_press_sent_count/lp_attempts.

Spec §3.2. 9 tests (6 ladder behavior + 1 retry telemetry + 2 regression) green.
EOF
)"
```

---

## Task 4: Codex review of code + apply findings

**Files:** all changes above

- [ ] **Step 1: Run codex review on uncommitted diff (но всё commit'нуто — на head)**

```bash
cd /home/claude-user/autowarm-testbench-feat-ig-share-tier2-20260511
~/.local/bin/codex review --base main > /tmp/codex-tier2-impl-review.txt 2>&1
```

Expected: codex анализирует diff против main, возвращает P1/P2/P3 finds для **кода** (не для spec).

- [ ] **Step 2: Apply P1 findings AND enough P2 findings — gate = 0 P1 + ≤1 P2 (Codex plan-review v2 P2 fix)**

```bash
cat /tmp/codex-tier2-impl-review.txt | tail -80
```

**Gate для перехода к Step 3 = 0 P1 AND ≤1 P2 remaining.** Если round возвращает 0 P1 но 2+ P2 — применить достаточно P2 findings чтобы выйти на gate (приоритет P2: ambiguity > scope-drift > missing-test > minor). P3 — opt-in, не блокирует.

Apply findings inline, затем:

```bash
# IMPORTANT: use `git add -A` (НЕ `git commit -am` — пропустит новые файлы)
git status --short
git add -A
# Заполнить commit message конкретным count'ом, убрать placeholder
git commit -m "feat(ig-share-tier2): apply Codex code-review round N (X P1 + Y P2)"
~/.local/bin/codex review --base main > /tmp/codex-tier2-impl-review-2.txt 2>&1
```

Итерировать пока 0 P1 + ≤1 P2. На каждом round'е считать X, Y и подставлять явные числа в commit message.

- [ ] **Step 3: Final full-suite green**

```bash
pytest tests/ -v 2>&1 | tail -20
```

Expected: всё PASS.

---

## Task 5: PR open + handoff к user

**Files:** none — git/PR ops

- [ ] **Step 1: Push branch**

```bash
cd /home/claude-user/autowarm-testbench-feat-ig-share-tier2-20260511
git push -u origin feat/ig-share-tier2-20260511
```

- [ ] **Step 2: Open PR**

```bash
GH_TOKEN="$(grep -oP 'ghp_\w+' ~/secrets/github-gengo2.env)" gh pr create \
  --title 'feat(ig-share-tier2): long-press escalation ladder' \
  --body "$(cat <<'EOF'
## Summary
Closes IG share rescue gap (current Tier 1 rate: 0/6 = 0% за 7 дней).

- 2 long-press attempts × 200ms hold через `input swipe cx cy cx cy 200`
- Post-loop final progress check (catches success на attempt 2)
- Tier 1 final emit downgrade на warning/ig_share_tier1_exhausted — final error 'ig_share_tap_no_progress' теперь только из Tier 2 fail
- 4 new categories для telemetry split: long_press_retry / long_press_progressed / progressed_pre_long_press + enriched tier2_attempted=true в fail meta

## Spec
`docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md` v5 (Codex 4 rounds: 3 P1 + 8 P2 + 1 P3 closed, VERDICT ready for plan)

## Test plan
- [ ] 14 new unit tests green (4 helper + 1 Tier 1 mod + 6 ladder + 1 retry telemetry + 2 regression)
- [ ] existing Tier 1 retry tests adapted (warning category)
- [ ] live verify: re-queue 1 IG задачу с known `ig_share_tap_no_progress` history → observe meta `tier2_attempted=True` в fail OR success path с `ig_share_long_press_progressed`
- [ ] 24h post-deploy: count `meta.category='ig_share_long_press_progressed'` vs `tier2_attempted=true` exhausted → decision for Tier 3 design

## Risk
+10s latency на fail path (Tier 1 ~10s, Tier 2 +10s) — fails ~1% от total → throughput impact <0.1%.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Update memory + present to user (Codex P3.2 fix — exact path)**

```bash
# Update memory с конкретным PR номером + commit SHA
# File: /home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_ig_share_tier2_design.md
# Меняем status секцию на: "PR #NN open, HEAD <sha>, awaiting user merge"
```

Edit с `Edit` tool, не shell — раздел `**Статус:**` обновляется на актуальный PR.

- [ ] **Step 4: Worktree cleanup decision (Codex P2.4 fix)**

Не удалять worktree сразу:
- **Если user merge'ает PR через GitHub UI**: после merge зайти в worktree, `git fetch origin main && git checkout main && git pull --ff-only`, потом `cd .. && git worktree remove autowarm-testbench-feat-ig-share-tier2-20260511 && git branch -d feat/ig-share-tier2-20260511`.
- **Если user просит изменения**: оставить worktree, итерировать там.

Не делать teardown сразу после PR open — user может попросить правки.

- [ ] **Step 5: Rollback criteria (Codex P2.5 fix)**

**Live verify SQL (24h post-deploy):**
```sql
SELECT
  count(*) FILTER (WHERE e->'meta'->>'category' = 'ig_share_long_press_progressed') AS lp_rescued,
  count(*) FILTER (WHERE e->'meta'->>'category' = 'ig_share_progressed_pre_long_press') AS pre_lp_auto,
  count(*) FILTER (WHERE e->'meta'->>'category' = 'ig_share_long_press_retry') AS lp_fired,
  count(DISTINCT pt.id) FILTER (
    WHERE pt.error_code = 'ig_share_tap_no_progress'
      AND e->'meta'->>'category' = 'ig_share_tap_no_progress'
      AND (e->'meta'->>'tier2_attempted')::boolean = true
  ) AS tier2_exhausted_tasks
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.started_at >= '2026-05-11 18:00:00';  -- adjust к moment деплоя
```

**Rollback triggers (revert PR + restart autowarm):**
1. **Total IG fail rate** идёт ↑ vs предыдущие 7д baseline (Spec §1.1: 6 unique Tier 1 tasks / 7д = ~1/день). Если >3/день в первые 24h — investigate.
2. **`tier2_exhausted_tasks` >= 80%** от total `ig_share_tap_no_progress` tasks → Tier 2 не помогает, обмыслить (но не auto-revert).
3. **New error_codes emerging** (категория не в pre-deploy listing) появляются >5/день — может быть regression от ladder logic.
4. **Subprocess hangs** (`error_code='watchdog_subprocess_hang'` рост) — Tier 2 latency может пушнуть subprocess к timeout.

**Rollback command:**
```bash
cd /home/claude-user/autowarm-testbench
git fetch origin main
# Find merge commit (e.g. ABC123) для feat/ig-share-tier2-20260511
git log --oneline --merges main | grep tier2 | head -1
# Revert merge commit с -m 1 (mainline):
git revert -m 1 <merge-sha>
git push origin main
# auto-push hook задеплоит prod
sudo pm2 restart autowarm
```

---

## File Structure Summary

| File | Action | Lines |
|---|---|---|
| `publisher_instagram.py` | Modify | +1 helper method (~30 lines) + 1-line Tier 1 emit mod (level/category swap) + Tier 2 ladder replacing `if share_no_progress: return False` (~70 lines) |
| `tests/test_ig_long_press_helper.py` | Create | 4 tests |
| `tests/test_ig_tier1_telemetry_downgrade.py` | Create | 1 test |
| `tests/test_ig_share_tier2_ladder.py` | Create | 9 tests (6 ladder behavior + 1 retry-telemetry + 2 regression) |
| `tests/test_publisher_instagram_share_retry.py` | Modify | Update `test_share_retry_exhausted_emits_no_progress` ассерт: category `ig_share_tap_no_progress` → `ig_share_tier1_exhausted` (Task 2 Step 5); после Task 3 добавить assertion на Tier 2 fail emit |

Total new tests: **14** (4 helper + 1 Tier 1 mod + 6 ladder + 1 retry-telemetry + 2 regression — Spec §9.1 укажет 13, retry-telemetry plan-level Codex P2.2 add).

---

## Self-Review checklist

**Spec coverage:**
- §3.1 helper → Task 1 ✓
- §3.2 ladder → Task 3 ✓
- §3.3 Tier 1 mod → Task 2 ✓
- §4.1-4.4 13 tests → Task 1 (4) + Task 2 (1) + Task 3 (8) = 13 ✓
- §5 edge cases → covered by tests 4 (no button), 9-10 (button_not_found scenarios) ✓
- §6 telemetry → emit calls in ladder ✓
- §9 acceptance → Task 4 (codex) + Task 5 (PR) ✓

**Placeholder scan:** none.

**Type consistency:** `_long_press_share_button(ui_xml: str, hold_ms: int) -> bool` consistent across helper file + ladder block + tests. Event meta key `long_press_sent_count` consistent across emit + assertions.
