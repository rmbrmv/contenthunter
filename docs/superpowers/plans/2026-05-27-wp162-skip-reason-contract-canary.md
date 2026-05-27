# WP #162 — Канарейка на контракт `skip_reason='moved_from_slot%'` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести тихий кросс-репо регресс контракта `skip_reason` в громкую тест-ошибку: ужесточить валидаторную проверку префикса, зафиксировать контракт комментариями в обоих репо и починить пред-существующий красный тест в delivery.

**Architecture:** Тест-онли + комментарии, без правок прод-логики/схемы/UI. Producer — `validator` (`schedule.py` строит литерал, `pipeline_reversal.py` пишет в `publish_queue.skip_reason`); consumer — `delivery` (`assign_candidates.js`, `LIKE 'moved_from_slot%'`). Единого cross-repo теста не существует, поэтому защита = детерминированная проверка префикса на стороне producer + громкие контракт-комментарии. Два PR (разные репозитории).

**Tech Stack:** Python/pytest (validator, тесты по реальной БД через `backend/tests/conftest.py` autouse-dispose), Node.js встроенный `node --test` (delivery), git worktrees.

**Spec:** `docs/superpowers/plans/../specs/2026-05-27-wp162-skip-reason-contract-canary-design.md`

---

## File Structure

**Репозиторий `validator-contenthunter` (worktree от `origin/main`):**
- Modify: `backend/tests/test_schedule_pipeline_reversal.py` — ужесточить проверку T8 (`in` → `startswith`) + CROSS-REPO CONTRACT CANARY-комментарий.
- Modify: `backend/src/routers/schedule.py` (~строка 457) — контракт-комментарий над `reason=f'moved_from_slot_...'`.
- Modify: `backend/src/services/pipeline_reversal.py` (~строка 197) — контракт-комментарий над `skip_reason=:reason`.

**Репозиторий `delivery-contenthunter` / autowarm (worktree от `origin/main`):**
- Modify: `tests/test_pipeline_guards.test.js` — вставить mock-результат `slotIsEffectivelyManual` в красный кейс.
- Modify: `assign_candidates.js` (~строки 17-24) — одна строка обратной ссылки на producer + канарейку.

---

## Часть A — Валидатор (`validator-contenthunter`)

### Task A0: Создать worktree валидатора от свежего origin/main

**Files:** none (git setup)

- [ ] **Step 1: Подтянуть origin и создать worktree**

```bash
git -C /home/claude-user/validator-contenthunter fetch origin --quiet
git -C /home/claude-user/validator-contenthunter worktree add -b wp162-skip-reason-canary \
  /home/claude-user/validator-contenthunter-wp162-skip-reason-canary origin/main
```

- [ ] **Step 2: Гард-проверка ветки (дисциплина общего чекаута)**

Run: `git -C /home/claude-user/validator-contenthunter-wp162-skip-reason-canary branch --show-current`
Expected: `wp162-skip-reason-canary`

- [ ] **Step 3: Pre-flight — нет ли auto-push post-commit hook**

Run:
```bash
cd /home/claude-user/validator-contenthunter-wp162-skip-reason-canary
ls .git/hooks/post-commit 2>/dev/null; git config --get core.hooksPath
```
Expected: пусто (если hook есть — НЕ коммитить до выяснения; auto-push в прод недопустим).

---

### Task A1: Канарейка — ужесточить проверку префикса T8

**Files:**
- Test: `backend/tests/test_schedule_pipeline_reversal.py` (тест `test_move_unpublished_updates_dates_not_cancels`, проверка ~строка 518)

- [ ] **Step 1: Baseline — прогнать T8, убедиться что зелёный с текущим `in`**

Run (из worktree валидатора):
```bash
cd /home/claude-user/validator-contenthunter-wp162-skip-reason-canary/backend
python -m pytest tests/test_schedule_pipeline_reversal.py::test_move_unpublished_updates_dates_not_cancels -v
```
Expected: PASS (1 passed). *(Если pytest не находит зависимости/БД — активировать venv репо и выставить тестовый DSN как для прочих live-DB тестов валидатора.)*

- [ ] **Step 2: Ужесточить проверку + добавить CONTRACT CANARY-комментарий**

Заменить строку:
```python
    assert 'moved_from_slot' in uc['reason']
```
на:
```python
    # CROSS-REPO CONTRACT CANARY (WP #162, follow-up #154):
    # delivery-contenthunter/assign_candidates.js пере-ставит перенесённый контент по
    # `skip_reason LIKE 'moved_from_slot%'`. Префикс ниже ОБЯЗАН совпадать с тем LIKE.
    # Менять текст причины можно ТОЛЬКО координированно: validator schedule.py:~457
    # (источник литерала) + delivery assign_candidates.js + этот тест — иначе delivery
    # МОЛЧА перестанет re-queue (тихий регресс, как до #154). startswith зеркалит LIKE-префикс.
    assert uc['reason'].startswith('moved_from_slot')
```

- [ ] **Step 3: Прогнать T8 — всё ещё зелёный (код уже даёт `moved_from_slot_...`)**

Run:
```bash
python -m pytest tests/test_schedule_pipeline_reversal.py::test_move_unpublished_updates_dates_not_cancels -v
```
Expected: PASS.

- [ ] **Step 4: Mutation-check — доказать, что канарейка ловит дрейф**

Временно изменить литерал в `backend/src/routers/schedule.py` (`reason=f'moved_from_slot_{source.id}_to_{target.id}'` → `reason=f'relocated_from_slot_{source.id}_to_{target.id}'`), затем:
```bash
python -m pytest tests/test_schedule_pipeline_reversal.py::test_move_unpublished_updates_dates_not_cancels -v
```
Expected: **FAIL** на `assert uc['reason'].startswith('moved_from_slot')`.
Затем **откатить** мутацию литерала:
```bash
git -C /home/claude-user/validator-contenthunter-wp162-skip-reason-canary checkout -- backend/src/routers/schedule.py
```
Re-run теста → снова PASS. *(Этот шаг — реальное доказательство, что канарейка не «вечнозелёная».)*

- [ ] **Step 5: Прогнать весь файл (регрессий нет)**

Run: `python -m pytest tests/test_schedule_pipeline_reversal.py -v`
Expected: все PASS (как на baseline; число тестов не уменьшилось).

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/validator-contenthunter-wp162-skip-reason-canary
git branch --show-current   # guard: must print wp162-skip-reason-canary
git add backend/tests/test_schedule_pipeline_reversal.py
git commit -m "test(wp162): канарейка — skip_reason при переносе startswith moved_from_slot (cross-repo контракт)"
```

---

### Task A2: Контракт-комментарии в producer и write-site

**Files:**
- Modify: `backend/src/routers/schedule.py` (~строка 457)
- Modify: `backend/src/services/pipeline_reversal.py` (~строка 197)

- [ ] **Step 1: Комментарий в `schedule.py` над построением литерала**

Найти блок (точный текст):
```python
        stats = await update_downstream_dates_for_content(
            db, moved_content_id,
            new_slot_id=target.id,
            new_slot_date=target.slot_date,
            reason=f'moved_from_slot_{source.id}_to_{target.id}',
        )
```
Вставить комментарий непосредственно над строкой `reason=...`:
```python
            # CROSS-REPO CONTRACT (WP #154/#162): этот префикс читает
            # delivery-contenthunter/assign_candidates.js по `skip_reason LIKE 'moved_from_slot%'`,
            # чтобы пере-ставить перенесённый контент в очередь. НЕ менять текст без
            # координации (delivery + канарейка test_schedule_pipeline_reversal.py) —
            # иначе delivery молча перестанет re-queue.
            reason=f'moved_from_slot_{source.id}_to_{target.id}',
```

- [ ] **Step 2: Комментарий в `pipeline_reversal.py` над записью в колонку**

Найти блок (внутри `update_downstream_dates_for_content`):
```python
    pq_result = await db.execute(text("""
        UPDATE publish_queue pq
        SET status='cancelled',
            skip_reason=:reason,
```
Вставить комментарий над `pq_result = await db.execute(text("""`:
```python
    # CROSS-REPO CONTRACT (WP #154/#162): `:reason` уходит в publish_queue.skip_reason и
    # читается delivery-contenthunter/assign_candidates.js (`LIKE 'moved_from_slot%'`).
    # Для move-пути значение формирует schedule.py (`moved_from_slot_<src>_to_<dst>`).
    pq_result = await db.execute(text("""
        UPDATE publish_queue pq
        SET status='cancelled',
            skip_reason=:reason,
```

- [ ] **Step 3: Прогнать тесты — комментарии ничего не ломают**

Run:
```bash
cd /home/claude-user/validator-contenthunter-wp162-skip-reason-canary/backend
python -m pytest tests/test_schedule_pipeline_reversal.py tests/test_pipeline_reversal.py -v
```
Expected: все PASS (поведение не изменилось — только комментарии).

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/validator-contenthunter-wp162-skip-reason-canary
git branch --show-current   # guard
git add backend/src/routers/schedule.py backend/src/services/pipeline_reversal.py
git commit -m "docs(wp162): контракт-комментарии skip_reason moved_from_slot% (producer + write-site)"
```

---

### Task A3: Codex review + PR валидатора

- [ ] **Step 1: Codex review диффа ветки**

Run:
```bash
cd /home/claude-user/validator-contenthunter-wp162-skip-reason-canary
git diff origin/main...HEAD | ~/.local/bin/codex review -
```
Expected: 0 P1. Разобрать замечания раундами до 0 P1; bubblewrap-warning игнорировать.

- [ ] **Step 2: Push + PR (после отмашки Данила — см. Execution Handoff)**

```bash
git push -u origin wp162-skip-reason-canary
gh pr create --repo GenGo2/validator-contenthunter --base main --head wp162-skip-reason-canary \
  --title "WP #162: канарейка на контракт skip_reason moved_from_slot% + контракт-комменты" \
  --body "Follow-up #154. Тест-онли + комментарии. Ужесточена проверка префикса (in→startswith) с пометкой CROSS-REPO CONTRACT CANARY; контракт-комменты в schedule.py (producer) и pipeline_reversal.py (write-site). Без прод-логики/схемы/UI."
```
NB: использовать токен `GenGo2` (`~/secrets/github-gengo2.env`). Без force-push.

---

## Часть B — Delivery / autowarm (`delivery-contenthunter`)

### Task B0: Создать worktree delivery от свежего origin/main

**Files:** none (git setup)

- [ ] **Step 1: Подтянуть origin и создать worktree**

```bash
git -C /home/claude-user/autowarm-testbench fetch origin --quiet
git -C /home/claude-user/autowarm-testbench worktree add -b wp162-skip-reason-canary \
  /home/claude-user/autowarm-testbench-wp162-skip-reason-canary origin/main
```

- [ ] **Step 2: Гард-проверка ветки**

Run: `git -C /home/claude-user/autowarm-testbench-wp162-skip-reason-canary branch --show-current`
Expected: `wp162-skip-reason-canary`

- [ ] **Step 3: Pre-flight — НЕТ auto-push post-commit hook (критично!)**

Run:
```bash
cd /home/claude-user/autowarm-testbench-wp162-skip-reason-canary
ls .git/hooks/post-commit 2>/dev/null; git config --get core.hooksPath
```
Expected: пусто. *(У прод-чекаута autowarm есть post-commit→GenGo2 auto-push; убедиться, что в этом dev-worktree его НЕТ, иначе коммит уедет в прод. Если есть — обезвредить/не коммитить до выяснения.)*

---

### Task B1: Починить красный `test_pipeline_guards.test.js`

**Files:**
- Test: `tests/test_pipeline_guards.test.js` (кейс «proceeds with dispatch when slot lineage is valid»)

- [ ] **Step 1: Подтвердить красный (RED)**

Run:
```bash
cd /home/claude-user/autowarm-testbench-wp162-skip-reason-canary
node --test tests/test_pipeline_guards.test.js 2>&1 | tail -30
```
Expected: FAIL в кейсе «proceeds with dispatch when slot lineage is valid» (получает `skipped:true` / `manual_publish` вместо `claimed:true`). Зафиксировать, какие ещё `checkDispatchQueueSlotLineage`-кейсы красные.

- [ ] **Step 2: Вставить mock-результат `slotIsEffectivelyManual` (не-manual)**

В этом кейсе найти массив (точный текст):
```javascript
    const client = makeMockClient([
      { rows: [], rowCount: 0 },   // BEGIN
      // unic_task lookup
      { rows: [{ meta: { slot_id: 5395 }, content_id: 2022, slot_date: '2026-05-15' }], rowCount: 1 },
      { rows: [], rowCount: 0 },   // advisory lock
      // slot check → valid (1 row)
      { rows: [{ '?column?': 1 }], rowCount: 1 },
      // pending→running claim
      { rows: [{ id: 88 }], rowCount: 1 },
      { rows: [], rowCount: 0 },   // COMMIT
    ]);
```
Вставить между «advisory lock» и «slot check» результат мануал-чека:
```javascript
    const client = makeMockClient([
      { rows: [], rowCount: 0 },   // BEGIN
      // unic_task lookup
      { rows: [{ meta: { slot_id: 5395 }, content_id: 2022, slot_date: '2026-05-15' }], rowCount: 1 },
      { rows: [], rowCount: 0 },   // advisory lock
      // WP #125: slotIsEffectivelyManual(client, slotId) — slot_id truthy → запрос выполняется
      { rows: [], rowCount: 0 },   // slotIsEffectivelyManual → НЕ manual (rows.length === 0)
      // slot check → valid (1 row)
      { rows: [{ '?column?': 1 }], rowCount: 1 },
      // pending→running claim
      { rows: [{ id: 88 }], rowCount: 1 },
      { rows: [], rowCount: 0 },   // COMMIT
    ]);
```

- [ ] **Step 3: Прогнать кейс — GREEN**

Run: `node --test tests/test_pipeline_guards.test.js 2>&1 | tail -30`
Expected: кейс «proceeds with dispatch when slot lineage is valid» PASS.

- [ ] **Step 4: Добить соседние десинк-кейсы (если красные из Step 1)**

Для каждого ещё красного `checkDispatchQueueSlotLineage`-кейса с истинным `meta.slot_id`: вставить такой же `{ rows: [], rowCount: 0 }  // slotIsEffectivelyManual → НЕ manual` между advisory-lock и slot-check (легаси-кейсы без `slot_id` не трогать — там ранний возврат до мануал-чека). Re-run после каждой правки.

- [ ] **Step 5: Весь файл зелёный**

Run: `node --test tests/test_pipeline_guards.test.js 2>&1 | tail -15`
Expected: 0 fail. *(Live-тесты `*_live.test.js` лежат в корне, не в `tests/` — этот прогон их не трогает.)*

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-testbench-wp162-skip-reason-canary
git branch --show-current   # guard
git add tests/test_pipeline_guards.test.js
git commit -m "test(wp162): починить mock-десинк test_pipeline_guards (slotIsEffectivelyManual, WP #125)"
```

---

### Task B2: Обратная ссылка контракта в `assign_candidates.js`

**Files:**
- Modify: `assign_candidates.js` (комментарий-блок ~строки 17-24)

- [ ] **Step 1: Добавить одну строку обратной ссылки на producer + канарейку**

В существующем комментарий-блоке над дедуп-клаузой (рядом со строкой, поясняющей `moved_from_slot%`) добавить:
```javascript
// CROSS-REPO CONTRACT (WP #154/#162): префикс 'moved_from_slot' формирует валидатор —
// validator-contenthunter/backend/src/routers/schedule.py (move_unpublished, ~стр.457),
// пишет в publish_queue.skip_reason через pipeline_reversal.py. Канарейка на стороне
// валидатора: test_schedule_pipeline_reversal.py (startswith 'moved_from_slot').
// Менять текст причины только координированно с валидатором.
```

- [ ] **Step 2: Прогнать связанные тесты — ничего не сломано**

Run:
```bash
cd /home/claude-user/autowarm-testbench-wp162-skip-reason-canary
node --test tests/test_assign_requeue_moved.test.js tests/test_pipeline_guards.test.js 2>&1 | tail -15
```
Expected: 0 fail (правка — только комментарий).

- [ ] **Step 3: Commit**

```bash
git branch --show-current   # guard
git add assign_candidates.js
git commit -m "docs(wp162): обратная ссылка контракта skip_reason на валидатор + канарейку"
```

---

### Task B3: Codex review + PR delivery

- [ ] **Step 1: Codex review диффа ветки**

Run:
```bash
cd /home/claude-user/autowarm-testbench-wp162-skip-reason-canary
git diff origin/main...HEAD | ~/.local/bin/codex review -
```
Expected: 0 P1; раундами до 0 P1.

- [ ] **Step 2: Push + PR (после отмашки Данила)**

```bash
git push -u origin wp162-skip-reason-canary
gh pr create --repo GenGo2/delivery-contenthunter --base main --head wp162-skip-reason-canary \
  --title "WP #162: фикс красного test_pipeline_guards + обратная ссылка контракта skip_reason" \
  --body "Follow-up #154. Тест-онли + комментарий. Починен mock-десинк test_pipeline_guards.test.js (slotIsEffectivelyManual, WP #125); добавлена обратная ссылка контракта в assign_candidates.js. Без прод-логики/схемы."
```
NB: токен `GenGo2`. Без force-push.

---

## Финал

- [ ] **Обновить OpenProject #162** в house-style (Что было не так → Что сделано → Что осталось, без футера): описать оба PR, статус → «Тестирование» после мёрджа (по решению Данила).
- [ ] **Обновить память** `project_wp162_skip_reason_contract_canary.md` (SHIPPED + ссылки на PR/коммиты).

---

## Self-Review (выполнено при написании плана)

1. **Покрытие спеки:**
   - Секция 1 (канарейка) → Task A1. ✓
   - Секция 2 (комменты обоих репо) → Task A2 (validator ×2) + Task B2 (delivery back-ref). ✓
   - Секция 3 (красный тест) → Task B1. ✓
   - Доставка/проверка (2 PR, worktree-дисциплина, прогоны) → A0/B0 pre-flight, A3/B3 PR. ✓
   - Out of scope (delivery live-тест, константы, прод-логика, схема, UI) — нигде не добавлены. ✓
2. **Плейсхолдеры:** нет TBD/TODO; все шаги с конкретным кодом/командами/ожидаемым выводом.
3. **Type/anchor consistency:** имена `uc['reason']`, `startswith`, `slotIsEffectivelyManual`, `{rows:[],rowCount:0}`, ветка `wp162-skip-reason-canary`, токен `GenGo2` — единообразны во всех задачах. Точные тексты-якоря для замен взяты дословно из `origin/main`.
