# Daily Publish Limits — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ограничить публикации на аккаунт в день (защита аккаунтов): потолок реальных публикаций (перенос лишних на след. день) + потолок попыток/ретраев (handoff в ручную) + авто-разгон новой выкладки, с настройками в admin-разделе «Публикация».

**Architecture:** Чистый модуль-резолвер `publish_limits.js` (как `retry_decision.js`) считает дневные лимиты из глобальных настроек + per-проект override + ramp-up. Два гейта-потребителя: наполнитель очереди (`assignUnicResultsToQueue` в `server.js`) переносит сверх-лимитные посты на следующий день; контроллер ретраев (`retry_controller.js`) при исчерпании капа попыток отдаёт в ручную. Глобал — в `autowarm_settings`, per-проект — в новой таблице `publish_project_limits`. UI — раздел сайдбара `publishing`, admin-only. Всё за kill-switch `PUBLISH_DAILY_LIMITS_ENABLED`.

**Tech Stack:** Node.js, Express, PostgreSQL (`pg` pool), `node:test`, ванильный inline-JS в `public/index.html`.

**Спец:** `docs/superpowers/specs/2026-06-05-daily-publish-limits-design.md`

**Репозиторий:** delivery-contenthunter (autowarm). Реализовывать в изолированном worktree (см. `superpowers:using-git-worktrees`). Команда тестов в корне worktree: `node --test --test-force-exit tests/<file>.test.js`. node_modules можно симлинкнуть из существующей рабочей копии.

---

## File Structure

- **Create** `publish_limits.js` — чистый резолвер: дефолты, чтение глобала, мёрдж override, ramp-up, поиск свободного дня. Без БД и побочных эффектов.
- **Create** `tests/publish_limits.test.js` — юнит-тесты резолвера.
- **Create** `tests/test_publish_limits_gates.test.js` — тесты гейтов через capture-pool (мок `pool.query`).
- **Modify** `server.js` — миграция таблицы + дефолтные ключи; гейт A в `assignUnicResultsToQueue`; helper `computeDeviceSlot`; эндпоинты `GET/PUT /api/publish-limits` (admin-only).
- **Modify** `retry_controller.js` — гейт B в `retryFailedPublishes` (резолв лимита проекта + кап попыток аккаунта → handoff).
- **Modify** `public/index.html` — пункт сайдбара + `section-publish-settings` + `loadPublishLimits()`/`savePublishLimits()`, admin-only видимость.

Kill-switch (env, читать через `process.env.PUBLISH_DAILY_LIMITS_ENABLED === 'true'`, default false): при OFF оба гейта — no-op, поведение идентично текущему. Дублирующий БД-флаг `publish_daily_limits_enabled` управляет тем же из UI — итоговое «включено» = env ИЛИ настройка true (см. Task 3/4).

---

## Task 1: Миграция — таблица override + дефолтные ключи

**Files:**
- Modify: `server.js` (рядом с прочими `CREATE TABLE IF NOT EXISTS`, после блока `autowarm_settings` ~283)

- [ ] **Step 1: Добавить создание таблицы**

В блоке инициализации схемы (после `CREATE TABLE IF NOT EXISTS autowarm_settings (...)`, ~строка 284) добавить:

```js
  await pool.query(`
    CREATE TABLE IF NOT EXISTS publish_project_limits (
      project_id           INT PRIMARY KEY,
      max_per_day          INT,
      max_attempts_per_day INT,
      rampup_days          INT,
      rampup_max_per_day   INT,
      updated_at           TIMESTAMPTZ DEFAULT now()
    )
  `);
```

- [ ] **Step 2: Запустить сервер локально и проверить, что таблица создаётся без ошибок**

Run: `node -e "require('./server.js')"` — НЕ нужно (поднимет порт). Вместо этого синтаксис-чек:
Run: `node -c server.js`
Expected: без вывода (синтаксис OK). Реальное создание таблицы проверится на проде при рестарте (idempotent `IF NOT EXISTS`).

- [ ] **Step 3: Commit**

```bash
git add server.js
git commit -m "feat(op139): таблица publish_project_limits (per-проект override лимитов)"
```

---

## Task 2: Чистый резолвер `publish_limits.js`

**Files:**
- Create: `publish_limits.js`
- Test: `tests/publish_limits.test.js`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/publish_limits.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const {
  DEFAULTS, readGlobalLimits, mergeProjectOverride, resolveDailyLimits,
  nextAvailableDay, daysBetween, addDays, toIntOr,
} = require('../publish_limits.js');

test('readGlobalLimits: пустые настройки → дефолты', () => {
  assert.deepStrictEqual(readGlobalLimits({}), {
    maxPerDay: 3, maxAttemptsPerDay: 4, rampupDays: 7, rampupMaxPerDay: 1,
  });
});

test('readGlobalLimits: строки из autowarm_settings парсятся в int', () => {
  const g = readGlobalLimits({ publish_max_per_day: '5', publish_max_attempts_per_day: '6' });
  assert.strictEqual(g.maxPerDay, 5);
  assert.strictEqual(g.maxAttemptsPerDay, 6);
});

test('mergeProjectOverride: null-поля наследуют глобал', () => {
  const g = { maxPerDay: 3, maxAttemptsPerDay: 4, rampupDays: 7, rampupMaxPerDay: 1 };
  const m = mergeProjectOverride(g, { max_per_day: 2, max_attempts_per_day: null,
    rampup_days: null, rampup_max_per_day: null });
  assert.strictEqual(m.maxPerDay, 2);
  assert.strictEqual(m.maxAttemptsPerDay, 4);
  assert.strictEqual(m.rampupDays, 7);
});

test('mergeProjectOverride: override отсутствует → глобал как есть', () => {
  const g = { maxPerDay: 3, maxAttemptsPerDay: 4, rampupDays: 7, rampupMaxPerDay: 1 };
  assert.deepStrictEqual(mergeProjectOverride(g, null), g);
});

test('resolveDailyLimits: вне ramp-up окна → обычный лимит', () => {
  const r = resolveDailyLimits({
    global: readGlobalLimits({}), projectOverride: null,
    startDate: '2026-06-01', today: '2026-06-10', // 9 дней >= 7
  });
  assert.strictEqual(r.maxPublishesPerDay, 3);
  assert.strictEqual(r.source, 'global');
});

test('resolveDailyLimits: внутри ramp-up окна → 1/день, source=rampup', () => {
  const r = resolveDailyLimits({
    global: readGlobalLimits({}), projectOverride: null,
    startDate: '2026-06-01', today: '2026-06-04', // 3 дня < 7
  });
  assert.strictEqual(r.maxPublishesPerDay, 1);
  assert.strictEqual(r.source, 'rampup');
});

test('resolveDailyLimits: startDate=null → ramp-up пропущен', () => {
  const r = resolveDailyLimits({
    global: readGlobalLimits({}), projectOverride: null,
    startDate: null, today: '2026-06-04',
  });
  assert.strictEqual(r.maxPublishesPerDay, 3);
});

test('resolveDailyLimits: project override + ramp-up override', () => {
  const r = resolveDailyLimits({
    global: readGlobalLimits({}),
    projectOverride: { max_per_day: 5, max_attempts_per_day: null,
      rampup_days: 14, rampup_max_per_day: 2 },
    startDate: '2026-06-01', today: '2026-06-05', // 4 < 14 → ramp-up
  });
  assert.strictEqual(r.maxPublishesPerDay, 2); // rampup_max_per_day override
  assert.strictEqual(r.maxAttemptsPerDay, 4);  // унаследован глобал
});

test('daysBetween / addDays', () => {
  assert.strictEqual(daysBetween('2026-06-01', '2026-06-08'), 7);
  assert.strictEqual(addDays('2026-06-01', 1), '2026-06-02');
  assert.strictEqual(addDays('2026-06-30', 1), '2026-07-01');
});

test('nextAvailableDay: первый день с местом', async () => {
  const counts = { '2026-06-01': 3, '2026-06-02': 3, '2026-06-03': 0 };
  const day = await nextAvailableDay((ymd) => counts[ymd] ?? 0, '2026-06-01', 3, 30);
  assert.strictEqual(day, '2026-06-03');
});

test('nextAvailableDay: место в стартовом дне', async () => {
  const day = await nextAvailableDay(() => 0, '2026-06-01', 3, 30);
  assert.strictEqual(day, '2026-06-01');
});

test('toIntOr: невалидное → дефолт', () => {
  assert.strictEqual(toIntOr('abc', 9), 9);
  assert.strictEqual(toIntOr(undefined, 9), 9);
  assert.strictEqual(toIntOr('0', 9), 0);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/publish_limits.test.js`
Expected: FAIL — `Cannot find module '../publish_limits.js'`.

- [ ] **Step 3: Реализовать модуль**

Создать `publish_limits.js`:

```js
'use strict';

/**
 * Дневные лимиты публикаций (OP#139/#184). Чистый модуль: без БД и побочных эффектов.
 * Резолвит лимиты из глобальных настроек + per-проект override + ramp-up первой недели.
 */

const DEFAULTS = { maxPerDay: 3, maxAttemptsPerDay: 4, rampupDays: 7, rampupMaxPerDay: 1 };

function toIntOr(v, d) {
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : d;
}

// Глобал из autowarm_settings (объект key→value, значения — строки).
function readGlobalLimits(settings = {}) {
  return {
    maxPerDay:         toIntOr(settings.publish_max_per_day,          DEFAULTS.maxPerDay),
    maxAttemptsPerDay: toIntOr(settings.publish_max_attempts_per_day, DEFAULTS.maxAttemptsPerDay),
    rampupDays:        toIntOr(settings.publish_rampup_days,          DEFAULTS.rampupDays),
    rampupMaxPerDay:   toIntOr(settings.publish_rampup_max_per_day,   DEFAULTS.rampupMaxPerDay),
  };
}

// Строка publish_project_limits с NULL-полями → наследование глобала.
function mergeProjectOverride(global, override) {
  if (!override) return { ...global };
  const pick = (o, g) => (o === null || o === undefined ? g : o);
  return {
    maxPerDay:         pick(override.max_per_day,          global.maxPerDay),
    maxAttemptsPerDay: pick(override.max_attempts_per_day, global.maxAttemptsPerDay),
    rampupDays:        pick(override.rampup_days,          global.rampupDays),
    rampupMaxPerDay:   pick(override.rampup_max_per_day,   global.rampupMaxPerDay),
  };
}

// Целые дни между YYYY-MM-DD (UTC-полночь, без TZ-дрейфа).
function daysBetween(fromYmd, toYmd) {
  const a = Date.parse(fromYmd + 'T00:00:00Z');
  const b = Date.parse(toYmd + 'T00:00:00Z');
  return Math.floor((b - a) / 86400000);
}

function addDays(ymd, n) {
  const t = Date.parse(ymd + 'T00:00:00Z') + n * 86400000;
  return new Date(t).toISOString().slice(0, 10);
}

/**
 * @param {object} a
 * @param {object} a.global  результат readGlobalLimits
 * @param {object|null} a.projectOverride  строка publish_project_limits или null
 * @param {string|null} a.startDate  YYYY-MM-DD первого дня расписания или null
 * @param {string} a.today  YYYY-MM-DD (бизнес-дата)
 * @returns {{maxPublishesPerDay:number, maxAttemptsPerDay:number, source:'global'|'project'|'rampup'}}
 */
function resolveDailyLimits({ global, projectOverride, startDate, today }) {
  const merged = mergeProjectOverride(global, projectOverride);
  let maxPublishesPerDay = merged.maxPerDay;
  let source = projectOverride ? 'project' : 'global';
  if (startDate) {
    const elapsed = daysBetween(startDate, today);
    if (elapsed >= 0 && elapsed < merged.rampupDays) {
      maxPublishesPerDay = merged.rampupMaxPerDay;
      source = 'rampup';
    }
  }
  return { maxPublishesPerDay, maxAttemptsPerDay: merged.maxAttemptsPerDay, source };
}

/**
 * Первый день (начиная со startYmd), где countFn(ymd) < maxPerDay.
 * countFn может быть async (возвращать число или Promise<number>).
 */
async function nextAvailableDay(countFn, startYmd, maxPerDay, maxLookahead = 30) {
  let ymd = startYmd;
  for (let i = 0; i <= maxLookahead; i++) {
    const c = await countFn(ymd);
    if (c < maxPerDay) return ymd;
    ymd = addDays(ymd, 1);
  }
  return ymd; // fallback: за горизонтом — последний просмотренный день
}

module.exports = {
  DEFAULTS, toIntOr, readGlobalLimits, mergeProjectOverride,
  resolveDailyLimits, nextAvailableDay, daysBetween, addDays,
};
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/publish_limits.test.js`
Expected: PASS (все тесты зелёные).

- [ ] **Step 5: Commit**

```bash
git add publish_limits.js tests/publish_limits.test.js
git commit -m "feat(op139): чистый резолвер publish_limits.js (глобал+override+ramp-up) + тесты"
```

---

## Task 3: Гейт A — перенос сверх-лимитных постов (наполнитель)

**Files:**
- Modify: `server.js` `assignUnicResultsToQueue()` (~6497–6770), вынести вычисление слота в helper `computeDeviceSlot`
- Test: `tests/test_publish_limits_gates.test.js`

**Контекст:** сейчас `scheduledAt` для устройства считается один раз перед циклом `for (const acc of accounts)` (server.js:6662-6679) и сдвигается на `PUBLISH_INTERVAL_MINUTES` после каждого аккаунта. При включённом лимите мы переносим аккаунт на ближайший день с местом и вычисляем `scheduledAt` для этого дня тем же приёмом.

- [ ] **Step 1: Написать падающий тест на helper + гейт (capture-pool)**

Создать `tests/test_publish_limits_gates.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const { gateAssignDay } = require('../publish_limits.js');

// gateAssignDay: чистая обёртка поверх nextAvailableDay для гейта A.
// countOnDay(account, platform, ymd) -> Promise<number> назначенных записей.
test('gateAssignDay: день полон → перенос на следующий', async () => {
  const counts = { '2026-06-01': 3, '2026-06-02': 1 };
  const day = await gateAssignDay({
    account: 'acc', platform: 'instagram', startDay: '2026-06-01',
    maxPerDay: 3, countOnDay: async (_a, _p, ymd) => counts[ymd] ?? 0,
  });
  assert.strictEqual(day, '2026-06-02');
});

test('gateAssignDay: место есть → стартовый день', async () => {
  const day = await gateAssignDay({
    account: 'acc', platform: 'instagram', startDay: '2026-06-01',
    maxPerDay: 3, countOnDay: async () => 0,
  });
  assert.strictEqual(day, '2026-06-01');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_publish_limits_gates.test.js`
Expected: FAIL — `gateAssignDay is not a function`.

- [ ] **Step 3: Добавить `gateAssignDay` в `publish_limits.js`**

В `publish_limits.js` перед `module.exports` добавить:

```js
// Гейт A: вернуть YYYY-MM-DD ближайшего дня (от startDay) с местом для (account,platform).
async function gateAssignDay({ account, platform, startDay, maxPerDay, countOnDay, maxLookahead = 30 }) {
  return nextAvailableDay((ymd) => countOnDay(account, platform, ymd), startDay, maxPerDay, maxLookahead);
}
```

И добавить `gateAssignDay` в `module.exports`.

- [ ] **Step 4: Запустить — PASS**

Run: `node --test --test-force-exit tests/test_publish_limits_gates.test.js`
Expected: PASS.

- [ ] **Step 5: Вынести вычисление слота устройства в helper в `server.js`**

Перед функцией `assignUnicResultsToQueue` (~6496) добавить helper (повторяет логику строк 6662-6679 для произвольной даты):

```js
// Вычислить scheduled_at для устройства на конкретный день: после последнего занятого
// слота +PUBLISH_INTERVAL_MINUTES, иначе старт дня (publishStart c учётом TZ).
async function computeDeviceSlot(deviceSerial, dateYmd, publishStart, timezone) {
  const { rows: lastSlot } = await pool.query(`
    SELECT MAX(scheduled_at) AS last_at
    FROM publish_queue
    WHERE device_serial = $1 AND status IN ('pending','running') AND DATE(scheduled_at) = $2::date
  `, [deviceSerial, dateYmd]);
  if (lastSlot[0]?.last_at) {
    return new Date(new Date(lastSlot[0].last_at).getTime() + PUBLISH_INTERVAL_MINUTES * 60000);
  }
  const [ph, pm] = publishStart.split(':').map(Number);
  let at = new Date(`${dateYmd}T${String(ph).padStart(2,'0')}:${String(pm).padStart(2,'0')}:00Z`);
  const tzOffset = timezone === 'Asia/Dubai' ? -4 : 0;
  return new Date(at.getTime() + tzOffset * 3600000);
}
```

- [ ] **Step 6: Подключить резолвер и гейт в цикле аккаунтов**

(6a) В начале `assignUnicResultsToQueue` (после чтения `publishStart`/`timezone`, ~6508) — один раз прочитать глобальные настройки и флаг:

```js
    const limitsEnabledEnv = process.env.PUBLISH_DAILY_LIMITS_ENABLED === 'true';
    const { rows: awSettingsRows } = await pool.query('SELECT key, value FROM autowarm_settings');
    const awSettings = {}; awSettingsRows.forEach(r => { awSettings[r.key] = r.value; });
    const limitsEnabled = limitsEnabledEnv || awSettings.publish_daily_limits_enabled === 'true';
    const { readGlobalLimits, resolveDailyLimits, gateAssignDay } = require('./publish_limits.js');
    const globalLimits = readGlobalLimits(awSettings);
    const projLimitCache = new Map();   // project_id → override row | null
    const projStartCache = new Map();   // project_id → startDate ymd | null
```

(6b) Заменить блок вычисления `scheduledAt` ДО цикла accounts (строки 6671-6679) на объявление переменной без вычисления — вычислять будем per-account:

```js
        // scheduledAt вычисляется per-account (ниже): без лимита — общий слот устройства,
        // с лимитом — на ближайший день с местом для аккаунта.
        let scheduledAt = null;
```

(6c) Внутри `for (const acc of accounts)` сразу после дедупа (после `}` на ~6717, перед `let caption;`) вставить резолв дня и слота:

```js
          let targetDay = pubDate;
          if (limitsEnabled) {
            const pid = res.project_id;
            if (!projLimitCache.has(pid)) {
              const { rows: ov } = await pool.query(
                'SELECT max_per_day, max_attempts_per_day, rampup_days, rampup_max_per_day FROM publish_project_limits WHERE project_id=$1',
                [pid]);
              projLimitCache.set(pid, ov[0] || null);
              const { rows: sd } = await pool.query(
                'SELECT MIN(slot_date)::text AS start FROM validator_schedule_slots WHERE project_id=$1',
                [pid]);
              projStartCache.set(pid, sd[0]?.start || null);
            }
            const lim = resolveDailyLimits({
              global: globalLimits, projectOverride: projLimitCache.get(pid),
              startDate: projStartCache.get(pid), today: pubDate,
            });
            targetDay = await gateAssignDay({
              account: acc.username, platform: platformLower, startDay: pubDate,
              maxPerDay: lim.maxPublishesPerDay,
              countOnDay: async (account, platform, ymd) => {
                const { rows } = await pool.query(`
                  SELECT count(*)::int AS n FROM publish_queue
                  WHERE account_username=$1 AND LOWER(platform)=$2 AND DATE(scheduled_at)=$3::date
                    AND status NOT IN ('cancelled','skipped','past_slot_dropped')`,
                  [account, platform, ymd]);
                return rows[0].n;
              },
            });
          }
          scheduledAt = await computeDeviceSlot(pack.device_serial, targetDay, publishStart, timezone);
```

(6d) Удалить старый per-account сдвиг `scheduledAt = new Date(scheduledAt.getTime() + PUBLISH_INTERVAL_MINUTES*60000);` (строка ~6767) — теперь `computeDeviceSlot` сам учитывает уже вставленные записи дня (MAX+interval), давая корректный разнос. Лог `at=${scheduledAt.toISOString()}` оставить.

- [ ] **Step 7: Синтаксис-чек**

Run: `node -c server.js`
Expected: без вывода.

- [ ] **Step 8: Прогнать юнит-тесты резолвера/гейта (регрессий нет)**

Run: `node --test --test-force-exit tests/publish_limits.test.js tests/test_publish_limits_gates.test.js`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add server.js publish_limits.js tests/test_publish_limits_gates.test.js
git commit -m "feat(op139): гейт A — перенос сверх-лимитных постов на след. день (за kill-switch)"
```

---

## Task 4: Гейт B — кап попыток аккаунта → handoff (ретраи)

**Files:**
- Modify: `retry_controller.js` `retryFailedPublishes` (~19–101)
- Test: `tests/test_publish_limits_gates.test.js` (дополнить)

**Контекст:** выборка в `retryFailedPublishes` (строки 43-61) сейчас не содержит `account_username`/`platform`/`project_id`. Добавляем их и перед `decideRetry` вставляем гейт: если попыток аккаунта за сегодня (все классы) ≥ `maxAttemptsPerDay` — `handoffToManual` вместо обычного потока.

- [ ] **Step 1: Дополнить тест — чистая проверка решения гейта B**

В `tests/test_publish_limits_gates.test.js` добавить:

```js
const { attemptsCapReached } = require('../publish_limits.js');

test('attemptsCapReached: достигнут → true', () => {
  assert.strictEqual(attemptsCapReached(4, 4), true);
  assert.strictEqual(attemptsCapReached(5, 4), true);
});
test('attemptsCapReached: не достигнут → false', () => {
  assert.strictEqual(attemptsCapReached(3, 4), false);
});
```

- [ ] **Step 2: Запустить — FAIL**

Run: `node --test --test-force-exit tests/test_publish_limits_gates.test.js`
Expected: FAIL — `attemptsCapReached is not a function`.

- [ ] **Step 3: Добавить `attemptsCapReached` в `publish_limits.js`**

```js
// Гейт B: достигнут ли дневной кап попыток аккаунта.
function attemptsCapReached(attemptsToday, maxAttemptsPerDay) {
  return attemptsToday >= maxAttemptsPerDay;
}
```

Добавить в `module.exports`.

- [ ] **Step 4: Запустить — PASS**

Run: `node --test --test-force-exit tests/test_publish_limits_gates.test.js`
Expected: PASS.

- [ ] **Step 5: Расширить выборку в `retryFailedPublishes`**

В SQL выборки (строки 44-46) добавить поля аккаунта/проекта:

```js
    SELECT pq.id AS pq_id, pq.client_publish_id, pq.unic_task_id,
           pq.account_username, pq.platform, pq.project_id,
           lt.id AS last_task_id, lt.error_code, lt.error_class, lt.last_failed_at,
           (pq.client_publish_id IS NULL) AS no_intent
```

- [ ] **Step 6: Прочитать флаг и глобал один раз в начале функции**

После строки 30 (`maxDeviceHealthPerDay`) добавить:

```js
  const dailyLimitsEnabled = process.env.PUBLISH_DAILY_LIMITS_ENABLED === 'true'
    || (await pool.query("SELECT value FROM autowarm_settings WHERE key='publish_daily_limits_enabled'"))
         .rows[0]?.value === 'true';
  const { readGlobalLimits, resolveDailyLimits, attemptsCapReached } = require('./publish_limits.js');
  const awForLimits = {};
  if (dailyLimitsEnabled) {
    const { rows: s } = await pool.query('SELECT key, value FROM autowarm_settings');
    s.forEach(r => { awForLimits[r.key] = r.value; });
  }
  const globalLimits = readGlobalLimits(awForLimits);
  const projLimitCache = new Map();
  const projStartCache = new Map();
  const todayMsk = (await pool.query(
    "SELECT (COALESCE($1::timestamptz, now()) AT TIME ZONE 'Europe/Moscow')::date::text AS d", [nowParam]
  )).rows[0].d;
```

- [ ] **Step 7: Вставить гейт B перед `decideRetry`**

Внутри `for (const r of rows)`, после строки `if (r.no_intent || !r.error_class) continue;` (строка 64), вставить:

```js
    if (dailyLimitsEnabled && r.project_id && r.account_username) {
      const pid = r.project_id;
      if (!projLimitCache.has(pid)) {
        const { rows: ov } = await pool.query(
          'SELECT max_per_day, max_attempts_per_day, rampup_days, rampup_max_per_day FROM publish_project_limits WHERE project_id=$1',
          [pid]);
        projLimitCache.set(pid, ov[0] || null);
        const { rows: sd } = await pool.query(
          'SELECT MIN(slot_date)::text AS start FROM validator_schedule_slots WHERE project_id=$1',
          [pid]);
        projStartCache.set(pid, sd[0]?.start || null);
      }
      const lim = resolveDailyLimits({
        global: globalLimits, projectOverride: projLimitCache.get(pid),
        startDate: projStartCache.get(pid), today: todayMsk,
      });
      const { rows: ac } = await pool.query(`
        SELECT count(*)::int AS n FROM publish_tasks
        WHERE account_username=$1 AND LOWER(platform)=$2
          AND (created_at AT TIME ZONE 'Europe/Moscow')::date
              = (COALESCE($3::timestamptz, now()) AT TIME ZONE 'Europe/Moscow')::date
      `, [r.account_username, (r.platform || '').toLowerCase(), nowParam]);
      if (attemptsCapReached(ac.rows[0].n, lim.maxAttemptsPerDay)) {
        if (handoffEnabled) await handoffToManual(pool, r, 'daily_attempts_cap', visibility);
        continue;
      }
    }
```

- [ ] **Step 8: Синтаксис-чек + тесты**

Run: `node -c retry_controller.js && node --test --test-force-exit tests/publish_limits.test.js tests/test_publish_limits_gates.test.js`
Expected: синтаксис OK; тесты PASS.

- [ ] **Step 9: Прогнать существующий retry-тест на отсутствие регрессий**

Run: `node --test --test-force-exit tests/retry_*.test.js 2>/dev/null || node --test --test-force-exit tests/*retry*.test.js`
Expected: PASS (если файл есть; при OFF-флаге поведение неизменно).

- [ ] **Step 10: Commit**

```bash
git add retry_controller.js publish_limits.js tests/test_publish_limits_gates.test.js
git commit -m "feat(op184): гейт B — кап попыток аккаунта/день → handoff в ручную (за kill-switch)"
```

---

## Task 5: API `GET/PUT /api/publish-limits` (admin-only)

**Files:**
- Modify: `server.js` (рядом с `/api/settings`, ~1143)
- Test: `tests/test_publish_limits_api.test.js`

- [ ] **Step 1: Написать падающий тест на чистый валидатор тела**

Создать `tests/test_publish_limits_api.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const { validateLimitsBody } = require('../publish_limits.js');

test('validateLimitsBody: валидные положительные целые', () => {
  const r = validateLimitsBody({ max_per_day: '3', max_attempts_per_day: '4',
    rampup_days: '7', rampup_max_per_day: '1' });
  assert.strictEqual(r.ok, true);
  assert.deepStrictEqual(r.value, { max_per_day: 3, max_attempts_per_day: 4,
    rampup_days: 7, rampup_max_per_day: 1 });
});

test('validateLimitsBody: пустые поля → null (наследование)', () => {
  const r = validateLimitsBody({ max_per_day: '', max_attempts_per_day: null });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.value.max_per_day, null);
  assert.strictEqual(r.value.max_attempts_per_day, null);
});

test('validateLimitsBody: отрицательное/нечисло → ошибка', () => {
  assert.strictEqual(validateLimitsBody({ max_per_day: '-1' }).ok, false);
  assert.strictEqual(validateLimitsBody({ max_per_day: 'x' }).ok, false);
});
```

- [ ] **Step 2: FAIL**

Run: `node --test --test-force-exit tests/test_publish_limits_api.test.js`
Expected: FAIL — `validateLimitsBody is not a function`.

- [ ] **Step 3: Реализовать `validateLimitsBody` в `publish_limits.js`**

```js
// Валидация тела per-проект override: каждое поле — положит. целое или пусто(=null/наследование).
function validateLimitsBody(body) {
  const fields = ['max_per_day', 'max_attempts_per_day', 'rampup_days', 'rampup_max_per_day'];
  const value = {};
  for (const f of fields) {
    const raw = body[f];
    if (raw === '' || raw === null || raw === undefined) { value[f] = null; continue; }
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 0) return { ok: false, error: `Поле ${f} должно быть целым ≥ 0` };
    value[f] = n;
  }
  return { ok: true, value };
}
```

Добавить в `module.exports`.

- [ ] **Step 4: PASS**

Run: `node --test --test-force-exit tests/test_publish_limits_api.test.js`
Expected: PASS.

- [ ] **Step 5: Добавить эндпоинты в `server.js`**

После `app.put('/api/settings', ...)` (~1143) вставить:

```js
// ===== PUBLISH LIMITS (admin-only) =====
function requireAdmin(req, res) {
  if (req.session.user?.role !== 'admin') { res.status(403).json({ error: 'Forbidden' }); return false; }
  return true;
}

// Глобал (autowarm_settings) + список per-проект override.
app.get('/api/publish-limits', requireAuth, async (req, res) => {
  if (!requireAdmin(req, res)) return;
  try {
    const { rows: s } = await pool.query('SELECT key, value FROM autowarm_settings');
    const settings = {}; s.forEach(r => { settings[r.key] = r.value; });
    const { readGlobalLimits } = require('./publish_limits.js');
    const global = readGlobalLimits(settings);
    const enabled = process.env.PUBLISH_DAILY_LIMITS_ENABLED === 'true'
      || settings.publish_daily_limits_enabled === 'true';
    const { rows: overrides } = await pool.query(`
      SELECT ppl.project_id, vp.project AS project_name,
             ppl.max_per_day, ppl.max_attempts_per_day, ppl.rampup_days, ppl.rampup_max_per_day
      FROM publish_project_limits ppl
      LEFT JOIN validator_projects vp ON vp.id = ppl.project_id
      ORDER BY vp.project NULLS LAST`);
    res.json({ enabled, global, overrides });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// Сохранить глобал и/или один per-проект override.
app.put('/api/publish-limits', requireAuth, async (req, res) => {
  if (!requireAdmin(req, res)) return;
  try {
    const { validateLimitsBody } = require('./publish_limits.js');
    // 1) глобал
    if (req.body.global) {
      const v = validateLimitsBody(req.body.global);
      if (!v.ok) return res.status(400).json({ error: v.error });
      const map = {
        publish_max_per_day: v.value.max_per_day, publish_max_attempts_per_day: v.value.max_attempts_per_day,
        publish_rampup_days: v.value.rampup_days, publish_rampup_max_per_day: v.value.rampup_max_per_day,
      };
      for (const [k, val] of Object.entries(map)) {
        if (val === null) continue; // глобал не наследует — пустое поле не перетираем
        await pool.query('INSERT INTO autowarm_settings (key,value) VALUES ($1,$2) ON CONFLICT (key) DO UPDATE SET value=$2', [k, String(val)]);
      }
      if (typeof req.body.enabled === 'boolean') {
        await pool.query('INSERT INTO autowarm_settings (key,value) VALUES ($1,$2) ON CONFLICT (key) DO UPDATE SET value=$2',
          ['publish_daily_limits_enabled', req.body.enabled ? 'true' : 'false']);
      }
    }
    // 2) per-проект override (upsert; все поля null → удалить строку = вернуть к глобалу)
    if (req.body.project_id) {
      const pid = parseInt(req.body.project_id, 10);
      if (!Number.isInteger(pid)) return res.status(400).json({ error: 'project_id некорректен' });
      const v = validateLimitsBody(req.body.override || {});
      if (!v.ok) return res.status(400).json({ error: v.error });
      const allNull = Object.values(v.value).every(x => x === null);
      if (allNull) {
        await pool.query('DELETE FROM publish_project_limits WHERE project_id=$1', [pid]);
      } else {
        await pool.query(`
          INSERT INTO publish_project_limits (project_id, max_per_day, max_attempts_per_day, rampup_days, rampup_max_per_day, updated_at)
          VALUES ($1,$2,$3,$4,$5, now())
          ON CONFLICT (project_id) DO UPDATE SET
            max_per_day=$2, max_attempts_per_day=$3, rampup_days=$4, rampup_max_per_day=$5, updated_at=now()`,
          [pid, v.value.max_per_day, v.value.max_attempts_per_day, v.value.rampup_days, v.value.rampup_max_per_day]);
      }
    }
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});
```

- [ ] **Step 6: Синтаксис-чек**

Run: `node -c server.js`
Expected: без вывода.

- [ ] **Step 7: Commit**

```bash
git add server.js publish_limits.js tests/test_publish_limits_api.test.js
git commit -m "feat(op139): API GET/PUT /api/publish-limits (admin-only) + валидатор тела"
```

---

## Task 6: UI — раздел сайдбара «Публикация» (admin-only)

**Files:**
- Modify: `public/index.html` — пункт меню в `sidebar-publishing`, `section-publish-settings`, `nav()` hook, `loadPublishLimits()`/`savePublishLimits()`, admin-видимость в `loadCurrentUser`

Фронт — inline-JS без тест-харнеса: реализуем зеркаля существующие паттерны (`saveSchedulerSettings` PUT, `loadGlobalSettings` GET, скрытие по роли в `loadCurrentUser`). Проверка — синтаксис страницы и ручная UI-приёмка.

- [ ] **Step 1: Добавить пункт меню в сайдбар `sidebar-publishing`**

Найти `<nav id="sidebar-publishing"` и добавить пункт (рядом с прочими `nav-item`), с `id` для admin-скрытия:

```html
<button onclick="nav('publish-settings')" id="nav-publish-settings" class="nav-item w-full text-left px-3 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50">📋 Публикация</button>
```

- [ ] **Step 2: Добавить секцию `section-publish-settings`**

Рядом с другими `<div id="section-...">` (например, после `section-global-settings`) добавить:

```html
<div id="section-publish-settings" class="section max-w-2xl mx-auto px-4 py-6 fade-in">
  <h2 class="text-lg font-semibold mb-4">📋 Лимиты публикаций</h2>
  <div class="bg-white rounded-xl border p-4 space-y-3 mb-6">
    <h3 class="font-medium">Глобальные лимиты (дефолт для всех проектов)</h3>
    <label class="flex items-center justify-between text-sm">Макс. публикаций в день на аккаунт
      <input id="pl-max-per-day" type="number" min="0" class="border rounded px-2 py-1 w-24 text-right"></label>
    <label class="flex items-center justify-between text-sm">Макс. попыток в день на аккаунт
      <input id="pl-max-attempts" type="number" min="0" class="border rounded px-2 py-1 w-24 text-right"></label>
    <label class="flex items-center justify-between text-sm">Разгон новых проектов: первые (дней)
      <input id="pl-rampup-days" type="number" min="0" class="border rounded px-2 py-1 w-24 text-right"></label>
    <label class="flex items-center justify-between text-sm">Лимит в дни разгона (постов/день)
      <input id="pl-rampup-max" type="number" min="0" class="border rounded px-2 py-1 w-24 text-right"></label>
    <label class="flex items-center gap-2 text-sm"><input id="pl-enabled" type="checkbox"> Лимиты включены</label>
    <button onclick="savePublishLimits()" class="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm">Сохранить глобальные</button>
  </div>
  <div class="bg-white rounded-xl border p-4 space-y-3">
    <h3 class="font-medium">Переопределение по проектам</h3>
    <div class="flex items-end gap-2 text-sm flex-wrap">
      <label>Проект<br><select id="pl-proj" class="border rounded px-2 py-1"></select></label>
      <label>/день<br><input id="pl-ov-max" type="number" min="0" class="border rounded px-2 py-1 w-20"></label>
      <label>попыток<br><input id="pl-ov-attempts" type="number" min="0" class="border rounded px-2 py-1 w-20"></label>
      <label>разгон дней<br><input id="pl-ov-rdays" type="number" min="0" class="border rounded px-2 py-1 w-20"></label>
      <label>разгон/день<br><input id="pl-ov-rmax" type="number" min="0" class="border rounded px-2 py-1 w-20"></label>
      <button onclick="savePublishOverride()" class="bg-indigo-600 text-white px-3 py-2 rounded-lg">Сохранить</button>
    </div>
    <p class="text-xs text-gray-500">Пустое поле = наследует глобальное. Все пустые = удалить переопределение.</p>
    <table class="w-full text-sm mt-2"><thead><tr class="text-left text-gray-500">
      <th>Проект</th><th>/день</th><th>попыток</th><th>разгон</th></tr></thead>
      <tbody id="pl-ov-tbody"></tbody></table>
  </div>
</div>
```

- [ ] **Step 3: Зарегистрировать раздел в `nav()`**

В `sidebarMap2` (server `public/index.html` ~4147) добавить `'publish-settings':'publishing',`. В конец цепочки `if (section === ...)` (после ~4187) добавить:

```js
  if (section === 'publish-settings') loadPublishLimits();
```

- [ ] **Step 4: Реализовать загрузку/сохранение**

Рядом с `saveSchedulerSettings` (или в конце `<script>`) добавить:

```js
async function loadPublishLimits() {
  const res = await fetch('/api/publish-limits');
  if (res.status === 403) { document.getElementById('section-publish-settings').innerHTML = '<p class="text-red-600 p-4">Доступ только для администраторов.</p>'; return; }
  const d = await res.json();
  document.getElementById('pl-max-per-day').value = d.global.maxPerDay;
  document.getElementById('pl-max-attempts').value = d.global.maxAttemptsPerDay;
  document.getElementById('pl-rampup-days').value = d.global.rampupDays;
  document.getElementById('pl-rampup-max').value = d.global.rampupMaxPerDay;
  document.getElementById('pl-enabled').checked = !!d.enabled;
  // список проектов в селект
  const proj = document.getElementById('pl-proj');
  const pr = await (await fetch('/api/projects')).json();
  proj.innerHTML = (Array.isArray(pr) ? pr : (pr.projects || []))
    .map(p => `<option value="${p.id}">${p.project || p.name || p.id}</option>`).join('');
  // таблица override
  document.getElementById('pl-ov-tbody').innerHTML = (d.overrides || []).map(o =>
    `<tr><td>${o.project_name || o.project_id}</td><td>${o.max_per_day ?? '—'}</td>`
    + `<td>${o.max_attempts_per_day ?? '—'}</td>`
    + `<td>${o.rampup_days ?? '—'}${o.rampup_max_per_day != null ? 'д→'+o.rampup_max_per_day : ''}</td></tr>`).join('');
}

async function savePublishLimits() {
  const body = { global: {
    max_per_day: document.getElementById('pl-max-per-day').value,
    max_attempts_per_day: document.getElementById('pl-max-attempts').value,
    rampup_days: document.getElementById('pl-rampup-days').value,
    rampup_max_per_day: document.getElementById('pl-rampup-max').value,
  }, enabled: document.getElementById('pl-enabled').checked };
  const res = await fetch('/api/publish-limits', { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const j = await res.json();
  alert(res.ok ? 'Сохранено ✓' : ('Ошибка: ' + (j.error || res.status)));
  if (res.ok) loadPublishLimits();
}

async function savePublishOverride() {
  const body = { project_id: document.getElementById('pl-proj').value, override: {
    max_per_day: document.getElementById('pl-ov-max').value,
    max_attempts_per_day: document.getElementById('pl-ov-attempts').value,
    rampup_days: document.getElementById('pl-ov-rdays').value,
    rampup_max_per_day: document.getElementById('pl-ov-rmax').value,
  }};
  const res = await fetch('/api/publish-limits', { method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const j = await res.json();
  alert(res.ok ? 'Сохранено ✓' : ('Ошибка: ' + (j.error || res.status)));
  if (res.ok) loadPublishLimits();
}
```

- [ ] **Step 5: Admin-only видимость пункта меню**

В `loadCurrentUser` (после блока с `module-tab`, ~5146) добавить скрытие пункта для не-админов:

```js
    const plBtn = document.getElementById('nav-publish-settings');
    if (plBtn) plBtn.style.display = (currentUser.role === 'admin') ? '' : 'none';
```

- [ ] **Step 6: Проверить, что HTML парсится (нет сломанных тегов/скобок)**

Run: `node -e "const fs=require('fs');const h=fs.readFileSync('public/index.html','utf8');const o=(h.match(/<script/g)||[]).length,c=(h.match(/<\/script>/g)||[]).length;if(o!==c)throw new Error('script tags '+o+'/'+c);console.log('script tags balanced:',o)"`
Expected: `script tags balanced: <N>`.

- [ ] **Step 7: Commit**

```bash
git add public/index.html
git commit -m "feat(op139): раздел сайдбара «Публикация» (admin-only) — настройки лимитов"
```

---

## Task 7: Финальная проверка интеграции

- [ ] **Step 1: Полный прогон тест-сьюта**

Run: `node --test --test-force-exit tests/*.test.js`
Expected: все новые тесты PASS; известный предсуществующий fail `test_manual_publish_queue › takeItem: 404 when row missing` допустим (не связан). Иных регрессий быть не должно.

- [ ] **Step 2: Синтаксис всех изменённых файлов**

Run: `node -c server.js && node -c retry_controller.js && node -c publish_limits.js && echo OK`
Expected: `OK`.

- [ ] **Step 3: Проверить, что при kill-switch OFF поведение неизменно**

Убедиться (чтением кода): обе ветки гейтов входят только при `limitsEnabled`/`dailyLimitsEnabled`. При флаге OFF (`PUBLISH_DAILY_LIMITS_ENABLED` не 'true' И `publish_daily_limits_enabled` ≠ 'true') — гейт A идёт прежним путём (общий `computeDeviceSlot` без переноса дня), гейт B не выполняется. Зафиксировать это в финальном отчёте.

---

## Self-Review (выполнено автором плана)

- **Покрытие спека:** таблица override (T1), резолвер+ramp-up (T2), гейт постов с переносом (T3), гейт попыток с handoff (T4), API admin-only (T5), UI-раздел admin-only (T6), kill-switch (T3/T4/T7), ramp-up от MIN(slot_date) (T3/T4). Все разделы спека покрыты.
- **Типы/имена согласованы:** `readGlobalLimits`/`resolveDailyLimits`/`nextAvailableDay`/`gateAssignDay`/`attemptsCapReached`/`validateLimitsBody` определены в T2-T5 и используются согласованно; поля override (`max_per_day` и т.д.) едины в таблице, валидаторе, API и UI.
- **Плейсхолдеров нет:** каждый шаг содержит реальный код/команду.
- **Замечание для исполнителя:** `/api/projects` форма ответа может быть массивом или `{projects:[...]}` — `loadPublishLimits` обрабатывает оба; если структура иная, поправить парсинг по факту.
