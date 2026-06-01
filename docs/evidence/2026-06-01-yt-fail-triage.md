# YT-триаж упавших задач за 2026-06-01

## Что смотрели
Все `publish_tasks` где `platform='YouTube'`, `status='failed'`, `created_at >= 2026-06-01 00:00`.
Источник: openclaw Postgres (Docker-контейнер), таблица `publish_tasks` (events JSONB, log, error_code, error_class).
Скринкастов нет: у всех доминантных задач `screen_record_url IS NULL` (запись скипнута, см. ниже — устройство недостижимо ещё на preflight, записывать нечего).

## Объём
| status | count |
|---|---|
| failed | 207 |
| done | 53 |
| published_no_url | 3 |
| running | 1 |

YT success-rate сегодня ≈ 53/(53+207) ≈ 20%.

## Разбивка failed по error_code
| error_code | count | error_class |
|---|---|---|
| switch_failed_unspecified | 114 | unknown |
| channel_deleted | 78 | banned |
| process_interrupted | 4 | (null) |
| yt_picker_target_absent | 3 | ui_changed |
| yt_app_not_foregrounded | 2 | ui_changed |
| yt_picker_dismissed | 1 | ui_changed |
| yt_target_not_in_picker_after_scroll | 1 | ui_changed |
| critical_exception | 1 | (null) |
| yt_editor_not_reached | 1 | ui_changed |
| yt_editor_upload_timeout | 1 | ui_changed |
| yt_foreign_foreground_unrecoverable | 1 | ui_changed |

## Ключевая находка №1 — мисклассификация (доминанта, 55%)
**113 из 114** `switch_failed_unspecified` в логе содержат `adb_devices_unreachable` на ADB-preflight
(1 — `adb_device_not_ready`). То есть «свитчер не сработал» — фантом: реальная причина в том,
что устройство было НЕДОСТИЖИМО ещё до старта флоу.

Пример (task 13469, @wellroompro):
```
[10:23:15] Старт публикации: YouTube short
[10:23:15] ADB preflight: adb_devices_unreachable
events: error "ADB preflight failed: adb_devices_unreachable"
  meta.stderr: failed to connect to '147.45.251.85:15098': Connection refused
              * cannot start server on remote host
```

### Инфра-факт (объём): один хост, узкое окно
- Все 113 — с **одного adb_host `147.45.251.85`** (за ним все 36 устройств).
- Таймлайн: 08:00→9, **09:00→97**, 10:00→7, после 10:00 — ноль.
- «Connection refused» (не timeout) = ADB-релей/порт-форвард на хосте был мёртв ~2 часа,
  утащив все 36 устройств за собой. Уже самовосстановился.
- → Это инцидент инфраструктуры (ops/мониторинг релея), не код-баг сам по себе.

### Код-баг (фикс): порядок событий → неверный error_code
`publisher_base.py`:
```
4307  self.update_status('failed', f'ADB preflight: {category}')   # ← здесь срабатывает _set_error_code_from_events()
4308  self.log_event('error', f'ADB preflight failed: {category}', meta=adb_err)  # ← error-событие пишется ПОСЛЕ
```
`update_status('failed')` (L1840-1842) синхронно вызывает `_set_error_code_from_events()`.
На этот момент error-событие с `meta.category=adb_devices_unreachable` ещё НЕ записано (оно на L4308).
- Pass 1 маппера: нет error-события с category → пусто.
- Pass 2: ищет только `fail`-события свитчера (фикс от 2026-05-12, task 5048) → пусто.
- Фоллбэк: `error_code = 'switch_failed_unspecified'` → `error_class = unknown`.

Это ТА ЖЕ ошибка очерёдности, что чинили 2026-05-12 для TT-свитчера (Pass 2), но preflight-путь
её не покрывает (preflight эмитит `error`-событие, а не `fail`-событие свитчера).

Каталог `publish_error_codes` уже содержит `adb_devices_unreachable` (error_class=network, retry=manual),
т.е. при правильной очерёдности эти 113 классифицировались бы как `network`/`adb_devices_unreachable`,
а не маскировались под фантомный «свитчер».

**Предлагаемый фикс:** поменять местами L4307↔L4308 (сначала `log_event('error', ...)`, потом
`update_status('failed', ...)`) — тогда Pass 1 маппера увидит preflight-категорию.
Минимальный, низкорисковый, зеркалит интент фикса 2026-05-12.

⚠️ Побочный эффект для обсуждения: `adb_devices_unreachable` в каталоге = `retry_strategy=manual`.
Сейчас эти задачи ретраятся как `transient_within_limits` (backoff), т.к. коды-фантом=switch_failed
(backoff). Для транзиентного 2ч-оутэйджа авто-backoff корректнее manual — возможно стоит сменить
retry_strategy на backoff для adb_devices_unreachable, иначе после фикса 113 задач уйдут в ручную
очередь. Решить при реализации (вне scope самого баг-фикса классификации).

## Ключевая находка №2 — channel_deleted (78, banned) уже чинится
Забаненные каналы («Канал удалён»). Таймлайн за сегодня: 00:00→16, 01→16, 02→16, 03→15,
04→6, 05→2 … после — единицы. Резкий спад совпадает с деплоем заморозки **WP#200** (01.06).
→ Код-фикс не нужен; остаток — ops (пересоздать каналы, #201). Не выбираем для фикса.

## Прочие коды
Длиннохвост по 1–4 (process_interrupted, yt_picker_*, yt_editor_*). Известны/дормант, не приоритет.

## Вывод
Доминирующий **код-фиксируемый** баг = мисклассификация preflight-ошибок очерёдностью событий
(113 задач сегодня скрыты под `switch_failed_unspecified`/`unknown`). Это искажает триаж: топовый
bucket «свитчер сломан» — мираж, реальная причина = недостижимость ADB-хоста.
→ Заведён WP на фикс очерёдности.
