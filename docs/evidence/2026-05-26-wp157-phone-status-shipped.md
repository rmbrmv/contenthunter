# WP #157 — таблица статусов телефонов: SHIPPED + DEPLOYED

**Дата:** 2026-05-26
**Задача:** OpenProject #157 «Сделать таблицу для отслеживания статуса телефона»
**Статус:** SHIPPED + DEPLOYED → OpenProject «Тестирование»

## Что сделано

В операторском дашборде (delivery.contenthunter.ru / GenGo2/delivery-contenthunter) добавлен раздел **«Статусы телефонов»** в группе «Выкладка»: таблица по каждому телефону с текущим статусом и подробной строкой из лога, поллинг ~7с.

Read-only агрегатор, **без миграций и правок воркеров**:
- `phone_status.js` — чистая `resolvePhoneStatus` (приоритет, stale-guard, fail-closed) + `fetchPhoneStatuses(pool, now)`.
- `GET /api/devices/status` (requireAuth) в `server.js`.
- Фронт-раздел `#section-phone-status` + `phsLoad/phsRender` в `public/index.html`.

Статус собирается из **6 подсистем по `device_serial`**:
- автовыкладка → `publish_tasks` (running/processing)
- ручная выкладка → `validator_manual_publish_queue` (`operator_status='in_progress'`; `queued` = счётчик очереди, не занятость)
- создание аккаунтов → `factory_reg_tasks` (running)
- прогрев → `autowarm_tasks` (аккаунт) + `phone_warm_tasks` (телефон); running=active, paused=reserved
- проверка выложенного → `archive_tasks` (running; нет `updated_at` → свежесть по `started_at`)

**Защиты:** fail-closed — при недоступном источнике телефон без подтверждённого ACTIVE помечается «неизвестно», НИКОГДА не «свободен». stale-guard — running старше `PHONE_STATUS_STALE_MINUTES` (дефолт 10 мин) → «возможно завис», не «свободен».

## Как проверено

- Тесты: 14 чистых (DB-free, дефолтный сьют) + 2 live-DB (`test_phone_status_fetch_live.test.js`, в корне вне `tests/*` по конвенции) — зелёные.
- Живой `fetchPhoneStatuses`: 181 телефон, `degraded=false`; среди прочего корректно поймал ручную выкладку, зависшую in_progress ~30ч → «возможно завис» (а не «свободен»).
- codex review спеки, плана и итогового диффа — 0 P1 (исправлены 2×P1 fail-closed; ложный флаг про `account_switcher.py` из-за уехавшего origin/main отбит проверкой merge-base).
- Post-deploy smoke на проде: `/api/devices/status` → 401 (роут жив, auth-gated), `/` → 200, логи PM2 чисты.

## Деплой

- GitHub GenGo2/delivery-contenthunter `main` → `6c3109d` (fast-forward, без force).
- Прод `/root/.openclaw/workspace-genri/autowarm` → ff-pull до `6c3109d`; `pm2 restart 35` (id 35 = дашборд autowarm), online.

## Осталось

- Визуальная сверка операторами: открыть раздел на нескольких телефонах, сверить статус с реальной работой.
- При необходимости подстроить порог «возможно завис» (10 мин может быть агрессивен для долгой ручной выкладки, но ошибается в безопасную сторону).

## Корректировки по ходу

- Первая разведка ошибочно сообщила, что у создания аккаунтов нет таблицы задач → чуть не сделали лишний per-device lock/гибрид. Проверка по коду нашла `factory_reg_tasks` → подход остался чисто read-only tasks-based (с подтверждением пользователя; отдельная таблица/задача не заводились).

Спека/план: `docs/superpowers/specs|plans/2026-05-26-wp157-phone-status-table*.md`.
