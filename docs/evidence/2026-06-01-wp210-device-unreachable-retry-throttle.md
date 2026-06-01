# WP#210 — троттлинг ретраев adb device-unreachable (реализация) — 2026-06-01

## Проблема

`switch_failed_unspecified` = доминант живых IG-падений (58/3д, растёт) = adb-preflight
недоступность девайса (`adb_devices_unreachable`/`_not_ready`/`_offline`). Эти коды лежали
в `error_class='network'` ∈ TRANSIENT → контроллер ретраев (`retry_decision.js`)
requeue'ил их как обычный сетевой сбой до 3×/день. Итог — churn: **58 фейлов/3д = 21
уникальная задача, ср. 2.76 ретрая/задачу (макс 5)**, пустые ретраи против заведомо
офлайн-девайса (часто SPOF-шлюз 147.45.251.85).

`retry_strategy='manual'` на `adb_devices_unreachable` контроллером **игнорировался** (он
решает по `error_class`, не по `retry_strategy`).

## Фикс (delivery-contenthunter PR#139 → main 05dbf6c)

Подход: **throttled auto-recovery** (выбран Данилом).

1. **Миграция** `20260601_wp210_device_unreachable_class.sql` (+rollback): новый
   `error_class='device_unreachable'` (ALTER CHECK), переклассификация 3 adb-кодов,
   backfill in-flight (3д).
2. **`retry_decision.js`**: отдельная ветка для `device_unreachable` с узким дневным
   капом (env `RETRY_MAX_DEVICE_HEALTH_PER_DAY`, дефолт 2): под капом → `requeue`
   `device_health_recheck`; сверх капа → `wait` `device_health_wait_tomorrow`.
   `window_exhausted` (2 дня) по-прежнему → `handoff` в ручную.
3. **`retry_controller.js`**: проброс `deviceHealthThrottle` + `maxDeviceHealthPerDay`;
   счётчик `attemptsTodayThisClass` изолирован новым классом (точный кап без примеси
   реального network).
4. **`retry_labels.js`**: текст для `device_health_recheck`.

Поведение: девайс восстанавливается сам (гейт #195 держит спавн), задача авто-доедет
в пределах 2-дневного окна, без churn'а и без засора ручной очереди инфра-шумом.

**Kill-switch** `RETRY_DEVICE_HEALTH_THROTTLE_ENABLED=false` → старое поведение (чистый
rollback: класс трактуется как transient).

## Связь

- **#207** (PR#138) — labeling: корректный `error_code` на preflight; retry НЕ трогал.
  WP#210 — поведенческий слой поверх. Вместе: #207 даёт правильный код → #210 троттлит.
- **#195** — scheduler device-health gate (не спавнит на unauthorized/offline).
- **#199** — каталог/таксономия preflight-кодов.

## Верификация

- TDD: decision 16/16, labels 8/8, controller 13/13, migration 1/1.
- Полный прогон (последовательно): 224 теста, 221 pass, 1 fail = пре-существующий WP140
  data-drift (некаталогизированные коды др. WP), не связан.
- codex review: 0 регрессий.
- Деплой: миграция применена к проду; прод pull → 05dbf6c; PM2 id35 рестарт, стабилен.
- Остаток: live-verify троттлинга по след. всплеску фейлов 147.45.251.85.
