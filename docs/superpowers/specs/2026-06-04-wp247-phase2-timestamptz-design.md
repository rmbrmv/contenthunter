# WP#247 Фаза 2 — миграция naive-UTC → timestamptz (устранение класса UTC/MSK-багов в корне)

- **OpenProject:** OP#247 (тип Ошибка, assignee `danil`, статус «В разработке»)
- **Дата:** 2026-06-04
- **Ветка:** `wp247-phase2-timestamptz-migration`
- **Follow-up от:** WP#221 (фикс группировки дашбордов), WP#247 Фаза 1 (per-user пояс отображения, SHIPPED 04.06)
- **Код:** репозиторий `delivery-contenthunter` (autowarm); прод-чекаут `/root/.openclaw/workspace-genri/autowarm`

## Проблема

Колонки времени `created_at`/`scheduled_at` (и др.) в ключевых таблицах хранятся как
`timestamp without time zone` (наивно, по факту в UTC). Это породило целый **класс багов**
(WP#220, WP#221, WP#239, WP#247 Фаза 1): каждое место отображения/группировки вынуждено
вручную дописывать `AT TIME ZONE 'UTC' AT TIME ZONE '<пояс>'`, и пропуск/ошибка в этой
двойной конвертации уводит дату на сутки/часы.

### Ключевой инсайт: система сейчас КОРРЕКТНА — но «по счастливой случайности»

Проверено вживую: **Session TimeZone БД = `Etc/UTC`**, процесс Node и ОС — тоже `Etc/UTC`.
Поэтому:
- Диспатч `scheduled_at <= NOW()` работает верно: наивный `timestamp` приводится к timestamptz
  по сессии = UTC → корректно. **Но это скрытая зависимость от `SET timezone`** — смена пояса
  сессии тихо сломала бы планирование.
- Сырые JS-чтения (`new Date(row.scheduled_at)`) тоже UTC-корректны, т.к. Node парсит наивную
  строку в локальном поясе процесса = UTC.

**Вывод: Фаза 2 — это устранение foot-gun'а (класс-риска), а НЕ починка живого бага.**
Цель — убрать наивную репрезентацию, чтобы ручной префикс `AT TIME ZONE 'UTC'` стал не нужен,
а корректность перестала зависеть от настройки сессии/процесса.

## Масштаб (согласован)

Мигрируем наивные time-колонки **двух таблиц**, которые показываются с конвертацией пояса
(дашборды/Лог/планировщик) и драйвят планирование/жизненный цикл — т.е. весь класс багов:

- `publish_queue`: `scheduled_at`, `created_at`, `updated_at`
- `publish_tasks`: `created_at`, `started_at`, `updated_at`, `url_capture_last_attempt_at`

**Вне скоупа (YAGNI):** `unic_results`, `unic_tasks`, `autowarm_users` и прочие ~40 таблиц —
они почти не отображаются с конвертацией пояса. Возможный отдельный sweep позже.

Уже `timestamptz` (не трогаем): `manual_handoff_at`, `last_retried_at`, `manual_queue.*`.

## Принцип: миграция instant-preserving

Раз вся среда в `Etc/UTC`, `ALTER … TYPE timestamptz USING col AT TIME ZONE 'UTC'` сохраняет
**тот же момент времени**. Наблюдаемое поведение (диспатч и отображение) не меняется — меняется
лишь внутренняя репрезентация и исчезает зависимость от пояса сессии.

## Архитектура решения

### 1. Миграция БД

Файлы по конвенции репо:
`migrations/20260604_wp247_phase2_timestamptz.sql` + `…__rollback.sql`.

- Forward: для каждой из 7 колонок
  `ALTER TABLE <t> ALTER COLUMN <c> TYPE timestamptz USING <c> AT TIME ZONE 'UTC';`
  Всё в одной транзакции (BEGIN/COMMIT).
- Rollback: обратный `ALTER … TYPE timestamp without time zone USING <c> AT TIME ZONE 'UTC';`
  (тоже instant-preserving назад).
- `DEFAULT now()` где есть — сохранить (now() корректен для обоих типов).
- Таблицы маленькие (`publish_queue` ~10k/15MB, `publish_tasks` ~10k/82MB) → перезапись и
  `ACCESS EXCLUSIVE`-лок субсекундные, отдельное окно обслуживания не требуется (выкат в окно
  низкого трафика).

### 2. Изменения кода (минимальные)

4 SQL-читателя переключить `naiveTzClause(...) → tzClause(...)` (убрать префикс
`AT TIME ZONE 'UTC'`), иначе на timestamptz будет двойная конвертация:

- `publish_planner.js:144` (`const NAIVE = naiveTzClause(TZ)`)
- `publish_planner.js:296` (`const NAIVE = naiveTzClause(TZ)`)
- `server.js:2122` (task-ветка date_trunc по scheduled_at)
- `server.js:2766` (`pt.created_at` business_date фильтр)

> Эти 4 места используют переменную `NAIVE`/инлайн-clause только для скоупных колонок
> (`pq.scheduled_at`, `pq.created_at`, `pt.created_at`). После флипа они читают timestamptz
> через `AT TIME ZONE '<пояс>'`.

Хелпер `naiveTzClause` в `tz_display.js` **оставить как шим** (на случай наивных колонок вне
скоупа); его удаление — отдельный тех-долг. Сырые JS-чтения (`new Date(row.X)`, расчёты
длительностей) **не трогаем** — они instant-корректны до и после.

### 3. Секвенс выката и безопасность

- **Без рантайм-kill-switch** — тип колонки не переключается флагом; флаг сделал бы SQL-код
  некогерентным фактическому типу. Роль отката играет **готовая протестированная
  rollback-миграция** + revert коммита с флипом читателей.
- Порядок: применить forward-миграцию → **сразу** `git pull` + `pm2 restart` server.
- Окно скоса: между ALTER и рестартом старый код применит `naiveTzClause` к уже-timestamptz
  колонке → отображение дат скошено на ~3ч **только в дашбордах/планировщике** в течение секунд.
  Диспатч `scheduled_at <= NOW()` от naiveTzClause не зависит и становится строго корректнее —
  планирование в окне скоса не страдает.

## Аудит писателей (red-flag для плана)

Все INSERT/UPDATE `scheduled_at`/`created_at` биндят значение параметром (`$N`) или используют
`NOW()`/интервалы. Планировщик строит слоты через `startOfDayUtcMs → toISOString` (UTC-ISO),
оконные сравнения используют UTC-инстанты. **В план включить задачу-аудит**: подтвердить, что
ни один писатель не кладёт «наивно-локальную» (wall-clock не-UTC) строку — иначе после ALTER
интерпретация значения изменится. Писатели: `server.js:2605/6535/6594/6808`, `2654`, `7123/7134/7239`,
`watchdog_breaker.js:33`.

## Тестирование (TDD)

- **Red-тесты:** для timestamptz-колонки `tzClause` даёт корректные метки MSK/Ekb, а старый
  `naiveTzClause` дал бы двойную конвертацию (доказать разницу на фикстуре).
- **Регрессия:** `test_tz_display`, `test_wp221_dashboard_tz`, planner/funnel/report-тесты —
  прогнать на новой схеме (timestamptz).
- **Live instant-equality:** до/после ALTER `SELECT <col>` по выборке id — момент идентичен.

## Верификация (после деплоя)

1. Instant-равенство выборки до/после (SQL).
2. Диспатч-тик не разъехался (задачи берутся в то же время).
3. Дашборды / Лог событий / планировщик показывают те же даты, что и до миграции, при
   дефолтном поясе (МСК) и при пользовательском (Ekb).
4. `information_schema.columns` подтверждает 7 колонок = `timestamp with time zone`.

## Что НЕ делаем (YAGNI)

- Не мигрируем остальные ~40 таблиц.
- Не удаляем `naiveTzClause`.
- Не вводим рантайм-флаг для типа колонки.
- Не делаем zero-downtime add-column-swap (избыточно для ~10k строк).
