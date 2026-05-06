# Publishing Tables — Project column + filters/sort fix — Design Spec

**Date:** 2026-05-06
**Branch target:** `delivery.contenthunter.ru/#publishing/publishing` (frontend `index.html` + `server.js` в `/root/.openclaw/workspace-genri/autowarm/`)
**Author:** Claude (brainstorming skill, approved by Danil)

## Цель

Привести в порядок две таблицы раздела «Выкладка»:

1. **Запланировано** (`?sub=up:queue`) — таблица `publish_queue`.
2. **Опубликовано** (`?sub=up:tasks`) — таблица `publish_tasks`.

Изменения:

- Добавить в обе таблицы колонку **«Проект»** с фильтром-выпадайкой.
- Скорректировать колонки **«Название»** и **«Описание»** в Запланировано.
- Починить фильтры и сортировку (выявлены конкретные баги — см. ниже).

## Backlog контекста (что обнаружено разведкой)

### Схема данных

`publish_queue`:
- `caption` — для YT хранит короткий title (~35–60 симв), для IG/TT хранит полное длинное описание (~324 симв).
- `title` — колонка существует, но всегда `NULL` (не используется).
- `content_description` — заполнено для всех платформ одинаковым исходным текстом (~326 симв). **Это и есть «Описание» которое хочет видеть пользователь.**
- `hashtags` — JSONB-массив, обычно `[]`.
- `project_id` → JOIN `validator_projects.project`.

`publish_tasks`:
- `project` (text) хранит pack-name (`Максим Иванов_16`), НЕ имя проекта. Не использовать.
- `project_id` отсутствует. Связь с проектом — через `publish_queue.project_id` (LEFT JOIN).

### Текущие баги

**Запланировано (queue):**
1. Колонка «Название» рендерит `row.caption` для всех платформ → для IG/TT показывает полный длинный текст, который должен быть в «Описании».
2. Колонка «Описание» рендерит **только хештеги** (`tags.map(t => '#'+t)`). Хештеги почти всегда `[]` → юзер видит «—».
3. Колонка «Проект» отсутствует. Имя проекта уже доступно в SELECT (`PUBLISH_QUEUE_SELECT.project_name` через JOIN `validator_projects`), но не выводится — используется как fallback в колонке «Пак».
4. Фильтр-input «Описание» (`upColFilter('description', val)`) во фронт-маппере склеивается в общий `search` (index.html:10722), а server `search` ищет по `caption / source_name / pq.id::text / pq.hashtags::text` — **`content_description` не покрыт**. Фильтр промахивается.
5. Сортировка по «Проект» отсутствует в `PUBLISH_QUEUE_SORT_WHITELIST`.

**Опубликовано (tasks):**
1. Колонка «Проект» отсутствует. JOIN на `validator_projects` через `publish_queue` ещё не сделан в `PUBLISH_TASKS_FROM`.
2. Sort whitelist (`PUBLISH_TASKS_SORT_WHITELIST`) содержит только `id, created_at, updated_at, scheduled_at, status, platform, device_serial`. **Кликабельные колонки в UI — `device_number, pack_name, account, video_name, tokens_used, started_at` — отсутствуют в whitelist** → клик возвращает 400. Это корень жалобы «sort выводит пустой результат».
3. Фильтры-input'ы фронта `id, device_number, account, video_name` склеиваются в общий `search` (index.html:10741). Server `search` ищет по `pt.caption / ut.input_video_name / pt.device_serial`. **`pt.account`, `fdn.device_number`, числовой `pt.id` не покрыты** → фильтры промахиваются.

## Решение

### Подход (выбран)

**Server-side JOIN на `validator_projects`** для обоих эндпойнтов. Один источник истины (`vp.project`), без миграций. Альтернативы (парсить pack-name; добавить `project_id` колонку в `publish_tasks`) отвергнуты как хрупкие/oversized.

### Backend — `server.js`

#### `publish_queue`

**`PUBLISH_QUEUE_SORT_WHITELIST`** — добавить:
```js
project: 'COALESCE(vp.project, vp2.project)',
```

**`buildPublishQueueFilters`** — добавить:
```js
if (query.project)     push("COALESCE(vp.project, vp2.project) = $?", String(query.project));
if (query.description) push("pq.content_description ILIKE $?", '%' + String(query.description) + '%');
```

**Новый endpoint** `GET /api/publish/queue/projects`:
```js
app.get('/api/publish/queue/projects', requireAuth, async (req, res) => {
  try {
    const { rows } = await pool.query(`
      SELECT DISTINCT COALESCE(vp.project, vp2.project) AS project
      FROM publish_queue pq
      LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
      LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
      LEFT JOIN validator_projects vp  ON vp.id  = pq.project_id
      LEFT JOIN validator_projects vp2 ON vp2.id = ut.project_id
      WHERE COALESCE(vp.project, vp2.project) IS NOT NULL
      ORDER BY 1
    `);
    res.json(rows.map(r => r.project));
  } catch (e) { res.status(500).json({ error: e.message }); }
});
```

#### `publish_tasks`

**`PUBLISH_TASKS_FROM`** — добавить JOIN:
```js
LEFT JOIN validator_projects vp ON vp.id = pq.project_id
```

**`PUBLISH_TASKS_SELECT`** — добавить:
```js
vp.project AS project_name,
```

**`PUBLISH_TASKS_SORT_WHITELIST`** — расширить:
```js
project:        'vp.project',
pack_name:      'pq.pack_name',
account:        'pt.account',
video_name:     'ut.input_video_name',
device_number:  'fdn.device_number',
tokens_used:    'pt.tokens_used',
started_at:     'pt.started_at',
```

**`buildPublishTasksFilters`** — добавить отдельные параметры (фронт перестаёт склеивать в `search`):
```js
if (query.project) push("vp.project = $?", String(query.project));
if (query.id) {
  const n = parseInt(query.id, 10);
  if (Number.isInteger(n)) push("pt.id = $?", n);
}
if (query.account)       push("pt.account ILIKE $?",                '%' + String(query.account) + '%');
if (query.video_name)    push("ut.input_video_name ILIKE $?",       '%' + String(query.video_name) + '%');
if (query.device_number) {
  const n = parseInt(query.device_number, 10);
  if (Number.isInteger(n)) push("fdn.device_number = $?", n);
}
```

**Новый endpoint** `GET /api/publish/tasks/projects`:
```js
app.get('/api/publish/tasks/projects', requireAuth, async (req, res) => {
  try {
    const { rows } = await pool.query(`
      SELECT DISTINCT vp.project
      FROM publish_tasks pt
      LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id
      LEFT JOIN validator_projects vp ON vp.id = pq.project_id
      WHERE vp.project IS NOT NULL
      ORDER BY 1
    `);
    res.json(rows.map(r => r.project));
  } catch (e) { res.status(500).json({ error: e.message }); }
});
```

### Frontend — `public/index.html`

#### Queue table

**`<thead>`** (строка 2306–2329):
- Между `ID` (`<th>` с `upSort('id')`) и `Пак` вставить `<th>` «Проект» с `onclick="upSort('project')"`.
- В строке фильтров между id-input и pack-input вставить `<select>` с `onchange="upColFilter('project', this.value)"`. Опции наполняются JS при init из `/api/publish/queue/projects`.
- Заглушка `colspan` повышается с **10 → 11** (две `<tr>` в `<tbody>` — main и sentinel).

**`upqRenderRow`** (index.html:10892):
- Добавить `<td>` с `row.project_name` между ID и Пак (после строки 10919).
- Колонка «Название» — заменить `captionCell`:
  ```js
  const captionCell = (row.platform?.toLowerCase() === 'youtube' && row.caption)
    ? `<span class="text-xs text-gray-700 block max-w-[160px] truncate" title="${(row.caption||'').replace(/"/g,'&quot;')}">${row.caption.slice(0, 100)}</span>`
    : '<span class="text-gray-300 text-xs">—</span>';
  ```
- Колонка «Описание» — заменить `descCell`:
  ```js
  const descCell = row.content_description
    ? `<span class="text-xs text-gray-700 block max-w-[200px] truncate" title="${(row.content_description||'').replace(/"/g,'&quot;')}">${row.content_description}</span>`
    : '<span class="text-gray-300 text-xs">—</span>';
  ```

**`upqMapFiltersToServer`** (index.html:10712):
- Добавить:
  ```js
  if (filters.project)     out.project     = filters.project;
  if (filters.description) out.description = filters.description;
  ```
- Убрать `description` из `searchParts` петли (теперь отдельный параметр).

**`_upqTable.emptyColspan`** (index.html:10951): `10 → 11`.

**`upClearFilters`** (index.html:10975):
- Добавить `'project'` и `'description'` (уже есть) в массив сбрасываемых фильтров.

**Init**:
- В `loadUnifiedPublish` или при первом показе секции — `fetch('/api/publish/queue/projects')`, заполнить `<select>` опциями.

#### Tasks table

**`<thead>`** (строка 2352–2377):
- Между `ID` и `№ Устр.` вставить `<th>` «Проект» с `onclick="uptSort('project')"`.
- Соответствующий `<select>` фильтр `onchange="uptColFilter('project', this.value)"`.
- Заглушка `colspan` повышается с **13 → 14**.

**`uptRenderRow`** (index.html:10771):
- Добавить `<td>` с `row.project_name` между ID и device.

**`uptMapFiltersToServer`** (index.html:10735):
- Каждый фильтр — отдельный параметр, без склейки в `search`:
  ```js
  function uptMapFiltersToServer(filters) {
    const out = {};
    if (filters.status)        out.status        = filters.status;
    if (filters.platform)      out.platform      = filters.platform;
    if (filters.pack_name)     out.pack_name     = filters.pack_name;
    if (filters.project)       out.project       = filters.project;
    if (filters.id)            out.id            = filters.id;
    if (filters.account)       out.account       = filters.account;
    if (filters.video_name)    out.video_name    = filters.video_name;
    if (filters.device_number) out.device_number = filters.device_number;
    return out;
  }
  ```

**`_uptTable.emptyColspan`** (index.html:10858): `13 → 14`.

**Init**:
- Аналогично — `fetch('/api/publish/tasks/projects')` при показе таблицы tasks.

### Дропдаун проектов — поведение

- **Queue list:** загружается в `loadUnifiedPublish()` (срабатывает на `nav('publishing')` и при `upSwitchTab('queue')`). Кэшируется в module-level переменной `_upqProjectsLoaded` чтобы не дёргать каждый раз.
- **Tasks list:** загружается в `uptResetAndLoad()` (срабатывает при `upSwitchTab('tasks')`). Аналогично кэшируется.
- Опции: `<option value="">все</option>` + список из endpoint'а.
- Сортировка алфавитная (server-side `ORDER BY 1`).
- Если endpoint вернёт ошибку — `<select>` остаётся с одной опцией «все», в консоль `console.warn`. Не блокирует загрузку таблицы.

## Тесты (TDD)

Backend (Node.js — нужно проверить наличие тестов в репе):
1. `GET /api/publish/queue?project=Content+hunter` — возвращает только строки этого проекта.
2. `GET /api/publish/queue?description=10%20млн` — ILIKE по content_description.
3. `GET /api/publish/queue?sort=project&order=asc` — успешный 200, отсортировано по vp.project.
4. `GET /api/publish/queue/projects` — список distinct, отсортирован.
5. То же для `/api/publish/tasks` (project, id, account, device_number, sort по project/pack_name/account/started_at/tokens_used).
6. `GET /api/publish/tasks/projects` — distinct.

Frontend (smoke в браузере):
1. Открыть Запланировано → колонка «Проект» отображается между ID и Пак.
2. Сортировка по любой кликабельной колонке (включая project) — таблица перерисовывается без ошибок 4xx в Network.
3. Фильтр по «Проект» — выбираешь проект, остаются только его строки.
4. Фильтр по «Описание» — вводишь фрагмент, остаются только подходящие.
5. «Название» для YT-строк — короткий title (≤100 симв); для IG/TT — «—».
6. «Описание» — текстовое описание (не «—», не хештеги).
7. Аналогично для Опубликовано: проект, фильтры id/account/device_number/video_name работают по точному/ILIKE-совпадению, sort по любой колонке без 400.

## Деплой

Frontend `public/index.html` живёт в `/root/.openclaw/workspace-genri/autowarm/`. Согласно памяти проекта (`reference_delivery_frontend_deploy.md`):
- Pattern: `cp` для test-deploy → cherry-pick в prod main для permanent (auto-push hook сам отправит в `GenGo2/delivery-contenthunter`).

Backend `server.js` — рестарт через `pm2 reload <app>` после коммита.

## Out of scope

- Не трогаю pagination factory (`paginated-table.js`).
- Не делаю миграцию `publish_tasks.project_id`.
- Не редизайню форму добавления задачи.
- Не трогаю фильтр «Показать выполненные» / status_exclude.
