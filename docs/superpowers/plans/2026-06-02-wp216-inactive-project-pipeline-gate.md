# WP#216 — Заморозка неактивных клиентов в пайплайне: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Не пускать клиентов с `validator_projects.active=false` ни в один этап пайплайна выкладки и разово вычистить уже протёкшие задачи.

**Architecture:** Единый модуль-предикат `project_active_filter.js` (по образцу `client_manual_filter.js`) подключается в 5 точках пайплайна (генератор уникализации, авто-диспатч, retry-handoff, наполнитель ручной очереди, выдача оператору). Общий kill-switch `INACTIVE_PROJECT_GATE_ENABLED` (default ON). Разовый идемпотентный скрипт очистки гасит существующие фантомы.

**Tech Stack:** Node.js (CommonJS), PostgreSQL (`openclaw` db, localhost:5432, user/pass `openclaw`/`openclaw123`), `node:test` + `node:assert/strict`, репозиторий `delivery-contenthunter` (рабочая копия `/home/claude-user/autowarm-testbench`).

**Рабочая директория для кода:** `/home/claude-user/autowarm-testbench` (origin `delivery-contenthunter`). Ветка: создать `wp216-inactive-project-gate` от `origin/main`.

**Контекст root-cause:** см. спеку `docs/superpowers/specs/2026-06-02-wp216-inactive-project-pipeline-gate-design.md` в репозитории `contenthunter`. Кратко: неактивный авто-клиент Септизим (id=83) утёк 29 строками в ручную очередь через retry-handoff упавшей авто-выкладки; `active` нигде в контент-пайплайне не проверяется.

**Тест-конвенция репо:** «contract-тест» — гонять SQL-фрагмент функции напрямую против фикстур (см. `test_client_manual_publish.test.js`), помечая `// Contract test — mirror of <func>. Keep in sync.`. Используем там, где функцию дорого вызывать целиком; поведенческий вызов — где дёшево.

---

## Подготовка ветки (выполнить один раз перед Task 1)

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin -q
git checkout -B wp216-inactive-project-gate origin/main
node --test test_client_manual_publish.test.js 2>&1 | tail -5   # baseline: убедиться, что live-БД доступна и тесты идут
```
Expected: тесты `test_client_manual_publish.test.js` проходят (live-БД доступна).

---

## Task 1: Модуль-предикат `project_active_filter.js`

**Files:**
- Create: `project_active_filter.js`
- Test: `test_project_active_filter.test.js`

- [ ] **Step 1: Написать падающий тест**

Create `test_project_active_filter.test.js`:

```js
'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { projectGateEnabled, activeProjectSql, projectIsActive } =
  require('./project_active_filter');

const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

const P_ACTIVE = 99216001;
const P_INACTIVE = 99216002;

before(async () => {
  await pool.query(`DELETE FROM validator_projects WHERE id IN ($1,$2)`, [P_ACTIVE, P_INACTIVE]);
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,'WP216Active','wp216act',true,false)`, [P_ACTIVE]);
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,'WP216Inactive','wp216ina',false,false)`, [P_INACTIVE]);
});
after(async () => {
  await pool.query(`DELETE FROM validator_projects WHERE id IN ($1,$2)`, [P_ACTIVE, P_INACTIVE]);
  await pool.end();
});

test('projectGateEnabled: default ON, off only on "false"', () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  assert.equal(projectGateEnabled(), true);
  process.env.INACTIVE_PROJECT_GATE_ENABLED = 'false';
  assert.equal(projectGateEnabled(), false);
  process.env.INACTIVE_PROJECT_GATE_ENABLED = 'true';
  assert.equal(projectGateEnabled(), true);
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
});

test('activeProjectSql: predicate when ON, no-op TRUE when OFF', () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  assert.equal(activeProjectSql('vp'), '(vp.active = true)');
  process.env.INACTIVE_PROJECT_GATE_ENABLED = 'false';
  assert.equal(activeProjectSql('vp'), 'TRUE');
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
});

test('projectIsActive: true for active, false for inactive', async () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  assert.equal(await projectIsActive(pool, P_ACTIVE), true);
  assert.equal(await projectIsActive(pool, P_INACTIVE), false);
});

test('projectIsActive: fail-closed on missing/null project_id', async () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  assert.equal(await projectIsActive(pool, 999999999), false);
  assert.equal(await projectIsActive(pool, null), false);
});

test('projectIsActive: gate OFF → always true (even inactive/null)', async () => {
  process.env.INACTIVE_PROJECT_GATE_ENABLED = 'false';
  assert.equal(await projectIsActive(pool, P_INACTIVE), true);
  assert.equal(await projectIsActive(pool, null), true);
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_project_active_filter.test.js`
Expected: FAIL — `Cannot find module './project_active_filter'`.

- [ ] **Step 3: Реализовать модуль**

Create `project_active_filter.js`:

```js
'use strict';
// WP#216: гейт неактивных клиентов (validator_projects.active=false) во всём
// пайплайне выкладки. Единый источник правды предиката, как client_manual_filter.js.
// Kill-switch INACTIVE_PROJECT_GATE_ENABLED=false → до-WP#216 поведение без редеплоя.

function projectGateEnabled() {
  return process.env.INACTIVE_PROJECT_GATE_ENABLED !== 'false';
}

// SQL-фрагмент. projAlias — алиас validator_projects ((LEFT) JOIN у caller'а).
// Гейт выключен → 'TRUE' (no-op; LEFT JOIN можно не трогать).
function activeProjectSql(projAlias) {
  return projectGateEnabled() ? `(${projAlias}.active = true)` : 'TRUE';
}

// Точечная проверка для не-SQL путей (retry-handoff). db = pg Pool|client.
// Гейт выключен → всегда true. project_id NULL/не найден → false (fail-closed).
async function projectIsActive(db, projectId) {
  if (!projectGateEnabled()) return true;
  if (!projectId) return false;
  const { rows } = await db.query(
    'SELECT active FROM validator_projects WHERE id = $1', [projectId]);
  return rows.length > 0 && rows[0].active === true;
}

module.exports = { projectGateEnabled, activeProjectSql, projectIsActive };
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_project_active_filter.test.js`
Expected: PASS (5 тестов).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add project_active_filter.js test_project_active_filter.test.js
git commit -m "feat(wp216): project_active_filter — общий предикат active + kill-switch"
```

---

## Task 2: Общие фикстуры + гейт в генераторе уникализации (`run_auto_unic.js`)

**Files:**
- Create: `test_wp216_inactive_gate.test.js` (фикстуры + первый contract-тест; пополняется в Task 3–6)
- Modify: `run_auto_unic.js`

Фикстуры (создаются здесь, переиспользуются в Task 3–6). Три проекта: активный авто, неактивный авто, неактивный ручной; у каждого content (approved/passed) + filled-слот + unic_task(done) + unic_result(ready).

- [ ] **Step 1: Написать падающий contract-тест + фикстуры**

Create `test_wp216_inactive_gate.test.js`:

```js
'use strict';
// WP#216 integration: гейт неактивных проектов в 5 точках пайплайна.
// Contract-тесты гоняют SQL-фрагмент функции напрямую (mirror — keep in sync).
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { activeProjectSql } = require('./project_active_filter');

const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

// --- ID-пространство WP216 (9921 6xxx) ---
const ACT = 99216001, INA = 99216002, INM = 99216003;           // projects: active-auto, inactive-auto, inactive-manual
const C = { [ACT]: 99216101, [INA]: 99216102, [INM]: 99216103 }; // content
const S = { [ACT]: 99216201, [INA]: 99216202, [INM]: 99216203 }; // slot
const T = { [ACT]: 99216301, [INA]: 99216302, [INM]: 99216303 }; // unic_task
const R = { [ACT]: 99216401, [INA]: 99216402, [INM]: 99216403 }; // unic_result
const MQ = { [ACT]: 99216501, [INA]: 99216502 };                 // manual_publish_queue rows
const PQ = { [ACT]: 99216601, [INA]: 99216602 };                 // publish_queue rows (retry)
const CPID = { [ACT]: '99216001-0000-0000-0000-000000000001',
               [INA]: '99216002-0000-0000-0000-000000000002' };  // client_publish_id (retry)

async function cleanup() {
  const projs = [ACT, INA, INM];
  await pool.query(`DELETE FROM publish_tasks WHERE client_publish_id IN ($1,$2)`,
                   [CPID[ACT], CPID[INA]]);
  await pool.query(`DELETE FROM publish_queue WHERE project_id = ANY($1)`, [projs]);
  await pool.query(`DELETE FROM validator_manual_publish_queue WHERE project_id = ANY($1)`, [projs]);
  await pool.query(`DELETE FROM unic_results WHERE id = ANY($1)`, [Object.values(R)]);
  await pool.query(`DELETE FROM unic_tasks WHERE id = ANY($1)`, [Object.values(T)]);
  await pool.query(`DELETE FROM validator_schedule_slots WHERE id = ANY($1)`, [Object.values(S)]);
  await pool.query(`DELETE FROM validator_content WHERE id = ANY($1)`, [Object.values(C)]);
  await pool.query(`DELETE FROM validator_projects WHERE id = ANY($1)`, [projs]);
}

async function seedProject(pid, { active, manual }) {
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,$2,$3,$4,$5)`,
                   [pid, `WP216_${pid}`, `wp216_${pid}`, active, manual]);
  await pool.query(`INSERT INTO validator_content (id, project_id, description, status, content_type, uploader_id, moderation_status, s3_url)
                    VALUES ($1,$2,'WP216 длинное описание контента для уникализации','approved','video',1,'passed','https://x/in.mp4')`,
                   [C[pid], pid]);
  await pool.query(`INSERT INTO validator_schedule_slots
                    (id, project_id, slot_date, slot_position, content_id, slot_type, status, manual_publish)
                    VALUES ($1,$2, CURRENT_DATE, 1, $3, 'client', 'filled', $4)`,
                   [S[pid], pid, C[pid], manual]);
  await pool.query(`INSERT INTO unic_tasks (id, content_id, project_id, project_name, slot_date, current_status, meta)
                    VALUES ($1,$2,$3,$4, CURRENT_DATE, 'done', jsonb_build_object('slot_id', $5::text))`,
                   [T[pid], C[pid], pid, `WP216_${pid}`, S[pid]]);
  await pool.query(`INSERT INTO unic_results (id, task_id, scheme_id, output_url, status, created_at)
                    VALUES ($1,$2, NULL, 'https://x/out.mp4', 'ready', now())`, [R[pid], T[pid]]);
}

async function setup() {
  await cleanup();
  await seedProject(ACT, { active: true,  manual: false });
  await seedProject(INA, { active: false, manual: false });
  await seedProject(INM, { active: false, manual: true });
  // Manual-queue строки (для listQueue, Task 6): по одной для активного и неактивного авто.
  for (const pid of [ACT, INA]) {
    await pool.query(`INSERT INTO validator_manual_publish_queue
        (id, slot_id, content_id, unic_result_id, unic_task_id, project_id, project_name,
         account_username, platform, planned_date, operator_status)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'wp216user','instagram', CURRENT_DATE, 'queued')`,
       [MQ[pid], S[pid], C[pid], R[pid], T[pid], pid, `WP216_${pid}`]);
  }
  // Failed publish_queue + publish_tasks (для retry, Task 4): окно ретраев исчерпано (5 дней).
  for (const pid of [ACT, INA]) {
    await pool.query(`INSERT INTO publish_queue
        (id, unic_result_id, unic_task_id, project_id, client_publish_id, status,
         manual_handoff_at, account_username, platform, pack_name, device_serial)
        VALUES ($1,$2,$3,$4,$5,'failed', NULL, 'wp216user','instagram','wp216pack','WP216DEV')`,
       [PQ[pid], R[pid], T[pid], pid, CPID[pid]]);
    await pool.query(`INSERT INTO publish_tasks
        (client_publish_id, status, error_code, error_class, created_at, updated_at)
        VALUES ($1,'failed','wp216_code','ui_changed', now() - interval '5 days', now() - interval '5 days')`,
       [CPID[pid]]);
  }
}

before(async () => { await setup(); });
after(async () => { await cleanup(); await pool.end(); });

// Contract test — mirror of run_auto_unic.js slot SELECT. Keep in sync.
test('run_auto_unic: неактивный проект НЕ попадает в выборку слотов; активный — попадает', async () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  const q = (pid) => pool.query(`
    SELECT s.id
    FROM validator_schedule_slots s
    JOIN validator_content c ON c.id = s.content_id
    JOIN validator_projects vp ON vp.id = c.project_id
    WHERE s.id = $1
      AND s.status = 'filled'
      AND c.status = 'approved'
      AND c.moderation_status = 'passed'
      AND ${activeProjectSql('vp')}
  `, [S[pid]]);
  assert.equal((await q(INA)).rows.length, 0, 'inactive project slot must be excluded');
  assert.equal((await q(ACT)).rows.length, 1, 'active project slot must be included');
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: PASS на самом contract-тесте НЕ гарантирован до правки `run_auto_unic.js` — этот тест проверяет фрагмент и пройдёт сразу. Реальная цель шага — убедиться, что **фикстуры корректно заводятся** (нет ошибок вставки). Если тест зелёный и без ошибок setup — фикстуры валидны.

> Примечание: contract-тест проверяет предикат, а не проводку. Проводку в `run_auto_unic.js` правим в Step 3 и держим «в синхроне» с тестом (как в `test_client_manual_publish.test.js`).

- [ ] **Step 3: Внести гейт в `run_auto_unic.js`**

В `run_auto_unic.js` добавить require сразу после `'use strict';` (строка 1):

```js
'use strict';
const { activeProjectSql } = require('./project_active_filter');
```

Заменить блок запроса слотов (текущие строки ~17-37) — добавить JOIN на проект и предикат:

```js
    const { rows: slots } = await pool.query(`
      SELECT
      s.id     AS slot_id,
      c.id     AS content_id,
      c.s3_url,
      c.project_id,
      c.title
      FROM validator_schedule_slots s
      JOIN validator_content c ON c.id = s.content_id
      JOIN validator_projects vp ON vp.id = c.project_id
      WHERE s.slot_date = $1
      AND s.status = 'filled'
      AND c.status = 'approved'
      AND c.moderation_status = 'passed'
      AND ${activeProjectSql('vp')}
      AND NOT EXISTS (
        SELECT 1 FROM unic_tasks ut
        WHERE ut.content_id = c.id
        AND ut.slot_date = $1
        AND ut.current_status IN ('pending','processing','done')
      )
    `, [slotDate]);
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js test_project_active_filter.test.js`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add test_wp216_inactive_gate.test.js run_auto_unic.js
git commit -m "feat(wp216): гейт active в run_auto_unic + общие фикстуры теста"
```

---

## Task 3: Гейт в авто-диспатче (`assign_candidates.js`)

**Files:**
- Modify: `assign_candidates.js`
- Test: `test_wp216_inactive_gate.test.js` (добавить test-блок)

Поведенческий тест: `selectAssignCandidates(pool)` не должен возвращать unic_result неактивного авто-проекта (слот не-ручной → иначе он был бы кандидатом), но должен возвращать активный.

- [ ] **Step 1: Добавить падающий тест в конец `test_wp216_inactive_gate.test.js`**

```js
test('assign_candidates: unic_result неактивного проекта НЕ кандидат; активного — кандидат', async () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  const { selectAssignCandidates } = require('./assign_candidates');
  const rows = await selectAssignCandidates(pool);
  const ids = new Set(rows.map(r => r.result_id));
  assert.equal(ids.has(R[INA]), false, 'inactive auto result must NOT be an assign candidate');
  assert.equal(ids.has(R[ACT]), true, 'active auto result must be an assign candidate');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: FAIL на новом тесте — `R[INA]` присутствует в кандидатах (гейта ещё нет).

- [ ] **Step 3: Внести гейт в `assign_candidates.js`**

Добавить require рядом с существующим `effectiveManualSql` (верх файла):

```js
const { activeProjectSql } = require('./project_active_filter');
```

В `selectAssignCandidates` (строки ~46-72) добавить JOIN на проект и предикат в WHERE. Заменить участок с `FROM unic_results ur ... WHERE ur.status IN ('ready','done')`:

```js
    FROM unic_results ur
    JOIN unic_tasks ut ON ut.id = ur.task_id
    JOIN validator_projects vpa ON vpa.id = ut.project_id
    LEFT JOIN validator_content vc ON vc.id = ut.content_id
    WHERE ur.status IN ('ready','done')
      AND ${activeProjectSql('vpa')}
      AND ${assignCandidateDedupClause(requeueMoved)}
      AND NOT EXISTS (
        SELECT 1 FROM validator_schedule_slots vss
        LEFT JOIN validator_projects p ON p.id = vss.project_id
        WHERE vss.id = (ut.meta->>'slot_id')::int
          AND ${effectiveManualSql('vss', 'p')}
      )
    ORDER BY ur.created_at ASC
    LIMIT 100
```

(JOIN `validator_projects vpa` на `ut.project_id` — не путать с `p` внутри NOT EXISTS, у которого другая семантика — исключение ручных слотов.)

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add assign_candidates.js test_wp216_inactive_gate.test.js
git commit -m "feat(wp216): гейт active в авто-диспатче selectAssignCandidates"
```

---

## Task 4: Гейт в retry-handoff (`retry_controller.js`)

**Files:**
- Modify: `retry_controller.js`
- Test: `test_wp216_inactive_gate.test.js` (добавить test-блок)

Поведенческий тест: `retryFailedPublishes(pool, {onlyClientPublishId})` для неактивного проекта НЕ сдаёт строку в ручную (`manual_handoff_at` остаётся NULL); для активного — сдаёт (`manual_handoff_at` проставлен).

- [ ] **Step 1: Добавить падающий тест в конец `test_wp216_inactive_gate.test.js`**

```js
test('retry-handoff: неактивный проект НЕ сдаётся в ручную; активный — сдаётся', async () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  const { retryFailedPublishes } = require('./retry_controller');

  // Неактивный: гейт должен пропустить (ни requeue, ни handoff).
  await retryFailedPublishes(pool, { onlyClientPublishId: CPID[INA] });
  const ina = await pool.query(
    `SELECT status, manual_handoff_at FROM publish_queue WHERE id=$1`, [PQ[INA]]);
  assert.equal(ina.rows[0].manual_handoff_at, null, 'inactive project must NOT be handed off');
  assert.equal(ina.rows[0].status, 'failed', 'inactive project row stays failed');

  // Активный контроль: окно исчерпано → handoff произошёл.
  await retryFailedPublishes(pool, { onlyClientPublishId: CPID[ACT] });
  const act = await pool.query(
    `SELECT manual_handoff_at FROM publish_queue WHERE id=$1`, [PQ[ACT]]);
  assert.ok(act.rows[0].manual_handoff_at !== null, 'active project must be handed off');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: FAIL на новом тесте — у неактивного `manual_handoff_at` проставлен (гейта ещё нет).

> Если тест случайно пройдёт из-за того, что решение `decideRetry` дало не `handoff`: проверь, что фикстура publish_tasks имеет `created_at` 5 дней назад и `error_class='ui_changed'` (окно `RETRY_WINDOW_DAYS`=2 исчерпано → `handoff`). Активный контроль в Step 1 это и подтверждает.

- [ ] **Step 3: Внести гейт в `retry_controller.js`**

Добавить require (верх файла, рядом с другими require):

```js
const { projectIsActive } = require('./project_active_filter');
```

В главном SELECT цикла (строки ~46-56) добавить `pq.project_id` в список колонок:

```js
    SELECT pq.id AS pq_id, pq.project_id, pq.client_publish_id, pq.unic_task_id,
           lt.id AS last_task_id, lt.error_code, lt.error_class, lt.last_failed_at,
           (pq.client_publish_id IS NULL) AS no_intent
    FROM publish_queue pq
```

В теле цикла `for (const r of rows)` сразу после строки `if (r.no_intent || !r.error_class) continue;` (строка ~58) добавить guard:

```js
    // WP#216: неактивный клиент заморожен — ни requeue, ни handoff. Строка остаётся
    // failed; разовая чистка добивает накопленное.
    if (!await projectIsActive(pool, r.project_id)) {
      continue;
    }
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: PASS.

> Активный handoff вставит строку в `validator_manual_publish_queue` для проекта ACT — она удаляется в `cleanup()` (DELETE по `project_id = ANY`), повторный прогон теста идемпотентен через `setup()`.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add retry_controller.js test_wp216_inactive_gate.test.js
git commit -m "feat(wp216): гейт active в retry-handoff (ни requeue, ни handoff неактивным)"
```

---

## Task 5: Гейт в наполнителе ручной очереди (`manual_queue_assign.js`)

**Files:**
- Modify: `manual_queue_assign.js`
- Test: `test_wp216_inactive_gate.test.js` (добавить test-блок)

Defense-in-depth. Contract-тест по образцу `manual_queue_assign` SELECT: неактивный РУЧНОЙ проект (INM) не должен быть кандидатом наполнителя, хотя его слот ручной.

- [ ] **Step 1: Добавить падающий contract-тест**

```js
// Contract test — mirror of manual_queue_assign.js assignManualPublishQueue SELECT. Keep in sync.
test('наполнитель: неактивный РУЧНОЙ проект НЕ кандидат ручной очереди', async () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  const { effectiveManualSql } = require('./client_manual_filter');
  // INM: active=false, manual_publish=true, slot manual_publish=true → без гейта был бы кандидат.
  const q = (pid) => pool.query(`
    SELECT ur.id
    FROM unic_results ur
    JOIN unic_tasks ut ON ut.id = ur.task_id
    JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
    LEFT JOIN validator_projects p ON p.id = vss.project_id
    WHERE ur.id = $1
      AND ur.status IN ('ready','done')
      AND ${effectiveManualSql('vss', 'p')}
      AND ${activeProjectSql('p')}
  `, [R[pid]]);
  assert.equal((await q(INM)).rows.length, 0, 'inactive manual project must NOT be a populator candidate');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: контракт-тест проверяет фрагмент с уже включённым `activeProjectSql` → пройдёт сразу. Цель шага — зафиксировать ожидаемый предикат; проводку правим в Step 3 и держим в синхроне.

> Это «keep in sync» contract-тест (как существующие в `test_client_manual_publish.test.js`): он валидирует предикат, а Step 3 вшивает его в функцию.

- [ ] **Step 3: Внести гейт в `manual_queue_assign.js`**

Добавить require рядом с существующим `effectiveManualSql` (строка 3):

```js
const { effectiveManualSql } = require('./client_manual_filter');
const { activeProjectSql } = require('./project_active_filter');
```

В `assignManualPublishQueue` основной SELECT (строки ~82-100) добавить предикат сразу после `AND ${effectiveManualSql('vss', 'p')}`:

```js
      WHERE ur.status IN ('ready','done')
        AND ${effectiveManualSql('vss', 'p')}
        AND ${activeProjectSql('p')}
        ${pastFilter}
        AND NOT EXISTS (
          SELECT 1 FROM validator_manual_publish_queue q
          WHERE q.unic_result_id = ur.id AND q.cancelled_at IS NULL
        )
      ORDER BY ur.created_at ASC
      LIMIT $1
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add manual_queue_assign.js test_wp216_inactive_gate.test.js
git commit -m "feat(wp216): гейт active в наполнителе ручной очереди (defense-in-depth)"
```

---

## Task 6: Гейт в выдаче оператору (`manual_publish_queue.js`)

**Files:**
- Modify: `manual_publish_queue.js`
- Test: `test_wp216_inactive_gate.test.js` (добавить test-блок)

Поведенческий тест: `listQueue(pool)` не возвращает строку неактивного проекта, возвращает строку активного.

- [ ] **Step 1: Добавить падающий тест**

```js
test('listQueue: строка неактивного проекта скрыта; активного — видна', async () => {
  delete process.env.INACTIVE_PROJECT_GATE_ENABLED;
  const mpq = require('./manual_publish_queue');
  const items = await mpq.listQueue(pool);
  const ids = new Set(items.map(i => i.id));
  assert.equal(ids.has(MQ[INA]), false, 'inactive project manual row must be hidden from operator');
  assert.equal(ids.has(MQ[ACT]), true, 'active project manual row must be visible');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: FAIL — `MQ[INA]` присутствует в выдаче (гейта ещё нет).

- [ ] **Step 3: Внести гейт в `manual_publish_queue.js`**

Добавить require сразу после `'use strict';` (строка 1):

```js
'use strict';
const { activeProjectSql } = require('./project_active_filter');
```

В `JOINED_SELECT` добавить LEFT JOIN на проект (после `LEFT JOIN autowarm_users au ... q.taken_by_id`):

```js
  LEFT JOIN autowarm_users au           ON au.id = q.taken_by_id
  LEFT JOIN validator_projects vp       ON vp.id = q.project_id
```

В `listQueue` добавить предикат в WHERE (НЕ в `getItem` — деталь по прямому id остаётся доступной):

```js
async function listQueue(pool, status = null) {
  const sql = JOINED_SELECT + `
    WHERE q.cancelled_at IS NULL
      AND ${activeProjectSql('vp')}
      AND ($1::text IS NULL OR q.operator_status = $1)
    ORDER BY q.planned_date ASC, q.phone_number ASC, q.id ASC`;
  const { rows } = await pool.query(sql, [status]);
  return rows.map(rowToDict);
}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_wp216_inactive_gate.test.js`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add manual_publish_queue.js test_wp216_inactive_gate.test.js
git commit -m "feat(wp216): гейт active в выдаче ручной очереди оператору"
```

---

## Task 7: Разовая очистка `cleanup_wp216_inactive_project_queue.js`

**Files:**
- Create: `cleanup_wp216_inactive_project_queue.js`
- Test: `test_cleanup_wp216_live.test.js`

По образцу `cleanup_wp155_manual_queue_overdue.js`: default dry-run, флаг `--apply`. Для проектов `active=false`: гасит `queued`/`in_progress` строки ручной очереди (`cancelled_at=now()`) и `pending` строки авто-тракта (`status='cancelled'`). Терминальные (`published`/`done`) не трогает. Идемпотентно.

- [ ] **Step 1: Написать падающий тест**

Create `test_cleanup_wp216_live.test.js`:

```js
'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { cleanupInactiveProjectQueue } = require('./cleanup_wp216_inactive_project_queue');

const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

const ACT = 99217001, INA = 99217002;
const MQ_INA_QUEUED = 99217101, MQ_INA_PUBLISHED = 99217102, MQ_ACT_QUEUED = 99217103;
const PQ_INA_PENDING = 99217201, PQ_INA_DONE = 99217202, PQ_ACT_PENDING = 99217203;

async function cleanup() {
  await pool.query(`DELETE FROM validator_manual_publish_queue WHERE id = ANY($1)`,
                   [[MQ_INA_QUEUED, MQ_INA_PUBLISHED, MQ_ACT_QUEUED]]);
  await pool.query(`DELETE FROM publish_queue WHERE id = ANY($1)`,
                   [[PQ_INA_PENDING, PQ_INA_DONE, PQ_ACT_PENDING]]);
  await pool.query(`DELETE FROM validator_projects WHERE id = ANY($1)`, [[ACT, INA]]);
}
async function mq(id, pid, st) {
  await pool.query(`INSERT INTO validator_manual_publish_queue
    (id, slot_id, content_id, unic_result_id, unic_task_id, project_id, project_name,
     account_username, platform, planned_date, operator_status)
    VALUES ($1,1,1,$1,1,$2,'wp216c','u','instagram', CURRENT_DATE, $3)`, [id, pid, st]);
}
async function pq(id, pid, st) {
  await pool.query(`INSERT INTO publish_queue (id, project_id, status, platform)
                    VALUES ($1,$2,$3,'instagram')`, [id, pid, st]);
}
async function setup() {
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,'WP216CleanAct','wp216ca',true,false)`, [ACT]);
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,'WP216CleanIna','wp216ci',false,false)`, [INA]);
  await mq(MQ_INA_QUEUED, INA, 'queued');
  await mq(MQ_INA_PUBLISHED, INA, 'published');   // терминальная — не трогать
  await mq(MQ_ACT_QUEUED, ACT, 'queued');         // активный — не трогать
  await pq(PQ_INA_PENDING, INA, 'pending');
  await pq(PQ_INA_DONE, INA, 'done');             // терминальная — не трогать
  await pq(PQ_ACT_PENDING, ACT, 'pending');       // активный — не трогать
}

before(async () => { await setup(); });
after(async () => { await cleanup(); await pool.end(); });

test('dry-run считает, но не меняет', async () => {
  const res = await cleanupInactiveProjectQueue(pool, { apply: false });
  assert.equal(res.manualCandidates, 1, 'one inactive queued manual row');
  assert.equal(res.autoCandidates, 1, 'one inactive pending auto row');
  const mqRow = await pool.query(`SELECT cancelled_at FROM validator_manual_publish_queue WHERE id=$1`, [MQ_INA_QUEUED]);
  assert.equal(mqRow.rows[0].cancelled_at, null, 'dry-run must not cancel');
});

test('apply гасит только неактивные не-терминальные; идемпотентно', async () => {
  const res = await cleanupInactiveProjectQueue(pool, { apply: true });
  assert.equal(res.manualCancelled, 1);
  assert.equal(res.autoCancelled, 1);

  // Неактивный queued → отменён; published не тронут.
  const mqQ = await pool.query(`SELECT cancelled_at FROM validator_manual_publish_queue WHERE id=$1`, [MQ_INA_QUEUED]);
  assert.ok(mqQ.rows[0].cancelled_at !== null, 'inactive queued cancelled');
  const mqP = await pool.query(`SELECT operator_status, cancelled_at FROM validator_manual_publish_queue WHERE id=$1`, [MQ_INA_PUBLISHED]);
  assert.equal(mqP.rows[0].cancelled_at, null, 'published not touched');
  // Активный queued не тронут.
  const mqA = await pool.query(`SELECT cancelled_at FROM validator_manual_publish_queue WHERE id=$1`, [MQ_ACT_QUEUED]);
  assert.equal(mqA.rows[0].cancelled_at, null, 'active project not touched');
  // Неактивный pending → cancelled; done не тронут; активный pending не тронут.
  const pqP = await pool.query(`SELECT status FROM publish_queue WHERE id=$1`, [PQ_INA_PENDING]);
  assert.equal(pqP.rows[0].status, 'cancelled', 'inactive pending cancelled');
  const pqD = await pool.query(`SELECT status FROM publish_queue WHERE id=$1`, [PQ_INA_DONE]);
  assert.equal(pqD.rows[0].status, 'done', 'done not touched');
  const pqA = await pool.query(`SELECT status FROM publish_queue WHERE id=$1`, [PQ_ACT_PENDING]);
  assert.equal(pqA.rows[0].status, 'pending', 'active pending not touched');

  // Идемпотентность: повторный apply — 0 изменений.
  const res2 = await cleanupInactiveProjectQueue(pool, { apply: true });
  assert.equal(res2.manualCancelled, 0);
  assert.equal(res2.autoCancelled, 0);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_cleanup_wp216_live.test.js`
Expected: FAIL — `Cannot find module './cleanup_wp216_inactive_project_queue'`.

- [ ] **Step 3: Реализовать скрипт**

Create `cleanup_wp216_inactive_project_queue.js`:

```js
'use strict';
// WP#216 one-off: заморозить накопленную работу неактивных клиентов (validator_projects.active=false).
//  - ручная очередь: cancelled_at для operator_status IN ('queued','in_progress') (published не трогаем)
//  - авто-тракт: publish_queue status='pending' → 'cancelled' (done/failed/cancelled не трогаем)
// Идемпотентно (повторный прогон находит 0). Использование:
//   node cleanup_wp216_inactive_project_queue.js            # dry-run (только счёт)
//   node cleanup_wp216_inactive_project_queue.js --apply    # отменить
const { Pool } = require('pg');

const INACTIVE = `(SELECT id FROM validator_projects WHERE active = false)`;
const MANUAL_TARGET = `
  FROM validator_manual_publish_queue q
  WHERE q.cancelled_at IS NULL
    AND q.operator_status IN ('queued','in_progress')
    AND q.project_id IN ${INACTIVE}`;
const AUTO_TARGET = `
  FROM publish_queue pq
  WHERE pq.status = 'pending'
    AND pq.project_id IN ${INACTIVE}`;

async function cleanupInactiveProjectQueue(pool, { apply = false } = {}) {
  const manualCandidates = (await pool.query(`SELECT count(*)::int AS n ${MANUAL_TARGET}`)).rows[0].n;
  const autoCandidates   = (await pool.query(`SELECT count(*)::int AS n ${AUTO_TARGET}`)).rows[0].n;
  if (!apply) {
    return { apply: false, manualCandidates, autoCandidates, manualCancelled: 0, autoCancelled: 0 };
  }
  const m = await pool.query(`
    UPDATE validator_manual_publish_queue q
    SET cancelled_at = now(), updated_at = now()
    WHERE q.id IN (SELECT q.id ${MANUAL_TARGET})`);
  const a = await pool.query(`
    UPDATE publish_queue pq
    SET status = 'cancelled', updated_at = now()
    WHERE pq.id IN (SELECT pq.id ${AUTO_TARGET})`);
  return { apply: true, manualCandidates, autoCandidates,
           manualCancelled: m.rowCount, autoCancelled: a.rowCount };
}

module.exports = { cleanupInactiveProjectQueue };

if (require.main === module) {
  const apply = process.argv.includes('--apply');
  const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });
  cleanupInactiveProjectQueue(pool, { apply })
    .then(r => { console.log('[cleanup-wp216]', JSON.stringify(r)); return pool.end(); })
    .catch(e => { console.error('[cleanup-wp216] error:', e.message); process.exit(1); });
}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-testbench && node --test test_cleanup_wp216_live.test.js`
Expected: PASS (2 теста).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add cleanup_wp216_inactive_project_queue.js test_cleanup_wp216_live.test.js
git commit -m "feat(wp216): разовая очистка in-flight работы неактивных клиентов"
```

---

## Task 8: Полный прогон + codex review

**Files:** нет (верификация)

- [ ] **Step 1: Прогнать все WP216-тесты + затронутые соседние**

Run:
```bash
cd /home/claude-user/autowarm-testbench
node --test test_project_active_filter.test.js test_wp216_inactive_gate.test.js test_cleanup_wp216_live.test.js test_client_manual_publish.test.js test_retry_decision.test.js test_manual_publish_queue.test.js
```
Expected: все PASS, 0 fail. (`test_client_manual_publish` и `test_manual_publish_queue` — регресс-страховка соседних путей.)

- [ ] **Step 2: Прогнать весь набор на регрессии**

Run: `cd /home/claude-user/autowarm-testbench && node --test 2>&1 | tail -20`
Expected: нет НОВЫХ падений против baseline (часть live-тестов может требовать спец-фикстур — сверить с состоянием до ветки, не вводить новых красных).

- [ ] **Step 3: Codex review диффа ветки**

Run: `cd /home/claude-user/autowarm-testbench && ~/.local/bin/codex review` (или `git diff origin/main` → codex)
Expected: 0 P1. P2/P3 — занести в evidence/обсудить с Данилом.

- [ ] **Step 4: Финальный коммит при правках по ревью**

```bash
cd /home/claude-user/autowarm-testbench
git add -A && git commit -m "chore(wp216): правки по codex review"   # если были
```

---

## Деплой (после мёржа PR — выполняется отдельно, не часть TDD-цикла)

1. **Код:** в проде `cd /root/.openclaw/workspace-genri/autowarm && git pull`.
2. **Рестарт процессов** (новый модуль require'ится в long-running процессах и кронах):
   `sudo pm2 restart` server.js (id35) и связанные cron-процессы. Точный список id — уточнить у Данила/по `pm2 list` (autowarm = id35).
3. **Разовая очистка:** сначала dry-run, затем apply:
   ```bash
   cd /root/.openclaw/workspace-genri/autowarm
   node cleanup_wp216_inactive_project_queue.js            # dry-run — свериться со счётом (~29 ручных + ~207 авто на момент диагностики)
   node cleanup_wp216_inactive_project_queue.js --apply
   ```
4. **Verify:** в UI ручной выкладки строк Септизима нет; `SELECT count(*) FROM validator_manual_publish_queue WHERE project_id=83 AND cancelled_at IS NULL` = 0.
5. **Откат:** `INACTIVE_PROJECT_GATE_ENABLED=false` в `.env` + рестарт — мгновенно возвращает старое поведение. Миграций БД нет.

---

## Self-Review (выполнено автором плана)

- **Spec coverage:** все 5 точек гейта (Task 2–6) + общий модуль (Task 1) + очистка (Task 7) + kill-switch (Task 1) + краевые случаи (fail-closed в Task 1, идемпотентность в Task 7, откат в Деплой) покрыты. Follow-up «каскад по деактивации» помечен вне scope в спеке.
- **Placeholder scan:** код приведён полностью в каждом шаге; «уточнить список pm2 id» — единственный открытый пункт, он в разделе Деплой (вне TDD-цикла), помечен явно.
- **Type/имя-consistency:** функция очистки называется `cleanupInactiveProjectQueue` в тесте (Task 7 Step 1) и в реализации (Step 3); поля результата `manualCandidates/autoCandidates/manualCancelled/autoCancelled` совпадают. Модульные экспорты `projectGateEnabled/activeProjectSql/projectIsActive` согласованы между Task 1 и потребителями (Task 2–6). Алиас `vpa` в assign_candidates не конфликтует с `p` внутри NOT EXISTS.
