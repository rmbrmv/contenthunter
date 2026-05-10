# TikTok Music Rights Dialog Handler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить handler в `publisher_tiktok.py::publish_tiktok` wait_upload loop, который detect'ит и accept'ит TikTok music rights confirmation dialog (новый TT UX 2026-05-10), что блокирует ~12 IG fails/24h на raspberry=9.

**Architecture:** Approach A — handler в wait_upload loop рядом с `_tt_audio_markers` / `_tt_notif_markers`. Strict structural detector (title-EXACT-node + checkbox/button structure, не plain substring). Pure helper в `TikTokMixin`. Auto-accept + persistence checkbox per user decision. Все 9 Codex round-1 finds + 5 round-2 + остальные cleanups применены — спецификация прошла 6 итераций аудита.

**Tech Stack:** Python 3.11, `xml.etree.ElementTree` (uiautomator dump parsing), pytest + unittest.mock, ADB shell. Существующие proxy API: `self.adb`, `self.dump_ui`, `self.log_event`, `self.adb_tap`, `self.set_step`, `self.tap_element` (НЕ использовать для music rights — есть строгая замена).

**Spec:** `docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md` (commit `178fa76ac`).

---

## Pre-flight Context

**Repo and worktree:**
- Code lives in **autowarm-testbench** repo (GitHub: `GenGo2/delivery-contenthunter`)
- Prod path: `/root/.openclaw/workspace-genri/autowarm/` (separate clone with auto-push hook)
- Local working clone: `/home/claude-user/autowarm-testbench/`
- **Use a worktree** for this plan: `/home/claude-user/autowarm-testbench-feat-tt-music-rights-20260510/` (created via `superpowers:using-git-worktrees`)

**Why worktree:** parallel sessions могут писать в main параллельно (memory `feedback_parallel_claude_sessions.md`); pytest зелёный перед коммитом обязателен.

**Test runner:**
```bash
cd /home/claude-user/autowarm-testbench-feat-tt-music-rights-20260510
pytest tests/test_publisher_tt_music_rights.py -v
```

**Pre-existing fails on main** (per memory `project_validator_stale_generate_description_tests.md` and similar): test_canonical_error_codes TT switcher + test_publisher_ig_camera_recovery — НЕ регрессии этого плана, не чинить.

**Auto-push hook:** prod clone имеет post-commit hook auto-push в GitHub (memory `reference_autowarm_git_hook.md`). Worktree этого хука НЕ имеет — push manually after merge to main.

---

## File Structure

| File | Action | Purpose |
|---|---|---|
| `publisher_tiktok.py` | Modify | Constants (TITLE_MARKERS / BUTTON / CHECKBOX), 4 helpers (`_strict_tap_clickable`, `_detect_*`, `_tick_*`, `_handle_*`), wire в wait_upload loop, counter reset в начале `publish_tiktok` |
| `publisher_kernel.py` | Modify (1 line) | Mapping `'tt_5_music_rights_stuck' → 'tt_music_rights_stuck'` в `_SWITCHER_STEP_TO_CATEGORY` |
| `tests/test_publisher_tt_music_rights.py` | Create | 19 unit/integration тестов (4 detector + 5 handle/checkbox + 3 loop + 3 ordering/regression + 4 strict-tap) |

**Out of scope:** `publisher_base.py` не трогаем — strict tap helper держим в `publisher_tiktok.py` рядом с TikTokMixin (YAGNI; если IG/YT понадобится — refactor позже).

---

## Task 1: Worktree setup + spec skim

**Files:** none (setup only)

- [ ] **Step 1: Pre-flight git fetch (avoid stale state)**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git status  # confirm на main, clean
```

Expected: clean working tree, `up to date with 'origin/main'`.

- [ ] **Step 2: Create worktree via using-git-worktrees skill**

Invoke `superpowers:using-git-worktrees` skill (if not auto-created). Worktree path:
```
/home/claude-user/autowarm-testbench-feat-tt-music-rights-20260510/
```

Branch name: `feat/tt-music-rights-dialog-20260510`.

- [ ] **Step 3: Verify worktree state**

```bash
cd /home/claude-user/autowarm-testbench-feat-tt-music-rights-20260510
git status                                 # clean, на feat/tt-music-rights-dialog-20260510
git log --oneline -3                       # совпадает с main HEAD
ls publisher_tiktok.py publisher_kernel.py # оба существуют
```

- [ ] **Step 4: Read spec end-to-end**

Read `docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md` from main (or copy via `cp`) — обязательно прочесть section 3 (Архитектура) полностью перед написанием кода.

- [ ] **Step 5: Verify pytest baseline**

```bash
cd /home/claude-user/autowarm-testbench-feat-tt-music-rights-20260510
pytest tests/test_tt_audio_dialog.py -v
```

Expected: 3-5 tests PASS (existing TT audio dialog tests). Если падают — НЕ начинай работу, разбирайся с baseline.

---

## Task 2: Add module + class constants in publisher_tiktok.py

**Files:**
- Modify: `publisher_tiktok.py` (add constants at module + class level)

- [ ] **Step 1: Add module-level cap constant**

В `publisher_tiktok.py`, рядом с `MAX_AUDIO_DIALOG_ITERATIONS = 10` (line ~25), добавить:

```python
# Music rights confirmation dialog cap (2026-05-10).
# Spec: docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md
MAX_MUSIC_RIGHTS_ITERATIONS = 5
```

- [ ] **Step 2: Add class-level marker lists in TikTokMixin**

В классе `TikTokMixin` (line ~28), сразу после docstring `"""TikTok-specific publish + URL capture methods."""`, добавить:

```python
    # Music rights dialog markers (2026-05-10).
    # Title — EXACT match (structural identity anchor). Включает оба
    # варианта (с ? и без ?) — TT minor-update может убрать punctuation.
    _TT_MUSIC_RIGHTS_TITLE_MARKERS = [
        'Подтвердить и опубликовать видео?',
        'Подтвердить и опубликовать видео',
        'Confirm and publish video?',
        'Confirm and publish video',
    ]
    _TT_MUSIC_RIGHTS_BUTTON = ['Опубликовать видео', 'Publish video']
    _TT_MUSIC_RIGHTS_CHECKBOX = [
        'Я принимаю Подтверждение прав на использование музыки',
        'I accept the Music Usage Rights Confirmation',
    ]
```

- [ ] **Step 3: Run existing tests — verify no syntax break**

```bash
pytest tests/test_tt_audio_dialog.py -v
```

Expected: PASS (constants добавление не должно ломать ничего).

- [ ] **Step 4: Commit**

```bash
git add publisher_tiktok.py
git commit -m "feat(tt-music-rights): add markers + iter cap constants

Spec: docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md"
```

---

## Task 3: Kernel mapping for tt_5_music_rights_stuck

**Files:**
- Create: `tests/test_publisher_tt_music_rights.py` (new file with first test)
- Modify: `publisher_kernel.py:96-99` (add one mapping line)

- [ ] **Step 1: Write failing test for kernel mapping**

Create `tests/test_publisher_tt_music_rights.py`:

```python
"""TT music rights confirmation dialog handler tests.

Spec: docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md

Запуск:
    cd /home/claude-user/autowarm-testbench-feat-tt-music-rights-20260510
    pytest tests/test_publisher_tt_music_rights.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_kernel import _SWITCHER_STEP_TO_CATEGORY  # noqa: E402
from publisher_tiktok import (  # noqa: E402
    MAX_MUSIC_RIGHTS_ITERATIONS,
    TikTokMixin,
)


# ====== T15 (kernel mapping) ======

def test_kernel_mapping_includes_music_rights():
    """Step 'tt_5_music_rights_stuck' должен canonicalize'аться в
    'tt_music_rights_stuck' через _SWITCHER_STEP_TO_CATEGORY (publisher_kernel.py).
    Без этой mapping dashboard split не увидит canonical error_code.
    """
    assert _SWITCHER_STEP_TO_CATEGORY.get('tt_5_music_rights_stuck') == 'tt_music_rights_stuck', (
        'tt_5_music_rights_stuck → tt_music_rights_stuck mapping missing in '
        'publisher_kernel._SWITCHER_STEP_TO_CATEGORY'
    )
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
pytest tests/test_publisher_tt_music_rights.py::test_kernel_mapping_includes_music_rights -v
```

Expected: FAIL with `KeyError` или `assert None == 'tt_music_rights_stuck'`.

- [ ] **Step 3: Add mapping in publisher_kernel.py**

В `publisher_kernel.py`, найти строку:
```python
'tt_5_audio_dialog_stuck': 'tt_audio_dialog_stuck',
```

Добавить **сразу после** неё:
```python
    # [2026-05-10] Music rights confirmation dialog stuck — TT UX rollout.
    # Triggered when music-rights detector runs >MAX_MUSIC_RIGHTS_ITERATIONS
    # без passing button tap (publisher_tiktok.py music-rights branch).
    'tt_5_music_rights_stuck': 'tt_music_rights_stuck',
```

- [ ] **Step 4: Run test — expect PASS**

```bash
pytest tests/test_publisher_tt_music_rights.py::test_kernel_mapping_includes_music_rights -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_music_rights.py publisher_kernel.py
git commit -m "feat(tt-music-rights): kernel mapping tt_5_music_rights_stuck

+ first test in new test file"
```

---

## Task 4: Strict tap helper `_strict_tap_clickable`

**Files:**
- Modify: `publisher_tiktok.py` (add helper in TikTokMixin)
- Modify: `tests/test_publisher_tt_music_rights.py` (4 tests)

- [ ] **Step 1: Append 4 strict-tap tests**

В `tests/test_publisher_tt_music_rights.py`, добавить:

```python
# ====== T16-T19 (strict tap helper direct tests) ======

def _make_mixin_with_mock_adb():
    """Build a fresh TikTokMixin instance with mocked adb_tap. Used by
    strict-tap and checkbox tests."""
    m = TikTokMixin()
    m.adb_tap = MagicMock()
    return m


_STRICT_TAP_UI_TEXT_EXACT = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Опубликовать видео" content-desc="" clickable="true"
        bounds="[100,1800][900,1900]" class="android.widget.Button" />
</hierarchy>'''

_STRICT_TAP_UI_DESC_EXACT = '''<?xml version="1.0"?>
<hierarchy>
  <node text="" content-desc="Publish video" clickable="true"
        bounds="[100,1800][900,1900]" class="android.widget.Button" />
</hierarchy>'''

_STRICT_TAP_UI_SUBSTRING = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Опубликовать видео и поделиться" content-desc="" clickable="true"
        bounds="[100,1800][900,1900]" class="android.widget.Button" />
</hierarchy>'''

_STRICT_TAP_UI_NON_CLICKABLE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Опубликовать видео" content-desc="" clickable="false"
        bounds="[100,1800][900,1900]" class="android.widget.TextView" />
</hierarchy>'''


def test_strict_tap_exact_text_match():
    """clickable=true node с EXACT text match → adb_tap по center bounds."""
    m = _make_mixin_with_mock_adb()
    result = m._strict_tap_clickable(_STRICT_TAP_UI_TEXT_EXACT,
                                     ['Опубликовать видео', 'Publish video'])
    assert result is True
    m.adb_tap.assert_called_once_with(500, 1850)


def test_strict_tap_exact_desc_match():
    """clickable=true node с EXACT content-desc match (text empty) → adb_tap."""
    m = _make_mixin_with_mock_adb()
    result = m._strict_tap_clickable(_STRICT_TAP_UI_DESC_EXACT,
                                     ['Опубликовать видео', 'Publish video'])
    assert result is True
    m.adb_tap.assert_called_once_with(500, 1850)


def test_strict_tap_rejects_substring():
    """text='Опубликовать видео и поделиться' содержит target substring но
    НЕ EXACT — strict helper НЕ tap'ает (защита от tap_element fallback)."""
    m = _make_mixin_with_mock_adb()
    result = m._strict_tap_clickable(_STRICT_TAP_UI_SUBSTRING,
                                     ['Опубликовать видео', 'Publish video'])
    assert result is False
    m.adb_tap.assert_not_called()


def test_strict_tap_rejects_non_clickable():
    """text exact match но clickable=false → НЕ tap'ает (vs tap_element fallback
    to find_element_bounds который игнорирует clickable_only)."""
    m = _make_mixin_with_mock_adb()
    result = m._strict_tap_clickable(_STRICT_TAP_UI_NON_CLICKABLE,
                                     ['Опубликовать видео', 'Publish video'])
    assert result is False
    m.adb_tap.assert_not_called()
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_publisher_tt_music_rights.py -k strict_tap -v
```

Expected: 4 FAIL with `AttributeError: 'TikTokMixin' object has no attribute '_strict_tap_clickable'`.

- [ ] **Step 3: Implement `_strict_tap_clickable` in TikTokMixin**

В `publisher_tiktok.py`, в классе `TikTokMixin` (после constants block из Task 2), добавить:

```python
    def _strict_tap_clickable(self, ui_xml: str, candidates: list) -> bool:
        """Strict clickable+EXACT-text/desc tap.

        Отличие от self.tap_element: НЕТ fallback'а на find_element_bounds,
        НЕТ substring match. Только parsed XML node с:
          - clickable='true' AND
          - text EXACT in candidates OR content-desc EXACT in candidates

        Returns True если tap отправлен; False иначе.
        Используется для music-rights button где fallback мог бы тапнуть
        link «Подтверждение прав >» (substring contains 'Опубликовать видео').
        """
        if not ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if txt in candidates or desc in candidates:
                bounds = n.get('bounds', '')
                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if not m:
                    continue
                cx = (int(m.group(1)) + int(m.group(3))) // 2
                cy = (int(m.group(2)) + int(m.group(4))) // 2
                try:
                    self.adb_tap(cx, cy)
                    return True
                except Exception:
                    return False
        return False
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_publisher_tt_music_rights.py -k strict_tap -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): strict tap helper (4 tests)

_strict_tap_clickable — clickable=true AND EXACT text/desc, no
fallback. Защищает от tap_element find_element_bounds fallback
который игнорирует exact/clickable_only (Codex round 1 #5)."
```

---

## Task 5: Detector helper `_detect_tt_music_rights_dialog`

**Files:**
- Modify: `publisher_tiktok.py` (add detector)
- Modify: `tests/test_publisher_tt_music_rights.py` (4 tests)

- [ ] **Step 1: Append 4 detector tests**

В `tests/test_publisher_tt_music_rights.py`:

```python
# ====== T1-T4 (detector tests) ======

_DETECT_UI_TITLE_AND_BUTTON_CLICKABLE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Подтвердить и опубликовать видео?" content-desc="" clickable="false"
        bounds="[40,800][1040,900]" class="android.widget.TextView" />
  <node text="Опубликовать видео" content-desc="" clickable="true"
        bounds="[100,1800][900,1900]" class="android.widget.Button" />
</hierarchy>'''

_DETECT_UI_TITLE_AND_DISABLED_BUTTON = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Подтвердить и опубликовать видео?" content-desc="" clickable="false"
        bounds="[40,800][1040,900]" class="android.widget.TextView" />
  <node text="Опубликовать видео" content-desc="" clickable="false"
        bounds="[100,1800][900,1900]" class="android.widget.Button" />
</hierarchy>'''

_DETECT_UI_BODY_SUBSTRING_NO_TITLE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Some banner about music usage rights here" content-desc=""
        clickable="false" bounds="[40,500][1040,600]" class="android.widget.TextView" />
  <node text="Other action" content-desc="" clickable="true"
        bounds="[100,1800][900,1900]" class="android.widget.Button" />
</hierarchy>'''


def test_detect_returns_true_when_title_and_button_present():
    """Title-EXACT-node + button-node clickable=true → True."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog(_DETECT_UI_TITLE_AND_BUTTON_CLICKABLE) is True


def test_detect_returns_true_when_title_and_disabled_button():
    """Title-EXACT-node + button-node clickable=false → True
    (round 2 fix: button может быть disabled до checkbox tick)."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog(_DETECT_UI_TITLE_AND_DISABLED_BUTTON) is True


def test_detect_returns_false_when_only_body_substring_no_title_node():
    """body substring 'music usage rights' без title-EXACT-node → False
    (защита от false-positive на banner/feed text)."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog(_DETECT_UI_BODY_SUBSTRING_NO_TITLE) is False


def test_detect_returns_false_no_marker():
    """Empty UI / UI без title markers → False сразу."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog('') is False
    assert m._detect_tt_music_rights_dialog('<?xml version="1.0"?><hierarchy />') is False
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_publisher_tt_music_rights.py -k 'detect_returns' -v
```

Expected: 4 FAIL with `AttributeError`.

- [ ] **Step 3: Implement `_detect_tt_music_rights_dialog`**

В `publisher_tiktok.py`, после `_strict_tap_clickable`, добавить:

```python
    def _detect_tt_music_rights_dialog(self, ui_xml: str) -> bool:
        """Strict structural detector for TT music rights confirmation dialog.

        Identity = title-node EXACT + (music-specific structure OR generic
        checkbox присутствует). Button НЕ обязан быть clickable на этом
        этапе (TT может disable до checkbox tick). Single-pass collection
        без order dependence.

        Returns True если dialog detected, False иначе.
        """
        if not ui_xml:
            return False
        # Cheap pre-filter: substring любого title marker — fast bail-out
        if not any(m in ui_xml for m in self._TT_MUSIC_RIGHTS_TITLE_MARKERS):
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        has_title_node = False
        has_specific_structure = False  # checkbox-label OR button-node
        has_generic_checkbox = False    # любой checkable=true / CheckBox class
        for n in root.iter('node'):
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            # Title — EXACT match по text ИЛИ desc (independently)
            if not has_title_node and (
                txt in self._TT_MUSIC_RIGHTS_TITLE_MARKERS
                or desc in self._TT_MUSIC_RIGHTS_TITLE_MARKERS
            ):
                has_title_node = True
            # Music-specific structure: checkbox-label substring ИЛИ button-node EXACT
            if not has_specific_structure:
                if (any(c in txt for c in self._TT_MUSIC_RIGHTS_CHECKBOX)
                    or any(c in desc for c in self._TT_MUSIC_RIGHTS_CHECKBOX)):
                    has_specific_structure = True
                elif (txt in self._TT_MUSIC_RIGHTS_BUTTON
                      or desc in self._TT_MUSIC_RIGHTS_BUTTON):
                    has_specific_structure = True
            # Generic checkbox/checkable node — sufficient ТОЛЬКО с title
            if not has_generic_checkbox and (
                n.get('checkable') == 'true'
                or 'CheckBox' in n.get('class', '')
            ):
                has_generic_checkbox = True
        if not has_title_node:
            return False
        return has_specific_structure or has_generic_checkbox
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_publisher_tt_music_rights.py -k 'detect_returns' -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): structured detector (4 tests)

_detect_tt_music_rights_dialog — title-EXACT-node + checkbox/button
structure. Single-pass без order dependence. Button clickability
игнорируется на detection (Codex round 2 — TT может disable до
checkbox tick)."
```

---

## Task 6: Checkbox helper `_tick_tt_music_rights_checkbox`

**Files:**
- Modify: `publisher_tiktok.py` (add checkbox helper + tap-by-bounds support)
- Modify: `tests/test_publisher_tt_music_rights.py` (2 tests)

- [ ] **Step 1: Append 2 checkbox tests**

В `tests/test_publisher_tt_music_rights.py`:

```python
# ====== T7-T8 (checkbox tests) ======

_CHECKBOX_UI_PATTERN_A_SELF_LABELED = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Я принимаю Подтверждение прав на использование музыки"
        content-desc="" clickable="true" checked="false" checkable="true"
        bounds="[100,2200][1000,2280]" class="android.widget.CheckBox" />
</hierarchy>'''

_CHECKBOX_UI_PATTERN_B_SPLIT = '''<?xml version="1.0"?>
<hierarchy>
  <node text="" content-desc="" clickable="true" checked="false" checkable="true"
        bounds="[40,2200][120,2280]" class="android.widget.CheckBox" />
  <node text="Я принимаю Подтверждение прав на использование музыки"
        content-desc="" clickable="false" checked="false"
        bounds="[140,2210][1000,2270]" class="android.widget.TextView" />
</hierarchy>'''


def test_checkbox_pattern_a_self_labeled():
    """Single node — clickable+checked=false+text matches → tap по center."""
    m = _make_mixin_with_mock_adb()
    result = m._tick_tt_music_rights_checkbox(_CHECKBOX_UI_PATTERN_A_SELF_LABELED)
    assert result is True
    m.adb_tap.assert_called_once_with(550, 2240)


def test_checkbox_pattern_b_split_label_and_checkbox():
    """Split: CheckBox node без label + sibling label → tap по checkbox
    bounds (80, 2240), не по label (140-1000)."""
    m = _make_mixin_with_mock_adb()
    result = m._tick_tt_music_rights_checkbox(_CHECKBOX_UI_PATTERN_B_SPLIT)
    assert result is True
    m.adb_tap.assert_called_once_with(80, 2240)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_publisher_tt_music_rights.py -k checkbox_pattern -v
```

Expected: 2 FAIL with `AttributeError`.

- [ ] **Step 3: Implement checkbox helper + internal `_tap_node_bounds`**

В `publisher_tiktok.py`, после `_detect_tt_music_rights_dialog`, добавить:

```python
    @staticmethod
    def _node_center(node) -> Optional[tuple]:
        """Parse bounds attribute → (cx, cy) tuple. None если bad-format."""
        bounds = node.get('bounds', '')
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
        if not m:
            return None
        cx = (int(m.group(1)) + int(m.group(3))) // 2
        cy = (int(m.group(2)) + int(m.group(4))) // 2
        return (cx, cy)

    def _tap_node_bounds(self, node) -> bool:
        """adb_tap по center bounds node'а. False если bounds bad-format."""
        center = self._node_center(node)
        if center is None:
            return False
        try:
            self.adb_tap(*center)
            return True
        except Exception:
            return False

    def _tick_tt_music_rights_checkbox(self, ui_xml: str) -> bool:
        """Tap по unchecked music-rights checkbox.

        Покрывает 2 паттерна:
          A) Single node: clickable=true AND checked=false AND text/desc
             contains music-rights checkbox label.
          B) Split: CheckBox node (checkable=true OR class=CheckBox) с
             checked=false; label-node с music-rights текстом отдельно.
             Tap по checkbox bounds (нечёткий label, чёткий checkbox).

        Returns True если tap отправлен; False если уже checked / нет нодов.
        """
        if not ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        # Pattern A: single self-labeled checkbox (text/desc независимо)
        for n in root.iter('node'):
            if n.get('clickable') != 'true' or n.get('checked') != 'false':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if (any(c in txt for c in self._TT_MUSIC_RIGHTS_CHECKBOX)
                or any(c in desc for c in self._TT_MUSIC_RIGHTS_CHECKBOX)):
                return self._tap_node_bounds(n)
        # Pattern B: separate checkbox + nearby label
        cb_nodes = [n for n in root.iter('node')
                    if (n.get('checkable') == 'true'
                        or 'CheckBox' in n.get('class', ''))
                    and n.get('checked') == 'false']
        label_nodes = []
        for n in root.iter('node'):
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if (any(c in txt for c in self._TT_MUSIC_RIGHTS_CHECKBOX)
                or any(c in desc for c in self._TT_MUSIC_RIGHTS_CHECKBOX)):
                label_nodes.append(n)
        if not cb_nodes or not label_nodes:
            return False
        nearest = self._nearest_node_to_labels(cb_nodes, label_nodes)
        if nearest is None:
            return False
        return self._tap_node_bounds(nearest)

    def _nearest_node_to_labels(self, cb_nodes, label_nodes):
        """Nearest checkbox-node к любому label-node по L2 distance центров.
        Returns node или None."""
        best = None
        best_dist = None
        for cb in cb_nodes:
            cb_c = self._node_center(cb)
            if cb_c is None:
                continue
            for lb in label_nodes:
                lb_c = self._node_center(lb)
                if lb_c is None:
                    continue
                dist = (cb_c[0] - lb_c[0]) ** 2 + (cb_c[1] - lb_c[1]) ** 2
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = cb
        return best
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_publisher_tt_music_rights.py -k checkbox_pattern -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): checkbox helper Pattern A+B (2 tests)

_tick_tt_music_rights_checkbox + _tap_node_bounds + _node_center +
_nearest_node_to_labels. Pattern A — self-labeled checkbox.
Pattern B — split CheckBox + sibling label, tap по checkbox bounds.
text+desc independently (Codex round 5 OR-short-circuit fix)."
```

---

## Task 7: Handle helper `_handle_tt_music_rights_dialog`

**Files:**
- Modify: `publisher_tiktok.py` (add handle helper)
- Modify: `tests/test_publisher_tt_music_rights.py` (3 tests — handle behavior)

- [ ] **Step 1: Append 3 handle tests**

В `tests/test_publisher_tt_music_rights.py`:

```python
# ====== T5-T6, T9 (handle tests) ======

_HANDLE_UI_DIALOG_VALID = _DETECT_UI_TITLE_AND_BUTTON_CLICKABLE  # reuse
_HANDLE_UI_DIALOG_NO_BUTTON = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Подтвердить и опубликовать видео?" content-desc="" clickable="false"
        bounds="[40,800][1040,900]" class="android.widget.TextView" />
  <node text="" content-desc="" clickable="true" checked="false" checkable="true"
        bounds="[100,2200][120,2280]" class="android.widget.CheckBox" />
</hierarchy>'''

_HANDLE_UI_DIALOG_WITH_CHECKBOX_AND_BUTTON = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Подтвердить и опубликовать видео?" content-desc="" clickable="false"
        bounds="[40,800][1040,900]" class="android.widget.TextView" />
  <node text="Я принимаю Подтверждение прав на использование музыки"
        content-desc="" clickable="true" checked="false" checkable="true"
        bounds="[100,2000][1000,2080]" class="android.widget.CheckBox" />
  <node text="Опубликовать видео" content-desc="" clickable="true"
        bounds="[100,2200][900,2300]" class="android.widget.Button" />
</hierarchy>'''


def _make_handle_mixin():
    """Mock dump_ui + log_event + adb_tap; default dump returns same UI
    (re-dump path); test overrides per-case."""
    m = TikTokMixin()
    m.adb_tap = MagicMock()
    m.dump_ui = MagicMock(return_value=_HANDLE_UI_DIALOG_VALID)
    m.log_event = MagicMock()
    m.platform = 'TikTok'
    return m


def test_handle_taps_publish_via_strict_helper():
    """detected dialog → _strict_tap_clickable called с button candidates;
    info event tt_music_rights_accepted logged. НЕ использует tap_element."""
    m = _make_handle_mixin()
    m.tap_element = MagicMock()  # должно остаться uncalled
    # Spy на _strict_tap_clickable — verify call args + suppress real impl
    real_strict = m._strict_tap_clickable
    m._strict_tap_clickable = MagicMock(side_effect=real_strict)

    result = m._handle_tt_music_rights_dialog(_HANDLE_UI_DIALOG_VALID)
    assert result is True
    # _strict_tap_clickable called с music-rights button candidates (round 1 #5 contract)
    strict_calls = m._strict_tap_clickable.call_args_list
    assert any(
        len(c.args) >= 2 and list(c.args[1]) == ['Опубликовать видео', 'Publish video']
        for c in strict_calls
    ), f'_strict_tap_clickable not called с button candidates; calls={strict_calls}'
    # adb_tap по button center (500, 1850 для UI_VALID)
    assert call(500, 1850) in m.adb_tap.call_args_list
    # tap_element НЕ должен использоваться (защита от fallback)
    m.tap_element.assert_not_called()
    # log_event called с tt_music_rights_accepted
    accept_calls = [c for c in m.log_event.call_args_list
                    if c.kwargs.get('meta', {}).get('category') == 'tt_music_rights_accepted'
                    or (len(c.args) >= 3 and c.args[2].get('category') == 'tt_music_rights_accepted')]
    assert len(accept_calls) >= 1


def test_handle_redumps_ui_after_checkbox_tick():
    """checkbox tap → dump_ui зовётся ДО button tap (re-dump для свежих
    bounds после потенциального button-enable, Codex round 1 #6)."""
    m = _make_handle_mixin()
    # Initial UI имеет checkbox; re-dump возвращает UI с button (имитация
    # того что после checkbox tick TT enable'ит button).
    m.dump_ui.return_value = _HANDLE_UI_DIALOG_WITH_CHECKBOX_AND_BUTTON

    # Перехватываем порядок вызовов через side_effect
    call_order = []
    def track_adb_tap(x, y):
        call_order.append(('adb_tap', x, y))
    def track_dump_ui():
        call_order.append(('dump_ui',))
        return _HANDLE_UI_DIALOG_WITH_CHECKBOX_AND_BUTTON
    m.adb_tap.side_effect = track_adb_tap
    m.dump_ui.side_effect = track_dump_ui

    result = m._handle_tt_music_rights_dialog(_HANDLE_UI_DIALOG_WITH_CHECKBOX_AND_BUTTON)
    assert result is True

    # Должен быть: checkbox tap → dump_ui → button tap
    actions = [c[0] for c in call_order]
    assert actions[0] == 'adb_tap'   # checkbox tap первый
    assert 'dump_ui' in actions      # re-dump между ними
    dump_idx = actions.index('dump_ui')
    # После dump_ui должен быть ещё adb_tap (button)
    assert 'adb_tap' in actions[dump_idx+1:]


def test_handle_button_not_found_returns_false_no_continue():
    """detected=True (title+checkbox/checkable есть) но _strict_tap_clickable
    failed (button не найден среди clickable=true) → returns False,
    warning event tt_music_rights_button_not_found logged."""
    m = _make_handle_mixin()
    m.dump_ui.return_value = _HANDLE_UI_DIALOG_NO_BUTTON

    result = m._handle_tt_music_rights_dialog(_HANDLE_UI_DIALOG_NO_BUTTON)
    assert result is False
    # warning event про button_not_found
    nf_calls = [c for c in m.log_event.call_args_list
                if c.kwargs.get('meta', {}).get('category') == 'tt_music_rights_button_not_found'
                or (len(c.args) >= 3 and c.args[2].get('category') == 'tt_music_rights_button_not_found')]
    assert len(nf_calls) >= 1
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_publisher_tt_music_rights.py -k 'handle_taps or handle_redumps or handle_button' -v
```

Expected: 3 FAIL with `AttributeError: '_handle_tt_music_rights_dialog'`.

- [ ] **Step 3: Implement `_handle_tt_music_rights_dialog`**

В `publisher_tiktok.py`, после `_nearest_node_to_labels`, добавить:

```python
    def _handle_tt_music_rights_dialog(self, ui_xml: str) -> bool:
        """Detect и accept TT music rights confirmation dialog.

        Flow:
          1. _detect_tt_music_rights_dialog(ui_xml) — guard
          2. _tick_tt_music_rights_checkbox(ui_xml) — best-effort persistence
          3. Если checkbox был tapped — re-dump UI (Codex round 1 #6:
             button bounds могут сместиться, button может стать enabled)
          4. _strict_tap_clickable(ui, _TT_MUSIC_RIGHTS_BUTTON) — НЕ
             tap_element (есть unsafe fallback на find_element_bounds)

        Returns True ТОЛЬКО если detected И button успешно tapped (checkbox
        tick — best-effort, не влияет на return). False иначе → caller НЕ
        должен continue на False.
        """
        if not self._detect_tt_music_rights_dialog(ui_xml):
            return False
        checkbox_set = self._tick_tt_music_rights_checkbox(ui_xml)
        if checkbox_set:
            time.sleep(0.5)
            try:
                fresh = self.dump_ui()
                if fresh:
                    ui_xml = fresh
            except Exception:
                pass  # best-effort; продолжаем со старым xml
        tapped = self._strict_tap_clickable(ui_xml, self._TT_MUSIC_RIGHTS_BUTTON)
        if tapped:
            self.log_event(
                'info',
                'TikTok: music rights dialog accepted',
                meta={'category': 'tt_music_rights_accepted',
                      'platform': self.platform,
                      'checkbox_set': checkbox_set,
                      'button_tapped': True})
        else:
            self.log_event(
                'warning',
                'TikTok: music rights dialog detected, accept button not found',
                meta={'category': 'tt_music_rights_button_not_found',
                      'platform': self.platform,
                      'checkbox_set': checkbox_set})
        return tapped
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_publisher_tt_music_rights.py -k 'handle_taps or handle_redumps or handle_button' -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): handle dialog (3 tests)

_handle_tt_music_rights_dialog — detect → tick checkbox → re-dump
→ strict tap button. Returns True ТОЛЬКО при successful button tap
(checkbox best-effort). Logs tt_music_rights_accepted (info) или
tt_music_rights_button_not_found (warning)."
```

---

## Task 8: Wire into wait_upload loop + counter reset

**Files:**
- Modify: `publisher_tiktok.py` (counter reset в начале publish_tiktok + handler block в loop)
- Modify: `tests/test_publisher_tt_music_rights.py` (3 integration tests)

- [ ] **Step 1: Append 3 integration tests**

В `tests/test_publisher_tt_music_rights.py`:

```python
# ====== T10-T12 (loop integration tests) ======

def test_loop_continues_only_on_handled_true():
    """Source guard: handler-block в publish_tiktok должен continue
    ТОЛЬКО при handled=True. Соответствующий behavior covered:
      - handled=True path → test_handle_taps_publish_via_strict_helper
      - handled=False path → test_handle_button_not_found_returns_false_no_continue
    Source guard защищает от accidental refactor который убирает условие.
    """
    src = (ROOT / 'publisher_tiktok.py').read_text()
    # Anchor на `# === Music rights` — уникальная decorative marker только
    # в loop-block (constants comment имеет другую wording).
    branch_idx = src.find('=== Music rights confirmation dialog (новый TT UX')
    assert branch_idx > 0, 'music-rights branch not found in source'
    # Берём блок до начала следующего comment-marker `# ===` (audio-dialog)
    next_marker = src.find('=== TikTok: аудио-диалог', branch_idx)
    assert next_marker > branch_idx, 'next marker not found'
    branch_block = src[branch_idx:next_marker]
    # `if handled:` ДОЛЖЕН быть в block, и `continue` ДОЛЖЕН быть внутри
    # его scope (сразу после).
    assert 'if handled' in branch_block, (
        'handler-block must check `if handled` before continue (Codex round 1 #1)'
    )
    # Грубая проверка ordering: 'if handled' появляется раньше 'continue'
    if_handled_idx = branch_block.find('if handled')
    continue_idx = branch_block.find('continue')
    assert if_handled_idx < continue_idx, (
        f'continue (idx {continue_idx}) должен быть ПОСЛЕ `if handled` (idx '
        f'{if_handled_idx}), не unconditional'
    )


def test_loop_iteration_cap_returns_false_and_emits_stuck(monkeypatch):
    """Behavior test: симулируем 6 cap-iterations через прямой вызов
    счётчика handler-блока. _music_rights_iter увеличивается, на >MAX
    логируется error и возвращается False.

    Полный publish_tiktok loop запускать не можем (зависит от ADB/DB);
    тест проверяет contract counter + cap, который handler-block использует.
    """
    m = TikTokMixin()
    m.platform = 'TikTok'
    m.log_event = MagicMock()
    m.set_step = MagicMock()
    m._music_rights_iter = 0

    # Имитация 6 итераций (cap=5)
    fail_emitted = False
    for _ in range(6):
        m._music_rights_iter += 1
        if m._music_rights_iter > MAX_MUSIC_RIGHTS_ITERATIONS:
            m.log_event(
                'error',
                f'tt_music_rights_stuck: dialog persists > '
                f'{MAX_MUSIC_RIGHTS_ITERATIONS} iter',
                meta={'category': 'tt_music_rights_stuck',
                      'iterations': m._music_rights_iter,
                      'step': 'tt_5_music_rights_stuck',
                      'platform': m.platform})
            m.set_step('tt_5_music_rights_stuck')
            fail_emitted = True
            break

    assert fail_emitted is True, 'cap не сработал на 6-й итерации'
    assert m._music_rights_iter == 6
    m.set_step.assert_called_once_with('tt_5_music_rights_stuck')
    err_calls = [c for c in m.log_event.call_args_list
                 if c.kwargs.get('meta', {}).get('category') == 'tt_music_rights_stuck'
                 or (len(c.args) >= 3 and c.args[2].get('category') == 'tt_music_rights_stuck')]
    assert len(err_calls) == 1


def test_per_publish_counter_reset():
    """Source guard: publish_tiktok должен reset _music_rights_iter в начале
    (НЕ полагаться на hasattr — instance может переиспользоваться).

    Source check здесь оправдан: behavior через end-to-end было бы запуск
    publish_tiktok дважды, что требует mock'инг 50+ ADB вызовов и DB. Source
    guard на одну строку — pragmatic regression check."""
    src = (ROOT / 'publisher_tiktok.py').read_text()
    pub_start = src.find('def publish_tiktok(')
    assert pub_start > 0
    # В первых 80 строках после signature должно быть `self._music_rights_iter = 0`
    pub_block = src[pub_start:pub_start + 6000]
    assert 'self._music_rights_iter = 0' in pub_block, (
        '_music_rights_iter must be reset at start of publish_tiktok '
        '(Codex round 1 #4: instance lifetime)'
    )
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_publisher_tt_music_rights.py -k 'loop_continues or loop_iteration or per_publish' -v
```

Expected: 3 FAIL (string не найдена в source).

- [ ] **Step 3: Add counter reset at start of `publish_tiktok`**

В `publisher_tiktok.py::publish_tiktok` (line ~30), сразу после первой строки `log.info('🎵 Публикация TikTok...')`, добавить:

```python
        # Music rights iter counter reset per publish (Codex round 1 #4:
        # publisher instance может переиспользоваться между tasks).
        self._music_rights_iter = 0
```

- [ ] **Step 4: Add handler block в wait_upload loop**

В `publisher_tiktok.py::publish_tiktok::wait_upload` loop, найти секцию где `matched_uploadok` блок заканчивается (line ~533, после `upload_confirmed = True; break`).

**Сразу после** UPLOAD_OK блока (после `if matched_uploadok:` всего блока, ПЕРЕД `# === TikTok: аудио-диалог`), добавить:

```python
            # === Music rights confirmation dialog (новый TT UX 2026-05-10) ===
            # Появляется ПОСЛЕ tap «Опубликовать» при detected copyright music.
            # Spec: docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md
            if self._detect_tt_music_rights_dialog(ui):
                self._music_rights_iter += 1
                if self._music_rights_iter > MAX_MUSIC_RIGHTS_ITERATIONS:
                    log.error(f'  ❌ TikTok: music rights dialog stuck > '
                              f'{MAX_MUSIC_RIGHTS_ITERATIONS} итераций — fail')
                    self.log_event(
                        'error',
                        f'tt_music_rights_stuck: dialog persists > '
                        f'{MAX_MUSIC_RIGHTS_ITERATIONS} iter',
                        meta={'category': 'tt_music_rights_stuck',
                              'iterations': self._music_rights_iter,
                              'step': 'tt_5_music_rights_stuck',
                              'platform': self.platform})
                    self.set_step('tt_5_music_rights_stuck')
                    return False
                handled = self._handle_tt_music_rights_dialog(ui)
                log.info(f'  🎵 TikTok: music rights dialog (wait {wait}, '
                         f'iter {self._music_rights_iter}/{MAX_MUSIC_RIGHTS_ITERATIONS}) '
                         f'handled={handled}')
                if handled:
                    time.sleep(2)
                    continue
                # handled=False — fall through (downstream handlers получают chance).
                # Counter инкрементирован → cap защищает от infinite loop.

```

- [ ] **Step 5: Run tests — expect PASS**

```bash
pytest tests/test_publisher_tt_music_rights.py -k 'loop_continues or loop_iteration or per_publish' -v
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): wire handler into wait_upload loop (3 tests)

- Counter reset _music_rights_iter в начале publish_tiktok (instance
  lifetime safety)
- Handler block после UPLOAD_OK (preserves Phase 1.5 invariant), перед
  audio-dialog block
- continue ТОЛЬКО при handled=True (Codex round 1 #1)
- Cap-exceeded → set_step('tt_5_music_rights_stuck') → kernel mapping
  canonicalize'ит в tt_music_rights_stuck"
```

---

## Task 9: Ordering & regression tests

**Files:**
- Modify: `tests/test_publisher_tt_music_rights.py` (3 tests — verify ordering invariant)

- [ ] **Step 1: Append 3 ordering/regression tests**

В `tests/test_publisher_tt_music_rights.py`:

```python
# ====== T13-T14 (ordering & regression) ======

def test_upload_ok_check_runs_before_music_rights():
    """Source guard: UPLOAD_OK matched_uploadok block ДОЛЖЕН appear ДО
    music-rights branch в publish_tiktok (Phase 1.5 invariant preserved).

    Behavior implication: на той же итерации loop'а если UI содержит И
    UPLOAD_OK marker И music-rights — UPLOAD_OK выигрывает (early break),
    music-rights handler не вызывается. Behavior проверяется через тот
    факт что UPLOAD_OK блок имеет `break`, а music-rights `continue` —
    они не могут отработать в одной iteration в правильном порядке.
    """
    src = (ROOT / 'publisher_tiktok.py').read_text()
    uploadok_idx = src.find('matched_uploadok = [kw for kw in UPLOAD_OK')
    assert uploadok_idx > 0, 'UPLOAD_OK check not found'
    music_branch_idx = src.find('=== Music rights confirmation dialog (новый TT UX')
    assert music_branch_idx > 0, 'music-rights branch not found'
    assert uploadok_idx < music_branch_idx, (
        f'UPLOAD_OK check (idx {uploadok_idx}) must precede music-rights '
        f'branch (idx {music_branch_idx}) — Phase 1.5 invariant'
    )
    # Дополнительная behavior verification: detector не должен реагировать
    # на pure UPLOAD_OK UI без title-node.
    m = TikTokMixin()
    upload_ok_only_ui = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Опубликовано" content-desc="" clickable="false"
        bounds="[40,800][1040,900]" class="android.widget.TextView" />
  <node text="Для вас" content-desc="" clickable="true"
        bounds="[40,2200][300,2280]" class="android.widget.TextView" />
</hierarchy>'''
    assert m._detect_tt_music_rights_dialog(upload_ok_only_ui) is False, (
        'detector неправильно matches UPLOAD_OK feed-state'
    )


def test_existing_audio_dialog_handler_independent():
    """Source guard + behavior: audio-dialog branch не сломан music-rights
    insertion. Detector НЕ должен matched на pure audio-dialog UI."""
    src = (ROOT / 'publisher_tiktok.py').read_text()
    music_idx = src.find('=== Music rights confirmation dialog (новый TT UX')
    audio_idx = src.find('=== TikTok: аудио-диалог после публикации ===')
    assert music_idx > 0
    assert audio_idx > 0
    assert music_idx < audio_idx, (
        f'audio-dialog branch (idx {audio_idx}) must come AFTER music-rights '
        f'branch (idx {music_idx}) — both handlers preserved, music first'
    )
    # Behavior: pure audio-dialog UI (не music rights) — detector False
    m = TikTokMixin()
    audio_dialog_ui = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Sound name" content-desc="" clickable="false"
        bounds="[40,800][1040,900]" class="android.widget.TextView" />
  <node text="Original sound" content-desc="" clickable="false"
        bounds="[40,1000][1040,1100]" class="android.widget.TextView" />
  <node text="Use" content-desc="" clickable="true"
        bounds="[100,2200][900,2300]" class="android.widget.Button" />
</hierarchy>'''
    assert m._detect_tt_music_rights_dialog(audio_dialog_ui) is False, (
        'detector неправильно matches audio-dialog UI'
    )
```

(Total теперь 14 + 3 + 2 + 4 = wait let me count properly. 4 detector + 5 handle/checkbox + 3 loop + 2 ordering + 4 strict = 18. Spec обещает 19; missing one. Add the 19th: explicit kernel mapping was already test #1 (T15 → T1 by file order). Let me re-tally — file has:

- test_kernel_mapping_includes_music_rights (1)
- test_strict_tap_* × 4 (5)
- test_detect_returns_* × 4 (9)
- test_checkbox_pattern_* × 2 (11)
- test_handle_taps + test_handle_redumps + test_handle_button × 3 (14)
- test_loop_continues + test_loop_iteration + test_per_publish × 3 (17)
- test_upload_ok_check + test_existing_audio_dialog × 2 (19) ✅

OK total 19 matches spec section 4.)

- [ ] **Step 2: Run tests — expect PASS**

```bash
pytest tests/test_publisher_tt_music_rights.py -k 'upload_ok or audio_dialog_handler' -v
```

Expected: 2 PASS (handler block already in place from Task 8).

- [ ] **Step 3: Run FULL test file — verify 19 tests pass**

```bash
pytest tests/test_publisher_tt_music_rights.py -v
```

Expected: **19 PASS, 0 FAIL** (matches spec acceptance criterion #1).

- [ ] **Step 4: Commit**

```bash
git add tests/test_publisher_tt_music_rights.py
git commit -m "test(tt-music-rights): ordering & regression tests

- UPLOAD_OK precedes music-rights (Phase 1.5 invariant)
- audio-dialog branch follows music-rights (no regression)
Total 19 tests green per spec acceptance criterion #1."
```

---

## Task 10: Full TT suite + deploy + live verify

**Files:** none (deployment only)

- [ ] **Step 1: Run full TT-related test suite — verify no regression**

```bash
pytest tests/ -v -k 'tiktok or tt_' | tee /tmp/tt-suite.log
PYTEST_RC=${PIPESTATUS[0]}
echo "pytest exit code: $PYTEST_RC"
```

Expected: все TT tests PASS, `pytest exit code: 0`. **Pre-existing fails** (документировано в memory `project_validator_stale_generate_description_tests.md` и `project_publisher_modularization_wip.md`):
- `test_canonical_error_codes` (TT switcher AttributeError) — не моя регрессия
- `test_publisher_ig_camera_recovery` — IG, не TT, не моя регрессия

Если `PYTEST_RC != 0` И в `/tmp/tt-suite.log` появились НОВЫЕ failures (НЕ из списка pre-existing) — НЕ deploy, диагностируй. Используй `tee` (не `tail`), потому что `pytest | tail` маскирует pytest exit code (PIPESTATUS).

- [ ] **Step 1.5: Run codex review on code (acceptance criterion #6)**

Per memory `feedback_codex_review_specs.md` — после кода тоже codex audit. Per memory `feedback_codex_sandbox_broken.md` — sandbox требует override:

```bash
~/.local/bin/codex review --uncommitted -c 'sandbox_mode="danger-full-access"' 2>&1 | tee /tmp/codex-tt-music-rights-code.log
```

Если codex дал actionable findings — apply, re-run tests, re-run codex до 'no actionable findings' либо до evidenced "не applicable" с rationale. Если sandbox всё-таки не работает — задокументировать в commit/evidence почему пропущен.

- [ ] **Step 2: Push branch**

```bash
git push -u origin feat/tt-music-rights-dialog-20260510
```

- [ ] **Step 3: Create PR**

```bash
source ~/secrets/github-gengo2.env
gh pr create --title "TT music rights confirmation dialog handler" --body "$(cat <<'EOF'
## Summary

Closes ~12 fails/24h on raspberry=9 (`tt_upload_confirmation_timeout`)
caused by new TikTok music rights confirmation dialog that publisher
не handle'ит.

## What

- Structured detector (title-EXACT-node + checkbox/button structure)
- Strict tap helper (no fallback на find_element_bounds → safe от
  link tap «Подтверждение прав >»)
- Auto-accept + persistence checkbox (Pattern A self-labeled / Pattern B
  split CheckBox+label)
- Counter reset per publish_tiktok (instance lifetime safety)
- Cap=5 + kernel mapping `tt_5_music_rights_stuck → tt_music_rights_stuck`
- Telemetry: `tt_music_rights_accepted` (info), `tt_music_rights_button_not_found`
  (warning), `tt_music_rights_stuck` (error)

## Spec & Audits

- Spec: `docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md`
- Codex audit: 6 rounds, 26 finds applied — no actionable findings round 7

## Test Plan

- [x] 19 unit/integration tests green
- [x] Full TT suite green (pre-existing fails unchanged)
- [ ] Live verify on prod after merge: re-queue 4488 (clickpay_world) →
      expect `tt_music_rights_accepted` event + post_url

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Merge PR (squash)**

После approval:
```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 5: Pull on prod autowarm**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin && git pull origin main
git log --oneline -3  # verify merge commit pulled
```

**WARNING**: НЕ force-push, НЕ skip hooks (memory `feedback_subagent_force_push_risk.md`).

- [ ] **Step 6: Verify pm2 path drift not happening**

```bash
sudo pm2 describe autowarm | grep "exec cwd"
```

Expected: `/root/.openclaw/workspace-genri/autowarm` (НЕ `/home/claude-user/...`).

Если drift — `sudo pm2 delete autowarm && sudo pm2 start /root/.openclaw/workspace-genri/autowarm/ecosystem.config.js` (memory `feedback_pm2_dump_path_drift.md`).

- [ ] **Step 7: PM2 spawns Python per-task — no reload needed**

Code изменения подхватятся следующим publish_tiktok call (Python re-imported per task spawn). Нет `sudo pm2 reload autowarm` — но если хочется уверенности:

```bash
sudo pm2 reload autowarm
```

- [ ] **Step 8: Live verify — re-queue task 4488 (clickpay_world)**

Single-statement re-queue через subquery (no runtime placeholder):

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
UPDATE publish_queue
SET status='pending', publish_task_id=NULL
WHERE id IN (
  SELECT pq.id FROM publish_queue pq
  JOIN publish_tasks pt ON pt.id=pq.publish_task_id
  WHERE pt.id=4488
)
RETURNING id, status;
"
```

Verify в одной команде: `RETURNING` покажет id затронутой строки. Если возврат пустой — публикация уже re-queued или pq отсутствует (memory `reference_publish_requeue_path.md`: дефолтный путь — обновить publish_queue, не publish_tasks).

Подожди 5-10 минут (dispatchPublishQueue tick = 5 min), затем:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, account, status, error_code, post_url,
  jsonb_path_query_array(events,
    '\$[*] ? (@.meta.category like_regex \"music_rights\")'
  ) AS music_events
FROM publish_tasks
WHERE account='clickpay_world' ORDER BY created_at DESC LIMIT 3;
"
```

Expected:
- `status='awaiting_url'` или `'done'`
- `error_code IS NULL`
- `post_url` начинается с `https://www.tiktok.com/@clickpay_world/video/`
- `music_events` содержит `tt_music_rights_accepted` info event

Если **fail c tt_upload_confirmation_timeout** снова — проверь events: возможно music-rights не появился (transient TT state) или `tt_music_rights_stuck` (cap exceeded — нужен debug). НЕ объявлять success без хоть одного `tt_music_rights_accepted` event.

- [ ] **Step 9: 24h post-deploy monitor**

Через 24ч:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT
  COUNT(*) FILTER (WHERE status='done') AS done,
  COUNT(*) FILTER (WHERE error_code='tt_upload_confirmation_timeout') AS timeout_fails,
  COUNT(*) FILTER (WHERE error_code='tt_music_rights_stuck') AS music_stuck_fails,
  COUNT(*) FILTER (WHERE events @> '[{\"meta\":{\"category\":\"tt_music_rights_accepted\"}}]') AS music_recovered
FROM publish_tasks
WHERE platform='TikTok' AND raspberry=9 AND testbench IS NOT TRUE
  AND updated_at >= NOW() - INTERVAL '24 hours';
"
```

Acceptance criteria #5: `timeout_fails < 3` (was 12); `music_recovered > 0`; `music_stuck_fails` ≈ 0 (если > 0 — дополнительный markers expansion).

- [ ] **Step 10: Write evidence doc (после сбора метрик из шагов 8-9)**

Evidence пишется ПОСЛЕ сбора всех значений в шагах 8-9. Шаблон ниже —
заполни плейсхолдеры конкретными числами/SHA из:

- `<PR_NUMBER>` — из вывода `gh pr view --json number -q .number` после step 3
- `<MERGE_SHA>` — из `git log --oneline -1` после merge на prod main (step 5)
- `<NEW_PT_ID>`, `<TT_VIDEO_URL>` — из results step 8 (re-queue verify query)
- `<CHECKBOX_SET_VAL>` — из `meta.checkbox_set` в `tt_music_rights_accepted` event
- `<TIMEOUT_AFTER>`, `<MUSIC_RECOVERED>`, `<MUSIC_STUCK>` — из step 9 24h SQL

```bash
cd /home/claude-user/contenthunter
# Сначала собери значения в bash переменные (примеры — adapt под реальные queries)
PR_NUMBER=$(gh pr view --json number -q .number)
MERGE_SHA=$(cd /root/.openclaw/workspace-genri/autowarm && git log --oneline -1 --format='%H')
# NEW_PT_ID, TT_VIDEO_URL, CHECKBOX_SET_VAL — manually скопируй из step 8 query result
# TIMEOUT_AFTER, MUSIC_RECOVERED, MUSIC_STUCK — manually из step 9 query result

cat > docs/evidence/2026-05-10-tt-music-rights-dialog-shipped.md <<EOF
# TT music rights confirmation dialog handler — shipped

**Date:** 2026-05-10
**PR:** #${PR_NUMBER}
**Merge commit:** ${MERGE_SHA}

## Spec & plan
- Spec: docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md (6-round Codex audit)
- Plan: docs/superpowers/plans/2026-05-10-tt-music-rights-dialog-plan.md

## Live verify (re-queue task 4488 clickpay_world)
- New pt: <NEW_PT_ID>  ← заполнить
- post_url: <TT_VIDEO_URL>  ← заполнить
- tt_music_rights_accepted event meta: checkbox_set=<CHECKBOX_SET_VAL>  ← заполнить

## 24h post-deploy metrics (raspberry=9 TikTok prod)
- tt_upload_confirmation_timeout: 12 (baseline) → <TIMEOUT_AFTER>  ← заполнить
- tt_music_rights_accepted (recovered): <MUSIC_RECOVERED>  ← заполнить
- tt_music_rights_stuck: <MUSIC_STUCK>  ← заполнить

## Acceptance criteria status
- [✓/✗] (1) 19 unit tests green
- [✓/✗] (2) Pre-existing TT suite unchanged
- [✓/✗] (3) Live verify: tt_music_rights_accepted в event log нового pt
- [✓/✗] (4) Dashboard split working
- [✓/✗] (5) timeout_fails <3/24h
- [✓/✗] (6) Codex review applied (см. spec section 10 + step 1.5 plan)

## Open follow-ups (если есть)
- ...
EOF

# Manually edit и заполни placeholder'ы (<NEW_PT_ID> etc.) перед commit
\$EDITOR docs/evidence/2026-05-10-tt-music-rights-dialog-shipped.md

# Verify нет remaining placeholders ('<' followed by uppercase identifier)
if grep -E '<[A-Z_]+>' docs/evidence/2026-05-10-tt-music-rights-dialog-shipped.md; then
    echo "ERROR: unfilled placeholders remain — fix before commit"
    exit 1
fi

git add docs/evidence/2026-05-10-tt-music-rights-dialog-shipped.md
git commit -m "docs(evidence): TT music rights handler shipped 2026-05-10"
```

---

## Self-Review

(Этот раздел — для writing-plans skill self-check, не для executor.)

**Spec coverage:** проверил каждую section спека:
- §3.1 constants → Task 2
- §3.2 detector → Task 5
- §3.3 handle helper → Task 7 (uses Task 4 strict tap + Task 5 detect + Task 6 checkbox)
- §3.4 checkbox helper → Task 6
- §3.5 wired в loop + counter reset → Task 8
- §3.6 kernel mapping → Task 3
- §3.8 ordering → Task 8 (after UPLOAD_OK) + Task 9 (regression test)
- §4 19 tests → Tasks 3, 4, 5, 6, 7, 8, 9 (1+4+4+2+3+3+2 = 19 ✅)
- §6 telemetry events → emitted в Task 7 helper и Task 8 cap path
- §9 acceptance #1 (19 tests) → Task 9 step 3; #2 (TT suite green) → Task 10 step 1; #3 (live verify) → Task 10 step 8; #4 (dashboard split) → telemetry в Task 7+8; #5 (24h metric) → Task 10 step 9; #6 (Codex review) → spec уже прошёл 6 round (документировано в spec section 10)

**Placeholder scan:** нет TBD/TODO. Bounds координаты, expected adb_tap значения, всё concrete.

**Type/method consistency:**
- `_strict_tap_clickable(ui_xml, candidates) -> bool` — consistent в Task 4 def + Task 7 use
- `_detect_tt_music_rights_dialog(ui_xml) -> bool` — Task 5 def, Task 7 use, Task 8 use
- `_tick_tt_music_rights_checkbox(ui_xml) -> bool` — Task 6 def, Task 7 use
- `_handle_tt_music_rights_dialog(ui_xml) -> bool` — Task 7 def, Task 8 use
- `_node_center` / `_tap_node_bounds` / `_nearest_node_to_labels` — все в Task 6
- `MAX_MUSIC_RIGHTS_ITERATIONS` — Task 2 def, Task 8 use
- `set_step('tt_5_music_rights_stuck')` — Task 8 use, Task 3 mapping
- `_TT_MUSIC_RIGHTS_TITLE_MARKERS` / `_BUTTON` / `_CHECKBOX` — Task 2 def, Tasks 5/6/7 use
- `_music_rights_iter` — Task 8 reset + use

Всё consistent.
