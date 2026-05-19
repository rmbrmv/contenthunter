# WP #106 — TT profile-tab promo-modal dismiss — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрывать известные TT profile-tab promo-модалки (контакты, FB friends) внутри retap-loop в `_switch_tiktok`, чтобы они не блокировали `_tt_is_own_profile` и не валили publish в `tt_profile_tab_broken`.

**Architecture:** Module-level constant `_TT_PROFILE_PROMO_DISMISSIBLE_MODALS` + module helper `_tt_try_dismiss_profile_promo` (pure detect) + `AccountSwitcher._tt_dismiss_profile_promo_dialog` method (detect + tap + log_event) + один блок в retap-loop сразу после `_tt_dismiss_security_prompt`. Зеркалит шаблон WP #67 Layer 2 (PR #70).

**Tech Stack:** Python 3.10+, pytest, MagicMock, uiautomator XML dumps, ADB tap dispatcher.

**Spec:** `docs/superpowers/specs/2026-05-19-tt-profile-promo-dismiss-design.md`

**Repo:** Код живёт в `GenGo2/delivery-contenthunter` (autowarm). Dev clone — `/home/claude-user/autowarm-testbench/` (git worktree base). Docs (этот файл, spec) — в `contenthunter` репо.

**Branch name:** `feat/wp106-tt-profile-promo-dismiss-20260519`.

**Worktree path:** `/home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519/`.

---

## Pre-flight: setup worktree

### Task 0: Создать worktree off origin/main + verify pytest baseline

**Files:**
- Create: `/home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519/` (новый git worktree)

- [ ] **Step 1: fetch + создать worktree**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin main
git worktree add -b feat/wp106-tt-profile-promo-dismiss-20260519 \
  /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519 \
  origin/main
```

Expected output: `Preparing worktree (new branch 'feat/wp106-tt-profile-promo-dismiss-20260519')` + `HEAD is now at <sha> <msg>`.

- [ ] **Step 2: verify clean state + branch**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519
git status
git log -1 --oneline
git branch --show-current
```

Expected: `working tree clean`, latest origin/main commit, branch `feat/wp106-tt-profile-promo-dismiss-20260519`.

- [ ] **Step 3: baseline pytest зелёный**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519
pytest tests/test_account_switcher_modal_dismiss.py tests/test_account_switcher_tt.py -v 2>&1 | tail -20
```

Expected: все тесты прошли (никаких `FAILED`). Если что-то падает — это pre-existing baseline, зафиксировать в комментарии под этим step'ом и продолжать.

---

## Code

### Task 1: Скачать UI-fixture'ы для двух variants промо-модалок

**Files:**
- Create: `tests/fixtures/tt_profile_promo_contacts_7827.xml`
- Create: `tests/fixtures/tt_profile_promo_fb_friends_7870.xml`

Эти fixtures используются всеми тестами Task 2-5. Создаём раньше, чтобы test'ы можно было писать сразу.

- [ ] **Step 1: download fixtures из S3**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519
curl -sS -o tests/fixtures/tt_profile_promo_contacts_7827.xml \
  https://save.gengo.io/autowarm/ui_dumps/tiktok/task7827_switch_7827_tt_2_not_own_retap1_1779182029.xml
curl -sS -o tests/fixtures/tt_profile_promo_fb_friends_7870.xml \
  https://save.gengo.io/autowarm/ui_dumps/tiktok/task7870_switch_7870_tt_2_not_own_retap1_1779185960.xml
wc -c tests/fixtures/tt_profile_promo_contacts_7827.xml \
       tests/fixtures/tt_profile_promo_fb_friends_7870.xml
```

Expected: 7319 / 7674 байт (известные размеры из триажа 2026-05-19).

- [ ] **Step 2: sanity grep — fixtures содержат whitelist title строки**

```bash
grep -c 'Чтобы связаться в TikTok' tests/fixtures/tt_profile_promo_contacts_7827.xml
grep -c 'Разрешить TikTok доступ к списку ваших друзей' tests/fixtures/tt_profile_promo_fb_friends_7870.xml
grep -c 'Не разрешать' tests/fixtures/tt_profile_promo_contacts_7827.xml
grep -c 'Не разрешать' tests/fixtures/tt_profile_promo_fb_friends_7870.xml
```

Expected: каждая команда `>= 1`.

- [ ] **Step 3: commit fixtures**

```bash
git add tests/fixtures/tt_profile_promo_contacts_7827.xml \
        tests/fixtures/tt_profile_promo_fb_friends_7870.xml
git -c commit.gpgsign=false commit -m "test(fixtures): WP #106 — TT profile-tab promo dumps (contacts + FB friends)"
git log -1 --oneline
```

Expected: 1 коммит c 2 новыми файлами.

---

### Task 2: TDD module helper — positive contacts case

**Files:**
- Create: `tests/test_account_switcher_profile_promo_dismiss.py`
- Modify: `account_switcher.py` (новый constant + новый module helper)

- [ ] **Step 1: написать failing test**

Создать `tests/test_account_switcher_profile_promo_dismiss.py` со следующим содержимым:

```python
"""Unit + integration tests для WP #106 — TT profile-tab promo-modal dismiss.

См. design spec docs/superpowers/specs/2026-05-19-tt-profile-promo-dismiss-design.md

Запуск:
    cd /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519
    pytest tests/test_account_switcher_profile_promo_dismiss.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from account_switcher import (  # noqa: E402
    AccountSwitcher,
    _TT_PROFILE_PROMO_DISMISSIBLE_MODALS,
    _tt_try_dismiss_profile_promo,
)


FIXTURES = ROOT / 'tests' / 'fixtures'


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


# ─── _tt_try_dismiss_profile_promo — pure unit ──────────────────────────────


def test_whitelist_seeded_with_two_entries():
    """Whitelist должен содержать contacts + FB friends promo."""
    titles = [t for t, _ in _TT_PROFILE_PROMO_DISMISSIBLE_MODALS]
    assert any('Чтобы связаться в TikTok' in t for t in titles)
    assert any('Разрешить TikTok доступ к списку ваших друзей' in t for t in titles)


def test_match_contacts_promo_7827():
    """task 7827 retap1 dump → ('Чтобы связаться в TikTok', 'Не разрешать')."""
    xml = _read_fixture('tt_profile_promo_contacts_7827.xml')
    result = _tt_try_dismiss_profile_promo(xml)
    assert result is not None
    title, button = result
    assert title == 'Чтобы связаться в TikTok'
    assert button == 'Не разрешать'
```

- [ ] **Step 2: запустить test — verify FAIL (ImportError)**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519
pytest tests/test_account_switcher_profile_promo_dismiss.py -v 2>&1 | tail -15
```

Expected: `ImportError: cannot import name '_TT_PROFILE_PROMO_DISMISSIBLE_MODALS'` (или аналог) — test collection fail.

- [ ] **Step 3: добавить constant + module helper в `account_switcher.py`**

Найти существующий `_TT_POST_SWITCH_DISMISSIBLE_MODALS` (~line 220) и добавить НИЖЕ него:

```python
# [WP #106 — 2026-05-19] Whitelist profile-tab promo-modals.
# Evidence: tasks 7827/7861/7884 (contacts promo), 7870 (FB friends promo).
# Match требует BOTH title_substr AND clickable button_text — защита от
# ложного dismiss другого «Не разрешать» в неродственном контексте.
# Расширяется по одной строке при появлении новой evidence.
_TT_PROFILE_PROMO_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...] = (
    # (title_substring, dismiss_button_text)
    ('Чтобы связаться в TikTok', 'Не разрешать'),
    ('Разрешить TikTok доступ к списку ваших друзей', 'Не разрешать'),
)
```

Найти существующий module helper `_tt_try_dismiss_post_switch_modal` (~line 383) и добавить НИЖЕ него:

```python
def _tt_try_dismiss_profile_promo(xml: str) -> Optional[tuple[str, str]]:
    """[WP #106 — 2026-05-19] Detect known dismissible TT profile-tab promo-modal.

    Используется в `AccountSwitcher._switch_tiktok` retap-loop, чтобы отличить
    случай "TT показал promo-модалку поверх профиля" от настоящего not-own
    fail'а. Match требует ОБА условия:
      - элемент с `title_substr` в `.label` где-то на экране;
      - clickable элемент с `.label.strip().lower() == button_text.lower()`.

    Title-check защищает от ложного dismiss другого «Не разрешать» в другом
    контексте (permission-prompt системы, alert-диалог TT и т.п.).

    Returns: (title_substr, button_text) первой совпавшей записи whitelist;
    None если ни одна не сматчилась.
    """
    if not xml:
        return None
    elements = parse_ui_dump(xml)  # parse_ui_dump возвращает [] на parse error / FLAG_SECURE
    if not elements:
        return None
    for title_substr, button_text in _TT_PROFILE_PROMO_DISMISSIBLE_MODALS:
        if not any(title_substr in el.label for el in elements):
            continue
        button_lc = button_text.lower()
        button_seen = any(
            el.clickable and el.label.strip().lower() == button_lc
            for el in elements
        )
        if button_seen:
            return (title_substr, button_text)
    return None
```

Точная позиция: после функции `_tt_try_dismiss_post_switch_modal` (после её `return None`, пустая строка, новая функция). `Optional` и `tuple` уже импортированы (используются в PR #70).

- [ ] **Step 4: запустить test — verify PASS**

```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py -v 2>&1 | tail -10
```

Expected: `2 passed` (test_whitelist_seeded_with_two_entries + test_match_contacts_promo_7827).

- [ ] **Step 5: commit**

```bash
git add account_switcher.py tests/test_account_switcher_profile_promo_dismiss.py
git -c commit.gpgsign=false commit -m "feat(switcher): WP #106 — add _tt_try_dismiss_profile_promo helper + contacts whitelist entry"
```

---

### Task 3: Расширить helper tests на остальные сценарии

**Files:**
- Modify: `tests/test_account_switcher_profile_promo_dismiss.py` (добавляем 6 тестов)

Все 6 тестов должны пройти БЕЗ изменений в коде (helper и whitelist уже умеют их обрабатывать).

- [ ] **Step 1: добавить 6 тестов в конец test-файла**

В `tests/test_account_switcher_profile_promo_dismiss.py` после `test_match_contacts_promo_7827`:

```python
def test_match_fb_friends_promo_7870():
    """task 7870 retap1 dump → ('Разрешить TikTok доступ…', 'Не разрешать')."""
    xml = _read_fixture('tt_profile_promo_fb_friends_7870.xml')
    result = _tt_try_dismiss_profile_promo(xml)
    assert result is not None
    title, button = result
    assert title == 'Разрешить TikTok доступ к списку ваших друзей'
    assert button == 'Не разрешать'


def test_no_match_other_dialog_with_disallow():
    """Title-substring miss → None, даже если кнопка «Не разрешать» есть на экране.

    Защита от ложного dismiss в неродственном контексте (например, системный
    permission-prompt с «Не разрешать»).
    """
    xml = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="Совершенно посторонний текст" clickable="false"
        bounds="[0,500][1080,600]" content-desc="" />
  <node text="Не разрешать" clickable="true"
        bounds="[400,1400][680,1480]" content-desc="" />
</hierarchy>'''
    assert _tt_try_dismiss_profile_promo(xml) is None


def test_no_match_title_present_button_not_clickable():
    """Title есть, button есть но clickable=false → None."""
    xml = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="Чтобы связаться в TikTok со своими знакомыми" clickable="false"
        bounds="[0,500][1080,600]" content-desc="" />
  <node text="Не разрешать" clickable="false"
        bounds="[400,1400][680,1480]" content-desc="" />
</hierarchy>'''
    assert _tt_try_dismiss_profile_promo(xml) is None


def test_no_match_title_present_button_text_different():
    """Title есть, clickable элемент есть но с другим text → None."""
    xml = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="Чтобы связаться в TikTok со своими знакомыми" clickable="false"
        bounds="[0,500][1080,600]" content-desc="" />
  <node text="Open Settings" clickable="true"
        bounds="[400,1400][680,1480]" content-desc="" />
</hierarchy>'''
    assert _tt_try_dismiss_profile_promo(xml) is None


def test_empty_xml_returns_none():
    assert _tt_try_dismiss_profile_promo('') is None


def test_malformed_xml_returns_none():
    """parse_ui_dump возвращает [] → guard if not elements → None."""
    assert _tt_try_dismiss_profile_promo('<not-hierarchy>x</not-hierarchy>') is None
```

- [ ] **Step 2: запустить tests — все 8 должны PASS**

```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py -v 2>&1 | tail -15
```

Expected: `8 passed` (2 из Task 2 + 6 новых).

- [ ] **Step 3: commit**

```bash
git add tests/test_account_switcher_profile_promo_dismiss.py
git -c commit.gpgsign=false commit -m "test(switcher): WP #106 — extend helper tests (FB friends + 5 negatives)"
```

---

### Task 4: TDD `_tt_dismiss_profile_promo_dialog` method

**Files:**
- Modify: `account_switcher.py` (новый AccountSwitcher method)
- Modify: `tests/test_account_switcher_profile_promo_dismiss.py` (3 теста на метод)

- [ ] **Step 1: добавить failing tests на метод в test-файл**

В конец `tests/test_account_switcher_profile_promo_dismiss.py`:

```python
# ─── AccountSwitcher._tt_dismiss_profile_promo_dialog — method unit ─────────


def _make_switcher() -> AccountSwitcher:
    """AccountSwitcher с mock publisher для method-unit тестов."""
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.log_event = MagicMock()
    publisher.tap_element = MagicMock(return_value=True)
    sw = AccountSwitcher(publisher)
    return sw


def _events_with_name(switcher: AccountSwitcher, name: str) -> list:
    """Извлечь все log_event-вызовы с заданным event_name (call.args[1])."""
    return [
        call for call in switcher.p.log_event.call_args_list
        if len(call.args) >= 2 and call.args[1] == name
    ]


def test_method_match_emits_event_and_taps():
    """Match contacts promo → emits _attempted event + tap_element([button]) → True."""
    sw = _make_switcher()
    xml = _read_fixture('tt_profile_promo_contacts_7827.xml')

    result = sw._tt_dismiss_profile_promo_dialog(xml, retap=0)

    assert result is True
    attempted = _events_with_name(sw, 'tt_profile_promo_dismiss_attempted')
    assert len(attempted) == 1
    meta = attempted[0].kwargs['meta']
    assert meta['title_substr'] == 'Чтобы связаться в TikTok'
    assert meta['button_text'] == 'Не разрешать'
    assert meta['retap'] == 1
    assert meta['platform'] == 'TikTok'
    assert meta['category'] == 'tt_profile_promo_dismiss_attempted'
    sw.p.tap_element.assert_called_once()
    # Verify tap_element call args
    call_args = sw.p.tap_element.call_args
    assert call_args.args[0] == xml
    assert call_args.args[1] == ['Не разрешать']
    assert call_args.kwargs.get('clickable_only') is True


def test_method_no_match_returns_false_no_events():
    """Whitelist miss → False, no events, no tap."""
    sw = _make_switcher()
    xml = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="что-то совсем другое" clickable="false"
        bounds="[0,500][1080,600]" content-desc="" />
</hierarchy>'''

    result = sw._tt_dismiss_profile_promo_dialog(xml, retap=0)

    assert result is False
    sw.p.log_event.assert_not_called()
    sw.p.tap_element.assert_not_called()


def test_method_tap_failed_emits_warning_returns_false():
    """Match found, но tap_element=False → tap_failed warning + False."""
    sw = _make_switcher()
    sw.p.tap_element = MagicMock(return_value=False)
    xml = _read_fixture('tt_profile_promo_contacts_7827.xml')

    result = sw._tt_dismiss_profile_promo_dialog(xml, retap=2)

    assert result is False
    attempted = _events_with_name(sw, 'tt_profile_promo_dismiss_attempted')
    assert len(attempted) == 1
    tap_failed = _events_with_name(sw, 'tt_profile_promo_dismiss_tap_failed')
    assert len(tap_failed) == 1
    assert tap_failed[0].kwargs['meta']['retap'] == 3  # retap=2 → retap+1=3


def test_method_kill_switch_disabled(monkeypatch):
    """Env TT_PROFILE_PROMO_DISMISS_DISABLED=1 → False без detection."""
    monkeypatch.setenv('TT_PROFILE_PROMO_DISMISS_DISABLED', '1')
    sw = _make_switcher()
    xml = _read_fixture('tt_profile_promo_contacts_7827.xml')

    result = sw._tt_dismiss_profile_promo_dialog(xml, retap=0)

    assert result is False
    sw.p.log_event.assert_not_called()
    sw.p.tap_element.assert_not_called()
```

- [ ] **Step 2: запустить tests — verify 4 новых FAIL (AttributeError)**

```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py -v 2>&1 | tail -15
```

Expected: 8 previous PASS + 4 новых FAIL c `AttributeError: 'AccountSwitcher' object has no attribute '_tt_dismiss_profile_promo_dialog'`.

- [ ] **Step 3: добавить метод в `account_switcher.py`**

Найти `_tt_dismiss_security_prompt` (line 2177). Добавить ПОСЛЕ его `return False` на line 2221 (между этим методом и `_switch_tiktok` на line 2223):

```python
    def _tt_dismiss_profile_promo_dialog(self, ui_xml: str, retap: int) -> bool:
        """[WP #106 — 2026-05-19] Detect and dismiss TT profile-tab promo-modal.

        Вызывается в `_switch_tiktok` retap-loop между `_tt_dismiss_security_prompt`
        и `_tt_is_own_profile`. Cap = 1 dismiss/retap (caller re-dump'ит UI).

        Kill-switch: env-var `TT_PROFILE_PROMO_DISMISS_DISABLED=1` → возврат False
        без detection (для defensive отключения без редеплоя).

        Args:
            ui_xml: текущий UI dump (xml_probe из retap-loop)
            retap: индекс retap (0-based) — для observability

        Returns:
            True если whitelist-match И tap прошёл успешно. Caller должен
            sleep + re-dump UI на основном пути.
            False если whitelist miss, kill-switch активен, или tap_element=False.
        """
        if os.environ.get('TT_PROFILE_PROMO_DISMISS_DISABLED') == '1':
            return False
        matched = _tt_try_dismiss_profile_promo(ui_xml)
        if matched is None:
            return False
        title_substr, button_text = matched
        self.p.log_event(
            'info', 'tt_profile_promo_dismiss_attempted',
            meta={'category': 'tt_profile_promo_dismiss_attempted',
                  'title_substr': title_substr,
                  'button_text': button_text,
                  'retap': retap + 1,
                  'platform': 'TikTok'},
        )
        tapped = self.p.tap_element(ui_xml, [button_text], clickable_only=True)
        if not tapped:
            self.p.log_event(
                'warning', 'tt_profile_promo_dismiss_tap_failed',
                meta={'category': 'tt_profile_promo_dismiss_tap_failed',
                      'title_substr': title_substr,
                      'button_text': button_text,
                      'retap': retap + 1,
                      'platform': 'TikTok'},
            )
            return False
        return True
```

`os` уже импортирован (используется в `_save_dump` line 5177 и других местах).

- [ ] **Step 4: запустить tests — все 12 должны PASS**

```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py -v 2>&1 | tail -15
```

Expected: `12 passed`.

- [ ] **Step 5: commit**

```bash
git add account_switcher.py tests/test_account_switcher_profile_promo_dismiss.py
git -c commit.gpgsign=false commit -m "feat(switcher): WP #106 — add _tt_dismiss_profile_promo_dialog method + kill-switch"
```

---

### Task 5: Интеграция в `_switch_tiktok` retap-loop

**Files:**
- Modify: `account_switcher.py:2335` (между блоком security_prompt и `_tt_is_own_profile`)
- Modify: `tests/test_account_switcher_profile_promo_dismiss.py` (2 integration теста)

- [ ] **Step 1: добавить 2 integration теста**

В конец `tests/test_account_switcher_profile_promo_dismiss.py`:

```python
# ─── _switch_tiktok retap-loop — integration ────────────────────────────────


def _make_switcher_for_switch_test() -> AccountSwitcher:
    """AccountSwitcher с mock publisher для integration через _switch_tiktok."""
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.task_id = 9999
    publisher.adb = MagicMock(return_value='')
    publisher.log_event = MagicMock()
    publisher.set_step = MagicMock()
    publisher.tap_element = MagicMock(return_value=True)
    publisher.dump_ui = MagicMock(return_value='')
    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    sw._fail = MagicMock(return_value=MagicMock(success=False, reason='stub_fail',
                                                final_step='tt_2_not_own_profile'))
    sw._ok = MagicMock(return_value=MagicMock(success=True))
    return sw


def test_retap1_promo_dismissed_then_own_profile(monkeypatch):
    """retap1 dump = promo → dismiss → re-dump = own_profile → break (success).

    Path: dump_ui(retap1) → promo XML; promo dismiss; dump_ui(re-dump) → own profile;
    `_tt_is_own_profile`(own) → True → break.
    """
    sw = _make_switcher_for_switch_test()
    xml_promo = _read_fixture('tt_profile_promo_contacts_7827.xml')
    xml_own = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" clickable="false" bounds="[0,100][1080,200]" content-desc="Меню профиля" />
  <node text="Создать историю" clickable="true" bounds="[0,300][200,400]" content-desc="" />
  <node text="Редактировать профиль" clickable="true" bounds="[200,400][800,500]" content-desc="" />
</hierarchy>'''

    # Stub the parts of _switch_tiktok that are out of scope for this test.
    monkeypatch.setattr(sw, '_ensure_app_foregrounded', MagicMock(return_value=True))
    monkeypatch.setattr(sw, '_ensure_foreground', MagicMock(return_value=True))
    monkeypatch.setattr(sw, '_go_to_profile_tab', MagicMock())
    monkeypatch.setattr(sw, '_tap_plus_and_verify',
                        MagicMock(return_value=MagicMock(success=True)))

    # dump_ui sequence: 1st = initial retap1 probe (promo); 2nd = after dismiss (own_profile).
    sw.p.dump_ui.side_effect = [xml_promo, xml_own]

    cfg = {
        'package': 'com.zhiliaoapp.musically',
        'launch_activity': 'com.zhiliaoapp.musically/.MainActivity',
        'editor_triggers': ['Опубликовать'],
        'profile_title_header_y_range': (0, 700),
    }
    sw._switch_tiktok(target='clickpay_app', cfg=cfg)

    # Expectation: promo dismiss attempt emitted на retap=0 (retap+1=1).
    attempted = _events_with_name(sw, 'tt_profile_promo_dismiss_attempted')
    assert len(attempted) == 1
    assert attempted[0].kwargs['meta']['retap'] == 1
    # _fail НЕ должен быть вызван.
    sw._fail.assert_not_called()
    # _tap_plus_and_verify должен быть вызван (мы прошли retap-loop и вышли в editor).
    sw._tap_plus_and_verify.assert_called_once()


def test_all_3_retaps_promo_persists_then_fail(monkeypatch):
    """retap1/2/3 dump = promo → каждый dismiss удачен, но re-dump опять promo → fail.

    Симулирует TT, где модалка возвращается после tap. После 3 retap — `_fail`
    с tt_2_not_own_profile, 3 `_attempted` события.
    """
    sw = _make_switcher_for_switch_test()
    xml_promo = _read_fixture('tt_profile_promo_contacts_7827.xml')

    monkeypatch.setattr(sw, '_ensure_app_foregrounded', MagicMock(return_value=True))
    monkeypatch.setattr(sw, '_ensure_foreground', MagicMock(return_value=True))
    monkeypatch.setattr(sw, '_go_to_profile_tab', MagicMock())
    monkeypatch.setattr(sw, '_tt_smart_tap_profile', MagicMock(return_value=True))
    monkeypatch.setattr(sw, '_tt_try_bottomsheet_recovery',
                        MagicMock(return_value=None))  # path not used (no foreign markers)
    # Каждый dump_ui (initial probe И после dismiss) возвращает тот же promo.
    sw.p.dump_ui.return_value = xml_promo

    cfg = {
        'package': 'com.zhiliaoapp.musically',
        'launch_activity': 'com.zhiliaoapp.musically/.MainActivity',
        'editor_triggers': ['Опубликовать'],
        'profile_title_header_y_range': (0, 700),
    }
    sw._switch_tiktok(target='clickpay_app', cfg=cfg)

    # 3 retap → 3 dismiss-attempt event'а.
    attempted = _events_with_name(sw, 'tt_profile_promo_dismiss_attempted')
    assert len(attempted) == 3
    assert [a.kwargs['meta']['retap'] for a in attempted] == [1, 2, 3]
    # Финальный _fail с tt_2_not_own_profile.
    sw._fail.assert_called_once()
    fail_step = sw._fail.call_args.kwargs.get('step') or sw._fail.call_args.args[-1]
    # Argument-style: positional reason + kwarg step OR positional both — поддержать оба.
    assert 'tt_2_not_own_profile' in str(sw._fail.call_args)
```

- [ ] **Step 2: запустить tests — verify 2 FAIL (нет dismiss call'а в retap-loop)**

```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py::test_retap1_promo_dismissed_then_own_profile tests/test_account_switcher_profile_promo_dismiss.py::test_all_3_retaps_promo_persists_then_fail -v 2>&1 | tail -25
```

Expected: оба FAIL. `attempted` будет пустым (== 0 != 1) — наш метод сейчас не вызывается из retap-loop.

- [ ] **Step 3: пропатчить retap-loop в `_switch_tiktok`**

В `account_switcher.py` найти существующий блок (line ~2326-2335):

```python
            if self._tt_dismiss_security_prompt(xml_probe):
                self.p.log_event(
                    'account_switch',
                    f'tt_security_prompt_dismissed step=tt_2_profile_tab retap={retap+1}',
                    meta={'category': 'tt_security_prompt_dismissed',
                          'retap': retap + 1,
                          'platform': 'TikTok'},
                )
                time.sleep(POST_TAP_WAIT_S + 0.5)
                xml_probe = self.p.dump_ui(retries=3) or ''

            if self._tt_is_own_profile(xml_probe):
```

Добавить НОВЫЙ блок между ними (после блока security_prompt, перед `_tt_is_own_profile`):

```python
            # [WP #106 — 2026-05-19] Detect TT profile-tab promo-modals
            # (контакты / Facebook friends) ПЕРЕД own-profile check, иначе
            # модалка sticky над профилем заставит _tt_is_own_profile вернуть
            # False и retap-loop сольёт `tt_profile_tab_broken`. Cap=1 dismiss/retap.
            if self._tt_dismiss_profile_promo_dialog(xml_probe, retap=retap):
                time.sleep(POST_TAP_WAIT_S + 0.5)
                xml_probe = self.p.dump_ui(retries=3) or ''
```

Результирующий блок (для верификации диффа):

```python
            if self._tt_dismiss_security_prompt(xml_probe):
                self.p.log_event(
                    'account_switch',
                    f'tt_security_prompt_dismissed step=tt_2_profile_tab retap={retap+1}',
                    meta={'category': 'tt_security_prompt_dismissed',
                          'retap': retap + 1,
                          'platform': 'TikTok'},
                )
                time.sleep(POST_TAP_WAIT_S + 0.5)
                xml_probe = self.p.dump_ui(retries=3) or ''

            # [WP #106 — 2026-05-19] Detect TT profile-tab promo-modals
            # (контакты / Facebook friends) ПЕРЕД own-profile check, иначе
            # модалка sticky над профилем заставит _tt_is_own_profile вернуть
            # False и retap-loop сольёт `tt_profile_tab_broken`. Cap=1 dismiss/retap.
            if self._tt_dismiss_profile_promo_dialog(xml_probe, retap=retap):
                time.sleep(POST_TAP_WAIT_S + 0.5)
                xml_probe = self.p.dump_ui(retries=3) or ''

            if self._tt_is_own_profile(xml_probe):
```

- [ ] **Step 4: запустить ВСЕ tests промо-файла — verify все 14 PASS**

```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py -v 2>&1 | tail -20
```

Expected: `14 passed`.

- [ ] **Step 5: commit**

```bash
git add account_switcher.py tests/test_account_switcher_profile_promo_dismiss.py
git -c commit.gpgsign=false commit -m "feat(switcher): WP #106 — wire profile-promo dismiss into _switch_tiktok retap-loop"
```

---

## Verification

### Task 6: Full switcher suite regression check

- [ ] **Step 1: запустить полный switcher pytest**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519
pytest tests/test_account_switcher*.py -v 2>&1 | tail -40
```

Expected: все тесты прошли. Сравнить с baseline (Task 0 Step 3): если есть НОВЫЕ FAILED тесты — это регрессия, дойти до root cause перед продолжением. Pre-existing fails (если были в baseline) можно игнорировать.

- [ ] **Step 2: pip-проверка зависимостей**

```bash
python -c "from account_switcher import _TT_PROFILE_PROMO_DISMISSIBLE_MODALS, _tt_try_dismiss_profile_promo, AccountSwitcher; print('imports OK', len(_TT_PROFILE_PROMO_DISMISSIBLE_MODALS), 'entries')"
```

Expected: `imports OK 2 entries`.

- [ ] **Step 3: записать результат в commit-message (если нужен)**

Если Task 6 нашёл и пофиксил pre-existing fail или дополнил тесты — отдельный коммит:

```bash
git status
# Если есть изменения:
git -c commit.gpgsign=false commit -am "fix(switcher): WP #106 — <короткое описание правки>"
```

Если изменений нет — пропустить step.

---

### Task 7: Codex review на финальном diff

- [ ] **Step 1: запустить codex review (workaround per memory `feedback_codex_sandbox_broken`)**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519
git diff origin/main..HEAD | ~/.local/bin/codex review - 2>&1 | tail -80
```

Expected: report'у P1=0. Если P1 issues найдены — пофиксить inline (отдельные коммиты per issue с conventional commit message), повторить codex review, пока 0 P1.

Bubblewrap warning — benign (per memory).

- [ ] **Step 2: если фиксили P1 — повторно прогнать pytest**

```bash
pytest tests/test_account_switcher*.py -v 2>&1 | tail -20
```

Expected: 0 регрессий.

---

### Task 8: Открыть PR (без merge, без push в main)

- [ ] **Step 1: push branch + open PR**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp106-tt-profile-promo-dismiss-20260519
git push -u origin feat/wp106-tt-profile-promo-dismiss-20260519

. ~/secrets/github-gengo2.env
GH_TOKEN="$GITHUB_TOKEN_GENGO2" gh --repo GenGo2/delivery-contenthunter pr create \
  --base main \
  --head feat/wp106-tt-profile-promo-dismiss-20260519 \
  --title "fix(tt-switcher): dismiss known profile-tab promo-modals (WP #106)" \
  --body "$(cat <<'EOF'
## Summary

WP #106 — закрывает топ-1 причину TT publish-fails 2026-05-19:
`tt_profile_tab_broken` (4 кейса / 24% дня, 31 за 7 дней).

Evidence (`docs/evidence/2026-05-19-tt-fails-triage.md` в `rmbrmv/contenthunter`):
4/4 retap1-дампа показывают TT promo-modal поверх профиля. Existing
`_tt_dismiss_security_prompt` не матчит — у этих модалок `content-desc=Диалог`,
а не `Нижняя шторка`.

Solution: зеркало WP #67 Layer 2 (PR #70) — module helper +
AccountSwitcher method + 1 блок в `_switch_tiktok` retap-loop сразу после
security_prompt. Whitelist seeded 2 RU варианта:
- «Чтобы связаться в TikTok» (контакты promo) → «Не разрешать»
- «Разрешить TikTok доступ к списку ваших друзей» (FB friends promo) → «Не разрешать»

Расширяется одной строкой при появлении нового variant'а.

Spec и план в rmbrmv/contenthunter:
- docs/superpowers/specs/2026-05-19-tt-profile-promo-dismiss-design.md
- docs/superpowers/plans/2026-05-19-tt-profile-promo-dismiss-plan.md

## Changes

- account_switcher.py:
  - _TT_PROFILE_PROMO_DISMISSIBLE_MODALS constant (whitelist 2 entries).
  - _tt_try_dismiss_profile_promo() module helper.
  - AccountSwitcher._tt_dismiss_profile_promo_dialog() method (+ kill-switch env).
  - _switch_tiktok retap-loop: новый блок после security_prompt.
- tests/test_account_switcher_profile_promo_dismiss.py: 14 tests (8 unit helper + 4 method + 2 integration).
- tests/fixtures/: 2 новых XML fixture (tasks 7827 contacts, 7870 FB friends).

## Test plan

- [x] 14 new tests passing.
- [x] Full switcher suite — 0 new regressions против baseline main.
- [x] Codex review (full diff) — 0 P1.
- [ ] Post-deploy live smoke: re-queue 1 из 4 сегодняшних тасок (7884) через UPDATE publish_queue → pending — ожидаем `tt_profile_promo_dismiss_attempted` event + tt_2_not_own_profile пропадает.
- [ ] 7-day soak: error_code='tt_profile_tab_broken' падает с 3-7/день до ~0 (или явно идентифицирован новый variant в логах через `not_own_profile` без preceding `dismiss_attempted` — расширим whitelist).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: новый PR создан, URL выведен. **НЕ мерджить** — пусть пользователь ревьюит.

- [ ] **Step 2: записать URL PR в task summary для пользователя**

Вернуть PR URL и dump последних 3-4 коммитов:

```bash
git log -5 --oneline
```

---

## Self-Review

### Spec coverage check

Прохожу spec section-by-section:

- **§1 Контекст и симптом** — задокументирован в Task header'е (Goal/Architecture); evidence упомянут в PR body. ✓
- **§2 Цель** — success criteria покрыты Task 6 (regression) + Task 8 (smoke + soak в PR body). ✓
- **§3.1 Module constant** — Task 2 Step 3 (с точным кодом). ✓
- **§3.2 Module helper** — Task 2 Step 3 (с точным кодом + 5 положительных и отрицательных кейсов в Task 2 + Task 3). ✓
- **§3.3 AccountSwitcher method** — Task 4 Step 3 (с точным кодом). ✓
- **§3.4 Integration site** — Task 5 Step 3 (с точным before/after блоком). ✓
- **§3.5 Observability events** — Task 4 tests `test_method_match_emits_event_and_taps` + `test_method_tap_failed_emits_warning_returns_false` проверяют meta. ✓
- **§3.6 Kill-switch** — Task 4 test `test_method_kill_switch_disabled`. ✓
- **§4 Test plan** — все 14 тестов разнесены по Task 2-5. ✓
- **§5 Deploy** — out of scope для plan'а (deploy происходит после merge PR через auto-push hook). Упоминаю в PR body как next-step. ✓
- **§6 Risks** — mitigations покрыты через test coverage (title-substr защита, kill-switch, fall-through). ✓
- **§7 Out of scope** — не реализуем EN-варианты, vision recovery, новый error_code. ✓
- **§8 Файлы** — Task header'ы перечисляют все 4 файла. ✓
- **§9 Acceptance** — 5 checkboxes покрыты Task 6/7/8 + PR body smoke/soak. ✓

Гэпов нет.

### Placeholder scan

Перечитал план — нет:
- "TBD" / "TODO" / "implement later" / "fill in details"
- "Add appropriate error handling" / "handle edge cases"
- "Write tests for the above" без кода
- "Similar to Task N" — каждый task self-contained
- Шагов без кода/команд

✓

### Type consistency

- `_TT_PROFILE_PROMO_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...]` — везде согласованно.
- `_tt_try_dismiss_profile_promo(xml: str) -> Optional[tuple[str, str]]` — sig идентичен в spec и плане.
- `_tt_dismiss_profile_promo_dialog(self, ui_xml: str, retap: int) -> bool` — sig идентичен.
- Event names: `tt_profile_promo_dismiss_attempted` / `tt_profile_promo_dismiss_tap_failed` — везде одинаково.
- Whitelist entries: оба title_substr строки идентичны в spec, helper-test, integration-test.

✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-tt-profile-promo-dismiss-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** — я дispatcham fresh subagent per task, review между tasks, быстрая итерация.

2. **Inline Execution** — выполнение в этой сессии через `superpowers:executing-plans`, batch execution с checkpoints для review.

Какой подход?
