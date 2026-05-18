# WP #77 — Content-hash Dedupe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить duration+size эвристику в video uniqueness на sha256(file_bytes), убрать массовые false-positives, разблокировать исторические записи через backfill.

**Architecture:** В двух местах video upload (`upload.py`, `content.py:replace-video`) считаем `sha256(file_bytes).hexdigest()` и пишем в `validator_content.content_hash`. `check_uniqueness` ищет совпадение `content_hash` в рамках того же `project_id` и `content_type=video`. Старая duration+size эвристика удаляется. Однократный backfill-скрипт пересчитывает hash для исторических записей и корректно сбрасывает false-positives.

**Tech Stack:** Python 3 + FastAPI + SQLAlchemy async + asyncpg + boto3 (S3) + pytest-asyncio (backend); Vue 3 + Vite (frontend); Postgres 14 (`openclaw` DB, table `validator_content`).

**Spec:** `docs/superpowers/specs/2026-05-18-wp77-duplicate-false-positive-design.md`

**Repo:** `/home/claude-user/validator-contenthunter` (GitHub: `GenGo2/validator-contenthunter`, default branch `main`).

---

## File Map

**Backend — modify:**
- `backend/src/services/uniqueness_service.py` — переписать целиком (старая duration+size логика → content_hash lookup)
- `backend/src/routers/upload.py` (≈line 312) — добавить sha256 для video upload
- `backend/src/routers/content.py` (≈line 381 в replace-video) — добавить sha256, убрать ручной сброс is_duplicate
- `backend/src/routers/validation.py` (≈line 113) — обновить сигнатуру вызова `check_uniqueness`

**Backend — create:**
- `backend/scripts/__init__.py` — если ещё нет, пустой
- `backend/scripts/backfill_content_hash.py` — однократный management script + S3 stream-hash helper
- `backend/tests/test_uniqueness_hash.py` — 4 runtime теста + 2 backfill теста
- `backend/tests/fixtures/sample_video_a.mp4` — fixture для identical-test (~15 КБ)
- `backend/tests/fixtures/sample_video_b.mp4` — fixture с тем же duration, близким size, разными байтами (~15 КБ)

**Frontend — modify:**
- `frontend/src/pages/client/ContentDetail.vue` (lines 345-347) — banner-текст
- `frontend/src/components/validation/ValidationDetails.vue` (lines 85-87) — banner-текст

**Не трогаем:**
- `backend/alembic/` — миграция не требуется, столбец и индекс уже есть в `ValidatorContent`
- Permission-модель approve-кнопки
- Carousel/post uniqueness

---

## Phase 1: Setup

### Task 1: Worktree + sanity check

**Files:**
- Worktree path: `/home/claude-user/validator-contenthunter-wp77-content-hash-20260518`
- Branch: `feat/wp77-content-hash-dedupe`

- [ ] **Step 1: Create worktree from latest main**

```bash
cd /home/claude-user/validator-contenthunter
git fetch origin main
git worktree add -b feat/wp77-content-hash-dedupe \
  /home/claude-user/validator-contenthunter-wp77-content-hash-20260518 \
  origin/main
cd /home/claude-user/validator-contenthunter-wp77-content-hash-20260518
git log -1 --oneline
```

Expected: HEAD points to current `origin/main` tip.

- [ ] **Step 2: Sanity-check that test infra works**

```bash
cd /home/claude-user/validator-contenthunter-wp77-content-hash-20260518/backend
python -m pytest tests/test_payload_hash.py -v 2>&1 | tail -20
```

Expected: at least one existing test passes. If `pytest` not found, check existing venv (`source .venv/bin/activate`) or how prior tests were run in this repo (`README.md`, `pyproject.toml`).

- [ ] **Step 3: Confirm DB connectivity**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -c "SELECT COUNT(*) FROM validator_content WHERE content_type='video'"
```

Expected: a number returns (real production data; do NOT mutate).

---

## Phase 2: Test fixtures

### Task 2: Generate sample video fixtures via ffmpeg

**Files:**
- Create: `backend/tests/fixtures/sample_video_a.mp4`
- Create: `backend/tests/fixtures/sample_video_b.mp4`

Both must: contain a video stream AND an audio stream (preflight rejects no-audio), small (<50 КБ), same duration (~2с), have different byte content. We can NOT just generate one and copy — we need genuinely different bytes to test the regression-guard scenario.

- [ ] **Step 1: Create fixtures directory**

```bash
mkdir -p backend/tests/fixtures
```

- [ ] **Step 2: Generate sample_video_a.mp4 (red testsrc + 440Hz sine)**

```bash
ffmpeg -y -f lavfi -i testsrc=size=320x180:rate=10:duration=2 \
       -f lavfi -i sine=frequency=440:duration=2 \
       -c:v libx264 -preset ultrafast -tune zerolatency \
       -c:a aac -shortest -movflags +faststart \
       backend/tests/fixtures/sample_video_a.mp4
```

- [ ] **Step 3: Generate sample_video_b.mp4 (different content, similar size/duration)**

```bash
ffmpeg -y -f lavfi -i "color=c=blue:size=320x180:rate=10:duration=2" \
       -f lavfi -i "sine=frequency=880:duration=2" \
       -c:v libx264 -preset ultrafast -tune zerolatency \
       -c:a aac -shortest -movflags +faststart \
       backend/tests/fixtures/sample_video_b.mp4
```

- [ ] **Step 4: Verify properties**

```bash
ls -la backend/tests/fixtures/
ffprobe -v error -show_entries format=duration,size -of default=nw=1 \
  backend/tests/fixtures/sample_video_a.mp4
ffprobe -v error -show_entries format=duration,size -of default=nw=1 \
  backend/tests/fixtures/sample_video_b.mp4
sha256sum backend/tests/fixtures/sample_video_*.mp4
```

Expected: оба ~2с длиной, размеры в пределах 5% друг от друга (т.е. сценарий «duration/size почти равны»), sha256 — РАЗНЫЕ.

If sizes ended up >5% apart — regenerate b with similar tune/preset until close. If sizes are accidentally identical bytewise (highly unlikely with different inputs) — change `frequency` to 660Hz and retry.

- [ ] **Step 5: Commit fixtures**

```bash
git add backend/tests/fixtures/sample_video_a.mp4 backend/tests/fixtures/sample_video_b.mp4
git commit -m "test(uniqueness): add sample mp4 fixtures for hash dedupe tests"
```

---

## Phase 3: Backend — uniqueness_service + write-points (TDD)

### Task 3: Failing test — identical files → duplicate

**Files:**
- Create: `backend/tests/test_uniqueness_hash.py`

- [ ] **Step 1: Write test_identical_files_marked_duplicate**

```python
# backend/tests/test_uniqueness_hash.py
"""WP #77 — content_hash sha256 dedupe.

Live-DB tests (autouse engine.dispose fixture in conftest.py).
Each test uses a unique project_id (picked >= 10_000 to avoid clashes
with production) and cleans up its own rows in teardown.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from src.database import AsyncSessionLocal  # confirmed in src/database.py:20
from src.models.content import (
    ContentStatus,
    ContentType,
    ModerationStatus,
    ValidatorContent,
)
from src.services.uniqueness_service import check_uniqueness


FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_A = FIXTURES / "sample_video_a.mp4"
SAMPLE_B = FIXTURES / "sample_video_b.mp4"


def _sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


async def _insert_video(
    db,
    *,
    project_id: int,
    content_hash: str | None,
    is_duplicate: bool = False,
    duplicate_of_id: int | None = None,
    status: ContentStatus = ContentStatus.uploaded,
    moderation_status: ModerationStatus = ModerationStatus.passed,
    duration: float = 2.0,
    file_size: int | None = None,
    uploader_id: int = 1,  # any existing validator_user id; see conftest
) -> ValidatorContent:
    row = ValidatorContent(
        uploader_id=uploader_id,
        project_id=project_id,
        content_type=ContentType.video,
        content_hash=content_hash,
        is_duplicate=is_duplicate,
        duplicate_of_id=duplicate_of_id,
        status=status,
        moderation_status=moderation_status,
        duration_seconds=duration,
        file_size_bytes=file_size or 12345,
        # Unique s3_key per row even when content_hash is NULL — otherwise
        # multiple NULL-hash seeded rows collide on the same key and the
        # backfill test mock collapses them into one entry.
        s3_key=f"test/wp77/{project_id}/{content_hash or 'nohash-' + uuid.uuid4().hex[:12]}.mp4",
        s3_url=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest_asyncio.fixture
async def clean_project_99001():
    """Reserved project_id for this test; cleanup after."""
    pid = 99001
    yield pid
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ValidatorContent).where(ValidatorContent.project_id == pid)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_identical_files_marked_duplicate(clean_project_99001):
    pid = clean_project_99001
    sha = _sha256_of(SAMPLE_A)
    async with AsyncSessionLocal() as db:
        first = await _insert_video(db, project_id=pid, content_hash=sha)
        second = await _insert_video(db, project_id=pid, content_hash=sha)

        result = await check_uniqueness(pid, sha, second.id, db)

    assert result["is_duplicate"] is True
    assert result["duplicate_of_id"] == first.id
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd backend
python -m pytest tests/test_uniqueness_hash.py::test_identical_files_marked_duplicate -v 2>&1 | tail -20
```

Expected: **FAIL** — old `check_uniqueness` has signature `(project_id, duration, file_size, content_id, db)`, not `(project_id, content_hash, content_id, db)`. Should error with TypeError or assertion fail.

(Sanity: `AsyncSessionLocal` is confirmed exported from `src/database.py:20` — see existing usage in `tests/test_account_packages_migration_smoke.py:17`.)

- [ ] **Step 3: Confirm uploader_id=1 exists**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -c "SELECT id, login FROM validator_users ORDER BY id LIMIT 5"
```

If id=1 doesn't exist, change `uploader_id=1` default to a real id from the query.

---

### Task 4: Rewrite uniqueness_service + add sha256 in upload — make test pass

**Files:**
- Modify: `backend/src/services/uniqueness_service.py` (rewrite)
- Modify: `backend/src/routers/upload.py` (add sha256 in video branch)
- Modify: `backend/src/routers/validation.py:113` (new call signature)

- [ ] **Step 1: Rewrite `uniqueness_service.py`**

Replace entire file with:

```python
"""WP #77 — content_hash (sha256) based dedupe for video uploads.

A duplicate is a byte-identical file uploaded twice into the same project.
We do NOT try to catch "re-encoded" copies — that's a separate feature.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.content import ContentType, ValidatorContent

log = logging.getLogger(__name__)


async def check_uniqueness(
    project_id: int,
    content_hash: Optional[str],
    content_id: int,
    db: AsyncSession,
) -> dict:
    """
    Returns {"is_duplicate": bool, "duplicate_of_id": int | None}.

    Rule: "original" = lowest id within the hash-group (project_id +
    content_hash + content_type='video'), INCLUDING the row being checked.
    If the current row IS the lowest id → not a duplicate. Otherwise →
    duplicate, with duplicate_of_id = the lowest id.

    This avoids flipping the original into a duplicate when validation
    is re-run after a later identical upload was added.
    """
    if not content_hash:
        log.info("uniqueness: content_id=%s skipped (no hash)", content_id)
        return {"is_duplicate": False, "duplicate_of_id": None}

    result = await db.execute(
        select(func.min(ValidatorContent.id))
        .where(
            ValidatorContent.project_id == project_id,
            ValidatorContent.content_hash == content_hash,
            ValidatorContent.content_type == ContentType.video,
        )
    )
    min_id = result.scalar_one_or_none()
    log.info(
        "uniqueness: content_id=%s project=%s min_in_group=%s",
        content_id, project_id, min_id,
    )
    if min_id is None or min_id == content_id:
        return {"is_duplicate": False, "duplicate_of_id": None}
    return {"is_duplicate": True, "duplicate_of_id": min_id}
```

- [ ] **Step 2: Update `routers/validation.py` call site**

Find lines around 113-118 (`uniq = await check_uniqueness(...)`) and replace with:

```python
    # Уникальность (sha256 в рамках project_id, только video)
    uniq = await check_uniqueness(
        content.project_id, content.content_hash, content.id, db
    )
    content.is_duplicate = uniq["is_duplicate"]
    content.duplicate_of_id = uniq["duplicate_of_id"]
```

- [ ] **Step 3: Add sha256 in `routers/upload.py` (video branch)**

Locate `file_bytes = await file.read()` near line 312 (the video upload handler — confirm by reading 280-340 to find the video-specific endpoint, NOT the carousel files-list handler at line 427).

Just after `file_bytes = await file.read()` and BEFORE the `content = ValidatorContent(...)` creation, compute hash. If `hashlib` is not already imported at top of file, add `import hashlib`.

When creating the new `ValidatorContent`, include `content_hash=hashlib.sha256(file_bytes).hexdigest()` in the kwargs. If creation is done in multiple stages (create then set attributes), set `content.content_hash = hashlib.sha256(file_bytes).hexdigest()` before the first commit.

Concrete diff sketch (verify exact context first by reading lines 295-340):

```python
    file_bytes = await file.read()
    actual_size = len(file_bytes)
    content_hash = hashlib.sha256(file_bytes).hexdigest()  # WP #77
    # ... existing preflight + s3 upload ...
    # When the ValidatorContent row is created/updated, set:
    content.content_hash = content_hash
```

Carousel/post upload (≈line 427) — do NOT touch.

- [ ] **Step 4: Run failing test — expect PASS now**

```bash
cd backend
python -m pytest tests/test_uniqueness_hash.py::test_identical_files_marked_duplicate -v 2>&1 | tail -20
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/uniqueness_service.py \
        backend/src/routers/validation.py \
        backend/src/routers/upload.py \
        backend/tests/test_uniqueness_hash.py
git commit -m "feat(uniqueness): content_hash sha256 dedupe for video (WP #77)"
```

---

### Task 5: Add regression-guard tests (different files, cross-project)

**Files:**
- Modify: `backend/tests/test_uniqueness_hash.py` (append two tests)

- [ ] **Step 1: Add `test_different_files_not_duplicate`**

Append to the test file:

```python
@pytest_asyncio.fixture
async def clean_project_99002():
    pid = 99002
    yield pid
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ValidatorContent).where(ValidatorContent.project_id == pid)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_different_files_not_duplicate(clean_project_99002):
    """Regression-guard: two videos with near-equal duration/size but
    different bytes must NOT be flagged as duplicates (the old heuristic
    bug)."""
    pid = clean_project_99002
    sha_a = _sha256_of(SAMPLE_A)
    sha_b = _sha256_of(SAMPLE_B)
    assert sha_a != sha_b, "fixtures must have different bytes"

    async with AsyncSessionLocal() as db:
        first = await _insert_video(db, project_id=pid, content_hash=sha_a)
        second = await _insert_video(db, project_id=pid, content_hash=sha_b)

        r1 = await check_uniqueness(pid, sha_a, first.id, db)
        r2 = await check_uniqueness(pid, sha_b, second.id, db)

    assert r1["is_duplicate"] is False
    assert r2["is_duplicate"] is False
```

- [ ] **Step 2: Add `test_same_file_different_projects`**

```python
@pytest_asyncio.fixture
async def clean_projects_99003_99004():
    pids = (99003, 99004)
    yield pids
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ValidatorContent).where(
                ValidatorContent.project_id.in_(pids)
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_same_file_different_projects(clean_projects_99003_99004):
    """Project isolation: same hash in two different projects → no dup."""
    pid_x, pid_y = clean_projects_99003_99004
    sha = _sha256_of(SAMPLE_A)

    async with AsyncSessionLocal() as db:
        row_x = await _insert_video(db, project_id=pid_x, content_hash=sha)
        row_y = await _insert_video(db, project_id=pid_y, content_hash=sha)

        r_x = await check_uniqueness(pid_x, sha, row_x.id, db)
        r_y = await check_uniqueness(pid_y, sha, row_y.id, db)

    assert r_x["is_duplicate"] is False
    assert r_y["is_duplicate"] is False
```

- [ ] **Step 3: Run both new tests — expect PASS without code change**

```bash
cd backend
python -m pytest tests/test_uniqueness_hash.py::test_different_files_not_duplicate \
                  tests/test_uniqueness_hash.py::test_same_file_different_projects -v 2>&1 | tail -20
```

Expected: both PASS. The code from Task 4 already handles these correctly.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_uniqueness_hash.py
git commit -m "test(uniqueness): regression-guard + cross-project isolation (WP #77)"
```

---

### Task 6: replace-video — recompute hash on file change

**Files:**
- Modify: `backend/src/routers/content.py` (≈line 381 in replace-video)

⚠️ This task has NO dedicated unit test. The endpoint requires multipart + S3 + auth plumbing that isn't worth replicating just for a one-line hash assignment; a mirrored unit-test would only re-prove `hashlib.sha256` works. Coverage for the change comes from:
1. **Codex review of the PR diff** (Task 12) — confirms the line is present and correctly placed.
2. **Production smoke** (Task 13) — after `--apply`, records 2123/2132 are verified to have `content_hash` set; if replace-video had been used on any historical record and the hash hadn't been recomputed, that record's hash would mismatch its bytes.
3. **Manual QA** after deploy — upload a video, then replace it with a different file via the UI, confirm via DB query that `content_hash` reflects the new file's sha256.

- [ ] **Step 1: Update `content.py` replace-video handler**

Read lines 370-430 of `backend/src/routers/content.py` to confirm context. Locate `file_bytes = await file.read()` at ~line 381.

If `hashlib` not yet imported at top of file, add `import hashlib`.

Insert right after `actual_size = len(file_bytes)` (≈line 382):

```python
    # WP #77 — пересчитываем content_hash при замене видео
    content.content_hash = hashlib.sha256(file_bytes).hexdigest()
```

Lines 423-424 (`content.is_duplicate = False` / `content.duplicate_of_id = None`) can be removed — `_do_full_validation` reruns `check_uniqueness` which now returns the correct boolean based on the new hash. Removing them keeps the code DRY.

- [ ] **Step 2: Commit**

```bash
git add backend/src/routers/content.py
git commit -m "feat(content): recompute content_hash on replace-video (WP #77)"
```

---

### Task 7: Full backend test run + smoke

- [ ] **Step 1: Run full pytest**

```bash
cd backend
python -m pytest tests/ -x -v 2>&1 | tail -40
```

Expected: zero new failures. If something unrelated was already red on `main` (see [[project_validator_stale_generate_description_tests.md]] — two stale anthropic-mock tests in `test_fixes_2026_04_20.py`), it stays red — that's not your regression.

- [ ] **Step 2: If any new failures — diagnose**

If `check_uniqueness` is called from anywhere besides `validation.py` (search: `grep -rn check_uniqueness backend/src`), update those call sites to the new signature too.

---

## Phase 4: Backfill

### Task 8: Backfill script — S3 stream-hash helper + main loop

**Files:**
- Create: `backend/scripts/__init__.py` (empty, if not exists)
- Create: `backend/scripts/backfill_content_hash.py`

- [ ] **Step 1: Ensure scripts is a package**

```bash
test -f backend/scripts/__init__.py || (mkdir -p backend/scripts && touch backend/scripts/__init__.py)
```

- [ ] **Step 2: Write backfill script**

Create `backend/scripts/backfill_content_hash.py`:

```python
"""WP #77 — one-shot backfill of content_hash for legacy video rows.

Re-hashes every video in validator_content where content_hash IS NULL,
re-evaluates is_duplicate by the new rule, and lifts the status of
records that were stuck in needs_review purely because of the old
false-positive heuristic.

NEVER calls Delivery webhook. NEVER touches rows with content_type != 'video'.

Usage:
    python -m scripts.backfill_content_hash --dry-run
    python -m scripts.backfill_content_hash --apply
    python -m scripts.backfill_content_hash --apply --limit 100
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.content import (
    ContentStatus,
    ContentType,
    ModerationStatus,
    ValidatorContent,
)
from src.services.uniqueness_service import check_uniqueness

log = logging.getLogger("backfill_content_hash")


class S3KeyMissing(Exception):
    pass


def stream_sha256_from_s3(s3_key: str, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Read object from S3 in chunks, return hex sha256.

    Synchronous — boto3 has no native async. Called inside asyncio via
    loop.run_in_executor in main() to avoid blocking the event loop.
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
    try:
        obj = s3.get_object(Bucket=settings.s3_bucket, Key=s3_key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            raise S3KeyMissing(s3_key) from e
        raise

    h = hashlib.sha256()
    body = obj["Body"]
    while True:
        chunk = body.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
    return h.hexdigest()


@dataclass
class Stats:
    processed: int = 0
    marked_duplicate: int = 0
    auto_unblocked: int = 0
    skipped_missing: int = 0
    errors: int = 0
    auto_unblock_sample: list[int] = field(default_factory=list)


async def run_backfill(*, dry_run: bool, limit: Optional[int]) -> Stats:
    stats = Stats()
    loop = asyncio.get_running_loop()

    async with AsyncSessionLocal() as db:
        q = (
            select(ValidatorContent)
            .where(
                ValidatorContent.content_type == ContentType.video,
                ValidatorContent.content_hash.is_(None),
                ValidatorContent.s3_key.isnot(None),
            )
            .order_by(ValidatorContent.id.asc())
        )
        if limit is not None:
            q = q.limit(limit)
        rows = (await db.execute(q)).scalars().all()
        log.info("backfill: %d candidate rows", len(rows))

        for content in rows:
            try:
                sha = await loop.run_in_executor(
                    None, stream_sha256_from_s3, content.s3_key
                )
            except S3KeyMissing:
                stats.skipped_missing += 1
                log.warning("skip id=%s s3_key=%s — missing in S3",
                            content.id, content.s3_key)
                continue
            except Exception as e:  # noqa: BLE001
                stats.errors += 1
                log.error("error id=%s s3_key=%s: %s", content.id, content.s3_key, e)
                continue

            stats.processed += 1
            if dry_run:
                log.info("would set id=%s hash=%s", content.id, sha[:12])
                continue

            content.content_hash = sha
            uniq = await check_uniqueness(content.project_id, sha, content.id, db)
            was_blocked_by_dup = (
                content.is_duplicate is True
                and content.status == ContentStatus.needs_review
                and content.moderation_status == ModerationStatus.passed
            )
            content.is_duplicate = uniq["is_duplicate"]
            content.duplicate_of_id = uniq["duplicate_of_id"]
            if not uniq["is_duplicate"] and was_blocked_by_dup:
                content.status = ContentStatus.approved
                stats.auto_unblocked += 1
                if len(stats.auto_unblock_sample) < 10:
                    stats.auto_unblock_sample.append(content.id)
            if uniq["is_duplicate"]:
                stats.marked_duplicate += 1
            await db.commit()

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="Compute hashes and log what WOULD change, but DO NOT write to DB.")
    g.add_argument("--apply", action="store_true",
                   help="Write content_hash and recompute is_duplicate/status.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Optional cap on rows processed in one run.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stats = asyncio.run(run_backfill(dry_run=args.dry_run, limit=args.limit))
    log.info("DONE %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify it imports and parses --help**

```bash
cd backend
python -m scripts.backfill_content_hash --help 2>&1 | tail -15
```

Expected: argparse help output. If `ModuleNotFoundError`, check `PYTHONPATH=src` or whether existing scripts use a different import pattern; mirror that.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/__init__.py backend/scripts/backfill_content_hash.py
git commit -m "feat(scripts): backfill content_hash for legacy video rows (WP #77)"
```

---

### Task 9: Backfill test — false-positive unblock

**Files:**
- Modify: `backend/tests/test_uniqueness_hash.py` (append test 5)

- [ ] **Step 1: Add test 5**

Append:

```python
@pytest_asyncio.fixture
async def clean_project_99006():
    pid = 99006
    yield pid
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ValidatorContent).where(ValidatorContent.project_id == pid)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_backfill_false_positive_unblocks(clean_project_99006, monkeypatch):
    """Mirrors production case: first video is the old "original"
    (already approved), second was wrongly tagged is_duplicate by the
    legacy heuristic. After backfill the second is_duplicate=False and
    is lifted from needs_review→approved. Delivery webhook NOT called."""
    pid = clean_project_99006
    sha_a = _sha256_of(SAMPLE_A)
    sha_b = _sha256_of(SAMPLE_B)
    assert sha_a != sha_b

    async with AsyncSessionLocal() as db:
        first = await _insert_video(
            db, project_id=pid, content_hash=None,
            is_duplicate=False, status=ContentStatus.approved,
            moderation_status=ModerationStatus.passed,
        )
        second = await _insert_video(
            db, project_id=pid, content_hash=None,
            is_duplicate=True, duplicate_of_id=first.id,
            status=ContentStatus.needs_review,
            moderation_status=ModerationStatus.passed,
        )

    from scripts import backfill_content_hash as bf
    hash_by_s3_key = {first.s3_key: sha_a, second.s3_key: sha_b}

    def fake_hash(key, chunk_size=0):
        if key in hash_by_s3_key:
            return hash_by_s3_key[key]
        raise bf.S3KeyMissing(key)

    monkeypatch.setattr(bf, "stream_sha256_from_s3", fake_hash)

    await bf.run_backfill(dry_run=False, limit=None)

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ValidatorContent).where(ValidatorContent.project_id == pid)
                .order_by(ValidatorContent.id.asc())
        )).scalars().all()
    assert len(rows) == 2
    a, b = rows
    assert a.content_hash == sha_a and a.is_duplicate is False
    assert a.status == ContentStatus.approved  # unchanged (was already approved)
    assert b.content_hash == sha_b and b.is_duplicate is False
    assert b.status == ContentStatus.approved  # promoted from needs_review
```

Note: `run_backfill(limit=None)` will pick up production rows too. To isolate, either:
- Pass `limit=2` and seed exactly two NULL-hash rows (which we did), OR
- Filter `monkeypatch` to fail for unknown s3_key, marking other rows as errors.

Recommended: seed with two known rows and assert relative changes on those two. Don't assert exact stats counts.

- [ ] **Step 2: Run test — expect PASS**

```bash
cd backend
python -m pytest tests/test_uniqueness_hash.py::test_backfill_false_positive_unblocks -v 2>&1 | tail -20
```

Note: `run_backfill(limit=None)` will scan all NULL-hash rows in the DB, but the `fake_hash` mock raises `S3KeyMissing` for any key it doesn't know — so all unrelated production rows are counted as `skipped_missing` and left untouched. Our two test rows are the only ones that get hashed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_uniqueness_hash.py
git commit -m "test(backfill): false-positive auto-unblock without webhook (WP #77)"
```

---

### Task 10: Backfill test — real duplicate stays blocked

**Files:**
- Modify: `backend/tests/test_uniqueness_hash.py` (append test 6)

- [ ] **Step 1: Add test 6**

```python
@pytest_asyncio.fixture
async def clean_project_99007():
    pid = 99007
    yield pid
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ValidatorContent).where(ValidatorContent.project_id == pid)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_backfill_real_duplicate_stays_blocked(clean_project_99007, monkeypatch):
    """Two IDENTICAL videos → backfill keeps second is_duplicate=True
    and status=needs_review (real-positive must NOT be auto-unblocked)."""
    pid = clean_project_99007
    sha = _sha256_of(SAMPLE_A)

    async with AsyncSessionLocal() as db:
        first = await _insert_video(
            db, project_id=pid, content_hash=None,
            is_duplicate=False, status=ContentStatus.approved,
            moderation_status=ModerationStatus.passed,
        )
        second = await _insert_video(
            db, project_id=pid, content_hash=None,
            is_duplicate=True, duplicate_of_id=first.id,
            status=ContentStatus.needs_review,
            moderation_status=ModerationStatus.passed,
        )

    from scripts import backfill_content_hash as bf
    same_hash = {first.s3_key: sha, second.s3_key: sha}

    def fake_hash(key, chunk_size=0):
        if key in same_hash:
            return same_hash[key]
        raise bf.S3KeyMissing(key)

    monkeypatch.setattr(bf, "stream_sha256_from_s3", fake_hash)

    await bf.run_backfill(dry_run=False, limit=None)

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ValidatorContent).where(ValidatorContent.project_id == pid)
                .order_by(ValidatorContent.id.asc())
        )).scalars().all()
    a, b = rows
    # Original — hash recorded, status unchanged (already approved)
    assert a.content_hash == sha and a.is_duplicate is False
    assert a.status == ContentStatus.approved
    # Second is a real duplicate — STAYS blocked
    assert b.content_hash == sha
    assert b.is_duplicate is True
    assert b.duplicate_of_id == a.id
    assert b.status == ContentStatus.needs_review
```

- [ ] **Step 2: Run test — expect PASS**

```bash
cd backend
python -m pytest tests/test_uniqueness_hash.py::test_backfill_real_duplicate_stays_blocked -v 2>&1 | tail -20
```

- [ ] **Step 3: Run ALL new tests together**

```bash
cd backend
python -m pytest tests/test_uniqueness_hash.py -v 2>&1 | tail -30
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_uniqueness_hash.py
git commit -m "test(backfill): real-positive duplicate stays blocked (WP #77)"
```

---

## Phase 5: Frontend

### Task 11: Banner text in two Vue files

**Files:**
- Modify: `frontend/src/pages/client/ContentDetail.vue` (lines 345-347)
- Modify: `frontend/src/components/validation/ValidationDetails.vue` (lines 85-87)

⚠️ **Do NOT run `npm run build` yet** — there is a postbuild hook that auto-deploys to `/var/www/validator/` ([[feedback_validator_postbuild_autodeploy.md]]). Build only at deploy time, not during local edit.

- [ ] **Step 1: Update `ContentDetail.vue`**

Read lines 340-360 of the file to confirm current content. Replace the banner block (was: `⚠️ Похоже на дубликат контента #{{ content.duplicate_of_id }}`) with:

```vue
          <div v-if="content.is_duplicate" class="mt-3 bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-sm text-yellow-800">
            🛑 Это точная копия контента
            <router-link :to="`/content/${content.duplicate_of_id}`" class="underline">
              #{{ content.duplicate_of_id }}
            </router-link>
            (тот же файл)
          </div>
```

Keep the surrounding container classes byte-identical — only the inner text/markup changes.

- [ ] **Step 2: Update `ValidationDetails.vue`**

Same edit pattern at lines 85-87:

```vue
    <div v-if="content.is_duplicate" class="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-sm text-yellow-800">
      🛑 Это точная копия контента
      <router-link :to="`/content/${content.duplicate_of_id}`" class="underline">
        #{{ content.duplicate_of_id }}
      </router-link>
      (тот же файл)
    </div>
```

- [ ] **Step 3: Confirm no other render-points exist**

```bash
grep -rn "Похоже на дубликат\|похож.*дубликат" frontend/src/
```

Expected: no remaining hits (or only in already-updated files).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/client/ContentDetail.vue \
        frontend/src/components/validation/ValidationDetails.vue
git commit -m "ui(content): clearer banner for exact-duplicate (WP #77)"
```

---

## Phase 6: Quality gate

### Task 12: Codex review of code changes

- [ ] **Step 1: Push branch (no PR yet)**

```bash
git push -u origin feat/wp77-content-hash-dedupe
```

- [ ] **Step 2: Run codex review on the full branch diff**

Codex `--base main` is broken ([[feedback_codex_sandbox_broken.md]]), use stdin:

```bash
git diff origin/main...HEAD | ~/.local/bin/codex review - 2>&1 | tail -80
```

- [ ] **Step 3: Apply P1 fixes, re-run**

For each P1 issue: fix → re-stage → re-run codex review until 0 P1.

- [ ] **Step 4: Commit any fixes**

```bash
git add -u
git commit -m "fix: codex review P1 (WP #77)"
git push
```

---

### Task 13: dry-run on real production data

⚠️ Read-only operation by design — `--dry-run` does NOT write to DB.

- [ ] **Step 1: Estimate volume**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT COUNT(*) AS rows,
       pg_size_pretty(SUM(file_size_bytes)) AS total_bytes
FROM validator_content
WHERE content_type='video' AND content_hash IS NULL AND s3_key IS NOT NULL
"
```

If estimated download is "huge" (multi-TB or 1000s of files), pause and discuss with user before continuing. For moderate volume (<200 GB), proceed.

- [ ] **Step 2: Dry-run with small limit first**

```bash
cd backend
python -m scripts.backfill_content_hash --dry-run --limit 5 2>&1 | tail -30
```

Expected: 5 "would set id=… hash=…" log lines, no exceptions, no DB writes.

- [ ] **Step 3: Full dry-run**

```bash
cd backend
python -m scripts.backfill_content_hash --dry-run 2>&1 | tee /tmp/wp77_backfill_dryrun.log | tail -30
```

Examine `/tmp/wp77_backfill_dryrun.log` for:
- total `processed` count
- `skipped_missing` count (S3 keys gone — acceptable, log id list)
- any `errors`

- [ ] **Step 4: Verify pair 2120/2123, 2130/2132 hashes in the log**

```bash
grep -E "id=(2120|2123|2130|2132)" /tmp/wp77_backfill_dryrun.log
```

Expected: each id has a `would set … hash=<12-char prefix>` line; 2120's hash != 2123's hash; 2130's hash != 2132's hash. This is the definitive proof that the false-positives will be released.

If hashes accidentally match — there's a real duplicate, escalate (do NOT auto-unblock those).

---

## Phase 7: PR + Deploy

### Task 14: Open pull request

- [ ] **Step 1: Push (if not already)**

```bash
git push -u origin feat/wp77-content-hash-dedupe
```

- [ ] **Step 2: Create PR**

```bash
gh pr create --title "WP #77 — content_hash sha256 dedupe + backfill" --body "$(cat <<'EOF'
## Summary
- Replaces fragile duration+size heuristic with sha256(file_bytes) in same `project_id` for video uniqueness.
- Adds sha256 computation in primary upload and replace-video paths.
- One-shot backfill script for legacy NULL-hash rows; auto-unblocks false-positives, leaves real duplicates blocked, no Delivery webhook.
- Banner text updated in both render-points.

**Spec:** `docs/superpowers/specs/2026-05-18-wp77-duplicate-false-positive-design.md` (in `contenthunter` agents repo).

**OpenProject:** WP #77.

## Test plan
- [ ] `pytest backend/tests/test_uniqueness_hash.py -v` — 5 green
- [ ] `pytest backend/tests/ -x` — no new regressions
- [ ] `python -m scripts.backfill_content_hash --dry-run --limit 5` — clean
- [ ] Visual check of banner in `/content/2123` and `/content/2132` after frontend deploy
- [ ] Post-merge: full `--apply` run on production, then verify 2123/2132 are `is_duplicate=false` and `status=approved`
EOF
)"
```

- [ ] **Step 3: Wait for review/merge**

Watch PR. Address review feedback. When merged → continue to Task 15.

---

### Task 15: Production backfill --apply

⚠️ Run AFTER PR merge — applies real changes to the live `openclaw` DB.

- [ ] **Step 1: Pull latest main on the deploy host**

If you're already on the VPS in a checkout that auto-deploys backend, ensure it's on `main` post-merge.

- [ ] **Step 2: Re-run dry-run to confirm nothing changed**

```bash
cd /path/to/validator-contenthunter/backend
python -m scripts.backfill_content_hash --dry-run 2>&1 | tail -10
```

- [ ] **Step 3: Apply**

```bash
python -m scripts.backfill_content_hash --apply 2>&1 | tee /tmp/wp77_backfill_apply.log | tail -10
```

- [ ] **Step 4: Verify the two flagship false-positives are released**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, project_id, is_duplicate, duplicate_of_id, status, content_hash IS NOT NULL AS has_hash
FROM validator_content WHERE id IN (2120, 2123, 2130, 2132)
ORDER BY id
"
```

Expected:
- 2120, 2130: `is_duplicate=f`, `has_hash=t`
- 2123, 2132: `is_duplicate=f`, `status=approved`, `has_hash=t` (these had different bytes from their old "originals")

If any of them remained `is_duplicate=t`, it means their bytes really do match — review manually with the user.

---

### Task 16: Close WP #77

- [ ] **Step 1: Post house-style comment**

Use [[feedback_openproject_practice.md]] format (Что было не так → Что сделано → Что осталось, plain language, no jargon, no footer):

```bash
source ~/secrets/openproject.env
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "$OPENPROJECT_URL/api/v3/work_packages/77/activities" \
  -d '{
    "comment": {
      "format": "markdown",
      "raw": "**Что было не так:** валидатор считал дубликатом любые два коротких ролика с почти одинаковой длиной и битрейтом (точка проверки — duration ±0.5с И размер ±5%). Ваши ролики 2123 и 2132 как раз попали под эту ловушку.\n\n**Что сделано:** уникальность теперь определяется только по полному совпадению файла (sha256 от байтов в рамках одного проекта). Ролики, которые ошибочно висели в «требует одобрения», переведены в «одобрено» — пришлите проверять что они доступны.\n\n**Что осталось:** ничего, фича задеплоена. Если будут новые жалобы на ложные дубли — пишите, разберём индивидуально."
    }
  }'
```

- [ ] **Step 2: Move WP to closed status**

Find the closed-status id (likely `7` or similar — verify):

```bash
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" "$OPENPROJECT_URL/api/v3/statuses" | python3 -m json.tool | grep -E '"name"|"id"'
```

Then PATCH:

```bash
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X PATCH "$OPENPROJECT_URL/api/v3/work_packages/77" \
  -d '{
    "lockVersion": <CURRENT_LOCK_VERSION>,
    "_links": {
      "status": { "href": "/api/v3/statuses/<CLOSED_ID>" }
    }
  }'
```

Get `lockVersion` from the latest GET on `/api/v3/work_packages/77`.

- [ ] **Step 3: Verify WP shown as closed in UI**

Open https://op.contenthunter.ru/work_packages/77 — status badge should reflect closed.

- [ ] **Step 4: Cleanup worktree**

```bash
cd /home/claude-user/validator-contenthunter
git worktree remove /home/claude-user/validator-contenthunter-wp77-content-hash-20260518
git branch -d feat/wp77-content-hash-dedupe  # only after merge — branch is gone on remote
```

---

## Done Criteria (mirrors spec)

- [ ] Backend: `check_uniqueness` uses `content_hash`, sha256 written in upload + replace-video
- [ ] Frontend: banner text updated in `ContentDetail.vue` and `ValidationDetails.vue`
- [ ] All 5 tests green on live-DB (`pytest backend/tests/test_uniqueness_hash.py -v`)
- [ ] Backfill script written, dry-run inspected, `--apply` run on production
- [ ] Records 2123 and 2132 confirmed `is_duplicate=false` and `status=approved`
- [ ] WP #77 closed with house-style comment
- [ ] Codex review on PR diff — 0 P1
