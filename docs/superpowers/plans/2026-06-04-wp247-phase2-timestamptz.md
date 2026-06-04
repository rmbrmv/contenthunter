# WP#247 Фаза 2 — миграция naive-UTC → timestamptz: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести 7 наивных `timestamp`-колонок таблиц `publish_queue` и `publish_tasks` в `timestamptz` (instant-preserving), убрав скрытую зависимость корректности времени от пояса сессии БД/процесса, и переключить 4 SQL-читателя с `naiveTzClause` на `tzClause`.

**Architecture:** Среда вся в `Etc/UTC` → `ALTER … TYPE timestamptz USING col AT TIME ZONE 'UTC'` сохраняет тот же момент времени. Меняется только внутренняя репрезентация; наблюдаемое поведение (диспатч, отображение) не меняется. После ALTER 4 читателя, использовавшие `AT TIME ZONE 'UTC' AT TIME ZONE '<пояс>'`, переключаются на `AT TIME ZONE '<пояс>'`, иначе будет двойная конвертация. Откат — обратной миграцией + revert коммита читателей. Рантайм-флага нет (тип колонки нельзя переключить флагом).

**Tech Stack:** PostgreSQL (host `localhost:5432`, db `openclaw`, user `openclaw`), Node.js + `pg`, `node:test`. Прод-чекаут autowarm: `/root/.openclaw/workspace-genri/autowarm`, server.js под pm2 id 35.

**Спека:** `docs/superpowers/specs/2026-06-04-wp247-phase2-timestamptz-design.md`

**⚠️ Репозиторий кода:** `delivery-contenthunter` (НЕ docs-репо `contenthunter`, где лежит этот план). Все code/test/migration пути ниже — относительно корня autowarm-чекаута.

**⚠️ Известное pre-existing:** `test_wp221_dashboard_tz.test.js` уже падает на текущей схеме — импортирует удалённые в WP#247 Фазе 1 экспорты `MSK/MSK_FROM_UTC` из `publish_planner`. Чиним в Task 5 (заодно превращаем в регрессию timestamptz).

---

## Колонки в скоупе (7)

- `publish_queue`: `scheduled_at`, `created_at`, `updated_at`
- `publish_tasks`: `created_at`, `started_at`, `updated_at`, `url_capture_last_attempt_at`

## 4 SQL-читателя для флипа `naiveTzClause → tzClause`

- `publish_planner.js:144` (`const NAIVE = naiveTzClause(TZ)` → используется для `pq.scheduled_at`/`pq.created_at`)
- `publish_planner.js:296` (`const NAIVE = naiveTzClause(TZ)` → используется для `publish_tasks.created_at`)
- `server.js:2122` (`date_trunc('${unit}', pq.scheduled_at ${tzd.naiveTzClause(dtz)})`)
- `server.js:2766` (`(pt.created_at ${tzd.naiveTzClause(TZ)})::date = $?::date`)

---

## Task 0: Изолированный worktree кода

**⚠️ Общий прод-чекаут autowarm = гонка с параллельными сессиями (IG/YT/TT). Работаем в отдельном worktree.**

**Files:** нет правок — только подготовка окружения.

- [ ] **Step 1: Создать worktree off main**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git worktree add /home/claude-user/work-trees/wp247-phase2-autowarm -b wp247-phase2-timestamptz origin/main
cd /home/claude-user/work-trees/wp247-phase2-autowarm
git branch --show-current   # ожидаем: wp247-phase2-timestamptz
```

- [ ] **Step 2: Проверить зависимости (pg установлен)**

Run: `cd /home/claude-user/work-trees/wp247-phase2-autowarm && node -e "require('pg'); console.log('pg ok')"`
Expected: `pg ok`

---

## Task 1: Миграция БД (forward + rollback) + temp-table тест

**Files:**
- Create: `migrations/20260604_wp247_phase2_timestamptz.sql`
- Create: `migrations/20260604_wp247_phase2_timestamptz__rollback.sql`
- Test: `test_wp247_phase2_migration.test.js`

- [ ] **Step 1: Написать падающий тест (USING-трансформ сохраняет момент и даёт timestamptz)**

`test_wp247_phase2_migration.test.js`:

```javascript
// Run: node --test --test-force-exit test_wp247_phase2_migration.test.js
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const pool = new Pool({ host:'localhost', port:5432, database:'openclaw', user:'openclaw', password:'openclaw123' });
after(async () => { await pool.end(); });

// Доказываем безопасность ALTER … USING col AT TIME ZONE 'UTC' на TEMP-таблице (прод не трогаем).
// Среда в UTC → момент сохраняется: 10:00 наивно-UTC == 10:00 UTC как timestamptz.
test('ALTER USING AT TIME ZONE UTC: тип становится timestamptz, момент сохранён', async () => {
  const c = await pool.connect();
  try {
    await c.query('BEGIN');
    await c.query(`CREATE TEMP TABLE _wp247_t (ts timestamp without time zone) ON COMMIT DROP`);
    await c.query(`INSERT INTO _wp247_t (ts) VALUES (TIMESTAMP '2026-05-13 10:00:00')`);
    await c.query(`ALTER TABLE _wp247_t ALTER COLUMN ts TYPE timestamptz USING ts AT TIME ZONE 'UTC'`);
    const { rows } = await c.query(
      `SELECT pg_typeof(ts)::text AS t, (ts AT TIME ZONE 'UTC')::text AS naive_utc FROM _wp247_t`);
    assert.equal(rows[0].t, 'timestamp with time zone');
    assert.equal(rows[0].naive_utc, '2026-05-13 10:00:00'); // момент = 10:00 UTC, не сдвинут
    await c.query('ROLLBACK');
  } finally { c.release(); }
});
```

- [ ] **Step 2: Прогнать — тест должен пройти сразу (это проверка свойства SQL, не нашего кода)**

Run: `node --test --test-force-exit test_wp247_phase2_migration.test.js`
Expected: PASS (1 pass). Тест фиксирует корректность USING-формулы, которую используют файлы миграции.

- [ ] **Step 3: Написать forward-миграцию**

`migrations/20260604_wp247_phase2_timestamptz.sql`:

```sql
-- WP#247 (Фаза 2): naive-UTC timestamp → timestamptz для publish_queue/publish_tasks.
-- Среда (БД-сессия/Node/ОС) в Etc/UTC → USING col AT TIME ZONE 'UTC' сохраняет момент.
-- Instant-preserving: наблюдаемое поведение не меняется, убираем зависимость от пояса сессии.
-- Парный файл отката: 20260604_wp247_phase2_timestamptz__rollback.sql.
BEGIN;

ALTER TABLE publish_queue
  ALTER COLUMN scheduled_at TYPE timestamptz USING scheduled_at AT TIME ZONE 'UTC',
  ALTER COLUMN created_at   TYPE timestamptz USING created_at   AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at   TYPE timestamptz USING updated_at   AT TIME ZONE 'UTC';

ALTER TABLE publish_tasks
  ALTER COLUMN created_at                TYPE timestamptz USING created_at                AT TIME ZONE 'UTC',
  ALTER COLUMN started_at                TYPE timestamptz USING started_at                AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at                TYPE timestamptz USING updated_at                AT TIME ZONE 'UTC',
  ALTER COLUMN url_capture_last_attempt_at TYPE timestamptz USING url_capture_last_attempt_at AT TIME ZONE 'UTC';

COMMIT;
```

- [ ] **Step 4: Написать rollback-миграцию**

`migrations/20260604_wp247_phase2_timestamptz__rollback.sql`:

```sql
-- Откат WP#247 Фаза 2: timestamptz → naive UTC (instant-preserving назад).
-- col AT TIME ZONE 'UTC' от timestamptz даёт наивное UTC-стенное время = исходное хранение.
BEGIN;

ALTER TABLE publish_queue
  ALTER COLUMN scheduled_at TYPE timestamp without time zone USING scheduled_at AT TIME ZONE 'UTC',
  ALTER COLUMN created_at   TYPE timestamp without time zone USING created_at   AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at   TYPE timestamp without time zone USING updated_at   AT TIME ZONE 'UTC';

ALTER TABLE publish_tasks
  ALTER COLUMN created_at                TYPE timestamp without time zone USING created_at                AT TIME ZONE 'UTC',
  ALTER COLUMN started_at                TYPE timestamp without time zone USING started_at                AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at                TYPE timestamp without time zone USING updated_at                AT TIME ZONE 'UTC',
  ALTER COLUMN url_capture_last_attempt_at TYPE timestamp without time zone USING url_capture_last_attempt_at AT TIME ZONE 'UTC';

COMMIT;
```

- [ ] **Step 5: Round-trip тест миграции на TEMP-таблице (forward→rollback момент сохраняется)**

Добавить в `test_wp247_phase2_migration.test.js`:

```javascript
test('round-trip naive→tstz→naive сохраняет исходное наивное значение', async () => {
  const c = await pool.connect();
  try {
    await c.query('BEGIN');
    await c.query(`CREATE TEMP TABLE _wp247_rt (ts timestamp without time zone) ON COMMIT DROP`);
    await c.query(`INSERT INTO _wp247_rt (ts) VALUES (TIMESTAMP '2026-05-13 10:00:00')`);
    await c.query(`ALTER TABLE _wp247_rt ALTER COLUMN ts TYPE timestamptz USING ts AT TIME ZONE 'UTC'`);
    await c.query(`ALTER TABLE _wp247_rt ALTER COLUMN ts TYPE timestamp without time zone USING ts AT TIME ZONE 'UTC'`);
    const { rows } = await c.query(`SELECT pg_typeof(ts)::text AS t, ts::text AS v FROM _wp247_rt`);
    assert.equal(rows[0].t, 'timestamp without time zone');
    assert.equal(rows[0].v, '2026-05-13 10:00:00');
    await c.query('ROLLBACK');
  } finally { c.release(); }
});
```

- [ ] **Step 6: Прогнать оба теста**

Run: `node --test --test-force-exit test_wp247_phase2_migration.test.js`
Expected: PASS (2 pass).

- [ ] **Step 7: Commit**

```bash
git add migrations/20260604_wp247_phase2_timestamptz.sql migrations/20260604_wp247_phase2_timestamptz__rollback.sql test_wp247_phase2_migration.test.js
git commit -m "feat(wp247): миграция Фаза 2 naive→timestamptz + temp-table round-trip тесты"
```

---

## Task 2: Red-тест принципа (на timestamptz tzClause верен, naiveTzClause — двойная конвертация)

**Files:**
- Test: `test_wp247_phase2_clause.test.js`

- [ ] **Step 1: Написать тест-доказательство флипа**

`test_wp247_phase2_clause.test.js`:

```javascript
// Run: node --test --test-force-exit test_wp247_phase2_clause.test.js
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { tzClause, naiveTzClause } = require('./tz_display');
const pool = new Pool({ host:'localhost', port:5432, database:'openclaw', user:'openclaw', password:'openclaw123' });
after(async () => { await pool.end(); });

// 22:30 UTC = 01:30 МСК следующего дня → бизнес-день 05-е.
// На timestamptz: tzClause (одинарный AT TIME ZONE) — верно; naiveTzClause (двойной) — нет.
test('timestamptz: tzClause даёт верную МСК-дату', async () => {
  const { rows } = await pool.query(
    `SELECT (TIMESTAMPTZ '2026-06-04 22:30:00+00' ${tzClause('Europe/Moscow')})::date::text AS d`);
  assert.equal(rows[0].d, '2026-06-05');
});

test('timestamptz: naiveTzClause двойная конвертация уводит дату (обоснование флипа)', async () => {
  const { rows } = await pool.query(
    `SELECT (TIMESTAMPTZ '2026-06-04 22:30:00+00' ${naiveTzClause('Europe/Moscow')})::date::text AS d`);
  assert.notEqual(rows[0].d, '2026-06-05'); // подтверждаем: на timestamptz naiveTzClause НЕЛЬЗЯ
});
```

- [ ] **Step 2: Прогнать**

Run: `node --test --test-force-exit test_wp247_phase2_clause.test.js`
Expected: PASS (2 pass).

- [ ] **Step 3: Commit**

```bash
git add test_wp247_phase2_clause.test.js
git commit -m "test(wp247): доказательство флипа naiveTzClause→tzClause на timestamptz"
```

---

## Task 3: Флип 4 читателей `naiveTzClause → tzClause`

**Files:**
- Modify: `publish_planner.js:144`, `publish_planner.js:296`
- Modify: `server.js:2118-2122`, `server.js:2766`

- [ ] **Step 1: publish_planner.js:144 — заменить**

Было:
```javascript
  const NAIVE = naiveTzClause(TZ);   // для scheduled_at, created_at (naive-UTC)
```
Стало:
```javascript
  const NAIVE = tzClause(TZ);        // WP#247 Фаза 2: scheduled_at/created_at теперь timestamptz
```

- [ ] **Step 2: publish_planner.js:296 — заменить**

Было:
```javascript
  const NAIVE = naiveTzClause(TZ);
```
Стало:
```javascript
  const NAIVE = tzClause(TZ);        // WP#247 Фаза 2: publish_tasks.created_at теперь timestamptz
```

- [ ] **Step 3: server.js:2118-2122 — заменить clause и комментарий**

Было:
```javascript
      // WP#247 — task-ветка: конвертируем scheduled_at (naive-UTC) в пояс пользователя через naiveTzClause.
      // При dtz=МСК naiveTzClause даёт `AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow'` = +3ч эквивалент.
      const bktExpr = dateBasis === 'planned'
        ? 'COALESCE(s.slot_date, ut.slot_date)::timestamp'
        : `date_trunc('${unit}', pq.scheduled_at ${tzd.naiveTzClause(dtz)})`;
```
Стало:
```javascript
      // WP#247 Фаза 2 — task-ветка: scheduled_at теперь timestamptz, конвертация в пояс через tzClause.
      // При dtz=МСК tzClause даёт `AT TIME ZONE 'Europe/Moscow'` (одинарный, без UTC-префикса).
      const bktExpr = dateBasis === 'planned'
        ? 'COALESCE(s.slot_date, ut.slot_date)::timestamp'
        : `date_trunc('${unit}', pq.scheduled_at ${tzd.tzClause(dtz)})`;
```

- [ ] **Step 4: server.js:2766 — заменить**

Было:
```javascript
    push(`(pt.created_at ${tzd.naiveTzClause(TZ)})::date = $?::date`, String(query.business_date));
```
Стало:
```javascript
    push(`(pt.created_at ${tzd.tzClause(TZ)})::date = $?::date`, String(query.business_date));
```

- [ ] **Step 5: Проверить, что не осталось скоупных naiveTzClause**

Run: `grep -n "naiveTzClause" publish_planner.js server.js`
Expected: пусто (все 4 скоупных места переключены; хелпер остаётся в `tz_display.js` как шим).

- [ ] **Step 6: Синтаксическая проверка (модули грузятся)**

Run: `node -e "require('./publish_planner'); require('./tz_display'); console.log('require ok')"`
Expected: `require ok` (server.js целиком не грузим — он стартует слушатель; достаточно `node --check`).
Run: `node --check server.js && echo "server.js syntax ok"`
Expected: `server.js syntax ok`

- [ ] **Step 7: Commit**

```bash
git add publish_planner.js server.js
git commit -m "feat(wp247): флип 4 читателей naiveTzClause→tzClause (scheduled_at/created_at теперь timestamptz)"
```

---

## Task 4: Аудит писателей scheduled_at/created_at (red-flag из спеки)

Цель — подтвердить, что **ни один писатель не кладёт наивно-локальную (не-UTC wall-clock) строку**; иначе после ALTER интерпретация значения изменится.

**Files:** только инспекция; правки — лишь если найдём наивно-локальный писатель.

- [ ] **Step 1: Перечислить всех писателей**

Run:
```bash
grep -nE "scheduled_at\s*=|INSERT INTO publish_queue|INSERT INTO publish_tasks|created_at\s*=" publish_planner.js server.js watchdog_breaker.js scheduler.js | grep -viE "test|AT TIME ZONE|::date|>= |<= |< \\$|>= \\$"
```
Зафиксировать список: `server.js:2605/6535/6594/6808` (INSERT), `server.js:2654` (UPDATE scheduled_at=$1), `server.js:7123/7134/7239`, `watchdog_breaker.js:33`.

- [ ] **Step 2: Для каждого писателя со значением-параметром ($N) определить источник JS-значения**

Для `server.js:2605/6535/6594/6808/2654` найти, какой JS-объект биндится в позицию `scheduled_at`/`created_at`. Подтвердить, что это:
- `NOW()` / `NOW() + INTERVAL` (корректно для timestamptz), **или**
- `Date`-объект / UTC-ISO строка (`…Z` или `+00`), либо результат `new Date(startOfDayUtcMs(...)).toISOString()` (как в `server.js:2022`).

Run (пример для одного INSERT):
```bash
sed -n '2600,2640p' server.js
```
Ожидаем: значение — `Date`/UTC-ISO/`NOW()`, НЕ строка вида `'YYYY-MM-DD HH:MM'` собранная в МСК.

- [ ] **Step 3: Зафиксировать вывод аудита**

Если все писатели UTC-корректны (ожидаемый исход) — добавить пометку в шапку лога задачи: «Аудит писателей: наивно-локальных не найдено, миграция instant-preserving подтверждена». Правок кода нет → коммита нет.

Если найден наивно-локальный писатель — **остановиться и сообщить**: он требует отдельного фикса (привести значение к UTC-ISO/Date) ПЕРЕД миграцией; это меняет план.

---

## Task 5: Оживить test_wp221_dashboard_tz как timestamptz-регрессию

`test_wp221_dashboard_tz.test.js` сейчас падает (импортит удалённые `MSK/MSK_FROM_UTC`). Переводим его на `tzd`-клозы и на timestamptz-семантику — он становится живой регрессией миграции на реальной `publish_queue`.

**⚠️ Зависит от применённой миграции:** SMOKE-часть вставляет `scheduled_at` и читает через `getPlannerCards`, которому нужна timestamptz-колонка. Этот тест запускаем **после деплоя миграции** (Task 7), либо адаптируем вставку под timestamptz-литерал. Здесь правим импорты/литералы; зелёным станет после Task 7.

**Files:**
- Modify: `test_wp221_dashboard_tz.test.js:5` (импорт) и тела двух снэпшот-тестов; SMOKE INSERT-литерал.

- [ ] **Step 1: Заменить импорт удалённых констант на tzd-клозы**

Было (строка 5):
```javascript
const { MSK, MSK_FROM_UTC } = require('./publish_planner');
```
Стало:
```javascript
const { tzClause } = require('./tz_display');
const MSK = tzClause('Europe/Moscow');           // timestamptz → МСК
```

- [ ] **Step 2: Снэпшот «naive-UTC у полуночи» переписать под timestamptz**

Заменить тело первого снэпшот-теста (бывш. `MSK_FROM_UTC: naive-UTC …`) на timestamptz-литерал (момент тот же, что хранит мигрированная колонка):
```javascript
test('timestamptz у полуночи даёт следующий МСК-день', async () => {
  const { rows } = await pool.query(
    `SELECT (TIMESTAMPTZ '2026-06-04 22:30:00+00' ${MSK})::date::text AS d`);
  assert.equal(rows[0].d, '2026-06-05');
});
```
Удалить дублирующий второй снэпшот, если он повторяет тот же кейс.

- [ ] **Step 3: SMOKE — INSERT scheduled_at сделать timestamptz-литералом**

Было (в INSERT publish_queue):
```javascript
TIMESTAMP '2026-06-04 22:30:00'
```
Стало:
```javascript
TIMESTAMPTZ '2026-06-04 22:30:00+00'
```

- [ ] **Step 4: Синтаксис-проверка (не запускать против БД до миграции)**

Run: `node --check test_wp221_dashboard_tz.test.js && echo "syntax ok"`
Expected: `syntax ok`. (Полный прогон — в Task 7 после применения миграции.)

- [ ] **Step 5: Commit**

```bash
git add test_wp221_dashboard_tz.test.js
git commit -m "test(wp247): оживить test_wp221 на timestamptz-семантике (убрать удалённые MSK/MSK_FROM_UTC)"
```

---

## Task 6: Регрессия безопасных (не зависящих от схемы) наборов

**Files:** только запуск.

- [ ] **Step 1: Прогнать tz_display + clause + migration тесты**

Run:
```bash
node --test --test-force-exit test_tz_display.test.js test_wp247_phase2_clause.test.js test_wp247_phase2_migration.test.js
```
Expected: все PASS (эти не зависят от типа скоупных колонок — temp-таблицы и SQL-литералы).

- [ ] **Step 2: Зафиксировать, какие наборы откладываются на post-deploy**

`test_wp221_dashboard_tz.test.js` и любые planner/funnel/report live-тесты, читающие `publish_queue.scheduled_at`/`publish_tasks.created_at`, гоняются **после** применения миграции (Task 7), т.к. до неё колонка ещё наивная и флипнутый `tzClause` дал бы расхождение.

---

## Task 7: Деплой + live-верификация (координировано, окно низкого трафика)

**⚠️ Это прод. Делать с согласия Данила, в окно низкого трафика. ALTER + рестарт — секунды; окно скоса = только отображение, диспатч не страдает.**

**Files:** прод-чекаут `/root/.openclaw/workspace-genri/autowarm`.

- [ ] **Step 1: Снять instant-снэпшот ДО миграции**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -p 5432 -U openclaw -d openclaw -tAc \
"SELECT id, scheduled_at, created_at FROM publish_queue ORDER BY id DESC LIMIT 5;
 SELECT id, created_at, started_at FROM publish_tasks ORDER BY id DESC LIMIT 5;" > /tmp/wp247_before.txt
cat /tmp/wp247_before.txt
```

- [ ] **Step 2: Смержить ветку кода в main и подготовить прод-чекаут**

```bash
cd /home/claude-user/work-trees/wp247-phase2-autowarm
git push origin wp247-phase2-timestamptz
# Мерж в main (PR или --no-ff локально по принятому в команде процессу), затем на проде:
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin && git status   # убедиться, что working tree чистый (checkout=main)
```

- [ ] **Step 3: Применить forward-миграцию**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -p 5432 -U openclaw -d openclaw \
  -f /home/claude-user/work-trees/wp247-phase2-autowarm/migrations/20260604_wp247_phase2_timestamptz.sql
```
Expected: `BEGIN`/`ALTER TABLE`×2/`COMMIT`, без ошибок.

- [ ] **Step 4: Сразу подтянуть код и перезапустить server.js**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git pull --ff-only origin main
sudo pm2 restart 35   # server.js = дашборд + крон-диспатч (long-running, нужен рестарт)
```

- [ ] **Step 5: Проверить типы колонок**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -p 5432 -U openclaw -d openclaw -tAc \
"SELECT table_name||'.'||column_name||' = '||data_type FROM information_schema.columns
 WHERE (table_name='publish_queue' AND column_name IN ('scheduled_at','created_at','updated_at'))
    OR (table_name='publish_tasks' AND column_name IN ('created_at','started_at','updated_at','url_capture_last_attempt_at'))
 ORDER BY 1;"
```
Expected: все 7 = `timestamp with time zone`.

- [ ] **Step 6: Instant-equality ПОСЛЕ миграции**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -p 5432 -U openclaw -d openclaw -tAc \
"SELECT id, (scheduled_at AT TIME ZONE 'UTC') AS sched_utc, (created_at AT TIME ZONE 'UTC') AS cr_utc
 FROM publish_queue ORDER BY id DESC LIMIT 5;"
```
Сравнить `sched_utc`/`cr_utc` со значениями из `/tmp/wp247_before.txt` — должны совпадать (момент сохранён).

- [ ] **Step 7: Прогнать отложенные live-тесты на мигрированной схеме**

Run:
```bash
cd /home/claude-user/work-trees/wp247-phase2-autowarm
node --test --test-force-exit test_wp221_dashboard_tz.test.js
```
Expected: PASS — планировщик группирует полуночный `scheduled_at` (22:30 UTC) под `2026-06-05`, фантома `2026-06-04` нет.

- [ ] **Step 8: Live-проверка диспатча и дашбордов**

- Диспатч-тик (server.js, каждые 5 мин) берёт задачи в то же время, что и до: проверить лог крона / отсутствие всплеска `scheduled_at <= NOW()`-выборки.
- Дашборд / Лог событий / планировщик показывают те же даты при дефолтном поясе (МСК) и пользовательском (Asia/Yekaterinburg).

- [ ] **Step 9: Перевести OP#247 в «Тестирование» и обновить память**

После зелёной верификации — OP#247 → «Тестирование»; обновить файл памяти `project_wp247_per_user_display_timezone.md` (Фаза 2 SHIPPED+DEPLOYED).

**Откат (если что-то разъехалось):** применить `…__rollback.sql` + `git revert` коммита Task 3 + `sudo pm2 restart 35`.

---

## Self-Review (выполнено при написании)

- **Покрытие спеки:** миграция (Task 1), флип читателей (Task 3), шим naiveTzClause сохранён (Task 3 step 5), без рантайм-флага (Task 7 — деплой+rollback), аудит писателей (Task 4), instant-preserving проверки (Task 1/7), тестирование TDD (Task 1/2/5/6), верификация (Task 7). Все разделы спеки покрыты.
- **Заглушки:** нет — весь SQL/JS приведён целиком.
- **Согласованность типов:** `tzClause`/`naiveTzClause` из `tz_display`; переменная `NAIVE` сохраняет имя, меняет значение на `tzClause`; пути и номера строк — из реального кода (publish_planner.js:144/296, server.js:2122/2766).
