# BACKLOG — Paginated Tables (after etap 1+2 ✅)

**Создан:** 2026-04-28 после закрытия этапа 2.
**Контекст:** этапы 1 (`/publishing/tasks`) и 2 (`/publishing/queue` + extract helper'ов) отгружены и merged в main. Memory: `project_paginated_tables_pilot.md`. Helper API: `paginate.js` (server) + `paginated-table.js` (frontend).

## Что в этом backlog'е

Это not-yet-claimed работа для следующих сессий. Каждый пункт оценён по приоритету (P0 — мешает дальше работать, P1 — пора сделать, P2 — можно отложить, P3 — nice-to-have). Сделано → отмечать ✅ + ссылку на commit/evidence.

---

## P1. Этап 3 — раскатка helper'а на 7 таблиц

**Цель:** перевести оставшиеся таблицы на cursor-pagination + server-side filters/sort/stats через готовый helper. Каждая — отдельный PR (~0.5 дня).

**Приоритет внутри этапа 3 (из spec §6.3):**

| # | Endpoint | Размер | Live? | Заметки |
|---|---|---|---|---|
| 1 | `/api/archive/tasks` | 6 360+ строк | ❌ | Самая большая, юзер заметит ускорение. liveRefresh=false. **EXPLAIN обязателен** — добавить композитный индекс если cursor-path делает Seq Scan + Sort. |
| 2 | `/api/unic/tasks` | 1 540 | ✅ | Активная очередь уникализации. liveRefresh=true. |
| 3 | `/api/factory/tasks` + `/api/factory/accounts` | 1 253 | ✅ | factory_inst_accounts. Может быть составным (две таблицы на одной странице). |
| 4 | `/api/whatsapp/tasks` | ? | ✅ | Размер уточнить EXPLAIN'ом. |
| 5 | `/api/telegram/tasks` | ? | ✅ | Аналогично. |
| 6 | `/api/phone-warm/tasks` | ? | ✅ | Минор по объёму, но «за единообразие». |
| 7 | `/api/tasks` (общий) | ? | ? | Аудит на этапе планирования: мигрировать или дропнуть как legacy. |

**Чек-лист каждой миграции:**
1. [ ] EXPLAIN для дефолтной сортировки (+ для cursor-предиката `(sort_col, id) cmpOp (...)`). Если Seq Scan + Sort на >5k строк — добавить композитный индекс отдельной миграцией ДО endpoint'а.
2. [ ] Server: добавить SORT_WHITELIST + buildXxxFilters + переписать handler через `buildPaginatedQuery` + `processPaginatedResult`. Backwards-compat: без `limit`/`cursor` → legacy array.
3. [ ] Server: добавить `/stats` (через `buildStatsQuery`) + `/by-ids` (через `buildByIdsQuery`) — `/by-ids` опционален, нужен только если frontend ставит `liveRefresh=true`.
4. [ ] Frontend: добавить sentinel-row в HTML; создать factory instance через `createPaginatedTable({...})`; заменить старые state-переменные/функции на тонкие wrappers.
5. [ ] **TDZ guard** — если legacy load-функция вызывается синхронно из `nav()` / `switchModule()` / IIFE-инициализатора, обернуть тело в `try/catch ReferenceError + setTimeout(0) defer`. Урок этапа 2 — без этого pageload падает на TDZ. См. evidence/paginated-tables-etap2-20260428.md «TDZ post-mortem».
6. [ ] Smoke: legacy diff (byte-identical), paginated 1-я страница, /stats, /by-ids, cursor 2-я страница, negative (invalid cursor → fall-back, sort key mismatch → 400, invalid sort → 400), filter+pagination.
7. [ ] Browser smoke (golden path + 2 edge-cases).
8. [ ] Evidence + memory update.

**Эстимейт:** ~7 PR'ов, каждая 0.5 дня. Можно за неделю при последовательной работе.

---

## P1. Backport pilot + etap2 в `autowarm-testbench`

**Контекст:** pilot и etap2 жили только в prod (`/root/.openclaw/workspace-genri/autowarm/`); testbench (`/home/claude-user/autowarm-testbench/`, branch `testbench`) **не получил** ни помощник, ни новые endpoints. Testbench отстаёт ~5 коммитов.

**Когда понадобится:** при следующем dev-cycle через testbench (новая feature-разработка для publishing-страниц или smoke-tests на тестовом устройстве).

**Что сделать:**
1. `cd /home/claude-user/autowarm-testbench/`
2. `git fetch && git pull origin testbench`
3. Cherry-pick: `da10b80` (paginate.js), `42b3581` (paginated-table.js + UI), `4a81909` (TDZ hotfix). Или просто `git checkout main -- paginate.js paginate.test.js public/paginated-table.js` плюс merge соответствующих частей `server.js` + `public/index.html`.
4. `node --test paginate.test.js` — должны пройти 19/19.
5. `pm2 restart autowarm-testbench` — `🔍 Validating index.html JS` пройдёт автоматически (pre-restart hook).
6. Smoke на testbench порту (3849? уточнить).

**Риск:** node_modules symlink в testbench может сломаться при merge (memory: `feedback_autowarm_testbench_deploy.md`). Нужен `npm install` после.

**Эстимейт:** 1 час.

---

## P2. Удалить BC (backwards-compat) layer

**Где:** `/api/publish/tasks` (legacy блок 1862-1874) и `/api/publish/queue` (legacy блок ~1481-1494) — обе ветки отдают плоский array без `limit`/`cursor`.

**Когда удалять:** после того как **все** frontend-страницы и сторонние клиенты (если есть) перейдут на cursor-paginated формат.

**Сейчас:** оба endpoint'а вызываются с `limit` из factory'и. Без `limit` — legacy. Если grep по всем кодовым базам не находит client'ов, дёргающих без `limit`, можно дропать.

**Чек-лист:**
1. [ ] `grep -rn "/api/publish/tasks" --include='*.js' --include='*.ts' --include='*.py' --include='*.html'` — найти всех вызывающих, убедиться что все передают `limit`.
2. [ ] Аналогично для `/api/publish/queue`.
3. [ ] Удалить legacy блоки в server.js. Заменить на default (limit=100 если не передан вместо BC).
4. [ ] Smoke + commit.

**Риск:** если внешний скрипт/cron дёргает endpoint без params (unlikely, но возможно) — он сломается. Перед удалением лучше один день мониторить логи на предмет таких запросов.

**Эстимейт:** 1 час + 1 день мониторинга.

---

## P2. EXPLAIN audit для `publish_tasks` на свежих данных

**Контекст:** EXPLAIN снимали на этапе 1 при ~1.4k строк. На этапе 2 не повторяли. Если таблица доросла до 5k+, cursor-предикат `(sort_col, id) cmpOp (...)` может стать Seq Scan + Sort вместо Index Scan.

**Что сделать:**
```sql
EXPLAIN ANALYZE SELECT pt.*, pq.media_url AS s3_url, ... FROM publish_tasks pt
LEFT JOIN publish_queue pq ON ...
WHERE (pt.created_at, pt.id) < ('2026-04-28T10:00:00Z', 50)
ORDER BY pt.created_at DESC, pt.id DESC LIMIT 100;
```
Для каждого sort-варианта (created_at, updated_at, scheduled_at, status, platform, device_serial). Если Seq Scan на >5k — добавить композитный индекс.

**Эстимейт:** 30 минут.

---

## P3. TypeScript-типизация helper'ов

**Контекст:** `paginate.js` и `paginated-table.js` написаны как plain JS с JSDoc. Типизация дала бы:
- автоcomplete в IDE для `createPaginatedTable({...})`
- compile-time check на missing required params
- лучшие dev-experience при работе с factory.getState() и event callbacks

**Что сделать:**
1. Конвертировать `paginate.js` в `paginate.ts`. Цели: `interface PaginatedQueryConfig`, `interface CursorObject`, generic `<TRow>` для row shape.
2. Конвертировать `paginated-table.js` в `paginated-table.ts` или сделать `paginated-table.d.ts` рядом.
3. Настроить компиляцию в `paginate.js` (output) + `dist/paginated-table.js` или inline-compile.

**Риск:** нужен build-step. Сейчас autowarm — pure Node без bundler/transpiler. Усложнение деплоя.

**Альтернатива (дешевле):** просто добавить более detailed JSDoc + typedef в существующих файлах. IDE подхватит без TS.

**Эстимейт:** 4 часа full TS, 1 час JSDoc-only.

---

## P3. Виртуальный скроллинг при N > 2000

**Контекст:** factory сейчас держит ВСЕ загруженные строки в DOM. Если юзер автоscroll'ил 20 страниц по 100 строк = 2000 `<tr>` в DOM. Может стать заметным при N>3000 (моргание, scroll-jank).

**Что сделать (если станет проблемой):** добавить in-view DOM recycling — снимать строки выше viewport, переустанавливать когда скроллит вверх. См. библиотеки типа `react-window` для inspiration. На vanilla JS реализуется через `IntersectionObserver` per-row + manual DOM manipulation.

**Риск низкий:** В нашем случае user редко доскролливает дальше 5-10 страниц (есть safety brake). Появится только если скрытые задачи перевалят порог.

**Эстимейт:** 1 день full implementation, или 2 часа на prototype + benchmark.

---

## P3. Helper versioning на случай breaking change

**Контекст:** spec § 6 предусмотрел fork helper'а на `paginate-v1.js` / `paginate-v2.js` если потребуется. Сейчас один файл, все таблицы на нём.

**Когда применить:** ТОЛЬКО если кто-то из callers потребует поведение, несовместимое с остальными (например, новый sort-formate, который сломает старые curl'ы). До того — НЕ форкаем (premature versioning).

**Эстимейт:** 0 пока не понадобится; тогда 2 часа на форк + миграцию подвыборки.

---

## Closed (этап 2)

- ✅ Extract `paginate.js` (server helper) — commit `da10b80` 2026-04-28
- ✅ Extract `paginated-table.js` (frontend factory) — commit `42b3581` 2026-04-28
- ✅ Migrate `/api/publish/queue` на cursor-pagination + `/stats` + `/by-ids` — `da10b80`
- ✅ Rewrite pilot `/api/publish/tasks` через helper (byte-identity verified) — `da10b80`
- ✅ Rewrite pilot frontend через factory (no regression) — `42b3581`
- ✅ Migrate queue UI на factory — `42b3581`
- ✅ TDZ hotfix — `4a81909`
- ✅ Browser smoke — пройден 2026-04-28
- ✅ Merge feature/paginated-tables-etap2-20260428 → main — `badcc31` 2026-04-28
- ✅ Memory updated — `project_paginated_tables_pilot.md`
- ✅ Evidence — `.ai-factory/evidence/paginated-tables-etap2-20260428.md`
