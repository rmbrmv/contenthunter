# WP #127 — Планировщик: счётчик выложенного — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Планировщик деливери должен показывать корректный счётчик выложенного в карточках — доверять `publish_queue.status`, когда связка `publish_tasks.client_publish_id` пустая.

**Architecture:** Бэкенд-только фикс в `publish_planner.js`. `publish_queue.status` (`done`/`published`/`published_no_url`) — авторитетный сигнал факта публикации. В чистой функции `buildPlannerCards`, если у намерения нет привязанного успеха в `publish_tasks`, но очередь говорит «выложено», синтезируем успех (дата = последний реальный день попытки, иначе плановый день). Поведение под env-флагом `PLANNER_TRUST_QUEUE_STATUS` (дефолт on). Фронт не меняется — рендерит `done_count`/`total_accounts` как есть.

**Tech Stack:** Node.js (CommonJS), Express, PostgreSQL (`pg`), `node:test` + `node:assert`.

**Спека:** `docs/superpowers/specs/2026-05-25-wp127-planner-counter-design.md`

---

## Prerequisites / Setup

Код живёт в репо **`GenGo2/delivery-contenthunter`** (autowarm), НЕ в `contenthunter` (здесь только docs). Прод-чекаут и testbench `publish_planner.js` **идентичны** (сверено 2026-05-25). Прод — ветка `main`.

**Перед началом** реализатор создаёт изолированный worktree autowarm от `main` (через superpowers:using-git-worktrees), напр.:
```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add -b wp127-planner-counter <worktree-path> origin/main
```
⚠️ Авто-push hook: любой commit в worktree этого репо пушит ТЕКУЩУЮ ветку на origin. Feature-ветку прод НЕ деплоит (тянет только `main`), но commit = публичный push. **Без force-push.**

Тесты гоняются из корня репо: `node --test --test-force-exit tests/publish_planner.test.js`.

## File Structure

- **Create:** `tests/publish_planner.test.js` — `node --test` для `buildPlannerCards` (чистая функция) + mock-pool тест `getPlannerCards`.
- **Modify:** `publish_planner.js`
  - `buildPlannerCards` — синтез успеха из `queue_status` (Task 1).
  - `getPlannerCards` — `SELECT pq.status AS queue_status`, проброс `queue_status`/`manual_handoff_date` в намерения, проброс опции `trustQueueStatus` (Task 2).
- **Modify:** `server.js` — флаг `PLANNER_TRUST_QUEUE_STATUS` + передача в `getPlannerCards` (Task 3).

---

## Task 1: `buildPlannerCards` — синтез успеха из `queue_status` (чистая функция, TDD)

**Files:**
- Create: `tests/publish_planner.test.js`
- Modify: `publish_planner.js` (функция `buildPlannerCards`, начало файла)

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/publish_planner.test.js`:

```javascript
'use strict';

/**
 * WP #127 — planner published-counter fix.
 * buildPlannerCards: publish_queue.status авторитетен для факта публикации.
 * TDD: тесты до реализации (RED → GREEN).
 */

const { test } = require('node:test');
const assert = require('node:assert');

const { buildPlannerCards } = require('../publish_planner.js');

const WIN = { from: '2026-05-18', to: '2026-05-24' };
// намерение-хелпер
function intent(over = {}) {
  return Object.assign({
    chain_id: 'slot:1', account_intent_id: 'i', project_id: 65,
    project_name: 'Forsal', video_title: 'V',
    scheduled_date: '2026-05-22', queue_status: 'pending',
    manual_handoff_date: null, attempts: [],
  }, over);
}
const cardOn = (cards, chain, date) =>
  cards.find(c => c.chain_id === chain && c.business_date === date);

test('queue done без привязанной задачи → учтено на плановый день', () => {
  const cards = buildPlannerCards([intent({ queue_status: 'done' })], WIN);
  const c = cardOn(cards, 'slot:1', '2026-05-22');
  assert.ok(c, 'карточка на 22.05 есть');
  assert.strictEqual(c.done_count, 1);
  assert.strictEqual(c.total_accounts, 1);
  assert.strictEqual(c.state, 'published');
});

test('queue done только с failed-попытками → синтез на последний день попытки', () => {
  const cards = buildPlannerCards([intent({
    queue_status: 'done',
    attempts: [
      { date: '2026-05-22', status: 'failed', error_code: 'x', via_manual: false },
      { date: '2026-05-23', status: 'failed', error_code: 'x', via_manual: false },
    ],
  })], WIN);
  // на 22 ещё не выложено (синтез на 23), на 23 — выложено
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').done_count, 0);
  const c23 = cardOn(cards, 'slot:1', '2026-05-23');
  assert.strictEqual(c23.done_count, 1);
  assert.strictEqual(c23.state, 'final');
});

test('привязанный реальный успех приоритетнее синтеза', () => {
  const cards = buildPlannerCards([intent({
    queue_status: 'done',
    attempts: [{ date: '2026-05-24', status: 'done', error_code: null, via_manual: false }],
  })], WIN);
  // успех на 24 (из задачи), не на плановый 22
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').done_count, 0);
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-24').done_count, 1);
});

test('failed без успеха → не учтено', () => {
  const cards = buildPlannerCards([intent({ queue_status: 'failed' })], WIN);
  const c = cardOn(cards, 'slot:1', '2026-05-22');
  assert.strictEqual(c.done_count, 0);
  assert.strictEqual(c.state, 'partial');
});

test('Forsal: 10 done + 2 failed без привязок → 10/12 partial', () => {
  const intents = [];
  for (let i = 0; i < 10; i++) intents.push(intent({ account_intent_id: 'd' + i, queue_status: 'done' }));
  for (let i = 0; i < 2; i++) intents.push(intent({ account_intent_id: 'f' + i, queue_status: 'failed' }));
  const cards = buildPlannerCards(intents, WIN);
  const c = cardOn(cards, 'slot:1', '2026-05-22');
  assert.strictEqual(c.total_accounts, 12);
  assert.strictEqual(c.done_count, 10);
  assert.strictEqual(c.state, 'partial');
  assert.strictEqual(c.carried_out_count, 2);
});

test('trustQueueStatus=false отключает синтез', () => {
  const cards = buildPlannerCards([intent({ queue_status: 'done' })],
    Object.assign({ trustQueueStatus: false }, WIN));
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').done_count, 0);
});

test('регресс: полностью привязанная цепочка не меняется', () => {
  const intents = [
    intent({ account_intent_id: 'a', queue_status: 'done',
      attempts: [{ date: '2026-05-22', status: 'done', error_code: null, via_manual: false }] }),
    intent({ account_intent_id: 'b', queue_status: 'done',
      attempts: [{ date: '2026-05-22', status: 'done', error_code: null, via_manual: false }] }),
  ];
  const cards = buildPlannerCards(intents, WIN);
  const c = cardOn(cards, 'slot:1', '2026-05-22');
  assert.strictEqual(c.done_count, 2);
  assert.strictEqual(c.state, 'published');
});

test('синтез с manual_handoff_date → mode=manual', () => {
  const cards = buildPlannerCards([intent({
    queue_status: 'published', manual_handoff_date: '2026-05-22',
  })], WIN);
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').mode, 'manual');
});
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: FAIL — синтез не реализован, `queue done без привязки` даёт `done_count 0` (а тест ждёт 1). (Тесты `failed без успеха`, `trustQueueStatus=false`, `регресс` могут проходить уже — это ок.)

- [ ] **Step 3: Реализовать синтез в `buildPlannerCards`**

В `publish_planner.js` найти начало функции (`function buildPlannerCards(intents, opts) {`). Изменить распаковку opts и цикл сбора успехов.

Было:
```javascript
function buildPlannerCards(intents, opts) {
  const { from, to } = opts;
  const chains = new Map();
```
Стало:
```javascript
function buildPlannerCards(intents, opts) {
  const { from, to } = opts;
  const trustQueue = opts.trustQueueStatus !== false; // WP #127: дефолт ON
  const chains = new Map();
```

Было (внутри `for (const it of group)`):
```javascript
      const good = real
        .filter(a => SUCCESS_STATUSES.has(a.status))
        .map(a => ({ date: a.date, via_manual: !!a.via_manual }))
        .sort((a, b) => a.date.localeCompare(b.date));
      successes.push(good.length ? good[0] : null);
```
Стало:
```javascript
      const good = real
        .filter(a => SUCCESS_STATUSES.has(a.status))
        .map(a => ({ date: a.date, via_manual: !!a.via_manual }))
        .sort((a, b) => a.date.localeCompare(b.date));
      let chosen = good.length ? good[0] : null;
      // WP #127: publish_queue.status — авторитетный сигнал факта публикации.
      // Если привязанного успеха в publish_tasks нет, но очередь говорит "выложено" —
      // синтезируем успех: дата = последний реальный день попытки, иначе плановый день.
      if (!chosen && trustQueue && SUCCESS_STATUSES.has(it.queue_status)) {
        const realDates = real.map(a => a.date).filter(Boolean).sort();
        const synthDate = realDates.length ? realDates[realDates.length - 1] : it.scheduled_date;
        activitySet.add(synthDate);
        chosen = { date: synthDate, via_manual: !!it.manual_handoff_date };
      }
      successes.push(chosen);
```

Остальное тело `buildPlannerCards` без изменений.

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: PASS (все тесты Task 1).

- [ ] **Step 5: Commit**

```bash
git add tests/publish_planner.test.js publish_planner.js
git commit -m "fix(planner): trust publish_queue.status for done-count (WP #127)

buildPlannerCards синтезирует успех из queue_status, когда привязка
publish_tasks.client_publish_id пустая. Под флагом trustQueueStatus (ON).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `getPlannerCards` — проброс `queue_status` + опции (mock-pool тест)

**Files:**
- Modify: `tests/publish_planner.test.js` (добавить mock-pool тест)
- Modify: `publish_planner.js` (функция `getPlannerCards`, full-путь)

- [ ] **Step 1: Написать падающий mock-pool тест**

Добавить в КОНЕЦ `tests/publish_planner.test.js`:

```javascript
const { getPlannerCards } = require('../publish_planner.js');

// mock pool: диспетчеризация по подстроке SQL
function makeMockPool(handlers) {
  return {
    query: async (sql) => {
      for (const h of handlers) if (h.match.test(sql)) return { rows: h.rows };
      return { rows: [] };
    },
  };
}

test('getPlannerCards: queue done без привязки → done_count из статуса очереди', async () => {
  const pool = makeMockPool([
    // hasColumn() вызывается отдельно для client_publish_id и manual_handoff_at;
    // обе проверки матчат этот handler и видят rows.length>0 → выбирается full-путь.
    { match: /information_schema\.columns/, rows: [{ ok: 1 }] },
    { match: /client_publish_id::text AS intent_id/, rows: [
      { queue_id: 1, intent_id: 'i1', account_username: 'a1', platform: 'youtube',
        project_id: 65, project_name: 'Forsal', video_title: 'V', chain_id: 'slot:1',
        scheduled_date: '2026-05-22', manual_handoff_date: null, queue_status: 'done' },
      { queue_id: 2, intent_id: 'i2', account_username: 'a2', platform: 'tiktok',
        project_id: 65, project_name: 'Forsal', video_title: 'V', chain_id: 'slot:1',
        scheduled_date: '2026-05-22', manual_handoff_date: null, queue_status: 'failed' },
    ] },
    { match: /FROM\s+publish_tasks/, rows: [] },              // привязок нет
    { match: /validator_manual_publish_queue/, rows: [] },
    { match: /validator_schedule_slots/, rows: [] },
  ]);
  const cards = await getPlannerCards(pool, { from: '2026-05-18', to: '2026-05-24' });
  const c = cards.find(x => x.chain_id === 'slot:1' && x.business_date === '2026-05-22');
  assert.ok(c, 'карточка slot:1 на 22.05 есть');
  assert.strictEqual(c.total_accounts, 2);
  assert.strictEqual(c.done_count, 1);
  assert.strictEqual(c.state, 'partial');
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: FAIL — `getPlannerCards` не селектит `pq.status`, не пробрасывает `queue_status` в намерения → `done_count` будет 0 (тест ждёт 1).

- [ ] **Step 3: Реализовать проброс в `getPlannerCards`**

В `publish_planner.js`, функция `getPlannerCards`.

(a) Сигнатура. Было:
```javascript
async function getPlannerCards(pool, { from, to, projectId = null }) {
```
Стало:
```javascript
async function getPlannerCards(pool, { from, to, projectId = null, trustQueueStatus = true }) {
```

(b) SQL `qrows` (full-путь). Было:
```javascript
      SELECT pq.id AS queue_id, pq.client_publish_id::text AS intent_id,
             pq.account_username, pq.platform,
             pq.project_id, COALESCE(vp.project, vp2.project) AS project_name,
```
Стало (добавлена `pq.status AS queue_status`):
```javascript
      SELECT pq.id AS queue_id, pq.client_publish_id::text AS intent_id,
             pq.account_username, pq.platform, pq.status AS queue_status,
             pq.project_id, COALESCE(vp.project, vp2.project) AS project_name,
```

(c) Маппинг намерений. Было:
```javascript
      return {
        chain_id: r.chain_id, account_intent_id: r.intent_id,
        project_id: r.project_id, project_name: r.project_name, video_title: r.video_title,
        scheduled_date: r.scheduled_date, attempts,
      };
```
Стало:
```javascript
      return {
        chain_id: r.chain_id, account_intent_id: r.intent_id,
        project_id: r.project_id, project_name: r.project_name, video_title: r.video_title,
        scheduled_date: r.scheduled_date, attempts,
        queue_status: r.queue_status, manual_handoff_date: r.manual_handoff_date, // WP #127
      };
```

(d) Вызов `buildPlannerCards`. Было:
```javascript
    cards.push(...buildPlannerCards(intents, { from, to }));
```
Стало:
```javascript
    cards.push(...buildPlannerCards(intents, { from, to, trustQueueStatus }));
```

- [ ] **Step 4: Запустить все тесты — убедиться, что проходят**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: PASS (все тесты Task 1 + Task 2).

- [ ] **Step 5: Commit**

```bash
git add tests/publish_planner.test.js publish_planner.js
git commit -m "fix(planner): plumb queue_status + trustQueueStatus into getPlannerCards (WP #127)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `server.js` — флаг `PLANNER_TRUST_QUEUE_STATUS` + передача в роут

**Files:**
- Modify: `server.js` (объявление флага ~строка 16; вызов `getPlannerCards` ~строка 5786)

- [ ] **Step 1: Добавить env-флаг рядом с `PLANNER_ENABLED`**

Найти (≈строка 16):
```javascript
const PLANNER_ENABLED = process.env.PLANNER_ENABLED !== 'false';
```
Добавить сразу следующей строкой:
```javascript
const PLANNER_TRUST_QUEUE_STATUS = process.env.PLANNER_TRUST_QUEUE_STATUS !== 'false'; // WP #127, дефолт ON
```

- [ ] **Step 2: Передать флаг в `getPlannerCards`**

Найти в роуте `app.get('/api/publish/planner', ...)` (≈строка 5786):
```javascript
    const cards = await planner.getPlannerCards(pool, { from, to, projectId });
```
Заменить на:
```javascript
    const cards = await planner.getPlannerCards(pool, { from, to, projectId, trustQueueStatus: PLANNER_TRUST_QUEUE_STATUS });
```

- [ ] **Step 3: Проверить, что сервер парсится без ошибок**

Run: `node --check server.js`
Expected: без вывода (синтаксис ок).

- [ ] **Step 4: Прогнать весь тест-сьют планировщика (регресс)**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.js
git commit -m "feat(planner): PLANNER_TRUST_QUEUE_STATUS kill-switch (WP #127)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Live-DB smoke на Forsal 22.05 (read-only верификация)

**Files:** нет (разовая проверка, не коммитим)

- [ ] **Step 1: Прогнать `getPlannerCards` на реальном окне Forsal**

Из корня worktree autowarm:
```bash
node -e "
const { Pool } = require('pg');
const planner = require('./publish_planner');
const pool = new Pool({ host:'localhost', port:5432, user:'openclaw', password:'openclaw123', database:'openclaw' });
(async () => {
  const cards = await planner.getPlannerCards(pool, { from:'2026-05-18', to:'2026-05-24', projectId:65 });
  const c = cards.find(x => x.business_date === '2026-05-22' && x.total_accounts);
  console.log(JSON.stringify(c, null, 2));
  await pool.end();
})();
"
```
Expected: карточка на `2026-05-22` с `total_accounts:12`, `done_count:10` (а не 0), `state:"partial"`, `carried_out_count:2`.

- [ ] **Step 2: Зафиксировать результат**

Сверить с ожидаемым (10/12). Если совпало — фикс работает на живых данных. Результат приложить в комментарий WP #127 при сдаче.

---

## Self-Review (выполнено при написании плана)

- **Покрытие спеки:** §4 (правило синтеза) → Task 1; §5.1–5.3 (SQL/маппинг/проброс) → Task 2; §7 (kill-switch) → Task 3; §8 (тесты + live smoke) → Task 1/2 + Task 4. §6 (что НЕ меняется) — фронт/схема/переносы не трогаются ни в одном таске. ✅
- **Плейсхолдеров нет:** весь код приведён полностью.
- **Согласованность типов:** поля намерения (`queue_status`, `manual_handoff_date`, `scheduled_date`, `attempts`) совпадают между Task 1 (тесты + синтез) и Task 2 (маппинг в `getPlannerCards`). Опция `trustQueueStatus` — единое имя в `getPlannerCards`, `buildPlannerCards`, `server.js`. ✅

## Деплой (после приёмки, отдельно)

Бэкенд-только: PR в `GenGo2/delivery-contenthunter` (`publish_planner.js`, `server.js`, `tests/publish_planner.test.js`) → merge в `main` → прод `git pull --ff-only origin main` → `sudo -n pm2 restart autowarm`. Прод-деплой — с одобрения Данила; без force-push; учитывать auto-push hook. Откат без редеплоя: `PLANNER_TRUST_QUEUE_STATUS=false`.
