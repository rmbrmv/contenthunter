# Session 2026-05-08 — Schemes-deficit banner CTA → /client/schemes (+ query-param deeplink)

**Repo:** `validator-contenthunter` (GenGo2/validator-contenthunter, branch `main`)
**Deployed:** `npm run build` → postbuild `cp -r dist/* /var/www/validator/` (auto on each build)

## TL;DR

Баннер «не хватает одобренных схем» в `/client/dashboard` теперь ведёт на мастер `/client/schemes` (со swipe-превью), а не на admin-таблицу `/admin/scheme-preferences`. Для admin/manager в aggregated-режиме CTA передаёт `?project=N`, и страница пред-выбирает проект через `projectStore`.

## Изменения

| Файл | Что |
|---|---|
| `frontend/src/components/SchemesDeficitBanner.vue:104-110` | `ctaSingle` → `\`/client/schemes?project=${projectId}\``; `ctaAllTop` → `/client/schemes` (без проекта, общий вход). Удалена ветка для роли client (теперь все роли идут на тот же URL) |
| `frontend/src/pages/client/SchemesPage.vue` | `import { useRoute }`; `applyProjectFromQuery()` валидирует `route.query.project` (positive int + проект существует в `projectStore.projects`) и зовёт `projectStore.selectProject(N)`. Триггерится в `onMounted` после `loadProjects()` и в `watch(() => route.query.project)`. Клиентская роль игнорирует query — у неё нет селектора проекта |

## Commits (main)

```
40230a5 merge fix/schemes-page-read-project-query-20260508 — aggregated banner row → preselect project on /client/schemes
1bff48f fix(frontend): SchemesPage reads ?project=N and switches projectStore
0042a75 merge fix/schemes-deficit-banner-cta-to-client-schemes-20260508 — schemes-deficit banner CTA → /client/schemes for all roles
a092210 fix(frontend): point schemes-deficit banner CTA to /client/schemes for all roles
```

## Validation

- `vue-tsc && vite build` — pass без warning'ов на изменённых файлах
- Деплой проверен grep'ом `/var/www/validator/`:
  - `ClientDashboard-*.js` содержит `client/schemes?project=${k}` (banner output)
  - `index-Yj7ZAe5R.js` — 2 обращения к `query.project` (watch source + body `applyProjectFromQuery`)
- Маршрут `/client/schemes` уже разрешён `roles: ['client', 'manager', 'producer', 'admin']` (`router/index.ts:21`) — admin/manager не упрутся в `meta.roles`

## Что НЕ задето

- `/admin/scheme-preferences` остаётся как страница; admin-сайдбар (`AppSidebar.vue:46`) и хедер-крошка (`AppHeader.vue:68`) на неё ведут — баннер был единственным «не-навигационным» CTA, его и retargeted
- Backend / API схем — без изменений
- Клиентская роль (нет селектора проекта) — query параметр игнорируется, т.к. `auth.user.project_id` уже фиксирован

## Why

Пользователь: «на `/admin/scheme-preferences` неудобно апруить — там нет превью. Перенаправь на `/client/schemes` (мастер с превью) для всех ролей». Aggregated-режим должен пред-выбирать конкретный проект, иначе manager после клика по строке проекта 16 видит схемы текущего выбранного проекта в `projectStore` — это диссонанс с UX-ожиданием.
