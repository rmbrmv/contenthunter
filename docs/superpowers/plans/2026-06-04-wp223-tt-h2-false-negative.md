# WP#223 — TikTok H2 false-negative детекции публикации — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить ложные `tt_upload_confirmation_timeout` при реально прошедшей публикации (false-negative): дисмиссить in-app модалку «Синхронизируйте контакты», добавить post-mortem dumpsys-пробу на профиле, и не дать преждевременно удалять тестбенч-задачи из `publish_tasks`.

**Architecture:** Три независимых компонента в `publisher_tiktok.py` (Python publisher, спавнится per-task) + один в источнике DELETE (выясняется разведкой). A — новый detector + dismiss-only обработчик в `_wait_upload_confirmation` (по образцу notif-обработчика). B — post-mortem проба на границе таймаута, читает `topResumedActivity` через dumpsys (ground-truth, зеркало WP#181) → inferred_success fall-through. C — разведка источника DELETE + защитный гард на не-удаление до терминального статуса.

**Tech Stack:** Python 3, pytest, `unittest.mock`; Postgres (`publish_tasks`); Android uiautomator/adb. Все поведенческие изменения под kill-switch'ами (env, default ON).

**Spec:** `docs/superpowers/specs/2026-06-04-wp223-tt-h2-false-negative-design.md`

**Код-репо:** `delivery-contenthunter`, прод-каталог `/root/.openclaw/workspace-genri/autowarm`. Правки вести в ИЗОЛИРОВАННОМ worktree (общий checkout = гонка).

---

## Конвенции тестов (прочитать перед стартом)

Тест-файлы TT-детекторов: `tests/test_publisher_tt_*.py`. Паттерн (из `tests/test_publisher_tt_overlay_handlers.py`):

```python
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from publisher_tiktok import TikTokMixin  # noqa: E402

def _xml(nodes_attrs: list[dict]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<hierarchy rotation="0">',
             '  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">']
    for n in nodes_attrs:
        attrs = ' '.join(f'{k}="{v}"' for k, v in n.items())
        lines.append(f'    <node {attrs} />')
    lines.append('  </node>')
    lines.append('</hierarchy>')
    return '\n'.join(lines)

def _bare_mixin() -> TikTokMixin:
    mx = TikTokMixin.__new__(TikTokMixin)
    mx.platform = 'TikTok'
    mx._init_wait_upload_overlay_state()
    mx.log_event = MagicMock()
    mx.adb = MagicMock(return_value='')
    mx.adb_tap = MagicMock()
    mx.set_step = MagicMock()
    mx.tap_element = MagicMock(return_value=True)
    return mx
```

Запуск набора: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_*.py -q` (НЕ запускать `pytest tests/` целиком — зависает на live-тестах).

---

## Task 1: Компонент A — детектор `_detect_tt_contacts_sync_modal` + константы

**Files:**
- Modify: `publisher_tiktok.py` (константы рядом с `_TT_NOTIF_MODAL_MARKERS` ~676; метод рядом с `_detect_tt_notifications_modal` ~898)
- Test: `tests/test_publisher_tt_contacts_sync_modal.py` (create)

- [ ] **Step 1: Написать падающий тест**

Create `tests/test_publisher_tt_contacts_sync_modal.py` (заголовок-конвенции из секции выше + ниже):

```python
def test_contacts_sync_positive_title_plus_deny():
    """Заголовок «Синхронизируйте контакты» + clickable «Не разрешать» → True."""
    mx = _bare_mixin()
    ui = _xml([
        {'text': 'Синхронизируйте контакты', 'bounds': '[100,400][980,520]'},
        {'text': 'Не разрешать', 'clickable': 'true', 'bounds': '[120,1700][520,1800]'},
        {'text': 'ОК', 'clickable': 'true', 'bounds': '[560,1700][960,1800]'},
    ])
    assert mx._detect_tt_contacts_sync_modal(ui) is True


def test_contacts_sync_negative_no_clickable_dismiss():
    """Заголовок есть, но кнопка дисмисса не clickable → False."""
    mx = _bare_mixin()
    ui = _xml([
        {'text': 'Синхронизируйте контакты', 'bounds': '[100,400][980,520]'},
        {'text': 'Не разрешать', 'clickable': 'false', 'bounds': '[120,1700][520,1800]'},
    ])
    assert mx._detect_tt_contacts_sync_modal(ui) is False


def test_contacts_sync_not_triggered_by_os_perm_dialog():
    """OS-диалог «доступ к контактам» (вотчина _detect_tt_contacts_perm) НЕ матчится."""
    mx = _bare_mixin()
    ui = _xml([
        {'text': 'Разрешить TikTok доступ к контактам?', 'bounds': '[100,400][980,520]'},
        {'text': 'Не разрешать', 'clickable': 'true', 'bounds': '[120,1700][520,1800]'},
    ])
    assert mx._detect_tt_contacts_sync_modal(ui) is False


def test_contacts_sync_empty_xml():
    mx = _bare_mixin()
    assert mx._detect_tt_contacts_sync_modal('') is False
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_contacts_sync_modal.py -q`
Expected: FAIL — `AttributeError: 'TikTokMixin' object has no attribute '_detect_tt_contacts_sync_modal'`

- [ ] **Step 3: Добавить константы**

В `publisher_tiktok.py` сразу после блока `_TT_NOTIF_MODAL_MARKERS` (заканчивается ~683, перед `def _init_wait_upload_overlay_state`):

```python
    # WP#223 H2.1 — in-app модалка «Синхронизируйте контакты» (Не разрешать/ОК).
    # Появляется post-publish поверх фида (task 14040: видео в ленте, модалка
    # перекрывает success-детект → ложный tt_upload_confirmation_timeout).
    # ОТЛИЧНА от OS-диалога contacts-perm (_TT_PERM_DIALOG_VARIANTS). Трактуем
    # как dismiss-only (НЕ доказательство публикации): после снятия оверлея
    # успех подтверждают navbar-shell / UPLOAD_OK маркеры на след. итерации.
    _TT_CONTACTS_SYNC_MARKERS = (
        'Синхронизируйте контакты',
        'Sync your contacts',
        'Sync contacts',
    )
    _TT_CONTACTS_SYNC_DISMISS_LABELS = ['Не разрешать', "Don't allow", 'ОК', 'OK']
    MAX_TT_CONTACTS_SYNC_ITERATIONS = 5
```

- [ ] **Step 4: Добавить детектор**

В `publisher_tiktok.py` сразу после метода `_detect_tt_notifications_modal` (заканчивается ~909):

```python
    def _detect_tt_contacts_sync_modal(self, ui_xml: str) -> bool:
        """[WP#223 H2.1] In-app модалка «Синхронизируйте контакты».

        Требует: substring-заголовок ИЗ _TT_CONTACTS_SYNC_MARKERS + ≥1 clickable
        кнопка дисмисса из _TT_CONTACTS_SYNC_DISMISS_LABELS. Отдельна от
        _detect_tt_contacts_perm (OS-permission rationale). Dismiss-only —
        НЕ используется как доказательство публикации.
        """
        if not ui_xml:
            return False
        if not any(m in ui_xml for m in self._TT_CONTACTS_SYNC_MARKERS):
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if (txt in self._TT_CONTACTS_SYNC_DISMISS_LABELS
                    or desc in self._TT_CONTACTS_SYNC_DISMISS_LABELS):
                return True
        return False
```

- [ ] **Step 5: Запустить — убедиться что зелёный**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_contacts_sync_modal.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Коммит**

```bash
cd /home/claude-user/wp223-tt-h2  # worktree автоварма для кода; см. примечание ниже
git add publisher_tiktok.py tests/test_publisher_tt_contacts_sync_modal.py
git commit -m "feat(wp223): detector _detect_tt_contacts_sync_modal (H2.1, dismiss-only)"
```

> **Примечание о worktree кода:** docs-репо (`rmbrmv/contenthunter`) и код-репо (`delivery-contenthunter`) — РАЗНЫЕ. Спека/план коммитятся в docs-worktree `/home/claude-user/wp223-tt-h2`. Код `publisher_tiktok.py` живёт в `delivery-contenthunter`; перед стартом кодинга создать ИЗОЛИРОВАННЫЙ worktree код-репо (`git -C /root/.openclaw/workspace-genri/autowarm worktree add -b wp223-tt-h2-code <path> origin/main`) и вести правки/тесты там, затем PR в `delivery-contenthunter`. Команды `git add/commit` в шагах относятся к КОД-worktree.

---

## Task 2: Компонент A — счётчик + wiring дисмисса в `_wait_upload_confirmation`

**Files:**
- Modify: `publisher_tiktok.py` (`_init_wait_upload_overlay_state` ~696; wait-loop рядом с notif-обработчиком ~3692)
- Test: `tests/test_publisher_tt_contacts_sync_modal.py` (append)

- [ ] **Step 1: Написать падающий тест на ресет счётчика**

Append в `tests/test_publisher_tt_contacts_sync_modal.py`:

```python
def test_contacts_sync_counter_reset_on_init():
    """_init_wait_upload_overlay_state обнуляет per-task счётчик."""
    mx = _bare_mixin()
    mx._contacts_sync_iter = 4
    mx._init_wait_upload_overlay_state()
    assert mx._contacts_sync_iter == 0
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_contacts_sync_modal.py::test_contacts_sync_counter_reset_on_init -q`
Expected: FAIL — счётчик не сбрасывается (AttributeError или AssertionError 4 != 0)

- [ ] **Step 3: Добавить счётчик в ресет**

В `_init_wait_upload_overlay_state` (после строки `self._story_editor_escape_iter = 0`):

```python
        self._contacts_sync_iter = 0  # WP#223 H2.1 contacts-sync modal dismiss counter
```

- [ ] **Step 4: Запустить — убедиться что зелёный**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_contacts_sync_modal.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Вписать дисмисс-обработчик в wait-loop**

В `_wait_upload_confirmation`, СРАЗУ ПОСЛЕ блока notif-обработчика (заканчивается `self.adb('input keyevent KEYCODE_BACK'); time.sleep(2); continue` ~3705), добавить:

```python
            # === [WP#223 H2.1] TikTok: in-app «Синхронизируйте контакты» ===
            # Dismiss-only (НЕ доказательство публикации): тап «Не разрешать»
            # (fallback BACK) → снимаем оверлей, success подтверждают navbar-shell
            # / UPLOAD_OK на след. итерации. Cap → перестаём долбить.
            if (os.environ.get('TT_CONTACTS_SYNC_MODAL_DISMISS_ENABLED', 'true').lower()
                    == 'true' and self._detect_tt_contacts_sync_modal(ui)):
                self._contacts_sync_iter += 1
                if self._contacts_sync_iter <= self.MAX_TT_CONTACTS_SYNC_ITERATIONS:
                    method = 'tap_deny'
                    if not self.tap_element(ui, ['Не разрешать', "Don't allow"]):
                        self.adb('input keyevent KEYCODE_BACK')
                        method = 'keycode_back'
                    self.log_event(
                        'info',
                        f'TikTok: contacts-sync modal dismiss (wait {wait})',
                        meta={'category': 'tt_contacts_sync_modal_dismissed',
                              'platform': self.platform, 'step': 'wait_upload',
                              'wait_iter': wait, 'attempt': self._contacts_sync_iter,
                              'dismiss_method': method},
                    )
                    time.sleep(2)
                    continue
```

- [ ] **Step 6: Запустить полный TT-набор (регрессия)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_*.py -q`
Expected: PASS (все зелёные, как до правок + новые)

- [ ] **Step 7: Коммит**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_contacts_sync_modal.py
git commit -m "feat(wp223): wire contacts-sync modal dismiss в wait-loop (H2.1, kill-switch TT_CONTACTS_SYNC_MODAL_DISMISS_ENABLED)"
```

---

## Task 3: Компонент B — классификатор `_tt_left_editor_activity`

**Files:**
- Modify: `publisher_tiktok.py` (метод рядом с `_tt_foreground_pkg` ~912)
- Test: `tests/test_publisher_tt_postmortem_probe.py` (create)

Классификатор использует уже существующие константы: `TT_COMPOSER_ACTIVITIES_SEED` (blacklist editor/composer, module-level ~67) и подтверждённые shell-активности `MainActivity`/`DetailActivity`. Консервативно: True ТОЛЬКО при TT-пакете + shell-активности + отсутствии composer-активности.

- [ ] **Step 1: Написать падающий тест**

Create `tests/test_publisher_tt_postmortem_probe.py` (заголовок-конвенции из секции выше + ниже):

```python
def test_left_editor_true_on_main_activity():
    """TT-пакет + MainActivity (фид/профиль) → ушли из редактора."""
    mx = _bare_mixin()
    act = 'topResumedActivity: ActivityRecord{abc u0 com.zhiliaoapp.musically/.main.MainActivity t123}'
    assert mx._tt_left_editor_activity(act) is True


def test_left_editor_true_on_detail_activity():
    """DetailActivity (открытое видео) → ушли из редактора."""
    mx = _bare_mixin()
    act = 'topResumedActivity: ActivityRecord{abc u0 com.zhiliaoapp.musically/.detail.DetailActivity t123}'
    assert mx._tt_left_editor_activity(act) is True


def test_left_editor_false_on_publish_activity():
    """Всё ещё в редакторе (PublishActivity) → НЕ ушли."""
    mx = _bare_mixin()
    act = 'topResumedActivity: ActivityRecord{abc u0 com.zhiliaoapp.musically/.publish.PublishActivity t123}'
    assert mx._tt_left_editor_activity(act) is False


def test_left_editor_false_on_non_tt_foreground():
    """Не-TT пакет (лаунчер) → не доказывает уход в TT-shell → False."""
    mx = _bare_mixin()
    act = 'topResumedActivity: ActivityRecord{abc u0 com.sec.android.app.launcher/.Launcher t1}'
    assert mx._tt_left_editor_activity(act) is False


def test_left_editor_false_on_empty():
    mx = _bare_mixin()
    assert mx._tt_left_editor_activity('') is False
    assert mx._tt_left_editor_activity(None) is False
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_postmortem_probe.py -q`
Expected: FAIL — `AttributeError: ... '_tt_left_editor_activity'`

- [ ] **Step 3: Добавить классификатор**

В `publisher_tiktok.py` сразу после `_tt_foreground_pkg` (заканчивается ~923):

```python
    # TT-пакеты (musically RU / trill global) — для post-mortem пробы.
    _TT_PACKAGES = ('com.zhiliaoapp.musically', 'com.ss.android.ugc.trill')
    # Shell-активности, подтверждённые в коде как НЕ-редактор (фид/профиль/видео).
    _TT_SHELL_ACTIVITIES = ('MainActivity', 'DetailActivity')

    def _tt_left_editor_activity(self, top_resumed_activity) -> bool:
        """[WP#223 H2.2] Ушли ли мы из upload/editor-активности на главную
        shell (фид/профиль/видео) — по topResumedActivity (ground-truth, не
        зависит от stale uiautomator).

        Консервативно: True ТОЛЬКО при TT-пакете + shell-активности
        (_TT_SHELL_ACTIVITIES) + отсутствии composer-активности
        (TT_COMPOSER_ACTIVITIES_SEED). Иначе False (включая не-TT foreground).
        """
        if not top_resumed_activity:
            return False
        act = str(top_resumed_activity)
        if not any(pkg in act for pkg in self._TT_PACKAGES):
            return False
        if any(c in act for c in TT_COMPOSER_ACTIVITIES_SEED):
            return False
        return any(s in act for s in self._TT_SHELL_ACTIVITIES)
```

- [ ] **Step 4: Запустить — убедиться что зелёный**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_postmortem_probe.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Коммит**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_postmortem_probe.py
git commit -m "feat(wp223): _tt_left_editor_activity activity-классификатор (H2.2)"
```

---

## Task 4: Компонент B — проба `_tt_postmortem_left_editor_probe` + env-helper

**Files:**
- Modify: `publisher_tiktok.py` (module-level helper рядом с другими module-функциями ~80; метод рядом с классификатором)
- Test: `tests/test_publisher_tt_postmortem_probe.py` (append)

- [ ] **Step 1: Написать падающие тесты**

Append в `tests/test_publisher_tt_postmortem_probe.py`:

```python
import publisher_tiktok as _ptt


def test_postmortem_probe_confirms_on_shell(monkeypatch):
    """dumpsys показывает MainActivity → проба возвращает True (transit)."""
    monkeypatch.setenv('TT_UPLOAD_POSTMORTEM_GRACE_S', '5')
    monkeypatch.setenv('TT_UPLOAD_POSTMORTEM_POLL_S', '0.1')
    mx = _bare_mixin()
    mx.adb = MagicMock(return_value=(
        'topResumedActivity: ActivityRecord{a u0 com.zhiliaoapp.musically/.main.MainActivity t1}'))
    assert mx._tt_postmortem_left_editor_probe() is True


def test_postmortem_probe_false_when_still_editor(monkeypatch):
    """dumpsys всё время показывает PublishActivity → проба False (честный fail)."""
    monkeypatch.setenv('TT_UPLOAD_POSTMORTEM_GRACE_S', '0.3')
    monkeypatch.setenv('TT_UPLOAD_POSTMORTEM_POLL_S', '0.1')
    mx = _bare_mixin()
    mx.adb = MagicMock(return_value=(
        'topResumedActivity: ActivityRecord{a u0 com.zhiliaoapp.musically/.publish.PublishActivity t1}'))
    assert mx._tt_postmortem_left_editor_probe() is False


def test_safe_float_env_clamps_and_defaults(monkeypatch):
    monkeypatch.delenv('TT_X_GRACE', raising=False)
    assert _ptt._tt_safe_float_env('TT_X_GRACE', 20.0) == 20.0
    monkeypatch.setenv('TT_X_GRACE', 'нечисло')
    assert _ptt._tt_safe_float_env('TT_X_GRACE', 20.0) == 20.0
    monkeypatch.setenv('TT_X_GRACE', '0.01')
    assert _ptt._tt_safe_float_env('TT_X_GRACE', 20.0) == 0.1
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_postmortem_probe.py -q`
Expected: FAIL — `AttributeError: '_tt_postmortem_left_editor_probe'` / `module ... has no attribute '_tt_safe_float_env'`

- [ ] **Step 3: Добавить module-level env-helper**

В `publisher_tiktok.py` рядом с другими module-level функциями (после `_matches_label`, ~80):

```python
def _tt_safe_float_env(var: str, default: float) -> float:
    """Безопасный float из env с дефолтом и нижним клампом 0.1 (WP#223 H2.2)."""
    try:
        value = float(os.environ.get(var, str(default)))
    except (ValueError, TypeError):
        return default
    if value < 0.1:
        return 0.1
    return value
```

(Убедиться что `import os` и `import time` уже на уровне модуля — они используются по всему файлу, так и есть.)

- [ ] **Step 4: Добавить метод пробы**

В `publisher_tiktok.py` сразу после `_tt_left_editor_activity`:

```python
    def _tt_postmortem_left_editor_probe(self) -> bool:
        """[WP#223 H2.2] Post-mortem проба на границе таймаута (зеркало WP#181).

        Когда uiautomator stale/нечитаем, а публикация реально прошла —
        поллит topResumedActivity (ground-truth). Если TT ушёл с editor/upload
        на shell-активность (_tt_left_editor_activity) за grace-окно → True
        (inferred success). Иначе False (честный fail).
        """
        grace = _tt_safe_float_env('TT_UPLOAD_POSTMORTEM_GRACE_S', 20.0)
        poll = _tt_safe_float_env('TT_UPLOAD_POSTMORTEM_POLL_S', 5.0)
        start = time.monotonic()
        it = 0
        while time.monotonic() - start < grace:
            it += 1
            try:
                act = self.adb(
                    'dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity',
                    timeout=5) or ''
            except Exception:
                act = ''
            if self._tt_left_editor_activity(act):
                self.log_event(
                    'info',
                    'TikTok: post-mortem transit out of editor confirmed',
                    meta={'category': 'tt_upload_postmortem_transit',
                          'platform': self.platform, 'step': 'wait_upload',
                          'top_activity': act.strip()[:200], 'iterations': it,
                          'grace_elapsed_s': round(time.monotonic() - start, 2)},
                )
                return True
            remaining = grace - (time.monotonic() - start)
            if remaining <= 0:
                break
            time.sleep(min(poll, max(0.0, remaining)))
            if it >= 100:
                break
        return False
```

- [ ] **Step 5: Запустить — убедиться что зелёный**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_postmortem_probe.py -q`
Expected: PASS (8 passed)

- [ ] **Step 6: Коммит**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_postmortem_probe.py
git commit -m "feat(wp223): _tt_postmortem_left_editor_probe + _tt_safe_float_env (H2.2)"
```

---

## Task 5: Компонент B — wiring пробы на границе таймаута

**Files:**
- Modify: `publisher_tiktok.py` (блок `if not upload_confirmed:` ~4174)

- [ ] **Step 1: Вписать пробу перед timeout-fail**

В `_wait_upload_confirmation` заменить начало блока. Было:

```python
        if not upload_confirmed:
            log.error('TikTok: подтверждения загрузки не получено за 3 мин')
            self._safe_kb_probe(self.dump_ui(), step='tt_upload_confirmation_timeout')
            self.log_event('error', 'TikTok: подтверждение загрузки не получено (3 мин timeout или ошибка кнопки)',
                            meta={'category': 'tt_upload_confirmation_timeout',
                                  'platform': self.platform, 'step': 'wait_upload'})
            return False
```

Стало:

```python
        if not upload_confirmed:
            # [WP#223 H2.2] Post-mortem dumpsys-проба перед честным fail: если
            # TT реально ушёл из редактора (публикация прошла, но uiautomator был
            # stale) — inferred success, как amplify/notif пути. Иначе — честный
            # таймаут как раньше.
            if (os.environ.get('TT_UPLOAD_POSTMORTEM_PROBE_ENABLED', 'true').lower()
                    == 'true' and self._tt_postmortem_left_editor_probe()):
                upload_confirmed = True
                inferred_path_used = True
                self.log_event(
                    'info',
                    'TikTok: upload подтверждён post-mortem пробой (reclassified)',
                    meta={'category': 'tt_upload_postmortem_success',
                          'platform': self.platform, 'step': 'wait_upload',
                          'reclassified_from': 'tt_upload_confirmation_timeout'},
                )
        if not upload_confirmed:
            log.error('TikTok: подтверждения загрузки не получено за 3 мин')
            self._safe_kb_probe(self.dump_ui(), step='tt_upload_confirmation_timeout')
            self.log_event('error', 'TikTok: подтверждение загрузки не получено (3 мин timeout или ошибка кнопки)',
                            meta={'category': 'tt_upload_confirmation_timeout',
                                  'platform': self.platform, 'step': 'wait_upload'})
            return False
```

- [ ] **Step 2: Запустить полный TT-набор (регрессия)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_*.py -q`
Expected: PASS (все зелёные)

- [ ] **Step 3: Коммит**

```bash
git add publisher_tiktok.py
git commit -m "feat(wp223): wire post-mortem пробу на границе таймаута (H2.2, kill-switch TT_UPLOAD_POSTMORTEM_PROBE_ENABLED)"
```

---

## Task 6: Компонент C1 — разведка источника DELETE тестбенч-задач

**Files:**
- Create: `docs/evidence/2026-06-04-wp223-testbench-delete-source.md` (в docs-worktree `/home/claude-user/wp223-tt-h2`)

Это investigation-таск (без кода). Цель — найти, кто удаляет `testbench=TRUE` строку из `publish_tasks` на стадии `awaiting_url`. Прод-DELETE отсутствует в autowarm и testbench-репо → искать вне.

- [ ] **Step 1: Проверить DB-триггеры/правила на `publish_tasks`**

Run (host-PG, localhost:5432 — НЕ Docker; креды из autowarm `.env`/`pg` хелпера):

```bash
cd /root/.openclaw/workspace-genri/autowarm
PSQL="psql -h localhost -p 5432 -U <user> -d <db>"  # подставить из .env (DATABASE_URL)
$PSQL -c "SELECT tgname, tgrelid::regclass, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid='publish_tasks'::regclass AND NOT tgisinternal;"
$PSQL -c "SELECT schemaname, tablename, rulename, definition FROM pg_rules WHERE tablename='publish_tasks';"
```

Записать вывод в evidence-файл (раздел «DB triggers/rules»).

- [ ] **Step 2: Проверить кроны и таймеры**

Run:

```bash
crontab -l 2>/dev/null; sudo crontab -l 2>/dev/null
systemctl list-timers --all 2>/dev/null | grep -iE 'publish|testbench|clean' || true
ls -la /etc/cron.d/ 2>/dev/null
grep -rn "DELETE FROM publish_tasks\|publish_tasks" /etc/cron.d/ /usr/local/bin/ 2>/dev/null | grep -i delete || true
```

Записать в evidence (раздел «Cron/timers»).

- [ ] **Step 3: Если источник не найден — поставить audit-логгер**

Создать временный statement-trigger, логирующий DELETE на `publish_tasks` (для отлова на следующем smoke). НЕ коммитить как постоянную миграцию — это диагностика:

```sql
CREATE OR REPLACE FUNCTION _wp223_audit_pt_delete() RETURNS trigger AS $$
BEGIN
  RAISE WARNING 'WP223-AUDIT: DELETE publish_tasks id=% status=% testbench=% by pid=% app=%',
    OLD.id, OLD.status, OLD.testbench, pg_backend_pid(),
    current_setting('application_name', true);
  RETURN OLD;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER _wp223_audit_pt_delete BEFORE DELETE ON publish_tasks
  FOR EACH ROW EXECUTE FUNCTION _wp223_audit_pt_delete();
```

Запустить smoke (`/usr/local/bin/testbench-start.sh` или canary), дождаться `awaiting_url`, снять `application_name`/pid из PG-логов → идентифицировать процесс. После — `DROP TRIGGER _wp223_audit_pt_delete ON publish_tasks; DROP FUNCTION _wp223_audit_pt_delete();`.

- [ ] **Step 4: Зафиксировать вывод + рекомендацию формы гарда**

Дописать в evidence: точный источник DELETE + рекомендованная форма гарда для Task 7 (внешний крон → условие по статусу; либо защитный BEFORE DELETE триггер).

- [ ] **Step 5: Коммит evidence (docs-worktree)**

```bash
cd /home/claude-user/wp223-tt-h2
git add docs/evidence/2026-06-04-wp223-testbench-delete-source.md
git commit -m "docs(wp223): разведка источника тестбенч-DELETE (C1)"
```

---

## Task 7: Компонент C2 — гард на не-удаление до терминала

**Files (зависят от вывода C1):**
- Если внешний крон/скрипт: Modify найденный источник + его тест.
- Если форма «защитный триггер» (fallback): Create `migrations/20260604_wp223_testbench_delete_guard.sql` + `migrations/20260604_wp223_testbench_delete_guard__rollback.sql` + Test: `tests/test_wp223_testbench_delete_guard.py`.

Ниже — **fallback-вариант (защитный BEFORE DELETE триггер)**, если C1 показал, что источник вне нашего кода/неустраним точечно. Если C1 нашёл конкретный крон/скрипт — вместо триггера добавить в его DELETE условие `AND status IN ('done','failed','published_no_url','cancelled')` (терминальные) и тест на это; тогда шаги ниже не применяются.

- [ ] **Step 1: Написать падающий тест гарда**

Create `tests/test_wp223_testbench_delete_guard.py`:

```python
"""WP#223 C2: защитный гард — нельзя удалять testbench-строку до терминала."""
from __future__ import annotations
import os
import psycopg2
import pytest

DSN = os.environ.get('DATABASE_URL')

@pytest.mark.skipif(not DSN, reason='no DATABASE_URL')
def test_pre_terminal_testbench_delete_blocked():
    conn = psycopg2.connect(DSN); conn.autocommit = False
    cur = conn.cursor()
    cur.execute("""INSERT INTO publish_tasks (testbench, status, platform, created_at, updated_at)
                   VALUES (TRUE, 'awaiting_url', 'TikTok', NOW(), NOW()) RETURNING id""")
    tid = cur.fetchone()[0]
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute("DELETE FROM publish_tasks WHERE id=%s", (tid,))
    conn.rollback()
    # терминальный статус — удаление разрешено
    cur.execute("UPDATE publish_tasks SET status='done' WHERE id=%s", (tid,))
    cur.execute("DELETE FROM publish_tasks WHERE id=%s", (tid,))
    conn.commit(); cur.close(); conn.close()
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && DATABASE_URL=<dsn> python -m pytest tests/test_wp223_testbench_delete_guard.py -q`
Expected: FAIL — удаление pre-terminal НЕ блокируется (no RaiseException)

- [ ] **Step 3: Написать миграцию-гард**

Create `migrations/20260604_wp223_testbench_delete_guard.sql`:

```sql
-- WP#223 C2: не удалять тестбенч-задачи до терминального статуса (теряются
-- результаты/скринкасты). Гард ТОЛЬКО для testbench=TRUE; прод-строки не трогает.
CREATE OR REPLACE FUNCTION _wp223_guard_testbench_delete() RETURNS trigger AS $$
BEGIN
  IF COALESCE(OLD.testbench, FALSE)
     AND OLD.status NOT IN ('done','failed','published_no_url','cancelled') THEN
    RAISE EXCEPTION 'WP223: запрет удаления testbench-задачи id=% в pre-terminal статусе %',
      OLD.id, OLD.status;
  END IF;
  RETURN OLD;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS _wp223_guard_testbench_delete ON publish_tasks;
CREATE TRIGGER _wp223_guard_testbench_delete BEFORE DELETE ON publish_tasks
  FOR EACH ROW EXECUTE FUNCTION _wp223_guard_testbench_delete();
```

Create `migrations/20260604_wp223_testbench_delete_guard__rollback.sql`:

```sql
DROP TRIGGER IF EXISTS _wp223_guard_testbench_delete ON publish_tasks;
DROP FUNCTION IF EXISTS _wp223_guard_testbench_delete();
```

- [ ] **Step 4: Применить миграцию**

Run: `cd /root/.openclaw/workspace-genri/autowarm && psql <DSN> -f migrations/20260604_wp223_testbench_delete_guard.sql`
Expected: `CREATE FUNCTION` / `CREATE TRIGGER`

- [ ] **Step 5: Запустить — убедиться что зелёный**

Run: `cd /root/.openclaw/workspace-genri/autowarm && DATABASE_URL=<dsn> python -m pytest tests/test_wp223_testbench_delete_guard.py -q`
Expected: PASS

- [ ] **Step 6: Коммит**

```bash
git add migrations/20260604_wp223_testbench_delete_guard.sql migrations/20260604_wp223_testbench_delete_guard__rollback.sql tests/test_wp223_testbench_delete_guard.py
git commit -m "feat(wp223): гард на не-удаление testbench-задач до терминала (C2)"
```

---

## Task 8: Полная регрессия + подготовка к деплою

- [ ] **Step 1: Прогнать весь TT-набор + новые файлы**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_publisher_tt_*.py tests/test_wp223_*.py -q`
Expected: PASS (все зелёные, 0 фейлов)

- [ ] **Step 2: Проверить kill-switch'и (env-гейты на месте)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && grep -n "TT_CONTACTS_SYNC_MODAL_DISMISS_ENABLED\|TT_UPLOAD_POSTMORTEM_PROBE_ENABLED" publisher_tiktok.py`
Expected: оба флага присутствуют, default `'true'`.

- [ ] **Step 3: Сводка для PR**

Подготовить тело PR в `delivery-contenthunter`: что меняется (A/B/C), kill-switch'и, как откатить (env=false / rollback-миграция), результаты тестов. Деплой: python publisher спавнится per-task → git pull в прод-каталог, PM2-restart НЕ нужен для publisher_tiktok.py. Для миграции C2 — применить на host-PG.

- [ ] **Step 4: Финальный коммит (если остались доки)**

```bash
git add -A && git commit -m "chore(wp223): финальная регрессия + PR-заметки" || true
```

---

## Порядок и зависимости

- Tasks 1→2 (компонент A) — независимы от B и C.
- Tasks 3→4→5 (компонент B) — независимы от A и C.
- Task 6 (C1 разведка) → Task 7 (C2 гард, форма зависит от C1).
- Task 8 — после всех.
- A и B можно делать параллельно; C идёт своим треком (разведка не блокирует A/B).
