# WP #128 «Правки к ручной выкладке» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Внести 6 UI-правок в подраздел «Ручная выкладка» delivery-дашборда: чекбоксы-фильтр статусов, убрать видео из карточки + точечное обновление вместо полного ререндера, колонка «Ручная дата», убрать «План выкладки» из сайдбара, починить дёргание ширины колонки статуса.

**Architecture:** Фронт целиком в `public/index.html` (vanilla JS, hash-routed SPA). Тестируемое ядро (предикат фильтра + диф строк) выносится в `public/mpq_pure.js` (UMD: browser-глобали + node `module.exports`) — паттерн уже есть (`public/paginated-table.js` грузится через `<script src>`). Бэкенд — одна строка в `manual_publish_queue.js` (SELECT-алиас `manual_date` из существующего `created_at`, без миграции). Поллинг переходит с полного `mpqRender()` на диф-`mpqReconcile()` (таблица) и sig-guard `mpqReconcileCard()` (карточка).

**Tech Stack:** Node.js (CommonJS), `node:test`, PostgreSQL (`pg`), vanilla JS + Tailwind CDN. Спека: `docs/superpowers/specs/2026-05-25-wp128-manual-publish-edits-design.md`.

**Рабочее дерево:** изолированный git-worktree от `autowarm` `main` (см. Task 0). Прод-чекаут `/root/.openclaw/workspace-genri/autowarm` остаётся на `main` (его cwd читает живой pm2-процесс — переключать ветку там НЕЛЬЗЯ).

---

## File Structure

| Файл | Роль | Действие |
|------|------|----------|
| `manual_publish_queue.js` | бэкенд-модуль очереди | Modify: `JOINED_SELECT` (+`manual_date` алиас), `rowToDict` (+`manual_date`) |
| `test_mpq_rowtodict.test.js` | юнит-тест маппинга (без БД) | Create |
| `public/mpq_pure.js` | чистые ф-ции `mpqStatusVisible` + `mpqDiff` (UMD) | Create |
| `test_mpq_pure.test.js` | юнит-тесты чистого ядра | Create |
| `public/index.html` | SPA (вся UI-логика mpq) | Modify (R1–R6) |

Якоря в `public/index.html` (на 2026-05-25): состояние `mpqRows/mpqSort/mpqFilters` — 12036; `MPQ_COLS` — 12038–12048 (`planned_date` 12045, `agg_status` 12046); `MPQ_STATUS` — 12049; `mpqCards` — 12064; `mpqMatch` — 12091; `mpqApply` — 12096; `mpqFilterCell` — 12104 (select 12107–12110, date 12112–12113, text 12115); `mpqCardActions` — 12118; `mpqCardRowHtml` — 12129; `mpqRender` — 12145; `mpqReset` — 12178; `mpqOpenCard` — 12196; `mpqRenderCard` — 12220 (`<video>` 12252); `mpqLoad` — 12285; `mpqStartPoll`/`mpqPoll` — 12297/12305; таблица `#mpq-table` — 2278; сайдбар-кнопка «План выкладки» — 279–281; `<script src="/paginated-table.js">` — 21.

---

## Task 0: Изолированный worktree + базовый прогон тестов

**Files:** нет правок кода — только подготовка дерева.

- [ ] **Step 1: Создать worktree от origin/main**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin --quiet
git worktree add -b wp128-manual-publish-edits /home/claude-user/autowarm-wp128 origin/main
```
Expected: `Preparing worktree (new branch 'wp128-manual-publish-edits')`. Дальше ВСЕ правки и коммиты — в `/home/claude-user/autowarm-wp128`. Прод-чекаут не трогаем.

- [ ] **Step 2: Подключить node_modules (worktree их не содержит — gitignored)**

```bash
ln -s /root/.openclaw/workspace-genri/autowarm/node_modules /home/claude-user/autowarm-wp128/node_modules
```

- [ ] **Step 3: Проверить auto-push hook и pre-commit (общие для worktree)**

```bash
cd /home/claude-user/autowarm-wp128
cat .git/hooks/pre-commit 2>/dev/null | head -30
```
Контекст: `post-commit` пушит ТЕКУЩУЮ ветку без `--force` (`git push origin "$BRANCH" -q`) → коммиты на `wp128-manual-publish-edits` просто публикуют фичеветку в `GenGo2/delivery-contenthunter`, `main` не трогают. Это ожидаемо и безопасно. **Никаких `--force` / `git push` в `main` вручную.**

- [ ] **Step 4: Базовый прогон тестов (зелёный старт)**

```bash
cd /home/claude-user/autowarm-wp128
node --test test_manual_publish_queue.test.js 2>&1 | tail -15
```
Expected: тесты проходят (live-DB, localhost openclaw поднята). Если падают ДО наших правок — зафиксировать как pre-existing и не чинить здесь.

---

## Task 1: Бэкенд — проброс `manual_date` (= `created_at`)

**Files:**
- Create: `test_mpq_rowtodict.test.js`
- Modify: `manual_publish_queue.js` (`rowToDict` ~стр. 18–40; `JOINED_SELECT` ~стр. 49–62)

- [ ] **Step 1: Написать падающий юнит-тест маппинга (без БД)**

Create `test_mpq_rowtodict.test.js`:
```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const mpq = require('./manual_publish_queue');

test('rowToDict пробрасывает manual_date из строки', () => {
  const d = mpq.rowToDict({
    id: 1, slot_id: 2, content_id: 3, unic_result_id: 4, platform: 'instagram',
    account_username: 'acc', planned_date: '2026-05-20', manual_date: '2026-05-18',
    operator_status: 'queued',
  });
  assert.equal(d.manual_date, '2026-05-18');
});
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

```bash
cd /home/claude-user/autowarm-wp128
node --test test_mpq_rowtodict.test.js 2>&1 | tail -15
```
Expected: FAIL — `d.manual_date` is `undefined` (поле ещё не пробрасывается).

- [ ] **Step 3: Добавить `manual_date` в `rowToDict`**

В `manual_publish_queue.js`, в объекте, который возвращает `rowToDict`, после строки `planned_date: m.planned_date, operator_status: m.operator_status,` добавить поле:
```js
    manual_date: m.manual_date,
```

- [ ] **Step 4: Добавить SQL-алиас в `JOINED_SELECT`**

В `manual_publish_queue.js`, в `JOINED_SELECT`, в строке с `to_char(q.planned_date, 'YYYY-MM-DD') AS planned_date` дописать второй алиас сразу после неё (в том же SELECT-списке):
```sql
         to_char(q.created_at, 'YYYY-MM-DD') AS manual_date,
```
Вставлять как отдельный элемент списка (с запятой), не ломая существующие колонки. Пример контекста — добавить новую строку перед `q.operator_status,`.

- [ ] **Step 5: Прогнать — тест зелёный**

```bash
cd /home/claude-user/autowarm-wp128
node --test test_mpq_rowtodict.test.js 2>&1 | tail -15
```
Expected: PASS.

- [ ] **Step 6: Sanity — live-запрос отдаёт `manual_date`**

```bash
cd /home/claude-user/autowarm-wp128
node -e "const {Pool}=require('pg');const mpq=require('./manual_publish_queue');(async()=>{const p=new Pool({host:'localhost',user:'openclaw',password:'openclaw123',database:'openclaw'});const r=await mpq.listQueue(p);console.log('rows:',r.length,'sample manual_date:',r[0]&&r[0].manual_date);await p.end();})().catch(e=>{console.error(e.message);process.exit(1)})"
```
Expected: печатает число строк и `manual_date` вида `YYYY-MM-DD` (или `undefined`-нет — если очередь пуста, ошибки быть не должно).

- [ ] **Step 7: Commit**

```bash
cd /home/claude-user/autowarm-wp128
git add manual_publish_queue.js test_mpq_rowtodict.test.js
git commit -m "feat(wp128): manual_date (=created_at) в очереди ручной выкладки"
```

---

## Task 2: Фронт-ядро — `public/mpq_pure.js` (чистые функции) + подключение

**Files:**
- Create: `public/mpq_pure.js`
- Create: `test_mpq_pure.test.js`
- Modify: `public/index.html` (строка 21 — добавить `<script src>`)

- [ ] **Step 1: Написать падающие тесты чистого ядра**

Create `test_mpq_pure.test.js`:
```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mpqStatusVisible, mpqDiff } = require('./public/mpq_pure');

test('mpqStatusVisible: дефолт показывает queued+in_progress, скрывает остальное', () => {
  const checked = ['queued', 'in_progress'];
  assert.equal(mpqStatusVisible('queued', checked), true);
  assert.equal(mpqStatusVisible('in_progress', checked), true);
  assert.equal(mpqStatusVisible('partial', checked), false);
  assert.equal(mpqStatusVisible('published', checked), false);
});

test('mpqStatusVisible: пустой набор → ничего; не-массив → показать всё', () => {
  assert.equal(mpqStatusVisible('queued', []), false);
  assert.equal(mpqStatusVisible('queued', null), true);
});

test('mpqDiff: add/remove/patch по ключу и сигнатуре', () => {
  const current = [{ unic_result_id: 1, sig: 'queued|' }, { unic_result_id: 2, sig: 'in_progress|ksenia' }];
  const desired = [{ unic_result_id: 2, sig: 'published|' }, { unic_result_id: 3, sig: 'queued|' }];
  const r = mpqDiff(current, desired);
  assert.deepEqual(r.toRemove, [1]);            // 1 исчез
  assert.deepEqual(r.toAdd, [3]);               // 3 появился
  assert.deepEqual(r.toPatch, [2]);             // 2 сменил статус
});

test('mpqDiff: неизменившиеся строки не патчатся', () => {
  const same = [{ unic_result_id: 5, sig: 'queued|' }];
  const r = mpqDiff(same, [{ unic_result_id: 5, sig: 'queued|' }]);
  assert.deepEqual(r, { toRemove: [], toAdd: [], toPatch: [] });
});
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

```bash
cd /home/claude-user/autowarm-wp128
node --test test_mpq_pure.test.js 2>&1 | tail -15
```
Expected: FAIL — `Cannot find module './public/mpq_pure'`.

- [ ] **Step 3: Создать `public/mpq_pure.js`**

Create `public/mpq_pure.js`:
```js
// mpq_pure.js — чистые функции ручной выкладки (WP #128). Без DOM.
// Грузится в браузер через <script src="/mpq_pure.js"> (window-глобали) и
// тестируется в node (module.exports). Пара к mpqReconcile/mpqRender в index.html.
(function (global) {
  'use strict';

  // R1: виден ли пак при отмеченных в фильтре статусах.
  // checked — массив agg_status'ов. Пустой массив → ничего. Не-массив → показать всё.
  function mpqStatusVisible(aggStatus, checked) {
    if (!Array.isArray(checked)) return true;
    return checked.includes(aggStatus);
  }

  // R2b: диф для точечного обновления tbody.
  // current/desired — массивы { unic_result_id, sig }, где sig — статус-сигнатура строки.
  // Возвращает { toRemove:[unic...], toAdd:[unic...], toPatch:[unic...] }.
  // toPatch — только строки, у которых sig изменился (неизменившиеся НЕ трогаем).
  function mpqDiff(current, desired) {
    const curMap = new Map(current.map(d => [d.unic_result_id, d.sig]));
    const desMap = new Map(desired.map(d => [d.unic_result_id, d.sig]));
    const toRemove = current.filter(d => !desMap.has(d.unic_result_id)).map(d => d.unic_result_id);
    const toAdd = desired.filter(d => !curMap.has(d.unic_result_id)).map(d => d.unic_result_id);
    const toPatch = desired
      .filter(d => curMap.has(d.unic_result_id) && curMap.get(d.unic_result_id) !== d.sig)
      .map(d => d.unic_result_id);
    return { toRemove, toAdd, toPatch };
  }

  const api = { mpqStatusVisible, mpqDiff };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') Object.assign(window, api);
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

- [ ] **Step 4: Прогнать — тесты зелёные**

```bash
cd /home/claude-user/autowarm-wp128
node --test test_mpq_pure.test.js 2>&1 | tail -15
```
Expected: PASS (4 теста).

- [ ] **Step 5: Подключить скрипт в index.html**

В `public/index.html` после строки 21 (`<script src="/paginated-table.js"></script>`) добавить:
```html
  <script src="/mpq_pure.js"></script>
```

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-wp128
git add public/mpq_pure.js test_mpq_pure.test.js public/index.html
git commit -m "feat(wp128): mpq_pure.js — mpqStatusVisible + mpqDiff (UMD, под тестами)"
```

---

## Task 3: R2b — разбить рендер + точечное обновление на поллинге

**Files:** Modify `public/index.html` — `mpqCardRowHtml` (12129), `mpqRender` (12145), `mpqOpenCard` (12196), `mpqRenderCard` (12220), `mpqPoll` (12305), state-decl (12193).

> Тестов на DOM нет (в репо нет jsdom) — корректность ядра покрыта `mpqDiff`/`mpqStatusVisible` (Task 2), визуальная проверка — Task 8. Каждый шаг — точечный Edit с проверкой `grep`.

- [ ] **Step 1: Дать строкам и заголовкам групп стабильные ключи + маркеры ячеек**

Заменить функцию `mpqCardRowHtml` (12129–12143) на:
```js
// Сигнатура строки = ВСЕ отображаемые/сортируемые/группирующие поля. Любое их изменение
// на поллинге → строка считается изменившейся и перерисовывается целиком (mpqPatchRow).
// (manual_date появится в Task 4 — пока undefined→'' , согласовано.)
function mpqRowSig(card) {
  return [card.phone_number, card.project_name, card.pack_name, card.platforms_label,
    card.source_video_url, card.unic_video_url, card.planned_date, card.manual_date,
    card.agg_status, card.taken_by].map(v => v == null ? '' : String(v)).join('|');
}

function mpqCardRowHtml(card) {
  const srcU = safeUrl(card.source_video_url), unicU = safeUrl(card.unic_video_url);
  const src = srcU ? `<a href="${esc(srcU)}" target="_blank" rel="noopener" class="text-indigo-600" onclick="event.stopPropagation()">исх.</a>` : '';
  const unic = unicU ? `<a href="${esc(unicU)}" target="_blank" rel="noopener" class="text-indigo-600" onclick="event.stopPropagation()">уник.</a>` : '';
  const taker = card.taken_by ? ` <span class="text-xs text-gray-400">(${esc(card.taken_by)})</span>` : '';
  return `<tr class="border-b hover:bg-gray-50 cursor-pointer" data-mpq-unic="${card.unic_result_id}" data-mpq-sig="${esc(mpqRowSig(card))}" onclick="mpqOpenCard(${card.unic_result_id})">
    <td class="px-2 py-1.5">${esc(card.phone_number ?? '')}</td>
    <td class="px-2 py-1.5">${esc(card.project_name ?? '')}</td>
    <td class="px-2 py-1.5">${esc(card.pack_name ?? '')}</td>
    <td class="px-2 py-1.5">${esc(card.platforms_label)}</td>
    <td class="px-2 py-1.5">${src}</td><td class="px-2 py-1.5">${unic}</td>
    <td class="px-2 py-1.5">${esc(card.planned_date ?? '')}</td>
    <td class="px-2 py-1.5">${esc(MPQ_STATUS[card.agg_status] || card.agg_status)}${taker}</td>
    <td class="px-2 py-1.5" onclick="event.stopPropagation()">${mpqCardActions(card)}</td></tr>`;
}
```
(Колонка «Ручная дата» добавится в Task 4, класс ширины статуса — в Task 5.)

- [ ] **Step 2: Разбить `mpqRender` на head/body + диф-реконсиляцию таблицы**

Заменить функцию `mpqRender` (12145–12163) на блок:
```js
function mpqRenderHead() {
  const thead = document.getElementById('mpq-thead');
  const sortMark = k => { const s = mpqSort.find(x => x.key === k); return s ? (s.dir === 'asc' ? ' ▲' : ' ▼') : ''; };
  thead.innerHTML =
    '<tr class="bg-gray-50 border-b sticky top-0 z-10">' +
    MPQ_COLS.map(c => `<th class="px-2 py-2 h-9 text-left font-semibold cursor-pointer select-none z-20" onclick="mpqToggleSort('${c.key}', event)">${esc(c.label)}${sortMark(c.key)}</th>`).join('') +
    '</tr><tr class="bg-indigo-50 border-b">' + MPQ_COLS.map(mpqFilterCell).join('') + '</tr>';
}

function mpqRenderBody() {
  const tbody = document.getElementById('mpq-tbody');
  const cards = mpqApply();
  document.getElementById('mpq-empty').classList.toggle('hidden', cards.length > 0);
  const groups = new Map();
  for (const c of cards) { const k = c.phone_number ?? '—'; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(c); }
  let html = '';
  for (const [phone, grp] of groups) {
    html += `<tr class="bg-gray-100" data-mpq-phone="${esc(phone)}"><td colspan="${MPQ_COLS.length}" class="px-2 py-1 font-semibold text-gray-600">📱 Тел. № ${esc(phone)} <span class="font-normal text-gray-400" data-mpq-count>(${grp.length})</span></td></tr>`;
    html += grp.map(mpqCardRowHtml).join('');
  }
  tbody.innerHTML = html;
}

function mpqRender() { mpqRenderHead(); mpqRenderBody(); }

// Строка изменилась (sig) → заменить её целиком свежим HTML. Позиция/группа сохраняются
// (порядок сверяется отдельно в mpqReconcile). Неизменившиеся строки не трогаются вовсе —
// именно это убирает мелькание. Свежий data-mpq-sig попадает в HTML из mpqCardRowHtml.
function mpqPatchRow(tr, card) { tr.outerHTML = mpqCardRowHtml(card); }

function mpqRefreshGroupHeaders() {
  const tbody = document.getElementById('mpq-tbody');
  let header = null, count = 0; const acc = [];
  for (const tr of [...tbody.children]) {
    if (tr.hasAttribute('data-mpq-phone')) { if (header) acc.push([header, count]); header = tr; count = 0; }
    else if (tr.hasAttribute('data-mpq-unic')) count++;
  }
  if (header) acc.push([header, count]);
  for (const [h, c] of acc) {
    if (c === 0) { h.remove(); continue; }
    const b = h.querySelector('[data-mpq-count]'); if (b) b.textContent = `(${c})`;
  }
}

// Желаемая последовательность "<phone>#<unic>" в сгруппированной по телефону раскладке (как mpqRenderBody).
// Группирующий ключ (phone) включён — чтобы ловить и реордер, и смену группы строки.
function mpqGroupedOrder(cards) {
  const groups = new Map();
  for (const c of cards) { const k = String(c.phone_number ?? '—'); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(c); }
  const out = [];
  for (const [phone, grp] of groups) for (const c of grp) out.push(phone + '#' + c.unic_result_id);
  return out;
}

// Точечное обновление tbody: убрать исчезнувшие, пропатчить сменившие статус,
// при появлении новых строк ИЛИ изменении порядка (активная сортировка по меняющемуся
// полю, напр. «Статус») — пересобрать тело. Без изменений — DOM не трогаем.
function mpqReconcile() {
  const tbody = document.getElementById('mpq-tbody');
  const cards = mpqApply();
  document.getElementById('mpq-empty').classList.toggle('hidden', cards.length > 0);
  const current = [...tbody.querySelectorAll('tr[data-mpq-unic]')].map(tr => ({
    unic_result_id: Number(tr.dataset.mpqUnic), sig: tr.dataset.mpqSig || '',
  }));
  const desired = cards.map(c => ({ unic_result_id: c.unic_result_id, sig: mpqRowSig(c) }));
  const { toRemove, toAdd, toPatch } = mpqDiff(current, desired);
  if (!toRemove.length && !toAdd.length && !toPatch.length) return;
  if (toAdd.length) { mpqRenderBody(); return; }
  // Сравнить последовательность "<группа>#<unic>" выживших строк (после удалений) с желаемой.
  // Учитывает и порядок (сортировка по меняющемуся полю), и смену группы (phone) строки — иначе
  // точечный патч оставил бы строку под старым заголовком группы / в устаревшем порядке.
  const removeSet = new Set(toRemove);
  let curPhone = '';
  const curSeq = [];
  for (const tr of [...tbody.children]) {
    if (tr.hasAttribute('data-mpq-phone')) curPhone = tr.dataset.mpqPhone;
    else if (tr.hasAttribute('data-mpq-unic')) { const u = Number(tr.dataset.mpqUnic); if (!removeSet.has(u)) curSeq.push(curPhone + '#' + u); }
  }
  const desSeq = mpqGroupedOrder(cards);
  if (curSeq.length !== desSeq.length || curSeq.some((s, i) => s !== desSeq[i])) { mpqRenderBody(); return; }
  const byUnic = new Map(cards.map(c => [c.unic_result_id, c]));
  for (const u of toRemove) { const tr = tbody.querySelector(`tr[data-mpq-unic="${u}"]`); if (tr) tr.remove(); }
  for (const u of toPatch) { const tr = tbody.querySelector(`tr[data-mpq-unic="${u}"]`); const c = byUnic.get(u); if (tr && c) mpqPatchRow(tr, c); }
  mpqRefreshGroupHeaders();
}
```

- [ ] **Step 3: Карточка — sig-guard реконсиляция + объявить `mpqCardSig`**

В строке 12193 `let mpqCardUnic = null, mpqCopyVals = {};` дописать `mpqCardSig`:
```js
let mpqCardUnic = null, mpqCopyVals = {}, mpqCardSig = null;
```
Сразу после функции `mpqOpenCard` (заканчивается на 12200) добавить:
```js
function mpqCardComputeSig(rows) {
  return rows.map(r => r.id + ':' + r.operator_status + ':' + (r.publication_url || '')).join('|') + '#' + mpqAgg(rows);
}
function mpqReconcileCard() {
  const rows = mpqGroupRows(mpqCardUnic);
  if (!rows.length) { mpqCloseCard(); return; }
  if (mpqCardComputeSig(rows) === mpqCardSig) return;   // без изменений — DOM не трогаем (видео/поля не дёргаются)
  mpqRenderCard();
}
```
В конце `mpqRenderCard` (после установки `innerHTML`, перед закрывающей `}` функции на 12264) добавить строку фиксации сигнатуры:
```js
  mpqCardSig = mpqCardComputeSig(rows);
```

- [ ] **Step 4: Переключить `mpqPoll` на точечное обновление (с kill-switch)**

Заменить тело `mpqPoll` (12305–12313) ниже строки `mpqRows = data.items || [];` на:
```js
  if (window.MPQ_TARGETED_REFRESH === false) {
    mpqRender();
    if (mpqCardUnic != null && !mpqCardHasUnsavedInput()) mpqRenderCard();
  } else {
    mpqReconcile();
    if (mpqCardUnic != null && !mpqCardHasUnsavedInput()) mpqReconcileCard();
  }
```
(Строки выше — проверка видимости секции и fetch — оставить как есть.)

- [ ] **Step 5: Проверить, что правки на месте**

```bash
cd /home/claude-user/autowarm-wp128
grep -n "function mpqRenderHead\|function mpqRenderBody\|function mpqReconcile\b\|function mpqGroupedOrder\|function mpqReconcileCard\|data-mpq-unic\|MPQ_TARGETED_REFRESH\|mpqCardSig" public/index.html | head -20
```
Expected: видны все новые функции, `data-mpq-unic`, kill-switch, `mpqCardSig`.

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-wp128
git add public/index.html
git commit -m "feat(wp128): точечное обновление ручной выкладки (диф таблицы + sig-guard карточки), kill-switch MPQ_TARGETED_REFRESH"
```

---

## Task 4: R3 + R5 — колонка «Ручная дата» (после «План дата»)

**Files:** Modify `public/index.html` — `MPQ_COLS` (12038), `mpqCards` (12064), `mpqCardRowHtml` (после Task 3).

- [ ] **Step 1: Добавить колонку в `MPQ_COLS` после `planned_date`**

В `MPQ_COLS` (12038–12048) после строки
```js
  { key: 'planned_date',     label: 'План дата', filter: 'date' },
```
вставить:
```js
  { key: 'manual_date',      label: 'Ручная дата', filter: null },
```

- [ ] **Step 2: Пробросить `manual_date` в объект пака**

В `mpqCards` (12068–12073), в объекте, который кладётся в `map.set(k, {...})`, после `pack_name: r.pack_name, planned_date: r.planned_date,` добавить:
```js
      manual_date: r.manual_date,
```

- [ ] **Step 3: Добавить ячейку в строку таблицы**

В `mpqCardRowHtml` (версия из Task 3) после ячейки план-даты
```js
    <td class="px-2 py-1.5">${esc(card.planned_date ?? '')}</td>
```
вставить ячейку «Ручная дата»:
```js
    <td class="px-2 py-1.5">${esc(card.manual_date ?? '')}</td>
```

- [ ] **Step 4: Проверить**

```bash
cd /home/claude-user/autowarm-wp128
grep -n "manual_date" public/index.html
```
Expected: 3 вхождения (MPQ_COLS, mpqCards, ячейка строки).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-wp128
git add public/index.html
git commit -m "feat(wp128): колонка «Ручная дата» (=created_at) после «План дата»"
```

---

## Task 5: R1 + R6 — чекбоксы фильтра статусов в шапке колонки + фикс ширины

**Files:** Modify `public/index.html` — `<style>` (~62), state-decl (12036), `MPQ_COLS` (12038), `mpqMatch` (12091), `mpqFilterCell` (12104), `mpqRenderHead` (из Task 3), `mpqCardRowHtml` (status `<td>`), `mpqReset` (12178); + новая `mpqToggleStatus`.

- [ ] **Step 1: Дефолт фильтра — queued + in_progress**

Заменить строку 12036:
```js
let mpqRows = [], mpqSort = [], mpqFilters = {};
```
на:
```js
let mpqRows = [], mpqSort = [], mpqFilters = { agg_status: ['queued', 'in_progress'] };
```

- [ ] **Step 2: Пометить колонку статуса классом ширины**

В `MPQ_COLS` заменить строку
```js
  { key: 'agg_status',       label: 'Статус',    filter: 'select' },
```
на:
```js
  { key: 'agg_status',       label: 'Статус',    filter: 'select', cls: 'mpq-col-status' },
```

- [ ] **Step 3: `mpqMatch` — ветка agg_status делегирует в чистую `mpqStatusVisible`**

Заменить функцию `mpqMatch` (12091–12095) на:
```js
function mpqMatch(card, c, f) {
  if (c.key === 'agg_status') return mpqStatusVisible(card.agg_status, Array.isArray(f) ? f : null);
  if (!f) return true;
  if (c.filter === 'select' || c.filter === 'date') return String(card[c.key] ?? '') === f;
  return String(card[c.key] ?? '').toLowerCase().includes(f.toLowerCase());
}
```

- [ ] **Step 4: `mpqFilterCell` — чекбоксы для agg_status + остальные фильтры зовут `mpqRenderBody`**

Заменить функцию `mpqFilterCell` (12104–12116) на:
```js
function mpqFilterCell(c) {
  if (c.key === 'actions') return `<th class="px-2 py-1 !top-9"><button onclick="mpqReset()" title="Сброс сортировки и фильтров" class="text-indigo-700">⟲</button></th>`;
  if (c.key === 'agg_status') {
    const sel = Array.isArray(mpqFilters.agg_status) ? mpqFilters.agg_status : [];
    const boxes = Object.keys(MPQ_STATUS).map(st =>
      `<label class="flex items-center gap-1 text-xs whitespace-nowrap cursor-pointer"><input type="checkbox" value="${st}" ${sel.includes(st) ? 'checked' : ''} onchange="mpqToggleStatus('${st}', this.checked)"> ${esc(MPQ_STATUS[st])}</label>`).join('');
    return `<th class="px-2 py-1 !top-9 mpq-col-status"><div class="flex flex-col gap-0.5">${boxes}</div></th>`;
  }
  if (!c.filter) return '<th class="px-2 py-1 !top-9"></th>';
  if (c.filter === 'select') {
    const vals = [...new Set(mpqCards().map(r => r[c.key]).filter(v => v !== null && v !== undefined && v !== ''))];
    const opts = vals.map(v => `<option value="${esc(v)}" ${mpqFilters[c.key] === String(v) ? 'selected' : ''}>${esc(v)}</option>`).join('');
    return `<th class="px-2 py-1 !top-9"><select onchange="mpqFilters['${c.key}']=this.value; mpqRenderBody()" class="w-full border rounded px-1 py-0.5 text-xs"><option value="">все</option>${opts}</select></th>`;
  }
  if (c.filter === 'date') {
    return `<th class="px-2 py-1 !top-9"><input type="date" value="${esc(mpqFilters[c.key] || '')}" onchange="mpqFilters['${c.key}']=this.value; mpqRenderBody()" class="w-full border rounded px-1 py-0.5 text-xs"></th>`;
  }
  return `<th class="px-2 py-1 !top-9"><input value="${esc(mpqFilters[c.key] || '')}" oninput="mpqFilters['${c.key}']=this.value; mpqRenderBody()" class="w-full border rounded px-1 py-0.5 text-xs" placeholder="фильтр"></th>`;
}
```
(agg_status больше не использует общую select-ветку, поэтому из неё убран спец-кейс `MPQ_STATUS`.)

- [ ] **Step 5: Добавить `mpqToggleStatus`**

Сразу после `mpqFilterCell` (перед `mpqCardActions`) добавить:
```js
function mpqToggleStatus(st, on) {
  const set = new Set(Array.isArray(mpqFilters.agg_status) ? mpqFilters.agg_status : []);
  if (on) set.add(st); else set.delete(st);
  mpqFilters.agg_status = [...set];
  mpqRenderBody();
}
```

- [ ] **Step 6: Шапка таблицы — поддержать класс колонки (`c.cls`)**

В `mpqRenderHead` (Task 3) в map заголовков заменить
```js
    MPQ_COLS.map(c => `<th class="px-2 py-2 h-9 text-left font-semibold cursor-pointer select-none z-20" onclick="mpqToggleSort('${c.key}', event)">${esc(c.label)}${sortMark(c.key)}</th>`).join('') +
```
на
```js
    MPQ_COLS.map(c => `<th class="px-2 py-2 h-9 text-left font-semibold cursor-pointer select-none z-20${c.cls ? ' ' + c.cls : ''}" onclick="mpqToggleSort('${c.key}', event)">${esc(c.label)}${sortMark(c.key)}</th>`).join('') +
```

- [ ] **Step 7: Ячейка статуса в строке — класс ширины**

В `mpqCardRowHtml` заменить ячейку статуса
```js
    <td class="px-2 py-1.5">${esc(MPQ_STATUS[card.agg_status] || card.agg_status)}${taker}</td>
```
на
```js
    <td class="px-2 py-1.5 mpq-col-status">${esc(MPQ_STATUS[card.agg_status] || card.agg_status)}${taker}</td>
```
(Это та же ячейка статуса, что в Task 3 — но в строке есть две ячейки `px-2 py-1.5` подряд; матчить именно ту, что содержит `MPQ_STATUS[card.agg_status]`.)

- [ ] **Step 8: CSS — зафиксировать ширину колонки статуса (R6)**

В `<style>`-блоке (рядом со строкой 62–63, где `.table-wrap`) добавить правило:
```css
    #mpq-table .mpq-col-status { width: 160px; min-width: 160px; max-width: 160px; }
```
Это пиннит ширину колонки статуса независимо от того, видна ли длинная метка «Частично выложено» → конец дёрганью при смене даты в «План дата».

- [ ] **Step 9: `mpqReset` — сбрасывать к дефолту фильтра**

Заменить `mpqReset` (12178):
```js
function mpqReset() { mpqSort = []; mpqFilters = {}; mpqRender(); }
```
на:
```js
function mpqReset() { mpqSort = []; mpqFilters = { agg_status: ['queued', 'in_progress'] }; mpqRender(); }
```

- [ ] **Step 10: Проверить + перегнать ядро-тесты (логика фильтра не сломана)**

```bash
cd /home/claude-user/autowarm-wp128
grep -n "mpqToggleStatus\|mpq-col-status\|agg_status: \['queued'" public/index.html | head
node --test test_mpq_pure.test.js 2>&1 | tail -8
```
Expected: вхождения видны; тесты `mpq_pure` зелёные.

- [ ] **Step 11: Commit**

```bash
cd /home/claude-user/autowarm-wp128
git add public/index.html
git commit -m "feat(wp128): чекбоксы фильтра статусов в шапке колонки (дефолт queued+in_progress) + фикс ширины колонки статуса"
```

---

## Task 6: R2a — убрать `<video>` из карточки (оставить ссылку)

**Files:** Modify `public/index.html` — `mpqRenderCard` (строка 12252).

- [ ] **Step 1: Удалить элемент `<video>`**

В `mpqRenderCard` удалить строку 12252 целиком:
```js
    ${unicU ? `<video src="${esc(unicU)}" controls class="w-full rounded-lg my-2 max-h-96"></video>` : ''}
```
Ссылки `copy('unic_link', ...)` (12253) и «⬇ исходное»/«⬇ уник.» (12254–12257) оставить — это и есть «только ссылка».

- [ ] **Step 2: Проверить, что других `<video>` в карточке нет**

```bash
cd /home/claude-user/autowarm-wp128
sed -n '12230,12260p' public/index.html | grep -n "video" || echo "нет <video> в карточке — ОК"
```
Expected: «нет <video> в карточке — ОК».

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-wp128
git add public/index.html
git commit -m "feat(wp128): убрать видео из карточки ручной выкладки (оставить ссылку)"
```

---

## Task 7: R4 — убрать «План выкладки» из сайдбара

**Files:** Modify `public/index.html` — сайдбар-кнопка (строки 279–281).

- [ ] **Step 1: Удалить кнопку**

Удалить блок строк 279–281:
```html
    <button onclick="nav('validator-plan')" id="nav-validator-plan" class="nav-item w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-gray-600 hover:bg-gray-100 text-left">
      <span>📅</span> План выкладки
    </button>
```
Секцию `section-validator-plan` и запись в `sidebarMap` НЕ трогаем (безвредны, обратимо).

- [ ] **Step 2: Проверить**

```bash
cd /home/claude-user/autowarm-wp128
grep -n "nav('validator-plan')\|План выкладки" public/index.html || echo "пункт убран — ОК"
```
Expected: «пункт убран — ОК» (кнопки в сайдбаре больше нет; упоминание в `sidebarMap` допустимо).

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-wp128
git add public/index.html
git commit -m "feat(wp128): убрать пункт «План выкладки» из сайдбара"
```

---

## Task 8: Полная верификация + браузерная приёмка + деплой-заметки

**Files:** нет правок — проверка.

- [ ] **Step 1: Прогнать все затронутые тесты**

```bash
cd /home/claude-user/autowarm-wp128
node --test test_mpq_rowtodict.test.js test_mpq_pure.test.js 2>&1 | tail -15
node --test test_manual_publish_queue.test.js 2>&1 | tail -10
```
Expected: всё зелёное (или те же pre-existing падения, что и в Task 0 Step 4 — не регрессия).

- [ ] **Step 2: Синтаксис-санити index.html (реально компилируем inline-JS)**

Извлекаем каждый inline `<script>` (без `src`) и компилируем его тело через `new Function` — это ловит битые шаблонные строки / несбалансированные скобки (без исполнения, только парсинг). В файле ровно 9 пар `<script>`/`</script>` без вложенных литералов `</script>`, поэтому жадно-нежадная выборка корректна.

```bash
cd /home/claude-user/autowarm-wp128
node <<'EOF'
const fs = require('fs');
const h = fs.readFileSync('public/index.html', 'utf8');
const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
let m, total = 0, compiled = 0;
while ((m = re.exec(h))) {
  total++;
  if (/\bsrc\s*=/.test(m[1])) continue;          // внешние скрипты пропускаем
  try { new Function(m[2]); compiled++; }
  catch (e) { console.error('SYNTAX ERROR в inline <script> #' + total + ': ' + e.message); process.exit(1); }
}
console.log('OK: inline <script> скомпилировано', compiled, '/ тегов', total);
EOF
```
Expected: `OK: inline <script> скомпилировано N / тегов 9` без `SYNTAX ERROR`. (Полная семантическая проверка — в браузере, шаг 3.) Примечание: если inline-скрипт использует top-level `await`, `new Function` ложно упадёт — в этом проекте такого нет.

- [ ] **Step 3: Браузерная приёмка на тестовой копии**

Деплой тест-копии (паттерн `cp` в прод-чекаут — НЕ коммит в `main`): запросить у Данила/выполнить временный `cp public/index.html public/mpq_pure.js` в прод `public/` ИЛИ открыть worktree-версию через временный статик-сервер. Чек-лист в `#publishing/publishing-manual`:
  1. По умолчанию видны только «В очереди» + «В работе»; чекбоксы статусов в шапке колонки «Статус».
  2. Снять/поставить чекбокс — строки появляются/исчезают; «Выложено»/«Частично» показываются при отметке.
  3. Колонка «Ручная дата» стоит сразу после «План дата», даты корректные.
  4. Открыть карточку — видео нет, ссылки «⬇ исходное»/«⬇ уник.» на месте.
  5. Подождать 1–2 цикла поллинга (≈10 с) — таблица и карточка не моргают, поля не прыгают; смена статуса (взять в работу/выложить на другом устройстве) обновляется точечно.
  6. Сменить дату в «План дата» — ширина колонки «Статус» не дёргается.
  7. В левом сайдбаре нет пункта «План выкладки».
  8. Kill-switch: в консоли `window.MPQ_TARGETED_REFRESH=false` → поведение откатывается на полный ререндер (для отката в проде).

- [ ] **Step 4: Деплой (после приёмки Данила)**

- Бэкенд (`manual_publish_queue.js`): cherry-pick в прод `main` → перезапуск процесса автоварма, обслуживающего `/api/publishing/manual-queue` (`pm2 restart <app>`; перед этим свериться `pm2 describe <app> | grep "exec cwd"`, что cwd = прод-чекаут).
- Фронт (`public/index.html` + `public/mpq_pure.js`): cherry-pick в прод `main` (auto-push hook доставит в `GenGo2/delivery-contenthunter`). Статик отдаётся сразу; пользователям при необходимости — hard reload.
- PR фичеветки `wp128-manual-publish-edits` в `GenGo2/delivery-contenthunter` (ветка уже запушена auto-push hook'ом).

- [ ] **Step 5: Обновить OpenProject WP #128**

Комментарий в house-стиле (Что было не так → Что сделано → Что осталось, без жаргона, без футера), статус → «Тестирование» после деплоя; «Готово» — после подтверждения Данилом в браузере.

---

## Self-Review (выполнено при написании плана)

- **Покрытие спеки:** R1 → T5; R2a → T6; R2b → T3; R3 → T1+T4; R4 → T7; R5 → T4; R6 → T5. Бэкенд `manual_date` → T1. Тестируемое ядро → T2. Все 6 пунктов + бэкенд закрыты.
- **Плейсхолдеры:** нет TBD/«добавить обработку» — каждый шаг с готовым кодом/командой.
- **Согласованность имён:** `mpqStatusVisible`/`mpqDiff` (T2) используются в `mpqMatch` (T5) и `mpqReconcile` (T3); `mpqRenderBody` (T3) зовётся фильтрами (T5); `data-mpq-unic`/`data-mpq-sig` (T3) читаются `mpqReconcile` (T3); `mpqPatchRow` заменяет строку целиком через `mpqCardRowHtml`; `mpq-col-status` (T5) задаётся в MPQ_COLS+ячейке+CSS; `mpqCardSig`/`mpqCardComputeSig` (T3) согласованы. Forward-зависимости упорядочены: T1→T2→T3→T4→T5→T6→T7→T8.
- **Гранулярность обновления:** `mpqRowSig` покрывает ВСЕ отображаемые поля → изменившаяся строка перерисовывается целиком (`mpqPatchRow` = замена `outerHTML`), неизменившиеся не трогаются вовсе (нет мелькания). Полный пересбор тела (`mpqRenderBody`) — только при появлении новых строк ИЛИ изменении порядка (редкие случаи). Карточка — sig-guard (полный ререндер только при реальном изменении пака). Всё под kill-switch `MPQ_TARGETED_REFRESH`. (Фиксы P2 codex-review: устаревший порядок при сортировке по статусу + узкая сигнатура строки.)
