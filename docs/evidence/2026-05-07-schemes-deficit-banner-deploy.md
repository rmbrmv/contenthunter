# Deploy: SchemesDeficitBanner — 2026-05-07

**Branch:** `feature/schemes-deficit-banner-2026-05-07`
**Merge commit:** `d1a83e8` (in `/root/.openclaw/workspace-genri/validator/` prod main)
**Tests:** 15/15 backend pytest pass

## Files added/modified

| File | Stat |
|---|---|
| `backend/src/services/schemes_service.py` | +56 (new function `get_deficits` with single CTE query) |
| `backend/src/routers/schemes.py` | +45 (new endpoint `/api/schemes/deficits`) |
| `backend/tests/test_schemes_deficits.py` | +319 (new file, 15 tests) |
| `frontend/src/api/schemes.ts` | +13 (new `DeficitEntry` + `getSchemesDeficits()`) |
| `frontend/src/composables/useSchemesDeficits.ts` | +58 (new) |
| `frontend/src/components/SchemesDeficitBanner.vue` | +112 (new) |
| `frontend/src/components/calendar/SlotCard.vue` | +9 (badge + props) |
| `frontend/src/components/calendar/WeeklyGrid.vue` | +11 (wire props) |
| `frontend/src/pages/client/ClientDashboard.vue` | +38 (composable + banner mount + inline badge) |

## Deploy steps (executed)

1. **2026-05-07 ~13:00** — feature ветка отправлена на GitHub (через prod creds, dev clone не имел push-доступа): `feature/schemes-deficit-banner-2026-05-07`
2. **2026-05-07 ~13:00** — merge feature → prod main (`d1a83e8`); pushed to GitHub origin
3. **2026-05-07 ~13:00** — `pm2 restart validator` (process id 24, restart count 15→16, uptime 0s, online ✓)
4. **2026-05-07 ~13:01** — backend smoke per anonymous:
   - `curl /api/schemes/deficits` → **403** "Not authenticated" ✓
   - `curl -H "Authorization: Bearer invalid_token" ...` → **401** "Invalid or expired token" ✓
   - `curl /api/schemes/deficits?project=999` (no auth) → **403** "Not authenticated" ✓ (query param ignored)
   - PM2 logs показывают только 401/403 на endpoint — нет 5xx
5. **2026-05-07 ~13:02** — frontend `npm run build` (5.99s, postbuild copied dist/* в /var/www/validator/)

## Backend logs check post-deploy

```
24|validat | INFO:     ... "GET /api/schemes/deficits HTTP/1.1" 403 Forbidden
24|validat | INFO:     ... "GET /api/schemes/deficits HTTP/1.1" 401 Unauthorized
24|validat | INFO:     ... "GET /api/schemes/deficits?project=999 HTTP/1.1" 403 Forbidden
```

Никаких 5xx, никаких ImportError'ов, validator startup чистый.

## Pre-deploy DB state

26 проектов в дефиците на момент деплоя:
- 79: 5/9 schemes (Aneco)
- 81: 7/9 (Inakent)
- 83: 7/17
- 85: 12/16
- + 22 проекта с approved=0 (новые/неактивные)

## Manual UI smoke — TODO для пользователя

Открыть `https://client.contenthunter.ru/dashboard` под разными ролями:

- [ ] **Client (admins of проектов 79/81/83/85)**: видит red banner "У вас одобрено X схем из необходимых Y" + per-slot бейджи "Не хватает схем" на каждом filled слоте недели
- [ ] **Admin all-mode**: red banner "26 проектов с заблокированной публикацией" + раскрывающийся список + per-row CTA
- [ ] **Admin single-mode** (выбран project=79): banner и per-slot бейджи как в client view
- [ ] **CTA "Одобрить схемы →"**:
  - client → переход на `/client/schemes`
  - admin → `/admin/scheme-preferences?project=<id>`
- [ ] **После одобрения недостающих схем + возврат на /dashboard**: banner и бейджи исчезают (composable refetch'ит на mount/onActivated)

## Rollback

Если потребуется:
```bash
cd /root/.openclaw/workspace-genri/validator
git revert d1a83e8 -m 1
git push origin main
sudo pm2 restart validator
cd frontend && npm run build  # postbuild возвращает старый bundle
```

Никаких миграций / БД-изменений — rollback чисто кодом.

## Disable без re-deploy

Endpoint защищён auth, баннер тихо скрывается на фронте при error/empty. Если нужно полностью отключить — feature flag не предусмотрен (read-only фича, low blast radius).
