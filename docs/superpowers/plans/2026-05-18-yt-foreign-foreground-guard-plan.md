# YT foreign-foreground guard — Implementation Plan (WP #74 Round 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить foreign-foreground guard в YouTube publisher: после `_normalize_yt_state_pre_upload` и перед `_select_gallery_video` fail-fast'ом detect'ить чужой пакет на foreground (Samsung Account ForceLogin и др.) и пытаться сбросить через escalation Skip-tap → BACK×2 → force-stop+relaunch.

**Architecture:** Один новый метод `_dismiss_foreign_foreground` в `YouTubeMixin` (publisher_youtube.py). Allowlist YT/permission-controller, blocklist системных пакетов. Два checkpoint'а интеграции с 1-уровневой retry-рекурсией в gallery select. Env-flag kill-switch.

**Tech Stack:** Python 3, pytest, unittest.mock, Android adb (через `self.adb`/`self.dump_ui`/`self.tap_element` proxy-методы публикатора).

**Source spec:** `docs/superpowers/specs/2026-05-18-yt-foreign-foreground-guard-design.md` (этот же worktree).

**Repo for implementation:** `/home/claude-user/autowarm-testbench` (autowarm-testbench, ветка `feat/yt-foreign-fg-guard-20260518`). НЕ репо контенхантера, где лежит этот план.

**Codebase landmarks:**
- `publisher_youtube.py:28` — `class YouTubeMixin`
- `publisher_youtube.py:617-761` — `_select_gallery_video` (Шаг 6 publish_youtube_short, добавляем checkpoint #2 ПЕРЕД fail-fast emit'ом на ~line 720)
- `publisher_youtube.py:764-810` — `_normalize_yt_state_pre_upload` (Round 1, добавляем checkpoint #1 в самый конец)
- `tests/test_publisher_youtube_state_normalize.py:19-37` — `_StubPub(YouTubeMixin)` stub для unit-тестов

---

## Task 0: Setup — создание worktree autowarm-testbench

**Files:**
- Внешний (вне репо): create worktree at `/home/claude-user/autowarm-testbench-feat-yt-foreign-fg-guard-20260518`

- [ ] **Step 1: Создать новую feature-ветку и worktree**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add -b feat/yt-foreign-fg-guard-20260518 \
    /home/claude-user/autowarm-testbench-feat-yt-foreign-fg-guard-20260518 \
    origin/main
cd /home/claude-user/autowarm-testbench-feat-yt-foreign-fg-guard-20260518
git status
```

Expected: `On branch feat/yt-foreign-fg-guard-20260518`, ahead 0/0, clean tree, последний коммит = текущий main HEAD.

- [ ] **Step 2: Baseline — все relevant тесты зелёные ДО изменений**

```bash
pytest tests/test_publisher_youtube_state_normalize.py tests/test_publisher_youtube_picker.py -v 2>&1 | tail -30
```

Expected: все тесты PASS (если что-то падает на baseline — это pre-existing, отметь, но не чини в рамках этого плана).

---

## Task 1: Helper-функция parse топ-активности

**Files:**
- Create: `tests/test_publisher_youtube_foreign_foreground.py`
- Modify: `publisher_youtube.py` — добавить module-level функцию `_parse_top_resumed_activity` рядом с другими module-level хелперами (поищи где они)

- [ ] **Step 1: Создать тест-файл с тестами парсера**

```python
# tests/test_publisher_youtube_foreign_foreground.py
"""Тесты для foreign-foreground guard — WP #74 Round 2."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_youtube import _parse_top_resumed_activity  # noqa: E402


class TestParseTopResumedActivity:
    def test_extracts_pkg_and_activity_from_full_record(self):
        line = ('topResumedActivity=ActivityRecord{885aae7 u0 '
                'com.sec.android.app.samsungapps/'
                '.initialization.ForceLoginSamungAccountActivity t1379}')
        pkg, act = _parse_top_resumed_activity(line)
        assert pkg == 'com.sec.android.app.samsungapps'
        assert act == 'initialization.ForceLoginSamungAccountActivity'

    def test_extracts_pkg_and_activity_youtube(self):
        line = ('topResumedActivity=ActivityRecord{abc u0 '
                'com.google.android.youtube/'
                '.app.honeycomb.Shell$HomeActivity t100}')
        pkg, act = _parse_top_resumed_activity(line)
        assert pkg == 'com.google.android.youtube'
        assert act == 'app.honeycomb.Shell$HomeActivity'

    def test_handles_empty(self):
        assert _parse_top_resumed_activity('') == (None, None)

    def test_handles_malformed(self):
        assert _parse_top_resumed_activity('garbage') == (None, None)

    def test_handles_no_slash(self):
        line = 'topResumedActivity=ActivityRecord{abc u0 com.foo t100}'
        assert _parse_top_resumed_activity(line) == (None, None)
```

- [ ] **Step 2: Запустить тесты — должны fail (ImportError)**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name '_parse_top_resumed_activity' from 'publisher_youtube'`.

- [ ] **Step 3: Реализовать `_parse_top_resumed_activity` в `publisher_youtube.py`**

Сначала найди удобное место для module-level хелпера:

```bash
grep -n "^def \|^import re" publisher_youtube.py | head -10
```

Добавь функцию после блока imports (если есть module-level def'ы — рядом с ними; если нет — сразу перед `class YouTubeMixin`):

```python
import re as _re_top  # если re уже импортирован под другим именем — используй существующий

_TOP_RESUMED_RE = re.compile(
    r'topResumedActivity=ActivityRecord\{[^}]*?\s+([\w.]+)/([\w.$]+)'
)


def _parse_top_resumed_activity(raw: str) -> tuple[str | None, str | None]:
    """Распарсить вывод `dumpsys activity activities | grep topResumedActivity`.

    Returns (package, activity) или (None, None) если строка пустая/некорректная.
    Активность без leading dot — нормализуем (Android dumpsys пишет
    `com.foo/.bar.Baz`, регулярка хватает `bar.Baz`).
    """
    if not raw:
        return (None, None)
    m = _TOP_RESUMED_RE.search(raw)
    if not m:
        return (None, None)
    return (m.group(1), m.group(2))
```

Удали `as _re_top` если `re` уже импортирован — это была защита от collision.

- [ ] **Step 4: Запустить тесты — все PASS**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py::TestParseTopResumedActivity -v 2>&1 | tail -15
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_foreign_foreground.py
git commit -m "feat(yt): parser для topResumedActivity (WP #74 Round 2 task 1)"
```

---

## Task 2: Skeleton `_dismiss_foreign_foreground` — probe + allowlist (no escalation)

**Files:**
- Modify: `publisher_youtube.py` — добавить метод `_dismiss_foreign_foreground` в `YouTubeMixin` рядом с `_normalize_yt_state_pre_upload`
- Modify: `tests/test_publisher_youtube_foreign_foreground.py` — добавить `_StubPub` + первые 2 теста

- [ ] **Step 1: Добавить stub + тесты для allowlist-пути**

В конец `tests/test_publisher_youtube_foreign_foreground.py`:

```python
from unittest.mock import MagicMock  # noqa: E402

from publisher_youtube import YouTubeMixin  # noqa: E402


class _StubPub(YouTubeMixin):
    """Min stub для unit-тестов foreign-foreground guard.

    Расширен из `_StubPub` в test_publisher_youtube_state_normalize.py
    добавлением `_save_debug_artifacts` (нужен для checkpoint #2).
    """
    def __init__(self, *, dumpsys_responses=None, tap_returns=None):
        self.platform = 'youtube'
        self.platform_cfg = {'package': 'com.google.android.youtube'}
        self.ensure_unlocked = MagicMock(return_value=True)
        self.dump_ui = MagicMock(return_value='<hierarchy></hierarchy>')
        self.set_step = MagicMock()
        self.log_event = MagicMock()
        self._save_debug_artifacts = MagicMock()

        # dumpsys_responses: list of strings возвращаются по очереди для
        # каждого вызова self.adb с 'topResumedActivity' в команде.
        # Прочие adb-вызовы возвращают пустую строку.
        self._dumpsys = list(dumpsys_responses or [])
        self._dumpsys_idx = 0
        self.adb = MagicMock(side_effect=self._adb_side_effect)

        # tap_returns: bool-список для tap_element.
        self._tap_returns = list(tap_returns or [])
        self._tap_idx = 0
        self.tap_element = MagicMock(side_effect=self._tap_side_effect)

    def _adb_side_effect(self, cmd, *args, **kwargs):
        if 'topResumedActivity' in cmd and self._dumpsys_idx < len(self._dumpsys):
            r = self._dumpsys[self._dumpsys_idx]
            self._dumpsys_idx += 1
            return r
        return ''

    def _tap_side_effect(self, ui, patterns, **kw):
        if self._tap_idx < len(self._tap_returns):
            r = self._tap_returns[self._tap_idx]
            self._tap_idx += 1
            return r
        return False


def _yt_dumpsys(activity='com.google.android.youtube/.app.honeycomb.Shell$HomeActivity'):
    return f'topResumedActivity=ActivityRecord{{abc u0 {activity} t1}}'


def _samsung_dumpsys():
    return ('topResumedActivity=ActivityRecord{885aae7 u0 '
            'com.sec.android.app.samsungapps/'
            '.initialization.ForceLoginSamungAccountActivity t1379}')


class TestDismissForeignForegroundAllowlist:
    def test_youtube_foreground_returns_not_foreign(self):
        pub = _StubPub(dumpsys_responses=[_yt_dumpsys()])
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['foreign_detected'] is False
        assert r['top_package'] == 'com.google.android.youtube'
        assert r['recovered'] is False
        assert r['escalation_steps'] == []
        assert r['unrecoverable_reason'] is None

    def test_permissioncontroller_in_allowlist(self):
        line = ('topResumedActivity=ActivityRecord{xyz u0 '
                'com.android.permissioncontroller/.permission.ui.GrantActivity t2}')
        pub = _StubPub(dumpsys_responses=[line])
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['foreign_detected'] is False
        assert r['top_package'] == 'com.android.permissioncontroller'

    def test_probe_failed_when_dumpsys_empty(self):
        pub = _StubPub(dumpsys_responses=[''])
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['foreign_detected'] is False
        assert r['unrecoverable_reason'] == 'probe_failed'
        # log_event 'yt_foreign_foreground_probe_failed' эмитится
        cats = [c.kwargs.get('meta', {}).get('category', '')
                for c in pub.log_event.call_args_list]
        assert 'yt_foreign_foreground_probe_failed' in cats
```

- [ ] **Step 2: Запустить — должны fail (`_dismiss_foreign_foreground` не существует)**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py::TestDismissForeignForegroundAllowlist -v 2>&1 | tail -10
```

Expected: AttributeError / no attribute `_dismiss_foreign_foreground`.

- [ ] **Step 3: Реализовать skeleton в `YouTubeMixin`**

В `publisher_youtube.py` добавь module-level константы возле `_parse_top_resumed_activity` (after Task 1):

```python
YT_FOREGROUND_ALLOWLIST = frozenset({
    'com.google.android.youtube',
    'com.google.android.youtube.tv',
    'com.android.permissioncontroller',
    'com.google.android.permissioncontroller',
    'com.samsung.android.permissioncontroller',
})

FOREIGN_FORCE_STOP_BLOCKLIST = frozenset({
    'android',
    'com.android.systemui',
    'com.android.settings',
    'com.google.android.gms',
    'com.google.android.packageinstaller',
})

FOREIGN_FOREGROUND_SKIP_KEYS = [
    'Закрыть', 'Отмена', 'Cancel', 'Не сейчас', 'Не сегодня',
    'Позже', 'Later', 'Skip', 'Пропустить', 'Не входить',
    'Нет, спасибо', 'No thanks',
]
```

В `class YouTubeMixin` сразу ПОСЛЕ `_normalize_yt_state_pre_upload` (примерно после line 810 в текущем файле) добавь skeleton:

```python
    def _dismiss_foreign_foreground(
        self, *, source: str, allow_recovery: bool = True,
    ) -> dict:
        """Detect+dismiss чужого пакета на foreground (WP #74 Round 2).

        После `_normalize_yt_state_pre_upload` чужой пакет (Samsung Account
        ForceLogin, Galaxy Store update, etc.) может перехватить foreground
        и блокировать YT upload-flow. Этот guard:
          1) probe `topResumedActivity`;
          2) если пакет в `YT_FOREGROUND_ALLOWLIST` — выход без действий;
          3) иначе escalation: skip-tap → BACK×2 → force-stop+relaunch
             (последний шаг блокирован для `FOREIGN_FORCE_STOP_BLOCKLIST`).

        Args:
          source: 'post_normalize' | 'pre_gallery_select_fail_fast' — для триажа.
          allow_recovery: False → detect+log only (kill-switch / dry-run).

        Returns:
          dict со схемой (см. design spec §2):
            {foreign_detected, top_package, top_activity, recovered,
             escalation_steps, unrecoverable_reason}
        """
        result = {
            'foreign_detected': False,
            'top_package': None,
            'top_activity': None,
            'recovered': False,
            'escalation_steps': [],
            'unrecoverable_reason': None,
        }
        # === Step 1: probe ===
        try:
            raw = self.adb(
                'dumpsys activity activities 2>/dev/null '
                '| grep -m1 "topResumedActivity"',
                timeout=5,
            ) or ''
        except Exception:
            raw = ''
        top_pkg, top_act = _parse_top_resumed_activity(raw)
        if not top_pkg:
            result['unrecoverable_reason'] = 'probe_failed'
            self.log_event(
                'info', 'yt_foreign_foreground_probe_failed',
                meta={'category': 'yt_foreign_foreground_probe_failed',
                      'source': source, 'raw': raw[:200]},
            )
            return result

        result['top_package'] = top_pkg
        result['top_activity'] = top_act

        # === Step 2: allowlist check ===
        if top_pkg in YT_FOREGROUND_ALLOWLIST:
            return result  # foreign_detected=False, тихо

        # FOREIGN DETECTED (escalation в следующих задачах)
        result['foreign_detected'] = True
        return result
```

- [ ] **Step 4: Запустить — все три теста PASS**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py::TestDismissForeignForegroundAllowlist -v 2>&1 | tail -15
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_foreign_foreground.py
git commit -m "feat(yt): skeleton _dismiss_foreign_foreground — probe+allowlist (WP #74 Round 2 task 2)"
```

---

## Task 3: Kill-switch + dry-run gate

**Files:**
- Modify: `publisher_youtube.py` — гейтинг в `_dismiss_foreign_foreground`
- Modify: `tests/test_publisher_youtube_foreign_foreground.py` — 2 теста

- [ ] **Step 1: Добавить тесты**

В тест-файл:

```python
import os  # noqa: E402


class TestForeignForegroundKillSwitch:
    def test_env_flag_disables_recovery(self, monkeypatch):
        monkeypatch.setenv('YT_FOREIGN_FOREGROUND_GUARD_DISABLE', '1')
        # Перезагрузить модуль чтобы env подхватился, если флаг читается на import.
        # Если читается каждый раз внутри метода — monkeypatch достаточно.
        pub = _StubPub(dumpsys_responses=[_samsung_dumpsys()])
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['foreign_detected'] is True
        assert r['recovered'] is False
        assert r['unrecoverable_reason'] == 'guard_disabled'
        assert r['escalation_steps'] == []
        # adb вызвался ровно один раз (probe), не было BACK/force-stop
        adb_cmds = [c.args[0] for c in pub.adb.call_args_list]
        assert len(adb_cmds) == 1
        assert 'topResumedActivity' in adb_cmds[0]
        # лог 'yt_foreign_foreground_detected' + 'yt_foreign_foreground_guard_disabled'
        cats = [c.kwargs.get('meta', {}).get('category', '')
                for c in pub.log_event.call_args_list]
        assert 'yt_foreign_foreground_detected' in cats
        assert 'yt_foreign_foreground_guard_disabled' in cats

    def test_allow_recovery_false_disables_recovery(self):
        pub = _StubPub(dumpsys_responses=[_samsung_dumpsys()])
        r = pub._dismiss_foreign_foreground(
            source='post_normalize', allow_recovery=False,
        )
        assert r['recovered'] is False
        assert r['unrecoverable_reason'] == 'guard_disabled'
```

- [ ] **Step 2: Запустить — оба fail**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py::TestForeignForegroundKillSwitch -v 2>&1 | tail -10
```

Expected: FAIL — нет `yt_foreign_foreground_detected` лога, `unrecoverable_reason` не выставлен.

- [ ] **Step 3: Расширить `_dismiss_foreign_foreground` гейтом**

Замени блок «FOREIGN DETECTED» в `_dismiss_foreign_foreground` на:

```python
        # FOREIGN DETECTED
        result['foreign_detected'] = True
        self.log_event(
            'info', 'yt_foreign_foreground_detected',
            meta={'category': 'yt_foreign_foreground_detected',
                  'source': source,
                  'top_package': top_pkg,
                  'top_activity': top_act},
        )

        # === Step 4: kill-switch / dry-run gate ===
        guard_disabled = (
            os.environ.get('YT_FOREIGN_FOREGROUND_GUARD_DISABLE') == '1'
            or not allow_recovery
        )
        if guard_disabled:
            result['unrecoverable_reason'] = 'guard_disabled'
            self.log_event(
                'info', 'yt_foreign_foreground_guard_disabled',
                meta={'category': 'yt_foreign_foreground_guard_disabled',
                      'source': source, 'top_package': top_pkg},
            )
            return result

        # Escalation — следующие задачи.
        return result
```

Убедись что `import os` есть на module-level (если нет — добавь в существующий import-блок).

- [ ] **Step 4: Запустить — оба теста + предыдущие 3 PASS**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py -v 2>&1 | tail -15
```

Expected: 5 passed (3 allowlist + 2 kill-switch).

- [ ] **Step 5: Commit**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_foreign_foreground.py
git commit -m "feat(yt): kill-switch + allow_recovery для foreign-fg guard (WP #74 Round 2 task 3)"
```

---

## Task 4: Escalation (a) — skip-tap

**Files:**
- Modify: `publisher_youtube.py`
- Modify: `tests/test_publisher_youtube_foreign_foreground.py`

- [ ] **Step 1: Добавить тест skip-tap success**

```python
class TestForeignForegroundEscalationSkipTap:
    def test_skip_tap_success_recovers(self):
        pub = _StubPub(
            dumpsys_responses=[_samsung_dumpsys(), _yt_dumpsys()],
            tap_returns=[True],  # skip-key matched, tap_element=True
        )
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['foreign_detected'] is True
        assert r['recovered'] is True
        assert r['escalation_steps'] == ['skip_tap']
        # tap_element вызван с FOREIGN_FOREGROUND_SKIP_KEYS
        tap_call = pub.tap_element.call_args
        keys = tap_call.args[1]
        assert 'Не входить' in keys and 'Cancel' in keys

    def test_skip_tap_logged_as_recovered(self):
        pub = _StubPub(
            dumpsys_responses=[_samsung_dumpsys(), _yt_dumpsys()],
            tap_returns=[True],
        )
        pub._dismiss_foreign_foreground(source='post_normalize')
        cats = [c.kwargs.get('meta', {}).get('category', '')
                for c in pub.log_event.call_args_list]
        assert 'yt_foreign_foreground_recovered' in cats
```

- [ ] **Step 2: Запустить — оба fail (`escalation_steps == []`)**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py::TestForeignForegroundEscalationSkipTap -v 2>&1 | tail -10
```

- [ ] **Step 3: Реализовать skip-tap + recovered emit**

Добавь helper-метод в `YouTubeMixin` для re-probe (DRY между задачами 4-6):

```python
    def _foreign_reprobe(self) -> tuple[str | None, str | None]:
        """Повторный probe topResumedActivity между шагами escalation."""
        try:
            raw = self.adb(
                'dumpsys activity activities 2>/dev/null '
                '| grep -m1 "topResumedActivity"',
                timeout=5,
            ) or ''
        except Exception:
            raw = ''
        return _parse_top_resumed_activity(raw)
```

Замени блок «Escalation — следующие задачи» на:

```python
        # === Step 5: escalation (a) — skip-tap ===
        try:
            ui = self.dump_ui()
        except Exception:
            ui = ''
        try:
            tapped = self.tap_element(
                ui, FOREIGN_FOREGROUND_SKIP_KEYS, clickable_only=True,
            )
        except Exception:
            tapped = False
        if tapped:
            time.sleep(2)
            result['escalation_steps'].append('skip_tap')
            new_pkg, _ = self._foreign_reprobe()
            if new_pkg and new_pkg in YT_FOREGROUND_ALLOWLIST:
                result['recovered'] = True
                self._emit_foreign_foreground_outcome(result, source, new_pkg)
                return result

        # Дальнейшие escalations — следующие задачи.
        return result

    def _emit_foreign_foreground_outcome(
        self, result: dict, source: str, final_top_pkg: str | None,
    ) -> None:
        """Emit `..._recovered` или `..._unrecoverable` event с meta."""
        if result['recovered']:
            self.log_event(
                'info', 'yt_foreign_foreground_recovered',
                meta={'category': 'yt_foreign_foreground_recovered',
                      'platform': self.platform,
                      'source': source,
                      'top_package': result['top_package'],
                      'top_activity': result['top_activity'],
                      'escalation_steps': list(result['escalation_steps']),
                      'final_top_package': final_top_pkg},
            )
        else:
            cat = 'yt_foreign_foreground_unrecoverable'
            if result['unrecoverable_reason'] == 'system_pkg_blocklist':
                cat = 'yt_foreign_foreground_unrecoverable_blocklist'
            self.log_event(
                'error', 'YT: foreign foreground unrecoverable',
                meta={'category': cat,
                      'platform': self.platform,
                      'source': source,
                      'top_package': result['top_package'],
                      'top_activity': result['top_activity'],
                      'escalation_steps': list(result['escalation_steps']),
                      'final_top_package': final_top_pkg,
                      'unrecoverable_reason': result['unrecoverable_reason']},
            )
```

Убедись что `import time` есть на module-level.

- [ ] **Step 4: Запустить — все 7 тестов PASS**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py -v 2>&1 | tail -15
```

- [ ] **Step 5: Commit**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_foreign_foreground.py
git commit -m "feat(yt): escalation (a) skip-tap для foreign-fg guard (WP #74 Round 2 task 4)"
```

---

## Task 5: Escalation (b) — BACK×2 с re-probe между шагами

**Files:**
- Modify: `publisher_youtube.py`
- Modify: `tests/test_publisher_youtube_foreign_foreground.py`

- [ ] **Step 1: Добавить тесты BACK×1 и BACK×2**

```python
class TestForeignForegroundEscalationBack:
    def test_back_x1_success_recovers(self):
        # skip-tap не сработал (tap_returns=[False]), BACK×1 вернул YT
        pub = _StubPub(
            dumpsys_responses=[_samsung_dumpsys(), _yt_dumpsys()],
            tap_returns=[False],
        )
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['recovered'] is True
        assert r['escalation_steps'] == ['back_x1']
        # KEYCODE_BACK был отправлен ровно один раз
        adb_cmds = [c.args[0] for c in pub.adb.call_args_list]
        back_cmds = [c for c in adb_cmds if 'KEYCODE_BACK' in c]
        assert len(back_cmds) == 1

    def test_back_x2_success_recovers(self):
        # skip=False, back#1 не помог (samsung всё ещё), back#2 → YT
        pub = _StubPub(
            dumpsys_responses=[
                _samsung_dumpsys(),  # initial probe
                _samsung_dumpsys(),  # after back_x1
                _yt_dumpsys(),       # after back_x2
            ],
            tap_returns=[False],
        )
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['recovered'] is True
        assert r['escalation_steps'] == ['back_x1', 'back_x2']
        adb_cmds = [c.args[0] for c in pub.adb.call_args_list]
        back_cmds = [c for c in adb_cmds if 'KEYCODE_BACK' in c]
        assert len(back_cmds) == 2
```

- [ ] **Step 2: Запустить — оба fail (BACK не реализован)**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py::TestForeignForegroundEscalationBack -v 2>&1 | tail -10
```

- [ ] **Step 3: Реализовать BACK loop**

В `_dismiss_foreign_foreground` замени `return result` (последняя строка перед `_emit_foreign_foreground_outcome` method-def) на:

```python
        # === Step 6: escalation (b) — BACK ×2 ===
        for i in (1, 2):
            try:
                self.adb('input keyevent KEYCODE_BACK')
            except Exception:
                pass
            time.sleep(1)
            result['escalation_steps'].append(f'back_x{i}')
            new_pkg, _ = self._foreign_reprobe()
            if new_pkg and new_pkg in YT_FOREGROUND_ALLOWLIST:
                result['recovered'] = True
                self._emit_foreign_foreground_outcome(result, source, new_pkg)
                return result

        # Дальнейший escalation (c) — следующая задача.
        return result
```

- [ ] **Step 4: Запустить — все 9 тестов PASS**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py -v 2>&1 | tail -20
```

- [ ] **Step 5: Commit**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_foreign_foreground.py
git commit -m "feat(yt): escalation (b) BACK×2 для foreign-fg guard (WP #74 Round 2 task 5)"
```

---

## Task 6: Escalation (c) — force-stop+relaunch с blocklist

**Files:**
- Modify: `publisher_youtube.py`
- Modify: `tests/test_publisher_youtube_foreign_foreground.py`

- [ ] **Step 1: Добавить тесты для force-stop success, still_foreign, и blocklist**

```python
class TestForeignForegroundEscalationForceStop:
    def test_force_stop_relaunch_success(self):
        pub = _StubPub(
            dumpsys_responses=[
                _samsung_dumpsys(),  # initial
                _samsung_dumpsys(),  # after back_x1
                _samsung_dumpsys(),  # after back_x2
                _yt_dumpsys(),       # after force-stop+relaunch
            ],
            tap_returns=[False],
        )
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['recovered'] is True
        assert 'force_stop_and_relaunch' in r['escalation_steps']
        adb_cmds = [c.args[0] for c in pub.adb.call_args_list]
        assert any('am force-stop com.sec.android.app.samsungapps' in c
                   for c in adb_cmds), adb_cmds
        assert any('am start' in c and 'LAUNCHER' in c
                   and 'com.google.android.youtube' in c
                   for c in adb_cmds), adb_cmds

    def test_still_foreign_after_all_escalations(self):
        # ВСЕ probe'ы возвращают samsung → recovery не удалось
        pub = _StubPub(
            dumpsys_responses=[_samsung_dumpsys()] * 5,
            tap_returns=[False],
        )
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['recovered'] is False
        assert r['unrecoverable_reason'] == 'still_foreign'
        assert 'force_stop_and_relaunch' in r['escalation_steps']
        cats = [c.kwargs.get('meta', {}).get('category', '')
                for c in pub.log_event.call_args_list]
        assert 'yt_foreign_foreground_unrecoverable' in cats

    def test_blocklist_skips_force_stop(self):
        # 'android' пакет на foreground — НЕЛЬЗЯ force-stop
        line = ('topResumedActivity=ActivityRecord{xyz u0 '
                'android/.system.SystemDialog t9}')
        pub = _StubPub(
            dumpsys_responses=[line] * 5,
            tap_returns=[False],
        )
        r = pub._dismiss_foreign_foreground(source='post_normalize')
        assert r['recovered'] is False
        assert r['unrecoverable_reason'] == 'system_pkg_blocklist'
        # force_stop НЕ должен быть в escalation_steps
        assert 'force_stop_and_relaunch' not in r['escalation_steps']
        adb_cmds = [c.args[0] for c in pub.adb.call_args_list]
        assert not any('am force-stop android' in c for c in adb_cmds), adb_cmds
        cats = [c.kwargs.get('meta', {}).get('category', '')
                for c in pub.log_event.call_args_list]
        assert 'yt_foreign_foreground_unrecoverable_blocklist' in cats
```

- [ ] **Step 2: Запустить — все три fail**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py::TestForeignForegroundEscalationForceStop -v 2>&1 | tail -10
```

- [ ] **Step 3: Реализовать escalation (c) + final outcome**

В `_dismiss_foreign_foreground` замени последний `return result` (тот что после `for i in (1, 2)`) на:

```python
        # === Step 7: escalation (c) — force-stop foreign + relaunch YT ===
        if top_pkg in FOREIGN_FORCE_STOP_BLOCKLIST:
            result['unrecoverable_reason'] = 'system_pkg_blocklist'
            self._emit_foreign_foreground_outcome(result, source, top_pkg)
            return result

        yt_pkg = self.platform_cfg['package']
        try:
            self.adb(f'am force-stop {top_pkg}')
        except Exception:
            pass
        time.sleep(1.5)
        try:
            self.adb(
                f'am start -p {yt_pkg} '
                f'-a android.intent.action.MAIN '
                f'-c android.intent.category.LAUNCHER'
            )
        except Exception:
            pass
        time.sleep(3)
        result['escalation_steps'].append('force_stop_and_relaunch')

        # === Step 8: final probe & emit ===
        final_pkg, _ = self._foreign_reprobe()
        if final_pkg and final_pkg in YT_FOREGROUND_ALLOWLIST:
            result['recovered'] = True
        else:
            result['unrecoverable_reason'] = 'still_foreign'
        self._emit_foreign_foreground_outcome(result, source, final_pkg)
        return result
```

- [ ] **Step 4: Запустить — все 12 тестов PASS**

```bash
pytest tests/test_publisher_youtube_foreign_foreground.py -v 2>&1 | tail -25
```

Expected: 5 parser + 3 allowlist + 2 kill-switch + 2 skip-tap + 2 back + 3 force-stop = 12 passed (один из тестов parser-класса — 5; и skip-tap класс — 2, выше я писал 2). Если число расходится — пересчитай.

- [ ] **Step 5: Commit**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_foreign_foreground.py
git commit -m "feat(yt): escalation (c) force-stop+relaunch с blocklist (WP #74 Round 2 task 6)"
```

---

## Task 7: Checkpoint #1 — интеграция в `_normalize_yt_state_pre_upload`

**Files:**
- Modify: `publisher_youtube.py:764-810` — добавить вызов guard'а в конце метода
- Modify: `tests/test_publisher_youtube_state_normalize.py` — +1 integration test

- [ ] **Step 1: Добавить integration test**

В конец класса (или нового класса) в `tests/test_publisher_youtube_state_normalize.py`:

```python
class TestNormalizeCallsForeignForegroundGuard:
    def test_calls_guard_with_source_post_normalize(self):
        pub = _StubPub()
        pub._dismiss_foreign_foreground = MagicMock(return_value={
            'foreign_detected': False, 'top_package': None,
            'top_activity': None, 'recovered': False,
            'escalation_steps': [], 'unrecoverable_reason': None,
        })
        pub._normalize_yt_state_pre_upload()
        pub._dismiss_foreign_foreground.assert_called_once_with(
            source='post_normalize',
        )
```

- [ ] **Step 2: Запустить — fail (метод не вызывается)**

```bash
pytest tests/test_publisher_youtube_state_normalize.py::TestNormalizeCallsForeignForegroundGuard -v 2>&1 | tail -10
```

Expected: `AssertionError: Expected _dismiss_foreign_foreground to have been called once. Called 0 times.`

- [ ] **Step 3: Добавить вызов в `_normalize_yt_state_pre_upload`**

В `publisher_youtube.py`, СРАЗУ ПОСЛЕ существующего `self.log_event('info', 'yt_pre_upload_state_normalized', ...)` (примерно line 810):

```python
        # WP #74 Round 2 (2026-05-18): foreign-foreground guard.
        # Если после force-stop+LAUNCHER чужой пакет перехватил foreground —
        # пытаемся вежливо дисмиссить. Non-blocking: если recovery failed,
        # _select_gallery_video downstream поймает и сделает fail-fast.
        self._dismiss_foreign_foreground(source='post_normalize')
```

- [ ] **Step 4: Запустить — integration test + предыдущие state-normalize тесты PASS**

```bash
pytest tests/test_publisher_youtube_state_normalize.py -v 2>&1 | tail -15
```

Все должны быть PASS (новый тест + старые не сломаны).

- [ ] **Step 5: Commit**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_state_normalize.py
git commit -m "feat(yt): checkpoint #1 — guard в _normalize_yt_state_pre_upload (WP #74 Round 2 task 7)"
```

---

## Task 8: Checkpoint #2 — интеграция в `_select_gallery_video` с 1-retry

**Files:**
- Modify: `publisher_youtube.py:617-761` — добавить `_foreign_retry_left` param + guard call + meta enrichment
- Modify: `tests/test_publisher_youtube_picker.py` — +3 integration tests

- [ ] **Step 1: Изучить существующую структуру `test_publisher_youtube_picker.py`**

```bash
head -60 tests/test_publisher_youtube_picker.py
```

Цель — понять какой stub он использует. Если есть свой `_PickerStub` отличный от `_StubPub` — расширь по тому же образцу с `_save_debug_artifacts`. Если использует общий — переиспользуй.

- [ ] **Step 2: Добавить 3 integration теста в `tests/test_publisher_youtube_picker.py`**

(Адаптируй stub-инициализацию под пример, который ты увидел в Step 1. Ниже — шаблон.)

```python
from unittest.mock import MagicMock

# Если в файле уже есть _PickerStub / _StubPub — переиспользуй его, добавив
# _save_debug_artifacts = MagicMock() если такого поля нет.


class TestSelectGalleryVideoForeignForegroundGuard:
    def _make_stub(self, *, foreign_returns):
        """foreign_returns: list[dict] — последовательно возвращаемые из
        _dismiss_foreign_foreground при последовательных вызовах."""
        pub = _PickerStub()  # или _StubPub — что есть в файле
        pub._save_debug_artifacts = MagicMock()
        # parse loop должен возвращать пустой UI (видео не находим)
        pub.dump_ui = MagicMock(return_value='<hierarchy></hierarchy>')
        pub.adb = MagicMock(return_value='')
        # ВНИМАНИЕ: dismiss_location_dialog тоже может быть нужен мок
        pub.dismiss_location_dialog = MagicMock(return_value=False)
        pub.tap_element = MagicMock(return_value=False)
        pub.adb_tap = MagicMock()
        pub.log_event = MagicMock()
        pub._dismiss_foreign_foreground = MagicMock(side_effect=foreign_returns)
        return pub

    def _no_foreign(self):
        return {'foreign_detected': False, 'top_package': None,
                'top_activity': None, 'recovered': False,
                'escalation_steps': [], 'unrecoverable_reason': None}

    def _foreign_recovered(self):
        return {'foreign_detected': True,
                'top_package': 'com.sec.android.app.samsungapps',
                'top_activity': 'ForceLoginSamungAccountActivity',
                'recovered': True,
                'escalation_steps': ['skip_tap'],
                'unrecoverable_reason': None}

    def _foreign_unrecovered(self):
        return {'foreign_detected': True,
                'top_package': 'com.sec.android.app.samsungapps',
                'top_activity': 'ForceLoginSamungAccountActivity',
                'recovered': False,
                'escalation_steps': ['skip_tap', 'back_x1', 'back_x2',
                                     'force_stop_and_relaunch'],
                'unrecoverable_reason': 'still_foreign'}

    def test_calls_guard_before_fail_fast(self):
        pub = self._make_stub(foreign_returns=[self._no_foreign()])
        result = pub._select_gallery_video('/sdcard/test.mp4')
        assert result is False
        pub._dismiss_foreign_foreground.assert_called_with(
            source='pre_gallery_select_fail_fast',
        )

    def test_retries_once_after_recovery(self):
        # 1й guard: recovered → retry parse-loop; 2й guard: unrecovered → fail.
        pub = self._make_stub(foreign_returns=[
            self._foreign_recovered(),
            self._foreign_unrecovered(),
        ])
        result = pub._select_gallery_video('/sdcard/test.mp4')
        assert result is False
        # guard вызвался 2 раза
        assert pub._dismiss_foreign_foreground.call_count == 2
        # event 'yt_gallery_retry_after_foreign_recovery' эмитнут
        cats = [c.kwargs.get('meta', {}).get('category', '')
                for c in pub.log_event.call_args_list]
        assert 'yt_gallery_retry_after_foreign_recovery' in cats
        # fail-fast meta содержит foreign_foreground_retry_exhausted=True
        fail_meta = next(
            c.kwargs['meta'] for c in pub.log_event.call_args_list
            if c.kwargs.get('meta', {}).get('category')
               == 'yt_gallery_no_video_candidate'
        )
        assert fail_meta.get('foreign_foreground_retry_exhausted') is True

    def test_no_retry_when_unrecovered(self):
        pub = self._make_stub(foreign_returns=[self._foreign_unrecovered()])
        result = pub._select_gallery_video('/sdcard/test.mp4')
        assert result is False
        # guard вызвался ровно 1 раз (retry НЕ запустился)
        assert pub._dismiss_foreign_foreground.call_count == 1
        # fail-fast meta содержит foreign_foreground_unrecoverable_reason
        fail_meta = next(
            c.kwargs['meta'] for c in pub.log_event.call_args_list
            if c.kwargs.get('meta', {}).get('category')
               == 'yt_gallery_no_video_candidate'
        )
        assert fail_meta.get('foreign_foreground_detected') is True
        assert fail_meta.get('foreign_foreground_unrecoverable_reason') \
            == 'still_foreign'
```

- [ ] **Step 3: Запустить — все 3 fail**

```bash
pytest tests/test_publisher_youtube_picker.py::TestSelectGalleryVideoForeignForegroundGuard -v 2>&1 | tail -15
```

- [ ] **Step 4: Изменить сигнатуру `_select_gallery_video` и интегрировать guard**

В `publisher_youtube.py` line 617 поменяй сигнатуру:

```python
    def _select_gallery_video(
        self, remote_media_path: str,
        *, _foreign_retry_left: int = 1,
    ) -> bool:
```

Внутри метода (после parse-loop'а), ЗАМЕНИ блок `if not video_selected:` (текущие lines ~717-760) на следующий (СОХРАНЯЯ существующие top_act/cur_pkg probe'ы для back-compat):

```python
        if not video_selected:
            log.error('YouTube: видео не найдено в gallery picker — abort')

            # WP #74 Round 2: foreign-foreground guard перед fail-fast emit'ом.
            guard_result = self._dismiss_foreign_foreground(
                source='pre_gallery_select_fail_fast',
            )
            if guard_result['recovered'] and _foreign_retry_left > 0:
                log.info('  Gallery probe retry после foreign-foreground recovery')
                self.log_event(
                    'info', 'yt_gallery_retry_after_foreign_recovery',
                    meta={'category': 'yt_gallery_retry_after_foreign_recovery',
                          'foreign_top_package': guard_result['top_package'],
                          'escalation_steps':
                              list(guard_result['escalation_steps'])},
                )
                return self._select_gallery_video(
                    remote_media_path, _foreign_retry_left=0,
                )

            try:
                self._save_debug_artifacts('yt_gallery_no_video')
            except Exception:
                pass
            diag = [{'cx': it[4], 'cy': it[5], 'desc': (it[6] or '')[:120]}
                    for it in (last_all_items or [])[:10]]

            # Существующие top_act/cur_pkg для back-compat дашбордов
            top_act = ''
            try:
                _act_raw = self.adb(
                    'dumpsys activity activities 2>/dev/null '
                    '| grep -m1 "topResumedActivity"', timeout=5
                ) or ''
                top_act = _act_raw.strip()[:200]
            except Exception:
                pass
            cur_pkg = ''
            try:
                _pkg_raw = self.adb(
                    'dumpsys window 2>/dev/null '
                    '| grep -m1 "mCurrentFocus"', timeout=5
                ) or ''
                cur_pkg = _pkg_raw.strip()[:200]
            except Exception:
                pass

            meta = {
                'category': 'yt_gallery_no_video_candidate',
                'platform': self.platform,
                'step': 'yt_gallery_select',
                'all_clickable_count': len(last_all_items or []),
                'first_clickables': diag,
                'top_resumed_activity': top_act,
                'current_package': cur_pkg,
            }
            if guard_result['foreign_detected']:
                meta.update({
                    'foreign_foreground_detected': True,
                    'foreign_foreground_top_package':
                        guard_result['top_package'],
                    'foreign_foreground_top_activity':
                        guard_result['top_activity'],
                    'foreign_foreground_recovered':
                        guard_result['recovered'],
                    'foreign_foreground_unrecoverable_reason':
                        guard_result['unrecoverable_reason'],
                    'foreign_foreground_escalation_steps':
                        list(guard_result['escalation_steps']),
                })
                if _foreign_retry_left == 0:
                    meta['foreign_foreground_retry_exhausted'] = True
            self.log_event(
                'error', 'YT: видео не найдено в gallery picker — fail-fast',
                meta=meta,
            )
            return False
        return True
```

- [ ] **Step 5: Запустить тесты picker + полный пакет YouTube**

```bash
pytest tests/test_publisher_youtube_picker.py -v 2>&1 | tail -25
pytest tests/test_publisher_youtube_*.py -v 2>&1 | tail -30
```

Expected: 3 новых теста + старые picker-тесты + 12 foreign-fg + state-normalize тесты — ВСЕ PASS. Если старый picker-тест сломался от изменения сигнатуры — проверь, что caller `publish_youtube_short` (line 1503) НЕ передаёт `_foreign_retry_left` (он не должен — мы оставили default).

- [ ] **Step 6: Commit**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_picker.py
git commit -m "feat(yt): checkpoint #2 — guard+1retry в _select_gallery_video (WP #74 Round 2 task 8)"
```

---

## Task 9: Документация — `PUBLISH-NOTES.md`

**Files:**
- Modify: `PUBLISH-NOTES.md` — добавить раздел Feature flags

- [ ] **Step 1: Найти существующий раздел про feature flags / env-vars**

```bash
grep -n -i "feature flag\|env\b\|kill.switch\|disable" PUBLISH-NOTES.md | head -20
```

- [ ] **Step 2: Добавить запись про `YT_FOREIGN_FOREGROUND_GUARD_DISABLE`**

В существующий раздел (или создать новый «Feature flags» в конце документа):

```markdown
### `YT_FOREIGN_FOREGROUND_GUARD_DISABLE` (WP #74 Round 2, 2026-05-18)

Kill-switch для foreign-foreground guard'а в `publish_youtube_short`.

- `=1` → guard работает в detect-only режиме (логирует
  `yt_foreign_foreground_detected` + `..._guard_disabled`, но НЕ делает
  BACK / force-stop / relaunch).
- `unset` или любое другое значение → guard в полном escalation-режиме.

Включить на prod:

```bash
# через PM2 ecosystem env: { } либо
pm2 set autowarm:env.YT_FOREIGN_FOREGROUND_GUARD_DISABLE 1
pm2 restart 34 autowarm --update-env
```

Использовать только если guard сам начал регрессировать (false-positive
force-stop'ы легитимного foreground'а — крайне маловероятно, но flag есть).
```

- [ ] **Step 3: Commit**

```bash
git add PUBLISH-NOTES.md
git commit -m "docs(publish): YT_FOREIGN_FOREGROUND_GUARD_DISABLE flag (WP #74 Round 2 task 9)"
```

---

## Task 10: Local full-suite green check

**Files:** none (verification step)

- [ ] **Step 1: Прогнать ВЕСЬ pytest tests/ — нет collateral регрессий**

```bash
pytest tests/ 2>&1 | tail -20
```

Expected: only известные pre-existing fails (если есть из baseline в Task 0). Любой НОВЫЙ red — fix перед PR. Не игнорируй.

- [ ] **Step 2: Если есть новые failures — debug и fix перед PR**

Не двигаемся дальше с красным тестом.

---

## Task 11: Codex review раундами

**Files:** none (review step). Memory: `feedback_codex_review_specs` + `feedback_codex_sandbox_broken`.

- [ ] **Step 1: Прогнать codex review через stdin**

```bash
git diff origin/main..HEAD | codex review - 2>&1 | tail -100
```

- [ ] **Step 2: Применить P1 issues inline**

Если есть P1 — fix, commit с сообщением `fix(yt): codex review — <issue>`. Перезапустить Step 1. Повторять до 0 P1.

- [ ] **Step 3: Финальный pytest после review-фиксов**

```bash
pytest tests/test_publisher_youtube_*.py -v 2>&1 | tail -30
```

---

## Task 12: Live smoke на testbench

**Files:** none. Memory: `reference_testbench_smoke_paths`, `feedback_mock_proxy_drift`.

- [ ] **Step 1: Прогнать pytest на autowarm-testbench main checkout**

(Worktree — изолированная копия; чтобы поймать mock-drift cross-class, нужно прогнать на той же базе кода, что прод-testbench.)

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git checkout feat/yt-foreign-fg-guard-20260518
pytest tests/test_publisher_youtube_*.py -v 2>&1 | tail -30
git checkout main  # возврат на baseline после проверки
```

Expected: все зелёные. Если что-то upal — это mock-drift, fix в worktree и push заново.

- [ ] **Step 2: Synthetic foreign foreground на тестбенче**

```bash
# 1. Открыть Samsung Account ForceLogin (если устройство держит этот activity)
adb -s <testbench_serial> shell am start -n \
    com.sec.android.app.samsungapps/.initialization.ForceLoginSamungAccountActivity

# Если ForceLogin недоступен — fallback на любой third-party app:
adb -s <testbench_serial> shell am start -n \
    com.android.calculator2/.Calculator

# 2. Триггер YouTube Short publish из testbench UI
#    (создай задачу через autowarm-testbench frontend или подними напрямую через
#    psql INSERT INTO publish_queue)

# 3. После завершения — посмотреть events в DB:
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT jsonb_pretty(e)
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events) e
WHERE pt.id = <new_task_id>
  AND (e->'meta'->>'category') LIKE 'yt_foreign_foreground_%'
ORDER BY (e->>'ts');
"
```

Expected: появилось хотя бы одно `yt_foreign_foreground_detected` событие, плюс либо `..._recovered` либо `..._unrecoverable`.

- [ ] **Step 3: Happy-path smoke (чистый YT)**

Триггерни обычную YT публикацию БЕЗ synthetic foreign (state YT чистый). Проверь что:
- задача прошла успешно (статус `published`),
- в events НЕТ `yt_foreign_foreground_detected` (либо есть с `foreign_detected:False` от probe_failed),
- old happy-path не сломан.

- [ ] **Step 4: Документировать smoke evidence**

Создай `docs/evidence/2026-05-18-wp74-round2-smoke.md` в репо контенхантера (НЕ autowarm-testbench) с краткой выпиской smoke-результатов, task_id'ами, и кратким verdict'ом. Commit + push.

---

## Task 13: PR + merge + prod deploy

**Files:** none. Memory: `reference_autowarm_git_hook`, `feedback_subagent_force_push_risk`.

- [ ] **Step 1: Push ветки и создание PR**

```bash
cd /home/claude-user/autowarm-testbench-feat-yt-foreign-fg-guard-20260518
git push -u origin feat/yt-foreign-fg-guard-20260518
gh pr create --title "YT foreign-foreground guard — Round 2 (WP #74)" \
    --body "$(cat <<'EOF'
## Summary

WP #74 Round 2. Round 1 (PR #64) выкатил `_normalize_yt_state_pre_upload`
(force-stop YT + LAUNCHER + permission-tap). Task 6899 (2026-05-18) показал
новый root cause: `ForceLoginSamungAccountActivity` (Samsung Galaxy Store)
перехватил foreground — force-stop YT тут бессилен (чужой пакет).

## Changes

- `_dismiss_foreign_foreground` в `YouTubeMixin` — probe topResumedActivity,
  allowlist (YT + permissioncontrollers), escalation Skip-tap → BACK×2 →
  force-stop+relaunch (с blocklist системных пакетов).
- 2 checkpoint'а: хвост `_normalize_yt_state_pre_upload` (non-blocking) +
  перед fail-fast'ом в `_select_gallery_video` (с 1-retry).
- Зонтичный `error_code = yt_gallery_no_video_candidate` СОХРАНЁН для
  дашбордов; новые поля идут в `meta.foreign_foreground_*`.
- Env-flag kill-switch `YT_FOREIGN_FOREGROUND_GUARD_DISABLE=1`.

## Tests

- 12 unit-тестов нового `tests/test_publisher_youtube_foreign_foreground.py`.
- 1 integration в `test_publisher_youtube_state_normalize.py`.
- 3 integration в `test_publisher_youtube_picker.py`.
- Live smoke на тестбенче: см. `docs/evidence/2026-05-18-wp74-round2-smoke.md`.

## Spec / Plan

- Spec: `docs/superpowers/specs/2026-05-18-yt-foreign-foreground-guard-design.md`
- Plan: `docs/superpowers/plans/2026-05-18-yt-foreign-foreground-guard-plan.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Дождаться CI green, request review (если есть автотриаж), merge**

После merge — auto-push hook (memory `reference_autowarm_git_hook`) разольёт в `/root/.openclaw/workspace-genri/autowarm/` автоматически.

- [ ] **Step 3: Restart PM2 и проверить exec cwd (memory `feedback_pm2_dump_path_drift`)**

```bash
pm2 restart 34 autowarm
pm2 describe autowarm | grep -i "exec cwd"
```

Expected: `exec cwd` указывает на `/root/.openclaw/workspace-genri/autowarm/`. Если на `/home/claude-user/autowarm-testbench/` — drift, fix через `pm2 delete autowarm && pm2 start ecosystem.config.js --only autowarm`.

- [ ] **Step 4: OpenProject — апдейт WP #74 в Тестирование**

```bash
source ~/secrets/openproject.env
# Сначала получить lockVersion
LV=$(curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
    "$OPENPROJECT_URL/api/v3/work_packages/74" | python3 -c "import json,sys;print(json.load(sys.stdin)['lockVersion'])")
# PATCH в Тестирование (status id 11)
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
    -X PATCH "$OPENPROJECT_URL/api/v3/work_packages/74" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "
import json
print(json.dumps({
  'lockVersion': $LV,
  '_links': {'status': {'href': '/api/v3/statuses/11'}},
  'comment': {'raw': '''## Что было не так

Round 1 (PR #64, 15.05) закрыл 2/2 исходных кейса, но 18.05 task 6899 поймал новый класс: ForceLoginSamungAccountActivity (Samsung Galaxy Store) перехватил foreground — force-stop YT тут не лечит чужой пакет.

## Что сделано

PR <#> — foreign-foreground guard с escalation Skip-tap → BACK×2 → force-stop+relaunch, allowlist YT/permission-controller, blocklist системных пакетов. Два checkpoint'а: после _normalize_yt_state_pre_upload и перед fail-fast в _select_gallery_video с 1-retry. Категория yt_gallery_no_video_candidate сохранена, новые поля в meta.foreign_foreground_*.

## Что осталось

24h verify: 0 рецидивов yt_gallery_no_video_candidate с meta.foreign_foreground_unrecoverable_reason=still_foreign при ненулевом потоке YT-задач.'''}
}))")"
```

- [ ] **Step 5: 24h verify (через сутки)**

Использовать SQL из spec'а §5 + паттерн `docs/evidence/2026-05-18-wp-triage-testing-status.md`. Если 0 unrecovered рецидивов — статус → Готово.

---

## Self-Review (run mentally)

**Spec coverage:**

| Spec section | Implemented in Task |
|---|---|
| §1 цели/нон-цели | Покрыто архитектурой Tasks 1-9 |
| §2 архитектура, allowlist, blocklist, skip-keys, kill-switch | Tasks 2 (skeleton) + 3 (kill-switch) + 6 (blocklist) |
| §3 internal flow (probe → allowlist → kill-switch → 3 эскалации → emit) | Tasks 1+2+3+4+5+6 |
| §4 checkpoint #1 + #2 | Tasks 7 + 8 |
| §5 observability (7 категорий) | Tasks 2, 3, 4, 6 emit'ят все 7 категорий |
| §5 kill-switch | Task 3 + Task 9 (docs) |
| §6 testing — 13 unit + 4 integration + live smoke | Tasks 1-6 unit (12 шт. — 5 parser + 3 allowlist + 2 kill-switch + 2 skip + 2 back + 3 force-stop = 17. Перепроверь счёт после Task 6 Step 4.) + 7+8 integration (4) + Task 12 live smoke |
| §7 файлы | Tasks 1-9 покрывают 5 файлов |
| §8 деплой/rollback | Task 13 |

**Placeholder scan:** Все steps содержат код / точные команды. TODO/TBD — нет.

**Type consistency:**
- `_dismiss_foreign_foreground(*, source: str, allow_recovery: bool = True) -> dict` — consistent во всех задачах.
- Return dict keys: `foreign_detected, top_package, top_activity, recovered, escalation_steps, unrecoverable_reason` — consistent.
- `_emit_foreign_foreground_outcome(result, source, final_top_pkg)` — appears в Task 4 def + используется в Tasks 4/6.
- `_foreign_reprobe()` — appears в Task 4 def + используется в Tasks 4/5/6.
- `YT_FOREGROUND_ALLOWLIST`, `FOREIGN_FORCE_STOP_BLOCKLIST`, `FOREIGN_FOREGROUND_SKIP_KEYS` — определены в Task 2, используются consistently.
- Event-категории: 7 шт. в spec'е, все 7 emit'ятся (`detected`, `recovered`, `unrecoverable`, `unrecoverable_blocklist`, `guard_disabled`, `probe_failed`, `yt_gallery_retry_after_foreign_recovery`).

Замечание для исполнителя: в Self-Review §testing я насчитал 17 unit-тестов вместо 13 из spec'а (5 parser + 3 allowlist + 2 kill-switch + 2 skip-tap + 2 back + 3 force-stop = 17). Spec'овская оценка 13 была занижена — это OK, больше тестов лучше. Меняй число в spec'е если хочется консистентности, либо игнорируй.
