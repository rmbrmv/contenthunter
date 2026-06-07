# Phase 0 — Device online/battery status: разведка зависимости от схемы `factory`

Дата: 2026-06-07. Хост OLD `72.56.107.157`. Код delivery: `/root/.openclaw/workspace-genri/autowarm`.
БД CH: docker `openclaw-postgres` (db `openclaw`). READ-ONLY, ничего не менялось.

## TL;DR
Локальный свежий источник online/battery **уже существует и активно пишется** — таблица
`public.autowarm_device_metrics` (наполняется `collectDeviceMetrics()` в `server.js`, pm2 id35, каждые 5 мин,
прямым опросом малинок через ADB-шлюз `147.45.251.85`). Вью `public.device_state` (единственный public-объект,
завязанный на `factory`) читает мёртвую `factory.device_state` (последняя запись **2026-05-11 16:00:01**).
Отвязка тривиальна: **пересоздать вью `device_state` поверх `autowarm_device_metrics` + `factory_device_numbers` + `raspberry_port`**. Колонки полностью покрываются.

---

## 1. Текущая цепочка получения статуса

```
малинки (Samsung-телефоны)
   │  ADB через шлюз 147.45.251.85 (порт rp.adb, напр. 15037/15017/15028)
   │
   ├─[МЁРТВО]  scripts/device_monitor.py  (cron */10, НЕ запущен — нет ни cron, ни процесса)
   │              dumpsys battery → INSERT INTO factory.device_state
   │                    │
   │                    ▼
   │              factory.device_state  (протухла 2026-05-11, 174k строк)
   │                    │  LEFT JOIN factory.device_numbers
   │                    ▼
   │              public.device_state (VIEW)  ◄── читает server.js (см. ниже)
   │
   └─[ЖИВОЕ]  server.js collectDeviceMetrics() (pm2 id35, setInterval 5 мин)
                  dumpsys battery → INSERT INTO autowarm_device_metrics  (СВЕЖАЯ, now-19с)
```

**Вью `public.device_state`:**
```sql
SELECT ds.id, ds.device_id, ds.server, ds.online, ds.device_number,
       ds.crnt_date, ds.crnt_time, ds.battery_percent, ds.battery_temperature,
       ((ds.crnt_date||' ')||COALESCE(ds.crnt_time::text,'00:00:00'))::timestamp AS checked_at,
       dn.raspberry
FROM factory.device_state ds
LEFT JOIN factory.device_numbers dn ON dn.id = ds.device_number;
```

**Кто читает `device_state` в `server.js` и какие колонки:**
- `GET /api/devices` (стр. ~505-575) — LATERAL по `device_id`, берёт `online, battery_percent, battery_temperature, checked_at`. Online = `_dsOnline(ds.online)===true`; stale = age > `DEVICES_STALE_MINUTES` (env, дефолт **60**), но online по stale НЕ блокируется (только UI-значок).
- `GET /api/devices/factory` (стр. ~679-745) — те же 4 колонки через LATERAL.
- `GET /api/debug/devices-online` (стр. ~620-675) — `online, checked_at`.
- `GET /api/sla/devices` (стр. ~5294) — `DISTINCT ON (device_id)`: `device_id, device_number, raspberry, online, battery_percent, battery_temperature, checked_at`. (Uptime 24ч — отдельно из `autowarm_device_metrics` по `raspberry_number`.)
- `GET /api/sla/device/:serial/history` (стр. ~5348) — `online, battery_percent, battery_temperature, checked_at` по `device_id`.
- `GET /api/sla/stats` (стр. ~5370) — агрегаты `online, battery_percent, battery_temperature`.

Порог устаревания: `DEVICES_STALE_MINUTES = parseInt(process.env.DEVICES_STALE_MINUTES||'60',10)` (server.js:482).

`GET /api/dashboard/stats` (стр. ~1255) **уже** считает online из `autowarm_device_metrics` (не из device_state).

## 2. collectDeviceMetrics — что/как/куда

`server.js:3780`. Каждые 5 мин (`setInterval`, server.js:5404; первый прогон через 10с, :5403). Также по `POST /api/sla/collect`.
- Источник малинок: `getRaspberryPorts()` → `SELECT id, raspberry_number, adb, host, scr, port FROM raspberry_port`.
- Список устройств: `adb -H <host> -P <adb> devices` → реальные серийники (фильтр строк, заканчивающихся `\tdevice`).
- Метрики на устройство: `adb -H host -P adb -s serial shell "dumpsys battery | grep -E 'level|temperature'"`; temp = raw/10.0; status `online`/`offline`.
- Побочно: детект рассинхрона маппинга serial↔Pi + авто-синк `factory_device_numbers.raspberry` (после 3 подтверждений), если `autowarm_settings.auto_sync_device_mapping='true'`.
- Запись: `INSERT INTO autowarm_device_metrics (device_serial, raspberry_number, battery_level, temperature, status)`.

**Схема `autowarm_device_metrics`:**
| колонка | тип | примечание |
|---|---|---|
| id | int PK | |
| device_serial | text | **реальный серийник** (RF8Y...), НЕ IP:PORT |
| raspberry_number | int | |
| battery_level | int | % |
| temperature | double | °C |
| status | text | `online`/`offline` |
| checked_at | timestamp | default now(), **реальный момент опроса** |

Индекс: `(device_serial, checked_at DESC)`.
Свежесть: `max(checked_at)=2026-06-07 20:24:15` при `now()=20:24:34` (актуально). ~4.2М строк, активно пишется.
Покрытие: **169 из 181** active `factory_device_numbers` имеют запись за последние 30 мин (12 — Pi недоступна/неактив).

> ⚠️ Комментарий в `/api/sla/devices` («device_serial в metrics = IP:PORT») — **устаревший/неверный**: фактически там реальные серийники, JOIN по `device_id=device_serial` работает.

## 3. Можно ли переключить статус на локальный источник
**ДА.** `autowarm_device_metrics` содержит всё необходимое (device_serial, raspberry_number, battery_level, temperature, status, checked_at). Маппинг на колонки вью:

| device_state (вью) | источник из локальных таблиц |
|---|---|
| device_id | `adm.device_serial` |
| online | `adm.status='online'` |
| battery_percent | `adm.battery_level` |
| battery_temperature | `adm.temperature` |
| checked_at | `adm.checked_at` (лучше прежнего — реальный ts, не crnt_date+crnt_time) |
| raspberry | `adm.raspberry_number` (или `fdn.raspberry`) |
| device_number | `fdn.device_number` (JOIN `factory_device_numbers` по device_id) |
| server | `'Raspberry '||adm.raspberry_number` |
| id | `adm.id` |

Все потребители используют только эти поля → переключение прозрачно для `server.js` (правок кода не требуется, если сохранить имена колонок вью).

## 4. Прямой опрос малинок — есть ли уже
**Уже есть, и работает.** `collectDeviceMetrics()` (server.js) опрашивает малинки напрямую по ADB через шлюз `147.45.251.85` (`raspberry_port.host/adb`) — это и есть «тянуть статус с малинок». Дополнительно тот же подход в `scripts/device_monitor.py` (но он не запущен). Питоновые `sim_scanner.py`, `profile_inspector.py` тоже ходят на устройства через `adb -H host -P adb_port`.
Таблица малинок — `public.raspberry_port`: `id, raspberry_number, adb (ADB-порт), host (147.45.251.85), scr, port, synced_at`.
Маппинг устройство→малинка — `public.factory_device_numbers`: `id, device_number, active, device_id (серийник), raspberry, warmup_end_date, synced_at`.
Ничего нового опрашивать не нужно — источник статуса с малинок уже наполняет `autowarm_device_metrics`.

## 5. Кто пишет factory.device_state
Единственный писатель в кодовой базе CH — `scripts/device_monitor.py` (`INSERT INTO factory.device_state`, последний git-touch 2026-04-13 Genri). Он **не запущен** (нет cron `*/10`, нет процесса). Поскольку вью протухла 11.05, а device_monitor.py не работает, **исторически factory.device_state наполняла ВНЕШНЯЯ старая платформа** (та самая, что владеет схемой `factory` и удаляется); device_monitor.py был попыткой завести локальный писатель, но не активирован. Сейчас фактический живой эквивалент — `collectDeviceMetrics` (пишет в autowarm_device_metrics, не в factory).

## 6. Все public-объекты, зависящие от схемы `factory`
- Вью: **`public.device_state`** — единственный.
- Функции (`prokind='f'`): **нет**.
- Материализованные вью: **нет**.
- (Замечание: таблицы `public.factory_device_numbers`, `public.factory_pack_accounts`, `public.raspberry_port` — это ЛОКАЛЬНЫЕ таблицы в схеме `public` с префиксом имени `factory_`; к схеме `factory` отношения не имеют, синкаются (`synced_at`) и используются независимо.)

## 7. Рекомендованный план отвязки от factory
**Вариант A (рекомендуемый, минимальный, без правок server.js): пересоздать вью `device_state` поверх локальных таблиц.**

```sql
CREATE OR REPLACE VIEW public.device_state AS
SELECT adm.id,
       adm.device_serial                      AS device_id,
       'Raspberry '||adm.raspberry_number      AS server,
       (adm.status = 'online')                 AS online,
       fdn.device_number                        AS device_number,
       adm.checked_at::date                     AS crnt_date,
       adm.checked_at::time                     AS crnt_time,
       adm.battery_level                        AS battery_percent,
       adm.temperature                          AS battery_temperature,
       adm.checked_at                           AS checked_at,
       adm.raspberry_number                     AS raspberry
FROM public.autowarm_device_metrics adm
LEFT JOIN public.factory_device_numbers fdn ON fdn.device_id = adm.device_serial;
```
Потребители (`/api/devices`, `/api/sla/*`, `/api/debug/devices-online`) сами берут `DISTINCT ON (device_id) ... ORDER BY checked_at DESC` или LATERAL-последнюю строку → дубликаты истории не мешают. `battery_temperature` отдаётся как `::float` в кодe — double подходит.

Нужные таблицы/колонки: `autowarm_device_metrics(device_serial, raspberry_number, battery_level, temperature, status, checked_at)` + `factory_device_numbers(device_id, device_number)`. Все уже существуют и свежи.

Опционально: создать индекс под latest-выборку — частичный/обычный `(device_serial, checked_at DESC)` уже есть; для агрегатов SLA достаточно текущих.

**Вариант B (альтернатива): переписать 5 SQL-читателей в server.js напрямую на `autowarm_device_metrics`** (больше правок, без вью). Не нужен, т.к. A покрывает всё прозрачно.

**Сопутствующее (вне scope, отметить):**
- `scripts/device_monitor.py` — мёртвый писатель в factory; после отвязки удалить/архивировать (не запущен, безопасно).
- Опечатка-комментарий в `/api/sla/devices` про «device_serial=IP:PORT» — поправить при случае.
- 12/181 устройств без свежих метрик = Pi недоступны/неактивны; поведение «нет строки → stale/offline» сохраняется как в текущем вью (LEFT JOIN, NULL).

**Риск отвязки: низкий.** Единственная завязка на factory — один вью; локальный источник свежий и уже наполняется живым процессом pm2 id35.
