# WP#239 — Единый переключатель типа даты для метрик дашборда: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Один UI-переключатель `date_basis` (planned|task, дефолт planned) когортирует оба набора метрик дашборда автовыкладки — плитки/тренд/success rate и воронку пайплайна — по выбранному типу даты; телеграм-отчёт показывает оба расчёта рядом.

**Architecture:** Параметр `date_basis` пробрасывается в эндпоинт `/api/publish-queue/dashboard` и в `computeFunnel`. Когорта-дата выбирается между `pq.scheduled_at` (task) и `COALESCE(s.slot_date, ut.slot_date)` (planned) через чистые helper-функции (тестируются строковыми ассертами). Серия под planned форсится дневной. Телеграм считает оба базиса и печатает два блока. Kill-switch отсутствует — откат это сам переключатель.

**Tech Stack:** Node.js (CommonJS), PostgreSQL (`pg` pool), тесты `node --test` + `node:assert/strict`. Фронтенд — ванильный JS в `public/index.html`. Код в репозитории **delivery-contenthunter** (autowarm).

**Спека:** `docs/superpowers/specs/2026-06-04-wp239-dashboard-date-basis-toggle-design.md`

> **Где код:** все правки `server.js`/`pipeline_funnel.js`/`daily_publish_report.js`/`public/index.html`/`tests/` — в рабочей копии delivery-contenthunter (на проде `/root/.openclaw/workspace-genri/autowarm`). Перед стартом исполнения завести отдельную ветку/worktree в delivery-contenthunter (skill `using-git-worktrees`) — НЕ редактировать прод-main напрямую. Команды тестов запускать из корня репозитория autowarm.

---

## File Structure

| Файл | Ответственность | Изменение |
|------|------------------|-----------|
| `pipeline_funnel.js` | Воронка пайплайна | Чистый `funnelWindowSql(basis, qKey)`; `computeFunnel` принимает `basis`+`range`; ветвление окна Q1–Q4 |
| `server.js` | Эндпоинт дашборда | Чистые `resolveDateBasis`, `pickBucketUnitForBasis`, `dashboardDateWindow`; константа `DASHBOARD_QUEUE_FROM`; проброс basis в tiles/series/funnel; `date_basis` в ответе |
| `daily_publish_report.js` | Ежедневный телеграм-отчёт | `buildReport` с basis; два блока в `formatMessage`; оба базиса в `runDailyReport` |
| `public/index.html` | Фронтенд дашборда | Переключатель базиса, проброс `date_basis`, URL-state |
| `tests/test_pipeline_funnel_pure.test.js` | Юнит-тесты воронки | Тесты `funnelWindowSql` |
| `tests/test_publish_dashboard.test.js` | Юнит-тесты дашборда | Тесты `resolveDateBasis`, `pickBucketUnitForBasis`, `dashboardDateWindow` |
| `tests/test_daily_publish_report.test.js` | Юнит-тесты отчёта | Тесты двухблочного `formatMessage`, basis в `buildReport` |

---

## Task 1: `resolveDateBasis` — нормализация параметра (server.js)

**Files:**
- Modify: `server.js` (рядом с `computeSuccessRate`, ~1896; экспорт в `module.exports`, ~9121)
- Test: `tests/test_publish_dashboard.test.js`

- [ ] **Step 1: Написать падающий тест**

В `tests/test_publish_dashboard.test.js` добавить в список импортов из `../server.js` имя `resolveDateBasis`, затем добавить блок:

```js
describe('resolveDateBasis — нормализация date_basis', () => {
  test('по умолчанию planned', () => {
    assert.equal(resolveDateBasis(undefined), 'planned');
    assert.equal(resolveDateBasis(''), 'planned');
    assert.equal(resolveDateBasis(null), 'planned');
  });
  test('task распознаётся', () => {
    assert.equal(resolveDateBasis('task'), 'task');
  });
  test('planned распознаётся', () => {
    assert.equal(resolveDateBasis('planned'), 'planned');
  });
  test('мусор → planned', () => {
    assert.equal(resolveDateBasis('garbage'), 'planned');
    assert.equal(resolveDateBasis('TASK '), 'task'); // trim + lower
  });
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_publish_dashboard.test.js`
Expected: FAIL — `resolveDateBasis is not a function` / `undefined`.

- [ ] **Step 3: Минимальная реализация**

В `server.js` сразу после функции `computeSuccessRate` (после строки `}` на ~1899) добавить:

```js
// WP#239 — нормализация date_basis для дашборда/отчёта.
// 'task' = когорта по pq.scheduled_at (дата задачи); 'planned' (дефолт) =
// когорта по COALESCE(slot_date, ut.slot_date) (запланированная дата слота).
function resolveDateBasis(raw) {
  const v = String(raw == null ? '' : raw).trim().toLowerCase();
  return v === 'task' ? 'task' : 'planned';
}
```

- [ ] **Step 4: Добавить в экспорты**

В блоке `module.exports.computeSuccessRate = computeSuccessRate;` (~9121) рядом добавить строку:

```js
  module.exports.resolveDateBasis = resolveDateBasis;
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_publish_dashboard.test.js`
Expected: PASS (новые 4 теста зелёные).

- [ ] **Step 6: Коммит**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(wp239): resolveDateBasis — нормализация date_basis (дефолт planned)"
```

---

## Task 2: `pickBucketUnitForBasis` — дневная серия под planned (server.js)

**Files:**
- Modify: `server.js` (после `pickBucketUnit`, ~1876; экспорт ~9121)
- Test: `tests/test_publish_dashboard.test.js`

- [ ] **Step 1: Написать падающий тест**

В импорт из `../server.js` добавить `pickBucketUnitForBasis`. Добавить блок:

```js
describe('pickBucketUnitForBasis — гранулярность серии по базису', () => {
  const dayRange = { from: new Date('2026-05-10T21:00:00Z'), to: new Date('2026-05-11T21:00:00Z') }; // 1 день
  const weekRange = { from: new Date('2026-05-10T21:00:00Z'), to: new Date('2026-05-17T21:00:00Z') }; // 7 дней
  test('task + однодневный диапазон → hour (как сейчас)', () => {
    assert.equal(pickBucketUnitForBasis(dayRange, 'task'), 'hour');
  });
  test('task + недельный диапазон → day', () => {
    assert.equal(pickBucketUnitForBasis(weekRange, 'task'), 'day');
  });
  test('planned всегда day (slot_date дневной), даже на одном дне', () => {
    assert.equal(pickBucketUnitForBasis(dayRange, 'planned'), 'day');
    assert.equal(pickBucketUnitForBasis(weekRange, 'planned'), 'day');
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_publish_dashboard.test.js`
Expected: FAIL — `pickBucketUnitForBasis is not a function`.

- [ ] **Step 3: Минимальная реализация**

В `server.js` сразу после `function pickBucketUnit(range) { ... }` (после ~1876) добавить:

```js
// WP#239 — под basis='planned' серия группируется по slot_date (дневной),
// поэтому часовые бакеты неприменимы → всегда 'day'. Под 'task' — прежняя логика.
function pickBucketUnitForBasis(range, basis) {
  return basis === 'planned' ? 'day' : pickBucketUnit(range);
}
```

- [ ] **Step 4: Добавить в экспорты**

Рядом с экспортом из Task 1:

```js
  module.exports.pickBucketUnitForBasis = pickBucketUnitForBasis;
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_publish_dashboard.test.js`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(wp239): pickBucketUnitForBasis — дневная серия под planned"
```

---

## Task 3: `dashboardDateWindow` — построение оконного предиката (server.js)

**Files:**
- Modify: `server.js` (после `pickBucketUnitForBasis`; экспорт ~9121)
- Test: `tests/test_publish_dashboard.test.js`

Helper возвращает `{ cond, params }` для плиток/тренда: placeholder'ы `$1`/`$2` заняты диапазоном, фильтры дашборда идут с `$3` (`buildDashboardFilters(query, 2)` — без изменений).

- [ ] **Step 1: Написать падающий тест**

В импорт добавить `dashboardDateWindow`. Добавить блок:

```js
describe('dashboardDateWindow — оконный предикат когорты по базису', () => {
  const range = { from: new Date('2026-05-10T21:00:00Z'), to: new Date('2026-05-11T21:00:00Z') };
  const slotBounds = { slotDateFrom: '2026-05-11', slotDateToExcl: '2026-05-12' };

  test('task: окно по pq.scheduled_at, params = [from, to]', () => {
    const w = dashboardDateWindow('task', range, slotBounds);
    assert.match(w.cond, /pq\.scheduled_at >= \$1/);
    assert.match(w.cond, /pq\.scheduled_at < \$2/);
    assert.deepEqual(w.params, [range.from, range.to]);
  });

  test('planned: окно по COALESCE(s.slot_date, ut.slot_date)::date, params = slot bounds', () => {
    const w = dashboardDateWindow('planned', range, slotBounds);
    assert.match(w.cond, /COALESCE\(s\.slot_date, ut\.slot_date\) >= \$1::date/);
    assert.match(w.cond, /COALESCE\(s\.slot_date, ut\.slot_date\) <  \$2::date/);
    assert.deepEqual(w.params, ['2026-05-11', '2026-05-12']);
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_publish_dashboard.test.js`
Expected: FAIL — `dashboardDateWindow is not a function`.

- [ ] **Step 3: Минимальная реализация**

В `server.js` сразу после `pickBucketUnitForBasis` добавить:

```js
// WP#239 — оконный предикат когорты для плиток/тренда дашборда.
// $1/$2 — границы; для 'task' это UTC-инстанты диапазона, для 'planned' —
// строки slot-дат [from, toExcl). Цепочка джойнов (ut, s) — в DASHBOARD_QUEUE_FROM.
function dashboardDateWindow(basis, range, slotBounds) {
  if (basis === 'task') {
    return {
      cond: 'pq.scheduled_at >= $1 AND pq.scheduled_at < $2',
      params: [range.from, range.to],
    };
  }
  return {
    cond: 'COALESCE(s.slot_date, ut.slot_date) >= $1::date AND COALESCE(s.slot_date, ut.slot_date) <  $2::date',
    params: [slotBounds.slotDateFrom, slotBounds.slotDateToExcl],
  };
}
```

- [ ] **Step 4: Добавить в экспорты**

```js
  module.exports.dashboardDateWindow = dashboardDateWindow;
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_publish_dashboard.test.js`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(wp239): dashboardDateWindow — оконный предикат когорты по basis"
```

---

## Task 4: `DASHBOARD_QUEUE_FROM` + проводка эндпоинта дашборда (server.js)

**Files:**
- Modify: `server.js` (`PUBLISH_QUEUE_FROM` ~1964; эндпоинт `/api/publish-queue/dashboard` ~2050-2160)

Цель: tiles и series используют новый FROM с джойном слота и оконный предикат по basis; серия — `pickBucketUnitForBasis`; в ответ добавлено `date_basis`. Воронка пробрасывает basis (полная реализация воронки — Task 6; здесь только проброс значения, дефолт planned не меняет текущее поведение).

- [ ] **Step 1: Добавить константу `DASHBOARD_QUEUE_FROM`**

Сразу после определения `const PUBLISH_QUEUE_FROM = \`FROM publish_queue pq ... \`;` (заканчивается ~1972) добавить:

```js
// WP#239 — расширение PUBLISH_QUEUE_FROM джойном слота для когорты по slot_date.
// LEFT JOIN на PK слота не даёт фан-аута → COUNT(*) не искажается; безопасно и для basis='task'.
const DASHBOARD_QUEUE_FROM = PUBLISH_QUEUE_FROM + `
      LEFT JOIN validator_schedule_slots s ON s.id = NULLIF(ut.meta->>'slot_id','')::int`;
```

- [ ] **Step 2: В обработчике эндпоинта вычислить basis и окно**

В `app.get('/api/publish-queue/dashboard', ...)` найти блок (около 2065):

```js
    // Фильтры: $1,$2 = диапазон, далее $3.. для project/platform/account/pack.
    const filt = buildDashboardFilters(req.query, 2);
    const whereSql = 'WHERE pq.scheduled_at >= $1 AND pq.scheduled_at < $2'
      + (filt.conds.length ? ' AND ' + filt.conds.join(' AND ') : '');
    const baseParams = [range.from, range.to, ...filt.params];
```

Заменить на:

```js
    // WP#239 — когорта по выбранному типу даты (planned=slot_date | task=scheduled_at).
    const dateBasis = resolveDateBasis(req.query.date_basis);
    const slotBounds = slotDateBoundsFromRange(range);
    const dateWin = dashboardDateWindow(dateBasis, range, slotBounds);
    // Фильтры: $1,$2 = окно когорты, далее $3.. для project/platform/account/pack.
    const filt = buildDashboardFilters(req.query, 2);
    const whereSql = 'WHERE ' + dateWin.cond
      + (filt.conds.length ? ' AND ' + filt.conds.join(' AND ') : '');
    const baseParams = [...dateWin.params, ...filt.params];
```

- [ ] **Step 3: tiles и series — использовать `DASHBOARD_QUEUE_FROM`**

В `tilesSql` заменить `${PUBLISH_QUEUE_FROM}` (~2077) на `${DASHBOARD_QUEUE_FROM}`.
В `seriesSql` заменить `${PUBLISH_QUEUE_FROM}` (~2096) на `${DASHBOARD_QUEUE_FROM}`.

- [ ] **Step 4: Серия — юнит по basis + дата-ось**

Найти в блоке серии (~2089):

```js
      const unit = pickBucketUnit(range);                 // 'hour' | 'day' (whitelisted by construction)
```

Заменить на:

```js
      const unit = pickBucketUnitForBasis(range, dateBasis); // planned→day; task→прежняя логика
```

Серийный SQL под basis='planned' должен бакетить по дате когорты, а не по `scheduled_at`. Найти в `seriesSql` (~2091) строку:

```js
            to_char(date_trunc('${unit}', pq.scheduled_at + interval '3 hours'), '${truncFmt}') AS bkt,
```

Заменить на (под planned бакет = сама дата слота, под task — прежнее по scheduled_at):

```js
            to_char(${dateBasis === 'planned'
              ? "COALESCE(s.slot_date, ut.slot_date)::timestamp"
              : "date_trunc('" + unit + "', pq.scheduled_at + interval '3 hours')"}, '${truncFmt}') AS bkt,
```

> Примечание: под planned `unit='day'`, `truncFmt='YYYY-MM-DD'`, ось `buildBucketAxis` шагает по дням — slot_date как `YYYY-MM-DD` совпадает с метками оси.

- [ ] **Step 5: Воронка — проброс basis (значение)**

Найти вызов `computeFunnel({ ... })` (~2121) и добавить в объект аргументов:

```js
        funnel = await computeFunnel({
          pool, slotDateFrom, slotDateToExcl,
          basis: dateBasis,              // WP#239
          range,                          // WP#239 — для окна по scheduled_at в режиме task
          filters: { /* без изменений */ },
        });
```

(`slotDateFrom`/`slotDateToExcl` уже извлекаются строкой выше; при дефолте planned поведение `computeFunnel` не изменится до Task 6.)

- [ ] **Step 6: Вернуть `date_basis` в ответе**

В объекте `res.json({ ... })` (~2148) добавить поле верхнего уровня:

```js
      date_basis: dateBasis,   // WP#239
      range: { /* без изменений */ },
```

- [ ] **Step 7: Прогнать весь набор дашборд-тестов + смок эндпоинта**

Run: `node --test --test-force-exit tests/test_publish_dashboard.test.js`
Expected: PASS (регрессий нет — pure-helpers).

Смок live (если доступна прод-БД локально), оба базиса:

```bash
curl -s 'http://127.0.0.1:3848/api/publish-queue/dashboard?preset=week' -H 'Cookie: <auth>' | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const j=JSON.parse(s);console.log("default basis:",j.date_basis, "overall:",j.overall);})'
curl -s 'http://127.0.0.1:3848/api/publish-queue/dashboard?preset=week&date_basis=task' -H 'Cookie: <auth>' | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{const j=JSON.parse(s);console.log("task basis:",j.date_basis, "overall:",j.overall);})'
```

Expected: первый ответ `date_basis: "planned"`, второй `"task"`; числа `overall` отличаются (разные когорты), оба эндпоинта 200.

- [ ] **Step 8: Коммит**

```bash
git add server.js
git commit -m "feat(wp239): дашборд — date_basis для плиток/тренда + DASHBOARD_QUEUE_FROM (slot join)"
```

---

## Task 5: `funnelWindowSql` — оконный предикат воронки по basis (pipeline_funnel.js)

**Files:**
- Modify: `pipeline_funnel.js` (новая функция + экспорт ~208)
- Test: `tests/test_pipeline_funnel_pure.test.js`

Под planned предикаты Q1–Q4 — как сейчас (по slot_date / planned_date). Под task — по `scheduled_at` строки очереди; строки/слоты без `scheduled_at` исключаются.

| qKey | planned | task |
|------|---------|------|
| `q1`,`q4` (publish_queue) | `COALESCE(s.slot_date, ut.slot_date)` | `pq.scheduled_at` |
| `q2` (manual queue) | `COALESCE(s.slot_date, m.planned_date)` | `EXISTS(...pq.scheduled_at в окне для той же публикации)` |
| `q3` (slots) | `s.slot_date` | `EXISTS(...pq.scheduled_at в окне для слота)` |

- [ ] **Step 1: Написать падающий тест**

В импорт `tests/test_pipeline_funnel_pure.test.js` добавить `funnelWindowSql`. Добавить:

```js
test('funnelWindowSql planned — даты слота для q1/q4', () => {
  const w = funnelWindowSql('planned', 'q1');
  assert.match(w, /COALESCE\(s\.slot_date, ut\.slot_date\) >= \$1::date/);
  assert.match(w, /COALESCE\(s\.slot_date, ut\.slot_date\) <  \$2::date/);
});

test('funnelWindowSql planned — q2 по planned_date, q3 по slot_date', () => {
  assert.match(funnelWindowSql('planned', 'q2'), /COALESCE\(s\.slot_date, m\.planned_date\) >= \$1::date/);
  assert.match(funnelWindowSql('planned', 'q3'), /s\.slot_date >= \$1::date/);
});

test('funnelWindowSql task — q1/q4 по scheduled_at', () => {
  const w = funnelWindowSql('task', 'q1');
  assert.match(w, /pq\.scheduled_at >= \$1/);
  assert.match(w, /pq\.scheduled_at <  \$2/);
  assert.doesNotMatch(w, /slot_date/);
});

test('funnelWindowSql task — q3 исключает слоты без scheduled_at (EXISTS pq в окне)', () => {
  const w = funnelWindowSql('task', 'q3');
  assert.match(w, /EXISTS/);
  assert.match(w, /pq2\.scheduled_at >= \$1/);
});

test('funnelWindowSql task — q2 исключает ручную без scheduled_at (EXISTS pq в окне)', () => {
  const w = funnelWindowSql('task', 'q2');
  assert.match(w, /EXISTS/);
  assert.match(w, /pq3\.scheduled_at >= \$1/);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_pipeline_funnel_pure.test.js`
Expected: FAIL — `funnelWindowSql is not a function`.

- [ ] **Step 3: Реализация**

В `pipeline_funnel.js` перед `async function computeFunnel(...)` (~96) добавить:

```js
// WP#239 — оконный предикат когорты воронки по типу даты.
// planned (дефолт): как WP#153 — по slot_date / planned_date.
// task: по pq.scheduled_at; строки/слоты без scheduled_at исключаются.
// $1/$2 — границы окна (planned: slot-даты 'YYYY-MM-DD'; task: UTC-инстанты диапазона).
function funnelWindowSql(basis, qKey) {
  if (basis === 'task') {
    switch (qKey) {
      case 'q1':
      case 'q4':
        return 'pq.scheduled_at >= $1 AND pq.scheduled_at <  $2';
      case 'q2':
        // Ручная очередь не имеет scheduled_at — берём только ту, у которой есть
        // строка publish_queue, исполнявшаяся в окне (исключаем проактив-ручную без очереди).
        return `EXISTS (
          SELECT 1 FROM publish_queue pq3
          WHERE pq3.unic_result_id = m.unic_result_id
            AND LOWER(pq3.account_username) = LOWER(m.account_username)
            AND LOWER(pq3.platform) = LOWER(m.platform)
            AND pq3.scheduled_at >= $1 AND pq3.scheduled_at <  $2)`;
      case 'q3':
        // Слот учитывается, только если у него есть строка очереди, исполнявшаяся в окне.
        return `EXISTS (
          SELECT 1 FROM publish_queue pq2
          LEFT JOIN unic_results ur2 ON ur2.id = pq2.unic_result_id
          LEFT JOIN unic_tasks ut2 ON ut2.id = COALESCE(pq2.unic_task_id, ur2.task_id)
          WHERE NULLIF(ut2.meta->>'slot_id','')::int = s.id
            AND pq2.scheduled_at >= $1 AND pq2.scheduled_at <  $2)`;
    }
  }
  // planned
  switch (qKey) {
    case 'q1':
    case 'q4':
      return 'COALESCE(s.slot_date, ut.slot_date) >= $1::date AND COALESCE(s.slot_date, ut.slot_date) <  $2::date';
    case 'q2':
      return 'COALESCE(s.slot_date, m.planned_date) >= $1::date AND COALESCE(s.slot_date, m.planned_date) <  $2::date';
    case 'q3':
      return 's.slot_date >= $1::date AND s.slot_date <  $2::date';
  }
  throw new Error('funnelWindowSql: unknown qKey ' + qKey);
}
```

- [ ] **Step 4: Экспорт**

В `module.exports = { ... }` (~208) добавить `funnelWindowSql`:

```js
module.exports = { assembleFunnel, slotDateBoundsFromRange, computeFunnel, funnelWindowSql, MSK_OFFSET_MS, round3 };
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_pipeline_funnel_pure.test.js`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add pipeline_funnel.js tests/test_pipeline_funnel_pure.test.js
git commit -m "feat(wp239): funnelWindowSql — оконный предикат воронки (planned|task)"
```

---

## Task 6: `computeFunnel` — ветвление по basis (pipeline_funnel.js)

**Files:**
- Modify: `pipeline_funnel.js` (`computeFunnel` ~96-206)
- Test: `tests/test_pipeline_funnel_pure.test.js` (проверка выбора params по basis)

`computeFunnel` принимает `basis` (дефолт 'planned') и `range`. Под task параметры окна = `[range.from, range.to]`, под planned = `[slotDateFrom, slotDateToExcl]`. Каждый Q использует `funnelWindowSql(basis, qKey)` вместо инлайн-предиката.

- [ ] **Step 1: Написать падающий тест выбора параметров окна**

Добавить чистый тест на helper выбора params (вынесем его, чтобы тестировать без БД). Сначала тест:

```js
const { funnelWindowParams } = require('../pipeline_funnel');

test('funnelWindowParams planned → slot-границы', () => {
  const p = funnelWindowParams('planned',
    { slotDateFrom: '2026-05-11', slotDateToExcl: '2026-05-12' },
    { from: new Date('2026-05-10T21:00:00Z'), to: new Date('2026-05-11T21:00:00Z') });
  assert.deepEqual(p, ['2026-05-11', '2026-05-12']);
});

test('funnelWindowParams task → инстанты диапазона', () => {
  const range = { from: new Date('2026-05-10T21:00:00Z'), to: new Date('2026-05-11T21:00:00Z') };
  const p = funnelWindowParams('task', { slotDateFrom: '2026-05-11', slotDateToExcl: '2026-05-12' }, range);
  assert.deepEqual(p, [range.from, range.to]);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_pipeline_funnel_pure.test.js`
Expected: FAIL — `funnelWindowParams is not a function`.

- [ ] **Step 3: Реализация `funnelWindowParams` + ветвление computeFunnel**

В `pipeline_funnel.js` рядом с `funnelWindowSql` добавить:

```js
// WP#239 — значения границ окна для подзапросов воронки по типу даты.
function funnelWindowParams(basis, bounds, range) {
  if (basis === 'task') {
    if (!range || !range.from || !range.to) throw new Error('funnelWindowParams: range required for basis=task');
    return [range.from, range.to];
  }
  return [bounds.slotDateFrom, bounds.slotDateToExcl];
}
```

Изменить сигнатуру `computeFunnel`:

```js
async function computeFunnel({ pool, slotDateFrom, slotDateToExcl, filters = {}, basis = 'planned', range = null }) {
  const bounds = { slotDateFrom, slotDateToExcl };
  const winParams = funnelWindowParams(basis, bounds, range);
```

Затем в КАЖДОМ из четырёх `pool.query(...)`:
1. Заменить инлайн-предикат `WHERE COALESCE(...) >= $1 AND ... < $2` на `WHERE ${funnelWindowSql(basis, '<qKey>')}` (qKey: q1, q2, q3, q4 соответственно).
2. Заменить хвост `[slotDateFrom, slotDateToExcl, ...fN.params]` на `[...winParams, ...fN.params]`.

Например, Q1 (около 99-128) — было:

```js
    WHERE COALESCE(s.slot_date, ut.slot_date) >= $1::date
      AND COALESCE(s.slot_date, ut.slot_date) <  $2::date
      ${f1.conds.length ? 'AND ' + f1.conds.join(' AND ') : ''}
  `, [slotDateFrom, slotDateToExcl, ...f1.params]);
```

Стало:

```js
    WHERE ${funnelWindowSql(basis, 'q1')}
      ${f1.conds.length ? 'AND ' + f1.conds.join(' AND ') : ''}
  `, [...winParams, ...f1.params]);
```

Аналогично Q2 (`'q2'`), Q3 (`'q3'`), Q4 (`'q4'`).

> Q4 содержит дополнительное условие `AND pq.status <> 'done' AND NOT EXISTS (...)` — оно остаётся, заменяется ТОЛЬКО строка с датами `COALESCE(...) >= $1 ... < $2` на `${funnelWindowSql(basis, 'q4')}`.
> Q3 уже содержит `AND s.status <> 'empty'` — оно остаётся, заменяется только дата-строка `s.slot_date >= $1 AND s.slot_date < $2` на `${funnelWindowSql(basis, 'q3')}`.

- [ ] **Step 4: Экспорт `funnelWindowParams`**

```js
module.exports = { assembleFunnel, slotDateBoundsFromRange, computeFunnel, funnelWindowSql, funnelWindowParams, MSK_OFFSET_MS, round3 };
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_pipeline_funnel_pure.test.js`
Expected: PASS. Также прогнать live-тест воронки, если БД доступна:
`node --test --test-force-exit tests/test_pipeline_funnel_live.test.js` (planned-ветка не должна регрессировать).

- [ ] **Step 6: Коммит**

```bash
git add pipeline_funnel.js tests/test_pipeline_funnel_pure.test.js
git commit -m "feat(wp239): computeFunnel — ветвление окна Q1-Q4 по basis (planned|task)"
```

---

## Task 7: `buildReport` с basis — per-platform SR по slot_date (daily_publish_report.js)

**Files:**
- Modify: `daily_publish_report.js` (`buildReport` ~64-95)
- Test: `tests/test_daily_publish_report.test.js`

`buildReport(pool, { startUtc, endUtc, basis })` — под `task` (дефолт) прежний SQL по `scheduled_at`; под `planned` — окно по `COALESCE(s.slot_date, ut.slot_date)` с джойном слота. Чистый helper `reportWindowSql(basis)` тестируем строково.

- [ ] **Step 1: Написать падающий тест**

В импорт из `../daily_publish_report.js` (`tests/test_daily_publish_report.test.js`) добавить `reportWindowSql`. Добавить:

```js
const { test } = require('node:test');
const assert = require('node:assert/strict');

test('reportWindowSql task — окно по scheduled_at без джойна слота', () => {
  const w = reportWindowSql('task');
  assert.match(w.where, /scheduled_at >= \$1 AND scheduled_at < \$2/);
  assert.equal(w.from, 'FROM publish_queue');
});

test('reportWindowSql planned — окно по slot_date с джойном слота', () => {
  const w = reportWindowSql('planned');
  assert.match(w.where, /COALESCE\(s\.slot_date, ut\.slot_date\) >= \$1::date/);
  assert.match(w.from, /validator_schedule_slots s/);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_daily_publish_report.test.js`
Expected: FAIL — `reportWindowSql is not a function`.

- [ ] **Step 3: Реализация `reportWindowSql` + параметризация `buildReport`**

В `daily_publish_report.js` перед `async function buildReport` добавить:

```js
// WP#239 — FROM+WHERE для per-platform SR по типу даты.
// task: окно по scheduled_at (как сейчас). planned: окно по slot_date слота
// с джойном publish_queue→unic_tasks→validator_schedule_slots.
// $1/$2 — границы (task: UTC-инстанты; planned: slot-даты 'YYYY-MM-DD').
function reportWindowSql(basis) {
  if (basis === 'planned') {
    return {
      from: `FROM publish_queue pq
        LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
        LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
        LEFT JOIN validator_schedule_slots s ON s.id = NULLIF(ut.meta->>'slot_id','')::int`,
      where: `COALESCE(s.slot_date, ut.slot_date) >= $1::date AND COALESCE(s.slot_date, ut.slot_date) < $2::date`,
      col: 'pq.',
    };
  }
  return { from: 'FROM publish_queue', where: 'scheduled_at >= $1 AND scheduled_at < $2', col: '' };
}
```

Переписать `buildReport`, чтобы принимать basis и собирать SQL из helper. Текущая сигнатура:

```js
async function buildReport(pool, { startUtc, endUtc }) {
  const { rows } = await pool.query(`
    SELECT LOWER(platform) AS platform,
      COUNT(*) FILTER (WHERE status='done')                            AS done,
      ...
    FROM publish_queue
    WHERE scheduled_at >= $1 AND scheduled_at < $2
      AND LOWER(platform) IN ('instagram','tiktok','youtube')
    GROUP BY LOWER(platform)
  `, [startUtc, endUtc]);
```

Заменить на (префикс `c` = `reportWindowSql.col`, под planned обращения к колонкам идут через `pq.`):

```js
async function buildReport(pool, { startUtc, endUtc, basis = 'task', winParams = null }) {
  const w = reportWindowSql(basis);
  const c = w.col;
  const params = winParams || [startUtc, endUtc];
  const { rows } = await pool.query(`
    SELECT LOWER(${c}platform) AS platform,
      COUNT(*) FILTER (WHERE ${c}status='done')                            AS done,
      COUNT(*) FILTER (WHERE ${c}status IN ('failed','past_slot_dropped')
                        OR (${c}status='cancelled' AND ${c}manual_handoff_at IS NOT NULL)) AS errors,
      COUNT(*) FILTER (WHERE ${c}status='past_slot_dropped')               AS dropped,
      COUNT(*) FILTER (WHERE ${c}status IN ('cancelled','skipped')
                        AND ${c}manual_handoff_at IS NULL)                 AS cancelled_skipped
    ${w.from}
    WHERE ${w.where}
      AND LOWER(${c}platform) IN ('instagram','tiktok','youtube')
    GROUP BY LOWER(${c}platform)
  `, params);
```

Остальная часть `buildReport` (сборка `perPlatform`/`overall`) — без изменений.

- [ ] **Step 4: Экспорт `reportWindowSql`**

В `module.exports` (~374) добавить `reportWindowSql`.

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_daily_publish_report.test.js`
Expected: PASS (включая существующие тесты buildReport, если есть — они используют дефолт basis='task').

- [ ] **Step 6: Коммит**

```bash
git add daily_publish_report.js tests/test_daily_publish_report.test.js
git commit -m "feat(wp239): buildReport с basis — per-platform SR по slot_date (planned)"
```

---

## Task 8: `formatMessage` — два блока (по дате задачи + по запланированной) (daily_publish_report.js)

**Files:**
- Modify: `daily_publish_report.js` (`formatMessage` ~189-235)
- Test: `tests/test_daily_publish_report.test.js`

Новая форма: `formatMessage` принимает структуру с двумя базисами. Минимально-инвазивно: вынести рендер одного базиса в helper `_renderBasisSection(report, funnel, { label })`, а `formatMessage` склеивает два раздела. Заголовок каждого раздела явно называет базис.

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_daily_publish_report.test.js`:

```js
const { formatMessage } = require('../daily_publish_report.js');

const REP = (rate) => ({
  perPlatform: {
    instagram: { done: 9, errors: 1, dropped: 0, cancelled_skipped: 0, rate },
    tiktok:    { done: 8, errors: 2, dropped: 0, cancelled_skipped: 0, rate: 0.8 },
    youtube:   { done: 0, errors: 0, dropped: 0, cancelled_skipped: 0, rate: null },
  },
  overall: { done: 17, errors: 3, rate },
  cancelledSkippedTotal: 0,
});

test('formatMessage — два блока: по запланированной и по дате задачи', () => {
  const msg = formatMessage({
    dateLabel: '04.06.2026',
    mentions: '',
    planned: { report: REP(0.9), funnel: { plan: 20, auto_published: 15, auto_acknowledged: 0,
      manual_published_total: 3, manual_handoff_published: 3, proactive_manual_published: 0,
      lost_count: 2, lost_pct: 0.1, manual_share_pct: 0.2, sr_total: 0.9 }, comments: {} },
    task:    { report: REP(0.85), funnel: { plan: 18, auto_published: 15, auto_acknowledged: 0,
      manual_published_total: 0, manual_handoff_published: 0, proactive_manual_published: 0,
      lost_count: 3, lost_pct: 0.166, manual_share_pct: 0, sr_total: 0.833 }, comments: {} },
  });
  assert.match(msg, /по запланированной дате/i);
  assert.match(msg, /по дате задачи/i);
  // оба итоговых SR присутствуют
  assert.match(msg, /90%/);
  assert.match(msg, /85%/);
});

test('formatMessage — пустые оба базиса → «публикаций не было»', () => {
  const empty = { perPlatform: { instagram:{done:0,errors:0,dropped:0,cancelled_skipped:0,rate:null},
    tiktok:{done:0,errors:0,dropped:0,cancelled_skipped:0,rate:null},
    youtube:{done:0,errors:0,dropped:0,cancelled_skipped:0,rate:null} },
    overall:{done:0,errors:0,rate:null}, cancelledSkippedTotal:0 };
  const msg = formatMessage({ dateLabel:'04.06.2026', mentions:'',
    planned:{ report: empty, funnel: null, comments:{} },
    task:{ report: empty, funnel: null, comments:{} } });
  assert.match(msg, /публикаций не было/i);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit tests/test_daily_publish_report.test.js`
Expected: FAIL — новый контракт `formatMessage` (ожидает `planned`/`task`) не выполнен старой сигнатурой.

- [ ] **Step 3: Рефактор `formatMessage` + helper**

Заменить текущую `function formatMessage(report, { dateLabel, mentions, comments = {}, funnel = null, snapshotMsk = null }) { ... }` на:

```js
// Рендер одного раздела (per-platform SR + причины + воронка) для конкретного базиса.
function _renderBasisSection(report, { funnel, comments = {}, basisLabel, snapshotMsk = null }) {
  const { perPlatform, overall, cancelledSkippedTotal } = report;
  const lines = [`——— <b>${basisLabel}</b> ———`];
  if (!overall || (overall.done + overall.errors) === 0) {
    lines.push('Авто-публикаций нет.');
    return lines;
  }
  lines.push(`Итого: <b>${_pct(overall.rate)}</b>  (${overall.done} из ${overall.done + overall.errors} опубликовано)`);
  for (const p of PLATFORMS) {
    const s = perPlatform[p];
    const label = PLATFORM_LABEL[p];
    if (s.rate === null) { lines.push(`▫️ ${label} — нет данных`); continue; }
    lines.push(`${_dot(s.rate)} ${label} — ${_pct(s.rate)}  (${s.done} опубл. / ${s.errors} ошибок)`);
  }
  if (cancelledSkippedTotal > 0) {
    lines.push(`ℹ️ Не учтены ${cancelledSkippedTotal} отменённых/пропущенных слотов.`);
  }
  const sub = PLATFORMS.filter(p => perPlatform[p].rate !== null && perPlatform[p].rate < GREEN);
  if (sub.length) {
    lines.push('', '<b>Причины ошибок</b>');
    for (const p of sub) {
      const c = comments[p];
      if (c) lines.push(`${_dot(perPlatform[p].rate)} <b>${PLATFORM_LABEL[p]}:</b> ${_esc(c)}`);
    }
  }
  if (funnel && funnel.plan > 0) {
    const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
    lines.push('', 'Воронка:');
    lines.push(`Запланировано: ${funnel.plan}`);
    lines.push(`Выложено авто: ${funnel.auto_published}${funnel.auto_acknowledged ? ` (+${funnel.auto_acknowledged} подтв. оператором)` : ''}`);
    lines.push(`Выложено вручную: ${funnel.manual_published_total} (реактив ${funnel.manual_handoff_published} + проактив ${funnel.proactive_manual_published})`);
    lines.push(`Потеряно: ${funnel.lost_count} (${pct(funnel.lost_pct)})`);
    lines.push(`Ручная выкладка: ${pct(funnel.manual_share_pct)} от авто-задач`);
    lines.push(`SR итоговый: ${pct(funnel.sr_total)}`);
  }
  return lines;
}

// WP#239 — два раздела: по запланированной дате (главный) и по дате задачи.
function formatMessage({ dateLabel, mentions, planned, task, snapshotMsk = null }) {
  const head = snapshotMsk ? `${dateLabel} (МСК, снимок ${snapshotMsk})` : `${dateLabel} (МСК)`;
  const lines = [`📊 <b>Авто-публикации за ${head}</b>`, ''];

  const plannedEmpty = !planned.report.overall || (planned.report.overall.done + planned.report.overall.errors) === 0;
  const taskEmpty = !task.report.overall || (task.report.overall.done + task.report.overall.errors) === 0;
  if (plannedEmpty && taskEmpty) {
    lines.push('За сутки авто-публикаций не было.');
    if (mentions) lines.push('', _esc(mentions));
    return lines.join('\n');
  }

  lines.push(..._renderBasisSection(planned.report, {
    funnel: planned.funnel, comments: planned.comments, basisLabel: 'По запланированной дате', snapshotMsk,
  }));
  lines.push('');
  lines.push(..._renderBasisSection(task.report, {
    funnel: task.funnel, comments: task.comments, basisLabel: 'По дате задачи', snapshotMsk,
  }));
  if (mentions) lines.push('', _esc(mentions));
  return lines.join('\n');
}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_daily_publish_report.test.js`
Expected: PASS. Старые тесты `formatMessage` со старой сигнатурой обновить под новый контракт (если падают) — см. Self-Review.

- [ ] **Step 5: Коммит**

```bash
git add daily_publish_report.js tests/test_daily_publish_report.test.js
git commit -m "feat(wp239): formatMessage — два раздела (запланированная + дата задачи)"
```

---

## Task 9: `runDailyReport` — считать оба базиса (daily_publish_report.js)

**Files:**
- Modify: `daily_publish_report.js` (`runDailyReport` ~277-345)

- [ ] **Step 1: Заменить расчёт report+funnel на два базиса**

Найти блок (около 305-330):

```js
  const report = await buildReport(pool, { startUtc, endUtc });

  let funnel = null;
  if (process.env.PIPELINE_FUNNEL_ENABLED !== '0') {
    try {
      const { slotDateFrom, slotDateToExcl } = slotDateBoundsFromRange({ from: startUtc, to: endUtc });
      funnel = await computeFunnel({ pool, slotDateFrom, slotDateToExcl, filters: {} });
    } catch (e) {
      console.warn('[daily-report] funnel skipped:', e.message);
    }
  }

  const comments = {};
  for (const p of PLATFORMS) {
    const s = report.perPlatform[p];
    if (s.rate !== null && s.rate < GREEN) {
      const breakdown = await buildErrorBreakdown(pool, { startUtc, endUtc, platform: p });
      comments[p] = await summarizeProblems(p, breakdown, llmOpts);
    }
  }
```

Заменить на:

```js
  const range = { from: startUtc, to: endUtc };
  const { slotDateFrom, slotDateToExcl } = slotDateBoundsFromRange(range);

  // WP#239 — оба базиса: planned (главный) и task.
  const plannedReport = await buildReport(pool, { startUtc, endUtc, basis: 'planned', winParams: [slotDateFrom, slotDateToExcl] });
  const taskReport = await buildReport(pool, { startUtc, endUtc, basis: 'task' });

  const funnelFor = async (basis) => {
    if (process.env.PIPELINE_FUNNEL_ENABLED === '0') return null;
    try {
      return await computeFunnel({ pool, slotDateFrom, slotDateToExcl, basis, range, filters: {} });
    } catch (e) { console.warn(`[daily-report] funnel(${basis}) skipped:`, e.message); return null; }
  };
  const plannedFunnel = await funnelFor('planned');
  const taskFunnel = await funnelFor('task');

  // Причины ошибок считаем по дате задачи (операционный угол) — для обоих разделов один источник.
  const comments = {};
  for (const p of PLATFORMS) {
    const s = taskReport.perPlatform[p];
    if (s.rate !== null && s.rate < GREEN) {
      const breakdown = await buildErrorBreakdown(pool, { startUtc, endUtc, platform: p });
      comments[p] = await summarizeProblems(p, breakdown, llmOpts);
    }
  }
```

- [ ] **Step 2: Обновить вызов `formatMessage`**

Найти:

```js
  const snapshotMsk = new Date().toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit' });
  const text = formatMessage(report, { dateLabel, mentions, comments, funnel, snapshotMsk });
```

Заменить на:

```js
  const snapshotMsk = new Date().toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit' });
  const text = formatMessage({
    dateLabel, mentions, snapshotMsk,
    planned: { report: plannedReport, funnel: plannedFunnel, comments },
    task:    { report: taskReport,    funnel: taskFunnel,    comments },
  });
```

- [ ] **Step 3: Прогон + dry-run**

Run: `node --test --test-force-exit tests/test_daily_publish_report.test.js`
Expected: PASS.

Dry-run (печатает сообщение без отправки; нужна доступная БД):

```bash
node daily_publish_report.js --dry-run
```

Expected: в выводе два раздела — «По запланированной дате» и «По дате задачи», каждый со своим «SR итоговый».

- [ ] **Step 4: Коммит**

```bash
git add daily_publish_report.js
git commit -m "feat(wp239): runDailyReport — считать и печатать оба базиса"
```

---

## Task 10: Фронтенд — переключатель базиса даты (public/index.html)

**Files:**
- Modify: `public/index.html` (HTML кнопки ~2380-2390; JS state/fetch/switch ~12200-12475)

Состояние `_dashDateBasis` (дефолт `'planned'`), сегмент-переключатель рядом с пресетами, проброс в `loadPublishingDashboard`, восстановление из URL-state.

- [ ] **Step 1: Добавить HTML-переключатель**

В блоке кнопок дашборда (после строки с кнопкой `custom`, перед кнопкой «🔄 Обновить», ~2387) добавить:

```html
      <span class="mx-1 w-px h-5 bg-gray-200"></span>
      <button data-basis="planned" onclick="switchDashboardBasis('planned')" title="Когорта по дате слота из плана"
        class="dash-basis-btn px-3 py-1.5 text-xs font-semibold rounded-lg border bg-indigo-50 text-indigo-700 border-indigo-200">Запланировано</button>
      <button data-basis="task" onclick="switchDashboardBasis('task')" title="Когорта по дате исполнения публикации"
        class="dash-basis-btn px-3 py-1.5 text-xs font-semibold rounded-lg border bg-white text-gray-600 border-gray-200 hover:bg-gray-50">Дата задачи</button>
```

- [ ] **Step 2: Объявить состояние**

Рядом с объявлением `_dashCurrentPreset` (найти `let _dashCurrentPreset` около 4205-4212 / в зоне dash-state) добавить:

```js
let _dashDateBasis = 'planned';   // WP#239 — тип даты когорты дашборда
```

- [ ] **Step 3: Прокинуть параметр в запрос**

В `loadPublishingDashboard` после `const params = new URLSearchParams({ preset: _dashCurrentPreset });` (~12410) добавить:

```js
  params.set('date_basis', _dashDateBasis);   // WP#239
```

- [ ] **Step 4: Добавить `switchDashboardBasis`**

Рядом с `function switchDashboardPreset(preset) {` (~12447) добавить функцию:

```js
function switchDashboardBasis(basis) {
  _dashDateBasis = (basis === 'task') ? 'task' : 'planned';
  document.querySelectorAll('.dash-basis-btn').forEach(btn => {
    const isActive = btn.dataset.basis === _dashDateBasis;
    btn.className = 'dash-basis-btn px-3 py-1.5 text-xs font-semibold rounded-lg border ' +
      (isActive
        ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
        : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50');
  });
  loadPublishingDashboard();
}
```

- [ ] **Step 5: Ручная проверка в браузере**

Открыть раздел «📊 Дашборд выкладки», переключить «Запланировано» ↔ «Дата задача»:
- Подсветка активной кнопки переключается.
- Запрос уходит с `date_basis=...` (DevTools → Network).
- Числа плиток/тренда/воронки меняются между базисами.
- Дефолт при загрузке страницы — «Запланировано».

- [ ] **Step 6: Коммит**

```bash
git add public/index.html
git commit -m "feat(wp239): фронтенд — переключатель типа даты дашборда (planned|task)"
```

---

## Task 11: Полный прогон тестов и финальная верификация

**Files:** —

- [ ] **Step 1: Прогнать все тесты репозитория**

Run: `node --test --test-force-exit tests/*.test.js`
Expected: все зелёные; live-тесты, требующие БД, либо проходят (если БД доступна), либо явно скипаются — зафиксировать какие.

> ⚠️ По заметке проекта полный `pytest tests/` для python-части может зависать — здесь речь только о node-тестах autowarm (`tests/*.test.js`). Python-тесты не затрагиваются этой задачей.

- [ ] **Step 2: Dry-run телеграм-отчёта (если БД доступна)**

Run: `node daily_publish_report.js --dry-run`
Expected: два раздела с разными SR; сообщение валидно (HTML-теги сбалансированы).

- [ ] **Step 3: Смок обоих базисов на эндпоинте**

Повторить curl-смок из Task 4 Step 7 — `date_basis` в ответе соответствует запросу, числа различаются.

- [ ] **Step 4: Финальный коммит (если остались несохранённые правки)**

```bash
git add -A && git commit -m "test(wp239): полный прогон node-тестов + верификация обоих базисов" || echo "nothing to commit"
```

---

## Self-Review

**1. Spec coverage:**
- §«Базис даты» (planned дефолт, task) → Task 1 (`resolveDateBasis`), Task 4 (wiring).
- §«Backend дашборд» (джойн слота, ветвление когорты, дневная серия, `date_basis` в ответе) → Task 2, 3, 4.
- §«Backend воронка» (basis, исключение строк без scheduled_at) → Task 5, 6.
- §«Frontend переключатель» → Task 10.
- §«Telegram оба расчёта рядом» → Task 7, 8, 9.
- §«Без kill-switch» → нигде не вводится env-флаг; ✓.
- §«Тестирование (TDD)» → тесты в каждой задаче + Task 11.

**2. Placeholder scan:** код приведён в каждом шаге; SQL-фрагменты полные; нет «add validation/error handling» без кода. ✓

**3. Type consistency:**
- `resolveDateBasis`, `pickBucketUnitForBasis`, `dashboardDateWindow` — server.js; вызовы в Task 4 совпадают по именам.
- `funnelWindowSql(basis, qKey)` / `funnelWindowParams(basis, bounds, range)` — pipeline_funnel.js; computeFunnel в Task 6 и вызовы в server.js (Task 4) / daily_report (Task 9) передают `basis` + `range`. ✓
- `reportWindowSql(basis)` → `{from, where, col}`; `buildReport` использует `w.col`/`w.from`/`w.where`. ✓
- `formatMessage({ dateLabel, mentions, planned, task, snapshotMsk })` — новый контракт; вызов в Task 9 Step 2 совпадает. ⚠️ **Существующие тесты `formatMessage` со старой сигнатурой `formatMessage(report, {...})` сломаются** — в Task 8 Step 4 их нужно переписать на новый контракт (обернуть report в `{ planned:{report,funnel,comments}, task:{...} }`). Зафиксировано как явный шаг.

**Замечание по интеграции:** computeFunnel под basis='task' и buildReport под обоими базисами надёжно проверяются только на живой БД (live-тесты). Pure-helpers покрыты юнит-тестами; интеграционная корректность — через dry-run отчёта и curl-смок дашборда (Task 4/9/11). Если локальная БД недоступна на этапе исполнения — пометить интеграционные шаги как отложенную верификацию на стейджинге/проде.
