# IG fail-триаж 2026-06-05 (раунд 2) — SHIPPED+DEPLOYED

Источник: прод host-PG `openclaw` (`publish_tasks`, status=failed, platform=Instagram, testbench=false), окно 7д.
Логи — колонка `log`; события — `events` (jsonb); скринкасты — `screen_record_url` (save.gengo.io).
Фокус-сессия: только публикация Instagram. 3 параллельных субагента (изолированные worktree от origin/main), полный цикл Spec→Plan→TDD→codex-review.

## Распределение error_code (7д / 3д / 1д)
| error_code | 7д | 3д | 1д | вывод |
|---|---|---|---|---|
| switch_failed_unspecified | 58 | 0 | 0 | ops (outage шлюза 147.45.251.85), затух |
| adb_device_not_ready | 19 | 16 | 1 | ops/device-health |
| process_interrupted | 16 | 2 | 0 | артефакт рестартов |
| ig_account_switcher_wrong_foreground | 15 | 0 | 0 | покрыто WP#197 (затух) |
| ig_target_not_in_picker | 15 | 6 | 0 | ops (аккаунты не залогинены) |
| **ig_picker_sheet_not_opened** | 10 | 6 | 1 | **WP#263 — третья RC (спиннер)** |
| ig_caption_screen_not_reached | 9 | 2 | 0 | покрыто WP#193 |
| **ig_camera_open_failed** | 8 | 6 | 2 | **WP#240 — CAPTCHA/permission split** |
| ig_upload_confirmation_timeout | 7 | 3 | 2 | WP#255 (Meta Verified, шипнут 05.06) |
| **ig_external_app_foreground** | 2 | 2 | 2 | **WP#262 — новый код** |

### Откло­нены данными (не делались)
- **WP#251** (root-cause схлопнутого профиля / reels-drift): маркеры `reel_drift`/`reel_drift_escaped` за 7д = **0** (reguard работает 31×, но в Reels не дрейфит) → первопричина неактивна. Отложено.
- **WP#227** (не выбивать BACK'ом полу-открытый sheet): низкий приоритет, заблокирован отсутствием прод-XML полу-открытого sheet; в свежих падениях overlay-escape BACK не фигурирует. Отложено.

## WP#240 → PR#164 (merged f4a6bc2) — split CAPTCHA / OS-permission из ig_camera_open_failed
**RC по кадрам (5 задач):** код маскировал 2 ops-причины, не относящиеся к открытию камеры.
- **CAPTCHA** «Подтвердите, что вы человек» (bloks_container, «Введите код на изображении») — task 14830/13989 @procontent_lab. Account-challenge, нужен человек.
- **OS storage-permission** «Разрешить Instagram доступ к фото и видео» (`com.android.permissioncontroller` grant_dialog, «Разрешить ко всем») — task 14938/15518/15627 @ivana.world.class. Камера/picker УЖЕ открыты, диалог перекрывал галерею.

**Фикс** (`publisher_instagram.py` open_camera-цикл): новые коды `ig_account_challenge_captcha` (новый класс `account_challenge`→STRUCTURAL в `retry_decision.js`→handoff) + `ig_storage_permission_dialog` (info, авто-dismiss «Разрешить ко всем» по resource-id `permission_allow_all_button`/permissioncontroller, wording-independent fallback). Миграция `20260605_wp240_account_challenge_class.sql` (+rollback): CHECK publish_error_codes +account_challenge, seed кода. Kill-switch `IG_CAMERA_CHALLENGE_PERMISSION_SPLIT_ENABLED` (default ON). 21 py + 23 js, IG-регрессия 161 passed.
**Честно:** это улучшение триажа (CAPTCHA=нужен человек, permission=конфиг устройства), а не баг камеры; permission вдобавок авто-решается.

## WP#262 → PR#162 (merged 06f0505) — новый ig_external_app_foreground
**RC по кадрам + events (`topResumedActivity`):** foreground украден ПОСЛЕ открытого picker'а. task 15517/11068 = `com.sec.android.app.launcher` (лаунчер Samsung); 15507/10764 = `com.zhiliaoapp.musically` (TikTok). Классификатор Шаг-5 `_ig_classify_pre_picker_state` при ЕДИНСТВЕННОМ замере `foreground!=IG` мгновенно фейлил → ручная (риск дубля), без анти-дребезга и recovery (sibling-ветки их имеют).
**Фикс** (`publisher_instagram.py`): `_ig_recover_external_app_pre_picker` (2-sample confirm 0.5с → `transient`; подтверждённый чужой → 1× recovery `am start`, без force-stop → **успех ТОЛЬКО при позитивной верификации picker** `_ig_is_gallery_picker_open` на свежем дампе, не по pkg). Caller recheck использует реальный foreground (не хардкод IG) → честный fail-fast при повторном уходе (латч=1 recovery/задача). Хелпер `_ig_resolve_pre_picker_guard`. Kill-switch `IG_PRE_PICKER_EXTERNAL_RECOVERY_ENABLED` (default ON). 17 + IG-регрессия 153 passed.
**Code-review:** 2 раунда codex закрыли P1 (recovery=любой IG-fg, а am start MainTabActivity=лента не picker) + P2 (recheck хардкод pkg маскировал повторный уход). Остаточный спекулятивный P2 (picker-проверка под дисмисс-оверлеем) отклонён: проверяется picker-ROOT (переживает оверлей в uiautomator-дереве), направление fail-safe.

## WP#263 → PR#163 (merged 128fc51) — picker_sheet_not_opened третья RC (спиннер-sheet)
**RC по кадрам:** остаток после WP#225, НЕ reel-drift и НЕ overlay-escape. account-switcher bottom-sheet РЕАЛЬНО открыт (drag-handle), но список ещё **догружается** — синий спиннер, markerless dump (только «Отмена» + центр-спиннер, recycler-маркеров нет). `_ig_on_account_switcher_sheet` матчит только загруженный список → poll 3×1с выходит до догрузки → ложный fail попыток=1. Лидер born.trip90 ×3; распределено по 8 аккаунтам → код, не ops.
**Фикс** (`account_switcher.py`): `_ig_on_loading_account_switcher_sheet` (детектор спиннер-sheet, disjoint от загруженного/reel-drift/overlay/audio) + продление окна poll один раз (+4 попытки ≈6с, не висит) в `_ig_poll_account_switcher_sheet`. Kill-switch `IG_PICKER_LOADING_SHEET_WAIT_ENABLED` (default ON). 14 + IG-switcher регрессия 95 passed. Валидация на живых прод-дампах (zero false-positive на feed/reel-drift). Codex чисто.
**Follow-up:** рекуррентный reel-drift (task 15660, escape срабатывает но re-tap re-дрейфит) — отдельная под-RC, частично пересекается с отложенным WP#251.

## Деплой (05.06)
- Merge в main: PR#163 (128fc51) → PR#164 (f4a6bc2) → PR#162 (06f0505). Hunk-overlap #162/#164 в publisher_instagram.py отсутствует.
- Миграция `20260605_wp240` применена на живой `openclaw` (идемпотентно): CHECK +account_challenge, код seeded.
- Прод autowarm `/root/.openclaw/workspace-genri/autowarm` ff-pull → HEAD 06f0505; новый код подтверждён.
- `pm2 restart 35` (autowarm: server.js+retry_controller один процесс — нужен для `retry_decision.js`); publisher per-task spawn (для publisher_instagram.py/account_switcher.py рестарт не обязателен, но процесс общий). Online, unstable restarts 0.
- Смоук: `retry_decision` 23/23 на проде, логи без ошибок нового кода. Все 3 OP→Тестирование.

## Процессный урок
Codex-ревью в субагентском sandbox технически невозможно (внутренний bubblewrap режет git: `bwrap: loopback Failed RTM_NEWADDR Operation not permitted`). Запуск из главного процесса требует `codex exec review --base main --dangerously-bypass-approvals-and-sandbox`. Вписать флаг в будущие брифинги субагентов.

## Остаток
Live-verify сутки по событиям: `ig_account_challenge_captcha`/`ig_storage_permission_dialog` (+`ig_camera_open_grace_recovered` WP#238), `ig_pre_picker_external_recovered`/`_recovery_failed`, `ig_picker_loading_sheet_awaited`. Follow-up: рекуррентный reel-drift (WP#251 переоценить по 15660).
