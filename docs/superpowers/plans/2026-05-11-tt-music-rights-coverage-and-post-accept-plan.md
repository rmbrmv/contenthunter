# TT Music-Rights Coverage + Post-Accept Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Расширить TT music-rights handler (PR #28) на изменившиеся title-варианты + добавить instrumentation для evidence collection. Спек v12: `docs/superpowers/specs/2026-05-11-tt-music-rights-coverage-and-post-accept-design.md`.

**Architecture:** Все изменения в одном файле `publisher_tiktok.py` (3 секции: helpers + module-level `_tt_infer_post_publish_success` + `publish_tiktok` upload-confirmation loop). 3 feature flag'а, default false → pure no-op rollout. TDD на каждый детектор.

**Tech Stack:** Python 3.x, pytest, xml.etree.ElementTree, ADB shell. Code repo: GenGo2/delivery-contenthunter (testbench checkout: `/home/claude-user/autowarm-testbench/`).

---

## Worktree path

**Canonical path (use everywhere — Codex v1 round 1, P1#1 fix):**
```
WORKTREE=/home/claude-user/autowarm-testbench-feat-tt-mr-cov-20260511
```
Все file paths и команды ниже относятся к этому worktree, не к базовому `/home/claude-user/autowarm-testbench/`.

## Files Affected

(Anchors over line numbers — Codex v1 round 1, P3#3: line numbers stale-prone после merge'ей.)

- **Modify:** `$WORKTREE/publisher_tiktok.py`
  - Module-level: `_tt_infer_post_publish_success` (anchor: `def _tt_infer_post_publish_success`) — gate'инг SEED через flag (Task 8)
  - Class `TikTokMixin`:
    - constants block (anchor: `_TT_MUSIC_RIGHTS_CHECKBOX = [`): добавить `_TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS` (Task 1)
    - после `_handle_tt_music_rights_dialog` (anchor: `def _handle_tt_music_rights_dialog`): добавить `_detect_tt_music_rights_dialog_fallback`, `_detect_tt_music_rights_dialog_evidence_only`, `_save_dump_for_fallback_review` (Tasks 2-4)
    - `_handle_tt_music_rights_dialog` (anchor): hybrid + evidence-only + throttle (Task 5)
    - `publish_tiktok` start (anchor: `self._music_rights_iter = 0`): init state vars (Task 6)
    - new helpers `_after_music_rights_handled`, `_maybe_dump_post_music_rights_xml` (anchors below): added для test'абельности RC-B.2/B.4 (Tasks 7, 9)
    - `publish_tiktok` upload-confirmation loop в `if handled:` block (anchor: `handled = self._handle_tt_music_rights_dialog`): вызов `_after_music_rights_handled` (Task 7)
    - `publish_tiktok` upload-confirmation loop после audio-dialog handler (anchor: `# === TikTok: аудио-диалог после публикации ===` end): вызов `_maybe_dump_post_music_rights_xml` (Task 9)
- **Modify:** `$WORKTREE/tests/test_publisher_tt_music_rights.py` (расширяем 22 тестами)

---

## Task 0: Setup worktree + baseline pytest green

**Files:**
- Create worktree: `/home/claude-user/autowarm-testbench-feat-tt-mr-cov-20260511/`

- [ ] **Step 1: Fetch latest main + create worktree**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add /home/claude-user/autowarm-testbench-feat-tt-mr-cov-20260511 -b feat/tt-mr-cov-20260511 origin/main
cd /home/claude-user/autowarm-testbench-feat-tt-mr-cov-20260511
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

Run: `cd /home/claude-user/autowarm-testbench-feat-tt-mr-cov-20260511 && python3 -c "from publisher_tiktok import TikTokMixin; print(TikTokMixin._TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS)"`
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

def test_save_dump_for_fallback_review_writes_file_into_redirected_dir(tmp_path, monkeypatch):
    """Dump-helper writes XML into target dir с ms-timestamp + uuid8 suffix
    в filename. Real implementation called (not monkeypatched) — Codex v1
    round 1, P2#1: validate behavior, не сам метод заменять."""
    m = TikTokMixin()
    m.task_id = 42

    # Redirect /tmp/autowarm_ui_dumps → tmp_path для изоляции теста.
    target = tmp_path / 'dumps'
    import publisher_tiktok as pt
    original_open = open

    def patched_open(path, *a, **kw):
        # Если код пишет в /tmp/autowarm_ui_dumps — redirect to tmp_path
        if isinstance(path, str) and path.startswith('/tmp/autowarm_ui_dumps/'):
            new_path = str(target / path.split('/tmp/autowarm_ui_dumps/')[1])
            return original_open(new_path, *a, **kw)
        return original_open(path, *a, **kw)

    target.mkdir()
    monkeypatch.setattr('builtins.open', patched_open)
    monkeypatch.setattr(pt.os, 'makedirs',
                        lambda p, **kw: target.mkdir(parents=True, exist_ok=True))

    result = m._save_dump_for_fallback_review('<xml>data</xml>', suffix='fallback')
    files = list(target.glob('tt_music_rights_fallback_42_*_*.xml'))
    assert len(files) == 1, f'Expected 1 file, found: {[f.name for f in files]}'
    assert files[0].read_text() == '<xml>data</xml>'
    # Filename содержит ms-timestamp + uuid8
    parts = files[0].name.replace('.xml', '').split('_')
    assert len(parts) >= 6  # tt_music_rights_fallback_42_<ms>_<uuid>
    assert parts[-1].isalnum() and len(parts[-1]) == 8  # uuid suffix
    assert parts[-2].isdigit() and len(parts[-2]) >= 10  # ms-timestamp


def test_save_dump_for_fallback_review_returns_write_failed_on_exception(monkeypatch):
    """Если write бросает — возвращаем 'write_failed', не raise."""
    m = TikTokMixin()
    m.task_id = 1
    import publisher_tiktok as pt

    def broken_open(*a, **kw):
        raise OSError('disk full')
    monkeypatch.setattr('builtins.open', broken_open)
    monkeypatch.setattr(pt.os, 'makedirs', lambda *a, **kw: None)
    result = m._save_dump_for_fallback_review('<xml>x</xml>', suffix='test')
    assert result == 'write_failed'
```

- [ ] **Step 2: Run tests to verify FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py::test_save_dump_for_fallback_review_writes_file_into_redirected_dir tests/test_publisher_tt_music_rights.py::test_save_dump_for_fallback_review_returns_write_failed_on_exception -v`
Expected: FAIL with `AttributeError: 'TikTokMixin' object has no attribute '_save_dump_for_fallback_review'`.

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

Run: `pytest tests/test_publisher_tt_music_rights.py::test_save_dump_for_fallback_review_writes_file_into_redirected_dir tests/test_publisher_tt_music_rights.py::test_save_dump_for_fallback_review_returns_write_failed_on_exception -v`
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
          text="I accept terms"/>
    <node text="Опубликовать видео" clickable="true"
          bounds="[100,1300][980,1400]" class="android.widget.Button"/>
  </node>
</hierarchy>'''
# (Codex v2 round 1, P1: nothing in this XML matches _TT_MUSIC_RIGHTS_FALLBACK_TITLE_SUBSTRINGS —
#  ни 'music rights', ни 'music usage rights', ни 'rights confirmation',
#  ни 'подтверждение прав', ни 'права на использование музыки'.)

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

Run: `pytest tests/test_publisher_tt_music_rights.py -k "detect_fallback" -v 2>&1 | tail -20`
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

Run: `pytest tests/test_publisher_tt_music_rights.py -k "detect_fallback" -v 2>&1 | tail -20`
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
    # Dump fired с suffix='fallback'
    assert any(s == 'fallback' for s, _ in saved_paths)
    # log_event'ы содержат matched_via='fallback' в meta для accepted event
    calls_with_matched_via = [
        c for c in m.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('matched_via') == 'fallback'
    ]
    assert len(calls_with_matched_via) >= 1, (
        'Ожидался хотя бы 1 log_event с meta[\'matched_via\']=\'fallback\'. '
        f'Видим: {[c.kwargs.get(\"meta\", {}).get(\"matched_via\") for c in m.log_event.call_args_list]}'
    )
    # И event с category=tt_music_rights_fallback_match (на fallback-detect)
    categories = [c.kwargs.get('meta', {}).get('category') for c in m.log_event.call_args_list]
    assert 'tt_music_rights_fallback_match' in categories


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

## Task 6: Init state vars + helper `_init_music_rights_state` (RC-B.1)

**Files:**
- Modify: `publisher_tiktok.py` — add helper method + call в `publish_tiktok`
- Test: `tests/test_publisher_tt_music_rights.py`

**Why refactor:** Codex v1 round 1, P2#5 — раньше state-init test вызывал весь `publish_tiktok` с try-except — brittle. Извлекаем init в helper для real unit-теста.

- [ ] **Step 1: Write failing test**

Append:

```python
# ====== v12 RC-B.1: state init helper ======

def test_init_music_rights_state_resets_all_vars():
    """_init_music_rights_state сбрасывает 4 state-переменные."""
    m = TikTokMixin()
    # Симулируем dirty state из предыдущего publish'а
    m._music_rights_iter = 5
    m._music_rights_just_accepted_iter = 42
    m._music_rights_accepted_ts = 1234567890
    m._music_rights_evidence_dumped = True
    # Reset
    m._init_music_rights_state()
    assert m._music_rights_iter == 0
    assert m._music_rights_just_accepted_iter is None
    assert m._music_rights_accepted_ts is None
    assert m._music_rights_evidence_dumped is False


def test_publish_tiktok_calls_init_music_rights_state(monkeypatch):
    """publish_tiktok start вызывает _init_music_rights_state."""
    m = _make_mixin_with_mock_adb()
    called = []
    monkeypatch.setattr(TikTokMixin, '_init_music_rights_state',
                        lambda self: called.append('init'))
    monkeypatch.setattr(m, 'log_event', MagicMock())
    monkeypatch.setattr(m, 'adb', MagicMock(return_value=''))
    monkeypatch.setattr(m, 'dump_ui', MagicMock(return_value=''))
    monkeypatch.setattr(TikTokMixin, 'platform_cfg',
                        {'package': 'com.zhiliaoapp.musically'}, raising=False)
    try:
        m.publish_tiktok('/tmp/fake.mp4')
    except Exception:
        pass  # OK — мы тестим только что helper вызывается в начале
    assert called == ['init'], f'_init_music_rights_state must be called once at start, got: {called}'
```

- [ ] **Step 2: Run tests FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "init_music_rights" -v 2>&1 | tail -10`
Expected: 2 FAIL (AttributeError).

- [ ] **Step 3: Add helper + call в `publish_tiktok`**

В `TikTokMixin` (ANCHOR: после `_save_dump_for_fallback_review`, перед `publish_tiktok`):

```python
    def _init_music_rights_state(self) -> None:
        """v12 RC-B.1: reset all music-rights state в начале publish_tiktok.

        Сбрасывает 4 переменные:
        - _music_rights_iter (counter для MAX_MUSIC_RIGHTS_ITERATIONS cap)
        - _music_rights_just_accepted_iter (флаг post-accept фазы)
        - _music_rights_accepted_ts (timestamp accept'а для diagnostics)
        - _music_rights_evidence_dumped (throttle flag для evidence-only path)
        """
        self._music_rights_iter = 0
        self._music_rights_just_accepted_iter = None
        self._music_rights_accepted_ts = None
        self._music_rights_evidence_dumped = False
```

В `publish_tiktok` (ANCHOR: existing `self._music_rights_iter = 0` line), **replace** the single line with:
```python
        self._init_music_rights_state()
```

- [ ] **Step 4: Run tests PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "init_music_rights" -v 2>&1 | tail -10`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): extract _init_music_rights_state helper + 2 tests (RC-B.1)"
```

---

## Task 7: Helper `_after_music_rights_handled` (RC-B.2)

**Files:**
- Modify: `publisher_tiktok.py` — add helper + call в music-rights branch
- Test: `tests/test_publisher_tt_music_rights.py`

**Why refactor:** Codex v1 round 1, P2#5 — inline-в-loop логику невозможно протестить без полного loop'а. Извлекаем в helper, тестируем напрямую.

- [ ] **Step 1: Write failing test**

Append:

```python
# ====== v12 RC-B.2: post-accept state helper ======

def test_after_music_rights_handled_sets_state_and_resets_counter(monkeypatch):
    """_after_music_rights_handled(wait) sets _music_rights_just_accepted_iter,
    _music_rights_accepted_ts, resets _music_rights_iter."""
    import publisher_tiktok as pt
    monkeypatch.setattr(pt.time, 'time', lambda: 9999.5)
    m = TikTokMixin()
    m._music_rights_iter = 3  # будто было 3 detections
    m._music_rights_just_accepted_iter = None
    m._music_rights_accepted_ts = None
    m._after_music_rights_handled(wait=17)
    assert m._music_rights_just_accepted_iter == 17
    assert m._music_rights_accepted_ts == 9999.5
    assert m._music_rights_iter == 0


def test_publish_tiktok_calls_after_music_rights_handled_on_handled_true():
    """В publish_tiktok после handled=True вызывается _after_music_rights_handled.
    Source-grep — структурная проверка (т.к. полный loop сложно симулировать)."""
    import inspect
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    # Поиск pattern: после `if handled:` вызывается our helper
    # Точная строка: 'self._after_music_rights_handled(wait)'
    assert 'self._after_music_rights_handled(wait)' in src, (
        '_after_music_rights_handled must be called after handled=True'
    )
```

- [ ] **Step 2: Run tests FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "after_music_rights_handled" -v 2>&1 | tail -10`
Expected: 2 FAIL.

- [ ] **Step 3: Add helper + update loop**

В `TikTokMixin` (ANCHOR: после `_init_music_rights_state`):

```python
    def _after_music_rights_handled(self, wait: int) -> None:
        """v12 RC-B.2: post-accept tracking + counter decouple.

        Codex v6 round 1, P1#3: MAX_MUSIC_RIGHTS_ITERATIONS не должен
        preempt'ить post-accept фазу. Counter reset после успешного handle.
        """
        self._music_rights_just_accepted_iter = wait
        self._music_rights_accepted_ts = time.time()
        self._music_rights_iter = 0  # decouple counter from post-accept phase
```

Обновить в `publish_tiktok` (ANCHOR: `handled = self._handle_tt_music_rights_dialog(ui)`), find:
```python
                if handled:
                    time.sleep(2)
                    continue
```

Replace:
```python
                if handled:
                    self._after_music_rights_handled(wait)
                    time.sleep(2)
                    continue
```

- [ ] **Step 4: Run tests PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "after_music_rights_handled" -v 2>&1 | tail -10`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): _after_music_rights_handled helper + 2 tests (RC-B.2)"
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

## Task 9: Helper `_maybe_dump_post_music_rights_xml` + per-iter call (RC-B.4)

**Files:**
- Modify: `publisher_tiktok.py` — add helper method + call в loop (anchor: after audio-dialog handler block end, before UPLOAD_OK substring check)
- Test: `tests/test_publisher_tt_music_rights.py`

**Why refactor:** Codex v1 round 1, P2#6 + P3#2 — раньше Task 9 имел source-grep тест и vague "выберите место". Извлекаем в helper для real unit-теста + точный anchor.

- [ ] **Step 1: Write failing tests**

Append:

```python
# ====== v12 RC-B.4: per-iter dump helper ======

def test_maybe_dump_post_music_rights_xml_flag_off_no_op(monkeypatch, tmp_path):
    """flag=false → helper returns без записи."""
    monkeypatch.setenv('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'false')
    m = TikTokMixin()
    m.task_id = 1
    m.platform = 'TikTok'
    m._music_rights_just_accepted_iter = 5
    m.log_event = MagicMock()
    m.adb = MagicMock(return_value='topResumedActivity=...')

    files_before = set(tmp_path.glob('*'))
    m._maybe_dump_post_music_rights_xml(wait=6, ui='<x/>')
    files_after = set(tmp_path.glob('*'))
    assert files_before == files_after
    m.log_event.assert_not_called()


def test_maybe_dump_post_music_rights_xml_no_accept_state_no_op(monkeypatch):
    """_music_rights_just_accepted_iter=None → helper returns без записи (даже при flag=true)."""
    monkeypatch.setenv('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'true')
    m = TikTokMixin()
    m._music_rights_just_accepted_iter = None
    m.log_event = MagicMock()
    m.adb = MagicMock(return_value='')
    m._maybe_dump_post_music_rights_xml(wait=6, ui='<x/>')
    m.log_event.assert_not_called()


def test_maybe_dump_at_iters_creates_file_and_logs_event(monkeypatch, tmp_path):
    """flag=true + accept state + iters_since in (1,3,5,10,20,40):
    создаёт файл с ms+uuid suffix И log_event с top_activity meta."""
    monkeypatch.setenv('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'true')
    import publisher_tiktok as pt
    # Redirect /tmp/autowarm_ui_dumps → tmp_path
    target = tmp_path / 'dumps'
    target.mkdir()
    original_open = open
    def patched_open(path, *a, **kw):
        if isinstance(path, str) and path.startswith('/tmp/autowarm_ui_dumps/'):
            new_path = str(target / path.split('/tmp/autowarm_ui_dumps/')[1])
            return original_open(new_path, *a, **kw)
        return original_open(path, *a, **kw)
    monkeypatch.setattr('builtins.open', patched_open)
    monkeypatch.setattr(pt.os, 'makedirs',
                        lambda p, **kw: target.mkdir(parents=True, exist_ok=True))

    m = TikTokMixin()
    m.task_id = 99
    m.platform = 'TikTok'
    m._music_rights_just_accepted_iter = 4  # accept на iter 4
    m.log_event = MagicMock()
    m.adb = MagicMock(return_value='topResumedActivity=ActivityRecord{com.zhiliaoapp.musically/.SAASceneWrapperActivity}')

    # wait=5: iters_since = 5-4 = 1 (in dump schedule)
    m._maybe_dump_post_music_rights_xml(wait=5, ui='<hierarchy>dump_iter1</hierarchy>')

    files = list(target.glob('tt_post_music_rights_99_iter1_*_*.xml'))
    assert len(files) == 1, f'Expected 1 dump file, got: {[f.name for f in target.iterdir()]}'
    assert files[0].read_text() == '<hierarchy>dump_iter1</hierarchy>'

    m.log_event.assert_called_once()
    args, kwargs = m.log_event.call_args
    meta = kwargs.get('meta', {})
    assert meta.get('category') == 'tt_post_music_rights_dump'
    assert meta.get('iters_after_accept') == 1
    assert 'SAASceneWrapperActivity' in meta.get('top_activity', '')


def test_maybe_dump_skips_non_schedule_iters(monkeypatch, tmp_path):
    """iters_since=2 (НЕ в schedule 1,3,5,10,20,40) → no dump."""
    monkeypatch.setenv('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'true')
    import publisher_tiktok as pt
    monkeypatch.setattr(pt.os, 'makedirs', lambda *a, **kw: None)

    m = TikTokMixin()
    m.task_id = 1
    m._music_rights_just_accepted_iter = 4
    m.log_event = MagicMock()
    m.adb = MagicMock(return_value='')

    # wait=6: iters_since = 6-4 = 2 (NOT in schedule)
    m._maybe_dump_post_music_rights_xml(wait=6, ui='<x/>')
    m.log_event.assert_not_called()


def test_publish_tiktok_calls_maybe_dump_post_music_rights_xml():
    """publish_tiktok upload-confirmation loop вызывает helper. Source-grep
    как структурный smoke (loop сложно exercise напрямую)."""
    import inspect
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    assert 'self._maybe_dump_post_music_rights_xml(wait, ui)' in src, (
        '_maybe_dump_post_music_rights_xml must be called inside loop'
    )
```

- [ ] **Step 2: Run tests FAIL**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "maybe_dump or test_publish_tiktok_calls_maybe_dump" -v 2>&1 | tail -10`
Expected: 5 FAIL (AttributeError).

- [ ] **Step 3: Add helper method**

В `TikTokMixin` (ANCHOR: после `_after_music_rights_handled`):

```python
    def _maybe_dump_post_music_rights_xml(self, wait: int, ui: str) -> None:
        """v12 RC-B.4: per-iter XML dump после music_rights accept.

        Срабатывает only при:
        - TT_DUMP_POST_MUSIC_RIGHTS_XML=true (env flag, default false)
        - _music_rights_just_accepted_iter is not None (= music_rights ранее accepted)
        - iters_since in (1, 3, 5, 10, 20, 40) (logarithmic schedule)

        Сохраняет ui XML на disk + log_event'ит с top_activity meta для
        SEED-activation evidence (RC-B.0 decision input).
        """
        if os.environ.get('TT_DUMP_POST_MUSIC_RIGHTS_XML', 'false').lower() != 'true':
            return
        if self._music_rights_just_accepted_iter is None:
            return
        iters_since = wait - self._music_rights_just_accepted_iter
        if iters_since not in (1, 3, 5, 10, 20, 40):
            return
        # All side effects внутри try — best-effort instrumentation
        # (Codex v2 round 1, P2: adb() exception раньше escape'ил try)
        try:
            cur_act_dump = self.adb(
                'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
                timeout=8) or ''
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

- [ ] **Step 4: Add helper invocation в loop**

В `publish_tiktok` upload-confirmation loop, **ANCHOR**: find existing block ending audio-dialog handler — последняя строка которого `time.sleep(2); continue` после audio-dialog detect block. Сразу после audio-dialog handler (когда audio-dialog НЕ обнаружен или handled), **в каждой iter перед UPLOAD_OK substring check** (anchor: line that does `matched = [kw for kw in UPLOAD_OK if kw in ui]`), insert:

```python
            # v12 RC-B.4: per-iter XML dump после music_rights accept
            # Spec: docs/superpowers/specs/2026-05-11-tt-music-rights-coverage-and-post-accept-design.md
            self._maybe_dump_post_music_rights_xml(wait, ui)
```

(Helper internally gates на flag + state — если flag off ИЛИ accept не was, no-op.)

- [ ] **Step 5: Run tests PASS**

Run: `pytest tests/test_publisher_tt_music_rights.py -k "maybe_dump or test_publish_tiktok_calls_maybe_dump" -v 2>&1 | tail -10`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_music_rights.py
git commit -m "feat(tt-music-rights): _maybe_dump_post_music_rights_xml helper + 5 tests (RC-B.4)"
```

---

## Task 10: Full test suite verification + manual sanity

**Files:** none

- [ ] **Step 1: Run full music-rights test file**

Run: `pytest tests/test_publisher_tt_music_rights.py -v 2>&1 | tail -30`
Expected: All tests PASS (existing PR #28 baseline + 27 new tests from this plan).

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
cd /home/claude-user/autowarm-testbench-feat-tt-mr-cov-20260511
source ~/secrets/github-gengo2.env
git push -u origin feat/tt-mr-cov-20260511
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

- [x] pytest tests/test_publisher_tt_music_rights.py -v (27 new tests pass)
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
- RC-A.1 (fallback matcher) → Task 3 (6 tests)
- RC-A.1b (evidence-only) → Task 4 (3 tests)
- RC-A.2 (hybrid handler + throttle) → Task 5 (5 tests)
- RC-B.0 (flag-gated SEED) → Task 8 (2 tests)
- RC-B.1 (state init helper) → Task 6 (2 tests)
- RC-B.2 (after_handled helper) → Task 7 (2 tests)
- RC-B.4 (dump helper + invocation) → Task 9 (5 tests)
- Task 2 dump-helper itself → 2 tests
- **Total: 27 new tests** (Codex v1 round 1, P3#1 accounting fixed)

**Не покрыто** (намеренно out-of-scope per v7 scope-cut):
- RC-B.3 streak-gate — отложено до XML evidence

**Refactor decisions:**
- Extracted 3 helpers from inline-в-loop code: `_init_music_rights_state`, `_after_music_rights_handled`, `_maybe_dump_post_music_rights_xml`. Это позволяет real unit-test'ить логику без полного `publish_tiktok` flow (Codex v1 round 1, P2#5/#6: inline тестируется только через source-grep, что слабо).
- Source-grep тесты ОСТАВЛЕНЫ как структурный smoke (2 шт: Task 7 + Task 9) — гарантируют что helper'ы реально вызваны из loop'а. Real behavior verified через helper unit tests.

**Open items for impl:**
- Phone #19 / Pi 9 smoke — see spec Open Questions; defer until impl complete
- Live activation steps (`.env` + pm2) — see spec Rollout section
