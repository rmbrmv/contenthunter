# WP #125 — Manual-slot autopublish guard (hotfix) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Гарантировать, что слот с `manual_publish=true` (или client-level manual, WP #115) НИКОГДА не уходит в авто-публикацию — даже если строка `publish_queue` была создана до выставления флага.

**Architecture:** Единый чокпоинт — `checkDispatchQueueSlotLineage` в `server.js` (вызывается из `dispatchPublishQueue` перед claim `pending→running`). Туда добавляем перепроверку `manual_publish` через новый helper `slotIsEffectivelyManual` в `client_manual_filter.js` (переиспользует `effectiveManualSql`). Если слот manual — отменяем строку (`skip_reason='manual_publish'`) в той же транзакции под advisory-lock'ом и не диспатчим. Плюс разовая идемпотентная зачистка уже-pending manual-строк. Только репозиторий autowarm (`GenGo2/delivery-contenthunter`), без миграций.

**Tech Stack:** Node.js + Express, `pg` (Pool), Postgres `openclaw`, тесты `node --test` против живой БД (паттерн `test_client_manual_publish.test.js`).

**Spec:** `docs/superpowers/specs/2026-05-21-wp125-manual-slot-autopublish-guard-design.md`

---

## Контекст реализации (проверено в коде на 2026-05-21)

- `checkDispatchQueueSlotLineage({client, publishQueueId, unicResultId})` — `server.js:5999`. Уже: резолвит `slotId` из `unic_tasks.meta.slot_id` через `unic_results` (5003-5013); при отсутствии slot_id делает graceful legacy-skip (5015-5023); берёт `pg_advisory_xact_lock(ADVISORY_LOCK_NAMESPACE_SLOT, slotId)` (5026-5029); проверяет lineage (slot_id+content_id+slot_date+status='filled', 5032-5039); при невалидности — `UPDATE publish_queue SET status='cancelled', skip_reason='slot_no_longer_valid_at_dispatch'` (5043-5050); иначе claim `pending→running` (5062-5066). Возвращает `{skipped, skip_reason}` / `{legacy:true}` / `{claimed}`.
- Вызов из `dispatchPublishQueue` — `server.js:6627`; `if (guardResult.skipped) continue;` (6632) уже обрабатывает skip.
- Функция **экспортируется для тестов** (`server.js:8602`), а запуск сервера под `if (require.main === module)` (8576) — значит `require('./server')` в тесте НЕ поднимает Express/кроны.
- `client_manual_filter.js`: `effectiveManualSql(slotAlias, projAlias)` + `clientManualEnabled()` (kill-switch `CLIENT_MANUAL_PUBLISH_ENABLED`). Чистые строковые билдеры, без обращений к БД.
- `server.js:16`: `const { effectiveManualSql } = require('./client_manual_filter');`
- **Слой 2 (немедленная отмена при включении флага) — вне скоупа:** в autowarm НЕТ писателя `manual_publish` (флаг ставит валидатор, отдельный репозиторий). Слой 1 (этот чокпоинт) закрывает баг полностью; разовая зачистка убирает уже-затаившиеся строки. Валидаторную немедленную отмену оставляем опциональным follow-up.

> Номера строк индикативны — сверяйся с актуальным файлом (`grep -n "checkDispatchQueueSlotLineage" server.js`).

## Файловая структура

- **Modify:** `client_manual_filter.js` — добавить async-helper `slotIsEffectivelyManual(db, slotId)`.
- **Modify:** `server.js` — импорт helper'а (строка 16) + перепроверка manual в `checkDispatchQueueSlotLineage` (после advisory-lock, до lineage-проверки), под kill-switch `DISPATCH_MANUAL_RECHECK_ENABLED`.
- **Create:** `test_dispatch_manual_guard.test.js` — live-DB тесты helper'а и guard'а.
- **Create:** `scripts/wp125_cleanup_manual_pending.sql` — разовая идемпотентная зачистка.

---

### Task 1: helper `slotIsEffectivelyManual`

**Files:**
- Modify: `client_manual_filter.js`
- Test: `test_dispatch_manual_guard.test.js` (создаётся в этой задаче)

- [ ] **Step 1: Написать падающий тест helper'а**

Create `test_dispatch_manual_guard.test.js`:

```javascript
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { slotIsEffectivelyManual } = require('./client_manual_filter');

const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });

// High fixture IDs (avoid clashing with live data) — WP#125
const PID = 991250;        // project, manual_publish=false (slot-level manual only)
const PID_CLIENT = 991251; // project, manual_publish=true (client-level manual)
const CONTENT = 9912500;
const SLOT_MANUAL = 9912500;     // slot.manual_publish=true
const SLOT_PLAIN = 9912501;      // slot.manual_publish=false, plain project
const SLOT_CLIENT = 9912502;     // slot.manual_publish=false, client-manual project

async function cleanup() {
  await pool.query(`DELETE FROM validator_schedule_slots WHERE id = ANY($1)`, [[SLOT_MANUAL, SLOT_PLAIN, SLOT_CLIENT]]);
  await pool.query(`DELETE FROM validator_content WHERE id=$1`, [CONTENT]);
  await pool.query(`DELETE FROM validator_projects WHERE id = ANY($1)`, [[PID, PID_CLIENT]]);
}

async function setup() {
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,'WP125Plain','wp125plain',true,false)`, [PID]);
  await pool.query(`INSERT INTO validator_projects (id, project, api_name, active, manual_publish)
                    VALUES ($1,'WP125Client','wp125client',true,true)`, [PID_CLIENT]);
  await pool.query(`INSERT INTO validator_content (id, project_id, description, status, content_type, uploader_id)
                    VALUES ($1,$2,'WP125 manual guard fixture content','approved','video',1)`, [CONTENT, PID]);
  await pool.query(`INSERT INTO validator_schedule_slots
                    (id, project_id, slot_date, slot_position, content_id, slot_type, status, manual_publish)
                    VALUES ($1,$2, CURRENT_DATE, 1, $3, 'client', 'filled', true)`, [SLOT_MANUAL, PID, CONTENT]);
  await pool.query(`INSERT INTO validator_schedule_slots
                    (id, project_id, slot_date, slot_position, content_id, slot_type, status, manual_publish)
                    VALUES ($1,$2, CURRENT_DATE, 2, $3, 'client', 'filled', false)`, [SLOT_PLAIN, PID, CONTENT]);
  await pool.query(`INSERT INTO validator_schedule_slots
                    (id, project_id, slot_date, slot_position, content_id, slot_type, status, manual_publish)
                    VALUES ($1,$2, CURRENT_DATE, 3, $3, 'client', 'filled', false)`, [SLOT_CLIENT, PID_CLIENT, CONTENT]);
}

before(async () => { await setup(); });
after(async () => { await cleanup(); await pool.end(); });

test('slotIsEffectivelyManual: slot-level manual → true', async () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  assert.equal(await slotIsEffectivelyManual(pool, SLOT_MANUAL), true);
});

test('slotIsEffectivelyManual: plain slot → false', async () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  assert.equal(await slotIsEffectivelyManual(pool, SLOT_PLAIN), false);
});

test('slotIsEffectivelyManual: client-level manual → true', async () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  assert.equal(await slotIsEffectivelyManual(pool, SLOT_CLIENT), true);
});

test('slotIsEffectivelyManual: client-manual + kill-switch off → false', async () => {
  process.env.CLIENT_MANUAL_PUBLISH_ENABLED = 'false';
  assert.equal(await slotIsEffectivelyManual(pool, SLOT_CLIENT), false);
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
});

test('slotIsEffectivelyManual: null slotId → false', async () => {
  assert.equal(await slotIsEffectivelyManual(pool, null), false);
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test --test-force-exit test_dispatch_manual_guard.test.js`
Expected: FAIL — `slotIsEffectivelyManual is not a function` (helper ещё не существует).

- [ ] **Step 3: Реализовать helper в `client_manual_filter.js`**

Добавить ПЕРЕД `module.exports`:

```javascript
// WP #125: is a slot effectively manual (own flag OR client-level)? Reused by
// the dispatch chokepoint guard (server.js checkDispatchQueueSlotLineage) to
// re-check at dispatch time. db = pg Pool or a client inside a transaction.
async function slotIsEffectivelyManual(db, slotId) {
  if (!slotId) return false;
  const { rows } = await db.query(`
    SELECT 1 FROM validator_schedule_slots vss
    LEFT JOIN validator_projects p ON p.id = vss.project_id
    WHERE vss.id = $1 AND ${effectiveManualSql('vss', 'p')}
    LIMIT 1
  `, [slotId]);
  return rows.length > 0;
}
```

И обновить экспорт:

```javascript
module.exports = { clientManualEnabled, effectiveManualSql, slotIsEffectivelyManual };
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_dispatch_manual_guard.test.js`
Expected: PASS (5 helper-тестов зелёные).

- [ ] **Step 5: Commit**

```bash
git add client_manual_filter.js test_dispatch_manual_guard.test.js
git commit -m "feat(wp125): slotIsEffectivelyManual helper for dispatch-time manual re-check"
```

---

### Task 2: перепроверка manual в `checkDispatchQueueSlotLineage`

**Files:**
- Modify: `server.js:16` (импорт), `server.js:~6024` (вставка перепроверки после advisory-lock)
- Test: `test_dispatch_manual_guard.test.js` (дополняем)

- [ ] **Step 1: Дописать падающий integration-тест**

Добавить в конец `test_dispatch_manual_guard.test.js` (ВНУТРИ файла, до `after`-секции порядок не важен — `node --test` собирает все `test()`):

```javascript
const { checkDispatchQueueSlotLineage } = require('./server');

// fixtures for the end-to-end guard test
const TASK = 9912500;
const RESULT = 9912500;
const PQ_MANUAL = 9912500;  // pending publish_queue row tied to the manual slot
const PQ_PLAIN  = 9912501;  // pending publish_queue row tied to the plain slot

async function setupQueueRows() {
  await pool.query(`DELETE FROM publish_queue WHERE id = ANY($1)`, [[PQ_MANUAL, PQ_PLAIN]]);
  await pool.query(`DELETE FROM unic_results WHERE id=$1`, [RESULT]);
  await pool.query(`DELETE FROM unic_tasks WHERE id=$1`, [TASK]);
  // unic_task points at the MANUAL slot via meta.slot_id; content_id+slot_date must
  // match the slot so the lineage check (status='filled') would otherwise pass.
  await pool.query(`INSERT INTO unic_tasks (id, content_id, project_id, slot_date, current_status, meta)
                    VALUES ($1,$2,$3, CURRENT_DATE, 'done', jsonb_build_object('slot_id', $4::text))`,
                   [TASK, CONTENT, PID, SLOT_MANUAL]);
  await pool.query(`INSERT INTO unic_results (id, task_id, scheme_id, output_url, status, created_at)
                    VALUES ($1,$2, NULL, 'https://x/wp125.mp4', 'done', now())`, [RESULT, TASK]);
  await pool.query(`INSERT INTO publish_queue
                    (id, unic_result_id, unic_task_id, project_id, account_username, platform,
                     device_serial, media_url, scheduled_at, status)
                    VALUES ($1,$2,$3,$4,'wp125acc','instagram','WP125SER','https://x/wp125.mp4', NOW(), 'pending')`,
                   [PQ_MANUAL, RESULT, TASK, PID]);
}

test('checkDispatchQueueSlotLineage: cancels pending row for a manual slot', async () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  delete process.env.DISPATCH_MANUAL_RECHECK_ENABLED;
  await setupQueueRows();
  const client = await pool.connect();
  let result;
  try {
    result = await checkDispatchQueueSlotLineage({ client, publishQueueId: PQ_MANUAL, unicResultId: RESULT });
  } finally { client.release(); }
  assert.equal(result.skipped, true, 'guard must skip manual slot');
  assert.equal(result.skip_reason, 'manual_publish');
  const { rows } = await pool.query(`SELECT status, skip_reason FROM publish_queue WHERE id=$1`, [PQ_MANUAL]);
  assert.equal(rows[0].status, 'cancelled');
  assert.equal(rows[0].skip_reason, 'manual_publish');
  await pool.query(`DELETE FROM publish_queue WHERE id=$1`, [PQ_MANUAL]);
  await pool.query(`DELETE FROM unic_results WHERE id=$1`, [RESULT]);
  await pool.query(`DELETE FROM unic_tasks WHERE id=$1`, [TASK]);
});

test('checkDispatchQueueSlotLineage: kill-switch off → does NOT skip manual slot', async () => {
  delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  process.env.DISPATCH_MANUAL_RECHECK_ENABLED = 'false';
  await setupQueueRows();
  const client = await pool.connect();
  let result;
  try {
    result = await checkDispatchQueueSlotLineage({ client, publishQueueId: PQ_MANUAL, unicResultId: RESULT });
  } finally { client.release(); }
  // With recheck off, manual is not blocked → lineage valid → row claimed pending→running.
  assert.notEqual(result.skip_reason, 'manual_publish');
  const { rows } = await pool.query(`SELECT status FROM publish_queue WHERE id=$1`, [PQ_MANUAL]);
  assert.equal(rows[0].status, 'running');
  delete process.env.DISPATCH_MANUAL_RECHECK_ENABLED;
  await pool.query(`DELETE FROM publish_queue WHERE id=$1`, [PQ_MANUAL]);
  await pool.query(`DELETE FROM unic_results WHERE id=$1`, [RESULT]);
  await pool.query(`DELETE FROM unic_tasks WHERE id=$1`, [TASK]);
});
```

Также расширить `after` cleanup: добавить удаление `publish_queue`/`unic_results`/`unic_tasks` (на случай падения):

```javascript
after(async () => {
  await pool.query(`DELETE FROM publish_queue WHERE id = ANY($1)`, [[PQ_MANUAL, PQ_PLAIN]]).catch(()=>{});
  await pool.query(`DELETE FROM unic_results WHERE id=$1`, [RESULT]).catch(()=>{});
  await pool.query(`DELETE FROM unic_tasks WHERE id=$1`, [TASK]).catch(()=>{});
  await cleanup();
  await pool.end();
});
```
(удалить старый `after`, заменить этим — иначе двойной `pool.end()`.)

- [ ] **Step 2: Запустить — убедиться, что новый тест падает**

Run: `node --test --test-force-exit test_dispatch_manual_guard.test.js`
Expected: тест `cancels pending row for a manual slot` FAIL — guard пока не знает про manual, строка получит `running` (claim), `skip_reason !== 'manual_publish'`.

- [ ] **Step 3: Импортировать helper в `server.js`**

Заменить строку 16:

```javascript
const { effectiveManualSql } = require('./client_manual_filter');
```
на:
```javascript
const { effectiveManualSql, slotIsEffectivelyManual } = require('./client_manual_filter');
```

- [ ] **Step 4: Вставить перепроверку в `checkDispatchQueueSlotLineage`**

Сразу ПОСЛЕ блока advisory-lock (после `await client.query('SELECT pg_advisory_xact_lock($1, $2)', [ADVISORY_LOCK_NAMESPACE_SLOT, slotId]);`, ~строка 6029) и ПЕРЕД lineage-проверкой (`const valid = await client.query(...)`, ~6032) вставить:

```javascript
    // WP #125: manual-publish slots must never be auto-dispatched. The insert-time
    // guard (assignUnicResultsToQueue) can't catch rows enqueued BEFORE the slot was
    // flagged manual (confirmed root cause: slot 21246 — pending row created 19.05,
    // flag set 20.05, auto-published 21.05). Re-check here at the single chokepoint.
    // Kill-switch DISPATCH_MANUAL_RECHECK_ENABLED=false reverts to pre-fix behavior.
    if (process.env.DISPATCH_MANUAL_RECHECK_ENABLED !== 'false'
        && await slotIsEffectivelyManual(client, slotId)) {
      await client.query(`
        UPDATE publish_queue
        SET status = 'cancelled', skip_reason = 'manual_publish', updated_at = now()
        WHERE id = $1 AND status = 'pending'
      `, [publishQueueId]);
      console.log(JSON.stringify({
        tag: 'dispatch-queue', skipped: true, reason: 'manual_publish',
        publish_queue_id: publishQueueId, slot_id: slotId,
      }));
      await client.query('COMMIT');
      return { skipped: true, skip_reason: 'manual_publish' };
    }
```

- [ ] **Step 5: Запустить — убедиться, что все тесты проходят**

Run: `node --test --test-force-exit test_dispatch_manual_guard.test.js`
Expected: PASS (7 тестов: 5 helper + 2 guard).

- [ ] **Step 6: Анти-регрессия — прогнать соседние guard/queue тесты**

Run: `node --test test_client_manual_filter.test.js test_client_manual_publish.test.js`
Expected: PASS (поведение insert-time guard и matcher не изменилось).

- [ ] **Step 7: Commit**

```bash
git add server.js test_dispatch_manual_guard.test.js
git commit -m "fix(wp125): re-check manual_publish at dispatch chokepoint, cancel pending row

Root cause (confirmed by Feminista slot 21246 data): publish_queue rows are
enqueued before the operator flags the slot manual; nothing cancelled them and
dispatchPublishQueue never re-checked the flag. Guard now cancels such rows
(skip_reason=manual_publish) inside the advisory-lock tx. Kill-switch
DISPATCH_MANUAL_RECHECK_ENABLED."
```

---

### Task 3: разовая идемпотентная зачистка уже-pending manual-строк

**Files:**
- Create: `scripts/wp125_cleanup_manual_pending.sql`

- [ ] **Step 1: Написать зачистку**

Create `scripts/wp125_cleanup_manual_pending.sql`:

```sql
-- WP #125 one-time cleanup: cancel any currently-pending publish_queue rows whose
-- slot is effectively manual (own flag OR client-level). Idempotent — safe to re-run.
-- Layer-1 dispatch guard would skip these on the next tick anyway; this clears them
-- immediately so they don't sit visibly "pending".
-- codex P2: filter to NUMERIC meta.slot_id in a CTE BEFORE casting, so a single
-- legacy unic_tasks.meta with a missing/non-numeric slot_id can't abort the run with
-- "invalid input syntax for type integer" (mirrors the dispatch guard's legacy skip).
WITH manual_tasks AS (
  SELECT ut.id AS unic_task_id, (ut.meta->>'slot_id')::int AS slot_id
  FROM unic_tasks ut
  WHERE ut.meta->>'slot_id' ~ '^[0-9]+$'
)
UPDATE publish_queue pq
SET status = 'cancelled', skip_reason = 'manual_publish', updated_at = now()
FROM manual_tasks mt
JOIN validator_schedule_slots vss ON vss.id = mt.slot_id
LEFT JOIN validator_projects p ON p.id = vss.project_id
WHERE pq.status = 'pending'
  AND pq.unic_task_id = mt.unic_task_id
  AND (vss.manual_publish = true OR p.manual_publish = true);
```

- [ ] **Step 2: Dry-run (SELECT превью затронутых строк)**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT pq.id, pq.account_username, pq.platform, pq.status, vss.id AS slot_id
FROM publish_queue pq
JOIN unic_tasks ut ON ut.id = pq.unic_task_id AND ut.meta->>'slot_id' ~ '^[0-9]+$'
JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
LEFT JOIN validator_projects p ON p.id = vss.project_id
WHERE pq.status='pending' AND (vss.manual_publish=true OR p.manual_publish=true);"
```
Expected: 0 строк сейчас (по диагностике 21.05 боевых pending-manual нет). Если строки есть — это и есть «затаившиеся» случаи; зачистка их уберёт.

- [ ] **Step 3: Применить (на проде — на чекпоинте деплоя, см. ниже). На testbench — прогнать для проверки идемпотентности**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f scripts/wp125_cleanup_manual_pending.sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f scripts/wp125_cleanup_manual_pending.sql
```
Expected: оба прогона без ошибок (`UPDATE 0` если боевых строк нет — идемпотентно).

- [ ] **Step 4: Commit**

```bash
git add scripts/wp125_cleanup_manual_pending.sql
git commit -m "chore(wp125): one-time idempotent cleanup of pending manual publish_queue rows"
```

---

### Task 4: финальная проверка + handoff на ревью

- [ ] **Step 1: Прогнать весь релевантный тест-сюит**

Run: `node --test --test-force-exit test_dispatch_manual_guard.test.js test_client_manual_filter.test.js test_client_manual_publish.test.js`
Expected: все PASS.

- [ ] **Step 2: Code review (superpowers:requesting-code-review) + codex review диффа**

Run: `git diff main HEAD | ~/.local/bin/codex review -`
Применить P1-фидбэк, до 0 P1.

- [ ] **Step 3: PR в `GenGo2/delivery-contenthunter`** (на одобрении Данила; деплой — отдельный чекпоинт)

Деплой (с одобрения Данила): prod `git pull` + применить `scripts/wp125_cleanup_manual_pending.sql` + `pm2 restart autowarm` (или per-task spawn — уточнить актуальный механизм по памяти PM2 dump path drift). Smoke: лог `dispatch-queue ... reason: manual_publish` появляется для manual-строк; non-manual публикуются. Мониторить ложноблоки сутки. Kill-switch `DISPATCH_MANUAL_RECHECK_ENABLED=false` при проблеме.

- [ ] **Step 4: OpenProject #125** — статус-комментарий (house style: Что было не так → Что сделано → Что осталось, без жаргона), перевести в «Тестирование» после деплоя.

---

## Self-review (выполнено автором плана)

- **Покрытие спека:** слой 1 (дисп-чокпоинт) → Task 2; helper → Task 1; разовая зачистка → Task 3; kill-switch → Task 2 Step 4; тесты (manual блок / non-manual / client-level / kill-switch / legacy-null) → Task 1+2; деплой → Task 4. Слой 2 (валидаторная немедленная отмена) осознанно вне скоупа (в autowarm нет писателя флага; слой 1 закрывает баг) — отражено в «Контексте реализации».
- **Плейсхолдеры:** нет — весь код приведён.
- **Согласованность типов:** helper `slotIsEffectivelyManual(db, slotId)` единообразно вызывается в тесте и в `server.js`; `skip_reason='manual_publish'` и возврат `{skipped:true, skip_reason:'manual_publish'}` согласованы между Task 2 Step 4 и тестом.
