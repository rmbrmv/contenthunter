# WP#174 Часть B — Lifecycle View «Лог событий»: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Новый read-only раздел «Лог событий» во вкладке «Аналитика» delivery: одна строка = один ролик, с агрегированной лентой 7 этапов (+⛔), worst-state бейджем, expand по аккаунтам и таймлайн-модалкой.

**Architecture:** Read-model поверх существующих таблиц (без новой writer-таблицы). SQL делает per-content rollup (счётчики по этапам + max-дни-застревания по группам); чистые JS-функции выводят worst-state и ленту. 4 эндпоинта + раздел во фронте. Порог N — в существующей `autowarm_settings`. Зависит от Части A (колонка `code`).

**Tech Stack:** Node.js `server.js` + `pg` Pool (openclaw@localhost:5432); vanilla JS + Tailwind `public/index.html`; tests `node --test`.

**Spec:** `docs/superpowers/specs/2026-05-29-wp174-part-b-lifecycle-view-design.md`

**Repo / worktree:** `/home/claude-user/autowarm-testbench/.wt/wp174-lifecycle` (branch `wp174-lifecycle-view`, off local main `f18187f` — содержит Part A delivery-код). NEVER touch `/home/claude-user/autowarm-testbench` main checkout.

**Тесты:** `cd /home/claude-user/autowarm-testbench/.wt/wp174-lifecycle && node --test test_lifecycle_*.test.js`. Файлы тестов — в корне репо (как существующие `*.test.js`). Live-DB тесты — суффикс `_live`. **psql:** `export PGPASSWORD=<openclaw-пароль из локальной конфигурации>` (не хранить в репо).

**Grounding (проверено 29.05):**
- Auth: `requireAuth` middleware (server.js:80) — вся админка за ним; отдельный admin-чек не нужен.
- Derivation 7 этапов: `pipeline_funnel.js` (JOIN publish_queue→unic_results→unic_tasks→content; `validator_schedule_slots s` через `ut.meta->>'slot_id'`; `validator_manual_publish_queue`).
- Настройки: таблица `autowarm_settings(key,value)` + `GET/PUT /api/settings` (server.js:1118).
- Телефон: `factory_device_numbers.device_number` по `device_id = pt.device_serial`.
- Таймлайн: `publish_tasks` (попытки по `client_publish_id`), `events` JSONB, `error_code`; `publish_error_codes` для класса.
- `publish_queue` имеет: `scheduled_at, created_at, updated_at, manual_handoff_at, last_retried_at`.

---

## File Structure

| Файл | Ответственность |
|------|-----------------|
| `lifecycle.js` (**new**) | Read-model: `rollupSql()` (per-content SQL), pure `deriveWorstState(row, N)`, `deriveRibbon(row)`, `accountsSql()`, `timelineSql()` |
| `server.js` (modify) | 4 эндпоинта `/api/lifecycle*` + чтение порога из `autowarm_settings` |
| `public/index.html` (modify) | Под-раздел «Лог событий» в «Аналитике»: таблица, лента, бейдж, фильтры, sort, expand, модалка, URL-параметры, настройка порога |
| `test_lifecycle_pure.test.js` (**new**) | Unit: `deriveWorstState`/`deriveRibbon` (без БД) |
| `test_lifecycle_live.test.js` (**new**) | Live-DB: `rollupSql`/`accountsSql`/`timelineSql` возвращают корректные данные |

---

## Task 1: Порог N в autowarm_settings + helper

**Files:** Modify `server.js`. Test: `test_lifecycle_pure.test.js`.

- [ ] **Step 1: Failing test** (create `test_lifecycle_pure.test.js`):
```javascript
// test_lifecycle_pure.test.js — node --test
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { stuckDaysFromSettings } = require('./lifecycle');

test('stuckDaysFromSettings: дефолт 2 при отсутствии/мусоре', () => {
  assert.equal(stuckDaysFromSettings({}), 2);
  assert.equal(stuckDaysFromSettings({ lifecycle_stuck_days: 'abc' }), 2);
  assert.equal(stuckDaysFromSettings({ lifecycle_stuck_days: '5' }), 5);
  assert.equal(stuckDaysFromSettings({ lifecycle_stuck_days: '0' }), 2); // <1 → дефолт
});
```
- [ ] **Step 2:** `node --test test_lifecycle_pure.test.js` → FAIL (no module).
- [ ] **Step 3:** Create `lifecycle.js` with:
```javascript
// lifecycle.js — WP#174 Часть B read-model (Lifecycle View)
'use strict';

/** Порог застревания N (дней) из autowarm_settings (key=lifecycle_stuck_days). Дефолт 2. */
function stuckDaysFromSettings(settings) {
  const raw = settings && settings.lifecycle_stuck_days;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n >= 1 ? n : 2;
}

module.exports = { stuckDaysFromSettings };
```
- [ ] **Step 4:** `node --test test_lifecycle_pure.test.js` → PASS.
- [ ] **Step 5: Commit:**
```bash
cd /home/claude-user/autowarm-testbench/.wt/wp174-lifecycle
git add lifecycle.js test_lifecycle_pure.test.js
git -c user.name="Варенька" commit -m "feat(wp174-B): lifecycle.js + порог N из autowarm_settings"
```

---

## Task 2: Read-model — rollup SQL + pure derivation

**Files:** Modify `lifecycle.js`. Test: `test_lifecycle_pure.test.js` (derivation), `test_lifecycle_live.test.js` (SQL).

- [ ] **Step 1: Failing pure tests** (append to `test_lifecycle_pure.test.js`):
```javascript
const { deriveWorstState, deriveRibbon } = require('./lifecycle');

// row: счётчики этапов + max-дни по группам, total
const mk = (o) => Object.assign({
  total_accounts: 0, s_planned:0, s_uniq:0, s_autoqueue:0, s_autopub:0,
  s_manualqueue:0, s_manualinprog:0, s_published:0, s_notpublished:0,
  max_manual_days:null, max_uniq_days:null, max_stage_days:null
}, o);

test('worst-state: полностью выложен', () => {
  assert.equal(deriveWorstState(mk({total_accounts:5, s_published:5}), 2).code, 'published');
});
test('worst-state: все терминальные → не выложен', () => {
  assert.equal(deriveWorstState(mk({total_accounts:3, s_notpublished:3}), 2).code, 'not_published');
});
test('worst-state: застрял в ручной (manual > N дней)', () => {
  const w = deriveWorstState(mk({total_accounts:4, s_manualqueue:2, s_published:2, max_manual_days:3}), 2);
  assert.equal(w.code, 'stuck_manual');
});
test('worst-state: застрял на уникализации', () => {
  const w = deriveWorstState(mk({total_accounts:4, s_uniq:2, s_autopub:2, max_uniq_days:5}), 2);
  assert.equal(w.code, 'stuck_uniq');
});
test('worst-state: в работе (оба режима)', () => {
  const w = deriveWorstState(mk({total_accounts:4, s_autopub:2, s_manualqueue:2, max_manual_days:1}), 2);
  assert.equal(w.code, 'working');
  assert.equal(w.mode, 'both');
});
test('worst-state: запланирован', () => {
  assert.equal(deriveWorstState(mk({total_accounts:3, s_planned:3}), 2).code, 'planned');
});
test('ribbon: 8 сегментов + сумма = total', () => {
  const row = mk({total_accounts:10, s_autoqueue:3, s_manualqueue:2, s_published:5});
  const seg = deriveRibbon(row);
  assert.equal(seg.length, 8);
  assert.equal(seg.reduce((a,s)=>a+s.count,0), 10);
});
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** (append to `lifecycle.js`):
```javascript
const STAGES = [
  { key: 's_planned',     icon: '📅', title: 'Запланирован' },
  { key: 's_uniq',        icon: '🎬', title: 'Уникализация' },
  { key: 's_autoqueue',   icon: '🚦', title: 'Авто-очередь' },
  { key: 's_autopub',     icon: '🤖', title: 'Авто-публикация' },
  { key: 's_manualqueue', icon: '📋', title: 'В ручной очереди' },
  { key: 's_manualinprog',icon: '✋', title: 'На ручной выкладке' },
  { key: 's_published',   icon: '✅', title: 'Выложен' },
  { key: 's_notpublished',icon: '⛔', title: 'Не выложен' },
];

/** Лента: 8 сегментов {icon,title,count} по порядку этапов. */
function deriveRibbon(row) {
  return STAGES.map(s => ({ icon: s.icon, title: s.title, count: Number(row[s.key] || 0) }));
}

/** Worst-state бейдж по приоритету (см. spec B3). N — порог дней. */
function deriveWorstState(row, N) {
  const total = Number(row.total_accounts || 0);
  const pub = Number(row.s_published || 0);
  const notpub = Number(row.s_notpublished || 0);
  const planned = Number(row.s_planned || 0);
  const maxManual = row.max_manual_days == null ? null : Number(row.max_manual_days);
  const maxUniq = row.max_uniq_days == null ? null : Number(row.max_uniq_days);
  const autoActive = Number(row.s_autoqueue||0) + Number(row.s_autopub||0);
  const manualActive = Number(row.s_manualqueue||0) + Number(row.s_manualinprog||0);

  if (total > 0 && pub === total) return { code: 'published', label: 'ПОЛНОСТЬЮ ВЫЛОЖЕН' };
  if (total > 0 && notpub === total) return { code: 'not_published', label: 'НЕ ВЫЛОЖЕН' };
  if (maxManual != null && maxManual > N) return { code: 'stuck_manual', label: 'ЗАСТРЯЛ В РУЧНОЙ' };
  if (maxUniq != null && maxUniq > N) return { code: 'stuck_uniq', label: 'ЗАСТРЯЛ НА УНИКАЛИЗАЦИИ' };
  if (autoActive > 0 || manualActive > 0) {
    const mode = autoActive > 0 && manualActive > 0 ? 'both' : (autoActive > 0 ? 'auto' : 'manual');
    const sub = mode === 'both' ? 'оба' : (mode === 'auto' ? 'в авто' : 'в ручной');
    return { code: 'working', mode, label: `В РАБОТЕ (${sub})` };
  }
  if (planned > 0) return { code: 'planned', label: 'ЗАПЛАНИРОВАН' };
  return { code: 'planned', label: 'ЗАПЛАНИРОВАН' };
}

/** SQL per-content rollup. Параметры фильтра подставляются вызывающим (см. эндпоинт). */
function rollupSql() {
  return `
WITH pq_rows AS (
  SELECT
    ut.content_id AS content_id,
    CASE
      WHEN pq.status='done' OR mq.operator_status='published' OR s.matched_post_url IS NOT NULL THEN 7
      WHEN mq.operator_status='in_progress' THEN 6
      WHEN pq.manual_handoff_at IS NOT NULL THEN 5
      WHEN pq.status IN ('cancelled','skipped','past_slot_dropped') THEN 8
      WHEN pq.status IN ('running','failed') THEN 4
      WHEN pq.publish_task_id IS NOT NULL THEN 3
      WHEN ur.status IS NULL OR ur.status NOT IN ('ready','done') THEN 2
      ELSE 1
    END AS stage,
    CASE
      WHEN pq.status='done' OR mq.operator_status='published' OR s.matched_post_url IS NOT NULL THEN COALESCE(mq.published_at, pq.updated_at)
      WHEN mq.operator_status='in_progress' THEN COALESCE(mq.taken_at, pq.manual_handoff_at)
      WHEN pq.manual_handoff_at IS NOT NULL THEN pq.manual_handoff_at
      WHEN pq.status IN ('cancelled','skipped','past_slot_dropped') THEN pq.updated_at
      WHEN pq.status IN ('running','failed') THEN COALESCE(pq.last_retried_at, pq.updated_at, pq.created_at)
      WHEN pq.publish_task_id IS NOT NULL THEN COALESCE(pq.last_retried_at, pq.created_at)
      ELSE COALESCE(pq.scheduled_at, pq.created_at)
    END AS stage_since
  FROM publish_queue pq
  LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
  LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
  LEFT JOIN validator_schedule_slots s ON s.id = NULLIF(ut.meta->>'slot_id','')::int
  LEFT JOIN validator_manual_publish_queue mq
        ON mq.content_id = ut.content_id
       AND mq.account_username = pq.account_username
       AND LOWER(mq.platform) = LOWER(pq.platform)
  WHERE ut.content_id IS NOT NULL
),
rollup AS (
  SELECT
    content_id,
    COUNT(*)::int AS total_accounts,
    COUNT(*) FILTER (WHERE stage=1)::int AS s_planned,
    COUNT(*) FILTER (WHERE stage=2)::int AS s_uniq,
    COUNT(*) FILTER (WHERE stage=3)::int AS s_autoqueue,
    COUNT(*) FILTER (WHERE stage=4)::int AS s_autopub,
    COUNT(*) FILTER (WHERE stage=5)::int AS s_manualqueue,
    COUNT(*) FILTER (WHERE stage=6)::int AS s_manualinprog,
    COUNT(*) FILTER (WHERE stage=7)::int AS s_published,
    COUNT(*) FILTER (WHERE stage=8)::int AS s_notpublished,
    MAX(EXTRACT(EPOCH FROM (now()-stage_since))/86400.0) FILTER (WHERE stage NOT IN (7,8)) AS max_stage_days,
    MAX(EXTRACT(EPOCH FROM (now()-stage_since))/86400.0) FILTER (WHERE stage IN (5,6))     AS max_manual_days,
    MAX(EXTRACT(EPOCH FROM (now()-stage_since))/86400.0) FILTER (WHERE stage IN (1,2))     AS max_uniq_days
  FROM pq_rows GROUP BY content_id
)
SELECT
  r.*,
  vc.title, vc.created_at AS content_created, vc.project_id,
  vp.project AS client, vp.code_prefix, vc.code_number,
  CASE WHEN vp.code_prefix IS NOT NULL AND vc.code_number IS NOT NULL
       THEN vp.code_prefix||'-'||CASE WHEN vc.code_number<1000 THEN lpad(vc.code_number::text,3,'0') ELSE vc.code_number::text END
  END AS code,
  (SELECT MIN(s2.slot_date) FROM validator_schedule_slots s2
     WHERE s2.content_id = r.content_id) AS planned_date
FROM rollup r
JOIN validator_content vc ON vc.id = r.content_id
LEFT JOIN validator_projects vp ON vp.id = vc.project_id`;
}

module.exports = { stuckDaysFromSettings, deriveWorstState, deriveRibbon, rollupSql, STAGES };
```
> Примечание: `planned_date` берётся как минимальный `slot_date` по `validator_schedule_slots.content_id` — если этой колонки/связи нет, реализатор уточняет источник плановой даты по факту (см. Step-проверку ниже) и корректирует подзапрос; при отсутствии — `NULL`.

- [ ] **Step 4: Live-DB test** (create `test_lifecycle_live.test.js`):
```javascript
// test_lifecycle_live.test.js — node --test (живая БД)
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { rollupSql, deriveWorstState, deriveRibbon } = require('./lifecycle');
const pool = new Pool({ host:'localhost', port:5432, database:'openclaw', user:'openclaw', password:'openclaw123' });

test('rollupSql: возвращает строки, сумма сегментов = total_accounts', async () => {
  const { rows } = await pool.query(rollupSql() + ' LIMIT 50');
  assert.ok(rows.length > 0, 'есть контент с очередью');
  for (const r of rows) {
    const seg = deriveRibbon(r);
    const sum = seg.reduce((a,s)=>a+s.count,0);
    assert.equal(sum, Number(r.total_accounts), `инвариант суммы для content ${r.content_id}`);
    assert.ok(deriveWorstState(r, 2).label, 'worst-state выводится');
  }
});

test.after(() => pool.end());
```
- [ ] **Step 5:** `node --test test_lifecycle_pure.test.js test_lifecycle_live.test.js` → all PASS. (Если live-тест падает на `planned_date`/slot — скорректировать подзапрос по фактической схеме, см. примечание.)
- [ ] **Step 6: Commit:**
```bash
git add lifecycle.js test_lifecycle_pure.test.js test_lifecycle_live.test.js
git -c user.name="Варенька" commit -m "feat(wp174-B): rollup SQL + deriveWorstState/deriveRibbon (read-model)"
```

---

## Task 3: GET /api/lifecycle (список)

**Files:** Modify `server.js`. Test: `test_lifecycle_live.test.js`.

Подход: SQL делает дешёвую фильтрацию по контенту (код/клиент/заголовок/дата/платформа); worst-state и total-range фильтруются в JS (объём ~сотни строк). Сортировка по умолчанию — `max_stage_days DESC NULLS LAST`. Пагинация — offset (page/pageSize).

- [ ] **Step 1: Failing live test** (append to `test_lifecycle_live.test.js`):
```javascript
const http = require('node:http');
// лёгкий интеграционный тест эндпоинта пропускаем без поднятого сервера;
// вместо него проверяем helper фильтра/сортировки (см. ниже)
const { applyClientSideFilters } = require('./lifecycle');
test('applyClientSideFilters: фильтр по worst-state + total-range + sort default', () => {
  const rows = [
    { content_id:1, total_accounts:3, s_planned:3, max_stage_days:0.1 },
    { content_id:2, total_accounts:8, s_published:8, max_stage_days:null },
    { content_id:3, total_accounts:5, s_manualqueue:5, max_manual_days:9, max_stage_days:9 },
  ];
  const out = applyClientSideFilters(rows, { status:['stuck_manual'], total_min:1, total_max:10 }, 2);
  assert.equal(out.length, 1);
  assert.equal(out[0].content_id, 3);
});
```
- [ ] **Step 2:** run → FAIL (no `applyClientSideFilters`).
- [ ] **Step 3a:** add to `lifecycle.js` (and export):
```javascript
/** JS-фильтрация по worst-state и total-range + сортировка. rows = результат rollupSql. */
function applyClientSideFilters(rows, f, N) {
  let out = rows.map(r => ({ ...r, _worst: deriveWorstState(r, N) }));
  if (f.status && f.status.length) out = out.filter(r => f.status.includes(r._worst.code));
  if (f.total_min != null) out = out.filter(r => Number(r.total_accounts) >= f.total_min);
  if (f.total_max != null) out = out.filter(r => Number(r.total_accounts) <= f.total_max);
  const sortKey = f.sort || 'stuck';
  const dir = (f.order === 'asc') ? 1 : -1;
  const cmp = {
    stuck: (a,b) => ((a.max_stage_days||0) - (b.max_stage_days||0)),
    code: (a,b) => String(a.code||'').localeCompare(String(b.code||'')),
    client: (a,b) => String(a.client||'').localeCompare(String(b.client||'')),
    planned: (a,b) => new Date(a.planned_date||0) - new Date(b.planned_date||0),
    total: (a,b) => a.total_accounts - b.total_accounts,
    status: (a,b) => String(a._worst.label).localeCompare(String(b._worst.label)),
  }[sortKey] || ((a,b)=>0);
  out.sort((a,b) => dir * cmp(a,b));
  return out;
}
```
(export `applyClientSideFilters` in module.exports.)
- [ ] **Step 3b: Endpoint in `server.js`** — add `const lifecycle = require('./lifecycle');` near other requires, then:
```javascript
app.get('/api/lifecycle', requireAuth, async (req, res) => {
  try {
    // порог N из autowarm_settings
    const sres = await pool.query('SELECT key, value FROM autowarm_settings');
    const settings = {}; sres.rows.forEach(r => settings[r.key] = r.value);
    const N = lifecycle.stuckDaysFromSettings(settings);

    // SQL-фильтры по контенту (дешёвые)
    const conds = []; const params = [];
    const push = (sql, val) => { params.push(val); conds.push(sql.replace('$?', '$'+params.length)); };
    if (req.query.code) {
      const c = String(req.query.code).trim().toUpperCase();
      if (c.endsWith('-*')) push("vp.code_prefix = $?", c.slice(0,-2));
      else push("(vp.code_prefix||'-'||lpad(vc.code_number::text,3,'0')) = $? OR (vp.code_prefix||'-'||vc.code_number::text) = $?".replace('$?','$'+(params.length+1)).replace('$?','$'+(params.length+2)), c);
      // упрощение: если двойной bind неудобен — реализовать поиск кода через ILIKE по вычисленному code в обёртке
    }
    if (req.query.client) push("vp.project = ANY($?)", String(req.query.client).split(',').filter(Boolean));
    if (req.query.title) push("vc.title ILIKE $?", '%'+String(req.query.title)+'%');
    if (req.query.date_from) push("vc.created_at >= $?", String(req.query.date_from));
    if (req.query.date_to) push("vc.created_at < ($?::date + 1)", String(req.query.date_to));
    const where = conds.length ? ' WHERE ' + conds.join(' AND ') : '';

    const { rows } = await pool.query(lifecycle.rollupSql() + where, params);

    // platform-фильтр (есть хоть один аккаунт платформы) — отдельным under-query при необходимости; в v1 опускаем серверно
    const status = req.query.status ? String(req.query.status).split(',').filter(Boolean) : null;
    const filtered = lifecycle.applyClientSideFilters(rows, {
      status,
      total_min: req.query.total_min ? +req.query.total_min : null,
      total_max: req.query.total_max ? +req.query.total_max : null,
      sort: req.query.sort, order: req.query.order,
    }, N);

    const page = Math.max(1, +(req.query.page||1));
    const pageSize = Math.min(200, Math.max(1, +(req.query.page_size||50)));
    const total = filtered.length;
    const slice = filtered.slice((page-1)*pageSize, page*pageSize).map(r => ({
      content_id: r.content_id, code: r.code, client: r.client, title: r.title,
      planned_date: r.planned_date, total_accounts: r.total_accounts,
      worst_state: r._worst, ribbon: lifecycle.deriveRibbon(r),
      max_stage_days: r.max_stage_days == null ? null : Math.floor(Number(r.max_stage_days)),
    }));
    res.json({ rows: slice, total, page, page_size: pageSize, stuck_days: N });
  } catch (e) {
    console.error('[GET /api/lifecycle]', e);
    res.status(500).json({ error: e.message });
  }
});
```
> Реализатору: упростить code-фильтр до одного выражения — например в SQL добавить вычисляемый `code` (как в Part A) и фильтровать `code ILIKE`/`= ` через обёрточный CTE, либо фильтровать код в JS внутри `applyClientSideFilters` (добавить параметр). Выбрать чище; покрыть тестом точный код и префикс `RLM-*`.
- [ ] **Step 4: Verify** via psql (rollup returns) + run pure/live tests. Optionally smoke the endpoint on a non-prod port (`PORT=3999 node server.js &` then `curl 'localhost:3999/api/lifecycle?page_size=3'` with a session — or verify SQL directly). Report method.
- [ ] **Step 5: Commit:**
```bash
git add server.js lifecycle.js test_lifecycle_live.test.js
git -c user.name="Варenька" commit -m "feat(wp174-B): GET /api/lifecycle — список с фильтрами/сортировкой/пагинацией"
```

---

## Task 4: GET /api/lifecycle/:contentId/accounts (expand)

**Files:** Modify `lifecycle.js` (`accountsSql()`), `server.js`. Test: `test_lifecycle_live.test.js`.

- [ ] **Step 1: Failing live test** (append): запросить accounts для content_id из rollup, проверить поля (account, phone #N, platform, stage, comment).
```javascript
test('accountsSql: per-account строки с телефоном и этапом', async () => {
  const { rows: roll } = await pool.query(rollupSql() + ' ORDER BY total_accounts DESC LIMIT 1');
  if (!roll.length) return;
  const cid = roll[0].content_id;
  const { accountsSql } = require('./lifecycle');
  const { rows } = await pool.query(accountsSql(), [cid]);
  assert.ok(rows.length >= 1);
  assert.ok('account_username' in rows[0] && 'stage' in rows[0] && 'pq_id' in rows[0]);
});
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3a:** add `accountsSql()` to `lifecycle.js` (one row per publish_queue of the content, with stage + device_number + last error/operator context):
```javascript
function accountsSql() {
  return `
  SELECT
    pq.id AS pq_id, pq.account_username, pq.platform, pq.device_serial,
    fdn.device_number,
    CASE
      WHEN pq.status='done' OR mq.operator_status='published' OR s.matched_post_url IS NOT NULL THEN 7
      WHEN mq.operator_status='in_progress' THEN 6
      WHEN pq.manual_handoff_at IS NOT NULL THEN 5
      WHEN pq.status IN ('cancelled','skipped','past_slot_dropped') THEN 8
      WHEN pq.status IN ('running','failed') THEN 4
      WHEN pq.publish_task_id IS NOT NULL THEN 3
      WHEN ur.status IS NULL OR ur.status NOT IN ('ready','done') THEN 2
      ELSE 1
    END AS stage,
    GREATEST(pq.updated_at, pq.manual_handoff_at, mq.taken_at, mq.published_at, pq.scheduled_at, pq.created_at) AS action_at,
    pt.error_code, pt.status AS task_status, mq.operator_status,
    mq.taken_by_id, pq.last_retry_reason
  FROM publish_queue pq
  LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
  LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
  LEFT JOIN validator_schedule_slots s ON s.id = NULLIF(ut.meta->>'slot_id','')::int
  LEFT JOIN validator_manual_publish_queue mq
        ON mq.content_id = ut.content_id AND mq.account_username = pq.account_username
       AND LOWER(mq.platform)=LOWER(pq.platform)
  LEFT JOIN factory_device_numbers fdn ON fdn.device_id = pq.device_serial
  LEFT JOIN publish_tasks pt ON pt.id = pq.publish_task_id
  WHERE ut.content_id = $1
  ORDER BY pq.platform, pq.account_username`;
}
```
- [ ] **Step 3b: Endpoint:**
```javascript
app.get('/api/lifecycle/:contentId/accounts', requireAuth, async (req, res) => {
  try {
    const { rows } = await pool.query(lifecycle.accountsSql(), [+req.params.contentId]);
    const STAGE_TITLES = lifecycle.STAGES.map(s => s.title); // index by stage-1
    res.json(rows.map(r => ({
      pq_id: r.pq_id, account: '@'+(r.account_username||''),
      phone: r.device_number ? ('#'+r.device_number) : '—',
      platform: r.platform, stage: r.stage,
      stage_title: STAGE_TITLES[r.stage-1] || '',
      action_at: r.action_at,
      error_code: r.error_code, task_status: r.task_status,
      operator_status: r.operator_status, last_retry_reason: r.last_retry_reason,
    })));
  } catch (e) { console.error('[GET /api/lifecycle/accounts]', e); res.status(500).json({ error: e.message }); }
});
```
- [ ] **Step 4:** run live tests → PASS.
- [ ] **Step 5: Commit** `feat(wp174-B): GET /api/lifecycle/:id/accounts — mini-breakdown`.

---

## Task 5: GET /api/lifecycle/account/:pqId/timeline (модалка)

**Files:** Modify `lifecycle.js` (`timelineSql()` + `buildTimeline()` pure), `server.js`. Test: both.

- [ ] **Step 1: Failing pure test** for `buildTimeline` (append to pure test) — собирает точки из таймстампов + попыток:
```javascript
const { buildTimeline } = require('./lifecycle');
test('buildTimeline: точки в порядке + текущая помечена', () => {
  const pq = { scheduled_at:'2026-05-25T09:00:00Z', manual_handoff_at:null, status:'failed', created_at:'2026-05-25T09:15:00Z', last_retried_at:'2026-05-28T09:12:00Z' };
  const attempts = [
    { created_at:'2026-05-27T18:00:00Z', error_code:'captcha_required' },
    { created_at:'2026-05-28T09:12:00Z', error_code:'ui_changed' },
  ];
  const mq = null;
  const pts = buildTimeline({ pq, attempts, mq });
  assert.ok(pts.length >= 3);
  assert.equal(pts[pts.length-1].current, true); // последняя = текущее состояние
});
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3a:** add `buildTimeline({pq, attempts, mq})` (pure) to `lifecycle.js`:
```javascript
function buildTimeline({ pq, attempts, mq }) {
  const pts = [];
  if (pq.scheduled_at || pq.created_at) pts.push({ at: pq.scheduled_at || pq.created_at, stage:'📅 Запланирован', ctx:'' });
  (attempts||[]).forEach((a, i) => pts.push({
    at: a.created_at, stage:'🤖 Авто-публикация',
    ctx: `попытка №${i+1}` + (a.error_code ? ` · ошибка ${a.error_code}` : ''),
  }));
  if (pq.manual_handoff_at) pts.push({ at: pq.manual_handoff_at, stage:'📋 Передан в ручную', ctx:'' });
  if (mq && mq.taken_at) pts.push({ at: mq.taken_at, stage:'✋ На ручной выкладке', ctx: mq.taken_by_id ? ('оператор #'+mq.taken_by_id) : '' });
  if (mq && mq.published_at) pts.push({ at: mq.published_at, stage:'✅ Выложен', ctx:'' });
  else if (pq.status==='done') pts.push({ at: pq.updated_at, stage:'✅ Выложен', ctx:'авто' });
  pts.sort((a,b) => new Date(a.at||0) - new Date(b.at||0));
  if (pts.length) pts[pts.length-1].current = true;
  return pts;
}
```
(export it.)
- [ ] **Step 3b:** add `timelineSql()` (fetch pq + mq + attempts) and endpoint:
```javascript
function timelineSql() {
  return `
  SELECT pq.id, pq.scheduled_at, pq.created_at, pq.updated_at, pq.manual_handoff_at,
         pq.last_retried_at, pq.status, pq.client_publish_id, ut.content_id, pq.account_username, pq.platform
  FROM publish_queue pq
  LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
  LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
  WHERE pq.id = $1`;
}
```
Endpoint:
```javascript
app.get('/api/lifecycle/account/:pqId/timeline', requireAuth, async (req, res) => {
  try {
    const { rows } = await pool.query(lifecycle.timelineSql(), [+req.params.pqId]);
    if (!rows.length) return res.status(404).json({ error: 'Не найдено' });
    const pq = rows[0];
    const att = pq.client_publish_id ? (await pool.query(
      'SELECT created_at, error_code, status FROM publish_tasks WHERE client_publish_id=$1 ORDER BY created_at ASC',
      [pq.client_publish_id])).rows : [];
    const mqr = (await pool.query(
      `SELECT taken_at, taken_by_id, published_at, operator_status FROM validator_manual_publish_queue
       WHERE content_id=$1 AND account_username=$2 AND LOWER(platform)=LOWER($3) LIMIT 1`,
      [pq.content_id, pq.account_username, pq.platform])).rows[0] || null;
    res.json({ points: lifecycle.buildTimeline({ pq, attempts: att, mq: mqr }) });
  } catch (e) { console.error('[GET /api/lifecycle/timeline]', e); res.status(500).json({ error: e.message }); }
});
```
- [ ] **Step 4:** run pure + live tests → PASS (live: pick a pq_id from accounts, expect points array).
- [ ] **Step 5: Commit** `feat(wp174-B): GET /api/lifecycle/account/:pqId/timeline`.

---

## Task 6: Frontend — раздел «Лог событий» (таблица/лента/бейдж/фильтры/сортировка)

**Files:** Modify `public/index.html`.

- [ ] **Step 1: Sub-section container.** В `#section-analytics` (после summary-cards, ~index.html:3760) добавить под-раздел с переключателем «Аналитика / Лог событий» и контейнером:
```html
<div class="flex gap-2 mb-4">
  <button id="lc-tab-analytics" onclick="lcShowSub('analytics')" class="px-3 py-1.5 rounded-lg text-sm">Метрики</button>
  <button id="lc-tab-lifecycle" onclick="lcShowSub('lifecycle')" class="px-3 py-1.5 rounded-lg text-sm">📜 Лог событий</button>
</div>
<div id="lc-sub-lifecycle" class="hidden">
  <div id="lc-platform-filter" class="mb-3 flex gap-2 text-sm"></div>
  <div class="overflow-x-auto bg-white rounded-2xl border border-gray-100">
    <table class="w-full text-sm">
      <thead id="lc-thead"></thead>
      <tbody id="lc-tbody"><tr><td class="p-4 text-gray-400">Загрузка…</td></tr></tbody>
    </table>
  </div>
  <div id="lc-pager" class="mt-3 flex items-center gap-2 text-sm"></div>
</div>
```
- [ ] **Step 2: JS — sub-tab toggle + load.** Add functions:
```javascript
let lcState = { page:1, page_size:50, sort:'stuck', order:'desc', filters:{} };
function lcShowSub(which) {
  document.getElementById('lc-sub-lifecycle').classList.toggle('hidden', which!=='lifecycle');
  // (analytics существующий контент — оставить видимым/скрыть по аналогии)
  if (which==='lifecycle') loadLifecycle();
}
async function loadLifecycle() {
  const q = new URLSearchParams();
  q.set('page', lcState.page); q.set('page_size', lcState.page_size);
  q.set('sort', lcState.sort); q.set('order', lcState.order);
  Object.entries(lcState.filters).forEach(([k,v]) => { if (v!=null && v!=='') q.set(k, v); });
  const r = await fetch('/api/lifecycle?'+q.toString());
  const data = await r.json();
  lcRenderHead(); lcRenderRows(data.rows); lcRenderPager(data);
}
```
- [ ] **Step 3: Render head + filter row + rows + ribbon + badge.**
```javascript
const LC_BADGE = { published:'bg-green-100 text-green-700', not_published:'bg-gray-200 text-gray-600',
  stuck_manual:'bg-red-100 text-red-700', stuck_uniq:'bg-orange-100 text-orange-700',
  working:'bg-blue-100 text-blue-700', planned:'bg-gray-100 text-gray-500' };
function lcRibbon(seg) {
  return '<div class="flex items-center gap-1">' + seg.map(s =>
    `<span title="${esc(s.title)}: ${s.count}" class="${s.count>0?'':'opacity-40'} text-xs whitespace-nowrap">${s.icon}${s.count}</span>`
  ).join('<span class="text-gray-200">|</span>') + '</div>';
}
function lcRenderRows(rows) {
  const tb = document.getElementById('lc-tbody');
  if (!rows.length) { tb.innerHTML = '<tr><td class="p-4 text-gray-400" colspan="7">Нет данных</td></tr>'; return; }
  tb.innerHTML = rows.map(r => `
    <tr class="border-t hover:bg-gray-50 cursor-pointer" onclick="lcToggleExpand(${r.content_id}, this)">
      <td class="px-3 py-2 font-mono text-xs">${r.code ? `<button onclick="event.stopPropagation();navigator.clipboard.writeText('${esc(r.code)}').then(()=>toast('Код скопирован','success'))" class="text-indigo-600 hover:underline">${esc(r.code)}</button>` : '—'}</td>
      <td class="px-3 py-2">${esc(r.client||'')}</td>
      <td class="px-3 py-2">${esc(r.title||'')}</td>
      <td class="px-3 py-2 whitespace-nowrap">${r.planned_date ? new Date(r.planned_date).toLocaleDateString('ru') : '—'}</td>
      <td class="px-3 py-2 text-center">${r.total_accounts}</td>
      <td class="px-3 py-2"><span class="px-2 py-0.5 rounded-full text-xs ${LC_BADGE[r.worst_state.code]||''}">${esc(r.worst_state.label)}</span></td>
      <td class="px-3 py-2">${lcRibbon(r.ribbon)}</td>
    </tr>
    <tr id="lc-exp-${r.content_id}" class="hidden"><td colspan="7" class="px-3 py-2 bg-gray-50"></td></tr>
  `).join('');
}
function lcRenderHead() {
  const cols = [['code','Код'],['client','Клиент'],['title','Заголовок'],['planned','План.дата'],['total','Всего'],['status','Статус'],['','Лента этапов']];
  document.getElementById('lc-thead').innerHTML = '<tr class="text-left text-xs text-gray-500">' +
    cols.map(([k,t]) => `<th class="px-3 py-2 ${k?'cursor-pointer':''}" ${k?`onclick="lcSort('${k}')"`:''}>${t}${k&&lcState.sort===k?(lcState.order==='asc'?' ▲':' ▼'):''}</th>`).join('') + '</tr>' +
    lcFilterRow();
}
function lcSort(k){ if(lcState.sort===k) lcState.order=lcState.order==='asc'?'desc':'asc'; else {lcState.sort=k;lcState.order='desc';} lcState.page=1; loadLifecycle(); }
```
- [ ] **Step 4: Filter row** (`lcFilterRow()` returns a `<tr>` with inputs under columns: code text, client multi (simple text csv in v1), title text, date range, total-range select, status multi-select) wired to `lcState.filters` + `loadLifecycle()` on change (debounced for text). Platform filter rendered into `#lc-platform-filter`. Provide concrete inputs; on change update `lcState.filters` keys: `code,client,title,date_from,date_to,total_min,total_max,status`.
- [ ] **Step 5: Pager** (`lcRenderPager(data)`): prev/next + «N всего», updates `lcState.page`.
- [ ] **Step 6: URL params** — on `loadLifecycle`/`switchModule('analytics')`, read `?stage=&blind_zone=&client=&code=` from `location.search` into `lcState.filters` (prefill) once. (Drill-down сам — отдельной задачей; здесь только приём параметров.)
- [ ] **Step 7: Verify** — `node --check`-эквивалента для html нет; перечитать функции глазами, сбалансировать кавычки/теги. Если можно поднять сервер на тест-порту — открыть раздел и убедиться: таблица грузится, лента/бейдж рендерятся, sort/фильтры дёргают `/api/lifecycle`. Report method.
- [ ] **Step 8: Commit** `feat(wp174-B): фронт раздел «Лог событий» — таблица/лента/бейдж/фильтры/сортировка`.

---

## Task 7: Frontend — expand (mini-breakdown) + timeline-модалка + настройка порога

**Files:** Modify `public/index.html`.

- [ ] **Step 1: Expand.** `lcToggleExpand(contentId, trEl)` — fetch `/api/lifecycle/${id}/accounts`, рендерит в строку `#lc-exp-${id}` таблицу 6 колонок (Аккаунт / Телефон #N / Платформа иконка / Дата действия ДД.ММ ЧЧ:ММ / Комментарий этапа / «📜 Лог аккаунта»). Toggle hidden; несколько строк могут быть открыты. Платформа-иконка: 🎵 tiktok / 📷 instagram / ▶️ youtube. Комментарий = `stage_title` + контекст (`error_code`/`operator`/`last_retry_reason`) без даты.
```javascript
const LC_PLAT = { tiktok:'🎵', instagram:'📷', youtube:'▶️' };
async function lcToggleExpand(id, trEl) {
  const exp = document.getElementById('lc-exp-'+id);
  if (!exp.classList.contains('hidden')) { exp.classList.add('hidden'); return; }
  exp.classList.remove('hidden');
  const cell = exp.firstElementChild;
  cell.innerHTML = 'Загрузка…';
  const r = await fetch(`/api/lifecycle/${id}/accounts`); const accs = await r.json();
  cell.innerHTML = `<table class="w-full text-xs"><tbody>` + accs.map(a => {
    const dt = a.action_at ? new Date(a.action_at).toLocaleString('ru',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
    const ctx = [a.error_code?('ошибка '+a.error_code):'', a.operator_status||'', a.last_retry_reason||''].filter(Boolean).join(' · ');
    return `<tr class="border-t">
      <td class="py-1 pr-3">${esc(a.account)}</td>
      <td class="py-1 pr-3 text-gray-500">${esc(a.phone)}</td>
      <td class="py-1 pr-3">${LC_PLAT[(a.platform||'').toLowerCase()]||''} ${esc(a.platform||'')}</td>
      <td class="py-1 pr-3 whitespace-nowrap">${dt}</td>
      <td class="py-1 pr-3">${esc(a.stage_title)}${ctx?(' · '+esc(ctx)):''}</td>
      <td class="py-1"><button onclick="event.stopPropagation();lcTimeline(${a.pq_id})" class="text-indigo-600 hover:underline">📜 Лог</button></td>
    </tr>`; }).join('') + `</tbody></table>`;
}
```
- [ ] **Step 2: Timeline modal.** `lcTimeline(pqId)` — fetch `/api/lifecycle/account/${pqId}/timeline`, открыть модалку (reuse существующий modal-механизм если есть; иначе простой overlay div) со списком точек: `время → этап → контекст`, текущая (`current:true`) — жёлтый маркер + плашка «сейчас».
```javascript
async function lcTimeline(pqId) {
  const r = await fetch(`/api/lifecycle/account/${pqId}/timeline`); const { points } = await r.json();
  const html = points.map(p => `
    <div class="flex gap-2 py-1 ${p.current?'bg-yellow-50 rounded px-2':''}">
      <span class="text-gray-400 whitespace-nowrap text-xs">${p.at?new Date(p.at).toLocaleString('ru',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):''}</span>
      <span>${esc(p.stage)}</span><span class="text-gray-500 text-xs">${esc(p.ctx||'')}</span>
      ${p.current?'<span class="ml-2 text-xs bg-yellow-300 px-1.5 rounded">сейчас</span>':''}
    </div>`).join('');
  lcOpenModal('📜 Лог аккаунта', html); // реализовать lcOpenModal как простой overlay (или reuse существующего)
}
```
- [ ] **Step 3: Threshold setting UI.** В разделе добавить маленький контрол «Порог застревания (дней): [input] [Сохранить]» — читает текущее `stuck_days` (из ответа `/api/lifecycle`), сохраняет через `PUT /api/settings` body `{lifecycle_stuck_days: <n>}`, затем `loadLifecycle()`.
```javascript
async function lcSaveStuckDays(v) {
  await fetch('/api/settings', { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ lifecycle_stuck_days: String(v) }) });
  toast('Порог сохранён','success'); loadLifecycle();
}
```
- [ ] **Step 4: Verify** — перечитать функции; при возможности поднять сервер на тест-порту и проверить expand + модалку + сохранение порога. Report method.
- [ ] **Step 5: Commit** `feat(wp174-B): expand + timeline-модалка + настройка порога застревания`.

---

## Финал Части B

- [ ] **Все тесты:** `node --test test_lifecycle_pure.test.js test_lifecycle_live.test.js` → PASS.
- [ ] **Регрессия:** `node --test test_pipeline_funnel.test.js test_phone_status_pure.test.js` → без новых падений; `node --check server.js`.
- [ ] **Codex review** диффа Части B, раундами до 0 P1.
- [ ] **Деплой:** код delivery → прод (pull + PM2 restart). Новой миграции нет (autowarm_settings + колонки Part A уже на проде после деплоя A). Зависит от деплоя Части A.
- [ ] **OpenProject #174** — комментарий о Части B; статус по решению Данила.

---

## Self-Review (выполнено при написании)

- **Покрытие spec B0–B12:** B0 архитектура→read-model lifecycle.js; B1 гранулярность→rollupSql (content_id); B2 derivation 7+⛔→CASE в rollupSql/accountsSql; B3 worst-state→deriveWorstState (Task 2); B4 таблица→Task 6; B5 лента→deriveRibbon/lcRibbon; B6 expand→Task 4+7; B7 timeline→Task 5+7; B8 sort/фильтры→applyClientSideFilters+Task 6; B9 порог N→Task 1+7 (autowarm_settings); B10 URL-параметры→Task 6 Step 6; B11 производительность→rollup на лету (~сотни строк); B12 тесты→встроены.
- **Плейсхолдеры:** SQL и pure-JS приведены полностью; фронт-задачи дают конкретный код + точки вставки (UI по природе менее TDD-able — отмечено).
- **Консистентность:** `deriveWorstState/deriveRibbon/rollupSql/accountsSql/timelineSql/buildTimeline/applyClientSideFilters/stuckDaysFromSettings/STAGES` — единый модуль `lifecycle.js`; имена этапов/коды бейджа едины между бэком и фронтом.
- **Открытый момент для реализатора:** источник `planned_date` (validator_schedule_slots.content_id) — проверить по факту схемы; code-фильтр упростить (один из двух путей). Помечено в тасках.
