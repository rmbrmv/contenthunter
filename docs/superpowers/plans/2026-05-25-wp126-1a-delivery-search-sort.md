# WP #126 Фаза 1a — delivery: поиск + единая сортировка в фильтрах (одиночный выбор)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить голые нативные `<select>` фильтра проекта (и Тел.№/Пак на Ручной выкладке) на переиспользуемый виджет с полем поиска и единой алфавитной сортировкой — на всех 5 страницах delivery. Поведение фильтрации не меняется (одиночный выбор), бэкенд не трогаем.

**Architecture:** Чистые функции сортировки/фильтра/метки выносятся в `public/search_select_pure.js` (паттерн `mpq_pure.js`: IIFE + `module.exports`/`window`, тестируется `node --test`). DOM-виджет `makeSearchSelect(host, opts)` в `public/search_select.js` монтируется в стабильный `<div>`-контейнер вместо `<select>`. Виджет multi-capable (под Фазу 1b), но здесь везде монтируется в одиночном режиме и вызывает существующие обработчики (`upColFilter`/`uptColFilter`/`plannerLoad`/`_dashApplyFilters`/`mpqFilters`). Ручная выкладка ремоунтит виджеты после `mpqRenderHead` (шапка перерисовывается через innerHTML на initial/sort/reset), читая выбор из `mpqFilters` (source of truth).

**Tech Stack:** Vanilla JS (single-file `public/index.html` ~14.4k строк, без сборки), Node.js `node --test` для чистых функций. Репозиторий-чекаут: `/home/claude-user/autowarm-testbench/`.

**Спека:** `docs/superpowers/specs/2026-05-25-wp126-search-sort-filters-design.md` (§4 архитектура, §5 delivery).

**Важно для исполнителя:**
- Все правки — в репозитории `/home/claude-user/autowarm-testbench/` (НЕ в `/home/claude-user/contenthunter`, где лежит этот план).
- Перед стартом: `cd /home/claude-user/autowarm-testbench && git fetch && git checkout -b wp126-1a-delivery-search-sort origin/main` (или текущая рабочая ветка по договорённости). Файл `index.html` редактируется параллельными сессиями — атомарные коммиты, не оставлять half-broken state.
- Координаты строк даны на 2026-05-25; если сдвинулись — ищи по якорям (id/имя функции), приведённым в каждом шаге.

---

## File Structure

| Файл | Действие | Ответственность |
|---|---|---|
| `public/search_select_pure.js` | Create | Чистые функции: `ssCompare`, `ssSortOptions`, `ssFilterOptions`, `ssTriggerLabel`, `ssToggle`. Без DOM. |
| `tests/test_search_select_pure.test.js` | Create | Юнит-тесты чистых функций (`node --test`). |
| `public/search_select.js` | Create | DOM-виджет `makeSearchSelect(host, opts)` (триггер + всплывашка с поиском, single+multi). |
| `public/index.html` | Modify | Подключение скриптов (head); замена 5 `<select>` на host-контейнеры; переписать функции наполнения на монтирование виджета. |

---

## Task 1: Чистые функции `search_select_pure.js` (TDD)

**Files:**
- Create: `public/search_select_pure.js`
- Test: `tests/test_search_select_pure.test.js`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_search_select_pure.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { ssCompare, ssSortOptions, ssFilterOptions, ssTriggerLabel, ssToggle } = require('../public/search_select_pure');

test('ssCompare: RU-алфавит, регистронезависимо, числа натурально', () => {
  assert.ok(ssCompare('Аквабрайт', 'Бест Клиник') < 0);
  assert.ok(ssCompare('бест', 'Аквабрайт') > 0);           // регистр не влияет на порядок букв
  assert.equal(Math.sign(ssCompare('тел 2', 'тел 10')), -1); // numeric: 2 < 10
});

test('ssSortOptions: сортирует по label, не мутирует вход', () => {
  const input = [{ value: 3, label: 'Балтамбер' }, { value: 1, label: 'Аквабрайт' }, { value: 2, label: 'бест' }];
  const out = ssSortOptions(input);
  assert.deepEqual(out.map(o => o.label), ['Аквабрайт', 'Балтамбер', 'бест']);
  assert.equal(input[0].label, 'Балтамбер'); // исходный массив не тронут
});

test('ssFilterOptions: подстрока регистронезависимо; пустой запрос → все', () => {
  const opts = [{ value: 1, label: 'Парфюмерия' }, { value: 2, label: 'Аквабрайт' }];
  assert.deepEqual(ssFilterOptions(opts, 'парф').map(o => o.value), [1]);
  assert.deepEqual(ssFilterOptions(opts, '').map(o => o.value), [1, 2]);
  assert.deepEqual(ssFilterOptions(opts, '   ').map(o => o.value), [1, 2]);
});

test('ssTriggerLabel: пусто→allLabel, один→label, много→"выбрано: N"', () => {
  const opts = [{ value: '1', label: 'Аквабрайт' }, { value: '2', label: 'Бест' }];
  assert.equal(ssTriggerLabel([], opts, 'все'), 'все');
  assert.equal(ssTriggerLabel(['1'], opts, 'все'), 'Аквабрайт');
  assert.equal(ssTriggerLabel(['1', '2'], opts, 'все'), 'выбрано: 2');
  assert.equal(ssTriggerLabel(['99'], opts, 'все'), '99'); // нет в опциях → сырое значение
});

test('ssToggle: добавляет/убирает значение, строки', () => {
  assert.deepEqual(ssToggle([], 5), ['5']);
  assert.deepEqual(ssToggle(['5'], '5'), []);
  assert.deepEqual(ssToggle(['5'], 7), ['5', '7']);
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-testbench && node --test tests/test_search_select_pure.test.js`
Expected: FAIL — `Cannot find module '../public/search_select_pure'`.

- [ ] **Step 3: Реализовать модуль**

Создать `public/search_select_pure.js`:

```js
// search_select_pure.js — чистые функции searchable-dropdown (WP #126). Без DOM.
// Грузится в браузер через <script src="/search_select_pure.js"> (window-глобали) и
// тестируется в node (module.exports). Пара к makeSearchSelect в search_select.js.
(function (global) {
  'use strict';

  // Сравнитель по отображаемому имени: RU-локаль, регистронезависимо (sensitivity:base),
  // натуральный числовой порядок (тел №2 раньше №10).
  function ssCompare(a, b) {
    return String(a).localeCompare(String(b), 'ru', { sensitivity: 'base', numeric: true });
  }

  // Сортировка опций [{value,label}] по label. Возвращает КОПИЮ (вход не мутируется).
  function ssSortOptions(options) {
    return [...(options || [])].sort((x, y) => ssCompare(x.label, y.label));
  }

  // Фильтр опций по подстроке query в label (регистронезависимо). Пустой/пробельный query → все.
  function ssFilterOptions(options, query) {
    const q = String(query || '').trim().toLowerCase();
    if (!q) return (options || []).slice();
    return (options || []).filter(o => String(o.label).toLowerCase().includes(q));
  }

  // Метка триггера. selected — массив value (single → 0..1 элемент). Пусто → allLabel;
  // один → его label (или сырое value, если опции нет); несколько → «выбрано: N».
  function ssTriggerLabel(selected, options, allLabel) {
    const sel = Array.isArray(selected) ? selected : (selected ? [selected] : []);
    if (sel.length === 0) return allLabel;
    if (sel.length === 1) {
      const o = (options || []).find(x => String(x.value) === String(sel[0]));
      return o ? o.label : String(sel[0]);
    }
    return `выбрано: ${sel.length}`;
  }

  // Тоггл value в наборе выбранных (multi). Все значения нормализуются к строкам. Новый массив.
  function ssToggle(selected, value) {
    const sel = Array.isArray(selected) ? selected.map(String) : [];
    const v = String(value);
    return sel.includes(v) ? sel.filter(x => x !== v) : [...sel, v];
  }

  const api = { ssCompare, ssSortOptions, ssFilterOptions, ssTriggerLabel, ssToggle };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') Object.assign(window, api);
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-testbench && node --test tests/test_search_select_pure.test.js`
Expected: PASS (5 тестов).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add public/search_select_pure.js tests/test_search_select_pure.test.js
git commit -m "feat(wp126): чистые функции searchable-select (sort/filter/label/toggle) + тесты"
```

---

## Task 2: DOM-виджет `makeSearchSelect`

**Files:**
- Create: `public/search_select.js`
- Modify: `public/index.html` (подключение скриптов, после строки 22 `<script src="/mpq_pure.js"></script>`)

- [ ] **Step 1: Создать виджет**

Создать `public/search_select.js`:

```js
// search_select.js — DOM-виджет searchable-dropdown (WP #126). Логика sort/filter/label/toggle
// делегируется в search_select_pure.js (window-глобали). Грузить ПОСЛЕ search_select_pure.js.
(function (global) {
  'use strict';

  function ssEsc(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  }

  // Стили инжектируются один раз.
  function ensureStyles() {
    if (document.getElementById('ss-styles')) return;
    const s = document.createElement('style');
    s.id = 'ss-styles';
    s.textContent =
      '.ss-root{position:relative;display:inline-block;width:100%}' +
      '.ss-trigger{width:100%;text-align:left;border:1px solid #e5e7eb;border-radius:.375rem;padding:.125rem .375rem;font-size:.75rem;line-height:1rem;background:#fff;cursor:pointer;display:flex;justify-content:space-between;gap:.25rem;align-items:center}' +
      '.ss-trigger:focus{outline:none;border-color:#a5b4fc}' +
      '.ss-trigger-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.ss-pop{position:absolute;z-index:60;top:100%;left:0;min-width:100%;max-width:340px;background:#fff;border:1px solid #e5e7eb;border-radius:.375rem;box-shadow:0 4px 16px rgba(0,0,0,.12);margin-top:2px}' +
      '.ss-search{width:100%;border:none;border-bottom:1px solid #eee;padding:.375rem .5rem;font-size:.75rem;outline:none;box-sizing:border-box}' +
      '.ss-list{max-height:240px;overflow-y:auto;padding:.125rem 0}' +
      '.ss-opt{display:flex;align-items:center;gap:.375rem;padding:.25rem .5rem;font-size:.75rem;cursor:pointer;white-space:nowrap}' +
      '.ss-opt:hover{background:#eef2ff}' +
      '.ss-empty{padding:.5rem;color:#9ca3af;font-size:.75rem;text-align:center}';
    document.head.appendChild(s);
  }

  // host — DOM-контейнер. opts: { options:[{value,label}], value, multi, allLabel, placeholder, onChange }.
  // Single: onChange(valueString) сразу по клику. Multi: onChange([values]) при закрытии всплывашки.
  // Возвращает контроллер { setOptions, getValue, setValue, destroy }.
  function makeSearchSelect(host, opts) {
    ensureStyles();
    const o = opts || {};
    function normSel(v) {
      if (Array.isArray(v)) return v.map(String).filter(s => s !== '');
      return (v === undefined || v === null || v === '') ? [] : [String(v)];
    }
    const state = {
      options: global.ssSortOptions(o.options || []),
      multi: !!o.multi,
      allLabel: o.allLabel || 'все',
      placeholder: o.placeholder || 'поиск…',
      onChange: typeof o.onChange === 'function' ? o.onChange : function () {},
      selected: normSel(o.value),
      open: false,
      query: '',
    };

    host.innerHTML = '';
    host.classList.add('ss-root');
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'ss-trigger';
    host.appendChild(trigger);
    let pop = null;

    function renderTrigger() {
      trigger.innerHTML = '<span class="ss-trigger-label">' +
        ssEsc(global.ssTriggerLabel(state.selected, state.options, state.allLabel)) +
        '</span><span style="color:#9ca3af">▾</span>';
    }

    function emit() {
      if (state.multi) state.onChange(state.selected.slice());
      else state.onChange(state.selected[0] || '');
    }

    function renderList() {
      if (!pop) return;
      const listEl = pop.querySelector('.ss-list');
      const shown = global.ssFilterOptions(state.options, state.query);
      if (!shown.length && state.query) { listEl.innerHTML = '<div class="ss-empty">ничего не найдено</div>'; return; }
      const rows = [{ value: '', label: state.allLabel, _all: true }].concat(shown);
      listEl.innerHTML = rows.map(opt => {
        const isAll = !!opt._all;
        const checked = isAll ? (state.selected.length === 0) : state.selected.includes(String(opt.value));
        const mark = state.multi
          ? ('<input type="checkbox" ' + (checked ? 'checked' : '') + ' tabindex="-1">')
          : (checked ? '✓' : '<span style="width:.75rem;display:inline-block"></span>');
        return '<div class="ss-opt" data-val="' + ssEsc(opt.value) + '" data-all="' + (isAll ? '1' : '') + '">' +
          mark + '<span>' + ssEsc(opt.label) + '</span></div>';
      }).join('');
    }

    function onPick(e) {
      const row = e.target.closest('.ss-opt');
      if (!row) return;
      const isAll = row.dataset.all === '1';
      const val = row.dataset.val;
      if (state.multi) {
        state.selected = isAll ? [] : global.ssToggle(state.selected, val);
        renderTrigger(); renderList();      // multi: применяем при закрытии
      } else {
        state.selected = isAll ? [] : [String(val)];
        renderTrigger();
        closePop();
        emit();                              // single: применяем сразу
      }
    }

    function onOutside(e) { if (!host.contains(e.target)) closePop(); }
    function onKey(e) { if (e.key === 'Escape') closePop(); }

    function openPop() {
      if (state.open) return;
      state.open = true; state.query = '';
      pop = document.createElement('div');
      pop.className = 'ss-pop';
      pop.innerHTML = '<input class="ss-search" placeholder="' + ssEsc(state.placeholder) + '"><div class="ss-list"></div>';
      host.appendChild(pop);
      renderList();
      const search = pop.querySelector('.ss-search');
      search.addEventListener('input', () => { state.query = search.value; renderList(); });
      pop.querySelector('.ss-list').addEventListener('click', onPick);
      search.focus();
      setTimeout(() => document.addEventListener('mousedown', onOutside), 0);
      document.addEventListener('keydown', onKey);
    }

    function closePop() {
      if (!state.open) return;
      state.open = false;
      document.removeEventListener('mousedown', onOutside);
      document.removeEventListener('keydown', onKey);
      const wasMulti = state.multi;
      if (pop) { pop.remove(); pop = null; }
      if (wasMulti) emit();                  // multi: эмитим накопленный выбор при закрытии
    }

    trigger.addEventListener('click', () => state.open ? closePop() : openPop());
    renderTrigger();

    return {
      setOptions(list) { state.options = global.ssSortOptions(list || []); renderTrigger(); if (state.open) renderList(); },
      getValue() { return state.multi ? state.selected.slice() : (state.selected[0] || ''); },
      setValue(v) { state.selected = normSel(v); renderTrigger(); if (state.open) renderList(); },
      destroy() { closePop(); host.innerHTML = ''; host.classList.remove('ss-root'); },
    };
  }

  if (typeof window !== 'undefined') window.makeSearchSelect = makeSearchSelect;
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

- [ ] **Step 2: Подключить скрипты в `index.html`**

Якорь — строка 22 `<script src="/mpq_pure.js"></script>`. Заменить:

```html
  <script src="/mpq_pure.js"></script>
```

на:

```html
  <script src="/mpq_pure.js"></script>
  <script src="/search_select_pure.js"></script>
  <script src="/search_select.js"></script>
```

(Порядок важен: pure до виджета — виджет читает `ssSortOptions` и т.п. с `window`.)

- [ ] **Step 3: Проверка синтаксиса**

Run: `cd /home/claude-user/autowarm-testbench && node --check public/search_select.js && node --check public/search_select_pure.js && echo OK`
Expected: `OK` (без ошибок парсинга).

- [ ] **Step 4: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add public/search_select.js public/index.html
git commit -m "feat(wp126): DOM-виджет makeSearchSelect + подключение скриптов"
```

---

## Task 3: Интеграция — Запланировано (Queue)

**Files:**
- Modify: `public/index.html` — HTML селекта (≈2429-2434), `loadQueueProjects()` (≈11404), `upClearFilters()` (≈11395)

- [ ] **Step 1: Заменить `<select>` на host-контейнер**

Найти (≈2429-2434):

```html
            <td class="px-2 py-1">
              <select id="up-project-select" onchange="upColFilter('project', this.value)"
                      class="w-full border border-gray-200 rounded px-1 py-0.5 text-xs focus:outline-none focus:border-indigo-300">
                <option value="">все</option>
              </select>
            </td>
```

Заменить на:

```html
            <td class="px-2 py-1"><div id="up-project-host"></div></td>
```

- [ ] **Step 2: Переписать `loadQueueProjects` на монтирование виджета**

Найти (≈11403-11420):

```js
let _upqProjectsLoaded = false;
async function loadQueueProjects() {
  if (_upqProjectsLoaded) return;
  try {
    const r = await fetch('/api/publish/queue/projects');
    if (!r.ok) return;
    const list = await r.json();
    const sel = document.getElementById('up-project-select');
    if (!sel) return;
    const cur = sel.value;
    // DOM API — text/value via textContent/attribute, no innerHTML escaping needed.
    sel.textContent = '';
    sel.add(new Option('все', ''));
    for (const p of list) sel.add(new Option(p, p));
    sel.value = cur;
    _upqProjectsLoaded = true;
  } catch (e) { console.warn('[loadQueueProjects]', e); }
}
```

Заменить на:

```js
let _upqProjectWidget = null;
async function loadQueueProjects() {
  try {
    const r = await fetch('/api/publish/queue/projects');
    if (!r.ok) return;
    const list = await r.json();
    const host = document.getElementById('up-project-host');
    if (!host) return;
    const options = list.map(p => ({ value: p, label: p }));
    if (_upqProjectWidget) { _upqProjectWidget.setOptions(options); return; }
    _upqProjectWidget = makeSearchSelect(host, {
      options, allLabel: 'все', placeholder: 'поиск проекта…',
      onChange: v => upColFilter('project', v),
    });
  } catch (e) { console.warn('[loadQueueProjects]', e); }
}
```

- [ ] **Step 3: Сбрасывать виджет в `upClearFilters`**

Найти (≈11395-11401):

```js
function upClearFilters() {
  document.querySelectorAll('#section-publishing input, #section-publishing select').forEach(el => { el.value = ''; });
  // Сбрасываем все user-фильтры (но сохраняем status_exclude — управляется чекбоксом).
  for (const k of ['status','platform','pack_name','account_username','caption','id','source_name','description','project']) {
    _upqTable.setFilter(k, null);
  }
}
```

Заменить на (добавлена строка сброса виджета — он `<div>`, под `el.value=''` не попадает):

```js
function upClearFilters() {
  document.querySelectorAll('#section-publishing input, #section-publishing select').forEach(el => { el.value = ''; });
  if (_upqProjectWidget) _upqProjectWidget.setValue('');
  // Сбрасываем все user-фильтры (но сохраняем status_exclude — управляется чекбоксом).
  for (const k of ['status','platform','pack_name','account_username','caption','id','source_name','description','project']) {
    _upqTable.setFilter(k, null);
  }
}
```

- [ ] **Step 4: Проверка синтаксиса**

Run: `cd /home/claude-user/autowarm-testbench && node --check public/index.html 2>&1 || echo "index.html не чистый JS — пропускаем node --check, проверим смоуком"`
Expected: `index.html` — это HTML, `node --check` не применим; шаг — формальность, реальная проверка в Task 8 (смоук). Достаточно глазами убедиться, что нет осиротевших тегов/скобок.

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add public/index.html
git commit -m "feat(wp126): Запланировано — поиск+сортировка фильтра проекта (виджет)"
```

---

## Task 4: Интеграция — Опубликовано (Tasks)

**Files:**
- Modify: `public/index.html` — HTML селекта (≈2501-2506), `loadTasksProjects()` (≈11273), `uptResetAndLoad()` (≈11291)

- [ ] **Step 1: Заменить `<select>` на host-контейнер**

Найти (≈2501-2506):

```html
            <td class="px-2 py-1">
              <select id="upt-project-select" onchange="uptColFilter('project', this.value)"
                      class="w-full border border-gray-200 rounded px-1 py-0.5 text-xs focus:outline-none focus:border-indigo-300">
                <option value="">все</option>
              </select>
            </td>
```

Заменить на:

```html
            <td class="px-2 py-1"><div id="upt-project-host"></div></td>
```

- [ ] **Step 2: Переписать `loadTasksProjects` на монтирование виджета**

Найти (≈11272-11289):

```js
let _uptProjectsLoaded = false;
async function loadTasksProjects() {
  if (_uptProjectsLoaded) return;
  try {
    const r = await fetch('/api/publish/tasks/projects');
    if (!r.ok) return;
    const list = await r.json();
    const sel = document.getElementById('upt-project-select');
    if (!sel) return;
    const cur = sel.value;
    // DOM API — text/value via textContent/attribute, no innerHTML escaping needed.
    sel.textContent = '';
    sel.add(new Option('все', ''));
    for (const p of list) sel.add(new Option(p, p));
    sel.value = cur;
    _uptProjectsLoaded = true;
  } catch (e) { console.warn('[loadTasksProjects]', e); }
}
```

Заменить на:

```js
let _uptProjectWidget = null;
async function loadTasksProjects() {
  try {
    const r = await fetch('/api/publish/tasks/projects');
    if (!r.ok) return;
    const list = await r.json();
    const host = document.getElementById('upt-project-host');
    if (!host) return;
    const options = list.map(p => ({ value: p, label: p }));
    if (_uptProjectWidget) { _uptProjectWidget.setOptions(options); return; }
    _uptProjectWidget = makeSearchSelect(host, {
      options, allLabel: 'все', placeholder: 'поиск проекта…',
      onChange: v => uptColFilter('project', v),
    });
  } catch (e) { console.warn('[loadTasksProjects]', e); }
}
```

- [ ] **Step 3: Сбрасывать виджет в `uptResetAndLoad`**

Найти (≈11291-11294):

```js
function uptResetAndLoad() {
  _uptTable.reset();
  loadTasksProjects();
}
```

Заменить на:

```js
function uptResetAndLoad() {
  _uptTable.reset();
  if (_uptProjectWidget) _uptProjectWidget.setValue('');
  loadTasksProjects();
}
```

- [ ] **Step 4: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add public/index.html
git commit -m "feat(wp126): Опубликовано — поиск+сортировка фильтра проекта (виджет)"
```

---

## Task 5: Интеграция — Планировщик (Planner)

**Files:**
- Modify: `public/index.html` — HTML селекта (≈2468-2470), `plannerInit()` (≈10889), `plannerLoad()` (≈10920, строка чтения `proj`)

- [ ] **Step 1: Заменить `<select>` на host-контейнер**

Найти (≈2468-2470):

```html
        <select id="planner-project-select" onchange="plannerLoad()" class="border border-gray-200 rounded px-2 py-1 text-xs">
          <option value="">все клиенты</option>
        </select>
```

Заменить на:

```html
        <div id="planner-project-host" style="min-width:200px"></div>
```

- [ ] **Step 2: Добавить модульную переменную и переписать `plannerInit`**

Найти (≈10889-10898):

```js
function plannerInit() {
  if (!_plannerWeekStart) _plannerWeekStart = plannerMonday(new Date());
  const sel = document.getElementById('planner-project-select');
  if (sel && sel.options.length <= 1) {
    fetch('/api/validator/projects', { credentials: 'same-origin' }).then(r => r.json()).then(d => {
      (d.projects || []).forEach(p => { const o = document.createElement('option'); o.value = p.project_id; o.textContent = p.project_name; sel.appendChild(o); });
    }).catch(() => {});
  }
  plannerLoad();
}
```

Заменить на:

```js
let _plannerProjectWidget = null;
let _plannerProjectId = '';
function plannerInit() {
  if (!_plannerWeekStart) _plannerWeekStart = plannerMonday(new Date());
  const host = document.getElementById('planner-project-host');
  if (host && !_plannerProjectWidget) {
    fetch('/api/validator/projects', { credentials: 'same-origin' }).then(r => r.json()).then(d => {
      const options = (d.projects || []).map(p => ({ value: p.project_id, label: p.project_name }));
      _plannerProjectWidget = makeSearchSelect(host, {
        options, allLabel: 'все клиенты', placeholder: 'поиск клиента…',
        onChange: v => { _plannerProjectId = v; plannerLoad(); },
      });
    }).catch(() => {});
  }
  plannerLoad();
}
```

- [ ] **Step 3: Читать проект из модульной переменной в `plannerLoad`**

Найти (≈10924) внутри `plannerLoad`:

```js
  const proj = document.getElementById('planner-project-select')?.value || '';
```

Заменить на:

```js
  const proj = _plannerProjectId || '';
```

- [ ] **Step 4: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add public/index.html
git commit -m "feat(wp126): Планировщик — поиск+сортировка фильтра клиента (виджет)"
```

---

## Task 6: Интеграция — Дашборд выкладки (Dashboard)

**Files:**
- Modify: `public/index.html` — HTML селекта (≈2312-2314), `loadDashProjects()` (≈11824), `_dashApplyFilters()` (≈11986), `resetDashFilters()` (≈11999)

- [ ] **Step 1: Заменить `<select>` на host-контейнер**

Найти (≈2312-2314):

```html
    <select id="dash-filter-project" onchange="_dashApplyFilters()" class="px-2 py-1 border border-gray-200 rounded-lg text-xs">
      <option value="">все проекты</option>
    </select>
```

Заменить на:

```html
    <div id="dash-filter-project-host" style="min-width:160px"></div>
```

- [ ] **Step 2: Переписать `loadDashProjects` на монтирование виджета**

Найти (≈11824-11835):

```js
async function loadDashProjects() {
  try {
    const r = await fetch('/api/publish/queue/projects', { credentials: 'same-origin' });
    if (!r.ok) return;
    const list = await r.json();
    const sel = document.getElementById('dash-filter-project');
    if (!sel) return;
    sel.innerHTML = '<option value="">все проекты</option>'
      + list.map(p => `<option value="${_dashEsc(p)}">${_dashEsc(p)}</option>`).join('');
    sel.value = _dashFilters.project;
  } catch (e) { /* дропдаун остаётся с «все проекты» */ }
}
```

Заменить на:

```js
let _dashProjectWidget = null;
async function loadDashProjects() {
  try {
    const r = await fetch('/api/publish/queue/projects', { credentials: 'same-origin' });
    if (!r.ok) return;
    const list = await r.json();
    const host = document.getElementById('dash-filter-project-host');
    if (!host) return;
    const options = list.map(p => ({ value: p, label: p }));
    if (_dashProjectWidget) { _dashProjectWidget.setOptions(options); _dashProjectWidget.setValue(_dashFilters.project); return; }
    _dashProjectWidget = makeSearchSelect(host, {
      options, value: _dashFilters.project, allLabel: 'все проекты', placeholder: 'поиск проекта…',
      onChange: v => { _dashFilters.project = v; loadPublishingDashboard(); },
    });
  } catch (e) { /* дропдаун остаётся с «все проекты» */ }
}
```

- [ ] **Step 3: Убрать чтение проекта из удалённого селекта в `_dashApplyFilters`**

Найти (≈11986-11992):

```js
function _dashApplyFilters() {
  _dashFilters.project          = document.getElementById('dash-filter-project')?.value || '';
  _dashFilters.platform         = document.getElementById('dash-filter-platform')?.value || '';
  _dashFilters.account_username = (document.getElementById('dash-filter-account')?.value || '').trim();
  _dashFilters.pack_name        = (document.getElementById('dash-filter-pack')?.value || '').trim();
  loadPublishingDashboard();
}
```

Заменить на (строка project удалена — проект теперь ведёт виджет через свой onChange):

```js
function _dashApplyFilters() {
  // _dashFilters.project ведёт виджет проекта (loadDashProjects.onChange); здесь не трогаем.
  _dashFilters.platform         = document.getElementById('dash-filter-platform')?.value || '';
  _dashFilters.account_username = (document.getElementById('dash-filter-account')?.value || '').trim();
  _dashFilters.pack_name        = (document.getElementById('dash-filter-pack')?.value || '').trim();
  loadPublishingDashboard();
}
```

- [ ] **Step 4: Сбрасывать виджет в `resetDashFilters`**

Найти (≈11999-12004):

```js
function resetDashFilters() {
  _dashFilters = { project: '', platform: '', account_username: '', pack_name: '' };
  ['dash-filter-project','dash-filter-platform','dash-filter-account','dash-filter-pack']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  loadPublishingDashboard();
}
```

Заменить на:

```js
function resetDashFilters() {
  _dashFilters = { project: '', platform: '', account_username: '', pack_name: '' };
  ['dash-filter-platform','dash-filter-account','dash-filter-pack']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  if (_dashProjectWidget) _dashProjectWidget.setValue('');
  loadPublishingDashboard();
}
```

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add public/index.html
git commit -m "feat(wp126): Дашборд выкладки — поиск+сортировка фильтра проекта (виджет)"
```

---

## Task 7: Интеграция — Ручная выкладка (Manual Publish)

Здесь шапка таблицы перерисовывается через `innerHTML` в `mpqRenderHead()` (initial / сортировка / сброс), но НЕ на поллинге (`mpqReconcile` трогает только tbody). Поэтому: `mpqFilterCell` рендерит host-плейсхолдер, а виджеты монтируются ремоунтом после `mpqRenderHead`, читая выбор из `mpqFilters` (source of truth). Состояние выбора — строка (одиночный), `mpqMatch` не меняется.

**Files:**
- Modify: `public/index.html` — `mpqFilterCell()` select-ветка (≈12187-12191), `mpqRenderHead()` (≈12258-12265)

- [ ] **Step 1: Заменить select-ветку `mpqFilterCell` на host-плейсхолдер**

Найти (≈12187-12191):

```js
  if (c.filter === 'select') {
    const vals = [...new Set(mpqCards().map(r => r[c.key]).filter(v => v !== null && v !== undefined && v !== ''))];
    const opts = vals.map(v => `<option value="${esc(v)}" ${mpqFilters[c.key] === String(v) ? 'selected' : ''}>${esc(v)}</option>`).join('');
    return `<th class="px-2 py-1 !top-9"><select onchange="mpqFilters['${c.key}']=this.value; mpqRenderBody()" class="w-full border rounded px-1 py-0.5 text-xs"><option value="">все</option>${opts}</select></th>`;
  }
```

Заменить на:

```js
  if (c.filter === 'select') {
    // Host под searchable-виджет; монтируется в mpqMountSearchFilters() после mpqRenderHead.
    // (agg_status сюда не доходит — у него спец-ветка выше; остаются phone_number/project_name/pack_name.)
    return `<th class="px-2 py-1 !top-9"><div data-mpq-ss="${esc(c.key)}"></div></th>`;
  }
```

- [ ] **Step 2: Добавить монтирование виджетов и вызвать его из `mpqRenderHead`**

Найти (≈12258-12265):

```js
function mpqRenderHead() {
  const thead = document.getElementById('mpq-thead');
  const sortMark = k => { const s = mpqSort.find(x => x.key === k); return s ? (s.dir === 'asc' ? ' ▲' : ' ▼') : ''; };
  thead.innerHTML =
    '<tr class="bg-gray-50 border-b sticky top-0 z-10">' +
    MPQ_COLS.map(c => `<th class="px-2 py-2 h-9 text-left font-semibold cursor-pointer select-none z-20${c.cls ? ' ' + c.cls : ''}" onclick="mpqToggleSort('${c.key}', event)">${esc(c.label)}${sortMark(c.key)}</th>`).join('') +
    '</tr><tr class="bg-indigo-50 border-b">' + MPQ_COLS.map(mpqFilterCell).join('') + '</tr>';
}
```

Заменить на:

```js
function mpqRenderHead() {
  const thead = document.getElementById('mpq-thead');
  const sortMark = k => { const s = mpqSort.find(x => x.key === k); return s ? (s.dir === 'asc' ? ' ▲' : ' ▼') : ''; };
  thead.innerHTML =
    '<tr class="bg-gray-50 border-b sticky top-0 z-10">' +
    MPQ_COLS.map(c => `<th class="px-2 py-2 h-9 text-left font-semibold cursor-pointer select-none z-20${c.cls ? ' ' + c.cls : ''}" onclick="mpqToggleSort('${c.key}', event)">${esc(c.label)}${sortMark(c.key)}</th>`).join('') +
    '</tr><tr class="bg-indigo-50 border-b">' + MPQ_COLS.map(mpqFilterCell).join('') + '</tr>';
  mpqMountSearchFilters();
}

// WP#126: монтирует searchable-виджеты в host-плейсхолдеры фильтр-строки (Тел.№/Проект/Пак).
// Вызывается после каждого mpqRenderHead (initial/sort/reset). Выбор читается из mpqFilters.
function mpqMountSearchFilters() {
  const thead = document.getElementById('mpq-thead');
  if (!thead) return;
  thead.querySelectorAll('[data-mpq-ss]').forEach(host => {
    const key = host.getAttribute('data-mpq-ss');
    const vals = [...new Set(mpqCards().map(r => r[key]).filter(v => v !== null && v !== undefined && v !== ''))];
    const options = vals.map(v => ({ value: String(v), label: String(v) }));
    makeSearchSelect(host, {
      options,
      value: mpqFilters[key] || '',
      allLabel: 'все',
      placeholder: 'поиск…',
      onChange: v => { mpqFilters[key] = v; mpqRenderBody(); },
    });
  });
}
```

- [ ] **Step 3: Коммит**

```bash
cd /home/claude-user/autowarm-testbench
git add public/index.html
git commit -m "feat(wp126): Ручная выкладка — поиск+сортировка фильтров Тел.№/Проект/Пак (виджет, ремоунт после mpqRenderHead)"
```

---

## Task 8: Финальный смоук и верификация на testbench

**Files:** нет правок кода — только проверка.

- [ ] **Step 1: Прогнать все JS-тесты**

Run: `cd /home/claude-user/autowarm-testbench && npm test 2>&1 | tail -20`
Expected: тесты `test_search_select_pure.test.js` (5) проходят; существующие тесты не сломаны (особенно `test_mpq_pure.test.js`, `publish_planner.test.js`).

- [ ] **Step 2: Синтаксис новых JS-модулей**

Run: `cd /home/claude-user/autowarm-testbench && node --check public/search_select_pure.js && node --check public/search_select.js && echo OK`
Expected: `OK`.

- [ ] **Step 3: Поднять testbench и проверить отдачу скриптов**

Запустить сервер testbench (как принято в репозитории — PM2/systemd или `node server.js`), затем:

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:<PORT>/search_select.js; curl -s -o /dev/null -w "%{http_code}\n" http://localhost:<PORT>/search_select_pure.js`
Expected: `200` и `200` (файлы отдаются статикой из `public/`).

- [ ] **Step 4: Визуальный смоук в браузере (чек-лист)**

На каждой странице проверить виджет фильтра проекта:

1. **Запланировано** (`#publishing/publishing?sub=up:queue`): открыть дропдаун → есть поле поиска; список проектов отсортирован по алфавиту (RU); ввод подстроки фильтрует; выбор проекта → таблица фильтруется (как раньше); «все» → сброс; кнопка «Сбросить фильтры» сбрасывает и виджет.
2. **Опубликовано** (`sub=up:tasks`): то же; «Сбросить» (`uptResetAndLoad`) очищает виджет.
3. **Планировщик** (`sub=up:planner`): поиск по клиентам; выбор → сетка перезагружается под `project_id`; «все клиенты» → все.
4. **Дашборд выкладки** (`#publishing/publishing-dashboard`): выбор проекта → плитки/график перезагружаются; «Сбросить» очищает виджет; платформа/аккаунт/пак-фильтры по-прежнему работают.
5. **Ручная выкладка** (`#publishing/publishing-manual`): три виджета (Тел.№/Проект/Пак) с поиском и сортировкой; выбор фильтрует карточки; сортировка колонки (клик по заголовку) НЕ ломает виджеты (ремоунт, выбор сохраняется); кнопка ⟲ (сброс) очищает фильтры; поллинг не сбрасывает открытый/выбранный фильтр.

Зафиксировать результаты (скрин/заметка). Любой фейл → завести как баг и чинить до зелёного.

- [ ] **Step 5: Финальная проверка истории коммитов**

Run: `cd /home/claude-user/autowarm-testbench && git log --oneline origin/main..HEAD`
Expected: 7 атомарных коммитов (Task 1-7), рабочее дерево чистое (`git status`).

---

## Self-Review (выполнено автором плана)

- **Покрытие спеки (§5 Фаза 1a):** поиск+сортировка на всех 5 delivery-страницах — Task 3 (queue), 4 (tasks), 5 (planner), 6 (dashboard), 7 (manual, 3 фильтра). Единая сортировка — `ssSortOptions` (Task 1), применяется в каждом виджете. Тестируемый модуль `search_select_pure.js` — Task 1. Смоук — Task 8. ✓
- **Без мультивыбора/бэкенда:** все интеграции монтируют виджет в одиночном режиме и зовут существующие одиночные обработчики; серверные эндпоинты не тронуты. Мульти-код виджета присутствует, но не активируется (`multi:true` нигде не передаётся) — он для Фазы 1b. ✓
- **Плейсхолдеры:** отсутствуют — весь код приведён целиком, edit-блоки old→new точные. `<PORT>` в Task 8 — реальная подстановка порта testbench исполнителем (не код-плейсхолдер). ✓
- **Согласованность имён:** `makeSearchSelect`, `ssSortOptions`/`ssFilterOptions`/`ssTriggerLabel`/`ssToggle`/`ssCompare`, host-id (`up-project-host`, `upt-project-host`, `planner-project-host`, `dash-filter-project-host`, `data-mpq-ss`), контроллер-методы (`setOptions`/`getValue`/`setValue`/`destroy`) — едины во всех тасках. ✓
- **Риск регрессии:** `upClearFilters` теряла побочный сброс tasks/planner-селектов (теперь они `<div>`) — это бывший непреднамеренный side-effect queue-кнопки, не сохраняем; queue-виджет сбрасывается явно. Отмечено в Task 3.
