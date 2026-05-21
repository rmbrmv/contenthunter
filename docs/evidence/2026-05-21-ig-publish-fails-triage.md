# Триаж упавших задач публикации — Instagram (2026-05-21)

Цель: собрать все упавшие IG-задачи, разобрать логи + скринкасты, ранжировать
ошибки по объёму, выбрать одну для фикса и завести WP.

## Методика

- Источник: `publish_tasks` (БД autowarm `openclaw@localhost`), `platform='Instagram'`,
  `status='failed'`.
- `error_code` в `publish_tasks` исторически врёт (пишет первую/preflight-ошибку,
  не финальную) — поэтому группировка по **финальной значимой категории** из
  `events[].meta.category` (последнее `type='error'` событие).
- **Исключён teardown-шум:** `screencast_pull_failed` / `screencast_stop_failed` —
  эти события срабатывают ПОСЛЕ реальной ошибки при попытке стянуть запись экрана
  (у таких задач `error_code` = реальная причина: `ig_target_not_in_picker`,
  `ig_share_tap_no_progress`, `date_mismatch` и т.п.). Без исключения они ложно
  всплывали в топ.
- **Исключено по указанию:** `switch_failed_unspecified` / `adb_devices_unreachable`
  (сетевой инцидент 2026-05-15, уже починен — даёт всплеск 160/172 фейлов на 05-15).
- **Исключён PM2-шум:** `process_interrupted` (deploy-kill, не баг).
- Кросс-чек: агрегация по `events` и по `error_code` дала практически идентичные
  числа — сигнал чистый.

## Ранжир ошибок (окно: последние 7 дней, 2026-05-14 … 2026-05-21)

| # | Категория | 7д | Статус / владелец |
|---|-----------|----|-------------------|
| 1 | `ig_share_tap_no_progress` | 26 | WP #73 (фикс ложно-негатива отгружен 2026-05-20). Найден остаточный подкейс — реальный «застрял в редакторе» (task 8764, 05-21) |
| 2 | **`ig_target_not_in_picker`** | **18** | только WP #102 (`[Бэклог] investigation`). **Выбран для фикса** |
| 3 | `ig_app_launch_failed` | 15 | WP #105 (В разработке, рецидив) |
| 4 | `ig_caption_fill_failed` | 12 | WP #81 (частичный фикс/defense) |
| 5 | `ig_caption_screen_not_reached` | 10 | нет WP, всплеск с 05-19 (8 из 10) |
| 6 | `ig_camera_open_failed` | 7 | — |
| 7 | `ig_picker_wrong_candidate` | 7 | — |
| 8 | `ig_upload_confirmation_timeout` | 5 | — |
| 9 | `date_mismatch` | 5 | — |
| — | `watchdog_subprocess_hang` | 4 | — |
| — | `ig_editor_timeout` / `adb_push_chunked_exception` / `ig_gallery_no_video_candidate` | 3 каждый | — |

(Для справки: за всё время лидируют уже пофикшенные/owned категории —
`ig_caption_fill_failed` 136, `ig_camera_open_failed` 95, `ig_editor_timeout` 86,
`ig_target_not_in_picker` 62, `ig_share_tap_no_progress` 50 и т.д. Всего 1284
упавших IG-задачи; 355 без значимой категории — преимущественно `error_code=NULL`,
не стартовавшие/skip, единым фиксящимся багом не являются.)

## Выбор для фикса: `ig_target_not_in_picker` (18/7д)

Почему он, а не #1:
- `ig_share_tap_no_progress` (26) уже имеет отгруженный фикс (WP #73); остаток —
  отдельный подкейс под follow-up к #73.
- `ig_target_not_in_picker` — крупнейший баг **без активной задачи на фикс**
  (есть только investigation-WP #102 в бэклоге, и моя разведка как раз его
  закрывает) и с **однозначно установленным код-корнем**.

### Корень (доказан): foreground-hijack на шаге выбора аккаунта

`ig_target_not_in_picker` — **вводящий в заблуждение** error_code. Реальная причина:
на шаге `ig_4_pick_account` на переднем плане оказывается **не Instagram**, а чужое
приложение/экран. Парсер списка аккаунтов (`_find_and_tap_account` →
`read_accounts_list`) слепо скребёт все text-узлы дампа, не проверяя пакет/экран,
получает мусор, не находит цель и рапортует «аккаунт не привязан к устройству».

Доказательства (3 разных чужих foreground подтверждены пакетом UI-dump):

| task | account | foreground на `ig_4_pick_account` | пакет | распарсенный список |
|------|---------|-----------------------------------|-------|---------------------|
| 8696 | clickpay_world | YouTube account-switcher | `com.google.android.youtube` | `['slava','clickpay','my_clickpay','wellroompro','12','world','google']` |
| 8657 | just_clickpay | TikTok промо «Привяжите почту» | `com.zhiliaoapp.musically` | `['знакомым.']` |
| 8623 | my_clickpay | домашний экран Samsung | `com.sec.android.app.launcher` | `['2.','23','гр.','permission','view','chrome','google','play']` |

- task 8696 дополнительно подтверждён скринкастом (`task8696_fail_screenrec`):
  на 165-й секунде кадр — bottom-sheet аккаунтов YouTube (таб-бар «Главная/Shorts/
  Подписки/Вы», «Параметры канала», «Управление аккаунтом Google»). Целевой
  `clickpay_world` показан как канал «clickpay world» (display-name с пробелом), и
  парсер раздробил его на `clickpay` + `world`; `'12'` ← «12 подписчиков»,
  `'google'` ← «Управление аккаунтом Google».
- **Все 18** задач за неделю имели срабатывание foreground-recovery (`fg_recovery=t`),
  у 2 явно залогирован `switcher_foreground_pkg_disagree`. Из 15 задач, где был
  залогирован распарсенный список, **все 15** содержат мусор (счётчики подписчиков,
  обрывки UI-текста «cохраненное»/«устройстве.»/«описание.», контент чужих
  приложений) — то есть парсился не IG-шит переключения аккаунтов.
- Размазано по множеству разных аккаунтов и устройств (RF8Y…, RFGYC…, RFGYA…) →
  системный код-баг, а не «один плохой аккаунт» / конфиг.

### Где в коде

`account_switcher.py::_switch_instagram` (prod `/root/.openclaw/workspace-genri/autowarm`):
- foreground-guard стоит только в начале — `_ensure_app_foregrounded('Instagram')`
  (`ig_0_foreground_guard`, ~строка 1570).
- далее навигация: `_go_to_profile_tab` → `_tap_profile_header` (`ig_3_open_list`) →
  `_find_and_tap_account(target, cfg, step='ig_4_pick_account')` (~строка 1683).
- **между guard'ом и парсингом списка повторной проверки foreground НЕТ.** Если за
  время навигации foreground уехал в YouTube/TikTok/лаунчер — `_find_and_tap_account`
  читает чужой экран и возвращает `False` → эмитится `ig_target_not_in_picker`
  (строки ~1685–1695).

Связь: тот же foreground-instability family, что и WP #105 (`ig_app_launch_failed` —
«dump видит launcher за секунду до того, как IG появляется»). Здесь — более поздняя
манифестация, когда ранний guard не удержал foreground.

### Направление фикса

Перед `_find_and_tap_account(... step='ig_4_pick_account')`:
1. Валидировать, что foreground-пакет = `com.instagram.android` **и** дамп — это
   реально шит переключения аккаунтов (по resource-id / известным маркерам), а не
   профиль/фид/чужое приложение.
2. Если foreground чужой — попытаться вернуть IG на передний план / повторить
   навигацию (переиспользовать `_ensure_app_foregrounded` / паттерн
   `_dismiss_foreign_foreground` как в YT WP #74).
3. При устойчивом неуспехе — фейлить с **точным** error_code (например
   `ig_account_switcher_wrong_foreground`), а НЕ с вводящим в заблуждение
   `ig_target_not_in_picker`.

Эффект: (а) часть кейсов восстановится (меньше фейлов), (б) остаток получит честный
error_code → корректный триаж и отсутствие ложного «аккаунт не привязан к устройству».

## Заведённая задача

**WP #119** (тип «Ошибка», статус «Бэклог», assignee Данил) — project content-hunter:
«IG: ig_target_not_in_picker — на шаге выбора аккаунта foreground уходит в чужое
приложение (YouTube/TikTok/лаунчер), парсер читает чужой экран (18 fails/7д)».

На investigation-WP #102 оставлен комментарий с выводом (это код, foreground-hijack)
и ссылкой на #119.
