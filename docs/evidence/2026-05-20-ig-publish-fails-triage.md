# IG publish-fails triage — 2026-05-20

Дата сбора: 2026-05-20 17:0x UTC.
Источник: `publish_tasks WHERE platform='Instagram' AND testbench=false AND status='failed'`.
Окно анализа: `created_at >= '2026-05-14'` (предыдущий триаж покрыл по 2026-05-13; всплеск 2026-05-15 = сетевая adb-проблема, исключена по указанию).

## Зачем окно, а не «всё время»

Всего `failed` по Instagram за всё время — 1051. Это включает давно закрытые баги. Цель — найти топ-причину *текущих* падений, поэтому смотрю свежее окно 2026-05-14…2026-05-20 (предыдущие триажи довели разбор до 13 мая).

## Исключения

- **`switch_failed_unspecified` (164 за окно)** — по указанию пользователя НЕ учитываем. Перепроверено: 100% этих кейсов = `adb_devices_unreachable` (160) / `adb_device_not_ready` (4), т.е. сетевая/девайс-проблема, уже починена. Всплеск 2026-05-15 (172 фейла за день) — это они.
- **`process_interrupted` (6)** — PM2 deploy-kill, не баг (по памяти исключается из fail-rate).

## Распределение причин (после исключений)

Группировка по `publish_tasks.error_code`, перепроверено по последнему `events[].meta.category` (post-fail артефакты `screencast_pull_failed`/`screencast_stop_failed` свёрнуты обратно в их `error_code`).

| # | error_code | падений | скринкастов | аккаунтов | устройств | статус |
|---|---|---|---|---|---|---|
| 1 | **`ig_share_tap_no_progress`** | **24** | 16 | 13 | 12 | WP #73 (Бэклог) — **выбран для фикса** |
| 2 | `ig_target_not_in_picker` | 18 | 16 | 13 | 11 | бэклог-кандидат |
| 3 | `ig_app_launch_failed` | 14 | 10 | 13 | 13 | WP #105 (В разработке, рецидив) |
| 4 | `ig_caption_fill_failed` | 11 | 11 | 10 | 9 | WP #81 (защита отгружена PR #67) |
| 5 | `ig_caption_screen_not_reached` | 8 | 7 | 6 | 6 | — |
| 6 | `ig_camera_open_failed` | 6 | 6 | 4 | 3 | — |
| 7 | `date_mismatch` (picker_wrong) | 5 | 3 | 5 | 5 | — |
| 8 | `watchdog_subprocess_hang` | 4 | 0 | 4 | 4 | инфра |
| 9 | `adb_push_chunked_exception` | 3 | 0 | 3 | 3 | инфра/сеть |
| 10 | `ig_app_not_foregrounded` | 3 | 3 | 3 | 3 | — |
| 11 | `ig_editor_timeout` | 3 | 3 | 3 | 3 | — |
| 12 | `ig_gallery_no_video_candidate` | 3 | 3 | 3 | 3 | WP #68 territory |
| | прочее (≤2 каждое) | 12 | — | — | — | хвост |

**Топ-1 = `ig_share_tap_no_progress` (24, ~21% после исключений).** Размазан по 13 аккаунтам / 12 устройствам → код/UI-баг, не девайс/аккаунт.

## Deep-dive: `ig_share_tap_no_progress` — ложно-негатив

### Семидневная динамика (all-time)

| день | count |
|---|---|
| 2026-05-20 | 6 |
| 2026-05-19 | 5 |
| 2026-05-18 | 7 |
| 2026-05-16 | 1 |
| 2026-05-15 | 2 |
| 2026-05-14 | 3 |
| 2026-05-13 | 12 |
| 2026-05-12 | 18 |
| 2026-05-11 | 4 |

Устойчивый поток с 2026-05-09, пик 12-13 мая, стабильно 5-7/день сейчас. Не разовый всплеск.

### Что происходит (логи + скринкасты)

Флоу доходит до самого конца: камера → REELS → галерея → редактор → подпись заполнена и **верифицирована** → «Поделиться» нажата. Затем:

1. `wait_upload_iter0_diag`: `topResumedActivity = com.instagram.modal.ModalActivity`, `share_button` ещё в DOM (clickable).
2. `ig_pre_tier1_probe`: **в 16/18 свежих задач** `topResumedActivity = com.instagram.mainactivity.InstagramMainActivity` — приложение УЖЕ вышло из редактора-модалки в основную активность.
3. Tier-2 ladder (retry 1 → retry 2 → action_bar OK fallback) отрабатывает целиком и фейлит → `ig_share_tap_no_progress`.

### Доказательство публикации (скринкасты)

**task 8604** (`estate_m.ivanov` / RFGYB1EBANP) и **task 8602** (`expertestate1` / RFGYA19BT8N) — два разных аккаунта/устройства. На обоих скринкаст в момент «фейла» показывает **уже опубликованный Reel** в профильной ленте: заголовок «Reels / Друзья», подпись задачи, и кнопки **«Статистика» / «Продвигать»** — они появляются ТОЛЬКО на собственных опубликованных постах.

Вывод: **публикация прошла успешно, но детектор успеха её не распознал** → ложно-негативный `ig_share_tap_no_progress` (зеркало WP #82 для TikTok). Задача помечена failed, хотя контент в профиле.

Проверка 18/18 свежих задач: подпись верифицирована = да, «Поделиться» нажата = да, post-share активность = `InstagramMainActivity` (16/18) либо `ModalActivity` (2/18 — 7871, 7707, возможно реальный stuck).

### Корневая причина (код)

`publisher_instagram.py`:

- **L2891-2895** `SUCCESS_ACT_TOKENS` (pre-Tier1 probe, добавлен 2026-05-13):
  ```python
  SUCCESS_ACT_TOKENS = ('MainTabActivity', 'ReelViewerActivity', 'IgFeedActivity')
  ```
- **L3243** основной wait-loop:
  ```python
  if 'MainTabActivity' in act_check:  # «вернулись в ленту, публикация прошла»
  ```

Оба места ищут успех по `MainTabActivity`. Но текущий билд IG на устройствах репортит post-publish активность как **`com.instagram.mainactivity.InstagramMainActivity`** — подстрока `MainTabActivity` в неё НЕ входит. Значит:

- probe не выставляет `probe_skip_tier1` → запускается Tier 1 → ретапы «Поделиться» уже по ленте → fail;
- основной wait-loop тоже не ловит успех по активности.

IG переименовал главную активность (`MainTabActivity` → `mainactivity.InstagramMainActivity`), а детектор успеха остался на старом имени. WP #73 заметила симптом (`InstagramMainActivity` после iter0), но **ошибочно** трактовала его как «share-tap улетел в feed = провал, надо вернуться в editor». Скринкасты опровергают: это успех.

### Направление фикса (для реализации, не часть триажа)

Добавить `InstagramMainActivity` (и/или подстроку `MainActivity`) как success-токен в обоих местах (L2892 probe + L3243 wait-loop). С осторожностью: `InstagramMainActivity` — общая главная активность, поэтому success лучше подтверждать связкой «вышли из editor-модалки + не видим editor-маркеров (`_is_ig_editor_still_visible==False`)», а не только по имени активности, чтобы не словить ложно-позитив при аварийном выходе на home без публикации. Под kill-switch env-флагом.

## Артефакты

- UI dump task 8604: `https://save.gengo.io/autowarm/ui_dumps/instagram/task8604_publish_8604_wait_upload_iter0_1779261338.xml`
- Screencast 8604: `https://save.gengo.io/autowarm/screenrecords/instagram/task8604_fail_screenrec_8604_1779261054.mp4`
- Screencast 8602: `https://save.gengo.io/autowarm/screenrecords/instagram/task8602_fail_screenrec_8602_1779260917.mp4`
- Примеры задач: 8604, 8602, 8597, 8594, 8590, 8529 (2026-05-20); 6822, 6819, 6801, 6799, 6798, 6763 (2026-05-18).
