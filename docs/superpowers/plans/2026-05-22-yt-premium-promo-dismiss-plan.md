# YT Premium-promo dismiss (WP #132 подсигнатура A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** На шаге `yt_6` (create-меню) при отсутствии триггеров и распознанном интерстишле YouTube Premium — безопасно снять промо (Back), переоткрыть «+» и довести публикацию; если не снялось — упасть с отдельным кодом.

**Architecture:** Чистый детектор-функция `_yt_is_premium_promo` + instance-метод recovery `_yt_dismiss_premium_promo_and_retap` (Back ×2 → 3 safety-гарда → ре-тап → re-verify), врезанные в ветку промаха `_tap_plus_and_verify`. Всё под kill-switch `YT_PREMIUM_DISMISS_ENABLED`. Один файл — `account_switcher.py`.

**Tech Stack:** Python 3, pytest, `unittest.mock.MagicMock`, uiautomator XML dumps. Репо `delivery-contenthunter` (autowarm). Spec: `docs/superpowers/specs/2026-05-22-yt-premium-promo-dismiss-design.md`.

---

## Файловая структура

- **Modify:** `account_switcher.py`
  - module-level рядом с `_guard_enabled` (~line 217): kill-switch `_premium_dismiss_enabled` + константы `_YT_PREMIUM_BRAND_MARKERS`/`_YT_PREMIUM_UPSELL_MARKERS` + функция `_yt_is_premium_promo`.
  - новый метод класса `AccountSwitcher`: `_exact_match_triggers` (рефактор inline-логики WP #88) и `_yt_dismiss_premium_promo_and_retap`.
  - правка ветки `if strict_verify and not hits:` в `_tap_plus_and_verify` (~line 4566).
- **Create:** `tests/test_yt_premium_promo_dismiss.py` — все новые тесты.
- **Create (fixtures):** `tests/fixtures/yt_create_menu/premium_promo_oformit.xml`, `tests/fixtures/yt_create_menu/premium_promo_family.xml`, `tests/fixtures/yt_create_menu/premium_word_video.xml`.
- **Reuse (fixtures):** `tests/fixtures/yt_create_menu/create_menu_open.xml`, `home_feed_no_create.xml` (уже существуют).

Все пути — относительно корня autowarm-репо.

---

## Task 0: Изолированный dev-чекаут autowarm (НЕ прод)

**Files:** none (среда).

Прод `/root/.openclaw/workspace-genri/autowarm` коммитить НЕЛЬЗЯ — там post-commit hook авто-пушит ветку в GitHub. Testbench занят чужой сессией. Нужен свежий локальный клон (клон НЕ копирует hooks → коммиты остаются локальными; origin = локальный путь).

- [ ] **Step 1: Клонировать прод локально**

```bash
git clone /root/.openclaw/workspace-genri/autowarm /home/claude-user/autowarm-wp132-dev
```

- [ ] **Step 2: Создать рабочую ветку**

Run:
```bash
git -C /home/claude-user/autowarm-wp132-dev checkout -b fix/wp132-yt-premium-dismiss
git -C /home/claude-user/autowarm-wp132-dev config --get remote.origin.url
```
Expected: origin = `/root/.openclaw/workspace-genri/autowarm` (локальный путь, НЕ github). Подтверждает, что push/коммит не уйдёт в прод.

- [ ] **Step 3: Синхронизировать account_switcher.py с РАБОЧИМ деревом прода**

Прод деплоит правки копией файла без коммита — в git может не быть актуального кода. Берём ground truth из рабочего дерева прода:

```bash
cp /root/.openclaw/workspace-genri/autowarm/account_switcher.py /home/claude-user/autowarm-wp132-dev/account_switcher.py
git -C /home/claude-user/autowarm-wp132-dev diff --stat account_switcher.py
```
Expected: либо нет диффа (прод == git), либо дифф = uncommitted прод-дрейф (это и есть актуальный код — оставляем).

- [ ] **Step 4: Базовый прогон тестов (зелёный baseline ДО изменений)**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_create_menu_strict_verify.py tests/test_yt_create_menu_fg_guard.py -q
```
Expected: PASS (все). Если красно — остановиться и разобраться ДО любых правок (baseline сломан не нами).

> Все последующие задачи выполняются в `/home/claude-user/autowarm-wp132-dev`.

---

## Task 1: Детектор `_yt_is_premium_promo` + константы + kill-switch

**Files:**
- Create: `tests/fixtures/yt_create_menu/premium_promo_oformit.xml`
- Create: `tests/fixtures/yt_create_menu/premium_promo_family.xml`
- Create: `tests/fixtures/yt_create_menu/premium_word_video.xml`
- Create: `tests/test_yt_premium_promo_dismiss.py`
- Modify: `account_switcher.py` (~line 217, рядом с `_guard_enabled`)

- [ ] **Step 1: Создать фикстуру promo «Оформить» (по мотивам task 9084)**

Create `tests/fixtures/yt_create_menu/premium_promo_oformit.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" package="com.google.android.youtube" bounds="[0,0][1080,2340]">
    <node text="Оформить YouTube Premium" class="android.widget.TextView" clickable="false" bounds="[80,160][1000,240]"/>
    <node text="Весь YouTube без рекламы." class="android.widget.TextView" clickable="false" bounds="[80,300][1000,420]"/>
    <node text="2 пробных месяца за 0 KZT, затем 2 700,00 KZT в месяц" class="android.widget.TextView" clickable="false" bounds="[80,500][1000,700]"/>
    <node text="2 месяца за 0 KZT" class="android.widget.Button" clickable="true" bounds="[80,1500][1000,1620]"/>
    <node content-desc="Закрыть" class="android.widget.ImageView" clickable="true" bounds="[40,120][140,220]"/>
  </node>
</hierarchy>
```

- [ ] **Step 2: Создать фикстуру promo «семейная подписка» (по мотивам task 9253)**

Create `tests/fixtures/yt_create_menu/premium_promo_family.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" package="com.google.android.youtube" bounds="[0,0][1080,2340]">
    <node text="YouTube Premium" class="android.widget.TextView" clickable="false" bounds="[120,160][600,240]"/>
    <node text="Попробуйте семейную подписку YouTube Premium" class="android.widget.TextView" clickable="false" bounds="[80,360][1000,520]"/>
    <node text="YouTube без рекламы" class="android.widget.TextView" clickable="false" bounds="[160,900][1000,980]"/>
    <node text="Попробуйте на 1 месяц" class="android.widget.Button" clickable="true" bounds="[80,1700][1000,1820]"/>
    <node content-desc="Закрыть" class="android.widget.ImageView" clickable="true" bounds="[920,120][1020,220]"/>
  </node>
</hierarchy>
```

- [ ] **Step 3: Создать НЕГАТИВНУЮ фикстуру (видео со словом «Premium» в названии, без апселл-CTA)**

Create `tests/fixtures/yt_create_menu/premium_word_video.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" package="com.google.android.youtube" bounds="[0,0][1080,2340]">
    <node text="Premium седаны 2026: обзор" class="android.widget.TextView" clickable="false" bounds="[40,200][1040,320]"/>
    <node text="1,2 млн просмотров" class="android.widget.TextView" clickable="false" bounds="[40,340][600,400]"/>
    <node content-desc="Главная" class="android.widget.Button" clickable="true" bounds="[0,2240][216,2340]"/>
  </node>
</hierarchy>
```

- [ ] **Step 4: Написать падающие юнит-тесты детектора**

Create `tests/test_yt_premium_promo_dismiss.py`:

```python
"""WP #132 подсигнатура A — снятие промо YouTube Premium на yt_6."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import account_switcher as _asw

FIX = Path(__file__).parent / "fixtures" / "yt_create_menu"
CFG = _asw.UI_CONSTANTS["YouTube"]


# ─── Task 1: детектор ────────────────────────────────────────────────────────
def test_detect_premium_promo_oformit():
    xml = (FIX / "premium_promo_oformit.xml").read_text()
    assert _asw._yt_is_premium_promo(xml) is True


def test_detect_premium_promo_family():
    xml = (FIX / "premium_promo_family.xml").read_text()
    assert _asw._yt_is_premium_promo(xml) is True


def test_detect_negative_premium_word_in_video_title():
    xml = (FIX / "premium_word_video.xml").read_text()
    assert _asw._yt_is_premium_promo(xml) is False


def test_detect_negative_real_create_menu():
    xml = (FIX / "create_menu_open.xml").read_text()
    assert _asw._yt_is_premium_promo(xml) is False


def test_detect_negative_empty_dump():
    assert _asw._yt_is_premium_promo("") is False
    assert _asw._yt_is_premium_promo(None) is False
```

- [ ] **Step 5: Запустить — убедиться, что падает**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py -q
```
Expected: FAIL — `AttributeError: module 'account_switcher' has no attribute '_yt_is_premium_promo'`.

- [ ] **Step 6: Реализовать константы + kill-switch + детектор**

В `account_switcher.py` сразу ПОСЛЕ функции `_guard_enabled` (после строки `return os.environ.get('YT_CREATE_MENU_GUARD_ENABLED', '1') != '0'`) добавить:

```python
# ─────────────────────────────────────────────────────────────────────────────
# WP #132 — YT create-menu: снятие промо YouTube Premium (подсигнатура A)
# ─────────────────────────────────────────────────────────────────────────────
def _premium_dismiss_enabled() -> bool:
    """[WP #132] Kill-switch для снятия промо YouTube Premium на yt_6.
    Default ON. YT_PREMIUM_DISMISS_ENABLED=0 → откат к legacy (fail сразу).
    """
    return os.environ.get('YT_PREMIUM_DISMISS_ENABLED', '1') != '0'


# Маркеры интерстишла YouTube Premium. Match требует ОБА: бренд И апселл-CTA —
# защита от ложного срабатывания (одно слово «Premium» без CTA не пройдёт).
# Бренд = слово 'premium' (НЕ непрерывное 'youtube premium': в dump'е слова
# могут быть в разных узлах). Точность даёт специфичный апселл-CTA. Сверка
# case-insensitive по сырому XML. Расширяется по evidence.
_YT_PREMIUM_BRAND_MARKERS: tuple[str, ...] = (
    'premium',
)
_YT_PREMIUM_UPSELL_MARKERS: tuple[str, ...] = (
    'попробуйте на 1 месяц',
    'месяца за 0',
    'за 0 kzt',
    'без рекламы',
    'семейную подписку',
    'оформить youtube premium',
    'пробных месяца',
)


def _yt_is_premium_promo(xml) -> bool:
    """True если dump похож на полноэкранный интерстишл YouTube Premium.
    Требует И бренд-маркер И апселл-CTA. Pure-функция над строкой dump'а.
    Пустой/None dump → False.
    """
    if not xml:
        return False
    low = xml.lower()
    has_brand = any(m in low for m in _YT_PREMIUM_BRAND_MARKERS)
    has_upsell = any(m in low for m in _YT_PREMIUM_UPSELL_MARKERS)
    return has_brand and has_upsell
```

- [ ] **Step 7: Запустить — убедиться, что детектор-тесты зелёные**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py -q
```
Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
cd /home/claude-user/autowarm-wp132-dev
git add account_switcher.py tests/test_yt_premium_promo_dismiss.py tests/fixtures/yt_create_menu/premium_promo_oformit.xml tests/fixtures/yt_create_menu/premium_promo_family.xml tests/fixtures/yt_create_menu/premium_word_video.xml
git commit -m "feat(wp132): детектор промо YouTube Premium + kill-switch (yt_6)"
```

---

## Task 2: Рефактор exact-match в helper `_exact_match_triggers`

Чтобы recovery-метод (Task 3) переиспользовал exact-match-логику WP #88 без дублирования. Поведение основного пути не меняется — та же логика, извлечённая в метод.

**Files:**
- Modify: `account_switcher.py` (метод `_tap_plus_and_verify`, блок ~line 4540-4557; + новый метод рядом)

- [ ] **Step 1: Написать тест helper'а (падающий)**

Дописать в `tests/test_yt_premium_promo_dismiss.py`:

```python
# ─── Task 2: exact-match helper ──────────────────────────────────────────────
def _bare_switcher():
    sw = _asw.AccountSwitcher.__new__(_asw.AccountSwitcher)
    sw.p = MagicMock()
    return sw


def test_exact_match_triggers_finds_create_menu_buttons():
    sw = _bare_switcher()
    xml = (FIX / "create_menu_open.xml").read_text()
    hits = sw._exact_match_triggers(xml, CFG["editor_triggers"])
    assert len(hits) >= 1
    assert all(h in CFG["editor_triggers"] for h in hits)


def test_exact_match_triggers_empty_on_promo():
    sw = _bare_switcher()
    xml = (FIX / "premium_promo_family.xml").read_text()
    assert sw._exact_match_triggers(xml, CFG["editor_triggers"]) == []


def test_exact_match_triggers_handles_bad_xml():
    sw = _bare_switcher()
    assert sw._exact_match_triggers("not xml <<<", CFG["editor_triggers"]) == []
    assert sw._exact_match_triggers("", CFG["editor_triggers"]) == []
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py -k exact_match -q
```
Expected: FAIL — `AttributeError: ... '_exact_match_triggers'`.

- [ ] **Step 3: Извлечь helper-метод**

В классе `AccountSwitcher`, рядом с `_tap_plus_and_verify`, добавить метод:

```python
    def _exact_match_triggers(self, xml, verify_triggers: list) -> list:
        """[WP #88/#132] Exact-match триггеров по node text/content-desc.
        Возвращает отсортированный список найденных триггеров. Битый/пустой
        xml → []. Извлечено из _tap_plus_and_verify для переиспользования.
        """
        if not xml or not verify_triggers:
            return []
        trigger_set = set(verify_triggers)
        seen: set = set()
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            root = None
        if root is not None:
            for n in root.iter('node'):
                for attr in ('text', 'content-desc'):
                    v = (n.get(attr, '') or '').strip()
                    if v and v in trigger_set:
                        seen.add(v)
        return sorted(seen)
```

- [ ] **Step 4: Заменить inline-блок в `_tap_plus_and_verify` на вызов helper'а**

Найти блок (внутри `if ui2 and verify_triggers:` → `if strict_verify:`):

```python
            if strict_verify:
                # [WP #88 2026-05-19] Exact-match по node text/content-desc
                # вместо permissive substring. Иначе trigger 'Видео' ложно
                # матчится на content-desc='Приостановить видео' (Shorts pause
                # overlay). Match каждого attr отдельно — не их конкатенации.
                trigger_set = set(verify_triggers)
                seen: set = set()
                try:
                    root = ET.fromstring(ui2)
                except ET.ParseError:
                    root = None
                if root is not None:
                    for n in root.iter('node'):
                        for attr in ('text', 'content-desc'):
                            v = (n.get(attr, '') or '').strip()
                            if v and v in trigger_set:
                                seen.add(v)
                hits = sorted(seen)
            else:
                # Legacy permissive substring (IG/TT) — поведение не меняется.
                hits = [t for t in verify_triggers if t.lower() in ui2.lower()]
```

Заменить на:

```python
            if strict_verify:
                # [WP #88/#132] Exact-match вынесен в _exact_match_triggers.
                hits = self._exact_match_triggers(ui2, verify_triggers)
            else:
                # Legacy permissive substring (IG/TT) — поведение не меняется.
                hits = [t for t in verify_triggers if t.lower() in ui2.lower()]
```

- [ ] **Step 5: Запустить — helper-тесты И существующие strict_verify-тесты зелёные**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py tests/test_yt_create_menu_strict_verify.py -q
```
Expected: all passed (рефактор не изменил поведение — strict_verify-тесты по-прежнему зелёные).

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-wp132-dev
git add account_switcher.py tests/test_yt_premium_promo_dismiss.py
git commit -m "refactor(wp132): exact-match триггеров в helper _exact_match_triggers"
```

---

## Task 3: Recovery-метод `_yt_dismiss_premium_promo_and_retap`

**Files:**
- Modify: `account_switcher.py` (новый метод класса `AccountSwitcher`)
- Modify: `tests/test_yt_premium_promo_dismiss.py`

- [ ] **Step 1: Написать падающие тесты recovery-метода (4 сценария)**

Дописать в `tests/test_yt_premium_promo_dismiss.py`:

```python
# ─── Task 3: recovery-метод ──────────────────────────────────────────────────
PROMO = None  # заполняется в _recovery_switcher
CREATE = None


def _recovery_switcher(dump_sequence, fg_pkg="com.google.android.youtube",
                       fg_recovered=True, monkeypatch=None):
    """AccountSwitcher с MagicMock-прокси; dump_ui отдаёт dump_sequence по очереди."""
    sw = _asw.AccountSwitcher.__new__(_asw.AccountSwitcher)
    sw.p = MagicMock()
    sw.p.dump_ui = MagicMock(side_effect=list(dump_sequence))
    sw.p.tap_element = MagicMock(return_value=True)
    sw.p.adb_tap = MagicMock()
    sw.p.adb = MagicMock()
    sw.p.log_event = MagicMock()
    sw._detect_foreground_pkg = MagicMock(return_value=fg_pkg)
    sw._yt_ensure_foreground = MagicMock(return_value=fg_recovered)
    if monkeypatch is not None:
        monkeypatch.setattr(_asw.time, "sleep", lambda *a, **k: None)
    return sw


def test_recovery_success_back_clears_promo(monkeypatch):
    create_xml = (FIX / "create_menu_open.xml").read_text()
    home_xml = (FIX / "home_feed_no_create.xml").read_text()
    # back-loop dump → not promo (home); pre-retap dump; post-retap dump → triggers
    sw = _recovery_switcher([home_xml, home_xml, create_xml], monkeypatch=monkeypatch)
    ok = sw._yt_dismiss_premium_promo_and_retap(CFG, "yt_6_create_menu")
    assert ok is True
    # ровно 1 ре-тап «+» (element-tap вернул True → adb_tap не звался)
    assert sw.p.tap_element.call_count == 1
    sw.p.adb_tap.assert_not_called()
    cats = [c.kwargs["meta"]["category"] for c in sw.p.log_event.call_args_list]
    assert "yt_premium_promo_dismissed" in cats


def test_recovery_fails_when_promo_persists(monkeypatch):
    promo = (FIX / "premium_promo_family.xml").read_text()
    sw = _recovery_switcher([promo, promo], monkeypatch=monkeypatch)
    ok = sw._yt_dismiss_premium_promo_and_retap(CFG, "yt_6_create_menu")
    assert ok is False
    # КРИТИЧНО: ни одного тапа при видимом промо
    sw.p.tap_element.assert_not_called()
    sw.p.adb_tap.assert_not_called()


def test_recovery_fails_on_empty_dump(monkeypatch):
    sw = _recovery_switcher([None, ""], monkeypatch=monkeypatch)
    ok = sw._yt_dismiss_premium_promo_and_retap(CFG, "yt_6_create_menu")
    assert ok is False
    sw.p.tap_element.assert_not_called()
    sw.p.adb_tap.assert_not_called()


def test_recovery_fails_on_foreground_drift(monkeypatch):
    home_xml = (FIX / "home_feed_no_create.xml").read_text()
    # промо ушло (home), но fg=launcher и ensure_foreground=False
    sw = _recovery_switcher([home_xml], fg_pkg="com.sec.android.app.launcher",
                            fg_recovered=False, monkeypatch=monkeypatch)
    ok = sw._yt_dismiss_premium_promo_and_retap(CFG, "yt_6_create_menu")
    assert ok is False
    sw.p.tap_element.assert_not_called()
    sw.p.adb_tap.assert_not_called()
    reasons = [c.kwargs["meta"].get("reason") for c in sw.p.log_event.call_args_list]
    assert "foreground_drift_after_back" in reasons
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py -k recovery -q
```
Expected: FAIL — `AttributeError: ... '_yt_dismiss_premium_promo_and_retap'`.

- [ ] **Step 3: Реализовать recovery-метод**

В классе `AccountSwitcher`, рядом с `_exact_match_triggers`, добавить:

```python
    def _yt_dismiss_premium_promo_and_retap(self, cfg: dict, final_step: str) -> bool:
        """[WP #132] Закрыть промо Premium через Back, переоткрыть «+», re-verify.
        Возвращает True если после recovery editor_triggers найдены.
        Безопасно: только Back; ре-тап лишь при ТРЁХ выполненных гардах.
        """
        self.p.log_event('account_switch', 'yt_premium_promo_detected',
            meta={'category': 'yt_premium_promo_detected', 'step': final_step})

        # 1) До 2 Back чтобы снять промо. Отслеживаем, что промо реально ушло.
        MAX_BACK = 2
        promo_gone = False
        for _ in range(MAX_BACK):
            self.p.adb('input keyevent 4')
            time.sleep(POST_TAP_WAIT_S + 0.5)
            xml = self.p.dump_ui(retries=1)
            # [codex P1] Пустой/неудачный dump НЕ доказывает снятие промо
            # (transient ADB / FLAG_SECURE) — промо могло остаться. promo_gone=True
            # только при ВАЛИДНОМ dump'е без промо.
            if xml and not _yt_is_premium_promo(xml):
                promo_gone = True
                break

        # [codex P1] Промо ещё на экране после бюджета Back → НЕ тапаем
        # (фолбэк-coords «+» (540,2137) попадёт по промо → CTA подписки). Fail-fast.
        if not promo_gone:
            self.p.log_event('warning', 'yt_premium_promo_dismiss_failed',
                meta={'category': 'yt_premium_promo_dismiss_failed', 'step': final_step,
                      'reason': 'promo_still_visible_after_back_budget'})
            return False

        # [codex P2] Back мог увести foreground в launcher/другой app. Перед
        # ре-тапом убедиться, что foreground всё ещё YouTube — иначе фолбэк-coords
        # ударит по чужому экрану. При drift'е — попытка вернуть YouTube; не вышло
        # → fail-fast без тапа.
        fg = self._detect_foreground_pkg()
        if fg and fg != cfg['package']:
            if not self._yt_ensure_foreground(
                    cfg, f'{final_step}_premium_post_back_fg_recovery'):
                self.p.log_event('warning', 'yt_premium_promo_dismiss_failed',
                    meta={'category': 'yt_premium_promo_dismiss_failed',
                          'step': final_step,
                          'reason': 'foreground_drift_after_back',
                          'foreground_pkg': fg})
                return False

        # 2) Промо ушло и YouTube в foreground → безопасно ре-тапнуть «+».
        plus = cfg['plus_button']
        ui = self.p.dump_ui(retries=1)
        tapped = self.p.tap_element(ui, plus['desc'], clickable_only=True) if ui else False
        if not tapped:
            self.p.adb_tap(*plus['coords'])
        time.sleep(POST_TAP_WAIT_S + 1.0)

        # 3) Ре-проверка editor_triggers (exact-match).
        ui2 = self.p.dump_ui(retries=1)
        hits = self._exact_match_triggers(ui2, cfg['editor_triggers'])
        if hits:
            self.p.log_event('account_switch', 'yt_premium_promo_dismissed',
                meta={'category': 'yt_premium_promo_dismissed', 'step': final_step,
                      'hits': hits})
            return True
        self.p.log_event('warning', 'yt_premium_promo_dismiss_failed',
            meta={'category': 'yt_premium_promo_dismiss_failed', 'step': final_step,
                  'reason': 'no_triggers_after_retap'})
        return False
```

- [ ] **Step 4: Запустить — recovery-тесты зелёные**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py -k recovery -q
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-wp132-dev
git add account_switcher.py tests/test_yt_premium_promo_dismiss.py
git commit -m "feat(wp132): recovery-метод снятия промо Premium (Back + 3 safety-гарда)"
```

---

## Task 4: Врезка в `_tap_plus_and_verify` + интеграционные тесты

**Files:**
- Modify: `account_switcher.py` (ветка `if strict_verify and not hits:` в `_tap_plus_and_verify`)
- Modify: `tests/test_yt_premium_promo_dismiss.py`

- [ ] **Step 1: Написать падающие интеграционные тесты (4 сценария)**

Дописать в `tests/test_yt_premium_promo_dismiss.py`:

```python
# ─── Task 4: врезка в _tap_plus_and_verify ───────────────────────────────────
def _integration_switcher(ui2_xml, monkeypatch, recovery_return=None,
                          fg_pkg="com.google.android.youtube"):
    """Прокси для _tap_plus_and_verify: 3-й dump_ui = ui2_xml (экран после «+»)."""
    sw = _asw.AccountSwitcher.__new__(_asw.AccountSwitcher)
    sw.p = MagicMock()
    # dump_ui: #1 initial-plus-tap, #2 внутри _save_dump-аргумента, #3 = ui2
    sw.p.dump_ui = MagicMock(side_effect=["<hierarchy/>", "<hierarchy/>", ui2_xml])
    sw.p.tap_element = MagicMock(return_value=True)
    sw.p.adb_tap = MagicMock()
    sw.p.adb = MagicMock()
    sw.p.log_event = MagicMock()
    sw._save_dump = MagicMock()
    sw._maybe_screenshot = MagicMock()
    sw._detect_foreground_pkg = MagicMock(return_value=fg_pkg)
    sw._attempts = 0
    sw._screenshots = []
    sw._dumps = []
    if recovery_return is not None:
        sw._yt_dismiss_premium_promo_and_retap = MagicMock(return_value=recovery_return)
    monkeypatch.setattr(_asw.time, "sleep", lambda *a, **k: None)
    return sw


def _run_tpv(sw):
    return sw._tap_plus_and_verify(
        CFG, step_prefix="yt_6", final_step="yt_6_create_menu",
        verify_triggers=CFG["editor_triggers"], already_matched=False,
        strict_verify=True)


def test_integration_promo_recovery_success(monkeypatch):
    promo = (FIX / "premium_promo_family.xml").read_text()
    sw = _integration_switcher(promo, monkeypatch, recovery_return=True)
    result = _run_tpv(sw)
    assert result.success is True
    assert result.final_step == "yt_6_create_menu"
    sw._yt_dismiss_premium_promo_and_retap.assert_called_once()


def test_integration_promo_recovery_fail_distinct_code(monkeypatch):
    promo = (FIX / "premium_promo_family.xml").read_text()
    sw = _integration_switcher(promo, monkeypatch, recovery_return=False)
    result = _run_tpv(sw)
    assert result.success is False
    assert result.final_step == "yt_6_create_menu_premium_blocking"
    cats = [c.kwargs.get("meta", {}).get("category")
            for c in sw.p.log_event.call_args_list]
    assert "yt_create_menu_premium_blocking" in cats


def test_integration_non_promo_keeps_legacy_code(monkeypatch):
    home = (FIX / "home_feed_no_create.xml").read_text()
    sw = _integration_switcher(home, monkeypatch, recovery_return=True)
    result = _run_tpv(sw)
    assert result.success is False
    assert result.final_step == "yt_6_create_menu_no_triggers"
    # recovery НЕ должен вызываться на не-промо экране
    sw._yt_dismiss_premium_promo_and_retap.assert_not_called()


def test_integration_killswitch_off_skips_recovery(monkeypatch):
    monkeypatch.setenv("YT_PREMIUM_DISMISS_ENABLED", "0")
    promo = (FIX / "premium_promo_family.xml").read_text()
    sw = _integration_switcher(promo, monkeypatch, recovery_return=True)
    result = _run_tpv(sw)
    assert result.success is False
    assert result.final_step == "yt_6_create_menu_no_triggers"
    sw._yt_dismiss_premium_promo_and_retap.assert_not_called()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py -k integration -q
```
Expected: FAIL (recovery-врезки ещё нет → промо-кейсы дают `yt_6_create_menu_no_triggers`, тесты ждут `_premium_blocking`/success).

- [ ] **Step 3: Врезать recovery в ветку промаха**

Найти в `_tap_plus_and_verify` блок:

```python
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
```

Заменить на (вставить блок ДО `fail_step = f'{final_step}_no_triggers'`):

```python
        if strict_verify and not hits:
            # [WP #132] До общего fail — попытка снять промо YouTube Premium и довести.
            if _premium_dismiss_enabled() and _yt_is_premium_promo(ui2):
                if self._yt_dismiss_premium_promo_and_retap(cfg, final_step):
                    return self._ok(final_step, already_matched=already_matched)
                # промо распознано, но снять не удалось → отдельный код (не маскарад).
                pb_step = f'{final_step}_premium_blocking'
                self.p.log_event(
                    'warning', f'{pb_step}: YouTube Premium promo not dismissable',
                    meta={'category': 'yt_create_menu_premium_blocking',
                          'step': pb_step},
                )
                return self._fail(
                    f'{final_step}: интерстишл YouTube Premium не снялся',
                    step=pb_step,
                )
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
```

- [ ] **Step 4: Запустить — интеграционные тесты зелёные**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py -k integration -q
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-wp132-dev
git add account_switcher.py tests/test_yt_premium_promo_dismiss.py
git commit -m "feat(wp132): врезка снятия промо Premium в _tap_plus_and_verify + отдельный код"
```

---

## Task 5: Регрессия, codex review, деплой

**Files:** `account_switcher.py` (деплой в прод).

- [ ] **Step 1: Полный прогон switcher-тестов (0 регрессий)**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && python3 -m pytest tests/test_yt_premium_promo_dismiss.py tests/test_yt_create_menu_strict_verify.py tests/test_yt_create_menu_fg_guard.py -q
```
Expected: all passed (включая 17 новых). Если есть упавшие из прочих switcher-тестов — прогнать `python3 -m pytest tests/ -q -k "switch or yt_ or create_menu"` и убедиться, что новых падений нет относительно baseline (Task 0 Step 4).

- [ ] **Step 2: Codex review дельты кода**

Run:
```bash
cd /home/claude-user/autowarm-wp132-dev && git diff main...HEAD -- account_switcher.py | ~/.local/bin/codex review -
```
Действие: применить P1/P2 раундами до 0 P1 (правка → тест → commit). Это код-ревью (не диффа спеки) — здесь codex видит реальную реализацию.

- [ ] **Step 3: СТОП — подтверждение перед прод-деплоем**

Прод-деплой — outward-facing. Показать пользователю сводку (что меняется, kill-switch, как откатить) и получить «деплой». НЕ деплоить без подтверждения.

- [ ] **Step 4: Деплой копией файла в прод (после подтверждения)**

Снять страховочную копию и скопировать:
```bash
cp /root/.openclaw/workspace-genri/autowarm/account_switcher.py /root/.openclaw/workspace-genri/autowarm/account_switcher.py.bak-wp132
cp /home/claude-user/autowarm-wp132-dev/account_switcher.py /root/.openclaw/workspace-genri/autowarm/account_switcher.py
python3 -c "import ast; ast.parse(open('/root/.openclaw/workspace-genri/autowarm/account_switcher.py').read()); print('syntax OK')"
```
Подхват — per-task spawn (новые publish-задачи импортируют свежий файл; PM2 restart НЕ нужен). Kill-switch: при проблеме `export YT_PREMIUM_DISMISS_ENABLED=0` в окружении publisher'а (или откат `.bak`-копией).

> Деплой тестовых файлов (`tests/...`) в прод working tree не требуется для работы фичи. Перенос в git-историю прод-репо (с авто-пушем) — отдельным шагом по решению пользователя.

- [ ] **Step 5: Verify на проде (после деплоя)**

Дождаться/инициировать YT-публикацию на аккаунте, где ранее ловили промо (напр. EliteCornersSpb / SmartEstatesDubai). Проверить в БД:
```sql
SELECT id, account, error_code,
       (SELECT count(*) FROM jsonb_array_elements(events) e
        WHERE e->'meta'->>'category' LIKE 'yt_premium_promo%') AS promo_events
FROM publish_tasks
WHERE platform='YouTube' AND created_at > now() - interval '6 hours'
ORDER BY id DESC LIMIT 20;
```
Ожидание: события `yt_premium_promo_detected`→`yt_premium_promo_dismissed` на recovered-задачах; либо `yt_create_menu_premium_blocking` (распознали, но не сняли — не маскарад). Снижение `yt_create_menu_not_reached` от промо-кейсов.

- [ ] **Step 6: Обновить WP #132 + evidence**

Пост в OpenProject #132 (house-style: Что было не так → Что сделано → Что осталось) + статус → Тестирование (id 9). Записать evidence-док `docs/evidence/2026-05-22-yt-premium-promo-dismiss-shipped.md` в worktree contenthunter.

---

## Self-review заметка

- **Покрытие спеки:** детектор (Task 1), exact-match рефактор §3.6 (Task 2), recovery + 3 гарда §3.4/§4 (Task 3), врезка + отдельный код §3.5/§5 (Task 4), kill-switch (Task 1+4), тесты §6 (Tasks 1/3/4), деплой §7 (Task 5). Подсигнатура B §8 — не трогаем.
- **Типы/имена:** `_yt_is_premium_promo`, `_premium_dismiss_enabled`, `_exact_match_triggers`, `_yt_dismiss_premium_promo_and_retap`, `UI_CONSTANTS["YouTube"]`, `CFG["editor_triggers"]`, `CFG["plus_button"]`, `cfg['package']`, событие-категории и код `yt_create_menu_premium_blocking` — единообразны во всех тасках.
- **Плейсхолдеров нет.**
