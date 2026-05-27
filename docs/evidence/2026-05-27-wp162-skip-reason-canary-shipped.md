# WP #162 — канарейка контракта `skip_reason='moved_from_slot%'` (follow-up WP #154) — SHIPPED+DEPLOYED 2026-05-27

**Тип:** хардинг, низкий приоритет. Ноль рантайм-изменений — только тесты + комментарии. OpenProject #162 → «Готово».

## Что было не так
Между двумя репозиториями есть **негласный кросс-репо контракт**. При переносе слота валидатор отменяет старые pending-строки `publish_queue` со `skip_reason='moved_from_slot_<src>_to_<dst>'`; сторона выкладки (delivery) опознаёт перенесённый контент по `skip_reason LIKE 'moved_from_slot%'` и пере-ставит его в очередь (WP #154). Если бы валидатор сменил текст причины — delivery **молча** перестал бы re-queue (тихий регресс, как было до #154), и заметили бы не сразу.

## Карта контракта (verified origin/main 27.05)
- **producer (источник литерала):** `validator backend/src/routers/schedule.py` (`_perform_move_unpublished` / `move_unpublished`) строит `reason=f'moved_from_slot_{source.id}_to_{target.id}'` инлайн.
- **write-site:** `validator backend/src/services/pipeline_reversal.py` (`update_downstream_dates_for_content`, дженерик `:reason`, дефолт `slot_moved`) пишет в `publish_queue.skip_reason`.
- **consumer:** `delivery assign_candidates.js` — `COALESCE(pq.skip_reason,'') LIKE 'moved_from_slot%'` (kill-switch `ASSIGN_REQUEUE_MOVED_ENABLED`).

## Что сделано
1. **Канарейка** (validator `tests/test_schedule_pipeline_reversal.py::test_move_unpublished_updates_dates_not_cancels`): ужесточено `assert 'moved_from_slot' in reason` → `assert reason.startswith('moved_from_slot')` — зеркалит SQL `LIKE`-префикс (не подстрока). Тест читает `reason`, который `move_unpublished` передаёт из прод-литерала → смена текста причины уронит тест.
2. **Комментарии-контракт** в трёх местах: validator `schedule.py` (источник литерала) + `pipeline_reversal.py` (write-site); delivery `assign_candidates.js` (обратная ссылка на валидатор + канарейку). «Менять префикс только координированно».
3. **Починен пред-существующий красный тест** delivery `tests/test_pipeline_guards.test.js` («proceeds with dispatch when slot lineage is valid», красный с 21.05 / WP #125): `checkDispatchQueueSlotLineage` зовёт `slotIsEffectivelyManual` между advisory-lock и slot-check → mock-десинк. Фикс — вставлена недостающая mock-строка `{rows:[],rowCount:0}` (не-manual). Тест-онли.

## Отгрузка
- **validator** PR #23 (`GenGo2/validator-contenthunter`) → origin/main `26e056c`.
- **delivery** PR #113 (`GenGo2/delivery-contenthunter`) → origin/main `3797aea`.
- Прод-деревья синхронизированы `git pull --ff-only origin main`: autowarm `/root/.openclaw/workspace-genri/autowarm` → `3797aea`; validator `/root/.openclaw/workspace-genri/validator` → `26e056c`.
- **PM2 restart НЕ выполнялся** — правки не-рантаймные (тесты+комментарии), running-процессы функционально идентичны; рестарт лишь рискнул бы прервать живые publish-задачи.

## Проверки
- validator канарейка: `1 passed` (по node-id, мокнутая БД — live-PG не трогает).
- delivery `test_pipeline_guards.test.js`: `11/11` (и до, и после merge свежего origin/main в отстававшую на 24 коммита ветку — файлы контракта на origin/main не пересекались, конфликтов нет).
- `codex review` обоих диффов: **0 находок**.

## Контекст процесса
Дизайн+реализация выполнены автоворкером (бриф `contenthunter_autoexec/briefs/162/`, спека одобрена Данилом, codex-clean), но остановились до PR/merge/deploy. Доведено до отгрузки другой сессией: обнаружено через `git log --all | grep wp162` + воркдеревья → сверено с пользователем → verify → codex → push → PR → merge → ff-pull деплой. Чужие основные чекауты/воркдеревья не тронуты.

Спека: `docs/superpowers/specs/2026-05-27-wp162-skip-reason-contract-canary-design.md`. План: `docs/superpowers/plans/2026-05-27-wp162-skip-reason-contract-canary.md`. Память: `project_wp162_skip_reason_contract_canary`.
