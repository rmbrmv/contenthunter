# WP #122 — TT share-loop «Добавить в историю» overlay — SHIPPED+DEPLOYED (OFF)

**Date:** 2026-05-26
**OpenProject:** [#122](https://openproject.contenthunter.ru/wp/122)
**PR:** [GenGo2/delivery-contenthunter #106](https://github.com/GenGo2/delivery-contenthunter/pull/106) (merged, merge commit `2972cce`)
**Spec:** `docs/superpowers/specs/2026-05-26-wp122-tt-share-loop-overlay-design.md`
**Plan:** `docs/superpowers/plans/2026-05-26-wp122-tt-share-loop-overlay-plan.md`

## Что сделано

Второй суб-режим `tt_upload_confirmation_timeout` (≈4/7 за 20.05): окно «Добавить в историю» (Samsung Add-to-Story / TT in-app Stories) перекрывает экран во время поиска кнопки «Опубликовать» в share-loop → кнопка не находится → fallback-coords мимо → таймаут.

Фикс — **переиспользование существующих** detect+dismiss хелперов (`_detect/_handle_samsung_stories_overlay`, `_detect/_handle_tt_inapp_stories`), которые раньше работали только в `wait_upload`, теперь и в share-loop через новый orchestrator `_run_tt_stories_overlay_share_loop_hook` (зеркало commercial-music хука). `publisher_tiktok.py` +79/-6.

Хендлеры получили `phase='wait_upload'` (default) — влияет только на `step` события; wait_upload payload не меняется (byte-for-byte). stuck-step phase-aware (`tt_5_share_loop_*_stuck`) для отличимой телеметрии.

## Безопасность / режим выката (решение WP #122)

- **Kill-switch `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED` — default OFF.** Деплой выполнен OFF (флаг нигде не выставлен) → поведение прода НЕ изменилось.
- Решение: тёмный выкат → happy-path смок на testbench → ручное включение + мониторинг. Причина осторожности: правка основного пути публикации (share-loop) до нажатия кнопки.

## Верификация

- Тесты: `tests/test_publisher_tt_share_loop_overlay.py` (16) + весь TT-регресс ≈ 253 passed, 0 fail. Критичный `test_loop_integration_lines_present_and_in_order` (порядок wait_upload) цел.
- Codex по spec/plan/коду — 0 P1 (telemetry-замечание закрыто фиксом stuck-step).
- Прод: `git pull` FF → `2972cce`; `import publisher_tiktok` OK; 16 тестов зелёные на проде; kill-switch default OFF подтверждён.

## Осталось (backlog)

1. **Happy-path смок на testbench** (#19/#171): обычная TT-публикация без оверлея → хук = `clean`, кнопка находится/нажимается, публикация проходит (главный регресс-гард основного пути).
2. **Включение** `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true` в проде (env воркера + рестарт) — живой риск, только после смока.
3. **Мониторинг** после включения: `tt_upload_confirmation_timeout` ↓ + `tt_samsung_overlay_dismissed`/`tt_inapp_stories_dismissed` (phase=share_loop). Если `*_stuck` с `step=tt_5_share_loop_*` — оверлей-вариант, который dismiss не берёт.
4. **Shared cap** (общий счётчик share_loop+wait_upload): при ложных stuck развести счётчики по фазам (отдельная правка). Маловероятно.
5. **`KEYCODE_BACK` на композере**: следить, не уводит ли BACK со share-экрана при реальных оверлеях (риск-секция спеки).
