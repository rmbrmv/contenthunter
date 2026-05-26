# Таблица статусов телефонов (WP #157) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Операторский read-only экран-таблица: по каждому телефону (малинке) текущий статус (занят/свободен/offline/завис) + подробная строка лога, с поллингом ~7с, чтобы оператор перед действием на телефоне видел, ведёт ли его автоматика.

**Architecture:** Чистая функция `resolvePhoneStatus` (приоритет статусов, active/reserved/stale/unknown/offline/free, fail-closed при недоступном источнике) + серверный `fetchPhoneStatuses(pool)`, который читает 6 таблиц задач по `device_serial` + реестр телефонов, нормализует и зовёт резолвер. Новый эндпоинт `GET /api/devices/status` + новый раздел во фронте. Без миграций, без правок воркеров.

**Tech Stack:** Node.js (Express, `pg` Pool), ванильный JS фронт (`public/index.html`), тесты `node:test` + `node:assert/strict`. БД PostgreSQL `openclaw` (localhost:5432, openclaw/openclaw123).

**Где исполнять:** в worktree кодового репо. Перед Task 1 создать его (using-git-worktrees), напр. `git worktree add /home/claude-user/autowarm-testbench-wp157 -b feat/wp157-phone-status origin/main` в кодовом репо. Прод-деплой — отдельная заключительная задача. Спека: `docs/superpowers/specs/2026-05-26-wp157-phone-status-table-design.md`.

---

## Структура файлов

- **Create** `phone_status.js` — ядро: чистые `resolvePhoneStatus`, `lastLogLine`, константы `PHONE_STATUS_PRIORITY`/`PHONE_STATUS_LABELS`; серверная `fetchPhoneStatuses(pool, now)`. Pool передаётся аргументом (как в `manual_publish_queue.js`). НЕ требует `pg`.
- **Create** `test_phone_status_pure.test.js` (корень репо) — юнит-тесты чистых функций (как `test_mpq_pure.test.js`).
- **Modify** `server.js` — `require('./phone_status')` рядом со строкой 14; новый обработчик `GET /api/devices/status` (стиль `requireAuth` + try/catch + `res.json`).
- **Modify** `public/index.html` — nav-кнопка `nav('phone-status')` в группе «Выкладка»; секция `#section-phone-status` с баннером деградации + таблицей; функции `phsLoad/phsPoll/phsRender/phsBadge` + `setInterval`.

---

## Task 1: Чистые помощники — `lastLogLine` + константы

**Files:**
- Create: `phone_status.js`
- Test: `test_phone_status_pure.test.js`

- [ ] **Step 1: Написать падающий тест**

`test_phone_status_pure.test.js`:
```javascript
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { lastLogLine, PHONE_STATUS_LABELS } = require('./phone_status');

test('lastLogLine: берёт msg последнего события с ts', () => {
  const events = [{ ts: '10:00:00', msg: 'старт' }, { ts: '10:01:02', msg: 'шаг 2' }];
  assert.equal(lastLogLine(events, ''), '10:01:02 шаг 2');
});

test('lastLogLine: без events падает на хвост log', () => {
  assert.equal(lastLogLine(null, 'строка1\nстрока2'), 'строка2');
});

test('lastLogLine: пусто → пустая строка', () => {
  assert.equal(lastLogLine(null, ''), '');
  assert.equal(lastLogLine([], null), '');
});

test('PHONE_STATUS_LABELS покрывают все 6 типов', () => {
  for (const t of ['manual_publish','auto_publish','account_create','warmup','phone_warmup','archive_check']) {
    assert.equal(typeof PHONE_STATUS_LABELS[t], 'string');
  }
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test test_phone_status_pure.test.js`
Expected: FAIL — `Cannot find module './phone_status'`.

- [ ] **Step 3: Создать `phone_status.js` с минимальной реализацией**

`phone_status.js`:
```javascript
'use strict';
// phone_status.js — статусы телефонов (WP #157). Чистые функции (resolvePhoneStatus,
// lastLogLine) + серверная fetchPhoneStatuses(pool). Pool передаётся аргументом.

const PHONE_STATUS_PRIORITY = [
  'manual_publish', 'auto_publish', 'account_create', 'warmup', 'phone_warmup', 'archive_check',
];

const PHONE_STATUS_LABELS = {
  manual_publish: 'ручная выкладка',
  auto_publish:   'автовыкладка',
  account_create: 'создание аккаунтов',
  warmup:         'прогрев (аккаунт)',
  phone_warmup:   'прогрев (телефон)',
  archive_check:  'проверка выложенного',
};

// Последняя осмысленная строка лога задачи: msg последнего события, иначе хвост log.
function lastLogLine(events, log) {
  if (Array.isArray(events) && events.length) {
    const e = events[events.length - 1];
    if (e && e.msg) return (e.ts ? e.ts + ' ' : '') + e.msg;
  }
  if (typeof log === 'string' && log.trim()) {
    const lines = log.trim().split('\n');
    return lines[lines.length - 1].slice(0, 200);
  }
  return '';
}

module.exports = { PHONE_STATUS_PRIORITY, PHONE_STATUS_LABELS, lastLogLine };
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test test_phone_status_pure.test.js`
Expected: PASS (4 теста).

- [ ] **Step 5: Commit**

```bash
git add phone_status.js test_phone_status_pure.test.js
git commit -m "feat(wp157): phone_status helpers — lastLogLine + labels (TDD)"
```

---

## Task 2: Чистая функция `resolvePhoneStatus`

**Files:**
- Modify: `phone_status.js`
- Test: `test_phone_status_pure.test.js`

`resolvePhoneStatus(input)` принимает нормализованный вход и решает статус. `input`:
- `activities`: массив `{ type, state:'active'|'reserved', detail, updatedAt }` (updatedAt — ms epoch или null)
- `online`: boolean|null; `hasDeviceState`: boolean
- `now`: ms; `staleMs`: число; `failedSources`: массив строк
Возвращает `{ status, kind, detail, stale, updatedAt }`, kind ∈ busy/stale/reserved/unknown/offline/free.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `test_phone_status_pure.test.js`:
```javascript
const { resolvePhoneStatus } = require('./phone_status');
const NOW = 1_700_000_000_000;
const base = { online: true, hasDeviceState: true, now: NOW, staleMs: 600000, failedSources: [] };

test('resolve: свежая ACTIVE → busy с меткой типа', () => {
  const r = resolvePhoneStatus({ ...base, activities: [
    { type: 'auto_publish', state: 'active', detail: 'грузим', updatedAt: NOW - 1000 },
  ]});
  assert.equal(r.kind, 'busy');
  assert.equal(r.status, 'автовыкладка');
  assert.equal(r.detail, 'грузим');
});

test('resolve: приоритет — ручная бьёт автовыкладку при двух свежих ACTIVE', () => {
  const r = resolvePhoneStatus({ ...base, activities: [
    { type: 'auto_publish',   state: 'active', detail: 'a', updatedAt: NOW - 1000 },
    { type: 'manual_publish', state: 'active', detail: 'm', updatedAt: NOW - 1000 },
  ]});
  assert.equal(r.status, 'ручная выкладка');
});

test('resolve: залипшая ACTIVE (старше порога) → stale, НЕ свободен', () => {
  const r = resolvePhoneStatus({ ...base, activities: [
    { type: 'warmup', state: 'active', detail: 'день 3', updatedAt: NOW - 20 * 60000 },
  ]});
  assert.equal(r.kind, 'stale');
  assert.match(r.status, /возможно завис/);
  assert.match(r.detail, /нет обновлений 20 мин/);
});

test('resolve: свежая ACTIVE бьёт offline-показание device_state', () => {
  const r = resolvePhoneStatus({ ...base, online: false, activities: [
    { type: 'account_create', state: 'active', detail: 'gmail', updatedAt: NOW - 5000 },
  ]});
  assert.equal(r.kind, 'busy');
});

test('resolve: только RESERVED (paused) → reserved «на паузе»', () => {
  const r = resolvePhoneStatus({ ...base, activities: [
    { type: 'phone_warmup', state: 'reserved', detail: 'день 2/7', updatedAt: NOW - 1000 },
  ]});
  assert.equal(r.kind, 'reserved');
  assert.match(r.status, /на паузе/);
});

test('resolve: нет активности, offline=false → offline', () => {
  const r = resolvePhoneStatus({ ...base, online: false, activities: [] });
  assert.equal(r.kind, 'offline');
});

test('resolve: нет активности, online → свободен', () => {
  const r = resolvePhoneStatus({ ...base, activities: [] });
  assert.equal(r.kind, 'free');
  assert.equal(r.status, 'свободен');
});

test('resolve: fail-closed — упал источник, нет подтверждённой ACTIVE → unknown (не свободен/offline)', () => {
  const r = resolvePhoneStatus({ ...base, activities: [], failedSources: ['factory_reg_tasks'] });
  assert.equal(r.kind, 'unknown');
  assert.match(r.detail, /factory_reg_tasks/);
});

test('resolve: fail-closed — подтверждённая ACTIVE из живого источника остаётся busy при деградации', () => {
  const r = resolvePhoneStatus({ ...base, failedSources: ['archive_tasks'], activities: [
    { type: 'auto_publish', state: 'active', detail: 'ок', updatedAt: NOW - 1000 },
  ]});
  assert.equal(r.kind, 'busy');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test test_phone_status_pure.test.js`
Expected: FAIL — `resolvePhoneStatus is not a function`.

- [ ] **Step 3: Реализовать `resolvePhoneStatus`**

В `phone_status.js` добавить ПЕРЕД `module.exports` и дополнить экспорт:
```javascript
// Решение статуса телефона по нормализованным активностям. Чистая, без БД.
function resolvePhoneStatus(input) {
  const { activities = [], online = null, hasDeviceState = false,
          now = Date.now(), staleMs = 600000, failedSources = [] } = input || {};
  const byPriority = (a, b) =>
    PHONE_STATUS_PRIORITY.indexOf(a.type) - PHONE_STATUS_PRIORITY.indexOf(b.type);
  const label = t => PHONE_STATUS_LABELS[t] || t;
  const degraded = Array.isArray(failedSources) && failedSources.length > 0;

  const actives = activities.filter(a => a.state === 'active');
  const fresh = actives.filter(a => a.updatedAt != null && (now - a.updatedAt) <= staleMs);
  if (fresh.length) {
    const top = fresh.slice().sort(byPriority)[0];
    return { status: label(top.type), kind: 'busy', detail: top.detail || '', stale: false, updatedAt: top.updatedAt };
  }

  const staleActive = actives.filter(a => a.updatedAt == null || (now - a.updatedAt) > staleMs);
  if (staleActive.length) {
    const top = staleActive.slice().sort(byPriority)[0];
    const mins = top.updatedAt != null ? Math.round((now - top.updatedAt) / 60000) : null;
    const suffix = mins != null ? ` · нет обновлений ${mins} мин` : ' · нет данных о времени';
    return { status: `возможно завис (${label(top.type)})`, kind: 'stale',
             detail: (top.detail || '') + suffix, stale: true, updatedAt: top.updatedAt };
  }

  const reserved = activities.filter(a => a.state === 'reserved');
  if (reserved.length) {
    const top = reserved.slice().sort(byPriority)[0];
    return { status: `${label(top.type)} (на паузе)`, kind: 'reserved', detail: top.detail || '', stale: false, updatedAt: top.updatedAt };
  }

  // fail-closed: не подтвердили занятость и часть источников недоступна → не врём «свободен».
  if (degraded) {
    return { status: 'неизвестно (нет данных)', kind: 'unknown',
             detail: 'источники недоступны: ' + failedSources.join(', '), stale: false, updatedAt: null };
  }

  if (online === false || !hasDeviceState) {
    return { status: 'offline', kind: 'offline', detail: '', stale: false, updatedAt: null };
  }
  return { status: 'свободен', kind: 'free', detail: '', stale: false, updatedAt: null };
}
```
И обновить экспорт:
```javascript
module.exports = { PHONE_STATUS_PRIORITY, PHONE_STATUS_LABELS, lastLogLine, resolvePhoneStatus };
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test test_phone_status_pure.test.js`
Expected: PASS (все, включая 9 новых).

- [ ] **Step 5: Commit**

```bash
git add phone_status.js test_phone_status_pure.test.js
git commit -m "feat(wp157): resolvePhoneStatus — приоритет, stale-guard, fail-closed (TDD)"
```

---

## Task 3: Серверная `fetchPhoneStatuses(pool, now)`

**Files:**
- Modify: `phone_status.js`
- Test: `test_phone_status_fetch.test.js` (live-DB smoke, корень репо)

Читает реестр + 6 источников, каждый в своём try/catch (упавший → в `failedSources`), нормализует в активности, зовёт `resolvePhoneStatus` на телефон. `staleMs` из env `PHONE_STATUS_STALE_MINUTES` (дефолт 10).

- [ ] **Step 1: Написать live-DB smoke-тест (форма ответа)**

`test_phone_status_fetch.test.js`:
```javascript
'use strict';
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { fetchPhoneStatuses } = require('./phone_status');

const pool = new Pool({ host: 'localhost', port: 5432, database: 'openclaw', user: 'openclaw', password: 'openclaw123' });
after(() => pool.end());

test('fetchPhoneStatuses: возвращает форму {degraded, failedSources, devices[]}', async () => {
  const res = await fetchPhoneStatuses(pool, Date.now());
  assert.equal(typeof res.degraded, 'boolean');
  assert.ok(Array.isArray(res.failedSources));
  assert.ok(Array.isArray(res.devices));
  if (res.devices.length) {
    const d = res.devices[0];
    for (const k of ['deviceSerial','deviceNumber','raspberry','status','kind','detail']) {
      assert.ok(k in d, `нет поля ${k}`);
    }
    assert.ok(['busy','stale','reserved','unknown','offline','free'].includes(d.kind));
  }
});

test('fetchPhoneStatuses: при живой БД degraded=false', async () => {
  const res = await fetchPhoneStatuses(pool, Date.now());
  assert.equal(res.degraded, false);
  assert.deepEqual(res.failedSources, []);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test test_phone_status_fetch.test.js`
Expected: FAIL — `fetchPhoneStatuses is not a function`.

- [ ] **Step 3: Реализовать `fetchPhoneStatuses`**

В `phone_status.js` добавить перед `module.exports`:
```javascript
const STALE_MS = (parseInt(process.env.PHONE_STATUS_STALE_MINUTES, 10) || 10) * 60000;
const toMs = ts => (ts ? new Date(ts).getTime() : null);

// Описание 6 источников: SQL только по активным/зарезервированным строкам + как
// превратить строку в активность. Каждый источник изолирован в try/catch вызывающим.
const SOURCES = [
  { name: 'publish_tasks', sql:
    `SELECT device_serial, status, events, log, updated_at FROM publish_tasks
     WHERE status IN ('running','processing')`,
    map: r => ({ type: 'auto_publish', state: 'active',
      detail: lastLogLine(r.events, r.log), updatedAt: toMs(r.updated_at) }) },

  { name: 'validator_manual_publish_queue', sql:
    `SELECT device_serial, account_username, platform, pack_name, updated_at, taken_at
     FROM validator_manual_publish_queue
     WHERE operator_status='in_progress' AND cancelled_at IS NULL`,
    map: r => ({ type: 'manual_publish', state: 'active',
      detail: `${r.pack_name || r.account_username || '?'} · ${r.platform || ''}`.trim(),
      updatedAt: toMs(r.updated_at || r.taken_at) }) },

  { name: 'factory_reg_tasks', sql:
    `SELECT device_serial, status, current_step, events, log, updated_at FROM factory_reg_tasks
     WHERE status='running'`,
    map: r => ({ type: 'account_create', state: 'active',
      detail: r.current_step || lastLogLine(r.events, r.log), updatedAt: toMs(r.updated_at) }) },

  { name: 'autowarm_tasks', sql:
    `SELECT device_serial, status, events, log, updated_at, current_day FROM autowarm_tasks
     WHERE status IN ('running','paused')`,
    map: r => ({ type: 'warmup', state: r.status === 'running' ? 'active' : 'reserved',
      detail: `день ${r.current_day || '?'} · ${lastLogLine(r.events, r.log)}`.trim(),
      updatedAt: toMs(r.updated_at) }) },

  { name: 'phone_warm_tasks', sql:
    `SELECT device_serial, status, events, log, updated_at, day, session, total_days FROM phone_warm_tasks
     WHERE status IN ('running','paused')`,
    map: r => ({ type: 'phone_warmup', state: r.status === 'running' ? 'active' : 'reserved',
      detail: `день ${r.day || '?'}/${r.total_days || '?'} сессия ${r.session || '?'}`,
      updatedAt: toMs(r.updated_at) }) },

  // archive_tasks: НЕТ updated_at → свежесть по started_at.
  { name: 'archive_tasks', sql:
    `SELECT device_serial, status, started_at, videos_checked, platform FROM archive_tasks
     WHERE status='running'`,
    map: r => ({ type: 'archive_check', state: 'active',
      detail: `проверка ${r.platform || ''}: ${r.videos_checked || 0} видео`.trim(),
      updatedAt: toMs(r.started_at) }) },
];

async function fetchPhoneStatuses(pool, now = Date.now()) {
  const failedSources = [];

  // Реестр телефонов. Намеренно НЕ в try/catch: без реестра рисовать нечего —
  // ошибка пробрасывается, эндпоинт отвечает 500 (фронт покажет предупреждение, Task 5).
  const roster = (await pool.query(
    `SELECT fdn.device_id, fdn.device_number, fdn.raspberry, rp.host
     FROM factory_device_numbers fdn
     LEFT JOIN raspberry_port rp ON rp.raspberry_number = fdn.raspberry
     WHERE fdn.active = TRUE`)).rows;

  // Последнее состояние устройства (device_state — view). Ошибка → degraded-источник,
  // НЕ throw: иначе сбой online/offline уронит весь эндпоинт и спрячет занятость.
  const dsMap = {};
  try {
    for (const r of (await pool.query(
      `SELECT DISTINCT ON (device_id) device_id, online, battery_percent, checked_at
       FROM device_state ORDER BY device_id, checked_at DESC NULLS LAST`)).rows) {
      dsMap[r.device_id] = r;
    }
  } catch (e) {
    console.error('[phone_status] device_state недоступен:', e.message);
    failedSources.push('device_state');
  }

  // Активности по device_serial из 6 источников (fail-closed: ошибка → в failedSources).
  const acts = {};
  for (const src of SOURCES) {
    try {
      for (const row of (await pool.query(src.sql)).rows) {
        if (!row.device_serial) continue;
        (acts[row.device_serial] = acts[row.device_serial] || []).push(src.map(row));
      }
    } catch (e) {
      console.error(`[phone_status] источник ${src.name} недоступен:`, e.message);
      failedSources.push(src.name);
    }
  }

  // Счётчик «в очереди на ручную» (queued — НЕ занятость).
  const queuedMap = {};
  try {
    for (const r of (await pool.query(
      `SELECT device_serial, COUNT(*)::int AS n FROM validator_manual_publish_queue
       WHERE operator_status='queued' AND cancelled_at IS NULL AND device_serial IS NOT NULL
       GROUP BY device_serial`)).rows) {
      queuedMap[r.device_serial] = r.n;
    }
  } catch (e) { console.error('[phone_status] queued-счётчик недоступен:', e.message); }

  const devices = roster.map(d => {
    const ds = dsMap[d.device_id];
    const r = resolvePhoneStatus({
      activities: acts[d.device_id] || [],
      online: ds ? ds.online : null,
      hasDeviceState: !!ds,
      now, staleMs: STALE_MS, failedSources,
    });
    return {
      deviceSerial: d.device_id, deviceNumber: d.device_number, raspberry: d.raspberry, host: d.host,
      online: ds ? ds.online : null, battery: ds ? ds.battery_percent : null,
      checkedAt: ds ? ds.checked_at : null,
      status: r.status, kind: r.kind, detail: r.detail, stale: r.stale, updatedAt: r.updatedAt,
      queuedManual: queuedMap[d.device_id] || 0,
    };
  });

  return { degraded: failedSources.length > 0, failedSources, devices };
}
```
Обновить экспорт:
```javascript
module.exports = { PHONE_STATUS_PRIORITY, PHONE_STATUS_LABELS, lastLogLine, resolvePhoneStatus, fetchPhoneStatuses };
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test test_phone_status_fetch.test.js`
Expected: PASS (2 теста). Если БД недоступна локально — запускать на сервере, где живёт `openclaw`.

- [ ] **Step 5: Прогнать ВСЕ phone_status-тесты вместе**

Run: `node --test test_phone_status_pure.test.js test_phone_status_fetch.test.js`
Expected: PASS все.

- [ ] **Step 6: Commit**

```bash
git add phone_status.js test_phone_status_fetch.test.js
git commit -m "feat(wp157): fetchPhoneStatuses — 6 источников, fail-closed, queued-счётчик"
```

---

## Task 4: Эндпоинт `GET /api/devices/status`

**Files:**
- Modify: `server.js` (require рядом со строкой 14; обработчик рядом с другими `/api/devices*`)

- [ ] **Step 1: Добавить require модуля**

В `server.js` после строки `const mpq = require('./manual_publish_queue');` (≈строка 14) добавить:
```javascript
const phoneStatus = require('./phone_status');
```

- [ ] **Step 2: Добавить обработчик**

В `server.js` рядом с прочими `app.get('/api/devices...')` добавить:
```javascript
// WP #157: статусы телефонов для операторов (read-only агрегатор).
app.get('/api/devices/status', requireAuth, async (req, res) => {
  try {
    const result = await phoneStatus.fetchPhoneStatuses(pool, Date.now());
    res.json(result);
  } catch (e) {
    console.error('[GET /api/devices/status]', e);
    res.status(500).json({ error: e.message });
  }
});
```

- [ ] **Step 3: Smoke — поднять сервер и дёрнуть эндпоинт**

Run (в worktree кодового репо):
```bash
node -e "require('./server.js')" & sleep 2
curl -s -b /tmp/sess.txt 'http://localhost:3848/api/devices/status' | head -c 400; echo
```
Expected: либо JSON `{"degraded":false,"failedSources":[],"devices":[...]}`, либо `{"error":"Unauthorized"}` (если без сессии — это ОК, значит роут смонтирован). Главное — не 404 и не падение процесса. Затем `kill %1`.

> Примечание: порт/способ запуска уточнить по `server.js` (`app.listen`). Если требуется аутентификация — проверить через залогиненную сессию или временно убрать `requireAuth` ЛОКАЛЬНО для smoke и вернуть обратно перед коммитом.

- [ ] **Step 4: Commit**

```bash
git add server.js
git commit -m "feat(wp157): GET /api/devices/status — эндпоинт статусов телефонов"
```

---

## Task 5: Фронтенд — раздел «Статусы телефонов»

**Files:**
- Modify: `public/index.html`

- [ ] **Step 1: Добавить nav-кнопку в группу «Выкладка»**

В `public/index.html` рядом с `<button onclick="nav('publishing-manual')" ...>` добавить:
```html
<button onclick="nav('phone-status'); phsLoad();" id="nav-phone-status" class="nav-item w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-600 hover:bg-gray-100 text-left">📱 Статусы телефонов</button>
```

- [ ] **Step 2: Добавить секцию с баннером и таблицей**

Рядом с `<div id="section-publishing-manual" ...>` добавить:
```html
<div id="section-phone-status" class="section px-4 py-4 fade-in">
  <div class="flex items-center justify-between mb-3">
    <h2 class="text-xl font-bold text-gray-900">📱 Статусы телефонов</h2>
    <button onclick="phsLoad()" class="px-3 py-1.5 rounded-lg bg-indigo-50 text-indigo-700 text-sm font-medium">🔄 Обновить</button>
  </div>
  <div id="phs-degraded" class="hidden mb-3 px-3 py-2 rounded-lg bg-red-50 text-red-700 text-sm font-medium"></div>
  <div class="table-wrap overflow-auto max-h-[calc(100vh-220px)] bg-white rounded-2xl shadow-sm border border-gray-100">
    <table class="w-full text-sm">
      <thead><tr class="text-left text-gray-500 border-b">
        <th class="px-3 py-2">Телефон</th><th class="px-3 py-2">Статус</th>
        <th class="px-3 py-2">Подробно</th><th class="px-3 py-2">Обновлено</th>
      </tr></thead>
      <tbody id="phs-tbody"></tbody>
    </table>
  </div>
  <p id="phs-empty" class="hidden text-center text-gray-400 py-8">Телефонов нет</p>
</div>
```

- [ ] **Step 3: Добавить JS — загрузка, рендер, бейдж, поллинг**

В `<script>`-блок `public/index.html` добавить:
```javascript
// WP #157: статусы телефонов.
let phsRows = [];
let phsPollTimer = null;
const PHS_KIND_CLASS = {
  free:     'bg-green-100 text-green-700',
  busy:     'bg-blue-100 text-blue-700',
  reserved: 'bg-amber-100 text-amber-700',
  stale:    'bg-red-100 text-red-700',
  unknown:  'bg-red-50 text-red-600',
  offline:  'bg-gray-100 text-gray-500',
};
function phsBadge(kind, text) {
  const cls = PHS_KIND_CLASS[kind] || 'bg-gray-100 text-gray-500';
  return `<span class="px-2 py-0.5 rounded-full text-xs font-semibold ${cls}">${text || '—'}</span>`;
}
function phsAgo(ms) {
  if (!ms) return '—';
  const s = Math.round((Date.now() - ms) / 1000);
  if (s < 60) return s + ' с назад';
  if (s < 3600) return Math.round(s / 60) + ' мин назад';
  return Math.round(s / 3600) + ' ч назад';
}
const PHS_KIND_ORDER = { stale: 0, unknown: 1, busy: 2, reserved: 3, offline: 4, free: 5 };
function phsRender() {
  const tb = document.getElementById('phs-tbody');
  const empty = document.getElementById('phs-empty');
  if (!phsRows.length) { tb.innerHTML = ''; empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');
  const rows = phsRows.slice().sort((a, b) =>
    (PHS_KIND_ORDER[a.kind] ?? 9) - (PHS_KIND_ORDER[b.kind] ?? 9) || (a.deviceNumber || 0) - (b.deviceNumber || 0));
  tb.innerHTML = rows.map(d => {
    const q = d.queuedManual ? ` <span class="text-xs text-gray-400">(${d.queuedManual} в очереди)</span>` : '';
    return `<tr class="border-b hover:bg-gray-50">
      <td class="px-3 py-2 font-medium">#${d.deviceNumber ?? '?'} <span class="text-gray-400 text-xs">мал.${d.raspberry ?? '?'}</span></td>
      <td class="px-3 py-2">${phsBadge(d.kind, d.status)}${q}</td>
      <td class="px-3 py-2 text-gray-600">${(d.detail || '').replace(/</g, '&lt;')}</td>
      <td class="px-3 py-2 text-gray-400 text-xs">${phsAgo(d.updatedAt)}</td>
    </tr>`;
  }).join('');
}
async function phsLoad() {
  const banner = document.getElementById('phs-degraded');
  const r = await fetch('/api/devices/status', { credentials: 'same-origin' }).catch(() => null);
  if (!r || !r.ok) {
    // Fail-closed на стороне фронта: не молчим со старыми данными (могут врать «свободен»).
    banner.textContent = '⚠️ Не удалось обновить статусы — данные могли устареть, не полагайтесь на «свободен».';
    banner.classList.remove('hidden');
    phsStartPoll();
    return;
  }
  const data = await r.json();
  phsRows = data.devices || [];
  if (data.degraded) {
    banner.textContent = `Часть данных недоступна (источники: ${(data.failedSources || []).join(', ')}) — статусы «неизвестно» могут скрывать занятость.`;
    banner.classList.remove('hidden');
  } else { banner.classList.add('hidden'); }
  phsRender();
  phsStartPoll();
}
function phsStartPoll() {
  if (phsPollTimer) return;
  phsPollTimer = setInterval(() => {
    const sec = document.getElementById('section-phone-status');
    if (!sec || sec.offsetParent === null) return;  // только когда раздел виден
    phsLoad();
  }, 7000);
}
```

- [ ] **Step 4: Ручная проверка в браузере**

Открыть дашборд → раздел «Статусы телефонов». Ожидаемо: таблица телефонов с цветными бейджами (свободен=зелёный, занят=синий, offline=серый и т.д.), сортировка «проблемные сверху», обновление раз в ~7с. Дёрнуть телефон в работу (или проверить на текущих in_progress ручной выкладки) → строка меняется в течение ~7с.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(wp157): фронт — раздел «Статусы телефонов» + поллинг 7с"
```

---

## Task 6: Финальная проверка и деплой

**Files:** —

- [ ] **Step 1: Прогнать все тесты фичи**

Run: `node --test test_phone_status_pure.test.js test_phone_status_fetch.test.js`
Expected: PASS все.

- [ ] **Step 2: codex review диффа фичи**

Run: `git diff origin/main HEAD | ~/.local/bin/codex review -`
Применить P1/P2, раундами до 0 P1 (свежими fixup-коммитами, НЕ `--amend`).

- [ ] **Step 3: Деплой в прод**

Влить ветку в прод-`main` autowarm (`/root/.openclaw/workspace-genri/autowarm/`; auto-push hook раздаёт в `GenGo2/delivery-contenthunter`). Перезапуск дашборда:
```bash
sudo pm2 restart 35   # дашборд autowarm (id уточнить: pm2 list)
```
Опционально выставить `PHONE_STATUS_STALE_MINUTES` в env PM2, если 10 мин не подходит. Фича read-only и аддитивна — kill-switch не требуется.

- [ ] **Step 4: Post-deploy smoke**

Открыть `delivery.contenthunter.ru` → «Статусы телефонов»; убедиться, что таблица грузится, `degraded=false`, статусы правдоподобны (сверить пару телефонов с реальными running-задачами).

- [ ] **Step 5: Обновить OpenProject #157**

Комментарий в house-стиле (Что было не так → Что сделано → Что осталось), статус → «Тестирование».

---

## Self-Review (выполнено при написании)

- **Покрытие спеки:** реестр+device_state (Task 3), 6 источников по device_serial (Task 3 SOURCES), приоритет/active/reserved/stale/unknown/offline/free (Task 2), fail-closed (Task 2+3), stale-guard порог env (Task 2+3), поллинг ~7с + раздел в «Выкладке» + баннер деградации + queued-счётчик (Task 5), тесты (Task 1-3), деплой без миграций (Task 6). Все секции спеки имеют задачу.
- **archive_tasks без updated_at** → свежесть по `started_at` (Task 3 SOURCES, комментарий).
- **Плейсхолдеров нет:** весь код приведён целиком.
- **Согласованность типов:** `resolvePhoneStatus` принимает `{type,state,detail,updatedAt}` — ровно то, что отдаёт `src.map` в Task 3; поля ответа (`deviceSerial/deviceNumber/raspberry/status/kind/detail/updatedAt/queuedManual`) совпадают между Task 3 (сервер), Task 4 (эндпоинт) и Task 5 (фронт `phsRender`). `kind`-значения (busy/stale/reserved/unknown/offline/free) едины в Task 2, `PHS_KIND_CLASS` и `PHS_KIND_ORDER` (Task 5).
