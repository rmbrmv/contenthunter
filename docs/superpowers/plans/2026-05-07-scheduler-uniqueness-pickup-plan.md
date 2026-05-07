# Scheduler→Uniqueness Pickup Sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Любой `(slot=filled, content=approved+passed, slot_date=today)` доходит до `unic_tasks` максимум за один sweep-интервал (5 мин), без риска двойной публикации при concurrency.

**Architecture:** Один новый модуль `unic_sweep.js` (date math + sweep loop, чистый, без прямых SQL — принимает `pool` и `runAutoUnicForDate` через DI). Партиальный unique index `(content_id, slot_date) WHERE current_status IN ('pending','processing','done')` блокирует физические дубликаты. INSERT в `runAutoUnicForDate` получает `ON CONFLICT (cols) WHERE <predicate> DO NOTHING`. Sweep таргетит `[today, yesterday]` business-dates (midnight grace), DST-aware через `Intl.DateTimeFormat`.

**Tech Stack:** Node.js 18+ (`node:test` runner, `node:assert/strict`), `pg` 8.x, PostgreSQL 13+ partial unique indexes.

**Scope:** Sub-project A из brainstorming-сессии 2026-05-07. Дизайн утверждён в `docs/superpowers/specs/2026-05-07-scheduler-uniqueness-pickup-design.md` (revision v3).

---

## File Structure

| Файл | Action | Ответственность |
|---|---|---|
| `autowarm/scripts/audit_unic_tasks_duplicates.sql` | CREATE | Read-only отчёт по дублям (pre-migration check) |
| `autowarm/migrations/20260507_unic_tasks_unique_active_slot.sql` | CREATE | `CREATE UNIQUE INDEX CONCURRENTLY ... WHERE ...` |
| `autowarm/migrations/20260507_unic_tasks_unique_active_slot__rollback.sql` | CREATE | `DROP INDEX CONCURRENTLY ux_unic_tasks_active_slot;` |
| `autowarm/unic_sweep.js` | CREATE | Чистый модуль: `computeBusinessDate`, `computeBusinessDateWindow`, `runScheduledUnicSweep`, `start`, `stop`. Принимает `{pool, runAutoUnicForDate, log}` через DI. |
| `autowarm/unic_sweep.test.js` | CREATE | `node --test`: unit-тесты date-helpers + sweep-loop логики (моки pool/runAutoUnicForDate) |
| `autowarm/tests/test_unic_sweep_integration.test.js` | CREATE | `node --test`: integration против реальной testbench-БД (eligibility, idempotency, midnight, race) |
| `autowarm/server.js` | MODIFY (lines 5355–5481, ~5557) | INSERT в `runAutoUnicForDate` → ON CONFLICT + return counts; require + start sweep после `setInterval(triggerAutoUnic)` |

---

## Pre-flight (one-time, перед T1)

- [ ] **Step 0.1: Зайти в рабочую директорию + git fetch**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git status  # ожидаем clean tree (если нет — спросить пользователя)
git log --oneline -5
```

- [ ] **Step 0.2: Создать ветку**

```bash
git checkout -b feature/unic-sweep-2026-05-07
```

- [ ] **Step 0.3: Smoke pgsql + node**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "SELECT version();" | head -3
node --version  # ожидаем 18+
```

Expected: PG ≥ 13, Node ≥ 18.

---

## Task 1: Audit script (read-only)

**Files:**
- Create: `autowarm/scripts/audit_unic_tasks_duplicates.sql`

- [ ] **Step 1.1: Создать директорию scripts**

```bash
mkdir -p /home/claude-user/autowarm-testbench/scripts
```

- [ ] **Step 1.2: Написать audit-скрипт**

`autowarm/scripts/audit_unic_tasks_duplicates.sql`:

```sql
-- Read-only audit: ищем дубли (content_id, slot_date) среди живых задач.
-- Запускать ПЕРЕД миграцией. Если строки есть — миграцию НЕ применять
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

- [ ] **Step 1.3: Запустить audit на dev БД**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /home/claude-user/autowarm-testbench/scripts/audit_unic_tasks_duplicates.sql
```

Expected: `(0 rows)` или `No rows`. Если строки есть — записать в evidence-файл и спросить пользователя как резолвить.

- [ ] **Step 1.4: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add scripts/audit_unic_tasks_duplicates.sql
git commit -m "feat(unic): read-only audit script for unic_tasks duplicate detection"
```

---

## Task 2: Migration files

**Files:**
- Create: `autowarm/migrations/20260507_unic_tasks_unique_active_slot.sql`
- Create: `autowarm/migrations/20260507_unic_tasks_unique_active_slot__rollback.sql`

- [ ] **Step 2.1: Написать up-миграцию**

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

- [ ] **Step 2.2: Написать rollback**

`autowarm/migrations/20260507_unic_tasks_unique_active_slot__rollback.sql`:

```sql
DROP INDEX CONCURRENTLY IF EXISTS ux_unic_tasks_active_slot;
```

- [ ] **Step 2.3: Применить up-миграцию на dev БД**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /home/claude-user/autowarm-testbench/migrations/20260507_unic_tasks_unique_active_slot.sql
```

Expected: `CREATE INDEX`. Без ошибок.

- [ ] **Step 2.4: Verify index existence**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d unic_tasks" | grep ux_unic_tasks
```

Expected: одна строка `"ux_unic_tasks_active_slot" UNIQUE, btree (content_id, slot_date) WHERE current_status = ANY (ARRAY['pending'::text, 'processing'::text, 'done'::text]) AND content_id IS NOT NULL AND slot_date IS NOT NULL`.

- [ ] **Step 2.5: Smoke-test rollback (применить и сразу откатить)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /home/claude-user/autowarm-testbench/migrations/20260507_unic_tasks_unique_active_slot__rollback.sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d unic_tasks" | grep ux_unic_tasks || echo "rollback ok"
```

Expected: `rollback ok` (индекс удалён).

- [ ] **Step 2.6: Применить up снова (мы остаёмся с включённым индексом для дальнейших тестов)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /home/claude-user/autowarm-testbench/migrations/20260507_unic_tasks_unique_active_slot.sql
```

- [ ] **Step 2.7: Smoke-test ON CONFLICT синтаксис**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
-- Создать тестовую запись (используем content_id=-1 чтобы не задеть прод-данные)
DELETE FROM unic_tasks WHERE content_id = -1;
INSERT INTO unic_tasks (content_id, slot_date, current_status) VALUES (-1, '2099-01-01', 'pending');
-- Попробовать вставить дубликат — должно молча skip'нуться
INSERT INTO unic_tasks (content_id, slot_date, current_status)
VALUES (-1, '2099-01-01', 'pending')
ON CONFLICT (content_id, slot_date)
WHERE current_status IN ('pending', 'processing', 'done')
DO NOTHING;
-- Должно остаться ровно 1 строка
SELECT COUNT(*) AS n FROM unic_tasks WHERE content_id = -1;
DELETE FROM unic_tasks WHERE content_id = -1;
SQL
```

Expected: `n = 1`.

Если синтаксис не проходит (Postgres < 9.5 или другая ошибка) — STOP и сообщить пользователю.

- [ ] **Step 2.8: Commit**

```bash
git add migrations/20260507_unic_tasks_unique_active_slot.sql migrations/20260507_unic_tasks_unique_active_slot__rollback.sql
git commit -m "feat(unic): partial unique index on unic_tasks(content_id, slot_date)

Prevents race-condition duplicates between trigger-immediate and the
upcoming sweep loop. Partial: only enforces while task is alive
(pending/processing/done); error tasks can be re-enqueued."
```

---

## Task 3: Date helpers in `unic_sweep.js` (TDD)

**Files:**
- Create: `autowarm/unic_sweep.js`
- Create: `autowarm/unic_sweep.test.js`

- [ ] **Step 3.1: Написать failing-тесты для `computeBusinessDate`**

`autowarm/unic_sweep.test.js`:

```javascript
// unic_sweep.test.js — node --test unic_sweep.test.js
'use strict';

const { test, describe, mock } = require('node:test');
const assert = require('node:assert/strict');
const { computeBusinessDate, computeBusinessDateWindow } = require('./unic_sweep');

describe('computeBusinessDate', () => {
  test('Asia/Dubai at 2026-05-07T20:30:00Z returns 2026-05-08', () => {
    // 20:30 UTC + 4ч = 00:30 GMT+4 next day
    const t = new Date('2026-05-07T20:30:00Z').getTime();
    assert.equal(computeBusinessDate('Asia/Dubai', t), '2026-05-08');
  });

  test('UTC at 2026-05-07T20:30:00Z returns 2026-05-07', () => {
    const t = new Date('2026-05-07T20:30:00Z').getTime();
    assert.equal(computeBusinessDate('UTC', t), '2026-05-07');
  });

  test('America/New_York DST-aware: 2026-05-07T03:00Z returns 2026-05-06', () => {
    // May 2026 → EDT (UTC-4); 03:00 UTC = 23:00 May 6 EDT
    const t = new Date('2026-05-07T03:00:00Z').getTime();
    assert.equal(computeBusinessDate('America/New_York', t), '2026-05-06');
  });

  test('America/New_York DST-aware: January (EST, UTC-5)', () => {
    // Jan 2026 → EST (UTC-5); 03:00 UTC = 22:00 Jan 6 EST
    const t = new Date('2026-01-07T03:00:00Z').getTime();
    assert.equal(computeBusinessDate('America/New_York', t), '2026-01-06');
  });

  test('Europe/London DST-aware: May (BST, UTC+1) at 23:30Z returns next day', () => {
    // May → BST UTC+1; 23:30 UTC = 00:30 next day BST
    const t = new Date('2026-05-07T23:30:00Z').getTime();
    assert.equal(computeBusinessDate('Europe/London', t), '2026-05-08');
  });

  test('null/undefined timezone falls back to Asia/Dubai', () => {
    const t = new Date('2026-05-07T20:30:00Z').getTime();
    assert.equal(computeBusinessDate(null, t), '2026-05-08');
    assert.equal(computeBusinessDate(undefined, t), '2026-05-08');
  });

  test('invalid timezone falls back to Asia/Dubai with error log', () => {
    const t = new Date('2026-05-07T20:30:00Z').getTime();
    const errs = [];
    const origErr = console.error;
    console.error = (m) => errs.push(m);
    try {
      assert.equal(computeBusinessDate('Mars/Olympus', t), '2026-05-08');
      assert.ok(errs.length >= 1, 'expected error log');
      assert.match(errs[0], /unknown timezone/i);
    } finally {
      console.error = origErr;
    }
  });
});

describe('computeBusinessDateWindow', () => {
  test('returns [today, yesterday] in business TZ', () => {
    const t = new Date('2026-05-07T08:00:00Z').getTime();  // GMT+4 = 12:00 May 7
    const [today, yesterday] = computeBusinessDateWindow('Asia/Dubai', t);
    assert.equal(today, '2026-05-07');
    assert.equal(yesterday, '2026-05-06');
  });

  test('handles month boundary', () => {
    const t = new Date('2026-05-01T05:00:00Z').getTime();  // GMT+4 = 09:00 May 1
    const [today, yesterday] = computeBusinessDateWindow('Asia/Dubai', t);
    assert.equal(today, '2026-05-01');
    assert.equal(yesterday, '2026-04-30');
  });
});
```

- [ ] **Step 3.2: Запустить — должно упасть «Cannot find module»**

```bash
cd /home/claude-user/autowarm-testbench
node --test unic_sweep.test.js 2>&1 | tail -10
```

Expected: FAIL — `Cannot find module './unic_sweep'`.

- [ ] **Step 3.3: Написать минимальную реализацию date-helpers**

`autowarm/unic_sweep.js`:

```javascript
'use strict';

/**
 * Возвращает business-date (YYYY-MM-DD) для заданной IANA timezone.
 * DST-aware (использует Intl.DateTimeFormat). Невалидные TZ → fallback Asia/Dubai с error-log.
 */
function computeBusinessDate(timezone, baseTime) {
  const t = (baseTime !== undefined && baseTime !== null) ? baseTime : Date.now();
  const tz = timezone || 'Asia/Dubai';
  try {
    const fmt = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz,
      year: 'numeric', month: '2-digit', day: '2-digit',
    });
    return fmt.format(new Date(t));  // 'en-CA' даёт YYYY-MM-DD
  } catch (e) {
    console.error(JSON.stringify({
      tag: 'unic-sweep', ok: false,
      error: `unknown timezone '${tz}', falling back to Asia/Dubai (${e.message})`,
    }));
    const fallback = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Dubai',
      year: 'numeric', month: '2-digit', day: '2-digit',
    });
    return fallback.format(new Date(t));
  }
}

/**
 * Возвращает [today, yesterday] business-date — для midnight grace-window.
 */
function computeBusinessDateWindow(timezone, baseTime) {
  const t = (baseTime !== undefined && baseTime !== null) ? baseTime : Date.now();
  const today = computeBusinessDate(timezone, t);
  const yesterday = computeBusinessDate(timezone, t - 24 * 3600 * 1000);
  return [today, yesterday];
}

module.exports = { computeBusinessDate, computeBusinessDateWindow };
```

- [ ] **Step 3.4: Запустить тесты — должны пройти**

```bash
node --test unic_sweep.test.js 2>&1 | tail -20
```

Expected: `# pass 9` (или больше, если будут саб-тесты), `# fail 0`.

- [ ] **Step 3.5: Commit**

```bash
git add unic_sweep.js unic_sweep.test.js
git commit -m "feat(unic): DST-aware business-date helpers in unic_sweep module

computeBusinessDate uses Intl.DateTimeFormat (correct for all IANA TZs
including DST transitions). computeBusinessDateWindow returns [today,
yesterday] for midnight grace-window in upcoming sweep loop."
```

---

## Task 4: Sweep loop в `unic_sweep.js` (TDD)

**Files:**
- Modify: `autowarm/unic_sweep.js` (add `runScheduledUnicSweep`, `start`, `stop`)
- Modify: `autowarm/unic_sweep.test.js` (add sweep-loop tests)

- [ ] **Step 4.1: Дописать failing-тесты для sweep-loop в конец `unic_sweep.test.js`**

```javascript
describe('runScheduledUnicSweep', () => {
  // Helper: build a fake pool that returns fixed unic_settings row
  const fakeSettings = { id: 1, timezone: 'Asia/Dubai', publish_start: '09:00:00', prep_hours: 4 };
  function fakePool(settingsRow = fakeSettings) {
    return {
      query: async (sql) => {
        if (/unic_settings/.test(sql)) return { rows: [settingsRow] };
        return { rows: [] };
      },
    };
  }

  test('calls runAutoUnicForDate twice — once for today, once for yesterday', async () => {
    const { runScheduledUnicSweep } = require('./unic_sweep');
    const calls = [];
    const fakeRun = async (date, settings) => {
      calls.push(date);
      return { inserted: 0, skipped: 0, errors: 0 };
    };
    const t = new Date('2026-05-07T08:00:00Z').getTime();
    await runScheduledUnicSweep({
      pool: fakePool(),
      runAutoUnicForDate: fakeRun,
      now: () => t,
    });
    assert.deepEqual(calls, ['2026-05-07', '2026-05-06']);
  });

  test('skips if previous tick still running (re-entrancy guard)', async () => {
    const { runScheduledUnicSweep } = require('./unic_sweep');
    let runCalls = 0;
    const fakeRun = async () => { runCalls++; return { inserted: 0, skipped: 0, errors: 0 }; };
    const state = { running: true };  // simulate "previous tick still running"
    const t = new Date('2026-05-07T08:00:00Z').getTime();
    await runScheduledUnicSweep({
      pool: fakePool(),
      runAutoUnicForDate: fakeRun,
      now: () => t,
      state,
    });
    assert.equal(runCalls, 0, 'runAutoUnicForDate should not be called when guard is set');
  });

  test('logs error JSON and resets running guard on exception', async () => {
    const { runScheduledUnicSweep } = require('./unic_sweep');
    const fakeRun = async () => { throw new Error('boom'); };
    const errs = [];
    const origErr = console.error;
    console.error = (m) => errs.push(m);
    const state = { running: false };
    const t = new Date('2026-05-07T08:00:00Z').getTime();
    try {
      await runScheduledUnicSweep({
        pool: fakePool(),
        runAutoUnicForDate: fakeRun,
        now: () => t,
        state,
      });
    } finally {
      console.error = origErr;
    }
    assert.equal(state.running, false, 'running guard must reset after error');
    assert.ok(errs.some(m => /boom/.test(m) && /unic-sweep/.test(m)),
      `expected error log with 'boom' and 'unic-sweep' tag, got: ${errs.join('|')}`);
  });

  test('returns aggregated counts {target_dates, total_inserted}', async () => {
    const { runScheduledUnicSweep } = require('./unic_sweep');
    const fakeRun = async (date) => ({
      inserted: date === '2026-05-07' ? 3 : 1,
      skipped: 0, errors: 0,
    });
    const t = new Date('2026-05-07T08:00:00Z').getTime();
    const result = await runScheduledUnicSweep({
      pool: fakePool(),
      runAutoUnicForDate: fakeRun,
      now: () => t,
    });
    assert.equal(result.total_inserted, 4);
    assert.deepEqual(result.target_dates, ['2026-05-07', '2026-05-06']);
  });
});

describe('start/stop loop', () => {
  test('start schedules a timer, stop clears it', () => {
    const { start, stop } = require('./unic_sweep');
    const state = { running: false, timer: null };
    start({
      pool: { query: async () => ({ rows: [{ timezone: 'UTC' }] }) },
      runAutoUnicForDate: async () => ({ inserted: 0, skipped: 0, errors: 0 }),
      state,
      initialDelayMs: 50_000,
      intervalMs: 60_000,
    });
    assert.ok(state.timer !== null, 'start should set state.timer');
    stop({ state });
    assert.equal(state.timer, null, 'stop should clear state.timer');
  });

  test('start is idempotent (second call no-op if timer exists)', () => {
    const { start, stop } = require('./unic_sweep');
    const state = { running: false, timer: null };
    const opts = {
      pool: { query: async () => ({ rows: [{}] }) },
      runAutoUnicForDate: async () => ({ inserted: 0, skipped: 0, errors: 0 }),
      state,
      initialDelayMs: 50_000,
      intervalMs: 60_000,
    };
    start(opts);
    const firstTimer = state.timer;
    start(opts);
    assert.equal(state.timer, firstTimer, 'second start should be no-op');
    stop({ state });
  });
});
```

- [ ] **Step 4.2: Запустить — должны упасть «runScheduledUnicSweep is not a function»**

```bash
node --test unic_sweep.test.js 2>&1 | tail -10
```

Expected: failures with `is not a function`.

- [ ] **Step 4.3: Дописать `runScheduledUnicSweep` + `start`/`stop` в `unic_sweep.js`**

В конце `autowarm/unic_sweep.js` добавить:

```javascript
/**
 * Один tick свипа. Чистая функция — все зависимости через DI:
 *   - pool: pg-style { query(sql, params) }
 *   - runAutoUnicForDate: async (date, settings) => { inserted, skipped, errors }
 *   - now: () => epoch_ms (для тестов с mock'нутым временем)
 *   - state: { running: bool, timer: handle } — внешнее состояние, разделяемое со start/stop
 */
async function runScheduledUnicSweep({
  pool,
  runAutoUnicForDate,
  now = Date.now,
  state = { running: false, timer: null },
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
      target_dates, total_inserted,
      took_ms: now() - t0,
    }));
    return { skipped: false, target_dates, total_inserted };
  } catch (e) {
    console.error(JSON.stringify({
      tag: 'unic-sweep', ok: false,
      target_dates, error: e.message,
      took_ms: now() - t0,
    }));
    return { skipped: false, target_dates, total_inserted: 0, error: e.message };
  } finally {
    state.running = false;
  }
}

const DEFAULT_INTERVAL_MS = 5 * 60 * 1000;
const DEFAULT_INITIAL_DELAY_MS = 30 * 1000;

/**
 * Запустить self-scheduling sweep loop. Идемпотентно (повторный вызов — no-op).
 */
function start({
  pool,
  runAutoUnicForDate,
  state = { running: false, timer: null },
  initialDelayMs = DEFAULT_INITIAL_DELAY_MS,
  intervalMs = DEFAULT_INTERVAL_MS,
  now = Date.now,
}) {
  if (state.timer) return;  // idempotent
  const tick = async () => {
    try {
      await runScheduledUnicSweep({ pool, runAutoUnicForDate, now, state });
    } catch (e) {
      console.error(JSON.stringify({
        tag: 'unic-sweep', ok: false,
        error: `unhandled in tick: ${e.message}`,
      }));
    }
    state.timer = setTimeout(tick, intervalMs);
  };
  state.timer = setTimeout(tick, initialDelayMs);
  return state;
}

function stop({ state }) {
  if (state && state.timer) {
    clearTimeout(state.timer);
    state.timer = null;
  }
}

module.exports = {
  computeBusinessDate,
  computeBusinessDateWindow,
  runScheduledUnicSweep,
  start,
  stop,
};
```

- [ ] **Step 4.4: Запустить тесты — должны пройти**

```bash
node --test unic_sweep.test.js 2>&1 | tail -20
```

Expected: все тесты pass, `# fail 0`.

- [ ] **Step 4.5: Commit**

```bash
git add unic_sweep.js unic_sweep.test.js
git commit -m "feat(unic): self-scheduling sweep loop with re-entrancy guard

runScheduledUnicSweep:
- Iterates [today, yesterday] for midnight grace
- Re-entrancy guard via shared state object
- Structured JSON logs per target_date + summary
- All deps via DI for testability

start/stop: idempotent module lifecycle, recursive setTimeout
(stable under event-loop drift)."
```

---

## Task 5: `runAutoUnicForDate` — ON CONFLICT + return counts

**Files:**
- Modify: `autowarm/server.js` (lines 5355–5481)

- [ ] **Step 5.1: Прочитать текущий `runAutoUnicForDate`**

```bash
sed -n '5355,5481p' /home/claude-user/autowarm-testbench/server.js | head -130
```

Зафиксировать что:
- Сигнатура: `async function runAutoUnicForDate(slotDate, settings)`
- Возвращает: ничего (void)
- INSERT на line ~5456 в `unic_tasks`
- Несколько `console.log` skip-ветвей (нет паков, нет схем, mismatch)

- [ ] **Step 5.2: Заменить функцию на версию с counts + ON CONFLICT**

В `autowarm/server.js`, заменить блок 5355–5481 на:

```javascript
async function runAutoUnicForDate(slotDate, settings) {
  const { publish_start, timezone } = settings;
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

      // INSERT с partial unique index protection (см. migration 20260507_unic_tasks_unique_active_slot)
      const insertResult = await pool.query(`
        INSERT INTO unic_tasks
          (input_video_url, input_video_name, project_name, schemes, schemes_total,
           current_status, project_id, content_id, slot_date, meta, created_at, updated_at)
        VALUES ($1,$2,$3,$4,$5,'pending',$6,$7,$8,$9,NOW(),NOW())
        ON CONFLICT (content_id, slot_date)
        WHERE current_status IN ('pending','processing','done')
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
}
```

- [ ] **Step 5.3: Smoke — server.js запускается без syntax-error**

```bash
cd /home/claude-user/autowarm-testbench
node -c server.js && echo "OK"
```

Expected: `OK` (только синтаксис-чек, не запуск).

- [ ] **Step 5.4: Existing callers продолжают работать**

```bash
grep -n "runAutoUnicForDate" server.js
```

Expected: 5 hits (declaration + 3 callers + comment) — все callers всё ещё передают (slotDate, settings); они НЕ читают return value, так что добавление `{inserted, skipped, errors}` не ломает их.

- [ ] **Step 5.5: Commit**

```bash
git add server.js
git commit -m "feat(unic): runAutoUnicForDate uses ON CONFLICT + returns counts

INSERT INTO unic_tasks now has ON CONFLICT (content_id, slot_date)
WHERE current_status IN (pending/processing/done) DO NOTHING.
This protects every insert path (trigger-immediate, morning batch,
upcoming sweep) against race-condition duplicates via the partial
unique index added in 20260507 migration.

Function now returns {inserted, skipped, errors} for the sweep
caller's structured logging."
```

---

## Task 6: Wire sweep loop в `server.js`

**Files:**
- Modify: `autowarm/server.js` (после line ~5555)

- [ ] **Step 6.1: Найти место для подключения**

```bash
grep -n "setInterval(triggerAutoUnic\|каждые 30 минут" /home/claude-user/autowarm-testbench/server.js | head -5
```

Expected: line ~5551–5555 — там `setInterval(async () => { await triggerAutoUnic(); }, 30 * 60 * 1000);`.

- [ ] **Step 6.2: Добавить require + start вызов**

В `autowarm/server.js`, **сразу после** блока `setInterval(triggerAutoUnic, ...)` (предположительно после line 5555), добавить:

```javascript
// ===== UNIC SWEEP: continuous safety net каждые 5 минут =====
// Дополняет trigger-immediate (in-day flow) и triggerAutoUnic (morning batch):
// ловит approved+filled слоты на сегодня/вчера, которые по любой причине
// не дошли до unic_tasks. Идемпотентно через ON CONFLICT + partial unique index.
const unicSweep = require('./unic_sweep');
const unicSweepState = { running: false, timer: null };

if (process.env.NODE_ENV !== 'test' && process.env.UNIC_SWEEP_DISABLED !== '1') {
  unicSweep.start({
    pool,
    runAutoUnicForDate,
    state: unicSweepState,
  });
  console.log('[unic-sweep] loop started (5min interval, 30s initial delay)');
}
```

- [ ] **Step 6.3: Smoke — server.js парсится**

```bash
node -c server.js && echo "OK"
```

Expected: `OK`.

- [ ] **Step 6.4: Smoke — server.js запускается, sweep тикает один раз**

```bash
# Сократить initial delay до 2с и interval до 5с через override (без env пока)
# Стартанём server.js на 15 секунд и поймаем первый тик в логах
cd /home/claude-user/autowarm-testbench
timeout 15 node server.js 2>&1 | grep -E "unic-sweep|Listening|listening" | head -10 || true
```

Expected: видим `[unic-sweep] loop started ...` и через 30+ секунд первый JSON-тик. Если timeout слишком короткий, чтобы дождаться 30с initial delay — продлить timeout до 45с.

```bash
# Альтернатива — продлить и фильтровать
timeout 45 node server.js 2>&1 | grep -E "unic-sweep" | head -5
```

Expected: минимум 1 строка `{"tag":"unic-sweep",...,"summary":true,...}` за 45 секунд.

Если в БД на сегодня нет ни одного `approved+filled` слота, в логе будут `[auto-unic] Нет слотов для уникализации на YYYY-MM-DD` — это ОК.

- [ ] **Step 6.5: Commit**

```bash
git add server.js
git commit -m "feat(unic): wire 5-minute sweep loop in server.js startup

Loads ./unic_sweep, starts loop in production (skipped when
NODE_ENV=test or UNIC_SWEEP_DISABLED=1). State object decoupled
from the module so tests can stop/start independently."
```

---

## Task 7: Integration tests — eligibility (I1, I2, I3, I4, I5, I6, I7)

**Files:**
- Create: `autowarm/tests/test_unic_sweep_integration.test.js`

- [ ] **Step 7.1: Создать integration-тест c fixture-helpers и тестами I1, I2**

`autowarm/tests/test_unic_sweep_integration.test.js`:

```javascript
// node --test tests/test_unic_sweep_integration.test.js
'use strict';

const { test, describe, before, after, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const path = require('path');

// Импортируем sweep + runAutoUnicForDate. Последний экспортируется не из server.js
// (там его нет в module.exports). Чтобы избежать boot'а сервера, повторяем функцию
// здесь через прямой require исполнения SQL-логики. ВАРИАНТ: extract'нуть
// runAutoUnicForDate в отдельный модуль server_helpers.js. Пока что — в этом
// тесте используем рецепт «вызываем уже-загруженный server.js модуль» через
// child_process НЕ подходит. Поэтому extract'ируем функцию.
//
// Решение для T7: ввести минимальный модуль `autowarm/run_auto_unic.js`,
// в который перенести runAutoUnicForDate, и server.js будет require'ить.
// См. Task 7.0 ниже.

const { runScheduledUnicSweep } = require('../unic_sweep');
const { runAutoUnicForDate } = require('../run_auto_unic');

const DB_URL = 'postgres://openclaw:openclaw123@localhost:5432/openclaw';

let pool;

before(async () => {
  pool = new Pool({ connectionString: DB_URL, max: 4 });
});

after(async () => {
  await pool.end();
});

// Test fixture data uses content_id < 0 to avoid colliding with prod-like rows.
const FIX_CONTENT_ID = -1001;
const FIX_PROJECT_ID = -101;
const FIX_PACK_ID_BASE = -201;

async function cleanupFixtures(c = pool) {
  await c.query('DELETE FROM unic_tasks WHERE content_id <= -1000');
  await c.query('DELETE FROM validator_schedule_slots WHERE content_id <= -1000');
  await c.query('DELETE FROM validator_content WHERE id <= -1000');
  await c.query('DELETE FROM factory_pack_accounts WHERE id <= -200 AND id >= -210');
  await c.query('DELETE FROM validator_scheme_preferences WHERE project_id = -101');
  await c.query('DELETE FROM unic_schemes WHERE id <= -1');
}

async function seedEligible({
  contentId = FIX_CONTENT_ID,
  projectId = FIX_PROJECT_ID,
  slotDate,
  contentStatus = 'approved',
  moderationStatus = 'passed',
  slotStatus = 'filled',
} = {}) {
  // 1. content
  await pool.query(`
    INSERT INTO validator_content (id, project_id, status, moderation_status, s3_url, title, created_at, updated_at)
    VALUES ($1, $2, $3, $4, 's3://test/x.mp4', 'fixture', NOW(), NOW())
    ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, moderation_status = EXCLUDED.moderation_status
  `, [contentId, projectId, contentStatus, moderationStatus]);

  // 2. slot
  await pool.query(`
    INSERT INTO validator_schedule_slots (content_id, slot_date, status, project_id)
    VALUES ($1, $2, $3, $4)
  `, [contentId, slotDate, slotStatus, projectId]);

  // 3. one pack to satisfy eligibility loop
  await pool.query(`
    INSERT INTO factory_pack_accounts (id, project_id, pack_name)
    VALUES ($1, $2, 'fixture_pack_1')
    ON CONFLICT (id) DO NOTHING
  `, [FIX_PACK_ID_BASE, projectId]);

  // 4. one approved scheme matching pack
  await pool.query(`
    INSERT INTO unic_schemes (id, status) VALUES (-1, true)
    ON CONFLICT (id) DO UPDATE SET status = true
  `);
  await pool.query(`
    INSERT INTO validator_scheme_preferences (project_id, scheme_id, status)
    VALUES ($1, -1, 'approved')
    ON CONFLICT (project_id, scheme_id) DO UPDATE SET status = 'approved'
  `, [projectId]);
}

beforeEach(async () => {
  await cleanupFixtures();
});

describe('integration: sweep eligibility', () => {
  test('I1 — single eligible slot today → enqueued in unic_tasks', async () => {
    const today = '2026-05-07';
    await seedEligible({ slotDate: today });
    // Mock business-tz so sweep targets exactly our test date.
    // unic_settings table должен иметь timezone — для теста делаем UTC и mock now.
    await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
    const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();

    const r = await runScheduledUnicSweep({
      pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null },
    });

    const { rows } = await pool.query(
      `SELECT id, current_status, slot_date FROM unic_tasks WHERE content_id=$1`,
      [FIX_CONTENT_ID]
    );
    assert.equal(rows.length, 1, 'expected exactly one unic_task');
    assert.equal(rows[0].current_status, 'pending');
    assert.equal(rows[0].slot_date.toISOString().slice(0, 10), today);

    const { rows: cont } = await pool.query(
      `SELECT status FROM validator_content WHERE id=$1`, [FIX_CONTENT_ID]
    );
    assert.equal(cont[0].status, 'in_uniqualization');
    assert.ok(r.total_inserted >= 1);
  });

  test('I2 — pre-existing pending task → no duplicate (idempotent)', async () => {
    const today = '2026-05-07';
    await seedEligible({ slotDate: today });
    await pool.query(`
      INSERT INTO unic_tasks (content_id, slot_date, current_status, project_id, created_at, updated_at)
      VALUES ($1, $2, 'pending', $3, NOW(), NOW())
    `, [FIX_CONTENT_ID, today, FIX_PROJECT_ID]);

    await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
    const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
    await runScheduledUnicSweep({
      pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null },
    });

    const { rows } = await pool.query(
      `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2`,
      [FIX_CONTENT_ID, today]
    );
    assert.equal(rows[0].n, 1, 'no new row should be inserted');
  });
});
```

- [ ] **Step 7.0: BLOCKER — extract `runAutoUnicForDate` в отдельный модуль `run_auto_unic.js`**

Тестам нужно `require('../run_auto_unic')`. Сейчас функция inline в server.js. Решаем сразу: переносим её в `autowarm/run_auto_unic.js`, а в server.js остаётся только require.

`autowarm/run_auto_unic.js` (NEW):

```javascript
'use strict';

/**
 * Создаёт unic_tasks для всех подходящих слотов на заданную дату.
 * Идемпотентно через partial unique index (см. migration 20260507).
 * Возвращает агрегированные counts.
 */
function makeRunAutoUnicForDate({ pool }) {
  return async function runAutoUnicForDate(slotDate, settings) {
    const { publish_start, timezone } = settings || {};
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
        // [body identical to Task 5 Step 5.2 — repeat in full here]
        // ...
        // (см. server.js patch ниже — мы перенесли всё тело)
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

(Тело for-loop'а — копия из Task 5 Step 5.2; перепиши его дословно, не оставляй троеточие.)

И в `server.js` заменяем встроенную функцию на:

```javascript
const { makeRunAutoUnicForDate } = require('./run_auto_unic');
const runAutoUnicForDate = makeRunAutoUnicForDate({ pool });
```

И для тестов экспортируем готовый instance:

`autowarm/run_auto_unic.js` (добавить в конец):

```javascript
// Convenience export для интеграционных тестов: создаёт instance c новым pool
let _testInstance = null;
function getRunAutoUnicForDateForTests(pool) {
  return makeRunAutoUnicForDate({ pool });
}

module.exports.getRunAutoUnicForDateForTests = getRunAutoUnicForDateForTests;
```

В тесте:

```javascript
const { getRunAutoUnicForDateForTests } = require('../run_auto_unic');
const runAutoUnicForDate = getRunAutoUnicForDateForTests(pool);
```

(Перепиши все упоминания `runAutoUnicForDate` в test-файле с использованием локально созданного instance.)

- [ ] **Step 7.0a: Применить refactor (server.js inline → run_auto_unic.js)**

```bash
cd /home/claude-user/autowarm-testbench
# Извлекаем функцию (вручную — Edit tool'ом)
node -c server.js && node -c run_auto_unic.js && echo "OK"
```

- [ ] **Step 7.0b: Smoke — server.js всё ещё запускается**

```bash
timeout 10 node server.js 2>&1 | head -20 || true
```

Expected: видим стандартный startup-лог; никаких "is not defined".

- [ ] **Step 7.0c: Commit refactor отдельно (для readability)**

```bash
git add run_auto_unic.js server.js
git commit -m "refactor(unic): extract runAutoUnicForDate into run_auto_unic.js

Pure DI factory makeRunAutoUnicForDate({pool}) returns the function.
server.js wires once and uses as before. Tests import a separately-
poolable instance via getRunAutoUnicForDateForTests(pool).

No behavior change — functionally identical to commit <T5 sha>."
```

- [ ] **Step 7.1 (продолжение): Запустить I1 + I2**

```bash
cd /home/claude-user/autowarm-testbench
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -30
```

Expected: I1 + I2 pass.

Если падает I1 с `INSERT ... ON CONFLICT ... WHERE` синтакс-ошибкой — STOP, проверить версию Postgres (pg_config).

- [ ] **Step 7.2: Добавить I3 (processing), I4 (done), I5 (re-enqueue после error)**

В тот же файл `tests/test_unic_sweep_integration.test.js` дописать:

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

  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });

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

  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });

  const { rows } = await pool.query(
    `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2`,
    [FIX_CONTENT_ID, today]
  );
  assert.equal(rows[0].n, 1);
});

test('I5 — pre-existing error task → re-enqueue allowed (2 rows after sweep)', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today });
  await pool.query(`
    INSERT INTO unic_tasks (content_id, slot_date, current_status, project_id, created_at, updated_at)
    VALUES ($1, $2, 'error', $3, NOW(), NOW())
  `, [FIX_CONTENT_ID, today, FIX_PROJECT_ID]);
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();

  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });

  const { rows } = await pool.query(
    `SELECT current_status FROM unic_tasks WHERE content_id=$1 AND slot_date=$2 ORDER BY id`,
    [FIX_CONTENT_ID, today]
  );
  assert.equal(rows.length, 2, 'old error + new pending');
  assert.equal(rows[0].current_status, 'error');
  assert.equal(rows[1].current_status, 'pending');
});
```

- [ ] **Step 7.3: Run I3-I5**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -30
```

Expected: 5 tests pass.

- [ ] **Step 7.4: Добавить I6 (future slot ignored), I7 (past slot ignored по policy, но тут yesterday — grace включает её, поэтому проверим что past < yesterday не подбирается)**

```javascript
test('I6 — slot tomorrow → not picked', async () => {
  const today = '2026-05-07';
  const tomorrow = '2026-05-08';
  await seedEligible({ slotDate: tomorrow });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();

  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });

  const { rows } = await pool.query(
    `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`,
    [FIX_CONTENT_ID]
  );
  assert.equal(rows[0].n, 0);
});

test('I7 — slot 2 days ago → not picked (grace window is only [today, yesterday])', async () => {
  const today = '2026-05-07';
  const twoDaysAgo = '2026-05-05';
  await seedEligible({ slotDate: twoDaysAgo });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();

  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });

  const { rows } = await pool.query(
    `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`,
    [FIX_CONTENT_ID]
  );
  assert.equal(rows[0].n, 0);
});

test('I7b — slot yesterday (within grace window) → picked', async () => {
  const today = '2026-05-07';
  const yesterday = '2026-05-06';
  await seedEligible({ slotDate: yesterday });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();

  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });

  const { rows } = await pool.query(
    `SELECT slot_date FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].slot_date.toISOString().slice(0, 10), yesterday);
});
```

- [ ] **Step 7.5: Run I6-I7b**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -30
```

Expected: 8 tests pass total (I1, I2, I3, I4, I5, I6, I7, I7b).

- [ ] **Step 7.6: Commit**

```bash
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): integration tests I1-I7 — eligibility + idempotency

I1: single eligible slot today → enqueued
I2-I4: pre-existing pending/processing/done task → no duplicate
I5: pre-existing error → re-enqueue allowed
I6-I7: future and 2-days-ago slots ignored
I7b: yesterday in grace-window → picked"
```

---

## Task 8: Integration test — midnight rollover (I8)

**Files:**
- Modify: `autowarm/tests/test_unic_sweep_integration.test.js`

- [ ] **Step 8.1: Дописать I8**

```javascript
test('I8 — midnight rollover: 23:59 GMT+4 picks today; 00:01 next day still picks via yesterday-grace', async () => {
  const day1 = '2026-05-07';
  const day2 = '2026-05-08';
  await seedEligible({ slotDate: day1 });
  await pool.query(`UPDATE unic_settings SET timezone='Asia/Dubai' WHERE id=1`);

  // Tick 1: 23:59 GMT+4 = 19:59 UTC on May 7
  const fakeNow1 = () => new Date('2026-05-07T19:59:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow1, state: { running: false, timer: null } });

  let { rows } = await pool.query(
    `SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2`,
    [FIX_CONTENT_ID, day1]
  );
  assert.equal(rows[0].n, 1, 'tick 1 should enqueue day1');

  // Add a new eligible slot for day2 (clean state for this content_id by archiving day1 task)
  await pool.query(`UPDATE unic_tasks SET current_status='done' WHERE content_id=$1 AND slot_date=$2`, [FIX_CONTENT_ID, day1]);
  await pool.query(`
    INSERT INTO validator_schedule_slots (content_id, slot_date, status, project_id)
    VALUES ($1, $2, 'filled', $3)
  `, [FIX_CONTENT_ID, day2, FIX_PROJECT_ID]);

  // Tick 2: 00:03 GMT+4 next day = 20:03 UTC on May 7
  const fakeNow2 = () => new Date('2026-05-07T20:03:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow2, state: { running: false, timer: null } });

  ({ rows } = await pool.query(
    `SELECT slot_date, current_status FROM unic_tasks WHERE content_id=$1 ORDER BY slot_date`,
    [FIX_CONTENT_ID]
  ));
  assert.equal(rows.length, 2, 'one for day1 (done), one for day2 (pending)');
  assert.equal(rows[1].slot_date.toISOString().slice(0, 10), day2);
  assert.equal(rows[1].current_status, 'pending');
});
```

- [ ] **Step 8.2: Run**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
```

Expected: I8 passes (9 tests total).

- [ ] **Step 8.3: Commit**

```bash
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): integration test I8 — midnight rollover with grace window"
```

---

## Task 9: Integration tests — negative cases (I9, I10, I11)

**Files:**
- Modify: `autowarm/tests/test_unic_sweep_integration.test.js`

- [ ] **Step 9.1: Дописать I9-I11**

```javascript
test('I9 — content.status=validating → not picked', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today, contentStatus: 'validating' });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });
  const { rows } = await pool.query(`SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows[0].n, 0);
});

test('I10 — slot.status=empty → not picked', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today, slotStatus: 'empty' });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });
  const { rows } = await pool.query(`SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows[0].n, 0);
});

test('I11 — moderation_status=pending → not picked', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today, moderationStatus: 'pending' });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);
  const fakeNow = () => new Date(today + 'T12:00:00Z').getTime();
  await runScheduledUnicSweep({ pool, runAutoUnicForDate, now: fakeNow, state: { running: false, timer: null } });
  const { rows } = await pool.query(`SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1`, [FIX_CONTENT_ID]);
  assert.equal(rows[0].n, 0);
});
```

- [ ] **Step 9.2: Run + commit**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): integration tests I9-I11 — negative eligibility cases"
```

Expected: 12 tests pass.

---

## Task 10: Race tests (I12a, I12b)

**Files:**
- Modify: `autowarm/tests/test_unic_sweep_integration.test.js`

- [ ] **Step 10.1: Дописать I12a — DB-level race против partial unique index**

```javascript
test('I12a — DB-level race: two clients INSERT concurrently → exactly one row remains', async () => {
  const today = '2026-05-07';
  const contentId = -1042;
  // Cleanup
  await pool.query('DELETE FROM unic_tasks WHERE content_id=$1', [contentId]);

  const { Client } = require('pg');
  const c1 = new Client({ connectionString: DB_URL });
  const c2 = new Client({ connectionString: DB_URL });
  await c1.connect();
  await c2.connect();

  const insertSql = `
    INSERT INTO unic_tasks (content_id, slot_date, current_status, created_at, updated_at)
    VALUES ($1, $2, 'pending', NOW(), NOW())
    ON CONFLICT (content_id, slot_date)
    WHERE current_status IN ('pending','processing','done')
    DO NOTHING
    RETURNING id
  `;

  try {
    await c1.query('BEGIN');
    await c2.query('BEGIN');

    // Оба прочитали бы NOT EXISTS независимо. Запускаем INSERT параллельно.
    const [r1, r2] = await Promise.all([
      c1.query(insertSql, [contentId, today]),
      c2.query(insertSql, [contentId, today]),
    ]);

    await c1.query('COMMIT');
    await c2.query('COMMIT');

    const totalInserted = r1.rowCount + r2.rowCount;
    assert.equal(totalInserted, 1, `expected exactly 1 successful INSERT, got ${totalInserted} (r1=${r1.rowCount}, r2=${r2.rowCount})`);

    const { rows } = await pool.query(
      'SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2',
      [contentId, today]
    );
    assert.equal(rows[0].n, 1, 'database must have exactly 1 row for (content_id, slot_date)');
  } finally {
    try { await c1.query('ROLLBACK'); } catch {}
    try { await c2.query('ROLLBACK'); } catch {}
    await pool.query('DELETE FROM unic_tasks WHERE content_id=$1', [contentId]);
    await c1.end();
    await c2.end();
  }
});
```

- [ ] **Step 10.2: Run I12a**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
```

Expected: I12a pass — physical unique index работает.

- [ ] **Step 10.3: Дописать I12b — application-level race (sweep + manual)**

```javascript
test('I12b — application race: parallel runAutoUnicForDate × 2 → exactly 1 row', async () => {
  const today = '2026-05-07';
  await seedEligible({ slotDate: today });
  await pool.query(`UPDATE unic_settings SET timezone='UTC' WHERE id=1`);

  // Запускаем две runAutoUnicForDate параллельно. NOT EXISTS внутри SELECT может
  // в обоих транзакциях вернуть «нет конфликта», но ON CONFLICT финальный
  // INSERT-conflict защитит.
  const [r1, r2] = await Promise.all([
    runAutoUnicForDate(today, { timezone: 'UTC' }),
    runAutoUnicForDate(today, { timezone: 'UTC' }),
  ]);

  const { rows } = await pool.query(
    'SELECT COUNT(*)::int AS n FROM unic_tasks WHERE content_id=$1 AND slot_date=$2',
    [FIX_CONTENT_ID, today]
  );
  assert.equal(rows[0].n, 1, `database has ${rows[0].n} rows after parallel runs`);

  const totalInserted = (r1.inserted || 0) + (r2.inserted || 0);
  // Acceptable outcomes:
  //   - One race won: inserted=1 elsewhere=0
  //   - Both observed pre-existing: inserted=0,0 — but this is impossible from a clean fixture
  assert.ok(totalInserted >= 1, 'at least one runner must report an insert');
});
```

- [ ] **Step 10.4: Run I12b**

```bash
node --test tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
```

Expected: I12b passes. Если не падает но totalInserted=2 — ON CONFLICT не работает; если в БД 2 строки — partial unique index не покрывает кейс. STOP, вернуться к Task 2.

- [ ] **Step 10.5: Commit**

```bash
git add tests/test_unic_sweep_integration.test.js
git commit -m "test(unic): integration tests I12a/I12b — race condition coverage

I12a: physical partial unique index test with two pg.Client tx
I12b: application-level race via Promise.all on runAutoUnicForDate"
```

---

## Task 11: Smoke на testbench

- [ ] **Step 11.1: Все unit + integration тесты pass**

```bash
cd /home/claude-user/autowarm-testbench
node --test unic_sweep.test.js tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
```

Expected: всё green. `# pass: 22+, # fail: 0`.

- [ ] **Step 11.2: Запустить server.js на 60 секунд и поймать живой тик**

```bash
# Создадим fake-eligible слот на сегодня для smoke
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
DELETE FROM unic_tasks WHERE content_id <= -1000;
DELETE FROM validator_schedule_slots WHERE content_id <= -1000;
DELETE FROM validator_content WHERE id <= -1000;
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

# Запускаем сервер на 50 секунд (хватит для 30s initial delay + один tick)
timeout 50 node server.js 2>&1 | grep -iE "unic-sweep|auto-unic" | head -20
```

Expected: видим JSON-лог `{"tag":"unic-sweep",...,"target_date":"<today>",...}` И `[auto-unic] ✅ task created: ... content=-1099`.

- [ ] **Step 11.3: Verify enqueued**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
  "SELECT id, content_id, slot_date, current_status FROM unic_tasks WHERE content_id=-1099;"
```

Expected: 1 строка, `current_status='pending'`.

- [ ] **Step 11.4: Cleanup**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL'
DELETE FROM unic_tasks WHERE content_id = -1099;
DELETE FROM validator_schedule_slots WHERE content_id = -1099;
DELETE FROM validator_content WHERE id = -1099;
SQL
```

- [ ] **Step 11.5: (Optional) Снять evidence-файл**

```bash
mkdir -p /home/claude-user/contenthunter/docs/evidence
cat > /home/claude-user/contenthunter/docs/evidence/2026-05-07-unic-sweep-smoke.md <<'EOF'
# Smoke: unic-sweep on testbench (2026-05-07)

## Setup
- Branch: feature/unic-sweep-2026-05-07
- Migration applied: 20260507_unic_tasks_unique_active_slot
- Test fixture: content_id=-1099, today's date

## Result
- First sweep tick fired ~30s after server start
- task INSERT'нул content=-1099 в unic_tasks с current_status='pending'
- Lifecycle dump (см. PM2 logs)

## All tests
- unit: <N> pass
- integration: <N> pass
EOF
```

(Опционально, не блокирует merge.)

---

## Task 12: Pre-flight + deploy checklist (для prod)

**Не выполняется автоматически — ассистент готовит шпаргалку, пользователь решает когда применять.**

- [ ] **Step 12.1: Создать deploy-checklist в evidence**

```bash
cat > /home/claude-user/contenthunter/docs/evidence/2026-05-07-unic-sweep-deploy-checklist.md <<'EOF'
# Deploy Checklist — unic-sweep (sub-project A)

## Pre-flight (на VPS)

1. SSH on prod, идём в `/root/.openclaw/workspace-genri/autowarm/`.
2. Запустить audit БЕЗ изменений:
   ```bash
   psql -U openclaw -d openclaw -f scripts/audit_unic_tasks_duplicates.sql
   ```
   - Если 0 строк → можно мигрировать.
   - Если строки есть → STOP. Каждую группу резолвит ops вручную (см. design doc § Migration safety).
3. Проверить имя PM2-процесса:
   ```bash
   pm2 list | grep -E "autowarm|delivery|server"
   ```

## Deploy

1. Применить миграцию (НЕ через runner — напрямую psql):
   ```bash
   psql -U openclaw -d openclaw -f migrations/20260507_unic_tasks_unique_active_slot.sql
   ```
2. Verify index:
   ```bash
   psql -U openclaw -d openclaw -c "\d unic_tasks" | grep ux_unic_tasks
   ```
3. Cherry-pick кода в prod main (auto-push hook сделает остальное), restart:
   ```bash
   pm2 restart <process_name>
   ```

## Monitoring

- T+1 мин: `pm2 logs <process> | grep unic-sweep | head -3` — должен быть стартовый log.
- T+5 мин: первый JSON-tick `{"tag":"unic-sweep","ok":true,"summary":true,...}`.
- T+30 мин: считаем `inserted` — если на dev было N застрявших слотов на сегодня, тут видим N.
- T+24ч: health-метрика возвращает 0 застрявших слотов.

## Rollback

Код:
```bash
git revert <merge_sha>
pm2 restart <process_name>
```

Миграция:
```bash
psql -U openclaw -d openclaw -f migrations/20260507_unic_tasks_unique_active_slot__rollback.sql
```

## Disable via env (без передеплоя кода)

```bash
pm2 set <process>.env.UNIC_SWEEP_DISABLED 1
pm2 restart <process>
```
EOF
git add docs/evidence/2026-05-07-unic-sweep-deploy-checklist.md
git -C /home/claude-user/contenthunter commit -m "docs(evidence): unic-sweep deploy checklist"
```

(Этот шаг — в репе `contenthunter`, не `autowarm-testbench`.)

---

## Final task: Push branch и подготовить PR (manual)

- [ ] **Step 13.1: Прогнать всё с нуля**

```bash
cd /home/claude-user/autowarm-testbench
node --test unic_sweep.test.js tests/test_unic_sweep_integration.test.js 2>&1 | tail -10
```

Expected: все green.

- [ ] **Step 13.2: Push branch**

```bash
git push -u origin feature/unic-sweep-2026-05-07
```

- [ ] **Step 13.3: Готовый changelog для пользователя**

Сообщить пользователю:
- Список коммитов: `git log --oneline main..HEAD`
- Краткое summary (что меняется, зачем)
- Ссылку на design doc и evidence
- Подождать утверждения для merge → cherry-pick в prod main.

---

## Self-Review

- **Spec coverage:** все секции спеки покрыты — миграция (T2), audit (T1), sweep helpers (T3-T4), runAutoUnicForDate patch (T5), wiring (T6), unit-тесты (T3-T4), I1-I12 integration (T7-T10), smoke (T11), deploy guide (T12). Open questions Q2/Q4/Q5/Q6 закрыты в pre-flight + по факту обнаружения test-runner pattern (`node --test`).
- **Placeholder scan:** одно место с троеточием в Task 7.0 — там написано «(тело for-loop'а — копия из Task 5 Step 5.2; перепиши его дословно, не оставляй троеточие.)». Это явная инструкция исполнителю не лениться.
- **Type consistency:** `runAutoUnicForDate` возвращает `{inserted, skipped, errors}` стабильно во всех вызовах; `state` объект `{running, timer}` един между sweep, start, stop; `pool` — pg.Pool везде.

---

## Decisions captured during plan-writing

- Test runner: `node --test` (Node.js built-in) — найден в существующих тестах `paginate.test.js`, `tests/test_pack_name_resolver.test.js`. Не добавляем Jest/vitest.
- Тесты pure-JS (не Python pytest), хотя в `autowarm-testbench/tests/` есть Python — они тестируют Python publisher, не server.js.
- `runAutoUnicForDate` извлекаем в отдельный модуль `run_auto_unic.js` для testability — это minimal refactor, не меняющий поведение, но делающий integration-тесты возможными без boot'а server.js.
- Все INSERT'ы в `unic_tasks` идут через единственную точку (`runAutoUnicForDate`), поэтому ON CONFLICT в одном месте покрывает все паттерны вызова (trigger-immediate, morning batch, sweep).
- Test fixtures используют `id <= -1000` чтобы не задевать прод-данные (паттерн из памяти `feedback_validator_test_engine_dispose.md` адаптирован для autowarm-testbench).
