# PLAN — Paginated tables этап 3, миграция #1: `/api/archive/tasks`

**Тип:** feat (server pagination + frontend factory rollout)
**Создан:** 2026-04-29
**Режим:** Full
**Источник:** `paginated-tables-etap3-backlog-20260428.md` (P1, миграция #1 из 7)

**Репо:**
- Код: `/root/.openclaw/workspace-genri/autowarm/` (post-commit hook → `GenGo2/delivery-contenthunter`).
- Plan/evidence: `/home/claude-user/contenthunter/`.

## Settings

- Testing: yes — paginate.test.js регрессия + smoke endpoints.
- Logging: warn-only — нет новых event-категорий.
- Docs: warn-only — evidence обязателен.

## Контекст

`archive_tasks` — 6360 строк, default sort `started_at DESC`. EXPLAIN показал Seq Scan + top-N heapsort (1.9ms / 118 buffers); cursor предикат тоже Seq Scan. > 5k threshold → нужен композитный индекс.

Текущий `/api/archive/tasks`: `SELECT * FROM archive_tasks ORDER BY started_at DESC LIMIT 200` — ВСЕГДА 200 строк, никаких filters/cursor. Frontend делает client-side filter в `filterArchiveTasks()` через `_archiveAll[]`.

Helper API готов: `paginate.js` (server) + `paginated-table.js` (frontend factory).

## Scope

**В scope:**
- T1 — миграция composite index
- T2 — backend rewrite `/api/archive/tasks` через helper + новый `/api/archive/tasks/stats`
- T3 — frontend через factory
- T4 — smoke endpoints
- T5 — browser smoke
- T6 — evidence + commits

**НЕ в scope:**
- `/api/archive/tasks/by-ids` — backlog говорит `liveRefresh=false` для archive, не нужен.
- Остальные 6 миграций этапа 3 — отдельные сессии.

## Задачи

### T0. Pre-check: EXPLAIN с предложенным индексом

Проверить что index ускорит cursor predicate:

```sql
BEGIN;
CREATE INDEX archive_tasks_started_at_id_idx ON archive_tasks (started_at DESC, id DESC);
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM archive_tasks ORDER BY started_at DESC LIMIT 100;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM archive_tasks WHERE (started_at, id) < ('2026-04-29 06:00:00', 6000) ORDER BY started_at DESC, id DESC LIMIT 100;
ROLLBACK;
```

Ожидание: Index Scan вместо Seq Scan + Sort.

### T1. Migration: композитный индекс

Файл: `migrations/20260429_archive_tasks_index.sql`:

```sql
-- Cursor pagination для /api/archive/tasks (этап 3 paginated tables).
-- 6360 rows, default sort started_at DESC. Без индекса cursor предикат =
-- Seq Scan + Sort на каждой странице → O(n) при load-more.
CREATE INDEX CONCURRENTLY IF NOT EXISTS archive_tasks_started_at_id_idx
  ON archive_tasks (started_at DESC, id DESC);
```

Применить: `psql ... -f migrations/20260429_archive_tasks_index.sql`. CONCURRENTLY — ~2-5s, prod не блокируется.

### T2. Backend: cursor pagination + filters + /stats

Файл: `server.js`. Заменить `app.get('/api/archive/tasks', ...)` (line 705-712):

```javascript
// === ARCHIVE TASKS — cursor pagination (etap 3 #1) ===
const ARCHIVE_TASKS_SORT_WHITELIST = {
  id:           'at.id',
  started_at:   'at.started_at',
  finished_at:  'at.finished_at',
  status:       'at.status',
  platform:     'at.platform',
  device_serial:'at.device_serial',
};
const ARCHIVE_TASKS_SELECT = `at.*`;
const ARCHIVE_TASKS_FROM = `FROM archive_tasks at`;

function buildArchiveTasksFilters(query) {
  const conds = [];
  const params = [];
  const push = (sql, val) => { params.push(val); conds.push(sql.replace('$?', '$' + params.length)); };

  if (query.status) {
    const list = String(query.status).split(',').map(s => s.trim()).filter(Boolean);
    if (list.length === 1) push("at.status = $?", list[0]);
    else if (list.length > 1) push("at.status = ANY($?::text[])", list);
  }
  if (query.platform)      push("at.platform = $?",      String(query.platform));
  if (query.device_serial) push("at.device_serial = $?", String(query.device_serial));
  if (query.account) {
    const s = `%${String(query.account).replace(/[%_]/g, m => '\\' + m)}%`;
    push("at.account ILIKE $?", s);
  }
  return { whereSql: conds.length ? 'WHERE ' + conds.join(' AND ') : '', params };
}

app.get('/api/archive/tasks', async (req, res) => {
  try {
    // BACKWARDS-COMPAT: без limit/cursor → legacy array (плоский, без cursor),
    // чтобы не сломать старые клиенты пока фронт мигрирует.
    const isLegacyCall = req.query.limit === undefined && req.query.cursor === undefined;
    if (isLegacyCall) {
      const { rows } = await pool.query(`
        SELECT ${ARCHIVE_TASKS_SELECT}
        ${ARCHIVE_TASKS_FROM}
        ORDER BY at.started_at DESC, at.id DESC
        LIMIT 200
      `);
      return res.json(rows);
    }
    
    const sortKey = String(req.query.sort || 'started_at');
    if (!ARCHIVE_TASKS_SORT_WHITELIST[sortKey]) return res.status(400).json({ error: 'invalid sort' });
    let limit = parseInt(req.query.limit, 10);
    if (!Number.isInteger(limit) || limit < 1) limit = 100;
    if (limit > 500) limit = 500;
    const cursor = decodeCursor(req.query.cursor);
    if (cursor && cursor.sk !== sortKey) {
      return res.status(400).json({ error: 'cursor sort key mismatch' });
    }
    const { whereSql, params } = buildArchiveTasksFilters(req.query);
    const { sql } = buildPaginatedQuery({
      selectClause: ARCHIVE_TASKS_SELECT,
      fromClause: ARCHIVE_TASKS_FROM,
      sortWhitelist: ARCHIVE_TASKS_SORT_WHITELIST,
      sortKey, order: req.query.order, cursor, limit,
      whereSql, params, idCol: 'at.id',
    });
    const { rows } = await pool.query(sql, params);
    const result = processPaginatedResult({ rows, limit, sortKey, cursorValueExtractor: (r) => r[sortKey] });
    res.json(result);
  } catch (e) {
    console.error('[GET /api/archive/tasks]', e);
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/archive/tasks/stats', async (req, res) => {
  try {
    const { whereSql, params } = buildArchiveTasksFilters(req.query);
    const { sql } = buildStatsQuery({
      fromClause: ARCHIVE_TASKS_FROM,
      whereSql, params, statusCol: 'at.status',
    });
    const { rows } = await pool.query(sql, params);
    const by_status = {};
    let total = 0;
    for (const r of rows) {
      const k = r.status || 'unknown';
      const n = parseInt(r.n, 10) || 0;
      by_status[k] = n;
      total += n;
    }
    res.json({ total, by_status });
  } catch (e) {
    console.error('[GET /api/archive/tasks/stats]', e);
    res.status(500).json({ error: e.message });
  }
});
```

Note: текущий `/api/archive/stats` (отдельный endpoint, не часть моего scope) уже существует для today/week агрегатов; новый `/api/archive/tasks/stats` — это group-by-status для filters, отдельный endpoint, name-spaced под `/tasks/`.

### T3. Frontend: factory + thin wrappers + TDZ guard

Файл: `public/index.html`.

**Изменения markup (~line 1949):**
- Добавить sentinel-row в конец `<tbody id="archive-tasks-table">` для intersection observer.

**Изменения JS (~line 5453-5520):**

```javascript
// ===== АРХИВАЦИЯ (paginated-table factory) =====
let _archiveTable = null;
let _archiveTableInit = false;

function _ensureArchiveTable() {
  if (_archiveTableInit) return _archiveTable;
  _archiveTableInit = true;
  _archiveTable = createPaginatedTable({
    endpoint: '/api/archive/tasks',
    statsEndpoint: '/api/archive/tasks/stats',
    tableBodyId: 'archive-tasks-table',
    sentinelId: 'archive-sentinel',
    defaultSort: 'started_at',
    defaultOrder: 'desc',
    pageSize: 100,
    liveRefresh: false,
    rowRenderer: renderArchiveRow,
    emptyMessage: 'Нет задач',
    colspan: 7,
  });
  return _archiveTable;
}

async function loadArchive() {
  // TDZ guard на случай первого вызова из nav() / initialization
  try {
    const tbl = _ensureArchiveTable();
    await tbl.reload();
    // Top-of-page агрегаты (today/week) — отдельный endpoint
    try {
      const stats = await fetch('/api/archive/stats').then(r => r.json());
      document.getElementById('arc-stat-today').textContent    = stats.tasks_today   ?? '—';
      document.getElementById('arc-stat-week').textContent     = stats.tasks_week    ?? '—';
      document.getElementById('arc-stat-checked').textContent  = stats.checked_week  ?? '—';
      document.getElementById('arc-stat-archived').textContent = stats.archived_week ?? '—';
    } catch {}
  } catch (e) {
    if (e instanceof ReferenceError) {
      // TDZ — _archiveTable пока не инициализирован, defer
      setTimeout(() => loadArchive(), 0);
      return;
    }
    document.getElementById('archive-tasks-table').innerHTML =
      `<tr><td colspan="7" class="px-4 py-8 text-center text-red-400">Ошибка: ${e.message}</td></tr>`;
  }
}

function filterArchiveTasks() {
  const filters = {};
  const qa = (document.getElementById('arc-filter-account')?.value || '').trim();
  const qs = document.getElementById('arc-filter-status')?.value || '';
  const qp = document.getElementById('arc-filter-platform')?.value || '';
  if (qa) filters.account = qa;
  if (qs) filters.status = qs;
  if (qp) filters.platform = qp;
  if (_archiveTable) _archiveTable.setFilters(filters);
}

function renderArchiveRow(t) {
  const colors = {
    done:    'bg-green-100 text-green-700',
    running: 'bg-blue-100 text-blue-700',
    failed:  'bg-red-100 text-red-700',
    pending: 'bg-yellow-100 text-yellow-700',
  };
  const dt = t.started_at ? new Date(t.started_at).toLocaleString('ru', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
  const cls = colors[t.status] || 'bg-gray-100 text-gray-500';
  const platformIcons = { instagram: '📸', tiktok: '🎵', youtube: '▶️' };
  const pIcon = platformIcons[t.platform] || '📱';
  const archBar = t.videos_checked > 0
    ? `<div class="w-full bg-gray-100 rounded-full h-1.5 mt-1"><div class="bg-indigo-400 h-1.5 rounded-full" style="width:${Math.round(t.videos_archived/t.videos_checked*100)}%"></div></div>`
    : '';
  // ... остальной row HTML (как было в renderArchiveTasks)
}
```

Удалить старые `_archiveAll`, `loadArchive` (старая версия), `filterArchiveTasks` (старая), `renderArchiveTasks`. Сохранить полную HTML-структуру row внутри `renderArchiveRow`.

### T4. Smoke endpoints

```bash
# Legacy compat (без params) — должен вернуть array, не object
curl -s 'http://localhost:3000/api/archive/tasks' | jq 'type'
# expected: "array"

# Paginated (1-я страница)
curl -s 'http://localhost:3000/api/archive/tasks?limit=5' | jq '{type:.type, has_more:.has_more, n:(.rows|length)}'
# expected: object, has_more=true, n=5

# Stats
curl -s 'http://localhost:3000/api/archive/tasks/stats' | jq '.total, (.by_status|keys|length)'
# expected: total ≥ 6360, status keys

# Cursor next page
CURSOR=$(curl -s 'http://localhost:3000/api/archive/tasks?limit=5' | jq -r .next_cursor)
curl -s "http://localhost:3000/api/archive/tasks?limit=5&cursor=$CURSOR" | jq '.rows | length'
# expected: 5

# Negative: invalid cursor → fall-back на 1-ю страницу
curl -s 'http://localhost:3000/api/archive/tasks?limit=5&cursor=garbage' -w '\n%{http_code}'
# expected: 200, valid first-page response (decodeCursor возвращает null на garbage)

# Negative: sort key mismatch
CURSOR2=$(curl -s 'http://localhost:3000/api/archive/tasks?sort=id&limit=5' | jq -r .next_cursor)
curl -s "http://localhost:3000/api/archive/tasks?sort=started_at&limit=5&cursor=$CURSOR2" -w '\n%{http_code}'
# expected: 400 'cursor sort key mismatch'

# Negative: invalid sort
curl -s 'http://localhost:3000/api/archive/tasks?sort=garbage&limit=5' -w '\n%{http_code}'
# expected: 400 'invalid sort'

# Filter + pagination
curl -s 'http://localhost:3000/api/archive/tasks?status=done&limit=5' | jq '.rows | length'
```

### T5. Browser smoke

1. `https://delivery.contenthunter.ru/` → клик «🗄️ Архивация»
2. Должно показать 100 строк (не 200 как раньше).
3. Scroll в конец → подгрузка следующих 100 (sentinel observer).
4. Filter «Аккаунт» — server-side filter, обновляет таблицу.
5. Filter «Статус» — то же.
6. Edge: invalid input в filter — graceful (просто другой набор строк).

### T6. Evidence + memory + commits

Evidence: `.ai-factory/evidence/paginated-tables-etap3-archive-20260429.md`:
- T0 EXPLAIN до/после
- T1 migration apply log
- T2 server diff
- T3 frontend diff (focus на TDZ pattern)
- T4 smoke output (8+ curl checks)
- T5 browser smoke confirmation

Memory:
- `project_paginated_tables_pilot.md` — обновить status: «✅ etap 3 миграция #1 (archive) shipped 2026-04-29; remaining 6/7».
- `paginated-tables-etap3-backlog-20260428.md` — вычеркнуть archive как closed.

Commits в prod (post-commit hook auto-push):

| # | Message |
|---|---|
| 1 | `feat(server): cursor pagination + stats for /api/archive/tasks` |
| 2 | `feat(ui): /archive table через paginated-table factory + TDZ guard` |
| (опц) 3 | `fix(ui): TDZ guard для archive load` (только если в smoke выяснится regression) |

И docs-commit в contenthunter.

## Commit Plan

2 atomic prod commits + 1 docs. Pytest gate (paginate.test.js должен остаться green) перед каждым.

## Риски

- **R1 — TDZ pitfall** (см. memory `project_paginated_tables_pilot.md`): `nav('archive')` синхронно дёргает `loadArchive()`, который ссылается на `_archiveTable` который ещё `let undefined`. Mitigation: try/catch ReferenceError + setTimeout(0) defer (как в etap 2).
- **R2 — backwards-compat layer**: legacy callers без params ожидают array. Сохранил BC layer; удалить позже когда фронт стабилизируется.
- **R3 — `started_at` может быть NULL** для row'ов pending. Cursor predicate `(started_at, id) < (X, Y)` обработает NULL правильно по PG semantics, но может потеряться на edge cases. Mitigation: проверить smoke с pending-задачами.
- **R4 — параллельная сессия** — нет других сессий paginated сейчас.

## Rollback

- Commit 1 (server): `git revert` возвращает 12-line endpoint, BC layer ничего не меняет для legacy callers.
- Commit 2 (frontend): `git revert` возвращает client-side filter. Index в БД остаётся (не вреден).
- Migration: index CONCURRENTLY → `DROP INDEX CONCURRENTLY archive_tasks_started_at_id_idx` если нужно откатить.

## Дальше

T0 (EXPLAIN с индексом) → T1 (apply migration) → T2 (server) → T3 (frontend) → T4 (smoke) → T5 (browser) → T6 (docs).

Stop-conditions:
- T0 EXPLAIN не показывает Index Scan → проверить syntax индекса.
- T4 любой curl даёт неожиданный 500 → revert последнего commit'а, разобраться.
- T5 browser smoke — TDZ или infinite scroll → fix или revert.
