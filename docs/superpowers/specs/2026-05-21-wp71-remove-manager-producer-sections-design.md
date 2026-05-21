# WP #71 — Удалить разделы «Менеджер» и «Продюсер» из валидатора

- **Дата:** 2026-05-21
- **OpenProject:** WP #71 «удалить ненужные блоки из клиента менеджер и продюссер» (автор — Анастасия, assignee — Данил, статус «В разработке»)
- **Репозиторий кода:** `/home/claude-user/validator-contenthunter` (фронтенд `frontend/`, Vite + Vue 3 + TS)
- **Рабочая ветка (доки):** `docs/wp71-remove-unused-blocks-2026-05-21` (agent-workspace)
- **Тип изменения:** только фронтенд-удаление; бэкенд, БД и роли не трогаем

## Контекст и решение

WP создана с пустым описанием. На уточнении Данил зафиксировал scope:

1. **Полностью убрать раздел «Менеджер» и все его подразделы.**
2. **Полностью убрать раздел «Продюсер» и все его подразделы.**
3. Раздел «Клиент» не трогаем.

Согласованные параметры:

- **Глубина = «интерфейс целиком»:** убрать пункты меню + маршруты + удалить страницы (`.vue`) и компоненты, которые после этого нигде не используются. Бэкенд-эндпоинты и таблицы (CRM / алерты / аналитика) **не трогаем** — остаются неиспользуемыми, но безопасными; полностью обратимо через git.
- **Доступ/роли = «убрать у всех, роли оставить»:** разделы исчезают у всех, **включая админа**. Роли `manager` / `producer` в авторизации и БД сохраняются (можно вернуть позже). Бэкенд RBAC не меняется.

## Карта удаляемого

### Меню (роли и текущая видимость)
- **МЕНЕДЖЕР** (видно при `isManager || isAdmin`): 👥 Клиенты, 🚨 Алерты, 📊 Аналитика.
- **ПРОДЮСЕР** (видно при `isProducer || isAdmin`): 🗺️ Клиенты, 📡 Охватный, 📦 Массовая, 📋 Заказы, 🔄 Канбан, 👷 Исполнители, 💰 Финансы.

### Маршруты (`frontend/src/router/index.ts`)
Блок Manager (строки 27–30) и блок Producer (строки 33–40), всего 11 маршрутов:

| Путь | Компонент | meta.roles |
|------|-----------|-----------|
| `/manager` | manager/ManagerDashboard.vue | manager, admin |
| `/manager/client/:id` | manager/ClientView.vue | manager, admin |
| `/manager/alerts` | manager/AlertsPage.vue | manager, admin |
| `/analytics` | manager/AnalyticsPage.vue | manager, admin |
| `/producer` | producer/ProducerDashboard.vue | producer, admin |
| `/producer/reach` | producer/ReachUpload.vue | producer, admin |
| `/producer/bulk` | producer/BulkUpload.vue | producer, admin |
| `/producer/crm` | producer/CrmOrders.vue | producer, admin |
| `/producer/crm/kanban` | producer/CrmKanban.vue | producer, admin |
| `/producer/crm/contractors` | producer/CrmContractors.vue | producer, admin |
| `/producer/crm/finance` | producer/CrmFinance.vue | producer, admin |

### Страницы (`.vue`) на удаление
- `frontend/src/pages/manager/`: `ManagerDashboard.vue`, `ClientView.vue`, `AlertsPage.vue`, `AnalyticsPage.vue` → после удаления папка пуста, удаляем.
- `frontend/src/pages/producer/`: `ProducerDashboard.vue`, `ReachUpload.vue`, `BulkUpload.vue`, `CrmOrders.vue`, `CrmKanban.vue`, `CrmContractors.vue`, `CrmFinance.vue` → папку удаляем.

### Компоненты на удаление (использовались только Менеджером/Продюсером)
- `frontend/src/components/dashboard/ClientGrid.vue` (только ManagerDashboard).
- `frontend/src/components/dashboard/FuelGauge.vue` (только ClientView).
- `frontend/src/components/calendar/WeeklyGrid.vue` (только ClientView).

**Обязательная проверка на этапе реализации:** перед удалением каждого из трёх компонентов ещё раз `grep` по `frontend/src` на импорты — подтвердить, что других потребителей нет (особенно `WeeklyGrid` — убедиться, что недельная сетка на Планировщике клиента отрисована инлайн в `ClientDashboard.vue`, а не через этот компонент).

## Изменения

Все пути — относительно `/home/claude-user/validator-contenthunter`.

### 1. `frontend/src/components/layout/AppSidebar.vue`
- Удалить секцию меню МЕНЕДЖЕР (десктоп, блок `v-if="auth.isManager || auth.isAdmin"`, ~строки 19–24).
- Удалить секцию меню ПРОДЮСЕР (десктоп, блок `v-if="auth.isProducer || auth.isAdmin"`, ~строки 26–38).
- Удалить соответствующие пункты из мобильной нижней навигации (~строки 61–69).
- Блоки удаляются целиком (вместе с `|| auth.isAdmin`) → исчезают у всех, включая админа.
- **Не трогаем** строку 13 `v-if="!auth.isManager"` на пункте «Аккаунты» — это существующее поведение (скрывает Аккаунты у менеджера) и вне scope.

### 2. `frontend/src/router/index.ts`
- Удалить блок Manager (строки 27–30) и блок Producer (строки 33–40) вместе с комментариями `// Manager`, `// Producer`, `// Producer CRM`.
- Добавить catch-all в конец массива `routes`: `{ path: '/:pathMatch(.*)*', redirect: '/dashboard' }`. Причина: catch-all сейчас нет; после удаления прямой переход на `/manager` или `/producer` (закладка/старая ссылка) отрисует пустой `<router-view>`. Редирект уводит на Планировщик.
- **Не трогаем** `meta.roles`, где упомянуты `manager`/`producer` на выживающих маршрутах (`/clients` строка 24, `/upload` строка 13, `/admin/scheme-preferences` строка 47) — роли сохраняются, упоминания безвредны.
- **Не трогаем** `beforeEach` (строки 51–68): он уже редиректит неавторизованную роль на `/dashboard`.

### 3. `frontend/src/pages/LoginPage.vue` и `frontend/src/pages/TgCallbackPage.vue`
- В карте «роль → стартовый маршрут» поменять `manager` и `producer` на `/dashboard` (сейчас `/manager` и `/producer` — после удаления это 404).
- `LoginPage.vue`: строки ~130 и ~163. `TgCallbackPage.vue`: строка ~30.
- `client → /dashboard` и `admin → /admin` оставить как есть.

### 4. Удаление файлов
- Удалить 11 страниц и 3 компонента из списков выше. Удалить опустевшие директории `pages/manager/` и `pages/producer/`.

### 5. (Опционально, по согласованию с Данилом) `frontend/src/components/layout/AppHeader.vue`
- Подчистить мёртвые title-мэппинги для `/manager*` и `/producer*` (~строки 55–64). Безвредны, если оставить (возвращают дефолт «Content Hunter»). Включаем в этот WP ради чистоты.

## Что осознанно НЕ трогаем

- **Роли** `manager`/`producer`: computed `isManager`/`isProducer` в `frontend/src/stores/auth.ts` (строки 25–26) остаются.
- **Бэкенд:** эндпоинты и таблицы CRM / алертов / аналитики не удаляем (вне scope «интерфейс целиком»).
- **Общие компоненты:** `PlatformIcon`, `upload/DropZone`, `upload/UploadProgress` — используются клиентом, остаются.
- **Мёртвый код в клиентских страницах:** `needsProjectSelector = auth.isAdmin || auth.isManager` в `AccountsPage`, `ContractPage`, `BrandPage`, `PublicationsPage`, `SchemesPage`, `client/AnalyticsPage`; `isManager || isAdmin` в `ContentDetail.vue`; дефолт `['admin','manager']` в `HelpDrawer.vue`. Не ломают ничего (страницы доступны менеджеру/продюсеру по `meta.roles`, но без UI-точек входа). Чистку не делаем — отдельный мелкий рефактор при желании.

## Поведение после изменений

- **Клиент** — без изменений.
- **Админ** — нет меню Менеджер/Продюсер и их страниц; сохраняется раздел Админ + `/clients` (ProjectsPage); календарь любого проекта смотрит через переключатель проектов («📁 Проект» / «🗂 Все проекты») на Планировщике `/dashboard`. Функция удалённого `ClientView` (read-only календарь клиента) дублируется Планировщиком, дангляющих ссылок на `/manager/client/:id` из выживающих страниц нет.
- **Пользователь с ролью `manager`/`producer`** (если такие есть в системе) — после входа попадает на `/dashboard` (Планировщик), видит клиентское меню (у менеджера «Аккаунты» скрыты существующим правилом), работает через переключатель проектов. 404 нет.

## Тестирование и приёмка

- **Сборка:** `npm run build` в `frontend/` — обязана пройти без ошибок (ловит любой осиротевший импорт удалённого файла). Type-check включён.
- **Юнит-тесты:** `slotStatus.test.ts`, `__tests__/UploadModal.spec.ts`, `calendar/__tests__/SlotCard.spec.ts`, `admin/__tests__/ProjectPublishModeCell.spec.ts` — ни один не ссылается на менеджер/продюсер; должны остаться зелёными. Прогнать после изменений.
- **Ручной смоук:**
  - Клиент: меню без Менеджер/Продюсер, Планировщик работает.
  - Админ: нет разделов Менеджер/Продюсер, есть Админ + `/clients`; переключатель проектов на Планировщике открывает календарь любого проекта.
  - Прямой переход на `/manager` и `/producer` → редирект на `/dashboard` (catch-all).

## Деплой (важная специфика валидатора)

- ⚠️ У фронтенда валидатора `postbuild`-хук **автоматически копирует сборку в `/var/www/validator`** — то есть `npm run build` = прод-деплой. Билд выполняется осознанно, как шаг выкладки, не «между делом». Перед билдом — pre-flight `package.json` (подтвердить, что postbuild на месте).
- Бэкенд не трогаем, поэтому конфликт `validator-backend.service` (systemd) ↔ PM2 `validator` к этой задаче не относится.
- Код-изменения делаются в `validator-contenthunter` в отдельной feature-ветке; merge в `main` репозитория валидатора отдельным PR.

## Риски

- **Низкие.** Чистое фронтенд-удаление, полностью обратимо через git.
- Основной риск — пропустить общий импорт удаляемого файла → падение сборки (ловится `npm run build` до деплоя).
- Catch-all устраняет пустые страницы по старым ссылкам.
- Роли сохранены → никого не залочит из системы.

## Открытые вопросы

- Подчищать ли `AppHeader.vue` (п.5) и мёртвые `isManager`-проверки в клиентских страницах, или строго минимум? (По умолчанию: `AppHeader` чистим, клиентские мёртвые проверки оставляем.)
