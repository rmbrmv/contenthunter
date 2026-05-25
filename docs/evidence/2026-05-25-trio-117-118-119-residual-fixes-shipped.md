# Переоткрытая тройка #117/#118/#119 — добивка SHIPPED+DEPLOYED 2026-05-25

**Статус:** все 3 PR merged, прод `delivery-contenthunter` main `8826fd8`, WP → «Тестирование». Приёмка — утренняя пачка 26.05.

## Контекст
Три бага получили фиксы 21.05, ушли в «Тестирование», но при триаже 25.05 рецидивировали → возвращены в «В разработке». Общая тема: гард/проверка 21.05 формально срабатывает, но не доводит сценарий до конца. Свежие числа рецидива (publish_tasks, финальная `meta.category`, исключая `adb_devices_unreachable`/`process_interrupted`, 22–25.05): #119 = 2/2/2/3 (9), #118 = 3/0/1/3 (7), #117 = 0/0/0/1 (1, слабый сигнал, но recovery объективно сломан).

Метод разведки: 3 параллельных read-only субагента (события упавших задач + прод-код + само-проверка по скринкасту). Урок — по #118 анализ только событий дал неверный вывод; решил видео-разбор (правило «видео в первую очередь»).

## Корневые причины (подтверждены)

### #119 IG `ig_target_not_in_picker` (PR #102)
На шаге `ig_4_pick_account` Instagram **на переднем плане**, но открыт Home/Reels Feed, а не sheet выбора аккаунта (UI-дампы tasks 9448=Reels, 9476=Home). Гард 21.05 `_ig_guard_picker_foreground` проверял только foreground-пакет → пропускал; парсер скрёб ленту → мусор → ложный код.
**Фикс:** staticmethod `_ig_on_account_switcher_sheet(xml)` (позитивный маркер `account_switcher_recycler`/`bottom_sheet_container` — взят из существующего `_ig_is_on_unexpected_screen`); в гарде после пакет-проверки — валидация экрана, при не-sheet → re-open list (2 попытки), при неуспехе честный `ig_account_switcher_wrong_foreground`. Kill-switch `IG_PICKER_SHEET_GUARD_ENABLED` (отдельный от `IG_PICKER_FG_GUARD_ENABLED`; call-site не тронут → два уровня отката).

### #118 TT `tt_upload_confirmation_timeout` (PR #103)
**Ложно-негатив (аналог IG #73).** Публикация реально проходит (скринкаст task 9357: пост в ленте «ContentHunter_0 · 1 c. назад», нижняя навигация видна), но поверх ложится post-publish промо-плашка **«Пусть вас заметят» / TikTok Amplify** (кнопка «Не сейчас») — детектор подтверждения её не знал → таймаут. В событиях плашка не логировалась (слепая зона). Visibility-модал и Samsung-overlay в упавших задачах НЕ срабатывали — причина не в них.
**Фикс:** `_detect_tt_amplify_modal` + `_handle_tt_amplify_modal` по образцу существующего promo-inbox хендлера (WP #82): tri-state, per-task cap → `inferred_success`, дисмисс «Не сейчас» + KEYCODE_BACK fallback. Wire-up в `_wait_upload_confirmation` под kill-switch `TT_AMPLIFY_MODAL_HANDLER_ENABLED`.

### #117 YT `yt_editor_upload_timeout` (PR #104)
Сам recovery desc-trap-гарда 21.05 сломан: `KEYCODE_BACK` без проверки `topResumedActivity` (события task 9628: BACK с «Добавьте описание» → профиль канала, повторный → лаунчер → дрейф → таймаут).
**Фикс:** helper `_yt_restart_upload_activity` (извлечён из stuck-counter; резолвит content-uri ДО HOME); в desc-trap-гарде после BACK — probe `topResumedActivity`, при уходе из YouTube рестарт `Shell_UploadActivity`; cap=2 повторов → рестарт вместо нового BACK; сброс `_yt_prev_texts`. Новые события `yt_desc_trap_restart`/`yt_desc_trap_back_left_app`. Kill-switch `YT_DESC_TRAP_GUARD_ENABLED` (существующий). Слабый сигнал (1 рецидив), но механика была сломана.

## Процесс и качество
brainstorm → spec → plan (оба codex-clean) → subagent-driven (3 PR параллельно, изолированные worktree-ы) → spec+quality review + независимое финальное opus-ревью (**approve ×3**). Codex на каждом PR поймал 2 реальных бага до прода: небезопасный generic feed-маркер «Входящие» (#118, убран), порядок HOME/uri (#117, исправлен). Тесты: 80 зелёных в прод-копии (15 IG + 55 TT + 10 YT, новых ~14).

## Деплой
3 PR squash-merged в main → прод `git pull --ff-only` (8826fd8). Per-task spawn → код подхватывается без рестарта PM2. Откат: `IG_PICKER_SHEET_GUARD_ENABLED=0` / `TT_AMPLIFY_MODAL_HANDLER_ENABLED=false` / `YT_DESC_TRAP_GUARD_ENABLED=0`.

## Приёмка (verify утром 26.05, нормальный трафик)
- `ig_target_not_in_picker` → ~0; остаток проявляется `ig_picker_wrong_screen` / `ig_account_switcher_wrong_foreground`.
- `tt_upload_confirmation_timeout` → падает; events `tt_amplify_modal_detected` / `tt_post_publish_inferred_from_amplify_loop` / `inferred_success`.
- `yt_editor_upload_timeout` (desc-trap сигнатура) → 0; при срабатывании — `yt_desc_trap_restart` / `yt_desc_trap_back_left_app` вместо ухода в лаунчер.

При подтверждении WP #117/#118/#119 → «Готово».

## Известные мелочи (от opus-ревьюера, не блокеры)
- #119: микро-гонка между dump для проверки sheet и финальным парсом (источник тот же, риск низкий).
- #117: после cap рестарт срабатывает на каждый повторный trap (ограничено бюджетом цикла 25 шагов, это путь восстановления).
