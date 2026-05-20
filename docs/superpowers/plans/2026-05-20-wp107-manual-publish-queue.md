# WP #107 — Manual Publishing Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an admin-only operator queue that turns uniqualized videos for manual-publish slots into ready-to-publish rows (one video × account × platform), with a sortable/filterable/grouped table and a publication card.

**Architecture:** New `validator_manual_publish_queue` table in the shared `openclaw` DB, populated by an autowarm sibling cron (`assignManualPublishQueue`, reuses the canonical scheme→pack→account→device pairing). The validator backend owns the operator status state-machine + admin-only REST API; the validator frontend owns the table + card UI. The table is physically isolated from `publish_queue` (the auto-dispatch table) so manual rows can never be auto-published.

**Tech Stack:** PostgreSQL + Alembic (raw-SQL migrations), FastAPI + SQLAlchemy async (validator backend), Vue 3 + TypeScript + Tailwind + Vitest (validator frontend), Node.js + `pg` Pool + `node --test` (autowarm).

**Spec:** `docs/superpowers/specs/2026-05-20-wp107-manual-publish-queue-design.md`

**Repos & branches (Phase 0 creates these):**
- validator: `/home/claude-user/validator-contenthunter` → branch `feat/wp107-manual-publish-queue`
- autowarm: `/home/claude-user/autowarm-testbench` → branch `feat/wp107-manual-publish-queue`

**Conventions:**
- Each commit message ends with the standard footer:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- `git fetch origin` + branch off `origin/main` before starting (parallel sessions run on `main`).
- Backend tests are **live-DB** (hit the real `openclaw`): `cd backend && python -m pytest`. The autouse `engine.dispose()` fixture in `backend/tests/conftest.py` is mandatory — do not remove it.
- Do NOT push to prod or run prod deploys. Deploy is done separately by Danil (see Phase 4).

---

## File Structure

**validator backend** (`/home/claude-user/validator-contenthunter/backend`):
- Create `alembic/versions/006_wp107_manual_publish_queue.py` — table + CHECK enum + indexes
- Create `src/models/manual_publish.py` — `ValidatorManualPublishQueue` model + `ManualPubStatus`
- Modify `src/models/__init__.py` — export the model
- Create `src/services/manual_publish_service.py` — serializer, joins, transitions, `account_profile_url`, `cancel_queued_for_slot`
- Create `src/routers/manual_publish.py` — admin-only endpoints
- Modify `src/main.py` — register router
- Modify `src/routers/schedule.py` — toggle-OFF cancels queued rows
- Create `tests/test_manual_publish_queue.py` — pytest

**validator frontend** (`/home/claude-user/validator-contenthunter/frontend`):
- Create `src/utils/clipboard.ts` — extracted copy helper
- Create `src/utils/accountUrl.ts` — profile-URL helper
- Create `src/utils/datetimeMsk.ts` — MSK input/format helpers
- Create `src/api/manualPublish.ts` — API module + `ManualPublishRow` type
- Create `src/composables/useManualPublishTable.ts` — sort/filter/group logic
- Create `tests/useManualPublishTable.spec.ts` — Vitest
- Create `src/pages/admin/ManualPublishingQueue.vue` — table page
- Create `src/components/manual-publish/PublicationCard.vue` — card dialog
- Modify `src/router/index.ts` — add `/manual-publish` route
- Modify `src/components/layout/AppSidebar.vue` — add «Выкладка» section

**autowarm** (`/home/claude-user/autowarm-testbench`):
- Create `queue_pairing.js` — shared resolution helpers
- Create `manual_queue_assign.js` — `assignManualPublishQueue`
- Modify `server.js` — wire interval + kill-switch; refactor `assignUnicResultsToQueue` to use helpers
- Create `test_queue_pairing.test.js` — node tests for helpers
- Create `test_manual_queue_assign.test.js` — node tests for populator

---

## Phase 0: Branch setup

### Task 0: Create feature branches in both code repos

**Files:** none (git only)

- [ ] **Step 1: validator branch off origin/main**

```bash
cd /home/claude-user/validator-contenthunter
git fetch origin
git checkout -b feat/wp107-manual-publish-queue origin/main
git branch --show-current   # expect: feat/wp107-manual-publish-queue
```

- [ ] **Step 2: autowarm branch off origin/main**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git checkout -b feat/wp107-manual-publish-queue origin/main
git branch --show-current   # expect: feat/wp107-manual-publish-queue
```

---

## Phase 1: Validator backend

### Task 1: Migration — `validator_manual_publish_queue`

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/alembic/versions/006_wp107_manual_publish_queue.py`

- [ ] **Step 1: Write the migration**

```python
"""WP #107: manual publish queue (operator-facing)

Revision ID: 006
Revises: 005
Create Date: 2026-05-20
"""
from alembic import op

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS validator_manual_publish_queue (
            id                serial PRIMARY KEY,
            slot_id           integer NOT NULL REFERENCES validator_schedule_slots(id),
            content_id        integer NOT NULL,
            unic_result_id    integer NOT NULL,
            unic_task_id      integer NOT NULL,
            scheme_id         integer NULL,
            project_id        integer NOT NULL,
            project_name      text NULL,
            pack_id           integer NULL,
            pack_name         text NULL,
            account_id        integer NULL,
            account_username  text NOT NULL,
            platform          text NOT NULL,
            device_serial     text NULL,
            raspberry_number  integer NULL,
            phone_number      integer NULL,
            planned_date      date NOT NULL,
            operator_status   text NOT NULL DEFAULT 'queued',
            taken_by_id       integer NULL REFERENCES validator_users(id),
            taken_at          timestamptz NULL,
            published_by_id   integer NULL REFERENCES validator_users(id),
            published_at      timestamptz NULL,
            post_url          text NULL,
            cancelled_at      timestamptz NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_manual_pub_status
                CHECK (operator_status IN ('queued','in_progress','published'))
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_manual_pub_result_account
          ON validator_manual_publish_queue (unic_result_id, account_username, platform)
          WHERE cancelled_at IS NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_manual_pub_active
          ON validator_manual_publish_queue (operator_status, planned_date)
          WHERE cancelled_at IS NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_manual_pub_slot
          ON validator_manual_publish_queue (slot_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_manual_pub_phone
          ON validator_manual_publish_queue (phone_number, planned_date)
          WHERE cancelled_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS validator_manual_publish_queue;")
```

- [ ] **Step 2: Apply the migration**

Run:
```bash
cd /home/claude-user/validator-contenthunter/backend
python -m alembic upgrade head
```
Expected: `Running upgrade 005 -> 006, WP #107: manual publish queue`.

- [ ] **Step 3: Verify table + constraint exist**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d validator_manual_publish_queue"
```
Expected: table prints with `ck_manual_pub_status` check and the 4 indexes.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/006_wp107_manual_publish_queue.py
git commit -m "feat(wp107): migration 006 validator_manual_publish_queue"
```

---

### Task 2: SQLAlchemy model

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/src/models/manual_publish.py`
- Modify: `/home/claude-user/validator-contenthunter/backend/src/models/__init__.py`

- [ ] **Step 1: Write the model**

`src/models/manual_publish.py`:
```python
import enum
from sqlalchemy import Column, Integer, Text, Date, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class ManualPubStatus(str, enum.Enum):
    queued = "queued"
    in_progress = "in_progress"
    published = "published"


class ValidatorManualPublishQueue(Base):
    __tablename__ = "validator_manual_publish_queue"

    id = Column(Integer, primary_key=True, index=True)
    slot_id = Column(Integer, ForeignKey("validator_schedule_slots.id"), nullable=False)
    content_id = Column(Integer, nullable=False)
    unic_result_id = Column(Integer, nullable=False)
    unic_task_id = Column(Integer, nullable=False)
    scheme_id = Column(Integer, nullable=True)
    project_id = Column(Integer, nullable=False)
    project_name = Column(Text, nullable=True)
    pack_id = Column(Integer, nullable=True)
    pack_name = Column(Text, nullable=True)
    account_id = Column(Integer, nullable=True)
    account_username = Column(Text, nullable=False)
    platform = Column(Text, nullable=False)
    device_serial = Column(Text, nullable=True)
    raspberry_number = Column(Integer, nullable=True)
    phone_number = Column(Integer, nullable=True)
    planned_date = Column(Date, nullable=False)
    operator_status = Column(Text, nullable=False, default=ManualPubStatus.queued.value)
    taken_by_id = Column(Integer, ForeignKey("validator_users.id"), nullable=True)
    taken_at = Column(DateTime(timezone=True), nullable=True)
    published_by_id = Column(Integer, ForeignKey("validator_users.id"), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    post_url = Column(Text, nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 2: Export it**

In `src/models/__init__.py` add the import and `__all__` entry:
```python
from .manual_publish import ValidatorManualPublishQueue, ManualPubStatus
```
and add `"ValidatorManualPublishQueue"` and `"ManualPubStatus"` to `__all__`.

- [ ] **Step 3: Verify it imports**

Run:
```bash
cd /home/claude-user/validator-contenthunter/backend
python -c "from src.models import ValidatorManualPublishQueue, ManualPubStatus; print(ManualPubStatus.queued.value)"
```
Expected: `queued`

- [ ] **Step 4: Commit**

```bash
git add backend/src/models/manual_publish.py backend/src/models/__init__.py
git commit -m "feat(wp107): ValidatorManualPublishQueue model"
```

---

### Task 3: Service — serializer, account URL, transitions, cancel

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/src/services/manual_publish_service.py`

- [ ] **Step 1: Write the service**

`src/services/manual_publish_service.py`:
```python
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.manual_publish import ValidatorManualPublishQueue, ManualPubStatus


def account_profile_url(platform: str | None, username: str | None) -> str | None:
    if not username:
        return None
    u = username.lstrip("@")
    p = (platform or "").lower()
    if p == "instagram":
        return f"https://instagram.com/{u}"
    if p == "tiktok":
        return f"https://www.tiktok.com/@{u}"
    if p == "youtube":
        return f"https://www.youtube.com/@{u}"
    return None


def _iso(v):
    return v.isoformat() if v is not None else None


def _row_to_dict(m) -> dict:
    """m is a SQLAlchemy RowMapping from the joined list/get query."""
    post_url = m["post_url"]
    matched_post_url = m["matched_post_url"]
    published_at = m["published_at"]
    matched_at = m["matched_at"]
    return {
        "id": m["id"],
        "slot_id": m["slot_id"],
        "content_id": m["content_id"],
        "scheme_id": m["scheme_id"],
        "project_id": m["project_id"],
        "project_name": m["project_name"],
        "pack_id": m["pack_id"],
        "pack_name": m["pack_name"],
        "account_username": m["account_username"],
        "account_url": account_profile_url(m["platform"], m["account_username"]),
        "platform": m["platform"],
        "phone_number": m["phone_number"],
        "device_serial": m["device_serial"],
        "planned_date": _iso(m["planned_date"]),
        "operator_status": m["operator_status"],
        "title": m["title"],
        "description": m["description"],
        "hashtags": m["hashtags"] or [],
        "geo": m["geo"],
        "source_video_url": m["source_video_url"],
        "unic_video_url": m["unic_video_url"],
        "post_url": post_url,
        "matched_post_url": matched_post_url,
        "published_at": _iso(published_at),
        "matched_at": _iso(matched_at),
        # convenience for the «Публикация» column / card:
        "publication_url": post_url or matched_post_url,
        "publication_at": _iso(published_at or matched_at),
        "taken_by_id": m["taken_by_id"],
        "taken_by": m["taken_by_login"],
        "published_by_id": m["published_by_id"],
        "published_by": m["published_by_login"],
    }


_JOINED_SELECT = """
    SELECT q.id, q.slot_id, q.content_id, q.scheme_id, q.project_id, q.project_name,
           q.pack_id, q.pack_name, q.account_username, q.platform, q.phone_number,
           q.device_serial, q.planned_date, q.operator_status, q.post_url,
           q.published_at, q.taken_by_id, q.published_by_id,
           vc.title, vc.description, vc.hashtags, vc.geo,
           vc.s3_url       AS source_video_url,
           ur.output_url   AS unic_video_url,
           s.matched_post_url, s.matched_at,
           tu.login        AS taken_by_login,
           pu.login        AS published_by_login
    FROM validator_manual_publish_queue q
    LEFT JOIN validator_content vc        ON vc.id = q.content_id
    LEFT JOIN unic_results ur             ON ur.id = q.unic_result_id
    LEFT JOIN validator_schedule_slots s  ON s.id  = q.slot_id
    LEFT JOIN validator_users tu          ON tu.id = q.taken_by_id
    LEFT JOIN validator_users pu          ON pu.id = q.published_by_id
"""


async def list_queue(db: AsyncSession, status: str | None = None) -> list[dict]:
    sql = _JOINED_SELECT + """
        WHERE q.cancelled_at IS NULL
          AND (:status IS NULL OR q.operator_status = :status)
        ORDER BY q.planned_date ASC, q.phone_number ASC, q.id ASC
    """
    rows = (await db.execute(text(sql), {"status": status})).mappings().all()
    return [_row_to_dict(m) for m in rows]


async def get_item(db: AsyncSession, item_id: int) -> dict:
    sql = _JOINED_SELECT + " WHERE q.id = :id"
    m = (await db.execute(text(sql), {"id": item_id})).mappings().first()
    if not m:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return _row_to_dict(m)


async def _load_for_update(db: AsyncSession, item_id: int) -> ValidatorManualPublishQueue:
    row = (await db.execute(
        select(ValidatorManualPublishQueue)
        .where(ValidatorManualPublishQueue.id == item_id)
        .with_for_update()
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found")
    if row.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Queue item is cancelled")
    return row


def _require_status(row: ValidatorManualPublishQueue, expected: ManualPubStatus):
    if row.operator_status != expected.value:
        raise HTTPException(
            status_code=409,
            detail=f"Expected status '{expected.value}', got '{row.operator_status}'",
        )


async def take_item(db: AsyncSession, item_id: int, user_id: int) -> dict:
    row = await _load_for_update(db, item_id)
    _require_status(row, ManualPubStatus.queued)
    row.operator_status = ManualPubStatus.in_progress.value
    row.taken_by_id = user_id
    row.taken_at = datetime.utcnow()
    await db.commit()
    return await get_item(db, item_id)


async def return_item(db: AsyncSession, item_id: int) -> dict:
    row = await _load_for_update(db, item_id)
    _require_status(row, ManualPubStatus.in_progress)
    row.operator_status = ManualPubStatus.queued.value
    row.taken_by_id = None
    row.taken_at = None
    await db.commit()
    return await get_item(db, item_id)


async def mark_published(db: AsyncSession, item_id: int, user_id: int,
                         published_at: datetime, post_url: str) -> dict:
    row = await _load_for_update(db, item_id)
    _require_status(row, ManualPubStatus.in_progress)
    row.operator_status = ManualPubStatus.published.value
    row.published_by_id = user_id
    row.published_at = published_at
    row.post_url = post_url
    # Close the loop with WP #85: stamp the slot if matcher hasn't yet.
    await db.execute(text("""
        UPDATE validator_schedule_slots
        SET matched_post_url = :url, matched_at = :at, updated_at = now()
        WHERE id = :slot_id AND matched_post_url IS NULL
    """), {"url": post_url, "at": published_at, "slot_id": row.slot_id})
    await db.commit()
    return await get_item(db, item_id)


async def rework_item(db: AsyncSession, item_id: int) -> dict:
    row = await _load_for_update(db, item_id)
    _require_status(row, ManualPubStatus.published)
    row.operator_status = ManualPubStatus.queued.value
    row.published_by_id = None
    row.published_at = None
    row.post_url = None
    row.taken_by_id = None
    row.taken_at = None
    await db.commit()
    return await get_item(db, item_id)


async def cancel_queued_for_slot(db: AsyncSession, slot_id: int) -> int:
    """WP #85 toggle OFF: cancel still-queued rows for a slot.

    in_progress / published rows are preserved for history.
    Caller commits (called inside the toggle transaction).
    """
    res = await db.execute(text("""
        UPDATE validator_manual_publish_queue
        SET cancelled_at = now(), updated_at = now()
        WHERE slot_id = :slot_id
          AND operator_status = 'queued'
          AND cancelled_at IS NULL
        RETURNING id
    """), {"slot_id": slot_id})
    return len(res.fetchall())
```

- [ ] **Step 2: Verify it imports**

Run:
```bash
cd /home/claude-user/validator-contenthunter/backend
python -c "from src.services.manual_publish_service import account_profile_url as f; print(f('tiktok','@x'), f('instagram','y'), f('vk','z'))"
```
Expected: `https://www.tiktok.com/@x https://instagram.com/y None`

- [ ] **Step 3: Commit**

```bash
git add backend/src/services/manual_publish_service.py
git commit -m "feat(wp107): manual_publish_service (serializer + transitions + cancel)"
```

---

### Task 4: Router + registration

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/src/routers/manual_publish.py`
- Modify: `/home/claude-user/validator-contenthunter/backend/src/main.py`

- [ ] **Step 1: Write the router**

`src/routers/manual_publish.py`:
```python
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..dependencies import get_current_user, require_role
from ..models.user import ValidatorUser, UserRole
from ..services import manual_publish_service as svc

router = APIRouter(prefix="/api/manual-publish", tags=["manual-publish"])

_admin = Depends(require_role(UserRole.admin))


class PublishBody(BaseModel):
    published_at: datetime
    post_url: str = Field(min_length=1)


@router.get("/queue", dependencies=[_admin])
async def list_queue(
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_queue(db, status=status)


@router.get("/queue/{item_id}", dependencies=[_admin])
async def get_item(item_id: int, db: AsyncSession = Depends(get_db)):
    return await svc.get_item(db, item_id)


@router.post("/queue/{item_id}/take", dependencies=[_admin])
async def take(item_id: int,
               current_user: ValidatorUser = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    return await svc.take_item(db, item_id, current_user.id)


@router.post("/queue/{item_id}/return", dependencies=[_admin])
async def return_to_queue(item_id: int, db: AsyncSession = Depends(get_db)):
    return await svc.return_item(db, item_id)


@router.post("/queue/{item_id}/publish", dependencies=[_admin])
async def publish(item_id: int, body: PublishBody,
                  current_user: ValidatorUser = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    return await svc.mark_published(db, item_id, current_user.id,
                                    body.published_at, body.post_url)


@router.post("/queue/{item_id}/rework", dependencies=[_admin])
async def rework(item_id: int, db: AsyncSession = Depends(get_db)):
    return await svc.rework_item(db, item_id)
```

- [ ] **Step 2: Register the router in `main.py`**

Add `manual_publish` to the routers import (line ~11-18 group):
```python
from .routers import manual_publish
```
Add after the other `include_router` calls (after line ~144):
```python
app.include_router(manual_publish.router)
```

- [ ] **Step 3: Verify the app boots & routes are mounted**

Run:
```bash
cd /home/claude-user/validator-contenthunter/backend
python -c "from src.main import app; print([r.path for r in app.routes if 'manual-publish' in getattr(r,'path','')])"
```
Expected: lists `/api/manual-publish/queue`, `/api/manual-publish/queue/{item_id}`, `.../take`, `.../return`, `.../publish`, `.../rework`.

- [ ] **Step 4: Commit**

```bash
git add backend/src/routers/manual_publish.py backend/src/main.py
git commit -m "feat(wp107): manual-publish router (admin-only)"
```

---

### Task 5: Toggle-OFF cancels queued rows (WP #85 hook)

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/backend/src/routers/schedule.py:686-691` (the OFF branch of `set_manual_publish`)

- [ ] **Step 1: Add import near the top of `schedule.py`**

Add to the imports block:
```python
from ..services.manual_publish_service import cancel_queued_for_slot
```

- [ ] **Step 2: Call cancel in the OFF branch**

In `set_manual_publish`, the existing OFF branch is:
```python
    elif not new_value and slot.manual_publish:
        slot.manual_publish = False
        slot.manual_publish_set_by_id = current_user.id
        slot.manual_publish_set_at = func.now()
        # matched_* NOT cleared — preserve history
        log.info("[manual-publish] disabled slot=%d", slot_id)
```
Replace it with:
```python
    elif not new_value and slot.manual_publish:
        slot.manual_publish = False
        slot.manual_publish_set_by_id = current_user.id
        slot.manual_publish_set_at = func.now()
        # matched_* NOT cleared — preserve history
        cancelled = await cancel_queued_for_slot(db, slot_id)
        log.info("[manual-publish] disabled slot=%d cancelled_manual_queue=%d", slot_id, cancelled)
```

- [ ] **Step 3: Verify it imports / app still boots**

Run:
```bash
cd /home/claude-user/validator-contenthunter/backend
python -c "from src.main import app; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/src/routers/schedule.py
git commit -m "feat(wp107): toggle-OFF cancels queued manual-publish rows"
```

---

### Task 6: Backend tests

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/tests/test_manual_publish_queue.py`

Uses the live-DB token helpers pattern from `tests/test_manual_publish.py`. Dedicated id range `78000+` to avoid clashing with other test files. Seeds a content row + slot + queue row directly via SQL.

- [ ] **Step 1: Write the tests**

`tests/test_manual_publish_queue.py`:
```python
import pytest
import pytest_asyncio
import httpx
from datetime import date, datetime, timezone
from sqlalchemy import text

from src.main import app
from src.database import AsyncSessionLocal
from src.services.auth_service import create_access_token
from src.services.manual_publish_service import account_profile_url

_BASE = 78000
_SLOT_ID = _BASE + 1
_CONTENT_ID = _BASE + 2
_QUEUE_ID = None
_PROJECT_ID = 51  # active project in live DB


async def _token(role: str, login: str) -> str:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT id FROM validator_users WHERE login=:l AND is_active LIMIT 1"
        ), {"l": login})).mappings().first()
        if row:
            uid = row["id"]
        else:
            uid = (await db.execute(text(
                "INSERT INTO validator_users (login, password_hash, role, is_active) "
                "VALUES (:l,'x',:r,true) ON CONFLICT (login) DO UPDATE SET is_active=true, role=:r "
                "RETURNING id"
            ), {"l": login, "r": role})).scalar_one()
            await db.commit()
        return "Bearer " + create_access_token({"sub": str(uid), "role": role})


@pytest_asyncio.fixture
async def admin_token():
    return await _token("admin", "admin")


@pytest_asyncio.fixture
async def client_token():
    return await _token("client", "client_Parfumeria")


@pytest_asyncio.fixture(autouse=True)
async def _seed():
    """Insert content + slot + a queued row; clean up after."""
    global _QUEUE_ID
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            INSERT INTO validator_content (id, project_id, title, description, hashtags, geo, s3_url, status)
            VALUES (:cid, :pid, 'Тест заголовок', 'Тест описание', '["tag1","tag2"]'::jsonb,
                    'Москва', 'https://s3.example/src.mp4', 'in_uniqualization')
            ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title
        """), {"cid": _CONTENT_ID, "pid": _PROJECT_ID})
        await db.execute(text("""
            INSERT INTO validator_schedule_slots (id, project_id, slot_date, slot_position, content_id, status, manual_publish)
            VALUES (:sid, :pid, :d, 1, :cid, 'filled', true)
            ON CONFLICT (id) DO UPDATE SET manual_publish=true, content_id=EXCLUDED.content_id
        """), {"sid": _SLOT_ID, "pid": _PROJECT_ID, "d": date(2026, 5, 21), "cid": _CONTENT_ID})
        qid = (await db.execute(text("""
            INSERT INTO validator_manual_publish_queue
              (slot_id, content_id, unic_result_id, unic_task_id, scheme_id, project_id,
               project_name, pack_id, pack_name, account_id, account_username, platform,
               device_serial, raspberry_number, phone_number, planned_date, operator_status)
            VALUES (:sid, :cid, :rid, :tid, 12, :pid, 'Proj', 99, 'Pack A', 7, 'nick_ig',
                    'instagram', 'SER1', 9, 19, :d, 'queued')
            RETURNING id
        """), {"sid": _SLOT_ID, "cid": _CONTENT_ID, "rid": _BASE + 10, "tid": _BASE + 11,
               "pid": _PROJECT_ID, "d": date(2026, 5, 21)})).scalar_one()
        await db.commit()
        _QUEUE_ID = qid
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM validator_manual_publish_queue WHERE slot_id=:s"), {"s": _SLOT_ID})
        await db.execute(text("DELETE FROM validator_schedule_slots WHERE id=:s"), {"s": _SLOT_ID})
        await db.execute(text("DELETE FROM validator_content WHERE id=:c"), {"c": _CONTENT_ID})
        await db.commit()


@pytest.mark.asyncio
async def test_account_url_per_platform():
    assert account_profile_url("instagram", "nick") == "https://instagram.com/nick"
    assert account_profile_url("tiktok", "@nick") == "https://www.tiktok.com/@nick"
    assert account_profile_url("youtube", "nick") == "https://www.youtube.com/@nick"
    assert account_profile_url("vk", "nick") is None
    assert account_profile_url("instagram", None) is None


@pytest.mark.asyncio
async def test_list_serializes_joined_fields(admin_token):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/manual-publish/queue", headers={"Authorization": admin_token})
    assert r.status_code == 200
    item = next(x for x in r.json() if x["id"] == _QUEUE_ID)
    assert item["title"] == "Тест заголовок"
    assert item["source_video_url"] == "https://s3.example/src.mp4"
    assert item["account_url"] == "https://instagram.com/nick_ig"
    assert item["phone_number"] == 19
    assert item["operator_status"] == "queued"


@pytest.mark.asyncio
async def test_non_admin_forbidden(client_token):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/api/manual-publish/queue", headers={"Authorization": client_token})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_full_status_cycle(admin_token):
    transport = httpx.ASGITransport(app=app)
    h = {"Authorization": admin_token}
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # take
        r = await c.post(f"/api/manual-publish/queue/{_QUEUE_ID}/take", headers=h)
        assert r.status_code == 200 and r.json()["operator_status"] == "in_progress"
        assert r.json()["taken_by"] == "admin"
        # publish requires both fields -> 422 when missing
        r = await c.post(f"/api/manual-publish/queue/{_QUEUE_ID}/publish", headers=h, json={})
        assert r.status_code == 422
        # publish ok
        r = await c.post(f"/api/manual-publish/queue/{_QUEUE_ID}/publish", headers=h,
                         json={"published_at": "2026-05-21T12:00:00+03:00",
                               "post_url": "https://instagram.com/p/abc"})
        assert r.status_code == 200 and r.json()["operator_status"] == "published"
        assert r.json()["publication_url"] == "https://instagram.com/p/abc"
        # rework -> back to queued, taken/published cleared
        r = await c.post(f"/api/manual-publish/queue/{_QUEUE_ID}/rework", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["operator_status"] == "queued"
        assert body["taken_by_id"] is None and body["post_url"] is None


@pytest.mark.asyncio
async def test_invalid_transition_rejected(admin_token):
    transport = httpx.ASGITransport(app=app)
    h = {"Authorization": admin_token}
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # cannot publish from 'queued'
        r = await c.post(f"/api/manual-publish/queue/{_QUEUE_ID}/publish", headers=h,
                         json={"published_at": "2026-05-21T12:00:00+03:00", "post_url": "x"})
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_slot_matched_stamped_on_publish(admin_token):
    transport = httpx.ASGITransport(app=app)
    h = {"Authorization": admin_token}
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post(f"/api/manual-publish/queue/{_QUEUE_ID}/take", headers=h)
        await c.post(f"/api/manual-publish/queue/{_QUEUE_ID}/publish", headers=h,
                     json={"published_at": "2026-05-21T12:00:00+03:00",
                           "post_url": "https://tt.com/p/xyz"})
    async with AsyncSessionLocal() as db:
        url = (await db.execute(text(
            "SELECT matched_post_url FROM validator_schedule_slots WHERE id=:s"
        ), {"s": _SLOT_ID})).scalar_one()
    assert url == "https://tt.com/p/xyz"
```

- [ ] **Step 2: Run the tests**

Run:
```bash
cd /home/claude-user/validator-contenthunter/backend
python -m pytest tests/test_manual_publish_queue.py -v
```
Expected: all tests PASS. (Live DB; if `validator_content` requires extra NOT NULL columns, add them to the seed INSERT — inspect with `\d validator_content`.)

- [ ] **Step 3: Run the full backend suite (no regressions)**

Run:
```bash
cd /home/claude-user/validator-contenthunter/backend
python -m pytest -q
```
Expected: no NEW failures vs `origin/main` baseline. (Known pre-existing failures: the 2 stale Anthropic-mock tests in `test_fixes_2026_04_20.py` — ignore those, do not "fix" them.)

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_manual_publish_queue.py
git commit -m "test(wp107): manual-publish queue API + transitions + RBAC"
```

---

## Phase 2: Autowarm populator

### Task 7: Shared pairing helpers

**Files:**
- Create: `/home/claude-user/autowarm-testbench/queue_pairing.js`
- Create: `/home/claude-user/autowarm-testbench/test_queue_pairing.test.js`

These mirror the resolution logic in `server.js` `assignUnicResultsToQueue` (scheme→pack, pack→device, pack→accounts). Each takes a `pg` client/pool so it is testable with a fake.

- [ ] **Step 1: Write the helpers**

`queue_pairing.js`:
```javascript
'use strict';

// Resolve which pack a uniqualization scheme maps to.
// Primary: unic_tasks.meta.pack_scheme_map[scheme_id]. Fallback: positional
// mapping of task.schemes order ↔ project packs ordered by id.
async function resolvePackForScheme(db, { meta, schemeId, taskId, projectId }) {
  const map = (meta && meta.pack_scheme_map) || {};
  let packId = map[String(schemeId)];
  if (!packId && projectId) {
    const { rows: taskRow } = await db.query('SELECT schemes FROM unic_tasks WHERE id=$1', [taskId]);
    const schemeIds = (taskRow[0]?.schemes || '').split(',').map(Number).filter(Boolean);
    const { rows: packs } = await db.query(
      'SELECT id FROM factory_pack_accounts WHERE project_id=$1 ORDER BY id ASC', [projectId]
    );
    schemeIds.forEach((sid, i) => { if (packs[i]) map[String(sid)] = packs[i].id; });
    packId = map[String(schemeId)];
  }
  return packId || null;
}

// Resolve device (serial, raspberry, phone number) for a pack.
async function resolveDevice(db, packId) {
  const { rows } = await db.query(`
    SELECT fpa.id AS pack_id, fpa.pack_name,
           fdn.device_id AS device_serial, fdn.raspberry,
           fdn.device_number AS phone_number
    FROM factory_pack_accounts fpa
    JOIN factory_device_numbers fdn ON fdn.id = fpa.device_num_id
    WHERE fpa.id = $1
  `, [packId]);
  return rows[0] || null;
}

// Active accounts of a pack — first account per platform (mirrors DISTINCT ON).
async function resolvePackAccounts(db, packId) {
  const { rows } = await db.query(`
    SELECT DISTINCT ON (platform) id, username, platform
    FROM factory_inst_accounts
    WHERE pack_id = $1 AND active = true
    ORDER BY platform, id ASC
  `, [packId]);
  return rows;
}

module.exports = { resolvePackForScheme, resolveDevice, resolvePackAccounts };
```

- [ ] **Step 2: Write the helper tests with a fake client**

`test_queue_pairing.test.js`:
```javascript
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { resolvePackForScheme, resolveDevice, resolvePackAccounts } = require('./queue_pairing');

function fakeDb(handlers) {
  return { query: async (sql, params) => {
    for (const h of handlers) if (h.match.test(sql)) return h.resp(params);
    throw new Error('unexpected SQL: ' + sql);
  }};
}

test('resolvePackForScheme: uses meta.pack_scheme_map', async () => {
  const db = fakeDb([]);
  const packId = await resolvePackForScheme(db, {
    meta: { pack_scheme_map: { '12': 99 } }, schemeId: 12, taskId: 1, projectId: 5,
  });
  assert.strictEqual(packId, 99);
});

test('resolvePackForScheme: positional fallback by project packs', async () => {
  const db = fakeDb([
    { match: /FROM unic_tasks/, resp: () => ({ rows: [{ schemes: '12,7' }] }) },
    { match: /FROM factory_pack_accounts/, resp: () => ({ rows: [{ id: 99 }, { id: 100 }] }) },
  ]);
  const packId = await resolvePackForScheme(db, { meta: {}, schemeId: 7, taskId: 1, projectId: 5 });
  assert.strictEqual(packId, 100);
});

test('resolveDevice: maps phone_number from device_number', async () => {
  const db = fakeDb([{ match: /factory_device_numbers/, resp: () => ({
    rows: [{ pack_id: 99, pack_name: 'P', device_serial: 'S', raspberry: 9, phone_number: 19 }] }) }]);
  const d = await resolveDevice(db, 99);
  assert.strictEqual(d.phone_number, 19);
  assert.strictEqual(d.device_serial, 'S');
});

test('resolvePackAccounts: returns one per platform', async () => {
  const db = fakeDb([{ match: /factory_inst_accounts/, resp: () => ({
    rows: [{ id: 1, username: 'a', platform: 'instagram' }, { id: 2, username: 'b', platform: 'tiktok' }] }) }]);
  const accs = await resolvePackAccounts(db, 99);
  assert.strictEqual(accs.length, 2);
});
```

- [ ] **Step 3: Run**

Run:
```bash
cd /home/claude-user/autowarm-testbench
node --test test_queue_pairing.test.js
```
Expected: 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add queue_pairing.js test_queue_pairing.test.js
git commit -m "feat(wp107): shared scheme->pack->device->accounts pairing helpers"
```

---

### Task 8: `assignManualPublishQueue` populator

**Files:**
- Create: `/home/claude-user/autowarm-testbench/manual_queue_assign.js`
- Create: `/home/claude-user/autowarm-testbench/test_manual_queue_assign.test.js`

- [ ] **Step 1: Write the populator**

`manual_queue_assign.js`:
```javascript
'use strict';
const { resolvePackForScheme, resolveDevice, resolvePackAccounts } = require('./queue_pairing');

function isEnabled() {
  return process.env.MANUAL_QUEUE_POPULATE_ENABLED !== 'false';
}
function batchSize() {
  return parseInt(process.env.MANUAL_QUEUE_POPULATE_BATCH || '100', 10);
}

// Find ready uniqualization results for manual-publish slots that are not yet
// in the manual queue, and insert one row per (account × platform).
async function assignManualPublishQueue(pool, log = console) {
  if (!isEnabled()) return;
  try {
    const { rows: results } = await pool.query(`
      SELECT ur.id AS result_id, ur.task_id, ur.scheme_id, ur.output_url,
             ut.meta, ut.project_id, ut.project_name, ut.content_id,
             (ut.meta->>'slot_id')::int AS slot_id,
             vss.slot_date AS planned_date
      FROM unic_results ur
      JOIN unic_tasks ut ON ut.id = ur.task_id
      JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
      WHERE ur.status IN ('ready','done')
        AND vss.manual_publish = true
        AND NOT EXISTS (
          SELECT 1 FROM validator_manual_publish_queue q
          WHERE q.unic_result_id = ur.id AND q.cancelled_at IS NULL
        )
      ORDER BY ur.created_at ASC
      LIMIT $1
    `, [batchSize()]);

    if (!results.length) return;
    log.log(`[manual-queue] ${results.length} результатов уникализации для ручной выкладки`);

    for (const res of results) {
      try {
        const packId = await resolvePackForScheme(pool, {
          meta: res.meta || {}, schemeId: res.scheme_id, taskId: res.task_id, projectId: res.project_id,
        });
        if (!packId) { log.log(`[manual-queue] result=${res.result_id}: pack не найден, пропуск`); continue; }

        const device = await resolveDevice(pool, packId);
        if (!device) { log.log(`[manual-queue] pack=${packId}: устройство не найдено`); continue; }

        const accounts = await resolvePackAccounts(pool, packId);
        if (!accounts.length) { log.log(`[manual-queue] pack=${packId}: нет активных аккаунтов`); continue; }

        for (const acc of accounts) {
          // Dedup: same content already queued/active for this account+platform.
          const { rows: dup } = await pool.query(`
            SELECT 1 FROM validator_manual_publish_queue
            WHERE content_id = $1 AND account_username = $2 AND LOWER(platform) = LOWER($3)
              AND cancelled_at IS NULL
            LIMIT 1
          `, [res.content_id, acc.username, acc.platform]);
          if (dup.length) {
            log.log(`[manual-queue] content=${res.content_id} уже в очереди для @${acc.username} (${acc.platform}), пропуск`);
            continue;
          }
          await pool.query(`
            INSERT INTO validator_manual_publish_queue
              (slot_id, content_id, unic_result_id, unic_task_id, scheme_id, project_id,
               project_name, pack_id, pack_name, account_id, account_username, platform,
               device_serial, raspberry_number, phone_number, planned_date, operator_status)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'queued')
            ON CONFLICT (unic_result_id, account_username, platform)
              WHERE cancelled_at IS NULL DO NOTHING
          `, [
            res.slot_id, res.content_id, res.result_id, res.task_id, res.scheme_id, res.project_id,
            res.project_name, device.pack_id, device.pack_name, acc.id, acc.username, acc.platform,
            device.device_serial, device.raspberry, device.phone_number, res.planned_date,
          ]);
          log.log(`[manual-queue] ✅ result=${res.result_id} → @${acc.username} (${acc.platform}) phone=${device.phone_number}`);
        }
      } catch (e) {
        log.error(`[manual-queue] ошибка result=${res.result_id}:`, e.message);
      }
    }
  } catch (e) {
    log.error('[manual-queue] ❌ error:', e.message);
  }
}

module.exports = { assignManualPublishQueue, isEnabled, batchSize };
```

- [ ] **Step 2: Write the populator tests**

`test_manual_queue_assign.test.js`:
```javascript
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { assignManualPublishQueue, isEnabled } = require('./manual_queue_assign');

// Fake pool that records INSERTs and answers the resolution queries.
function makePool({ results, packId = 99, accounts, dupFor = new Set() }) {
  const inserts = [];
  return {
    inserts,
    query: async (sql, params) => {
      if (/FROM unic_results/.test(sql)) return { rows: results };
      if (/FROM unic_tasks WHERE id=/.test(sql)) return { rows: [{ schemes: '12' }] };
      if (/FROM factory_pack_accounts WHERE project_id/.test(sql)) return { rows: [{ id: packId }] };
      if (/factory_device_numbers/.test(sql)) return { rows: [{ pack_id: packId, pack_name: 'P', device_serial: 'S', raspberry: 9, phone_number: 19 }] };
      if (/FROM factory_inst_accounts/.test(sql)) return { rows: accounts };
      if (/SELECT 1 FROM validator_manual_publish_queue/.test(sql)) {
        const key = params[1] + '|' + params[2];
        return { rows: dupFor.has(key) ? [{ '?column?': 1 }] : [] };
      }
      if (/INSERT INTO validator_manual_publish_queue/.test(sql)) { inserts.push(params); return { rows: [] }; }
      throw new Error('unexpected SQL: ' + sql);
    },
  };
}

const silent = { log() {}, error() {} };

test('isEnabled honors kill-switch', () => {
  delete process.env.MANUAL_QUEUE_POPULATE_ENABLED;
  assert.strictEqual(isEnabled(), true);
  process.env.MANUAL_QUEUE_POPULATE_ENABLED = 'false';
  assert.strictEqual(isEnabled(), false);
  delete process.env.MANUAL_QUEUE_POPULATE_ENABLED;
});

test('inserts one row per account, mapping phone + pairing', async () => {
  const pool = makePool({
    results: [{ result_id: 10, task_id: 1, scheme_id: 12, output_url: 'u', meta: { pack_scheme_map: { '12': 99 } },
                project_id: 5, project_name: 'P', content_id: 200, slot_id: 300, planned_date: '2026-05-21' }],
    accounts: [{ id: 1, username: 'a', platform: 'instagram' }, { id: 2, username: 'b', platform: 'tiktok' }],
  });
  await assignManualPublishQueue(pool, silent);
  assert.strictEqual(pool.inserts.length, 2);
  // params order: [slot, content, result, task, scheme, project, projname, pack, packname, accid, user, platform, serial, rasp, phone, date]
  assert.strictEqual(pool.inserts[0][0], 300);   // slot_id
  assert.strictEqual(pool.inserts[0][14], 19);   // phone_number
  assert.strictEqual(pool.inserts[0][11], 'instagram');
});

test('dedup skips account already queued for the content', async () => {
  const pool = makePool({
    results: [{ result_id: 10, task_id: 1, scheme_id: 12, output_url: 'u', meta: { pack_scheme_map: { '12': 99 } },
                project_id: 5, project_name: 'P', content_id: 200, slot_id: 300, planned_date: '2026-05-21' }],
    accounts: [{ id: 1, username: 'a', platform: 'instagram' }],
    dupFor: new Set(['a|instagram']),
  });
  await assignManualPublishQueue(pool, silent);
  assert.strictEqual(pool.inserts.length, 0);
});

test('kill-switch off => no work', async () => {
  process.env.MANUAL_QUEUE_POPULATE_ENABLED = 'false';
  const pool = makePool({ results: [{}], accounts: [] });
  await assignManualPublishQueue(pool, silent);
  assert.strictEqual(pool.inserts.length, 0);
  delete process.env.MANUAL_QUEUE_POPULATE_ENABLED;
});
```

- [ ] **Step 3: Run**

Run:
```bash
cd /home/claude-user/autowarm-testbench
node --test test_manual_queue_assign.test.js
```
Expected: 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add manual_queue_assign.js test_manual_queue_assign.test.js
git commit -m "feat(wp107): assignManualPublishQueue populator + tests"
```

---

### Task 9: Wire populator into `server.js` + refactor auto path to shared helpers

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/server.js`

- [ ] **Step 1: Require the modules near the top of `server.js`** (with the other `require`s)

```javascript
const { assignManualPublishQueue } = require('./manual_queue_assign');
const { resolvePackForScheme, resolveDevice, resolvePackAccounts } = require('./queue_pairing');
```

- [ ] **Step 2: Schedule the populator** — add right after the existing `setInterval(assignUnicResultsToQueue, 30 * 60 * 1000);` line (~6278)

```javascript
// WP #107: populate the manual publishing queue for manual_publish slots.
assignManualPublishQueue(pool);
setInterval(() => assignManualPublishQueue(pool),
  parseInt(process.env.MANUAL_QUEUE_POPULATE_INTERVAL_MS || String(30 * 60 * 1000), 10));
```

- [ ] **Step 3: Refactor `assignUnicResultsToQueue` to call the shared helpers**

In `assignUnicResultsToQueue` (server.js ~6095-6151) replace the inline pack-resolution block (the `packSchemeMap`/`packId` fallback up to the `if (!packId)` guard) with:
```javascript
        const packId = await resolvePackForScheme(pool, {
          meta, schemeId: res.scheme_id, taskId: res.task_id, projectId: res.project_id,
        });
        if (!packId) {
          console.log(`[assign-queue] result=${res.result_id} scheme=${res.scheme_id}: pack не найден, пропускаем`);
          continue;
        }
```
Replace the inline device query (`SELECT ... FROM factory_pack_accounts ... JOIN factory_device_numbers ...` building `pack`) with:
```javascript
        const pack = await resolveDevice(pool, packId);
        if (!pack) { console.log(`[assign-queue] pack_id=${packId}: устройство не найдено`); continue; }
```
Replace the inline accounts query with:
```javascript
        const accounts = await resolvePackAccounts(pool, packId);
        if (!accounts.length) { console.log(`[assign-queue] pack_id=${packId}: нет активных аккаунтов`); continue; }
```
> NOTE: `resolveDevice` returns `pack_id, pack_name, device_serial, raspberry, phone_number` but NOT `adb_port`/`adb_host`. The auto path uses `pack.adb_port`/`pack.adb_host` in its INSERT. To keep behavior identical, KEEP the existing `raspberry_port` join: after `resolveDevice`, fetch adb info:
```javascript
        const { rows: rp } = await pool.query(
          `SELECT adb AS adb_port, COALESCE(host, '82.115.54.26') AS adb_host
           FROM raspberry_port WHERE raspberry_number = $1`, [pack.raspberry]);
        pack.adb_port = rp[0]?.adb_port || null;
        pack.adb_host = rp[0]?.adb_host || '82.115.54.26';
```

- [ ] **Step 4: Run the FULL autowarm test suite (regression guard for the auto path)**

Run:
```bash
cd /home/claude-user/autowarm-testbench
node --test test_queue_pairing.test.js test_manual_queue_assign.test.js test_slot_matcher.test.js
```
Expected: all pass. Then run the broader suite the repo uses (check `package.json` `scripts.test`); expect no new failures vs `origin/main`.

- [ ] **Step 5: Syntax-check server.js**

Run:
```bash
cd /home/claude-user/autowarm-testbench
node --check server.js
```
Expected: no output (valid).

- [ ] **Step 6: Commit**

```bash
git add server.js
git commit -m "feat(wp107): wire manual-queue populator + reuse pairing helpers in auto path"
```

---

## Phase 3: Validator frontend

### Task 10: Utilities (clipboard, account URL, MSK datetime)

**Files:**
- Create: `/home/claude-user/validator-contenthunter/frontend/src/utils/clipboard.ts`
- Create: `/home/claude-user/validator-contenthunter/frontend/src/utils/accountUrl.ts`
- Create: `/home/claude-user/validator-contenthunter/frontend/src/utils/datetimeMsk.ts`

- [ ] **Step 1: clipboard.ts** (extracted from `ManagerDashboard.vue:160-172`)

```typescript
export async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}
```

- [ ] **Step 2: accountUrl.ts** (mirror of backend `account_profile_url`)

```typescript
export function accountProfileUrl(platform?: string | null, username?: string | null): string | null {
  if (!username) return null
  const u = username.replace(/^@/, '')
  const p = (platform || '').toLowerCase()
  if (p === 'instagram') return `https://instagram.com/${u}`
  if (p === 'tiktok') return `https://www.tiktok.com/@${u}`
  if (p === 'youtube') return `https://www.youtube.com/@${u}`
  return null
}
```

- [ ] **Step 3: datetimeMsk.ts** (operator enters/views in Moscow time, UTC+3, no DST)

```typescript
// `<input type="datetime-local">` gives "YYYY-MM-DDTHH:mm" with no zone.
// We treat that wall-clock as MSK (UTC+3) and produce an absolute ISO string.
export function mskInputToISO(value: string): string {
  if (!value) return ''
  const v = value.length === 16 ? value + ':00' : value
  return new Date(v + '+03:00').toISOString()
}

// Format an absolute ISO string as MSK wall-clock for display.
export function formatMsk(iso?: string | null): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(iso)) + ' МСК'
}
```

- [ ] **Step 4: Re-point `ManagerDashboard.vue` to the shared util** (DRY)

In `frontend/src/pages/manager/ManagerDashboard.vue`, import `copyToClipboard` and replace the inline `navigator.clipboard … execCommand` block inside `copyCredentials()` with `await copyToClipboard(text)`. (Keep the `copied.value = true` UX around it.)

- [ ] **Step 5: Verify build/typecheck of utils**

Run:
```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit
```
Expected: no new type errors involving these files.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/utils/clipboard.ts frontend/src/utils/accountUrl.ts frontend/src/utils/datetimeMsk.ts frontend/src/pages/manager/ManagerDashboard.vue
git commit -m "feat(wp107): clipboard/accountUrl/MSK utils (+ DRY ManagerDashboard copy)"
```

---

### Task 11: API module + row type

**Files:**
- Create: `/home/claude-user/validator-contenthunter/frontend/src/api/manualPublish.ts`

- [ ] **Step 1: Write the module**

```typescript
import api from './client'

export type OperatorStatus = 'queued' | 'in_progress' | 'published'

export interface ManualPublishRow {
  id: number
  slot_id: number
  content_id: number
  scheme_id: number | null
  project_id: number
  project_name: string | null
  pack_id: number | null
  pack_name: string | null
  account_username: string
  account_url: string | null
  platform: string
  phone_number: number | null
  device_serial: string | null
  planned_date: string | null
  operator_status: OperatorStatus
  title: string | null
  description: string | null
  hashtags: string[]
  geo: string | null
  source_video_url: string | null
  unic_video_url: string | null
  post_url: string | null
  matched_post_url: string | null
  published_at: string | null
  matched_at: string | null
  publication_url: string | null
  publication_at: string | null
  taken_by_id: number | null
  taken_by: string | null
  published_by_id: number | null
  published_by: string | null
}

export const listQueue = (params?: Record<string, any>) =>
  api.get<ManualPublishRow[]>('/manual-publish/queue', { params })
export const getItem = (id: number) =>
  api.get<ManualPublishRow>(`/manual-publish/queue/${id}`)
export const takeItem = (id: number) =>
  api.post<ManualPublishRow>(`/manual-publish/queue/${id}/take`)
export const returnItem = (id: number) =>
  api.post<ManualPublishRow>(`/manual-publish/queue/${id}/return`)
export const publishItem = (id: number, data: { published_at: string; post_url: string }) =>
  api.post<ManualPublishRow>(`/manual-publish/queue/${id}/publish`, data)
export const reworkItem = (id: number) =>
  api.post<ManualPublishRow>(`/manual-publish/queue/${id}/rework`)
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/manualPublish.ts
git commit -m "feat(wp107): manualPublish API module + ManualPublishRow type"
```

---

### Task 12: Table composable (sort / filter / group) + Vitest

**Files:**
- Create: `/home/claude-user/validator-contenthunter/frontend/src/composables/useManualPublishTable.ts`
- Create: `/home/claude-user/validator-contenthunter/frontend/tests/useManualPublishTable.spec.ts`

- [ ] **Step 1: Write the failing test first**

`frontend/tests/useManualPublishTable.spec.ts`:
```typescript
import { describe, it, expect } from 'vitest'
import { ref } from 'vue'
import { useManualPublishTable } from '@/composables/useManualPublishTable'
import type { ManualPublishRow } from '@/api/manualPublish'

const mk = (o: Partial<ManualPublishRow>): ManualPublishRow => ({
  id: 0, slot_id: 0, content_id: 0, scheme_id: null, project_id: 0, project_name: null,
  pack_id: null, pack_name: null, account_username: '', account_url: null, platform: '',
  phone_number: null, device_serial: null, planned_date: null, operator_status: 'queued',
  title: null, description: null, hashtags: [], geo: null, source_video_url: null,
  unic_video_url: null, post_url: null, matched_post_url: null, published_at: null,
  matched_at: null, publication_url: null, publication_at: null, taken_by_id: null,
  taken_by: null, published_by_id: null, published_by: null, ...o,
})

describe('useManualPublishTable', () => {
  const rows = ref<ManualPublishRow[]>([
    mk({ id: 1, phone_number: 19, planned_date: '2026-05-22', platform: 'instagram' }),
    mk({ id: 2, phone_number: 19, planned_date: '2026-05-20', platform: 'tiktok' }),
    mk({ id: 3, phone_number: 7,  planned_date: '2026-05-21', platform: 'instagram' }),
  ])

  it('default sort = planned_date asc', () => {
    const t = useManualPublishTable(rows)
    expect(t.sortedRows.value.map(r => r.id)).toEqual([2, 3, 1])
  })

  it('filter by platform (exact)', () => {
    const t = useManualPublishTable(rows)
    t.filters.value.platform = 'instagram'
    expect(t.sortedRows.value.map(r => r.id).sort()).toEqual([1, 3])
  })

  it('toggleSort replaces by default, CTRL adds multi-key', () => {
    const t = useManualPublishTable(rows)
    t.toggleSort('phone_number', false)            // asc
    expect(t.sortKeys.value).toEqual([{ col: 'phone_number', dir: 'asc' }])
    t.toggleSort('planned_date', true)             // additive
    expect(t.sortKeys.value.length).toBe(2)
    // phone asc, then date asc: phone7(id3), phone19 -> date asc (id2 then id1)
    expect(t.sortedRows.value.map(r => r.id)).toEqual([3, 2, 1])
  })

  it('toggleSort cycles asc -> desc -> removed', () => {
    const t = useManualPublishTable(rows)
    t.toggleSort('id', false); expect(t.sortKeys.value[0].dir).toBe('asc')
    t.toggleSort('id', false); expect(t.sortKeys.value[0].dir).toBe('desc')
    t.toggleSort('id', false); expect(t.sortKeys.value.length).toBe(0)
  })

  it('groupedByPhone: groups ordered by oldest planned_date', () => {
    const t = useManualPublishTable(rows)
    const groups = t.groupedByPhone.value
    // phone 19 has 05-20 (oldest overall) so its group comes first
    expect(groups.map(g => g.phone)).toEqual([19, 7])
    expect(groups[0].rows.map(r => r.id)).toEqual([2, 1])
  })

  it('resetSortFilters clears state', () => {
    const t = useManualPublishTable(rows)
    t.filters.value.platform = 'tiktok'
    t.toggleSort('id', false)
    t.resetSortFilters()
    expect(t.filters.value.platform).toBeUndefined()
    expect(t.sortKeys.value.length).toBe(0)
  })
})
```

- [ ] **Step 2: Run to confirm it fails**

Run:
```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vitest run tests/useManualPublishTable.spec.ts
```
Expected: FAIL (`useManualPublishTable` not found).

- [ ] **Step 3: Implement the composable**

`frontend/src/composables/useManualPublishTable.ts`:
```typescript
import { ref, computed, type Ref } from 'vue'
import type { ManualPublishRow } from '@/api/manualPublish'

export type SortDir = 'asc' | 'desc'
export interface SortKey { col: string; dir: SortDir }

const cmp = (a: any, b: any): number => {
  if (a == null && b == null) return 0
  if (a == null) return -1
  if (b == null) return 1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), 'ru')
}

export function useManualPublishTable(rows: Ref<ManualPublishRow[]>) {
  const sortKeys = ref<SortKey[]>([])
  const filters = ref<Record<string, string>>({})

  function toggleSort(col: string, additive: boolean) {
    const existing = sortKeys.value.find(k => k.col === col)
    if (!additive) {
      if (!existing) { sortKeys.value = [{ col, dir: 'asc' }]; return }
      if (existing.dir === 'asc') { sortKeys.value = [{ col, dir: 'desc' }]; return }
      sortKeys.value = []           // third click resets (chronological/original)
      return
    }
    if (!existing) { sortKeys.value = [...sortKeys.value, { col, dir: 'asc' }]; return }
    if (existing.dir === 'asc') { existing.dir = 'desc'; sortKeys.value = [...sortKeys.value]; return }
    sortKeys.value = sortKeys.value.filter(k => k.col !== col)
  }

  function resetSortFilters() {
    sortKeys.value = []
    filters.value = {}
  }

  const filteredRows = computed(() => {
    const f = filters.value
    return rows.value.filter(r =>
      Object.entries(f).every(([col, val]) => {
        if (val == null || val === '') return true
        const cell = (r as any)[col]
        if (cell == null) return false
        return String(cell).toLowerCase().includes(String(val).toLowerCase())
      })
    )
  })

  const sortedRows = computed(() => {
    const keys = sortKeys.value
    const arr = [...filteredRows.value]
    if (!keys.length) {
      // default: planned_date asc, then phone, then id
      return arr.sort((a, b) =>
        cmp(a.planned_date, b.planned_date) || cmp(a.phone_number, b.phone_number) || cmp(a.id, b.id))
    }
    return arr.sort((a, b) => {
      for (const k of keys) {
        const c = cmp((a as any)[k.col], (b as any)[k.col])
        if (c !== 0) return k.dir === 'asc' ? c : -c
      }
      return cmp(a.id, b.id)
    })
  })

  const groupedByPhone = computed(() => {
    const map = new Map<number | null, ManualPublishRow[]>()
    for (const r of sortedRows.value) {
      const key = r.phone_number ?? null
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(r)
    }
    const groups = Array.from(map.entries()).map(([phone, rs]) => ({
      phone,
      rows: rs,
      oldest: rs.reduce<string | null>((m, r) =>
        (m == null || (r.planned_date && r.planned_date < m)) ? r.planned_date : m, null),
    }))
    return groups.sort((a, b) => cmp(a.oldest, b.oldest))
  })

  function uniqueValues(col: keyof ManualPublishRow): string[] {
    const set = new Set<string>()
    for (const r of rows.value) {
      const v = (r as any)[col]
      if (v != null && v !== '') set.add(String(v))
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'ru'))
  }

  return { sortKeys, filters, toggleSort, resetSortFilters,
           filteredRows, sortedRows, groupedByPhone, uniqueValues }
}
```

- [ ] **Step 4: Run to confirm pass**

Run:
```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vitest run tests/useManualPublishTable.spec.ts
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useManualPublishTable.ts frontend/tests/useManualPublishTable.spec.ts
git commit -m "feat(wp107): table composable (multi-sort/filter/group) + vitest"
```

---

### Task 13: Publication card component

**Files:**
- Create: `/home/claude-user/validator-contenthunter/frontend/src/components/manual-publish/PublicationCard.vue`

Pattern reference for the overlay shell: `frontend/src/components/schemes/SchemeDetailModal.vue`.

- [ ] **Step 1: Write the component**

`src/components/manual-publish/PublicationCard.vue`:
```vue
<template>
  <Teleport to="body">
    <div v-if="row" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/50" @click="$emit('close')"></div>
      <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6">

        <!-- Publish-confirmation banner -->
        <div v-if="confirmMode" class="mb-4 rounded-xl bg-red-600 text-white px-4 py-3 text-sm font-semibold">
          Введите дата-время публикации и ссылку на публикацию
        </div>

        <div class="flex items-center justify-between mb-4">
          <span class="badge" :class="statusBadgeClass">{{ statusLabel }}</span>
          <button class="text-gray-400 hover:text-gray-700" @click="$emit('close')">✕</button>
        </div>

        <!-- Copy-on-click content fields -->
        <div class="space-y-2 mb-4">
          <div class="cursor-pointer rounded-xl border border-gray-200 p-3 hover:bg-gray-50"
               @click="copy(row.title || '', 'title')">
            <div class="text-xs text-gray-400">Заголовок видео {{ copiedKey==='title' ? '· скопировано' : '' }}</div>
            <div class="text-sm">{{ row.title || '—' }}</div>
          </div>
          <div class="cursor-pointer rounded-xl border border-gray-200 p-3 hover:bg-gray-50"
               @click="copy(descriptionText, 'desc')">
            <div class="text-xs text-gray-400">Описание и хэштеги {{ copiedKey==='desc' ? '· скопировано' : '' }}</div>
            <div class="text-sm whitespace-pre-wrap">{{ descriptionText || '—' }}</div>
          </div>
          <div class="cursor-pointer rounded-xl border border-gray-200 p-3 hover:bg-gray-50"
               @click="copy(row.geo || '', 'geo')">
            <div class="text-xs text-gray-400">Гео {{ copiedKey==='geo' ? '· скопировано' : '' }}</div>
            <div class="text-sm">{{ row.geo || '—' }}</div>
          </div>
        </div>

        <!-- Video player + downloads -->
        <video v-if="row.unic_video_url" :src="row.unic_video_url" :key="row.unic_video_url"
               controls class="w-full rounded-xl mb-2" style="background:#000; max-height:50vh"></video>
        <div class="flex gap-4 text-sm mb-4">
          <a v-if="row.unic_video_url" :href="row.unic_video_url" target="_blank"
             class="text-indigo-600 hover:underline" download>Скачать уникализированное видео</a>
          <a v-if="row.source_video_url" :href="row.source_video_url" target="_blank"
             class="text-indigo-600 hover:underline" download>Скачать исходное видео</a>
        </div>

        <!-- Publication group -->
        <div class="rounded-xl bg-gray-50 p-3 mb-4 text-sm">
          <div class="text-xs text-gray-400 mb-1">Публикация</div>
          <template v-if="!confirmMode">
            <div>Дата-время: {{ formatMsk(row.publication_at) }}</div>
            <div>Ссылка:
              <a v-if="row.publication_url" :href="row.publication_url" target="_blank"
                 class="text-indigo-600 hover:underline">{{ row.publication_url }}</a>
              <span v-else>—</span>
            </div>
          </template>
          <template v-else>
            <label class="block mb-2">
              <span class="text-xs text-gray-500">Дата-время публикации (МСК)</span>
              <input v-model="form.publishedAtLocal" type="datetime-local" class="input mt-1" />
            </label>
            <label class="block">
              <span class="text-xs text-gray-500">Ссылка на публикацию</span>
              <input v-model="form.postUrl" type="url" placeholder="https://…" class="input mt-1" />
            </label>
          </template>
        </div>

        <!-- Status-driven action -->
        <div class="flex justify-end gap-2">
          <template v-if="confirmMode">
            <button class="btn-secondary" @click="confirmMode=false">Отмена</button>
            <button class="btn-primary" :disabled="!confirmValid" @click="doPublish">Подтвердить выкладку</button>
          </template>
          <template v-else>
            <button v-if="row.operator_status==='queued'" class="btn-primary" @click="$emit('take', row.id)">Взять в работу</button>
            <button v-if="row.operator_status==='in_progress'" class="btn-secondary" @click="$emit('return', row.id)">Вернуть в очередь</button>
            <button v-if="row.operator_status==='in_progress'" class="btn-primary" @click="enterConfirm">Отметить выкладку</button>
            <button v-if="row.operator_status==='published'" class="btn-secondary" @click="$emit('rework', row.id)">Вернуть на доработку</button>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import type { ManualPublishRow } from '@/api/manualPublish'
import { copyToClipboard } from '@/utils/clipboard'
import { formatMsk, mskInputToISO } from '@/utils/datetimeMsk'

const props = defineProps<{ row: ManualPublishRow | null; startConfirm?: boolean }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'take', id: number): void
  (e: 'return', id: number): void
  (e: 'rework', id: number): void
  (e: 'publish', payload: { id: number; published_at: string; post_url: string }): void
}>()

const confirmMode = ref(false)
const copiedKey = ref('')
const form = reactive({ publishedAtLocal: '', postUrl: '' })

watch(() => props.row, () => { confirmMode.value = !!props.startConfirm; form.publishedAtLocal=''; form.postUrl='' }, { immediate: true })

const descriptionText = computed(() => {
  const tags = (props.row?.hashtags || []).map(t => `#${t.replace(/^#/, '')}`).join(' ')
  return [props.row?.description || '', tags].filter(Boolean).join('\n\n')
})
const statusLabel = computed(() => ({ queued: 'В очереди', in_progress: 'В работе', published: 'Выложено' } as any)[props.row?.operator_status || 'queued'])
const statusBadgeClass = computed(() => ({ queued: 'badge-gray', in_progress: 'badge-blue', published: 'badge-green' } as any)[props.row?.operator_status || 'queued'])
const confirmValid = computed(() => !!form.publishedAtLocal && !!form.postUrl.trim())

function enterConfirm() { confirmMode.value = true }
async function copy(text: string, key: string) {
  if (!text) return
  await copyToClipboard(text)
  copiedKey.value = key
  setTimeout(() => { if (copiedKey.value === key) copiedKey.value = '' }, 2000)
}
function doPublish() {
  if (!props.row || !confirmValid.value) return
  emit('publish', { id: props.row.id, published_at: mskInputToISO(form.publishedAtLocal), post_url: form.postUrl.trim() })
}

defineExpose({ formatMsk })
</script>
```
> Note: `formatMsk` is used in the template; it is imported into scope, so `defineExpose` is optional — keep the import. If your lint forbids unused `defineExpose`, drop that line.

- [ ] **Step 2: Typecheck**

Run:
```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit
```
Expected: no new errors in this file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/manual-publish/PublicationCard.vue
git commit -m "feat(wp107): PublicationCard dialog (copy/player/downloads/confirm-banner)"
```

---

### Task 14: Queue page

**Files:**
- Create: `/home/claude-user/validator-contenthunter/frontend/src/pages/admin/ManualPublishingQueue.vue`

Pattern reference for table sort/filter/sticky: `frontend/src/pages/admin/UsersManagement.vue`.

- [ ] **Step 1: Write the page**

`src/pages/admin/ManualPublishingQueue.vue`:
```vue
<template>
  <div class="p-4">
    <div class="flex items-center justify-between mb-4">
      <h1 class="text-xl font-semibold">Ручная выкладка</h1>
      <button class="btn-secondary" @click="load">Обновить</button>
    </div>

    <div class="card overflow-x-auto">
      <table class="min-w-full text-sm">
        <thead class="sticky top-0 z-10 bg-white">
          <tr class="text-left text-gray-500">
            <th v-for="col in columns" :key="col.key"
                class="px-2 py-2 cursor-pointer select-none whitespace-nowrap"
                @click="onHeaderClick(col.key, $event)">
              {{ col.label }} <span class="text-xs">{{ sortIndicator(col.key) }}</span>
            </th>
            <th class="px-2 py-2">Действие</th>
          </tr>
          <tr class="bg-gray-50">
            <th v-for="col in columns" :key="col.key" class="px-2 py-1 align-top">
              <select v-if="col.filter==='select'" v-model="t.filters.value[col.key]" class="input py-1 text-xs">
                <option value="">—</option>
                <option v-for="v in t.uniqueValues(col.key as any)" :key="v" :value="v">{{ v }}</option>
              </select>
              <input v-else-if="col.filter==='text'" v-model="t.filters.value[col.key]" class="input py-1 text-xs" placeholder="…" />
            </th>
            <th class="px-2 py-1">
              <button class="btn-secondary text-xs" title="Сбросить фильтры и сортировку" @click="t.resetSortFilters()">⟲ Сброс</button>
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in t.groupedByPhone.value" :key="group.phone ?? 'none'">
            <tr class="bg-indigo-50">
              <td :colspan="columns.length + 1" class="px-2 py-1 font-semibold text-indigo-700">
                📱 Телефон {{ group.phone ?? '—' }}
              </td>
            </tr>
            <tr v-for="r in group.rows" :key="r.id"
                class="border-t hover:bg-gray-50 cursor-pointer"
                @click="openCard(r)">
              <td class="px-2 py-2">{{ r.id }}</td>
              <td class="px-2 py-2">{{ r.phone_number ?? '—' }}</td>
              <td class="px-2 py-2">{{ r.project_name || r.project_id }}</td>
              <td class="px-2 py-2">{{ platformLabel(r.platform) }}</td>
              <td class="px-2 py-2">{{ r.pack_name || r.pack_id }}</td>
              <td class="px-2 py-2" @click.stop>
                <a v-if="r.account_url" :href="r.account_url" target="_blank" class="text-indigo-600 hover:underline">@{{ r.account_username }}</a>
                <span v-else>@{{ r.account_username }}</span>
              </td>
              <td class="px-2 py-2" @click.stop>
                <a v-if="r.source_video_url" :href="r.source_video_url" target="_blank" class="text-indigo-600 hover:underline">▶</a>
                <span v-else>—</span>
              </td>
              <td class="px-2 py-2" @click.stop>
                <a v-if="r.unic_video_url" :href="r.unic_video_url" target="_blank" class="text-indigo-600 hover:underline">▶</a>
                <span v-else>—</span>
              </td>
              <td class="px-2 py-2">{{ r.scheme_id ?? '—' }}</td>
              <td class="px-2 py-2">{{ r.planned_date || '—' }}</td>
              <td class="px-2 py-2"><span class="badge" :class="statusBadgeClass(r.operator_status)">{{ statusLabel(r.operator_status) }}</span></td>
              <td class="px-2 py-2" @click.stop>
                <a v-if="r.publication_url" :href="r.publication_url" target="_blank" class="text-indigo-600 hover:underline">↗</a>
                <span v-else>—</span>
              </td>
              <td class="px-2 py-2" @click.stop>
                <button v-if="r.operator_status==='queued'" class="btn-primary text-xs" @click="act(takeItem, r.id)">Взять в работу</button>
                <template v-else-if="r.operator_status==='in_progress'">
                  <button class="btn-secondary text-xs mr-1" @click="act(returnItem, r.id)">Вернуть в очередь</button>
                  <button class="btn-primary text-xs" @click="openCard(r, true)">Отметить выкладку</button>
                </template>
                <button v-else-if="r.operator_status==='published'" class="btn-secondary text-xs" @click="act(reworkItem, r.id)">Вернуть на доработку</button>
              </td>
            </tr>
          </template>
          <tr v-if="!rows.length"><td :colspan="columns.length + 1" class="px-2 py-6 text-center text-gray-400">Очередь пуста</td></tr>
        </tbody>
      </table>
    </div>

    <PublicationCard :row="selected" :start-confirm="startConfirm"
      @close="selected=null"
      @take="id => act(takeItem, id)"
      @return="id => act(returnItem, id)"
      @rework="id => act(reworkItem, id)"
      @publish="onPublish" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import {
  listQueue, takeItem, returnItem, reworkItem, publishItem,
  type ManualPublishRow,
} from '@/api/manualPublish'
import { useManualPublishTable } from '@/composables/useManualPublishTable'
import PublicationCard from '@/components/manual-publish/PublicationCard.vue'

const columns = [
  { key: 'id', label: 'id', filter: 'text' },
  { key: 'phone_number', label: 'Тел.№', filter: 'select' },
  { key: 'project_name', label: 'Проект', filter: 'select' },
  { key: 'platform', label: 'Платформа', filter: 'select' },
  { key: 'pack_name', label: 'Пак', filter: 'select' },
  { key: 'account_username', label: 'Аккаунт', filter: 'text' },
  { key: 'source_video_url', label: 'Исх.', filter: 'none' },
  { key: 'unic_video_url', label: 'Уник.', filter: 'none' },
  { key: 'scheme_id', label: 'Схема', filter: 'select' },
  { key: 'planned_date', label: 'План дата', filter: 'text' },
  { key: 'operator_status', label: 'Статус', filter: 'select' },
  { key: 'publication_url', label: 'Публикация', filter: 'none' },
] as const

const rows = ref<ManualPublishRow[]>([])
const t = useManualPublishTable(rows)
const selected = ref<ManualPublishRow | null>(null)
const startConfirm = ref(false)
let timer: number | undefined

async function load() {
  const res = await listQueue()
  rows.value = res.data
}
function openCard(r: ManualPublishRow, confirm = false) { selected.value = r; startConfirm.value = confirm }
async function act(fn: (id: number) => Promise<any>, id: number) {
  await fn(id); await load()
  if (selected.value?.id === id) selected.value = rows.value.find(r => r.id === id) || null
}
async function onPublish(p: { id: number; published_at: string; post_url: string }) {
  await publishItem(p.id, { published_at: p.published_at, post_url: p.post_url })
  selected.value = null
  await load()
}
function onHeaderClick(key: string, e: MouseEvent) {
  if ((columns.find(c => c.key === key) as any)?.filter === 'none') return
  t.toggleSort(key, e.ctrlKey || e.metaKey)
}
function sortIndicator(key: string) {
  const i = t.sortKeys.value.findIndex(k => k.col === key)
  if (i === -1) return ''
  const k = t.sortKeys.value[i]
  return (k.dir === 'asc' ? '▲' : '▼') + (t.sortKeys.value.length > 1 ? String(i + 1) : '')
}
function platformLabel(p: string) { return ({ instagram: 'IG', tiktok: 'TT', youtube: 'YT' } as any)[p?.toLowerCase()] || p }
function statusLabel(s: string) { return ({ queued: 'В очереди', in_progress: 'В работе', published: 'Выложено' } as any)[s] || s }
function statusBadgeClass(s: string) { return ({ queued: 'badge-gray', in_progress: 'badge-blue', published: 'badge-green' } as any)[s] || 'badge-gray' }

onMounted(() => { load(); timer = window.setInterval(load, 60000) })
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
```

- [ ] **Step 2: Typecheck**

Run:
```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit
```
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/admin/ManualPublishingQueue.vue
git commit -m "feat(wp107): ManualPublishingQueue page (sticky/multi-sort/filters/group)"
```

---

### Task 15: Route + sidebar

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/frontend/src/router/index.ts`
- Modify: `/home/claude-user/validator-contenthunter/frontend/src/components/layout/AppSidebar.vue`

- [ ] **Step 1: Add the route** (in the Admin block of the `routes` array)

```typescript
    { path: '/manual-publish', component: () => import('@/pages/admin/ManualPublishingQueue.vue'), meta: { roles: ['admin'] } },
```

- [ ] **Step 2: Add the «Выкладка» sidebar section** — insert a new block before the existing `<div v-if="auth.isAdmin" class="pt-3">` (the «Админ» block, ~line 40)

```vue
      <div v-if="auth.isAdmin" class="pt-3">
        <p class="text-xs font-semibold text-gray-400 uppercase tracking-wide px-3 mb-1">Выкладка</p>
        <NavItem to="/manual-publish" icon="📤" label="Ручная выкладка" />
      </div>
```
(Match the heading markup used by the other sections; if other sections render their title differently, mirror that exact pattern.)

- [ ] **Step 3: Build the frontend (verifies route + page compile)**

Run:
```bash
cd /home/claude-user/validator-contenthunter/frontend
npm run build
```
Expected: build succeeds. (NOTE: `postbuild` copies output to `/var/www/validator/` — that is the LOCAL dev box, not prod. This is fine on the dev box; do not run on prod.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router/index.ts frontend/src/components/layout/AppSidebar.vue
git commit -m "feat(wp107): route + sidebar «Выкладка → Ручная выкладка» (admin)"
```

---

## Phase 4: Integration & handoff

### Task 16: End-to-end smoke on the dev box

**Files:** none (manual verification)

- [ ] **Step 1: Confirm migration applied & table empty-or-seeded**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
  "SELECT count(*) FROM validator_manual_publish_queue;"
```

- [ ] **Step 2: Dry-run the populator against the live DB** (no interval; one pass)

```bash
cd /home/claude-user/autowarm-testbench
node -e "const {Pool}=require('pg');const p=new Pool({connectionString:'postgresql://openclaw:openclaw123@localhost:5432/openclaw'});require('./manual_queue_assign').assignManualPublishQueue(p).then(()=>p.end());"
```
Expected: logs `[manual-queue] …` lines if any manual_publish slot has ready `unic_results`; otherwise silent. No errors.

- [ ] **Step 3: Hit the API as admin** (reuse a real admin JWT, or the test helper) and confirm `GET /api/manual-publish/queue` returns rows that match the table; walk one row through take → publish → rework via the UI on the dev validator.

- [ ] **Step 4: Full suites green**

```bash
cd /home/claude-user/validator-contenthunter/backend && python -m pytest -q
cd /home/claude-user/autowarm-testbench && node --test test_queue_pairing.test.js test_manual_queue_assign.test.js test_slot_matcher.test.js
cd /home/claude-user/validator-contenthunter/frontend && npx vitest run
```
Expected: no new failures.

### Deploy notes (executed by Danil — NOT in this plan run)

1. **validator first:** pull → `cd backend && python -m alembic upgrade head` (creates the table). Bind: PM2 `validator` (id=24), not systemd (`validator-backend.service` stays disabled).
2. **autowarm:** pull → `pm2 restart autowarm` (picks up `assignManualPublishQueue`). Watch `[manual-queue]` log for dup/pairing misses the first week.
3. **validator frontend:** `cd frontend && npm run build` (postbuild auto-deploys to `/var/www/validator/`).
4. Kill-switch if needed: `MANUAL_QUEUE_POPULATE_ENABLED=false` on autowarm.

---

## Self-Review (completed during authoring)

- **Spec coverage:** table fields → Task 1/3/14; status machine + buttons → Task 3/13/14; «Отметить выкладку» red-banner modal → Task 13; population/pairing → Task 7/8/9; toggle-OFF cancel → Task 5; «Публикация» both-paths (operator + matcher) → Task 3 (`mark_published` stamps slot; serializer `publication_url`); RBAC admin-only → Task 4 + Task 15 route meta + sidebar admin block; sticky/multi-sort/filters/reset/group → Task 12/14; copy/player/downloads → Task 13; kill-switch → Task 8/9; tests → Task 6/7/8/12; migration + deploy order → Task 1 + Phase 4. No gaps.
- **Placeholder scan:** no TBD/TODO; every code step has full code.
- **Type/name consistency:** serializer keys (`publication_url`, `publication_at`, `operator_status`, `unic_video_url`, `source_video_url`, `account_url`) match `ManualPublishRow` (Task 11) and the page/card usage (Task 13/14). Status values `queued|in_progress|published` consistent across migration CHECK, `ManualPubStatus`, transitions, and frontend labels. Helper names `resolvePackForScheme/resolveDevice/resolvePackAccounts` consistent across Task 7/8/9.
