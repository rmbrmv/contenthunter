# WP #181 — IG share no_progress post-mortem probe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перестать ложно классифицировать опубликованные IG-Reels как `ig_share_tap_no_progress`: добавить post-mortem success probe после Tier 1 + Tier 1.5, который через `dumpsys activity` подтверждает, что editor покинут (IG ушёл в Reels feed) — и в этом случае **не** пишет error event, а fall-through в основной success-loop (url-poller подберёт URL).

**Architecture:** Один pure-function helper + один блок post-mortem probe внутри `_wait_instagram_upload`. Никаких новых модулей. Kill-switch `IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED` (default true), grace `IG_SHARE_POSTMORTEM_GRACE_S=20`, polling `IG_SHARE_POSTMORTEM_POLL_S=5`. Никакого whitelist activity-имён — решающий критерий «`com.instagram.android` в foreground **и** не `ModalActivity`».

**Tech Stack:** Python 3 (autowarm-testbench), pytest + unittest.mock, ADB. Цель — `/home/claude-user/autowarm-testbench/publisher_instagram.py` и тесты в `/home/claude-user/autowarm-testbench/tests/`.

**Спека:** `docs/superpowers/specs/2026-05-28-wp181-ig-share-no-progress-postmortem-design.md`

---

## File Structure

| Файл | Действие | Ответственность |
|---|---|---|
| `/home/claude-user/autowarm-testbench/publisher_instagram.py` | Modify (≈L3136-3148 + helper рядом с `_is_ig_editor_still_visible` L1144) | Helper `_is_ig_post_share_progressed`; блок post-mortem probe внутри `_wait_instagram_upload`. |
| `/home/claude-user/autowarm-testbench/tests/test_publisher_instagram_postmortem_probe.py` | Create | Unit-тесты helper + behavior-тесты блока post-mortem. |

Существующий тестовый каркас в `tests/test_publisher_instagram_share_retry.py` (XML-стаб + `_make_publisher_stub`) переиспользуем — копируем helpers в новый файл локально, чтобы тесты были self-contained (как уже принято в проекте).

---

## Pre-flight: ветка и baseline

**Файлы:** none

- [ ] **Step 1: Создать рабочую ветку в autowarm-testbench**

Внимание: autowarm-testbench — общий чекаут с параллельными worktree-папками (~/autowarm-testbench-feat-*). Делаем worktree, не `checkout -b`.

```bash
cd ~/autowarm-testbench
git fetch origin
git worktree add ../autowarm-testbench-feat-wp181-ig-share-postmortem-20260528 -b feat/wp181-ig-share-postmortem origin/main
cd ../autowarm-testbench-feat-wp181-ig-share-postmortem-20260528
git branch --show-current
```

Expected output: `feat/wp181-ig-share-postmortem`

- [ ] **Step 2: Baseline — все существующие IG-тесты зелёные**

```bash
pytest tests/test_publisher_instagram_share_retry.py tests/test_publisher_instagram_wait_upload_diag.py tests/test_publisher_ig_editor.py tests/test_publisher_ig_camera_recovery.py -v
```

Expected: все PASS. Если что-то pre-existing red — записать список (учесть при regression в Task 6, не путать с regressions от новой работы).

---

## Task 1: Helper `_is_ig_post_share_progressed` (unit-tested)

**Files:**
- Create: `/home/claude-user/autowarm-testbench/tests/test_publisher_instagram_postmortem_probe.py`
- Modify: `/home/claude-user/autowarm-testbench/publisher_instagram.py` (вставка нового метода рядом с `_is_ig_editor_still_visible` L1144)

- [ ] **Step 1.1: Создать тест-файл с unit-тестами helper'а**

`tests/test_publisher_instagram_postmortem_probe.py`:

```python
"""Behavior + unit тесты для post-mortem success probe (WP #181).

Спека: docs/superpowers/specs/2026-05-28-wp181-ig-share-no-progress-postmortem-design.md

Запуск: cd /home/claude-user/autowarm-testbench && \
        pytest tests/test_publisher_instagram_postmortem_probe.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─── Helper unit-tests ──────────────────────────────────────────────────────

def test_is_ig_post_share_progressed_modal_activity_returns_false():
    """Editor (ModalActivity) ещё открыт → не progress."""
    from publisher import DevicePublisher
    line = 'topResumedActivity=ActivityRecord{1 u0 com.instagram.android/com.instagram.modal.ModalActivity t1523}'
    assert DevicePublisher._is_ig_post_share_progressed(line) is False


def test_is_ig_post_share_progressed_instagram_main_activity_returns_true():
    """Post-publish current build (InstagramMainActivity) → progress."""
    from publisher import DevicePublisher
    line = 'topResumedActivity=ActivityRecord{1 u0 com.instagram.android/.activity.InstagramMainActivity t1}'
    assert DevicePublisher._is_ig_post_share_progressed(line) is True


def test_is_ig_post_share_progressed_reel_viewer_activity_returns_true():
    """Reels feed (ReelViewerActivity) → progress."""
    from publisher import DevicePublisher
    line = 'topResumedActivity=ActivityRecord{1 u0 com.instagram.android/.reels.viewer.ReelViewerActivity t1}'
    assert DevicePublisher._is_ig_post_share_progressed(line) is True


def test_is_ig_post_share_progressed_non_ig_package_returns_false():
    """IG ушёл из foreground (launcher / другой app) → не progress (uncertain)."""
    from publisher import DevicePublisher
    line = 'topResumedActivity=ActivityRecord{1 u0 com.android.launcher/.Launcher t1}'
    assert DevicePublisher._is_ig_post_share_progressed(line) is False


def test_is_ig_post_share_progressed_empty_string_returns_false():
    """Пустой dumpsys output → не progress (safe default)."""
    from publisher import DevicePublisher
    assert DevicePublisher._is_ig_post_share_progressed('') is False
```

- [ ] **Step 1.2: Прогнать тесты helper'а — ожидаем FAIL**

```bash
cd ~/autowarm-testbench-feat-wp181-ig-share-postmortem-20260528
pytest tests/test_publisher_instagram_postmortem_probe.py -v
```

Expected: 5 FAIL с `AttributeError: type object 'DevicePublisher' has no attribute '_is_ig_post_share_progressed'`.

- [ ] **Step 1.3: Имплементировать helper в publisher_instagram.py**

В `publisher_instagram.py` добавить новый метод **сразу после** `_is_ig_editor_still_visible` (то есть после L1144-… найди конец этого метода и встав сразу после него).

```python
    @staticmethod
    def _is_ig_post_share_progressed(act_line: str) -> bool:
        """True, если IG-package остаётся в foreground, но editor (ModalActivity) покинут.

        Решающий критерий для post-mortem success probe (WP #181, спека
        docs/superpowers/specs/2026-05-28-wp181-ig-share-no-progress-postmortem-design.md):
        не зависит от whitelist activity-имён — любая активность IG кроме
        com.instagram.modal.ModalActivity = transit прошёл, editor закрыт.

        Args:
            act_line: одна строка из `dumpsys activity activities | grep topResumedActivity`.

        Returns:
            True, если строка содержит `com.instagram.android` И не содержит
            `ModalActivity`. False иначе (другой package / пусто / editor open).
        """
        if not act_line:
            return False
        if 'com.instagram.android' not in act_line:
            return False
        if 'ModalActivity' in act_line:
            return False
        return True
```

- [ ] **Step 1.4: Прогнать тесты helper'а — ожидаем PASS**

```bash
pytest tests/test_publisher_instagram_postmortem_probe.py -v
```

Expected: 5 PASS.

- [ ] **Step 1.5: Коммит**

```bash
git add tests/test_publisher_instagram_postmortem_probe.py publisher_instagram.py
git commit -m "$(cat <<'EOF'
feat(wp181): add _is_ig_post_share_progressed helper

Pure-function determinant для post-mortem probe — без whitelist
activity-имён, по отрицательной сигнатуре «IG-package + не
ModalActivity». 5 unit-тестов покрывают позитив/негатив/empty.

Спека: docs/superpowers/specs/2026-05-28-wp181-ig-share-no-progress-postmortem-design.md
EOF
)"
```

---

## Task 2: Behavior test — post-mortem probe rescues false-negative

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/tests/test_publisher_instagram_postmortem_probe.py`

- [ ] **Step 2.1: Добавить общий test-scaffold helpers внизу того же файла**

Эти helper'ы — копии из `test_publisher_instagram_share_retry.py` (паттерн self-contained tests как принят в проекте). Дописать **в конец** существующего файла:

```python
# ─── Test scaffolding (mirror of test_publisher_instagram_share_retry.py) ──

def _editor_xml() -> str:
    return (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="caption text" content-desc="" '
        'resource-id="com.instagram.android:id/caption_input_text_view" '
        'bounds="[100,100][900,200]" clickable="true"/>'
        '<node text="" content-desc="Поделиться" '
        'resource-id="com.instagram.android:id/share_button" '
        'bounds="[563,2025][1035,2149]" clickable="true"/>'
        '</hierarchy>'
    )


def _make_publisher_stub(dump_ui_responses, adb_responses=None,
                          env_overrides=None):
    """Stub DevicePublisher для invoke _wait_instagram_upload.

    adb_responses: list или None. Если None — default editor-composer activity
        (НЕ success token и НЕ ModalActivity), чтобы pre-Tier1 probe не skip.
    env_overrides: optional dict {VAR: value} — применяется через patch.dict
        в самом тесте (этот fn только хранит ссылку).
    """
    from publisher import DevicePublisher
    stub = DevicePublisher.__new__(DevicePublisher)
    stub.task_id = 9999
    stub.adb_host = '127.0.0.1'
    stub.adb_port = 1234
    stub.device_serial = 'TESTSERIAL'
    stub.platform = 'Instagram'
    stub.account = 'test_user'
    stub._collected_screenshots = []
    stub._collected_ui_dumps = []
    stub.set_step = MagicMock()
    stub.log_event = MagicMock()
    stub._safe_kb_probe = MagicMock()
    stub._save_debug_artifacts = MagicMock()
    stub._save_debug_ui_dump = MagicMock(return_value='https://s3/test.xml')
    stub._save_debug_screenshot = MagicMock(return_value=None)
    stub.dismiss_location_dialog = MagicMock(return_value=False)
    stub.dismiss_overlay_dialogs = MagicMock(return_value=False)
    stub.tap_element = MagicMock(return_value=True)
    stub._auto_get_instagram_url = MagicMock(return_value='')
    stub._save_post_url = MagicMock()
    stub._capture_via_notifications = MagicMock(return_value='')
    stub._fetch_instagram_url_via_api = MagicMock(return_value='')
    stub._update_post_url_final = MagicMock()
    if adb_responses is None:
        stub.adb = MagicMock(return_value='topResumedActivity=com.instagram.android/.creation.activity.MediaCaptureActivity t1')
    else:
        padded = list(adb_responses) + [adb_responses[-1]] * 100
        stub.adb = MagicMock(side_effect=padded)
    stub.dump_ui = MagicMock(side_effect=dump_ui_responses)
    return stub
```

- [ ] **Step 2.2: Добавить behavior-test «probe rescues»**

В тот же файл:

```python
# ─── Behavior tests: post-mortem probe ─────────────────────────────────────

def test_postmortem_probe_rescues_false_negative_no_progress():
    """Tier 1 + Tier 1.5 не помогли (editor visible во всех dump'ах),
    но post-mortem probe видит ReelViewerActivity → НЕ пишет
    ig_share_tap_no_progress, пишет ig_share_postmortem_success.

    adb sequence (в порядке вызовов):
      1. pre-Tier1 probe samples 1..6 → MediaCaptureActivity (default) — НЕ skip Tier 1
      2. post-mortem probe iter 1 → ModalActivity (transit ещё не закончен)
      3. post-mortem probe iter 2 → ReelViewerActivity → progress detected, break

    dump_ui: всегда editor — Tier 1 retries exhausted + Tier 1.5 OK fallback
             не находит action_bar OK (нет в editor_xml без OK-node) →
             ok_tap_dispatched=False → final fail-path запущен.
    """
    dump_responses = [_editor_xml()] * 50

    # adb responses: pre-Tier1 probe (6 default samples) + post-mortem (2 polls)
    adb_responses = [
        # pre-Tier1 probe (6 samples — все MediaCaptureActivity)
        'topResumedActivity=com.instagram.android/.creation.activity.MediaCaptureActivity t1',
    ] * 6 + [
        # main success-loop interim probes (если попадёт; padding fall-through)
        'topResumedActivity=com.instagram.android/com.instagram.modal.ModalActivity t1',
    ] * 30 + [
        # post-mortem probe iter 1 — still ModalActivity
        'topResumedActivity=ActivityRecord{1 u0 com.instagram.android/com.instagram.modal.ModalActivity t1}',
        # post-mortem probe iter 2 — transit done
        'topResumedActivity=ActivityRecord{1 u0 com.instagram.android/.reels.viewer.ReelViewerActivity t1}',
    ]

    stub = _make_publisher_stub(dump_ui_responses=dump_responses,
                                  adb_responses=adb_responses)

    with patch.dict(os.environ, {'IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED': 'true',
                                  'IG_SHARE_POSTMORTEM_GRACE_S': '20',
                                  'IG_SHARE_POSTMORTEM_POLL_S': '5'}):
        with patch('time.sleep'):
            stub._wait_instagram_upload()

    no_progress = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
    ]
    postmortem = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_postmortem_success'
    ]

    assert len(no_progress) == 0, \
        f'expected 0 ig_share_tap_no_progress (rescued by postmortem), got {len(no_progress)}'
    assert len(postmortem) == 1, \
        f'expected 1 ig_share_postmortem_success, got {len(postmortem)}'
    assert 'ReelViewerActivity' in postmortem[0].kwargs['meta']['topResumedActivity']
```

- [ ] **Step 2.3: Прогнать новый тест — ожидаем FAIL**

```bash
pytest tests/test_publisher_instagram_postmortem_probe.py::test_postmortem_probe_rescues_false_negative_no_progress -v
```

Expected: FAIL — событие `ig_share_tap_no_progress` всё ещё пишется (блок post-mortem ещё не реализован).

- [ ] **Step 2.4: Коммит теста (red-state TDD checkpoint)**

```bash
git add tests/test_publisher_instagram_postmortem_probe.py
git commit -m "test(wp181): failing test — postmortem probe rescues false-negative"
```

---

## Task 3: Behavior test — post-mortem probe sees only ModalActivity → старое поведение

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/tests/test_publisher_instagram_postmortem_probe.py`

- [ ] **Step 3.1: Добавить тест в тот же файл**

```python
def test_postmortem_probe_modal_only_keeps_old_no_progress_behavior():
    """Post-mortem probe видит ModalActivity на всех iterations → старое
    поведение: ig_share_tap_no_progress emit, return False.

    Сценарий: реальный transit не произошёл — пользовательский screen залип
    в редакторе. Поведение должно быть в точности как до WP #181.
    """
    dump_responses = [_editor_xml()] * 50

    adb_responses = [
        'topResumedActivity=com.instagram.android/.creation.activity.MediaCaptureActivity t1',
    ] * 6 + [
        'topResumedActivity=com.instagram.android/com.instagram.modal.ModalActivity t1',
    ] * 60  # достаточно для 4 post-mortem iterations + main loop padding

    stub = _make_publisher_stub(dump_ui_responses=dump_responses,
                                  adb_responses=adb_responses)

    with patch.dict(os.environ, {'IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED': 'true',
                                  'IG_SHARE_POSTMORTEM_GRACE_S': '20',
                                  'IG_SHARE_POSTMORTEM_POLL_S': '5'}):
        with patch('time.sleep'):
            result = stub._wait_instagram_upload()

    no_progress = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
    ]
    postmortem = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_postmortem_success'
    ]

    assert result is False
    assert len(no_progress) == 1, \
        f'expected 1 ig_share_tap_no_progress (postmortem did not rescue), got {len(no_progress)}'
    assert len(postmortem) == 0, \
        f'expected 0 ig_share_postmortem_success (probe saw only ModalActivity), got {len(postmortem)}'
```

- [ ] **Step 3.2: Прогнать новый тест — ожидаем FAIL**

```bash
pytest tests/test_publisher_instagram_postmortem_probe.py::test_postmortem_probe_modal_only_keeps_old_no_progress_behavior -v
```

Expected: FAIL — пока что блок post-mortem не имплементирован, тест может пройти случайно по старому поведению. Проверь: если PASS — всё равно нормально (assertion проходит при текущем поведении, импл потом не сломает).

- [ ] **Step 3.3: Коммит теста**

```bash
git add tests/test_publisher_instagram_postmortem_probe.py
git commit -m "test(wp181): postmortem probe — modal-only path keeps old fail"
```

---

## Task 4: Behavior test — kill-switch off → старое поведение

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/tests/test_publisher_instagram_postmortem_probe.py`

- [ ] **Step 4.1: Добавить тест kill-switch'а**

```python
def test_postmortem_probe_disabled_via_killswitch_keeps_old_behavior():
    """IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED=false — даже если probe
    БЫ увидел ReelViewerActivity, блок не запускается → старое поведение
    ig_share_tap_no_progress. Защита от регрессии при выключении флага.
    """
    dump_responses = [_editor_xml()] * 50

    adb_responses = [
        'topResumedActivity=com.instagram.android/.creation.activity.MediaCaptureActivity t1',
    ] * 6 + [
        'topResumedActivity=ActivityRecord{1 u0 com.instagram.android/.reels.viewer.ReelViewerActivity t1}',
    ] * 30  # probe увидел бы success — но он отключён kill-switch'ем

    stub = _make_publisher_stub(dump_ui_responses=dump_responses,
                                  adb_responses=adb_responses)

    with patch.dict(os.environ, {'IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED': 'false'}):
        with patch('time.sleep'):
            result = stub._wait_instagram_upload()

    no_progress = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_tap_no_progress'
    ]
    postmortem = [
        c for c in stub.log_event.call_args_list
        if c.kwargs.get('meta', {}).get('category') == 'ig_share_postmortem_success'
    ]

    assert result is False
    assert len(no_progress) == 1, \
        f'kill-switch off — старое поведение должно сохраниться (got {len(no_progress)} no_progress)'
    assert len(postmortem) == 0, \
        f'kill-switch off — postmortem не должен пускаться (got {len(postmortem)})'
```

- [ ] **Step 4.2: Прогнать новый тест**

```bash
pytest tests/test_publisher_instagram_postmortem_probe.py::test_postmortem_probe_disabled_via_killswitch_keeps_old_behavior -v
```

Expected: PASS (старое поведение работает) ИЛИ irrelevant (важно зафиксировать, проверка нужна для regression-защиты).

- [ ] **Step 4.3: Коммит**

```bash
git add tests/test_publisher_instagram_postmortem_probe.py
git commit -m "test(wp181): postmortem probe — kill-switch off keeps old behavior"
```

---

## Task 5: Implementation — post-mortem probe block

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/publisher_instagram.py` (L3136-L3148: блок final fail внутри try/except)

- [ ] **Step 5.1: Локализовать точку вставки**

Найди в `publisher_instagram.py` блок:

```python
                if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
                    self.log_event('error',
                                   'Instagram: Share tap не прогрессировал после retries',
                                   meta={'category': 'ig_share_tap_no_progress',
                                         'platform': self.platform,
                                         'step': 'wait_upload',
                                         'retries_exhausted': 2,
                                         'ok_fallback_attempted': ok_tap_dispatched})
                    try:
                        self._save_debug_artifacts('instagram_share_no_progress')
                    except Exception as _art_e:
                        log.warning(f'_save_debug_artifacts failed: {_art_e}')
                    share_no_progress = True
```

(≈L3136-3148). Это место имплементации.

- [ ] **Step 5.2: Имплементировать post-mortem probe**

Замени блок выше на следующий (внимание: сохрани отступ — он внутри `try:` который начался на L3096):

```python
                if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
                    # === Post-mortem success probe (WP #181) ===
                    # Эвиденс 2026-05-28: 3/3 проверенных «no_progress» скринкастов
                    # показали Reels feed на финале — пост опубликован, но
                    # _is_ig_editor_still_visible вернул True из-за stale uiautomator.
                    # Probe смотрит ground-truth через dumpsys; если IG ушёл из
                    # ModalActivity — fall-through в success-loop без fail-events.
                    pm_enabled = os.environ.get(
                        'IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED', 'true'
                    ).lower() == 'true'
                    pm_grace_s = float(os.environ.get('IG_SHARE_POSTMORTEM_GRACE_S', '20'))
                    pm_poll_s = float(os.environ.get('IG_SHARE_POSTMORTEM_POLL_S', '5'))
                    pm_progressed = False
                    pm_observed_act = ''
                    if pm_enabled:
                        pm_start = time.monotonic()
                        pm_iter = 0
                        while time.monotonic() - pm_start < pm_grace_s:
                            pm_iter += 1
                            try:
                                pm_act = self.adb(
                                    'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
                                    timeout=5,
                                ) or ''
                            except Exception:
                                pm_act = ''
                            pm_observed_act = pm_act.strip()[:300]
                            if self._is_ig_post_share_progressed(pm_act):
                                pm_progressed = True
                                break
                            remaining = pm_grace_s - (time.monotonic() - pm_start)
                            if remaining <= 0:
                                break
                            time.sleep(min(pm_poll_s, max(0.0, remaining)))
                        if pm_progressed:
                            self.log_event(
                                'info',
                                'Instagram: share post-mortem transit confirmed',
                                meta={
                                    'category': 'ig_share_postmortem_success',
                                    'platform': self.platform,
                                    'topResumedActivity': pm_observed_act,
                                    'grace_elapsed_s': round(time.monotonic() - pm_start, 2),
                                    'iterations': pm_iter,
                                    'reclassified_from': 'ig_share_tap_no_progress',
                                },
                            )
                            # fall-through в основной success-loop (L3155+) —
                            # share_no_progress остаётся False, события fail не пишем
                        else:
                            self.log_event('error',
                                           'Instagram: Share tap не прогрессировал после retries',
                                           meta={'category': 'ig_share_tap_no_progress',
                                                 'platform': self.platform,
                                                 'step': 'wait_upload',
                                                 'retries_exhausted': 2,
                                                 'ok_fallback_attempted': ok_tap_dispatched,
                                                 'postmortem_iterations': pm_iter,
                                                 'postmortem_last_act': pm_observed_act})
                            try:
                                self._save_debug_artifacts('instagram_share_no_progress')
                            except Exception as _art_e:
                                log.warning(f'_save_debug_artifacts failed: {_art_e}')
                            share_no_progress = True
                    else:
                        # kill-switch off → старое поведение в точности
                        self.log_event('error',
                                       'Instagram: Share tap не прогрессировал после retries',
                                       meta={'category': 'ig_share_tap_no_progress',
                                             'platform': self.platform,
                                             'step': 'wait_upload',
                                             'retries_exhausted': 2,
                                             'ok_fallback_attempted': ok_tap_dispatched})
                        try:
                            self._save_debug_artifacts('instagram_share_no_progress')
                        except Exception as _art_e:
                            log.warning(f'_save_debug_artifacts failed: {_art_e}')
                        share_no_progress = True
```

- [ ] **Step 5.3: Прогнать все 3 behavior-тестa + 5 unit-тестов**

```bash
pytest tests/test_publisher_instagram_postmortem_probe.py -v
```

Expected: 8 PASS (5 helper unit + 3 behavior).

- [ ] **Step 5.4: Коммит имплементации**

```bash
git add publisher_instagram.py
git commit -m "$(cat <<'EOF'
feat(wp181): post-mortem success probe в _wait_instagram_upload

Перед записью ig_share_tap_no_progress — polling dumpsys (grace 20s,
poll 5s, через _is_ig_post_share_progressed). При подтверждённом transit
пишет ig_share_postmortem_success и fall-through в success-loop —
url-poller (WP #86) подберёт post_url.

Kill-switch IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED=true (default),
параметры IG_SHARE_POSTMORTEM_GRACE_S=20, IG_SHARE_POSTMORTEM_POLL_S=5.

Эвиденс: 3/3 проверенных скринкастов 11660/11472/11646 показали Reels
feed на финале — пост опубликован, но stale uiautomator маскировал
успех под ig_share_tap_no_progress (99/7д).

Refs WP#73 (исходный детект success через InstagramMainActivity).
EOF
)"
```

---

## Task 6: Regression — все IG-тесты зелёные

**Files:** none

- [ ] **Step 6.1: Прогнать полный IG-test-набор**

```bash
pytest tests/test_publisher_instagram_share_retry.py \
       tests/test_publisher_instagram_wait_upload_diag.py \
       tests/test_publisher_instagram_postmortem_probe.py \
       tests/test_publisher_ig_editor.py \
       tests/test_publisher_ig_camera_recovery.py \
       -v
```

Expected: все PASS. Если что-то new red — debug. Если pre-existing red (см. baseline Task 0 Step 2) — оставить как было.

- [ ] **Step 6.2: Прогнать общий publisher-test-набор**

```bash
pytest tests/test_publisher_helpers_layer_a.py \
       tests/test_publisher_imports.py \
       tests/test_publisher_baseexception_handling.py \
       tests/test_publisher_intermediate_probes.py \
       tests/test_publisher_error_code_mapper_dedup.py \
       tests/test_publisher_error_code_mapper_probe.py \
       -v
```

Expected: все PASS / unchanged.

- [ ] **Step 6.3: Codex review (memory practice — обязательно для feat/fix)**

```bash
cd ~/autowarm-testbench-feat-wp181-ig-share-postmortem-20260528
git diff origin/main -- publisher_instagram.py tests/test_publisher_instagram_postmortem_probe.py | codex review -
```

Expected: 0 P1 findings. Если есть P1 — разобрать, исправить, повторить. P2/P3 — оценить и зафиксировать в spec / следующей итерации (memory practice).

- [ ] **Step 6.4: Коммит fix'ов после codex (если были)**

```bash
git add -p
git commit -m "review(wp181): codex round N fixes"
```

(Опционально, если diff не требовал правок — пропустить.)

---

## Task 7: Деплой + smoke

**Files:** none (env / PM2 операции на VPS).

- [ ] **Step 7.1: Merge в main и push**

Хост-машина:

```bash
cd ~/autowarm-testbench-feat-wp181-ig-share-postmortem-20260528
git push -u origin feat/wp181-ig-share-postmortem
# Создать PR через gh (если practice проекта = PR) или fast-forward в main:
cd ~/autowarm-testbench && git fetch origin && git merge --ff-only origin/feat/wp181-ig-share-postmortem
git push origin main
```

Уточни у Данила, если есть post-commit auto-deploy git-hook (memory: `reference_autowarm_git_hook`) — он может выкатить автоматически. Если нет — ручной ребут autowarm.

- [ ] **Step 7.2: Verify kill-switch значение в проде**

На VPS (или локально, если та же машина):

```bash
grep IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED /home/<owner>/autowarm-testbench/.env || \
  echo "(не задано — будет default true)"
```

Default `true` — дополнительных правок .env не требуется. Если есть `=false` от предыдущей итерации — поменять на `true` или удалить строку.

- [ ] **Step 7.3: Restart autowarm**

```bash
pm2 restart <autowarm-app-name>   # уточни имя через `pm2 list` (autowarm/autowarm-publisher)
pm2 logs <autowarm-app-name> --lines 50 --nostream
```

Expected: процесс up, без import errors, без warning'ов про IG_SHARE_POSTMORTEM_GRACE_S/POLL_S parsing.

- [ ] **Step 7.4: Live-smoke — первая прошедшая IG-задача**

```bash
# На VPS:
psql -U openclaw -h localhost -d openclaw -c "
SELECT id, status, error_code, post_url, created_at
FROM publish_tasks
WHERE platform='Instagram' AND testbench=false
ORDER BY created_at DESC LIMIT 5;
"
```

Expected: новые задачи нормально завершаются (`done`) или `awaiting_url` (для post-mortem success — `url-poller подберёт URL`). Никаких import errors.

---

## Task 8: Post-deploy 24h verify

**Files:** none — наблюдение метрик.

- [ ] **Step 8.1: ~12-24ч после деплоя — сравнить error_code распределение**

```bash
psql -U openclaw -h localhost -d openclaw -c "
SELECT error_code, COUNT(*) as cnt
FROM publish_tasks
WHERE platform='Instagram' AND testbench=false AND status='failed'
  AND created_at >= NOW() - INTERVAL '24 hours'
GROUP BY error_code ORDER BY cnt DESC;
"
```

Expected: `ig_share_tap_no_progress` существенно меньше (baseline 27-28.05: 45+12=57 за 2 дня, ожидаемо <10 за 24ч если postmortem ловит ≥90% false-negatives).

- [ ] **Step 8.2: Проверить positive-метрику ig_share_postmortem_success**

```bash
psql -U openclaw -h localhost -d openclaw -c "
SELECT COUNT(*) FROM publish_tasks
WHERE platform='Instagram'
  AND created_at >= NOW() - INTERVAL '24 hours'
  AND events::text LIKE '%ig_share_postmortem_success%';
"
```

Expected: counter > 0 (probe реально ловит false-negatives) — это сигнал, что фикс работает.

- [ ] **Step 8.3: Sample validation — взять 5 задач с postmortem_success и проверить пост на IG**

```bash
psql -U openclaw -h localhost -d openclaw -c "
SELECT id, account, post_url, status FROM publish_tasks
WHERE events::text LIKE '%ig_share_postmortem_success%'
  AND created_at >= NOW() - INTERVAL '24 hours'
LIMIT 5;
"
```

Для каждой — если `post_url` пуст: открыть Instagram аккаунта, убедиться что пост от соответствующей даты реально опубликован. Если все 5/5 опубликованы — переключить OpenProject WP #181 → «Тестирование» с эвиденс-комментом. Если есть отказы — диагностировать.

- [ ] **Step 8.4: Обновить OpenProject + memory**

```bash
# Через OpenProject API (~/secrets/openproject.env) обновить WP #181:
# - status → «Тестирование»
# - комментарий с baseline-vs-after метриками
# Память: обновить project_wp181_ig_ai_label_overlay.md →
#   project_wp181_ig_share_postmortem_probe.md (переименование +
#   корректировка гипотезы: «AI-label был red herring, root cause = stale UI dump +
#   long transit, fix = post-mortem probe»)
```

---

## Self-Review

**Spec coverage:**
- ✅ Helper `_is_ig_post_share_progressed` с отрицательной сигнатурой (спека §Architecture/Логика probe) → Task 1
- ✅ Block в `_wait_instagram_upload` (спека §Точка вставки) → Task 5
- ✅ Возврат `share_no_progress = False` + info-event `ig_share_postmortem_success` (спека §Возвращаемое значение) → Task 5
- ✅ Kill-switch `IG_SHARE_NO_PROGRESS_POSTMORTEM_PROBE_ENABLED` (спека §Kill-switch) → Task 5 + Task 4
- ✅ Параметры grace/poll через env (спека §Kill-switch) → Task 5
- ✅ Unit-тесты helper (спека §Тестирование/Unit) → Task 1
- ✅ Integration-тесты вкл/выкл/false-negative (спека §Тестирование/Integration) → Tasks 2-4
- ✅ Regression — существующие IG-тесты (спека §Тестирование/Regression) → Task 6
- ✅ Деплой через PM2 reload (спека §Деплой) → Task 7
- ✅ Post-deploy 24h verify (спека §Тестирование/Post-deploy) → Task 8
- ✅ Откат через kill-switch (спека §Откат) → Task 4 покрывает kill-switch off

**Placeholder scan:** Перечитал план — TBD/TODO нет. Все шаги содержат конкретный код или конкретные команды. «Уточни у Данила» в Task 7.1 — это явный gate (зависит от состояния auto-deploy hook'а, который я не могу точно проверить без обращения к нему).

**Type consistency:** Helper `_is_ig_post_share_progressed` — static, принимает `act_line: str`, возвращает `bool`. Используется одинаково в Tasks 1 (тесты) и 5 (impl). Env names и default'ы согласованы между Task 5 (impl) и Tasks 2-4 (тесты). Категории событий (`ig_share_postmortem_success`, `ig_share_tap_no_progress`) — одинаково по всему плану.
