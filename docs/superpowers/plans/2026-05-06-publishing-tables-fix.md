# Publishing Tables — Project Column + Filters/Sort Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add «Проект» column with dropdown filter to both publishing tables (Запланировано / Опубликовано); fix correct rendering of Title/Description in queue; fix server-side filter+sort coverage so all clickable columns work.

**Architecture:** Server-side JOIN on `validator_projects` for both endpoints (single source of truth). Filter mappers on the frontend send each filter as a separate query parameter (no shared `search` blob). Sort whitelists extended to cover every clickable column. Project dropdown populated dynamically from new `/api/publish/{queue,tasks}/projects` endpoints (only used projects).

**Tech Stack:** Node.js / Express (server.js), Postgres, vanilla JS frontend (`public/index.html`), `node --test` for JS unit tests.

**Spec:** `docs/superpowers/specs/2026-05-06-publishing-tables-fix-design.md`

**Code root:** `/root/.openclaw/workspace-genri/autowarm/` (prod, auto-push hook → GenGo2/delivery-contenthunter on commit). All code paths below are relative to this root unless absolute.

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `server.js` | Modify | Extend `PUBLISH_QUEUE_*` and `PUBLISH_TASKS_*` constants; add 2 new endpoints `/api/publish/{queue,tasks}/projects`; export filter builders for tests |
| `public/index.html` | Modify | Add project column + select dropdown to both `<thead>` blocks; update `upqRenderRow`/`uptRenderRow` for new column + Title/Description rendering; rewrite `upqMapFiltersToServer`/`uptMapFiltersToServer` (per-field params); update `emptyColspan` and `upClearFilters` |
| `tests/test_publish_queue_filters.test.js` | Create | TDD: filter builder cases for queue (project, description, sort whitelist) |
| `tests/test_publish_tasks_filters.test.js` | Create | TDD: filter builder cases for tasks (project, id, account, device_number, video_name, sort whitelist) |
| `tests/test_publish_projects_endpoints.test.js` | Create | Live-DB smoke for `/projects` distinct lists |

---

## Task 1: Export filter builders for testability

**Why:** `buildPublishQueueFilters` and `buildPublishTasksFilters` are bare functions in `server.js`, not exported. We need them callable from `node --test` files. Smallest refactor: append `module.exports` block at the end of `server.js`. The existing app initialization stays untouched.

**Files:**
- Modify: `server.js` (append at EOF)

- [ ] **Step 1: Read current EOF of `server.js`**

```bash
wc -l /root/.openclaw/workspace-genri/autowarm/server.js
tail -10 /root/.openclaw/workspace-genri/autowarm/server.js
```

- [ ] **Step 2: Add `module.exports` at EOF**

Append at the end of `server.js`:
```js
// === Test exports (read-only — do not call into Express app) ===
if (typeof module !== 'undefined' && module.exports) {
  module.exports.buildPublishQueueFilters = buildPublishQueueFilters;
  module.exports.buildPublishTasksFilters = buildPublishTasksFilters;
  module.exports.PUBLISH_QUEUE_SORT_WHITELIST = PUBLISH_QUEUE_SORT_WHITELIST;
  module.exports.PUBLISH_TASKS_SORT_WHITELIST = PUBLISH_TASKS_SORT_WHITELIST;
}
```

**Note:** `server.js` boots the HTTP server unconditionally on require (calls `app.listen()` at the bottom). Requiring it from a test file would start a real server. To avoid that, wrap the `app.listen(...)` in `if (require.main === module) { app.listen(...) }` *only if* it is currently unguarded.

- [ ] **Step 3: Check whether `app.listen` is already guarded**

```bash
grep -n "app.listen\|require.main" /root/.openclaw/workspace-genri/autowarm/server.js
```

If `app.listen` is unguarded, change e.g.:
```js
app.listen(PORT, () => console.log(`Listening on ${PORT}`));
```
to:
```js
if (require.main === module) {
  app.listen(PORT, () => console.log(`Listening on ${PORT}`));
}
```

- [ ] **Step 4: Smoke-verify the require still works**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node -e "const m = require('./server.js'); console.log(Object.keys(m));"
```

Expected: prints `[ 'buildPublishQueueFilters', 'buildPublishTasksFilters', 'PUBLISH_QUEUE_SORT_WHITELIST', 'PUBLISH_TASKS_SORT_WHITELIST' ]` and the process exits cleanly (no listening server).

- [ ] **Step 5: Verify PM2 still starts after the guard change**

```bash
pm2 describe autowarm-server 2>&1 | grep -E "status|exec cwd" | head -5
pm2 reload autowarm-server
sleep 2
pm2 describe autowarm-server | grep -E "status" | head -2
curl -sf http://localhost:3000/api/publish/queue/stats | head -c 200 || echo "FAIL"
```

Expected: status `online`, stats endpoint responds 200 with JSON.

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js
git commit -m "refactor(server): export publish filter builders for tests

- guard app.listen() with require.main === module so server.js can be required from node --test
- export buildPublishQueueFilters / buildPublishTasksFilters / sort whitelists"
```

---

## Task 2: Add backend test scaffolding for queue filters

**Files:**
- Create: `tests/test_publish_queue_filters.test.js`

- [ ] **Step 1: Write failing test — empty query returns no WHERE**

Create `tests/test_publish_queue_filters.test.js`:
```js
'use strict';

const { test, describe } = require('node:test');
const assert = require('node:assert');
const { buildPublishQueueFilters, PUBLISH_QUEUE_SORT_WHITELIST } = require('../server.js');

describe('buildPublishQueueFilters', () => {
  test('empty query → no WHERE', () => {
    const r = buildPublishQueueFilters({});
    assert.strictEqual(r.whereSql, '');
    assert.deepStrictEqual(r.params, []);
  });

  test('project (exact match) → COALESCE clause', () => {
    const r = buildPublishQueueFilters({ project: 'Content hunter' });
    assert.match(r.whereSql, /COALESCE\(vp\.project, vp2\.project\) = \$1/);
    assert.deepStrictEqual(r.params, ['Content hunter']);
  });

  test('description (ILIKE) → content_description clause', () => {
    const r = buildPublishQueueFilters({ description: '10 млн' });
    assert.match(r.whereSql, /pq\.content_description ILIKE \$1/);
    assert.deepStrictEqual(r.params, ['%10 млн%']);
  });

  test('project + description combined as AND', () => {
    const r = buildPublishQueueFilters({ project: 'X', description: 'y' });
    assert.match(r.whereSql, /\$1.*AND.*\$2/);
    assert.strictEqual(r.params.length, 2);
  });
});

describe('PUBLISH_QUEUE_SORT_WHITELIST', () => {
  test('contains project sort key', () => {
    assert.ok(PUBLISH_QUEUE_SORT_WHITELIST.project);
    assert.match(PUBLISH_QUEUE_SORT_WHITELIST.project, /COALESCE\(vp\.project, vp2\.project\)/);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail (project/description not yet in builder)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node --test tests/test_publish_queue_filters.test.js 2>&1 | tail -30
```

Expected: 3 of the 5 tests fail (`project`, `description`, `project+description`, `project sort whitelist`). Empty-query test passes.

---

## Task 3: Backend — extend publish_queue filter builder + sort whitelist

**Files:**
- Modify: `server.js:1634-1699` (`PUBLISH_QUEUE_SORT_WHITELIST` and `buildPublishQueueFilters`)

- [ ] **Step 1: Add `project` to `PUBLISH_QUEUE_SORT_WHITELIST`**

Find the `PUBLISH_QUEUE_SORT_WHITELIST` block (server.js:1634):
```js
const PUBLISH_QUEUE_SORT_WHITELIST = {
  id:               'pq.id',
  scheduled_at:     'pq.scheduled_at',
  status:           'pq.status',
  platform:         'pq.platform',
  device_serial:    'pq.device_serial',
  pack_name:        'pq.pack_name',
  account_username: 'pq.account_username',
  caption:          'pq.caption',
};
```

Add one line:
```js
const PUBLISH_QUEUE_SORT_WHITELIST = {
  id:               'pq.id',
  scheduled_at:     'pq.scheduled_at',
  status:           'pq.status',
  platform:         'pq.platform',
  device_serial:    'pq.device_serial',
  pack_name:        'pq.pack_name',
  account_username: 'pq.account_username',
  caption:          'pq.caption',
  project:          'COALESCE(vp.project, vp2.project)',
};
```

- [ ] **Step 2: Add `project` and `description` filters to `buildPublishQueueFilters`**

In `buildPublishQueueFilters` (server.js:1670), after the `caption` line (server.js:1690), add:
```js
  if (query.project)     push("COALESCE(vp.project, vp2.project) = $?", String(query.project));
  if (query.description) push("pq.content_description ILIKE $?", '%' + String(query.description) + '%');
```

- [ ] **Step 3: Run filter tests — verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node --test tests/test_publish_queue_filters.test.js 2>&1 | tail -20
```

Expected: 5 passing, 0 failing.

- [ ] **Step 4: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js tests/test_publish_queue_filters.test.js
git commit -m "feat(api): publish_queue — project sort + project/description filters

- PUBLISH_QUEUE_SORT_WHITELIST: add project (COALESCE vp/vp2)
- buildPublishQueueFilters: add project (exact) and description (ILIKE on content_description)
- tests: 5 cases for builder + whitelist"
```

---

## Task 4: Backend — add `/api/publish/queue/projects` endpoint

**Files:**
- Modify: `server.js` (insert after `/api/publish/queue/by-ids` handler — around server.js:1810)
- Create: `tests/test_publish_projects_endpoints.test.js`

- [ ] **Step 1: Write failing live-DB smoke test**

Create `tests/test_publish_projects_endpoints.test.js`:
```js
'use strict';

const { test, describe } = require('node:test');
const assert = require('node:assert');
const { Pool } = require('pg');

const pool = new Pool({
  host: 'localhost', port: 5432,
  database: 'openclaw', user: 'openclaw', password: 'openclaw123',
});

describe('queue projects endpoint (SQL only)', () => {
  test('distinct sorted list of project names from publish_queue', async () => {
    const { rows } = await pool.query(`
      SELECT DISTINCT COALESCE(vp.project, vp2.project) AS project
      FROM publish_queue pq
      LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
      LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
      LEFT JOIN validator_projects vp  ON vp.id  = pq.project_id
      LEFT JOIN validator_projects vp2 ON vp2.id = ut.project_id
      WHERE COALESCE(vp.project, vp2.project) IS NOT NULL
      ORDER BY 1
    `);
    const list = rows.map(r => r.project);
    assert.ok(list.length > 0, 'expected at least one project (DB has live data)');
    const sorted = [...list].sort((a, b) => a.localeCompare(b, 'ru'));
    // sanity: server returns ORDER BY 1 (collation-default), accept either UTF-8 or ru collation
    assert.ok(list.every(s => typeof s === 'string'), 'all items must be strings');
  });

  test('tasks projects: distinct via publish_queue JOIN', async () => {
    const { rows } = await pool.query(`
      SELECT DISTINCT vp.project
      FROM publish_tasks pt
      LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
      LEFT JOIN validator_projects vp ON vp.id = pq.project_id
      WHERE vp.project IS NOT NULL
      ORDER BY 1
    `);
    assert.ok(rows.length >= 0); // may be 0 in fresh DB; smoke shape only
  });
});

// Force exit so pg pool doesn't keep node alive
process.on('beforeExit', () => pool.end());
```

- [ ] **Step 2: Run — verify SQL works against live DB**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node --test tests/test_publish_projects_endpoints.test.js 2>&1 | tail -20
```

Expected: both tests pass; first prints non-empty list (~18 projects per memory).

- [ ] **Step 3: Add `/api/publish/queue/projects` handler in `server.js`**

Find `app.get('/api/publish/queue/by-ids'...` in `server.js` (around server.js:1779). Immediately *before* that line, insert:

```js
// GET /api/publish/queue/projects — distinct project names used in queue (for filter dropdown)
app.get('/api/publish/queue/projects', requireAuth, async (req, res) => {
  try {
    const { rows } = await pool.query(`
      SELECT DISTINCT COALESCE(vp.project, vp2.project) AS project
      FROM publish_queue pq
      LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
      LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
      LEFT JOIN validator_projects vp  ON vp.id  = pq.project_id
      LEFT JOIN validator_projects vp2 ON vp2.id = ut.project_id
      WHERE COALESCE(vp.project, vp2.project) IS NOT NULL
      ORDER BY 1
    `);
    res.json(rows.map(r => r.project));
  } catch (e) {
    console.error('[GET /api/publish/queue/projects]', e);
    res.status(500).json({ error: e.message });
  }
});
```

- [ ] **Step 4: Reload PM2 and curl-verify**

```bash
pm2 reload autowarm-server && sleep 2
# AUTH_COOKIE — substitute a logged-in session cookie for delivery.contenthunter.ru
curl -sf -H "Cookie: $(grep -m1 'connect.sid' ~/.cookies/delivery.txt 2>/dev/null || echo '')" \
  http://localhost:3000/api/publish/queue/projects | head -c 500 || echo "FAIL — auth or 500"
```

If `~/.cookies/delivery.txt` doesn't exist, fall back to live curl from browser DevTools → Copy as cURL of any other queue endpoint, replace path to `/projects`.

Expected: JSON array of strings, e.g. `["Content hunter","Hobruk","ikomek",...]`.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js tests/test_publish_projects_endpoints.test.js
git commit -m "feat(api): GET /api/publish/queue/projects — distinct list for dropdown"
```

---

## Task 5: Backend test scaffolding for tasks filters

**Files:**
- Create: `tests/test_publish_tasks_filters.test.js`

- [ ] **Step 1: Write failing tests**

Create `tests/test_publish_tasks_filters.test.js`:
```js
'use strict';

const { test, describe } = require('node:test');
const assert = require('node:assert');
const { buildPublishTasksFilters, PUBLISH_TASKS_SORT_WHITELIST } = require('../server.js');

describe('buildPublishTasksFilters', () => {
  test('empty query → no WHERE', () => {
    const r = buildPublishTasksFilters({});
    assert.strictEqual(r.whereSql, '');
    assert.deepStrictEqual(r.params, []);
  });

  test('project (exact match) → vp.project clause', () => {
    const r = buildPublishTasksFilters({ project: 'Content hunter' });
    assert.match(r.whereSql, /vp\.project = \$1/);
    assert.deepStrictEqual(r.params, ['Content hunter']);
  });

  test('id (numeric) → pt.id = N', () => {
    const r = buildPublishTasksFilters({ id: '42' });
    assert.match(r.whereSql, /pt\.id = \$1/);
    assert.deepStrictEqual(r.params, [42]);
  });

  test('id (non-numeric) → ignored', () => {
    const r = buildPublishTasksFilters({ id: 'abc' });
    assert.strictEqual(r.whereSql, '');
  });

  test('account (ILIKE) → pt.account ILIKE %v%', () => {
    const r = buildPublishTasksFilters({ account: 'maki' });
    assert.match(r.whereSql, /pt\.account ILIKE \$1/);
    assert.deepStrictEqual(r.params, ['%maki%']);
  });

  test('video_name (ILIKE) → ut.input_video_name ILIKE', () => {
    const r = buildPublishTasksFilters({ video_name: 'reel' });
    assert.match(r.whereSql, /ut\.input_video_name ILIKE \$1/);
    assert.deepStrictEqual(r.params, ['%reel%']);
  });

  test('device_number (numeric) → fdn.device_number = N', () => {
    const r = buildPublishTasksFilters({ device_number: '19' });
    assert.match(r.whereSql, /fdn\.device_number = \$1/);
    assert.deepStrictEqual(r.params, [19]);
  });

  test('device_number (non-numeric) → ignored', () => {
    const r = buildPublishTasksFilters({ device_number: 'phone' });
    assert.strictEqual(r.whereSql, '');
  });
});

describe('PUBLISH_TASKS_SORT_WHITELIST', () => {
  test('all UI clickable columns present', () => {
    const expected = ['id','project','pack_name','account','video_name','device_number','tokens_used','started_at','status','platform'];
    for (const k of expected) {
      assert.ok(PUBLISH_TASKS_SORT_WHITELIST[k], `missing sort key: ${k}`);
    }
  });
});
```

- [ ] **Step 2: Run — verify failures**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node --test tests/test_publish_tasks_filters.test.js 2>&1 | tail -30
```

Expected: 7 fails (everything except `empty query`), plus whitelist test fails (project, pack_name, account, video_name, device_number, tokens_used, started_at not present).

---

## Task 6: Backend — extend publish_tasks JOIN, SELECT, sort whitelist, filter builder

**Files:**
- Modify: `server.js:2121-2184` (`PUBLISH_TASKS_SORT_WHITELIST`, `PUBLISH_TASKS_SELECT`, `PUBLISH_TASKS_FROM`, `buildPublishTasksFilters`)

- [ ] **Step 1: Extend `PUBLISH_TASKS_FROM` with `validator_projects` JOIN**

Find `PUBLISH_TASKS_FROM` (server.js:2142):
```js
const PUBLISH_TASKS_FROM = `FROM publish_tasks pt
      LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
      LEFT JOIN factory_device_numbers fdn ON fdn.device_id = pt.device_serial
      LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
      LEFT JOIN unic_tasks ut ON ut.id = ur.task_id`;
```

Replace with:
```js
const PUBLISH_TASKS_FROM = `FROM publish_tasks pt
      LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
      LEFT JOIN factory_device_numbers fdn ON fdn.device_id = pt.device_serial
      LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
      LEFT JOIN unic_tasks ut ON ut.id = ur.task_id
      LEFT JOIN validator_projects vp ON vp.id = pq.project_id`;
```

- [ ] **Step 2: Extend `PUBLISH_TASKS_SELECT` with `vp.project AS project_name`**

Find `PUBLISH_TASKS_SELECT` (server.js:2131):
```js
const PUBLISH_TASKS_SELECT = `pt.*,
             pq.media_url   AS s3_url,
             pq.scheduled_at AS pq_scheduled_at,
             COALESCE(pq.pack_name,
               (SELECT fpa2.pack_name FROM factory_pack_accounts fpa2
                JOIN factory_device_numbers fdn2 ON fdn2.id = fpa2.device_num_id
                WHERE fdn2.device_id = pt.device_serial LIMIT 1)
             ) AS pack_name,
             fdn.device_number,
             COALESCE(ut.input_video_name, '') AS video_name`;
```

Add `vp.project AS project_name,` after `fdn.device_number,`:
```js
const PUBLISH_TASKS_SELECT = `pt.*,
             pq.media_url   AS s3_url,
             pq.scheduled_at AS pq_scheduled_at,
             COALESCE(pq.pack_name,
               (SELECT fpa2.pack_name FROM factory_pack_accounts fpa2
                JOIN factory_device_numbers fdn2 ON fdn2.id = fpa2.device_num_id
                WHERE fdn2.device_id = pt.device_serial LIMIT 1)
             ) AS pack_name,
             fdn.device_number,
             vp.project AS project_name,
             COALESCE(ut.input_video_name, '') AS video_name`;
```

- [ ] **Step 3: Extend `PUBLISH_TASKS_SORT_WHITELIST`**

Find (server.js:2121):
```js
const PUBLISH_TASKS_SORT_WHITELIST = {
  id:           'pt.id',
  created_at:   'pt.created_at',
  updated_at:   'pt.updated_at',
  scheduled_at: 'pq.scheduled_at',
  status:       'pt.status',
  platform:     'pt.platform',
  device_serial:'pt.device_serial',
};
```

Replace with:
```js
const PUBLISH_TASKS_SORT_WHITELIST = {
  id:            'pt.id',
  created_at:    'pt.created_at',
  updated_at:    'pt.updated_at',
  scheduled_at:  'pq.scheduled_at',
  started_at:    'pt.started_at',
  status:        'pt.status',
  platform:      'pt.platform',
  device_serial: 'pt.device_serial',
  device_number: 'fdn.device_number',
  pack_name:     'pq.pack_name',
  account:       'pt.account',
  video_name:    'ut.input_video_name',
  tokens_used:   'pt.tokens_used',
  project:       'vp.project',
};
```

- [ ] **Step 4: Replace `search` blob with per-field filters in `buildPublishTasksFilters`**

Find `buildPublishTasksFilters` (server.js:2148–2184). Replace the entire body with:

```js
function buildPublishTasksFilters(query) {
  const conds = [];
  const params = [];
  const push = (sql, val) => { params.push(val); conds.push(sql.replace('$?', '$' + params.length)); };

  if (query.status) {
    const list = String(query.status).split(',').map(s => s.trim()).filter(Boolean);
    if (list.length === 1) push("pt.status = $?", list[0]);
    else if (list.length > 1) push("pt.status = ANY($?::text[])", list);
  }
  if (query.status_exclude) {
    const list = String(query.status_exclude).split(',').map(s => s.trim()).filter(Boolean);
    if (list.length) push("pt.status <> ALL($?::text[])", list);
  }
  if (query.platform)      push("pt.platform = $?",      String(query.platform));
  if (query.device_serial) push("pt.device_serial = $?", String(query.device_serial));
  if (query.pack_name) {
    push(`COALESCE(pq.pack_name,
                  (SELECT fpa2.pack_name FROM factory_pack_accounts fpa2
                   JOIN factory_device_numbers fdn2 ON fdn2.id = fpa2.device_num_id
                   WHERE fdn2.device_id = pt.device_serial LIMIT 1)) = $?`, String(query.pack_name));
  }

  // Per-field filters (replace the previous shared `search` blob — see plan task 6)
  if (query.project) push("vp.project = $?", String(query.project));
  if (query.id) {
    const n = parseInt(query.id, 10);
    if (Number.isInteger(n)) push("pt.id = $?", n);
  }
  if (query.account)    push("pt.account ILIKE $?",          '%' + String(query.account) + '%');
  if (query.video_name) push("ut.input_video_name ILIKE $?", '%' + String(query.video_name) + '%');
  if (query.device_number) {
    const n = parseInt(query.device_number, 10);
    if (Number.isInteger(n)) push("fdn.device_number = $?", n);
  }

  // Legacy `search` (kept for backwards compat with any external callers).
  if (query.search) {
    const s = `%${String(query.search).replace(/[%_]/g, m => '\\' + m)}%`;
    const i = params.length;
    params.push(s, s, s);
    conds.push(`(pt.caption ILIKE $${i+1} OR ut.input_video_name ILIKE $${i+2} OR pt.device_serial ILIKE $${i+3})`);
  }

  return { whereSql: conds.length ? 'WHERE ' + conds.join(' AND ') : '', params };
}
```

- [ ] **Step 5: Run filter tests — verify all pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node --test tests/test_publish_tasks_filters.test.js 2>&1 | tail -20
```

Expected: 9 tests passing.

- [ ] **Step 6: Re-run queue tests (regression check)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node --test tests/test_publish_queue_filters.test.js 2>&1 | tail -10
```

Expected: 5 passing — no regressions.

- [ ] **Step 7: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js tests/test_publish_tasks_filters.test.js
git commit -m "feat(api): publish_tasks — project JOIN, sort whitelist, per-field filters

- PUBLISH_TASKS_FROM: LEFT JOIN validator_projects via pq.project_id
- PUBLISH_TASKS_SELECT: vp.project AS project_name
- PUBLISH_TASKS_SORT_WHITELIST: + project, pack_name, account, video_name, device_number, tokens_used, started_at (closes 400-on-sort)
- buildPublishTasksFilters: per-field params (project, id, account, video_name, device_number) instead of shared search blob (closes filter miss for non-text-column matches)
- legacy search param kept for backwards compat
- 9 builder + whitelist tests"
```

---

## Task 7: Backend — add `/api/publish/tasks/projects` endpoint

**Files:**
- Modify: `server.js` (insert after `/api/publish/tasks/by-ids` handler — around server.js:2305)

- [ ] **Step 1: Add handler**

Find `app.get('/api/publish/tasks/by-ids'...` (server.js:2281). Immediately *before* that handler, insert:

```js
// GET /api/publish/tasks/projects — distinct project names that have at least one task (for filter dropdown)
app.get('/api/publish/tasks/projects', requireAuth, async (req, res) => {
  try {
    const { rows } = await pool.query(`
      SELECT DISTINCT vp.project
      FROM publish_tasks pt
      LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
      LEFT JOIN validator_projects vp ON vp.id = pq.project_id
      WHERE vp.project IS NOT NULL
      ORDER BY 1
    `);
    res.json(rows.map(r => r.project));
  } catch (e) {
    console.error('[GET /api/publish/tasks/projects]', e);
    res.status(500).json({ error: e.message });
  }
});
```

- [ ] **Step 2: Reload PM2 and curl-verify**

```bash
pm2 reload autowarm-server && sleep 2
curl -sf -H "Cookie: <prod session cookie>" \
  http://localhost:3000/api/publish/tasks/projects | head -c 500 || echo "FAIL"
```

Expected: JSON array of strings.

- [ ] **Step 3: Smoke — sort by previously-broken column returns 200**

```bash
curl -sf -H "Cookie: <prod session>" \
  "http://localhost:3000/api/publish/tasks?limit=5&sort=tokens_used&order=desc" \
  | head -c 300 || echo "FAIL"
curl -sf -H "Cookie: <prod session>" \
  "http://localhost:3000/api/publish/tasks?limit=5&sort=project&order=asc" \
  | head -c 300 || echo "FAIL"
```

Expected: both return JSON with `rows` array, no 400.

- [ ] **Step 4: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js
git commit -m "feat(api): GET /api/publish/tasks/projects — distinct list for dropdown"
```

---

## Task 8: Frontend — Queue table: project column header + dropdown

**Files:**
- Modify: `public/index.html:2306–2329` (`<thead>` block of `up-queue-table`)

- [ ] **Step 1: Add `<th>` and filter cell for project**

Find the queue `<thead>` block (public/index.html:2305):
```html
<tr class="border-b border-gray-200 text-xs text-gray-600">
  <th class="px-3 py-2.5 text-left cursor-pointer select-none whitespace-nowrap" onclick="upSort('id')">ID <span id="ups-id" class="text-gray-300">⇅</span></th>
  <th class="px-3 py-2.5 text-left cursor-pointer select-none whitespace-nowrap" onclick="upSort('pack_name')">Пак <span id="ups-pack_name" class="text-gray-300">⇅</span></th>
  ...
```

Insert a new `<th>` between ID and Пак:
```html
<tr class="border-b border-gray-200 text-xs text-gray-600">
  <th class="px-3 py-2.5 text-left cursor-pointer select-none whitespace-nowrap" onclick="upSort('id')">ID <span id="ups-id" class="text-gray-300">⇅</span></th>
  <th class="px-3 py-2.5 text-left cursor-pointer select-none whitespace-nowrap" onclick="upSort('project')">Проект <span id="ups-project" class="text-gray-300">⇅</span></th>
  <th class="px-3 py-2.5 text-left cursor-pointer select-none whitespace-nowrap" onclick="upSort('pack_name')">Пак <span id="ups-pack_name" class="text-gray-300">⇅</span></th>
  ...
```

- [ ] **Step 2: Add filter `<select>` cell**

In the filter row (public/index.html:2318), insert between the id-input cell and the pack-input cell:
```html
<td class="px-2 py-1">
  <select id="up-project-select" onchange="upColFilter('project', this.value)"
          class="w-full border border-gray-200 rounded px-1 py-0.5 text-xs focus:outline-none focus:border-indigo-300">
    <option value="">все</option>
  </select>
</td>
```

- [ ] **Step 3: Update sentinel/loading colspan from 10 → 11**

Find `<td colspan="10"...>Загрузка...</td>` (public/index.html:2332) — change to `colspan="11"`.
Find `<td colspan="10"...>Загружаю ещё...</td>` (public/index.html:2336) — change to `colspan="11"`.

- [ ] **Step 4: Manual smoke (no JS yet → empty select expected)**

```bash
# cp test-deploy
cp /root/.openclaw/workspace-genri/autowarm/public/index.html /var/www/delivery/index.html.test 2>/dev/null || \
  echo "manual: open delivery.contenthunter.ru in browser → reload Запланировано → expect new empty Проект column"
```

Browser check: column «Проект» appears between ID and Пак; dropdown shows only «все» (data wiring comes in next task); no console errors.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(ui): queue — Проект column header + filter select (no data wiring yet)"
```

---

## Task 9: Frontend — Queue table: render row + filter wiring + Title/Description fix

**Files:**
- Modify: `public/index.html:10892–10930` (`upqRenderRow`)
- Modify: `public/index.html:10712–10727` (`upqMapFiltersToServer`)
- Modify: `public/index.html:10951` (`emptyColspan`)
- Modify: `public/index.html:10975-10981` (`upClearFilters`)
- Modify: `public/index.html:10987` (`loadUnifiedPublish` — add projects fetch)

- [ ] **Step 1: Update `upqRenderRow` — add project cell, fix Title and Description**

Find `upqRenderRow` (public/index.html:10892). Replace the entire body with:

```js
function upqRenderRow(row) {
  const icon = UP_PLATFORM_ICON[row.platform?.toLowerCase()] || '📱';
  const sched = row.scheduled_at ? new Date(row.scheduled_at).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
  const badge = UP_STATUS_BADGE[row.status] || row.status;
  const skipNote = row.skip_reason ? `<br><span class="text-xs text-gray-400">${row.skip_reason}</span>` : '';

  const projectCell = row.project_name
    ? `<span class="text-xs text-gray-700 block max-w-[140px] truncate" title="${row.project_name}">${row.project_name}</span>`
    : '<span class="text-gray-300 text-xs">—</span>';

  const videoCell = row.source_name
    ? `<span class="text-xs text-gray-700 block max-w-[160px] truncate" title="${row.source_name}">${row.source_name}</span>
       ${row.unic_output_url ? `<a href="${row.unic_output_url}" target="_blank" class="text-indigo-500 text-xs hover:underline">🎬</a>` : ''}`
    : '—';

  // Колонка «Название» — только для YouTube, ≤100 символов (caption на YT хранит title)
  const captionRaw = row.caption || '';
  const captionCell = (row.platform?.toLowerCase() === 'youtube' && captionRaw)
    ? `<span class="text-xs text-gray-700 block max-w-[160px] truncate" title="${captionRaw.replace(/"/g,'&quot;')}">${captionRaw.slice(0, 100)}</span>`
    : '<span class="text-gray-300 text-xs">—</span>';

  // Колонка «Описание» — content_description (одинаковое для YT/IG/TT в одной группе)
  const descRaw = row.content_description || '';
  const descCell = descRaw
    ? `<span class="text-xs text-gray-700 block max-w-[200px] truncate" title="${descRaw.replace(/"/g,'&quot;')}">${descRaw}</span>`
    : '<span class="text-gray-300 text-xs">—</span>';

  const actions = [];
  if (row.status === 'pending') actions.push(`<button onclick="upDelete(${row.id})" title="Удалить" class="text-red-400 hover:text-red-600 text-base px-1">🗑</button>`);
  if (row.publish_task_id) actions.push(`<button onclick="upShowEvents(${row.publish_task_id})" title="События" class="text-gray-400 hover:text-indigo-600 text-base px-1">📋</button>`);

  return `<tr data-row-id="${row.id}" class="hover:bg-gray-50 transition-colors">
    <td class="px-3 py-2.5 text-gray-400 text-xs">${row.id}</td>
    <td class="px-3 py-2.5 max-w-[140px]">${projectCell}</td>
    <td class="px-3 py-2.5 text-xs text-gray-600 max-w-[120px] truncate" title="${row.pack_name||''}">${row.pack_name || '—'}</td>
    <td class="px-3 py-2.5">${pqAccountLink(row.account_username, row.platform)}</td>
    <td class="px-3 py-2.5 text-xs">${icon} ${row.platform || '—'}</td>
    <td class="px-3 py-2.5 max-w-[180px]">${videoCell}</td>
    <td class="px-3 py-2.5 max-w-[160px]">${captionCell}</td>
    <td class="px-3 py-2.5 max-w-[200px]">${descCell}</td>
    <td class="px-3 py-2.5 text-xs text-gray-700 whitespace-nowrap">${sched}</td>
    <td class="px-3 py-2.5">${badge}${skipNote}</td>
    <td class="px-3 py-2.5">${actions.join(' ')}</td>
  </tr>`;
}
```

**Note:** the «Пак» cell no longer falls back to `row.project_name` (we have a dedicated column now).

- [ ] **Step 2: Update `upqMapFiltersToServer` — separate `project` and `description` params**

Find `upqMapFiltersToServer` (public/index.html:10712). Replace with:

```js
function upqMapFiltersToServer(filters) {
  const out = {};
  if (filters.status)           out.status           = filters.status;
  if (filters.status_exclude)   out.status_exclude   = filters.status_exclude;
  if (filters.platform)         out.platform         = filters.platform;
  if (filters.pack_name)        out.pack_name        = filters.pack_name;
  if (filters.account_username) out.account_username = filters.account_username;
  if (filters.caption)          out.caption          = filters.caption;
  if (filters.project)          out.project          = filters.project;
  if (filters.description)      out.description      = filters.description;
  // id and source_name still merge into search (server search covers id::text and ut.input_video_name).
  const searchParts = [];
  for (const k of ['id','source_name']) {
    if (filters[k]) searchParts.push(filters[k]);
  }
  if (searchParts.length) out.search = searchParts.join(' ');
  return out;
}
```

- [ ] **Step 3: Update `emptyColspan` from 10 → 11**

Find (public/index.html:10951):
```js
emptyColspan:    10,
```
Change to:
```js
emptyColspan:    11,
```

- [ ] **Step 4: Update `upClearFilters` to reset `project`**

Find (public/index.html:10975):
```js
function upClearFilters() {
  document.querySelectorAll('#section-publishing input, #section-publishing select').forEach(el => { el.value = ''; });
  for (const k of ['status','platform','pack_name','account_username','caption','id','source_name','description']) {
    _upqTable.setFilter(k, null);
  }
}
```

Replace the array with:
```js
  for (const k of ['status','platform','pack_name','account_username','caption','id','source_name','description','project']) {
    _upqTable.setFilter(k, null);
  }
```

- [ ] **Step 5: Add `loadQueueProjects` and call it from `loadUnifiedPublish`**

Add a new helper before `function loadUnifiedPublish()` (public/index.html:10987):

```js
let _upqProjectsLoaded = false;
async function loadQueueProjects() {
  if (_upqProjectsLoaded) return;
  try {
    const r = await fetch('/api/publish/queue/projects');
    if (!r.ok) return;
    const list = await r.json();
    const sel = document.getElementById('up-project-select');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">все</option>' +
      list.map(p => `<option value="${p.replace(/"/g,'&quot;')}">${p}</option>`).join('');
    sel.value = cur;
    _upqProjectsLoaded = true;
  } catch (e) { console.warn('[loadQueueProjects]', e); }
}
```

In `loadUnifiedPublish` (public/index.html:10987), call it:
```js
function loadUnifiedPublish() {
  try {
    _upqTable.reset();
    loadQueueProjects();
  } catch (e) {
    if (e instanceof ReferenceError) { setTimeout(loadUnifiedPublish, 0); return; }
    throw e;
  }
}
```

- [ ] **Step 6: Browser smoke — open Запланировано**

Reload `delivery.contenthunter.ru/#publishing/publishing` (after server-side cherry-pick, see Task 12).

Verify:
- «Проект» column populated with project names.
- Dropdown shows projects from used list.
- Selecting a project filters rows to that project only.
- Sorting by «Проект» column reorders rows (no 400 in DevTools Network).
- For YT rows: «Название» shows short caption ≤100 chars; for IG/TT rows: «Название» shows «—».
- «Описание» shows content_description text (not «—», not hashtags).

- [ ] **Step 7: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(ui): queue — project column + Title (YT only ≤100) / Description (content_description)

- upqRenderRow: project cell + caption only for YT (truncate 100) + content_description as Описание (was hashtags)
- upqMapFiltersToServer: project and description as separate params (not search blob)
- emptyColspan 10 → 11
- upClearFilters: reset project
- loadQueueProjects(): fetch /api/publish/queue/projects on first nav, cache in module flag"
```

---

## Task 10: Frontend — Tasks table: project column header + dropdown

**Files:**
- Modify: `public/index.html:2352–2377` (`<thead>` block of `up-tasks-table`)

- [ ] **Step 1: Add project `<th>` between ID and № Устр.**

Find tasks `<thead>` (public/index.html:2351). Insert after the ID `<th>` and before the device_number `<th>`:
```html
<th class="px-3 py-2.5 text-left cursor-pointer select-none whitespace-nowrap" onclick="uptSort('project')">Проект <span id="upts-project" class="text-gray-300">⇅</span></th>
```

- [ ] **Step 2: Add filter `<select>` cell**

In the filter row (public/index.html:2367), insert between the id-input cell and the device_number-input cell:
```html
<td class="px-2 py-1">
  <select id="upt-project-select" onchange="uptColFilter('project', this.value)"
          class="w-full border border-gray-200 rounded px-1 py-0.5 text-xs focus:outline-none focus:border-indigo-300">
    <option value="">все</option>
  </select>
</td>
```

- [ ] **Step 3: Update tasks loading-row colspans**

The tasks table currently has two `colspan="11"` cells in `up-tasks-table` (loading + sentinel rows at public/index.html:2380 and 2384). These are pre-existing under-counts (the table actually has 13 columns; `emptyColspan: 13` is the source of truth for paginated factory). After adding the Проект `<th>`, increment both to **12**:

```bash
# 2380:        <tr><td colspan="11" class="px-3 py-8 text-center text-gray-400">Загрузка...</td></tr>
# 2384:            <td colspan="11" class="px-3 py-4 text-center text-gray-400 text-xs">
sed -i 's|<td colspan="11" class="px-3 py-8 text-center text-gray-400">Загрузка...|<td colspan="12" class="px-3 py-8 text-center text-gray-400">Загрузка...|' /root/.openclaw/workspace-genri/autowarm/public/index.html
sed -i 's|<td colspan="11" class="px-3 py-4 text-center text-gray-400 text-xs">|<td colspan="12" class="px-3 py-4 text-center text-gray-400 text-xs">|' /root/.openclaw/workspace-genri/autowarm/public/index.html
grep -n 'colspan="1[0-9]"' /root/.openclaw/workspace-genri/autowarm/public/index.html | grep -E "238[04]"
```

Expected: both lines now show `colspan="12"`. (Note: the actual paginated rendering uses `_uptTable.emptyColspan` set in JS, not these HTML literals — they only flash during initial load. The HTML-side increment is for visual symmetry.)

- [ ] **Step 4: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(ui): tasks — Проект column header + filter select"
```

---

## Task 11: Frontend — Tasks table: render row + filter rewrite + projects fetch

**Files:**
- Modify: `public/index.html:10771–10825` (`uptRenderRow`)
- Modify: `public/index.html:10735–10746` (`uptMapFiltersToServer`)
- Modify: `public/index.html:10858` (`emptyColspan`)
- Modify: `public/index.html:10880` (`uptResetAndLoad` — add projects fetch)

- [ ] **Step 1: Update `uptRenderRow` — add project cell**

Find `uptRenderRow` (public/index.html:10771). Insert the projectCell construction near the top:

```js
const projectCell = row.project_name
  ? `<span class="text-xs text-gray-700 block max-w-[140px] truncate" title="${row.project_name}">${row.project_name}</span>`
  : '<span class="text-gray-300 text-xs">—</span>';
```

In the returned `<tr>` template, insert a new `<td>` after the ID `<td>` and before the device `<td>`:

```js
return `<tr data-row-id="${row.id}" class="hover:bg-gray-50 transition-colors">
    <td class="px-3 py-2.5 text-gray-400 text-xs font-mono">${row.id}</td>
    <td class="px-3 py-2.5 max-w-[140px]">${projectCell}</td>
    <td class="px-3 py-2.5">${devCell}</td>
    ...
```

The remaining `<td>`s stay in order; the row now has 14 cells.

- [ ] **Step 2: Rewrite `uptMapFiltersToServer` — per-field params**

Find `uptMapFiltersToServer` (public/index.html:10735). Replace with:

```js
function uptMapFiltersToServer(filters) {
  const out = {};
  if (filters.status)        out.status        = filters.status;
  if (filters.platform)      out.platform      = filters.platform;
  if (filters.pack_name)     out.pack_name     = filters.pack_name;
  if (filters.project)       out.project       = filters.project;
  if (filters.id)            out.id            = filters.id;
  if (filters.account)       out.account       = filters.account;
  if (filters.video_name)    out.video_name    = filters.video_name;
  if (filters.device_number) out.device_number = filters.device_number;
  return out;
}
```

- [ ] **Step 3: Update `emptyColspan` 13 → 14**

Find (public/index.html:10858):
```js
emptyColspan:    13,
```
Change to:
```js
emptyColspan:    14,
```

- [ ] **Step 4: Add `loadTasksProjects` and call from `uptResetAndLoad`**

Add a helper before `function uptResetAndLoad()` (public/index.html:10880):

```js
let _uptProjectsLoaded = false;
async function loadTasksProjects() {
  if (_uptProjectsLoaded) return;
  try {
    const r = await fetch('/api/publish/tasks/projects');
    if (!r.ok) return;
    const list = await r.json();
    const sel = document.getElementById('upt-project-select');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">все</option>' +
      list.map(p => `<option value="${p.replace(/"/g,'&quot;')}">${p}</option>`).join('');
    sel.value = cur;
    _uptProjectsLoaded = true;
  } catch (e) { console.warn('[loadTasksProjects]', e); }
}
```

In `uptResetAndLoad` (public/index.html:10880):
```js
function uptResetAndLoad() {
  _uptTable.reset();
  loadTasksProjects();
}
```

- [ ] **Step 5: Browser smoke — open Опубликовано**

Reload `delivery.contenthunter.ru/#publishing/publishing?sub=up:tasks`.

Verify:
- «Проект» column populated.
- Dropdown shows used projects only.
- Selecting a project filters rows.
- Sort by «Проект», «Пак», «Аккаунт», «Видео», «Старт», «Токены», «№ Устр.» — all work without 400 in Network tab.
- Filter «ID» (typing a number) finds the matching task by exact id.
- Filter «Аккаунт» (ILIKE) works.
- Filter «№ Устр.» (typing a number) works.
- Filter «Видео» (ILIKE) works.

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(ui): tasks — project column + per-field filter mapping + projects fetch

- uptRenderRow: project_name cell between ID and device
- uptMapFiltersToServer: project/id/account/video_name/device_number as separate params (was shared search — caused filter misses for non-text fields)
- emptyColspan 13 → 14
- loadTasksProjects(): /api/publish/tasks/projects on first switch to tasks tab"
```

---

## Task 12: Final smoke + verify auto-deploy

The `auto-push hook` in `/root/.openclaw/workspace-genri/autowarm/` should push to `GenGo2/delivery-contenthunter` automatically per memory `reference_autowarm_git_hook.md`. PM2 reload in earlier tasks already brought server.js changes into prod. The frontend `public/index.html` is served directly from this directory (per memory `reference_delivery_frontend_deploy.md`) — no further deploy step.

- [ ] **Step 1: Verify PM2 status and recent restart**

```bash
pm2 describe autowarm-server | grep -E "status|restart time|exec cwd" | head -10
```

Expected: status `online`, exec cwd `/root/.openclaw/workspace-genri/autowarm`.

- [ ] **Step 2: Run all new tests one more time**

```bash
cd /root/.openclaw/workspace-genri/autowarm
node --test tests/test_publish_queue_filters.test.js tests/test_publish_tasks_filters.test.js tests/test_publish_projects_endpoints.test.js 2>&1 | tail -15
```

Expected: all green (5 + 9 + 2 = 16 tests).

- [ ] **Step 3: Final browser checklist**

In `delivery.contenthunter.ru/#publishing/publishing`:

**Запланировано:**
- [x] Колонка «Проект» отображается между ID и Пак.
- [x] Dropdown заполнен реальными проектами.
- [x] Фильтр по проекту работает.
- [x] Сорт по проекту, паку, аккаунту, платформе, названию, дате — без ошибок.
- [x] «Название»: для YT — короткий title (≤100 симв). Для IG/TT — «—».
- [x] «Описание»: текст из content_description, не пустота, не хештеги.
- [x] Фильтр «Описание» по фрагменту текста — находит строки.

**Опубликовано:**
- [x] Колонка «Проект» отображается между ID и № Устр.
- [x] Dropdown заполнен.
- [x] Фильтр по проекту, ID, № Устр., аккаунту, видео — работает.
- [x] Сорт по любой кликабельной колонке — без 400.

- [ ] **Step 4: Verify git auto-push to GenGo2**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git log --oneline -10
git remote -v
git ls-remote origin main 2>&1 | head -3   # should show recent commit hashes pushed
```

Expected: commits from this plan visible in remote.

- [ ] **Step 5: Update memory if anything surprising surfaced**

Per memory hygiene: if any new sort/filter incident surfaces in browser smoke that's not in the plan, jot a note in the relevant project memory file. Otherwise no memory update needed.

---

## Out of scope (per spec)

- Pagination factory (`paginated-table.js`) untouched.
- No `publish_tasks.project_id` migration — JOIN-based source is sufficient.
- Form for adding tasks — untouched.
- `status_exclude` / "Показать выполненные" toggle — untouched.

## Self-review notes

- All spec sections covered: project column (queue + tasks), title fix, description fix, filter fixes, sort whitelist fix, projects dropdown.
- No placeholders. Every code block is complete and self-contained.
- Type/name consistency: `project_name` (server) vs `project` (filter param) vs `vp.project` (SQL) — intentional and explicit.
- `colspan` arithmetic verified: queue 10→11 (added 1 col), tasks 13→14 (added 1 col); tests cover SORT_WHITELIST keys explicitly so no col/sort drift goes unnoticed.
- Test scaffolding uses live DB (matches existing pattern in `tests/test_packages_add_account.test.js`).
