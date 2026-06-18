# WP#167 — Синхронизация авто/ручной выкладки (админка ↔ карточка планировщика) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бейдж 🤖авто/👋вручную на карточке планировщика берёт режим из конфигурации (`slot.manual_publish OR project.manual_publish`), а не из факта исполнения — полная синхронность с админкой валидатора.

**Architecture:** Все правки в репозитории `delivery-contenthunter` (autowarm-дашборд). Новый чистый JS-хелпер `isEffectivelyManual` в `client_manual_filter.js` (единый источник истины, зеркало `effectiveManualSql`, уважает kill-switch `CLIENT_MANUAL_PUBLISH_ENABLED`). Три ветки построения карточек в `publish_planner.js` читают флаги слота/проекта и вычисляют `mode` через хелпер. Поведение под новый kill-switch `PLANNER_MODE_FROM_CONFIG_ENABLED` (дефолт ON). Фронтенд и БД не трогаем.

**Tech Stack:** Node.js, `node:test` + `node:assert`, PostgreSQL (`pg` Pool), Express. Тест-раннер: `node --test --test-force-exit tests/*.test.js`.

**Рабочее окружение:** изолированный git worktree от `delivery-contenthunter` (создаётся через superpowers:using-git-worktrees перед исполнением), отдельная ветка, чтобы не мешать параллельным сессиям на общем прод-чекауте `/root/.openclaw/workspace-genri/autowarm`.

**Контекст кода (на момент написания плана):**
- `client_manual_filter.js` — `clientManualEnabled()`, `effectiveManualSql(slotAlias, projAlias)`, `slotIsEffectivelyManual(db, slotId)`.
- `publish_planner.js`:
  - `getPlannerCards(pool, {from,to,projectIds,trustQueueStatus})` — full-запрос (≈153), degradation-ветка (≈222), плановые карточки `prows` (≈254).
  - `buildPlannerCards(intents, opts)` — основная логика, `mode` на ≈стр. 92.
- Канонический тест: `tests/publish_planner.test.js` (12 passed baseline). Легаси-дубль `./test_publish_planner.test.js` НЕ трогаем (не в раннере).

---

## File Structure

- **Modify** `client_manual_filter.js` — добавить `isEffectivelyManual({slotManual, projectManual})`, добавить в `module.exports`.
- **Create** `tests/client_manual_filter.test.js` — юнит-тесты хелпера.
- **Modify** `publish_planner.js` — `plannerModeFromConfigEnabled()`, проброс флагов в 3 ветках, `mode` из конфигурации, `module.exports`.
- **Modify** `tests/publish_planner.test.js` — обновить семантику существующего теста handoff, добавить тесты конфиг-режима и kill-switch.

---

## Task 1: Хелпер `isEffectivelyManual` в client_manual_filter.js

**Files:**
- Create: `tests/client_manual_filter.test.js`
- Modify: `client_manual_filter.js`

- [ ] **Step 1: Write the failing test**

Создать `tests/client_manual_filter.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const { isEffectivelyManual } = require('../client_manual_filter.js');

test('isEffectivelyManual: project-manual → true', () => {
  assert.strictEqual(isEffectivelyManual({ slotManual: false, projectManual: true }), true);
});

test('isEffectivelyManual: slot-manual → true', () => {
  assert.strictEqual(isEffectivelyManual({ slotManual: true, projectManual: false }), true);
});

test('isEffectivelyManual: оба false → false', () => {
  assert.strictEqual(isEffectivelyManual({ slotManual: false, projectManual: false }), false);
});

test('isEffectivelyManual: null/undefined → false', () => {
  assert.strictEqual(isEffectivelyManual({ slotManual: null, projectManual: undefined }), false);
});

test('isEffectivelyManual: CLIENT_MANUAL_PUBLISH_ENABLED=false → учитывается только слот', () => {
  const prev = process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
  process.env.CLIENT_MANUAL_PUBLISH_ENABLED = 'false';
  try {
    assert.strictEqual(isEffectivelyManual({ slotManual: false, projectManual: true }), false);
    assert.strictEqual(isEffectivelyManual({ slotManual: true, projectManual: false }), true);
  } finally {
    if (prev === undefined) delete process.env.CLIENT_MANUAL_PUBLISH_ENABLED;
    else process.env.CLIENT_MANUAL_PUBLISH_ENABLED = prev;
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test --test-force-exit tests/client_manual_filter.test.js`
Expected: FAIL — `isEffectivelyManual is not a function`.

- [ ] **Step 3: Write minimal implementation**

В `client_manual_filter.js` добавить функцию перед `module.exports`:

```js
// WP#167: значение-предикат, зеркало effectiveManualSql для использования вне SQL
// (карточка планировщика). Уважает тот же kill-switch CLIENT_MANUAL_PUBLISH_ENABLED.
function isEffectivelyManual({ slotManual, projectManual }) {
  if (clientManualEnabled()) return !!slotManual || !!projectManual;
  return !!slotManual;
}
```

И обновить экспорт:

```js
module.exports = { clientManualEnabled, effectiveManualSql, slotIsEffectivelyManual, isEffectivelyManual };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test --test-force-exit tests/client_manual_filter.test.js`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add client_manual_filter.js tests/client_manual_filter.test.js
git commit -m "feat(wp167): isEffectivelyManual — значение-предикат режима выкладки"
```

---

## Task 2: `buildPlannerCards` — mode из конфигурации (основная ветка)

**Files:**
- Modify: `publish_planner.js` (импорт хелпера; `plannerModeFromConfigEnabled()`; `mode` ≈стр. 92)
- Modify: `tests/publish_planner.test.js` (обновить handoff-тест; добавить конфиг-тесты)

- [ ] **Step 1: Write the failing tests**

В `tests/publish_planner.test.js` **заменить** существующий тест (строки ≈99-103):

```js
test('синтез с manual_handoff_date → mode=manual', () => {
  const cards = buildPlannerCards([intent({
    queue_status: 'published', manual_handoff_date: '2026-05-22',
  })], WIN);
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').mode, 'manual');
});
```

на новую семантику (WP#167: handoff показывает маркер auto_handoff, а не бейдж mode):

```js
test('WP#167: handoff без конфиг-флага → mode=auto, но auto_handoff=true', () => {
  const cards = buildPlannerCards([intent({
    queue_status: 'published', manual_handoff_date: '2026-05-22',
  })], WIN);
  const c = cardOn(cards, 'slot:1', '2026-05-22');
  assert.strictEqual(c.mode, 'auto');
  assert.strictEqual(c.auto_handoff, true);
});
```

И **добавить** после него новые тесты конфиг-режима:

```js
test('WP#167: project_manual=true → mode=manual независимо от исполнения', () => {
  const cards = buildPlannerCards([intent({
    queue_status: 'done', project_manual: true,
    attempts: [{ date: '2026-05-22', status: 'done', error_code: null, via_manual: false }],
  })], WIN);
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').mode, 'manual');
});

test('WP#167: slot_manual=true → mode=manual', () => {
  const cards = buildPlannerCards([intent({
    queue_status: 'done', slot_manual: true,
  })], WIN);
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').mode, 'manual');
});

test('WP#167: оба флага false → mode=auto', () => {
  const cards = buildPlannerCards([intent({ queue_status: 'done' })], WIN);
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').mode, 'auto');
});

test('WP#167: modeFromConfig=false → старое поведение (via_manual)', () => {
  const cards = buildPlannerCards([intent({
    queue_status: 'published', manual_handoff_date: '2026-05-22',
  })], { ...WIN, modeFromConfig: false });
  assert.strictEqual(cardOn(cards, 'slot:1', '2026-05-22').mode, 'manual');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: FAIL — новый handoff-тест ждёт `mode='auto'`, но текущий код даёт `'manual'`; конфиг-тесты ждут `'manual'`, код даёт `'auto'`.

- [ ] **Step 3: Write minimal implementation**

В `publish_planner.js` вверху файла (рядом с прочими require) добавить импорт и хелпер kill-switch:

```js
const { isEffectivelyManual } = require('./client_manual_filter');

// WP#167: kill-switch — mode карточки из конфигурации (slot/project manual_publish).
// OFF → прежнее поведение (via_manual в основной ветке, хардкод auto в плановых/degradation).
function plannerModeFromConfigEnabled() {
  return process.env.PLANNER_MODE_FROM_CONFIG_ENABLED !== 'false';
}
```

В `buildPlannerCards` после строки `const trustQueueStatus = opts.trustQueueStatus !== false;` добавить:

```js
  const modeFromConfig = opts.modeFromConfig !== false; // WP#167: дефолт ON
```

Заменить строку `mode: todayManual ? 'manual' : 'auto',` (≈стр. 92) на:

```js
        mode: modeFromConfig
          ? (isEffectivelyManual({ slotManual: meta.slot_manual, projectManual: meta.project_manual }) ? 'manual' : 'auto')
          : (todayManual ? 'manual' : 'auto'),
```

(`meta = group[0]` — конфиг-флаги одинаковы в цепочке; intent в тестах задаёт их напрямую, в проде их проставит Task 3.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: PASS — все тесты (включая прежние 11 + новые).

- [ ] **Step 5: Commit**

```bash
git add publish_planner.js tests/publish_planner.test.js
git commit -m "feat(wp167): buildPlannerCards — mode из конфигурации + kill-switch"
```

---

## Task 3: full-ветка getPlannerCards — выборка флагов слота/проекта

**Files:**
- Modify: `publish_planner.js` (full-запрос ≈153-171; map intents ≈204-218; вызов buildPlannerCards ≈219)
- Modify: `tests/publish_planner.test.js` (mock-pool тест конфиг-режима)

- [ ] **Step 1: Write the failing test**

В `tests/publish_planner.test.js` добавить после блока getPlannerCards-тестов:

```js
test('WP#167 getPlannerCards full: project_manual из строки → mode=manual', async () => {
  const pool = makeMockPool([
    { match: /information_schema\.columns/, rows: [{ ok: 1 }] },
    { match: /client_publish_id::text AS intent_id/, rows: [
      { queue_id: 1, intent_id: 'i1', account_username: 'a1', platform: 'youtube',
        project_id: 100, project_name: 'Feminista', video_title: 'V', chain_id: 'slot:7',
        scheduled_date: '2026-05-22', manual_handoff_date: null, queue_status: 'done',
        slot_manual: false, project_manual: true },
    ] },
    { match: /FROM\s+publish_tasks/, rows: [] },
    { match: /validator_manual_publish_queue/, rows: [] },
  ]);
  const cards = await getPlannerCards(pool, { from: '2026-05-18', to: '2026-05-24' });
  const c = cards.find(x => x.chain_id === 'slot:7' && x.business_date === '2026-05-22');
  assert.ok(c, 'карточка slot:7 есть');
  assert.strictEqual(c.mode, 'manual');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: FAIL — `mode='auto'` (full-запрос ещё не выбирает slot_manual/project_manual, map их не пробрасывает).

- [ ] **Step 3: Write minimal implementation**

В `publish_planner.js`, full-запрос `getPlannerCards`. В список SELECT (после `manual_handoff_date`-строки) добавить:

```sql
             COALESCE(vss.manual_publish, false)                 AS slot_manual,
             COALESCE(vp.manual_publish, vp2.manual_publish, false) AS project_manual,
```

В блок JOIN-ов (после `LEFT JOIN validator_projects vp2 ON vp2.id = ut.project_id`) добавить:

```sql
      LEFT JOIN validator_schedule_slots vss ON vss.id = NULLIF(ut.meta->>'slot_id','')::int
```

В map intents (объект, возвращаемый `qrows.map(r => {...})`, ≈стр. 211-217) добавить поля:

```js
        slot_manual: r.slot_manual, project_manual: r.project_manual,
```

В вызов `buildPlannerCards(intents, { from, to, trustQueueStatus })` (≈стр. 219) добавить флаг:

```js
    cards.push(...buildPlannerCards(intents, { from, to, trustQueueStatus, modeFromConfig: plannerModeFromConfigEnabled() }));
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: PASS — новый full-тест зелёный, прежние не сломаны (slot_manual/project_manual в их mock-строках undefined → false → mode='auto', что соответствует их ожиданиям).

- [ ] **Step 5: Commit**

```bash
git add publish_planner.js tests/publish_planner.test.js
git commit -m "feat(wp167): full-ветка планировщика читает manual_publish слота/проекта"
```

---

## Task 4: degradation-ветка getPlannerCards — флаги из конфигурации

**Files:**
- Modify: `publish_planner.js` (degradation-запрос ≈222-238; объект push ≈241-249)
- Modify: `tests/publish_planner.test.js` (mock-pool degradation-тест)

- [ ] **Step 1: Write the failing test**

В `tests/publish_planner.test.js` добавить:

```js
test('WP#167 getPlannerCards degradation: project_manual → mode=manual', async () => {
  // hasColumn → false (нет колонок WP#108) → degradation-ветка
  const pool = makeMockPool([
    { match: /information_schema\.columns/, rows: [] },
    { match: /COUNT\(\*\) FILTER \(WHERE pq\.status IN/, rows: [
      { chain_id: 'task:5', project_id: 100, project_name: 'Feminista', video_title: 'V',
        code_number: null, code_prefix: 'FEM', business_date: '2026-05-22',
        total_accounts: 2, done_count: 2, slot_manual: false, project_manual: true },
    ] },
  ]);
  const cards = await getPlannerCards(pool, { from: '2026-05-18', to: '2026-05-24' });
  const c = cards.find(x => x.chain_id === 'task:5' && x.business_date === '2026-05-22');
  assert.ok(c, 'карточка task:5 есть');
  assert.strictEqual(c.mode, 'manual');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: FAIL — `mode='auto'` (degradation-ветка хардкодит auto и не выбирает флаги).

- [ ] **Step 3: Write minimal implementation**

В `publish_planner.js`, degradation-запрос. В SELECT (после `done_count`-строки) добавить:

```sql
             bool_or(COALESCE(vss.manual_publish, false))                   AS slot_manual,
             bool_or(COALESCE(vp.manual_publish, vp2.manual_publish, false)) AS project_manual
```

В JOIN-ы (после `LEFT JOIN validator_projects vp2 ON vp2.id = ut.project_id`) добавить:

```sql
      LEFT JOIN validator_schedule_slots vss ON vss.id = NULLIF(ut.meta->>'slot_id','')::int
```

(`bool_or` — агрегат, GROUP BY расширять не нужно: `slot_manual`/`project_manual` агрегируются по группе.)

В объекте `cards.push({...})` degradation-ветки заменить `state: done === N ? 'published' : 'partial', mode: 'auto',` на:

```js
        state: done === N ? 'published' : 'partial',
        mode: plannerModeFromConfigEnabled()
          ? (isEffectivelyManual({ slotManual: r.slot_manual, projectManual: r.project_manual }) ? 'manual' : 'auto')
          : 'auto',
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publish_planner.js tests/publish_planner.test.js
git commit -m "feat(wp167): degradation-ветка планировщика — mode из конфигурации"
```

---

## Task 5: плановые карточки (prows) — флаги из конфигурации

**Files:**
- Modify: `publish_planner.js` (плановый запрос ≈254-273; объект push ≈275-283)
- Modify: `tests/publish_planner.test.js` (mock-pool тест плановой карточки)

- [ ] **Step 1: Write the failing test**

В `tests/publish_planner.test.js` добавить (кейс Feminista — будущий плановый слот):

```js
test('WP#167 getPlannerCards планово: project_manual → плановая карточка mode=manual', async () => {
  const pool = makeMockPool([
    { match: /information_schema\.columns/, rows: [{ ok: 1 }] }, // full-путь, но full-запрос пуст
    { match: /client_publish_id::text AS intent_id/, rows: [] },
    { match: /FROM\s+publish_tasks/, rows: [] },
    { match: /validator_manual_publish_queue/, rows: [] },
    // плановый запрос (есть content_status + slot_date)
    { match: /vc\.status AS content_status/, rows: [
      { project_id: 100, project_name: 'Feminista', video_title: 'V',
        code_number: 1, code_prefix: 'FEM', business_date: '2026-05-23',
        content_status: 'approved', chain_id: 'slot:9',
        slot_manual: false, project_manual: true },
    ] },
  ]);
  const cards = await getPlannerCards(pool, { from: '2026-05-18', to: '2026-05-24' });
  const c = cards.find(x => x.chain_id === 'slot:9' && x.business_date === '2026-05-23');
  assert.ok(c, 'плановая карточка slot:9 есть');
  assert.strictEqual(c.mode, 'manual');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: FAIL — `mode='auto'` (плановая ветка хардкодит auto).

- [ ] **Step 3: Write minimal implementation**

В `publish_planner.js`, плановый запрос `prows`. В SELECT (после `vc.code_number, vp.code_prefix,`-строки) добавить:

```sql
           COALESCE(s.manual_publish, false) AS slot_manual,
           COALESCE(vp.manual_publish, false) AS project_manual,
```

(Запрос уже джойнит `validator_schedule_slots s` и `validator_projects vp` — новые JOIN не нужны.)

В объекте `cards.push({...})` плановой ветки заменить `state: mapContentState(r.content_status), mode: 'auto',` на:

```js
      state: mapContentState(r.content_status),
      mode: plannerModeFromConfigEnabled()
        ? (isEffectivelyManual({ slotManual: r.slot_manual, projectManual: r.project_manual }) ? 'manual' : 'auto')
        : 'auto',
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test --test-force-exit tests/publish_planner.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publish_planner.js tests/publish_planner.test.js
git commit -m "feat(wp167): плановые карточки планировщика — mode из конфигурации"
```

---

## Task 6: Регрессия и финальная проверка

**Files:** (только запуск)

- [ ] **Step 1: Полная регрессия планировщика**

Run: `node --test --test-force-exit tests/publish_planner.test.js tests/client_manual_filter.test.js`
Expected: PASS, 0 fail (12 прежних + новые).

- [ ] **Step 2: Прогон затронутых смежных наборов**

Run: `node --test --test-force-exit tests/test_pipeline_funnel.test.js 2>/dev/null; node --test --test-force-exit tests/*manual*.test.js`
Expected: PASS или предсуществующие фейлы без отношения к WP#167 (зафиксировать, если есть).

- [ ] **Step 3: Sanity grep — нет осиротевших хардкодов mode='auto'**

Run: `grep -n "mode: 'auto'" publish_planner.js`
Expected: совпадения остаются ТОЛЬКО внутри тернарника `plannerModeFromConfigEnabled() ? ... : 'auto'` (т.е. как ветка kill-switch OFF), отдельных безусловных `mode: 'auto'` быть не должно.

- [ ] **Step 4: Финальный коммит (если остались несохранённые правки)**

```bash
git add -A && git commit -m "test(wp167): регрессия планировщика зелёная" || echo "нечего коммитить"
```

---

## Self-Review (выполнено при написании плана)

**Spec coverage:**
- Хелпер `isEffectivelyManual` + kill-switch `CLIENT_MANUAL_PUBLISH_ENABLED` → Task 1. ✅
- Основная ветка `buildPlannerCards`, замена via_manual → Task 2. ✅
- full-ветка чтения флагов → Task 3. ✅
- degradation-ветка → Task 4. ✅
- плановые карточки (кейс Feminista) → Task 5. ✅
- kill-switch `PLANNER_MODE_FROM_CONFIG_ENABLED` дефолт ON → Task 2 (хелпер + проброс), используется в Tasks 3-5. ✅
- маркеры auto_handoff/had_retry не затронуты → проверено тестом в Task 2. ✅
- фронтенд/БД/админка вне охвата → правок нет. ✅

**Placeholder scan:** плейсхолдеров нет — весь код приведён дословно.

**Type consistency:** `isEffectivelyManual({slotManual, projectManual})` — единая сигнатура во всех тасках; поля строк `slot_manual`/`project_manual` единообразны (SQL snake_case → JS-свойство), `modeFromConfig` в opts buildPlannerCards единообразен; `plannerModeFromConfigEnabled()` — единое имя.

## Развёртывание (после исполнения плана)

- Деплой: git pull в `/root/.openclaw/workspace-genri/autowarm` + `pm2 restart` (server.js — дашборд).
- Миграций нет (колонки уже существуют).
- Откат: `PLANNER_MODE_FROM_CONFIG_ENABLED=false` без редеплоя.
- Verify: открыть планировщик, у Feminista (project_id=100) карточки показывают 👋 вручную; слоты с `manual_publish=true` тоже.
