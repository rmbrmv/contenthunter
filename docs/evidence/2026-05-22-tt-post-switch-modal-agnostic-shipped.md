# WP #67 Layer 3 — TT post-switch modal-agnostic confirm SHIPPED 2026-05-22

**WP:** OpenProject #67 (`tt_post_switch_verify_unrecoverable`) — третий заход (Layer 1 @-логин 14.05 PR #62, Layer 2 whitelist 18.05 PR #70).
**PR:** [GenGo2/delivery-contenthunter #99](https://github.com/GenGo2/delivery-contenthunter/pull/99) (squash `063f401`).
**Прод:** задеплоено fast-forward в `/root/.openclaw/workspace-genri/autowarm/` (HEAD `063f401`), Python подхватывается per-task spawn, без PM2 restart.
**Артефакты:** spec `docs/superpowers/specs/2026-05-22-tt-post-switch-modal-agnostic-confirm-design.md`, plan `docs/superpowers/plans/2026-05-22-tt-post-switch-modal-agnostic-confirm-plan.md`.

## Корень

Остаточные ложные `tt_post_switch_verify_unrecoverable` (1–3/сутки: 19.05=1, 20.05=3, 21.05=1, 22.05=2). Разбор скринкастов 6 фейлов (события `events[].meta.category`, кадры в `/tmp/wp67-frames/`) → три под-режима, общий корень «модалка/переходный экран сбивает чтение профиля», TikTok при этом остаётся на переднем плане (НЕ foreground-drift / WP #130):

| Под-режим | задачи | сигнатура | экран |
|---|---|---|---|
| A | 9124, 8685 | `feed_after_pick → renav_failed` | свитч удался (тост «Вы вошли как WellroomCare»), модалка «Подпишитесь на друзей» поверх ленты ломает renav |
| B | 8573, 9190 | `verify_unrecoverable` без feed | шторка свитча + спиннер, профиль не дочитан |
| C | 7715, 8616 | `feed_after_pick → verify_unrecoverable` | renav прошёл, «Быстрая проверка безопасности» поверх профиля |

## Фикс (3 кирпича под kill-switch)

1. **Banner** `_tt_read_login_confirm_banner` + `_tt_early_banner_confirm` (ранний dump после pick, до settle) + `_tt_post_switch_confirm` (banner→profile). Авторитетный screen-independent сигнал. `TT_POST_SWITCH_BANNER_DISABLED`.
2. **Generic dismiss** `_tt_find_safe_dismiss` (консервативный SAFE_DISMISS список, affirmative-кнопки исключены) + `_tt_dismiss_and_confirm_loop` (cap `TT_DISMISS_MAX`). `TT_POST_SWITCH_GENERIC_DISMISS_DISABLED`.
3. **Settle-retry** `_tt_screen_is_transitional` + цикл (`TT_SETTLE_S`/`TT_SETTLE_RETRIES`). `TT_POST_SWITCH_SETTLE_DISABLED`.

Реворк `_tt_handle_post_switch_unknown` оркестрирует кирпичи (pre_feed dismiss → settle → feed-detect → pre_renav dismiss → renav → post_renav dismiss → честный fail). Врезка early-banner + confirm в `_switch_tiktok`. **Fail-closed и mismatch сохранены**; WP #93 fail-fast не тронут.

Новые события: `tt_post_switch_confirmed_via_banner`, `tt_post_switch_modal_dismissed_generic`, `tt_post_switch_blocked_no_safe_button` (новый триаж-сигнал «добавь label в SAFE_DISMISS»), `tt_post_switch_settle_retry`, `tt_post_switch_banner_mismatch`. Терминальный `tt_post_switch_verify_unrecoverable` сохранён.

## Качество

- TDD subagent-driven: 31 новый тест (`tests/test_tt_post_switch_modal_agnostic.py`) + миграция 4 integration-тестов старого Layer 2; полный switcher-suite зелёный (130 passed после rebase на origin/main с WP #130/#132).
- Ревью: per-task spec+quality (sonnet) × 4 группы + финальное общее (opus) + codex по spec, plan и коду — **0 critical/important**. Подтверждено: dismiss тапает только закрывающие кнопки; early-banner short-circuit требует точного равенства handle; границы циклов; None-safe.
- Минорный долг (follow-up): dead-code старого whitelist `_try_dismiss_and_redump`/`_TT_POST_SWITCH_DISMISSIBLE_MODALS` оставлен определённым (10 unit-тестов зелёные); `exact=True` для tap как defense-in-depth; защита парсинга env-var.

## Деплой-нюанс (parallel-session)

origin/main опередил baseline на WP #130 (TT foreground-guard на `tt_3_open_list`, тот же `_switch_tiktok`!) + WP #132 + #105. Rebase прошёл чисто (регионы TT-switch vs мои не пересеклись построчно), 130 тестов зелёные пострибейз, врезка early-banner проверена визуально (после pick, до settle; WP #130 guard — до pick, отдельно).

## Live-smoke (re-queue 2026-05-22)

Перевыложены через `publish_queue` (3731→task 9124 wellroomcare под-режим A; 3970→task 7715 el_cosmo46 под-режим C; status→pending, publish_task_id→NULL).

Результат (новые pt созданы диспетчером, прогон на устройствах):

| новый pt | аккаунт | устройство | исходный под-режим | post-switch цепочка | статус | error-событий |
|---|---|---|---|---|---|---|
| 9386 | wellroomcare | RFGYC31P94Z | A | (clean, без unknown) | `awaiting_url` | 0 |
| 9385 | el_cosmo46 | RF8Y80ZT5JB | C | `handle_unknown → feed_after_pick → recovered_via_renav` | `awaiting_url` | 0 |

Оба переключения прошли (один — через переработанный recovery `recovered_via_renav`, второй — чисто), публикация ушла дальше переключения (`awaiting_url`), **ни один не упал** на `tt_post_switch_verify_unrecoverable`, 0 error-событий. После деплоя (`063f401`) новых `tt_post_switch_verify_unrecoverable` по аккаунтам нет.

Замечание: в этом прогоне `banner` и `generic dismiss` не срабатывали (модалка под-режима A в этот раз не появилась; под-режим C восстановился через renav). Перехватываемость баннера «Вы вошли как X» в dump'е этими двумя прогонами не подтверждена и не опровергнута — кирпич 1 остаётся включённым (best-effort), фикс держится на кирпичах 2+3 и переработанном renav. Подтверждение баннера — по событиям `tt_post_switch_confirmed_via_banner` в ходе 24h soak.

## 24h soak

Acceptance: тренд `tt_post_switch_verify_unrecoverable` 1–3/сутки → ~0 в части модалок/переходов. Остаток (новые `tt_post_switch_blocked_no_safe_button` без safe-кнопки) → отдельные WP. Перевод WP #67 → «Готово» после подтверждения за сутки.
