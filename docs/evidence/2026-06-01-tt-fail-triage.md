# Триаж упавших TikTok-задач за 2026-06-01

Фокус: только платформа TikTok. Источник: `publish_tasks` (openclaw PG, localhost:5432),
`testbench=false`, `started_at >= 2026-06-01 00:00`.

## Сводка по статусам (сегодня, прод)

| platform  | failed | done | published_no_url | прочее |
|-----------|-------:|-----:|-----------------:|-------:|
| Instagram |     77 |    4 |               63 | 1      |
| **TikTok**|**150** |   41 |                6 | 1      |
| YouTube   |    207 |   53 |                3 | 1      |

## TikTok failed (150) — разбивка по error_code

| # | error_code                            | class      | count | реальная причина |
|---|---------------------------------------|------------|------:|------------------|
| 1 | `switch_failed_unspecified`           | unknown    | **83**| **НЕ TikTok-баг** — 81/83 = `adb_devices_unreachable`, 2 = `adb_device_not_ready` (см. ниже) |
| 2 | `tt_upload_confirmation_timeout`      | ui_changed |    18 | «Опубликовать» перекрыта хэштег-панелью → WP#203 iter4 (PR#136, уже задеплоен, в верификации) |
| 3 | `tt_inapp_upload_unreached`           | ui_changed |    14 | до редактора не дошли |
| 4 | `process_interrupted`                 | (null)     |     8 | прерывание процесса |
| 5 | `tt_fg_lost`                          | ui_changed |     4 | |
| 5 | `tt_account_not_in_list`              | ui_changed |     4 | |
| 7 | `phone_or_email_link_required`        | banned     |     3 | аккаунт-блок |
| 7 | `tt_caption_field_not_focused`        | ui_changed |     3 | |
| 7 | `tt_profile_tab_broken`               | ui_changed |     3 | |
| - | прочее (tt_post_switch_verify / tt_app_not_foregrounded / tt_audio_dialog_stuck / tt_storyservice_fg_stuck / tt_account_switcher_wrong_foreground / rc_nonzero / tt_open_list_probe_stale_ui / null) | разн. | по 1–2 | длиннохвост |

## Главный драйвер: один мёртвый ADB-шлюз (инфра + баг классификации)

Разворот первого error-event у всех 83 `switch_failed_unspecified`:

| underlying category      | count |
|--------------------------|------:|
| `adb_devices_unreachable`|    81 |
| `adb_device_not_ready`   |     2 |

Все 81 — на **одном хосте `147.45.251.85`** (29 задействованных девайсов сегодня),
stderr = «Connection refused». Этот хост — **единственный ADB-шлюз всего флота**
(7 дней: 94 девайса, 3641 задача). Единая точка отказа.

Затронуты ВСЕ платформы (фейлы на хосте 147.45.251.85 за сегодня):
**YouTube 113 + TikTok 81 + Instagram 43 = 237 задач**.

Динамика (час МСК): 08:00 → 12, **09:00 → 207**, 10:00 → 18, далее 0
(гейт WP#195 / частичное восстановление шлюза). Живой `adb connect` к одному из
портов на этом хосте на момент триажа всё ещё «failed to connect» (длиннохвост на
отдельных девайсах), но основная масса задач после 10:00 пошла успешно.

Скринкастов у этого бакета НЕТ (`has_rec=false`) — фейл на ADB-preflight, до старта записи.

## Root cause бага классификации (код-фиксабельно)

`publisher_base.py:4303-4308` (ветка adb preflight):

```python
self.set_step('adb preflight')
adb_ok, adb_err = self._preflight_adb_device()
if not adb_ok:
    category = adb_err.get('category')
    self.update_status('failed', f'ADB preflight: {category}')      # ← дёргает _set_error_code_from_events СЕЙЧАС
    self.log_event('error', f'ADB preflight failed: {category}', meta=adb_err)  # ← error-event пишется ПОСЛЕ
```

`update_status('failed')` триггерит `_set_error_code_from_events()`
(`publisher_base.py:2134`). Его **Pass 1** предпочёл бы `meta.category`
первого `error`-event (= `adb_devices_unreachable`) — но на этот момент error-event
ещё НЕ записан в `events`. Fail-event с маппируемым switcher-step тоже нет
(preflight до свитчера) → срабатывает дефолт:

```python
if not error_code:
    error_code = 'switch_failed_unspecified'
```

Дальше реальный error-event с `adb_devices_unreachable` дописывается строкой ниже,
но `_set_error_code_from_events` идемпотентен (`UPDATE ... WHERE error_code IS NULL`) —
код уже залочен в `switch_failed_unspecified` / class `unknown`.

Это **та же ordering-гонка**, что чинили 2026-05-12 для switcher-step (см. комментарий
Pass 2 в `_set_error_code_from_events`), но на ADB-preflight пути. Касается всех трёх
категорий: `adb_devices_unreachable`, `adb_device_offline`, `adb_device_not_ready`.

### Последствия
1. **Маскировка**: 237 фейлов/день по флоту от одного мёртвого шлюза прячутся в
   бакете `unknown` — оператор по error_code не видит, что это инфра/прокси.
2. **Вредный авто-requeue**: `switch_failed_unspecified`/unknown классифицируется как
   `transient_within_limits` → задача авто-перезапускается против заведомо мёртвого
   хоста (в task 13454 виден retry в 13:03, спустя ~3ч).

### Минимальный фикс
Поменять местами строки 4307↔4308: логировать `error`-event с `meta.category`
ДО `update_status('failed')` — тогда Pass 1 маппера честно проставит
`adb_devices_unreachable` (код уже зарегистрирован в каталоге как `infra`/transient
по своим правилам). Зеркало фикса 2026-05-12.

Опционально (вне минимального фикса, отдельная итерация): host-level circuit-breaker /
расширение device-health-gate WP#195 на «Connection refused к шлюзу», чтобы один
мёртвый шлюз не генерил массовый авто-requeue.

## Скринкаст-проверка genuine TT-UI бакета (tt_upload_confirmation_timeout, 18)

Задача 13534 (12:36–12:56), кадры из screenrec:
caption введён (focus подтверждён, story-derail escape отработал), открыта хэштег-панель
(«# Хэштеги / @ Упомянуть / #енотиграет 70 публикаций»), кнопка «Опубликовать» вытеснена
за экран. Лог: `ai_find_tap_no_coords` (null) → fallback-тапы (816,2130)/(808,2109)/(825,2145)
бьют по клавиатуре «ADB Keyboard {ON}» → upload-confirm timeout. Это ровно root cause
**WP#203 iter4** (PR#136, задеплоен 01.06, в верификации) — отдельный WP не нужен.

## Вывод
- Крупнейший драйвер TT-фейлов сегодня (83/150) — НЕ баг TikTok-флоу, а отказ единственного
  ADB-шлюза `147.45.251.85`, маскированный багом классификации в `switch_failed_unspecified`.
- К фиксу выбран **баг классификации/requeue ADB-preflight** (см. WP) — код-фиксабелен,
  максимальный масштаб (237/день по флоту), комплементарен WP#195/#140.
- Genuine TT-UI бакет №2 (`tt_upload_confirmation_timeout`) уже закрыт WP#203 iter4.

## Статус (обновлено 01.06)
- **WP#207 (TT) + WP#208 (YT)** — ФИКС реализован в `publisher_base.py` (helper
  `_fail_with_preflight_error`: `log_event('error')` до `update_status('failed')`),
  PR GenGo2/delivery-contenthunter **#138 СМЕРЖЕН в main `5a745ac`** и **задеплоен на прод**
  (`/root/.openclaw/workspace-genri/autowarm` HEAD=`5a745ac`, helper подтверждён; PM2-restart
  не нужен — `publisher.py` спавнится per-task). Тесты `tests/test_preflight_error_code_ordering.py`
  зелёные; `codex review` — чисто, 0 замечаний. Обе WP → «Тестирование», live-verify по факту
  следующего отказа шлюза.
- Поведение ретрая не меняется: `network` (=`adb_devices_unreachable`) уже в TRANSIENT
  рядом с `unknown` → меняется только наблюдаемость.
- **WP#210** — retry-churn per device (IG-угол), В разработке.
- **WP#211** — инфра-резилентность шлюза `147.45.251.85` (SPOF: мониторинг + host-level
  circuit-breaker), Бэклог.
