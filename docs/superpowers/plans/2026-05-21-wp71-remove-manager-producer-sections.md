# WP #71 — Remove Manager & Producer Sections — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Полностью удалить из фронтенда валидатора разделы «Менеджер» и «Продюсер» (меню + маршруты + страницы + их эксклюзивные компоненты), сохранив клиента, админа, роли и весь бэкенд.

**Architecture:** Чистое фронтенд-удаление в репозитории `/home/claude-user/validator-contenthunter` (Vite + Vue 3 + TypeScript, Pinia, vue-router). Убираем UI-точки входа (сайдбар, маршруты, post-login редиректы, title-мэппинги), затем удаляем осиротевшие `.vue`-файлы. Роли `manager`/`producer` в `stores/auth.ts` и бэкенд не трогаем. Добавляем catch-all-маршрут, чтобы старые ссылки на `/manager`/`/producer` вели на `/dashboard`.

**Tech Stack:** Vue 3 SFC, vue-router 4, Pinia, TypeScript, vitest + @vue/test-utils, vue-tsc.

**Spec:** `docs/superpowers/specs/2026-05-21-wp71-remove-manager-producer-sections-design.md`

---

## Подход к верификации (важно для исполнителя)

Это **удалительная** задача — паттерн «сначала падающий тест на новую функцию» к ней не применим напрямую. Верификация:

1. **`npx vue-tsc --noEmit`** — статическая проверка типов. Ловит любой висячий импорт удалённого файла. **НЕ деплоит.** Успех = нет вывода, exit 0.
2. **`npm run test`** (`vitest run`) — юнит-тесты. **НЕ деплоит.**
3. **Один router-guard тест** (Task 2/3) — реальный TDD-якорь: проверяет, что маршрутов `/manager`/`/producer` больше нет и есть catch-all. Сейчас падает, после удаления маршрутов — зеленеет.
4. **Ручной смоук в браузере** (Task 8) — клиент/админ/прямой URL.

### ⚠️ Критично: `npm run build` = ПРОД-ДЕПЛОЙ

`package.json` содержит `"postbuild": "cp -r dist/* /var/www/validator/"`. То есть **`npm run build` автоматически копирует сборку в боевой `/var/www/validator/`**. Поэтому:
- Во время разработки **НИКОГДА не запускать `npm run build`** для «просто проверки» — используйте `npx vue-tsc --noEmit`.
- `npm run build` выполняется **только** в Task 8 как осознанный шаг выкладки **после явного одобрения Данила**.

### Git
- Код-изменения — в репозитории `/home/claude-user/validator-contenthunter` в **отдельной feature-ветке** от `main`.
- Атомарные коммиты: каждая задача оставляет ветку в зелёном (компилируемом) состоянии.
- **Никаких `--force`/`--force-with-lease` push.**

---

## File Structure

Все пути — относительно `/home/claude-user/validator-contenthunter/frontend/`.

**Modify:**
- `src/router/index.ts` — удалить 11 маршрутов manager/producer, добавить catch-all.
- `src/components/layout/AppSidebar.vue` — удалить секции меню Менеджер/Продюсер (десктоп + мобайл).
- `src/pages/LoginPage.vue` — две карты редиректа: `manager`/`producer` → `/dashboard`.
- `src/pages/TgCallbackPage.vue` — одна карта редиректа: `manager`/`producer` → `/dashboard`.
- `src/components/layout/AppHeader.vue` — убрать title-мэппинги для `/manager*` и `/producer*`.

**Create:**
- `src/router/__tests__/routes.spec.ts` — guard-тест отсутствия manager/producer маршрутов + наличия catch-all.

**Delete (Task 7):**
- Страницы: `src/pages/manager/{ManagerDashboard,ClientView,AlertsPage,AnalyticsPage}.vue` (вся папка), `src/pages/producer/{ProducerDashboard,ReachUpload,BulkUpload,CrmOrders,CrmKanban,CrmContractors,CrmFinance}.vue` (вся папка).
- Компоненты: `src/components/dashboard/ClientGrid.vue`, `src/components/dashboard/FuelGauge.vue`, `src/components/calendar/WeeklyGrid.vue`.

**Untouched (явно):** `src/stores/auth.ts` (роли `isManager`/`isProducer` остаются), все общие компоненты (`PlatformIcon`, `upload/DropZone`, `upload/UploadProgress`), весь бэкенд.

---

## Task 1: Feature-ветка и зелёный baseline

**Files:** нет правок кода — только git + проверка.

- [ ] **Step 1: Создать feature-ветку от свежего main**

```bash
cd /home/claude-user/validator-contenthunter
git fetch origin --quiet 2>/dev/null || true
git status -s            # ожидаем чисто; если есть чужие незакоммиченные правки — СТОП, сообщить пользователю
git checkout main
git checkout -b feat/wp71-remove-manager-producer-2026-05-21
git branch --show-current
```

Expected: `feat/wp71-remove-manager-producer-2026-05-21`. Если `git status -s` показывает чужие незакоммиченные изменения — остановиться и спросить пользователя (не перетирать чужую работу).

- [ ] **Step 2: Зафиксировать baseline type-check**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit ; echo "exit=$?"
```

Expected: `exit=0` (нет вывода). Если есть pre-existing ошибки **в файлах, которых мы не касаемся** — записать их как известный фон и продолжить (не чинить чужое). Если ошибки в наших файлах — разобраться до начала.

- [ ] **Step 3: Зафиксировать baseline тестов**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npm run test 2>&1 | tail -25
```

Expected: все существующие тесты (`slotStatus.test.ts`, `UploadModal.spec.ts`, `SlotCard.spec.ts`, `ProjectPublishModeCell.spec.ts`) зелёные. Записать число прошедших как baseline. Pre-existing падения вне нашего scope — задокументировать, не чинить.

---

## Task 2: Router-guard тест (падающий)

**Files:**
- Create: `src/router/__tests__/routes.spec.ts`

- [ ] **Step 1: Написать guard-тест**

Create `src/router/__tests__/routes.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import router from '@/router'

// WP #71 — разделы Менеджер и Продюсер удалены из фронтенда.
// Этот тест охраняет от их случайного возврата и проверяет catch-all.
describe('router: manager/producer sections removed (WP #71)', () => {
  const paths = router.getRoutes().map((r) => r.path)

  it('не содержит маршрутов менеджера', () => {
    expect(paths.some((p) => p === '/manager' || p.startsWith('/manager/'))).toBe(false)
    expect(paths).not.toContain('/analytics') // бывшая manager AnalyticsPage
  })

  it('не содержит маршрутов продюсера', () => {
    expect(paths.some((p) => p === '/producer' || p.startsWith('/producer/'))).toBe(false)
  })

  it('имеет catch-all маршрут (для редиректа старых ссылок)', () => {
    expect(paths.some((p) => p.includes('pathMatch'))).toBe(true)
  })

  it('сохраняет клиентский Планировщик', () => {
    expect(paths).toContain('/dashboard')
  })
})
```

- [ ] **Step 2: Запустить — убедиться, что падает**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vitest run src/router/__tests__/routes.spec.ts 2>&1 | tail -25
```

Expected: FAIL — тесты «не содержит маршрутов менеджера/продюсера» и «имеет catch-all» падают (сейчас маршруты `/manager`, `/producer` ещё есть, catch-all нет). Тест «сохраняет Планировщик» проходит. **Коммит пока НЕ делаем** — ветка должна оставаться зелёной только на границах задач; этот тест зафиксируем вместе с правкой роутера в Task 3.

---

## Task 3: Удалить маршруты + добавить catch-all (`router/index.ts`)

**Files:**
- Modify: `src/router/index.ts` (удалить блоки Manager стр. 26–30 и Producer стр. 32–40; добавить catch-all после стр. 47)

- [ ] **Step 1: Удалить блоки маршрутов Manager и Producer**

Заменить (Edit) этот фрагмент:

```ts
    // Manager
    { path: '/manager', component: () => import('@/pages/manager/ManagerDashboard.vue'), meta: { roles: ['manager', 'admin'] } },
    { path: '/manager/client/:id', component: () => import('@/pages/manager/ClientView.vue'), meta: { roles: ['manager', 'admin'] } },
    { path: '/manager/alerts', component: () => import('@/pages/manager/AlertsPage.vue'), meta: { roles: ['manager', 'admin'] } },
    { path: '/analytics', component: () => import('@/pages/manager/AnalyticsPage.vue'), meta: { roles: ['manager', 'admin'] } },

    // Producer
    { path: '/producer', component: () => import('@/pages/producer/ProducerDashboard.vue'), meta: { roles: ['producer', 'admin'] } },
    { path: '/producer/reach', component: () => import('@/pages/producer/ReachUpload.vue'), meta: { roles: ['producer', 'admin'] } },
    { path: '/producer/bulk', component: () => import('@/pages/producer/BulkUpload.vue'), meta: { roles: ['producer', 'admin'] } },
    // Producer CRM
    { path: '/producer/crm', component: () => import('@/pages/producer/CrmOrders.vue'), meta: { roles: ['producer', 'admin'] } },
    { path: '/producer/crm/kanban', component: () => import('@/pages/producer/CrmKanban.vue'), meta: { roles: ['producer', 'admin'] } },
    { path: '/producer/crm/contractors', component: () => import('@/pages/producer/CrmContractors.vue'), meta: { roles: ['producer', 'admin'] } },
    { path: '/producer/crm/finance', component: () => import('@/pages/producer/CrmFinance.vue'), meta: { roles: ['producer', 'admin'] } },

    // Admin
```

на:

```ts
    // Admin
```

- [ ] **Step 2: Добавить catch-all в конец массива routes**

Заменить (Edit) фрагмент (последний admin-маршрут + закрытие массива):

```ts
    { path: '/admin/scheme-preferences', component: () => import('@/pages/admin/SchemePreferencesPage.vue'), meta: { roles: ['manager', 'admin'] } },
  ],
})
```

на:

```ts
    { path: '/admin/scheme-preferences', component: () => import('@/pages/admin/SchemePreferencesPage.vue'), meta: { roles: ['manager', 'admin'] } },

    // WP #71: старые/закладочные ссылки на удалённые разделы → Планировщик
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})
```

- [ ] **Step 3: Запустить guard-тест — должен пройти**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vitest run src/router/__tests__/routes.spec.ts 2>&1 | tail -25
```

Expected: PASS (все 4 теста).

- [ ] **Step 4: Type-check (страницы ещё на месте, импорты резолвятся)**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit ; echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/router/index.ts frontend/src/router/__tests__/routes.spec.ts
git commit -m "feat(wp71): remove manager/producer routes, add catch-all to /dashboard"
```

---

## Task 4: Удалить секции меню (`AppSidebar.vue`)

**Files:**
- Modify: `src/components/layout/AppSidebar.vue` (десктоп-блоки стр. 19–38; мобильные ссылки стр. 61–69)

- [ ] **Step 1: Удалить десктоп-секции Менеджер и Продюсер**

Заменить (Edit) фрагмент:

```html
      <div v-if="auth.isManager || auth.isAdmin" class="pt-3">
        <p class="text-xs font-semibold text-gray-400 uppercase tracking-wide px-3 mb-1">Менеджер</p>
        <NavItem to="/manager" icon="👥" label="Клиенты" />
        <NavItem to="/manager/alerts" icon="🚨" label="Алерты" />
        <NavItem to="/analytics" icon="📊" label="Аналитика" />
      </div>

      <div v-if="auth.isProducer || auth.isAdmin" class="pt-3">
        <p class="text-xs font-semibold text-gray-400 uppercase tracking-wide px-3 mb-1">Продюсер</p>
        <NavItem to="/producer" icon="🗺️" label="Клиенты" :exact="true" />
        <NavItem to="/producer/reach" icon="📡" label="Охватный" />
        <NavItem to="/producer/bulk" icon="📦" label="Массовая" />
        <div class="mt-2 mb-1 px-3">
          <div class="h-px bg-gray-100"></div>
        </div>
        <NavItem to="/producer/crm" icon="📋" label="Заказы" />
        <NavItem to="/producer/crm/kanban" icon="🔄" label="Канбан" />
        <NavItem to="/producer/crm/contractors" icon="👷" label="Исполнители" />
        <NavItem to="/producer/crm/finance" icon="💰" label="Финансы" />
      </div>

      <div v-if="auth.isAdmin" class="pt-3">
```

на:

```html
      <div v-if="auth.isAdmin" class="pt-3">
```

- [ ] **Step 2: Удалить мобильные ссылки Менеджер и Продюсер**

Заменить (Edit) фрагмент:

```html
    <router-link v-if="auth.isManager || auth.isAdmin" to="/manager" class="mob-tab" :class="{ active: $route.path.startsWith('/manager') }">
      <span class="mob-icon">👥</span>
      <span class="mob-label">Клиенты</span>
    </router-link>

    <router-link v-if="auth.isProducer || auth.isAdmin" to="/producer" class="mob-tab" :class="{ active: $route.path.startsWith('/producer') }">
      <span class="mob-icon">🗺️</span>
      <span class="mob-label">Продюсер</span>
    </router-link>

    <router-link v-if="auth.isAdmin" to="/admin/users" class="mob-tab" :class="{ active: $route.path.startsWith('/admin') }">
```

на:

```html
    <router-link v-if="auth.isAdmin" to="/admin/users" class="mob-tab" :class="{ active: $route.path.startsWith('/admin') }">
```

**Не трогать** строку 13 `<NavItem v-if="!auth.isManager" ...>` (пункт «Аккаунты») и `roleLabel` в `<script>` — вне scope, существующее поведение.

- [ ] **Step 3: Type-check**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit ; echo "exit=$?"
```

Expected: `exit=0`. (`auth` всё ещё используется — `isManager` на стр. 13, `isAdmin` в админ-секции; висячих ссылок нет.)

- [ ] **Step 4: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/components/layout/AppSidebar.vue
git commit -m "feat(wp71): remove manager/producer nav sections (desktop + mobile)"
```

---

## Task 5: Починить post-login редиректы (`LoginPage.vue`, `TgCallbackPage.vue`)

**Files:**
- Modify: `src/pages/LoginPage.vue` (две карты редиректа)
- Modify: `src/pages/TgCallbackPage.vue` (одна карта редиректа)

- [ ] **Step 1: LoginPage.vue — карта в Telegram-колбэке**

Заменить (Edit) строку:

```ts
        const routes: Record<string, string> = { client: '/dashboard', admin: '/admin', manager: '/manager', producer: '/producer' }
```

на:

```ts
        const routes: Record<string, string> = { client: '/dashboard', admin: '/admin', manager: '/dashboard', producer: '/dashboard' }
```

- [ ] **Step 2: LoginPage.vue — карта в handleLogin**

Заменить (Edit) фрагмент:

```ts
    const routes: Record<string, string> = {
      client: '/dashboard', admin: '/admin', manager: '/manager', producer: '/producer'
    }
```

на:

```ts
    const routes: Record<string, string> = {
      client: '/dashboard', admin: '/admin', manager: '/dashboard', producer: '/dashboard'
    }
```

- [ ] **Step 3: TgCallbackPage.vue — карта редиректа**

Заменить (Edit) строку:

```ts
      const routes: Record<string, string> = { client: '/dashboard', admin: '/admin', manager: '/manager', producer: '/producer' }
```

на:

```ts
      const routes: Record<string, string> = { client: '/dashboard', admin: '/admin', manager: '/dashboard', producer: '/dashboard' }
```

- [ ] **Step 4: Type-check**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit ; echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/pages/LoginPage.vue frontend/src/pages/TgCallbackPage.vue
git commit -m "feat(wp71): redirect manager/producer logins to /dashboard"
```

---

## Task 6: Подчистить title-мэппинги (`AppHeader.vue`)

**Files:**
- Modify: `src/components/layout/AppHeader.vue` (стр. 55–64)

- [ ] **Step 1: Удалить мэппинги manager/producer из `titles`**

Заменить (Edit) фрагмент:

```ts
  '/client/contract': 'Мой пакет',
  '/manager': 'Клиенты',
  '/manager/alerts': 'Алерты',
  '/analytics': 'Аналитика',
  '/producer': 'Карта клиентов',
  '/producer/reach': 'Охватный контент',
  '/producer/bulk': 'Массовая загрузка',
  '/producer/crm': 'Заказы',
  '/producer/crm/kanban': 'Канбан',
  '/producer/crm/contractors': 'Исполнители',
  '/producer/crm/finance': 'Финансы',
  '/admin/users': 'Пользователи',
```

на:

```ts
  '/client/contract': 'Мой пакет',
  '/admin/users': 'Пользователи',
```

- [ ] **Step 2: Type-check**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit ; echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 3: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/components/layout/AppHeader.vue
git commit -m "chore(wp71): drop dead manager/producer page-title mappings"
```

---

## Task 7: Удалить осиротевшие страницы и компоненты

**Files:**
- Delete: `src/pages/manager/` (4 файла), `src/pages/producer/` (7 файлов), `src/components/dashboard/ClientGrid.vue`, `src/components/dashboard/FuelGauge.vue`, `src/components/calendar/WeeklyGrid.vue`

- [ ] **Step 1: Подтвердить, что компоненты больше нигде не импортируются**

```bash
cd /home/claude-user/validator-contenthunter/frontend
grep -rnE "ClientGrid|FuelGauge|WeeklyGrid" src/ | grep -vE "src/pages/(manager|producer)/"
echo "exit=$?"
```

Expected: пустой вывод (`exit=1` у grep = совпадений нет вне удаляемых страниц). Если что-то нашлось вне manager/producer — СТОП, разобраться.

- [ ] **Step 2: Удалить файлы и пустые папки**

```bash
cd /home/claude-user/validator-contenthunter/frontend
git rm src/pages/manager/ManagerDashboard.vue src/pages/manager/ClientView.vue \
       src/pages/manager/AlertsPage.vue src/pages/manager/AnalyticsPage.vue \
       src/pages/producer/ProducerDashboard.vue src/pages/producer/ReachUpload.vue \
       src/pages/producer/BulkUpload.vue src/pages/producer/CrmOrders.vue \
       src/pages/producer/CrmKanban.vue src/pages/producer/CrmContractors.vue \
       src/pages/producer/CrmFinance.vue \
       src/components/dashboard/ClientGrid.vue src/components/dashboard/FuelGauge.vue \
       src/components/calendar/WeeklyGrid.vue
# Удалить пустые директории (git rm не удаляет каталоги)
rmdir src/pages/manager src/pages/producer 2>/dev/null || true
ls -la src/pages/ | grep -E "manager|producer" || echo "manager/producer dirs gone"
```

Expected: `manager/producer dirs gone`. (Папка `src/components/dashboard/` может остаться, если в ней есть другие компоненты — это нормально, не трогаем.)

- [ ] **Step 3: Type-check (висячих импортов быть не должно)**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npx vue-tsc --noEmit ; echo "exit=$?"
```

Expected: `exit=0`. Если `Cannot find module '@/pages/manager/...'` — значит где-то остался импорт; найти и убрать (вернуться к Task 3/4/6).

- [ ] **Step 4: Полный прогон тестов**

```bash
cd /home/claude-user/validator-contenthunter/frontend
npm run test 2>&1 | tail -25
```

Expected: все тесты зелёные, включая `src/router/__tests__/routes.spec.ts`. Число прошедших ≥ baseline (Task 1) + наш router-тест.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add -A frontend/src
git commit -m "feat(wp71): delete orphaned manager/producer pages and exclusive components"
```

---

## Task 8: Финальная проверка, деплой (с одобрения) и обновление статуса

**Files:** нет правок кода.

- [ ] **Step 1: Полный self-review диффа ветки**

```bash
cd /home/claude-user/validator-contenthunter
git log --oneline main..HEAD
git diff --stat main..HEAD
```

Проверить, что затронуты только ожидаемые файлы (router, AppSidebar, AppHeader, LoginPage, TgCallbackPage, удалённые страницы/компоненты, новый router-тест). Никаких правок в `stores/auth.ts`, общих компонентах, бэкенде.

- [ ] **Step 2: Прогнать codex review на диффе ветки**

```bash
cd /home/claude-user/validator-contenthunter
git diff main..HEAD | ~/.local/bin/codex review - 2>&1 | tail -40
```

Применить P1-фидбэк (раундами до 0 P1), коммитя правки. Bubblewrap-warning игнорировать.

- [ ] **Step 3: 🚦 ГЕЙТ ДЕПЛОЯ — получить явное «ок» от Данила**

Сообщить: ветка готова, type-check + тесты зелёные, codex чист. Напомнить, что `npm run build` сразу выкладывает в прод (`/var/www/validator`). **Дождаться явного подтверждения перед Step 4.**

- [ ] **Step 4: Pre-flight + сборка-деплой**

```bash
cd /home/claude-user/validator-contenthunter/frontend
grep -A1 '"postbuild"' package.json     # подтвердить, что postbuild на месте (cp в /var/www/validator/)
npm run build 2>&1 | tail -30
```

Expected: `vue-tsc` без ошибок, `vite build` успешно, postbuild скопировал `dist/*` в `/var/www/validator/`.

- [ ] **Step 5: Живой смоук в браузере**

Проверить на боевом домене валидатора:
- **Клиент:** в меню нет «Менеджер»/«Продюсер»; Планировщик открывается и работает.
- **Админ:** нет разделов Менеджер/Продюсер ни в десктоп-сайдбаре, ни в мобильной навигации; есть раздел Админ + «Клиенты» (`/clients`); переключатель проектов («📁 Проект» / «🗂 Все проекты») на Планировщике открывает календарь любого проекта.
- **Прямой URL:** переход на `/manager` и `/producer/crm` → редирект на `/dashboard` (не пустая страница).
- (Если есть пользователь с ролью manager/producer) — после входа попадает на Планировщик, без 404.

- [ ] **Step 6: Слить ветку в main репозитория валидатора**

```bash
cd /home/claude-user/validator-contenthunter
git remote -v     # есть ли удалённый репозиторий?
git checkout main
git merge --no-ff feat/wp71-remove-manager-producer-2026-05-21 -m "Merge WP #71: remove manager/producer sections"
# Если есть GitHub-remote — обычный (НЕ force) push соответствующей ветки/PR.
# git push origin main   # только если remote настроен и это принятый флоу репозитория
```

- [ ] **Step 7: Обновить OpenProject WP #71**

Перевести WP #71 в статус «В тестировании» (id 9) и оставить комментарий в домашнем стиле (Что было не так → Что сделано → Что осталось; простым языком, без жаргона/PR/хешей/путей, без подписи). Механика API — `docs/superpowers/specs/...` / память `reference-openproject-access`. Пример смысла комментария:

> **Что сделано:** убрали из интерфейса разделы «Менеджер» и «Продюсер» со всеми подразделами — у всех, включая администратора. Клиентская часть не изменилась.
> **Что осталось:** проверить вживую в браузере, что всё открывается как надо.

Финальный перевод в «Готово» (id 12) — после приёмки Данилом в браузере.

---

## Self-Review плана (выполнено автором)

- **Покрытие спеки:** меню (Task 4) ✓, маршруты + catch-all (Task 3) ✓, post-login редиректы (Task 5) ✓, удаление страниц (Task 7) ✓, удаление эксклюзивных компонентов (Task 7) ✓, AppHeader-чистка (Task 6) ✓, «не трогаем роли/бэкенд/общие компоненты» — явно зафиксировано в File Structure и шагах ✓, проверка/смоук (Task 1, 7, 8) ✓, деплой-специфика postbuild (заголовок + Task 8) ✓.
- **Плейсхолдеры:** нет — каждый Edit показывает реальный before/after, каждая проверка — точную команду и ожидаемый результат.
- **Согласованность:** имена файлов и пути совпадают со спекой и фактическим деревом; router-тест ссылается на реальные пути (`/manager`, `/producer`, `/analytics`, `/dashboard`, `pathMatch`).
- **Порядок:** ссылки удаляются (Tasks 3–6) до удаления файлов (Task 7) → каждый коммит компилируется; деплой изолирован в гейтированный Task 8.
