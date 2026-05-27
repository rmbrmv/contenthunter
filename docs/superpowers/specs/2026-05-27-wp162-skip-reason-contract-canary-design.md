# WP #162 — Канарейка на кросс-репо контракт `skip_reason='moved_from_slot%'`

**Дата:** 2026-05-27
**Тип:** Задача (харднинг, низкий приоритет). Follow-up к WP #154.
**Репозитории:** `validator-contenthunter`, `delivery-contenthunter` (autowarm).
**Видимость:** нулевая в UI. Чисто инженерная страховка в коде/тестах — никаких экранов, кнопок или настроек ни для админов, ни для пользователей.

## Проблема

После WP #154 популятор delivery снова ставит перенесённый контент в очередь, опознавая
отменённые при переносе слота строки `publish_queue` по `skip_reason LIKE 'moved_from_slot%'`.
Эту формулировку пишет валидатор. Это **негласный кросс-репозиторный контракт**: две программы
живут в разных репо и нигде формально не «договорены». Если кто-то изменит текст причины на
стороне валидатора, delivery **молча** перестанет пере-ставлять перенесённый контент — без падения
тестов и без ошибок в проде (ровно регресс, который был до WP #154).

### Карта контракта (verified против `origin/main` обоих репо, 2026-05-27)

- **Producer (валидатор):** `backend/src/routers/schedule.py:457` строит литерал инлайн:
  `reason=f'moved_from_slot_{source.id}_to_{target.id}'` и передаёт его в
  `update_downstream_dates_for_content(...)`.
- **Запись в колонку (валидатор):** `backend/src/services/pipeline_reversal.py` (функция
  `update_downstream_dates_for_content`, ~стр. 197-208) выполняет
  `UPDATE publish_queue ... skip_reason=:reason` — значение попадает в колонку дословно.
- **Consumer (delivery):** `assign_candidates.js:28` — дедуп-клауза
  `... AND NOT (pq.status = 'cancelled' AND COALESCE(pq.skip_reason,'') LIKE 'moved_from_slot%')`
  с kill-switch `ASSIGN_REQUEUE_MOVED_ENABLED` и комментарием контракта (стр. 17-24).

### Что уже покрыто (во избежание дублирования / YAGNI)

- Валидатор T8 (`backend/tests/test_schedule_pipeline_reversal.py:518`) уже проверяет
  `'moved_from_slot' in uc['reason']` — но через **`in`** (подстрока где угодно), не префикс,
  и только на уровне аргумента вызова.
- Delivery unit-тест (`tests/test_assign_requeue_moved.test.js`) пинит SQL
  `LIKE 'moved_from_slot%'`; live-тест (`test_assign_requeue_moved_live.test.js`) вставляет
  синтетический `moved_from_slot_111_to_222`.

### Фундаментальное ограничение

Тест живёт только в одном репо — **единого артефакта, падающего при рассинхроне двух
репозиториев, не существует**. Поэтому «канарейка» = (а) детерминированная проверка префикса на
одной стороне + (б) громкий cross-repo комментарий, чтобы правка литерала была **осознанным**
контрактным событием, а не рутинным обновлением теста.

## Решение (минимальный вариант — согласован с Данилом)

Три тест-онли / comment-онли поставки. **Без правок прод-логики, без изменений схемы БД.**

### 1. Канарейка (валидатор, тест-онли)

Литерал строится инлайн в `schedule.py:457`, поэтому единственный способ проверить его вывод —
прогнать путь `move_unpublished`, что уже делает T8.

- В `backend/tests/test_schedule_pipeline_reversal.py` **ужесточить** проверку T8
  `'moved_from_slot' in uc['reason']` → `uc['reason'].startswith('moved_from_slot')`.
  Это зеркало delivery-шного `LIKE 'moved_from_slot%'` (префикс).
- Над этой проверкой добавить явный блок-комментарий: `CROSS-REPO CONTRACT CANARY` — со ссылкой на
  `delivery-contenthunter/assign_candidates.js` и пояснением, что менять префикс можно только
  координированно (оба репо + эта канарейка) под угрозой тихого регресса re-queue.

Сознательно **не** вводим named-константу / refactor литерала — это была бы правка прод-логики,
которую бриф просит избегать.

### 2. Контракт-комментарии (бриф: «в обоих местах»)

- `backend/src/routers/schedule.py:457` (producer) — комментарий: префикс `moved_from_slot`
  потребляется кросс-репо delivery'ем; не менять без координации + обновления канарейки.
- `backend/src/services/pipeline_reversal.py` (точка `skip_reason=:reason`) — короткий комментарий,
  что значение уходит наружу в delivery и завязано на контракт.
- `delivery-contenthunter/assign_candidates.js` — комментарий контракта там уже есть; добавить
  одну строку обратной ссылки на `validator schedule.py:457` + на канарейку (двусторонняя ссылка).
  Comment-only.

### 3. Починка пред-существующего красного теста (delivery, тест-онли)

`tests/test_pipeline_guards.test.js`, кейс **«proceeds with dispatch when slot lineage is valid»**
красный с 21.05 (WP #125). Root cause (verified): `checkDispatchQueueSlotLineage` (`server.js:6157`)
после WP #125 вызывает `slotIsEffectivelyManual(client, slotId)` между advisory-lock и проверкой
валидности слота. `slotIsEffectivelyManual` (`client_manual_filter.js:27`) при истинном `slotId`
делает свой `db.query(...)` и возвращает `rows.length > 0`. В тесте `slot_id=5395` (истинный) → этот
запрос съедает mock-результат «слот валиден» (`{rows:[{'?column?':1}],rowCount:1}`) → функция считает
слот manual → уходит в ветку `manual_publish` → возвращает `{skipped:true}` вместо ожидаемого
`{skipped:false, claimed:true}`.

- **Фикс:** вставить в массив `queryResults` этого кейса результат мануал-чека
  `{ rows: [], rowCount: 0 }` («слот не manual») между advisory-lock и результатом проверки слота.
- Прогнать весь файл; применить ту же вставку к соседним `checkDispatchQueueSlotLineage`-кейсам,
  если они страдают тем же десинком (привести файл к зелёному).

## Out of scope

- **Delivery live-тест** на реальные данные БД (`*_live.test.js`, наблюдение реального вывода
  валидатора) — рассмотрен и отклонён: срабатывает только при наличии свежих переносов, как жёсткий
  CI-гейт слабее. Можно добавить позже отдельной задачей при желании defense-in-depth.
- Любые правки прод-логики, named-константы, изменения схемы БД.
- UI — задача его не касается.

## Доставка и проверка

- **Два PR** (репозитории разные):
  - `validator-contenthunter`: секции 1 + 2 (валидаторная часть).
  - `delivery-contenthunter`: секция 2 (delivery-комментарий) + секция 3 (фикс красного теста).
- Оба репо — **общие чекауты**: работа строго через `git worktree add` от свежего `origin/main`,
  никогда `checkout -b`; гард-проверка `git branch --show-current` перед каждым коммитом; без
  `--amend` на shared HEAD; без force-push.
- **Проверка:**
  - Валидатор: `pytest backend/tests/test_schedule_pipeline_reversal.py` (бьёт по реальной БД —
    `conftest.py` autouse-dispose). Показать прогон до/после.
  - Delivery: `node --test tests/test_pipeline_guards.test.js` + `node --test tests/` — показать
    красный→зелёный.
- **Codex review** спеки и плана перед передачей Данилу (стандартная практика проекта).

## Риски

- **Низкие.** Изменения тест-онли + комментарии. Нет прод-логики, нет схемы, нет UI.
- Кросс-репозиторность → два PR; ловушка branch-chaos общего чекаута снимается worktree-дисциплиной.
- Канарейка не даёт абсолютной гарантии (единого cross-repo теста нет) — но переводит тихий
  регресс в громкий, осознанный контрактный шаг. Это и есть цель харднинга.
