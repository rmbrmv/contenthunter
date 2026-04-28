# Paginated Tables (Infinite Scroll) — Design Spec

**Дата:** 2026-04-28
**Автор:** Danil Pavlov (с Claude)
**Статус:** approved, готов к написанию плана реализации

---

## 1. Цель и контекст

Сейчас все табличные разделы в `delivery.contenthunter.ru` загружают полный набор записей одним запросом и фильтруют/сортируют в браузере:
- `/publishing/tasks` — `/api/publish/tasks` отдаёт все ~1300+ строк.
- Аналогичный паттерн в ~10 endpoint'ах: `/api/publish/queue`, `/api/archive/tasks` (6360+ строк), `/api/unic/tasks`, `/api/whatsapp/tasks`, `/api/telegram/tasks`, `/api/factory/tasks`, `/api/factory/accounts`, `/api/phone-warm/tasks` и др.

С ростом данных (особенно `archive_tasks`) это становится медленно для пользователя и тяжело для сервера. Stats counters в шапке считаются от загруженного набора и врут при частичной загрузке.

**Задача:** перевести таблицы на бесконечную ленту (cursor-based pagination) с серверными фильтрами/сортировкой/поиском и серверной агрегацией статистики. Начать с pilot (`publishing/tasks`), затем извлечь общий helper и раскатать на остальные таблицы.

## 2. Архитектурные решения

| # | Решение | Обоснование |
|---|---|---|
| 1 | Серверные фильтры/сортировка/поиск | Клиентский фильтр на partial-наборе вводит в заблуждение; counters лгут |
| 2 | Cursor-based (keyset) пагинация по композитному ключу `(sort_value, id)` | Стабильно к вставкам в живых таблицах; работает с любой сортировкой |
| 3 | Stats — отдельный endpoint, polling | Counters всегда актуальны независимо от прокрутки |
| 4 | Row-refresh по `/by-ids` для «живых» таблиц, manual refresh для исторических | Точечное обновление DOM без переломки склеенной ленты |
| 5 | IntersectionObserver на sentinel + safety-brake `maxAutoLoadPages` (default 5) | «Бесконечная лента» как просил пользователь, защита от ухода в архив на 6k строк |
| 6 | Pilot → extract helper → roll out (rollout по одной таблице за PR) | Первая абстракция всегда плохая, если выводить из одного use case |

## 3. API контракт

Универсальный паттерн для всех мигрируемых endpoint'ов. Применяется к `/api/publish/tasks` в pilot, далее тиражируется.

### 3.1 Основной endpoint — список с курсором

```
GET /api/<resource>

Query params:
  cursor   string?  — base64 от {sort_value, id} последней строки прошлой страницы. Пусто на первой странице.
  limit    int      — по умолчанию 100, clamp в [1, 500]
  sort     string   — имя колонки (whitelist на сервере), по умолчанию "id"
  order    string   — "asc" | "desc", по умолчанию "desc"
  <filter>=<value>  — отдельные фильтры; имена тоже по whitelist'у

Response 200:
  {
    "rows": [...],                  // <= limit
    "next_cursor": string | null,   // null = больше нет
    "has_more": boolean
  }
```

**Cursor:** base64-кодированный JSON `{ "v": <sort_value>, "id": <int> }`. Опаковый — фронт не должен парсить, только передавать обратно. На сервере декодируется, валидируется тип `v` против типа sort-колонки.

**Пагинация SQL** (для `ORDER BY <sort> DESC, id DESC`):
```sql
WHERE (<sort_col>, id) < ($cursor_v, $cursor_id)
ORDER BY <sort_col> DESC, id DESC
LIMIT $limit + 1
```
+1 нужен, чтобы понять `has_more` без отдельного COUNT'а. Лишняя строка отрезается перед ответом.

### 3.2 Stats endpoint

```
GET /api/<resource>/stats?<те же filters что и в основном>

Response 200:
  {
    "total": int,
    "by_status": { "<status>": int, ... }
  }
```
SQL: `SELECT status, COUNT(*) AS n FROM ... WHERE <filters> GROUP BY status`. `total` считается как сумма `n` на сервере. Stats применяет **те же фильтры**, что активны в таблице — иначе counters не отражают того, что юзер видит.

### 3.3 Row-refresh endpoint (только для «живых» таблиц)

```
GET /api/<resource>/by-ids?ids=1,2,3,...&<те же filters что и в основном>

Constraints:
  - Лимит 500 ID на запрос
  - ids — только integer; невалидные значения отбрасываются
  - Применяет те же фильтры, что активны в таблице
    (фронт передаёт текущий filter-set; ответ содержит только те ID, которые
    удовлетворяют фильтрам — это позволяет фронту корректно удалять из DOM
    строки, которые перестали соответствовать фильтру, например status сменился).

Response 200:
  { "rows": [...] }   // тот же формат, что у основного
```

### 3.4 Серверная безопасность

- `sort` и имена фильтров — whitelist на сервере, никаких `ORDER BY ${user_input}`
- `cursor` декодируется и валидируется
- `limit` clamp'ится
- `ids` парсится через `Number.isInteger`

## 4. Frontend паттерн

### 4.1 Состояние таблицы

```js
const state = {
  rows: [],
  cursor: null,
  hasMore: true,
  loading: false,
  filters: {},
  sort: { col: 'id', order: 'desc' },
  autoLoadedCount: 0,
}
```

### 4.2 Поведение

1. **Первая загрузка** — fetch с пустым cursor + текущими `filters`/`sort` → заполняет `rows`, сохраняет `next_cursor`. Параллельно — `/stats`.

2. **IntersectionObserver на sentinel** в конце `<tbody>`:
   - Sentinel въезжает в viewport, `hasMore && !loading` → fetch следующей страницы по `cursor`, дописывает в `rows`, инкрементирует `autoLoadedCount`.
   - При `autoLoadedCount >= maxAutoLoadPages` — safety brake: вместо авто-fetch показываем кнопку «Загрузить ещё». Клик → `autoLoadedCount = 0`, авто-режим возобновляется.

3. **Изменение фильтра/сортировки** — полный reset: `rows=[], cursor=null, autoLoadedCount=0`, новая первая загрузка. Поиск дебаунсится 300мс.

4. **Stats polling** — каждые 10 сек, только при `document.visibilityState === 'visible'`.

5. **Row-refresh polling** (только для live-таблиц) — каждые 15 сек, gate'ится `visibilityState`. Собирает все ID из `rows`, шлёт на `/by-ids`, мержит ответ по ID.
   - Если строки нет в ответе — удалить из DOM (трактуется как «удалена»). Применяется только в рамках row-refresh цикла.

6. **Manual refresh** — полный reset + первая загрузка + stats.

7. **Действие над строкой** (stop/approve/retry) — оптимистическое обновление + точечный fetch `/by-ids?ids=<id>` для подтверждения.

### 4.3 Reusable helper (после второй миграции)

```js
createPaginatedTable({
  endpoint: '/api/publish/tasks',
  tbodyEl, sentinelEl, statsEl,
  renderRow: (row) => '<tr>...</tr>',
  renderStats: (stats) => '...',
  liveRefresh: true,           // включает /by-ids polling
  maxAutoLoadPages: 5,
  pageSize: 100,
  initialSort: { col: 'id', order: 'desc' },
})
```

Возвращает API: `{ reload(), setFilter(name, value), setSort(col, order), destroy() }`.

## 5. Pilot: `/publishing/tasks`

### 5.1 Backend (`server.js`)

1. **Переписать `GET /api/publish/tasks`** на cursor-based.
   - Whitelist sort: `id`, `created_at`, `updated_at`, `scheduled_at`, `status`, `platform`, `device_serial`.
   - Whitelist фильтров:
     - `status` — точное совпадение или CSV-список (`status=pending,running` → `status IN (...)`)
     - `status_exclude` — CSV-список для исключения (`status_exclude=done,skipped` → `status NOT IN (...)`); используется чекбоксом «скрыть выполненные»
     - `platform`, `device_serial`, `pack_name` — точное совпадение
     - `search` — ILIKE по `caption`, `source_name`, `device_serial`
   - JOIN'ы остаются как сейчас: `publish_queue`, `factory_device_numbers`, `unic_results`, `unic_tasks`.
   - Проверить план запроса с `EXPLAIN` для дефолтной сортировки `id DESC` — должен использовать PK. Для остальных sort-колонок проверить и при необходимости добавить индексы миграцией.

2. **Новый `GET /api/publish/tasks/stats`** — `GROUP BY status` с теми же фильтрами.

3. **Новый `GET /api/publish/tasks/by-ids`** — тот же SELECT с JOIN'ами + `WHERE pt.id = ANY($1::int[])`. Лимит 500 ID, парсинг через `Number.isInteger`.

### 5.2 Frontend (`public/index.html`)

1. **Заменить `loadPublishTasks()`** на новую логику с состоянием `_uptState`.
2. **Sentinel** — добавить `<tr id="upt-sentinel"><td colspan="11">...</td></tr>` в конец `<tbody id="upt-tbody">`. IntersectionObserver на нём.
3. **Существующие фильтры/сортировка** (`upSort`, `upColFilter`, `_upShowDone`) — переписать на серверную семантику: меняют `_uptState.filters/sort`, дёргают reset+reload.
4. **Stats polling** — `setInterval(fetchStats, 10000)` с `visibilityState`-guard.
5. **Live row-refresh** — `setInterval(refreshLoadedRows, 15000)`, тот же visibility-guard. Включаем сразу.
6. **Чекбокс «скрыть выполненные»** — превращается в server-side фильтр `status_exclude=done,skipped`.

### 5.3 Что НЕ трогаем в pilot

- Markup строки (`uptRenderRows` body) — рендеринг каждой строки остаётся; меняется только источник данных и стейт.
- Действия над задачей (stop/approve/retry/events modal) — после успеха делаем точечный refresh через `/by-ids`.
- Логика «выкладка» (`up:queue` таб, `loadUnifiedPublish`) — не входит в pilot, мигрируется во второй итерации.

### 5.4 Тестовый план

- Curl-проверка трёх endpoint'ов с разными `cursor`/`filters`/`sort`.
- В браузере: первая загрузка → скролл → подгрузка → фильтр → reset → действие → row-refresh.
- Edge cases:
  - Фильтр с нулевым результатом (sentinel не должен зацикливать)
  - Sentinel в видимой зоне с самого начала (если строк <`pageSize`)
  - Устаревший cursor (БД изменилась между запросами) — не должно валить, просто пустая страница / `has_more=false`
  - Tab уходит в фон → polling замораживается → возвращается → восстанавливается

### 5.5 Деплой

1 PR в `delivery.contenthunter.ru` (репо `GenGo2/delivery-contenthunter`), серверные endpoint'ы + фронт. Деплой по обычному паттерну: cherry-pick в prod main → auto-push hook → `pm2 restart`. Откат — revert одного коммита.

## 6. План раскатки

### Этап 2: вторая миграция + extract helper

`/api/publish/queue` (714 строк, та же страница `/publishing`). Мигрируем по pilot-паттерну, **параллельно вытаскиваем** общий код в:
- **Backend:** `paginate.js` — `buildPaginatedQuery({...})`, `buildStatsQuery({...})`, `decodeCursor()`, `encodeCursor()`.
- **Frontend:** `paginated-table.js` — `createPaginatedTable({...})` (см. 4.3).

В этом же PR — pilot переписывается на helper. Это реальная проверка, что абстракция честная.

### Этап 3: раскатка по приоритету

| # | Endpoint | Строк | Live? | Заметки |
|---|---|---|---|---|
| 1 | `archive/tasks` | 6360 | ❌ | Самая большая, юзер заметит ускорение. liveRefresh=false |
| 2 | `unic/tasks` | 1540 | ✅ | Активная очередь уникализации |
| 3 | `factory/tasks` + `factory/accounts` | 1253 | ✅ | factory_inst_accounts |
| 4 | `whatsapp/tasks` | — | ✅ | |
| 5 | `telegram/tasks` | — | ✅ | |
| 6 | `phone-warm/tasks` | — | ✅ | Минорно по объёму, но за единообразие |
| 7 | `tasks` (общий) | — | ? | На этапе аудита раскатки: проинспектировать `/api/tasks` в server.js и решить — мигрировать или убрать как legacy |

Каждая миграция — отдельный PR (1 endpoint backend + 1 страница фронт). Размер маленький, легко ревьюить, легко откатывать.

### Что обязательно в каждой миграции

- `EXPLAIN` для дефолтной сортировки. Нужны ли индексы — добавляем миграцией перед эндпоинтом.
- Все existing client-side фильтры/сортировка/поиск переехали на сервер.
- Stats counters работают с фильтрами.
- Нет регрессии в действиях над строками.

### Out of scope для этого проекта

- Endpoint'ы с малыми фиксированными наборами (`/api/publish/packs?project_id=...`, `/api/publish/carousels?project_id=...`) — у них естественные лимиты, бесконечная лента не нужна.
- Админка для глобальной настройки `pageSize`/`maxAutoLoadPages` — пока константы.
- WebSocket / SSE — остаёмся на polling.

### Откат helper'а на отдельной странице

Каждая страница использует helper, но если на странице N всплывает баг helper'а, можно временно «отвязать» эту страницу (вернуть локальную копию) и фиксить helper отдельно. Версионирование helper'а — простое: один файл, в репо, при необходимости кладём `paginated-table-v1.js` рядом и привязываем нужные страницы.

## 7. Сроки (грубо)

- Pilot — 1 PR, ~1 день.
- Этап 2 (publish/queue + extract) — 1 PR, ~1 день.
- Этап 3 — 7 PR'ов по ~0.5 дня, можно за неделю.

## 8. Риски

| Риск | Митигация |
|---|---|
| Helper выводится преждевременно, не подходит другим таблицам | Этап 2 (вторая миграция) обязателен ДО раскатки; если не подходит — переделываем helper до этапа 3 |
| Cursor-pagination требует индекса для нестандартной сортировки | `EXPLAIN` обязателен в чек-листе каждой миграции; добавление индекса — отдельной миграцией перед endpoint'ом |
| Row-refresh polling нагружает сервер на больших таблицах | По умолчанию выключен (`liveRefresh=false`); включается только для активно меняющихся таблиц |
| Юзер фильтрует/сортирует часто — каждый раз новый запрос | Дебаунс 300мс на input-фильтрах; для select-фильтров не требуется |
| Sentinel-зацикливание на пустом результате | `hasMore=false` сразу после первого ответа без `next_cursor` — IntersectionObserver не дёргается |
