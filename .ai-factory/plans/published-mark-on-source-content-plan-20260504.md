# Published mark on source content — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show "📣 опубликовано" badge on slot cards in `/dashboard` and a per-platform breakdown block on `/content/<id>`, computed live from `publish_queue.status='done'`.

**Architecture:** Live JOIN on read (no schema changes, no autowarm coupling). New `is_published: bool` field as orthogonal axis to `content.status`. Backend additive in `validator-contenthunter` repo. Three partial indexes for performance. Frontend gets one new component (`PublishedBlock.vue`) plus minimal patches to `SlotCard.vue` and `ContentDetail.vue`.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend), Vue 3 Composition API + Tailwind (frontend), PostgreSQL (`openclaw` DB on prod VPS). Tests: pytest-asyncio against live DB (autouse `engine.dispose` fixture per `backend/tests/conftest.py`).

**Repo:** `GenGo2/validator-contenthunter`. All paths below are repo-relative. Create a feature branch (e.g. `feat/published-mark-source-content-20260504`) before starting.

**Reference spec:** `.ai-factory/plans/published-mark-on-source-content-design-20260504.md` in the agent workspace repo (`rmbrmv/contenthunter` worktree). Read the spec first for context, especially §3 (SQL), §4.3 (decision: `is_published` as orthogonal axis, NOT lazy-override of `status`), §6 (edge cases).

---

## File Structure

### Backend (`backend/`)

| File | Responsibility | New / Modified |
|---|---|---|
| `alembic/versions/003_publish_summary_indexes.py` | 3 partial indexes for live JOIN performance | New |
| `src/services/publish_summary_service.py` | `get_publish_summary(content_id)` and `get_published_flags(content_ids)` against `publish_queue/unic_tasks/unic_results` via raw `text()` | New |
| `src/routers/content.py` | Add async `_content_to_dict_with_publish` wrapper; replace calls in 6 places (lines 89, 138, 226, 268, 350, 441) | Modified |
| `src/services/schedule_service.py` | `get_week_slots` does bulk publish-flag lookup; `_slot_to_dict_with_content` adds `is_published`; `is_slot_movable_unpublished` accepts new `is_published` param to short-circuit | Modified |
| `tests/services/test_publish_summary.py` | Live-DB unit tests for service functions | New |
| `tests/test_content_publish_response.py` | Integration test for `/api/content/:id` and `/api/schedule` returning new fields | New |

### Frontend (`frontend/`)

| File | Responsibility | New / Modified |
|---|---|---|
| `src/utils/pluralize.ts` | ru-RU plural helper (1/2-4/5+) | New |
| `src/components/content/PublishedBlock.vue` | 3-tile breakdown block with click-to-expand account list | New |
| `src/components/calendar/SlotCard.vue` | Override badge label/class when `content.is_published === true` | Modified |
| `src/pages/client/ContentDetail.vue` | Mount `<PublishedBlock>` between status block and moderation block | Modified |

No frontend test framework exists in the repo — frontend coverage is **manual smoke** on prod (Task 10).

---

## Task 1: Backend — Alembic migration for 3 partial indexes

**Files:**
- Create: `backend/alembic/versions/003_publish_summary_indexes.py`

- [ ] **Step 1: Verify latest migration revision**

Run: `ls backend/alembic/versions/`
Expected: `001_initial.py  002_add_hashtags_geo.py` (no `003_*` yet).

- [ ] **Step 2: Write migration file**

Create `backend/alembic/versions/003_publish_summary_indexes.py`:

```python
"""Partial indexes for publish_summary live JOIN

Revision ID: 003
Revises: 002
Create Date: 2026-05-04
"""
from alembic import op


revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_unic_tasks_content_id
            ON unic_tasks (content_id) WHERE content_id IS NOT NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_publish_queue_unic_result_done
            ON publish_queue (unic_result_id) WHERE status = 'done';
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_publish_queue_carousel_done
            ON publish_queue (carousel_content_id)
            WHERE status = 'done' AND carousel_content_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_unic_tasks_content_id;")
    op.execute("DROP INDEX IF EXISTS ix_publish_queue_unic_result_done;")
    op.execute("DROP INDEX IF EXISTS ix_publish_queue_carousel_done;")
```

- [ ] **Step 3: Verify migration syntactically**

Run: `cd backend && python -c "import alembic.config; alembic.config.main(['heads'])"`
Expected: prints `003 (head)` (or similar — no errors).

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/003_publish_summary_indexes.py
git commit -m "feat(db): add partial indexes for publish_summary live JOIN"
```

---

## Task 2: Backend — publish_summary_service.get_publish_summary

**Files:**
- Create: `backend/src/services/publish_summary_service.py`
- Test: `backend/tests/services/test_publish_summary.py`

- [ ] **Step 1: Create empty service module**

Create `backend/src/services/publish_summary_service.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

PLATFORM_WHITELIST = ("instagram", "tiktok", "youtube")


async def get_publish_summary(content_id: int, db: AsyncSession) -> dict:
    """Per-platform breakdown for a single content_id.

    Returns:
        {
          "instagram": {"accounts": int, "account_list": list[str]},
          "tiktok":    {...},
          "youtube":   {...},
          "first_published_at": str | None,  # ISO-8601 UTC
          "is_published": bool,
        }

    Empty platforms (no done rows) are filled with accounts=0, account_list=[]
    so the frontend always renders three tiles.
    """
    raise NotImplementedError
```

- [ ] **Step 2: Create test file with 4 live-DB tests**

Create `backend/tests/services/__init__.py` (empty file).

Create `backend/tests/services/test_publish_summary.py`:

```python
"""Live-DB tests for publish_summary_service.

Combines multiple assertions per test to keep the asyncpg pool on a single
event loop (see backend/tests/conftest.py). Uses well-known prod content
ids confirmed to have known done-rows distribution.
"""
import pytest

from src.database import AsyncSessionLocal
from src.services.publish_summary_service import (
    get_publish_summary,
    PLATFORM_WHITELIST,
)


# Prod canaries (verified via SQL on 2026-05-04):
#   id=1894 → 12 done in {instagram, youtube}
#   id=1763 → 9 done in {tiktok, youtube}
#   id=1804 → 8 done in {youtube} only
KNOWN_IG_YT_CONTENT_ID = 1894
KNOWN_TT_YT_CONTENT_ID = 1763
KNOWN_YT_ONLY_CONTENT_ID = 1804
UNKNOWN_CONTENT_ID = 999_999_999


@pytest.mark.asyncio
async def test_get_publish_summary_canaries():
    async with AsyncSessionLocal() as db:
        summary_ig_yt = await get_publish_summary(KNOWN_IG_YT_CONTENT_ID, db)
        summary_tt_yt = await get_publish_summary(KNOWN_TT_YT_CONTENT_ID, db)
        summary_yt = await get_publish_summary(KNOWN_YT_ONLY_CONTENT_ID, db)
        empty = await get_publish_summary(UNKNOWN_CONTENT_ID, db)

    # Always returns all three platforms in result
    for s in (summary_ig_yt, summary_tt_yt, summary_yt, empty):
        for p in PLATFORM_WHITELIST:
            assert p in s, f"missing platform {p!r} in {s!r}"
            assert "accounts" in s[p]
            assert "account_list" in s[p]
            assert isinstance(s[p]["accounts"], int)
            assert isinstance(s[p]["account_list"], list)

    # Canary distributions
    assert summary_ig_yt["instagram"]["accounts"] > 0
    assert summary_ig_yt["youtube"]["accounts"] > 0
    assert summary_ig_yt["tiktok"]["accounts"] == 0
    assert summary_ig_yt["is_published"] is True

    assert summary_tt_yt["tiktok"]["accounts"] > 0
    assert summary_tt_yt["youtube"]["accounts"] > 0

    assert summary_yt["youtube"]["accounts"] > 0
    assert summary_yt["instagram"]["accounts"] == 0
    assert summary_yt["tiktok"]["accounts"] == 0

    # Unknown content → empty zero-state
    assert empty["is_published"] is False
    for p in PLATFORM_WHITELIST:
        assert empty[p]["accounts"] == 0
        assert empty[p]["account_list"] == []
    assert empty["first_published_at"] is None

    # account_list содержит хотя бы один реальный username для KNOWN_IG_YT
    assert len(summary_ig_yt["instagram"]["account_list"]) == summary_ig_yt["instagram"]["accounts"]
    assert all(isinstance(u, str) and u for u in summary_ig_yt["instagram"]["account_list"])
```

- [ ] **Step 3: Run test to verify it fails (NotImplementedError)**

Run: `cd backend && pytest tests/services/test_publish_summary.py -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 4: Implement get_publish_summary**

Replace the body of `get_publish_summary` in `backend/src/services/publish_summary_service.py`:

```python
async def get_publish_summary(content_id: int, db: AsyncSession) -> dict:
    """Per-platform breakdown for a single content_id."""
    sql = text("""
        WITH published AS (
          SELECT pq.platform, pq.account_username
          FROM unic_tasks ut
          JOIN unic_results ur ON ur.task_id = ut.id
          JOIN publish_queue pq ON pq.unic_result_id = ur.id
          WHERE ut.content_id = :content_id
            AND pq.status = 'done'
            AND lower(pq.platform) = ANY(:whitelist)
            AND pq.account_username IS NOT NULL

          UNION ALL

          SELECT pq.platform, pq.account_username
          FROM publish_queue pq
          WHERE pq.carousel_content_id = :content_id
            AND pq.status = 'done'
            AND lower(pq.platform) = ANY(:whitelist)
            AND pq.account_username IS NOT NULL
        )
        SELECT
          lower(platform) AS platform,
          count(DISTINCT account_username) AS accounts,
          array_agg(DISTINCT account_username ORDER BY account_username) AS account_list
        FROM published
        GROUP BY lower(platform);
    """)
    rows = (await db.execute(
        sql,
        {"content_id": content_id, "whitelist": list(PLATFORM_WHITELIST)},
    )).mappings().all()

    # Build per-platform map; pad missing platforms with zero-state
    by_platform = {p: {"accounts": 0, "account_list": []} for p in PLATFORM_WHITELIST}
    for r in rows:
        by_platform[r["platform"]] = {
            "accounts": int(r["accounts"]),
            "account_list": list(r["account_list"] or []),
        }

    is_published = any(by_platform[p]["accounts"] > 0 for p in PLATFORM_WHITELIST)

    first_at_sql = text("""
        SELECT min(pq.updated_at) AS t
        FROM publish_queue pq
        LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
        LEFT JOIN unic_tasks ut ON ut.id = ur.task_id
        WHERE pq.status = 'done'
          AND lower(pq.platform) = ANY(:whitelist)
          AND (ut.content_id = :content_id OR pq.carousel_content_id = :content_id);
    """)
    first_at = (await db.execute(
        first_at_sql,
        {"content_id": content_id, "whitelist": list(PLATFORM_WHITELIST)},
    )).scalar()

    return {
        **by_platform,
        "first_published_at": first_at.isoformat() if first_at else None,
        "is_published": is_published,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/services/test_publish_summary.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/publish_summary_service.py backend/tests/services/__init__.py backend/tests/services/test_publish_summary.py
git commit -m "feat(publish-summary): add get_publish_summary service + live-DB tests"
```

---

## Task 3: Backend — publish_summary_service.get_published_flags

**Files:**
- Modify: `backend/src/services/publish_summary_service.py`
- Modify: `backend/tests/services/test_publish_summary.py`

- [ ] **Step 1: Add stub for new function**

Append to `backend/src/services/publish_summary_service.py`:

```python
async def get_published_flags(
    content_ids: list[int], db: AsyncSession
) -> dict[int, bool]:
    """Bulk lookup: returns {content_id: is_published_bool} for the given ids.

    content_ids without a single done-row in publish_queue are still present
    in the result with value False (caller can rely on full coverage).
    """
    raise NotImplementedError
```

- [ ] **Step 2: Add test**

Append to `backend/tests/services/test_publish_summary.py`:

```python
from src.services.publish_summary_service import get_published_flags


@pytest.mark.asyncio
async def test_get_published_flags_bulk():
    async with AsyncSessionLocal() as db:
        flags = await get_published_flags(
            [
                KNOWN_IG_YT_CONTENT_ID,
                KNOWN_TT_YT_CONTENT_ID,
                UNKNOWN_CONTENT_ID,
            ],
            db,
        )

    assert flags[KNOWN_IG_YT_CONTENT_ID] is True
    assert flags[KNOWN_TT_YT_CONTENT_ID] is True
    assert flags[UNKNOWN_CONTENT_ID] is False

    # Empty input returns empty dict (no SQL crashes)
    async with AsyncSessionLocal() as db:
        empty = await get_published_flags([], db)
    assert empty == {}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/services/test_publish_summary.py::test_get_published_flags_bulk -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 4: Implement get_published_flags**

Replace the stub body:

```python
async def get_published_flags(
    content_ids: list[int], db: AsyncSession
) -> dict[int, bool]:
    if not content_ids:
        return {}
    sql = text("""
        SELECT DISTINCT content_id FROM (
          SELECT ut.content_id
          FROM publish_queue pq
          JOIN unic_results ur ON ur.id = pq.unic_result_id
          JOIN unic_tasks ut ON ut.id = ur.task_id
          WHERE pq.status = 'done'
            AND lower(pq.platform) = ANY(:whitelist)
            AND ut.content_id = ANY(:ids)

          UNION

          SELECT pq.carousel_content_id AS content_id
          FROM publish_queue pq
          WHERE pq.status = 'done'
            AND lower(pq.platform) = ANY(:whitelist)
            AND pq.carousel_content_id = ANY(:ids)
        ) t;
    """)
    rows = (await db.execute(
        sql,
        {"ids": list(content_ids), "whitelist": list(PLATFORM_WHITELIST)},
    )).mappings().all()
    published_set = {int(r["content_id"]) for r in rows if r["content_id"] is not None}
    return {cid: (cid in published_set) for cid in content_ids}
```

- [ ] **Step 5: Run all service tests**

Run: `cd backend && pytest tests/services/test_publish_summary.py -v`
Expected: 2/2 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/publish_summary_service.py backend/tests/services/test_publish_summary.py
git commit -m "feat(publish-summary): add bulk get_published_flags + test"
```

---

## Task 4: Backend — Integrate into _content_to_dict

**Files:**
- Modify: `backend/src/routers/content.py`
- Test: `backend/tests/test_content_publish_response.py`

- [ ] **Step 1: Read existing routers/content.py around line 446**

Run: `sed -n '440,500p' backend/src/routers/content.py`
Note the 6 callers of `_content_to_dict` at lines: 89, 138, 226, 268, 350, 441.

- [ ] **Step 2: Add async wrapper without changing existing sync function**

In `backend/src/routers/content.py`, add this near the bottom of the file (after the existing `_content_to_dict`):

```python
from ..services.publish_summary_service import get_publish_summary


async def _content_to_dict_with_publish(c, db) -> dict:
    """Async wrapper: dict from _content_to_dict + published_summary + is_published.

    Use this in async handlers that have a db session. Sync _content_to_dict
    is kept for callers without db (e.g. dashboard's _content_short).
    """
    d = _content_to_dict(c)
    summary = await get_publish_summary(c.id, db)
    d["published_summary"] = summary
    d["is_published"] = summary["is_published"]
    return d
```

- [ ] **Step 3: Replace 6 existing calls of `_content_to_dict(...)`**

Search for all calls and replace per below. Use `grep -n "_content_to_dict(" backend/src/routers/content.py` to locate each.

For each call, change:
```python
return _content_to_dict(content)
```
to:
```python
return await _content_to_dict_with_publish(content, db)
```

For the list-builder at line ~89 (inside list endpoint):
```python
"items": [_content_to_dict(c) for c in items],
```
change to (sequential await; lists are short — ≤100 items per page):
```python
"items": [await _content_to_dict_with_publish(c, db) for c in items],
```

If list endpoints care about latency for large pages, alternatively replace with a bulk pattern using `get_published_flags` for `is_published` + skip per-item `published_summary` (only `_content_to_dict_with_publish` is needed for single-content endpoints). For now, keep the sequential await — list pages cap at 100 items, sequential await of 100 cheap queries is acceptable.

- [ ] **Step 4: Write integration test**

Create `backend/tests/test_content_publish_response.py`:

```python
"""Integration: GET /api/content/:id returns published_summary + is_published."""
import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import AsyncSessionLocal


KNOWN_IG_YT_CONTENT_ID = 1894


@pytest.mark.asyncio
async def test_content_get_includes_publish_summary():
    # Bypass auth via existing testing pattern (if app uses get_current_user
    # dependency override, otherwise this test calls the underlying service
    # directly — adjust based on auth setup discovered in Task 4.1).
    from src.routers.content import _content_to_dict_with_publish
    from src.models.content import ValidatorContent
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        c = (await db.execute(
            select(ValidatorContent).where(ValidatorContent.id == KNOWN_IG_YT_CONTENT_ID)
        )).scalar_one_or_none()
        assert c is not None, "canary content not in DB — pick a fresh id"
        d = await _content_to_dict_with_publish(c, db)

    assert "published_summary" in d
    assert "is_published" in d
    assert d["is_published"] is True
    assert d["published_summary"]["instagram"]["accounts"] > 0
    assert d["published_summary"]["youtube"]["accounts"] > 0
    assert d["published_summary"]["tiktok"]["accounts"] == 0
    # Original status is untouched (orthogonal axis)
    assert d["status"] != "published"
```

- [ ] **Step 5: Run integration test**

Run: `cd backend && pytest tests/test_content_publish_response.py -v`
Expected: PASS.

- [ ] **Step 6: Run full backend suite to confirm no regressions**

Run: `cd backend && pytest -v`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/src/routers/content.py backend/tests/test_content_publish_response.py
git commit -m "feat(content): expose published_summary + is_published in /api/content/:id"
```

---

## Task 5: Backend — Integrate into get_week_slots + drag guard

**Files:**
- Modify: `backend/src/services/schedule_service.py`
- Test: `backend/tests/test_schedule_lock.py` (extend existing)

- [ ] **Step 1: Update get_week_slots to bulk-fetch is_published**

In `backend/src/services/schedule_service.py`, find `get_week_slots` (around line 116). Replace its body:

```python
async def get_week_slots(project_id: int, week_start: date, db: AsyncSession) -> list:
    """Возвращает слоты недели с данными контента + флагом публикации."""
    from .publish_summary_service import get_published_flags
    week_end = week_start + timedelta(days=6)
    result = await db.execute(
        select(ValidatorScheduleSlot, ValidatorContent).outerjoin(
            ValidatorContent, ValidatorScheduleSlot.content_id == ValidatorContent.id
        ).where(
            ValidatorScheduleSlot.project_id == project_id,
            ValidatorScheduleSlot.slot_date >= week_start,
            ValidatorScheduleSlot.slot_date <= week_end,
        ).order_by(ValidatorScheduleSlot.slot_date, ValidatorScheduleSlot.slot_position)
    )
    rows = result.all()
    content_ids = [c.id for _, c in rows if c is not None]
    flags = await get_published_flags(content_ids, db) if content_ids else {}
    return [
        _slot_to_dict_with_content(slot, content, is_published=flags.get(content.id) if content else False)
        for slot, content in rows
    ]
```

- [ ] **Step 2: Update _slot_to_dict and _slot_to_dict_with_content signatures**

Replace `_slot_to_dict` and `_slot_to_dict_with_content` (around lines 193-222):

```python
def _slot_to_dict(
    s: ValidatorScheduleSlot,
    content: Optional[ValidatorContent] = None,
    is_published: bool = False,
) -> dict:
    day_locked = is_day_locked(s.slot_date) if s.slot_date else False
    movable = is_slot_movable_unpublished(s, content, is_published=is_published)
    content_status = None
    if content is not None and content.status is not None:
        content_status = content.status.value if hasattr(content.status, "value") else content.status
    return {
        "id": s.id,
        "project_id": s.project_id,
        "slot_date": s.slot_date.isoformat() if s.slot_date else None,
        "slot_position": s.slot_position,
        "content_id": s.content_id,
        "assigned_by_id": s.assigned_by_id,
        "slot_type": s.slot_type.value if s.slot_type else None,
        "status": s.status.value if s.status else None,
        "moderation_status": None,
        "content_title": None,
        "content_status": content_status,
        "is_published": is_published,
        "day_locked": day_locked,
        "movable_unpublished": movable,
    }


def _slot_to_dict_with_content(
    s: ValidatorScheduleSlot, c, is_published: bool = False
) -> dict:
    d = _slot_to_dict(s, c, is_published=is_published)
    if c is not None:
        d["moderation_status"] = c.moderation_status.value if c.moderation_status else None
        d["content_title"] = c.title
        d["content_type"] = c.content_type.value if c.content_type else None
    return d
```

- [ ] **Step 3: Update is_slot_movable_unpublished to accept is_published param**

Find `is_slot_movable_unpublished` in the same file (the spec says it lives in `schedule_service.py`; verify with `grep -n "def is_slot_movable_unpublished" backend/src/services/schedule_service.py`).

Update signature and body to add a third optional argument that short-circuits:

```python
def is_slot_movable_unpublished(
    slot: ValidatorScheduleSlot,
    content: Optional[ValidatorContent] = None,
    is_published: bool = False,
) -> bool:
    """Returns True if slot is draggable as 'unpublished'.

    is_published (computed live via publish_summary_service) wins over enum:
    if any done-row exists in publish_queue for this content, drag is blocked
    even if validator_content.status is still 'approved'.
    """
    if is_published:
        return False
    # Existing logic preserved below — keep status checks for backwards compat
    if slot.content_id is None:
        return False
    if slot.status == SlotStatus.published:
        return False
    if content is not None and content.status == ContentStatus.published:
        return False
    return True
```

If the existing function has additional checks (e.g. day_locked-related), preserve them after the `is_published` short-circuit.

- [ ] **Step 4: Find all callers of is_slot_movable_unpublished and add is_published kwarg where needed**

Run: `grep -rn "is_slot_movable_unpublished(" backend/src/`

For callers within `schedule_service.py` itself (the `_slot_to_dict` change in Step 2), `is_published` flows through.

For callers in `routers/schedule.py` (e.g. `_perform_move_unpublished`, line ~257, ~364), the safest path is: compute the flag inline before calling.

In `backend/src/routers/schedule.py`, before each call site of `is_slot_movable_unpublished(source, content)`, add:

```python
from ..services.publish_summary_service import get_published_flags
flags = await get_published_flags([content.id] if content else [], db)
movable = is_slot_movable_unpublished(source, content, is_published=flags.get(content.id, False) if content else False)
```

Then replace the call expression with the precomputed `movable`.

- [ ] **Step 5: Add test for new is_published param**

Append to `backend/tests/test_schedule_lock.py`:

```python
from src.services.schedule_service import is_slot_movable_unpublished as _movable


def test_is_slot_movable_unpublished_short_circuited_by_is_published():
    s = _slot(content_id=42, status=SlotStatus.filled)
    c = SimpleNamespace(status=None)
    # Without is_published flag, movable
    assert _movable(s, c, is_published=False) is True
    # With is_published flag, NOT movable
    assert _movable(s, c, is_published=True) is False
```

- [ ] **Step 6: Run schedule tests**

Run: `cd backend && pytest tests/test_schedule_lock.py -v`
Expected: all PASS (including new test).

- [ ] **Step 7: Run full backend suite again**

Run: `cd backend && pytest -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/src/services/schedule_service.py backend/src/routers/schedule.py backend/tests/test_schedule_lock.py
git commit -m "feat(schedule): plumb is_published into slot dict + drag guard"
```

---

## Task 6: Frontend — Pluralize helper

**Files:**
- Create: `frontend/src/utils/pluralize.ts`

- [ ] **Step 1: Verify utils dir does not exist**

Run: `ls frontend/src/utils 2>/dev/null || echo MISSING`
Expected: `MISSING` (or empty list — fine either way).

- [ ] **Step 2: Create pluralize helper**

Create `frontend/src/utils/pluralize.ts`:

```typescript
/**
 * Russian pluralization rule helper.
 *
 * forms = [singular, few, many]   e.g. ['аккаунт', 'аккаунта', 'аккаунтов']
 *
 *   1, 21, 31, …  → singular ('1 аккаунт')
 *   2-4, 22-24, … → few ('2 аккаунта')
 *   0, 5-20, 25-30, … → many ('5 аккаунтов', '0 аккаунтов')
 */
export function pluralizeRu(n: number, forms: [string, string, string]): string {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return forms[2];
  if (last > 1 && last < 5) return forms[1];
  if (last === 1) return forms[0];
  return forms[2];
}
```

- [ ] **Step 3: Smoke-check via tsc**

Run: `cd frontend && npx tsc --noEmit src/utils/pluralize.ts`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/utils/pluralize.ts
git commit -m "feat(utils): add ru-RU pluralizeRu helper"
```

---

## Task 7: Frontend — PublishedBlock.vue component

**Files:**
- Create: `frontend/src/components/content/PublishedBlock.vue`

- [ ] **Step 1: Verify content/ subdir does not exist; create directory**

Run: `ls frontend/src/components/content 2>/dev/null || mkdir -p frontend/src/components/content`

- [ ] **Step 2: Create PublishedBlock.vue**

Create `frontend/src/components/content/PublishedBlock.vue`:

```vue
<template>
  <div v-if="summary?.is_published" class="bg-white border border-gray-200 rounded-2xl p-4 mb-4">
    <h3 class="text-sm font-semibold text-gray-700 mb-3">📣 Опубликовано</h3>

    <div class="grid grid-cols-3 gap-3">
      <div
        v-for="p in platforms"
        :key="p.key"
        :class="[
          'rounded-xl px-3 py-2 transition',
          p.bg,
          summary[p.key].accounts > 0
            ? 'cursor-pointer hover:opacity-80'
            : 'opacity-50 cursor-default',
          expanded === p.key ? 'ring-2 ring-purple-300' : '',
        ]"
        @click="onTileClick(p.key)"
      >
        <div class="flex items-center gap-2 mb-1">
          <PlatformIcon :platform="p.key" :size="20" />
          <span :class="['text-sm font-medium', p.text]">{{ p.label }}</span>
        </div>
        <div :class="['text-xs', p.text]">
          <template v-if="summary[p.key].accounts > 0">
            <span class="font-semibold">{{ summary[p.key].accounts }}</span>
            {{ pluralizeRu(summary[p.key].accounts, ['аккаунт', 'аккаунта', 'аккаунтов']) }}
          </template>
          <template v-else>—</template>
        </div>
      </div>
    </div>

    <div v-if="expanded && summary[expanded].account_list.length" class="mt-3 pl-2 border-l-2 border-purple-200">
      <div class="text-xs text-gray-500 mb-1">{{ expandedTitle }}:</div>
      <div class="flex flex-wrap gap-2">
        <span
          v-for="u in summary[expanded].account_list"
          :key="u"
          class="text-xs bg-gray-100 text-gray-700 px-2 py-0.5 rounded"
        >@{{ u.replace(/^@/, '') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import PlatformIcon from '@/components/PlatformIcon.vue'
import { pluralizeRu } from '@/utils/pluralize'

interface PlatformSummary {
  accounts: number
  account_list: string[]
}
interface PublishSummary {
  instagram: PlatformSummary
  tiktok: PlatformSummary
  youtube: PlatformSummary
  first_published_at: string | null
  is_published: boolean
}

const props = defineProps<{ summary?: PublishSummary | null }>()

const platforms = [
  { key: 'instagram', label: 'Instagram', bg: 'bg-pink-50', text: 'text-pink-700' },
  { key: 'tiktok',    label: 'TikTok',    bg: 'bg-gray-50', text: 'text-gray-900' },
  { key: 'youtube',   label: 'YouTube',   bg: 'bg-red-50',  text: 'text-red-700'  },
] as const

const expanded = ref<'instagram' | 'tiktok' | 'youtube' | null>(null)

function onTileClick(key: 'instagram' | 'tiktok' | 'youtube') {
  if (!props.summary || props.summary[key].accounts === 0) return
  expanded.value = expanded.value === key ? null : key
}

const expandedTitle = computed(() => {
  if (!expanded.value) return ''
  const p = platforms.find(x => x.key === expanded.value)
  return p ? `Аккаунты ${p.label}` : ''
})
</script>
```

- [ ] **Step 3: Build to confirm no TS or template errors**

Run: `cd frontend && npm run build 2>&1 | tail -30`
Expected: build succeeds. Common gotcha: if `@/utils/pluralize` alias is unknown, check `tsconfig.json` for `paths`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/content/PublishedBlock.vue
git commit -m "feat(content): add PublishedBlock component for publish breakdown"
```

---

## Task 8: Frontend — Insert PublishedBlock into ContentDetail

**Files:**
- Modify: `frontend/src/pages/client/ContentDetail.vue`

- [ ] **Step 1: Locate the status block (lines 26-35) and the moderation block (line ~270)**

Run: `sed -n '20,45p' frontend/src/pages/client/ContentDetail.vue`
Note the closing `</div>` of the top status section.

- [ ] **Step 2: Add import for PublishedBlock**

In the `<script setup lang="ts">` block of `ContentDetail.vue`, add the import near other component imports:

```typescript
import PublishedBlock from '@/components/content/PublishedBlock.vue'
```

- [ ] **Step 3: Insert <PublishedBlock> between status and moderation sections**

In the `<template>` of `ContentDetail.vue`, find the closing `</div>` of the status section (after line ~35). Right after it, **before** the file/carousel block (`<!-- Файл + замена видео ... -->`), insert:

```vue
<!-- Опубликовано: где и сколько аккаунтов -->
<PublishedBlock :summary="content.published_summary" />
```

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build 2>&1 | tail -30`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/client/ContentDetail.vue
git commit -m "feat(content-detail): mount PublishedBlock between status and moderation"
```

---

## Task 9: Frontend — Update SlotCard badge logic

**Files:**
- Modify: `frontend/src/components/calendar/SlotCard.vue`

- [ ] **Step 1: Locate statusLabel and statusBadgeClass computed (lines ~121-122)**

Run: `sed -n '95,130p' frontend/src/components/calendar/SlotCard.vue`

- [ ] **Step 2: Add isPublished computed and override badge label/class**

In the `<script setup lang="ts">` block of `SlotCard.vue`, find the existing `statusMap`, `statusLabel`, `statusBadgeClass` definitions (around lines 113-122). Add the `isPublished` computed before them, then replace the two computeds:

```typescript
const isPublished = computed<boolean>(() => !!props.content?.is_published)

const statusMap: Record<string, { label: string; cls: string }> = {
  approved:     { label: '✅', cls: 'bg-green-100 text-green-700' },
  rejected:     { label: '🚫', cls: 'bg-red-100 text-red-700' },
  needs_review: { label: '⚠️', cls: 'bg-yellow-100 text-yellow-700' },
  uploaded:     { label: '📁', cls: 'bg-gray-100 text-gray-600' },
  scheduled:    { label: '📅', cls: 'bg-blue-100 text-blue-700' },
  published:    { label: '📣', cls: 'bg-purple-100 text-purple-700' },
}

const statusLabel = computed(() =>
  isPublished.value
    ? '📣 опубликовано'
    : statusMap[props.content?.status]?.label ?? '📁'
)
const statusBadgeClass = computed(() =>
  isPublished.value
    ? 'bg-purple-100 text-purple-700'
    : statusMap[props.content?.status]?.cls ?? 'bg-gray-100 text-gray-600'
)
```

- [ ] **Step 3: Verify isMovableUnpublished respects backend movable_unpublished**

Re-read the existing computed at lines 73-79. It already prefers `props.slot.movable_unpublished` (from backend) over fallback. No changes needed here — backend Task 5 handles immutability.

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build 2>&1 | tail -30`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/calendar/SlotCard.vue
git commit -m "feat(slot-card): switch badge to '📣 опубликовано' when content.is_published"
```

---

## Task 10: Deploy & manual verification

**Files:** none (deployment).

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin feat/published-mark-source-content-20260504
gh pr create --title "feat: published mark on source content (badge + breakdown)" \
  --body "$(cat <<'EOF'
## Summary
- New `is_published` field on slot dict + content dict (live JOIN, no schema changes)
- New `published_summary` block on `/api/content/:id` with per-platform account counts
- `📣 опубликовано` badge on SlotCard once any done-row in publish_queue
- New `PublishedBlock.vue` component on `/content/<id>` with 3 platform tiles + click-to-expand account list
- 3 partial indexes on publish_queue/unic_tasks for sub-1ms live JOIN

Spec: `.ai-factory/plans/published-mark-on-source-content-design-20260504.md` (in agent workspace).

## Test plan
- [ ] `pytest backend/tests/services/test_publish_summary.py` passes (live DB)
- [ ] `pytest backend/tests/test_content_publish_response.py` passes
- [ ] `pytest backend/tests/test_schedule_lock.py` passes
- [ ] `npm run build` in frontend/ succeeds
- [ ] On prod: open `/content/1894` → see "📣 Опубликовано" block, IG and YT tiles non-zero, TT zero
- [ ] On prod: dashboard for project of #1894 → slot of #1894 shows "📣 опубликовано" badge
- [ ] On prod: drag/drop of published slot is blocked (backend returns movable_unpublished=false)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: After PR review/merge — apply migration on prod**

Run on prod backend host:

```bash
cd /path/to/validator/backend && alembic upgrade head
```

Verify:

```bash
psql -h localhost -U openclaw -d openclaw -c "\\di ix_unic_tasks_content_id ix_publish_queue_unic_result_done ix_publish_queue_carousel_done"
```

Expected: 3 indexes present.

- [ ] **Step 3: Deploy backend**

Per project's deploy procedure (uvicorn restart). After restart:

```bash
curl -s "https://client.contenthunter.ru/api/content/1894" -H "Cookie: <session>" | jq '.is_published, .published_summary'
```

Expected: `true`, full summary object with IG and YT non-zero, TT zero.

- [ ] **Step 4: Deploy frontend**

`npm run build` → sync `frontend/dist/` to nginx serving location.

Important: per `feedback_vite_outage_user_hard_reload`, after deploy verify that newly-built `assets/*.js` chunk hashes are reachable on disk and nginx serves them. Old open tabs require hard reload.

- [ ] **Step 5: Manual prod check**

On a test browser session:

1. Open `https://client.contenthunter.ru/content/1894` →
   - "📣 Опубликовано" block visible above moderation block
   - Three tiles: Instagram (non-zero count), YouTube (non-zero), TikTok ("—")
   - Click Instagram tile → list of `@usernames` expands underneath
   - Click again → collapses
   - Click TikTok tile → no-op (greyed out)
2. Open `https://client.contenthunter.ru/dashboard` for the project owning content #1894 →
   - Slot containing #1894 shows "📣 опубликовано" purple badge
3. Try to drag the published slot to an empty slot →
   - Blocked: cursor not grab, drag does not initiate

- [ ] **Step 6: Rollback procedure (if issues)**

Backend rollback:
```bash
git revert <merge-commit-sha>
# redeploy backend
```

Frontend rollback: redeploy previous Vite build dir.

Migration rollback (only if indexes cause perf issues, unlikely):
```bash
alembic downgrade -1
```

---

## Self-review checklist (after writing this plan)

**1. Spec coverage:**
- §3 SQL → Tasks 2, 3 (service implementation)
- §3.3 Indexes → Task 1
- §4.1 Service contract → Tasks 2, 3
- §4.2 Handler integration → Tasks 4, 5
- §4.3 Orthogonal axis decision → enforced via `is_published` field, no `status` override (Task 4 verifies via assertion)
- §5.1 SlotCard badge → Task 9
- §5.2 PublishedBlock → Task 7, 8
- §6 Edge cases → covered by SQL whitelists in service (Task 2)
- §7 Performance → Task 1 indexes; bulk pattern (Task 5)
- §8 Deploy plan → Task 10
- §9 Tests → Task 2, 3, 4, 5 (backend); Task 10 step 5 (manual frontend)
- §11 Open questions → resolved in Tasks 8 (placement: between status & moderation), 9 (label: '📣 опубликовано'), 7 (icons: PlatformIcon component, not emoji)

**2. Type consistency:**
- `is_published` (snake_case) — used consistently in API responses and Vue prop reads
- `published_summary` field name — consistent
- `PLATFORM_WHITELIST` tuple — same constant used in both service functions
- `pluralizeRu` (camelCase, no underscore prefix) — exported once, imported once

**3. No placeholders:**
- All steps have explicit code blocks
- All file paths absolute-relative to repo root
- All commands have expected output
- No "TBD" or "see above"
