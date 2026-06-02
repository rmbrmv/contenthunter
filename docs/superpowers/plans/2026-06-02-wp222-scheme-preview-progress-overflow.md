# WP#222 — Переполнение счётчика генерации превью: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить переполнение счётчика «Генерация превью…» (`41/34`, 121%) и зависание, починив первопричину — двойную обработку scheme_preview-таска воркером.

**Architecture:** Три независимых слоя. (а) Воркер штампует `owner_run_id` в `meta` при захвате таска и гардит все записи прогресса/финализации по нему — «осиротевший» второй воркер тихо отваливается. (б) Бэкенд считает прогресс как число реально отрендеренных превью (`COUNT` в `validator_scheme_previews`), а не из суммируемого `schemes_done`. (в) Фронт зажимает отображение ≤100%. Плюс разовый бэкфилл текущих залипших строк. Каждый слой — за kill-switch (кроме тривиального фронта).

**Tech Stack:** Python/asyncpg (unic-worker), FastAPI/SQLAlchemy/pydantic-settings (validator backend), Vue 3 + TypeScript + vitest (validator frontend), PostgreSQL (openclaw).

**Repos & окружения:**
- `unic-worker` (`/home/claude-user/unic-worker`) — деплой на хост `91.98.180.103` (за Данилом). Тесты: live-DB asyncpg, `project_id >= 100000`.
- `validator-contenthunter/backend` (`/home/claude-user/validator-contenthunter/backend`) — PM2 id24. Тесты: live-DB SQLAlchemy.
- `validator-contenthunter/frontend` — `npm run build`. Тесты: `vitest run`.
- Все правки кода — на ветке `wp222-...` каждого репозитория (изоляция от параллельных сессий; общий каталог гоняется).
- Прогон тестов воркера/бэкенда требует доступа к openclaw PG (`DATABASE_URL`/`TEST_DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw`).

---

## Task 1: Воркер — гард владельца таска (слой «а»)

**Files:**
- Modify: `/home/claude-user/unic-worker/worker.py`
- Test: `/home/claude-user/unic-worker/tests/test_owner_guard.py` (create)

### Task 1.1: env-флаг + helper `is_task_owner`

**Files:**
- Modify: `worker.py` (после строки 31, блок env-констант)
- Modify: `worker.py` (добавить helper рядом с `update_task_progress`, ~строка 150)
- Test: `tests/test_owner_guard.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_owner_guard.py`:

```python
"""Owner-guard: записи прогресса/финализации гардятся по meta.owner_run_id."""
import json
import pytest
from worker import is_task_owner, update_scheme_progress, mark_task_done

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _insert_processing(conn, pid, owner_meta='{}'):
    row = await conn.fetchrow("""
        INSERT INTO unic_tasks
          (task_type, project_id, current_status, schemes, schemes_total, schemes_done,
           schemes_error, input_video_url, project_name, payload_hash, meta, created_at, updated_at)
        VALUES
          ('scheme_preview', $1, 'processing', '[]'::text, 34, 0, 0,
           'http://t/s.mp4', 'test', $2, $3::jsonb, NOW(), NOW())
        RETURNING id
    """, pid, f'hash-{pid}-{owner_meta[:8]}', owner_meta)
    return row['id']


@pytest.mark.asyncio(loop_scope="session")
async def test_is_task_owner_matches_token(pool, clean_unic_tasks, test_project_id):
    pid = test_project_id
    async with pool.acquire() as conn:
        tid = await _insert_processing(conn, pid, '{"owner_run_id": "TOKEN_A"}')
    assert await is_task_owner(pool, tid, "TOKEN_A") is True
    assert await is_task_owner(pool, tid, "TOKEN_B") is False
    # None токен (guard off / legacy) — всегда owner
    assert await is_task_owner(pool, tid, None) is True
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/unic-worker && DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_owner_guard.py::test_is_task_owner_matches_token -v`
Expected: FAIL — `ImportError: cannot import name 'is_task_owner'`.

- [ ] **Step 3: Реализовать env-флаг и helper**

В `worker.py` после строки 31 (`MAX_WORKERS = ...`) добавить:

```python
# WP#222: гард владельца scheme_preview-таска — защита от двойной обработки.
OWNER_GUARD_ENABLED = os.environ.get('SCHEME_PREVIEW_OWNER_GUARD_ENABLED', '1') != '0'
```

После функции `update_task_progress` (после строки 152) добавить:

```python
async def is_task_owner(pool, task_id, owner_run_id) -> bool:
    """True если owner_run_id is None (guard off/legacy) или совпадает с meta.owner_run_id."""
    if owner_run_id is None:
        return True
    async with pool.acquire() as conn:
        current = await conn.fetchval(
            "SELECT meta->>'owner_run_id' FROM unic_tasks WHERE id=$1", task_id
        )
    return current == owner_run_id


async def update_scheme_progress(pool, task_id, owner_run_id, done, errors) -> int:
    """Гард-апдейт прогресса. Возвращает число изменённых строк (0 = владение потеряно)."""
    async with pool.acquire() as conn:
        status = await conn.execute(
            "UPDATE unic_tasks SET schemes_done=$2, schemes_error=$3, updated_at=NOW() "
            "WHERE id=$1 AND ($4::text IS NULL OR meta->>'owner_run_id' IS NOT DISTINCT FROM $4)",
            task_id, done, errors, owner_run_id,
        )
    return int(status.split()[-1])  # 'UPDATE N' → N
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd /home/claude-user/unic-worker && DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_owner_guard.py::test_is_task_owner_matches_token -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/unic-worker
git add worker.py tests/test_owner_guard.py
git commit -m "feat(worker): owner-guard helpers is_task_owner + update_scheme_progress (WP#222)"
```

### Task 1.2: гард-апдейт прогресса (тест)

**Files:**
- Test: `tests/test_owner_guard.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_owner_guard.py`:

```python
@pytest.mark.asyncio(loop_scope="session")
async def test_progress_update_blocked_on_owner_mismatch(pool, clean_unic_tasks, test_project_id):
    pid = test_project_id
    async with pool.acquire() as conn:
        tid = await _insert_processing(conn, pid, '{"owner_run_id": "TOKEN_A"}')

    # чужой токен → no-op, schemes_done не меняется
    n = await update_scheme_progress(pool, tid, "TOKEN_B", 10, 0)
    assert n == 0
    async with pool.acquire() as conn:
        done = await conn.fetchval("SELECT schemes_done FROM unic_tasks WHERE id=$1", tid)
    assert done == 0

    # свой токен → апдейт проходит
    n2 = await update_scheme_progress(pool, tid, "TOKEN_A", 10, 0)
    assert n2 == 1
    async with pool.acquire() as conn:
        done2 = await conn.fetchval("SELECT schemes_done FROM unic_tasks WHERE id=$1", tid)
    assert done2 == 10

    # None токен (guard off) → апдейт всегда проходит
    n3 = await update_scheme_progress(pool, tid, None, 12, 0)
    assert n3 == 1
```

- [ ] **Step 2: Запустить — убедиться, что проходит** (реализация уже есть из 1.1)

Run: `cd /home/claude-user/unic-worker && DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_owner_guard.py::test_progress_update_blocked_on_owner_mismatch -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/unic-worker
git add tests/test_owner_guard.py
git commit -m "test(worker): owner-guard блокирует чужой progress-update (WP#222)"
```

### Task 1.3: гард на `mark_task_done` и `mark_task_error`

**Files:**
- Modify: `worker.py:128-148` (`mark_task_done`, `mark_task_error`)
- Test: `tests/test_owner_guard.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_owner_guard.py`:

```python
@pytest.mark.asyncio(loop_scope="session")
async def test_mark_done_blocked_on_owner_mismatch(pool, clean_unic_tasks, test_project_id):
    pid = test_project_id
    async with pool.acquire() as conn:
        tid = await _insert_processing(conn, pid, '{"owner_run_id": "TOKEN_A"}')

    # чужой токен → no-op, статус остаётся processing
    await mark_task_done(pool, tid, "TOKEN_B")
    async with pool.acquire() as conn:
        st = await conn.fetchval("SELECT current_status FROM unic_tasks WHERE id=$1", tid)
    assert st == 'processing'

    # свой токен → done
    await mark_task_done(pool, tid, "TOKEN_A")
    async with pool.acquire() as conn:
        st2 = await conn.fetchval("SELECT current_status FROM unic_tasks WHERE id=$1", tid)
    assert st2 == 'done'


@pytest.mark.asyncio(loop_scope="session")
async def test_mark_done_legacy_no_owner(pool, clean_unic_tasks, test_project_id):
    pid = test_project_id
    async with pool.acquire() as conn:
        tid = await _insert_processing(conn, pid, '{}')  # без owner_run_id
    # None токен → done проходит как раньше
    await mark_task_done(pool, tid, None)
    async with pool.acquire() as conn:
        st = await conn.fetchval("SELECT current_status FROM unic_tasks WHERE id=$1", tid)
    assert st == 'done'
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/unic-worker && DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_owner_guard.py::test_mark_done_blocked_on_owner_mismatch -v`
Expected: FAIL — `mark_task_done() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Реализовать гард**

Заменить `mark_task_done` (worker.py:128-130) на:

```python
async def mark_task_done(pool, task_id, owner_run_id=None):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE unic_tasks SET current_status='done', updated_at=NOW() "
            "WHERE id=$1 AND ($2::text IS NULL OR meta->>'owner_run_id' IS NOT DISTINCT FROM $2)",
            task_id, owner_run_id)
```

В `mark_task_error` (worker.py:132) добавить параметр `owner_run_id=None` в сигнатуру и owner-гард в оба `UPDATE`. Заменить тело на:

```python
async def mark_task_error(pool, task_id, msg, scheme_errors=None, owner_run_id=None):
    import json as _json
    _guard = " AND ($N::text IS NULL OR meta->>'owner_run_id' IS NOT DISTINCT FROM $N)"
    async with pool.acquire() as conn:
        if scheme_errors:
            row = await conn.fetchrow("SELECT meta FROM unic_tasks WHERE id=$1", task_id)
            raw_meta = row['meta'] if row and row['meta'] else {}
            if isinstance(raw_meta, str):
                raw_meta = _json.loads(raw_meta)
            meta = dict(raw_meta) if raw_meta else {}
            meta['scheme_errors'] = {str(k): str(v)[:300] for k, v in scheme_errors.items()}
            await conn.execute(
                "UPDATE unic_tasks SET current_status='error', error_message=$2, meta=$3::jsonb, updated_at=NOW() "
                "WHERE id=$1 AND ($4::text IS NULL OR meta->>'owner_run_id' IS NOT DISTINCT FROM $4)",
                task_id, msg[:1000], _json.dumps(meta), owner_run_id)
        else:
            await conn.execute(
                "UPDATE unic_tasks SET current_status='error', error_message=$2, updated_at=NOW() "
                "WHERE id=$1 AND ($3::text IS NULL OR meta->>'owner_run_id' IS NOT DISTINCT FROM $3)",
                task_id, msg[:1000], owner_run_id)
```

(Удалить временную `_guard`-строку — она оставлена как пояснение; в финальном коде её нет.)

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd /home/claude-user/unic-worker && DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_owner_guard.py -v`
Expected: PASS (все тесты модуля).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/unic-worker
git add worker.py tests/test_owner_guard.py
git commit -m "feat(worker): owner-guard на mark_task_done/mark_task_error (WP#222)"
```

### Task 1.4: захват таска штампует `owner_run_id`

**Files:**
- Modify: `worker.py:108-126` (`get_pending_task`, шаги 2-3)
- Test: `tests/test_owner_guard.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_owner_guard.py`:

```python
from worker import get_pending_task


@pytest.mark.asyncio(loop_scope="session")
async def test_pickup_stamps_owner_run_id(pool, clean_unic_tasks, test_project_id):
    pid = test_project_id
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, payload_hash, created_at, updated_at)
            VALUES
              ('scheme_preview', $1, 'pending', '[]'::text, 0,
               'http://t/s.mp4', 'test', $2, NOW(), NOW())
        """, pid, f'hash-pickup-{pid}')

    task = await get_pending_task(pool)
    assert task is not None and task['project_id'] == pid
    meta = task['meta']
    if isinstance(meta, str):
        meta = json.loads(meta)
    # при default-ON флаге pickup проштамповал owner_run_id
    assert meta.get('owner_run_id'), "owner_run_id не проштампован при захвате"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/unic-worker && DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_owner_guard.py::test_pickup_stamps_owner_run_id -v`
Expected: FAIL — `AssertionError: owner_run_id не проштампован при захвате` (meta пустой).

- [ ] **Step 3: Реализовать штамповку в `get_pending_task`**

Заменить шаг 3 (worker.py:120-126) на:

```python
            # Шаг 3: пометить как processing и (для scheme_preview при включённом
            # guard) проштамповать свежий owner_run_id в meta — защита от двойной
            # обработки (WP#222). owner_run_id живёт в meta jsonb, без схемной миграции.
            token = None
            if candidate['task_type'] == 'scheme_preview' and OWNER_GUARD_ENABLED:
                token = uuid.uuid4().hex
            row = await conn.fetchrow(
                "UPDATE unic_tasks SET current_status='processing', updated_at=NOW(), "
                "meta = CASE WHEN $2::text IS NULL THEN meta "
                "            ELSE COALESCE(meta, '{}'::jsonb) "
                "                 || jsonb_build_object('owner_run_id', $2::text) END "
                "WHERE id=$1 RETURNING *",
                candidate['id'], token,
            )
            return dict(row) if row else None
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd /home/claude-user/unic-worker && DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_owner_guard.py tests/test_per_project_guard.py -v`
Expected: PASS (новый тест + не сломан per-project guard).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/unic-worker
git add worker.py tests/test_owner_guard.py
git commit -m "feat(worker): захват scheme_preview-таска штампует owner_run_id (WP#222)"
```

### Task 1.5: подключить гард в `process_scheme_preview_task`

**Files:**
- Modify: `worker.py:656-824` (`process_scheme_preview_task`)

Это wiring-шаг: новых unit-тестов нет (полный pipeline тянет ffmpeg/S3 и в unit не гоняется), логика покрыта helper-тестами 1.1-1.4. Проверка — полный прогон существующего набора без регрессий.

- [ ] **Step 1: Извлечь `owner_run_id` из meta таска**

После парсинга `meta` (worker.py:661-663) добавить строку:

```python
        owner_run_id = meta.get('owner_run_id')
```

- [ ] **Step 2: Проверка владения в начале каждой итерации цикла**

В цикле `for i, scheme in enumerate(schemes):` (worker.py:715) первой строкой тела добавить:

```python
                if not await is_task_owner(pool, task_id, owner_run_id):
                    logger.warning(
                        f'[scheme_preview {task_id}] владение потеряно (другой воркер '
                        f'перехватил таск) — выходим, не дописывая прогресс'
                    )
                    break
```

- [ ] **Step 3: Заменить inline progress-UPDATE на гард-helper**

Заменить блок progress update (worker.py:797-803) на:

```python
                # progress update (owner-guard, WP#222)
                await update_scheme_progress(pool, task_id, owner_run_id, done_count, len(scheme_errors))
```

- [ ] **Step 4: Прокинуть `owner_run_id` в финализацию и ранние ошибки**

- worker.py:672 → `await mark_task_error(pool, task_id, 'sample_url missing in meta', owner_run_id=owner_run_id)`
- worker.py:681 → `await mark_task_error(pool, task_id, f'Failed to download sample from {sample_url[:80]}', owner_run_id=owner_run_id)`
- worker.py:806-810 (all-failed) → добавить `owner_run_id=owner_run_id` в вызов `mark_task_error`.
- worker.py:813-822 (partial-success UPDATE) → добавить owner-гард в `WHERE`:

```python
                async with pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE unic_tasks
                           SET current_status='done', updated_at=NOW(),
                               meta = COALESCE(meta, '{}'::jsonb) || jsonb_build_object(
                                 'scheme_errors',
                                 ($2::jsonb)
                               )
                         WHERE id=$1
                           AND ($3::text IS NULL OR meta->>'owner_run_id' IS NOT DISTINCT FROM $3)
                    """, task_id, json.dumps({str(k): v for k, v in scheme_errors.items()}), owner_run_id)
```

- worker.py:824 → `await mark_task_done(pool, task_id, owner_run_id)`

- [ ] **Step 5: Прогнать весь набор тестов воркера**

Run: `cd /home/claude-user/unic-worker && DATABASE_URL=postgresql://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest -v`
Expected: PASS (все модули: owner_guard, per_project_guard, watchdog, heartbeat, dispatch, payload_processing).

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/unic-worker
git add worker.py
git commit -m "feat(worker): подключить owner-guard в process_scheme_preview_task — выход при перехвате (WP#222)"
```

---

## Task 2: Бэкенд — идемпотентный прогресс (слой «б»)

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/backend/src/config.py:50` (добавить флаг)
- Modify: `/home/claude-user/validator-contenthunter/backend/src/services/scheme_preview_queue.py:155-212`
- Test: `/home/claude-user/validator-contenthunter/backend/tests/test_scheme_preview_queue.py`

### Task 2.1: config-флаг

- [ ] **Step 1: Добавить флаг в Settings**

В `config.py` после строки 50 (`max_upload_bytes = ...`) добавить:

```python

    # WP#222: прогресс scheme_preview = COUNT реально отрендеренных превью
    # (а не суммируемый schemes_done) — защита от «121%».
    scheme_preview_progress_from_count_enabled: bool = True
```

- [ ] **Step 2: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/config.py
git commit -m "feat(backend): флаг scheme_preview_progress_from_count_enabled (WP#222)"
```

### Task 2.2: прогресс из реального COUNT превью

- [ ] **Step 1: Написать падающий тест**

Добавить в `backend/tests/test_scheme_preview_queue.py`:

```python
@pytest_asyncio.fixture
async def clean_previews(clean_project):
    """Доп. очистка validator_scheme_previews для test pid (поверх clean_project)."""
    pid = clean_project
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "DELETE FROM validator_scheme_previews WHERE project_id=:pid"), {'pid': pid})
        await db.commit()
    yield pid
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "DELETE FROM validator_scheme_previews WHERE project_id=:pid"), {'pid': pid})
        await db.commit()


@pytest.mark.asyncio
async def test_progress_counts_real_previews_not_inflated_done(clean_previews):
    pid = clean_previews
    async with AsyncSessionLocal() as db:
        tid = (await db.execute(text("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total, schemes_done,
               schemes_error, input_video_url, project_name, payload_hash, created_at, updated_at)
            VALUES ('scheme_preview', :pid, 'processing', '[]'::text, 34, 64, 0,
               'http://t/s.mp4', 'test', :h, NOW(), NOW())
            RETURNING id
        """), {'pid': pid, 'h': f'h-prog-{pid}'})).scalar()
        # 5 реально отрендеренных превью этим таском
        for sid in range(1, 6):
            await db.execute(text("""
                INSERT INTO validator_scheme_previews
                  (scheme_id, project_id, thumb_url, video_url, last_task_id, generated_at)
                VALUES (:sid, :pid, NULL, 'http://t/v.mp4', :tid, NOW())
                ON CONFLICT (scheme_id, project_id) DO UPDATE SET last_task_id=EXCLUDED.last_task_id
            """), {'sid': sid, 'pid': pid, 'tid': tid})
        await db.commit()

    async with AsyncSessionLocal() as db:
        status = await read_scheme_preview_status(db, pid)

    assert status['total'] == 34
    assert status['progress'] == 5  # COUNT превью, НЕ раздутый schemes_done=64
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && DATABASE_URL=postgresql+asyncpg://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_scheme_preview_queue.py::test_progress_counts_real_previews_not_inflated_done -v`
Expected: FAIL — `assert 64 == 5`.

- [ ] **Step 3: Реализовать COUNT-based progress**

В `scheme_preview_queue.py` в начало файла добавить импорт настроек (после строки 10):

```python
from ..config import settings
```

В `read_scheme_preview_status`, перед блоком `return` (после строки 202), вычислить `progress`:

```python
    progress = int(row['done'])
    if settings.scheme_preview_progress_from_count_enabled:
        cnt = (await db.execute(text("""
            SELECT COUNT(*) FROM validator_scheme_previews
             WHERE project_id = :pid AND last_task_id = :tid
        """), {'pid': project_id, 'tid': int(row['id'])})).scalar()
        progress = int(cnt or 0)
```

В словаре `return` заменить `'progress': int(row['done']),` на `'progress': progress,`.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/validator-contenthunter/backend && DATABASE_URL=postgresql+asyncpg://openclaw:openclaw123@172.17.0.3:5432/openclaw python -m pytest tests/test_scheme_preview_queue.py -v`
Expected: PASS (новый тест + существующие enqueue/dedup/supersede).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/services/scheme_preview_queue.py backend/tests/test_scheme_preview_queue.py
git commit -m "feat(backend): прогресс scheme_preview из COUNT превью, не из schemes_done (WP#222)"
```

---

## Task 3: Фронт — зажим отображения ≤100% (слой «в»)

**Files:**
- Create: `/home/claude-user/validator-contenthunter/frontend/src/utils/progress.ts`
- Create: `/home/claude-user/validator-contenthunter/frontend/src/utils/__tests__/progress.spec.ts`
- Modify: `/home/claude-user/validator-contenthunter/frontend/src/pages/client/SchemesPage.vue:182,369`

### Task 3.1: чистые helper-функции + тест

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/utils/__tests__/progress.spec.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { clampProgress, clampPercent } from '../progress'

describe('progress clamp (WP#222)', () => {
  it('зажимает процент на 100 при progress > total', () => {
    expect(clampPercent(41, 34)).toBe(100)
    expect(clampPercent(64, 34)).toBe(100)
  })
  it('зажимает числитель на total', () => {
    expect(clampProgress(41, 34)).toBe(34)
  })
  it('нормальный случай не затрагивается', () => {
    expect(clampPercent(17, 34)).toBe(50)
    expect(clampProgress(17, 34)).toBe(17)
  })
  it('total=0 → 0%', () => {
    expect(clampPercent(5, 0)).toBe(0)
    expect(clampProgress(5, 0)).toBe(5)
  })
})
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vitest run src/utils/__tests__/progress.spec.ts`
Expected: FAIL — не может зарезолвить `../progress`.

- [ ] **Step 3: Реализовать `progress.ts`**

Создать `frontend/src/utils/progress.ts`:

```typescript
// WP#222: зажим отображения прогресса генерации превью — бар не врёт даже при
// некорректных данных из БД (последний рубеж поверх backend-фикса).
export function clampProgress(progress: number, total: number): number {
  if (!total || total <= 0) return Math.max(0, progress)
  return Math.min(progress, total)
}

export function clampPercent(progress: number, total: number): number {
  if (!total || total <= 0) return 0
  return Math.min(100, Math.round((progress / total) * 100))
}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vitest run src/utils/__tests__/progress.spec.ts`
Expected: PASS (4 теста).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/utils/progress.ts frontend/src/utils/__tests__/progress.spec.ts
git commit -m "feat(frontend): чистые clampProgress/clampPercent + тесты (WP#222)"
```

### Task 3.2: подключить зажим в `SchemesPage.vue`

- [ ] **Step 1: Импортировать helpers**

В `SchemesPage.vue` в блок импортов (рядом со строкой 282, `import api from '@/api/client'`) добавить:

```typescript
import { clampProgress, clampPercent } from '@/utils/progress'
```

- [ ] **Step 2: Переписать `genPercent` через `clampPercent`**

Заменить строку 369:

```typescript
const genPercent = computed(() => genTotal.value ? Math.round(genProgress.value / genTotal.value * 100) : 0)
```

на:

```typescript
const genPercent = computed(() => clampPercent(genProgress.value, genTotal.value))
```

- [ ] **Step 3: Зажать числитель в шаблоне**

Заменить строку 182:

```html
            <span>{{ genProgress }} / {{ genTotal }}</span>
```

на:

```html
            <span>{{ clampProgress(genProgress, genTotal) }} / {{ genTotal }}</span>
```

(`clampProgress` доступна в шаблоне как импортированная функция в `<script setup>`.)

- [ ] **Step 4: Сборка-проверка типов**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | head -20 || npm run build 2>&1 | tail -20`
Expected: без новых ошибок типов по `SchemesPage.vue`/`progress.ts`.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/pages/client/SchemesPage.vue
git commit -m "feat(frontend): зажать прогресс-бар генерации превью ≤100% (WP#222)"
```

---

## Task 4: Бэкфилл текущих залипших строк (разово, при деплое)

**Files:**
- Create: `/home/claude-user/ch-wp222/docs/superpowers/plans/wp222_backfill.sql`

- [ ] **Step 1: Написать SQL-бэкфилл**

Создать `docs/superpowers/plans/wp222_backfill.sql` (в worktree `ch-wp222`):

```sql
-- WP#222: разовый бэкфилл уже залипших scheme_preview-строк, где счётчик
-- перевалил за total (косметика истории; строки уже done, на новые генерации
-- не влияют). Запускать на openclaw PG.
UPDATE unic_tasks
   SET schemes_done = LEAST(schemes_done, schemes_total),
       updated_at = NOW()
 WHERE task_type = 'scheme_preview'
   AND schemes_done > schemes_total;
```

- [ ] **Step 2: Прогнать (dry-run SELECT перед UPDATE)**

Run:
```bash
PGPASSWORD=openclaw123 psql -h 172.17.0.3 -p 5432 -U openclaw -d openclaw \
  -c "SELECT id, project_id, schemes_total, schemes_done FROM unic_tasks WHERE task_type='scheme_preview' AND schemes_done > schemes_total ORDER BY id DESC;"
```
Expected: список залипших (ожидаем 3976/117, 3955/103 и т.п.). Затем выполнить файл:
```bash
PGPASSWORD=openclaw123 psql -h 172.17.0.3 -p 5432 -U openclaw -d openclaw -f docs/superpowers/plans/wp222_backfill.sql
```
Expected: `UPDATE N` (N = число залипших строк), после — повторный SELECT возвращает 0 строк.

- [ ] **Step 3: Commit SQL**

```bash
cd /home/claude-user/ch-wp222
git add docs/superpowers/plans/wp222_backfill.sql
git commit -m "chore(wp222): разовый бэкфилл залипших scheme_preview-строк"
```

---

## Деплой (после мерджа, выполняет Данил где нужен sudo/SSH)

1. **unic-worker** → хост `91.98.180.103`: `git pull` + рестарт воркера. Env: добавить `SCHEME_PREVIEW_OWNER_GUARD_ENABLED=1` (или опустить — default ON). **SSH-ключей агента туда нет → за Данилом.**
2. **validator backend** → `/root/.openclaw/workspace-genri/validator`: `git pull` (агент, без sudo) + `sudo pm2 restart 24`. Env: `SCHEME_PREVIEW_PROGRESS_FROM_COUNT_ENABLED=1` (default ON).
3. **validator frontend** → `cd frontend && npm run build` → postbuild `cp` в `/var/www/validator`.
4. **Бэкфилл** → Task 4 SQL разово на openclaw PG.
5. **OpenProject** WP#222 → «Тестирование». Verify по следующей генерации: прогресс доходит до `N/N` = 100% и завершается; в БД `schemes_done ≤ schemes_total`; новых строк с `schemes_done > schemes_total` не появляется.

---

## Self-Review (выполнено при написании)

- **Покрытие спеки:** слой (а) → Task 1; слой (б) → Task 2; слой (в) → Task 3; бэкфилл → Task 4; kill-switch'и → 1.1 (`SCHEME_PREVIEW_OWNER_GUARD_ENABLED`) и 2.1 (`scheme_preview_progress_from_count_enabled`); деплой → секция «Деплой». Все требования спеки имеют задачу.
- **Плейсхолдеры:** нет TBD/TODO; весь код приведён целиком. (`_guard`-пояснение в 1.3 явно помечено как удаляемое.)
- **Согласованность типов/имён:** `is_task_owner`, `update_scheme_progress`, `clampProgress`, `clampPercent`, `owner_run_id`, флаги — одинаковы во всех задачах и в спеке. Сигнатуры `mark_task_done(pool, task_id, owner_run_id=None)` / `mark_task_error(..., owner_run_id=None)` совпадают между Task 1.3 и Task 1.5.
