# WP #115 — Признак ручной выкладки клиенту — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить клиентский (на уровне `validator_projects`) флаг «Ручная выкладка», который маршрутизирует весь контент клиента в ручную выкладку, поверх существующего послотового флага WP #85.

**Architecture:** Единый источник правды — колонка `validator_projects.manual_publish`. «Эффективная ручная выкладка» = `slot.manual_publish OR project.manual_publish` вычисляется на лету в 3 SQL-местах autowarm (через единый модуль-предикат с kill-switch). Переключение клиента ретроактивно: Авто→Ручная отзывает pending авто-контент, Ручная→Авто отменяет ещё-не-взятые ручные строки слотов, помеченных ручными только из-за клиента. UI — колонка на странице `/clients`, менять может только админ.

**Tech Stack:** Validator backend = FastAPI + SQLAlchemy(async asyncpg) + Alembic; БД `openclaw` (общая с autowarm). Validator frontend = Vue 3 + TS + Vitest. autowarm = Node.js (`pg`) + `node --test`.

**Спека:** `docs/superpowers/specs/2026-05-21-wp115-client-manual-publish-design.md`

**Репозитории (код вне docs-репо):**
- validator: `/home/claude-user/validator-contenthunter` (ветка `feat/wp107-manual-publish-queue` — содержит WP #85+#107). Для #115 завести отдельную ветку.
- autowarm: `/home/claude-user/autowarm-testbench`.
- БД для live-тестов: локальный Postgres `openclaw/openclaw123@localhost:5432/openclaw` (общий, testbench).

**Порядок:** Task 1 (миграция) — обязательный prerequisite: добавляет колонку, которую читают и backend-, и autowarm-тесты. Применить к локальной `openclaw` до остальных live-тестов.

**Схема-изменение чисто аддитивное** (новая nullable/defaulted колонка) — существующие SELECT'ы в validator/autowarm не ломает (cross-repo grep practice: DROP/rename нет).

---

## Task 1: Миграция 007 — колонка `manual_publish` на `validator_projects`

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/alembic/versions/007_wp115_client_manual_publish.py`

- [ ] **Step 1: Создать файл миграции**

```python
"""WP #115: client-level manual-publish flag on validator_projects

Revision ID: 007
Revises: 006
Create Date: 2026-05-21
"""
from alembic import op

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE validator_projects
          ADD COLUMN IF NOT EXISTS manual_publish boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS manual_publish_set_by_id integer NULL
              REFERENCES validator_users(id),
          ADD COLUMN IF NOT EXISTS manual_publish_set_at timestamp with time zone NULL;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE validator_projects
          DROP COLUMN IF EXISTS manual_publish_set_at,
          DROP COLUMN IF EXISTS manual_publish_set_by_id,
          DROP COLUMN IF EXISTS manual_publish;
    """)
```

- [ ] **Step 2: Применить миграцию к локальной БД**

Run: `cd /home/claude-user/validator-contenthunter/backend && alembic upgrade head`
Expected: `Running upgrade 006 -> 007, WP #115: client-level manual-publish flag on validator_projects`

- [ ] **Step 3: Проверить, что колонка появилась**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
"SELECT column_name, data_type, column_default FROM information_schema.columns WHERE table_name='validator_projects' AND column_name LIKE 'manual_publish%' ORDER BY 1;"
```
Expected: 3 строки — `manual_publish | boolean | false`, `manual_publish_set_at | timestamp with time zone |`, `manual_publish_set_by_id | integer |`.

- [ ] **Step 4: Проверить откат и снова накатить (sanity)**

Run: `cd /home/claude-user/validator-contenthunter/backend && alembic downgrade -1 && alembic upgrade head`
Expected: обе команды без ошибок; downgrade убирает колонки, upgrade возвращает.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/alembic/versions/007_wp115_client_manual_publish.py
git commit -m "feat(wp115): migration 007 — client-level manual_publish flag on validator_projects"
```

---

## Task 2: Сервис `apply_client_publish_mode` (запись флага + ретроактивный каскад)

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/backend/src/services/manual_publish_service.py` (добавить функцию рядом с `cancel_queued_for_slot`)
- Test: `/home/claude-user/validator-contenthunter/backend/tests/test_client_manual_publish.py` (новый)

- [ ] **Step 1: Написать падающие тесты**

Создать `backend/tests/test_client_manual_publish.py`:

```python
import pytest
import pytest_asyncio
from datetime import date
from sqlalchemy import text

from src.database import AsyncSessionLocal
from src.services.manual_publish_service import apply_client_publish_mode

# Изолированные диапазоны id (вне prod-данных)
_PID = 880115            # тестовый project_id
_SLOT = 778100           # базовый slot_id
_CONTENT = 7781000


async def _setup_project(manual_publish=False):
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM validator_projects WHERE id=:id"), {"id": _PID})
        await db.execute(text("""
            INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
            VALUES (:id, 'WP115Test', 'wp115_test', true, :mp)
        """), {"id": _PID, "mp": manual_publish})
        await db.commit()


async def _setup_slot(slot_id, content_id, status='filled', manual_publish=False):
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM validator_schedule_slots WHERE id=:id"), {"id": slot_id})
        await db.execute(text("DELETE FROM validator_content WHERE id=:id"), {"id": content_id})
        await db.execute(text("""
            INSERT INTO validator_content (id, uploader_id, project_id, content_type, title, status)
            VALUES (:cid, 1, :pid, 'video', 'wp115', 'approved')
        """), {"cid": content_id, "pid": _PID})
        await db.execute(text("""
            INSERT INTO validator_schedule_slots
              (id, project_id, slot_date, slot_position, slot_type, status, content_id, manual_publish)
            VALUES (:id, :pid, :d, 1, 'client', :st, :cid, :mp)
        """), {"id": slot_id, "pid": _PID, "d": date(2099, 2, slot_id - _SLOT + 1),
               "st": status, "cid": content_id, "mp": manual_publish})
        await db.commit()


async def _cleanup():
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            DELETE FROM validator_manual_publish_queue
            WHERE project_id=:pid
        """), {"pid": _PID})
        await db.execute(text("DELETE FROM validator_schedule_slots WHERE project_id=:pid"), {"pid": _PID})
        await db.execute(text("DELETE FROM validator_content WHERE project_id=:pid"), {"pid": _PID})
        await db.execute(text("DELETE FROM validator_projects WHERE id=:id"), {"id": _PID})
        await db.commit()


@pytest.mark.asyncio
async def test_apply_writes_flag_and_audit():
    await _setup_project(manual_publish=False)
    try:
        async with AsyncSessionLocal() as db:
            stats = await apply_client_publish_mode(db, _PID, True, user_id=1)
            await db.commit()
        assert stats["manual_publish"] is True
        assert stats["changed"] is True
        async with AsyncSessionLocal() as db:
            row = (await db.execute(text(
                "SELECT manual_publish, manual_publish_set_by_id, manual_publish_set_at "
                "FROM validator_projects WHERE id=:id"), {"id": _PID})).mappings().first()
        assert row["manual_publish"] is True
        assert row["manual_publish_set_by_id"] == 1
        assert row["manual_publish_set_at"] is not None
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_apply_idempotent_no_change():
    await _setup_project(manual_publish=True)
    try:
        async with AsyncSessionLocal() as db:
            stats = await apply_client_publish_mode(db, _PID, True, user_id=1)
            await db.commit()
        assert stats["changed"] is False
        assert stats["cancelled_publish_queue"] == 0
        assert stats["cancelled_unic_tasks"] == 0
        assert stats["cancelled_manual_queue"] == 0
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_manual_to_auto_cancels_only_client_only_manual_queue_rows():
    """Ручная→Авто: отменяем queued-строки слота с manual_publish=false,
    НЕ трогаем строки послотово-ручного слота."""
    await _setup_project(manual_publish=True)
    sid_client = _SLOT + 1     # ручной только из-за клиента
    sid_slot = _SLOT + 2       # послотово-ручной
    await _setup_slot(sid_client, _CONTENT + 1, manual_publish=False)
    await _setup_slot(sid_slot, _CONTENT + 2, manual_publish=True)
    async with AsyncSessionLocal() as db:
        for sid, cid in ((sid_client, _CONTENT + 1), (sid_slot, _CONTENT + 2)):
            await db.execute(text("""
                INSERT INTO validator_manual_publish_queue
                  (slot_id, content_id, unic_result_id, unic_task_id, project_id,
                   account_username, platform, planned_date, operator_status)
                VALUES (:sid, :cid, :urid, :utid, :pid, 'acc', 'instagram', :d, 'queued')
            """), {"sid": sid, "cid": cid, "urid": cid, "utid": cid, "pid": _PID,
                   "d": date(2099, 2, 1)})
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            stats = await apply_client_publish_mode(db, _PID, False, user_id=1)
            await db.commit()
        assert stats["changed"] is True
        assert stats["cancelled_manual_queue"] == 1   # только client-only слот
        async with AsyncSessionLocal() as db:
            client_row = (await db.execute(text(
                "SELECT cancelled_at FROM validator_manual_publish_queue WHERE slot_id=:s"),
                {"s": sid_client})).mappings().first()
            slot_row = (await db.execute(text(
                "SELECT cancelled_at FROM validator_manual_publish_queue WHERE slot_id=:s"),
                {"s": sid_slot})).mappings().first()
        assert client_row["cancelled_at"] is not None   # отменён
        assert slot_row["cancelled_at"] is None          # сохранён (послотово-ручной)
    finally:
        await _cleanup()
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_client_manual_publish.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_client_publish_mode'`.

- [ ] **Step 3: Реализовать сервис**

Добавить в `backend/src/services/manual_publish_service.py` (в конец файла):

```python
async def apply_client_publish_mode(
    db: AsyncSession,
    project_id: int,
    manual_publish: bool,
    user_id: int,
) -> dict:
    """WP #115: записать клиентский флаг ручной выкладки и ретроактивно
    перенаправить незавершённый контент.

    Caller commits (вызывается внутри транзакции эндпоинта).

    Авто→Ручная: отменяет pending авто-путь (publish_queue + unic_tasks) для
      слотов проекта, ещё не опубликованных, — контент уйдёт в ручную очередь.
    Ручная→Авто: отменяет ещё-не-взятые (queued) строки ручной очереди только
      для слотов проекта с slot.manual_publish=false (они были ручными лишь
      из-за клиента); послотово-ручные и in_progress/published сохраняются.

    Returns dict: project_id, manual_publish, changed,
                  cancelled_publish_queue, cancelled_unic_tasks, cancelled_manual_queue
    """
    cur = (await db.execute(
        text("SELECT manual_publish FROM validator_projects WHERE id = :id"),
        {"id": project_id},
    )).scalar_one_or_none()

    if cur is None:
        return {"project_id": project_id, "manual_publish": manual_publish,
                "changed": False, "cancelled_publish_queue": 0,
                "cancelled_unic_tasks": 0, "cancelled_manual_queue": 0}

    await db.execute(text("""
        UPDATE validator_projects
        SET manual_publish = :mp,
            manual_publish_set_by_id = :uid,
            manual_publish_set_at = now()
        WHERE id = :id
    """), {"mp": manual_publish, "uid": user_id, "id": project_id})

    changed = (bool(cur) != manual_publish)
    cancelled_pq = cancelled_ut = cancelled_mq = 0

    if changed and manual_publish:
        reason = f"client_manual_enabled_project_{project_id}"
        pq = await db.execute(text("""
            UPDATE publish_queue pq
            SET status = 'cancelled', skip_reason = :reason, updated_at = now()
            FROM unic_results ur
            JOIN unic_tasks ut ON ut.id = ur.task_id
            JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
            WHERE pq.unic_result_id = ur.id
              AND vss.project_id = :pid
              AND vss.status <> 'published'
              AND pq.status = 'pending'
              AND pq.publish_task_id IS NULL
            RETURNING pq.id
        """), {"reason": reason, "pid": project_id})
        cancelled_pq = len(pq.fetchall())

        ut = await db.execute(text("""
            UPDATE unic_tasks ut
            SET current_status = 'cancelled', updated_at = now(),
                error_message = COALESCE(error_message, '') || E'\\n[' || :reason || ']'
            FROM validator_schedule_slots vss
            WHERE vss.id = (ut.meta->>'slot_id')::int
              AND vss.project_id = :pid
              AND vss.status <> 'published'
              AND ut.current_status = 'pending'
            RETURNING ut.id
        """), {"reason": reason, "pid": project_id})
        cancelled_ut = len(ut.fetchall())

    elif changed and not manual_publish:
        mq = await db.execute(text("""
            UPDATE validator_manual_publish_queue q
            SET cancelled_at = now(), updated_at = now()
            WHERE q.operator_status = 'queued'
              AND q.cancelled_at IS NULL
              AND q.slot_id IN (
                  SELECT vss.id FROM validator_schedule_slots vss
                  WHERE vss.project_id = :pid AND vss.manual_publish = false
              )
            RETURNING q.id
        """), {"pid": project_id})
        cancelled_mq = len(mq.fetchall())

    return {
        "project_id": project_id,
        "manual_publish": manual_publish,
        "changed": changed,
        "cancelled_publish_queue": cancelled_pq,
        "cancelled_unic_tasks": cancelled_ut,
        "cancelled_manual_queue": cancelled_mq,
    }
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_client_manual_publish.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/services/manual_publish_service.py backend/tests/test_client_manual_publish.py
git commit -m "feat(wp115): apply_client_publish_mode service — flag write + retroactive cascade"
```

---

## Task 3: Эндпоинт `PATCH /api/projects/{id}/publish-mode` + отдача `manual_publish` в GET

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/backend/src/routers/projects.py`
- Test: `/home/claude-user/validator-contenthunter/backend/tests/test_client_manual_publish.py` (дописать)

- [ ] **Step 1: Дописать падающие тесты эндпоинта**

Добавить в конец `backend/tests/test_client_manual_publish.py`:

```python
import httpx
from src.main import app
from src.services.auth_service import create_access_token


async def _token(role: str, login: str) -> str:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT id FROM validator_users WHERE login=:l AND is_active LIMIT 1"),
            {"l": login})).mappings().first()
        if row:
            uid = row["id"]
        else:
            uid = (await db.execute(text(
                "INSERT INTO validator_users (login, password_hash, role, is_active) "
                "VALUES (:l, 'x', :r, true) ON CONFLICT (login) DO UPDATE SET is_active=true, role=:r "
                "RETURNING id"), {"l": login, "r": role})).scalar_one()
            await db.commit()
        return f"Bearer {create_access_token({'sub': str(uid), 'role': role})}"


@pytest.mark.asyncio
async def test_endpoint_admin_sets_mode():
    await _setup_project(manual_publish=False)
    try:
        tok = await _token("admin", "admin")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/api/projects/{_PID}/publish-mode",
                              json={"manual_publish": True}, headers={"Authorization": tok})
        assert r.status_code == 200, f"body={r.text}"
        assert r.json()["manual_publish"] is True
        async with AsyncSessionLocal() as db:
            mp = (await db.execute(text(
                "SELECT manual_publish FROM validator_projects WHERE id=:id"), {"id": _PID})).scalar_one()
        assert mp is True
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_endpoint_manager_403():
    await _setup_project(manual_publish=False)
    try:
        tok = await _token("manager", "manager_test_wp115")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.patch(f"/api/projects/{_PID}/publish-mode",
                              json={"manual_publish": True}, headers={"Authorization": tok})
        assert r.status_code == 403, f"got {r.status_code} body={r.text}"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM validator_users WHERE login='manager_test_wp115'"))
            await db.commit()
        await _cleanup()


@pytest.mark.asyncio
async def test_endpoint_404_unknown_project():
    tok = await _token("admin", "admin")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch("/api/projects/99090909/publish-mode",
                          json={"manual_publish": True}, headers={"Authorization": tok})
    assert r.status_code == 404, f"got {r.status_code} body={r.text}"


@pytest.mark.asyncio
async def test_get_projects_exposes_manual_publish():
    await _setup_project(manual_publish=True)
    try:
        tok = await _token("admin", "admin")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/projects", headers={"Authorization": tok})
        assert r.status_code == 200
        row = next((p for p in r.json() if p["id"] == _PID), None)
        assert row is not None and row["manual_publish"] is True
    finally:
        await _cleanup()
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_client_manual_publish.py -k endpoint -v`
Expected: FAIL — 404/405 (маршрута нет) или KeyError `manual_publish` в GET.

- [ ] **Step 3: Реализовать в `projects.py`**

Заменить блок импортов (строки 1-10) на:

```python
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..dependencies import get_current_user, require_role
from ..models.user import ValidatorUser, UserRole
from ..services.manual_publish_service import apply_client_publish_mode

router = APIRouter(prefix="/api/projects", tags=["projects"])
```

В `list_projects` (строки 26-30) добавить колонку `manual_publish` в SELECT:

```python
    result = await db.execute(text("""
        SELECT id, project, api_name, active, logo_url, manager, manual_publish
        FROM validator_projects
        ORDER BY active DESC, project ASC
    """))
    return [dict(r) for r in result.mappings().all()]
```

Добавить новый эндпоинт (после `update_project`, перед `delete_project`):

```python
class PublishModeBody(BaseModel):
    manual_publish: bool


@router.patch(
    "/{project_id}/publish-mode",
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def set_publish_mode(
    project_id: int,
    body: PublishModeBody,
    current_user: ValidatorUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """WP #115: переключить тип выкладки клиента (admin-only)."""
    if os.getenv("MANUAL_PUBLISH_TOGGLE_ENABLED", "true").lower() == "false":
        raise HTTPException(status_code=409, detail="Переключение ручной выкладки отключено")
    exists = (await db.execute(
        text("SELECT 1 FROM validator_projects WHERE id = :id"), {"id": project_id}
    )).first()
    if exists is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    stats = await apply_client_publish_mode(db, project_id, body.manual_publish, current_user.id)
    await db.commit()
    return stats
```

- [ ] **Step 4: Запустить ВСЕ тесты файла — убедиться, что проходят**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_client_manual_publish.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/routers/projects.py backend/tests/test_client_manual_publish.py
git commit -m "feat(wp115): PATCH /api/projects/{id}/publish-mode (admin-only) + expose manual_publish in GET"
```

---

## Task 4: autowarm — единый модуль-предикат `client_manual_filter.js`

**Files:**
- Create: `/home/claude-user/autowarm-testbench/client_manual_filter.js`
- Test: `/home/claude-user/autowarm-testbench/test_client_manual_filter.test.js` (новый)

- [ ] **Step 1: Написать падающие юнит-тесты**

Создать `test_client_manual_filter.test.js`:

```javascript
const { test } = require('node:test');
const assert = require('node:assert/strict');

function load() {
  delete require.cache[require.resolve('./client_manual_filter')];
  return require('./client_manual_filter');
}

test('effectiveManualSql ORs the project flag by default', () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  const { effectiveManualSql } = load();
  assert.equal(
    effectiveManualSql('vss', 'p'),
    '(vss.manual_publish = true OR p.manual_publish = true)'
  );
});

test('effectiveManualSql falls back to slot-only when kill-switch off', () => {
  process.env.CLIENT_MANUAL_PUBLISH_ENABLED = 'false';
  const { effectiveManualSql } = load();
  assert.equal(effectiveManualSql('s', 'p'), '(s.manual_publish = true)');
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
});

test('clientManualEnabled reflects env', () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  assert.equal(load().clientManualEnabled(), true);
  process.env.CLIENT_MANUAL_PUBLISH_ENABLED = 'false';
  assert.equal(load().clientManualEnabled(), false);
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
});
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_client_manual_filter.test.js`
Expected: FAIL — `Cannot find module './client_manual_filter'`.

- [ ] **Step 3: Реализовать модуль**

Создать `client_manual_filter.js`:

```javascript
'use strict';
// WP #115: client-level (validator_projects) manual-publish flag.
// "Effectively manual" = the slot's own manual_publish OR its client is manual.
// Single source of truth for the SQL predicate, reused by the auto-path guard
// (server.js assignUnicResultsToQueue), the manual-queue populator
// (manual_queue_assign.js) and the slot matcher (slot_matcher_cron.js).

// Kill-switch: CLIENT_MANUAL_PUBLISH_ENABLED=false reverts to pre-WP#115
// slot-only behavior without redeploying the validator.
function clientManualEnabled() {
  return process.env.CLIENT_MANUAL_PUBLISH_ENABLED !== 'false';
}

// Boolean SQL fragment. slotAlias = validator_schedule_slots alias;
// projAlias = validator_projects alias (caller LEFT JOINs it on
// <slotAlias>.project_id). When the kill-switch is off the project flag is
// ignored — the harmless LEFT JOIN can stay.
function effectiveManualSql(slotAlias, projAlias) {
  if (clientManualEnabled()) {
    return `(${slotAlias}.manual_publish = true OR ${projAlias}.manual_publish = true)`;
  }
  return `(${slotAlias}.manual_publish = true)`;
}

module.exports = { clientManualEnabled, effectiveManualSql };
```

- [ ] **Step 4: Запустить — убедиться, что проходят**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_client_manual_filter.test.js`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add client_manual_filter.js test_client_manual_filter.test.js
git commit -m "feat(wp115): client_manual_filter — single-source effective-manual SQL predicate + kill-switch"
```

---

## Task 5: autowarm — вплести предикат в 3 SQL-места + live-DB тесты

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/server.js` (require + auto-guard ~5989-5996)
- Modify: `/home/claude-user/autowarm-testbench/manual_queue_assign.js` (require + candidate query)
- Modify: `/home/claude-user/autowarm-testbench/slot_matcher_cron.js` (require + candidate query)
- Test: `/home/claude-user/autowarm-testbench/test_client_manual_publish.test.js` (новый)

- [ ] **Step 1: Написать падающие live-DB тесты**

Создать `test_client_manual_publish.test.js`:

```javascript
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { runSlotMatcher } = require('./slot_matcher_cron');
const { effectiveManualSql } = require('./client_manual_filter');

const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

const PID = 880116;        // client with manual_publish=true
const SLOT = 778200;       // slot with manual_publish=false (manual ONLY via client)
const CONTENT = 7782000;
const RESULT = 7782000;
const TASK = 7782000;
const POST = 9782000;
const REGACC = 9682000;
const INSTACC = 9782001;
const PACK = 96015;

async function cleanup() {
  await pool.query(`DELETE FROM validator_manual_publish_queue WHERE project_id=$1`, [PID]);
  await pool.query(`DELETE FROM publish_queue WHERE unic_result_id=$1`, [RESULT]);
  await pool.query(`DELETE FROM unic_results WHERE id=$1`, [RESULT]);
  await pool.query(`DELETE FROM unic_tasks WHERE id=$1`, [TASK]);
  await pool.query(`DELETE FROM validator_schedule_slots WHERE id=$1`, [SLOT]);
  await pool.query(`DELETE FROM validator_content WHERE id=$1`, [CONTENT]);
  await pool.query(`DELETE FROM factory_inst_reels WHERE id=$1`, [POST]);
  await pool.query(`DELETE FROM factory_inst_accounts WHERE id=$1`, [INSTACC]);
  await pool.query(`DELETE FROM factory_reg_accounts WHERE id=$1`, [REGACC]);
  await pool.query(`DELETE FROM validator_projects WHERE id=$1`, [PID]);
}

async function setup({ withPost = false } = {}) {
  await cleanup();
  // client on MANUAL, slot NOT individually manual
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,'WP115ManualClient','wp115mc',true,true)`, [PID]);
  await pool.query(`INSERT INTO validator_content (id, project_id, description, status, content_type, uploader_id)
                    VALUES ($1,$2,'Длинное описание WP115 клиентская ручная выкладка','approved','video',1)`,
                   [CONTENT, PID]);
  await pool.query(`INSERT INTO validator_schedule_slots
                    (id, project_id, slot_date, slot_position, content_id, slot_type, status, manual_publish)
                    VALUES ($1,$2, CURRENT_DATE, 1, $3, 'client', 'filled', false)`,
                   [SLOT, PID, CONTENT]);
  await pool.query(`INSERT INTO unic_tasks (id, content_id, project_id, slot_date, current_status, meta)
                    VALUES ($1,$2,$3, CURRENT_DATE, 'done', jsonb_build_object('slot_id', $4::text))`,
                   [TASK, CONTENT, PID, SLOT]);
  await pool.query(`INSERT INTO unic_results (id, task_id, scheme_id, output_url, status, created_at)
                    VALUES ($1,$2, NULL, 'https://x/out.mp4', 'ready', now())`, [RESULT, TASK]);
  if (withPost) {
    await pool.query(`INSERT INTO factory_reg_accounts (id, pack_id, platform, username, project)
                      VALUES ($1,$2,'instagram','wp115mc','WP115ManualClient') ON CONFLICT (id) DO NOTHING`,
                     [REGACC, PACK]);
    await pool.query(`INSERT INTO factory_inst_accounts (id, username, instagram_id, platform, pack_id, active)
                      VALUES ($1,'wp115mc','IG-WP115-1','instagram',$2,true) ON CONFLICT (id) DO NOTHING`,
                     [INSTACC, PACK]);
    await pool.query(`INSERT INTO factory_inst_reels (id, account_id, ig_media_id, short_code, url, caption, timestamp, platform, synced_at)
                      VALUES ($1,'IG-WP115-1','wp115mc','wp115mc','https://instagram.com/p/wp115mc',
                              'Длинное описание WP115 клиентская ручная выкладка', $2, 'instagram', now())
                      ON CONFLICT (id) DO NOTHING`, [POST, new Date().toISOString()]);
  }
}

before(async () => { await setup(); });
after(async () => { await cleanup(); await pool.end(); });

// AUTO-GUARD: client-manual slot must be EXCLUDED from the auto path.
// (contract test of the assignUnicResultsToQueue NOT EXISTS guard — keep in sync with server.js)
test('auto-path guard excludes a client-manual slot', async () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  const { rows } = await pool.query(`
    SELECT ur.id FROM unic_results ur
    JOIN unic_tasks ut ON ut.id = ur.task_id
    WHERE ur.id = $1
      AND NOT EXISTS (
        SELECT 1 FROM validator_schedule_slots vss
        LEFT JOIN validator_projects p ON p.id = vss.project_id
        WHERE vss.id = (ut.meta->>'slot_id')::int
          AND ${effectiveManualSql('vss', 'p')}
      )
  `, [RESULT]);
  assert.equal(rows.length, 0, 'client-manual result must NOT be eligible for auto');
});

// MANUAL POPULATOR: candidate SELECT must INCLUDE the client-manual slot.
// (contract test of the assignManualPublishQueue candidate query — keep in sync)
test('manual-queue candidate query includes a client-manual slot', async () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  const { rows } = await pool.query(`
    SELECT ur.id FROM unic_results ur
    JOIN unic_tasks ut ON ut.id = ur.task_id
    JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
    LEFT JOIN validator_projects p ON p.id = vss.project_id
    WHERE ur.id = $1 AND ur.status IN ('ready','done')
      AND ${effectiveManualSql('vss', 'p')}
  `, [RESULT]);
  assert.equal(rows.length, 1, 'client-manual result must be a manual candidate');
});

// KILL-SWITCH OFF: with the project flag ignored, a non-manual slot is auto again.
test('kill-switch off: client-manual slot is NOT a manual candidate', async () => {
  process.env.CLIENT_MANUAL_PUBLISH_ENABLED = 'false';
  const { rows } = await pool.query(`
    SELECT ur.id FROM unic_results ur
    JOIN unic_tasks ut ON ut.id = ur.task_id
    JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
    LEFT JOIN validator_projects p ON p.id = vss.project_id
    WHERE ur.id = $1 AND ${effectiveManualSql('vss', 'p')}
  `, [RESULT]);
  assert.equal(rows.length, 0, 'with kill-switch off, non-manual slot is not manual');
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
});

// MATCHER (end-to-end real function): client-manual slot must be matchable.
test('runSlotMatcher matches a client-manual slot to a fresh post', async () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  await setup({ withPost: true });
  await runSlotMatcher(pool, { windowDays: 3, similarityMin: 0.7, batch: 200 });
  const { rows } = await pool.query(
    `SELECT matched_at FROM validator_schedule_slots WHERE id=$1`, [SLOT]);
  assert.ok(rows[0].matched_at !== null, 'client-manual slot should be matched');
});
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_client_manual_publish.test.js`
Expected: FAIL — матчер ещё игнорирует `p.manual_publish`, поэтому `matched_at` остаётся NULL (тест матчера падает). Контракт-тесты используют helper и пройдут сразу, но матчер-тест — нет, пока не пропатчен `slot_matcher_cron.js`.

- [ ] **Step 3: Пропатчить `slot_matcher_cron.js`**

Добавить require после строки 4 (`const { normalizeText, matchScore } = require('./slot_matcher');`):

```javascript
const { effectiveManualSql } = require('./client_manual_filter');
```

В финальном SELECT (строки 55-60) добавить LEFT JOIN и заменить условие. Было:

```javascript
    FROM account_projects acp
    JOIN validator_schedule_slots s ON s.project_id = acp.project_id
    JOIN validator_content c ON c.id = s.content_id
    WHERE s.content_id IS NOT NULL
      AND s.matched_at IS NULL
      AND (s.manual_publish = true OR s.status = 'published')
```

Стало:

```javascript
    FROM account_projects acp
    JOIN validator_schedule_slots s ON s.project_id = acp.project_id
    JOIN validator_content c ON c.id = s.content_id
    LEFT JOIN validator_projects p ON p.id = s.project_id
    WHERE s.content_id IS NOT NULL
      AND s.matched_at IS NULL
      AND (${effectiveManualSql('s', 'p')} OR s.status = 'published')
```

- [ ] **Step 4: Пропатчить `manual_queue_assign.js`**

Добавить require после строки 2 (`const { resolvePackForScheme, ... } = require('./queue_pairing');`):

```javascript
const { effectiveManualSql } = require('./client_manual_filter');
```

В candidate-query (строки 21-25) добавить LEFT JOIN и заменить условие. Было:

```javascript
      FROM unic_results ur
      JOIN unic_tasks ut ON ut.id = ur.task_id
      JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
      WHERE ur.status IN ('ready','done')
        AND vss.manual_publish = true
```

Стало:

```javascript
      FROM unic_results ur
      JOIN unic_tasks ut ON ut.id = ur.task_id
      JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
      LEFT JOIN validator_projects p ON p.id = vss.project_id
      WHERE ur.status IN ('ready','done')
        AND ${effectiveManualSql('vss', 'p')}
```

- [ ] **Step 5: Пропатчить auto-guard в `server.js`**

Добавить require рядом с `require('./manual_queue_assign')` (строка 15 на origin/main):

```javascript
const { effectiveManualSql } = require('./client_manual_filter');
```

Заменить guard-подзапрос (строки 6027-6031 на origin/main; блок совпадает байт-в-байт). Было:

```javascript
        AND NOT EXISTS (
          SELECT 1 FROM validator_schedule_slots vss
          WHERE vss.id = (ut.meta->>'slot_id')::int
            AND vss.manual_publish = true
        )
```

Стало:

```javascript
        AND NOT EXISTS (
          SELECT 1 FROM validator_schedule_slots vss
          LEFT JOIN validator_projects p ON p.id = vss.project_id
          WHERE vss.id = (ut.meta->>'slot_id')::int
            AND ${effectiveManualSql('vss', 'p')}
        )
```

- [ ] **Step 6: Запустить live-DB тесты — убедиться, что проходят**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_client_manual_publish.test.js`
Expected: 4 passed (auto-guard exclude, manual candidate include, kill-switch off, matcher matches).

- [ ] **Step 7: Прогнать существующий matcher-тест (регрессия)**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_slot_matcher.test.js`
Expected: PASS (без регрессий — добавленный LEFT JOIN не меняет поведение для послотово-ручных слотов).

- [ ] **Step 8: Проверить, что server.js парсится (синтаксис шаблонной строки)**

Run: `cd /home/claude-user/autowarm-testbench && node --check server.js`
Expected: без вывода (синтаксис ок).

- [ ] **Step 9: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add server.js manual_queue_assign.js slot_matcher_cron.js test_client_manual_publish.test.js
git commit -m "feat(wp115): weave client manual-publish flag into auto-guard, manual populator, matcher"
```

---

## Task 6: Frontend — презентационный компонент `ProjectPublishModeCell.vue`

**Files:**
- Create: `/home/claude-user/validator-contenthunter/frontend/src/components/admin/ProjectPublishModeCell.vue`
- Test: `/home/claude-user/validator-contenthunter/frontend/src/components/admin/__tests__/ProjectPublishModeCell.spec.ts` (новый)

- [ ] **Step 1: Написать падающий Vitest-спек**

Создать `frontend/src/components/admin/__tests__/ProjectPublishModeCell.spec.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProjectPublishModeCell from '../ProjectPublishModeCell.vue'

describe('ProjectPublishModeCell (WP #115)', () => {
  it('shows auto badge when manualPublish=false', () => {
    const w = mount(ProjectPublishModeCell, { props: { manualPublish: false, isAdmin: false } })
    expect(w.text()).toContain('Автовыкладка')
    expect(w.text()).not.toContain('Ручная выкладка')
  })

  it('shows manual badge when manualPublish=true', () => {
    const w = mount(ProjectPublishModeCell, { props: { manualPublish: true, isAdmin: false } })
    expect(w.text()).toContain('Ручная выкладка')
  })

  it('non-admin has no clickable button', () => {
    const w = mount(ProjectPublishModeCell, { props: { manualPublish: false, isAdmin: false } })
    expect(w.find('button').exists()).toBe(false)
  })

  it('admin sees a clickable button and emits toggle with the next value', async () => {
    const w = mount(ProjectPublishModeCell, { props: { manualPublish: false, isAdmin: true } })
    const btn = w.find('button')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(w.emitted().toggle).toBeTruthy()
    expect((w.emitted().toggle![0] as any[])[0]).toBe(true)  // false -> request true
  })

  it('admin toggle from manual emits false', async () => {
    const w = mount(ProjectPublishModeCell, { props: { manualPublish: true, isAdmin: true } })
    await w.find('button').trigger('click')
    expect((w.emitted().toggle![0] as any[])[0]).toBe(false)
  })
})
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vitest run src/components/admin/__tests__/ProjectPublishModeCell.spec.ts`
Expected: FAIL — компонент не существует.

- [ ] **Step 3: Реализовать компонент**

Создать `frontend/src/components/admin/ProjectPublishModeCell.vue`:

```vue
<template>
  <button
    v-if="isAdmin"
    @click.stop="$emit('toggle', !manualPublish)"
    :title="manualPublish ? 'Переключить на автовыкладку' : 'Переключить на ручную выкладку'"
    class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium transition-colors"
    :class="manualPublish ? 'bg-purple-100 text-purple-700 hover:bg-purple-200'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'"
  >
    {{ manualPublish ? '✋ Ручная выкладка' : '🤖 Автовыкладка' }}
  </button>
  <span
    v-else
    class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
    :class="manualPublish ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'"
  >
    {{ manualPublish ? '✋ Ручная выкладка' : '🤖 Автовыкладка' }}
  </span>
</template>

<script setup lang="ts">
defineProps<{ manualPublish: boolean; isAdmin: boolean }>()
defineEmits<{ (e: 'toggle', next: boolean): void }>()
</script>
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vitest run src/components/admin/__tests__/ProjectPublishModeCell.spec.ts`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/components/admin/ProjectPublishModeCell.vue frontend/src/components/admin/__tests__/ProjectPublishModeCell.spec.ts
git commit -m "feat(wp115): ProjectPublishModeCell — publish-type badge/toggle component"
```

---

## Task 7: Frontend — вплести колонку «Тип выкладки» в `ProjectsPage.vue`

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/frontend/src/pages/admin/ProjectsPage.vue`

Изменения охватывают: `Project` интерфейс, импорт auth-стора и компонента-ячейки, заголовок колонки, ячейку, модалку подтверждения, обработчик переключения, `colspan`. Логика переключения покрыта тестами backend (Task 3) + компонента (Task 6); проводка проверяется на e2e-смоуке (Task 8).

- [ ] **Step 1: Добавить импорты и поле интерфейса**

В `<script setup>` после строки `import api from '@/api/client'` добавить:

```typescript
import { useAuthStore } from '@/stores/auth'
import ProjectPublishModeCell from '@/components/admin/ProjectPublishModeCell.vue'

const auth = useAuthStore()
```

В интерфейс `Project` добавить поле:

```typescript
interface Project {
  id: number
  project: string
  api_name: string
  active: boolean
  logo_url: string | null
  manager: string | null
  manual_publish: boolean
}
```

- [ ] **Step 2: Добавить состояние модалки подтверждения и обработчик**

В блоке модалок (после `const deleteModal = reactive(...)`, ~строка 270) добавить:

```typescript
const publishModal = reactive({ show: false, project: null as Project | null })

function requestToggle(p: Project, next: boolean) {
  if (next) {
    // включение ручной выкладки ретроактивно отзывает авто-контент — подтверждаем
    publishModal.project = p
    publishModal.show = true
  } else {
    applyPublishMode(p, false)
  }
}

async function applyPublishMode(p: Project, next: boolean) {
  saving.value = true
  try {
    await api.patch(`/projects/${p.id}/publish-mode`, { manual_publish: next })
    const idx = projects.value.findIndex(x => x.id === p.id)
    if (idx >= 0) projects.value[idx].manual_publish = next
    publishModal.show = false
  } finally { saving.value = false }
}

function confirmPublishManual() {
  if (publishModal.project) applyPublishMode(publishModal.project, true)
}
```

- [ ] **Step 3: Добавить заголовок колонки**

В строку заголовков (после `<th ...>Менеджер ...</th>`, ~строка 30) добавить:

```html
              <th class="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-40">Тип выкладки</th>
```

В строку фильтров (после ячейки фильтра менеджера, ~строка 54) добавить пустую ячейку, чтобы колонки не разъехались:

```html
              <td class="px-2 py-2"></td>
```

- [ ] **Step 4: Добавить ячейку в строку данных**

В `<tr v-for="p in processed">` после ячейки менеджера (`<td ...>{{ p.manager || '—' }}</td>`, ~строка 83) добавить:

```html
              <td class="px-4 py-3">
                <ProjectPublishModeCell
                  :manual-publish="!!p.manual_publish"
                  :is-admin="auth.isAdmin"
                  @toggle="(next: boolean) => requestToggle(p, next)"
                />
              </td>
```

- [ ] **Step 5: Обновить colspan пустой строки**

Заменить `<td colspan="7" ...>Ничего не найдено</td>` (~строка 100) на `colspan="8"`.

- [ ] **Step 6: Добавить модалку подтверждения**

Перед закрывающим `</template>` (после модалки удаления, ~строка 185) добавить:

```html
    <!-- Модал: подтверждение перевода клиента в ручную выкладку -->
    <Teleport to="body">
      <div v-if="publishModal.show" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/40" @click="publishModal.show = false"></div>
        <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-sm p-6">
          <div class="flex items-center gap-3 mb-4">
            <div class="w-10 h-10 bg-purple-100 rounded-full flex items-center justify-center text-xl">✋</div>
            <h3 class="text-lg font-bold text-gray-800">Ручная выкладка клиента?</h3>
          </div>
          <p class="text-gray-600 text-sm mb-6">
            Весь неопубликованный контент клиента
            <span class="font-semibold text-gray-800">«{{ publishModal.project?.project }}»</span>
            будет перенаправлен в ручную выкладку. Продолжить?
          </p>
          <div class="flex gap-3">
            <button @click="confirmPublishManual" :disabled="saving"
              class="flex-1 px-4 py-2.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-60 text-white font-medium rounded-lg transition-colors text-sm">
              {{ saving ? 'Применение...' : 'Да, в ручную' }}
            </button>
            <button @click="publishModal.show = false"
              class="flex-1 px-4 py-2.5 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-colors text-sm">
              Отмена
            </button>
          </div>
        </div>
      </div>
    </Teleport>
```

- [ ] **Step 7: Прогнать сборку фронта (типы + bundle)**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vue-tsc --noEmit && npx vitest run`
Expected: типы без ошибок; все vitest-спеки зелёные.

> ⚠️ ВНИМАНИЕ: `npm run build` имеет postbuild-хук, который КОПИРУЕТ результат в `/var/www/validator/` (автодеплой). На этом шаге используем `vue-tsc --noEmit`, НЕ `npm run build`, чтобы не задеплоить раньше времени.

- [ ] **Step 8: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/pages/admin/ProjectsPage.vue
git commit -m "feat(wp115): /clients — publish-type column with admin toggle + confirm modal"
```

---

## Task 8: E2E smoke на testbench + финальная верификация

**Files:** нет (проверочный прогон против живой БД)

- [ ] **Step 1: Прогнать все backend-тесты файла**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_client_manual_publish.py -v`
Expected: 7 passed.

- [ ] **Step 2: Прогнать все autowarm-тесты WP #115 + регрессия**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_client_manual_filter.test.js test_client_manual_publish.test.js test_slot_matcher.test.js`
Expected: всё зелёное (3 + 4 + существующие matcher-тесты).

- [ ] **Step 3: E2E — перевод клиента в «Ручную» через API, проверка отзыва**

Подготовить тестовый проект с pending авто-контентом, затем:

```bash
# 1) найти реальный admin-токен (или создать) и project_id с pending publish_queue
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
"SELECT vss.project_id, count(*) FROM publish_queue pq
 JOIN unic_results ur ON ur.id=pq.unic_result_id
 JOIN unic_tasks ut ON ut.id=ur.task_id
 JOIN validator_schedule_slots vss ON vss.id=(ut.meta->>'slot_id')::int
 WHERE pq.status='pending' AND pq.publish_task_id IS NULL AND vss.status<>'published'
 GROUP BY vss.project_id ORDER BY 2 DESC LIMIT 5;"
```

Зафиксировать `before` (кол-во pending авто-строк проекта), вызвать `PATCH /api/projects/{id}/publish-mode {manual_publish:true}` с admin-токеном, затем проверить, что эти строки `publish_queue.status='cancelled'`, а соответствующие слоты на следующем тике `assignManualPublishQueue` попадают в `validator_manual_publish_queue`. Вернуть проект в авто и убедиться, что queued-строки ручной очереди (для слотов с `manual_publish=false`) отменены.

> ⚠️ Использовать НЕпродовый/тестовый проект, чтобы не зацепить реальный контент клиентов. Если такого нет — создать как в backend-тестах (project id 880115 + слот + unic-линия с одной pending publish_queue строкой) и прогнать сценарий вручную, затем удалить.

Expected: pending авто-строки → `cancelled`; ручная очередь наполняется; обратный перевод отменяет client-only queued-строки.

- [ ] **Step 4: Зафиксировать smoke-эвиденс**

Создать `docs/evidence/wp115_smoke_2026-05-21.md` в docs-репо с выводом проверок (counts before/after).

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/wp115_smoke_2026-05-21.md
git commit -m "docs(evidence): WP #115 e2e smoke — client manual-publish reroute verified"
```

- [ ] **Step 5: Финальный отчёт** — свести: какие PR (validator + autowarm), какие миграции, env kill-switches (`CLIENT_MANUAL_PUBLISH_ENABLED`, `MANUAL_PUBLISH_TOGGLE_ENABLED`), порядок деплоя (см. спеку §12), и риск-проверка прод-`server.js` на подключённость `assignManualPublishQueue`.

---

## Deploy (после прохождения всех тестов — выполняет Данил)

Порядок (см. спеку §12):
1. **Validator backend:** `git pull` в prod-чекаут → `alembic upgrade head` (007) → перезапуск PM2 `validator` (id=24). Systemd `validator-backend.service` оставить **disabled** (порт-конфликт).
2. **Validator frontend:** `npm run build` (postbuild автодеплой во `/var/www/validator/`). Юзерам — hard reload (stale-bundle).
3. **autowarm:** `git pull` → `pm2 restart autowarm`.
4. Env по умолчанию всё включено. Kill-switches: `CLIENT_MANUAL_PUBLISH_ENABLED=false` (autowarm) — откат на послотовое поведение; `MANUAL_PUBLISH_TOGGLE_ENABLED=false` (validator) — блок новых переключений.
   - ⚠️ **Согласованность:** эти два флага в разных процессах. Выключая `CLIENT_MANUAL_PUBLISH_ENABLED` в autowarm, ОБЯЗАТЕЛЬНО ставь `MANUAL_PUBLISH_TOGGLE_ENABLED=false` на валидаторе и предварительно верни ручных клиентов в «Авто» — иначе валидатор отменит авто-контент, а autowarm не подхватит его в ручную (контент застрянет). Деталь — спека §10.
5. **ПРОВЕРИТЬ перед раскаткой:** в прод-`server.js` подключён ли `assignManualPublishQueue` в шедулер (деплой-зависимость WP #107) — иначе ручной контент клиента не дойдёт до очереди.

---

## Self-review checklist (заполняется при написании плана)

- **Spec coverage:** §5 схема → Task 1; §6 autowarm 3 SQL → Task 4+5; §7 эндпоинт+сервис+каскад → Task 2+3; §8 UI /clients → Task 6+7; §9 RBAC → Task 3 (admin-only) + Task 6 (isAdmin); §10 kill-switches → Task 3 (`MANUAL_PUBLISH_TOGGLE_ENABLED`) + Task 4 (`CLIENT_MANUAL_PUBLISH_ENABLED`); §11 тесты → каждый Task + Task 8; §12 деплой → раздел Deploy. Сериализатор `_slot_to_dict` (§7, опционально) НЕ включён — помечен в спеке как nice-to-have, вне MVP.
- **Type consistency:** `apply_client_publish_mode(db, project_id, manual_publish, user_id)` — единая сигнатура в Task 2 (определение), Task 3 (вызов). `effectiveManualSql(slotAlias, projAlias)` — Task 4 (опр.), Task 5 (3 вызова). Поле ответа `manual_publish`/`changed`/`cancelled_*` — едино в сервисе и тестах. Компонент `ProjectPublishModeCell` props `manualPublish`/`isAdmin`, emit `toggle` — едины в Task 6 и Task 7.
- **No placeholders:** все шаги содержат конкретный код/команды/ожидаемый вывод.
