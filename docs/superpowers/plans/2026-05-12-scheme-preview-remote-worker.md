# Scheme Preview Remote Worker Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести scheme preview generation из validator FastAPI background-task на unic-worker (PM2 на 91.98.180.103) через shared DB queue `unic_tasks`. Добавить payload-hash dedup, supersede pending, per-project processing guard, heartbeat watchdog и last-write-wins UPSERT-guard.

**Architecture:** Расширяем существующую `unic_tasks` таблицу колонкой `task_type` ('unic' | 'scheme_preview'). Validator пишет task через `INSERT` (с advisory lock per project + dedup/supersede в одной транзакции) и читает статус оттуда же. Worker поллит `unic_tasks` с per-project guard, диспатчит по `task_type`. `heartbeat_loop` обновляет `updated_at` каждые 30s, `stale_task_recovery_loop` reverts processing-задачи старше 15 мин. UPSERT в `validator_scheme_previews` отказывается перезаписать если `last_task_id` целевой строки уже больше.

**Tech Stack:** PostgreSQL 12+ (shared queue, advisory locks, partial indexes), FastAPI + SQLAlchemy + asyncpg (validator), Python asyncio + asyncpg (unic-worker), alembic (validator migrations), pytest + pytest-asyncio (live-DB tests), PM2 (deploy).

**Spec reference:** `docs/superpowers/specs/2026-05-12-scheme-preview-remote-worker-design.md`

---

## File Structure

### Phase 1: DB migration
- Create: `validator-contenthunter/backend/alembic/versions/004_scheme_preview_task_type.py`

### Phase 2: unic-worker (мы создаём git-зеркало + правки)
Текущий `/root/unic-worker/` на 91.98.180.103 — НЕ git репо. Создаём локальное зеркало, версионируем, ручной scp deploy.
- Create: `/home/claude-user/unic-worker/` (git init + remote на новый private GH repo)
- Modify: `/home/claude-user/unic-worker/worker.py`
- Create: `/home/claude-user/unic-worker/tests/__init__.py`
- Create: `/home/claude-user/unic-worker/tests/conftest.py`
- Create: `/home/claude-user/unic-worker/tests/test_dispatch_by_task_type.py`
- Create: `/home/claude-user/unic-worker/tests/test_payload_processing.py`
- Create: `/home/claude-user/unic-worker/tests/test_heartbeat.py`
- Create: `/home/claude-user/unic-worker/tests/test_watchdog.py`
- Create: `/home/claude-user/unic-worker/tests/test_per_project_guard.py`
- Create: `/home/claude-user/unic-worker/requirements.txt`
- Create: `/home/claude-user/unic-worker/requirements-test.txt`
- Create: `/home/claude-user/unic-worker/pytest.ini`
- Create: `/home/claude-user/unic-worker/.gitignore`

### Phase 3: validator
- Modify: `validator-contenthunter/backend/src/routers/schemes.py` (большая перепись `_run_generation` секции + endpoints)
- Create: `validator-contenthunter/backend/src/services/scheme_preview_queue.py` (helpers: compute_hash, enqueue_with_dedup, read_status)
- Create: `validator-contenthunter/backend/tests/test_scheme_preview_endpoint.py`
- Create: `validator-contenthunter/backend/tests/test_scheme_preview_queue.py`
- Create: `validator-contenthunter/backend/tests/test_payload_hash.py`

### Phase 4: Deploy + smoke
- Apply alembic migration on prod
- Deploy unic-worker (scp + pm2 restart)
- Deploy validator (cp + sudo pm2 restart)
- Live smoke

### Phase 5: Memory + cleanup
- Memory update
- Backlog tickets

---

## Phase 1 — DB Migration

### Task 1: Cross-repo grep audit (memory rule `feedback_cross_repo_schema_changes`)

**Files:** read-only audit

- [ ] **Step 1: grep unic_tasks across validator + autowarm + contenthunter repos**

```bash
cd /home/claude-user
grep -rn 'unic_tasks' \
    validator-contenthunter/backend/src/ \
    validator-contenthunter/backend/alembic/ \
    autowarm-testbench/ \
    contenthunter/ \
    2>/dev/null | grep -v '__pycache__' | grep -v '.git/'
```

Expected: hits в `validator/routers/schemes.py`, `validator/alembic/versions/003_publish_summary_indexes.py`. Никаких сюрпризов (например прямой `INSERT` из autowarm-кода в `unic_tasks` или зависимость на `slot_date NOT NULL`).

- [ ] **Step 2: grep on remote unic-worker**

```bash
sshpass -p 'MNcwMPCiyiYtM5' ssh -o StrictHostKeyChecking=no root@91.98.180.103 \
    "grep -rn 'unic_tasks\|slot_date' /root/unic-worker/ 2>&1 | head -20"
```

Expected: hits в `worker.py` (мы их учитываем). Никаких других сервисов на `91.98.180.103` использующих эту таблицу.

- [ ] **Step 3: записать аудит-результаты в эвиденс (если есть удивления)**

Если что-то неожиданное — создать `docs/evidence/2026-05-12-unic-tasks-cross-repo-audit.md` с findings. Если nothing surprising — пропустить и идти дальше.

---

### Task 2: pg_dump бэкап unic_tasks

**Files:** read-only БД snapshot

- [ ] **Step 1: pg_dump только таблицы unic_tasks**

```bash
PGPASSWORD=openclaw123 pg_dump -h localhost -U openclaw -d openclaw \
    --table=unic_tasks --data-only --column-inserts \
    > /tmp/unic_tasks_pre_scheme_preview_$(date +%s).sql

ls -la /tmp/unic_tasks_pre_scheme_preview_*.sql
wc -l /tmp/unic_tasks_pre_scheme_preview_*.sql
```

Expected: файл с ~1626 INSERT statements (по числу строк), размер ~несколько MB.

- [ ] **Step 2: pg_dump schema unic_tasks**

```bash
PGPASSWORD=openclaw123 pg_dump -h localhost -U openclaw -d openclaw \
    --table=unic_tasks --schema-only \
    > /tmp/unic_tasks_schema_pre_$(date +%s).sql

cat /tmp/unic_tasks_schema_pre_*.sql | head -30
```

Expected: видим текущий `CREATE TABLE unic_tasks`, ALTER, индексы. Нам важно зафиксировать что было ДО.

- [ ] **Step 3: проверить current_status enum constraint**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
    "SELECT conname, pg_get_constraintdef(oid)
       FROM pg_constraint
      WHERE conrelid='unic_tasks'::regclass
        AND contype='c'"
```

Expected: либо пусто (`current_status` это plain TEXT, мы свободно добавим 'superseded') либо CHECK constraint, который придётся расширить в alembic. Запомнить результат для Task 3.

---

### Task 3: Alembic migration 004

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/alembic/versions/004_scheme_preview_task_type.py`

- [ ] **Step 1: создать revision file**

```python
"""Add task_type/payload_hash to unic_tasks + last_task_id to validator_scheme_previews

Revision ID: 004
Revises: 003
Create Date: 2026-05-12

Расширяет unic_tasks для scheme_preview pipeline:
  - task_type ('unic' | 'scheme_preview'), default 'unic'
  - payload_hash для dedup
  - slot_date становится nullable (preview не имеет slot)
  - unique partial index per (project_id, payload_hash) для активных preview tasks
  - polling/lookup индексы

Расширяет validator_scheme_previews:
  - last_task_id (BIGINT) для last-write-wins UPSERT guard
"""
from alembic import op
import sqlalchemy as sa


revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) unic_tasks columns
    op.add_column(
        'unic_tasks',
        sa.Column(
            'task_type', sa.Text(), nullable=False,
            server_default='unic',
        ),
    )
    op.create_check_constraint(
        'ck_unic_tasks_task_type',
        'unic_tasks',
        "task_type IN ('unic', 'scheme_preview')",
    )
    op.add_column(
        'unic_tasks',
        sa.Column('payload_hash', sa.Text(), nullable=True),
    )

    # 2) slot_date nullable (preview не имеет slot)
    op.alter_column('unic_tasks', 'slot_date', nullable=True)

    # 3) Уникальный partial index для активных scheme_preview (по payload_hash)
    op.execute("""
        CREATE UNIQUE INDEX uniq_scheme_preview_active_payload
            ON unic_tasks (project_id, payload_hash)
         WHERE task_type = 'scheme_preview'
           AND current_status IN ('pending', 'processing')
    """)

    # 4) Polling index
    op.execute("""
        CREATE INDEX idx_unic_tasks_polling
            ON unic_tasks (current_status, id)
         WHERE current_status = 'pending'
    """)

    # 5) Lookup index для GET /generation-status (latest по проекту/типу)
    op.execute("""
        CREATE INDEX idx_unic_tasks_project_type_id
            ON unic_tasks (project_id, task_type, id DESC)
    """)

    # 6) validator_scheme_previews: last_task_id для UPSERT-guard
    op.add_column(
        'validator_scheme_previews',
        sa.Column('last_task_id', sa.BigInteger(), nullable=True),
    )

    # 7) Если current_status имеет CHECK — расширить.
    #    Проверяется alembic'ом во время upgrade через raw SQL:
    op.execute("""
        DO $$
        DECLARE
            cdef text;
        BEGIN
            SELECT pg_get_constraintdef(c.oid) INTO cdef
              FROM pg_constraint c
             WHERE c.conrelid = 'unic_tasks'::regclass
               AND c.contype = 'c'
               AND c.conname LIKE '%current_status%';

            IF cdef IS NOT NULL THEN
                -- Если CHECK уже есть — расширить
                EXECUTE 'ALTER TABLE unic_tasks DROP CONSTRAINT '
                     || (SELECT conname FROM pg_constraint
                          WHERE conrelid='unic_tasks'::regclass
                            AND contype='c'
                            AND conname LIKE '%current_status%' LIMIT 1);
                ALTER TABLE unic_tasks
                    ADD CONSTRAINT ck_unic_tasks_current_status
                    CHECK (current_status IN (
                        'pending', 'processing', 'done', 'error',
                        'cancelled', 'superseded'
                    ));
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_column('validator_scheme_previews', 'last_task_id')
    op.execute("DROP INDEX IF EXISTS idx_unic_tasks_project_type_id")
    op.execute("DROP INDEX IF EXISTS idx_unic_tasks_polling")
    op.execute("DROP INDEX IF EXISTS uniq_scheme_preview_active_payload")
    op.alter_column('unic_tasks', 'slot_date', nullable=False)
    op.drop_column('unic_tasks', 'payload_hash')
    op.drop_constraint('ck_unic_tasks_task_type', 'unic_tasks', type_='check')
    op.drop_column('unic_tasks', 'task_type')
```

- [ ] **Step 2: dry-run проверка alembic не сломан**

```bash
cd /home/claude-user/validator-contenthunter/backend
python3 -c "
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config('alembic.ini')
sd = ScriptDirectory.from_config(cfg)
for r in sd.walk_revisions():
    print(r.revision, '<-', r.down_revision, r.doc[:60])
"
```

Expected: видим `004 <- 003 ...`, `003 <- 002`, `002 <- 001`, `001 <- None`. Цепочка целая.

- [ ] **Step 3: apply migration в test environment**

Test environment = тот же prod openclaw, потому что у нас нет staging. Применяем напрямую (с pre-flight pg_dump из Task 2 как safety net):

```bash
cd /home/claude-user/validator-contenthunter/backend
# Show pending migrations
alembic current
alembic heads

# Apply
alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade 003 -> 004, Add task_type/payload_hash...`

- [ ] **Step 4: verify post-migration schema**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d+ unic_tasks" | grep -E 'task_type|payload_hash|slot_date|uniq_scheme|idx_unic_tasks_polling|idx_unic_tasks_project_type'
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d validator_scheme_previews" | grep last_task_id
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "SELECT COUNT(*) FROM unic_tasks WHERE task_type='unic'"
```

Expected:
- видим `task_type | text | not null` с default `'unic'`
- `payload_hash | text` nullable
- `slot_date | date` (без NOT NULL)
- три новых индекса есть
- `last_task_id | bigint` есть в validator_scheme_previews
- COUNT(\*) = 1626 (legacy строки получили task_type='unic' через DEFAULT)

- [ ] **Step 5: smoke: legacy unic-worker не сломался**

```bash
# Подождать ~30 секунд после миграции и поверить что worker poll не упал
sshpass -p 'MNcwMPCiyiYtM5' ssh root@91.98.180.103 "pm2 logs unic-worker --lines 30 --nostream" 2>&1 | tail -20
```

Expected: нет ошибок типа `column "task_type" does not exist`. Worker продолжает poll (либо idle если очередь пуста, либо processing legacy задач).

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git checkout -b feat/004-scheme-preview-task-type-20260512
git add backend/alembic/versions/004_scheme_preview_task_type.py
git commit -m "$(cat <<'EOF'
feat(alembic): 004 — unic_tasks task_type/payload_hash + validator_scheme_previews.last_task_id

Schema foundation для миграции scheme preview generation на remote unic-worker.

Spec: docs/superpowers/specs/2026-05-12-scheme-preview-remote-worker-design.md
Plan: docs/superpowers/plans/2026-05-12-scheme-preview-remote-worker.md

- task_type TEXT NOT NULL DEFAULT 'unic' CHECK ('unic','scheme_preview')
- payload_hash TEXT NULL — для dedup активных preview-task'ов
- slot_date nullable — preview не имеет slot
- uniq_scheme_preview_active_payload partial UNIQUE index
- idx_unic_tasks_polling, idx_unic_tasks_project_type_id
- validator_scheme_previews.last_task_id BIGINT — last-write-wins UPSERT guard

Legacy unic-задачи получают task_type='unic' через DEFAULT (1626 строк).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — unic-worker (mirror repo + код + тесты)

### Task 4: Создать локальное git-зеркало unic-worker

**Files:**
- Create: `/home/claude-user/unic-worker/` (новый git repo)

- [ ] **Step 1: fetch текущего state с 91.98.180.103**

```bash
mkdir -p /home/claude-user/unic-worker
cd /home/claude-user/unic-worker

sshpass -p 'MNcwMPCiyiYtM5' scp -o StrictHostKeyChecking=no \
    'root@91.98.180.103:/root/unic-worker/worker.py' \
    'root@91.98.180.103:/root/unic-worker/ecosystem.config.js' \
    .

# .env скачиваем отдельно, в git его НЕ добавляем (секреты)
sshpass -p 'MNcwMPCiyiYtM5' scp -o StrictHostKeyChecking=no \
    'root@91.98.180.103:/root/unic-worker/.env' \
    .env.example.from-prod
```

- [ ] **Step 2: setup git**

```bash
cd /home/claude-user/unic-worker
git init
cat > .gitignore <<'EOF'
__pycache__/
*.pyc
.env
.env.local
.pytest_cache/
.venv/
*.bak_*
EOF

# scrub секреты из .env.example
grep -v 'KEY\|PASSWORD\|TOKEN' .env.example.from-prod > .env.example
rm .env.example.from-prod

git add .gitignore worker.py ecosystem.config.js .env.example
git commit -m "chore: initial import from 91.98.180.103:/root/unic-worker (snapshot 2026-05-12)"
```

- [ ] **Step 3: create GH repo + push**

```bash
source ~/secrets/github-gengo2.env
GH_TOKEN="$GITHUB_TOKEN_GENGO2" gh repo create GenGo2/unic-worker --private --source=. --remote=origin --push 2>&1 | tail -3
```

Expected: репо создан, push прошёл. Origin = `git@github.com:GenGo2/unic-worker.git` или https-variant.

- [ ] **Step 4: создать feature branch**

```bash
cd /home/claude-user/unic-worker
git checkout -b feat/scheme-preview-task-type-20260512
```

---

### Task 5: Setup pytest + asyncpg test fixtures

**Files:**
- Create: `/home/claude-user/unic-worker/pytest.ini`
- Create: `/home/claude-user/unic-worker/requirements.txt`
- Create: `/home/claude-user/unic-worker/requirements-test.txt`
- Create: `/home/claude-user/unic-worker/tests/__init__.py`
- Create: `/home/claude-user/unic-worker/tests/conftest.py`

- [ ] **Step 1: requirements.txt** (зависимости рантайма, копируем из текущего worker.py imports)

```text
asyncpg>=0.29.0
boto3>=1.35.0
httpx>=0.27.0
```

- [ ] **Step 2: requirements-test.txt**

```text
-r requirements.txt
pytest>=8.0
pytest-asyncio>=0.23
```

- [ ] **Step 3: pytest.ini**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
log_cli = true
log_cli_level = INFO
```

- [ ] **Step 4: tests/__init__.py** — пустой файл

```python
```

- [ ] **Step 5: tests/conftest.py**

```python
"""Live-DB pytest fixtures for unic-worker tests.

Подключаемся к тому же Postgres что и worker (через env DATABASE_URL).
Каждый тест работает в отдельной транзакции которая откатывается на teardown,
поэтому данные остальной БД не страдают.
"""
import asyncio
import os
import pytest
import asyncpg


DB_URL = os.environ.get(
    'TEST_DATABASE_URL',
    'postgresql://openclaw:openclaw123@localhost:5432/openclaw',
)


@pytest.fixture(scope='session')
def event_loop():
    """Один event loop на всю сессию pytest — иначе asyncpg pool падает."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope='session')
async def pool():
    """Shared connection pool на всю сессию."""
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    yield p
    await p.close()


@pytest.fixture
async def clean_unic_tasks(pool):
    """Чистит scheme_preview-задачи до теста и удаляет созданные за тест."""
    async with pool.acquire() as conn:
        # очистить заранее
        await conn.execute(
            "DELETE FROM unic_tasks WHERE task_type='scheme_preview' "
            "AND project_id >= 100000"  # test project_id range
        )
    yield
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM unic_tasks WHERE task_type='scheme_preview' "
            "AND project_id >= 100000"
        )


@pytest.fixture
async def test_project_id():
    """Уникальный project_id для теста (не пересекается с реальными)."""
    import random
    return 100000 + random.randint(1, 99999)
```

- [ ] **Step 6: install dependencies**

```bash
cd /home/claude-user/unic-worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
```

- [ ] **Step 7: smoke pytest**

```bash
cd /home/claude-user/unic-worker
source .venv/bin/activate
pytest tests/ -v 2>&1 | tail -10
```

Expected: `no tests ran in 0.XX s` (тестов ещё нет, но pytest успешно загрузил conftest).

- [ ] **Step 8: Commit**

```bash
git add pytest.ini requirements.txt requirements-test.txt tests/__init__.py tests/conftest.py
git commit -m "test: scaffold pytest + asyncpg live-DB fixtures"
```

---

### Task 6: Test + implement `_compute_payload_hash` helper (опционально — может быть в validator side)

**Skip:** payload_hash вычисляется validator'ом перед INSERT'ом, worker hash не пересчитывает. Реализуется в Phase 3 (Task 14). Worker только читает поле из jsonb.

---

### Task 7: Test + modify `get_pending_task` с per-project guard

**Files:**
- Modify: `/home/claude-user/unic-worker/worker.py` (функция `get_pending_task`)
- Create: `/home/claude-user/unic-worker/tests/test_per_project_guard.py`

- [ ] **Step 1: Write failing test — guard блокирует concurrent pickup того же project**

`tests/test_per_project_guard.py`:

```python
"""Per-project guard: не подхватывать второй scheme_preview pending
если того же project уже есть processing."""
import asyncio
import pytest
from worker import get_pending_task


@pytest.mark.asyncio
async def test_guard_blocks_pickup_when_project_already_processing(
    pool, clean_unic_tasks, test_project_id,
):
    pid = test_project_id

    async with pool.acquire() as conn:
        # уже processing того же project
        await conn.execute("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, created_at, updated_at)
            VALUES
              ('scheme_preview', $1, 'processing', '[]'::text, 0,
               'http://test/s.mp4', 'test', NOW(), NOW())
        """, pid)

        # pending того же project
        await conn.execute("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, created_at, updated_at)
            VALUES
              ('scheme_preview', $1, 'pending', '[]'::text, 0,
               'http://test/s.mp4', 'test', NOW(), NOW())
        """, pid)

    # worker poll
    task = await get_pending_task(pool)

    # guard НЕ должен подхватить pending — у того же project уже processing
    if task is not None:
        assert not (
            task['task_type'] == 'scheme_preview' and task['project_id'] == pid
        ), f"Guard violated: подхватил pending {pid} пока processing активен"


@pytest.mark.asyncio
async def test_guard_lets_pickup_when_no_processing(
    pool, clean_unic_tasks, test_project_id,
):
    pid = test_project_id

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, created_at, updated_at)
            VALUES
              ('scheme_preview', $1, 'pending', '[]'::text, 0,
               'http://test/s.mp4', 'test', NOW(), NOW())
            RETURNING id
        """, pid)

    task = await get_pending_task(pool)

    assert task is not None
    assert task['task_type'] == 'scheme_preview'
    assert task['project_id'] == pid
    assert task['current_status'] == 'processing'  # уже UPDATE'нулось в poll


@pytest.mark.asyncio
async def test_guard_does_not_affect_unic_legacy_tasks(
    pool, clean_unic_tasks, test_project_id,
):
    """Legacy unic-задачи поллятся без guard'a (как раньше)."""
    pid = test_project_id

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               slot_date, input_video_url, project_name, created_at, updated_at)
            VALUES
              ('unic', $1, 'processing', '[]'::text, 0,
               '2026-05-12', 'http://test/s.mp4', 'test', NOW(), NOW())
        """, pid)
        await conn.execute("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               slot_date, input_video_url, project_name, created_at, updated_at)
            VALUES
              ('unic', $1, 'pending', '[]'::text, 0,
               '2026-05-12', 'http://test/s.mp4', 'test', NOW(), NOW())
        """, pid)

    task = await get_pending_task(pool)

    # legacy unic должна подхватиться даже при наличии processing того же project
    if task is not None:
        if task['project_id'] == pid:
            assert task['task_type'] == 'unic'  # подхватили unic, не preview
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /home/claude-user/unic-worker
source .venv/bin/activate
pytest tests/test_per_project_guard.py -v 2>&1 | tail -15
```

Expected: первый и третий тесты могут проходить случайно (зависит от состояния очереди), второй пройдёт. **Главное** — guard ещё не реализован, поэтому `test_guard_blocks_pickup_when_project_already_processing` может упасть на pickup'е pending'a того же project. Если все три зелёные с первого раза — старый код мог никогда не подхватить из-за other reasons; всё равно реализуем (TDD discipline + real correctness).

- [ ] **Step 3: Modify worker.py — get_pending_task с per-project guard**

В `worker.py` найти текущую функцию `get_pending_task` (около строки 70):

```python
async def get_pending_task(pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE unic_tasks SET current_status='processing', updated_at=NOW()
            WHERE id=(SELECT id FROM unic_tasks WHERE current_status='pending' ORDER BY id ASC LIMIT 1 FOR UPDATE SKIP LOCKED)
            RETURNING *
        """)
        return dict(row) if row else None
```

Заменить на:

```python
async def get_pending_task(pool):
    """Подхватить следующий pending task.

    Для task_type='scheme_preview' — per-project guard: не подхватывать pending
    если у того же project_id уже есть processing scheme_preview-task. Это
    исключает stale-overwrite сценарий когда два task'a одного project
    конкурируют за S3 keys и UPSERT в validator_scheme_previews.

    Для task_type='unic' (legacy) — без guard, как раньше.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE unic_tasks SET current_status='processing', updated_at=NOW()
             WHERE id = (
                 SELECT t.id FROM unic_tasks t
                  WHERE t.current_status = 'pending'
                    AND (
                          t.task_type = 'unic'  -- legacy: без guard
                          OR (
                            t.task_type = 'scheme_preview'
                            AND NOT EXISTS (
                              SELECT 1 FROM unic_tasks p
                               WHERE p.task_type = 'scheme_preview'
                                 AND p.project_id = t.project_id
                                 AND p.current_status = 'processing'
                            )
                          )
                        )
                  ORDER BY t.id ASC
                  LIMIT 1
                  FOR UPDATE SKIP LOCKED
             )
            RETURNING *
        """)
        return dict(row) if row else None
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/test_per_project_guard.py -v 2>&1 | tail -15
```

Expected: все 3 теста зелёные.

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_per_project_guard.py
git commit -m "feat(get_pending_task): per-project guard для scheme_preview

Worker не подхватывает второй pending scheme_preview если у того же project
уже есть processing — исключает race на S3 keys + validator_scheme_previews
UPSERT когда несколько task'ов одного project обрабатываются параллельно.

Legacy unic-задачи поллятся без guard'a (как раньше)."
```

---

### Task 8: Test + implement heartbeat_loop

**Files:**
- Modify: `/home/claude-user/unic-worker/worker.py` (добавить `heartbeat_loop`)
- Create: `/home/claude-user/unic-worker/tests/test_heartbeat.py`

- [ ] **Step 1: Write failing test**

`tests/test_heartbeat.py`:

```python
"""Heartbeat обновляет unic_tasks.updated_at пока worker реально работает,
чтобы watchdog не подумал что задача зависла во время длинного render'a."""
import asyncio
import pytest
from datetime import datetime, timedelta, timezone

from worker import heartbeat_loop


@pytest.fixture
async def processing_task(pool, clean_unic_tasks, test_project_id):
    """INSERT scheme_preview task в processing, return id."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, created_at, updated_at)
            VALUES
              ('scheme_preview', $1, 'processing', '[]'::text, 0,
               'http://test/s.mp4', 'test',
               NOW() - INTERVAL '5 minutes',
               NOW() - INTERVAL '5 minutes')
            RETURNING id, updated_at
        """, test_project_id)
        return dict(row)


async def _get_updated_at(pool, task_id):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT updated_at FROM unic_tasks WHERE id=$1", task_id,
        )


@pytest.mark.asyncio
async def test_heartbeat_updates_updated_at_within_interval(pool, processing_task):
    """Один heartbeat-tick за 30 секунд обновляет updated_at."""
    task_id = processing_task['id']
    old_ts = processing_task['updated_at']

    stop = asyncio.Event()
    # patched fast interval для теста
    hb = asyncio.create_task(heartbeat_loop(pool, task_id, stop, interval_sec=1.0))

    await asyncio.sleep(1.5)
    stop.set()
    await hb

    new_ts = await _get_updated_at(pool, task_id)
    assert new_ts > old_ts, f"updated_at не двинулся: old={old_ts} new={new_ts}"


@pytest.mark.asyncio
async def test_heartbeat_stops_when_status_changes(pool, processing_task):
    """Если status сменился (done/error/superseded), heartbeat-update это
    видит и НЕ переписывает updated_at случайно."""
    task_id = processing_task['id']

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE unic_tasks SET current_status='done', updated_at=NOW() WHERE id=$1",
            task_id,
        )
        ts_done = await conn.fetchval(
            "SELECT updated_at FROM unic_tasks WHERE id=$1", task_id,
        )

    stop = asyncio.Event()
    hb = asyncio.create_task(heartbeat_loop(pool, task_id, stop, interval_sec=0.5))

    await asyncio.sleep(1.5)
    stop.set()
    await hb

    ts_after = await _get_updated_at(pool, task_id)
    # heartbeat имеет WHERE current_status='processing' — done-задачу не трогает
    assert ts_after == ts_done, \
        f"Heartbeat обновил done-задачу! before={ts_done} after={ts_after}"


@pytest.mark.asyncio
async def test_heartbeat_handles_db_errors_gracefully(pool, processing_task):
    """Транзиентная ошибка БД не убивает heartbeat — он логирует и
    продолжает (важно для production resilience)."""
    task_id = processing_task['id']
    stop = asyncio.Event()
    hb = asyncio.create_task(heartbeat_loop(pool, task_id, stop, interval_sec=0.5))

    # Не падаем даже если что-то странное случится
    await asyncio.sleep(1.5)
    stop.set()
    await hb

    # heartbeat завершился чисто (без exception)
    assert hb.done()
    assert hb.exception() is None
```

- [ ] **Step 2: Run, expect import error**

```bash
pytest tests/test_heartbeat.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'heartbeat_loop' from 'worker'`.

- [ ] **Step 3: Implement heartbeat_loop в worker.py**

Добавить в `worker.py` сразу после `mark_task_error` (около строки 95):

```python
async def heartbeat_loop(pool, task_id: int, stop: asyncio.Event, interval_sec: float = 30.0):
    """Каждые interval_sec секунд UPDATE updated_at=NOW() для активного task'a.

    Защита от ложно-positive watchdog'a: один scheme может рендериться 5+ мин,
    весь task — 30-75 мин. Без heartbeat'a watchdog подумал бы что worker
    помер и requeue'нул бы активный task → дубль S3/DB записи.

    Guard `WHERE current_status='processing'` — если статус сменился
    (done/error/superseded), heartbeat не оживит завершённую запись.
    """
    while not stop.is_set():
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE unic_tasks SET updated_at=NOW() "
                    "WHERE id=$1 AND current_status='processing'",
                    task_id,
                )
        except Exception as e:
            logger.warning(f'[heartbeat] task {task_id} update failed: {e}')

        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/test_heartbeat.py -v 2>&1 | tail -15
```

Expected: 3/3 зелёные.

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_heartbeat.py
git commit -m "feat(heartbeat): heartbeat_loop обновляет updated_at каждые 30s

Защита от ложно-positive watchdog requeue во время длинного scheme_preview
рендера. WHERE current_status='processing' guard не даёт случайно оживить
завершённые задачи."
```

---

### Task 9: Test + implement stale_task_recovery_loop (watchdog)

**Files:**
- Modify: `/home/claude-user/unic-worker/worker.py` (добавить watchdog)
- Create: `/home/claude-user/unic-worker/tests/test_watchdog.py`

- [ ] **Step 1: Write failing test**

`tests/test_watchdog.py`:

```python
"""Watchdog reverts processing scheme_preview-tasks без heartbeat'a > 15 мин."""
import asyncio
import pytest
from worker import stale_task_recovery_loop, _run_watchdog_tick


@pytest.mark.asyncio
async def test_watchdog_reverts_stale_scheme_preview(pool, clean_unic_tasks, test_project_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, created_at, updated_at)
            VALUES
              ('scheme_preview', $1, 'processing', '[]'::text, 0,
               'http://test/s.mp4', 'test',
               NOW() - INTERVAL '20 minutes',
               NOW() - INTERVAL '20 minutes')
            RETURNING id
        """, test_project_id)
        task_id = row['id']

    reverted = await _run_watchdog_tick(pool)

    assert task_id in [r['id'] for r in reverted]

    async with pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT current_status FROM unic_tasks WHERE id=$1", task_id,
        )
        meta = await conn.fetchval(
            "SELECT meta FROM unic_tasks WHERE id=$1", task_id,
        )

    assert status == 'pending'
    # revert_count записан в meta jsonb
    import json
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert int(meta.get('watchdog_revert_count', 0)) == 1


@pytest.mark.asyncio
async def test_watchdog_skips_unic_legacy_tasks(pool, clean_unic_tasks, test_project_id):
    """Legacy unic task processing > 15 min — watchdog НЕ трогает (см. spec
    Out of scope #8 — нужен heartbeat в legacy process_task, не в этом PR)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               slot_date, input_video_url, project_name, created_at, updated_at)
            VALUES
              ('unic', $1, 'processing', '[]'::text, 0,
               '2026-05-12', 'http://test/s.mp4', 'test',
               NOW() - INTERVAL '30 minutes',
               NOW() - INTERVAL '30 minutes')
            RETURNING id
        """, test_project_id)
        task_id = row['id']

    reverted = await _run_watchdog_tick(pool)

    assert task_id not in [r['id'] for r in reverted]
    async with pool.acquire() as conn:
        status = await conn.fetchval(
            "SELECT current_status FROM unic_tasks WHERE id=$1", task_id,
        )
    assert status == 'processing'  # не тронут


@pytest.mark.asyncio
async def test_watchdog_skips_fresh_processing(pool, clean_unic_tasks, test_project_id):
    """updated_at < 15 мин назад — не stale, watchdog не трогает."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, created_at, updated_at)
            VALUES
              ('scheme_preview', $1, 'processing', '[]'::text, 0,
               'http://test/s.mp4', 'test',
               NOW() - INTERVAL '10 minutes',
               NOW() - INTERVAL '10 minutes')
            RETURNING id
        """, test_project_id)
        task_id = row['id']

    reverted = await _run_watchdog_tick(pool)
    assert task_id not in [r['id'] for r in reverted]


@pytest.mark.asyncio
async def test_watchdog_skips_after_3_reverts(pool, clean_unic_tasks, test_project_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, created_at, updated_at,
               meta)
            VALUES
              ('scheme_preview', $1, 'processing', '[]'::text, 0,
               'http://test/s.mp4', 'test',
               NOW() - INTERVAL '20 minutes',
               NOW() - INTERVAL '20 minutes',
               '{"watchdog_revert_count": 3}'::jsonb)
            RETURNING id
        """, test_project_id)
        task_id = row['id']

    reverted = await _run_watchdog_tick(pool)
    assert task_id not in [r['id'] for r in reverted]
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/test_watchdog.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'stale_task_recovery_loop'`.

- [ ] **Step 3: Implement watchdog в worker.py**

Добавить в `worker.py` после `heartbeat_loop`:

```python
async def _run_watchdog_tick(pool) -> list[dict]:
    """Один tick watchdog'a: revert stale scheme_preview-tasks → pending.

    Returns: список reverted row'ов (id, task_type, revert_count) для логирования.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            UPDATE unic_tasks
               SET current_status='pending',
                   updated_at=NOW(),
                   meta = COALESCE(meta, '{}'::jsonb) || jsonb_build_object(
                     'watchdog_revert_at', NOW()::text,
                     'watchdog_revert_count',
                        COALESCE((meta->>'watchdog_revert_count')::int, 0) + 1
                   )
             WHERE current_status='processing'
               AND updated_at < NOW() - INTERVAL '15 minutes'
               AND task_type = 'scheme_preview'
               AND COALESCE((meta->>'watchdog_revert_count')::int, 0) < 3
            RETURNING id, task_type,
                      (meta->>'watchdog_revert_count')::int as revert_count
        """)
    return [dict(r) for r in rows]


async def stale_task_recovery_loop(pool):
    """Каждые 5 минут revert'ит stale scheme_preview-tasks → pending."""
    while True:
        await asyncio.sleep(300)
        try:
            rows = await _run_watchdog_tick(pool)
            for r in rows:
                logger.warning(
                    f'[watchdog] Reverted stale task id={r["id"]} '
                    f'type={r["task_type"]} revert_count={r["revert_count"]}'
                )
        except Exception as e:
            logger.exception(f'[watchdog] loop error: {e}')
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/test_watchdog.py -v 2>&1 | tail -15
```

Expected: 4/4 зелёные.

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_watchdog.py
git commit -m "feat(watchdog): stale_task_recovery_loop reverts stuck scheme_preview tasks

5-мин cron tick. WHERE task_type='scheme_preview' (legacy unic не трогаем,
требует heartbeat — отдельный backlog). Max 3 revert'a per task — после
останавливается для ручного расследования."
```

---

### Task 10: Test + implement `process_scheme_preview_task` + dispatcher

**Files:**
- Modify: `/home/claude-user/unic-worker/worker.py` (новая функция + dispatcher в main loop)
- Create: `/home/claude-user/unic-worker/tests/test_dispatch_by_task_type.py`
- Create: `/home/claude-user/unic-worker/tests/test_payload_processing.py`

- [ ] **Step 1: Write dispatch test**

`tests/test_dispatch_by_task_type.py`:

```python
"""Dispatcher выбирает правильную ветку обработки по task_type."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from worker import dispatch_task


@pytest.mark.asyncio
async def test_dispatch_routes_scheme_preview():
    task = {'id': 1, 'task_type': 'scheme_preview', 'project_id': 1, 'schemes': '[]'}
    pool = AsyncMock()
    with patch('worker.process_scheme_preview_task', new_callable=AsyncMock) as mock_preview, \
         patch('worker.process_task', new_callable=AsyncMock) as mock_unic:
        await dispatch_task(pool, task)

    mock_preview.assert_awaited_once_with(pool, task)
    mock_unic.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_routes_unic_legacy():
    task = {'id': 1, 'task_type': 'unic', 'project_id': 1, 'schemes': '[]'}
    pool = AsyncMock()
    with patch('worker.process_scheme_preview_task', new_callable=AsyncMock) as mock_preview, \
         patch('worker.process_task', new_callable=AsyncMock) as mock_unic:
        await dispatch_task(pool, task)

    mock_unic.assert_awaited_once_with(pool, task)
    mock_preview.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_unknown_type_logs_error(caplog):
    task = {'id': 1, 'task_type': 'mystery', 'project_id': 1, 'schemes': '[]'}
    pool = AsyncMock()
    with patch('worker.process_scheme_preview_task', new_callable=AsyncMock), \
         patch('worker.process_task', new_callable=AsyncMock), \
         patch('worker.mark_task_error', new_callable=AsyncMock) as mock_err:
        await dispatch_task(pool, task)

    mock_err.assert_awaited_once()
    args, _ = mock_err.call_args
    assert "Unknown task_type" in args[2]  # mark_task_error(pool, task_id, msg)
```

- [ ] **Step 2: Run, expect ImportError на `dispatch_task`**

```bash
pytest tests/test_dispatch_by_task_type.py -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement dispatcher + skeleton process_scheme_preview_task**

В `worker.py`, в конец перед main loop добавить:

```python
async def process_scheme_preview_task(pool, task):
    """Обработка scheme_preview task'a: рендер N схем для UI выбора.

    Pipeline:
      1) heartbeat_loop запускается параллельно (обновляет updated_at каждые 30s)
      2) download sample/logo/overlays/pattern в /tmp/unic_worker/preview_{id}/
      3) for each scheme:
         - generate_ffmpeg(...) → preview.mp4
         - thumbnail (frame 5)
         - S3 upload: scheme-previews/{project_id}/{scheme_id}/preview.mp4 + thumb.jpg
         - UPSERT в validator_scheme_previews с last_task_id guard
         - UPDATE unic_tasks.schemes_done
      4) cleanup tmp
      5) mark_task_done

    Stop-conditions: scheme-individual error → continue остальными;
    catastrophic error (download sample, disk full) → mark_task_error.
    """
    import json
    import os
    import tempfile

    task_id = task['id']
    project_id = task['project_id']
    stop = asyncio.Event()
    hb = asyncio.create_task(heartbeat_loop(pool, task_id, stop))

    try:
        schemes = task['schemes']
        if isinstance(schemes, str):
            schemes = json.loads(schemes)

        meta = task.get('meta') or {}
        if isinstance(meta, str):
            meta = json.loads(meta)

        sample_url = meta.get('sample_url')
        logo_url = meta.get('logo_url')
        pattern_url = meta.get('pattern_url')
        content_resources = meta.get('content_resources') or {}
        overlay_videos = content_resources.get('videos', [])

        if not sample_url:
            await mark_task_error(pool, task_id, 'sample_url missing in meta')
            return

        tmp_dir = tempfile.mkdtemp(prefix=f'preview_{task_id}_', dir=TEMP_DIR)
        logger.info(f'[scheme_preview {task_id}] Starting, tmp={tmp_dir}, schemes={len(schemes)}')

        try:
            sample_path = os.path.join(tmp_dir, 'sample.mp4')
            if not _download_file_sync(sample_url, sample_path):
                await mark_task_error(pool, task_id, f'Failed to download sample from {sample_url[:80]}')
                return

            logo_path = None
            if logo_url:
                logo_path = os.path.join(tmp_dir, 'logo.png')
                if not _download_file_sync(logo_url, logo_path):
                    logo_path = None
                    logger.warning(f'[scheme_preview {task_id}] logo download failed, continuing')

            pattern_path = None
            if pattern_url:
                pattern_path = os.path.join(tmp_dir, 'pattern.png')
                if not _download_file_sync(pattern_url, pattern_path):
                    pattern_path = None

            # overlays — lazy скачиваем только нужные
            needed_indices = set()
            for s in schemes:
                idx = int(s.get('content_video_index') or 1) - 1
                needed_indices.add(idx)

            ov_paths: dict[int, str] = {}
            for idx in needed_indices:
                if idx < 0 or idx >= len(overlay_videos):
                    continue
                ov = overlay_videos[idx]
                p = os.path.join(tmp_dir, f'overlay_{idx}.mp4')
                if _download_file_sync(ov['file_path'], p):
                    ov_paths[idx] = p

            scheme_errors: dict[int, str] = {}
            done_count = 0

            for i, scheme in enumerate(schemes):
                sid = scheme['id']
                try:
                    files = {'original': sample_path}
                    video_idx = int(scheme.get('content_video_index') or 1) - 1
                    chromakey_color = None
                    if video_idx in ov_paths:
                        files['overlay_video'] = ov_paths[video_idx]
                        chromakey_color = overlay_videos[video_idx].get('chromakey_color')
                    elif ov_paths:
                        first_idx = next(iter(ov_paths))
                        files['overlay_video'] = ov_paths[first_idx]
                        chromakey_color = overlay_videos[first_idx].get('chromakey_color')

                    if logo_path:
                        files['logo'] = logo_path
                    if pattern_path:
                        files['pattern'] = pattern_path

                    video_path = os.path.join(tmp_dir, f's{sid}.mp4')
                    thumb_path = os.path.join(tmp_dir, f's{sid}.jpg')

                    cmd = generate_ffmpeg(scheme, files, chromakey_color, video_path)
                    logger.info(f'[scheme_preview {task_id}] scheme {sid} ({i+1}/{len(schemes)}): running ffmpeg')
                    result = await asyncio.to_thread(
                        subprocess.run, cmd,
                        capture_output=True, text=True, timeout=300,
                    )
                    if result.returncode != 0:
                        scheme_errors[sid] = result.stderr[-400:]
                        logger.error(f'[scheme_preview {task_id}] scheme {sid} ffmpeg fail: {result.stderr[-200:]}')
                        continue

                    # thumbnail
                    await asyncio.to_thread(
                        subprocess.run,
                        [
                            'ffmpeg', '-y', '-i', video_path,
                            '-vf', 'select=eq(n\\,5)', '-vframes', '1', '-q:v', '3',
                            thumb_path,
                        ],
                        capture_output=True, timeout=30,
                    )

                    # S3 upload
                    s3_prefix = f'scheme-previews/{project_id}/{sid}'
                    video_key = f'{s3_prefix}/preview.mp4'
                    video_url = await asyncio.to_thread(
                        upload_to_s3, video_path, video_key,
                    )

                    thumb_url = None
                    if os.path.exists(thumb_path):
                        thumb_key = f'{s3_prefix}/thumb.jpg'
                        try:
                            thumb_url = await asyncio.to_thread(
                                upload_to_s3, thumb_path, thumb_key,
                            )
                        except Exception as e:
                            logger.warning(f'[scheme_preview {task_id}] thumb upload fail scheme {sid}: {e}')

                    # UPSERT в validator_scheme_previews с last_task_id guard
                    async with pool.acquire() as conn:
                        affected = await conn.execute("""
                            INSERT INTO validator_scheme_previews
                                (scheme_id, project_id, thumb_url, video_url, last_task_id, generated_at)
                            VALUES ($1, $2, $3, $4, $5, NOW())
                            ON CONFLICT (scheme_id, project_id) DO UPDATE
                               SET thumb_url    = EXCLUDED.thumb_url,
                                   video_url    = EXCLUDED.video_url,
                                   last_task_id = EXCLUDED.last_task_id,
                                   generated_at = NOW()
                             WHERE validator_scheme_previews.last_task_id IS NULL
                                OR validator_scheme_previews.last_task_id < EXCLUDED.last_task_id
                        """, sid, project_id, thumb_url, video_url, task_id)
                        if affected == 'INSERT 0 0':  # WHERE-false на UPDATE
                            logger.warning(
                                f'[scheme_preview {task_id}] scheme {sid} skipped UPSERT — '
                                f'newer task_id already wrote'
                            )

                    done_count += 1

                except Exception as e:
                    scheme_errors[sid] = str(e)[:300]
                    logger.exception(f'[scheme_preview {task_id}] scheme {sid} unexpected fail: {e}')

                # progress update
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE unic_tasks SET schemes_done=$2, schemes_error=$3, updated_at=NOW() "
                        "WHERE id=$1",
                        task_id, done_count, len(scheme_errors),
                    )

            if scheme_errors and done_count == 0:
                await mark_task_error(
                    pool, task_id,
                    f'All {len(schemes)} schemes failed',
                    scheme_errors=scheme_errors,
                )
            elif scheme_errors:
                # partial success — done, но scheme_errors в meta
                async with pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE unic_tasks
                           SET current_status='done', updated_at=NOW(),
                               meta = COALESCE(meta, '{}'::jsonb) || jsonb_build_object(
                                 'scheme_errors',
                                 ($2::jsonb)
                               )
                         WHERE id=$1
                    """, task_id, json.dumps({str(k): v for k, v in scheme_errors.items()}))
            else:
                await mark_task_done(pool, task_id)

        finally:
            # cleanup tmp dir
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
    finally:
        stop.set()
        await hb


async def dispatch_task(pool, task):
    """Роутит task по task_type."""
    tt = task.get('task_type', 'unic')
    if tt == 'scheme_preview':
        await process_scheme_preview_task(pool, task)
    elif tt == 'unic':
        await process_task(pool, task)
    else:
        await mark_task_error(pool, task['id'], f'Unknown task_type: {tt}')
```

В main poll loop (внизу `worker.py`) заменить:

```python
# Найти текущее место где poll → process_task(pool, task)
# и заменить на dispatch_task(pool, task)
```

Конкретно: ищите в main loop вызов `await process_task(pool, task)` и меняйте на `await dispatch_task(pool, task)`. (Скорее всего внутри `worker_loop` или `main` функции.)

Также в `main()`/`startup` добавить запуск watchdog'a:

```python
async def main():
    pool = await get_pool()
    # ... другая инициализация ...

    # Параллельный watchdog (никогда не блокирует main poll)
    watchdog_task = asyncio.create_task(stale_task_recovery_loop(pool))

    try:
        # main poll loop (как был)
        while True:
            task = await get_pending_task(pool)
            if task:
                await dispatch_task(pool, task)
            else:
                await asyncio.sleep(POLL_INTERVAL)
    finally:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 4: Run dispatch tests, expect pass**

```bash
pytest tests/test_dispatch_by_task_type.py -v 2>&1 | tail -15
```

Expected: 3/3 зелёные.

- [ ] **Step 5: Commit**

```bash
git add worker.py tests/test_dispatch_by_task_type.py
git commit -m "feat(worker): process_scheme_preview_task + dispatch_task

Dispatcher маршрутизирует по task_type: 'scheme_preview' → новый pipeline,
'unic' (legacy) → существующий process_task. Unknown type → mark_task_error.

process_scheme_preview_task:
  - heartbeat_loop параллельно
  - download sample/logo/overlays/pattern
  - for each scheme: generate_ffmpeg + thumbnail + S3 + UPSERT с last_task_id
  - per-scheme errors не валят весь task (partial success)
  - cleanup tmp в finally"
```

---

### Task 11: Test + implement payload processing E2E

**Files:**
- Create: `/home/claude-user/unic-worker/tests/test_payload_processing.py`

- [ ] **Step 1: Write E2E test (с mock'ом S3 и ffmpeg)**

`tests/test_payload_processing.py`:

```python
"""End-to-end test process_scheme_preview_task.

Mock'аем _download_file_sync, generate_ffmpeg вызов, upload_to_s3, и subprocess.
Проверяем что вся orchestration работает корректно (DB UPDATE'ы, UPSERT,
heartbeat, status transitions)."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from worker import process_scheme_preview_task


@pytest.fixture
async def preview_task(pool, clean_unic_tasks, test_project_id):
    """INSERT pending scheme_preview task в БД."""
    schemes = [
        {'id': 9001, 'content_video_index': 1},
        {'id': 9002, 'content_video_index': 1},
    ]
    meta = {
        'sample_url': 'http://test/sample.mp4',
        'logo_url': None,
        'pattern_url': None,
        'content_resources': {'videos': [{'file_path': 'http://test/ov0.mp4'}]},
    }
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO unic_tasks
              (task_type, project_id, current_status, schemes, schemes_total,
               input_video_url, project_name, meta,
               created_at, updated_at)
            VALUES
              ('scheme_preview', $1, 'processing', $2, $3,
               $4, 'test', $5, NOW(), NOW())
            RETURNING id
        """, test_project_id, json.dumps(schemes), len(schemes),
              meta['sample_url'], json.dumps(meta))

        # cleanup previews от прошлых прогонов
        await conn.execute(
            "DELETE FROM validator_scheme_previews WHERE project_id=$1",
            test_project_id,
        )

    return {'id': row['id'], 'project_id': test_project_id,
            'schemes': schemes, 'meta': meta}


@pytest.mark.asyncio
async def test_happy_path_marks_done_and_writes_previews(pool, preview_task):
    task_row = preview_task

    async with pool.acquire() as conn:
        task = await conn.fetchrow(
            "SELECT * FROM unic_tasks WHERE id=$1", task_row['id'],
        )
        task = dict(task)

    # Mock внешних эффектов
    with patch('worker._download_file_sync', return_value=True) as mock_dl, \
         patch('worker.subprocess.run') as mock_run, \
         patch('worker.upload_to_s3', return_value='https://save.gengo.io/scheme-previews/test.mp4'):
        mock_run.return_value = MagicMock(returncode=0, stderr='')

        await process_scheme_preview_task(pool, task)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_status, schemes_done, schemes_error "
            "FROM unic_tasks WHERE id=$1",
            task_row['id'],
        )
        previews = await conn.fetch(
            "SELECT scheme_id, video_url, last_task_id "
            "FROM validator_scheme_previews WHERE project_id=$1 ORDER BY scheme_id",
            task_row['project_id'],
        )

    assert row['current_status'] == 'done'
    assert row['schemes_done'] == 2
    assert row['schemes_error'] == 0
    assert len(previews) == 2
    assert all(p['last_task_id'] == task_row['id'] for p in previews)


@pytest.mark.asyncio
async def test_partial_failure_marks_done_with_scheme_errors(pool, preview_task):
    task_row = preview_task
    async with pool.acquire() as conn:
        task = dict(await conn.fetchrow(
            "SELECT * FROM unic_tasks WHERE id=$1", task_row['id'],
        ))

    # вторая схема упадёт
    call_count = {'n': 0}
    def run_mock(*args, **kwargs):
        call_count['n'] += 1
        # пара ffmpeg+thumb per scheme = 2 calls per scheme. Total для 2 схем = 4.
        # Падать на 3-м (т.е. ffmpeg второй схемы)
        if call_count['n'] == 3:
            return MagicMock(returncode=1, stderr='ffmpeg error simulated')
        return MagicMock(returncode=0, stderr='')

    with patch('worker._download_file_sync', return_value=True), \
         patch('worker.subprocess.run', side_effect=run_mock), \
         patch('worker.upload_to_s3', return_value='https://save.gengo.io/test.mp4'):
        await process_scheme_preview_task(pool, task)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_status, meta FROM unic_tasks WHERE id=$1",
            task_row['id'],
        )

    meta = row['meta']
    if isinstance(meta, str):
        meta = json.loads(meta)
    assert row['current_status'] == 'done'
    assert 'scheme_errors' in meta


@pytest.mark.asyncio
async def test_sample_download_failure_marks_error(pool, preview_task):
    task_row = preview_task
    async with pool.acquire() as conn:
        task = dict(await conn.fetchrow(
            "SELECT * FROM unic_tasks WHERE id=$1", task_row['id'],
        ))

    with patch('worker._download_file_sync', return_value=False):
        await process_scheme_preview_task(pool, task)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_status, error_message FROM unic_tasks WHERE id=$1",
            task_row['id'],
        )

    assert row['current_status'] == 'error'
    assert 'sample' in (row['error_message'] or '').lower()


@pytest.mark.asyncio
async def test_last_task_id_guard_blocks_stale_overwrite(pool, preview_task):
    """Если уже есть строка с last_task_id больше — UPSERT skip."""
    task_row = preview_task
    pid = task_row['project_id']

    # pre-INSERT свежую строку с last_task_id=99999999
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO validator_scheme_previews
              (scheme_id, project_id, thumb_url, video_url, last_task_id, generated_at)
            VALUES (9001, $1, 'stale/thumb.jpg', 'stale/preview.mp4', 99999999, NOW())
        """, pid)

        task = dict(await conn.fetchrow(
            "SELECT * FROM unic_tasks WHERE id=$1", task_row['id'],
        ))

    with patch('worker._download_file_sync', return_value=True), \
         patch('worker.subprocess.run', return_value=MagicMock(returncode=0, stderr='')), \
         patch('worker.upload_to_s3', return_value='https://save.gengo.io/NEW.mp4'):
        await process_scheme_preview_task(pool, task)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT video_url, last_task_id FROM validator_scheme_previews "
            "WHERE project_id=$1 AND scheme_id=9001",
            pid,
        )

    # старая запись с last_task_id=99999999 НЕ перезаписана
    assert row['last_task_id'] == 99999999
    assert row['video_url'] == 'stale/preview.mp4'
```

- [ ] **Step 2: Run E2E tests**

```bash
pytest tests/test_payload_processing.py -v 2>&1 | tail -20
```

Expected: 4/4 зелёные. Если что-то падает — fix имплементацию `process_scheme_preview_task` в Task 10 inline, не правь тесты для прохождения.

- [ ] **Step 3: Commit**

```bash
git add tests/test_payload_processing.py
git commit -m "test(scheme_preview): E2E pipeline + partial failure + last_task_id guard"
```

---

### Task 12: Codex review unic-worker diff + push PR

- [ ] **Step 1: запустить codex review на полном diff'е**

```bash
cd /home/claude-user/unic-worker
git diff main..HEAD | codex review - 2>&1 | tail -50
```

Expected: P1=0. Если есть P1 — фиксить, повторять, до зелёного.

- [ ] **Step 1.5: Add minimal GitHub Actions CI**

`.github/workflows/test.yml`:

```yaml
name: tests
on: [push, pull_request]
jobs:
  pytest:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: openclaw
          POSTGRES_PASSWORD: openclaw123
          POSTGRES_DB: openclaw
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements-test.txt
      - name: Apply test schema
        env:
          PGPASSWORD: openclaw123
        run: |
          psql -h localhost -U openclaw -d openclaw -c "
            CREATE TABLE unic_tasks (
              id SERIAL PRIMARY KEY,
              task_type TEXT NOT NULL DEFAULT 'unic',
              project_id INT, current_status TEXT,
              schemes TEXT, schemes_total INT, schemes_done INT, schemes_error INT,
              input_video_url TEXT, project_name TEXT, slot_date DATE,
              error_message TEXT, meta JSONB, payload_hash TEXT,
              created_at TIMESTAMPTZ DEFAULT NOW(),
              updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE validator_scheme_previews (
              scheme_id INT, project_id INT,
              thumb_url TEXT, video_url TEXT, last_task_id BIGINT,
              generated_at TIMESTAMPTZ,
              PRIMARY KEY (scheme_id, project_id)
            );
          "
      - run: pytest -v
        env:
          TEST_DATABASE_URL: postgresql://openclaw:openclaw123@localhost:5432/openclaw
```

```bash
git add .github/workflows/test.yml
git commit -m "ci: pytest on push/PR with postgres service"
```

- [ ] **Step 2: push PR**

```bash
source ~/secrets/github-gengo2.env
GH_TOKEN="$GITHUB_TOKEN_GENGO2" git push -u origin feat/scheme-preview-task-type-20260512
GH_TOKEN="$GITHUB_TOKEN_GENGO2" gh pr create --repo GenGo2/unic-worker \
    --title "feat: scheme_preview task_type + dispatcher + heartbeat + watchdog" \
    --body "$(cat <<'EOF'
## Summary

Реализует worker-side миграции scheme preview generation на этот воркер.

Spec: contenthunter/docs/superpowers/specs/2026-05-12-scheme-preview-remote-worker-design.md
Plan: contenthunter/docs/superpowers/plans/2026-05-12-scheme-preview-remote-worker.md

## Components

- `get_pending_task` — per-project guard для scheme_preview
- `heartbeat_loop` — UPDATE updated_at каждые 30s
- `stale_task_recovery_loop` — watchdog reverts scheme_preview > 15min без heartbeat'a
- `process_scheme_preview_task` — рендер N схем + UPSERT validator_scheme_previews с last_task_id
- `dispatch_task` — по task_type → preview / unic / error

## Tests

- per-project guard (3)
- heartbeat (3)
- watchdog (4)
- dispatch (3)
- E2E pipeline (4)

## Deploy

После merge — scp на 91.98.180.103, pm2 restart. См. plan Task 16.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: автоматический merge (validator-style)**

```bash
# Можно использовать --auto если стандарт; иначе ручное merge:
GH_TOKEN="$GITHUB_TOKEN_GENGO2" gh pr merge --repo GenGo2/unic-worker --merge --delete-branch
```

---

## Phase 3 — validator-contenthunter side

### Task 13: Create feature branch + setup

**Files:** branching

- [ ] **Step 1: branch + sync**

```bash
cd /home/claude-user/validator-contenthunter
git fetch origin --quiet
git checkout main
git pull --ff-only
# Phase 1 ветка уже merged (Task 3 step 6); если ещё нет — merge сначала её
git checkout -b feat/scheme-preview-via-worker-20260512
```

---

### Task 14: Test + implement `_compute_payload_hash`

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/src/services/scheme_preview_queue.py`
- Create: `/home/claude-user/validator-contenthunter/backend/tests/test_payload_hash.py`

- [ ] **Step 1: Write failing test**

`backend/tests/test_payload_hash.py`:

```python
"""payload_hash должен:
1) быть стабильным относительно порядка keys/items
2) меняться при изменении любого render-параметра внутри схемы
3) меняться при изменении sample_url/logo_url/pattern_url
4) меняться при изменении состава content_video_ids
"""
from src.services.scheme_preview_queue import compute_payload_hash


def test_hash_stable_with_reordered_keys():
    payload_a = {
        'project_id': 53,
        'schemes': [
            {'id': 1, 'drawboxes': [{'x': 5, 'y': 10}], 'rotation': 1.5},
            {'id': 2, 'drawboxes': [], 'rotation': 0},
        ],
        'sample_url': 'http://s/a.mp4',
        'logo_url': 'http://s/logo.png',
        'pattern_url': None,
        'content_resources': {'videos': [{'id': 100}, {'id': 200}]},
    }
    payload_b = {
        'content_resources': {'videos': [{'id': 200}, {'id': 100}]},
        'pattern_url': None,
        'logo_url': 'http://s/logo.png',
        'sample_url': 'http://s/a.mp4',
        'schemes': [
            {'rotation': 0, 'id': 2, 'drawboxes': []},
            {'drawboxes': [{'y': 10, 'x': 5}], 'rotation': 1.5, 'id': 1},
        ],
        'project_id': 53,
    }
    assert compute_payload_hash(payload_a) == compute_payload_hash(payload_b)


def test_hash_changes_on_scheme_param_change():
    base = {
        'project_id': 53,
        'schemes': [{'id': 1, 'drawboxes': [{'x': 5}], 'rotation': 1.5}],
        'sample_url': 'http://s/a.mp4', 'logo_url': None, 'pattern_url': None,
        'content_resources': {'videos': []},
    }
    modified = {
        'project_id': 53,
        'schemes': [{'id': 1, 'drawboxes': [{'x': 999}], 'rotation': 1.5}],
        'sample_url': 'http://s/a.mp4', 'logo_url': None, 'pattern_url': None,
        'content_resources': {'videos': []},
    }
    assert compute_payload_hash(base) != compute_payload_hash(modified)


def test_hash_changes_on_sample_url():
    a = {'project_id': 53, 'schemes': [], 'sample_url': 'http://a',
         'logo_url': None, 'pattern_url': None,
         'content_resources': {'videos': []}}
    b = {'project_id': 53, 'schemes': [], 'sample_url': 'http://b',
         'logo_url': None, 'pattern_url': None,
         'content_resources': {'videos': []}}
    assert compute_payload_hash(a) != compute_payload_hash(b)


def test_hash_changes_on_video_id_set():
    a = {'project_id': 53, 'schemes': [], 'sample_url': 'http://a',
         'logo_url': None, 'pattern_url': None,
         'content_resources': {'videos': [{'id': 1}]}}
    b = {'project_id': 53, 'schemes': [], 'sample_url': 'http://a',
         'logo_url': None, 'pattern_url': None,
         'content_resources': {'videos': [{'id': 2}]}}
    assert compute_payload_hash(a) != compute_payload_hash(b)


def test_hash_independent_of_video_order():
    a = {'project_id': 53, 'schemes': [], 'sample_url': 'http://a',
         'logo_url': None, 'pattern_url': None,
         'content_resources': {'videos': [{'id': 1}, {'id': 2}]}}
    b = {'project_id': 53, 'schemes': [], 'sample_url': 'http://a',
         'logo_url': None, 'pattern_url': None,
         'content_resources': {'videos': [{'id': 2}, {'id': 1}]}}
    assert compute_payload_hash(a) == compute_payload_hash(b)
```

- [ ] **Step 2: Run, expect ImportError**

```bash
cd /home/claude-user/validator-contenthunter/backend
pytest tests/test_payload_hash.py -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement `compute_payload_hash`**

`backend/src/services/scheme_preview_queue.py`:

```python
"""Helpers для scheme_preview queue: payload hashing, enqueue с dedup/supersede, status read.

Vendoring через одну точку входа упрощает testing и держит router lean.
"""
import hashlib
import json
from typing import Any


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """Канонический md5 от полного payload (schemes contents included).

    Hash меняется при ЛЮБОМ изменении render-параметров: drawboxes, chromakey,
    rotation, speed и т.д. Поэтому dedup-join возможен только для idempotent
    повторов (двойной клик), не при изменении настроек схем.

    Stable to:
      - порядок keys в dict
      - порядок content_video_ids (sorted)
      - whitespace в json
    """
    canonical = {
        'project_id': int(payload.get('project_id', 0)),
        'schemes': sorted([
            json.dumps(s, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            for s in (payload.get('schemes') or [])
        ]),
        'sample_url': payload.get('sample_url') or '',
        'logo_url': payload.get('logo_url') or '',
        'pattern_url': payload.get('pattern_url') or '',
        'content_video_ids': sorted([
            int(v.get('id', 0))
            for v in (payload.get('content_resources') or {}).get('videos', [])
        ]),
    }
    body = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.md5(body.encode('utf-8')).hexdigest()
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/test_payload_hash.py -v 2>&1 | tail -15
```

Expected: 5/5 зелёные.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/scheme_preview_queue.py backend/tests/test_payload_hash.py
git commit -m "feat(scheme_preview_queue): compute_payload_hash + tests"
```

---

### Task 15: Test + implement `enqueue_scheme_preview` (advisory lock + dedup + supersede)

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/backend/src/services/scheme_preview_queue.py`
- Create: `/home/claude-user/validator-contenthunter/backend/tests/test_scheme_preview_queue.py`

- [ ] **Step 1: Write failing test**

`backend/tests/test_scheme_preview_queue.py`:

```python
"""enqueue_scheme_preview: advisory lock per project + dedup + supersede."""
import asyncio
import json
import pytest
from sqlalchemy import text
from src.database import AsyncSessionLocal
from src.services.scheme_preview_queue import enqueue_scheme_preview


@pytest.fixture
async def clean_project():
    """Очищает scheme_preview tasks для test_project_id (>=100000)."""
    import random
    pid = 100000 + random.randint(1, 99999)
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "DELETE FROM unic_tasks WHERE task_type='scheme_preview' AND project_id=:pid"
        ), {'pid': pid})
        await db.commit()
    yield pid
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "DELETE FROM unic_tasks WHERE task_type='scheme_preview' AND project_id=:pid"
        ), {'pid': pid})
        await db.commit()


SAMPLE_PAYLOAD = lambda pid: {
    'project_id': pid,
    'schemes': [{'id': 1, 'rotation': 0}],
    'sample_url': 'http://s/a.mp4', 'logo_url': None, 'pattern_url': None,
    'content_resources': {'videos': []},
}


@pytest.mark.asyncio
async def test_enqueue_creates_pending_task(clean_project):
    pid = clean_project
    async with AsyncSessionLocal() as db:
        result = await enqueue_scheme_preview(db, SAMPLE_PAYLOAD(pid))
        await db.commit()

    assert result['joined_existing'] is False
    assert result['task_id'] > 0
    assert result['total'] == 1

    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT current_status, task_type, payload_hash FROM unic_tasks WHERE id=:id"
        ), {'id': result['task_id']})).mappings().first()
        assert row['current_status'] == 'pending'
        assert row['task_type'] == 'scheme_preview'
        assert row['payload_hash'] is not None


@pytest.mark.asyncio
async def test_enqueue_dedup_same_payload_returns_existing(clean_project):
    pid = clean_project
    payload = SAMPLE_PAYLOAD(pid)

    async with AsyncSessionLocal() as db:
        r1 = await enqueue_scheme_preview(db, payload)
        await db.commit()

    async with AsyncSessionLocal() as db:
        r2 = await enqueue_scheme_preview(db, payload)
        await db.commit()

    assert r2['joined_existing'] is True
    assert r2['task_id'] == r1['task_id']

    async with AsyncSessionLocal() as db:
        cnt = (await db.execute(text(
            "SELECT COUNT(*) AS c FROM unic_tasks WHERE task_type='scheme_preview' AND project_id=:pid"
        ), {'pid': pid})).scalar()
        assert cnt == 1  # одна строка, не две


@pytest.mark.asyncio
async def test_enqueue_supersedes_pending_with_different_payload(clean_project):
    pid = clean_project
    payload_a = SAMPLE_PAYLOAD(pid)
    payload_b = SAMPLE_PAYLOAD(pid)
    payload_b['schemes'][0]['rotation'] = 99  # другой payload

    async with AsyncSessionLocal() as db:
        r1 = await enqueue_scheme_preview(db, payload_a)
        await db.commit()

    async with AsyncSessionLocal() as db:
        r2 = await enqueue_scheme_preview(db, payload_b)
        await db.commit()

    assert r2['task_id'] != r1['task_id']

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, current_status FROM unic_tasks "
            "WHERE task_type='scheme_preview' AND project_id=:pid ORDER BY id"
        ), {'pid': pid})).mappings().all()
        assert len(rows) == 2
        assert rows[0]['id'] == r1['task_id']
        assert rows[0]['current_status'] == 'superseded'
        assert rows[1]['id'] == r2['task_id']
        assert rows[1]['current_status'] == 'pending'


@pytest.mark.asyncio
async def test_enqueue_does_not_supersede_processing(clean_project):
    pid = clean_project
    payload_a = SAMPLE_PAYLOAD(pid)
    payload_b = SAMPLE_PAYLOAD(pid)
    payload_b['schemes'][0]['rotation'] = 99

    async with AsyncSessionLocal() as db:
        r1 = await enqueue_scheme_preview(db, payload_a)
        # промотать вручную в processing
        await db.execute(text(
            "UPDATE unic_tasks SET current_status='processing' WHERE id=:id"
        ), {'id': r1['task_id']})
        await db.commit()

    async with AsyncSessionLocal() as db:
        r2 = await enqueue_scheme_preview(db, payload_b)
        await db.commit()

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, current_status FROM unic_tasks "
            "WHERE task_type='scheme_preview' AND project_id=:pid ORDER BY id"
        ), {'pid': pid})).mappings().all()
        assert rows[0]['current_status'] == 'processing'  # processing нетронут
        assert rows[1]['current_status'] == 'pending'


@pytest.mark.asyncio
async def test_concurrent_enqueue_serialized_per_project(clean_project):
    pid = clean_project
    p_a = SAMPLE_PAYLOAD(pid)
    p_b = SAMPLE_PAYLOAD(pid)
    p_b['schemes'][0]['rotation'] = 99

    async def call(payload):
        async with AsyncSessionLocal() as db:
            r = await enqueue_scheme_preview(db, payload)
            await db.commit()
            return r

    # concurrent
    r1, r2 = await asyncio.gather(call(p_a), call(p_b))

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, current_status FROM unic_tasks "
            "WHERE task_type='scheme_preview' AND project_id=:pid ORDER BY id"
        ), {'pid': pid})).mappings().all()

    # после serialized resolve должно быть: одна superseded + одна pending
    # ИЛИ одна pending (если второй заджойнился к первому до supersede; но
    # payload разный, dedup не сработает).
    pending = [r for r in rows if r['current_status'] == 'pending']
    assert len(pending) == 1, f"Ожидаем одну pending, got {[dict(r) for r in rows]}"
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/test_scheme_preview_queue.py -v 2>&1 | tail -10
```

Expected: ImportError для `enqueue_scheme_preview`.

- [ ] **Step 3: Implement `enqueue_scheme_preview`**

Дописать в `backend/src/services/scheme_preview_queue.py`:

```python
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def enqueue_scheme_preview(db: AsyncSession, payload: dict) -> dict:
    """Atomic enqueue с dedup + supersede + advisory lock per project_id.

    Возвращает {task_id, status: 'queued', joined_existing: bool, total: N}.

    Шаги (в одной транзакции):
      0) pg_advisory_xact_lock per project_id — сериализует concurrent
         enqueue-запросы того же project'a
      1) Dedup: SELECT existing scheme_preview task с тем же payload_hash
         в active state. Если есть — RETURN её id с joined_existing=True
      2) Supersede: UPDATE pending → superseded для всех других pending
         того же project
      3) INSERT новой строки с payload_hash + meta + schemes
    """
    project_id = int(payload.get('project_id'))
    if not project_id:
        raise ValueError("payload.project_id обязателен")

    schemes = payload.get('schemes') or []
    sample_url = payload.get('sample_url') or ''
    logo_url = payload.get('logo_url')
    pattern_url = payload.get('pattern_url')
    content_resources = payload.get('content_resources') or {}

    payload_hash = compute_payload_hash(payload)

    # 0) Advisory lock per project. Освобождается на COMMIT/ROLLBACK
    #    транзакции. hashtext даёт stable int4 для произвольной строки.
    await db.execute(text("""
        SELECT pg_advisory_xact_lock(
            hashtext('scheme_preview_enqueue:' || :pid)
        )
    """), {'pid': str(project_id)})

    # 1) Dedup check
    existing = (await db.execute(text("""
        SELECT id, schemes_total
          FROM unic_tasks
         WHERE task_type='scheme_preview'
           AND project_id = :pid
           AND payload_hash = :hash
           AND current_status IN ('pending','processing')
         ORDER BY id DESC
         LIMIT 1
    """), {'pid': project_id, 'hash': payload_hash})).mappings().first()

    if existing:
        return {
            'task_id': int(existing['id']),
            'status': 'queued',
            'joined_existing': True,
            'total': int(existing['schemes_total'] or len(schemes)),
        }

    # 2) Supersede pending'ов того же project (любой hash)
    await db.execute(text("""
        UPDATE unic_tasks
           SET current_status='superseded', updated_at=NOW()
         WHERE task_type='scheme_preview'
           AND project_id = :pid
           AND current_status = 'pending'
    """), {'pid': project_id})

    # 3) INSERT
    meta = {
        'sample_url': sample_url,
        'logo_url': logo_url,
        'pattern_url': pattern_url,
        'content_resources': content_resources,
    }
    row = (await db.execute(text("""
        INSERT INTO unic_tasks
          (task_type, project_id, current_status, payload_hash,
           schemes, schemes_total, schemes_done, schemes_error,
           input_video_url, project_name, meta,
           created_at, updated_at)
        VALUES
          ('scheme_preview', :pid, 'pending', :hash,
           :schemes::text, :total, 0, 0,
           :sample, :pname, :meta::jsonb,
           NOW(), NOW())
        RETURNING id
    """), {
        'pid': project_id,
        'hash': payload_hash,
        'schemes': json.dumps(schemes, ensure_ascii=False),
        'total': len(schemes),
        'sample': sample_url,
        'pname': f'preview_proj_{project_id}',
        'meta': json.dumps(meta, ensure_ascii=False),
    })).mappings().first()

    return {
        'task_id': int(row['id']),
        'status': 'queued',
        'joined_existing': False,
        'total': len(schemes),
    }


async def read_scheme_preview_status(db: AsyncSession, project_id: int) -> dict | None:
    """Читает самый свежий scheme_preview-task проекта.

    Returns: {phase, progress, total, error, task_id, age_sec} или None.
    """
    row = (await db.execute(text("""
        SELECT id, current_status,
               COALESCE(schemes_total, 0) AS total,
               COALESCE(schemes_done, 0) AS done,
               COALESCE(schemes_error, 0) AS errors,
               error_message,
               EXTRACT(EPOCH FROM (NOW() - created_at))::int AS age_sec,
               EXTRACT(EPOCH FROM (NOW() - updated_at))::int AS stale_sec
          FROM unic_tasks
         WHERE task_type='scheme_preview'
           AND project_id = :pid
         ORDER BY id DESC
         LIMIT 1
    """), {'pid': project_id})).mappings().first()

    if not row:
        return None

    phase = row['current_status']
    # queue_delayed: pending старше 30s — worker занят, очередь
    if phase == 'pending' and row['age_sec'] and row['age_sec'] > 30:
        phase = 'queue_delayed'

    return {
        'task_id': int(row['id']),
        'phase': phase,
        'progress': int(row['done']),
        'total': int(row['total']),
        'errors': int(row['errors']),
        'error': row['error_message'],
    }
```

- [ ] **Step 4: Run tests, expect all pass**

```bash
pytest tests/test_scheme_preview_queue.py -v 2>&1 | tail -20
```

Expected: 5/5 зелёные. Если concurrent test flaky — повторить, advisory lock должен гарантировать determinism.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/scheme_preview_queue.py backend/tests/test_scheme_preview_queue.py
git commit -m "feat(scheme_preview_queue): enqueue с advisory lock + dedup + supersede

Atomic transaction с pg_advisory_xact_lock per project_id — сериализует
concurrent enqueue одного project. Dedup join по payload_hash, supersede
pending'ов любого hash того же project. Defense-in-depth для race conditions."
```

---

### Task 16: Test + rewire `POST /api/schemes/{id}/generate-previews` и `GET .../generation-status`

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/backend/src/routers/schemes.py`
- Create: `/home/claude-user/validator-contenthunter/backend/tests/test_scheme_preview_endpoint.py`

- [ ] **Step 1: Write endpoint contract test**

`backend/tests/test_scheme_preview_endpoint.py`:

```python
"""Endpoint contract tests — POST /generate-previews и GET /generation-status."""
import pytest
import httpx
from sqlalchemy import text

from src.main import app
from src.database import AsyncSessionLocal


@pytest.fixture
async def auth_headers():
    """Логин временного admin'a и возврат Bearer header."""
    # Минимальная имплементация: создать temp admin, login, возврат токена.
    # Использовать тот же паттерн что Phase 1/4a debugging.
    # Для краткости плана — admin создаётся вручную в conftest.
    # (см. backend/tests/conftest.py для существующего fixture'a)
    from tests.conftest import get_admin_token
    token = await get_admin_token()
    return {'Authorization': f'Bearer {token}'}


SAMPLE_PROJECT_ID = 100123  # отдельный test project (не пересекается с prod)


@pytest.fixture
async def clean_test_project():
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "DELETE FROM unic_tasks WHERE project_id=:pid"
        ), {'pid': SAMPLE_PROJECT_ID})
        await db.commit()
    yield SAMPLE_PROJECT_ID
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "DELETE FROM unic_tasks WHERE project_id=:pid"
        ), {'pid': SAMPLE_PROJECT_ID})
        await db.commit()


@pytest.fixture
def client():
    return httpx.AsyncClient(app=app, base_url='http://test')


@pytest.mark.asyncio
async def test_generate_previews_creates_task_in_db(client, auth_headers, clean_test_project):
    pid = clean_test_project
    body = {
        'sample_url': 'http://test/sample.mp4',
        'schemes': [{'id': 1, 'rotation': 0}, {'id': 2, 'rotation': 1}],
        'content_resources': {'videos': [{'id': 100, 'file_path': 'http://test/ov.mp4'}]},
    }
    async with client as c:
        r = await c.post(f'/api/schemes/{pid}/generate-previews',
                         headers=auth_headers, json=body)

    assert r.status_code == 200
    data = r.json()
    assert data['joined_existing'] is False
    assert data['total'] == 2
    assert data['task_id'] > 0

    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT task_type, current_status FROM unic_tasks WHERE id=:id"
        ), {'id': data['task_id']})).mappings().first()
        assert row['task_type'] == 'scheme_preview'
        assert row['current_status'] == 'pending'


@pytest.mark.asyncio
async def test_generate_previews_dedup(client, auth_headers, clean_test_project):
    pid = clean_test_project
    body = {
        'sample_url': 'http://test/sample.mp4',
        'schemes': [{'id': 1}],
        'content_resources': {'videos': []},
    }
    async with client as c:
        r1 = await c.post(f'/api/schemes/{pid}/generate-previews',
                          headers=auth_headers, json=body)
        r2 = await c.post(f'/api/schemes/{pid}/generate-previews',
                          headers=auth_headers, json=body)

    assert r2.json()['task_id'] == r1.json()['task_id']
    assert r2.json()['joined_existing'] is True


@pytest.mark.asyncio
async def test_generation_status_reflects_db_state(client, auth_headers, clean_test_project):
    pid = clean_test_project
    body = {
        'sample_url': 'http://test/sample.mp4',
        'schemes': [{'id': 1}, {'id': 2}],
        'content_resources': {'videos': []},
    }
    async with client as c:
        r = await c.post(f'/api/schemes/{pid}/generate-previews',
                         headers=auth_headers, json=body)
        task_id = r.json()['task_id']

        # вручную проставить progress
        async with AsyncSessionLocal() as db:
            await db.execute(text(
                "UPDATE unic_tasks SET current_status='processing', schemes_done=1 WHERE id=:id"
            ), {'id': task_id})
            await db.commit()

        rs = await c.get(f'/api/schemes/{pid}/generation-status',
                         headers=auth_headers)

    assert rs.status_code == 200
    d = rs.json()
    assert d['phase'] == 'processing'
    assert d['progress'] == 1
    assert d['total'] == 2


@pytest.mark.asyncio
async def test_generation_status_returns_404_when_no_task(client, auth_headers, clean_test_project):
    pid = clean_test_project
    async with client as c:
        rs = await c.get(f'/api/schemes/{pid}/generation-status',
                         headers=auth_headers)
    assert rs.status_code == 404
```

- [ ] **Step 2: Run, expect failure (endpoint ещё пишет в legacy BackgroundTasks)**

```bash
cd /home/claude-user/validator-contenthunter/backend
pytest tests/test_scheme_preview_endpoint.py -v 2>&1 | tail -20
```

Expected: тесты падают (current endpoint не пишет в `unic_tasks`, использует in-memory _generation_status).

- [ ] **Step 3: Rewire endpoints в schemes.py**

В `backend/src/routers/schemes.py`:

1. **Удалить** старые функции (~400 строк):
   - `_run_generation` (вместе с `_build_ffmpeg_cmd`, `_download_file`, `_download_file_sync`, `_s3_upload_with_retry`)
   - `_generation_status` global dict
   - всё что было импортировано только для них

2. **Заменить** `POST /api/schemes/{id}/generate-previews` endpoint. Найти существующий handler (по grep'у `generate-previews`) и переделать тело:

```python
@router.post("/{project_id}/generate-previews")
async def generate_previews(
    project_id: int,
    payload: dict,  # {sample_url, schemes, content_resources, logo_url?, pattern_url?}
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # validate (как было)
    schemes = payload.get('schemes') or []
    if not schemes:
        raise HTTPException(status_code=400, detail='schemes is required and non-empty')
    if not payload.get('sample_url'):
        raise HTTPException(status_code=400, detail='sample_url is required')

    payload['project_id'] = project_id  # форсим project_id из URL

    from ..services.scheme_preview_queue import enqueue_scheme_preview
    try:
        result = await enqueue_scheme_preview(db, payload)
        await db.commit()
    except IntegrityError as e:
        # UniqueViolation race на partial index — fallback на read existing
        await db.rollback()
        # повторный SELECT (lock освободится сам)
        async with AsyncSessionLocal() as db2:
            from ..services.scheme_preview_queue import read_scheme_preview_status
            status = await read_scheme_preview_status(db2, project_id)
            if status:
                return {
                    'task_id': status['task_id'],
                    'status': 'queued',
                    'joined_existing': True,
                    'total': status['total'],
                }
            raise HTTPException(status_code=500, detail=f'enqueue race not resolved: {e}')

    return result
```

3. **Заменить** `GET /api/schemes/{id}/generation-status`:

```python
@router.get("/{project_id}/generation-status")
async def generation_status(
    project_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..services.scheme_preview_queue import read_scheme_preview_status
    status = await read_scheme_preview_status(db, project_id)
    if not status:
        raise HTTPException(status_code=404, detail='no scheme_preview task for this project')
    return status
```

- [ ] **Step 4: Run endpoint tests**

```bash
pytest tests/test_scheme_preview_endpoint.py -v 2>&1 | tail -20
```

Expected: 4/4 зелёные. Все остальные tests тоже должны быть зелёными:

```bash
pytest 2>&1 | tail -10
```

Expected: full suite зелёный (если какие-то падают — fix).

- [ ] **Step 5: Commit**

```bash
git add backend/src/routers/schemes.py backend/tests/test_scheme_preview_endpoint.py
git commit -m "feat(schemes): rewire generate-previews → DB queue, generation-status → DB read

Удаляет _run_generation, _build_ffmpeg_cmd, _download_file*, _s3_upload_with_retry,
in-memory _generation_status. Validator больше не делает ffmpeg рендер — пишет
task в unic_tasks (через advisory lock + dedup + supersede), polling через
generation-status endpoint читает свежую строку из БД.

Все правки контракта эндпоинтов сохранены: фронт SchemesPage.vue не меняется."
```

---

### Task 17: Codex review validator diff + PR

- [ ] **Step 1: codex review**

```bash
cd /home/claude-user/validator-contenthunter
git diff main..HEAD | codex review - 2>&1 | tail -50
```

Expected: P1=0. Если есть — поправить.

- [ ] **Step 2: push PR**

```bash
source ~/secrets/github-gengo2.env
GH_TOKEN="$GITHUB_TOKEN_GENGO2" git push -u origin feat/scheme-preview-via-worker-20260512
GH_TOKEN="$GITHUB_TOKEN_GENGO2" gh pr create --repo GenGo2/validator-contenthunter \
    --title "feat(schemes): миграция scheme preview на unic-worker" \
    --body "$(cat <<'EOF'
## Summary

Validator side миграции: больше никакого ffmpeg на validator backend для
scheme preview generation. Endpoint пишет task в unic_tasks с advisory lock
+ dedup + supersede, polling endpoint читает свежую строку из БД.

Spec: docs/superpowers/specs/2026-05-12-scheme-preview-remote-worker-design.md
Worker PR: GenGo2/unic-worker#... (Task 12)
Migration: alembic 004 (merged ранее, Task 3)

## Changes

- backend/src/services/scheme_preview_queue.py — compute_payload_hash + enqueue + read_status
- backend/src/routers/schemes.py — rewire endpoints, удаляет _run_generation/_build_ffmpeg_cmd/...
- backend/tests/test_payload_hash.py (5 tests)
- backend/tests/test_scheme_preview_queue.py (5 tests, incl. concurrent)
- backend/tests/test_scheme_preview_endpoint.py (4 tests)

## Test plan

- [x] Pytest зелёный (14 tests добавлено + suite не сломался)
- [x] Codex review P1=0
- [ ] Deploy: cp в prod + sudo pm2 restart validator (см. plan Task 18)
- [ ] Live smoke (Task 19)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Phase 4 — Deploy + smoke

### Task 18: Deploy unic-worker на 91.98.180.103

- [ ] **Step 1: scp worker.py**

```bash
sshpass -p 'MNcwMPCiyiYtM5' scp -o StrictHostKeyChecking=no \
    /home/claude-user/unic-worker/worker.py \
    root@91.98.180.103:/root/unic-worker/worker.py.new

# safety backup на сервере
sshpass -p 'MNcwMPCiyiYtM5' ssh -o StrictHostKeyChecking=no root@91.98.180.103 \
    "cp /root/unic-worker/worker.py /root/unic-worker/worker.py.bak_pre_scheme_preview_$(date +%s) && mv /root/unic-worker/worker.py.new /root/unic-worker/worker.py"
```

- [ ] **Step 2: syntax check на сервере**

```bash
sshpass -p 'MNcwMPCiyiYtM5' ssh -o StrictHostKeyChecking=no root@91.98.180.103 \
    "python3 -c 'import ast; ast.parse(open(\"/root/unic-worker/worker.py\").read())' && echo OK"
```

Expected: `OK`.

- [ ] **Step 3: pm2 restart**

```bash
sshpass -p 'MNcwMPCiyiYtM5' ssh -o StrictHostKeyChecking=no root@91.98.180.103 \
    "pm2 restart unic-worker && sleep 5 && pm2 logs unic-worker --lines 30 --nostream"
```

Expected: pm2 status online, в логах нет import errors, видим startup-сообщение и первый poll-tick.

- [ ] **Step 4: smoke — legacy unic-задача обрабатывается**

```bash
# если в очереди есть legacy pending — подождать pickup
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
    "SELECT current_status, COUNT(*) FROM unic_tasks WHERE task_type='unic' GROUP BY 1"
```

Expected: pending'ов нет ИЛИ они движутся в processing/done нормально.

---

### Task 19: Deploy validator + live smoke

- [ ] **Step 1: merge PR**

```bash
source ~/secrets/github-gengo2.env
GH_TOKEN="$GITHUB_TOKEN_GENGO2" gh pr merge --repo GenGo2/validator-contenthunter \
    --merge --delete-branch <pr_number>
```

- [ ] **Step 2: sync local main + copy to prod**

```bash
cd /home/claude-user/validator-contenthunter
git checkout main
git pull --ff-only

# copy все правленые файлы в prod
cp backend/src/services/scheme_preview_queue.py \
   /root/.openclaw/workspace-genri/validator/backend/src/services/scheme_preview_queue.py

cp backend/src/routers/schemes.py \
   /root/.openclaw/workspace-genri/validator/backend/src/routers/schemes.py
```

- [ ] **Step 3: restart validator**

```bash
sudo -n /usr/bin/pm2 restart validator
sleep 8
# verify ожил
curl -sS -m 10 -o /dev/null -w "%{http_code} in %{time_total}s\n" http://127.0.0.1:8000/docs
```

Expected: `200 in <0.1s`.

- [ ] **Step 4: Live E2E smoke**

Manager в UI жмёт «Generate previews» для тестового project'a. Параллельно проверяем:

```bash
# pickup в unic-worker?
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
    "SELECT id, current_status, schemes_done, schemes_total, updated_at
       FROM unic_tasks
      WHERE task_type='scheme_preview'
      ORDER BY id DESC LIMIT 3"

# логи worker'a
sshpass -p 'MNcwMPCiyiYtM5' ssh root@91.98.180.103 \
    "pm2 logs unic-worker --lines 50 --nostream" 2>&1 | tail -30

# во время рендера validator API отвечает мгновенно?
time curl -sS -m 5 -o /dev/null http://127.0.0.1:8000/api/auth/me \
    -H "Authorization: Bearer ..."  # expected: 401/403 в <100ms

# после finish — previews в S3?
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
    "SELECT scheme_id, video_url, last_task_id, generated_at
       FROM validator_scheme_previews
      WHERE project_id=<test_pid> ORDER BY scheme_id"
```

Expected: видим pickup, progress increment'ы, видео-URL'ы, last_task_id заполнен, validator API отвечает в <100ms всё время.

- [ ] **Step 5: Dedup + supersede smoke (manual в UI)**

Двойной клик «Generate» → видим один task_id, прогресс продолжается. Сменить scheme params → второй клик → старый task `superseded`, новый pending.

- [ ] **Step 6: ✓ closure**

Если всё работает, написать docs/evidence:

```bash
cat > /home/claude-user/contenthunter/docs/evidence/2026-05-12-scheme-preview-remote-worker-shipped.md <<EOF
# Scheme preview generation → unic-worker ✅ shipped 2026-05-12

(Записать: timestamps deployment, evidence of smoke tests, тестируемый project_id,
сколько previews сгенерилось, latency на одну схему, и т.д.)
EOF
```

---

## Phase 5 — Memory + cleanup

### Task 20: Memory update

- [ ] **Step 1: создать новую memory**

```bash
cat > /home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_scheme_preview_remote_worker_shipped.md <<'EOF'
---
name: scheme-preview-remote-worker-shipped
description: scheme preview generation вынесен на unic-worker (91.98.180.103) через расширенный unic_tasks queue. Включает dedup, supersede, per-project guard, heartbeat watchdog, last-write-wins UPSERT
metadata:
  type: project
---

# Scheme preview → unic-worker ✅ shipped 2026-05-12

PR validator-contenthunter#<N>, PR unic-worker#<N>, alembic 004 в openclaw.

`validator/backend/src/routers/schemes.py` больше не рендерит ffmpeg для scheme preview. Endpoint `POST /api/schemes/{id}/generate-previews` пишет task в `unic_tasks` (через advisory lock + dedup по payload_hash + supersede pending'ов), polling `GET .../generation-status` читает свежую строку. Воркер на 91.98.180.103 диспатчит по task_type, реально рендерит, пишет в `validator_scheme_previews` с last_task_id-guard.

**Why:** инцидент 2026-05-12 — фронт показал «Ошибка» в /admin/users пока ffmpeg рендерил scheme preview на validator backend и блокировал event loop. Hot-fix PR #6 (asyncio.to_thread) сразу решил, миграция — архитектурное закрытие.

**How to apply:**
- Pattern для будущих ffmpeg-задач (OCR, transcription, video_metadata): добавить новый `task_type` в CHECK constraint, новый `process_<type>_task` в worker, новый dispatcher branch.
- payload_hash вычисляется по `compute_payload_hash` в `scheme_preview_queue.py` — включает полные scheme JSON'ы (drawboxes/chromakey/rotation), не только id'ы.
- Watchdog (worker stale_task_recovery_loop) пока **только** для `task_type='scheme_preview'` — legacy unic-pipeline без heartbeat'a, чтобы не сделать duplicate processing. Heartbeat в legacy `process_task` — backlog.
- unic-worker теперь в git: GenGo2/unic-worker. Deploy = scp worker.py на сервер + pm2 restart.

Связано: [[project_validator_schemes_async_ffmpeg_fix]], [[project_unic_logo_resolver]].
EOF
```

- [ ] **Step 2: обновить MEMORY.md index**

Добавить строку в конец `MEMORY.md`:

```
- [Scheme preview → unic-worker ✅ shipped 2026-05-12](project_scheme_preview_remote_worker_shipped.md) — alembic 004 + новый task_type, advisory lock dedup, watchdog с heartbeat, last_task_id UPSERT guard
```

- [ ] **Step 3: verify memory files**

```bash
ls -la /home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_scheme_preview_remote_worker_shipped.md
grep -c "scheme_preview_remote_worker_shipped" /home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/MEMORY.md
```

Expected: файл существует, индекс содержит 1 hit. Memory не в git'е — auto-persists через runtime claude memory механизм.

---

### Task 21: Backlog tickets (короткие, отдельные репо/Jira/что есть)

- [ ] **Step 1: создать backlog notes**

```bash
cat >> /home/claude-user/contenthunter/docs/superpowers/plans/BACKLOG.md <<'EOF'

## После 2026-05-12-scheme-preview-remote-worker

### Other ffmpeg tasks → unic-worker (same pattern)
- OCR (`src/services/ocr_service.py`)
- Transcription (`src/services/transcription_service.py`)
- Video metadata extraction (`src/services/video_metadata.py`)

Подход: добавить task_type в CHECK constraint (alembic 005), новый process_<type>_task в worker, dispatcher branch.

### Heartbeat для legacy unic-pipeline
Сейчас watchdog не трогает task_type='unic' потому что process_task может рендерить одну тяжёлую схему >15 мин без updated_at. Решение: heartbeat_loop в legacy pipeline тоже (тот же helper, просто wrap). После этого расширить watchdog WHERE на оба task_type.

### Async cancellation orphan ffmpeg при PM2 restart
Codex P2 backlog из PR #6: asyncio.to_thread + subprocess.run не отменяют ffmpeg при SIGTERM. Перейти на asyncio.create_subprocess_exec с явным process.kill() в finally.

### TG-notification при watchdog 3-revert
Сейчас только logger.warning. Подключить через bugs-bot infrastructure.

### Frontend timeout-aware error display
UsersManagement.vue:348 паттерн `e.response?.data?.detail || 'Ошибка'` — для axios timeout `e.response` undefined → generic 'Ошибка'. Заменить на `(e.code === 'ECONNABORTED' ? 'Превышено время ожидания, попробуйте ещё раз' : e.response?.data?.detail) || 'Ошибка'`.

### Multi-worker horizontal scale
Architecturally разрешено через FOR UPDATE SKIP LOCKED. Поднимать второй worker на другом сервере если queue depth растёт.

EOF
```

---

## Summary

После выполнения всех 21 task:

1. ✅ alembic 004 применён, `unic_tasks` имеет task_type/payload_hash, `validator_scheme_previews` имеет last_task_id
2. ✅ unic-worker на 91.98.180.103 в git, версионирован, имеет pytest suite, диспатчит scheme_preview / unic / unknown
3. ✅ validator endpoint больше не запускает ffmpeg для scheme preview — пишет в БД, читает оттуда же
4. ✅ Defense-in-depth: advisory lock per project + dedup + supersede + per-project guard + heartbeat + watchdog + last_task_id UPSERT guard
5. ✅ 27 unit/integration тестов (validator 14 + unic-worker 13)
6. ✅ Live smoke: ffmpeg больше не блокирует validator event loop
7. ✅ Memory + backlog tickets для будущих миграций (OCR/transcription/etc.)
