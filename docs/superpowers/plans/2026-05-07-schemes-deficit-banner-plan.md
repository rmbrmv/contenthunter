# Schemes Deficit Banner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a banner on `/dashboard` (validator-contenthunter, "Планировщик") when client/admin/manager has a project where `approvedSchemes < packs`, plus a per-slot red badge on each affected slot. CTA links to scheme approval flow.

**Architecture:** New backend endpoint `GET /api/schemes/deficits` (single CTE-query, server-side auth only). Frontend composable `useSchemesDeficits.ts` provides reactive `deficits` + `Map` keyed by project_id. New `SchemesDeficitBanner.vue` reads single source of truth. Per-slot badge added inline in BOTH renderers (`SlotCard.vue` for manager + inline render in `ClientDashboard.vue` for client) — patched simultaneously per memory `feedback_validator_two_slot_renderers.md`.

**Tech Stack:** Python 3 + FastAPI + asyncpg (backend); Vue 3 + Vite + Tailwind + Pinia (frontend); pytest + `node:test` available, no frontend test infra exists (manual smoke covers).

**Reference:** Design spec `docs/superpowers/specs/2026-05-07-schemes-deficit-banner-design.md` (revision v3, post-Codex).

---

## File Structure

| Файл | Action | Ответственность |
|---|---|---|
| `backend/src/routers/schemes.py` | MODIFY | Добавить endpoint `GET /api/schemes/deficits` (после существующих `/summary` endpoints) |
| `backend/src/services/schemes_service.py` | MODIFY | Добавить функцию `get_deficits(allowed_ids: list[int], db) -> list[dict]` (single CTE query) |
| `backend/tests/test_schemes_deficits.py` | CREATE | pytest для `/api/schemes/deficits`: B1-B11 покрывают eligibility, empty cases, cross-tenant, role escalation, query count |
| `frontend/src/composables/useSchemesDeficits.ts` | CREATE | Reactive `deficits`, `deficitsByProjectId`, `fetch()`, `hasDeficitFor()`, `deficitFor()` — null-safe |
| `frontend/src/api/schemes.ts` | MODIFY | Добавить `getSchemesDeficits()` API call (если файл существует), иначе создать |
| `frontend/src/components/SchemesDeficitBanner.vue` | CREATE | Banner с single-mode и all-mode рендерами, expandable list для all-mode |
| `frontend/src/components/SlotCard.vue` | MODIFY | Добавить per-slot badge (manager renderer) |
| `frontend/src/pages/client/ClientDashboard.vue` | MODIFY | Mount `<SchemesDeficitBanner>`, invoke composable, добавить inline-badge на client renderer слотов |
| `docs/evidence/2026-05-07-schemes-deficit-banner-deploy.md` | CREATE (в repo `contenthunter`) | Deploy steps + smoke + rollback |

---

## Task 0: Pre-flight

- [ ] **Step 0.1: Зайти в репозиторий + git fetch**

```bash
cd /home/claude-user/validator-contenthunter
git fetch origin
git status
git log --oneline -5
```

Expected: clean tree.

- [ ] **Step 0.2: Создать ветку**

```bash
git checkout -b feature/schemes-deficit-banner-2026-05-07
```

- [ ] **Step 0.3: Verify фикстура для admin in DB**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
-- Какие проекты в дефиците СЕЙЧАС (ожидаемо 6)?
WITH packs AS (
  SELECT project_id, COUNT(*) AS pack_count FROM factory_pack_accounts
  WHERE project_id IS NOT NULL GROUP BY project_id
),
approved AS (
  SELECT sp.project_id, COUNT(*) AS approved_count
  FROM validator_scheme_preferences sp
  JOIN unic_schemes us ON us.id = sp.scheme_id AND us.status = true
  WHERE sp.status = 'approved' GROUP BY sp.project_id
)
SELECT p.project_id, p.pack_count AS min_required, COALESCE(a.approved_count, 0) AS approved
FROM packs p LEFT JOIN approved a ON a.project_id = p.project_id
WHERE p.pack_count > 0 AND p.pack_count > COALESCE(a.approved_count, 0)
ORDER BY p.project_id;
SQL
```

Expected: 6 строк (projects 79, 81, 83, 85, … — с дефицитом). Зафиксировать список — он используется для backend smoke (Step 3.5) и manual smoke (Step 8).

- [ ] **Step 0.4: Verify project store на frontend**

```bash
grep -nE "allProjects|findById|projects\.get" /home/claude-user/validator-contenthunter/frontend/src/stores/project.ts | head -10
cat /home/claude-user/validator-contenthunter/frontend/src/stores/project.ts | head -60
```

Цель: подтвердить, что `useProjectStore()` имеет `allProjects: [{id, project, ...}]` или эквивалент. Зафиксировать имя поля для project_name (вероятно `project`, не `name`). Если store не существует или не имеет нужного метода — STOP, документировать и переключиться на возврат project_name из backend.

- [ ] **Step 0.5: Verify slot.project_id field name in ClientDashboard.vue**

```bash
grep -nE "slot\.(project_id|projectId|project)" /home/claude-user/validator-contenthunter/frontend/src/pages/client/ClientDashboard.vue | head -10
grep -nE "slot\.(project_id|projectId|project)" /home/claude-user/validator-contenthunter/frontend/src/components/SlotCard.vue 2>&1 | head -10
```

Expected: оба используют `slot.project_id` (snake_case, JSON field from backend). Если разные имена — STOP, harmonize или передавать как computed prop.

---

## Task 1: Backend — `get_deficits` service + endpoint (TDD)

**Files:**
- Modify: `backend/src/services/schemes_service.py`
- Modify: `backend/src/routers/schemes.py`
- Create: `backend/tests/test_schemes_deficits.py`

### Subtask 1A — Service function (no endpoint yet, pure SQL)

- [ ] **Step 1A.1: Failing test for `get_deficits` (DB-backed integration test)**

`backend/tests/test_schemes_deficits.py` (НОВЫЙ файл, начало):

```python
"""Unit + integration tests for schemes deficit endpoint and service."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from src.database import AsyncSessionLocal
from src.services.schemes_service import get_deficits


# Fixture content_id < 0 to avoid prod data
TEST_PROJECT_ID = -901


async def _seed_project_with_packs_and_approved(db, project_id: int, n_packs: int, n_approved: int):
    """Create n_packs in factory_pack_accounts + n_approved scheme preferences (approved)."""
    # 1. Cleanup any prior fixtures for this project_id
    await db.execute(text("DELETE FROM validator_scheme_preferences WHERE project_id = :pid"), {"pid": project_id})
    await db.execute(text("DELETE FROM factory_pack_accounts WHERE project_id = :pid"), {"pid": project_id})
    await db.commit()

    # 2. Create packs (negative ids, base = -1000)
    for i in range(n_packs):
        await db.execute(text("""
            INSERT INTO factory_pack_accounts (id, project_id, pack_name)
            VALUES (:id, :pid, :name)
            ON CONFLICT (id) DO NOTHING
        """), {"id": -1000 - i - (project_id * 100), "pid": project_id, "name": f"test_pack_{i}"})

    # 3. Create unic_schemes (-1 .. -n) и approved preferences
    for i in range(n_approved):
        scheme_id = -1 - i
        await db.execute(text("""
            INSERT INTO unic_schemes (id, status) VALUES (:sid, true)
            ON CONFLICT (id) DO UPDATE SET status = true
        """), {"sid": scheme_id})
        await db.execute(text("""
            INSERT INTO validator_scheme_preferences (project_id, scheme_id, status)
            VALUES (:pid, :sid, 'approved')
            ON CONFLICT (project_id, scheme_id) DO UPDATE SET status = 'approved'
        """), {"pid": project_id, "sid": scheme_id})

    await db.commit()


async def _cleanup_project(db, project_id: int):
    await db.execute(text("DELETE FROM validator_scheme_preferences WHERE project_id = :pid"), {"pid": project_id})
    await db.execute(text("DELETE FROM factory_pack_accounts WHERE project_id = :pid"), {"pid": project_id})
    await db.commit()


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_get_deficits_returns_empty_for_no_allowed_ids(db_session):
    result = await get_deficits([], db_session)
    assert result == []


@pytest.mark.asyncio
async def test_get_deficits_returns_entry_for_project_with_deficit(db_session):
    project_id = -901
    await _seed_project_with_packs_and_approved(db_session, project_id, n_packs=9, n_approved=5)
    try:
        result = await get_deficits([project_id], db_session)
        assert len(result) == 1
        entry = result[0]
        assert entry["project_id"] == project_id
        assert entry["min_required"] == 9
        assert entry["approved"] == 5
        assert entry["missing"] == 4
    finally:
        await _cleanup_project(db_session, project_id)


@pytest.mark.asyncio
async def test_get_deficits_filters_full_coverage(db_session):
    project_id = -902
    await _seed_project_with_packs_and_approved(db_session, project_id, n_packs=3, n_approved=3)
    try:
        result = await get_deficits([project_id], db_session)
        assert result == []
    finally:
        await _cleanup_project(db_session, project_id)


@pytest.mark.asyncio
async def test_get_deficits_filters_no_packs(db_session):
    project_id = -903
    await _seed_project_with_packs_and_approved(db_session, project_id, n_packs=0, n_approved=2)
    try:
        result = await get_deficits([project_id], db_session)
        assert result == []  # min_required=0 → not in result
    finally:
        await _cleanup_project(db_session, project_id)
```

- [ ] **Step 1A.2: Run — должны упасть с ImportError**

```bash
cd /home/claude-user/validator-contenthunter/backend
python -m pytest tests/test_schemes_deficits.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'get_deficits' from 'src.services.schemes_service'`.

- [ ] **Step 1A.3: Implement `get_deficits` in service**

В `backend/src/services/schemes_service.py` добавить (в конец файла):

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_deficits(allowed_ids: list[int], db: AsyncSession) -> list[dict]:
    """Возвращает список проектов где approved < min_required (count of packs).

    Аргументы:
        allowed_ids: server-side validated project_ids доступные текущему пользователю.
                     Передавать только то, к чему юзер действительно имеет доступ.
        db: AsyncSession.

    Возвращает:
        [{"project_id": int, "approved": int, "min_required": int, "missing": int}, ...]
        Отсортирован по project_id ASC. Пустой список если allowed_ids пуст
        или ни один проект не имеет дефицита.
    """
    if not allowed_ids:
        return []

    result = await db.execute(text("""
        WITH allowed AS (
          SELECT unnest(CAST(:allowed_ids AS int[])) AS project_id
        ),
        packs AS (
          SELECT project_id, COUNT(*) AS pack_count
          FROM factory_pack_accounts
          WHERE project_id IN (SELECT project_id FROM allowed)
          GROUP BY project_id
        ),
        approved AS (
          SELECT sp.project_id, COUNT(DISTINCT sp.scheme_id) AS approved_count
          FROM validator_scheme_preferences sp
          JOIN unic_schemes us ON us.id = sp.scheme_id AND us.status = true
          WHERE sp.status = 'approved'
            AND sp.project_id IN (SELECT project_id FROM allowed)
          GROUP BY sp.project_id
        )
        SELECT
          p.project_id,
          p.pack_count                              AS min_required,
          COALESCE(a.approved_count, 0)             AS approved,
          p.pack_count - COALESCE(a.approved_count, 0) AS missing
        FROM packs p
        LEFT JOIN approved a ON a.project_id = p.project_id
        WHERE p.pack_count > 0
          AND p.pack_count > COALESCE(a.approved_count, 0)
        ORDER BY p.project_id
    """), {"allowed_ids": allowed_ids})

    rows = result.mappings().all()
    return [
        {
            "project_id": int(r["project_id"]),
            "approved": int(r["approved"]),
            "min_required": int(r["min_required"]),
            "missing": int(r["missing"]),
        }
        for r in rows
    ]
```

- [ ] **Step 1A.4: Run — должны пройти 4 теста**

```bash
python -m pytest tests/test_schemes_deficits.py -v 2>&1 | tail -10
```

Expected: 4 passed.

- [ ] **Step 1A.5: Commit Subtask 1A**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/services/schemes_service.py backend/tests/test_schemes_deficits.py
git commit -m "feat(schemes): get_deficits service — single CTE query

Returns list of {project_id, approved, min_required, missing} for
projects in allowed_ids where approved schemes < pack count.
Source-of-truth for deficits banner."
```

### Subtask 1B — Endpoint with auth scoping

- [ ] **Step 1B.1: Add tests for endpoint authorization**

В тот же `backend/tests/test_schemes_deficits.py` добавить (в конец):

```python
from httpx import AsyncClient
from src.main import app  # FastAPI instance


@pytest_asyncio.fixture
async def http_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


# Helper: build session cookie for a test user
async def _login_as_role(client: AsyncClient, db: AsyncSession, role: str, project_id=None, project_ids=None):
    """Return cookies dict for an authenticated test user. Uses minimal user creation
    + login flow that the existing test_accounts_endpoint uses."""
    # See backend/tests/test_accounts_endpoint.py for the established login pattern.
    # The implementation MUST mirror that pattern; if it differs, STOP and ask.
    raise NotImplementedError("see test_accounts_endpoint.py for login pattern; copy exact mechanism")


# B1: client with deficit project_id → 1 entry
@pytest.mark.asyncio
async def test_endpoint_client_with_deficit_returns_one_entry(http_client, db_session):
    project_id = -911
    await _seed_project_with_packs_and_approved(db_session, project_id, n_packs=9, n_approved=5)
    try:
        cookies = await _login_as_role(http_client, db_session, "client", project_id=project_id)
        resp = await http_client.get("/api/schemes/deficits", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["project_id"] == project_id
        assert data[0]["missing"] == 4
    finally:
        await _cleanup_project(db_session, project_id)
```

**STOP point:** Step 1B.1 references `_login_as_role` which depends on the existing test's login pattern. Before writing more endpoint tests, the implementer MUST inspect `backend/tests/test_accounts_endpoint.py` and mirror that login mechanism exactly — copy the helper if it exists. If no test login pattern exists in the repo, escalate (NEEDS_CONTEXT) — login flow is too involved to invent.

- [ ] **Step 1B.2: Inspect existing test login pattern**

```bash
cd /home/claude-user/validator-contenthunter/backend
grep -nE "login|cookies|auth" tests/test_accounts_endpoint.py | head -20
cat tests/test_accounts_endpoint.py | head -80
```

Document the pattern in your scratchpad. Common patterns:
- Direct token injection via `Authorization: Bearer <token>`
- Session cookie via direct DB insertion
- App fixture with auth-bypass middleware

Use whatever the existing test file uses. **No new login mechanism.**

- [ ] **Step 1B.3: Implement endpoint in `routers/schemes.py`**

В `backend/src/routers/schemes.py` добавить (после существующего `schemes_summary_by_project`, около line 70):

```python
@router.get("/deficits")
async def schemes_deficits(
    db: AsyncSession = Depends(get_db),
    current_user: ValidatorUser = Depends(get_current_user),
):
    """List of projects with approved < min_required schemes.

    Auth strictly server-side:
      - client: только current_user.project_id (если задан)
      - manager: только current_user.project_ids (массив)
      - admin: все project_ids из factory_pack_accounts (DISTINCT)
      - другая роль: 403
    Ignored: X-Project-Id header, ?project= query params.
    """
    from sqlalchemy import text
    role = current_user.role
    allowed_ids: list[int]

    if role == UserRole.client:
        allowed_ids = [current_user.project_id] if current_user.project_id else []
    elif role == UserRole.manager:
        allowed_ids = list(current_user.project_ids or [])
    elif role == UserRole.admin:
        result = await db.execute(text("""
            SELECT DISTINCT project_id FROM factory_pack_accounts
            WHERE project_id IS NOT NULL
            ORDER BY project_id
        """))
        allowed_ids = [int(r[0]) for r in result.fetchall()]
    else:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    deficits = await schemes_service.get_deficits(allowed_ids, db)

    logger.info(
        "schemes_deficits returned",
        extra={
            "role": role.value if hasattr(role, "value") else str(role),
            "project_count": len(allowed_ids),
            "returned": len(deficits),
        },
    )
    # Полный список allowed_ids — на debug-уровне
    logger.debug("schemes_deficits allowed_ids=%s", allowed_ids)

    return deficits
```

- [ ] **Step 1B.4: Run B1 + earlier tests**

```bash
python -m pytest tests/test_schemes_deficits.py -v 2>&1 | tail -15
```

Expected: 5 passed.

- [ ] **Step 1B.5: Commit endpoint**

```bash
git add backend/src/routers/schemes.py backend/tests/test_schemes_deficits.py
git commit -m "feat(schemes): /api/schemes/deficits endpoint with role-scoped auth

client → own project_id; manager → project_ids array; admin → all
project_ids from factory_pack_accounts. Headers/query params ignored.
Structured logging at info level (role/counts only); debug for IDs."
```

---

## Task 2: Backend — full coverage tests B2–B11

**Files:** Modify `backend/tests/test_schemes_deficits.py`

- [ ] **Step 2.1: Add B2 (full coverage), B3 (null project_id), B4 (manager scope)**

Append to file:

```python
# B2: client с full coverage → empty
@pytest.mark.asyncio
async def test_endpoint_client_full_coverage_returns_empty(http_client, db_session):
    project_id = -912
    await _seed_project_with_packs_and_approved(db_session, project_id, n_packs=3, n_approved=3)
    try:
        cookies = await _login_as_role(http_client, db_session, "client", project_id=project_id)
        resp = await http_client.get("/api/schemes/deficits", cookies=cookies)
        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        await _cleanup_project(db_session, project_id)


# B3: client с project_id=None → empty
@pytest.mark.asyncio
async def test_endpoint_client_no_project_returns_empty(http_client, db_session):
    cookies = await _login_as_role(http_client, db_session, "client", project_id=None)
    resp = await http_client.get("/api/schemes/deficits", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == []


# B4: manager с проектами 79, 80, 81 — deficits на 79 и 81
@pytest.mark.asyncio
async def test_endpoint_manager_filters_by_project_ids(http_client, db_session):
    p1, p2, p3 = -921, -922, -923
    await _seed_project_with_packs_and_approved(db_session, p1, n_packs=5, n_approved=3)
    await _seed_project_with_packs_and_approved(db_session, p2, n_packs=2, n_approved=2)  # full
    await _seed_project_with_packs_and_approved(db_session, p3, n_packs=4, n_approved=1)
    try:
        cookies = await _login_as_role(http_client, db_session, "manager", project_ids=[p1, p2, p3])
        resp = await http_client.get("/api/schemes/deficits", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        ids = sorted([d["project_id"] for d in data])
        assert ids == sorted([p1, p3])  # p2 is full coverage, excluded
    finally:
        for p in (p1, p2, p3):
            await _cleanup_project(db_session, p)
```

- [ ] **Step 2.2: Add B5 (admin), B5b (manager empty), B6 (no packs already covered), B7 (unauthenticated)**

```python
# B5: admin sees all deficits across all projects
@pytest.mark.asyncio
async def test_endpoint_admin_sees_all_deficits(http_client, db_session):
    p1, p2 = -931, -932
    await _seed_project_with_packs_and_approved(db_session, p1, n_packs=5, n_approved=2)
    await _seed_project_with_packs_and_approved(db_session, p2, n_packs=3, n_approved=1)
    try:
        cookies = await _login_as_role(http_client, db_session, "admin")
        resp = await http_client.get("/api/schemes/deficits", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        ids = {d["project_id"] for d in data}
        assert p1 in ids and p2 in ids
        # MAY include other prod-existing deficits — assert at least our 2 are there
    finally:
        for p in (p1, p2):
            await _cleanup_project(db_session, p)


# B5b (Codex IMPORTANT #5): manager с пустым project_ids → []
@pytest.mark.asyncio
async def test_endpoint_manager_empty_project_ids_returns_empty(http_client, db_session):
    cookies = await _login_as_role(http_client, db_session, "manager", project_ids=[])
    resp = await http_client.get("/api/schemes/deficits", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json() == []


# B7: unauthenticated → 401
@pytest.mark.asyncio
async def test_endpoint_unauthenticated_returns_401(http_client):
    resp = await http_client.get("/api/schemes/deficits")
    assert resp.status_code == 401
```

- [ ] **Step 2.3: Add B8/B9 (cross-tenant), B10 (role escalation)**

```python
# B8: client отправляет X-Project-Id header pointing to another project — header ignored
@pytest.mark.asyncio
async def test_endpoint_client_ignores_x_project_id_header(http_client, db_session):
    own_pid = -941
    other_pid = -942
    await _seed_project_with_packs_and_approved(db_session, own_pid, n_packs=5, n_approved=2)
    await _seed_project_with_packs_and_approved(db_session, other_pid, n_packs=5, n_approved=1)
    try:
        cookies = await _login_as_role(http_client, db_session, "client", project_id=own_pid)
        # Try to spoof header to access other project
        resp = await http_client.get(
            "/api/schemes/deficits",
            cookies=cookies,
            headers={"X-Project-Id": str(other_pid)},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Must show ONLY own project, not the spoofed one
        assert all(d["project_id"] == own_pid for d in data)
        assert other_pid not in [d["project_id"] for d in data]
    finally:
        for p in (own_pid, other_pid):
            await _cleanup_project(db_session, p)


# B9: query param ?project= ignored
@pytest.mark.asyncio
async def test_endpoint_query_param_project_is_ignored(http_client, db_session):
    own_pid = -943
    other_pid = -944
    await _seed_project_with_packs_and_approved(db_session, own_pid, n_packs=4, n_approved=1)
    await _seed_project_with_packs_and_approved(db_session, other_pid, n_packs=4, n_approved=1)
    try:
        cookies = await _login_as_role(http_client, db_session, "client", project_id=own_pid)
        resp = await http_client.get(f"/api/schemes/deficits?project={other_pid}", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert all(d["project_id"] == own_pid for d in data)
    finally:
        for p in (own_pid, other_pid):
            await _cleanup_project(db_session, p)


# B10: role producer (или другой неподдерживаемый) → 403
@pytest.mark.asyncio
async def test_endpoint_unsupported_role_returns_403(http_client, db_session):
    # producer — реальная роль в системе, но не client/manager/admin для этого endpoint
    cookies = await _login_as_role(http_client, db_session, "producer")
    resp = await http_client.get("/api/schemes/deficits", cookies=cookies)
    assert resp.status_code == 403
```

- [ ] **Step 2.4: Run all backend tests**

```bash
cd /home/claude-user/validator-contenthunter/backend
python -m pytest tests/test_schemes_deficits.py -v 2>&1 | tail -20
```

Expected: 11 passed (4 service-level + B1, B2, B3, B4, B5, B5b, B7, B8, B9, B10 = 13 actually; verify count).

If any test fails because of login helper issue, return to Step 1B.2 — likely the helper signature differs from what's needed.

- [ ] **Step 2.5: Commit**

```bash
git add backend/tests/test_schemes_deficits.py
git commit -m "test(schemes): full coverage for deficits endpoint

B1-B5b: eligibility paths (client/manager/admin, full coverage,
empty cases). B7: unauthenticated 401. B8-B9: cross-tenant tests
(spoofed X-Project-Id header, ?project= query param) — both ignored.
B10: unsupported role (producer) → 403.

All tests confirm server-side auth is the only source of truth."
```

---

## Task 3: Backend deploy + smoke per role

- [ ] **Step 3.1: Push branch backend changes (если решим деплоить отдельно)**

В этом плане backend и frontend живут на одной ветке, deploy происходит за два этапа. Но git pushes могут быть атомарны.

Не пушим пока — сначала frontend.

- [ ] **Step 3.2: Запустить локальный backend smoke**

```bash
cd /home/claude-user/validator-contenthunter/backend
# В одном терминале — поднять backend на dev порту
PORT=8001 uvicorn src.main:app --reload &
SERVER_PID=$!
sleep 3
# Smoke (без auth — должен 401)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/api/schemes/deficits
# Expected: 401
kill $SERVER_PID
```

- [ ] **Step 3.3: Локальный smoke с реальной auth (опционально, если есть тест-юзер)**

Если на dev есть test-юзер (admin) с известным session token — можно прогнать:

```bash
curl -s -H "Cookie: session=<dev-admin-token>" http://localhost:8001/api/schemes/deficits | jq .
```

Expected: массив из 6 deficits (Aneco/Inakent/etc на 2026-05-07 — известные из Step 0.3).

Если нет dev-admin-token — пропускаем; полный prod smoke в Step 3.6 после деплоя.

(Этот шаг можно пропустить если pytest всё покрывает.)

- [ ] **Step 3.4: Backend ОТДЕЛЬНЫЙ commit-set готов к merge** — на этой стадии ничего не пушим, переходим к Task 4 (frontend).

(Почему: согласно Codex IMPORTANT #17 backend deploy ДО frontend deploy — но push branch'а целиком будет в Task 9 после реализации фронта. Деплоим backend через cherry-pick в prod main, фронт следом.)

---

## Task 4: Frontend — `useSchemesDeficits` composable

**Files:**
- Create: `frontend/src/composables/useSchemesDeficits.ts`
- Modify: `frontend/src/api/schemes.ts` (если существует) или создать

- [ ] **Step 4.1: Inspect existing api/schemes.ts**

```bash
ls /home/claude-user/validator-contenthunter/frontend/src/api/ 2>&1 | head
cat /home/claude-user/validator-contenthunter/frontend/src/api/schemes.ts 2>&1 | head -40
```

Если файл существует — добавить функцию в конец. Если нет — создать новый `frontend/src/api/schemes.ts`.

- [ ] **Step 4.2: Add API function**

В `frontend/src/api/schemes.ts` (создать если нужно, копируя style из соседних файлов в `frontend/src/api/`):

```typescript
import apiClient from './client';

export interface DeficitEntry {
  project_id: number;
  approved: number;
  min_required: number;
  missing: number;
}

export async function getSchemesDeficits(): Promise<DeficitEntry[]> {
  // Auth via session cookie; no query params, no project header (server-side scoped).
  const res = await apiClient.get<DeficitEntry[]>('/api/schemes/deficits');
  return res.data;
}
```

(Если `apiClient` импортируется иначе в этом репо — pre-flight `cat frontend/src/api/client.ts` или соседний api-файл.)

- [ ] **Step 4.3: Create composable**

`frontend/src/composables/useSchemesDeficits.ts`:

```typescript
import { ref, computed, type Ref, type ComputedRef } from 'vue';
import { getSchemesDeficits, type DeficitEntry } from '@/api/schemes';

interface UseSchemesDeficitsReturn {
  deficits: Ref<DeficitEntry[]>;
  deficitsByProjectId: ComputedRef<Map<number, DeficitEntry>>;
  loading: Ref<boolean>;
  error: Ref<string | null>;
  fetch: () => Promise<void>;
  hasDeficitFor: (projectId: number | null | undefined) => boolean;
  deficitFor: (projectId: number | null | undefined) => DeficitEntry | null;
}

export function useSchemesDeficits(): UseSchemesDeficitsReturn {
  const deficits = ref<DeficitEntry[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const deficitsByProjectId = computed<Map<number, DeficitEntry>>(() => {
    const m = new Map<number, DeficitEntry>();
    for (const d of deficits.value) m.set(d.project_id, d);
    return m;
  });

  async function fetch(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      deficits.value = await getSchemesDeficits();
    } catch (e: any) {
      const status = e?.response?.status;
      const msg = e?.message ?? String(e);
      // Suppress 401 noise (auth race on first paint), surface 5xx
      if (status !== 401) {
        // eslint-disable-next-line no-console
        console.error(JSON.stringify({ tag: 'schemes-deficits', status, message: msg }));
      }
      error.value = msg;
      deficits.value = [];
    } finally {
      loading.value = false;
    }
  }

  function hasDeficitFor(projectId: number | null | undefined): boolean {
    if (projectId === null || projectId === undefined) return false;
    if (typeof projectId !== 'number' || Number.isNaN(projectId)) return false;
    return deficitsByProjectId.value.has(projectId);
  }

  function deficitFor(projectId: number | null | undefined): DeficitEntry | null {
    if (projectId === null || projectId === undefined) return null;
    if (typeof projectId !== 'number' || Number.isNaN(projectId)) return null;
    return deficitsByProjectId.value.get(projectId) ?? null;
  }

  return { deficits, deficitsByProjectId, loading, error, fetch, hasDeficitFor, deficitFor };
}
```

- [ ] **Step 4.4: TypeScript check**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit 2>&1 | grep -E "useSchemesDeficits|api/schemes" | head -10
```

Expected: 0 ошибок в этих файлах.

- [ ] **Step 4.5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/api/schemes.ts frontend/src/composables/useSchemesDeficits.ts
git commit -m "feat(frontend): useSchemesDeficits composable + API binding

Reactive deficits + computed Map<project_id, entry> single source of
truth for upcoming banner and slot badge. Null-safe helpers
hasDeficitFor / deficitFor handle null/undefined/NaN project_id.
401 errors suppressed (auth race on initial paint), 5xx logged."
```

---

## Task 5: Frontend — `SchemesDeficitBanner.vue` component

**Files:** Create `frontend/src/components/SchemesDeficitBanner.vue`

- [ ] **Step 5.1: Create component**

`frontend/src/components/SchemesDeficitBanner.vue`:

```vue
<template>
  <!-- Single-mode: один проект с дефицитом -->
  <div
    v-if="singleDeficit"
    class="bg-red-50 border border-red-200 rounded-xl p-4 mb-5 text-sm"
  >
    <div class="font-semibold text-red-800 mb-1">⚠️ Контент не публикуется</div>
    <div class="text-red-700 leading-relaxed mb-3">
      У вас одобрено <strong>{{ singleDeficit.approved }}</strong> схем из необходимых <strong>{{ singleDeficit.min_required }}</strong>.
      Одобрите ещё <strong>{{ singleDeficit.missing }}</strong> схем чтобы публикация возобновилась.
    </div>
    <router-link
      :to="ctaSingle(singleDeficit.project_id)"
      class="inline-block px-3 py-1.5 bg-red-600 text-white text-sm font-medium rounded hover:bg-red-700"
    >
      Одобрить схемы →
    </router-link>
  </div>

  <!-- All-mode: aggregated banner -->
  <div
    v-else-if="showAggregated"
    class="bg-red-50 border border-red-200 rounded-xl p-4 mb-5 text-sm"
  >
    <button
      type="button"
      @click="expanded = !expanded"
      class="w-full flex items-start text-left"
    >
      <div class="flex-1">
        <div class="font-semibold text-red-800 mb-1">⚠️ {{ deficits.length }} проектов с заблокированной публикацией</div>
        <div class="text-red-700 text-xs">
          {{ expanded ? 'Скрыть список' : 'Раскрыть список' }} {{ expanded ? '↑' : '↓' }}
        </div>
      </div>
    </button>
    <ul v-if="expanded" class="mt-3 space-y-1">
      <li
        v-for="d in deficits"
        :key="d.project_id"
        class="flex items-center justify-between bg-white/40 rounded px-3 py-1.5"
      >
        <span class="text-red-800 text-sm">
          <strong>{{ projectName(d.project_id) }}</strong>:
          одобрено {{ d.approved }}/{{ d.min_required }}
          (нужно ещё {{ d.missing }})
        </span>
        <router-link
          :to="ctaSingle(d.project_id)"
          class="text-red-700 text-xs underline hover:text-red-900"
        >
          Одобрить →
        </router-link>
      </li>
    </ul>
    <router-link
      v-if="userRole !== 'client'"
      :to="ctaAllTop()"
      class="mt-3 inline-block px-3 py-1.5 bg-red-600 text-white text-sm font-medium rounded hover:bg-red-700"
    >
      Открыть управление схемами →
    </router-link>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import type { DeficitEntry } from '@/api/schemes';

interface Props {
  deficits: DeficitEntry[];
  viewMode: 'single' | 'all';
  currentProjectId?: number | null;
  userRole: string;
}

const props = defineProps<Props>();
const expanded = ref(false);

// Single source of truth: same Map logic as composable, but inline-safe to props
const deficitMap = computed(() => {
  const m = new Map<number, DeficitEntry>();
  for (const d of props.deficits) m.set(d.project_id, d);
  return m;
});

const singleDeficit = computed<DeficitEntry | null>(() => {
  if (props.viewMode !== 'single') return null;
  if (props.currentProjectId === null || props.currentProjectId === undefined) return null;
  if (typeof props.currentProjectId !== 'number') return null;
  return deficitMap.value.get(props.currentProjectId) ?? null;
});

const showAggregated = computed(() =>
  props.viewMode === 'all' && props.deficits.length > 0
);

// Resolve project name from project store with fallback
import { useProjectStore } from '@/stores/project';
const projectStore = useProjectStore();
function projectName(projectId: number): string {
  // Pre-flight Q2 verified that store has allProjects with `project` field name.
  // If not — fallback to placeholder.
  const p = (projectStore.allProjects ?? []).find((proj: any) => proj.id === projectId);
  return p?.project ?? `Project ${projectId}`;
}

// CTA URLs
function ctaSingle(projectId: number): string {
  if (props.userRole === 'client') return '/client/schemes';
  return `/admin/scheme-preferences?project=${projectId}`;
}

function ctaAllTop(): string {
  return '/admin/scheme-preferences';
}
</script>
```

- [ ] **Step 5.2: TypeScript check**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit 2>&1 | grep -E "SchemesDeficitBanner" | head -10
```

Expected: 0 errors. Если выскакивают про `projectStore.allProjects` или `proj.project` — фолбэкнуться через `(p as any).project` или уточнить тип в Step 0.4.

- [ ] **Step 5.3: Commit**

```bash
git add frontend/src/components/SchemesDeficitBanner.vue
git commit -m "feat(frontend): SchemesDeficitBanner component

Single-mode: red banner with X/Y schemes count + 'Одобрить схемы →' CTA.
All-mode: aggregated 'N проектов' banner with expandable list,
per-project CTA in expanded list, generic top CTA. Project name
resolved from project store with fallback. Null-safe."
```

---

## Task 6: Frontend — per-slot badge (SlotCard.vue + ClientDashboard inline)

**Files:**
- Modify: `frontend/src/components/SlotCard.vue`
- Modify: `frontend/src/pages/client/ClientDashboard.vue` (только inline-render слота)

### Subtask 6A — SlotCard.vue badge

- [ ] **Step 6A.1: Read SlotCard.vue to understand slot rendering**

```bash
cat /home/claude-user/validator-contenthunter/frontend/src/components/SlotCard.vue | head -80
```

Identify где рендерится title/content в слоте — туда добавить badge inline.

- [ ] **Step 6A.2: Add `hasDeficit` prop to SlotCard.vue**

В `<script setup>` существующего SlotCard.vue добавить prop в `defineProps<...>` (или props object). Точное место зависит от структуры файла — pre-flight выше.

Пример:

```typescript
interface Props {
  // ... existing props ...
  hasDeficit?: boolean;
  deficitTooltip?: string;
}

const props = defineProps<Props>();
```

В `<template>` найти место где рендерится текст слота (вероятно рядом с `slot.content_title`), добавить badge:

```vue
<span
  v-if="props.hasDeficit"
  class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold text-red-700 bg-red-100 border border-red-200 rounded ml-1"
  :title="props.deficitTooltip || 'Не хватает одобренных схем уникализации'"
>
  Не хватает схем
</span>
```

Точное место вставки зависит от текущей разметки SlotCard.vue. Ставить рядом с `slot.content_title` или в info-area, чтобы badge не ломал layout.

- [ ] **Step 6A.3: TypeScript + visual check (no automated test, just compile)**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit 2>&1 | grep -E "SlotCard" | head -5
```

Expected: 0 errors.

- [ ] **Step 6A.4: Commit Subtask 6A**

```bash
git add frontend/src/components/SlotCard.vue
git commit -m "feat(frontend): per-slot 'Не хватает схем' badge in SlotCard.vue

hasDeficit prop renders red text badge inline with slot content.
Tooltip configurable via deficitTooltip prop."
```

### Subtask 6B — ClientDashboard.vue inline-slot badge

- [ ] **Step 6B.1: Read ClientDashboard.vue inline slot template**

```bash
sed -n '120,180p' /home/claude-user/validator-contenthunter/frontend/src/pages/client/ClientDashboard.vue
```

Find where `slot.content_title` is rendered (line ~161 per recon).

- [ ] **Step 6B.2: Add badge HTML inline (analogue to SlotCard.vue)**

Найти строку типа:
```vue
<div class="text-xs font-medium text-gray-700 truncate">{{ slot.content_title || 'Контент' }}</div>
```

Сразу после неё добавить:

```vue
<span
  v-if="hasDeficitFor(slot.project_id)"
  class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold text-red-700 bg-red-100 border border-red-200 rounded mt-1"
  :title="`Одобрено ${deficitFor(slot.project_id)?.approved ?? 0} из ${deficitFor(slot.project_id)?.min_required ?? 0} схем уникализации`"
>
  Не хватает схем
</span>
```

(`hasDeficitFor` и `deficitFor` будут доступны через composable — добавим в Task 7.)

- [ ] **Step 6B.3: TypeScript check** (badge ссылается на функции, которые ещё не импортированы — это пока чёрная box; компиляция упадёт; не commit'ить пока)

Шаг ничего не делаем — просто фикcируем что эта строка есть. Компиляция пройдёт после Task 7.

---

## Task 7: Frontend — wire ClientDashboard.vue (composable + banner mount)

**Files:** Modify `frontend/src/pages/client/ClientDashboard.vue`

- [ ] **Step 7.1: Read top of ClientDashboard.vue's `<script setup>`**

```bash
sed -n '270,330p' /home/claude-user/validator-contenthunter/frontend/src/pages/client/ClientDashboard.vue
```

Identify imports section, `onMounted` hook, viewMode/selectedProjectId state.

- [ ] **Step 7.2: Add imports**

В `<script setup>` ClientDashboard.vue добавить:

```typescript
import { onMounted, watch } from 'vue';  // если ещё не импортированы
import { useSchemesDeficits } from '@/composables/useSchemesDeficits';
import SchemesDeficitBanner from '@/components/SchemesDeficitBanner.vue';
import { useAuthStore } from '@/stores/auth';
```

(Если `useAuthStore` уже импортирован — пропустить эту часть; нужен только для `userRole`.)

- [ ] **Step 7.3: Initialize composable + lifecycle**

В `<script setup>` после import'ов:

```typescript
const { deficits, fetch: fetchDeficits, hasDeficitFor, deficitFor } = useSchemesDeficits();
const auth = useAuthStore();
const userRole = computed(() => auth.user?.role ?? 'client');

onMounted(() => {
  fetchDeficits();
});

// Refetch on viewMode/selectedProject change OR on route re-entry to /dashboard
watch(
  () => [viewMode.value, selectedProjectId.value],
  () => fetchDeficits(),
);
```

Если `viewMode` и `selectedProjectId` имеют другие имена в этом файле — pre-flight найти настоящие имена.

- [ ] **Step 7.4: Mount banner in template**

В `<template>` найти конец header'а (`</div>` после кнопки "⬆️ Загрузить контент"), после него и до week-navigator вставить:

```vue
<SchemesDeficitBanner
  :deficits="deficits"
  :view-mode="viewMode"
  :current-project-id="isClient ? auth.user?.project_id : selectedProjectId || null"
  :user-role="userRole"
/>
```

Точное место — зависит от существующей разметки. Banner идёт ОТДЕЛЬНОЙ строкой между header'ом и week-navigator.

- [ ] **Step 7.5: TypeScript check на всём dashboard**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit 2>&1 | grep -E "ClientDashboard|SchemesDeficitBanner|useSchemesDeficits" | head -15
```

Expected: 0 errors. Если есть — фиксить inline, не commit'ить пока.

- [ ] **Step 7.6: `npm run build` — auto-postbuild доставит в /var/www/validator/**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npm run build 2>&1 | tail -30
```

Expected: build success, postbuild copies to /var/www/validator/.

- [ ] **Step 7.7: Commit (everything wired)**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/pages/client/ClientDashboard.vue
git commit -m "feat(frontend): wire SchemesDeficitBanner + per-slot badge in dashboard

Composable fetches on mount and on viewMode/selectedProjectId change.
Banner mounted between header and week-navigator. Per-slot badge
inline next to content title — uses hasDeficitFor(slot.project_id)
from same composable (single source of truth with banner)."
```

---

## Task 8: Manual smoke checklist

В отсутствие frontend-test-infra — структурированный manual smoke. Каждый пункт — checkbox в evidence-doc.

- [ ] **Step 8.1: Pre-deploy smoke на dev environment (validator running локально)**

Если есть локальный dev validator:
```bash
cd /home/claude-user/validator-contenthunter/frontend
npm run dev
# открыть http://localhost:5173 в браузере
```

Если нет — пропустить, делаем post-deploy smoke в Step 8.4-8.6.

- [ ] **Step 8.2: Smoke client (для одного из 6 проблемных проектов)**

В браузере залогиниться как клиент проекта 79 (Aneco). Открыть `/dashboard`. Verify:
- Banner красный с текстом "У вас одобрено X схем из необходимых Y" (5/9)
- Кнопка "Одобрить схемы →" ведёт на `/client/schemes`
- На каждом filled слоте этой недели — красный бейдж "Не хватает схем"
- Hover на бейдж → тооltip "Одобрено 5 из 9 схем уникализации"

- [ ] **Step 8.3: Smoke admin single-mode**

Login as admin. На `/dashboard` выбрать viewMode='single' + project=79. Verify:
- Тот же banner что в Step 8.2
- CTA-линк ведёт на `/admin/scheme-preferences?project=79`
- Per-slot badges на слотах project=79

- [ ] **Step 8.4: Smoke admin all-mode**

На `/dashboard` переключить в viewMode='all'. Verify:
- Banner показывает "6 проектов с заблокированной публикацией" (или сколько актуально)
- Клик "Раскрыть список ↓" — раскрывает строки `Aneco: 5/9 (нужно ещё 4)` etc
- Per-row кнопка "Одобрить →" ведёт на `/admin/scheme-preferences?project=<id>`
- Top кнопка "Открыть управление схемами →" — `/admin/scheme-preferences` (без preselect)
- Per-slot badges на слотах ВСЕХ deficit-проектов (project=79, 81, 83, 85, ...)

- [ ] **Step 8.5: Smoke negative — проект БЕЗ deficit'а**

Login as client с project_id, у которого approved >= packs (если такой есть; если нет — пропустить). Verify:
- Banner НЕ показывается
- Per-slot badges НЕ показываются

- [ ] **Step 8.6: Refetch on return**

Login as client проекта 79. На `/client/schemes` одобрить недостающие схемы (по reality — этот шаг на проде делает реальный клиент; мы можем сэмулировать прямой UPDATE в БД для теста, и откатить):

```sql
-- (Optional, для теста — не оставлять в проде если делаем dry-run)
UPDATE validator_scheme_preferences
SET status = 'approved'
WHERE project_id = 79 AND scheme_id IN (...)  -- 4 first non-approved scheme_ids
LIMIT 4;
```

Перейти на `/dashboard`. Verify:
- Banner и badges исчезают (composable fetch'ит заново на mount)

Откатить test-update если применяли.

- [ ] **Step 8.7: Записать результаты smoke в evidence**

`docs/evidence/2026-05-07-schemes-deficit-banner-smoke.md` (в repo `contenthunter`):

```markdown
# Smoke: SchemesDeficitBanner (date)

## Tested as
- [ ] client project=79 (Aneco) — banner ✓ badge ✓
- [ ] admin single-mode project=79 — banner ✓ CTA ?project=79 ✓
- [ ] admin all-mode — aggregated banner "6 projects" ✓ expansion ✓ per-row CTA ✓
- [ ] client without deficit — no banner ✓
- [ ] refetch on /client/schemes → /dashboard — banner disappears ✓

## Backend curl smoke
- [ ] curl as client → 0 or 1 deficit
- [ ] curl as admin → 6 deficits (matches DB query in Step 0.3)
- [ ] curl ?project=999 — query param ignored ✓
```

---

## Task 9: Deploy backend → frontend

- [ ] **Step 9.1: Apply backend changes to prod main**

```bash
cd /root/.openclaw/workspace-genri/  # validator prod path — pre-flight
ls /root/.openclaw/workspace-genri/ | grep validator  # find prod validator dir
```

Adjust path based on what's there. If validator prod is in different location — find it first:

```bash
find /root/.openclaw -maxdepth 4 -name "main.py" -path "*validator*" 2>&1 | head -3
```

Once located, navigate there and:

```bash
cd /path/to/prod/validator
git fetch origin
git merge --no-ff origin/feature/schemes-deficit-banner-2026-05-07 -m "merge feature/schemes-deficit-banner-2026-05-07 — schemes deficit banner

Banner on /dashboard signals when project has approvedSchemes < packs.
Backend endpoint /api/schemes/deficits + frontend banner + per-slot badges.
Read-only feature, no migrations.

Sub-project sequel to A. See docs/evidence/2026-05-07-schemes-deficit-banner-deploy.md
in contenthunter repo."
```

If auto-push hook doesn't fire — manual `git push origin main`.

- [ ] **Step 9.2: PM2 restart validator**

```bash
sudo pm2 restart validator
sudo pm2 logs validator --lines 50 --nostream | grep -iE "schemes|deficits|started" | head -10
```

Expected: validator restart success, no errors.

- [ ] **Step 9.3: Backend smoke per role (3 curl)**

(per Codex IMPORTANT #7 — verify all 3 roles)

```bash
# Client (если есть session token)
curl -s -H "Cookie: session=<client-token>" https://client.contenthunter.ru/api/schemes/deficits | jq .

# Manager
curl -s -H "Cookie: session=<manager-token>" https://client.contenthunter.ru/api/schemes/deficits | jq 'length'

# Admin
curl -s -H "Cookie: session=<admin-token>" https://client.contenthunter.ru/api/schemes/deficits | jq 'length'

# Spoofed query param (must be ignored)
curl -s -H "Cookie: session=<client-token>" "https://client.contenthunter.ru/api/schemes/deficits?project=999" | jq .
```

Expected:
- Client → 0 or 1 entry
- Manager → only their accessible projects
- Admin → 6 (or current count from Step 0.3)
- Spoofed query → same as without query param

If any returns 5xx — STOP, do not deploy frontend. Fix backend first.

- [ ] **Step 9.4: Frontend deploy**

Frontend code merged in Step 9.1 (single branch). After backend is verified:

```bash
cd /path/to/prod/validator/frontend
npm run build  # postbuild автокопирует в /var/www/validator/
```

Если frontend дев-копия отдельная (а prod build не запускается из этой dir) — locate prod frontend build dir и build там.

- [ ] **Step 9.5: Manual smoke на проде**

Открыть `https://client.contenthunter.ru/dashboard` (под client/admin/manager аккаунтами по очереди), применить чеклист из Task 8 (Steps 8.2-8.6).

- [ ] **Step 9.6: Commit deploy evidence**

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/2026-05-07-schemes-deficit-banner-deploy.md docs/evidence/2026-05-07-schemes-deficit-banner-smoke.md
git commit -m "docs(evidence): schemes deficit banner — deploy + smoke results"
```

---

## Task 10: Push branch + final summary

- [ ] **Step 10.1: Push feature branch (если ещё не запушено через merge to main)**

```bash
cd /home/claude-user/validator-contenthunter
git push -u origin feature/schemes-deficit-banner-2026-05-07
```

(Если процесс был "merge directly to main с auto-push" — этот шаг лишний.)

- [ ] **Step 10.2: Final report для пользователя**

Сообщить:
- `git log --oneline main..HEAD` (если ветка не merged) или последние commits на main
- Ссылку на design doc + plan + smoke evidence
- Список затронутых проектов (6 на момент 2026-05-07: 79/81/83/85 + 2 других — точные на основе Step 0.3)
- Краткое summary что увидит клиент

---

## Self-Review

- **Spec coverage:** все секции спеки покрыты — backend endpoint + tests, composable + types, banner component, slot badge in 2 places, deploy backend-first, smoke checklist. Open questions Q1/Q3/Q5/Q6 закрыты в pre-flight Step 0.

- **Placeholder scan:** `_login_as_role` в Step 1B.1 явно помечен как требующий копирования из существующего теста (Step 1B.2 делает это inspect'ом). Без этого тесты не пройдут — explicit STOP point.

- **Type consistency:** `DeficitEntry` определён в `api/schemes.ts`, имеет одинаковую форму везде; helpers `hasDeficitFor`/`deficitFor` принимают `number | null | undefined`; backend SQL возвращает все 4 поля. Banner и badge используют ОДНУ Map (Codex IMPORTANT #4 — banner использует `deficitMap` напрямую от props, badge через composable; обе ссылаются на one-and-the-same backend response).

- **Ordering:** backend Task 1-3 → frontend Task 4-7 → smoke Task 8 → deploy Task 9. Backend deploy перед frontend — Codex IMPORTANT #17.

---

## Decisions captured

- Test runner: pytest для backend (полное покрытие); manual smoke для frontend (no test infra existed in repo, adding vitest deferred).
- `_login_as_role` helper копируется из существующего `tests/test_accounts_endpoint.py` — STOP point если паттерн отличается.
- Backend SQL — single CTE-query с `unnest($1::int[])` (Postgres-specific, не sqlite-compatible — обычная для FastAPI стека).
- Frontend project_name — резолвим через `useProjectStore().allProjects` (проверяется в pre-flight; fallback `Project ${id}`).
- Composable export shape: `{deficits, deficitsByProjectId, loading, error, fetch, hasDeficitFor, deficitFor}` — все доступны для использования и в banner, и в slot-badge.
- Banner-component не использует composable напрямую — получает `deficits` через props (для testability и переиспользования). Single source of truth — composable в parent (`ClientDashboard.vue`).
- Per-slot badge тоже не использует composable напрямую: в SlotCard через `hasDeficit` prop (manager use case), в client inline-render — напрямую через composable helpers (parent scope).

## Codex review iterations

- Plan v1 (этот документ) — на review pending. Если найдутся blocker'ы — apply inline и пересохранить.
