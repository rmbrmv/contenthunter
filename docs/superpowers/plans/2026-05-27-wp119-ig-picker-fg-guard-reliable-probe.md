# WP #119 — IG picker fg-guard на надёжном пробнике: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести IG picker foreground-guard (`_ig_guard_picker_foreground`) с ненадёжного `_detect_foreground_pkg` (первый `package=` из XML-дампа → systemui → over-fire) на надёжный bare-dumpsys `topResumedActivity`, добавить 2-sample confirm, починить 8 связанных красных тестов и снова включить гард в проде.

**Architecture:** Новый метод `_reliable_foreground_pkg()` в `AccountSwitcher` делегирует в проверенный `self.p._ig_probe_foreground_pkg` (WP #135), с локальным bare-dumpsys fallback для шима и нормализацией `'unknown'`/не-строка → `''`. Гард использует его + подтверждает чужой foreground вторым замером (паттерн WP #129). Глобальный `_detect_foreground_pkg` НЕ трогаем (на нём держатся YT/TT). Flow-тесты изолируются от гарда kill-switch'ем `IG_PICKER_FG_GUARD_ENABLED=0`; гард покрывается отдельными прямыми тестами.

**Tech Stack:** Python 3.12, pytest, MagicMock. Репозиторий кода `GenGo2/delivery-contenthunter`.

**Spec:** `docs/superpowers/specs/2026-05-27-wp119-ig-picker-fg-guard-reliable-probe-design.md`

---

## Рабочее окружение (важно)

- **Код-репозиторий:** `GenGo2/delivery-contenthunter`. Прод-копия `/root/.openclaw/workspace-genri/autowarm` (ветка `main`) — **только для чтения/референса**, НЕ редактировать напрямую.
- **Где работать:** отдельная feature-ветка/worktree `delivery-contenthunter` (создать на этапе исполнения). ⚠️ post-commit git-hook этого репо пушит текущую ветку на origin (коммит = публичный push); прод тянет только `main`, поэтому feature-ветка не задеплоится сама.
- **Файлы (пути от корня autowarm):**
  - Modify: `account_switcher.py` — `_reliable_foreground_pkg` (новый) + `_ig_guard_picker_foreground` (правка источника fg + 2-sample).
  - Test: `tests/test_account_switcher.py` — новые прямые тесты гарда + починка фикстур/тестов.
  - Test: `tests/test_canonical_error_codes.py` — починка 2 тестов.
- **Запуск тестов:** из корня autowarm-checkout: `python3 -m pytest tests/test_account_switcher.py tests/test_canonical_error_codes.py -q`.

---

## Task 1: Метод `_reliable_foreground_pkg`

**Files:**
- Modify: `account_switcher.py` (добавить метод сразу после `_detect_foreground_pkg`, ~строка 3958)
- Test: `tests/test_account_switcher.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_account_switcher.py`:

```python
# ─── WP #119 _reliable_foreground_pkg ──────────────────────────────────────

def test_reliable_fg_delegates_to_probe(monkeypatch):
    """В бою делегирует в self.p._ig_probe_foreground_pkg и возвращает его строку."""
    from unittest.mock import MagicMock
    stub = MagicMock()
    stub._ig_probe_foreground_pkg = MagicMock(return_value='com.instagram.android')
    sw = AccountSwitcher(stub, verbose_screenshots=False)
    assert sw._reliable_foreground_pkg() == 'com.instagram.android'
    stub._ig_probe_foreground_pkg.assert_called_once()


def test_reliable_fg_unknown_normalized_to_empty(monkeypatch):
    """'unknown' от пробника → '' (= «не определили», чтобы guard не считал foreign)."""
    from unittest.mock import MagicMock
    stub = MagicMock()
    stub._ig_probe_foreground_pkg = MagicMock(return_value='unknown')
    sw = AccountSwitcher(stub, verbose_screenshots=False)
    assert sw._reliable_foreground_pkg() == ''


def test_reliable_fg_non_string_normalized_to_empty(monkeypatch):
    """Не-строка (например MagicMock из непровязанного стаба) → '' (защита от over-fire-ловушки)."""
    from unittest.mock import MagicMock
    stub = MagicMock()
    stub._ig_probe_foreground_pkg = MagicMock(return_value=object())
    sw = AccountSwitcher(stub, verbose_screenshots=False)
    assert sw._reliable_foreground_pkg() == ''


def test_reliable_fg_fallback_bare_dumpsys_for_shim():
    """Шим без _ig_probe_foreground_pkg → локальный bare-dumpsys через self.p.adb."""
    from unittest.mock import MagicMock

    class _Shim:
        def __init__(self):
            self.adb = MagicMock(
                return_value='  topResumedActivity=ActivityRecord{xyz u0 com.instagram.android/.MainActivity t1}')
    shim = _Shim()
    sw = AccountSwitcher(shim, verbose_screenshots=False)
    assert sw._reliable_foreground_pkg() == 'com.instagram.android'
    shim.adb.assert_called_once()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 -m pytest tests/test_account_switcher.py -k reliable_fg -q`
Expected: FAIL — `AttributeError: 'AccountSwitcher' object has no attribute '_reliable_foreground_pkg'`

- [ ] **Step 3: Реализовать метод**

В `account_switcher.py` сразу после `_detect_foreground_pkg` (после строки `return pkg` ~3958) добавить:

```python
    def _reliable_foreground_pkg(self) -> str:
        """[WP #119 2026-05-27] Надёжный foreground-пакет через bare-dumpsys
        topResumedActivity — для picker-fg-guard вместо _detect_foreground_pkg.

        _detect_foreground_pkg берёт ПЕРВЫЙ package="..." из XML-дампа (часто
        systemui/launcher) → ложный «foreign» → over-fire (инцидент 26.05,
        IG 79%→22%). Здесь — реальный foreground.

        В бою делегируем в проверенный self.p._ig_probe_foreground_pkg
        (WP #129/#135). Для шима (account_revision) без IG-методов — локальный
        bare-dumpsys fallback через self.p.adb (без timeout, как _detect_foreground_pkg).

        Нормализация: 'unknown'/пусто/не-строка → '' (= «не определили» →
        guard no-op; иначе 'unknown' != пакет дал бы новую over-fire-ловушку).
        """
        probe = getattr(self.p, '_ig_probe_foreground_pkg', None)
        if callable(probe):
            pkg = probe()
        else:
            out = self.p.adb(
                'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"') or ''
            m = re.search(r'ActivityRecord\{[^}]*?\s([\w.]+)/', out)
            pkg = m.group(1) if m else ''
        if not isinstance(pkg, str) or pkg == 'unknown':
            return ''
        return pkg
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python3 -m pytest tests/test_account_switcher.py -k reliable_fg -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Коммит**

```bash
git add account_switcher.py tests/test_account_switcher.py
git commit -m "feat(wp119): _reliable_foreground_pkg — надёжный fg-пробник для picker-guard"
```

---

## Task 2: Гард на надёжном пробнике + 2-sample confirm

**Files:**
- Modify: `account_switcher.py` — `_ig_guard_picker_foreground` (начало тела, строки ~1815–1825)
- Test: `tests/test_account_switcher.py`

- [ ] **Step 1: Написать падающие тесты гарда**

Добавить в конец `tests/test_account_switcher.py`:

```python
# ─── WP #119 picker fg-guard на надёжном пробнике ───────────────────────────

_IG_CFG = {'package': 'com.instagram.android'}


def _make_guard_switcher(monkeypatch):
    """Switcher для прямых тестов _ig_guard_picker_foreground (WP #119).
    sheet-валидация мокается True — изолируем именно fg-пробник."""
    from unittest.mock import MagicMock
    import account_switcher as _asw
    monkeypatch.setattr(_asw.time, 'sleep', lambda *a, **kw: None)
    stub = MagicMock()
    stub.platform = 'Instagram'
    stub.task_id = 1
    stub.log_event = MagicMock()
    stub.dump_ui = MagicMock(return_value='<hierarchy/>')
    switcher = AccountSwitcher(stub, verbose_screenshots=False)
    switcher._ensure_app_foregrounded = MagicMock(return_value=True)
    switcher._go_to_profile_tab = MagicMock(return_value=True)
    switcher._read_screen_hybrid = MagicMock(return_value=([], 'empty', None))
    switcher._tap_profile_header = MagicMock(return_value=True)
    switcher._ig_on_account_switcher_sheet = MagicMock(return_value=True)
    return switcher, stub


def test_ig_picker_guard_ignores_dump_first_package_regression(monkeypatch):
    """[WP #119 регресс инцидента 26.05] dump_ui первым узлом отдаёт systemui
    (старая ловушка _detect_foreground_pkg), но гард доверяет надёжному пробнику
    (IG) → НЕ срабатывает foreign. Этот тест поймал бы over-fire."""
    switcher, stub = _make_guard_switcher(monkeypatch)
    stub.dump_ui = MagicMock(
        return_value='<hierarchy><node package="com.android.systemui"/></hierarchy>')
    stub._ig_probe_foreground_pkg = MagicMock(return_value='com.instagram.android')

    assert switcher._ig_guard_picker_foreground(_IG_CFG, header_y_max=260) is True
    switcher._ensure_app_foregrounded.assert_not_called()
    assert _extract_log_events(stub, 'warning', 'ig_picker_fg_foreign') == []


def test_ig_picker_guard_unknown_is_noop(monkeypatch):
    """Пробник вернул 'unknown' → '' → «не определили» → no-op (True)."""
    switcher, stub = _make_guard_switcher(monkeypatch)
    stub._ig_probe_foreground_pkg = MagicMock(return_value='unknown')

    assert switcher._ig_guard_picker_foreground(_IG_CFG, header_y_max=260) is True
    switcher._ensure_app_foregrounded.assert_not_called()


def test_ig_picker_guard_foreign_confirmed_triggers_recovery(monkeypatch):
    """Два замера подряд = чужой (YouTube) → recovery; relaunch успешен → True."""
    switcher, stub = _make_guard_switcher(monkeypatch)
    stub._ig_probe_foreground_pkg = MagicMock(
        side_effect=['com.google.android.youtube', 'com.google.android.youtube'])

    assert switcher._ig_guard_picker_foreground(_IG_CFG, header_y_max=260) is True
    switcher._ensure_app_foregrounded.assert_called_once_with('Instagram')
    assert len(_extract_log_events(stub, 'warning', 'ig_picker_fg_foreign')) == 1


def test_ig_picker_guard_foreign_recovery_fails_returns_false(monkeypatch):
    """Чужой подтверждён, но relaunch IG не удался → False (caller → честный код)."""
    switcher, stub = _make_guard_switcher(monkeypatch)
    stub._ig_probe_foreground_pkg = MagicMock(
        side_effect=['com.google.android.youtube', 'com.google.android.youtube'])
    switcher._ensure_app_foregrounded = MagicMock(return_value=False)

    assert switcher._ig_guard_picker_foreground(_IG_CFG, header_y_max=260) is False


def test_ig_picker_guard_transient_foreign_is_noop(monkeypatch):
    """1й замер чужой, 2й = IG → транзиент не подтверждён → no-op, без recovery."""
    switcher, stub = _make_guard_switcher(monkeypatch)
    stub._ig_probe_foreground_pkg = MagicMock(
        side_effect=['com.sec.android.app.launcher', 'com.instagram.android'])

    assert switcher._ig_guard_picker_foreground(_IG_CFG, header_y_max=260) is True
    switcher._ensure_app_foregrounded.assert_not_called()
    assert len(_extract_log_events(stub, 'info', 'ig_picker_fg_transient')) == 1
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 -m pytest tests/test_account_switcher.py -k ig_picker_guard -q`
Expected: FAIL — текущий гард зовёт `_detect_foreground_pkg` (его нет в стабе → MagicMock-путь), 2-sample/transient/foreign-семантики ещё нет; ассерты не сходятся.

- [ ] **Step 3: Править гард**

В `account_switcher.py`, `_ig_guard_picker_foreground`, заменить начало тела. Найти блок (строки ~1815–1825):

```python
        fg_pkg = self._detect_foreground_pkg()
        foreign = bool(fg_pkg) and fg_pkg != cfg['package']
        if foreign:
            self.p.log_event(
                'warning',
                f'ig_picker_fg_foreign: foreground={fg_pkg!r} перед ig_4_pick_account — '
                f'relaunch IG + re-navigate',
                meta={'category': 'ig_picker_fg_foreign',
                      'foreground_pkg': fg_pkg,
                      'step': 'ig_4_pick_account'},
            )
            if not self._ensure_app_foregrounded('Instagram'):
                return False
```

заменить на:

```python
        # [WP #119 2026-05-27] Надёжный пробник вместо _detect_foreground_pkg
        # (тот брал первый package= из дампа → systemui → over-fire 26.05).
        fg_pkg = self._reliable_foreground_pkg()
        self.p.log_event(
            'info',
            f'ig_picker_fg_probe: foreground={fg_pkg or "undetermined"} перед ig_4_pick_account',
            meta={'category': 'ig_picker_fg_probe',
                  'foreground_pkg': fg_pkg or 'undetermined',
                  'step': 'ig_4_pick_account'},
        )
        foreign = bool(fg_pkg) and fg_pkg != cfg['package']
        if foreign:
            # 2-sample confirm (паттерн WP #129 lost_streak>=2): одиночный
            # транзиент (лаунчер мелькнул во время анимации) НЕ триггерит
            # recovery. Чужим считаем только если 2-й замер подтвердил.
            time.sleep(0.5)
            fg_pkg2 = self._reliable_foreground_pkg()
            if not (bool(fg_pkg2) and fg_pkg2 != cfg['package']):
                self.p.log_event(
                    'info',
                    f'ig_picker_fg_transient: 1й замер {fg_pkg!r} чужой, 2й {fg_pkg2!r} '
                    f'не подтвердил — транзиент, гард no-op',
                    meta={'category': 'ig_picker_fg_transient',
                          'first_pkg': fg_pkg, 'second_pkg': fg_pkg2,
                          'step': 'ig_4_pick_account'},
                )
                foreign = False
        if foreign:
            self.p.log_event(
                'warning',
                f'ig_picker_fg_foreign: foreground={fg_pkg!r} перед ig_4_pick_account — '
                f'relaunch IG + re-navigate',
                meta={'category': 'ig_picker_fg_foreign',
                      'foreground_pkg': fg_pkg,
                      'step': 'ig_4_pick_account'},
            )
            if not self._ensure_app_foregrounded('Instagram'):
                return False
```

(Остальное тело гарда — `_go_to_profile_tab`, sheet-валидация и т.д. — без изменений.)

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python3 -m pytest tests/test_account_switcher.py -k ig_picker_guard -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Коммит**

```bash
git add account_switcher.py tests/test_account_switcher.py
git commit -m "fix(wp119): picker fg-guard на надёжном пробнике + 2-sample confirm"
```

---

## Task 3: Починка 8 связанных красных тестов

Эти тесты падают, потому что гард (его sheet-валидация, PR #102) включён по умолчанию и выедает/не находит то, что ожидают flow-тесты (см. spec). Гард — не их предмет; изолируем их kill-switch'ем `IG_PICKER_FG_GUARD_ENABLED=0`. Гард покрыт прямыми тестами из Task 2.

**Files:**
- Modify: `tests/test_account_switcher.py`
- Modify: `tests/test_canonical_error_codes.py`

- [ ] **Step 1: Зафиксировать текущие падения (baseline)**

Run:
```bash
python3 -m pytest \
  "tests/test_account_switcher.py::test_ig_sa_mode_disabled_keeps_normal_list_open_flow" \
  "tests/test_account_switcher.py::test_ig_human_check_no_match_invokes_kb_shadow_probe_at_both_sites" \
  "tests/test_account_switcher.py::test_ig_post_switch_match_no_retry" \
  "tests/test_account_switcher.py::test_ig_post_switch_mismatch_then_match_after_retry" \
  "tests/test_account_switcher.py::test_ig_post_switch_mismatch_three_attempts_fails" \
  "tests/test_account_switcher.py::test_ig_post_switch_unknown_handle_proceeds_without_retry" \
  "tests/test_canonical_error_codes.py::test_ig_target_not_in_picker_emitted_when_account_not_in_list" \
  "tests/test_canonical_error_codes.py::test_ig_picker_scroll_exhausted_maps_to_ig_target_not_in_picker" \
  -q
```
Expected: 8 failed (после Task 2 они всё ещё красные — гард включён в тестах по умолчанию).

- [ ] **Step 2: Поправить фикстуру `_make_ig_pick_switcher_stub`**

В `tests/test_account_switcher.py`, в `_make_ig_pick_switcher_stub` (~строки 700–701) заменить:

```python
    # [WP #119] IG foregrounded — picker fg-guard is a no-op (не трогает dump_ui-sequence).
    switcher._detect_foreground_pkg = MagicMock(return_value='com.instagram.android')
```

на:

```python
    # [WP #119] picker fg-guard не предмет этих flow-тестов — отключаем kill-switch'ем
    # (гард покрыт прямыми тестами test_ig_picker_guard_*).
    monkeypatch.setenv('IG_PICKER_FG_GUARD_ENABLED', '0')
```

- [ ] **Step 3: Поправить 2 теста, использующих `_make_sa_switcher_stub` напрямую**

В `test_ig_sa_mode_disabled_keeps_normal_list_open_flow` (~531) сразу после
`switcher, _ = _make_sa_switcher_stub(monkeypatch)` добавить строку:

```python
    monkeypatch.setenv('IG_PICKER_FG_GUARD_ENABLED', '0')  # [WP #119] guard не предмет теста
```

В `test_ig_human_check_no_match_invokes_kb_shadow_probe_at_both_sites` (~634) сразу после
`switcher, stub = _make_sa_switcher_stub(monkeypatch)` добавить ту же строку:

```python
    monkeypatch.setenv('IG_PICKER_FG_GUARD_ENABLED', '0')  # [WP #119] guard не предмет теста
```

- [ ] **Step 4: Поправить 2 канонических теста**

В `tests/test_canonical_error_codes.py`, в `test_ig_target_not_in_picker_emitted_when_account_not_in_list` (~249) и `test_ig_picker_scroll_exhausted_maps_to_ig_target_not_in_picker` (~282) сразу после `sw, log_calls = _make_switcher()` добавить:

```python
    monkeypatch.setenv('IG_PICKER_FG_GUARD_ENABLED', '0')  # [WP #119] guard не предмет теста
```

- [ ] **Step 5: Запустить 8 — убедиться, что зелёные**

Run: команда из Step 1.
Expected: 8 passed.

- [ ] **Step 6: Коммит**

```bash
git add tests/test_account_switcher.py tests/test_canonical_error_codes.py
git commit -m "test(wp119): изолировать flow/canonical-тесты от picker fg-guard (kill-switch)"
```

---

## Task 4: Полная сюита зелёная + codex review

- [ ] **Step 1: Прогнать обе сюиты целиком**

Run: `python3 -m pytest tests/test_account_switcher.py tests/test_canonical_error_codes.py -q`
Expected: all passed, 0 failed (включая 9 новых тестов Task 1+2 и 8 починенных).

- [ ] **Step 2: Codex review диффа**

Run: `git diff main HEAD | ~/.local/bin/codex review -`
Раундами устранять P1 (если есть), пока 0 P1. (bubblewrap-варнинг безобиден.)

- [ ] **Step 3: Открыть PR в `delivery-contenthunter`**

PR-тело по house-style; ссылка на spec/plan; отметить kill-switch `IG_PICKER_FG_GUARD_ENABLED` и план включения после live-smoke. НЕ force-push.

---

## Task 5: Деплой + live-smoke + включение гарда (операционный, после мержа PR)

⚠️ Не TDD — операционные шаги; требуют живого устройства и идут ПОСЛЕ мержа PR в `main`.

- [ ] **Step 1: Деплой.** Прод `/root/.openclaw/workspace-genri/autowarm` → `git pull --ff-only origin main`. Публишер спавнится per-task → рестарт PM2 не нужен. Гард приезжает под тем же `IG_PICKER_FG_GUARD_ENABLED=0` (пока OFF).

- [ ] **Step 2: Live-smoke с гардом ON.** На устройстве (рецепт смока #19, task 10064): `INSERT publish_tasks status='running' testbench=true` → `IG_PICKER_FG_GUARD_ENABLED=1 python3 publisher.py <id>` напрямую. Проверить: account-switch чисто, 0 `ig_account_switcher_wrong_foreground`, в логе событие `ig_picker_fg_probe` с `com.instagram.android` (НЕ systemui), флоу до success.

- [ ] **Step 3: Включить в проде.** Если смок чист — в `/root/.openclaw/workspace-genri/autowarm/.env` убрать строку `IG_PICKER_FG_GUARD_ENABLED=0` (или → `=1`). Per-task spawn подхватит env со следующей задачи.

- [ ] **Step 4: Verify 24ч.** IG success-rate не просел (≈79%); `ig_target_not_in_picker` → ~0; `ig_account_switcher_wrong_foreground` только на реальных foreign (единицы, не всплеск); `ig_picker_fg_transient` — редкие, без массовости. Откат при просадке: `IG_PICKER_FG_GUARD_ENABLED=0`.

- [ ] **Step 5: OpenProject #119.** Комментарий house-style (Что было не так → Что сделано → Что осталось) + статус → «Тестирование». Обновить память.

---

## Самопроверка плана (выполнено автором)

- **Spec coverage:** пробник (Task 1) ✓; гард + 2-sample + observability (Task 2) ✓; 8 тестов (Task 3) ✓; полная сюита + codex (Task 4) ✓; выкатка/smoke/re-enable/verify (Task 5) ✓; sheet-guard и глобальный `_detect_foreground_pkg` явно не трогаются (вне скоупа) ✓.
- **Плейсхолдеры:** нет — весь код приведён.
- **Type consistency:** `_reliable_foreground_pkg` → str везде; `_ig_probe_foreground_pkg` (стаб) → str; `cfg['package']`='com.instagram.android'; имена событий `ig_picker_fg_probe`/`ig_picker_fg_transient`/`ig_picker_fg_foreign` согласованы между кодом и тестами; `_extract_log_events`/`_make_sa_switcher_stub`/`_make_ig_pick_switcher_stub` — существующие хелперы.
