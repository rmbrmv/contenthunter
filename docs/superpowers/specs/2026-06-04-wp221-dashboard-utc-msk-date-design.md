# WP#221 — Дашборды: тот же UTC/MSK-сдвиг в группировке по дате

**Тип:** Ошибка (фоллоу-ап WP#220) · **Приоритет:** Обычный (отчётность, не hot-path) · **OpenProject:** #221

## Проблема

Сервер и хранение работают в **UTC** (`SHOW timezone` = `Etc/UTC`). Колонки `created_at`/`scheduled_at` объявлены как `timestamp without time zone`, но значения в них — по Гринвичу (naive-UTC). Приём `(ts AT TIME ZONE 'Europe/Moscow')::date` трактует naive-значение как уже-московское и **вычитает 3 часа вместо прибавления** → строки около полуночи (00:00–02:59 МСК = 21:00–23:59 UTC прошлых суток) попадают в отчётах не в те сутки.

Проверено эмпирически в Postgres:

```sql
WITH t AS (SELECT TIMESTAMP '2026-06-04 22:30:00' AS ts)  -- naive-UTC = 01:30 МСК 05-го
SELECT (ts AT TIME ZONE 'Europe/Moscow')::date,                       -- 2026-06-04  ❌
       (ts AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date;    -- 2026-06-05  ✅
```

Корректный рецепт — тот же, что уже применён в WP#220 (`retry_controller.js:86-93`):
`(ts AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date`.

## Объём (полный инвентарь, 9 мест)

Исходный триаж WP#220 искал по литералу `AT TIME ZONE 'Europe/Moscow'` и **пропустил места, спрятанные за константой `${MSK}`** в `publish_planner.js`. Полный инвентарь по прод-коду (без тестов):

### 🔴 Чиним — naive-UTC + одинарный `AT TIME ZONE 'Europe/Moscow'`

| Файл:строка | Колонка | Тип колонки | Роль |
|---|---|---|---|
| `publish_planner.js:300` | `created_at` (publish_tasks) | naive-UTC | список ошибок по дате — **назван в задаче** |
| `server.js:2728` | `pt.created_at` | naive-UTC | фильтр `business_date` — **назван в задаче** |
| `publish_planner.js:173` | `created_at` (publish_tasks) | naive-UTC | попытки по дате (через `${MSK}`) |
| `publish_planner.js:155` | `pq.scheduled_at` | naive-UTC | `chain_id` |
| `publish_planner.js:156` | `pq.scheduled_at` | naive-UTC | `scheduled_date` |
| `publish_planner.js:163` | `pq.scheduled_at` | naive-UTC | `WHERE … BETWEEN` |
| `publish_planner.js:222` | `pq.scheduled_at` | naive-UTC | `business_date` карточки |
| `publish_planner.js:230` | `pq.scheduled_at` | naive-UTC | `WHERE … BETWEEN` |
| `publish_planner.js:265` | `pq.scheduled_at` | naive-UTC | JOIN со слотами `= s.slot_date` |

### 🟢 НЕ трогаем — timestamptz, одинарный `AT TIME ZONE` корректен

| Файл:строка | Колонка | Тип |
|---|---|---|
| `publish_planner.js:157` | `manual_handoff_at` | timestamptz |
| `publish_planner.js:187,190` | `q.published_at` (validator_manual_publish_queue) | timestamptz |
| `server.js:1341` | `h.hour` (из `generate_series(NOW()…)`) | timestamptz |
| `retry_controller.js:*` | уже исправлено в WP#220 / timestamptz | — |

Типы колонок подтверждены через `information_schema.columns`.

### Бонус-корректность (JOIN со слотами)

`publish_planner.js:265` сравнивает `(pq.scheduled_at <buggy>)::date = s.slot_date`, где `s.slot_date` — чистый `date`-столбец (целевой МСК-день, **независимый** от scheduled_at). Сейчас у полуночных слотов кривой LHS не матчит верный `slot_date` → показываются фантомные плановые карточки. Фикс **исправляет** JOIN, а не ломает его. Это и снимает главный риск расширенного объёма.

## Дизайн фикса

### Две типобезопасные константы (устраняем ловушку в корне)

Нельзя просто «починить» глобальную `MSK` — она корректна для timestamptz-колонок (157/187/190). Вводим вторую константу и оставляем первую только для timestamptz, с предупреждающим комментарием:

```js
// naive-UTC колонки (created_at, scheduled_at — значения по Гринвичу в timestamp without time zone):
// пометить как UTC, затем перевести в МСК. См. WP#220/#221.
const MSK_FROM_UTC = `AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow'`;
// ⚠ КОРРЕКТНО ТОЛЬКО для timestamptz-колонок (manual_handoff_at, published_at).
//    Для naive-UTC использовать MSK_FROM_UTC, иначе дата уезжает на сутки у полуночи.
const MSK = `AT TIME ZONE 'Europe/Moscow'`;
```

### Точечные правки

- `publish_planner.js`: в 7 naive-местах через константу (155, 156, 163, 173, 222, 230, 265) заменить `${MSK}` → `${MSK_FROM_UTC}`.
- `publish_planner.js:300`: литерал → `(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date::text`.
- `server.js:2728`: → `(pt.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date = $?::date`.
- 157/187/190 — без изменений (остаются на `MSK`).

Без миграции (схема БД не меняется). **Без kill-switch** — read-only дата-бакетинг, нет hot-path/мутаций, откат тривиален через `git revert` + `pm2 restart`.

## Тестирование (TDD)

**SQL-снэпшот-тесты (live DB, как существующие `test_*.test.js`):**
1. `MSK_FROM_UTC` на граничном naive-UTC значении `2026-06-04 22:30:00` → бизнес-дата `2026-06-05` (а не `2026-06-04`).
2. `MSK` на timestamptz `2026-06-04 22:30:00+00` → по-прежнему верно (регрессия: timestamptz-места не сломаны).
3. Контраст: тот же naive-UTC через старый `MSK` даёт `2026-06-04` — фиксируем, что баг был реален.

**Интеграционный смок планировщика:**
4. Вставить `publish_queue`-строку с полуночным `scheduled_at` (напр. 22:30 UTC) и соответствующий `validator_schedule_slots.slot_date = '2026-06-05'`; вызвать планировщик; убедиться, что строка группируется под `business_date = '2026-06-05'` и JOIN со слотом матчится (нет фантомной плановой карточки).

## Деплой

Меняются `publish_planner.js` + `server.js` (веб-сервер) → прод `git pull` + `sudo pm2 restart 35`. Миграции нет. Код-репозиторий = **delivery-contenthunter** (autowarm), прод-каталог `/root/.openclaw/workspace-genri/autowarm` (доступен claude-user без sudo на pull; pm2 — под root). Правки кода веду в **изолированном git worktree** delivery-contenthunter (защита от гонки общего checkout — параллельные IG/YT/TT-сессии). Доки — в rmbrmv/contenthunter отдельным PR.

## Критерий приёмки

- Все 9 мест используют корректный рецепт; 4 timestamptz-места не тронуты.
- Тесты 1–4 зелёные; регрессия `publish_planner`/планировщика без новых падений.
- На проде: карточка планировщика и список ошибок у полуночной границы показывают корректные МСК-сутки; фантомные плановые карточки у полуночных слотов исчезают.
- OP#221 → Тестирование, затем верификация в UI Данилом → Готово.
