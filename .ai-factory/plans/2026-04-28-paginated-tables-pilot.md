# Paginated Tables Pilot — Publishing/Tasks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести страницу `/publishing/tasks` на cursor-based бесконечную ленту с серверными фильтрами, сортировкой, поиском, агрегированной статистикой и точечным обновлением загруженных строк.

**Architecture:** Три серверных endpoint'а в `server.js` (`GET /api/publish/tasks` cursor-based, `/stats`, `/by-ids`). Фронт переписан с `_uptAll` на `_uptState`, IntersectionObserver на sentinel-строке, polling stats каждые 10с, polling row-refresh каждые 15с. Никакой преждевременной абстракции — helper выводим во второй итерации (см. spec § 6).

**Spec:** `.ai-factory/specs/2026-04-28-paginated-tables-design.md`

**Tech Stack:** Node.js + Express (`server.js`), PostgreSQL (`pg`), HTML/JS (vanilla, в `public/index.html`), Tailwind для стилей.

**Repo:** Реализация в `/root/.openclaw/workspace-genri/autowarm/` (auto-push hook → `GenGo2/delivery-contenthunter`). PM2 для рестарта.

**Test approach:** В этом проекте нет автоматических тестов для HTTP endpoint'ов. Используем curl как «тест» — каждый шаг с очевидной серверной логикой проверяется curl'ом до и после изменения. Фронт-изменения проверяем в браузере на конкретных сценариях, описанных в задаче 14.

---

## Файловая структура

**Modify:**
- `/root/.openclaw/workspace-genri/autowarm/server.js`:
  - ~line 1780–1802 — переписать `GET /api/publish/tasks`
  - ~line 1802 (после) — добавить два новых endpoint'а: `/stats` и `/by-ids`
  - top of file — мини-helpers `encodeCursor`/`decodeCursor` (несколько строк, оставляем inline; вынесем в отдельный файл во втором этапе)

- `/root/.openclaw/workspace-genri/autowarm/public/index.html`:
  - ~line 2369 — добавить `<tr id="upt-sentinel">` в конец `<tbody id="upt-tbody">`
  - ~line 10544 — заменить state-переменные `_uptAll/_uptSort/_uptSortDir/_uptColFilters` на единый объект `_uptState`
  - ~line 10599–10612 — переписать `uptSort` и `uptColFilter` на server-side reset+reload
  - ~line 10627–10712 — переписать `uptRenderRows` — теперь только рендеринг ленты (без фильтрации/сортировки в JS)
  - ~line 10714–10734 — переписать `loadPublishTasks` под cursor + добавить `loadMorePublishTasks`, `fetchPublishTasksStats`, `refreshPublishTaskRows`
  - ~line 10583, 10710, 10876 — точки, где `loadPublishTasks` вызывался для refresh после действия — заменить на точечный `/by-ids?ids=<id>`

**Не модифицируем в pilot'е:**
- Логику queue tab (`loadUnifiedPublish`, `_upAll`, `upRenderRows`, `upSort`, `upColFilter`, `_upShowDone`).
- Markup строки задачи (тело `uptRenderRows` для одной строки) — копируем 1-в-1 в новую функцию `uptRenderRow(row) → string`.
- Любые другие endpoint'ы в server.js.

---

## Task 1: Подготовка — отдельная ветка в autowarm prod

Текущий рабочий каталог `/root/.openclaw/workspace-genri/autowarm/` имеет auto-push hook (commit → push в `GenGo2/delivery-contenthunter`). Работаем на отдельной ветке, чтобы не сваливать в main недо-готовый pilot.

**Files:** none

- [ ] **Step 1: Проверить чистоту дерева autowarm**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git status
git log --oneline -5
```

Если есть незакоммиченные изменения — остановиться и разобраться (это может быть работа другой Claude-сессии). Если чисто — двигаемся.

- [ ] **Step 2: Создать ветку для pilot**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git fetch origin
git checkout -b feat/paginated-publish-tasks-20260428
```

- [ ] **Step 3: Подтвердить, что pm2 запущен и сервер отвечает**

```bash
pm2 status
curl -sS -o /dev/null -w "%{http_code}\n" https://delivery.contenthunter.ru/api/publish/tasks
```

Ожидаем `200` (или `401/302` если требуется auth — это нормально, главное что сервер живой). Если `5xx` или таймаут — разобраться до начала работ.

---

## Task 2: Cursor-encoding helpers

Маленькие чистые функции, без зависимостей. Размещаем в начале `server.js` (после imports), помечаем комментарием как «cursor pagination utilities (extracted to module in iteration 2)» — чтобы было понятно, что это временно inline.

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js` (после блока imports / перед первым `app.use`)

- [ ] **Step 1: Найти место для вставки helper'ов**

```bash
grep -n "^app\.\|^const app" /root/.openclaw/workspace-genri/autowarm/server.js | head -3
```

Запомнить строку первого `app.use` или `app.get` — helpers вставляем **перед** ней.

- [ ] **Step 2: Вставить cursor helpers**

```js
// === Cursor pagination utilities (inline; extracted to ./paginate.js in iteration 2) ===

function encodeCursor(sortValue, id) {
  const payload = JSON.stringify({ v: sortValue, id });
  return Buffer.from(payload, 'utf8').toString('base64url');
}

function decodeCursor(cursor) {
  if (!cursor) return null;
  try {
    const json = Buffer.from(cursor, 'base64url').toString('utf8');
    const obj = JSON.parse(json);
    if (typeof obj !== 'object' || obj === null || !('v' in obj) || !('id' in obj)) return null;
    if (!Number.isInteger(obj.id)) return null;
    return obj;
  } catch {
    return null;
  }
}
```

- [ ] **Step 3: Smoke-проверка через node -e (быстрый sanity)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
node -e "
  const f = require('./server.js'); // НЕ запустится, server.js слушает порт. Альтернатива:
"
```

Альтернативный способ без поднятия сервера:

```bash
node -e "
  const enc = (v, id) => Buffer.from(JSON.stringify({v, id}),'utf8').toString('base64url');
  const dec = (c) => { try { return JSON.parse(Buffer.from(c,'base64url').toString('utf8')); } catch { return null; } };
  const c = enc(1234, 567);
  console.log('encoded:', c);
  console.log('decoded:', dec(c));
"
```

Ожидаем: `decoded: { v: 1234, id: 567 }`.

- [ ] **Step 4: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add server.js
git commit -m "feat(server): add cursor encode/decode helpers for paginated endpoints"
```

⚠️ После коммита auto-push hook запушит ветку на remote — это нормально, ветка не merged.

---

## Task 3: Переписать GET /api/publish/tasks на cursor + filters + sort

Главный backend endpoint. Сохраняем исходные JOIN'ы, добавляем cursor + whitelisted filters/sort + LIMIT+1 для `has_more`.

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js:1780-1802`

- [ ] **Step 1: Зафиксировать baseline curl-ответ старого endpoint'а**

```bash
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks' \
  | jq 'length, .[0] | keys' 2>&1 | head -20
```

Сохранить количество строк и список полей (нужно будет проверить, что после переделки набор полей не изменился).

⚠️ Если `requireAuth` — нужны cookies. Получить их можно из браузерной DevTools (Network → копировать cookie) и сохранить в `/tmp/dc-cookies.txt` в формате `Cookie: session=...`. В любом случае, формат ответа должен быть **массив объектов с теми же полями**.

- [ ] **Step 2: Заменить endpoint на новую реализацию**

Удалить блок `app.get('/api/publish/tasks', requireAuth, ...)` (строки 1780–1802) и заменить на:

```js
// GET /api/publish/tasks — cursor-based pagination + server-side filters/sort
// Spec: .ai-factory/specs/2026-04-28-paginated-tables-design.md
const PUBLISH_TASKS_SORT_WHITELIST = {
  id:           'pt.id',
  created_at:   'pt.created_at',
  updated_at:   'pt.updated_at',
  scheduled_at: 'pq.scheduled_at',
  status:       'pt.status',
  platform:     'pt.platform',
  device_serial:'pt.device_serial',
};

function buildPublishTasksFilters(query) {
  // Возвращает { whereSql, params } — индексы плейсхолдеров начинаются с 1.
  const conds = [];
  const params = [];
  const push = (sql, val) => { params.push(val); conds.push(sql.replace('$?', '$' + params.length)); };

  // status: точное или CSV
  if (query.status) {
    const list = String(query.status).split(',').map(s => s.trim()).filter(Boolean);
    if (list.length === 1) push("pt.status = $?", list[0]);
    else if (list.length > 1) push("pt.status = ANY($?::text[])", list);
  }
  // status_exclude: CSV (для "скрыть выполненные")
  if (query.status_exclude) {
    const list = String(query.status_exclude).split(',').map(s => s.trim()).filter(Boolean);
    if (list.length) push("pt.status <> ALL($?::text[])", list);
  }
  if (query.platform)      push("pt.platform = $?",      String(query.platform));
  if (query.device_serial) push("pt.device_serial = $?", String(query.device_serial));
  if (query.pack_name) {
    push(`COALESCE(pq.pack_name,
                  (SELECT fpa2.pack_name FROM factory_pack_accounts fpa2
                   JOIN factory_device_numbers fdn2 ON fdn2.id = fpa2.device_num_id
                   WHERE fdn2.device_id = pt.device_serial LIMIT 1)) = $?`, String(query.pack_name));
  }
  if (query.search) {
    const s = `%${String(query.search).replace(/[%_]/g, m => '\\' + m)}%`;
    const i = params.length;
    params.push(s, s, s);
    conds.push(`(pt.caption ILIKE $${i+1} OR ut.input_video_name ILIKE $${i+2} OR pt.device_serial ILIKE $${i+3})`);
  }

  return { whereSql: conds.length ? 'WHERE ' + conds.join(' AND ') : '', params };
}

app.get('/api/publish/tasks', requireAuth, async (req, res) => {
  try {
    // === BACKWARDS-COMPAT: если клиент не передал ни limit, ни cursor —
    // отдаём старый формат (плоский массив, без пагинации, без фильтров),
    // чтобы существующий фронт не сломался между Task 3 и Task 8.
    // Удалить этот блок одновременно с этапом 2 (когда фронт переехал
    // на новый формат и больше не зовёт endpoint без параметров).
    const isLegacyCall = req.query.limit === undefined && req.query.cursor === undefined;
    if (isLegacyCall) {
      const { rows } = await pool.query(`
        SELECT pt.*,
               pq.media_url   AS s3_url,
               pq.scheduled_at AS pq_scheduled_at,
               COALESCE(pq.pack_name,
                 (SELECT fpa2.pack_name FROM factory_pack_accounts fpa2
                  JOIN factory_device_numbers fdn2 ON fdn2.id = fpa2.device_num_id
                  WHERE fdn2.device_id = pt.device_serial LIMIT 1)
               ) AS pack_name,
               fdn.device_number,
               COALESCE(ut.input_video_name, '') AS video_name
        FROM publish_tasks pt
        LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
        LEFT JOIN factory_device_numbers fdn ON fdn.device_id = pt.device_serial
        LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
        LEFT JOIN unic_tasks ut ON ut.id = ur.task_id
        ORDER BY pt.id DESC
      `);
      return res.json(rows);   // legacy shape: array
    }
    // === END BACKWARDS-COMPAT ===

    // 1. sort
    const sortKey = String(req.query.sort || 'id');
    const sortCol = PUBLISH_TASKS_SORT_WHITELIST[sortKey];
    if (!sortCol) return res.status(400).json({ error: 'invalid sort' });
    const order = (String(req.query.order || 'desc').toLowerCase() === 'asc') ? 'ASC' : 'DESC';
    const cmpOp = order === 'ASC' ? '>' : '<';

    // 2. limit
    let limit = parseInt(req.query.limit, 10);
    if (!Number.isInteger(limit) || limit < 1) limit = 100;
    if (limit > 500) limit = 500;

    // 3. cursor
    const cursor = decodeCursor(req.query.cursor);

    // 4. filters
    const { whereSql, params } = buildPublishTasksFilters(req.query);

    // 5. cursor clause: (sort_val, id) cmp (cursor.v, cursor.id)
    let cursorSql = '';
    if (cursor) {
      const i1 = params.length + 1, i2 = params.length + 2;
      cursorSql = (whereSql ? ' AND ' : 'WHERE ')
                + `(${sortCol}, pt.id) ${cmpOp} ($${i1}, $${i2})`;
      params.push(cursor.v, cursor.id);
    }

    // 6. limit + 1 for has_more detection
    params.push(limit + 1);
    const limitIdx = params.length;

    const sql = `
      SELECT pt.*,
             pq.media_url   AS s3_url,
             pq.scheduled_at AS pq_scheduled_at,
             COALESCE(pq.pack_name,
               (SELECT fpa2.pack_name FROM factory_pack_accounts fpa2
                JOIN factory_device_numbers fdn2 ON fdn2.id = fpa2.device_num_id
                WHERE fdn2.device_id = pt.device_serial LIMIT 1)
             ) AS pack_name,
             fdn.device_number,
             COALESCE(ut.input_video_name, '') AS video_name
      FROM publish_tasks pt
      LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
      LEFT JOIN factory_device_numbers fdn ON fdn.device_id = pt.device_serial
      LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
      LEFT JOIN unic_tasks ut ON ut.id = ur.task_id
      ${whereSql}
      ${cursorSql}
      ORDER BY ${sortCol} ${order}, pt.id ${order}
      LIMIT $${limitIdx}
    `;

    const { rows } = await pool.query(sql, params);
    const hasMore = rows.length > limit;
    const out = hasMore ? rows.slice(0, limit) : rows;
    let nextCursor = null;
    if (hasMore && out.length) {
      const last = out[out.length - 1];
      // sortKey может быть 'scheduled_at' (из pq) или 'id' (из pt) и т.п.
      // Используем то же имя, что и в SELECT (alias или поле):
      const sortValForCursor = sortKey === 'scheduled_at' ? last.pq_scheduled_at : last[sortKey];
      nextCursor = encodeCursor(sortValForCursor, last.id);
    }
    res.json({ rows: out, next_cursor: nextCursor, has_more: hasMore });
  } catch (e) {
    console.error('[GET /api/publish/tasks]', e);
    res.status(500).json({ error: e.message });
  }
});
```

✅ **Backwards-compat встроен** в начало handler'а: если клиент не передал `limit` и `cursor`, endpoint отдаёт старый формат (массив). Это значит, что pm2 reload между Task 3 и Task 8 безопасен — старый фронт продолжает работать. Backwards-compat блок будет удалён в этапе 2, когда фронт перестанет вызывать endpoint без параметров.

- [ ] **Step 3: pm2 reload и smoke (backwards-compat)**

```bash
pm2 reload all
sleep 1
# BC: запрос без новых параметров должен вернуть старый плоский массив
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks' | jq 'type'
```

Ожидаем: `"array"` (legacy shape сохранён). Если `"object"` — backwards-compat сломан, разобраться.

- [ ] **Step 3b: smoke с новыми параметрами**

```bash
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks?limit=5' | jq
```

Ожидаем:
- Поле `rows` — массив из 5 объектов
- Поле `has_more: true`
- Поле `next_cursor` — непустая base64-строка

- [ ] **Step 4: Smoke с курсором (2-я страница)**

```bash
CURSOR=$(curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks?limit=5' | jq -r '.next_cursor')
curl -sS -b /tmp/dc-cookies.txt "https://delivery.contenthunter.ru/api/publish/tasks?limit=5&cursor=$CURSOR" | jq '.rows | map(.id)'
```

Ожидаем: 5 ID, **отличных** от первой страницы (без пересечений), и каждый меньше last_id первой страницы (так как ORDER BY DESC).

- [ ] **Step 5: Smoke с фильтром**

```bash
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks?limit=10&status=done' | jq '.rows | map(.status) | unique'
```

Ожидаем: `["done"]`.

- [ ] **Step 6: Smoke с status_exclude**

```bash
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks?limit=10&status_exclude=done,skipped' | jq '.rows | map(.status) | unique'
```

Ожидаем: массив без `"done"` и без `"skipped"`.

- [ ] **Step 7: Smoke с поиском**

```bash
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks?limit=10&search=test' | jq '.rows | length'
```

Ожидаем: число (может быть 0). Главное — не 500 и не invalid sort.

- [ ] **Step 8: Negative tests**

```bash
# bad sort
curl -sS -o /dev/null -w "%{http_code}\n" -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks?sort=DROP_TABLE'
# expected: 400

# bad cursor (мусор)
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks?limit=5&cursor=not-base64-!!!' | jq 'has("rows")'
# expected: true (мусор интерпретируется как "нет курсора" — отдаём первую страницу)

# limit clamping
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks?limit=10000' | jq '.rows | length'
# expected: <= 500
```

- [ ] **Step 9: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add server.js
git commit -m "feat(api): publish/tasks cursor-based pagination + server-side filters/sort

When request has no 'limit'/'cursor' params, endpoint returns legacy array
format (backwards-compat for old frontend). With pagination params — new
{rows, next_cursor, has_more} shape. BC layer removed in iteration 2."
```

---

## Task 4: GET /api/publish/tasks/stats

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js` — добавить новый endpoint **сразу после** переписанного `/api/publish/tasks`.

- [ ] **Step 1: Добавить endpoint**

```js
app.get('/api/publish/tasks/stats', requireAuth, async (req, res) => {
  try {
    const { whereSql, params } = buildPublishTasksFilters(req.query);

    // НЕ применяем cursor — stats всегда считается по всему filtered-набору.
    const sql = `
      SELECT pt.status, COUNT(*) AS n
      FROM publish_tasks pt
      LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
      LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
      LEFT JOIN unic_tasks ut ON ut.id = ur.task_id
      ${whereSql}
      GROUP BY pt.status
    `;
    const { rows } = await pool.query(sql, params);

    const by_status = {};
    let total = 0;
    for (const r of rows) {
      const k = r.status || 'unknown';
      const n = parseInt(r.n, 10) || 0;
      by_status[k] = n;
      total += n;
    }
    res.json({ total, by_status });
  } catch (e) {
    console.error('[GET /api/publish/tasks/stats]', e);
    res.status(500).json({ error: e.message });
  }
});
```

- [ ] **Step 2: pm2 reload и smoke**

```bash
pm2 reload all
sleep 1
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks/stats' | jq
```

Ожидаем: `{ "total": <int>, "by_status": { "done": <int>, "failed": <int>, ... } }`. Значения — целые числа. `total` равен сумме всех `by_status`.

- [ ] **Step 3: Smoke с фильтром**

```bash
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks/stats?status=done' | jq
```

Ожидаем: `total` = `by_status.done`, других ключей нет.

- [ ] **Step 4: Sanity — total из stats совпадает с full COUNT**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc 'SELECT COUNT(*) FROM publish_tasks'
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks/stats' | jq '.total'
```

Числа должны совпадать.

- [ ] **Step 5: Commit**

```bash
git add server.js
git commit -m "feat(api): GET /api/publish/tasks/stats — server-side aggregation"
```

---

## Task 5: GET /api/publish/tasks/by-ids

Точечный refresh загруженных строк.

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js` — добавить **сразу после** `/stats`.

- [ ] **Step 1: Добавить endpoint**

```js
app.get('/api/publish/tasks/by-ids', requireAuth, async (req, res) => {
  try {
    // Парсим ids — CSV из integer'ов, max 500
    const raw = String(req.query.ids || '').split(',').map(s => s.trim()).filter(Boolean);
    const ids = raw.map(s => parseInt(s, 10)).filter(n => Number.isInteger(n));
    if (!ids.length) return res.json({ rows: [] });
    if (ids.length > 500) return res.status(400).json({ error: 'too many ids (max 500)' });

    // Применяем те же фильтры, что в основном endpoint'е,
    // чтобы фронт мог корректно убрать из DOM строки, переставшие удовлетворять фильтру.
    const { whereSql, params } = buildPublishTasksFilters(req.query);
    const idsIdx = params.length + 1;
    params.push(ids);

    const sql = `
      SELECT pt.*,
             pq.media_url   AS s3_url,
             pq.scheduled_at AS pq_scheduled_at,
             COALESCE(pq.pack_name,
               (SELECT fpa2.pack_name FROM factory_pack_accounts fpa2
                JOIN factory_device_numbers fdn2 ON fdn2.id = fpa2.device_num_id
                WHERE fdn2.device_id = pt.device_serial LIMIT 1)
             ) AS pack_name,
             fdn.device_number,
             COALESCE(ut.input_video_name, '') AS video_name
      FROM publish_tasks pt
      LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
      LEFT JOIN factory_device_numbers fdn ON fdn.device_id = pt.device_serial
      LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
      LEFT JOIN unic_tasks ut ON ut.id = ur.task_id
      ${whereSql}
      ${whereSql ? 'AND' : 'WHERE'} pt.id = ANY($${idsIdx}::int[])
    `;
    const { rows } = await pool.query(sql, params);
    res.json({ rows });
  } catch (e) {
    console.error('[GET /api/publish/tasks/by-ids]', e);
    res.status(500).json({ error: e.message });
  }
});
```

- [ ] **Step 2: pm2 reload и smoke**

```bash
pm2 reload all
sleep 1

# Возьмём пару валидных ID из БД
IDS=$(PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc 'SELECT id FROM publish_tasks ORDER BY id DESC LIMIT 3' | tr '\n' ',' | sed 's/,$//')
echo "IDs: $IDS"

curl -sS -b /tmp/dc-cookies.txt "https://delivery.contenthunter.ru/api/publish/tasks/by-ids?ids=$IDS" | jq '.rows | length'
```

Ожидаем: 3.

- [ ] **Step 3: Smoke с фильтром (фильтр должен «исключать» некоторые ID)**

```bash
# Найдём ID с status=done и проверим, что с фильтром status=running ответ пустой
DONE_ID=$(PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "SELECT id FROM publish_tasks WHERE status='done' LIMIT 1")
curl -sS -b /tmp/dc-cookies.txt "https://delivery.contenthunter.ru/api/publish/tasks/by-ids?ids=$DONE_ID&status=running" | jq '.rows | length'
```

Ожидаем: 0 (строка отфильтрована).

- [ ] **Step 4: Negative — мусор в ids**

```bash
curl -sS -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks/by-ids?ids=abc,def' | jq '.rows | length'
```

Ожидаем: 0 (мусор отброшен фильтром `Number.isInteger`).

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -b /tmp/dc-cookies.txt 'https://delivery.contenthunter.ru/api/publish/tasks/by-ids?ids='$(seq -s, 1 501)
```

Ожидаем: 400.

- [ ] **Step 5: Commit**

```bash
git add server.js
git commit -m "feat(api): GET /api/publish/tasks/by-ids — targeted row refresh"
```

---

## Task 6: EXPLAIN check для sort-вариантов

Проверить, что cursor-pagination не делает full scan при нестандартных сортировках. Если делает — добавить индекс.

**Files:** возможно — миграция в `migrations/` (если есть в репо), либо ad-hoc `CREATE INDEX` через psql.

- [ ] **Step 1: Проверить план для дефолтной сортировки `id DESC`**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
EXPLAIN
SELECT pt.id FROM publish_tasks pt
ORDER BY pt.id DESC, pt.id DESC
LIMIT 101;
"
```

Ожидаем: `Index Scan using publish_tasks_pkey`. Если `Seq Scan` — что-то не так с PK, разобраться.

- [ ] **Step 2: Проверить план для `created_at DESC`**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
EXPLAIN
SELECT pt.id FROM publish_tasks pt
ORDER BY pt.created_at DESC, pt.id DESC
LIMIT 101;
"
```

Если `Seq Scan` — добавить индекс:

```sql
CREATE INDEX IF NOT EXISTS idx_publish_tasks_created_at_id ON publish_tasks (created_at DESC, id DESC);
```

- [ ] **Step 3: Проверить `updated_at`, `status`, `platform`, `device_serial`**

```bash
for COL in updated_at status platform device_serial; do
  echo "--- $COL ---"
  PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
    EXPLAIN SELECT pt.id FROM publish_tasks pt
    ORDER BY pt.$COL DESC, pt.id DESC
    LIMIT 101;
  " | head -10
done
```

Для каждого `Seq Scan` решаем:
- Если данных в таблице мало (1-2k) — Seq Scan может быть **дешевле** индекса; не добавлять.
- Если данных >5k и колонка часто используется в сортировке (UI знает только дефолтное `id`, поэтому остальные пока редкие) — добавить.

**Решение для pilot'а на publish_tasks (1379 строк):** не добавлять индексы. Размер таблицы небольшой; добавим, когда appropriate. Для archive_tasks (6360+) при раскатке — обязательно проверить.

- [ ] **Step 4: Зафиксировать решение**

Добавить комментарий в `server.js` рядом с `PUBLISH_TASKS_SORT_WHITELIST`:

```js
// EXPLAIN-проверено 2026-04-28: для publish_tasks (~1.4k строк) дополнительные
// индексы не нужны. Для таблиц >5k строк при раскатке — повторить EXPLAIN.
```

- [ ] **Step 5: Commit (если были изменения; иначе пропустить)**

```bash
git add server.js
git commit -m "chore(api): document EXPLAIN check for publish_tasks sort variants"
```

---

## Task 7: Frontend — sentinel-строка в DOM

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html:2369`

- [ ] **Step 1: Найти конец таблицы tasks**

```bash
grep -n 'id="upt-tbody"' /root/.openclaw/workspace-genri/autowarm/public/index.html
```

Запомнить номер строки начала `<tbody id="upt-tbody">`. Найти соответствующий `</tbody>`.

- [ ] **Step 2: Сразу перед `</tbody>` добавить sentinel-строку**

В контексте: tbody содержит динамически генерируемые `<tr>`. Sentinel должен присутствовать **всегда**, не пересоздаваться. Добавляем его **после** `</tbody>` через `<tfoot>`, либо как отдельный `<tr>` с фиксированным id, который никогда не очищается.

Решение: добавить **после** существующего `</tbody>`, но внутри той же `<table>`, отдельный `<tbody id="upt-sentinel-body">`:

```html
<tbody id="upt-tbody" class="divide-y divide-gray-100">
  <!-- ...существующее... -->
</tbody>
<tbody id="upt-sentinel-body">
  <tr id="upt-sentinel" class="hidden">
    <td colspan="11" class="px-3 py-4 text-center text-gray-400 text-xs">
      <span id="upt-sentinel-text">Загружаю ещё...</span>
      <button id="upt-load-more-btn" onclick="loadMorePublishTasks()" class="hidden ml-2 px-3 py-1 border border-gray-300 rounded text-xs hover:bg-gray-50">Загрузить ещё</button>
    </td>
  </tr>
</tbody>
```

- [ ] **Step 3: Smoke в браузере**

Открыть `https://delivery.contenthunter.ru/#publishing/publishing?sub=up:tasks`, в DevTools проверить:

```js
document.getElementById('upt-sentinel') !== null
```

Должно вернуть `true`. Sentinel пока скрыт (`class="hidden"`) — это норма, фронт-логика покажет его в Task 8.

- [ ] **Step 4: Commit**

⚠️ **Не коммитить** — frontend и backend (Task 3) сейчас несовместимы. Совместный коммит после Task 8. Отметить шаг сделанным, не коммитить пока.

---

## Task 8: Frontend — переписать loadPublishTasks на cursor + интегрировать sentinel

Это большой шаг. Полностью заменяем state и контроль.

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html:10544` (state), `:10599` (uptSort), `:10608` (uptColFilter), `:10627` (uptRenderRows), `:10714` (loadPublishTasks)

- [ ] **Step 1: Заменить state declaration (строка ~10544)**

Найти:
```js
let _uptAll = [], _uptSort = 'id', _uptSortDir = -1, _uptColFilters = {};
```

Заменить на:
```js
// Tasks tab — cursor-pagination state
const _uptState = {
  rows: [],
  cursor: null,
  hasMore: true,
  loading: false,
  filters: {},                          // { col: value, ... }
  sort: { col: 'id', order: 'desc' },
  autoLoadedCount: 0,
};
const UPT_MAX_AUTO_PAGES = 5;
const UPT_PAGE_SIZE = 100;
let _uptObserver = null;
let _uptStatsTimer = null;
let _uptRefreshTimer = null;
let _uptSearchDebounce = null;
```

- [ ] **Step 2: Переписать uptSort**

Найти существующий `function uptSort(col)` и заменить на:

```js
function uptSort(col) {
  if (_uptState.sort.col === col) {
    _uptState.sort.order = _uptState.sort.order === 'asc' ? 'desc' : 'asc';
  } else {
    _uptState.sort.col = col;
    _uptState.sort.order = 'desc';
  }
  // Update sort indicators
  document.querySelectorAll('[id^="upts-"]').forEach(el => el.textContent = '⇅');
  const el = document.getElementById('upts-' + col);
  if (el) el.textContent = _uptState.sort.order === 'asc' ? '▲' : '▼';
  uptResetAndLoad();
}
```

- [ ] **Step 3: Переписать uptColFilter**

```js
function uptColFilter(col, val) {
  if (val) _uptState.filters[col] = val;
  else delete _uptState.filters[col];
  // Дебаунс только для текстовых полей. Селекты вызывают onchange — мгновенно.
  // Простой эвристический критерий: если вызов из input — debounce; иначе сразу.
  // Вместо распознавания типа event'а просто debounce'им всё на 300мс — безопасно для select'ов тоже.
  clearTimeout(_uptSearchDebounce);
  _uptSearchDebounce = setTimeout(uptResetAndLoad, 300);
}
```

⚠️ **Маппинг имён фильтров фронт→бэк:**
Фронт сейчас фильтрует по: `id`, `device_number`, `pack_name`, `platform`, `account`, `video_name`, `status`. Бэк-whitelist: `status`, `platform`, `device_serial`, `pack_name`, `search`. Нужен маппинг:

```js
function uptMapFiltersToServer(filters) {
  const out = {};
  if (filters.status)    out.status = filters.status;
  if (filters.platform)  out.platform = filters.platform;
  if (filters.pack_name) out.pack_name = filters.pack_name;
  // id, device_number, account, video_name → объединяются в search
  const searchParts = [];
  for (const k of ['id','device_number','account','video_name']) {
    if (filters[k]) searchParts.push(filters[k]);
  }
  if (searchParts.length) out.search = searchParts.join(' ');
  return out;
}
```

⚠️ **Ограничение pilot'а:** объединение всех «прочих» фильтров в `search` — компромисс. Нативно бэк ищет ILIKE по `caption`/`source_name`/`device_serial`, что **не покрывает** фильтры по `id` или `account`. В pilot мы говорим: тонкие фильтры по этим колонкам в pilot'е работают приближённо через общий поиск; точное соответствие — задача этапа 2 (расширение whitelist'а или per-column поиск).

Добавить эту функцию рядом с `uptMapFiltersToServer`. Документировать ограничение комментарием в коде.

- [ ] **Step 4: Добавить uptResetAndLoad**

```js
async function uptResetAndLoad() {
  _uptState.rows = [];
  _uptState.cursor = null;
  _uptState.hasMore = true;
  _uptState.autoLoadedCount = 0;
  uptRenderRows();             // очистит DOM
  await loadPublishTasks();    // первая загрузка
  await fetchPublishTasksStats();
}
```

- [ ] **Step 5: Переписать uptRenderRows (только рендеринг)**

Найти `function uptRenderRows()` (строка ~10627). Сейчас в нём идёт фильтрация и сортировка по `_uptColFilters` и `_uptSort`. Удаляем этот блок — данные уже отфильтрованы и отсортированы сервером. Оставляем **только рендеринг**.

Структурно:

```js
function uptRenderRows() {
  const tbody = document.getElementById('upt-tbody');
  const footer = document.getElementById('upt-footer');
  const sentinel = document.getElementById('upt-sentinel');
  if (!tbody) return;

  const data = _uptState.rows;

  if (!data.length) {
    if (_uptState.loading) {
      tbody.innerHTML = '<tr><td colspan="11" class="px-3 py-8 text-center text-gray-400">Загрузка...</td></tr>';
    } else {
      tbody.innerHTML = '<tr><td colspan="11" class="px-3 py-8 text-center text-gray-400">Нет данных</td></tr>';
    }
  } else {
    tbody.innerHTML = data.map(row => uptRenderRow(row)).join('');
  }

  if (footer) {
    footer.textContent = `Загружено: ${data.length}`
      + (_uptState.hasMore ? ' (есть ещё)' : '');
  }

  // Sentinel visibility
  if (sentinel) {
    if (_uptState.hasMore) {
      sentinel.classList.remove('hidden');
      const text = document.getElementById('upt-sentinel-text');
      const btn = document.getElementById('upt-load-more-btn');
      if (_uptState.autoLoadedCount >= UPT_MAX_AUTO_PAGES) {
        if (text) text.textContent = 'Подгружено много страниц подряд — продолжить?';
        if (btn) btn.classList.remove('hidden');
      } else {
        if (text) text.textContent = _uptState.loading ? 'Загружаю ещё...' : 'Прокрути вниз для подгрузки';
        if (btn) btn.classList.add('hidden');
      }
    } else {
      sentinel.classList.add('hidden');
    }
  }
}
```

- [ ] **Step 6: Извлечь рендеринг одной строки в uptRenderRow**

Существующий `data.map(row => { ... })` (строки ~10794–10846) переносим в отдельную функцию `uptRenderRow(row)`, **не меняя логику** — только обёрткa. Это нужно, чтобы row-refresh мог точечно перерисовать одну строку.

```js
function uptRenderRow(row) {
  const icon = UP_PLATFORM_ICON[row.platform?.toLowerCase()] || '📱';
  // ... ВСЁ существующее тело старого .map() ...
  return `<tr data-row-id="${row.id}">...</tr>`;   // ВАЖНО: добавить data-row-id
}
```

⚠️ **Важно:** добавить `data-row-id="${row.id}"` к корневому `<tr>` — это нужно для row-refresh, чтобы найти и перерисовать конкретную строку.

- [ ] **Step 7: Переписать loadPublishTasks**

```js
async function loadPublishTasks() {
  if (_uptState.loading || !_uptState.hasMore) return;
  _uptState.loading = true;
  uptRenderRows();   // обновит footer/sentinel ("Загружаю...")

  try {
    const params = new URLSearchParams();
    params.set('limit', String(UPT_PAGE_SIZE));
    params.set('sort', _uptState.sort.col);
    params.set('order', _uptState.sort.order);
    if (_uptState.cursor) params.set('cursor', _uptState.cursor);
    const sf = uptMapFiltersToServer(_uptState.filters);
    for (const [k, v] of Object.entries(sf)) params.set(k, v);

    const r = await fetch('/api/publish/tasks?' + params.toString());
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();

    _uptState.rows = _uptState.rows.concat(data.rows || []);
    _uptState.cursor = data.next_cursor || null;
    _uptState.hasMore = !!data.has_more;
  } catch (e) {
    console.error('loadPublishTasks:', e);
  } finally {
    _uptState.loading = false;
    uptRenderRows();
  }
}

async function loadMorePublishTasks() {
  // Вызывается кнопкой "Загрузить ещё" после safety brake.
  _uptState.autoLoadedCount = 0;
  await loadPublishTasks();
}
```

- [ ] **Step 8: Добавить fetchPublishTasksStats**

```js
async function fetchPublishTasksStats() {
  try {
    const params = new URLSearchParams();
    const sf = uptMapFiltersToServer(_uptState.filters);
    for (const [k, v] of Object.entries(sf)) params.set(k, v);

    const r = await fetch('/api/publish/tasks/stats' + (params.toString() ? '?' + params : ''));
    if (!r.ok) return;
    const stats = await r.json();
    document.getElementById('up-stat-total').textContent   = stats.total || 0;
    document.getElementById('up-stat-pending').textContent = stats.by_status?.pending || 0;
    document.getElementById('up-stat-running').textContent = stats.by_status?.running || 0;
    document.getElementById('up-stat-done').textContent    = stats.by_status?.done || 0;
    document.getElementById('up-stat-failed').textContent  = stats.by_status?.failed || 0;
    document.getElementById('up-stat-skipped').textContent = stats.by_status?.processing || 0;
  } catch (e) {
    console.error('fetchPublishTasksStats:', e);
  }
}
```

⚠️ Stats DOM-элементы (`up-stat-*`) **разделяются** между tasks и queue tab. Это корректно: stats полла должна работать только когда tasks tab активен (см. Task 9 — visibility-guard и tab-guard).

- [ ] **Step 9: Добавить IntersectionObserver setup**

```js
function uptInitObserver() {
  if (_uptObserver) return;
  const sentinel = document.getElementById('upt-sentinel');
  if (!sentinel) return;
  _uptObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      // Условия для авто-подгрузки
      if (_uptCurrentTab() !== 'tasks') continue;
      if (_uptState.loading || !_uptState.hasMore) continue;
      if (_uptState.autoLoadedCount >= UPT_MAX_AUTO_PAGES) continue;
      _uptState.autoLoadedCount += 1;
      loadPublishTasks();
    }
  }, { root: null, rootMargin: '200px', threshold: 0 });
  _uptObserver.observe(sentinel);
}

function _uptCurrentTab() {
  return _upCurrentTab; // существующая глобальная — 'queue' или 'tasks'
}
```

- [ ] **Step 10: Привязать инициализацию к смене таба**

Найти существующий `function upSwitchTab(tab)` (строка ~10547). В конце функции, после переключения видимости, добавить:

```js
if (tab === 'tasks') {
  uptInitObserver();
  uptStartPolling();
  if (_uptState.rows.length === 0) uptResetAndLoad();
} else {
  uptStopPolling();
}
```

Добавить функции polling-таймеров:

```js
function uptStartPolling() {
  uptStopPolling();
  _uptStatsTimer = setInterval(() => {
    if (document.visibilityState !== 'visible') return;
    if (_uptCurrentTab() !== 'tasks') return;
    fetchPublishTasksStats();
  }, 10000);
  _uptRefreshTimer = setInterval(() => {
    if (document.visibilityState !== 'visible') return;
    if (_uptCurrentTab() !== 'tasks') return;
    refreshPublishTaskRows();
  }, 15000);
}

function uptStopPolling() {
  if (_uptStatsTimer) { clearInterval(_uptStatsTimer); _uptStatsTimer = null; }
  if (_uptRefreshTimer) { clearInterval(_uptRefreshTimer); _uptRefreshTimer = null; }
}
```

- [ ] **Step 11: Добавить refreshPublishTaskRows (live-обновление загруженных строк)**

```js
async function refreshPublishTaskRows() {
  if (!_uptState.rows.length) return;
  try {
    const ids = _uptState.rows.map(r => r.id);
    const params = new URLSearchParams();
    params.set('ids', ids.join(','));
    const sf = uptMapFiltersToServer(_uptState.filters);
    for (const [k, v] of Object.entries(sf)) params.set(k, v);

    const r = await fetch('/api/publish/tasks/by-ids?' + params.toString());
    if (!r.ok) return;
    const data = await r.json();
    const byId = new Map((data.rows || []).map(row => [row.id, row]));

    // Мержим: для каждого id из текущего state — обновляем или удаляем.
    const newRows = [];
    for (const oldRow of _uptState.rows) {
      const fresh = byId.get(oldRow.id);
      if (fresh) newRows.push(fresh);
      // если нет — строка отвалилась (по фильтру или удалена); не добавляем.
    }
    _uptState.rows = newRows;
    uptRenderRows();
  } catch (e) {
    console.error('refreshPublishTaskRows:', e);
  }
}
```

⚠️ **Альтернатива (более точная, для будущих оптимизаций):** обновлять только конкретные `<tr data-row-id="...">` без полного `tbody.innerHTML = ...`. В pilot'е используем простую реализацию — `uptRenderRows()` на каждом refresh. Если будет UX-проблема (моргание, потеря focus в input'ах фильтров) — оптимизируем при extract'е helper'а.

- [ ] **Step 12: Точечный refresh после действий над строкой**

Найти места в коде, где после действия (stop/approve/retry) вызывался `loadPublishTasks()` или `loadUnifiedPublish()`:
- строка ~10583 (`loadPublishTasks();` после stop)
- строка ~10710 (`loadPublishTasks();` после stop in tasks tab)

Заменить на точечный refresh:

```js
async function uptRefreshOne(id) {
  try {
    const params = new URLSearchParams();
    params.set('ids', String(id));
    const sf = uptMapFiltersToServer(_uptState.filters);
    for (const [k, v] of Object.entries(sf)) params.set(k, v);
    const r = await fetch('/api/publish/tasks/by-ids?' + params.toString());
    if (!r.ok) return;
    const data = await r.json();
    const idx = _uptState.rows.findIndex(row => row.id === id);
    if (idx === -1) return;
    if (data.rows.length) {
      _uptState.rows[idx] = data.rows[0];
    } else {
      _uptState.rows.splice(idx, 1);   // строка отфильтровалась (например, статус изменился)
    }
    uptRenderRows();
    fetchPublishTasksStats();          // counters могли измениться
  } catch (e) {
    console.error('uptRefreshOne:', e);
  }
}
```

И в обработчиках действий заменить `loadPublishTasks()` на `uptRefreshOne(id)`. Конкретные точки:

```js
// Было:
//   loadPublishTasks();
// Стало:
   uptRefreshOne(id);
```

⚠️ В обработчике `approve` через modal (строка ~10876, сейчас вызывает `loadUnifiedPublish()`) — эта функция вызывается из contexta queue tab. Если approve вызывается из tasks tab tooo (проверить, через `_upCurrentTab`), то ветвить:

```js
if (_uptCurrentTab() === 'tasks') uptRefreshOne(_approveTaskId);
else loadUnifiedPublish();
```

- [ ] **Step 13: Перевязать кнопку «🔄 Обновить» на reset-семантику**

Найти в DOM (строка ~2287):

```html
<button onclick="_upCurrentTab==='queue'?loadUnifiedPublish():loadPublishTasks()" ...>🔄 Обновить</button>
```

В новой реализации `loadPublishTasks()` **только подгружает следующую страницу** — она не сбрасывает state. Manual refresh должен вызывать `uptResetAndLoad()`. Заменить:

```html
<button onclick="_upCurrentTab==='queue'?loadUnifiedPublish():uptResetAndLoad()" ...>🔄 Обновить</button>
```

Также убедиться, что в `upSwitchTab` (Step 10) при переключении на tasks мы вызываем `uptResetAndLoad()` (если state пустой), не старый `loadPublishTasks()`. Первоначальный bootstrap страницы (где вызывается `loadUnifiedPublish()` при заходе на `/publishing`) **не** трогаем — tasks tab лениво грузится только при переключении на него.

- [ ] **Step 14: Удалить устаревший код**

После переписывания `uptRenderRows` старые сортировка-в-JS и фильтры-в-JS внутри неё стали мёртвым кодом. Убедиться, что они удалены целиком (никаких висящих `_uptColFilters[col]` или `_uptSort` ссылок). Grep-проверка:

```bash
grep -n "_uptAll\|_uptSort\|_uptSortDir\|_uptColFilters" /root/.openclaw/workspace-genri/autowarm/public/index.html
```

Ожидаем: **пусто** (всё заменено на `_uptState`).

- [ ] **Step 15: Browser smoke**

Открыть `https://delivery.contenthunter.ru/#publishing/publishing?sub=up:tasks`, проверить в DevTools:

```js
_uptState.rows.length         // ~100 после первой загрузки
_uptState.cursor              // непустая base64-строка
_uptState.hasMore             // true (если в БД >100 задач)
document.querySelectorAll('#upt-tbody tr').length  // ~100
```

Прокрутить таблицу вниз — должна подгрузиться ещё страница. После 5 авто-страниц — должна появиться кнопка «Загрузить ещё».

Кликнуть в фильтр платформы → выбрать Instagram → подождать 300мс — таблица должна полностью перезагрузиться, показать только Instagram-задачи. Stats counters — пересчитаться.

Отключить фильтр → таблица возвращается к полному набору.

Уйти на другой таб (queue) → подождать 30с → вернуться → polling должен возобновиться (статусы обновятся, stats будет свежий).

- [ ] **Step 16: Commit (combo с Task 3)**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add server.js public/index.html
git commit -m "feat(ui): publishing/tasks infinite scroll + server-side filters

- IntersectionObserver auto-load with 5-page safety brake
- Stats polled every 10s, row-refresh every 15s (visibility-gated)
- Targeted refresh after row actions (stop/approve/retry) via /by-ids
- Existing column filters mapped to server: status, platform, pack_name
  go through whitelist; id/device_number/account/video_name folded into
  ILIKE search (per-column to be expanded in iteration 2)

Spec: .ai-factory/specs/2026-04-28-paginated-tables-design.md"
```

---

## Task 9: Visibility & lifecycle handlers

Добавить корректное поведение при visibilitychange (заморозка polling).

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/public/index.html` — рядом с `uptStartPolling`/`uptStopPolling`.

- [ ] **Step 1: Добавить visibilitychange listener**

Polling уже учитывает `document.visibilityState` внутри callback'а. Никаких дополнительных listener'ов **не нужно** для базового поведения. Опционально — можно сразу запросить fresh stats при возврате видимости:

```js
// Один раз при загрузке скрипта (рядом с другими document listener'ами)
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && _uptCurrentTab() === 'tasks') {
    fetchPublishTasksStats();
    refreshPublishTaskRows();
  }
});
```

- [ ] **Step 2: Browser smoke**

Открыть tasks tab, дождаться загрузки. Свернуть вкладку, подождать 30с (polling должен «уснуть» — не делать запросов; проверить через DevTools Network). Развернуть — должны быть один stats request и один by-ids request, без накопившихся очередей.

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "feat(ui): refresh publishing/tasks on tab visibility return"
```

---

## Task 10: Edge cases — пустой результат, sentinel виден сразу, устаревший cursor

**Files:** проверка работы существующего кода в специфических сценариях. Изменения только если найдём баг.

- [ ] **Step 1: Edge — фильтр с нулевым результатом**

В browser tasks tab — ввести в фильтр строку, гарантированно не дающую результата (например, `pack_name=zzz_nonexistent`). Ожидаем:
- `_uptState.rows = []`
- `_uptState.hasMore = false`
- В таблице — текст «Нет данных»
- Sentinel — скрыт (`hidden` класс)
- IntersectionObserver не дёргается в бесконечном цикле

Проверить в DevTools Network: ровно один запрос `/api/publish/tasks?...`, **не больше**.

- [ ] **Step 2: Edge — sentinel виден сразу при <100 строках**

Применить фильтр, дающий <100 результатов (например, `status=running`, обычно их 1-3). Ожидаем:
- Все строки загружены за один запрос
- `has_more = false`
- Sentinel скрыт
- Никаких лишних запросов

- [ ] **Step 3: Edge — page refresh при включённом фильтре**

Применить фильтр (например, status=done) → нажать F5 → проверить, что фильтр сбрасывается (это норма для pilot'а — мы не сохраняем фильтры в URL). Документировать как known limitation в spec'е, если ещё не там.

⚠️ Если пользователь захочет сохранение фильтров в URL (`?sub=up:tasks&filter_status=done`) — это отдельная фича, не в pilot'е.

- [ ] **Step 4: Edge — устаревший cursor**

Симулировать через DevTools Console:

```js
// 1. Загрузить первую страницу
await uptResetAndLoad();
// 2. Сохранить cursor
const stale = _uptState.cursor;
// 3. Вручную удалить из БД верхнюю строку (либо просто симулировать неконсистентность)
// 4. Использовать stale cursor в новом запросе
const r = await fetch('/api/publish/tasks?cursor=' + encodeURIComponent(stale));
console.log(await r.json());
```

Ожидаем: ответ без 500-ки, `rows` может быть пустым или сдвинутым — это норма. Главное — сервер не падает.

- [ ] **Step 5: Документировать находки**

Если все три edge-кейса прошли — никаких действий. Если есть баги — фикс + повтор тестов.

(Этот шаг может не привести к коммиту — это всё чистая проверка.)

---

## Task 11: Manual full-flow QA в браузере

Финальная человеческая проверка перед merge'ом.

**Files:** none

- [ ] **Step 1: Чек-лист golden path**

В браузере на `/publishing/publishing?sub=up:tasks`:

1. **Первая загрузка** — таблица показывает 100 строк за <500мс, stats counters в шапке заполнены.
2. **Скролл вниз** — sentinel въезжает в viewport, появляется надпись «Загружаю ещё», подгружается следующие 100 строк, sentinel снова в самом низу.
3. **Авто-brake** — после 5 авто-страниц (500 строк) sentinel показывает «продолжить?» с кнопкой. Кнопка работает — следующие 5 страниц снова авто.
4. **Сортировка** — клик на «ID» → таблица перезагружается (можно проверить, изменился ли первый ID).
5. **Фильтр платформы** — выбор «Instagram» в select'е → таблица перезагружается за ~300мс, все строки `Instagram`. Stats counters пересчитаны (только по Instagram).
6. **Поиск (свободный фильтр)** — ввод в input «Видео» → debounce 300мс → таблица перезагружается. Stats — пересчитан.
7. **Reset** — очистить все фильтры (если есть кнопка) — возврат к полному набору.
8. **Manual refresh** — кнопка «🔄 Обновить» в шапке — таблица перезагружается с нуля.
9. **Действие** — найти задачу со статусом `running`, нажать Stop. Через ~1с строка должна обновиться (новый статус — paused/stopped). Stats counters — пересчитаны. Без перезагрузки всей ленты.
10. **Live update** — оставить таб открытым на 30 сек, наблюдая за задачей `running`. Когда статус меняется (testbench продолжает работу) — должно отразиться в DOM без действий пользователя.

- [ ] **Step 2: Negative QA**

1. **Сетевой fail** — в DevTools включить «Offline» → попробовать прокрутить вниз. Должно отображаться «Загрузка...» или ошибка в консоли, но **не зацикливание fetch'ей**.
2. **Возврат сети** — выключить «Offline» → следующий polling-тик восстанавливает работу.
3. **Tab visibility** — свернуть таб на 60с → DevTools Network должен показать **0** запросов из tasks tab.

- [ ] **Step 3: Если все шаги ок — двигаемся к деплою**

Если есть баги — фиксим в отдельных коммитах в этой же ветке.

---

## Task 12: Деплой в прод

**Files:** none (git operations + pm2)

- [ ] **Step 1: Финальный rebase / merge с main**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git fetch origin
git rebase origin/main
```

Если конфликты — разрулить вручную, не сбрасывать ничего.

- [ ] **Step 2: Push ветки и создание PR (если paradigm — через PR)**

```bash
git push origin feat/paginated-publish-tasks-20260428
```

Если в проекте принято работать через PR — создать PR в `GenGo2/delivery-contenthunter` через `gh pr create`. Если принято cherry-pick'ом в main (memory: «cherry-pick в prod main → auto-push hook → pm2 restart» — typical паттерн) — продолжаем по этому пути:

```bash
git checkout main
git merge --no-ff feat/paginated-publish-tasks-20260428
# auto-push hook сам зальёт в GenGo2/delivery-contenthunter
```

⚠️ Уточнить у пользователя предпочтительный путь до старта Step 2.

- [ ] **Step 3: pm2 restart**

```bash
pm2 reload all
sleep 2
pm2 status
```

Все процессы должны быть `online`.

- [ ] **Step 4: Production smoke**

Открыть `https://delivery.contenthunter.ru/#publishing/publishing?sub=up:tasks` в чистом браузере (либо incognito), пройти ускоренный чек-лист из Task 11 Step 1 (пункты 1, 2, 5, 9). Минимум 5 минут наблюдать за live-update'ом.

Параллельно — мониторинг ошибок:

```bash
pm2 logs --lines 100 | grep -iE 'error|publish/tasks'
```

Не должно быть свежих ошибок, относящихся к нашим endpoint'ам.

- [ ] **Step 5: Rollback plan**

Если что-то сломалось:

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git revert <merge-commit-sha>
git push origin main
pm2 reload all
```

Один revert — один restart — всё откачено.

---

## Self-Review Checklist (выполняется перед закрытием плана)

**Spec coverage:**
- §3.1 Cursor endpoint — Task 3 ✓
- §3.2 Stats endpoint — Task 4 ✓
- §3.3 By-ids endpoint — Task 5 ✓
- §3.4 Безопасность (whitelist, clamp, integer) — Task 3 (sort whitelist, limit clamp), Task 5 (Number.isInteger) ✓
- §4.1 Состояние — Task 8 Step 1 ✓
- §4.2 Поведение (1) первая загрузка — Task 8 Step 4 (uptResetAndLoad) ✓
- §4.2 Поведение (2) IntersectionObserver + brake — Task 8 Step 9 ✓
- §4.2 Поведение (3) reset на изменение фильтра/сортировки + дебаунс — Task 8 Steps 2,3,4 ✓
- §4.2 Поведение (4) Stats polling — Task 8 Step 10, Task 9 ✓
- §4.2 Поведение (5) Row-refresh polling + удаление выпавших строк — Task 8 Step 11 ✓
- §4.2 Поведение (6) Manual refresh — Task 8 Step 13 (перевязка кнопки `🔄 Обновить` на `uptResetAndLoad`) ✓
- §4.2 Поведение (7) Действие над строкой → /by-ids — Task 8 Step 12 ✓
- §5.1 Backend pilot — Tasks 3,4,5 ✓
- §5.2 Frontend pilot — Tasks 7,8,9 ✓
- §5.3 NOT in pilot — соблюдено ✓
- §5.4 Тестовый план — Tasks 3-5 (curl), 10 (edge), 11 (browser) ✓
- §5.5 Деплой — Task 12 ✓

**Placeholder scan:** TBD/TODO — нет. «implement later» — нет. «add appropriate validation» — нет. «similar to Task N» — нет.

**Type consistency:**
- `_uptState.sort.col`/`order` (Step 1) ↔ `_uptState.sort.col`/`order` в `uptSort` (Step 2) ✓
- `uptMapFiltersToServer` (Step 3) ↔ вызывается в `loadPublishTasks` (Step 7), `fetchPublishTasksStats` (Step 8), `refreshPublishTaskRows` (Step 11), `uptRefreshOne` (Step 12) — везде с одной сигнатурой ✓
- `encodeCursor`/`decodeCursor` (Task 2) ↔ используются в Task 3 ✓
- `buildPublishTasksFilters` (Task 3) ↔ используется в Task 4 (stats) и Task 5 (by-ids) ✓

