# WP#221 — UTC/MSK-сдвиг в дашбордах: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Исправить группировку по дате во всех 9 местах, где naive-UTC колонка (`created_at`/`scheduled_at`) ошибочно переводится в МСК одинарным `AT TIME ZONE 'Europe/Moscow'` (вычитает 3ч вместо прибавления → дата уезжает у полуночи).

**Architecture:** Вводим вторую типобезопасную SQL-константу `MSK_FROM_UTC = AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow'` для naive-UTC колонок; старую `MSK` оставляем только для timestamptz-колонок (с предупреждающим комментарием). Меняем 8 мест в `publish_planner.js` и 1 в `server.js`. Без миграции, без kill-switch (read-only отчётность).

**Tech Stack:** Node.js, `pg` (Pool localhost/openclaw), тест-раннер `node:test` (`node --test --test-force-exit <file>`), Postgres.

**Репозиторий кода:** `delivery-contenthunter` (autowarm). Прод-каталог `/root/.openclaw/workspace-genri/autowarm`. Правки вести в **изолированном git worktree** (защита от гонки общего checkout с параллельными IG/YT/TT-сессиями — см. память `feedback_shared_worktree_checkout_race`).

**Спека:** `docs/superpowers/specs/2026-06-04-wp221-dashboard-utc-msk-date-design.md`

**Полный инвентарь (типы колонок подтверждены через `information_schema.columns`):**

| Файл:строка | Колонка | Тип | Действие |
|---|---|---|---|
| publish_planner.js:155,156,163,222,230,265 | `pq.scheduled_at` ×6 | naive-UTC | `${MSK}` → `${MSK_FROM_UTC}` |
| publish_planner.js:173 | `created_at` (publish_tasks) | naive-UTC | `${MSK}` → `${MSK_FROM_UTC}` |
| publish_planner.js:300 | `created_at` (publish_tasks) | naive-UTC | литерал → рецепт |
| server.js:2728 | `pt.created_at` | naive-UTC | литерал → рецепт |
| publish_planner.js:157 | `manual_handoff_at` | timestamptz | **НЕ трогать** (`MSK` корректна) |
| publish_planner.js:187,190 | `q.published_at` | timestamptz | **НЕ трогать** |
| server.js:1341 | `h.hour` | timestamptz | **НЕ трогать** |

---

## Предварительный шаг: изолированный worktree

Перед Task 1 создать worktree через `superpowers:using-git-worktrees` для репозитория `/root/.openclaw/workspace-genri/autowarm` на новой ветке `wp221-dashboard-utc-msk-date`. Все правки кода и тесты — внутри worktree. Прод-каталог (main) не трогаем до деплоя.

---

## Task 1: Ввести `MSK_FROM_UTC` + снэпшот-тесты рецепта

**Files:**
- Modify: `publish_planner.js:138` (добавить константу), `publish_planner.js:322` (экспорт)
- Test: `test_wp221_dashboard_tz.test.js` (создать в корне репозитория)

- [ ] **Step 1: Написать падающий тест (снэпшоты 1 и 2)**

Создать `test_wp221_dashboard_tz.test.js`:

```js
// Run: node --test --test-force-exit test_wp221_dashboard_tz.test.js
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { MSK, MSK_FROM_UTC } = require('./publish_planner');
const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

after(async () => { await pool.end(); });

// Снэпшот 1: naive-UTC через MSK_FROM_UTC → корректная МСК-дата.
// 2026-06-04 22:30 UTC = 2026-06-05 01:30 МСК → бизнес-день 05-е.
test('MSK_FROM_UTC: naive-UTC у полуночи даёт следующий МСК-день', async () => {
  const { rows } = await pool.query(
    `SELECT (TIMESTAMP '2026-06-04 22:30:00' ${MSK_FROM_UTC})::date::text AS d`);
  assert.equal(rows[0].d, '2026-06-05');
});

// Снэпшот 2 (регрессия нетронутых мест): timestamptz через MSK → корректно.
// 2026-06-04 22:30 UTC как timestamptz = 01:30 МСК 05-го → 05-е.
test('MSK: timestamptz у полуночи остаётся корректным', async () => {
  const { rows } = await pool.query(
    `SELECT (TIMESTAMPTZ '2026-06-04 22:30:00+00' ${MSK})::date::text AS d`);
  assert.equal(rows[0].d, '2026-06-05');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit test_wp221_dashboard_tz.test.js`
Expected: FAIL — `MSK_FROM_UTC` is undefined (импорт `undefined` → SQL-синтакс-ошибка/`undefined` в строке).

- [ ] **Step 3: Добавить константу и экспорт**

В `publish_planner.js`, строка 138 — заменить определение `MSK` на пару констант:

```js
// naive-UTC колонки (created_at, scheduled_at — значения по Гринвичу в timestamp without time zone):
// сначала пометить как UTC, затем перевести в МСК. См. WP#220/#221.
const MSK_FROM_UTC = `AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow'`;
// ⚠ КОРРЕКТНО ТОЛЬКО для timestamptz-колонок (manual_handoff_at, published_at).
//    Для naive-UTC использовать MSK_FROM_UTC, иначе дата уезжает на сутки у полуночи.
const MSK = `AT TIME ZONE 'Europe/Moscow'`;
```

В `publish_planner.js:322` — добавить обе константы в экспорт:

```js
module.exports = { buildPlannerCards, deriveTransferColumns, getPlannerCards, attachQueueTransferColumns, SUCCESS_STATUSES, MSK, MSK_FROM_UTC };
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit test_wp221_dashboard_tz.test.js`
Expected: PASS (2/2).

- [ ] **Step 5: Коммит**

```bash
git add publish_planner.js test_wp221_dashboard_tz.test.js
git commit -m "feat(wp221): MSK_FROM_UTC для naive-UTC дат + снэпшот-тесты рецепта"
```

---

## Task 2: Смок планировщика (RED) + фикс 8 мест в publish_planner.js (GREEN)

**Files:**
- Modify: `publish_planner.js` строки 155, 156, 163, 173, 222, 230, 265 (`${MSK}` → `${MSK_FROM_UTC}`), 300 (литерал → рецепт)
- Test: `test_wp221_dashboard_tz.test.js` (дополнить смоком)

- [ ] **Step 1: Дописать падающий смок-тест планировщика**

Добавить в `test_wp221_dashboard_tz.test.js`:

```js
const { getPlannerCards } = require('./publish_planner');

const PID=992210, CONTENT=9922100, SLOT=9922100, TASK=9922100, RESULT=9922100, PQ=9922100;
const CPID='aaaaaaaa-0000-0000-0000-000000099221';

async function cleanupSmoke(){
  await pool.query('DELETE FROM publish_queue WHERE id=$1',[PQ]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1',[TASK]).catch(()=>{});
  await pool.query('DELETE FROM validator_schedule_slots WHERE id=$1',[SLOT]).catch(()=>{});
  await pool.query('DELETE FROM validator_content WHERE id=$1',[CONTENT]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1',[PID]).catch(()=>{});
}

// Смок: строка очереди с полуночным scheduled_at (22:30 UTC = 01:30 МСК 05-го)
// должна группироваться под business_date = '2026-06-05', а слот '2026-06-05' матчиться (нет фантома).
test('SMOKE: планировщик группирует полуночный scheduled_at в верный МСК-день', async () => {
  await cleanupSmoke();
  await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,'WP221','wp221',true,false)`,[PID]);
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'wp221','approved','video',1)`,[CONTENT,PID]);
  await pool.query(`INSERT INTO validator_schedule_slots (id,project_id,slot_date,slot_position,content_id,slot_type,status,manual_publish) VALUES ($1,$2,DATE '2026-06-05',1,$3,'client','filled',false)`,[SLOT,PID,CONTENT]);
  await pool.query(`INSERT INTO unic_tasks (id,content_id,project_id,slot_date,current_status,meta) VALUES ($1,$2,$3,DATE '2026-06-05','done',jsonb_build_object('slot_id',$4::text))`,[TASK,CONTENT,PID,SLOT]);
  await pool.query(`INSERT INTO unic_results (id,task_id,scheme_id,output_url,status,created_at) VALUES ($1,$2,NULL,'https://x/y.mp4','done',now())`,[RESULT,TASK]);
  await pool.query(`INSERT INTO publish_queue (id,unic_result_id,unic_task_id,project_id,account_username,platform,device_serial,media_url,scheduled_at,status,client_publish_id)
                    VALUES ($1,$2,$3,$4,'acc','instagram','SER','https://x/y.mp4',TIMESTAMP '2026-06-04 22:30:00','pending',$5)`,[PQ,RESULT,TASK,PID,CPID]);

  const cards = await getPlannerCards(pool, { from:'2026-06-01', to:'2026-06-30', projectIds:[PID] });
  const ours = cards.filter(c => c.business_date === '2026-06-05');
  assert.ok(ours.length >= 1, 'ожидали карточку под 2026-06-05');
  assert.equal(cards.some(c => c.business_date === '2026-06-04'), false, 'не должно быть карточки под 2026-06-04');

  await cleanupSmoke();
});
```

- [ ] **Step 2: Запустить смок — убедиться, что падает (баг)**

Run: `node --test --test-force-exit test_wp221_dashboard_tz.test.js`
Expected: FAIL на SMOKE — текущий код даёт `business_date = '2026-06-04'` (баг), карточки под `2026-06-05` нет.

- [ ] **Step 3: Применить рецепт к 8 местам в publish_planner.js**

Заменить `${MSK}` → `${MSK_FROM_UTC}` ровно в этих строках (только `scheduled_at`/`created_at`, **НЕ** трогать 157/187/190):

- Стр. 155: `…'proj:'||pq.project_id::text||':'||(pq.scheduled_at ${MSK_FROM_UTC})::date::text) AS chain_id,`
- Стр. 156: `(pq.scheduled_at ${MSK_FROM_UTC})::date::text AS scheduled_date,`
- Стр. 163: `WHERE (pq.scheduled_at ${MSK_FROM_UTC})::date BETWEEN ($1::date - INTERVAL '3 days') AND $2::date`
- Стр. 173: `(created_at ${MSK_FROM_UTC})::date::text AS date, status, error_code`
- Стр. 222: `(pq.scheduled_at ${MSK_FROM_UTC})::date::text AS business_date,`
- Стр. 230: `WHERE (pq.scheduled_at ${MSK_FROM_UTC})::date BETWEEN $1::date AND $2::date`
- Стр. 265: `AND (pq.scheduled_at ${MSK_FROM_UTC})::date = s.slot_date`

Строка 300 — литерал на рецепт:

```js
             (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date::text AS date, error_code
```

- [ ] **Step 4: Запустить смок — убедиться, что проходит**

Run: `node --test --test-force-exit test_wp221_dashboard_tz.test.js`
Expected: PASS (3/3, включая SMOKE).

- [ ] **Step 5: Регрессия планировщика**

Run: `node --test --test-force-exit test_planner*.test.js test_publish_planner*.test.js 2>/dev/null || node --test --test-force-exit $(ls test_*planner*.test.js 2>/dev/null)`
Expected: PASS, без новых падений. (Если planner-тестов нет — пропустить, отметив это.)

- [ ] **Step 6: Коммит**

```bash
git add publish_planner.js test_wp221_dashboard_tz.test.js
git commit -m "fix(wp221): naive-UTC даты планировщика через MSK_FROM_UTC (8 мест) + смок"
```

---

## Task 3: Снэпшот фильтра `business_date` + фикс server.js:2728

**Files:**
- Modify: `server.js:2728`
- Test: `test_wp221_dashboard_tz.test.js` (дополнить снэпшотом 3)

- [ ] **Step 1: Дописать снэпшот-тест фильтра (доказывает рецепт и необходимость)**

Добавить в `test_wp221_dashboard_tz.test.js`:

```js
// Снэпшот 3 (server.js:2728): фильтр business_date по naive-UTC created_at.
// Строка 22:30 UTC (=01:30 МСК 05-го) должна попадать в business_date='2026-06-05'
// по НОВОМУ рецепту и НЕ попадать по СТАРОМУ (литерал AT TIME ZONE 'Europe/Moscow').
test('business_date filter: рецепт UTC→MSK ловит полуночную строку, старый — нет', async () => {
  const ts = `TIMESTAMP '2026-06-04 22:30:00'`;
  const fixed = await pool.query(
    `SELECT (${ts} AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date = DATE '2026-06-05' AS hit`);
  const old = await pool.query(
    `SELECT (${ts} AT TIME ZONE 'Europe/Moscow')::date = DATE '2026-06-05' AS hit`);
  assert.equal(fixed.rows[0].hit, true,  'новый рецепт должен матчить 05-е');
  assert.equal(old.rows[0].hit,   false, 'старый приём ошибочно НЕ матчит 05-е (баг)');
});
```

- [ ] **Step 2: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit test_wp221_dashboard_tz.test.js`
Expected: PASS (4/4). Тест характеризует баг и фиксирует корректный рецепт (прямой SQL — RED не требуется, правка кода ниже мерж-механическая).

- [ ] **Step 3: Применить рецепт к server.js:2728**

Заменить строку 2728:

```js
    push("(pt.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date = $?::date", String(query.business_date));
```

- [ ] **Step 4: Проверить синтаксис server.js**

Run: `node --check server.js`
Expected: без ошибок (exit 0).

- [ ] **Step 5: Коммит**

```bash
git add server.js test_wp221_dashboard_tz.test.js
git commit -m "fix(wp221): business_date-фильтр (server.js) через рецепт UTC→MSK + снэпшот"
```

---

## Task 4: Финальная верификация и деплой

- [ ] **Step 1: Полный прогон нового тест-файла**

Run: `node --test --test-force-exit test_wp221_dashboard_tz.test.js`
Expected: PASS 4/4.

- [ ] **Step 2: Греп-проверка — не осталось naive-UTC + одинарного AT TIME ZONE**

Run:
```bash
grep -n "scheduled_at ${MSK}\|created_at ${MSK}\|created_at AT TIME ZONE 'Europe/Moscow'" publish_planner.js server.js
```
Expected: пусто (все naive-места переведены). Места `manual_handoff_at`/`published_at`/`h.hour` остаются на `MSK`/одинарном — это корректно.

- [ ] **Step 3: Слить worktree-ветку в прод-main и задеплоить**

Через `superpowers:finishing-a-development-branch`: смерджить `wp221-dashboard-utc-msk-date` в `main` репозитория delivery-contenthunter (неразрушающим merge — на проде общий main с параллельными сессиями).

Деплой:
```bash
cd /root/.openclaw/workspace-genri/autowarm && git pull --rebase
sudo pm2 restart 35
```
Миграции нет.

- [ ] **Step 4: Прод-смок**

Открыть планировщик и «Лог событий» в UI; убедиться, что у полуночной границы строки в корректных МСК-сутках и фантомные плановые карточки у полуночных слотов исчезли. (Финальная приёмка — за Данилом.)

- [ ] **Step 5: OpenProject**

Перевести OP#221 → «Тестирование», комментарий со ссылкой на коммиты/PR.

- [ ] **Step 6: Доки**

Добавить запись в rmbrmv/contenthunter (доки-репозиторий) отдельным PR/коммитом; обновить память проекта.

---

## Self-Review (выполнено при написании)

- **Покрытие спеки:** все 9 🔴-мест → Task 2 (8) + Task 3 (1); 4 🟢-места явно не трогаются (Task 2 Step 3 + Task 4 Step 2 грепом). Константа-ловушка устранена (Task 1). Тесты = 3 снэпшота + 1 смок (как согласовано).
- **Плейсхолдеры:** нет — весь код тестов и правок приведён дословно, команды с ожидаемым выводом.
- **Согласованность типов/имён:** `MSK_FROM_UTC`/`MSK` едины во всех тасках; `getPlannerCards(pool,{from,to,projectIds})` и поле карточки `business_date` соответствуют коду.
- **Без kill-switch / без миграции** — соответствует решению по дизайну.
