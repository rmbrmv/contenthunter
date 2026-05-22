# WP #109 — Планировщик в деливери — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать менеджеру календарь-планировщик выкладок (недельная сетка с переносами, состояниями и hover-подсветкой) + две колонки («перенесено», «попытка») в таблице очереди — read-only визуализация поверх данных движка ретраев #108.

**Architecture:** Read-only фича. Бэкенд — новый модуль `publish_planner.js`: вся доменная логика в **чистых функциях** (`buildPlannerCards`, `deriveTransferColumns`), переносы/попытки **выводятся из таймлайна** `publish_tasks` по МСК-дням (Подход 1, без новых полей сверх #108). Контракт к #108 тонкий: `client_publish_id`, леджер `publish_tasks` (даты/статусы попыток), `manual_handoff_at`. До прода #108 — мягкая деградация (карточки без цепочек, колонки `—`) за фича-флагами. Фронт — третий под-таб `up:planner` в секции publishing (ванильный JS, CSS-grid).

**Tech Stack:** Node.js + Express (autowarm `server.js`), PostgreSQL (`pg` Pool, БД `openclaw`), ванильный JS + Tailwind в `public/index.html`, тесты `node --test` (live-DB фикстуры + чистые юнит-тесты без БД).

**Spec:** `docs/superpowers/specs/2026-05-21-wp109-delivery-planner-design.md`

**⚠️ Прод-чекаут `/root/.openclaw/workspace-genri/autowarm/` имеет auto-push hook** (любой коммит улетает в `GenGo2/delivery-contenthunter`). Реализация/тесты — на изолированном клоне/ветке; деплой в прод-чекаут — отдельным шагом с одобрения Данила, **без force-push**.

---

## File Structure

| Файл | Ответственность | Действие |
|---|---|---|
| `publish_planner.js` | Read-model: чистая логика карточек/переносов + SQL-сборка | **Create** |
| `test_publish_planner.test.js` | Юнит-тесты чистых функций (без БД) | **Create** |
| `server.js` | Роут `GET /api/publish/planner`; навеска колонок в `/api/publish/queue` | **Modify** (`~2015`, `~5750`) |
| `public/index.html` | Под-таб `up:planner`, недельная сетка, 2 колонки очереди | **Modify** (`~267`, `~2398`, `~10809`, `~11098`) |

**Фазы (для независимой проверки):**
- **Фаза A (Задачи 1–4):** бэкенд-модуль + эндпоинт планировщика. Тестируемо изолированно.
- **Фаза B (Задачи 5–6):** две колонки очереди (бэкенд-навеска + фронт). Независимо от планировщика.
- **Фаза C (Задачи 7–10):** фронт планировщика (потребляет эндпоинт Фазы A).
- **Фаза D (Задача 11):** интеграция, деплой, live-smoke, OpenProject.

---

## Task 1: Чистое ядро — `buildPlannerCards`

Главная доменная логика: разложить аккаунт-намерения в карточки по дням с состояниями и переносами. Чистая функция → настоящий red-green без БД.

**Files:**
- Create: `publish_planner.js`
- Test: `test_publish_planner.test.js`

- [ ] **Step 1: Написать падающий тест** (`test_publish_planner.test.js`)

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { buildPlannerCards } = require('./publish_planner');

const WIN = { from: '2026-05-18', to: '2026-05-24' };

// Хелпер: намерение одного аккаунта с готовым успехом в день `successDate` (или null)
function intent(chain, accId, scheduled, attempts) {
  return {
    chain_id: chain, account_intent_id: accId,
    project_id: 12, project_name: 'Relisme',
    video_title: 'Одна вещь — два формата. Удобно?',
    scheduled_date: scheduled, attempts,
  };
}

test('сценарий Relisme: 5 авто 20.05, 3 авто 21.05, 2 вручную 22.05 → partial/echo/final', () => {
  const intents = [];
  for (let i = 0; i < 5; i++) intents.push(intent('slot:1', `a${i}`, '2026-05-20',
    [{ date: '2026-05-20', status: 'done', error_code: null, via_manual: false }]));
  for (let i = 5; i < 8; i++) intents.push(intent('slot:1', `a${i}`, '2026-05-20',
    [{ date: '2026-05-20', status: 'failed', error_code: 'adb_push_timeout', via_manual: false },
     { date: '2026-05-21', status: 'done', error_code: null, via_manual: false }]));
  for (let i = 8; i < 10; i++) intents.push(intent('slot:1', `a${i}`, '2026-05-20',
    [{ date: '2026-05-22', status: 'published', error_code: null, via_manual: true }]));

  const cards = buildPlannerCards(intents, WIN).sort((a, b) => a.business_date.localeCompare(b.business_date));
  assert.equal(cards.length, 3);

  assert.deepEqual({ d: cards[0].business_date, st: cards[0].state, done: cards[0].done_count, out: cards[0].carried_out_count, to: cards[0].carried_out_to, mode: cards[0].mode },
    { d: '2026-05-20', st: 'partial', done: 5, out: 5, to: '2026-05-21', mode: 'auto' });
  assert.deepEqual({ d: cards[1].business_date, st: cards[1].state, done: cards[1].done_count, inf: cards[1].carried_in_from, out: cards[1].carried_out_count, to: cards[1].carried_out_to, mode: cards[1].mode },
    { d: '2026-05-21', st: 'echo', done: 8, inf: '2026-05-20', out: 2, to: '2026-05-22', mode: 'auto' });
  assert.deepEqual({ d: cards[2].business_date, st: cards[2].state, done: cards[2].done_count, closed: cards[2].closed_transfer_from, mode: cards[2].mode },
    { d: '2026-05-22', st: 'final', done: 10, closed: '2026-05-20', mode: 'manual' });
});

test('все выложены в день D0 → одна карточка published, без переноса', () => {
  const intents = [];
  for (let i = 0; i < 4; i++) intents.push(intent('slot:2', `b${i}`, '2026-05-19',
    [{ date: '2026-05-19', status: 'done', error_code: null, via_manual: false }]));
  const cards = buildPlannerCards(intents, WIN);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].state, 'published');
  assert.equal(cards[0].done_count, 4);
  assert.equal(cards[0].carried_out_count, 0);
  assert.equal(cards[0].carried_out_to, null);
});

test('process_interrupted не учитывается; published_no_url = успех', () => {
  const intents = [
    intent('slot:3', 'c0', '2026-05-20',
      [{ date: '2026-05-20', status: 'failed', error_code: 'process_interrupted', via_manual: false },
       { date: '2026-05-20', status: 'published_no_url', error_code: null, via_manual: false }]),
  ];
  const cards = buildPlannerCards(intents, WIN);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].state, 'published');
  assert.equal(cards[0].done_count, 1);
});

test('остаток без следующего дня активности → partial с carried_out_to=null', () => {
  const intents = [];
  for (let i = 0; i < 6; i++) intents.push(intent('slot:4', `d${i}`, '2026-05-20',
    [{ date: '2026-05-20', status: 'done', error_code: null, via_manual: false }]));
  for (let i = 6; i < 10; i++) intents.push(intent('slot:4', `d${i}`, '2026-05-20',
    [{ date: '2026-05-20', status: 'failed', error_code: 'caption_fill_failed', via_manual: false }]));
  const cards = buildPlannerCards(intents, WIN);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].state, 'partial');
  assert.equal(cards[0].done_count, 6);
  assert.equal(cards[0].carried_out_count, 4);
  assert.equal(cards[0].carried_out_to, null);
});

test('ретрай на след. день, но всё ещё неуспех → echo-карточка на дне переноса', () => {
  const intents = [];
  for (let i = 0; i < 6; i++) intents.push(intent('slot:5', `e${i}`, '2026-05-20',
    [{ date: '2026-05-20', status: 'done', error_code: null, via_manual: false }]));
  for (let i = 6; i < 10; i++) intents.push(intent('slot:5', `e${i}`, '2026-05-20',
    [{ date: '2026-05-20', status: 'failed', error_code: 'adb_push_timeout', via_manual: false },
     { date: '2026-05-21', status: 'failed', error_code: 'adb_push_timeout', via_manual: false }]));
  const cards = buildPlannerCards(intents, WIN).sort((a, b) => a.business_date.localeCompare(b.business_date));
  assert.equal(cards.length, 2);
  assert.deepEqual({ d: cards[0].business_date, st: cards[0].state, done: cards[0].done_count, out: cards[0].carried_out_count, to: cards[0].carried_out_to },
    { d: '2026-05-20', st: 'partial', done: 6, out: 4, to: '2026-05-21' });
  assert.deepEqual({ d: cards[1].business_date, st: cards[1].state, done: cards[1].done_count, inf: cards[1].carried_in_from, out: cards[1].carried_out_count, to: cards[1].carried_out_to },
    { d: '2026-05-21', st: 'echo', done: 6, inf: '2026-05-20', out: 4, to: null });
});

test('две цепочки группируются раздельно по chain_id', () => {
  const intents = [
    intent('slot:A', 'x', '2026-05-20', [{ date: '2026-05-20', status: 'done', error_code: null, via_manual: false }]),
    intent('slot:B', 'y', '2026-05-20', [{ date: '2026-05-20', status: 'done', error_code: null, via_manual: false }]),
  ];
  const cards = buildPlannerCards(intents, WIN);
  assert.equal(cards.length, 2);
  assert.deepEqual([...new Set(cards.map(c => c.chain_id))].sort(), ['slot:A', 'slot:B']);
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test test_publish_planner.test.js`
Expected: FAIL — `Cannot find module './publish_planner'` (модуль ещё не создан).

- [ ] **Step 3: Реализовать `buildPlannerCards`** (`publish_planner.js`)

```js
'use strict';

const SUCCESS_STATUSES = new Set(['done', 'published', 'published_no_url']);

/**
 * Чистая функция: разложить аккаунт-намерения цепочек в карточки по дням.
 * @param {Array} intents  — по одному на аккаунт:
 *   { chain_id, account_intent_id, project_id, project_name, video_title,
 *     scheduled_date:'YYYY-MM-DD'(МСК),
 *     attempts:[{ date:'YYYY-MM-DD'(МСК), status, error_code, via_manual:bool }] }
 * @param {Object} opts — { from:'YYYY-MM-DD', to:'YYYY-MM-DD' } — окно отсечения карточек
 * @returns {Array} карточки (см. spec §5)
 */
function buildPlannerCards(intents, opts) {
  const { from, to } = opts;
  const chains = new Map();
  for (const it of intents) {
    if (!chains.has(it.chain_id)) chains.set(it.chain_id, []);
    chains.get(it.chain_id).push(it);
  }

  const cards = [];
  for (const [chainId, group] of chains) {
    const N = group.length;
    const meta = group[0]; // project/title общие в цепочке
    const D0 = group.map(g => g.scheduled_date).sort()[0];

    // первый успешный день каждого намерения + ВСЕ реальные дни попыток
    // (вкл. неуспешные ретраи — именно они и есть «перенос на следующий день»; process_interrupted игнорим)
    const successes = [];
    const activitySet = new Set([D0]);
    for (const it of group) {
      const real = (it.attempts || []).filter(a => a.error_code !== 'process_interrupted');
      for (const a of real) activitySet.add(a.date);
      const good = real
        .filter(a => SUCCESS_STATUSES.has(a.status))
        .map(a => ({ date: a.date, via_manual: !!a.via_manual }))
        .sort((a, b) => a.date.localeCompare(b.date));
      successes.push(good.length ? good[0] : null);
    }
    const activityDays = [...activitySet].sort();

    for (let i = 0; i < activityDays.length; i++) {
      const Dk = activityDays[i];
      const isSource = Dk === D0;
      const succeededToday = successes.some(s => s && s.date === Dk);
      const cumBefore = successes.filter(s => s && s.date < Dk).length;
      // не-исходный день рисуем только если он что-то двигает (успех сегодня) или перенос ещё открыт
      if (!isSource && !succeededToday && cumBefore >= N) continue;

      const cumulativeDone = successes.filter(s => s && s.date <= Dk).length;
      const remainder = N - cumulativeDone;
      const nextDay = activityDays[i + 1] || null;

      const state = isSource
        ? (cumulativeDone === N ? 'published' : 'partial')
        : (cumulativeDone === N ? 'final' : 'echo');
      const todayManual = successes.some(s => s && s.date === Dk && s.via_manual);

      if (Dk < from || Dk > to) continue; // вне видимой недели — пометки сохранятся у соседей

      cards.push({
        chain_id: chainId,
        business_date: Dk,
        project_id: meta.project_id,
        project_name: meta.project_name,
        video_title: meta.video_title,
        total_accounts: N,
        done_count: cumulativeDone,
        state,
        mode: todayManual ? 'manual' : 'auto',
        carried_in_from: (state === 'echo' || state === 'final') ? D0 : null,
        carried_out_count: remainder > 0 ? remainder : 0,
        carried_out_to: remainder > 0 ? nextDay : null,
        closed_transfer_from: state === 'final' ? D0 : null,
      });
    }
  }
  return cards;
}

module.exports = { buildPlannerCards, SUCCESS_STATUSES };
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test test_publish_planner.test.js`
Expected: PASS (6 тестов).

- [ ] **Step 5: Commit**

```bash
git add publish_planner.js test_publish_planner.test.js
git commit -m "feat(planner): чистое ядро buildPlannerCards — раскладка переносов по дням"
```

---

## Task 2: Чистый хелпер — `deriveTransferColumns` (колонки очереди)

`attempt_count` + `transferred_to` для двух новых колонок очереди. Чистая функция → red-green без БД.

**Files:**
- Modify: `publish_planner.js`
- Test: `test_publish_planner.test.js`

- [ ] **Step 1: Дописать падающий тест** (в конец `test_publish_planner.test.js`)

```js
const { deriveTransferColumns } = require('./publish_planner');

test('deriveTransferColumns: нет переноса — transferred_to=null', () => {
  const r = deriveTransferColumns({
    attempts: [{ date: '2026-05-20', error_code: 'adb_push_timeout' }, { date: '2026-05-20', error_code: null }],
    scheduledDate: '2026-05-20', manualHandoffDate: null });
  assert.equal(r.attempt_count, 2);
  assert.equal(r.transferred_to, null);
});

test('deriveTransferColumns: попытка позже даты слота → перенос на эту дату', () => {
  const r = deriveTransferColumns({
    attempts: [{ date: '2026-05-20', error_code: 'adb_push_timeout' }, { date: '2026-05-21', error_code: null }],
    scheduledDate: '2026-05-20', manualHandoffDate: null });
  assert.equal(r.attempt_count, 2);
  assert.equal(r.transferred_to, '2026-05-21');
});

test('deriveTransferColumns: ручная передача → дата handoff приоритетна', () => {
  const r = deriveTransferColumns({
    attempts: [{ date: '2026-05-20', error_code: null }],
    scheduledDate: '2026-05-20', manualHandoffDate: '2026-05-22' });
  assert.equal(r.transferred_to, '2026-05-22');
});

test('deriveTransferColumns: process_interrupted не считается попыткой', () => {
  const r = deriveTransferColumns({
    attempts: [{ date: '2026-05-20', error_code: 'process_interrupted' }, { date: '2026-05-20', error_code: null }],
    scheduledDate: '2026-05-20', manualHandoffDate: null });
  assert.equal(r.attempt_count, 1);
});

test('deriveTransferColumns: нет попыток (легаси) → 0 / null', () => {
  const r = deriveTransferColumns({ attempts: [], scheduledDate: '2026-05-20', manualHandoffDate: null });
  assert.equal(r.attempt_count, 0);
  assert.equal(r.transferred_to, null);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test test_publish_planner.test.js`
Expected: FAIL — `deriveTransferColumns is not a function`.

- [ ] **Step 3: Реализовать** (в `publish_planner.js`, добавить функцию и в `module.exports`)

```js
/**
 * Чистая функция: «попытка» (счётчик) + «перенесено» (дата) для строки очереди.
 * @param {Object} a — { attempts:[{date:'YYYY-MM-DD'(МСК), error_code}],
 *                        scheduledDate:'YYYY-MM-DD'(МСК),
 *                        manualHandoffDate:'YYYY-MM-DD'(МСК)|null }
 * @returns {{attempt_count:number, transferred_to:string|null}}
 */
function deriveTransferColumns({ attempts, scheduledDate, manualHandoffDate }) {
  const real = (attempts || []).filter(a => a.error_code !== 'process_interrupted');
  const attempt_count = real.length;
  let transferred_to = null;
  if (manualHandoffDate) {
    transferred_to = manualHandoffDate;
  } else {
    const dates = real.map(a => a.date).filter(Boolean).sort();
    const last = dates.length ? dates[dates.length - 1] : null;
    if (last && last > scheduledDate) transferred_to = last;
  }
  return { attempt_count, transferred_to };
}

module.exports = { buildPlannerCards, deriveTransferColumns, SUCCESS_STATUSES };
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test test_publish_planner.test.js`
Expected: PASS (11 тестов).

- [ ] **Step 5: Commit**

```bash
git add publish_planner.js test_publish_planner.test.js
git commit -m "feat(planner): deriveTransferColumns — попытка/перенесено для очереди"
```

---

## Task 3: SQL-сборка `getPlannerCards(pool, opts)`

Сборка входа для `buildPlannerCards` из БД + плановые карточки из расписания. **Зависит от колонок #108** (`client_publish_id`, `manual_handoff_at`) — пишем с runtime-проверкой существования и деградацией.

**Files:**
- Modify: `publish_planner.js`

> ⚠️ **Grounding ПЕРЕД написанием SQL** (выполнить и сверить):
> ```bash
> cd /root/.openclaw/workspace-genri/autowarm
> # 1) есть ли колонки #108?
> psql "postgres://openclaw:openclaw123@localhost/openclaw" -c "\d publish_queue" | grep -E 'client_publish_id|manual_handoff_at'
> psql "postgres://openclaw:openclaw123@localhost/openclaw" -c "\d publish_tasks" | grep -E 'client_publish_id|created_at|status|error_code'
> # 2) статусы модерации контента (для approved/pending карточек)
> psql "postgres://openclaw:openclaw123@localhost/openclaw" -c "SELECT DISTINCT status FROM validator_content LIMIT 30;"
> # 3) связь ручной выкладки ↔ слот/аккаунт (для дня ручного успеха)
> psql "postgres://openclaw:openclaw123@localhost/openclaw" -c "\d validator_manual_publish_queue" | grep -E 'slot_id|unic_result_id|account_username|platform|published_at'
> ```
> **Сверено 2026-05-21 (live DB openclaw):** колонки #108 УЖЕ на месте (`publish_queue.client_publish_id` + `manual_handoff_at`; `publish_tasks.client_publish_id/created_at/status/error_code`) → активен **full-режим**. Статусы `validator_content`: `approved`, `in_uniqualization`, `needs_review`, `rejected` (нет 'published'/'pending'). Плановые карточки строим только из `approved`/`needs_review`; `rejected`/`in_uniqualization` исключаем. Связочные колонки `validator_manual_publish_queue` (slot_id, account_username, platform, published_at, project_id) на месте. Деградационная ветка остаётся как защита для сред без #108.

- [ ] **Step 1: Хелпер проверки колонки + МСК-дата**

```js
// publish_planner.js — добавить

async function hasColumn(pool, table, column) {
  const { rows } = await pool.query(
    `SELECT 1 FROM information_schema.columns WHERE table_name=$1 AND column_name=$2`,
    [table, column]);
  return rows.length > 0;
}

// Карта статуса контента → состояние плановой карточки.
// approved → 'approved' (зелёная); needs_review → 'pending' (жёлтая «Требует одобрения»).
// Запрос плановых карточек берёт только эти два статуса (см. ниже), rejected/in_uniqualization исключены.
function mapContentState(status) {
  return status === 'approved' ? 'approved' : 'pending';
}
```

- [ ] **Step 2: `getPlannerCards` — выкладка (full/degraded) + план**

```js
// publish_planner.js — добавить; в module.exports добавить getPlannerCards

const MSK = `AT TIME ZONE 'Europe/Moscow'`; // = UTC+3 fixed (см. server.js MSK_OFFSET_MS)

/**
 * @param {Pool} pool
 * @param {Object} opts — { from:'YYYY-MM-DD', to:'YYYY-MM-DD', projectId:number|null }
 * @returns {Promise<Array>} карточки (выкладка + план)
 */
async function getPlannerCards(pool, { from, to, projectId = null }) {
  // full-режим только если ОБЕ колонки #108 на месте (full-запрос селектит и manual_handoff_at;
  // на частично-мигрированной БД иначе будет 500 вместо мягкой деградации)
  const full = (await hasColumn(pool, 'publish_queue', 'client_publish_id'))
            && (await hasColumn(pool, 'publish_queue', 'manual_handoff_at'));

  // окно расширяем назад на 3 дня, чтобы поймать цепочки, стартовавшие до from и заехавшие в окно
  const cards = [];

  if (full) {
    // 1) намерения выкладки (publish_queue) в расширенном окне
    const { rows: qrows } = await pool.query(`
      SELECT pq.id AS queue_id, pq.client_publish_id::text AS intent_id,
             pq.account_username, pq.platform,
             pq.project_id, COALESCE(vp.project, vp2.project) AS project_name,
             COALESCE(ut.input_video_name, pq.title, pq.caption) AS video_title,
             COALESCE('slot:'||(ut.meta->>'slot_id'), 'task:'||pq.unic_task_id::text,
                      'proj:'||pq.project_id::text||':'||(pq.scheduled_at ${MSK})::date::text) AS chain_id,
             (pq.scheduled_at ${MSK})::date::text AS scheduled_date,
             (pq.manual_handoff_at ${MSK})::date::text AS manual_handoff_date
      FROM publish_queue pq
      LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, NULL)
      LEFT JOIN validator_projects vp  ON vp.id  = pq.project_id
      LEFT JOIN validator_projects vp2 ON vp2.id = ut.project_id
      WHERE (pq.scheduled_at ${MSK})::date BETWEEN ($1::date - INTERVAL '3 days') AND $2::date
        AND ($3::int IS NULL OR pq.project_id = $3)
        AND pq.client_publish_id IS NOT NULL
    `, [from, to, projectId]);

    const intentIds = qrows.map(r => r.intent_id);
    // 2) авто-попытки (publish_tasks) по этим намерениям
    const attemptsByIntent = new Map();
    if (intentIds.length) {
      const { rows: arows } = await pool.query(`
        SELECT client_publish_id::text AS intent_id,
               (created_at ${MSK})::date::text AS date, status, error_code
        FROM publish_tasks
        WHERE client_publish_id = ANY($1::uuid[])
      `, [intentIds]);
      for (const a of arows) {
        if (!attemptsByIntent.has(a.intent_id)) attemptsByIntent.set(a.intent_id, []);
        attemptsByIntent.get(a.intent_id).push({ date: a.date, status: a.status, error_code: a.error_code, via_manual: false });
      }
    }
    // 3) ручные успехи (validator_manual_publish_queue) — матчим ПО АККАУНТУ (не по цепочке!),
    //    иначе частичная ручная выкладка ложно закроет все оставшиеся аккаунты цепочки.
    const acctKey = (chain, user, plat) => `${chain}|${(user || '').replace(/^@+/, '')}|${(plat || '').toLowerCase()}`;
    const { rows: mrows } = await pool.query(`
      SELECT 'slot:'||q.slot_id::text AS chain_id, q.account_username, q.platform,
             (q.published_at ${MSK})::date::text AS date
      FROM validator_manual_publish_queue q
      WHERE q.published_at IS NOT NULL
        AND (q.published_at ${MSK})::date BETWEEN ($1::date - INTERVAL '3 days') AND $2::date
        AND ($3::int IS NULL OR q.project_id = $3)
    `, [from, to, projectId]);
    const manualByAcct = new Map(); // chain|username|platform → ранняя дата ручного успеха
    for (const m of mrows) {
      const k = acctKey(m.chain_id, m.account_username, m.platform);
      if (!manualByAcct.has(k) || m.date < manualByAcct.get(k)) manualByAcct.set(k, m.date);
    }

    // 4) собрать intents для buildPlannerCards
    const intents = qrows.map(r => {
      const attempts = attemptsByIntent.get(r.intent_id) || [];
      const hasAutoSuccess = attempts.some(a => SUCCESS_STATUSES.has(a.status) && a.error_code !== 'process_interrupted');
      const mk = acctKey(r.chain_id, r.account_username, r.platform);
      if (!hasAutoSuccess && manualByAcct.has(mk)) {
        // ручной успех ИМЕННО этого аккаунта → синтетический via_manual
        attempts.push({ date: manualByAcct.get(mk), status: 'published', error_code: null, via_manual: true });
      }
      return {
        chain_id: r.chain_id, account_intent_id: r.intent_id,
        project_id: r.project_id, project_name: r.project_name, video_title: r.video_title,
        scheduled_date: r.scheduled_date, attempts,
      };
    });
    cards.push(...buildPlannerCards(intents, { from, to }));
  } else {
    // ДЕГРАДАЦИЯ (нет колонок #108): группируем по (project, unic_task, день) без переносов
    const { rows } = await pool.query(`
      SELECT COALESCE('task:'||pq.unic_task_id::text, 'proj:'||pq.project_id::text) AS chain_id,
             pq.project_id, COALESCE(vp.project, vp2.project) AS project_name,
             COALESCE(ut.input_video_name, pq.title, pq.caption) AS video_title,
             (pq.scheduled_at ${MSK})::date::text AS business_date,
             COUNT(*) AS total_accounts,
             COUNT(*) FILTER (WHERE pq.status IN ('done','published')) AS done_count
      FROM publish_queue pq
      LEFT JOIN unic_tasks ut ON ut.id = pq.unic_task_id
      LEFT JOIN validator_projects vp  ON vp.id  = pq.project_id
      LEFT JOIN validator_projects vp2 ON vp2.id = ut.project_id
      WHERE (pq.scheduled_at ${MSK})::date BETWEEN $1::date AND $2::date
        AND ($3::int IS NULL OR pq.project_id = $3)
      GROUP BY 1,2,3,4,5
    `, [from, to, projectId]);
    for (const r of rows) {
      const N = Number(r.total_accounts), done = Number(r.done_count);
      cards.push({
        chain_id: r.chain_id, business_date: r.business_date,
        project_id: r.project_id, project_name: r.project_name, video_title: r.video_title,
        total_accounts: N, done_count: done,
        state: done === N ? 'published' : 'partial', mode: 'auto',
        carried_in_from: null, carried_out_count: 0, carried_out_to: null, closed_transfer_from: null,
      });
    }
  }

  // 5) плановые карточки (approved/pending) из расписания — дни без строк выкладки
  const { rows: prows } = await pool.query(`
    SELECT s.project_id, vp.project AS project_name,
           COALESCE(vc.title, vc.description, '—') AS video_title,
           to_char(s.slot_date, 'YYYY-MM-DD') AS business_date,
           vc.status AS content_status,
           'slot:'||s.id::text AS chain_id
    FROM validator_schedule_slots s
    LEFT JOIN validator_content vc   ON vc.id = s.content_id
    LEFT JOIN validator_projects vp  ON vp.id = s.project_id
    WHERE s.slot_date BETWEEN $1::date AND $2::date
      AND ($3::int IS NULL OR s.project_id = $3)
      AND vc.status IN ('approved','needs_review')
      AND NOT EXISTS (
        SELECT 1 FROM publish_queue pq
        WHERE pq.project_id = s.project_id
          AND (pq.scheduled_at ${MSK})::date = s.slot_date
          AND COALESCE(pq.unic_task_id, -1) IN (
            SELECT id FROM unic_tasks ut WHERE (ut.meta->>'slot_id') = s.id::text))
  `, [from, to, projectId]);
  for (const r of prows) {
    cards.push({
      chain_id: r.chain_id, business_date: r.business_date,
      project_id: r.project_id, project_name: r.project_name, video_title: r.video_title,
      total_accounts: null, done_count: null,
      state: mapContentState(r.content_status), mode: 'auto',
      carried_in_from: null, carried_out_count: 0, carried_out_to: null, closed_transfer_from: null,
    });
  }

  return cards;
}

module.exports = { buildPlannerCards, deriveTransferColumns, getPlannerCards, SUCCESS_STATUSES };
```

- [ ] **Step 2: Синтаксис-проверка модуля**

Run: `node -e "require('./publish_planner'); console.log('ok')"`
Expected: `ok`

- [ ] **Step 3: Юнит-тесты всё ещё зелёные** (чистые функции не задеты)

Run: `node --test test_publish_planner.test.js`
Expected: PASS (11 тестов).

> Интеграция SQL проверяется live-smoke в Задаче 11 (зависит от данных #108). Здесь убеждаемся, что модуль грузится и чистая логика цела.

- [ ] **Step 4: Commit**

```bash
git add publish_planner.js
git commit -m "feat(planner): getPlannerCards — SQL-сборка (full/degraded) + плановые карточки"
```

---

## Task 4: Роут `GET /api/publish/planner` + флаг `PLANNER_ENABLED`

**Files:**
- Modify: `server.js` (рядом с роутами WP#107, `~5750`)

- [ ] **Step 1: Подключить модуль** (вверху `server.js`, рядом с `const mpq = require('./manual_publish_queue');` на строке 14)

```js
const planner = require('./publish_planner');
const PLANNER_ENABLED = process.env.PLANNER_ENABLED !== 'false';
```

- [ ] **Step 2: Добавить роут** (после блока `// ============ WP#107 ... ============`, перед `// ====== TRIGGER-IMMEDIATE`, ~5751)

```js
// ============ WP#109 ПЛАНИРОВЩИК ============
app.get('/api/publish/planner', requireAuth, async (req, res) => {
  if (!PLANNER_ENABLED) return res.json({ cards: [] });
  try {
    const from = String(req.query.from || '').slice(0, 10);
    const to   = String(req.query.to   || '').slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) {
      return res.status(400).json({ error: 'from/to required as YYYY-MM-DD' });
    }
    const projectId = req.query.project_id ? parseInt(req.query.project_id, 10) : null;
    const cards = await planner.getPlannerCards(pool, { from, to, projectId });
    res.json({ cards });
  } catch (e) {
    console.error('[GET /api/publish/planner]', e);
    res.status(500).json({ error: e.message });
  }
});
```

- [ ] **Step 3: Синтаксис-проверка**

Run: `node --check server.js`
Expected: без ошибок (пустой вывод).

- [ ] **Step 4: Commit**

```bash
git add server.js
git commit -m "feat(planner): роут GET /api/publish/planner + флаг PLANNER_ENABLED"
```

---

## Task 5: Колонки очереди — навеска `attempt_count` + `transferred_to` (бэкенд)

Навешиваем два поля на строки `/api/publish/queue` после фетча (оба пути: legacy flat + paginated), за флагом. `client_publish_id`/`manual_handoff_at` приходят через `pq.*`.

**Files:**
- Modify: `server.js` (`~2015` роут queue; флаг рядом с `PLANNER_ENABLED`)
- Modify: `publish_planner.js` (экспорт хелпера навески)

- [ ] **Step 1: Хелпер навески в модуле** (`publish_planner.js`, добавить + в exports)

```js
/**
 * Догружает агрегаты попыток по client_publish_id и навешивает attempt_count/transferred_to.
 * Мутирует и возвращает rows. Без колонок #108 — проставляет 0/null.
 */
async function attachQueueTransferColumns(pool, rows) {
  if (!rows.length) return rows;
  const hasCol = await hasColumn(pool, 'publish_queue', 'client_publish_id');
  if (!hasCol) {
    for (const r of rows) { r.attempt_count = 0; r.transferred_to = null; }
    return rows;
  }
  const ids = [...new Set(rows.map(r => r.client_publish_id).filter(Boolean))];
  const byIntent = new Map();
  if (ids.length) {
    const { rows: arows } = await pool.query(`
      SELECT client_publish_id::text AS intent_id,
             (created_at AT TIME ZONE 'Europe/Moscow')::date::text AS date, error_code
      FROM publish_tasks WHERE client_publish_id = ANY($1::uuid[])
    `, [ids]);
    for (const a of arows) {
      if (!byIntent.has(a.intent_id)) byIntent.set(a.intent_id, []);
      byIntent.get(a.intent_id).push({ date: a.date, error_code: a.error_code });
    }
  }
  for (const r of rows) {
    const iid = r.client_publish_id ? String(r.client_publish_id) : null;
    const attempts = (iid && byIntent.get(iid)) || [];
    const scheduledDate = r.scheduled_at
      ? new Date(new Date(r.scheduled_at).getTime() + 3 * 3600 * 1000).toISOString().slice(0, 10) : null;
    const manualHandoffDate = r.manual_handoff_at
      ? new Date(new Date(r.manual_handoff_at).getTime() + 3 * 3600 * 1000).toISOString().slice(0, 10) : null;
    const { attempt_count, transferred_to } = deriveTransferColumns({ attempts, scheduledDate, manualHandoffDate });
    r.attempt_count = attempt_count;
    r.transferred_to = transferred_to;
  }
  return rows;
}

module.exports = { buildPlannerCards, deriveTransferColumns, getPlannerCards, attachQueueTransferColumns, SUCCESS_STATUSES };
```

- [ ] **Step 2: Флаг + навеска в роуте queue** (`server.js`)

Рядом с `PLANNER_ENABLED`:
```js
const QUEUE_TRANSFER_COLUMNS_ENABLED = process.env.QUEUE_TRANSFER_COLUMNS_ENABLED !== 'false';
```

В роуте `app.get('/api/publish/queue', ...)` (`~2015`) — **обе ветки** перед отправкой:

Legacy-ветка (`~2029`), заменить `return res.json(rows);` на:
```js
      if (QUEUE_TRANSFER_COLUMNS_ENABLED) await planner.attachQueueTransferColumns(pool, rows);
      return res.json(rows);
```

Paginated-ветка (`~2058`), перед `res.json(result);`:
```js
    if (QUEUE_TRANSFER_COLUMNS_ENABLED && Array.isArray(result.rows)) {
      await planner.attachQueueTransferColumns(pool, result.rows);
    }
    res.json(result);
```

> **Сверено:** `processPaginatedResult` (paginate.js:91) возвращает `{ rows, next_cursor, has_more }` — массив строк лежит в `result.rows` (НЕ `items`). Фронт очереди ходит пагинированно, так что именно эта ветка реально кормит UI.

- [ ] **Step 3: Синтаксис-проверка**

Run: `node --check server.js && node -e "require('./publish_planner'); console.log('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add server.js publish_planner.js
git commit -m "feat(planner): навеска attempt_count/transferred_to в /api/publish/queue за флагом"
```

---

## Task 6: Фронт — две колонки в таблице очереди

**Files:**
- Modify: `public/index.html` (заголовки `~2410–2440`, рендер `upqRenderRow` `~11129–11141`, конфиг `emptyColspan` `~11163`, загрузочные `colspan` `~2443`/`~2447`)

> Фронт-задачи проверяются в браузере (для монолитного `index.html` юнит-харнесса нет — это принятая практика проекта: live-smoke).

- [ ] **Step 1: Добавить два `<th>`** в первый ряд заголовков, **перед** `<th ...>Действия</th>` (строка `~2421`)

```html
            <th class="px-3 py-2.5 text-left whitespace-nowrap">Перенесено</th>
            <th class="px-3 py-2.5 text-left whitespace-nowrap">Попытка</th>
```

- [ ] **Step 2: Добавить два пустых фильтр-`<td>`** во второй ряд заголовков, перед последним `<td class="px-2 py-1"></td>` (строка `~2439`)

```html
            <td class="px-2 py-1"></td>
            <td class="px-2 py-1"></td>
```

- [ ] **Step 3: Добавить два `<td>`** в `upqRenderRow`, **перед** строкой действий (`~11140`)

```js
    <td class="px-3 py-2.5 text-xs text-gray-600 whitespace-nowrap">${row.transferred_to ? new Date(row.transferred_to).toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'}) : '<span class="text-gray-300">—</span>'}</td>
    <td class="px-3 py-2.5 text-xs text-gray-600 text-center">${row.attempt_count ? row.attempt_count : '<span class="text-gray-300">—</span>'}</td>
```

- [ ] **Step 4: Обновить `colspan` 11 → 13** в трёх местах: `emptyColspan: 11` → `13` (`~11163`), `<td colspan="11"` загрузки (`~2443`) и sentinel (`~2447`).

- [ ] **Step 5: Браузер-проверка**

Запустить локально (Задача 11 описывает деплой; для проверки достаточно открыть деливери после деплоя на тест). Открыть `#publishing/publishing?sub=up:queue`:
Expected: появились колонки «Перенесено» и «Попытка»; при отсутствии данных #108 — `—`; вёрстка не разъехалась (13 колонок).

- [ ] **Step 6: Commit**

```bash
git add public/index.html
git commit -m "feat(planner): колонки Перенесено/Попытка в таблице очереди"
```

---

## Task 7: Фронт — под-таб `up:planner` (навигация + контейнер)

**Files:**
- Modify: `public/index.html` (сайдбар `~272`, контейнер рядом с `up-queue-table` `~2456`, `upSwitchTab` `~10809`)

- [ ] **Step 1: Кнопка сайдбара** — после кнопки «Опубликовано» (строка `~272`)

```html
    <button onclick="nav('publishing'); upSwitchTab('planner');" id="nav-publishing-planner" class="nav-item w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-600 hover:bg-gray-100 text-left">
      <span>🗓️</span> Планировщик
    </button>
```

- [ ] **Step 2: Контейнер планировщика** — сразу после закрытия `<div id="up-queue-table">...</div>` (после строки `~2456`)

```html
  <div id="up-planner-table" class="hidden bg-white rounded-xl border border-gray-200 p-4">
    <div class="flex items-center justify-between mb-4 text-sm text-gray-600">
      <button onclick="plannerShiftWeek(-1)" class="px-2 py-1 rounded hover:bg-gray-100">← Пред. неделя</button>
      <div class="flex items-center gap-3">
        <select id="planner-project-select" onchange="plannerLoad()" class="border border-gray-200 rounded px-2 py-1 text-xs">
          <option value="">все клиенты</option>
        </select>
        <b id="planner-week-label"></b>
      </div>
      <button onclick="plannerShiftWeek(1)" class="px-2 py-1 rounded hover:bg-gray-100">След. неделя →</button>
    </div>
    <div id="planner-grid" class="grid grid-cols-7 gap-2"></div>
  </div>
```

- [ ] **Step 3: Расширить `upSwitchTab`** — заменить тело видимости/подсветки на три состояния. Заменить весь блок `if (tab === 'queue') { ... } else { ... }` (`~10822–10844`) и хвост (`~10846–10854`) на:

```js
  const pTable = document.getElementById('up-planner-table');
  const navP = document.getElementById('nav-publishing-planner');
  // сброс
  [navQ, navT, navP].forEach(n => { if (n) n.className = inactiveClass; });
  [qTable, tTable, pTable].forEach(t => { if (t) t.classList.add('hidden'); });
  const statsRow = document.getElementById('up-stats-row'); // блок счётчиков (см. grounding)

  if (tab === 'planner') {
    if (navP) navP.className = activeClass;
    if (pTable) pTable.classList.remove('hidden');
    if (statsRow) statsRow.classList.add('hidden');
    const titleEl = document.getElementById('up-section-title');
    if (titleEl) titleEl.textContent = 'Планировщик';
    _uptTable.onTabDeactivate(); _upqTable.onTabDeactivate();
    plannerInit();
    return;
  }
  if (statsRow) statsRow.classList.remove('hidden');

  if (tab === 'queue') {
    if (navQ) navQ.className = activeClass;
    if (qTable) qTable.classList.remove('hidden');
    const titleEl = document.getElementById('up-section-title');
    if (titleEl) titleEl.textContent = 'Запланировано';
    document.getElementById('up-stat-pending-label').textContent = 'ожидают';
    document.getElementById('up-stat-running-label').textContent = 'в работе';
    document.getElementById('up-stat-skipped-label').textContent = 'пропущено';
    _uptTable.onTabDeactivate(); _upqTable.onTabActivate(); loadQueueProjects();
  } else {
    if (navT) navT.className = activeClass;
    if (tTable) tTable.classList.remove('hidden');
    const titleEl = document.getElementById('up-section-title');
    if (titleEl) titleEl.textContent = 'Опубликовано';
    document.getElementById('up-stat-pending-label').textContent = 'ожидает';
    document.getElementById('up-stat-running-label').textContent = 'выполняется';
    document.getElementById('up-stat-skipped-label').textContent = 'обработка';
    _upqTable.onTabDeactivate(); _uptTable.onTabActivate(); loadTasksProjects();
  }
```

> **Сверено:** блок виджетов статистики — это `<div class="flex gap-1.5 flex-1 flex-wrap min-w-0">` (≈ строка 2364, оборачивает up-stat-total/pending/running/done/failed/skipped). У него НЕТ id — добавь `id="up-stats-row"`, чтобы `upSwitchTab('planner')` мог его скрыть. Заголовок `up-section-title` в planner-ветке ставим в «Планировщик».

- [ ] **Step 4: Браузер-проверка**

Открыть деливери, нажать «Планировщик»: появляется пустой контейнер с шапкой недели, URL → `?sub=up:planner`, переключение на «Запланировано»/«Опубликовано» работает как раньше.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(planner): под-таб up:planner — навигация и контейнер"
```

---

## Task 8: Фронт — `plannerLoad()` + рендер недельной сетки

**Files:**
- Modify: `public/index.html` (новый JS-блок рядом с `upSwitchTab`, `~10855`)

- [ ] **Step 1: Состояние недели + init + загрузка проектов**

```js
// ===== WP#109 Планировщик =====
let _plannerWeekStart = null; // понедельник текущей недели (Date, локально-наивно)

function plannerMonday(d) { const x = new Date(d); const wd = (x.getDay() + 6) % 7; x.setDate(x.getDate() - wd); x.setHours(0,0,0,0); return x; }
// ВАЖНО: локальные компоненты, НЕ toISOString — иначе для МСК (UTC+3) полночь уедет на −1 день.
function plannerFmt(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function plannerEsc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function plannerInit() {
  if (!_plannerWeekStart) _plannerWeekStart = plannerMonday(new Date());
  // заполнить дропдаун клиентов один раз
  const sel = document.getElementById('planner-project-select');
  if (sel && sel.options.length <= 1) {
    fetch('/api/validator/projects', { credentials: 'same-origin' }).then(r => r.json()).then(d => {
      (d.projects || []).forEach(p => { const o = document.createElement('option'); o.value = p.project_id; o.textContent = p.project_name; sel.appendChild(o); });
    }).catch(() => {});
  }
  plannerLoad();
}

function plannerShiftWeek(delta) {
  _plannerWeekStart = _plannerWeekStart || plannerMonday(new Date());
  _plannerWeekStart.setDate(_plannerWeekStart.getDate() + delta * 7);
  plannerLoad();
}
```

> Grounding: подтверди эндпоинт списка проектов — в `server.js` около строки 5690 есть `SELECT id AS project_id, project AS project_name ... FROM validator_projects WHERE active`. Найди его роут (`grep -n "project_id, project AS project_name" server.js` → подняться к `app.get(`) и подставь точный путь вместо `/api/projects-list`.

- [ ] **Step 2: `plannerLoad` — фетч + раскладка по дням**

```js
const PLANNER_STATE_BORDER = {
  published: 'border-violet-500', approved: 'border-emerald-500', pending: 'border-amber-500',
  partial: 'border-orange-500', echo: 'border-orange-500', final: 'border-violet-500',
};
const PLANNER_BADGE = {
  published: ['bg-violet-100 text-violet-700', n => `опубликовано ${n}`],
  approved:  ['bg-emerald-100 text-emerald-700', () => '✅ Одобрено'],
  pending:   ['bg-amber-100 text-amber-700', () => '⏳ Требует одобрения'],
  partial:   ['bg-orange-100 text-orange-700', n => `⚠️ Частично ${n}`],
  echo:      ['bg-orange-100 text-orange-700', n => `🔄 Перенос ${n}`],
  final:     ['bg-violet-100 text-violet-700', n => `опубликовано ${n}`],
};
const PLANNER_DOW = ['пн','вт','ср','чт','пт','сб','вс'];

async function plannerLoad() {
  _plannerWeekStart = _plannerWeekStart || plannerMonday(new Date());
  const from = new Date(_plannerWeekStart);
  const to = new Date(_plannerWeekStart); to.setDate(to.getDate() + 6);
  const proj = document.getElementById('planner-project-select')?.value || '';
  const lbl = document.getElementById('planner-week-label');
  if (lbl) lbl.textContent = `${from.toLocaleDateString('ru-RU',{day:'2-digit',month:'long'})} — ${to.toLocaleDateString('ru-RU',{day:'2-digit',month:'long'})}`;

  const qs = new URLSearchParams({ from: plannerFmt(from), to: plannerFmt(to) });
  if (proj) qs.set('project_id', proj);
  let cards = [];
  try {
    const r = await fetch(`/api/publish/planner?${qs}`, { credentials: 'same-origin' });
    cards = (await r.json()).cards || [];
  } catch (e) { cards = []; }

  // группировка по дню
  const byDay = {};
  for (let i = 0; i < 7; i++) { const d = new Date(from); d.setDate(d.getDate() + i); byDay[plannerFmt(d)] = []; }
  for (const c of cards) { if (byDay[c.business_date]) byDay[c.business_date].push(c); }

  const todayStr = plannerFmt(new Date());
  const grid = document.getElementById('planner-grid');
  grid.innerHTML = '';
  for (let i = 0; i < 7; i++) {
    const d = new Date(from); d.setDate(d.getDate() + i);
    const ds = plannerFmt(d);
    const col = document.createElement('div');
    col.className = 'min-h-[180px]';
    const isToday = ds === todayStr;
    col.innerHTML = `<div class="text-center text-xs rounded-md py-1.5 mb-2 ${isToday ? 'bg-violet-700 text-white' : 'text-gray-500'}">
      ${PLANNER_DOW[i]}<span class="block text-lg font-semibold">${d.getDate()}</span></div>`;
    // сортировка: переносные цепочки (orange/closed) вверх, стабильно по chain_id; прочее ниже
    const order = { partial: 0, echo: 0, final: 1, published: 2, approved: 3, pending: 4 };
    const day = byDay[ds].sort((a, b) => (order[a.state] - order[b.state]) || a.chain_id.localeCompare(b.chain_id));
    for (const c of day) col.insertAdjacentHTML('beforeend', plannerCardHtml(c));
    grid.appendChild(col);
  }
  plannerWireCards();
}
```

- [ ] **Step 3: `plannerCardHtml` — карточка**

```js
function plannerCardHtml(c) {
  const border = PLANNER_STATE_BORDER[c.state] || 'border-gray-200';
  const [badgeCls, badgeFn] = PLANNER_BADGE[c.state] || ['bg-gray-100 text-gray-600', () => c.state];
  const ratio = (c.done_count != null && c.total_accounts != null) ? `${c.done_count}/${c.total_accounts}` : '';
  const isOrange = c.state === 'partial' || c.state === 'echo';
  const showBar = c.total_accounts ? true : false;
  const pct = c.total_accounts ? Math.round((c.done_count / c.total_accounts) * 100) : 0;

  const notes = [];
  const dm = s => s ? new Date(s).toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'}) : '';
  if (c.carried_in_from && c.state === 'echo') notes.push(`↩ с ${dm(c.carried_in_from)}`);
  if (c.carried_out_count > 0) notes.push(`↗ ${c.carried_out_count}${c.carried_out_to ? ' на ' + dm(c.carried_out_to) : ' ожидают'}`);
  if (c.state === 'final' && c.closed_transfer_from) notes.length = 0, notes.push(`↩ закрыло перенос с ${dm(c.closed_transfer_from)}`);
  const noteCls = c.state === 'final' ? 'text-violet-700' : 'text-orange-700';

  const mode = c.mode === 'manual'
    ? `<span class="inline-flex items-center gap-1 bg-violet-100 text-violet-700 px-2 py-0.5 rounded-lg text-[10px]">👋 вручную</span>`
    : `<span class="inline-flex items-center gap-1 bg-gray-100 text-gray-600 px-2 py-0.5 rounded-lg text-[10px]">🤖 авто</span>`;

  return `<div data-chain="${plannerEsc(c.chain_id)}" data-has-exec="${c.total_accounts != null ? '1' : '0'}" data-project="${plannerEsc(c.project_name || '')}"
      class="planner-card border-2 ${border} rounded-xl p-2.5 mb-2 cursor-pointer hover:shadow transition flex flex-col justify-between min-h-[140px]">
    <div>
      <div class="text-indigo-500 text-xs font-medium truncate">🎬 ${plannerEsc(c.project_name || '—')}</div>
      <div class="text-gray-800 text-xs leading-snug mb-1.5" style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${plannerEsc(c.video_title || '—')}</div>
      <span class="inline-block ${badgeCls} px-2 py-0.5 rounded-full text-[10px] font-medium">${badgeFn(ratio)}</span>
      ${showBar ? `<div class="mt-1.5 h-[3px] bg-gray-100 rounded overflow-hidden"><div class="h-full ${isOrange ? 'bg-orange-500' : 'bg-violet-500'}" style="width:${pct}%"></div></div>` : ''}
      ${notes.length ? `<div class="mt-1 text-[10px] italic ${noteCls} truncate">${notes.join(' · ')}</div>` : ''}
    </div>
    <div class="mt-1">${mode}</div>
  </div>`;
}
```

- [ ] **Step 4: Браузер-проверка**

После деплоя на тест — открыть планировщик: карточки раскладываются по дням; бейджи/цвета/прогресс/пометки/режим соответствуют макету; «сегодня» подсвечена.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(planner): plannerLoad + рендер недельной сетки и карточек"
```

---

## Task 9: Фронт — hover-подсветка + (навигация уже в Задаче 7/8)

**Files:**
- Modify: `public/index.html` (рядом с `plannerLoad`)

- [ ] **Step 1: `plannerWireCards` (hover; клик добавим в Задаче 10)**

```js
function plannerWireCards() {
  document.querySelectorAll('#planner-grid .planner-card[data-chain]').forEach(card => {
    card.addEventListener('mouseenter', () => {
      const chain = card.dataset.chain;
      document.querySelectorAll('#planner-grid .planner-card').forEach(c => {
        if (c.dataset.chain !== chain) c.classList.add('opacity-20');
      });
    });
    card.addEventListener('mouseleave', () => {
      document.querySelectorAll('#planner-grid .planner-card.opacity-20').forEach(c => c.classList.remove('opacity-20'));
    });
  });
}
```

- [ ] **Step 2: Браузер-проверка**

Навести курсор на оранжевую карточку цепочки — её эхо-карты в соседних днях остаются яркими, остальные приглушаются (opacity 0.2); увод курсора — всё возвращается. Кнопки «Пред./След. неделя» сдвигают диапазон и рефетчат; фильтр клиента сужает срез.

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "feat(planner): hover-подсветка цепочки переноса"
```

---

## Task 10: Фронт — клик по карточке → детали слота (очередь по цепочке)

**Files:**
- Modify: `public/index.html` (рядом с `plannerLoad`)

- [ ] **Step 1: Расширить `plannerWireCards` — добавить клик (читаем `dataset`, без inline-JSON)**

Заменить функцию `plannerWireCards` (из Задачи 9) на версию с hover + click:

```js
function plannerWireCards() {
  const cards = document.querySelectorAll('#planner-grid .planner-card[data-chain]');
  cards.forEach(card => {
    card.addEventListener('mouseenter', () => {
      const chain = card.dataset.chain;
      cards.forEach(c => { if (c.dataset.chain !== chain) c.classList.add('opacity-20'); });
    });
    card.addEventListener('mouseleave', () => {
      document.querySelectorAll('#planner-grid .planner-card.opacity-20').forEach(c => c.classList.remove('opacity-20'));
    });
    card.addEventListener('click', () => {
      if (card.dataset.hasExec !== '1') return; // плановая карточка (нет выкладки) — деталей нет
      // переключаемся на очередь и фильтруем по проекту (подслоты = строки аккаунтов)
      upSwitchTab('queue');
      setTimeout(() => {
        const sel = document.getElementById('up-project-select');
        const proj = card.dataset.project || '';
        if (sel && proj) {
          for (const o of sel.options) { if (o.textContent === proj) { sel.value = o.value; break; } }
          if (typeof upColFilter === 'function') upColFilter('project', sel.value);
        }
      }, 50);
    });
  });
}
```

> Grounding: проверь сигнатуру `upColFilter(col, value)` (`grep -n "function upColFilter" public/index.html`) и значение, которое ждёт фильтр «project» (id проекта vs имя). Если очередь умеет фильтр по `unic_task_id`/дате — добавь более точную фильтрацию по цепочке. Минимально достаточно фильтра по проекту. Клик навешивается через `dataset` (`data-has-exec`, `data-project`) — без inline-`onclick` с JSON (XSS-безопасно).

- [ ] **Step 2: Браузер-проверка**

Клик по карточке с выкладкой → открывается под-таб «Запланировано», очередь отфильтрована по проекту карточки (видны строки-аккаунты). Клик по плановой (approved/pending) карточке — ничего не ломает (no-op).

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "feat(planner): клик по карточке → очередь по цепочке"
```

---

## Task 11: Интеграция, деплой, live-smoke, OpenProject

**Files:** —

- [ ] **Step 1: Прогон всех юнит-тестов (изолированный клон)**

Run: `node --test test_publish_planner.test.js`
Expected: PASS (11 тестов).

- [ ] **Step 2: Cross-repo grep (общая БД openclaw)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && grep -rn "PLANNER_ENABLED\|QUEUE_TRANSFER_COLUMNS_ENABLED\|/api/publish/planner\|attachQueueTransferColumns" --include=*.js .
# и в валидаторе — нет ли коллизий имён роута/флагов
```
Expected: совпадения только в новом коде #109; коллизий нет.

- [ ] **Step 3: Деплой в прод-чекаут (с одобрения Данила, без force-push)**

Перенести коммиты (`publish_planner.js`, `test_publish_planner.test.js`, изменения `server.js`/`public/index.html`) в `/root/.openclaw/workspace-genri/autowarm/`, затем:
```bash
pm2 restart autowarm
```
> ⚠️ Прод-чекаут имеет auto-push hook → коммит улетит в `GenGo2/delivery-contenthunter`. Убедиться, что прод-чекаут на правильной ветке (не чужой); не делать force-push.

- [ ] **Step 4: Live-smoke планировщика (с реальными/тестовыми данными)**

- Открыть `https://delivery.contenthunter.ru/#publishing/publishing?sub=up:planner`.
- Если #108 в проде и есть цепочки с переносами — проверить, что карточки `partial/echo/final` рисуются на верных днях, `N/N` сходится, hover работает, колонки очереди показывают «перенесено»/«попытка».
- Если #108 ещё нет — убедиться в **деградации**: карточки published/partial по статусам без цепочек, колонки очереди `—`, ошибок в консоли/логах нет (`pm2 logs autowarm --lines 50`).
- Плановые карточки (approved/pending) на будущие дни отображаются из расписания.

- [ ] **Step 5: Обновить OpenProject WP #109** (house comment style: Что было не так → Что сделано → Что осталось; plain language, без жаргона/footer; по-русски)

Если задеплоено и проверено — статус «Тестирование» (id 9). Комментарий, например:
> **Что сделано:** в деливери появился календарь-планировщик выкладок (раздел «Выкладка» → «Планировщик»): по дням недели видно ролики по клиентам, сколько аккаунтов уже выложено (N/N), и переносы — когда часть не вышла сегодня и уехала на следующий день, а на третий день делается вручную. Наведёшь на ролик — подсветится вся его цепочка переноса. В таблице очереди добавлены колонки «перенесено» (на какую дату уехал) и «попытка» (сколько раз пытались).
> **Что осталось:** проверить вживую на реальных переносах после запуска движка ретраев; пока он не включён — переносы показываются по мере накопления данных.

---

## Self-Review

**1. Spec coverage:**
- §1 (две части — календарь + 2 колонки): Задачи 6 (колонки фронт), 5 (колонки бэк), 7–10 (календарь). ✅
- §4 (тонкий контракт #108): Задача 3 (`client_publish_id`, `publish_tasks`, `manual_handoff_at`) + деградация. ✅
- §5 (read-model эндпоинт + union план/выкладка): Задачи 3–4. ✅
- §6 (карточки/состояния): `buildPlannerCards` (Задача 1) + `plannerCardHtml` (Задача 8). ✅
- §7 (вывод переносов из таймлайна, МСК): Задача 1 (логика) + Задача 3 (`AT TIME ZONE 'Europe/Moscow'`). ✅
- §8 (колонки очереди): Задачи 2,5,6. ✅
- §9 (навигация/фронт): Задачи 7,8. ✅
- §10 (интерактивность: hover, навигация, клик): Задачи 9,10. ✅
- §11 (сортировка/lane): Задача 8 Step 2 (сорт по state→chain_id). ✅
- §12 (edge cases: process_interrupted, published_no_url, легаси, N меняется): покрыто тестами Задач 1–2 + деградация Задачи 3. ✅
- §13 (kill-switches): `PLANNER_ENABLED` (Задача 4), `QUEUE_TRANSFER_COLUMNS_ENABLED` (Задача 5). ✅
- §14 (тестирование): Задачи 1–2 (юнит) + Задача 11 (live-smoke). ✅
- §15 (деплой/деградация): Задача 11. ✅

**2. Placeholder scan:** код в Задачах 1–10 конкретный; «grounding»-шаги содержат реальные команды (psql/grep), а не TODO. Маппинг статусов контента — конкретный (`approved`→approved, иначе pending) с командой сверки.

**3. Type consistency:** форма карточки (`chain_id, business_date, project_id, project_name, video_title, total_accounts, done_count, state, mode, carried_in_from, carried_out_count, carried_out_to, closed_transfer_from`) идентична в `buildPlannerCards` (Задача 1), деградации/плане (Задача 3) и `plannerCardHtml`/`plannerLoad` (Задача 8). `deriveTransferColumns` → `{attempt_count, transferred_to}` совпадает между Задачей 2 и навеской (Задача 5) и рендером строки (Задача 6). Имена функций (`getPlannerCards`, `attachQueueTransferColumns`, `plannerLoad`, `plannerCardHtml`, `plannerWireCards`, `plannerShiftWeek`, `plannerInit`, `plannerFmt`, `plannerEsc`) согласованы; клик навешивается в `plannerWireCards` через `dataset` (без inline-JSON).
