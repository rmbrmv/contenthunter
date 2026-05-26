# WP #153 — Воронка пайплайна + статистика ручной выкладки/потеряно — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить воронку пайплайна (6 шагов + Потеряно/% ручной) и метрику «SR итоговый» в дашборд delivery и утренний TG-отчёт, чтобы было видно где теряется контент и сколько идёт вручную.

**Architecture:** Единый модуль `pipeline_funnel.js` — единственный источник правды для воронки; чистая функция `assembleFunnel` (вся арифметика, тестируется без БД) + `computeFunnel` (3 SQL-запроса по когорте текущего slot_date). **Якорь когорты** = `COALESCE(validator_schedule_slots.slot_date, unic_tasks.slot_date)` для очереди и `COALESCE(s.slot_date, m.planned_date)` для ручной — живая дата планировщика (решение «по текущему slot_date»), снапшоты только как fallback при удалённом слоте; обе когорты якорятся одинаково, чтобы не смешивать дни. Вызывается и эндпоинтом дашборда (`server.js`), и TG-отчётом (`daily_publish_report.js`). Фронт (`public/index.html`) рендерит новый блок и плашку из ответа эндпоинта. Миграций нет — только чтение.

**Tech Stack:** Node.js, `pg` (node-postgres), Express, встроенный `node:test`, Tailwind-разметка во фронте.

**ВАЖНО — репозитории:**
- **Код** (всё ниже, кроме этого плана) — репо `GenGo2/delivery-contenthunter`, рабочая копия **`/root/.openclaw/workspace-genri/autowarm/`** (прод; auto-push git-hook на коммит). Тесты: `node --test --test-force-exit tests/*.test.js` (+ корневые `*.test.js`).
- **Спека и этот план** — репо `contenthunter`, ветка `wp153-manual-publish-funnel-stats`.
- БД: `openclaw:openclaw123@localhost:5432/openclaw`.

**Kill-switch:** `PIPELINE_FUNNEL_ENABLED` (дефолт `'1'`). При `'0'` эндпоинт отдаёт `funnel:null` + `overall.sr_total:null`, TG-отчёт пропускает блок воронки, фронт прячет блок/плашку.

---

## Контракт данных (используется во всех тасках)

`assembleFunnel(raw)` принимает сырые счётчики и возвращает готовый объект. **Сырой вход `raw`:**

```js
{
  plan: int,                          // все строки очереди когорты
  uniqualized: int,                   // строки с готовым unic_result
  autotask: int,                      // строки с publish_task_id (диспатчнуто)
  auto_published: int,                // status='done'
  manual_handoff: int,                // реактивный handoff (manual_handoff_at)
  manual_handoff_published: int,      // из handoff: слот получил matched_post_url
  proactive_manual_notdispatched: int,// недиспатч + slot.manual_publish=true (оценка)
  manual_published_total: int,        // ВСЯ ручная выложено (validator_manual_publish_queue)
  slots_planned: int,                 // не-empty слотов в когорте (slot-level)
  slots_with_queue: int               // из них имеют ≥1 строку очереди (slot-level)
}
```

**Выход `assembleFunnel(raw)`:**

```js
{
  plan, uniqualized, autotask, auto_published,
  manual_handoff, manual_handoff_published, manual_published_total,
  lost_count,            // max(0, plan - auto_published - manual_published_total)
  lost_pct,             // plan>0 ? round3(lost_count/plan) : null
  manual_share_pct,     // autotask>0 ? round3(manual_handoff/autotask) : null
  sr_total,             // plan>0 ? round3((auto_published+manual_published_total)/plan) : null
  proactive_manual_published, // max(0, manual_published_total - manual_handoff_published)
  blind_zones: {
    before_uniq,   // max(0, slots_planned - slots_with_queue)  [slot-level оценка]
    after_uniq,    // max(0, uniqualized - autotask - proactive_manual_notdispatched)
    auto_errors,   // max(0, autotask - auto_published - manual_handoff)
    manual_stuck   // max(0, manual_handoff - manual_handoff_published)
  }
}
```

`round3(x)` = `Math.round(x*1000)/1000` (зеркало `computeSuccessRate`). Тождество: при `plan>0` и неклампленном `lost_count` → `lost_pct + sr_total === 1`.

**Эталон когорты 2026-05-25** (для регрессии): `plan=280, uniqualized≈280, autotask=126, auto_published=113, manual_handoff=12, manual_published_total=122` → `lost_count=45, sr_total≈0.839`.

---

## File Structure

- **Create** `/root/.openclaw/workspace-genri/autowarm/pipeline_funnel.js` — модуль воронки (`assembleFunnel`, `slotDateBoundsFromRange`, `computeFunnel`).
- **Create** `/root/.openclaw/workspace-genri/autowarm/tests/test_pipeline_funnel_pure.test.js` — юнит-тесты `assembleFunnel` + `slotDateBoundsFromRange`.
- **Create** `/root/.openclaw/workspace-genri/autowarm/tests/test_pipeline_funnel_live.test.js` — live-DB регрессия `computeFunnel`.
- **Modify** `/root/.openclaw/workspace-genri/autowarm/server.js` — вызвать `computeFunnel` в `/api/publish-queue/dashboard`, добавить `funnel` + `overall.sr_total`.
- **Modify** `/root/.openclaw/workspace-genri/autowarm/daily_publish_report.js` — добавить строки воронки в TG.
- **Modify** `/root/.openclaw/workspace-genri/autowarm/public/index.html` — плашка «SR итоговый» + блок «Воронка пайплайна».

---

## Task 1: Чистая функция `assembleFunnel` + `slotDateBoundsFromRange`

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/pipeline_funnel.js`
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_pipeline_funnel_pure.test.js`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_pipeline_funnel_pure.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { assembleFunnel, slotDateBoundsFromRange } = require('../pipeline_funnel');

const COHORT_2505 = {
  plan: 280, uniqualized: 280, autotask: 126, auto_published: 113,
  manual_handoff: 12, manual_handoff_published: 9,
  proactive_manual_notdispatched: 140, manual_published_total: 122,
  slots_planned: 16, slots_with_queue: 16,
};

test('assembleFunnel: эталон когорты 25.05', () => {
  const f = assembleFunnel(COHORT_2505);
  assert.equal(f.plan, 280);
  assert.equal(f.auto_published, 113);
  assert.equal(f.manual_published_total, 122);
  assert.equal(f.lost_count, 45);                 // 280-113-122
  assert.equal(f.sr_total, 0.839);                // 235/280
  assert.equal(f.manual_share_pct, 0.095);        // 12/126
  assert.equal(f.blind_zones.auto_errors, 1);     // 126-113-12
  assert.equal(f.blind_zones.manual_stuck, 3);    // 12-9
  assert.equal(f.proactive_manual_published, 113);// 122-9
});

test('assembleFunnel: тождество lost_pct + sr_total = 1 при plan>0', () => {
  const f = assembleFunnel(COHORT_2505);
  assert.ok(Math.abs(f.lost_pct + f.sr_total - 1) < 1e-9);
});

test('assembleFunnel: пустая когорта → проценты null, без NaN', () => {
  const f = assembleFunnel({
    plan: 0, uniqualized: 0, autotask: 0, auto_published: 0,
    manual_handoff: 0, manual_handoff_published: 0,
    proactive_manual_notdispatched: 0, manual_published_total: 0,
    slots_planned: 0, slots_with_queue: 0,
  });
  assert.equal(f.lost_count, 0);
  assert.equal(f.lost_pct, null);
  assert.equal(f.sr_total, null);
  assert.equal(f.manual_share_pct, null);
});

test('assembleFunnel: clamp — отрицательные зоны не уходят в минус', () => {
  // manual_published_total > plan (грязные данные) → lost_count кламп в 0
  const f = assembleFunnel({
    plan: 5, uniqualized: 5, autotask: 5, auto_published: 4,
    manual_handoff: 1, manual_handoff_published: 1,
    proactive_manual_notdispatched: 0, manual_published_total: 10,
    slots_planned: 1, slots_with_queue: 1,
  });
  assert.equal(f.lost_count, 0);
  assert.equal(f.blind_zones.auto_errors, 0);     // 5-4-1=0
});

test('slotDateBoundsFromRange: МСК-полночь UTC-инстанты → YYYY-MM-DD [from, toExcl)', () => {
  // range «вчера» 25.05: from=24.05 21:00Z (00:00 MSK 25.05), to=25.05 21:00Z (00:00 MSK 26.05)
  const range = { from: new Date('2026-05-24T21:00:00.000Z'), to: new Date('2026-05-25T21:00:00.000Z') };
  const b = slotDateBoundsFromRange(range);
  assert.equal(b.slotDateFrom, '2026-05-25');
  assert.equal(b.slotDateToExcl, '2026-05-26');
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_pipeline_funnel_pure.test.js`
Expected: FAIL — `Cannot find module '../pipeline_funnel'`.

- [ ] **Step 3: Написать модуль (чистая часть)**

Создать `pipeline_funnel.js`:

```js
'use strict';
// WP #153 — воронка пайплайна (уровень публикаций, когорта по unic_tasks.slot_date).
// Spec: contenthunter/docs/superpowers/specs/2026-05-26-wp153-manual-publish-funnel-stats-design.md
const MSK_OFFSET_MS = 3 * 60 * 60 * 1000;

function round3(x) { return Math.round(x * 1000) / 1000; }
function nn(v) { return Number(v) || 0; }
function clamp0(x) { return x < 0 ? 0 : x; }

// Сырые счётчики → готовый объект воронки. Чистая, без БД.
function assembleFunnel(raw) {
  const plan = nn(raw.plan);
  const uniqualized = nn(raw.uniqualized);
  const autotask = nn(raw.autotask);
  const auto_published = nn(raw.auto_published);
  const manual_handoff = nn(raw.manual_handoff);
  const manual_handoff_published = nn(raw.manual_handoff_published);
  const manual_published_total = nn(raw.manual_published_total);
  const proactive_nd = nn(raw.proactive_manual_notdispatched);
  const slots_planned = nn(raw.slots_planned);
  const slots_with_queue = nn(raw.slots_with_queue);

  const lost_count = clamp0(plan - auto_published - manual_published_total);
  return {
    plan, uniqualized, autotask, auto_published,
    manual_handoff, manual_handoff_published, manual_published_total,
    lost_count,
    lost_pct: plan > 0 ? round3(lost_count / plan) : null,
    manual_share_pct: autotask > 0 ? round3(manual_handoff / autotask) : null,
    sr_total: plan > 0 ? round3((auto_published + manual_published_total) / plan) : null,
    proactive_manual_published: clamp0(manual_published_total - manual_handoff_published),
    blind_zones: {
      before_uniq: clamp0(slots_planned - slots_with_queue),
      after_uniq: clamp0(uniqualized - autotask - proactive_nd),
      auto_errors: clamp0(autotask - auto_published - manual_handoff),
      manual_stuck: clamp0(manual_handoff - manual_handoff_published),
    },
  };
}

// {from,to} (UTC-инстанты MSK-полночей из calcDashboardRange/windowForSendDate)
// → границы slot_date 'YYYY-MM-DD' [slotDateFrom, slotDateToExcl).
// Трюк: ms + MSK_OFFSET → toISOString() даёт MSK-календарную дату.
function slotDateBoundsFromRange(range) {
  const toYmd = (dt) => new Date(dt.getTime() + MSK_OFFSET_MS).toISOString().slice(0, 10);
  return { slotDateFrom: toYmd(range.from), slotDateToExcl: toYmd(range.to) };
}

module.exports = { assembleFunnel, slotDateBoundsFromRange, MSK_OFFSET_MS, round3 };
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_pipeline_funnel_pure.test.js`
Expected: PASS (5 tests).

- [ ] **Step 5: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add pipeline_funnel.js tests/test_pipeline_funnel_pure.test.js
git commit -m "feat(wp153): pipeline_funnel — чистая assembleFunnel + slotDateBoundsFromRange"
```

---

## Task 2: `computeFunnel` — SQL по когорте + фильтры + live-тест

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/pipeline_funnel.js`
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_pipeline_funnel_live.test.js`

- [ ] **Step 1: Написать падающий live-тест**

Создать `tests/test_pipeline_funnel_live.test.js` (изолированные id в диапазоне 9915300, как в существующих live-тестах):

```js
// Run: node --test --test-force-exit tests/test_pipeline_funnel_live.test.js
'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { computeFunnel } = require('../pipeline_funnel');
const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

const PID=9915300, CONTENT=9915300, SLOT=9915300, TASK=9915300, RESULT=9915300;
const D='2026-09-09'; // дата вне прод-данных

async function cleanup(){
  await pool.query('DELETE FROM validator_manual_publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1',[TASK]).catch(()=>{});
  await pool.query('DELETE FROM validator_schedule_slots WHERE id=$1',[SLOT]).catch(()=>{});
  await pool.query('DELETE FROM validator_content WHERE id=$1',[CONTENT]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1',[PID]).catch(()=>{});
}

before(async()=>{ await cleanup();
  await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,'WP153','wp153',true,false)`,[PID]);
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'wp153','approved','video',1)`,[CONTENT,PID]);
  await pool.query(`INSERT INTO validator_schedule_slots (id,project_id,slot_date,slot_position,content_id,slot_type,status,manual_publish,matched_post_url)
                    VALUES ($1,$2,$3,1,$4,'client','filled',false,NULL)`,[SLOT,PID,D,CONTENT]);
  await pool.query(`INSERT INTO unic_tasks (id,project_id,content_id,slot_date,current_status,meta)
                    VALUES ($1,$2,$3,$4,'done',jsonb_build_object('slot_id',$5))`,[TASK,PID,CONTENT,D,SLOT]);
  await pool.query(`INSERT INTO unic_results (id,task_id,status,output_url) VALUES ($1,$2,'done','x')`,[RESULT,TASK]);
  // 3 строки очереди: 1 done (диспатч), 1 handoff (диспатч+manual_handoff_at), 1 проактивная (не диспатч)
  await pool.query(`INSERT INTO publish_queue (id,unic_result_id,unic_task_id,project_id,platform,account_username,status,scheduled_at,publish_task_id,manual_handoff_at)
    VALUES (9915301,$1,$2,$3,'instagram','a','done',     now(), 111111, NULL),
           (9915302,$1,$2,$3,'tiktok',   'a','cancelled',now(), 111112, now()),
           (9915303,$1,$2,$3,'youtube',  'a','cancelled',now(), NULL,   NULL)`,[RESULT,TASK,PID]);
});
after(async()=>{ await cleanup(); await pool.end(); });

test('computeFunnel: считает когорту по slot_date', async()=>{
  const f = await computeFunnel({ pool, slotDateFrom:D, slotDateToExcl:'2026-09-10', filters:{} });
  assert.equal(f.plan, 3);
  assert.equal(f.uniqualized, 3);
  assert.equal(f.autotask, 2);             // 2 строки с publish_task_id
  assert.equal(f.auto_published, 1);       // done
  assert.equal(f.manual_handoff, 1);       // manual_handoff_at
  assert.equal(f.manual_handoff_published, 0); // slot.matched_post_url IS NULL
  assert.equal(f.manual_published_total, 0);   // нет строк в ручной очереди
  assert.equal(f.lost_count, 2);           // 3-1-0
});

test('computeFunnel: пустое окно → нули и null-проценты', async()=>{
  const f = await computeFunnel({ pool, slotDateFrom:'2026-09-20', slotDateToExcl:'2026-09-21', filters:{} });
  assert.equal(f.plan, 0);
  assert.equal(f.sr_total, null);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_pipeline_funnel_live.test.js`
Expected: FAIL — `computeFunnel is not a function`.

- [ ] **Step 3: Реализовать `computeFunnel` в `pipeline_funnel.js`**

Добавить ПЕРЕД `module.exports` (и дополнить экспорт):

```js
// Фильтры дашборда для publish_queue-когорты (project/platform/account/pack).
// startIndex: уже заняты $1 (slotDateFrom), $2 (slotDateToExcl).
function _pqFilters(filters, startIndex) {
  const conds = []; const params = [];
  const push = (tpl, val) => { params.push(val); conds.push(tpl.replace('$?', '$' + (startIndex + params.length))); };
  if (filters.project) {
    const list = [].concat(filters.project).map(s => String(s).trim()).filter(Boolean);
    if (list.length === 1) push('COALESCE(vp.project, vp2.project) = $?', list[0]);
    else if (list.length > 1) push('COALESCE(vp.project, vp2.project) = ANY($?::text[])', list);
  }
  if (filters.platform)         push('LOWER(pq.platform) = $?',          String(filters.platform).toLowerCase());
  if (filters.account_username) push('pq.account_username ILIKE $?',     '%' + String(filters.account_username) + '%');
  if (filters.pack_name)        push('pq.pack_name ILIKE $?',            '%' + String(filters.pack_name) + '%');
  return { conds, params };
}

// Фильтры для ручной очереди (своя таблица, свои колонки).
function _mqFilters(filters, startIndex) {
  const conds = []; const params = [];
  const push = (tpl, val) => { params.push(val); conds.push(tpl.replace('$?', '$' + (startIndex + params.length))); };
  if (filters.project) {
    const list = [].concat(filters.project).map(s => String(s).trim()).filter(Boolean);
    if (list.length === 1) push('m.project_name = $?', list[0]);
    else if (list.length > 1) push('m.project_name = ANY($?::text[])', list);
  }
  if (filters.platform)         push('LOWER(m.platform) = $?',           String(filters.platform).toLowerCase());
  if (filters.account_username) push('m.account_username ILIKE $?',      '%' + String(filters.account_username) + '%');
  if (filters.pack_name)        push('m.pack_name ILIKE $?',             '%' + String(filters.pack_name) + '%');
  return { conds, params };
}

async function computeFunnel({ pool, slotDateFrom, slotDateToExcl, filters = {} }) {
  // Q1: publish_queue-когорта по unic_tasks.slot_date (уровень публикаций).
  const f1 = _pqFilters(filters, 2);
  const q1 = await pool.query(`
    SELECT
      COUNT(*)                                                   AS plan,
      COUNT(*) FILTER (WHERE ur.status IN ('ready','done'))      AS uniqualized,
      COUNT(*) FILTER (WHERE pq.publish_task_id IS NOT NULL)     AS autotask,
      COUNT(*) FILTER (WHERE pq.status = 'done')                 AS auto_published,
      COUNT(*) FILTER (WHERE pq.manual_handoff_at IS NOT NULL)   AS manual_handoff,
      COUNT(*) FILTER (WHERE pq.manual_handoff_at IS NOT NULL
                        AND s.matched_post_url IS NOT NULL)      AS manual_handoff_published,
      COUNT(*) FILTER (WHERE pq.publish_task_id IS NULL
                        AND s.manual_publish IS TRUE)            AS proactive_manual_notdispatched
    FROM publish_queue pq
    LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
    LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
    LEFT JOIN validator_schedule_slots s ON s.id = NULLIF(ut.meta->>'slot_id','')::int
    LEFT JOIN validator_projects vp  ON vp.id  = pq.project_id
    LEFT JOIN validator_projects vp2 ON vp2.id = ut.project_id
    WHERE COALESCE(s.slot_date, ut.slot_date) >= $1::date
      AND COALESCE(s.slot_date, ut.slot_date) <  $2::date
      ${f1.conds.length ? 'AND ' + f1.conds.join(' AND ') : ''}
  `, [slotDateFrom, slotDateToExcl, ...f1.params]);

  // Q2: вся выложенная вручную (validator_manual_publish_queue по planned_date).
  const f2 = _mqFilters(filters, 2);
  // Якорь — тот же текущий slot_date, что и в Q1 (join к слоту по m.slot_id),
  // fallback на снапшот m.planned_date если слот удалён. Иначе при переносах
  // ручные строки попали бы в чужой день (codex P2).
  const q2 = await pool.query(`
    SELECT COUNT(*) AS manual_published_total
    FROM validator_manual_publish_queue m
    LEFT JOIN validator_schedule_slots s ON s.id = m.slot_id
    WHERE COALESCE(s.slot_date, m.planned_date) >= $1::date
      AND COALESCE(s.slot_date, m.planned_date) <  $2::date
      AND m.operator_status = 'published'
      ${f2.conds.length ? 'AND ' + f2.conds.join(' AND ') : ''}
  `, [slotDateFrom, slotDateToExcl, ...f2.params]);

  // Q3: slot-level оценка «до постановки в очередь» (только project-фильтр).
  const f3 = (() => {
    const conds = []; const params = [];
    if (filters.project) {
      const list = [].concat(filters.project).map(s => String(s).trim()).filter(Boolean);
      if (list.length === 1) { params.push(list[0]); conds.push('vp.project = $' + (2 + params.length)); }
      else if (list.length > 1) { params.push(list); conds.push('vp.project = ANY($' + (2 + params.length) + '::text[])'); }
    }
    return { conds, params };
  })();
  const q3 = await pool.query(`
    SELECT
      COUNT(*) AS slots_planned,
      COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM publish_queue pq2
        LEFT JOIN unic_results ur2 ON ur2.id = pq2.unic_result_id
        LEFT JOIN unic_tasks ut2 ON ut2.id = COALESCE(pq2.unic_task_id, ur2.task_id)
        WHERE NULLIF(ut2.meta->>'slot_id','')::int = s.id
      )) AS slots_with_queue
    FROM validator_schedule_slots s
    LEFT JOIN validator_projects vp ON vp.id = s.project_id
    WHERE s.slot_date >= $1::date AND s.slot_date < $2::date
      AND s.status <> 'empty'
      ${f3.conds.length ? 'AND ' + f3.conds.join(' AND ') : ''}
  `, [slotDateFrom, slotDateToExcl, ...f3.params]);

  return assembleFunnel({
    ...q1.rows[0],
    manual_published_total: q2.rows[0].manual_published_total,
    slots_planned: q3.rows[0].slots_planned,
    slots_with_queue: q3.rows[0].slots_with_queue,
  });
}
```

Обновить экспорт:

```js
module.exports = { assembleFunnel, slotDateBoundsFromRange, computeFunnel, MSK_OFFSET_MS, round3 };
```

- [ ] **Step 4: Запустить live-тест — убедиться, что проходит**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_pipeline_funnel_live.test.js`
Expected: PASS (2 tests).

- [ ] **Step 5: Прогнать на реальной когорте 25.05 (ручная сверка эталона)**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm && node -e "
const { Pool } = require('pg');
const { computeFunnel } = require('./pipeline_funnel');
const pool = new Pool({host:'localhost',user:'openclaw',password:'openclaw123',database:'openclaw'});
computeFunnel({pool, slotDateFrom:'2026-05-25', slotDateToExcl:'2026-05-26', filters:{}})
  .then(f => { console.log(JSON.stringify(f,null,1)); return pool.end(); });
"
```
Expected: порядок величин эталона — `plan≈280, autotask≈126, auto_published≈113, manual_handoff≈12, manual_published_total≈122, lost_count≈45, sr_total≈0.839`. Числа из разведки считались по `ut.slot_date`/`planned_date`; при живом якоре `COALESCE(s.slot_date,…)` они могут чуть сдвинуться для перенесённых слотов — **записать фактический вывод как регрессионный эталон** (pure-тест в Task 1 на хардкодных входах от этого не зависит).

- [ ] **Step 6: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add pipeline_funnel.js tests/test_pipeline_funnel_live.test.js
git commit -m "feat(wp153): computeFunnel — SQL по когорте slot_date + фильтры + live-тест"
```

---

## Task 3: Интеграция в эндпоинт дашборда (`server.js`)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js` (require ~верх; handler `1937-2038`)

- [ ] **Step 1: Подключить модуль**

Найти require-блок около начала `server.js` (где подключаются другие локальные модули, напр. `require('./daily_publish_report')`). Добавить:

```js
const { computeFunnel, slotDateBoundsFromRange } = require('./pipeline_funnel');
```

- [ ] **Step 2: Вызвать `computeFunnel` в обработчике**

В `app.get('/api/publish-queue/dashboard', ...)`, ПОСЛЕ блока серии (после строки `series = Object.assign(...)` / до `console.log('[pub-dash]'...)`, ~строка 2010), добавить:

```js
    // --- Воронка пайплайна (WP #153) — когорта по unic_tasks.slot_date ---
    let funnel = null;
    if (process.env.PIPELINE_FUNNEL_ENABLED !== '0') {
      try {
        const { slotDateFrom, slotDateToExcl } = slotDateBoundsFromRange(range);
        funnel = await computeFunnel({
          pool, slotDateFrom, slotDateToExcl,
          filters: {
            project: req.query.project,
            platform: req.query.platform,
            account_username: req.query.account_username,
            pack_name: req.query.pack_name,
          },
        });
      } catch (e) {
        console.error('[pub-dash] funnel error:', e.message);  // воронка опциональна — не роняем дашборд
      }
    }
```

- [ ] **Step 3: Добавить `funnel` и `sr_total` в ответ**

В `return res.json({...})` (строки ~2018-2035): добавить `funnel` в корень и `sr_total` в `overall`. Заменить:

```js
      overall,
```
на:

```js
      overall: Object.assign({}, overall, { sr_total: funnel ? funnel.sr_total : null }),
```

и добавить строку (рядом с `series,`):

```js
      funnel,
```

- [ ] **Step 4: Смоук эндпоинта**

Перезапустить сервер локально или дернуть прод-инстанс. Минимальная проверка формы ответа без сервера:

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm && node -e "
const { slotDateBoundsFromRange } = require('./pipeline_funnel');
const r = { from:new Date('2026-05-24T21:00:00Z'), to:new Date('2026-05-25T21:00:00Z') };
console.log(slotDateBoundsFromRange(r));
" && node --check server.js && echo "server.js syntax OK"
```
Expected: `{ slotDateFrom: '2026-05-25', slotDateToExcl: '2026-05-26' }` и `server.js syntax OK`.

- [ ] **Step 5: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js
git commit -m "feat(wp153): дашборд-эндпоинт отдаёт funnel + overall.sr_total (kill-switch PIPELINE_FUNNEL_ENABLED)"
```

---

## Task 4: Фронт — плашка «SR итоговый» + блок «Воронка пайплайна» (`public/index.html`)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html` (markup `2329-2342`; JS `11835-11935`)

- [ ] **Step 1: Расширить сетку плиток и добавить плашку SR итоговый**

В markup (строка ~2331) заменить `grid-cols-7` на `grid-cols-8`:

```html
    <div class="grid grid-cols-8 gap-2" id="dash-overall-tiles">
```

В JS переименовать существующую плашку `success_rate` (строка ~11842) в «SR авто»:

```js
  ['success_rate',      'SR авто',     'text-indigo-600',  'border-indigo-100'],
```

В `renderDashboardOverall` (строка ~11860) после `.join('')` стандартных плиток добавить 8-ю плашку SR итоговый. Заменить тело функции на:

```js
function renderDashboardOverall(overall) {
  const root = document.getElementById('dash-overall-tiles');
  if (!root) return;
  const tiles = DASH_BUCKET_LABELS.map(([key, label, textCls, borderCls]) => `
    <div class="flex flex-col items-center gap-0.5 bg-white border ${borderCls} rounded-lg px-2 py-2">
      <span class="text-xl font-bold ${textCls}">${_fmtBucketCell(key, overall[key])}</span>
      <span class="text-[10px] text-gray-400 uppercase">${label}</span>
    </div>
  `);
  // SR итоговый (WP #153): (Авто + Ручная) / План. Прячем при выключенной воронке (kill-switch → sr_total:null), honors codex P3.
  const showSr = overall.sr_total != null;
  if (showSr) {
    tiles.push(`
      <div class="flex flex-col items-center gap-0.5 bg-violet-50 border border-violet-300 rounded-lg px-2 py-2">
        <span class="text-xl font-bold text-violet-700">${Math.round(overall.sr_total*100)}%</span>
        <span class="text-[10px] text-violet-600 uppercase font-semibold">SR итоговый</span>
      </div>
    `);
  }
  root.className = 'grid gap-2 ' + (showSr ? 'grid-cols-8' : 'grid-cols-7');
  root.innerHTML = tiles.join('');
}
```

- [ ] **Step 2: Добавить markup блока «Воронка пайплайна»**

После блока «По платформам» (после строки `</div>` на ~2342, до блока графика на ~2344) вставить:

```html
  <!-- Воронка пайплайна (WP #153) -->
  <div id="dash-funnel-card" class="bg-white rounded-xl border border-gray-200 p-4 mt-3 hidden">
    <div class="text-xs font-semibold text-gray-400 uppercase mb-3">Воронка пайплайна</div>
    <div id="dash-funnel" class="overflow-x-auto"></div>
    <div id="dash-funnel-notes" class="text-[11px] text-gray-500 mt-3 pt-2 border-t border-dashed border-gray-200"></div>
  </div>
```

- [ ] **Step 3: Добавить рендер воронки**

После `renderDashboardPlatforms` (строка ~11886) добавить:

```js
function _fmtPct(v) { return v == null ? '—' : Math.round(v * 100) + '%'; }

function renderDashboardFunnel(funnel) {
  const card = document.getElementById('dash-funnel-card');
  const root = document.getElementById('dash-funnel');
  const notes = document.getElementById('dash-funnel-notes');
  if (!card || !root) return;
  if (!funnel) { card.classList.add('hidden'); return; }
  card.classList.remove('hidden');

  const steps = [
    ['План', funnel.plan, 'text-violet-600'],
    ['Уникали-зировано', funnel.uniqualized, 'text-sky-500'],
    ['Авто-задача', funnel.autotask, 'text-blue-500'],
    ['Авто выложено', funnel.auto_published, 'text-green-600'],
    ['В ручную', funnel.manual_handoff, 'text-yellow-500'],
    ['В ручную выложено', funnel.manual_handoff_published, 'text-green-600'],
  ];
  const stepCells = steps.map(([label, val, cls]) => `
    <td class="text-center px-3 py-2 align-top">
      <div class="text-[10px] text-gray-400 uppercase leading-tight mb-1">${label}</div>
      <div class="text-2xl font-bold ${cls}">${val}</div>
    </td>`).join('');
  const lostCell = `
    <td class="text-center px-3 py-2 align-top bg-amber-50 rounded">
      <div class="text-[10px] text-amber-700 uppercase font-semibold leading-tight mb-1">Потеряно кол./%</div>
      <div class="text-2xl font-bold text-amber-700">${funnel.lost_count}</div>
      <div class="text-xs text-amber-600">${_fmtPct(funnel.lost_pct)}</div>
    </td>`;
  const shareCell = `
    <td class="text-center px-3 py-2 align-top bg-amber-50 rounded">
      <div class="text-[10px] text-amber-700 uppercase font-semibold leading-tight mb-1">% ручной выкладки</div>
      <div class="text-2xl font-bold text-amber-700">${_fmtPct(funnel.manual_share_pct)}</div>
    </td>`;
  root.innerHTML = `<table class="w-full"><tbody><tr>${stepCells}${lostCell}${shareCell}</tr></tbody></table>`;

  const bz = funnel.blind_zones || {};
  notes.innerHTML =
    `<b>Слепые зоны:</b> до постановки в очередь — ${bz.before_uniq} (оценка по слотам) │ ` +
    `после уник. → авто-задача — ${bz.after_uniq} │ ошибки авто — ${bz.auto_errors} │ зависло вручную — ${bz.manual_stuck}` +
    `<br>Проактивная ручная (≈${funnel.proactive_manual_published}) учтена в «Потеряно», но не в реактивной ветке. ` +
    `Период «Сегодня» включает незавершённые публикации в «Потеряно».`;
}
```

- [ ] **Step 4: Вызвать рендер в `loadPublishingDashboard`**

В `loadPublishingDashboard` после `renderDashboardPlatforms(data.by_platform);` (строка ~11925) добавить:

```js
    renderDashboardFunnel(data.funnel);
```

- [ ] **Step 5: Визуальная проверка**

Открыть дашборд delivery (раздел «Дашборд выкладки»), переключить на «Вчера». Ожидать: плашка «SR итоговый» (8-я, фиолетовая) в «Все задачи»; блок «Воронка пайплайна» с 6 шагами + 2 жёлтыми колонками + строкой слепых зон. Сверить раскладку с макетом (вложение 36).

- [ ] **Step 6: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(wp153): фронт — плашка SR итоговый + блок Воронка пайплайна"
```

---

## Task 5: Интеграция в TG-отчёт (`daily_publish_report.js`)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/daily_publish_report.js` (require `16`; `formatMessage` `188-220`; `runDailyReport` `265-323`)

- [ ] **Step 1: Подключить модуль**

После строки 16 (`const { NOISE_CATEGORIES, ... } = require('./daily_publish_report_dict.js');`) добавить:

```js
const { computeFunnel, slotDateBoundsFromRange } = require('./pipeline_funnel.js');
```

- [ ] **Step 2: Считать воронку в `runDailyReport` и пробросить в `formatMessage`**

В `runDailyReport`, после `const report = await buildReport(pool, { startUtc, endUtc });` (строка ~295) добавить:

```js
  let funnel = null;
  if (process.env.PIPELINE_FUNNEL_ENABLED !== '0') {
    try {
      const { slotDateFrom, slotDateToExcl } = slotDateBoundsFromRange({ from: startUtc, to: endUtc });
      funnel = await computeFunnel({ pool, slotDateFrom, slotDateToExcl, filters: {} });
    } catch (e) {
      console.warn('[daily-report] funnel skipped:', e.message); // не роняем отчёт
    }
  }
```

Заменить вызов `formatMessage(report, { dateLabel, mentions, comments })` (строка ~306) на:

```js
  const text = formatMessage(report, { dateLabel, mentions, comments, funnel });
```

- [ ] **Step 3: Добавить строки воронки в `formatMessage`**

В сигнатуре `formatMessage(report, { dateLabel, mentions, comments = {} })` (строка 188) добавить `funnel = null`:

```js
function formatMessage(report, { dateLabel, mentions, comments = {}, funnel = null }) {
```

ПЕРЕД финальным блоком `if (mentions) lines.push(...)` (строка ~218) вставить блок воронки:

```js
  if (funnel && funnel.plan > 0) {
    const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
    lines.push('', `——— <b>Воронка за ${dateLabel}</b> ———`);
    lines.push(`Запланировано: ${funnel.plan}`);
    lines.push(`Выложено авто: ${funnel.auto_published}`);
    lines.push(`Выложено вручную: ${funnel.manual_published_total}`);
    lines.push(`Потеряно: ${funnel.lost_count} (${pct(funnel.lost_pct)})`);
    lines.push(`Ручная выкладка: ${pct(funnel.manual_share_pct)} от авто-задач`);
  }
```

- [ ] **Step 4: Дополнить пустую ветку (нет авто-публикаций, но воронка может быть)**

В раннем `return` при `(overall.done + overall.errors) === 0` (строки ~192-196) воронка не печатается — это приемлемо (если авто-публикаций не было, воронка почти пуста). Оставить как есть; убедиться, что блок воронки добавлен ПОСЛЕ этого раннего return (он уже после — шаг 3 вставляет в основную ветку). Проверить визуально расположение.

- [ ] **Step 5: Dry-run проверка**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm && node daily_publish_report.js --dry-run
```
Expected: печать сообщения в консоль с блоком «——— Воронка за DD.MM.YYYY ———» и строками Запланировано/Выложено авто/Выложено вручную/Потеряно/Ручная выкладка. (Отправки нет — dry-run.)

- [ ] **Step 6: Прогнать ВСЕ тесты автоварма (регрессия)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/*.test.js *.test.js 2>&1 | tail -20`
Expected: новые тесты pass; существующие не сломаны (pre-existing fails, если есть, не относятся к нашим файлам).

- [ ] **Step 7: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add daily_publish_report.js
git commit -m "feat(wp153): TG-отчёт — строки воронки (План/авто/ручная/потеряно/% ручной)"
```

---

## Task 6: Деплой и верификация

**Files:** нет (операционная задача)

- [ ] **Step 1: Подтвердить PM2-процессы**

Run: `sudo pm2 list | grep -iE "server|autowarm|daily"` — найти процесс, обслуживающий `server.js` (дашборд) и cron TG-отчёта.

- [ ] **Step 2: Убедиться, что код в проде (auto-push hook уже запушил коммиты)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && git log --oneline -6` — увидеть 4 коммита WP#153.

- [ ] **Step 3: Перезапустить сервер дашборда**

Run: `sudo pm2 restart <имя-процесса-server.js>` (имя из шага 1). Проверить логи: `sudo pm2 logs <имя> --lines 20 --nostream` — без ошибок старта.

- [ ] **Step 4: Боевой смоук эндпоинта**

Run (с прод-хоста, авторизованной сессией или внутренним curl):
```bash
curl -s 'http://localhost:<port>/api/publish-queue/dashboard?preset=yesterday' -H 'Cookie: <session>' | python3 -m json.tool | grep -A12 '"funnel"'
```
Expected: объект `funnel` с непустыми `plan/auto_published/lost_count/sr_total` и `overall.sr_total`.

- [ ] **Step 5: Верификация TG (следующий отчёт 09:50 МСК или ручной --once в нужный момент)**

Дождаться утреннего отчёта или прогнать вручную при готовности (НЕ дублировать, если уже отправлен за дату). Проверить, что блок воронки появился. Kill-switch при проблеме: `PIPELINE_FUNNEL_ENABLED=0` в env + restart.

- [ ] **Step 6: Обновить OpenProject WP #153**

Перевести в «Тестирование» (id 9), комментарий в house-style (Что было не так → Что сделано → Что осталось, без жаргона/footer).

---

## Self-Review

**Spec coverage:**
- Часть 1 (TG-отчёт строки) → Task 5. ✓
- Часть 2 (блок воронки + сноски) → Task 4 (фронт) + Task 2/3 (данные). ✓
- Часть 3 (SR итоговый) → Task 4 (плашка) + Task 3 (overall.sr_total). ✓
- Решения 1-6 из спеки: когорта slot_date (Task 2 SQL), окно «Вчера» (дефолт фронта/отчёта), уровень публикаций (Task 2), реактивный handoff (manual_handoff_at), Потеряно вычитает всю ручную (assembleFunnel), SR авто не тронут (плашка отдельная). ✓
- Слепые зоны → assembleFunnel.blind_zones + Task 4 сноски. ✓
- Kill-switch → Task 3/5. ✓
- Тесты → Task 1 (pure) + Task 2 (live) + Task 5 step 6 (регрессия). ✓

**Placeholder scan:** код приведён полностью в каждом шаге, без TBD/«добавить обработку». ✓

**Type consistency:** `assembleFunnel`/`computeFunnel`/`slotDateBoundsFromRange` — единые имена и поля (`funnel.plan`, `funnel.sr_total`, `funnel.blind_zones.*`) во всех тасках (модуль → server.js → index.html → daily_publish_report.js). ✓

**Известные приближения (задокументированы в спеке):** `before_uniq` — slot-level оценка (игнорирует platform/account/pack-фильтры); `proactive_manual_notdispatched` опирается на «грязный» `slot.manual_publish` — только для сноски, не для главных чисел.
