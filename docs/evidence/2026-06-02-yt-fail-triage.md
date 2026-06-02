# YT-триаж упавших задач за 2026-06-02

## Что смотрели
Все `publish_tasks` где `platform='YouTube'`, `status IN ('failed','preflight_failed')`,
за МСК-сутки 02.06 (`created_at >= '2026-06-01 21:00' UTC`, т.к. `created_at` хранится
**naive-UTC**, сессия БД `Etc/UTC`).
Источник: openclaw Postgres (`72.56.107.157:5432`, креды `openclaw:openclaw123`),
таблица `publish_tasks` (events JSONB, log, error_code, error_class) + `publish_queue`.
Скринкастов нет: у всех доминантных задач `screen_record_url IS NULL` — устройство не готово
ещё на ADB-preflight, записывать нечего.

## Объём (МСК-сутки 02.06)
| status | count |
|---|---|
| done | 72 |
| failed | 38 |
| running | 5 |
| awaiting_url | 2 |
| published_no_url | 2 |
| preflight_failed | 1 |

YT success-rate ≈ 72/(72+39) ≈ **65%**.

## Разбивка падений (failed + preflight_failed) по error_code
| error_code | count | error_class |
|---|---|---|
| **adb_device_not_ready** | **33** | **device_unreachable** |
| yt_picker_target_absent | 3 | ui_changed |
| (null) | 1 | (null) |
| switch_failed_unspecified | 1 | unknown |
| timeout | 1 | network |

Доминанта — `adb_device_not_ready` (device_unreachable) = **33 из 39 (85%)**.

## Ключевая находка — один мёртвый девайс + ретрай-churn по TZ-багу (82% всех падений)

### Срез доминанты
- 33 `adb_device_not_ready`: **31 — одно устройство `RF8YA0V7FKW`** (+ 2 — `RF8Y90LC1SB`).
- Все 31 — **ОДНО намерение** (`client_publish_id c1db1b1b-2516-…`), ретраенное **31 раз**
  за 00:43→06:18 МСК, ровный интервал **10 мин**.
- Состояние устройства в events: `"line": "RF8YA0V7FKW unauthorized usb:3-2.3.1 …"`,
  `"state": "unauthorized"` — слетела USB-авторизация ADB (нужна физ. ре-авторизация, ops/#99).
- adb_host `147.45.251.85`, raspberry 5, аккаунт `Lead_Content_1`.

### Почему 31, хотя есть защиты
В коде autowarm (`delivery-contenthunter`) есть ДВА механизма, которые ровно это должны гасить:
- **WP#195** (`scheduler.js`): device-health gate — не спавнит publish на `unauthorized`/`offline`.
- **WP#210** (`retry_controller.js` + `retry_decision.js`): для `device_unreachable` узкий
  дневной кап `RETRY_MAX_DEVICE_HEALTH_PER_DAY=2`.

Факт из БД: `publish_queue#8611.last_retry_reason='device_health_recheck'`, в events 31 задачи —
**30 retry-маркеров `rule=device_health_recheck`** (`retry_decision.js:33`). Т.е. троттл WP#210
ВКЛЮЧЁН и работает, но его дневной кап `attemptsTodayThisClass >= 2` почти всю ночь возвращал
FALSE → бесконечный requeue каждые 10 мин.

### Корень — асимметрия `AT TIME ZONE` в подсчёте «сегодня» (доказано)
`retry_controller.js:61-67` считает попытки за день так:
```sql
... AND (created_at AT TIME ZONE 'Europe/Moscow')::date
        = (now() AT TIME ZONE 'Europe/Moscow')::date
```
`created_at` — `timestamp WITHOUT time zone`, и значение = **UTC-стенные часы** (now()=09:32+00 ≈
max(created_at)=09:28; будь оно МСК, было бы ~12:28). Для naive-таймстампа
`created_at AT TIME ZONE 'Europe/Moscow'` ТРАКТУЕТ его как Moscow-локальное и сдвигает на **−3ч**.
А `now()` (timestamptz) `AT TIME ZONE 'Europe/Moscow'` — наоборот, даёт Moscow-стенные часы (+3ч).
Направления противоположны → даты не совпадают.

Эффект: все задачи, созданные в **00:00–06:00 МСК (21:00–03:00 UTC), попадают в «вчера»** и
НЕ считаются «сегодня». Прямое доказательство по этому намерению (now=12:32 МСК):

| | значение |
|---|---|
| buggy-подсчёт «сегодня» `(created_at AT TZ Moscow)::date` | **2** |
| корректный MSK-подсчёт `(created_at AT TZ UTC AT TZ Moscow)::date` | **31** |

29 из 31 попыток забакетились в `2026-06-01` (неверно), только 2 (созданные после 03:00 UTC /
06:00 МСК) — в `2026-06-02`. Кап `>=2` сработал лишь в ~06:18 МСК, когда 2 задачи наконец попали
в «сегодняшний» бакет — поэтому churn и остановился на 31-й попытке.

### Масштаб бага шире device_unreachable
Тот же кап-запрос (`retry_controller.js:61-67`) питает и **generic дневной кап**
(`maxPerClassPerDay=3`, `retry_decision.js:37`) для ВСЕХ transient-классов (`network`,
`unknown`, `rate_limited`). Значит **любой** transient-фейл в окне 00:00–06:00 МСК получает
ретраи без капа. То же окно — ночь, когда оператор спит и устройство некому переавторизовать,
т.е. защита обнулена ровно тогда, когда нужнее всего. Баг platform-agnostic (IG/TT тоже).
Зеркальный риск в `retry_controller.js:69-73` (`daysSinceFirstAttempt` / окно 2 дней) — те же
два `AT TIME ZONE 'Europe/Moscow'` над naive-`created_at`/`min(created_at)`.

### Предлагаемый фикс
Интерпретировать naive-`created_at` как UTC перед конвертацией в МСК:
```sql
(created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date
```
(`now()` — уже timestamptz, его трогать не нужно). Поправить оба места (строки 64-65 и 70-71).
Минимально, низкорисково, чисто корректность. TDD: тест на задачу, созданную в 01:00 МСК
(22:00 UTC), должна считаться «сегодня».
⚠️ Та же ошибка вероятна в дашборд-агрегациях (`2026-05-25-wp84-wp110-analytics-source-data.md`
рекомендует именно баговый `(ts AT TIME ZONE 'Europe/Moscow')::date`) — отдельная проверка.

## Прочие коды (длиннохвост)
- `yt_picker_target_absent` = 3 (ui_changed) — известный (смена аккаунтов, #202 ops), не приоритет.
- `timeout`/`switch_failed_unspecified`/`(null)` — по 1, дормант.

## Связанные задачи
- Ops: переавторизовать `RF8YA0V7FKW` (физ. «Allow USB debugging») — #99.
- WP#210 — троттл сам по себе корректен, но обнуляется этим TZ-багом ночью.
- WP#195 — device-health gate (комплементарен).
- WP#215 (Бэклог) — продуктовая идея «ретраи только день в день» (другое).

## Вывод
Доминирующий **код-фиксируемый** баг за сегодня = неверный учёт «сегодня» в дневном капе ретраев
(`AT TIME ZONE` поверх naive-UTC `created_at`): кап молчит в окне 00:00–06:00 МСК, из-за чего одно
`unauthorized`-устройство (`RF8YA0V7FKW`) сожгло **31 пустую попытку** на одном намерении за ночь
(82% всех YT-падений 02.06). → Заведён WP на фикс TZ-учёта дневного капа.
