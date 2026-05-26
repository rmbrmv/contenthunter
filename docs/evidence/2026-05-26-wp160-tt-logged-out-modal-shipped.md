# WP #160 — TT модалка разлогина «Вы вышли из аккаунта» — SHIPPED+DEPLOYED 2026-05-26

**Parent:** WP #131. **Spec:** `docs/superpowers/specs/2026-05-26-wp160-tt-logged-out-modal-design.md`. **Plan:** `docs/superpowers/plans/2026-05-26-wp160-tt-logged-out-modal.md`.

## Что было не так

TikTok при разлогине показывает модалку «Статус аккаунта» с текстом «Вы вышли из аккаунта. Попробуйте войти снова.» и кнопкой «OK». Это не полноэкранный логин (нет «Войти»/«Создать аккаунт»), поэтому детектор `_tt_is_logged_out` её не ловил. В own-profile петле верификации все 4 детектора давали False, бот зря крутил 3 retap'а + cold-start и падал общей ошибкой `tt_profile_tab_broken`, вводя триаж в заблуждение. Пример: задача 9652 (LexisVoice_Up, RFGYB180RZV, 25.05).

## Что сделано

Approach A (выделенный детектор по образцу WP #93):

- Общий matcher `_tt_match_modal_whitelist(xml, whitelist)` вынесен из `_tt_detect_switch_blocking_modal` (рефактор без смены поведения, WP #93 тесты byte-identical).
- Новый whitelist `_TT_LOGGED_OUT_MODALS = (('Вы вышли из аккаунта', 'OK', 'manual_login_required'),)` + детектор `_tt_detect_logged_out_modal` (heading в non-clickable + «OK» exact в clickable).
- Handler `_maybe_handle_logged_out_modal` в own-profile петле (`account_switcher.py`, после `_tt_is_logged_out`, перед `_tt_is_reauth_prompt`): event `tt_logged_out_modal` → `account_blocks.set_block_by_username(reason='manual_login_required')` → `notify_escalation` → fail-fast `step='tt_2_logged_out_modal'`. Кнопку «OK» не тапаем.
- Маппинг `tt_2_logged_out_modal → tt_logged_out_modal` в `_SWITCHER_STEP_TO_CATEGORY` (`publisher_kernel.py`).
- Kill-switch `TT_LOGGED_OUT_MODAL_GUARD` (default ON) + кодовый фолбэк (пустой whitelist).
- Фикстура из реального дампа 9652 (MD5 сверен с save.gengo.io).

**Тесты:** 14 WP #160 (детектор match/no-false-positive/no-cross-match/no-OK; handler freeze/escalation/fail/kill-switch обе стороны; интеграция через `_switch_tiktok`; error_code map). Полный TT-регресс зелёный (включая WP #93/#131/#159 — мирно сосуществует с viewer-history dismiss-whitelist). 8 IG-падений (`ig_4_pick_account_fg_guard`) — pre-existing на базовом коммите (проверено: падают идентично без этой ветки), не регрессия #160.

**Ревью:** per-task spec + code-quality review (subagent-driven) + финальный holistic review — все Approved; codex review спеки/плана/кода — 0 P1.

## Деплой

Прод autowarm `main` merge-коммит **`7ebcea7`** (`merge --no-ff wp160-tt-logged-out-modal`, 5 коммитов `7ae88c5..6491abf`, ребейзнуты на текущий main `a675b2d`). `git push origin main` `a675b2d..7ebcea7` → GenGo2/delivery-contenthunter. Python спавнится свежим per-task → **PM2 restart не нужен**. Санити в прод-чекауте: 14/14 зелёные.

## Что осталось

24ч verify (~27.05): появилась категория `tt_logged_out_modal`; затронутые аккаунты получают `tt_block.reason='manual_login_required'` и уходят из warming-ротации; `tt_profile_tab_broken` не растёт (модалочная доля ушла в честный код). По итогу → WP #160 «Готово». Откат: `TT_LOGGED_OUT_MODAL_GUARD=0`.
