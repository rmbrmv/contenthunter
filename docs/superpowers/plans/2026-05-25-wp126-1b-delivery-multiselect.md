# WP #126 Фаза 1b — delivery: мультивыбор фильтров (frontend multi + backend массивы)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Включить мультивыбор (OR) в фильтрах проекта/телефона/пака на 5 страницах delivery поверх виджета из Фазы 1a. Сервер учится принимать список значений (обратно совместимо: одиночное значение работает как раньше).

**Architecture:** Виджет `makeSearchSelect` уже multi-capable (эмитит массив при закрытии всплывашки в режиме `multi:true`). Бэкенд: фильтр-билдеры зеркалят существующий паттерн status-фильтра (CSV → `ANY($?::text[])`); планировщик — `project_id` CSV → `int[]` → `ANY`. Фронт сериализует массив в CSV-параметр. Порядок коммитов держит приложение рабочим на каждом шаге: backend (совместимо) → фронт-сериализация и `mpqMatch` (принимают и строку, и массив) → флип виджетов в `multi:true`.

**Tech Stack:** Vanilla JS (`public/index.html`), Node/Express (`server.js`), `publish_planner.js`. Тесты `node --test`.

**База:** ветвиться от ЛОКАЛЬНОГО `main` репо `/home/claude-user/autowarm-testbench` (HEAD `4dd2b97`, содержит Фазу 1a — origin/main её ещё НЕ имеет).

**Спека:** `docs/superpowers/specs/2026-05-25-wp126-search-sort-filters-design.md` (§4.3 семантика, §5.3 бэкенд).

**Важно для исполнителя:** все правки в worktree `/home/claude-user/autowarm-testbench-feat-wp126-1b-multiselect-20260525`. Координаты строк — на момент 4dd2b97; матчить по тексту. `node --test` для существующих тестов; новые серверные правки зеркалят протестированный паттерн status-фильтра, проверяются смоуком.

---

## File Structure

| Файл | Действие | Что меняем |
|---|---|---|
| `server.js` | Modify | `buildPublishQueueFilters` (project CSV→ANY), `buildDashboardFilters` (project CSV→ANY), `buildPublishTasksFilters` (project CSV→ANY), planner-эндпоинт (`project_id` CSV→int[]). |
| `publish_planner.js` | Modify | `getPlannerCards`: `projectId`→`projectIds` (int[]\|null), 4 SQL-условия `=$3`→`=ANY($3)`. |
| `public/index.html` | Modify | мапперы+сериализация (queue/tasks/dashboard/planner) array→CSV; `mpqMatch` массивы; флип 5 виджетов в `multi:true`. |

---

## Task 1: Backend — queue/dashboard/tasks project → список (CSV→ANY)

Зеркалим существующий паттерн status-фильтра (`split(',') → list.length===1 ? '=$?' : 'ANY($?::text[])'`). Обратно совместимо.

**Files:** Modify `server.js`

- [ ] **Step 1: `buildPublishQueueFilters` (≈line 1900)**

FIND:
```js
  if (query.project)     push('COALESCE(vp.project, vp2.project) = $?', String(query.project));
```
REPLACE:
```js
  if (query.project) {
    const list = String(query.project).split(',').map(s => s.trim()).filter(Boolean);
    if (list.length === 1) push('COALESCE(vp.project, vp2.project) = $?', list[0]);
    else if (list.length > 1) push('COALESCE(vp.project, vp2.project) = ANY($?::text[])', list);
  }
```

- [ ] **Step 2: `buildDashboardFilters` (≈line 1918)**

FIND:
```js
  if (query.project)          push('COALESCE(vp.project, vp2.project) = $?', String(query.project));
```
REPLACE:
```js
  if (query.project) {
    const list = String(query.project).split(',').map(s => s.trim()).filter(Boolean);
    if (list.length === 1) push('COALESCE(vp.project, vp2.project) = $?', list[0]);
    else if (list.length > 1) push('COALESCE(vp.project, vp2.project) = ANY($?::text[])', list);
  }
```

- [ ] **Step 3: `buildPublishTasksFilters` (≈line 2554)**

FIND:
```js
  if (query.project) push("vp.project = $?", String(query.project));
```
REPLACE:
```js
  if (query.project) {
    const list = String(query.project).split(',').map(s => s.trim()).filter(Boolean);
    if (list.length === 1) push("vp.project = $?", list[0]);
    else if (list.length > 1) push("vp.project = ANY($?::text[])", list);
  }
```

- [ ] **Step 4: Синтаксис + коммит**

Run: `cd /home/claude-user/autowarm-testbench-feat-wp126-1b-multiselect-20260525 && node --check server.js && echo OK`
Expected: `OK`.
```bash
git add server.js
git commit -m "feat(wp126-1b): queue/dashboard/tasks фильтр проекта принимает список (CSV→ANY, совместимо)"
```

---

## Task 2: Backend — планировщик project_id → список

**Files:** Modify `server.js` (endpoint ≈5801), `publish_planner.js` (`getPlannerCards` ≈137-258)

- [ ] **Step 1: server.js planner endpoint (≈5801-5803)**

FIND:
```js
    const pid = req.query.project_id ? parseInt(req.query.project_id, 10) : NaN;
    const projectId = Number.isInteger(pid) ? pid : null;
    const cards = await planner.getPlannerCards(pool, { from, to, projectId, trustQueueStatus: PLANNER_TRUST_QUEUE_STATUS });
```
REPLACE:
```js
    const projectIds = String(req.query.project_id || '')
      .split(',').map(s => parseInt(s.trim(), 10)).filter(Number.isInteger);
    const cards = await planner.getPlannerCards(pool, { from, to, projectIds: projectIds.length ? projectIds : null, trustQueueStatus: PLANNER_TRUST_QUEUE_STATUS });
```

- [ ] **Step 2: publish_planner.js — сигнатура (≈line 137)**

FIND:
```js
async function getPlannerCards(pool, { from, to, projectId = null, trustQueueStatus = true }) {
```
REPLACE:
```js
async function getPlannerCards(pool, { from, to, projectIds = null, trustQueueStatus = true }) {
```

- [ ] **Step 3: publish_planner.js — два идентичных условия `pq.project_id` (lines 159 и 223)**

Используй Edit с `replace_all: true` (строка встречается дважды, обе меняются одинаково).

FIND (replace_all):
```js
        AND ($3::int IS NULL OR pq.project_id = $3)
```
REPLACE:
```js
        AND ($3::int[] IS NULL OR pq.project_id = ANY($3))
```

- [ ] **Step 4: publish_planner.js — условие `q.project_id` (≈line 186)**

FIND:
```js
        AND ($3::int IS NULL OR q.project_id = $3)
```
REPLACE:
```js
        AND ($3::int[] IS NULL OR q.project_id = ANY($3))
```

- [ ] **Step 5: publish_planner.js — условие `s.project_id` (≈line 250)**

FIND:
```js
      AND ($3::int IS NULL OR s.project_id = $3)
```
REPLACE:
```js
      AND ($3::int[] IS NULL OR s.project_id = ANY($3))
```

- [ ] **Step 6: publish_planner.js — 4 param-массива `[from, to, projectId]`**

Используй Edit с `replace_all: true` (4 идентичных вхождения: ≈161, 187, 225, 258).

FIND (replace_all):
```js
    `, [from, to, projectId]);
```
REPLACE:
```js
    `, [from, to, projectIds]);
```

⚠️ Проверь, что в файле НЕ осталось `projectId` (единственное число): `grep -n "projectId\b" publish_planner.js` должен быть пуст.

- [ ] **Step 7: Синтаксис + grep + коммит**

Run:
```bash
cd /home/claude-user/autowarm-testbench-feat-wp126-1b-multiselect-20260525
node --check server.js && node --check publish_planner.js && echo OK
grep -n "projectId\b" publish_planner.js || echo "no stray projectId (good)"
grep -c "ANY(\$3)" publish_planner.js
```
Expected: `OK`; no stray `projectId`; `ANY($3)` встречается 4 раза.
```bash
git add server.js publish_planner.js
git commit -m "feat(wp126-1b): планировщик принимает список project_id (CSV→int[]→ANY, совместимо)"
```

---

## Task 3: Frontend — сериализация массива→CSV в мапперах и фетчах

Все обработчики учатся принимать и строку (старое), и массив (новое мульти). Пустой массив → параметр не отправляется.

**Files:** Modify `public/index.html`

- [ ] **Step 1: `upqMapFiltersToServer` (≈line 11065)**

FIND:
```js
  if (filters.project)          out.project          = filters.project;
```
REPLACE:
```js
  { const p = Array.isArray(filters.project) ? filters.project.join(',') : filters.project; if (p) out.project = p; }
```

- [ ] **Step 2: `uptMapFiltersToServer` (≈line 11082)**

FIND:
```js
  if (filters.project)       out.project       = filters.project;
```
REPLACE:
```js
  { const p = Array.isArray(filters.project) ? filters.project.join(',') : filters.project; if (p) out.project = p; }
```

- [ ] **Step 3: `loadPublishingDashboard` project-параметр (≈line 11907)**

FIND:
```js
  if (_dashFilters.project)          params.set('project', _dashFilters.project);
```
REPLACE:
```js
  { const p = Array.isArray(_dashFilters.project) ? _dashFilters.project.join(',') : _dashFilters.project; if (p) params.set('project', p); }
```

- [ ] **Step 4: `plannerLoad` project_id-параметр (≈line 10928-10929)**

FIND:
```js
  const qs = new URLSearchParams({ from: plannerFmt(from), to: plannerFmt(to) });
  if (proj) qs.set('project_id', proj);
```
REPLACE:
```js
  const qs = new URLSearchParams({ from: plannerFmt(from), to: plannerFmt(to) });
  const projCsv = Array.isArray(proj) ? proj.join(',') : proj;
  if (projCsv) qs.set('project_id', projCsv);
```

(`proj` здесь = `_plannerProjectId`, которое после флипа станет массивом; до флипа — строка. Обе ветки покрыты.)

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp126-1b-multiselect-20260525
git add public/index.html
git commit -m "feat(wp126-1b): фронт сериализует мультивыбор проекта в CSV (queue/tasks/dashboard/planner)"
```

---

## Task 4: Frontend — `mpqMatch` принимает массив (Ручная выкладка, клиент)

**Files:** Modify `public/index.html` — `mpqMatch` (≈line 12149)

- [ ] **Step 1: обновить select-ветку `mpqMatch`**

FIND:
```js
function mpqMatch(card, c, f) {
  if (c.key === 'agg_status') return mpqStatusVisible(card.agg_status, Array.isArray(f) ? f : null);
  if (c.key === 'platforms_label') return mpqPlatformVisible(card.rows.map(r => (r.platform || '').toLowerCase()), Array.isArray(f) ? f : null);
  if (c.filter === 'daterange') return mpqDateInRange(card[c.key], f);
  if (!f) return true;
  if (c.filter === 'select' || c.filter === 'date') return String(card[c.key] ?? '') === f;
  return String(card[c.key] ?? '').toLowerCase().includes(f.toLowerCase());
}
```
REPLACE:
```js
function mpqMatch(card, c, f) {
  if (c.key === 'agg_status') return mpqStatusVisible(card.agg_status, Array.isArray(f) ? f : null);
  if (c.key === 'platforms_label') return mpqPlatformVisible(card.rows.map(r => (r.platform || '').toLowerCase()), Array.isArray(f) ? f : null);
  if (c.filter === 'daterange') return mpqDateInRange(card[c.key], f);
  // WP#126-1b: мультивыбор select-фильтров (phone/project/pack) — f это массив; пусто = все.
  if (c.filter === 'select' && Array.isArray(f)) return f.length === 0 || f.includes(String(card[c.key] ?? ''));
  if (!f) return true;
  if (c.filter === 'select' || c.filter === 'date') return String(card[c.key] ?? '') === f;
  return String(card[c.key] ?? '').toLowerCase().includes(f.toLowerCase());
}
```

- [ ] **Step 2: Коммит**

```bash
git add public/index.html
git commit -m "feat(wp126-1b): mpqMatch — мультивыбор select-фильтров (значение ∈ множество)"
```

---

## Task 5: Frontend — флип 5 виджетов в `multi:true`

Теперь все downstream-обработчики готовы к массивам → включаем мультирежим. В мульти `onChange` отдаёт массив при закрытии всплывашки.

**Files:** Modify `public/index.html`

- [ ] **Step 1: Queue widget (`loadQueueProjects`, ≈line 11406)**

FIND:
```js
    _upqProjectWidget = makeSearchSelect(host, {
      options, allLabel: 'все', placeholder: 'поиск проекта…',
      onChange: v => upColFilter('project', v),
    });
```
REPLACE:
```js
    _upqProjectWidget = makeSearchSelect(host, {
      options, multi: true, allLabel: 'все', placeholder: 'поиск проекта…',
      onChange: v => upColFilter('project', v),
    });
```

- [ ] **Step 2: Tasks widget (`loadTasksProjects`, ≈line 11275)**

FIND:
```js
    _uptProjectWidget = makeSearchSelect(host, {
      options, allLabel: 'все', placeholder: 'поиск проекта…',
      onChange: v => uptColFilter('project', v),
    });
```
REPLACE:
```js
    _uptProjectWidget = makeSearchSelect(host, {
      options, multi: true, allLabel: 'все', placeholder: 'поиск проекта…',
      onChange: v => uptColFilter('project', v),
    });
```

- [ ] **Step 3: Planner widget (`plannerInit`, ≈line 10885)**

FIND:
```js
      _plannerProjectWidget = makeSearchSelect(host, {
        options, allLabel: 'все клиенты', placeholder: 'поиск клиента…',
        onChange: v => { _plannerProjectId = v; plannerLoad(); },
      });
```
REPLACE:
```js
      _plannerProjectWidget = makeSearchSelect(host, {
        options, multi: true, allLabel: 'все клиенты', placeholder: 'поиск клиента…',
        onChange: v => { _plannerProjectId = v; plannerLoad(); },
      });
```

- [ ] **Step 4: Dashboard widget (`loadDashProjects`, ≈line 11825)**

FIND:
```js
    _dashProjectWidget = makeSearchSelect(host, {
      options, value: _dashFilters.project, allLabel: 'все проекты', placeholder: 'поиск проекта…',
      onChange: v => { _dashFilters.project = v; loadPublishingDashboard(); },
    });
```
REPLACE:
```js
    _dashProjectWidget = makeSearchSelect(host, {
      options, multi: true, value: _dashFilters.project, allLabel: 'все проекты', placeholder: 'поиск проекта…',
      onChange: v => { _dashFilters.project = v; loadPublishingDashboard(); },
    });
```

- [ ] **Step 5: Manual Publish widgets (`mpqMountSearchFilters`, ≈line 12273)**

FIND:
```js
    makeSearchSelect(host, {
      options,
      value: mpqFilters[key] || '',
      allLabel: 'все',
      placeholder: 'поиск…',
      onChange: v => { mpqFilters[key] = v; mpqRenderBody(); },
    });
```
REPLACE:
```js
    makeSearchSelect(host, {
      options,
      multi: true,
      value: mpqFilters[key] || '',
      allLabel: 'все',
      placeholder: 'поиск…',
      onChange: v => { mpqFilters[key] = v; mpqRenderBody(); },
    });
```

- [ ] **Step 6: Коммит**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp126-1b-multiselect-20260525
git add public/index.html
git commit -m "feat(wp126-1b): включён мультивыбор на 5 страницах delivery (multi:true)"
```

---

## Task 6: Смоук и верификация

**Files:** нет правок.

- [ ] **Step 1: Существующие тесты не сломаны**

Run: `cd /home/claude-user/autowarm-testbench-feat-wp126-1b-multiselect-20260525 && node --test tests/test_search_select_pure.test.js test_mpq_pure.test.js 2>&1 | grep -E "# (tests|pass|fail)"`
Expected: 13/13 pass.

- [ ] **Step 2: Синтаксис всех изменённых файлов**

Run: `node --check server.js && node --check publish_planner.js && echo OK`
Expected: `OK`. (index.html — HTML, не проверяется node --check; смоук в браузере.)

- [ ] **Step 3: SQL-смоук планировщика (если есть доступ к БД)**

Если БД доступна, проверить, что `getPlannerCards` с `projectIds: [<id1>,<id2>]` возвращает карточки только этих проектов, а `projectIds: null` — все. Иначе — браузерный смоук ниже.

- [ ] **Step 4: Визуальный смоук в браузере (чек-лист)**

На testbench, на каждой странице:
1. **Запланировано / Опубликовано:** открыть фильтр проекта → чекбоксы; отметить 2+ проекта → закрыть всплывашку → таблица показывает строки ВСЕХ выбранных (OR); снять все / «Все» → все строки; одиночный выбор по-прежнему работает.
2. **Планировщик:** отметить 2+ клиентов → сетка показывает карточки всех выбранных; «все клиенты» → все.
3. **Дашборд выкладки:** отметить 2+ проекта → метрики/график агрегируются по набору.
4. **Ручная выкладка:** Тел.№/Проект/Пак — мультивыбор; отметить несколько проектов → карточки фильтруются по объединению; сортировка колонки сохраняет мультивыбор (ремоунт читает массив из `mpqFilters`).
5. Проверить, что фильтр применяется ОДИН раз при закрытии всплывашки (не дёргает сервер на каждый чек) — по вкладке Network.

- [ ] **Step 5: История коммитов**

Run: `cd /home/claude-user/autowarm-testbench-feat-wp126-1b-multiselect-20260525 && git log --oneline main..HEAD`
Expected: 5 коммитов (Task 1-5), дерево чистое.

---

## Self-Review (выполнено автором)

- **Покрытие спеки (§5.3):** 4 серверных точки (queue/dashboard/tasks builders + planner) — Tasks 1-2; фронт-сериализация — Task 3; клиентский мульти Ручной — Task 4; включение — Task 5. ✓
- **Обратная совместимость:** все серверные правки — `list.length===1 ? '=$?' : 'ANY'`; одиночный CSV (один элемент) идёт прежним путём. Планировщик: `projectIds=null` (нет параметра) → `$3::int[] IS NULL` true → фильтра нет, как раньше. ✓
- **Порядок коммитов безопасен:** backend (принимает и одиночное, и список) → фронт-сериализация и mpqMatch (принимают и строку, и массив) → флип в multi. На каждом коммите приложение рабочее. ✓
- **Планировщик `projectId`→`projectIds`:** Step 6 Task 2 грепом проверяет отсутствие осиротевшего `projectId`; `ANY($3)` ×4. ⚠ Самая рискованная правка — на ревью смотреть SQL внимательно.
- **Плейсхолдеры:** нет; все edit-блоки old→new точные. Два идентичных условия планировщика и 4 param-массива — через `replace_all` (явно отмечено). ✓
- **Имена:** `_upqProjectWidget/_uptProjectWidget/_plannerProjectWidget/_dashProjectWidget`, `_plannerProjectId`, `_dashFilters.project`, `mpqFilters[key]` — согласованы с Фазой 1a. ✓
