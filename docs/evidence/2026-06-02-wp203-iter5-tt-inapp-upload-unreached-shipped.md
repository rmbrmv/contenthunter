# WP#203 iter5 — `tt_inapp_upload_unreached` (driver B): SHIPPED+DEPLOYED

- **Дата:** 2026-06-02
- **OpenProject:** #203 «TikTok publish flow нестабилен» → **Тестирование**
- **Репо/деплой:** delivery-contenthunter, PR #148 → main `94dadba`; прод autowarm (`/root/.openclaw/workspace-genri/autowarm`) — iter5 в `publisher_tiktok.py`; PM2-restart не нужен (publisher per-task spawn); миграции нет.

## Разграничение скоупа
После iter4 у #203 остались два публикатор-драйвера TikTok:
- **Driver A `tt_upload_confirmation_timeout`** — закрыт отдельной задачей **WP#218** (задеплоен+верифицирован live 02.06). iter5 его **не трогал** (без двойной работы).
- **Driver B `tt_inapp_upload_unreached`** — скоуп iter5.

`adb_device_not_ready` (крупнейший сырой код) — device-health, вне #203 (WP#195/#210/#207).

## Root cause (driver B), прод-данные 02.06 (host-PG `localhost:5432/openclaw`, `publish_tasks`)
Стейт-машина `_tt_inapp_upload_from_camera` (лимит `MAX_INAPP_UPLOAD_ITERATIONS=12`) после story-derail escape (BACK) приземлялась в нераспознанный/ложный экран и не имела детерминированной ре-навигации в `feed→«+»→редактор` → холостой `sleep` до исчерпания лимита → `tt_inapp_upload_unreached` → ручная (~13/день).

Три проявления (события + UI-дампы):
1. **fg=лаунчер после BACK-перелёта** — BACK из story-derail выходил в `com.sec.android.app.launcher`; внешний foreground-recovery возвращал TikTok, но в произвольный под-экран.
2. **Профиль ложно классифицировался** (task 14223) — экран собственного профиля разделяет нижнюю навигацию с лентой (→ `_tt_detect_feed` True), содержит «Эффекты» (→ editor-маркер) и текст «Добавить в историю» сторис-кольца (→ story-derail). Тап «+» из профиля снова уводил в derail.
3. **Story-picker вариант** (task 14189) — «Добавить в историю» + табы-галерея, ловился как derail, но BACK снова перелетал.

Единственная recovery (`_post_derail_feed_recovery`) была **однократным** BACK — при fg=лаунчер бесполезна.

## Фикс (подход А, TDD)
- `_tt_detect_profile_screen` — строгий own-profile детект (`@`-handle + ≥1 из {Подписки/Подписчиков/Лайки} + «TikTok Studio»). Ветка **a2** в стейт-машине **сразу после caption** (перед editor — т.к. профиль ложно матчит «Эффекты») → роут на «Главная» (`_tt_tap_home_nav`), не «+».
- `_tt_reset_to_feed` — детерминированный `am start -p <pkg> -a MAIN -c LAUNCHER` → ре-дамп → проверка feed. Лечит fg=лаунчер.
- Повторяемый unknown-reset в ветке (g) с капом `MAX_INAPP_UNKNOWN_RESETS=3` вместо iter4 one-shot. Удалён флаг `TT_STORY_DERAIL_FEED_RECOVERY_ENABLED` и атрибут `_post_derail_feed_recovery_done`.
- Kill-switch `TT_INAPP_UNKNOWN_RESET_ENABLED` (default ON; в прод `.env` не выставлен → активен).
- Story-picker (14189) — проверочные тесты подтвердили, что существующий `_tt_detect_story_derail` его уже ловит (кода не меняли).

## Качество
- Процесс: brainstorm→spec→plan→subagent-driven (9 задач, haiku/sonnet), per-task spec+quality review + финальное холистическое ревью (**READY TO MERGE**).
- TDD: 74 теста в `tests/test_publisher_tt_inapp_upload.py` (реальные прод-дампы 14223/14189/feed как фикстуры; профиль-роутинг, cap=3, flag-off fall-through).
- Регрессия: полная TT-выборка **774 passed, 0 регрессий iter5** (2 pre-existing fail вне скоупа).

## Деплой-заметка (гонка общего прод-checkout)
Прод-`main` был в гонке с параллельной сессией **WP#152** (3 непушнутых локальных коммита: schemes/overlays/audio_bitrate). Файловые наборы disjoint (iter5=`publisher_tiktok.py`+тесты; WP#152=unic/схемы/overlays; `prep_circle_overlays.py` идентичен в обеих ветках). Деплой выполнен **неразрушающим** `git merge origin/main` в прод-дереве (без reset/force); прод-main **не пушился** (чужие WP#152-коммиты целы); 2 untracked-артефакта отодвинуты в `/tmp/prod-untracked-backup-wp203` (вернулись из origin как tracked).

## Остаток (→ Тестирование)
Live-verify сутки:
- `tt_inapp_upload_unreached` падает с ~13/день к длинному хвосту;
- появляется событие `tt_inapp_unknown_reset` и завершается достижением редактора (не до капа);
- рост TT success.

Откат: `TT_INAPP_UNKNOWN_RESET_ENABLED=false` (рестарт не нужен).

Spec/план: `docs/superpowers/specs/2026-06-02-wp203-iter5-tt-inapp-upload-unreached-design.md`, `docs/superpowers/plans/2026-06-02-wp203-iter5-tt-inapp-upload-unreached.md` (delivery-contenthunter).
