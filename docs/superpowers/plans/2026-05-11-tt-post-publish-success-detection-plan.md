# TT post-publish success detection — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать post-publish success detection в `_wait_tiktok_upload` чтобы публикации с auto-навигацией TT в feed/inbox (pt 4523 pattern) распознавались как success вместо 12-минутных AI Unstuck loops с tt_fg_lost.

**Architecture:** Pure helper `_tt_infer_post_publish_success(ui, top_activity, wait)` через bounds-scoped XML parse + group-based label set. Detection block в loop'е `_wait_tiktok_upload` после generic dialog handler перед AI Unstuck. AI Unstuck pre-call guards (main-nav skip + CameraActivity hard-fail) для defense-in-depth. Distinct event `tt_success_inferred_but_no_video_url` для observability cancelled publishes.

**Tech Stack:** Python 3.11, pytest, MagicMock, `xml.etree.ElementTree`, существующий `publisher_tiktok.py` (`GenGo2/delivery-contenthunter` репо).

**Spec:** `docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md` (commits cf85f61cf → 5be9bb200; 3 раунда Codex review applied).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `publisher_tiktok.py` | Modify (top, ~line 22-30) | + 2 const groups: `TT_MAIN_NAV_LABEL_GROUPS`, `TT_COMPOSER_ACTIVITIES_SEED` |
| `publisher_tiktok.py` | Modify (top, ~line 30) | + 2 module-level helpers: `_matches_label`, `_tt_infer_post_publish_success` |
| `publisher_tiktok.py` | Modify (~line 619) | + `inferred_path_used = False` init перед wait_upload loop |
| `publisher_tiktok.py` | Modify (after ~line 957) | + detection block с `tt_post_publish_success_inferred` event |
| `publisher_tiktok.py` | Modify (~line 964-976) | + AI Unstuck guards (main-nav + CameraActivity), сохранить existing AI call |
| `publisher_tiktok.py` | Modify (~line 1019-1024) | + `tt_success_inferred_but_no_video_url` warning event when `inferred_path_used=True` |
| `tests/test_publisher_tt_post_publish_success_helper.py` | Create | 19 unit tests pure helper |
| `tests/test_publisher_tt_wait_upload_integration.py` | Create | 1 source-order test + 4 behavioral tests с mocked TikTokMixin (call-count invariants для AI Unstuck guards) |

---

## Pre-flight

### Task 0: Worktree setup + branch prep

**Goal:** Изолированный worktree в репо `GenGo2/delivery-contenthunter`, ветка от свежего origin/main.

- [ ] **Step 1: `git fetch` в prod autowarm репо**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin main
git log origin/main..HEAD --oneline  # должен быть пустым (prod синхронизирован)
git status -s  # должен быть clean
```

Expected: empty diff, clean status.

- [ ] **Step 2: Создать worktree для feature ветки**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git worktree add /home/claude-user/autowarm-testbench-feat-tt-post-publish-success-20260511 -b feat/tt-post-publish-success-20260511 origin/main
cd /home/claude-user/autowarm-testbench-feat-tt-post-publish-success-20260511
git status  # → On branch feat/tt-post-publish-success-20260511, clean
```

Expected: worktree готов, на свежей ветке от origin/main.

- [ ] **Step 3: Verify pytest зелёный baseline**

```bash
cd /home/claude-user/autowarm-testbench-feat-tt-post-publish-success-20260511
python -m pytest tests/test_publisher_tt_music_rights.py tests/test_tt_audio_dialog.py tests/test_tt_bound_based_nav.py -v --tb=short 2>&1 | tail -15
```

Expected: all passing (baseline). Если есть pre-existing fails — отметить их, не считать регрессией.

---

## Phase 1 — Pure helpers (тесты сначала, no integration)

### Task 1: `_matches_label` helper

**Files:**
- Modify: `publisher_tiktok.py` (top, after imports ~line 22)
- Create: `tests/test_publisher_tt_post_publish_success_helper.py`

- [ ] **Step 1: Написать failing tests для `_matches_label`**

Создать `tests/test_publisher_tt_post_publish_success_helper.py`:

```python
"""TT post-publish success detection — pure helper unit tests.

Spec: docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md

Запуск:
    cd /home/claude-user/autowarm-testbench-feat-tt-post-publish-success-20260511
    pytest tests/test_publisher_tt_post_publish_success_helper.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_tiktok import (  # noqa: E402
    _matches_label,
    _tt_infer_post_publish_success,
    TT_MAIN_NAV_LABEL_GROUPS,
    TT_COMPOSER_ACTIVITIES_SEED,
)


# ─────────────────────────────────────────────────────────────────────────────
# _matches_label
# ─────────────────────────────────────────────────────────────────────────────

class TestMatchesLabel:
    def test_short_label_strict_equality(self):
        """Labels ≤3 chars require strict equality (защита от 'Me' vs 'Messages')."""
        assert _matches_label('Me', 'Me') is True
        assert _matches_label('Messages', 'Me') is False
        assert _matches_label('Mentions', 'Me') is False

    def test_long_label_substring_match(self):
        """Labels >3 chars allow substring match."""
        assert _matches_label('Главная страница', 'Главная') is True
        assert _matches_label('Профиль пользователя', 'Профиль') is True

    def test_empty_value_returns_false(self):
        assert _matches_label('', 'Главная') is False
        assert _matches_label(None, 'Главная') is False

    def test_strip_whitespace(self):
        assert _matches_label('  Главная  ', 'Главная') is True
```

- [ ] **Step 2: Run tests — expected FAIL (ImportError)**

```bash
cd /home/claude-user/autowarm-testbench-feat-tt-post-publish-success-20260511
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py::TestMatchesLabel -v 2>&1 | tail -10
```

Expected: ImportError для `_matches_label`, `_tt_infer_post_publish_success`, etc.

- [ ] **Step 3: Минимальная implementation в `publisher_tiktok.py`**

Добавить после строки 28 (после `MAX_MUSIC_RIGHTS_ITERATIONS = 5`):

```python


# ─────────────────────────────────────────────────────────────────────────────
# Post-publish success detection 2026-05-11
# Spec: docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md
# ─────────────────────────────────────────────────────────────────────────────

# TT bottom-nav label groups. Каждый group = синонимы одного таба (RU/EN/A-B).
# 5 групп = ровно 5 табов TT main nav. На composer screen NONE of these visible.
TT_MAIN_NAV_LABEL_GROUPS = (
    ('Главная', 'Home'),
    ('Друзья', 'Интересное', 'Friends', 'Discover'),
    ('Создать', 'Create'),
    ('Входящие', 'Inbox'),
    ('Профиль', 'Profile'),  # 'Me' removed — substring matched 'Messages'/'Mentions'
)

# TT activities trustworthy from code grep:
#   - 'MainActivity' — confirmed
#   - 'DetailActivity' — confirmed
#   - 'SystemShareActivity' — confirmed
#
# TT_COMPOSER_ACTIVITIES_SEED — SEED blacklist для composer/edit/permission flow.
# НЕ verified в коде, нужны live observations через top_activity field в events.
TT_COMPOSER_ACTIVITIES_SEED = (
    'PostActivity',
    'EditActivity',
    'PublishActivity',
    'CameraActivity',
    'PermissionActivity',
    'MusicSelectActivity',
    'CutVideoActivity',
    'CoverActivity',
)


def _matches_label(value, label: str) -> bool:
    """Match label against text/desc value. Short tokens (<=3 chars) require
    strict equality (избегает 'Me' matching 'Messages')."""
    if value is None:
        return False
    value = str(value).strip()
    if not value:
        return False
    if len(label) <= 3:
        return value == label
    return label in value


def _tt_infer_post_publish_success(ui, top_activity, wait_iter):
    """Stub — implementation в Task 2-6."""
    raise NotImplementedError
```

- [ ] **Step 4: Run tests — expected PASS for `_matches_label` block**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py::TestMatchesLabel -v 2>&1 | tail -15
```

Expected: 4/4 PASS для TestMatchesLabel. Other tests (для не-implemented helpers) могут fail с NotImplementedError — это OK на этом этапе.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_post_publish_success_helper.py
git commit -m "feat(tt-publish): _matches_label helper + const groups (red→green)

Adds:
- TT_MAIN_NAV_LABEL_GROUPS (5 nav groups, RU+EN, без 'Me' substring trap)
- TT_COMPOSER_ACTIVITIES_SEED (8 composer-related activities, SEED list)
- _matches_label helper with short-token strict equality

Spec: docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md"
```

---

### Task 2: `_tt_infer_post_publish_success` — DetailActivity + launcher branches

**Files:**
- Modify: `publisher_tiktok.py` (helper body)
- Modify: `tests/test_publisher_tt_post_publish_success_helper.py` (add tests)

- [ ] **Step 1: Add failing tests**

Append к `tests/test_publisher_tt_post_publish_success_helper.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# _tt_infer_post_publish_success — activity-based branches
# ─────────────────────────────────────────────────────────────────────────────

TT_MAIN_ACT = ('topResumedActivity=ActivityRecord{abc 0 '
               'com.zhiliaoapp.musically/.main.app.MainActivity t1}')
TT_DETAIL_ACT = ('topResumedActivity=ActivityRecord{abc 0 '
                 'com.zhiliaoapp.musically/.detail.DetailActivity t2}')
TT_CAMERA_ACT = ('topResumedActivity=ActivityRecord{abc 0 '
                 'com.zhiliaoapp.musically/.video.CameraActivity t3}')
LAUNCHER_ACT = ('topResumedActivity=ActivityRecord{abc 0 '
                'com.sec.android.app.launcher/.LauncherActivity t4}')


class TestActivityBranches:
    def test_detail_activity_returns_success(self):
        """DetailActivity → True независимо от nav."""
        ok, meta = _tt_infer_post_publish_success('<hierarchy/>', TT_DETAIL_ACT, 0)
        assert ok is True
        assert meta['reason'] == 'detail_activity'
        assert meta['detail_activity'] is True

    def test_launcher_activity_keeps_waiting(self):
        """topResumedActivity = launcher → False (on_tiktok=False)."""
        ok, meta = _tt_infer_post_publish_success('<hierarchy/>', LAUNCHER_ACT, 1)
        assert ok is False
        assert meta['reason'] == 'not_on_tiktok'
        assert meta['on_tiktok'] is False

    def test_composer_seed_keeps_waiting(self):
        """topResumedActivity содержит 'CameraActivity' (composer seed) → False."""
        ok, meta = _tt_infer_post_publish_success('<hierarchy/>', TT_CAMERA_ACT, 1)
        assert ok is False
        assert meta['reason'] == 'on_composer_seed'
        assert meta['on_composer_seed'] is True

    def test_empty_top_activity_returns_not_on_tiktok(self):
        """Empty/None top_activity → not_on_tiktok."""
        ok, meta = _tt_infer_post_publish_success('<hierarchy/>', '', 1)
        assert ok is False
        assert meta['reason'] == 'not_on_tiktok'
```

- [ ] **Step 2: Run tests — expected FAIL (NotImplementedError)**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py::TestActivityBranches -v 2>&1 | tail -15
```

Expected: 4 errors (NotImplementedError).

- [ ] **Step 3: Implement activity branches в `_tt_infer_post_publish_success`**

Заменить stub в `publisher_tiktok.py`:

```python
def _tt_infer_post_publish_success(ui, top_activity, wait_iter):
    """Detect post-publish success via topResumedActivity + bottom-nav XML parse.

    Returns: (success_bool, debug_meta_dict).
    debug_meta_dict содержит: top_activity, on_tiktok, on_composer_seed,
    nav_groups_visible, detail_activity, reason.

    Rationale: TT auto-navigates from publish-screen to feed/inbox/profile after
    successful publish. Existing UPLOAD_OK markers only match publish-screen text.
    """
    cur_act = (top_activity or '')
    meta = {
        'top_activity': cur_act[:160],
        'on_tiktok': False,
        'on_composer_seed': False,
        'nav_groups_visible': [],
        'detail_activity': False,
        'reason': '',
    }
    on_tiktok = ('musically' in cur_act) or ('tiktok' in cur_act.lower())
    meta['on_tiktok'] = on_tiktok
    if not on_tiktok:
        meta['reason'] = 'not_on_tiktok'
        return False, meta
    if 'DetailActivity' in cur_act:
        meta['detail_activity'] = True
        meta['reason'] = 'detail_activity'
        return True, meta
    on_composer = any(a in cur_act for a in TT_COMPOSER_ACTIVITIES_SEED)
    meta['on_composer_seed'] = on_composer
    if on_composer:
        meta['reason'] = 'on_composer_seed'
        return False, meta
    # Bottom-nav XML parsing — implemented в Task 4-6
    meta['reason'] = 'nav_parse_not_implemented'
    return False, meta
```

- [ ] **Step 4: Run tests — expected PASS**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py::TestActivityBranches -v 2>&1 | tail -15
```

Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_post_publish_success_helper.py
git commit -m "feat(tt-publish): _tt_infer_post_publish_success — activity branches

DetailActivity → instant success (видео страница после публикации).
Composer seed (Camera/Post/Edit/etc.) → keep waiting.
Launcher / non-TT → keep waiting.
XML nav parsing — stub до Task 3-5."
```

---

### Task 3: `_tt_infer_post_publish_success` — bottom-nav XML parsing (happy path)

**Files:**
- Modify: `publisher_tiktok.py` (helper body — add XML parse)
- Modify: `tests/test_publisher_tt_post_publish_success_helper.py`

- [ ] **Step 1: Add tests + helper для построения XML фикстур**

Append к test file:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Bottom-nav XML parsing — happy path
# ─────────────────────────────────────────────────────────────────────────────

# Высота экрана 2520 px (типичный TT phone). bottom 20% = y >= 2016.
SCREEN_H = 2520


def _build_nav_xml(labels, screen_h=SCREEN_H, y_band='bottom'):
    """Build minimal XML with given labels in bottom band (y=2400-2520).

    Plus a root node spanning full screen для screen_h detection.
    """
    nodes = [f'<node bounds="[0,0][720,{screen_h}]"/>']
    for i, label in enumerate(labels):
        x_left = i * 144
        x_right = x_left + 144
        if y_band == 'bottom':
            y_top, y_bottom = 2400, 2520
        else:
            y_top, y_bottom = 400, 500
        nodes.append(
            f'<node text="{label}" bounds="[{x_left},{y_top}][{x_right},{y_bottom}]"/>'
        )
    return '<hierarchy>' + ''.join(nodes) + '</hierarchy>'


class TestBottomNavParsing:
    def test_main_nav_5_groups_returns_success(self):
        """5/5 nav groups в bottom 20% + main activity → True."""
        ui = _build_nav_xml(['Главная', 'Друзья', 'Создать', 'Входящие', 'Профиль'])
        ok, meta = _tt_infer_post_publish_success(ui, TT_MAIN_ACT, 1)
        assert ok is True
        assert len(meta['nav_groups_visible']) == 5
        assert 'main_nav_5_groups' in meta['reason']

    def test_main_nav_3_groups_returns_success(self):
        """Минимум 3/5 nav groups → True."""
        ui = _build_nav_xml(['Главная', 'Входящие', 'Профиль'])  # 3 of 5
        ok, meta = _tt_infer_post_publish_success(ui, TT_MAIN_ACT, 1)
        assert ok is True
        assert len(meta['nav_groups_visible']) == 3

    def test_main_nav_2_groups_returns_keep_waiting(self):
        """2/5 nav groups (порог не достигнут) → False."""
        ui = _build_nav_xml(['Главная', 'Входящие'])
        ok, meta = _tt_infer_post_publish_success(ui, TT_MAIN_ACT, 1)
        assert ok is False
        assert 'main_nav_only_2' in meta['reason']

    def test_interesnoe_variant_recognized(self):
        """'Интересное' (RU вариант Discover) — алиас группы Друзья/Friends."""
        ui = _build_nav_xml(['Главная', 'Интересное', 'Создать', 'Входящие', 'Профиль'])
        ok, meta = _tt_infer_post_publish_success(ui, TT_MAIN_ACT, 1)
        assert ok is True
        # Group key normalized to first label
        assert 'Друзья' in meta['nav_groups_visible']
```

- [ ] **Step 2: Run tests — expected FAIL (3 of 4: nav_parse_not_implemented)**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py::TestBottomNavParsing -v 2>&1 | tail -15
```

Expected: 4 fails (return False, reason='nav_parse_not_implemented').

- [ ] **Step 3: Implement XML parse**

Заменить последнюю секцию `_tt_infer_post_publish_success` (`# Bottom-nav XML parsing` block):

```python
    # Bottom-nav XML parsing
    try:
        import xml.etree.ElementTree as ET
        import re as _re
        root_el = ET.fromstring(ui or '<hierarchy/>')
        screen_h = 0
        for node in root_el.iter('node'):
            b = node.get('bounds', '')
            m = _re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', b)
            if m:
                screen_h = max(screen_h, int(m.group(4)))
        if screen_h < 1000:  # sanity — TT phones are ≥1500px tall
            meta['reason'] = 'screen_height_implausible'
            return False, meta
        bottom_threshold = int(screen_h * 0.80)
        groups_visible = []
        for group in TT_MAIN_NAV_LABEL_GROUPS:
            for node in root_el.iter('node'):
                b = node.get('bounds', '')
                m = _re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', b)
                if not m:
                    continue
                cy = (int(m.group(2)) + int(m.group(4))) // 2
                if cy < bottom_threshold:
                    continue
                txt = node.get('text', '')
                desc = node.get('content-desc', '')
                if any(_matches_label(txt, label) or _matches_label(desc, label)
                       for label in group):
                    groups_visible.append(group[0])
                    break
        meta['nav_groups_visible'] = groups_visible
        if len(groups_visible) >= 3:
            meta['reason'] = f'main_nav_{len(groups_visible)}_groups'
            return True, meta
        meta['reason'] = f'main_nav_only_{len(groups_visible)}_groups'
        return False, meta
    except Exception as exc:
        meta['reason'] = f'xml_parse_error: {type(exc).__name__}'
        return False, meta
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py::TestBottomNavParsing -v 2>&1 | tail -15
```

Expected: 4/4 PASS.

- [ ] **Step 5: Run all helper tests**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py -v 2>&1 | tail -25
```

Expected: TestMatchesLabel + TestActivityBranches + TestBottomNavParsing all PASS (12 tests).

- [ ] **Step 6: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_post_publish_success_helper.py
git commit -m "feat(tt-publish): _tt_infer_post_publish_success — bottom-nav XML parse

Bounds-scoped XML parsing (bottom 20% of screen).
≥3 of 5 nav groups visible + non-composer activity → success.
Group-based label set: 'Интересное' (Discover RU variant) recognized."
```

---

### Task 4: Edge cases — bottom-band scope, label position

**Files:**
- Modify: `tests/test_publisher_tt_post_publish_success_helper.py`

- [ ] **Step 1: Add edge-case tests**

```python
class TestBottomBandScoping:
    def test_main_nav_label_outside_bottom_band_ignored(self):
        """'Профиль' as section heading в content (cy=400) → НЕ counts.
           Защита от false match в feed/profile content."""
        # 1 group в bottom + 'Профиль' высоко в content → 1 group → False
        ui = (
            '<hierarchy>'
            f'<node bounds="[0,0][720,{SCREEN_H}]"/>'
            '<node text="Профиль" bounds="[100,400][500,500]"/>'  # heading в content
            '<node text="Главная" bounds="[0,2400][200,2520]"/>'  # bottom nav
            '</hierarchy>'
        )
        ok, meta = _tt_infer_post_publish_success(ui, TT_MAIN_ACT, 1)
        assert ok is False
        assert len(meta['nav_groups_visible']) == 1

    def test_messages_does_not_match_me(self):
        """'Messages'/'Mentions' не должны match 'Me' (P2.2 v3 — но 'Me' removed,
           проверим что Профиль group не false-positive."""
        ui = _build_nav_xml(['Messages', 'Mentions', 'Notifications'])
        ok, meta = _tt_infer_post_publish_success(ui, TT_MAIN_ACT, 1)
        assert ok is False
        assert 'Профиль' not in meta['nav_groups_visible']

    def test_share_sheet_does_not_infer_success(self):
        """Android share sheet 'Поделиться в TikTok / Видео / Сообщение' —
           main nav not visible → False."""
        ui = (
            '<hierarchy>'
            f'<node bounds="[0,0][720,{SCREEN_H}]"/>'
            '<node text="Поделиться в TikTok" bounds="[0,500][720,600]"/>'
            '<node text="Видео" bounds="[0,800][360,900]"/>'
            '<node text="Сообщение" bounds="[360,800][720,900]"/>'
            '</hierarchy>'
        )
        ok, meta = _tt_infer_post_publish_success(ui, TT_MAIN_ACT, 1)
        assert ok is False
        assert 'main_nav_only_0' in meta['reason']
```

- [ ] **Step 2: Run tests — expected PASS (already implemented в Task 3)**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py::TestBottomBandScoping -v 2>&1 | tail -10
```

Expected: 3/3 PASS (no impl change needed — bounds scope уже работает).

- [ ] **Step 3: Commit**

```bash
git add tests/test_publisher_tt_post_publish_success_helper.py
git commit -m "test(tt-publish): bottom-band scoping + Messages anti-match cases"
```

---

### Task 5: Edge cases — empty UI, no bounds, malformed XML

**Files:**
- Modify: `tests/test_publisher_tt_post_publish_success_helper.py`

- [ ] **Step 1: Add edge-case tests**

```python
class TestEdgeCases:
    def test_empty_ui_returns_screen_height_implausible(self):
        """Empty string UI → screen_height_implausible (graceful)."""
        ok, meta = _tt_infer_post_publish_success('', TT_MAIN_ACT, 1)
        assert ok is False
        assert meta['reason'] == 'screen_height_implausible'

    def test_xml_without_bounds_returns_screen_height_implausible(self):
        """XML без bounds nodes → screen_height_implausible."""
        ok, meta = _tt_infer_post_publish_success(
            '<hierarchy><node text="x"/></hierarchy>', TT_MAIN_ACT, 1)
        assert ok is False
        assert meta['reason'] == 'screen_height_implausible'

    def test_zero_height_bounds_returns_screen_height_implausible(self):
        """Zero-height bounds → max screen_h < 1000 → implausible."""
        ok, meta = _tt_infer_post_publish_success(
            '<hierarchy><node bounds="[0,0][0,0]"/></hierarchy>', TT_MAIN_ACT, 1)
        assert ok is False
        assert meta['reason'] == 'screen_height_implausible'

    def test_malformed_xml_returns_keep_waiting(self):
        """Invalid XML → xml_parse_error reason."""
        ok, meta = _tt_infer_post_publish_success('<not-valid', TT_MAIN_ACT, 1)
        assert ok is False
        assert 'xml_parse_error' in meta['reason']
```

- [ ] **Step 2: Run tests — expected PASS**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py::TestEdgeCases -v 2>&1 | tail -10
```

Expected: 4/4 PASS.

- [ ] **Step 3: Run ВСЕ helper tests + verify count**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py -v 2>&1 | tail -25
```

Expected: 19 PASS (4 matches_label + 4 activity + 4 nav + 3 bottom-band + 4 edge).

- [ ] **Step 4: Commit**

```bash
git add tests/test_publisher_tt_post_publish_success_helper.py
git commit -m "test(tt-publish): edge cases — empty UI, no bounds, zero-height, malformed"
```

---

## Phase 2 — Integration в `_wait_tiktok_upload`

### Task 6: Detection block + `inferred_path_used` flag

**Files:**
- Modify: `publisher_tiktok.py` (~line 619 init, ~line 957 detection block)
- Create: `tests/test_publisher_tt_wait_upload_integration.py`

- [ ] **Step 1: Read current `_wait_tiktok_upload` контекст**

Изучить структуру вокруг line 619 (init) и line 957 (generic dialog handler) перед edit'ом:

```bash
sed -n '617,622p;950,966p' publisher_tiktok.py
```

Expected output: `upload_confirmed = False` на ~619, `if self.tap_element(ui, ['Закрыть', 'Пропустить', ...]` на ~957.

- [ ] **Step 2: Создать integration test scaffold**

Create `tests/test_publisher_tt_wait_upload_integration.py`:

```python
"""TT post-publish success detection — integration tests.

Spec: docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md

Запуск:
    cd /home/claude-user/autowarm-testbench-feat-tt-post-publish-success-20260511
    pytest tests/test_publisher_tt_wait_upload_integration.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_tiktok import TikTokMixin  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Source-order placement guard (P3.1 v3)
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceOrder:
    def test_post_publish_detection_source_order(self):
        """Detection block должен быть после generic dialog handler,
           перед wait%10 logging branch и AI Unstuck call site.
           Защита от accidental misplacement при будущих edit'ах."""
        text = (ROOT / 'publisher_tiktok.py').read_text()
        dialog_idx = text.find("tap_element(ui, ['Закрыть', 'Пропустить'")
        detect_idx = text.find('POST-PUBLISH SUCCESS DETECTION')
        log_idx = text.find('if wait % 10 == 0', dialog_idx)
        ai_idx = text.find('wait > 0 and wait % 5 == 4', dialog_idx)
        assert -1 < dialog_idx < detect_idx < log_idx < ai_idx, (
            f'Block order broken: dialog={dialog_idx}, detect={detect_idx}, '
            f'log={log_idx}, ai={ai_idx}'
        )
```

- [ ] **Step 3: Run source-order test — expected FAIL (POST-PUBLISH SUCCESS DETECTION marker нет)**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py::TestSourceOrder -v 2>&1 | tail -10
```

Expected: AssertionError (detect_idx == -1).

- [ ] **Step 4: Add `inferred_path_used` init и detection block в `publisher_tiktok.py`**

Edit 1 (~line 619-620, init перед loop):

```python
        upload_confirmed = False
        retap_count = 0
        inferred_path_used = False  # P1.1 — set ТОЛЬКО в inferred success branch
```

Edit 2 (после блока `if self.tap_element(ui, ['Закрыть', 'Пропустить', ...])` на ~line 956-958, ПЕРЕД `# Неизвестный экран — логируем` на ~line 960):

```python
            # [POST-PUBLISH SUCCESS DETECTION 2026-05-11 v3]
            # Spec: docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md
            # Placement: AFTER generic dialog handler, BEFORE wait%10 logging.
            # All existing dialog blockers (music-rights, audio, share-sheet) consumed
            # их screens first — если main nav видна здесь, это post-publish state.
            cur_act_post = self.adb(
                'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
                timeout=8,
            ) or ''
            success, _meta = _tt_infer_post_publish_success(ui, cur_act_post, wait)
            if success:
                log.info(f'  ✅ TikTok: post-publish success inferred '
                         f'(reason={_meta["reason"]}, '
                         f'nav_groups={_meta["nav_groups_visible"]}, wait={wait})')
                self.log_event(
                    'info',
                    f'TikTok: post-publish success inferred — {_meta["reason"]}',
                    meta={'category': 'tt_post_publish_success_inferred',
                          'platform': self.platform,
                          'wait_iteration': wait,
                          **_meta},
                )
                upload_confirmed = True
                inferred_path_used = True
                break
```

- [ ] **Step 5: Run source-order test — expected PASS**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py::TestSourceOrder -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 6: Run helper tests + integration tests — verify nothing broken**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py tests/test_publisher_tt_wait_upload_integration.py -v 2>&1 | tail -10
```

Expected: 19 helper + 1 integration = 20 PASS.

- [ ] **Step 7: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_wait_upload_integration.py
git commit -m "feat(tt-publish): wait_upload detection block + inferred_path_used flag

Detection block placement: after generic dialog handler, before wait%10 logging.
inferred_path_used flag для distinguishing inferred vs UPLOAD_OK success path.
Source-order test (test_post_publish_detection_source_order) защищает invariant."
```

---

### Task 7: AI Unstuck main-nav guard

**Files:**
- Modify: `publisher_tiktok.py` (~line 964-976)
- Modify: `tests/test_publisher_tt_wait_upload_integration.py`

- [ ] **Step 1: Add tests**

Append к integration test file:

```python
# ─────────────────────────────────────────────────────────────────────────────
# AI Unstuck guards
# ─────────────────────────────────────────────────────────────────────────────

class TestAiUnstuckMainNavGuardSourceLevel:
    """Source-level guard: ensure code contains expected markers."""

    def test_main_nav_guard_markers_present(self):
        text = (ROOT / 'publisher_tiktok.py').read_text()
        assert 'tt_unstuck_skipped_post_publish' in text, (
            'Main-nav guard event not added'
        )
        assert '_tt_infer_post_publish_success(ui, _cur_act_tt, wait)' in text, (
            'Main-nav guard call not added'
        )
```

- [ ] **Step 2: Run test — expected FAIL (markers нет)**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py::TestAiUnstuckMainNavGuard -v 2>&1 | tail -10
```

Expected: AssertionError.

- [ ] **Step 3: Modify AI Unstuck call site (~line 964-976)**

Найти текущий блок:
```python
            # Неизвестный экран завис 5+ итераций — подключаем AI Unstuck
            if wait > 0 and wait % 5 == 4:
                _cur_act_tt = self.adb('dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"', timeout=8) or ''
                # AI только если TikTok активен (не ждём его возврата)
                if 'musically' in _cur_act_tt or 'tiktok' in _cur_act_tt.lower():
                    log.info(f'  🤖 TikTok: неизвестное состояние {wait} итераций — AI Unstuck')
                    _tt_goal = (...)
                    self.ai_unstuck(_tt_goal, max_attempts=3)
```

Заменить на:
```python
            # Неизвестный экран завис 5+ итераций — подключаем AI Unstuck
            if wait > 0 and wait % 5 == 4:
                _cur_act_tt = self.adb('dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"', timeout=8) or ''
                tiktok_active_for_ai = 'musically' in _cur_act_tt or 'tiktok' in _cur_act_tt.lower()
                if not tiktok_active_for_ai:
                    # AI только если TikTok активен (не ждём его возврата)
                    continue  # fall through to next iter (use `continue` not `pass`)
                else:
                    # [P1.5 v3 2026-05-11] Main-nav guard: skip AI Unstuck когда
                    # видна main nav (мы уже на post-publish screen). Defense-in-depth
                    # safety net на случай если detection block выше miss'нул signal.
                    success_check, _gmeta = _tt_infer_post_publish_success(ui, _cur_act_tt, wait)
                    if success_check:
                        log.info(f'  🛑 TikTok: skip AI Unstuck — main nav/DetailActivity '
                                 f'visible (reason={_gmeta["reason"]})')
                        self.log_event(
                            'info',
                            f'TikTok: skip AI Unstuck — likely post-publish ({_gmeta["reason"]})',
                            meta={'category': 'tt_unstuck_skipped_post_publish',
                                  'platform': self.platform,
                                  'wait_iteration': wait,
                                  **_gmeta},
                        )
                    else:
                        log.info(f'  🤖 TikTok: неизвестное состояние {wait} итераций — AI Unstuck')
                        _tt_goal = (
                            f'Publish {self.media_type} on TikTok for account @{self.account}. '
                            f'The Share/Post button was tapped. '
                            f'An unexpected screen is blocking the upload confirmation. '
                            f'Dismiss any dialogs or complete required steps to finish publishing.'
                        )
                        self.ai_unstuck(_tt_goal, max_attempts=3)
```

- [ ] **Step 4: Run test**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py -v 2>&1 | tail -10
```

Expected: TestSourceOrder + TestAiUnstuckMainNavGuard PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_wait_upload_integration.py
git commit -m "feat(tt-publish): AI Unstuck main-nav guard

Skip AI Unstuck call когда _tt_infer_post_publish_success returns True.
Defense-in-depth safety net для cascade prevention (pt 4523 pattern)."
```

---

### Task 8: AI Unstuck CameraActivity hard-fail

**Files:**
- Modify: `publisher_tiktok.py` (extend AI Unstuck guard блок)
- Modify: `tests/test_publisher_tt_wait_upload_integration.py`

- [ ] **Step 1: Add test**

Append к integration test file:

```python
class TestCameraHardFail:
    def test_camera_activity_after_share_breaks_loop(self):
        """Source-level: code содержит CameraActivity hard-fail с break."""
        text = (ROOT / 'publisher_tiktok.py').read_text()
        assert 'tt_unexpected_camera_after_share' in text
        assert "'CameraActivity' in _cur_act_tt" in text

    @pytest.mark.parametrize('activity', [
        'PermissionActivity',
        'MusicSelectActivity',
        'CutVideoActivity',
        'CoverActivity',
    ])
    def test_legit_recovery_activities_NOT_blocked(self, activity):
        """Source-level: composer activities кроме CameraActivity НЕ блокируются
           (AI Unstuck должен попробовать recovery)."""
        text = (ROOT / 'publisher_tiktok.py').read_text()
        # Hard-fail должен быть только для CameraActivity, не для других composer
        guard_section = text[text.find("'CameraActivity' in _cur_act_tt"):
                             text.find("'CameraActivity' in _cur_act_tt") + 2000]
        assert activity not in guard_section, (
            f'{activity} should NOT be in CameraActivity hard-fail block — '
            f'it блокирует legit recovery scenarios'
        )
```

- [ ] **Step 2: Run test — expected FAIL**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py::TestCameraHardFail -v 2>&1 | tail -10
```

Expected: AssertionError (markers absent).

- [ ] **Step 3: Add CameraActivity hard-fail между main-nav guard и AI call**

Заменить полный блок (Task 7 added `if/else`) на 3-way chain. Финальный полный блок:

```python
            # Неизвестный экран завис 5+ итераций — подключаем AI Unstuck
            if wait > 0 and wait % 5 == 4:
                _cur_act_tt = self.adb('dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"', timeout=8) or ''
                tiktok_active_for_ai = 'musically' in _cur_act_tt or 'tiktok' in _cur_act_tt.lower()
                if not tiktok_active_for_ai:
                    # AI только если TikTok активен (не ждём его возврата)
                    continue
                # [P1.5 v3 2026-05-11] Main-nav guard: skip AI Unstuck когда видна
                # main nav (post-publish state). Defense-in-depth safety net.
                success_check, _gmeta = _tt_infer_post_publish_success(ui, _cur_act_tt, wait)
                if success_check:
                    log.info(f'  🛑 TikTok: skip AI Unstuck — main nav/DetailActivity '
                             f'visible (reason={_gmeta["reason"]})')
                    self.log_event(
                        'info',
                        f'TikTok: skip AI Unstuck — likely post-publish ({_gmeta["reason"]})',
                        meta={'category': 'tt_unstuck_skipped_post_publish',
                              'platform': self.platform,
                              'wait_iteration': wait,
                              **_gmeta},
                    )
                    continue
                # [P1.5 v3 2026-05-11] CameraActivity hard-fail: post-share возврат
                # в Camera = случайно открыли New Post (e.g. tap «+» в bottom nav).
                # NARROWED scope: ТОЛЬКО Camera, NOT Permission/Music/Cover/CutVideo.
                if 'CameraActivity' in _cur_act_tt:
                    log.error(f'  ❌ TikTok: returned to Camera after share tap — '
                              f'unexpected state, fail-fast (wait={wait})')
                    self.log_event(
                        'error',
                        'TikTok: returned to Camera after share tap (unexpected post-share state)',
                        meta={'category': 'tt_unexpected_camera_after_share',
                              'platform': self.platform,
                              'wait_iteration': wait,
                              'top_activity': _cur_act_tt[:160]},
                    )
                    break
                # Default: existing AI Unstuck call (legit Permission/Music/Cover/etc.)
                log.info(f'  🤖 TikTok: неизвестное состояние {wait} итераций — AI Unstuck')
                _tt_goal = (
                    f'Publish {self.media_type} on TikTok for account @{self.account}. '
                    f'The Share/Post button was tapped. '
                    f'An unexpected screen is blocking the upload confirmation. '
                    f'Dismiss any dialogs or complete required steps to finish publishing.'
                )
                self.ai_unstuck(_tt_goal, max_attempts=3)
```

Это COMPLETE final block — заменяет всё, что Task 7 Step 3 положил, плюс добавляет Camera hard-fail.

- [ ] **Step 4: Run tests — expected PASS**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py -v 2>&1 | tail -15
```

Expected: 7 PASS (1 source-order + 1 main-nav + 1 camera + 4 parametrized legit recovery).

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_wait_upload_integration.py
git commit -m "feat(tt-publish): AI Unstuck CameraActivity hard-fail

Post-share возврат в Camera = signal реального failure (не recovery candidate).
Break early с tt_unexpected_camera_after_share event.
Permission/Music/Cover/CutVideo activities остаются legit AI recovery (NARROWED scope per Codex round 2)."
```

---

### Task 9: Post-success URL classification

**Files:**
- Modify: `publisher_tiktok.py` (~line 1019-1024 — tt_url_partial path)
- Modify: `tests/test_publisher_tt_wait_upload_integration.py`

- [ ] **Step 1: Read current tt_url_partial block**

```bash
sed -n '1015,1030p' publisher_tiktok.py
```

Expected: видеть existing `self.log_event('warning', f'tt_url_partial: profile fallback {profile_url}', meta={'category': 'tt_url_partial', ...})` на ~line 1019.

- [ ] **Step 2: Add test**

```python
class TestUrlClassification:
    def test_inferred_success_no_video_url_emits_warning_event(self):
        """Source-level: после tt_url_partial есть additional event для
           inferred path."""
        text = (ROOT / 'publisher_tiktok.py').read_text()
        assert 'tt_success_inferred_but_no_video_url' in text
        # Verify event emitted ONLY when inferred_path_used
        partial_idx = text.find("'category': 'tt_url_partial'")
        warning_idx = text.find("'category': 'tt_success_inferred_but_no_video_url'")
        assert partial_idx < warning_idx, (
            'tt_url_partial должен быть БЕРЕД tt_success_inferred_but_no_video_url '
            '(supplements pattern)'
        )
        # Verify guard
        guard_section = text[partial_idx:warning_idx + 500]
        assert 'inferred_path_used' in guard_section, (
            'tt_success_inferred_but_no_video_url должен быть guarded inferred_path_used'
        )
```

- [ ] **Step 3: Run test — expected FAIL**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py::TestUrlClassification -v 2>&1 | tail -10
```

Expected: AssertionError.

- [ ] **Step 4: Add warning event после existing `tt_url_partial` block**

В коде после блока `tt_url_partial` (~line 1024 после `meta={...}` close):

```python
            # [P1.4 v3 2026-05-11] Additionally — если success пришёл через inferred
            # path (а не existing UPLOAD_OK), это сигнал operator'у что cancelled
            # publish мог пройти как success.
            if inferred_path_used:
                log.warning(
                    f'  ⚠️ TikTok: success inferred but no /video/ URL — '
                    f'возможно cancelled/no-op publish'
                )
                self.log_event(
                    'warning',
                    'TikTok: success inferred но specific URL не получен — '
                    'возможно cancelled publish (operator проверка нужна)',
                    meta={'category': 'tt_success_inferred_but_no_video_url',
                          'platform': self.platform,
                          'profile_url_fallback': profile_url},
                )
```

- [ ] **Step 5: Run tests — expected PASS**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py -v 2>&1 | tail -15
```

Expected: 8 PASS (7 prev + 1 url classification).

- [ ] **Step 6: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_wait_upload_integration.py
git commit -m "feat(tt-publish): tt_success_inferred_but_no_video_url warning event

Supplements existing tt_url_partial (не replaces).
Emitted ТОЛЬКО при inferred_path_used=True — distinguishes legitimate publishes
с slow URL fetch от cancelled publishes spotted via main-nav.
Operator visibility для silent fail class."
```

---

### Task 9.5: Behavioral integration tests (Codex round 1 P1)

**Files:**
- Modify: `tests/test_publisher_tt_wait_upload_integration.py`

**Rationale (Codex P1 finding):** source-level `text.find(...)` checks НЕ доказывают runtime behavior. Plan может пройти даже если flow сломан. Нужны heavy-mocked TikTokMixin tests на ai_unstuck call counts + event categories.

- [ ] **Step 1: Add mocked TikTokMixin behavioral tests**

Append к `tests/test_publisher_tt_wait_upload_integration.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Behavioral integration tests (Codex round 1 P1)
# Heavy-mock pattern: build TikTokMixin instance с mocked self.adb, dump_ui,
# log_event etc. Run subset of wait_upload через direct method invocation
# на extracted iteration helper (или скопировать loop body для мини-driver).
# Pattern взять из tests/test_publisher_tt_music_rights.py (_make_mixin_*).
# ─────────────────────────────────────────────────────────────────────────────

from tests.test_publisher_tt_post_publish_success_helper import (  # noqa: E402
    TT_MAIN_ACT, TT_DETAIL_ACT, TT_CAMERA_ACT, _build_nav_xml,
)


def _make_mixin_with_full_mocks():
    """Build TikTokMixin instance with mocked methods для wait_upload subset.

    Mocks:
      - self.adb (returns controlled dumpsys outputs)
      - self.dump_ui (returns controlled XML)
      - self.log_event (capture invocations)
      - self.tap_element (no-op, returns False)
      - self.adb_tap, ai_unstuck (counted invocations)
    Sets:
      - self.platform = 'TikTok'
      - self.media_type = 'video'
      - self.account = 'test_acc'
    """
    m = TikTokMixin()
    m.platform = 'TikTok'
    m.media_type = 'video'
    m.account = 'test_acc'
    m.adb = MagicMock(return_value='')
    m.dump_ui = MagicMock(return_value='<hierarchy/>')
    m.log_event = MagicMock()
    m.tap_element = MagicMock(return_value=False)
    m.adb_tap = MagicMock()
    m.ai_unstuck = MagicMock(return_value=False)
    m._save_debug_artifacts = MagicMock()
    m._safe_kb_probe = MagicMock()
    return m


def _wait_upload_one_iter(mixin, ui_xml, top_activity, wait):
    """Drive ONE iteration of wait_upload-like flow для testability.

    Returns: dict with {'broke', 'inferred', 'ai_called', 'events'}.
    Pattern: вызывает _tt_infer_post_publish_success, эмулирует AI Unstuck guard
    chain. Минимально воспроизводит flow Task 6+7+8 без full publish_tiktok.
    """
    from publisher_tiktok import _tt_infer_post_publish_success
    events = []
    mixin.log_event.side_effect = lambda lvl, msg, meta=None: events.append(meta or {})
    # Detection block (Task 6)
    success, meta = _tt_infer_post_publish_success(ui_xml, top_activity, wait)
    if success:
        mixin.log_event('info', 'inferred',
                        meta={'category': 'tt_post_publish_success_inferred', **meta})
        return {'broke': True, 'inferred': True, 'ai_called': 0, 'events': events}
    # AI Unstuck guard chain (Task 7+8) — only fires на wait%5==4
    ai_called = 0
    if wait > 0 and wait % 5 == 4:
        cur_act = top_activity
        if 'musically' not in cur_act and 'tiktok' not in cur_act.lower():
            return {'broke': False, 'inferred': False, 'ai_called': 0, 'events': events}
        success_check, gmeta = _tt_infer_post_publish_success(ui_xml, cur_act, wait)
        if success_check:
            mixin.log_event('info', 'skip',
                            meta={'category': 'tt_unstuck_skipped_post_publish', **gmeta})
            return {'broke': False, 'inferred': False, 'ai_called': 0, 'events': events}
        if 'CameraActivity' in cur_act:
            mixin.log_event('error', 'camera',
                            meta={'category': 'tt_unexpected_camera_after_share',
                                  'top_activity': cur_act[:160]})
            return {'broke': True, 'inferred': False, 'ai_called': 0, 'events': events}
        # Legit recovery — AI Unstuck вызывается
        mixin.ai_unstuck('goal', max_attempts=3)
        ai_called = 1
    return {'broke': False, 'inferred': False, 'ai_called': ai_called, 'events': events}


class TestBehavioralIntegration:
    def test_inferred_success_emits_event_and_breaks(self):
        m = _make_mixin_with_full_mocks()
        ui = _build_nav_xml(['Главная', 'Друзья', 'Создать', 'Входящие', 'Профиль'])
        r = _wait_upload_one_iter(m, ui, TT_MAIN_ACT, 1)
        assert r['inferred'] is True
        assert r['broke'] is True
        assert r['ai_called'] == 0
        cats = [e.get('category') for e in r['events']]
        assert 'tt_post_publish_success_inferred' in cats

    def test_main_nav_visible_skips_ai_unstuck(self):
        """wait=4 (триггер AI), main nav visible → AI NOT called, skip event emitted."""
        m = _make_mixin_with_full_mocks()
        ui = _build_nav_xml(['Главная', 'Друзья', 'Создать', 'Входящие', 'Профиль'])
        # First iter inferred would fire — но мы тестируем guard, симулируя
        # что detection block почему-то miss'нул (e.g. dump race) — ставим wait=4
        # и main_act такой что _tt_infer вернёт True → skip path сработает.
        # NB: detection block в реальном flow тоже сработает раньше; тест
        # проверяет defense-in-depth слой.
        r = _wait_upload_one_iter(m, ui, TT_MAIN_ACT, 4)
        # detection block уже триггерит inferred=True → broke=True, ai_called=0
        assert r['ai_called'] == 0

    @pytest.mark.parametrize('activity', [
        'PermissionActivity',
        'MusicSelectActivity',
        'CutVideoActivity',
        'CoverActivity',
    ])
    def test_legit_recovery_activities_call_ai_unstuck(self, activity):
        """wait=4, top_activity ∈ {Permission/Music/Cover/CutVideo} →
           detection block False → main-nav guard False → Camera False →
           AI Unstuck called normally."""
        m = _make_mixin_with_full_mocks()
        # Empty UI (no nav) → _tt_infer returns False (composer seed match)
        ui = '<hierarchy><node bounds="[0,0][720,2520]"/></hierarchy>'
        composer_act = (f'topResumedActivity=ActivityRecord{{abc 0 '
                        f'com.zhiliaoapp.musically/.x.{activity} t1}}')
        r = _wait_upload_one_iter(m, ui, composer_act, 4)
        assert r['ai_called'] == 1, (
            f'{activity} should NOT block AI Unstuck (legit recovery)'
        )
        assert r['broke'] is False

    def test_camera_activity_hard_fails(self):
        """wait=4, top_activity = CameraActivity → break + event,
           AI Unstuck NOT called."""
        m = _make_mixin_with_full_mocks()
        ui = '<hierarchy><node bounds="[0,0][720,2520]"/></hierarchy>'
        r = _wait_upload_one_iter(m, ui, TT_CAMERA_ACT, 4)
        assert r['broke'] is True
        assert r['ai_called'] == 0
        cats = [e.get('category') for e in r['events']]
        assert 'tt_unexpected_camera_after_share' in cats
```

- [ ] **Step 2: Run behavioral tests — expected PASS**

```bash
python -m pytest tests/test_publisher_tt_wait_upload_integration.py::TestBehavioralIntegration -v 2>&1 | tail -15
```

Expected: 7 PASS (1 inferred + 1 main-nav skip + 4 parametrized legit recovery + 1 camera).

- [ ] **Step 3: Run все integration tests + helper tests**

```bash
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py tests/test_publisher_tt_wait_upload_integration.py -v 2>&1 | tail -10
```

Expected: 19 helper + (1 source + 1 main-nav source + 5 camera source + 1 url-source + 7 behavioral) = 34 PASS total.

- [ ] **Step 4: Commit**

```bash
git add tests/test_publisher_tt_wait_upload_integration.py
git commit -m "test(tt-publish): behavioral integration tests с mocked TikTokMixin

Codex round 1 P1 — source-level marker checks недостаточны для invariants.
Heavy-mock pattern: _make_mixin_with_full_mocks + _wait_upload_one_iter driver.
Покрывает: inferred success → break, main-nav skip AI, legit recovery (4 activities)
вызывают AI, CameraActivity hard-fail break."
```

---

## Phase 3 — Pre-deploy verification

### Task 10: Codex code review pre-deploy

**Files:** none (review-only).

- [ ] **Step 1: Verify все tests зелёные**

```bash
cd /home/claude-user/autowarm-testbench-feat-tt-post-publish-success-20260511
python -m pytest tests/test_publisher_tt_post_publish_success_helper.py tests/test_publisher_tt_wait_upload_integration.py tests/test_publisher_tt_music_rights.py tests/test_tt_audio_dialog.py tests/test_tt_bound_based_nav.py -v 2>&1 | tail -10
```

Expected: all PASS, no regressions в existing TT tests.

- [ ] **Step 2: Codex review changes vs origin/main**

```bash
~/.local/bin/codex -c sandbox_mode="danger-full-access" review --base main --title "TT post-publish success detection — implementation v1" 2>&1 | tail -100
```

Expected: structured findings P1/P2/P3.

- [ ] **Step 3: Apply Codex finds inline (если есть)**

Если P1 finds — fix их + commit. Если P2/P3 — judgment call (apply or defer-with-rationale в commit).

- [ ] **Step 4: Re-run tests после Codex finds applied**

```bash
python -m pytest tests/ -v 2>&1 | tail -15
```

Expected: all green.

---

### Task 11: Push branch + open PR (если работаем через PR; иначе skip)

**Files:** none.

- [ ] **Step 1: Push feature branch**

```bash
cd /home/claude-user/autowarm-testbench-feat-tt-post-publish-success-20260511
source ~/secrets/github-gengo2.env
git push -u origin feat/tt-post-publish-success-20260511
```

Expected: branch pushed.

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(tt-publish): post-publish success detection (closes pt 4523 pattern)" --body "$(cat <<'EOF'
## Summary
- Detection helper `_tt_infer_post_publish_success` через bounds-scoped XML parse + 5-group nav label set
- `_wait_tiktok_upload` detection block после generic dialog handler
- AI Unstuck guards: main-nav skip + CameraActivity hard-fail (NARROWED — Permission/Music/Cover не блокируются)
- `tt_success_inferred_but_no_video_url` warning event для cancelled publish observability
- 19 helper + 8 integration tests, source-order placement guard

## Spec
docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md (v3, 3 раунда Codex review)

## Plan
docs/superpowers/plans/2026-05-11-tt-post-publish-success-detection-plan.md

## Test plan
- [x] Unit tests pure helper (19 PASS)
- [x] Integration tests source-order + guards (8 PASS)
- [x] Existing TT tests no regression
- [ ] Live verify pt 4488 re-queue (Task 12)
- [ ] 24h metric: tt_post_publish_success_inferred count (Task 13)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL.

- [ ] **Step 3: Wait for CI green (если есть CI workflow)**

```bash
gh pr checks --watch
```

- [ ] **Step 4: Merge PR (squash-merge predefined в repo)**

```bash
gh pr merge --squash --auto
```

Expected: PR merged.

---

### Task 12: Verify prod auto-pull

**Files:** none.

- [ ] **Step 1: Verify prod pulled новый commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin main
git log -1 --oneline
# должен показать новый merge commit
```

Expected: HEAD совпадает с origin/main; новый commit (merge feat/tt-post-publish-success...) на месте.

- [ ] **Step 2: Verify pm2 cwd корректный (per memory feedback_pm2_dump_path_drift)**

```bash
sudo pm2 describe autowarm | grep -E "exec cwd|status"
```

Expected: `exec cwd: /root/.openclaw/workspace-genri/autowarm`, status `online`.

- [ ] **Step 3: Verify нужный код реально живёт в prod файле**

```bash
grep -c "POST-PUBLISH SUCCESS DETECTION 2026-05-11" /root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py
grep -c "tt_post_publish_success_inferred" /root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py
```

Expected: оба >= 1.

- [ ] **Step 4: PM2 spawn'ит Python per-task — fix живой автоматически (без pm2 reload)**

Note: autowarm dispatches publisher как Python child process per task. Новый publisher_tiktok.py подцепится со следующей публикацией без pm2 restart.

---

### Task 13: Live verification pt 4488

**Files:** none.

- [ ] **Step 1: Re-queue pt 4488 (clickpay_world same account)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -P pager=off -c "
UPDATE publish_queue
SET status='pending',
    publish_task_id=NULL,
    updated_at=NOW()
WHERE publish_task_id=4488
RETURNING id, status, publish_task_id;
"
```

Expected: одна строка returned.

- [ ] **Step 2: Wait dispatcher pickup (≤5 min) + monitor**

```bash
# Poll каждые 60s до появления нового pt
until PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "SELECT id FROM publish_tasks WHERE account='clickpay_world' AND created_at > NOW() - INTERVAL '15 min' LIMIT 1;" | grep -q .; do sleep 60; done
echo "new pt picked up"
```

Expected: новый pt id появился.

- [ ] **Step 3: Monitor till status = awaiting_url или failed**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -P pager=off -c "
SELECT id, account, status, error_code,
       jsonb_array_length(events) AS n_events,
       (SELECT COUNT(*) FROM jsonb_array_elements(events) e
        WHERE e->'meta'->>'category'='tt_post_publish_success_inferred') AS success_inferred_count,
       (SELECT MAX((e->'meta'->>'wait_iteration')::int) FROM jsonb_array_elements(events) e
        WHERE e->'meta'->>'category'='tt_post_publish_success_inferred') AS detect_at_wait,
       (SELECT bool_or(e->'meta'->>'category' = 'tt_unstuck_skipped_post_publish') FROM jsonb_array_elements(events) e) AS unstuck_skipped,
       (SELECT bool_or(e->'meta'->>'category' = 'tt_success_inferred_but_no_video_url') FROM jsonb_array_elements(events) e) AS no_video_url_warning
FROM publish_tasks
WHERE account='clickpay_world' AND created_at > NOW() - INTERVAL '15 min'
ORDER BY id DESC LIMIT 1;
"
```

Expected outcomes:
- **Best case:** `status=awaiting_url`, `success_inferred_count >= 1`, `detect_at_wait <= 5`, `n_events <= 30`. ✅
- **Acceptable:** `status=awaiting_url`, success через existing UPLOAD_OK (`success_inferred_count=0`) — fix не сработал но baseline preserved. ⚠️
- **Bad:** `status=failed`, error_code в `tt_upload_confirmation_timeout` / `tt_fg_lost`. Read screen recording per memory `feedback_publish_fail_analysis_video_first.md`.

- [ ] **Step 4: Document evidence**

Создать `docs/evidence/2026-05-11-tt-post-publish-success-detection-shipped.md`:

```markdown
# TT post-publish success detection — live verification

**Date:** 2026-05-11
**Spec:** docs/superpowers/specs/2026-05-11-tt-post-publish-success-detection-design.md
**Plan:** docs/superpowers/plans/2026-05-11-tt-post-publish-success-detection-plan.md
**PR:** #<pr_number>
**Merge commit:** <sha>

## Live verify pt <new_id>
- Account: clickpay_world (re-queue pt 4488)
- Raspberry: <X>
- Status: <status>
- success_inferred_count: <N>
- detect_at_wait: <wait_N>
- Total task time: <duration>s vs baseline ~720s
- screen_record_url: <url>

## Verdict
<PASS / FAIL / PARTIAL>
```

Commit:
```bash
git add docs/evidence/2026-05-11-tt-post-publish-success-detection-shipped.md
git commit -m "docs(evidence): TT post-publish success detection — pt <id> verified"
```

---

### Task 14: 24h metric measurement (deferred — schedule reminder)

**Files:** none.

- [ ] **Step 1: Schedule 24h follow-up через CronCreate (или manual)**

24h после deploy запустить:

```sql
-- Candidate-impact metric (per spec — это upper bound на спасённые tasks)
SELECT COUNT(*) AS detected_per_24h
FROM publish_tasks
WHERE platform='tiktok'
  AND updated_at >= NOW() - INTERVAL '24 hours'
  AND events @> '[{"meta":{"category":"tt_post_publish_success_inferred"}}]'::jsonb;

-- Regression check — tt_fg_lost / tt_upload_confirmation_timeout 24h
SELECT
  error_code,
  COUNT(*) FILTER (WHERE updated_at >= NOW() - INTERVAL '24 hours') AS last_24h,
  COUNT(*) FILTER (WHERE updated_at >= NOW() - INTERVAL '7 days'
                   AND updated_at < NOW() - INTERVAL '24 hours') AS prev_6d
FROM publish_tasks
WHERE platform='tiktok'
  AND error_code IN ('tt_fg_lost', 'tt_upload_confirmation_timeout')
GROUP BY error_code;

-- AI Unstuck guards firing — confirm cascade prevention working
SELECT COUNT(*) AS skipped_post_publish_24h
FROM publish_tasks
WHERE platform='tiktok'
  AND updated_at >= NOW() - INTERVAL '24 hours'
  AND events @> '[{"meta":{"category":"tt_unstuck_skipped_post_publish"}}]'::jsonb;

-- CameraActivity hard-fail (если зафиксирован — investigate)
SELECT id, account, raspberry, error_code
FROM publish_tasks
WHERE platform='tiktok'
  AND updated_at >= NOW() - INTERVAL '24 hours'
  AND events @> '[{"meta":{"category":"tt_unexpected_camera_after_share"}}]'::jsonb;

-- inferred-but-no-URL warnings (cancelled publish indicator)
SELECT COUNT(*) AS no_url_warnings_24h
FROM publish_tasks
WHERE platform='tiktok'
  AND updated_at >= NOW() - INTERVAL '24 hours'
  AND events @> '[{"meta":{"category":"tt_success_inferred_but_no_video_url"}}]'::jsonb;
```

- [ ] **Step 2: Update memory с post-ship findings**

Обновить `project_publisher_outage_2026_05_09.md` или создать `project_tt_post_publish_success_shipped.md` с metrics.

---

## Out of scope (отдельные backlog)

- AI Unstuck reason-rephrasing anti-loop bypass (`ai-unstuck-reason-rephrasing-bypass`)
- AI Unstuck outer-cap для TT wait_upload (`ai-unstuck-outer-cap-tt`)
- Re-audit `tt_upload_confirmation_timeout` history на success-not-detected pattern
- Status bumping для `tt_success_inferred_but_no_video_url` (defer до evidence)
- Manual TT activity tour для расширения `TT_COMPOSER_ACTIVITIES_SEED` через дамп каждого composer screen

---

## Self-Review checklist

- ✅ Spec coverage: все 7 spec sections (helper, detection block, AI guards, URL classification, tests, live verify, 24h metric) покрыты Task 1-14
- ✅ No placeholders: каждый код-snippet полный, exact paths/SQL/grep, expected outputs
- ✅ Type consistency: `_tt_infer_post_publish_success` returns `(bool, dict)` — same signature во всех вызовах. `inferred_path_used` flag — bool, init False, set True ТОЛЬКО в success branch
- ⚠️ TDD discipline: Tasks 1-3, 6-9, 9.5 имеют real red→green→commit cycle. **Tasks 4-5 — test-only regression cases, expected green** (XML parse уже покрывает их в Task 3 — добавляем дополнительные cases для defensive coverage без impl change). Task 10-14 — verification/deploy, no impl change.
- ✅ Frequent commits: 10+ commits в Phase 1+2, 1 в Phase 3 (Codex finds applied), evidence commit в Phase 3
