# WP#225 — IG picker reel-drift escape: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить ложно-реальный `ig_picker_sheet_not_opened`, когда «профиль» задрейфовал в рилс (сетка Reels от верха / открытый рилс-пост) и слепой fallback-тап `_tap_profile_header` уводит глубже вместо открытия sheet выбора аккаунта.

**Architecture:** Подход 1 (профилактика + escape). Новый pure-детектор `_ig_on_profile_reel_drift` (позиционный: грид в зоне хедера без username-тайтла ИЛИ маркеры рилс-поста). Новая escape-ветка в reguard-цикле `_ig_guard_picker_foreground` (BACK + ре-нав профиль-таба, по образцу WP#219). Подавление слепого fallback-тапа в `_tap_profile_header`, когда зона хедера занята рилс-гридом. Всё за kill-switch `IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED` (default ON). PR#150-poll не трогаем.

**Tech Stack:** Python 3, `pytest`, `unittest.mock`. Репо `delivery-contenthunter`, файл `account_switcher.py`. Прод-деплой = `git pull` в autowarm (publisher per-task spawn, PM2-restart не нужен).

**Окружение и изоляция:** код-правки делать в **изолированном worktree** `delivery-contenthunter` на отдельной ветке (общий checkout = гонка с параллельными сессиями, см. память `feedback_shared_worktree_checkout_race`). Спека: `docs/superpowers/specs/2026-06-04-wp225-ig-picker-reel-drift-design.md`.

---

## File Structure

- **Modify** `account_switcher.py`:
  - kill-switch helper `_ig_picker_reel_drift_escape_enabled()` — рядом с `_ig_picker_sheet_recheck_enabled` (~стр. 389, module-level).
  - regex `_IG_REEL_GRID_DESC_RE` + classmethods `_ig_header_zone_has_reel_grid`, `_ig_on_profile_reel_drift` — после `_ig_on_audio_page` (~стр. 2951).
  - escape-`elif` в `_ig_guard_picker_foreground` — после audio-page-ветки (~стр. 2275).
  - подавление слепого тапа в `_tap_profile_header` (~стр. 5402-5406).
- **Create** `tests/test_account_switcher_ig_reel_drift_escape.py` — все юниты (kill-switch, pure-детектор, escape-интеграция, suppression). Зеркало `tests/test_account_switcher_ig_audio_page_escape.py`.

**Якоря (текущий прод-код для ориентира):**
- `_ig_picker_audio_escape_enabled` — стр. 367-375; `_ig_picker_sheet_recheck_enabled` — стр. 378-389.
- audio-escape `elif` в reguard — стр. 2261-2275; сразу после него `elements_rg = self._read_screen_hybrid(...)` — стр. 2277.
- `_ig_on_audio_page` — стр. 2934-2951.
- `_tap_profile_header` — стр. 5386-5406 (слепой fallback — стр. 5402-5406).
- `header_y_max` приходит в `_ig_guard_picker_foreground(self, cfg, header_y_max)` (стр. 2101); для IG `cfg['profile_title_header_y_range'] = (120, 260)` → `header_y_max = 260`.

---

## Task 1: Kill-switch helper

**Files:**
- Modify: `account_switcher.py` (после `_ig_picker_sheet_recheck_enabled`, ~стр. 389)
- Test: `tests/test_account_switcher_ig_reel_drift_escape.py` (создать)

- [ ] **Step 1: Write failing test (создаёт новый тест-файл с шапкой и импортом)**

```python
"""WP#225 follow-up — escape с рилс-дрейфа в sheet-reguard цикле IG-свитчера.

Живые рецидивы ig_picker_sheet_not_opened после деплоя PR#150 (tasks
15234 Lexis Voice / 15049 Splus / 15071 тест): «профиль» показывает сетку
Reels от верха (хедер схлопнут, username-тайтла нет) → _tap_profile_header
не находит username → слепой fallback-тап (540,180) попадает в ячейку
рилса → дрейф в рилс-пост (row_feed_profile_header), у которого нет
escape-ветки → исчерпание range(2) → ig_picker_sheet_not_opened.

Фикс за kill-switch IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED (default ON):
  • pure-детектор _ig_on_profile_reel_drift(xml, header_y_max);
  • reguard escape (BACK + bottom-nav профиль) при fg=IG на рилс-дрейфе;
  • подавление слепого fallback-тапа _tap_profile_header на грид-в-хедере.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from account_switcher import (  # noqa: E402
    AccountSwitcher,
    UI_CONSTANTS,
    parse_ui_dump,
    _ig_picker_reel_drift_escape_enabled,
)

IG_PKG = 'com.instagram.android'


def test_reel_drift_escape_kill_switch_default_on(monkeypatch):
    monkeypatch.delenv('IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED', raising=False)
    assert _ig_picker_reel_drift_escape_enabled() is True


def test_reel_drift_escape_kill_switch_off(monkeypatch):
    monkeypatch.setenv('IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED', '0')
    assert _ig_picker_reel_drift_escape_enabled() is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd <worktree> && python -m pytest tests/test_account_switcher_ig_reel_drift_escape.py -v`
Expected: FAIL — `ImportError: cannot import name '_ig_picker_reel_drift_escape_enabled'`

- [ ] **Step 3: Add the kill-switch helper**

В `account_switcher.py` сразу после функции `_ig_picker_sheet_recheck_enabled` (после её `return ...` строки, ~стр. 389) добавить:

```python
def _ig_picker_reel_drift_escape_enabled() -> bool:
    """[WP #225 follow-up] Kill-switch для escape с рилс-дрейфа в sheet-reguard
    + подавления слепого fallback-тапа _tap_profile_header.

    Default ON. `IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED=0` → reguard-цикл НЕ
    распознаёт «профиль задрейфовал в рилс» (сетка Reels от верха при
    схлопнутом хедере / открытый рилс-пост `row_feed_profile_header`) и
    `_tap_profile_header` снова делает слепой fallback-тап (540,180) в ячейку
    рилс-грида → дрейф глубже → ложный `ig_picker_sheet_not_opened`,
    `попыток=1` (живые рецидивы после PR#150: tasks 15234/15049/15071,
    IG fail-триаж 2026-06-04).
    """
    return os.environ.get('IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED', '1') != '0'
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_account_switcher_ig_reel_drift_escape.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_ig_reel_drift_escape.py
git commit -m "feat(wp225): kill-switch IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED (default ON)"
```

---

## Task 2: Pure-детектор рилс-дрейфа

**Files:**
- Modify: `account_switcher.py` (после `_ig_on_audio_page`, ~стр. 2951)
- Test: `tests/test_account_switcher_ig_reel_drift_escape.py`

- [ ] **Step 1: Write failing tests (добавить XML-фикстуры + тесты детектора в конец тест-файла)**

```python
# ─── XML-фикстуры (header_y_max=260 для IG) ─────────────────────────────────

# Форма A — сетка Reels от верха (task 15234 attempt0): грид-ячейки с top<260,
# нет username-тайтла (единственный текст — "4"). «Ivanov»/«Expert» сидят ТОЛЬКО
# внутри content-desc грид-ячейки (их _looks_like_username ложно бы счёл
# username'ом — детектор обязан исключать сами грид-ячейки).
_REEL_GRID_TOP_XML = (
    '<hierarchy rotation="0"><node package="com.instagram.android" bounds="[0,0][1080,2400]">'
    '<node text="4" bounds="[40,40][120,100]"/>'
    '<node content-desc="Видео Reels Ivanov Expert в строке 1, столбце 1" bounds="[0,102][356,577]"/>'
    '<node content-desc="Видео Reels Ivanov Expert в строке 1, столбце 2" bounds="[362,102][718,577]"/>'
    '<node content-desc="Видео Reels Ivanov Expert в строке 1, столбце 3" bounds="[724,102][1080,577]"/>'
    '<node resource-id="com.instagram.android:id/profile_tab" bounds="[864,2200][1080,2400]"/>'
    '</node></hierarchy>'
)
# Форма B — открыт рилс-пост на профиле (task 15234: оба маркера).
_REEL_POST_XML = (
    '<hierarchy rotation="0"><node package="com.instagram.android" bounds="[0,0][1080,2400]">'
    '<node resource-id="com.instagram.android:id/row_feed_profile_header" bounds="[0,80][1080,200]"/>'
    '<node text="Продвигать публикацию" bounds="[40,1900][800,1960]"/>'
    '<node resource-id="com.instagram.android:id/feed_preview_bottom_cta_container" bounds="[0,2000][1080,2100]"/>'
    '</node></hierarchy>'
)
# Форма B — рилс-пост ТОЛЬКО с row_feed_profile_header (task 15049: cta-контейнера
# нет) → детект обязан быть OR, а не AND.
_REEL_POST_NO_CTA_XML = (
    '<hierarchy rotation="0"><node package="com.instagram.android" bounds="[0,0][1080,2400]">'
    '<node resource-id="com.instagram.android:id/row_feed_profile_header" bounds="[0,80][1080,200]"/>'
    '<node text="pisca.who · Оригинальное аудио" bounds="[40,210][800,270]"/>'
    '</node></hierarchy>'
)
# Негатив — нормальный профиль: username-тайтл в хедере (y<260) + грид НИЖЕ
# хедера (top=820 >= 260) → не дрейф.
_NORMAL_PROFILE_XML = (
    '<hierarchy rotation="0"><node package="com.instagram.android" bounds="[0,0][1080,2400]">'
    '<node resource-id="com.instagram.android:id/action_bar_title" text="relisssme" bounds="[0,120][600,200]"/>'
    '<node content-desc="Видео Reels relisssme в строке 1, столбце 1" bounds="[0,820][356,1200]"/>'
    '<node resource-id="com.instagram.android:id/profile_tab" bounds="[864,2200][1080,2400]"/>'
    '</node></hierarchy>'
)
# Негатив — sheet выбора аккаунта (приоритет: со sheet escape не делаем).
_SHEET_XML = (
    '<hierarchy><node package="com.instagram.android">'
    '<node resource-id="com.instagram.android:id/account_switcher_recycler">'
    '<node text="relisssme"/><node text="clickpay_world"/>'
    '</node></node></hierarchy>'
)
# Edge — грид в зоне хедера, НО username-тайтл присутствует (схлопнутый app-bar
# с username) → можно тапнуть шапку → НЕ дрейф.
_REEL_GRID_TOP_WITH_USERNAME_XML = (
    '<hierarchy rotation="0"><node package="com.instagram.android" bounds="[0,0][1080,2400]">'
    '<node resource-id="com.instagram.android:id/action_bar_title" text="relisssme" bounds="[0,120][600,200]"/>'
    '<node content-desc="Видео Reels relisssme в строке 1, столбце 1" bounds="[0,210][356,577]"/>'
    '</node></hierarchy>'
)

HMAX = 260  # IG: cfg['profile_title_header_y_range'][1]


# ─── pure-детектор _ig_on_profile_reel_drift ────────────────────────────────

def test_reel_drift_detector_positive_grid_from_top():
    assert AccountSwitcher._ig_on_profile_reel_drift(_REEL_GRID_TOP_XML, HMAX) is True


def test_reel_drift_detector_positive_reel_post_both_markers():
    assert AccountSwitcher._ig_on_profile_reel_drift(_REEL_POST_XML, HMAX) is True


def test_reel_drift_detector_positive_reel_post_only_row_header():
    # OR-условие: один row_feed_profile_header достаточно (task 15049)
    assert AccountSwitcher._ig_on_profile_reel_drift(_REEL_POST_NO_CTA_XML, HMAX) is True


def test_reel_drift_detector_negative_normal_profile():
    assert AccountSwitcher._ig_on_profile_reel_drift(_NORMAL_PROFILE_XML, HMAX) is False


def test_reel_drift_detector_negative_sheet_priority():
    assert AccountSwitcher._ig_on_profile_reel_drift(_SHEET_XML, HMAX) is False


def test_reel_drift_detector_negative_grid_top_with_username():
    # грид в хедере, но есть username-тайтл (не грид-ячейка) → не дрейф
    assert AccountSwitcher._ig_on_profile_reel_drift(_REEL_GRID_TOP_WITH_USERNAME_XML, HMAX) is False


def test_reel_drift_detector_negative_empty():
    assert AccountSwitcher._ig_on_profile_reel_drift('', HMAX) is False


def test_header_zone_has_reel_grid_positive():
    els = parse_ui_dump(_REEL_GRID_TOP_XML)
    assert AccountSwitcher._ig_header_zone_has_reel_grid(els, HMAX) is True


def test_header_zone_has_reel_grid_negative_grid_below_header():
    els = parse_ui_dump(_NORMAL_PROFILE_XML)
    assert AccountSwitcher._ig_header_zone_has_reel_grid(els, HMAX) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_account_switcher_ig_reel_drift_escape.py -v`
Expected: FAIL — `AttributeError: type object 'AccountSwitcher' has no attribute '_ig_on_profile_reel_drift'`

- [ ] **Step 3: Add the detector code**

В `account_switcher.py` сразу после метода `_ig_on_audio_page` (после его `return False`, ~стр. 2951) добавить:

```python
    # [WP#225 follow-up] Рилс-дрейф профиля. Живые рецидивы после PR#150
    # (tasks 15234 Lexis Voice / 15049 Splus): «профиль» показывает сетку Reels
    # от самого верха (хедер схлопнут, username-тайтла нет) → _tap_profile_header
    # слепо тапает (540,180) в ячейку грида → открывается рилс-пост
    # (row_feed_profile_header) → дрейф без escape. Грид-ячейка несёт
    # content-desc «Видео Reels … в строке N, столбце M» (ru) / «… in row N,
    # column M» (en) — устойчивый позиционный маркер сетки.
    _IG_REEL_GRID_DESC_RE = re.compile(
        r'(в строке\s*\d+,?\s*столбце\s*\d+|in row\s*\d+,?\s*column\s*\d+)',
        re.IGNORECASE,
    )
    # Маркеры открытого рилс-поста на профиле (feed-просмотр). OR: cta-контейнер
    # есть не всегда (task 15049 — только row_feed_profile_header).
    _IG_REEL_POST_MARKERS = (
        'com.instagram.android:id/row_feed_profile_header',
        'com.instagram.android:id/feed_preview_bottom_cta_container',
    )

    @classmethod
    def _ig_header_zone_has_reel_grid(cls, elements: list, header_y_max: int) -> bool:
        """[WP#225 follow-up] True, если в зоне хедера (`bounds.top < header_y_max`)
        есть ячейка рилс-грида (`content-desc` матчит `_IG_REEL_GRID_DESC_RE`).

        На нормальном профиле грид всегда НИЖЕ хедера/био (`top > header_y_max`),
        поэтому грид-в-зоне-хедера = схлопнутый хедер / дрейф. Pure над
        списком `UIElement`."""
        return any(
            el.bounds[1] < header_y_max
            and cls._IG_REEL_GRID_DESC_RE.search(el.content_desc or '')
            for el in elements
        )

    @classmethod
    def _ig_on_profile_reel_drift(cls, xml: Optional[str], header_y_max: int) -> bool:
        """[WP#225 follow-up] True, если профиль задрейфовал в рилс — две формы:
          • открыт рилс-пост (маркер `row_feed_profile_header` ИЛИ
            `feed_preview_bottom_cta_container`);
          • сетка Reels от верха (грид-ячейка с `top < header_y_max`) ПРИ
            отсутствии username-тайтла в зоне хедера.

        Со sheet escape НЕ делаем (приоритет sheet — как `_ig_on_audio_page`).
        Грид-ячейки исключаются из поиска username-тайтла: их content-desc
        («Видео Reels Ivanov Expert …») содержит латинские токены, которые
        `_looks_like_username` ложно счёл бы username'ом → false-negative.
        Pure-функция над xml."""
        if not xml:
            return False
        if cls._ig_on_account_switcher_sheet(xml):
            return False
        # Форма B: открытый рилс-пост (resource-id маркеры, OR).
        if any(m in xml for m in cls._IG_REEL_POST_MARKERS):
            return True
        # Форма A: сетка Reels от верха + нет username-тайтла.
        elements = parse_ui_dump(xml)
        if not cls._ig_header_zone_has_reel_grid(elements, header_y_max):
            return False
        for el in elements:
            if el.bounds[1] >= header_y_max:
                continue
            if cls._IG_REEL_GRID_DESC_RE.search(el.content_desc or ''):
                continue  # сама грид-ячейка — не тайтл
            for raw in (el.text, el.content_desc):
                if not raw:
                    continue
                for tok in re.split(r'\s+|\n', raw):
                    if _looks_like_username(tok):
                        return False  # есть реальный username-тайтл → не дрейф
        return True
```

> Зависимости уже импортированы в модуле: `re`, `Optional` (typing), `parse_ui_dump`, `_looks_like_username`, `_ig_on_account_switcher_sheet` (classmethod). Проверить наличие `Optional` в импортах (`from typing import Optional`) — он используется в соседних сигнатурах, так что есть.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_account_switcher_ig_reel_drift_escape.py -v`
Expected: PASS (11 passed суммарно с Task 1)

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_ig_reel_drift_escape.py
git commit -m "feat(wp225): pure-детектор _ig_on_profile_reel_drift (грид-от-верха + рилс-пост)"
```

---

## Task 3: Escape-ветка в reguard-цикле

**Files:**
- Modify: `account_switcher.py` `_ig_guard_picker_foreground` (после audio-page elif, ~стр. 2275)
- Test: `tests/test_account_switcher_ig_reel_drift_escape.py`

- [ ] **Step 1: Write failing tests (добавить мок-харнес + интеграционные тесты в конец тест-файла)**

```python
# ─── мок-харнес (зеркало test_account_switcher_ig_audio_page_escape.py) ─────

def _make_switcher():
    publisher = MagicMock()
    publisher.platform = 'Instagram'
    publisher.adb = MagicMock(return_value='')
    publisher.dump_ui = MagicMock(return_value='')
    publisher.adb_tap = MagicMock()
    publisher.tap_element = MagicMock(return_value=True)
    log_calls: list[dict] = []

    def _capture_log(event_type, message, meta=None):
        log_calls.append({'event_type': event_type, 'message': message, 'meta': meta or {}})

    publisher.log_event.side_effect = _capture_log
    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    sw._maybe_screenshot = MagicMock()
    return sw, log_calls


def _has_category(log_calls, category):
    return any(c['meta'].get('category') == category for c in log_calls)


# ─── escape-ветка: рилс-дрейф → BACK + bottom-nav профиль → sheet ───────────

def test_loop_escapes_reel_drift_then_sheet(monkeypatch):
    monkeypatch.setenv('IG_PICKER_SHEET_GUARD_ENABLED', '1')
    monkeypatch.setenv('IG_PICKER_REGUARD_HARDEN_ENABLED', '1')
    monkeypatch.setenv('IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED', '1')
    monkeypatch.setenv('IG_PICKER_SHEET_RECHECK_ENABLED', '1')
    sw, log_calls = _make_switcher()
    sw._reliable_foreground_pkg = MagicMock(return_value=IG_PKG)
    # dump0 (top-of-loop) = рилс-дрейф → escape; dump1 (poll) = sheet
    sw.p.dump_ui = MagicMock(side_effect=[_REEL_GRID_TOP_XML, _SHEET_XML])
    sw._go_to_profile_tab = MagicMock()
    sw._read_screen_hybrid = MagicMock(return_value=([], 'uiautomator', ''))
    sw._tap_profile_header = MagicMock(return_value=True)
    cfg = UI_CONSTANTS['Instagram']
    result = sw._ig_guard_picker_foreground(cfg, cfg['profile_title_header_y_range'][1])
    assert result is True
    back_calls = [c for c in sw.p.adb.call_args_list
                  if c.args and 'BACK' in str(c.args[0]).upper()]
    assert back_calls, 'escape должен послать KEYCODE_BACK'
    sw._go_to_profile_tab.assert_called()
    assert _has_category(log_calls, 'ig_picker_reguard_reel_drift_escaped')


def test_loop_reel_drift_escape_inactive_when_off(monkeypatch):
    monkeypatch.setenv('IG_PICKER_SHEET_GUARD_ENABLED', '1')
    monkeypatch.setenv('IG_PICKER_REGUARD_HARDEN_ENABLED', '1')
    monkeypatch.setenv('IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED', '0')
    monkeypatch.setenv('IG_PICKER_SHEET_RECHECK_ENABLED', '1')
    sw, log_calls = _make_switcher()
    sw._reliable_foreground_pkg = MagicMock(return_value=IG_PKG)
    sw.p.dump_ui = MagicMock(return_value=_REEL_GRID_TOP_XML)  # всегда дрейф
    sw._go_to_profile_tab = MagicMock()
    sw._read_screen_hybrid = MagicMock(return_value=([], 'uiautomator', ''))
    sw._tap_profile_header = MagicMock(return_value=True)
    cfg = UI_CONSTANTS['Instagram']
    result = sw._ig_guard_picker_foreground(cfg, cfg['profile_title_header_y_range'][1])
    assert result is False
    assert not _has_category(log_calls, 'ig_picker_reguard_reel_drift_escaped')
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_account_switcher_ig_reel_drift_escape.py::test_loop_escapes_reel_drift_then_sheet -v`
Expected: FAIL — категория `ig_picker_reguard_reel_drift_escaped` не логируется (escape-ветки ещё нет), `assert _has_category(...)` падает.

- [ ] **Step 3: Add escape branch**

В `account_switcher.py`, в `_ig_guard_picker_foreground`, **сразу после** закрывающего блока audio-page-ветки (после `self._go_to_profile_tab(cfg, 'ig_2_profile_tab_audio_escape')` + `time.sleep(POST_TAP_WAIT_S)`, ~стр. 2275) и **перед** строкой `elements_rg, _, _ = self._read_screen_hybrid(` (~стр. 2277) добавить новый `elif` (он принадлежит той же `if/elif`-цепочке внутри `if harden:`):

```python
                # [WP#225 follow-up] fg=IG, но профиль задрейфовал в рилс:
                # сетка Reels от верха (хедер схлопнут, username-тайтла нет) или
                # открытый рилс-пост (row_feed_profile_header). Слепой re-tap
                # _tap_profile_header попадает в ячейку грида → дрейф глубже →
                # ig_picker_sheet_not_opened (tasks 15234 Lexis Voice / 15049
                # Splus, пост-деплой PR#150). Escape: BACK (выход из рилс-поста)
                # + bottom-nav профиль (скролл-в-верх → username-тайтл
                # восстанавливается). Стоит ПОСЛЕ overlay/audio веток —
                # их кейсы имеют приоритет и не пересекаются по маркерам.
                elif (_ig_picker_reel_drift_escape_enabled()
                      and self._ig_on_profile_reel_drift(xml, header_y_max)):
                    self.p.log_event(
                        'warning',
                        f'ig_picker_reguard_reel_drift_escaped: профиль '
                        f'задрейфовал в рилс (грид-от-верха / рилс-пост) '
                        f'(attempt {attempt}) — BACK + bottom-nav профиль',
                        meta={'category': 'ig_picker_reguard_reel_drift_escaped',
                              'step': 'ig_4_pick_account',
                              'attempt': attempt},
                    )
                    self.p.adb('input keyevent KEYCODE_BACK')
                    time.sleep(POST_TAP_WAIT_S)
                    self._go_to_profile_tab(cfg, 'ig_2_profile_tab_reel_drift_escape')
                    time.sleep(POST_TAP_WAIT_S)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_account_switcher_ig_reel_drift_escape.py -v`
Expected: PASS (все тесты, включая 2 интеграционных)

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_ig_reel_drift_escape.py
git commit -m "feat(wp225): escape-ветка рилс-дрейфа в reguard-цикле (BACK + ре-нав)"
```

---

## Task 4: Подавление слепого fallback-тапа

**Files:**
- Modify: `account_switcher.py` `_tap_profile_header` (~стр. 5402-5406)
- Test: `tests/test_account_switcher_ig_reel_drift_escape.py`

- [ ] **Step 1: Write failing tests (добавить + новую фикстуру в конец тест-файла)**

```python
# Профиль без распознаваемого username и БЕЗ грида в зоне хедера → легаси
# слепой fallback-тап должен сохраниться.
_PROFILE_NO_USERNAME_XML = (
    '<hierarchy rotation="0"><node package="com.instagram.android" bounds="[0,0][1080,2400]">'
    '<node text="Публикации" bounds="[40,300][300,360]"/>'
    '<node resource-id="com.instagram.android:id/profile_tab" bounds="[864,2200][1080,2400]"/>'
    '</node></hierarchy>'
)


def test_tap_profile_header_suppresses_blind_tap_on_reel_grid(monkeypatch):
    monkeypatch.setenv('IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED', '1')
    sw, log_calls = _make_switcher()
    elements = parse_ui_dump(_REEL_GRID_TOP_XML)
    res = sw._tap_profile_header(elements, HMAX, 'step', fallback_coords=(540, 180))
    assert res is False
    sw.p.adb_tap.assert_not_called()
    assert _has_category(log_calls, 'ig_picker_header_blind_tap_suppressed')


def test_tap_profile_header_blind_fallback_on_normal_profile(monkeypatch):
    monkeypatch.setenv('IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED', '1')
    sw, _ = _make_switcher()
    elements = parse_ui_dump(_PROFILE_NO_USERNAME_XML)
    res = sw._tap_profile_header(elements, HMAX, 'step', fallback_coords=(540, 180))
    assert res is True
    sw.p.adb_tap.assert_called_with(540, 180)


def test_tap_profile_header_blind_fallback_when_switch_off(monkeypatch):
    monkeypatch.setenv('IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED', '0')
    sw, _ = _make_switcher()
    elements = parse_ui_dump(_REEL_GRID_TOP_XML)  # грид в хедере
    res = sw._tap_profile_header(elements, HMAX, 'step', fallback_coords=(540, 180))
    assert res is True  # kill-switch off → легаси слепой тап не подавлён
    sw.p.adb_tap.assert_called_with(540, 180)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_account_switcher_ig_reel_drift_escape.py::test_tap_profile_header_suppresses_blind_tap_on_reel_grid -v`
Expected: FAIL — `adb_tap` всё-таки вызван (подавления нет), `assert res is False` падает.

- [ ] **Step 3: Add suppression in `_tap_profile_header`**

В `account_switcher.py` заменить хвост `_tap_profile_header` (текущие строки 5402-5406):

```python
        log.info(f'[switcher] {step}: header tap via fallback {fallback_coords}')
        self.p.adb_tap(*fallback_coords)
        self._save_dump(step, self.p.dump_ui(retries=1))
        self._maybe_screenshot(step)
        return True
```

на:

```python
        log.info(f'[switcher] {step}: header tap via fallback {fallback_coords}')
        # [WP#225 follow-up] Не тапать вслепую, если зона хедера занята рилс-
        # гридом (хедер схлопнут / профиль задрейфовал): (540,180) попадает в
        # ячейку рилса → дрейф в рилс-пост → ig_picker_sheet_not_opened (tasks
        # 15234 Lexis Voice / 15049 Splus). Честно возвращаем False — caller
        # прекращает без «успешного» дрейфа. На нормальном профиле (грида в
        # зоне хедера нет) слепой fallback сохраняется без изменений.
        if (_ig_picker_reel_drift_escape_enabled()
                and self._ig_header_zone_has_reel_grid(elements, header_y_max)):
            self.p.log_event(
                'warning',
                f'ig_picker_header_blind_tap_suppressed: зона хедера занята '
                f'рилс-гридом ({step}) — слепой fallback-тап подавлён',
                meta={'category': 'ig_picker_header_blind_tap_suppressed',
                      'step': step},
            )
            return False
        self.p.adb_tap(*fallback_coords)
        self._save_dump(step, self.p.dump_ui(retries=1))
        self._maybe_screenshot(step)
        return True
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_account_switcher_ig_reel_drift_escape.py -v`
Expected: PASS (все тесты файла)

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher_ig_reel_drift_escape.py
git commit -m "feat(wp225): подавить слепой fallback-тап _tap_profile_header на грид-в-хедере"
```

---

## Task 5: Регрессия и финальная проверка

**Files:** —

- [ ] **Step 1: Прогнать весь набор switcher-тестов**

Run:
```bash
python -m pytest tests/test_account_switcher.py \
  tests/test_account_switcher_ig_audio_page_escape.py \
  tests/test_account_switcher_ig_picker_fg_guard.py \
  tests/test_account_switcher_ig_picker_sheet_recheck.py \
  tests/test_account_switcher_ig_reguard_harden.py \
  tests/test_account_switcher_modal_dismiss.py \
  tests/test_account_switcher_ig_reel_drift_escape.py -v
```
Expected: все PASS. Особое внимание — audio/overlay/fg-guard escape-тесты зелёные (новая ветка стоит ПОСЛЕ них и не перехватывает их кейсы).

- [ ] **Step 2: Проверить, что новая ветка не сломала существующий `_tap_profile_header`**

Run: `python -m pytest tests/ -k "tap_profile_header or profile_header" -v`
Expected: все PASS (включая существующие позитивные username-тесты).

- [ ] **Step 3: Грубая проверка на реальной фикстуре (sanity, опционально)**

Скачать дамп task 15234 `ig_4_sheet_reguard_0` (S3-URL из events) и убедиться, что детектор True:
```bash
python -c "
from account_switcher import AccountSwitcher
xml = open('/tmp/p0.xml').read()  # дамп 15234 ig_4_sheet_reguard_0
print('reel_drift:', AccountSwitcher._ig_on_profile_reel_drift(xml, 260))"
```
Expected: `reel_drift: True`

- [ ] **Step 4: Финальный коммит-нет — всё уже закоммичено по задачам**

Проверить `git log --oneline -5` — 4 фичевых коммита (Task 1-4) на ветке.

---

## Self-Review (выполнено при написании плана)

**Spec coverage:**
- §3.1 детектор `_ig_on_profile_reel_drift` (+ `_ig_header_zone_has_reel_grid`) → Task 2 ✅
- §3.2 escape-ветка в reguard → Task 3 ✅
- §3.3 подавление слепого тапа в `_tap_profile_header` → Task 4 ✅
- §4 kill-switch `IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED` default ON → Task 1 ✅
- §5 TDD (grid-from-top True, reel-post True/True, normal False, sheet False, overlap-negatives) → Task 2/3/4 тесты ✅
- §6 деплой/верификация → раздел «Деплой» ниже ✅

**Уточнение vs спека (более корректно, сохраняет инвариант):**
- Форма B детектора = **OR** маркеров (`row_feed_profile_header` ИЛИ `feed_preview_bottom_cta_container`), т.к. на task 15049 cta-контейнера нет (подтверждено дампом). Спека §3.1 указывала «+», но реальные данные требуют OR — иначе false-negative.
- В проверке «есть ли username-тайтл» (форма A) **исключаются грид-ячейки**: `_looks_like_username` ложно матчит латинские токены из их content-desc («Ivanov»/«Expert» → True, подтверждено) — иначе false-negative формы A.

**Placeholder scan:** плейсхолдеров нет; весь код — конкретный.
**Type consistency:** имена методов/категорий согласованы между задачами (`_ig_on_profile_reel_drift`, `_ig_header_zone_has_reel_grid`, `_ig_picker_reel_drift_escape_enabled`, категории `ig_picker_reguard_reel_drift_escaped` / `ig_picker_header_blind_tap_suppressed`).

---

## Деплой (после мержа PR)

1. PR `delivery-contenthunter` → main (squash).
2. Прод-autowarm: `cd /root/.openclaw/workspace-genri/autowarm && git pull --ff-only` (publisher per-task spawn — **PM2-restart не нужен**).
3. Kill-switch `IG_PICKER_REEL_DRIFT_ESCAPE_ENABLED` default ON — активен сразу.
4. OpenProject WP#225 → «Тестирование».
5. **Верификация сутки:** рост события `ig_picker_reguard_reel_drift_escaped` (+ `ig_picker_header_blind_tap_suppressed`) и падение `ig_picker_sheet_not_opened` у реальных клиентов (Lexis Voice, Splus). Тест-проект Тестовый_171b исключить (артефакт scheme_preview, WP#217).
6. Docs-PR (спека+план) в `rmbrmv/contenthunter`.
