# WP #165 — Защита от watchdog_subprocess_hang: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Остановить ретрай-шторм watchdog-зависаний (28 публикаций → 551 hang в инциденте 27.05), сделать всплески видимыми (TG-алерт) и закрыть слепые пятна диагностики.

**Architecture:** Два новых node-модуля (`watchdog_breaker.js`, `watchdog_alert.js`), подключаемые в `server.js` `watchdogRunningTasks()`. Breaker заменяет безусловное немедленное реквью на оконный-по-cpid backoff. Alert считает всплеск и шлёт TG (переиспользуя плумбинг daily-report). Диагностика: `last_step` в kill-событии + видимый heartbeat-сбой в `publisher_base.py` + `log_lock_waits=on` в Postgres. Всё за env kill-switch'ами. **Схема БД не меняется.**

**Tech Stack:** Node.js (server.js + pg Pool), Python (publisher_base.py), Postgres 16, PM2 (ecosystem.production.config.js), тесты — `node --test` live-DB (паттерн `test_retry_controller.test.js`).

**Базовый чекаут кода:** прод autowarm `/root/.openclaw/workspace-genri/autowarm/`. Все пути ниже — относительно него. (Спека и план живут в репо contenthunter, ветка `wp165-watchdog-hang-triage`.)

**Ключевые факты из разведки (контекст для исполнителя):**
- watchdog в `server.js:7020-7071` раз в 2 мин убивает `publish_tasks` со `status='running' AND updated_at < NOW()-3min`, ставит `error_code='watchdog_subprocess_hang'`, и **безусловно** реквьюит pq в pending (стр. 7061-7065) → бесконечный 5-мин цикл редиспатча.
- `client_publish_id` (cpid) персистентен на `publish_tasks` между ретраями; в инциденте NULL-cpid = 0.
- `publish_queue` без FK; обязательны только `id` (auto) и `client_publish_id` (auto). `publish_tasks` без обязательных-без-дефолта колонок → тестовый seed тривиален.
- heartbeat (`publisher_base.py:513-531`) глотает исключение DB-write → `updated_at` молча замерзает.
- TG-плумбинг: `daily_publish_report.js:235` (`https://api.telegram.org/bot${token}/sendMessage`), env `DAILY_REPORT_BOT_TOKEN` / `DAILY_REPORT_CHAT_ID`.
- Тест-раннер: `node --test --test-force-exit <file>.test.js`; live-тесты используют реальный `Pool` + высокие fixture-id + cleanup.

---

## Task 1: Модуль circuit-breaker (`watchdog_breaker.js`) + тест

**Files:**
- Create: `watchdog_breaker.js`
- Test: `test_watchdog_breaker.test.js`

- [ ] **Step 1: Написать падающий тест**

Create `test_watchdog_breaker.test.js`:

```javascript
// Run: node --test --test-force-exit test_watchdog_breaker.test.js
const { test, before, after, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { requeueWithBreaker, parseLastStep } = require('./watchdog_breaker');

const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

// Высокие fixture-id чтобы не пересечься с живыми данными
const CPID = 'bbbbbbbb-0000-0000-0000-000000165001';
const PQ = 9916500;
const PT_BASE = 9916500; // PT_BASE..PT_BASE+9 — синтетические hang-задачи

async function cleanup() {
  await pool.query('DELETE FROM publish_queue WHERE id=$1', [PQ]).catch(()=>{});
  await pool.query('DELETE FROM publish_tasks WHERE client_publish_id=$1', [CPID]).catch(()=>{});
}

// Сидим N уже-упавших watchdog-hang задач по cpid + одну running pq, привязанную к ptId
async function seed(nPriorHangs, ptId) {
  await cleanup();
  for (let i = 0; i < nPriorHangs; i++) {
    await pool.query(
      `INSERT INTO publish_tasks (id, client_publish_id, platform, account, status, error_code, updated_at)
       VALUES ($1,$2,'Instagram','acc','failed','watchdog_subprocess_hang', NOW() - INTERVAL '5 minutes')`,
      [PT_BASE + i, CPID]
    );
  }
  // Текущая «только что упавшая» задача (watchdog уже пометил failed)
  await pool.query(
    `INSERT INTO publish_tasks (id, client_publish_id, platform, account, status, error_code, updated_at)
     VALUES ($1,$2,'Instagram','acc','failed','watchdog_subprocess_hang', NOW())`,
    [ptId, CPID]
  );
  await pool.query(
    `INSERT INTO publish_queue (id, publish_task_id, status, scheduled_at, client_publish_id)
     VALUES ($1,$2,'running', NOW(), $3)`,
    [PQ, ptId, CPID]
  );
}

before(async () => { await cleanup(); });
after(async () => { await cleanup(); await pool.end(); });

test('под порогом → немедленное реквью (scheduled_at ≈ now)', async () => {
  const ptId = PT_BASE + 8;
  await seed(1, ptId); // всего 2 hang (1 прошлый + текущая) < 3
  const res = await requeueWithBreaker(pool, { id: ptId, client_publish_id: CPID },
    { WATCHDOG_BREAKER_ENABLED:'true', WATCHDOG_BREAKER_MAX_HANGS:'3', WATCHDOG_BREAKER_WINDOW_MIN:'60', WATCHDOG_BREAKER_BACKOFF_HOURS:'6' });
  assert.equal(res.action, 'immediate');
  const { rows } = await pool.query('SELECT status, publish_task_id, scheduled_at FROM publish_queue WHERE id=$1', [PQ]);
  assert.equal(rows[0].status, 'pending');
  assert.equal(rows[0].publish_task_id, null);
  const deltaSec = Math.abs((new Date(rows[0].scheduled_at) - new Date()) / 1000);
  assert.ok(deltaSec < 120, `scheduled_at должен быть ≈ now, дельта=${deltaSec}s`);
});

test('на пороге → backoff-реквью (scheduled_at ≈ now+6ч)', async () => {
  const ptId = PT_BASE + 9;
  await seed(2, ptId); // всего 3 hang (2 прошлых + текущая) >= 3
  const res = await requeueWithBreaker(pool, { id: ptId, client_publish_id: CPID },
    { WATCHDOG_BREAKER_ENABLED:'true', WATCHDOG_BREAKER_MAX_HANGS:'3', WATCHDOG_BREAKER_WINDOW_MIN:'60', WATCHDOG_BREAKER_BACKOFF_HOURS:'6' });
  assert.equal(res.action, 'backoff');
  const { rows } = await pool.query('SELECT status, scheduled_at FROM publish_queue WHERE id=$1', [PQ]);
  assert.equal(rows[0].status, 'pending');
  const deltaH = (new Date(rows[0].scheduled_at) - new Date()) / 3600000;
  assert.ok(deltaH > 5.5 && deltaH < 6.5, `scheduled_at должен быть ≈ now+6ч, дельта=${deltaH}ч`);
});

test('kill-switch off → всегда немедленно', async () => {
  const ptId = PT_BASE + 9;
  await seed(5, ptId); // далеко за порогом
  const res = await requeueWithBreaker(pool, { id: ptId, client_publish_id: CPID },
    { WATCHDOG_BREAKER_ENABLED:'false', WATCHDOG_BREAKER_MAX_HANGS:'3', WATCHDOG_BREAKER_WINDOW_MIN:'60', WATCHDOG_BREAKER_BACKOFF_HOURS:'6' });
  assert.equal(res.action, 'immediate');
});

test('NULL cpid → немедленно (breaker неприменим)', async () => {
  const ptId = PT_BASE + 7;
  await cleanup();
  await pool.query(
    `INSERT INTO publish_tasks (id, platform, account, status, error_code, updated_at)
     VALUES ($1,'Instagram','acc','failed','watchdog_subprocess_hang', NOW())`, [ptId]);
  await pool.query(
    `INSERT INTO publish_queue (id, publish_task_id, status, scheduled_at)
     VALUES ($1,$2,'running', NOW())`, [PQ, ptId]);
  const res = await requeueWithBreaker(pool, { id: ptId, client_publish_id: null },
    { WATCHDOG_BREAKER_ENABLED:'true', WATCHDOG_BREAKER_MAX_HANGS:'3', WATCHDOG_BREAKER_WINDOW_MIN:'60', WATCHDOG_BREAKER_BACKOFF_HOURS:'6' });
  assert.equal(res.action, 'immediate');
  await pool.query('DELETE FROM publish_queue WHERE id=$1', [PQ]).catch(()=>{});
  await pool.query('DELETE FROM publish_tasks WHERE id=$1', [ptId]).catch(()=>{});
});

test('parseLastStep: из лога с 💓 берёт последний шаг', () => {
  const log = '\n[21:00:01] 💓 [Instagram] инициализация\n[21:00:31] 💓 [Instagram] переключение аккаунта';
  assert.equal(parseLastStep(log), 'переключение аккаунта');
});

test('parseLastStep: пустой/без heartbeat → null', () => {
  assert.equal(parseLastStep(''), null);
  assert.equal(parseLastStep(null), null);
  assert.equal(parseLastStep('\n[21:00:01] какой-то другой лог'), null);
});
```

- [ ] **Step 2: Запустить тест — убедиться что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit test_watchdog_breaker.test.js`
Expected: FAIL — `Cannot find module './watchdog_breaker'`.

- [ ] **Step 3: Создать модуль**

Create `watchdog_breaker.js`:

```javascript
// watchdog_breaker.js — WP#165.
// Circuit-breaker для watchdog-реквью. При повторных watchdog_subprocess_hang по
// одной публикации (cpid) в окне — реквьюит с backoff-задержкой вместо немедленного,
// чтобы остановить ретрай-шторм (инцидент 27.05: 28 публикаций × ~20 ретраев = 551 hang).
'use strict';

function num(v, d) { const n = parseInt(v, 10); return Number.isFinite(n) ? n : d; }

// task: { id, client_publish_id }. Вызывается ПОСЛЕ того как watchdog пометил задачу failed.
async function requeueWithBreaker(pool, task, env = process.env) {
  const enabled   = env.WATCHDOG_BREAKER_ENABLED !== 'false';
  const maxHangs  = num(env.WATCHDOG_BREAKER_MAX_HANGS, 3);
  const windowMin = num(env.WATCHDOG_BREAKER_WINDOW_MIN, 60);
  const backoffH  = num(env.WATCHDOG_BREAKER_BACKOFF_HOURS, 6);
  const cpid = task.client_publish_id;

  let action = 'immediate';
  if (enabled && cpid) {
    const { rows } = await pool.query(
      `SELECT count(*)::int AS n FROM publish_tasks
       WHERE client_publish_id = $1
         AND error_code = 'watchdog_subprocess_hang'
         AND updated_at > NOW() - ($2 || ' minutes')::interval`,
      [cpid, String(windowMin)]
    );
    if (rows[0].n >= maxHangs) action = 'backoff';
  }

  if (action === 'backoff') {
    await pool.query(
      `UPDATE publish_queue
         SET status='pending', publish_task_id=NULL,
             scheduled_at = NOW() + ($2 || ' hours')::interval, updated_at=NOW()
       WHERE publish_task_id=$1 AND status='running'`,
      [task.id, String(backoffH)]
    );
  } else {
    await pool.query(
      `UPDATE publish_queue
         SET status='pending', publish_task_id=NULL, updated_at=NOW()
       WHERE publish_task_id=$1 AND status='running'`,
      [task.id]
    );
  }
  return { action };
}

// Достаёт последний шаг из publish_tasks.log (heartbeat пишет "💓 [Platform] {шаг}").
function parseLastStep(log) {
  if (!log) return null;
  const matches = String(log).match(/💓 \[[^\]]*\] [^\n]+/g);
  if (!matches || !matches.length) return null;
  const m = matches[matches.length - 1].match(/💓 \[[^\]]*\] (.+)$/);
  return m ? m[1].trim() : null;
}

module.exports = { requeueWithBreaker, parseLastStep };
```

- [ ] **Step 4: Запустить тест — убедиться что проходит**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit test_watchdog_breaker.test.js`
Expected: PASS (6 tests).

- [ ] **Step 5: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add watchdog_breaker.js test_watchdog_breaker.test.js
git commit -m "feat(wp165): circuit-breaker модуль для watchdog-реквью (оконный + backoff)"
```

---

## Task 2: Интеграция breaker + last_step в `server.js` watchdog

**Files:**
- Modify: `server.js` (require ~стр. 6987 рядом; SELECT 7022-7029; kill-событие 7034-7045; реквью 7060-7066)

- [ ] **Step 1: Добавить require breaker**

Найти `const { retryFailedPublishes } = require('./retry_controller');` (≈стр. 6987) и **добавить строкой ниже**:

```javascript
const { requeueWithBreaker, parseLastStep } = require('./watchdog_breaker');
```

- [ ] **Step 2: Добавить `client_publish_id` в SELECT watchdog'а**

В `watchdogRunningTasks()` заменить SELECT (стр. 7022-7029):

```javascript
    const { rows } = await pool.query(`
      SELECT pt.id, pt.platform, pt.account,
             EXTRACT(EPOCH FROM (NOW() - pt.updated_at))/60 AS stale_min,
             pt.log, pt.client_publish_id
      FROM publish_tasks pt
      WHERE pt.status = 'running'
        AND pt.updated_at < NOW() - INTERVAL '3 minutes'
    `);
```

- [ ] **Step 3: Добавить `last_step` в meta kill-события**

В объекте `errorEvent.meta` (стр. 7038-7044) добавить поле `last_step` (гейт `WATCHDOG_DIAG_ENABLED`):

```javascript
        meta: {
          category: 'watchdog_subprocess_hang',
          reason: 'watchdog_subprocess_hang',
          stale_min: staleMin,
          platform: task.platform,
          source: 'server.js:watchdogRunningTasks',
          last_step: process.env.WATCHDOG_DIAG_ENABLED === 'false' ? undefined : parseLastStep(task.log),
        },
```

- [ ] **Step 4: Заменить безусловное реквью на breaker**

Заменить блок реквью (стр. 7060-7066) — был:

```javascript
      // Сбрасываем pq обратно в pending чтобы переотправить
      await pool.query(
        `UPDATE publish_queue SET status='pending', publish_task_id=NULL, updated_at=NOW()
         WHERE publish_task_id=$1 AND status='running'`,
        [task.id]
      );
      console.log(`[watchdog] task#${task.id} → failed (error_code=watchdog_subprocess_hang), pq → pending (будет переотправлена)`);
```

на:

```javascript
      // WP#165: реквью через circuit-breaker (оконный по cpid + backoff против шторма)
      const { action } = await requeueWithBreaker(pool, { id: task.id, client_publish_id: task.client_publish_id });
      console.log(`[watchdog] task#${task.id} → failed (watchdog_subprocess_hang), pq → pending [${action}]`);
```

- [ ] **Step 5: Smoke — синтаксис + запуск без падения**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node -c server.js && echo "SYNTAX OK"`
Expected: `SYNTAX OK` (статическая проверка; полный рестарт — на деплое, Task 7).

- [ ] **Step 6: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js
git commit -m "feat(wp165): подключить circuit-breaker + last_step-диагностику в watchdog"
```

---

## Task 3: Модуль алерта (`watchdog_alert.js`) + тест

**Files:**
- Create: `watchdog_alert.js`
- Test: `test_watchdog_alert.test.js`

- [ ] **Step 1: Написать падающий тест**

Create `test_watchdog_alert.test.js`:

```javascript
// Run: node --test --test-force-exit test_watchdog_alert.test.js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { maybeAlertHangSpike, _resetCooldownForTest } = require('./watchdog_alert');

const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });
const CPID = 'cccccccc-0000-0000-0000-000000165001';
const PT_BASE = 9916600;

async function cleanup() {
  await pool.query('DELETE FROM publish_tasks WHERE client_publish_id=$1', [CPID]).catch(()=>{});
}
async function seedHangs(n) {
  await cleanup();
  for (let i = 0; i < n; i++) {
    await pool.query(
      `INSERT INTO publish_tasks (id, client_publish_id, platform, account, status, error_code, updated_at)
       VALUES ($1,$2,'Instagram','acc','failed','watchdog_subprocess_hang', NOW())`,
      [PT_BASE + i, CPID]
    );
  }
}
const ENV = {
  WATCHDOG_ALERT_ENABLED:'true', WATCHDOG_ALERT_THRESHOLD:'5',
  WATCHDOG_ALERT_WINDOW_MIN:'30', WATCHDOG_ALERT_COOLDOWN_MIN:'60',
  DAILY_REPORT_BOT_TOKEN:'tok', DAILY_REPORT_CHAT_ID:'chat',
};

before(async () => { await cleanup(); });
after(async () => { await cleanup(); await pool.end(); });

test('ниже порога → не шлёт', async () => {
  _resetCooldownForTest();
  await seedHangs(4); // < 5
  let called = 0;
  const res = await maybeAlertHangSpike(pool, ENV, { fetch: async () => { called++; return { ok:true }; }, now: () => Date.now() });
  assert.equal(res.sent, false);
  assert.equal(res.reason, 'below_threshold');
  assert.equal(called, 0);
});

test('на пороге → шлёт TG', async () => {
  _resetCooldownForTest();
  await seedHangs(6); // >= 5
  let body = null;
  const res = await maybeAlertHangSpike(pool, ENV, { fetch: async (url, opt) => { body = JSON.parse(opt.body); return { ok:true }; }, now: () => Date.now() });
  assert.equal(res.sent, true);
  assert.ok(body.text.includes('6'));
  assert.equal(body.chat_id, 'chat');
});

test('cooldown → второй вызов не шлёт', async () => {
  _resetCooldownForTest();
  await seedHangs(6);
  const t0 = 1000000;
  let calls = 0;
  const deps = { fetch: async () => { calls++; return { ok:true }; }, now: () => t0 };
  await maybeAlertHangSpike(pool, ENV, deps);      // отправит, запомнит t0
  const res2 = await maybeAlertHangSpike(pool, ENV, { ...deps, now: () => t0 + 60*1000 }); // +1 мин < cooldown
  assert.equal(res2.sent, false);
  assert.equal(res2.reason, 'cooldown');
  assert.equal(calls, 1);
});

test('kill-switch off → не шлёт', async () => {
  _resetCooldownForTest();
  await seedHangs(10);
  const res = await maybeAlertHangSpike(pool, { ...ENV, WATCHDOG_ALERT_ENABLED:'false' }, { fetch: async () => ({ ok:true }), now: () => Date.now() });
  assert.equal(res.sent, false);
  assert.equal(res.reason, 'kill_switch');
});
```

- [ ] **Step 2: Запустить тест — убедиться что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit test_watchdog_alert.test.js`
Expected: FAIL — `Cannot find module './watchdog_alert'`.

- [ ] **Step 3: Создать модуль**

Create `watchdog_alert.js`:

```javascript
// watchdog_alert.js — WP#165.
// При всплеске watchdog_subprocess_hang за окно шлёт TG-алерт (переиспользует
// плумбинг daily_publish_report). In-memory cooldown-дедуп, чтобы не спамить шторм.
'use strict';

function num(v, d) { const n = parseInt(v, 10); return Number.isFinite(n) ? n : d; }
let _lastAlertMs = 0;
let _inFlight = false;
let _inFlightSince = 0;
const MAX_INFLIGHT_MS = 120000; // > watchdog-интервал (2 мин): зависший вызов само-сбрасывается

async function maybeAlertHangSpike(pool, env = process.env, deps = {}) {
  const fetchFn = deps.fetch || global.fetch;
  const now = deps.now || (() => Date.now());

  if (env.WATCHDOG_ALERT_ENABLED === 'false') return { sent: false, reason: 'kill_switch' };
  // in-flight guard (time-bounded): watchdog тикает каждые 2 мин fire-and-forget; перекрывающиеся
  // вызовы не должны слать дубль-алерт. Латч само-сбрасывается через MAX_INFLIGHT_MS, чтобы
  // зависший pool.query/fetch не заглушил алерт навсегда до рестарта.
  if (_inFlight && (now() - _inFlightSince) < MAX_INFLIGHT_MS) return { sent: false, reason: 'in_flight' };
  _inFlight = true;
  _inFlightSince = now();
  try {
    const threshold   = num(env.WATCHDOG_ALERT_THRESHOLD, 20);
    const windowMin   = num(env.WATCHDOG_ALERT_WINDOW_MIN, 30);
    const cooldownMin = num(env.WATCHDOG_ALERT_COOLDOWN_MIN, 60);
    const token  = env.DAILY_REPORT_BOT_TOKEN;
    const chatId = env.DAILY_REPORT_CHAT_ID;

    const { rows } = await pool.query(
      `SELECT count(*)::int AS total,
              count(*) FILTER (WHERE platform='Instagram')::int AS ig,
              count(*) FILTER (WHERE platform='TikTok')::int    AS tt,
              count(*) FILTER (WHERE platform='YouTube')::int   AS yt,
              count(DISTINCT client_publish_id)::int            AS cpids
       FROM publish_tasks
       WHERE error_code='watchdog_subprocess_hang'
         AND updated_at > NOW() - ($1 || ' minutes')::interval`,
      [String(windowMin)]
    );
    const r = rows[0];
    if (r.total < threshold) return { sent: false, reason: 'below_threshold', total: r.total };
    // cooldown применяем только если уже был успешный алерт (иначе первый вызов ложно «cooldown»)
    if (_lastAlertMs > 0 && now() - _lastAlertMs < cooldownMin * 60 * 1000) return { sent: false, reason: 'cooldown', total: r.total };
    if (!token || !chatId) { console.error('[watchdog-alert] missing DAILY_REPORT_BOT_TOKEN/CHAT_ID'); return { sent: false, reason: 'no_tg_config', total: r.total }; }

    const text = `🚨 <b>watchdog_subprocess_hang всплеск</b>\n`
      + `За ${windowMin} мин: <b>${r.total}</b> зависаний (IG ${r.ig} / TT ${r.tt} / YT ${r.yt}), публикаций затронуто: ${r.cpids}.\n`
      + `Проверьте autowarm / ADB-мост / Postgres-локи (log_lock_waits).`;
    // Таймаут на сетевой вызов: watchdog-тик не должен висеть на зависшем TG.
    const timeoutMs = num(env.WATCHDOG_ALERT_TIMEOUT_MS, 10000);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const resp = await fetchFn(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: chatId, text, parse_mode: 'HTML', disable_web_page_preview: true }),
        signal: ctrl.signal,
      });
      if (!resp.ok) { console.error(`[watchdog-alert] TG status ${resp.status}`); return { sent: false, reason: 'tg_error', total: r.total }; }
      _lastAlertMs = now();
      return { sent: true, total: r.total };
    } catch (e) {
      console.error(`[watchdog-alert] send failed: ${e.message}`);
      return { sent: false, reason: 'exception', total: r.total };
    } finally {
      clearTimeout(timer);
    }
  } finally {
    _inFlight = false;
  }
}

function _resetCooldownForTest() { _lastAlertMs = 0; _inFlight = false; _inFlightSince = 0; }
module.exports = { maybeAlertHangSpike, _resetCooldownForTest };
```

- [ ] **Step 4: Запустить тест — убедиться что проходит**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit test_watchdog_alert.test.js`
Expected: PASS (4 tests).

- [ ] **Step 5: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add watchdog_alert.js test_watchdog_alert.test.js
git commit -m "feat(wp165): модуль TG-алерта при всплеске watchdog-зависаний"
```

---

## Task 4: Подключить алерт в `server.js` watchdog

**Files:**
- Modify: `server.js` (require рядом с Task 2; вызов в конце `watchdogRunningTasks`)

- [ ] **Step 1: Добавить require**

Рядом с require из Task 2 добавить:

```javascript
const { maybeAlertHangSpike } = require('./watchdog_alert');
```

- [ ] **Step 2: Вызвать алерт после обработки задач**

В `watchdogRunningTasks()`, **после** цикла `for (const task of rows) { ... }` и **до** `catch` (т.е. перед закрывающей скобкой try, ≈стр. 7067), добавить.
**Важно: fire-and-forget (без `await`)** — watchdog-тик не должен ждать сетевой вызов TG
(сам модуль тоже имеет timeout, это вторая линия защиты):

```javascript
    // WP#165: проверить всплеск зависаний и алертнуть — НЕ блокируя watchdog-тик
    maybeAlertHangSpike(pool).catch(e => console.error('[watchdog-alert]', e.message));
```

- [ ] **Step 3: Smoke — синтаксис**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node -c server.js && echo "SYNTAX OK"`
Expected: `SYNTAX OK`.

- [ ] **Step 4: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js
git commit -m "feat(wp165): вызывать алерт всплеска в watchdog-тике"
```

---

## Task 5: Видимый heartbeat-сбой в `publisher_base.py` (C2)

**Files:**
- Modify: `publisher_base.py:530-531` (except-ветка heartbeat-цикла)
- Test: `test_heartbeat_visibility.py`

- [ ] **Step 1: Написать падающий python-тест**

Create `test_heartbeat_visibility.py`:

```python
# Run: cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest test_heartbeat_visibility.py -v
import os, sys, types, importlib

def test_heartbeat_failure_writes_stderr_and_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('WATCHDOG_DIAG_ENABLED', 'true')
    # Перенаправляем файл-fallback в tmp
    fail_dir = tmp_path / 'hb_fail'
    from publisher_base import _record_heartbeat_failure  # извлечённый хелпер
    _record_heartbeat_failure(task_id=9916700, exc=RuntimeError('lock timeout'), base_dir=str(fail_dir))
    err = capsys.readouterr().err
    assert 'heartbeat_fail task=9916700' in err
    assert 'RuntimeError: lock timeout' in err
    f = fail_dir / '9916700.log'
    assert f.exists()
    assert 'RuntimeError: lock timeout' in f.read_text()

def test_heartbeat_failure_gated_off(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('WATCHDOG_DIAG_ENABLED', 'false')
    from publisher_base import _record_heartbeat_failure
    fail_dir = tmp_path / 'hb_fail2'
    _record_heartbeat_failure(task_id=9916701, exc=RuntimeError('x'), base_dir=str(fail_dir))
    err = capsys.readouterr().err
    assert 'heartbeat_fail' not in err
    assert not (fail_dir / '9916701.log').exists()
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest test_heartbeat_visibility.py -v`
Expected: FAIL — `ImportError: cannot import name '_record_heartbeat_failure'`.

- [ ] **Step 3: Добавить хелпер + вызвать из except**

В `publisher_base.py` добавить модульный хелпер (рядом с другими module-level функциями, например после импортов/до класса):

```python
def _record_heartbeat_failure(task_id, exc, base_dir='/tmp/autowarm_heartbeat_fail'):
    """WP#165: сделать сбой heartbeat-записи видимым.
    Корень инцидента 27.05 был невидим — DB-write молча падал, updated_at замерзал,
    watchdog убивал с 0 событий. Дублируем текст исключения в stderr (его перехватывает
    scheduler с префиксом [publish#id]) и в файл-fallback."""
    if os.environ.get('WATCHDOG_DIAG_ENABLED', 'true') == 'false':
        return
    msg = f'{type(exc).__name__}: {exc}'
    try:
        sys.stderr.write(f'[heartbeat_fail task={task_id}] {msg}\n')
        sys.stderr.flush()
    except Exception:
        pass
    try:
        os.makedirs(base_dir, exist_ok=True)
        with open(f'{base_dir}/{task_id}.log', 'a') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')
    except Exception:
        pass
```

Убедиться, что вверху файла есть `import os`, `import sys`, `import time` (добавить недостающие). Затем в heartbeat-цикле (стр. 530-531) заменить:

```python
            except Exception as e:
                log.warning(f'heartbeat error: {e}')
```

на:

```python
            except Exception as e:
                log.warning(f'heartbeat error: {e}')
                _record_heartbeat_failure(self.task_id, e)
```

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest test_heartbeat_visibility.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Проверить, что модуль импортируется (не сломали publisher)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python3 -c "import publisher_base; print('IMPORT OK')"`
Expected: `IMPORT OK`.

- [ ] **Step 6: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_base.py test_heartbeat_visibility.py
git commit -m "feat(wp165): сделать сбой heartbeat-записи видимым (stderr + файл-fallback)"
```

---

## Task 6: Kill-switch'и в `ecosystem.production.config.js`

**Files:**
- Modify: `ecosystem.production.config.js` (env-блок autowarm-приложения)

- [ ] **Step 1: Добавить env-переменные**

В `env: { ... }` блоке autowarm-приложения (рядом с `TT_BOUND_NAV_ENABLED`) добавить:

```javascript
        // WP#165 watchdog circuit-breaker + алерт + диагностика. Kill-switch'и:
        // *_ENABLED='false' откатывает компонент. См. spec 2026-05-27-wp165.
        WATCHDOG_BREAKER_ENABLED: 'true',
        WATCHDOG_BREAKER_MAX_HANGS: '3',
        WATCHDOG_BREAKER_WINDOW_MIN: '60',
        WATCHDOG_BREAKER_BACKOFF_HOURS: '6',
        WATCHDOG_ALERT_ENABLED: 'true',
        WATCHDOG_ALERT_THRESHOLD: '20',
        WATCHDOG_ALERT_WINDOW_MIN: '30',
        WATCHDOG_ALERT_COOLDOWN_MIN: '60',
        WATCHDOG_ALERT_TIMEOUT_MS: '10000',
        WATCHDOG_DIAG_ENABLED: 'true',
```

> Примечание: `DAILY_REPORT_BOT_TOKEN` / `DAILY_REPORT_CHAT_ID` уже должны быть в окружении (используются daily-report). Если их нет — алерт логирует `no_tg_config` и не падает.

- [ ] **Step 2: Smoke — конфиг валиден**

Run: `cd /root/.openclaw/workspace-genri/autowarm && node -e "require('./ecosystem.production.config.js'); console.log('CONFIG OK')"`
Expected: `CONFIG OK`.

- [ ] **Step 3: Коммит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add ecosystem.production.config.js
git commit -m "chore(wp165): kill-switch'и watchdog-защиты в ecosystem.production"
```

---

## Task 7: Деплой + C3 (log_lock_waits) + прогон тестов

**Files:** ops-шаги (без правок репо, кроме уже закоммиченного)

- [ ] **Step 1: Прогнать все новые тесты разом**

Run (СЕРИЙНО — live-DB тесты не должны идти параллельно, общая таблица):
```bash
cd /home/claude-user/autowarm-wp165
node --test --test-force-exit --test-concurrency=1 test_watchdog_breaker.test.js test_watchdog_alert.test.js
python3 -m pytest test_heartbeat_visibility.py -v
```
Expected: все PASS (breaker 6 + alert 4 + heartbeat 2).

> **As-built:** alert-тест сделан **baseline-aware** (порог относительно реальных hang в окне),
> иначе флапает от контаминации реальными `watchdog_subprocess_hang` или фикстурами параллельных
> файлов (урок feedback_livedb_controller_test_isolation). Многофайловый прогон — только `--test-concurrency=1`.

- [ ] **Step 2: `codex review` диффа (правило для WP — раундами до 0 P1)**

Run: `cd /root/.openclaw/workspace-genri/autowarm && git diff HEAD~5 | ~/.local/bin/codex review -`
Адресовать P1 (если есть), повторить. Затем юзеру.

- [ ] **Step 3: C3 — включить log_lock_waits в Postgres**

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET log_lock_waits = on;"
sudo systemctl reload postgresql
sudo -u postgres psql -tAc "SHOW log_lock_waits;"   # ожидаем: on
```
Откат: `ALTER SYSTEM SET log_lock_waits = off;` + reload.

- [ ] **Step 4: Деплой autowarm (PM2 restart)**

Код уже в прод-чекауте (`/root/.openclaw/workspace-genri/autowarm`). Перезапустить воркер:
```bash
sudo pm2 restart autowarm
sudo pm2 describe autowarm | grep -E "status|exec cwd"   # online + правильный cwd
```
(Проверка `exec cwd` — против дрейфа PM2-пути, см. урок pm2_dump_path_drift.)

- [ ] **Step 5: Пост-деплой smoke (live)**

```bash
# 5–10 мин после рестарта: алерт-модуль не падает, breaker логирует action
grep -aE "\[watchdog\].*\[(immediate|backoff)\]|watchdog-alert" /var/log/autowarm-out.log | tail -20
```
Expected: watchdog-строки с `[immediate]`/`[backoff]`; ошибок модулей нет.

- [ ] **Step 6: Evidence + закрытие**

Записать в `docs/evidence/2026-05-27-wp165-*.md` (репо contenthunter): прогон тестов, codex-результат, deploy SHA, пост-деплой наблюдения. Обновить OpenProject #165 (house style: Что было не так → Что сделано → Что осталось). Обновить память.

---

## Self-review заметки (для исполнителя)

- **Покрытие спеки:** A (breaker) → Task 1+2; B (alert) → Task 3+4; C1 (last_step) → Task 2 step 3; C2 (heartbeat visibility) → Task 5; C3 (log_lock_waits) → Task 7 step 3; kill-switch'и → Task 6. Вне scope (ADB-preflight, зомби) — задач нет, верно.
- **Тесты live-DB:** требуют доступного Postgres `openclaw:openclaw123@localhost`. Fixture-id 99165xx/99166xx/99167xx не пересекаются с живыми.
- **Порядок:** Task 2 зависит от Task 1 (модуль); Task 4 от Task 3; остальное независимо. Деплой (Task 7) — последним.
