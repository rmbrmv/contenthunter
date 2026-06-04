# WP#250 — TikTok story-derail real root-cause (Phase 1: evidence) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Инструментировать TT-upload-флоу диагностическим trace, прогнать canary на phone #19 и снять живую сигнатуру экранов story-derail — БЕЗ написания фикса (фикс = отдельный план после decision gate).

**Architecture:** Новый kill-switched хелпер `_tt_trace_capture` снимает activity+XML+скриншот в S3 и логирует `tt_trace_*` события в 3 точках (пост-switch, per-iteration в стейт-машине, терминальная сводка). Default OFF → ноль накладных в проде. Canary гоняется на изолированном тестбенч-стенде (`autowarm-testbench`, phone #19), прод-публикатор не затрагивается. План ЗАКАНЧИВАЕТСЯ decision gate — Фаза 2 (фикс) пишется отдельным планом против снятых дампов.

**Tech Stack:** Python (publisher_tiktok.py / publisher_base.py), pytest (unittest.mock), PostgreSQL events JSONB (host localhost:5432), S3 (save.gengo.io), ADB/uiautomator, testbench orchestrator.

**Репозиторий кода:** `delivery-contenthunter` (autowarm). Прод-чекаут `/root/.openclaw/workspace-genri/autowarm` (root-owned, git без sudo). Тестбенч-чекаут `/home/claude-user/autowarm-testbench` (claude-user). Доки — этот репо (`rmbrmv/contenthunter`).

---

## File Structure

- **Modify** `publisher_tiktok.py`:
  - `_init_wait_upload_overlay_state` (`:715`) — инициализация `self._tt_trace_urls = []`.
  - Новый метод `_tt_trace_capture(label, branch, upload_iter)` — рядом с другими `_tt_*` хелперами.
  - `publish_tiktok` (`:3231`) — точка A (пост-switch snapshot).
  - `_tt_inapp_upload_from_camera` (`:1470`, `:1508`, `:1592`, `:1627`) — точки B (a3/c/g) и C (терминальная сводка).
- **Create** `tests/test_publisher_tt_upload_trace.py` — юнит-тесты `_tt_trace_capture` и wiring.
- **No changes** к Instagram/YouTube, switcher, стейт-машине (логика веток не меняется — только добавляются `if trace` вызовы).

---

## Task 1: Хелпер `_tt_trace_capture` (TDD)

**Files:**
- Create: `tests/test_publisher_tt_upload_trace.py`
- Modify: `publisher_tiktok.py` (новый метод + `_init_wait_upload_overlay_state:715`)

- [ ] **Step 1: Write the failing test (disabled-by-default + enabled-path + never-raises)**

Создать `tests/test_publisher_tt_upload_trace.py`:

```python
"""Unit tests for TT upload diagnostic trace (WP#250, Phase 1 evidence)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_tiktok import TikTokMixin  # noqa: E402


def _bare_mixin() -> TikTokMixin:
    mx = TikTokMixin.__new__(TikTokMixin)
    mx.platform = 'TikTok'
    mx.task_id = 999
    mx._init_wait_upload_overlay_state()
    mx.log_event = MagicMock()
    mx.adb = MagicMock(return_value='  topResumedActivity: ActivityRecord{x SocialMediaPickerActivity}')
    mx._save_debug_screenshot = MagicMock(return_value='https://s3/shot.png')
    mx._save_debug_ui_dump = MagicMock(return_value='https://s3/dump.xml')
    return mx


def test_trace_disabled_by_default(monkeypatch):
    monkeypatch.delenv('TT_INAPP_UPLOAD_TRACE_ENABLED', raising=False)
    mx = _bare_mixin()
    mx._tt_trace_capture('state', 'unknown', 3)
    mx.log_event.assert_not_called()
    mx._save_debug_ui_dump.assert_not_called()
    mx.adb.assert_not_called()


def test_trace_enabled_logs_event_and_collects_url(monkeypatch):
    monkeypatch.setenv('TT_INAPP_UPLOAD_TRACE_ENABLED', 'true')
    mx = _bare_mixin()
    mx._tt_trace_capture('state', 'story_derail', 5)
    assert mx._save_debug_ui_dump.called
    assert 'https://s3/dump.xml' in mx._tt_trace_urls
    args, kwargs = mx.log_event.call_args
    meta = kwargs.get('meta') or args[2]
    assert meta['category'] == 'tt_trace_state'
    assert meta['branch'] == 'story_derail'
    assert meta['upload_iter'] == 5
    assert 'SocialMediaPickerActivity' in meta['activity']
    assert meta['dump_url'] == 'https://s3/dump.xml'


def test_trace_never_raises_on_capture_error(monkeypatch):
    monkeypatch.setenv('TT_INAPP_UPLOAD_TRACE_ENABLED', 'true')
    mx = _bare_mixin()
    mx._save_debug_ui_dump = MagicMock(side_effect=RuntimeError('boom'))
    # Must not raise — diagnostics may never break the publish flow.
    mx._tt_trace_capture('post_switch', 'post_switch', None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_publisher_tt_upload_trace.py -v`
Expected: FAIL — `AttributeError: 'TikTokMixin' object has no attribute '_tt_trace_capture'` (и/или `_tt_trace_urls`).

- [ ] **Step 3: Init `_tt_trace_urls` в `_init_wait_upload_overlay_state`**

В `publisher_tiktok.py`, внутри `_init_wait_upload_overlay_state` (около `:715`, рядом с `self._inapp_unknown_resets = 0`), добавить:

```python
        # WP#250: diagnostic trace dump URLs accumulated per publish (point C).
        self._tt_trace_urls = []
```

- [ ] **Step 4: Реализовать `_tt_trace_capture`**

Добавить метод в `publisher_tiktok.py` (рядом с другими `_tt_*` хелперами, например после `_tt_reset_to_feed`):

```python
    def _tt_trace_capture(self, label: str, branch: str, upload_iter) -> None:
        """WP#250: диагностический trace для root-cause story-derail.

        Снимает topResumedActivity + скриншот + XML-дамп в S3 и пишет событие
        tt_trace_{label}. No-op, пока TT_INAPP_UPLOAD_TRACE_ENABLED != 'true'.
        НИКОГДА не бросает — диагностика не должна ломать публикацию.

        Args:
            label: 'post_switch' | 'state' (→ category tt_trace_<label>).
            branch: ветка стейт-машины ('post_switch'/'story_editor'/
                    'story_derail'/'unknown').
            upload_iter: номер итерации upload-цикла или None.
        """
        if os.environ.get('TT_INAPP_UPLOAD_TRACE_ENABLED',
                          'false').lower() != 'true':
            return
        try:
            activity = self.adb(
                'dumpsys activity activities 2>/dev/null '
                '| grep -m1 "topResumedActivity"', timeout=8) or ''
            activity = activity.strip()[:200]
            shot_url = self._save_debug_screenshot(f'trace_{label}')
            dump_url = self._save_debug_ui_dump(f'trace_{label}')
            if dump_url:
                try:
                    self._tt_trace_urls.append(dump_url)
                except AttributeError:
                    self._tt_trace_urls = [dump_url]
            self.log_event(
                'info',
                f'TikTok trace [{branch}] iter={upload_iter}',
                meta={'category': f'tt_trace_{label}',
                      'branch': branch,
                      'upload_iter': upload_iter,
                      'activity': activity,
                      'dump_url': dump_url,
                      'shot_url': shot_url,
                      'platform': self.platform})
        except Exception as e:
            log.warning(f'_tt_trace_capture({label}) error: {e}')
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_publisher_tt_upload_trace.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add tests/test_publisher_tt_upload_trace.py publisher_tiktok.py
git commit -m "feat(wp250): _tt_trace_capture diagnostic helper (kill-switch, default OFF)"
```

---

## Task 2: Точка A — пост-switch snapshot (TDD)

**Files:**
- Modify: `publisher_tiktok.py:3231` (в `publish_tiktok`, после `_ensure_correct_account`)
- Test: `tests/test_publisher_tt_upload_trace.py`

- [ ] **Step 1: Write the failing test**

Добавить в `tests/test_publisher_tt_upload_trace.py`:

```python
def test_post_switch_snapshot_wired(monkeypatch):
    """publish_tiktok вызывает trace('post_switch') сразу после switch."""
    monkeypatch.setenv('TT_INAPP_UPLOAD_TRACE_ENABLED', 'true')
    mx = _bare_mixin()
    mx._tt_trace_capture = MagicMock()
    # Останавливаем поток сразу после switch: switch ok, но дальше не идём.
    mx.ensure_unlocked = MagicMock(return_value=True)
    mx.dismiss_overlay_dialogs = MagicMock(return_value=False)
    mx._ensure_correct_account = MagicMock(return_value=True)
    mx._snapshot_pre_publish_video_ids = MagicMock()
    mx.dump_ui = MagicMock(return_value='<hierarchy></hierarchy>')
    mx.set_step = MagicMock()
    mx._init_music_rights_state = MagicMock()
    mx._init_commercial_music_state = MagicMock()
    mx.platform_cfg = {'package': 'com.zhiliaoapp.musically'}
    # in-app upload вернёт False сразу → выходим из publish_tiktok рано.
    mx._tt_inapp_upload_from_camera = MagicMock(return_value=False)
    monkeypatch.setenv('TT_INAPP_UPLOAD_VIA_CAMERA_ENABLED', 'true')

    mx.publish_tiktok('/sdcard/x.mp4')

    labels = [c.args[0] for c in mx._tt_trace_capture.call_args_list]
    assert 'post_switch' in labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_publisher_tt_upload_trace.py::test_post_switch_snapshot_wired -v`
Expected: FAIL — `assert 'post_switch' in []` (вызов ещё не добавлен).

- [ ] **Step 3: Добавить вызов в `publish_tiktok`**

В `publisher_tiktok.py`, сразу после блока `_ensure_correct_account` (после `:3221 return False`) и ПЕРЕД `_snapshot_pre_publish_video_ids` (`:3223`), вставить:

```python
        # WP#250: пост-switch snapshot — снять реальную Activity, куда switcher
        # приземлил поток (проверка гипотезы: SocialMediaPickerActivity?).
        self._tt_trace_capture('post_switch', 'post_switch', upload_iter=None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_publisher_tt_upload_trace.py::test_post_switch_snapshot_wired -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_upload_trace.py
git commit -m "feat(wp250): point A — post-switch trace snapshot in publish_tiktok"
```

---

## Task 3: Точка B — per-iteration trace в стейт-машине (TDD)

**Files:**
- Modify: `publisher_tiktok.py:1470` (a3 story-editor), `:1508` (c story-derail), `:1592` (g unknown)
- Test: `tests/test_publisher_tt_upload_trace.py`

- [ ] **Step 1: Write the failing test (story-derail ветка снимает trace до BACK)**

Добавить в `tests/test_publisher_tt_upload_trace.py`:

```python
def test_state_trace_on_story_derail(monkeypatch):
    """Ветка story-derail снимает trace('state','story_derail') до BACK."""
    monkeypatch.setenv('TT_INAPP_UPLOAD_TRACE_ENABLED', 'true')
    monkeypatch.setenv('TT_INAPP_UNKNOWN_RESET_ENABLED', 'false')
    mx = _bare_mixin()
    mx._tt_trace_capture = MagicMock()
    mx.set_step = MagicMock()
    mx.adb_tap = MagicMock()
    mx._pushed_video_duration_s = None
    mx._tt_foreground_pkg = MagicMock(return_value='com.zhiliaoapp.musically')
    mx.dump_ui = MagicMock(return_value='<hierarchy></hierarchy>')
    mx._is_tt_caption_screen = MagicMock(return_value=False)
    mx._tt_detect_profile_screen = MagicMock(return_value=False)
    mx._tt_detect_inapp_story_editor = MagicMock(return_value=False)
    # editor markers absent → branch b skipped
    mx._tt_in_gallery_picker = MagicMock(return_value=False)
    mx._tt_detect_story_derail = MagicMock(return_value=True)

    mx._tt_inapp_upload_from_camera()

    calls = [(c.args[0], c.args[1]) for c in mx._tt_trace_capture.call_args_list]
    assert ('state', 'story_derail') in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_publisher_tt_upload_trace.py::test_state_trace_on_story_derail -v`
Expected: FAIL — `('state','story_derail')` отсутствует в вызовах.

- [ ] **Step 3: Добавить вызовы trace в 3 ветки**

В `_tt_inapp_upload_from_camera`:

**(a3) story-editor** — внутри блока `if (... _tt_detect_inapp_story_editor(ui)):` (`:1472`), ПЕРВОЙ строкой после `if`, до инкремента счётчика (`:1473`):
```python
                self._tt_trace_capture('state', 'story_editor', it)
```

**(c) story-derail** — внутри `if self._tt_detect_story_derail(ui, fg):` (`:1508`), ПЕРВОЙ строкой после `if`, до инкремента (`:1509`):
```python
                self._tt_trace_capture('state', 'story_derail', it)
```

**(g) unknown** — в ветке `else:` (`:1592`), ПЕРВОЙ строкой блока (до `rec = self._tt_recover_from_storyservice_fg(...)`, `:1593`):
```python
                self._tt_trace_capture('state', 'unknown', it)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_publisher_tt_upload_trace.py::test_state_trace_on_story_derail -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_upload_trace.py
git commit -m "feat(wp250): point B — per-iteration trace on story_editor/story_derail/unknown"
```

---

## Task 4: Точка C — терминальная сводка trace_urls (TDD)

**Files:**
- Modify: `publisher_tiktok.py:1627` (терминальный `tt_inapp_upload_unreached`)
- Test: `tests/test_publisher_tt_upload_trace.py`

- [ ] **Step 1: Write the failing test**

Добавить в `tests/test_publisher_tt_upload_trace.py`:

```python
def test_terminal_event_includes_trace_urls(monkeypatch):
    """Терминальный tt_inapp_upload_unreached несёт собранные trace_urls."""
    monkeypatch.setenv('TT_INAPP_UPLOAD_TRACE_ENABLED', 'false')
    monkeypatch.setenv('TT_INAPP_UNKNOWN_RESET_ENABLED', 'false')
    mx = _bare_mixin()
    mx._tt_trace_urls = ['https://s3/a.xml', 'https://s3/b.xml']
    mx.set_step = MagicMock()
    mx._save_debug_artifacts = MagicMock()
    mx._pushed_video_duration_s = None
    mx._tt_foreground_pkg = MagicMock(return_value='launcher')
    mx.dump_ui = MagicMock(return_value='<hierarchy></hierarchy>')
    mx._is_tt_caption_screen = MagicMock(return_value=False)
    mx._tt_detect_profile_screen = MagicMock(return_value=False)
    mx._tt_detect_inapp_story_editor = MagicMock(return_value=False)
    mx._tt_in_gallery_picker = MagicMock(return_value=False)
    mx._tt_detect_story_derail = MagicMock(return_value=False)
    mx._tt_detect_camera_screen = MagicMock(return_value=False)
    mx._tt_detect_feed = MagicMock(return_value=False)
    mx._tt_recover_from_storyservice_fg = MagicMock(return_value='none')
    mx.MAX_INAPP_UPLOAD_ITERATIONS = 1  # пройти 1 итерацию → терминал

    mx._tt_inapp_upload_from_camera()

    term = [c for c in mx.log_event.call_args_list
            if (c.kwargs.get('meta') or {}).get('category') == 'tt_inapp_upload_unreached']
    assert term, 'терминальное событие не залогировано'
    meta = term[-1].kwargs['meta']
    assert meta['trace_urls'] == ['https://s3/a.xml', 'https://s3/b.xml']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_publisher_tt_upload_trace.py::test_terminal_event_includes_trace_urls -v`
Expected: FAIL — `KeyError: 'trace_urls'` (ключа ещё нет в meta).

- [ ] **Step 3: Добавить trace_urls в терминальный meta**

В `_tt_inapp_upload_from_camera`, терминальный `log_event` (`:1627-1630`), расширить `meta`:

```python
        self.log_event(
            'error', 'TikTok: in-app upload не достиг редактора за лимит',
            meta={'category': 'tt_inapp_upload_unreached', 'platform': self.platform,
                  'entered_gallery': entered_gallery,
                  'trace_urls': getattr(self, '_tt_trace_urls', [])})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_publisher_tt_upload_trace.py::test_terminal_event_includes_trace_urls -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_upload_trace.py
git commit -m "feat(wp250): point C — attach collected trace_urls to terminal event"
```

---

## Task 5: Регрессия TT-набора

**Files:** нет изменений — только верификация.

- [ ] **Step 1: Прогнать весь новый файл + смежные TT in-app тесты**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest \
  tests/test_publisher_tt_upload_trace.py \
  tests/test_publisher_tt_inapp_upload.py \
  -v
```
Expected: all PASS (новые 6 + существующие in-app тесты зелёные).

- [ ] **Step 2: Прогнать широкий TT-набор (нет регрессий от wiring)**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/ -k "tt or tiktok" -q
```
Expected: 0 failed (если есть pre-existing флаки — зафиксировать список, убедиться что не связаны с trace).
> ⚠️ Полный `pytest tests/` зависает (live-наборы) — используем курируемый `-k` фильтр (урок из IG-триажа 04.06).

- [ ] **Step 3: Commit (если правок не было — пропустить)**

Правок кода на этом шаге нет; коммит не требуется.

---

## Task 6: Подготовка canary-стенда (manual / ops, GATED)

> ⚠️ Общий тестбенч-стенд. Координация с Данилом ОБЯЗАТЕЛЬНА перед переключением.
> Выполняется на прод-хосте (где живёт phone #19 / Pi #7), НЕ в worktree.

- [ ] **Step 1: Согласовать окно canary с Данилом** (стенд один, phone #19).

- [ ] **Step 2: Проверить, что стенд не на паузе и не занят**

Run:
```bash
psql -h localhost -p 5432 -U <user> -d <db> -c \
  "SELECT key,value FROM system_flags WHERE key='testbench_paused';"
psql -h localhost -p 5432 -U <user> -d <db> -c \
  "SELECT id,platform,status FROM publish_tasks WHERE testbench=TRUE AND status IN ('pending','publishing') ORDER BY id DESC LIMIT 5;"
```
Expected: `testbench_paused` ≠ 'true' (или отсутствует); нет активных testbench-задач в работе.

- [ ] **Step 3: Запомнить текущее состояние тестбенч-чекаута (для отката)**

Run:
```bash
cd /home/claude-user/autowarm-testbench && git rev-parse --abbrev-ref HEAD && git rev-parse HEAD
grep -n TT_INAPP_UPLOAD_TRACE_ENABLED .env 2>/dev/null || echo "trace var отсутствует (ожидаемо)"
```
Записать ветку/коммит — вернём после canary.

- [ ] **Step 4: Перевести тестбенч-чекаут на ветку WP#250 + включить trace**

Run:
```bash
cd /home/claude-user/autowarm-testbench
git fetch origin && git checkout wp250-tt-story-derail-rootcause && git pull --ff-only
grep -q TT_INAPP_UPLOAD_TRACE_ENABLED .env \
  && sed -i 's/^TT_INAPP_UPLOAD_TRACE_ENABLED=.*/TT_INAPP_UPLOAD_TRACE_ENABLED=true/' .env \
  || echo 'TT_INAPP_UPLOAD_TRACE_ENABLED=true' >> .env
```
> Тестбенч-скедулер спавнит `publisher.py` из ЭТОГО чекаута per-task → рестарт PM2 не нужен (новый код подхватится следующим спавном). Если `autowarm-testbench` кэширует процесс — `pm2 restart autowarm-testbench`.

- [ ] **Step 5: Подтвердить, что seed-видео TikTok на месте**

Run: `ls -la /home/claude-user/testbench-seed/tiktok/ | head`
Expected: ≥1 видео-файл (иначе `tick` не создаст задачу).

---

## Task 7: Прогон canary и сбор evidence (manual, GATED)

> Выполняется на прод-хосте. N=3–5 реальных публикаций на phone #19.

- [ ] **Step 1: Создать TikTok-canary-задачу (повторить N=3–5 раз с интервалом)**

Run (из тестбенч-дир):
```bash
cd /home/claude-user/autowarm-testbench
python3 -c "import testbench_orchestrator as t; print(t.tick({'idx':1}))"
```
> `PLATFORMS=['Instagram','TikTok','YouTube']` → `idx=1` = **TikTok**. `tick` берёт свежий аккаунт+seed phone #19 и создаёт реальную задачу. Сырой requeue старых задач НЕ работает (media_path обнулён post-cleanup) — только `tick`.
> Между прогонами ждать завершения предыдущей задачи (стенд = 1 телефон).

- [ ] **Step 2: Дождаться завершения каждой задачи и собрать trace-события**

Run:
```bash
psql -h localhost -p 5432 -U <user> -d <db> -c \
"SELECT id, status, jsonb_path_query_array(events,'\$[*] ? (@.meta.category like_regex \"tt_trace\")') \
 FROM publish_tasks WHERE testbench=TRUE AND platform='TikTok' ORDER BY id DESC LIMIT 5;"
```
Expected: события `tt_trace_post_switch` / `tt_trace_state` с `meta.activity`, `meta.branch`, `meta.dump_url`.

- [ ] **Step 3: Скачать XML-дампы и скриншоты из S3**

Для каждого `dump_url`/`shot_url` из событий:
```bash
mkdir -p /tmp/wp250-evidence && cd /tmp/wp250-evidence
curl -sO "<dump_url>"   # https://save.gengo.io/autowarm/ui_dumps/...
curl -sO "<shot_url>"   # https://save.gengo.io/autowarm/screenshots/...
```

- [ ] **Step 4: Откатить тестбенч-стенд в исходное состояние**

Run:
```bash
cd /home/claude-user/autowarm-testbench
sed -i 's/^TT_INAPP_UPLOAD_TRACE_ENABLED=.*/TT_INAPP_UPLOAD_TRACE_ENABLED=false/' .env
git checkout <сохранённая-ветка-из-Task6-Step3>
```
> Обязательно — иначе следующая чужая сессия получит чужой код/включённый trace.

- [ ] **Step 5: Собрать сводную таблицу траектории**

Создать `/tmp/wp250-evidence/signature.md`: строки = (run_id, upload_iter, activity, ключевые узлы XML, ветка стейт-машины). Цель — увидеть стабильную точку рождения derail по N прогонам.

---

## Task 8: DECISION GATE — STOP (фикс = отдельный план)

**Files:** нет кода.

- [ ] **Step 1: Показать Данилу evidence**

Предоставить: `signature.md` + скриншоты ключевых экранов + вывод о реальном корне (один из):
- **(i) switcher** приземляет на share/story-Activity;
- **(ii) точка входа** ведёт через story-галерею;
- **(iii) пост-switch навигация** уходит в share-flow.

- [ ] **Step 2: Согласовать конкретный фикс** (i/ii/iii или гибрид). НЕ переоткрывать iter5/iter6 как есть.

- [ ] **Step 3: STOP — вернуться в brainstorming/writing-plans для Фазы 2**

Написать отдельный план `docs/superpowers/plans/YYYY-MM-DD-wp250-phase2-fix.md` с:
- Red-тестами на реальные XML-дампы (фикстуры из `/tmp/wp250-evidence/`);
- фиксом за НОВЫМ kill-switch (default OFF до canary-верификации — не повторить регрессию iter6 32%→10%);
- canary-верификацией на phone #19 (публикация до caption, `/video/` URL, 0 событий derail);
- прод-деплоем + включением kill-switch дефолтом отдельным шагом после суток.

> ⛔ НЕ начинать Фазу 2, пока сигнатура не снята и фикс не согласован на гейте.

---

## Self-Review notes

- **Spec coverage:** точки A/B/C → Tasks 2/3/4; kill-switch `TT_INAPP_UPLOAD_TRACE_ENABLED` → Task 1; постоянство (не throwaway) → код остаётся; canary N=3–5 + изоляция стенда → Tasks 6/7; decision gate + 3 исхода → Task 8; Фаза 2 (TDD+canary+kill-switch) → Task 8 Step 3 (отдельный план, by design).
- **No placeholders:** весь код приведён; команды и ожидаемые выводы конкретны. `<user>/<db>` в psql — реальные креды берутся из окружения прод-хоста на момент выполнения (не хардкодим секреты в план).
- **Type consistency:** `_tt_trace_capture(label, branch, upload_iter)`, `_tt_trace_urls`, категории `tt_trace_post_switch`/`tt_trace_state`, env `TT_INAPP_UPLOAD_TRACE_ENABLED` — единообразны во всех задачах.
