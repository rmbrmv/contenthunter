# WP#238 — ложный ig_camera_open_failed (Reels-камера открыта)

## RC (по событиям + UI-dump + скринкастам)
Задачи 15091/14125/13157 (clickpay_world, my_clickpay): happy-path bottomsheet
strict Reels-tile miss (`ig_create_tile_strict_miss`) → deeplink fallback
`am force-stop` + `am start instagram://reels-camera`. Камера РЕАЛЬНО открывается
(скринкаст: REELS-таб, кнопка съёмки, миниатюра галереи), но open_camera loop её
не распознаёт и через ~61с эмитит `ig_camera_open_failed` с `detected_state=unknown`,
`tried_full_reset=false`, `consecutive_state_count={}`.

Доказательство ложности: fail-артефакт `instagram_no_camera` (dump через ~2с после
цикла) содержит `text="REELS"`, `content-desc="Затвор"/"Галерея"`, resource-id
`cam_dest_clips`/`bottom_camera_capture_controls_container`. То есть `'REELS' in ui`
дал бы True — но в течение loop'а `dump_ui()` возвращал пустой/contentless dump
(uiautomator не сериализует свежую camera-surface после cold-start deeplink), бюджет
6 попыток исчерпался раньше, чем поверхность устаканилась. Watchdog open_camera=120с
не срабатывал (фейл на 61с).

## Фикс (kill-switch IG_CAMERA_OPEN_GRACE_RECHECK_ENABLED, default ON)
1. `_ig_camera_surface_ready(ui)` — распознаёт открытую camera/destination-picker
   поверхность по устойчивым resource-id (`cam_dest_clips`, `camera_destination_picker`,
   `bottom_camera_capture_controls`, ...) и точным токенам text/desc (REELS, ИСТОРИЯ,
   ПУБЛИКАЦИЯ, Затвор, Галерея, Добавить аудио, «Reels camera»). Attribute-scoped, не
   ловит reels-feed («Лента Reels»/`clips_tab_feed`).
2. `_ig_grace_recheck_camera()` — перед фейлом доп. settle (3×3с=9с, в пределах
   watchdog 120с) + повторный dump + проверка маркеров; при распознавании →
   `camera_ready=True` (событие `ig_camera_open_grace_recovered`).
3. Доп. сигнал в основном camera-ready чеке цикла (частичный рендер ловится раньше).

## Тесты
tests/test_ig_camera_surface_ready.py — 15 (12 маркеры + 3 grace-recovery/killswitch).
Код: delivery-contenthunter / publisher_instagram.py.

## Follow-up (не в этой итерации)
Тот же код `ig_camera_open_failed` маскирует 2 ops-RC: CAPTCHA «Подтвердите что вы
человек» (procontent_lab 14830/13989) и OS-диалог «Разрешить доступ к фото/видео»
(14938) — отделить в отдельные коды (account-challenge / permission-dialog dismiss).
