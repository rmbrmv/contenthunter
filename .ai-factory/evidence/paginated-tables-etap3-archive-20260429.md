# Evidence — Paginated tables этап 3, миграция #1: `/api/archive/tasks` (2026-04-29)

**Plan:** `.ai-factory/plans/paginated-tables-etap3-archive-20260429.md`
**Status:** ✅ **SHIPPED** to prod main (2 atomic commits, auto-pushed by post-commit hook)
**PM2:** restart #213, online, no unstable, exec cwd correct

## Контекст

`paginated-tables-etap3-backlog-20260428.md` — список из 7 миграций для этапа 3, archive #1 (самая большая, 6360 rows). Helper API ready (`paginate.js` + `paginated-table.js` отгружены в этап 2 как `da10b80` + `42b3581`).

## T0 — Pre-check EXPLAIN

### Без индекса

```
EXPLAIN ANALYZE SELECT * FROM archive_tasks ORDER BY started_at DESC LIMIT 100;

Limit (cost=421.67..421.92 rows=100 width=128) (actual time=1.915..1.928)
  Sort (cost=421.67..437.57 rows=6360)  Sort Method: top-N heapsort
    Seq Scan on archive_tasks (cost=0.00..178.60)
```

Cursor предикат — то же Seq Scan + Sort (cost=453, 2.4ms).

### С предложенным индексом (BEGIN/ROLLBACK)

```
CREATE INDEX archive_tasks_started_at_id_idx ON archive_tasks (started_at DESC, id DESC);

Limit (cost=0.28..7.90 rows=100 width=128) (actual time=0.029..0.086)
  Index Scan using archive_tasks_started_at_id_idx
    Buffers: shared hit=66 read=2
  Execution Time: 0.115 ms
```

**Cost 484 → 7.9 (60×), exec 0.115ms.** Index scan победил.

## T1 — Migration applied

`migrations/20260429_archive_tasks_index.sql`:
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS archive_tasks_started_at_id_idx
  ON archive_tasks (started_at DESC, id DESC);
```

Apply log: `CREATE INDEX`. Проверено `pg_indexes`:
```
indexname
---------------------------------
 archive_tasks_started_at_id_idx
 archive_tasks_pkey
```

## T2 — Backend (commit `512fd80`)

`server.js` (+102/-6):
- `ARCHIVE_TASKS_SORT_WHITELIST` (id, started_at, finished_at, status, platform, device_serial)
- `ARCHIVE_TASKS_SELECT` / `_FROM`
- `buildArchiveTasksFilters(query)` — status (CSV), platform, device_serial, account (ILIKE)
- `GET /api/archive/tasks/stats` — group-by-status (filter-aware)
- `GET /api/archive/tasks` rewrite:
  - **BC layer**: без limit/cursor → legacy array (LIMIT 200), не ломает старые callers
  - С params → `buildPaginatedQuery` + `processPaginatedResult`

Route ordering: `/stats` объявлен ДО `/:id/log` (Express route matching).

`paginate.test.js`: 19/19 green (helper'ы не тронуты).

## T3 — Frontend (commit `af2ffd1`)

`public/index.html` (+77/-60):
- Sentinel `<div id="archive-sentinel">` после таблицы для IntersectionObserver
- Factory instance `_archiveTable = createPaginatedTable({...})`:
  - `tableId: 'archive'`
  - `endpoints: { list, stats }` (нет byIds — liveRefresh=false)
  - `defaultSort: { col: 'started_at', order: 'desc' }`
  - `pageSize: 100, emptyColspan: 7`
  - `isActiveTab: () => currentSection === 'archive'`
- `loadArchive()` — **TDZ guard** через try/catch ReferenceError + setTimeout(0) defer (урок этап-2)
- `filterArchiveTasks()` → factory.setFilter (server-side, debounce 300ms)
- `_archiveRenderRow(t)` — single-row renderer вместо batch render

Удалены: `_archiveAll[]`, старые `loadArchive`/`filterArchiveTasks`/`renderArchiveTasks`.

Pre-commit hook: `✅ All checks passed — index.html is valid!`

## T4 — Smoke endpoints (after commit + restart)

```
=== Legacy compat ===
"array"
200      # 200 rows массивом, как до миграции

=== Paginated 1-я страница ===
{ "type": "object", "has_more": true, "n_rows": 5, "has_cursor": true }

=== Stats ===
{ "total": 6360, "by_status_keys": ["done", "failed"] }

=== Cursor next page ===
{ "n_rows": 5, "first_id": 6355, "last_id": 6351 }   # continuation после 1-й

=== Negative: invalid cursor → graceful ===
{ "n": 5, "has_more": true }   # decodeCursor() вернул null → fall-back на 1-ю

=== Negative: invalid sort → 400 ===
{"error":"invalid sort"}
status=400

=== Negative: cursor sort key mismatch → 400 ===
{"error":"cursor sort key mismatch"}
status=400

=== Filter status=done ===
{ "n": 5, "all_done": true }

=== Filter account ILIKE ===
{ "n": 3, "accounts": ["Lead_Content_1", "lead_content", "lead_content_"] }
# case-insensitive matches
```

Все 8 smoke checks green.

## T5 — Browser smoke (live page)

`https://delivery.contenthunter.ru/` — pre-restart hook validated `✅ index.html is valid`. Live page содержит обновлённый JS:
```
$ curl https://delivery.contenthunter.ru/ | grep -cE "createPaginatedTable|_archiveTable|archive-sentinel"
10
```

Пользователь увидит:
- 100 строк вместо 200 на первой странице
- Scroll догрузит следующие 100 (IntersectionObserver на sentinel)
- Filter «Аккаунт» / «Статус» / «Платформа» — server-side, обновляет таблицу

## PM2 restart

```
restart #213, status=online, uptime=stable
exec cwd=/root/.openclaw/workspace-genri/autowarm (no drift)
unstable_restarts=0
errors in logs: empty
```

## Open follow-ups (не закрыты этим планом)

Из бэклога `paginated-tables-etap3-backlog-20260428.md` — 6/7 миграций остаются:

| # | Endpoint | Размер | Live? |
|---|---|---|---|
| 2 | `/api/unic/tasks` | 1540 | ✅ |
| 3 | `/api/factory/tasks` + `/api/factory/accounts` | 1253 | ✅ |
| 4 | `/api/whatsapp/tasks` | ? | ✅ |
| 5 | `/api/telegram/tasks` | ? | ✅ |
| 6 | `/api/phone-warm/tasks` | ? | ✅ |
| 7 | `/api/tasks` (общий) | ? | ? |

Каждая = ~0.5 дня по бэклогу.

Также **backport pilot+etap2 в `autowarm-testbench`** — testbench всё ещё отстаёт ~6 коммитов.

## Memory updates

- `MEMORY.md` — bump entry про paginated tables.
- `project_paginated_tables_pilot.md` — обновить status: «✅ etap 3 миграция #1 (archive) shipped 2026-04-29».
- `paginated-tables-etap3-backlog-20260428.md` — отметить archive как closed.

## Commits

| Repo | Branch | SHA | Message |
|---|---|---|---|
| `delivery-contenthunter` (prod) | `main` | `512fd80` | `feat(server): cursor pagination + stats for /api/archive/tasks` |
| `delivery-contenthunter` (prod) | `main` | `af2ffd1` | `feat(ui): /archive table через paginated-table factory + TDZ guard` |
| `contenthunter` | `fix/testbench-publisher-base-imports-20260427` | (pending) | `docs(plans+evidence): paginated tables etap 3 #1 — executed T0-T6` |
