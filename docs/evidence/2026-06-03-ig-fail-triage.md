# IG publish-fail триаж — 2026-06-03

Источник: `publish_tasks` (openclaw, `72.56.107.157:5432`), `lower(platform)='instagram'`, `status='failed'`.
Окна: 7д / 3д / 1д (от 2026-06-03 06:56 UTC). Логи (`log`), классы (`error_class`), скринкасты (`screen_record_url`).

## Ранжирование падений (`status='failed'`)

| # | error_code | 7д | 3д | 1д | error_class | Реальная причина (логи/скринкасты) | Статус / покрытие |
|---|---|---|---|---|---|---|---|
| 1 | switch_failed_unspecified | 61 | 47 | 0 | unknown | ADB-preflight `adb_devices_unreachable`, до экрана не дошло | **Покрыто** WP#199/#207/#210 + инфра-SPOF |
| 2 | ig_share_tap_no_progress | 27+7 | 5 | 1 | ui_changed/unknown | false-negative Share | WP#181 Готово |
| 3 | ig_account_switcher_wrong_foreground | 26 | 5 | 0 | ui_changed | свитчер читал чужой fg | WP#197 Готово (0/1д) |
| 4 | process_interrupted | 24 | 4 | 1 | — | процесс убит извне (инфра) | — |
| 5 | ig_caption_screen_not_reached | 21+3 | 6 | 2 | ui_changed | интерстишалы редактора Reels | WP#193 Тестирование |
| 6 | ig_target_not_in_picker | 19 | 15 | 7 | ui_changed | **ops**: целевой аккаунт не залогинен на девайсе | ops (см. ниже) |
| 7 | adb_device_not_ready | 14 | 14 | 11 | device_unreachable | preflight device health | WP#210/#195, инфра |
| 8 | ig_editor_falsely_detected_as_gallery | 13+1 | 6 | 0 | ui_changed | редактор ложно=галерея | WP#206 шипнут 01.06 (0/1д) |
| 9 | **ig_picker_sheet_not_opened** | **6** | **6** | **3** | ui_changed | **sheet реально открыт/грузится, но детект ложно «не открылся»** | **НЕ покрыто → этот триаж (WP#225)** |
| 10 | ig_upload_confirmation_timeout | 5 | 3 | 1 | ui_changed | промо «Meta Verified» перекрыла флоу (гетерогенно) | НЕ покрыто (раннер-ап) |
| 11 | ig_camera_open_failed | 5 | 4 | 2 | ui_changed | камера не открывается, 1–3 ретрая | НЕ покрыто, малый объём |
| — | ig_app_not_foregrounded | 4 | 3 | 0 | ui_changed | — | длиннохвост |

## Главный вывод

- **Лидеры объёма** (`switch_failed_unspecified` 47/3д, `adb_device_not_ready` 14/3д) — **инфра ADB-preflight**, до экрана публикатора не доходит, уже покрыто WP#199/#207/#210. Исключены.
- **`ig_target_not_in_picker`** (15/3д) — крупнейший по объёму экранный код, но это **ops, не баг кода**: скринкаст task14622 (цель `Murat_Invest_Flow`) показывает открытый sheet, где залогинен только `techwearstyle_1`; целевого аккаунта на девайсе физически нет. 8 из 15 — один девайс RF8Y91F80TR/проект Мурат. Исключён из код-фикса.
- **Выбран для фикса — `ig_picker_sheet_not_opened`** (6/3д): №1 живой фикс-кандидат публикатора. Это остаточный хвост после WP#219 (тот закрыл только под-кейс «дрейф на аудио-страницу Reels»).

## Выбранный для фикса баг: `ig_picker_sheet_not_opened` → WP#225

**Симптом.** `FAIL: ... sheet выбора аккаунта не открылся (шаг=ig_4_pick_account_sheet_not_opened, попыток=1)` в случаях, когда sheet **реально открыт или ещё догружается**.

**Доказательства (пост-деплой WP#219, audio-escape НЕ срабатывал):**

- **task 14646** (ClickPay_152b, RFGYC31P26P, цель `clickpay_world`): скринкаст на момент фейла — **полностью открытый sheet** со списком `my_clickpay` (✓) + **`clickpay_world` (целевой, виден)** + «Добавьте аккаунт Instagram» / «Перейти в Центр аккаунтов». Лог: `ig_4_sheet_reguard_0` → `ig_2_profile_tab_overlay_escape_tap_phase` (сработал `_ig_on_inapp_overlay` → BACK выбил полу-открытый sheet) → `ig_4_sheet_reguard_1` → FAIL `попыток=1`.
- **task 14746** (Тестовый_171b, RF8Y90GCWWL, цель `born.trip90`): скринкаст — sheet **открывается, но завис на спиннере загрузки** (белый лист + синяя крутилка, аккаунты не отрисованы). 2 reguard-итерации не дождались прогрузки → `sheet_not_opened`.

**Корень (по коду `autowarm/account_switcher.py`):**

1. `_ig_guard_picker_foreground()` (≈2058): reguard-цикл `for attempt in range(2)`; re-чек `_ig_on_account_switcher_sheet` стоит **только в начале** каждой итерации → sheet, открывшийся после финального тапа (14646) или догрузившийся к концу, не перепроверяется (нет пост-тап / пост-цикл верификации).
2. `_ig_on_account_switcher_sheet()` (≈2786): опознаёт sheet по футер-текстам / `recycler_view_container_id`. На **загружающемся** sheet (спиннер, 14746) маркеры ещё не отрисованы → false-negative; нет маркера «контейнер sheet есть, но грузится» и нет ожидания прогрузки.
3. `_ig_on_inapp_overlay`-escape (≈2198) может сматчиться на переходном/полу-открытом sheet и сделать BACK → **закрыть реально открывающийся sheet** (14646).

**Направление фикса (TDD на этапе реализации):**
- Перепроверять sheet **после** каждого open-list тапа + финальная пост-цикловая проверка.
- Polling-ожидание прогрузки: виден контейнер sheet, но спиннер/нет строк → короткий wait-loop вместо немедленного «не открылся».
- Не запускать overlay/audio-escape (BACK), если в дампе уже есть маркер sheet-контейнера.
- Обязателен kill-switch (default ON).

**Связи.** Follow-up WP#219 (PR #143, родитель). Аналог TikTok — WP#96. Код = репо `delivery-contenthunter` (autowarm).

## Раннер-ап (отдельная задача, не этот фикс)

`ig_upload_confirmation_timeout` (3/3д) — промо «Meta Verified» перекрывает флоу; группа гетерогенна (часть = реальное зависание загрузки). Семейство интерстишал-дисмисса (WP#193/#206).
