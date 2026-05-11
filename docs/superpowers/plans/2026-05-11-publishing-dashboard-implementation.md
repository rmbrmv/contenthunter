# Publishing Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md` (commit `37dd4c83c`).

**Goal:** Добавить подраздел «📊 Дашборд» в модуль «📤 Выкладка» — KPI-карточки (всего/ожидание/выполняются/готово/ошибки/отменено + success rate) с пресетами Сегодня/Неделя/Месяц/Custom (Europe/Moscow, календарные) в общей строке и разбивкой по IG/TT/YT.

**Architecture:** Один новый endpoint `GET /api/publish-queue/dashboard` агрегирует `publish_queue` через `GROUPING SETS ((platform), ())` с `GROUPING(platform)` для разделения grand-total и реальных `NULL`-platform строк. Frontend — новая HTML-секция в `public/index.html` с date-presets toolbar и manual refresh. Period calc живёт в server.js (Europe/Moscow = UTC+3 fixed, no DST).

**Tech Stack:** Node.js 20+, Express, `pg` driver, native `node --test`. Vanilla JS + Tailwind в `public/index.html`.

**Working directories:**
- Backend: `/root/.openclaw/workspace-genri/autowarm/server.js`
- Frontend: `/root/.openclaw/workspace-genri/autowarm/public/index.html`
- Tests: `/root/.openclaw/workspace-genri/autowarm/tests/test_publish_dashboard.test.js`
- PM2 app: `autowarm` (см. `ecosystem.production.config.js`)
- Auto-push hook: коммиты в `/root/.openclaw/workspace-genri/autowarm/` автоматически уходят в `GenGo2/delivery-contenthunter`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `tests/test_publish_dashboard.test.js` | Create | Unit-тесты для `calcDashboardRange`, `mapDashboardRows`, `computeSuccessRate` |
| `server.js` | Modify | Добавить хелперы + endpoint `/api/publish-queue/dashboard`; экспортнуть хелперы под `if (module.exports)` блоком на строке ~7785 |
| `public/index.html` | Modify | Sidebar-кнопка «📊 Дашборд», новая секция `section-publishing-dashboard`, JS-функции `loadPublishingDashboard`/`renderDashboardOverall`/`renderDashboardPlatforms`/`switchDashboardPreset`; обновить `defaultSections.publishing` и `sidebarMap` |

Все backend-изменения локализованы в одном файле (`server.js`); все frontend-изменения — в одном файле (`index.html`). Это соответствует существующему паттерну autowarm.

---

## Task 1: Backend pure helpers (TDD)

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/test_publish_dashboard.test.js`
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js` (добавить хелперы + экспорт около строки 7785)

### Step 1: Write failing tests

- [ ] Создать `tests/test_publish_dashboard.test.js` со следующим содержимым:

```javascript
'use strict';

/**
 * Unit-тесты для publishing dashboard helpers.
 * Спек: docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md
 *
 * Покрываем pure-функции (без БД):
 *   - calcDashboardRange: today / week / month / custom + ошибки валидации
 *   - mapDashboardRows: GROUPING SETS rows → response shape
 *   - computeSuccessRate: done / (done + errors), null если деном=0
 */

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');

const {
  calcDashboardRange,
  mapDashboardRows,
  computeSuccessRate,
} = require('../server.js');

// ---- calcDashboardRange ---------------------------------------------------

describe('calcDashboardRange — Europe/Moscow (UTC+3 fixed)', () => {

  test('today: 06:00 MSK → [today 00:00 MSK, tomorrow 00:00 MSK)', () => {
    // 2026-05-11 03:00 UTC = 06:00 MSK
    const now = Date.UTC(2026, 4, 11, 3, 0, 0);
    const r = calcDashboardRange('today', null, null, now);
    assert.equal(r.preset, 'today');
    assert.equal(r.from.toISOString(), '2026-05-10T21:00:00.000Z');
    assert.equal(r.to.toISOString(),   '2026-05-11T21:00:00.000Z');
  });

  test('today: 22:30 UTC = 01:30 MSK next day — date flips', () => {
    // 2026-05-10 22:30 UTC = 2026-05-11 01:30 MSK
    const now = Date.UTC(2026, 4, 10, 22, 30, 0);
    const r = calcDashboardRange('today', null, null, now);
    // MSK-сегодня = 2026-05-11, окно [2026-05-10 21:00 UTC, 2026-05-11 21:00 UTC)
    assert.equal(r.from.toISOString(), '2026-05-10T21:00:00.000Z');
    assert.equal(r.to.toISOString(),   '2026-05-11T21:00:00.000Z');
  });

  test('week: Wednesday 2026-05-13 → Mon 2026-05-11 .. Mon 2026-05-18 MSK', () => {
    // 2026-05-13 09:00 UTC = 12:00 MSK (среда)
    const now = Date.UTC(2026, 4, 13, 9, 0, 0);
    const r = calcDashboardRange('week', null, null, now);
    assert.equal(r.preset, 'week');
    assert.equal(r.from.toISOString(), '2026-05-10T21:00:00.000Z'); // Mon 2026-05-11 00:00 MSK
    assert.equal(r.to.toISOString(),   '2026-05-17T21:00:00.000Z'); // Mon 2026-05-18 00:00 MSK
  });

  test('week: Sunday → previous Monday start, not next', () => {
    // 2026-05-17 12:00 UTC = 15:00 MSK (воскресенье)
    const now = Date.UTC(2026, 4, 17, 12, 0, 0);
    const r = calcDashboardRange('week', null, null, now);
    assert.equal(r.from.toISOString(), '2026-05-10T21:00:00.000Z'); // Mon 2026-05-11
    assert.equal(r.to.toISOString(),   '2026-05-17T21:00:00.000Z'); // Mon 2026-05-18
  });

  test('month: May 11 → 2026-05-01 MSK .. 2026-06-01 MSK', () => {
    const now = Date.UTC(2026, 4, 11, 9, 0, 0);
    const r = calcDashboardRange('month', null, null, now);
    assert.equal(r.preset, 'month');
    assert.equal(r.from.toISOString(), '2026-04-30T21:00:00.000Z'); // 2026-05-01 00:00 MSK
    assert.equal(r.to.toISOString(),   '2026-05-31T21:00:00.000Z'); // 2026-06-01 00:00 MSK
  });

  test('month: December → wraps to next year January', () => {
    const now = Date.UTC(2026, 11, 15, 9, 0, 0); // 2026-12-15 12:00 MSK
    const r = calcDashboardRange('month', null, null, now);
    assert.equal(r.from.toISOString(), '2026-11-30T21:00:00.000Z'); // 2026-12-01 MSK
    assert.equal(r.to.toISOString(),   '2026-12-31T21:00:00.000Z'); // 2027-01-01 MSK
  });

  test('custom: valid range 2026-05-01..2026-05-11 inclusive', () => {
    const r = calcDashboardRange('custom', '2026-05-01', '2026-05-11', Date.UTC(2026, 4, 11));
    assert.equal(r.preset, 'custom');
    assert.equal(r.from.toISOString(), '2026-04-30T21:00:00.000Z'); // 2026-05-01 00:00 MSK
    assert.equal(r.to.toISOString(),   '2026-05-11T21:00:00.000Z'); // 2026-05-12 00:00 MSK (exclusive)
  });

  test('custom: single day from == to', () => {
    const r = calcDashboardRange('custom', '2026-05-11', '2026-05-11', Date.UTC(2026, 4, 11));
    assert.equal(r.from.toISOString(), '2026-05-10T21:00:00.000Z');
    assert.equal(r.to.toISOString(),   '2026-05-11T21:00:00.000Z'); // следующий день
  });

  test('custom: from > to → throws', () => {
    assert.throws(
      () => calcDashboardRange('custom', '2026-05-11', '2026-05-01', Date.UTC(2026, 4, 11)),
      /from must be <= to/
    );
  });

  test('custom: range > 60 days → throws', () => {
    assert.throws(
      () => calcDashboardRange('custom', '2026-01-01', '2026-05-01', Date.UTC(2026, 4, 11)),
      /range too large/
    );
  });

  test('custom: invalid format → throws', () => {
    assert.throws(
      () => calcDashboardRange('custom', '05/11/2026', '2026-05-11', Date.UTC(2026, 4, 11)),
      /invalid date format/
    );
  });

  test('unknown preset → throws', () => {
    assert.throws(
      () => calcDashboardRange('yesterday', null, null, Date.UTC(2026, 4, 11)),
      /unknown preset/
    );
  });
});

// ---- computeSuccessRate ---------------------------------------------------

describe('computeSuccessRate', () => {
  test('typical case: 95 done / 12 errors → 0.888', () => {
    assert.equal(computeSuccessRate(95, 12), 0.888);
  });
  test('100% success: errors=0', () => {
    assert.equal(computeSuccessRate(50, 0), 1);
  });
  test('0% success: done=0, errors=10', () => {
    assert.equal(computeSuccessRate(0, 10), 0);
  });
  test('null when both zero (нечего считать)', () => {
    assert.equal(computeSuccessRate(0, 0), null);
  });
  test('rounded to 3 decimals', () => {
    // 7 / (7+3) = 0.7 → 0.7 exactly
    assert.equal(computeSuccessRate(7, 3), 0.7);
    // 1 / 3 = 0.3333... → 0.333
    assert.equal(computeSuccessRate(1, 2), 0.333);
  });
});

// ---- mapDashboardRows -----------------------------------------------------

describe('mapDashboardRows — GROUPING SETS rows → response shape', () => {
  test('full mix: IG + TT + YT + vk + NULL platform + grand total', () => {
    // Эмулируем результат SELECT с GROUPING SETS ((platform), ())
    const rows = [
      { bucket: 'instagram', is_grand_total: 0, total: 40, pending: 3, running: 1, done: 32, errors: 4, cancelled_skipped: 0 },
      { bucket: 'tiktok',    is_grand_total: 0, total: 45, pending: 3, running: 1, done: 38, errors: 2, cancelled_skipped: 1 },
      { bucket: 'youtube',   is_grand_total: 0, total: 35, pending: 2, running: 0, done: 25, errors: 6, cancelled_skipped: 2 },
      { bucket: 'vk',        is_grand_total: 0, total: 10, pending: 1, running: 0, done: 7,  errors: 2, cancelled_skipped: 0 },
      { bucket: 'unknown',   is_grand_total: 0, total: 2,  pending: 0, running: 0, done: 0,  errors: 2, cancelled_skipped: 0 },
      { bucket: 'all',       is_grand_total: 1, total: 132,pending: 9, running: 2, done: 102,errors: 16,cancelled_skipped: 3 },
    ];
    const out = mapDashboardRows(rows);

    assert.deepEqual(out.overall, {
      total: 132, pending: 9, running: 2, done: 102, errors: 16, cancelled_skipped: 3,
      success_rate: computeSuccessRate(102, 16), // ≈ 0.864
    });
    assert.equal(out.by_platform.instagram.total, 40);
    assert.equal(out.by_platform.tiktok.total, 45);
    assert.equal(out.by_platform.youtube.total, 35);
    // vk и unknown НЕ должны попасть в by_platform
    assert.equal(out.by_platform.vk, undefined);
    assert.equal(out.by_platform.unknown, undefined);
  });

  test('empty result set → zeros и success_rate=null', () => {
    // Grand-total ряд с нулями (publish_queue ничего не вернул в окне).
    // GROUPING SETS вернёт только grand-total строку, без per-platform.
    const rows = [
      { bucket: 'all', is_grand_total: 1, total: 0, pending: 0, running: 0, done: 0, errors: 0, cancelled_skipped: 0 },
    ];
    const out = mapDashboardRows(rows);
    assert.equal(out.overall.total, 0);
    assert.equal(out.overall.success_rate, null);
    // IG/TT/YT должны быть заполнены нулевыми объектами для стабильного API
    assert.equal(out.by_platform.instagram.total, 0);
    assert.equal(out.by_platform.tiktok.total, 0);
    assert.equal(out.by_platform.youtube.total, 0);
    assert.equal(out.by_platform.instagram.success_rate, null);
  });

  test('partial: только IG в окне → TT/YT с нулями', () => {
    const rows = [
      { bucket: 'instagram', is_grand_total: 0, total: 5, pending: 0, running: 0, done: 4, errors: 1, cancelled_skipped: 0 },
      { bucket: 'all',       is_grand_total: 1, total: 5, pending: 0, running: 0, done: 4, errors: 1, cancelled_skipped: 0 },
    ];
    const out = mapDashboardRows(rows);
    assert.equal(out.by_platform.instagram.total, 5);
    assert.equal(out.by_platform.tiktok.total, 0);
    assert.equal(out.by_platform.youtube.total, 0);
  });

  test('пг возвращает строковые числа (pg-driver default) — преобразуются к Number', () => {
    // pg-driver по умолчанию возвращает COUNT(*) как string. Mapping должен это учесть.
    const rows = [
      { bucket: 'instagram', is_grand_total: '0', total: '10', pending: '1', running: '0', done: '8', errors: '1', cancelled_skipped: '0' },
      { bucket: 'all',       is_grand_total: '1', total: '10', pending: '1', running: '0', done: '8', errors: '1', cancelled_skipped: '0' },
    ];
    const out = mapDashboardRows(rows);
    assert.equal(out.overall.total, 10);
    assert.equal(typeof out.overall.total, 'number');
    assert.equal(out.by_platform.instagram.done, 8);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail (no implementation yet)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_publish_dashboard.test.js 2>&1 | tail -20
```

Expected: все падают с `TypeError: calcDashboardRange is not a function` (или похожим). Это ОК — TDD.

- [ ] **Step 3: Implement helpers in server.js**

Добавить в `server.js` секцию с хелперами (рекомендую размещение около строки 1655 — там уже живут SQL constants `PUBLISH_QUEUE_SELECT`/`PUBLISH_QUEUE_FROM`):

```javascript
// ===== Publishing Dashboard helpers =====
// Spec: docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md
// MSK = UTC+3 fixed (no DST). Никакого Intl-tz: считаем через смещение.

const MSK_OFFSET_MS = 3 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
const MAX_DASHBOARD_RANGE_DAYS = 60;

function calcDashboardRange(preset, fromStr, toStr, nowMs = Date.now()) {
  // Перевод now в MSK-frame: трактуем (UTC+3 ms) как UTC,
  // тогда getUTC* возвращает MSK-календарь.
  const nowMsk = new Date(nowMs + MSK_OFFSET_MS);
  const y = nowMsk.getUTCFullYear();
  const m = nowMsk.getUTCMonth();
  const d = nowMsk.getUTCDate();

  // dayMsMsk = MSK 00:00 текущей даты, выраженное в "MSK-frame UTC ms"
  // (т.е. сдвинутое). Чтобы получить настоящий UTC ts — вычесть MSK_OFFSET_MS.
  const dayMsMsk = Date.UTC(y, m, d);

  if (preset === 'today') {
    return {
      preset: 'today',
      from: new Date(dayMsMsk - MSK_OFFSET_MS),
      to:   new Date(dayMsMsk + DAY_MS - MSK_OFFSET_MS),
    };
  }

  if (preset === 'week') {
    // JS getUTCDay: 0=Sun..6=Sat. Хотим Mon-start: dow1=1..7 с Mon=1, Sun=7.
    const jsDow = new Date(dayMsMsk).getUTCDay();
    const dow1 = jsDow === 0 ? 7 : jsDow;
    const daysSinceMon = dow1 - 1;
    const monMsk = dayMsMsk - daysSinceMon * DAY_MS;
    return {
      preset: 'week',
      from: new Date(monMsk - MSK_OFFSET_MS),
      to:   new Date(monMsk + 7 * DAY_MS - MSK_OFFSET_MS),
    };
  }

  if (preset === 'month') {
    const m1Msk = Date.UTC(y, m, 1);
    const nextY = m === 11 ? y + 1 : y;
    const nextM = m === 11 ? 0 : m + 1;
    const m1NextMsk = Date.UTC(nextY, nextM, 1);
    return {
      preset: 'month',
      from: new Date(m1Msk - MSK_OFFSET_MS),
      to:   new Date(m1NextMsk - MSK_OFFSET_MS),
    };
  }

  if (preset === 'custom') {
    const dateRe = /^\d{4}-\d{2}-\d{2}$/;
    if (!dateRe.test(String(fromStr || '')) || !dateRe.test(String(toStr || ''))) {
      throw new Error('invalid date format, expected YYYY-MM-DD');
    }
    const [fy, fm, fd] = fromStr.split('-').map(Number);
    const [ty, tm, td] = toStr.split('-').map(Number);
    const fromMsk = Date.UTC(fy, fm - 1, fd);
    const toMsk = Date.UTC(ty, tm - 1, td) + DAY_MS; // exclusive
    if (fromMsk >= toMsk) throw new Error('from must be <= to');
    if (toMsk - fromMsk > MAX_DASHBOARD_RANGE_DAYS * DAY_MS) {
      throw new Error('range too large (max ' + MAX_DASHBOARD_RANGE_DAYS + ' days)');
    }
    return {
      preset: 'custom',
      from: new Date(fromMsk - MSK_OFFSET_MS),
      to:   new Date(toMsk - MSK_OFFSET_MS),
    };
  }

  throw new Error('unknown preset: ' + preset);
}

function computeSuccessRate(done, errors) {
  const denom = Number(done) + Number(errors);
  if (denom === 0) return null;
  return Math.round((Number(done) / denom) * 1000) / 1000;
}

const DASHBOARD_PLATFORMS = ['instagram', 'tiktok', 'youtube'];

function _emptyBucket() {
  return { total: 0, pending: 0, running: 0, done: 0, errors: 0, cancelled_skipped: 0, success_rate: null };
}

function _rowToBucket(r) {
  const done = Number(r.done);
  const errors = Number(r.errors);
  return {
    total: Number(r.total),
    pending: Number(r.pending),
    running: Number(r.running),
    done,
    errors,
    cancelled_skipped: Number(r.cancelled_skipped),
    success_rate: computeSuccessRate(done, errors),
  };
}

function mapDashboardRows(rows) {
  let overall = _emptyBucket();
  const by_platform = {};
  for (const p of DASHBOARD_PLATFORMS) by_platform[p] = _emptyBucket();

  for (const r of rows) {
    if (Number(r.is_grand_total) === 1) {
      overall = _rowToBucket(r);
      continue;
    }
    if (DASHBOARD_PLATFORMS.includes(r.bucket)) {
      by_platform[r.bucket] = _rowToBucket(r);
    }
    // bucket='unknown' или 'vk'/'pinterest'/'likee' → отбрасываем
    // (они уже учтены в grand-total).
  }
  return { overall, by_platform };
}
```

Добавить экспорт в существующий блок около строки 7785:

```javascript
if (typeof module !== 'undefined' && module.exports) {
  // ... существующие экспорты ...
  module.exports.calcDashboardRange = calcDashboardRange;
  module.exports.computeSuccessRate = computeSuccessRate;
  module.exports.mapDashboardRows = mapDashboardRows;
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm && node --test --test-force-exit tests/test_publish_dashboard.test.js 2>&1 | tail -30
```

Expected: все `pass`, итог типа `# tests N`, `# pass N`, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js tests/test_publish_dashboard.test.js
git commit -m "feat(publish-dashboard): add pure helpers — calcDashboardRange/mapDashboardRows/computeSuccessRate

Pure functions для periods/aggregation/rate без БД-зависимостей.
Europe/Moscow UTC+3 fixed (no DST handling needed).
Spec: docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md
Tests: tests/test_publish_dashboard.test.js
"
```

---

## Task 2: Backend endpoint `/api/publish-queue/dashboard`

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js` (добавить route)

### Step 1: Locate where to add the route

- [ ] Найти существующий маршрут `app.get('/api/publish/queue', requireAuth, ...)` (около строки 1705 в server.js). Новый endpoint размещаем перед ним для логичной группировки.

### Step 2: Add endpoint

- [ ] Добавить в server.js перед `app.get('/api/publish/queue', ...)`:

```javascript
// GET /api/publish-queue/dashboard — агрегированные метрики publish_queue
// Spec: docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md
// Query: preset=today|week|month|custom, from=YYYY-MM-DD, to=YYYY-MM-DD (custom).
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

    const sql = `
      SELECT
        CASE
          WHEN GROUPING(platform) = 1 THEN 'all'
          WHEN platform IS NULL      THEN 'unknown'
          ELSE platform
        END                                                                  AS bucket,
        GROUPING(platform)                                                   AS is_grand_total,
        COUNT(*)                                                             AS total,
        COUNT(*) FILTER (WHERE status = 'pending')                           AS pending,
        COUNT(*) FILTER (WHERE status = 'running')                           AS running,
        COUNT(*) FILTER (WHERE status = 'done')                              AS done,
        COUNT(*) FILTER (WHERE status IN ('failed','past_slot_dropped'))     AS errors,
        COUNT(*) FILTER (WHERE status IN ('cancelled','skipped'))            AS cancelled_skipped
      FROM publish_queue
      WHERE scheduled_at >= $1 AND scheduled_at < $2
      GROUP BY GROUPING SETS ((platform), ())
    `;
    const { rows } = await pool.query(sql, [range.from, range.to]);
    const { overall, by_platform } = mapDashboardRows(rows);

    return res.json({
      range: {
        preset: range.preset,
        from: range.from.toISOString(),
        to: range.to.toISOString(),
        tz: 'Europe/Moscow',
      },
      overall,
      by_platform,
    });
  } catch (e) {
    console.error('[pub-dash] failed:', e);
    return res.status(500).json({ error: 'internal error' });
  }
});
```

### Step 3: Reload PM2 to pick up server.js change

- [ ] Сначала проверить cwd PM2-процесса (memory `pm2_dump_path_drift`):

```bash
pm2 describe autowarm | grep -E 'exec cwd|status'
```

Expected: `exec cwd = /root/.openclaw/workspace-genri/autowarm` и `status: online`. Если cwd другой — STOP, доложить пользователю.

- [ ] Перезапустить:

```bash
pm2 reload autowarm
pm2 logs autowarm --lines 20 --nostream
```

Expected: процесс online, нет fatal errors.

### Step 4: Smoke endpoint manually

- [ ] Через curl с auth-cookie (или из браузера в DevTools):

```bash
# Из браузера: открыть https://delivery.contenthunter.ru, в DevTools Console:
# fetch('/api/publish-queue/dashboard?preset=today').then(r=>r.json()).then(console.log)
# 
# Или через curl с session-cookie из браузера:
curl -sS -b "connect.sid=<SESSION_FROM_BROWSER>" \
  https://delivery.contenthunter.ru/api/publish-queue/dashboard?preset=today | jq
```

Expected JSON структура:
```json
{
  "range": {"preset": "today", "from": "...", "to": "...", "tz": "Europe/Moscow"},
  "overall": {"total": N, "pending": N, ..., "success_rate": <0..1|null>},
  "by_platform": {"instagram": {...}, "tiktok": {...}, "youtube": {...}}
}
```

- [ ] Проверить пресет `week`, `month`, `custom`:

```bash
curl -sS -b "connect.sid=..." 'https://delivery.contenthunter.ru/api/publish-queue/dashboard?preset=week' | jq '.range'
curl -sS -b "connect.sid=..." 'https://delivery.contenthunter.ru/api/publish-queue/dashboard?preset=month' | jq '.range'
curl -sS -b "connect.sid=..." 'https://delivery.contenthunter.ru/api/publish-queue/dashboard?preset=custom&from=2026-05-01&to=2026-05-11' | jq '.range'
```

- [ ] Проверить error 400 на bad input:

```bash
curl -sS -b "connect.sid=..." 'https://delivery.contenthunter.ru/api/publish-queue/dashboard?preset=custom&from=2026-05-11&to=2026-05-01' -w '\nHTTP %{http_code}\n'
```

Expected: HTTP 400, `{"error":"from must be <= to"}`.

### Step 5: Cross-check данных с прямым SQL

- [ ] Сравнить overall.total из endpoint с прямым SQL за тот же диапазон:

```bash
# Возьми from/to из response endpoint (preset=today), подставь в:
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
  SELECT status, COUNT(*) FROM publish_queue
  WHERE scheduled_at >= '<from>' AND scheduled_at < '<to>'
  GROUP BY status ORDER BY COUNT(*) DESC;
"
```

Expected: суммы по статусам совпадают с overall.{pending,running,done,errors,cancelled_skipped}. Если расхождение — отладка перед commit.

### Step 6: Commit

- [ ] 

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js
git commit -m "feat(publish-dashboard): add GET /api/publish-queue/dashboard endpoint

Один GROUPING SETS-запрос; GROUPING(platform) разделяет grand-total и
real NULL-platform строки (past_slot_dropped audit). Период расчитывается
на сервере (Europe/Moscow, календарные).

Spec: docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md
"
```

(Auto-push hook отправит коммит в `GenGo2/delivery-contenthunter`.)

---

## Task 3: Frontend — sidebar button + section scaffold + nav wiring

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html`

### Step 1: Add sidebar button (first position)

- [ ] Открыть `public/index.html`, найти блок `<nav id="sidebar-publishing"` (строка ~252). Заменить:

```html
  <nav id="sidebar-publishing" class="hidden p-3 space-y-1 flex-1">
    <button onclick="nav('publishing'); upSwitchTab('queue');" id="nav-publishing" class="nav-item w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium bg-indigo-50 text-indigo-700 text-left">
      <span>📋</span> Запланировано
    </button>
```

на:

```html
  <nav id="sidebar-publishing" class="hidden p-3 space-y-1 flex-1">
    <button onclick="nav('publishing-dashboard')" id="nav-publishing-dashboard" class="nav-item w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium bg-indigo-50 text-indigo-700 text-left">
      <span>📊</span> Дашборд
    </button>
    <button onclick="nav('publishing'); upSwitchTab('queue');" id="nav-publishing" class="nav-item w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-600 hover:bg-gray-100 text-left">
      <span>📋</span> Запланировано
    </button>
```

Изменение: Дашборд — новый первый пункт с active-классом; «Запланировано» теперь начинается с inactive-стилей (active будет назначен при клике).

### Step 2: Add section HTML scaffold

- [ ] Найти `<div id="section-publishing" class="section ...">` (около строки 2255). **Перед** этим div вставить новую секцию:

```html
<!-- ===== Publishing Dashboard (KPI карточки + разбивка по платформам) ===== -->
<div id="section-publishing-dashboard" class="section px-4 py-4 fade-in">
  <div class="flex items-center justify-between gap-3 mb-3 flex-wrap">
    <h2 class="text-base font-bold text-gray-900 shrink-0">📊 Дашборд выкладки</h2>
    <div class="flex gap-1.5 items-center flex-wrap">
      <button data-preset="today"  onclick="switchDashboardPreset('today')"  class="dash-preset-btn px-3 py-1.5 text-xs font-semibold rounded-lg border bg-indigo-50 text-indigo-700 border-indigo-200">Сегодня</button>
      <button data-preset="week"   onclick="switchDashboardPreset('week')"   class="dash-preset-btn px-3 py-1.5 text-xs font-semibold rounded-lg border bg-white text-gray-600 border-gray-200 hover:bg-gray-50">Неделя</button>
      <button data-preset="month"  onclick="switchDashboardPreset('month')"  class="dash-preset-btn px-3 py-1.5 text-xs font-semibold rounded-lg border bg-white text-gray-600 border-gray-200 hover:bg-gray-50">Месяц</button>
      <button data-preset="custom" onclick="switchDashboardPreset('custom')" class="dash-preset-btn px-3 py-1.5 text-xs font-semibold rounded-lg border bg-white text-gray-600 border-gray-200 hover:bg-gray-50">Свой диапазон</button>
      <button onclick="loadPublishingDashboard()" class="px-3 py-1.5 border border-gray-200 text-gray-600 text-xs font-semibold rounded-lg hover:bg-gray-50">🔄 Обновить</button>
    </div>
  </div>

  <!-- Custom range inputs (hidden until preset=custom) -->
  <div id="dash-custom-range" class="hidden mb-3 flex items-center gap-2 text-xs">
    <span class="text-gray-500">с</span>
    <input type="date" id="dash-from" class="px-2 py-1 border border-gray-200 rounded-lg text-xs">
    <span class="text-gray-500">по</span>
    <input type="date" id="dash-to" class="px-2 py-1 border border-gray-200 rounded-lg text-xs">
    <button onclick="applyDashboardCustom()" class="px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-lg">Применить</button>
    <span id="dash-range-error" class="text-xs text-red-500"></span>
  </div>

  <div id="dash-range-display" class="text-xs text-gray-400 mb-3">—</div>

  <!-- ВСЕ ЗАДАЧИ -->
  <div class="bg-white rounded-xl border border-gray-200 p-4 mb-3">
    <div class="text-xs font-semibold text-gray-400 uppercase mb-2">Все задачи</div>
    <div class="grid grid-cols-7 gap-2" id="dash-overall-tiles">
      <!-- генерится в renderDashboardOverall -->
    </div>
  </div>

  <!-- По платформам -->
  <div class="bg-white rounded-xl border border-gray-200 p-4">
    <div class="text-xs font-semibold text-gray-400 uppercase mb-2">По платформам</div>
    <div id="dash-platforms" class="space-y-2">
      <!-- генерится в renderDashboardPlatforms -->
    </div>
  </div>
</div>
```

### Step 3: Wire navigation — `defaultSections` + `sidebarMap`

- [ ] Найти `const defaultSections = { ... };` (около строки 3811). Изменить:

```javascript
  const defaultSections = { farming:'dashboard', devices:'sla', publishing:'publishing', accounts:'whatsapp', uniqualization:'uniqualization', 'unic-content':'uniqualization', analytics:'analytics', admin:'admin', 'global-settings':'global-settings' };
```

на:

```javascript
  const defaultSections = { farming:'dashboard', devices:'sla', publishing:'publishing-dashboard', accounts:'whatsapp', uniqualization:'uniqualization', 'unic-content':'uniqualization', analytics:'analytics', admin:'admin', 'global-settings':'global-settings' };
```

- [ ] Найти `const sidebarMap = { ...` (около строки 4000). Добавить ключ `'publishing-dashboard': 'publishing'`:

```javascript
  const sidebarMap = { devices: 'devices', ..., publishing: 'publishing', 'publishing-queue': 'publishing', 'publishing-results': 'publishing', 'publishing-tokens': 'publishing', ..., 'publishing-dashboard': 'publishing', ... };
```

(Точный паттерн: вставить `'publishing-dashboard': 'publishing',` среди остальных `publishing-*` ключей в этом объекте.)

- [ ] Найти функцию `nav(section)` (около строки 3918). Найти список обработчиков типа `if (section === 'publishing') loadUnifiedPublish();` (~строка 3966). Добавить ниже:

```javascript
  if (section === 'publishing-dashboard') loadPublishingDashboard();
```

- [ ] Найти `if (section === 'publishing-queue') { nav('publishing'); return; }` (около строки 3997). Активного редиректа на publishing-dashboard НЕ добавляем — секция самостоятельная.

### Step 4: Smoke navigation in browser

- [ ] Открыть `https://delivery.contenthunter.ru` (после auto-push hook + jam-free), кликнуть в module-tabs «📤 Выкладка». Expected:
  - Сразу открывается секция `section-publishing-dashboard` (а не Запланировано).
  - В левом сайдбаре первая активная кнопка — «📊 Дашборд».
  - URL содержит `#publishing/publishing-dashboard`.
- [ ] Перейти на «📋 Запланировано» — должна открыться старая секция queue, sidebar-active переключается. Возврат на «📊 Дашборд» — снова показывает дашборд (пока с пустыми KPI tiles).

### Step 5: Commit

- [ ] 

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(publish-dashboard): add sidebar nav + section scaffold

Новая первая кнопка '📊 Дашборд' в sidebar Выкладки.
defaultSections.publishing смещён с 'publishing' → 'publishing-dashboard'.
Tiles + custom-range UI без data-load пока (Task 5 заполнит JS).
"
```

---

## Task 4: Frontend — preset state mgmt + custom range

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html`

### Step 1: Add JS state + switchDashboardPreset

- [ ] Найти область в `<script>` блоке, где определены подобные state-переменные (например `_upCurrentTab` около строки 10681). Добавить рядом или в новый scope:

```javascript
// ===== Publishing Dashboard state =====
let _dashCurrentPreset = 'today';
let _dashCustomFrom = null;
let _dashCustomTo = null;

function switchDashboardPreset(preset) {
  _dashCurrentPreset = preset;
  // Подсветка кнопок
  document.querySelectorAll('.dash-preset-btn').forEach(btn => {
    const isActive = btn.dataset.preset === preset;
    btn.className = 'dash-preset-btn px-3 py-1.5 text-xs font-semibold rounded-lg border ' +
      (isActive
        ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
        : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50');
  });
  // Custom-range визуальность
  const custom = document.getElementById('dash-custom-range');
  if (custom) custom.classList.toggle('hidden', preset !== 'custom');
  // URL state
  if (preset !== 'custom') {
    setSubParam('dash:' + preset);
    loadPublishingDashboard();
  } else {
    // custom — ждём applyDashboardCustom
    setSubParam('dash:custom');
  }
}

function applyDashboardCustom() {
  const f = document.getElementById('dash-from').value;
  const t = document.getElementById('dash-to').value;
  const errEl = document.getElementById('dash-range-error');
  errEl.textContent = '';
  if (!f || !t) {
    errEl.textContent = 'Заполни обе даты';
    return;
  }
  if (f > t) {
    errEl.textContent = 'Дата «с» должна быть ≤ «по»';
    return;
  }
  _dashCustomFrom = f;
  _dashCustomTo = t;
  setSubParam('dash:custom:' + f + ':' + t);
  loadPublishingDashboard();
}
```

### Step 2: Smoke in browser — preset toggling без данных

- [ ] Открыть Дашборд. Кликать Сегодня/Неделя/Месяц/Свой диапазон. Expected:
  - Активная кнопка визуально меняется (синий фон).
  - При «Свой диапазон» появляется блок с двумя `<input type="date">`.
  - При других пресетах custom-range исчезает.
  - В URL меняется `#publishing/publishing-dashboard?dash:today` и т.п.
- [ ] В Custom — ввести `from > to`, нажать «Применить»: появляется красная подсказка.

### Step 3: Commit

- [ ] 

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(publish-dashboard): add preset state + custom range UI

switchDashboardPreset + applyDashboardCustom; visual toggling кнопок,
hide/show custom-range inputs, URL state через setSubParam.
loadPublishingDashboard() пока stub — данные в Task 5.
"
```

---

## Task 5: Frontend — data load + render

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html`

### Step 1: Add load function + renderers

- [ ] Добавить в `<script>` блок (рядом с `switchDashboardPreset`):

```javascript
const DASH_BUCKET_LABELS = [
  ['total',             'Всего',       'text-gray-700',    'border-gray-100'],
  ['pending',           'Ожидание',    'text-yellow-500',  'border-yellow-100'],
  ['running',           'Выполняются', 'text-blue-500',    'border-blue-100'],
  ['done',              'Готово',      'text-green-600',   'border-green-100'],
  ['errors',            'Ошибки',      'text-red-500',     'border-red-100'],
  ['cancelled_skipped', 'Отменено',    'text-gray-400',    'border-gray-100'],
  ['success_rate',      'Success rate','text-indigo-600',  'border-indigo-100'],
];

const DASH_PLATFORM_META = [
  ['instagram', '📷 Instagram'],
  ['tiktok',    '🎵 TikTok'],
  ['youtube',   '▶️ YouTube'],
];

function _fmtBucketCell(key, val) {
  if (key === 'success_rate') {
    if (val === null || val === undefined) return '—';
    return Math.round(val * 100) + '%';
  }
  if (val === null || val === undefined) return '—';
  return String(val);
}

function renderDashboardOverall(overall) {
  const root = document.getElementById('dash-overall-tiles');
  if (!root) return;
  root.innerHTML = DASH_BUCKET_LABELS.map(([key, label, textCls, borderCls]) => `
    <div class="flex flex-col items-center gap-0.5 bg-white border ${borderCls} rounded-lg px-2 py-2">
      <span class="text-xl font-bold ${textCls}">${_fmtBucketCell(key, overall[key])}</span>
      <span class="text-[10px] text-gray-400 uppercase">${label}</span>
    </div>
  `).join('');
}

function renderDashboardPlatforms(byPlatform) {
  const root = document.getElementById('dash-platforms');
  if (!root) return;
  root.innerHTML = DASH_PLATFORM_META.map(([key, label]) => {
    const b = byPlatform[key] || { total:0, pending:0, running:0, done:0, errors:0, cancelled_skipped:0, success_rate:null };
    const cells = DASH_BUCKET_LABELS.map(([k, , textCls]) =>
      `<span class="${textCls} font-semibold">${_fmtBucketCell(k, b[k])}</span>`
    ).join('<span class="text-gray-300">·</span>');
    return `
      <div class="flex items-center gap-3 py-2 border-b border-gray-50 last:border-b-0">
        <span class="text-sm font-semibold text-gray-700 w-28 shrink-0">${label}</span>
        <div class="flex items-center gap-2 text-sm flex-wrap">${cells}</div>
      </div>
    `;
  }).join('');
}

function _fmtRangeDisplay(range) {
  // ISO timestamps в UTC → красивые MSK даты "11.05.2026 00:00 — 12.05.2026 00:00 МСК"
  const fmt = ts => {
    const d = new Date(ts);
    const dd = String(d.getUTCDate() + (d.getUTCHours() >= 21 ? 1 : 0)).padStart(2, '0');
    // На самом деле проще: показать range.preset + сам диапазон по ISO + tz.
    return d.toISOString().slice(0, 16).replace('T', ' ');
  };
  const presetLabel = {today:'Сегодня', week:'Неделя', month:'Месяц', custom:'Свой диапазон'}[range.preset] || range.preset;
  return `${presetLabel}: ${fmt(range.from)} — ${fmt(range.to)} UTC`;
}

async function loadPublishingDashboard() {
  const root = document.getElementById('section-publishing-dashboard');
  if (!root) return;
  const display = document.getElementById('dash-range-display');
  if (display) display.textContent = 'Загрузка…';

  const params = new URLSearchParams({ preset: _dashCurrentPreset });
  if (_dashCurrentPreset === 'custom') {
    if (!_dashCustomFrom || !_dashCustomTo) {
      if (display) display.textContent = 'Выбери диапазон';
      return;
    }
    params.set('from', _dashCustomFrom);
    params.set('to', _dashCustomTo);
  }

  try {
    const r = await fetch('/api/publish-queue/dashboard?' + params.toString(), { credentials: 'same-origin' });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      if (display) display.innerHTML = `<span class="text-red-500">Ошибка: ${body.error || r.status}</span>`;
      return;
    }
    const data = await r.json();
    if (display) display.textContent = _fmtRangeDisplay(data.range);
    renderDashboardOverall(data.overall);
    renderDashboardPlatforms(data.by_platform);
  } catch (e) {
    if (display) display.innerHTML = `<span class="text-red-500">Сеть упала: ${e.message}</span>`;
  }
}
```

### Step 2: Wire to nav

- [ ] Уже добавлено в Task 3 Step 3 (`if (section === 'publishing-dashboard') loadPublishingDashboard();`). Убедиться, что хук остался.

### Step 3: Browser smoke — golden path

- [ ] Открыть `https://delivery.contenthunter.ru/#publishing/publishing-dashboard`. Expected:
  - Грузится «Загрузка…» → меняется на «Сегодня: 2026-05-10 21:00 — 2026-05-11 21:00 UTC» (или похожее).
  - 7 tile'ов в блоке «Все задачи» с числами или прочерками.
  - 3 строки IG/TT/YT в блоке «По платформам».
- [ ] Кликнуть «Неделя» → данные перегружаются.
- [ ] Кликнуть «Месяц» → данные перегружаются.
- [ ] Кликнуть «Свой диапазон» → ввести `2026-05-01..2026-05-11` → «Применить» → данные за этот диапазон.

### Step 4: Cross-check данных вручную

- [ ] Сравнить число в tile «Готово» с прямым SQL для пресета `today`. Запустить (взяв from/to из `dash-range-display`):

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
  SELECT COUNT(*) AS done FROM publish_queue
  WHERE scheduled_at >= '<FROM>'::timestamp AND scheduled_at < '<TO>'::timestamp
    AND status = 'done';
"
```

Expected: совпадает с UI «Готово».

- [ ] Аналогично проверить overall.errors = `SELECT COUNT(*) WHERE status IN ('failed','past_slot_dropped')`. И sum по платформам ≤ overall (разница = vk/pinterest/likee/NULL).

### Step 5: Commit

- [ ] 

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(publish-dashboard): wire data load + render overall/platforms

loadPublishingDashboard fetch + skeleton / error states.
renderDashboardOverall (7 KPI tiles) + renderDashboardPlatforms (IG/TT/YT rows).
success_rate в % с округлением; null → '—'.
"
```

---

## Task 6: URL state restore on page load

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html`

### Step 1: Find URL-state restore pattern

- [ ] Найти область где парсятся sub-params для других модулей (например, поиск `getSubParam` или `parseHashParams`). Если паттерна нет — добавить в `loadPublishingDashboard` чтение `location.hash` начальное.

### Step 2: Add restore-on-mount

- [ ] В `nav(section)` ветке `if (section === 'publishing-dashboard')` _перед_ `loadPublishingDashboard()` добавить:

```javascript
  if (section === 'publishing-dashboard') {
    const subParam = getSubParam ? getSubParam() : null; // совместимость с существующей utility
    if (subParam && subParam.startsWith('dash:')) {
      const parts = subParam.split(':');
      // dash:today | dash:week | dash:month | dash:custom | dash:custom:<from>:<to>
      const preset = parts[1] || 'today';
      if (['today','week','month','custom'].includes(preset)) {
        _dashCurrentPreset = preset;
        if (preset === 'custom' && parts.length === 4) {
          _dashCustomFrom = parts[2];
          _dashCustomTo = parts[3];
          const f = document.getElementById('dash-from');
          const t = document.getElementById('dash-to');
          if (f) f.value = _dashCustomFrom;
          if (t) t.value = _dashCustomTo;
        }
      }
    }
    switchDashboardPreset(_dashCurrentPreset); // вызовет loadPublishingDashboard
    return;
  }
```

Если `getSubParam` не существует — заменить на парсинг `location.hash`:

```javascript
const hash = location.hash || '';
const parts = hash.split('?');
const subParam = parts[1] || '';
// далее как выше
```

### Step 3: Browser smoke — bookmark works

- [ ] Открыть `https://delivery.contenthunter.ru/#publishing/publishing-dashboard?dash:month` — Expected: пресет «Месяц» подсвечен, данные за месяц.
- [ ] Открыть `...?dash:custom:2026-05-01:2026-05-11` — Expected: пресет «Свой диапазон» подсвечен, инпуты заполнены, данные за этот период.

### Step 4: Commit

- [ ] 

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add public/index.html
git commit -m "feat(publish-dashboard): restore preset + custom range from URL hash

dash:today|week|month|custom[:from:to] парсится на mount, фиксирует
state и вызывает switchDashboardPreset → перерисовка.
Закладки и refresh страницы сохраняют выбранный пресет.
"
```

---

## Task 7: Evidence document + handoff

**Files:**
- Create: `/home/claude-user/contenthunter/evidence/publishing-dashboard-shipped-2026-05-11.md`

### Step 1: Capture screenshots / SQL evidence

- [ ] Запустить из браузера: открыть Дашборд → скриншот.
- [ ] Зафиксировать SQL cross-check для каждого пресета (`today/week/month/custom-7d`):

```bash
for preset in today week month; do
  echo "=== preset=$preset ==="
  curl -sS -b "connect.sid=<SESSION>" "https://delivery.contenthunter.ru/api/publish-queue/dashboard?preset=$preset" \
    | jq '{range, overall, by_platform_totals: (.by_platform | to_entries | map({key, total: .value.total}) | from_entries)}'
done
```

### Step 2: Write evidence doc

- [ ] Создать `/home/claude-user/contenthunter/evidence/publishing-dashboard-shipped-2026-05-11.md`:

```markdown
# Publishing Dashboard — shipped 2026-05-11

**Spec:** docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md
**Plan:** docs/superpowers/plans/2026-05-11-publishing-dashboard-implementation.md
**Endpoint:** `GET /api/publish-queue/dashboard`
**UI:** https://delivery.contenthunter.ru/#publishing/publishing-dashboard

## Commits (in /root/.openclaw/workspace-genri/autowarm/)

1. `<sha1>` — feat(publish-dashboard): add pure helpers
2. `<sha2>` — feat(publish-dashboard): add GET endpoint
3. `<sha3>` — feat(publish-dashboard): add sidebar nav + section scaffold
4. `<sha4>` — feat(publish-dashboard): add preset state + custom range UI
5. `<sha5>` — feat(publish-dashboard): wire data load + render
6. `<sha6>` — feat(publish-dashboard): restore preset from URL hash

(Auto-push hook отправил всё в GenGo2/delivery-contenthunter.)

## Verification

- [ ] Unit tests: `node --test tests/test_publish_dashboard.test.js` — все pass
- [ ] HTTP smoke `preset=today/week/month/custom` — 200 OK, expected JSON shape
- [ ] HTTP 400 на `from > to` и `range > 60 дней`
- [ ] UI cross-check overall.{done,errors,pending,...} vs SQL — совпадают
- [ ] Sidebar active state переключается; URL hash сохраняется при refresh

## Known limitations / backlog

- Нет project/account фильтра в дашборде
- Нет графиков тренда (line chart за 30 дней)
- Нет drill-down: клик по «Ошибки» НЕ переходит в Запланировано с фильтром
- Платформы `vk`/`pinterest`/`likee` учитываются в `overall.total`, но не показаны
  отдельной строкой → возможна «дельта» между overall и sum(IG+TT+YT)
- No auto-refresh — manual только

## Memory update

После shipment добавить в `~/.claude/projects/.../memory/`:
- `project_publishing_dashboard_shipped.md` — endpoint + sidebar route + scope
```

### Step 3: Commit evidence + update memory index

- [ ] 

```bash
cd /home/claude-user/contenthunter
git add evidence/publishing-dashboard-shipped-2026-05-11.md
git commit -m "docs(evidence): publishing dashboard shipped 2026-05-11" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] Создать memory note `~/.claude/projects/-home-claude-user-contenthunter/memory/project_publishing_dashboard_shipped.md` + добавить ссылку в `MEMORY.md`.

---

## Self-Review summary

**Spec coverage:**
- §2 Source of truth → Task 2 (publish_queue в SQL).
- §3 Backend (endpoint + SQL + response + edge cases) → Task 1 (helpers) + Task 2 (route).
- §4 Frontend (sidebar + section + presets + load) → Tasks 3+4+5+6.
- §5 Error handling → Task 1 (validation throws), Task 2 (400/500 routes), Task 5 (UI error states).
- §6 Testing → Task 1 (unit), Task 2+5 (manual smoke), Task 7 (evidence).
- §7 Scope/YAGNI → backlog зафиксирован в Task 7 evidence.
- §8 Deploy → Task 2 Step 3 (pm2 reload), auto-push hook на коммитах.

**Type/method consistency:** `calcDashboardRange` сигнатура `(preset, fromStr, toStr, nowMs?)` одинаковая в тестах и реализации. `mapDashboardRows(rows)` возвращает `{overall, by_platform}` — клиент использует именно эти ключи в `loadPublishingDashboard`. `bucket` row-keys: `'all'|'instagram'|'tiktok'|'youtube'|'unknown'|<other>` — согласовано между SQL CASE и mapper.

**Placeholders:** нет TODO/TBD; код в каждом step полный.
