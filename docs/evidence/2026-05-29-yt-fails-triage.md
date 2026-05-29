# YT publish-fails triage — 2026-05-29

## Объём за сегодня (YouTube, created_at >= 2026-05-29 00:00 UTC)

| status | tasks |
|---|---|
| done | 52 |
| **failed** | **12** |
| awaiting_url | 1 |
| published_no_url | 1 |

Fail-rate ~12/66 ≈ 18% (без учёта awaiting/no_url).

## Разбор 12 упавших — по реальной последней `meta.category` (не по `error_code`, который пишет первую ошибку)

| category | tasks | уник. аккаунтов | уник. устройств |
|---|---|---|---|
| `yt_accounts_btn_missing` | **9** | 1 (`estate-z5i` / `RFGYB180RZV`) | 1 |
| `yt_editor_not_reached` | 3 | 3 (`SpbProperty1Guide`, `bodyrelieflab_1`, `estate-z5i`) | 3 |

## Группа A — `yt_accounts_btn_missing` (9 задач) → УЖЕ ИСПРАВЛЕНО СЕГОДНЯ

Все 9 — один канал `estate-z5i` на телефоне `RFGYB180RZV`, авто-ретраи каждые ~20 мин (00:08→02:48).

Корень (по дампам, `usable=true` — НЕ stale-UI): после открытия профиля автозапускается
featured-видео канала (трейлер ~18 мин) и оверлей **«Рекомендуемое видео»** + шторка
**«Описание»** перекрывают bottom-nav и кнопку «Аккаунты». Свитчер жжёт retap/alt-avatar/
Settings-Activity впустую → ложный `yt_accounts_btn_missing_postmortem`.

Скриншот `yt_3_pre_tap` (task 11858): экран видеоплеера, «Закрыть/Воспроизвести», «Описание»,
автор «Oleg Shevelev». `header_texts_seen`: «Видеопроигрыватель», «Рекомендуемое видео»,
«Воронка продаж…», «29:43».

**Статус: закрыт.** Это остаток WP#180, не покрытый stale-гипотезой. Фикс
`_yt_escape_video_player` (kill-switch `YT_PROFILE_VIDEO_PLAYER_ESCAPE_ENABLED`, default ON)
**SHIPPED+DEPLOYED 29.05** (main `4642df2`) — см. `2026-05-29-wp180-iter2-yt-video-escape.md`.
Сегодняшние 9 падений — ночные (00:08–02:48), ДО дневного деплоя iter2. Дубль не заводим;
verify под WP#180 («Тестирование»).

7-дневный контекст подтверждает доминанту и разделение корней:
- `yt_accounts_btn_missing` за 7д = **107 задач, 9 акк, 6 устройств** (топ-1 YT-фейл).
- из них `usable=false` (stale-UI, закрыт оригинальным WP#180): 84 задачи, 8 акк, дни 25–28.05.
- `usable=true` (video-player overlay, закрыт iter2): 22 задачи, 2 акк (`estate-z5i`, `clickpay_officia`), дни 27–29.05.

## Группа B — `yt_editor_not_reached` (3 задачи) → НЕИСПРАВЛЕНО, кандидат на новую задачу

Задачи 11953 / 11976 / 11983. В момент падения `top_activity` у всех трёх =
`com.sec.android.app.launcher/.activities.LauncherActivity` — устройство «уехало» на
домашний экран Samsung во время фазы редактора/публикации. `edit_fields_count=0`.

Прекурсоры: `yt_post_switch_handle_unknown` (2/3) + `yt_foreground_recovery`,
далее `yt_create_menu_absent_skip_tap` → `yt_editor_not_reached`. Скринкасты 11953/11976
заканчиваются на лаунчере (виджет погоды «Астана», «Включить»).

Гипотеза: после смены аккаунта / в начале публикации YouTube теряет foreground (падает на
launcher), а текущий foreground-recovery не восстанавливает приложение до фазы редактора →
honest `yt_editor_not_reached`, но без перезапуска YouTube. За сегодня 3 задачи на 3 разных
аккаунтах/устройствах (широкий, не account-specific). За 7д — 3 задачи, 3 акк.

Открытых WP по `yt_editor_not_reached` нет (проверено в OpenProject). → завести задачу.

## Источники
- БД `publish_tasks` (openclaw@localhost), events JSONB, postmortem-дампы `usable`.
- Скринкасты: `task11858/11953/11976_fail_screenrec_*.mp4` (save.gengo.io), кадры ffmpeg.
- Скриншоты свитчера: `task11858_publish_11858_switch_yt_3_pre_tap_*.png`.
