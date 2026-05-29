# WP#187 «Выложено авто» + отмена для ручной выкладки — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать оператору кнопку «Выложено авто» в карточке ручной выкладки (закрывает строку без обязательной ссылки, считается авто-успехом) и кнопку «Отменить» (возврат в «В работе»).

**Architecture:** Approach A — новый терминальный `operator_status='published_auto'`; `publish_queue` не мутируем; атрибуция «как авто» делается в `pipeline_funnel.js`. Транзакционные переходы в `manual_publish_queue.js`, роуты в `server.js`, рендер в `public/index.html` + `public/mpq_pure.js`, TG-отчёт в `daily_publish_report.js`.

**Tech Stack:** Node.js (Express, `pg`), Postgres (`openclaw`), ванильный JS фронт + Tailwind CDN, тесты `node --test`.

**Репозиторий кода:** `autowarm-testbench` (НЕ contenthunter). Все пути ниже — относительно корня `autowarm-testbench`. План и spec лежат в `contenthunter`.

**Спека:** `contenthunter/docs/superpowers/specs/2026-05-29-wp187-manual-publish-auto-design.md`

**Пред-условие исполнителю:** перед началом завести изолированную ветку/worktree В РЕПОЗИТОРИИ `autowarm-testbench` (общий чекаут — `git worktree add`, НЕ `checkout -b`). Все коммиты — в неё.

---

## Файловая карта

| Файл | Что меняем |
|---|---|
| `migrations/20260529_wp187_published_auto_status.sql` (+ `__rollback.sql`) | CHECK `ck_manual_pub_status` + `'published_auto'` |
| `manual_publish_queue.js` | `markPublishedAuto`, `cancelPublishedAuto` + экспорт |
| `server.js` | флаг `MANUAL_PUBLISHED_AUTO_ENABLED`, роуты `publish-auto`/`cancel-auto`, флаг в ответе `manual-queue` |
| `public/mpq_pure.js` | перенос `mpqAgg` сюда + учёт `published_auto` |
| `public/index.html` | `MPQ_STATUS`, `mpqPlatformRowHtml`, `platforms_label`, `mpqPublishAutoPlatform`/`mpqCancelAutoPlatform`, `mpqLoad`, 3 вызова `mpqAgg` |
| `pipeline_funnel.js` | Q2 (+`auto_acknowledged`), `assembleFunnel` (lost/sr), Q4 (исключить `published_auto`) |
| `daily_publish_report.js` | строка TG-отчёта |
| `test_manual_publish_queue.test.js` | тесты переходов |
| `test_mpq_pure.test.js` | тесты `mpqAgg` |
| `test_pipeline_funnel.test.js` (создать) | тест сверки воронки |

---

## Task 1: Миграция — добавить `published_auto` в CHECK

**Files:**
- Create: `migrations/20260529_wp187_published_auto_status.sql`
- Create: `migrations/20260529_wp187_published_auto_status__rollback.sql`

- [ ] **Step 1: Написать миграцию**

`migrations/20260529_wp187_published_auto_status.sql`:
```sql
-- WP#187: новый терминальный operator_status 'published_auto' (оператор подтвердил,
-- что слот уже выложен автовыкладкой). Считается авто-успехом в воронке.
ALTER TABLE validator_manual_publish_queue DROP CONSTRAINT IF EXISTS ck_manual_pub_status;
ALTER TABLE validator_manual_publish_queue
  ADD CONSTRAINT ck_manual_pub_status
  CHECK (operator_status = ANY (ARRAY['queued','in_progress','published','published_auto']));
```

- [ ] **Step 2: Написать rollback**

`migrations/20260529_wp187_published_auto_status__rollback.sql`:
```sql
-- Откат WP#187. Сначала вернуть любые published_auto в in_progress, иначе CHECK не наложится.
UPDATE validator_manual_publish_queue SET operator_status='in_progress' WHERE operator_status='published_auto';
ALTER TABLE validator_manual_publish_queue DROP CONSTRAINT IF EXISTS ck_manual_pub_status;
ALTER TABLE validator_manual_publish_queue
  ADD CONSTRAINT ck_manual_pub_status
  CHECK (operator_status = ANY (ARRAY['queued','in_progress','published']));
```

- [ ] **Step 3: Накатить миграцию**

Run: `PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f migrations/20260529_wp187_published_auto_status.sql`
Expected: `ALTER TABLE` (дважды).

- [ ] **Step 4: Проверить ограничение**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_manual_pub_status';"
```
Expected: содержит `'published_auto'`.

- [ ] **Step 5: Commit**

```bash
git add migrations/20260529_wp187_published_auto_status.sql migrations/20260529_wp187_published_auto_status__rollback.sql
git commit -m "feat(wp187): миграция — operator_status published_auto в CHECK"
```

---

## Task 2: Переходы `markPublishedAuto` / `cancelPublishedAuto`

**Files:**
- Modify: `manual_publish_queue.js` (после `reworkItem`, до `listGroup`; экспорт в конце)
- Test: `test_manual_publish_queue.test.js`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `test_manual_publish_queue.test.js` (перед `after`-хуком ничего не трогаем — `node:test` хуки уже объявлены сверху):
```js
// ─── WP#187: published_auto ───────────────────────────────────────────────────

test('markPublishedAuto: in_progress → published_auto без ссылки, слот не трогается', async () => {
  await setup();
  await mpq.takeGroup(pool, RESULT, USER_A);
  const out = await mpq.markPublishedAuto(pool, Q_IG, {});
  assert.equal(out.operator_status, 'published_auto');
  assert.equal(out.post_url, null);
  const slot = await pool.query('SELECT matched_post_url FROM validator_schedule_slots WHERE id=$1', [SLOT]);
  assert.equal(slot.rows[0].matched_post_url, null, 'слот не размечается');
});

test('markPublishedAuto: ссылка пишется в строку очереди, НЕ в слот', async () => {
  await setup();
  await mpq.takeGroup(pool, RESULT, USER_A);
  const out = await mpq.markPublishedAuto(pool, Q_TT, { postUrl: 'https://tiktok.com/@x/video/1' });
  assert.equal(out.operator_status, 'published_auto');
  assert.equal(out.post_url, 'https://tiktok.com/@x/video/1');
  const slot = await pool.query('SELECT matched_post_url FROM validator_schedule_slots WHERE id=$1', [SLOT]);
  assert.equal(slot.rows[0].matched_post_url, null, 'слот НЕ размечается даже при ссылке');
});

test('markPublishedAuto: из не-in_progress → 409', async () => {
  await setup(); // строки queued
  await assert.rejects(() => mpq.markPublishedAuto(pool, Q_IG, {}), /Expected status 'in_progress'/);
});

test('cancelPublishedAuto: published_auto → in_progress, чистит url, taken_by_id=userId', async () => {
  await setup();
  await mpq.takeGroup(pool, RESULT, USER_A);
  await mpq.markPublishedAuto(pool, Q_YT, { postUrl: 'https://youtube.com/shorts/zzz' });
  const out = await mpq.cancelPublishedAuto(pool, Q_YT, USER_B);
  assert.equal(out.operator_status, 'in_progress');
  assert.equal(out.post_url, null);
  assert.equal(out.taken_by, 'wp123_anna');
});

test('cancelPublishedAuto: из не-published_auto → 409', async () => {
  await setup();
  await mpq.takeGroup(pool, RESULT, USER_A);
  await assert.rejects(() => mpq.cancelPublishedAuto(pool, Q_IG, USER_A), /Expected status 'published_auto'/);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test test_manual_publish_queue.test.js`
Expected: FAIL — `mpq.markPublishedAuto is not a function`.

- [ ] **Step 3: Реализовать переходы**

В `manual_publish_queue.js` после функции `reworkItem` (строка ~148) вставить:
```js
// WP#187: оператор подтверждает, что слот уже выложен автовыкладкой.
// Терминальный статус published_auto. Ссылка опциональна и пишется ТОЛЬКО в строку
// очереди (post_url) для отображения — slot.matched_post_url НЕ трогаем (codex P1:
// иначе слот цепляется к дисплейной метрике «реактивной ручной»). Один UPDATE —
// транзакция не нужна (в отличие от markPublished/reworkItem, что писали и в слот).
async function markPublishedAuto(pool, id, { postUrl } = {}) {
  const url = postUrl && String(postUrl).trim() ? String(postUrl).trim() : null;
  const { rows } = await pool.query(`
    UPDATE validator_manual_publish_queue
    SET operator_status='published_auto', published_at=now(), post_url=$2, updated_at=now()
    WHERE id=$1 AND operator_status='in_progress' AND cancelled_at IS NULL
    RETURNING id`, [id, url]);
  if (!rows.length) await failTransition(pool, id, 'in_progress');
  return getItem(pool, id);
}

// WP#187: отмена ошибочного «Выложено авто» — возврат в in_progress у текущего оператора.
// Слот не трогали при подтверждении → откатывать нечего; чистим только строку очереди.
async function cancelPublishedAuto(pool, id, userId) {
  const { rows } = await pool.query(`
    UPDATE validator_manual_publish_queue
    SET operator_status='in_progress', post_url=NULL, published_at=NULL,
        taken_by_id=$2, taken_at=now(), updated_at=now()
    WHERE id=$1 AND operator_status='published_auto' AND cancelled_at IS NULL
    RETURNING id`, [id, userId]);
  if (!rows.length) await failTransition(pool, id, 'published_auto');
  return getItem(pool, id);
}
```

Обновить `module.exports` (строка ~213) — добавить две функции:
```js
module.exports = { httpErr, accountUrl, rowToDict, JOINED_SELECT, listQueue, getItem,
  takeItem, returnItem, markPublished, reworkItem, markPublishedAuto, cancelPublishedAuto,
  listGroup, takeGroup, returnGroup };
```

- [ ] **Step 4: Запустить — зелёные**

Run: `node --test test_manual_publish_queue.test.js`
Expected: PASS (включая ранее существовавшие).

- [ ] **Step 5: Commit**

```bash
git add manual_publish_queue.js test_manual_publish_queue.test.js
git commit -m "feat(wp187): переходы markPublishedAuto/cancelPublishedAuto + тесты"
```

---

## Task 3: Роуты сервера + kill-switch + флаг для фронта

**Files:**
- Modify: `server.js` (флаг ~строка 22; роуты после 5819; ответ `manual-queue` ~5786)

- [ ] **Step 1: Объявить kill-switch**

Рядом с другими флагами (после строки 22, `PUBLISH_TAG_FILL_ENABLED`):
```js
const MANUAL_PUBLISHED_AUTO_ENABLED = process.env.MANUAL_PUBLISHED_AUTO_ENABLED !== 'false';
```

- [ ] **Step 2: Прокинуть флаг в ответ списка**

Заменить тело `app.get('/api/publishing/manual-queue', ...)` (строки 5786–5791):
```js
app.get('/api/publishing/manual-queue', requireAuth, async (req, res) => {
  try {
    const status = req.query.status || null;
    res.json({ items: await mpq.listQueue(pool, status), published_auto_enabled: MANUAL_PUBLISHED_AUTO_ENABLED });
  } catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});
```

- [ ] **Step 3: Добавить роуты**

После роута `/rework` (строка 5819), перед блоком WP#124 group:
```js
// WP#187: подтвердить авто-выкладку (опц. ссылка) / отменить ошибочное подтверждение.
app.post('/api/publishing/manual-queue/:id/publish-auto', requireAuth, async (req, res) => {
  if (!MANUAL_PUBLISHED_AUTO_ENABLED) return res.status(403).json({ error: 'feature disabled' });
  try {
    const { post_url } = req.body || {};
    res.json(await mpq.markPublishedAuto(pool, parseInt(req.params.id, 10), { postUrl: post_url }));
  } catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});

app.post('/api/publishing/manual-queue/:id/cancel-auto', requireAuth, async (req, res) => {
  if (!MANUAL_PUBLISHED_AUTO_ENABLED) return res.status(403).json({ error: 'feature disabled' });
  try {
    const uid = req.session.user && req.session.user.id;
    res.json(await mpq.cancelPublishedAuto(pool, parseInt(req.params.id, 10), uid));
  } catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});
```

- [ ] **Step 4: Проверить синтаксис**

Run: `node -c server.js`
Expected: без вывода (OK).

- [ ] **Step 5: Commit**

```bash
git add server.js
git commit -m "feat(wp187): роуты publish-auto/cancel-auto + kill-switch MANUAL_PUBLISHED_AUTO_ENABLED"
```

---

## Task 4: Перенести `mpqAgg` в `mpq_pure.js` с учётом `published_auto`

**Files:**
- Modify: `public/mpq_pure.js` (добавить `mpqAgg` + экспорт)
- Modify: `public/index.html` (удалить инлайн `mpqAgg`, обновить 3 вызова)
- Test: `test_mpq_pure.test.js`

- [ ] **Step 1: Написать падающие тесты**

Сначала добавить `mpqAgg` в существующую деструктуризацию импорта в шапке файла (строка 4):
```js
const { mpqStatusVisible, mpqDiff, mpqPlatformVisible, mpqDateInRange, mpqCurrentWeekRange, mpqIsClaimable, mpqAgg } = require('./public/mpq_pure');
```
Затем добавить тесты в конец `test_mpq_pure.test.js` (отдельный `require` для `mpqAgg` НЕ добавлять — он уже в импорте выше):
```js
test('mpqAgg: все строки закрыты (published/published_auto) → published', () => {
  assert.equal(mpqAgg(['published', 'published_auto']), 'published');
  assert.equal(mpqAgg(['published_auto', 'published_auto']), 'published');
});
test('mpqAgg: часть закрыта → partial', () => {
  assert.equal(mpqAgg(['published_auto', 'queued']), 'partial');
  assert.equal(mpqAgg(['published', 'in_progress']), 'partial');
});
test('mpqAgg: есть in_progress без закрытых → in_progress; иначе queued', () => {
  assert.equal(mpqAgg(['in_progress', 'queued']), 'in_progress');
  assert.equal(mpqAgg(['queued', 'queued']), 'queued');
  assert.equal(mpqAgg([]), 'queued');
});
```

- [ ] **Step 2: Запустить — падает**

Run: `node --test test_mpq_pure.test.js`
Expected: FAIL — `mpqAgg is not a function`.

- [ ] **Step 3: Реализовать в `mpq_pure.js`**

Перед строкой `const api = {...}` (строка ~68) вставить:
```js
  // Агрегат статуса пака по статусам строк. closed = published | published_auto
  // (терминальные успехи; WP#187). statuses — массив operator_status.
  function mpqAgg(statuses) {
    const closed = statuses.filter(s => s === 'published' || s === 'published_auto').length;
    const inp = statuses.filter(s => s === 'in_progress').length;
    if (statuses.length && closed === statuses.length) return 'published';
    if (closed > 0) return 'partial';
    if (inp > 0) return 'in_progress';
    return 'queued';
  }
```
Добавить `mpqAgg` в объект `api`:
```js
  const api = { mpqStatusVisible, mpqDiff, mpqPlatformVisible, mpqDateInRange, mpqCurrentWeekRange, mpqIsClaimable, mpqAgg };
```

- [ ] **Step 4: Убрать инлайн-`mpqAgg` из `index.html` и поправить вызовы**

Удалить определение `function mpqAgg(rows){...}` (строки 12229–12236 в `public/index.html`).
Заменить 3 вызова (передаём массив статусов вместо rows):
- строка ~12252 `card.agg_status = mpqAgg(card.rows);` → `card.agg_status = mpqAgg(card.rows.map(r => r.operator_status));`
- строка ~12519 (в `mpqCardComputeSig`) `... + '#' + mpqAgg(rows);` → `... + '#' + mpqAgg(rows.map(r => r.operator_status));`
- строка ~12550 (в `mpqRenderCard`) `const agg = mpqAgg(rows);` → `const agg = mpqAgg(rows.map(r => r.operator_status));`

- [ ] **Step 5: Запустить — зелёные**

Run: `node --test test_mpq_pure.test.js`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add public/mpq_pure.js public/index.html test_mpq_pure.test.js
git commit -m "feat(wp187): mpqAgg → mpq_pure.js, учёт published_auto в агрегате пака"
```

---

## Task 5: Фронтенд — кнопки «Выложено авто» / «Отменить»

**Files:**
- Modify: `public/index.html` (`MPQ_STATUS` ~12224, `mpqPlatformRowHtml` ~12528, `platforms_label` ~12255, новые JS-функции после `mpqReworkPlatform` ~12611, `mpqLoad` ~12613)

- [ ] **Step 1: Добавить статус в `MPQ_STATUS`**

Строка 12224 → добавить ключ:
```js
const MPQ_STATUS = { queued: 'В очереди', in_progress: 'В работе', partial: 'Частично выложено', published: 'Выложено', published_auto: 'Выложено авто' };
```

- [ ] **Step 2: Переписать `mpqPlatformRowHtml`**

Заменить функцию целиком (строки 12528–12544):
```js
function mpqPlatformRowHtml(r) {
  const plat = PLAT_SHORT[(r.platform||'').toLowerCase()] || (r.platform||'');
  const accUrl = safeUrl(r.account_url);
  const acc = accUrl ? `<a href="${esc(accUrl)}" target="_blank" rel="noopener" class="text-indigo-600">@${esc(r.account_username)}</a>` : ('@' + esc(r.account_username || ''));
  let st = esc(MPQ_STATUS[r.operator_status] || r.operator_status);
  let linkCell = '<span class="text-gray-400">—</span>', actionCell = '';
  if (r.operator_status === 'in_progress') {
    linkCell = `<input type="url" id="mpq-purl-${r.id}" class="w-full border rounded px-1 py-0.5 text-xs" placeholder="https://...">`;
    actionCell = `<button onclick="mpqPublishPlatform(${r.id})" class="px-2 py-1 rounded bg-green-600 text-white text-xs">Отметить выложенным</button>`;
    if (window.MPQ_PUBLISHED_AUTO_ENABLED !== false)
      actionCell += ` <button onclick="mpqPublishAutoPlatform(${r.id})" class="px-2 py-1 rounded border border-indigo-600 text-indigo-600 text-xs">Выложено авто</button>`;
  } else if (r.operator_status === 'published') {
    const pubU = safeUrl(r.publication_url);
    if (pubU) { mpqCopyVals['purl_' + r.id] = pubU;
      linkCell = `<span onclick="mpqCopy(this,'purl_${r.id}')" class="cursor-pointer text-indigo-600 break-all" title="Клик — копировать">${esc(pubU)}</span>`; }
    actionCell = `<button onclick="mpqReworkPlatform(${r.id})" class="px-2 py-1 rounded bg-amber-500 text-white text-xs">Вернуть на доработку</button>`;
  } else if (r.operator_status === 'published_auto') {
    st = `<span class="px-2 py-0.5 rounded-full text-xs font-semibold" style="color:#4a45c2;background:#ecebfb">${esc(MPQ_STATUS.published_auto)}</span>`;
    const pubU = safeUrl(r.publication_url);
    if (pubU) { mpqCopyVals['purl_' + r.id] = pubU;
      linkCell = `<span onclick="mpqCopy(this,'purl_${r.id}')" class="cursor-pointer text-indigo-600 break-all" title="Клик — копировать">${esc(pubU)}</span>`; }
    else linkCell = `<span class="text-gray-400">— выложено автовыкладкой</span>`;
    actionCell = `<button onclick="mpqCancelAutoPlatform(${r.id})" class="px-2 py-1 rounded bg-gray-100 text-gray-600 text-xs">Отменить</button>`;
  }
  return `<tr class="border-b align-top"><td class="py-1 pr-2 font-medium">${esc(plat)}</td><td class="pr-2">${acc}</td><td class="pr-2">${st}</td><td class="pr-2 w-1/2">${linkCell}</td><td>${actionCell}</td></tr>`;
}
```
(Изменение в `<td>${st}</td>` — без `esc()`, т.к. `st` уже либо экранированная строка, либо готовый HTML-бейдж.)

- [ ] **Step 3: Пометка в `platforms_label`**

Строка 12255 заменить тернарник `mark`:
```js
const mark = r.operator_status === 'published' ? ' ✓'
           : r.operator_status === 'published_auto' ? ' ⚡'
           : r.operator_status === 'in_progress' ? ' ⏳' : '';
```

- [ ] **Step 4: Новые JS-функции действий**

После `mpqReworkPlatform` (строка ~12611) вставить:
```js
async function mpqPublishAutoPlatform(id) {
  const u = (document.getElementById('mpq-purl-' + id)?.value || '').trim();
  const r = await fetch(`/api/publishing/manual-queue/${id}/publish-auto`, {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(u ? { post_url: u } : {}) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); alert('Ошибка: ' + (e.error || r.status)); return; }
  await mpqLoad();
}
async function mpqCancelAutoPlatform(id) {
  const r = await fetch(`/api/publishing/manual-queue/${id}/cancel-auto`, { method: 'POST', credentials: 'same-origin' });
  if (!r.ok) { const e = await r.json().catch(() => ({})); alert('Ошибка: ' + (e.error || r.status)); return; }
  await mpqLoad();
}
```

- [ ] **Step 5: Прочитать флаг в `mpqLoad`**

В `mpqLoad` (строка ~12613) после `const data = await r.json();` добавить:
```js
  window.MPQ_PUBLISHED_AUTO_ENABLED = data.published_auto_enabled !== false;
```

- [ ] **Step 6: Проверить, что фронт грузится (smoke)**

Run (если сервер тестбенча поднят):
```bash
curl -s localhost:3000/mpq_pure.js | grep -c mpqAgg
```
Expected: `>= 1`. (Если сервер не поднят — пропустить, проверка в Task 9 live-smoke.)

- [ ] **Step 7: Commit**

```bash
git add public/index.html
git commit -m "feat(wp187): фронт — кнопки «Выложено авто»/«Отменить» + бейдж + флаг"
```

---

## Task 6: Воронка — учёт `published_auto` как авто-успех

**Files:**
- Modify: `pipeline_funnel.js` (Q2 ~123, `assembleFunnel` ~10–58, Q4 ~175)
- Test: `test_pipeline_funnel.test.js` (создать)

- [ ] **Step 1: Написать падающий тест сверки**

Create `test_pipeline_funnel.test.js`:
```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { assembleFunnel } = require('./pipeline_funnel');

test('assembleFunnel: published_auto идёт в Авто, не в Потеряно; сверка сходится', () => {
  const f = assembleFunnel({
    plan: 10, uniqualized: 10, autotask: 10, auto_published: 5, auto_inflight: 0,
    manual_handoff: 5, manual_handoff_published: 2, manual_published_total: 2,
    proactive_manual_notdispatched: 0, auto_acknowledged: 3,
    loss_breakdown: [], slots_planned: 10, slots_with_queue: 10,
  });
  assert.equal(f.auto_acknowledged, 3);
  // 5 авто + 3 подтв.авто + 2 ручная = 10 → Потеряно 0
  assert.equal(f.lost_count, 0);
  assert.equal(f.sr_total, 1);
});

test('assembleFunnel: без auto_acknowledged поведение прежнее', () => {
  const f = assembleFunnel({
    plan: 10, uniqualized: 10, autotask: 10, auto_published: 5, auto_inflight: 0,
    manual_handoff: 5, manual_handoff_published: 2, manual_published_total: 2,
    proactive_manual_notdispatched: 0, loss_breakdown: [], slots_planned: 10, slots_with_queue: 10,
  });
  assert.equal(f.auto_acknowledged, 0);
  assert.equal(f.lost_count, 3); // 10 - 5 - 0 - 2
});
```

- [ ] **Step 2: Запустить — падает**

Run: `node --test test_pipeline_funnel.test.js`
Expected: FAIL (`lost_count` = 5, нет `auto_acknowledged`).

- [ ] **Step 3: Учесть `auto_acknowledged` в `assembleFunnel`**

В `pipeline_funnel.js` в начале `assembleFunnel` (после строки 18, `manual_published_total`) добавить:
```js
  const auto_acknowledged = nn(raw.auto_acknowledged);
```
Заменить строку 23 (`lost_count`):
```js
  const lost_count = clamp0(plan - auto_published - auto_acknowledged - manual_published_total);
```
В возвращаемом объекте (строка ~42) добавить `auto_acknowledged` в список и поправить `sr_total` (строка 49):
```js
    plan, uniqualized, autotask, auto_published, auto_acknowledged, auto_inflight,
```
```js
    sr_total: plan > 0 ? round3((auto_published + auto_acknowledged + manual_published_total) / plan) : null,
```

- [ ] **Step 4: Запустить — зелёные**

Run: `node --test test_pipeline_funnel.test.js`
Expected: PASS.

- [ ] **Step 5: Подсчёт `auto_acknowledged` в Q2 + исключение из Q4**

Заменить Q2 (строки 123–131) — считаем оба статуса. `auto_acknowledged` дедуплицируется
против уже-авто-выложенных строк (codex P1): если для той же (unic_result × account × platform)
есть `publish_queue.status='done'`, слот уже в `auto_published` — повторно не считаем.
```js
  const q2 = await pool.query(`
    SELECT
      COUNT(*) FILTER (WHERE m.operator_status = 'published')      AS manual_published_total,
      COUNT(*) FILTER (WHERE m.operator_status = 'published_auto'
        AND NOT EXISTS (
          SELECT 1 FROM publish_queue pq2
          WHERE pq2.unic_result_id = m.unic_result_id
            AND LOWER(pq2.account_username) = LOWER(m.account_username)
            AND LOWER(pq2.platform) = LOWER(m.platform)
            AND pq2.status = 'done')
      ) AS auto_acknowledged
    FROM validator_manual_publish_queue m
    LEFT JOIN validator_schedule_slots s ON s.id = m.slot_id
    WHERE COALESCE(s.slot_date, m.planned_date) >= $1::date
      AND COALESCE(s.slot_date, m.planned_date) <  $2::date
      ${f2.conds.length ? 'AND ' + f2.conds.join(' AND ') : ''}
  `, [slotDateFrom, slotDateToExcl, ...f2.params]);
```
В Q4 (строка ~175) расширить `NOT EXISTS`:
```sql
      AND NOT EXISTS (
        SELECT 1 FROM validator_manual_publish_queue m
        WHERE m.slot_id = s.id AND m.operator_status IN ('published','published_auto'))
```
В сборке результата (строка ~182) добавить проброс:
```js
    manual_published_total: q2.rows[0].manual_published_total,
    auto_acknowledged: q2.rows[0].auto_acknowledged,
```

- [ ] **Step 6: Проверить синтаксис + тесты**

Run: `node -c pipeline_funnel.js && node --test test_pipeline_funnel.test.js`
Expected: OK + PASS.

- [ ] **Step 7: Commit**

```bash
git add pipeline_funnel.js test_pipeline_funnel.test.js
git commit -m "feat(wp187): воронка — published_auto как авто-успех (Q2/Q4/сверка)"
```

---

## Task 7: Рендер воронки (дашборд + TG-отчёт)

**Files:**
- Modify: `public/index.html` (блок рендера воронки ~11947, сверка ~11989–11993)
- Modify: `daily_publish_report.js` (~строка 225)

- [ ] **Step 1: Строка в дашборде**

В `public/index.html` после строки 11947 (`['Авто: выложено', funnel.auto_published, 'text-green-600'],`) добавить:
```js
    ['Авто: подтв. оператором', funnel.auto_acknowledged, 'text-green-500'],
```

- [ ] **Step 2: Поправить сверку**

Строка 11989 (`recOk`):
```js
  const recOk = (funnel.auto_published + funnel.auto_acknowledged + funnel.manual_published_total + funnel.lost_count) === funnel.plan;
```
Строка 11993 (текст сверки) — заменить терм «Авто»:
```js
      `Сверка: Авто ${funnel.auto_published + funnel.auto_acknowledged} + Ручная ${funnel.manual_published_total} + Потеряно ${funnel.lost_count} = План ${funnel.plan} ${recOk ? '✓' : '✗'}</div>` +
```

- [ ] **Step 3: Строка в TG-отчёте**

В `daily_publish_report.js` заменить строку 225 (`Выложено авто: ...`):
```js
    lines.push(`Выложено авто: ${funnel.auto_published}${funnel.auto_acknowledged ? ` (+${funnel.auto_acknowledged} подтв. оператором)` : ''}`);
```

- [ ] **Step 4: Проверить синтаксис**

Run: `node -c daily_publish_report.js`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add public/index.html daily_publish_report.js
git commit -m "feat(wp187): рендер воронки — строка «подтв. оператором» + сверка (дашборд+TG)"
```

---

## Task 8: Верификация смежных модулей (защита от редиспатча)

**Files:** проверка — `manual_queue_assign.js`, `server.js` (dispatch-гард ~6704), `retry_controller.js:49`

> **Анализ редиспатча (codex P2).** `published_auto` намеренно не трогает `publish_queue`/`slot.matched_post_url`. Защита от повторной авто-выкладки реактивных строк — durable-маркер `manual_handoff_at` на строке `publish_queue`: он проставляется при хэндоффе (`retry_controller.js` handoffToManual / server.js) и НЕ очищается. `retry_controller` берёт в ретрай только `pq.status='failed' AND pq.manual_handoff_at IS NULL` → строка, отданная в ручную, исключена из ретрая навсегда, независимо от `operator_status`. То есть `matched_post_url` НЕ был защитой от редиспатча (он для расписания/воронки); защита = `manual_handoff_at`. Для проактивных ручных строк (без хэндоффа) экспозиция идентична существующему статусу `published` — нового регресса нет. Шаги ниже это подтверждают.

- [ ] **Step 1: Populator не реквеуит `published_auto`**

`enqueueManualRow` (manual_queue_assign.js:42) идемпотентен по `ON CONFLICT (unic_result_id, account_username, platform) WHERE cancelled_at IS NULL DO NOTHING`. Строка `published_auto` имеет `cancelled_at IS NULL` → повторный INSERT не пройдёт.
Проверить кодом:
```bash
grep -n "ON CONFLICT" manual_queue_assign.js
```
Expected: видно `WHERE cancelled_at IS NULL DO NOTHING`. ✔ изменений не нужно.

- [ ] **Step 2: Dispatch-гард терминальный статус не блокирует**

`operator_status IN ('queued','in_progress')` (server.js:6704/6723) — `published_auto` не входит → авто-диспатч не блокируется (ожидаемо: слот уже выложен).
Проверить:
```bash
grep -n "operator_status IN ('queued','in_progress')" server.js
```
Expected: 2 совпадения, `published_auto` отсутствует. ✔ изменений не нужно.

- [ ] **Step 2b: Durable-защита от редиспатча через `manual_handoff_at`**

Подтвердить, что ретрай-контроллер durable-исключает отданные в ручную строки независимо от `operator_status`:
```bash
grep -n "status = 'failed' AND pq.manual_handoff_at IS NULL\|manual_handoff_at" retry_controller.js | head
```
Expected: SELECT-условие (строка ~49) содержит `pq.manual_handoff_at IS NULL` → строка с проставленным `manual_handoff_at` (реактивный хэндофф) в ретрай не попадёт. ✔ `published_auto` не открывает путь к дублю для реактивных строк; для проактивных — поведение как у `published` (без регресса).

- [ ] **Step 3: Зафиксировать вывод в spec/evidence (опц.)**

Без коммита кода — отметить в чеклисте плана, что смежные модули верифицированы.

---

## Task 9: Прогон всех тестов + live-smoke + финальный коммит

- [ ] **Step 1: Полный прогон unit-тестов очереди и pure**

Run:
```bash
node --test test_manual_publish_queue.test.js test_mpq_pure.test.js test_pipeline_funnel.test.js
```
Expected: все PASS, 0 fail.

- [ ] **Step 2: Регрессия — смежные тесты ручной выкладки**

Run:
```bash
node --test test_manual_queue_assign_live.test.js test_dispatch_manual_guard.test.js
```
Expected: PASS (поведение `queued`/`in_progress` не изменилось).

- [ ] **Step 3: Live-smoke полного цикла (если БД/сервер доступны)**

На тестовой строке (взять id из `validator_manual_publish_queue` с `operator_status='in_progress'` тестового пака, либо через `takeGroup` фикстуры): пройти `in_progress → publish-auto → cancel-auto → in_progress` curl-запросами к локальному серверу с сессией оператора. Проверить, что пак-агрегат и воронка ведут себя ожидаемо. Зафиксировать результат в evidence-файле.

- [ ] **Step 4: `codex review` диффа ветки**

Run: `git diff origin/main...HEAD | ~/.local/bin/codex review -`
Раунды до 0 P1 (фиксить найденное).

- [ ] **Step 5: Финальный коммит/пуш по решению Данила**

Не пушить без явной отмашки. После согласования — пуш ветки `autowarm-testbench`, деплой по принятому пути (PM2, не systemd), миграцию накатить на прод-БД (контейнер openclaw), kill-switch `MANUAL_PUBLISHED_AUTO_ENABLED` наготове.

---

## Self-review (выполнено автором плана)

- **Покрытие спеки:** §1 миграция → Task 1; §2 переходы → Task 2; роуты+kill-switch → Task 3; §3 mpqAgg → Task 4; §4 фронт → Task 5; §5 воронка → Task 6+7; §6 смежные → Task 8; §7 kill-switch → Task 3/5; §8 тесты → Task 2/4/6/9. Пробелов нет.
- **Плейсхолдеры:** нет «TBD/TODO»; код приведён во всех шагах.
- **Согласованность типов:** `markPublishedAuto`/`cancelPublishedAuto`, `auto_acknowledged`, `published_auto`, `MANUAL_PUBLISHED_AUTO_ENABLED`, `published_auto_enabled` (JSON-ключ), `window.MPQ_PUBLISHED_AUTO_ENABLED` — имена едины во всех задачах. `mpqAgg(statuses)` — сигнатура изменена с rows на statuses, все 3 вызова обновлены (Task 4 Step 4).
