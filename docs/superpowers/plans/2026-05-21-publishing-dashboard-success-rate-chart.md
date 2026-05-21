# Publishing Dashboard — Success-rate Trend Chart + Filters — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить на дашборд выкладки линейный график success rate в динамике по платформам (IG/TT/YT + «Все») с метками значений, плюс серверные фильтры (проект/платформа/аккаунт/пак) и пресеты «Вчера»/«Последние 3 дня» — всё применяется и к плиткам, и к графику.

**Architecture:** Расширяем ОДИН существующий эндпоинт `GET /api/publish-queue/dashboard` (server.js): добавляем фильтры (переиспользуя SQL-фрагменты `buildPublishQueueFilters`) и возвращаем `series` (тренд по бакетам) рядом с `overall`/`by_platform`. Бакет час/день выбирается по длине диапазона. Ось бакетов и сборка серии — чистые JS-функции (тестируются без БД); сам SQL покрывается ручной проверкой. Фронт — ванильный JS + Chart.js (уже подключён) + локально подключённый `chartjs-plugin-datalabels`.

**Tech Stack:** Node/Express + node-postgres; `node --test` (тесты в `tests/*.test.js`); ванильный JS + Tailwind + Chart.js v4 в `public/index.html`.

**Спека:** `docs/superpowers/specs/2026-05-21-publishing-dashboard-success-rate-chart-design.md`

---

## Окружение и деплой (прочитать перед началом)

- **Код живёт в репозитории `delivery-contenthunter`**, прод-чекаут: `/root/.openclaw/workspace-genri/autowarm/` (writable без sudo). Файлы: `server.js`, `public/index.html`, `tests/`. План/спека живут отдельно — в репо `contenthunter` (этот worktree).
- **Изоляция разработки:** работать в отдельном worktree прод-репо, НЕ править прод-чекаут напрямую до деплоя:
  ```bash
  git -C /root/.openclaw/workspace-genri/autowarm worktree add /home/claude-user/wt-wp90-impl -b wp90-success-rate-impl HEAD
  ln -s /root/.openclaw/workspace-genri/autowarm/node_modules /home/claude-user/wt-wp90-impl/node_modules   # для node --test
  cd /home/claude-user/wt-wp90-impl && npm test   # baseline — должно быть зелёным
  ```
- **Тесты:** `npm test` (= `node --test --test-force-exit tests/*.test.js`). Запускать перед каждым коммитом.
- **Деплой (после зелёных тестов и ревью):** скопировать `server.js` + `public/index.html` (+ изменённый тест) в прод-чекаут, добавить env при необходимости, `pm2 restart`. ⚠️ ГОТЧИ (memory `project_daily_publish_report`, `pm2_dump_path_drift`): (1) прод-чекаут может содержать чужую незакоммиченную WIP — копировать файлы хирургически, не `git pull`/`reset`; (2) перед рестартом `pm2 describe <app> | grep "exec cwd"` — убедиться, что PM2 читает прод-путь, а не testbench; (3) `index.html` — auto-push hook отправит коммит в GitHub, без force-push.
- **Все новые pure-функции экспортировать** из `server.js` (блок `module.exports` ~строка 8439), иначе тесты их не увидят.

---

## File Structure

- **Modify** `server.js`:
  - `calcDashboardRange` (~1666) — +ветки `yesterday`, `last3`.
  - +`pickBucketUnit(range)` — выбор `'hour'|'day'`.
  - +`buildDashboardFilters(query, startIndex)` — подмножество фильтров (project/platform/account/pack).
  - +`buildBucketAxis(fromMs, toMs, unit)` — полная ось MSK-бакетов (метки).
  - +`assembleSeries(rows, axis)` — SQL-строки серии → `{all,instagram,tiktok,youtube}` точек.
  - +`isDashboardTimeseriesEnabled()` — env kill-switch.
  - Эндпоинт `GET /api/publish-queue/dashboard` (~1832) — фильтры + `PUBLISH_QUEUE_FROM` + `series`.
  - `module.exports` (~8439) — +5 новых функций.
- **Modify** `tests/test_publish_dashboard.test.js` — поправить тест `'yesterday' → throws`; +тесты новых helpers.
- **Modify** `public/index.html`:
  - `<head>` (~строка 11) — +CDN `chartjs-plugin-datalabels` + глобальное отключение меток.
  - HTML `#section-publishing-dashboard` (~2257) — +кнопки пресетов, +строка фильтров, +карточка графика.
  - JS (~11533–11675) — фильтр-стейт, метки диапазона, фильтры→загрузка, рендер графика, тумблер меток.
  - URL-restore (~4018) — расширить whitelist пресетов.

---

## Task 1: calcDashboardRange — пресеты `yesterday` и `last3` (+ починка существующего теста)

**Files:**
- Modify: `tests/test_publish_dashboard.test.js` (тест `unknown preset` — заменить `'yesterday'` на действительно неизвестный пресет; +новые тесты)
- Modify: `server.js:1666-1738` (`calcDashboardRange`, добавить ветки до финального `throw`)

- [ ] **Step 1: Починить ломающийся тест + написать новые failing-тесты**

В `tests/test_publish_dashboard.test.js` заменить блок теста `'unknown preset → throws'` (сейчас использует `'yesterday'`, который станет валидным):

```js
  test('unknown preset → throws', () => {
    assert.throws(
      () => calcDashboardRange('nonsense', null, null, Date.UTC(2026, 4, 11)),
      /unknown preset/
    );
  });

  test('yesterday: May 11 09:00 UTC → [2026-05-09 21:00Z, 2026-05-10 21:00Z)', () => {
    const now = Date.UTC(2026, 4, 11, 9, 0, 0);
    const r = calcDashboardRange('yesterday', null, null, now);
    assert.equal(r.preset, 'yesterday');
    assert.equal(r.from.toISOString(), '2026-05-09T21:00:00.000Z');
    assert.equal(r.to.toISOString(),   '2026-05-10T21:00:00.000Z');
  });

  test('last3: May 11 09:00 UTC → [2026-05-08 21:00Z, 2026-05-11 21:00Z) (3 дня вкл. сегодня)', () => {
    const now = Date.UTC(2026, 4, 11, 9, 0, 0);
    const r = calcDashboardRange('last3', null, null, now);
    assert.equal(r.preset, 'last3');
    assert.equal(r.from.toISOString(), '2026-05-08T21:00:00.000Z');
    assert.equal(r.to.toISOString(),   '2026-05-11T21:00:00.000Z');
  });
```

- [ ] **Step 2: Запустить тесты — убедиться, что новые падают**

Run: `npm test 2>&1 | grep -A2 -iE "yesterday|last3"`
Expected: FAIL — `calcDashboardRange('yesterday')` пока бросает `unknown preset`.

- [ ] **Step 3: Добавить ветки в `calcDashboardRange`**

В `server.js`, сразу ПОСЛЕ блока `if (preset === 'month') { ... }` (перед `if (preset === 'custom')`), вставить:

```js
  if (preset === 'yesterday') {
    return {
      preset: 'yesterday',
      from: new Date(dayMsMsk - DAY_MS - MSK_OFFSET_MS),
      to:   new Date(dayMsMsk - MSK_OFFSET_MS),
    };
  }

  if (preset === 'last3') {
    // 3 календарных дня, включая сегодня: [сегодня-2 00:00 MSK, завтра 00:00 MSK)
    return {
      preset: 'last3',
      from: new Date(dayMsMsk - 2 * DAY_MS - MSK_OFFSET_MS),
      to:   new Date(dayMsMsk + DAY_MS - MSK_OFFSET_MS),
    };
  }
```

- [ ] **Step 4: Запустить тесты — зелёные**

Run: `npm test 2>&1 | tail -5`
Expected: PASS (все тесты дашборда, включая старые today/week/month/custom).

- [ ] **Step 5: Commit**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(dashboard): add yesterday/last3 presets to calcDashboardRange (WP #90)"
```

---

## Task 2: pickBucketUnit — выбор гранулярности

**Files:**
- Modify: `tests/test_publish_dashboard.test.js`
- Modify: `server.js` (добавить функцию после `calcDashboardRange`, до `computeSuccessRate`; экспорт в Task 6)

- [ ] **Step 1: Failing-тесты**

Добавить в импорт верхнего блока теста `pickBucketUnit`:

```js
const {
  calcDashboardRange,
  mapDashboardRows,
  computeSuccessRate,
  pickBucketUnit,
} = require('../server.js');
```

И новый describe-блок (после блока `calcDashboardRange`):

```js
describe('pickBucketUnit — hour для ≤1 дня, иначе day', () => {
  const at = Date.UTC(2026, 4, 11, 9, 0, 0);
  test('today → hour', () => assert.equal(pickBucketUnit(calcDashboardRange('today', null, null, at)), 'hour'));
  test('yesterday → hour', () => assert.equal(pickBucketUnit(calcDashboardRange('yesterday', null, null, at)), 'hour'));
  test('custom single day → hour', () =>
    assert.equal(pickBucketUnit(calcDashboardRange('custom', '2026-05-11', '2026-05-11', at)), 'hour'));
  test('last3 → day', () => assert.equal(pickBucketUnit(calcDashboardRange('last3', null, null, at)), 'day'));
  test('week → day', () => assert.equal(pickBucketUnit(calcDashboardRange('week', null, null, at)), 'day'));
  test('month → day', () => assert.equal(pickBucketUnit(calcDashboardRange('month', null, null, at)), 'day'));
});
```

- [ ] **Step 2: Запустить — падает**

Run: `npm test 2>&1 | grep -i pickBucketUnit | head`
Expected: FAIL — `pickBucketUnit is not a function`.

- [ ] **Step 3: Реализация**

В `server.js`, сразу после функции `calcDashboardRange` (до `function computeSuccessRate`):

```js
function pickBucketUnit(range) {
  const spanMs = range.to.getTime() - range.from.getTime();
  return spanMs <= DAY_MS ? 'hour' : 'day';
}
```

(`DAY_MS` уже объявлен на ~строке 1663.)

- [ ] **Step 4: Запустить — зелёные** (после добавления экспорта в Task 6 — здесь тест упадёт на отсутствии экспорта; временно можно прогнать после Task 6. Чтобы держать TDD-ритм, экспорт `pickBucketUnit` добавить сразу в этом шаге.)

Добавить в `module.exports` (~8441, рядом с `mapDashboardRows`):

```js
  module.exports.pickBucketUnit = pickBucketUnit;
```

Run: `npm test 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(dashboard): pickBucketUnit (hour for <=1 day, else day) (WP #90)"
```

---

## Task 3: buildDashboardFilters — серверные фильтры

**Files:**
- Modify: `tests/test_publish_dashboard.test.js`
- Modify: `server.js` (после `buildPublishQueueFilters` ~1827; экспорт)

- [ ] **Step 1: Failing-тесты**

Добавить `buildDashboardFilters` в импорт. Новый describe-блок:

```js
const { buildDashboardFilters } = require('../server.js');

describe('buildDashboardFilters — подмножество фильтров (offset $1,$2 = range)', () => {
  test('пустой query → нет условий', () => {
    const f = buildDashboardFilters({}, 2);
    assert.deepEqual(f.conds, []);
    assert.deepEqual(f.params, []);
  });
  test('project → нумерация с $3', () => {
    const f = buildDashboardFilters({ project: 'Alpha' }, 2);
    assert.deepEqual(f.conds, ['COALESCE(vp.project, vp2.project) = $3']);
    assert.deepEqual(f.params, ['Alpha']);
  });
  test('platform приводится к lower', () => {
    const f = buildDashboardFilters({ platform: 'Instagram' }, 2);
    assert.deepEqual(f.conds, ['LOWER(pq.platform) = $3']);
    assert.deepEqual(f.params, ['instagram']);
  });
  test('account/pack — ILIKE с обёрткой %', () => {
    const f = buildDashboardFilters({ account_username: 'bob', pack_name: 'p1' }, 2);
    assert.deepEqual(f.conds, ['pq.account_username ILIKE $3', 'pq.pack_name ILIKE $4']);
    assert.deepEqual(f.params, ['%bob%', '%p1%']);
  });
  test('все 4 фильтра — $3..$6 в фикс. порядке', () => {
    const f = buildDashboardFilters({ project: 'A', platform: 'tiktok', account_username: 'x', pack_name: 'y' }, 2);
    assert.deepEqual(f.conds, [
      'COALESCE(vp.project, vp2.project) = $3',
      'LOWER(pq.platform) = $4',
      'pq.account_username ILIKE $5',
      'pq.pack_name ILIKE $6',
    ]);
    assert.deepEqual(f.params, ['A', 'tiktok', '%x%', '%y%']);
  });
});
```

- [ ] **Step 2: Запустить — падает**

Run: `npm test 2>&1 | grep -i buildDashboardFilters | head`
Expected: FAIL — не функция.

- [ ] **Step 3: Реализация**

В `server.js`, сразу после функции `buildPublishQueueFilters` (после строки `}` ~1827):

```js
// Подмножество buildPublishQueueFilters для дашборда: project/platform/account/pack.
// Нумерация placeholder'ов начинается с startIndex+1 (range занимает $1,$2).
function buildDashboardFilters(query, startIndex = 0) {
  const conds = [];
  const params = [];
  const push = (tpl, val) => { params.push(val); conds.push(tpl.replace('$?', '$' + (startIndex + params.length))); };
  if (query.project)          push('COALESCE(vp.project, vp2.project) = $?', String(query.project));
  if (query.platform)         push('LOWER(pq.platform) = $?',                String(query.platform).toLowerCase());
  if (query.account_username) push('pq.account_username ILIKE $?',           '%' + String(query.account_username) + '%');
  if (query.pack_name)        push('pq.pack_name ILIKE $?',                  '%' + String(query.pack_name) + '%');
  return { conds, params };
}
```

Добавить экспорт (~8441):

```js
  module.exports.buildDashboardFilters = buildDashboardFilters;
```

- [ ] **Step 4: Запустить — зелёные**

Run: `npm test 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(dashboard): buildDashboardFilters (project/platform/account/pack) (WP #90)"
```

---

## Task 4: buildBucketAxis — полная ось MSK-бакетов

**Files:**
- Modify: `tests/test_publish_dashboard.test.js`
- Modify: `server.js` (рядом с `pickBucketUnit`; экспорт)

**Контракт меток (должен совпасть с SQL `to_char`):** `day` → `'YYYY-MM-DD'`; `hour` → `'YYYY-MM-DD HH:MM'` (минуты всегда `00`).

- [ ] **Step 1: Failing-тесты**

Добавить `buildBucketAxis` в импорт. Новый describe:

```js
const { buildBucketAxis } = require('../server.js');

describe('buildBucketAxis — MSK-метки бакетов', () => {
  test('day: неделя из 7 дневных меток', () => {
    const r = calcDashboardRange('week', null, null, Date.UTC(2026, 4, 13, 9, 0, 0)); // Mon 05-11 .. Mon 05-18
    const axis = buildBucketAxis(r.from.getTime(), r.to.getTime(), 'day');
    assert.deepEqual(axis, ['2026-05-11','2026-05-12','2026-05-13','2026-05-14','2026-05-15','2026-05-16','2026-05-17']);
  });
  test('hour: today → 24 часовые метки, первая 00:00 MSK', () => {
    const r = calcDashboardRange('today', null, null, Date.UTC(2026, 4, 11, 9, 0, 0));
    const axis = buildBucketAxis(r.from.getTime(), r.to.getTime(), 'hour');
    assert.equal(axis.length, 24);
    assert.equal(axis[0], '2026-05-11 00:00');
    assert.equal(axis[23], '2026-05-11 23:00');
  });
  test('day: last3 → 3 метки вкл. сегодня', () => {
    const r = calcDashboardRange('last3', null, null, Date.UTC(2026, 4, 11, 9, 0, 0));
    const axis = buildBucketAxis(r.from.getTime(), r.to.getTime(), 'day');
    assert.deepEqual(axis, ['2026-05-09','2026-05-10','2026-05-11']);
  });
});
```

- [ ] **Step 2: Запустить — падает**

Run: `npm test 2>&1 | grep -i buildBucketAxis | head`
Expected: FAIL.

- [ ] **Step 3: Реализация**

В `server.js`, после `pickBucketUnit`:

```js
const HOUR_MS = 60 * 60 * 1000;

// Полная последовательность MSK-меток бакетов на [fromMs, toMs).
// fromMs/toMs — UTC-инстанты из calcDashboardRange (MSK-полночь и т.п.).
// Метки: day → 'YYYY-MM-DD'; hour → 'YYYY-MM-DD HH:MM' (совпадает с SQL to_char).
function buildBucketAxis(fromMs, toMs, unit) {
  const step = unit === 'hour' ? HOUR_MS : DAY_MS;
  const fmt = (ms) => {
    const iso = new Date(ms + MSK_OFFSET_MS).toISOString(); // MSK-wall как будто UTC
    return unit === 'hour' ? iso.slice(0, 16).replace('T', ' ') : iso.slice(0, 10);
  };
  const labels = [];
  for (let ms = fromMs; ms < toMs; ms += step) labels.push(fmt(ms));
  return labels;
}
```

Экспорт (~8441):

```js
  module.exports.buildBucketAxis = buildBucketAxis;
```

- [ ] **Step 4: Запустить — зелёные**

Run: `npm test 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(dashboard): buildBucketAxis — MSK hour/day labels (WP #90)"
```

---

## Task 5: assembleSeries — SQL-строки серии → точки `{rate,done,denom}`

**Files:**
- Modify: `tests/test_publish_dashboard.test.js`
- Modify: `server.js` (после `assembleSeries`-зависимостей; экспорт)

- [ ] **Step 1: Failing-тесты**

Добавить `assembleSeries` в импорт. Новый describe:

```js
const { assembleSeries } = require('../server.js');

describe('assembleSeries — выравнивание по оси, {rate,done,denom}|null', () => {
  const axis = ['2026-05-19', '2026-05-20'];

  test('all + IG в день 19; день 20 пустой → null; TT/YT все null', () => {
    const rows = [
      { bkt: '2026-05-19', platform_key: 'all',       is_all: 1, done: 90, errors: 10 },
      { bkt: '2026-05-19', platform_key: 'instagram', is_all: 0, done: 32, errors: 4  },
    ];
    const out = assembleSeries(rows, axis);
    assert.deepEqual(out.all[0], { rate: 0.9, done: 90, denom: 100 });
    assert.deepEqual(out.instagram[0], { rate: 0.889, done: 32, denom: 36 });
    assert.equal(out.all[1], null);
    assert.equal(out.instagram[1], null);
    assert.deepEqual(out.tiktok, [null, null]);
    assert.deepEqual(out.youtube, [null, null]);
  });

  test('denom==0 (только pending/cancelled) → точка null', () => {
    const rows = [{ bkt: '2026-05-19', platform_key: 'all', is_all: 1, done: 0, errors: 0 }];
    const out = assembleSeries(rows, axis);
    assert.equal(out.all[0], null);
  });

  test('unknown/vk per-platform строки игнорируются (учтены в all)', () => {
    const rows = [
      { bkt: '2026-05-19', platform_key: 'all',     is_all: 1, done: 7, errors: 3 },
      { bkt: '2026-05-19', platform_key: 'vk',      is_all: 0, done: 5, errors: 1 },
      { bkt: '2026-05-19', platform_key: 'unknown', is_all: 0, done: 2, errors: 2 },
    ];
    const out = assembleSeries(rows, axis);
    assert.deepEqual(out.all[0], { rate: 0.7, done: 7, denom: 10 });
    // vk/unknown не попадают в отдельные линии
    assert.deepEqual(out.tiktok, [null, null]);
  });

  test('pg-driver строки-числа приводятся к Number', () => {
    const rows = [{ bkt: '2026-05-20', platform_key: 'youtube', is_all: '0', done: '3', errors: '1' }];
    const out = assembleSeries(rows, axis);
    assert.deepEqual(out.youtube[1], { rate: 0.75, done: 3, denom: 4 });
  });
});
```

- [ ] **Step 2: Запустить — падает**

Run: `npm test 2>&1 | grep -i assembleSeries | head`
Expected: FAIL.

- [ ] **Step 3: Реализация**

В `server.js`, после `mapDashboardRows` (~1781):

```js
const DASHBOARD_SERIES_KEYS = ['all', 'instagram', 'tiktok', 'youtube'];

// SQL-строки серии (GROUPING SETS ((bkt,plat),(bkt))) → выровненные по axis массивы.
// Точка: { rate, done, denom(=done+errors) } либо null (denom==0 или нет строки).
function assembleSeries(rows, axis) {
  const idx = {};
  axis.forEach((label, i) => { idx[label] = i; });
  const out = {};
  for (const k of DASHBOARD_SERIES_KEYS) out[k] = axis.map(() => null);

  for (const r of rows) {
    const key = Number(r.is_all) === 1
      ? 'all'
      : (DASHBOARD_PLATFORMS.includes(r.platform_key) ? r.platform_key : null);
    if (key === null) continue;                 // unknown/vk/etc — только в 'all' через grand-total
    const i = idx[r.bkt];
    if (i === undefined) continue;              // защита: бакет вне оси
    const done = Number(r.done);
    const errors = Number(r.errors);
    const denom = done + errors;
    out[key][i] = denom === 0 ? null : { rate: computeSuccessRate(done, errors), done, denom };
  }
  return out;
}
```

(`DASHBOARD_PLATFORMS` уже объявлен на ~1746.)

Экспорт (~8441):

```js
  module.exports.assembleSeries = assembleSeries;
```

- [ ] **Step 4: Запустить — зелёные**

Run: `npm test 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(dashboard): assembleSeries — series rows to aligned {rate,done,denom} (WP #90)"
```

---

## Task 6: isDashboardTimeseriesEnabled — kill-switch

**Files:**
- Modify: `tests/test_publish_dashboard.test.js`
- Modify: `server.js` (рядом с другими env-хелперами; экспорт)

- [ ] **Step 1: Failing-тесты**

Добавить `isDashboardTimeseriesEnabled` в импорт. Новый describe:

```js
const { isDashboardTimeseriesEnabled } = require('../server.js');

describe('isDashboardTimeseriesEnabled — env kill-switch (default on)', () => {
  const orig = process.env.DASHBOARD_TIMESERIES_ENABLED;
  test('unset → true', () => { delete process.env.DASHBOARD_TIMESERIES_ENABLED; assert.equal(isDashboardTimeseriesEnabled(), true); });
  test('"0" → false', () => { process.env.DASHBOARD_TIMESERIES_ENABLED = '0'; assert.equal(isDashboardTimeseriesEnabled(), false); });
  test('"1" → true', () => { process.env.DASHBOARD_TIMESERIES_ENABLED = '1'; assert.equal(isDashboardTimeseriesEnabled(), true); });
  process.env.DASHBOARD_TIMESERIES_ENABLED = orig;
});
```

- [ ] **Step 2: Запустить — падает**

Run: `npm test 2>&1 | grep -i isDashboardTimeseries | head`
Expected: FAIL.

- [ ] **Step 3: Реализация**

В `server.js`, рядом с `pickBucketUnit`:

```js
function isDashboardTimeseriesEnabled() {
  return String(process.env.DASHBOARD_TIMESERIES_ENABLED || '1') !== '0';
}
```

Экспорт (~8441):

```js
  module.exports.isDashboardTimeseriesEnabled = isDashboardTimeseriesEnabled;
```

- [ ] **Step 4: Запустить — зелёные**

Run: `npm test 2>&1 | tail -5`
Expected: PASS (весь файл `test_publish_dashboard.test.js`).

- [ ] **Step 5: Commit**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(dashboard): DASHBOARD_TIMESERIES_ENABLED kill-switch (WP #90)"
```

---

## Task 7: Эндпоинт — фильтры + серия в ответе

**Files:**
- Modify: `server.js:1832-1880` (`GET /api/publish-queue/dashboard`)

Чистые helpers уже покрыты тестами; SQL проверяется вручную (Step 4–5). JS-юнит-теста на сам обработчик нет (как и у базовой фичи).

- [ ] **Step 1: Переписать тело эндпоинта**

Заменить тело `app.get('/api/publish-queue/dashboard', ...)` (строки ~1832-1880) на:

```js
app.get('/api/publish-queue/dashboard', requireAuth, async (req, res) => {
  try {
    const preset = String(req.query.preset || 'today');
    const fromStr = req.query.from ? String(req.query.from) : null;
    const toStr = req.query.to ? String(req.query.to) : null;

    let range;
    try {
      range = calcDashboardRange(preset, fromStr, toStr);
    } catch (e) {
      return res.status(400).json({ error: String(e.message || e) });
    }

    // Фильтры: $1,$2 = диапазон, далее $3.. для project/platform/account/pack.
    const filt = buildDashboardFilters(req.query, 2);
    const whereSql = 'WHERE pq.scheduled_at >= $1 AND pq.scheduled_at < $2'
      + (filt.conds.length ? ' AND ' + filt.conds.join(' AND ') : '');
    const baseParams = [range.from, range.to, ...filt.params];

    // --- Плитки (snapshot) ---
    const tilesSql = `
      SELECT
        CASE
          WHEN GROUPING(pq.platform) = 1 THEN 'all'
          WHEN pq.platform IS NULL       THEN 'unknown'
          ELSE pq.platform
        END                                                                  AS bucket,
        GROUPING(pq.platform)                                                AS is_grand_total,
        COUNT(*)                                                             AS total,
        COUNT(*) FILTER (WHERE pq.status = 'pending')                        AS pending,
        COUNT(*) FILTER (WHERE pq.status = 'running')                        AS running,
        COUNT(*) FILTER (WHERE pq.status = 'done')                           AS done,
        COUNT(*) FILTER (WHERE pq.status IN ('failed','past_slot_dropped'))  AS errors,
        COUNT(*) FILTER (WHERE pq.status IN ('cancelled','skipped'))         AS cancelled_skipped
      ${PUBLISH_QUEUE_FROM}
      ${whereSql}
      GROUP BY GROUPING SETS ((pq.platform), ())
    `;
    const { rows: tileRows } = await pool.query(tilesSql, baseParams);
    const { overall, by_platform } = mapDashboardRows(tileRows);

    // --- Серия (тренд по бакетам) ---
    let series = null;
    if (isDashboardTimeseriesEnabled()) {
      const unit = pickBucketUnit(range);                 // 'hour' | 'day' (whitelisted by construction)
      const truncFmt = unit === 'hour' ? 'YYYY-MM-DD HH24:MI' : 'YYYY-MM-DD';
      const seriesSql = `
        WITH bucketed AS (
          SELECT
            to_char(date_trunc('${unit}', pq.scheduled_at + interval '3 hours'), '${truncFmt}') AS bkt,
            LOWER(pq.platform) AS plat,
            pq.status          AS status
          ${PUBLISH_QUEUE_FROM}
          ${whereSql}
        )
        SELECT
          bkt,
          CASE WHEN GROUPING(plat) = 1 THEN 'all'
               WHEN plat IS NULL       THEN 'unknown'
               ELSE plat END                                              AS platform_key,
          GROUPING(plat)                                                  AS is_all,
          COUNT(*) FILTER (WHERE status = 'done')                         AS done,
          COUNT(*) FILTER (WHERE status IN ('failed','past_slot_dropped')) AS errors
        FROM bucketed
        GROUP BY GROUPING SETS ((bkt, plat), (bkt))
      `;
      const { rows: seriesRows } = await pool.query(seriesSql, baseParams);
      const axis = buildBucketAxis(range.from.getTime(), range.to.getTime(), unit);
      series = Object.assign({ unit, buckets: axis }, assembleSeries(seriesRows, axis));
    }

    console.log('[pub-dash]', JSON.stringify({
      preset: range.preset, unit: series ? series.unit : null,
      buckets: series ? series.buckets.length : 0,
      filters: filt.params.length,
    }));

    return res.json({
      range: {
        preset: range.preset,
        from: range.from.toISOString(),
        to: range.to.toISOString(),
        tz: 'Europe/Moscow',
      },
      filters: {
        project: req.query.project || null,
        platform: req.query.platform || null,
        account_username: req.query.account_username || null,
        pack_name: req.query.pack_name || null,
      },
      overall,
      by_platform,
      series,
    });
  } catch (e) {
    console.error('[pub-dash] failed:', e);
    return res.status(500).json({ error: 'internal error' });
  }
});
```

- [ ] **Step 2: Прогнать все тесты (регрессий нет)**

Run: `npm test 2>&1 | tail -8`
Expected: PASS (helpers); эндпоинт без юнит-теста — проверяется вручную.

- [ ] **Step 3: Запустить сервер локально / на проде в dev и проверить плитки (обратная совместимость)**

Поскольку эндпоинт ходит в живую БД, проверка — против рабочей БД. Запрос без фильтров (плитки как раньше):

Run:
```bash
curl -s "http://localhost:<PORT>/api/publish-queue/dashboard?preset=week" -H "Cookie: <auth>" | python3 -m json.tool | head -40
```
Expected: есть `overall`, `by_platform`, `filters` (все null), `series` с `unit:"day"`, `buckets` (7), массивы `all/instagram/tiktok/youtube` той же длины.

- [ ] **Step 4: Проверить серию против прямого SQL**

Run (psql, тот же период — неделя; подставить MSK-границы из ответа `range`):
```sql
SELECT to_char(date_trunc('day', pq.scheduled_at + interval '3 hours'),'YYYY-MM-DD') AS bkt,
       LOWER(pq.platform) AS plat,
       COUNT(*) FILTER (WHERE pq.status='done') done,
       COUNT(*) FILTER (WHERE pq.status IN ('failed','past_slot_dropped')) errors
FROM publish_queue pq
WHERE pq.scheduled_at >= '<from>' AND pq.scheduled_at < '<to>'
GROUP BY 1,2 ORDER BY 1,2;
```
Expected: success rate из `series.instagram[i].rate*100` ≈ `done/(done+errors)*100` для соответствующего бакета.

- [ ] **Step 5: Проверить фильтр + kill-switch**

Run:
```bash
# фильтр платформы — плитки и серия сужаются
curl -s ".../dashboard?preset=week&platform=instagram" -H "Cookie: <auth>" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("by_platform.tiktok.total=",d["by_platform"]["tiktok"]["total"]);print("series.tiktok all null?",all(x is None for x in d["series"]["tiktok"]))'
# kill-switch
DASHBOARD_TIMESERIES_ENABLED=0  # установить в .env/окружении процесса, рестарт; series должно стать null
```
Expected: при `platform=instagram` `by_platform.tiktok.total==0` и `series.tiktok` все `null`; при kill-switch `series:null`.

- [ ] **Step 6: Commit**

```bash
git add server.js
git commit -m "feat(dashboard): extend /api/publish-queue/dashboard with filters + series (WP #90)"
```

---

## Task 8: Frontend — подключить datalabels, погасить глобально

**Files:**
- Modify: `public/index.html` (~строка 11, после `<script src=...chart.js>`)

- [ ] **Step 1: Добавить CDN-плагин и глобальное отключение меток**

После строки `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>` (index.html:11) вставить:

```html
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
  <script>
    // chartjs-plugin-datalabels UMD авто-регистрируется глобально → метки полезли бы на ВСЕ
    // графики (фарминг/SLA/токены). Гасим по умолчанию; включаем только на дашборде выкладки.
    if (window.Chart && window.ChartDataLabels) {
      Chart.defaults.set('plugins.datalabels', { display: false });
    }
  </script>
```

- [ ] **Step 2: Smoke — другие графики БЕЗ меток**

Открыть существующие графики (Фарминг / SLA-модал / Расход токенов), убедиться, что подписи значений на них НЕ появились.
Expected: внешний вид прежних графиков не изменился.

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "feat(dashboard): load chartjs-plugin-datalabels, disabled globally (WP #90)"
```

---

## Task 9: Frontend — HTML: пресеты, фильтры, карточка графика

**Files:**
- Modify: `public/index.html:2257-2297` (`#section-publishing-dashboard`)

- [ ] **Step 1: Добавить кнопки пресетов «Вчера» и «Последние 3 дня»**

В блоке кнопок (после кнопки `data-preset="today"`, index.html:2262) вставить:

```html
      <button data-preset="yesterday" onclick="switchDashboardPreset('yesterday')" class="dash-preset-btn px-3 py-1.5 text-xs font-semibold rounded-lg border bg-white text-gray-600 border-gray-200 hover:bg-gray-50">Вчера</button>
      <button data-preset="last3" onclick="switchDashboardPreset('last3')" title="3 календарных дня включая сегодня" class="dash-preset-btn px-3 py-1.5 text-xs font-semibold rounded-lg border bg-white text-gray-600 border-gray-200 hover:bg-gray-50">Последние 3 дня</button>
```

- [ ] **Step 2: Добавить строку фильтров**

Сразу ПОСЛЕ `<div id="dash-custom-range" ...>...</div>` (index.html:2278) и ПЕРЕД `<div id="dash-range-display" ...>`, вставить:

```html
  <!-- Фильтры (применяются и к плиткам, и к графику) -->
  <div class="flex items-center gap-2 mb-3 flex-wrap text-xs">
    <select id="dash-filter-project" onchange="_dashApplyFilters()" class="px-2 py-1 border border-gray-200 rounded-lg text-xs">
      <option value="">все проекты</option>
    </select>
    <select id="dash-filter-platform" onchange="_dashApplyFilters()" class="px-2 py-1 border border-gray-200 rounded-lg text-xs">
      <option value="">все платформы</option>
      <option value="instagram">Instagram</option>
      <option value="tiktok">TikTok</option>
      <option value="youtube">YouTube</option>
    </select>
    <input type="text" id="dash-filter-account" oninput="onDashFilterInput()" placeholder="аккаунт" class="px-2 py-1 border border-gray-200 rounded-lg text-xs w-32">
    <input type="text" id="dash-filter-pack" oninput="onDashFilterInput()" placeholder="пак" class="px-2 py-1 border border-gray-200 rounded-lg text-xs w-28">
    <button onclick="resetDashFilters()" class="px-3 py-1 border border-gray-200 text-gray-500 rounded-lg hover:bg-gray-50">Сбросить</button>
  </div>
```

- [ ] **Step 3: Добавить карточку графика**

Сразу ПОСЛЕ закрывающего `</div>` блока «По платформам» (index.html:2296, перед закрытием `#section-publishing-dashboard`), вставить:

```html
  <!-- График success rate в динамике -->
  <div id="dash-chart-card" class="bg-white rounded-xl border border-gray-200 p-4 mt-3">
    <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
      <div class="text-xs font-semibold text-gray-400 uppercase">Success rate в динамике</div>
      <label class="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
        <input type="checkbox" id="dash-labels-toggle" checked onchange="renderDashboardChart(_dashLastSeries)" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500">
        Значения на графике
      </label>
    </div>
    <div class="relative" style="height:320px">
      <canvas id="dash-chart"></canvas>
      <div id="dash-chart-empty" class="hidden absolute inset-0 flex items-center justify-center text-sm text-gray-400">Нет данных за период</div>
    </div>
  </div>
```

- [ ] **Step 4: Smoke — структура отрисовалась**

Открыть `#farming/publishing-dashboard`: видны кнопки «Вчера»/«Последние 3 дня» (у последней — нативная подсказка при наведении), строка фильтров, пустая карточка графика. (JS-проводки ещё нет — фильтры/график оживут в Task 10–11.)

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(dashboard): HTML — presets, filters row, chart card (WP #90)"
```

---

## Task 10: Frontend — JS-стейт, метки диапазона, URL-restore, загрузка проектов

**Files:**
- Modify: `public/index.html` (JS-блок дашборда ~11533; URL-restore ~4018)

- [ ] **Step 1: Расширить стейт и метки диапазона**

В блоке `// ===== Publishing Dashboard state =====` (после `let _dashCustomTo = null;`, index.html:11536) добавить:

```js
let _dashFilters = { project: '', platform: '', account_username: '', pack_name: '' };
let _dashLastSeries = null;
let _dashChart = null;
let _dashFilterDebounce = null;

const DASH_SERIES_META = [
  ['all',       'Все',       '#6366f1'],
  ['instagram', 'Instagram', '#ec4899'],
  ['tiktok',    'TikTok',    '#14b8a6'],
  ['youtube',   'YouTube',   '#ef4444'],
];
const DASH_LABELS_MAX = 24; // порог авто-скрытия меток (видимых точек суммарно)

function _dashEsc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}
```

Заменить `_fmtRangeDisplay` (index.html:11591-11596) — расширить карту пресетов:

```js
function _fmtRangeDisplay(range) {
  const fmt = ts => new Date(ts).toISOString().slice(0, 16).replace('T', ' ');
  const presetLabel = {today:'Сегодня', yesterday:'Вчера', last3:'Последние 3 дня', week:'Неделя', month:'Месяц', custom:'Свой диапазон'}[range.preset] || range.preset;
  return `${presetLabel}: ${fmt(range.from)} — ${fmt(range.to)} UTC`;
}
```

- [ ] **Step 2: Расширить whitelist пресетов в URL-restore**

В `index.html:4018` заменить:

```js
      if (['today','week','month','custom'].includes(preset)) {
```
на:
```js
      if (['today','yesterday','last3','week','month','custom'].includes(preset)) {
```

И в том же блоке (перед `switchDashboardPreset(_dashCurrentPreset);`, index.html:4030) добавить загрузку проектов в дропдаун:

```js
    loadDashProjects();
```

- [ ] **Step 3: Добавить загрузку списка проектов**

В JS-блок дашборда (например, после `_dashEsc`) добавить:

```js
async function loadDashProjects() {
  try {
    const r = await fetch('/api/publish/queue/projects', { credentials: 'same-origin' });
    if (!r.ok) return;
    const list = await r.json();
    const sel = document.getElementById('dash-filter-project');
    if (!sel) return;
    sel.innerHTML = '<option value="">все проекты</option>'
      + list.map(p => `<option value="${_dashEsc(p)}">${_dashEsc(p)}</option>`).join('');
    sel.value = _dashFilters.project;
  } catch (e) { /* дропдаун остаётся с «все проекты» */ }
}
```

- [ ] **Step 4: Smoke — пресеты и проекты**

Открыть дашборд: дропдаун «проект» наполнен; клик «Вчера»/«Последние 3 дня» подсвечивает кнопку, плитки обновляются (график пока пустой — рендер в Task 11), URL получает `sub=dash:yesterday`/`dash:last3`; перезагрузка страницы по такому URL восстанавливает пресет.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(dashboard): JS state, range labels, URL restore for new presets, projects dropdown (WP #90)"
```

---

## Task 11: Frontend — фильтры в запросе + рендер графика

**Files:**
- Modify: `public/index.html` (`loadPublishingDashboard` ~11598; +новые функции)

- [ ] **Step 1: Прокинуть фильтры в запрос и вызвать рендер графика**

В `loadPublishingDashboard` (index.html:11604-11624) после блока custom-параметров (после строки `}` закрывающей `if (_dashCurrentPreset === 'custom')`, index.html:11612) добавить:

```js
  if (_dashFilters.project)          params.set('project', _dashFilters.project);
  if (_dashFilters.platform)         params.set('platform', _dashFilters.platform);
  if (_dashFilters.account_username) params.set('account_username', _dashFilters.account_username);
  if (_dashFilters.pack_name)        params.set('pack_name', _dashFilters.pack_name);
```

И в блоке успешного ответа (после `renderDashboardPlatforms(data.by_platform);`, index.html:11624) добавить:

```js
    _dashLastSeries = data.series;
    renderDashboardChart(data.series);
```

- [ ] **Step 2: Добавить функции фильтров (после `applyDashboardCustom`, index.html:11675)**

```js
function _dashApplyFilters() {
  _dashFilters.project          = document.getElementById('dash-filter-project')?.value || '';
  _dashFilters.platform         = document.getElementById('dash-filter-platform')?.value || '';
  _dashFilters.account_username = (document.getElementById('dash-filter-account')?.value || '').trim();
  _dashFilters.pack_name        = (document.getElementById('dash-filter-pack')?.value || '').trim();
  loadPublishingDashboard();
}

function onDashFilterInput() {
  clearTimeout(_dashFilterDebounce);
  _dashFilterDebounce = setTimeout(_dashApplyFilters, 400);
}

function resetDashFilters() {
  _dashFilters = { project: '', platform: '', account_username: '', pack_name: '' };
  ['dash-filter-project','dash-filter-platform','dash-filter-account','dash-filter-pack']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  loadPublishingDashboard();
}
```

- [ ] **Step 3: Добавить рендер графика (после функций фильтров)**

```js
function _fmtBucketAxisLabel(label, unit) {
  if (unit === 'hour') return label.slice(11, 16);        // 'YYYY-MM-DD HH:MM' → 'HH:MM'
  const p = label.split('-');                              // 'YYYY-MM-DD' → 'DD.MM'
  return p[2] + '.' + p[1];
}

function renderDashboardChart(series) {
  const canvas = document.getElementById('dash-chart');
  const empty  = document.getElementById('dash-chart-empty');
  if (!canvas) return;

  if (!series || !Array.isArray(series.buckets) || series.buckets.length === 0) {
    if (_dashChart) { _dashChart.destroy(); _dashChart = null; }
    if (empty) empty.classList.remove('hidden');
    canvas.classList.add('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');
  canvas.classList.remove('hidden');

  const labels = series.buckets.map(b => _fmtBucketAxisLabel(b, series.unit));
  const datasets = DASH_SERIES_META.map(([key, label, color]) => {
    const points = series[key] || [];
    return {
      label,
      borderColor: color,
      backgroundColor: color,
      borderWidth: key === 'all' ? 3 : 2,
      pointRadius: 3,
      tension: 0.25,
      spanGaps: false,
      _points: points,                                     // {rate,done,denom}|null для тултипа
      data: points.map(p => (p ? Math.round(p.rate * 100) : null)),
    };
  });

  const totalPoints = datasets.reduce((n, ds) => n + ds.data.filter(v => v !== null).length, 0);
  const wantLabels = document.getElementById('dash-labels-toggle')?.checked ?? true;
  const showLabels = wantLabels && totalPoints <= DASH_LABELS_MAX;

  if (_dashChart) _dashChart.destroy();
  _dashChart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } },
      plugins: {
        legend: { position: 'top' },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const p = ctx.dataset._points && ctx.dataset._points[ctx.dataIndex];
              if (!p) return ctx.dataset.label + ': —';
              return `${ctx.dataset.label}: ${Math.round(p.rate * 100)}% (${p.done} из ${p.denom})`;
            },
          },
        },
        datalabels: {
          display: showLabels ? (ctx) => ctx.dataset.data[ctx.dataIndex] !== null : false,
          align: 'top',
          color: (ctx) => ctx.dataset.borderColor,
          font: { size: 9, weight: 'bold' },
          formatter: (v) => (v === null ? '' : v + '%'),
        },
      },
    },
    plugins: [window.ChartDataLabels].filter(Boolean),       // локальная регистрация — только этот график
  });
}
```

- [ ] **Step 4: Smoke — график живой**

Открыть дашборд (через изолированный dev-сервер или после деплоя в Task 12):
- «Неделя» → линия из 7 точек по дням, 4 линии (Все/IG/TT/YT), метки `%` видны, ось Y `0–100%`.
- «Сегодня»/«Вчера» → бакеты по часам.
- Наведение → тултип со всеми линиями `XX% (done из denom)`.
- Клик по легенде прячет линию. Месяц (много точек) → метки авто-скрылись; тумблер «Значения на графике» включает/выключает.
- Смена фильтра проект/платформа/аккаунт/пак → и плитки, и график пересчитываются; «Сбросить» очищает.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(dashboard): wire filters into request + render success-rate chart (WP #90)"
```

---

## Task 12: Деплой + финальная верификация на проде

**Files:** прод-чекаут `/root/.openclaw/workspace-genri/autowarm/`

- [ ] **Step 1: Полный прогон тестов в dev-worktree**

Run: `cd /home/claude-user/wt-wp90-impl && npm test 2>&1 | tail -8`
Expected: все тесты зелёные, без падений в соседних файлах.

- [ ] **Step 2: Хирургический деплой кода**

```bash
# сверить, что в прод-чекауте нет чужой WIP в этих файлах
git -C /root/.openclaw/workspace-genri/autowarm status --porcelain server.js public/index.html tests/test_publish_dashboard.test.js
# скопировать изменённые файлы из dev-worktree в прод
cp /home/claude-user/wt-wp90-impl/server.js /root/.openclaw/workspace-genri/autowarm/server.js
cp /home/claude-user/wt-wp90-impl/public/index.html /root/.openclaw/workspace-genri/autowarm/public/index.html
cp /home/claude-user/wt-wp90-impl/tests/test_publish_dashboard.test.js /root/.openclaw/workspace-genri/autowarm/tests/test_publish_dashboard.test.js
```
Expected: чисто; при чужой WIP — разрулить вручную до копирования.

- [ ] **Step 3: (опц.) выставить kill-switch и рестарт**

```bash
pm2 describe autowarm | grep "exec cwd"   # убедиться, что прод-путь, не testbench
# DASHBOARD_TIMESERIES_ENABLED не задаём — default on
pm2 restart autowarm
pm2 logs autowarm --lines 20 --nostream | grep -i "pub-dash\|error"
```
Expected: процесс поднялся без ошибок.

- [ ] **Step 4: Прод-верификация UI**

Открыть `https://delivery.contenthunter.ru/#farming/publishing-dashboard`:
- График рисуется (Все/IG/TT/YT), метки `%`, тултип `XX% (done из denom)`.
- Пресеты Сегодня/Вчера(часы) и Неделя/Месяц/Последние-3-дня/Custom(дни).
- Фильтры проект/платформа/аккаунт/пак меняют и плитки, и график; «Сбросить» работает.
- Открыть Фарминг/SLA/Токены — метки на тех графиках НЕ появились (anti-regression).
- Сверить точку графика с `SELECT ... GROUP BY day` по тому же периоду/фильтру.

- [ ] **Step 5: Commit (прод-чекаут — auto-push hook отправит в GitHub)**

```bash
git -C /root/.openclaw/workspace-genri/autowarm add server.js public/index.html tests/test_publish_dashboard.test.js
git -C /root/.openclaw/workspace-genri/autowarm commit -m "feat(dashboard): success-rate trend chart + filters + presets (WP #90)"
# auto-push hook → GenGo2/delivery-contenthunter (без force-push)
```

- [ ] **Step 6: Обновить OpenProject WP #90**

Комментарий (house-style, plain language) + статус → «Тестирование» (id 9) после прод-проверки. Удалить dev-worktree: `git -C /root/.openclaw/workspace-genri/autowarm worktree remove /home/claude-user/wt-wp90-impl`.

---

## Заметки по реализации

- **DRY:** фильтры переиспользуют те же SQL-фрагменты, что таблица «Запланировано»; `computeSuccessRate`/`mapDashboardRows`/`PUBLISH_QUEUE_FROM` не дублируются.
- **YAGNI:** URL-persist фильтров, auto-refresh, сравнение периодов, «Прочие платформы», drill-down, экспорт — вне scope (backlog в спеке §11).
- **TZ:** единственный источник MSK-логики — `MSK_OFFSET_MS`/`DAY_MS`; и `buildBucketAxis` (JS), и `date_trunc(... + interval '3 hours')` (SQL) дают MSK-метки одного формата.
- **Безопасность SQL:** `unit`/`truncFmt` строятся из whitelisted `pickBucketUnit` (только `'hour'|'day'`), не из пользовательского ввода; остальные значения — параметризованы.
- **Анти-регрессия меток:** datalabels гасится глобально (`Chart.defaults`), включается только локально (`plugins:[ChartDataLabels]`) на дашборде.
