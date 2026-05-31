# WP#195 — adb_device_not_ready спайк: device-health gate

**Дата:** 2026-05-31 · **OpenProject:** #195 → Тестирование · **Деплой:** autowarm prod main `92cef97`, pm2#35 restart

## Симптом
Спайк `adb_device_not_ready` 5→59 после 29.05 — вторая причина обвала success-rate TikTok (28%).

## Корень (доказан по прод-БД)
Весь спайк — **ОДНО устройство `RF8YA0V7LEH`** (adb_host 147.45.251.85, **порт 15048 / Pi#5**) в adb state `unauthorized` (USB-авторизация слетела: `usb:3-2.3.2 transport_id:965`). Кросс-платформенно (TikTok 59 / Instagram 14 / YouTube 13 за 3д) → **device-level, не TikTok-баг**. `_preflight_adb_device` (`publisher_base.py:1591`) эмитит `adb_device_not_ready`, когда serial виден в `adb devices -l`, но state≠`device`. Диспатчер слал на устройство десятки публикаций → каждая падала на preflight + жгла прогон (pre-warm/screen-record/S3) + засоряла fail-статистику.

## Разделение зон (без дублей)
- Физический re-auth устройства → **WP#99** (ops/Данил, Запланировано).
- Переклейка error_code (`adb_device_not_ready` ≠ `switch_failed_unspecified`) → **WP#199** (`triage_classifier.py`, в разработке).
- **WP#195 (эта)** → превентив: не дать одному unauthorized-девайсу плодить фейлы.

## Фикс (`scheduler.js`)
Device-health гейт в `launchTask`: перед спавном publish — `adb devices -l`; если целевой serial в state `unauthorized`/`offline` → **не спавним**, задача остаётся `pending` (запуск при восстановлении устройства). probe-fail (adb-сервер недоступен) НЕ гасит — отдаём `publisher.py` preflight. In-memory cooldown 5 мин (не пробить/не переотбирать мёртвый девайс каждый тик). Kill-switch `SCHEDULER_DEVICE_HEALTH_GATE_ENABLED` (default ON; `=false` → legacy).

Чистые хелперы `parseAdbDeviceState` / `shouldSkipUnhealthyDevice` / `deviceHealthCooldownActive`. **11 node:test зелёных, codex 0 P1.**

## Деплой + верификация
`scheduler.js` крутится ВНУТРИ `server.js` (pm2 #35) → деплой = рестарт главного сервера (0 in-flight публикаций на момент рестарта). Проверено вживую: после рестарта здоровая публикация (task 12788, IG, RFGYA19DBAX) прошла через `launchTask` нормально, 0 ошибок → гейт не сломал нормальный диспатч. Откат: `SCHEDULER_DEVICE_HEALTH_GATE_ENABLED=false`.

## Остаток
1. **WP#99** — физ.re-auth RF8YA0V7LEH (без него устройство не публикует; гейт лишь останавливает трату/фейлы). На устройство 36 будущих слотов (01–11.06) — будут чисто пропускаться гейтом до re-auth.
2. **codex P2 (известный остаток):** скипнутые задачи остаются в candidate-window планировщика (`LIMIT 50 ORDER BY id ASC`) — при накоплении многих мёртвых pending могут теснить здоровые. Полное лечение = DB-level backoff в наполнителе (`server.js`) → follow-up (не трогал свежеизменённый диспатч WP#183/#186). На практике наполнитель материализует `publish_tasks` по слоту (немного одновременно).
