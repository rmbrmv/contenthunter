# WP #121 — Launcher-hijack gate recovery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать foreground-гейт `_ensure_app_foregrounded` устойчивым к застреванию в Samsung launcher / sbrowser CustomTab, делегируя подъём приложения проверенному `_open_app` (вариант A1), под kill-switch.

**Architecture:** Один файл `account_switcher.py`. В `_ensure_app_foregrounded` добавляется ветка «strong recovery» (default ON): при не-целевом foreground вместо `am start` ×2 вызывается `_open_app`, который сам гасит blocking-overlay'и (force-stop sbrowser/launcher → cold-start), ретраит `am start` и применяет WP #105 cross-source. Legacy-путь (`am start` ×2) сохраняется байт-в-байт под `SWITCHER_GATE_STRONG_RECOVERY_ENABLED=0`. Контракт функции (`(platform_key) -> bool`, error_code `<prefix>_app_not_foregrounded`) не меняется — call-sites IG/YT/TT не трогаем.

**Tech Stack:** Python 3, pytest, unittest.mock. Репозиторий `autowarm-testbench` (= GenGo2/delivery-contenthunter). Спека: `docs/superpowers/specs/2026-05-25-wp121-launcher-hijack-gate-recovery-design.md`.

**Рабочая директория для всех команд:** `/home/claude-user/autowarm-testbench`

---

## File Structure

- **Modify:** `account_switcher.py:3897-3963` — функция `_ensure_app_foregrounded`. Добавить strong-ветку + kill-switch; legacy-цикл сохранить без изменений.
- **Create:** `tests/test_account_switcher_gate_strong_recovery.py` — новые тесты strong-пути (launcher→target, sbrowser→target, kill-switch off, финальный fail).
- **Modify:** `tests/test_switcher_youtube.py:806-852` — два legacy-теста гейта перевести на `SWITCHER_GATE_STRONG_RECOVERY_ENABLED=0` (пинят legacy-путь). Тест на 792 (happy-path) НЕ трогаем — проходит в обоих режимах.

---

### Task 1: Новые тесты strong-пути (failing)

**Files:**
- Create: `tests/test_account_switcher_gate_strong_recovery.py`

- [ ] **Step 1: Написать падающие тесты**

```python
"""Unit-тесты strong-recovery ветки `_ensure_app_foregrounded` (WP #121).

Гейт при не-целевом foreground делегирует подъём приложения в `_open_app`
(force-stop sbrowser/launcher → cold-start). Kill-switch:
SWITCHER_GATE_STRONG_RECOVERY_ENABLED (default ON).

Запуск: cd /home/claude-user/autowarm-testbench && \
        pytest tests/test_account_switcher_gate_strong_recovery.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from account_switcher import AccountSwitcher  # noqa: E402

YT = 'com.google.android.youtube'
LAUNCHER = 'com.sec.android.app.launcher'
SBROWSER = 'com.sec.android.app.sbrowser'


def _make_switcher() -> tuple[AccountSwitcher, MagicMock]:
    stub = MagicMock()
    stub.platform = 'YouTube'
    stub.task_id = 1
    stub.adb = MagicMock(return_value='')
    stub.adb_tap = MagicMock()
    stub.dump_ui = MagicMock(return_value='')
    stub.log_event = MagicMock()
    stub.set_step = MagicMock()
    stub.ensure_unlocked = MagicMock()
    sw = AccountSwitcher(stub, verbose_screenshots=False)
    # _open_app пишет дампы/скрины — глушим файловый I/O в unit-тестах
    sw._save_dump = MagicMock()
    sw._maybe_screenshot = MagicMock()
    return sw, stub


def _reasons(stub) -> list[str]:
    out = []
    for c in stub.log_event.call_args_list:
        meta = c.kwargs.get('meta') or (c.args[-1] if c.args and isinstance(c.args[-1], dict) else {})
        if isinstance(meta, dict) and meta.get('reason'):
            out.append(meta['reason'])
    return out


def test_strong_recovery_launcher_then_target(monkeypatch):
    """Launcher foreground → _open_app force-stop target + am start → YT foreground → True."""
    monkeypatch.setenv('SWITCHER_GATE_STRONG_RECOVERY_ENABLED', '1')
    import account_switcher as _asw
    monkeypatch.setattr(_asw.time, 'sleep', lambda *a, **kw: None)
    sw, stub = _make_switcher()

    state = {'started': False}

    def adb_side(cmd: str):
        if cmd.startswith('am start'):
            state['started'] = True
            return ''
        if 'force-stop' in cmd:
            return ''
        if 'dumpsys activity' in cmd:
            pkg = YT if state['started'] else LAUNCHER
            return f'  topResumedActivity=ActivityRecord{{ u0 {pkg}/.Activity t1}}\n'
        return ''

    stub.adb.side_effect = adb_side
    stub.dump_ui.side_effect = lambda *a, **kw: (
        f'<hierarchy><node package="{YT if state["started"] else LAUNCHER}"/></hierarchy>'
    )

    assert sw._ensure_app_foregrounded('YouTube') is True
    cmds = [c.args[0] for c in stub.adb.call_args_list]
    # launcher-overlay handler делает force-stop ЦЕЛЕВОГО приложения (cold-start)
    assert any(f'force-stop {YT}' in c for c in cmds), 'ожидался force-stop target (launcher cold-start)'
    assert any(c.startswith('am start') for c in cmds), 'ожидался am start'
    rs = _reasons(stub)
    assert 'yt_foreground_recovery' in rs
    assert 'yt_app_foregrounded_after_recovery' in rs


def test_strong_recovery_sbrowser_customtab_then_target(monkeypatch):
    """sbrowser CustomTab поверх YT → BACK + force-stop sbrowser → YT раскрывается → True."""
    monkeypatch.setenv('SWITCHER_GATE_STRONG_RECOVERY_ENABLED', '1')
    import account_switcher as _asw
    monkeypatch.setattr(_asw.time, 'sleep', lambda *a, **kw: None)
    sw, stub = _make_switcher()

    state = {'killed': False}

    def adb_side(cmd: str):
        if f'force-stop {SBROWSER}' in cmd:
            state['killed'] = True
            return ''
        if 'dumpsys activity' in cmd:
            if state['killed']:
                return f'  topResumedActivity=ActivityRecord{{ u0 {YT}/.HomeActivity t1}}\n'
            return (f'  topResumedActivity=ActivityRecord{{ u0 '
                    f'{SBROWSER}/.customtabs.CustomTabActivity t99}}\n')
        return ''

    stub.adb.side_effect = adb_side
    stub.dump_ui.side_effect = lambda *a, **kw: (
        f'<hierarchy><node package="{YT if state["killed"] else SBROWSER}"/></hierarchy>'
    )

    assert sw._ensure_app_foregrounded('YouTube') is True
    cmds = [c.args[0] for c in stub.adb.call_args_list]
    assert any(f'force-stop {SBROWSER}' in c for c in cmds), 'ожидался force-stop sbrowser'
    assert 'yt_app_foregrounded_after_recovery' in _reasons(stub)


def test_strong_recovery_off_uses_legacy_am_start(monkeypatch):
    """Kill-switch OFF → старый путь (am start), _open_app НЕ вызывается."""
    monkeypatch.setenv('SWITCHER_GATE_STRONG_RECOVERY_ENABLED', '0')
    import account_switcher as _asw
    monkeypatch.setattr(_asw.time, 'sleep', lambda *a, **kw: None)
    sw, stub = _make_switcher()
    sw._open_app = MagicMock(return_value=True)

    seq = iter([
        f'  topResumedActivity=ActivityRecord{{ u0 com.zhiliaoapp.musically/.MainActivity t1}}\n',
        '',  # am start
        f'  topResumedActivity=ActivityRecord{{ u0 {YT}/.HomeActivity t1}}\n',
    ])
    stub.adb.side_effect = lambda cmd: next(seq, '')

    assert sw._ensure_app_foregrounded('YouTube') is True
    sw._open_app.assert_not_called()
    cmds = [c.args[0] for c in stub.adb.call_args_list]
    assert any('am start' in c for c in cmds)


def test_strong_recovery_final_fail_emits_app_not_foregrounded(monkeypatch):
    """_open_app не вытянул → False + canonical reason yt_app_not_foregrounded."""
    monkeypatch.setenv('SWITCHER_GATE_STRONG_RECOVERY_ENABLED', '1')
    sw, stub = _make_switcher()
    sw._open_app = MagicMock(return_value=False)
    stub.adb.return_value = (
        f'  topResumedActivity=ActivityRecord{{ u0 {LAUNCHER}/.Activity t1}}\n'
    )

    assert sw._ensure_app_foregrounded('YouTube') is False
    sw._open_app.assert_called_once()
    # step передан как yt_0_foreground_guard
    assert sw._open_app.call_args.args[2] == 'yt_0_foreground_guard'
    err = [c for c in stub.log_event.call_args_list
           if (c.args and c.args[0] == 'error')]
    err_reasons = [
        (c.kwargs.get('meta') or {}).get('reason') for c in err
    ]
    assert 'yt_app_not_foregrounded' in err_reasons
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd /home/claude-user/autowarm-testbench && pytest tests/test_account_switcher_gate_strong_recovery.py -v`
Expected: FAIL. `test_strong_recovery_launcher_then_target` и `..._sbrowser...` падают (текущий гейт не делает force-stop — `am start` ×2 без overlay-dismiss). `..._final_fail...` падает (текущий гейт не вызывает `_open_app`). `..._off...` может пройти (legacy уже есть) — это ок.

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add tests/test_account_switcher_gate_strong_recovery.py
git commit -m "test(wp121): failing-тесты strong-recovery гейта (launcher/sbrowser/kill-switch/fail)"
```

---

### Task 2: Реализация strong-recovery ветки

**Files:**
- Modify: `account_switcher.py:3897-3963` (`_ensure_app_foregrounded`)

- [ ] **Step 1: Заменить тело `_ensure_app_foregrounded`**

Заменить весь блок строк 3897-3963 (от `def _ensure_app_foregrounded` до `return False` финального fail) на:

```python
    def _ensure_app_foregrounded(self, platform_key: str,
                                  max_retries: int = 2,
                                  poll_delay: float = 2.0) -> bool:
        """Проверяет что нужный app в foreground (mCurrentFocus). Если нет —
        поднимает приложение. Возвращает True/False.

        На False emit'ит error event с canonical reason
        `<platform_prefix>_app_not_foregrounded` (short-form: yt_, tt_, ig_).

        [WP #121 2026-05-25] Strong-recovery (default ON): при не-целевом
        foreground подъём делегируется `_open_app`, который гасит blocking-
        overlay'и (force-stop sbrowser CustomTab / launcher → cold-start),
        ретраит `am start` и применяет WP #105 cross-source. Старый путь
        (`am start` ×2 без force-stop) не вытягивал launcher/sbrowser →
        `yt_app_not_foregrounded` (триаж 2026-05-25: 30/30 launcher-
        терминальных фейлов 3д = YT). Kill-switch:
        `SWITCHER_GATE_STRONG_RECOVERY_ENABLED=0` → старое поведение.
        """
        expected_pkg = self._PLATFORM_PACKAGES.get(platform_key)
        if not expected_pkg:
            log.warning(f'[switcher] _ensure_app_foregrounded: unknown platform={platform_key}')
            return False

        cfg = UI_CONSTANTS.get(platform_key) or {}
        launch_activity = cfg.get('launch_activity')
        platform_prefix = self._PLATFORM_REASON_PREFIX.get(platform_key, platform_key.lower())

        strong = os.getenv('SWITCHER_GATE_STRONG_RECOVERY_ENABLED', '1') != '0'
        if strong and launch_activity:
            focus_out = self.p.adb(
                'dumpsys activity activities | grep -m1 topResumedActivity'
            ) or ''
            if expected_pkg in focus_out:
                return True
            self.p.log_event(
                'warning',
                f'{platform_prefix}_foreground_recovery: focus={focus_out[:80]!r} mode=strong',
                meta={
                    'reason': f'{platform_prefix}_foreground_recovery',
                    'focus': focus_out[:120],
                    'mode': 'strong_open_app',
                },
            )
            if self._open_app(expected_pkg, launch_activity,
                              f'{platform_prefix}_0_foreground_guard'):
                self.p.log_event(
                    'info',
                    f'{platform_prefix}_app_foregrounded_after_recovery: mode=strong',
                    meta={
                        'reason': f'{platform_prefix}_app_foregrounded_after_recovery',
                        'mode': 'strong_open_app',
                    },
                )
                return True
            self.p.log_event(
                'error',
                f'{platform_prefix}_app_not_foregrounded: failed after strong recovery',
                meta={
                    'reason': f'{platform_prefix}_app_not_foregrounded',
                    'expected_pkg': expected_pkg,
                    'mode': 'strong_open_app',
                },
            )
            return False

        # --- Legacy path (kill-switch off или нет launch_activity) ---
        for attempt in range(1, max_retries + 1):
            focus_out = self.p.adb(
                'dumpsys activity activities | grep -m1 topResumedActivity'
            ) or ''
            if expected_pkg in focus_out:
                if attempt > 1:
                    self.p.log_event(
                        'info',
                        f'{platform_prefix}_app_foregrounded_after_recovery: attempt={attempt}',
                        meta={
                            'reason': f'{platform_prefix}_app_foregrounded_after_recovery',
                            'attempt': attempt,
                        },
                    )
                return True

            # Чужой app — relaunch
            self.p.log_event(
                'warning',
                f'{platform_prefix}_foreground_recovery: focus={focus_out[:80]!r} '
                f'attempt={attempt}',
                meta={
                    'reason': f'{platform_prefix}_foreground_recovery',
                    'focus': focus_out[:120],
                    'attempt': attempt,
                },
            )
            if launch_activity:
                self.p.adb(f'am start -W -n {launch_activity}')
            else:
                self.p.adb(f'monkey -p {expected_pkg} -c android.intent.category.LAUNCHER 1')
            time.sleep(poll_delay)

        # Финальный fail
        self.p.log_event(
            'error',
            f'{platform_prefix}_app_not_foregrounded: failed after {max_retries} retries',
            meta={
                'reason': f'{platform_prefix}_app_not_foregrounded',
                'expected_pkg': expected_pkg,
                'retries': max_retries,
            },
        )
        return False
```

(`os` уже импортирован — `account_switcher.py:37`. Legacy-цикл идентичен прежнему.)

- [ ] **Step 2: Запустить новые тесты — убедиться, что проходят**

Run: `cd /home/claude-user/autowarm-testbench && pytest tests/test_account_switcher_gate_strong_recovery.py -v`
Expected: PASS (4/4).

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add account_switcher.py
git commit -m "fix(wp121): strong-recovery foreground-гейта через _open_app (launcher/sbrowser)

Гейт _ensure_app_foregrounded при чужом foreground делегирует подъём в
_open_app (force-stop sbrowser/launcher + cold-start + ретраи + WP#105)
вместо am start x2. Kill-switch SWITCHER_GATE_STRONG_RECOVERY_ENABLED
(default ON). Legacy-путь сохранён. Контракт и error_code без изменений."
```

---

### Task 3: Перевод legacy-тестов гейта на kill-switch OFF

**Files:**
- Modify: `tests/test_switcher_youtube.py:806`, `:832`

После Task 2 эти два теста ассертят `am start`-логику, которая теперь только под kill-switch OFF. Пиним их на legacy-путь.

- [ ] **Step 1: Добавить setenv в `test_ensure_app_foregrounded_relaunches_when_wrong_app`**

В тесте на строке 806, сразу после `sw = AccountSwitcher(mock_pub)` (≈ строка 820), добавить:

```python
    monkeypatch.setenv('SWITCHER_GATE_STRONG_RECOVERY_ENABLED', '0')
```

- [ ] **Step 2: Добавить setenv в `test_ensure_app_foregrounded_fails_after_retries`**

В тесте на строке 832, сразу после `sw = AccountSwitcher(mock_pub)` (≈ строка 844), добавить:

```python
    monkeypatch.setenv('SWITCHER_GATE_STRONG_RECOVERY_ENABLED', '0')
```

(Оба теста уже принимают `monkeypatch` в сигнатуре — менять её не нужно.)

- [ ] **Step 3: Запустить весь файл гейт-тестов**

Run: `cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py -k ensure_app_foregrounded -v`
Expected: PASS (3/3 — включая happy-path 792 без изменений).

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add tests/test_switcher_youtube.py
git commit -m "test(wp121): legacy-тесты гейта пинят SWITCHER_GATE_STRONG_RECOVERY_ENABLED=0"
```

---

### Task 4: Полный прогон + codex review

**Files:** (нет правок — верификация)

- [ ] **Step 1: Прогнать весь набор тестов switcher'а и смежные**

Run:
```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_account_switcher.py tests/test_switcher_youtube.py \
       tests/test_account_switcher_tt.py tests/test_overlay_dismiss.py \
       tests/test_yt_post_switch_verify.py \
       tests/test_account_switcher_gate_strong_recovery.py \
       tests/test_account_switcher_ig_picker_fg_guard.py \
       tests/test_account_switcher_tt_switch_fg_guard.py -q
```
Expected: all PASS, 0 failed. Если что-то красное из-за гейта — чинить прицельно (вероятный кандидат: тест, который дергает `_ensure_app_foregrounded` с не-целевым foreground и бьёт по адб-последовательности → добавить `SWITCHER_GATE_STRONG_RECOVERY_ENABLED=0`, если он про legacy, либо подстроить мок под strong-путь).

- [ ] **Step 2: codex review (раундами до 0 P1)**

Run:
```bash
cd /home/claude-user/autowarm-testbench
git diff origin/main...HEAD -- account_switcher.py tests/ | ~/.local/bin/codex review -
```
(При warning про bubblewrap — игнорировать, benign.) Применить P1-фидбэк, повторить до 0 P1.

- [ ] **Step 3: Отдать пользователю на ревью перед деплоем**

Деплой в прод (`/root/.openclaw/workspace-genri/autowarm`, path-scoped, без PM2-restart) — отдельный шаг, ТОЛЬКО после явного «погнали» от Данила. Деплой-механику и verify-критерий см. в спеке (§6-7): динамика `yt_app_not_foregrounded` через сутки, спад с ~10/день к околонулю.

---

## Self-Review (выполнено при написании)

- **Spec coverage:** §2 решение → Task 2; §3 kill-switch → Task 2 (env-var); §5 тесты (4 кейса + обновление legacy) → Task 1 + Task 3; §6 деплой / §7 verify → Task 4 Step 3 (ссылка на спеку, user-gated). ✓
- **Placeholder scan:** код приведён полностью во всех steps; команды с ожидаемым результатом. ✓
- **Type/имя-консистентность:** env-var `SWITCHER_GATE_STRONG_RECOVERY_ENABLED` и reason'ы (`yt_foreground_recovery`, `yt_app_foregrounded_after_recovery`, `yt_app_not_foregrounded`) идентичны в коде Task 2 и ассертах Task 1. Сигнатура `_open_app(package, launch_activity, step_name)` — позиционно как в `account_switcher.py:5537`. ✓
