# WP #131 — TT stale-uiautomator guard в own-profile верификации — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Когда dumpsys стабильно подтверждает, что TikTok на переднем плане, но uiautomator-дамп протух (показывает лаунчер/пусто), перестать жечь retap'ы own-profile на stale XML — выйти из петли к существующей vision-based проверке аккаунта, которая постит только при `current==target`.

**Architecture:** Точечная врезка в retap-петлю `AccountSwitcher._switch_tiktok` (`account_switcher.py`). Один новый kill-switch (module-level), два маленьких метода-хелпера (`_tt_probe_looks_stale`, `_tt_dumpsys_confirms_foreground`), один guard-блок с `break`. Никакого нового механизма «рестарта uiautomator» (его нет — WP #105). Переиспользуем существующую post-loop vision-проверку аккаунта на 2911-2925.

**Tech Stack:** Python 3, pytest + `unittest.mock.MagicMock` (fake-proxy паттерн как в `tests/test_account_switcher_tt_switch_fg_guard.py`).

**Spec:** `docs/superpowers/specs/2026-05-26-wp131-tt-profile-tab-stale-ui-guard-design.md` (codex-clean, 3 раунда).

**Репозиторий кода:** `/root/.openclaw/workspace-genri/autowarm/` (prod autowarm; в `/home/claude-user/contenthunter` только docs). Изоляция: git worktree + ветка `wp131-tt-stale-ui-guard` создаётся на этапе исполнения через `superpowers:using-git-worktrees`. На `main` autowarm-репо уже лежит чужой `account_switcher.py.bak-wp132` (параллельная сессия WP #132) — НЕ трогать, атомарные коммиты, зелёный pytest перед merge.

---

## File Structure

- **Modify:** `account_switcher.py`
  - `~291`: новый module-level `_tt_stale_ui_guard_enabled()` (после `_tt_switch_fg_guard_enabled`).
  - `~2595` (перед `def _tt_guard_switcher_foreground`): два новых метода `_tt_probe_looks_stale`, `_tt_dumpsys_confirms_foreground`.
  - `~2856` (в retap-петле `_switch_tiktok`, между `self.p._safe_kb_probe(...)` и `log.warning('...не на своём профиле...')`): guard-блок с `break`.
- **Create:** `tests/test_account_switcher_tt_stale_ui.py` — все тесты WP #131.

Все команды pytest выполняются из корня autowarm-репо (или worktree-корня):
`python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -v`

---

## Task 1: Kill-switch `_tt_stale_ui_guard_enabled()`

**Files:**
- Modify: `account_switcher.py` (после строки 291)
- Test: `tests/test_account_switcher_tt_stale_ui.py`

- [ ] **Step 1: Создать тест-файл с заголовком и kill-switch тестами (failing)**

```python
"""WP #131 — TikTok own-profile stale-uiautomator guard.

Корень (разведка 2026-05-26): на шаге tt_2_profile_tab dumpsys стабильно видит
TikTok на переднем плане, но uiautomator отдаёт протухший XML лаунчера. Все 4
детектора own/logged_out/reauth/foreign возвращают False на stale XML → retap-петля
исчерпывается → ложный tt_profile_tab_broken. #130 (foreground) при этом исправен,
маркеры own-profile тоже — гниёт сам дамп.

Guard: при подтверждённом stale-UI (xml пустой/без TikTok + dumpsys стабильно=TikTok)
тапаем профиль и break из петли → существующая vision-based проверка аккаунта на
2911 решает (постит только при current==target, иначе bottomsheet-переключение).
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
    _tt_stale_ui_guard_enabled,
)

import pytest  # noqa: E402

TT_PKG = 'com.zhiliaoapp.musically'
LAUNCHER_PKG = 'com.sec.android.app.launcher'
TOP_TIKTOK = '  topResumedActivity=ActivityRecord{abc u0 com.zhiliaoapp.musically/.main.MainActivity}'
TOP_LAUNCHER = '  topResumedActivity=ActivityRecord{abc u0 com.sec.android.app.launcher/.activity}'


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(_asw.time, 'sleep', lambda *_a, **_kw: None)


def _make_switcher():
    publisher = MagicMock()
    publisher.platform = 'TikTok'
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


def test_kill_switch_default_on(monkeypatch):
    monkeypatch.delenv('TT_STALE_UI_OWN_PROFILE_GUARD', raising=False)
    assert _tt_stale_ui_guard_enabled() is True


def test_kill_switch_off(monkeypatch):
    monkeypatch.setenv('TT_STALE_UI_OWN_PROFILE_GUARD', '0')
    assert _tt_stale_ui_guard_enabled() is False
```

- [ ] **Step 2: Запустить — убедиться что падает на импорте**

Run: `python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -v`
Expected: FAIL — `ImportError: cannot import name '_tt_stale_ui_guard_enabled'`

- [ ] **Step 3: Добавить kill-switch в `account_switcher.py` после строки 291**

После функции `_tt_switch_fg_guard_enabled` (заканчивается на строке 291 `return os.environ.get('TT_SWITCH_FG_GUARD_ENABLED', '1') != '0'`) вставить:

```python


def _tt_stale_ui_guard_enabled() -> bool:
    """[WP #131] Kill-switch для stale-uiautomator guard в own-profile верификации.

    Default ON. `TT_STALE_UI_OWN_PROFILE_GUARD=0` → legacy: retap-петля
    исчерпывается на stale XML и падает с tt_profile_tab_broken.
    """
    return os.environ.get('TT_STALE_UI_OWN_PROFILE_GUARD', '1') != '0'
```

- [ ] **Step 4: Запустить — убедиться что 2 теста проходят**

Run: `python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_tt_stale_ui.py
git commit -m "feat(wp131): kill-switch _tt_stale_ui_guard_enabled"
```

---

## Task 2: Хелпер `_tt_probe_looks_stale`

Определяет, что probe-дамп протух: пустой XML ИЛИ XML без пакета TikTok вообще (лаунчер). Модалки (viewer-history/logged-out) содержат пакет TikTok → НЕ stale → не захватываются этим guard'ом (они out-of-scope, #159/#160).

**Files:**
- Modify: `account_switcher.py` (перед `def _tt_guard_switcher_foreground`, ~2595)
- Test: `tests/test_account_switcher_tt_stale_ui.py`

- [ ] **Step 1: Добавить тесты (failing)**

```python
def test_probe_looks_stale_empty():
    sw, _ = _make_switcher()
    assert sw._tt_probe_looks_stale('', TT_PKG) is True


def test_probe_looks_stale_launcher_no_tiktok():
    sw, _ = _make_switcher()
    xml = '<hierarchy><node package="com.sec.android.app.launcher" text="x"/></hierarchy>'
    assert sw._tt_probe_looks_stale(xml, TT_PKG) is True


def test_probe_not_stale_when_tiktok_present():
    sw, _ = _make_switcher()
    xml = '<hierarchy><node package="com.zhiliaoapp.musically" text="x"/></hierarchy>'
    assert sw._tt_probe_looks_stale(xml, TT_PKG) is False
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -k probe -v`
Expected: FAIL — `AttributeError: ... has no attribute '_tt_probe_looks_stale'`

- [ ] **Step 3: Добавить метод в `account_switcher.py` перед `def _tt_guard_switcher_foreground` (~2595)**

```python
    def _tt_probe_looks_stale(self, xml: str, target_pkg: str) -> bool:
        """[WP #131] True если probe-дамп протух: пустой ИЛИ без пакета TikTok.

        При stale uiautomator XML = снимок лаунчера (пакета TikTok в нём нет).
        Модалки TikTok (viewer-history / logged-out) содержат target_pkg →
        НЕ stale (идут прежним путём; out-of-scope #159/#160).
        """
        if not xml:
            return True
        return target_pkg not in xml
```

- [ ] **Step 4: Запустить — убедиться что проходят**

Run: `python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -k probe -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_tt_stale_ui.py
git commit -m "feat(wp131): _tt_probe_looks_stale helper"
```

---

## Task 3: Хелпер `_tt_dumpsys_confirms_foreground`

Читает `topResumedActivity` через dumpsys `reads` раз подряд (по умолчанию 3), все должны == target_pkg. Дёшево, без uiautomator. Тот же приём, что trust-dumpsys ветка WP #105 (`account_switcher.py:5709`).

**Files:**
- Modify: `account_switcher.py` (сразу после `_tt_probe_looks_stale`, ~2595)
- Test: `tests/test_account_switcher_tt_stale_ui.py`

- [ ] **Step 1: Добавить тесты (failing)**

```python
def test_dumpsys_confirms_when_stable():
    sw, _ = _make_switcher()
    sw.p.adb = MagicMock(return_value=TOP_TIKTOK)
    assert sw._tt_dumpsys_confirms_foreground(TT_PKG, reads=3) is True
    assert sw.p.adb.call_count == 3


def test_dumpsys_rejects_when_one_read_differs():
    sw, _ = _make_switcher()
    sw.p.adb = MagicMock(side_effect=[TOP_TIKTOK, TOP_LAUNCHER, TOP_TIKTOK])
    assert sw._tt_dumpsys_confirms_foreground(TT_PKG, reads=3) is False


def test_dumpsys_rejects_when_empty():
    sw, _ = _make_switcher()
    sw.p.adb = MagicMock(return_value='')
    assert sw._tt_dumpsys_confirms_foreground(TT_PKG, reads=3) is False
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -k dumpsys -v`
Expected: FAIL — `AttributeError: ... has no attribute '_tt_dumpsys_confirms_foreground'`

- [ ] **Step 3: Добавить метод в `account_switcher.py` сразу после `_tt_probe_looks_stale`**

```python
    def _tt_dumpsys_confirms_foreground(self, target_pkg: str,
                                        reads: int = 3,
                                        interval: float = 0.5) -> bool:
        """[WP #131] True если dumpsys СТАБИЛЬНО (reads чтений подряд) видит
        target_pkg на переднем плане. Без uiautomator (дёшево). Тот же приём,
        что trust-dumpsys ветка WP #105 (~5709)."""
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

- [ ] **Step 4: Запустить — убедиться что проходят**

Run: `python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -k dumpsys -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_tt_stale_ui.py
git commit -m "feat(wp131): _tt_dumpsys_confirms_foreground stability check"
```

---

## Task 4: Врезка guard'а в retap-петлю `_switch_tiktok`

**Files:**
- Modify: `account_switcher.py` (в retap-петле, между `self.p._safe_kb_probe(...)` блоком и `log.warning('...не на своём профиле...')`, ~2856)
- Test: `tests/test_account_switcher_tt_stale_ui.py`

- [ ] **Step 1: Добавить интеграционные тесты (failing)**

Эти тесты драйвят `_switch_tiktok` целиком. `sw.p.dump_ui` возвращает XML лаунчера → реальные детекторы own/logged_out/reauth/foreign все False → fall-through к guard'у. Хелперы `_tt_probe_looks_stale` / `_tt_dumpsys_confirms_foreground` (юнит-тестированы в Task 2-3) **мокаются напрямую** — это убирает хрупкость от подсчёта `adb`-вызовов внутри cold-start retap'а и изолирует тест wiring'а guard'а от реализации хелперов.

```python
LAUNCHER_XML = '<hierarchy rotation="0"><node package="com.sec.android.app.launcher" text="Phone"/></hierarchy>'


def _arm_stale_loop(sw):
    """Довести _switch_tiktok до retap-петли с stale-launcher probe.
    dump_ui=лаунчер → реальные own/logged_out/reauth/foreign детекторы вернут
    False → управление дойдёт до guard-блока."""
    sw._ensure_app_foregrounded = MagicMock(return_value=True)
    sw._ensure_foreground = MagicMock(return_value=True)
    sw._go_to_profile_tab = MagicMock()
    sw._tt_smart_tap_profile = MagicMock(return_value=True)
    sw._tt_dismiss_security_prompt = MagicMock(return_value=False)
    sw._tt_dismiss_profile_promo_dialog = MagicMock(return_value=False)
    sw.p.dump_ui = MagicMock(return_value=LAUNCHER_XML)
    sw.p.adb = MagicMock(return_value=TOP_TIKTOK)


def test_stale_ui_guard_breaks_and_posts_when_vision_matches_target():
    """Главный кейс: stale-UI + vision читает current==target → break →
    _tap_plus_and_verify (постим), эмит tt_own_profile_stale_ui, профиль-тап до break."""
    sw, log_calls = _make_switcher()
    _arm_stale_loop(sw)
    sw._tt_probe_looks_stale = MagicMock(return_value=True)
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw._read_screen_hybrid = MagicMock(return_value=([], 'vision', None))
    sw._vision_read_current_account = MagicMock(return_value='axilor_brand')
    sentinel = MagicMock(success=True, final_step='tt_fp_editor')
    sw._tap_plus_and_verify = MagicMock(return_value=sentinel)

    result = sw._switch_tiktok('axilor_brand', UI_CONSTANTS['TikTok'])

    assert result is sentinel
    assert _has_category(log_calls, 'tt_own_profile_stale_ui')
    sw._tap_plus_and_verify.assert_called_once()
    # профиль-тап сделан перед break (smart_tap → True, coords fallback не нужен)
    sw._tt_smart_tap_profile.assert_called()


def test_stale_ui_guard_routes_to_switcher_when_vision_reads_other_account():
    """Wrong-account: stale-UI + vision читает ДРУГОЙ аккаунт → НЕ постит напрямую,
    идёт в _open_tt_account_switcher (ответ на Codex P1)."""
    sw, log_calls = _make_switcher()
    _arm_stale_loop(sw)
    sw._tt_probe_looks_stale = MagicMock(return_value=True)
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw._read_screen_hybrid = MagicMock(return_value=([], 'vision', None))
    sw._vision_read_current_account = MagicMock(return_value='someone_else')
    sw._tap_plus_and_verify = MagicMock()
    sw._open_tt_account_switcher = MagicMock(return_value=(None, 'tt_account_sheet_closed_before_parse'))

    result = sw._switch_tiktok('axilor_brand', UI_CONSTANTS['TikTok'])

    assert _has_category(log_calls, 'tt_own_profile_stale_ui')
    sw._open_tt_account_switcher.assert_called_once()
    # прямой пост (ветка current==target) НЕ вызван
    sw._tap_plus_and_verify.assert_not_called()
    assert not result.success


def test_stale_ui_guard_not_triggered_when_dumpsys_unstable():
    """dumpsys нестабилен → _tt_dumpsys_confirms_foreground=False → guard НЕ
    срабатывает → старая retap-петля исчерпывается → tt_2_not_own_profile."""
    sw, log_calls = _make_switcher()
    _arm_stale_loop(sw)
    sw._tt_probe_looks_stale = MagicMock(return_value=True)
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=False)
    sw._read_screen_hybrid = MagicMock(return_value=([], 'vision', None))
    sw._vision_read_current_account = MagicMock(return_value=None)

    result = sw._switch_tiktok('axilor_brand', UI_CONSTANTS['TikTok'])

    assert not _has_category(log_calls, 'tt_own_profile_stale_ui')
    assert not result.success
    assert result.final_step == 'tt_2_not_own_profile', result.final_step


def test_stale_ui_guard_off_via_kill_switch(monkeypatch):
    """kill-switch=0 → guard выключен (helpers даже не вызываются) → старый retap/fail."""
    monkeypatch.setenv('TT_STALE_UI_OWN_PROFILE_GUARD', '0')
    sw, log_calls = _make_switcher()
    _arm_stale_loop(sw)
    sw._tt_probe_looks_stale = MagicMock(return_value=True)
    sw._tt_dumpsys_confirms_foreground = MagicMock(return_value=True)
    sw._read_screen_hybrid = MagicMock(return_value=([], 'vision', None))
    sw._vision_read_current_account = MagicMock(return_value=None)

    result = sw._switch_tiktok('axilor_brand', UI_CONSTANTS['TikTok'])

    assert not _has_category(log_calls, 'tt_own_profile_stale_ui')
    assert result.final_step == 'tt_2_not_own_profile', result.final_step
```

> Замечание о порядке вычисления: в guard-условии `_tt_stale_ui_guard_enabled()` стоит первым, поэтому при kill-switch=0 хелперы не вызываются (short-circuit `and`). Так задумано.

- [ ] **Step 2: Запустить — убедиться что падают**

Run: `python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -k stale_ui_guard -v`
Expected: FAIL — главный кейс падает (guard ещё не врезан: петля исчерпывается → `tt_2_not_own_profile`, `tt_own_profile_stale_ui` не эмитится, `_tap_plus_and_verify` не вызван).

- [ ] **Step 3: Врезать guard в `account_switcher.py`**

Найти в retap-петле `_switch_tiktok` блок (после `_safe_kb_probe`, перед `log.warning`):

```python
            self.p._safe_kb_probe(
                xml_probe, step='tt_2_profile_tab',
            )

            log.warning(f'[FIX: TT-own-profile] не на своём профиле (retap {retap+1}/3)')
```

Вставить guard МЕЖДУ закрывающей скобкой `_safe_kb_probe(...)` и строкой `log.warning(...не на своём профиле...)`:

```python
            self.p._safe_kb_probe(
                xml_probe, step='tt_2_profile_tab',
            )

            # [WP #131] stale-uiautomator guard: dumpsys стабильно видит TikTok, но
            # xml_probe — протухший лаунчер/пусто → все 4 детектора ложно-False.
            # Не жжём retap'ы и НЕ _fail-им на stale XML: тапаем профиль ещё раз
            # (чтобы реальный экран был профилем, а не Feed) и break из петли —
            # отработает vision-based проверка target-аккаунта ниже (2911+),
            # которая постит ТОЛЬКО при current==target, иначе bottomsheet-switch.
            if _tt_stale_ui_guard_enabled() \
                    and self._tt_probe_looks_stale(xml_probe, cfg['package']) \
                    and self._tt_dumpsys_confirms_foreground(cfg['package']):
                self.p.log_event(
                    'account_switch',
                    f'tt_own_profile_stale_ui: dumpsys=TikTok стабилен, uiautomator '
                    f'stale (retap {retap+1}) → профиль-тап + break в vision verify',
                    meta={'category': 'tt_own_profile_stale_ui',
                          'retap': retap + 1, 'platform': 'TikTok',
                          'probe_empty': not bool(xml_probe)})
                self._save_dump(f'tt_2_stale_ui_retap{retap+1}', xml_probe)
                if not self._tt_smart_tap_profile():
                    self._go_to_profile_tab(cfg, f'tt_2_stale_retap{retap+1}')
                time.sleep(POST_TAP_WAIT_S + 1)
                break

            log.warning(f'[FIX: TT-own-profile] не на своём профиле (retap {retap+1}/3)')
```

- [ ] **Step 4: Запустить guard-тесты — убедиться что проходят**

Run: `python3 -m pytest tests/test_account_switcher_tt_stale_ui.py -k stale_ui_guard -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Запустить весь новый файл + смежные TT-тесты (регрессия)**

Run:
```bash
python3 -m pytest tests/test_account_switcher_tt_stale_ui.py \
  tests/test_account_switcher_tt.py \
  tests/test_account_switcher_tt_switch_fg_guard.py \
  tests/test_account_switcher_profile_promo_dismiss.py \
  tests/test_account_switcher_modal_dismiss.py -v
```
Expected: PASS (все, включая существующие — guard не ломает прежние пути; помни про conftest engine.dispose fixture для live-DB, к этим unit-тестам не относится).

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_tt_stale_ui.py
git commit -m "feat(wp131): stale-uiautomator guard breaks retap-loop to vision account verify"
```

---

## Деплой (после approve диффа пользователем)

- `codex review` диффа (раундами до 0 P1/P2) — стандартная практика, ДО деплоя.
- Python-публикатор спавнится свежим на каждую задачу → **PM2 restart НЕ нужен**.
- Раскатка: cherry-pick коммитов в prod autowarm `/root/.openclaw/workspace-genri/autowarm/` на `main` (НЕ force-push; auto-push hook сам разнесёт в GenGo2/delivery).
- Зелёный pytest на ветке перед merge (parallel-sessions practice); проверить, что чужой `.bak-wp132` не затронут.
- Проверка на проде за 24ч: `SELECT count(*) FROM publish_tasks p, jsonb_array_elements(p.events) e WHERE e->'meta'->>'category'='tt_own_profile_stale_ui' AND p.updated_at >= '<deploy_date>'` + динамика `error_code='tt_profile_tab_broken'` (цель — к нулю в stale-bucket). Кросс-сверка task'ов с событием против финального статуса (done/published = безопасно).

## Self-review (выполнено при написании плана)

- **Spec coverage:** §4.1 → Task 3 (`_tt_dumpsys_confirms_foreground`); §4.2 врезка+break → Task 4; §4.2 stale-детект → Task 2 (`_tt_probe_looks_stale`); §4.3 account-verify через существующий 2911 → покрыто тестами Task 4 (match/wrong-account); §5 kill-switch → Task 1; §6 событие `tt_own_profile_stale_ui` → Task 4; §7 тест-матрица → Task 4 тесты. Out-of-scope модалки (§3) — отдельные #159/#160, не в плане.
- **Placeholders:** нет — каждый шаг с полным кодом и точной командой.
- **Type consistency:** `_tt_stale_ui_guard_enabled` (Task 1) ↔ Task 4; `_tt_probe_looks_stale(xml, target_pkg)` (Task 2) ↔ Task 4 вызов с `cfg['package']`; `_tt_dumpsys_confirms_foreground(target_pkg, reads, interval)` (Task 3) ↔ Task 4 вызов; событие `tt_own_profile_stale_ui` консистентно.
