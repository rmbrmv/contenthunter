# WP #123 + #124 — Manual-publish card grouping & realtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сгруппировать очередь ручной выкладки в карточку на исходное видео × пак (#123) и сделать её близкой к реальному времени с защитой «уже в работе» (#124).

**Architecture:** Бэкенд `manual_publish_queue.js` отдаёт плоские строки + `unic_result_id` + имя занявшего оператора (join `autowarm_users` по уже существующей колонке `taken_by_id`). Фронт (`public/index.html`, vanilla-JS блок MPQ) группирует строки по `unic_result_id` в карточки; «Взять в работу» — групповой атомарный claim (новые endpoints `/group/:unicResultId/take|return`), выкладка — по платформе (существующие per-id `publish`/`rework`), частичный статус считается на фронте. Поллинг ~5 c обновляет список и открытую карточку, не затирая введённые ссылки. Только репозиторий autowarm (`GenGo2/delivery-contenthunter`).

**Tech Stack:** Node.js + Express, `pg`, Postgres `openclaw`; фронт — vanilla JS + Tailwind (CDN); бэкенд-тесты `node --test` против живой БД; фронт — live-smoke на дашборде.

**Spec:** `docs/superpowers/specs/2026-05-21-wp123-124-manual-publish-card-realtime-design.md`

---

## Контекст реализации (проверено в коде/БД на 2026-05-21)

- Грейн строки: 1 на `(unic_result_id × account × platform)`; все платформенные строки одного пака делят общий `unic_result_id` (наполнитель `manual_queue_assign.js` вставляет per-account×platform в цикле по одному `unic_result`).
- **Миграция НЕ нужна:** `validator_manual_publish_queue` уже имеет колонки `taken_by_id`, `taken_at`, `published_by_id`, `published_at`, `post_url`, `cancelled_at`. `takeItem` сейчас НЕ пишет `taken_by_id` — это и добавляем.
- `autowarm_users(id, username, role, …)` — для имени оператора join по `taken_by_id`.
- `manual_publish_queue.js`: `JOINED_SELECT` (стр. 37-49) НЕ выбирает `q.unic_result_id` и `taken_by_id`; `rowToDict` (18-35) их не отдаёт. `takeItem`/`returnItem` (74-92) — per-id. `markPublished`/`reworkItem` (110-144) — per-id, уже годятся для частичной выкладки. `httpErr(status,msg)` (3-5).
- Endpoints `server.js:5700-5733` (`/api/publishing/manual-queue*`), все под `requireAuth`. Сессия: `req.session.user = {id, username, role}` (server.js:78).
- Фронт MPQ-блок: `public/index.html:11869-12053` (один `<script>`), контейнер карточки `#mpq-card`/`#mpq-card-body` на `public/index.html:14031-14032`. Секция `#section-publishing-manual` (2269+), вход `nav('publishing-manual')` → `mpqLoad()` (4093). Хелперы `esc()`/`safeUrl()` уже есть в блоке.

> Номера строк индикативны — сверяйся (`grep -n "JOINED_SELECT\|function mpqRender\|id=\"mpq-card\"" ...`).

## Файловая структура

- **Modify:** `manual_publish_queue.js` — `JOINED_SELECT`+`rowToDict` (отдать `unic_result_id`,`taken_by`,`taken_by_id`); новые `takeGroup`/`returnGroup`; экспорт.
- **Modify:** `server.js` — два новых group-endpoint'а + 409 с `taken_by`.
- **Modify:** `public/index.html` — заменить MPQ-блок (карточная группировка, мини-таблица платформ, копируемая ссылка на уник, групповой take, частичная выкладка, предупреждение, поллинг) + сделать карточку на весь экран.
- **Modify/Create:** `test_manual_publish_queue.test.js` — live-DB тесты read/group-claim/409.

---

### Task 1: бэкенд-read отдаёт `unic_result_id` + имя занявшего

**Files:**
- Modify: `manual_publish_queue.js` (`JOINED_SELECT` ~37-49, `rowToDict` ~18-35)
- Test: `test_manual_publish_queue.test.js`

- [ ] **Step 1: Падающий тест read-формы**

Create `test_manual_publish_queue.test.js`:

```javascript
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const mpq = require('./manual_publish_queue');

const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

// High fixture IDs — WP#123/#124
const PID = 991230, CONTENT = 9912300, SLOT = 9912300, TASK = 9912300, RESULT = 9912300;
const USER_A = 9912301, USER_B = 9912302;
const Q_IG = 99123001, Q_TT = 99123002, Q_YT = 99123003; // pack of 3 platforms, same unic_result

async function cleanup() {
  await pool.query(`DELETE FROM validator_manual_publish_queue WHERE unic_result_id=$1`, [RESULT]);
  await pool.query(`DELETE FROM unic_results WHERE id=$1`, [RESULT]);
  await pool.query(`DELETE FROM unic_tasks WHERE id=$1`, [TASK]);
  await pool.query(`DELETE FROM validator_schedule_slots WHERE id=$1`, [SLOT]);
  await pool.query(`DELETE FROM validator_content WHERE id=$1`, [CONTENT]);
  await pool.query(`DELETE FROM autowarm_users WHERE id = ANY($1)`, [[USER_A, USER_B]]);
  await pool.query(`DELETE FROM validator_projects WHERE id=$1`, [PID]);
}

async function setup() {
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,'WP123Proj','wp123',true,false)`, [PID]);
  await pool.query(`INSERT INTO validator_content (id, project_id, description, title, status, content_type, uploader_id, s3_url)
                    VALUES ($1,$2,'WP123 desc','WP123 заголовок','approved','video',1,'https://x/src.mp4')`, [CONTENT, PID]);
  await pool.query(`INSERT INTO validator_schedule_slots (id, project_id, slot_date, slot_position, content_id, slot_type, status, manual_publish)
                    VALUES ($1,$2, CURRENT_DATE, 1, $3, 'client', 'filled', true)`, [SLOT, PID, CONTENT]);
  await pool.query(`INSERT INTO unic_tasks (id, content_id, project_id, slot_date, current_status, meta)
                    VALUES ($1,$2,$3, CURRENT_DATE, 'done', jsonb_build_object('slot_id',$4::text))`, [TASK, CONTENT, PID, SLOT]);
  await pool.query(`INSERT INTO unic_results (id, task_id, scheme_id, output_url, status, created_at)
                    VALUES ($1,$2,NULL,'https://x/unic.mp4','done',now())`, [RESULT, TASK]);
  await pool.query(`INSERT INTO autowarm_users (id, username, role, is_active) VALUES ($1,'ksenia','operator',true),($2,'anna','operator',true)`, [USER_A, USER_B]);
  for (const [qid, plat, user] of [[Q_IG,'instagram','wp123ig'],[Q_TT,'tiktok','wp123tt'],[Q_YT,'youtube','wp123yt']]) {
    await pool.query(`INSERT INTO validator_manual_publish_queue
      (id, slot_id, content_id, unic_result_id, unic_task_id, project_id, project_name, pack_id, pack_name,
       account_username, platform, phone_number, planned_date, operator_status)
      VALUES ($1,$2,$3,$4,$5,$6,'WP123Proj',7777,'WP123Pack',$7,$8,'154', CURRENT_DATE,'queued')`,
      [qid, SLOT, CONTENT, RESULT, TASK, PID, user, plat]);
  }
}

before(async () => { await setup(); });
after(async () => { await cleanup(); await pool.end(); });

test('listQueue exposes unic_result_id and taken_by (null when unclaimed)', async () => {
  const items = await mpq.listQueue(pool);
  const mine = items.filter(i => i.unic_result_id === RESULT);
  assert.equal(mine.length, 3, 'pack of 3 platform rows');
  assert.ok(mine.every(i => i.unic_result_id === RESULT), 'unic_result_id present');
  assert.ok(mine.every(i => i.taken_by === null || i.taken_by === undefined), 'taken_by null when unclaimed');
});
```

- [ ] **Step 2: Запустить — упадёт**

Run: `node --test test_manual_publish_queue.test.js`
Expected: FAIL — `unic_result_id` отсутствует в выдаче (`mine` пустой или поле undefined).

- [ ] **Step 3: Добавить поля в `JOINED_SELECT` и `rowToDict`**

В `manual_publish_queue.js`, `JOINED_SELECT` — добавить `q.unic_result_id`, `q.taken_by_id`, `au.username AS taken_by` и LEFT JOIN:

```javascript
const JOINED_SELECT = `
  SELECT q.id, q.slot_id, q.content_id, q.unic_result_id, q.scheme_id, q.project_id, q.project_name,
         q.pack_id, q.pack_name, q.account_username, q.platform, q.phone_number,
         q.device_serial, to_char(q.planned_date, 'YYYY-MM-DD') AS planned_date, q.operator_status,
         q.post_url, q.published_at, q.taken_by_id, au.username AS taken_by,
         vc.title, vc.description, vc.hashtags, vc.geo,
         vc.s3_url       AS source_video_url,
         ur.output_url   AS unic_video_url,
         s.matched_post_url, s.matched_at
  FROM validator_manual_publish_queue q
  LEFT JOIN validator_content vc        ON vc.id = q.content_id
  LEFT JOIN unic_results ur             ON ur.id = q.unic_result_id
  LEFT JOIN validator_schedule_slots s  ON s.id  = q.slot_id
  LEFT JOIN autowarm_users au           ON au.id = q.taken_by_id
`;
```

В `rowToDict` — добавить поля в возвращаемый объект (рядом с существующими):

```javascript
    unic_result_id: m.unic_result_id,
    taken_by_id: m.taken_by_id, taken_by: m.taken_by ?? null,
```

- [ ] **Step 4: Запустить — пройдёт**

Run: `node --test test_manual_publish_queue.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add manual_publish_queue.js test_manual_publish_queue.test.js
git commit -m "feat(wp123): expose unic_result_id + taken_by operator name in manual-queue read"
```

---

### Task 2: групповой claim `takeGroup`/`returnGroup` + endpoints + 409 с именем

**Files:**
- Modify: `manual_publish_queue.js` (новые функции + экспорт)
- Modify: `server.js:~5733` (новые endpoints)
- Test: `test_manual_publish_queue.test.js`

- [ ] **Step 1: Падающие тесты группового claim**

Дописать в `test_manual_publish_queue.test.js`:

```javascript
test('takeGroup claims all queued rows of the pack for the operator', async () => {
  await setup();
  const res = await mpq.takeGroup(pool, RESULT, USER_A);
  assert.equal(res.length, 3);
  assert.ok(res.every(r => r.operator_status === 'in_progress'), 'all in_progress');
  assert.ok(res.every(r => r.taken_by === 'ksenia'), 'taken_by name set');
});

test('takeGroup by another operator → 409 with taken_by name', async () => {
  await setup();
  await mpq.takeGroup(pool, RESULT, USER_A);
  await assert.rejects(
    () => mpq.takeGroup(pool, RESULT, USER_B),
    (e) => { assert.equal(e.httpStatus, 409); assert.equal(e.taken_by, 'ksenia'); return true; }
  );
});

test('takeGroup does NOT claim queued rows if another operator holds part of the pack', async () => {
  await setup();
  // USER_A holds ONE platform of the pack (simulates per-id take / partial leftover state)
  await pool.query(`UPDATE validator_manual_publish_queue
    SET operator_status='in_progress', taken_by_id=$2, taken_at=now() WHERE id=$1`, [Q_IG, USER_A]);
  // USER_B tries to take the pack → must 409 AND must NOT claim the still-queued rows
  await assert.rejects(
    () => mpq.takeGroup(pool, RESULT, USER_B),
    (e) => { assert.equal(e.httpStatus, 409); assert.equal(e.taken_by, 'ksenia'); return true; }
  );
  const { rows } = await pool.query(
    `SELECT operator_status, taken_by_id FROM validator_manual_publish_queue WHERE id = ANY($1)`, [[Q_TT, Q_YT]]);
  assert.ok(rows.every(r => r.operator_status === 'queued' && r.taken_by_id === null),
    'queued rows must stay unclaimed — no split ownership');
});

test('takeGroup blocked by an UNATTRIBUTED in_progress row (legacy per-id take, taken_by_id NULL)', async () => {
  await setup();
  // Legacy per-id take left a row in_progress WITHOUT taken_by_id
  await pool.query(`UPDATE validator_manual_publish_queue
    SET operator_status='in_progress', taken_by_id=NULL, taken_at=now() WHERE id=$1`, [Q_IG]);
  await assert.rejects(
    () => mpq.takeGroup(pool, RESULT, USER_B),
    (e) => { assert.equal(e.httpStatus, 409); return true; }   // taken_by may be null — still 409
  );
  const { rows } = await pool.query(
    `SELECT operator_status, taken_by_id FROM validator_manual_publish_queue WHERE id = ANY($1)`, [[Q_TT, Q_YT]]);
  assert.ok(rows.every(r => r.operator_status === 'queued' && r.taken_by_id === null),
    'queued rows must stay unclaimed even when blocker is unattributed');
});

test('a returned partially-published pack is claimable by another operator (published does not lock)', async () => {
  await setup();
  await mpq.takeGroup(pool, RESULT, USER_A);
  await mpq.markPublished(pool, Q_IG, { publishedAt: new Date().toISOString(), postUrl: 'https://instagram.com/p/x' });
  await mpq.returnGroup(pool, RESULT, USER_A);                  // TT/YT → queued; IG stays published (taken_by_id=A)
  const res = await mpq.takeGroup(pool, RESULT, USER_B); // USER_B must be able to claim the leftovers
  const byId = Object.fromEntries(res.map(r => [r.id, { st: r.operator_status, by: r.taken_by }]));
  assert.equal(byId[Q_IG].st, 'published', 'published platform stays published');
  assert.equal(byId[Q_TT].st, 'in_progress'); assert.equal(byId[Q_TT].by, 'anna');
  assert.equal(byId[Q_YT].st, 'in_progress'); assert.equal(byId[Q_YT].by, 'anna');
});

test('returnGroup reverts only in_progress rows, keeps published', async () => {
  await setup();
  await mpq.takeGroup(pool, RESULT, USER_A);
  // publish one platform (partial)
  await mpq.markPublished(pool, Q_IG, { publishedAt: new Date().toISOString(), postUrl: 'https://instagram.com/p/x' });
  const res = await mpq.returnGroup(pool, RESULT, USER_A);
  const byId = Object.fromEntries(res.map(r => [r.id, r.operator_status]));
  assert.equal(byId[Q_IG], 'published', 'published platform untouched');
  assert.equal(byId[Q_TT], 'queued', 'in_progress reverted to queued');
  assert.equal(byId[Q_YT], 'queued');
});

test('returnGroup by a NON-holder is a no-op (cannot return someone else\'s work)', async () => {
  await setup();
  await mpq.takeGroup(pool, RESULT, USER_A);
  await mpq.returnGroup(pool, RESULT, USER_B);  // USER_B is not the holder → must be a no-op
  const { rows } = await pool.query(
    `SELECT operator_status, taken_by_id FROM validator_manual_publish_queue WHERE unic_result_id=$1`, [RESULT]);
  assert.ok(rows.every(r => r.operator_status === 'in_progress' && r.taken_by_id === USER_A),
    "A's active work stays in_progress and owned by A");
});

test('returnGroup clears a legacy unattributed (taken_by_id NULL) in_progress lock for any operator', async () => {
  await setup();
  await pool.query(`UPDATE validator_manual_publish_queue
    SET operator_status='in_progress', taken_by_id=NULL, taken_at=now() WHERE id=$1`, [Q_IG]);
  await mpq.returnGroup(pool, RESULT, USER_B);  // unowned lock → any operator may clear it
  const { rows } = await pool.query(
    `SELECT operator_status FROM validator_manual_publish_queue WHERE id=$1`, [Q_IG]);
  assert.equal(rows[0].operator_status, 'queued', 'unattributed lock cleared → pack claimable again');
});
```

- [ ] **Step 2: Запустить — упадёт**

Run: `node --test test_manual_publish_queue.test.js`
Expected: FAIL — `mpq.takeGroup is not a function`.

- [ ] **Step 3: Реализовать `takeGroup`/`returnGroup`**

В `manual_publish_queue.js` добавить ПЕРЕД `module.exports`:

```javascript
// WP #124: list all rows of one pack-card (shared unic_result_id).
async function listGroup(pool, unicResultId) {
  const { rows } = await pool.query(JOINED_SELECT + `
    WHERE q.unic_result_id = $1 AND q.cancelled_at IS NULL
    ORDER BY q.platform ASC, q.id ASC`, [unicResultId]);
  return rows.map(rowToDict);
}

// WP #124: atomically claim ALL queued rows of a pack for one operator.
// Pack-level ownership guard (codex P1): claim only if NO OTHER operator already
// holds any row of the group (NOT EXISTS) — otherwise a second operator could grab
// the still-queued rows of a partially-held pack (split ownership). If blocked → 409
// with the holder's name. Re-entrant: the SAME operator may claim leftover queued
// rows (e.g. a freshly populated platform) without error.
async function takeGroup(pool, unicResultId, userId) {
  // Block claim only if ANY row of the pack is currently in_progress by someone other
  // than this operator. Ownership = active in_progress work; published platforms are
  // DONE and must NOT lock the pack (codex P2 round 3: returning a partially-published
  // pack leaves published rows with the original taken_by_id — if those blocked, the
  // queued leftovers would be unclaimable by anyone else). codex P2 round 2: the legacy
  // per-id take path can leave an in_progress row with taken_by_id=NULL — treat such
  // unattributed in_progress rows as "held by someone else" too (avoid split ownership).
  // Re-entrant: in_progress rows held by THIS operator don't block.
  const { rows } = await pool.query(`
    UPDATE validator_manual_publish_queue
    SET operator_status='in_progress', taken_by_id=$2, taken_at=now(), updated_at=now()
    WHERE unic_result_id=$1 AND operator_status='queued' AND cancelled_at IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM validator_manual_publish_queue h
        WHERE h.unic_result_id=$1 AND h.cancelled_at IS NULL
          AND h.operator_status = 'in_progress'
          AND (h.taken_by_id IS NULL OR h.taken_by_id <> $2)
      )
    RETURNING id`, [unicResultId, userId]);
  if (!rows.length) {
    const { rows: blocker } = await pool.query(`
      SELECT au.username AS taken_by
      FROM validator_manual_publish_queue q
      LEFT JOIN autowarm_users au ON au.id = q.taken_by_id
      WHERE q.unic_result_id=$1 AND q.cancelled_at IS NULL
        AND q.operator_status = 'in_progress'
        AND (q.taken_by_id IS NULL OR q.taken_by_id <> $2)
      LIMIT 1`, [unicResultId]);
    if (blocker.length) {
      const e = httpErr(409, 'Задача уже у кого-то в работе');
      e.taken_by = blocker[0].taken_by;   // may be null for legacy unattributed rows
      throw e;
    }
    return listGroup(pool, unicResultId); // nothing queued & not blocked → already ours/done (idempotent)
  }
  return listGroup(pool, unicResultId);
}

// WP #124: return a pack to the queue — this operator's own in_progress rows, PLUS any
// legacy UNATTRIBUTED (taken_by_id NULL) in_progress rows. codex P2 round 4: a non-holder
// must not return someone else's active work (taken_by_id = другой → не трогаем).
// codex P2 round 5: NULL-owner rows block takeGroup but are owned by nobody — let any
// operator clear them, иначе legacy per-id-take лок навсегда застрянет в новом UI.
// Published rows untouched.
async function returnGroup(pool, unicResultId, userId) {
  await pool.query(`
    UPDATE validator_manual_publish_queue
    SET operator_status='queued', taken_by_id=NULL, taken_at=NULL, updated_at=now()
    WHERE unic_result_id=$1 AND operator_status='in_progress' AND cancelled_at IS NULL
      AND (taken_by_id = $2 OR taken_by_id IS NULL)`,
    [unicResultId, userId]);
  return listGroup(pool, unicResultId);
}
```

Обновить экспорт:

```javascript
module.exports = { httpErr, accountUrl, rowToDict, JOINED_SELECT, listQueue, getItem,
  takeItem, returnItem, markPublished, reworkItem, listGroup, takeGroup, returnGroup };
```

- [ ] **Step 4: Запустить — пройдёт**

Run: `node --test test_manual_publish_queue.test.js`
Expected: PASS (read + 3 group-теста).

- [ ] **Step 5: Добавить group-endpoints в `server.js`**

После блока endpoints (после строки 5733, до комментария `// ====== TRIGGER-IMMEDIATE`) вставить:

```javascript
app.post('/api/publishing/manual-queue/group/:unicResultId/take', requireAuth, async (req, res) => {
  try {
    const uid = req.session.user && req.session.user.id;
    res.json({ items: await mpq.takeGroup(pool, parseInt(req.params.unicResultId, 10), uid) });
  } catch (e) {
    res.status(e.httpStatus || 500).json({ error: e.message, taken_by: e.taken_by });
  }
});

app.post('/api/publishing/manual-queue/group/:unicResultId/return', requireAuth, async (req, res) => {
  try {
    const uid = req.session.user && req.session.user.id;
    res.json({ items: await mpq.returnGroup(pool, parseInt(req.params.unicResultId, 10), uid) });
  } catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});
```

- [ ] **Step 6: Commit**

```bash
git add manual_publish_queue.js server.js test_manual_publish_queue.test.js
git commit -m "feat(wp124): group take/return by unic_result_id with 'taken by operator' 409"
```

---

### Task 3: фронт — карточная группировка, мини-таблица платформ, частичная выкладка, копируемая ссылка на уник

**Files:**
- Modify: `public/index.html` — заменить MPQ-блок (`11869`–`12053`); сделать `#mpq-card` на весь экран (`14031`-`14032`).

Фронт-тестов нет (паттерн репо — live-smoke на дашборде). Шаги: реализация + проверка вживую.

- [ ] **Step 1: Заменить MPQ-блок целиком**

Заменить строки `11869`–`12053` (от `let mpqRows = [], ...` до закрывающей `}` функции `mpqPublish`, НЕ трогая `</script>` на 12055) на:

```javascript
let mpqRows = [], mpqSort = [], mpqFilters = {};
// WP#123: карточный вид — одна карточка на unic_result_id (= исходное видео × пак).
const MPQ_COLS = [
  { key: 'phone_number',     label: 'Тел. №',    filter: 'select' },
  { key: 'project_name',     label: 'Проект',    filter: 'select' },
  { key: 'pack_name',        label: 'Пак',       filter: 'select' },
  { key: 'platforms_label',  label: 'Платформы', filter: null },
  { key: 'source_video_url', label: 'Исх. видео',filter: null },
  { key: 'unic_video_url',   label: 'Уник. видео',filter: null },
  { key: 'planned_date',     label: 'План дата', filter: 'date' },
  { key: 'agg_status',       label: 'Статус',    filter: 'select' },
  { key: 'actions',          label: 'Действие',  filter: null },
];
const MPQ_STATUS = { queued: 'В очереди', in_progress: 'В работе', partial: 'Частично выложено', published: 'Выложено' };
const PLAT_SHORT = { instagram: 'IG', tiktok: 'TT', youtube: 'YT' };
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }

function mpqAgg(rows) {
  const pub = rows.filter(r => r.operator_status === 'published').length;
  const inp = rows.filter(r => r.operator_status === 'in_progress').length;
  if (rows.length && pub === rows.length) return 'published';
  if (pub > 0) return 'partial';
  if (inp > 0) return 'in_progress';
  return 'queued';
}

// Группируем плоские строки по unic_result_id в карточки.
function mpqCards() {
  const map = new Map();
  for (const r of mpqRows) {
    const k = r.unic_result_id;
    if (!map.has(k)) map.set(k, {
      unic_result_id: k, phone_number: r.phone_number, project_name: r.project_name,
      pack_name: r.pack_name, planned_date: r.planned_date,
      source_video_url: r.source_video_url, unic_video_url: r.unic_video_url,
      title: r.title, description: r.description, hashtags: r.hashtags, geo: r.geo, rows: [],
    });
    map.get(k).rows.push(r);
  }
  for (const card of map.values()) {
    card.agg_status = mpqAgg(card.rows);
    card.platforms_label = card.rows.map(r => {
      const p = PLAT_SHORT[(r.platform||'').toLowerCase()] || (r.platform||'');
      const mark = r.operator_status === 'published' ? ' ✓' : (r.operator_status === 'in_progress' ? ' ⏳' : '');
      return p + mark;
    }).join(' · ');
    const taker = card.rows.find(r => r.taken_by);
    card.taken_by = taker ? taker.taken_by : null;
  }
  return [...map.values()];
}

function mpqMatch(card, c, f) {
  if (!f) return true;
  if (c.filter === 'select' || c.filter === 'date') return String(card[c.key] ?? '') === f;
  return String(card[c.key] ?? '').toLowerCase().includes(f.toLowerCase());
}
function mpqApply() {
  let cards = mpqCards().filter(card => MPQ_COLS.every(c => mpqMatch(card, c, mpqFilters[c.key])));
  for (const s of [...mpqSort].reverse()) {
    cards.sort((a, b) => { const av = a[s.key] ?? '', bv = b[s.key] ?? ''; return (av > bv ? 1 : av < bv ? -1 : 0) * (s.dir === 'desc' ? -1 : 1); });
  }
  return cards;
}

function mpqFilterCell(c) {
  if (c.key === 'actions') return `<th class="px-2 py-1 !top-9"><button onclick="mpqReset()" title="Сброс сортировки и фильтров" class="text-indigo-700">⟲</button></th>`;
  if (!c.filter) return '<th class="px-2 py-1 !top-9"></th>';
  if (c.filter === 'select') {
    const vals = [...new Set(mpqCards().map(r => r[c.key]).filter(v => v !== null && v !== undefined && v !== ''))];
    const opts = vals.map(v => `<option value="${esc(v)}" ${mpqFilters[c.key] === String(v) ? 'selected' : ''}>${esc(c.key === 'agg_status' ? (MPQ_STATUS[v] || v) : v)}</option>`).join('');
    return `<th class="px-2 py-1 !top-9"><select onchange="mpqFilters['${c.key}']=this.value; mpqRender()" class="w-full border rounded px-1 py-0.5 text-xs"><option value="">все</option>${opts}</select></th>`;
  }
  if (c.filter === 'date') {
    return `<th class="px-2 py-1 !top-9"><input type="date" value="${esc(mpqFilters[c.key] || '')}" onchange="mpqFilters['${c.key}']=this.value; mpqRender()" class="w-full border rounded px-1 py-0.5 text-xs"></th>`;
  }
  return `<th class="px-2 py-1 !top-9"><input value="${esc(mpqFilters[c.key] || '')}" oninput="mpqFilters['${c.key}']=this.value; mpqRender()" class="w-full border rounded px-1 py-0.5 text-xs" placeholder="фильтр"></th>`;
}

function mpqCardActions(card) {
  // Claimable = есть queued-строки и НЕТ in_progress (никто сейчас не держит пак).
  // Покрывает и полностью queued, и частично выложенный возвращённый пак (codex P1):
  // published-платформы не мешают взять оставшиеся queued.
  const hasQueued = card.rows.some(r => r.operator_status === 'queued');
  const hasInProgress = card.rows.some(r => r.operator_status === 'in_progress');
  if (hasQueued && !hasInProgress)
    return `<button onclick="mpqGroupAction(${card.unic_result_id},'take')" class="px-2 py-1 rounded bg-indigo-600 text-white text-xs">Взять в работу</button>`;
  return `<button onclick="mpqOpenCard(${card.unic_result_id})" class="px-2 py-1 rounded bg-gray-200 text-xs">Открыть</button>`;
}

function mpqCardRowHtml(card) {
  const srcU = safeUrl(card.source_video_url), unicU = safeUrl(card.unic_video_url);
  const src = srcU ? `<a href="${esc(srcU)}" target="_blank" rel="noopener" class="text-indigo-600" onclick="event.stopPropagation()">исх.</a>` : '';
  const unic = unicU ? `<a href="${esc(unicU)}" target="_blank" rel="noopener" class="text-indigo-600" onclick="event.stopPropagation()">уник.</a>` : '';
  const taker = card.taken_by ? ` <span class="text-xs text-gray-400">(${esc(card.taken_by)})</span>` : '';
  return `<tr class="border-b hover:bg-gray-50 cursor-pointer" onclick="mpqOpenCard(${card.unic_result_id})">
    <td class="px-2 py-1.5">${esc(card.phone_number ?? '')}</td>
    <td class="px-2 py-1.5">${esc(card.project_name ?? '')}</td>
    <td class="px-2 py-1.5">${esc(card.pack_name ?? '')}</td>
    <td class="px-2 py-1.5">${esc(card.platforms_label)}</td>
    <td class="px-2 py-1.5">${src}</td><td class="px-2 py-1.5">${unic}</td>
    <td class="px-2 py-1.5">${esc(card.planned_date ?? '')}</td>
    <td class="px-2 py-1.5">${esc(MPQ_STATUS[card.agg_status] || card.agg_status)}${taker}</td>
    <td class="px-2 py-1.5" onclick="event.stopPropagation()">${mpqCardActions(card)}</td></tr>`;
}

function mpqRender() {
  const thead = document.getElementById('mpq-thead');
  const tbody = document.getElementById('mpq-tbody');
  const sortMark = k => { const s = mpqSort.find(x => x.key === k); return s ? (s.dir === 'asc' ? ' ▲' : ' ▼') : ''; };
  thead.innerHTML =
    '<tr class="bg-gray-50 border-b sticky top-0 z-10">' +
    MPQ_COLS.map(c => `<th class="px-2 py-2 h-9 text-left font-semibold cursor-pointer select-none z-20" onclick="mpqToggleSort('${c.key}', event)">${esc(c.label)}${sortMark(c.key)}</th>`).join('') +
    '</tr><tr class="bg-indigo-50 border-b">' + MPQ_COLS.map(mpqFilterCell).join('') + '</tr>';
  const cards = mpqApply();
  document.getElementById('mpq-empty').classList.toggle('hidden', cards.length > 0);
  const groups = new Map();
  for (const c of cards) { const k = c.phone_number ?? '—'; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(c); }
  let html = '';
  for (const [phone, grp] of groups) {
    html += `<tr class="bg-gray-100"><td colspan="${MPQ_COLS.length}" class="px-2 py-1 font-semibold text-gray-600">📱 Тел. № ${esc(phone)} <span class="font-normal text-gray-400">(${grp.length})</span></td></tr>`;
    html += grp.map(mpqCardRowHtml).join('');
  }
  tbody.innerHTML = html;
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

async function mpqGroupAction(unicResultId, action) {
  const r = await fetch(`/api/publishing/manual-queue/group/${unicResultId}/${action}`, { method: 'POST', credentials: 'same-origin' });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    if (r.status === 409) alert(e.taken_by ? `Задача взята оператором ${e.taken_by} в работу` : 'Задача уже у кого-то в работе');
    else alert('Ошибка: ' + (e.error || r.status));
    await mpqLoad();   // подгрузить актуальный статус записи
    return;
  }
  await mpqLoad();
}

// ===== Карточка пака (на весь экран) =====
let mpqCardUnic = null, mpqCopyVals = {};
function mpqGroupRows(unicResultId) { return mpqRows.filter(r => r.unic_result_id === unicResultId); }

function mpqOpenCard(unicResultId) {
  mpqCardUnic = unicResultId; mpqCopyVals = {};
  mpqRenderCard();
  document.getElementById('mpq-card').classList.remove('hidden');
}

function mpqPlatformRowHtml(r) {
  const plat = PLAT_SHORT[(r.platform||'').toLowerCase()] || (r.platform||'');
  const accUrl = safeUrl(r.account_url);
  const acc = accUrl ? `<a href="${esc(accUrl)}" target="_blank" rel="noopener" class="text-indigo-600">@${esc(r.account_username)}</a>` : ('@' + esc(r.account_username || ''));
  const st = MPQ_STATUS[r.operator_status] || r.operator_status;
  let linkCell = '<span class="text-gray-400">—</span>', actionCell = '';
  if (r.operator_status === 'in_progress') {
    linkCell = `<input type="url" id="mpq-purl-${r.id}" class="w-full border rounded px-1 py-0.5 text-xs" placeholder="https://...">`;
    actionCell = `<button onclick="mpqPublishPlatform(${r.id})" class="px-2 py-1 rounded bg-green-600 text-white text-xs">Отметить выложенным</button>`;
  } else if (r.operator_status === 'published') {
    const pubU = safeUrl(r.publication_url);
    if (pubU) { mpqCopyVals['purl_' + r.id] = pubU;
      linkCell = `<span onclick="mpqCopy(this,'purl_${r.id}')" class="cursor-pointer text-indigo-600 break-all" title="Клик — копировать">${esc(pubU)}</span>`; }
    actionCell = `<button onclick="mpqReworkPlatform(${r.id})" class="px-2 py-1 rounded bg-amber-500 text-white text-xs">Вернуть на доработку</button>`;
  }
  return `<tr class="border-b align-top"><td class="py-1 pr-2 font-medium">${esc(plat)}</td><td class="pr-2">${acc}</td><td class="pr-2">${esc(st)}</td><td class="pr-2 w-1/2">${linkCell}</td><td>${actionCell}</td></tr>`;
}

function mpqRenderCard() {
  const rows = mpqGroupRows(mpqCardUnic);
  if (!rows.length) { mpqCloseCard(); return; }
  const head = rows[0];
  const agg = mpqAgg(rows);
  const taker = rows.find(r => r.taken_by);
  const unicU = safeUrl(head.unic_video_url), srcU = safeUrl(head.source_video_url);
  mpqCopyVals = {};
  const copy = (key, label, val) => {
    if (val == null || val === '') return '';
    const text = Array.isArray(val) ? val.join(' ') : String(val);
    mpqCopyVals[key] = text;
    return `<div class="mb-2"><p class="text-xs text-gray-400">${esc(label)}</p><div onclick="mpqCopy(this,'${key}')" class="cursor-pointer bg-gray-50 rounded px-2 py-1 hover:bg-indigo-50 break-all" title="Клик — копировать">${esc(text)}</div></div>`;
  };
  const platRows = rows.map(mpqPlatformRowHtml).join('');
  const groupBtns = (agg === 'in_progress' || agg === 'partial')
    ? `<button onclick="mpqGroupAction(${mpqCardUnic},'return')" class="px-3 py-1.5 rounded bg-gray-200 text-sm">Вернуть пак в очередь</button>` : '';
  document.getElementById('mpq-card-body').innerHTML = `
    <div class="flex justify-between items-center mb-3">
      <h3 class="text-lg font-bold">Карточка выкладки — ${esc(head.pack_name || '')}</h3>
      <button onclick="mpqCloseCard()" class="text-gray-400 text-2xl">✕</button>
    </div>
    <p class="mb-3 text-sm">
      <span class="text-xs text-gray-400">Проект:</span> <b>${esc(head.project_name || '')}</b>
      · <span class="text-xs text-gray-400">Дата:</span> <b>${esc(head.planned_date || '')}</b>
      · <span class="text-xs text-gray-400">Статус:</span> <b>${esc(MPQ_STATUS[agg] || agg)}</b>
      ${taker ? `<span class="text-xs text-gray-400"> · в работе у ${esc(taker.taken_by)}</span>` : ''}
    </p>
    ${copy('title', 'Заголовок видео', head.title)}
    ${copy('description', 'Описание', head.description)}
    ${copy('hashtags', 'Хэштеги', head.hashtags)}
    ${copy('geo', 'Гео', head.geo)}
    ${unicU ? `<video src="${esc(unicU)}" controls class="w-full rounded-lg my-2 max-h-96"></video>` : ''}
    ${copy('unic_link', 'Ссылка на уник-видео', head.unic_video_url)}
    <div class="flex gap-3 text-sm my-2">
      ${srcU ? `<a href="${esc(srcU)}" target="_blank" rel="noopener" class="text-indigo-600">⬇ исходное</a>` : ''}
      ${unicU ? `<a href="${esc(unicU)}" target="_blank" rel="noopener" class="text-indigo-600">⬇ уник.</a>` : ''}
    </div>
    <div class="border-t mt-3 pt-3">
      <div class="flex justify-between items-center mb-2"><p class="font-semibold">Платформы пака</p>${groupBtns}</div>
      <table class="w-full text-sm"><thead><tr class="text-left text-gray-500 border-b">
        <th class="py-1 pr-2">Платформа</th><th class="pr-2">Аккаунт</th><th class="pr-2">Статус</th><th class="pr-2">Ссылка на публикацию</th><th></th></tr></thead>
        <tbody>${platRows}</tbody></table>
    </div>`;
}

function mpqCloseCard() { document.getElementById('mpq-card').classList.add('hidden'); mpqCardUnic = null; }
function mpqCopy(el, key) { navigator.clipboard.writeText(mpqCopyVals[key] || ''); const o = el.textContent; el.textContent = '✓ скопировано'; setTimeout(() => el.textContent = o, 900); }

async function mpqPublishPlatform(id) {
  const u = (document.getElementById('mpq-purl-' + id)?.value || '').trim();
  if (!u) { alert('Вставьте ссылку на публикацию'); return; }
  const iso = new Date().toISOString();
  const r = await fetch(`/api/publishing/manual-queue/${id}/publish`, {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ published_at: iso, post_url: u }) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); alert('Ошибка: ' + (e.error || r.status)); return; }
  await mpqLoad();
}
async function mpqReworkPlatform(id) {
  const r = await fetch(`/api/publishing/manual-queue/${id}/rework`, { method: 'POST', credentials: 'same-origin' });
  if (!r.ok) { const e = await r.json().catch(() => ({})); alert('Ошибка: ' + (e.error || r.status)); return; }
  await mpqLoad();
}

async function mpqLoad() {
  const r = await fetch('/api/publishing/manual-queue', { credentials: 'same-origin' });
  const data = await r.json();
  mpqRows = data.items || [];
  mpqRender();
  if (mpqCardUnic != null) mpqRenderCard();
}
```

(Поллинг `mpqStartPoll`/`mpqPoll` добавляется в Task 4 — в этой задаче `mpqLoad` его НЕ вызывает, чтобы Task 3 не падал с `ReferenceError` до Task 4. Codex P2.)

- [ ] **Step 2: Сделать карточку на весь экран**

`public/index.html:14031-14032` — заменить:

```html
<div id="mpq-card" class="hidden fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onclick="if(event.target===this)mpqCloseCard()">
  <div class="bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-auto p-5" id="mpq-card-body"></div>
```
на:
```html
<div id="mpq-card" class="hidden fixed inset-0 bg-black/50 z-50" onclick="if(event.target===this)mpqCloseCard()">
  <div class="bg-white w-full h-full overflow-auto p-6 max-w-5xl mx-auto" id="mpq-card-body"></div>
```

- [ ] **Step 3: Live-smoke (карточная группировка + частичная выкладка + копирование)**

Запустить дашборд локально (если не запущен): `node server.js` (или существующий pm2/dev-инстанс), открыть раздел «📤 Выкладка».
Проверить:
- одна строка-карточка на пак (а не 3 платформенные); колонка «Платформы» = `IG · TT · YT`;
- клик по строке → карточка на весь экран; внутри мини-таблица по платформам; поле «Ссылка на уник-видео» копируется по клику (✓ скопировано);
- «Взять в работу» (queued) → все платформы карточки `В работе`; вставить ссылку по одной платформе → «Отметить выложенным» → статус карточки `Частично выложено`; вставить остальные → `Выложено`;
- «Вернуть на доработку» по платформе → платформа снова `В работе`.

Чек seed-данных (если очередь пуста — взять из реального наполнителя или вставить временную фикстуру по образцу Task 2 setup, затем удалить).

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "feat(wp123): group manual-queue into per-pack fullscreen card with per-platform partial publish + copyable unic link"
```

---

### Task 4: фронт — поллинг ~5 c без затирания открытой карточки

**Files:**
- Modify: `public/index.html` (MPQ-блок — добавить поллинг)

- [ ] **Step 1: Добавить поллинг**

Вставить в MPQ-блок (перед `</script>` на ~12055, после `mpqLoad`):

```javascript
// WP#124: лёгкий поллинг ~5 c. Обновляет список и открытую карточку,
// но НЕ перерисовывает карточку, если оператор уже печатает ссылку (не затираем ввод).
let mpqPollTimer = null;
function mpqStartPoll() {
  if (mpqPollTimer) return;
  const ms = window.MPQ_POLL_MS || 5000;
  mpqPollTimer = setInterval(mpqPoll, ms);
}
function mpqCardHasUnsavedInput() {
  return [...document.querySelectorAll('#mpq-card-body input[id^="mpq-purl-"]')].some(i => i.value.trim() !== '');
}
async function mpqPoll() {
  const sec = document.getElementById('section-publishing-manual');
  if (!sec || sec.offsetParent === null) return;            // только когда раздел виден
  const r = await fetch('/api/publishing/manual-queue', { credentials: 'same-origin' }).catch(() => null);
  if (!r || !r.ok) return;
  const data = await r.json();
  mpqRows = data.items || [];
  mpqRender();
  if (mpqCardUnic != null && !mpqCardHasUnsavedInput()) mpqRenderCard();
}
```

- [ ] **Step 1b: Запустить поллинг из `mpqLoad`**

Теперь, когда `mpqStartPoll` определён, добавить его вызов в конец `mpqLoad` (в Task 3 он был намеренно опущён). Заменить в `mpqLoad`:

```javascript
  if (mpqCardUnic != null) mpqRenderCard();
}
```
на:
```javascript
  if (mpqCardUnic != null) mpqRenderCard();
  mpqStartPoll();
}
```

(`mpqStartPoll` идемпотентен — повторные вызовы `mpqLoad` не плодят таймеры.)

- [ ] **Step 2: Live-smoke (реалтайм + защита «уже в работе»)**

Открыть раздел в ДВУХ вкладках (или двумя операторами):
- во вкладке A «Взять в работу» пак → во вкладке B в течение ~5 c карточка пака сама переходит в «В работе (у …)» без ручного «Обновить»;
- во вкладке B нажать «Взять в работу» на том же паке → alert «Задача взята оператором <имя A> в работу», затем статус подтягивается;
- открыть карточку, начать печатать ссылку → дождаться тика поллинга → ввод НЕ затёрт; список при этом обновляется.

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "feat(wp124): ~5s polling for manual-queue, preserves in-progress link input"
```

---

### Task 5: финальная проверка + handoff

- [ ] **Step 1: Прогнать бэкенд-тесты**

Run: `node --test test_manual_publish_queue.test.js`
Expected: все PASS. Анти-регрессия: `node --test test_client_manual_publish.test.js`.

- [ ] **Step 2: Code review (superpowers:requesting-code-review) + codex review диффа**

Run: `git diff main HEAD | ~/.local/bin/codex review -` — применить P1, до 0 P1.
Особое внимание (codex не ловит cross-class факты): имена методов фронт↔бэк (`/group/:unicResultId/take|return`), форма 409 (`{error, taken_by}`), что `mpq.takeGroup` принимает `(pool, unicResultId, userId)` одинаково в endpoint и тесте.

- [ ] **Step 3: PR в `GenGo2/delivery-contenthunter`** (на одобрении Данила; деплой отдельным чекпоинтом ПОСЛЕ хотфикса #125).

Деплой: prod `git pull` + `pm2 restart autowarm` (или per-task spawn — сверить актуальный механизм). Без миграций. Live-smoke на проде: группировка, групповой take, частичная выкладка, поллинг, предупреждение «взято оператором XXX». Финальная визуальная приёмка — Данил.

- [ ] **Step 4: OpenProject #123 и #124** — статус-комментарии (house style), перевести в «Тестирование» после деплоя.

---

## Self-review (выполнено автором плана)

- **Покрытие спека #123:** ключ карточки `unic_result_id` → Task 1 (read) + Task 3 (`mpqCards`); мини-таблица платформ с per-platform handle → `mpqPlatformRowHtml`; копируемая ссылка на уник → `copy('unic_link', …)`; карточка на весь экран → Task 3 Step 2; имя аккаунта → мини-таблица. **#124:** групповой атомарный take + `taken_by_id` → Task 2; 409 «взято оператором XXX» → `takeGroup` + endpoint + `mpqGroupAction`; частичная выкладка → per-platform `publish`/`rework` + `mpqAgg` (`partial`); реалтайм → Task 4 поллинг; не затирать ввод → `mpqCardHasUnsavedInput`.
- **Миграция:** не нужна — `taken_by_id`/`published_by_id` уже в таблице (проверено в БД). Зафиксировано в «Контексте».
- **Плейсхолдеры:** нет — весь код приведён (фронт-блок заменяется целиком).
- **Согласованность:** `takeGroup(pool, unicResultId, userId)` / `returnGroup(pool, unicResultId)` — единые сигнатуры в `manual_publish_queue.js`, endpoint'ах и тестах; ключи `agg_status`/`platforms_label`/`taken_by`/`unic_result_id` согласованы между `mpqCards`, `MPQ_COLS`, рендером и фильтрами; статус `partial` добавлен в `MPQ_STATUS`.
- **YAGNI:** GET group-endpoint не вводим — карточка собирается из уже загруженных `mpqRows`; per-id `take`/`return` остаются для обратной совместимости, но новый UI их не использует.
```
