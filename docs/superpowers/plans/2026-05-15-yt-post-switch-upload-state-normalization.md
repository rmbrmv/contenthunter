# YT post-switch upload state normalization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть `yt_gallery_no_video_candidate` фейлы публикации YT (WP #74) тремя
небольшими правками: state-reset YT перед upload-flow, расширенный
permission-tap внутри gallery-picker'а, обогащённая meta при fail-fast.

**Architecture:** Spec — `docs/superpowers/specs/2026-05-15-yt-post-switch-upload-state-normalization-design.md`.
Все изменения локальны в `publisher_youtube.py`; новый helper `_normalize_yt_state_pre_upload`
переиспользует существующие `adb`, `set_step`, `ensure_unlocked`, `dump_ui`, `tap_element`,
`log_event` из `publisher_base.PublisherBase`. Тесты mock'ают эти зависимости.

**Tech Stack:** Python 3.11, pytest, unittest.mock; repo `GenGo2/delivery-contenthunter`
(prod `/root/.openclaw/workspace-genri/autowarm/`, dev clone
`/home/claude-user/autowarm-testbench/`).

---

## Task 0: Подготовка worktree autowarm-testbench

**Файлы:** только worktree-setup, кода не меняем.

- [ ] **Step 1: Fetch свежий main**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git status --short  # должно быть пусто
```

- [ ] **Step 2: Создать worktree на feature-branch**

```bash
git worktree add /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515 \
  -b feat/yt-state-normalize-20260515 origin/main
cd /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515
git status --short  # чисто
```

- [ ] **Step 3: Baseline pytest — убедиться, что репо зелёный**

```bash
cd /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515
PYTHONPATH=. pytest tests/test_publisher_youtube_picker.py tests/test_publisher_imports.py -q 2>&1 | tail -10
```

Ожидаемо: оба файла зелёные (PR #36 уже в main).

---

## Task A: `_normalize_yt_state_pre_upload` helper + wiring

**Файлы:**
- Modify: `publisher_youtube.py` — добавить метод `_normalize_yt_state_pre_upload`
  перед `publish_youtube_short` (ориентир: после `_select_gallery_video` на :617-732,
  до `publish_youtube_short` на :735); вызвать в начале `publish_youtube_short`
  сразу после `_ensure_correct_account`.
- Create: `tests/test_publisher_youtube_state_normalize.py`

### Шаги A

- [ ] **Step A.1: Write failing test для helper**

Создать `tests/test_publisher_youtube_state_normalize.py`:

```python
"""Тесты для YouTubeMixin._normalize_yt_state_pre_upload — WP #74.

Гарантии:
1. force-stop YT package + start LAUNCHER intent.
2. После старта — 2 итерации tap'ов permission/onboarding-кнопок.
3. log_event 'yt_pre_upload_state_normalized' с meta package + force_stop_done.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_youtube import YouTubeMixin  # noqa: E402


class _StubPub(YouTubeMixin):
    def __init__(self, tap_returns=None):
        # tap_returns: list[bool] для последовательных tap_element вызовов
        self.platform = 'youtube'
        self.platform_cfg = {'package': 'com.google.android.youtube'}
        self.adb = MagicMock(return_value='')
        self.ensure_unlocked = MagicMock(return_value=True)
        self.dump_ui = MagicMock(return_value='<hierarchy></hierarchy>')
        self.set_step = MagicMock()
        self.log_event = MagicMock()
        self._tap_returns = tap_returns or [False, False]
        self._tap_idx = 0
        self.tap_element = MagicMock(side_effect=self._tap_side_effect)

    def _tap_side_effect(self, ui, patterns, **kw):
        idx = self._tap_idx
        self._tap_idx += 1
        if idx < len(self._tap_returns):
            return self._tap_returns[idx]
        return False


class TestNormalizeYtStatePreUpload:
    def test_force_stop_and_launcher_invoked(self):
        pub = _StubPub()
        pub._normalize_yt_state_pre_upload()
        cmds = [c[0][0] for c in pub.adb.call_args_list]
        assert any('force-stop com.google.android.youtube' in c for c in cmds), cmds
        assert any('am start' in c and 'LAUNCHER' in c for c in cmds), cmds

    def test_set_step_marked(self):
        pub = _StubPub()
        pub._normalize_yt_state_pre_upload()
        pub.set_step.assert_called()
        step_name = pub.set_step.call_args[0][0]
        assert 'нормализация' in step_name.lower() or 'normalize' in step_name.lower()

    def test_taps_permission_buttons_twice(self):
        # Симулируем 2 диалога: оба тапаются успешно
        pub = _StubPub(tap_returns=[True, True, False])
        pub._normalize_yt_state_pre_upload()
        # Должно быть >=2 вызовов tap_element с permission-patterns
        perms_patterns = {'при использовании приложения', 'только в этот раз',
                          'ок', 'разрешить', 'allow', 'понятно'}
        perm_calls = [c for c in pub.tap_element.call_args_list
                      if any(p.lower() in perms_patterns
                             for p in c[0][1])]
        assert len(perm_calls) >= 2, pub.tap_element.call_args_list

    def test_logs_completion_event(self):
        pub = _StubPub()
        pub._normalize_yt_state_pre_upload()
        events = [c for c in pub.log_event.call_args_list
                  if 'yt_pre_upload_state_normalized' in str(c)]
        assert events, pub.log_event.call_args_list
        # meta содержит package + force_stop_done
        ev = events[0]
        meta = ev[1].get('meta') if len(ev) > 1 else ev[0][2] if len(ev[0]) > 2 else None
        # log_event обычно вызывается как (type, msg, meta=...)
        kwargs = ev.kwargs if hasattr(ev, 'kwargs') else ev[1]
        meta = kwargs.get('meta', {})
        assert meta.get('package') == 'com.google.android.youtube'
        assert meta.get('force_stop_done') is True
```

- [ ] **Step A.2: Run failing test**

```bash
cd /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515
PYTHONPATH=. pytest tests/test_publisher_youtube_state_normalize.py -v 2>&1 | tail -20
```

Ожидаемо: 4 теста FAIL с `AttributeError: 'YouTubeMixin' object has no attribute '_normalize_yt_state_pre_upload'`.

- [ ] **Step A.3: Реализовать `_normalize_yt_state_pre_upload`**

Добавить в `publisher_youtube.py` ПЕРЕД `def publish_youtube_short` (line 735):

```python
    def _normalize_yt_state_pre_upload(self) -> None:
        """Сбросить YT в home-feed перед upload-flow — WP #74.

        После account_switch YT может остаться в Shorts feed с открытой
        bottom-sheet («Описание»), либо в Shorts camera после неудачного
        intent-launch. Эти состояния ломают `publish_youtube_short` — он
        ожидает либо меню создания, либо приземление через Shell_UploadActivity
        прямо в gallery. Принудительный force-stop + LAUNCHER гарантирует
        чистое исходное состояние.

        Idempotent: безопасно вызывать многократно (force-stop без crash'а на
        уже остановленном app).

        Evidence: 2026-05-15 task 6513 (camera permission overlay) + 6515
        (Shorts description sheet) — оба упали с `yt_gallery_no_video_candidate`
        из-за non-home post-switch state.
        """
        yt_pkg = self.platform_cfg['package']  # com.google.android.youtube
        self.set_step('YouTube: нормализация состояния перед upload')
        self.adb(f'am force-stop {yt_pkg}')
        time.sleep(1.5)
        try:
            self.ensure_unlocked()
        except Exception:
            pass
        self.adb(
            f'am start -p {yt_pkg} '
            f'-a android.intent.action.MAIN '
            f'-c android.intent.category.LAUNCHER'
        )
        time.sleep(3)
        # 2 итерации tap'а онбординг/permission диалогов после свежего start'а.
        for _ in range(2):
            ui = self.dump_ui()
            if self.tap_element(ui, [
                'При использовании приложения', 'Только в этот раз',
                'ОК', 'OK', 'Разрешить', 'Allow', 'Понятно',
            ]):
                time.sleep(2)
            else:
                break
        self.log_event(
            'info',
            'yt_pre_upload_state_normalized',
            meta={'category': 'yt_pre_upload_state_normalized',
                  'package': yt_pkg,
                  'force_stop_done': True},
        )
```

- [ ] **Step A.4: Wiring в `publish_youtube_short`**

В `publisher_youtube.py` сразу после строки `if not self._ensure_correct_account(): return False` (line 752-753) и ДО `content_uri = self._get_mediastore_content_uri(remote_media_path)` (line 756) добавить:

```python
        # WP #74: после account_switch YT может остаться в Shorts feed /
        # description sheet / shorts camera state. Принудительно возвращаем
        # на home-feed перед probe'ом меню создания.
        self._normalize_yt_state_pre_upload()
```

- [ ] **Step A.5: Run tests — pass**

```bash
cd /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515
PYTHONPATH=. pytest tests/test_publisher_youtube_state_normalize.py -v 2>&1 | tail -15
```

Ожидаемо: 4 PASS.

- [ ] **Step A.6: Регрессия — picker и imports**

```bash
PYTHONPATH=. pytest tests/test_publisher_youtube_picker.py tests/test_publisher_imports.py -q 2>&1 | tail -10
```

Ожидаемо: всё PASS (state-normalize изолирован).

- [ ] **Step A.7: Commit A**

```bash
cd /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515
git add publisher_youtube.py tests/test_publisher_youtube_state_normalize.py
git commit -m "feat(yt): нормализация состояния YT перед upload-flow (WP #74 task A)

После account_switch YT может остаться в Shorts feed с открытой 'Описание'
bottom-sheet или в Shorts camera — publish_youtube_short в обоих случаях
не находит меню создания и фейлится в _select_gallery_video с
all_clickable_count=0.

Helper _normalize_yt_state_pre_upload: force-stop YT → am start LAUNCHER →
2 итерации tap'ов permission/onboarding-кнопок. Вызывается в начале
publish_youtube_short после _ensure_correct_account.

Evidence: WP #74 — task 6513 (camera permission overlay) + 6515
(Shorts description sheet) за 2026-05-15."
```

---

## Task B: Permission-tap в `_select_gallery_video`

**Файлы:**
- Modify: `publisher_youtube.py:647-653` — расширить existing tap'ы внутри `for parse_attempt in range(4)` loop'а.
- Modify: `tests/test_publisher_youtube_picker.py` — новый тест.

### Шаги B

- [ ] **Step B.1: Failing test для permission-tap в picker**

Добавить в `tests/test_publisher_youtube_picker.py` после класса `TestSelectGalleryVideo`:

```python
class TestSelectGalleryVideoPermissionTap:
    """WP #74 Task B: picker tap'ит permission-кнопки внутри parse loop."""

    def test_permission_tap_inside_parse_loop(self):
        """Когда `_select_gallery_video` ловит фейл (no videos), он должен
        ТАПНУТЬ permission-buttons хотя бы раз — это даёт UI шанс отрисовать
        gallery после dismissal'а свежего onboarding-диалога.
        """
        pub = _StubPublisher(
            ui_xml=YT_PICKER_XML_NO_VIDEOS,
            push_ts=None,
            expected_basename=None,
        )
        # tap_element будет вызван много раз; интересуют permission-patterns
        pub._select_gallery_video('/sdcard/Download/test.mp4')
        perm_patterns_lower = {'при использовании приложения',
                               'только в этот раз'}
        perm_calls = [c for c in pub.tap_element.call_args_list
                      if any(p.lower() in perm_patterns_lower
                             for p in c[0][1])]
        assert perm_calls, pub.tap_element.call_args_list
```

- [ ] **Step B.2: Run failing test**

```bash
cd /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515
PYTHONPATH=. pytest tests/test_publisher_youtube_picker.py::TestSelectGalleryVideoPermissionTap -v 2>&1 | tail -10
```

Ожидаемо: FAIL — текущий код тапает только `['ОК', 'OK', 'Разрешить']` (line 652) без `'При использовании приложения' / 'Только в этот раз'`.

- [ ] **Step B.3: Реализовать**

В `publisher_youtube.py` line 652 (внутри `for parse_attempt in range(4):`):

Заменить:
```python
            if self.tap_element(ui, ['ОК', 'OK', 'Разрешить']):
                time.sleep(2); continue
```
на:
```python
            # WP #74: расширенный список включает Android 10+ permission-кнопки.
            if self.tap_element(ui, [
                'ОК', 'OK', 'Разрешить', 'Allow',
                'При использовании приложения', 'Только в этот раз',
                'Понятно',
            ]):
                time.sleep(2); continue
```

- [ ] **Step B.4: Run test — pass**

```bash
PYTHONPATH=. pytest tests/test_publisher_youtube_picker.py -v 2>&1 | tail -20
```

Ожидаемо: все picker-тесты PASS (включая новый).

- [ ] **Step B.5: Commit B**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_picker.py
git commit -m "feat(yt): permission-tap расширен в _select_gallery_video (WP #74 task B)

В parse loop _select_gallery_video добавлены 'При использовании приложения',
'Только в этот раз', 'Allow', 'Понятно' — Android 10+ permission-кнопки,
которые могли заблокировать gallery после Shell_UploadActivity на свежем YT.

Evidence: task 6513 (2026-05-15) висел на 'Откройте YouTube доступ к камере'
весь fail-окно — picker dialog handler ловил только 'ОК/OK/Разрешить'."
```

---

## Task C: Обогащённая meta при fail-fast

**Файлы:**
- Modify: `publisher_youtube.py:712-731` (блок fail-fast).
- Modify: `tests/test_publisher_youtube_picker.py` — расширить
  `test_no_videos_fails_fast`.

### Шаги C

- [ ] **Step C.1: Update test для meta enrichment**

В `tests/test_publisher_youtube_picker.py` тест `test_no_videos_fails_fast` —
расширить ассерты в конце (после уже существующих
`assert 'all_clickable_count' in meta` / `assert 'first_clickables' in meta`):

```python
        # WP #74 task C — meta обогащена для post-mortem
        assert 'top_resumed_activity' in meta
        assert 'current_package' in meta
```

- [ ] **Step C.2: Run failing test**

```bash
PYTHONPATH=. pytest tests/test_publisher_youtube_picker.py::TestSelectGalleryVideo::test_no_videos_fails_fast -v 2>&1 | tail -10
```

Ожидаемо: FAIL — `top_resumed_activity` not in meta.

- [ ] **Step C.3: Реализовать**

В `publisher_youtube.py` блок fail-fast (line 712-731). Сразу после `if not video_selected:` (line 712) и перед `log.error('YouTube: видео не найдено в gallery picker — abort')` добавить:

```python
            # WP #74: топ-активность + package для post-mortem (понять, был ли
            # YT вообще в upload-state когда picker фейлится).
            top_act = ''
            try:
                _act_raw = self.adb(
                    'dumpsys activity activities 2>/dev/null '
                    '| grep -m1 "topResumedActivity"', timeout=5
                ) or ''
                top_act = _act_raw.strip()[:200]
            except Exception:
                pass
            cur_pkg = ''
            try:
                _pkg_raw = self.adb(
                    'dumpsys window 2>/dev/null '
                    '| grep -m1 "mCurrentFocus"', timeout=5
                ) or ''
                cur_pkg = _pkg_raw.strip()[:200]
            except Exception:
                pass
```

И в `meta` блока `self.log_event('error', 'YT: видео не найдено в gallery picker — fail-fast', ...)` добавить два новых поля. Текущий блок:

```python
            self.log_event(
                'error',
                'YT: видео не найдено в gallery picker — fail-fast',
                meta={'category': 'yt_gallery_no_video_candidate',
                      'platform': self.platform,
                      'step': 'yt_gallery_select',
                      'all_clickable_count': len(last_all_items or []),
                      'first_clickables': diag},
            )
```

Заменить meta-словарь на:

```python
            self.log_event(
                'error',
                'YT: видео не найдено в gallery picker — fail-fast',
                meta={'category': 'yt_gallery_no_video_candidate',
                      'platform': self.platform,
                      'step': 'yt_gallery_select',
                      'all_clickable_count': len(last_all_items or []),
                      'first_clickables': diag,
                      'top_resumed_activity': top_act,
                      'current_package': cur_pkg},
            )
```

- [ ] **Step C.4: Обновить _StubPublisher**

`_StubPublisher` (line 48-73 в test_publisher_youtube_picker.py) не имеет `self.adb`. Добавить:

```python
        self.adb = MagicMock(return_value='')
```

- [ ] **Step C.5: Run test — pass**

```bash
PYTHONPATH=. pytest tests/test_publisher_youtube_picker.py -v 2>&1 | tail -20
```

Ожидаемо: все picker-тесты PASS.

- [ ] **Step C.6: Commit C**

```bash
git add publisher_youtube.py tests/test_publisher_youtube_picker.py
git commit -m "feat(yt): fail-fast meta — top_resumed_activity + current_package (WP #74 task C)

При yt_gallery_no_video_candidate сейчас в meta только
all_clickable_count + first_clickables — нельзя отличить 'YT в upload-state
без видимой галереи' от 'YT вообще не в upload-state'. Добавляем
topResumedActivity + mCurrentFocus для будущего post-mortem.

Категорию yt_gallery_no_video_candidate сохраняем — dashboards привязаны
к ней."
```

---

## Task D: Полный pytest + codex review кода

- [ ] **Step D.1: Полный прогон тестов на затронутых файлах**

```bash
cd /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515
PYTHONPATH=. pytest \
  tests/test_publisher_youtube_picker.py \
  tests/test_publisher_youtube_state_normalize.py \
  tests/test_publisher_imports.py \
  -v 2>&1 | tail -30
```

Ожидаемо: всё PASS.

- [ ] **Step D.2: Codex review uncommitted? — нет, всё закоммичено. Diff vs main:**

```bash
git diff origin/main...HEAD | ~/.local/bin/codex review - 2>&1 | tail -80
```

Если codex P1 — исправить inline, добавить commit `fix(yt): codex review P1`.

- [ ] **Step D.3: Push branch + PR**

```bash
cd /home/claude-user/autowarm-testbench-feat-yt-state-normalize-20260515
git push -u origin feat/yt-state-normalize-20260515
gh pr create --title "YT post-switch upload state normalization (WP #74)" \
  --body "$(cat <<'EOF'
## Что было не так

За 2026-05-15 2 YT-публикации (task 6513, 6515) упали с
`yt_gallery_no_video_candidate` после успешного account_switch:

- **6513** (oracle_spacee): YT застрял на системном диалоге камеры
  «Откройте YouTube доступ к камере и микрофону» (При использовании / Только в этот раз / Запретить).
- **6515** (oraclevisionn): YT остался на Shorts feed с открытой 'Описание' bottom-sheet
  («Богатенький Ричи 1994»).

Watchdog `post-account-switch` ловил оба за 120s, потом `_select_gallery_video`
фейлился с `all_clickable_count: 0`.

## Что сделано

- **A.** `_normalize_yt_state_pre_upload`: force-stop YT → `am start ... LAUNCHER`
  → 2 итерации tap'ов permission/onboarding-кнопок. Вызывается в начале
  `publish_youtube_short` после `_ensure_correct_account`.
- **B.** В parse loop `_select_gallery_video` добавлены 'При использовании приложения',
  'Только в этот раз', 'Allow', 'Понятно' — Android 10+ permission-кнопки.
- **C.** Meta при fail-fast обогащена `top_resumed_activity` + `current_package`
  для post-mortem (категория `yt_gallery_no_video_candidate` сохранена —
  dashboards привязаны к ней).

Spec + plan: `docs/superpowers/specs/2026-05-15-yt-post-switch-upload-state-normalization-design.md`
+ `docs/superpowers/plans/2026-05-15-yt-post-switch-upload-state-normalization.md`.

## Что осталось

Live verify — 0 fails `yt_gallery_no_video_candidate` за 24h при ненулевом
объёме YT-задач. Если кейс повторится — meta теперь содержит
`top_resumed_activity` для уточнения root cause.

OpenProject: https://openproject.contenthunter.ru/work_packages/74
EOF
)"
```

- [ ] **Step D.4: Update OpenProject WP #74 с PR URL**

```bash
source ~/secrets/openproject.env
PR_URL="<URL from gh pr create output>"
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST \
  "$OPENPROJECT_URL/api/v3/work_packages/74/activities" \
  -d "{\"comment\":{\"raw\":\"PR открыт: $PR_URL\\n\\nЧто сделано: A (state-normalize), B (permission-tap в picker), C (meta enrichment). Все тесты зелёные.\\n\\nЧто осталось: live verify 0 fails yt_gallery_no_video_candidate за 24h.\"}}"
```

---

## Self-review checklist

**Spec coverage:**
- ✅ A (state-normalize): Task A.
- ✅ B (permission-tap в picker): Task B.
- ✅ C (meta enrichment): Task C.
- ✅ Tests (unit для picker + новый для state-normalize): Task A.1, B.1, C.1.
- ✅ Live verify: упомянуто в PR description + WP comment (Task D.3-D.4).

**Placeholders:** нет TBD/TODO — все шаги содержат конкретный код.

**Type consistency:** `_normalize_yt_state_pre_upload` сигнатура одна:
`(self) -> None`, в тесте и в реализации идентична. `platform_cfg['package']`
используется и в `publish_youtube_short` (line 739), и в новом методе.

**Scope:** одна публикационная функция, два изменения в существующем методе,
один новый метод. Достаточно для одного PR.
