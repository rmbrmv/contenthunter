# Дизайн: дневные лимиты публикаций на аккаунт (OP#139 / OP#184)

**Дата:** 2026-06-05
**Статус:** утверждён (брейншторм), готов к плану реализации
**Репозиторий кода:** delivery-contenthunter (autowarm); UI — `public/index.html`, бэкенд — `server.js`
**Kill-switch:** `PUBLISH_DAILY_LIMITS_ENABLED` (default OFF при выкатке, включается после верификации)

## Проблема

- **OP#184:** из-за ретраев аккаунт за день получает до ~4 публикаций/дёрганий приложения, что
  вредно для аккаунтов; нужно «не больше 3 в день» и «не в одно время».
- **OP#139:** объём выкладки зависит от клиента; в **первую неделю** нового проекта — не больше
  1 ролика/день, чтобы не спамить.

Сейчас лимита публикаций на аккаунт/день нет. Наполнитель очереди `assignUnicResultsToQueue()`
создаёт по записи на каждый результат уникализации, разнося их по устройству на
`PUBLISH_INTERVAL_MINUTES=20`, но без потолка на аккаунт. Ретраи (`retry_controller.js`)
переиспользуют ту же строку очереди; кап `RETRY_MAX_PER_CLASS_PER_DAY=3` — по классу ошибки,
не общий на аккаунт.

## Решения (из брейншторма)

1. **Два лимита** на аккаунт (`account_username × platform`) в день:
   - **A. реальные публикации** (`status IN done/published/published_no_url`);
   - **B. попытки** (исходная + ретраи).
2. Превышение **A** → **перенос лишних роликов на следующий день** (на этапе наполнения очереди).
3. **Глобальный дефолт + per-проект override.**
4. **Авто-ramp-up** первой недели: первые `rampup_days` от даты старта → лимит `rampup_max_per_day`.
   **Дата старта = `MIN(slot_date)`** по проекту в `validator_schedule_slots` (первый день расписания).
5. Превышение **B** → **сразу handoff в ручную** (`sameDayHandoff`).
6. Настройки — в новом разделе сайдбара **«Публикация»** (admin-only).

**Дефолтные глобальные значения:** `max_per_day=3`, `max_attempts_per_day=4`,
`rampup_days=7`, `rampup_max_per_day=1`.

## Архитектура (подход A — резолвер + два гейта)

```
publish_limits.js  (новый чистый модуль, тестируется изолированно как retry_decision.js)
  resolveDailyLimits({ global, projectOverride, startDate, today })
    → { maxPublishesPerDay, maxAttemptsPerDay, source: 'global'|'project'|'rampup' }
  мёрдж: global ← projectOverride (NULL-поля наследуют) ← ramp-up (если today в окне разгона)

Гейт A (посты)   — server.js assignUnicResultsToQueue(): при выборе scheduled_at для аккаунта
                   COUNT publish_queue на (account_username,platform,день), исключая
                   cancelled/skipped/past_slot_dropped; если ≥ maxPublishesPerDay → перенос
                   ролика на следующий день, повтор проверки (несколько дней вперёд). Разнос
                   +20 мин внутри дня сохраняется.

Гейт B (попытки) — retry_controller.js перед requeueOne(): COUNT попыток аккаунта за сегодня;
                   если ≥ maxAttemptsPerDay → sameDayHandoff (skip_reason
                   'retry_handoff:daily_attempts_cap') вместо requeue. Бонус к #184 «не в одно
                   время»: ретрай переставляется на ближайший свободный слот аккаунта (+20 мин),
                   а не в прошлое.

Хранилище        — глобал: autowarm_settings (key-value); per-проект: новая таблица
                   publish_project_limits.
API              — GET/PUT /api/publish-limits (admin-only, role==='admin').
UI               — раздел сайдбара «Публикация» → section-publish-settings (admin-only).
```

Всё за kill-switch `PUBLISH_DAILY_LIMITS_ENABLED`; при OFF резолвер не применяется, поведение
идентично текущему.

## Хранилище

**Глобал** — ключи в `autowarm_settings` (key-value, как `scheduler_active_hours_*`):
`publish_max_per_day`, `publish_max_attempts_per_day`, `publish_rampup_days`,
`publish_rampup_max_per_day`, `publish_daily_limits_enabled`.

**Per-проект override** — новая autowarm-таблица (НЕ трогаем кросс-репо `validator_projects`):
```sql
CREATE TABLE IF NOT EXISTS publish_project_limits (
  project_id          INT PRIMARY KEY,
  max_per_day         INT,            -- NULL = наследовать глобал
  max_attempts_per_day INT,           -- NULL = наследовать
  rampup_days         INT,            -- NULL = наследовать
  rampup_max_per_day  INT,            -- NULL = наследовать
  updated_at          TIMESTAMPTZ DEFAULT now()
);
```
Отсутствие строки = полностью глобальные дефолты.

## Гейт A — посты (наполнение)

Лимит A семантически ограничивает **реальные публикации/день**, но обеспечивается на этапе
наполнения: каждая назначенная (не-отменённая) запись очереди → не более одной реальной
публикации, поэтому достаточно не **назначать** больше `maxPublishesPerDay` записей на день.
Считаем именно назначенные записи (pending/running/done/failed), исключая отменённые.

В `assignUnicResultsToQueue()` (server.js ~6497–6788), в момент назначения `scheduled_at`
аккаунту на день `D`:
```sql
SELECT COUNT(*) FROM publish_queue
WHERE account_username=$1 AND platform=$2 AND DATE(scheduled_at)=$3
  AND status NOT IN ('cancelled','skipped','past_slot_dropped');
```
Если `count ≥ resolveDailyLimits(...).maxPublishesPerDay` для дня `D` → `D := D+1`, повтор
(цикл с разумным капом дней вперёд). Иначе ставим на `D` с существующим разносом +20 мин.

## Гейт B — попытки (ретраи)

В `retry_controller.js` (`retryFailedPublishes`) перед `requeueOne`: считаем суммарные попытки
аккаунта за сегодня (исходная публикация + все ретраи; считаем по событиям/счётчику попыток).
Если `≥ maxAttemptsPerDay` → `sameDayHandoff` (WP#215) со `skip_reason='retry_handoff:daily_attempts_cap'`.
Иначе `requeue`, переставляя `scheduled_at` на ближайший свободный слот аккаунта (+20 мин от
соседних публикаций этого аккаунта на сегодня), а не в прошлое (устраняет «в одно время»).

## Ramp-up первой недели

`startDate = MIN(slot_date)` по `project_id` из `validator_schedule_slots`. Если
`today < startDate + rampup_days` → `maxPublishesPerDay := rampup_max_per_day` (1). Иначе обычный
лимит. `startDate IS NULL` (нет слотов) → ramp-up пропускается, действует обычный лимит.

## UI — раздел «Публикация» (admin-only)

Пункт меню в существующем `sidebar-publishing` → новый `section-publish-settings`. Виден только
при `currentUser.role==='admin'` (по образцу скрытия модулей в `loadCurrentUser`, ~index.html:5134).
Бэкенд-эндпоинты `GET/PUT /api/publish-limits` дополнительно проверяют
`req.session.user?.role==='admin'` (как `POST /api/users`, server.js:169).

```
┌─ 📋 Публикация ────────────────────────────────────────┐
│ Глобальные лимиты (дефолт для всех проектов)            │
│   Макс. публикаций в день на аккаунт      [ 3 ]        │
│   Макс. попыток в день на аккаунт         [ 4 ]        │
│   Разгон новых проектов: первые [ 7 ] дней [ 1 ]/день  │
│   ☑ Лимиты включены (kill-switch)                      │
│   [ Сохранить ]                                        │
│                                                        │
│ Переопределение по проектам                            │
│   Проект [ ▼ выбрать ]   [ Добавить override ]          │
│   ┌────────────────────────────────────────────────┐  │
│   │ Проект    │ /день │ попыток │ разгон  │        │  │
│   │ Феминиста │  3    │   4     │ 7д→1    │ [ред]  │  │
│   │ Покер26   │  2    │   3     │ —(глоб) │ [ред]  │  │
│   └────────────────────────────────────────────────┘  │
│   (пусто = наследует глобальные)                       │
└────────────────────────────────────────────────────────┘
```
Список проектов для селекта — существующий `GET /api/projects`. Фронт читает настройки при
`nav('publish-settings')` → `loadPublishSettings()`, сохраняет PUT-запросом (паттерн
`saveSchedulerSettings`).

## Тестирование (TDD)

- **Резолвер** (`publish_limits.test.js`): глобал-only; project override (включая частичный с NULL);
  ramp-up активен/истёк; `startDate=NULL`; `enabled=false` → лимиты не применяются.
- **Гейт A**: день полон → перенос на D+1; несколько полных дней подряд; разнос +20 мин сохранён;
  при OFF поведение неизменно.
- **Гейт B**: кап попыток достигнут → handoff со скип-причиной; не достигнут → requeue с разносом;
  при OFF — старое поведение.
- **API**: 403 для не-админа на GET/PUT; валидация значений (положительные целые);
  upsert per-проект; удаление override (пустые поля).

## Edge cases

- Проект без строки в `publish_project_limits` → глобальные дефолты.
- `startDate IS NULL` → без ramp-up.
- Несколько паков с разными датами → дата старта берётся из расписания (`MIN(slot_date)`), а не
  из паков, поэтому неоднозначности паков не влияют.
- kill-switch OFF → ни один гейт не активен, миграция таблицы безопасна (создание пустой таблицы).

## Откат

- `PUBLISH_DAILY_LIMITS_ENABLED=0` (или `publish_daily_limits_enabled=false`) — мгновенно отключает
  оба гейта.
- Полный откат — revert коммитов + `DROP TABLE publish_project_limits` (данные настроек не критичны).

## Не входит в скоуп (YAGNI)

- Лимиты на уровне устройства/Pi (уже есть `MAX_CONCURRENT_PUBLISHES_PER_RASPBERRY`).
- Аналитика/графики по лимитам на дашборде (отдельная задача при необходимости).
- Изменение логики расписания в валидаторе (override живёт на стороне autowarm).
