# WP#182 — TT _open_tt_account_switcher hardening (implementation plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть рецидив `tt_account_sheet_closed_before_parse` в TT-свитчере добавив (A) stale-dump guard на probe-стадии (зеркало WP#131 на новом месте) и (B) Phase 2 menu-path fallback при «sheet не открылся + dump валидный + на профиле».

**Architecture:** Два независимых kill-switch фикса внутри `_open_tt_account_switcher` (autowarm-testbench/account_switcher.py:4770-4872). Узкий helper-рефактор: текущий Phase 2 menu-path (строки 4894 до конца метода) выносится в private `_run_tt_phase2_menu_path` — вызывается из Stories-pivot ветки и нового sheet-not-opened fallback'а. Контракт: helper ожидает «foreground=TT, на собственном профиле» — оба caller'а это обеспечивают до вызова.

**Tech Stack:** Python 3, pytest, unittest.mock. Существующий тест-стиль — `tests/test_account_switcher_tt_stale_ui.py` (MagicMock publisher, monkeypatch env, log_calls capture).

**Spec:** `docs/superpowers/specs/2026-05-28-wp182-tt-open-list-hardening-design.md`

---

## File Structure

**Modified:**
- `account_switcher.py` — основной файл свитчера
  - Module-level: 2 новых env-helper'а (`_tt_open_list_phase2_fallback_enabled`, `_tt_open_list_probe_stale_guard_enabled`)
  - Method `_open_tt_account_switcher`: вставка stale-guard + Phase 2 fallback
  - New method `_has_tt_profile_screen_signature` (instance method)
  - New method `_run_tt_phase2_menu_path` (instance method, рефактор из тела `_open_tt_account_switcher`)

**Created:**
- `tests/test_account_switcher_tt_open_list_hardening.py` — 7 unit-тестов (по стилю `test_account_switcher_tt_stale_ui.py`)
- `tests/fixtures/tt_open_list_probe_stale.xml` — опаковый probe-dump (можно переиспользовать существующий `tt_opaque_hierarchy_10940.xml` если совпадает)
- `tests/fixtures/tt_profile_with_menu_button.xml` — валидный профильный dump с `content-desc="Меню профиля"`
- `tests/fixtures/tt_open_list_sheet.xml` — dump с открытым sheet (для recovery-теста probe2)

**Worktree:** `~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening` (создать в Task 0).

---

## Task 0: Поднять worktree в autowarm-testbench

**Files:** (системная подготовка)

- [ ] **Step 1: Detect isolation в autowarm-testbench**

```bash
cd /home/claude-user/autowarm-testbench
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
echo "git_dir=$GIT_DIR git_common=$GIT_COMMON"
git branch --show-current
```

Expected: `GIT_DIR == GIT_COMMON` (мы в обычном чекауте, не worktree).

- [ ] **Step 2: Создать worktree в global path**

```bash
mkdir -p ~/.config/superpowers/worktrees/autowarm-testbench
cd /home/claude-user/autowarm-testbench
git worktree add ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening -b feat/wp182-tt-open-list-hardening
```

Expected: `Preparing worktree (new branch 'feat/wp182-tt-open-list-hardening')`.

- [ ] **Step 3: Baseline test run в worktree**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt.py tests/test_account_switcher_tt_stale_ui.py tests/test_tt_account_switcher_open.py -v 2>&1 | tail -30
```

Expected: все зелёные (baseline), сохранить число тестов для сравнения позже.

- [ ] **Step 4: Sanity check — sapience worktree branch**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
git branch --show-current
git log --oneline -3
```

Expected: branch=`feat/wp182-tt-open-list-hardening`, log начинается с актуального main.

Все последующие задачи работают в этом worktree. Команды `cd` явно указывают путь.

---

## Task 1: Feature-flag helpers + новая meta для tt_open_list

**Files:**
- Modify: `~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening/account_switcher.py` (после строки 335, где `_tt_stale_ui_guard_enabled`)
- Test: `~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening/tests/test_account_switcher_tt_open_list_hardening.py` (новый)

- [ ] **Step 1: Создать тест-файл с RED тестами на feature flags**

Create `tests/test_account_switcher_tt_open_list_hardening.py`:

```python
"""WP#182 — TT _open_tt_account_switcher hardening.

Spec: docs/superpowers/specs/2026-05-28-wp182-tt-open-list-hardening-design.md
Evidence: docs/evidence/2026-05-28-tt-failures-triage.md
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import account_switcher as _asw  # noqa: E402
from account_switcher import (  # noqa: E402
    AccountSwitcher,
    _tt_open_list_phase2_fallback_enabled,
    _tt_open_list_probe_stale_guard_enabled,
)

import pytest  # noqa: E402

TT_PKG = 'com.zhiliaoapp.musically'
LAUNCHER_PKG = 'com.sec.android.app.launcher'
TOP_TIKTOK = '  topResumedActivity=ActivityRecord{abc u0 com.zhiliaoapp.musically/.main.MainActivity}'
TOP_LAUNCHER = '  topResumedActivity=ActivityRecord{abc u0 com.sec.android.app.launcher/.activity}'


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(_asw.time, 'sleep', lambda *_a, **_kw: None)


def test_phase2_fallback_kill_switch_default_on(monkeypatch):
    monkeypatch.delenv('TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED', raising=False)
    assert _tt_open_list_phase2_fallback_enabled() is True


def test_phase2_fallback_kill_switch_off(monkeypatch):
    monkeypatch.setenv('TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED', '0')
    assert _tt_open_list_phase2_fallback_enabled() is False


def test_probe_stale_guard_kill_switch_default_on(monkeypatch):
    monkeypatch.delenv('TT_OPEN_LIST_PROBE_STALE_GUARD', raising=False)
    assert _tt_open_list_probe_stale_guard_enabled() is True


def test_probe_stale_guard_kill_switch_off(monkeypatch):
    monkeypatch.setenv('TT_OPEN_LIST_PROBE_STALE_GUARD', '0')
    assert _tt_open_list_probe_stale_guard_enabled() is False
```

- [ ] **Step 2: Run tests, expect FAIL (ImportError)**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py -v 2>&1 | tail -20
```

Expected: ImportError on `_tt_open_list_phase2_fallback_enabled` / `_tt_open_list_probe_stale_guard_enabled`.

- [ ] **Step 3: Добавить env-helpers в account_switcher.py**

Найти `_tt_stale_ui_guard_enabled` (около строки 332) и добавить **сразу после неё**:

```python
def _tt_open_list_phase2_fallback_enabled() -> bool:
    """WP#182 fallback: если probe не открыл sheet, но dump валиден и мы на
    профиле — пробуем Phase 2 menu path (как при Stories-pivot, но без BACK).

    Default ON. `TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED=0` → legacy: сразу
    `tt_account_sheet_closed_before_parse` без попытки menu-path.
    """
    return os.environ.get('TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED', '1') != '0'


def _tt_open_list_probe_stale_guard_enabled() -> bool:
    """WP#182 stale-guard: если на ПОСЛЕДНЕЙ probe-попытке dump !usable и
    dumpsys=TikTok → honest `tt_open_list_probe_stale_ui` (зеркало WP#131
    `tt_own_profile_stale_ui` на стадии открытия списка).

    Default ON. `TT_OPEN_LIST_PROBE_STALE_GUARD=0` → legacy: dump !usable
    идёт по обычной ветке probe-fail → `tt_account_sheet_closed_before_parse`.
    """
    return os.environ.get('TT_OPEN_LIST_PROBE_STALE_GUARD', '1') != '0'
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py -v 2>&1 | tail -20
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
git add account_switcher.py tests/test_account_switcher_tt_open_list_hardening.py
git -c commit.gpgsign=false commit -m "feat(wp182): env-helpers для TT_OPEN_LIST_{PHASE2_FALLBACK,PROBE_STALE_GUARD}

Два независимых kill-switch (default ON). Default-on и off-кейсы покрыты юнитами."
```

---

## Task 2: Helper `_has_tt_profile_screen_signature`

**Files:**
- Modify: `account_switcher.py` (после `_detect_tt_stories_viewer`, около строки 4673)
- Modify: `tests/test_account_switcher_tt_open_list_hardening.py` (добавить тесты)

- [ ] **Step 1: Добавить тесты в test-файл (RED)**

Append к `tests/test_account_switcher_tt_open_list_hardening.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# _has_tt_profile_screen_signature
# ─────────────────────────────────────────────────────────────────────────────

def _make_switcher():
    """Mock publisher + AccountSwitcher для unit-тестов.
    Зеркало helper'а из test_account_switcher_tt_stale_ui.py."""
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.adb = MagicMock(return_value='')
    publisher.dump_ui = MagicMock(return_value='')
    publisher.tap_element = MagicMock(return_value=False)
    publisher.adb_tap = MagicMock()
    log_calls: list[dict] = []

    def _capture_log(event_type, message, meta=None):
        log_calls.append({'event_type': event_type, 'message': message, 'meta': meta or {}})

    publisher.log_event.side_effect = _capture_log
    publisher.set_step = MagicMock()
    publisher._safe_kb_probe = MagicMock()

    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    sw._maybe_screenshot = MagicMock()
    sw._single_account_mode = False
    return sw, log_calls


def _ui_element(text='', content_desc='', clickable=False, bounds=(0, 0, 100, 100)):
    """Mini-UIElement для unit-тестов. Совместим с парсером — атрибуты те же,
    что у `UIElement` из `account_switcher`."""
    el = MagicMock()
    el.text = text
    el.content_desc = content_desc
    el.label = text or content_desc
    el.clickable = clickable
    el.bounds = bounds
    el.center = ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
    return el


def test_profile_signature_present_when_menu_button_visible():
    sw, _ = _make_switcher()
    elements = [
        _ui_element(content_desc='Меню профиля', clickable=True, bounds=(945, 112, 1058, 225)),
        _ui_element(text='@spb.home', clickable=True, bounds=(439, 574, 641, 616)),
    ]
    assert sw._has_tt_profile_screen_signature(elements) is True


def test_profile_signature_present_with_english_locale():
    sw, _ = _make_switcher()
    elements = [
        _ui_element(content_desc='Profile menu', clickable=True),
    ]
    assert sw._has_tt_profile_screen_signature(elements) is True


def test_profile_signature_absent_on_search_screen():
    sw, _ = _make_switcher()
    elements = [
        _ui_element(text='Поиск', clickable=True),
        _ui_element(text='Главная', clickable=True),
    ]
    assert sw._has_tt_profile_screen_signature(elements) is False


def test_profile_signature_absent_on_empty():
    sw, _ = _make_switcher()
    assert sw._has_tt_profile_screen_signature([]) is False
```

- [ ] **Step 2: Run, expect FAIL (AttributeError)**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py -v 2>&1 | tail -20
```

Expected: 4 предыдущих passed, 4 новых FAIL (AttributeError on `_has_tt_profile_screen_signature`).

- [ ] **Step 3: Добавить метод в AccountSwitcher**

Найти `_detect_tt_stories_viewer` (около строки 4640). После метода (около строки 4673, до `_find_tt_account_switcher_anchor_in_drawer`), добавить:

```python
    # WP#182: маркер «мы всё ещё на собственном профиле TT» — content-desc
    # «Меню профиля» / «Profile menu» button в правом верхнем углу профиля.
    # Используется как pre-flight гард для Phase 2 menu-path fallback'а,
    # чтобы не запустить drawer-логику на Search/Feed/Stories.
    _TT_PROFILE_MENU_LABELS = ('меню профиля', 'profile menu')

    def _has_tt_profile_screen_signature(self, elements: list) -> bool:
        """True если в `elements` есть «Меню профиля» / «Profile menu» button
        (content-desc или text). Сигнал «мы всё ещё на собственном TT-профиле»
        — кнопка-бургер живёт только на экране собственного профиля.

        Pure-функция над UIElement-list — safe to test in isolation.
        """
        for el in elements:
            cd = (el.content_desc or '').strip().lower()
            txt = (el.text or '').strip().lower()
            for label in self._TT_PROFILE_MENU_LABELS:
                if label in cd or label in txt:
                    return True
        return False
```

- [ ] **Step 4: Run, expect PASS**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py -v 2>&1 | tail -15
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_tt_open_list_hardening.py
git -c commit.gpgsign=false commit -m "feat(wp182): _has_tt_profile_screen_signature helper

Сигнал «мы на собственном TT-профиле» по content-desc «Меню профиля» /
«Profile menu». Pure-функция, 4 unit-теста (RU/EN locale, Search-screen, empty)."
```

---

## Task 3: Phase 2 рефактор → `_run_tt_phase2_menu_path` helper

**Files:**
- Modify: `account_switcher.py` (вынести строки 4894 → конец метода `_open_tt_account_switcher` в новый метод)

Это **чистый рефактор без изменения поведения**. Существующий test_stories_pivot должен оставаться зелёным.

- [ ] **Step 1: Идентифицировать существующий тест на Stories-pivot**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
grep -nE 'def test_.*stories|def test_.*phase2|def test_.*pivot|def test_.*menu_path' tests/*.py
```

Expected: показывает существующие тесты Stories-pivot (если есть). Сохранить список для прогонки после рефактора. Если ни одного нет — это всё равно ок (поведение покрыто Task 7 regression test); рефактор выполняется без преждевременной заглушки.

- [ ] **Step 2: Прочитать текущий метод полностью**

```bash
sed -n '4770,4990p' ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening/account_switcher.py | head -260
```

Идентифицировать: строки с комментария `# --- Phase 2: menu path (inline tap; orchestrator owns pre-tap dump) ---` (около 4894) и до конца метода `_open_tt_account_switcher`.

- [ ] **Step 3: Вынести Phase 2 в новый метод `_run_tt_phase2_menu_path`**

В файле `account_switcher.py`:

1) **Вырезать** строки от `# --- Phase 2: menu path (inline tap; orchestrator owns pre-tap dump) ---` до конца метода (то есть всё от `menu_dump = self.p.dump_ui(retries=1)` и далее, включая `return ...` в конце).

2) **Заменить** вырезанный блок на:

```python
        return self._run_tt_phase2_menu_path(target, step_base, anchors, cfg)
```

3) **Добавить** новый метод **сразу после** `_open_tt_account_switcher` (то есть на том же уровне отступа), сохранив весь вырезанный код **без изменений**, обёрнутый в:

```python
    def _run_tt_phase2_menu_path(self, target: str, step_base: str,
                                  anchors: list, cfg: dict):
        """Phase 2 menu path: тап «Меню профиля» → drawer → «Управление
        аккаунтами» / settings-nested fallback / scroll-search.

        Возвращает `(anchor_bounds, error_code)`, тот же контракт, что и
        `_open_tt_account_switcher`. Предполагает: foreground=TT, мы уже на
        собственном профиле (caller это гарантирует — Stories-pivot через BACK,
        WP#182 fallback через `_has_tt_profile_screen_signature`).

        Вынесено из тела `_open_tt_account_switcher` в WP#182 для разделения
        Phase 1 (probe) и Phase 2 (drawer-path) — у нас теперь два caller'а.

        Spec: docs/superpowers/specs/2026-05-28-wp182-tt-open-list-hardening-design.md
        """
        def _emit_error(code, extra=None):
            meta = {'category': code}
            if extra:
                meta.update(extra)
            self.p.log_event('error', code, meta=meta)
            return None, code

        # <ВСТАВИТЬ ВЫРЕЗАННЫЙ КОД С КОММЕНТАРИЕМ "# --- Phase 2: menu path" ВКЛЮЧИТЕЛЬНО>
```

**Важно:** локальный `_emit_error` нужен в helper-методе, потому что он был closure'ом внутри родительского `_open_tt_account_switcher`. Дублируем его явно (3 строки) — без этого `_emit_error` потеряет видимость.

- [ ] **Step 4: Прогнать ВСЕ существующие тесты, expect PASS (поведение не меняется)**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt.py tests/test_account_switcher_tt_stale_ui.py tests/test_tt_account_switcher_open.py tests/test_account_switcher_tt_open_list_hardening.py -v 2>&1 | tail -30
```

Expected: все baseline тесты + 8 наших новых = всё зелёное, **0 регрессий**.

Если что-то упало — **остановиться, исследовать**: рефактор должен быть behaviour-preserving. Проверить closure-видимости `cfg`, `target`, `step_base`, `anchors` — все 4 переданы как параметры.

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py
git -c commit.gpgsign=false commit -m "refactor(wp182): вынести Phase 2 menu-path в _run_tt_phase2_menu_path

Поведение не меняется. Нужно для общего вызова Stories-pivot и нового
WP#182 fallback'а (Task 5). Контракт helper'а: caller гарантирует «foreground=TT,
на собственном профиле». Локальный _emit_error дублирован в helper (был closure'ом)."
```

---

## Task 4: Stale-guard на probe — изменение №1

**Files:**
- Modify: `account_switcher.py`, метод `_open_tt_account_switcher` (внутри Phase 1 probe цикла)
- Modify: `tests/test_account_switcher_tt_open_list_hardening.py` (3 теста)

- [ ] **Step 1: Создать XML-фикстуру опакового probe dump**

```bash
ls ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening/tests/fixtures/tt_opaque_hierarchy_10940.xml 2>/dev/null && echo "fixture exists, переиспользуем" || echo "fixture missing, создать новую"
```

Если fixture **существует** (от WP#131) — переиспользуем, шаг 1 закончен.

Если **нет** — создать `tests/fixtures/tt_opaque_probe.xml`:

```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0"><node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.zhiliaoapp.musically" content-desc="" checkable="false" checked="false" clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" long-clickable="false" password="false" selected="false" bounds="[0,0][1080,2340]" /></hierarchy>
```

(1 нода, package=TikTok, нет text/clickable — это и есть opaque_hierarchy variant.)

- [ ] **Step 2: Добавить 3 теста (RED) в test-файл**

Append к `tests/test_account_switcher_tt_open_list_hardening.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Stale-guard на probe (Изменение №1)
# ─────────────────────────────────────────────────────────────────────────────

OPAQUE_PROBE_XML = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
    "<hierarchy rotation=\"0\"><node index=\"0\" text=\"\" "
    "class=\"android.widget.FrameLayout\" "
    "package=\"com.zhiliaoapp.musically\" "
    "bounds=\"[0,0][1080,2340]\" /></hierarchy>"
)

SHEET_OPEN_XML_SNIPPET = "+ Добавить аккаунт"  # минимальный признак открытого sheet'а


def _make_cfg():
    return {
        'package': TT_PKG,
        'profile_title_header_y_range': (120, 700),
    }


def _stub_open_list_phase1(sw, log_calls, dumps_in_order, dumpsys_tt=True):
    """Замокать всё, что нужно для прогонки Phase 1 probe цикла:
    _tap_profile_header → True (no-op), dump_ui возвращает по очереди dumps_in_order,
    _tt_dumpsys_confirms_foreground → dumpsys_tt.
    """
    sw._tap_profile_header = MagicMock(return_value=True)
    sw.p.dump_ui = MagicMock(side_effect=list(dumps_in_order))
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=dumpsys_tt)
    sw._detect_tt_stories_viewer = MagicMock(return_value=False)
    # Phase 2 не должен вызываться в stale-кейсе — замокать чтоб упасть, если позовут.
    sw._run_tt_phase2_menu_path = MagicMock(
        side_effect=AssertionError('Phase 2 should NOT be called on stale guard'))
    return sw


def test_probe_stale_both_attempts_emits_honest_code(monkeypatch):
    monkeypatch.delenv('TT_OPEN_LIST_PROBE_STALE_GUARD', raising=False)
    sw, log_calls = _make_switcher()
    _stub_open_list_phase1(
        sw, log_calls,
        dumps_in_order=[OPAQUE_PROBE_XML, OPAQUE_PROBE_XML],
        dumpsys_tt=True,
    )
    anchor, code = sw._open_tt_account_switcher(
        elements=[], cfg=_make_cfg(),
        target='someuser', step_base='tt_3_open_list',
    )
    assert anchor is None
    assert code == 'tt_open_list_probe_stale_ui'
    stale = [c for c in log_calls if c['meta'].get('category') == 'tt_open_list_probe_stale_ui']
    assert stale, f'expected stale-ui emit; got {[c["meta"].get("category") for c in log_calls]}'
    meta = stale[0]['meta']
    assert meta.get('variant') in ('opaque_hierarchy', 'launcher_empty')
    assert meta.get('probe_attempt') == 2


def test_probe_stale_first_attempt_recovers_on_second(monkeypatch):
    """Codex P2: transient stale на 1-й попытке не должен фейлить — 2-я попытка
    может восстановиться и открыть sheet. Stale-guard срабатывает только на
    последней (2-й) попытке."""
    monkeypatch.delenv('TT_OPEN_LIST_PROBE_STALE_GUARD', raising=False)
    sw, log_calls = _make_switcher()
    # 1-я probe → opaque, 2-я → валидный dump с маркером open sheet.
    valid_sheet_xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        "<hierarchy rotation=\"0\">"
        "<node text=\"+ Добавить аккаунт\" bounds=\"[100,1800][980,1900]\" "
        "package=\"com.zhiliaoapp.musically\" clickable=\"true\" />"
        "</hierarchy>"
    )
    _stub_open_list_phase1(
        sw, log_calls,
        dumps_in_order=[OPAQUE_PROBE_XML, valid_sheet_xml],
        dumpsys_tt=True,
    )
    anchor, code = sw._open_tt_account_switcher(
        elements=[], cfg=_make_cfg(),
        target='someuser', step_base='tt_3_open_list',
    )
    # Recovery: 2-я probe нашла открытый sheet → success.
    assert code is None, f'expected success on 2nd probe, got {code}'
    # Stale-code НЕ должен быть в логах (на 1-й попытке guard не сработал).
    stale = [c for c in log_calls if c['meta'].get('category') == 'tt_open_list_probe_stale_ui']
    assert not stale, f'unexpected stale-ui emit on transient stale: {stale}'


def test_probe_stale_dump_but_foreground_drifted_falls_through(monkeypatch):
    """Stale + dumpsys=другое приложение → НЕ наш guard, существующая WP#130 fg-drift
    логика на верхнем уровне (`if not stories_seen:`) разберётся."""
    monkeypatch.delenv('TT_OPEN_LIST_PROBE_STALE_GUARD', raising=False)
    sw, log_calls = _make_switcher()
    # Этот тест не должен звать Phase 2; убираем stub, чтобы не упало по AssertionError.
    sw._run_tt_phase2_menu_path = MagicMock()
    _stub_open_list_phase1(
        sw, log_calls,
        dumps_in_order=[OPAQUE_PROBE_XML, OPAQUE_PROBE_XML],
        dumpsys_tt=False,  # foreground drifted!
    )
    anchor, code = sw._open_tt_account_switcher(
        elements=[], cfg=_make_cfg(),
        target='someuser', step_base='tt_3_open_list',
    )
    # Stale-code НЕ должен эмититься; должен сработать существующий WP#130 fg-drift
    # путь (tt_fg_drift_unrecoverable) — он работает в `if not stories_seen:` ниже.
    stale = [c for c in log_calls if c['meta'].get('category') == 'tt_open_list_probe_stale_ui']
    assert not stale, f'stale guard fired despite foreground drift: {stale}'
```

- [ ] **Step 3: Run, expect FAIL (stale guard ещё не реализован)**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py -v -k "test_probe_stale" 2>&1 | tail -20
```

Expected: `test_probe_stale_both_attempts_emits_honest_code` FAIL (нет stale-ui emit'а). Остальные — PASS «по случайности», но это ок.

- [ ] **Step 4: Имплементация stale-guard в `_open_tt_account_switcher`**

Найти Phase 1 probe цикл (около строки 4798-4839, начиная с `for attempt in range(2):`). Найти строку:

```python
            probe_elements = parse_ui_dump(probe_dump) if probe_dump else []
```

(приблизительно строка 4811). Сразу **после** этой строки вставить:

```python
            # WP#182 [Изменение №1]: stale-guard на последней probe-попытке.
            # На 1-й попытке transient stale может восстановиться 2-й probe'ой —
            # не эмитим (Codex P2). На 2-й попытке, если dump !usable И
            # foreground=TT → честный код вместо legacy generic.
            is_last_attempt = (attempt + 1 == 2)
            if _tt_open_list_probe_stale_guard_enabled() \
                    and is_last_attempt \
                    and not is_dump_usable(probe_elements) \
                    and self._tt_dumpsys_confirms_foreground(cfg['package']):
                variant = ('opaque_hierarchy'
                           if (probe_dump and cfg['package'] in probe_dump)
                           else 'launcher_empty')
                return _emit_error(
                    'tt_open_list_probe_stale_ui',
                    {'probe_attempt': attempt + 1,
                     'variant': variant,
                     'probe_empty': not bool(probe_dump),
                     'target': target})
```

- [ ] **Step 5: Run all stale-tests, expect PASS**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py -v 2>&1 | tail -25
```

Expected: 11 passed (4 flag + 4 signature + 3 stale).

Также прогнать baseline на регрессию:

```bash
python -m pytest tests/test_account_switcher_tt.py tests/test_account_switcher_tt_stale_ui.py tests/test_tt_account_switcher_open.py -v 2>&1 | tail -10
```

Expected: 0 регрессий.

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_tt_open_list_hardening.py
git -c commit.gpgsign=false commit -m "feat(wp182): stale-guard на probe stage (Изменение №1)

Phase 1 probe loop, на ПОСЛЕДНЕЙ попытке: dump !usable + dumpsys=TikTok →
honest tt_open_list_probe_stale_ui (зеркало WP#131). 3 unit-теста:
both-stale (emit), transient-stale-recovery (no emit, Codex P2), fg-drift
(пропускаем — другая категория)."
```

---

## Task 5: Phase 2 fallback при sheet-not-opened — изменение №2

**Files:**
- Modify: `account_switcher.py`, метод `_open_tt_account_switcher` (после Phase 1 цикла, до Stories-pivot)
- Modify: `tests/test_account_switcher_tt_open_list_hardening.py` (2 теста)

- [ ] **Step 1: Добавить 2 теста (RED) в test-файл**

Append к `tests/test_account_switcher_tt_open_list_hardening.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 fallback (Изменение №2)
# ─────────────────────────────────────────────────────────────────────────────

PROFILE_NO_SHEET_XML = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
    "<hierarchy rotation=\"0\">"
    "<node index=\"0\" class=\"android.widget.Button\" "
    "content-desc=\"Меню профиля\" "
    "package=\"com.zhiliaoapp.musically\" clickable=\"true\" "
    "bounds=\"[945,112][1058,225]\" />"
    "<node index=\"1\" class=\"android.widget.Button\" text=\"@someuser\" "
    "package=\"com.zhiliaoapp.musically\" clickable=\"true\" "
    "bounds=\"[439,574][641,616]\" />"
    "<node index=\"2\" class=\"android.widget.TextView\" text=\"Подписки\" "
    "package=\"com.zhiliaoapp.musically\" "
    "bounds=\"[117,700][398,745]\" />"
    "<node index=\"3\" class=\"android.widget.TextView\" text=\"Подписчиков\" "
    "package=\"com.zhiliaoapp.musically\" "
    "bounds=\"[399,706][680,745]\" />"
    "<node index=\"4\" class=\"android.widget.TextView\" text=\"Лайки\" "
    "package=\"com.zhiliaoapp.musically\" "
    "bounds=\"[681,700][962,745]\" />"
    "</hierarchy>"
)

NON_PROFILE_XML = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
    "<hierarchy rotation=\"0\">"
    "<node text=\"Поиск\" clickable=\"true\" "
    "package=\"com.zhiliaoapp.musically\" "
    "bounds=\"[100,100][500,200]\" />"
    "<node text=\"Главная\" clickable=\"true\" "
    "package=\"com.zhiliaoapp.musically\" "
    "bounds=\"[600,100][900,200]\" />"
    "</hierarchy>"
)


def test_probe_fail_valid_dump_triggers_phase2_fallback(monkeypatch):
    """Доминанта 4/5 в день: probe 2× → валидный профиль БЕЗ открытого sheet'а →
    запускаем Phase 2 menu-path вместо legacy fail."""
    monkeypatch.delenv('TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED', raising=False)
    monkeypatch.delenv('TT_OPEN_LIST_PROBE_STALE_GUARD', raising=False)
    sw, log_calls = _make_switcher()
    sw._tap_profile_header = MagicMock(return_value=True)
    sw.p.dump_ui = MagicMock(side_effect=[PROFILE_NO_SHEET_XML, PROFILE_NO_SHEET_XML])
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw._detect_tt_stories_viewer = MagicMock(return_value=False)
    # Helper должен быть вызван; вернёт фиктивный успех.
    sw._run_tt_phase2_menu_path = MagicMock(return_value=((10, 20, 30, 40), None))

    anchor, code = sw._open_tt_account_switcher(
        elements=[], cfg=_make_cfg(),
        target='someuser', step_base='tt_3_open_list',
    )

    assert anchor == (10, 20, 30, 40)
    assert code is None
    sw._run_tt_phase2_menu_path.assert_called_once()
    # Диагностический emit перед helper'ом
    fallback = [c for c in log_calls
                if c['meta'].get('category') == 'tt_open_list_probe_fallback_to_phase2']
    assert fallback, f'expected fallback-to-phase2 emit; got {[c["meta"].get("category") for c in log_calls]}'
    # legacy НЕ эмитится
    legacy = [c for c in log_calls
              if c['meta'].get('category') == 'tt_account_sheet_closed_before_parse']
    assert not legacy


def test_probe_fail_no_profile_signature_keeps_legacy_fail(monkeypatch):
    """Если probe не открыл sheet И мы не на профиле (например, Search tab):
    Phase 2 НЕ вызываем, legacy emit как было."""
    monkeypatch.delenv('TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED', raising=False)
    monkeypatch.delenv('TT_OPEN_LIST_PROBE_STALE_GUARD', raising=False)
    sw, log_calls = _make_switcher()
    sw._tap_profile_header = MagicMock(return_value=True)
    sw.p.dump_ui = MagicMock(side_effect=[NON_PROFILE_XML, NON_PROFILE_XML])
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw._detect_tt_stories_viewer = MagicMock(return_value=False)
    sw._run_tt_phase2_menu_path = MagicMock(
        side_effect=AssertionError('Phase 2 should NOT run without profile signature'))

    anchor, code = sw._open_tt_account_switcher(
        elements=[], cfg=_make_cfg(),
        target='someuser', step_base='tt_3_open_list',
    )

    assert anchor is None
    assert code == 'tt_account_sheet_closed_before_parse'
    legacy = [c for c in log_calls
              if c['meta'].get('category') == 'tt_account_sheet_closed_before_parse']
    assert legacy
    fallback = [c for c in log_calls
                if c['meta'].get('category') == 'tt_open_list_probe_fallback_to_phase2']
    assert not fallback
```

- [ ] **Step 2: Run, expect FAIL (fallback ещё не реализован)**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py -v -k "test_probe_fail" 2>&1 | tail -20
```

Expected: `test_probe_fail_valid_dump_triggers_phase2_fallback` FAIL (Phase 2 не позвался).

- [ ] **Step 3: Имплементация Phase 2 fallback в `_open_tt_account_switcher`**

Найти ветку `if not stories_seen:` (около строки 4840). После существующего блока WP#130 fg-drift гарда (заканчивается `return _emit_error('tt_fg_drift_unrecoverable', ...)` около строки 4854), но **до** legacy `self.p.log_event('error', f'tt_account_sheet_closed_before_parse: ...')` (около строки 4865), вставить:

```python
            # WP#182 [Изменение №2]: если probe не открыл sheet, но dump валиден
            # и мы всё ещё на собственном профиле — пробуем Phase 2 menu-path
            # вместо legacy generic-fail. Закрывает доминанту 4/5 случаев 28.05
            # (tasks 11554, 11565, 11658, 11673), где @username button clickable=true,
            # но тап не открывает sheet на текущем TT-UI варианте.
            if _tt_open_list_phase2_fallback_enabled() \
                    and is_dump_usable(probe_elements) \
                    and self._has_tt_profile_screen_signature(probe_elements):
                self.p.log_event(
                    'account_switch',
                    'tt_probe_fallback_to_phase2: dump valid + profile screen + '
                    'no sheet/stories → пробуем menu-path',
                    meta={'category': 'tt_open_list_probe_fallback_to_phase2',
                          'target': target,
                          'probe_top_labels': _top_labels(probe_elements, 30)},
                )
                return self._run_tt_phase2_menu_path(target, step_base, anchors, cfg)
```

- [ ] **Step 4: Run, expect PASS**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py -v 2>&1 | tail -25
```

Expected: 13 passed (4 flag + 4 signature + 3 stale + 2 fallback).

- [ ] **Step 5: Прогнать full TT-test suite, expect 0 регрессий**

```bash
python -m pytest tests/test_account_switcher_tt.py tests/test_account_switcher_tt_stale_ui.py tests/test_tt_account_switcher_open.py tests/test_account_switcher_tt_switch_fg_guard.py tests/test_account_switcher_tt_open_list_hardening.py tests/test_canonical_error_codes.py -v 2>&1 | tail -15
```

Expected: 0 регрессий.

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_tt_open_list_hardening.py
git -c commit.gpgsign=false commit -m "feat(wp182): Phase 2 fallback при sheet-not-opened (Изменение №2)

После 2 неудачных probe, если dump !stale + has profile signature → запускаем
_run_tt_phase2_menu_path вместо legacy tt_account_sheet_closed_before_parse.
Закрывает доминанту 4/5 случаев 28.05 (11554/11565/11658/11673).
2 unit-теста (fallback fired / profile-signature absent → legacy)."
```

---

## Task 6: Kill-switch OFF keeps legacy

**Files:**
- Modify: `tests/test_account_switcher_tt_open_list_hardening.py` (1 тест)

- [ ] **Step 1: Добавить тест на off-kill-switches**

Append:

```python
def test_kill_switches_off_keep_legacy(monkeypatch):
    """Оба флага OFF: stale-dump → legacy, sheet-not-opened-valid-dump → legacy.
    Phase 2 fallback и stale-guard НЕ вызываются."""
    monkeypatch.setenv('TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED', '0')
    monkeypatch.setenv('TT_OPEN_LIST_PROBE_STALE_GUARD', '0')

    # --- sub-case 1: stale dump → legacy (без stale-honest-code) ---
    sw, log_calls = _make_switcher()
    sw._tap_profile_header = MagicMock(return_value=True)
    sw.p.dump_ui = MagicMock(side_effect=[OPAQUE_PROBE_XML, OPAQUE_PROBE_XML])
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw._detect_tt_stories_viewer = MagicMock(return_value=False)
    sw._run_tt_phase2_menu_path = MagicMock(
        side_effect=AssertionError('Phase 2 should NOT run with flags off'))

    anchor, code = sw._open_tt_account_switcher(
        elements=[], cfg=_make_cfg(),
        target='u', step_base='tt_3_open_list',
    )
    assert code == 'tt_account_sheet_closed_before_parse'
    assert not any(c['meta'].get('category') == 'tt_open_list_probe_stale_ui'
                   for c in log_calls)

    # --- sub-case 2: valid dump + profile signature → legacy (без phase2 fallback) ---
    sw2, log_calls2 = _make_switcher()
    sw2._tap_profile_header = MagicMock(return_value=True)
    sw2.p.dump_ui = MagicMock(side_effect=[PROFILE_NO_SHEET_XML, PROFILE_NO_SHEET_XML])
    sw2._tt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw2._detect_tt_stories_viewer = MagicMock(return_value=False)
    sw2._run_tt_phase2_menu_path = MagicMock(
        side_effect=AssertionError('Phase 2 should NOT run with flags off'))

    anchor, code = sw2._open_tt_account_switcher(
        elements=[], cfg=_make_cfg(),
        target='u', step_base='tt_3_open_list',
    )
    assert code == 'tt_account_sheet_closed_before_parse'
    assert not any(c['meta'].get('category') == 'tt_open_list_probe_fallback_to_phase2'
                   for c in log_calls2)
```

- [ ] **Step 2: Run, expect PASS** (Imp уже есть из Task 4/5)

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py::test_kill_switches_off_keep_legacy -v 2>&1 | tail -10
```

Expected: PASS. Если FAIL — значит флаг-гарды в Task 4/5 не сработали; вернуться, проверить `_tt_open_list_*_enabled()` вызовы.

- [ ] **Step 3: Commit**

```bash
git add tests/test_account_switcher_tt_open_list_hardening.py
git -c commit.gpgsign=false commit -m "test(wp182): kill-switches OFF keep legacy behavior

Регресс-страховка: при отключённых флагах оба фикса не вмешиваются,
legacy tt_account_sheet_closed_before_parse эмитится как до WP#182."
```

---

## Task 7: Stories-pivot regression test

**Files:**
- Modify: `tests/test_account_switcher_tt_open_list_hardening.py` (1 тест)

- [ ] **Step 1: Добавить regression-тест для Stories-pivot**

Append:

```python
STORIES_VIEWER_XML = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
    "<hierarchy rotation=\"0\">"
    "<node text=\"Закрыть\" content-desc=\"Закрыть\" "
    "package=\"com.zhiliaoapp.musically\" bounds=\"[20,40][120,150]\" />"
    "<node text=\"2 ч. назад\" "
    "package=\"com.zhiliaoapp.musically\" bounds=\"[200,200][400,250]\" />"
    "<node text=\"Ещё\" content-desc=\"Ещё\" "
    "package=\"com.zhiliaoapp.musically\" bounds=\"[500,2000][700,2100]\" />"
    "</hierarchy>"
)

OWN_PROFILE_BACK_XML = PROFILE_NO_SHEET_XML  # after BACK мы на собственном профиле


def test_stories_pivot_still_works(monkeypatch):
    """Регрессионный: Stories detected на probe → BACK → _tt_is_own_profile True →
    _run_tt_phase2_menu_path вызван. Та же helper-поверхность, что у WP#182
    fallback, но через существующий Stories-pivot путь."""
    monkeypatch.delenv('TT_OPEN_LIST_PROBE_STALE_GUARD', raising=False)
    monkeypatch.delenv('TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED', raising=False)
    sw, log_calls = _make_switcher()
    sw._tap_profile_header = MagicMock(return_value=True)
    # 1-я probe: Stories viewer → pivot break out of probe loop.
    # 2-я probe не нужна (break на 1-й).
    # После pivot: BACK + own-profile-check dump.
    sw.p.dump_ui = MagicMock(side_effect=[
        STORIES_VIEWER_XML,            # 1-й probe dump
        OWN_PROFILE_BACK_XML,          # back_dump после BACK
    ])
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    # detect_tt_stories_viewer пусть честно вернёт True на 1-м probe (timetext + close + more)
    sw._detect_tt_stories_viewer = MagicMock(side_effect=lambda elements: True)
    sw._tt_is_own_profile = MagicMock(return_value=True)
    sw._run_tt_phase2_menu_path = MagicMock(return_value=((1, 2, 3, 4), None))

    anchor, code = sw._open_tt_account_switcher(
        elements=[], cfg=_make_cfg(),
        target='someuser', step_base='tt_3_open_list',
    )

    assert anchor == (1, 2, 3, 4)
    assert code is None
    sw._run_tt_phase2_menu_path.assert_called_once()
    # Stories-pivot diagnostic emit
    stories = [c for c in log_calls
               if c['meta'].get('category') == 'tt_username_tap_opened_stories']
    assert stories, 'expected Stories-pivot emit'
```

- [ ] **Step 2: Run, expect PASS** (рефактор из Task 3 уже сделал helper вызываемым из обеих веток)

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/test_account_switcher_tt_open_list_hardening.py::test_stories_pivot_still_works -v 2>&1 | tail -10
```

Expected: PASS. Если FAIL — проверить, что в `_open_tt_account_switcher` Stories-pivot ветка тоже вызывает `_run_tt_phase2_menu_path` (а не дублирует код).

- [ ] **Step 3: Commit**

```bash
git add tests/test_account_switcher_tt_open_list_hardening.py
git -c commit.gpgsign=false commit -m "test(wp182): Stories-pivot still works (regression)

Подтверждает что helper-рефактор Task 3 не сломал существующий Stories-pivot.
Тот же _run_tt_phase2_menu_path вызывается из обеих веток (Stories + WP#182 fallback)."
```

---

## Task 8: Full test suite + codex review

- [ ] **Step 1: Прогнать ВСЁ relevant**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
python -m pytest tests/ -v 2>&1 | tail -30
```

Expected: 0 регрессий vs baseline (Task 0 Step 3). Если что-то упало — **остановиться**, исследовать.

- [ ] **Step 2: Codex review diff против main**

```bash
cd ~/.config/superpowers/worktrees/autowarm-testbench/feat-wp182-tt-open-list-hardening
git diff main..HEAD | ~/.local/bin/codex review - 2>&1 | tail -80
```

Expected: 0 P1. P2/P3 — оценить, при необходимости поправить и закоммитить.

- [ ] **Step 3: Если codex P1 → исправить и повторить шаг 2**

(итерация до 0 P1; per [feedback_codex_review_specs] — раундами до 0 P1)

- [ ] **Step 4: Verify branch state**

```bash
git log --oneline main..HEAD
git diff --stat main..HEAD
```

Expected: ~6-7 коммитов (Task 1-7), модификации только в `account_switcher.py` + новый test-файл + (опционально) fixture.

---

## Task 9: Canary + deploy

**Этот таск выполняется ВРУЧНУЮ с участием пользователя** — деплой prod.

- [ ] **Step 1: Cherry-pick / merge стратегия**

Спросить Данила: merge в main + push (с авто-пулом per [reference_autowarm_git_hook]) или отдельный canary-cherry-pick.

- [ ] **Step 2: Canary launch**

Заэнкьюить одну TT-задачу с `is_canary=true` в `publish_queue`. Команда — определить через [project_contenthunter_server] / publisher.py (не диктовать заранее, [feedback_execution_autonomy]).

- [ ] **Step 3: Monitor 1ч**

```sql
SELECT id, status, error_code, screen_record_url
FROM publish_tasks
WHERE platform='TikTok' AND is_canary=true
ORDER BY id DESC LIMIT 5;

-- ищем позитивы:
SELECT id, status, error_code FROM publish_tasks
WHERE platform='TikTok' AND status IN ('done','failed')
  AND created_at > now() - interval '1 hour'
  AND events::text LIKE '%tt_open_list_probe_fallback_to_phase2%';
```

Expected: 0 регрессий vs предыдущий канарейка.

- [ ] **Step 4: Раскатка**

PM2 reload через post-commit auto-pull (без systemd, per [feedback_deploy_scope_constraints]).

- [ ] **Step 5: Обновить memory + WP#182 → «Тестирование»**

Обновить [[project_wp182_tt_account_sheet_closed_recur]] статусом «SHIPPED+DEPLOYED». Перевести WP#182 в OpenProject в «Тестирование» через REST API.

---

## Self-Review (выполнено перед записью этого плана)

**1. Spec coverage.**
- Spec §3.1 (stale-guard) → Task 4 + тесты 1-3.
- Spec §3.2 (Phase 2 fallback + helper-рефактор) → Task 3 (рефактор) + Task 5 (fallback) + тест 4-5.
- Spec §3.3 (что не меняется) → Task 3 step 4 регрессия + Task 7.
- Spec §4 (новые элементы) → Task 1 (flags) + Task 2 (`_has_tt_profile_screen_signature`) + Task 3 (`_run_tt_phase2_menu_path`).
- Spec §5 (7 тестов) → 4 в Task 1 + 4 в Task 2 + 3 в Task 4 + 2 в Task 5 + 1 в Task 6 + 1 в Task 7 = 15 тестов; spec говорил «7 ключевых», но мы добавили 4 flag-теста + 4 signature-теста как RED для unit-уровня helper'ов (стандартно для TDD). Всё в рамках spec намерения.
- Spec §6 (деплой/rollback) → Task 9.
- Spec §7 (метрики) → Task 9 step 3 SQL.

Все секции покрыты. Нет orphan-требований.

**2. Placeholder scan.** Нет TBD/TODO/«implement later» в шагах. Каждый шаг содержит конкретный код / команду / expected output.

**3. Type consistency.**
- `_run_tt_phase2_menu_path(target, step_base, anchors, cfg)` — сигнатура одинакова в Task 3 (определение) и Task 5 (вызов).
- `_has_tt_profile_screen_signature(elements: list) -> bool` — одинакова в Task 2 (определение) и Task 5 (вызов).
- env-имена `TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED` / `TT_OPEN_LIST_PROBE_STALE_GUARD` — одинаковы в Task 1 (helpers) и Task 6 (off-test).
- Категория `tt_open_list_probe_stale_ui` / `tt_open_list_probe_fallback_to_phase2` — одинаковы по всему плану.
- Все паттерны соответствуют spec §4 таблице.

Готово к выбору режима исполнения.
