# WP #154 — Re-queue после переноса слота: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать кандидатный дедуп популятора `assignUnicResultsToQueue` status-aware, чтобы перенесённый (move-cancelled) контент снова пере-ставился в `publish_queue`, не ломая подавление удалённого контента.

**Architecture:** Извлекаем dedup-предикат и кандидатный SELECT из гигантского `server.js` в новый focused-модуль `assign_candidates.js` (идиома репо — ср. `client_manual_filter.js`, `slot_matcher.js`). Это даёт чистую тестируемость без побочных эффектов импорта `server.js` (его cron `assignUnicResultsToQueue()` стартует на require). Сам фикс: впускать в кандидаты результаты, у которых единственная блокирующая строка — move-cancelled (`status='cancelled' AND COALESCE(skip_reason,'') LIKE 'moved_from_slot%'`); решение re-insert/suppress остаётся за существующим D3 lineage-guard. Под kill-switch `ASSIGN_REQUEUE_MOVED_ENABLED` (default ON).

**Tech Stack:** Node.js (CommonJS), PostgreSQL (`pg`), `node:test` runner (`node --test --test-force-exit`), прод-деплой через auto-push post-commit hook + PM2.

**Спека:** `docs/superpowers/specs/2026-05-26-wp154-requeue-after-slot-move-design.md`

---

## File Structure

- **Create:** `assign_candidates.js` — `requeueMovedEnabled()`, `assignCandidateDedupClause(enabled)`, `selectAssignCandidates(db, opts)`. Зависит от `./client_manual_filter`.
- **Modify:** `server.js` — require из `./assign_candidates`; заменить инлайновый кандидатный SELECT (строки ~6242-6271) на вызов `selectAssignCandidates(pool)`.
- **Create:** `tests/test_assign_requeue_moved.test.js` — unit (clause, без БД) + live-DB (selectAssignCandidates).
- **Modify:** `.env` (прод, не в репо) — задокументировать флаг `ASSIGN_REQUEUE_MOVED_ENABLED` (по умолчанию ON, ничего вписывать не нужно).

Прод-репо: `/root/.openclaw/workspace-genri/autowarm/` (ветка main, auto-push). Реализацию вести там же (как другие autowarm-фиксы), коммиты атомарные.

---

## Task 1: Модуль `assign_candidates.js` + dedup-предикат (clause)

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/assign_candidates.js`
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_assign_requeue_moved.test.js`

- [ ] **Step 1: Написать падающий unit-тест на clause**

Создать `tests/test_assign_requeue_moved.test.js`:

```js
'use strict';
// Run: node --test --test-force-exit tests/test_assign_requeue_moved.test.js
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { assignCandidateDedupClause } = require('../assign_candidates');

describe('assignCandidateDedupClause — WP #154', () => {
  test('flag ON: впускает move-cancelled, NULL-safe через COALESCE', () => {
    const sql = assignCandidateDedupClause(true);
    assert.match(sql, /NOT EXISTS/);
    assert.match(sql, /pq\.unic_result_id = ur\.id/);
    assert.match(sql, /NOT \(pq\.status = 'cancelled'/);
    assert.match(sql, /COALESCE\(pq\.skip_reason, ''\) LIKE 'moved_from_slot%'/);
  });

  test('flag OFF: status-слепой дедуп (без move-исключения)', () => {
    const sql = assignCandidateDedupClause(false);
    assert.match(sql, /NOT EXISTS/);
    assert.match(sql, /pq\.unic_result_id = ur\.id/);
    assert.doesNotMatch(sql, /moved_from_slot/);
  });
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_assign_requeue_moved.test.js`
Expected: FAIL — `Cannot find module '../assign_candidates'`.

- [ ] **Step 3: Создать `assign_candidates.js` с clause-хелпером**

```js
'use strict';
// WP #154: кандидатный отбор для assignUnicResultsToQueue, вынесен из server.js
// ради тестируемости (require('server.js') стартует cron'ы). Идиома репо —
// ср. client_manual_filter.js / slot_matcher.js.
const { effectiveManualSql } = require('./client_manual_filter');

// Kill-switch: ASSIGN_REQUEUE_MOVED_ENABLED=false возвращает status-слепой дедуп
// (доперенос-фиксовое прод-поведение) без передеплоя кода. Default ON.
function requeueMovedEnabled() {
  return process.env.ASSIGN_REQUEUE_MOVED_ENABLED !== 'false';
}

// Dedup-предикат кандидатного отбора. По умолчанию любая строка publish_queue с
// этим unic_result_id блокирует повторное назначение. При enabled НЕ блокируют
// строки, отменённые переносом слота (validator pipeline_reversal пишет
// skip_reason='moved_from_slot_<src>_to_<dst>'), чтобы перенесённый контент мог
// быть пере-поставлен на новую дату. Решение re-insert/suppress делегируется
// D3 lineage-guard (checkAssignQueueSlotLineage в server.js).
//
// NULL-safety (codex P2): без COALESCE для cancelled-строки со skip_reason IS NULL
// выражение `skip_reason LIKE ...` = NULL → `NOT(... AND NULL)` = NULL → строка не
// учитывается EXISTS → не-move отмена с NULL-причиной ошибочно впускалась бы.
// COALESCE(skip_reason,'') → '' LIKE 'moved_from_slot%' = FALSE → остаётся блокирующей.
function assignCandidateDedupClause(enabled = requeueMovedEnabled()) {
  const moveExclusion = enabled
    ? `\n        AND NOT (pq.status = 'cancelled' AND COALESCE(pq.skip_reason, '') LIKE 'moved_from_slot%')`
    : '';
  return `NOT EXISTS (
        SELECT 1 FROM publish_queue pq
        WHERE pq.unic_result_id = ur.id${moveExclusion}
      )`;
}

module.exports = { requeueMovedEnabled, assignCandidateDedupClause };
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_assign_requeue_moved.test.js`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add assign_candidates.js tests/test_assign_requeue_moved.test.js
git commit -m "feat(wp154): assign_candidates module + status-aware dedup clause (kill-switch)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `selectAssignCandidates` + live-DB тесты

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/assign_candidates.js`
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_assign_requeue_moved.test.js`

- [ ] **Step 1: Дописать падающие live-DB тесты**

Добавить в конец `tests/test_assign_requeue_moved.test.js`:

```js
const { before, after, beforeEach } = require('node:test');
const { Pool } = require('pg');
const { selectAssignCandidates } = require('../assign_candidates');
const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

// Изолированные id (диапазон 99154xx, чтобы не задеть прод-строки).
const PID=9915400, CONTENT=9915400, SLOT=9915400, TASK=9915400, RESULT=9915400;

async function cleanup(){
  await pool.query('DELETE FROM publish_queue WHERE unic_result_id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1',[TASK]).catch(()=>{});
  await pool.query('DELETE FROM validator_schedule_slots WHERE id=$1',[SLOT]).catch(()=>{});
  await pool.query('DELETE FROM validator_content WHERE id=$1',[CONTENT]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1',[PID]).catch(()=>{});
}

async function pq(status, skip_reason){
  await pool.query(
    `INSERT INTO publish_queue (unic_result_id, project_id, status, skip_reason, platform, account_username, scheduled_at, created_at, updated_at)
     VALUES ($1,$2,$3,$4,'instagram','acc1', now(), now(), now())`,
    [RESULT, PID, status, skip_reason]);
}
async function present(requeueMoved){
  const rows = await selectAssignCandidates(pool, { requeueMoved });
  return rows.some(r => r.result_id === RESULT);
}

describe('selectAssignCandidates — WP #154 (live DB)', () => {
  before(async()=>{
    await cleanup();
    await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,'WP154','wp154',true,false)`,[PID]);
    await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'wp154','approved','video',1)`,[CONTENT,PID]);
    await pool.query(`INSERT INTO validator_schedule_slots (id,project_id,slot_date,slot_position,content_id,slot_type,status,manual_publish) VALUES ($1,$2,'2026-05-28',1,$3,'client','filled',false)`,[SLOT,PID,CONTENT]);
    await pool.query(`INSERT INTO unic_tasks (id,project_id,project_name,content_id,slot_date,meta,current_status,schemes) VALUES ($1,$2,'WP154',$3,'2026-05-28',jsonb_build_object('slot_id',$4::text),'done','1')`,[TASK,PID,CONTENT,SLOT]);
    await pool.query(`INSERT INTO unic_results (id,task_id,scheme_id,output_url,status,created_at) VALUES ($1,$2,1,'http://x/v.mp4','done', now())`,[RESULT,TASK]);
  });
  after(async()=>{ await cleanup(); await pool.end(); });
  beforeEach(async()=>{
    await pool.query('DELETE FROM publish_queue WHERE unic_result_id=$1',[RESULT]);
    await pool.query(`UPDATE validator_schedule_slots SET manual_publish=false, status='filled', content_id=$2 WHERE id=$1`,[SLOT,CONTENT]);
  });

  test('1. move-cancelled only + flag ON → впущен', async()=>{
    await pq('cancelled','moved_from_slot_111_to_222');
    assert.equal(await present(true), true);
  });
  test('2. move-cancelled only + flag OFF → не впущен (прод-поведение)', async()=>{
    await pq('cancelled','moved_from_slot_111_to_222');
    assert.equal(await present(false), false);
  });
  test('3. cancelled с NULL skip_reason + flag ON → не впущен (NULL-safe)', async()=>{
    await pq('cancelled', null);
    assert.equal(await present(true), false);
  });
  test('4. cancelled с не-move причиной + flag ON → не впущен', async()=>{
    await pq('cancelled','slot_moved');
    assert.equal(await present(true), false);
  });
  test('5. есть живая pending-строка + flag ON → не впущен (нет дублей)', async()=>{
    await pq('cancelled','moved_from_slot_111_to_222');
    await pq('pending', null);
    assert.equal(await present(true), false);
  });
  test('6. move-cancelled + manual-слот + flag ON → не впущен', async()=>{
    await pq('cancelled','moved_from_slot_111_to_222');
    await pool.query(`UPDATE validator_schedule_slots SET manual_publish=true WHERE id=$1`,[SLOT]);
    assert.equal(await present(true), false);
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_assign_requeue_moved.test.js`
Expected: FAIL — `selectAssignCandidates is not a function` (ещё не экспортирован).

- [ ] **Step 3: Добавить `selectAssignCandidates` в `assign_candidates.js`**

Вставить перед `module.exports`:

```js
// Кандидатный SELECT популятора (вынесен из server.js без изменения семантики,
// кроме status-aware дедупа через assignCandidateDedupClause). Возвращает строки
// в том же виде, что ожидает цикл assignUnicResultsToQueue.
async function selectAssignCandidates(db, { requeueMoved = requeueMovedEnabled() } = {}) {
  const { rows } = await db.query(`
    SELECT
      ur.id            AS result_id,
      ur.task_id,
      ur.scheme_id,
      ur.output_url,
      ut.meta,
      ut.project_id,
      ut.project_name,
      to_char(ut.slot_date, 'YYYY-MM-DD') AS slot_date,
      vc.title         AS content_title,
      vc.description   AS content_description,
      vc.hashtags      AS content_hashtags,
      vc.geo           AS content_geo
    FROM unic_results ur
    JOIN unic_tasks ut ON ut.id = ur.task_id
    LEFT JOIN validator_content vc ON vc.id = ut.content_id
    WHERE ur.status IN ('ready','done')
      AND ${assignCandidateDedupClause(requeueMoved)}
      AND NOT EXISTS (
        SELECT 1 FROM validator_schedule_slots vss
        LEFT JOIN validator_projects p ON p.id = vss.project_id
        WHERE vss.id = (ut.meta->>'slot_id')::int
          AND ${effectiveManualSql('vss', 'p')}
      )
    ORDER BY ur.created_at ASC
    LIMIT 100
  `);
  return rows;
}
```

И обновить экспорт:

```js
module.exports = { requeueMovedEnabled, assignCandidateDedupClause, selectAssignCandidates };
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_assign_requeue_moved.test.js`
Expected: PASS (2 unit + 6 live = 8 тестов). Если всплывёт NOT NULL на `publish_queue` — добавить недостающую колонку в `pq()` (все прочие nullable, ср. `clampPastSlot` INSERT в server.js).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add assign_candidates.js tests/test_assign_requeue_moved.test.js
git commit -m "feat(wp154): selectAssignCandidates + live-DB tests (move-requeue/NULL-safe/manual/dup)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Интеграция в `server.js` (замена инлайнового запроса)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js` (require + строки ~6242-6271)

- [ ] **Step 1: Добавить require рядом с другими модульными импортами**

Возле `const { effectiveManualSql, slotIsEffectivelyManual } = require('./client_manual_filter');` (≈server.js:25) добавить:

```js
const { selectAssignCandidates } = require('./assign_candidates');
```

- [ ] **Step 2: Заменить инлайновый кандидатный SELECT на вызов**

В функции `assignUnicResultsToQueue` (server.js ≈6239) заменить блок, который сейчас выглядит так:

```js
    // 1. Найти unic_results без записи в publish_queue (не назначенные)
    const { rows: results } = await pool.query(`
      SELECT
        ur.id            AS result_id,
        ...
        AND NOT EXISTS (
          SELECT 1 FROM publish_queue pq WHERE pq.unic_result_id = ur.id
        )
        AND NOT EXISTS (
          SELECT 1 FROM validator_schedule_slots vss
          LEFT JOIN validator_projects p ON p.id = vss.project_id
          WHERE vss.id = (ut.meta->>'slot_id')::int
            AND ${effectiveManualSql('vss', 'p')}
        )
      ORDER BY ur.created_at ASC
      LIMIT 100
    `);
```

на:

```js
    // 1. Найти unic_results без живой записи в publish_queue (не назначенные).
    // WP #154: дедуп status-aware — move-cancelled строки не блокируют re-queue.
    const results = await selectAssignCandidates(pool);
```

(Удаляется весь инлайновый `pool.query` SELECT; остальная часть функции, начиная с `if (!results.length) return;`, не меняется.)

- [ ] **Step 3: Проверить, что модуль грузится без синтаксических ошибок**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node -e "require('./assign_candidates'); console.log('assign_candidates OK'); require('child_process'); const s=require('fs').readFileSync('./server.js','utf8'); new Function(s); console.log('server.js parses OK')"`
Expected: `assign_candidates OK` + `server.js parses OK` (без throw). Если упадёт — синтаксис в правке server.js.

- [ ] **Step 4: Прогнать релевантные существующие тесты (регрессия)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_assign_queue_clamp.test.js tests/test_pipeline_guards.test.js tests/test_assign_requeue_moved.test.js`
Expected: PASS во всех (clamp/guards не должны были задеться; новый — зелёный). Pre-existing фейлы (если есть) зафиксировать как НЕ регрессию.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js
git commit -m "feat(wp154): wire selectAssignCandidates into populator (status-aware requeue)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Codex review + деплой + смок на Енотах

**Files:** нет (review/deploy/monitor)

- [ ] **Step 1: Codex review диффа реализации**

Run: `cd /root/.openclaw/workspace-genri/autowarm && git diff HEAD~3 | ~/.local/bin/codex review -`
Применить P1/P2, перепрогнать до 0 P1. Закоммитить правки (если были).

- [ ] **Step 2: Деплой в прод (PM2)**

Auto-push hook уже доставит коммиты в `GenGo2/delivery-contenthunter`. Перезапустить процесс delivery:
Run: `sudo pm2 restart 35 && sleep 3 && sudo pm2 describe 35 | grep -E "status|exec cwd"`
Expected: `online`, `exec cwd = /root/.openclaw/workspace-genri/autowarm`. Сверить, что cwd НЕ stale-dev (ср. memory PM2 dump path drift).

- [ ] **Step 3: Проверить лог крона и флаг**

Run: `sudo pm2 logs 35 --lines 40 --nostream | grep -E "assign-queue|ASSIGN_REQUEUE"`
Expected: `[assign-queue] Обрабатываем N результатов...` без ошибок. (Флаг default ON; явно вписывать в `.env` не требуется.)

- [ ] **Step 4: Смок — Еноты (107) пере-ставились**

Run:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -P pager=off -c "
SELECT platform, status, scheduled_at, skip_reason
FROM publish_queue WHERE project_id=107 AND created_at > now() - interval '1 hour'
ORDER BY scheduled_at;"
```
Expected: появились `pending` строки на 27–30.05 (auto-слоты); 26.05 (manual) НЕ пере-ставлен; past-слотов в pending нет (либо `past_slot_dropped`).

- [ ] **Step 5: Смок — нет дублей и здоровье волны по 14 проектам**

Run:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -P pager=off -c "
-- дубли: один unic_result_id с >1 живой строкой
SELECT unic_result_id, count(*) FROM publish_queue
WHERE status IN ('pending','running') GROUP BY 1 HAVING count(*) > 1 LIMIT 20;"
psql -h localhost -U openclaw -d openclaw -P pager=off -c "
-- объём re-queue за час по проектам
SELECT project_id, status, count(*) FROM publish_queue
WHERE created_at > now() - interval '1 hour' GROUP BY 1,2 ORDER BY 1;"
```
Expected: дублей по `unic_result_id` среди живых строк НЕТ; объём re-queue ограничен (LIMIT 100/тик), доля `past_slot_dropped` ожидаема.

- [ ] **Step 6: Обновить WP #154 (house-style) + статус**

Комментарий: Что было не так (перенос слота отменял очередь, status-слепой дедуп не давал пере-поставить — системно, 14 проектов) → Что сделано (status-aware дедуп через D3-guard, kill-switch, авто-восстановление) → Что осталось (verify динамики выкладки ~27.05). Эль = штатное поведение (перенос сработал), отдельным абзацем. Статус → «Тестирование». Откат: `ASSIGN_REQUEUE_MOVED_ENABLED=false` + `sudo pm2 restart 35`.

---

## Self-Review (выполнено автором плана)

- **Покрытие спеки:** §2.5 первопричина → Task 1/2/3; §3.1 SQL + §3.4 kill-switch → Task 1; §5 сценарии 1/4/5/6 + flag → Task 2 (сценарии 2 «past-drop» и 3 «removed→suppress» покрыты *существующими* тестами `test_assign_queue_clamp`/`test_pipeline_guards` — этот фикс их не меняет, candidate-admission течёт в те же гарды; регрессия проверяется Task 3 Step 4); §4 разблокировка + §6 rollout → Task 4.
- **Плейсхолдеры:** нет; весь код и команды конкретны.
- **Консистентность имён:** `assignCandidateDedupClause`, `selectAssignCandidates`, `requeueMovedEnabled`, флаг `ASSIGN_REQUEUE_MOVED_ENABLED` — едины во всех задачах и совпадают со спекой.
- **Риск:** правка прод-популятора. Снижение — извлечение в отдельный модуль (тест без побочек), kill-switch default-ON с откатом без передеплоя, регрессия существующих guard-тестов, смок на одном проекте перед оценкой волны.
