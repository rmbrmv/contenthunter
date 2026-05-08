# TikTok publish stabilization — Phase 1 implementation plan v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать Phase 1 из spec'и `2026-05-08-tiktok-publish-stabilization-design.md` — combined classification + bound-based nav + vision-fallback за feature flag.

**Architecture:** Изменения в `account_switcher.py` (TT-detector + nav helpers) и `publisher_kernel.py` (step→category mapping).

**Feature flag scope (явно):**
- **Always-on (классификация / observability):** step→category mappings,
  `_tt_is_own_profile` positive-evidence, split fail-categories на 3
  (`unreachable`/`target_absent`/`profile_nav_failed_foreign`),
  marker updates. Это безопасные изменения, нужны для измерения
  iter-2 эффекта.
- **За env-var `TT_BOUND_NAV_ENABLED` (default `false`):** bound-based
  bottom-nav lookup + vision-fallback в `_go_to_profile_tab` (tap-target
  resolution). Это активный change поведения; gate'ит его flag для
  безопасного rollout. Старый legacy path остаётся фоллбэком.

**Path conventions (важно):**
- **Working tree (specs + plans + evidence):**
  `/home/claude-user/contenthunter/.claude/worktrees/tt-publish-design-20260508/`
  — `docs/superpowers/{specs,plans}/...` и `docs/evidence/...`.
- **Deploy tree (autowarm code):**
  `/root/.openclaw/workspace-genri/autowarm/`
  — `account_switcher.py`, `publisher_kernel.py`, `tests/...`. **Каждая
  команда ниже отмечает в каком tree выполняется.** Auto-push hook
  (memory `reference_autowarm_git_hook.md`) пушит коммиты deploy-tree
  main'а в GitHub; pre-merge код живёт в feature-branch и не деплоится.

**Branch strategy:**
- В deploy-tree создать feature-branch `fix/tt-bound-nav-phase1` от main.
  Все Task 2-9 deploy-tree коммиты идут в эту ветку.
- В working-tree коммиты идут в `worktree-tt-publish-design-20260508`
  (текущая worktree-branch).

**Tech Stack:** Python 3.11, pytest, MagicMock; ADB через `publisher.adb`/`publisher.adb_tap`; uiautomator dump через `publisher.dump_ui`; vision через `publisher_vision_recovery.attempt_vision_recovery`.

---

## File map

**Modify (deploy tree):**
- `publisher_kernel.py` — extend `_SWITCHER_STEP_TO_CATEGORY` (3 new entries).
- `account_switcher.py`:
  - `_TT_OWN_PROFILE_MARKERS` — extend для TT 44.4.3 (Task 3).
  - `_tt_is_own_profile` — positive-evidence (Task 4).
  - `_tt_bottom_nav_profile_bounds_from_xml` (new helper, Task 5).
  - `_go_to_profile_tab` (TT branch) — bounds → vision → coords-fallback (Task 6, 7).
  - `_tt_try_bottomsheet_recovery` — return enum reason, split categories (Task 8).
  - `_switch_tiktok` — wire new categories from recovery enum (Task 8).

**Create (deploy tree):**
- `tests/test_tt_bound_based_nav.py` — Phase-1 TDD tests.
- `tests/fixtures/tt_4_4_3_own_profile.xml`
- `tests/fixtures/tt_4_4_3_foreign_profile.xml`
- `tests/fixtures/tt_4_4_3_feed.xml`
- `tests/fixtures/PROVENANCE.md` — short doc: dump source per fixture.

**Create (working tree):**
- `docs/evidence/2026-05-08-tt-publish-phase1-phone19-smoke.md` (Task 9).

---

## Task 1: Capture phone #19 fixtures + provenance doc

**Tree:** deploy
**Files:**
- Create: `tests/fixtures/tt_4_4_3_foreign_profile.xml` (download from S3)
- Create: `tests/fixtures/tt_4_4_3_feed.xml` (latest task на phone #19)
- Create: `tests/fixtures/tt_4_4_3_own_profile.xml` (manual capture phone #19)
- Create: `tests/fixtures/PROVENANCE.md`

> **Why first:** TDD требует known-good fixtures. Без own-profile fixture
> Task 3 (markers) и Task 4 (positive evidence) проверять нечем.

- [ ] **Step 1: Foreign fixture from task 3773**

```bash
cd /root/.openclaw/workspace-genri/autowarm
mkdir -p tests/fixtures
curl -s 'https://save.gengo.io/autowarm/ui_dumps/tiktok/task3773_switch_3773_tt_2_profile_tab_1778228448.xml' \
  -o tests/fixtures/tt_4_4_3_foreign_profile.xml
test -s tests/fixtures/tt_4_4_3_foreign_profile.xml && \
  grep -c 'Подписаться\|Сообщение' tests/fixtures/tt_4_4_3_foreign_profile.xml
```

Expected: file size ~53KB, `Подписаться` and `Сообщение` markers present.

- [ ] **Step 2: Feed fixture — last failed TT task на phone #19**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -t -A -c "
SELECT events FROM publish_tasks
WHERE platform='TikTok' AND device_serial='RF8YA0W57EP'
  AND created_at > NOW() - INTERVAL '7 days'
ORDER BY id DESC LIMIT 1;
" | python3 -c "
import sys, json
events = json.loads(sys.stdin.read())
for e in events:
    msg = e.get('message','') or e.get('msg','')
    if 'tt_1_feed' in msg and 'url=' in msg:
        for tok in msg.split():
            if tok.startswith('url='):
                print(tok[4:]); sys.exit(0)
print('NOT_FOUND')
"
```

Скачать URL → `tests/fixtures/tt_4_4_3_feed.xml`. Проверить:

```bash
grep -oE 'text="[^"]{1,40}"' tests/fixtures/tt_4_4_3_feed.xml | sort -u | head -30
```

Expected: видны bottom-nav labels (`Главная`, `Интересное`, `Профиль` или
аналог), хотя бы один nav-text с координатами в нижней части. Если labels
отсутствуют — попробовать других recent failed tasks или зафиксировать
факт в PROVENANCE и обозначить ожидаемое содержимое (Tasks 4-5 могут
потребовать обновления).

- [ ] **Step 3: Own-profile fixture — manual capture phone #19**

В отдельной ssh-сессии или вручную через ADB:

```bash
ADB="adb -H 82.115.54.26 -P 15068 -s RF8YA0W57EP"
# Ensure TT foreground + manually navigate to own profile
$ADB shell monkey -p com.zhiliaoapp.musically -c android.intent.category.LAUNCHER 1
sleep 8
# Manually (через VNC/screencap) — открыть TT, тапнуть Профиль,
# если попали на foreign — открыть account-switcher (tap header) и
# переключиться на gennadiya4 / user70415121188138.
# Когда подтверждено что на own (виден «Редактировать профиль» / handle):
$ADB shell uiautomator dump --compressed /sdcard/own.xml
$ADB pull /sdcard/own.xml tests/fixtures/tt_4_4_3_own_profile.xml
ls -la tests/fixtures/tt_4_4_3_own_profile.xml
grep -oE '(text|content-desc)="[^"]{1,80}"' tests/fixtures/tt_4_4_3_own_profile.xml \
  | sort -u | head -40
```

Expected: dump содержит как минимум один из markers
{`Редактировать профиль`, `Edit profile`, `Меню профиля`,
`Profile menu`, `Создать историю`, `TikTok Studio`}. Если ни одного —
**Task 3 (markers update) обязателен** перед Task 4.

> **Если uiautomator падает с idle-state:** попробовать `--compressed` (как
> в команде выше), или `service call activity 1599295570 i32 1 i32 1` (ANR
> nudge), или `am force-stop` + relaunch. Если совсем ничего — записать
> screenshot via `screencap -p` и зафиксировать в PROVENANCE что fixture
> = vision-only (Task 5 будет не XML-based assertion).

- [ ] **Step 4: Provenance doc**

Создать `tests/fixtures/PROVENANCE.md`:

```markdown
# TT 44.4.3 fixtures

Source: phone #19 (RF8YA0W57EP, raspberry=7, ADB 82.115.54.26:15068).
TikTok versionName=44.4.3 (versionCode=2024404030).

## tt_4_4_3_foreign_profile.xml
Captured from publish_task 3773 (target=clickpay_app). Foreign profile:
@qazaqsha_sozder.arnasy1 (Kazakh TikTok, 4.3M followers, surfaced from
Suggestions feed). Anti-markers `text="Подписаться"`, `text="Сообщение"`.

## tt_4_4_3_feed.xml
Captured from <task_id_filled_at_runtime>, step `tt_1_feed`. Bottom-nav
visible. Used in Task 5 to verify _tt_bottom_nav_profile_bounds_from_xml.

## tt_4_4_3_own_profile.xml
Manually captured 2026-05-08 from phone #19 after switching to
<gennadiya4|user70415121188138> via account-switcher. Used in Tasks 3-4
для validation own-profile markers и positive-evidence detection.
```

- [ ] **Step 5: Commit fixtures + provenance**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git checkout -b fix/tt-bound-nav-phase1   # if not already on it
git add tests/fixtures/tt_4_4_3_*.xml tests/fixtures/PROVENANCE.md
git commit -m "test(fixtures): TT 44.4.3 own/foreign/feed dumps from phone #19"
```

---

## Task 2: Add new step→category mappings (no behavior change)

**Tree:** deploy
**Files:**
- Modify: `publisher_kernel.py:76-100`
- Create/Modify: `tests/test_tt_bound_based_nav.py`

- [ ] **Step 1: Read current `_SWITCHER_STEP_TO_CATEGORY` (lines 76-100)**

```bash
cd /root/.openclaw/workspace-genri/autowarm
sed -n '76,105p' publisher_kernel.py
```

- [ ] **Step 2: Add 3 new mappings — insert after line 81 (`tt_2_target_not_logged_in`)**

```python
    # [Phase-1 2026-05-08] Split categories — было одно tt_target_not_on_device,
    # теперь разделение: nav не достиг own profile vs switcher не открылся
    # vs switcher открылся но target отсутствует. Старый
    # tt_target_not_on_device остаётся для совместимости alerts/dashboards.
    'tt_2_profile_nav_failed_foreign': 'tt_profile_nav_failed_foreign',
    'tt_2_account_switcher_unreachable': 'tt_account_switcher_unreachable',
    'tt_2_account_switcher_target_absent': 'tt_account_switcher_target_absent',
```

- [ ] **Step 3: Create `tests/test_tt_bound_based_nav.py` skeleton + first 2 tests**

```python
"""Phase-1 TT publish stabilization tests.

Запуск:
    cd /root/.openclaw/workspace-genri/autowarm
    pytest tests/test_tt_bound_based_nav.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_kernel import _SWITCHER_STEP_TO_CATEGORY  # noqa: E402
from account_switcher import AccountSwitcher  # noqa: E402

FIXTURES = ROOT / 'tests' / 'fixtures'


def _make_tt_switcher() -> AccountSwitcher:
    """Mock AccountSwitcher with platform=TikTok publisher."""
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.task_id = 9999
    publisher.adb = MagicMock(return_value='')
    publisher.dump_ui = MagicMock(return_value='')
    publisher.log_event = MagicMock()
    publisher.set_step = MagicMock()
    publisher.adb_tap = MagicMock()
    publisher.tap_element = MagicMock(return_value=False)
    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    sw._maybe_screenshot = MagicMock(return_value=None)
    return sw


def test_split_categories_present():
    """Phase-1 split: 3 new step→category mappings."""
    assert _SWITCHER_STEP_TO_CATEGORY['tt_2_profile_nav_failed_foreign'] == 'tt_profile_nav_failed_foreign'
    assert _SWITCHER_STEP_TO_CATEGORY['tt_2_account_switcher_unreachable'] == 'tt_account_switcher_unreachable'
    assert _SWITCHER_STEP_TO_CATEGORY['tt_2_account_switcher_target_absent'] == 'tt_account_switcher_target_absent'


def test_legacy_target_not_on_device_alias_preserved():
    """Старый mapping остаётся (compat для frontend/analytics)."""
    assert _SWITCHER_STEP_TO_CATEGORY['tt_2_target_not_logged_in'] == 'tt_target_not_on_device'
```

- [ ] **Step 4: Run tests, expect 2 PASS**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_tt_bound_based_nav.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add publisher_kernel.py tests/test_tt_bound_based_nav.py
git commit -m "feat(switcher): TT split categories — Phase-1 step→category mappings"
```

---

## Task 3: Update `_TT_OWN_PROFILE_MARKERS` для TT 44.4.3 (BEFORE positive-evidence)

**Tree:** deploy
**Files:**
- Modify: `account_switcher.py:1444-1463`
- Modify: `tests/test_tt_bound_based_nav.py`

> **Why before Task 4:** Task 4 будет проверять `_tt_is_own_profile(own_xml) == True`.
> Если markers устарели, Task 4 fail'ит «for the wrong reason».

- [ ] **Step 1: Inspect own-profile fixture для актуальных markers**

```bash
cd /root/.openclaw/workspace-genri/autowarm
grep -oE '(text|content-desc)="[^"]{1,80}"' tests/fixtures/tt_4_4_3_own_profile.xml \
  | sort -u | head -50
```

Compare со списком в `_TT_OWN_PROFILE_MARKERS:1444-1463` (`account_switcher.py`):

```bash
sed -n '1444,1463p' account_switcher.py
```

Identify: какие из current markers found в fixture? Какие в fixture но
отсутствуют в коде? **Не добавлять markers, которые могут появиться на
foreign** (Подписаться/Сообщение/Suggested и т.п.) — они должны быть
unambiguously own (e.g. «Кошелёк», «Активность», «Удалённые»,
«Закладки» — только на own profile).

- [ ] **Step 2: Add failing test for fixture-recognition**

В `tests/test_tt_bound_based_nav.py`, добавить:

```python
def test_own_profile_fixture_recognized_by_markers():
    """Real phone-#19 own-profile dump should match _TT_OWN_PROFILE_MARKERS."""
    sw = _make_tt_switcher()
    own_xml = (FIXTURES / 'tt_4_4_3_own_profile.xml').read_text()
    # На этом этапе positive-evidence ещё не реализована (Task 4).
    # Используем существующую логику _tt_is_own_profile (legacy: any-marker).
    assert sw._tt_is_own_profile(own_xml), (
        f'TT 44.4.3 own-profile fixture not recognized — markers list outdated. '
        f'Update _TT_OWN_PROFILE_MARKERS based on fixture content.'
    )
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_tt_bound_based_nav.py::test_own_profile_fixture_recognized_by_markers -v
```

Если PASS — markers OK, переходим к Step 5 (commit only fixture без
изменения markers). Если FAIL — Step 4.

- [ ] **Step 4 (if FAIL): Update `_TT_OWN_PROFILE_MARKERS`**

В `account_switcher.py:1444-1463`, добавить markers based on Step 1 grep:

```python
    _TT_OWN_PROFILE_MARKERS = [
        # ... existing markers preserved ...
        # [Phase-1 2026-05-08] TT 44.4.3 markers from phone #19 fixture
        # ('text', '<actual_marker_from_grep>'),
        # ('content-desc', '<another_marker>'),
        # IMPORTANT: keep them unambiguously own-only (no Подписаться/etc.)
    ]
```

Re-run test → PASS.

- [ ] **Step 5: Run full suite, no regression**

```bash
pytest tests/test_account_switcher_tt.py tests/test_tt_bound_based_nav.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_tt_bound_based_nav.py
git commit -m "feat(switcher): _TT_OWN_PROFILE_MARKERS validated/updated for TT 44.4.3"
```

---

## Task 4: `_tt_is_own_profile` requires positive evidence

**Tree:** deploy
**Files:**
- Modify: `account_switcher.py:1536-1553`
- Modify: `tests/test_tt_bound_based_nav.py`

> **Why:** Codex pushback — «not foreign» != «own». Need positive marker
> AND no foreign markers. Conflict (rare) → defensive False.

- [ ] **Step 1: Add 3 failing tests**

```python
def test_is_own_profile_requires_positive_evidence():
    """Ambiguous XML без markers → False (не True)."""
    sw = _make_tt_switcher()
    ambiguous_xml = '<hierarchy><node text="Загрузка..." /></hierarchy>'
    assert sw._tt_is_own_profile(ambiguous_xml) is False


def test_is_own_profile_true_with_own_marker_no_foreign():
    """Positive marker + no foreign → True."""
    sw = _make_tt_switcher()
    own_xml = (FIXTURES / 'tt_4_4_3_own_profile.xml').read_text()
    assert sw._tt_is_own_profile(own_xml) is True


def test_is_own_profile_false_when_own_and_foreign_both_present():
    """Conflict: own + foreign markers → defensive False."""
    sw = _make_tt_switcher()
    conflict_xml = (
        '<hierarchy>'
        '<node text="Редактировать профиль" />'
        '<node text="Подписаться" />'
        '</hierarchy>'
    )
    assert sw._tt_is_own_profile(conflict_xml) is False
```

- [ ] **Step 2: Run tests — at least 1 should FAIL**

```bash
pytest tests/test_tt_bound_based_nav.py::test_is_own_profile_requires_positive_evidence \
       tests/test_tt_bound_based_nav.py::test_is_own_profile_false_when_own_and_foreign_both_present -v
```

Expected: ≥1 FAIL (`test_is_own_profile_false_when_own_and_foreign_both_present`
точно — current logic не проверяет foreign). Если все три PASS уже —
re-read implementation: возможно current уже enforces, тогда переписать
тесты так чтобы они актуально probed gap. Don't proceed until at least
один test fails.

- [ ] **Step 3: Update `_tt_is_own_profile` (account_switcher.py:1536-1553)**

```python
    def _tt_is_own_profile(self, xml: str) -> bool:
        """True если xml-дамп показывает свой профиль TikTok.

        [Phase-1 2026-05-08] Positive evidence required: positive marker
        из `_TT_OWN_PROFILE_MARKERS` И отсутствие foreign markers
        (`_TT_FOREIGN_PROFILE_MARKERS`). Конфликт обоих → defensive
        False (caller должен trigger vision/dump-retry).

        [FIX: TT-markers-any-attr] Проверяем markers в content-desc/text
        одинаково.
        """
        if not xml:
            return False
        any_own_vals = [v for _, v in self._TT_OWN_PROFILE_MARKERS]
        has_own = any(
            re.search(rf'content-desc="{re.escape(val)}"', xml)
            or re.search(rf'text="{re.escape(val)}"', xml)
            for val in any_own_vals
        )
        if not has_own:
            return False
        has_foreign = any(
            re.search(rf'text="{re.escape(val)}"', xml)
            for val in self._TT_FOREIGN_PROFILE_MARKERS
        )
        return not has_foreign
```

- [ ] **Step 4: Run all positive-evidence tests, expect PASS**

```bash
pytest tests/test_tt_bound_based_nav.py::test_is_own_profile_requires_positive_evidence \
       tests/test_tt_bound_based_nav.py::test_is_own_profile_true_with_own_marker_no_foreign \
       tests/test_tt_bound_based_nav.py::test_is_own_profile_false_when_own_and_foreign_both_present -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full TT suite — confirm no regression**

```bash
pytest tests/test_account_switcher_tt.py tests/test_tt_bound_based_nav.py -v
```

Expected: all pass. Если что-то регрессит из старых TT-тестов (особенно
тесты что проверяют «not foreign → own»), обновить тесты под новую
семантику (positive evidence required).

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_tt_bound_based_nav.py
git commit -m "fix(switcher): _tt_is_own_profile requires positive evidence (Phase-1)"
```

---

## Task 5: `_tt_bottom_nav_profile_bounds_from_xml` helper

**Tree:** deploy
**Files:**
- Modify: `account_switcher.py` — add helper near `_tt_smart_tap_profile` (line 1742)
- Modify: `tests/test_tt_bound_based_nav.py`

> **Why:** Static coords (972, 2320) drift'нули. Резолвить bounds из XML.

- [ ] **Step 1: Verify `parse_ui_dump` element API in account_switcher**

```bash
sed -n '150,170p' account_switcher.py  # UIElement dataclass
```

Confirm `el.clickable`, `el.bounds` (tuple x1,y1,x2,y2), `el.label`,
`el.center` available. Если signature другая — Task 5 implementation
скорректировать (но это base infra, должно совпадать).

- [ ] **Step 2: Add 2 failing tests**

```python
def test_bottom_nav_profile_bounds_finds_lower_15pct_label():
    """Phase-1: clickable element с label «Профиль» в нижней 15%."""
    sw = _make_tt_switcher()
    feed_xml = (FIXTURES / 'tt_4_4_3_feed.xml').read_text()
    bounds = sw._tt_bottom_nav_profile_bounds_from_xml(feed_xml, screen_height=2340)
    assert bounds is not None, 'Should find profile tab in feed bottom-nav'
    cx, cy = bounds
    assert cx > 800, f'Profile tab is rightmost; got x={cx}'
    assert cy >= int(2340 * 0.85), f'Profile tab in lower 15%; got y={cy}'


def test_bottom_nav_profile_bounds_returns_none_when_no_label():
    """No nav labels → None."""
    sw = _make_tt_switcher()
    empty_xml = (
        '<hierarchy>'
        '<node text="some-feed-content" clickable="true" bounds="[0,100][1080,500]" />'
        '</hierarchy>'
    )
    bounds = sw._tt_bottom_nav_profile_bounds_from_xml(empty_xml, screen_height=2340)
    assert bounds is None
```

- [ ] **Step 3: Run, expect FAIL (helper not defined)**

```bash
pytest tests/test_tt_bound_based_nav.py::test_bottom_nav_profile_bounds_finds_lower_15pct_label -v
```

Expected: `AttributeError: ... has no attribute '_tt_bottom_nav_profile_bounds_from_xml'`.

- [ ] **Step 4: Implement helper**

Добавить **прямо перед** `_tt_smart_tap_profile` (line 1742):

```python
    # Narrow labels — exact match (case-insensitive) после strip,
    # не substring. 'me' substring matched бы 'menu', 'meme' и т.п.
    _TT_PROFILE_TAB_LABELS = ('профиль', 'profile', 'я', 'you', 'me')

    def _tt_bottom_nav_profile_bounds_from_xml(
            self, xml: str, screen_height: int = 2340) -> Optional[tuple]:
        """Найти центр иконки «Профиль» в bottom-nav TT через XML.

        Returns (cx, cy) или None если элемент не найден.
        Критерии:
          - clickable=true
          - text/content-desc после strip().lower() ∈ _TT_PROFILE_TAB_LABELS
            (exact match, не substring)
          - bounds[1] >= screen_height * 0.85 (нижняя 15%)
          - выбираем самый правый кандидат (Профиль обычно последний)
        """
        if not xml:
            return None
        elements = parse_ui_dump(xml)
        if not elements:
            return None
        threshold_y = int(screen_height * 0.85)
        candidates = []
        for el in elements:
            if not el.clickable:
                continue
            if el.bounds[1] < threshold_y:
                continue
            for attr_val in (el.text, el.content_desc):
                if attr_val and attr_val.strip().lower() in self._TT_PROFILE_TAB_LABELS:
                    candidates.append(el)
                    break
        if not candidates:
            return None
        target = max(candidates, key=lambda e: e.bounds[0])
        return target.center
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
pytest tests/test_tt_bound_based_nav.py::test_bottom_nav_profile_bounds_finds_lower_15pct_label \
       tests/test_tt_bound_based_nav.py::test_bottom_nav_profile_bounds_returns_none_when_no_label -v
```

Expected: 2 passed.

> Если 1st fail'ит из-за labels отсутствуют в `tt_4_4_3_feed.xml` — посмотреть
> grep'ом (Task 1 Step 2). Если в fixture только desc=«Профиль» без text —
> наш helper уже учитывает оба attr. Если совсем нет такого clickable — fixture
> неудачный, перезапустить Step 2 на другой recent task'е.

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_tt_bound_based_nav.py
git commit -m "feat(switcher): _tt_bottom_nav_profile_bounds_from_xml helper"
```

---

## Task 6: Wire bound-based nav в `_go_to_profile_tab` (за feature flag)

**Tree:** deploy
**Files:**
- Modify: `account_switcher.py` — `_go_to_profile_tab` (find via grep)
- Modify: `tests/test_tt_bound_based_nav.py`

> **Why:** Use the bounds helper, but ТОЛЬКО когда `TT_BOUND_NAV_ENABLED=true`.
> Default — legacy code-path.

- [ ] **Step 1: Locate `_go_to_profile_tab`**

```bash
grep -n "def _go_to_profile_tab" /root/.openclaw/workspace-genri/autowarm/account_switcher.py
```

Read 30 lines starting at the matched line. Note: existing impl, скорее
всего, тапает по `cfg['profile_tab']['coords']` или ищет по `desc`.
Сохраняй legacy behavior как is для flag=false.

- [ ] **Step 2: Add 2 failing tests**

```python
def test_go_to_profile_tab_uses_bounds_when_flag_enabled(monkeypatch):
    """С TT_BOUND_NAV_ENABLED=true: bounds path."""
    monkeypatch.setenv('TT_BOUND_NAV_ENABLED', 'true')
    sw = _make_tt_switcher()
    feed_xml = (FIXTURES / 'tt_4_4_3_feed.xml').read_text()
    sw.p.dump_ui = MagicMock(return_value=feed_xml)
    cfg = {'profile_tab': {'coords': (972, 2320), 'desc': ['Профиль']},
           'package': 'com.zhiliaoapp.musically'}
    sw._go_to_profile_tab(cfg, 'tt_2_profile_tab')
    assert sw.p.adb_tap.called
    cx, cy = sw.p.adb_tap.call_args.args[:2]
    assert cx > 800 and cy >= int(2340 * 0.85)


def test_go_to_profile_tab_skips_bounds_when_flag_disabled(monkeypatch):
    """Default (no env): legacy path; bounds helper НЕ вызывается."""
    monkeypatch.delenv('TT_BOUND_NAV_ENABLED', raising=False)
    sw = _make_tt_switcher()
    sw._tt_bottom_nav_profile_bounds_from_xml = MagicMock(return_value=(999, 999))
    cfg = {'profile_tab': {'coords': (972, 2320), 'desc': ['Профиль']},
           'package': 'com.zhiliaoapp.musically'}
    sw._go_to_profile_tab(cfg, 'tt_2_profile_tab')
    # Helper не должен вызваться
    assert not sw._tt_bottom_nav_profile_bounds_from_xml.called, (
        'Bounds helper should not run when TT_BOUND_NAV_ENABLED is unset'
    )
```

- [ ] **Step 3: Run, expect 1st FAIL (bounds path not wired)**

```bash
pytest tests/test_tt_bound_based_nav.py::test_go_to_profile_tab_uses_bounds_when_flag_enabled -v
```

Expected: FAIL (adb_tap called с (972, 2320) или not called).

- [ ] **Step 4: Wire feature flag в `_go_to_profile_tab`**

Найти TT-branch (или общий entry). В начале метода добавить:

```python
        # [Phase-1 2026-05-08] Bound-based nav за feature flag.
        # Скоп ограничен TT (других платформ не касается).
        if (self.p.platform == 'TikTok'
                and os.environ.get('TT_BOUND_NAV_ENABLED', 'false').strip().lower()
                in ('1', 'true', 'yes')):
            xml = self.p.dump_ui(retries=1) or ''
            bounds = self._tt_bottom_nav_profile_bounds_from_xml(xml, screen_height=2340)
            if bounds:
                cx, cy = bounds
                log.info(f'[Phase-1 TT-bound-nav] resolved profile tab at '
                         f'({cx},{cy}) tap_method=xml_bounds')
                self.p.log_event(
                    'account_switch',
                    f'tt_bound_nav: tap_method=xml_bounds coords=({cx},{cy})',
                    meta={'category': 'tt_bound_nav',
                          'tap_method': 'xml_bounds',
                          'tap_coords': [cx, cy],
                          'step': step},
                )
                self.p.adb_tap(cx, cy)
                return
            # bounds not found — vision fallback (Task 7) wired ниже
            # затем legacy coords fall-through.
            log.info('[Phase-1 TT-bound-nav] bounds not in XML; trying legacy '
                     '(vision fallback in Task 7)')
            self.p.log_event(
                'account_switch',
                'tt_bound_nav: tap_method=coords_fallback (no_bounds_in_xml)',
                meta={'category': 'tt_bound_nav',
                      'tap_method': 'coords_fallback',
                      'reason': 'no_bounds_in_xml',
                      'step': step},
            )
        # ... existing legacy logic continues unchanged ...
```

Verify `import os` уже есть в account_switcher.py header (он есть — `_dump_dir = '/tmp/...'` использует path).

> **Скоп изменения:** только prefix добавлен; legacy код остаётся как
> fallback. flag=false → код тот же что до commit'а.

- [ ] **Step 5: Run tests, expect PASS**

```bash
pytest tests/test_tt_bound_based_nav.py::test_go_to_profile_tab_uses_bounds_when_flag_enabled \
       tests/test_tt_bound_based_nav.py::test_go_to_profile_tab_skips_bounds_when_flag_disabled -v
```

Expected: 2 passed.

- [ ] **Step 6: Run full TT suite — flag-disabled regression check**

```bash
pytest tests/test_account_switcher_tt.py tests/test_tt_bound_based_nav.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add account_switcher.py tests/test_tt_bound_based_nav.py
git commit -m "feat(switcher): bound-based TT profile-tab nav за TT_BOUND_NAV_ENABLED"
```

---

## Task 7: Vision-fallback for bottom-nav profile-tab

**Tree:** deploy
**Files:**
- Modify: `account_switcher.py` — extend `_go_to_profile_tab` (TT branch)
- Modify: `tests/test_tt_bound_based_nav.py`

> **Why:** TT 44.4.3 uiautomator dump часто не usable (idle-state). Vision
> fallback видит UI напрямую через screencap.

- [ ] **Step 1: Verify `attempt_vision_recovery` API**

```bash
sed -n '1,80p' /root/.openclaw/workspace-genri/autowarm/publisher_vision_recovery.py
grep -n "def attempt_vision_recovery\|@dataclass\|VisionInstruction\|action\|coords\|reason" \
  /root/.openclaw/workspace-genri/autowarm/publisher_vision_recovery.py | head -20
```

Записать: signature `attempt_vision_recovery(publisher, *, task_id, platform, account, step, error_code, extra_hint)`. Return type — что-то с `.action`, `.coords`, `.reason` (как в `_switch_tiktok` уже есть pattern на line 1786-1810).

> **Если signature другой** (новый required arg, переименование) — Task 7 Step 4
> подстроить. Это primary risk поломки Task 7. Если adapter нужен — добавить
> wrapper `_call_vision_for_nav(...)` инкапсулирующий вызов.

- [ ] **Step 2: Add failing test**

```python
def test_go_to_profile_tab_uses_vision_when_xml_not_usable(monkeypatch):
    """Если dump_ui пустой → vision-fallback."""
    monkeypatch.setenv('TT_BOUND_NAV_ENABLED', 'true')
    sw = _make_tt_switcher()
    sw.p.dump_ui = MagicMock(return_value='')   # not usable
    fake_instr = MagicMock()
    fake_instr.action = 'tap'
    fake_instr.coords = (1000, 2280)
    fake_instr.reason = 'profile tab visible at (1000,2280)'
    cfg = {'profile_tab': {'coords': (972, 2320), 'desc': ['Профиль']},
           'package': 'com.zhiliaoapp.musically'}
    # Patch the import — implementation does `from publisher_vision_recovery
    # import attempt_vision_recovery` inside function, so patch source-module.
    with patch('publisher_vision_recovery.attempt_vision_recovery',
               return_value=fake_instr):
        sw._go_to_profile_tab(cfg, 'tt_2_profile_tab')
    assert sw.p.adb_tap.called
    cx, cy = sw.p.adb_tap.call_args.args[:2]
    assert (cx, cy) == (1000, 2280)
```

- [ ] **Step 3: Run, expect FAIL**

```bash
pytest tests/test_tt_bound_based_nav.py::test_go_to_profile_tab_uses_vision_when_xml_not_usable -v
```

- [ ] **Step 4: Add vision branch в `_go_to_profile_tab` (TT path)**

Insert **между** `if bounds:` блоком и финальным `coords_fallback log_event`
(Task 6, между «bounds не нашёл» fall-through):

```python
            # [Phase-1 2026-05-08] Vision-fallback когда XML не usable.
            try:
                from publisher_vision_recovery import attempt_vision_recovery
                instr = attempt_vision_recovery(
                    self.p,
                    task_id=getattr(self.p, 'task_id', 0),
                    platform='TikTok',
                    account=getattr(self, '_target', '') or '',
                    step='tt_2_profile_tab_bound_nav',
                    error_code='tt_profile_tab_bounds_unavailable',
                    extra_hint='Найди иконку bottom-nav «Профиль/Profile/Я» '
                               '(самая правая иконка в нижней панели TikTok). '
                               'Верни action="tap" с coords=(x,y) центра иконки.',
                )
                if (instr and getattr(instr, 'action', None) == 'tap'
                        and getattr(instr, 'coords', None)):
                    vx, vy = instr.coords
                    log.info(f'[Phase-1 TT-bound-nav] vision resolved at '
                             f'({vx},{vy}) tap_method=vision')
                    self.p.log_event(
                        'account_switch',
                        f'tt_bound_nav: tap_method=vision coords=({vx},{vy})',
                        meta={'category': 'tt_bound_nav',
                              'tap_method': 'vision',
                              'tap_coords': [vx, vy],
                              'vision_reason': (instr.reason or '')[:200],
                              'step': step},
                    )
                    self.p.adb_tap(vx, vy)
                    return
            except Exception as e:
                log.warning(f'[Phase-1 TT-bound-nav] vision fallback failed: {e}')
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_tt_bound_based_nav.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_tt_bound_based_nav.py
git commit -m "feat(switcher): vision-fallback for TT profile-tab when XML not usable"
```

---

## Task 8: Split `_tt_try_bottomsheet_recovery` into structured outcome

**Tree:** deploy
**Files:**
- Modify: `account_switcher.py:1671-1740` — `_tt_try_bottomsheet_recovery`
- Modify: `account_switcher.py:1922-1941` — `_switch_tiktok` callsite
- Modify: `tests/test_tt_bound_based_nav.py`

> **Why:** Codex pushback — `bool` return undermines categorization.
> Заменить на enum: `RECOVERED` / `UNREACHABLE` / `TARGET_ABSENT` /
> `PARSER_FAILED`. И требование `rows_parsed > 0` для `target_absent`
> (иначе fallback — `unreachable` или `parser_failed`).

- [ ] **Step 1: Define enum and update return type**

В `account_switcher.py`, рядом с `SwitchResult` dataclass (~line 177):

```python
from enum import Enum

class TTRecoveryOutcome(Enum):
    RECOVERED = 'recovered'                 # success: target switched
    UNREACHABLE = 'unreachable'             # sheet anchor not found
    PARSER_FAILED = 'parser_failed'         # anchor found but rows_parsed == 0
    TARGET_ABSENT = 'target_absent'         # rows parsed, scroll exhausted, target missing
```

- [ ] **Step 2: Add 3 failing tests**

```python
def test_bottomsheet_recovery_returns_unreachable_when_anchor_missing():
    """Header tap → no sheet anchor → UNREACHABLE."""
    from account_switcher import TTRecoveryOutcome
    sw = _make_tt_switcher()
    sw.p.dump_ui = MagicMock(return_value='<hierarchy><node text="x" /></hierarchy>')
    sw._tap_profile_header = MagicMock(return_value=True)
    cfg = {'profile_title_header_y_range': (120, 260)}
    outcome = sw._tt_try_bottomsheet_recovery('test_tgt', cfg, retap_idx=1)
    assert outcome == TTRecoveryOutcome.UNREACHABLE


def test_bottomsheet_recovery_returns_parser_failed_when_no_rows():
    """Anchor found, rows_parsed == 0 → PARSER_FAILED (не TARGET_ABSENT)."""
    from account_switcher import TTRecoveryOutcome
    sw = _make_tt_switcher()
    sheet_xml = (
        '<hierarchy>'
        '<node text="Управление аккаунтами" bounds="[0,1500][1080,1600]" />'
        '</hierarchy>'  # no clickable rows below anchor
    )
    sw.p.dump_ui = MagicMock(return_value=sheet_xml)
    sw._tap_profile_header = MagicMock(return_value=True)
    sw._find_and_tap_account = MagicMock(return_value=False)
    cfg = {'profile_title_header_y_range': (120, 260)}
    outcome = sw._tt_try_bottomsheet_recovery('test_tgt', cfg, retap_idx=1)
    assert outcome == TTRecoveryOutcome.PARSER_FAILED


def test_bottomsheet_recovery_returns_target_absent_when_rows_no_target():
    """Anchor found, rows_parsed > 0, scroll exhausted → TARGET_ABSENT."""
    from account_switcher import TTRecoveryOutcome
    sw = _make_tt_switcher()
    sheet_xml = (
        '<hierarchy>'
        '<node text="Управление аккаунтами" bounds="[0,1500][1080,1600]" />'
        '<node text="@other_user" bounds="[0,1700][1080,1800]" clickable="true" />'
        '<node text="@third_user" bounds="[0,1900][1080,2000]" clickable="true" />'
        '</hierarchy>'
    )
    sw.p.dump_ui = MagicMock(return_value=sheet_xml)
    sw._tap_profile_header = MagicMock(return_value=True)
    sw._find_and_tap_account = MagicMock(return_value=False)
    cfg = {'profile_title_header_y_range': (120, 260)}
    outcome = sw._tt_try_bottomsheet_recovery('test_tgt', cfg, retap_idx=1)
    assert outcome == TTRecoveryOutcome.TARGET_ABSENT
```

- [ ] **Step 3: Run tests, expect FAIL (current returns bool)**

```bash
pytest tests/test_tt_bound_based_nav.py::test_bottomsheet_recovery_returns_unreachable_when_anchor_missing \
       tests/test_tt_bound_based_nav.py::test_bottomsheet_recovery_returns_parser_failed_when_no_rows \
       tests/test_tt_bound_based_nav.py::test_bottomsheet_recovery_returns_target_absent_when_rows_no_target -v
```

Expected: 3 FAILs (`AssertionError: assert False == TTRecoveryOutcome.UNREACHABLE` или импорт).

- [ ] **Step 4: Update `_tt_try_bottomsheet_recovery` (line 1671)**

Заменить весь метод (1671-1740). Полная новая версия (`account_switcher.py`):

```python
    def _tt_try_bottomsheet_recovery(self, target: str, cfg: dict,
                                     retap_idx: int) -> 'TTRecoveryOutcome':
        """[T3 2026-04-19, Phase-1 2026-05-08] Recovery через bottomsheet.

        Returns TTRecoveryOutcome:
          - RECOVERED: target found + tapped, post-switch verified
          - UNREACHABLE: header tap не открыл sheet (anchor not found)
          - PARSER_FAILED: anchor present, но rows_parsed == 0
                           (sheet visible, layout changed / parser miss)
          - TARGET_ABSENT: rows_parsed > 0, scroll exhausted, target not
                           in list — реально target absent (inventory)

        Caller (_switch_tiktok) маппит outcome → правильную step→category.
        """
        log.info(f'[T3 TT-recovery] foreign detected → bottomsheet '
                 f'(retap_idx={retap_idx}, target={target!r})')
        self.p.log_event('account_switch',
                         f'foreign_detected_trying_bottomsheet target={target!r}')
        elements_now, _, _ = self._read_screen_hybrid('tt_2_foreign_probe_header')
        header_y_max = cfg['profile_title_header_y_range'][1]
        if not self._tap_profile_header(
                elements_now, header_y_max,
                f'tt_2_foreign_bottomsheet_probe_retap{retap_idx+1}',
                fallback_coords=(540, 180)):
            log.warning('[T3 TT-recovery] header tap failed → UNREACHABLE')
            self.p.log_event(
                'error',
                'tt_account_switcher_unreachable: header_tap_failed',
                meta={'category': 'tt_account_switcher_unreachable',
                      'target': target, 'retap_idx': retap_idx,
                      'reason': 'header_tap_failed'},
            )
            return TTRecoveryOutcome.UNREACHABLE
        time.sleep(POST_TAP_WAIT_S + 0.8)
        dump = self.p.dump_ui(retries=1)
        post_elements = parse_ui_dump(dump) if dump else []
        anchors = ACCOUNT_LIST_ANCHORS.get('TikTok', [])
        anchor_bounds = find_anchor_bounds(post_elements, anchors)
        if not anchor_bounds:
            log.warning('[T3 TT-recovery] anchor not found → UNREACHABLE')
            self.p.log_event(
                'error',
                'tt_account_switcher_unreachable: anchor_not_found',
                meta={'category': 'tt_account_switcher_unreachable',
                      'target': target, 'retap_idx': retap_idx,
                      'reason': 'anchor_not_found'},
            )
            return TTRecoveryOutcome.UNREACHABLE
        # Count clickable rows below the anchor — evidence the parser saw content.
        rows_parsed = sum(
            1 for el in post_elements
            if el.clickable and el.bounds[1] > anchor_bounds[1]
        )
        if rows_parsed == 0:
            log.warning('[T3 TT-recovery] anchor present, rows_parsed=0 → PARSER_FAILED')
            self.p.log_event(
                'error',
                'tt_account_switcher_unreachable: anchor_found_no_rows '
                '(parser_failed / layout_changed)',
                meta={'category': 'tt_account_switcher_unreachable',
                      'target': target, 'retap_idx': retap_idx,
                      'reason': 'parser_failed', 'rows_parsed': 0},
            )
            return TTRecoveryOutcome.PARSER_FAILED
        log.info(f'[T3 TT-recovery] sheet open at {anchor_bounds}, '
                 f'rows_parsed={rows_parsed}, searching {target!r}')
        if not self._find_and_tap_account(
                target, cfg, step='tt_2_foreign_recovery',
                container_y_range=(anchor_bounds[1] - 800, 2400)):
            log.warning(f'[T3 TT-recovery] target={target!r} absent after '
                        f'scroll (rows_parsed={rows_parsed}) → TARGET_ABSENT')
            self.p.log_event(
                'error',
                f'tt_account_switcher_target_absent: target={target!r} '
                f'not in list (rows_parsed={rows_parsed})',
                meta={'category': 'tt_account_switcher_target_absent',
                      'target': target, 'retap_idx': retap_idx,
                      'rows_parsed': rows_parsed,
                      'reason': 'target_not_in_list'},
            )
            return TTRecoveryOutcome.TARGET_ABSENT
        time.sleep(AFTER_SWITCH_WAIT_S)
        xml_after = self.p.dump_ui(retries=2) or ''
        if not self._tt_is_own_profile(xml_after):
            log.warning('[T3 TT-recovery] post-switch verify failed → UNREACHABLE')
            self._save_dump('tt_2_foreign_recovery_reverify_failed', xml_after)
            self.p.log_event(
                'error',
                'tt_account_switcher_unreachable: post_switch_reverify_failed',
                meta={'category': 'tt_account_switcher_unreachable',
                      'target': target, 'retap_idx': retap_idx,
                      'reason': 'post_switch_reverify_failed'},
            )
            return TTRecoveryOutcome.UNREACHABLE
        log.info(f'[T3 TT-recovery] success! switched to {target!r}')
        self.p.log_event('account_switch',
                         f'foreign_recovery: switched_ok target={target!r}')
        return TTRecoveryOutcome.RECOVERED
```

- [ ] **Step 5: Update `_switch_tiktok` callsite (line ~1922-1941)**

Заменить старый блок:

```python
                    if self._tt_try_bottomsheet_recovery(target, cfg, retap):
                        return self._tap_plus_and_verify(...)
                    self.p.log_event(
                        'error',
                        f'tt_target_not_on_device: foreign profile на ...',
                        meta={'reason': 'tt_target_not_on_device', ...},
                    )
                    return self._fail(
                        f'@{target} не logged in на устройстве — ...',
                        step='tt_2_target_not_logged_in',
                    )
```

на:

```python
                    outcome = self._tt_try_bottomsheet_recovery(target, cfg, retap)
                    if outcome == TTRecoveryOutcome.RECOVERED:
                        return self._tap_plus_and_verify(
                            cfg, step_prefix='tt_fr', final_step='tt_fp_editor',
                            verify_triggers=cfg['editor_triggers'],
                            already_matched=True,
                        )
                    # Map outcome → final fail step. Recovery уже залоггировала
                    # detailed event meta; здесь только final step для
                    # _SWITCHER_STEP_TO_CATEGORY mapping.
                    if outcome == TTRecoveryOutcome.UNREACHABLE \
                            or outcome == TTRecoveryOutcome.PARSER_FAILED:
                        final_step = 'tt_2_account_switcher_unreachable'
                    elif outcome == TTRecoveryOutcome.TARGET_ABSENT:
                        final_step = 'tt_2_account_switcher_target_absent'
                    else:
                        # Defensive fallback — не должно происходить.
                        final_step = 'tt_2_profile_nav_failed_foreign'
                    return self._fail(
                        f'@{target} не доступен через bottomsheet '
                        f'(outcome={outcome.value}); foreign profile на '
                        f'{foreign_probe_count} retap',
                        step=final_step,
                    )
```

- [ ] **Step 6: Run new tests + 4th test для final step in `_switch_tiktok`**

Add a 4th test:

```python
def test_switch_tiktok_emits_target_absent_step_when_recovery_says_so(monkeypatch):
    """End-to-end: recovery returns TARGET_ABSENT → fail step = tt_2_account_switcher_target_absent."""
    from account_switcher import TTRecoveryOutcome
    sw = _make_tt_switcher()
    sw._ensure_app_foregrounded = MagicMock(return_value=True)
    sw._ensure_foreground = MagicMock(return_value=True)
    sw._go_to_profile_tab = MagicMock()
    foreign_xml = '<hierarchy><node text="Подписаться" /><node text="Сообщение" /></hierarchy>'
    sw.p.dump_ui = MagicMock(return_value=foreign_xml)
    sw._tt_try_bottomsheet_recovery = MagicMock(return_value=TTRecoveryOutcome.TARGET_ABSENT)
    cfg = {
        'package': 'com.zhiliaoapp.musically',
        'profile_title_header_y_range': (120, 260),
        'editor_triggers': ['Опубликовать'],
        'profile_tab': {'coords': (972, 2320), 'desc': ['Профиль']},
    }
    result = sw._switch_tiktok('test_tgt', cfg)
    assert not result.success
    assert result.final_step == 'tt_2_account_switcher_target_absent'
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_tt_bound_based_nav.py -v
```

Expected: all pass. Если `test_account_switcher_tt.py` регрессит из-за
`tt_target_not_on_device` event-strings, обновить asserting tests на новые
строки/категории (НЕ откатывать impl).

- [ ] **Step 8: Commit**

```bash
git add account_switcher.py tests/test_tt_bound_based_nav.py
git commit -m "feat(switcher): _tt_try_bottomsheet_recovery returns enum outcome

Replaces bool with TTRecoveryOutcome (RECOVERED/UNREACHABLE/PARSER_FAILED/
TARGET_ABSENT). _switch_tiktok maps outcome → fail step → category.
TARGET_ABSENT requires rows_parsed > 0 evidence per Codex pushback."
```

---

## Task 9: Smoke phone #19 (testbench-only deploy)

**Tree:** working (evidence) + deploy (smoke run + rollback)
**Files:**
- Create: `docs/evidence/2026-05-08-tt-publish-phase1-phone19-smoke.md` (working tree)
- No code changes — runtime + DB только.

> **Why:** Phase-1 gate — ≥80% / 10 attempts на phone #19. Без этого не идём в Phase 2.

> **CRITICAL safety:** PM2 global env-set затронет ВСЕ phones. Используем
> testbench-only deploy: на autowarm-testbench branch / process,
> привязанном к phone #19 (memory `project_publish_testbench.md` —
> testbench отдельная PM2 ecosystem `ecosystem.testbench.config.js`).

- [ ] **Step 1: Capture rollback-state baseline**

```bash
# Save current PM2 process state before any change
sudo pm2 list > /tmp/phase1_pm2_baseline_$(date +%s).txt
sudo pm2 describe autowarm-testbench > /tmp/phase1_testbench_pre.txt 2>&1
# Capture current SHA in deploy tree
cd /root/.openclaw/workspace-genri/autowarm
git log -1 --oneline > /tmp/phase1_deploy_sha_pre.txt
cat /tmp/phase1_deploy_sha_pre.txt
```

Записать в evidence-doc что SHA и PM2 state являются rollback baseline.

- [ ] **Step 2: Push feature branch + checkout в testbench**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git push origin fix/tt-bound-nav-phase1
# Если testbench отдельный clone (см. memory), checkout там:
cd /home/claude-user/autowarm-testbench
git fetch origin
git checkout fix/tt-bound-nav-phase1
git log -1 --oneline
ls -la account_switcher.py  # confirm file looks updated
```

> Если testbench symlink'и ломаются (memory `feedback_autowarm_testbench_deploy.md`):
> rebuild node_modules через `npm ci` и затем `pm2 restart autowarm-testbench`.

- [ ] **Step 3: Set TT_BOUND_NAV_ENABLED ТОЛЬКО для testbench process**

```bash
# Edit ecosystem.testbench.config.js — add env var inline
sudo pm2 stop autowarm-testbench
# Manually edit: ecosystem.testbench.config.js → apps[].env.TT_BOUND_NAV_ENABLED='true'
# (file location: same dir as ecosystem.testbench.config.js)
sudo pm2 start ecosystem.testbench.config.js --update-env
sudo pm2 show autowarm-testbench | grep TT_BOUND_NAV_ENABLED
```

Expected: env var present and = 'true' in show output. Confirm через `sudo pm2 logs autowarm-testbench --lines 20` что нет крэша на старте.

> **Не используй `sudo pm2 set TT_BOUND_NAV_ENABLED true`** — это global PM2
> setting; затронет другие процессы при их restart.

- [ ] **Step 4: Create 10 testbench publish_tasks**

```bash
# Find current testbench seed media path (memory reference_testbench_smoke_paths.md)
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT DISTINCT media_path FROM publish_tasks
WHERE testbench=true AND status='done' AND platform='TikTok'
ORDER BY media_path
LIMIT 5;
"
```

Скопировать любой validated path. Если нет TikTok done seed — взять IG done media (S21, 1080×1920 video).

```sql
-- Скопировать MEDIA_PATH из шага выше; insert 10 tasks (5 + 5)
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<EOF
INSERT INTO publish_tasks (
  device_serial, adb_port, adb_host, raspberry, platform, account, project,
  media_path, media_type, caption, hashtags, status, testbench
) VALUES
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'gennadiya4', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #1', '["test"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'gennadiya4', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #2', '["test","tt"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'gennadiya4', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #3', '[]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'gennadiya4', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #4 longer caption testing tap-share path', '["a","b","c"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'gennadiya4', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #5', '["only"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #6', '["test"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #7', '["short"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #8', '[]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #9 — varied caption length', '["long","caption","mix"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_smoke',
   '<MEDIA_PATH>', 'video', 'Phase-1 #10', '["last"]'::jsonb, 'pending', true);
EOF
```

- [ ] **Step 5: Watch progress (15-30 минут)**

```bash
# Monitor — until все settle
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, status, error_code, account, started_at::time(0)
FROM publish_tasks
WHERE testbench=true AND project='phase1_smoke'
ORDER BY id DESC;
"
```

Wait until все 10 settle (`done` или `failed`).

- [ ] **Step 6: Compute success rate + breakdown**

```bash
# Success rate
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT status, COUNT(*) FROM publish_tasks
WHERE testbench=true AND project='phase1_smoke'
GROUP BY status ORDER BY status;
"

# Tap method distribution
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
WITH tap_methods AS (
  SELECT id, jsonb_array_elements(events)->'meta'->>'tap_method' as method
  FROM publish_tasks
  WHERE testbench=true AND project='phase1_smoke'
)
SELECT method, COUNT(*) FROM tap_methods
WHERE method IS NOT NULL GROUP BY method ORDER BY COUNT(*) DESC;
"

# Failed-only category breakdown
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
WITH cats AS (
  SELECT id, jsonb_array_elements(events)->'meta'->>'category' as category
  FROM publish_tasks
  WHERE testbench=true AND project='phase1_smoke' AND status='failed'
)
SELECT category, COUNT(DISTINCT id)
FROM cats WHERE category IS NOT NULL
GROUP BY category ORDER BY 2 DESC;
"
```

Cross-check expected behavior:
- `tap_method=xml_bounds` или `vision` для всех 10 (на TT_BOUND_NAV_ENABLED).
- Если `coords_fallback` доминирует — feature flag не включился, debug.

- [ ] **Step 7: Document evidence (working tree)**

В working tree:

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/tt-publish-design-20260508
mkdir -p docs/evidence
# Create file: docs/evidence/2026-05-08-tt-publish-phase1-phone19-smoke.md
```

Содержимое файла: pre-condition (deploy SHA, env, accounts, baseline files
из Step 1), per-task results (id, status, error_code, key event-categories,
tap_method), success rate X/10, distribution.

Если ≥80%: → Phase 2 plan.
Если <80%: root-cause sub-analysis → next iteration.

- [ ] **Step 8: Commit evidence (working tree)**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/tt-publish-design-20260508
git add docs/evidence/2026-05-08-tt-publish-phase1-phone19-smoke.md
git commit -m "docs(evidence): TT publish Phase-1 smoke — phone #19 (X/10)"
```

- [ ] **Step 9: Rollback procedure (если smoke fail или нужно)**

```bash
# 1) Stop testbench
sudo pm2 stop autowarm-testbench
# 2) Revert ecosystem.testbench.config.js (remove TT_BOUND_NAV_ENABLED env)
#    git checkout HEAD -- ecosystem.testbench.config.js
git -C /home/claude-user/autowarm-testbench checkout main
# (revert to main branch — discard fix/tt-bound-nav-phase1 в testbench tree)
# 3) Restart on previous stable
sudo pm2 start ecosystem.testbench.config.js
# 4) Verify
sudo pm2 show autowarm-testbench | grep -E "exec cwd|env"
sudo pm2 logs autowarm-testbench --lines 30
# 5) Compare against /tmp/phase1_testbench_pre.txt — same?
diff <(sudo pm2 describe autowarm-testbench) /tmp/phase1_testbench_pre.txt
```

> Production prod-tree (`/root/.openclaw/workspace-genri/autowarm/`) не
> трогается до Phase-4 rollout.

---

## Self-review checklist

After all 9 tasks complete:

1. **Spec coverage:**
   - [ ] Phase 1a (always-on classification) — Tasks 2, 8
   - [ ] Phase 1b (gated bound-based nav) — Tasks 5, 6, 7
   - [ ] _tt_is_own_profile positive evidence — Task 4
   - [ ] Markers update for 44.4.3 — Task 3
   - [ ] Phase 1 smoke gate — Task 9

2. **Placeholder scan:** legitimate runtime placeholders — `<MEDIA_PATH>`,
   `<task_id_filled_at_runtime>`, `<gennadiya4|user70415121188138>` —
   filled при выполнении. No TBD/TODO/FIXME.

3. **Type consistency:**
   - `_tt_bottom_nav_profile_bounds_from_xml` returns `Optional[tuple]` —
     consistent across Tasks 5, 6, 7.
   - `TTRecoveryOutcome` enum used in Task 8 only; legacy bool-callers
     не должны остаться (`_switch_tiktok` callsite tightly coupled).
   - `attempt_vision_recovery` signature verified Task 7 Step 1 — adapter
     если signature meantime изменился.

4. **Risks addressed:**
   - Test regression в `test_account_switcher_tt.py` — Tasks 4, 8 explicitly
     mention update assertions, не impl rollback.
   - PM2 global env risk — Task 9 explicitly testbench-only.
   - Path ambiguity — header-block clear separation; каждый Task
     marked working/deploy.
   - Rollback — Task 9 Step 9.

5. **Outcome metric:** ≥80% / 10 attempts на phone #19, with `tap_method`
   distribution showing `xml_bounds` или `vision` doминируют.

## Backlog (отдельные планы)

- Phase 2 plan (canary 30 attempts / 4 raspberry / 2 screen classes) —
  написать после Phase 1 evidence.
- Phase 3 audit — gated by Phase 2 decision table.
- Phase 4 production rollout (bulk re-queue с idempotency guard) —
  gated by Phase 3.
- Settings activity / longpress investigation — backlog до Phase 2 evidence.
- `tt_upload_confirmation_timeout` — separate issue.
- Hashtag/geotag UX features — отдельный design.
