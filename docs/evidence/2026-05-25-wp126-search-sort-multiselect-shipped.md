# WP #126 — Поиск + единая сортировка + мультивыбор фильтров — SHIPPED+DEPLOYED 2026-05-25

OpenProject: [WP #126](https://openproject.contenthunter.ru/work_packages/126) → «Тестирование» (комментарий id 538).
Спека + 4 плана: `docs/superpowers/specs/2026-05-25-wp126-search-sort-filters-design.md`, `docs/superpowers/plans/2026-05-25-wp126-1a…/1b…/2a…/2b….md`.

## Что просили
Добавить поиск в фильтры по клиенту/проекту/телефону; везде единая сортировка по алфавиту; где осмысленно — мультивыбор (кроме «уникализации» и «мой пакет»).

## Что сделано (по фазам)

**Фаза 1 — delivery (GenGo2/delivery-contenthunter, main `2b57fee`):**
- **1a:** `public/search_select_pure.js` (sort/filter/label/toggle, `node --test`) + DOM-виджет `public/search_select.js` `makeSearchSelect` + замена нативных `<select>` на 5 страницах (Ручная выкладка, Запланировано, Опубликовано, Планировщик, Дашборд) — поиск + единая сортировка (`localeCompare('ru',{sensitivity:'base',numeric:true})`).
- **1b:** мультивыбор через ПОВТОРЯЕМЫЕ query-параметры (`project=A&project=B`, comma-safe) — 4 серверных эндпоинта (`server.js`: queue/dashboard/tasks builders, `publish_planner.js`: `getPlannerCards` `projectIds`→`= ANY`), `paginated-table.js` разворот массива, клиентский `mpqMatch` для Ручной выкладки.

**Фаза 2 — client/validator (GenGo2/validator-contenthunter, main `1c493df`):**
- **2a:** `frontend/src/utils/projectSort.ts` (+vitest) + `frontend/src/components/SearchableSelect.vue` (single) + замена 7 селекторов проекта.
- **2b:** компонент → режим `multiple` (массив v-model, `change` на закрытии) + `projectStore.projectIdsHeader` (`X-Project-Ids`) + мультивыбор на Публикациях/Аккаунтах/Аналитике + бэкенд FastAPI (`_resolve_project_ids` с RBAC клиента, `= ANY(:pids)` в analytics, union `get_project_accounts` для аккаунтов). Аналитика суммирует по выбранным проектам.

## Решения по скоупу (уточнено с заказчиком 2026-05-25)
- Мультивыбор в кабинете — только на 3 страницах (Публикации/Аккаунты/Аналитика).
- «Распаковка», «уникализация», «мой пакет» — одиночный выбор (формы/договор одного проекта).
- «Дашборд» не трогали — у него уже есть режим «Все проекты».

## Качество
- Все планы прогнаны через `codex review` (исправлено 3 реальных замечания: CSV-в-имени-проекта→repeated params; баг теста мультивыбора; int-parse hardening). Финальные ревью opus по каждой фазе — CLEAN/SHIP-READY.
- Тесты: delivery `node --test` 23/23; validator vitest (projectSort 3 + SearchableSelect 2 + существующие). По ходу починены: утечка mousedown-слушателя, регрессия planner→tasks drill-down, парсинг битого `X-Project-Ids`.

## Деплой (2026-05-25)
- **delivery:** прод-checkout `/root/.openclaw/workspace-genri/autowarm` ff-merge → `2b57fee`; PM2 `autowarm` (id 35, root) рестарт; порт 3848 отдаёт `/search_select.js`+`/search_select_pure.js`=200, index.html с новыми тегами.
- **validator:** прод-checkout `/root/.openclaw/workspace-genri/validator` ff-merge → `1c493df`; PM2 `validator` (id 24, root) рестарт (FastAPI :8000, чистый старт, эндпоинты 403-not-500); фронт `npm run build` (vue-tsc+vite ✓) → postbuild → `/var/www/validator`.

## Остаточные риски / verify
- **Бэкенд validator не прогонялся на боевой БД** (нет БД в dev-окружении) — только review + чистый импорт + 403-not-500. Обратная совместимость: выбор одного проекта идёт прежним путём (`= ANY([pid])`). Нужен функциональный DB-смоук мультивыбора (аналитика/публикации/аккаунты).
- Визуальный смоук обоих фронтов (чек-листы в планах).
- Накопленные старые asset-хэши в `/var/www/validator/assets` (postbuild = `cp`, не clean) — pre-existing, безвредно.
