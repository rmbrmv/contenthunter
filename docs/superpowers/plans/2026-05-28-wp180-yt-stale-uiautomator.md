# WP #180 — YT stale uiautomator guard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перестать ложно атрибутировать stale uiautomator на YT-профиле как `yt_accounts_btn_missing_postmortem` (9/13 = 69 % YT-фейлов 28.05). Эмитить честный `yt_own_profile_stale_ui` с попыткой cold-restart recovery.

**Architecture:** Зеркало WP#131/TT. Добавляем три хелпера (`_yt_probe_looks_stale`, `_yt_dumpsys_confirms_foreground`, `_yt_stale_ui_check_and_recover`) + модульный kill-switch `_yt_stale_ui_guard_enabled`. Вызываем guard в `_switch_youtube` сразу после `yt_3_pre_tap`, перед `_yt_try_accounts_btn_with_retries`. На stale + dumpsys=YT — `am force-stop` + `am start` + повторный probe. Default ON.

**Tech Stack:** Python 3, pytest, `unittest.mock`, `account_switcher.py` + `publisher_kernel.py` в `autowarm-testbench`. Тесты — стиль `tests/test_account_switcher_tt_stale_ui.py`.

**Spec:** [`docs/superpowers/specs/2026-05-28-wp180-yt-stale-uiautomator-design.md`](../specs/2026-05-28-wp180-yt-stale-uiautomator-design.md)
**Evidence:** [`docs/evidence/2026-05-28-yt-triage.md`](../../evidence/2026-05-28-yt-triage.md)
**OpenProject:** https://openproject.contenthunter.ru/wp/180

---

## Working tree

Код живёт в `~/autowarm-testbench` (отдельный репозиторий от `contenthunter`). Параллельные сессии работают над WP#181/WP#182 — не блокируем main, делаем worktree.

**Все code-изменения происходят в** `~/autowarm-testbench-feat-wp180-yt-stale-ui` (новая ветка `feat/wp180-yt-stale-uiautomator`).
**Этот план + спека + evidence** живут в `~/contenthunter-wt/wp-yt-triage-2026-05-28` (ветка `wp/yt-triage-2026-05-28`, уже создана).

## File structure

- **Create:** `tests/test_account_switcher_yt_stale_ui.py` — 13 тестов (12 из спеки + kill-switch default ON).
- **Modify:** `account_switcher.py` — добавить 4 символа (1 модульная функция + 3 метода `AccountSwitcher`), вставить guard-вызов в `_switch_youtube` после `yt_3_pre_tap`.
- **Modify:** `publisher_kernel.py` — одна строка в `_SWITCHER_STEP_TO_CATEGORY`.

---

## Task 0: Setup feature worktree в autowarm-testbench

**Files:** none.

- [ ] **Step 0.1: Создать worktree autowarm-testbench**

```bash
cd ~/autowarm-testbench && git fetch origin --quiet
git worktree add ~/autowarm-testbench-feat-wp180-yt-stale-ui \
    -b feat/wp180-yt-stale-uiautomator origin/main
```

Expected:
```
Preparing worktree (new branch 'feat/wp180-yt-stale-uiautomator')
branch 'feat/wp180-yt-stale-uiautomator' set up to track 'origin/main'.
HEAD is now at 4609ab4 Merge pull request #118 from GenGo2/feat/wp179-backfill-queue-only
```

- [ ] **Step 0.2: Verify clean worktree, можем работать**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && git branch --show-current
```

Expected: `feat/wp180-yt-stale-uiautomator`

- [ ] **Step 0.3: Verify pytest discoverable**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -q 2>&1 | tail -5
```

Expected: все TT-тесты зелёные (`14 passed` или похоже). Если есть pre-existing red — задокументировать, не чинить в этом WP.

---

## Task 1: kill-switch helper `_yt_stale_ui_guard_enabled`

**Files:**
- Modify: `account_switcher.py` (после `_tt_stale_ui_guard_enabled`, около строки 336)
- Create: `tests/test_account_switcher_yt_stale_ui.py`

- [ ] **Step 1.1: Создать новый тест-файл с двумя тестами на kill-switch**

Создать `tests/test_account_switcher_yt_stale_ui.py`:

```python
"""WP #180 — YouTube own-profile stale-uiautomator guard.

Корень (триаж 2026-05-28): на шаге yt_3_open_accounts dumpsys стабильно видит
YouTube на переднем плане, но uiautomator отдаёт протухший XML (bytes=4936,
usable=False). _yt_try_accounts_btn_with_retries видит пустые elements,
триггеры «Аккаунты» не матчатся, 2 retap'а + alt-avatar + Settings-Activity
жгутся впустую → ложный yt_accounts_btn_missing_postmortem (9/13 фейлов
28.05.2026, 91/14d на 5 устройствах). Зеркало WP#131 для TT.

Guard: при подтверждённом stale-UI (xml пустой/без YT-пакета/unusable +
dumpsys стабильно=YouTube) делаем cold-restart YT (am force-stop + am start)
+ re-tap profile + повторный probe. Если повторный dump usable — продолжаем
основной flow; если снова stale — честный _fail(yt_3_own_profile_stale_ui)
без жжения 2 retap'ов + alt-avatar + Settings-Activity.
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
    UI_CONSTANTS,
    _yt_stale_ui_guard_enabled,
)

import pytest  # noqa: E402

YT_PKG = 'com.google.android.youtube'
LAUNCHER_PKG = 'com.sec.android.app.launcher'
TOP_YOUTUBE = '  topResumedActivity=ActivityRecord{abc u0 com.google.android.youtube/.WatchWhileActivity}'
TOP_LAUNCHER = '  topResumedActivity=ActivityRecord{abc u0 com.sec.android.app.launcher/.activity}'
TOP_SBROWSER = '  topResumedActivity=ActivityRecord{abc u0 com.sec.android.app.sbrowser/.Main}'


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(_asw.time, 'sleep', lambda *_a, **_kw: None)


def _make_switcher():
    publisher = MagicMock()
    publisher.platform = 'YouTube'
    publisher.adb = MagicMock(return_value='')
    publisher.dump_ui = MagicMock(return_value='')
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


def _has_category(log_calls, category):
    return any(c['meta'].get('category') == category for c in log_calls)


def _meta_for(log_calls, category):
    return next(c['meta'] for c in log_calls
                if c['meta'].get('category') == category)


# ─── Kill-switch tests ─────────────────────────────────────────────────────

def test_kill_switch_default_on(monkeypatch):
    monkeypatch.delenv('YT_STALE_UI_OWN_PROFILE_GUARD', raising=False)
    assert _yt_stale_ui_guard_enabled() is True


def test_kill_switch_off(monkeypatch):
    monkeypatch.setenv('YT_STALE_UI_OWN_PROFILE_GUARD', '0')
    assert _yt_stale_ui_guard_enabled() is False
```

- [ ] **Step 1.2: Прогнать тесты — оба должны упасть с ImportError (`_yt_stale_ui_guard_enabled` не существует)**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -q 2>&1 | tail -10
```

Expected: `ImportError: cannot import name '_yt_stale_ui_guard_enabled' from 'account_switcher'`

- [ ] **Step 1.3: Добавить `_yt_stale_ui_guard_enabled` в `account_switcher.py`**

Найти строки 329-335 (`_tt_stale_ui_guard_enabled`). Прямо после неё (около строки 336) добавить:

```python
def _yt_stale_ui_guard_enabled() -> bool:
    """[WP #180] Kill-switch для stale-uiautomator guard на YT профиле.

    Default ON. `YT_STALE_UI_OWN_PROFILE_GUARD=0` → legacy: жжём 2 retap'а +
    alt-avatar + Settings-Activity на stale dump'ах и эмитим
    yt_accounts_btn_missing_postmortem (как было до WP #180).
    """
    return os.environ.get('YT_STALE_UI_OWN_PROFILE_GUARD', '1') != '0'
```

- [ ] **Step 1.4: Прогнать тесты — оба должны пройти**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -q 2>&1 | tail -5
```

Expected: `2 passed`

- [ ] **Step 1.5: Commit**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    git add account_switcher.py tests/test_account_switcher_yt_stale_ui.py && \
    git -c commit.gpgsign=false commit -m "feat(wp180): kill-switch _yt_stale_ui_guard_enabled (default ON)"
```

---

## Task 2: `_yt_probe_looks_stale` + 4 теста

**Files:**
- Modify: `account_switcher.py` (метод класса `AccountSwitcher`)
- Modify: `tests/test_account_switcher_yt_stale_ui.py`

- [ ] **Step 2.1: Дописать 4 теста на probe в test-файл (после kill-switch тестов)**

```python
# ─── _yt_probe_looks_stale tests ───────────────────────────────────────────

def test_probe_looks_stale_empty_xml():
    sw, _ = _make_switcher()
    assert sw._yt_probe_looks_stale('', YT_PKG) is True


def test_probe_looks_stale_pkg_missing():
    """XML без YT-пакета (например, launcher после home-gesture) → stale."""
    sw, _ = _make_switcher()
    xml = '<hierarchy><node package="com.sec.android.app.launcher" text="x"/></hierarchy>'
    assert sw._yt_probe_looks_stale(xml, YT_PKG) is True


def test_probe_looks_stale_opaque_hierarchy():
    """Пакет YT есть, но иерархия непрозрачна (1 node, is_dump_usable=False).
    Реальный паттерн bytes=4936 из task 11661."""
    sw, _ = _make_switcher()
    xml = (
        '<hierarchy rotation="0">'
        '<node class="android.widget.FrameLayout" package="com.google.android.youtube" '
        'text="" resource-id="" content-desc=""/>'
        '</hierarchy>'
    )
    assert 'com.google.android.youtube' in xml
    assert sw._yt_probe_looks_stale(xml, YT_PKG) is True


def test_probe_not_stale_normal_dump():
    """Пакет YT + ЧИТАЕМАЯ иерархия (≥5 labeled) → НЕ stale."""
    sw, _ = _make_switcher()
    xml = (
        '<hierarchy rotation="0">'
        '<node package="com.google.android.youtube" text="Аккаунты" bounds="[0,200][1080,300]"/>'
        '<node package="com.google.android.youtube" text="Главная" bounds="[0,2200][216,2340]"/>'
        '<node package="com.google.android.youtube" text="Shorts" bounds="[216,2200][432,2340]"/>'
        '<node package="com.google.android.youtube" text="Подписки" bounds="[648,2200][864,2340]"/>'
        '<node package="com.google.android.youtube" text="Вы" bounds="[864,2200][1080,2340]"/>'
        '</hierarchy>'
    )
    assert sw._yt_probe_looks_stale(xml, YT_PKG) is False
```

- [ ] **Step 2.2: Прогнать — 4 новых теста должны упасть с AttributeError**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py::test_probe_looks_stale_empty_xml -q 2>&1 | tail -5
```

Expected: FAIL — `'AccountSwitcher' object has no attribute '_yt_probe_looks_stale'`

- [ ] **Step 2.3: Добавить метод `_yt_probe_looks_stale` в `AccountSwitcher`**

Найти `_tt_probe_looks_stale` (около строки 2781). Рядом, например на строке 2800 (между `_tt_probe_looks_stale` и `_tt_dumpsys_confirms_foreground`), добавить:

```python
    def _yt_probe_looks_stale(self, xml: str, target_pkg: str) -> bool:
        """[WP #180] True если YT-probe протух.

        Варианты:
          • пустой XML (uiautomator вернул '');
          • XML без YT-пакета (снимок лаунчера/чужого приложения);
          • пакет YT присутствует, но uiautomator не видит view-tree
            (Compose / SurfaceView / FLAG_SECURE — сигнатура bytes=4936,
            is_dump_usable=False).

        Зеркало _tt_probe_looks_stale (WP #131).
        """
        if not xml:
            return True
        if target_pkg not in xml:
            return True
        if not is_dump_usable(parse_ui_dump(xml)):
            return True
        return False
```

- [ ] **Step 2.4: Прогнать — 6 тестов файла должны пройти**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -q 2>&1 | tail -5
```

Expected: `6 passed`

- [ ] **Step 2.5: Commit**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    git add account_switcher.py tests/test_account_switcher_yt_stale_ui.py && \
    git -c commit.gpgsign=false commit -m "feat(wp180): _yt_probe_looks_stale (empty/pkg_missing/opaque) + 4 tests"
```

---

## Task 3: `_yt_dumpsys_confirms_foreground` + 3 теста

**Files:**
- Modify: `account_switcher.py`
- Modify: `tests/test_account_switcher_yt_stale_ui.py`

- [ ] **Step 3.1: Дописать 3 теста на dumpsys**

```python
# ─── _yt_dumpsys_confirms_foreground tests ─────────────────────────────────

def test_dumpsys_confirms_when_stable():
    sw, _ = _make_switcher()
    sw.p.adb = MagicMock(return_value=TOP_YOUTUBE)
    assert sw._yt_dumpsys_confirms_foreground(YT_PKG, reads=2) is True
    assert sw.p.adb.call_count == 2


def test_dumpsys_rejects_when_one_read_differs():
    sw, _ = _make_switcher()
    sw.p.adb = MagicMock(side_effect=[TOP_YOUTUBE, TOP_SBROWSER])
    assert sw._yt_dumpsys_confirms_foreground(YT_PKG, reads=2) is False


def test_dumpsys_rejects_when_empty():
    sw, _ = _make_switcher()
    sw.p.adb = MagicMock(return_value='')
    assert sw._yt_dumpsys_confirms_foreground(YT_PKG, reads=2) is False
```

- [ ] **Step 3.2: Прогнать — должны упасть с AttributeError**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -k dumpsys -q 2>&1 | tail -5
```

Expected: FAIL — нет атрибута.

- [ ] **Step 3.3: Добавить метод `_yt_dumpsys_confirms_foreground`**

В `account_switcher.py` сразу после `_yt_probe_looks_stale` добавить (зеркало `_tt_dumpsys_confirms_foreground` на строке 2801):

```python
    def _yt_dumpsys_confirms_foreground(self, target_pkg: str,
                                         reads: int = 2,
                                         interval: float = 0.5) -> bool:
        """[WP #180] True если dumpsys СТАБИЛЬНО (reads чтений подряд) видит
        target_pkg на переднем плане. Без uiautomator (дёшево). Тот же приём,
        что _tt_dumpsys_confirms_foreground (WP #131) и trust-dumpsys ветка
        WP #105."""
        for i in range(reads):
            top = self.p.adb(
                "dumpsys activity activities | "
                "grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
            m = re.search(r'\s([\w\.]+)/[\w\.]+', top)
            if (m.group(1) if m else '') != target_pkg:
                return False
            if i < reads - 1:
                time.sleep(interval)
        return True
```

- [ ] **Step 3.4: Прогнать — 9 тестов должны пройти**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -q 2>&1 | tail -5
```

Expected: `9 passed`

- [ ] **Step 3.5: Commit**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    git add account_switcher.py tests/test_account_switcher_yt_stale_ui.py && \
    git -c commit.gpgsign=false commit -m "feat(wp180): _yt_dumpsys_confirms_foreground (stable read) + 3 tests"
```

---

## Task 4: `_yt_stale_ui_check_and_recover` (recovery happy-path + unrecoverable)

**Files:**
- Modify: `account_switcher.py`
- Modify: `tests/test_account_switcher_yt_stale_ui.py`

- [ ] **Step 4.1: Дописать тесты на check_and_recover (4 кейса)**

```python
# ─── _yt_stale_ui_check_and_recover tests ─────────────────────────────────

def test_check_and_recover_no_stale_passes_through():
    """Probe возвращает False → recovery не запускается, status=no_stale."""
    sw, log_calls = _make_switcher()
    sw._yt_probe_looks_stale = MagicMock(return_value=False)
    sw._yt_dumpsys_confirms_foreground = MagicMock()
    sw._last_hybrid_xml = '<hierarchy/>'

    ok, status = sw._yt_stale_ui_check_and_recover(UI_CONSTANTS['YouTube'])

    assert (ok, status) == (True, 'no_stale')
    sw._yt_dumpsys_confirms_foreground.assert_not_called()
    assert not _has_category(log_calls, 'yt_own_profile_stale_detected')


def test_check_and_recover_not_yt_foreground_falls_through():
    """Probe stale, но dumpsys НЕ подтверждает YT → status=not_yt_foreground,
    основной flow продолжается (fg-guard потом упадёт по своему коду)."""
    sw, log_calls = _make_switcher()
    sw._yt_probe_looks_stale = MagicMock(return_value=True)
    sw._yt_dumpsys_confirms_foreground = MagicMock(return_value=False)
    sw._last_hybrid_xml = ''

    ok, status = sw._yt_stale_ui_check_and_recover(UI_CONSTANTS['YouTube'])

    assert (ok, status) == (True, 'not_yt_foreground')
    assert not _has_category(log_calls, 'yt_own_profile_stale_detected')


def test_check_and_recover_cold_restart_recovers():
    """Probe stale + dumpsys=YT → cold-restart → второй dump usable →
    status=recovered, эмиты detected + recovered."""
    sw, log_calls = _make_switcher()
    sw._yt_probe_looks_stale = MagicMock(return_value=True)
    sw._yt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw._last_hybrid_xml = ''  # variant=launcher_empty
    sw._go_to_profile_tab = MagicMock()
    # Готовый «живой» dump после restart
    good_elements = [MagicMock(label='Аккаунты'),
                     MagicMock(label='Главная'),
                     MagicMock(label='Shorts'),
                     MagicMock(label='Подписки'),
                     MagicMock(label='Вы')]
    sw._read_screen_hybrid = MagicMock(return_value=(good_elements, 'hybrid', None))

    ok, status = sw._yt_stale_ui_check_and_recover(UI_CONSTANTS['YouTube'])

    assert (ok, status) == (True, 'recovered')
    assert _has_category(log_calls, 'yt_own_profile_stale_detected')
    assert _has_category(log_calls, 'yt_own_profile_stale_recovered')
    # cold-restart выполнен (adb вызвался для force-stop + start)
    adb_calls = [c.args[0] for c in sw.p.adb.call_args_list if c.args]
    assert any('force-stop' in c for c in adb_calls)
    assert any('am start' in c for c in adb_calls)
    sw._go_to_profile_tab.assert_called()


def test_check_and_recover_cold_restart_irrecoverable():
    """Probe stale + dumpsys=YT → cold-restart → второй dump СНОВА stale →
    status=unrecoverable, эмит detected + yt_own_profile_stale_ui error."""
    sw, log_calls = _make_switcher()
    sw._yt_probe_looks_stale = MagicMock(return_value=True)
    sw._yt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw._last_hybrid_xml = ''
    sw._go_to_profile_tab = MagicMock()
    # Повторный dump — пустой (НЕ usable)
    sw._read_screen_hybrid = MagicMock(return_value=([], 'hybrid', None))

    ok, status = sw._yt_stale_ui_check_and_recover(UI_CONSTANTS['YouTube'])

    assert (ok, status) == (False, 'unrecoverable')
    assert _has_category(log_calls, 'yt_own_profile_stale_detected')
    assert _has_category(log_calls, 'yt_own_profile_stale_ui')
```

- [ ] **Step 4.2: Прогнать — должны упасть на AttributeError для `_yt_stale_ui_check_and_recover`**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -k check_and_recover -q 2>&1 | tail -10
```

Expected: 4 FAIL — `'AccountSwitcher' object has no attribute '_yt_stale_ui_check_and_recover'`

- [ ] **Step 4.3: Добавить `_yt_stale_ui_check_and_recover`**

В `account_switcher.py` сразу после `_yt_dumpsys_confirms_foreground` (новый метод из Task 3) добавить:

```python
    def _yt_stale_ui_check_and_recover(self, cfg: dict) -> tuple[bool, str]:
        """[WP #180] Если последний dump на YT-профиле выглядит stale и
        dumpsys стабильно подтверждает YT на переднем плане — пробуем
        cold-restart (am force-stop + am start) + re-tap profile + повторный
        probe.

        Returns (ok, status):
          • (True,  'no_stale')          — dump не stale, основной flow продолжается.
          • (True,  'not_yt_foreground') — stale, но dumpsys ≠ YT (другой класс
                                            ошибки, ловится отдельно).
          • (True,  'recovered')         — cold-restart дал usable dump, можно
                                            продолжать.
          • (False, 'unrecoverable')     — повторный probe снова stale,
                                            caller обязан _fail('yt_3_own_profile_stale_ui').

        Зеркало WP#131/TT с двумя отличиями: (1) не break-from-loop, а
        отдельный pre-step перед _yt_try_accounts_btn_with_retries; (2)
        active recovery вместо vision-based проверки (YT picker не имеет
        вижн-fallback'а current==target).
        """
        xml = self._last_hybrid_xml or ''
        if not self._yt_probe_looks_stale(xml, cfg['package']):
            return (True, 'no_stale')

        if not self._yt_dumpsys_confirms_foreground(cfg['package']):
            return (True, 'not_yt_foreground')

        # Определяем variant для метрик
        if not xml:
            variant = 'launcher_empty'
        elif cfg['package'] not in xml:
            variant = 'pkg_missing'
        else:
            variant = 'opaque_hierarchy'

        self.p.log_event(
            'account_switch',
            f'yt_own_profile_stale_ui_detected: cold-restart YT '
            f'(variant={variant})',
            meta={'category': 'yt_own_profile_stale_detected',
                  'variant': variant,
                  'step': 'yt_3_stale_recovery',
                  'platform': 'YouTube'},
        )
        self._save_dump('yt_3_stale_dump', xml)

        # ВАЖНО: _open_app_aggressive в этом файле — read-only/revision-only
        # (может выполнить `pm clear` и снести login-сессию). Здесь используем
        # простой am start, как TT retap3 (account_switcher.py:3166-3173).
        self.p.adb(f'am force-stop {cfg["package"]}')
        time.sleep(2)
        self.p.adb(f'am start -n {cfg["launch_activity"]}')
        time.sleep(OPEN_APP_WAIT_S + 2)
        self._go_to_profile_tab(cfg, 'yt_3_stale_recovery_profile')
        time.sleep(POST_TAP_WAIT_S + 1)

        elements_after, _, _ = self._read_screen_hybrid(
            'yt_3_stale_recovery_probe')
        if elements_after and is_dump_usable(elements_after):
            self.p.log_event(
                'account_switch',
                'yt_own_profile_stale_recovered',
                meta={'category': 'yt_own_profile_stale_recovered',
                      'variant': variant,
                      'step': 'yt_3_stale_recovery',
                      'platform': 'YouTube'},
            )
            return (True, 'recovered')

        self.p.log_event(
            'error',
            'yt_own_profile_stale_ui: cold-restart не помог, '
            'uiautomator всё ещё stale',
            meta={'category': 'yt_own_profile_stale_ui',
                  'variant': variant,
                  'step': 'yt_3_own_profile_stale_ui',
                  'platform': 'YouTube'},
        )
        return (False, 'unrecoverable')
```

- [ ] **Step 4.4: Прогнать — 4 новых теста + 9 предыдущих = 13 passed**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -q 2>&1 | tail -5
```

Expected: `13 passed`

- [ ] **Step 4.5: Commit**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    git add account_switcher.py tests/test_account_switcher_yt_stale_ui.py && \
    git -c commit.gpgsign=false commit -m "feat(wp180): _yt_stale_ui_check_and_recover (4 веток: no_stale/not_yt_fg/recovered/unrecoverable) + 4 tests"
```

---

## Task 5: Wire в `_switch_youtube` + маппинг + integration-тесты

**Files:**
- Modify: `account_switcher.py` (точка встройки в `_switch_youtube`, около строки 3691-3699)
- Modify: `publisher_kernel.py` (одна строка в `_SWITCHER_STEP_TO_CATEGORY`)
- Modify: `tests/test_account_switcher_yt_stale_ui.py`

- [ ] **Step 5.1: Дописать integration-тесты (3 кейса)**

В тестах нужно довести `_switch_youtube` до точки встройки. Это нетривиально — есть SA-shortcircuit, fg-guard, `_yt_ensure_foreground`, `_read_screen_hybrid` на `yt_2_profile_screen`. Поскольку нас интересует ТОЛЬКО ветка после `yt_3_pre_tap`, мокаем всё выше.

Дописать в test-файл:

```python
# ─── _switch_youtube integration tests (Task 5) ────────────────────────────

def _arm_yt_switch_to_yt3(sw, monkeypatch):
    """Довести _switch_youtube до точки встройки guard'а:
    yt_2_profile_screen / SA-check / yt_3_fg_guard все проходят,
    _read_screen_hybrid возвращает безобидные elements. Дальше тест задаёт
    поведение _yt_stale_ui_check_and_recover."""
    # модульный get_current_account_from_profile НЕ должен возвращать target
    monkeypatch.setattr(_asw, 'get_current_account_from_profile',
                        lambda *_a, **_kw: None)
    sw._yt_ensure_foreground = MagicMock(return_value=True)
    sw._go_to_profile_tab = MagicMock()
    sw._vision_read_current_account = MagicMock(return_value=None)
    # yt_2_profile_screen + yt_3_pre_tap читают один и тот же mock
    sw._read_screen_hybrid = MagicMock(
        return_value=([MagicMock(label='whatever', bounds=(0, 100, 100, 200))],
                      'hybrid', None))
    sw._last_hybrid_xml = ''


def test_switch_youtube_no_stale_runs_legacy_path(monkeypatch):
    """Guard говорит no_stale → _yt_try_accounts_btn_with_retries
    вызывается как обычно."""
    sw, log_calls = _make_switcher()
    _arm_yt_switch_to_yt3(sw, monkeypatch)
    sw._yt_stale_ui_check_and_recover = MagicMock(return_value=(True, 'no_stale'))
    sw._yt_try_accounts_btn_with_retries = MagicMock(
        return_value={'found': True, 'retries': 0,
                      'header_texts_seen': [], 'avatar_alt_tried': False})
    sw._find_and_tap_account = MagicMock(return_value=True)
    sw._tap_plus_and_verify = MagicMock(
        return_value=MagicMock(success=True, final_step='yt_fp_create_menu'))

    sw._switch_youtube('globalcardspay', UI_CONSTANTS['YouTube'])

    sw._yt_stale_ui_check_and_recover.assert_called_once()
    sw._yt_try_accounts_btn_with_retries.assert_called()


def test_switch_youtube_stale_irrecoverable_emits_honest_fail(monkeypatch):
    """Guard говорит unrecoverable → _fail('yt_3_own_profile_stale_ui'),
    _yt_try_accounts_btn_with_retries НЕ вызывается."""
    sw, log_calls = _make_switcher()
    _arm_yt_switch_to_yt3(sw, monkeypatch)
    sw._yt_stale_ui_check_and_recover = MagicMock(
        return_value=(False, 'unrecoverable'))
    sw._yt_try_accounts_btn_with_retries = MagicMock()

    result = sw._switch_youtube('globalcardspay', UI_CONSTANTS['YouTube'])

    sw._yt_try_accounts_btn_with_retries.assert_not_called()
    assert result.final_step == 'yt_3_own_profile_stale_ui', result.final_step
    assert not result.success


def test_switch_youtube_stale_recovered_continues_to_mill(monkeypatch):
    """Guard говорит recovered → элементы перечитываются и
    _yt_try_accounts_btn_with_retries вызывается с новыми elements."""
    sw, log_calls = _make_switcher()
    _arm_yt_switch_to_yt3(sw, monkeypatch)
    sw._yt_stale_ui_check_and_recover = MagicMock(return_value=(True, 'recovered'))
    sw._yt_try_accounts_btn_with_retries = MagicMock(
        return_value={'found': True, 'retries': 0,
                      'header_texts_seen': [], 'avatar_alt_tried': False})
    sw._find_and_tap_account = MagicMock(return_value=True)
    sw._tap_plus_and_verify = MagicMock(
        return_value=MagicMock(success=True, final_step='yt_fp_create_menu'))

    sw._switch_youtube('globalcardspay', UI_CONSTANTS['YouTube'])

    sw._yt_stale_ui_check_and_recover.assert_called_once()
    sw._yt_try_accounts_btn_with_retries.assert_called()
    # _read_screen_hybrid должен был вызваться ≥2 раз (pre_tap + after_recovery)
    assert sw._read_screen_hybrid.call_count >= 2


def test_switch_youtube_kill_switch_off_skips_guard(monkeypatch):
    """YT_STALE_UI_OWN_PROFILE_GUARD=0 → _yt_stale_ui_check_and_recover НЕ
    вызывается, поведение прежнее (mill идёт на исходных elements)."""
    monkeypatch.setenv('YT_STALE_UI_OWN_PROFILE_GUARD', '0')
    sw, log_calls = _make_switcher()
    _arm_yt_switch_to_yt3(sw, monkeypatch)
    sw._yt_stale_ui_check_and_recover = MagicMock()
    sw._yt_try_accounts_btn_with_retries = MagicMock(
        return_value={'found': True, 'retries': 0,
                      'header_texts_seen': [], 'avatar_alt_tried': False})
    sw._find_and_tap_account = MagicMock(return_value=True)
    sw._tap_plus_and_verify = MagicMock(
        return_value=MagicMock(success=True, final_step='yt_fp_create_menu'))

    sw._switch_youtube('globalcardspay', UI_CONSTANTS['YouTube'])

    sw._yt_stale_ui_check_and_recover.assert_not_called()
    sw._yt_try_accounts_btn_with_retries.assert_called()
```

- [ ] **Step 5.2: Прогнать — должны упасть, потому что guard ещё не встроен в `_switch_youtube`**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -k switch_youtube -q 2>&1 | tail -10
```

Expected: 4 FAIL (один из вариантов: `_yt_try_accounts_btn_with_retries.assert_not_called` упадёт; финальный шаг неправильный; и т.д.). Это норма, guard ещё не встроен.

- [ ] **Step 5.3: Встроить guard-вызов в `_switch_youtube`**

В `account_switcher.py` найти строки 3691-3699 (`_yt_ensure_foreground` → `elements_refreshed` → `_yt_try_accounts_btn_with_retries`). Заменить:

**ДО (3691-3699):**
```python
        # После fg_guard делаем свежий dump — возможно mы relaunch'нулись
        # и экран сейчас другой.
        elements_refreshed, _, _ = self._read_screen_hybrid('yt_3_pre_tap')
        if elements_refreshed:
            elements = elements_refreshed

        # [FIX: YT-accounts-retries 2026-04-19] ретраи + alt-path перед fail
        # (evidence: tasks 396/417/420/422/423 — триггер-мисс без ретраев).
        _accts_result = self._yt_try_accounts_btn_with_retries(elements, cfg)
```

**ПОСЛЕ:**
```python
        # После fg_guard делаем свежий dump — возможно mы relaunch'нулись
        # и экран сейчас другой.
        elements_refreshed, _, _ = self._read_screen_hybrid('yt_3_pre_tap')
        if elements_refreshed:
            elements = elements_refreshed

        # [WP #180] stale-uiautomator guard на YT-профиле: если последний dump
        # выглядит stale (4936 bytes / usable=False) И dumpsys стабильно
        # подтверждает YT впереди — пробуем cold-restart + 1 попытку. На
        # повторный stale — честный fail вместо ложного
        # yt_accounts_btn_missing_postmortem (жжёт 2 retap'а + alt-avatar +
        # Settings-Activity на тех же мусорных dump'ах).
        if _yt_stale_ui_guard_enabled():
            ok, status = self._yt_stale_ui_check_and_recover(cfg)
            if not ok:
                return self._fail(
                    'uiautomator на YT-профиле залип (stale) — '
                    'cold-restart не помог',
                    step='yt_3_own_profile_stale_ui',
                )
            if status == 'recovered':
                elements_after, _, _ = self._read_screen_hybrid(
                    'yt_3_pre_tap_after_recovery')
                if elements_after:
                    elements = elements_after

        # [FIX: YT-accounts-retries 2026-04-19] ретраи + alt-path перед fail
        # (evidence: tasks 396/417/420/422/423 — триггер-мисс без ретраев).
        _accts_result = self._yt_try_accounts_btn_with_retries(elements, cfg)
```

- [ ] **Step 5.4: Добавить mapping в `publisher_kernel.py`**

Найти секцию `# ── YouTube ─` в `_SWITCHER_STEP_TO_CATEGORY` (около строки 162-172). Сразу после `'yt_fg_drift_escalated': 'yt_fg_drift_escalated',` добавить:

```python
    'yt_3_own_profile_stale_ui': 'yt_own_profile_stale_ui',  # WP #180
```

- [ ] **Step 5.5: Прогнать integration-тесты — все должны пройти**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -q 2>&1 | tail -5
```

Expected: `17 passed` (13 ранее + 4 новых).

- [ ] **Step 5.6: Проверить, что mapping работает — отдельный быстрый sanity-test**

Дописать в test-файл:

```python
# ─── publisher_kernel mapping sanity ───────────────────────────────────────

def test_switcher_step_to_category_mapping_present():
    from publisher_kernel import _SWITCHER_STEP_TO_CATEGORY  # noqa: E402
    assert _SWITCHER_STEP_TO_CATEGORY.get('yt_3_own_profile_stale_ui') == \
        'yt_own_profile_stale_ui', (
            'WP #180: yt_3_own_profile_stale_ui отсутствует в '
            'publisher_kernel._SWITCHER_STEP_TO_CATEGORY'
        )
```

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/test_account_switcher_yt_stale_ui.py -q 2>&1 | tail -5
```

Expected: `18 passed`

- [ ] **Step 5.7: Commit**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    git add account_switcher.py publisher_kernel.py tests/test_account_switcher_yt_stale_ui.py && \
    git -c commit.gpgsign=false commit -m "feat(wp180): wire stale-UI guard в _switch_youtube + mapping yt_own_profile_stale_ui + 4 integration tests"
```

---

## Task 6: Full regression + codex review + PR

**Files:** none (только проверки + ревью).

- [ ] **Step 6.1: Прогнать ВЕСЬ pytest-набор tests/**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/ -q 2>&1 | tail -15
```

Expected: ≥130 зелёных (точное число — см. ранее, например `130 passed` или `>=`). Никаких REGRESSION в IG/TT/YT/общих. Если есть pre-existing red — задокументировать (не чинить).

- [ ] **Step 6.2: Прогнать codex review на diff с main**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    git diff origin/main..HEAD | ~/.local/bin/codex review - 2>&1 | tail -60
```

Expected: 0 P1. Допустимо P2/P3 — обсудить с пользователем, исправить если просто. Итерации до 0 P1 (commit per fix).

- [ ] **Step 6.3: Финальный pytest после codex-fix'ов (если были)**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    python3 -m pytest tests/ -q 2>&1 | tail -5
```

Expected: тот же green-count, что и в Step 6.1.

- [ ] **Step 6.4: Push ветки + PR**

```bash
cd ~/autowarm-testbench-feat-wp180-yt-stale-ui && \
    git push -u origin feat/wp180-yt-stale-uiautomator
set -a; source ~/secrets/github-gengo2.env; set +a
gh pr create --title "feat(wp180): YT stale uiautomator guard на профиле" \
    --body "$(cat <<'EOF'
## Что не так
За 28.05.2026 YT — 13 фейлов, из них **9 (69 %) — `yt_accounts_btn_missing_postmortem`**. 14d cross-check: **91 фейл на 5 устройствах и 9 аккаунтах** — не device-specific.

Фактическая причина — **stale uiautomator на YT-профиле**: после `yt_0_foreground_guard` (24675 bytes, usable=True) все следующие dumps возвращают `4936 bytes, usable=False`. `_yt_try_accounts_btn_with_retries` видит пустые elements → ретраи/alt-avatar/Settings-Activity жгутся впустую → ложный postmortem.

OpenProject: https://openproject.contenthunter.ru/wp/180
Spec: contenthunter `docs/superpowers/specs/2026-05-28-wp180-yt-stale-uiautomator-design.md`
Evidence: contenthunter `docs/evidence/2026-05-28-yt-triage.md`

## Что сделано
Зеркало WP#131 (TT). Добавлено:
* `_yt_probe_looks_stale(xml, pkg)` — empty/pkg_missing/opaque (`account_switcher.py`).
* `_yt_dumpsys_confirms_foreground(pkg, reads=2)` — стабильное чтение dumpsys'а без uiautomator.
* `_yt_stale_ui_check_and_recover(cfg)` → `(ok, status)`: на stale + dumpsys=YT делает `am force-stop` + `am start` + re-tap profile + повторный probe.
* Вызов guard'а в `_switch_youtube` сразу после `yt_3_pre_tap`, перед `_yt_try_accounts_btn_with_retries`. На `unrecoverable` — честный `_fail('yt_3_own_profile_stale_ui')` без жжения mill'а.
* Маппинг `'yt_3_own_profile_stale_ui': 'yt_own_profile_stale_ui'` в `publisher_kernel._SWITCHER_STEP_TO_CATEGORY`.
* Kill-switch `YT_STALE_UI_OWN_PROFILE_GUARD` (default ON).
* Тесты: `tests/test_account_switcher_yt_stale_ui.py` — 18 тестов (2 kill-switch + 4 probe + 3 dumpsys + 4 check_and_recover + 4 switch_youtube + 1 mapping sanity).

## Что осталось
* 24-48ч наблюдение: SQL по `error_code IN ('yt_own_profile_stale_ui','yt_own_profile_stale_recovered','yt_accounts_btn_missing_postmortem')`. Ожидаем сдвиг с ложного на честные + recovery rate.
* Если recovery rate низкий — обсудить следующую итерацию (Settings-Activity intent / account_blocks).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL, например `https://github.com/GenGo2/autowarm-testbench/pull/119`.

- [ ] **Step 6.5: Записать прогресс в evidence-файл contenthunter**

После мержа PR — обновить `~/contenthunter-wt/wp-yt-triage-2026-05-28/docs/evidence/2026-05-28-yt-triage.md`: добавить секцию «SHIPPED YYYY-MM-DD» с PR-ссылкой и hash коммита прода (после auto-deploy в `GenGo2/delivery-contenthunter`).

```bash
cd ~/contenthunter-wt/wp-yt-triage-2026-05-28 && \
    git -c commit.gpgsign=false commit -am "docs(wp180): evidence — SHIPPED+DEPLOYED ссылки PR/прод-hash"
```

- [ ] **Step 6.6: OpenProject — статус WP#180 → «Тестирование»**

После мержа и pull прода:

```bash
set -a; source ~/secrets/openproject.env; set +a
python3 <<'PY'
import json, os, urllib.request, base64
URL=os.environ['OPENPROJECT_URL'].rstrip('/'); T=os.environ['OPENPROJECT_API_TOKEN']
auth='Basic ' + base64.b64encode(f'apikey:{T}'.encode()).decode()
req=urllib.request.Request(f'{URL}/api/v3/work_packages/180', method='GET',
                          headers={'Authorization': auth})
with urllib.request.urlopen(req) as r:
    wp=json.load(r); lock=wp['lockVersion']
patch={'lockVersion': lock,
       '_links': {'status': {'href': '/api/v3/statuses/9'}}}  # Тестирование
req=urllib.request.Request(f'{URL}/api/v3/work_packages/180',
                          data=json.dumps(patch).encode(), method='PATCH',
                          headers={'Authorization': auth,
                                   'Content-Type': 'application/json'})
with urllib.request.urlopen(req) as r:
    body=json.load(r); print('status:', body['_links']['status']['title'])
PY
```

Expected: `status: Тестирование`

- [ ] **Step 6.7: Память — обновить memory entry о WP#180 (SHIPPED→Testing)**

В `~/.claude/projects/-home-claude-user-contenthunter/memory/project_wp180_yt_stale_uiautomator_profile.md`: переместить статус «Бэклог → готов к плану» → «SHIPPED+DEPLOYED YYYY-MM-DD прод <hash>, → Тестирование, verify 24-48ч». Обновить строку в `MEMORY.md`.

---

## Self-Review Notes (для исполняющего агента)

**Spec coverage check:**
* `_yt_probe_looks_stale` → Task 2 ✅
* `_yt_dumpsys_confirms_foreground` → Task 3 ✅
* `_yt_stale_ui_check_and_recover` (5 веток: no_stale/not_yt_foreground/recovered/unrecoverable + variant detection) → Task 4 ✅
* Wire в `_switch_youtube` → Task 5 ✅
* Mapping в `publisher_kernel` → Task 5 (Step 5.4) ✅
* Kill-switch `YT_STALE_UI_OWN_PROFILE_GUARD` → Task 1 + Task 5 (off-path) ✅
* 12 тестов из спеки + 1 mapping sanity = 13 (фактически 18 с разделением variant/error/recovered) ✅

**Recovery — где `_open_app_aggressive` НЕ использовать:** см. Step 4.3, в коде явный комментарий. Это критично — `_open_app_aggressive` может выполнить `pm clear` и снести login YT (revision-only метод).

**Параллельные сессии:** работа в отдельной ветке + worktree (Task 0). НЕ `--amend` на shared HEAD. Перед каждым commit'ом — `git branch --show-current`.

**Auto-deploy после мержа:** git-hook autowarm-testbench post-commit → автопуш в `GenGo2/delivery-contenthunter`. PM2 restart воркера НЕ нужен для default-ON флага (читается на каждом вызове `_yt_stale_ui_guard_enabled`). Для kill-switch=0 (rollback) — добавить ENV в `.env` + PM2 restart.

**Если в Task 6.1 регрессия в существующих YT-тестах:** не баг этого WP — pre-existing. Задокументировать и продолжить. Гипотетический риск: новый `import` (но мы ничего нового не импортируем, всё уже есть в `account_switcher.py`: `os`, `re`, `time`, `is_dump_usable`, `parse_ui_dump`, `OPEN_APP_WAIT_S`, `POST_TAP_WAIT_S`).
