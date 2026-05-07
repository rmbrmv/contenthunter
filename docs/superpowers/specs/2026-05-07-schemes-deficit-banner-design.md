# Schemes Deficit Banner — Design Spec

**Date:** 2026-05-07
**Status:** Design — pending implementation plan
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

Файл: `backend/src/routers/schemes.py` (добавить новую функцию). Использует существующий `schemes_service` для подсчётов.

Логика:
1. Определить список доступных пользователю project_ids:
   - role=`client` → `[current_user.project_id]` если он не None, иначе пустой список → возвращаем `[]`
   - role=`manager` → `current_user.project_ids` (массив доступа)
   - role=`admin` → все project_ids из `factory_projects` (или `validator_projects` — тот же `factory_pack_accounts.project_id` source-of-truth)
2. Для каждого project_id вызвать `schemes_service.get_summary(project_id)` → `{approved, min_required, ...}`.
3. Отфильтровать `approved < min_required AND min_required > 0`.
4. JOIN с project name (через `factory_pack_accounts.pack_name → strip suffix` или существующий маппинг).

Ответ:
```json
[
  {"project_id": 79, "project_name": "Aneco", "approved": 5, "min_required": 9},
  {"project_id": 81, "project_name": "Inakent", "approved": 7, "min_required": 9}
]
```

Производительность — O(N projects) per request, для admin (N=~30) это OK на dashboard load.

### Frontend

**Composable:** `frontend/src/composables/useSchemesDeficits.ts` (новый):
- Reactive `deficits: Ref<DeficitEntry[]>`
- `fetch()` — вызывает `GET /api/schemes/deficits` с `projectHeaders()` (см. `stores/project.ts`)
- TTL-кеш на 10 минут (in-memory, per-session)
- Helper `hasDeficitFor(projectId): boolean`
- Helper `deficitFor(projectId): DeficitEntry | null`

**Banner component:** `frontend/src/components/SchemesDeficitBanner.vue` (новый):
- Props: `deficits: DeficitEntry[]`, `viewMode: 'single' | 'all'`, `currentProjectId?: number`, `userRole: string`
- Если `viewMode === 'single'` И есть deficit для `currentProjectId` → single-line banner с числами + CTA
- Если `viewMode === 'all'` И deficits.length > 0 → агрегированный baner ("N проектов") с раскрывающимся списком
- CTA-линк: для client → `/client/schemes`; для manager/admin → `/admin/scheme-preferences?project=<id>` (если single) или `/admin/scheme-preferences` (если all-mode без выбранного проекта)

**Per-slot badge:** добавить в **ОБА** рендерера:
1. `frontend/src/components/SlotCard.vue` (manager-side)
2. inline в `frontend/src/pages/client/ClientDashboard.vue` (client-side)

Per-slot badge — небольшой inline `<span>` блок с условным рендерингом:
```vue
<span
  v-if="hasDeficit"
  class="inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold text-red-700 bg-red-100 border border-red-200 rounded"
  title="Одобрено X из Y схем уникализации"
>🚫 Не хватает схем</span>
```

Где `hasDeficit` пробрасывается prop'ом сверху (рассчитывается в `ClientDashboard.vue` через composable).

**Integration в `ClientDashboard.vue`:**
- В `<script setup>` импортировать composable, вызвать `fetch()` в `onMounted`
- Перерасчёт при `viewMode/selectedProjectId` change
- В template: вставить `<SchemesDeficitBanner ... />` ПОД header'ом, ДО week-navigator
- При рендеринге слота — пробросить `hasDeficit="hasDeficitFor(slot.project_id)"` в badge

## Data flow

```
[/dashboard mount]
   ↓ apiClient.get('/api/schemes/deficits')
[Backend] schemes.py → schemes_service.get_summary loop → filtered
   ↓
[Frontend composable] deficits ref set
   ↓
[Banner] reads deficits, viewMode, currentProjectId → renders / hides
[SlotCard / inline slot] reads hasDeficitFor(project_id) → renders badge

[user clicks CTA "Одобрить схемы →"]
   ↓
client: /client/schemes
manager/admin: /admin/scheme-preferences?project=<id>
```

## Error handling

- 401/403 на /api/schemes/deficits → composable swallows, banner hidden (no UI noise)
- 5xx → composable пишет в console.error, banner hidden
- Empty array → banner hidden, badges не показываются

## Observability

- Backend: `[deficits] role=client project_ids=[79] returned=1` console-log per request
- Frontend: ничего специального; Vue Devtools покажет state composable
- Не нужны метрики — фича read-only поверх существующих данных

## Testing

### Backend (pytest, `backend/tests/`)

| Тест | Setup | Expect |
|---|---|---|
| **B1** | client с project_id=79 (5/9 deficit) | 1 элемент `{project_id:79, approved:5, min_required:9}` |
| **B2** | client с project_id=99 (full coverage 9/9) | empty array |
| **B3** | client с project_id=NULL | empty array |
| **B4** | manager с project_ids=[79,80,81], deficits на 79 и 81 | 2 элемента |
| **B5** | admin (все проекты), 6 deficits | 6 элементов |
| **B6** | проект без packs (min_required=0) | НЕ включается (фильтр `min_required > 0`) |
| **B7** | unauthenticated → 401 |

Использовать существующий `engine.dispose` autouse fixture (см. memory `feedback_validator_test_engine_dispose.md`).

### Frontend (vitest или node:test — выяснить convention в repo)

| Тест | Setup | Expect |
|---|---|---|
| **F1** | composable без deficits → banner v-if=false |
| **F2** | composable с 1 deficit + viewMode='single' → single-line banner с правильными числами |
| **F3** | composable с 3 deficits + viewMode='all' → агрегированный banner "3 проекта" |
| **F4** | hasDeficitFor(79)=true, hasDeficitFor(80)=false → badge только на slot.project_id=79 |
| **F5** | CTA-линк для role='client' → href='/client/schemes' |
| **F6** | CTA-линк для role='admin' single mode → href='/admin/scheme-preferences?project=79' |

### Manual smoke

1. Открыть `/dashboard` под клиентом проекта 79 → увидеть red banner "5/9 схем" + per-slot badges на всех слотах project=79.
2. Открыть `/dashboard` под admin'ом, single mode выбран project 79 → то же что #1.
3. Admin all-mode → агрегированный banner "X проектов" + per-slot badges по всем deficit-проектам.
4. Клик «Одобрить схемы →» переходит на правильную страницу.
5. После одобрения недостающих схем на /client/schemes и возврата на /dashboard → банера и бейджей нет (после refresh страницы — TTL кеш).

## Rollout

1. **Dev (validator-contenthunter):** ветка `feature/schemes-deficit-banner-2026-05-07`. Worktree (см. memory `feedback_parallel_claude_sessions.md`).
2. **Backend** сначала — запустить pytest, smoke `/api/schemes/deficits` через curl с реальным JWT.
3. **Frontend** — `npm run build` (auto-postbuild копирует в `/var/www/validator/` — см. memory `feedback_validator_postbuild_autodeploy.md`). Hot-reload не нужен для prod-like smoke.
4. **Smoke на dev:** открыть `client.contenthunter.ru` локально через port-forward или dev-server, под одним из 6 проблемных проектов (79/81/83/85), увидеть banner.
5. **Cherry-pick в prod main**, рестарт validator PM2-процесса (`pm2 restart validator`).
6. **Monitoring T+15 мин:** запросить от клиента screenshot или попросить тестового клиента проверить. Также `pm2 logs validator | grep deficits` показывает активность.
7. **Rollback:** `git revert <merge_sha>` + `pm2 restart validator`. Никаких миграций, БД-изменений, не нужно откатывать данные.

## Risks

| Риск | Вероятность | Митигация |
|---|---|---|
| `/api/schemes/deficits` для admin'а с 30+ проектами медленный | Низкая | Each get_summary → 2 SELECT'а, итого ~60 SELECT'ов. На indexed таблицах <100ms. Если станет узким — оптимизировать одним JOIN-запросом позже. |
| project_name неправильно резолвится (если pack_name suffix паттерн другой) | Средняя | Pre-flight grep по `validator_projects` или `factory_projects` — найти canonical таблицу с проект-именами. |
| Клиент видит баннер от другого проекта (cross-tenant leak) | Низкая | Backend строго фильтрует по `current_user.project_id` для роли client. Тест B1+B2 покрывает. |
| Stale кеш — клиент одобрил схемы, баннер ещё показывается 10 мин | Низкая | UX-приемлемо. Можно очистить кеш на route-change `/client/schemes → /dashboard` (минимально). |
| Per-slot badge ломает существующий layout слота | Средняя | Проверить визуально оба рендерера до commit. Использовать `position: absolute` или inline-flex с маленьким размером (10px шрифт). |

## Open questions для writing-plans

| Q | Что проверить |
|---|---|
| **Q1** | Frontend test runner: vitest или jest? Если ничего — добавить vitest как dev-dep ИЛИ написать тесты на node:test (как в autowarm-testbench). Pre-flight `cat package.json`. |
| **Q2** | Canonical таблица для project_name: `validator_projects` или `factory_projects`? `factory_pack_accounts.pack_name` имеет суффикс типа `_1`, `_2` — strip их, как в существующем `runAutoUnicForDate` (`pack_name?.replace(/_\d+$/, '')`). |
| **Q3** | Есть ли уже composable-pattern в validator (Pinia store + composable) или только Pinia? Pre-flight `ls frontend/src/composables/`. |
| **Q4** | Auth/role pass-through: `current_user.project_ids` уже есть в `Auth` Pydantic model для manager? Pre-flight `grep -nE "project_ids" backend/src/models`. |
| **Q5** | UNIQUE на `validator_scheme_preferences (project_id, scheme_id)` — есть (`uq_project_scheme`), используется в schemes_service. ✓ |

## Decisions captured

- Single endpoint `/api/schemes/deficits` (не extend существующий `/api/schemes/summary/{project_id}` — sep responsibility)
- Composable + reactive ref (не Pinia store, проще для one-off use case)
- Per-slot badge inline в обоих рендерерах (правило `feedback_validator_two_slot_renderers.md`)
- Aggregated banner expandable (clickable disclosure), не fixed list (rascal-проблема)
- TTL 10min — компромисс между свежестью и нагрузкой; ручной refresh через page reload
- CTA URLs: client→/client/schemes, admin/manager→/admin/scheme-preferences?project=<id>
