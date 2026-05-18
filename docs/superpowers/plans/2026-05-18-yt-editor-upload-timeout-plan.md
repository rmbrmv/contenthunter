# YT `yt_editor_upload_timeout` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить главный bucket YT-фейлов (`yt_editor_upload_timeout`, 75% за сутки) тремя слоями fail-fast guard'ов в switcher → create-menu тапе → editor verify.

**Architecture:** Все изменения в репозитории `/root/.openclaw/workspace-genri/autowarm` (GenGo2/delivery-contenthunter). Layer 1 — `account_switcher.py` (новый opt-in `strict_verify` параметр + чистка YT `editor_triggers`). Layer 2 — `publisher_youtube.py::_is_create_menu_open` детектор + замена unsafe `tap_element`. Layer 3 — `publisher_youtube.py::_verify_yt_editor_reached` guard перед editor loop. Регистрация нового error_code в `publisher_kernel._SWITCHER_STEP_TO_CATEGORY`.

**Tech Stack:** Python 3.12, pytest 8.3, MagicMock-based fixtures (см. `tests/conftest.py`), реальные UI-dump XML с production-задач 6815/6816 как фикстуры.

**Spec:** `docs/superpowers/specs/2026-05-18-yt-editor-upload-timeout-design.md`
**OpenProject:** WP #80

---

## File Structure

**Целевой репо:** `/root/.openclaw/workspace-genri/autowarm` (отдельный git checkout от текущего worktree). Все пути ниже — относительные к нему.

| Action | File | Назначение |
|---|---|---|
| Modify | `account_switcher.py:101` | YT `editor_triggers`: убрать двусмысленный `'Short'`, добавить точные `'Видео'/'Прямой эфир'/'Live'`. |
| Modify | `account_switcher.py:4110-4134` (`_tap_plus_and_verify`) | Добавить optional `strict_verify: bool = False`. При strict + пустых hits → `_fail` со step `<final_step>_no_triggers`. |
| Modify | `account_switcher.py:3150-3154` (`_switch_youtube`) | Передавать `strict_verify=True` в `_tap_plus_and_verify` для `yt_6_create_menu`. |
| Modify | `publisher_kernel.py:161-169` | Добавить mapping `'yt_6_create_menu_no_triggers': 'yt_create_menu_not_reached'`. |
| Modify | `publisher_youtube.py` (вокруг `publish_youtube_short`, ~830-905) | Layer 2 (детектор Create-menu) + Layer 3 (editor verify). |
| Create | `tests/fixtures/yt_create_menu/create_menu_open.xml` | Synthetic UI dump с 4 кнопками Create. |
| Create | `tests/fixtures/yt_create_menu/home_feed_no_create.xml` | Реальный home feed (downloaded). |
| Create | `tests/fixtures/yt_editor_verify/editor_with_title.xml` | Synthetic editor с EditText title-field. |
| Create | `tests/fixtures/yt_editor_verify/shorts_overlay_6815.xml` | Реальный dump task 6815 (Shorts overlay). |
| Create | `tests/fixtures/yt_editor_verify/chrome_temu_6816.xml` | Реальный dump task 6816 (Chrome). |
| Create | `tests/test_yt_create_menu_strict_verify.py` | Unit-тесты Layer 1. |
| Create | `tests/test_yt_publisher_editor_guards.py` | Unit-тесты Layer 2 + Layer 3. |

---

## Pre-Task 0: Setup target repo

**Files:** workspace shell

- [ ] **Step 0.1: Создать feature branch в autowarm-репо.**

Worktree `/home/claude-user/contenthunter/.claude/worktrees/yt-fails-triage-2026-05-18` — это docs-репо (контент-хантер). Код autowarm лежит в **другом** репо: `/root/.openclaw/workspace-genri/autowarm`. Auto-push git hook отправит push в `GenGo2/delivery-contenthunter` на каждом commit'е (см. memory `reference_autowarm_git_hook`). Поэтому работаем на отдельной ветке, не main.

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git checkout main && git pull --ff-only origin main
git checkout -b yt-editor-upload-timeout-fix-2026-05-18
```

Ожидаемо: `Switched to a new branch 'yt-editor-upload-timeout-fix-2026-05-18'`.

- [ ] **Step 0.2: Прогнать baseline tests.**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python -m pytest tests/test_yt_post_switch_verify.py tests/test_account_switcher.py -q 2>&1 | tail -20
```

Ожидаемо: green (или известные skips). Если красные тесты на main — сообщить и не продолжать.

---

## Task 1: UI-dump фикстуры

**Files:**
- Create: `tests/fixtures/yt_create_menu/create_menu_open.xml`
- Create: `tests/fixtures/yt_create_menu/home_feed_no_create.xml`
- Create: `tests/fixtures/yt_editor_verify/editor_with_title.xml`
- Create: `tests/fixtures/yt_editor_verify/shorts_overlay_6815.xml`
- Create: `tests/fixtures/yt_editor_verify/chrome_temu_6816.xml`

- [ ] **Step 1.1: Создать каталоги фикстур.**

```bash
cd /root/.openclaw/workspace-genri/autowarm
mkdir -p tests/fixtures/yt_create_menu tests/fixtures/yt_editor_verify
```

- [ ] **Step 1.2: Скачать реальный Shorts-overlay dump (task 6815).**

```bash
curl -fsSL -o tests/fixtures/yt_editor_verify/shorts_overlay_6815.xml \
  "https://save.gengo.io/autowarm/ui_dumps/youtube/task6815_publish_6815_youtube_editor_step0_1779088572.xml"
test -s tests/fixtures/yt_editor_verify/shorts_overlay_6815.xml && echo OK
```

Ожидаемо: `OK` + ненулевой размер. Если URL уже не доступен — взять любой Shorts-feed dump из памяти `reference_autowarm_artifacts` / `/tmp/autowarm_ui_dumps`.

- [ ] **Step 1.3: Скачать реальный Chrome dump (task 6816).**

```bash
curl -fsSL -o tests/fixtures/yt_editor_verify/chrome_temu_6816.xml \
  "https://save.gengo.io/autowarm/ui_dumps/youtube/task6816_publish_6816_youtube_editor_step0_1779089093.xml"
test -s tests/fixtures/yt_editor_verify/chrome_temu_6816.xml && echo OK
```

- [ ] **Step 1.4: Создать synthetic editor dump.**

Файл `tests/fixtures/yt_editor_verify/editor_with_title.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.google.android.youtube" bounds="[0,0][1080,2340]">
    <node index="0" text="Добавьте название" resource-id="com.google.android.youtube:id/title_edit_text" class="android.widget.EditText" package="com.google.android.youtube" clickable="true" bounds="[40,400][1040,560]"/>
    <node index="1" text="Добавить описание" resource-id="com.google.android.youtube:id/description_edit_text" class="android.widget.EditText" package="com.google.android.youtube" clickable="true" bounds="[40,600][1040,760]"/>
    <node index="2" text="Загрузить" resource-id="com.google.android.youtube:id/upload_button" class="android.widget.Button" package="com.google.android.youtube" clickable="true" bounds="[820,2100][1040,2200]"/>
  </node>
</hierarchy>
```

- [ ] **Step 1.5: Создать synthetic Create-menu open dump.**

Файл `tests/fixtures/yt_create_menu/create_menu_open.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.google.android.youtube" bounds="[0,0][1080,2340]">
    <node index="0" text="Shorts" resource-id="" class="android.widget.TextView" package="com.google.android.youtube" clickable="true" bounds="[100,1800][400,1900]"/>
    <node index="1" text="Видео" resource-id="" class="android.widget.TextView" package="com.google.android.youtube" clickable="true" bounds="[100,1900][400,2000]"/>
    <node index="2" text="Прямой эфир" resource-id="" class="android.widget.TextView" package="com.google.android.youtube" clickable="true" bounds="[100,2000][400,2100]"/>
    <node index="3" text="Пост" resource-id="" class="android.widget.TextView" package="com.google.android.youtube" clickable="true" bounds="[100,2100][400,2200]"/>
  </node>
</hierarchy>
```

- [ ] **Step 1.6: Создать synthetic home-feed (без Create-menu) dump.**

Файл `tests/fixtures/yt_create_menu/home_feed_no_create.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.google.android.youtube" bounds="[0,0][1080,2340]">
    <node index="0" text="Главная" resource-id="" class="android.widget.TextView" package="com.google.android.youtube" clickable="true" bounds="[0,2200][216,2340]"/>
    <node index="1" text="Shorts" resource-id="" class="android.widget.TextView" package="com.google.android.youtube" clickable="true" bounds="[216,2200][432,2340]"/>
    <node index="2" text="Подписки" resource-id="" class="android.widget.TextView" package="com.google.android.youtube" clickable="true" bounds="[648,2200][864,2340]"/>
    <node index="3" text="Вы" resource-id="" class="android.widget.TextView" package="com.google.android.youtube" clickable="true" bounds="[864,2200][1080,2340]"/>
  </node>
</hierarchy>
```

- [ ] **Step 1.7: Commit.**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add tests/fixtures/yt_create_menu tests/fixtures/yt_editor_verify
git commit -m "test(yt): фикстуры UI-dump для create-menu/editor verify guards"
```

---

## Task 2: Layer 1 — `_tap_plus_and_verify` strict mode + YT cfg cleanup

**Files:**
- Modify: `account_switcher.py:101` (YT `editor_triggers`)
- Modify: `account_switcher.py:4110-4134` (`_tap_plus_and_verify`)
- Modify: `account_switcher.py:3150-3154` (`_switch_youtube` callsite)
- Modify: `publisher_kernel.py:161-169` (step→category mapping)
- Create: `tests/test_yt_create_menu_strict_verify.py`

- [ ] **Step 2.1: Написать failing-test для strict_verify=True + home-feed dump.**

Создать `tests/test_yt_create_menu_strict_verify.py`:

```python
"""Layer 1 — switcher fail-fast при отсутствии Create-menu (WP #80)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import account_switcher as _asw

FIX = Path(__file__).parent / "fixtures" / "yt_create_menu"


def _stub_switcher_with_dump(xml_path: Path) -> _asw.AccountSwitcher:
    xml = xml_path.read_text()
    sw = _asw.AccountSwitcher.__new__(_asw.AccountSwitcher)
    sw.p = MagicMock()
    sw.p.dump_ui = MagicMock(return_value=xml)
    sw.p.tap_element = MagicMock(return_value=True)
    sw.p.adb_tap = MagicMock()
    sw.p.log_event = MagicMock()
    sw._save_dump = MagicMock()
    sw._maybe_screenshot = MagicMock()
    return sw


def test_strict_verify_fails_when_triggers_absent_on_home_feed():
    """Home feed YT (bottom-nav only) → strict_verify=True должен вернуть _fail."""
    sw = _stub_switcher_with_dump(FIX / "home_feed_no_create.xml")
    cfg = _asw.PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg,
        step_prefix="yt_6",
        final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False,
        strict_verify=True,
    )
    assert result.success is False, (
        "Ожидался fail при отсутствии Create-menu triggers"
    )
    assert result.final_step == "yt_6_create_menu_no_triggers"


def test_strict_verify_passes_when_triggers_present_on_create_menu():
    """Реальное Create-menu (4 кнопки) → strict_verify=True проходит."""
    sw = _stub_switcher_with_dump(FIX / "create_menu_open.xml")
    cfg = _asw.PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg,
        step_prefix="yt_6",
        final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False,
        strict_verify=True,
    )
    assert result.success is True
    assert result.final_step == "yt_6_create_menu"


def test_non_strict_verify_still_passes_on_missing_triggers_for_ig_tt():
    """IG/TT не передают strict_verify=True → текущее поведение (warning + ok)."""
    sw = _stub_switcher_with_dump(FIX / "home_feed_no_create.xml")
    cfg = _asw.PLATFORM_CFG["YouTube"]
    result = sw._tap_plus_and_verify(
        cfg,
        step_prefix="yt_6",
        final_step="yt_6_create_menu",
        verify_triggers=cfg["editor_triggers"],
        already_matched=False,
    )
    assert result.success is True, (
        "Без strict_verify должно сохраняться текущее поведение для IG/TT"
    )


def test_yt_editor_triggers_no_longer_contain_ambiguous_short():
    """'Short' матчится на bottom-nav 'Shorts' — должно быть удалено из YT cfg."""
    assert "Short" not in _asw.PLATFORM_CFG["YouTube"]["editor_triggers"]
```

- [ ] **Step 2.2: Запустить тест — должен fail.**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python -m pytest tests/test_yt_create_menu_strict_verify.py -v 2>&1 | tail -20
```

Ожидаемо: FAIL — `TypeError: unexpected keyword 'strict_verify'` или ассерт по `'Short'`.

- [ ] **Step 2.3: Обновить YT cfg в `account_switcher.py:101`.**

Прочитать строки 96-105 (фрагмент cfg `'YouTube'`). Заменить:

```python
        'editor_triggers': ['Добавить описание', 'Add description', 'Опубликовать',
                            'Upload', 'Short'],
```

на:

```python
        'editor_triggers': ['Добавить описание', 'Add description', 'Опубликовать',
                            'Upload', 'Видео', 'Видео ', 'Прямой эфир', 'Live'],
```

Note: `'Видео '` (с trailing space) НЕ добавлять — оставить только `'Видео'`. Триггер matched через `t.lower() in ui.lower()`, поэтому substring `'видео'` корректно найдётся независимо от bounds.

Финальный список: `['Добавить описание', 'Add description', 'Опубликовать', 'Upload', 'Видео', 'Прямой эфир', 'Live']`.

- [ ] **Step 2.4: Расширить `_tap_plus_and_verify` параметром `strict_verify`.**

В `account_switcher.py:4110-4134` заменить сигнатуру и тело:

```python
    def _tap_plus_and_verify(self, cfg: dict, step_prefix: str, final_step: str,
                             verify_triggers: list,
                             already_matched: bool,
                             strict_verify: bool = False) -> SwitchResult:
        """Тап "+" → опционально проверить ожидаемый экран.

        strict_verify=True (используется только в _switch_youtube для
        yt_6_create_menu): если verify_triggers ни одного hit не дали — вернуть
        _fail со step '<final_step>_no_triggers'. Без этого флага сохраняется
        legacy-поведение (warning + success), чтобы не сломать IG/TT.
        """
        plus = cfg['plus_button']
        ui = self.p.dump_ui()
        tapped = False
        if ui:
            tapped = self.p.tap_element(ui, plus['desc'], clickable_only=True)
        if not tapped:
            log.debug(f'[switcher] {step_prefix}_plus: fallback coords {plus["coords"]}')
            self.p.adb_tap(*plus['coords'])
        time.sleep(POST_TAP_WAIT_S + 1.0)
        self._save_dump(final_step, self.p.dump_ui(retries=1))
        self._maybe_screenshot(final_step)

        ui2 = self.p.dump_ui(retries=1)
        hits = []
        if ui2 and verify_triggers:
            hits = [t for t in verify_triggers if t.lower() in ui2.lower()]
            if hits:
                log.info(f'[switcher] {final_step}: verified by triggers {hits}')
            else:
                log.warning(f'[switcher] {final_step}: no expected triggers — '
                            f'continuing (FLAG_SECURE/unknown layout)')
        if strict_verify and not hits:
            fail_step = f'{final_step}_no_triggers'
            self.p.log_event(
                'warning', f'{fail_step}: Create-menu triggers not found',
                meta={'category': 'yt_create_menu_not_reached',
                      'step': fail_step,
                      'verify_triggers': list(verify_triggers)},
            )
            return self._fail(
                f'{final_step}: ни один verify-trigger не найден '
                f'после tap "+" (strict_verify)',
                step=fail_step,
            )
        return self._ok(final_step, already_matched=already_matched)
```

- [ ] **Step 2.5: Включить strict_verify в `_switch_youtube`.**

В `account_switcher.py:3150-3154` заменить:

```python
        return self._tap_plus_and_verify(
            cfg, step_prefix='yt_6', final_step='yt_6_create_menu',
            verify_triggers=cfg['editor_triggers'],
            already_matched=False,
        )
```

на:

```python
        return self._tap_plus_and_verify(
            cfg, step_prefix='yt_6', final_step='yt_6_create_menu',
            verify_triggers=cfg['editor_triggers'],
            already_matched=False,
            strict_verify=True,
        )
```

- [ ] **Step 2.6: Зарегистрировать step→category mapping.**

В `publisher_kernel.py` найти блок YT (строки 161-169) и добавить новую запись:

```python
    'yt_1_feed': 'yt_app_launch_failed',
    'yt_2_profile_tab': 'yt_profile_tab_broken',
    'yt_3_open_accounts': 'yt_accounts_btn_missing',
    'yt_3_pick_account': 'yt_account_not_in_list',
    'yt_4_pick_account': 'yt_target_not_in_picker_after_scroll', # canonical B3
    'yt_5_post_switch_mismatch': 'yt_post_switch_mismatch',
    'yt_5_editor': 'yt_editor_not_opened',
    'yt_6_create_menu_no_triggers': 'yt_create_menu_not_reached',  # WP #80
    'yt_fg_drift_unrecoverable': 'yt_fg_drift_unrecoverable',
    'yt_fg_drift_escalated': 'yt_fg_drift_escalated',
```

- [ ] **Step 2.7: Запустить тесты — должны passed.**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python -m pytest tests/test_yt_create_menu_strict_verify.py -v 2>&1 | tail -20
```

Ожидаемо: 4 passed.

- [ ] **Step 2.8: Прогнать существующие switcher-тесты, чтобы убедиться что IG/TT не сломались.**

```bash
python -m pytest tests/test_account_switcher.py tests/test_account_switcher_tt.py tests/test_yt_post_switch_verify.py -q 2>&1 | tail -10
```

Ожидаемо: всё green (или те же skips что были в baseline на Step 0.2).

- [ ] **Step 2.9: Commit.**

```bash
git add account_switcher.py publisher_kernel.py tests/test_yt_create_menu_strict_verify.py
git commit -m "fix(yt-switcher): strict-verify create-menu triggers + cleanup ambiguous 'Short'

При отсутствии Create-menu triggers на yt_6_create_menu switcher
теперь возвращает _fail (step=yt_6_create_menu_no_triggers,
error_code=yt_create_menu_not_reached). Триггер 'Short' удалён —
он матчился на bottom-nav 'Shorts' и давал false-positive verify
даже когда YT остался на home feed.

Slayer 1/3 фикса WP #80 (yt_editor_upload_timeout)."
```

---

## Task 3: Layer 2 — `_is_create_menu_open` детектор

**Files:**
- Modify: `publisher_youtube.py` (новый helper `_is_create_menu_open` + замена `tap_element` в `publish_youtube_short`)
- Create: `tests/test_yt_publisher_editor_guards.py`

- [ ] **Step 3.1: Написать failing-test для `_is_create_menu_open`.**

Создать `tests/test_yt_publisher_editor_guards.py`:

```python
"""Layer 2 + Layer 3 — publisher_youtube guards (WP #80)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import publisher_youtube

FIX_MENU = Path(__file__).parent / "fixtures" / "yt_create_menu"
FIX_ED = Path(__file__).parent / "fixtures" / "yt_editor_verify"


def _yt_pub(xml: str | None = None) -> publisher_youtube.YouTubeMixin:
    p = publisher_youtube.YouTubeMixin.__new__(publisher_youtube.YouTubeMixin)
    p.task_id = 9999
    p.platform = "YouTube"
    p.platform_cfg = {"package": "com.google.android.youtube"}
    p.log_event = MagicMock()
    p.set_step = MagicMock()
    p.adb = MagicMock(return_value="")
    p.adb_tap = MagicMock()
    p.adb_text = MagicMock()
    p.dump_ui = MagicMock(return_value=xml or "<hierarchy/>")
    p.tap_element = MagicMock(return_value=False)
    return p


def test_is_create_menu_open_true_on_4_buttons():
    p = _yt_pub()
    xml = (FIX_MENU / "create_menu_open.xml").read_text()
    assert p._is_create_menu_open(xml) is True


def test_is_create_menu_open_false_on_home_feed():
    """Bottom-nav содержит 'Shorts' но НЕ содержит Create-menu — должно быть False."""
    p = _yt_pub()
    xml = (FIX_MENU / "home_feed_no_create.xml").read_text()
    assert p._is_create_menu_open(xml) is False


def test_is_create_menu_open_false_on_empty_or_garbage():
    p = _yt_pub()
    assert p._is_create_menu_open("") is False
    assert p._is_create_menu_open("<hierarchy/>") is False
```

- [ ] **Step 3.2: Запустить — должен fail.**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python -m pytest tests/test_yt_publisher_editor_guards.py -v 2>&1 | tail -10
```

Ожидаемо: FAIL — `AttributeError: ... has no attribute '_is_create_menu_open'`.

- [ ] **Step 3.3: Добавить `_is_create_menu_open` в `publisher_youtube.py`.**

Перед `def _normalize_yt_state_pre_upload` (строка ~764) добавить новый helper:

```python
    # WP #80 Layer 2 — детектор Create-menu (Shorts/Видео/Прямой эфир/Пост).
    # Bottom-nav YT содержит элемент 'Shorts' с тем же label, что и кнопка
    # Shorts в Create-menu — поэтому одиночный матч 'Shorts' давал заход
    # в Shorts feed чужих видео (см. WP #80, 4/6 фейлов 2026-05-18).
    _CREATE_MENU_BUTTONS = (
        'Shorts', 'Short',
        'Видео', 'Video',
        'Прямой эфир', 'Live',
        'Опрос', 'Poll',
        'Пост', 'Post',
    )

    def _is_create_menu_open(self, ui_xml: str) -> bool:
        """Возвращает True если в UI dump есть ≥3 кнопок Create-menu.

        Используется в publish_youtube_short перед попыткой
        tap_element(['Shorts',...]) — гарантирует, что мы не тапнем
        в bottom-nav 'Shorts' вместо Create-menu Shorts.
        """
        if not ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        labels = set()
        for node in root.iter('node'):
            txt = (node.get('text', '') or node.get('content-desc', '')).strip()
            if not txt:
                continue
            for btn in self._CREATE_MENU_BUTTONS:
                if txt == btn:
                    labels.add(btn)
                    break
        return len(labels) >= 3
```

- [ ] **Step 3.4: Запустить — 3 теста зелёные.**

```bash
python -m pytest tests/test_yt_publisher_editor_guards.py::test_is_create_menu_open_true_on_4_buttons tests/test_yt_publisher_editor_guards.py::test_is_create_menu_open_false_on_home_feed tests/test_yt_publisher_editor_guards.py::test_is_create_menu_open_false_on_empty_or_garbage -v 2>&1 | tail -10
```

Ожидаемо: 3 passed.

- [ ] **Step 3.5: Защитить `tap_element(['Shorts',...])` в `publish_youtube_short`.**

В `publisher_youtube.py` найти блок (строки ~846-854):

```python
        # Шаг 1: пробуем выбрать "Short"/"Shorts" в меню создания.
        ui_menu = self.dump_ui()
        shorts_picked = bool(ui_menu) and self.tap_element(
            ui_menu, ['Shorts', 'Short', 'Shorts', 'Видео', 'Video'],
            clickable_only=True)
        if shorts_picked:
            log.info('  ✅ Shorts выбран из меню создания')
            time.sleep(3)
            direct_upload = True
        else:
```

Заменить на:

```python
        # Шаг 1: пробуем выбрать "Short"/"Shorts" в меню создания.
        # WP #80 Layer 2: тапаем только если на экране РЕАЛЬНО Create-menu
        # (≥3 кнопок Create). Без этого guard'а tap_element матчил bottom-nav
        # 'Shorts' и публикатор уходил в Shorts feed чужих видео.
        ui_menu = self.dump_ui()
        if ui_menu and self._is_create_menu_open(ui_menu):
            shorts_picked = self.tap_element(
                ui_menu, ['Shorts', 'Short', 'Видео', 'Video'],
                clickable_only=True,
            )
        else:
            shorts_picked = False
            self.log_event(
                'info',
                'yt_create_menu_absent_skip_tap',
                meta={'category': 'yt_create_menu_absent_skip_tap',
                      'platform': 'YouTube'},
            )
        if shorts_picked:
            log.info('  ✅ Shorts выбран из меню создания')
            time.sleep(3)
            direct_upload = True
        else:
```

- [ ] **Step 3.6: Прогнать существующие YT publisher тесты.**

```bash
python -m pytest tests/test_yt_text_fill_verification.py tests/test_yt_picker_state_guard.py tests/test_yt_picker_dismissed_recovery.py -q 2>&1 | tail -10
```

Ожидаемо: green (или известные skips).

- [ ] **Step 3.7: Commit.**

```bash
git add publisher_youtube.py tests/test_yt_publisher_editor_guards.py
git commit -m "fix(yt-publisher): _is_create_menu_open detector защищает tap_element

Раньше tap_element(['Shorts','Short','Видео','Video']) после
force-stop+launch матчил bottom-nav 'Shorts' и публикатор уходил
в Shorts feed чужих видео (4/6 фейлов 2026-05-18). Теперь тап
выполняется только если в UI dump ≥3 кнопок Create-menu, иначе
сразу падаем в Shell_UploadActivity fallback (надёжный intent).

Slayer 2/3 фикса WP #80 (yt_editor_upload_timeout)."
```

---

## Task 4: Layer 3 — `_verify_yt_editor_reached` guard

**Files:**
- Modify: `publisher_youtube.py` (новый helper + интеграция перед editor loop)
- Modify: `tests/test_yt_publisher_editor_guards.py` (добавить editor verify тесты)

- [ ] **Step 4.1: Добавить failing-тесты для editor verify.**

В конец `tests/test_yt_publisher_editor_guards.py`:

```python
# ─── Layer 3 — editor verify ────────────────────────────────────────────


def test_verify_editor_pass_on_real_editor():
    """Synthetic editor (EditText с resource-id title) → ok=True."""
    p = _yt_pub()
    xml = (FIX_ED / "editor_with_title.xml").read_text()
    p.dump_ui = MagicMock(return_value=xml)
    ok, meta = p._verify_yt_editor_reached()
    assert ok is True, f"editor должен быть распознан, meta={meta}"


def test_verify_editor_fail_on_shorts_overlay():
    """Реальный dump task 6815 (Shorts player overlay) → ok=False."""
    p = _yt_pub()
    xml = (FIX_ED / "shorts_overlay_6815.xml").read_text()
    p.dump_ui = MagicMock(return_value=xml)
    p.adb = MagicMock(return_value="topResumedActivity= ActivityRecord{... com.google.android.youtube/.HomeActivity}")
    ok, meta = p._verify_yt_editor_reached()
    assert ok is False, f"Shorts overlay не должен распознаваться как editor"
    assert "yt_editor_not_reached" in (meta.get("category") or "")


def test_verify_editor_fail_on_chrome():
    """Реальный dump task 6816 (Chrome temu.com) → ok=False."""
    p = _yt_pub()
    xml = (FIX_ED / "chrome_temu_6816.xml").read_text()
    p.dump_ui = MagicMock(return_value=xml)
    p.adb = MagicMock(return_value="topResumedActivity= ActivityRecord{... com.android.chrome/...}")
    ok, meta = p._verify_yt_editor_reached()
    assert ok is False, f"Chrome browser не должен распознаваться как editor"
    assert "yt_editor_not_reached" in (meta.get("category") or "")


def test_verify_editor_pass_on_upload_activity_in_top():
    """Если topResumedActivity содержит UploadActivity — pass даже без markers в UI."""
    p = _yt_pub()
    p.dump_ui = MagicMock(return_value="<hierarchy/>")
    p.adb = MagicMock(
        return_value="topResumedActivity= ActivityRecord{... com.google.android.youtube/.application.Shell_UploadActivity}"
    )
    ok, _ = p._verify_yt_editor_reached()
    assert ok is True
```

- [ ] **Step 4.2: Запустить — fail.**

```bash
python -m pytest tests/test_yt_publisher_editor_guards.py -k "verify_editor" -v 2>&1 | tail -15
```

Ожидаемо: 4 fails (`AttributeError: '_verify_yt_editor_reached'`).

- [ ] **Step 4.3: Добавить `_verify_yt_editor_reached` в `publisher_youtube.py`.**

Перед `def publish_youtube_short` (строка ~813) добавить:

```python
    # WP #80 Layer 3 — editor verify перед editor loop.
    _EDITOR_TEXT_MARKERS = (
        'добавьте название', 'add title',
        'добавьте описание', 'добавить описание', 'add description',
        'загрузить', 'upload',
    )
    _EDITOR_RID_SUBSTRS = ('title', 'description', 'caption', 'compose')
    _EDITOR_ACTIVITY_SUBSTRS = (
        'uploadactivity', 'shareactivity', 'composeactivity',
    )

    def _verify_yt_editor_reached(self) -> tuple:
        """Проверка что мы реально в YT editor перед началом editor loop.

        3 итерации dump_ui (~6с). Editor распознаётся по любому из:
          - EditText с resource-id, содержащим title/description/caption/compose;
          - текст 'Добавьте название'/'Загрузить'/etc;
          - topResumedActivity содержит UploadActivity/ShareActivity/ComposeActivity.

        Returns:
            (True, {})  — editor найден, продолжаем штатный loop;
            (False, meta) — editor не найден, caller возвращает False,
                            error_code=yt_editor_not_reached.
        """
        import xml.etree.ElementTree as _ET
        all_texts_last: list = []
        edit_ids_last: list = []
        top_act_last = ''
        for _ in range(3):
            ui = self.dump_ui() or ''
            try:
                root = _ET.fromstring(ui) if ui else None
            except Exception:
                root = None
            edit_ids = []
            all_texts = []
            if root is not None:
                for n in root.iter('node'):
                    txt = (n.get('text', '') or n.get('content-desc', '')).strip()
                    if txt:
                        all_texts.append(txt)
                    rid = n.get('resource-id', '') or ''
                    cls = n.get('class', '') or ''
                    if cls.endswith('EditText') and rid:
                        edit_ids.append(rid)
            all_texts_last = all_texts
            edit_ids_last = edit_ids
            # 1. EditText resource-id markers
            for rid in edit_ids:
                rid_low = rid.lower()
                if any(sub in rid_low for sub in self._EDITOR_RID_SUBSTRS):
                    return True, {}
            # 2. Text markers
            ui_low_join = '\n'.join(all_texts).lower()
            if any(m in ui_low_join for m in self._EDITOR_TEXT_MARKERS):
                # EditText neighbour не обязателен — если есть «Загрузить»/«Добавьте
                # название» в UI, скорее всего мы в editor (caption-screen).
                return True, {}
            # 3. topResumedActivity markers
            try:
                top_act_last = self.adb(
                    "dumpsys activity activities 2>/dev/null "
                    "| grep -m1 -E 'topResumedActivity|ResumedActivity'",
                    timeout=6,
                ) or ''
            except Exception:
                top_act_last = ''
            top_low = top_act_last.lower()
            if any(sub in top_low for sub in self._EDITOR_ACTIVITY_SUBSTRS):
                return True, {}
            time.sleep(2)
        meta = {
            'category': 'yt_editor_not_reached',
            'platform': 'YouTube',
            'top_activity': top_act_last.strip()[:200],
            'all_texts': all_texts_last[:10],
            'edit_fields_count': len(edit_ids_last),
        }
        self.log_event(
            'error',
            'yt_editor_not_reached',
            meta=meta,
        )
        return False, meta
```

- [ ] **Step 4.4: Запустить — 4 теста зелёные.**

```bash
python -m pytest tests/test_yt_publisher_editor_guards.py -k "verify_editor" -v 2>&1 | tail -15
```

Ожидаемо: 4 passed.

- [ ] **Step 4.5: Интегрировать guard в `publish_youtube_short` перед editor loop.**

В `publisher_youtube.py` найти (строка ~894-904):

```python
        else:
            log.info('  ✅ Shell_UploadActivity сработал — пропускаем навигацию и галерею')
            # Ждём загрузки редактора YouTube Shorts (может занять 3-5 сек)
            time.sleep(5)
            # Обрабатываем начальные диалоги (разрешения, геолокация)
            for _ in range(4):
                ui = self.dump_ui()
                if self.dismiss_location_dialog(ui): time.sleep(1); continue
                if self.tap_element(ui, ['ОК', 'OK', 'Понятно', 'Разрешить', 'Allow',
                                         'При использовании приложения']):
                    time.sleep(2)
                else:
                    break
            # Прыгаем сразу на шаг 8 (редактор)
            log.info('Проходим редактор YouTube Short (direct upload)...')
            self.set_step('YouTube: редактор (обрезка/загрузка)')
            title_filled = False
```

После `self.set_step('YouTube: редактор (обрезка/загрузка)')` и перед `title_filled = False` вставить:

```python
            # WP #80 Layer 3 — verify что мы реально в editor.
            # Без этого guard editor loop 25 шагов искал «Загрузить» в
            # Shorts feed чужих видео / Chrome — 5-минутный timeout с
            # бесполезным AI Unstuck (см. WP #80 evidence).
            _ed_ok, _ed_meta = self._verify_yt_editor_reached()
            if not _ed_ok:
                log.error(
                    f'YouTube: editor не достигнут после direct_upload — '
                    f'fail fast. meta={_ed_meta}'
                )
                return False
```

- [ ] **Step 4.6: Полный прогон новых тестов + сэйнити.**

```bash
python -m pytest tests/test_yt_publisher_editor_guards.py tests/test_yt_create_menu_strict_verify.py tests/test_yt_post_switch_verify.py tests/test_yt_text_fill_verification.py tests/test_yt_picker_state_guard.py tests/test_yt_picker_dismissed_recovery.py -q 2>&1 | tail -15
```

Ожидаемо: всё green (новые ~7 passed, существующие как в baseline).

- [ ] **Step 4.7: Commit.**

```bash
git add publisher_youtube.py tests/test_yt_publisher_editor_guards.py
git commit -m "fix(yt-publisher): _verify_yt_editor_reached guard перед editor loop

3-итерационный verify (dump_ui markers + topResumedActivity) перед
25-шаговым editor loop. Если editor не найден — fail fast с
error_code=yt_editor_not_reached вместо 5-минутного yt_editor_upload_timeout
+ бесполезных AI Unstuck попыток.

Slayer 3/3 фикса WP #80 (yt_editor_upload_timeout)."
```

---

## Task 5: Push + PR + smoke + live verify

**Files:** workspace shell, GitHub

- [ ] **Step 5.1: Полный pytest perimeter check.**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python -m pytest tests/ -q --ignore=tests/integration 2>&1 | tail -20
```

Ожидаемо: no NEW failures относительно baseline на Step 0.2. Если есть — диагностировать причину, чинить, добавить regression-тест.

- [ ] **Step 5.2: Push в `GenGo2/delivery-contenthunter`.**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git push -u origin yt-editor-upload-timeout-fix-2026-05-18
```

Note: post-commit hook автопушит main → этот hook НЕ должен мешать пушу feature ветки. Если на ветке `yt-editor-upload-timeout-fix-2026-05-18` нет force-push — всё ок (см. memory `feedback_subagent_force_push_risk`: NEVER --force на main).

- [ ] **Step 5.3: Открыть PR.**

```bash
source ~/secrets/github-gengo2.env
gh pr create --repo GenGo2/delivery-contenthunter \
  --base main \
  --head yt-editor-upload-timeout-fix-2026-05-18 \
  --title "fix(yt): устранение yt_editor_upload_timeout (3 слоя guard'ов) — WP #80" \
  --body "$(cat <<'EOF'
## Что было не так
За 2026-05-18 6/8 YT-фейлов (75%) свалились с `yt_editor_upload_timeout`. Все 6 — на разных устройствах/аккаунтах: switcher молча отдавал управление публикатору при отсутствии Create-menu, дальше `tap_element(['Shorts',...])` ловил bottom-nav `Shorts`, публикатор уходил в Shorts feed чужих видео (в 2/6 — в Chrome через рекламные dialog'и), и 25 шагов editor loop искали «Загрузить» в чужом UI.

## Что сделано (3 слоя fail-safe)
- **Layer 1 — switcher (`account_switcher.py`):** новый opt-in `strict_verify=True` в `_tap_plus_and_verify`. Если на yt_6_create_menu ни один verify-trigger не сматчился — возвращаем `_fail` со step `yt_6_create_menu_no_triggers` → `error_code='yt_create_menu_not_reached'`. Дополнительно убран `'Short'` из YT `editor_triggers` (матчился на bottom-nav `Shorts` и давал false-positive). IG/TT не затрагиваются (strict_verify=False по умолчанию).
- **Layer 2 — `_is_create_menu_open` (`publisher_youtube.py`):** детектор Create-menu (требует ≥3 кнопок из {Shorts, Видео, Прямой эфир, Пост, ...}). `tap_element(['Shorts',...])` вызывается ТОЛЬКО при `_is_create_menu_open=True`, иначе сразу падаем в Shell_UploadActivity fallback (надёжнее — explicit intent).
- **Layer 3 — `_verify_yt_editor_reached` (`publisher_youtube.py`):** 3-итерационный guard перед 25-шаговым editor loop. Editor распознаётся по EditText resource-id (`title`/`description`/`caption`/`compose`), текст-markers (`Загрузить`/`Добавьте название`), либо `topResumedActivity` ∈ {UploadActivity, ShareActivity, ComposeActivity}. Если не найден — fail fast с `error_code='yt_editor_not_reached'` вместо 5-минутного timeout.

## Тесты
- `tests/test_yt_create_menu_strict_verify.py` — 4 теста на Layer 1 (strict_verify pass/fail + IG/TT не затронуты + cfg чистка).
- `tests/test_yt_publisher_editor_guards.py` — 7 тестов на Layer 2 + Layer 3 (real-life UI dumps task 6815/6816 как фикстуры).

## Test plan
- [ ] CI green
- [ ] Smoke testbench (phone #19): 1-2 публикации YT через farming-testbench scheduler
- [ ] Live verify 24h: `SELECT error_code, COUNT(*) FROM publish_tasks WHERE platform='YouTube' AND status='failed' AND started_at >= NOW()-INTERVAL '24 hours' GROUP BY 1 ORDER BY 2 DESC` — `yt_editor_upload_timeout` должен упасть до 0 (или почти); ожидаются новые `yt_create_menu_not_reached`/`yt_editor_not_reached` как замена.

OpenProject WP #80 · Spec: `docs/superpowers/specs/2026-05-18-yt-editor-upload-timeout-design.md` (контент-хантер репо)
EOF
)"
```

- [ ] **Step 5.4: Дождаться CI/проверить статус.**

```bash
gh pr checks --repo GenGo2/delivery-contenthunter --watch
```

Ожидаемо: green. Если red — фиксить, добавить regression-тест.

- [ ] **Step 5.5: Live smoke на testbench.**

После merge'а — re-queue 2-3 свежих failed YT-tasks через `publish_queue`:

```sql
-- pick 2 свежих failed YT не на testbench
SELECT pt.id, pq.id AS queue_id
FROM publish_tasks pt
JOIN publish_queue pq ON pq.publish_task_id = pt.id
WHERE pt.platform='YouTube'
  AND pt.status='failed'
  AND pt.error_code='yt_editor_upload_timeout'
  AND pt.started_at::date >= '2026-05-18'
ORDER BY pt.started_at DESC LIMIT 3;

-- (вручную убедившись что задачи актуальны и пользователь даёт ок)
UPDATE publish_queue SET status='pending', publish_task_id=NULL
WHERE id IN (...);
```

Через ~5-30 мин (зависит от scheduler tick) проверить новые `publish_tasks` — error_code должен быть либо `done` (исправление сработало), либо новый точный `yt_create_menu_not_reached`/`yt_editor_not_reached` (исправление сработало, но root cause глубже).

- [ ] **Step 5.6: Обновить WP #80 в OpenProject (status='Разработан') с комментарием SHIPPED + ссылкой на PR.**

```bash
source ~/secrets/openproject.env
PR_URL="<paste PR URL after merge>"
# (см. memory openproject_practice: Что было не так → Что сделано → Что осталось)
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" -H "Content-Type: application/json" \
  -X POST "$OPENPROJECT_URL/api/v3/work_packages/80/activities" \
  -d "{\"comment\":{\"raw\":\"## Что сделано\\nPR $PR_URL смерджен. 3 слоя guard'ов: switcher strict_verify, _is_create_menu_open detector, _verify_yt_editor_reached перед editor loop.\\n\\n## Что осталось\\nLive verify 24h: распределение error_code на YT failed.\"}}"
```

- [ ] **Step 5.7: Обновить docs/backlog в контент-хантер репо.**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/yt-fails-triage-2026-05-18
# найти/обновить backlog раздел: SHIPPED 2026-05-18 PR #... (WP #80)
```

(если backlog уже trackит WP #80 — добавить SHIPPED-строку; если нет — пропустить).

---

## Out of scope (отдельные задачи)

- AI Unstuck guard для YT editor flow (запрет тапов в Search/Voice) — backlog.
- Recovery flow «вернуться в editor если зашли в Shorts feed» — нужна live-evidence о feasibility.
- Regression corpus для publisher_youtube (фикстур in-tree pytest достаточно для текущего scope).
