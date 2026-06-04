# IG fail-триаж 2026-06-04

Источник: прод host-PG `openclaw` (`publish_tasks`, status=failed, platform=Instagram), окно 7 дней.
Логи — колонка `log`; скринкасты — `screen_record_url` (save.gengo.io).

## Распределение error_code (7д)
| error_code | шт | вывод |
|---|---|---|
| switch_failed_unspecified | 58 | ops/инфра: outage ADB-шлюза 147.45.251.85 (40/43 в час 01.06 09:00), лог `adb_devices_unreachable`. Мислейбл error_class=unknown (не device_unreachable) |
| ig_account_switcher_wrong_foreground | 20 | WP#197 iter2; в последние 3д = 0 |
| adb_device_not_ready | 18 | ops/device-health (#195) |
| ig_caption_screen_not_reached | 16 | WP#193 |
| ig_target_not_in_picker | 15 | ops: 9/15 на Murat_Invest_Flow/Top (не залогинены) |
| ig_share_tap_no_progress | 11 | размазан |
| ig_editor_falsely_detected_as_gallery | 10 | WP#206 |
| ig_picker_sheet_not_opened | 8 | WP#225 (деплой 03.06, верифицируется) |
| ig_camera_open_failed | 6 | **ВЫБРАН → WP#238** |
| ig_upload_confirmation_timeout | 5 | хвост |

## ig_camera_open_failed (6/6 в последних 3 днях) — разбор скринкастов
| task | аккаунт | конечное состояние | категория |
|---|---|---|---|
| 15091 | clickpay_world | Reels-камера ОТКРЫТА (REELS-таб, shutter, галерея) | **КОД** false-negative |
| 14125 | my_clickpay | Reels-камера ОТКРЫТА | **КОД** false-negative |
| 13157 | my_clickpay | Reels-камера ОТКРЫТА | **КОД** false-negative |
| 14938 | ivana.world.class | пикер + OS-диалог «Разрешить доступ к фото/видео» | необработанный оверлей |
| 14830 | procontent_lab | CAPTCHA «Подтвердите, что вы человек» | ops/блок |
| 13989 | procontent_lab | CAPTCHA | ops/блок |

## RC доминирующих 3/6
`_verify_reels_camera_mode` (publisher_instagram.py:1160) подтверждает Reels только по resource-id `clips_tab` или точному тексту `'REELS'`/`'Reels camera'`. На билде Reels-камеры с расширенной творческой панелью таб-бар отдаёт текст иначе → точное сравнение в set промахивается → `unknown` → ветка ig_wrong_camera_mode `continue` → петля open_camera исчерпывается → `ig_camera_open_failed` (publisher_instagram.py:2408).

## Направление фикса (WP#238)
1. Устойчивый позитивный маркер Reels-камеры: case-insensitive `reels` + сигнатуры открытой камеры (shutter/capture, flip_camera, музыка/эффекты), не только точный `'REELS'`/`clips_tab`.
2. Отделить captcha-challenge и OS-permission-диалог в отдельные коды, чтобы ops-шум не маскировал код-RC.
3. Kill-switch + TDD. Код: delivery-contenthunter / autowarm.
