# WP #107 — «Ручная выкладка» в delivery: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести операторский UI «Ручная выкладка» из админки валидатора в delivery-дашборд (autowarm, раздел «Выкладка»), переиспользуя таблицу `validator_manual_publish_queue` и логику переходов; подключить мёртвый наполнитель очереди; удалить валидаторную копию.

**Architecture:** Delivery-фронт (vanilla JS в `public/index.html`) ↔ новые эндпоинты autowarm `server.js` (под `requireAuth`) ↔ общая таблица `validator_manual_publish_queue` (openclaw, без изменений схемы). Логика очереди вынесена в тестируемый модуль `manual_publish_queue.js` (только `pool.query`, атомарные условные UPDATE). Наполнитель `assignManualPublishQueue` подключается в шедулер.

**Tech Stack:** Node.js + Express + `pg` (autowarm); vanilla JS + Tailwind (`public/index.html`); `node --test` (mock-pool); Vue 3 + TS (валидатор — только удаление).

**Repos / branches:**
- autowarm = `/root/.openclaw/workspace-genri/autowarm` (origin `GenGo2/delivery-contenthunter`, есть post-commit auto-push hook). Ветка: `feat/wp107-manual-publish-delivery`.
- validator = `/home/claude-user/validator-contenthunter` (origin `GenGo2/validator-contenthunter`). Ветка: `chore/wp107-remove-validator-manual-publish`.

**Спек:** `docs/superpowers/specs/2026-05-21-wp107-manual-publish-delivery-design.md`.

**Известный риск (mock-drift):** autowarm-тесты мокают `pool.query` по regex SQL — они НЕ ловят расхождение SQL с реальной схемой (см. инцидент PR #52). Поэтому Task 8 содержит обязательный live-smoke через curl против реальной БД.

---

## File Structure

| Файл | Репо | Ответственность |
|---|---|---|
| `manual_publish_queue.js` (Create) | autowarm | Чистая логика очереди: `accountUrl`, `rowToDict`, `JOINED_SELECT`, `listQueue`, `getItem`, переходы `takeItem/returnItem/markPublished/reworkItem`, `httpErr`. Только `pool.query`. |
| `tests/test_manual_publish_queue.test.js` (Create) | autowarm | `node --test` mock-pool: сериализатор, account_url, переходы, коды ошибок. |
| `server.js` (Modify) | autowarm | Express-эндпоинты `/api/publishing/manual-queue*` (тонкие обёртки над модулем) + wiring `assignManualPublishQueue` в шедулер. |
| `public/index.html` (Modify) | autowarm | Пункт сайдбара + секция + рендер/фетч таблицы + модалка-карточка. |
| `tests/wp107.spec.cjs`-нет | — | Фронт-харнесса нет → фронт = implement + manual smoke. |
| validator: `ManualPublishingQueue.vue`, `PublicationCard.vue`, `useManualPublishTable.ts`, `manualPublish.ts`, `manual_publish.py` (Delete) | validator | Удаление валидаторной копии. |
| validator: `router/index.ts`, `AppSidebar.vue`, `main.py`, `manual_publish_service.py` (Modify) | validator | Снять роут/пункт/роутер; оставить `cancel_queued_for_slot` + toggle-хук. |

---

## Task 1: Модуль `manual_publish_queue.js` — сериализатор и чтение

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/manual_publish_queue.js`
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_manual_publish_queue.test.js`

- [ ] **Step 1: Создать ветку**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin && git checkout -b feat/wp107-manual-publish-delivery origin/main
```
Expected: `Switched to a new branch`.

- [ ] **Step 2: Написать падающий тест (account_url + rowToDict + listQueue/getItem)**

Create `tests/test_manual_publish_queue.test.js`:
```js
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const mpq = require('../manual_publish_queue');

test('accountUrl per platform, strips @', () => {
  assert.strictEqual(mpq.accountUrl('instagram', '@bob'), 'https://instagram.com/bob');
  assert.strictEqual(mpq.accountUrl('tiktok', 'bob'), 'https://www.tiktok.com/@bob');
  assert.strictEqual(mpq.accountUrl('youtube', 'bob'), 'https://www.youtube.com/@bob');
  assert.strictEqual(mpq.accountUrl('vk', 'bob'), null);
  assert.strictEqual(mpq.accountUrl('instagram', null), null);
});

test('rowToDict maps fields + derived publication', () => {
  const d = mpq.rowToDict({
    id: 1, slot_id: 9, content_id: 2, scheme_id: 12, project_id: 5, project_name: 'P',
    pack_id: 7, pack_name: 'Pk', account_username: 'bob', platform: 'instagram',
    phone_number: 19, device_serial: 'S', planned_date: '2026-05-21', operator_status: 'queued',
    title: 'T', description: 'D', hashtags: null, geo: 'G',
    source_video_url: 'src', unic_video_url: 'unic',
    post_url: null, matched_post_url: 'http://m', published_at: null, matched_at: '2026-05-21T10:00:00Z',
  });
  assert.strictEqual(d.account_url, 'https://instagram.com/bob');
  assert.deepStrictEqual(d.hashtags, []);
  assert.strictEqual(d.publication_url, 'http://m');     // post_url ?? matched_post_url
  assert.strictEqual(d.publication_at, '2026-05-21T10:00:00Z');
});

// mock pool: pattern-match SQL; поддерживает connect() для транзакций (BEGIN/COMMIT/ROLLBACK no-op)
function makePool(handlers) {
  const q = async (sql, params) => {
    if (/^\s*(BEGIN|COMMIT|ROLLBACK)/i.test(sql)) return { rows: [] };
    for (const [re, fn] of handlers) if (re.test(sql)) return fn(params);
    throw new Error('unexpected SQL: ' + sql);
  };
  return { query: q, connect: async () => ({ query: q, release() {} }) };
}
const QROW = { id: 1, slot_id: 9, content_id: 2, scheme_id: 12, project_id: 5, project_name: 'P',
  pack_id: 7, pack_name: 'Pk', account_username: 'bob', platform: 'instagram', phone_number: 19,
  device_serial: 'S', planned_date: '2026-05-21', operator_status: 'queued', title: 'T',
  description: 'D', hashtags: ['a'], geo: 'G', source_video_url: 'src', unic_video_url: 'unic',
  post_url: null, matched_post_url: null, published_at: null, matched_at: null };

test('listQueue returns serialized rows', async () => {
  const pool = makePool([[/FROM validator_manual_publish_queue q/, () => ({ rows: [QROW] })]]);
  const out = await mpq.listQueue(pool, null);
  assert.strictEqual(out.length, 1);
  assert.strictEqual(out[0].account_url, 'https://instagram.com/bob');
});

test('getItem 404 when missing', async () => {
  const pool = makePool([[/FROM validator_manual_publish_queue q/, () => ({ rows: [] })]]);
  await assert.rejects(() => mpq.getItem(pool, 999), e => e.httpStatus === 404);
});
```

- [ ] **Step 3: Запустить — убедиться, что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test tests/test_manual_publish_queue.test.js`
Expected: FAIL — `Cannot find module '../manual_publish_queue'`.

- [ ] **Step 4: Реализовать модуль (чтение)**

Create `manual_publish_queue.js`:
```js
'use strict';

function httpErr(status, message) {
  return Object.assign(new Error(message), { httpStatus: status });
}

function accountUrl(platform, username) {
  if (!username) return null;
  const u = String(username).replace(/^@+/, '');
  switch ((platform || '').toLowerCase()) {
    case 'instagram': return `https://instagram.com/${u}`;
    case 'tiktok':    return `https://www.tiktok.com/@${u}`;
    case 'youtube':   return `https://www.youtube.com/@${u}`;
    default:          return null;
  }
}

function rowToDict(m) {
  const pub = m.post_url || m.matched_post_url || null;
  const pubAt = m.published_at || m.matched_at || null;
  return {
    id: m.id, slot_id: m.slot_id, content_id: m.content_id, scheme_id: m.scheme_id,
    project_id: m.project_id, project_name: m.project_name,
    pack_id: m.pack_id, pack_name: m.pack_name,
    account_username: m.account_username, platform: m.platform,
    account_url: accountUrl(m.platform, m.account_username),
    phone_number: m.phone_number, device_serial: m.device_serial,
    planned_date: m.planned_date, operator_status: m.operator_status,
    title: m.title, description: m.description, hashtags: m.hashtags || [], geo: m.geo,
    source_video_url: m.source_video_url, unic_video_url: m.unic_video_url,
    post_url: m.post_url, matched_post_url: m.matched_post_url,
    published_at: m.published_at, matched_at: m.matched_at,
    publication_url: pub, publication_at: pubAt,
  };
}

const JOINED_SELECT = `
  SELECT q.id, q.slot_id, q.content_id, q.scheme_id, q.project_id, q.project_name,
         q.pack_id, q.pack_name, q.account_username, q.platform, q.phone_number,
         q.device_serial, q.planned_date, q.operator_status, q.post_url, q.published_at,
         vc.title, vc.description, vc.hashtags, vc.geo,
         vc.s3_url       AS source_video_url,
         ur.output_url   AS unic_video_url,
         s.matched_post_url, s.matched_at
  FROM validator_manual_publish_queue q
  LEFT JOIN validator_content vc        ON vc.id = q.content_id
  LEFT JOIN unic_results ur             ON ur.id = q.unic_result_id
  LEFT JOIN validator_schedule_slots s  ON s.id  = q.slot_id
`;

async function listQueue(pool, status = null) {
  const sql = JOINED_SELECT + `
    WHERE q.cancelled_at IS NULL
      AND ($1::text IS NULL OR q.operator_status = $1)
    ORDER BY q.planned_date ASC, q.phone_number ASC, q.id ASC`;
  const { rows } = await pool.query(sql, [status]);
  return rows.map(rowToDict);
}

async function getItem(pool, id) {
  const { rows } = await pool.query(JOINED_SELECT + ` WHERE q.id = $1`, [id]);
  if (!rows.length) throw httpErr(404, 'Queue item not found');
  return rowToDict(rows[0]);
}

module.exports = { httpErr, accountUrl, rowToDict, JOINED_SELECT, listQueue, getItem };
```

- [ ] **Step 5: Запустить — убедиться, что зелёный**

Run: `node --test tests/test_manual_publish_queue.test.js`
Expected: PASS (5 tests).

- [ ] **Step 6: Коммит**

```bash
git add manual_publish_queue.js tests/test_manual_publish_queue.test.js
git commit -m "feat(wp107): manual_publish_queue module — serializer + read (delivery)"
```

---

## Task 2: Переходы статусов в модуле

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/manual_publish_queue.js`
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_manual_publish_queue.test.js`

- [ ] **Step 1: Дописать падающие тесты переходов**

Append to `tests/test_manual_publish_queue.test.js`:
```js
// helper: mock that serves an UPDATE result, then a JOINED_SELECT for getItem
function transitionPool({ updateRows, rawRow, slotCapture }) {
  return makePool([
    [/^\s*UPDATE validator_manual_publish_queue/, () => ({ rows: updateRows })],
    [/UPDATE validator_schedule_slots/, (p) => { if (slotCapture) slotCapture.push(p); return { rows: [] }; }],
    [/SELECT operator_status, cancelled_at/, () => ({ rows: rawRow ? [rawRow] : [] })],
    [/FROM validator_manual_publish_queue q/, () => ({ rows: [{ ...QROW, operator_status: 'in_progress' }] })],
  ]);
}

test('takeItem: queued -> in_progress', async () => {
  const out = await mpq.takeItem(transitionPool({ updateRows: [{ id: 1 }] }), 1);
  assert.strictEqual(out.operator_status, 'in_progress');
});

test('takeItem: 409 when not queued', async () => {
  const pool = transitionPool({ updateRows: [], rawRow: { operator_status: 'in_progress', cancelled_at: null } });
  await assert.rejects(() => mpq.takeItem(pool, 1), e => e.httpStatus === 409);
});

test('takeItem: 404 when row missing', async () => {
  const pool = transitionPool({ updateRows: [], rawRow: null });
  await assert.rejects(() => mpq.takeItem(pool, 1), e => e.httpStatus === 404);
});

test('takeItem: 409 when cancelled', async () => {
  const pool = transitionPool({ updateRows: [], rawRow: { operator_status: 'queued', cancelled_at: '2026-05-21' } });
  await assert.rejects(() => mpq.takeItem(pool, 1), e => e.httpStatus === 409);
});

test('markPublished: 422 without date/url', async () => {
  await assert.rejects(() => mpq.markPublished(makePool([]), 1, { publishedAt: null, postUrl: 'x' }),
    e => e.httpStatus === 422);
  await assert.rejects(() => mpq.markPublished(makePool([]), 1, { publishedAt: 'x', postUrl: '' }),
    e => e.httpStatus === 422);
});

test('markPublished: stamps slot.matched_post_url', async () => {
  const slotCapture = [];
  const pool = transitionPool({ updateRows: [{ slot_id: 9 }], slotCapture });
  await mpq.markPublished(pool, 1, { publishedAt: '2026-05-21T10:00:00Z', postUrl: 'http://p' });
  assert.deepStrictEqual(slotCapture[0], ['http://p', '2026-05-21T10:00:00Z', 9]);
});

test('reworkItem: published -> queued, clears slot stamp only for operator url', async () => {
  const slotCapture = [];
  const pool = makePool([
    [/SELECT slot_id, post_url FROM validator_manual_publish_queue/, () => ({ rows: [{ slot_id: 9, post_url: 'http://old' }] })],
    [/^\s*UPDATE validator_manual_publish_queue/, () => ({ rows: [{ slot_id: 9 }] })],
    [/UPDATE validator_schedule_slots/, (p) => { slotCapture.push(p); return { rows: [] }; }],
    [/FROM validator_manual_publish_queue q/, () => ({ rows: [{ ...QROW, operator_status: 'queued' }] })],
  ]);
  const out = await mpq.reworkItem(pool, 1);
  assert.strictEqual(out.operator_status, 'queued');
  assert.deepStrictEqual(slotCapture[0], [9, 'http://old']); // slot_id, oldUrl
});

test('reworkItem: 409 when not published', async () => {
  const pool = makePool([
    [/SELECT slot_id, post_url FROM validator_manual_publish_queue/, () => ({ rows: [{ slot_id: 9, post_url: null }] })],
    [/^\s*UPDATE validator_manual_publish_queue/, () => ({ rows: [] })],
    [/SELECT operator_status, cancelled_at/, () => ({ rows: [{ operator_status: 'queued', cancelled_at: null }] })],
  ]);
  await assert.rejects(() => mpq.reworkItem(pool, 1), e => e.httpStatus === 409);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test tests/test_manual_publish_queue.test.js`
Expected: FAIL — `mpq.takeItem is not a function`.

- [ ] **Step 3: Реализовать переходы**

Add to `manual_publish_queue.js` before `module.exports` (and extend exports):
```js
async function failTransition(pool, id, expected) {
  const { rows } = await pool.query(
    'SELECT operator_status, cancelled_at FROM validator_manual_publish_queue WHERE id = $1', [id]);
  if (!rows.length) throw httpErr(404, 'Queue item not found');
  if (rows[0].cancelled_at) throw httpErr(409, 'Queue item is cancelled');
  throw httpErr(409, `Expected status '${expected}', got '${rows[0].operator_status}'`);
}

async function takeItem(pool, id) {
  const { rows } = await pool.query(`
    UPDATE validator_manual_publish_queue
    SET operator_status='in_progress', taken_at=now(), updated_at=now()
    WHERE id=$1 AND operator_status='queued' AND cancelled_at IS NULL
    RETURNING id`, [id]);
  if (!rows.length) await failTransition(pool, id, 'queued');
  return getItem(pool, id);
}

async function returnItem(pool, id) {
  const { rows } = await pool.query(`
    UPDATE validator_manual_publish_queue
    SET operator_status='queued', taken_at=NULL, updated_at=now()
    WHERE id=$1 AND operator_status='in_progress' AND cancelled_at IS NULL
    RETURNING id`, [id]);
  if (!rows.length) await failTransition(pool, id, 'in_progress');
  return getItem(pool, id);
}

// multi-table переходы (queue + slot) — в ОДНОЙ транзакции (атомарность при краше)
async function withTx(pool, fn) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const r = await fn(client);
    await client.query('COMMIT');
    return r;
  } catch (e) {
    try { await client.query('ROLLBACK'); } catch (_) {}
    throw e;
  } finally {
    client.release();
  }
}

async function markPublished(pool, id, { publishedAt, postUrl }) {
  if (!publishedAt || !postUrl) throw httpErr(422, 'published_at and post_url are required');
  await withTx(pool, async (c) => {
    const { rows } = await c.query(`
      UPDATE validator_manual_publish_queue
      SET operator_status='published', published_at=$2, post_url=$3, updated_at=now()
      WHERE id=$1 AND operator_status='in_progress' AND cancelled_at IS NULL
      RETURNING slot_id`, [id, publishedAt, postUrl]);
    if (!rows.length) await failTransition(c, id, 'in_progress');  // throws -> ROLLBACK
    await c.query(`
      UPDATE validator_schedule_slots
      SET matched_post_url=$1, matched_at=$2, updated_at=now()
      WHERE id=$3 AND matched_post_url IS NULL`, [postUrl, publishedAt, rows[0].slot_id]);
  });
  return getItem(pool, id);
}

async function reworkItem(pool, id) {
  await withTx(pool, async (c) => {
    // lock row + capture operator's published url before clearing
    const cur = await c.query(
      'SELECT slot_id, post_url FROM validator_manual_publish_queue WHERE id=$1 FOR UPDATE', [id]);
    const oldUrl = cur.rows.length ? cur.rows[0].post_url : null;
    const { rows } = await c.query(`
      UPDATE validator_manual_publish_queue
      SET operator_status='queued', published_at=NULL, post_url=NULL, taken_at=NULL, updated_at=now()
      WHERE id=$1 AND operator_status='published' AND cancelled_at IS NULL
      RETURNING slot_id`, [id]);
    if (!rows.length) await failTransition(c, id, 'published');  // throws -> ROLLBACK
    // clear slot stamp ONLY if it still holds THIS operator's url (IS NOT DISTINCT FROM
    // = NULL-safe equality; не затираем результат матчера WP#85, если он отличается)
    await c.query(`
      UPDATE validator_schedule_slots
      SET matched_post_url=NULL, matched_at=NULL, updated_at=now()
      WHERE id=$1 AND matched_post_url IS NOT DISTINCT FROM $2`, [rows[0].slot_id, oldUrl]);
  });
  return getItem(pool, id);
}
```
Update exports line:
```js
module.exports = { httpErr, accountUrl, rowToDict, JOINED_SELECT, listQueue, getItem,
  takeItem, returnItem, markPublished, reworkItem };
```

- [ ] **Step 4: Запустить — убедиться, что зелёный**

Run: `node --test tests/test_manual_publish_queue.test.js`
Expected: PASS (13 tests).

- [ ] **Step 5: Коммит**

```bash
git add manual_publish_queue.js tests/test_manual_publish_queue.test.js
git commit -m "feat(wp107): manual_publish_queue transitions (take/return/publish/rework) + error codes"
```

---

## Task 3: Express-эндпоинты + подключение наполнителя (server.js)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js` (require + endpoints + scheduler wiring near line 6278)

- [ ] **Step 1: Добавить require модуля**

Рядом с прочими `require` вверху `server.js` добавить:
```js
const mpq = require('./manual_publish_queue');
const { assignManualPublishQueue } = require('./manual_queue_assign');
```

- [ ] **Step 2: Добавить эндпоинты (после блока `/api/validator/projects`, ~строка 5560)**

```js
// ============ WP#107 РУЧНАЯ ВЫКЛАДКА ============
app.get('/api/publishing/manual-queue', requireAuth, async (req, res) => {
  try {
    const status = req.query.status || null;
    res.json({ items: await mpq.listQueue(pool, status) });
  } catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});

app.get('/api/publishing/manual-queue/:id', requireAuth, async (req, res) => {
  try { res.json(await mpq.getItem(pool, parseInt(req.params.id, 10))); }
  catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});

app.post('/api/publishing/manual-queue/:id/take', requireAuth, async (req, res) => {
  try { res.json(await mpq.takeItem(pool, parseInt(req.params.id, 10))); }
  catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});

app.post('/api/publishing/manual-queue/:id/return', requireAuth, async (req, res) => {
  try { res.json(await mpq.returnItem(pool, parseInt(req.params.id, 10))); }
  catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});

app.post('/api/publishing/manual-queue/:id/publish', requireAuth, async (req, res) => {
  try {
    const { published_at, post_url } = req.body || {};
    res.json(await mpq.markPublished(pool, parseInt(req.params.id, 10),
      { publishedAt: published_at, postUrl: post_url }));
  } catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});

app.post('/api/publishing/manual-queue/:id/rework', requireAuth, async (req, res) => {
  try { res.json(await mpq.reworkItem(pool, parseInt(req.params.id, 10))); }
  catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});
```

- [ ] **Step 3: Подключить наполнитель в шедулер**

Сразу после строки `setInterval(assignUnicResultsToQueue, 30 * 60 * 1000);` (server.js:6278) добавить:
```js
// WP#107: наполнитель очереди ручной выкладки (kill-switch MANUAL_QUEUE_POPULATE_ENABLED)
assignManualPublishQueue(pool).catch(e => console.error('[manual-queue]', e.message));
setInterval(() => assignManualPublishQueue(pool).catch(e => console.error('[manual-queue]', e.message)),
  30 * 60 * 1000);
```

- [ ] **Step 4: Проверить синтаксис (server не запускаем — порт занят прод-процессом)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --check server.js`
Expected: без вывода (синтаксис ок).

- [ ] **Step 5: Прогнать все autowarm-тесты (не сломали соседей)**

Run: `node --test --test-force-exit tests/*.test.js`
Expected: PASS (включая 11 новых + существующие manual_queue_assign).

- [ ] **Step 6: Коммит**

```bash
git add server.js
git commit -m "feat(wp107): /api/publishing/manual-queue endpoints + wire assignManualPublishQueue scheduler"
```

---

## Task 4: Frontend — пункт сайдбара, секция, таблица

> Фронт-харнесса для `index.html` нет → реализация + ручной smoke (Task 8). Код vanilla JS в стиле существующего дашборда.

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html`

- [ ] **Step 1: Пункт сайдбара** — после кнопки `nav-publishing-dashboard` (≈строка 255) в `<nav id="sidebar-publishing">` добавить:
```html
    <button onclick="nav('publishing-manual')" id="nav-publishing-manual" class="nav-item w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-600 hover:bg-gray-100 text-left">
      <span>📤</span> Ручная выкладка
    </button>
```

- [ ] **Step 2: Регистрация в `sidebarMap`** — в объекте `sidebarMap` (≈строка 4066) добавить ключ:
```js
    'publishing-manual': 'publishing',
```

- [ ] **Step 3: Секция-контейнер** — рядом с `<div id="section-publishing-dashboard">` (≈строка 2258) добавить новую секцию:
```html
<div id="section-publishing-manual" class="section px-4 py-4 fade-in hidden">
  <div class="flex items-center justify-between mb-3">
    <h2 class="text-xl font-bold text-gray-900">📤 Ручная выкладка</h2>
    <button onclick="mpqLoad()" class="px-3 py-1.5 rounded-lg bg-indigo-50 text-indigo-700 text-sm font-medium">🔄 Обновить</button>
  </div>
  <div class="table-wrap overflow-auto max-h-[calc(100vh-220px)] bg-white rounded-2xl shadow-sm border border-gray-100">
    <table class="w-full text-sm" id="mpq-table">
      <thead id="mpq-thead"></thead>
      <tbody id="mpq-tbody"></tbody>
    </table>
  </div>
  <p id="mpq-empty" class="hidden text-center text-gray-400 py-8">Очередь пуста</p>
</div>
```

- [ ] **Step 4: Ветка рендера в `nav()`** — найти обработчик секций (≈строка 4012, `if (section === 'publishing-dashboard')`) и добавить ветку:
```js
  if (section === 'publishing-manual') { mpqLoad(); }
```

- [ ] **Step 5: JS-логика таблицы** — добавить в основной `<script>` (рядом с другими функциями раздела publishing):
```js
// ===== WP#107 Ручная выкладка =====
let mpqRows = [], mpqSort = [], mpqFilters = {};
const MPQ_COLS = [
  { key: 'id', label: 'id', filter: null },
  { key: 'phone_number', label: 'Тел. №', filter: 'select' },
  { key: 'project_name', label: 'Проект', filter: 'select' },
  { key: 'platform', label: 'Платформа', filter: 'select' },
  { key: 'pack_name', label: 'Пак', filter: 'select' },
  { key: 'account_username', label: 'Аккаунт', filter: 'text' },
  { key: 'source_video_url', label: 'Исх. видео', filter: null },
  { key: 'unic_video_url', label: 'Уник. видео', filter: null },
  { key: 'scheme_id', label: 'Схема', filter: 'select' },
  { key: 'planned_date', label: 'План дата', filter: 'text' },
  { key: 'operator_status', label: 'Статус', filter: 'select' },
  { key: 'publication_url', label: 'Публикация', filter: null },
  { key: 'actions', label: 'Действие', filter: null },
];
const MPQ_STATUS = { queued: 'В очереди', in_progress: 'В работе', published: 'Выложено' };

// XSS-защита: контент из БД (заголовки/описания клиентов, ники, URL) — НЕдоверенный
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }

async function mpqLoad() {
  const r = await fetch('/api/publishing/manual-queue', { credentials: 'same-origin' });
  const data = await r.json();
  mpqRows = data.items || [];
  mpqRender();
}

function mpqMatch(row, c, f) {
  if (!f) return true;
  if (c.filter === 'select') return String(row[c.key] ?? '') === f;       // dropdown = точное равенство
  return String(row[c.key] ?? '').toLowerCase().includes(f.toLowerCase()); // text = подстрока
}
function mpqApply() {
  let rows = mpqRows.filter(row => MPQ_COLS.every(c => mpqMatch(row, c, mpqFilters[c.key])));
  for (const s of [...mpqSort].reverse()) {
    rows.sort((a, b) => {
      const av = a[s.key] ?? '', bv = b[s.key] ?? '';
      return (av > bv ? 1 : av < bv ? -1 : 0) * (s.dir === 'desc' ? -1 : 1);
    });
  }
  return rows;
}

function mpqFilterCell(c) {
  if (c.key === 'actions') return `<th class="px-2 py-1"><button onclick="mpqReset()" title="Сброс сортировки и фильтров" class="text-indigo-700">⟲</button></th>`;
  if (!c.filter) return '<th class="px-2 py-1"></th>';
  if (c.filter === 'select') {            // дропдаун из уникальных значений колонки
    const vals = [...new Set(mpqRows.map(r => r[c.key]).filter(v => v !== null && v !== undefined && v !== ''))];
    const opts = vals.map(v => `<option value="${esc(v)}" ${mpqFilters[c.key] === String(v) ? 'selected' : ''}>${esc(c.key === 'operator_status' ? (MPQ_STATUS[v] || v) : v)}</option>`).join('');
    return `<th class="px-2 py-1"><select onchange="mpqFilters['${c.key}']=this.value; mpqRender()" class="w-full border rounded px-1 py-0.5 text-xs"><option value="">все</option>${opts}</select></th>`;
  }
  return `<th class="px-2 py-1"><input value="${esc(mpqFilters[c.key] || '')}" oninput="mpqFilters['${c.key}']=this.value; mpqRender()" class="w-full border rounded px-1 py-0.5 text-xs" placeholder="фильтр"></th>`;
}

function mpqRowHtml(row) {
  const accUrl = safeUrl(row.account_url);
  const acc = accUrl ? `<a href="${esc(accUrl)}" target="_blank" rel="noopener" class="text-indigo-600" onclick="event.stopPropagation()">@${esc(row.account_username)}</a>` : ('@' + esc(row.account_username || ''));
  const srcU = safeUrl(row.source_video_url), unicU = safeUrl(row.unic_video_url), pubU = safeUrl(row.publication_url);
  const src = srcU ? `<a href="${esc(srcU)}" target="_blank" rel="noopener" class="text-indigo-600" onclick="event.stopPropagation()">исх.</a>` : '';
  const unic = unicU ? `<a href="${esc(unicU)}" target="_blank" rel="noopener" class="text-indigo-600" onclick="event.stopPropagation()">уник.</a>` : '';
  const pub = pubU ? `<a href="${esc(pubU)}" target="_blank" rel="noopener" class="text-indigo-600" onclick="event.stopPropagation()">ссылка</a>` : '—';
  return `<tr class="border-b hover:bg-gray-50 cursor-pointer" onclick="mpqOpenCard(${row.id})">
    <td class="px-2 py-1.5">${esc(row.id)}</td><td class="px-2 py-1.5">${esc(row.phone_number ?? '')}</td>
    <td class="px-2 py-1.5">${esc(row.project_name ?? '')}</td><td class="px-2 py-1.5">${esc((row.platform || '').toUpperCase())}</td>
    <td class="px-2 py-1.5">${esc(row.pack_name ?? '')}</td><td class="px-2 py-1.5">${acc}</td>
    <td class="px-2 py-1.5">${src}</td><td class="px-2 py-1.5">${unic}</td>
    <td class="px-2 py-1.5">${esc(row.scheme_id ?? '')}</td><td class="px-2 py-1.5">${esc(row.planned_date ?? '')}</td>
    <td class="px-2 py-1.5">${esc(MPQ_STATUS[row.operator_status] || row.operator_status)}</td>
    <td class="px-2 py-1.5">${pub}</td>
    <td class="px-2 py-1.5" onclick="event.stopPropagation()">${mpqActions(row)}</td></tr>`;
}

function mpqRender() {
  const thead = document.getElementById('mpq-thead');
  const tbody = document.getElementById('mpq-tbody');
  const sortMark = k => { const s = mpqSort.find(x => x.key === k); return s ? (s.dir === 'asc' ? ' ▲' : ' ▼') : ''; };
  thead.innerHTML =
    '<tr class="bg-gray-50 border-b sticky top-0 z-10">' +
    MPQ_COLS.map(c => `<th class="px-2 py-2 text-left font-semibold cursor-pointer select-none" onclick="mpqToggleSort('${c.key}', event)">${esc(c.label)}${sortMark(c.key)}</th>`).join('') +
    '</tr><tr class="bg-indigo-50 border-b">' + MPQ_COLS.map(mpqFilterCell).join('') + '</tr>';

  const rows = mpqApply();
  document.getElementById('mpq-empty').classList.toggle('hidden', rows.length > 0);
  // группировка по телефону: заголовок группы перед строками каждого телефона
  const groups = new Map();
  for (const r of rows) { const k = r.phone_number ?? '—'; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(r); }
  let html = '';
  for (const [phone, grp] of groups) {
    html += `<tr class="bg-gray-100"><td colspan="${MPQ_COLS.length}" class="px-2 py-1 font-semibold text-gray-600">📱 Тел. № ${esc(phone)} <span class="font-normal text-gray-400">(${grp.length})</span></td></tr>`;
    html += grp.map(mpqRowHtml).join('');
  }
  tbody.innerHTML = html;
}

function mpqActions(row) {
  if (row.operator_status === 'queued')
    return `<button onclick="mpqAction(${row.id},'take')" class="px-2 py-1 rounded bg-indigo-600 text-white text-xs">Взять в работу</button>`;
  if (row.operator_status === 'in_progress')
    return `<button onclick="mpqAction(${row.id},'return')" class="px-2 py-1 rounded bg-gray-200 text-xs mr-1">Вернуть в очередь</button>` +
           `<button onclick="mpqOpenCard(${row.id}, true)" class="px-2 py-1 rounded bg-green-600 text-white text-xs">Отметить выкладку</button>`;
  if (row.operator_status === 'published')
    return `<button onclick="mpqAction(${row.id},'rework')" class="px-2 py-1 rounded bg-amber-500 text-white text-xs">Вернуть на доработку</button>`;
  return '';
}

function mpqToggleSort(key, ev) {
  if (key === 'actions') return;
  const existing = mpqSort.find(s => s.key === key);
  if (!ev.ctrlKey && !ev.metaKey) {
    if (existing && mpqSort.length === 1) { mpqSort = existing.dir === 'asc' ? [{ key, dir: 'desc' }] : []; }
    else mpqSort = [{ key, dir: 'asc' }];
  } else {
    if (!existing) mpqSort.push({ key, dir: 'asc' });
    else if (existing.dir === 'asc') existing.dir = 'desc';
    else mpqSort = mpqSort.filter(s => s.key !== key);
  }
  mpqRender();
}

function mpqReset() { mpqSort = []; mpqFilters = {}; mpqRender(); }

async function mpqAction(id, action) {
  const r = await fetch(`/api/publishing/manual-queue/${id}/${action}`, { method: 'POST', credentials: 'same-origin' });
  if (!r.ok) { const e = await r.json().catch(() => ({})); alert('Ошибка: ' + (e.error || r.status)); return; }
  await mpqLoad();
}
```

- [ ] **Step 6: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(wp107): delivery «Ручная выкладка» — sidebar item + section + table (sort/filter/reset)"
```

---

## Task 5: Frontend — карточка публикации (модалка)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html`

- [ ] **Step 1: Контейнер модалки** — перед закрывающим `</body>` добавить:
```html
<div id="mpq-card" class="hidden fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onclick="if(event.target===this)mpqCloseCard()">
  <div class="bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-auto p-5" id="mpq-card-body"></div>
</div>
```

- [ ] **Step 2: JS модалки** — добавить в основной `<script>`:
```js
let mpqCardId = null, mpqCopyVals = {};
async function mpqOpenCard(id, publishMode = false) {
  const r = await fetch(`/api/publishing/manual-queue/${id}`, { credentials: 'same-origin' });
  if (!r.ok) return;
  const row = await r.json();
  mpqCardId = id; mpqCopyVals = {};
  const copy = (key, label, val) => {
    if (val == null || val === '') return '';
    const text = Array.isArray(val) ? val.join(' ') : String(val);
    mpqCopyVals[key] = text;  // значение копируется из map, НЕ из inline-HTML (анти-XSS)
    return `<div class="mb-2"><p class="text-xs text-gray-400">${esc(label)}</p><div onclick="mpqCopy(this,'${key}')" class="cursor-pointer bg-gray-50 rounded px-2 py-1 hover:bg-indigo-50" title="Клик — копировать">${esc(text)}</div></div>`;
  };
  const inProgress = row.operator_status === 'in_progress';
  const unicU = safeUrl(row.unic_video_url), srcU = safeUrl(row.source_video_url);
  document.getElementById('mpq-card-body').innerHTML = `
    <div class="flex justify-between items-center mb-3">
      <h3 class="text-lg font-bold">Карточка публикации</h3>
      <button onclick="mpqCloseCard()" class="text-gray-400 text-xl">✕</button>
    </div>
    <p class="mb-3"><span class="text-xs text-gray-400">Статус:</span> <b>${esc(MPQ_STATUS[row.operator_status] || row.operator_status)}</b></p>
    ${copy('title', 'Заголовок видео', row.title)}
    ${copy('description', 'Описание', row.description)}
    ${copy('hashtags', 'Хэштеги', row.hashtags)}
    ${copy('geo', 'Гео', row.geo)}
    ${unicU ? `<video src="${esc(unicU)}" controls class="w-full rounded-lg my-2 max-h-80"></video>` : ''}
    <div class="flex gap-3 text-sm my-2">
      ${srcU ? `<a href="${esc(srcU)}" target="_blank" rel="noopener" class="text-indigo-600">⬇ исходное</a>` : ''}
      ${unicU ? `<a href="${esc(unicU)}" target="_blank" rel="noopener" class="text-indigo-600">⬇ уник.</a>` : ''}
    </div>
    ${(inProgress || publishMode) ? `
      <div class="border-t mt-3 pt-3 bg-red-50 rounded-lg p-3">
        <p class="font-semibold text-red-700 mb-2">Отметить выкладку</p>
        <label class="text-xs text-gray-500">Дата-время публикации (МСК)</label>
        <input type="datetime-local" id="mpq-pub-date" class="w-full border rounded px-2 py-1 mb-2" oninput="mpqValidatePublish()">
        <label class="text-xs text-gray-500">Ссылка на пост</label>
        <input type="url" id="mpq-pub-url" class="w-full border rounded px-2 py-1 mb-2" placeholder="https://..." oninput="mpqValidatePublish()">
        <button id="mpq-pub-btn" disabled onclick="mpqPublish()" class="px-4 py-2 rounded-lg bg-green-600 text-white disabled:opacity-40">Подтвердить выкладку</button>
      </div>` : ''}`;
  document.getElementById('mpq-card').classList.remove('hidden');
}
function mpqCloseCard() { document.getElementById('mpq-card').classList.add('hidden'); mpqCardId = null; }
function mpqCopy(el, key) { navigator.clipboard.writeText(mpqCopyVals[key] || ''); const o = el.textContent; el.textContent = '✓ скопировано'; setTimeout(() => el.textContent = o, 900); }
function mpqValidatePublish() {
  const d = document.getElementById('mpq-pub-date').value, u = document.getElementById('mpq-pub-url').value;
  document.getElementById('mpq-pub-btn').disabled = !(d && u);
}
async function mpqPublish() {
  const dLocal = document.getElementById('mpq-pub-date').value; // МСК (UTC+3), без зоны
  const u = document.getElementById('mpq-pub-url').value;
  const iso = new Date(dLocal + ':00+03:00').toISOString();   // МСК -> UTC ISO
  const r = await fetch(`/api/publishing/manual-queue/${mpqCardId}/publish`, {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ published_at: iso, post_url: u }) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); alert('Ошибка: ' + (e.error || r.status)); return; }
  mpqCloseCard(); await mpqLoad();
}
```

- [ ] **Step 3: Коммит**

```bash
git add public/index.html
git commit -m "feat(wp107): delivery «Ручная выкладка» — карточка публикации (copy-on-click, video, publish-confirm)"
```

---

## Task 6: Удаление UI из валидатора (frontend)

**Files (validator = `/home/claude-user/validator-contenthunter`):**
- Delete: `frontend/src/pages/admin/ManualPublishingQueue.vue`, `frontend/src/components/manual-publish/PublicationCard.vue`, `frontend/src/composables/useManualPublishTable.ts`, `frontend/src/api/manualPublish.ts`, `frontend/tests/useManualPublishTable.spec.ts`
- Modify: `frontend/src/router/index.ts` (снять роут `/manual-publish` + import), `frontend/src/components/layout/AppSidebar.vue` (снять секцию «Выкладка» + NavItem)

- [ ] **Step 1: Ветка**

Run:
```bash
cd /home/claude-user/validator-contenthunter
git fetch origin && git checkout -b chore/wp107-remove-validator-manual-publish origin/main
```

- [ ] **Step 2: Удалить файлы**

```bash
git rm frontend/src/pages/admin/ManualPublishingQueue.vue \
       frontend/src/components/manual-publish/PublicationCard.vue \
       frontend/src/composables/useManualPublishTable.ts \
       frontend/src/api/manualPublish.ts \
       frontend/tests/useManualPublishTable.spec.ts
```

- [ ] **Step 3: Снять роут** — в `frontend/src/router/index.ts` удалить import `ManualPublishingQueue` и объект route с `path: '/manual-publish'` (и его `meta.roles`).

- [ ] **Step 4: Снять секцию сайдбара** — в `frontend/src/components/layout/AppSidebar.vue` удалить блок:
```html
      <div v-if="auth.isAdmin" class="pt-3">
        <p ...>Выкладка</p>
        <NavItem to="/manual-publish" icon="📤" label="Ручная выкладка" />
      </div>
```

- [ ] **Step 5: Сборка фронта (ловит висячие импорты)**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npm run build`
Expected: build OK, нет ошибок «failed to resolve import ManualPublishingQueue/manualPublish». (Postbuild авто-деплоит во `/var/www/validator/` — это допустимо, фронт без пункта.)

- [ ] **Step 6: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add -A
git commit -m "chore(wp107): remove manual-publish UI from validator (moved to delivery)"
```

---

## Task 7: Удаление backend-роутера из валидатора (оставить toggle-хук)

**Files (validator):**
- Delete: `backend/src/routers/manual_publish.py`
- Modify: `backend/src/main.py` (снять import + `include_router`), `backend/src/services/manual_publish_service.py` (удалить read/transition-функции, оставить `cancel_queued_for_slot`)
- Keep: `backend/src/models/manual_publish.py` (модель нужна `cancel_queued_for_slot` и общей таблице), миграция `006`.

- [ ] **Step 1: Удалить роутер + снять подключение**

```bash
cd /home/claude-user/validator-contenthunter
git rm backend/src/routers/manual_publish.py
```
В `backend/src/main.py` удалить строки `from .routers import manual_publish` и `app.include_router(manual_publish.router)`.

- [ ] **Step 2: Урезать сервис до toggle-хука** — в `backend/src/services/manual_publish_service.py` удалить `list_queue`, `get_item`, `_load_for_update`, `_require_status`, `take_item`, `return_item`, `mark_published`, `rework_item`, `_row_to_dict`, `_JOINED_SELECT`, `account_profile_url`, `_iso`. **Оставить** только `cancel_queued_for_slot` (+ нужные импорты: `text`, `AsyncSession`).

- [ ] **Step 3: Убедиться, что `cancel_queued_for_slot` ещё импортируется там, где WP#85 toggle**

Run:
```bash
cd /home/claude-user/validator-contenthunter
grep -rn "cancel_queued_for_slot\|manual_publish_service" backend/src --include=*.py | grep -v test
```
Expected: остаётся вызов из обработчика toggle (`set_manual_publish`); нет ссылок на удалённые функции.

- [ ] **Step 4: Прогнать backend-тесты (live-DB, autouse engine.dispose)**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/ -q`
Expected: PASS. Удалить/поправить `tests/test_manual_publish_queue.py` (тесты удалённого роутера) — `git rm backend/tests/test_manual_publish_queue.py`, оставив тест `cancel_queued_for_slot`, если он там есть (вынести в отдельный, если смешан).

- [ ] **Step 5: Коммит**

```bash
git add -A
git commit -m "chore(wp107): remove validator manual-publish router/service (keep toggle-OFF cancel hook)"
```

---

## Task 8: Деплой + live-smoke + откат валидатора

> Прод-операции. autowarm прод-чекаут = `/root/.openclaw/workspace-genri/autowarm` (auto-push hook → GenGo2). **Никаких force-push.**

- [ ] **Step 1: PR + merge autowarm** — создать PR из `feat/wp107-manual-publish-delivery` в `GenGo2/delivery-contenthunter`, прогнать codex review плана-диффа (раундами до 0 P1), смёржить.

- [ ] **Step 2: Деплой autowarm** — в прод-чекауте подтянуть main и рестартнуть:
```bash
cd /root/.openclaw/workspace-genri/autowarm
git status --porcelain   # ДОЛЖНО быть пусто (не затирать чужой WIP)
git pull --ff-only origin main
node --check server.js
sudo pm2 restart autowarm
```
Expected: процесс online.

- [ ] **Step 3: Smoke — наполнитель пошёл**

Run:
```bash
sudo pm2 logs autowarm --lines 40 --nostream | grep -i "manual-queue" | tail
F=/root/.openclaw/workspace-genri/validator/backend/.env
DBURL=$(grep -h DATABASE_URL "$F" | head -1 | cut -d= -f2- | tr -d '"' | sed 's/+asyncpg//')
psql "$DBURL" -c "SELECT operator_status, count(*) FROM validator_manual_publish_queue WHERE cancelled_at IS NULL GROUP BY 1;"
```
Expected: лог `[manual-queue] …` без ошибок; если есть готовые ручные слоты — строки в очереди.

- [ ] **Step 4a: Smoke — реальный SQL (ловит mock-drift, ОБЯЗАТЕЛЬНО)**

Mock-тесты НЕ исполняют реальный SQL. Прогоняем `listQueue` против живой openclaw — это валидирует JOIN'ы и имена колонок:
```bash
cd /root/.openclaw/workspace-genri/autowarm
node -e '
const { Pool } = require("pg");
const mpq = require("./manual_publish_queue");
const pool = new Pool({ host:"localhost", port:5432, database:"openclaw", user:"openclaw", password:"openclaw123" });
mpq.listQueue(pool, null)
  .then(r => { console.log("listQueue OK, rows=", r.length); if (r[0]) console.log("keys:", Object.keys(r[0]).join(",")); return pool.end(); })
  .catch(e => { console.error("listQueue FAILED:", e.message); process.exit(1); });
'
```
Expected: `listQueue OK, rows=N` без ошибок (никаких `column ... does not exist` / `relation ... does not exist`). Если есть строка — `keys:` содержит `account_url, publication_url, …`.

- [ ] **Step 4b: Smoke — роут зарегистрирован**

```bash
curl -s -o /dev/null -w "list -> %{http_code}\n" http://127.0.0.1:3848/api/publishing/manual-queue
```
Expected: `list -> 401` (роут есть, отбит `requireAuth`; не 404). Полный UI-smoke — Step 6.

> Порт autowarm = `3848` (server.js:8406, `process.env.PORT || '3848'`; подтверждено `/login → 200`). Пул — `openclaw/openclaw123@localhost:5432/openclaw` (server.js:169).

- [ ] **Step 5: Деплой валидатора (откат UI+роутера)** — смёржить PR Task 6+7 в `GenGo2/validator-contenthunter`, затем:
```bash
cd /root/.openclaw/workspace-genri/validator
git status --porcelain && git pull --ff-only origin main
sudo pm2 restart validator
```
Сборка фронта валидатора уже задеплоена Task 6 Step 5 (postbuild). Проверить: пункт «Ручная выкладка» исчез из сайдбара `client.contenthunter.ru` (hard-reload), `/api/manual-publish/queue` → 404.

- [ ] **Step 6: Приёмочный smoke в delivery (браузер)** — на `delivery.contenthunter.ru` под логином: модуль «📤 Выкладка» → «Ручная выкладка». Проверить: таблица грузится, sticky-заголовки, клик-сортировка + CTRL-мультисорт, фильтры-дропдауны + `⟲` сброс, кнопки по статусам (Взять→Вернуть/Отметить→карточка), карточка (copy-on-click, видео, скачивания), «Подтвердить выкладку» активна только при дате+ссылке, после publish статус «Выложено» + ссылка в «Публикация».

- [ ] **Step 7: Обновить OpenProject WP #107** — комментарий в house-style (Что было не так → Что сделано → Что осталось): фича перенесена из валидатора в delivery, наполнитель подключён, валидаторная копия удалена. Статус — по факту приёмки.

---

## Self-Review notes (заполнено автором плана)

- **Покрытие спека:** §2 данные/статусы → Task 1 (rowToDict, status map в UI Task 4); §3 backend → Tasks 1-3; §4 наполнитель → Task 3 Step 3; §5 frontend → Tasks 4-5; §6 удаление из валидатора → Tasks 6-7; §7 тесты → Tasks 1-2 (+ live-smoke Task 8); §8 деплой → Task 8. ✅
- **Атрибуция оператора (NULL):** переходы НЕ пишут `taken_by_id/published_by_id` — соответствует §2. ✅
- **Типы/имена:** функции модуля (`listQueue/getItem/takeItem/returnItem/markPublished/reworkItem/accountUrl/rowToDict/httpErr`) консистентны между Task 1/2/3 и тестами. ✅
- **Плейсхолдеры:** не найдено. Порт autowarm = `3848` (подтверждён, server.js:8406). ✅
- **Codex round 1 (применено):** [P1] XSS — добавлены `esc()`/`safeUrl()`, все текст-поля и URL экранируются в таблице (Task 4) и карточке (Task 5), copy-on-click читает из JS-map. [P2] rework — Task 2 `reworkItem` чистит `slot.matched_post_url/matched_at` через `IS NOT DISTINCT FROM` старого `post_url` (не затирая результат матчера); +2 теста. ✅
- **Codex round 2 (применено):** [P1] live-smoke — Task 8 Step 4a исполняет реальный `listQueue` против openclaw (ловит drift JOIN/колонок); 401-curl оставлен как «роут зарегистрирован» (4b). [P2] атомарность — `markPublished`/`reworkItem` обёрнуты в `withTx` (одна client-транзакция queue+slot); mock-пул получил `connect()`. ✅
- **Codex round 3 (применено):** [P2] фронт — `MPQ_COLS` получили `filter: select|text|null`; `mpqFilterCell` рисует дропдауны (платформа/проект/пак/телефон/статус/схема) из уникальных значений + текст для аккаунта/дат; `mpqApply`/`mpqMatch` — точное равенство для select, подстрока для text; `mpqRender` группирует строки по телефону (заголовок группы). ✅
- **Codex round 4 (ОТКЛОНЕНО — ложноположительный):** [P1] «`q.unic_result_id` не существует» — НЕВЕРНО. Колонка есть в `validator_manual_publish_queue` (проверено `information_schema.columns` в живой openclaw); наполнитель `manual_queue_assign.js` в неё INSERT'ит, а партиал-индекс `ON CONFLICT (unic_result_id, account_username, platform)` на неё ссылается. Codex видит только дифф плана, не реальную схему → предположил отсутствие. JOIN `ur.id = q.unic_result_id` корректен. Реальных P1 = 0.
