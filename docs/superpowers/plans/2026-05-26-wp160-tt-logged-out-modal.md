# WP #160 — TT logged-out modal detector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Распознавать TT-модалку разлогина «Вы вышли из аккаунта» в own-profile петле верификации, морозить аккаунт (`account_blocks`, reason `manual_login_required`) и падать честным error_code `tt_logged_out_modal` вместо маскирующего `tt_profile_tab_broken`.

**Architecture:** Approach A из спеки — выделенный детектор по образцу WP #93. Общий matcher (heading в non-clickable + кнопка exact в clickable) выносится из `_tt_detect_switch_blocking_modal` в `_tt_match_modal_whitelist`; новый whitelist `_TT_LOGGED_OUT_MODALS` + детектор `_tt_detect_logged_out_modal` + handler `_maybe_handle_logged_out_modal` с вызовом в own-profile петле. Kill-switch `TT_LOGGED_OUT_MODAL_GUARD`.

**Tech Stack:** Python 3, pytest, prod autowarm (`/root/.openclaw/workspace-genri/autowarm`), `account_switcher.py` + `publisher_kernel.py`. Спека: `docs/superpowers/specs/2026-05-26-wp160-tt-logged-out-modal-design.md`.

**Где работаем:** код — autowarm-репо (remote `GenGo2/delivery-contenthunter`); доки (этот план + evidence) — `rmbrmv/contenthunter`. Все код-задачи выполняются в git worktree autowarm-репо (см. Task 0). Тесты запускаются из корня worktree.

---

### Task 0: Изолированный worktree для autowarm-кода

**Files:** — (git-операция)

REQUIRED SUB-SKILL: superpowers:using-git-worktrees.

- [ ] **Step 1: Создать worktree off main**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git worktree add -b wp160-tt-logged-out-modal /tmp/autowarm-wp160 main
```

- [ ] **Step 2: Проверить базу**

```bash
cd /tmp/autowarm-wp160
git branch --show-current   # ожидаем: wp160-tt-logged-out-modal
pytest tests/test_tt_switch_blocking_modal.py -q   # baseline зелёный
```
Expected: ветка `wp160-tt-logged-out-modal`, существующий WP #93 сьют PASS.

**Все последующие команды Task 1-5 выполняются из `/tmp/autowarm-wp160`.**

---

### Task 1: Вынести общий matcher `_tt_match_modal_whitelist` (рефактор без смены поведения)

**Files:**
- Modify: `account_switcher.py` (функция `_tt_detect_switch_blocking_modal`, ~471-509)

Существующий WP #93 сьют (`tests/test_tt_switch_blocking_modal.py`) — это и есть регресс-тест: он проверяет, что `_tt_detect_switch_blocking_modal` матчит свою фикстуру. Рефактор не должен его сломать.

- [ ] **Step 1: Прогнать WP #93 сьют (baseline)**

Run: `pytest tests/test_tt_switch_blocking_modal.py -v`
Expected: PASS (все тесты зелёные до рефактора).

- [ ] **Step 2: Вынести тело матча в общий helper**

Заменить тело функции `_tt_detect_switch_blocking_modal` (account_switcher.py, начинается со строки `def _tt_detect_switch_blocking_modal(`) на новый общий helper + тонкую обёртку. Итоговый блок:

```python
def _tt_match_modal_whitelist(
    xml: str,
    whitelist: tuple[tuple[str, str, str], ...],
) -> Optional[tuple[str, str, str]]:
    """Generic matcher TT-модалок вида (heading_substr, button, reason).

    Возвращает первую запись whitelist'а, для которой в одном дампе сосуществуют:
    NON-clickable элемент, чей label содержит heading_substr (heading), И clickable
    элемент с label.strip().lower() == button (кнопка, точное равенство). Иначе None.

    NON-clickable требование для heading защищает от ловушки, где heading_substr
    совпал бы с label КНОПКИ. Defensive: parse_ui_dump уже robust к ParseError,
    любое иное исключение → None (продолжаем на старый verify-флоу).
    """
    if not xml:
        return None
    try:
        elements = parse_ui_dump(xml)
    except Exception:
        return None
    if not elements:
        return None
    for heading, button, reason in whitelist:
        heading_lc = heading.lower()
        button_lc = button.lower()
        has_heading = any(
            heading_lc in el.label.lower() and not el.clickable
            for el in elements
        )
        has_button = any(
            el.clickable and el.label.strip().lower() == button_lc
            for el in elements
        )
        if has_heading and has_button:
            return (heading, button, reason)
    return None


def _tt_detect_switch_blocking_modal(
    xml: str,
) -> Optional[tuple[str, str, str]]:
    """[WP #93] Блокирующая pre-switch модалка TT. Делегирует
    _tt_match_modal_whitelist с _TT_SWITCH_BLOCKING_MODALS — поведение
    неизменно (см. оригинальную docstring/match-правило в _tt_match_modal_whitelist).
    """
    return _tt_match_modal_whitelist(xml, _TT_SWITCH_BLOCKING_MODALS)
```

- [ ] **Step 3: Прогнать WP #93 сьют (после рефактора)**

Run: `pytest tests/test_tt_switch_blocking_modal.py -v`
Expected: PASS (поведение byte-identical).

- [ ] **Step 4: Commit**

```bash
git add account_switcher.py
git commit -m "refactor(wp160): вынести общий matcher TT-модалок _tt_match_modal_whitelist

Без смены поведения: _tt_detect_switch_blocking_modal делегирует общему
helper'у. Готовит почву под детектор модалки разлогина (WP #160).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Фикстура + whitelist `_TT_LOGGED_OUT_MODALS` + детектор `_tt_detect_logged_out_modal`

**Files:**
- Create: `tests/fixtures/tt_logged_out_modal_9652.xml`
- Modify: `tests/fixtures/PROVENANCE.md`
- Create: `tests/test_tt_logged_out_modal.py`
- Modify: `account_switcher.py` (добавить whitelist + детектор после `_tt_detect_switch_blocking_modal`)

- [ ] **Step 1: Скачать прод-дамп задачи 9652 в фикстуру**

```bash
curl -s -o tests/fixtures/tt_logged_out_modal_9652.xml \
  "https://save.gengo.io/autowarm/ui_dumps/tiktok/task9652_switch_9652_tt_2_not_own_retap1_1779705001.xml"
grep -c 'Вы вышли из аккаунта. Попробуйте войти снова.' tests/fixtures/tt_logged_out_modal_9652.xml
grep -c 'text="OK"' tests/fixtures/tt_logged_out_modal_9652.xml
```
Expected: оба grep → `1`. (Узлы: title «Статус аккаунта» + body «Вы вышли из аккаунта…» non-clickable TextView, кнопка «OK» clickable Button `android:id/button1`.)

- [ ] **Step 2: Записать provenance**

Добавить в конец `tests/fixtures/PROVENANCE.md`:

```markdown

## tt_logged_out_modal_9652.xml (WP #160)
Задача 9652 (аккаунт LexisVoice_Up, устройство RFGYB180RZV, 25.05.2026), dump
`tt_2_not_own_retap1`. Модалка разлогина «Статус аккаунта» / «Вы вышли из
аккаунта. Попробуйте войти снова.» + кнопка «OK». Источник: save.gengo.io.
```

- [ ] **Step 3: Написать падающие тесты детектора**

Создать `tests/test_tt_logged_out_modal.py`:

```python
"""Unit tests для WP #160 — TT logged-out modal detector + handler.

См. spec docs/superpowers/specs/2026-05-26-wp160-tt-logged-out-modal-design.md

Запуск:
    cd /root/.openclaw/workspace-genri/autowarm   # или worktree
    pytest tests/test_tt_logged_out_modal.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import account_switcher as _asw  # noqa: E402
from account_switcher import (  # noqa: E402
    AccountSwitcher,
    UI_CONSTANTS,
    _TT_LOGGED_OUT_MODALS,
    _tt_detect_logged_out_modal,
    _tt_detect_switch_blocking_modal,
    _tt_logged_out_modal_guard_enabled,
)

FIXTURES = ROOT / 'tests' / 'fixtures'


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


# ─── детектор — pure unit ───────────────────────────────────────────────

def test_whitelist_seeded():
    assert ('Вы вышли из аккаунта', 'OK', 'manual_login_required') in _TT_LOGGED_OUT_MODALS


def test_detect_matches_prod_dump_9652():
    xml = _read_fixture('tt_logged_out_modal_9652.xml')
    assert _tt_detect_logged_out_modal(xml) == (
        'Вы вышли из аккаунта', 'OK', 'manual_login_required'
    )


def test_detect_none_on_own_profile():
    xml = _read_fixture('tt_profile_screen.xml')
    assert _tt_detect_logged_out_modal(xml) is None


def test_detect_none_on_feed():
    xml = _read_fixture('tt_feed_no_sheet.xml')
    assert _tt_detect_logged_out_modal(xml) is None


def test_detect_none_on_wp93_phone_email_modal():
    """Кросс-матч: WP #93 phone/email модалка не должна срабатывать logged-out
    whitelist'ом (другой heading + кнопка «Не сейчас», не «OK»)."""
    xml = _read_fixture('tt_switch_blocked_phone_email_7372.xml')
    assert _tt_detect_logged_out_modal(xml) is None


def test_detect_none_when_heading_without_ok_button():
    """Heading есть, но кнопки «OK» нет → None (требование точной кнопки).
    bounds обязательны: parse_ui_dump отбрасывает узлы без валидного bounds."""
    xml = (
        '<hierarchy rotation="0">'
        '<node text="Статус аккаунта" clickable="false" bounds="[95,975][985,1045]"/>'
        '<node text="Вы вышли из аккаунта. Попробуйте войти снова." '
        'clickable="false" bounds="[27,1068][1053,1174]"/>'
        '<node text="Отмена" clickable="true" bounds="[839,1214][1019,1366]"/>'
        '</hierarchy>'
    )
    assert _tt_detect_logged_out_modal(xml) is None


def test_wp93_detector_unchanged_after_refactor():
    """Регресс delegation (Task 1): WP #93 детектор матчит свою фикстуру."""
    xml = _read_fixture('tt_switch_blocked_phone_email_7372.xml')
    assert _tt_detect_switch_blocking_modal(xml) == (
        'Необходимо обновить аккаунт', 'Не сейчас', 'phone_or_email_link_required'
    )
```

- [ ] **Step 4: Прогнать — убедиться, что падает**

Run: `pytest tests/test_tt_logged_out_modal.py -v`
Expected: FAIL на import (`cannot import name '_TT_LOGGED_OUT_MODALS'` / `_tt_detect_logged_out_modal` / `_tt_logged_out_modal_guard_enabled`).

- [ ] **Step 5: Добавить whitelist + детектор**

В `account_switcher.py` сразу после функции `_tt_detect_switch_blocking_modal` (из Task 1) добавить:

```python
# ─────────────────────────────────────────────────────────────────────────────
# WP #160 2026-05-26 — TT logged-out modal detector.
# Модалка «Статус аккаунта» / body «Вы вышли из аккаунта. Попробуйте войти снова.»
# + кнопка «OK» (acknowledge). НЕ полноэкранный логин — _tt_is_logged_out её не
# ловит (нет «Войти»/«Создать аккаунт»). Sticky поверх профиля в own-profile петле
# → 4 детектора False → ложный tt_profile_tab_broken. Match-механизм как WP #93
# (heading в non-clickable + кнопка exact в clickable). Отдельный whitelist+reason:
# семантика «нужен ручной вход» (не phone_or_email_link_required).
# ─────────────────────────────────────────────────────────────────────────────
_TT_LOGGED_OUT_MODALS: tuple[tuple[str, str, str], ...] = (
    ('Вы вышли из аккаунта', 'OK', 'manual_login_required'),
)


def _tt_detect_logged_out_modal(
    xml: str,
) -> Optional[tuple[str, str, str]]:
    """[WP #160] Модалка разлогина TT. Делегирует _tt_match_modal_whitelist
    с _TT_LOGGED_OUT_MODALS. Возврат (heading, button, reason) либо None."""
    return _tt_match_modal_whitelist(xml, _TT_LOGGED_OUT_MODALS)
```

Также добавить kill-switch helper рядом с `_tt_stale_ui_guard_enabled` (поиск по `def _tt_stale_ui_guard_enabled`):

```python
def _tt_logged_out_modal_guard_enabled() -> bool:
    """[WP #160] Kill-switch. TT_LOGGED_OUT_MODAL_GUARD=0 → детект модалки
    разлогина отключён, флоу идентичен pre-fix. Default ON."""
    return os.environ.get('TT_LOGGED_OUT_MODAL_GUARD', '1') != '0'
```

- [ ] **Step 6: Прогнать детектор-тесты**

Run: `pytest tests/test_tt_logged_out_modal.py -v`
Expected: PASS (handler-тесты ещё не добавлены — в файле пока только детектор).

- [ ] **Step 7: Commit**

```bash
git add account_switcher.py tests/test_tt_logged_out_modal.py \
        tests/fixtures/tt_logged_out_modal_9652.xml tests/fixtures/PROVENANCE.md
git commit -m "feat(wp160): детектор модалки разлогина TT «Вы вышли из аккаунта»

Whitelist _TT_LOGGED_OUT_MODALS + _tt_detect_logged_out_modal (делегирует
общему matcher'у) + kill-switch _tt_logged_out_modal_guard_enabled. Фикстура
из прод-дампа задачи 9652. Unit: match/no-false-positive/no-cross-match/no-OK.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Handler `_maybe_handle_logged_out_modal`

**Files:**
- Modify: `account_switcher.py` (добавить метод рядом с `_maybe_handle_switch_blocking_modal`)
- Modify: `tests/test_tt_logged_out_modal.py` (добавить handler-тесты)

- [ ] **Step 1: Написать падающие тесты handler'а**

Дописать в конец `tests/test_tt_logged_out_modal.py`:

```python
# ─── handler — unit ─────────────────────────────────────────────────────

def _make_switcher_for_handler():
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.task_id = 9652
    log_calls: list[dict] = []

    def _capture_log(event_type, message, meta=None):
        log_calls.append({'event_type': event_type, 'message': message, 'meta': meta or {}})

    publisher.log_event.side_effect = _capture_log
    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    return sw, log_calls


def _has_category(log_calls, category):
    return any(c['meta'].get('category') == category for c in log_calls)


def test_kill_switch_default_on(monkeypatch):
    monkeypatch.delenv('TT_LOGGED_OUT_MODAL_GUARD', raising=False)
    assert _tt_logged_out_modal_guard_enabled() is True


def test_kill_switch_off(monkeypatch):
    monkeypatch.setenv('TT_LOGGED_OUT_MODAL_GUARD', '0')
    assert _tt_logged_out_modal_guard_enabled() is False


def test_handler_returns_none_when_no_modal():
    sw, _ = _make_switcher_for_handler()
    xml = _read_fixture('tt_feed_no_sheet.xml')
    assert sw._maybe_handle_logged_out_modal(xml, 'someacct', 0) is None


def test_handler_returns_none_when_kill_switch_off(monkeypatch):
    monkeypatch.setenv('TT_LOGGED_OUT_MODAL_GUARD', '0')
    sw, _ = _make_switcher_for_handler()
    xml = _read_fixture('tt_logged_out_modal_9652.xml')
    assert sw._maybe_handle_logged_out_modal(xml, 'someacct', 0) is None


def test_handler_freezes_and_fails_on_match(monkeypatch):
    import account_blocks
    import notifier
    set_block = MagicMock(return_value=42)
    notify = MagicMock(return_value=True)
    monkeypatch.setattr(account_blocks, 'set_block_by_username', set_block)
    monkeypatch.setattr(notifier, 'notify_escalation', notify)

    sw, log_calls = _make_switcher_for_handler()
    sentinel = object()
    sw._fail = MagicMock(return_value=sentinel)
    xml = _read_fixture('tt_logged_out_modal_9652.xml')

    result = sw._maybe_handle_logged_out_modal(xml, 'someacct', 1)

    assert result is sentinel
    sw._fail.assert_called_once()
    assert sw._fail.call_args.kwargs.get('step') == 'tt_2_logged_out_modal'
    # заморозка с правильным reason
    assert set_block.call_args.args[0] == 'someacct'
    assert set_block.call_args.args[1] == 'tt'
    assert set_block.call_args.kwargs.get('reason') == 'manual_login_required'
    # эскалация + событие
    notify.assert_called_once()
    assert _has_category(log_calls, 'tt_logged_out_modal')
    sw._save_dump.assert_called_once()
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `pytest tests/test_tt_logged_out_modal.py -k handler -v`
Expected: FAIL (`AttributeError: ... '_maybe_handle_logged_out_modal'`).

- [ ] **Step 3: Реализовать handler**

В `account_switcher.py` сразу после метода `_maybe_handle_switch_blocking_modal` (поиск по `def _maybe_handle_switch_blocking_modal`, метод заканчивается `return self._fail(... step='tt_switch_blocked')`) добавить:

```python
    def _maybe_handle_logged_out_modal(self, xml: str, target: str, retap: int):
        """[WP #160 2026-05-26] Детект модалки разлогина TT «Вы вышли из
        аккаунта» в own-profile петле верификации.

        Вызывается в цикле own-profile проверки после _tt_is_logged_out
        (полный экран) и перед _tt_is_reauth_prompt. Если модалка сматчилась:
          1. log_event category='tt_logged_out_modal',
          2. best-effort account_blocks.set_block_by_username(reason=
             'manual_login_required'),
          3. best-effort notifier.notify_escalation,
          4. _save_dump,
          5. возвращает self._fail(step='tt_2_logged_out_modal') — caller
             должен сделать return этим значением, прервав цикл.

        Если модалка не сматчилась или kill-switch off — None (цикл продолжает).
        Кнопку «OK» НЕ тапаем: аккаунт замораживается, лишний tap = лишний риск.
        Detector обёрнут в try/except defensive (как WP #93).
        """
        if not _tt_logged_out_modal_guard_enabled():
            return None
        try:
            matched = _tt_detect_logged_out_modal(xml)
        except Exception as de:
            log.warning(f'switcher.tt.detect_logged_out_modal_failed: {de}')
            matched = None
        if matched is None:
            return None

        heading, button, reason = matched
        log.error(
            f'switcher.tt.logged_out_modal target={target!r} reason={reason!r} '
            f'heading={heading!r} retap={retap + 1}'
        )
        self.p.log_event(
            'error',
            f'TT logged-out modal: {heading!r}',
            meta={
                'category': 'tt_logged_out_modal',
                'reason': reason,
                'heading_substr': heading,
                'button_substr': button,
                'target': target,
                'retap': retap + 1,
                'step': 'tt_2_logged_out_modal',
            },
        )

        acc_id = None
        try:
            import account_blocks
            acc_id = account_blocks.set_block_by_username(
                target, 'tt', reason=reason,
                publish_task_id=self.p.task_id,
                step='tt_2_logged_out_modal',
                last_seen_screen='tt_2_profile_tab',
                heading_substr=heading,
            )
        except Exception as be:
            log.warning(f'switcher.tt.set_block_failed: {be}')

        try:
            import notifier
            notifier.notify_escalation(
                f'tt_logged_out_modal_{reason}',
                f'TikTok разлогинен — нужен ручной вход для account={target}',
                f'task_id={self.p.task_id} factory_id={acc_id} '
                f'step=tt_2_logged_out_modal',
            )
        except Exception as ne:
            log.warning(f'switcher.tt.notify_failed: {ne}')

        self._save_dump(f'tt_2_logged_out_modal_retap{retap + 1}', xml)
        return self._fail(
            f'TikTok разлогинен (модалка «Вы вышли из аккаунта») — '
            f'нужен ручной вход для @{target}',
            step='tt_2_logged_out_modal',
        )
```

- [ ] **Step 4: Прогнать handler-тесты**

Run: `pytest tests/test_tt_logged_out_modal.py -v`
Expected: PASS (все детектор + handler тесты).

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_tt_logged_out_modal.py
git commit -m "feat(wp160): handler _maybe_handle_logged_out_modal + заморозка аккаунта

Match → event tt_logged_out_modal + account_blocks(manual_login_required) +
escalation + fail-fast step=tt_2_logged_out_modal. Кнопку OK не тапаем.
best-effort isolation на account_blocks/notifier.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire детект в own-profile петлю + error_code map

**Files:**
- Modify: `account_switcher.py` (вставить вызов в own-profile петле, после блока `_tt_is_logged_out`)
- Modify: `publisher_kernel.py` (`_SWITCHER_STEP_TO_CATEGORY`, после строки `'tt_switch_blocked': 'tt_switch_blocked',`)
- Modify: `tests/test_tt_logged_out_modal.py` (интеграционный тест петли + тест map)

- [ ] **Step 1: Написать падающий интеграционный тест + тест map**

Дописать в конец `tests/test_tt_logged_out_modal.py`:

```python
# ─── интеграция: own-profile петля + error_code map ─────────────────────

TOP_TIKTOK = ('  topResumedActivity=ActivityRecord{abc u0 '
              'com.zhiliaoapp.musically/.main.MainActivity}')


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(_asw.time, 'sleep', lambda *_a, **_kw: None)


def _arm_loop_with_modal(sw, modal_xml):
    """Довести _switch_tiktok до own-profile петли с модалкой разлогина в
    dump_ui (зеркало _arm_stale_loop из test_account_switcher_tt_stale_ui.py).
    Модалка — реальный дамп TT → _tt_probe_looks_stale False → stale-guard не
    мешает, наш детект срабатывает на retap=0."""
    sw._ensure_app_foregrounded = MagicMock(return_value=True)
    sw._ensure_foreground = MagicMock(return_value=True)
    sw._go_to_profile_tab = MagicMock()
    sw._tt_smart_tap_profile = MagicMock(return_value=True)
    sw._tt_dismiss_security_prompt = MagicMock(return_value=False)
    sw._tt_dismiss_profile_promo_dialog = MagicMock(return_value=False)
    sw._tt_guard_switcher_foreground = MagicMock(return_value='ok')
    sw.p.dump_ui = MagicMock(return_value=modal_xml)
    sw.p.adb = MagicMock(return_value=TOP_TIKTOK)


def test_loop_fails_fast_and_freezes_on_modal(monkeypatch):
    import account_blocks
    import notifier
    set_block = MagicMock(return_value=42)
    monkeypatch.setattr(account_blocks, 'set_block_by_username', set_block)
    monkeypatch.setattr(notifier, 'notify_escalation', MagicMock(return_value=True))

    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.task_id = 9652
    publisher.dump_ui = MagicMock(return_value='')
    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    sw._maybe_screenshot = MagicMock()
    sw._single_account_mode = False

    modal_xml = _read_fixture('tt_logged_out_modal_9652.xml')
    _arm_loop_with_modal(sw, modal_xml)

    result = sw._switch_tiktok('someacct', UI_CONSTANTS['TikTok'])

    assert result.success is False
    assert result.final_step == 'tt_2_logged_out_modal'
    set_block.assert_called_once()
    assert set_block.call_args.kwargs.get('reason') == 'manual_login_required'


def test_step_mapped_to_error_code():
    import publisher_kernel
    assert (publisher_kernel._SWITCHER_STEP_TO_CATEGORY['tt_2_logged_out_modal']
            == 'tt_logged_out_modal')
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `pytest tests/test_tt_logged_out_modal.py -k "loop or step_mapped" -v`
Expected: FAIL (петля не вызывает handler → `final_step != 'tt_2_logged_out_modal'`; map не содержит ключ → KeyError).

- [ ] **Step 3: Вставить вызов в own-profile петлю**

В `account_switcher.py` найти блок `_tt_is_logged_out` в own-profile петле (`if self._tt_is_logged_out(xml_probe):` … заканчивается `step='tt_2_logged_out',` + `)`). Сразу ПОСЛЕ закрывающей скобки этого блока и ПЕРЕД комментарием `# [T5 2026-04-19] Reauth-prompt check:` вставить:

```python
            # [WP #160 2026-05-26] Модалка разлогина «Вы вышли из аккаунта» —
            # sticky поверх профиля, НЕ полноэкранный логин (маркеры не
            # пересекаются с _tt_is_logged_out). Детект → заморозка аккаунта +
            # честный tt_2_logged_out_modal + fail-fast (не жжём retap'ы +
            # bottomsheet-recovery). Реальный дамп TT → stale-UI guard ниже не
            # мешает. Порядок относительно logged_out не важен (маркеры разные).
            _lo = self._maybe_handle_logged_out_modal(xml_probe, target, retap)
            if _lo is not None:
                return _lo
```

- [ ] **Step 4: Добавить строку в error_code map**

В `publisher_kernel.py` после строки `'tt_switch_blocked': 'tt_switch_blocked',  # WP #93 2026-05-18` добавить:

```python
    'tt_2_logged_out_modal': 'tt_logged_out_modal',  # WP #160 2026-05-26
```

- [ ] **Step 5: Прогнать тесты**

Run: `pytest tests/test_tt_logged_out_modal.py -v`
Expected: PASS (все тесты, включая интеграцию и map).

- [ ] **Step 6: Commit**

```bash
git add account_switcher.py publisher_kernel.py tests/test_tt_logged_out_modal.py
git commit -m "feat(wp160): wire детект модалки разлогина в own-profile петлю + error_code

Вызов _maybe_handle_logged_out_modal после _tt_is_logged_out (fail-fast на
retap=0). Маппинг tt_2_logged_out_modal → tt_logged_out_modal в
_SWITCHER_STEP_TO_CATEGORY. Интеграционный тест петли + тест map.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Регресс всего switcher-сьюта + codex review

**Files:** — (проверка)

- [ ] **Step 1: Полный switcher-регресс**

Run:
```bash
pytest tests/test_account_switcher.py tests/test_account_switcher_tt.py \
       tests/test_account_switcher_tt_stale_ui.py tests/test_tt_switch_blocking_modal.py \
       tests/test_canonical_error_codes.py tests/test_error_code_mapper.py \
       tests/test_tt_logged_out_modal.py -q
```
Expected: всё PASS, 0 failed. (Если падает не наш тест — зафиксировать, сверить с baseline на main: pre-existing fail ≠ регрессия.)

- [ ] **Step 2: Codex review дифа**

Run:
```bash
git diff main...HEAD | ~/.local/bin/codex review -
```
Прогнать раундами до 0 P1. Применить фидбэк (если есть) отдельными fix-коммитами, перепрогнать Step 1.

---

### Task 6: Деплой + evidence + OpenProject  ⚠️ CHECKPOINT

> Деплой на прод — outward-facing, делать аккуратно. NO force-push на main (см. инцидент с subagent force-push). Перед мержем убедиться, что прод-чекаут `/root/.openclaw/workspace-genri/autowarm` на ветке `main`.

- [ ] **Step 1: Слить ветку в прод autowarm main**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git branch --show-current   # ДОЛЖНО быть main; если нет — НЕ продолжать
git merge --no-ff wp160-tt-logged-out-modal -m "Merge wp160: детект модалки разлогина TT «Вы вышли из аккаунта»"
git push origin main        # БЕЗ --force; auto-push hook продублирует на GenGo2
```
Python спавнится свежим per-task → **PM2 restart не нужен**. (Если push отвергнут — `git pull --rebase origin main`, перепрогнать тесты, push заново.)

- [ ] **Step 2: Evidence-doc в docs-репо**

Создать в docs-worktree (`rmbrmv/contenthunter`, ветка `wp160-tt-logged-out-modal`) `docs/evidence/2026-05-26-wp160-tt-logged-out-modal-shipped.md`: что чинили (модалка 9652), что сделали (детект+заморозка+honest code), тесты (N зелёных + регресс), kill-switch, остаток (24ч verify). Закоммитить.

- [ ] **Step 3: OpenProject #160 → «Тестирование»**

Комментарий в house-style (Что было не так → Что сделано → Что осталось, plain language, без жаргона/хешей/путей), статус → id 9 (см. reference-openproject-access для API). Заметка: проверить актуальный lockVersion перед PATCH.

- [ ] **Step 4: Verify ~24ч (≈27.05)**

Через сутки: появилась категория `tt_logged_out_modal`; аккаунты получают `tt_block.reason='manual_login_required'`; `tt_profile_tab_broken` не растёт. По результату → WP #160 «Готово», откат-флаг `TT_LOGGED_OUT_MODAL_GUARD=0` задокументирован.

---

## Self-Review (выполнено при написании плана)

**Spec coverage:** детект (T2) ✓, общий matcher (T1) ✓, handler+freeze+escalation (T3) ✓, точка вставки в own-profile петлю (T4) ✓, телеметрия event+map (T3/T4) ✓, kill-switch (T2) ✓, тесты-фикстура+unit+cross-match+no-OK+интеграция (T2-T4) ✓, регресс (T5) ✓, деплой/evidence/OpenProject (T6) ✓. Scope строго по #160 (полный логин не трогаем) — соблюдён.

**Placeholder scan:** плейсхолдеров нет; все код-блоки и команды конкретны.

**Type/name consistency:** `_tt_match_modal_whitelist` / `_tt_detect_logged_out_modal` / `_tt_logged_out_modal_guard_enabled` / `_maybe_handle_logged_out_modal` / `_TT_LOGGED_OUT_MODALS`, step `tt_2_logged_out_modal`, error_code/category `tt_logged_out_modal`, reason `manual_login_required`, env `TT_LOGGED_OUT_MODAL_GUARD` — согласованы во всех задачах и со спекой.
