# WP #155 — Гейт просрочки в ручной очереди: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ручной наполнитель очереди выкладки перестаёт сваливать в очередь просроченный архив проекта — льёт только слоты с план-датой не старше грейс-окна (по умолчанию 3 дня), как авто-тракт дропает прошедшие слоты; накопившаяся просрочка зачищается разовым скриптом; колонка «Ручная дата» переименована.

**Architecture:** Гейт реализован SQL-фильтром в SELECT наполнителя `assignManualPublishQueue` (`manual_queue_assign.js`) под env-флагами; cutoff считается `computeBusinessDate(tz, now − grace)` ровно как в авто-тракте. Ретро-зачистка — отдельный one-off скрипт по паттерну `cleanup_wp148_manual_queue_dups.js`. Ярлык — одна строка `public/index.html`.

**Tech Stack:** Node.js (CommonJS), PostgreSQL (`pg`), `node --test`, репо `GenGo2/delivery-contenthunter` (autowarm).

**Спека:** `docs/superpowers/specs/2026-05-26-wp155-manual-queue-past-slot-gate-design.md`.

---

## Где работаем

Код живёт в репо autowarm (`GenGo2/delivery-contenthunter`). **Не работать в прод-копии** `/root/.openclaw/workspace-genri/autowarm` (там auto-push hook на main). Все правки — в изолированном worktree от dev-чекаута `autowarm-testbench`.

### Task 0: Подготовить worktree

**Files:** нет (setup).

- [ ] **Step 1: Завести worktree + ветку от origin/main**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add -b wp155-manual-queue-past-slot-gate /home/claude-user/autowarm-wp155 origin/main
```

- [ ] **Step 2: Подключить node_modules (worktree их не наследует; нужны для `node --test` → `pg`)**

```bash
ln -s /home/claude-user/autowarm-testbench/node_modules /home/claude-user/autowarm-wp155/node_modules
```

- [ ] **Step 3: Базовый прогон тестов наполнителя — зелёный до правок**

Run: `cd /home/claude-user/autowarm-wp155 && node --test tests/test_manual_queue_assign.test.js`
Expected: PASS (5 тестов) — фиксируем исходное зелёное состояние.

---

## Task 1: Гейт просрочки в наполнителе

**Files:**
- Modify: `manual_queue_assign.js` (хелперы-флаги + расчёт cutoff + условный фильтр в SELECT `assignManualPublishQueue`, текущие строки 5–13 и 58–75)
- Test: `tests/test_manual_queue_assign.test.js`

- [ ] **Step 1: Расширить mock-pool в тесте — обработать запрос `unic_settings` и захватывать SELECT наполнителя**

В `tests/test_manual_queue_assign.test.js`, в `makePool` добавить параметр `capture` и две ветки. Заменить сигнатуру и начало `query`:

```js
function makePool({ results, packId = 99, accounts, dupFor = new Set(), publishedKeys = new Set(), capture = {} }) {
  const inserts = [];
  return {
    inserts,
    query: async (sql, params) => {
      if (/FROM unic_settings/.test(sql)) return { rows: [{ timezone: 'Asia/Dubai' }] };
      if (/FROM unic_results/.test(sql)) { capture.unicSql = sql; capture.unicParams = params; return { rows: results }; }
      if (/FROM unic_tasks WHERE id=/.test(sql)) return { rows: [{ schemes: '12' }] };
      if (/FROM factory_pack_accounts WHERE project_id/.test(sql)) return { rows: [{ id: packId }] };
      if (/factory_device_numbers/.test(sql)) return { rows: [{ pack_id: packId, pack_name: 'P', device_serial: 'S', raspberry: 9, phone_number: 19 }] };
      if (/FROM factory_inst_accounts/.test(sql)) return { rows: accounts };
      if (/SELECT 1 FROM validator_manual_publish_queue/.test(sql)) {
        const key = params[1] + '|' + params[2];
        return { rows: dupFor.has(key) ? [{ '?column?': 1 }] : [] };
      }
      if (/SELECT 1 FROM publish_queue/.test(sql)) {
        const key = (params[1] + '|' + params[2]).toLowerCase();
        return { rows: publishedKeys.has(key) ? [{ '?column?': 1 }] : [] };
      }
      if (/INSERT INTO validator_manual_publish_queue/.test(sql)) { inserts.push(params); return { rows: [{ id: 1 }] }; }
      throw new Error('unexpected SQL: ' + sql);
    },
  };
}
```

- [ ] **Step 2: Написать падающие тесты гейта (в конец файла)**

```js
const { computeBusinessDate } = require('../unic_sweep');

test('past-slot gate ON: SELECT фильтрует slot_date >= cutoff (today - 3д по умолчанию)', async () => {
  delete process.env.MANUAL_QUEUE_DROP_PAST_SLOTS;
  delete process.env.MANUAL_QUEUE_PAST_SLOT_GRACE_DAYS;
  const capture = {};
  const pool = makePool({ results: [], accounts: [], capture });
  await assignManualPublishQueue(pool, silent);
  assert.match(capture.unicSql, /to_char\(vss\.slot_date, 'YYYY-MM-DD'\) >= \$2/);
  assert.strictEqual(capture.unicParams[1], computeBusinessDate('Asia/Dubai', Date.now() - 3 * 86400000));
});

test('past-slot gate OFF (MANUAL_QUEUE_DROP_PAST_SLOTS=false): фильтра нет, только batchSize-параметр', async () => {
  process.env.MANUAL_QUEUE_DROP_PAST_SLOTS = 'false';
  const capture = {};
  const pool = makePool({ results: [], accounts: [], capture });
  await assignManualPublishQueue(pool, silent);
  delete process.env.MANUAL_QUEUE_DROP_PAST_SLOTS;
  assert.ok(!/>=\s*\$/.test(capture.unicSql), 'фильтра slot_date>= быть не должно');
  assert.strictEqual(capture.unicParams.length, 1);
});

test('MANUAL_QUEUE_PAST_SLOT_GRACE_DAYS меняет cutoff', async () => {
  process.env.MANUAL_QUEUE_PAST_SLOT_GRACE_DAYS = '7';
  const capture = {};
  const pool = makePool({ results: [], accounts: [], capture });
  await assignManualPublishQueue(pool, silent);
  delete process.env.MANUAL_QUEUE_PAST_SLOT_GRACE_DAYS;
  assert.strictEqual(capture.unicParams[1], computeBusinessDate('Asia/Dubai', Date.now() - 7 * 86400000));
});
```

- [ ] **Step 3: Прогнать — тесты падают (фильтра ещё нет)**

Run: `cd /home/claude-user/autowarm-wp155 && node --test tests/test_manual_queue_assign.test.js`
Expected: 3 новых теста FAIL (нет `unic_settings`-чтения / нет фильтра / `unicParams` длиной 1), старые 5 — либо PASS, либо упадут на `unexpected SQL: ...unic_settings` если фильтр уже добавлен; на этом шаге фильтра нет → новые падают по `assert.match`/`unicParams[1] undefined`.

- [ ] **Step 4: Добавить флаги-хелперы в `manual_queue_assign.js`**

После `excludePublishedEnabled()` (строка 13) добавить:

```js
function dropPastEnabled() {
  return process.env.MANUAL_QUEUE_DROP_PAST_SLOTS !== 'false';
}
function pastSlotGraceDays() {
  const n = parseInt(process.env.MANUAL_QUEUE_PAST_SLOT_GRACE_DAYS || '3', 10);
  return Number.isFinite(n) && n >= 0 ? n : 3;
}
```

- [ ] **Step 5: Встроить расчёт cutoff и условный фильтр в `assignManualPublishQueue`**

Заменить блок SELECT (текущие строки 58–75) на версию с подготовкой фильтра ПЕРЕД запросом:

```js
    // WP#155: гейт просрочки — не тащить в ручную слоты с план-датой старше грейса.
    // Зеркалит политику авто-тракта (server.js clampPastSlot), но с грейс-окном
    // (ручная выкладка = человеческий догон). Фильтр в SQL обязателен: иначе при
    // ORDER BY ur.created_at ASC LIMIT батч забьётся старьём и актуальные не дойдут.
    let pastFilter = '';
    const params = [batchSize()];
    if (dropPastEnabled()) {
      const { computeBusinessDate } = require('./unic_sweep');
      const { rows: settings } = await pool.query('SELECT * FROM unic_settings WHERE id=1');
      const timezone = settings[0]?.timezone || 'Asia/Dubai';
      const cutoff = computeBusinessDate(timezone, Date.now() - pastSlotGraceDays() * 86400000);
      params.push(cutoff);
      pastFilter = `AND to_char(vss.slot_date, 'YYYY-MM-DD') >= $${params.length}`;
      log.log(`[manual-queue] past-slot gate ON: cutoff=${cutoff} grace=${pastSlotGraceDays()}d`);
    }

    const { rows: results } = await pool.query(`
      SELECT ur.id AS result_id, ur.task_id, ur.scheme_id, ur.output_url,
             ut.meta, ut.project_id, ut.project_name, ut.content_id,
             (ut.meta->>'slot_id')::int AS slot_id,
             vss.slot_date AS planned_date
      FROM unic_results ur
      JOIN unic_tasks ut ON ut.id = ur.task_id
      JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
      LEFT JOIN validator_projects p ON p.id = vss.project_id
      WHERE ur.status IN ('ready','done')
        AND ${effectiveManualSql('vss', 'p')}
        ${pastFilter}
        AND NOT EXISTS (
          SELECT 1 FROM validator_manual_publish_queue q
          WHERE q.unic_result_id = ur.id AND q.cancelled_at IS NULL
        )
      ORDER BY ur.created_at ASC
      LIMIT $1
    `, params);
```

> Параметры позиционные: `$1` = batchSize (в `LIMIT $1`), `$2` = cutoff (в фильтре). Порядок в SQL роли не играет.

- [ ] **Step 6: Прогнать — все тесты зелёные**

Run: `cd /home/claude-user/autowarm-wp155 && node --test tests/test_manual_queue_assign.test.js`
Expected: PASS (8 тестов: 5 старых + 3 новых). Старые проходят, т.к. mock возвращает `results` независимо от фильтра, а ветка `unic_settings` теперь обработана.

- [ ] **Step 7: Коммит**

```bash
cd /home/claude-user/autowarm-wp155
git add manual_queue_assign.js tests/test_manual_queue_assign.test.js
git commit -m "feat(wp155): past-slot gate в ручном наполнителе (grace 3д, kill-switch)"
```

---

## Task 2: Скрипт ретро-зачистки просрочки

**Files:**
- Create: `cleanup_wp155_manual_queue_overdue.js`
- Test: `test_cleanup_wp155_overdue_live.test.js` (живой DB-тест, паттерн `test_manual_queue_assign_live.test.js`)

- [ ] **Step 1: Написать падающий живой тест**

Создать `test_cleanup_wp155_overdue_live.test.js`:

```js
// Run: node --test --test-force-exit test_cleanup_wp155_overdue_live.test.js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { cleanupOverdue } = require('./cleanup_wp155_manual_queue_overdue');
const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

// Изолированные id (диапазон 99155xxx, чтобы не задеть прод).
const PID=9915500, CONTENT=9915500, SLOT=9915500, TASK=9915500, RESULT=9915500;
const PROJ='WP155TestProj';
const CUTOFF='2026-05-23';                 // фиксированный порог для детерминизма
const QID = { pastq:99155001, graceq:99155002, pastpub:99155003, pastinprog:99155004 };

async function cleanup(){
  await pool.query('DELETE FROM validator_manual_publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1',[TASK]).catch(()=>{});
  await pool.query('DELETE FROM validator_schedule_slots WHERE id=$1',[SLOT]).catch(()=>{});
  await pool.query('DELETE FROM validator_content WHERE id=$1',[CONTENT]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1',[PID]).catch(()=>{});
}

before(async()=>{
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,$2,'wp155',true,true)`,[PID,PROJ]);
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'wp155','approved','video',1)`,[CONTENT,PID]);
  await pool.query(`INSERT INTO validator_schedule_slots (id,project_id,slot_date,slot_position,content_id,slot_type,status,manual_publish) VALUES ($1,$2,'2026-05-25',1,$3,'client','filled',true)`,[SLOT,PID,CONTENT]);
  // unic_tasks/unic_results — на текущей схеме FK на unic_result_id/unic_task_id НЕТ
  // (FK только slot_id/taken_by_id/published_by_id), но сидируем для устойчивости к будущим FK.
  await pool.query(`INSERT INTO unic_tasks (id,content_id,project_id,slot_date,current_status,meta) VALUES ($1,$2,$3,'2026-05-25','done',jsonb_build_object('slot_id',$4::text))`,[TASK,CONTENT,PID,SLOT]);
  await pool.query(`INSERT INTO unic_results (id,task_id,scheme_id,output_url,status,created_at) VALUES ($1,$2,NULL,'https://x/y.mp4','done',now())`,[RESULT,TASK]);
  // 4 строки: одна queued+просрочена (кандидат), одна queued+в грейсе, одна published+просрочена, одна in_progress+просрочена.
  const rows = [
    [QID.pastq,    'acc_pastq',    'instagram','2026-05-10','queued'],
    [QID.graceq,   'acc_graceq',   'instagram','2026-05-25','queued'],
    [QID.pastpub,  'acc_pastpub',  'instagram','2026-05-10','published'],
    [QID.pastinprog,'acc_pastinprog','instagram','2026-05-10','in_progress'],
  ];
  for (const [id,acc,plat,pdate,st] of rows) {
    await pool.query(`INSERT INTO validator_manual_publish_queue
      (id,slot_id,content_id,unic_result_id,unic_task_id,project_id,project_name,pack_id,pack_name,
       account_username,platform,phone_number,planned_date,operator_status)
      VALUES ($1,$2,$3,$4,$5,$6,$7,7777,'WP155Pack',$8,$9,'19',$10,$11)`,
      [id,SLOT,CONTENT,RESULT,TASK,PID,PROJ,acc,plat,pdate,st]);
  }
});
after(async()=>{ await cleanup(); await pool.end(); });

test('dry-run: считает 1 кандидата (queued+просрочен), ничего не отменяет', async()=>{
  const r = await cleanupOverdue(pool, { dryRun:true, cutoff:CUTOFF, onlyProject:PROJ });
  assert.equal(r.candidates, 1);
  assert.equal(r.cancelled, 0);
  const { rows } = await pool.query(`SELECT count(*)::int n FROM validator_manual_publish_queue WHERE unic_result_id=$1 AND cancelled_at IS NOT NULL`,[RESULT]);
  assert.equal(rows[0].n, 0, 'dry-run не пишет');
});

test('apply: отменяет только queued+просрочен; published/in_progress/в-грейсе не трогает', async()=>{
  const r = await cleanupOverdue(pool, { dryRun:false, cutoff:CUTOFF, onlyProject:PROJ });
  assert.equal(r.cancelled, 1);
  const { rows } = await pool.query(`SELECT id, cancelled_at FROM validator_manual_publish_queue WHERE unic_result_id=$1 ORDER BY id`,[RESULT]);
  const byId = Object.fromEntries(rows.map(x=>[x.id, x.cancelled_at]));
  assert.ok(byId[QID.pastq] !== null, 'просроченный queued отменён');
  assert.equal(byId[QID.graceq], null, 'в грейсе — не трогаем');
  assert.equal(byId[QID.pastpub], null, 'published — не трогаем');
  assert.equal(byId[QID.pastinprog], null, 'in_progress — не трогаем');
});

test('idempotent: повторный apply находит 0 кандидатов', async()=>{
  const r = await cleanupOverdue(pool, { dryRun:false, cutoff:CUTOFF, onlyProject:PROJ });
  assert.equal(r.candidates, 0);
  assert.equal(r.cancelled, 0);
});
```

- [ ] **Step 2: Прогнать — падает (модуль ещё не создан)**

Run: `cd /home/claude-user/autowarm-wp155 && node --test --test-force-exit test_cleanup_wp155_overdue_live.test.js`
Expected: FAIL — `Cannot find module './cleanup_wp155_manual_queue_overdue'`.

- [ ] **Step 3: Создать скрипт `cleanup_wp155_manual_queue_overdue.js`**

```js
'use strict';
// WP #155 one-off: отменить queued-строки ручной очереди с план-датой старше
// порога (today - GRACE дней). published/in_progress НЕ трогаем. Идемпотентно
// (повторный запуск ничего не находит). Использование:
//   node cleanup_wp155_manual_queue_overdue.js                        # dry-run (только счёт)
//   node cleanup_wp155_manual_queue_overdue.js --apply                # отменить
//   node cleanup_wp155_manual_queue_overdue.js --onlyProject=Feminista  # изоляция (ILIKE по имени или = по id)
const { Pool } = require('pg');
const { computeBusinessDate } = require('./unic_sweep');

function graceDays() {
  const n = parseInt(process.env.MANUAL_QUEUE_PAST_SLOT_GRACE_DAYS || '3', 10);
  return Number.isFinite(n) && n >= 0 ? n : 3;
}

// scoped — тест-изоляция/точечный прогон: сужает запрос до одного проекта.
// В проде без --onlyProject запрос ГЛОБАЛЬНЫЙ.
function targetSql(scoped) {
  return `
  FROM validator_manual_publish_queue q
  WHERE q.operator_status = 'queued'
    AND q.cancelled_at IS NULL
    AND to_char(q.planned_date, 'YYYY-MM-DD') < $1
    ${scoped ? 'AND (q.project_name ILIKE $2 OR q.project_id::text = $2)' : ''}`;
}

async function cleanupOverdue(pool, { dryRun = true, onlyProject = null, cutoff = null } = {}) {
  if (!cutoff) {
    const { rows: settings } = await pool.query('SELECT * FROM unic_settings WHERE id=1');
    const timezone = settings[0]?.timezone || 'Asia/Dubai';
    cutoff = computeBusinessDate(timezone, Date.now() - graceDays() * 86400000);
  }
  const scoped = onlyProject != null;
  const params = scoped ? [cutoff, onlyProject] : [cutoff];
  const cnt = (await pool.query(`SELECT count(*)::int AS n ${targetSql(scoped)}`, params)).rows[0].n;
  if (dryRun) return { cutoff, candidates: cnt, cancelled: 0 };
  const upd = await pool.query(
    `UPDATE validator_manual_publish_queue q
     SET cancelled_at = now(), updated_at = now()
     WHERE q.id IN (SELECT q.id ${targetSql(scoped)})`, params);
  return { cutoff, candidates: cnt, cancelled: upd.rowCount };
}

module.exports = { cleanupOverdue };

if (require.main === module) {
  const apply = process.argv.includes('--apply');
  const onlyArg = process.argv.find(a => a.startsWith('--onlyProject='));
  const onlyProject = onlyArg ? onlyArg.split('=')[1] : null;
  const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });
  cleanupOverdue(pool, { dryRun: !apply, onlyProject })
    .then(r => console.log(`[wp155-cleanup] ${apply ? 'APPLIED' : 'DRY-RUN'} cutoff=${r.cutoff} candidates=${r.candidates} cancelled=${r.cancelled} reason=wp155_overdue_gate`))
    .catch(e => { console.error('[wp155-cleanup] error:', e.message); process.exitCode = 1; })
    .finally(() => pool.end());
}
```

- [ ] **Step 4: Прогнать — тесты зелёные**

Run: `cd /home/claude-user/autowarm-wp155 && node --test --test-force-exit test_cleanup_wp155_overdue_live.test.js`
Expected: PASS (3 теста). Если падает на FK/NOT NULL при INSERT фикстуры — сверить набор колонок строки очереди с `test_manual_publish_queue.test.js` setup (строки 42–46).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-wp155
git add cleanup_wp155_manual_queue_overdue.js test_cleanup_wp155_overdue_live.test.js
git commit -m "feat(wp155): one-off скрипт зачистки просроченных queued-строк (dry-run default)"
```

---

## Task 3: Переименовать колонку «Ручная дата»

**Files:**
- Modify: `public/index.html:12102`

- [ ] **Step 1: Поменять label в `MPQ_COLS`**

Заменить строку 12102:

```js
  { key: 'manual_date',      label: 'Ручная дата', filter: 'daterange' },
```
на:
```js
  { key: 'manual_date',      label: 'Добавлено в очередь', filter: 'daterange' },
```

> Ключ `manual_date`, бэкенд-алиас и фильтр `daterange` НЕ трогаем — меняется только отображаемый текст.

- [ ] **Step 2: Проверка отсутствия других вхождений старого ярлыка**

Run: `cd /home/claude-user/autowarm-wp155 && grep -n "'Ручная дата'" public/index.html`
Expected: пусто (единственное вхождение заменено).

- [ ] **Step 3: Коммит**

```bash
cd /home/claude-user/autowarm-wp155
git add public/index.html
git commit -m "feat(wp155): колонка ручной очереди «Ручная дата» → «Добавлено в очередь»"
```

---

## Task 4: Финальная проверка и PR

**Files:** нет.

- [ ] **Step 1: Полный прогон затронутых тестов**

Run:
```bash
cd /home/claude-user/autowarm-wp155
node --test tests/test_manual_queue_assign.test.js
node --test --test-force-exit test_cleanup_wp155_overdue_live.test.js
```
Expected: оба PASS.

- [ ] **Step 2: Открыть PR в `GenGo2/delivery-contenthunter`**

```bash
cd /home/claude-user/autowarm-wp155
set -a; . ~/secrets/github-gengo2.env; set +a
git push -u origin wp155-manual-queue-past-slot-gate
gh pr create --repo GenGo2/delivery-contenthunter --base main \
  --title "WP#155: гейт просрочки в ручной очереди выкладки" \
  --body "Гейт прошедших слотов в наполнителе (grace 3д, kill-switch MANUAL_QUEUE_DROP_PAST_SLOTS) + one-off зачистка просрочки + переименование колонки. Спека/план в rmbrmv/contenthunter docs/superpowers."
```

> **Стоп-гейт:** PR на ревью. Деплой (Task 5) — только после одобрения.

---

## Task 5: Деплой и зачистка (после одобрения PR — операционный шаг)

**Files:** нет. Выполняется на проде после merge PR; требует явного go-ahead.

- [ ] **Step 1: Бэкенд в прод**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git checkout main && git pull
sudo pm2 restart autowarm   # ROOT PM2 id=35; наполнитель — setInterval в server.js
sudo pm2 describe autowarm | grep "exec cwd"   # должен быть /root/.openclaw/workspace-genri/autowarm
```

- [ ] **Step 2: Фронт в прод (cherry-pick в прод main → auto-push hook)**

`public/index.html` живёт в прод-чекауте; правка ярлыка попадёт тем же `git pull` (Step 1) — отдельный cp не нужен, т.к. index.html в том же репо. Проверить, что прод-main содержит коммит ярлыка.

- [ ] **Step 3: Зачистка — сначала dry-run, потом точечно, потом глобально**

```bash
cd /root/.openclaw/workspace-genri/autowarm
node cleanup_wp155_manual_queue_overdue.js                                  # глобальный dry-run: смотрим candidates
node cleanup_wp155_manual_queue_overdue.js --onlyProject="Патчи для глаз Feminista" --apply   # точечно на одном проекте
node cleanup_wp155_manual_queue_overdue.js --apply                          # глобально, когда точечный ОК
```

- [ ] **Step 4: Верификация после деплоя**

```sql
-- просроченных queued не должно остаться (по грейсу 3д)
SELECT count(*) FROM validator_manual_publish_queue
WHERE cancelled_at IS NULL AND operator_status='queued'
  AND planned_date < (CURRENT_DATE - 3);
```
Expected: 0 (или близко к 0 с учётом таймзоны). И в логах автоварма — строка `[manual-queue] past-slot gate ON: cutoff=... grace=3d`.

- [ ] **Step 5: Обновить WP #155 в OpenProject** — статус-коммент (стиль: Что было не так → Что сделано → Что осталось, без жаргона) + перевести в «Тестирование» (id 9).

---

## Заметки для исполнителя

- **Не пушить force** в прод main; не работать в `/root/.openclaw/workspace-genri/autowarm` напрямую.
- **Живые тесты бьют по реальной БД** (openclaw) с изолированными id 99155xxx и `onlyProject` — UPDATE в тесте всегда scoped, чтобы не задеть прод-строки.
- **Kill-switch/grace меняются только с рестартом** `sudo pm2 restart autowarm --update-env` (env фиксируется на старте процесса).
- Перед коммитами — `git fetch` и зелёные тесты (параллельные сессии).
