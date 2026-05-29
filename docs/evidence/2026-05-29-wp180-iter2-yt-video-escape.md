# WP#180 iter2 — YouTube profile video-player escape (SHIPPED+DEPLOYED 2026-05-29)

## Контекст

WP#180 (stale-uiautomator guard на YT-профиле) был выложен 28.05 и переведён в
«Тестирование». Суточная проверка 29.05 показала **рецидив** `yt_accounts_btn_missing_postmortem`:
18 фейлов за ночь 28→29.05, **все на одном канале** `estate-z5i` / телефон
`RFGYB180RZV`, авто-ретраями с интервалом ~20 мин.

## Root cause (разбор по реальным дампам — НЕ stale-UI)

Гард `_yt_stale_ui_check_and_recover` ни разу не сработал post-deploy — и
корректно. Дампы рецидивов **полностью читаемы** (30-40 КБ, `usable=True`), это
не stale-сигнатура (4936 байт), которую чинил оригинальный WP#180.

Траектория (task 11866):

| шаг | состояние |
|---|---|
| `yt_2_profile_tab` | **профиль ОК**, кнопка «Аккаунты» присутствует `[34,107][386,220]` |
| `overlay_dismissed button='закрыть'` | дисмисс оверлея |
| `yt_2_profile_screen` … `yt_3_open_accounts_postmortem` | **играет видео** (Видеопроигрыватель, 13:39→16:25 / 18:15, «Автор: Oleg Shevelev») |

Все рецидивы (11858/11862/11848/11866 …) на чекпоинте `yt_3_pre_tap` — на
watch-странице YouTube. Маркеры: `resource-id=com.google.android.youtube:id/watch_player`,
`content-desc="Видеопроигрыватель"`, `watch_panel`, `related_chip_cloud`. На
здоровом профиле этих маркеров нет.

**Вывод:** на канале `estate-z5i` после открытия профиля автозапускается его
featured-видео (трейлер канала, ~18:15) и перекрывает bottom-nav + кнопку
«Аккаунты». `_yt_try_accounts_btn_with_retries` жёг retap'ы + alt-avatar +
Settings-Activity впустую → ложный `yt_accounts_btn_missing_postmortem`. Это
account-specific остаток, не покрытый stale-гипотезой WP#180.

## Фикс

Зеркало проверенного `_yt_escape_shorts` / `_yt_escape_search`:

- `_YT_VIDEO_PLAYER_MARKERS` + `_yt_is_in_video_player(xml)` — детект watch-страницы.
- `_yt_escape_video_player(max_iter=3)` — до 3 back-тапов до выхода на профиль/feed.
- Интеграция в probe-loop `_switch_youtube` (yt_2): при обнаружении плеера —
  escape + повторное открытие профиля, затем перечитываем экран.
- Kill-switch `YT_PROFILE_VIDEO_PLAYER_ESCAPE_ENABLED` (default ON).

Новые события для наблюдаемости: `yt_profile_video_player_detected`,
`yt_profile_video_player_escaped`.

## Качество

- 12 новых unit-тестов (`tests/test_account_switcher_yt_profile_video_escape.py`) — GREEN.
- 0 регрессий (144 passed в соседних YT/switcher-наборах; единственный фейл
  `test_switcher_read_only::test_yt_happy_path` — pre-existing на main, read-only путь).
- codex review — 0 findings.

## Деплой

- PR `GenGo2/delivery-contenthunter#124` squash-merged → main `4642df2`.
- **Находка:** прод-чекаут `/root/.openclaw/workspace-genri/autowarm` отставал на
  `efd0264` (28.05 13:57) — на 3 фичи: `f8ca9e8` (#182 Phase 2), WP#44 TT caption
  focus-gate (+миграция), и этот #180 iter2. Тикеты #182/#44 «SHIPPED+DEPLOYED»
  фактически в прод не доехали (прод не тянет из GitHub автоматически).
- Деплой: `git -C <prod> merge --ff-only origin/main` → `4642df2`; применена
  миграция `20260529_wp44_tt_caption_field_not_focused.sql` (идемпотентный INSERT
  в `publish_error_codes`). server.js не менялся → PM2-restart не нужен (Python
  спавнится per-task).

## Verify

Утренняя пачка 29-30.05: по `estate-z5i` ожидаем `yt_profile_video_player_detected`/
`_escaped` события и спад `yt_accounts_btn_missing_postmortem`. Rollback:
`YT_PROFILE_VIDEO_PLAYER_ESCAPE_ENABLED=0`.

## Остаток / follow-up

- Деплой-разрыв прод↔main (несколько «выложенных» правок не были в проде) —
  отдельная инфра-задача: восстановить надёжный pull прод-чекаута после мерджа в main.
- Если автоплей featured-видео встретится на других каналах — fix общий (не
  привязан к estate-z5i), покроет автоматически.
