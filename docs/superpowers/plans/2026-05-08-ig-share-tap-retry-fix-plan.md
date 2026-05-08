# IG Share tap retry fix (Tier 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect editor-stuck after Share tap (caption_input_text_view + clickable id/share_button still visible) и re-tap до 2 раз; fail-fast с новым error_code `ig_share_tap_no_progress` если retries exhausted. Покрывает Mode B (Share tap no-op) — 23 fails/24h `ig_upload_confirmation_timeout`.

**Architecture:** Pure helper `_is_ig_editor_still_visible(ui_xml)` через regex/etree-парс editor markers. Tier 1 retry block добавляется в `_wait_instagram_upload` ПОСЛЕ существующего iter0 diag block, ПЕРЕД main 30-iter loop. Reuses `iter0_ui_xml` (с явной init `= ''` для clean scope). Outer try/except защищает happy path; inner try/except wraps `_save_debug_artifacts`; `share_no_progress` flag триггерит `return False` ВНЕ try-периметра.

**Tech Stack:** Python 3 (stdlib `xml.etree.ElementTree`, `unittest.mock`), pytest. Repo `autowarm-testbench` (auto-pushed в `GenGo2/delivery-contenthunter`).

**Spec:** `docs/superpowers/specs/2026-05-08-ig-share-tap-retry-fix-design.md`

---

## Task 1: Изоляция — feature branch + worktree

**Files:**
- Create: `/home/claude-user/autowarm-testbench-share-retry/` (worktree)

- [ ] **Step 1: `git fetch`**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git log --oneline origin/main -3
```

Expected: видим последний commit `2443160` (или новее). Diag instrumentation merged.

- [ ] **Step 2: Создать worktree**

```bash
cd /home/claude-user/autowarm-testbench
git worktree add -b feature/ig-share-tap-retry-2026-05-08 \
  /home/claude-user/autowarm-testbench-share-retry origin/main
cd /home/claude-user/autowarm-testbench-share-retry
git status
```

Expected: на новой ветке `feature/ig-share-tap-retry-2026-05-08`, ahead of origin/main by 0, working tree clean.

- [ ] **Step 3: Baseline pytest**

```bash
cd /home/claude-user/autowarm-testbench-share-retry
python3 -m pytest tests/ --tb=short 2>&1 | tail -10
```

Expected: 770 passed, 12 pre-existing failed (identical to prior baseline). Если новые fails — STOP BLOCKED.

---

## Task 2: TDD red — `_is_ig_editor_still_visible` 5 failing tests

**Files:**
- Create: `tests/test_ig_editor_visible_helper.py`

- [ ] **Step 1: Создать test file**

Write to `/home/claude-user/autowarm-testbench-share-retry/tests/test_ig_editor_visible_helper.py`:

```python
"""Unit-тесты для _is_ig_editor_still_visible helper.

Pure-function helper detects IG Reels editor screen via two markers:
  - caption_input_text_view present в XML
  - clickable id/share_button (NOT direct_share_button) node

Used by Tier 1 share retry logic в _wait_instagram_upload для detecting
post-Share editor-stuck condition.

Запуск: cd /home/claude-user/autowarm-testbench && pytest tests/test_ig_editor_visible_helper.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_stub():
    """Минимальный stub DevicePublisher для вызова _is_ig_editor_still_visible."""
    from publisher import DevicePublisher
    return DevicePublisher.__new__(DevicePublisher)


def test_editor_visible_returns_true_for_editor_xml():
    """Editor screen: caption_input_text_view + clickable id/share_button → True."""
    stub = _make_stub()
    xml = (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="My caption text" content-desc="" '
        'resource-id="com.instagram.android:id/caption_input_text_view" '
        'bounds="[100,100][900,200]" clickable="true"/>'
        '<node text="" content-desc="Поделиться" '
        'resource-id="com.instagram.android:id/share_button" '
        'bounds="[563,2025][1035,2149]" clickable="true"/>'
        '</hierarchy>'
    )
    assert stub._is_ig_editor_still_visible(xml) is True


def test_editor_visible_returns_false_when_caption_input_absent():
    """Только share_button без caption_input_text_view → False."""
    stub = _make_stub()
    xml = (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="" content-desc="Поделиться" '
        'resource-id="com.instagram.android:id/share_button" '
        'bounds="[563,2025][1035,2149]" clickable="true"/>'
        '</hierarchy>'
    )
    assert stub._is_ig_editor_still_visible(xml) is False


def test_editor_visible_returns_false_when_share_not_clickable():
    """caption_input_text_view present но id/share_button clickable=false → False."""
    stub = _make_stub()
    xml = (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="caption" content-desc="" '
        'resource-id="com.instagram.android:id/caption_input_text_view" '
        'bounds="[100,100][900,200]" clickable="true"/>'
        '<node text="" content-desc="Поделиться" '
        'resource-id="com.instagram.android:id/share_button" '
        'bounds="[563,2025][1035,2149]" clickable="false"/>'
        '</hierarchy>'
    )
    assert stub._is_ig_editor_still_visible(xml) is False


def test_editor_visible_distinguishes_direct_share_button():
    """caption_input_text_view + clickable direct_share_button (НЕ id/share_button) → False.

    Phase 1.7 evidence: 4098 (post-share success screen) имеет direct_share_button
    clickable но editor markers отсутствуют. Helper должен endswith(':id/share_button')
    точно matchить, не зацепляя `direct_share_button`.
    """
    stub = _make_stub()
    xml = (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="caption" content-desc="" '
        'resource-id="com.instagram.android:id/caption_input_text_view" '
        'bounds="[100,100][900,200]" clickable="true"/>'
        '<node text="" content-desc="Поделиться" '
        'resource-id="com.instagram.android:id/direct_share_button" '
        'bounds="[919,1412][1043,1536]" clickable="true"/>'
        '</hierarchy>'
    )
    assert stub._is_ig_editor_still_visible(xml) is False


def test_editor_visible_handles_empty_and_malformed():
    """xml='' и xml='<not-xml' → False (graceful)."""
    stub = _make_stub()
    assert stub._is_ig_editor_still_visible('') is False
    assert stub._is_ig_editor_still_visible('<not-xml') is False
```

- [ ] **Step 2: Прогон новых тестов — все 5 должны падать**

```bash
cd /home/claude-user/autowarm-testbench-share-retry
python3 -m pytest tests/test_ig_editor_visible_helper.py -v
```

Expected: 5 failed (`AttributeError: 'DevicePublisher' object has no attribute '_is_ig_editor_still_visible'`).

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_ig_editor_visible_helper.py
git commit -m "test(ig-share-retry): _is_ig_editor_still_visible helper tests (red)

5 unit tests за pure helper detecting editor-stuck condition. Tests
fail until helper implemented в Task 3."
```

---

## Task 3: Implement `_is_ig_editor_still_visible` helper

**Files:**
- Modify: `publisher_instagram.py` (add helper near `_collect_share_candidates`)

- [ ] **Step 1: Найти подходящее место**

```bash
cd /home/claude-user/autowarm-testbench-share-retry
grep -n "def _collect_share_candidates\|def _build_ig_editor_timeout_meta" publisher_instagram.py | head
```

Expected: `_collect_share_candidates` около line ~281 (added prior task).

- [ ] **Step 2: Добавить `_is_ig_editor_still_visible` ПОСЛЕ `_collect_share_candidates`**

Insert directly after end of `_collect_share_candidates`:

```python
    def _is_ig_editor_still_visible(self, ui_xml: str) -> bool:
        """True if IG Reels editor markers present: caption_input_text_view +
        clickable id/share_button. Used by Tier 1 share retry logic.

        Editor signature (Phase 1.7 evidence, dump task 4123):
          - caption_input_text_view resource-id present anywhere в XML
          - id/share_button (NOT direct_share_button) clickable=true
        Post-publish screens (4098) lack caption_input field — helper returns False.
        """
        if not ui_xml or 'caption_input_text_view' not in ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        for n in root.iter('node'):
            rid = n.get('resource-id', '')
            if rid.endswith(':id/share_button') and n.get('clickable') == 'true':
                return True
        return False
```

`endswith(':id/share_button')` точно matches `com.instagram.android:id/share_button` без зацепления `direct_share_button`.

- [ ] **Step 3: Прогон helper-тестов — 5 green**

```bash
python3 -m pytest tests/test_ig_editor_visible_helper.py -v
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add publisher_instagram.py
git commit -m "feat(ig-share-retry): add _is_ig_editor_still_visible helper

Pure function detects IG Reels editor screen via dual marker check:
caption_input_text_view present + clickable id/share_button (exact
match via endswith ':id/share_button' to distinguish direct_share_button).
Used by Tier 1 share retry logic.

5/5 tests green."
```

---

## Task 4: TDD red — retry block 2 behavior tests

**Files:**
- Create: `tests/test_publisher_instagram_share_retry.py`

- [ ] **Step 1: Создать test file**

Write to `/home/claude-user/autowarm-testbench-share-retry/tests/test_publisher_instagram_share_retry.py`:

```python
"""Behavior-тесты для Tier 1 share retry block в _wait_instagram_upload.

Phase 1.7 evidence: Share tap может не вызывать IG progression past editor
(Mode B). Retry block detects editor-still-visible через _is_ig_editor_still_visible,
re-taps до 2 раз. Если progress нет — fail-fast с error_code ig_share_tap_no_progress.

Запуск: cd /home/claude-user/autowarm-testbench && pytest tests/test_publisher_instagram_share_retry.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _editor_xml() -> str:
    """7-node editor XML — caption_input_text_view + clickable share_button + filler."""
    return (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="caption text" content-desc="" '
        'resource-id="com.instagram.android:id/caption_input_text_view" '
        'bounds="[100,100][900,200]" clickable="true"/>'
        '<node text="" content-desc="" bounds="[0,200][100,300]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,300][100,400]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,400][100,500]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,500][100,600]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,600][100,700]" clickable="false"/>'
        '<node text="" content-desc="Поделиться" '
        'resource-id="com.instagram.android:id/share_button" '
        'bounds="[563,2025][1035,2149]" clickable="true"/>'
        '</hierarchy>'
    )


def _post_publish_xml() -> str:
    """Post-publish screen — без caption_input, с direct_share_button (не editor)."""
    return (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="Видео Reels от ..." content-desc="" bounds="[100,100][900,200]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,200][100,300]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,300][100,400]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,400][100,500]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,500][100,600]" clickable="false"/>'
        '<node text="" content-desc="" bounds="[0,600][100,700]" clickable="false"/>'
        '<node text="" content-desc="Поделиться" '
        'resource-id="com.instagram.android:id/direct_share_button" '
        'bounds="[919,1412][1043,1536]" clickable="true"/>'
        '</hierarchy>'
    )


def _make_publisher_stub(dump_ui_responses, ui_dump_url='https://s3/test.xml'):
    """Stub DevicePublisher для invoke _wait_instagram_upload.

    dump_ui_responses: list of XML strings, returned in order на successive calls.
    """
    from publisher import DevicePublisher
    stub = DevicePublisher.__new__(DevicePublisher)
    stub.task_id = 9999
    stub.adb_host = '127.0.0.1'
    stub.adb_port = 1234
    stub.device_serial = 'TESTSERIAL'
    stub.platform = 'Instagram'
    stub.account = 'test_user'
    stub._collected_screenshots = []
    stub._collected_ui_dumps = []
    stub.set_step = MagicMock()
    stub.log_event = MagicMock()
    stub._safe_kb_probe = MagicMock()
    stub._save_debug_artifacts = MagicMock()
    stub._save_debug_ui_dump = MagicMock(return_value=ui_dump_url)
    stub._save_debug_screenshot = MagicMock(return_value=None)
    stub.dismiss_location_dialog = MagicMock(return_value=False)
    stub.dismiss_overlay_dialogs = MagicMock(return_value=False)
    stub.tap_element = MagicMock(return_value=True)  # tap reports success (но IG может ignore)
    # adb всегда возвращает stuck activity для timeout path (если retry block НЕ срабатывает)
    stub.adb = MagicMock(return_value='topResumedActivity=...InstagramMainActivity t1...')
    stub.dump_ui = MagicMock(side_effect=dump_ui_responses)
    return stub


def test_share_retry_progresses_after_first_retry():
    """Editor visible на iter0, retry 1 progressed → ig_share_retry event, no error_code.

    dump_ui sequence:
      [editor_xml]      ← iter0 diag dump
      [editor_xml]      ← retry 1: still editor before re-tap
      [post_publish_xml]  ← retry 1: AFTER re-tap, editor gone (но мы не доходим — break by check)
      ... остальные dump для main loop, не важны
    Wait — на самом деле after re-tap mы делаем sleep(2) и идём в next iteration где
    dump_ui снова вызывается ВНАЧАЛЕ retry loop. Trace:
      1. iter0 diag → dump #1 = editor_xml
      2. retry block: _is_editor_still_visible(iter0_xml=editor_xml) → True
      3. retry_n=1: time.sleep(3), dump #2 = editor_xml (ДО re-tap)
         _is_editor_still_visible → True → НЕ progressed
         tap_element → True → log ig_share_retry retry_n=1, sleep(2)
      4. retry_n=2: time.sleep(3), dump #3 = post_publish_xml
         _is_editor_still_visible → False → progressed=True, break
      5. progressed=True → НЕ emit ig_share_tap_no_progress
      6. main loop entered с adb=InstagramMainActivity → eventual timeout (НЕ цель этого теста)

    Post-publish XML на dump #3 имеет direct_share_button которая mocking не-editor.
    Helper test уже verified что direct_share_button doesn't trigger True.

    Asserts:
      - 1 ig_share_retry event с retry_n=1
      - 0 ig_share_tap_no_progress events
    """
    dump_responses = [
        _editor_xml(),       # iter0 diag
        _editor_xml(),       # retry 1 check before re-tap
        _post_publish_xml(), # retry 2 check — progressed
        # для main 30-iter loop dump_ui вызывается каждую итерацию; даём infinite post_publish
        # (timeout will fire eventually; не цель теста)
    ] + [_post_publish_xml()] * 100

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    retry_calls = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_retry'
    ]
    no_progress_calls = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
    ]

    assert len(retry_calls) == 1, f'expected 1 ig_share_retry, got {len(retry_calls)}'
    assert retry_calls[0].kwargs['meta']['retry_n'] == 1
    assert len(no_progress_calls) == 0, f'expected 0 ig_share_tap_no_progress, got {len(no_progress_calls)}'


def test_share_retry_exhausted_emits_no_progress():
    """Editor visible на ВСЕХ checks → 2 retries fire, final check confirms editor →
    ig_share_tap_no_progress emit, return False.

    dump_ui sequence:
      1. iter0 diag → editor_xml
      2. retry 1 check (before re-tap) → editor_xml
      3. retry 2 check (before re-tap) → editor_xml
      4. final check (after retries exhausted) → editor_xml
    Total 4 dump_ui calls before fail-fast return.

    Asserts:
      - 2 ig_share_retry events (retry_n=1, retry_n=2)
      - 1 ig_share_tap_no_progress event
      - return False
    """
    dump_responses = [_editor_xml()] * 10  # always editor

    stub = _make_publisher_stub(dump_ui_responses=dump_responses)

    with patch('time.sleep'):
        result = stub._wait_instagram_upload()

    retry_calls = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_retry'
    ]
    no_progress_calls = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
    ]

    assert result is False
    assert len(retry_calls) == 2, f'expected 2 ig_share_retry, got {len(retry_calls)}'
    assert sorted(c.kwargs['meta']['retry_n'] for c in retry_calls) == [1, 2]
    assert len(no_progress_calls) == 1
    assert no_progress_calls[0].kwargs['meta']['retries_exhausted'] == 2
```

- [ ] **Step 2: Прогон новых тестов — оба должны падать**

```bash
cd /home/claude-user/autowarm-testbench-share-retry
python3 -m pytest tests/test_publisher_instagram_share_retry.py -v
```

Expected: 2 failed (retry block нет, ig_share_retry / ig_share_tap_no_progress events не emit'ятся).

- [ ] **Step 3: Commit**

```bash
git add tests/test_publisher_instagram_share_retry.py
git commit -m "test(ig-share-retry): retry block behavior tests (red)

2 behavior tests с side_effect dump_ui sequences:
- progressed-after-retry-1: editor → editor → post_publish (1 retry fixes)
- exhausted: editor × infinity (2 retries fire + ig_share_tap_no_progress)

Tests fail until retry block implemented в Task 5."
```

---

## Task 5: Implement Tier 1 retry block + iter0 init

**Files:**
- Modify: `publisher_instagram.py` (in `_wait_instagram_upload`)

- [ ] **Step 1: Найти existing iter0 diag block**

```bash
cd /home/claude-user/autowarm-testbench-share-retry
grep -n "Diagnostic instrumentation iter0\|wait_upload_iter0_diag\|published = False" publisher_instagram.py | head
```

Expected: видим `published = False` около line ~1700 и `Diagnostic instrumentation iter0` около line ~1701-1719.

- [ ] **Step 2: Добавить `iter0_ui_xml = ''` init ПЕРЕД iter0 diag block**

В `_wait_instagram_upload`, найти строку `published = False` (line ~1699). После неё, ПЕРЕД `# === Diagnostic instrumentation iter0 ===`, вставить:

```python
        # Init для clean scope downstream (Tier 1 retry block reuses).
        iter0_ui_xml = ''
```

И в самом iter0 diag try block, БЕЗ изменений — `iter0_ui_xml = self.dump_ui()` уже там, просто теперь не shadowed.

- [ ] **Step 3: Добавить Tier 1 retry block ПОСЛЕ iter0 diag block, ПЕРЕД `SUCCESS_KW`**

Найти `except Exception as _diag_e:` около line ~1718-1719 (конец iter0 try-except). После него, ПЕРЕД `# Строгие признаки успеха` или `SUCCESS_KW = [`, вставить:

```python
        # === Tier 1 fix: detect editor-stuck and retry Share ===
        # Phase 1.7 evidence: Share tap can be no-op (timing race / anti-bot / layout shift).
        # Detect via editor markers; re-tap up to 2 times; fail-fast если progress нет.
        share_no_progress = False  # signal вне try/except для unconditional return False
        try:
            if self._is_ig_editor_still_visible(iter0_ui_xml):
                progressed = False
                for retry_n in range(1, 3):  # 2 retries
                    time.sleep(3)
                    retry_ui = self.dump_ui()
                    if not self._is_ig_editor_still_visible(retry_ui):
                        progressed = True
                        break
                    if self.tap_element(retry_ui, ['Поделиться', 'Share', 'Опубликовать'],
                                        exact=False, clickable_only=True):
                        self.log_event('info', f'Instagram: Share re-tap retry {retry_n}',
                                       meta={'category': 'ig_share_retry',
                                             'platform': self.platform,
                                             'retry_n': retry_n})
                        time.sleep(2)
                    else:
                        # tap_element не matched share text НО editor visible
                        # (per check above). НЕ set progressed=True — final check решит:
                        # если editor still visible → fail-fast ig_share_tap_no_progress.
                        log.warning(f'wait_upload retry {retry_n}: tap_element no share match — break to final check')
                        break

                if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
                    self.log_event('error',
                                   'Instagram: Share tap не прогрессировал после retries',
                                   meta={'category': 'ig_share_tap_no_progress',
                                         'platform': self.platform,
                                         'step': 'wait_upload',
                                         'retries_exhausted': 2})
                    try:
                        self._save_debug_artifacts('instagram_share_no_progress')
                    except Exception as _art_e:
                        log.warning(f'_save_debug_artifacts failed: {_art_e}')
                    share_no_progress = True
        except Exception as _retry_e:
            log.warning(f'wait_upload share retry block failed: {_retry_e}')

        if share_no_progress:
            return False
```

- [ ] **Step 4: Прогон retry tests — оба green**

```bash
python3 -m pytest tests/test_publisher_instagram_share_retry.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Прогон other publisher_instagram tests — green**

```bash
python3 -m pytest tests/test_publisher_instagram_wait_upload_diag.py tests/test_ig_*.py -v 2>&1 | tail -10
```

Expected: все green кроме pre-existing `test_reopen_via_home_taps_plus_then_reels_on_success_path` baseline failure.

- [ ] **Step 6: Commit**

```bash
git add publisher_instagram.py
git commit -m "feat(ig-share-retry): Tier 1 retry block в _wait_instagram_upload

Detects editor-still-visible after Share tap (Phase 1.7 Mode B).
Re-taps до 2 раз с 3s/2s delays. Fail-fast если editor unchanged
после retries — emits ig_share_tap_no_progress error_code.

Inner try/except wraps _save_debug_artifacts; share_no_progress flag
signals fail-fast return ВНЕ outer try-периметра (per Codex review).

iter0_ui_xml initialized к '' перед iter0 diag block для clean scope
(replaces locals().get pattern).

2/2 new behavior tests green. Existing IG tests unchanged."
```

---

## Task 6: Final pytest gate

- [ ] **Step 1: Full suite**

```bash
cd /home/claude-user/autowarm-testbench-share-retry
python3 -m pytest tests/ --tb=short 2>&1 | tail -15
```

Expected: ~775 passed (770 baseline + 5 helper + 2 retry + ?), 12 pre-existing failed (same set). Если new failures — STOP BLOCKED.

- [ ] **Step 2: Sanity import**

```bash
python3 -c "from publisher_instagram import InstagramMixin; print('OK helper:', hasattr(InstagramMixin, '_is_ig_editor_still_visible'))"
```

Expected: `OK helper: True`.

---

## Task 7: Push + merge → main + prod deploy

**IMPORTANT — explicit «no force-push» instruction.** Per memory `feedback_subagent_force_push_risk.md`, prior subagent task briefly regressed GitHub main via `--force-with-lease`. **NEVER** use `--force` или `--force-with-lease` on main. Если push rejected — STOP BLOCKED, report.

- [ ] **Step 1: Push feature branch**

```bash
cd /home/claude-user/autowarm-testbench-share-retry
git push -u origin feature/ig-share-tap-retry-2026-05-08
```

Expected: clean push без conflicts.

- [ ] **Step 2: Merge → autowarm-testbench main**

```bash
cd /home/claude-user/autowarm-testbench
git checkout main
git pull --ff-only origin main
git merge --no-ff feature/ig-share-tap-retry-2026-05-08 \
  -m "merge feature/ig-share-tap-retry-2026-05-08 — IG Share retry Tier 1 fix"
git push origin main
```

Expected: merge commit pushed cleanly. Если `git push` rejected — STOP, не использовать force.

- [ ] **Step 3: Cleanup worktree + local branch**

```bash
git worktree remove /home/claude-user/autowarm-testbench-share-retry
git branch -d feature/ig-share-tap-retry-2026-05-08
```

- [ ] **Step 4: Pull в prod**

```bash
cd /root/.openclaw/workspace-genri/autowarm
# CRITICAL — verify on main branch first
git symbolic-ref HEAD
```

Expected: `refs/heads/main`. Если не main — `git checkout main` ПЕРЕД pull.

```bash
git pull --ff-only origin main
git log --oneline -3
```

Expected: видим merge commit на top.

- [ ] **Step 5: PM2 reload + verify cwd**

```bash
sudo -n pm2 reload autowarm
sudo -n pm2 status autowarm | head -3
sudo -n pm2 describe autowarm | grep "exec cwd"
```

Expected: status=online, restart counter +1, exec cwd = `/root/.openclaw/workspace-genri/autowarm`.

---

## Task 8: Live evidence collection

- [ ] **Step 1: Schedule wakeup ~6h after deploy**

После deploy подождать ~6 часов для accumulation events. IG batch volume 23 fails/24h — за 6h ожидаем 5-7 fail tasks с retry block exercised.

- [ ] **Step 2: SQL — distribution `ig_share_retry` vs `ig_share_tap_no_progress`**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT 
  COUNT(*) FILTER (WHERE e->'meta'->>'category' = 'ig_share_retry') AS retry_events,
  COUNT(DISTINCT pt.id) FILTER (WHERE e->'meta'->>'category' = 'ig_share_retry') AS retry_tasks,
  COUNT(*) FILTER (WHERE e->'meta'->>'category' = 'ig_share_tap_no_progress') AS no_progress_tasks,
  COUNT(*) FILTER (WHERE pt.error_code = 'ig_upload_confirmation_timeout') AS still_generic_timeout,
  COUNT(*) FILTER (WHERE pt.status = 'done') AS done
FROM publish_tasks pt LEFT JOIN jsonb_array_elements(pt.events::jsonb) e ON true
WHERE pt.platform='Instagram' AND pt.started_at > '<DEPLOY_TS>'::timestamp;
"
```

(Replace `<DEPLOY_TS>` with actual deploy timestamp from Task 7 Step 4 git log.)

Expected outcomes:

- **Retry recovers Mode B (B.1 race / B.3 layout):** retry_tasks > 0 AND no_progress_tasks LOW → fix effective, residual issue limited.
- **Retry doesn't fix (B.2 anti-bot):** retry_tasks ≥ no_progress_tasks AND `ig_share_tap_no_progress` rate close to old `ig_upload_confirmation_timeout` rate → Tier 2 needed (alternative tap method).
- **Mixed:** обе категории non-zero — partial success, residual rate определяет priority Tier 2.

- [ ] **Step 3: Записать findings**

Create `/home/claude-user/contenthunter/docs/evidence/2026-05-08-ig-share-retry-deploy.md`:

```markdown
# IG Share retry Tier 1 — deploy + post-deploy evidence

**Дата:** 2026-05-08
**Deploy commit:** <MERGE_SHA>
**Deploy timestamp:** <DEPLOY_TS>

## Pre-deploy baseline (24h)
- `ig_upload_confirmation_timeout`: ~15-23 fails/24h
- Mode B confirmed (Phase 1.7)

## Post-deploy distribution (6h после deploy)
- `ig_share_retry` events fired: <N>
- `ig_share_retry` tasks affected: <M>
- `ig_share_tap_no_progress` tasks (retries exhausted): <K>
- Generic `ig_upload_confirmation_timeout` (без retry triggered, e.g. iter0 diag failed): <L>
- IG done: <D>

## Conclusion
[On-the-spot interpretation: B.1 racing dominant / B.2 anti-bot dominant / mixed]

## Next steps
[Tier 2 design if needed / observation if rate acceptable]
```

Replace `<MERGE_SHA>`, `<DEPLOY_TS>`, `<N>`, `<M>`, `<K>`, `<L>`, `<D>` with actual values.

- [ ] **Step 4: Commit evidence**

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/2026-05-08-ig-share-retry-deploy.md
git commit -m "docs(evidence): IG share retry Tier 1 — deploy + post-fix metrics"
```

---

## Self-review checklist

1. **Spec coverage:**
   - ✅ Spec Section 2.1 (recommended approach) → Task 5 retry block.
   - ✅ Section 3.1 pure helper → Tasks 2-3.
   - ✅ Section 3.2 retry block → Task 5.
   - ✅ Section 3.3 order of operations (iter0_ui_xml init + retry block placement) → Task 5 Steps 2-3.
   - ✅ Section 4 edge cases #1-8 → tests in Task 4 + retry block logic в Task 5.
   - ✅ Section 5.1 5 helper tests → Task 2.
   - ✅ Section 5.2 2 behavior tests → Task 4.
   - ✅ Section 7 R1-R6 risks — все addressed в коде (try/except periphery + inner artifact wrap + flag-pattern).
   - ✅ Section 8 DoD → Tasks 6-8.

2. **Placeholder scan:** все exact paths, complete code blocks. `<DEPLOY_TS>` / `<MERGE_SHA>` etc в Task 8 — runtime placeholders заполняются из live state.

3. **Type consistency:**
   - `_is_ig_editor_still_visible(self, ui_xml: str) -> bool` ✅
   - `iter0_ui_xml` (str) ✅
   - `share_no_progress` (bool) ✅
   - log_event meta keys: `category`, `platform`, `retry_n` (для ig_share_retry); `category`, `platform`, `step`, `retries_exhausted` (для ig_share_tap_no_progress) ✅

4. **Branch isolation:** Task 1 worktree в `/home/claude-user/autowarm-testbench-share-retry/`. Task 7 explicit "no force-push" instruction per memory `feedback_subagent_force_push_risk`.
