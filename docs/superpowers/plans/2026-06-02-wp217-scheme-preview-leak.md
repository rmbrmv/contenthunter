# WP#217 — Барьер scheme_preview в автовыкладке: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Не давать служебным прогонам уникализатора (`task_type='scheme_preview'`, отбор схем) уезжать в автовыкладку; зачистить уже утёкшие pending-строки.

**Architecture:** Allowlist `task_type='unic'` в авто-мосте `unic_results → publish_queue` в двух точках (кандидатный отбор + чокпоинт диспатча), оба под kill-switch; плюс одноразовый идемпотентный cleanup-скрипт. Валидатор/воркер не трогаем — генерация превью и их чтение в валидаторе остаются как есть.

**Tech Stack:** Node.js, `pg` (Postgres `openclaw` на localhost:5432), тест-раннер `node --test --test-force-exit`. Спека: `docs/superpowers/specs/2026-06-02-wp217-scheme-preview-leak-design.md`.

---

## Подготовка (один раз перед Task 1)

Весь код — в репозитории **delivery-contenthunter** (autowarm), НЕ в contenthunter (там только спека/план). Создать изолированный worktree autowarm off `origin/main`:

```bash
# исходный прод-каталог autowarm (claude-user, без sudo)
cd /root/.openclaw/workspace-genri/autowarm 2>/dev/null || cd /home/claude-user/autowarm-testbench
git fetch origin --quiet
git worktree add -b wp217-scheme-preview-leak /home/claude-user/work-trees/wp217-autowarm origin/main
cd /home/claude-user/work-trees/wp217-autowarm
git branch --show-current   # → wp217-scheme-preview-leak
```

Все пути файлов ниже — относительно `/home/claude-user/work-trees/wp217-autowarm`.

**Контекст для исполнителя (нулевой контекст по кодбазе):**
- `assign_candidates.js` — чистые helper'ы кандидатного отбора авто-выкладки (`selectAssignCandidates`); идиома репо — pure-предикаты + kill-switch (см. `assignCandidateDedupClause`/`requeueMovedEnabled`).
- `server.js::checkDispatchQueueSlotLineage` — единый чокпоинт диспатча `publish_queue` (экспортируется для тестов на стр. ~9082).
- Колонка `unic_tasks.task_type` — `NOT NULL DEFAULT 'unic'`; нормальные задачи = `'unic'`, превью отбора схем = `'scheme_preview'`.
- Тест-конвенция: DB-free тесты в `tests/*.test.js`; LIVE-DB тесты — в корне репо как `test_*_live.test.js` (явный запуск), `pg.Pool` на `localhost/openclaw/openclaw123/openclaw`, изолированные высокие id.

---

## File Structure

- **Modify** `assign_candidates.js` — добавить kill-switch `publishableTaskTypeGuardEnabled()` + pure-предикат `publishableTaskTypeClause()`, вшить в `selectAssignCandidates`, дополнить exports. (Task 1)
- **Create** `tests/test_assign_publishable_type.test.js` — DB-free unit-тесты предиката и kill-switch. (Task 1)
- **Create** `test_assign_publishable_type_live.test.js` — LIVE-DB: превью исключается, `unic` проходит, kill-switch off → старое поведение. (Task 1)
- **Modify** `server.js::checkDispatchQueueSlotLineage` — добавить `ut.task_type` в SELECT + зеркальную отмену не-`unic` строк под `DISPATCH_TASK_TYPE_RECHECK_ENABLED`. (Task 2)
- **Create** `test_dispatch_task_type_guard.test.js` — LIVE-DB по образцу `test_dispatch_manual_guard.test.js`. (Task 2)
- **Create** `cleanup_wp217_scheme_preview_leak.js` — одноразовая зачистка pending превью-строк (dry-run/`--apply`). (Task 3)
- **Create** `test_cleanup_wp217_live.test.js` — LIVE-DB на cleanup. (Task 3)
- **Create** `test_manual_queue_preview_safe_live.test.js` — защитный регресс: превью не попадают в ручную очередь. (Task 4)

---

## Task 1: Allowlist `task_type='unic'` в кандидатном отборе (A)

**Files:**
- Modify: `assign_candidates.js`
- Test: `tests/test_assign_publishable_type.test.js` (DB-free)
- Test: `test_assign_publishable_type_live.test.js` (LIVE-DB, корень репо)

- [ ] **Step 1: Написать падающий DB-free unit-тест предиката + kill-switch**

Create `tests/test_assign_publishable_type.test.js`:

```javascript
'use strict';
// Run: node --test --test-force-exit tests/test_assign_publishable_type.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { publishableTaskTypeClause, publishableTaskTypeGuardEnabled } = require('../assign_candidates');

describe('publishableTaskTypeClause — WP#217', () => {
  test('flag ON: фильтрует по task_type=unic', () => {
    assert.equal(publishableTaskTypeClause(true), "ut.task_type = 'unic'");
  });
  test('flag OFF: предикат-ноль TRUE (старое поведение)', () => {
    assert.equal(publishableTaskTypeClause(false), 'TRUE');
  });
});

describe('publishableTaskTypeGuardEnabled — WP#217 kill-switch', () => {
  const KEY = 'ASSIGN_PUBLISHABLE_TASK_TYPE_GUARD_ENABLED';
  const orig = process.env[KEY];
  const restore = () => { if (orig === undefined) delete process.env[KEY]; else process.env[KEY] = orig; };

  test('env unset → ON (default)', () => {
    delete process.env[KEY];
    try { assert.equal(publishableTaskTypeGuardEnabled(), true); } finally { restore(); }
  });
  test("env 'false' → OFF", () => {
    process.env[KEY] = 'false';
    try { assert.equal(publishableTaskTypeGuardEnabled(), false); } finally { restore(); }
  });
  test("env 'true' → ON", () => {
    process.env[KEY] = 'true';
    try { assert.equal(publishableTaskTypeGuardEnabled(), true); } finally { restore(); }
  });
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_assign_publishable_type.test.js`
Expected: FAIL — `publishableTaskTypeClause is not a function` (ещё не экспортировано).

- [ ] **Step 3: Реализовать helper'ы в `assign_candidates.js`**

В `assign_candidates.js` после функции `requeueMovedEnabled()` (≈стр. 13) добавить:

```javascript
// WP#217 kill-switch: ASSIGN_PUBLISHABLE_TASK_TYPE_GUARD_ENABLED=false → не фильтровать
// по task_type (прод-поведение до WP#217) без передеплоя. Default ON.
function publishableTaskTypeGuardEnabled() {
  return process.env.ASSIGN_PUBLISHABLE_TASK_TYPE_GUARD_ENABLED !== 'false';
}

// WP#217 publishable-allowlist. Публикуется ТОЛЬКО task_type='unic'. Служебные прогоны
// уникализатора (scheme_preview — отбор схем) пишут результаты в unic_results, но НЕ
// должны уезжать в автовыкладку. fail-closed: любой будущий служебный тип тоже не утечёт.
// При выключенном гарде → 'TRUE' (предикат-ноль = прежнее поведение).
function publishableTaskTypeClause(enabled = publishableTaskTypeGuardEnabled()) {
  return enabled ? `ut.task_type = 'unic'` : 'TRUE';
}
```

- [ ] **Step 4: Вшить предикат в `selectAssignCandidates` и дополнить exports**

В `assign_candidates.js`:

(а) Сигнатуру `selectAssignCandidates` расширить опцией `publishableGuard`:

```javascript
async function selectAssignCandidates(db, { requeueMoved = requeueMovedEnabled(), publishableGuard = publishableTaskTypeGuardEnabled() } = {}) {
```

(б) В `WHERE` SELECT'а, сразу после строки `AND ${activeProjectSql('vpa')}`, добавить:

```javascript
      AND ${publishableTaskTypeClause(publishableGuard)}
```

(в) В `module.exports` (последняя строка файла) добавить новые имена:

```javascript
module.exports = { requeueMovedEnabled, assignCandidateDedupClause, selectAssignCandidates,
  publishableTaskTypeGuardEnabled, publishableTaskTypeClause };
```

- [ ] **Step 5: Запустить DB-free тест — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_assign_publishable_type.test.js`
Expected: PASS (5 тестов).

- [ ] **Step 6: Написать падающий LIVE-DB тест**

Create `test_assign_publishable_type_live.test.js` (корень репо):

```javascript
'use strict';
// Run: node --test --test-force-exit test_assign_publishable_type_live.test.js
// LIVE-DB (real Postgres). В корне репо — чтобы tests/*.test.js оставался DB-free.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { selectAssignCandidates } = require('./assign_candidates');
const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

// Изолированный диапазон id (9921700+), чтобы не задеть прод-строки.
const PID = 9921700;
const TASK_UNIC = 9921701, TASK_PREVIEW = 9921702;
const RES_UNIC = 9921701, RES_PREVIEW = 9921702;

async function cleanup() {
  await pool.query('DELETE FROM publish_queue WHERE unic_result_id = ANY($1)', [[RES_UNIC, RES_PREVIEW]]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id = ANY($1)', [[RES_UNIC, RES_PREVIEW]]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id = ANY($1)', [[TASK_UNIC, TASK_PREVIEW]]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1', [PID]).catch(()=>{});
}

before(async () => {
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active) VALUES ($1,'WP217','wp217',true)`, [PID]);
  // обычная публикуемая задача (task_type DEFAULT 'unic')
  await pool.query(`INSERT INTO unic_tasks (id, project_id, current_status, meta) VALUES ($1,$2,'done','{}'::jsonb)`, [TASK_UNIC, PID]);
  // превью отбора схем
  await pool.query(`INSERT INTO unic_tasks (id, project_id, current_status, task_type, meta)
                    VALUES ($1,$2,'done','scheme_preview','{}'::jsonb)`, [TASK_PREVIEW, PID]);
  for (const [rid, tid] of [[RES_UNIC, TASK_UNIC], [RES_PREVIEW, TASK_PREVIEW]]) {
    await pool.query(`INSERT INTO unic_results (id, task_id, scheme_id, output_url, status, created_at)
                      VALUES ($1,$2,NULL,'https://x/wp217.mp4','done', now())`, [rid, tid]);
  }
});
after(async () => { await cleanup(); await pool.end(); });

test('guard ON: scheme_preview исключён, unic — попадает', async () => {
  const rows = await selectAssignCandidates(pool, { publishableGuard: true });
  const ids = rows.map(r => r.result_id);
  assert.ok(ids.includes(RES_UNIC), 'обычный unic-результат должен быть кандидатом');
  assert.ok(!ids.includes(RES_PREVIEW), 'scheme_preview НЕ должен быть кандидатом');
});

test('guard OFF (kill-switch): scheme_preview снова в кандидатах', async () => {
  const rows = await selectAssignCandidates(pool, { publishableGuard: false });
  const ids = rows.map(r => r.result_id);
  assert.ok(ids.includes(RES_PREVIEW), 'при выключенном гарде превью возвращается (старое поведение)');
});
```

- [ ] **Step 7: Запустить LIVE-тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_assign_publishable_type_live.test.js`
Expected: PASS (2 теста). Если падает с ошибкой подключения — проверить, что Postgres `openclaw` поднят на localhost:5432.

- [ ] **Step 8: Коммит**

```bash
git add assign_candidates.js tests/test_assign_publishable_type.test.js test_assign_publishable_type_live.test.js
git commit -m "fix(wp217): allowlist task_type=unic в assign-кандидатах (kill-switch)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Зеркальная отмена не-`unic` строк на диспатче (B)

**Files:**
- Modify: `server.js::checkDispatchQueueSlotLineage` (≈стр. 6328-6352)
- Test: `test_dispatch_task_type_guard.test.js` (LIVE-DB, корень репо)

- [ ] **Step 1: Написать падающий LIVE-тест (образец — `test_dispatch_manual_guard.test.js`)**

Create `test_dispatch_task_type_guard.test.js`:

```javascript
'use strict';
// Run: node --test --test-force-exit test_dispatch_task_type_guard.test.js
// NOTE: импорт ./server поднимает setInterval-циклы и HTTP listener → ТОЛЬКО с --test-force-exit.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });
const { checkDispatchQueueSlotLineage } = require('./server');

const PID = 9921720, TASK = 9921720, RESULT = 9921720, PQ = 9921720;

async function cleanup() {
  await pool.query('DELETE FROM publish_queue WHERE id=$1', [PQ]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1', [RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1', [TASK]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1', [PID]).catch(()=>{});
}

async function setupPreviewQueueRow() {
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active) VALUES ($1,'WP217D','wp217d',true)`, [PID]);
  // превью-задача: task_type='scheme_preview', без slot_id (как в проде)
  await pool.query(`INSERT INTO unic_tasks (id, project_id, current_status, task_type, meta)
                    VALUES ($1,$2,'done','scheme_preview','{}'::jsonb)`, [TASK, PID]);
  await pool.query(`INSERT INTO unic_results (id, task_id, scheme_id, output_url, status, created_at)
                    VALUES ($1,$2,NULL,'https://x/wp217d.mp4','done', now())`, [RESULT, TASK]);
  await pool.query(`INSERT INTO publish_queue
                    (id, unic_result_id, unic_task_id, project_id, account_username, platform,
                     device_serial, media_url, scheduled_at, status)
                    VALUES ($1,$2,$3,$4,'wp217acc','youtube','WP217SER','https://x/wp217d.mp4', NOW(), 'pending')`,
                   [PQ, RESULT, TASK, PID]);
}

before(async () => { await setupPreviewQueueRow(); });
after(async () => { await cleanup(); await pool.end(); });

test('checkDispatchQueueSlotLineage: scheme_preview → cancelled/non_publishable_task_type', async () => {
  delete process.env.DISPATCH_TASK_TYPE_RECHECK_ENABLED;
  await setupPreviewQueueRow();
  const client = await pool.connect();
  let result;
  try { result = await checkDispatchQueueSlotLineage({ client, publishQueueId: PQ, unicResultId: RESULT }); }
  finally { client.release(); }
  assert.equal(result.skipped, true);
  assert.equal(result.skip_reason, 'non_publishable_task_type');
  const { rows } = await pool.query('SELECT status, skip_reason FROM publish_queue WHERE id=$1', [PQ]);
  assert.equal(rows[0].status, 'cancelled');
  assert.equal(rows[0].skip_reason, 'non_publishable_task_type');
});

test('checkDispatchQueueSlotLineage: kill-switch off → НЕ отменяет превью', async () => {
  process.env.DISPATCH_TASK_TYPE_RECHECK_ENABLED = 'false';
  await setupPreviewQueueRow();
  const client = await pool.connect();
  let result;
  try { result = await checkDispatchQueueSlotLineage({ client, publishQueueId: PQ, unicResultId: RESULT }); }
  finally { client.release(); }
  assert.notEqual(result.skip_reason, 'non_publishable_task_type');
  delete process.env.DISPATCH_TASK_TYPE_RECHECK_ENABLED;
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test --test-force-exit test_dispatch_task_type_guard.test.js`
Expected: FAIL — первый тест: `skip_reason` будет `undefined`/`legacy` (превью без slot_id уходит в legacy-ветку и НЕ отменяется), строка останется `pending`/`running`.

- [ ] **Step 3: Добавить `ut.task_type` в SELECT и проверку в `checkDispatchQueueSlotLineage`**

В `server.js`, внутри `checkDispatchQueueSlotLineage`, заменить блок SELECT+parse (текущие ≈стр. 6332-6342) на:

```javascript
    // Look up lineage from unic_task via unic_result
    const utRes = await client.query(`
      SELECT ut.meta, ut.content_id, ut.slot_date, ut.task_type
      FROM unic_tasks ut
      JOIN unic_results ur ON ur.task_id = ut.id
      WHERE ur.id = $1
      LIMIT 1
    `, [unicResultId]);

    const taskType = utRes.rows[0]?.task_type;
    const slotId = parseInt(utRes.rows[0]?.meta?.slot_id);
    const contentId = utRes.rows[0]?.content_id;
    const slotDate = utRes.rows[0]?.slot_date;

    // WP#217: публикуется только task_type='unic'. Служебные прогоны уникализатора
    // (scheme_preview — отбор схем) могли попасть в очередь до раскатки allowlist'а
    // в assign_candidates.js — отменяем на единственном чокпоинте диспатча.
    // Kill-switch DISPATCH_TASK_TYPE_RECHECK_ENABLED=false → откат без передеплоя.
    if (process.env.DISPATCH_TASK_TYPE_RECHECK_ENABLED !== 'false'
        && taskType && taskType !== 'unic') {
      await client.query(`
        UPDATE publish_queue
        SET status = 'cancelled', skip_reason = 'non_publishable_task_type', updated_at = now()
        WHERE id = $1 AND status = 'pending'
      `, [publishQueueId]);
      console.log(JSON.stringify({
        tag: 'dispatch-queue', skipped: true, reason: 'non_publishable_task_type',
        publish_queue_id: publishQueueId, unic_result_id: unicResultId, task_type: taskType,
      }));
      await client.query('COMMIT');
      return { skipped: true, skip_reason: 'non_publishable_task_type' };
    }
```

(Остальной код функции — legacy-ветка `if (!slotId || !contentId)`, advisory-lock, WP125-рекчек, lineage-check, claim — НЕ меняется.)

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_dispatch_task_type_guard.test.js`
Expected: PASS (2 теста).

- [ ] **Step 5: Прогнать существующий dispatch-guard тест — нет регрессии**

Run: `node --test --test-force-exit test_dispatch_manual_guard.test.js`
Expected: PASS (все тесты WP#125 зелёные — добавление поля `ut.task_type` в SELECT и ветки выше не задевает manual-recheck, у тех фикстур `task_type` дефолтный `'unic'`).

- [ ] **Step 6: Коммит**

```bash
git add server.js test_dispatch_task_type_guard.test.js
git commit -m "fix(wp217): диспатч отменяет не-unic строки (зеркало allowlist, kill-switch)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Одноразовый cleanup-скрипт утёкших pending-строк (C)

**Files:**
- Create: `cleanup_wp217_scheme_preview_leak.js`
- Test: `test_cleanup_wp217_live.test.js` (LIVE-DB, корень репо)

- [ ] **Step 1: Написать падающий LIVE-тест**

Create `test_cleanup_wp217_live.test.js`:

```javascript
'use strict';
// Run: node --test --test-force-exit test_cleanup_wp217_live.test.js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { cleanupSchemePreviewLeak } = require('./cleanup_wp217_scheme_preview_leak');
const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

const PID = 9921730;
const TASK_PREVIEW = 9921731, TASK_UNIC = 9921732;
const RES_PREVIEW = 9921731, RES_UNIC = 9921732;
const PQ_PREVIEW_PENDING = 9921731, PQ_PREVIEW_DONE = 9921733, PQ_UNIC_PENDING = 9921732;

async function cleanup() {
  await pool.query('DELETE FROM publish_queue WHERE id = ANY($1)', [[PQ_PREVIEW_PENDING, PQ_PREVIEW_DONE, PQ_UNIC_PENDING]]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id = ANY($1)', [[RES_PREVIEW, RES_UNIC]]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id = ANY($1)', [[TASK_PREVIEW, TASK_UNIC]]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1', [PID]).catch(()=>{});
}

async function seed() {
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active) VALUES ($1,'WP217C','wp217c',true)`, [PID]);
  await pool.query(`INSERT INTO unic_tasks (id, project_id, current_status, task_type, meta)
                    VALUES ($1,$2,'done','scheme_preview','{}'::jsonb)`, [TASK_PREVIEW, PID]);
  await pool.query(`INSERT INTO unic_tasks (id, project_id, current_status, meta)
                    VALUES ($1,$2,'done','{}'::jsonb)`, [TASK_UNIC, PID]);
  await pool.query(`INSERT INTO unic_results (id, task_id, status, output_url, created_at)
                    VALUES ($1,$2,'done','https://x/p.mp4',now()),($3,$4,'done','https://x/u.mp4',now())`,
                   [RES_PREVIEW, TASK_PREVIEW, RES_UNIC, TASK_UNIC]);
  const ins = (id, res, task, status) => pool.query(`INSERT INTO publish_queue
      (id, unic_result_id, unic_task_id, project_id, account_username, platform, media_url, scheduled_at, status)
      VALUES ($1,$2,$3,$4,'a','youtube','https://x/x.mp4',now(),$5)`, [id, res, task, PID, status]);
  await ins(PQ_PREVIEW_PENDING, RES_PREVIEW, TASK_PREVIEW, 'pending'); // должна отмениться
  await ins(PQ_PREVIEW_DONE,    RES_PREVIEW, TASK_PREVIEW, 'done');    // НЕ трогать (уже опубликована)
  await ins(PQ_UNIC_PENDING,    RES_UNIC,    TASK_UNIC,    'pending'); // НЕ трогать (обычный контент)
}

before(seed);
after(async () => { await cleanup(); await pool.end(); });

test('dry-run: считает кандидатов, ничего не меняет', async () => {
  const r = await cleanupSchemePreviewLeak(pool, { apply: false, onlyProjects: [PID] });
  assert.equal(r.candidates, 1, 'один pending превью-кандидат');
  assert.equal(r.cancelled, 0);
  const { rows } = await pool.query('SELECT status FROM publish_queue WHERE id=$1', [PQ_PREVIEW_PENDING]);
  assert.equal(rows[0].status, 'pending', 'dry-run не меняет статус');
});

test('apply: отменяет только pending превью, не трогает done/unic', async () => {
  const r = await cleanupSchemePreviewLeak(pool, { apply: true, onlyProjects: [PID] });
  assert.equal(r.cancelled, 1);
  const get = async id => (await pool.query('SELECT status, skip_reason FROM publish_queue WHERE id=$1', [id])).rows[0];
  assert.deepEqual(await get(PQ_PREVIEW_PENDING), { status: 'cancelled', skip_reason: 'scheme_preview_leak' });
  assert.equal((await get(PQ_PREVIEW_DONE)).status, 'done');
  assert.equal((await get(PQ_UNIC_PENDING)).status, 'pending');
});

test('идемпотентность: повторный apply находит 0', async () => {
  const r = await cleanupSchemePreviewLeak(pool, { apply: true, onlyProjects: [PID] });
  assert.equal(r.candidates, 0);
  assert.equal(r.cancelled, 0);
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test --test-force-exit test_cleanup_wp217_live.test.js`
Expected: FAIL — `Cannot find module './cleanup_wp217_scheme_preview_leak'`.

- [ ] **Step 3: Реализовать cleanup-скрипт (образец — `cleanup_wp216_inactive_project_queue.js`)**

Create `cleanup_wp217_scheme_preview_leak.js`:

```javascript
'use strict';
// WP#217 one-off: отменить pending-строки автовыкладки, утёкшие из служебных прогонов
// уникализатора (отбор схем, unic_tasks.task_type='scheme_preview'). Только status='pending'
// (done/failed/running/cancelled не трогаем). Идемпотентно (повтор находит 0).
// onlyProjects — тест-изоляция/точечный прогон; в проде без него — глобально.
// Использование:
//   node cleanup_wp217_scheme_preview_leak.js                      # dry-run (только счёт)
//   node cleanup_wp217_scheme_preview_leak.js --apply              # отменить
//   node cleanup_wp217_scheme_preview_leak.js --onlyProject=117 [--apply]
const { Pool } = require('pg');

function target(scoped) {
  return `
  FROM publish_queue pq
  JOIN unic_tasks ut ON ut.id = pq.unic_task_id
  WHERE pq.status = 'pending'
    AND ut.task_type = 'scheme_preview'
    ${scoped ? 'AND pq.project_id = ANY($1)' : ''}`;
}

async function cleanupSchemePreviewLeak(pool, { apply = false, onlyProjects = null } = {}) {
  const scoped = Array.isArray(onlyProjects) && onlyProjects.length > 0;
  const params = scoped ? [onlyProjects] : [];
  const candidates = (await pool.query(`SELECT count(*)::int AS n ${target(scoped)}`, params)).rows[0].n;
  if (!apply) {
    return { apply: false, scoped, candidates, cancelled: 0 };
  }
  const res = await pool.query(`
    UPDATE publish_queue pq
    SET status = 'cancelled', skip_reason = 'scheme_preview_leak', updated_at = now()
    WHERE pq.id IN (SELECT pq.id ${target(scoped)})`, params);
  return { apply: true, scoped, candidates, cancelled: res.rowCount };
}

module.exports = { cleanupSchemePreviewLeak };

if (require.main === module) {
  const apply = process.argv.includes('--apply');
  const only = process.argv.find(a => a.startsWith('--onlyProject='));
  let onlyProjects = null;
  if (only) {
    const id = parseInt(only.split('=')[1], 10);
    if (!Number.isFinite(id)) { console.error('[cleanup-wp217] --onlyProject требует число (project_id)'); process.exit(1); }
    onlyProjects = [id];
  }
  const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });
  cleanupSchemePreviewLeak(pool, { apply, onlyProjects })
    .then(r => { console.log('[cleanup-wp217]', JSON.stringify(r)); return pool.end(); })
    .catch(e => { console.error('[cleanup-wp217] error:', e.message); process.exit(1); });
}
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_cleanup_wp217_live.test.js`
Expected: PASS (3 теста).

- [ ] **Step 5: Коммит**

```bash
git add cleanup_wp217_scheme_preview_leak.js test_cleanup_wp217_live.test.js
git commit -m "chore(wp217): cleanup-скрипт отмены утёкших scheme_preview pending-строк

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Защитный регресс — превью не попадают в ручную очередь (D) + полный прогон

**Files:**
- Test: `test_manual_queue_preview_safe_live.test.js` (LIVE-DB, корень репо)

- [ ] **Step 1: Написать LIVE-тест ручной очереди**

`assignManualPublishQueue` делает `INNER JOIN validator_schedule_slots ON vss.id = (ut.meta->>'slot_id')::int`; у превью `slot_id` нет → JOIN их отбрасывает ДО резолва паков, поэтому минимальная фикстура (без паков/аккаунтов) корректна: на выходе ноль строк ручной очереди.

Create `test_manual_queue_preview_safe_live.test.js`:

```javascript
'use strict';
// Run: node --test --test-force-exit test_manual_queue_preview_safe_live.test.js
// WP#217 защитный регресс: scheme_preview-результаты не утекают в ручную очередь.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { assignManualPublishQueue } = require('./manual_queue_assign');
const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

const PID = 9921740, TASK_PREVIEW = 9921740, RES_PREVIEW = 9921740;
const silent = { log() {}, warn() {}, error() {} };

async function cleanup() {
  await pool.query('DELETE FROM validator_manual_publish_queue WHERE unic_result_id=$1', [RES_PREVIEW]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1', [RES_PREVIEW]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1', [TASK_PREVIEW]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1', [PID]).catch(()=>{});
}

before(async () => {
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish) VALUES ($1,'WP217M','wp217m',true,true)`, [PID]);
  // превью-задача без slot_id в meta (как в проде)
  await pool.query(`INSERT INTO unic_tasks (id, project_id, current_status, task_type, meta)
                    VALUES ($1,$2,'done','scheme_preview','{}'::jsonb)`, [TASK_PREVIEW, PID]);
  await pool.query(`INSERT INTO unic_results (id, task_id, status, output_url, created_at)
                    VALUES ($1,$2,'done','https://x/m.mp4',now())`, [RES_PREVIEW, TASK_PREVIEW]);
});
after(async () => { await cleanup(); await pool.end(); });

test('assignManualPublishQueue: scheme_preview не появляется в ручной очереди', async () => {
  await assignManualPublishQueue(pool, silent);
  const { rows } = await pool.query('SELECT count(*)::int AS n FROM validator_manual_publish_queue WHERE unic_result_id=$1', [RES_PREVIEW]);
  assert.equal(rows[0].n, 0, 'превью-результат не должен попадать в ручную очередь');
});
```

- [ ] **Step 2: Запустить — убедиться, что проходит сразу (код ручной очереди не менялся)**

Run: `node --test --test-force-exit test_manual_queue_preview_safe_live.test.js`
Expected: PASS (1 тест). Это документирующий регресс-тест: подтверждает структурную безопасность ручной очереди.

- [ ] **Step 3: Прогнать весь DB-free набор — нет регрессий**

Run: `npm test`
Expected: PASS (весь `tests/*.test.js`, включая новый `tests/test_assign_publishable_type.test.js`).

- [ ] **Step 4: Прогнать все новые LIVE-тесты вместе**

Run: `node --test --test-force-exit test_assign_publishable_type_live.test.js test_dispatch_task_type_guard.test.js test_cleanup_wp217_live.test.js test_manual_queue_preview_safe_live.test.js`
Expected: PASS (все).

- [ ] **Step 5: Коммит**

```bash
git add test_manual_queue_preview_safe_live.test.js
git commit -m "test(wp217): защитный регресс — превью не утекают в ручную очередь

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Завершение (после всех тасков)

1. **Code review** (`superpowers:requesting-code-review` / codex) → исправить P1/P2.
2. **Деплой:** PR в `delivery-contenthunter` main → merge → на проде `git pull` autowarm под `claude-user` → **`sudo pm2 restart` id35** (A и B живут в долгоживущем `server.js`).
3. **Зачистка:** на проде `node cleanup_wp217_scheme_preview_leak.js` (dry-run → проверить счёт ~75 → `--apply`).
4. **Kill-switch'и** в прод `.env` (default ON, добавлять не обязательно — гарды включены без записи).
5. **OpenProject WP#217:** комментарий с (а) корнем, (б) перечнем 9 опубликованных превью-URL/аккаунтов для операторского удаления, (в) числом отменённых pending; статус → «Тестирование».
6. **Verify** (через ~сутки): новые `scheme_preview`-прогоны не дают строк в `publish_queue`; счётчик `non_publishable_task_type` в логах диспатча; 0 новых утечек.

## Spec coverage (self-review)

- §3.A allowlist → Task 1. §3.B dispatch → Task 2. §3.C cleanup → Task 3.
- §5 edge-cases: kill-switch'и (Task 1/2 тесты), B только pending (Task 2 фикстура), ручная очередь (Task 4).
- §6 тесты: assign (Task 1), dispatch (Task 2), cleanup (Task 3), manual-queue (Task 4) — все покрыты.
- §7 деплой / §8 опубликованное → раздел «Завершение».
