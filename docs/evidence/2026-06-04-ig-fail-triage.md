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

## RC доминирующих 3/6 (уточнён по publish_tasks.events + UI-dump)
Не детектор `_verify_reels_camera_mode`, а **ненадёжность UI-dump на camera-surface**: после промаха strict-плитки Reels (`ig_create_tile_strict_miss`) → deeplink fallback `instagram://reels-camera` камера РЕАЛЬНО открывается, но `dump_ui()` на свежей camera-surface после cold-start возвращает пустой/contentless dump → петля open_camera её не видит и через ~61с эмитит `ig_camera_open_failed` (`detected_state=unknown`, `tried_full_reset=false`, `consecutive_state_count={}`). Fail-артефакт `instagram_no_camera` (dump через ~2с) уже содержит `text=REELS`/`content-desc=Затвор,Галерея`/`resource-id=cam_dest_clips` — доказательство ложности. Watchdog open_camera = `STEP_TIMEOUT_DEFAULT` 120с (паттерны не матчат «open_camera»), на 61с не срабатывал.

## Реализация → SHIPPED+DEPLOYED 04.06 (PR #159, OP#238→Тестирование)
Kill-switch `IG_CAMERA_OPEN_GRACE_RECHECK_ENABLED` (default ON):
1. `_ig_camera_surface_ready(ui)` — устойчивые resource-id (`cam_dest_clips`, `camera_destination_picker`, `bottom_camera_capture_controls`, ...) + точные токены text/desc (REELS/ИСТОРИЯ/ПУБЛИКАЦИЯ/Затвор/Галерея/Добавить аудио/«Reels camera»); attribute-scoped, не ловит reels-feed (`clips_tab_feed`).
2. `_ig_grace_recheck_camera()` — перед фейлом доп. settle 3×3с=9с + переснять dump → `camera_ready=True` (событие `ig_camera_open_grace_recovered`).
3. Доп. сигнал в основном camera-ready чеке цикла.

TDD: `tests/test_ig_camera_surface_ready.py` 15 тестов; целевая регрессия IG/caption/gallery 380 passed. Код: delivery-contenthunter `publisher_instagram.py` (main `e5a651d`, прод autowarm ff-pull, PM2-restart не нужен — publisher per-task spawn). Подробности: `2026-06-04-wp238-ig-camera-open-false.md`.

## Follow-up (Бэклог)
Отделить от `ig_camera_open_failed` две ops-RC, которые сейчас под него маскируются: CAPTCHA «Подтвердите, что вы человек» (procontent_lab 14830/13989 → account-challenge) и OS-диалог «Разрешить доступ к фото/видео» (14938 → permission-dismiss).
