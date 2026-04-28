# Evidence — Paginated Tables Этап 2 (helper extract + queue migration)

**Дата:** 2026-04-28
**Plan:** `.ai-factory/plans/2026-04-28-paginated-tables-etap2.md`
**Spec:** `.ai-factory/specs/2026-04-28-paginated-tables-design.md` §6

## Статус: ОТГРУЖЕНО ✅

Все 16 задач плана закрыты. Phase 1 (backend) + Phase 2 (frontend) задеплоены, browser smoke пройден.

## Commits в `delivery-contenthunter` (prod)

Ветка: `feature/paginated-tables-etap2-20260428`. Auto-push hook ↑GenGo2 отработал на каждом commit'е.

| SHA | Тип | Сообщение |
|---|---|---|
| `da10b80` | feat | refactor(server): extract paginate.js + cursor pagination for /api/publish/queue |
| `3dcaf6e` | unrelated | fix(publisher): @staticmethod for `_is_specific_reel_url` (orphan от соседней сессии — не моё) |
| `42b3581` | feat | refactor(ui): paginated-table.js factory + apply to /publishing/tasks + /publishing/queue |
| `4a81909` | hotfix | fix(ui): defer loadUnifiedPublish if `_upqTable` still in TDZ |

Решено пока **НЕ мержить в main** — оставляю как feature-ветку (matches pilot rollout pattern: pilot тоже жил в feature-ветке несколько часов до merge).

## T1 — Baseline curl-снапшоты

| Endpoint | Size | Rows | MD5 |
|---|---|---|---|
| `/api/publish/tasks` (legacy array) | 9 075 009 B | 1 382 | `b14ba974c144...` |
| `/api/publish/tasks?limit=20&sort=id&order=desc` | 323 780 B | 20 (obj) | `42997bb2ede2...` |
| `/api/publish/tasks/stats` | 132 B | n/a | `85e10b8d471a...` |
| `/api/publish/tasks/by-ids?ids=1,2,3` | 11 981 B | 3 | `369b3f16b929...` |
| `/api/publish/queue` (legacy array) | 1 547 415 B | 500 | `b2d9ff105cf2...` |

## T2 — `paginate.js` + tests

Файлы: `paginate.js` (140 строк), `paginate.test.js` (165 строк).

API: `encodeCursor`, `decodeCursor`, `buildPaginatedQuery`, `processPaginatedResult`, `buildStatsQuery`, `buildByIdsQuery`.

```
$ node --test paginate.test.js
# tests 19
# pass 19
# fail 0
# duration_ms 95.171872
```

## T3 — Pilot endpoints через helper (byte-identity vs baseline)

| Endpoint | Baseline → After (size, md5) | Verdict |
|---|---|---|
| `/api/publish/tasks` legacy | 9 075 009B → 9 075 009B (12-line `updated_at` drift) | ✅ structural identity |
| `/api/publish/tasks?limit=20&...` | 323 780B → 323 780B | ✅ md5 совпал |
| `/api/publish/tasks/stats` | 132B → 132B | ✅ md5 совпал |
| `/api/publish/tasks/by-ids?ids=1,2,3` | 11 981B → 11 981B | ✅ md5 совпал |

Diff на legacy: 3 строки `updated_at` за 4 минуты живых данных. Структура (count, keys, first/last id) идентична.

## T4 — EXPLAIN `/api/publish/queue`

Таблица `publish_queue`: 720 строк, 1 индекс (pkey).

| Sort | Plan | Time |
|---|---|---|
| `pq.scheduled_at DESC` | Seq Scan + top-N heapsort | 1.08 ms |
| `+ status='pending'` | Seq Scan + quicksort | 0.22 ms |
| Cursor `(scheduled_at, id) <` | Seq Scan + top-N heapsort | 0.69 ms |
| `pq.id DESC` | **Index Scan Backward** (pkey) | 0.22 ms |

**Решение:** индексы НЕ добавляем — таблица <2k строк, все запросы <2ms. При раскатке на `archive_tasks` (6360+) или `publish_tasks` (>1.4k) повторить EXPLAIN и решить точечно.

## T5/T6/T7 — `/api/publish/queue` paginated + `/stats` + `/by-ids`

Sort whitelist расширен: `id, scheduled_at, status, platform, device_serial, pack_name, account_username, caption`.

Filters добавлены: `pack_name, account_username, caption, search` (objединяет id+source_name+description через ILIKE), `status_exclude` (для чекбокса «Показать выполненные»). Стек: status (как single | CSV ANY), status_exclude (CSV `<> ALL`).

Backwards-compat: без `limit`/`cursor` отдаёт legacy array (LIMIT 500), byte-identical к baseline.

## T8 — Smoke `/api/publish/queue` (10 сценариев)

| # | Сценарий | Результат |
|---|---|---|
| 1 | Legacy diff (без params) | byte-identical (md5 `5c9069f7...`) ✅ |
| 2 | Paginated 1-я страница `?limit=20&sort=scheduled_at&order=desc` | 20 rows, has_more=true, has_cursor=true ✅ |
| 3 | Stats без фильтров | total=720, by_status: {failed:472, skipped:167, done:78, pending:3} ✅ |
| 4 | Stats с фильтром `?status=pending` | total=3, by_status:{pending:3} ✅ |
| 5 | by-ids `?ids=1,2,3` | 3 rows, ids=[1,2,3] ✅ |
| 6 | Cursor 2-я страница (sort=id desc) | page1 last=728, page2 first=727 (no overlap) ✅ |
| 7 | Negative — invalid cursor | 200 OK, fall back to первая страница (consistent с pilot) ✅ |
| 8 | Negative — sort key mismatch на cursor | 400 Bad Request ✅ |
| 9 | Negative — invalid sort key | 400 Bad Request ✅ |
| 10 | Filter `?status=pending` paginated | 3 rows, has_more=false, statuses=[pending] ✅ |

Plus extended (T6 после-фактовый smoke):
- Sort `pack_name asc` — first_pack="Booster cap_1" ✅
- `search=pimble` — 10 rows ✅
- `pack_name=rev_pimble` — 5 rows, packs=["rev_pimble_dev103","rev_pimble_dev105"] ✅
- `status_exclude=done,skipped` — 10 rows, statuses=[failed, pending] ✅
- `/queue/stats?status_exclude=done,skipped` — total=474, by_status={failed:471, pending:3} ✅

## T10 — `paginated-table.js` factory

Файл: `public/paginated-table.js` (255 строк).

API: `createPaginatedTable({tableId, isActiveTab, endpoints, tbodyId, sentinelId, footerId, pageSize, maxAutoLoadPages, defaultSort, filtersToServer, renderRow, emptyColspan, onStats, liveRefresh, ...})` → `{reset, load, loadMore, setSort, setFilter, refreshOne, refreshVisible, fetchStats, render, onTabActivate, onTabDeactivate, getState, destroy}`.

Подключен через `<script src="/paginated-table.js">` ДО основного inline-скрипта. Express сервит как static.

## T11 — Pilot UI на factory

Удалено: `_uptState`, `_uptObserver`, `_uptStatsTimer`, `_uptRefreshTimer`, `_uptSearchDebounce`, `_uptCurrentTab` функция, `loadPublishTasks` (10808 версия — 7215 версия осталась как dead code), `fetchPublishTasksStats`, `uptInitObserver`, `uptStartPolling`, `uptStopPolling`, `refreshPublishTaskRows`, `uptRenderRows`, тело `uptRefreshOne`, visibilitychange handler.

Сохранено: `uptMapFiltersToServer`, `UPT_STATUS_BADGE`, `uptRenderRow` (передаются factory), `uptStop` (callback in DOM, перевязан на `_uptTable.refreshOne`).

Добавлено: `uptApplyStats` (onStats callback), `_uptTable` factory instance, тонкие wrappers `uptSort`/`uptColFilter`/`uptResetAndLoad`/`loadMorePublishTasks`/`uptRefreshOne` (call factory methods + DOM sort indicators).

Browser smoke: пройден (после hotfix 4a81909).

## T12 — Queue UI на factory

DOM:
- Добавлен sentinel-row внутри второго `<tbody id="up-sentinel-body">` для queue таблицы (`<tr id="up-sentinel">` + `<span id="up-sentinel-text">` + `<button id="up-load-more-btn">`).

JS — удалено: `_upAll, _upSort, _upSortDir, _upColFilters, _upShowDone` (заменены на factory state), `loadUnifiedPublish` старая, `upRenderRows`, `upUpdateStats`, тело `upDelete` старое.

Добавлено: `_upqShowDone` (одиночное), `upqApplyStats`, `upqMapFiltersToServer`, `upqRenderRow`, `upqUpdateHiddenCount`, `_upqTable` factory instance, инициализация `_upqTable.setFilter('status_exclude', 'done,skipped')` (matches default `_upShowDone=false`), wrapper'ы `upSort`/`upColFilter`/`upClearFilters`/`loadUnifiedPublish`/`loadMoreUnifiedPublish`. `upDelete` обновлён — после успешного DELETE вызывает `_upqTable.refreshOne(id)`.

«(скрыто выполненных: N)» badge — отдельным `/stats` без `status_exclude`. Иначе bynature первого вызова stats (которому передаём активные фильтры включая status_exclude) счётчик done/skipped был бы 0.

## T14 — Deploy + browser smoke

Каждый commit auto-pushed в `GenGo2/delivery-contenthunter`. Pre-commit hook валидировал JS в index.html (3 script-блока) на каждом commit'е.

Pm2 reload'ы происходили после каждого backend-коммита (4 раза суммарно). Финальный pm2 status: online, restarts=207, uptime steady.

**Browser smoke (пользователь):**
- Initial state: TDZ ReferenceError на `_upqTable` через sync `loadUnifiedPublish()` из `switchModule('publishing')` ❌
- Hotfix `4a81909`: try-catch defer на `loadUnifiedPublish` / `loadMoreUnifiedPublish` → page рабочая ✅
- Подтверждение пользователя: «грузится таблица, обновляет и фильтруется корректно» ✅

## TDZ post-mortem (хранить как урок)

**Что произошло.** Page-load IIFE `restoreNav` (line ~7846) вызывает `switchModule(mod)` синхронно. Для `mod='publishing'` switchModule на line ~3843 вызывает `loadUnifiedPublish()` синхронно. После моего refactor'а тело `loadUnifiedPublish` стало `_upqTable.reset()`. Но `const _upqTable = createPaginatedTable(...)` находится на line ~10879 — script-eval ещё не дошёл до этой строки. Result: ReferenceError.

**Почему не словил на смоке.** Curl-проверки тестируют только endpoints, не JS-инициализацию. Pre-commit hook `node --check` валидирует синтаксис, но не TDZ semantics (это runtime, не compile-time). Browser smoke поймал.

**Урок (memory rule):** при миграции функции, которая уже вызывается синхронно из IIFE / page-init цепочки, на factory pattern с `const _factory = ...` объявленным позже в скрипте — ВСЕГДА оборачивать тело новой функции в try-catch ReferenceError + setTimeout(0) defer. Альтернатива: переместить factory creation в начало скрипта.

## Out of scope (явно не делал)

1. Backport pilot+etap2 в `autowarm-testbench` (отдельный follow-up)
2. Этап 3 — раскатка на 7 таблиц
3. WebSocket / SSE
4. Виртуальный скроллинг
5. Helper versioning (v1/v2 файлы)
6. Перевод pilot/queue UI на TypeScript
7. Merge feature-ветки в main (оставлено пользователю)

## Файлы изменены

В `delivery-contenthunter` (prod):
- `paginate.js` (новый, 140 строк)
- `paginate.test.js` (новый, 165 строк)
- `public/paginated-table.js` (новый, 255 строк)
- `server.js` (строки 28-52 → require; pilot endpoints 1862-2045 → helper; queue endpoint 1453-1494 → +sort/filter whitelist + cursor pagination + stats + by-ids)
- `public/index.html` (script tag паги-helper'а; pilot и queue UI блоки переписаны через factory; TDZ hotfix wrap)

В `contenthunter` (текущая ветка `fix/testbench-publisher-base-imports-20260427`):
- `.ai-factory/plans/2026-04-28-paginated-tables-etap2.md` (план, untracked при первом запуске, добавляется в T16)
- `.ai-factory/evidence/paginated-tables-etap2-20260428.md` (этот файл)
