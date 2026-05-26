# TikTok share-loop overlay-guard (WP #122) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть кнопку-перекрывающее окно «Добавить в историю» (Samsung Add-to-Story / TT in-app Stories) прямо во время share-loop публикации TikTok, переиспользуя существующие overlay-хендлеры под тёмным kill-switch.

**Architecture:** Новый метод-хелпер `_run_tt_share_loop_overlay_guard(ui, attempt)` (tri-state `'handled'/'stuck'/None`, по образцу `_run_tt_commercial_music_hook`) гейтится отдельным env-флагом `TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED` (default **OFF**). Вызывается в share-loop `publish_tiktok` только когда кнопка не найдена в XML (после `break`), перед слепым fallback. Внутри зовёт уже существующие `_detect/_handle_samsung_stories_overlay` и `_detect/_handle_tt_inapp_stories` с новым опциональным `phase='share_loop'`. wait_upload-хендлеры и их ON-флаги не трогаются.

**Tech Stack:** Python 3, autowarm (`GenGo2/delivery-contenthunter`), pytest, unittest.mock. Файл `publisher_tiktok.py`, класс `TikTokMixin`.

**Spec:** `docs/superpowers/specs/2026-05-26-tt-share-loop-overlay-guard-design.md`

**База:** ветка от `origin/main` репозитория `GenGo2/delivery-contenthunter` (на момент планирования `2d994db`; `publisher_tiktok.py` идентичен prod `f569f5d`). Якоря: `_handle_samsung_stories_overlay`=L489, `_handle_tt_inapp_stories`=L566, `_run_tt_commercial_music_hook`=L1445, `publish_tiktok`=L1620, `if _tapped_post:`=L1934, `if attempt >= 2:`=L1939.

**Где работать:** изолированный git-worktree от `origin/main` (НЕ в prod `/root/.openclaw/workspace-genri/autowarm` — там post-commit auto-push). Например `/home/claude-user/autowarm-testbench/.worktrees/wp122-tt-share-loop-overlay` (см. Task 0).

---

## Task 0: Изолированный worktree для кода

**Files:** —

- [ ] **Step 1: Создать worktree от свежего origin/main**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin --quiet
git worktree add -b wp122-tt-share-loop-overlay .worktrees/wp122-tt-share-loop-overlay origin/main
cd .worktrees/wp122-tt-share-loop-overlay
```

- [ ] **Step 2: Убедиться, что pytest зелёный на старте (baseline)**

Run: `cd /home/claude-user/autowarm-testbench/.worktrees/wp122-tt-share-loop-overlay && python -m pytest tests/test_publisher_tt_overlay_handlers.py -q`
Expected: PASS (все существующие TT-overlay тесты зелёные — baseline до правок).

> Все последующие задачи выполняются ВНУТРИ этого worktree. Пути тестов — относительные от его корня.

---

## Task 1: `phase`-параметр в `_handle_samsung_stories_overlay`

**Files:**
- Create: `tests/test_publisher_tt_share_loop_overlay_guard.py`
- Modify: `publisher_tiktok.py` (метод `_handle_samsung_stories_overlay`, ~L489–564)

- [ ] **Step 1: Завести новый тест-файл со скелетом и двумя тестами на phase**

Создать `tests/test_publisher_tt_share_loop_overlay_guard.py` с полным содержимым:

```python
"""Unit tests for TT share-loop overlay guard (WP #122, sub-mode A).

Переиспользование Samsung "Добавить в историю" + TT in-app Stories overlay
хендлеров ВО ВРЕМЯ share-loop (поиск кнопки публикации), под тёмным
kill-switch TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED (default OFF).

Spec:  docs/superpowers/specs/2026-05-26-tt-share-loop-overlay-guard-design.md
Plan:  docs/superpowers/plans/2026-05-26-tt-share-loop-overlay-guard.md
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


def _samsung_overlay_xml() -> str:
    return _xml([
        {'text': 'Добавить в историю', 'bounds': '[200,80][520,160]'},
        {'text': 'Аа', 'bounds': '[80,300][200,420]'},
        {'text': 'Флип', 'bounds': '[400,300][520,420]'},
        {'content-desc': 'Закрыть', 'bounds': '[20,80][120,180]',
         'clickable': 'true'},
    ])


def _inapp_stories_xml() -> str:
    return _xml([
        {'text': 'Ваша история', 'bounds': '[60,2200][320,2280]',
         'clickable': 'true'},
        {'text': 'Далее', 'bounds': '[440,2200][1020,2280]',
         'clickable': 'true'},
        {'content-desc': 'Автомонтаж', 'bounds': '[400,2050][720,2120]'},
    ])


def _clean_xml() -> str:
    return _xml([
        {'text': 'Опубликовать', 'bounds': '[700,2080][900,2180]',
         'clickable': 'true'},
    ])


# ── Task 1/2: phase param propagation ──

def test_samsung_handler_phase_share_loop_in_meta():
    mx = _bare_mixin()
    mx._handle_samsung_stories_overlay(_samsung_overlay_xml(), wait=0,
                                       phase='share_loop')
    steps = [c.kwargs.get('meta', {}).get('step')
             for c in mx.log_event.call_args_list]
    assert 'share_loop' in steps
    assert 'wait_upload' not in steps


def test_samsung_handler_phase_defaults_wait_upload():
    mx = _bare_mixin()
    mx._handle_samsung_stories_overlay(_samsung_overlay_xml(), wait=0)
    steps = [c.kwargs.get('meta', {}).get('step')
             for c in mx.log_event.call_args_list]
    assert 'wait_upload' in steps
    assert 'share_loop' not in steps
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают (TypeError на unexpected kwarg)**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py::test_samsung_handler_phase_share_loop_in_meta -v`
Expected: FAIL — `TypeError: _handle_samsung_stories_overlay() got an unexpected keyword argument 'phase'`.

- [ ] **Step 3: Добавить `phase` в сигнатуру `_handle_samsung_stories_overlay`**

В `publisher_tiktok.py` заменить строку:

```python
    def _handle_samsung_stories_overlay(self, ui_xml: str, wait: int) -> bool:
```

на:

```python
    def _handle_samsung_stories_overlay(self, ui_xml: str, wait: int,
                                        phase: str = 'wait_upload') -> bool:
```

- [ ] **Step 4: Прокинуть `phase` в meta обоих событий хендлера**

Заменить блок события `detected`:

```python
            self.log_event(
                'info', 'TikTok: Samsung "Добавить в историю" overlay detected',
                meta={'category': 'tt_samsung_overlay_detected',
                      'platform': self.platform, 'step': 'wait_upload',
                      'wait_iter': wait}
            )
```

на:

```python
            self.log_event(
                'info', 'TikTok: Samsung "Добавить в историю" overlay detected',
                meta={'category': 'tt_samsung_overlay_detected',
                      'platform': self.platform, 'step': phase,
                      'wait_iter': wait}
            )
```

И заменить блок события `dismiss_attempt`:

```python
        self.log_event(
            'info',
            f'TikTok: Samsung overlay dismiss attempt {n} via {strategy}',
            meta={'category': 'tt_samsung_overlay_dismiss_attempt',
                  'platform': self.platform, 'step': 'wait_upload',
                  'iteration': n, 'strategy': strategy, 'wait_iter': wait}
        )
```

на:

```python
        self.log_event(
            'info',
            f'TikTok: Samsung overlay dismiss attempt {n} via {strategy}',
            meta={'category': 'tt_samsung_overlay_dismiss_attempt',
                  'platform': self.platform, 'step': phase,
                  'iteration': n, 'strategy': strategy, 'wait_iter': wait}
        )
```

> Событие `tt_samsung_overlay_stuck` имеет свой `'step': 'tt_5_samsung_overlay_stuck'` — НЕ трогать.

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py -k samsung_handler_phase -v`
Expected: PASS (2 теста).

- [ ] **Step 6: Регресс существующих overlay-тестов**

Run: `python -m pytest tests/test_publisher_tt_overlay_handlers.py -q`
Expected: PASS (дефолт `phase='wait_upload'` сохраняет старое поведение).

- [ ] **Step 7: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_share_loop_overlay_guard.py
git commit -m "feat(wp122): phase param в _handle_samsung_stories_overlay"
```

---

## Task 2: `phase`-параметр в `_handle_tt_inapp_stories`

**Files:**
- Modify: `publisher_tiktok.py` (метод `_handle_tt_inapp_stories`, ~L566–626)
- Modify: `tests/test_publisher_tt_share_loop_overlay_guard.py` (добавить 2 теста)

- [ ] **Step 1: Добавить 2 теста на phase для in-app stories**

В конец `tests/test_publisher_tt_share_loop_overlay_guard.py` добавить:

```python
def test_inapp_stories_handler_phase_share_loop_in_meta():
    mx = _bare_mixin()
    mx._handle_tt_inapp_stories(_inapp_stories_xml(), wait=0, phase='share_loop')
    steps = [c.kwargs.get('meta', {}).get('step')
             for c in mx.log_event.call_args_list]
    assert 'share_loop' in steps
    assert 'wait_upload' not in steps


def test_inapp_stories_handler_phase_defaults_wait_upload():
    mx = _bare_mixin()
    mx._handle_tt_inapp_stories(_inapp_stories_xml(), wait=0)
    steps = [c.kwargs.get('meta', {}).get('step')
             for c in mx.log_event.call_args_list]
    assert 'wait_upload' in steps
    assert 'share_loop' not in steps
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py -k inapp_stories_handler_phase -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'phase'`.

- [ ] **Step 3: Добавить `phase` в сигнатуру `_handle_tt_inapp_stories`**

Заменить:

```python
    def _handle_tt_inapp_stories(self, ui_xml: str, wait: int) -> bool:
```

на:

```python
    def _handle_tt_inapp_stories(self, ui_xml: str, wait: int,
                                 phase: str = 'wait_upload') -> bool:
```

- [ ] **Step 4: Прокинуть `phase` в meta обоих событий**

Заменить блок `detected`:

```python
            self.log_event(
                'info', 'TikTok: in-app Stories editor detected',
                meta={'category': 'tt_inapp_stories_detected',
                      'platform': self.platform, 'step': 'wait_upload',
                      'wait_iter': wait}
            )
```

на:

```python
            self.log_event(
                'info', 'TikTok: in-app Stories editor detected',
                meta={'category': 'tt_inapp_stories_detected',
                      'platform': self.platform, 'step': phase,
                      'wait_iter': wait}
            )
```

И блок `dismiss_attempt`:

```python
        self.log_event(
            'info',
            f'TikTok: in-app Stories dismiss attempt {n} via {strategy}',
            meta={'category': 'tt_inapp_stories_dismiss_attempt',
                  'platform': self.platform, 'step': 'wait_upload',
                  'iteration': n, 'strategy': strategy, 'wait_iter': wait}
        )
```

на:

```python
        self.log_event(
            'info',
            f'TikTok: in-app Stories dismiss attempt {n} via {strategy}',
            meta={'category': 'tt_inapp_stories_dismiss_attempt',
                  'platform': self.platform, 'step': phase,
                  'iteration': n, 'strategy': strategy, 'wait_iter': wait}
        )
```

> Событие `tt_inapp_stories_stuck` (`'step': 'tt_5_inapp_stories_stuck'`) — НЕ трогать.

- [ ] **Step 5: Запустить — убедиться, что проходят**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py -k inapp_stories_handler_phase -v`
Expected: PASS (2 теста).

- [ ] **Step 6: Регресс**

Run: `python -m pytest tests/test_publisher_tt_overlay_handlers.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_share_loop_overlay_guard.py
git commit -m "feat(wp122): phase param в _handle_tt_inapp_stories"
```

---

## Task 3: Хелпер `_run_tt_share_loop_overlay_guard`

**Files:**
- Modify: `publisher_tiktok.py` (новый метод сразу после `_handle_tt_inapp_stories`, ~L626)
- Modify: `tests/test_publisher_tt_share_loop_overlay_guard.py` (добавить тесты хелпера)

- [ ] **Step 1: Добавить тесты хелпера (kill-switch, detect+dismiss, cap, reset)**

В конец `tests/test_publisher_tt_share_loop_overlay_guard.py` добавить:

```python
# ── Task 3: helper kill-switch ──

def test_guard_disabled_by_default_returns_none(monkeypatch):
    monkeypatch.delenv('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', raising=False)
    mx = _bare_mixin()
    assert mx._run_tt_share_loop_overlay_guard(_samsung_overlay_xml(), 0) is None
    mx.adb_tap.assert_not_called()
    mx.adb.assert_not_called()


def test_guard_disabled_explicit_false(monkeypatch):
    monkeypatch.setenv('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', 'false')
    mx = _bare_mixin()
    assert mx._run_tt_share_loop_overlay_guard(_inapp_stories_xml(), 0) is None


# ── Task 3: helper detect + dismiss ──

def test_guard_samsung_overlay_handled(monkeypatch):
    monkeypatch.setenv('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', 'true')
    mx = _bare_mixin()
    res = mx._run_tt_share_loop_overlay_guard(_samsung_overlay_xml(), 0)
    assert res == 'handled'
    assert mx._samsung_overlay_iter == 1
    cats = [c.kwargs.get('meta', {}).get('category')
            for c in mx.log_event.call_args_list]
    assert 'tt_samsung_overlay_detected' in cats


def test_guard_inapp_stories_handled(monkeypatch):
    monkeypatch.setenv('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', 'true')
    mx = _bare_mixin()
    res = mx._run_tt_share_loop_overlay_guard(_inapp_stories_xml(), 0)
    assert res == 'handled'
    assert mx._inapp_stories_iter == 1


def test_guard_no_overlay_returns_none(monkeypatch):
    monkeypatch.setenv('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', 'true')
    mx = _bare_mixin()
    assert mx._run_tt_share_loop_overlay_guard(_clean_xml(), 0) is None


def test_guard_samsung_cap_returns_stuck(monkeypatch):
    monkeypatch.setenv('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', 'true')
    mx = _bare_mixin()
    mx._samsung_overlay_iter = TikTokMixin.MAX_SAMSUNG_OVERLAY_ITERATIONS
    res = mx._run_tt_share_loop_overlay_guard(_samsung_overlay_xml(), 9)
    assert res == 'stuck'
    mx.set_step.assert_called_with('tt_5_samsung_overlay_stuck')


def test_guard_dismissed_reset_emits_event(monkeypatch):
    """Оверлей дисмиссили ранее (iter>0), теперь его нет → dismissed-событие
    со step='share_loop' + сброс счётчика."""
    monkeypatch.setenv('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', 'true')
    mx = _bare_mixin()
    mx._samsung_overlay_iter = 2
    res = mx._run_tt_share_loop_overlay_guard(_clean_xml(), 3)
    assert res is None
    assert mx._samsung_overlay_iter == 0
    cats = [c.kwargs.get('meta', {}).get('category')
            for c in mx.log_event.call_args_list]
    assert 'tt_samsung_overlay_dismissed' in cats
    steps = [c.kwargs.get('meta', {}).get('step')
             for c in mx.log_event.call_args_list]
    assert 'share_loop' in steps
```

- [ ] **Step 2: Запустить — убедиться, что падают (нет метода)**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py -k guard_ -v`
Expected: FAIL — `AttributeError: 'TikTokMixin' object has no attribute '_run_tt_share_loop_overlay_guard'`.

- [ ] **Step 3: Реализовать хелпер**

В `publisher_tiktok.py` добавить новый метод сразу ПОСЛЕ `_handle_tt_inapp_stories` (перед `_handle_tt_contacts_perm`):

```python
    def _run_tt_share_loop_overlay_guard(self, ui_xml: str, attempt: int):
        """Закрыть окно «Добавить в историю» (Samsung / TT in-app Stories),
        перекрывающее кнопку публикации ВО ВРЕМЯ share-loop (WP #122, суб-режим A).

        Зеркалит overlay-блок из wait_upload, но гейтится СОБСТВЕННЫМ
        kill-switch TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED (default OFF — тёмный
        выкат). wait_upload-хендлеры сохраняют свои отдельные ON-флаги.

        Tri-state (тот же контракт, что у _run_tt_commercial_music_hook):
          'handled' — оверлей закрыт; вызывающий делает sleep + continue.
          'stuck'   — cap превышен; вызывающий делает return False.
          None      — оверлея нет (или гард выключен); вызывающий продолжает.
        """
        if (os.environ.get('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', 'false')
                .lower() != 'true'):
            return None
        # Samsung "Добавить в историю"
        if self._detect_samsung_stories_overlay(ui_xml):
            if not self._handle_samsung_stories_overlay(ui_xml, attempt,
                                                        phase='share_loop'):
                return 'stuck'
            return 'handled'
        elif self._samsung_overlay_iter > 0:
            self.log_event(
                'info', 'TikTok: Samsung overlay dismissed successfully',
                meta={'category': 'tt_samsung_overlay_dismissed',
                      'platform': self.platform, 'step': 'share_loop',
                      'attempts': self._samsung_overlay_iter,
                      'wait_iter': attempt})
            self._samsung_overlay_iter = 0
        # TT in-app Stories editor
        if self._detect_tt_inapp_stories(ui_xml):
            if not self._handle_tt_inapp_stories(ui_xml, attempt,
                                                 phase='share_loop'):
                return 'stuck'
            return 'handled'
        elif self._inapp_stories_iter > 0:
            self.log_event(
                'info', 'TikTok: in-app Stories editor dismissed successfully',
                meta={'category': 'tt_inapp_stories_dismissed',
                      'platform': self.platform, 'step': 'share_loop',
                      'attempts': self._inapp_stories_iter,
                      'wait_iter': attempt})
            self._inapp_stories_iter = 0
        return None
```

- [ ] **Step 4: Запустить — убедиться, что проходят**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py -k guard_ -v`
Expected: PASS (7 тестов).

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_share_loop_overlay_guard.py
git commit -m "feat(wp122): _run_tt_share_loop_overlay_guard helper (kill-switch OFF)"
```

---

## Task 4: Врезать вызов в share-loop `publish_tiktok`

**Files:**
- Modify: `publisher_tiktok.py` (share-loop в `publish_tiktok`, между L1935 и L1937)
- Modify: `tests/test_publisher_tt_share_loop_overlay_guard.py` (source-level wiring тесты)

- [ ] **Step 1: Добавить структурные тесты размещения вызова**

В конец `tests/test_publisher_tt_share_loop_overlay_guard.py` добавить:

```python
# ── Task 4: share-loop wiring (source-level lock) ──

def test_guard_wired_between_button_search_and_fallback():
    import inspect
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    tapped_idx = src.find('if _tapped_post:')
    call_idx = src.find('_run_tt_share_loop_overlay_guard(ui, attempt)')
    fallback_idx = src.find('if attempt >= 2:')
    assert -1 < tapped_idx < call_idx < fallback_idx, (
        'share-loop overlay guard должен вызываться ПОСЛЕ XML-поиска кнопки '
        '(`if _tapped_post: break`) и ПЕРЕД слепым fallback (`if attempt >= 2:`)'
    )


def test_guard_call_site_handles_stuck_and_handled():
    import inspect
    src = inspect.getsource(TikTokMixin.publish_tiktok)
    start = src.find('_run_tt_share_loop_overlay_guard(ui, attempt)')
    seg = src[start:start + 400]
    assert "== 'stuck'" in seg and 'return False' in seg
    assert "== 'handled'" in seg and 'continue' in seg
```

- [ ] **Step 2: Запустить — убедиться, что падают (вызова нет)**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py -k "wired or call_site" -v`
Expected: FAIL — `find` вернёт -1, ассерт упадёт.

- [ ] **Step 3: Врезать вызов в share-loop**

В `publisher_tiktok.py` найти (это конец XML-поиска кнопки и начало fallback в `publish_tiktok`):

```python
            if _tapped_post:
                break

            # Fallback: тап в верхний правый угол где всегда находится кнопка публикации TikTok
```

Заменить на:

```python
            if _tapped_post:
                break

            # WP #122 (суб-режим A): окно «Добавить в историю» (Samsung /
            # TT in-app Stories) перекрывает кнопку публикации в share-loop.
            # Переиспользуем wait_upload overlay-хендлеры, гейт за СВОИМ
            # kill-switch TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED (default OFF).
            # Сюда доходим только когда кнопка НЕ найдена в XML (после `break`
            # выше управление не попадает) → happy-path не затрагивается.
            _ov_res = self._run_tt_share_loop_overlay_guard(ui, attempt)
            if _ov_res == 'stuck':
                return False
            if _ov_res == 'handled':
                time.sleep(1.5)
                continue

            # Fallback: тап в верхний правый угол где всегда находится кнопка публикации TikTok
```

- [ ] **Step 4: Запустить wiring-тесты — убедиться, что проходят**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py -k "wired or call_site" -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Полный новый тест-файл зелёный**

Run: `python -m pytest tests/test_publisher_tt_share_loop_overlay_guard.py -q`
Expected: PASS (все ~13 тестов).

- [ ] **Step 6: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_share_loop_overlay_guard.py
git commit -m "feat(wp122): врезать overlay-guard в share-loop publish_tiktok"
```

---

## Task 5: Полный регресс TT + codex review + PR

**Files:** —

- [ ] **Step 1: Прогнать все TT-тесты (регресс)**

Run: `python -m pytest tests/test_publisher_tt_overlay_handlers.py tests/test_publisher_tt_wait_upload_integration.py tests/test_publisher_tt_commercial_music_modal.py tests/test_publisher_tt_visibility_confirm.py tests/test_publisher_tt_share_loop_overlay_guard.py -q`
Expected: PASS (новый файл + все смежные TT-тесты зелёные; wait_upload-поведение не регрессировало).

- [ ] **Step 2: Прогнать компиляцию модуля (синтаксис)**

Run: `python -c "import ast,sys; ast.parse(open('publisher_tiktok.py').read()); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Codex review диффа (стоячая практика — до 0 P1)**

Run: `git diff origin/main | ~/.local/bin/codex review -`
Применить фидбэк раундами, пока не останется P1; коммитить правки.

- [ ] **Step 4: Push ветки и PR в delivery-contenthunter**

```bash
set -a; . ~/secrets/github-gengo2.env; set +a
git push -u origin wp122-tt-share-loop-overlay
gh pr create --repo GenGo2/delivery-contenthunter \
  --base main --head wp122-tt-share-loop-overlay \
  --title "WP #122: TT share-loop overlay-guard (dark deploy, OFF)" \
  --body "Суб-режим A tt_upload_confirmation_timeout: окно «Добавить в историю» перекрывает share-loop. Переиспользуем существующие overlay-хендлеры в share-loop под НОВЫМ kill-switch TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED (default OFF — тёмный выкат). wait_upload не тронут. Включение — только после смоука на testbench. Spec/plan в contenthunter docs/superpowers. 🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

Expected: PR создан. **Без force-push, без рестарта prod PM2 на этом шаге** (флаг OFF → в бою неактивно даже после merge).

---

## Task 6: Testbench-смоук → ручное включение в проде (deploy-фаза)

> Выполняется ПОСЛЕ merge PR, отдельным контролируемым шагом. Это не автоматизируется в плане — требует наблюдения за реальной публикацией.

- [ ] **Step 1: Смоук на testbench с включённым флагом**

На testbench-устройстве запустить реальную TikTok-публикацию с `TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED=true`, по возможности воспроизвести окно «Добавить в историю». Проверить:
- оверлей закрывается в share-loop (события `tt_samsung_overlay_detected`/`tt_inapp_stories_detected` со `step='share_loop'` + `tt_*_dismissed`);
- кнопка публикации находится, публикация уходит;
- happy-path без оверлея НЕ сломан (обычная публикация проходит как раньше).

- [ ] **Step 2: Ручное включение флага в проде**

После зелёного смоука выставить `TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED=true` в окружении prod-воркера autowarm (PM2). Откат — снять флаг / `false` (мгновенно, без релиза).

- [ ] **Step 3: Верификация на нормальной TT-пачке**

Через сутки после включения: доля `tt_upload_confirmation_timeout` падает; в событиях появляются `tt_*_detected`/`tt_*_dismissed` со `step='share_loop'`. Группировать по финальной `meta.category` (исключая `adb_devices_unreachable`/`process_interrupted`).

- [ ] **Step 4: Обновить WP #122 + evidence + память**

OpenProject: комментарий в house-style (Что было не так → Что сделано → Что осталось), статус → «Тестирование» после включения и первичной верификации. Evidence-док в `docs/evidence/`. Обновить память (project-файл WP #122).

---

## Notes for the Executor

- **Где код:** worktree от `origin/main` `GenGo2/delivery-contenthunter`. НЕ коммитить в `/root/.openclaw/workspace-genri/autowarm` (post-commit auto-push в prod).
- **Kill-switch default OFF** — это намеренно (тёмный выкат, выбор пользователя). Не менять default на `'true'`.
- **wait_upload не трогаем** — отдельные флаги `TT_SAMSUNG_OVERLAY_HANDLER_ENABLED`/`TT_INAPP_STORIES_HANDLER_ENABLED` остаются ON.
- **`phase` — trailing-kwarg с дефолтом** `'wait_upload'`: существующие positional-вызовы из wait_upload (`_handle_..._overlay(ui, wait)`) не ломаются.
- **`*_stuck`-события не трогаем** — у них свой явный `step`.
- **Без force-push** на любую общую ветку.
