# PLAN — Paginated Tables Этап 2 (helper extract + `/api/publish/queue` migration)

**Тип:** refactor + feature
**Создан:** 2026-04-28
**Режим:** Full (без `--parallel`; план/evidence в текущей feature-ветке `fix/testbench-publisher-base-imports-20260427` — она исторически собирает доки этих сессий; код — отдельный repo)
**Spec:** `.ai-factory/specs/2026-04-28-paginated-tables-design.md` §6 (Этап 2)
**Pilot ref:** `.ai-factory/plans/2026-04-28-paginated-tables-pilot.md` (этап 1, shipped) + memory `project_paginated_tables_pilot.md`

## Репо

- **Plan/evidence:** `/home/claude-user/contenthunter/` (текущая ветка). Этап 2 — отдельный plan-файл, никаких записей в `PLAN.md` (правило `feedback_plan_full_mode_branch.md`).
- **Код:** `/root/.openclaw/workspace-genri/autowarm/` — prod-first. Пилот жил/живёт только здесь (5 commits 51ae35e..86a870e). Post-commit hook автоматически пушит в `GenGo2/delivery-contenthunter`.
- **НЕ в scope:** backport в `/home/claude-user/autowarm-testbench/`. Отдельный follow-up если понадобится — сейчас testbench и так отстаёт от prod на этап 1; смысла усложнять этап 2 нет.

## Settings

- **Testing:** yes — Node unit-тесты для `paginate.js` (encode/decode round-trip, validation, query-builder snapshots). Browser smoke руками для frontend (golden path + 2 edge-cases).
- **Logging:** verbose — серверные хелперы пишут `[paginate] action=<x> sort=<y> filters=<...>`; frontend factory — `[pt:<table-id>] event=<x>` (table-id из конфига instance'а).
- **Docs:** yes — evidence-файл `.ai-factory/evidence/paginated-tables-etap2-20260428.md` (curl baselines + commits + EXPLAIN + smoke результаты). Memory: расширить `project_paginated_tables_pilot.md` — отметить этап 2 закрыт.
- **Roadmap linkage:** skip (`.ai-factory/ROADMAP.md` отсутствует).

## Контекст — что уже есть (на 2026-04-28 14:00)

### Backend (`/root/.openclaw/workspace-genri/autowarm/server.js`)

| Что | Где | Заметка |
|---|---|---|
| `encodeCursor`/`decodeCursor` | строки 28–52 | inline; помечены TODO «extracted to module in iteration 2» |
| `PUBLISH_TASKS_SORT_WHITELIST` | строки 1814–1822 | `id, created_at, updated_at, scheduled_at, status, platform, device_serial` |
| `GET /api/publish/tasks` | 1862–1973 | cursor pagination + filters + sort + backwards-compat (без limit/cursor → array) |
| `GET /api/publish/tasks/stats` | 1975–2004 | server-side aggregation `{total, by_status: {...}}` |
| `GET /api/publish/tasks/by-ids` | 2006–2045 | row-refresh для polling |
| `GET /api/publish/queue` | 1453–1494 | **legacy**: flat array LIMIT 500, query params `status/platform/device/date_from/date_to` |

### Frontend (`/root/.openclaw/workspace-genri/autowarm/public/index.html`)

| Что | Где | Заметка |
|---|---|---|
| Pilot state `_uptState` | 10555 | `{rows, cursor, hasMore, loading, filters, sort}` + `UPT_PAGE_SIZE=100`, `UPT_MAX_AUTO_PAGES=5` |
| `loadPublishTasks()` | 10807 | cursor-based fetcher |
| `uptResetAndLoad()` | 10675 | сбрасывает курсор → `loadPublishTasks()` |
| `fetchPublishTasksStats()` | 10842 | дёргает `/stats` |
| `uptInitObserver()` | 10862 | `IntersectionObserver` на `<tr id="upt-sentinel">` (DOM 2372) |
| `uptStartPolling()` | 10884 | 10с stats + 15с row-refresh, gated `visibilitychange` |
| `refreshPublishTaskRows()` | 10914 | live-обновление через `/by-ids` |
| Queue legacy state | `_upAll`, `_upSort`, `_upSortDir`, `_upColFilters`, `_upShowDone` | client-side фильтр/сортировка по flat array |
| `loadUnifiedPublish()` | ~11100 | дёргает `/api/publish/queue` без параметров |
| `upRenderRows()` | ~рядом | client-side рендер |

## Scope

**В scope:**
1. Извлечь cursor-pagination в Node-модуль `paginate.js` (encode/decode + query-builders).
2. Перевести pilot (`/api/publish/tasks`, `/stats`, `/by-ids`) на helper — без регрессии (curl baseline = curl after).
3. Добавить cursor-pagination в `/api/publish/queue` (+ `/stats`, опционально `/by-ids` если frontend ставим на live-refresh).
4. Извлечь frontend-логику в `paginated-table.js` — factory `createPaginatedTable({...})`.
5. Перевести pilot UI (`/publishing/tasks`) на factory — без регрессии в браузере.
6. Перевести queue UI (`/publishing/queue` или нынешний tab unified-publish) на factory.
7. Unit-тесты для `paginate.js`. Browser smoke для UI.
8. Deploy в prod (commit, auto-push, `pm2 reload autowarm`).
9. Evidence + memory update.

**НЕ в scope:**
- Backport в `autowarm-testbench`.
- Этап 3 (раскатка на `archive/tasks`, `unic/tasks`, `factory/*`, `whatsapp/*`, `telegram/*`, `phone-warm/*`, `tasks`).
- WebSocket / SSE — остаёмся на polling.
- Виртуальный скроллинг.
- Авто-rebuild индексов; добавление индексов делаем точечно если EXPLAIN скажет, что нужно.
- Helper versioning (v1/v2) — кладём один файл `paginate.js`, один `paginated-table.js`. Если позже всплывёт необходимость fork — рассмотрим тогда.

## Корневые задачи

### Phase 1 — Backend: extract + pilot rewrite

#### T1. Pre-flight + baseline curl-ответов pilot

**Цель:** зафиксировать byte-identical baseline pilot endpoints, чтобы после рефактора убедиться: ноль регрессий.

- Подтвердить `cwd` prod: `pm2 describe autowarm | grep "exec cwd"` — должен быть `/root/.openclaw/workspace-genri/autowarm/` (правило `feedback_pm2_dump_path_drift.md`).
- Подтвердить чистоту репо:
  ```bash
  cd /root/.openclaw/workspace-genri/autowarm/
  git status
  git log --oneline -3
  ```
- Создать ветку для этапа 2 (внутри prod-репо — auto-push в GenGo2/delivery-contenthunter):
  ```bash
  git checkout -b feature/paginated-tables-etap2-20260428
  ```
- Сохранить cookie от UI (без креденшлов): `--cookie-jar` в `/tmp/_paginated2_cookie.txt`. Использовать тот же подход, что в pilot smoke (`paginated-tables-pilot.md` Task 3 Step 1).
- Снять baseline'ы (по одному вызову на каждый):
  - `curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/tasks' > /tmp/_baseline_tasks_legacy.json`
  - `curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/tasks?limit=20&sort=id&order=desc' > /tmp/_baseline_tasks_paginated.json`
  - `curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/tasks/stats' > /tmp/_baseline_tasks_stats.json`
  - `curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/tasks/by-ids?ids=1,2,3' > /tmp/_baseline_tasks_byids.json`
  - `curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/queue' > /tmp/_baseline_queue_legacy.json`
- Лог-инвариант: каждая baseline-команда в evidence-файл `paginated-tables-etap2-20260428.md` с MD5 и счётчиком записей.

**Лог:** `[etap2/baseline] endpoint=<x> rows=<n> md5=<...>`

#### T2. Извлечь cursor-helpers в `paginate.js`

**Файл:** новый `/root/.openclaw/workspace-genri/autowarm/paginate.js`

**Содержимое (минимум):**
```js
// paginate.js — server-side cursor pagination utilities
// Used by /api/publish/tasks, /api/publish/queue, и будущими endpoint'ами этапа 3.

function encodeCursor(sortValue, id, sortKey) {
  const payload = JSON.stringify({ v: sortValue, id, sk: sortKey });
  return Buffer.from(payload, 'utf8').toString('base64url');
}

function decodeCursor(cursor) {
  if (!cursor) return null;
  try {
    const json = Buffer.from(cursor, 'base64url').toString('utf8');
    const obj = JSON.parse(json);
    if (typeof obj !== 'object' || obj === null || !('v' in obj) || !('id' in obj)) return null;
    if (!Number.isInteger(obj.id)) return null;
    const vt = typeof obj.v;
    if (obj.v !== null && vt !== 'string' && vt !== 'number' && vt !== 'boolean') return null;
    if (typeof obj.sk !== 'string') return null;
    return obj;
  } catch {
    return null;
  }
}

/**
 * Сборка SQL для cursor-paginated запроса.
 *
 * @param {object} cfg
 * @param {string} cfg.table — имя таблицы (whitelist на стороне caller)
 * @param {object} cfg.sortWhitelist — { sortKey: { col: '<sql_col>', type: 'number'|'string'|'datetime' } }
 * @param {string} cfg.sortKey — выбранный ключ (один из sortWhitelist)
 * @param {'asc'|'desc'} cfg.order
 * @param {object|null} cfg.cursor — результат decodeCursor() (или null)
 * @param {number} cfg.limit — page size (1..200)
 * @param {Array<{sql:string,params:any[]}>} cfg.filters — массив { sql: 'col = $X', params: [...] } применяется в WHERE через AND
 * @returns { sql, params, sortCol }
 */
function buildPaginatedQuery({ table, sortWhitelist, sortKey, order, cursor, limit, filters }) {
  // ... validation + параметрический запрос, sort-key from whitelist; tie-breaker по id
}

/**
 * Сборка stats-запроса (counts по status + total) с теми же фильтрами.
 */
function buildStatsQuery({ table, statusCol, filters }) { ... }

/**
 * Сборка by-ids запроса с теми же фильтрами + WHERE id IN (...).
 */
function buildByIdsQuery({ table, sortWhitelist, sortKey, order, ids, filters }) { ... }

module.exports = { encodeCursor, decodeCursor, buildPaginatedQuery, buildStatsQuery, buildByIdsQuery };
```

**Принцип:** helper НЕ знает про конкретные эндпоинты. Caller передаёт `table`, `sortWhitelist`, `filters` как параметризованные SQL-фрагменты. Helper не делает query-execution — возвращает `{sql, params}`. Это сохраняет существующий паттерн в `server.js` (где `pool.query(sql, params)` уже в caller'е).

**Step 1:** Создать файл с полным телом (см. выше + полное тело `buildPaginatedQuery/Stats/ByIds`). **Содержимое сборщиков** — портировать существующую SQL-сборку из текущих handler'ов в `server.js:1862-2045`. Сохранить ту же логику параметризации (`$1, $2, ...`).

**Step 2:** Добавить тесты `paginate.test.js` (Node native test runner, не нужен Jest — у проекта нет node-test setup'а):
```js
const { test } = require('node:test');
const assert = require('node:assert');
const { encodeCursor, decodeCursor, buildPaginatedQuery, buildStatsQuery, buildByIdsQuery } = require('./paginate');

test('encode/decode roundtrip', () => {
  const c = encodeCursor('2026-04-28', 42, 'created_at');
  const d = decodeCursor(c);
  assert.deepStrictEqual(d, { v: '2026-04-28', id: 42, sk: 'created_at' });
});

test('decode rejects malformed', () => {
  assert.strictEqual(decodeCursor(''), null);
  assert.strictEqual(decodeCursor('not_base64!'), null);
  assert.strictEqual(decodeCursor(Buffer.from('{"x":1}', 'utf8').toString('base64url')), null);
});

test('decode rejects non-int id', () => {
  const bad = Buffer.from(JSON.stringify({ v: 1, id: 'string', sk: 'id' }), 'utf8').toString('base64url');
  assert.strictEqual(decodeCursor(bad), null);
});

test('buildPaginatedQuery — id desc, no cursor, no filters', () => {
  const r = buildPaginatedQuery({
    table: 'publish_tasks',
    sortWhitelist: { id: { col: 'id', type: 'number' } },
    sortKey: 'id',
    order: 'desc',
    cursor: null,
    limit: 100,
    filters: [],
  });
  assert.match(r.sql, /FROM publish_tasks/);
  assert.match(r.sql, /ORDER BY id DESC/);
  assert.match(r.sql, /LIMIT \$1/);
  assert.deepStrictEqual(r.params, [101]);  // limit + 1 для has_more detection
});

test('buildPaginatedQuery — created_at desc + cursor + filter status', () => {
  const cursorObj = decodeCursor(encodeCursor('2026-04-28T10:00:00Z', 50, 'created_at'));
  const r = buildPaginatedQuery({
    table: 'publish_tasks',
    sortWhitelist: { created_at: { col: 'created_at', type: 'datetime' } },
    sortKey: 'created_at',
    order: 'desc',
    cursor: cursorObj,
    limit: 50,
    filters: [{ sql: 'status = $X', params: ['running'] }],
  });
  assert.match(r.sql, /\(created_at, id\) < \(\$\d+, \$\d+\)/);
  assert.match(r.sql, /status = \$\d+/);
  assert.deepStrictEqual(r.params.slice(-1), [51]);  // limit last
});

test('buildStatsQuery — group by status + total', () => {
  const r = buildStatsQuery({
    table: 'publish_tasks',
    statusCol: 'status',
    filters: [{ sql: 'platform = $X', params: ['instagram'] }],
  });
  assert.match(r.sql, /GROUP BY status/);
  assert.deepStrictEqual(r.params, ['instagram']);
});

test('buildByIdsQuery — WHERE id IN (...)', () => {
  const r = buildByIdsQuery({
    table: 'publish_tasks',
    sortWhitelist: { id: { col: 'id', type: 'number' } },
    sortKey: 'id',
    order: 'desc',
    ids: [1, 2, 3],
    filters: [],
  });
  assert.match(r.sql, /id = ANY\(\$\d+\)/);
  assert.deepStrictEqual(r.params[0], [1, 2, 3]);
});
```

**Step 3:** Запустить тесты:
```bash
cd /root/.openclaw/workspace-genri/autowarm/
node --test paginate.test.js
```
Все тесты должны быть зелёные. Если падает — править helper, не тест.

**Лог при выполнении смок'а:** `[paginate/test] passed=N total=M` (вывод `node --test`).

**Файлы:** create `paginate.js`, `paginate.test.js`. Не править `server.js` пока — это T3.

#### T3. Переписать pilot endpoints через `paginate.js`

**Файл:** `server.js` (modify), строки 28-52 (старые helpers) и 1862-2045 (3 endpoint'а).

**Step 1:** В начале файла (где сейчас inline `encodeCursor`/`decodeCursor`) заменить на:
```js
const { encodeCursor, decodeCursor, buildPaginatedQuery, buildStatsQuery, buildByIdsQuery } = require('./paginate');
```
Удалить старые inline-определения (строки 28-52).

**Step 2:** В `app.get('/api/publish/tasks'` (1862-1973):
- Сохранить весь preprocessing (parse query params, validate sort key через whitelist, validate cursor через `decodeCursor`).
- Заменить inline-сборку SQL на вызов `buildPaginatedQuery({table:'publish_tasks', sortWhitelist:PUBLISH_TASKS_SORT_WHITELIST, sortKey, order, cursor:cursorObj, limit, filters:builtFilters})`.
- Сохранить backwards-compat блок (если без limit/cursor — вернуть массив).
- Сохранить логирование `[publish/tasks]`.

**Step 3:** В `app.get('/api/publish/tasks/stats'` (1975-2004) — тот же паттерн через `buildStatsQuery`.

**Step 4:** В `app.get('/api/publish/tasks/by-ids'` (2006-2045) — через `buildByIdsQuery`.

**Step 5:** `pm2 reload autowarm` (zero-downtime). Если пилот сломается — pm2 reload откатить через `git stash` и повторный reload.

**Step 6:** Smoke — повторить все curl из T1 и сравнить результаты с baseline'ами:
```bash
for f in tasks_legacy tasks_paginated tasks_stats tasks_byids; do
  curl -s -b /tmp/_paginated2_cookie.txt "http://localhost:3000/...соответствующий URL..." > /tmp/_after_${f}.json
  diff /tmp/_baseline_${f}.json /tmp/_after_${f}.json && echo "$f OK" || echo "$f REGRESSION"
done
```
Все 4 — `OK`. Если хоть один `REGRESSION` — править refactor, не двигаться к T4.

**Edge:** `next_cursor` зависит от `Date.now()` в курсоре? Нет (cursor — из row data, deterministic). Diff должен совпасть, если данные не менялись между baseline и after. Если меняются (живая БД) — выдержать минимум: повторить baseline снимок + after сразу друг за другом, и сравнить структуру (`jq 'keys, .rows[0] | keys'`), а не полный diff.

**Лог:** `[publish/tasks][refactor] sort=<x> filters=<...> rows=<n> next_cursor=<...>`

**Файлы:** modify `server.js`. **Не править** frontend в этом таске.

#### T4. EXPLAIN /api/publish/queue + index decision

**Цель:** убедиться, что cursor-pagination на `publish_queue` (или `publishing_queue` или как там реально называется таблица) использует индекс по дефолтной сортировке.

**Step 1:** Найти текущую SQL'ю `/api/publish/queue` (server.js:1453-1494). Зафиксировать дефолтную сортировку (если `ORDER BY` отсутствует — это проблема, нужно решить дефолт; pilot использовал `id DESC`).

**Step 2:** Запустить `EXPLAIN ANALYZE` для типичных вариантов:
```sql
-- через psql openclaw user/db (memory: openclaw:openclaw123@localhost:5432)
EXPLAIN ANALYZE SELECT * FROM publish_queue ORDER BY id DESC LIMIT 100;
EXPLAIN ANALYZE SELECT * FROM publish_queue WHERE status='running' ORDER BY id DESC LIMIT 100;
EXPLAIN ANALYZE SELECT * FROM publish_queue WHERE platform='instagram' ORDER BY created_at DESC LIMIT 100;
EXPLAIN ANALYZE SELECT * FROM publish_queue WHERE (created_at, id) < ('2026-04-28T10:00:00Z', 50) ORDER BY created_at DESC, id DESC LIMIT 100;
```
Записать вывод в evidence.

**Step 3:** Решение по индексам:
- Если `Seq Scan` на таблице >5k строк и есть Filter — обсудить.
- Если `Index Scan using publish_queue_pkey` на дефолтной — индекс ОК.
- Для `(created_at, id)` cursor-pagination нужен композитный индекс `(created_at DESC, id DESC)` — добавить **только если** EXPLAIN показывает Sort + Seq Scan на >5k строк.

**Step 4:** Если индексы нужны — отдельный SQL-файл `migrations/<timestamp>_publish_queue_paginate_indexes.sql` с `CREATE INDEX ... CONCURRENTLY`. Применить вручную через psql (memory: code-сценаристы пишут миграцию, applied — на этом проекте через прямой psql).

**Лог:** `[etap2/explain] sort=<x> filters=<y> plan=<one-line>`

**Файлы:** evidence-секция `EXPLAIN`. Опционально — `migrations/*.sql`.

#### T5. Cursor-pagination для `/api/publish/queue`

**Файл:** `server.js:1453-1494`

**Step 1:** Объявить sort-whitelist для queue (по аналогии с `PUBLISH_TASKS_SORT_WHITELIST`):
```js
const PUBLISH_QUEUE_SORT_WHITELIST = {
  id: { col: 'id', type: 'number' },
  created_at: { col: 'created_at', type: 'datetime' },
  // + что было на фронте: status, platform, device — добавить если EXPLAIN ОК
};
```

**Step 2:** Переписать handler:
- Парсинг query params: `status`, `platform`, `device` (старые), плюс новые `limit`, `cursor`, `sort`, `order`, `search`, `status_exclude` (если применимо).
- **Backwards-compat блок**: если ни `limit`, ни `cursor` не пришли — отдать legacy (flat array LIMIT 500). Это позволит сделать pm2 reload между backend и frontend без сломанной фронт-страницы.
- Иначе — `buildPaginatedQuery`, выполнить, вернуть `{rows, next_cursor, has_more}`.

**Step 3:** Логирование: `[publish/queue] mode=<legacy|paginated> filters=<...> rows=<n>`.

#### T6. `/api/publish/queue/stats` endpoint

**Файл:** `server.js` — новый handler сразу после `/api/publish/queue`.

**Step 1:** Реализовать через `buildStatsQuery({ table: 'publish_queue', statusCol: 'status', filters: builtFilters })`. Ответ: `{total, by_status: {...}}`.

**Step 2:** Сохранить совпадение фильтров с основным endpoint'ом — это правило spec § 3.2.

#### T7. `/api/publish/queue/by-ids` endpoint (опционально)

**Решение:** реализуем, если в T11 решим включать `liveRefresh: true` для queue. Если queue — статичная очередь (новые записи появляются редко), live-refresh не нужен → пропускаем T7. Решаем по итогу T8 (Phase 2 кикоффа: посмотрим, как часто меняются строки в queue в проде).

Если нужен — реализовать через `buildByIdsQuery`.

#### T8. Smoke `/api/publish/queue`

**Step 1:** Snapshot legacy (без params) ДО refactor'а уже снят в T1 (`/tmp/_baseline_queue_legacy.json`). После T5 — повторить и сравнить (должен совпадать byte-to-byte).

**Step 2:** Snapshot paginated:
```bash
curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/queue?limit=20&sort=id&order=desc' | jq '.rows | length, .has_more, (.next_cursor | length)'
# expected: 20, true, >0
```

**Step 3:** Smoke `/stats` + matching фильтр:
```bash
curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/queue/stats' | jq '.total, .by_status'
curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/queue/stats?status=running' | jq
```

**Step 4:** Cursor pagination — 2-я страница:
```bash
NEXT=$(curl -s -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/queue?limit=20' | jq -r '.next_cursor')
curl -s -b /tmp/_paginated2_cookie.txt "http://localhost:3000/api/publish/queue?limit=20&cursor=$NEXT" | jq '.rows | length'
# expected: 20 (или меньше если хвост)
```

**Step 5:** Negative — invalid cursor:
```bash
curl -i -b /tmp/_paginated2_cookie.txt 'http://localhost:3000/api/publish/queue?limit=20&cursor=invalid_cursor_string'
# expected: 400 или ignore + первая страница (синхронизировать поведение с pilot — он возвращает 400)
```

#### T9. Commit Phase 1

```
git add paginate.js paginate.test.js server.js
git commit -m "refactor(server): extract paginate.js + apply to /api/publish/tasks
                                                                                
+ /api/publish/queue cursor pagination via the new helper. Pilot endpoints
unchanged in behavior (verified via baseline diff). Follows spec §6 etap 2."
```

⚠️ Auto-push hook → GenGo2/delivery-contenthunter. Это нормально — ветка не merged.

### Phase 2 — Frontend: extract + pilot rewrite + queue migration

#### T10. Извлечь pilot UI-логику в `paginated-table.js`

**Файл:** новый `/root/.openclaw/workspace-genri/autowarm/public/paginated-table.js`

**API factory** (по spec § 4.3):
```js
window.createPaginatedTable = function(config) {
  // config = {
  //   tableId,                              // 'upt' / 'upq' / etc — для namespacing event'ов и DOM ids
  //   endpoints: { list, stats, byIds },    // null если фича не нужна
  //   tbodyId,                              // 'upt-tbody'
  //   sentinelId,                           // 'upt-sentinel'
  //   pageSize, maxAutoLoadPages,
  //   defaultSort: { key, order },
  //   filters: { /* state schema */ },
  //   renderRow(row),                       // (row) => '<tr>...</tr>'
  //   onStats(stats),                       // (optional) callback для UI counters
  //   liveRefresh: true|false,              // включает 15-сек polling по /by-ids
  // };
  //
  // returns { reset(), reload(), setFilter(k,v), setSort(k,o), refreshVisibleRows(), destroy() }
};
```

**Step 1:** Создать файл, портировать `_uptState`, `loadPublishTasks`, `uptResetAndLoad`, `fetchPublishTasksStats`, `uptInitObserver`, `uptStartPolling`, `refreshPublishTaskRows`, `uptRenderRows`, debounce-логику, IntersectionObserver, visibility handler. Заменить hard-coded `_uptState` на `instance.state`, hard-coded endpoints на `config.endpoints.*`, hard-coded DOM ids на `config.tbodyId`/`sentinelId`.

**Step 2:** Подключить в `index.html` через `<script src="/paginated-table.js"></script>` **перед** основным inline-кодом таблиц.

**Step 3:** Логирование внутри factory: `[pt:${config.tableId}] event=<x>` (например, `[pt:upt] event=load_page page=2 rows=100 has_more=true`).

#### T11. Переписать pilot UI на `createPaginatedTable`

**Файл:** `index.html` — большой блок 10544..~11000.

**Step 1:** Создать instance:
```js
const _uptTable = createPaginatedTable({
  tableId: 'upt',
  endpoints: { list: '/api/publish/tasks', stats: '/api/publish/tasks/stats', byIds: '/api/publish/tasks/by-ids' },
  tbodyId: 'upt-tbody',
  sentinelId: 'upt-sentinel',
  pageSize: 100,
  maxAutoLoadPages: 5,
  defaultSort: { key: 'id', order: 'desc' },
  filters: { /* ... */ },
  renderRow: uptRenderRow,                  // вынесем как отдельную функцию
  onStats: uptApplyStats,                   // обновляет counters в шапке таба
  liveRefresh: true,
});
```

**Step 2:** Удалить старые `_uptState`, `loadPublishTasks`, `uptResetAndLoad`, `fetchPublishTasksStats`, `uptInitObserver`, `uptStartPolling`, `refreshPublishTaskRows` — остаются только привязки к UI (DOM input handlers → `_uptTable.setFilter(...)`, sort-headers → `_uptTable.setSort(...)`, кнопка «🔄 Обновить» → `_uptTable.reset()`).

**Step 3:** `uptRenderRow(row)` — отдельная функция (вынести из старой `uptRenderRows()`). Принимает 1 row, возвращает `<tr>...`.

**Step 4:** `uptApplyStats(stats)` — обновляет DOM counters.

**Step 5:** Browser smoke (после T15 коммита и pm2 reload — но локально проверить через DevTools после `pm2 reload`):
- Tasks tab открывается → стартовая страница 100 строк.
- Скролл вниз → подгрузка ещё страницы.
- Фильтр платформы → reset + новая первая страница только Instagram.
- Сортировка по created_at → reset + новый порядок.
- Polling: открыть DevTools → Network, через 10с — запрос к `/stats`; через 15с — `/by-ids`.
- Visibility: переключить таб → polling приостанавливается (нет запросов); вернуть → возобновляется.

#### T12. Cursor-pagination для UI `/publishing/queue`

**Файл:** `index.html` — блок ~10987..11200 (`loadUnifiedPublish`, `_upAll`, `upRenderRows`).

**Step 1:** Добавить sentinel-row перед `</tbody>` queue-таблицы:
```html
<tr id="upq-sentinel"><td colspan="N" style="text-align:center;color:#888">Загрузка...</td></tr>
```
(N = количество колонок. Найти текущий header tr и посчитать.)

**Step 2:** Создать instance:
```js
const _upqTable = createPaginatedTable({
  tableId: 'upq',
  endpoints: { list: '/api/publish/queue', stats: '/api/publish/queue/stats', byIds: null /* или /by-ids если T7 сделан */ },
  tbodyId: '<id queue-tbody>',
  sentinelId: 'upq-sentinel',
  pageSize: 100,
  maxAutoLoadPages: 5,
  defaultSort: { key: 'id', order: 'desc' },
  filters: { status: '', platform: '', device: '', date_from: '', date_to: '' },
  renderRow: upqRenderRow,
  onStats: upqApplyStats,
  liveRefresh: false,                       // решено в T7
});
```

**Step 3:** Удалить `_upAll`, `_upSort`, `_upSortDir`, `_upColFilters`, `_upShowDone`, client-side `upSort`/`upFilter`. Привязать DOM handlers к `_upqTable.setFilter`/`setSort`.

**Step 4:** `upqRenderRow(row)` — отдельная функция (вынести логику отрисовки строки из `upRenderRows`).

**Step 5:** Browser smoke (golden path + 3 edge cases):
- Queue tab открывается → 100 строк, скролл подгружает следующую.
- Фильтр платформы → reset + новая первая.
- Date_from filter → reset + урезанный набор.
- Filter с пустым результатом → таблица пустая, "Загрузка..." исчезает.
- pm2 reload между phase 1 (backend) и phase 2 (frontend) — UI на старом коде должен работать (legacy без `limit`/`cursor` отдаёт array из `app.get('/api/publish/queue')`). Если кто-то нажал «Обновить» — UI не должен сломаться.

#### T13. Commit Phase 2

```
git add public/paginated-table.js public/index.html
git commit -m "refactor(ui): paginated-table.js factory + apply to /publishing/tasks + /publishing/queue

Pilot UI (/publishing/tasks) переведено на factory без регрессии (verified в браузере).
Queue UI (/publishing/queue) — впервые на cursor-pagination, sentinel + IntersectionObserver."
```

### Phase 3 — Deploy + evidence

#### T14. Deploy validation

**Step 1:** `pm2 reload autowarm` (zero-downtime). Подождать 10с, проверить статус: `pm2 describe autowarm | grep -E "status|uptime|restart"`. Restart counter — увеличился ровно на 1.

**Step 2:** `pm2 logs autowarm --lines 50` — нет `Error`/`Cannot find module`/`SyntaxError`. Если есть — rollback (`git revert HEAD~3..HEAD` + reload).

**Step 3:** Production smoke в браузере: <https://delivery.contenthunter.ru/publishing> — открыть все 2 tab'а, проверить infinite scroll, фильтры, сортировку. Через 15с — глянуть Network на `/by-ids` (если включён live-refresh).

**Step 4:** Если всё ок — auto-push hook уже отработал (post-commit). Проверить:
```bash
cd /root/.openclaw/workspace-genri/autowarm/
git log --oneline origin/feature/paginated-tables-etap2-20260428..HEAD
# expected: пусто (всё запушено)
```

**Step 5:** Слить ветку → main:
```bash
git checkout main
git pull origin main
git merge --no-ff feature/paginated-tables-etap2-20260428
# auto-push hook отработает
```

#### T15. Evidence + memory

**Файл:** `.ai-factory/evidence/paginated-tables-etap2-20260428.md` (в `contenthunter` repo).

**Содержимое:**
- Контекст (этап 2 после pilot этапа 1).
- T1 baseline'ы (md5 + record counts).
- EXPLAIN решение из T4.
- Commit-ссылки (3 commit'а: phase 1, phase 2, deploy если нужен).
- Smoke-результаты (T3, T8, T11, T12).
- Скриншоты (если делаем) — `/tmp/etap2_screenshots/`.
- Итоги: что отгружено, что в follow-up'ах (testbench backport, etap 3).

**Memory update:** расширить `~/.claude/projects/-home-claude-user-contenthunter/memory/project_paginated_tables_pilot.md`:
- Имя обновить на `Paginated tables — pilot ✅ + etap 2 ✅`.
- Добавить:
  - Helper модули: `paginate.js` (Node), `paginated-table.js` (browser).
  - Endpoints этапа 2: `/api/publish/queue` (cursor + stats + опционально by-ids).
  - Pattern для новых таблиц (этап 3): `require('./paginate')` + `createPaginatedTable({...})`.
  - Backport в testbench — open follow-up если будет нужен.

**Файлы:** create evidence, update memory.

#### T16. Plan/evidence commit в `contenthunter`

```bash
cd /home/claude-user/contenthunter/
git add .ai-factory/plans/2026-04-28-paginated-tables-etap2.md
git add .ai-factory/evidence/paginated-tables-etap2-20260428.md
git commit -m "docs(plans+evidence): paginated-tables etap 2 — extract helper + queue migration"
```

⚠️ **НЕ пушим в main contenthunter** — оставить локально (ветка `fix/testbench-publisher-base-imports-20260427`), как в pilot'е. Решение про merge — отдельно.

## Commit Plan

| После | Repo | Сообщение |
|---|---|---|
| T9 | `delivery-contenthunter` (prod, ветка `feature/paginated-tables-etap2-20260428`) | `refactor(server): extract paginate.js + apply to /api/publish/tasks` |
| T13 | то же | `refactor(ui): paginated-table.js factory + apply to /publishing/tasks + /publishing/queue` |
| T14 | то же, на main | merge --no-ff (опционально, если решили мержить сразу) |
| T16 | `contenthunter` (текущая ветка) | `docs(plans+evidence): paginated-tables etap 2 — extract helper + queue migration` |

## Out of scope (явно)

1. Backport pilot+etap 2 в `autowarm-testbench` (отдельный follow-up; testbench и так лагает на pilot).
2. Этап 3 — раскатка на 7 таблиц (отдельный плана-файл, отдельные PR'ы).
3. WebSocket / SSE.
4. Виртуальный скроллинг (только если будет проблема производительности на >2000 видимых строк).
5. Helper versioning (v1/v2 файлы).
6. Перевод pilot/queue на TypeScript.

## Риски и митигации

| Риск | Митигация |
|---|---|
| Refactor pilot вносит регрессию (потеряется фильтр/сортировка/курсор) | T1 baseline + T3 Step 6 byte-diff. Если diff не нулевой — править refactor, не двигаться к T4 |
| `paginated-table.js` факторизация теряет live-refresh поведение pilot'а | T11 Step 5 проверяет polling в DevTools (10с stats + 15с by-ids) |
| pm2 reload между Phase 1 и Phase 2 ломает старый фронт | Backwards-compat: legacy без `limit`/`cursor` → array. T8 Step 1 это проверяет |
| EXPLAIN покажет Seq Scan на queue → cursor-pagination медленнее legacy | T4 Step 4 — добавить индекс отдельной миграцией ДО релиза T5 |
| Auto-push hook пушит half-broken state | Phase 1 и Phase 2 — каждая закрывается «зелёным» smoke'ом ДО следующей |
| `factory_pack_accounts` (или другая таблица queue) меняется чаще, чем ожидаем — диффы baseline нестабильны | T1 — снимок + after сразу, или сравнивать `jq` структуру вместо byte-diff |

## Notes для исполнителя (`/aif-implement`)

- Каждое `pm2 reload autowarm` сопровождается smoke'ом из соответствующего таска. Без зелёного smoke'а — не двигаться к следующему таску.
- Логирование verbose — сохраняет debug-возможность, ничего не вычёркиваем после стабилизации в этом этапе. Если объём логов будет проблемой — будем фильтровать в этапе 3.
- **Не править PLAN.md** в `contenthunter` — соседние сессии могут пишут туда (правило `feedback_plan_full_mode_branch.md`).
- Если что-то развалится, evidence-файл — единый источник истины. Записываем туда сразу как сломалось, до фикса.
