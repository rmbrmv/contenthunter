# WP #93 — TT Switch Blocking Modal Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Распознавать блокирующую TT-модалку «Необходимо обновить аккаунт» сразу после tap по picker-row, эмитить `error_code='tt_switch_blocked'`, записывать `factory_reg_accounts.tt_block` и удалить ошибочную whitelist-запись из Layer 2 — bundle в один PR.

**Architecture:** Module-level detector helper в `account_switcher.py` вызывается defensive try/except в `_switch_tiktok` после `_save_dump`/`_maybe_screenshot` и до `_post_switch_verify_handle`. На матч — log_event + `set_block_by_username` + `notify_escalation` + `_fail(step='tt_switch_blocked')`. Step→error_code мап в `publisher_kernel.py` даёт финальный `error_code`. Пере-используем IG human_check паттерн (publisher_base.py:4215).

**Tech Stack:** Python 3, pytest, psycopg2, существующие модули `account_switcher.py` / `account_blocks.py` / `notifier.py` / `publisher_kernel.py` в `GenGo2/delivery-contenthunter` (prod checkout `/root/.openclaw/workspace-genri/autowarm/`).

**Spec:** `docs/superpowers/specs/2026-05-18-wp93-tt-switch-blocking-modal-design.md` (rmbrmv/contenthunter).

**Repo / workspace:**
- Spec и plan живут в `/home/claude-user/contenthunter` (rmbrmv/contenthunter).
- Код и тесты живут в `/root/.openclaw/workspace-genri/autowarm/` (GenGo2/delivery-contenthunter).
- ⚠ **Auto-push hook**: `.git/hooks/post-commit` (см. файл) пушит **любую current branch** на GenGo2/delivery-contenthunter сразу после каждого commit (`git push origin "$BRANCH" -q`). Это безопасно для feature-branch — branch появится на remote, но merge в main всё равно идёт ТОЛЬКО через PR. Главное правило: **никаких commits в `main` autowarm-репа**. Step P3 (preflight) явно проверяет что мы на feature branch перед любой работой; каждый Task контролирует currentbranch перед commit.

---

## Files

**Create (autowarm = `/root/.openclaw/workspace-genri/autowarm/`):**
- `tests/fixtures/tt_switch_blocked_phone_email_7372.xml` — копия prod-dump task 7372 `tt_4_target_profile` (модалка «Необходимо обновить аккаунт»).
- `tests/fixtures/tt_feed_after_modal_dismiss_7372.xml` — копия prod-dump task 7372 `tt_4_target_profile_after_modal_dismiss` (feed после «Не сейчас»).
- `tests/fixtures/tt_profile_screen_7372.xml` — копия prod-dump task 7372 `tt_2_profile_screen` (own profile до switch).
- `tests/test_tt_switch_blocking_modal.py` — unit + integration тесты (~250 строк).

**Modify (autowarm):**
- `account_switcher.py` — добавить `_TT_SWITCH_BLOCKING_MODALS` константу + `_tt_detect_switch_blocking_modal` хелпер, удалить regression-строку из `_TT_POST_SWITCH_DISMISSIBLE_MODALS:225`, вставить defensive detector call в `_switch_tiktok` после строк 2560-2561.
- `publisher_kernel.py` — добавить `'tt_switch_blocked': 'tt_switch_blocked'` в step→error_code map.
- `tests/fixtures/PROVENANCE.md` — задокументировать 3 новых fixture.

**Modify (rmbrmv/contenthunter — отдельный коммит на ветке `feat/wp93-tt-picker-wrong-row`, уже создана):**
- Этот план файл (`docs/superpowers/plans/2026-05-18-wp93-tt-switch-blocking-modal-plan.md`).

---

## Pre-flight (один раз перед началом)

- [ ] **Step P1: Проверить статус autowarm-репа**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git status --short
git branch --show-current
```

Expected: чистое дерево (или только untracked файлы вне нашего scope), branch = `main`.

- [ ] **Step P2: Fetch + создать feature branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git fetch origin main
git checkout -b feat/wp93-tt-switch-blocking-modal origin/main
git branch --show-current
```

Expected: `feat/wp93-tt-switch-blocking-modal`.

- [ ] **Step P3: Smoke pytest baseline (никаких регрессий не должно появиться позже)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_account_switcher_modal_dismiss.py -q 2>&1 | tail -10
```

Expected: WP #67 тесты зелёные (16 passed). Если красные сразу — STOP, чинить baseline до старта работы.

- [ ] **Step P4: Подтвердить current branch перед каждым commit**

Каждый Task с `git commit` должен начинаться с проверки:

```bash
cd /root/.openclaw/workspace-genri/autowarm/
test "$(git branch --show-current)" = "feat/wp93-tt-switch-blocking-modal" || \
  { echo "STOP: не на feature branch — выходим"; exit 1; }
```

Если check fail'ит — НЕ commit'ить, разобраться (особенно после возможного `git stash`/`git checkout` в параллельной сессии).

---

## Tasks

### Task 1: Add fixtures + provenance

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_switch_blocked_phone_email_7372.xml`
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_feed_after_modal_dismiss_7372.xml`
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_profile_screen_7372.xml`
- Modify: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/PROVENANCE.md`

- [ ] **Step 1.1: Скачать 3 fixture с S3**

```bash
cd /root/.openclaw/workspace-genri/autowarm/tests/fixtures
curl -sSL -o tt_switch_blocked_phone_email_7372.xml \
  "https://save.gengo.io/autowarm/ui_dumps/tiktok/task7372_switch_7372_tt_4_target_profile_1779114421.xml"
curl -sSL -o tt_feed_after_modal_dismiss_7372.xml \
  "https://save.gengo.io/autowarm/ui_dumps/tiktok/task7372_switch_7372_tt_4_target_profile_after_modal_dismiss_1779114431.xml"
curl -sSL -o tt_profile_screen_7372.xml \
  "https://save.gengo.io/autowarm/ui_dumps/tiktok/task7372_switch_7372_tt_2_profile_screen_1779114389.xml"
ls -l tt_switch_blocked_phone_email_7372.xml tt_feed_after_modal_dismiss_7372.xml tt_profile_screen_7372.xml
```

Expected: 3 файла на диске, размеры ~7K / ~20K / ~56K соответственно.

- [ ] **Step 1.2: Smoke-проверить ключевой fixture**

```bash
cd /root/.openclaw/workspace-genri/autowarm/tests/fixtures
grep -c "Необходимо обновить аккаунт" tt_switch_blocked_phone_email_7372.xml
grep -c "Не сейчас" tt_switch_blocked_phone_email_7372.xml
```

Expected: оба grep возвращают `1` (хотя бы одно вхождение каждого).

- [ ] **Step 1.3: Добавить запись в PROVENANCE.md**

Append в конец `tests/fixtures/PROVENANCE.md`:

```markdown

## tt_switch_blocked_phone_email_7372.xml

**Source:** S3 archive — task 7372, step `tt_4_target_profile`, dump filename
`task7372_switch_7372_tt_4_target_profile_1779114421.xml`

**URL:** `https://save.gengo.io/autowarm/ui_dumps/tiktok/task7372_switch_7372_tt_4_target_profile_1779114421.xml`

**Capture context:** WP #93 evidence (2026-05-18). Account `expertcontentlab` на raspberry 5. После tap по picker-row TT показал блокирующую модалку «Необходимо обновить аккаунт / Привязать номер телефона или эл. почту / Не сейчас». Используется как primary positive-fixture для `_tt_detect_switch_blocking_modal`.

## tt_feed_after_modal_dismiss_7372.xml

**Source:** S3 archive — task 7372, step `tt_4_target_profile_after_modal_dismiss`, dump filename
`task7372_switch_7372_tt_4_target_profile_after_modal_dismiss_1779114431.xml`

**URL:** `https://save.gengo.io/autowarm/ui_dumps/tiktok/task7372_switch_7372_tt_4_target_profile_after_modal_dismiss_1779114431.xml`

**Capture context:** WP #93. После того как Layer 2 ошибочно нажал «Не сейчас», TT отменил переключение и выкинул на feed (sidebar `Профиль ᵂᴴᴵᵀᴱ ＢＩＴＡ`). Negative-fixture для `_tt_detect_switch_blocking_modal` — не должна матчиться.

## tt_profile_screen_7372.xml

**Source:** S3 archive — task 7372, step `tt_2_profile_screen`, dump filename
`task7372_switch_7372_tt_2_profile_screen_1779114389.xml`

**URL:** `https://save.gengo.io/autowarm/ui_dumps/tiktok/task7372_switch_7372_tt_2_profile_screen_1779114389.xml`

**Capture context:** WP #93. Own-profile дамп ДО открытия picker (active `@serafima_liliyins`). Negative-fixture для `_tt_detect_switch_blocking_modal` — обычный profile-screen не должен матчиться.
```

- [ ] **Step 1.4: Commit fixtures**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add tests/fixtures/tt_switch_blocked_phone_email_7372.xml \
        tests/fixtures/tt_feed_after_modal_dismiss_7372.xml \
        tests/fixtures/tt_profile_screen_7372.xml \
        tests/fixtures/PROVENANCE.md
git commit -m "test(tt): WP #93 fixtures — switch-blocked modal + feed/profile negatives"
```

Expected: 1 commit, 4 files changed.

---

### Task 2: Failing unit test для базовой detection (TDD red)

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/test_tt_switch_blocking_modal.py`

- [ ] **Step 2.1: Создать тест-файл с одним failing-тестом**

Write to `tests/test_tt_switch_blocking_modal.py`:

```python
"""Unit + integration tests для WP #93 — TT switch blocking modal detector.

См. design spec docs/superpowers/specs/2026-05-18-wp93-tt-switch-blocking-modal-design.md

Запуск:
    cd /root/.openclaw/workspace-genri/autowarm
    pytest tests/test_tt_switch_blocking_modal.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from account_switcher import (  # noqa: E402
    _TT_SWITCH_BLOCKING_MODALS,
    _tt_detect_switch_blocking_modal,
)


FIXTURES = ROOT / 'tests' / 'fixtures'


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


# ─── _tt_detect_switch_blocking_modal — pure unit ───────────────────────────


def test_whitelist_seeded_with_phone_email_link_required():
    """Whitelist должен содержать запись для «Необходимо обновить аккаунт» с
    refusal-кнопкой «Не сейчас» и reason 'phone_or_email_link_required'."""
    found = False
    for heading, button, reason in _TT_SWITCH_BLOCKING_MODALS:
        if (heading == 'Необходимо обновить аккаунт'
                and button == 'Не сейчас'
                and reason == 'phone_or_email_link_required'):
            found = True
            break
    assert found, f'Запись не найдена в _TT_SWITCH_BLOCKING_MODALS={_TT_SWITCH_BLOCKING_MODALS!r}'
```

- [ ] **Step 2.2: Run test to verify it fails (ImportError)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_tt_switch_blocking_modal.py::test_whitelist_seeded_with_phone_email_link_required -v 2>&1 | tail -15
```

Expected: FAIL — `ImportError: cannot import name '_TT_SWITCH_BLOCKING_MODALS' from 'account_switcher'`.

---

### Task 3: Implement constant + helper (TDD green for Task 2)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (добавить блок рядом с `_TT_POST_SWITCH_DISMISSIBLE_MODALS` около строки 226)

- [ ] **Step 3.1: Найти точку вставки в `account_switcher.py`**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
grep -n "_TT_POST_SWITCH_DISMISSIBLE_MODALS:" account_switcher.py | head -3
```

Expected: одна или две строки около 223-226. Точка вставки нашего нового блока — сразу ПОСЛЕ закрывающей `)` whitelist'а Layer 2.

- [ ] **Step 3.2: Добавить константу + helper после `_TT_POST_SWITCH_DISMISSIBLE_MODALS`**

Insert после закрывающей `)` `_TT_POST_SWITCH_DISMISSIBLE_MODALS` (около строки 227, перед следующей пустой строкой / функцией):

```python


# ─────────────────────────────────────────────────────────────────────────────
# WP #93 2026-05-18 — TT switch blocking modal detector.
# Распознаём блокирующие pre-switch модалки TT (например «Необходимо обновить
# аккаунт» с refusal-кнопкой «Не сейчас»). Эти модалки появляются ПОСЛЕ tap по
# picker-row и ДО фактического переключения; их «dismiss» = refuse switch
# (TT отменяет переход и выкидывает на feed). Отдельный whitelist от
# _TT_POST_SWITCH_DISMISSIBLE_MODALS (тот — для nuisance-модалок поверх уже
# переключённого профиля).
#
# Match-правило (защита от Layer 2 ловушки, где title_substr совпал с текстом
# BUTTON): heading_substr должен лежать в NON-clickable элементе, refusal_button
# — в clickable элементе с точным равенством label (case-insensitive, trimmed).
# UIElement не хранит class — отличаем headings от buttons по флагу clickable.
# ─────────────────────────────────────────────────────────────────────────────
_TT_SWITCH_BLOCKING_MODALS: tuple[tuple[str, str, str], ...] = (
    ('Необходимо обновить аккаунт', 'Не сейчас', 'phone_or_email_link_required'),
)


def _tt_detect_switch_blocking_modal(
    xml: str,
) -> Optional[tuple[str, str, str]]:
    """Return (heading_substr, button_substr, reason) если матчится первая
    запись whitelist'а, иначе None.

    Matches when there exists a NON-clickable element whose label contains
    heading_substr (heading), AND a clickable element whose label equals
    button_substr (case-insensitive, trimmed). Both must coexist in the
    same dump. Heading-check requires NON-clickable explicitly to avoid the
    Layer 2 trap (where title_substr matched a button label and led to
    nuisance dismiss of a refusal button).
    """
    if not xml:
        return None
    elements = parse_ui_dump(xml)
    if not elements:
        return None
    for heading, button, reason in _TT_SWITCH_BLOCKING_MODALS:
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
```

- [ ] **Step 3.3: Run unit test — должен пройти**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_tt_switch_blocking_modal.py::test_whitelist_seeded_with_phone_email_link_required -v 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 3.4: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add account_switcher.py tests/test_tt_switch_blocking_modal.py
git commit -m "feat(tt): WP #93 step 1 — _TT_SWITCH_BLOCKING_MODALS + detector helper"
```

---

### Task 4: Расширить unit-suite (positive + 5 negatives)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/tests/test_tt_switch_blocking_modal.py`

- [ ] **Step 4.1: Добавить 6 дополнительных unit-тестов**

Append в `tests/test_tt_switch_blocking_modal.py`:

```python


def test_detect_known_blocking_modal_from_prod_dump():
    """task 7372 dump → ('Необходимо обновить аккаунт', 'Не сейчас', 'phone_or_email_link_required')."""
    xml = _read_fixture('tt_switch_blocked_phone_email_7372.xml')
    result = _tt_detect_switch_blocking_modal(xml)
    assert result is not None, 'detector должен сматчить prod-dump task 7372'
    heading, button, reason = result
    assert heading == 'Необходимо обновить аккаунт'
    assert button == 'Не сейчас'
    assert reason == 'phone_or_email_link_required'


def test_detect_returns_none_on_feed():
    """Feed после dismiss (sidebar профиля) не должен матчиться."""
    xml = _read_fixture('tt_feed_after_modal_dismiss_7372.xml')
    result = _tt_detect_switch_blocking_modal(xml)
    assert result is None, f'Feed-dump не должен матчиться, got {result!r}'


def test_detect_returns_none_on_profile():
    """Обычный own-profile screen не должен матчиться."""
    xml = _read_fixture('tt_profile_screen_7372.xml')
    result = _tt_detect_switch_blocking_modal(xml)
    assert result is None, f'Profile-dump не должен матчиться, got {result!r}'


def test_detect_button_only_no_match():
    """Только кнопка «Не сейчас» без heading — не должно матчиться."""
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2340]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[100,100][500,200]" class="android.widget.Button"
          text="Не сейчас" content-desc="" clickable="true" />
  </node>
</hierarchy>'''
    result = _tt_detect_switch_blocking_modal(xml)
    assert result is None


def test_detect_heading_as_button_no_match():
    """Если «Необходимо обновить...» лежит в clickable Button — НЕ матчится
    (это та самая Layer 2 ловушка)."""
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2340]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[100,800][900,900]" class="android.widget.Button"
          text="Необходимо обновить аккаунт" content-desc="" clickable="true" />
    <node bounds="[100,1000][900,1100]" class="android.widget.Button"
          text="Не сейчас" content-desc="" clickable="true" />
  </node>
</hierarchy>'''
    result = _tt_detect_switch_blocking_modal(xml)
    assert result is None, 'heading в Button (clickable=true) не должен матчиться'


def test_detect_heading_only_no_match():
    """Heading есть, но clickable refusal-button отсутствует — не матчится."""
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2340]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[100,800][900,900]" class="android.widget.TextView"
          text="Необходимо обновить аккаунт" content-desc="" clickable="false" />
  </node>
</hierarchy>'''
    result = _tt_detect_switch_blocking_modal(xml)
    assert result is None


def test_detect_empty_xml_returns_none():
    """Пустой XML / None / мусор не должны падать."""
    assert _tt_detect_switch_blocking_modal('') is None
    assert _tt_detect_switch_blocking_modal('<not-xml>') is None
    assert _tt_detect_switch_blocking_modal('<hierarchy rotation="1"></hierarchy>') is None
```

- [ ] **Step 4.2: Run все unit-тесты — должны пройти**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_tt_switch_blocking_modal.py -v 2>&1 | tail -20
```

Expected: 7 PASSED.

- [ ] **Step 4.3: Commit unit-suite**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add tests/test_tt_switch_blocking_modal.py
git commit -m "test(tt): WP #93 unit-suite — 7 detector tests (prod fixture + 5 edge negatives)"
```

---

### Task 5: Failing integration test для switcher call-site

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/tests/test_tt_switch_blocking_modal.py`

- [ ] **Step 5.1: Изучить вызов `_save_dump`/`_post_switch_verify_handle` в `_switch_tiktok`**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
sed -n '2555,2575p' account_switcher.py
```

Expected: видите блок:
```
xml_after_pick = self.p.dump_ui(retries=1) or ''
self._save_dump(label, xml_after_pick)
self._maybe_screenshot(label)
status, current = self._post_switch_verify_handle(target, xml_after_pick, header_y_max=header_y_max)
```

Точка вставки detector'а — между `self._maybe_screenshot(label)` и `status, current = self._post_switch_verify_handle(...)`.

- [ ] **Step 5.2: Добавить failing integration test в test-файл**

Append в `tests/test_tt_switch_blocking_modal.py`:

```python


# ─── Integration: _switch_tiktok detector call-site ─────────────────────────


class _FakeProxy:
    """Минимальный publisher-proxy для switcher integration-тестов.

    Поведение скопировано с conftest._stub_publisher_mixin — единственная
    разница: collect log_event() calls для assertion на category/meta.
    """
    def __init__(self):
        self.task_id = 7372
        self.account = 'expertcontentlab'
        self.platform = 'TikTok'
        self.events = []  # list[tuple(level, msg, meta)]

    def log_event(self, level, msg, meta=None):
        self.events.append((level, msg, meta or {}))

    def dump_ui(self, retries=1):
        return self._next_xml_for_dump

    # _switch_tiktok вызывает self.p.dump_ui — выставляется per-test
    _next_xml_for_dump = ''


def _make_switcher_with_blocking_modal_xml(monkeypatch, xml: str):
    """Build AccountSwitcher with mocked p.dump_ui returning given xml,
    and stub of _save_dump / _maybe_screenshot / _fail (capture-only)."""
    from account_switcher import AccountSwitcher
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.p = _FakeProxy()
    sw.p._next_xml_for_dump = xml
    sw._save_dump = MagicMock()
    sw._maybe_screenshot = MagicMock()
    sw._fail = MagicMock(return_value=MagicMock(success=False))
    # Заглушка _post_switch_verify_handle — НЕ должна быть вызвана если
    # detector сматчил.
    sw._post_switch_verify_handle = MagicMock(
        return_value=('unknown', None))
    return sw


_SENTINEL_FAIL = object()  # уникальный sentinel-объект для _fail mock return


def _make_switcher_with_blocking_modal_xml_v2(monkeypatch, xml: str):
    """Build AccountSwitcher with _fail mocked to return _SENTINEL_FAIL,
    чтобы можно было проверить что _maybe_handle_switch_blocking_modal
    возвращает именно тот же объект (доказывает что caller получит
    propagated fail-result, не пересоздаст новый)."""
    sw = _make_switcher_with_blocking_modal_xml(monkeypatch, xml)
    sw._fail = MagicMock(return_value=_SENTINEL_FAIL)
    return sw


def test_switcher_detector_emits_event_and_returns_fail_when_blocked(monkeypatch):
    """Integration: при блокирующей модалке _maybe_handle_switch_blocking_modal должен:
    1. вызвать _tt_detect_switch_blocking_modal,
    2. эмитнуть log_event с category='tt_switch_blocked',
    3. НЕ вызывать _post_switch_verify_handle,
    4. вернуть пробросом результат _fail(step='tt_switch_blocked').
    """
    xml = _read_fixture('tt_switch_blocked_phone_email_7372.xml')
    sw = _make_switcher_with_blocking_modal_xml_v2(monkeypatch, xml)
    # Mock account_blocks + notifier чтобы не тыкать боевую БД.
    fake_blocks = MagicMock()
    fake_blocks.set_block_by_username = MagicMock(return_value=42)
    fake_notifier = MagicMock()
    monkeypatch.setitem(sys.modules, 'account_blocks', fake_blocks)
    monkeypatch.setitem(sys.modules, 'notifier', fake_notifier)

    result = sw._maybe_handle_switch_blocking_modal(
        xml_after_pick=xml,
        target='expertcontentlab',
        attempt=0,
    )
    # detector сматчил — функция должна вернуть результат _fail (sentinel),
    # не None
    assert result is _SENTINEL_FAIL, (
        '_maybe_handle_switch_blocking_modal должен вернуть результат _fail '
        f'при матче, got {result!r}'
    )

    # log_event эмитнут с правильной категорией
    blocked_events = [e for e in sw.p.events
                      if e[2].get('category') == 'tt_switch_blocked']
    assert len(blocked_events) == 1
    _, _, meta = blocked_events[0]
    assert meta['reason'] == 'phone_or_email_link_required'
    assert meta['heading_substr'] == 'Необходимо обновить аккаунт'
    assert meta['target'] == 'expertcontentlab'
    assert meta['attempt'] == 1  # 1-indexed

    # _fail вызван с правильным step
    sw._fail.assert_called_once()
    _, kwargs = sw._fail.call_args
    assert kwargs.get('step') == 'tt_switch_blocked'

    # _post_switch_verify_handle НЕ вызван
    sw._post_switch_verify_handle.assert_not_called()


def test_switcher_detector_no_match_returns_none(monkeypatch):
    """Integration: при не-блокирующей модалке (feed) detector возвращает
    None и не эмитит fail-events."""
    xml = _read_fixture('tt_feed_after_modal_dismiss_7372.xml')
    sw = _make_switcher_with_blocking_modal_xml_v2(monkeypatch, xml)
    fake_blocks = MagicMock()
    fake_notifier = MagicMock()
    monkeypatch.setitem(sys.modules, 'account_blocks', fake_blocks)
    monkeypatch.setitem(sys.modules, 'notifier', fake_notifier)

    result = sw._maybe_handle_switch_blocking_modal(
        xml_after_pick=xml,
        target='expertcontentlab',
        attempt=0,
    )
    assert result is None
    blocked_events = [e for e in sw.p.events
                      if e[2].get('category') == 'tt_switch_blocked']
    assert blocked_events == []
    sw._fail.assert_not_called()
    fake_blocks.set_block_by_username.assert_not_called()
    fake_notifier.notify_escalation.assert_not_called()


def test_switcher_detector_set_block_failure_doesnt_break_fail(monkeypatch):
    """Integration: если set_block_by_username raise — fail всё равно
    эмитится, event сохранён, log.warning записан."""
    xml = _read_fixture('tt_switch_blocked_phone_email_7372.xml')
    sw = _make_switcher_with_blocking_modal_xml_v2(monkeypatch, xml)
    fake_blocks = MagicMock()
    fake_blocks.set_block_by_username = MagicMock(
        side_effect=RuntimeError('db down'))
    fake_notifier = MagicMock()
    monkeypatch.setitem(sys.modules, 'account_blocks', fake_blocks)
    monkeypatch.setitem(sys.modules, 'notifier', fake_notifier)

    result = sw._maybe_handle_switch_blocking_modal(
        xml_after_pick=xml,
        target='expertcontentlab',
        attempt=0,
    )
    assert result is _SENTINEL_FAIL
    sw._fail.assert_called_once()
    blocked_events = [e for e in sw.p.events
                      if e[2].get('category') == 'tt_switch_blocked']
    assert len(blocked_events) == 1


def test_switcher_detector_calls_notify_escalation(monkeypatch):
    """Integration: notify_escalation вызван с правильным key/title/body."""
    xml = _read_fixture('tt_switch_blocked_phone_email_7372.xml')
    sw = _make_switcher_with_blocking_modal_xml_v2(monkeypatch, xml)
    fake_blocks = MagicMock()
    fake_blocks.set_block_by_username = MagicMock(return_value=42)
    fake_notifier = MagicMock()
    monkeypatch.setitem(sys.modules, 'account_blocks', fake_blocks)
    monkeypatch.setitem(sys.modules, 'notifier', fake_notifier)

    sw._maybe_handle_switch_blocking_modal(
        xml_after_pick=xml,
        target='expertcontentlab',
        attempt=0,
    )
    fake_notifier.notify_escalation.assert_called_once()
    args, _ = fake_notifier.notify_escalation.call_args
    key, title, body = args
    assert key == 'tt_switch_blocked_phone_or_email_link_required'
    assert 'expertcontentlab' in title
    assert 'task_id=7372' in body
    assert 'factory_id=42' in body


def test_layer2_does_not_match_phone_email_button():
    """После удаления regression-строки из _TT_POST_SWITCH_DISMISSIBLE_MODALS,
    Layer 2 НЕ должен матчить нашу модалку (по `Привязать номер...` Button)."""
    from account_switcher import (
        _TT_POST_SWITCH_DISMISSIBLE_MODALS,
        _tt_try_dismiss_post_switch_modal,
    )
    # Проверка whitelist'а
    titles = [t for t, _ in _TT_POST_SWITCH_DISMISSIBLE_MODALS]
    assert 'Привязать номер телефона или эл. почту' not in titles, \
        'regression-строка должна быть удалена'
    # Проверка поведения на real prod dump
    xml = _read_fixture('tt_switch_blocked_phone_email_7372.xml')
    result = _tt_try_dismiss_post_switch_modal(xml)
    assert result is None, \
        f'Layer 2 не должен матчить нашу блокирующую модалку, got {result!r}'
```

- [ ] **Step 5.3: Run integration-тесты — должны FAIL (метод не существует)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_tt_switch_blocking_modal.py -v 2>&1 | tail -25
```

Expected: 7 unit-тестов PASSED + 5 integration-тестов FAILED с `AttributeError: 'AccountSwitcher' object has no attribute '_maybe_handle_switch_blocking_modal'` или (для `test_layer2_does_not_match_phone_email_button`) `AssertionError: regression-строка должна быть удалена` / `Layer 2 не должен матчить...`.

---

### Task 6: Реализовать `_maybe_handle_switch_blocking_modal` (TDD green для Task 5 integration)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (добавить method в class `AccountSwitcher`)

- [ ] **Step 6.1: Найти подходящее место для method в class `AccountSwitcher`**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
grep -n "def _post_switch_verify_handle\|def _switch_tiktok\|class AccountSwitcher" account_switcher.py | head -5
```

Expected: видны определения method'ов. Новый method вставляется рядом с `_post_switch_verify_handle` (semantically близко).

- [ ] **Step 6.2: Добавить method `_maybe_handle_switch_blocking_modal` в `class AccountSwitcher`**

Insert НА том же уровне отступа что и другие methods класса (4 spaces), РЯДОМ с `_post_switch_verify_handle`. Полный код:

```python
    def _maybe_handle_switch_blocking_modal(
        self,
        xml_after_pick: str,
        target: str,
        attempt: int,
    ):
        """[WP #93 2026-05-18] Детект блокирующей pre-switch модалки TT.

        Вызывается в `_switch_tiktok` после `_save_dump` и `_maybe_screenshot`,
        ДО `_post_switch_verify_handle`. Если модалка сматчилась:
          1. log_event с category='tt_switch_blocked',
          2. best-effort `account_blocks.set_block_by_username`,
          3. best-effort `notifier.notify_escalation`,
          4. возвращает результат `self._fail(step='tt_switch_blocked')` —
             caller должен сделать `return` этим значением, прервав цикл.

        Если модалка не сматчилась — возвращает None (caller продолжает
        на старый verify-flow).

        Detector обёрнут в try/except defensive: parse_ui_dump уже robust к
        ParseError, но любой другой Exception (re.error и т.п.) тут гасим,
        возвращаем None — продолжаем на старый verify-flow без падения switch.
        """
        try:
            blocked = _tt_detect_switch_blocking_modal(xml_after_pick)
        except Exception as de:
            log.warning(f'switcher.tt.detect_blocking_modal_failed: {de}')
            blocked = None
        if blocked is None:
            return None

        heading, button, reason = blocked
        log.error(
            f'switcher.tt.switch_blocked target={target!r} reason={reason!r} '
            f'heading={heading!r} attempt={attempt + 1}'
        )
        self.p.log_event(
            'error',
            f'TT switch blocked by modal: {heading!r}',
            meta={
                'category': 'tt_switch_blocked',
                'reason': reason,
                'heading_substr': heading,
                'button_substr': button,
                'target': target,
                'attempt': attempt + 1,
                'step': 'tt_switch_blocked',
            },
        )

        acc_id = None
        try:
            # set_block_by_username(username, platform, reason, **context) —
            # **context kwargs принимаются и складываются в JSONB payload
            # (см. account_blocks.py:51 set_block signature, существующий
            # IG human_check call в publisher_base.py:4217).
            import account_blocks
            acc_id = account_blocks.set_block_by_username(
                target, 'tt', reason=reason,
                publish_task_id=self.p.task_id,
                step='tt_switch_blocked',
                last_seen_screen='tt_4_target_profile',
                heading_substr=heading,
            )
        except Exception as be:
            log.warning(f'switcher.tt.set_block_failed: {be}')

        try:
            import notifier
            notifier.notify_escalation(
                f'tt_switch_blocked_{reason}',
                f'TT требует привязки номера/email для account={target}',
                f'task_id={self.p.task_id} factory_id={acc_id} step=tt_switch_blocked',
            )
        except Exception as ne:
            log.warning(f'switcher.tt.notify_failed: {ne}')

        return self._fail(
            f'tt switch blocked (reason={reason})',
            step='tt_switch_blocked',
        )
```

- [ ] **Step 6.3: Run integration-тесты — должны PASS (для 4 из 5; `test_layer2_does_not_match_phone_email_button` всё ещё FAIL)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_tt_switch_blocking_modal.py -v 2>&1 | tail -25
```

Expected: 7 unit + 4 integration PASSED, 1 integration FAILED (`test_layer2_does_not_match_phone_email_button` — regression-строка ещё не удалена).

- [ ] **Step 6.4: Commit method**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add account_switcher.py tests/test_tt_switch_blocking_modal.py
git commit -m "feat(tt): WP #93 step 2 — _maybe_handle_switch_blocking_modal method"
```

---

### Task 7: Вызвать `_maybe_handle_switch_blocking_modal` из `_switch_tiktok`

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (вставка вызова после строки 2561)

- [ ] **Step 7.1: Найти точную точку вставки**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
grep -n "self._maybe_screenshot(label)" account_switcher.py | head
```

Expected: одна или больше строк. Нас интересует та, что НЕ в `tt_2_*` блоках (т.е. в `tt_4_target_profile` flow). По состоянию баз — это строка около 2561.

```bash
sed -n '2555,2570p' account_switcher.py
```

Expected: видеть блок:
```
            label = (
                'tt_4_target_profile' if attempt == 0
                else f'tt_4_target_profile_retry_{attempt}'
            )
            xml_after_pick = self.p.dump_ui(retries=1) or ''
            self._save_dump(label, xml_after_pick)
            self._maybe_screenshot(label)

            status, current = self._post_switch_verify_handle(
```

- [ ] **Step 7.2: Вставить вызов detector'а между `_maybe_screenshot` и `_post_switch_verify_handle`**

Точное изменение (Edit с уникальным контекстом, чтобы не задеть другие `_maybe_screenshot` вызовы в файле):

**old:**
```python
            label = (
                'tt_4_target_profile' if attempt == 0
                else f'tt_4_target_profile_retry_{attempt}'
            )
            xml_after_pick = self.p.dump_ui(retries=1) or ''
            self._save_dump(label, xml_after_pick)
            self._maybe_screenshot(label)

            status, current = self._post_switch_verify_handle(
                target, xml_after_pick, header_y_max=header_y_max,
            )
```

**new:**
```python
            label = (
                'tt_4_target_profile' if attempt == 0
                else f'tt_4_target_profile_retry_{attempt}'
            )
            xml_after_pick = self.p.dump_ui(retries=1) or ''
            self._save_dump(label, xml_after_pick)
            self._maybe_screenshot(label)

            # [WP #93 2026-05-18] Детект блокирующих pre-switch модалок TT
            # (например "Необходимо обновить аккаунт / Не сейчас"). Если
            # сматчилось — fail-fast с tt_switch_blocked, без verify.
            # _maybe_handle_switch_blocking_modal сам вызывает self._fail(...)
            # и возвращает его результат (SwitchResult-like) — propagate его
            # наружу как обычный fail-return из _switch_tiktok.
            _blocked_result = self._maybe_handle_switch_blocking_modal(
                xml_after_pick=xml_after_pick,
                target=target,
                attempt=attempt,
            )
            if _blocked_result is not None:
                return _blocked_result

            status, current = self._post_switch_verify_handle(
                target, xml_after_pick, header_y_max=header_y_max,
            )
```

- [ ] **Step 7.3: Wiring-assertion (TDD-замена для нормального integration-теста на полный `_switch_tiktok`)**

Существующие integration-тесты вызывают `_maybe_handle_switch_blocking_modal` напрямую (через mock proxy), потому что полный `_switch_tiktok` flow требует слишком много зависимостей. Чтобы убедиться что Task 7.2 правильно подключил вызов в `_switch_tiktok`, делаем grep-проверку на физическое наличие:

```bash
cd /root/.openclaw/workspace-genri/autowarm/
# Должна быть последовательность: _maybe_screenshot(label) → _maybe_handle_switch_blocking_modal → if _blocked_result is not None
awk '/self\._maybe_screenshot\(label\)/{flag=1; line=NR} flag && /_maybe_handle_switch_blocking_modal/ && NR-line<10 {found=1; print "OK: wiring found at line " NR; exit} END{if(!found){print "FAIL: detector call missing after _maybe_screenshot(label)"; exit 1}}' account_switcher.py
```

Expected: `OK: wiring found at line NNNN`. Если FAIL — Step 7.2 не вступил в силу, Edit ещё раз.

- [ ] **Step 7.4: Run все тесты — все 12 должны PASS, кроме layer2-теста**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_tt_switch_blocking_modal.py -v 2>&1 | tail -20
```

Expected: 11 PASSED, 1 FAILED (`test_layer2_does_not_match_phone_email_button` — regression ещё не удалена).

- [ ] **Step 7.5: Commit вставку**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add account_switcher.py
git commit -m "feat(tt): WP #93 step 3 — wire detector into _switch_tiktok before verify"
```

---

### Task 8: Удалить regression-строку из `_TT_POST_SWITCH_DISMISSIBLE_MODALS`

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (строка 225)

- [ ] **Step 8.1: Edit удаление regression-строки**

**old:**
```python
_TT_POST_SWITCH_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...] = (
    # NB: title-check защищает от ложного dismiss другого 'Не сейчас' в неродственном контексте.
    ('Привязать номер телефона или эл. почту', 'Не сейчас'),
    ('Сохранить данные для входа', 'Не сейчас'),
)
```

**new:**
```python
_TT_POST_SWITCH_DISMISSIBLE_MODALS: tuple[tuple[str, str], ...] = (
    # NB: title-check защищает от ложного dismiss другого 'Не сейчас' в неродственном контексте.
    # [WP #93 2026-05-18] УДАЛЕНО: ('Привязать номер телефона или эл. почту', 'Не сейчас').
    # Это была regression-строка Layer 2: title_substr матчился по тексту BUTTON,
    # реальный heading модалки — «Необходимо обновить аккаунт». Dismiss «Не сейчас»
    # на этой модалке = refuse switch (TT отменяет переход, выкидывает на feed).
    # Перенесено в _TT_SWITCH_BLOCKING_MODALS с правильной semantics.
    ('Сохранить данные для входа', 'Не сейчас'),
)
```

⚠ **Step 8.1 предупреждение:** точный исходный текст комментариев на строках 221-224 может отличаться. Если Edit падает с "old_string not found" — Read строки 218-230 и выполнить Edit с актуальным контентом.

- [ ] **Step 8.2: Run все тесты — все 12 должны PASS**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_tt_switch_blocking_modal.py -v 2>&1 | tail -20
```

Expected: 12 PASSED.

- [ ] **Step 8.3: Run WP #67 тесты — НЕ должно быть регрессий**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/test_account_switcher_modal_dismiss.py -v 2>&1 | tail -25
```

Expected: один тест станет skip/fail на старой записи «Привязать номер...» если он есть. Проверить:

```bash
grep -n "Привязать номер" tests/test_account_switcher_modal_dismiss.py
```

Если есть assertion ожидающий matched на эту запись — её НУЖНО обновить (теперь Layer 2 не матчит, новая Detector матчит). Замените `assert ... 'Привязать номер...'` на `# WP #93: модалка перенесена в _TT_SWITCH_BLOCKING_MODALS, см. test_tt_switch_blocking_modal.py`.

Если такого assertion нет — все WP #67 тесты должны остаться зелёными (мы убрали whitelist-запись, но не сломали инфраструктуру).

- [ ] **Step 8.4: Commit удаление**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add account_switcher.py
# плюс tests/test_account_switcher_modal_dismiss.py если правили на Step 8.3
git commit -m "fix(tt): WP #93 step 4 — remove Layer 2 regression entry (phone-email modal)"
```

---

### Task 9: Добавить step → error_code mapping в `publisher_kernel.py`

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_kernel.py` (рядом со строкой 159)

- [ ] **Step 9.1: Найти секцию TikTok step→error_code mappings**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
grep -n "tt_4_target_profile\|tt_post_switch_verify_unrecoverable\|TikTok" publisher_kernel.py | head -10
```

Expected: видны TT mappings около строк 145-170.

- [ ] **Step 9.2: Добавить новую строку в map**

Insert рядом с существующими `'tt_4_target_profile': 'tt_post_switch_verify_unrecoverable'` (около строки 146):

**old:**
```python
    'tt_4_target_profile': 'tt_post_switch_verify_unrecoverable',
    'tt_4_target_profile_renav': 'tt_post_switch_verify_unrecoverable',
```

**new:**
```python
    'tt_4_target_profile': 'tt_post_switch_verify_unrecoverable',
    'tt_4_target_profile_renav': 'tt_post_switch_verify_unrecoverable',
    'tt_switch_blocked': 'tt_switch_blocked',  # WP #93 2026-05-18
```

- [ ] **Step 9.3: Smoke-test mapping (если есть test_error_code_mapper.py — расширить, иначе grep-проверка)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
grep -n "tt_switch_blocked" publisher_kernel.py
```

Expected: одна строка с нашим mapping.

Если в `tests/test_canonical_error_codes.py` есть assertions про доступные error_codes — добавить `'tt_switch_blocked'` в whitelist если он есть:

```bash
grep -n "tt_post_switch\|canonical\|VALID_ERROR_CODES" tests/test_canonical_error_codes.py 2>&1 | head -10
```

Если whitelist есть — добавить `'tt_switch_blocked'`. Если нет — пропустить.

- [ ] **Step 9.4: Run полный набор тестов — должны PASS (guarded)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
TESTS="tests/test_tt_switch_blocking_modal.py"
[ -f tests/test_canonical_error_codes.py ] && TESTS="$TESTS tests/test_canonical_error_codes.py"
[ -f tests/test_error_code_mapper.py ] && TESTS="$TESTS tests/test_error_code_mapper.py"
pytest $TESTS -v 2>&1 | tail -20
```

Expected: все зелёные. Если что-то падает — fix inline (вероятно нужно расширить whitelist в test_canonical_error_codes).

- [ ] **Step 9.5: Commit mapping**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add publisher_kernel.py
# плюс tests/test_canonical_error_codes.py если правили на Step 9.3
git commit -m "feat(tt): WP #93 step 5 — step->error_code mapping tt_switch_blocked"
```

---

### Task 10: Полный test suite — никаких регрессий

- [ ] **Step 10.1: Run все switcher-related тесты (guarded по существованию)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
TESTS=""
for f in tests/test_account_switcher.py tests/test_account_switcher_tt.py \
         tests/test_account_switcher_modal_dismiss.py \
         tests/test_tt_switch_blocking_modal.py \
         tests/test_canonical_error_codes.py tests/test_error_code_mapper.py; do
  [ -f "$f" ] && TESTS="$TESTS $f"
done
echo "Запускаем: $TESTS"
pytest $TESTS -v 2>&1 | tail -30
```

Expected: все зелёные. Если что-то красное — STOP, разбираться корень. Не маркировать complete с регрессией.

- [ ] **Step 10.2: Run полный suite (если на машине есть время)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
pytest tests/ -q 2>&1 | tail -15
```

Expected: все зелёные (или столько же зелёных как до начала работы, +12 новых). Если красные — проверить, наш ли scope.

- [ ] **Step 10.3: Sanity-check git log на ветке**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git log --oneline origin/main..HEAD
git diff --stat origin/main..HEAD
```

Expected: ~6 коммитов (Task 1 + Task 3 + Task 4 + Task 6 + Task 7 + Task 8 + Task 9), ~4-5 файлов изменено.

---

### Task 11: Push branch + open PR

- [ ] **Step 11.1: Push feature branch на remote**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git push -u origin feat/wp93-tt-switch-blocking-modal 2>&1 | tail -10
```

Expected: `* [new branch] feat/wp93-tt-switch-blocking-modal -> feat/wp93-tt-switch-blocking-modal`.

⚠ **Не делать force-push.** Если push отклонён — fetch + rebase + retry (но обычно для нового branch push успешен).

- [ ] **Step 11.2: Создать PR на GenGo2/delivery-contenthunter**

```bash
export GITHUB_TOKEN=$(grep ^GITHUB_TOKEN ~/secrets/github-gengo2.env | cut -d= -f2)
cd /root/.openclaw/workspace-genri/autowarm/
gh pr create \
  --repo GenGo2/delivery-contenthunter \
  --base main \
  --head feat/wp93-tt-switch-blocking-modal \
  --title "WP #93 — TT switch blocked by «Необходимо обновить аккаунт» modal: detect + classify" \
  --body "$(cat <<'EOF'
## Summary

Распознаём блокирующую TT-модалку «Необходимо обновить аккаунт» сразу после tap по picker-row. Эта модалка появляется ПЕРЕД самим переключением аккаунта; нажатие «Не сейчас» = refusal switch (TT отменяет переход и выкидывает на feed), не nuisance-dismiss. Bundle:
- detector + account_blocks write + notify_escalation в новом методе `_maybe_handle_switch_blocking_modal`,
- revert ошибочной строки `('Привязать номер телефона или эл. почту', 'Не сейчас')` из `_TT_POST_SWITCH_DISMISSIBLE_MODALS` (WP #67 Layer 2 regression — title_substr матчил текст BUTTON, не heading).

См. spec `docs/superpowers/specs/2026-05-18-wp93-tt-switch-blocking-modal-design.md` в rmbrmv/contenthunter.

## Что меняется

- `account_switcher.py`: новая константа `_TT_SWITCH_BLOCKING_MODALS`, helper `_tt_detect_switch_blocking_modal`, method `_maybe_handle_switch_blocking_modal`, вставка вызова в `_switch_tiktok` (после `_save_dump`/`_maybe_screenshot`, до `_post_switch_verify_handle`), удаление regression-строки из Layer 2 whitelist.
- `publisher_kernel.py`: новая запись `'tt_switch_blocked': 'tt_switch_blocked'` в step→error_code map.
- `tests/`: 7 unit + 5 integration тестов; 3 prod-fixture с S3.

## Test plan

- [ ] `pytest tests/test_tt_switch_blocking_modal.py -v` — 12/12 зелёных.
- [ ] `pytest tests/test_account_switcher_modal_dismiss.py -v` — WP #67 не сломан.
- [ ] Re-queue task 7372 (`expertcontentlab`) через `publish_queue` → ожидаем `status='failed'`, `error_code='tt_switch_blocked'`, jsonb event с category=`tt_switch_blocked`.
- [ ] `SELECT tt_block FROM factory_reg_accounts WHERE tiktok_username='expertcontentlab';` → reason=`phone_or_email_link_required`, `heading_substr='Необходимо обновить аккаунт'`.
- [ ] 24h soak: `count(error_code='tt_switch_blocked')` 0-2, `count(error_code='tt_post_switch_verify_unrecoverable')` не больше pre-deploy baseline.

## Kill-switch

`_TT_SWITCH_BLOCKING_MODALS = ()` в `account_switcher.py` → helper всегда None → flow идентичен pre-fix.

## Links

- WP: https://openproject.contenthunter.ru/work_packages/93
- WP #67 Layer 2 ship doc: `docs/evidence/2026-05-18-tt-post-switch-modal-dismiss-shipped.md` (rmbrmv/contenthunter)
- Spec: `docs/superpowers/specs/2026-05-18-wp93-tt-switch-blocking-modal-design.md` (rmbrmv/contenthunter, branch `feat/wp93-tt-picker-wrong-row`)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" 2>&1 | tail -3
```

Expected: URL созданного PR.

- [ ] **Step 11.3: Принести PR URL в чат для user review**

После создания PR — вывести URL и пометить task сompleted. Дальнейшие действия (merge, deploy, smoke-проверка post-deploy, 24h soak) — за пользователем / отдельной session.

---

## Post-implementation (вне scope этого плана)

Эти шаги — за пользователем после merge:

- **Deploy:** автоматический через post-commit hook на prod autowarm (`/root/.openclaw/workspace-genri/autowarm/` → main → push) ПОСЛЕ merge PR. По памяти `feedback_pm2_dump_path_drift.md` — после merge проверить `pm2 describe <app> | grep "exec cwd"`, чтобы убедиться что pm2 читает из prod, не из testbench.
- **Smoke post-deploy:** Task 11.2 plan_body (test plan).
- **24h soak:** queries из spec §7.5.
- **OpenProject update:** добавить comment в WP #93 с PR-ссылкой и smoke-результатами по house style (Что было не так → Что сделано → Что осталось).
- **Memory update:** при ship — добавить `project_tt_switch_blocking_modal_shipped.md` запись в `~/.claude/projects/-home-claude-user-contenthunter/memory/` (см. `project_tt_post_switch_modal_dismiss_shipped.md` как шаблон).
