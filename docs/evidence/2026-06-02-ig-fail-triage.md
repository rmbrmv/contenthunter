# IG publish-fail триаж — 2026-06-02

Источник: `publish_tasks` (openclaw, `72.56.107.157:5432`), `lower(platform)='instagram'`, `status='failed'`.
Окна: 7 дней / 3 дня / 1 день (от 2026-06-02 09:31 UTC). Логи (`log`), классы (`error_class`), скринкасты (`screen_record_url`).

## Ранжирование падений (`status='failed'`)

| # | error_code | 7д | 3д | 1д | error_class | Реальная причина (логи/скринкасты) | Статус / покрытие |
|---|---|---|---|---|---|---|---|
| 1 | watchdog_subprocess_hang | 476 | 1 | 1 | — | Инфра-хэнг (инцидент 27.05) | WP#165, мёртв |
| 2 | ig_share_tap_no_progress | 86 | 4 | 2 | ui_changed | false-negative Share | WP#181 Готово |
| 3 | **switch_failed_unspecified** | 67 | 58 | 29 | unknown | ADB-preflight `adb_devices_unreachable` (всплеск 01.06 ~09:50–10:02 на общем шлюзе), 0 скринкастов — до экрана не дошло; 58 попыток = 21 уник. намерение (retry-churn) | **Покрыто** WP#199/#207 (labeling) + WP#210 (retry-throttle) + инфра-SPOF шлюз 147.45.251.85 |
| 4 | ig_account_switcher_wrong_foreground | 57 | 15 | **0** | ui_changed | свитчер читал чужой fg | **WP#197** шипнут 01.06 → упал в 0/1д |
| 5 | ig_caption_screen_not_reached | 31 | 5 | 1 | ui_changed | интерстишалы редактора Reels | WP#193 Тестирование |
| 6 | process_interrupted | 25 | 13 | 0 | — | процесс убит извне (инфра) | — |
| 7 | ig_target_not_in_picker | 23 | 9 | 4 | ui_changed | аккаунт не залогинен на девайсе (длинный хвост) | ops (WP#102/#119) |
| 8 | ig_editor_falsely_detected_as_gallery | 16 | 6 | 1 | ui_changed | редактор ложно=галерея | WP#206 шипнут 01.06 |
| 9 | **ig_picker_sheet_not_opened** | — | **4** | **4** | ui_changed | **sheet выбора аккаунта не открывается после тапа по имени аккаунта; `попыток=1`, без ретрая** | **НЕ покрыто → этот триаж** |
| 10 | ig_upload_confirmation_timeout | 7 | 5 | 3 | ui_changed | ≥1 случай = промо-модалка «Meta Verified» перекрыла флоу (не зависший спиннер); группа гетерогенна | НЕ покрыто (раннер-ап) |
| 11 | ig_camera_open_failed | 5 | 3 | 2 | ui_changed | камера не открывается, 1–3 ретрая open_camera → fail | НЕ покрыто, малый объём |
| — | adb_device_not_ready | 3 | 3 | 3 | device_unreachable | preflight device health | WP#210/#195 |

## Главный вывод

- **Абсолютный лидер объёма** — `switch_failed_unspecified` (58/3д), но это **не баг публикатора**: ADB-preflight `adb_devices_unreachable` на общем шлюзе 147.45.251.85 (всплеск 01.06 утром), до экрана дело не доходит (0 скринкастов), уже покрыт WP#199/#207 (метка) + WP#210 (retry-throttle) + инфра-SPOF. Исключён из выбора на фикс.
- **Лидер живых экранных падений публикатора за 24ч** = **`ig_picker_sheet_not_opened`** (4/4 за сутки). Это honest-остаток после WP#197: тот починил ложную метку `wrong_foreground`, но не само «sheet не открылся».

## Выбранный для фикса баг: `ig_picker_sheet_not_opened`

**Симптом.** На профиле тапается имя текущего аккаунта (нужно переключиться на целевой) → bottom-sheet выбора аккаунта НЕ открывается → `FAIL: ... sheet выбора аккаунта не открылся (шаг=ig_4_pick_account_sheet_not_opened, попыток=1)` → `Публикация не прошла`.

**Объём.** 4 фейла за 3д (все 4 — за последние 24ч), на **4 разных девайсах / 4 проектах / 4 аккаунтах** → системное поведение публикатора, не привязка к одному девайсу. Код появился 01.06 (honest-метка WP#197).

**Доказательство (скринкаст task14098, `easy.septic.care`, дев RFGYA19BGWT):**
- t=20с — лаунчер (IG запускается).
- t=150с — **профиль аккаунта `relisssme`** (Relisme Wear) с дропдауном имени `relisssme ▼`. Целевой аккаунт задачи — `easy.septic.care` (другой) → нужен свитч через тап по имени.
- t=285–300с (момент фейла) — вместо sheet выбора аккаунта экран показывает **аудио-страницу Reels** («Secrets on Static» / «Использовать аудио» / сетка Reels).
- Лог: `ig_3_profile_screen` ×2 → `ig_4_sheet_reguard_0/1` → FAIL `sheet_not_opened`, `попыток=1`.

**Вероятный корень.** Тап по дропдауну имени аккаунта на профиле промахивается (попадает в сетку Reels → открывает Reel → уходит на аудио-страницу), sheet выбора аккаунта не появляется. Публикатор делает **ровно одну попытку** (`попыток=1`) и сдаётся, без повторного тапа/ожидания и без escape назад на профиль.

**Направление фикса (на этапе реализации уточнить TDD):**
- Robust-ретрай открытия sheet: если после тапа по имени аккаунта sheet не детектится — escape назад на чистый профиль (`ig_3_profile_screen`), пере-таргетить координаты имени аккаунта (контейнер с `content-desc`/`▼`, а не grid-thumbnail) и повторить тап N раз с проверкой появления sheet.
- Sheet-reguard: текущий `ig_4_sheet_reguard` фиксирует «не открылся», но не восстанавливает состояние — добавить recovery-ветку «ушли на Reel/аудио-страницу → BACK до профиля».
- Точность тапа: матчить кликабельный контейнер дропдауна имени (верхняя панель профиля), а не координаты, которые могут попасть в верхний ряд сетки.
- Обязателен kill-switch.

**Связи.** Follow-up WP#197 (родитель, honest-метка). Аналог на TikTok — WP#96 (account-picker bottomsheet silently fails to open) — Готово, можно подсмотреть подход.

## Фикс (WP#219) — РЕАЛИЗОВАН + СМЕРЖЕН в main

**Репо:** `GenGo2/delivery-contenthunter` (код autowarm). **PR #143** → merge main `5f342a0`.

**Корень (подтверждён по коду):** `account_switcher.py:_tap_profile_header` при отсутствии элемента-username в шапке делает СЛЕПОЙ тап по fallback-координатам `(540,180)` и **всегда возвращает `True`**. В reguard-цикле `_ig_guard_picker_foreground`, когда телефон оказался на аудио-странице Reels, слепой тап попадает в сетку → дрейф глубже → sheet не открывается → `ig_picker_sheet_not_opened`. Существующий escape `_ig_on_inapp_overlay` (WP#197 iter2) аудио-страницу не покрывал.

**Что сделано (kill-switch `IG_PICKER_AUDIO_ESCAPE_ENABLED`, default ON):**
- pure-детектор `_ig_on_audio_page(xml)` — матч CTA «Использовать аудио»/«Use audio» по `.label` разобранных элементов (не raw-substring; clickable у узла не требуем — урок WP#203);
- ветка escape в reguard-цикле: при fg=IG на аудио-странице → `KEYCODE_BACK` + bottom-nav профиль вместо слепого тапа (событие `ig_picker_reguard_audio_page_escaped`).

**Проверки:** 11 новых тестов (`tests/test_account_switcher_ig_audio_page_escape.py`) + reguard/picker наборы зелёные; общая регрессия 142 passed (1 pre-existing YT-fail `test_yt_happy_path_returns_accounts`, вне скоупа). Встроенный код-ревью (3+ finder-агента + verify): 1 PLAUSIBLE-замечание (substring-ложный escape) закрыто label-based матчем + 2 анти-ложных теста; дублирование тела escape-веток признано приемлемым (раздельный kill-switch/категория). Codex CLI недоступен (model-entitlement).

**Деплой:** `git pull` в прод-каталоге autowarm (`/root/.openclaw/workspace-genri/autowarm`) на 72.56.107.157; PM2-restart НЕ нужен (publisher per-task spawn). Выполняется на прод-сервере (этот триаж-хост — ContentHunter VPS, shell-доступа к autowarm-проду нет).

## Раннер-ап (отдельная задача, не этот фикс)

`ig_upload_confirmation_timeout` (5/3д) — НЕ зависший upload-спиннер: скринкаст task14150 (`septic.helper`) на момент фейла показывает full-screen промо **«Meta Verified»** («Получите первый месяц бесплатно», Standard/Plus, «Получить преимущества»), перекрывшее флоу. Группа гетерогенна (часть может быть реальным зависанием загрузки) → отдельный триаж/WP. Семейство интерстишал-дисмисса (WP#193/#206).
