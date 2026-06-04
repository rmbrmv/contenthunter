# WP#249 — Унификация advance_where метки editor_loop_1/2: SHIPPED+DEPLOYED 2026-06-04

- **OpenProject:** WP#249 (Ошибка, follow-up WP#224) → **Тестирование**.
- **Код:** GenGo2/delivery-contenthunter — merge `3f780e3` в main (`--no-ff`, ветка `wp249-advance-where-unify`).
- **Спек/план:** `docs/superpowers/specs|plans/2026-06-04-wp249-advance-where-unify-*.md` (в delivery-репо).
- **Тип:** мелкая нормализация метрик, без kill-switch.

## Проблема
В helper `_ig_editor_loop_gallery_branch_guard` (`publisher_instagram.py`, из [WP#224](2026-06-04-wp224-ig-editor-loop-guard-dedup-shipped.md)) параметр `advance_where` шёл в `meta["where"]` события `ig_editor_false_gallery_advanced` и имел разные значения для двух веток (унаследовано из исходника, сохранено намеренно ради byte-identical рефактора):
- `editor_loop_1` → `editor_loop_gallery_branch`
- `editor_loop_2` → `editor_loop_2`

Одно поле — две конвенции меток (минорная несогласованность наблюдаемости).

## Безопасность (проверено)
`meta.where` этого события **нигде не потребляется кодом**: ни дашборды, ни `server.js`-аналитика, ни «Лог событий», ни триаж-запросы. Значения встречались только в продюсере и тестах. Поле диагностическое (читают люди при ad-hoc триаже) → смена безопасна.

## Фикс
Параметр `advance_where` удалён; advance-событие пишет `meta["where"] = branch`. Поскольку helper уже принимал `branch`, отдельный параметр был избыточен.
- Сигнатура: `_ig_editor_loop_gallery_branch_guard(self, ui, step, *, branch, editor_next_coord)`.
- Оба call-site: убран аргумент `advance_where=...`.
- **Эффект:** для `editor_loop_1` `meta.where` `editor_loop_gallery_branch` → `editor_loop_1`; `editor_loop_2` без изменения. Все три IG editor-loop события (`ig_editor_false_gallery_advanced` + `ig_editor_falsely_detected_as_gallery` + `ig_picker_multiclip_add_unsafe`) теперь используют единую метку `editor_loop_1`/`editor_loop_2`.

## Тесты
- `tests/test_ig_editor_loop_gallery_branch_guard.py`: advance-`where`==`branch` для обеих веток (loop1 обновлён, loop2 — новый тест), `_call` без `advance_where`; итого 7 в файле.
- Курируемая IG-регрессия (non-live): **85 passed**; на смёрдженном дереве (3 leak-критичных файла): 43 passed.
- ⚠️ полный `pytest tests/` зависает (live-зависимости) → курируемый набор.

## Процесс
brainstorm → spec → plan → subagent-driven (2 таска, two-stage review каждый) → final-review (**READY TO MERGE, cross-project-leak регрессии НЕТ** — затронута лишь диагностич. метка) → merge → deploy.

## Деплой
1. merge `--no-ff` `3f780e3` в main (прод-autowarm checkout = main → working tree обновлён напрямую).
2. push `3e52e1b..3f780e3`.
3. **PM2-restart не нужен** (publisher per-task spawn). Worktree+ветка убраны.

## Остаток
- **Verify (~сутки):** события editor-loop пишут единую `where`-метку (`editor_loop_1`/`editor_loop_2`) → WP#249 «Готово».
