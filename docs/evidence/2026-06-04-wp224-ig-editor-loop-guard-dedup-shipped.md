# WP#224 — Дедуп editor_loop gallery-branch guard: SHIPPED+DEPLOYED 2026-06-04

- **OpenProject:** WP#224 (Ошибка, тех-долг из код-ревью WP#206 iter2) → **Тестирование**.
- **Код:** GenGo2/delivery-contenthunter — merge `3d143cc` в main (`--no-ff`, ветка `wp224-ig-editor-loop-dedup`).
- **Спек/план:** `docs/superpowers/specs|plans/2026-06-04-wp224-ig-editor-loop-gallery-guard-dedup-*.md` (в delivery-репо).
- **Тип:** чистый рефактор, без изменения поведения, без kill-switch.

## Корень (тех-долг)
В `publisher_instagram.py::publish_instagram_reel` две почти идентичные ветки обработки «детект галереи внутри editor loop» — `editor_loop_1` (keyword-based, GALLERY_KW) и `editor_loop_2` (resource-id, GALLERY_MARKERS) — симметрично дублировали:
1. **advance-гард (WP#206 iter2)** — `_ig_editor_false_gallery_advanceable` за kill-switch `_ig_editor_false_gallery_advance_enabled()` → тап `EDITOR_NEXT_COORD` + `continue` (ложный gallery-матч на готовом редакторе);
2. **Layer-B аборты** — `_ig_is_editor_screen` / `_ig_is_multiclip_add_picker` → `return False` (защита от кросс-проектной склейки клипов).

Сам код был помечен «Дубликат логики первой editor-loop branch» — при WP#206 зеркальный гард пришлось вставлять в обе ветки руками (риск рассинхрона при будущих правках этой защиты).

## Фикс
Вынесен общий метод `InstagramMixin._ig_editor_loop_gallery_branch_guard(self, ui, step, *, branch, advance_where, editor_next_coord)`, возвращающий строковый сигнал (идиома как у `_ig_handle_edits_promo_at_picker`):
- `'advance'` — helper уже залогировал, тапнул `editor_next_coord` + sleep(3); вызывающий → `continue`;
- `'abort'`   — helper уже сделал `log_event` + `_save_debug_artifacts`; вызывающий → `return False`;
- `'proceed'` — безопасно; вызывающий проваливается к inline edits-промо гарду + re-select.

Обе ветки editor_loop_1/2 заменены на вызов helper'а + 3-way dispatch. Различия прокидываются параметрами для **byte-identical** поведения:
- `branch`: `editor_loop_1` / `editor_loop_2` → meta Layer-B событий;
- `advance_where`: `editor_loop_gallery_branch` / `editor_loop_2` → meta `where` advance-события (значения сохранены 1:1);
- `editor_next_coord`: `EDITOR_NEXT_COORD` параметром (остальные 6 использований локальной переменной не тронуты).

**Вне scope** (оставлено inline в каждой ветке): edits-промо гард `_ig_handle_edits_promo_at_picker` и re-select (`_resel`/`_resel2`).

**Единственное отличие** от исходника — человекочитаемая `log.warning`-строка advance-гарда стала единой (с упоминанием `branch`); структурированные `log_event`/`meta` без изменений (категории `ig_editor_false_gallery_advanced` / `ig_editor_falsely_detected_as_gallery` / `ig_picker_multiclip_add_unsafe` сохранены, по 1 в helper'е, проверено diff'ом).

## Тесты
- Характеризационные `tests/test_ig_editor_loop_gallery_branch_guard.py` (6): все 3 сигнала + оба abort-подсценария (editor_screen + multiclip_add_picker) + прокидывание `branch`/`advance_where` для loop1/loop2 + gate-OFF → fall-through к Layer-B. Предикаты НЕ мокаются (реальные `_ig_*`), мокаются только `adb_tap`/`log_event`/`_save_debug_artifacts` и env-флаг.
- Курируемая IG-регрессия (10 файлов, non-live): **152 passed**. На смёрдженном прод-дереве (5 leak-критичных файлов): **84 passed**.
- ⚠️ полный `pytest tests/` зависает (live-зависимости) → курируемый набор.

## Процесс
brainstorm → spec → plan → subagent-driven (4 таска, two-stage review каждый: spec-compliance + code-quality) → opus final-review (**READY TO MERGE, cross-project-leak регрессии НЕТ**) → merge → deploy.

Spec-review поймал пробел покрытия (нет теста на `ig_picker_multiclip_add_unsafe`) → добавлен до прохода. Код-ревью подтвердил: безопасные аборты воспроизведены идентичными предикатами в том же порядке; advance тапает фиксированный `EDITOR_NEXT_COORD` (не `video_candidates[0]`) → re-tap/склейка невозможна.

## Деплой
1. merge `--no-ff` ветки в main (прод-autowarm checkout `/root/.openclaw/workspace-genri/autowarm` = `main`) → working tree обновлён напрямую (= деплой).
2. push `e224895..3d143cc`.
3. **PM2-restart не нужен** — publisher спавнится per-task.
4. Worktree удалён, ветка `wp224-ig-editor-loop-dedup` смёрджена и удалена.

## Остаток
- **Verify (~сутки):** структурированные события IG-публикаций не должны измениться (те же категории/meta) → WP#224 «Готово».
- **Follow-up (Бэклог WP#249):** унифицировать `advance_where` метку editor_loop_1/2 (`editor_loop_gallery_branch` vs `editor_loop_2`) — минорная несогласованность наблюдаемости, унаследована из исходника.
