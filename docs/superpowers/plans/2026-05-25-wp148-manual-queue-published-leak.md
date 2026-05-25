# WP #148 — Manual-queue published-leak: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ручная очередь (`validator_manual_publish_queue`) должна содержать только комбинации аккаунт×платформа, которые НЕ вышли автоматически; уже опубликованное (`publish_queue.status='done'`) туда не попадает.

**Architecture:** Два пути залива в ручную очередь чинятся отдельно. (A) retry-handoff (`retry_controller.js`) становится per-account: вместо флипа всего слота в `manual_publish` он заливает в ручную очередь только упавшую строку. (B) Populator (`manual_queue_assign.js`) исключает аккаунты с уже-`done` авто-публикацией. Общий INSERT выносится в хелпер `enqueueManualRow`. Плюс one-off зачистка 174 уже-накопленных дублей.

**Tech Stack:** Node.js (CommonJS), `pg` Pool, `node:test` (live-DB против `openclaw:openclaw123@localhost:5432`), PostgreSQL.

**Спека:** `docs/superpowers/specs/2026-05-25-wp148-manual-queue-published-leak-design.md`

**Репозиторий кода:** autowarm — рабочая копия `/home/claude-user/autowarm-testbench/` (тут разработка и `node --test`). Прод: `/root/.openclaw/workspace-genri/autowarm/` (деплой через `git pull` + `pm2 restart`, см. Task 6). Все пути ниже — относительно `/home/claude-user/autowarm-testbench/`.

---

## File Structure

- `manual_queue_assign.js` — **модифицируем**: (1) добавляем экспортируемый хелпер `enqueueManualRow(db, row)` (единый INSERT в ручную очередь с `ON CONFLICT`); (2) populator переиспользует хелпер; (3) per-account фильтр «исключать done» под kill-switch `MANUAL_QUEUE_EXCLUDE_PUBLISHED`.
- `retry_controller.js` — **модифицируем**: `handoffToManual` становится per-account (gather-запрос + `enqueueManualRow`, без флипа `slot.manual_publish`) под kill-switch `RETRY_HANDOFF_PER_ACCOUNT`; ветка-легаси сохраняет старое поведение при выключенном флаге.
- `cleanup_wp148_manual_queue_dups.js` — **создаём**: one-off идемпотентный скрипт ретро-зачистки `queued`-дублей.
- `test_retry_controller.test.js` — **модифицируем**: переписать тест handoff под per-account, добавить idempotency + kill-switch.
- `test_manual_queue_assign_live.test.js` — **создаём** (root, live-DB; имя с `_live` чтобы не конфликтовать с пре-существующим `tests/test_manual_queue_assign.test.js`): тесты хелпера + exclude-done + kill-switch.
- `tests/test_manual_queue_assign.test.js` — **модифицируем** (Task 2): пре-существующий mock-тест populator'а; добавить ветку `FROM publish_queue` в `makePool` под новый `isAlreadyPublished`. Запускается через `npm test`.
- `test_cleanup_wp148.test.js` — **создаём**: тест зачистки (только queued-дубли).

> **Перед стартом:** убедиться, что мы в рабочей копии и БД доступна:
> ```bash
> cd /home/claude-user/autowarm-testbench && git fetch origin --quiet && git status -sb
> PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -X -c "SELECT 1"
> ```
> Реализацию вести в отдельной ветке autowarm (не в общем рабочем дереве, чтобы не мешать параллельным сессиям):
> ```bash
> git checkout -b wp148-manual-queue-published-leak
> ```

---

## Task 1: Хелпер `enqueueManualRow` + рефактор populator (без изменения поведения)

**Files:**
- Modify: `manual_queue_assign.js`
- Test: `test_manual_queue_assign_live.test.js` (создаётся в этой задаче)

Цель: вынести INSERT в ручную очередь в один хелпер и переключить populator на него. Поведение не меняется — это подготовка к Task 2/3 (DRY).

- [ ] **Step 1: Написать падающий тест на хелпер**

Создать `test_manual_queue_assign_live.test.js`:

```js
// Run: node --test --test-force-exit test_manual_queue_assign_live.test.js
const { test, before, after, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { enqueueManualRow } = require('./manual_queue_assign');
const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

// Изолированные тестовые id (диапазон 99148xxx, чтобы не задеть прод-строки).
const PID=9914800, CONTENT=9914800, SLOT=9914800, TASK=9914800, RESULT=9914800;

async function cleanup(){
  await pool.query('DELETE FROM validator_manual_publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1',[TASK]).catch(()=>{});
  await pool.query('DELETE FROM validator_schedule_slots WHERE id=$1',[SLOT]).catch(()=>{});
  await pool.query('DELETE FROM validator_content WHERE id=$1',[CONTENT]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1',[PID]).catch(()=>{});
}
function row(over={}){
  return Object.assign({
    slot_id:SLOT, content_id:CONTENT, unic_result_id:RESULT, unic_task_id:TASK,
    scheme_id:null, project_id:PID, project_name:'WP148', pack_id:null, pack_name:null,
    account_id:null, account_username:'acc1', platform:'instagram',
    device_serial:null, raspberry_number:null, phone_number:null,
    planned_date:'2026-05-25',
  }, over);
}
before(async()=>{ await cleanup();
  // slot_id у ручной очереди имеет FK → validator_schedule_slots; сидим проект+контент+слот.
  await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,'WP148','wp148',true,false)`,[PID]);
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'wp148','approved','video',1)`,[CONTENT,PID]);
  await pool.query(`INSERT INTO validator_schedule_slots (id,project_id,slot_date,slot_position,content_id,slot_type,status,manual_publish) VALUES ($1,$2,'2026-05-25',1,$3,'client','filled',false)`,[SLOT,PID,CONTENT]);
});
after(async()=>{ await cleanup(); await pool.end(); });
beforeEach(async()=>{ await pool.query('DELETE FROM validator_manual_publish_queue WHERE unic_result_id=$1',[RESULT]); });

test('enqueueManualRow вставляет строку и возвращает id', async()=>{
  const id = await enqueueManualRow(pool, row());
  assert.ok(id, 'должен вернуть id');
  const { rows } = await pool.query(
    `SELECT operator_status, account_username, platform FROM validator_manual_publish_queue WHERE id=$1`,[id]);
  assert.equal(rows[0].operator_status, 'queued');
  assert.equal(rows[0].account_username, 'acc1');
});

test('enqueueManualRow идемпотентен по (unic_result_id, account, platform)', async()=>{
  await enqueueManualRow(pool, row());
  const id2 = await enqueueManualRow(pool, row());     // тот же ключ
  assert.equal(id2, null, 'повтор не должен вставлять (ON CONFLICT DO NOTHING)');
  const { rows } = await pool.query(
    `SELECT count(*)::int n FROM validator_manual_publish_queue WHERE unic_result_id=$1 AND cancelled_at IS NULL`,[RESULT]);
  assert.equal(rows[0].n, 1);
});
```

- [ ] **Step 2: Прогнать тест — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test --test-force-exit test_manual_queue_assign_live.test.js`
Expected: FAIL — `enqueueManualRow is not a function` (хелпер ещё не экспортирован).

- [ ] **Step 3: Добавить хелпер и переключить populator на него**

В `manual_queue_assign.js` добавить функцию (после `batchSize()`):

```js
// Единый INSERT в ручную очередь (DRY: populator + retry-handoff). Идемпотентен
// по уникальному partial-индексу uq_manual_pub_result_account.
async function enqueueManualRow(db, row) {
  const r = await db.query(`
    INSERT INTO validator_manual_publish_queue
      (slot_id, content_id, unic_result_id, unic_task_id, scheme_id, project_id,
       project_name, pack_id, pack_name, account_id, account_username, platform,
       device_serial, raspberry_number, phone_number, planned_date, operator_status)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'queued')
    ON CONFLICT (unic_result_id, account_username, platform)
      WHERE cancelled_at IS NULL DO NOTHING
    RETURNING id
  `, [
    row.slot_id, row.content_id, row.unic_result_id, row.unic_task_id, row.scheme_id,
    row.project_id, row.project_name, row.pack_id, row.pack_name, row.account_id,
    row.account_username, row.platform, row.device_serial, row.raspberry_number,
    row.phone_number, row.planned_date,
  ]);
  return r.rows[0] ? r.rows[0].id : null;
}
```

Затем заменить inline-INSERT в `assignManualPublishQueue` (текущие строки ~63-76, блок `await pool.query(\`INSERT INTO validator_manual_publish_queue ...\`, [...])` и следующий за ним `log.log('[manual-queue] ✅ ...')`) на вызов хелпера:

```js
          const insertedId = await enqueueManualRow(pool, {
            slot_id: res.slot_id, content_id: res.content_id, unic_result_id: res.result_id,
            unic_task_id: res.task_id, scheme_id: res.scheme_id, project_id: res.project_id,
            project_name: res.project_name, pack_id: device.pack_id, pack_name: device.pack_name,
            account_id: acc.id, account_username: acc.username, platform: acc.platform,
            device_serial: device.device_serial, raspberry_number: device.raspberry,
            phone_number: device.phone_number, planned_date: res.planned_date,
          });
          if (insertedId)
            log.log(`[manual-queue] ✅ result=${res.result_id} → @${acc.username} (${acc.platform}) phone=${device.phone_number}`);
```

> Примечание: существующий ручной dup-check (строки ~53-62) можно оставить — он безвреден, `ON CONFLICT` тоже защищает. Не удалять в этой задаче.

Обновить экспорт в конце файла:

```js
module.exports = { assignManualPublishQueue, enqueueManualRow, isEnabled, batchSize };
```

- [ ] **Step 4: Прогнать тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_manual_queue_assign_live.test.js`
Expected: PASS (2 теста).

- [ ] **Step 5: Прогнать смежные тесты — нет регрессий**

Run: `node --test --test-force-exit test_client_manual_publish.test.js test_client_manual_filter.test.js`
Expected: PASS (поведение populator не изменилось).

- [ ] **Step 6: Commit**

```bash
git add manual_queue_assign.js test_manual_queue_assign_live.test.js
git commit -m "refactor(wp148): extract enqueueManualRow helper, populator reuses it"
```

---

## Task 2: `manual_queue_assign` — исключать уже опубликованное (`done`)

**Files:**
- Modify: `manual_queue_assign.js`
- Test: `test_manual_queue_assign_live.test.js`

- [ ] **Step 1: Написать падающий тест на exclude-done**

Добавить в `test_manual_queue_assign_live.test.js` (внутри файла из Task 1) хелпер для проверки фильтра напрямую. Чтобы не поднимать весь pack/device-резолвинг, тестируем приватную проверку через публичную функцию `isAlreadyPublished` (её добавим в Task 2 Step 3).

```js
const { isAlreadyPublished } = require('./manual_queue_assign');

test('isAlreadyPublished=true когда есть done в publish_queue по (result,account,platform)', async()=>{
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'wp148','approved','video',1) ON CONFLICT (id) DO NOTHING`,[CONTENT,PID]);
  await pool.query(`INSERT INTO unic_tasks (id,content_id,project_id,slot_date,current_status,meta) VALUES ($1,$2,$3,'2026-05-25','done',jsonb_build_object('slot_id',$4::text)) ON CONFLICT (id) DO NOTHING`,[TASK,CONTENT,PID,SLOT]);
  await pool.query(`INSERT INTO unic_results (id,task_id,scheme_id,output_url,status,created_at) VALUES ($1,$2,NULL,'https://x/y.mp4','done',now()) ON CONFLICT (id) DO NOTHING`,[RESULT,TASK]);
  await pool.query(`INSERT INTO publish_queue (unic_result_id,unic_task_id,project_id,account_username,platform,media_url,scheduled_at,status)
                    VALUES ($1,$2,$3,'PUBacc','youtube','https://x/y.mp4',NOW(),'done')`,[RESULT,TASK,PID]);

  assert.equal(await isAlreadyPublished(pool, RESULT, 'PUBacc', 'youtube'), true);
  assert.equal(await isAlreadyPublished(pool, RESULT, 'PUBacc', 'instagram'), false, 'другая платформа — не done');
  assert.equal(await isAlreadyPublished(pool, RESULT, 'OTHER', 'youtube'), false, 'другой аккаунт — не done');

  await pool.query(`DELETE FROM publish_queue WHERE unic_result_id=$1`,[RESULT]);
});

test('kill-switch MANUAL_QUEUE_EXCLUDE_PUBLISHED=false → isAlreadyPublished всегда false', async()=>{
  process.env.MANUAL_QUEUE_EXCLUDE_PUBLISHED='false';
  await pool.query(`INSERT INTO publish_queue (unic_result_id,unic_task_id,project_id,account_username,platform,media_url,scheduled_at,status)
                    VALUES ($1,$2,$3,'PUBacc','youtube','https://x/y.mp4',NOW(),'done')`,[RESULT,TASK,PID]);
  const res = await isAlreadyPublished(pool, RESULT, 'PUBacc', 'youtube');
  delete process.env.MANUAL_QUEUE_EXCLUDE_PUBLISHED;
  await pool.query(`DELETE FROM publish_queue WHERE unic_result_id=$1`,[RESULT]);
  assert.equal(res, false);
});
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `node --test --test-force-exit test_manual_queue_assign_live.test.js`
Expected: FAIL — `isAlreadyPublished is not a function`.

- [ ] **Step 3: Реализовать `isAlreadyPublished` и вызвать её в populator-цикле**

В `manual_queue_assign.js` добавить:

```js
function excludePublishedEnabled() {
  return process.env.MANUAL_QUEUE_EXCLUDE_PUBLISHED !== 'false';
}

// WP #148: аккаунт×платформа уже успешно вышел автоматом? Тогда в ручную не льём.
async function isAlreadyPublished(db, unicResultId, accountUsername, platform) {
  if (!excludePublishedEnabled()) return false;
  const { rows } = await db.query(`
    SELECT 1 FROM publish_queue
    WHERE unic_result_id = $1
      AND LOWER(account_username) = LOWER($2)
      AND LOWER(platform) = LOWER($3)
      AND status = 'done'
    LIMIT 1
  `, [unicResultId, accountUsername, platform]);
  return rows.length > 0;
}
```

В цикле `for (const acc of accounts)` (после dup-check, перед вызовом `enqueueManualRow` из Task 1) добавить:

```js
          if (await isAlreadyPublished(pool, res.result_id, acc.username, acc.platform)) {
            log.log(`[manual-queue] content=${res.content_id} @${acc.username} (${acc.platform}) уже опубликован автоматом, пропуск (WP#148)`);
            continue;
          }
```

Обновить экспорт:

```js
module.exports = { assignManualPublishQueue, enqueueManualRow, isAlreadyPublished, isEnabled, batchSize };
```

- [ ] **Step 4: Прогнать live-тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_manual_queue_assign_live.test.js`
Expected: PASS (4 теста).

- [ ] **Step 5: Починить пре-существующий mock-тест `tests/test_manual_queue_assign.test.js`**

> **Важно (поймано на ревью Task 1):** есть git-трекнутый mock-тест `tests/test_manual_queue_assign.test.js`. Его `makePool.query` бросает `unexpected SQL` на любой незнакомый запрос. Новый `isAlreadyPublished` шлёт `SELECT 1 FROM publish_queue ... status='done'` ВНУТРИ populator-цикла (`assignManualPublishQueue`), поэтому без ветки в mock тест упадёт. Это запускается через `npm test` (`node --test tests/*.test.js`) — обязательно держать зелёным.

В `tests/test_manual_queue_assign.test.js`, в функции `makePool` внутри `query`, добавить ветку для нового SELECT **перед** веткой `INSERT INTO validator_manual_publish_queue` (иначе `/validator_manual_publish_queue/` тоже матчит — но `publish_queue` ≠ `validator_manual_publish_queue`, так что порядок не критичен; всё равно добавить явно). Дефолт — «не опубликовано», чтобы существующие assertions (`inserts.length === 2`) сохранились:

```js
      if (/FROM publish_queue/.test(sql)) return { rows: [] };  // WP#148: isAlreadyPublished — по умолчанию не опубликовано
```

Заодно повысить достоверность mock INSERT (он сейчас возвращает `{ rows: [] }`, из-за чего `enqueueManualRow` думает, что был конфликт): вернуть синтетический id, чтобы success-лог populator'а тоже отрабатывал в mock:

```js
      if (/INSERT INTO validator_manual_publish_queue/.test(sql)) { inserts.push(params); return { rows: [{ id: 1 }] }; }
```

Прогнать mock-тест:
Run: `node --test --test-force-exit tests/test_manual_queue_assign.test.js`
Expected: PASS (4 теста) — `inserts.length === 2` сохраняется (done-ветка вернула `[]` → не исключаем).

- [ ] **Step 6: Commit**

```bash
git add manual_queue_assign.js test_manual_queue_assign_live.test.js tests/test_manual_queue_assign.test.js
git commit -m "fix(wp148): manual-queue populator skips already auto-published accounts (kill-switch MANUAL_QUEUE_EXCLUDE_PUBLISHED)"
```

---

## Task 3: `retry_controller.handoffToManual` — per-account вместо флипа слота

**Files:**
- Modify: `retry_controller.js`
- Test: `test_retry_controller.test.js`

- [ ] **Step 1: Обновить seed/cleanup и переписать тест handoff под per-account**

В `test_retry_controller.test.js`:

(а) В функции `cleanup()` добавить первой строкой удаление строк ручной очереди:

```js
  await pool.query('DELETE FROM validator_manual_publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
```

(б) Заменить тест `'banned → handoff: ...'` (целиком) на:

```js
test('banned → handoff per-account: слот НЕ помечен manual, упавший аккаунт в ручной очереди, очередь погашена', async()=>{
  await seedFailed('account_banned','banned');
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00'), onlyClientPublishId: CPID });

  const q = (await pool.query('SELECT status, manual_handoff_at FROM publish_queue WHERE id=$1',[PQ])).rows[0];
  const s = (await pool.query('SELECT manual_publish FROM validator_schedule_slots WHERE id=$1',[SLOT])).rows[0];
  const mq = (await pool.query(
    `SELECT operator_status, account_username, platform FROM validator_manual_publish_queue
     WHERE unic_result_id=$1 AND cancelled_at IS NULL`,[RESULT])).rows;

  assert.ok(['cancelled','skipped'].includes(q.status), 'строка очереди погашена');
  assert.ok(q.manual_handoff_at, 'manual_handoff_at выставлен');
  assert.equal(s.manual_publish, false, 'слот НЕ флипается (per-account)');
  assert.equal(mq.length, 1, 'ровно одна строка в ручной очереди');
  assert.equal(mq[0].account_username, 'acc');
  assert.equal(mq[0].platform, 'instagram');
  assert.equal(mq[0].operator_status, 'queued');
});

test('handoff per-account идемпотентен: повторный tick не создаёт дубль', async()=>{
  await seedFailed('account_banned','banned');
  const opts = { nowMsk: new Date('2026-05-21T08:00:00+03:00'), onlyClientPublishId: CPID };
  await retryFailedPublishes(pool, opts);
  // вернуть строку в failed, чтобы tick снова попытался handoff
  await pool.query(`UPDATE publish_queue SET status='failed', manual_handoff_at=NULL WHERE id=$1`,[PQ]);
  await retryFailedPublishes(pool, opts);
  const n = (await pool.query(
    `SELECT count(*)::int c FROM validator_manual_publish_queue WHERE unic_result_id=$1 AND cancelled_at IS NULL`,[RESULT])).rows[0].c;
  assert.equal(n, 1);
});

test('kill-switch RETRY_HANDOFF_PER_ACCOUNT=false → старое поведение (флип слота)', async()=>{
  await seedFailed('account_banned','banned');
  process.env.RETRY_HANDOFF_PER_ACCOUNT='false';
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00'), onlyClientPublishId: CPID });
  delete process.env.RETRY_HANDOFF_PER_ACCOUNT;
  const s = (await pool.query('SELECT manual_publish FROM validator_schedule_slots WHERE id=$1',[SLOT])).rows[0];
  const n = (await pool.query(
    `SELECT count(*)::int c FROM validator_manual_publish_queue WHERE unic_result_id=$1 AND cancelled_at IS NULL`,[RESULT])).rows[0].c;
  assert.equal(s.manual_publish, true, 'легаси: слот флипается');
  assert.equal(n, 0, 'легаси: в ручную напрямую не льём');
});
```

> Важно: `seedFailed` вставляет `publish_queue` без `pack_id` — это ок. Gather-запрос (Step 3) берёт `slot_id/content_id/planned_date` из слота (они NOT NULL и засидены), `pack_id/phone_number/account_id` останутся NULL (nullable). Строка ручной очереди всё равно валидна.

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test --test-force-exit test_retry_controller.test.js`
Expected: FAIL — тест per-account: `s.manual_publish` всё ещё `true` и строки в ручной очереди нет (старая реализация флипает слот).

- [ ] **Step 3: Переписать `handoffToManual` на per-account**

В `retry_controller.js`:

(а) В начало файла добавить импорт хелпера:

```js
const { enqueueManualRow } = require('./manual_queue_assign');
```

(б) Заменить функцию `handoffToManual` (целиком, текущие строки ~95-128) на:

```js
/** Передать упавшую публикацию в ручную. По умолчанию per-account (WP #148):
 *  заливаем в ручную очередь ТОЛЬКО эту строку (account×platform), слот НЕ флипаем —
 *  остальные аккаунты пака продолжают авто-выкладку. Kill-switch
 *  RETRY_HANDOFF_PER_ACCOUNT=false возвращает старое поведение (флип всего слота). */
async function handoffToManual(pool, r, reason) {
  const perAccount = process.env.RETRY_HANDOFF_PER_ACCOUNT !== 'false';
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    // Guard от гонок: захватываем строку и подтверждаем, что она ВСЁ ЕЩЁ failed без handoff.
    const guard = await client.query(
      `SELECT id FROM publish_queue
       WHERE id=$1 AND status='failed' AND manual_handoff_at IS NULL
       FOR UPDATE`, [r.pq_id]);
    if (guard.rowCount === 0) {
      await client.query('ROLLBACK');
      console.log(`[retry-controller] skip handoff pq#${r.pq_id} — строка изменилась под нами`);
      return;
    }

    if (perAccount) {
      // Собрать всё нужное для строки ручной очереди по одной строке publish_queue.
      const g = await client.query(`
        SELECT pq.unic_result_id, pq.unic_task_id, pq.project_id,
               pq.account_username, pq.platform,
               pq.pack_id, pq.pack_name, pq.device_serial, pq.raspberry_number,
               (ut.meta->>'slot_id')::int AS slot_id,
               s.content_id, s.slot_date AS planned_date,
               p.project AS project_name,
               ur.scheme_id,
               ia.id AS account_id,
               fdn.device_number AS phone_number
        FROM publish_queue pq
        JOIN unic_tasks ut ON ut.id = pq.unic_task_id
        LEFT JOIN validator_schedule_slots s ON s.id = (ut.meta->>'slot_id')::int
        LEFT JOIN validator_projects p ON p.id = pq.project_id
        LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
        LEFT JOIN factory_pack_accounts fpa ON fpa.id = pq.pack_id
        LEFT JOIN factory_device_numbers fdn ON fdn.id = fpa.device_num_id
        LEFT JOIN factory_inst_accounts ia ON ia.pack_id = pq.pack_id
             AND LOWER(ia.username) = LOWER(pq.account_username)
             AND LOWER(ia.platform) = LOWER(pq.platform)
        WHERE pq.id = $1
      `, [r.pq_id]);
      const row = g.rows[0];
      // NOT NULL ручной очереди: slot_id, content_id, planned_date обязательны.
      if (row && row.slot_id && row.content_id && row.planned_date) {
        await enqueueManualRow(client, {
          slot_id: row.slot_id, content_id: row.content_id, unic_result_id: row.unic_result_id,
          unic_task_id: row.unic_task_id, scheme_id: row.scheme_id, project_id: row.project_id,
          project_name: row.project_name, pack_id: row.pack_id, pack_name: row.pack_name,
          account_id: row.account_id, account_username: row.account_username, platform: row.platform,
          device_serial: row.device_serial, raspberry_number: row.raspberry_number,
          phone_number: row.phone_number, planned_date: row.planned_date,
        });
      } else {
        console.warn(`[retry-controller] handoff pq#${r.pq_id}: нет slot_id/content_id — строка не залита в ручную (legacy)`);
      }
    } else {
      // Легаси: флип всего слота в manual (kill-switch).
      const slot = await client.query(
        `SELECT (ut.meta->>'slot_id')::int AS slot_id FROM unic_tasks ut WHERE ut.id=$1`, [r.unic_task_id]);
      const slotId = slot.rows[0] && slot.rows[0].slot_id;
      if (slotId) {
        await client.query(
          `UPDATE validator_schedule_slots
           SET manual_publish=true, manual_publish_set_at=now()
           WHERE id=$1 AND manual_publish=false`, [slotId]);
      }
    }

    await client.query(
      `UPDATE publish_queue SET status='cancelled', skip_reason=$2, manual_handoff_at=now(), updated_at=NOW() WHERE id=$1`,
      [r.pq_id, `retry_handoff:${reason}`]);
    await client.query('COMMIT');
    console.log(`[retry-controller] handoff pq#${r.pq_id} (${reason}, per_account=${perAccount})`);
  } catch (e) {
    await client.query('ROLLBACK');
    console.error(`[retry-controller] handoff error pq#${r.pq_id}: ${e.message}`);
  } finally { client.release(); }
}
```

> `enqueueManualRow(client, ...)` принимает транзакционный `client` (тот же тип API `.query`, что и Pool) — вставка идёт внутри той же транзакции, что и гашение очереди. `require('./manual_queue_assign')` цикла не создаёт (manual_queue_assign не требует retry_controller).

> **No-silent-drop (доводка по финальному codex, реализовано):** введён флаг `didHandoff`. Если per-account ветка НЕ смогла залить в ручную (нет `slot_id/content_id/planned_date`), строка `publish_queue` **НЕ гасится** — `ROLLBACK`, строка остаётся `failed` (видна/повторяема), вместо молчаливой потери упавшей публикации. Гашение (`status='cancelled'`+`manual_handoff_at`) выполняется только при успешной передаче (per-account enqueue или legacy флип). Покрыто тестом «нет slot_id в meta → строка остаётся failed».

- [ ] **Step 4: Прогнать — убедиться, что проходит**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: PASS (исходные requeue/kill-switch/race тесты + 3 новых per-account теста).

- [ ] **Step 5: Прогнать смежные тесты**

Run: `node --test --test-force-exit test_retry_decision.test.js test_dispatch_manual_guard.test.js test_manual_queue_assign_live.test.js`
Expected: PASS (decision-логика и dispatch-guard не менялись; manual_queue_assign из Task 1/2 цел).

- [ ] **Step 6: Commit**

```bash
git add retry_controller.js test_retry_controller.test.js
git commit -m "fix(wp148): retry handoff is per-account, no longer flips whole slot to manual (kill-switch RETRY_HANDOFF_PER_ACCOUNT)"
```

---

## Task 4: One-off скрипт ретро-зачистки 174 `queued`-дублей

**Files:**
- Create: `cleanup_wp148_manual_queue_dups.js`
- Test: `test_cleanup_wp148.test.js`

> **Реализовано с test-изоляцией:** `cleanupPublishedDups(pool, { dryRun, onlyResultId })`. `onlyResultId` (по умолчанию `null` → ГЛОБАЛЬНО, как и нужно для прод-запуска) добавляет фильтр `q.unic_result_id = $1`, чтобы live-DB тесты не мутировали прод-строки (зеркало `retry_controller.onlyClientPublishId`). CLI-путь (`--apply`) — всегда глобальный. `TARGET_SQL` вынесен в `targetSql(scoped)`-функцию, параметр прокинут и в COUNT, и в UPDATE-подзапрос.

- [ ] **Step 1: Написать падающий тест**

Создать `test_cleanup_wp148.test.js`:

```js
// Run: node --test --test-force-exit test_cleanup_wp148.test.js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { cleanupPublishedDups } = require('./cleanup_wp148_manual_queue_dups');
const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

const PID=9914810, CONTENT=9914810, SLOT=9914810, TASK=9914810, RESULT=9914810;

async function cleanup(){
  await pool.query('DELETE FROM validator_manual_publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1',[TASK]).catch(()=>{});
  await pool.query('DELETE FROM validator_schedule_slots WHERE id=$1',[SLOT]).catch(()=>{});
  await pool.query('DELETE FROM validator_content WHERE id=$1',[CONTENT]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1',[PID]).catch(()=>{});
}
async function mqRow(account, platform, status){
  await pool.query(`INSERT INTO validator_manual_publish_queue
    (slot_id,content_id,unic_result_id,unic_task_id,project_id,account_username,platform,planned_date,operator_status)
    VALUES ($1,$2,$3,$4,$5,$6,$7,'2026-05-25',$8)`,[SLOT,CONTENT,RESULT,TASK,PID,account,platform,status]);
}
async function doneInQueue(account, platform){
  await pool.query(`INSERT INTO publish_queue (unic_result_id,unic_task_id,project_id,account_username,platform,media_url,scheduled_at,status)
    VALUES ($1,$2,$3,$4,$5,'https://x/y.mp4',NOW(),'done')`,[RESULT,TASK,PID,account,platform]);
}
before(async()=>{ await cleanup();
  // slot_id FK → validator_schedule_slots; сидим проект+контент+слот.
  await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,'WP148c','wp148c',true,false)`,[PID]);
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'wp148c','approved','video',1)`,[CONTENT,PID]);
  await pool.query(`INSERT INTO validator_schedule_slots (id,project_id,slot_date,slot_position,content_id,slot_type,status,manual_publish) VALUES ($1,$2,'2026-05-25',1,$3,'client','filled',false)`,[SLOT,PID,CONTENT]);
  // task/result — для переносимости (в нашей БД у publish_queue FK нет, но сидим для надёжности)
  await pool.query(`INSERT INTO unic_tasks (id,content_id,project_id,slot_date,current_status,meta) VALUES ($1,$2,$3,'2026-05-25','done',jsonb_build_object('slot_id',$4::text))`,[TASK,CONTENT,PID,SLOT]);
  await pool.query(`INSERT INTO unic_results (id,task_id,scheme_id,output_url,status,created_at) VALUES ($1,$2,NULL,'https://x/y.mp4','done',now())`,[RESULT,TASK]);
});
after(async()=>{ await cleanup(); await pool.end(); });

test('зачистка отменяет только queued-дубли done; published и не-дубли не трогает', async()=>{
  await mqRow('q_dup','instagram','queued');   await doneInQueue('q_dup','instagram');   // → отменить
  await mqRow('p_dup','tiktok','published');    await doneInQueue('p_dup','tiktok');       // published — не трогать
  await mqRow('q_nodup','youtube','queued');                                             // нет done — не трогать

  const res = await cleanupPublishedDups(pool, { dryRun:false });
  assert.equal(res.cancelled, 1, 'отменена ровно 1 строка');

  const q = async(a,p)=> (await pool.query(
    `SELECT cancelled_at FROM validator_manual_publish_queue WHERE unic_result_id=$1 AND account_username=$2 AND platform=$3`,
    [RESULT,a,p])).rows[0];
  assert.ok((await q('q_dup','instagram')).cancelled_at, 'queued-дубль отменён');
  assert.equal((await q('p_dup','tiktok')).cancelled_at, null, 'published не тронут');
  assert.equal((await q('q_nodup','youtube')).cancelled_at, null, 'не-дубль не тронут');
});

test('повторный запуск — no-op (идемпотентность)', async()=>{
  const res = await cleanupPublishedDups(pool, { dryRun:false });
  assert.equal(res.cancelled, 0);
});

test('dryRun считает, но не отменяет', async()=>{
  await mqRow('q_dry','instagram','queued'); await doneInQueue('q_dry','instagram');
  const res = await cleanupPublishedDups(pool, { dryRun:true });
  assert.equal(res.candidates, 1);
  const row = (await pool.query(
    `SELECT cancelled_at FROM validator_manual_publish_queue WHERE unic_result_id=$1 AND account_username='q_dry'`,[RESULT])).rows[0];
  assert.equal(row.cancelled_at, null, 'dryRun не отменяет');
});
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `node --test --test-force-exit test_cleanup_wp148.test.js`
Expected: FAIL — `Cannot find module './cleanup_wp148_manual_queue_dups'`.

- [ ] **Step 3: Реализовать скрипт**

Создать `cleanup_wp148_manual_queue_dups.js`:

```js
'use strict';
// WP #148 one-off: отменить queued-строки ручной очереди, дублирующие уже успешную
// авто-публикацию (publish_queue.status='done'). published НЕ трогаем.
// Идемпотентно (повторный запуск ничего не находит). Использование:
//   node cleanup_wp148_manual_queue_dups.js          # dry-run (только счёт)
//   node cleanup_wp148_manual_queue_dups.js --apply  # отменить
const { Pool } = require('pg');

const TARGET_SQL = `
  FROM validator_manual_publish_queue q
  WHERE q.operator_status = 'queued'
    AND q.cancelled_at IS NULL
    AND EXISTS (
      SELECT 1 FROM publish_queue pq
      WHERE pq.unic_result_id = q.unic_result_id
        AND LOWER(pq.account_username) = LOWER(q.account_username)
        AND LOWER(pq.platform) = LOWER(q.platform)
        AND pq.status = 'done'
    )`;

async function cleanupPublishedDups(pool, { dryRun = true } = {}) {
  const cnt = (await pool.query(`SELECT count(*)::int AS n ${TARGET_SQL}`)).rows[0].n;
  if (dryRun) return { candidates: cnt, cancelled: 0 };
  const upd = await pool.query(
    `UPDATE validator_manual_publish_queue q
     SET cancelled_at = now(), updated_at = now()
     WHERE q.id IN (SELECT q.id ${TARGET_SQL})`);
  return { candidates: cnt, cancelled: upd.rowCount };
}

module.exports = { cleanupPublishedDups };

if (require.main === module) {
  const apply = process.argv.includes('--apply');
  const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });
  cleanupPublishedDups(pool, { dryRun: !apply })
    .then(r => { console.log(`[wp148-cleanup] ${apply ? 'APPLIED' : 'DRY-RUN'} candidates=${r.candidates} cancelled=${r.cancelled}`); })
    .catch(e => { console.error('[wp148-cleanup] error:', e.message); process.exitCode = 1; })
    .finally(() => pool.end());
}
```

- [ ] **Step 4: Прогнать — убедиться, что проходит**

Run: `node --test --test-force-exit test_cleanup_wp148.test.js`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add cleanup_wp148_manual_queue_dups.js test_cleanup_wp148.test.js
git commit -m "feat(wp148): one-off cleanup script for already-published queued manual-queue dups"
```

---

## Task 5: Полный прогон тестов + codex review

- [ ] **Step 1: Прогнать все затронутые тесты разом**

Run:
```bash
cd /home/claude-user/autowarm-testbench && node --test --test-force-exit \
  test_retry_controller.test.js test_retry_decision.test.js \
  test_manual_queue_assign_live.test.js tests/test_manual_queue_assign.test.js \
  test_cleanup_wp148.test.js \
  test_dispatch_manual_guard.test.js test_client_manual_publish.test.js \
  test_client_manual_filter.test.js
```
Expected: все PASS, 0 fail.

> Если параллельные zombie `node --test` процессы поднимают load — `pkill -f "test_.*\.test\.js"` (см. практику проекта). После прогона убедиться, что процессы завершились (`--test-force-exit`).

- [ ] **Step 2: Codex review диффа**

Run:
```bash
export PATH="$HOME/.local/bin:$PATH"
git diff main..HEAD | codex review -
```
Применить P1-замечания (раундами до 0 P1), перекоммитить точечно.

- [ ] **Step 3: Commit (если правки от codex)**

```bash
git add -A && git commit -m "fix(wp148): address codex review feedback"
```

---

## Task 6: Деплой на прод + ретро-зачистка + OpenProject

> Деплой меняет прод-поведение и пишет в прод-БД — выполнять с подтверждением пользователя. Не force-push в prod main.

- [ ] **Step 1: Мердж ветки в autowarm `main`** (через PR или fast-forward, по практике репозитория) и подтянуть в прод:

```bash
cd /root/.openclaw/workspace-genri/autowarm && git pull --ff-only
pm2 describe autowarm | grep "exec cwd"   # подтвердить cwd = /root/.openclaw/workspace-genri/autowarm (не testbench)
pm2 restart autowarm
```

- [ ] **Step 2: Dry-run ретро-зачистки на проде, сверить число**

> **NB:** ретро-зачистка 174 `queued`-дублей **уже выполнена** 2026-05-25 как глобальный побочный эффект live-DB теста до добавления `onlyResultId`-изоляции (подтверждено: 174 queued отменено, 137 published не тронуты, 0 не-дублей задето). Поэтому на проде ожидается уже `candidates≈0`. Шаг оставлен как идемпотентная подстраховка.

Run (из прод-копии):
```bash
cd /root/.openclaw/workspace-genri/autowarm && node cleanup_wp148_manual_queue_dups.js
```
Expected: `candidates≈0 cancelled=0` (зачистка уже применена; если cron нагенерил новых до деплоя фикса — небольшое число, это ок).

- [ ] **Step 3: Применить зачистку (если dry-run показал >0)**

Run (только если Step 2 показал candidates > 0):
```bash
node cleanup_wp148_manual_queue_dups.js --apply
```
Expected: `cancelled=<candidates>`.

- [ ] **Step 4: Верификация на проде (через ~10 мин, чтобы прошли тики populator/retry)**

```sql
-- дублей done в живой очереди не должно прибывать:
SELECT count(*) FROM validator_manual_publish_queue q
JOIN publish_queue pq ON pq.unic_result_id=q.unic_result_id
 AND LOWER(pq.account_username)=LOWER(q.account_username)
 AND LOWER(pq.platform)=LOWER(q.platform) AND pq.status='done'
WHERE q.cancelled_at IS NULL AND q.operator_status='queued';
-- ожидаемо: 0 (или близко к 0 при гонках)
```
Проверить логи: `pm2 logs autowarm --lines 200 | grep -E "retry-controller|manual-queue"` — handoff идёт per_account=true, populator пишет «уже опубликован автоматом, пропуск (WP#148)».

- [ ] **Step 5: Обновить WP #148 в OpenProject**

House-style комментарий (Что было не так → Что сделано → Что осталось, простым языком, без жаргона/футера), статус → «Тестирование» (id 9). Механика API — `reference-openproject-access`.

---

## Self-Review (заполнить при написании, проверка покрытия спеки)

- **Спека §«Изменения A» (per-account handoff):** Task 3. ✔
- **Спека §«Изменения B» (хелпер enqueueManualRow):** Task 1. ✔
- **Спека §«Изменения C» (exclude-done в populator):** Task 2. ✔
- **Спека §«Ретро-зачистка» (174 queued):** Task 4 + Task 6 Step 2-3. ✔
- **Спека §«Kill-switches»:** `RETRY_HANDOFF_PER_ACCOUNT` (Task 3), `MANUAL_QUEUE_EXCLUDE_PUBLISHED` (Task 2). ✔
- **Спека §«Тесты» (6 пунктов):** handoff per-account/idempotency/kill-switch (Task 3), exclude-done + kill-switch (Task 2), cleanup (Task 4). ✔
- **Спека §«Деплой»:** Task 6. ✔
- **Типы/имена:** `enqueueManualRow(db,row)` — определён Task 1, вызывается Task 1/3 с тем же объектом-строкой. `isAlreadyPublished(db,resultId,acc,platform)` — Task 2. `cleanupPublishedDups(pool,{dryRun})` — Task 4. Имена согласованы.
