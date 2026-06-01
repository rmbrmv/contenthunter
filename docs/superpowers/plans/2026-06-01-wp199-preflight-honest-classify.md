# WP#199 — Честная классификация preflight/media-фейлов — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить маску `switch_failed_unspecified`, переупорядочив `log_event('error', meta=category)` перед `update_status('failed')` в двух fail-точках `publisher_base.py`, чтобы error_code-маппер видел реальную preflight/media-категорию.

**Architecture:** `update_status('failed')` синхронно запускает `_set_error_code_from_events`, читающий `events` из БД. Если error-event с `meta.category` ещё не записан — маппер падает в catch-all. Фикс = в двух блоках сначала логировать error-event, потом менять статус. Без правок маппера, каталога, triage_classifier.

**Tech Stack:** Python 3.12, psycopg2, pytest. БД событий — host-PG `localhost:5432` (openclaw/openclaw123, db openclaw). Код в `autowarm-testbench`, worktree `.worktrees/wp199`, ветка `wp199-preflight-honest-classify`.

**Spec:** `docs/superpowers/specs/2026-06-01-wp199-preflight-honest-classify-design.md`

---

## File Structure

- **Modify:** `publisher_base.py` — 2 точки swap (preflight-блок ~L4328-4332, media-блок ~L4458-4459). Единственный продовый писатель error_code.
- **Create:** `tests/test_preflight_error_code_ordering.py` — статический тест порядка строк в исходнике (red→green guard самого фикса).
- **Modify:** `tests/test_error_code_mapper.py` — добавить DB-контракт-тесты «error-event первым → честный код» (документируют механизм для всех категорий).

Все пути — относительно корня worktree `/home/claude-user/autowarm-testbench/.worktrees/wp199`.

---

## Task 1: Swap порядка в двух fail-точках (red→green по статическому тесту)

**Files:**
- Create: `tests/test_preflight_error_code_ordering.py`
- Modify: `publisher_base.py` (preflight-блок и media-блок)

- [ ] **Step 1: Написать падающий тест порядка строк**

Создать `tests/test_preflight_error_code_ordering.py`:

```python
"""WP#199 — статический guard порядка в fail-точках publisher_base.

В обеих точках (ADB preflight, media-фаза) error-event с meta.category
ДОЛЖЕН логироваться ДО update_status('failed'), иначе error_code-маппер
(хук update_status) не видит категорию и пишет switch_failed_unspecified.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'publisher_base.py')


def _lines():
    with open(SRC, encoding='utf-8') as f:
        return f.readlines()


def _block(lines, start_marker, start_from=0):
    """Индексы [start, return] блока: от start_marker до первого `return`."""
    start = next((i for i in range(start_from, len(lines))
                  if start_marker in lines[i]), None)
    assert start is not None, f'start marker not found: {start_marker!r}'
    end = next((i for i in range(start, len(lines))
                if lines[i].strip() == 'return'), None)
    assert end is not None, f'no `return` after L{start+1}'
    return start, end


def _assert_error_before_status(lines, start, end, label):
    log_idx = next((i for i in range(start, end + 1)
                    if "log_event('error'" in lines[i]), None)
    status_idx = next((i for i in range(start, end + 1)
                       if "update_status('failed'" in lines[i]), None)
    assert log_idx is not None, f'{label}: нет log_event(error) в блоке'
    assert status_idx is not None, f'{label}: нет update_status(failed) в блоке'
    assert log_idx < status_idx, (
        f'{label}: log_event(error) (L{log_idx+1}) должен идти ДО '
        f'update_status(failed) (L{status_idx+1}) — ordering-баг WP#199'
    )


def test_preflight_logs_error_before_failed():
    lines = _lines()
    start, end = _block(lines, 'adb_ok, adb_err = self._preflight_adb_device()')
    _assert_error_before_status(lines, start, end, 'ADB preflight')


def test_media_phase_logs_error_before_failed():
    lines = _lines()
    start, end = _block(lines, "msg = f'{category}: {err}'")
    _assert_error_before_status(lines, start, end, 'media phase')
```

- [ ] **Step 2: Запустить тест — убедиться, что падает (red)**

Run: `cd /home/claude-user/autowarm-testbench/.worktrees/wp199 && python -m pytest tests/test_preflight_error_code_ordering.py -v`
Expected: оба теста FAIL с «log_event(error) (Lxxxx) должен идти ДО update_status(failed)».

- [ ] **Step 3: Применить swap — preflight-блок**

В `publisher_base.py`, в блоке `if not adb_ok:`, поменять местами две строки.

Было:
```python
            if not adb_ok:
                category = adb_err.get('category', 'adb_unknown')
                self.update_status('failed', f'ADB preflight: {category}')
                self.log_event('error', f'ADB preflight failed: {category}', meta=adb_err)
                return
```
Стало:
```python
            if not adb_ok:
                category = adb_err.get('category', 'adb_unknown')
                # WP#199: error-event ДО update_status — иначе error_code-маппер
                # (хук update_status) не видит meta.category и пишет catch-all
                # switch_failed_unspecified.
                self.log_event('error', f'ADB preflight failed: {category}', meta=adb_err)
                self.update_status('failed', f'ADB preflight: {category}')
                return
```

- [ ] **Step 4: Применить swap — media-блок**

В `publisher_base.py`, после chain'а сборки `msg`, поменять местами две строки.

Было:
```python
                else:
                    msg = f'{category}: {err}'
                self.update_status('failed', msg)
                self.log_event('error', msg, meta=err)
                return
```
Стало:
```python
                else:
                    msg = f'{category}: {err}'
                # WP#199: error-event ДО update_status (см. preflight выше).
                self.log_event('error', msg, meta=err)
                self.update_status('failed', msg)
                return
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит (green)**

Run: `cd /home/claude-user/autowarm-testbench/.worktrees/wp199 && python -m pytest tests/test_preflight_error_code_ordering.py -v`
Expected: оба теста PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-testbench/.worktrees/wp199
git add publisher_base.py tests/test_preflight_error_code_ordering.py
git commit -m "fix(wp199): log error-event before update_status in preflight+media fail paths

Ordering-баг: update_status('failed') запускает error_code-маппер, читающий
events из БД, ДО log_event('error',meta=category) → catch-all
switch_failed_unspecified маскировал adb_device_not_ready/adb_devices_unreachable/
media (371/371 за 7д). Swap порядка чинит все категории через эти 2 точки.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: DB-контракт-тесты честной классификации (документируют механизм)

**Files:**
- Modify: `tests/test_error_code_mapper.py`

- [ ] **Step 1: Расширить стаб `_DummyPublisher` атрибутом `_watchdog`**

В `tests/test_error_code_mapper.py` заменить класс:

```python
class _DummyPublisher:
    """Minimal stub — только нужные атрибуты для _set_error_code_from_events."""
    def __init__(self, task_id):
        self.task_id = task_id
```
на:
```python
class _DummyPublisher:
    """Minimal stub — атрибуты для _set_error_code_from_events / log_event / update_status."""
    def __init__(self, task_id):
        self.task_id = task_id
        self._watchdog = None  # log_event пингует watchdog только если не None
```

- [ ] **Step 2: Добавить контракт-тесты в конец `tests/test_error_code_mapper.py`**

```python
@pytest.mark.parametrize('category', [
    'adb_device_not_ready', 'adb_devices_unreachable', 'media_not_found',
])
def test_error_event_first_yields_honest_code(temp_task_id, category):
    """WP#199: log_event('error',meta=category) ДО update_status('failed')
    → маппер пишет реальную категорию, а не switch_failed_unspecified."""
    tid, conn, cur = temp_task_id
    pub = _DummyPublisher(tid)
    publisher_base.BasePublisher.log_event(
        pub, 'error', f'preflight: {category}', meta={'category': category})
    publisher_base.BasePublisher.update_status(
        pub, 'failed', f'preflight: {category}')
    conn.commit()
    cur.execute("SELECT error_code FROM publish_tasks WHERE id=%s", (tid,))
    assert cur.fetchone()[0] == category


def test_update_status_first_masks_as_catchall(temp_task_id):
    """WP#199 характеризация бага: status-first прячет категорию в catch-all
    (first-writer-wins в маппере не перезатирается поздним error-event)."""
    tid, conn, cur = temp_task_id
    pub = _DummyPublisher(tid)
    publisher_base.BasePublisher.update_status(
        pub, 'failed', 'preflight: adb_device_not_ready')
    publisher_base.BasePublisher.log_event(
        pub, 'error', 'preflight', meta={'category': 'adb_device_not_ready'})
    conn.commit()
    cur.execute("SELECT error_code FROM publish_tasks WHERE id=%s", (tid,))
    assert cur.fetchone()[0] == 'switch_failed_unspecified'
```

- [ ] **Step 3: Запустить новые тесты**

Run: `cd /home/claude-user/autowarm-testbench/.worktrees/wp199 && python -m pytest tests/test_error_code_mapper.py -v`
Expected: все тесты PASS (включая 3 параметризованных + characterization). Требуется доступ к host-PG localhost:5432.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench/.worktrees/wp199
git add tests/test_error_code_mapper.py
git commit -m "test(wp199): DB-контракт — error-event первым даёт честный код

3 параметризованных (adb_device_not_ready/adb_devices_unreachable/media_not_found)
+ characterization бага (status-first → switch_failed_unspecified).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Регрессионный прогон + verification

**Files:** (нет правок — только проверка)

- [ ] **Step 1: Прогнать релевантные наборы**

Run:
```bash
cd /home/claude-user/autowarm-testbench/.worktrees/wp199
python -m pytest tests/test_preflight_error_code_ordering.py \
                 tests/test_error_code_mapper.py \
                 tests/test_canonical_error_codes.py -v
```
Expected: все PASS, 0 failed.

- [ ] **Step 2: Проверить отсутствие импорт-регрессий публикатора**

Run: `cd /home/claude-user/autowarm-testbench/.worktrees/wp199 && python -c "import publisher_base; print('import OK')"`
Expected: `import OK`.

- [ ] **Step 3: Зафиксировать, что catch-all больше не пишется на новых preflight-фейлах (post-deploy verify, не блокер мержа)**

После деплоя (прод pull в каталоге autowarm под claude-user; рестарт PM2 для publisher не нужен — `_set_error_code_from_events`/call-flow в процессе, нужен restart воркера-публикатора id, уточнить при деплое), через сутки:
```sql
SELECT error_code, count(*) FROM publish_tasks
WHERE status='failed' AND updated_at > NOW() - INTERVAL '24 hours'
  AND events::text ~ 'adb_device_not_ready|adb_devices_unreachable|adb_push_|media_not_found|media_empty'
GROUP BY error_code ORDER BY 2 DESC;
```
Expected: доминируют честные коды (`adb_devices_unreachable`, `adb_device_not_ready`, …); `switch_failed_unspecified` стремится к 0.

---

## Notes / Out of scope
- **Не трогаем** `triage_classifier.py` (корректен + `if not testbench: return`), каталог `publish_error_codes` (коды уже есть с верным error_class), kill-switch не вводим.
- **Принятый эффект:** `adb_devices_unreachable` (network/manual) и media (unknown/manual) перестанут авто-ретраиться — согласовано.
- **Follow-up (noted, не в scope):** путь «Публикация не прошла» (~L4516) имеет тот же латентный ordering-баг, но в проде в catch-all сейчас не попадает (0/7д). Тем же swap'ом чинится при желании позже.
- **Деплой:** правка только в `publisher_base.py`; деплой = git pull в прод-каталоге autowarm. Рестарт процесса-публикатора нужен (код грузится при старте процесса). Уточнить id у Данила при деплое.
```
