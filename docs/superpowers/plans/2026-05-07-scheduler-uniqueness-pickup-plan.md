# Scheduler→Uniqueness Pickup Sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Любой `(slot=filled, content=approved+passed, slot_date=today)` доходит до `unic_tasks` максимум за один sweep-интервал (5 мин), без риска двойной публикации при concurrency.

**Architecture:** Один новый модуль `unic_sweep.js` (date math + sweep loop). Существующая `runAutoUnicForDate` извлекается в `run_auto_unic.js` (DI-фабрика, тестируема без boot'а server.js) и одновременно получает ON CONFLICT DO NOTHING. Партиальный unique index `(content_id, slot_date) WHERE current_status IN ('pending','processing','done')` блокирует физические дубликаты. Sweep таргетит `[today, yesterday]` business-dates (midnight grace), DST-aware через `Intl.DateTimeFormat.formatToParts`.

**Tech Stack:** Node.js 18+ (`node:test` runner, `node:assert/strict`), `pg` 8.x, PostgreSQL 13+ partial unique indexes.

**Reference:** Design spec `docs/superpowers/specs/2026-05-07-scheduler-uniqueness-pickup-design.md` (revision v3, post-Codex).

**Plan revisions:** v1 — Codex review поднял 5 BLOCKER + 7 IMPORTANT (ordering, placeholders, deadlock в I12a, content_status в I8, ON CONFLICT predicate, схемы фикстур, refactor risk, start/stop race, settings pollution). v2 (этот документ) применяет все.

---

## File Structure

| Файл | Action | Ответственность |
|---|---|---|
| `autowarm/scripts/audit_unic_tasks_duplicates.sql` | CREATE | Read-only отчёт по дублям (pre-migration check) |
| `autowarm/migrations/20260507_unic_tasks_unique_active_slot.sql` | CREATE | `CREATE UNIQUE INDEX CONCURRENTLY ... WHERE ...` |
| `autowarm/migrations/20260507_unic_tasks_unique_active_slot__rollback.sql` | CREATE | `DROP INDEX CONCURRENTLY ux_unic_tasks_active_slot;` |
| `autowarm/unic_sweep.js` | CREATE | Чистый модуль: `computeBusinessDate`, `computeBusinessDateWindow`, `runScheduledUnicSweep`, `start`, `stop`. Все deps через DI. |
| `autowarm/unic_sweep.test.js` | CREATE | `node --test`: unit-тесты date-helpers + sweep-loop логики (моки pool/runAutoUnicForDate) |
| `autowarm/run_auto_unic.js` | CREATE | DI-фабрика для runAutoUnicForDate (извлечена из server.js, добавлен ON CONFLICT + return counts) |
| `autowarm/tests/test_unic_sweep_integration.test.js` | CREATE | `node --test`: integration против реальной testbench-БД (eligibility, idempotency, midnight, race) |
| `autowarm/server.js` | MODIFY (line 5355–5481, ~5557) | Заменить inline runAutoUnicForDate на require, добавить sweep startup |

---

## Task 0: Pre-flight

- [ ] **Step 0.1: Зайти в рабочую директорию + git fetch**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git status
git log --oneline -5
```

Expected: clean tree.

- [ ] **Step 0.2: Создать ветку**

```bash
git checkout -b feature/unic-sweep-2026-05-07
```

- [ ] **Step 0.3: Smoke pgsql + node**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "SELECT version();" | head -3
node --version
```

Expected: PG ≥ 13, Node ≥ 18.

- [ ] **Step 0.4: Pre-flight grep — какие closure'ы захватывает текущая `runAutoUnicForDate` (важно для безопасного refactor в Task 5)**

```bash
sed -n '5355,5481p' server.js | grep -oE "[a-zA-Z_][a-zA-Z0-9_]*" | sort -u | head -40
```

Зафиксировать список. Ожидаемые внешние имена: `pool`, `console`, `JSON`, `NOW`, `Math`, `Number`, `String`, плюс параметры `slotDate`/`settings`. Если есть что-то ещё (helper-функция, env-var, метрика-коллектор) — STOP, добавить в DI factory.

- [ ] **Step 0.5: Verify schemas таблиц для test-фикстур**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -c "\d validator_content" -c "\d validator_schedule_slots" \
  -c "\d factory_pack_accounts" -c "\d unic_schemes" \
  -c "\d validator_scheme_preferences" -c "\d unic_settings" \
  > /tmp/unic-sweep-schemas.txt
cat /tmp/unic-sweep-schemas.txt
```

Зафиксировать (для Task 7):
- Какие колонки NOT NULL без DEFAULT в `validator_content`?
- Есть ли FK constraint на `factory_pack_accounts.project_id → factory_projects.id`?
- Есть ли UNIQUE на `validator_scheme_preferences (project_id, scheme_id)`?
- `validator_content.id` — SERIAL/BIGSERIAL? Если да, можем ли мы вставить отрицательный id?

Если из инспекции видно что **FK блокирует** наш `project_id=-101` (т.е. `factory_projects` не имеет такой строки) — STOP, спросить пользователя как лучше: создавать row в factory_projects(-101) или использовать существующий тест-проект.

---

## Task 1: Audit script (read-only)

**Files:** Create `autowarm/scripts/audit_unic_tasks_duplicates.sql`

- [ ] **Step 1.1: Создать директорию scripts**

```bash
mkdir -p /home/claude-user/autowarm-testbench/scripts
```

- [ ] **Step 1.2: Написать audit-скрипт**

`autowarm/scripts/audit_unic_tasks_duplicates.sql`:

```sql
-- Read-only audit: ищем дубли (content_id, slot_date) среди живых задач.
-- Запускать ПЕРЕД миграцией. Если возвращает строки — миграцию НЕ применять
-- до ручного резолва дублей (см. design doc § Migration safety).

SELECT content_id,
       slot_date,
       COUNT(*) AS dup_count,
       array_agg(id ORDER BY id) AS task_ids,
       array_agg(current_status ORDER BY id) AS statuses,
       array_agg(created_at ORDER BY id) AS created_ats
FROM unic_tasks
WHERE content_id IS NOT NULL
  AND slot_date IS NOT NULL
  AND current_status IN ('pending', 'processing', 'done')
GROUP BY content_id, slot_date
HAVING COUNT(*) > 1
ORDER BY content_id, slot_date;
```

- [ ] **Step 1.3: Запустить на dev**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f scripts/audit_unic_tasks_duplicates.sql
```

Expected: `(0 rows)`. Если есть строки — записать в evidence-файл, спросить пользователя.

- [ ] **Step 1.4: Commit**

```bash
git add scripts/audit_unic_tasks_duplicates.sql
git commit -m "feat(unic): read-only audit script for unic_tasks duplicate detection"
```

---

## Task 2: Migration files

**Files:** Create migration up + rollback.

- [ ] **Step 2.1: Up-миграция**

`autowarm/migrations/20260507_unic_tasks_unique_active_slot.sql`:

```sql
-- ВАЖНО: запускать НАПРЯМУЮ через psql, без транзакционной обёртки.
-- CREATE INDEX CONCURRENTLY запрещён внутри tx.
-- Pre-flight: scripts/audit_unic_tasks_duplicates.sql должен вернуть 0 строк.

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ux_unic_tasks_active_slot
  ON unic_tasks (content_id, slot_date)
  WHERE current_status IN ('pending', 'processing', 'done')
    AND content_id IS NOT NULL
    AND slot_date IS NOT NULL;
```

- [ ] **Step 2.2: Rollback**

`autowarm/migrations/20260507_unic_tasks_unique_active_slot__rollback.sql`:

```sql
DROP INDEX CONCURRENTLY IF EXISTS ux_unic_tasks_active_slot;
```

- [ ] **Step 2.3: Apply on dev**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f migrations/20260507_unic_tasks_unique_active_slot.sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d unic_tasks" | grep ux_unic_tasks
```

Expected: `"ux_unic_tasks_active_slot" UNIQUE, btree (content_id, slot_date) WHERE current_status = ANY (ARRAY['pending'::text, 'processing'::text, 'done'::text]) AND content_id IS NOT NULL AND slot_date IS NOT NULL`

- [ ] **Step 2.4: ON CONFLICT smoke (predicate matches index)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
DELETE FROM unic_tasks WHERE content_id = -1;
INSERT INTO unic_tasks (content_id, slot_date, current_status, created_at, updated_at)
  VALUES (-1, '2099-01-01', 'pending', NOW(), NOW());

INSERT INTO unic_tasks (content_id, slot_date, current_status, created_at, updated_at)
VALUES (-1, '2099-01-01', 'pending', NOW(), NOW())
ON CONFLICT (content_id, slot_date)
WHERE current_status IN ('pending', 'processing', 'done')
  AND content_id IS NOT NULL
  AND slot_date IS NOT NULL
DO NOTHING;

SELECT COUNT(*) AS n FROM unic_tasks WHERE content_id = -1;
DELETE FROM unic_tasks WHERE content_id = -1;
SQL
```

Expected: `n = 1`. Если ошибка `there is no unique or exclusion constraint matching the ON CONFLICT specification` — STOP, проверить что предикат INSERT'a IDENTICAL предикату индекса (включая `IS NOT NULL` оба).

- [ ] **Step 2.5: Rollback smoke**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f migrations/20260507_unic_tasks_unique_active_slot__rollback.sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d unic_tasks" | grep ux_unic_tasks || echo "rollback ok"
```

Expected: `rollback ok`.

- [ ] **Step 2.6: Re-apply (оставляем индекс для последующих тестов)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f migrations/20260507_unic_tasks_unique_active_slot.sql
```

- [ ] **Step 2.7: Commit**

```bash
git add migrations/20260507_unic_tasks_unique_active_slot.sql migrations/20260507_unic_tasks_unique_active_slot__rollback.sql
git commit -m "feat(unic): partial unique index on unic_tasks(content_id, slot_date)

Prevents race-condition duplicates between trigger-immediate and
the upcoming sweep loop. Partial: only enforces while task is alive
(pending/processing/done); error tasks can be re-enqueued."
```

---

## Task 3: Date helpers in `unic_sweep.js` (TDD)

**Files:** Create `autowarm/unic_sweep.js`, `autowarm/unic_sweep.test.js`.

- [ ] **Step 3.1: Failing tests**

`autowarm/unic_sweep.test.js`:

```javascript
// node --test unic_sweep.test.js
'use strict';

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { computeBusinessDate, computeBusinessDateWindow } = require('./unic_sweep');

describe('computeBusinessDate', () => {
  test('Asia/Dubai at 2026-05-07T20:30:00Z returns 2026-05-08', () => {
    const t = new Date('2026-05-07T20:30:00Z').getTime();
    assert.equal(computeBusinessDate('Asia/Dubai', t), '2026-05-08');
  });

  test('UTC at 2026-05-07T20:30:00Z returns 2026-05-07', () => {
    const t = new Date('2026-05-07T20:30:00Z').getTime();
    assert.equal(computeBusinessDate('UTC', t), '2026-05-07');
  });

  test('America/New_York DST-aware: May (EDT, UTC-4) at 03:00Z returns 2026-05-06', () => {
    const t = new Date('2026-05-07T03:00:00Z').getTime();
    assert.equal(computeBusinessDate('America/New_York', t), '2026-05-06');
  });

  test('America/New_York DST-aware: January (EST, UTC-5) at 03:00Z returns 2026-01-06', () => {
    const t = new Date('2026-01-07T03:00:00Z').getTime();
    assert.equal(computeBusinessDate('America/New_York', t), '2026-01-06');
  });

  test('Europe/London DST-aware: May (BST, UTC+1) at 23:30Z returns next day', () => {
    const t = new Date('2026-05-07T23:30:00Z').getTime();
    assert.equal(computeBusinessDate('Europe/London', t), '2026-05-08');
  });

  test('null timezone falls back to Asia/Dubai', () => {
    const t = new Date('2026-05-07T20:30:00Z').getTime();
    assert.equal(computeBusinessDate(null, t), '2026-05-08');
  });

  test('invalid timezone falls back to Asia/Dubai with error log', () => {
    const t = new Date('2026-05-07T20:30:00Z').getTime();
    const errs = [];
    const origErr = console.error;
    console.error = (m) => errs.push(m);
    try {
      assert.equal(computeBusinessDate('Mars/Olympus', t), '2026-05-08');
      assert.ok(errs.length >= 1, 'expected at least one error log');
      assert.match(errs[0], /unknown timezone/i);
    } finally {
      console.error = origErr;
    }
  });
});

describe('computeBusinessDateWindow', () => {
  test('returns [today, yesterday]', () => {
    const t = new Date('2026-05-07T08:00:00Z').getTime();
    const [today, yesterday] = computeBusinessDateWindow('Asia/Dubai', t);
    assert.equal(today, '2026-05-07');
    assert.equal(yesterday, '2026-05-06');
  });

  test('handles month boundary', () => {
    const t = new Date('2026-05-01T05:00:00Z').getTime();
    const [today, yesterday] = computeBusinessDateWindow('Asia/Dubai', t);
    assert.equal(today, '2026-05-01');
    assert.equal(yesterday, '2026-04-30');
  });
});
```

- [ ] **Step 3.2: Run — должны упасть**

```bash
cd /home/claude-user/autowarm-testbench
node --test unic_sweep.test.js 2>&1 | tail -10
```

Expected: FAIL — `Cannot find module './unic_sweep'`.

- [ ] **Step 3.3: Минимальная реализация**

`autowarm/unic_sweep.js` (только date-helpers; sweep-loop в Task 4):

```javascript
'use strict';

function _formatYmd(timezone, time) {
  // formatToParts даёт детерминированное YYYY-MM-DD без зависимости от 'en-CA' quirks
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric', month: '2-digit', day: '2-digit',
  });
  const parts = fmt.formatToParts(new Date(time));
  const m = {};
  for (const p of parts) m[p.type] = p.value;
  return `${m.year}-${m.month}-${m.day}`;
}

function computeBusinessDate(timezone, baseTime) {
  const t = (baseTime !== undefined && baseTime !== null) ? baseTime : Date.now();
  const tz = timezone || 'Asia/Dubai';
  try {
    return _formatYmd(tz, t);
  } catch (e) {
    console.error(JSON.stringify({
      tag: 'unic-sweep', ok: false,
      error: `unknown timezone '${tz}', falling back to Asia/Dubai (${e.message})`,
    }));
    return _formatYmd('Asia/Dubai', t);
  }
}

function computeBusinessDateWindow(timezone, baseTime) {
  const t = (baseTime !== undefined && baseTime !== null) ? baseTime : Date.now();
  const today = computeBusinessDate(timezone, t);
  const yesterday = computeBusinessDate(timezone, t - 24 * 3600 * 1000);
  return [today, yesterday];
}

module.exports = { computeBusinessDate, computeBusinessDateWindow };
```

- [ ] **Step 3.4: Run — должны пройти**

```bash
node --test unic_sweep.test.js 2>&1 | tail -10
```

Expected: `# fail: 0`.

- [ ] **Step 3.5: Commit**

```bash
git add unic_sweep.js unic_sweep.test.js
git commit -m "feat(unic): DST-aware business-date helpers in unic_sweep module

formatToParts implementation — robust across ICU builds. computeBusinessDateWindow returns [today, yesterday] for midnight grace-window."
```

---

## Task 4: Sweep loop в `unic_sweep.js` (TDD)

**Files:** Modify both files.

- [ ] **Step 4.1: Failing tests (дописать к unic_sweep.test.js)**

```javascript
describe('runScheduledUnicSweep', () => {
  function fakePool(settingsRow = { id: 1, timezone: 'Asia/Dubai' }) {
    return {
      query: async (sql) => /unic_settings/.test(sql) ? { rows: [settingsRow] } : { rows: [] },
    };
  }

  test('calls runAutoUnicForDate twice — for today and yesterday', async () => {
    const { runScheduledUnicSweep } = require('./unic_sweep');
    const calls = [];
    const fakeRun = async (date) => { calls.push(date); return { inserted: 0, skipped: 0, errors: 0 }; };
    const t = new Date('2026-05-07T08:00:00Z').getTime();
    await runScheduledUnicSweep({
      pool: fakePool(), runAutoUnicForDate: fakeRun, now: () => t,
      state: { running: false, timer: null, stopped: false },
    });
    assert.deepEqual(calls, ['2026-05-07', '2026-05-06']);
  });

  test('skips if previous tick still running', async () => {
    const { runScheduledUnicSweep } = require('./unic_sweep');
    let runCalls = 0;
    const fakeRun = async () => { runCalls++; return { inserted: 0, skipped: 0, errors: 0 }; };
    const state = { running: true, timer: null, stopped: false };
    const t = new Date('2026-05-07T08:00:00Z').getTime();
    await runScheduledUnicSweep({ pool: fakePool(), runAutoUnicForDate: fakeRun, now: () => t, state });
    assert.equal(runCalls, 0);
  });

  test('logs error JSON and resets running guard on exception', async () => {
    const { runScheduledUnicSweep } = require('./unic_sweep');
    const fakeRun = async () => { throw new Error('boom'); };
    const errs = [];
    const origErr = console.error;
    console.error = (m) => errs.push(m);
    const state = { running: false, timer: null, stopped: false };
    try {
      await runScheduledUnicSweep({
        pool: fakePool(), runAutoUnicForDate: fakeRun,
        now: () => new Date('2026-05-07T08:00:00Z').getTime(), state,
      });
    } finally { console.error = origErr; }
    assert.equal(state.running, false);
    assert.ok(errs.some(m => /boom/.test(m) && /unic-sweep/.test(m)));
  });

  test('returns aggregated counts {target_dates, total_inserted}', async () => {
    const { runScheduledUnicSweep } = require('./unic_sweep');
    const fakeRun = async (date) => ({
      inserted: date === '2026-05-07' ? 3 : 1, skipped: 0, errors: 0,
    });
    const t = new Date('2026-05-07T08:00:00Z').getTime();
    const result = await runScheduledUnicSweep({
      pool: fakePool(), runAutoUnicForDate: fakeRun, now: () => t,
      state: { running: false, timer: null, stopped: false },
    });
    assert.equal(result.total_inserted, 4);
    assert.deepEqual(result.target_dates, ['2026-05-07', '2026-05-06']);
  });
});

describe('start/stop loop', () => {
  test('start schedules a timer, stop clears it and sets stopped=true', () => {
    const { start, stop } = require('./unic_sweep');
    const state = { running: false, timer: null, stopped: false };
    start({
      pool: { query: async () => ({ rows: [{ timezone: 'UTC' }] }) },
      runAutoUnicForDate: async () => ({ inserted: 0, skipped: 0, errors: 0 }),
      state, initialDelayMs: 50_000, intervalMs: 60_000,
    });
    assert.ok(state.timer !== null);
    stop({ state });
    assert.equal(state.timer, null);
    assert.equal(state.stopped, true);
  });

  test('start is idempotent (second call no-op if timer exists)', () => {
    const { start, stop } = require('./unic_sweep');
    const state = { running: false, timer: null, stopped: false };
    const opts = {
      pool: { query: async () => ({ rows: [{}] }) },
      runAutoUnicForDate: async () => ({ inserted: 0, skipped: 0, errors: 0 }),
      state, initialDelayMs: 50_000, intervalMs: 60_000,
    };
    start(opts);
    const firstTimer = state.timer;
    start(opts);
    assert.equal(state.timer, firstTimer);
    stop({ state });
  });
});
```

- [ ] **Step 4.2: Run — должны упасть (`is not a function`)**

```bash
node --test unic_sweep.test.js 2>&1 | tail -10
```

- [ ] **Step 4.3: Дописать sweep-loop в `unic_sweep.js`**

В конце файла добавить (и заменить старый `module.exports`):

```javascript
async function runScheduledUnicSweep({
  pool, runAutoUnicForDate,
  now = Date.now,
  state = { running: false, timer: null, stopped: false },
}) {
  if (state.running) {
    console.warn(JSON.stringify({
      tag: 'unic-sweep', ok: true, skipped: true,
      reason: 'previous tick still running',
    }));
    return { skipped: true, target_dates: [], total_inserted: 0 };
  }
  state.running = true;
  const t0 = now();
  let target_dates = [];
  let total_inserted = 0;
  try {
    const { rows } = await pool.query('SELECT * FROM unic_settings WHERE id=1');
    const settings = rows[0] || {};
    target_dates = computeBusinessDateWindow(settings.timezone, now());
    for (const date of target_dates) {
      const r = await runAutoUnicForDate(date, settings);
      total_inserted += r.inserted;
      console.log(JSON.stringify({
        tag: 'unic-sweep', ok: true,
        target_date: date,
        inserted: r.inserted, skipped: r.skipped, errors: r.errors,
      }));
    }
    console.log(JSON.stringify({
      tag: 'unic-sweep', ok: true, summary: true,
      target_dates, total_inserted, took_ms: now() - t0,
    }));
    return { skipped: false, target_dates, total_inserted };
  } catch (e) {
    console.error(JSON.stringify({
      tag: 'unic-sweep', ok: false,
      target_dates, error: e.message, took_ms: now() - t0,
    }));
    return { skipped: false, target_dates, total_inserted: 0, error: e.message };
  } finally {
    state.running = false;
  }
}

const DEFAULT_INTERVAL_MS = 5 * 60 * 1000;
const DEFAULT_INITIAL_DELAY_MS = 30 * 1000;

function start({
  pool, runAutoUnicForDate,
  state = { running: false, timer: null, stopped: false },
  initialDelayMs = DEFAULT_INITIAL_DELAY_MS,
  intervalMs = DEFAULT_INTERVAL_MS,
  now = Date.now,
}) {
  if (state.timer) return state;
  state.stopped = false;
  const tick = async () => {
    try {
      await runScheduledUnicSweep({ pool, runAutoUnicForDate, now, state });
    } catch (e) {
      console.error(JSON.stringify({
        tag: 'unic-sweep', ok: false,
        error: `unhandled in tick: ${e.message}`,
      }));
    }
    // Защита от race: если stop() вызвали во время длинного tick'a — не планируем следующий
    if (state.stopped) {
      state.timer = null;
      return;
    }
    state.timer = setTimeout(tick, intervalMs);
  };
  state.timer = setTimeout(tick, initialDelayMs);
  return state;
}

function stop({ state }) {
  if (!state) return;
  state.stopped = true;
  if (state.timer) {
    clearTimeout(state.timer);
    state.timer = null;
  }
}

module.exports = {
  computeBusinessDate, computeBusinessDateWindow,
  runScheduledUnicSweep, start, stop,
};
```

- [ ] **Step 4.4: Run — должны пройти все**

```bash
node --test unic_sweep.test.js 2>&1 | tail -15
```

Expected: `# fail: 0`.

- [ ] **Step 4.5: Commit**

```bash
git add unic_sweep.js unic_sweep.test.js
git commit -m "feat(unic): self-scheduling sweep loop with stopped-flag race protection

runScheduledUnicSweep iterates [today, yesterday] for midnight grace,
re-entrancy guard via shared state, structured JSON logs.
start/stop: stopped-flag prevents tick from re-scheduling after stop()
called mid-tick. All deps via DI."
```

---

## Task 5: Extract `runAutoUnicForDate` → `run_auto_unic.js` + ON CONFLICT + return counts

Combined: refactor + behavior change в одном task'e.

**Files:** Create `autowarm/run_auto_unic.js`. Modify `autowarm/server.js` (line 5355–5481).

- [ ] **Step 5.1: Прочитать текущий `runAutoUnicForDate`**

```bash
sed -n '5355,5485p' /home/claude-user/autowarm-testbench/server.js
```

Зафиксировать конец функции (последний `}` перед `async function triggerAutoUnicForced`).

- [ ] **Step 5.2: Создать `autowarm/run_auto_unic.js`**

`autowarm/run_auto_unic.js`:

```javascript
'use strict';

/**
 * DI factory: возвращает runAutoUnicForDate замкнутый на {pool}.
 *
 * Поведение идентично прежней inline-версии в server.js, плюс:
 *   1. INSERT теперь использует ON CONFLICT DO NOTHING (см. migration
 *      20260507_unic_tasks_unique_active_slot — partial unique index).
 *   2. Возвращает { inserted, skipped, errors } для structured logging.
 *
 * Существующие callers (trigger-immediate, triggerAutoUnic, triggerAutoUnicForced)
 * НЕ читают return value, так что добавление structured-output не ломает их.
 */
function makeRunAutoUnicForDate({ pool }) {
  return async function runAutoUnicForDate(slotDate, settings) {
    let inserted = 0, skipped = 0, errors = 0;

    const { rows: slots } = await pool.query(`
      SELECT
      s.id     AS slot_id,
      c.id     AS content_id,
      c.s3_url,
      c.project_id,
      c.title
      FROM validator_schedule_slots s
      JOIN validator_content c ON c.id = s.content_id
      WHERE s.slot_date = $1
      AND s.status = 'filled'
      AND c.status = 'approved'
      AND c.moderation_status = 'passed'
      AND NOT EXISTS (
        SELECT 1 FROM unic_tasks ut
        WHERE ut.content_id = c.id
        AND ut.slot_date = $1
        AND ut.current_status IN ('pending','processing','done')
      )
    `, [slotDate]);

    if (!slots.length) {
      console.log(`[auto-unic] Нет слотов для уникализации на ${slotDate}`);
      return { inserted, skipped, errors };
    }

    for (const slot of slots) {
      try {
        const { rows: packs } = await pool.query(
          `SELECT id, pack_name FROM factory_pack_accounts WHERE project_id = $1 ORDER BY id ASC`,
          [slot.project_id]
        );
        if (!packs.length) {
          console.log(`[auto-unic] Нет паков для проекта ${slot.project_id}, пропускаем slot=${slot.slot_id}`);
          skipped++; continue;
        }

        const { rows: approvedSchemes } = await pool.query(
          `SELECT sp.scheme_id AS id FROM validator_scheme_preferences sp
           JOIN unic_schemes us ON us.id = sp.scheme_id AND us.status = true
           WHERE sp.project_id = $1 AND sp.status = 'approved'
           ORDER BY sp.scheme_id ASC`,
          [slot.project_id]
        );
        if (!approvedSchemes.length) {
          console.log(`[auto-unic] ⚠️ Нет одобренных схем для проекта ${slot.project_id}, пропускаем slot=${slot.slot_id}`);
          skipped++; continue;
        }
        if (approvedSchemes.length < packs.length) {
          console.log(`[auto-unic] ⚠️ Одобрено ${approvedSchemes.length} схем, но паков ${packs.length} у проекта ${slot.project_id}. Пропускаем slot=${slot.slot_id}`);
          skipped++; continue;
        }

        let selectedSchemes;
        if (approvedSchemes.length === packs.length) {
          selectedSchemes = approvedSchemes;
        } else {
          const { rows: lastTask } = await pool.query(
            `SELECT schemes FROM unic_tasks WHERE project_id = $1 AND current_status IN ('pending','processing','done')
             ORDER BY id DESC LIMIT 1`,
            [slot.project_id]
          );
          let offset = 0;
          if (lastTask.length && lastTask[0].schemes) {
            const lastSchemeIds = lastTask[0].schemes.split(',').map(Number).filter(Boolean);
            const lastMax = Math.max(...lastSchemeIds);
            const lastIdx = approvedSchemes.findIndex(s => s.id === lastMax);
            if (lastIdx >= 0) offset = lastIdx + 1;
          }
          selectedSchemes = [];
          for (let i = 0; i < packs.length; i++) {
            selectedSchemes.push(approvedSchemes[(offset + i) % approvedSchemes.length]);
          }
        }

        const packSchemeMap = {};
        selectedSchemes.forEach((scheme, i) => {
          if (packs[i]) packSchemeMap[String(scheme.id)] = packs[i].id;
        });

        const schemeIds = selectedSchemes.map(s => s.id).join(',');
        const projectName = packs[0]?.pack_name?.replace(/_\d+$/, '') || null;

        const meta = {
          source: 'auto_unic',
          slot_id: slot.slot_id,
          pack_scheme_map: packSchemeMap,
        };

        const insertResult = await pool.query(`
          INSERT INTO unic_tasks
            (input_video_url, input_video_name, project_name, schemes, schemes_total,
             current_status, project_id, content_id, slot_date, meta, created_at, updated_at)
          VALUES ($1,$2,$3,$4,$5,'pending',$6,$7,$8,$9,NOW(),NOW())
          ON CONFLICT (content_id, slot_date)
          WHERE current_status IN ('pending','processing','done')
            AND content_id IS NOT NULL
            AND slot_date IS NOT NULL
          DO NOTHING
          RETURNING id
        `, [
          slot.s3_url,
          slot.title,
          projectName,
          schemeIds,
          selectedSchemes.length,
          slot.project_id,
          slot.content_id,
          slotDate,
          JSON.stringify(meta),
        ]);

        if (insertResult.rowCount > 0) {
          await pool.query(
            `UPDATE validator_content SET status='in_uniqualization', unic_queued_at=NOW(), updated_at=NOW() WHERE id=$1`,
            [slot.content_id]
          );
          console.log(`[auto-unic] ✅ task created: slot=${slot.slot_id} content=${slot.content_id} schemes=${selectedSchemes.length}/${approvedSchemes.length} approved, packs=${packs.length} map=${JSON.stringify(packSchemeMap)}`);
          inserted++;
        } else {
          console.log(JSON.stringify({
            tag: 'auto-unic', skipped: true, reason: 'race-conflict',
            slot_id: slot.slot_id, content_id: slot.content_id, slot_date: slotDate,
          }));
          skipped++;
        }
      } catch (e) {
        console.error(JSON.stringify({
          tag: 'auto-unic', ok: false,
          slot_id: slot.slot_id, content_id: slot.content_id, slot_date: slotDate,
          error: e.message,
        }));
        errors++;
      }
    }

    return { inserted, skipped, errors };
  };
}

module.exports = { makeRunAutoUnicForDate };
```

- [ ] **Step 5.3: Удалить inline-функцию из `server.js`, заменить на require**

В `server.js`:
- найти `async function runAutoUnicForDate(slotDate, settings) {` (line ~5355);
- удалить **весь** блок до закрывающей `}` на line ~5481;
- на освободившемся месте вставить:

```javascript
const { makeRunAutoUnicForDate } = require('./run_auto_unic');
const runAutoUnicForDate = makeRunAutoUnicForDate({ pool });
```

- [ ] **Step 5.4: Verify единственный INSERT в `unic_tasks`**

```bash
cd /home/claude-user/autowarm-testbench
grep -nE "INSERT INTO unic_tasks" server.js
```

Expected: 0 hits в server.js.

```bash
grep -nE "INSERT INTO unic_tasks" run_auto_unic.js
```

Expected: 1 hit в run_auto_unic.js. Если в server.js остались — добавить им ON CONFLICT тем же синтаксисом.

- [ ] **Step 5.5: Smoke**

```bash
node -c server.js && echo "syntax OK"
grep -nE "runAutoUnicForDate" server.js
```

Expected: 4 hit'a (1 declaration через makeRun..., 3 calling sites).

```bash
timeout 5 node server.js 2>&1 | head -20 | grep -iE "error|undefined" || echo "(no errors in 5s)"
```

Expected: никаких `ReferenceError`.

- [ ] **Step 5.6: Commit**

```bash
git add run_auto_unic.js server.js
git commit -m "feat(unic): extract runAutoUnicForDate + add ON CONFLICT + return counts

makeRunAutoUnicForDate({pool}) DI factory. INSERT INTO unic_tasks
gets ON CONFLICT (content_id, slot_date) WHERE current_status IN
(pending/processing/done) AND content_id IS NOT NULL AND slot_date
IS NOT NULL DO NOTHING — predicate matches partial unique index
ux_unic_tasks_active_slot exactly.

Function returns {inserted, skipped, errors}. Existing call sites
ignore return value, so no behavior change for them."
```

---

## Task 6: Wire sweep loop в `server.js`

**Files:** Modify `autowarm/server.js`.

- [ ] **Step 6.1: Найти место**

```bash
grep -n "setInterval(triggerAutoUnic\|каждые 30 минут" server.js | head -5
```

Expected: line ~5551–5555.

- [ ] **Step 6.2: Добавить require + start**

Сразу **после** `setInterval(... triggerAutoUnic ..., 30 * 60 * 1000);`:

```javascript
// ===== UNIC SWEEP: continuous safety net каждые 5 минут =====
const unicSweep = require('./unic_sweep');
const unicSweepState = { running: false, timer: null, stopped: false };

if (process.env.NODE_ENV !== 'test' && process.env.UNIC_SWEEP_DISABLED !== '1') {
  unicSweep.start({
    pool, runAutoUnicForDate, state: unicSweepState,
  });
  console.log('[unic-sweep] loop started (5min interval, 30s initial delay)');
}
```

- [ ] **Step 6.3: Smoke**

```bash
node -c server.js && echo "OK"
```

- [ ] **Step 6.4: Live tick smoke**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
DELETE FROM unic_tasks WHERE content_id = -1099;
DELETE FROM validator_schedule_slots WHERE content_id = -1099;
DELETE FROM validator_content WHERE id = -1099;
INSERT INTO validator_content (id, project_id, status, moderation_status, s3_url, title, created_at, updated_at)
  VALUES (-1099, -101, 'approved', 'passed', 's3://test/smoke.mp4', 'smoke', NOW(), NOW())
  ON CONFLICT (id) DO UPDATE SET status='approved', moderation_status='passed';
INSERT INTO validator_schedule_slots (content_id, slot_date, status, project_id)
  VALUES (-1099, CURRENT_DATE, 'filled', -101);
INSERT INTO factory_pack_accounts (id, project_id, pack_name) VALUES (-201, -101, 'smoke_pack')
  ON CONFLICT (id) DO NOTHING;
INSERT INTO unic_schemes (id, status) VALUES (-1, true) ON CONFLICT (id) DO UPDATE SET status=true;
INSERT INTO validator_scheme_preferences (project_id, scheme_id, status) VALUES (-101, -1, 'approved')
  ON CONFLICT (project_id, scheme_id) DO UPDATE SET status='approved';
SQL

timeout 50 node server.js 2>&1 | grep -iE "unic-sweep|auto-unic" | head -10
```

Expected:
- `[unic-sweep] loop started ...`
- через ~30с — JSON-tick `{"tag":"unic-sweep",...,"target_date":"...","inserted":1,...}`
- и `[auto-unic] ✅ task created: ... content=-1099`

Если фикстуры не работают (FK error) — STOP, разобраться.

- [ ] **Step 6.5: Cleanup**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
DELETE FROM unic_tasks WHERE content_id = -1099;
DELETE FROM validator_schedule_slots WHERE content_id = -1099;
DELETE FROM validator_content WHERE id = -1099;
SQL
```

- [ ] **Step 6.6: Commit**

```bash
git add server.js
git commit -m "feat(unic): wire 5-minute sweep loop in server.js startup

Loads ./unic_sweep, starts loop unless NODE_ENV=test or
UNIC_SWEEP_DISABLED=1."
```

---

## Task 7: Integration tests — fixture + I1, I2

**Files:** Create `autowarm/tests/test_unic_sweep_integration.test.js`.

- [ ] **Step 7.1: Создать тест-файл с helpers + I1 + I2**

`autowarm/tests/test_unic_sweep_integration.test.js`:

```javascript
// node --test tests/test_unic_sweep_integration.test.js
'use strict';

const { test, describe, before, after, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const { Pool, Client } = require('pg');
const { runScheduledUnicSweep } = require('../unic_sweep');
const { makeRunAutoUnicForDate } = require('../run_auto_unic');

const DB_URL = 'postgres://openclaw:openclaw123@localhost:5432/openclaw';

let pool;
let runAutoUnicForDate;
let originalSettings;

const FIX_CONTENT_ID = -1001;
const FIX_PROJECT_ID = -101;
const FIX_PACK_ID = -201;
const FIX_SCHEME_ID = -1;

before(async () => {
  pool = new Pool({ connectionString: DB_URL, max: 4 });
  runAutoUnicForDate = makeRunAutoUnicForDate({ pool });
  const { rows } = await pool.query('SELECT * FROM unic_settings WHERE id=1');
  originalSettings = rows[0] || null;
});

after(async () => {
  if (originalSettings) {
    await pool.query(
      `UPDATE unic_settings SET timezone=$1, publish_start=$2 WHERE id=1`,
      [originalSettings.timezone, originalSettings.publish_start]
    );
  }
  await pool.end();
});

async function cleanupFixtures() {
  await pool.query('DELETE FROM unic_tasks WHERE content_id <= -1000');
  await pool.query('DELETE FROM validator_schedule_slots WHERE content_id <= -1000');
  await pool.query('DELETE FROM validator_content WHERE id <= -1000');
  await pool.query('DELETE FROM factory_pack_accounts WHERE id <= -200 AND id >= -210');
  await pool.query('DELETE FROM validator_scheme_preferences WHERE project_id = $1', [FIX_PROJECT_ID]);
  await pool.query('DELETE FROM unic_schemes WHERE id <= -1');
}

async function seedEligible({
  contentId = FIX_CONTENT_ID,
  projectId = FIX_PROJECT_ID,
  slotDate,
  contentStatus = 'approved',
  moderationStatus = 'passed',
  slotStatus = 'filled',
} = {}) {
  await pool.query(`
    INSERT INTO validator_content (id, project_id, status, moderation_status, s3_url, title, created_at, updated_at)
    VALUES ($1, $2, $3, $4, 's3://test/x.mp4', 'fixture', NOW(), NOW())
    ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, moderation_status=EXCLUDED.moderation_status
  `, [contentId, projectId, contentStatus, moderationStatus]);

  await pool.query(`
    INSERT INTO validator_schedule_slots (content_id, slot_date, status, project_id)
    VALUES ($1, $2, $3, $4)
  `, [contentId, slotDate, slotStatus, projectId]);

  await pool.query(`
    INSERT INTO factory_pack_accounts (id, project_id, pack_name)
    VALUES ($1, $2, 'fixture_pack_1')
    ON CONFLICT (id) DO NOTHING
  `, [FIX_PACK_ID, projectId]);

  await pool.query(`
    INSERT INTO unic_schemes (id, status) VALUES ($1, true)
    ON CONFLICT (id) DO UPDATE SET status = true
  `, [FIX_SCHEME_ID]);

  await pool.query(`
    INSERT INTO validator_scheme_preferences (project_id, scheme_id, status)
    VALUES ($1, $2, 'approved')
    ON CONFLICT (project_id, scheme_id) DO UPDATE SET status = 'approved'
  `, [projectId, FIX_SCHEME_ID]);
}

beforeEach(async () => {
  await cleanupFixtures();
});

describe('integration: sweep eligibility', () => {
  test('I1 — single eligible slot today → enqueued', async () => {
    const today = '2026-05-07';
    await seedEligible({ slotDate: today });
    await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
    const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();

    await runScheduledUnicSweep({
      pool, runAutoUnicForDate, now: fakeNow,
      state: { running: false, timer: null, stopped: false },
    });

    const { rows } = await pool.query(
      `SELECT id, current_status, slot_date FROM unic_tasks WHERE content_id=$1`,
      [FIX_CONTENT_ID]
    );
    assert.equal(rows.length, 1);
    assert.equal(rows[0].current_status, 'pending');
    assert.equal(rows[0].slot_date.toISOString().slice(0, 10), today);

    const { rows: cont } = await pool.query(
      `SELECT status FROM validator_content WHERE id=$1`, [FIX_CONTENT_ID]
    );
    assert.equal(cont[0].status, 'in_uniqualization');
  });

  test('I2 — pre-existing pending task → no duplicate', async () => {
    const today = '2026-05-07';
    await seedEligible({ slotDate: today });
    await pool.query(`
      INSERT INTO unic_tasks (content_id, slot_date, current_status, project_id, created_at, updated_at)
      VALUES ($1, $2, 'pending', $3, NOW(), NOW())
    `, [FIX_CONTENT_ID, today, FIX_PROJECT_ID]);
    await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
    const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();

    await runScheduledUnicSweep({
      pool, runAutoUnicForDate, now: fakeNow,
      state: { running: false, timer: null, stopped: false },
    });

    const { rows } = await pool.query(
      `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2`,
      [FIX_CONTENT_ID, today]
    );
    assert.equal(rows[0].n, 1);
  });
});
```

- [ ] **Step 7.2: Run I1 + I2**

```bash
cd /home/claude-user/autowarm-testbench
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -20
```

Expected: 2 tests pass. Если падает с FK или required-column ошибкой — вернуться к Step 0.5, починить fixture.

- [ ] **Step 7.3: Commit**

```bash
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): integration test scaffold + I1 + I2"
```

---

## Task 8: I3-I7b (idempotency + future/past)

**Files:** Modify test file (append к `describe`).

- [ ] **Step 8.1: I3, I4, I5**

```javascript
test('I3 — pre-existing processing task → no duplicate', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today });
  await pool.query(`
    INSERT INTO unic_tasks (content_id, slot_date, current_status, project_id, created_at, updated_at)
    VALUES ($1, $2, 'processing', $3, NOW(), NOW())
  `, [FIX_CONTENT_ID, today, FIX_PROJECT_ID]);
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(
    `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2`,
    [FIX_CONTENT_ID, today]
  );
  assert.equal(rows[0].n, 1);
});

test('I4 — pre-existing done task → no duplicate', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today });
  await pool.query(`
    INSERT INTO unic_tasks (content_id, slot_date, current_status, project_id, created_at, updated_at)
    VALUES ($1, $2, 'done', $3, NOW(), NOW())
  `, [FIX_CONTENT_ID, today, FIX_PROJECT_ID]);
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(
    `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2`,
    [FIX_CONTENT_ID, today]
  );
  assert.equal(rows[0].n, 1);
});

test('I5 — pre-existing error task → re-enqueue allowed (2 rows)', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today });
  await pool.query(`
    INSERT INTO unic_tasks (content_id, slot_date, current_status, project_id, created_at, updated_at)
    VALUES ($1, $2, 'error', $3, NOW(), NOW())
  `, [FIX_CONTENT_ID, today, FIX_PROJECT_ID]);
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(
    `SELECT current_status FROM unic_tasks WHERE content_id=$1 AND slot_date=$2 ORDER BY id`,
    [FIX_CONTENT_ID, today]
  );
  assert.equal(rows.length, 2);
  assert.equal(rows[0].current_status, 'error');
  assert.equal(rows[1].current_status, 'pending');
});
```

- [ ] **Step 8.2: I6, I7, I7b**

```javascript
test('I6 — slot tomorrow → not picked', async () => {
  const today = '2026-05-07';
  const tomorrow = '2026-05-08';
  await seedEligible({ slotDate: tomorrow });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(`SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows[0].n, 0);
});

test('I7 — slot 2 days ago → not picked (grace = [today, yesterday] only)', async () => {
  const today = '2026-05-07';
  const twoDaysAgo = '2026-05-05';
  await seedEligible({ slotDate: twoDaysAgo });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(`SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows[0].n, 0);
});

test('I7b — slot yesterday (within grace) → picked', async () => {
  const today = '2026-05-07';
  const yesterday = '2026-05-06';
  await seedEligible({ slotDate: yesterday });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(`SELECT slot_date FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].slot_date.toISOString().slice(0, 10), yesterday);
});
```

- [ ] **Step 8.3: Run + commit**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -15
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): integration tests I3-I7b — idempotency + boundary cases"
```

---

## Task 9: I8 midnight rollover (с reset content.status)

**Files:** Modify test file.

- [ ] **Step 9.1: I8 с явным reset content.status**

```javascript
test('I8 — midnight rollover: 23:59 GMT+4 picks today; 00:03 next day picks via grace', async () => {
  const day1 = '2026-05-07';
  const day2 = '2026-05-08';
  await seedEligible({ slotDate: day1 });
  await pool.query(`UPDATE unic_settings SET timezone='Asia/Dubai' WHERE id=1`);

  // Tick 1: 23:59 GMT+4 = 19:59 UTC on May 7
  const fakeNow1 = () => new Date('2026-05-07T19:59:00Z').getTime();
  await runScheduledUnicSweep({
    pool, runAutoUnicForDate, now: fakeNow1,
    state: { running: false, timer: null, stopped: false },
  });

  let { rows } = await pool.query(
    `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2`,
    [FIX_CONTENT_ID, day1]
  );
  assert.equal(rows[0].n, 1, 'tick 1 should enqueue day1');

  // Сброс: после tick 1 content.status стал 'in_uniqualization' и task стал 'pending'.
  // Чтобы tick 2 мог enqueue'ить day2, content.status должен снова быть 'approved',
  // а day1-task — закрыт (например 'done', чтобы NOT EXISTS из day2 не блокировал).
  await pool.query(`UPDATE unic_tasks SET current_status='done' WHERE content_id=$1 AND slot_date=$2`, [FIX_CONTENT_ID, day1]);
  await pool.query(`UPDATE validator_content SET status='approved' WHERE id=$1`, [FIX_CONTENT_ID]);
  await pool.query(`
    INSERT INTO validator_schedule_slots (content_id, slot_date, status, project_id)
    VALUES ($1, $2, 'filled', $3)
  `, [FIX_CONTENT_ID, day2, FIX_PROJECT_ID]);

  // Tick 2: 00:03 GMT+4 next day = 20:03 UTC on May 7
  const fakeNow2 = () => new Date('2026-05-07T20:03:00Z').getTime();
  await runScheduledUnicSweep({
    pool, runAutoUnicForDate, now: fakeNow2,
    state: { running: false, timer: null, stopped: false },
  });

  ({ rows } = await pool.query(
    `SELECT slot_date, current_status FROM unic_tasks WHERE content_id=$1 ORDER BY slot_date`,
    [FIX_CONTENT_ID]
  ));
  assert.equal(rows.length, 2, 'one for day1 (done), one for day2 (pending)');
  assert.equal(rows[1].slot_date.toISOString().slice(0, 10), day2);
  assert.equal(rows[1].current_status, 'pending');
});
```

- [ ] **Step 9.2: Run + commit**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): I8 midnight rollover with explicit content.status reset"
```

---

## Task 10: I9-I11 negative cases

**Files:** Modify test file.

- [ ] **Step 10.1: Дописать I9-I11**

```javascript
test('I9 — content.status=validating → not picked', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today, contentStatus: 'validating' });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(`SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows[0].n, 0);
});

test('I10 — slot.status=empty → not picked', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today, slotStatus: 'empty' });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(`SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows[0].n, 0);
});

test('I11 — moderation_status=pending → not picked', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today, moderationStatus: 'pending' });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null, stopped: false } });
  const { rows } = await pool.query(`SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows[0].n, 0);
});
```

- [ ] **Step 10.2: Run + commit**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): I9-I11 — negative eligibility (validating/empty/pending-moderation)"
```

---

## Task 11: I12a/I12b race tests

**Files:** Modify test file.

- [ ] **Step 11.1: I12a — DB-level race БЕЗ explicit transactions (auto-commit устраняет deadlock)**

```javascript
test('I12a — DB-level race against partial unique index (auto-commit)', async () => {
  const today = '2026-05-07';
  const contentId = -1042;
  await pool.query('DELETE FROM unic_tasks WHERE content_id=$1', [contentId]);

  const c1 = new Client({ connectionString: DB_URL });
  const c2 = new Client({ connectionString: DB_URL });
  await c1.connect();
  await c2.connect();

  // Auto-commit per statement: каждый INSERT — самостоятельная транзакция.
  // PG разруливает: первая получает row, вторая в конфликте получает rowCount=0.
  // Нет deadlock'а потому что нет открытых tx, ждущих друг друга.
  const insertSql = `
    INSERT INTO unic_tasks (content_id, slot_date, current_status, created_at, updated_at)
    VALUES ($1, $2, 'pending', NOW(), NOW())
    ON CONFLICT (content_id, slot_date)
    WHERE current_status IN ('pending','processing','done')
      AND content_id IS NOT NULL
      AND slot_date IS NOT NULL
    DO NOTHING
    RETURNING id
  `;

  try {
    const [r1, r2] = await Promise.all([
      c1.query(insertSql, [contentId, today]),
      c2.query(insertSql, [contentId, today]),
    ]);

    const totalInserted = r1.rowCount + r2.rowCount;
    assert.equal(totalInserted, 1, `expected exactly 1 successful INSERT, got ${totalInserted}`);

    const { rows } = await pool.query(
      'SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2',
      [contentId, today]
    );
    assert.equal(rows[0].n, 1, 'database must have exactly 1 row');
  } finally {
    await pool.query('DELETE FROM unic_tasks WHERE content_id=$1', [contentId]);
    await c1.end();
    await c2.end();
  }
});
```

- [ ] **Step 11.2: I12b — application-level smoke race**

```javascript
test('I12b — application race: parallel runAutoUnicForDate × 2 → exactly 1 row', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);

  const [r1, r2] = await Promise.all([
    runAutoUnicForDate(today, { timezone: 'UTC' }),
    runAutoUnicForDate(today, { timezone: 'UTC' }),
  ]);

  const { rows } = await pool.query(
    'SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2',
    [FIX_CONTENT_ID, today]
  );
  assert.equal(rows[0].n, 1, `database has ${rows[0].n} rows`);

  const totalInserted = (r1.inserted || 0) + (r2.inserted || 0);
  assert.ok(totalInserted >= 1);
});
```

- [ ] **Step 11.3: Run + commit**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): I12a/I12b — race coverage

I12a: DB-level race against partial unique index, two pg.Client'ов
без explicit BEGIN/COMMIT (auto-commit предотвращает deadlock).
I12b: application-level smoke race через Promise.all."
```

---

## Task 12: Полный прогон + smoke

- [ ] **Step 12.1: Все тесты green**

```bash
cd /home/claude-user/autowarm-testbench
node --test unic_sweep.test.js tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
```

Expected: `# pass: 22+, # fail: 0`.

- [ ] **Step 12.2: Live smoke server.js**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
DELETE FROM unic_tasks WHERE content_id = -1099;
DELETE FROM validator_schedule_slots WHERE content_id = -1099;
DELETE FROM validator_content WHERE id = -1099;
INSERT INTO validator_content (id, project_id, status, moderation_status, s3_url, title, created_at, updated_at)
  VALUES (-1099, -101, 'approved', 'passed', 's3://test/smoke.mp4', 'smoke-fixture', NOW(), NOW());
INSERT INTO validator_schedule_slots (content_id, slot_date, status, project_id)
  VALUES (-1099, CURRENT_DATE, 'filled', -101);
INSERT INTO factory_pack_accounts (id, project_id, pack_name) VALUES (-201, -101, 'smoke_pack')
  ON CONFLICT (id) DO NOTHING;
INSERT INTO unic_schemes (id, status) VALUES (-1, true) ON CONFLICT (id) DO UPDATE SET status=true;
INSERT INTO validator_scheme_preferences (project_id, scheme_id, status) VALUES (-101, -1, 'approved')
  ON CONFLICT (project_id, scheme_id) DO UPDATE SET status='approved';
SQL

timeout 50 node server.js 2>&1 | grep -iE "unic-sweep|auto-unic" | head -10
```

Expected: `[unic-sweep] loop started`, JSON-tick, `[auto-unic] ✅ task created: ... content=-1099`.

- [ ] **Step 12.3: Verify enqueued**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
  "SELECT id, content_id, slot_date, current_status FROM unic_tasks WHERE content_id=-1099;"
```

Expected: 1 row, `current_status='pending'`.

- [ ] **Step 12.4: Cleanup**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
DELETE FROM unic_tasks WHERE content_id = -1099;
DELETE FROM validator_schedule_slots WHERE content_id = -1099;
DELETE FROM validator_content WHERE id = -1099;
SQL
```

---

## Task 13: Deploy checklist + push branch

- [ ] **Step 13.1: Deploy checklist в evidence (репа `contenthunter`)**

```bash
cat > /home/claude-user/contenthunter/docs/evidence/2026-05-07-unic-sweep-deploy-checklist.md <<'EOF'
# Deploy Checklist — unic-sweep (sub-project A)

## Pre-flight on prod VPS

1. SSH on prod, `/root/.openclaw/workspace-genri/autowarm/`.
2. Audit:
   ```bash
   psql -U openclaw -d openclaw -f scripts/audit_unic_tasks_duplicates.sql
   ```
   - 0 строк → можно мигрировать.
   - Иначе → STOP, ops резолвит.
3. Имя PM2-процесса: `pm2 list | grep -E "autowarm|delivery|server"`.

## Deploy

1. Миграция (напрямую psql, не через runner с auto-tx):
   ```bash
   psql -U openclaw -d openclaw -f migrations/20260507_unic_tasks_unique_active_slot.sql
   psql -U openclaw -d openclaw -c "\d unic_tasks" | grep ux_unic_tasks
   ```
2. Cherry-pick кода в prod main (auto-push hook доставит).
3. `pm2 restart <process_name>`.

## Monitoring

- T+1 мин: `pm2 logs <process> | grep unic-sweep | head -3`.
- T+5 мин: первый JSON-tick.
- T+30 мин: `inserted` count.
- T+24 ч: health-метрика = 0 застрявших слотов.

## Rollback

- Код: `git revert <merge_sha>` + `pm2 restart`.
- Миграция: `psql -f migrations/20260507_unic_tasks_unique_active_slot__rollback.sql`.

## Disable без re-deploy

```bash
pm2 set <process>.env.UNIC_SWEEP_DISABLED 1
pm2 restart <process>
```
EOF

cd /home/claude-user/contenthunter
git add docs/evidence/2026-05-07-unic-sweep-deploy-checklist.md
git commit -m "docs(evidence): unic-sweep deploy checklist"
```

- [ ] **Step 13.2: Push branch**

```bash
cd /home/claude-user/autowarm-testbench
git push -u origin feature/unic-sweep-2026-05-07
```

- [ ] **Step 13.3: Сообщить пользователю**

Отдать пользователю:
- `git log --oneline main..HEAD`
- ссылки на design doc + plan + deploy checklist
- ожидаем approve для cherry-pick в prod main.

---

## Self-Review

- **Spec coverage:** все секции спеки покрыты (audit, migration, sweep helpers, sweep loop, runAutoUnicForDate refactor с ON CONFLICT, wiring, unit-тесты, I1-I12 integration, smoke, deploy guide).
- **Placeholder scan:** нет «TODO», «// see Step X above» — всё содержимое выписано.
- **Type consistency:** `runAutoUnicForDate` стабильно возвращает `{inserted, skipped, errors}`, `state` — `{running, timer, stopped}`, `pool` — pg.Pool.
- **Ordering:** Task 5 (extract) идёт ДО Task 7 (тесты), которые импортируют `../run_auto_unic`. Task 6 (wiring) ДО Task 12 (live smoke).

---

## Decisions captured

- Test runner: `node --test` (built-in) — найдено в `paginate.test.js`, `tests/test_pack_name_resolver.test.js`. Не добавляем Jest.
- runAutoUnicForDate extracted в отдельный модуль одним движением вместе с ON CONFLICT — refactor + behavior change в одном Task'e (минимальный diff).
- Все INSERT'ы `unic_tasks` идут через единственную точку (`run_auto_unic.js`); ON CONFLICT в одном месте покрывает все callers.
- Test fixtures используют `id <= -1000` для content и `<= -200` для packs.
- I12a — auto-commit per-statement, что устраняет потенциальный deadlock от Codex BLOCKER #4.
- I8 — явный reset `content.status='approved'` после первого tick'a (Codex BLOCKER #5).
- ON CONFLICT predicate: `(content_id, slot_date) WHERE current_status IN (...) AND content_id IS NOT NULL AND slot_date IS NOT NULL` — match index predicate exactly (Codex IMPORTANT #6).
- start/stop с `state.stopped` flag для предотвращения race при stop()-вызванном-mid-tick (Codex IMPORTANT #11).
- `unic_settings` save/restore в `before`/`after` (Codex IMPORTANT #12).
- `computeBusinessDate` использует `formatToParts` (Codex MINOR #13) для robustness.

## Codex review iterations

- v1: 5 BLOCKER + 7 IMPORTANT + 3 MINOR — все BLOCKER и большинство IMPORTANT учтены в этой v2 ревизии.
