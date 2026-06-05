# Дашборд выкладки: пояс, «на сейчас», факт-время часового ряда — План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать так, чтобы график автовыкладки совпадал с текущим временем МСК (часовой ряд — по факту выкладки), и явно показать пояс отображения и «по состоянию на сейчас».

**Architecture:** Три изолированных изменения в `delivery-contenthunter`: (C) в почасовом режиме `basis=task` бакетить ряд по `COALESCE(pq.updated_at, pq.scheduled_at)` вместо `scheduled_at`, за kill-switch `DASHBOARD_SERIES_ACTUAL_TIME_ENABLED` (дефолт ON); (A) добавить в ответ dashboard пояс/смещение/`as_of` и отрисовать метку; (B) отрисовать вертикальный маркер «сейчас» и сноску про текущий незавершённый час. Когорта и дневной режим не меняются.

**Tech Stack:** Node.js + Express (`server.js`), Postgres, ванильный фронт (`public/index.html`) + Chart.js (без annotation-плагина), тесты — `node:test` (`node --test`).

**Спека:** `docs/superpowers/specs/2026-06-05-dashboard-tz-asof-design.md` (в docs-репо `rmbrmv/contenthunter`).

---

## Контекст для исполнителя (важно)

- **Код живёт в репо `delivery-contenthunter`** (origin `github.com/GenGo2/delivery-contenthunter`), НЕ в текущем docs-репо. Свежий локальный чекаут с этим origin: `~/op255-ig-metaverified` (ветка другая — сделать новую от `origin/main`).
- Дашборд-эндпоинт: `server.js` → `GET /api/publish-queue/dashboard` (около строк 2063–2199).
- Помощники пояса: `tz_display.js` (экспортирует `tzClause`, `tzOffsetMs`, `instantToYmd`, `hourLabelInTz`, `safeTz`).
- Хелперы дашборда экспортируются для юнит-тестов под `process.env.TEST_MODE='1'` (см. `server.js` ~строка 9150+).
- Тест-раннер: `node --test test_*.test.js` из корня репо. Тесты подключают `server.js` с `TEST_MODE=1` и фиктивным `DATABASE_URL` (БД не дёргается для pure-хелперов).
- Конвенция kill-switch «дефолт ON»: `process.env.FLAG !== '0'` (как `isDashboardTimeseriesEnabled`).
- **Деплой:** `server.js` — это pm2-процесс **id 35**; после правок нужен `sudo pm2 restart 35` на проде (в отличие от publisher, который per-task spawn). `public/index.html` отдаётся статикой тем же процессом.

---

## Файловая структура

| Файл | Что меняется |
|------|--------------|
| `tz_display.js` | + `tzLabel(instantMs, name)` ('UTC+3'); + `hourBucketLabelInTz(instantMs, name)` ('YYYY-MM-DD HH:00') |
| `server.js` | + `isSeriesActualTimeEnabled()`; + `seriesBucketExpr(basis, unit, dtz)`; + `buildDisplayTzMeta(nowMs, dtz)`; + `currentHourBucketLabel(nowMs, dtz, unit)`; правка эндпоинта (использовать хелперы, добавить поля в ответ); экспорт под TEST_MODE |
| `public/index.html` | + элемент `#dash-tz-note` и `#dash-hour-note`; функция `_renderDashTzNote(data)`; инлайн Chart.js плагин `nowMarkerPlugin`; правка `renderDashboardChart` и `loadPublishDashboard` |
| `test_dashboard_tz_asof.test.js` (новый) | юнит-тесты `tzLabel`, `hourBucketLabelInTz`, `seriesBucketExpr` (ON/OFF/planned), `buildDisplayTzMeta`, `currentHourBucketLabel` |

---

## Task 0: Изолированная ветка в delivery-contenthunter

**Files:** (рабочее дерево)

- [ ] **Step 1: Создать ветку от свежего main**

```bash
cd ~/op255-ig-metaverified
git fetch origin main
git worktree add -b dashboard-tz-asof-2026-06-05 ~/dashboard-tz-asof origin/main
cd ~/dashboard-tz-asof
git log --oneline -1
```

Expected: рабочее дерево `~/dashboard-tz-asof` на новой ветке от `origin/main`. Все дальнейшие шаги выполняются в `~/dashboard-tz-asof`.

- [ ] **Step 2: Прогнать существующие dashboard/tz-тесты (baseline зелёный)**

Run: `cd ~/dashboard-tz-asof && node --test test_wp221_dashboard_tz.test.js test_wp247_dashboard_window.test.js test_tz_display.test.js`
Expected: PASS (фиксируем исходное зелёное состояние).

---

## Task 1: `tz_display.js` — `tzLabel` и `hourBucketLabelInTz`

**Files:**
- Modify: `tz_display.js` (добавить 2 функции + экспорт)
- Test: `test_dashboard_tz_asof.test.js` (создать)

- [ ] **Step 1: Написать падающий тест**

Создать `test_dashboard_tz_asof.test.js`:

```js
'use strict';
// План 2026-06-05: пояс/факт-время дашборда.
// Run: node --test test_dashboard_tz_asof.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const tzd = require('./tz_display');

const MS = Date.UTC(2026, 5, 5, 10, 30, 0); // 2026-06-05 10:30Z = 13:30 МСК

test('tzLabel: целые и дробные смещения', () => {
  assert.equal(tzd.tzLabel(MS, 'Europe/Moscow'), 'UTC+3');
  assert.equal(tzd.tzLabel(MS, 'Asia/Yekaterinburg'), 'UTC+5');
  assert.equal(tzd.tzLabel(MS, 'Asia/Kolkata'), 'UTC+5:30');
  assert.equal(tzd.tzLabel(MS, 'America/New_York'), 'UTC-4'); // лето, EDT
});

test('hourBucketLabelInTz: усечение до часа в поясе', () => {
  assert.equal(tzd.hourBucketLabelInTz(MS, 'Europe/Moscow'), '2026-06-05 13:00');
  assert.equal(tzd.hourBucketLabelInTz(MS, 'Asia/Yekaterinburg'), '2026-06-05 15:00');
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test test_dashboard_tz_asof.test.js`
Expected: FAIL — `tzd.tzLabel is not a function`.

- [ ] **Step 3: Реализовать функции в `tz_display.js`**

Вставить перед `module.exports` (после `hourLabelInTz`):

```js
// Человекочитаемое смещение пояса для инстанта: 'UTC+3', 'UTC+5:30', 'UTC-4'.
function tzLabel(instantMs, name) {
  const offMin = Math.round(tzOffsetMs(instantMs, safeTz(name)) / 60000);
  const sign = offMin >= 0 ? '+' : '-';
  const abs = Math.abs(offMin);
  const h = Math.floor(abs / 60);
  const m = abs % 60;
  return `UTC${sign}${h}${m ? ':' + String(m).padStart(2, '0') : ''}`;
}

// Метка ЧАСОВОГО бакета инстанта в поясе: 'YYYY-MM-DD HH:00'
// (совпадает с hour-aligned метками buildBucketAxis).
function hourBucketLabelInTz(instantMs, name) {
  const TZ = safeTz(name);
  const ymd = instantToYmd(instantMs, TZ);
  const hh = new Intl.DateTimeFormat('en-GB', {
    timeZone: TZ, hour: '2-digit', hourCycle: 'h23',
  }).format(new Date(instantMs));
  return `${ymd} ${hh}:00`;
}
```

Обновить `module.exports` — добавить `tzLabel, hourBucketLabelInTz`:

```js
module.exports = { DEFAULT_TZ, isValidTz, safeTz, naiveTzClause, tzClause,
                   tzOffsetMs, instantToYmd, startOfDayUtcMs, hourLabelInTz,
                   tzLabel, hourBucketLabelInTz };
```

- [ ] **Step 4: Запустить тест — PASS**

Run: `node --test test_dashboard_tz_asof.test.js`
Expected: PASS (оба теста).

- [ ] **Step 5: Коммит**

```bash
git add tz_display.js test_dashboard_tz_asof.test.js
git commit -m "feat(tz): tzLabel + hourBucketLabelInTz для метки пояса и маркера 'сейчас'"
```

---

## Task 2: `server.js` — `seriesBucketExpr` + kill-switch (пункт C)

**Files:**
- Modify: `server.js` — добавить хелперы (рядом с `pickBucketUnitForBasis`, ~строка 1870), заменить inline `bktExpr` (строки 2120–2122), экспорт под TEST_MODE (~строка 9162)
- Test: `test_dashboard_tz_asof.test.js`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `test_dashboard_tz_asof.test.js`:

```js
process.env.TEST_MODE = '1';
process.env.DATABASE_URL = 'postgresql://openclaw:openclaw123@localhost/openclaw';
const srv = require('./server');

test('seriesBucketExpr: planned — по дате слота, без времени', () => {
  assert.match(srv.seriesBucketExpr('planned', 'day', 'Europe/Moscow'),
    /COALESCE\(s\.slot_date, ut\.slot_date\)::timestamp/);
});

test('seriesBucketExpr: task + флаг ON (дефолт) — по факту updated_at', () => {
  delete process.env.DASHBOARD_SERIES_ACTUAL_TIME_ENABLED;
  const e = srv.seriesBucketExpr('task', 'hour', 'Europe/Moscow');
  assert.match(e, /COALESCE\(pq\.updated_at, pq\.scheduled_at\)/);
  assert.match(e, /AT TIME ZONE 'Europe\/Moscow'/);
  assert.match(e, /date_trunc\('hour'/);
});

test('seriesBucketExpr: task + флаг OFF — по плану scheduled_at', () => {
  process.env.DASHBOARD_SERIES_ACTUAL_TIME_ENABLED = '0';
  const e = srv.seriesBucketExpr('task', 'hour', 'Europe/Moscow');
  assert.match(e, /pq\.scheduled_at AT TIME ZONE/);
  assert.doesNotMatch(e, /updated_at/);
  delete process.env.DASHBOARD_SERIES_ACTUAL_TIME_ENABLED;
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test test_dashboard_tz_asof.test.js`
Expected: FAIL — `srv.seriesBucketExpr is not a function`.

- [ ] **Step 3: Добавить хелперы в `server.js`**

Вставить сразу после функции `pickBucketUnitForBasis` (после строки ~1870):

```js
// План 2026-06-05 — kill-switch: почасовой ряд по фактическому времени выкладки
// (updated_at). Дефолт ON; OFF (='0') → прежнее поведение по scheduled_at.
function isSeriesActualTimeEnabled() {
  return process.env.DASHBOARD_SERIES_ACTUAL_TIME_ENABLED !== '0';
}

// Выражение бакета для ряда дашборда.
// planned → дата слота (дневной ряд); task → час/день по времени.
// При isSeriesActualTimeEnabled() task бакетится по факту выкладки
// COALESCE(updated_at, scheduled_at) (момент перехода в терминальный статус,
// тот же прокси, что lifecycle.js), иначе по плану scheduled_at.
function seriesBucketExpr(dateBasis, unit, dtz) {
  if (dateBasis === 'planned') return 'COALESCE(s.slot_date, ut.slot_date)::timestamp';
  const timeCol = isSeriesActualTimeEnabled()
    ? 'COALESCE(pq.updated_at, pq.scheduled_at)'
    : 'pq.scheduled_at';
  return `date_trunc('${unit}', ${timeCol} ${tzd.tzClause(dtz)})`;
}
```

- [ ] **Step 4: Заменить inline `bktExpr` в эндпоинте**

В `server.js` найти (строки ~2116–2122):

```js
      // WP#239 — slot_date это DATE; planned бакетит по самой дате слота (::timestamp,
      // формат YYYY-MM-DD совпадает с дневной осью buildBucketAxis), task — по часу/дню scheduled_at.
      // WP#247 Фаза 2 — task-ветка: scheduled_at теперь timestamptz, конвертация в пояс через tzClause.
      // При dtz=МСК tzClause даёт `AT TIME ZONE 'Europe/Moscow'` (одинарный, без UTC-префикса).
      const bktExpr = dateBasis === 'planned'
        ? 'COALESCE(s.slot_date, ut.slot_date)::timestamp'
        : `date_trunc('${unit}', pq.scheduled_at ${tzd.tzClause(dtz)})`;
```

Заменить на:

```js
      // План 2026-06-05 — выражение бакета вынесено в seriesBucketExpr.
      // task-ветка (почасовой) бакетится по факту выкладки (updated_at) за kill-switch
      // DASHBOARD_SERIES_ACTUAL_TIME_ENABLED; planned — по дате слота (дневной).
      const bktExpr = seriesBucketExpr(dateBasis, unit, dtz);
```

- [ ] **Step 5: Экспортировать хелперы под TEST_MODE**

В блоке `if (process.env.TEST_MODE)` (рядом с `module.exports.buildBucketAxis`, ~строка 9162) добавить:

```js
  module.exports.isSeriesActualTimeEnabled = isSeriesActualTimeEnabled;
  module.exports.seriesBucketExpr = seriesBucketExpr;
```

- [ ] **Step 6: Запустить тест — PASS**

Run: `node --test test_dashboard_tz_asof.test.js`
Expected: PASS (все тесты, включая Task 1).

- [ ] **Step 7: Регрессия dashboard/tz**

Run: `node --test test_wp221_dashboard_tz.test.js test_wp247_dashboard_window.test.js test_wp247_funnel_report_tz.test.js test_tz_display.test.js`
Expected: PASS (без изменений).

- [ ] **Step 8: Коммит**

```bash
git add server.js test_dashboard_tz_asof.test.js
git commit -m "feat(dashboard): часовой ряд по факту выкладки (updated_at) за kill-switch DASHBOARD_SERIES_ACTUAL_TIME_ENABLED"
```

---

## Task 3: `server.js` — мета пояса/`as_of` + `current_bucket` (пункты A, B бэкенд)

**Files:**
- Modify: `server.js` — хелперы (после `seriesBucketExpr`), правка эндпоинта (захват `nowMs`, поля ответа, `series.current_bucket`), экспорт
- Test: `test_dashboard_tz_asof.test.js`

- [ ] **Step 1: Дописать падающий тест**

Добавить в `test_dashboard_tz_asof.test.js`:

```js
test('buildDisplayTzMeta: пояс, смещение, as_of', () => {
  const meta = srv.buildDisplayTzMeta(MS, 'Europe/Moscow');
  assert.equal(meta.display_tz, 'Europe/Moscow');
  assert.equal(meta.display_tz_label, 'UTC+3');
  assert.equal(meta.as_of, '2026-06-05 13:30');
});

test('currentHourBucketLabel: только для часового режима', () => {
  assert.equal(srv.currentHourBucketLabel(MS, 'Europe/Moscow', 'hour'), '2026-06-05 13:00');
  assert.equal(srv.currentHourBucketLabel(MS, 'Europe/Moscow', 'day'), null);
});
```

(`MS` уже объявлен в Task 1; переменная переиспользуется.)

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test test_dashboard_tz_asof.test.js`
Expected: FAIL — `srv.buildDisplayTzMeta is not a function`.

- [ ] **Step 3: Добавить хелперы в `server.js`**

Сразу после `seriesBucketExpr` (из Task 2):

```js
// План 2026-06-05 — мета пояса отображения для дашборда (пункт A).
function buildDisplayTzMeta(nowMs, dtz) {
  return {
    display_tz: dtz,
    display_tz_label: tzd.tzLabel(nowMs, dtz),
    as_of: tzd.hourLabelInTz(nowMs, dtz),   // 'YYYY-MM-DD HH:MM' в поясе отображения
  };
}

// Метка текущего часового бакета (для маркера «сейчас», пункт B);
// null если ряд не часовой.
function currentHourBucketLabel(nowMs, dtz, unit) {
  return unit === 'hour' ? tzd.hourBucketLabelInTz(nowMs, dtz) : null;
}
```

- [ ] **Step 4: Захватить `nowMs` и проставить поля в эндпоинте**

В обработчике `GET /api/publish-queue/dashboard` сразу после `const preset = ...` (строка ~2065) добавить:

```js
    const nowMs = Date.now();
```

Заменить вызов `calcDashboardRange(preset, fromStr, toStr, Date.now(), dtz)` (строка ~2072) на использование `nowMs`:

```js
      range = calcDashboardRange(preset, fromStr, toStr, nowMs, dtz);
```

После сборки серии (строка ~2147, сразу после `series = Object.assign({...}, assembleSeries(...))`) добавить:

```js
      series.current_bucket = currentHourBucketLabel(nowMs, dtz, series.unit);
```

В `return res.json({ ... })` (строка ~2177) добавить разворот меты сразу после `date_basis: dateBasis,`:

```js
      date_basis: dateBasis,
      ...buildDisplayTzMeta(nowMs, dtz),
```

- [ ] **Step 5: Экспортировать хелперы под TEST_MODE**

Рядом с экспортами из Task 2:

```js
  module.exports.buildDisplayTzMeta = buildDisplayTzMeta;
  module.exports.currentHourBucketLabel = currentHourBucketLabel;
```

- [ ] **Step 6: Запустить тест — PASS**

Run: `node --test test_dashboard_tz_asof.test.js`
Expected: PASS (все тесты).

- [ ] **Step 7: Smoke — сервер стартует без синтаксических ошибок**

Run: `node -e "process.env.TEST_MODE='1';process.env.DATABASE_URL='postgresql://openclaw:openclaw123@localhost/openclaw';require('./server');console.log('OK require server.js')"`
Expected: вывод `OK require server.js` без исключений.

- [ ] **Step 8: Коммит**

```bash
git add server.js test_dashboard_tz_asof.test.js
git commit -m "feat(dashboard): мета пояса (display_tz/label/as_of) + series.current_bucket в ответе"
```

---

## Task 4: `public/index.html` — метка пояса, маркер «сейчас», сноска (пункты A, B фронт)

**Files:**
- Modify: `public/index.html` — разметка (~строки 2457–2469), `loadPublishDashboard` (~12482), `renderDashboardChart` (~12583)

- [ ] **Step 1: Добавить элементы разметки в карточку графика**

В `public/index.html` найти заголовок карточки (строки ~2458–2464):

```html
      <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div class="text-xs font-semibold text-gray-400 uppercase">Success rate в динамике</div>
        <label class="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
          <input type="checkbox" id="dash-labels-toggle" checked onchange="renderDashboardChart(_dashLastSeries)" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500">
          Значения на графике
        </label>
      </div>
```

Заменить на (добавлена строка `#dash-tz-note`):

```html
      <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div class="flex items-center gap-2 flex-wrap">
          <div class="text-xs font-semibold text-gray-400 uppercase">Success rate в динамике</div>
          <span id="dash-tz-note" class="text-xs text-gray-400"></span>
        </div>
        <label class="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
          <input type="checkbox" id="dash-labels-toggle" checked onchange="renderDashboardChart(_dashLastSeries)" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500">
          Значения на графике
        </label>
      </div>
```

Найти контейнер канвы (строки ~2465–2468):

```html
      <div class="relative" style="height:320px">
        <canvas id="dash-chart"></canvas>
        <div id="dash-chart-empty" class="hidden absolute inset-0 flex items-center justify-center text-sm text-gray-400">Нет данных за период</div>
      </div>
```

Заменить на (добавлена сноска `#dash-hour-note` после контейнера):

```html
      <div class="relative" style="height:320px">
        <canvas id="dash-chart"></canvas>
        <div id="dash-chart-empty" class="hidden absolute inset-0 flex items-center justify-center text-sm text-gray-400">Нет данных за период</div>
      </div>
      <div id="dash-hour-note" class="hidden text-xs text-gray-400 mt-1">Текущий час ещё заполняется</div>
```

- [ ] **Step 2: Рендер метки пояса в `loadPublishDashboard`**

Найти в `loadPublishDashboard` строку (~12482):

```js
    if (display) display.textContent = _fmtRangeDisplay(data.range);
```

Сразу ПОД ней добавить:

```js
    _renderDashTzNote(data);
```

Добавить функцию `_renderDashTzNote` непосредственно перед `function renderDashboardChart(series) {` (строка ~12583):

```js
function _renderDashTzNote(data) {
  const el = document.getElementById('dash-tz-note');
  if (!el) return;
  const tz = data.display_tz || (data.range && data.range.tz) || '';
  const lbl = data.display_tz_label ? ` (${data.display_tz_label})` : '';
  const time = (data.as_of || '').split(' ')[1] || '';
  el.textContent = tz ? `🌍 Данные по поясу ${tz}${lbl}${time ? ' · на ' + time : ''}` : '';
}
```

- [ ] **Step 3: Инлайн-плагин маркера «сейчас» + правка `renderDashboardChart`**

Добавить ПЕРЕД `function renderDashboardChart(series) {` (можно сразу после `_renderDashTzNote`):

```js
// Вертикальный пунктир «сейчас» на индексе текущего часа (chart.$nowIdx).
const nowMarkerPlugin = {
  id: 'dashNowMarker',
  afterDatasetsDraw(chart) {
    const idx = chart.$nowIdx;
    if (idx == null || idx < 0) return;
    const xScale = chart.scales.x;
    if (!xScale) return;
    const x = xScale.getPixelForValue(idx);
    const { top, bottom } = chart.chartArea;
    const ctx = chart.ctx;
    ctx.save();
    ctx.strokeStyle = 'rgba(99,102,241,0.7)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(99,102,241,0.9)';
    ctx.font = '10px sans-serif';
    ctx.fillText('сейчас', x + 4, top + 10);
    ctx.restore();
  },
};
```

В `renderDashboardChart`, после строки `const labels = buckets.map(b => _fmtBucketAxisLabel(b, series.unit));` (~12614) добавить вычисление индекса текущего часа и сноски:

```js
  const nowIdx = (series && series.unit === 'hour' && series.current_bucket)
    ? buckets.indexOf(series.current_bucket) : -1;
  const hourNote = document.getElementById('dash-hour-note');
  if (hourNote) {
    if (nowIdx >= 0) {
      const hh = (series.current_bucket.split(' ')[1] || '').slice(0, 2);
      hourNote.textContent = `Текущий час (${hh}:00–${hh}:59) ещё заполняется`;
      hourNote.classList.remove('hidden');
    } else {
      hourNote.classList.add('hidden');
    }
  }
```

Подключить плагин в массив `plugins` создания чарта. Найти (~12649):

```js
    plugins: [window.ChartDataLabels].filter(Boolean),
  });
```

Заменить на (добавлен плагин + проставление `$nowIdx` после создания):

```js
    plugins: [window.ChartDataLabels, nowMarkerPlugin].filter(Boolean),
  });
  _dashChart.$nowIdx = nowIdx;
  _dashChart.update();
```

- [ ] **Step 4: Визуальная проверка**

Run (локальный статик-сервер для index.html недостаточен — нужен бэкенд; проверяем на запущенном инстансе или после канареечного деплоя):

1. Открыть дашборд выкладки, режим **«Дата задачи»**, пресет **«Сегодня»**.
2. Убедиться: над графиком метка `🌍 Данные по поясу Europe/Moscow (UTC+3) · на ЧЧ:ММ`, где ЧЧ:ММ ≈ настенные часы МСК.
3. Линия ряда доходит до **текущего часа** (а не отстаёт на час).
4. На текущем часе — вертикальный пунктир «сейчас», под графиком — сноска «Текущий час (ЧЧ:00–ЧЧ:59) ещё заполняется».
5. Переключиться на **«Запланировано»** (дневной) — сноска и маркер скрыты, дневной ряд без изменений.

Expected: всё перечисленное визуально подтверждено.

- [ ] **Step 5: Коммит**

```bash
git add public/index.html
git commit -m "feat(dashboard-ui): метка пояса/'на сейчас', маркер текущего часа и сноска про незавершённый час"
```

---

## Task 5: Полная регрессия + деплой

- [ ] **Step 1: Прогнать релевантные наборы тестов**

Run: `node --test test_dashboard_tz_asof.test.js test_wp221_dashboard_tz.test.js test_wp247_dashboard_window.test.js test_wp247_funnel_report_tz.test.js test_tz_display.test.js`
Expected: PASS во всех.

- [ ] **Step 2: Сверка факт-режима с живым SQL (после деплоя)**

После деплоя на прод выполнить read-only запрос (бакеты по факту выкладки) и сверить с графиком:

```sql
SELECT to_char(date_trunc('hour', COALESCE(pq.updated_at, pq.scheduled_at) AT TIME ZONE 'Europe/Moscow'), 'HH24:MI') AS hour_msk,
       COUNT(*) FILTER (WHERE pq.status='done') AS done,
       COUNT(*) FILTER (WHERE pq.status IN ('failed','past_slot_dropped')
                         OR (pq.status='cancelled' AND pq.manual_handoff_at IS NOT NULL)) AS errors
FROM publish_queue pq
WHERE (pq.scheduled_at AT TIME ZONE 'Europe/Moscow')::date = (now() AT TIME ZONE 'Europe/Moscow')::date
GROUP BY 1 ORDER BY 1;
```

Expected: текущий час присутствует с ненулевым done/errors (линия доходит до него на графике).

- [ ] **Step 3: Деплой**

Действия на проде (autowarm/delivery, процесс pm2 id 35):

```bash
# на проде, в каталоге деплоя delivery (где запущен server.js под pm2 id 35):
git fetch origin && git merge --ff-only origin/main   # после мерджа ветки в main
sudo pm2 restart 35
sudo pm2 logs 35 --lines 20 --nostream
```

Kill-switch `DASHBOARD_SERIES_ACTUAL_TIME_ENABLED` по умолчанию ON (code-default). Откат поведения C без отката кода: выставить `DASHBOARD_SERIES_ACTUAL_TIME_ENABLED=0` в прод-`.env` и `sudo pm2 restart 35 --update-env`.

Expected: процесс перезапущен, в логах нет ошибок, дашборд открывается.

- [ ] **Step 4: Финальная приёмка (визуально)**

Повторить визуальную проверку Task 4 Step 4 на проде. Подтвердить с Данилом, что график совпадает с текущим временем МСК и метка пояса видна.

---

## Самопроверка покрытия спеки

- **A (метка пояса + «на сейчас»):** Task 1 (`tzLabel`), Task 3 (`buildDisplayTzMeta`, поля ответа), Task 4 (`_renderDashTzNote`, `#dash-tz-note`). ✓
- **B (маркер текущего часа):** Task 1 (`hourBucketLabelInTz`), Task 3 (`currentHourBucketLabel`, `series.current_bucket`), Task 4 (`nowMarkerPlugin`, `#dash-hour-note`). ✓
- **C (часовой ряд по факту, kill-switch):** Task 2 (`seriesBucketExpr`, `isSeriesActualTimeEnabled`, замена inline, экспорт, тесты ON/OFF/planned). ✓
- **Когорта/дневной/отчёт/воронка не тронуты:** Task 2 меняет только выражение бакета ряда; `whereSql`/`baseParams`/planned-ветка/`pipeline_funnel.js`/`daily_publish_report.js` не изменяются. ✓
- **Известные ограничения суток:** задокументированы в спеке (когорта по `scheduled_at`, ось по `updated_at`); кода не требуют. ✓

---

## Финальный статус (2026-06-05)

**SHIPPED → delivery `main` (ff, HEAD `ead6369`); ветка `dashboard-tz-asof-2026-06-05`.** OpenProject **WP#271** (Тестирование) + follow-up **WP#272** (Бэклог).

Все 5 задач выполнены субагент-driven с двухстадийным ревью (спек+качество) и финальным холистическим ревью. Коммиты: `00211e9` (tz хелперы) → `9ccae81` (фиксы ревью) → `ac8488f` (seriesBucketExpr+kill-switch) → `048fe91` (мета пояса+current_bucket) → `e9aa02d`+`03e41f2` (фронт). Доступные тесты зелёные (7 unit + 10 tz_display); DB-регрессия (Task 5 Step 1/2) и деплой (Step 3/4) — на прод-хосте.
