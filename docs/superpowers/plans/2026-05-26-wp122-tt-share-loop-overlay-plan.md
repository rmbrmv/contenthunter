# WP #122 — TT share-loop «Добавить в историю» overlay dismiss — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Гасить окно «Добавить в историю» (Samsung Add-to-Story + TT in-app Stories) в share-loop перед поиском кнопки «Опубликовать», переиспользуя существующие wait_upload-хендлеры, под выключателем default OFF (тёмный выкат).

**Architecture:** Новый orchestrator `_run_tt_stories_overlay_share_loop_hook` (зеркало `_run_tt_commercial_music_hook`) вызывает существующие `_detect/_handle_samsung_stories_overlay` и `_detect/_handle_tt_inapp_stories`. Хендлеры получают необязательный `phase`-параметр (влияет только на `step` события; default сохраняет wait_upload-поведение byte-for-byte). Один новый env-флаг `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED` (default `'false'`). wait_upload-ветка не трогается.

**Tech Stack:** Python 3, `publisher_tiktok.py` (`TikTokMixin`) в репо `GenGo2/delivery-contenthunter` (autowarm), pytest, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-05-26-wp122-tt-share-loop-overlay-design.md`
**Rollout decision (WP #122 #605):** dark OFF → testbench happy-path смок → ручное включение.

---

## Pre-flight (execution-time, не задача-коммит)

Реализация идёт в **GenGo2/delivery-contenthunter** (НЕ в `rmbrmv/contenthunter`, где лежит этот план). Прод autowarm двигается активно — обязателен свежий fetch.

```bash
# Создать изолированный worktree off свежего origin/main репо autowarm.
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git worktree add /home/claude-user/autowarm-wt-wp122 -b wp122-tt-share-loop-overlay origin/main
cd /home/claude-user/autowarm-wt-wp122
# Песочница для тестов (без node_modules — правки Python-only):
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py -q   # baseline зелёный
```
Ожидаемо: существующие overlay-тесты зелёные (baseline до правок).

---

## File Structure

- **Modify** `publisher_tiktok.py`:
  - `_handle_samsung_stories_overlay` (≈`:489`) — добавить `phase: str = 'wait_upload'`, заменить два литерала `'step': 'wait_upload'` на `'step': _step`.
  - `_handle_tt_inapp_stories` (≈`:566`) — то же.
  - Новый метод `_run_tt_stories_overlay_share_loop_hook` — рядом с `_run_tt_commercial_music_hook` (≈`:1445`).
  - Call-site в `publish_tiktok` share-loop (≈`:1888`, сразу после commercial-music hook).
- **Create** `tests/test_publisher_tt_share_loop_overlay.py` — все unit/structure тесты этой фичи.

---

## Task 1: `phase`-параметр для `_handle_samsung_stories_overlay`

**Files:**
- Modify: `publisher_tiktok.py` (метод `_handle_samsung_stories_overlay`, ≈`:489-564`)
- Test: `tests/test_publisher_tt_share_loop_overlay.py`

- [ ] **Step 1: Создать тест-файл с харнесом и написать падающие тесты**

Создать `tests/test_publisher_tt_share_loop_overlay.py`:

```python
"""WP #122 — TT share-loop «Добавить в историю» overlay dismiss.

Spec: docs/superpowers/specs/2026-05-26-wp122-tt-share-loop-overlay-design.md
Plan: docs/superpowers/plans/2026-05-26-wp122-tt-share-loop-overlay-plan.md
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest  # noqa: F401

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


def _samsung_xml() -> str:
    return _xml([
        {'text': 'Добавить в историю', 'bounds': '[200,80][520,160]'},
        {'text': 'Аа', 'bounds': '[80,300][200,420]'},
        {'text': 'Флип', 'bounds': '[400,300][520,420]'},
        {'content-desc': 'Закрыть', 'bounds': '[20,80][120,180]', 'clickable': 'true'},
    ])


def _metas(mx) -> list[dict]:
    return [c.kwargs.get('meta', {}) for c in mx.log_event.call_args_list]


# ── Task 1: Samsung handler phase param ──

def test_samsung_handler_phase_share_loop_sets_step():
    mx = _bare_mixin()
    assert mx._handle_samsung_stories_overlay(_samsung_xml(), wait=0,
                                              phase='share_loop') is True
    steps = {m.get('step') for m in _metas(mx)
             if m.get('category') in ('tt_samsung_overlay_detected',
                                      'tt_samsung_overlay_dismiss_attempt')}
    assert steps == {'tt_5_share_loop'}


def test_samsung_handler_default_phase_unchanged():
    """Default phase → step='wait_upload', НЕТ ключа 'phase' (payload byte-for-byte)."""
    mx = _bare_mixin()
    assert mx._handle_samsung_stories_overlay(_samsung_xml(), wait=0) is True
    for m in _metas(mx):
        if m.get('category') in ('tt_samsung_overlay_detected',
                                 'tt_samsung_overlay_dismiss_attempt'):
            assert m.get('step') == 'wait_upload'
            assert 'phase' not in m
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 -m pytest tests/test_publisher_tt_share_loop_overlay.py -q`
Expected: FAIL — `test_samsung_handler_phase_share_loop_sets_step` падает с `TypeError: _handle_samsung_stories_overlay() got an unexpected keyword argument 'phase'`.

- [ ] **Step 3: Добавить `phase`-параметр в `_handle_samsung_stories_overlay`**

В сигнатуре:
```python
    def _handle_samsung_stories_overlay(self, ui_xml: str, wait: int,
                                        phase: str = 'wait_upload') -> bool:
```
Сразу после `n = self._samsung_overlay_iter`:
```python
        _step = 'tt_5_share_loop' if phase == 'share_loop' else 'wait_upload'
```
Заменить ОБА вхождения `'step': 'wait_upload',` в `log_event`-вызовах этого метода (событие `tt_samsung_overlay_detected` и `tt_samsung_overlay_dismiss_attempt`) на `'step': _step,`. **Не** добавлять ключ `'phase'`. Stuck-ветку (`'step': 'tt_5_samsung_overlay_stuck'` + `set_step`) НЕ трогать.

- [ ] **Step 4: Запустить — убедиться, что прошло (и старые тесты тоже)**

Run: `python3 -m pytest tests/test_publisher_tt_share_loop_overlay.py tests/test_publisher_tt_overlay_handlers.py -q`
Expected: PASS (новые 2 + все существующие overlay-тесты зелёные).

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_share_loop_overlay.py
git commit -m "feat(wp122): phase param on _handle_samsung_stories_overlay (step-only, payload-safe)"
```

---

## Task 2: `phase`-параметр для `_handle_tt_inapp_stories`

**Files:**
- Modify: `publisher_tiktok.py` (метод `_handle_tt_inapp_stories`, ≈`:566-626`)
- Test: `tests/test_publisher_tt_share_loop_overlay.py`

- [ ] **Step 1: Добавить падающие тесты**

Дописать в `tests/test_publisher_tt_share_loop_overlay.py`:

```python
def _inapp_xml() -> str:
    return _xml([
        {'text': 'Ваша история', 'bounds': '[60,2200][320,2280]', 'clickable': 'true'},
        {'text': 'Далее', 'bounds': '[440,2200][1020,2280]', 'clickable': 'true'},
        {'content-desc': 'Автомонтаж', 'bounds': '[400,2050][720,2120]'},
        {'content-desc': 'Назад', 'bounds': '[20,80][100,160]', 'clickable': 'true'},
    ])


def test_inapp_handler_phase_share_loop_sets_step():
    mx = _bare_mixin()
    assert mx._handle_tt_inapp_stories(_inapp_xml(), wait=0, phase='share_loop') is True
    steps = {m.get('step') for m in _metas(mx)
             if m.get('category') in ('tt_inapp_stories_detected',
                                      'tt_inapp_stories_dismiss_attempt')}
    assert steps == {'tt_5_share_loop'}


def test_inapp_handler_default_phase_unchanged():
    mx = _bare_mixin()
    assert mx._handle_tt_inapp_stories(_inapp_xml(), wait=0) is True
    for m in _metas(mx):
        if m.get('category') in ('tt_inapp_stories_detected',
                                 'tt_inapp_stories_dismiss_attempt'):
            assert m.get('step') == 'wait_upload'
            assert 'phase' not in m
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 -m pytest tests/test_publisher_tt_share_loop_overlay.py::test_inapp_handler_phase_share_loop_sets_step -q`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'phase'`.

- [ ] **Step 3: Добавить `phase`-параметр в `_handle_tt_inapp_stories`**

Сигнатура:
```python
    def _handle_tt_inapp_stories(self, ui_xml: str, wait: int,
                                 phase: str = 'wait_upload') -> bool:
```
После `n = self._inapp_stories_iter`:
```python
        _step = 'tt_5_share_loop' if phase == 'share_loop' else 'wait_upload'
```
Заменить ОБА `'step': 'wait_upload',` (события `tt_inapp_stories_detected` и `tt_inapp_stories_dismiss_attempt`) на `'step': _step,`. Stuck-ветку (`'tt_5_inapp_stories_stuck'`) НЕ трогать. Ключ `'phase'` НЕ добавлять.

- [ ] **Step 4: Запустить — pass**

Run: `python3 -m pytest tests/test_publisher_tt_share_loop_overlay.py tests/test_publisher_tt_overlay_handlers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_share_loop_overlay.py
git commit -m "feat(wp122): phase param on _handle_tt_inapp_stories (step-only, payload-safe)"
```

---

## Task 3: Orchestrator `_run_tt_stories_overlay_share_loop_hook`

**Files:**
- Modify: `publisher_tiktok.py` (новый метод рядом с `_run_tt_commercial_music_hook`, ≈`:1445`)
- Test: `tests/test_publisher_tt_share_loop_overlay.py`

- [ ] **Step 1: Написать падающие тесты orchestrator'а**

Дописать в тест-файл:

```python
import os  # noqa: E402

FLAG = 'TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED'


def test_hook_disabled_by_default(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    mx = _bare_mixin()
    mx._detect_samsung_stories_overlay = MagicMock(return_value=True)
    mx._detect_tt_inapp_stories = MagicMock(return_value=True)
    assert mx._run_tt_stories_overlay_share_loop_hook(_samsung_xml(), 0) == 'clean'
    mx._detect_samsung_stories_overlay.assert_not_called()
    mx.adb_tap.assert_not_called()
    mx.adb.assert_not_called()


def test_hook_clean_when_no_overlay(monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    mx = _bare_mixin()
    plain = _xml([{'text': 'Опубликовать', 'bounds': '[400,2000][680,2100]',
                   'clickable': 'true'}])
    assert mx._run_tt_stories_overlay_share_loop_hook(plain, 0) == 'clean'
    mx.adb_tap.assert_not_called()


def test_hook_samsung_handled(monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    mx = _bare_mixin()
    assert mx._run_tt_stories_overlay_share_loop_hook(_samsung_xml(), 0) == 'handled'
    assert mx._samsung_overlay_iter == 1
    mx.adb_tap.assert_called_with(70, 130)  # center of [20,80][120,180]


def test_hook_inapp_handled(monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    mx = _bare_mixin()
    assert mx._run_tt_stories_overlay_share_loop_hook(_inapp_xml(), 0) == 'handled'
    assert mx._inapp_stories_iter == 1


def test_hook_samsung_priority_over_inapp(monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    mx = _bare_mixin()
    mx._detect_samsung_stories_overlay = MagicMock(return_value=True)
    mx._detect_tt_inapp_stories = MagicMock(return_value=True)
    mx._handle_samsung_stories_overlay = MagicMock(return_value=True)
    mx._handle_tt_inapp_stories = MagicMock(return_value=True)
    assert mx._run_tt_stories_overlay_share_loop_hook('<x/>', 0) == 'handled'
    mx._handle_samsung_stories_overlay.assert_called_once()
    mx._handle_tt_inapp_stories.assert_not_called()


def test_hook_samsung_stuck_at_cap(monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    mx = _bare_mixin()
    mx._samsung_overlay_iter = TikTokMixin.MAX_SAMSUNG_OVERLAY_ITERATIONS
    assert mx._run_tt_stories_overlay_share_loop_hook(_samsung_xml(), 0) == 'stuck'
    mx.set_step.assert_called_with('tt_5_samsung_overlay_stuck')
    cats = [m.get('category') for m in _metas(mx)]
    assert 'tt_samsung_overlay_stuck' in cats


def test_hook_inapp_stuck_at_cap(monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    mx = _bare_mixin()
    mx._inapp_stories_iter = TikTokMixin.MAX_INAPP_STORIES_ITERATIONS
    assert mx._run_tt_stories_overlay_share_loop_hook(_inapp_xml(), 0) == 'stuck'
    cats = [m.get('category') for m in _metas(mx)]
    assert 'tt_inapp_stories_stuck' in cats


def test_hook_emits_dismissed_with_phase_after_recovery(monkeypatch):
    monkeypatch.setenv(FLAG, 'true')
    mx = _bare_mixin()
    mx._samsung_overlay_iter = 2  # был оверлей в прошлом проходе
    plain = _xml([{'text': 'Опубликовать', 'bounds': '[400,2000][680,2100]',
                   'clickable': 'true'}])
    assert mx._run_tt_stories_overlay_share_loop_hook(plain, 3) == 'clean'
    assert mx._samsung_overlay_iter == 0  # сброшен
    dismissed = [m for m in _metas(mx)
                 if m.get('category') == 'tt_samsung_overlay_dismissed']
    assert len(dismissed) == 1
    assert dismissed[0].get('step') == 'tt_5_share_loop'
    assert dismissed[0].get('phase') == 'share_loop'
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 -m pytest tests/test_publisher_tt_share_loop_overlay.py -k hook -q`
Expected: FAIL — `AttributeError: 'TikTokMixin' object has no attribute '_run_tt_stories_overlay_share_loop_hook'`.

- [ ] **Step 3: Реализовать orchestrator**

Добавить в `publisher_tiktok.py` рядом с `_run_tt_commercial_music_hook` (после него):

```python
    def _run_tt_stories_overlay_share_loop_hook(self, ui_xml: str,
                                                attempt: int) -> str:
        """Dismiss Samsung "Add to Story" / TT in-app Stories overlay in share_loop.

        WP #122: переиспользует существующие wait_upload detect+handle. Отдельный
        kill-switch (default OFF) — wait_upload не затронут, основной путь
        включается осознанно после testbench-смока.

        Returns:
          'handled' — оверлей был, dismiss-шаг отправлен (caller: sleep+continue).
          'stuck'   — счётчик > MAX, событие tt_*_stuck записано (caller: return False).
          'clean'   — оверлея нет или выключатель OFF (caller: обычная логика).
        """
        if (os.environ.get('TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED', 'false').lower()
                != 'true'):
            return 'clean'

        # Samsung "Добавить в историю" overlay (приоритет над in-app).
        if self._detect_samsung_stories_overlay(ui_xml):
            if not self._handle_samsung_stories_overlay(ui_xml, attempt,
                                                        phase='share_loop'):
                return 'stuck'
            return 'handled'
        if self._samsung_overlay_iter > 0:
            self.log_event(
                'info', 'TikTok: Samsung overlay dismissed successfully (share_loop)',
                meta={'category': 'tt_samsung_overlay_dismissed',
                      'platform': self.platform, 'step': 'tt_5_share_loop',
                      'phase': 'share_loop', 'attempts': self._samsung_overlay_iter,
                      'wait_iter': attempt})
            self._samsung_overlay_iter = 0

        # TT in-app Stories editor.
        if self._detect_tt_inapp_stories(ui_xml):
            if not self._handle_tt_inapp_stories(ui_xml, attempt,
                                                 phase='share_loop'):
                return 'stuck'
            return 'handled'
        if self._inapp_stories_iter > 0:
            self.log_event(
                'info', 'TikTok: in-app Stories dismissed successfully (share_loop)',
                meta={'category': 'tt_inapp_stories_dismissed',
                      'platform': self.platform, 'step': 'tt_5_share_loop',
                      'phase': 'share_loop', 'attempts': self._inapp_stories_iter,
                      'wait_iter': attempt})
            self._inapp_stories_iter = 0

        return 'clean'
```

Убедиться, что `import os` уже есть в начале файла (используется другими хендлерами — есть).

- [ ] **Step 4: Запустить — pass**

Run: `python3 -m pytest tests/test_publisher_tt_share_loop_overlay.py -q`
Expected: PASS (все тесты orchestrator'а + Task 1/2 зелёные).

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_share_loop_overlay.py
git commit -m "feat(wp122): _run_tt_stories_overlay_share_loop_hook (reuse handlers, kill-switch OFF)"
```

---

## Task 4: Wire orchestrator в share-loop + structural guards

**Files:**
- Modify: `publisher_tiktok.py` (`publish_tiktok` share-loop, ≈`:1883-1888`)
- Test: `tests/test_publisher_tt_share_loop_overlay.py`

- [ ] **Step 1: Написать падающие structural-тесты**

Дописать в тест-файл (source-level locks — паттерн как `test_loop_integration_lines_present_and_in_order`):

```python
import inspect  # noqa: E402


def test_share_loop_hook_wired_after_commercial_music():
    """Хук вызван в share-loop, ПОСЛЕ commercial-music и ДО поиска кнопки."""
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    cm_idx = src.find("_run_tt_commercial_music_hook(ui, 'share_loop')")
    hook_idx = src.find('_run_tt_stories_overlay_share_loop_hook(ui, attempt)')
    btn_idx = src.find("exact_post =")
    assert -1 < cm_idx < hook_idx < btn_idx, (
        'share-loop overlay hook must be wired between commercial-music hook '
        'and the publish-button search'
    )


def test_share_loop_hook_handles_stuck_and_handled():
    """Call-site обрабатывает оба сигнала: handled→continue, stuck→return False."""
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    seg = src[src.find('_run_tt_stories_overlay_share_loop_hook(ui, attempt)'):]
    seg = seg[:400]
    assert "== 'handled'" in seg
    assert "== 'stuck'" in seg
    assert 'return False' in seg


def test_wait_upload_block_untouched():
    """wait_upload Samsung/in-app вызовы остаются с bare `ui` (не share_loop)."""
    src = inspect.getsource(TikTokMixin)
    assert '_detect_samsung_stories_overlay(ui)' in src
    assert '_detect_tt_inapp_stories(ui)' in src
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 -m pytest tests/test_publisher_tt_share_loop_overlay.py::test_share_loop_hook_wired_after_commercial_music -q`
Expected: FAIL — `hook_idx == -1` (вызов ещё не добавлен), assert падает.

- [ ] **Step 3: Вставить call-site в share-loop**

В `publish_tiktok`, в цикле `for attempt in range(8):`, сразу ПОСЛЕ блока commercial-music hook (после `if _cm_res == 'stuck': return False`) и ДО защиты геолокации:

```python
            # WP #122 (2026-05-26): «Добавить в историю» overlay during share_loop.
            # Reuses wait_upload Samsung/in-app-stories handlers; kill-switch
            # TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED default OFF (dark launch —
            # enable after testbench smoke).
            _ov_res = self._run_tt_stories_overlay_share_loop_hook(ui, attempt)
            if _ov_res == 'handled':
                time.sleep(1.5)
                continue
            if _ov_res == 'stuck':
                return False
```

- [ ] **Step 4: Запустить — pass (вся фича + regression suite)**

Run: `python3 -m pytest tests/test_publisher_tt_share_loop_overlay.py tests/test_publisher_tt_overlay_handlers.py tests/test_publisher_tt_commercial_music_modal.py tests/test_publisher_tt_wait_upload_integration.py -q`
Expected: PASS (новые structural + все TT-regression зелёные; особенно `test_loop_integration_lines_present_and_in_order` — порядок wait_upload не сломан).

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_share_loop_overlay.py
git commit -m "feat(wp122): wire share-loop overlay hook before publish-button search (OFF)"
```

---

## Task 5: Полный прогон + PR (чекпоинт перед деплоем)

- [ ] **Step 1: Полный TT-relevant suite**

Run: `python3 -m pytest tests/ -q -k "tt or overlay or publisher" 2>&1 | tail -20`
Expected: всё зелёное (или известные pre-existing fails, не связанные с правкой — зафиксировать какие).

- [ ] **Step 2: Sanity — флаг OFF не меняет поведение**

Подтвердить статически: без `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true` хук возвращает `'clean'` первым же `if` (`test_hook_disabled_by_default` это покрывает). Никаких прод-эффектов до включения.

- [ ] **Step 3: Push + PR (outward-facing — согласовать с Данилом перед push)**

```bash
git push -u origin wp122-tt-share-loop-overlay
gh pr create --repo GenGo2/delivery-contenthunter \
  --title "feat(wp122): TT share-loop «Добавить в историю» overlay dismiss (kill-switch OFF)" \
  --body "<см. шаблон ниже>"
```
PR body: ссылка на spec/plan, что переиспользуются существующие хендлеры, kill-switch default OFF, rollout = смок на testbench → ручное включение, список тестов.

- [ ] **Step 4: НЕ деплоить/не включать без отдельного ок** — деплой OFF, happy-path смок на testbench (#19/#171), затем `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true` + наблюдение. См. spec § Rollout.

---

## Self-Review (по skill-checklist)

**Spec coverage:** ✅ orchestrator (Task 3), phase-param payload-safe (Task 1/2), wire-in (Task 4), kill-switch OFF (Task 3 env default), observability dismissed+phase (Task 3 test), регресс-гард wait_upload (Task 1/2 default-phase тесты + Task 4 structural). Rollout/смок — Task 5 + spec.

**Placeholder scan:** ✅ нет TBD/«handle edge cases»; весь код и команды конкретны.

**Type consistency:** ✅ имена согласованы — `_run_tt_stories_overlay_share_loop_hook(ui_xml, attempt)` (метод) / `(ui, attempt)` (call-site, `ui`=локальная dump-переменная); хендлеры `(ui_xml, wait, phase='wait_upload')`; флаг `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED`; категории/`step` совпадают между spec, кодом и тестами. `_detect_*(ui_xml)` в orchestrator не конфликтует с source-order локом, ищущим `_detect_*(ui)`.
