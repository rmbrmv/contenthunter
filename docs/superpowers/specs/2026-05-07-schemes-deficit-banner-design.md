# Schemes Deficit Banner — Design Spec

**Date:** 2026-05-07
**Status:** Design — pending implementation plan
**Revision:** v3 (post-Codex v2 review — applied cleanup)
**Project:** validator-contenthunter (Vue 3 SPA + FastAPI backend)

## Problem

После отгрузки sub-project A (unic-sweep) выявился pre-existing бизнес-фильтр: 6 проектов имеют `approvedSchemes < packs` и потому их слоты на сегодня skipped в `runAutoUnicForDate`. Клиенты этого не видят — им кажется что "запланировано не выкладывается" без объяснения причины.

Цель — превентивно сигнализировать клиенту в `/dashboard` (раздел «Планировщик»):
1. **Сколько схем одобрено и сколько нужно** (top banner)
2. **На каждом конкретном слоте** — что он не уйдёт в публикацию из-за этого (per-slot badge)
3. **CTA-линк** в `/client/schemes` для одобрения

## Goals

- Клиент с дефицитом видит баннер на `/dashboard` сразу при открытии страницы.
- Клик «Одобрить схемы →» ведёт в нужное место (для клиента — `/client/schemes`, для admin/manager — `/admin/scheme-preferences` с pre-selected проектом).
- В режиме «все проекты» (admin/manager) баннер агрегирует список проблемных проектов; раскрывается по клику в inline-список.
- Per-slot бейдж показывается на каждом слоте чьего проекта approved < min_required.
- Минимальная нагрузка на backend: один новый endpoint, без N+1 запросов.

## Non-goals

- Не дублируем функциональность `/client/schemes` (мастер одобрения остаётся как есть).
- Не делаем bulk-approve в баннере (CTA ведёт в существующий flow).
- Не меняем backend pipeline (`runAutoUnicForDate`, sweep) — это только UI-сигнал поверх существующей логики.
- Не делаем real-time обновления (WebSocket / SSE) — refetch при mount + ручной refresh.
- Не модифицируем существующий `/api/schemes/summary/{project_id}` (per-project endpoint остаётся).
- Не делаем баннер на других страницах (/upload, /publications, /content/:id) — только на `/dashboard`.

## Architecture

### Backend

**Новый endpoint:** `GET /api/schemes/deficits`

Файл: `backend/src/routers/schemes.py` (добавить новую функцию).

### Authorization (Codex BLOCKER #1)

Allowed project IDs **строго** из server-side authenticated user (JWT/session DB-claim). НЕ читаем `X-Project-Id` header или query-параметр — это display-only state на фронтенде, не источник прав.

- role=`client` → `[current_user.project_id]` если не None; иначе `[]` → ранний return.
- role=`manager` → `current_user.project_ids` (массив из БД, prepopulated в JWT/session). Если пусто — `[]`, никаких "fall through to all".
- role=`admin` → все project_ids из канонической project-таблицы. **Решено (v3, Codex IMPORTANT #2):** источник = `SELECT DISTINCT project_id FROM factory_pack_accounts WHERE project_id IS NOT NULL`. Self-consistent с расчётом min_required (проект без packs = min_required=0 = не показывается в дефицитах в любом случае). НЕ использовать `validator_projects` отдельно — это могло бы привести к admin'у, видящему проекты без packs (для которых дефицит логически не определён).
- Любая другая роль → 403.

Cross-tenant контроль: тест должен попытаться spoof'нуть `X-Project-Id` header и проверить что ответ не меняется.

### Single grouped query (Codex IMPORTANT #3)

Не циклить `get_summary()` per-project (60 SELECT'ов на admin-load). Один query с CTE:

```sql
WITH allowed AS (
  -- $1 = ARRAY of allowed project_ids (validated server-side)
  SELECT unnest($1::int[]) AS project_id
),
packs AS (
  SELECT project_id, COUNT(*) AS pack_count
  FROM factory_pack_accounts
  WHERE project_id IN (SELECT project_id FROM allowed)
  GROUP BY project_id
),
approved AS (
  SELECT sp.project_id, COUNT(*) AS approved_count
  FROM validator_scheme_preferences sp
  JOIN unic_schemes us ON us.id = sp.scheme_id AND us.status = true
  WHERE sp.status = 'approved'
    AND sp.project_id IN (SELECT project_id FROM allowed)
  GROUP BY sp.project_id
)
SELECT
  p.project_id,
  p.pack_count                          AS min_required,
  COALESCE(a.approved_count, 0)         AS approved,
  p.pack_count - COALESCE(a.approved_count, 0) AS missing
FROM packs p
LEFT JOIN approved a ON a.project_id = p.project_id
WHERE p.pack_count > 0
  AND p.pack_count > COALESCE(a.approved_count, 0)
ORDER BY p.project_id;
```

Один query, индексы существуют (`ix_validator_scheme_preferences_project_id`, `factory_pack_accounts_pkey` — не оптимально по project_id; см. risk).

### Count semantics (Codex IMPORTANT #3)

- `min_required = COUNT(*) FROM factory_pack_accounts WHERE project_id=?`. Каждая строка в этой таблице = независимый аккаунт-в-паке-для-публикации. Дубликаты project_id ОЖИДАЮТСЯ (несколько паков на проект); это НЕ ошибка. `COUNT(*)`, не `COUNT(DISTINCT)`.
- `approved = COUNT(*) FROM validator_scheme_preferences WHERE project_id=? AND status='approved' JOIN unic_schemes ON ... AND status=true`. UNIQUE constraint `uq_project_scheme(project_id, scheme_id)` гарантирует что pre row = pre scheme. `COUNT(*)` корректно равно `COUNT(DISTINCT scheme_id)`. Для устойчивости в случае будущих schema-изменений можно использовать `COUNT(DISTINCT sp.scheme_id)` явно — overhead минимальный.

### No query parameters (Codex IMPORTANT #4)

Endpoint signature: `GET /api/schemes/deficits` — **без** query-параметров. Backend не принимает `?project=`, `?role=` и подобное. Это гарантирует что весь scope — server-side, через JWT. Тест: client запрашивает `/api/schemes/deficits?project=999` → query-param игнорируется (FastAPI не подключает к функции).

### Project identity (Codex BLOCKER #2)

**НЕ** деривируем имя через `factory_pack_accounts.pack_name → strip suffix`. Backend возвращает только `project_id`. Frontend резолвит project_name через **существующий project store** (Pinia store с `allProjects: [{id, project, ...}]`, см. recon `frontend/src/stores/project.ts`). Если store не имеет проекта — fallback на `Project ${id}` плейсхолдер.

Pre-flight для writing-plans (Q2): подтвердить структуру project store + существование `validator_projects` или `factory_projects` table для admin-mode (где admin может видеть проекты которых нет в personal `project_ids`).

### Response format (Codex MINOR #13)

```json
[
  {"project_id": 79, "approved": 5, "min_required": 9, "missing": 4},
  {"project_id": 81, "approved": 7, "min_required": 9, "missing": 2}
]
```

(Без project_name — frontend резолвит.)

### Errors

- 401 (no auth) → 401 (FastAPI auth dependency)
- 403 (unknown role) → 403
- 5xx (DB error) → 500 + structured backend log

### Logging (Codex MINOR #14)

Структурированный logger.info/debug, без полных списков project_ids в info-level:
```python
logger.info("schemes_deficits", extra={"role": role, "project_count": len(allowed_ids), "returned": len(result), "took_ms": elapsed_ms})
```
Полный список project_ids — только debug-level.

### Frontend

**Composable:** `frontend/src/composables/useSchemesDeficits.ts` (новый):
- Reactive state: `deficits: Ref<DeficitEntry[]>`, `deficitsByProjectId: ComputedRef<Map<number, DeficitEntry>>` — единственный источник истины (Codex IMPORTANT #4)
- `fetch()` — вызывает `GET /api/schemes/deficits` БЕЗ `projectHeaders()` для этого endpoint'а (auth уже в JWT — см. backend §). Однако для admin/manager если фронтенд хочет filter'нуть по `viewMode='single'` selectedProjectId — это computed-фильтр поверх массива, НЕ передача header'а.
- **Cache policy (Codex IMPORTANT #8):** НЕ кешировать долго. Refetch при каждом mount компонента + при возврате на `/dashboard` через router-hook (`watch` на `route.path`). Опционально 30-секундный server-side cache (FastAPI middleware) для admin запросов — но это в backlog, не в первой версии.
- Helpers (Codex IMPORTANT #6 — null-safe):
  - `hasDeficitFor(projectId: number | null | undefined): boolean` — false для `null/undefined/NaN`, иначе lookup в Map.
  - `deficitFor(projectId: number | null | undefined): DeficitEntry | null` — то же.
- Error states: `loading`, `error` (для вывода "статус схем недоступен" подсказки в DevTools без пользовательского noise — Codex IMPORTANT #9).

**Banner component:** `frontend/src/components/SchemesDeficitBanner.vue` (новый):
- Props: `deficits: DeficitEntry[]`, `viewMode: 'single' | 'all'`, `currentProjectId?: number | null`, `userRole: string`
- Resolves project_name из существующего project store (см. § Project identity) — `useProjectStore().findById(id)?.project ?? \`Project ${id}\``
- **Single mode:** показывается только если `deficitFor(currentProjectId)` возвращает non-null (используем единый null-safe helper, не прямой `Map.has` — Codex IMPORTANT #5). Single-line banner с числами + кнопка CTA.
- **All mode (Codex IMPORTANT #7):** глобальный (across all accessible projects), не scoped к видимой неделе. Copy: "**N проектов с заблокированной публикацией.** Раскрыть список ↓". В раскрытом списке — каждая строка `<project_name>: X/Y · [Одобрить →]` (Codex MINOR #15: per-project CTA в expanded list).
- CTA-линк (final):
  - role=client → `/client/schemes` (один маршрут, проект уже привязан к client'у)
  - role=manager/admin **single mode** → `/admin/scheme-preferences?project=<id>`
  - role=manager/admin **all mode top-button** → `/admin/scheme-preferences` (generic, без preselect — пусть выбирают на странице)
  - role=manager/admin **all mode per-row in expanded list** → `/admin/scheme-preferences?project=<row.project_id>`
- **Visual (Codex MINOR #16):** убираем emoji 🚫 в badge, оставляем только текстовый "Не хватает схем" с red bg. В banner допустим одиночный info-icon из существующего lucide/heroicons библиотеки (если есть в проекте — pre-flight).

**Per-slot badge:** добавить в **ОБА** рендерера:
1. `frontend/src/components/SlotCard.vue` (manager-side)
2. inline в `frontend/src/pages/client/ClientDashboard.vue` (client-side)

Per-slot badge — небольшой inline `<span>` блок с условным рендерингом:
```vue
<span
  v-if="hasDeficit"
  class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold text-red-700 bg-red-100 border border-red-200 rounded"
  :title="deficitTooltip"
>Не хватает схем</span>
```

`hasDeficit: boolean` и `deficitTooltip: string` — оба prop'а пробрасываются сверху из родителя (Codex IMPORTANT #4: badges и banner используют ОДНУ Map из composable). Tooltip строится в parent: `Одобрено ${approved} из ${min_required} схем уникализации` (NB: `Об` и `из` со строчной — обычные слова).

Slot project_id source (Codex IMPORTANT #12): использовать тот же field, что и существующий код в render — recon показал `slot.project_id` (line 158 ClientDashboard.vue: `:title="slot.project_name"`). Если в `SlotCard.vue` поле названо иначе — pre-flight grep'ом найти canonical name. Если `slot.project_id` бывает null/undefined для ещё-не-заполненных слотов — наш null-safe helper вернёт `false`.

**Integration в `ClientDashboard.vue`:**
- В `<script setup>` импортировать composable, вызвать `fetch()` в `onMounted`
- Перерасчёт при `viewMode/selectedProjectId` change
- В template: вставить `<SchemesDeficitBanner ... />` ПОД header'ом, ДО week-navigator
- При рендеринге слота — пробросить `hasDeficit="hasDeficitFor(slot.project_id)"` в badge

## Data flow

```
[/dashboard mount]
   ↓ apiClient.get('/api/schemes/deficits')  [no query params]
[Backend] schemes.py → resolve allowed_ids server-side (JWT/session)
                    → single CTE query (packs JOIN approved-schemes)
                    → filter min_required > approved
   ↓ DeficitEntry[] {project_id, approved, min_required, missing}
[Frontend composable] deficits ref set; deficitsByProjectId computed Map
   ↓
[Banner] uses deficitFor(currentProjectId) (single-mode) или deficits.length (all-mode)
[SlotCard / inline slot] uses hasDeficitFor(slot.project_id) — null-safe

[user clicks CTA "Одобрить схемы →"]
   ↓
client: /client/schemes
manager/admin single-mode: /admin/scheme-preferences?project=<id>
manager/admin all-mode top: /admin/scheme-preferences (generic)
manager/admin all-mode per-row: /admin/scheme-preferences?project=<row.id>
```

## Error handling

- 401/403 на /api/schemes/deficits → composable swallows, banner hidden (no UI noise)
- 5xx → composable пишет в console.error, banner hidden
- Empty array → banner hidden, badges не показываются

## Observability

- Backend: structured logger (см. § Logging выше) — `logger.info("schemes_deficits", extra={"role": ..., "project_count": ..., "returned": ..., "took_ms": ...})`. Полный список project_ids — только debug-level. Никаких ad-hoc print/console-log per request.
- Frontend: ничего специального; Vue Devtools покажет state composable; 4xx/5xx логируются в `console.error` со структурированным payload (`{tag: 'schemes-deficits', status, message}`).
- Не нужны метрики — фича read-only поверх существующих данных.

## Testing

### Backend (pytest, `backend/tests/`)

| Тест | Setup | Expect |
|---|---|---|
| **B1** | client с project_id=79 (5/9 deficit) | 1 элемент `{project_id:79, approved:5, min_required:9, missing:4}` |
| **B2** | client с project_id=99 (full coverage 9/9) | empty array |
| **B3** | client с project_id=NULL | empty array |
| **B4** | manager с project_ids=[79,80,81], deficits на 79 и 81 | 2 элемента (без 80) |
| **B5** | admin (все проекты), 6 deficits | 6 элементов |
| **B5b** | manager с **project_ids=[]** (пусто) | empty array; никаких "fall through to all projects"; 0 SQL queries against project tables |
| **B6** | проект без packs (min_required=0) | НЕ включается |
| **B7** | unauthenticated → 401 |
| **B8** (cross-tenant, Codex IMPORTANT #10) | client с project_id=79 отправляет `X-Project-Id: 80` header | Header игнорируется. Ответ — только проект 79. |
| **B9** (cross-tenant) | manager с project_ids=[79] отправляет `X-Project-Id: 999` header | Header игнорируется. Ответ — только дефициты project_id=79. |
| **B10** (role escalation) | role=`producer` (не client/manager/admin) → 403 |

Использовать существующий `engine.dispose` autouse fixture (см. memory `feedback_validator_test_engine_dispose.md`).

**Performance smoke (Codex IMPORTANT #3):** `B11` тест считает количество SQL-запросов через SQLAlchemy event listener (если есть hook в существующих тестах — переиспользовать). Запрос `/api/schemes/deficits` для admin с 30 проектами → ровно 1 query на project-data (CTE), без N+1.

### Frontend (test runner — pre-flight в writing-plans, см. Q1)

| Тест | Setup | Expect |
|---|---|---|
| **F1** | composable без deficits → banner v-if=false, badges не показываются |
| **F2** | composable с 1 deficit + viewMode='single' с этим project_id → single-line banner с правильными числами |
| **F2b** | composable с 1 deficit + viewMode='single' с **другим** project_id → banner НЕ показывается, badges на slot'ах с deficit-project показываются (orthogonal data sources) |
| **F3** | composable с 3 deficits + viewMode='all' → агрегированный banner "3 проекта", expanded list имеет 3 строки + per-row CTA |
| **F4** (helper, Codex IMPORTANT #6) | `hasDeficitFor(null)`, `hasDeficitFor(undefined)`, `hasDeficitFor(NaN)` все возвращают `false` |
| **F5** | CTA-линк для role='client' → href='/client/schemes' |
| **F6** | CTA-линк для role='admin' single mode → href='/admin/scheme-preferences?project=79' |
| **F6b** | CTA-линк для role='manager' all mode top-button → href='/admin/scheme-preferences' (без project param) |
| **F6c** | CTA-линк per-row in expanded list → href='/admin/scheme-preferences?project=<that-row-id>' |
| **F7** (mode switching, Codex IMPORTANT #4) | viewMode all → single → another single → видим banner switch'ит без stale state |

### Integration tests (Codex IMPORTANT #11)

Mount-тесты для **обоих** рендереров слотов с подключённым composable:

| Тест | Setup | Expect |
|---|---|---|
| **I-S1** | mount `SlotCard.vue` (manager renderer) с props slot.project_id=79, deficits map содержит 79 | badge виден |
| **I-S2** | mount `SlotCard.vue` с slot.project_id=80, deficits map не содержит 80 | badge не виден |
| **I-D1** | mount `ClientDashboard.vue` с client-роль и project_id=79 (deficit), seed slots на этой неделе | banner виден + badges на client inline-render слотах |
| **I-D2** | mount `ClientDashboard.vue` с slot.project_id=null | badge не виден (null-safe) |
| **I-D3** | After-fetch state change (deficits initially empty → re-fetch with 1 entry) → badge appears reactively |

### Manual smoke

1. Открыть `/dashboard` под клиентом проекта 79 → увидеть red banner "5/9 схем" + per-slot badges на всех слотах project=79.
2. Открыть `/dashboard` под admin'ом, single mode выбран project 79 → то же что #1.
3. Admin all-mode → агрегированный banner "X проектов" + per-slot badges по всем deficit-проектам.
4. Клик «Одобрить схемы →» переходит на правильную страницу.
5. После одобрения недостающих схем на /client/schemes и возврата на /dashboard → composable refetch'ит на mount (нет client-side cache в v1) → banner и бейджи пропадают сразу (без manual refresh страницы).

## Rollout

**Order matters (Codex MINOR #17):** backend deploy ПЕРЕД frontend, чтобы избежать окна, в котором фронт зовёт несуществующий endpoint и баннер тихо скрывается.

1. **Dev (validator-contenthunter):** ветка `feature/schemes-deficit-banner-2026-05-07`. Worktree (memory `feedback_parallel_claude_sessions.md`).
2. **Backend impl + tests** — запустить pytest, smoke `/api/schemes/deficits` через curl с реальным JWT для client/manager/admin. Применить также cross-tenant тесты (B8/B9).
3. **Backend deploy first:** cherry-pick backend изменений в prod main → `pm2 restart <validator-backend-process-name>` (имя — pre-flight Q5). **Verify endpoint per role** (Codex IMPORTANT #7):
   - `curl -H "Cookie: session=<client-jwt>" https://client.contenthunter.ru/api/schemes/deficits` → 0 или 1 entry (если client.project_id в дефиците)
   - `curl -H "Cookie: session=<manager-jwt>" ...` → дефициты только из manager.project_ids
   - `curl -H "Cookie: session=<admin-jwt>" ...` → ожидаемо 6 entries (Aneco, Inakent, и т.п. — известные на 2026-05-07)
   - `curl ... /api/schemes/deficits?project=999` → query-параметр игнорируется, ответ как без него (B-test эквивалент)
   Если хоть одна из них падает 5xx или возвращает не-то — STOP, не катить frontend.
4. **Frontend impl + tests** — `npm run build` (auto-postbuild копирует в `/var/www/validator/`).
5. **Frontend deploy:** cherry-pick frontend в prod main → npm run build → готово (постбилд авто-копирует).
6. **Smoke на проде:** открыть `client.contenthunter.ru/dashboard` под одним из 6 проблемных проектов (79/81/83/85), увидеть banner + badges. Под admin'ом all-mode — увидеть aggregated banner.
7. **Monitoring T+15 мин:** `pm2 logs validator-backend | grep schemes_deficits` — активность endpoint'а. Запросить тестового клиента screenshot чтобы подтвердить визуал.
8. **Rollback:** `git revert <merge_sha>` (отдельно для backend и frontend). PM2-restart соответствующего процесса. Никаких миграций.

## Risks

| Риск | Вероятность | Митигация |
|---|---|---|
| `/api/schemes/deficits` для admin'а с 30+ проектами медленный | Низкая | Один CTE-query (см. § Backend), не N+1. Indexed на `validator_scheme_preferences.project_id`; `factory_pack_accounts` без индекса по project_id — full-scan приемлем при <10K строк. Pre-flight: `EXPLAIN ANALYZE` на проде до релиза. |
| Project store на фронте не содержит проект для admin'а в all-mode | Низкая | Fallback `Project ${id}` в banner expanded list. Acceptable UX; admin всё равно увидит project_id и может определиться. |
| Клиент видит баннер от другого проекта (cross-tenant leak) | Низкая | Backend строго фильтрует server-side. Тесты B1+B2+B8+B9 покрывают (header-spoof, query-param spoof, multi-project manager scope). |
| Per-slot badge ломает существующий layout слота | Средняя | Проверить визуально оба рендерера до commit. Inline-flex с small text (10px шрифт). Без `position: absolute` (могут быть z-index конфликты в существующем UI). |
| `validator_scheme_preferences` или `factory_pack_accounts` имеют дубликаты, инфлирующие counts | Низкая | UNIQUE `uq_project_scheme` гарантирует non-dup approved. Для packs дубликаты project_id ОЖИДАЕМЫ (= пакаунт count). См. § Count semantics выше. |

## Open questions для writing-plans

| Q | Что проверить |
|---|---|
| **Q1** | Frontend test runner: vitest или jest? Pre-flight `cat package.json`. Если ничего — добавить vitest dev-dep (предпочтительно для Vue) или fall back на node:test. |
| **Q2** | ~~Canonical таблица для project списка admin-mode'а~~ ✅ resolved (v3): `SELECT DISTINCT project_id FROM factory_pack_accounts WHERE project_id IS NOT NULL`. Self-consistent с min_required и не требует отдельной project-таблицы. |
| **Q3** | Composable-pattern: `ls frontend/src/composables/` (если папка пуста — создаём первый файл с этим паттерном; OK для нашего случая). |
| **Q4** | Auth/role: `current_user.project_ids` уже есть в `Auth` Pydantic model для manager? Pre-flight `grep -nE "project_ids" backend/src/models backend/src/auth*`. Если только `project_id` (одиночный) — manager может быть только привязан к одному проекту? Это меняет дизайн B4. |
| **Q5** | PM2 process names на проде: уточнить `validator` vs `validator-backend` vs `validator-frontend` (frontend обычно serve через nginx из /var/www/validator/, не отдельный pm2 process). |
| **Q6** | Иконка-библиотека (lucide / heroicons / homemade) для info-icon в banner — pre-flight `grep -rE "lucide-vue\|heroicons" frontend/package.json frontend/src/components`. Если нет — текстовый emoji-free дизайн. |

## Decisions captured

- Single endpoint `/api/schemes/deficits` (не extend существующий `/api/schemes/summary/{project_id}` — sep responsibility)
- **Single SQL CTE-query** вместо цикла per-project (Codex IMPORTANT #3)
- **Auth — server-side only,** игнорируем `X-Project-Id` для этого endpoint'а (Codex BLOCKER #1)
- **Project name резолвится на фронте** через project store, backend возвращает только project_id (Codex BLOCKER #2)
- Response поле `missing` на бэке (Codex MINOR #13)
- Composable + reactive ref + computed Map deficitsByProjectId — единый источник истины
- **No client-side cache** (refetch on mount + on /dashboard re-entry); Codex IMPORTANT #8
- Per-slot badge inline в обоих рендерерах (memory `feedback_validator_two_slot_renderers.md`)
- Aggregated banner expandable (clickable disclosure)
- All-mode banner **глобальный** (не scoped к видимой неделе) — Codex IMPORTANT #7
- CTA URLs: client→/client/schemes; admin/manager single→preselect; admin/manager all top-button → generic; per-row in expanded list → preselect (Codex MINOR #15)
- **Visual:** убрали emoji в badge, `Не хватает схем` text-only (Codex MINOR #16)
- **Deploy:** backend first → smoke endpoint → frontend (Codex MINOR #17)

## Codex review iterations
- v1 review: 2 BLOCKER (auth, project name) + 9 IMPORTANT + 4 MINOR — applied → v2.
- v2 review: 0 BLOCKER + 7 IMPORTANT + 3 MINOR — preimущественно cleanup stale wording от v1; applied → v3 (этот документ). Verdict APPROVE-WITH-CHANGES.
- Convergence: после v3 ожидаем APPROVE без новых блокеров. Open questions Q1/Q4/Q5/Q6 — runtime pre-flight checks для writing-plans, не дизайн-уровень.
