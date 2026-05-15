# TT commercial-music modal handler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distinguish, dismiss (cancel-X) или, при невозможности, выбрать первый трек в новом TT-модале «Коммерческие треки», который сейчас приводит к 3–4 fails/24h с `tt_upload_confirmation_timeout`.

**Architecture:** Overlay-handler в стиле существующего `_handle_tt_music_rights_dialog` — три-уровневый detector (strict / fallback / evidence-only) + action ladder (cancel ≤ 2 iter → select 1-го трека > 2 iter → stuck > MAX). Логика hook'а вытянута в одну testable точку `_run_tt_commercial_music_hook(ui, phase)` и вызывается из двух мест: pre-share share-loop и wait_upload outer loop.

**Tech Stack:** Python 3, stdlib `xml.etree.ElementTree`, pytest, MagicMock; `TikTokMixin` (publisher_tiktok.py), conftest fixtures (`tt_mixin_stub`).

**Spec:** `docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md`
**OpenProject:** [#75](https://openproject.contenthunter.ru/wp/75)
**Branch (docs):** `tt-publish-fails-triage-2026-05-15` (rmbrmv/contenthunter)
**Code repo:** autowarm — `/root/.openclaw/workspace-genri/autowarm/` (GenGo2/delivery-contenthunter). Создать worktree через `superpowers:using-git-worktrees` для изоляции от параллельных сессий перед началом Task 1.

---

## File Structure

| Файл | Действие | Ответственность |
|---|---|---|
| `publisher_tiktok.py` | Modify | Все новые методы + константы + hook. Точки правки: ~line 30 (constant), ~line 187 (class-level markers), ~line 222 (state init), ~line 879 (handler block), ~line 1015 (init wire-up), ~line 1257 (share-loop hook), ~line 1568 (wait_upload hook). |
| `tests/test_publisher_tt_commercial_music_modal.py` | Create | Все unit-тесты: constants/init + detector × 3 + tap helpers × 2 + handler ladder + hook orchestration. |
| `tests/test_publisher_tt_wait_upload_integration.py` | Modify | Один integration smoke-тест (модал → cancel → publish proceeds). |

Worktree path шаблон (для исполнителя): `/home/claude-user/autowarm-feat-tt-commercial-music-20260515` (или аналог; следуйте конвенции из `feedback_autowarm_testbench_deploy.md`).

---

## Task 1: Constants and markers

**Files:**
- Modify: `publisher_tiktok.py` (lines 30 and ~187)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_publisher_tt_commercial_music_modal.py`:

```python
"""TT commercial-music modal handler tests.

Spec: docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_tiktok import (  # noqa: E402
    MAX_COMMERCIAL_MUSIC_ITERATIONS,
    TikTokMixin,
)


def test_constants_exist_and_non_empty():
    assert MAX_COMMERCIAL_MUSIC_ITERATIONS == 4
    assert TikTokMixin._TT_COMMERCIAL_MUSIC_TITLE_MARKERS
    assert TikTokMixin._TT_COMMERCIAL_MUSIC_FALLBACK_SUBSTRINGS
    assert TikTokMixin._TT_COMMERCIAL_MUSIC_TAB_LABELS
    assert TikTokMixin._TT_COMMERCIAL_MUSIC_PLAYLIST_HINTS
    assert TikTokMixin._TT_COMMERCIAL_MUSIC_CLOSE_LABELS
    # Lowercase-only для fallback substring сравнений
    assert all(s == s.lower() for s in TikTokMixin._TT_COMMERCIAL_MUSIC_FALLBACK_SUBSTRINGS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py::test_constants_exist_and_non_empty -v`
Expected: FAIL with `ImportError: cannot import name 'MAX_COMMERCIAL_MUSIC_ITERATIONS'`

- [ ] **Step 3: Add module-level constant after `MAX_MUSIC_RIGHTS_ITERATIONS`**

In `publisher_tiktok.py` after line 30 (after `MAX_MUSIC_RIGHTS_ITERATIONS = 5`):

```python
# Commercial-music modal cap (2026-05-15).
# Spec: docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md
# 4 = 2 cancel-X attempts + 2 select-first-track attempts.
MAX_COMMERCIAL_MUSIC_ITERATIONS = 4
```

- [ ] **Step 4: Add class-level markers after `_TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS` (line 187)**

In `publisher_tiktok.py` after line 187 (before `# ─── wait_upload overlay handlers (2026-05-12) ───`):

```python
    # Commercial-music modal markers (2026-05-15).
    # Spec: docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md
    _TT_COMMERCIAL_MUSIC_TITLE_MARKERS = [
        'Коммерческие треки',
        'Commercial music',
        'Commercial sounds',
    ]
    # lowercase substrings для case-insensitive fallback
    _TT_COMMERCIAL_MUSIC_FALLBACK_SUBSTRINGS = [
        'коммерчески',
        'commercial mus',
        'commercial sou',
    ]
    _TT_COMMERCIAL_MUSIC_TAB_LABELS = [
        'Интересное', 'Избранное', 'For You', 'Favorites',
    ]
    _TT_COMMERCIAL_MUSIC_PLAYLIST_HINTS = [
        'TikBiz', 'TikTok Viral', 'New Releases', 'Emerging Artists',
    ]
    _TT_COMMERCIAL_MUSIC_CLOSE_LABELS = [
        'Close', 'Закрыть', 'Cancel', 'Отмена', '×', 'X',
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py::test_constants_exist_and_non_empty -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): constants + class markers (WP #75)"
```

---

## Task 2: `_init_commercial_music_state` helper

**Files:**
- Modify: `publisher_tiktok.py` (add method near line 893, after `_init_music_rights_state`)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

- [ ] **Step 1: Append failing test**

Append to `tests/test_publisher_tt_commercial_music_modal.py`:

```python
def test_init_state_sets_attrs():
    m = TikTokMixin.__new__(TikTokMixin)
    m._init_commercial_music_state()
    assert m._commercial_music_iter == 0
    assert m._commercial_music_evidence_dumped is False


def test_init_state_resets_existing_values():
    m = TikTokMixin.__new__(TikTokMixin)
    m._commercial_music_iter = 7
    m._commercial_music_evidence_dumped = True
    m._init_commercial_music_state()
    assert m._commercial_music_iter == 0
    assert m._commercial_music_evidence_dumped is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k init_state`
Expected: FAIL with `AttributeError: ... has no attribute '_init_commercial_music_state'`

- [ ] **Step 3: Add helper method**

In `publisher_tiktok.py` immediately AFTER the `_after_music_rights_handled` method (line ~905, find `def _after_music_rights_handled`), add:

```python
    def _init_commercial_music_state(self) -> None:
        """Init commercial-music modal handler state.

        Spec: docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md

        Attributes:
        - _commercial_music_iter (counter for MAX_COMMERCIAL_MUSIC_ITERATIONS cap)
        - _commercial_music_evidence_dumped (throttle flag для evidence-only path)
        """
        self._commercial_music_iter = 0
        self._commercial_music_evidence_dumped = False
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k init_state`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): _init_commercial_music_state helper (WP #75)"
```

---

## Task 3: Strict detector

**Files:**
- Modify: `publisher_tiktok.py` (add method after `_detect_tt_music_rights_dialog_evidence_only`, line ~705)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_publisher_tt_commercial_music_modal.py`:

```python
# === Strict detector ===

_STRICT_UI_RU_WITH_TAB = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Коммерческие треки" content-desc="" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node text="Интересное" content-desc="" clickable="true" class="android.widget.TextView" bounds="[100,300][400,400]" />
  <node text="Beat Automotivo" content-desc="" clickable="true" class="android.widget.LinearLayout" bounds="[100,600][1000,800]" />
</hierarchy>'''

_STRICT_UI_EN_WITH_PLAYLIST = '''<?xml version="1.0"?>
<hierarchy>
  <node content-desc="Commercial music" text="" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node text="TikBiz" content-desc="" clickable="true" class="android.widget.LinearLayout" bounds="[100,1000][500,1100]" />
</hierarchy>'''

_STRICT_UI_NO_TITLE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Some other dialog" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node text="Интересное" clickable="true" class="android.widget.TextView" bounds="[100,300][400,400]" />
</hierarchy>'''

_STRICT_UI_TITLE_NO_STRUCTURE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Коммерческие треки" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node text="Just random text" class="android.widget.TextView" bounds="[100,300][400,400]" />
</hierarchy>'''


def test_detect_strict_ru_with_tab():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal(_STRICT_UI_RU_WITH_TAB) is True


def test_detect_strict_en_with_playlist():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal(_STRICT_UI_EN_WITH_PLAYLIST) is True


def test_detect_strict_no_title():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal(_STRICT_UI_NO_TITLE) is False


def test_detect_strict_title_no_structure():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal(_STRICT_UI_TITLE_NO_STRUCTURE) is False


def test_detect_strict_empty_xml():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal('') is False


def test_detect_strict_malformed_xml():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal('<not valid xml') is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k detect_strict`
Expected: 6 FAILs with `AttributeError: ... has no attribute '_detect_tt_commercial_music_modal'`

- [ ] **Step 3: Add strict detector**

In `publisher_tiktok.py` immediately AFTER `_detect_tt_music_rights_dialog_evidence_only` method body (line ~703-704, find the line with `return False` that ends that method), add:

```python
    def _detect_tt_commercial_music_modal(self, ui_xml: str) -> bool:
        """Strict detector для TT 'Коммерческие треки' modal.

        Identity = title-marker EXACT (text OR desc) AND
        (хотя бы один TAB_LABEL OR PLAYLIST_HINT в дереве как text/desc).
        Title alone недостаточен (защищает от false-positive на settings).

        Returns True если modal detected, False иначе.
        """
        if not ui_xml:
            return False
        # Cheap pre-filter
        if not any(m in ui_xml for m in self._TT_COMMERCIAL_MUSIC_TITLE_MARKERS):
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        has_title = False
        has_structure = False
        for n in root.iter('node'):
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if not has_title and (
                txt in self._TT_COMMERCIAL_MUSIC_TITLE_MARKERS
                or desc in self._TT_COMMERCIAL_MUSIC_TITLE_MARKERS
            ):
                has_title = True
            if not has_structure:
                for label in self._TT_COMMERCIAL_MUSIC_TAB_LABELS:
                    if txt == label or desc == label:
                        has_structure = True
                        break
                if not has_structure:
                    for hint in self._TT_COMMERCIAL_MUSIC_PLAYLIST_HINTS:
                        if txt == hint or desc == hint:
                            has_structure = True
                            break
            if has_title and has_structure:
                return True
        return False
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k detect_strict`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): strict detector (WP #75)"
```

---

## Task 4: Fallback detector

**Files:**
- Modify: `publisher_tiktok.py` (add method after `_detect_tt_commercial_music_modal`)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

- [ ] **Step 1: Append failing tests**

```python
# === Fallback detector ===

_FALLBACK_UI_LOWERCASE_SUBSTR = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Коммерческие треки видео" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node content-desc="Close" clickable="true" class="android.widget.ImageButton" bounds="[20,80][140,200]" />
  <node text="Beat Automotivo" content-desc="" clickable="true" class="android.widget.LinearLayout" bounds="[100,600][1000,800]" />
</hierarchy>'''

_FALLBACK_UI_NO_CLOSE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="commercial music selector" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node text="Beat Automotivo" clickable="true" class="android.widget.LinearLayout" bounds="[100,600][1000,800]" />
</hierarchy>'''

_FALLBACK_UI_NO_TRACK = '''<?xml version="1.0"?>
<hierarchy>
  <node text="commercial music" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node content-desc="Close" clickable="true" class="android.widget.ImageButton" bounds="[20,80][140,200]" />
</hierarchy>'''


def test_detect_fallback_match():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal_fallback(_FALLBACK_UI_LOWERCASE_SUBSTR) is True


def test_detect_fallback_no_close():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal_fallback(_FALLBACK_UI_NO_CLOSE) is False


def test_detect_fallback_no_track_row():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal_fallback(_FALLBACK_UI_NO_TRACK) is False


def test_detect_fallback_no_substring():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal_fallback(_STRICT_UI_NO_TITLE) is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k detect_fallback`
Expected: 4 FAILs with `AttributeError`.

- [ ] **Step 3: Add fallback detector**

In `publisher_tiktok.py` immediately after `_detect_tt_commercial_music_modal`, add:

```python
    def _detect_tt_commercial_music_modal_fallback(self, ui_xml: str) -> bool:
        """Looser fallback для variants TT title.

        Conditions (ALL true):
          1. lowercase substring из FALLBACK_SUBSTRINGS в ui_xml.lower().
          2. clickable node-кандидат на close-X (top-left zone OR один из
             CLOSE_LABELS в text/desc).
          3. хотя бы один track-row кандидат: clickable node с y_top > 250
             и непустым text длиной > 3 (отбрасывает иконки).
        """
        if not ui_xml:
            return False
        low = ui_xml.lower()
        if not any(s in low for s in self._TT_COMMERCIAL_MUSIC_FALLBACK_SUBSTRINGS):
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        has_close = False
        has_track_row = False
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            center = self._node_center(n)
            if center is None:
                continue
            cx, cy = center
            if not has_close:
                if txt in self._TT_COMMERCIAL_MUSIC_CLOSE_LABELS \
                        or desc in self._TT_COMMERCIAL_MUSIC_CLOSE_LABELS:
                    has_close = True
                elif cx < 200 and cy < 250:
                    has_close = True
            if not has_track_row:
                if cy > 250 and len(txt) > 3:
                    has_track_row = True
            if has_close and has_track_row:
                return True
        return False
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k detect_fallback`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): fallback detector (WP #75)"
```

---

## Task 5: Evidence-only detector

**Files:**
- Modify: `publisher_tiktok.py` (add method after `_detect_tt_commercial_music_modal_fallback`)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

- [ ] **Step 1: Append failing tests**

```python
# === Evidence-only detector ===

_EVIDENCE_ONLY_UI = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Что-то про commercial music" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node text="Just text" class="android.widget.TextView" bounds="[100,500][400,600]" />
</hierarchy>'''


def test_detect_evidence_only_substring_alone():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal_evidence_only(_EVIDENCE_ONLY_UI) is True


def test_detect_evidence_only_no_substring():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal_evidence_only(_STRICT_UI_NO_TITLE) is False


def test_detect_evidence_only_empty():
    m = TikTokMixin.__new__(TikTokMixin)
    assert m._detect_tt_commercial_music_modal_evidence_only('') is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k detect_evidence`
Expected: 3 FAILs with `AttributeError`.

- [ ] **Step 3: Add evidence-only detector**

In `publisher_tiktok.py` immediately after `_detect_tt_commercial_music_modal_fallback`, add:

```python
    def _detect_tt_commercial_music_modal_evidence_only(self, ui_xml: str) -> bool:
        """Slack-match для логирования + dump. НЕ для auto-handle.

        Condition: lowercase substring из FALLBACK_SUBSTRINGS в ui_xml.lower().
        Caller отвечает за logical-AND: вызывать ТОЛЬКО когда strict и
        fallback оба вернули False.
        """
        if not ui_xml:
            return False
        low = ui_xml.lower()
        return any(s in low for s in self._TT_COMMERCIAL_MUSIC_FALLBACK_SUBSTRINGS)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k detect_evidence`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): evidence-only detector (WP #75)"
```

---

## Task 6: Dump helper

**Files:**
- Modify: `publisher_tiktok.py` (add method after `_save_dump_for_fallback_review`)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

- [ ] **Step 1: Append failing test**

```python
import time as _time  # already imported below — use module-level import block at top of test file
import re as _re_for_dump


def test_save_dump_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr('os.makedirs', lambda *a, **kw: None)
    m = TikTokMixin.__new__(TikTokMixin)
    m.task_id = 9999
    # Redirect /tmp/autowarm_ui_dumps writes into tmp_path
    real_open = open
    captured = {}
    def fake_open(path, mode='r', *args, **kwargs):
        if 'tt_commercial_music_' in path:
            captured['path'] = path
            return real_open(tmp_path / Path(path).name, mode, *args, **kwargs)
        return real_open(path, mode, *args, **kwargs)
    monkeypatch.setattr('builtins.open', fake_open)
    res = m._save_dump_for_commercial_music_review('<x/>', 'fallback')
    assert res != 'write_failed'
    assert 'tt_commercial_music_fallback_task_9999_' in res
    assert (tmp_path / Path(res).name).read_text() == '<x/>'
```

Also add an import line at the top of the test file (after the existing `from unittest.mock import MagicMock` line):

```python
from pathlib import Path  # already imported above
```

(If `from pathlib import Path` уже импортирован в начале файла — пропустить.)

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k save_dump`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Add dump helper**

In `publisher_tiktok.py` immediately after `_save_dump_for_fallback_review` method (find `def _save_dump_for_fallback_review` near line ~860), add:

```python
    def _save_dump_for_commercial_music_review(self, ui_xml: str, suffix: str) -> str:
        """Best-effort dump of UI XML for commercial-music modal evidence.

        Returns path or 'write_failed'. Never raises.
        ms-timestamp + uuid8 suffix защищает от коллизий при retries.
        """
        try:
            os.makedirs('/tmp/autowarm_ui_dumps', exist_ok=True)
            ts_ms = int(time.time() * 1000)
            uid8 = uuid.uuid4().hex[:8]
            path = (f'/tmp/autowarm_ui_dumps/'
                    f'tt_commercial_music_{suffix}_task_{self.task_id}'
                    f'_{ts_ms}_{uid8}.xml')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(ui_xml or '')
            return path
        except Exception as e:
            log.warning(f'  ⚠️ Не удалось сохранить commercial_music dump: {e}')
            return 'write_failed'
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k save_dump`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): dump helper (WP #75)"
```

---

## Task 7: Close-X tap helper

**Files:**
- Modify: `publisher_tiktok.py` (add method)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

- [ ] **Step 1: Append failing tests**

```python
# === Close-X tap helper ===

_CLOSE_UI_BY_DESC = '''<?xml version="1.0"?>
<hierarchy>
  <node content-desc="Close" clickable="true" class="android.widget.ImageButton" bounds="[20,80][140,200]" />
</hierarchy>'''

_CLOSE_UI_BY_ZAKRYT = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Закрыть" clickable="true" class="android.widget.Button" bounds="[20,80][140,200]" />
</hierarchy>'''

_CLOSE_UI_BY_TOPLEFT_ZONE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="" content-desc="" clickable="true" class="android.widget.ImageView" bounds="[20,80][140,200]" />
  <node text="" content-desc="" clickable="true" class="android.widget.ImageView" bounds="[500,80][700,200]" />
</hierarchy>'''

_CLOSE_UI_NONE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="No close button" class="android.widget.TextView" bounds="[100,100][900,200]" />
</hierarchy>'''


def test_close_by_desc():
    m = TikTokMixin.__new__(TikTokMixin)
    m.adb_tap = MagicMock()
    assert m._tap_tt_commercial_music_close(_CLOSE_UI_BY_DESC) is True
    m.adb_tap.assert_called_once_with(80, 140)


def test_close_by_zakryt_text():
    m = TikTokMixin.__new__(TikTokMixin)
    m.adb_tap = MagicMock()
    assert m._tap_tt_commercial_music_close(_CLOSE_UI_BY_ZAKRYT) is True
    m.adb_tap.assert_called_once_with(80, 140)


def test_close_by_topleft_zone():
    m = TikTokMixin.__new__(TikTokMixin)
    m.adb_tap = MagicMock()
    assert m._tap_tt_commercial_music_close(_CLOSE_UI_BY_TOPLEFT_ZONE) is True
    # Center of [20,80][140,200] = (80, 140)
    m.adb_tap.assert_called_once_with(80, 140)


def test_close_not_found():
    m = TikTokMixin.__new__(TikTokMixin)
    m.adb_tap = MagicMock()
    assert m._tap_tt_commercial_music_close(_CLOSE_UI_NONE) is False
    m.adb_tap.assert_not_called()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k close`
Expected: 4 FAILs with `AttributeError`.

- [ ] **Step 3: Add close-X tap helper**

In `publisher_tiktok.py` immediately after the `_tap_node_bounds` method (find `def _tap_node_bounds`, line ~716), add:

```python
    def _tap_tt_commercial_music_close(self, ui_xml: str) -> bool:
        """Find и tap кнопку X (close) для commercial-music modal.

        Priority order:
          1. clickable node с text OR desc in _TT_COMMERCIAL_MUSIC_CLOSE_LABELS.
          2. clickable node-кандидат в top-left zone (cx < 200 AND cy < 250),
             class содержит 'ImageView' OR 'ImageButton' OR 'Button'.

        Returns True если tap отправлен, False иначе.
        """
        if not ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        # Pass 1: labeled close
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if txt in self._TT_COMMERCIAL_MUSIC_CLOSE_LABELS \
                    or desc in self._TT_COMMERCIAL_MUSIC_CLOSE_LABELS:
                return self._tap_node_bounds(n)
        # Pass 2: top-left zone candidate
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            cls = n.get('class', '') or ''
            if not ('ImageView' in cls or 'ImageButton' in cls or 'Button' in cls):
                continue
            center = self._node_center(n)
            if center is None:
                continue
            cx, cy = center
            if cx < 200 and cy < 250:
                return self._tap_node_bounds(n)
        return False
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k close`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): close-X tap helper (WP #75)"
```

---

## Task 8: First-track tap helper

**Files:**
- Modify: `publisher_tiktok.py` (add method)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

- [ ] **Step 1: Append failing tests**

```python
# === First-track tap helper ===

_TRACK_UI_CHECKMARK_UNICODE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Beat Automotivo" class="android.widget.TextView" bounds="[100,600][700,700]" />
  <node text="✓" content-desc="" clickable="true" class="android.widget.ImageButton" bounds="[800,600][900,700]" />
</hierarchy>'''

_TRACK_UI_TWO_CHECKMARKS = '''<?xml version="1.0"?>
<hierarchy>
  <node text="✓" clickable="true" bounds="[800,100][900,200]" />
  <node text="✓" clickable="true" bounds="[800,800][900,900]" />
</hierarchy>'''

_TRACK_UI_NONE = '''<?xml version="1.0"?>
<hierarchy>
  <node text="No checkmark anywhere" class="android.widget.TextView" bounds="[100,600][900,700]" />
</hierarchy>'''


def test_first_track_by_checkmark():
    m = TikTokMixin.__new__(TikTokMixin)
    m.adb_tap = MagicMock()
    assert m._tap_tt_commercial_music_first_track(_TRACK_UI_CHECKMARK_UNICODE) is True
    # Center of [800,600][900,700] = (850, 650)
    m.adb_tap.assert_called_once_with(850, 650)


def test_first_track_skips_header_zone():
    m = TikTokMixin.__new__(TikTokMixin)
    m.adb_tap = MagicMock()
    assert m._tap_tt_commercial_music_first_track(_TRACK_UI_TWO_CHECKMARKS) is True
    # Should skip [800,100] (y=150 < 250 header) and pick [800,800][900,900] = (850, 850)
    m.adb_tap.assert_called_once_with(850, 850)


def test_first_track_not_found():
    m = TikTokMixin.__new__(TikTokMixin)
    m.adb_tap = MagicMock()
    assert m._tap_tt_commercial_music_first_track(_TRACK_UI_NONE) is False
    m.adb_tap.assert_not_called()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k first_track`
Expected: 3 FAILs with `AttributeError`.

- [ ] **Step 3: Add first-track tap helper**

In `publisher_tiktok.py` immediately after `_tap_tt_commercial_music_close`, add:

```python
    def _tap_tt_commercial_music_first_track(self, ui_xml: str) -> bool:
        """Find и tap первый трек (✓-button) в commercial-music modal.

        Algorithm:
          1. Найти все clickable node'ы с ✓-glyph в text/desc (или label
             'Select'/'Выбрать'/'Confirm') — это per-row confirm-buttons.
          2. Отсортировать по y_top центра.
          3. Взять первый с y_top > 250 (отбрасывает header-зону).
          4. Tap по центру bounds.

        Returns True если tap отправлен, False если ✓-candidates не нашлись.
        """
        if not ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        check_labels = ('✓', '✓', 'Select', 'Выбрать', 'Confirm')
        candidates = []
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            is_check = any(lbl in txt or lbl in desc for lbl in check_labels)
            if not is_check:
                continue
            center = self._node_center(n)
            if center is None:
                continue
            cx, cy = center
            candidates.append((cy, cx, n))
        candidates.sort(key=lambda t: (t[0], t[1]))
        for cy, _cx, node in candidates:
            if cy > 250:
                return self._tap_node_bounds(node)
        return False
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k first_track`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): first-track tap helper (WP #75)"
```

---

## Task 9: Handler (cancel-select ladder)

**Files:**
- Modify: `publisher_tiktok.py` (add `_handle_tt_commercial_music_modal` method)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

- [ ] **Step 1: Append failing tests**

```python
# === Handler ladder ===

def _build_mixin_with_taps():
    """TikTokMixin instance с mocked tap helpers + log_event."""
    m = TikTokMixin.__new__(TikTokMixin)
    m._init_commercial_music_state()
    m.platform = 'TikTok'
    m.log_event = MagicMock()
    m._tap_tt_commercial_music_close = MagicMock(return_value=True)
    m._tap_tt_commercial_music_first_track = MagicMock(return_value=True)
    return m


def test_handler_iter1_cancels():
    m = _build_mixin_with_taps()
    m._commercial_music_iter = 1
    handled = m._handle_tt_commercial_music_modal('<x/>', 'strict')
    assert handled is True
    m._tap_tt_commercial_music_close.assert_called_once()
    m._tap_tt_commercial_music_first_track.assert_not_called()
    # log_event с category tt_commercial_music_cancelled
    args, kwargs = m.log_event.call_args
    meta = kwargs.get('meta') or (args[2] if len(args) > 2 else None)
    assert meta is not None
    assert meta['category'] == 'tt_commercial_music_cancelled'
    assert meta['matched_via'] == 'strict'
    assert meta['phase'] == 'cancel'


def test_handler_iter3_selects_first_track():
    m = _build_mixin_with_taps()
    m._commercial_music_iter = 3
    handled = m._handle_tt_commercial_music_modal('<x/>', 'fallback')
    assert handled is True
    m._tap_tt_commercial_music_first_track.assert_called_once()
    m._tap_tt_commercial_music_close.assert_not_called()
    args, kwargs = m.log_event.call_args
    meta = kwargs.get('meta') or (args[2] if len(args) > 2 else None)
    assert meta['category'] == 'tt_commercial_music_track_selected'
    assert meta['matched_via'] == 'fallback'
    assert meta['phase'] == 'select'


def test_handler_close_not_found_logs_warning():
    m = _build_mixin_with_taps()
    m._commercial_music_iter = 1
    m._tap_tt_commercial_music_close.return_value = False
    handled = m._handle_tt_commercial_music_modal('<x/>', 'strict')
    assert handled is False
    args, kwargs = m.log_event.call_args
    level = args[0]
    meta = kwargs.get('meta') or (args[2] if len(args) > 2 else None)
    assert level == 'warning'
    assert meta['category'] == 'tt_commercial_music_close_not_found'


def test_handler_track_not_found_logs_warning():
    m = _build_mixin_with_taps()
    m._commercial_music_iter = 3
    m._tap_tt_commercial_music_first_track.return_value = False
    handled = m._handle_tt_commercial_music_modal('<x/>', 'strict')
    assert handled is False
    args, kwargs = m.log_event.call_args
    level = args[0]
    meta = kwargs.get('meta') or (args[2] if len(args) > 2 else None)
    assert level == 'warning'
    assert meta['category'] == 'tt_commercial_music_track_not_found'
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k handler_`
Expected: 4 FAILs with `AttributeError`.

- [ ] **Step 3: Add handler method**

In `publisher_tiktok.py` immediately after `_init_commercial_music_state` (added in Task 2), add:

```python
    def _handle_tt_commercial_music_modal(self, ui_xml: str, matched_via: str) -> bool:
        """Action ladder для commercial-music modal.

        Counter `self._commercial_music_iter` уже инкрементирован caller'ом.
          - iter <= 2 → cancel via X
          - iter > 2  → select 1-го трека

        matched_via ∈ {'strict','fallback'} — пробрасывается в meta для триажа.

        Returns True если tap отправлен; False если tap-helper не нашёл target.
        """
        if self._commercial_music_iter <= 2:
            tapped = self._tap_tt_commercial_music_close(ui_xml)
            category = ('tt_commercial_music_cancelled' if tapped
                        else 'tt_commercial_music_close_not_found')
            phase = 'cancel'
        else:
            tapped = self._tap_tt_commercial_music_first_track(ui_xml)
            category = ('tt_commercial_music_track_selected' if tapped
                        else 'tt_commercial_music_track_not_found')
            phase = 'select'
        self.log_event(
            'info' if tapped else 'warning',
            f'TikTok: commercial-music modal {category}',
            meta={'category': category,
                  'platform': 'TikTok',
                  'matched_via': matched_via,
                  'iter': self._commercial_music_iter,
                  'phase': phase},
        )
        return tapped
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k handler_`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): cancel-select handler ladder (WP #75)"
```

---

## Task 10: Hook orchestrator (`_run_tt_commercial_music_hook`)

**Files:**
- Modify: `publisher_tiktok.py` (add method)
- Test: `tests/test_publisher_tt_commercial_music_modal.py` (extend)

Контекст: hook'и в share-loop и wait_upload должны быть idempotent и testable. Извлекаем общий orchestrator. Возвращает `'handled'`, `'stuck'` или `'clean'`.

- [ ] **Step 1: Append failing tests**

```python
# === Hook orchestrator ===

def _build_hook_mixin(monkeypatch, env=None):
    env = env or {'TT_COMMERCIAL_MUSIC_HANDLER_ENABLED': 'true'}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    m = TikTokMixin.__new__(TikTokMixin)
    m._init_commercial_music_state()
    m.platform = 'TikTok'
    m.task_id = 9999
    m.log_event = MagicMock()
    m._detect_tt_commercial_music_modal = MagicMock(return_value=False)
    m._detect_tt_commercial_music_modal_fallback = MagicMock(return_value=False)
    m._detect_tt_commercial_music_modal_evidence_only = MagicMock(return_value=False)
    m._handle_tt_commercial_music_modal = MagicMock(return_value=True)
    m._save_dump_for_commercial_music_review = MagicMock(return_value='/tmp/x.xml')
    return m


def test_hook_handler_disabled_returns_clean(monkeypatch):
    m = _build_hook_mixin(monkeypatch, env={'TT_COMMERCIAL_MUSIC_HANDLER_ENABLED': 'false'})
    m._detect_tt_commercial_music_modal.return_value = True
    res = m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    assert res == 'clean'
    m._handle_tt_commercial_music_modal.assert_not_called()


def test_hook_strict_match_increments_and_handles(monkeypatch):
    m = _build_hook_mixin(monkeypatch)
    m._detect_tt_commercial_music_modal.return_value = True
    res = m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    assert res == 'handled'
    assert m._commercial_music_iter == 1
    m._handle_tt_commercial_music_modal.assert_called_once_with('<x/>', 'strict')


def test_hook_fallback_used_when_strict_misses(monkeypatch):
    m = _build_hook_mixin(monkeypatch,
        env={'TT_COMMERCIAL_MUSIC_HANDLER_ENABLED': 'true',
             'TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED': 'true'})
    m._detect_tt_commercial_music_modal.return_value = False
    m._detect_tt_commercial_music_modal_fallback.return_value = True
    res = m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    assert res == 'handled'
    m._handle_tt_commercial_music_modal.assert_called_once_with('<x/>', 'fallback')
    # fallback_match event logged
    cats = [c.kwargs.get('meta', {}).get('category') for c in m.log_event.call_args_list]
    assert 'tt_commercial_music_fallback_match' in cats


def test_hook_fallback_disabled_by_default(monkeypatch):
    m = _build_hook_mixin(monkeypatch)
    m._detect_tt_commercial_music_modal.return_value = False
    m._detect_tt_commercial_music_modal_fallback.return_value = True
    res = m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    assert res == 'clean'
    m._handle_tt_commercial_music_modal.assert_not_called()


def test_hook_stuck_when_iter_exceeds_max(monkeypatch):
    m = _build_hook_mixin(monkeypatch)
    m._commercial_music_iter = 4  # at MAX, next increment hits MAX+1
    m._detect_tt_commercial_music_modal.return_value = True
    res = m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    assert res == 'stuck'
    m._handle_tt_commercial_music_modal.assert_not_called()
    cats = [c.kwargs.get('meta', {}).get('category') for c in m.log_event.call_args_list]
    assert 'tt_commercial_music_stuck' in cats


def test_hook_dismissed_when_modal_gone_after_iter(monkeypatch):
    m = _build_hook_mixin(monkeypatch)
    m._commercial_music_iter = 1
    m._detect_tt_commercial_music_modal.return_value = False
    res = m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    assert res == 'clean'
    assert m._commercial_music_iter == 0
    cats = [c.kwargs.get('meta', {}).get('category') for c in m.log_event.call_args_list]
    assert 'tt_commercial_music_dismissed' in cats


def test_hook_evidence_only_dumps_when_fallback_enabled(monkeypatch):
    m = _build_hook_mixin(monkeypatch,
        env={'TT_COMMERCIAL_MUSIC_HANDLER_ENABLED': 'true',
             'TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED': 'true'})
    m._detect_tt_commercial_music_modal.return_value = False
    m._detect_tt_commercial_music_modal_fallback.return_value = False
    m._detect_tt_commercial_music_modal_evidence_only.return_value = True
    res = m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    assert res == 'clean'
    assert m._commercial_music_evidence_dumped is True
    m._save_dump_for_commercial_music_review.assert_called_once()
    cats = [c.kwargs.get('meta', {}).get('category') for c in m.log_event.call_args_list]
    assert 'tt_commercial_music_unhandled_suspect' in cats


def test_hook_evidence_only_throttled(monkeypatch):
    m = _build_hook_mixin(monkeypatch,
        env={'TT_COMMERCIAL_MUSIC_HANDLER_ENABLED': 'true',
             'TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED': 'true'})
    m._detect_tt_commercial_music_modal_evidence_only.return_value = True
    m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    m._run_tt_commercial_music_hook('<x/>', 'share_loop')
    # Dump только один раз
    assert m._save_dump_for_commercial_music_review.call_count == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k "hook_"`
Expected: 8 FAILs with `AttributeError: _run_tt_commercial_music_hook`.

- [ ] **Step 3: Add hook orchestrator**

In `publisher_tiktok.py` immediately after `_handle_tt_commercial_music_modal` (Task 9 location), add:

```python
    def _run_tt_commercial_music_hook(self, ui_xml: str, phase: str) -> str:
        """Orchestrate commercial-music modal detection + handling.

        Phase ∈ {'share_loop','wait_upload'} — пробрасывается в meta + step.

        Returns:
          'handled' — модал был и tap отправлен (caller: sleep + continue loop).
          'stuck'   — iter > MAX, event tt_commercial_music_stuck написан
                      (caller: вернуть False = провал attempt).
          'clean'   — модала нет или handler disabled, никаких действий
                      (caller: продолжает нормальную логику).
        """
        if os.environ.get('TT_COMMERCIAL_MUSIC_HANDLER_ENABLED', 'true').lower() != 'true':
            return 'clean'
        fb_enabled = (os.environ.get('TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED', 'false')
                      .lower() == 'true')
        matched_via = None
        if self._detect_tt_commercial_music_modal(ui_xml):
            matched_via = 'strict'
        elif fb_enabled and self._detect_tt_commercial_music_modal_fallback(ui_xml):
            matched_via = 'fallback'
            dump_path = self._save_dump_for_commercial_music_review(ui_xml, 'fallback')
            self.log_event(
                'info',
                'TikTok: commercial-music modal matched via fallback',
                meta={'category': 'tt_commercial_music_fallback_match',
                      'dump_path': dump_path,
                      'platform': 'TikTok',
                      'phase': phase})

        if matched_via is not None:
            self._commercial_music_iter = getattr(
                self, '_commercial_music_iter', 0) + 1
            if self._commercial_music_iter > MAX_COMMERCIAL_MUSIC_ITERATIONS:
                self.log_event(
                    'error',
                    f'tt_commercial_music_stuck: modal persists > '
                    f'{MAX_COMMERCIAL_MUSIC_ITERATIONS} iterations',
                    meta={'category': 'tt_commercial_music_stuck',
                          'iterations': self._commercial_music_iter,
                          'platform': 'TikTok',
                          'step': 'tt_5_share_loop' if phase == 'share_loop' else 'wait_upload',
                          'phase': phase})
                return 'stuck'
            self._handle_tt_commercial_music_modal(ui_xml, matched_via)
            return 'handled'

        # No match.
        if (fb_enabled
                and not getattr(self, '_commercial_music_evidence_dumped', False)
                and self._detect_tt_commercial_music_modal_evidence_only(ui_xml)):
            dump_path = self._save_dump_for_commercial_music_review(
                ui_xml, 'unhandled_suspect')
            self.log_event(
                'warning',
                'TikTok: commercial-music modal-like suspect, not auto-handled',
                meta={'category': 'tt_commercial_music_unhandled_suspect',
                      'dump_path': dump_path,
                      'platform': 'TikTok',
                      'phase': phase})
            self._commercial_music_evidence_dumped = True

        if getattr(self, '_commercial_music_iter', 0) > 0:
            self.log_event(
                'info',
                'TikTok: commercial-music modal dismissed',
                meta={'category': 'tt_commercial_music_dismissed',
                      'platform': 'TikTok',
                      'attempts': self._commercial_music_iter,
                      'phase': phase})
            self._commercial_music_iter = 0
        return 'clean'
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k "hook_"`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): hook orchestrator (WP #75)"
```

---

## Task 11: Wire init in `publish_tiktok` entry

**Files:**
- Modify: `publisher_tiktok.py` (line ~1015)

- [ ] **Step 1: Append failing test**

```python
def test_publish_tiktok_calls_init():
    """publish_tiktok должен вызвать _init_commercial_music_state в начале.

    Smoke-проверка via direct method introspection — публичный entry-point
    тоо тяжёл для полного теста, но import + grep сорсника достаточен.
    """
    import inspect, publisher_tiktok
    src = inspect.getsource(publisher_tiktok.TikTokMixin.publish_tiktok)
    assert '_init_commercial_music_state' in src, (
        'publish_tiktok must call self._init_commercial_music_state() in entry'
    )
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k publish_tiktok_calls`
Expected: FAIL — string not in source.

- [ ] **Step 3: Modify `publish_tiktok` to call init**

In `publisher_tiktok.py`, locate the `_init_wait_upload_overlay_state()` call (around line 1015 inside `publish_tiktok`). Add ONE LINE immediately after it:

Before:
```python
        self._init_music_rights_state()
        ...
        self._init_wait_upload_overlay_state()
```

After:
```python
        self._init_music_rights_state()
        ...
        self._init_wait_upload_overlay_state()
        self._init_commercial_music_state()
```

(Если строки рядом — добавить после `_init_wait_upload_overlay_state()`. Если между ними есть код — всё равно добавить именно после `_init_wait_upload_overlay_state()`.)

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k publish_tiktok_calls`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): init state in publish_tiktok entry (WP #75)"
```

---

## Task 12: Wire hook into share-loop (Шаг 5)

**Files:**
- Modify: `publisher_tiktok.py` (line ~1257, inside `for attempt in range(8):` of share-loop)

- [ ] **Step 1: Append failing test**

```python
def test_share_loop_invokes_commercial_music_hook():
    """`Шаг 5` share-loop должен вызвать _run_tt_commercial_music_hook
    перед XML-сканом 'Опубликовать'. Smoke через grep."""
    import inspect, publisher_tiktok
    src = inspect.getsource(publisher_tiktok.TikTokMixin.publish_tiktok)
    assert "_run_tt_commercial_music_hook" in src, (
        'publish_tiktok share-loop must call _run_tt_commercial_music_hook'
    )
    # И возврат 'stuck' должен приводить к return False
    assert "'stuck'" in src or '"stuck"' in src
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k share_loop_invokes`
Expected: FAIL — string not in source.

- [ ] **Step 3: Inject hook into share-loop**

In `publisher_tiktok.py` locate `for attempt in range(8):` near line 1256 (inside `# === Шаг 5: Нажимаем Поделиться`), then locate `ui = self.dump_ui()` immediately after the `for attempt`. Insert the hook code IMMEDIATELY after `ui = self.dump_ui()`:

Before:
```python
        for attempt in range(8):
            ui = self.dump_ui()

            # Защита: экран геолокации — закрываем
            if any(kw in ui for kw in ['Добавить местоположение', ...
```

After:
```python
        for attempt in range(8):
            ui = self.dump_ui()

            # Commercial-music modal handler (2026-05-15 / WP #75).
            # Spec: docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md
            _cm_res = self._run_tt_commercial_music_hook(ui, 'share_loop')
            if _cm_res == 'handled':
                time.sleep(2)
                continue
            if _cm_res == 'stuck':
                return False

            # Защита: экран геолокации — закрываем
            if any(kw in ui for kw in ['Добавить местоположение', ...
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k share_loop_invokes`
Expected: 1 passed.

- [ ] **Step 5: Run FULL test file**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v`
Expected: All passed (≥30 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): wire hook into share-loop Шаг 5 (WP #75)"
```

---

## Task 13: Wire hook into wait_upload outer loop

**Files:**
- Modify: `publisher_tiktok.py` (near line 1568, in `_wait_upload_confirmation` overlay-handlers block)

- [ ] **Step 1: Append failing test**

```python
def test_wait_upload_invokes_commercial_music_hook():
    """`_wait_upload_confirmation` outer loop должен вызвать
    _run_tt_commercial_music_hook (defensive — модал может появиться
    после tap Share)."""
    import inspect, publisher_tiktok
    # _wait_upload_confirmation — method на TikTokMixin
    cls = publisher_tiktok.TikTokMixin
    method = getattr(cls, '_wait_upload_confirmation', None)
    assert method is not None, 'TikTokMixin._wait_upload_confirmation not found'
    src = inspect.getsource(method)
    assert "_run_tt_commercial_music_hook(ui, 'wait_upload')" in src \
           or '_run_tt_commercial_music_hook(ui, "wait_upload")' in src, (
        '_wait_upload_confirmation must call _run_tt_commercial_music_hook '
        "with phase='wait_upload'"
    )
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k wait_upload_invokes`
Expected: FAIL — string not in source.

- [ ] **Step 3: Inject hook into `_wait_upload_confirmation`**

In `publisher_tiktok.py`, locate the overlay-handlers section (near line 1568, comment `# === [wait_upload overlay handlers 2026-05-12] ===`). Insert hook code IMMEDIATELY BEFORE the `if (os.environ.get('TT_SAMSUNG_OVERLAY_HANDLER_ENABLED', 'true')...` block (line 1574):

```python
            # Commercial-music modal handler (2026-05-15 / WP #75) — defensive.
            # Spec: docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md
            _cm_res = self._run_tt_commercial_music_hook(ui, 'wait_upload')
            if _cm_res == 'handled':
                time.sleep(1.5)
                continue
            if _cm_res == 'stuck':
                return False
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v -k wait_upload_invokes`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_commercial_music_modal.py publisher_tiktok.py
git commit -m "feat(tt-commercial-music): wire hook into wait_upload outer loop (WP #75)"
```

---

## Task 14: Integration smoke test

**Files:**
- Modify: `tests/test_publisher_tt_wait_upload_integration.py`

- [ ] **Step 1: Inspect existing integration test структуру**

Run: `head -60 tests/test_publisher_tt_wait_upload_integration.py`
Note the fixture/mocking conventions (probably mocks dump_ui sequence + log_event).

- [ ] **Step 2: Append new integration test**

Add to `tests/test_publisher_tt_wait_upload_integration.py` (используя существующий стиль fixtures и mocks; адаптировать имена под conventions того файла):

```python
def test_commercial_music_modal_in_share_loop_then_publish_proceeds(monkeypatch, tt_mixin_stub):
    """Smoke: модал → cancel (handled) → следующий dump без модала → progress."""
    monkeypatch.setenv('TT_COMMERCIAL_MUSIC_HANDLER_ENABLED', 'true')
    m = tt_mixin_stub
    m._init_commercial_music_state()
    # Sequence: первый dump — модал, второй — clean (после cancel)
    modal_ui = '''<?xml version="1.0"?>
<hierarchy>
  <node text="Коммерческие треки" class="android.widget.TextView" bounds="[100,100][900,200]" />
  <node text="Интересное" clickable="true" class="android.widget.TextView" bounds="[100,300][400,400]" />
  <node text="TikBiz" clickable="true" class="android.widget.LinearLayout" bounds="[100,1000][500,1100]" />
  <node content-desc="Close" clickable="true" class="android.widget.ImageButton" bounds="[20,80][140,200]" />
</hierarchy>'''
    clean_ui = '<hierarchy/>'
    # First call: modal → handler returns 'handled', counter=1
    res = m._run_tt_commercial_music_hook(modal_ui, 'share_loop')
    assert res == 'handled'
    assert m._commercial_music_iter == 1
    # Verify cancel was called (adb_tap was called for X button)
    # adb_tap mock comes from tt_mixin_stub fixture
    assert m.adb_tap.called
    m.adb_tap.reset_mock()
    # Second call: clean UI → counter resets, dismissed event emitted
    res = m._run_tt_commercial_music_hook(clean_ui, 'share_loop')
    assert res == 'clean'
    assert m._commercial_music_iter == 0
    cats = [c.kwargs.get('meta', {}).get('category')
            for c in m.log_event.call_args_list]
    assert 'tt_commercial_music_cancelled' in cats
    assert 'tt_commercial_music_dismissed' in cats
```

- [ ] **Step 3: Run integration test**

Run: `pytest tests/test_publisher_tt_wait_upload_integration.py::test_commercial_music_modal_in_share_loop_then_publish_proceeds -v`
Expected: 1 passed.

- [ ] **Step 4: Run FULL test suite (regression check)**

Run: `pytest tests/ -v 2>&1 | tail -30`
Expected: All pre-existing tests still green. New tests pass. Look for FAIL/ERROR markers — should be none from this branch.

- [ ] **Step 5: Commit**

```bash
git add tests/test_publisher_tt_wait_upload_integration.py
git commit -m "test(tt-commercial-music): integration smoke modal→cancel→clean (WP #75)"
```

---

## Task 15: Final verification + push

- [ ] **Step 1: Run new test file in full**

Run: `pytest tests/test_publisher_tt_commercial_music_modal.py -v`
Expected: All ≥30 tests pass, no errors.

- [ ] **Step 2: Run TT-related tests (regression scope)**

Run: `pytest tests/ -v -k "tiktok or _tt_ or music_rights or wait_upload or audio_dialog" 2>&1 | tail -30`
Expected: All pre-existing TT tests still green; new tests pass; no new failures.

- [ ] **Step 3: Confirm no new lint/import errors**

Run: `python -c "import publisher_tiktok; print('OK', publisher_tiktok.MAX_COMMERCIAL_MUSIC_ITERATIONS)"`
Expected: `OK 4`

- [ ] **Step 4: Verify git log shows discrete commits**

Run: `git log --oneline -15`
Expected: ~12 atomic commits, each labeled `feat(tt-commercial-music): ... (WP #75)` or `test(tt-commercial-music): ... (WP #75)`.

- [ ] **Step 5: Push branch + create PR**

```bash
git push -u origin <branch-name>
gh pr create --title "feat(tt): commercial-music modal handler (WP #75)" --body "$(cat <<'EOF'
## Summary
- Закрывает новый TT-модал «Коммерческие треки» (3+1 fails/24h за 2026-05-15, 44% non-network TT-фейлов).
- Cancel-X first, fallback select 1-го трека через 2 попытки.
- 2 hook'а: pre-share share-loop + defensive wait_upload outer loop.
- 9 новых event categories для триажа.
- Env kill-switches: `TT_COMMERCIAL_MUSIC_HANDLER_ENABLED` (default ON), `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED` (default OFF).

## Test plan
- [ ] `pytest tests/test_publisher_tt_commercial_music_modal.py -v` — all green
- [ ] `pytest tests/test_publisher_tt_wait_upload_integration.py -v` — smoke green
- [ ] Live: на следующих 24h после rollout проверить распределение `tt_commercial_music_cancelled` vs `tt_commercial_music_track_selected` в `events` для TT failed tasks
- [ ] Live: убедиться что `tt_upload_confirmation_timeout` count на TT упал

Spec: docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md (rmbrmv/contenthunter)
OpenProject: https://openproject.contenthunter.ru/wp/75
EOF
)"
```

(Имя ветки и адрес remote зависят от worktree-setup исполнителя; следуйте конвенциям autowarm-testbench worktrees.)

---

## Self-review (for plan-author after first draft)

**Spec coverage:**
- Strict detector → Task 3 ✓
- Fallback detector → Task 4 ✓
- Evidence-only detector → Task 5 ✓
- Dump helper → Task 6 ✓
- Close-X tap → Task 7 ✓
- First-track tap → Task 8 ✓
- Handler ladder → Task 9 ✓
- Hook orchestrator (`stuck`/`handled`/`clean`) → Task 10 ✓
- `_init_commercial_music_state` wiring → Task 2 + Task 11 ✓
- Share-loop hook injection → Task 12 ✓
- wait_upload hook injection → Task 13 ✓
- Integration smoke → Task 14 ✓
- Env flags `TT_COMMERCIAL_MUSIC_HANDLER_ENABLED` (default ON) + `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED` (default OFF) → Task 10 (read inside hook) ✓
- Rollback plan — relies on env flags, no code change needed; documented in PR body ✓
- All 9 new event categories asserted in tests across Tasks 9-10 ✓

**Placeholder scan:** Каждый шаг содержит код или точные команды; нет TBD/TODO. ✓

**Type consistency:** `_run_tt_commercial_music_hook` возвращает строку (`'handled'/'stuck'/'clean'`) — используется консистентно в Task 12+13 callers. `_handle_tt_commercial_music_modal(ui, matched_via)` сигнатура согласована с тестами Task 9. ✓
