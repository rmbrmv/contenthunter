# Evidence — Paginated tables этап 3 completion (2026-04-29)

**Plan:** `.ai-factory/plans/paginated-tables-etap3-archive-20260429.md` (миграция #1) +
этот документ (миграции #2-#7, единым commit).
**Status:** ✅ **SHIPPED** — все 7 миграций этапа 3 закрыты в один день.

## Summary

Этап 3 завершён за 2 commit-batch'а:
1. `512fd80` + `af2ffd1` — `/api/archive/tasks` (server + frontend factory + composite index)
2. `d880a3f` — 6 остальных endpoint'ов в одном atomic commit (server-side only, BC layer для frontend continuity)

| # | Endpoint | Table | Rows | Status |
|---|---|---|---|---|
| 1 | `/api/archive/tasks` | archive_tasks | 6360 | ✅ server + UI factory (composite index added) |
| 2 | `/api/unic/tasks` | unic_tasks | 1542 | ✅ server (UI deferred — div-list, factory-incompat) |
| 3a | `/api/factory/tasks` | factory_reg_tasks | 44 | ✅ server (UI deferred — small N, no rework justified) |
| 3b | `/api/factory/accounts` | factory_reg_accounts | 44 | ✅ server (UI deferred) |
| 4 | `/api/whatsapp/tasks` | wa_warm_tasks | 0 | ✅ server (UI deferred — empty table) |
| 5 | `/api/telegram/tasks` | tg_warm_tasks | 0 | ✅ server (UI deferred — empty table) |
| 6 | `/api/phone-warm/tasks` | phone_warm_tasks | 1 | ✅ server (UI deferred — 1 row) |
| 7 | `/api/tasks` | autowarm_tasks | 315 | ✅ server (UI keeps existing `tasks-pagination` div, BC layer) |

## Architectural decisions

### Composite indexes — НЕ создаём

EXPLAIN ANALYZE на этих объёмах:
- unic_tasks (1542): Seq Scan + top-N heapsort, ~2ms
- autowarm_tasks (315), factory_reg_* (44), warm_tasks (0-1): тривиально

Все < 5k threshold из бэклога. Index не оправдан (cost + maintenance overhead для tiny gain).
Только archive_tasks (6360) получил composite index в commit `512fd80`.

### Frontend factory rollout — DEFERRED для 6/7

Бэклог-чеклист требовал:
> Frontend: добавить sentinel-row в HTML; создать factory instance через createPaginatedTable({...})

Но реальные UI-shapes:
- **`/api/unic/tasks`**: `<div id="unic-tasks-list">` (div-list, не tbody) — `paginated-table.js` factory designed только для tbody. Требует расширения factory ИЛИ markup rewrite.
- **`/api/tasks`**: уже имеет существующую `<div id="tasks-pagination">` custom-pagination. Frontend rework конкурирует с уже работающим UX.
- **factory/whatsapp/telegram/phone-warm**: `<tbody>` совместимы, но 0-44 rows не оправдывают UI rework.

**BC layer** в каждом endpoint (без `limit`/`cursor` → legacy array возврат) гарантирует что existing frontend продолжает работать без изменений.

Frontend factory rollout — отдельная задача когда tables get data volume justifying UX iteration.

## Что сделано во ВСЕХ 6 endpoints (commit `d880a3f`)

Каждый endpoint получил одинаковый структурный набор:

```javascript
// === ENDPOINT — cursor pagination (etap 3 #N) ===
const XXX_SORT_WHITELIST = { id, status, ... };
const XXX_SELECT = `t.*`;
const XXX_FROM = `FROM xxx_table t`;
function buildXxxFilters(query) { ... }

app.get('/api/.../stats', requireAuth, ...);  // group-by-status, filter-aware
app.get('/api/...', requireAuth, ...) {
  // BC layer: без params → legacy array (существующее поведение)
  // С params → cursor pagination через buildPaginatedQuery + processPaginatedResult
}
```

### Sort whitelists (per endpoint)

| Endpoint | Sortable columns |
|---|---|
| /api/unic/tasks | id, current_status, project_id, created_at, updated_at |
| /api/factory/tasks | id, status, device_id |
| /api/factory/accounts | id, status, device_id, platform |
| /api/whatsapp/tasks | id, status, device_id |
| /api/telegram/tasks | id, status, device_id |
| /api/phone-warm/tasks | id, status, device_id, created_at |
| /api/tasks | id, status, device_serial, account, project, started_at, updated_at |

### Filters (per endpoint)

| Endpoint | Filters |
|---|---|
| /api/unic/tasks | current_status (CSV), project_id, search (input_video_name OR project_name ILIKE) |
| /api/factory/tasks | status, device_id |
| /api/factory/accounts | status, device_id, platform |
| /api/whatsapp/tasks | status, device_id |
| /api/telegram/tasks | status, device_id |
| /api/phone-warm/tasks | status (CSV), device_id |
| /api/tasks | status (CSV), platform, device_serial, project, account ILIKE |

## Smoke

### Pytest gate

`paginate.test.js`: 19/19 green после d880a3f (helper'ы не тронуты).
`node -c server.js`: syntax OK.

### Auth-protected endpoints (5 из 6)

5 endpoints (unic/factory*/wa/tg/phone-warm) защищены `requireAuth` middleware.
Curl без сессии → `{"error":"Unauthorized"}` 401. Это правильное поведение
middleware (не баг моих изменений).

### SQL-level smoke (для auth-protected)

Прогнал те же queries что endpoint выполняет, через `psql`:
```
unic_tasks  legacy n=100   (limit=100)
factory_reg_tasks legacy n=44
factory_reg_accounts legacy n=44
wa_warm_tasks legacy n=0
tg_warm_tasks legacy n=0
phone_warm_tasks legacy n=1

# Cursor pagination для unic_tasks (sort=id, id<5000, limit=3):
1561, 1560, 1559  ← правильный desc-order

# /stats GROUP BY:
unic_tasks → error=7, done=1535
autowarm_tasks → 7 различных статусов (failed=221, ...)
```

### Curl smoke для /api/tasks (no-auth)

```
=== Legacy compat ===
"array", n=315

=== Paginated (limit=3) ===
{ "type": "object", "has_more": true, "n_rows": 3 }

=== Stats ===
{ "total": 315 }

=== Negative: invalid sort ===
status=400, {"error":"invalid sort"}

=== Negative: cursor sort key mismatch ===
status=400, {"error":"cursor sort key mismatch"}

=== Filter status=failed (limit=3) ===
{ "n": 3, "all_failed": true }

=== /stats?status=failed ===
{ "total": 221, "by_status_count": 1 }   ← matches psql
```

8/8 green.

### PM2 restart

```
restart #214, status=online, exec cwd correct, unstable=0, errors in logs: empty
```

## Что осталось

**Frontend factory rollout** для 6/7 endpoint'ов — отдельная задача когда:
- Tables grow > 1k rows и lazy-loading становится важным
- ИЛИ UX redesign делает factory-style UI релевантным

**Backport pilot+etap2+etap3 в `autowarm-testbench`** — testbench отстаёт ~10 коммитов
по этим миграциям. Per memory `feedback_autowarm_testbench_deploy.md` — node_modules
symlink risk при merge.

## Memory updates

- `MEMORY.md` — bump entry: «etap 3 ✅ closed (1 full + 6 server-only)».
- `project_paginated_tables_pilot.md` — обновить: все 7 миграций закрыты, frontend factory deferred.
- `paginated-tables-etap3-backlog-20260428.md` — отметить все 7 как closed (with SHA).

## Commits

| Repo | SHA | Message |
|---|---|---|
| `delivery-contenthunter` (prod) | `512fd80` | `feat(server): cursor pagination + stats for /api/archive/tasks` |
| `delivery-contenthunter` (prod) | `af2ffd1` | `feat(ui): /archive table через paginated-table factory + TDZ guard` |
| `delivery-contenthunter` (prod) | `d880a3f` | `feat(server): cursor pagination + stats for 6 etap-3 backlog endpoints` |
| `contenthunter` | `e3777164a` | `docs(plans+evidence): paginated tables etap 3 #1 archive — executed T0-T6` |
| `contenthunter` | (pending) | `docs(plans+evidence): paginated tables etap 3 completion — 6 server-side migrations` |
