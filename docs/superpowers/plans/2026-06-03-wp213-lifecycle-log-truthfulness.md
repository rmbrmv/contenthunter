# WP#213 Правдивость «Лога событий» (под-проект A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать статусы «Лога событий» честными: убрать ложный «застрял в ручной» (2141 строк), показать реально застрявших в авто (LEX-012) и починить модалку «Лог аккаунта» (WAN-021) — правкой read-model и отрисовки, без миграции данных.

**Architecture:** Все три бага живут в `lifecycle.js` (read-model). Меняем (1) SQL-классификацию стадий в `rollupSql`/`accountsSql` через общий фрагмент `stageCaseSql`, (2) `deriveWorstState` — новый бейдж `stuck_auto`, (3) `buildTimeline` — терминальные точки. Всё за kill-switch `LIFECYCLE_TRUTHFUL_STAGE_ENABLED` (default ON), читаемым внутри функций `lifecycle.js` — поэтому `server.js` не меняется. Фронт `public/index.html` получает новый код статуса автоматически, добавляем только цвет бейджа и пункт фильтра.

**Tech Stack:** Node.js, `node:test` runner, PostgreSQL (`pg`), ванильный JS фронт. Тесты: `node --test` (pure + live за `RUN_LIVE_DB`).

**Репо:** `delivery-contenthunter` (локально `/home/claude-user/autowarm-testbench`). Файлы: `lifecycle.js`, `test_lifecycle_pure.test.js`, `test_lifecycle_live.test.js`, `public/index.html`.

---

## Setup (перед Task 1)

Реализацию вести в изолированном worktree кода (не в общем `/home/claude-user/autowarm-testbench`, который делят параллельные сессии).

- [ ] **Создать worktree** (через superpowers:using-git-worktrees или вручную):

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin --quiet
git worktree add -b wp213-lifecycle-truthful /home/claude-user/wp213-autowarm origin/main
cd /home/claude-user/wp213-autowarm && git branch --show-current
```
Expected: `wp213-lifecycle-truthful`. Все пути в задачах ниже — относительно этого worktree.

- [ ] **Sanity: тесты lifecycle зелёные на старте**

Run: `cd /home/claude-user/wp213-autowarm && node --test test_lifecycle_pure.test.js`
Expected: все тесты PASS (базлайн).

---

## Task 1: Хелпер kill-switch `truthfulStageEnabled()`

**Files:**
- Modify: `lifecycle.js` (добавить функцию + экспорт)
- Test: `test_lifecycle_pure.test.js`

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `test_lifecycle_pure.test.js`:
```js
const { truthfulStageEnabled } = require('./lifecycle');
test('truthfulStageEnabled: default ON, выключается только явным false', () => {
  assert.equal(truthfulStageEnabled({}), true);
  assert.equal(truthfulStageEnabled({ LIFECYCLE_TRUTHFUL_STAGE_ENABLED: 'true' }), true);
  assert.equal(truthfulStageEnabled({ LIFECYCLE_TRUTHFUL_STAGE_ENABLED: 'false' }), false);
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test test_lifecycle_pure.test.js`
Expected: FAIL — `truthfulStageEnabled is not a function`.

- [ ] **Step 3: Реализовать**

В `lifecycle.js` после `stuckDaysFromSettings` (после строки 8) добавить:
```js
function truthfulStageEnabled(env) {
  const e = env || process.env;
  return e.LIFECYCLE_TRUTHFUL_STAGE_ENABLED !== 'false';
}
```
Добавить `truthfulStageEnabled` в `module.exports` (строка 201).

- [ ] **Step 4: Запустить — убедиться что прошёл**

Run: `node --test test_lifecycle_pure.test.js`
Expected: PASS (все, включая новый).

- [ ] **Step 5: Коммит**

```bash
git add lifecycle.js test_lifecycle_pure.test.js
git commit -m "feat(wp213): kill-switch truthfulStageEnabled (default ON)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `deriveWorstState` — бейдж «ЗАСТРЯЛ В АВТО» (баг 1)

**Files:**
- Modify: `lifecycle.js` (`deriveWorstState`)
- Test: `test_lifecycle_pure.test.js`

- [ ] **Step 1: Написать падающие тесты**

Сначала обновить хелпер `mk` (строки 14-18) — добавить поле `max_auto_days:null`:
```js
const mk = (o) => Object.assign({
  total_accounts: 0, s_planned:0, s_uniq:0, s_autoqueue:0, s_autopub:0,
  s_manualqueue:0, s_manualinprog:0, s_published:0, s_notpublished:0,
  max_manual_days:null, max_uniq_days:null, max_auto_days:null, max_stage_days:null
}, o);
```
Добавить тесты после теста `worst-state: застрял на уникализации` (после строки 22):
```js
test('worst-state: застрял в авто (auto > N дней)', () => {
  assert.equal(deriveWorstState(mk({total_accounts:4, s_autopub:3, s_published:1, max_auto_days:5}), 2, true).code, 'stuck_auto');
});
test('worst-state: stuck_auto не срабатывает при выключенном kill-switch', () => {
  const w = deriveWorstState(mk({total_accounts:4, s_autopub:3, s_published:1, max_auto_days:5}), 2, false);
  assert.equal(w.code, 'working');
});
test('worst-state: stuck_manual приоритетнее stuck_auto', () => {
  assert.equal(deriveWorstState(mk({total_accounts:4, s_manualqueue:2, s_autopub:2, max_manual_days:5, max_auto_days:5}), 2, true).code, 'stuck_manual');
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test test_lifecycle_pure.test.js`
Expected: FAIL — `stuck_auto`-тесты падают (сейчас вернётся `working`).

- [ ] **Step 3: Реализовать**

В `lifecycle.js` заменить сигнатуру и тело `deriveWorstState` (строки 25-45). Новая версия:
```js
function deriveWorstState(row, N, enabled) {
  const on = (enabled === undefined) ? truthfulStageEnabled() : enabled;
  const total = Number(row.total_accounts || 0);
  const pub = Number(row.s_published || 0);
  const notpub = Number(row.s_notpublished || 0);
  const planned = Number(row.s_planned || 0);
  const maxManual = row.max_manual_days == null ? null : Number(row.max_manual_days);
  const maxUniq = row.max_uniq_days == null ? null : Number(row.max_uniq_days);
  const maxAuto = row.max_auto_days == null ? null : Number(row.max_auto_days);
  const autoActive = Number(row.s_autoqueue||0) + Number(row.s_autopub||0);
  const manualActive = Number(row.s_manualqueue||0) + Number(row.s_manualinprog||0);
  if (total > 0 && pub === total) return { code: 'published', label: 'ПОЛНОСТЬЮ ВЫЛОЖЕН' };
  if (total > 0 && notpub === total) return { code: 'not_published', label: 'НЕ ВЫЛОЖЕН' };
  if (maxManual != null && maxManual > N) return { code: 'stuck_manual', label: 'ЗАСТРЯЛ В РУЧНОЙ' };
  if (maxUniq != null && maxUniq > N) return { code: 'stuck_uniq', label: 'ЗАСТРЯЛ НА УНИКАЛИЗАЦИИ' };
  if (on && maxAuto != null && maxAuto > N) return { code: 'stuck_auto', label: 'ЗАСТРЯЛ В АВТО' };
  if (autoActive > 0 || manualActive > 0) {
    const mode = autoActive > 0 && manualActive > 0 ? 'both' : (autoActive > 0 ? 'auto' : 'manual');
    const sub = mode === 'both' ? 'оба' : (mode === 'auto' ? 'в авто' : 'в ручной');
    return { code: 'working', mode, label: `В РАБОТЕ (${sub})` };
  }
  if (planned > 0) return { code: 'planned', label: 'ЗАПЛАНИРОВАН' };
  return { code: 'planned', label: 'ЗАПЛАНИРОВАН' };
}
```

- [ ] **Step 4: Запустить — убедиться что прошёл**

Run: `node --test test_lifecycle_pure.test.js`
Expected: PASS (все, включая 3 новых; старые worst-state без 3-го аргумента работают — default = env ON).

- [ ] **Step 5: Коммит**

```bash
git add lifecycle.js test_lifecycle_pure.test.js
git commit -m "feat(wp213): deriveWorstState — бейдж ЗАСТРЯЛ В АВТО (баг 1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `buildTimeline` — терминальные точки (баг 6)

**Files:**
- Modify: `lifecycle.js` (`buildTimeline`)
- Test: `test_lifecycle_pure.test.js`

- [ ] **Step 1: Написать падающие тесты**

Добавить после существующего теста `buildTimeline` (после строки 68):
```js
test('buildTimeline: отменённый аккаунт без попыток → последняя точка «Не выложен», а не «Запланирован»', () => {
  const pq = { scheduled_at:'2026-05-25T09:00:00Z', created_at:'2026-05-25T09:00:00Z', updated_at:'2026-05-26T10:00:00Z', manual_handoff_at:null, status:'cancelled' };
  const pts = buildTimeline({ pq, attempts: [], mq: null, enabled: true });
  const last = pts[pts.length-1];
  assert.equal(last.current, true);
  assert.ok(/Не выложен/.test(last.stage), 'последняя точка — Не выложен, получено: '+last.stage);
});
test('buildTimeline: published_auto → «Выложен (авто)»', () => {
  const pq = { scheduled_at:'2026-05-25T09:00:00Z', created_at:'2026-05-25T09:00:00Z', updated_at:'2026-05-26T10:00:00Z', manual_handoff_at:'2026-05-25T12:00:00Z', status:'failed' };
  const mq = { taken_at:null, taken_by_id:null, published_at:null, operator_status:'published_auto' };
  const pts = buildTimeline({ pq, attempts: [], mq, enabled: true });
  const last = pts[pts.length-1];
  assert.ok(/Выложен/.test(last.stage), 'ожидали Выложен, получено: '+last.stage);
});
test('buildTimeline: failed + handoff + нет живого mq → «слетел из ручной»', () => {
  const pq = { scheduled_at:'2026-05-25T09:00:00Z', created_at:'2026-05-25T09:00:00Z', updated_at:'2026-05-26T10:00:00Z', manual_handoff_at:'2026-05-25T12:00:00Z', status:'failed' };
  const pts = buildTimeline({ pq, attempts: [], mq: null, enabled: true });
  const last = pts[pts.length-1];
  assert.ok(/слетел из ручной/.test(last.stage), 'получено: '+last.stage);
});
test('buildTimeline: при выключенном kill-switch терминальная точка не добавляется', () => {
  const pq = { scheduled_at:'2026-05-25T09:00:00Z', created_at:'2026-05-25T09:00:00Z', updated_at:'2026-05-26T10:00:00Z', manual_handoff_at:null, status:'cancelled' };
  const pts = buildTimeline({ pq, attempts: [], mq: null, enabled: false });
  assert.ok(/Запланирован/.test(pts[pts.length-1].stage));
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test test_lifecycle_pure.test.js`
Expected: FAIL — новые `buildTimeline`-тесты (сейчас последняя точка = «Запланирован»).

- [ ] **Step 3: Реализовать**

В `lifecycle.js` заменить `buildTimeline` (строки 145-159) на:
```js
function buildTimeline({ pq, attempts, mq, enabled }) {
  const on = (enabled === undefined) ? truthfulStageEnabled() : enabled;
  const pts = [];
  if (pq.scheduled_at || pq.created_at) pts.push({ at: pq.scheduled_at || pq.created_at, stage:'📅 Запланирован', ctx:'' });
  (attempts||[]).forEach((a, i) => pts.push({
    at: a.created_at, stage:'🤖 Авто-публикация',
    ctx: `попытка №${i+1}` + (a.error_code ? ` · ошибка ${a.error_code}` : ''),
  }));
  if (pq.manual_handoff_at) pts.push({ at: pq.manual_handoff_at, stage:'📋 Передан в ручную', ctx:'' });
  if (mq && mq.taken_at) pts.push({ at: mq.taken_at, stage:'✋ На ручной выкладке', ctx: mq.taken_by_id ? ('оператор #'+mq.taken_by_id) : '' });

  let published = false;
  if (mq && mq.published_at) { pts.push({ at: mq.published_at, stage:'✅ Выложен', ctx:'' }); published = true; }
  else if (mq && mq.operator_status === 'published_auto') { pts.push({ at: pq.updated_at, stage:'✅ Выложен (авто, отмечен оператором)', ctx:'' }); published = true; }
  else if (pq.status === 'done') { pts.push({ at: pq.updated_at, stage:'✅ Выложен', ctx:'авто' }); published = true; }

  // Терминальные негативные состояния — иначе модалка ложно заканчивается на «Запланирован» (баг 6)
  if (on && !published) {
    if (['cancelled','skipped','past_slot_dropped'].includes(pq.status)) {
      pts.push({ at: pq.updated_at, stage:'⛔ Не выложен', ctx:'' });
    } else if (pq.manual_handoff_at && !(mq && (mq.operator_status === 'queued' || mq.operator_status === 'in_progress'))) {
      pts.push({ at: pq.updated_at, stage:'⛔ Не выложен (слетел из ручной)', ctx:'' });
    }
  }

  pts.sort((a,b) => new Date(a.at||0) - new Date(b.at||0));
  if (pts.length) pts[pts.length-1].current = true;
  return pts;
}
```

- [ ] **Step 4: Запустить — убедиться что прошёл**

Run: `node --test test_lifecycle_pure.test.js`
Expected: PASS (все, включая 4 новых и старый buildTimeline-тест).

- [ ] **Step 5: Коммит**

```bash
git add lifecycle.js test_lifecycle_pure.test.js
git commit -m "fix(wp213): buildTimeline рисует терминальные состояния (баг 6 WAN-021)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Stage-логика SQL — общий `stageCaseSql` + фикс + `max_auto_days` (баг 4)

**Files:**
- Modify: `lifecycle.js` (`rollupSql`, `accountsSql`, новый `stageCaseSql`)
- Test: `test_lifecycle_live.test.js` (live, за `RUN_LIVE_DB`)

- [ ] **Step 1: Написать падающий live-тест-инвариант**

Добавить в `test_lifecycle_live.test.js` перед `after(...)`:
```js
const { stageCaseSql } = require('./lifecycle');
test('stageCaseSql(true): нет строк stage=5 без живой mq (баг 4)', { skip: !process.env.RUN_LIVE_DB }, async () => {
  const stage = stageCaseSql(true);
  const q = `
    SELECT COUNT(*)::int AS bad FROM publish_queue pq
    LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
    LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
    LEFT JOIN validator_schedule_slots s ON s.id = NULLIF(ut.meta->>'slot_id','')::int
    LEFT JOIN validator_manual_publish_queue mq
      ON mq.content_id = ut.content_id AND mq.account_username = pq.account_username
     AND LOWER(mq.platform)=LOWER(pq.platform) AND mq.cancelled_at IS NULL
    WHERE ut.content_id IS NOT NULL AND (${stage}) = 5 AND mq.id IS NULL`;
  const { rows } = await pool.query(q);
  assert.equal(rows[0].bad, 0, 'stage=5 должен требовать живую mq-строку');
});
test('stageCaseSql(true): published_auto классифицируется как stage 7', { skip: !process.env.RUN_LIVE_DB }, async () => {
  const stage = stageCaseSql(true);
  const q = `
    SELECT COUNT(*)::int AS bad FROM publish_queue pq
    LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
    LEFT JOIN unic_tasks ut ON ut.id = COALESCE(pq.unic_task_id, ur.task_id)
    LEFT JOIN validator_schedule_slots s ON s.id = NULLIF(ut.meta->>'slot_id','')::int
    LEFT JOIN validator_manual_publish_queue mq
      ON mq.content_id = ut.content_id AND mq.account_username = pq.account_username
     AND LOWER(mq.platform)=LOWER(pq.platform) AND mq.cancelled_at IS NULL
    WHERE ut.content_id IS NOT NULL AND mq.operator_status='published_auto' AND (${stage}) <> 7`;
  const { rows } = await pool.query(q);
  assert.equal(rows[0].bad, 0, 'published_auto = Выложен (stage 7)');
});
test('rollupSql: содержит max_auto_days', { skip: !process.env.RUN_LIVE_DB }, async () => {
  const { rows } = await pool.query(rollupSql() + ' LIMIT 1');
  assert.ok(rows.length === 0 || 'max_auto_days' in rows[0]);
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `RUN_LIVE_DB=1 node --test test_lifecycle_live.test.js`
Expected: FAIL — `stageCaseSql is not a function` (и/или `bad` > 0 на старой логике).

- [ ] **Step 3: Реализовать**

В `lifecycle.js` добавить общий фрагмент (перед `rollupSql`, после строки 45):
```js
function stageCaseSql(enabled) {
  const on = (enabled === undefined) ? truthfulStageEnabled() : enabled;
  if (!on) {
    // старая логика (для отката kill-switch)
    return `CASE
      WHEN pq.status='done' OR mq.operator_status='published' OR s.matched_post_url IS NOT NULL THEN 7
      WHEN mq.operator_status='in_progress' THEN 6
      WHEN pq.status IN ('cancelled','skipped','past_slot_dropped') THEN 8
      WHEN pq.manual_handoff_at IS NOT NULL THEN 5
      WHEN pq.status IN ('running','failed') THEN 4
      WHEN pq.publish_task_id IS NOT NULL THEN 3
      WHEN ur.status IS NULL OR ur.status NOT IN ('ready','done') THEN 2
      ELSE 1 END`;
  }
  return `CASE
    WHEN pq.status='done' OR mq.operator_status IN ('published','published_auto') OR s.matched_post_url IS NOT NULL THEN 7
    WHEN mq.operator_status='in_progress' THEN 6
    WHEN mq.id IS NOT NULL AND mq.operator_status='queued' THEN 5
    WHEN pq.status IN ('cancelled','skipped','past_slot_dropped') THEN 8
    WHEN pq.manual_handoff_at IS NOT NULL AND mq.id IS NULL THEN 8
    WHEN pq.status IN ('running','failed') THEN 4
    WHEN pq.publish_task_id IS NOT NULL THEN 3
    WHEN ur.status IS NULL OR ur.status NOT IN ('ready','done') THEN 2
    ELSE 1 END`;
}
```
Добавить `stageCaseSql` в `module.exports`.

В `rollupSql` (строки 47-112): заменить inline-CASE для `stage` (строки 53-62) на `${stageCaseSql()} AS stage,`. Добавить агрегат в CTE `rollup` после `max_uniq_days` (после строки 97):
```js
    MAX(EXTRACT(EPOCH FROM (now()-stage_since))/86400.0) FILTER (WHERE stage IN (3,4))     AS max_auto_days,
```

В `accountsSql` (строки 114-143): заменить inline-CASE для `stage` (строки 119-128) на `${stageCaseSql()} AS stage,`.

> Примечание: `stage_since` CASE (строки 63-71) не меняем — терминальные стадии (7,8) не участвуют в `max_*` фильтрах, поэтому возраст «слетевших из ручной» не искажает метрики.

- [ ] **Step 4: Запустить — убедиться что прошёл**

Run: `RUN_LIVE_DB=1 node --test test_lifecycle_live.test.js`
Expected: PASS — `bad=0` в обоих инвариантах, `max_auto_days` присутствует, инвариант суммы сегментов держится.

- [ ] **Step 5: Коммит**

```bash
git add lifecycle.js test_lifecycle_live.test.js
git commit -m "fix(wp213): stageCaseSql — stage 5 требует живую mq, handoff-без-mq → Не выложен, +published_auto, +max_auto_days (баг 4)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Фронт — цвет бейджа + пункт фильтра «Застрял в авто»

**Files:**
- Modify: `public/index.html` (`LC_BADGE` строки 7060-7062, `STATUS_OPTS` строка 7103)

- [ ] **Step 1: Добавить цвет бейджа `stuck_auto`**

В `public/index.html` заменить объект `LC_BADGE` (строки 7060-7062) на:
```js
const LC_BADGE = { published:'bg-green-100 text-green-700', not_published:'bg-gray-200 text-gray-600',
  stuck_manual:'bg-red-100 text-red-700', stuck_uniq:'bg-orange-100 text-orange-700',
  stuck_auto:'bg-amber-100 text-amber-800',
  working:'bg-blue-100 text-blue-700', planned:'bg-gray-100 text-gray-500' };
```

- [ ] **Step 2: Добавить пункт фильтра**

В `public/index.html` в `lcFilterRow` заменить строку `const STATUS_OPTS = ...` (строка 7103) на:
```js
  const STATUS_OPTS = [['stuck_manual','Застрял в ручной'],['stuck_auto','Застрял в авто'],['stuck_uniq','Застрял на уник.'],['working','В работе'],['published','Выложен'],['not_published','Не выложен'],['planned','Запланирован']];
```

- [ ] **Step 3: Проверка синтаксиса JS внутри HTML**

Run: `node -e "const s=require('fs').readFileSync('public/index.html','utf8'); const m=s.match(/const LC_BADGE[\s\S]*?planned:'bg-gray-100 text-gray-500' };/); if(!m) throw new Error('LC_BADGE не найден'); if(!/stuck_auto/.test(m[0])) throw new Error('stuck_auto не добавлен'); console.log('OK');"`
Expected: `OK`.

- [ ] **Step 4: Коммит**

```bash
git add public/index.html
git commit -m "feat(wp213): фронт — бейдж и фильтр «Застрял в авто»

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Регрессия — полный прогон тестов lifecycle

**Files:** нет (проверка)

- [ ] **Step 1: Pure-тесты**

Run: `node --test test_lifecycle_pure.test.js`
Expected: все PASS, 0 fail.

- [ ] **Step 2: Live-тесты**

Run: `RUN_LIVE_DB=1 node --test test_lifecycle_live.test.js`
Expected: все PASS, 0 fail.

- [ ] **Step 3: Прогон при выключенном kill-switch (откат не ломает базлайн)**

Run: `LIFECYCLE_TRUTHFUL_STAGE_ENABLED=false node --test test_lifecycle_pure.test.js`
Expected: PASS (тесты, завязанные на `enabled:true`/`false` явно, проходят; тесты без явного флага используют env).

> Если какой-то pure-тест зависит от env-дефолта и падает при OFF — это ожидаемо только для тестов, передающих `enabled` неявно; в наших новых тестах флаг передаётся явно, поэтому падений быть не должно.

---

## После реализации

1. **Code review:** `superpowers:requesting-code-review` перед мержем.
2. **Деплой (после ревью+мержа в main):** git pull в прод-каталог автоварма на этом хосте; `sudo pm2 restart` id35 (read-model грузится в процессе server.js → рестарт нужен). Без миграции данных.
3. **Verify в UI:** открыть Аналитика → 📜 Лог событий:
   - число роликов «ЗАСТРЯЛ В РУЧНОЙ» упало с ~226 до реальных (живые mq queued);
   - LEX-012 = «ЗАСТРЯЛ В АВТО»;
   - WAN-021: модалка «Лог аккаунта» отменённого аккаунта = «Не выложен», а не «Запланирован».
4. **OpenProject:** WP#213 (под-проект A) → «Тестирование», прокомментировать. Под-проект B (п.2/3/5) — отдельный спек/план/PR.
