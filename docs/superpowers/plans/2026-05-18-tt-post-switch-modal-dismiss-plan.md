# TT post-switch promo-modal dismiss — Implementation Plan (WP #67 Layer 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть residual `tt_post_switch_verify_unrecoverable` fails (1–2/день) — научить TT post-switch verify закрывать известные dismissible promo-модалки и re-verify, вместо немедленного fail'а.

**Architecture:** Variant A из спеки. Module-level whitelist `(title_substr, button_text)` + pure helper `_tt_try_dismiss_post_switch_modal(xml)` + method `_try_dismiss_and_redump(...)` + 2 probe-site вставки в `AccountSwitcher._tt_handle_post_switch_unknown` (pre-feed-detect и post-renav-re-verify). Cap=1 dismiss на probe-site, total ≤2 на handle.

**Tech Stack:** Python 3.12, pytest, `unittest.mock.MagicMock`, существующий `parse_ui_dump`/`UIElement` из `account_switcher.py`, `tap_element` из `publisher_base.py:1600`.

**Spec:** [docs/superpowers/specs/2026-05-18-tt-post-switch-modal-dismiss-design.md](../specs/2026-05-18-tt-post-switch-modal-dismiss-design.md)

**Repo:** Реализация в `GenGo2/delivery-contenthunter` (а не в `rmbrmv/contenthunter`). Все пути под `/root/.openclaw/workspace-genri/autowarm/` относятся к prod-чекауту; разработка ведётся в **отдельном dev-чекауте** на feature-ветке, см. Task 0.

---

## File Structure

**Modify (один файл):** `/root/.openclaw/workspace-genri/autowarm/account_switcher.py`
- Add module-level constant `_TT_POST_SWITCH_DISMISSIBLE_MODALS` после `_TT_FEED_MARKERS` (после line 216).
- Add module-level helper `_tt_try_dismiss_post_switch_modal(xml) -> Optional[tuple[str, str]]` рядом с остальными TT-helper'ами (рядом с `_is_tt_feed_after_pick` ~line 4216).
- Add method `AccountSwitcher._try_dismiss_and_redump(...)` рядом с `_tt_handle_post_switch_unknown` (~line 4256).
- Modify `AccountSwitcher._tt_handle_post_switch_unknown` (line 4256–4341) — 2 новых probe-site вызова.

**Create (тесты):** `/root/.openclaw/workspace-genri/autowarm/tests/test_account_switcher_modal_dismiss.py` — новый модуль для всех тестов этого фикса (изолирован, не пересекается с существующими `test_account_switcher_tt.py`).

**Create (фикстуры):** в `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/`:
- `tt_post_switch_modal_phone_email_6514.xml` — байт-в-байт копия дампа из `/tmp/wp67_6514_xml.xml`.
- `tt_post_switch_modal_save_login_7307_renav.xml` — копия из `/tmp/wp67_7307_task7307_switch_7307_tt_4_target_profile_renav_1779100142.xml.xml`.
- (Reuse) `tt_post_switch_5817_relism_e.xml` — existing fixture, negative (profile screen with `@handle`).
- (Reuse) `tt_feed_no_sheet.xml` — existing fixture, negative (TT feed top-bar).

---

## Task 0: Setup dev worktree + baseline

**Files:** Создаём dev-чекаут autowarm на отдельной ветке. Prod-чекаут `/root/.openclaw/workspace-genri/autowarm/` НЕ трогаем (там auto-push hook + PM2 cwd).

- [ ] **Step 1: Создать dev-worktree autowarm**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git worktree add /home/claude-user/autowarm-wp67-tt-modal -b worktree-wp67-tt-modal-dismiss-2026-05-18 origin/main
cd /home/claude-user/autowarm-wp67-tt-modal
git log --oneline -3
```

Expected: новая ветка `worktree-wp67-tt-modal-dismiss-2026-05-18` от свежего `origin/main`. Последний коммит — на main (memory `feedback_parallel_claude_sessions`: git fetch перед стартом).

- [ ] **Step 2: Baseline switcher tests должны быть зелёные (или с известным pre-existing fail)**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
pytest tests/test_account_switcher.py tests/test_account_switcher_tt.py tests/test_switcher_read_only.py tests/test_switcher_step_progress.py tests/test_switcher_youtube.py tests/test_tt_account_switcher_open.py -v 2>&1 | tail -30
```

Expected: всё passed, либо ≤1 pre-existing fail `test_yt_happy_path_returns_accounts` (memory: known pre-existing per WP #67 Layer 1 PR #62 deploy notes). Если новые fail'ы — STOP, report.

- [ ] **Step 3: Pwd check + commit-author check**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal && pwd && git config user.email && git remote -v
```

Expected: pwd = dev-worktree (НЕ /root/.openclaw/...), email задан, remote = GenGo2/delivery-contenthunter.

---

## Task 1: Copy fixtures into autowarm tests/fixtures/

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_switch_modal_phone_email_6514.xml`
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_switch_modal_save_login_7307_renav.xml`

NB: пути выше — в dev-worktree (`/home/claude-user/autowarm-wp67-tt-modal/tests/fixtures/`), а не в prod-чекауте. Subagent должен `cd` в dev-worktree сначала.

- [ ] **Step 1: Скопировать fixtures из /tmp (уже скачаны в evidence-сборе)**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
cp /tmp/wp67_6514_xml.xml tests/fixtures/tt_post_switch_modal_phone_email_6514.xml
cp /tmp/wp67_7307_task7307_switch_7307_tt_4_target_profile_renav_1779100142.xml.xml tests/fixtures/tt_post_switch_modal_save_login_7307_renav.xml
wc -c tests/fixtures/tt_post_switch_modal_phone_email_6514.xml tests/fixtures/tt_post_switch_modal_save_login_7307_renav.xml
```

Expected:
- `tt_post_switch_modal_phone_email_6514.xml` = 7603 bytes (modal title `Привязать номер...`, button `Не сейчас` at `y=1433`)
- `tt_post_switch_modal_save_login_7307_renav.xml` ≈ 8298 bytes (modal title `Сохранить данные для входа`, button `Не сейчас` at `y≈1388`)

Если /tmp файлы пропали — re-download:

```bash
curl -s -o tests/fixtures/tt_post_switch_modal_phone_email_6514.xml \
  "https://save.gengo.io/autowarm/ui_dumps/tiktok/task6514_switch_6514_tt_4_target_profile_1778850014.xml"
curl -s -o tests/fixtures/tt_post_switch_modal_save_login_7307_renav.xml \
  "https://save.gengo.io/autowarm/ui_dumps/tiktok/task7307_switch_7307_tt_4_target_profile_renav_1779100142.xml"
```

- [ ] **Step 2: Sanity-check содержимое**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
grep -o 'text="[^"]*"' tests/fixtures/tt_post_switch_modal_phone_email_6514.xml | grep -E "Привязать|Не сейчас"
grep -o 'text="[^"]*"' tests/fixtures/tt_post_switch_modal_save_login_7307_renav.xml | grep -E "Сохранить|Не сейчас"
```

Expected:
```
text="Привязать номер телефона или эл. почту"
text="Не сейчас"
text="Сохранить данные для входа"
text="Не сейчас"
```

- [ ] **Step 3: Commit fixtures**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
git add tests/fixtures/tt_post_switch_modal_phone_email_6514.xml tests/fixtures/tt_post_switch_modal_save_login_7307_renav.xml
git commit -m "test(switcher): TT post-switch modal fixtures (WP #67)

Evidence dumps from tasks 6514 (phone/email bind modal) and 7307
(save-login modal post-renav). Both block tt_4_target_profile verify
with dismissible 'Не сейчас' buttons.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add whitelist constant + failing unit tests for `_tt_try_dismiss_post_switch_modal`

**Files:**
- Modify: `/home/claude-user/autowarm-wp67-tt-modal/account_switcher.py` — добавить только константу (helper будет в Task 3).
- Create: `/home/claude-user/autowarm-wp67-tt-modal/tests/test_account_switcher_modal_dismiss.py`

- [ ] **Step 1: Добавить константу `_TT_POST_SWITCH_DISMISSIBLE_MODALS` после `_TT_FEED_MARKERS` (line 216)**

Открой `account_switcher.py`. После строки `_TT_FEED_MARKERS = ('Смотреть', 'Подписки', 'Рекомендации')` (line 216) вставь:

```python

# [WP #67 Layer 2 — 2026-05-18] Whitelist post-switch dismissible promo-modals.
# Evidence: tasks 6514/6631/6704/6786 (phone/email bind), 7307 (save login).
# Match requires BOTH title_substr AND clickable button_text on screen —
# защита от ложного dismiss другого 'Не сейчас' в неродственном контексте.
# Расширяется по одной строке при появлении новой evidence.
_TT_POST_SWITCH_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...] = (
    # (title_substring, dismiss_button_text)
    ('Привязать номер телефона или эл. почту', 'Не сейчас'),
    ('Сохранить данные для входа', 'Не сейчас'),
)
```

- [ ] **Step 2: Создать test файл с failing unit-тестами (helper не существует пока)**

Создай `tests/test_account_switcher_modal_dismiss.py` с содержимым:

```python
"""Unit + integration tests для WP #67 Layer 2 — post-switch promo-modal dismiss.

См. design spec docs/superpowers/specs/2026-05-18-tt-post-switch-modal-dismiss-design.md

Запуск:
    cd /root/.openclaw/workspace-genri/autowarm
    pytest tests/test_account_switcher_modal_dismiss.py -v
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
    _TT_POST_SWITCH_DISMISSIBLE_MODALS,
    _tt_try_dismiss_post_switch_modal,
)


FIXTURES = ROOT / 'tests' / 'fixtures'


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


# ─── _tt_try_dismiss_post_switch_modal — pure unit ──────────────────────────


def test_whitelist_seeded_with_two_entries():
    """Whitelist должен содержать оба evidence-кейса WP #67."""
    titles = [t for t, _ in _TT_POST_SWITCH_DISMISSIBLE_MODALS]
    assert any('Привязать номер' in t for t in titles)
    assert any('Сохранить данные для входа' in t for t in titles)


def test_modal_phone_email_6514_returns_match():
    """task 6514 dump → ('Привязать номер...', 'Не сейчас')."""
    xml = _read_fixture('tt_post_switch_modal_phone_email_6514.xml')
    result = _tt_try_dismiss_post_switch_modal(xml)
    assert result is not None
    title, button = result
    assert 'Привязать номер' in title
    assert button == 'Не сейчас'


def test_modal_save_login_7307_returns_match():
    """task 7307 renav dump → ('Сохранить данные для входа', 'Не сейчас')."""
    xml = _read_fixture('tt_post_switch_modal_save_login_7307_renav.xml')
    result = _tt_try_dismiss_post_switch_modal(xml)
    assert result is not None
    title, button = result
    assert title == 'Сохранить данные для входа'
    assert button == 'Не сейчас'


def test_profile_screen_5817_returns_none():
    """Реальный TT profile screen с @handle → None (negative)."""
    xml = _read_fixture('tt_post_switch_5817_relism_e.xml')
    assert _tt_try_dismiss_post_switch_modal(xml) is None


def test_feed_no_sheet_returns_none():
    """TT feed top-bar → None (negative)."""
    xml = _read_fixture('tt_feed_no_sheet.xml')
    assert _tt_try_dismiss_post_switch_modal(xml) is None


def test_empty_xml_returns_none():
    assert _tt_try_dismiss_post_switch_modal('') is None


def test_unparseable_xml_returns_none():
    """parse_ui_dump empty → None."""
    assert _tt_try_dismiss_post_switch_modal('<not-hierarchy>x</not-hierarchy>') is None


def test_title_present_but_no_button_returns_none():
    """Title есть, но button не clickable / отсутствует — None."""
    xml = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="Привязать номер телефона или эл. почту" clickable="false"
        bounds="[0,100][1080,200]" content-desc="" />
</hierarchy>'''
    assert _tt_try_dismiss_post_switch_modal(xml) is None


def test_button_present_but_no_title_returns_none():
    """Button есть, но title не найден — None (защита от false-positive)."""
    xml = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="Не сейчас" clickable="true"
        bounds="[400,1400][680,1480]" content-desc="" />
</hierarchy>'''
    assert _tt_try_dismiss_post_switch_modal(xml) is None


def test_button_present_but_not_clickable_returns_none():
    """Title + button text есть, но button НЕ clickable → None."""
    xml = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="Сохранить данные для входа" clickable="false"
        bounds="[0,500][1080,600]" content-desc="" />
  <node text="Не сейчас" clickable="false"
        bounds="[400,1400][680,1480]" content-desc="" />
</hierarchy>'''
    assert _tt_try_dismiss_post_switch_modal(xml) is None
```

- [ ] **Step 3: Прогнать тесты — должны fail'нуть на ImportError**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
pytest tests/test_account_switcher_modal_dismiss.py -v 2>&1 | tail -10
```

Expected: ImportError на `_tt_try_dismiss_post_switch_modal` (импорт в test файле, helper ещё не существует). Если иначе — STOP.

- [ ] **Step 4: Закоммитить failing tests + constant**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
git add account_switcher.py tests/test_account_switcher_modal_dismiss.py
git commit -m "test(switcher): failing unit tests for TT post-switch modal dismiss (WP #67)

10 unit tests for _tt_try_dismiss_post_switch_modal — fails with
ImportError until Task 3 implements the helper. Whitelist constant
already added with 2 evidence-seeded entries.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Implement `_tt_try_dismiss_post_switch_modal` helper

**Files:**
- Modify: `/home/claude-user/autowarm-wp67-tt-modal/account_switcher.py`

- [ ] **Step 1: Добавить helper после `_is_tt_feed_after_pick` (~line 4239)**

Найди `def _is_tt_feed_after_pick(self, ...)` в `account_switcher.py` (line 4216). Этот метод — instance-method, но **новый helper будет module-level** (как и `parse_ui_dump`). Найди определение `parse_ui_dump` (line 337) — добавь новый helper сразу после него на module-level.

Add:

```python
def _tt_try_dismiss_post_switch_modal(xml: str) -> Optional[tuple[str, str]]:
    """[WP #67 Layer 2 — 2026-05-18] Detect known dismissible TT promo-modal.

    Используется в `AccountSwitcher._tt_handle_post_switch_unknown` чтобы
    отличить ситуацию "после переключения вылез promo-модал" от настоящего
    `non-feed` fail'а. Match требует ОБА условия:
      - элемент с `title_substr` в `.label` где-то на экране;
      - clickable элемент с `.label.strip().lower() == button_text.lower()`.

    Title-check защищает от ложного dismiss другого 'Не сейчас' в другом
    контексте (например permission dialog).

    Returns: (title_substr, button_text) первой совпавшей записи whitelist;
    None если ни одна не сматчилась.
    """
    if not xml:
        return None
    elements = parse_ui_dump(xml)
    if not elements:
        return None
    for title_substr, button_text in _TT_POST_SWITCH_DISMISSIBLE_MODALS:
        title_seen = any(title_substr in el.label for el in elements)
        if not title_seen:
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

- [ ] **Step 2: Прогнать unit-тесты — все должны pass**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
pytest tests/test_account_switcher_modal_dismiss.py -v 2>&1 | tail -20
```

Expected: все 10 тестов PASSED. Если хоть один FAILED — debugging:
- ImportError на `_tt_try_dismiss_post_switch_modal` → helper не на module-level или опечатка в имени.
- Negative-тест fails → проверь что title-check **И** button-check оба обязательны.

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
git add account_switcher.py
git commit -m "feat(switcher): _tt_try_dismiss_post_switch_modal helper (WP #67 Layer 2)

Pure module-level detector — matches whitelist title_substr + clickable
button_text. Returns (title, button) or None. Used by
_tt_handle_post_switch_unknown to distinguish dismissible promo-modal
from genuine non-feed failure.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Failing integration tests for `_tt_handle_post_switch_unknown` modal branches

**Files:**
- Modify: `/home/claude-user/autowarm-wp67-tt-modal/tests/test_account_switcher_modal_dismiss.py` — добавить integration-блок ниже unit-тестов.

- [ ] **Step 1: Дописать integration tests в конец `test_account_switcher_modal_dismiss.py`**

Open `tests/test_account_switcher_modal_dismiss.py` и в конец добавь:

```python


# ─── _tt_handle_post_switch_unknown — integration ───────────────────────────


def _make_switcher_for_handle_test() -> AccountSwitcher:
    """AccountSwitcher с mock publisher. Минимум для _tt_handle_post_switch_unknown."""
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.adb = MagicMock(return_value='')
    publisher.log_event = MagicMock()
    publisher.set_step = MagicMock()
    publisher.tap_element = MagicMock(return_value=True)
    publisher.dump_ui = MagicMock(return_value='')
    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    sw._fail = MagicMock(return_value=MagicMock(success=False, reason='stub_fail'))
    return sw


def _events_with_name(switcher: AccountSwitcher, name: str) -> list:
    """Извлечь все log_event-вызовы с заданным event_name."""
    return [
        call for call in switcher.p.log_event.call_args_list
        if len(call.args) >= 2 and call.args[1] == name
    ]


def test_pre_feed_dismiss_happy_path(monkeypatch):
    """xml_after_pick = modal → dismiss → re-verify match → ('recovered', target, None)."""
    sw = _make_switcher_for_handle_test()
    xml_modal = _read_fixture('tt_post_switch_modal_phone_email_6514.xml')
    xml_profile_after_dismiss = _read_fixture('tt_post_switch_5817_relism_e.xml')

    # dump_ui вызовется ОДИН раз — после dismiss tap.
    sw.p.dump_ui.return_value = xml_profile_after_dismiss

    # Stub re-verify: первый вызов возвращает 'match' (после dismiss).
    monkeypatch.setattr(
        sw, '_post_switch_verify_handle',
        MagicMock(return_value=('match', 'pure_oracle')),
    )

    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='pure_oracle',
        xml_after_pick=xml_modal,
        header_y_max=700,
        label='tt_4_target_profile',
        attempt=0,
    )

    assert outcome == 'recovered'
    assert current == 'pure_oracle'
    assert fail_result is None
    sw.p.tap_element.assert_called_once_with(
        xml_modal, ['Не сейчас'], clickable_only=True,
    )
    recovered_events = _events_with_name(sw, 'tt_post_switch_recovered_via_modal_dismiss')
    assert len(recovered_events) == 1
    assert recovered_events[0].kwargs['meta']['probe_site'] == 'pre_feed'
    sw._fail.assert_not_called()


def test_post_renav_dismiss_happy_path(monkeypatch):
    """xml_after_pick = feed → renav → xml_after_renav = modal → dismiss → match."""
    sw = _make_switcher_for_handle_test()
    xml_feed = _read_fixture('tt_feed_no_sheet.xml')
    xml_renav_modal = _read_fixture('tt_post_switch_modal_save_login_7307_renav.xml')
    xml_profile_after_dismiss = _read_fixture('tt_post_switch_5817_relism_e.xml')

    # Renav: 1st dump_ui (after _navigate_to_profile_tab) → renav_modal;
    # 2nd dump_ui (after modal dismiss tap) → profile.
    sw.p.dump_ui.side_effect = [xml_renav_modal, xml_profile_after_dismiss]
    # Stub renav itself to return True (navigated).
    monkeypatch.setattr(sw, '_navigate_to_profile_tab', MagicMock(return_value=True))

    # Stub re-verify:
    #   1st call (after renav, xml = renav_modal) → 'unknown'
    #   2nd call (after modal dismiss, xml = profile)   → 'match'
    monkeypatch.setattr(
        sw, '_post_switch_verify_handle',
        MagicMock(side_effect=[('unknown', None), ('match', 'just_clickpay')]),
    )

    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='just_clickpay',
        xml_after_pick=xml_feed,
        header_y_max=700,
        label='tt_4_target_profile',
        attempt=0,
    )

    assert outcome == 'recovered'
    assert current == 'just_clickpay'
    assert fail_result is None
    recovered_events = _events_with_name(sw, 'tt_post_switch_recovered_via_modal_dismiss')
    assert len(recovered_events) == 1
    assert recovered_events[0].kwargs['meta']['probe_site'] == 'post_renav'
    sw._fail.assert_not_called()


def test_whitelist_miss_falls_through_to_existing_fail():
    """xml_after_pick = unknown_screen (no whitelist match, not feed) → existing fail."""
    sw = _make_switcher_for_handle_test()
    xml_unknown = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="Какой-то непредвиденный текст" clickable="false"
        bounds="[0,500][1080,600]" content-desc="" />
</hierarchy>'''

    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='expertcontentlab',
        xml_after_pick=xml_unknown,
        header_y_max=700,
        label='tt_4_target_profile',
        attempt=0,
    )

    assert outcome == 'failed'
    assert current is None
    assert fail_result is not None
    sw._fail.assert_called_once()
    fail_msg = sw._fail.call_args.args[0]
    assert 'tt_post_switch_verify_unrecoverable: unknown header non-feed' in fail_msg
    sw.p.tap_element.assert_not_called()  # whitelist miss = no tap


def test_modal_matched_reverify_still_unknown_falls_through(monkeypatch):
    """Modal dismissed but re-verify still unknown AND new XML is not feed → existing fail."""
    sw = _make_switcher_for_handle_test()
    xml_modal = _read_fixture('tt_post_switch_modal_phone_email_6514.xml')
    # После dismiss экран всё равно непонятный (не feed, не profile).
    xml_unknown_after_dismiss = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="loading..." clickable="false"
        bounds="[0,500][1080,600]" content-desc="" />
</hierarchy>'''
    sw.p.dump_ui.return_value = xml_unknown_after_dismiss
    monkeypatch.setattr(
        sw, '_post_switch_verify_handle',
        MagicMock(return_value=('unknown', None)),
    )

    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='pure_oracle',
        xml_after_pick=xml_modal,
        header_y_max=700,
        label='tt_4_target_profile',
        attempt=0,
    )

    assert outcome == 'failed'
    assert current is None
    no_recovery_events = _events_with_name(sw, 'tt_post_switch_modal_dismiss_no_recovery')
    assert len(no_recovery_events) == 1


def test_modal_matched_reverify_mismatch_falls_through(monkeypatch):
    """Modal dismissed, re-verify = mismatch → пропускаем в existing mismatch path."""
    sw = _make_switcher_for_handle_test()
    xml_modal = _read_fixture('tt_post_switch_modal_phone_email_6514.xml')
    xml_other_profile = _read_fixture('tt_post_switch_5817_relism_e.xml')
    sw.p.dump_ui.return_value = xml_other_profile
    monkeypatch.setattr(
        sw, '_post_switch_verify_handle',
        MagicMock(return_value=('mismatch', 'relism_e')),
    )

    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='pure_oracle',
        xml_after_pick=xml_modal,
        header_y_max=700,
        label='tt_4_target_profile',
        attempt=0,
    )

    # После dismiss → mismatch → caller разберётся (mismatch-retry-loop).
    # _tt_handle_post_switch_unknown возвращает outcome='mismatch' напрямую.
    assert outcome == 'mismatch'
    assert current == 'relism_e'
    assert fail_result is None


def test_tap_element_returns_false_no_recovery_event(monkeypatch):
    """tap_element=False (DOM сместился) → tap_failed event + fall through."""
    sw = _make_switcher_for_handle_test()
    xml_modal = _read_fixture('tt_post_switch_modal_phone_email_6514.xml')
    sw.p.tap_element = MagicMock(return_value=False)

    outcome, current, fail_result = sw._tt_handle_post_switch_unknown(
        target='pure_oracle',
        xml_after_pick=xml_modal,
        header_y_max=700,
        label='tt_4_target_profile',
        attempt=0,
    )

    assert outcome == 'failed'
    # dump_ui НЕ должен вызваться после неудачного tap.
    sw.p.dump_ui.assert_not_called()
    # Event tap_failed залогирован.
    tap_failed_events = _events_with_name(sw, 'tt_post_switch_modal_dismiss_no_recovery')
    assert len(tap_failed_events) == 1
    assert tap_failed_events[0].kwargs['meta']['reverify_status'] == 'tap_failed'
```

- [ ] **Step 2: Прогнать integration tests — должны fail'нуть**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
pytest tests/test_account_switcher_modal_dismiss.py -v -k "test_pre_feed_dismiss or test_post_renav_dismiss or test_whitelist_miss or test_modal_matched or test_tap_element" 2>&1 | tail -20
```

Expected: 6 integration тестов FAILED (модификация `_tt_handle_post_switch_unknown` ещё не сделана; pre-feed-probe не вызывается, dismiss не происходит, recovered events не пишутся).

Pre-existing 10 unit-тестов из Task 3 должны быть зелёные.

- [ ] **Step 3: Commit failing integration tests**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
git add tests/test_account_switcher_modal_dismiss.py
git commit -m "test(switcher): failing integration tests — 2 probe sites WP #67 Layer 2

6 integration scenarios for _tt_handle_post_switch_unknown:
- pre_feed_dismiss_happy_path
- post_renav_dismiss_happy_path
- whitelist_miss_falls_through_to_existing_fail
- modal_matched_reverify_still_unknown_falls_through
- modal_matched_reverify_mismatch_falls_through
- tap_element_returns_false_no_recovery_event

Fail until Task 5 wires probe sites.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Implement `_try_dismiss_and_redump` method + wire 2 probe sites

**Files:**
- Modify: `/home/claude-user/autowarm-wp67-tt-modal/account_switcher.py` — функция `_tt_handle_post_switch_unknown` (line 4256–4341).

- [ ] **Step 1: Добавить private method `_try_dismiss_and_redump` сразу перед `_tt_handle_post_switch_unknown`**

Найди line 4256 (def `_tt_handle_post_switch_unknown`). Вставь перед ней:

```python
    def _try_dismiss_and_redump(self, xml: str, *,
                                       probe_site: str, target: str,
                                       label: str, attempt: int):
        """[WP #67 Layer 2 — 2026-05-18] Probe whitelist + dismiss + re-dump.

        Returns:
            new XML (str) если whitelist-match и tap прошёл успешно;
            None если whitelist miss ИЛИ tap_element вернул False.

        Caller должен вызвать `_post_switch_verify_handle` на возвращённом XML.
        """
        matched = _tt_try_dismiss_post_switch_modal(xml)
        if matched is None:
            return None
        title_substr, button_text = matched
        self.p.log_event(
            'info', 'tt_post_switch_modal_dismiss_attempted',
            meta={'title_substr': title_substr, 'button_text': button_text,
                  'probe_site': probe_site, 'target': target,
                  'attempt': attempt + 1,
                  'category': 'tt_post_switch_modal_dismiss_attempted'},
        )
        tapped = self.p.tap_element(xml, [button_text], clickable_only=True)
        if not tapped:
            self.p.log_event(
                'warning', 'tt_post_switch_modal_dismiss_no_recovery',
                meta={'title_substr': title_substr, 'target': target,
                      'probe_site': probe_site, 'reverify_status': 'tap_failed',
                      'category': 'tt_post_switch_modal_dismiss_no_recovery'},
            )
            return None
        time.sleep(1.0)
        new_xml = self.p.dump_ui(retries=1) or ''
        self._save_dump(f'{label}_after_modal_dismiss', new_xml)
        return new_xml
```

- [ ] **Step 2: Модифицировать `_tt_handle_post_switch_unknown` — 2 probe-site вставки**

Открой `_tt_handle_post_switch_unknown` (после вставки helper'а её body будет на ~line 4296). Замени **всю** функцию (от `def _tt_handle_post_switch_unknown` до `return ('failed', None, fail_result)` включительно) на:

```python
    def _tt_handle_post_switch_unknown(self, target: str, xml_after_pick: str,
                                       header_y_max: int, label: str,
                                       attempt: int) -> tuple:
        """[tt_post_switch_renav 2026-05-11 + WP #67 Layer 2 2026-05-18]
        Recovery для unknown verify status.

        Step 0a (NEW, WP #67 Layer 2): pre-feed-detect probe — если
        xml_after_pick matches whitelist promo-modal → dismiss → re-verify.
        Match → recovered; иначе fall through к existing logic c новым XML.

        Step 1–4 (existing):
          1. Детектим TT feed-top-bar в первичном XML.
          2. Если feed → log + navigate-to-profile + re-dump + re-verify.
          3a (NEW, WP #67 Layer 2): если re-verify=unknown — ещё один probe
             модалки (post-renav site).
          3. По re-verify результату:
             - match    → лог recovered_via_renav,
                          return ('recovered', current, None)
             - mismatch → return ('mismatch', current, None)
             - unknown  → _fail с tt_post_switch_verify_unrecoverable,
                          return ('failed', None, SwitchResult)
          4. Если в первичном XML feed-markers НЕТ → _fail сразу.

        Returns: tuple[outcome: str, current: Optional[str],
                       fail_result: Optional[SwitchResult]]
                 outcome ∈ {'recovered', 'mismatch', 'failed'}.
        """
        # ── Step 0a (WP #67 Layer 2): pre-feed-detect modal probe ────────────
        dismissed_xml = self._try_dismiss_and_redump(
            xml_after_pick, probe_site='pre_feed', target=target,
            label=label, attempt=attempt,
        )
        if dismissed_xml is not None:
            status, current = self._post_switch_verify_handle(
                target, dismissed_xml, header_y_max=header_y_max,
            )
            if status == 'match':
                self.p.log_event(
                    'account_switch', 'tt_post_switch_recovered_via_modal_dismiss',
                    meta={'category': 'tt_post_switch_recovered_via_modal_dismiss',
                          'target': target, 'current': current,
                          'probe_site': 'pre_feed', 'attempt': attempt + 1},
                )
                return ('recovered', current, None)
            self.p.log_event(
                'warning', 'tt_post_switch_modal_dismiss_no_recovery',
                meta={'category': 'tt_post_switch_modal_dismiss_no_recovery',
                      'target': target, 'probe_site': 'pre_feed',
                      'reverify_status': status},
            )
            # Replace XML so existing logic uses post-dismiss screen.
            xml_after_pick = dismissed_xml
            if status == 'mismatch':
                return ('mismatch', current, None)
            # status == 'unknown' — fall through to existing feed-detect path.

        # ── Existing: feed-detect ────────────────────────────────────────────
        is_feed = self._is_tt_feed_after_pick(xml_after_pick, header_y_max)
        if not is_feed:
            fail_result = self._fail(
                f'tt_post_switch_verify_unrecoverable: unknown header non-feed '
                f'(target={target!r})',
                step=label,
            )
            return ('failed', None, fail_result)

        # Feed-after-pick — известное regression в новом TT UX.
        self.p.log_event(
            'warning', 'tt_post_switch_feed_after_pick',
            meta={'category': 'tt_post_switch_feed_after_pick',
                  'target': target, 'step': label,
                  'attempt': attempt + 1},
        )
        nav_ok = self._navigate_to_profile_tab()
        if not nav_ok:
            self.p.log_event(
                'error', 'tt_post_switch_renav_failed',
                meta={'category': 'tt_post_switch_renav_failed',
                      'target': target, 'step': label,
                      'attempt': attempt + 1},
            )
            fail_result = self._fail(
                f'tt_post_switch_verify_unrecoverable: navigate_to_profile_tab '
                f'failed после feed-detect (target={target!r})',
                step=f'{label}_renav',
            )
            return ('failed', None, fail_result)
        xml_after_renav = self.p.dump_ui(retries=1) or ''
        self._save_dump(f'{label}_renav', xml_after_renav)
        status, current = self._post_switch_verify_handle(
            target, xml_after_renav, header_y_max=header_y_max,
        )

        # ── Step 3a (WP #67 Layer 2): post-renav modal probe ────────────────
        if status == 'unknown':
            dismissed_xml = self._try_dismiss_and_redump(
                xml_after_renav, probe_site='post_renav', target=target,
                label=f'{label}_renav', attempt=attempt,
            )
            if dismissed_xml is not None:
                status, current = self._post_switch_verify_handle(
                    target, dismissed_xml, header_y_max=header_y_max,
                )
                if status == 'match':
                    self.p.log_event(
                        'account_switch', 'tt_post_switch_recovered_via_modal_dismiss',
                        meta={'category': 'tt_post_switch_recovered_via_modal_dismiss',
                              'target': target, 'current': current,
                              'probe_site': 'post_renav', 'attempt': attempt + 1},
                    )
                    return ('recovered', current, None)
                self.p.log_event(
                    'warning', 'tt_post_switch_modal_dismiss_no_recovery',
                    meta={'category': 'tt_post_switch_modal_dismiss_no_recovery',
                          'target': target, 'probe_site': 'post_renav',
                          'reverify_status': status},
                )

        if status == 'match':
            self.p.log_event(
                'account_switch', 'tt_post_switch_recovered_via_renav',
                meta={'category': 'tt_post_switch_recovered_via_renav',
                      'target': target, 'current': current,
                      'attempt': attempt + 1},
            )
            return ('recovered', current, None)
        if status == 'mismatch':
            return ('mismatch', current, None)
        fail_result = self._fail(
            f'tt_post_switch_verify_unrecoverable: no profile after re-nav '
            f'(target={target!r})',
            step=f'{label}_renav',
        )
        return ('failed', None, fail_result)
```

- [ ] **Step 3: Прогнать тесты модуля — все 16 (10 unit + 6 integration) должны pass**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
pytest tests/test_account_switcher_modal_dismiss.py -v 2>&1 | tail -30
```

Expected: 16 passed. Если хоть один failed — debugging:
- `test_pre_feed_dismiss_happy_path` fails: probe-call не на правильном XML, или event-name typo.
- `test_post_renav_dismiss_happy_path` fails: dump_ui.side_effect order (1st = renav dump, 2nd = post-dismiss).
- `test_modal_matched_reverify_mismatch_falls_through`: проверь return point после dismiss=mismatch.
- `test_tap_element_returns_false_no_recovery_event`: dump_ui не должен вызываться вообще; check the `return None` после `if not tapped`.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
git add account_switcher.py
git commit -m "feat(switcher): wire 2 probe sites for TT post-switch modal dismiss (WP #67 Layer 2)

Add _try_dismiss_and_redump method + wire into
_tt_handle_post_switch_unknown at:
  - pre_feed (before is_feed check)
  - post_renav (after re-verify=unknown)

Cap=1 dismiss per probe site, total ≤2 per handle. Match writes
tt_post_switch_recovered_via_modal_dismiss event; miss writes
tt_post_switch_modal_dismiss_no_recovery + falls through to existing
non-feed / no-profile fail. No new error_code: distinguishes via
presence of dismiss_attempted events in publish_tasks.events.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Full switcher suite — no regressions

**Files:** —

- [ ] **Step 1: Прогнать ВСЕ switcher-тесты**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
pytest tests/test_account_switcher.py tests/test_account_switcher_tt.py tests/test_account_switcher_modal_dismiss.py tests/test_switcher_read_only.py tests/test_switcher_step_progress.py tests/test_switcher_youtube.py tests/test_tt_account_switcher_open.py -v 2>&1 | tail -40
```

Expected: новые 16 тестов passed, существующие — без новых fail'ов. Допустим 1 pre-existing fail `test_yt_happy_path_returns_accounts` (см. WP #67 Layer 1 PR #62 deploy notes, не наша регрессия).

- [ ] **Step 2: Если есть НОВЫЕ fail'ы — diff baseline и debug**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
# Сравнить с baseline из Task 0 Step 2 — какие тесты ДОБАВИЛИ fail?
# Если регрессия — STOP, найти и пофиксить, не мерджить.
```

Не было новых fail'ов? → переходим дальше.

- [ ] **Step 3: Smoke — реальный prod-dataset не нужен (Layer 2 — UI-only, нет DB-writes); пропустить**

(Pre-deploy verification на 5 реальных дампах уже частично покрыта unit-тестами Task 3 + integration Task 4 на 2 fixture'ах. Доп. live re-queue — после deploy, см. Task 9.)

---

## Task 7: Codex review on diff

**Files:** —

- [ ] **Step 1: Сгенерировать diff feature-ветки vs origin/main и прогнать через codex review**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
git diff origin/main...HEAD | ~/.local/bin/codex review - 2>&1 | tail -60
```

Expected: P1/P2 issues = 0. P3 (стиль/мелочи) — оценить, исправить очевидное.

Memory note `feedback_codex_sandbox_broken`: bubblewrap warning benign, используем stdin-pipe.

- [ ] **Step 2: Если P1/P2 issues есть — fix inline, повторить codex review**

```bash
# После fix:
cd /home/claude-user/autowarm-wp67-tt-modal
git add <files>
git commit -m "fix: codex review iter#N — <short description>"
git diff origin/main...HEAD | ~/.local/bin/codex review - 2>&1 | tail -40
```

Повторять до 0 P1 (memory `feedback_codex_review_specs`).

- [ ] **Step 3: Финальный suite-прогон после fix'ов**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
pytest tests/test_account_switcher_modal_dismiss.py -v 2>&1 | tail -20
```

Expected: 16 passed.

---

## Task 8: Push branch + open PR to GenGo2/delivery-contenthunter

**Files:** —

- [ ] **Step 1: Push feature branch**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
source ~/secrets/github-gengo2.env
git push -u origin worktree-wp67-tt-modal-dismiss-2026-05-18
```

Expected: ветка создана на remote, без force-push (memory `feedback_subagent_force_push_risk`).

- [ ] **Step 2: Открыть PR**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
source ~/secrets/github-gengo2.env
gh pr create --title "fix(tt-switcher): dismiss known post-switch promo-modals (WP #67 Layer 2)" --body "$(cat <<'EOF'
## Summary

WP #67 Layer 2 — закрывает residual `tt_post_switch_verify_unrecoverable`
(1–2/день после Layer 1 PR #62 от 2026-05-14).

Evidence (5 residual задач 2026-05-15..18): 4/5 — модалка «Привязать
номер телефона или эл. почту» / «Не сейчас»; 1/5 (task 7307) — после
renav вылез второй модал «Сохранить данные для входа» / «Не сейчас».

Variant A из спеки: 2 probe-site вставки в `_tt_handle_post_switch_unknown`
(pre-feed + post-renav). Cap=1 dismiss/site. Whitelist seeded 2 entries.

Spec: `docs/superpowers/specs/2026-05-18-tt-post-switch-modal-dismiss-design.md` (в rmbrmv/contenthunter)
Plan: `docs/superpowers/plans/2026-05-18-tt-post-switch-modal-dismiss-plan.md` (в rmbrmv/contenthunter)

## Changes

- `account_switcher.py`:
  - `_TT_POST_SWITCH_DISMISSIBLE_MODALS` constant (whitelist 2 entries).
  - `_tt_try_dismiss_post_switch_modal()` module helper.
  - `AccountSwitcher._try_dismiss_and_redump()` method.
  - `AccountSwitcher._tt_handle_post_switch_unknown()` — 2 probe sites.
- `tests/test_account_switcher_modal_dismiss.py`: 16 tests (10 unit + 6 integration).
- `tests/fixtures/`: 2 new XML fixtures from real failing tasks.

## Test plan

- [x] 16 new tests passing.
- [x] Full switcher suite — 0 new regressions (1 pre-existing
      `test_yt_happy_path_returns_accounts` known).
- [x] Codex review — 0 P1/P2.
- [ ] Post-deploy live smoke: re-queue 2 из 5 residual задач через
      publish_queue → ожидаем match через modal_dismiss probe.
- [ ] 24h soak: `tt_post_switch_verify_unrecoverable` 1–2/день → ~0.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL. Записать его — пригодится для Task 9 и для WP-комментария.

- [ ] **Step 3: Merge PR (squash, после CI)**

```bash
cd /home/claude-user/autowarm-wp67-tt-modal
source ~/secrets/github-gengo2.env
# Подождать CI (обычно <5 мин), потом:
gh pr merge --squash --delete-branch
```

После merge — main на GitHub обновлён. Прод-чекаут `/root/.openclaw/workspace-genri/autowarm/` НЕ обновится автоматически (auto-push hook идёт В remote, не ИЗ remote).

---

## Task 9: Deploy to prod + PM2 restart

**Files:** —

- [ ] **Step 1: Pull в prod-checkout (отдельный путь от dev-worktree!)**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git status  # должен быть clean
git log --oneline -1  # remember old HEAD для rollback
git pull --ff-only origin main
git log --oneline -3
```

Expected: ff-only прошёл, новый коммит на top (squash-merge от Task 8). Если ff-only fails — STOP, не force-merge (memory `feedback_subagent_force_push_risk`).

- [ ] **Step 2: PM2 restart + cwd check (memory `feedback_pm2_dump_path_drift`)**

```bash
sudo pm2 describe autowarm | grep -E "exec cwd|status"
sudo pm2 restart autowarm
sudo pm2 describe autowarm | grep -E "exec cwd|status"
```

Expected: `exec cwd = /root/.openclaw/workspace-genri/autowarm`, status `online`. Если cwd ≠ prod-path — `sudo pm2 delete autowarm && sudo pm2 start ecosystem.config.js` per memory.

- [ ] **Step 3: Watchdog tail — первые 60 сек после restart**

```bash
sudo pm2 logs autowarm --lines 100 --nostream 2>&1 | tail -50
# Если есть Python tracebacks / ImportError — STOP, rollback:
# cd /root/.openclaw/workspace-genri/autowarm && git reset --hard <old-HEAD-from-step-1>
```

Expected: чисто, штатный publisher loop. Если crash → rollback.

- [ ] **Step 4: Live smoke — re-queue 2 из 5 residual задач**

Кандидаты для re-queue (см. memory `reference_publish_requeue_path`):
- task 6786 (expertcontentlab) — pre-feed модал (phone/email).
- task 7307 (just_clickpay) — post-renav модал (save login).

```sql
-- ВАЖНО: re-queue через publish_queue, НЕ publish_tasks (memory)
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
UPDATE publish_queue
SET status='pending', publish_task_id=NULL, updated_at=NOW()
WHERE id IN (
  SELECT publish_queue_id FROM publish_tasks
  WHERE id IN (6786, 7307)
);
SELECT id, status, publish_task_id FROM publish_queue
WHERE id IN (
  SELECT publish_queue_id FROM publish_tasks WHERE id IN (6786, 7307)
);
SQL
```

Через 5–10 мин (dispatchPublishQueue cron) появится новый `publish_tasks` row на каждый. Следить через:

```sql
SELECT id, status, created_at,
  (SELECT count(*) FROM jsonb_array_elements(events) e
   WHERE e->>'msg' LIKE '%tt_post_switch_modal_dismiss_attempted%') AS dismiss_attempts,
  (SELECT count(*) FROM jsonb_array_elements(events) e
   WHERE e->>'msg' LIKE '%tt_post_switch_recovered_via_modal_dismiss%') AS recovered
FROM publish_tasks
WHERE platform='TikTok' AND account IN ('expertcontentlab', 'just_clickpay')
  AND created_at >= NOW() - INTERVAL '1 hour'
ORDER BY id DESC;
```

Expected: для каждой задачи `dismiss_attempts ≥ 1` И `recovered = 1` (новые события появились), `status` доходит хотя бы до publish-стадии (не fall'нулся на verify_unrecoverable).

- [ ] **Step 5: Если live smoke FAIL → rollback**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git reset --hard <OLD_HEAD_FROM_STEP_1>
sudo pm2 restart autowarm
# Report что произошло, не пытаться auto-fix in-place.
```

---

## Task 10: 24h soak + WP #67 update

**Files:** —

- [ ] **Step 1: Запланировать 24h soak-check (memory `feedback_openproject_practice` — keep WP current)**

Через ~24h после deploy прогнать:

```sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
WITH last_fail AS (
  SELECT pt.id, pt.account, pt.created_at,
    (SELECT e->>'msg' FROM jsonb_array_elements(pt.events) WITH ORDINALITY x(e,ord)
     WHERE e->>'type'='fail' ORDER BY ord DESC LIMIT 1) AS failmsg,
    (SELECT count(*) FROM jsonb_array_elements(pt.events) e
     WHERE e->>'msg' LIKE '%tt_post_switch_modal_dismiss_attempted%') AS dismiss_attempts
  FROM publish_tasks pt
  WHERE pt.platform='TikTok' AND pt.status='failed' AND pt.testbench=false
    AND pt.created_at >= NOW() - INTERVAL '24 hours'
)
SELECT
  count(*) FILTER (WHERE failmsg LIKE '%tt_post_switch_verify_unrecoverable%') AS verify_fails_24h,
  count(*) FILTER (WHERE failmsg LIKE '%tt_post_switch_verify_unrecoverable%'
                     AND dismiss_attempts = 0) AS verify_fails_no_dismiss_24h
FROM last_fail;
SQL
```

Expected: `verify_fails_24h` ≤ 1 (целевой 0); `verify_fails_no_dismiss_24h ≥ 1` сигналит что вылез новый modal-title, нужно расширить whitelist в патче.

- [ ] **Step 2: Закомментировать WP #67 (house style — `Что было не так / Что сделано / Что осталось`, memory `feedback_openproject_practice`)**

```bash
source ~/secrets/openproject.env
curl -s -u apikey:$OPENPROJECT_API_TOKEN \
  -X POST "$OPENPROJECT_URL/api/v3/work_packages/67/activities" \
  -H "Content-Type: application/json" \
  -d '{
  "comment": {
    "raw": "## Что было не так\nПосле Layer 1 остались 1–2/день падений на экранах, где после переключения вылезала промо-модалка («Привязать номер телефона или эл. почту» или «Сохранить данные для входа»), и проверка читать @-логин не могла.\n\n## Что сделано\nLayer 2 — список известных модалок-с-кнопкой-dismiss. Если verify не нашёл аккаунт, проверяем не лежит ли сверху одна из них, тапаем dismiss, перепроверяем. Покрыты обе известные модалки + случай когда модалка вылезает после renav (task 7307). PR <gh-url-from-task-8>, выкачено на прод <дата>. 16 тестов зелёные, codex review без P1.\n\n## Что осталось\n24h soak — ожидаем ~0 verify-fails. Если в логах появится новая модалка (по событию tt_post_switch_modal_dismiss_attempted с count=0 в события задачи) — расширить whitelist одной строкой и перевыкатить."
  }
}'
```

- [ ] **Step 3: Если soak показывает 0 fails — перевести WP #67 в Тестирование**

```bash
source ~/secrets/openproject.env
# 1) Получить lockVersion
LOCKV=$(curl -s -u apikey:$OPENPROJECT_API_TOKEN "$OPENPROJECT_URL/api/v3/work_packages/67" | python3 -c "import json,sys;print(json.load(sys.stdin)['lockVersion'])")
# 2) Найти id статуса "Тестирование"
TESTING_ID=$(curl -s -u apikey:$OPENPROJECT_API_TOKEN "$OPENPROJECT_URL/api/v3/statuses" | python3 -c "import json,sys;[print(s['id']) for s in json.load(sys.stdin)['_embedded']['elements'] if 'естирование' in s['name']]")
# 3) PATCH
curl -s -u apikey:$OPENPROJECT_API_TOKEN \
  -X PATCH "$OPENPROJECT_URL/api/v3/work_packages/67" \
  -H "Content-Type: application/json" \
  -d "{\"lockVersion\":$LOCKV,\"_links\":{\"status\":{\"href\":\"/api/v3/statuses/$TESTING_ID\"}}}"
```

- [ ] **Step 4: Удалить dev-worktree**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git worktree remove /home/claude-user/autowarm-wp67-tt-modal
git worktree prune
git branch -D worktree-wp67-tt-modal-dismiss-2026-05-18  # local copy
```

Expected: worktree снят, ветка удалена локально (на remote уже удалена при merge `--delete-branch`).

---

## Out of plan (NOT in this PR)

- Расширение whitelist под третий/четвёртый модал — только когда появится evidence (через `tt_post_switch_modal_dismiss_attempted=0` + новый failmsg).
- Реклассификация `_is_tt_feed_after_pick` в classifier-enum (Variant C из брейншторма).
- Generic pre-verify dismiss во всех 4 call-site `get_current_account_from_profile` (Variant B): отдельный WP при появлении evidence.
- IG/YT modals — отдельные WP по своим багам.
