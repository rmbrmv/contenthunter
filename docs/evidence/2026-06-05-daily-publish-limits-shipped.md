# Дневные лимиты публикаций (OP#139/#184) — SHIPPED+DEPLOYED (инертно) 2026-06-05

Брейншторм → спек → план → subagent-driven TDD (6 задач, по имплементеру + spec/quality-ревью на
задачу) → финальное холистическое ревью (без блокеров) → merge в `delivery-contenthunter/main`
(`3b41792 → 1c75adf`) → прод pull + `pm2 restart 35`. **Задеплоено инертно: kill-switch
`PUBLISH_DAILY_LIMITS_ENABLED` (default OFF), поведение не изменено** до включения.

Спек: `docs/superpowers/specs/2026-06-05-daily-publish-limits-design.md`.
План: `docs/superpowers/plans/2026-06-05-daily-publish-limits.md`.

## Что сделано

Два дневных лимита на аккаунт (`account_username × platform`):

- **Гейт A (посты, OP#139)** — `server.js assignUnicResultsToQueue`: не назначать больше
  `maxPublishesPerDay` публикаций/аккаунт/день; лишние переносятся на ближайший следующий день
  с местом (helper `computeDeviceSlot`, поиск `nextAvailableDay`); при исчерпании 30-дн окна —
  аккаунт пропускается (не переполняет день). Авто-**ramp-up** первой недели: первые
  `rampup_days` от `MIN(slot_date)` проекта → лимит `rampup_max_per_day`.
- **Гейт B (попытки, OP#184)** — `retry_controller.js retryFailedPublishes`: общий дневной кап
  ПОПЫТОК аккаунта (все запуски publisher, включая успешные — «дёрганья приложения») ≥
  `maxAttemptsPerDay` → handoff в ручную (`skip_reason='retry_handoff:daily_attempts_cap'`,
  лейбл в `retry_labels.js`) вместо ретрая. Разнос +20 мин сохранён.

Архитектура — **подход A**: чистый резолвер `publish_limits.js` (глобал `autowarm_settings` +
per-проект override `publish_project_limits` + ramp-up), потребляемый обоими гейтами и API.

- **Хранилище:** глобал — ключи `publish_max_per_day`/`publish_max_attempts_per_day`/
  `publish_rampup_days`/`publish_rampup_max_per_day`/`publish_daily_limits_enabled` в
  `autowarm_settings`; per-проект — новая таблица `publish_project_limits` (NULL-поля наследуют
  глобал; idempotent `CREATE TABLE IF NOT EXISTS` в `initDB`).
- **API:** `GET/PUT /api/publish-limits` (admin-only, `requireAdmin`).
- **UI:** раздел сайдбара «Публикация» (admin-only) — глобальные лимиты + per-проект override +
  таблица текущих override.

**Дефолты:** 3 поста / 4 попытки / ramp-up 7 дней → 1. Дата старта ramp-up = `MIN(slot_date)`.

## Качество

- TDD: чистый резолвер (17 тестов), гейты (6), API-валидатор (3) — все зелёные. Полный сьют
  485/486 (1 fail предсуществующий `takeItem: 404`, inactive-project gate, не из фичи).
- Каждая задача: spec-ревью + code-quality-ревью. Поймано и исправлено: гейт A — `null` при
  исчерпании lookahead (скип аккаунта вместо переполнения дня); гейт B — человекочитаемый
  handoff-лейбл `daily_attempts_cap` + комментарий о намеренном учёте успешных публикаций в капе.
- Финальное холистическое ревью: единый резолвер/`project_id`/`startDate`, единый kill-switch во
  всех 3 точках, OFF-эквивалентность подтверждена, миграция идемпотентна. TZ-расхождение
  ramp-up между гейтами доказано безвредным (гейт B не читает ramp-up-зависимое поле).

## Деплой (инертный)

- `delivery-contenthunter/main`: `1c75adf` (merge ветки `feat/publish-daily-limits`, 8 коммитов).
- Прод `/root/.openclaw/workspace-genri/autowarm`: pull + `pm2 restart 35`. Таблица
  `publish_project_limits` создана `initDB` (0 строк). Флаг `publish_daily_limits_enabled` не задан
  = OFF. `/api/health` 200, `/api/publish-limits` 401 без сессии (эндпоинт жив, admin-gate).
- **Поведение не изменено** — оба гейта no-op при OFF.

## Остаток / follow-up

- **Включение:** через раздел «Публикация» (чекбокс «Лимиты включены») или
  `PUBLISH_DAILY_LIMITS_ENABLED=true` — после смоук-проверки UI Данилом.
- Follow-up (Minor из ревью, не блокеры): FK `publish_project_limits.project_id` →
  `validator_projects(id)`; верхняя граница значений в `validateLimitsBody`; комментарий в гейте B
  о неиспользуемом ramp-up-поле; тех-долг TZ-группировки `DATE(scheduled_at)` (зеркало WP#247).

OP#139 + OP#184 → «Тестирование».
