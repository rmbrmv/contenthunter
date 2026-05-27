# WP #140 — классификатор error-кодов `publish_error_codes`: SHIPPED + DEPLOYED 2026-05-27

**Статус:** задеплоено в прод, OpenProject #140 → «Тестирование».

## Что было
Движок ретраев (WP #108) резолвит `error_class` из справочника `publish_error_codes` по `code=error_code` с фолбэком `unknown`. ~35 реальных прод-кодов отсутствовали в справочнике → дефолтились в `unknown` → трактовались как transient и ретраились (пример: `pq#5069` `yt_picker_target_absent`).

## Решения (брейншторм с Данилом)
- UI-навигационные коды (экран/пикер/фокус/anchor) → `ui_changed` (STRUCTURAL → сразу в ручную). Acceptance №3 переформулирован: «сразу handoff», без «после лимита» (для `ui_changed` лимит недостижим).
- `switch_failed_unspecified` (738/30д, catch-all, микс сеть/UI) → `unknown` (transient, is_known=true).
- Отдельная задача на таксономию/нейминг → **OpenProject #166** (Бэклог).

## Что сделано
- Миграция `migrations/20260527_wp140_error_class_catalog.sql` (`INSERT ... ON CONFLICT (code) DO UPDATE`, идемпотентно) + scoped backfill in-flight задач через CTE `INSERT ... RETURNING` (`manual_handoff_at IS NULL` — не трогаем завершённые хэндофы). Парный `__rollback.sql`.
- Классификация 35 кодов: `ui_changed` 24 / `unknown` 7 / `network` 2 / `banned` 2.
- Тест `test_wp140_error_class_catalog.test.js` (применяет миграцию/rollback в транзакции с ROLLBACK — без мутации прода).
- Репозиторий кода: autowarm `GenGo2/delivery-contenthunter`, **PR #110** (merge-commit `937bd8353`).

## Деплой и верификация (прод, openclaw@localhost)
- Пред-апплай: 63 строки каталога; 0/35 целевых кодов существуют (предусловие rollback держится); 35 недостающих прод-кодов.
- Апплай: `BEGIN / UPDATE 19 / COMMIT` (backfill перекласовал 19 in-flight задач). Перезапуск не требовался (публикатор читает каталог живым SQL; контроллер — материализованный `pt.error_class`).
- Пост-апплай: каталог **98** (63+35); инвариант «нет некаталогизированных прод-кодов» = **0**; классы 35 новых = ui_changed 24 / unknown 7 / network 2 / banned 2; stale in-flight = **0**.
- Тесты: 11/11 GREEN (9 антирегресс `test_retry_decision` + 2 новых). Codex: 0 P1 (остаточный P2 — безусловный rollback `DELETE` — принят: одна БД, 35 кодов проверенно отсутствовали).

## Что осталось
- Наблюдение 1–2 дня: UI-падения (`yt_*`/`ig_*`/`tt_*`) уходят в handoff сразу (`structural_error`), транзиентные — после окна 2д (`window_exhausted`), а не крутятся вхолостую.
- При проблеме откат: `psql -f migrations/20260527_wp140_error_class_catalog__rollback.sql` (backfill необратим по дизайну).
- Наведение порядка в нейминге/таксономии ошибок — отдельная задача #166.
