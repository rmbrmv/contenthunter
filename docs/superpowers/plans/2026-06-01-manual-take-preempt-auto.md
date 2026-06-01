# Вытеснение автовыкладки при «Взять в работу» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При «Взять в работу» в ручной очереди — мгновенно вытеснять (SIGTERM→SIGKILL) уже бегущую автовыкладку на том же телефоне и честно показывать оператору «телефон освобождается… NN сек» до реального освобождения.

**Architecture:** Вытеснение живёт в `scheduler.js` (он владеет child-процессом авто-задачи через `running`-Map): новая `preemptForDevice(deviceSerial, claimedUnicResultId)` убивает publish-процессы на устройстве и сама пишет финальный статус в БД после смерти процесса (requeue по умолчанию; cancel — если контент задачи = взятый оператором пак, анти-двойная-публикация). Триггерится из take-хендлеров `server.js` под kill-switch. GET ручной очереди отдаёт флаг `device_auto_busy` (есть ли `publish_task` running/delegated на устройстве); UI крутит спиннер+таймер пока флаг истинен и блокирует кнопки платформ.

**Tech Stack:** Node.js (Express, `pg`), `node --test` (реальная БД-фикстура openclaw:openclaw123@localhost:5432), ванильный JS-фронт (`public/index.html` + `public/mpq_pure.js`).

---

## Контекст исполнителя (прочитай до старта)

- **Репозиторий кода:** `delivery-contenthunter` (GenGo2). Прод — `/root/.openclaw/workspace-genri/autowarm`, процесс `pm2 #35` (`server.js` + `scheduler.js` в одном процессе).
- **ОБЩИЙ чекаут!** Реализацию вести в worktree от `origin/main`, НИКОГДА `checkout -b` в основном чекауте. Worktree уже создан: `/home/claude-user/autowarm-testbench-preempt` (ветка `feat/manual-take-preempt-auto`, от `origin/main`), `node_modules` симлинком. Если его нет — создать:
  ```bash
  cd /home/claude-user/autowarm-testbench
  git fetch origin main
  git worktree add -b feat/manual-take-preempt-auto /home/claude-user/autowarm-testbench-preempt origin/main
  ln -s /home/claude-user/autowarm-testbench/node_modules /home/claude-user/autowarm-testbench-preempt/node_modules
  ```
- Все пути ниже — относительно worktree `/home/claude-user/autowarm-testbench-preempt`.
- **Запуск тестов:** `node --test --test-force-exit tests/<file>` (флаг нужен, т.к. набор открывает pg-pool).
- **Спека:** `contenthunter/docs/superpowers/specs/2026-06-01-manual-take-preempt-auto-design.md`.
- Паттерн БД-тестов — копировать из `tests/test_manual_inprogress_blocks_dispatch.test.js` (фикстуры project/content/slot/mpq, `before`/`after`, `pool.end()`).

## Файловая структура (что трогаем)

- **Modify** `scheduler.js` — `preemptForDevice` + `_preemptFate` + `_killAndWait` + тест-сидеры + экспорт.
- **Modify** `manual_publish_queue.js` — `JOINED_SELECT` (+`q.taken_at`, +`device_auto_busy`), `rowToDict` (проброс двух полей).
- **Modify** `server.js` — take-хендлеры (`/take`, `/group/:unicResultId/take`) зовут `preemptForDevice` под kill-switch.
- **Modify** `public/mpq_pure.js` — чистая `mpqIsReleasing(card)`.
- **Modify** `public/index.html` — `mpqCards` (+`device_auto_busy`,`taken_at`), рендер релизинг-бейджа+спиннера+таймера, блок кнопок, `mpqRowSig`/`mpqCardComputeSig` (+`device_auto_busy`), ускорение поллинга.
- **Create** `tests/test_preempt_for_device.test.js` — юниты scheduler-вытеснения.
- **Create** `tests/test_mpq_device_auto_busy.test.js` — юнит `device_auto_busy` в выдаче.
- **Create** `tests/test_mpq_is_releasing.test.js` — юнит чистой UI-функции.

---

## Task 1: `_preemptFate` — решение requeue vs cancel

**Files:**
- Modify: `scheduler.js` (рядом с `getManualBusyDevices`, ~строка 130)
- Test: `tests/test_preempt_for_device.test.js`

Решение судьбы вытесняемой авто-задачи: `cancel`, если её контент (`publish_queue.unic_result_id` по `publish_task_id`) совпадает с паком, который берёт оператор (`claimedUnicResultId`); иначе `requeue`.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_preempt_for_device.test.js`:

```javascript
'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');

const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

const PID=9913000, CONTENT=9913000, PT_SAME=9913001, PT_OTHER=9913002;
const UNIC_CLAIMED=9913100, UNIC_OTHER=9913200, PQ_SAME=9913001, PQ_OTHER=9913002;

const scheduler = require('../scheduler');

async function cleanup(){
  await pool.query(`DELETE FROM publish_queue WHERE id IN ($1,$2)`,[PQ_SAME,PQ_OTHER]).catch(()=>{});
  await pool.query(`DELETE FROM publish_tasks WHERE id IN ($1,$2)`,[PT_SAME,PT_OTHER]).catch(()=>{});
  await pool.query(`DELETE FROM validator_content WHERE id=$1`,[CONTENT]).catch(()=>{});
  await pool.query(`DELETE FROM validator_projects WHERE id=$1`,[PID]).catch(()=>{});
}
before(async()=>{
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,'PreemptFix','preemptfix',true,false)`,[PID]);
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'preempt-fix','approved','video',1)`,[CONTENT,PID]);
  // две авто-задачи на одном устройстве: одна = взятый пак, другая = другой пак
  await pool.query(`INSERT INTO publish_tasks (id,device_serial,status) VALUES ($1,'PREEMPT_DEV','running'),($2,'PREEMPT_DEV','running')`,[PT_SAME,PT_OTHER]);
  await pool.query(`INSERT INTO publish_queue (id,unic_result_id,project_id,platform,device_serial,status,publish_task_id) VALUES ($1,$2,$3,'tiktok','PREEMPT_DEV','running',$4)`,[PQ_SAME,UNIC_CLAIMED,PID,PT_SAME]);
  await pool.query(`INSERT INTO publish_queue (id,unic_result_id,project_id,platform,device_serial,status,publish_task_id) VALUES ($1,$2,$3,'tiktok','PREEMPT_DEV','running',$4)`,[PQ_OTHER,UNIC_OTHER,PID,PT_OTHER]);
  scheduler._setPoolForTest(pool);
});
after(async()=>{ await cleanup(); await pool.end(); });

test('_preemptFate: cancel когда контент задачи = взятый пак', async()=>{
  assert.equal(await scheduler._preemptFate(PT_SAME, UNIC_CLAIMED), 'cancel');
});
test('_preemptFate: requeue когда контент задачи — другой пак', async()=>{
  assert.equal(await scheduler._preemptFate(PT_OTHER, UNIC_CLAIMED), 'requeue');
});
test('_preemptFate: requeue когда claimedUnicResultId не задан', async()=>{
  assert.equal(await scheduler._preemptFate(PT_SAME, null), 'requeue');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_preempt_for_device.test.js`
Expected: FAIL — `scheduler._preemptFate is not a function`.

- [ ] **Step 3: Реализовать `_preemptFate`**

В `scheduler.js` после функции `getManualBusyDevices` (≈строка 155) добавить:

```javascript
// Судьба вытесняемой авто-задачи: 'cancel' если её контент = пак, взятый оператором
// (иначе авто выложит повторно после ручной выкладки), иначе 'requeue'.
async function _preemptFate(taskId, claimedUnicResultId) {
  if (!claimedUnicResultId) return 'requeue';
  try {
    const { rows } = await pool.query(
      `SELECT unic_result_id FROM publish_queue WHERE publish_task_id=$1 LIMIT 1`, [taskId]);
    const taskUnic = rows.length ? rows[0].unic_result_id : null;
    return (taskUnic != null && String(taskUnic) === String(claimedUnicResultId)) ? 'cancel' : 'requeue';
  } catch (e) {
    console.error(`Scheduler: _preemptFate error для #${taskId}:`, e.message);
    return 'requeue'; // fail-safe: не теряем авто-задачу
  }
}
```

Добавить `_preemptFate` в `module.exports` (строка ~615, в общий объект):

```javascript
module.exports = { init, getStatus, killTask, tick, runAnalytics,
                   parseAdbDeviceState, shouldSkipUnhealthyDevice,
                   deviceHealthCooldownActive,
                   getManualBusyDevices, getCandidates, _setPoolForTest,
                   preemptForDevice, _preemptFate, _injectRunningForTest };
```

(`preemptForDevice` и `_injectRunningForTest` появятся в Task 2 — экспорт можно добавить сейчас, JS-функции поднимаются hoisting'ом только для `function`-деклараций; чтобы избежать `undefined` в экспорте до Task 2, временно добавь в экспорт только `_preemptFate`, а `preemptForDevice`/`_injectRunningForTest` допиши в Task 2.)

Итог для этого шага — экспорт:
```javascript
                   getManualBusyDevices, getCandidates, _setPoolForTest,
                   _preemptFate };
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_preempt_for_device.test.js`
Expected: PASS (3/3).

- [ ] **Step 5: Коммит**

```bash
git add scheduler.js tests/test_preempt_for_device.test.js
git commit -m "feat(scheduler): _preemptFate — requeue vs cancel для вытеснения авто-задачи"
```

---

## Task 2: `preemptForDevice` — убийство процессов + запись судьбы

**Files:**
- Modify: `scheduler.js`
- Test: `tests/test_preempt_for_device.test.js` (дописать)

`preemptForDevice` перебирает `running`-Map, убивает publish-процессы на устройстве (SIGTERM, через grace — SIGKILL), ждёт `exit`, затем пишет в БД requeue/cancel. Под kill-switch `MANUAL_TAKE_PREEMPT_AUTO_ENABLED`. Для тестируемости — инъектор фейковых `running`-entry и env-overridable grace.

- [ ] **Step 1: Написать падающие тесты (дописать в конец файла)**

```javascript
const { test: t2 } = require('node:test');

// Фейковый child: записывает сигналы, отдаёт exit по требованию.
function fakeChild() {
  const listeners = {};
  return {
    signals: [], exitCode: null,
    kill(sig){ this.signals.push(sig); },
    once(ev, cb){ (listeners[ev] = listeners[ev] || []).push(cb); },
    _emitExit(code){ this.exitCode = code; (listeners.exit||[]).forEach(cb=>cb(code)); },
  };
}

t2('preemptForDevice: requeue другого пака — publish_task→pending, started_at=NULL', async()=>{
  process.env.PREEMPT_SIGKILL_GRACE_MS = '50';
  delete process.env.MANUAL_TAKE_PREEMPT_AUTO_ENABLED;
  await pool.query(`UPDATE publish_tasks SET status='running', started_at=now() WHERE id=$1`,[PT_OTHER]);
  const child = fakeChild();
  scheduler._injectRunningForTest(`publish:${PT_OTHER}`, { type:'publish', device_serial:'PREEMPT_DEV', child });
  const res = scheduler.preemptForDevice('PREEMPT_DEV', UNIC_CLAIMED);
  assert.deepEqual(res.killed.sort(), [PT_OTHER]);
  child._emitExit(143);                       // процесс умер по SIGTERM
  await new Promise(r=>setTimeout(r,150));     // дать _preemptOne записать БД
  const { rows } = await pool.query(`SELECT status, started_at FROM publish_tasks WHERE id=$1`,[PT_OTHER]);
  assert.equal(rows[0].status,'pending');
  assert.equal(rows[0].started_at, null);
  assert.ok(child.signals.includes('SIGTERM'));
});

t2('preemptForDevice: cancel same-content — publish_task→cancelled+preempted_by_manual, publish_queue помечен', async()=>{
  process.env.PREEMPT_SIGKILL_GRACE_MS = '50';
  await pool.query(`UPDATE publish_tasks SET status='running' WHERE id=$1`,[PT_SAME]);
  await pool.query(`UPDATE publish_queue SET status='running', manual_handoff_at=NULL WHERE id=$1`,[PQ_SAME]);
  const child = fakeChild();
  scheduler._injectRunningForTest(`publish:${PT_SAME}`, { type:'publish', device_serial:'PREEMPT_DEV', child });
  scheduler.preemptForDevice('PREEMPT_DEV', UNIC_CLAIMED);
  child._emitExit(137);
  await new Promise(r=>setTimeout(r,150));
  const pt = (await pool.query(`SELECT status, error_class FROM publish_tasks WHERE id=$1`,[PT_SAME])).rows[0];
  assert.equal(pt.status,'cancelled');
  assert.equal(pt.error_class,'preempted_by_manual');
  const pq = (await pool.query(`SELECT status, manual_handoff_at FROM publish_queue WHERE id=$1`,[PQ_SAME])).rows[0];
  assert.equal(pq.status,'cancelled');
  assert.ok(pq.manual_handoff_at != null);
});

t2('preemptForDevice: kill-switch off → no-op (ничего не убивает)', async()=>{
  process.env.MANUAL_TAKE_PREEMPT_AUTO_ENABLED='false';
  try {
    const child = fakeChild();
    scheduler._injectRunningForTest(`publish:${PT_OTHER}`, { type:'publish', device_serial:'PREEMPT_DEV', child });
    const res = scheduler.preemptForDevice('PREEMPT_DEV', UNIC_CLAIMED);
    assert.deepEqual(res.killed, []);
    assert.deepEqual(child.signals, []);
  } finally { delete process.env.MANUAL_TAKE_PREEMPT_AUTO_ENABLED; }
});

t2('preemptForDevice: SIGKILL после grace если процесс не умер по TERM', async()=>{
  process.env.PREEMPT_SIGKILL_GRACE_MS='30';
  delete process.env.MANUAL_TAKE_PREEMPT_AUTO_ENABLED;
  const child = fakeChild();
  scheduler._injectRunningForTest(`publish:${PT_OTHER}`, { type:'publish', device_serial:'PREEMPT_DEV', child });
  scheduler.preemptForDevice('PREEMPT_DEV', UNIC_CLAIMED);
  await new Promise(r=>setTimeout(r,80));      // > grace, exit не эмитили
  assert.ok(child.signals.includes('SIGTERM'));
  assert.ok(child.signals.includes('SIGKILL'));
  child._emitExit(137);                          // подчистить
  await new Promise(r=>setTimeout(r,50));
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_preempt_for_device.test.js`
Expected: FAIL — `scheduler.preemptForDevice is not a function` / `_injectRunningForTest is not a function`.

- [ ] **Step 3: Реализовать `preemptForDevice` + `_killAndWait` + сидер**

В `scheduler.js` после `_preemptFate` добавить:

```javascript
const PREEMPT_SIGKILL_GRACE_MS = () => parseInt(process.env.PREEMPT_SIGKILL_GRACE_MS, 10) || 15000;

// Вытеснить бегущие publish-задачи на устройстве (оператор взял телефон в работу).
// Best-effort: действуем только на процессы из running-Map (которые мы спавнили);
// delegated/чужие не трогаем — device_auto_busy честно останется true до их финиша.
function preemptForDevice(deviceSerial, claimedUnicResultId) {
  if (process.env.MANUAL_TAKE_PREEMPT_AUTO_ENABLED === 'false') return { killed: [], skipped: [] };
  const killed = [];
  for (const [key, v] of running.entries()) {
    if (v.type !== 'publish' || v.device_serial !== deviceSerial) continue;
    const id = parseInt(key.split(':')[1], 10);
    v.preempting = true;
    killed.push(id);
    _preemptOne(id, key, v, claimedUnicResultId).catch(e =>
      console.error(`Scheduler: _preemptOne error для #${id}:`, e.message));
  }
  if (killed.length) console.log(`🛑 Вытеснение авто на ${deviceSerial}: publish #${killed.join(', #')} (взят пак ${claimedUnicResultId})`);
  return { killed, skipped: [] };
}

async function _preemptOne(id, key, entry, claimedUnicResultId) {
  const fate = await _preemptFate(id, claimedUnicResultId);   // решаем ДО смерти процесса
  await _killAndWait(entry);                                   // SIGTERM → grace → SIGKILL → exit
  if (fate === 'cancel') {
    await pool.query(`UPDATE publish_tasks SET status='cancelled', error_class='preempted_by_manual', updated_at=NOW() WHERE id=$1`, [id]);
    await pool.query(`UPDATE publish_queue SET status='cancelled', manual_handoff_at=COALESCE(manual_handoff_at, NOW()), updated_at=NOW() WHERE publish_task_id=$1`, [id]);
  } else {
    await pool.query(`UPDATE publish_tasks SET status='pending', started_at=NULL, updated_at=NOW() WHERE id=$1`, [id]);
  }
}

function _killAndWait(entry) {
  return new Promise((resolve) => {
    const child = entry.child;
    if (!child || child.exitCode !== null) return resolve();
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    child.once('exit', finish);
    try { child.kill('SIGTERM'); } catch (e) {}
    const grace = PREEMPT_SIGKILL_GRACE_MS();
    setTimeout(() => { if (!done && child.exitCode === null) { try { child.kill('SIGKILL'); } catch (e) {} } }, grace);
    setTimeout(finish, grace + 5000);   // safety: не висим вечно
  });
}

// тест-сидер: положить фейковую running-entry без реального спавна
function _injectRunningForTest(key, entry) { running.set(key, entry); }
```

Обновить `module.exports`, добавив `preemptForDevice` и `_injectRunningForTest`:

```javascript
                   getManualBusyDevices, getCandidates, _setPoolForTest,
                   _preemptFate, preemptForDevice, _injectRunningForTest };
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_preempt_for_device.test.js`
Expected: PASS (7/7).

- [ ] **Step 5: Коммит**

```bash
git add scheduler.js tests/test_preempt_for_device.test.js
git commit -m "feat(scheduler): preemptForDevice — SIGTERM/SIGKILL + requeue/cancel вытеснённой авто-задачи"
```

---

## Task 3: Триггер вытеснения в take-хендлерах

**Files:**
- Modify: `server.js` (хендлеры `:id/take` ≈5798, `group/:unicResultId/take` ≈5822)
- Test: `tests/test_preempt_for_device.test.js` (дописать — проверяем выбор device/unic, не сам HTTP)

Take-хендлеры после успешного claim зовут `scheduler.preemptForDevice(device, unicResultId)` (огонь-и-забыли). Чтобы это было тестируемо без поднятия Express — вынести выбор аргументов в чистую функцию `pickPreemptArgs(items)` рядом с хендлерами и экспортировать её из `server.js` (там уже есть экспорт-блок для тестов dispatch).

- [ ] **Step 1: Написать падающий тест**

```javascript
const { test: t3 } = require('node:test');
const srv = require('../server');   // ВНИМАНИЕ: server поднимает loops → запускать с --test-force-exit

t3('pickPreemptArgs: берёт device_serial и unic_result_id из строк пака', () => {
  const items = [{ device_serial:'DEV1', unic_result_id: 555 }, { device_serial:'DEV1', unic_result_id: 555 }];
  assert.deepEqual(srv.pickPreemptArgs(items), { deviceSerial:'DEV1', unicResultId:555 });
});
t3('pickPreemptArgs: пустой/без device → null (нечего вытеснять)', () => {
  assert.equal(srv.pickPreemptArgs([]), null);
  assert.equal(srv.pickPreemptArgs([{ device_serial:'', unic_result_id:1 }]), null);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_preempt_for_device.test.js`
Expected: FAIL — `srv.pickPreemptArgs is not a function`.

- [ ] **Step 3: Реализация в `server.js`**

Рядом с take-хендлерами (≈5797) добавить чистый помощник:

```javascript
// Выбор аргументов вытеснения из строк взятого пака (пак = 1 устройство).
function pickPreemptArgs(items) {
  if (!Array.isArray(items) || !items.length) return null;
  const withDev = items.find(i => i && i.device_serial);
  if (!withDev) return null;
  return { deviceSerial: withDev.device_serial, unicResultId: withDev.unic_result_id };
}
```

Обновить хендлеры. Одиночный take (≈5798):

```javascript
app.post('/api/publishing/manual-queue/:id/take', requireAuth, async (req, res) => {
  try {
    const item = await mpq.takeItem(pool, parseInt(req.params.id, 10));
    const pa = pickPreemptArgs([item]);
    if (pa) scheduler.preemptForDevice(pa.deviceSerial, pa.unicResultId);   // fire-and-forget
    res.json(item);
  } catch (e) { res.status(e.httpStatus || 500).json({ error: e.message }); }
});
```

Групповой take (≈5822):

```javascript
app.post('/api/publishing/manual-queue/group/:unicResultId/take', requireAuth, async (req, res) => {
  try {
    const uid = req.session.user && req.session.user.id;
    const items = await mpq.takeGroup(pool, parseInt(req.params.unicResultId, 10), uid);
    const pa = pickPreemptArgs(items);
    if (pa) scheduler.preemptForDevice(pa.deviceSerial, pa.unicResultId);   // fire-and-forget
    res.json({ items });
  } catch (e) {
    res.status(e.httpStatus || 500).json({ error: e.message, taken_by: e.taken_by });
  }
});
```

Экспортировать `pickPreemptArgs`. Найти существующий тест-экспорт (`module.exports = { ... fetchBusyDevices, insertPublishTaskRaceSafe ... }`) и добавить:

```javascript
module.exports = { /* …существующие… */ pickPreemptArgs };
```

(Если экспорта нет — добавить в конец `server.js`: `module.exports = Object.assign(module.exports || {}, { fetchBusyDevices, insertPublishTaskRaceSafe, pickPreemptArgs });` — сверить имена с тем, что уже экспортируется для dispatch-тестов.)

Примечание: `scheduler` уже импортирован в `server.js` (`const scheduler = require('./scheduler')`), `preemptForDevice` уже в его экспорте (Task 2). Kill-switch проверяется внутри `preemptForDevice`.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_preempt_for_device.test.js`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add server.js tests/test_preempt_for_device.test.js
git commit -m "feat(server): take/group-take триггерят preemptForDevice (pickPreemptArgs)"
```

---

## Task 4: `device_auto_busy` + `taken_at` в выдаче ручной очереди

**Files:**
- Modify: `manual_publish_queue.js` (`JOINED_SELECT` ≈ строка с SELECT, `rowToDict`)
- Test: `tests/test_mpq_device_auto_busy.test.js`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_mpq_device_auto_busy.test.js`:

```javascript
'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const mpq = require('../manual_publish_queue');

const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });
const PID=9913500, CONTENT=9913500, SLOT=9913500, ROW_BUSY=9913501, ROW_FREE=9913502, PT=9913500;

async function cleanup(){
  await pool.query(`DELETE FROM publish_tasks WHERE id=$1`,[PT]).catch(()=>{});
  await pool.query(`DELETE FROM validator_manual_publish_queue WHERE id IN ($1,$2)`,[ROW_BUSY,ROW_FREE]).catch(()=>{});
  await pool.query(`DELETE FROM validator_schedule_slots WHERE id=$1`,[SLOT]).catch(()=>{});
  await pool.query(`DELETE FROM validator_content WHERE id=$1`,[CONTENT]).catch(()=>{});
  await pool.query(`DELETE FROM validator_projects WHERE id=$1`,[PID]).catch(()=>{});
}
before(async()=>{
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,'DABFix','dabfix',true,false)`,[PID]);
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'dab','approved','video',1)`,[CONTENT,PID]);
  await pool.query(`INSERT INTO validator_schedule_slots (id,project_id,slot_date,slot_position,content_id,slot_type,status,manual_publish) VALUES ($1,$2,CURRENT_DATE,10,$3,'client','filled',false)`,[SLOT,PID,CONTENT]);
  // running авто-задача на DAB_BUSY; на DAB_FREE — нет
  await pool.query(`INSERT INTO publish_tasks (id,device_serial,status) VALUES ($1,'DAB_BUSY','running')`,[PT]);
  const ins = (id,dev)=>pool.query(`INSERT INTO validator_manual_publish_queue (id,slot_id,content_id,unic_result_id,unic_task_id,project_id,account_username,platform,device_serial,planned_date,operator_status,taken_at) VALUES ($1,$2,$3,$1,$1,$4,'acc','instagram',$5,CURRENT_DATE,'in_progress',now())`,[id,SLOT,CONTENT,PID,dev]);
  await ins(ROW_BUSY,'DAB_BUSY'); await ins(ROW_FREE,'DAB_FREE');
  mpq._setPoolForTest ? mpq._setPoolForTest(pool) : null;
});
after(async()=>{ await cleanup(); await pool.end(); });

test('device_auto_busy=true когда на устройстве running publish_task', async()=>{
  const it = await mpq.getItem(pool, ROW_BUSY);
  assert.equal(it.device_auto_busy, true);
  assert.ok(it.taken_at);                 // taken_at пробрасывается
});
test('device_auto_busy=false когда авто-задач на устройстве нет', async()=>{
  const it = await mpq.getItem(pool, ROW_FREE);
  assert.equal(it.device_auto_busy, false);
});
```

> Если `getItem(pool, id)` принимает pool аргументом — `_setPoolForTest` не нужен; вызывай `mpq.getItem(pool, id)` как выше (сверь сигнатуру в `manual_publish_queue.js`).

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_mpq_device_auto_busy.test.js`
Expected: FAIL — `it.device_auto_busy` is `undefined`.

- [ ] **Step 3: Реализация**

В `manual_publish_queue.js`, в `JOINED_SELECT`: добавить `q.taken_at` в список и коррелированный подзапрос `device_auto_busy`. Заменить начало SELECT:

```javascript
const JOINED_SELECT = `
  SELECT q.id, q.slot_id, q.content_id, q.unic_result_id, q.scheme_id, q.project_id, q.project_name,
         q.pack_id, q.pack_name, q.account_username, q.platform, q.phone_number,
         q.device_serial, to_char(q.planned_date, 'YYYY-MM-DD') AS planned_date, to_char(q.created_at, 'YYYY-MM-DD') AS manual_date, q.operator_status,
         q.taken_at,
         (EXISTS (SELECT 1 FROM publish_tasks pt
                  WHERE pt.device_serial = q.device_serial
                    AND pt.status IN ('running','delegated'))) AS device_auto_busy,
         q.post_url, q.published_at, q.taken_by_id, au.username AS taken_by,
         vc.title, vc.description, vc.hashtags, vc.geo,
         vc.s3_url       AS source_video_url,
         ur.output_url   AS unic_video_url,
         s.matched_post_url, s.matched_at
  FROM validator_manual_publish_queue q
  ...остальное без изменений...
`;
```

В `rowToDict(m)` добавить два поля в возвращаемый объект:

```javascript
    planned_date: m.planned_date, manual_date: m.manual_date, operator_status: m.operator_status,
    taken_at: m.taken_at ?? null,
    device_auto_busy: m.device_auto_busy === true,
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_mpq_device_auto_busy.test.js`
Expected: PASS (2/2).

- [ ] **Step 5: Коммит**

```bash
git add manual_publish_queue.js tests/test_mpq_device_auto_busy.test.js
git commit -m "feat(mpq): device_auto_busy + taken_at в выдаче ручной очереди"
```

---

## Task 5: Чистая UI-функция `mpqIsReleasing`

**Files:**
- Modify: `public/mpq_pure.js`
- Test: `tests/test_mpq_is_releasing.test.js`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_mpq_is_releasing.test.js`:

```javascript
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mpqIsReleasing } = require('../public/mpq_pure.js');

test('releasing: agg in_progress + device_auto_busy=true', () => {
  assert.equal(mpqIsReleasing({ agg_status:'in_progress', device_auto_busy:true }), true);
});
test('не releasing: in_progress но device свободен', () => {
  assert.equal(mpqIsReleasing({ agg_status:'in_progress', device_auto_busy:false }), false);
});
test('не releasing: queued (оператор не взял) даже если device_auto_busy', () => {
  assert.equal(mpqIsReleasing({ agg_status:'queued', device_auto_busy:true }), false);
});
test('не releasing: published', () => {
  assert.equal(mpqIsReleasing({ agg_status:'published', device_auto_busy:true }), false);
});
test('защита от undefined', () => {
  assert.equal(mpqIsReleasing({}), false);
  assert.equal(mpqIsReleasing(null), false);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test tests/test_mpq_is_releasing.test.js`
Expected: FAIL — `mpqIsReleasing is not a function`.

- [ ] **Step 3: Реализация в `public/mpq_pure.js`**

Перед строкой `const api = { ... }` добавить:

```javascript
  // Релизинг: оператор взял пак (agg in_progress), но телефон ещё держит авто-задача.
  // card — { agg_status, device_auto_busy }. Только этот случай крутит спиннер.
  function mpqIsReleasing(card) {
    return !!card && card.agg_status === 'in_progress' && card.device_auto_busy === true;
  }
```

И добавить `mpqIsReleasing` в объект `api`:

```javascript
  const api = { mpqStatusVisible, mpqDiff, mpqPlatformVisible, mpqDateInRange,
                mpqCurrentWeekRange, mpqIsClaimable, mpqAgg, mpqIsReleasing };
```

(сверить с реальным списком в `api` — добавить новое имя, не убирая существующие.)

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test tests/test_mpq_is_releasing.test.js`
Expected: PASS (5/5).

- [ ] **Step 5: Коммит**

```bash
git add public/mpq_pure.js tests/test_mpq_is_releasing.test.js
git commit -m "feat(mpq-ui): чистая mpqIsReleasing — предикат состояния освобождения"
```

---

## Task 6: UI — спиннер «телефон освобождается», таймер, блок кнопок, ускорение поллинга

**Files:**
- Modify: `public/index.html` (`mpqCards` ≈12590, `mpqRowSig` ≈12707, `mpqCardComputeSig` ≈12871, рендер строки ≈12718-12726 и take-кнопки ≈12700/12924, `mpqPoll`/`mpqStartPoll` ≈13078)

Чисто DOM-обвязка вокруг `mpqIsReleasing` (логика уже покрыта Task 5). Node-тестов нет — проверка ручная в браузере. Делать аккуратно, по существующим паттернам.

- [ ] **Step 1: Прокинуть поля в карточку**

В `mpqCards()` (после `card.agg_status = mpqAgg(...)`, ≈12603) добавить:

```javascript
    card.device_auto_busy = card.rows.some(r => r.device_auto_busy === true);
    card.taken_at = card.rows.map(r => r.taken_at).filter(Boolean).sort()[0] || null;
    card.is_releasing = mpqIsReleasing(card);
```

- [ ] **Step 2: Сигнатуры reconcile — чтобы карточка перерисовалась при смене занятости**

В `mpqRowSig(card)` (≈12707) добавить `card.device_auto_busy` в массив перед `.join('|')`:

```javascript
function mpqRowSig(card) {
  return [card.unic_result_id, card.agg_status, card.taken_by, card.device_auto_busy]
    .map(v => v == null ? '' : String(v)).join('|');
}
```

В `mpqCardComputeSig(rows)` (≈12871) добавить признак занятости в сигнатуру:

```javascript
function mpqCardComputeSig(rows) {
  const busy = rows.some(r => r.device_auto_busy === true) ? '1' : '0';
  return rows.map(r => r.id + ':' + r.operator_status + ':' + (r.publication_url || '')).join('|')
       + '#' + mpqAgg(rows.map(r => r.operator_status)) + '#' + busy;
}
```

- [ ] **Step 3: Рендер релизинг-состояния в строке таблицы**

В рендере строки (ячейка статуса ≈12726) — если `card.is_releasing`, показать спиннер+таймер вместо обычного бейджа. Заменить содержимое `mpq-col-status`:

```javascript
    <td class="px-2 py-1.5 mpq-col-status">${
      card.is_releasing
        ? `<span class="inline-flex items-center gap-1 text-amber-700" data-mpq-releasing="${card.unic_result_id}" data-taken-at="${card.taken_at || ''}">
             <svg class="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/></svg>
             Телефон освобождается… <span class="mpq-rel-sec">${mpqReleasingSec(card.taken_at)}</span> сек
           </span>`
        : `${esc(MPQ_STATUS[card.agg_status] || card.agg_status)}${taker}`
    }</td>
```

Добавить хелпер рядом с рендером:

```javascript
function mpqReleasingSec(takenAt) {
  if (!takenAt) return 0;
  return Math.max(0, Math.round((Date.now() - new Date(takenAt).getTime()) / 1000));
}
```

- [ ] **Step 4: Блокировка кнопок платформ при релизинге**

Take-кнопка показывается для `mpqIsClaimable`. После взятия пак становится `in_progress` → показываются действия платформы (Выложить/На доработку). Обернуть их рендер: если `card.is_releasing` — рисовать `disabled`-кнопки с подсказкой. Найти, где рендерятся `mpqPublishPlatform`/`mpqReworkPlatform`-кнопки в карточке (≈12900-12940), и для релизинга заменить на:

```javascript
    card.is_releasing
      ? `<button disabled class="px-3 py-1.5 rounded bg-gray-200 text-gray-400 text-sm cursor-not-allowed" title="Телефон ещё занят автовыкладкой — идёт остановка">⏳ Освобождается…</button>`
      : `…существующие активные кнопки…`
```

- [ ] **Step 5: Тикающий таймер + ускорение поллинга**

Добавить лёгкий 1-сек тик, обновляющий только секунды (без полного ре-рендера), и ускорять поллинг до 2с пока есть релизинг-карточки. В `mpqStartPoll()` (≈13088) сделать интервал динамическим:

```javascript
let mpqPollTimer = null, mpqRelTimer = null;
function mpqHasReleasing() {
  return (mpqRows || []).some(r => r.device_auto_busy === true && r.operator_status === 'in_progress');
}
function mpqStartPoll() {
  const ms = mpqHasReleasing() ? 2000 : (window.MPQ_POLL_MS || 5000);
  if (mpqPollTimer) clearInterval(mpqPollTimer);
  mpqPollTimer = setInterval(mpqPoll, ms);
  // тикаем секунды в открытых релизинг-бейджах
  if (!mpqRelTimer) mpqRelTimer = setInterval(() => {
    document.querySelectorAll('[data-mpq-releasing]').forEach(el => {
      const t = el.getAttribute('data-taken-at');
      const s = el.querySelector('.mpq-rel-sec');
      if (s) s.textContent = mpqReleasingSec(t);
    });
  }, 1000);
}
```

В конце `mpqPoll()` (после обновления `mpqRows`) переустанавливать интервал, если изменилось наличие релизинга:

```javascript
  mpqStartPoll();   // подстроить частоту (2с при релизинге, иначе 5с)
```

(Убедиться, что `mpqStartPoll` идемпотентен — он чистит старый таймер выше.)

- [ ] **Step 6: Ручная проверка**

Невозможно юнитом — проверка в браузере на тест-стенде (или зафиксировать для verify после деплоя):
1. Взять пак на телефоне с бегущей авто → карточка показывает спиннер «Телефон освобождается… NN сек», секунды тикают, кнопки платформ disabled.
2. Через несколько секунд (процесс убит, `device_auto_busy=false`) → бейдж «В работе», кнопки активны.
3. Взять пак на свободном телефоне → сразу «В работе», без спиннера.

- [ ] **Step 7: Коммит**

```bash
git add public/index.html
git commit -m "feat(mpq-ui): спиннер освобождения телефона + таймер + блок кнопок + ускоренный поллинг"
```

---

## Task 7: Полный прогон, ревью, деплой

**Files:** —

- [ ] **Step 1: Прогнать весь релевантный набор тестов**

Run:
```bash
node --test --test-force-exit tests/test_preempt_for_device.test.js tests/test_mpq_device_auto_busy.test.js tests/test_mpq_is_releasing.test.js tests/test_manual_inprogress_blocks_dispatch.test.js
```
Expected: все PASS, 0 fail. (Включён dispatch-набор как регрессия — мы трогали server.js/scheduler.js/mpq.)

- [ ] **Step 2: Синтаксис**

Run: `node -c scheduler.js && node -c server.js && node -c manual_publish_queue.js && echo OK`
Expected: `OK`.

- [ ] **Step 3: codex review**

Run: `~/.local/bin/codex review --commit HEAD -c sandbox_mode=danger-full-access` (или `--base origin/main` для всей ветки). Исправить P1/P2 инлайн, перекоммитить, перепрогнать тесты.

- [ ] **Step 4: Проверить publisher.py на SIGTERM**

Глянуть `publisher.py` — корректно ли завершается по SIGTERM (освобождает ADB/чистит артефакты). Если нет обработчика — SIGKILL-фоллбек (через grace) гарантирует освобождение телефона; задокументировать в evidence.

- [ ] **Step 5: PR + merge + deploy**

```bash
git push -u origin feat/manual-take-preempt-auto
# gh pr create --repo GenGo2/delivery-contenthunter --base main ... (токен ~/secrets/github-gengo2.env: GITHUB_TOKEN_GENGO2)
# после merge:
cd /root/.openclaw/workspace-genri/autowarm && git pull --ff-only origin main
sudo pm2 restart 35
```
Без миграций БД. Kill-switch `MANUAL_TAKE_PREEMPT_AUTO_ENABLED` default ON; `=false` для отката.

- [ ] **Step 6: Очистка worktree**

```bash
cd /home/claude-user/autowarm-testbench
rm -f /home/claude-user/autowarm-testbench-preempt/node_modules
git worktree remove /home/claude-user/autowarm-testbench-preempt --force
```

- [ ] **Step 7: Verify (через сутки)**

Повторить замер коллизий из спеки: медиана ожидания должна упасть к ~секундам; проверить отсутствие двойных публикаций (`error_class='preempted_by_manual'` есть, дублей post_url нет) и брошенных requeue-задач.

---

## Self-Review (выполнено автором плана)

- **Покрытие спеки:** (A) вытеснение → Task 1-2; (B) триггер в take → Task 3; (C) `device_auto_busy` → Task 4; UI спиннер/таймер/блок/поллинг → Task 5-6; kill-switch → Task 2; same-content cancel + анти-двойная-публикация (вкл. пометку publish_queue) → Task 1-2; best-effort на неубиваемые → Task 2 (running-Map only); тесты → каждый backend-таск; деплой/verify → Task 7. ✓
- **Плейсхолдеры:** нет TBD/«добавить обработку» — код приведён в каждом шаге. ✓
- **Согласованность типов:** `preemptForDevice(deviceSerial, claimedUnicResultId)` → возвращает `{killed,skipped}`; `_preemptFate(taskId, claimedUnicResultId)` → `'cancel'|'requeue'`; `pickPreemptArgs(items)` → `{deviceSerial,unicResultId}|null`; `mpqIsReleasing(card{agg_status,device_auto_busy})` → bool. Имена согласованы между задачами. ✓
- **Риск-замечания для исполнителя:** (1) сверить точные номера строк в `server.js`/`index.html` — файлы большие, ориентируйся по именам функций; (2) сверить реальный тест-экспорт `server.js` перед добавлением `pickPreemptArgs`; (3) `getItem` сигнатура — pool аргументом (тогда `_setPoolForTest` для mpq не нужен).
