# WP#213 Коды роликов и фильтры (под-проект B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать код ролика видимым/искомым в ручной выкладке, в планировщике (только админам) и добавить фильтр периодом в «Лог событий».

**Architecture:** Общий JS-хелпер `content_code.formatContentCode(prefix, number)` форматирует код из сырых `code_prefix`+`code_number`. Ручная (`rowToDict`) и планировщик (`getPlannerCards`/`buildPlannerCards`) отдают новое поле `code`. Фронт показывает код-колонку в ручной (с текстовым поиском), код в карточке планировщика (за `currentUser.role==='admin'`) и второй date-input в «Логе событий». Без миграции (колонки кода есть из WP#174), без kill-switch (аддитивный UI).

**Tech Stack:** Node.js, `node:test` (pure + live за `RUN_LIVE_DB`), PostgreSQL (`pg`), ванильный JS фронт.

**Репо:** `delivery-contenthunter` (локально `autowarm-testbench`). Файлы: новый `content_code.js`; `manual_publish_queue.js`; `publish_planner.js`; `public/index.html`.

---

## Setup (перед Task 1)

- [ ] **Создать worktree кода** (через superpowers:using-git-worktrees или вручную):
```bash
cd /home/claude-user/autowarm-testbench
git fetch origin --quiet
git worktree add -b wp213b-codes-filters /home/claude-user/wp213b-autowarm origin/main
cd /home/claude-user/wp213b-autowarm && git branch --show-current
```
Expected: `wp213b-codes-filters`. Все пути ниже — относительно этого worktree.

- [ ] **Baseline тесты:**
```bash
cd /home/claude-user/wp213b-autowarm && node --test test_publish_planner.test.js
```
Expected: PASS (базлайн buildPlannerCards).

---

## Task 1: `content_code.js` — общий хелпер формата кода

**Files:** Create `content_code.js`; Create `test_content_code.test.js`.

- [ ] **Step 1: Failing test** — создать `test_content_code.test.js`:
```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { formatContentCode } = require('./content_code');

test('formatContentCode: NNN lpad до 3 при <1000', () => {
  assert.equal(formatContentCode('RLM', 14), 'RLM-014');
  assert.equal(formatContentCode('LEX', 12), 'LEX-012');
  assert.equal(formatContentCode('WAN', 7), 'WAN-007');
});
test('formatContentCode: >=1000 без паддинга', () => {
  assert.equal(formatContentCode('WAN', 1234), 'WAN-1234');
});
test('formatContentCode: null при отсутствии prefix/number', () => {
  assert.equal(formatContentCode(null, 5), null);
  assert.equal(formatContentCode('X', null), null);
  assert.equal(formatContentCode('X', undefined), null);
  assert.equal(formatContentCode('', 5), null);
});
```

- [ ] **Step 2: Run, verify FAIL**
Run: `node --test test_content_code.test.js`
Expected: FAIL — `Cannot find module './content_code'`.

- [ ] **Step 3: Implement** — создать `content_code.js`:
```js
'use strict';

// Формат кода ролика (WP#174): PREFIX-NNN; number<1000 паддится до 3 знаков, иначе как есть.
function formatContentCode(prefix, number) {
  if (!prefix || number == null) return null;
  const n = Number(number);
  if (!Number.isFinite(n)) return null;
  return prefix + '-' + (n < 1000 ? String(n).padStart(3, '0') : String(n));
}

module.exports = { formatContentCode };
```

- [ ] **Step 4: Run, verify PASS**
Run: `node --test test_content_code.test.js`
Expected: ALL pass.

- [ ] **Step 5: Commit**
```bash
cd /home/claude-user/wp213b-autowarm
git add content_code.js test_content_code.test.js
git commit -m "feat(wp213b): content_code.formatContentCode — общий хелпер формата кода

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Код в ручной выкладке — backend (`manual_publish_queue.js`)

**Files:** Modify `manual_publish_queue.js`; Create `test_manual_code.test.js`.

- [ ] **Step 1: Failing test** — создать `test_manual_code.test.js` (чистый, без БД — `rowToDict` экспортируется):
```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { rowToDict } = require('./manual_publish_queue');

test('rowToDict: code из code_prefix+code_number', () => {
  const d = rowToDict({ id: 1, code_prefix: 'RLM', code_number: 14, platform: 'tiktok', account_username: 'x' });
  assert.equal(d.code, 'RLM-014');
});
test('rowToDict: code = null если нет кода', () => {
  const d = rowToDict({ id: 2, code_prefix: null, code_number: null, platform: 'tiktok' });
  assert.equal(d.code, null);
});
```

- [ ] **Step 2: Run, verify FAIL**
Run: `node --test test_manual_code.test.js`
Expected: FAIL — `d.code` is `undefined` (rowToDict ещё не отдаёт code).

- [ ] **Step 3: Implement**
В `manual_publish_queue.js` после строки `const { activeProjectSql, projectNotFrozenSql } = require('./project_active_filter');` добавить:
```js
const { formatContentCode } = require('./content_code');
```
В `rowToDict`, в возвращаемый объект добавить поле (рядом с `content_id`):
```js
    code: formatContentCode(m.code_prefix, m.code_number),
```
В `JOINED_SELECT`, в список колонок (после `vc.title, vc.description, vc.hashtags, vc.geo,`) добавить:
```sql
         vp.code_prefix, vc.code_number,
```
(`vp` и `vc` уже в JOIN — добавляем только выборку.)

- [ ] **Step 4: Run, verify PASS**
Run: `node --test test_manual_code.test.js`
Expected: ALL pass.
Также прогнать живой набор (проверить, что SQL не сломан):
Run: `node --test test_manual_publish_queue.test.js`
Expected: PASS (как в базлайне).

- [ ] **Step 5: Commit**
```bash
cd /home/claude-user/wp213b-autowarm
git add manual_publish_queue.js test_manual_code.test.js
git commit -m "feat(wp213b): код ролика в ручной выкладке (rowToDict.code + JOINED_SELECT)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Код в ручной выкладке — frontend (`public/index.html`)

**Files:** Modify `public/index.html` (MPQ_COLS, mpqCards, mpqCardRowHtml, mpqRowSig).

- [ ] **Step 1: Добавить колонку «Код» в `MPQ_COLS`**
Найти массив `const MPQ_COLS = [` и добавить ПЕРВЫМ элементом (перед `{ key: 'phone_number', ...`):
```js
  { key: 'code',             label: 'Код',       filter: 'text' },
```
(`filter: 'text'` → `mpqFilterCell` отрисует текстовый input по дефолтной ветке; `mpqMatch` даст substring-поиск.)

- [ ] **Step 2: Протащить `code` в карточку (`mpqCards`)**
В `mpqCards()`, в объект `map.set(k, { ... })` добавить поле (рядом с `unic_result_id: k,`):
```js
      code: r.code,
```

- [ ] **Step 3: Вывести код в строке (`mpqCardRowHtml`)**
В `mpqCardRowHtml`, ПЕРВЫМ `<td>` (перед `<td class="px-2 py-1.5">${esc(card.phone_number ?? '')}</td>`) добавить копируемый код (как в `lcRenderRows`):
```js
    <td class="px-2 py-1.5 font-mono text-xs">${card.code ? `<button onclick="event.stopPropagation();navigator.clipboard.writeText('${esc(card.code)}').then(()=>toast('Код скопирован','success'))" class="text-indigo-600 hover:underline">${esc(card.code)}</button>` : '—'}</td>
```

- [ ] **Step 4: Добавить `code` в сигнатуру строки (`mpqRowSig`)**
В `mpqRowSig`, в массив полей добавить `card.code` первым:
```js
  return [card.code, card.phone_number, card.project_name, card.pack_name, card.platforms_label,
```

- [ ] **Step 5: Sanity-check (фронт целостность)**
```bash
cd /home/claude-user/wp213b-autowarm
node -e "const s=require('fs').readFileSync('public/index.html','utf8');
if(!/\{ key: 'code',\s*label: 'Код',\s*filter: 'text' \}/.test(s)) throw 'MPQ_COLS code missing';
if(!/code: r\.code,/.test(s)) throw 'mpqCards code missing';
if(!/navigator\.clipboard\.writeText\('\\\$\{esc\(card\.code\)\}'/.test(s)) throw 'cardRow code missing';
console.log('OK');"
```
Expected: `OK`.

- [ ] **Step 6: Commit**
```bash
cd /home/claude-user/wp213b-autowarm
git add public/index.html
git commit -m "feat(wp213b): колонка «Код» + поиск в ручной выкладке (фронт)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Код в планировщике — backend (`publish_planner.js`)

**Files:** Modify `publish_planner.js` (require, 3 SQL-ветки, intent-маппинг, buildPlannerCards); Modify `test_publish_planner.test.js`; Create `test_planner_code_live.test.js`.

- [ ] **Step 1: Failing pure-тест** — в `test_publish_planner.test.js` добавить в конец:
```js
test('buildPlannerCards: карточка несёт code из meta', () => {
  const intents = [{
    chain_id: 'slot:9', account_intent_id: 'a1', project_id: 12, project_name: 'Relisme',
    video_title: 'T', code: 'RLM-014', scheduled_date: '2026-05-20',
    attempts: [{ date: '2026-05-20', status: 'done', error_code: null, via_manual: false }],
  }];
  const cards = buildPlannerCards(intents, { from: '2026-05-18', to: '2026-05-24' });
  assert.ok(cards.length >= 1);
  assert.equal(cards[0].code, 'RLM-014');
});
```

- [ ] **Step 2: Run, verify FAIL**
Run: `node --test test_publish_planner.test.js`
Expected: FAIL — `cards[0].code` is `undefined`.

- [ ] **Step 3: Implement — `buildPlannerCards` + intent + 3 SQL**

3a. В начале `publish_planner.js` после `'use strict';` добавить:
```js
const { formatContentCode } = require('./content_code');
```

3b. В `buildPlannerCards`, в объект `cards.push({ ... })` (внутри основного цикла, где есть `project_name: meta.project_name,`) добавить:
```js
        code: meta.code || null,
```

3c. **Full-ветка** (`getPlannerCards`, запрос `qrows`): в SELECT после `COALESCE(ut.input_video_name, pq.title, pq.caption) AS video_title,` добавить:
```sql
             vc.code_number, COALESCE(vp.code_prefix, vp2.code_prefix) AS code_prefix,
```
и добавить join после `LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, NULL)`:
```sql
      LEFT JOIN validator_content vc ON vc.id = ut.content_id
```
В маппинге intent'ов (объект, возвращаемый `.map`, где `video_title: r.video_title,`) добавить:
```js
        code: formatContentCode(r.code_prefix, r.code_number),
```

3d. **Legacy-ветка** (`else`, GROUP BY-запрос): в SELECT после `COALESCE(ut.input_video_name, pq.title, pq.caption) AS video_title,` добавить:
```sql
             vc.code_number, COALESCE(vp.code_prefix, vp2.code_prefix) AS code_prefix,
```
добавить join после `LEFT JOIN unic_tasks ut ON ut.id = pq.unic_task_id`:
```sql
      LEFT JOIN validator_content vc ON vc.id = ut.content_id
```
заменить `GROUP BY 1,2,3,4,5` на:
```sql
      GROUP BY 1,2,3,4,5, vc.code_number, COALESCE(vp.code_prefix, vp2.code_prefix)
```
В соответствующем `cards.push({ ... })` (где `state: done === N ? ...`) добавить:
```js
        code: formatContentCode(r.code_prefix, r.code_number),
```

3e. **Plan-ветка** (`prows`, расписание): в SELECT после `COALESCE(vc.title, vc.description, '—') AS video_title,` добавить:
```sql
           vc.code_number, vp.code_prefix,
```
(`vc` и `vp` уже джойнятся.) В соответствующем `cards.push({ ... })` (где `state: mapContentState(r.content_status),`) добавить:
```js
      code: formatContentCode(r.code_prefix, r.code_number),
```

- [ ] **Step 4: Run pure, verify PASS**
Run: `node --test test_publish_planner.test.js`
Expected: ALL pass (новый + базлайн).

- [ ] **Step 5: Live smoke** — создать `test_planner_code_live.test.js`:
```js
'use strict';
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { getPlannerCards } = require('./publish_planner');
const pool = new Pool({ host: 'localhost', port: 5432, database: 'openclaw', user: 'openclaw', password: 'openclaw123' });

test('getPlannerCards: каждая карточка имеет ключ code (SQL не сломан)', { skip: !process.env.RUN_LIVE_DB }, async () => {
  const cards = await getPlannerCards(pool, { from: '2026-05-01', to: '2026-06-30' });
  for (const c of cards) assert.ok('code' in c, 'карточка без ключа code: ' + JSON.stringify(c).slice(0,120));
});
after(() => pool.end());
```

- [ ] **Step 6: Run live, verify PASS**
Run: `RUN_LIVE_DB=1 node --test test_planner_code_live.test.js`
Expected: PASS (карточки возвращаются, у всех есть ключ `code`).

- [ ] **Step 7: Commit**
```bash
cd /home/claude-user/wp213b-autowarm
git add publish_planner.js test_publish_planner.test.js test_planner_code_live.test.js
git commit -m "feat(wp213b): код ролика в карточках планировщика (3 ветки + buildPlannerCards)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Фронт планировщика (код только админам) + период в «Логе событий»

**Files:** Modify `public/index.html` (`plannerCardHtml`, `lcFilterRow`).

- [ ] **Step 1: Код в карточке планировщика только админам**
В `plannerCardHtml(c)`, внутри блока заголовка, сразу после строки с `🎬 ${plannerEsc(c.project_name || '—')}</div>` добавить:
```js
      ${(currentUser?.role === 'admin' && c.code) ? `<div class="text-gray-400 text-[10px] font-mono">${plannerEsc(c.code)}</div>` : ''}
```

- [ ] **Step 2: Период (date_to) в «Логе событий»**
В `lcFilterRow`, заменить ячейку «План.дата» (строка с `lcSetFilter('date_from', this.value)`) на две даты:
```js
    <td class="${fc}"><div class="flex flex-col gap-0.5"><input type="date" value="${esc(f.date_from||'')}" onchange="lcSetFilter('date_from', this.value)" class="border rounded px-1 py-0.5" title="с"><input type="date" value="${esc(f.date_to||'')}" onchange="lcSetFilter('date_to', this.value)" class="border rounded px-1 py-0.5" title="по"></div></td>
```
(Бэкенд `applyClientSideFilters`/эндпоинт уже обрабатывают `date_to` — не трогаем.)

- [ ] **Step 3: Sanity-check**
```bash
cd /home/claude-user/wp213b-autowarm
node -e "const s=require('fs').readFileSync('public/index.html','utf8');
if(!/currentUser\?\.role === 'admin' && c\.code/.test(s)) throw 'planner admin code gate missing';
if(!/lcSetFilter\('date_to', this\.value\)/.test(s)) throw 'log date_to missing';
console.log('OK');"
```
Expected: `OK`.

- [ ] **Step 4: Commit**
```bash
cd /home/claude-user/wp213b-autowarm
git add public/index.html
git commit -m "feat(wp213b): код в планировщике (admin) + период в Логе событий (date_to)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Регрессия

**Files:** нет (проверка).

- [ ] **Step 1: Pure-наборы B**
Run: `node --test test_content_code.test.js test_manual_code.test.js test_publish_planner.test.js`
Expected: все PASS, 0 fail.

- [ ] **Step 2: Live-наборы B**
Run: `RUN_LIVE_DB=1 node --test test_planner_code_live.test.js test_manual_publish_queue.test.js`
Expected: все PASS, 0 fail.

- [ ] **Step 3: Фронт-санити целиком** (все 4 правки фронта на месте)
```bash
cd /home/claude-user/wp213b-autowarm
grep -q "key: 'code'" public/index.html \
 && grep -q "code: r.code," public/index.html \
 && grep -q "currentUser?.role === 'admin' && c.code" public/index.html \
 && grep -q "lcSetFilter('date_to', this.value)" public/index.html \
 && echo "OK frontend" || echo "MISSING frontend edit"
```
Expected: `OK frontend`.

---

## После реализации

1. **Code review:** `superpowers:requesting-code-review` перед мержем.
2. **Деплой:** PR delivery-contenthunter → merge main → прод `git pull` в `/root/.openclaw/workspace-genri/autowarm` (owned claude-user, без sudo) + `sudo pm2 restart 35`. Без миграции.
3. **Verify в UI:** ручная выкладка — колонка «Код» + поиск по коду; планировщик под админом — код в карточке (под не-админом нет); «Лог событий» — фильтр диапазоном дат (с/по).
4. **OpenProject:** WP#213 закрывается полностью (A+B) → «Тестирование»/«Готово» по решению владельца. Обновить evidence/память.
