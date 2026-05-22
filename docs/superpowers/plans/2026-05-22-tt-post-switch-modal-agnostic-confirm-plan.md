# TT post-switch modal-agnostic confirm — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать остаточные ложные `tt_post_switch_verify_unrecoverable` (1–3/сутки) в TikTok, добавив modal-agnostic confirm-слой поверх существующей post-switch проверки.

**Architecture:** Три независимых, kill-switch'абельных кирпича в `account_switcher.py`: (1) ловля баннера «Вы вошли как X» как screen-independent сигнал успеха; (2) generic dismiss-loop по консервативному списку безопасных кнопок (вместо per-модального whitelist); (3) settle-retry для переходных экранов. Реворк `_tt_handle_post_switch_unknown` оркестрирует их, сохраняя fail-closed и mismatch-детект.

**Tech Stack:** Python 3, pytest + unittest.mock, Android uiautomator XML dumps. Код в `account_switcher.py` (autowarm). Spec: `docs/superpowers/specs/2026-05-22-tt-post-switch-modal-agnostic-confirm-design.md`.

---

## Контекст репозитория (важно для исполнителя)

- **Код и тесты живут в репо autowarm**, рабочая копия для разработки: `/home/claude-user/autowarm-testbench/` (ветка `main`). НЕ в `contenthunter` (там только spec/plan/evidence).
- Перед началом — изолировать работу: создать ветку/worktree в autowarm-testbench (см. Task 0), чтобы не мешать параллельным сессиям. `git fetch` перед стартом.
- Деплой в прод (`/root/.openclaw/workspace-genri/autowarm/`) — отдельный шаг (Task 11): cherry-pick в prod main (auto-push hook → GenGo2/delivery-contenthunter). Python-код в проде подхватывается per-task spawn'ом, **без** PM2 restart.
- Запуск тестов: `cd /home/claude-user/autowarm-testbench && pytest tests/<file> -v`.

## Карта файлов

| Файл | Действие | Ответственность |
|---|---|---|
| `account_switcher.py` | Modify | Новые module-хелперы (banner/safe-dismiss/transitional) + 3 instance-метода + реворк `_tt_handle_post_switch_unknown` + врезка в `_switch_tiktok` |
| `tests/test_tt_post_switch_modal_agnostic.py` | Create | Unit + integration для нового слоя |
| `tests/fixtures/tt_friends_promo_modal.xml` | Create | Под-режим A — модалка «Подпишитесь на друзей» |
| `tests/fixtures/tt_security_check_modal.xml` | Create | Под-режим C — «Быстрая проверка безопасности» |
| `tests/fixtures/tt_transitional_switch_sheet.xml` | Create | Под-режим B — шторка свитча + спиннер |
| `tests/fixtures/tt_login_banner.xml` | Create | Баннер «Вы вошли как X» |
| `tests/test_account_switcher_modal_dismiss.py` | Modify | Мигрировать 6 integration-тестов на generic-flow (10 unit-тестов матчера остаются) |
| `tests/test_post_switch_renav.py` | Modify | Адаптировать recovery-flow тесты под новый порядок вызовов |

**Существующие реальные фикстуры для переиспользования** (НЕ создавать заново): `tt_post_switch_5817_relism_e.xml` (профиль с @handle), `tt_feed_no_sheet.xml` (лента), `tt_post_switch_modal_save_login_7307_renav.xml` (реальная модалка «Сохранить данные…»/«Не сейчас»).

---

## Task 0: Изоляция и зелёный baseline

**Files:** — (только git)

- [ ] **Step 1: Fetch + worktree в autowarm-testbench**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add -b wp67-l3-modal-agnostic /home/claude-user/autowarm-testbench/.wt-wp67 origin/main 2>/dev/null || git checkout -b wp67-l3-modal-agnostic origin/main
```
(Если worktree-конвенции в этом репо нет — допустима локальная ветка от `origin/main`. Главное: не коммитить в `main` и не трогать чужие незакоммиченные изменения. `git status` перед стартом — чисто.)

- [ ] **Step 2: Прогнать релевантные тесты — baseline зелёный**

Run: `cd /home/claude-user/autowarm-testbench && pytest tests/test_post_switch_renav.py tests/test_account_switcher_modal_dismiss.py tests/test_account_switcher_tt.py -q`
Expected: PASS (зелёный baseline до изменений).

---

## Task 1: `_tt_read_login_confirm_banner` (кирпич 1, чистая функция)

**Files:**
- Modify: `account_switcher.py` (module-level, рядом с `_TT_FEED_MARKERS` ~строка 240)
- Test: `tests/test_tt_post_switch_modal_agnostic.py`
- Fixture: `tests/fixtures/tt_login_banner.xml`

- [ ] **Step 1: Создать фикстуру баннера**

`tests/fixtures/tt_login_banner.xml`:
```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node text="Вы вошли как WellroomCare" content-desc="" class="android.widget.TextView" bounds="[60,180][1020,260]" clickable="false" />
    <node text="Рекомендации" content-desc="" class="android.widget.TextView" bounds="[400,90][680,150]" clickable="false" />
  </node>
</hierarchy>
```

- [ ] **Step 2: Написать падающий тест**

В новом файле `tests/test_tt_post_switch_modal_agnostic.py` (шапка как в `test_account_switcher_modal_dismiss.py`: `sys.path.insert`, `FIXTURES`, `_read_fixture`):
```python
from account_switcher import (  # noqa: E402
    _tt_read_login_confirm_banner,
)

def test_banner_extracts_handle():
    xml = _read_fixture('tt_login_banner.xml')
    assert _tt_read_login_confirm_banner(xml) == 'WellroomCare'

def test_banner_logged_in_as_english():
    xml = ('<hierarchy><node text="Logged in as nofomo93" '
           'class="android.widget.TextView" bounds="[0,0][100,50]"/></hierarchy>')
    assert _tt_read_login_confirm_banner(xml) == 'nofomo93'

def test_banner_takes_first_token_only():
    xml = ('<hierarchy><node text="Вы вошли как el_cosmo46. Готово" '
           'class="android.widget.TextView" bounds="[0,0][100,50]"/></hierarchy>')
    assert _tt_read_login_confirm_banner(xml) == 'el_cosmo46'

def test_banner_none_on_profile():
    xml = _read_fixture('tt_post_switch_5817_relism_e.xml')
    assert _tt_read_login_confirm_banner(xml) is None

def test_banner_none_on_empty():
    assert _tt_read_login_confirm_banner('') is None
```

- [ ] **Step 3: Запуск — убедиться, что падает**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -q`
Expected: FAIL (`ImportError: cannot import name '_tt_read_login_confirm_banner'`).

- [ ] **Step 4: Реализация (module-level)**

```python
# [WP #67 Layer 3 — 2026-05-22] Banner «Вы вошли как X» — screen-independent
# сигнал успеха свитча. TikTok показывает его ~2с после переключения.
_TT_LOGIN_BANNER_RES = (
    re.compile(r'(?:вы\s+)?вошли\s+как\s+(\S+)', re.IGNORECASE),
    re.compile(r'logged\s+in\s+as\s+(\S+)', re.IGNORECASE),
    re.compile(r'switched\s+to\s+(\S+)', re.IGNORECASE),
)


def _tt_read_login_confirm_banner(xml: str):
    """Извлечь handle из баннера подтверждения свитча. None если нет.

    Возвращает RAW handle (без нормализации) — caller сверяет через
    `_normalize_username`. Берёт первый токен после «вошли как».
    """
    if not xml:
        return None
    for el in parse_ui_dump(xml):
        label = (el.label or '').strip()
        if not label:
            continue
        for rx in _TT_LOGIN_BANNER_RES:
            m = rx.search(label)
            if m:
                handle = m.group(1).strip().strip('.,!?»«"\'')
                if handle:
                    return handle
    return None
```
(`re` и `parse_ui_dump` уже доступны в модуле.)

- [ ] **Step 5: Запуск — зелёный**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -q`
Expected: PASS (5 тестов).

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_tt_post_switch_modal_agnostic.py tests/fixtures/tt_login_banner.xml
git commit -m "feat(tt-switch): WP #67 L3 brick 1 — login-confirm banner reader"
```

---

## Task 2: `_tt_find_safe_dismiss` (кирпич 2, чистая функция)

**Files:**
- Modify: `account_switcher.py` (module-level, рядом с Task 1 хелпером)
- Test: `tests/test_tt_post_switch_modal_agnostic.py`
- Fixtures: `tt_friends_promo_modal.xml`, `tt_security_check_modal.xml`

- [ ] **Step 1: Создать фикстуры модалок**

`tests/fixtures/tt_friends_promo_modal.xml` (под-режим A — «Подпишитесь на друзей», крестик content-desc «Закрыть»):
```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node text="Подписки" class="android.widget.TextView" bounds="[300,90][460,150]" clickable="false" />
    <node text="Рекомендации" class="android.widget.TextView" bounds="[480,90][760,150]" clickable="false" />
    <node text="Подпишитесь на друзей" class="android.widget.TextView" bounds="[120,820][960,900]" clickable="false" />
    <node text="" content-desc="Закрыть" class="android.widget.Button" bounds="[960,820][1040,900]" clickable="true" />
    <node text="Подписаться" class="android.widget.Button" bounds="[820,960][1000,1030]" clickable="true" />
  </node>
</hierarchy>
```

`tests/fixtures/tt_security_check_modal.xml` (под-режим C — «Быстрая проверка безопасности», крестик «Закрыть» + affirmative «Продолжить»):
```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node text="Быстрая проверка безопасности" class="android.widget.TextView" bounds="[120,900][960,980]" clickable="false" />
    <node text="" content-desc="Закрыть" class="android.widget.Button" bounds="[960,820][1040,900]" clickable="true" />
    <node text="Продолжить" class="android.widget.Button" bounds="[120,1700][960,1790]" clickable="true" />
  </node>
</hierarchy>
```

- [ ] **Step 2: Написать падающий тест**

```python
from account_switcher import _tt_find_safe_dismiss  # add to imports

def test_safe_dismiss_friends_modal_close():
    xml = _read_fixture('tt_friends_promo_modal.xml')
    assert _tt_find_safe_dismiss(xml) == 'Закрыть'

def test_safe_dismiss_security_modal_close_not_continue():
    """Должен взять «Закрыть», НЕ «Продолжить» (affirmative исключён)."""
    xml = _read_fixture('tt_security_check_modal.xml')
    assert _tt_find_safe_dismiss(xml) == 'Закрыть'

def test_safe_dismiss_real_save_login_modal_ne_seychas():
    """Реальный дамп: кнопка «Не сейчас»."""
    xml = _read_fixture('tt_post_switch_modal_save_login_7307_renav.xml')
    assert _tt_find_safe_dismiss(xml) == 'Не сейчас'

def test_safe_dismiss_none_on_feed():
    xml = _read_fixture('tt_feed_no_sheet.xml')
    assert _tt_find_safe_dismiss(xml) is None

def test_safe_dismiss_none_on_profile():
    xml = _read_fixture('tt_post_switch_5817_relism_e.xml')
    assert _tt_find_safe_dismiss(xml) is None

def test_safe_dismiss_ignores_affirmative_only():
    """Экран только с affirmative-кнопками → None."""
    xml = ('<hierarchy><node text="Разрешить" class="android.widget.Button" '
           'bounds="[0,0][100,50]" clickable="true"/>'
           '<node text="Открыть настройки" class="android.widget.Button" '
           'bounds="[0,60][100,110]" clickable="true"/></hierarchy>')
    assert _tt_find_safe_dismiss(xml) is None

def test_safe_dismiss_none_on_empty():
    assert _tt_find_safe_dismiss('') is None
```

- [ ] **Step 3: Запуск — падает**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k safe_dismiss -q`
Expected: FAIL (ImportError).

- [ ] **Step 4: Реализация (module-level)**

```python
# [WP #67 Layer 3 — 2026-05-22] Modal-agnostic dismiss: консервативный список
# БЕЗОПАСНЫХ кнопок-закрытия. Affirmative-кнопки (продолжить/разрешить/ок/
# подписаться/открыть настройки/allow/continue/follow) ЯВНО исключены —
# тап по dismiss не подпишет, не выдаст пермишены, не запустит security-флоу.
_TT_SAFE_DISMISS_LABELS = frozenset({
    'не сейчас', 'закрыть', 'не разрешать', 'пропустить', 'отмена',
    'позже', 'not now', 'close', 'skip', 'cancel', "don't allow",
    'dismiss', 'later',
})


def _tt_find_safe_dismiss(xml: str):
    """Найти clickable safe-dismiss кнопку. Вернуть её label или None.

    Match: `el.label.strip().lower()` ∈ `_TT_SAFE_DISMISS_LABELS` И `el.clickable`.
    `el.label` = text + content-desc (см. UiElement.label) — крестик с
    content-desc «Закрыть» матчится.
    """
    if not xml:
        return None
    for el in parse_ui_dump(xml):
        if not el.clickable:
            continue
        lbl = (el.label or '').strip().lower()
        if lbl in _TT_SAFE_DISMISS_LABELS:
            return el.label.strip()
    return None
```

- [ ] **Step 5: Запуск — зелёный**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k safe_dismiss -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_tt_post_switch_modal_agnostic.py tests/fixtures/tt_friends_promo_modal.xml tests/fixtures/tt_security_check_modal.xml
git commit -m "feat(tt-switch): WP #67 L3 brick 2 — generic safe-dismiss matcher"
```

---

## Task 3: `_tt_screen_is_transitional` (кирпич 3, чистая функция)

**Files:**
- Modify: `account_switcher.py` (module-level)
- Test: `tests/test_tt_post_switch_modal_agnostic.py`
- Fixture: `tt_transitional_switch_sheet.xml`

- [ ] **Step 1: Создать фикстуру переходного экрана**

`tests/fixtures/tt_transitional_switch_sheet.xml` (шторка свитча ещё видна + спиннер):
```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node text="Сменить аккаунт" class="android.widget.TextView" bounds="[120,1300][500,1370]" clickable="false" />
    <node text="" content-desc="" class="android.widget.ProgressBar" bounds="[500,1100][580,1180]" clickable="false" />
  </node>
</hierarchy>
```

- [ ] **Step 2: Написать падающий тест**

```python
from account_switcher import _tt_screen_is_transitional  # add to imports

def test_transitional_true_on_switch_sheet_with_spinner():
    xml = _read_fixture('tt_transitional_switch_sheet.xml')
    assert _tt_screen_is_transitional(xml) is True

def test_transitional_false_on_profile():
    xml = _read_fixture('tt_post_switch_5817_relism_e.xml')
    assert _tt_screen_is_transitional(xml) is False

def test_transitional_false_on_feed():
    xml = _read_fixture('tt_feed_no_sheet.xml')
    assert _tt_screen_is_transitional(xml) is False

def test_transitional_false_on_empty():
    assert _tt_screen_is_transitional('') is False
```

- [ ] **Step 3: Запуск — падает**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k transitional -q`
Expected: FAIL (ImportError).

- [ ] **Step 4: Реализация (module-level)**

```python
# [WP #67 Layer 3 — 2026-05-22] Переходный/loading-экран: свитч ещё не
# завершён (шторка аккаунтов видна или крутится прогресс). Сигнал для
# settle-retry вместо мгновенного fail.
_TT_TRANSITIONAL_MARKERS = ('Сменить аккаунт', 'Управление аккаунтами')


def _tt_screen_is_transitional(xml: str) -> bool:
    """True если на экране маркер незавершённого свитча (sheet/spinner)."""
    if not xml:
        return False
    for marker in _TT_TRANSITIONAL_MARKERS:
        if marker in xml:
            return True
    return 'ProgressBar' in xml
```

- [ ] **Step 5: Запуск — зелёный**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k transitional -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py tests/test_tt_post_switch_modal_agnostic.py tests/fixtures/tt_transitional_switch_sheet.xml
git commit -m "feat(tt-switch): WP #67 L3 brick 3 — transitional-screen detector"
```

---

## Task 4: `_tt_post_switch_confirm` (instance: banner + profile-read)

**Files:**
- Modify: `account_switcher.py` (instance-метод рядом с `_post_switch_verify_handle` ~4663)
- Test: `tests/test_tt_post_switch_modal_agnostic.py`

- [ ] **Step 1: Написать падающий тест**

```python
import os
from unittest.mock import MagicMock
from account_switcher import AccountSwitcher  # add to imports

def _bare_switcher():
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.p = MagicMock()
    return sw

def test_confirm_banner_match_short_circuits(monkeypatch):
    monkeypatch.delenv('TT_POST_SWITCH_BANNER_DISABLED', raising=False)
    sw = _bare_switcher()
    sw._normalize_username = lambda s: s.strip().lstrip('@').lower()
    sw._post_switch_verify_handle = MagicMock()  # НЕ должен вызваться
    xml = '<hierarchy><node text="Вы вошли как WellroomCare" class="x" bounds="[0,0][9,9]"/></hierarchy>'
    status, current = sw._tt_post_switch_confirm('wellroomcare', xml, header_y_max=260)
    assert status == 'match'
    sw._post_switch_verify_handle.assert_not_called()

def test_confirm_no_banner_falls_through_to_profile_read():
    sw = _bare_switcher()
    sw._normalize_username = lambda s: s.strip().lstrip('@').lower()
    sw._post_switch_verify_handle = MagicMock(return_value=('match', 'relism_e'))
    xml = '<hierarchy><node text="Профиль" class="x" bounds="[0,0][9,9]"/></hierarchy>'
    status, current = sw._tt_post_switch_confirm('relism_e', xml, header_y_max=260)
    assert (status, current) == ('match', 'relism_e')
    sw._post_switch_verify_handle.assert_called_once()

def test_confirm_banner_disabled_by_killswitch(monkeypatch):
    monkeypatch.setenv('TT_POST_SWITCH_BANNER_DISABLED', '1')
    sw = _bare_switcher()
    sw._normalize_username = lambda s: s.strip().lstrip('@').lower()
    sw._post_switch_verify_handle = MagicMock(return_value=('unknown', None))
    xml = '<hierarchy><node text="Вы вошли как WellroomCare" class="x" bounds="[0,0][9,9]"/></hierarchy>'
    status, current = sw._tt_post_switch_confirm('wellroomcare', xml, header_y_max=260)
    assert status == 'unknown'  # banner проигнорирован, ушли в profile-read
    sw._post_switch_verify_handle.assert_called_once()
```

- [ ] **Step 2: Запуск — падает**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k confirm -q`
Expected: FAIL (`AttributeError: '_tt_post_switch_confirm'`).

- [ ] **Step 3: Реализация (instance-метод)**

```python
def _tt_post_switch_confirm(self, target: str, xml: str,
                            header_y_max: int) -> tuple:
    """[WP #67 L3] Confirm свитча: banner (best-effort) → profile-read.

    Возвращает ('match'|'mismatch'|'unknown', current) как
    `_post_switch_verify_handle`. Banner — авторитетный сигнал успеха,
    минующий чтение профиля. Под kill-switch TT_POST_SWITCH_BANNER_DISABLED.
    """
    if os.environ.get('TT_POST_SWITCH_BANNER_DISABLED') != '1':
        banner = _tt_read_login_confirm_banner(xml)
        if banner and self._normalize_username(banner) == \
                self._normalize_username(target):
            self.p.log_event(
                'account_switch', 'tt_post_switch_confirmed_via_banner',
                meta={'category': 'tt_post_switch_confirmed_via_banner',
                      'target': target, 'banner_handle': banner,
                      'probe_site': 'confirm'},
            )
            return ('match', banner)
    return self._post_switch_verify_handle(target, xml, header_y_max=header_y_max)
```

- [ ] **Step 4: Запуск — зелёный**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k confirm -q`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_tt_post_switch_modal_agnostic.py
git commit -m "feat(tt-switch): WP #67 L3 — _tt_post_switch_confirm (banner+profile)"
```

---

## Task 5: `_tt_dismiss_and_confirm_loop` (instance: generic dismiss-цикл)

**Files:**
- Modify: `account_switcher.py` (instance-метод)
- Test: `tests/test_tt_post_switch_modal_agnostic.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_dismiss_loop_recovers_after_close(monkeypatch):
    monkeypatch.delenv('TT_POST_SWITCH_GENERIC_DISMISS_DISABLED', raising=False)
    sw = _bare_switcher()
    sw._save_dump = MagicMock()
    modal_xml = _read_fixture('tt_friends_promo_modal.xml')
    profile_xml = _read_fixture('tt_post_switch_5817_relism_e.xml')
    sw.p.tap_element = MagicMock(return_value=True)
    sw.p.dump_ui = MagicMock(return_value=profile_xml)  # после dismiss — профиль
    sw._tt_post_switch_confirm = MagicMock(return_value=('match', 'relism_e'))
    status, current, xml = sw._tt_dismiss_and_confirm_loop(
        'relism_e', modal_xml, header_y_max=260,
        probe_site='pre_feed', label='tt_4', attempt=0)
    assert status == 'match'
    sw.p.tap_element.assert_called_once()

def test_dismiss_loop_no_safe_button_returns_unknown():
    sw = _bare_switcher()
    sw._save_dump = MagicMock()
    feed_xml = _read_fixture('tt_feed_no_sheet.xml')
    status, current, xml = sw._tt_dismiss_and_confirm_loop(
        'relism_e', feed_xml, header_y_max=260,
        probe_site='pre_feed', label='tt_4', attempt=0)
    assert status == 'unknown'
    assert xml == feed_xml  # без safe-кнопки xml не менялся

def test_dismiss_loop_killswitch(monkeypatch):
    monkeypatch.setenv('TT_POST_SWITCH_GENERIC_DISMISS_DISABLED', '1')
    sw = _bare_switcher()
    modal_xml = _read_fixture('tt_friends_promo_modal.xml')
    status, current, xml = sw._tt_dismiss_and_confirm_loop(
        'relism_e', modal_xml, header_y_max=260,
        probe_site='pre_feed', label='tt_4', attempt=0)
    assert status == 'unknown'
```

- [ ] **Step 2: Запуск — падает**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k dismiss_loop -q`
Expected: FAIL (AttributeError).

- [ ] **Step 3: Реализация (instance-метод)**

```python
def _tt_dismiss_and_confirm_loop(self, target: str, xml: str,
                                 header_y_max: int, *, probe_site: str,
                                 label: str, attempt: int) -> tuple:
    """[WP #67 L3] Generic modal-dismiss цикл. Возвращает (status, current, xml).

    Пока на экране есть safe-dismiss кнопка (cap TT_DISMISS_MAX): тап →
    settle → re-dump → confirm. match/mismatch → возврат с новым xml.
    Нет safe-кнопки → ('unknown', None, xml). Под kill-switch
    TT_POST_SWITCH_GENERIC_DISMISS_DISABLED.
    """
    if os.environ.get('TT_POST_SWITCH_GENERIC_DISMISS_DISABLED') == '1':
        return ('unknown', None, xml)
    cap = int(os.environ.get('TT_DISMISS_MAX', '2'))
    for i in range(cap):
        button = _tt_find_safe_dismiss(xml)
        if button is None:
            break
        self.p.log_event(
            'account_switch', 'tt_post_switch_modal_dismissed_generic',
            meta={'category': 'tt_post_switch_modal_dismissed_generic',
                  'button_label': button, 'probe_site': probe_site,
                  'attempt': i + 1, 'target': target},
        )
        if not self.p.tap_element(xml, [button], clickable_only=True):
            break
        time.sleep(POST_TAP_WAIT_S)
        xml = self.p.dump_ui(retries=1) or ''
        self._save_dump(f'{label}_generic_dismiss_{i + 1}', xml)
        status, current = self._tt_post_switch_confirm(
            target, xml, header_y_max=header_y_max)
        if status in ('match', 'mismatch'):
            return (status, current, xml)
    return ('unknown', None, xml)
```

- [ ] **Step 4: Запуск — зелёный**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k dismiss_loop -q`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_tt_post_switch_modal_agnostic.py
git commit -m "feat(tt-switch): WP #67 L3 — generic dismiss-and-confirm loop"
```

---

## Task 6: `_tt_early_banner_confirm` (instance: ранняя ловля баннера у pick)

**Files:**
- Modify: `account_switcher.py` (instance-метод)
- Test: `tests/test_tt_post_switch_modal_agnostic.py`

- [ ] **Step 1: Написать падающий тест**

```python
def test_early_banner_confirm_true(monkeypatch):
    monkeypatch.delenv('TT_POST_SWITCH_BANNER_DISABLED', raising=False)
    sw = _bare_switcher()
    sw._save_dump = MagicMock()
    sw._normalize_username = lambda s: s.strip().lstrip('@').lower()
    sw.p.dump_ui = MagicMock(
        return_value=_read_fixture('tt_login_banner.xml'))
    assert sw._tt_early_banner_confirm('wellroomcare', step='tt_4_early') is True

def test_early_banner_confirm_false_no_banner():
    sw = _bare_switcher()
    sw._save_dump = MagicMock()
    sw._normalize_username = lambda s: s.strip().lstrip('@').lower()
    sw.p.dump_ui = MagicMock(
        return_value=_read_fixture('tt_feed_no_sheet.xml'))
    assert sw._tt_early_banner_confirm('relism_e', step='tt_4_early') is False

def test_early_banner_confirm_killswitch(monkeypatch):
    monkeypatch.setenv('TT_POST_SWITCH_BANNER_DISABLED', '1')
    sw = _bare_switcher()
    sw.p.dump_ui = MagicMock()
    assert sw._tt_early_banner_confirm('wellroomcare', step='tt_4_early') is False
    sw.p.dump_ui.assert_not_called()
```

- [ ] **Step 2: Запуск — падает**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k early_banner -q`
Expected: FAIL (AttributeError).

- [ ] **Step 3: Реализация (instance-метод)**

```python
def _tt_early_banner_confirm(self, target: str, step: str) -> bool:
    """[WP #67 L3] Быстрый dump сразу после pick (до settle-wait) — ловим
    баннер «Вы вошли как X» пока он жив (~2с). True если handle ≈ target.
    Под kill-switch TT_POST_SWITCH_BANNER_DISABLED.
    """
    if os.environ.get('TT_POST_SWITCH_BANNER_DISABLED') == '1':
        return False
    xml = self.p.dump_ui(retries=1) or ''
    self._save_dump(step, xml)
    banner = _tt_read_login_confirm_banner(xml)
    if banner and self._normalize_username(banner) == \
            self._normalize_username(target):
        self.p.log_event(
            'account_switch', 'tt_post_switch_confirmed_via_banner',
            meta={'category': 'tt_post_switch_confirmed_via_banner',
                  'target': target, 'banner_handle': banner,
                  'probe_site': 'early'},
        )
        return True
    return False
```

- [ ] **Step 4: Запуск — зелёный**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k early_banner -q`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_tt_post_switch_modal_agnostic.py
git commit -m "feat(tt-switch): WP #67 L3 — early login-banner confirm at pick"
```

---

## Task 7: Реворк `_tt_handle_post_switch_unknown` (оркестрация)

**Files:**
- Modify: `account_switcher.py:4797-4936` (заменить тело метода)
- Test: `tests/test_tt_post_switch_modal_agnostic.py`

- [ ] **Step 1: Написать падающие integration-тесты (3 под-режима + happy)**

```python
def _recovery_switcher():
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.p = MagicMock()
    sw.p.log_event = MagicMock()
    sw._save_dump = MagicMock()
    sw._normalize_username = lambda s: s.strip().lstrip('@').lower()
    fail_sentinel = MagicMock(name='SwitchResult(success=False)')
    fail_sentinel.success = False
    sw._fail = MagicMock(return_value=fail_sentinel)
    return sw

def test_submode_A_modal_over_feed_then_renav(monkeypatch):
    """Модалка поверх ленты: dismiss перед renav → recovered."""
    monkeypatch.delenv('TT_POST_SWITCH_GENERIC_DISMISS_DISABLED', raising=False)
    monkeypatch.delenv('TT_POST_SWITCH_SETTLE_DISABLED', raising=False)
    sw = _recovery_switcher()
    feed_modal = _read_fixture('tt_friends_promo_modal.xml')
    profile = _read_fixture('tt_post_switch_5817_relism_e.xml')
    sw.p.tap_element = MagicMock(return_value=True)
    sw.p.dump_ui = MagicMock(return_value=profile)  # после dismiss — профиль
    sw._tt_post_switch_confirm = MagicMock(side_effect=[('match', 'relism_e')])
    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='relism_e', xml_after_pick=feed_modal,
        header_y_max=260, label='tt_4_target_profile', attempt=0)
    assert outcome == 'recovered'

def test_submode_B_transitional_settles_to_match(monkeypatch):
    """Переходный экран → settle-retry → re-dump даёт профиль → recovered."""
    monkeypatch.delenv('TT_POST_SWITCH_SETTLE_DISABLED', raising=False)
    monkeypatch.setenv('TT_SETTLE_S', '0')
    sw = _recovery_switcher()
    transitional = _read_fixture('tt_transitional_switch_sheet.xml')
    profile = _read_fixture('tt_post_switch_5817_relism_e.xml')
    sw.p.tap_element = MagicMock(return_value=False)
    sw.p.dump_ui = MagicMock(return_value=profile)
    # confirm: pre_feed dismiss (нет кнопки → не зовётся в loop'е после break),
    # затем settle re-dump confirm → match
    sw._tt_post_switch_confirm = MagicMock(side_effect=[('match', 'relism_e')])
    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='relism_e', xml_after_pick=transitional,
        header_y_max=260, label='tt_4_target_profile', attempt=0)
    assert outcome == 'recovered'

def test_submode_C_renav_then_security_modal(monkeypatch):
    """Лента → renav → security-модалка → dismiss → recovered."""
    monkeypatch.delenv('TT_POST_SWITCH_GENERIC_DISMISS_DISABLED', raising=False)
    sw = _recovery_switcher()
    feed = _read_fixture('tt_feed_no_sheet.xml')
    security = _read_fixture('tt_security_check_modal.xml')
    profile = _read_fixture('tt_post_switch_5817_relism_e.xml')
    sw._navigate_to_profile_tab = MagicMock(return_value=True)
    sw.p.tap_element = MagicMock(return_value=True)
    # post-renav re-dump = security modal, generic-dismiss re-dump = profile
    sw.p.dump_ui = MagicMock(side_effect=[security, profile])
    # confirm: post-renav (unknown) → после generic-dismiss (match)
    sw._tt_post_switch_confirm = MagicMock(
        side_effect=[('unknown', None), ('match', 'relism_e')])
    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='relism_e', xml_after_pick=feed,
        header_y_max=260, label='tt_4_target_profile', attempt=0)
    assert outcome == 'recovered'

def test_non_feed_unrecoverable_fails_honestly():
    """Ни баннера, ни safe-кнопки, не лента, не переходный → честный fail."""
    sw = _recovery_switcher()
    blank = ('<hierarchy><node text="что-то непонятное" class="x" '
             'bounds="[0,0][9,9]"/></hierarchy>')
    sw.p.dump_ui = MagicMock(return_value=blank)
    sw._tt_post_switch_confirm = MagicMock(return_value=('unknown', None))
    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='relism_e', xml_after_pick=blank,
        header_y_max=260, label='tt_4_target_profile', attempt=0)
    assert outcome == 'failed'
    sw._fail.assert_called_once()
    # новый сигнал триажа эмитнут
    cats = [c.kwargs.get('meta', {}).get('category')
            for c in sw.p.log_event.call_args_list]
    assert 'tt_post_switch_blocked_no_safe_button' in cats
```

- [ ] **Step 2: Запуск — падает**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k "submode or unrecoverable" -q`
Expected: FAIL (старое тело метода не эмитит `tt_post_switch_blocked_no_safe_button`, порядок вызовов не совпадает).

- [ ] **Step 3: Заменить тело `_tt_handle_post_switch_unknown`**

Заменить строки 4797–4936 (от `def _tt_handle_post_switch_unknown` до `return ('failed', None, fail_result)` включительно) на:
```python
    def _tt_handle_post_switch_unknown(self, target: str, xml_after_pick: str,
                                       header_y_max: int, label: str,
                                       attempt: int) -> tuple:
        """[WP #67 Layer 3 — 2026-05-22] Modal-agnostic recovery для unknown.

        Поток: generic-dismiss (pre_feed) → settle-retry (transitional) →
        feed-detect → (dismiss → renav → dismiss) → confirm → честный fail.
        Сохранён fail-closed и mismatch-детект. Контракт возврата:
        (outcome ∈ {recovered, mismatch, failed}, current, fail_result).
        """
        xml = xml_after_pick

        # ── 1. Generic dismiss-loop на первичном экране (pre_feed) ───────────
        status, current, xml = self._tt_dismiss_and_confirm_loop(
            target, xml, header_y_max, probe_site='pre_feed',
            label=label, attempt=attempt)
        if status == 'match':
            self.p.log_event(
                'account_switch', 'tt_post_switch_recovered_via_modal_dismiss',
                meta={'category': 'tt_post_switch_recovered_via_modal_dismiss',
                      'target': target, 'current': current,
                      'probe_site': 'pre_feed', 'attempt': attempt + 1})
            return ('recovered', current, None)
        if status == 'mismatch':
            return ('mismatch', current, None)

        # ── 2. Settle-retry для переходных/loading-экранов ──────────────────
        if (os.environ.get('TT_POST_SWITCH_SETTLE_DISABLED') != '1'
                and _tt_screen_is_transitional(xml)):
            retries = int(os.environ.get('TT_SETTLE_RETRIES', '2'))
            settle_s = float(os.environ.get('TT_SETTLE_S', '1.5'))
            for s in range(retries):
                self.p.log_event(
                    'info', 'tt_post_switch_settle_retry',
                    meta={'category': 'tt_post_switch_settle_retry',
                          'attempt': s + 1, 'target': target, 'step': label})
                time.sleep(settle_s)
                xml = self.p.dump_ui(retries=1) or ''
                self._save_dump(f'{label}_settle_{s + 1}', xml)
                status, current = self._tt_post_switch_confirm(
                    target, xml, header_y_max=header_y_max)
                if status == 'match':
                    return ('recovered', current, None)
                if status == 'mismatch':
                    return ('mismatch', current, None)
                status, current, xml = self._tt_dismiss_and_confirm_loop(
                    target, xml, header_y_max, probe_site='settle',
                    label=label, attempt=attempt)
                if status == 'match':
                    return ('recovered', current, None)
                if status == 'mismatch':
                    return ('mismatch', current, None)
                if not _tt_screen_is_transitional(xml):
                    break

        # ── 3. Feed-detect ──────────────────────────────────────────────────
        if not self._is_tt_feed_after_pick(xml, header_y_max):
            self.p.log_event(
                'warning', 'tt_post_switch_blocked_no_safe_button',
                meta={'category': 'tt_post_switch_blocked_no_safe_button',
                      'target': target, 'probe_site': 'non_feed',
                      'step': label})
            fail_result = self._fail(
                f'tt_post_switch_verify_unrecoverable: unknown header non-feed '
                f'(target={target!r})', step=label)
            return ('failed', None, fail_result)

        self.p.log_event(
            'warning', 'tt_post_switch_feed_after_pick',
            meta={'category': 'tt_post_switch_feed_after_pick',
                  'target': target, 'step': label, 'attempt': attempt + 1})

        # ── 3a. Dismiss модалки ПОВЕРХ ленты ДО renav (под-режим A) ─────────
        status, current, xml = self._tt_dismiss_and_confirm_loop(
            target, xml, header_y_max, probe_site='pre_renav',
            label=label, attempt=attempt)
        if status == 'match':
            self.p.log_event(
                'account_switch', 'tt_post_switch_recovered_via_modal_dismiss',
                meta={'category': 'tt_post_switch_recovered_via_modal_dismiss',
                      'target': target, 'current': current,
                      'probe_site': 'pre_renav', 'attempt': attempt + 1})
            return ('recovered', current, None)
        if status == 'mismatch':
            return ('mismatch', current, None)

        # ── 3b. Renav в профиль ─────────────────────────────────────────────
        if not self._navigate_to_profile_tab():
            self.p.log_event(
                'error', 'tt_post_switch_renav_failed',
                meta={'category': 'tt_post_switch_renav_failed',
                      'target': target, 'step': label, 'attempt': attempt + 1})
            fail_result = self._fail(
                f'tt_post_switch_verify_unrecoverable: navigate_to_profile_tab '
                f'failed после feed-detect (target={target!r})',
                step=f'{label}_renav')
            return ('failed', None, fail_result)
        xml = self.p.dump_ui(retries=1) or ''
        self._save_dump(f'{label}_renav', xml)
        status, current = self._tt_post_switch_confirm(
            target, xml, header_y_max=header_y_max)

        # ── 3c. Dismiss модалки поверх профиля после renav (под-режим C) ────
        if status == 'unknown':
            status, current, xml = self._tt_dismiss_and_confirm_loop(
                target, xml, header_y_max, probe_site='post_renav',
                label=f'{label}_renav', attempt=attempt)

        if status == 'match':
            self.p.log_event(
                'account_switch', 'tt_post_switch_recovered_via_renav',
                meta={'category': 'tt_post_switch_recovered_via_renav',
                      'target': target, 'current': current,
                      'attempt': attempt + 1})
            return ('recovered', current, None)
        if status == 'mismatch':
            return ('mismatch', current, None)

        # ── 4. Остаток — честный fail (fail-closed) ─────────────────────────
        self.p.log_event(
            'warning', 'tt_post_switch_blocked_no_safe_button',
            meta={'category': 'tt_post_switch_blocked_no_safe_button',
                  'target': target, 'probe_site': 'post_renav',
                  'step': f'{label}_renav'})
        fail_result = self._fail(
            f'tt_post_switch_verify_unrecoverable: no profile after re-nav '
            f'(target={target!r})', step=f'{label}_renav')
        return ('failed', None, fail_result)
```

Примечания:
- Старые `_try_dismiss_and_redump` и `_TT_POST_SWITCH_DISMISSIBLE_MODALS` больше не вызываются из этого метода (их кейсы покрыл SAFE_DISMISS). Функции/whitelist **оставить определёнными** (их pure-unit тесты в `test_account_switcher_modal_dismiss.py` остаются зелёными). Помеченное «superseded» удаление — отдельная будущая чистка, не в этом фиксе.
- Шаги/сообщения `_fail` сохранены дословно — kernel-маппинг на `tt_post_switch_verify_unrecoverable` не меняется.

- [ ] **Step 4: Запуск — зелёный**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -k "submode or unrecoverable" -q`
Expected: PASS (4 теста).

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_tt_post_switch_modal_agnostic.py
git commit -m "feat(tt-switch): WP #67 L3 — rework post-switch unknown recovery (modal-agnostic)"
```

---

## Task 8: Врезка в `_switch_tiktok` (early banner + confirm)

**Files:**
- Modify: `account_switcher.py:2759-2760` (early banner после pick) и `:2846` (`_post_switch_verify_handle` → `_tt_post_switch_confirm`)

- [ ] **Step 1: Early banner после attempt-0 pick**

Найти (строка ~2759-2760):
```python
                step='tt_3_pick_account',
            )

        time.sleep(AFTER_SWITCH_WAIT_S)
```
Заменить на:
```python
                step='tt_3_pick_account',
            )

        # [WP #67 Layer 3] Ранний banner-confirm: ловим «Вы вошли как X»
        # пока баннер жив (~2с), ДО settle-wait. Авторитетный сигнал успеха.
        if self._tt_early_banner_confirm(target, step='tt_4_early_banner'):
            return self._tap_plus_and_verify(
                cfg, step_prefix='tt_5', final_step='tt_5_editor',
                verify_triggers=cfg['editor_triggers'],
                already_matched=False,
            )

        time.sleep(AFTER_SWITCH_WAIT_S)
```

- [ ] **Step 2: Заменить verify-вызов в loop'е на confirm**

Найти (строка ~2846):
```python
            status, current = self._post_switch_verify_handle(
                target, xml_after_pick, header_y_max=header_y_max,
            )
```
Заменить на:
```python
            status, current = self._tt_post_switch_confirm(
                target, xml_after_pick, header_y_max=header_y_max,
            )
```

- [ ] **Step 3: Проверить отсутствие синтаксических ошибок**

Run: `cd /home/claude-user/autowarm-testbench && python -c "import account_switcher"`
Expected: без ошибок.

- [ ] **Step 4: Commit**

```bash
git add account_switcher.py
git commit -m "feat(tt-switch): WP #67 L3 — wire early-banner + confirm into _switch_tiktok"
```

---

## Task 9: Миграция существующих тестов + полный suite

**Files:**
- Modify: `tests/test_account_switcher_modal_dismiss.py` (6 integration-тестов), `tests/test_post_switch_renav.py` (recovery-flow тесты)

- [ ] **Step 1: Прогнать suite — увидеть, что сломалось**

Run: `cd /home/claude-user/autowarm-testbench && pytest tests/test_account_switcher_modal_dismiss.py tests/test_post_switch_renav.py -q`
Expected: часть integration-тестов FAIL (старый flow использовал whitelist-probe / другой порядок вызовов).

- [ ] **Step 2: Адаптировать упавшие тесты под новый flow**

Для каждого упавшего integration-теста:
- Если он проверял событие `tt_post_switch_modal_dismiss_attempted` / `_recovered_via_modal_dismiss` через старый whitelist-probe — заменить ожидание на `tt_post_switch_modal_dismissed_generic` и мок `sw._tt_post_switch_confirm` (вместо `_post_switch_verify_handle`), как в Task 7 integration-тестах.
- Если он мокал `_post_switch_verify_handle` и проверял число вызовов в recovery-пути — recovery теперь зовёт `_tt_post_switch_confirm`; перенаправить мок на `sw._tt_post_switch_confirm`.
- Pure-unit тесты матчера (`_tt_try_dismiss_post_switch_modal`, `_is_tt_feed_after_pick`) **не трогать** — они остаются зелёными.

Принцип: тест отражает новый порядок (generic-dismiss вместо whitelist-probe), а не подгоняется фиктивно.

- [ ] **Step 3: Полный switcher-suite зелёный**

Run: `cd /home/claude-user/autowarm-testbench && pytest tests/test_tt_post_switch_modal_agnostic.py tests/test_account_switcher_modal_dismiss.py tests/test_post_switch_renav.py tests/test_account_switcher_tt.py tests/test_tt_security_prompt_dismiss.py tests/test_account_switcher_profile_promo_dismiss.py -q`
Expected: PASS (0 регрессий).

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(tt-switch): WP #67 L3 — migrate recovery-flow tests to generic dismiss"
```

---

## Task 10: Реальные фикстуры через re-queue + проверка баннера

**Files:** — (прод-действие + опц. обновление фикстур)

> **Прод-действие.** Перевыкладка использует реальное устройство и попытку публикации. Делать осознанно. Механика re-queue: [[reference_publish_requeue_path]] — `UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE ...`; cron `dispatchPublishQueue` (5 мин) создаст новый pt.

- [ ] **Step 1: Перевыложить 1–2 задачи под-режимов A и C**

Выбрать недавние упавшие (например 9124 — под-режим A, 7715 — под-режим C). Найти их строки в `publish_queue` и вернуть в `pending` (см. механику выше). Дождаться нового pt (≤~10 мин).

- [ ] **Step 2: Снять post-switch дампы из `/tmp/autowarm_ui_dumps`**

После прогона найти дампы новых задач (`switch_<ptid>_tt_4_*`, `*_renav*`, `*_generic_dismiss_*`, `tt_4_early_banner*`). Скопировать показательные в `tests/fixtures/` (заменив синтетические на реальные, где возможно).

- [ ] **Step 3: КЛЮЧЕВОЕ — проверить, ловится ли баннер**

```bash
grep -l "вошли как\|вошли в\|logged in as" /tmp/autowarm_ui_dumps/*tt_4_early_banner* 2>/dev/null
```
- Если баннер найден в дампе → кирпич 1 рабочий, оставляем `TT_POST_SWITCH_BANNER_DISABLED` **не задан** (вкл. по умолчанию).
- Если НЕ найден ни в одном дампе → баннер не в accessibility-дереве; в прод-конфиге выставить `TT_POST_SWITCH_BANNER_DISABLED=1` (кирпич 1 отключён, фикс держится на кирпичах 2+3). Записать вывод в evidence-док.

- [ ] **Step 4: Обновить тесты под реальные фикстуры (если заменяли) и прогнать**

Run: `pytest tests/test_tt_post_switch_modal_agnostic.py -q`
Expected: PASS.

- [ ] **Step 5: Commit (если были изменения фикстур/тестов)**

```bash
git add tests/
git commit -m "test(tt-switch): WP #67 L3 — real prod-dump fixtures + banner capturability check"
```

---

## Task 11: Деплой в прод + live smoke + soak

**Files:** — (деплой)

- [ ] **Step 1: Cherry-pick в prod autowarm**

В `/root/.openclaw/workspace-genri/autowarm/` (prod main) cherry-pick'нуть коммиты ветки `wp67-l3-modal-agnostic` (или squash-merge через PR в GenGo2/delivery-contenthunter, затем auto-push hook). **Без force-push.** Python подхватится per-task spawn'ом — PM2 restart не требуется.

- [ ] **Step 2: Подтвердить, что прод читает новый код**

```bash
grep -c "_tt_dismiss_and_confirm_loop\|tt_post_switch_confirmed_via_banner" /root/.openclaw/workspace-genri/autowarm/account_switcher.py
```
Expected: ≥ 1 (новый код в проде).

- [ ] **Step 3: Live smoke — перевыложить 9124 / 7715 (+ 8573)**

Re-queue (как Task 10). Ожидать в логах новых pt: события `tt_post_switch_modal_dismissed_generic` / `tt_post_switch_confirmed_via_banner` / `tt_post_switch_settle_retry`, и `done` (или продвижение дальше переключения).

- [ ] **Step 4: 24h soak**

Через сутки запросить тренд (SQL по `events[].meta.category`):
```sql
SELECT date(created_at),
  count(*) FILTER (WHERE id IN (
    SELECT pt.id FROM publish_tasks pt, jsonb_array_elements(pt.events) e
    WHERE e->'meta'->>'category'='tt_post_switch_verify_unrecoverable'))
FROM publish_tasks
WHERE platform='TikTok' AND created_at >= now() - interval '2 days'
GROUP BY 1;
```
Acceptance: `tt_post_switch_verify_unrecoverable` 1–3/сутки → ~0 в части модалок/переходов. Остаток (новые `tt_post_switch_blocked_no_safe_button` без safe-кнопки) → отдельные WP.

- [ ] **Step 5: Обновить OpenProject #67 + evidence-док**

- Evidence: `docs/evidence/2026-05-22-tt-post-switch-modal-agnostic-shipped.md` (в contenthunter-репо) — что было/сделано/осталось, результаты smoke + soak, статус баннера.
- OpenProject #67: статус → `Тестирование` (id 9) после деплоя; комментарий в house-стиле (Что было не так → Что сделано → Что осталось, без жаргона). «Готово» — только после 24h soak с подтверждённым падением до ~0.

---

## Self-review (выполнено автором плана)

- **Покрытие spec:** кирпич 1 → Task 1,4,6,8; кирпич 2 → Task 2,5; кирпич 3 → Task 3,7; оркестрация → Task 7; врезка → Task 8; телеметрия → события в Task 4–7; fail-closed/kill-switch → Task 7 + env-vars; тесты/фикстуры → Task 1–3,9,10; live smoke/soak → Task 11; банн-неизвестность → Task 10 Step 3. Все секции spec покрыты.
- **Плейсхолдеры:** код приведён полностью в каждом шаге; команды и ожидаемый вывод указаны.
- **Согласованность типов/имён:** `_tt_read_login_confirm_banner`, `_tt_find_safe_dismiss`, `_tt_screen_is_transitional`, `_tt_post_switch_confirm`, `_tt_dismiss_and_confirm_loop`, `_tt_early_banner_confirm` — имена одинаковы во всех тасках. Контракт `_tt_handle_post_switch_unknown` `(outcome, current, fail_result)` сохранён. Env-vars: `TT_POST_SWITCH_BANNER_DISABLED`, `TT_POST_SWITCH_GENERIC_DISMISS_DISABLED`, `TT_POST_SWITCH_SETTLE_DISABLED`, `TT_DISMISS_MAX`, `TT_SETTLE_S`, `TT_SETTLE_RETRIES` — единообразны.
