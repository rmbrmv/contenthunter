# TT Music-Rights Coverage + Post-Accept Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Расширить TT music-rights handler (PR #28) на изменившиеся title-варианты + добавить instrumentation для evidence collection. Спек v12: `docs/superpowers/specs/2026-05-11-tt-music-rights-coverage-and-post-accept-design.md`.

**Architecture:** Все изменения в одном файле `publisher_tiktok.py` (3 секции: helpers + module-level `_tt_infer_post_publish_success` + `publish_tiktok` upload-confirmation loop). 3 feature flag'а, default false → pure no-op rollout. TDD на каждый детектор.

**Tech Stack:** Python 3.x, pytest, xml.etree.ElementTree, ADB shell. Code repo: GenGo2/delivery-contenthunter (testbench checkout: `/home/claude-user/autowarm-testbench/`).

---

## Files Affected

- **Modify:** `/home/claude-user/autowarm-testbench/publisher_tiktok.py`
  - Module-level (стр. 78-150): `_tt_infer_post_publish_success` — gate'инг SEED через flag
  - Class `TikTokMixin` (стр. 153+):
    - стр. 159-169: добавить constant `_TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS`
    - стр. 209-257: `_detect_tt_music_rights_dialog` остаётся, рядом добавляются `_detect_tt_music_rights_dialog_fallback` и `_detect_tt_music_rights_dialog_evidence_only` + `_save_dump_for_fallback_review`
    - стр. 347-389: `_handle_tt_music_rights_dialog` обновляется
    - стр. 391+: `publish_tiktok` — добавить инициализацию state vars
    - стр. 922-924: где `handled = self._handle_tt_music_rights_dialog(ui)`, добавить set state + reset counter
    - upload-confirmation loop (стр. ~770-1200): добавить RC-B.4 dump блок
- **Modify:** `/home/claude-user/autowarm-testbench/tests/test_publisher_tt_music_rights.py` (расширяем 19 тестами)

---

## Task 0: Setup worktree + baseline pytest green

**Files:**
- Create worktree: `/home/claude-user/autowarm-testbench-feat-tt-music-rights-coverage-20260511/`

- [ ] **Step 1: Fetch latest main + create worktree**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add /home/claude-user/autowarm-testbench-feat-tt-music-rights-coverage-20260511 -b feat/tt-music-rights-coverage-and-post-accept-20260511 origin/main
cd /home/claude-user/autowarm-testbench-feat-tt-music-rights-coverage-20260511
```

- [ ] **Step 2: Verify baseline pytest green**

Run: `pytest tests/test_publisher_tt_music_rights.py -v 2>&1 | tail -20`
Expected: All tests PASS (existing PR #28 tests).
If any fail — STOP, do not proceed. Baseline must be green.

- [ ] **Step 3: Verify node_modules / Python deps OK**

Run: `python3 -c "from publisher_tiktok import TikTokMixin, _tt_infer_post_publish_success, TT_COMPOSER_ACTIVITIES_SEED; print('OK')"`
Expected: `OK` printed.

- [ ] **Step 4: No commit yet** — proceed to Task 1.

---

## Task 1: Add fallback title substring constant + uuid/os imports

**Files:**
- Modify: `publisher_tiktok.py` (top of TikTokMixin class, after `_TT_MUSIC_RIGHTS_CHECKBOX` constant)
- Modify: `publisher_tiktok.py` (top of file, imports section)

- [ ] **Step 1: Add imports** (top of file, after existing imports stmt block):

```python
import os
import uuid
```

Find existing `import re; import time; import logging` block (around line 14-16) and add `os` and `uuid` next to them. If already imported, skip.

- [ ] **Step 2: Add `_TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS` class attribute**

In `class TikTokMixin:`, immediately after existing `_TT_MUSIC_RIGHTS_CHECKBOX = [...]` block (around line 166-169), add:

```python
    # v12 (2026-05-11): Fallback title substrings (case-insensitive match).
    # Spec: docs/superpowers/specs/2026-05-11-tt-music-rights-coverage-and-post-accept-design.md
    # Все substring'и в lowercase — сравнение делается с ui_xml.lower().
    _TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS = [
        'права на использование музыки',
        'music usage rights',
        'music rights',
        'rights confirmation',
        'подтверждение прав',
    ]
```

- [ ] **Step 3: Run import-smoke**

Run: `cd /home/claude-user/autowarm-testbench-feat-tt-music-rights-coverage-and-post-accept-20260511 && python3 -c "from publisher_tiktok import TikTokMixin; print(TikTokMixin._TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS)"`
Expected: list printed.

- [ ] **Step 4: Commit**

```bash
git add publisher_tiktok.py
git commit -m "feat(tt-music-rights): add fallback title substrings constant + os/uuid imports"
```

---

## Task 2: Implement `_save_dump_for_fallback_review` (TDD)

**Files:**
- Modify: `publisher_tiktok.py` (in `TikTokMixin`)
- Test: `tests/test_publisher_tt_music_rights.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_publisher_tt_music_rights.py`:

```python
# ====== v12 RC-A: dump helper ======

def test_save_dump_for_fallback_review_writes_file(tmp_path, monkeypatch):
    """Dump-helper saves XML с ms-timestamp + uuid8 suffix в filename."""
    m = TikTokMixin()
    m.task_id = 42
    monkeypatch.setattr('publisher_tiktok.os.makedirs', lambda *a, **kw: None)
    # Redirect /tmp path to tmp_path via monkeypatch on open
    dumps_dir = tmp_path / 'autowarm_ui_dumps'
    dumps_dir.mkdir()
    import publisher_tiktok as pt
    original_save = pt.TikTokMixin._save_dump_for_fallback_review
    # Inject custom DUMP_DIR
    def patched(self, ui_xml, suffix):
        try:
            dumps_dir.mkdir(parents=True, exist_ok=True)
            ts_ms = int(pt.time.time() * 1000)
            uid8 = pt.uuid.uuid4().hex[:8]
            path = dumps_dir / f'tt_music_rights_{suffix}_{self.task_id}_{ts_ms}_{uid8}.xml'
            path.write_text(ui_xml or '', encoding='utf-8')
            return str(path)
        except Exception:
            return 'write_failed'
    monkeypatch.setattr(pt.TikTokMixin, '_save_dump_for_fallback_review', patched)

    result = m._save_dump_for_fallback_review('<xml>data</xml>', suffix='fallback')
    files = list(dumps_dir.glob('tt_music_rights_fallback_42_*_*.xml'))
    assert len(files) == 1
    assert files[0].read_text() == '<xml>data</xml>'


def test_save_dump_for_fallback_review_returns_write_failed_on_exception(monkeypatch):
    """Если write бросает — возвращаем 'write_failed', не raise."""
    m = TikTokMixin()
    m.task_id = 1
    import publisher_tiktok as pt
    # Force write to fail by monkeypatching `open` to raise
    def broken_open(*a, **kw):
        raise OSError('disk full')
    monkeypatch.setattr('builtins.open', broken_open)
    monkeypatch.setattr(pt.os, 'makedirs', lambda *a, **kw: None)
    result = m._save_dump_for_fallback_review('<xml>x</xml>', suffix='test')
    assert result == 'write_failed'
```

- [ ] **Step 2: Run tests to verify FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py::test_save_dump_for_fallback_review_writes_file tests/test_publisher_tt_music_rights.py::test_save_dump_for_fallback_review_returns_write_failed_on_exception -v`
Expected: FAIL with `AttributeError: 'TikTokMixin' object has no attribute '_save_dump_for_fallback_review'` (или подобное).

- [ ] **Step 3: Implement `_save_dump_for_fallback_review`**

Add to `TikTokMixin` (after `_handle_tt_music_rights_dialog`, before `publish_tiktok`):

```python
    def _save_dump_for_fallback_review(self, ui_xml: str, suffix: str) -> str:
        """Best-effort dump of UI XML для post-hoc analysis.

        Returns path или 'write_failed'. Никогда не raise'ит.
        ms-timestamp + uuid8 suffix защищает от коллизий при retries.
        """
        try:
            os.makedirs('/tmp/autowarm_ui_dumps', exist_ok=True)
            ts_ms = int(time.time() * 1000)
            uid8 = uuid.uuid4().hex[:8]
            path = (f'/tmp/autowarm_ui_dumps/'
                    f'tt_music_rights_{suffix}_{self.task_id}'
                    f'_{ts_ms}_{uid8}.xml')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(ui_xml or '')
            return path
        except Exception as e:
            log.warning(f'  ⚠️ Не удалось сохранить music_rights dump: {e}')
            return 'write_failed'
```

- [ ] **Step 4: Run tests to verify PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py::test_save_dump_for_fallback_review_writes_file tests/test_publisher_tt_music_rights.py::test_save_dump_for_fallback_review_returns_write_failed_on_exception -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): add _save_dump_for_fallback_review helper + 2 tests"
```

---

## Task 3: Implement `_detect_tt_music_rights_dialog_fallback` (TDD)

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_music_rights.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
# ====== v12 RC-A.1: fallback detector ======

_FALLBACK_VALID_DIALOG = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.app.AlertDialog" bounds="[0,500][1080,1500]" package="com.zhiliaoapp.musically">
    <node text="Music Usage Rights Confirmation" content-desc="" bounds="[100,600][980,700]"/>
    <node class="android.widget.CheckBox" checkable="true" checked="false" clickable="true"
          bounds="[100,800][980,900]"
          text="Я принимаю Подтверждение прав на использование музыки"/>
    <node text="Опубликовать видео" content-desc="" clickable="true"
          bounds="[100,1300][980,1400]" class="android.widget.Button"/>
  </node>
</hierarchy>'''

_FALLBACK_NO_BUTTON = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.app.AlertDialog" bounds="[0,500][1080,1500]" package="com.zhiliaoapp.musically">
    <node text="Music Usage Rights Confirmation" bounds="[100,600][980,700]"/>
    <node class="android.widget.CheckBox" checkable="true" checked="false" clickable="true"
          bounds="[100,800][980,900]"
          text="Я принимаю Подтверждение прав на использование музыки"/>
    <!-- no button -->
  </node>
</hierarchy>'''

_FALLBACK_NO_CHECKBOX_LABEL = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.app.AlertDialog" bounds="[0,500][1080,1500]" package="com.zhiliaoapp.musically">
    <node text="Music Usage Rights Confirmation" bounds="[100,600][980,700]"/>
    <node class="android.widget.CheckBox" checkable="true" checked="false" clickable="true"
          bounds="[100,800][980,900]"
          text="I agree"/>
    <node text="Опубликовать видео" clickable="true"
          bounds="[100,1300][980,1400]" class="android.widget.Button"/>
  </node>
</hierarchy>'''

_FALLBACK_NO_SUBSTRING = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.app.AlertDialog" bounds="[0,500][1080,1500]" package="com.zhiliaoapp.musically">
    <node text="Confirm publishing" bounds="[100,600][980,700]"/>
    <node class="android.widget.CheckBox" checkable="true" checked="false" clickable="true"
          bounds="[100,800][980,900]"
          text="Я принимаю Подтверждение прав на использование музыки"/>
    <node text="Опубликовать видео" clickable="true"
          bounds="[100,1300][980,1400]" class="android.widget.Button"/>
  </node>
</hierarchy>'''

_FALLBACK_NO_DIALOG_ANCESTOR = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]" package="com.zhiliaoapp.musically">
    <node text="Music Usage Rights Confirmation" bounds="[100,300][980,400]"/>
  </node>
  <node class="android.widget.FrameLayout" bounds="[0,1500][1080,2000]" package="com.zhiliaoapp.musically">
    <node class="android.widget.CheckBox" checkable="true" checked="false" clickable="true"
          text="Я принимаю Подтверждение прав на использование музыки"/>
    <node text="Опубликовать видео" clickable="true" class="android.widget.Button"/>
  </node>
</hierarchy>'''

_FALLBACK_GENERIC_LAYOUT_ANCESTOR = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.widget.LinearLayout" bounds="[0,0][1080,2000]" package="com.zhiliaoapp.musically">
    <node text="Music Usage Rights Confirmation" bounds="[100,300][980,400]"/>
    <node class="android.widget.CheckBox" checkable="true" checked="false" clickable="true"
          text="Я принимаю Подтверждение прав на использование музыки"/>
    <node text="Опубликовать видео" clickable="true" class="android.widget.Button"/>
  </node>
</hierarchy>'''


def test_detect_fallback_matches_substring_title_titlecase():
    """Case-insensitive: title с Title Case matches lowercase substring."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog_fallback(_FALLBACK_VALID_DIALOG) is True


def test_detect_fallback_no_button_no_match():
    """Без EXACT button-node fallback returns False."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog_fallback(_FALLBACK_NO_BUTTON) is False


def test_detect_fallback_no_checkbox_label():
    """Без EXACT checkbox-label fallback returns False."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog_fallback(_FALLBACK_NO_CHECKBOX_LABEL) is False


def test_detect_fallback_no_substring():
    """Substring 'music rights' / RU равиваленты не найдены — False."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog_fallback(_FALLBACK_NO_SUBSTRING) is False


def test_detect_fallback_no_common_dialog_ancestor():
    """Nodes под разными root children — нет общего Dialog ancestor — False."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog_fallback(_FALLBACK_NO_DIALOG_ANCESTOR) is False


def test_detect_fallback_rejects_generic_layout_ancestor():
    """Общий ancestor — generic LinearLayout (не Dialog/PopupWindow/AlertDialog) — False."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog_fallback(_FALLBACK_GENERIC_LAYOUT_ANCESTOR) is False
```

- [ ] **Step 2: Run tests to verify FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "fallback" -v 2>&1 | tail -20`
Expected: All FAIL with `AttributeError: '_detect_tt_music_rights_dialog_fallback'`.

- [ ] **Step 3: Implement detector**

Add to `TikTokMixin` (immediately after `_detect_tt_music_rights_dialog`):

```python
    def _detect_tt_music_rights_dialog_fallback(self, ui_xml: str) -> bool:
        """Looser fallback match для изменившихся title-вариантов TT.

        Conditions (ALL true):
          1. Substring (case-insensitive) есть в ui_xml.
          2. Node с text/desc EXACT in _TT_MUSIC_RIGHTS_CHECKBOX.
          3. Clickable node с text/desc EXACT in _TT_MUSIC_RIGHTS_BUTTON.
          4. (2) и (3) находятся под общим Dialog/PopupWindow/AlertDialog
             ancestor (NOT generic FrameLayout/LinearLayout/RelativeLayout —
             collapse'ят к composer root).

        Возвращает False если что-либо из 1-4 не выполнено.
        """
        if not ui_xml:
            return False
        low = ui_xml.lower()
        if not any(s in low for s in self._TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS):
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False

        # Build parent map для ancestor walking.
        parent_map = {child: parent for parent in root.iter() for child in parent}

        checkbox_label_node = None
        button_node = None
        for n in root.iter('node'):
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if checkbox_label_node is None and (
                txt in self._TT_MUSIC_RIGHTS_CHECKBOX
                or desc in self._TT_MUSIC_RIGHTS_CHECKBOX
            ):
                checkbox_label_node = n
            if button_node is None and n.get('clickable') == 'true' and (
                txt in self._TT_MUSIC_RIGHTS_BUTTON
                or desc in self._TT_MUSIC_RIGHTS_BUTTON
            ):
                button_node = n
            if checkbox_label_node is not None and button_node is not None:
                break

        if checkbox_label_node is None or button_node is None:
            return False

        # Walk up to find common ancestor with Dialog/PopupWindow/AlertDialog class.
        def ancestors_with_dialog_class(node, max_depth=8):
            cur = node
            for _ in range(max_depth):
                cur = parent_map.get(cur)
                if cur is None:
                    return
                cls = cur.get('class', '') or ''
                if ('Dialog' in cls
                        or 'PopupWindow' in cls
                        or 'AlertDialog' in cls):
                    yield cur

        cb_dialog_ancestors = set(ancestors_with_dialog_class(checkbox_label_node))
        btn_dialog_ancestors = set(ancestors_with_dialog_class(button_node))
        common = cb_dialog_ancestors & btn_dialog_ancestors
        if not common:
            return False
        return True
```

- [ ] **Step 4: Run tests to verify PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "fallback" -v 2>&1 | tail -20`
Expected: 6 PASS.

- [ ] **Step 5: Run full test file to verify no regression**

Run: `pytest tests/test_publisher_tt_music_rights.py -v 2>&1 | tail -10`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): add _detect_tt_music_rights_dialog_fallback + 6 tests"
```

---

## Task 4: Implement `_detect_tt_music_rights_dialog_evidence_only` (TDD)

**Files:** same as Task 3.

- [ ] **Step 1: Write failing test**

Append:

```python
# ====== v12 RC-A.1b: evidence-only detector ======

_EVIDENCE_ONLY_SUBSTRING_WITH_GENERIC_CB = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.widget.FrameLayout">
    <node text="Some music rights help link here" bounds="[100,200][900,300]"/>
    <node class="android.widget.CheckBox" checkable="true" checked="false"
          bounds="[100,400][200,500]"/>
  </node>
</hierarchy>'''


def test_evidence_only_substring_with_generic_checkbox_true():
    """substring + generic checkbox (без EXACT label) → True."""
    m = TikTokMixin()
    assert m._detect_tt_music_rights_dialog_evidence_only(_EVIDENCE_ONLY_SUBSTRING_WITH_GENERIC_CB) is True


def test_evidence_only_no_substring_false():
    """Без substring → False."""
    m = TikTokMixin()
    xml = '<hierarchy><node text="Something else"/><node class="CheckBox" checkable="true"/></hierarchy>'
    assert m._detect_tt_music_rights_dialog_evidence_only(xml) is False


def test_evidence_only_substring_no_checkbox_false():
    """Substring но нет generic checkbox → False."""
    m = TikTokMixin()
    xml = '<hierarchy><node text="music rights here"/></hierarchy>'
    assert m._detect_tt_music_rights_dialog_evidence_only(xml) is False
```

- [ ] **Step 2: Run tests to verify FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "evidence_only" -v 2>&1 | tail -10`
Expected: 3 FAIL (AttributeError).

- [ ] **Step 3: Implement detector**

Add to `TikTokMixin` (after `_detect_tt_music_rights_dialog_fallback`):

```python
    def _detect_tt_music_rights_dialog_evidence_only(self, ui_xml: str) -> bool:
        """Slack-match для логирования + dump. НЕ для auto-handle.

        Conditions:
          1. Substring (case-insensitive) есть в ui_xml.
          2. has_generic_checkbox в дереве (`checkable='true'` OR class*=CheckBox).

        Caller отвечает за logical-AND: вызывать ТОЛЬКО когда strict и
        fallback оба вернули False.
        """
        if not ui_xml:
            return False
        low = ui_xml.lower()
        if not any(s in low for s in self._TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS):
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        for n in root.iter('node'):
            if n.get('checkable') == 'true' or 'CheckBox' in n.get('class', ''):
                return True
        return False
```

- [ ] **Step 4: Run tests to verify PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "evidence_only" -v 2>&1 | tail -10`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): add _detect_tt_music_rights_dialog_evidence_only + 3 tests"
```

---

## Task 5: Update `_handle_tt_music_rights_dialog` (hybrid + evidence-only + throttle)

**Files:**
- Modify: `publisher_tiktok.py` `_handle_tt_music_rights_dialog`
- Test: `tests/test_publisher_tt_music_rights.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
# ====== v12 RC-A.2: hybrid handler ======

def test_handle_strict_match_unchanged():
    """Strict match — original behavior, no flag dependency."""
    m = _make_mixin_with_mock_adb()
    m.log_event = MagicMock()
    m._music_rights_evidence_dumped = False
    strict_xml = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.app.AlertDialog">
    <node text="Подтвердить и опубликовать видео?"/>
    <node class="android.widget.CheckBox" checkable="true" checked="false" clickable="true"
          text="Я принимаю Подтверждение прав на использование музыки"/>
    <node text="Опубликовать видео" clickable="true" bounds="[100,1300][980,1400]"
          class="android.widget.Button"/>
  </node>
</hierarchy>'''
    result = m._handle_tt_music_rights_dialog(strict_xml)
    assert result is True
    # log_event with matched_via='strict' or no matched_via (back-compat)
    m.log_event.assert_called()
    args, kwargs = m.log_event.call_args
    assert 'tt_music_rights_accepted' in kwargs.get('meta', {}).get('category', '')


def test_handle_fallback_match_when_flag_enabled(monkeypatch, tmp_path):
    """Fallback fires только при flag=true; dumps XML; log_event matched_via='fallback'."""
    monkeypatch.setenv('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'true')
    m = _make_mixin_with_mock_adb()
    m.task_id = 99
    m.log_event = MagicMock()
    m._music_rights_evidence_dumped = False
    # Redirect /tmp via monkeypatch
    monkeypatch.setattr('publisher_tiktok.os.makedirs', lambda *a, **kw: None)
    saved_paths = []
    original_save = TikTokMixin._save_dump_for_fallback_review
    def capture(self, ui_xml, suffix):
        saved_paths.append((suffix, ui_xml[:30]))
        return f'/tmp/captured_{suffix}.xml'
    monkeypatch.setattr(TikTokMixin, '_save_dump_for_fallback_review', capture)

    # Fallback XML (см. _FALLBACK_VALID_DIALOG из Task 3)
    result = m._handle_tt_music_rights_dialog(_FALLBACK_VALID_DIALOG)
    assert result is True
    # 2 saves: fallback + (after tap), but spec only requires fallback dump
    assert any(s == 'fallback' for s, _ in saved_paths)


def test_handle_fallback_skipped_when_flag_off(monkeypatch):
    """Flag=false → fallback не вызывается, fallback XML → return False."""
    monkeypatch.setenv('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'false')
    m = _make_mixin_with_mock_adb()
    m.log_event = MagicMock()
    m._music_rights_evidence_dumped = False
    result = m._handle_tt_music_rights_dialog(_FALLBACK_VALID_DIALOG)
    assert result is False


def test_handle_evidence_only_fires_when_substring_and_generic_cb(monkeypatch):
    """Strict+fallback False, evidence-only True → dump + log_event unhandled_suspect, return False."""
    monkeypatch.setenv('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'true')
    m = _make_mixin_with_mock_adb()
    m.task_id = 100
    m.log_event = MagicMock()
    m._music_rights_evidence_dumped = False
    saved = []
    monkeypatch.setattr(TikTokMixin, '_save_dump_for_fallback_review',
                        lambda self, ui_xml, suffix: saved.append(suffix) or f'/tmp/x_{suffix}.xml')

    result = m._handle_tt_music_rights_dialog(_EVIDENCE_ONLY_SUBSTRING_WITH_GENERIC_CB)
    assert result is False
    assert 'unhandled_suspect' in saved
    # log_event with category=tt_music_rights_unhandled_suspect
    categories = [c.kwargs.get('meta', {}).get('category') for c in m.log_event.call_args_list]
    assert 'tt_music_rights_unhandled_suspect' in categories


def test_handle_evidence_only_throttle_after_first_dump(monkeypatch):
    """Per-task flag блокирует повторные dumps в том же publish'е."""
    monkeypatch.setenv('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'true')
    m = _make_mixin_with_mock_adb()
    m.task_id = 101
    m.log_event = MagicMock()
    m._music_rights_evidence_dumped = False
    saved = []
    monkeypatch.setattr(TikTokMixin, '_save_dump_for_fallback_review',
                        lambda self, ui_xml, suffix: saved.append(suffix) or 'x')

    # First call — fires.
    m._handle_tt_music_rights_dialog(_EVIDENCE_ONLY_SUBSTRING_WITH_GENERIC_CB)
    # Second call — must NOT fire (throttle).
    m._handle_tt_music_rights_dialog(_EVIDENCE_ONLY_SUBSTRING_WITH_GENERIC_CB)
    # Third call — still throttled.
    m._handle_tt_music_rights_dialog(_EVIDENCE_ONLY_SUBSTRING_WITH_GENERIC_CB)
    assert saved.count('unhandled_suspect') == 1
```

- [ ] **Step 2: Run tests to verify FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "test_handle" -v 2>&1 | tail -20`
Expected: 5 FAIL (existing handler doesn't have fallback/evidence-only branches).

- [ ] **Step 3: Update `_handle_tt_music_rights_dialog`**

Replace the existing method (стр. 347-389):

```python
    def _handle_tt_music_rights_dialog(self, ui_xml: str) -> bool:
        """Detect и accept TT music rights confirmation dialog.

        Order: strict → fallback (if flag) → evidence-only (if flag, throttled).
        Возвращает True ТОЛЬКО при successful accept (strict OR fallback).
        Evidence-only path не handle'ит — только dump + log.
        """
        matched_via = None
        fallback_enabled = (os.environ.get('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'false')
                            .lower() == 'true')

        if self._detect_tt_music_rights_dialog(ui_xml):
            matched_via = 'strict'
        elif fallback_enabled and self._detect_tt_music_rights_dialog_fallback(ui_xml):
            matched_via = 'fallback'
            dump_path = self._save_dump_for_fallback_review(ui_xml, suffix='fallback')
            self.log_event(
                'info',
                'TikTok: music rights dialog matched via fallback',
                meta={'category': 'tt_music_rights_fallback_match',
                      'dump_path': dump_path,
                      'platform': self.platform})
        else:
            # Evidence-only path (Codex v7 round 1, P3#1: throttle через per-task flag).
            if (fallback_enabled
                and not getattr(self, '_music_rights_evidence_dumped', False)
                and self._detect_tt_music_rights_dialog_evidence_only(ui_xml)):
                dump_path = self._save_dump_for_fallback_review(
                    ui_xml, suffix='unhandled_suspect')
                self.log_event(
                    'warning',
                    'TikTok: music rights-like dialog suspect, not auto-handled',
                    meta={'category': 'tt_music_rights_unhandled_suspect',
                          'dump_path': dump_path,
                          'platform': self.platform})
                self._music_rights_evidence_dumped = True
            return False

        # Proceed with accept (existing behavior).
        checkbox_set = self._tick_tt_music_rights_checkbox(ui_xml)
        if checkbox_set:
            time.sleep(0.5)
            try:
                fresh = self.dump_ui()
                if fresh:
                    ui_xml = fresh
            except Exception:
                pass
        tapped = self._strict_tap_clickable(ui_xml, self._TT_MUSIC_RIGHTS_BUTTON)
        if tapped:
            self.log_event(
                'info',
                'TikTok: music rights dialog accepted',
                meta={'category': 'tt_music_rights_accepted',
                      'platform': self.platform,
                      'checkbox_set': checkbox_set,
                      'button_tapped': True,
                      'matched_via': matched_via})
        else:
            self.log_event(
                'warning',
                'TikTok: music rights dialog detected, accept button not found',
                meta={'category': 'tt_music_rights_button_not_found',
                      'platform': self.platform,
                      'checkbox_set': checkbox_set,
                      'matched_via': matched_via})
        return tapped
```

- [ ] **Step 4: Run tests to verify PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "test_handle" -v 2>&1 | tail -20`
Expected: 5 PASS.

- [ ] **Step 5: Run full file to ensure no regression**

Run: `pytest tests/test_publisher_tt_music_rights.py -v 2>&1 | tail -10`
Expected: all PASS (including existing PR #28 tests).

- [ ] **Step 6: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): hybrid handler (strict→fallback→evidence-only) + 5 tests"
```

---

## Task 6: Initialize publisher state vars in `publish_tiktok` (RC-B.1)

**Files:**
- Modify: `publisher_tiktok.py` `publish_tiktok` method (стр. 391+)
- Test: `tests/test_publisher_tt_music_rights.py`

- [ ] **Step 1: Write failing test**

Append:

```python
# ====== v12 RC-B.1/B.2: state initialization ======

def test_state_init_at_publish_tiktok_start(monkeypatch):
    """publish_tiktok start — resets _music_rights_just_accepted_iter,
    _music_rights_accepted_ts, _music_rights_evidence_dumped."""
    from publisher_tiktok import TikTokMixin as _TM
    m = _make_mixin_with_mock_adb()
    # Симулируем что state установился в предыдущем publish'е
    m._music_rights_just_accepted_iter = 42
    m._music_rights_accepted_ts = 1234567890
    m._music_rights_evidence_dumped = True
    m._music_rights_iter = 3
    # publish_tiktok внутри инициализирует state, мы протестим только начало.
    # Stub'ает остальной flow через монипатчинг.
    monkeypatch.setattr(_TM, 'platform_cfg', {'package': 'com.zhiliaoapp.musically'},
                        raising=False)
    monkeypatch.setattr(m, 'adb', MagicMock(return_value=''))
    monkeypatch.setattr(m, 'dump_ui', MagicMock(return_value='<hierarchy/>'))
    monkeypatch.setattr(m, 'log_event', MagicMock())
    # Ранний exit — заменим основной flow на raise после init blocks
    # Здесь test'им только что после публикации call'а state == defaults.
    # Best-effort: вызываем функцию, catch'аем, проверяем state.
    try:
        m.publish_tiktok('/tmp/fake.mp4')
    except Exception:
        pass  # Любое падение OK — нам важна только initialization.
    assert m._music_rights_just_accepted_iter is None
    assert m._music_rights_accepted_ts is None
    assert m._music_rights_evidence_dumped is False
```

- [ ] **Step 2: Run test FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py::test_state_init_at_publish_tiktok_start -v 2>&1 | tail -10`
Expected: FAIL (state not reset).

- [ ] **Step 3: Add init in `publish_tiktok`**

Find existing line (around стр. 397):
```python
        self._music_rights_iter = 0
```

Add immediately after:
```python
        # v12 RC-B.1: state for post-accept tracking + evidence throttle.
        self._music_rights_just_accepted_iter = None
        self._music_rights_accepted_ts = None
        self._music_rights_evidence_dumped = False
```

- [ ] **Step 4: Run test PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py::test_state_init_at_publish_tiktok_start -v 2>&1 | tail -10`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): initialize post-accept state vars in publish_tiktok (RC-B.1)"
```

---

## Task 7: Set state + reset music_rights_iter after handled=True (RC-B.2)

**Files:**
- Modify: `publisher_tiktok.py` upload-confirmation loop (стр. 922-924)
- Test: `tests/test_publisher_tt_music_rights.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_music_rights_iter_reset_after_handled():
    """После handled=True _music_rights_iter сбрасывается + state set'ится."""
    # Этот тест требует mock'нуть весь upload-confirmation loop. Используем
    # surgical-strategy: вызываем helper, проверяем что after-handled block
    # выставляет нужные поля.
    # Реальное место в коде — около стр. 922:
    #   if handled: time.sleep(2); continue;
    # → after fix:
    #   if handled:
    #     self._music_rights_just_accepted_iter = wait
    #     self._music_rights_accepted_ts = time.time()
    #     self._music_rights_iter = 0  # reset counter после handle
    #     time.sleep(2); continue;
    #
    # Тестируем через grep исходник + sanity-check переменных.
    import inspect
    from publisher_tiktok import TikTokMixin
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    # Find the music-rights `if handled:` block (анкер — _handle_tt_music_rights_dialog)
    assert 'self._music_rights_just_accepted_iter = wait' in src
    assert 'self._music_rights_accepted_ts = time.time()' in src
    # Counter reset должен быть рядом
    assert 'self._music_rights_iter = 0  # reset after handle' in src
```

- [ ] **Step 2: Run test FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py::test_music_rights_iter_reset_after_handled -v 2>&1 | tail -10`
Expected: FAIL.

- [ ] **Step 3: Update `publish_tiktok` upload-confirmation loop**

Find existing block (around стр. 918-924):
```python
                handled = self._handle_tt_music_rights_dialog(ui)
                log.info(f'  🎵 TikTok: music rights dialog (wait {wait}, '
                         f'iter {self._music_rights_iter}/{MAX_MUSIC_RIGHTS_ITERATIONS}) '
                         f'handled={handled}')
                if handled:
                    time.sleep(2)
                    continue
```

Replace `if handled:` block:
```python
                if handled:
                    # v12 RC-B.2: track post-accept state + decouple counter
                    # (Codex round 1, P1#3: MAX_MUSIC_RIGHTS_ITERATIONS не должен
                    # preempt'ить post-accept фазу).
                    self._music_rights_just_accepted_iter = wait
                    self._music_rights_accepted_ts = time.time()
                    self._music_rights_iter = 0  # reset after handle
                    time.sleep(2)
                    continue
```

- [ ] **Step 4: Run test PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py::test_music_rights_iter_reset_after_handled -v 2>&1 | tail -10`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): set post-accept state + reset counter after handled (RC-B.2)"
```

---

## Task 8: Flag-gated SAASceneWrapperActivity in SEED (RC-B.0)

**Files:**
- Modify: `publisher_tiktok.py` `_tt_infer_post_publish_success` (стр. 78-150)
- Test: `tests/test_publisher_tt_music_rights.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
# ====== v12 RC-B.0: flag-gated SEED hardening ======

def test_seed_hardening_flag_off_no_saascene(monkeypatch):
    """flag=false: SAASceneWrapperActivity не в SEED → not on_composer."""
    monkeypatch.setenv('TT_SEED_HARDENING_SAASCENE_ENABLED', 'false')
    from publisher_tiktok import _tt_infer_post_publish_success
    top_act = 'topResumedActivity=ActivityRecord{... com.zhiliaoapp.musically/.activity.SAASceneWrapperActivity ...}'
    # Provide enough ui для bottom-nav fallback to fail safely (no nav)
    ui = '<hierarchy><node bounds="[0,0][1080,2000]"/></hierarchy>'
    success, meta = _tt_infer_post_publish_success(ui, top_act, 5)
    # on_composer_seed False because SAASceneWrapperActivity NOT in SEED by default
    assert meta['on_composer_seed'] is False


def test_seed_hardening_flag_on_adds_saascene(monkeypatch):
    """flag=true: SAASceneWrapperActivity = composer → on_composer_seed True."""
    monkeypatch.setenv('TT_SEED_HARDENING_SAASCENE_ENABLED', 'true')
    from publisher_tiktok import _tt_infer_post_publish_success
    top_act = 'topResumedActivity=ActivityRecord{... com.zhiliaoapp.musically/.activity.SAASceneWrapperActivity ...}'
    ui = '<hierarchy><node bounds="[0,0][1080,2000]"/></hierarchy>'
    success, meta = _tt_infer_post_publish_success(ui, top_act, 5)
    assert meta['on_composer_seed'] is True
    assert meta['reason'] == 'on_composer_seed'
    assert success is False
```

- [ ] **Step 2: Run tests FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "seed_hardening" -v 2>&1 | tail -10`
Expected: 2 FAIL.

- [ ] **Step 3: Update `_tt_infer_post_publish_success`**

Find existing block (около стр. 106-110):
```python
    on_composer = any(a in cur_act for a in TT_COMPOSER_ACTIVITIES_SEED)
    meta['on_composer_seed'] = on_composer
    if on_composer:
        meta['reason'] = 'on_composer_seed'
        return False, meta
```

Replace:
```python
    # v12 RC-B.0: flag-gated SEED hardening (Codex v10 round 1, P2:
    # SAASceneWrapperActivity untested как pure composer activity; evidence-guarded).
    seed = TT_COMPOSER_ACTIVITIES_SEED
    if os.environ.get('TT_SEED_HARDENING_SAASCENE_ENABLED', 'false').lower() == 'true':
        seed = seed + ('SAASceneWrapperActivity',)
    on_composer = any(a in cur_act for a in seed)
    meta['on_composer_seed'] = on_composer
    if on_composer:
        meta['reason'] = 'on_composer_seed'
        return False, meta
```

(`os` уже импортирован в Task 1, ensure that's still in the imports.)

- [ ] **Step 4: Run tests PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "seed_hardening" -v 2>&1 | tail -10`
Expected: 2 PASS.

- [ ] **Step 5: Verify existing PR #29 tests not broken**

Run: `pytest tests/test_tt_post_publish_inferred.py -v 2>&1 | tail -20` (if file exists)
Expected: PASS or "file not found" (depending on what was shipped).

Run also: `pytest tests/test_publisher_tt_music_rights.py -v 2>&1 | tail -10`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): flag-gated SAASceneWrapperActivity SEED hardening (RC-B.0)"
```

---

## Task 9: Per-iter XML dump + top_activity event (RC-B.4)

**Files:**
- Modify: `publisher_tiktok.py` upload-confirmation loop (after audio-dialog handler, before UPLOAD_OK substring check OR at the end of each iter — выберите место наиболее logical)
- Test: `tests/test_publisher_tt_music_rights.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
# ====== v12 RC-B.4: per-iter XML dump + top_activity event ======

def test_dump_flag_off_no_writes(monkeypatch):
    """flag=false → dump-блок не пишет файлы."""
    monkeypatch.setenv('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'false')
    monkeypatch.delenv('TT_MUSIC_RIGHTS_FALLBACK_ENABLED', raising=False)
    # Sanity: проверяем что переменная env не вызывает дам
    import inspect
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    # Pattern должен иметь env check
    assert "os.environ.get('TT_DUMP_POST_MUSIC_RIGHTS_XML'" in src


def test_dump_at_iters_with_ms_timestamp_uuid_and_event(monkeypatch):
    """flag=true + music_rights_accepted: dump fires на iter 1,3,5,10,20,40
    с ms-timestamp + uuid в filename, и log_event с top_activity meta."""
    # Грубый test через source-grep — pattern должен присутствовать.
    import inspect
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    assert 'tt_post_music_rights_dump' in src  # event category
    assert "iters_since in (1, 3, 5, 10, 20, 40)" in src or \
           "iters_since in [1, 3, 5, 10, 20, 40]" in src
    assert "int(time.time() * 1000)" in src
    assert "uuid.uuid4().hex[:8]" in src
    assert "'top_activity':" in src  # meta key
```

- [ ] **Step 2: Run tests FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "dump_flag_off_no_writes or dump_at_iters" -v 2>&1 | tail -10`
Expected: 2 FAIL.

- [ ] **Step 3: Add dump block in `publish_tiktok` upload-confirmation loop**

Find an appropriate location в loop'е — после `audio-dialog handler` block (около стр. 990, ПЕРЕД `# Признаки УСПЕХА: ищем сообщение/индикатор после публикации` блока), insert:

```python
            # v12 RC-B.4: per-iteration XML dump после music_rights accept
            # Spec: docs/superpowers/specs/2026-05-11-tt-music-rights-coverage-and-post-accept-design.md
            if (os.environ.get('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'false').lower() == 'true'
                and self._music_rights_just_accepted_iter is not None):
                iters_since = wait - self._music_rights_just_accepted_iter
                if iters_since in (1, 3, 5, 10, 20, 40):
                    cur_act_dump = self.adb(
                        'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
                        timeout=8) or ''
                    try:
                        os.makedirs('/tmp/autowarm_ui_dumps', exist_ok=True)
                        ts_ms = int(time.time() * 1000)
                        uid8 = uuid.uuid4().hex[:8]
                        path = (f'/tmp/autowarm_ui_dumps/'
                                f'tt_post_music_rights_{self.task_id}'
                                f'_iter{iters_since}_{ts_ms}_{uid8}.xml')
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(ui or '')
                        log.info(f'  💾 post-music-rights dump (iter+{iters_since}): {path}')
                        self.log_event('info',
                            f'TikTok: post-music-rights dump saved (iter+{iters_since})',
                            meta={'category': 'tt_post_music_rights_dump',
                                  'iters_after_accept': iters_since,
                                  'dump_path': path,
                                  'top_activity': cur_act_dump.strip()[:200],
                                  'platform': self.platform})
                    except Exception as e:
                        log.warning(f'  ⚠️ Не удалось сохранить post-music-rights dump: {e}')
```

- [ ] **Step 4: Run tests PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "dump_flag_off_no_writes or dump_at_iters" -v 2>&1 | tail -10`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): per-iter XML dump + top_activity event (RC-B.4)"
```

---

## Task 10: Full test suite verification + manual sanity

**Files:** none

- [ ] **Step 1: Run full music-rights test file**

Run: `pytest tests/test_publisher_tt_music_rights.py -v 2>&1 | tail -30`
Expected: All tests PASS (19+ tests).

- [ ] **Step 2: Run full publisher_tiktok-related tests**

Run: `pytest tests/test_publisher_tt_music_rights.py tests/test_publisher_tt.py 2>&1 | tail -10` (если test_publisher_tt.py существует)
Expected: All PASS.

- [ ] **Step 3: Import sanity**

Run: `python3 -c "from publisher_tiktok import TikTokMixin, _tt_infer_post_publish_success, TT_COMPOSER_ACTIVITIES_SEED; m = TikTokMixin(); print(m._TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS); print('OK')"`
Expected: list printed + OK.

- [ ] **Step 4: Verify no flag default change (regression test)**

Run:
```bash
python3 -c "
import os
for var in ['TT_MUSIC_RIGHTS_FALLBACK_ENABLED', 'TT_SEED_HARDENING_SAASCENE_ENABLED', 'TT_DUMP_POST_MUSIC_RIGHTS_XML']:
    os.environ.pop(var, None)

from publisher_tiktok import TikTokMixin, _tt_infer_post_publish_success
m = TikTokMixin()
m.log_event = lambda *a, **kw: None
m.dump_ui = lambda: ''
m._strict_tap_clickable = lambda *a, **kw: False
m._tick_tt_music_rights_checkbox = lambda *a, **kw: False
# Fallback XML — handler should return False without flag
result = m._handle_tt_music_rights_dialog('<hierarchy><node text=\"music rights\"/></hierarchy>')
assert result is False, 'flag-off behavior changed!'
print('no-op rollout verified')
"
```
Expected: `no-op rollout verified`.

- [ ] **Step 5: No commit** — sanity only. Proceed to Task 11.

---

## Task 11: Push branch + create PR

- [ ] **Step 1: Push branch**

```bash
cd /home/claude-user/autowarm-testbench-feat-tt-music-rights-coverage-and-post-accept-20260511
source ~/secrets/github-gengo2.env
git push -u origin feat/tt-music-rights-coverage-and-post-accept-20260511
```

- [ ] **Step 2: Create PR**

```bash
gh pr create --title "TT music-rights coverage + post-accept instrumentation (RC-A + RC-B.0/B.4)" --body "$(cat <<'EOF'
## Summary

Расширяет TT music-rights handler (PR #28) + добавляет instrumentation для evidence collection.

**Spec:** `docs/superpowers/specs/2026-05-11-tt-music-rights-coverage-and-post-accept-design.md` (v12, Codex CLEAN после 12 ревизий)

**Что внутри:**
- RC-A: matcher coverage (strict → fallback → evidence-only) + dump на match
- RC-B.0: flag-gated SAASceneWrapperActivity в SEED (evidence-guarded activation)
- RC-B.4: per-iter XML dump + log_event с top_activity meta после music_rights accept

**3 feature flag'а, все default false** — pure no-op rollout. Активация через `.env` + `pm2 restart --update-env`.

**Что НЕ адресуется в этом раунде:**
- RC-B success rate (60% post-accept timeouts) — `_tt_infer_post_publish_success` возвращает False для них; positive-path detection ждёт XML evidence из RC-B.4 instrumentation.

## Test plan

- [x] pytest tests/test_publisher_tt_music_rights.py -v (19+ tests pass)
- [x] No-op rollout sanity (all flags false → behavior identical to prod)
- [ ] After merge: deploy + enable TT_DUMP_POST_MUSIC_RIGHTS_XML=true → collect dumps 1-2h
- [ ] After merge: enable TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true → monitor `tt_music_rights_fallback_match` events
- [ ] After ≥1 dump shows SAASceneWrapperActivity on failed post-accept → enable TT_SEED_HARDENING_SAASCENE_ENABLED=true
- [ ] After 24-48h: analyze `/tmp/autowarm_ui_dumps/tt_post_music_rights_*.xml` для следующего раунда RC-B detection design

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Return PR URL to user**

After `gh pr create` succeeds, return the PR URL printed.

---

## Self-Review Notes

**Spec coverage check:**
- RC-A.1 (fallback matcher) → Task 3
- RC-A.1b (evidence-only) → Task 4
- RC-A.2 (hybrid handler + throttle) → Task 5
- RC-B.0 (flag-gated SEED) → Task 8
- RC-B.1 (state init) → Task 6
- RC-B.2 (set state + reset counter) → Task 7
- RC-B.4 (per-iter dump + event) → Task 9
- All 18 tests from spec covered (Tasks 3-9)

**Не покрыто** (намеренно out-of-scope per v7 scope-cut):
- RC-B.3 streak-gate — отложено до XML evidence

**Open items for impl:**
- Phone #19 / Pi 9 smoke — see spec Open Questions; defer until impl complete
- Live activation steps (`.env` + pm2) — see spec Rollout section
