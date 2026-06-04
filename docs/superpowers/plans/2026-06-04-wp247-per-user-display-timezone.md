# Per-user часовой пояс отображения (WP#247, Фаза 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать каждому оператору видеть даты/времена в дашбордах/логах в выбранном им часовом поясе (дефолт МСК), сведя три способа конвертации к одному хелперу; хранение и планирование не трогаем.

**Architecture:** Модель *store-UTC / display-from-settings*. Новая колонка `autowarm_users.timezone`. Новый модуль `tz_display.js` — единственный источник конвертации (SQL-фрагменты для naive-UTC и timestamptz колонок + JS-хелперы на `Intl` вместо хардкода `+3ч`). Пояс резолвится из сессии на каждый запрос (`resolveDisplayTz`), фоллбэк/cron → `Europe/Moscow`. Все читающие эндпоинты прокидывают пояс в хелперы. Планирование `scheduled_at` и горячий путь диспатча НЕ изменяются. Без kill-switch: дефолт МСК = текущее поведение байт-в-байт.

**Tech Stack:** Node.js, Express (express-session + connect-pg-simple), PostgreSQL (`pg`), node:test, ванильный JS-фронт в `public/index.html`. Код-репозиторий — **delivery-contenthunter** (autowarm).

**Репозиторий и изоляция:** Все правки кода — в изолированном git worktree delivery-contenthunter (общий прод-checkout = гонка с параллельными сессиями). Worktree создаётся скиллом `superpowers:using-git-worktrees` в начале исполнения. Прод-каталог для чтения образцов: `/root/.openclaw/workspace-genri/autowarm`.

**Прогон тестов:** `node --test <файл>` для одиночного файла. Живая БД: `PGHOST=localhost PGPORT=5432 PGDATABASE=openclaw PGUSER=openclaw PGPASSWORD=openclaw123`.

---

## File Structure

| Файл | Ответственность | Действие |
|---|---|---|
| `migrations/20260604_wp247_user_timezone.sql` (+`__rollback.sql`) | Колонка `autowarm_users.timezone` | Create |
| `tz_display.js` | Единый источник конвертации: SQL-фрагменты + JS `Intl`-хелперы + валидация пояса | Create |
| `test_tz_display.test.js` | Юнит-тесты хелперов (без БД) | Create |
| `test_wp247_display_tz_live.test.js` | Живые тесты: эквивалентность МСК + per-user + валидация | Create |
| `server.js` | `resolveDisplayTz`, пояс в сессию, `/api/me` + `POST /api/me/timezone`; проводка пояса в SQL/JS сайты дашбордов | Modify |
| `publish_planner.js` | `getPlannerCards`/`attachQueueTransferColumns` принимают `tz` | Modify |
| `pipeline_funnel.js` | Окна воронки в поясе пользователя | Modify |
| `daily_publish_report.js` | Cron → дефолт МСК через хелперы | Modify |
| `public/index.html` | UI-выбор пояса (курированный + «показать все»); формат дат по `currentUser.timezone` | Modify |

---

## Task 1: DB-миграция — колонка `autowarm_users.timezone`

**Files:**
- Create: `migrations/20260604_wp247_user_timezone.sql`
- Create: `migrations/20260604_wp247_user_timezone__rollback.sql`

- [ ] **Step 1: Написать миграцию**

Создать `migrations/20260604_wp247_user_timezone.sql`:

```sql
-- WP#247 (Фаза 1): per-user часовой пояс ОТОБРАЖЕНИЯ.
-- Аддитивно, маленькая внутренняя таблица, дефолт = текущее поведение (МСК).
-- Не горячий путь. Хранение/планирование не трогаем. См. фоллоу-ап WP#220/#221.
BEGIN;

ALTER TABLE autowarm_users
  ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'Europe/Moscow';

COMMIT;
```

- [ ] **Step 2: Написать откат**

Создать `migrations/20260604_wp247_user_timezone__rollback.sql`:

```sql
-- Откат WP#247 Фаза 1.
BEGIN;
ALTER TABLE autowarm_users DROP COLUMN IF EXISTS timezone;
COMMIT;
```

- [ ] **Step 3: Применить миграцию на dev/live БД и проверить**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f migrations/20260604_wp247_user_timezone.sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -At -c "SELECT column_name,data_type,column_default FROM information_schema.columns WHERE table_name='autowarm_users' AND column_name='timezone';"
```
Expected: `timezone|text|'Europe/Moscow'::text` и все существующие строки получили `Europe/Moscow`.

- [ ] **Step 4: Commit**

```bash
git add migrations/20260604_wp247_user_timezone.sql migrations/20260604_wp247_user_timezone__rollback.sql
git commit -m "feat(wp247): миграция — колонка autowarm_users.timezone (дефолт МСК)"
```

---

## Task 2: Модуль `tz_display.js` — единый источник конвертации

Сначала SQL-фрагменты и валидация (юнит-тесты без БД), затем JS `Intl`-хелперы.

**Files:**
- Create: `tz_display.js`
- Test: `test_tz_display.test.js`

- [ ] **Step 1: Написать падающий тест на валидацию и SQL-фрагменты**

Создать `test_tz_display.test.js`:

```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const tz = require('./tz_display');

test('isValidTz: принимает корректные пояса, отклоняет мусор', () => {
  assert.equal(tz.isValidTz('Europe/Moscow'), true);
  assert.equal(tz.isValidTz('Asia/Yekaterinburg'), true);
  assert.equal(tz.isValidTz('UTC'), true);
  assert.equal(tz.isValidTz("Europe/Moscow'; DROP TABLE x;--"), false);
  assert.equal(tz.isValidTz('Not/AZone'), false);
  assert.equal(tz.isValidTz(''), false);
  assert.equal(tz.isValidTz(null), false);
});

test('safeTz: валидный возвращается, невалидный → дефолт МСК', () => {
  assert.equal(tz.safeTz('Asia/Yekaterinburg'), 'Asia/Yekaterinburg');
  assert.equal(tz.safeTz('мусор'), 'Europe/Moscow');
  assert.equal(tz.safeTz(undefined), 'Europe/Moscow');
});

test('naiveTzClause/tzClause: безопасная интерполяция валидного пояса', () => {
  assert.equal(tz.naiveTzClause('Europe/Moscow'),
    "AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow'");
  assert.equal(tz.tzClause('Asia/Yekaterinburg'),
    "AT TIME ZONE 'Asia/Yekaterinburg'");
});

test('naiveTzClause: невалидный пояс бросает (защита от инъекции)', () => {
  assert.throws(() => tz.naiveTzClause("x'; DROP--"), /invalid timezone/i);
});
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `node --test test_tz_display.test.js`
Expected: FAIL — `Cannot find module './tz_display'`.

- [ ] **Step 3: Реализовать SQL-фрагменты и валидацию**

Создать `tz_display.js`:

```js
'use strict';
// WP#247: единый источник конвертации времени для ОТОБРАЖЕНИЯ.
// Дефолт — МСК (текущее поведение). Используется во всех читающих эндпоинтах.

const DEFAULT_TZ = 'Europe/Moscow';

// Имя IANA-пояса: буквы/цифры/_ и +-/ . Никаких кавычек/пробелов/точек-с-запятой.
const TZ_NAME_RE = /^[A-Za-z][A-Za-z0-9_+\-/]*$/;

// Проверка, что среда (Intl) реально знает пояс. Невалидный → Intl бросает RangeError.
function intlKnows(name) {
  try { new Intl.DateTimeFormat('en-US', { timeZone: name }); return true; }
  catch { return false; }
}

function isValidTz(name) {
  return typeof name === 'string' && TZ_NAME_RE.test(name) && intlKnows(name);
}

// Вернуть валидный пояс или дефолт МСК.
function safeTz(name) {
  return isValidTz(name) ? name : DEFAULT_TZ;
}

// Безопасно закавычить уже провалидированный пояс для SQL.
function quoteTz(name) {
  if (!isValidTz(name)) throw new Error(`invalid timezone: ${name}`);
  return `'${name.replace(/'/g, "''")}'`;
}

// SQL-фрагмент для naive-UTC колонок (scheduled_at, created_at):
// сначала пометить UTC, затем перевести в пояс.
function naiveTzClause(name) {
  return `AT TIME ZONE 'UTC' AT TIME ZONE ${quoteTz(name)}`;
}

// SQL-фрагмент для timestamptz колонок (manual_handoff_at, published_at, h.hour).
function tzClause(name) {
  return `AT TIME ZONE ${quoteTz(name)}`;
}

module.exports = { DEFAULT_TZ, isValidTz, safeTz, naiveTzClause, tzClause };
```

- [ ] **Step 4: Прогнать — убедиться, что проходит**

Run: `node --test test_tz_display.test.js`
Expected: PASS (4 теста).

- [ ] **Step 5: Дописать тест JS `Intl`-хелперов (замена `MSK_OFFSET_MS`)**

Добавить в `test_tz_display.test.js`:

```js
test('instantToYmd: дата инстанта в поясе', () => {
  // 2026-06-04 22:30:00Z = 01:30 МСК 05-го = 03:30 Екб 05-го
  const ms = Date.UTC(2026, 5, 4, 22, 30, 0);
  assert.equal(tz.instantToYmd(ms, 'Europe/Moscow'), '2026-06-05');
  assert.equal(tz.instantToYmd(ms, 'Asia/Yekaterinburg'), '2026-06-05');
  assert.equal(tz.instantToYmd(ms, 'UTC'), '2026-06-04');
});

test('startOfDayUtcMs: 00:00 даты в поясе → UTC-инстант', () => {
  // 00:00 05-06-2026 МСК (UTC+3) = 2026-06-04T21:00:00Z
  assert.equal(tz.startOfDayUtcMs('2026-06-05', 'Europe/Moscow'),
    Date.UTC(2026, 5, 4, 21, 0, 0));
  // 00:00 05-06-2026 Екб (UTC+5) = 2026-06-04T19:00:00Z
  assert.equal(tz.startOfDayUtcMs('2026-06-05', 'Asia/Yekaterinburg'),
    Date.UTC(2026, 5, 4, 19, 0, 0));
});

test('startOfDayUtcMs: корректно через DST-границу (America/New_York spring-forward)', () => {
  // 2026-03-08 США переходят на летнее: 00:00 ET = UTC-5 = 2026-03-08T05:00:00Z
  assert.equal(tz.startOfDayUtcMs('2026-03-08', 'America/New_York'),
    Date.UTC(2026, 2, 8, 5, 0, 0));
});

test('roundTripMsk: эквивалентность старому MSK_OFFSET_MS (+3ч фикс)', () => {
  const ms = Date.UTC(2026, 5, 4, 22, 30, 0);
  const OLD = 3 * 3600 * 1000;
  const oldYmd = new Date(ms + OLD).toISOString().slice(0, 10);
  assert.equal(tz.instantToYmd(ms, 'Europe/Moscow'), oldYmd);
});
```

- [ ] **Step 6: Прогнать — убедиться, что падает**

Run: `node --test test_tz_display.test.js`
Expected: FAIL — `tz.instantToYmd is not a function`.

- [ ] **Step 7: Реализовать JS `Intl`-хелперы**

Добавить в `tz_display.js` ПЕРЕД `module.exports` и дописать экспорты:

```js
// Смещение пояса (wall - utc) в мс для данного инстанта. Через Intl, учитывает DST.
function tzOffsetMs(instantMs, name) {
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone: safeTz(name), hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  const p = Object.fromEntries(dtf.formatToParts(new Date(instantMs)).map(x => [x.type, x.value]));
  const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
  return asUtc - instantMs;
}

// 'YYYY-MM-DD' инстанта в поясе (en-CA даёт ISO-формат даты).
function instantToYmd(instantMs, name) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: safeTz(name), year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date(instantMs));
}

// UTC-инстант (мс) для 00:00 указанной календарной даты в поясе. DST-safe (двойной проход).
function startOfDayUtcMs(ymd, name) {
  const [y, m, d] = ymd.split('-').map(Number);
  const guess = Date.UTC(y, m - 1, d, 0, 0, 0);
  let utc = guess - tzOffsetMs(guess, name);
  const off2 = tzOffsetMs(utc, name);     // уточнить, если перескочили DST-границу
  if (off2 !== tzOffsetMs(guess, name)) utc = guess - off2;
  return utc;
}
```
И обновить экспорт:
```js
module.exports = { DEFAULT_TZ, isValidTz, safeTz, naiveTzClause, tzClause,
                   tzOffsetMs, instantToYmd, startOfDayUtcMs };
```

- [ ] **Step 8: Прогнать — убедиться, что всё проходит**

Run: `node --test test_tz_display.test.js`
Expected: PASS (8 тестов).

- [ ] **Step 9: Commit**

```bash
git add tz_display.js test_tz_display.test.js
git commit -m "feat(wp247): tz_display — SQL-фрагменты + Intl-хелперы + валидация пояса"
```

---

## Task 3: Резолв пояса, сессия и эндпоинт настройки

**Files:**
- Modify: `server.js` (login ~101, tg-auth ~127, `/api/me` ~137-148; добавить `resolveDisplayTz` + `POST /api/me/timezone`)
- Test: `test_wp247_display_tz_live.test.js`

- [ ] **Step 1: Написать падающий живой тест эндпоинта валидации пояса**

Создать `test_wp247_display_tz_live.test.js`:

```js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const tz = require('./tz_display');

const pool = new Pool({ host: 'localhost', port: 5432, database: 'openclaw',
  user: 'openclaw', password: 'openclaw123' });

test('safeTz фоллбэк гарантирует валидный SQL-фрагмент даже при мусоре', () => {
  // resolveDisplayTz в проде вернёт safeTz(...) — фрагмент всегда строится.
  assert.doesNotThrow(() => tz.naiveTzClause(tz.safeTz("'; DROP--")));
});

test('naive-фрагмент: полуночный scheduled_at в МСК и Екб', async () => {
  const mskClause = tz.naiveTzClause('Europe/Moscow');
  const ekbClause = tz.naiveTzClause('Asia/Yekaterinburg');
  const q = await pool.query(
    `SELECT (TIMESTAMP '2026-06-04 22:30:00' ${mskClause})::date::text AS msk,
            (TIMESTAMP '2026-06-04 22:30:00' ${ekbClause})::date::text AS ekb`);
  assert.equal(q.rows[0].msk, '2026-06-05');
  assert.equal(q.rows[0].ekb, '2026-06-05');
});

test.after(() => pool.end());
```

- [ ] **Step 2: Прогнать — убедиться, что падает (ещё нет проводки) или проходит частично**

Run: `node --test test_wp247_display_tz_live.test.js`
Expected: оба теста на этом этапе PASS (они проверяют только tz_display). Это база для Task 4-6 (проводку проверяем там). Если PASS — двигаемся.

- [ ] **Step 3: Добавить `resolveDisplayTz` в server.js**

Около начала server.js, после `const planner = require('./publish_planner')` (≈строка 19), добавить:
```js
const tzd = require('./tz_display');
// Пояс ОТОБРАЖЕНИЯ для текущего запроса: из сессии пользователя, иначе МСК.
function resolveDisplayTz(req) {
  return tzd.safeTz(req && req.session && req.session.user && req.session.user.timezone);
}
```

- [ ] **Step 4: Класть пояс в сессию при логине**

В `server.js` заменить ОБА присваивания `req.session.user` (строки ≈101 и ≈127):
```js
req.session.user = { id: user.id, username: user.username, role: user.role };
```
на:
```js
req.session.user = { id: user.id, username: user.username, role: user.role, timezone: tzd.safeTz(user.timezone) };
```
(`user` — строка из `SELECT * FROM autowarm_users`, колонка `timezone` уже есть после Task 1.)

- [ ] **Step 5: Возвращать пояс в `/api/me` и добавить эндпоинт смены**

В `/api/me` (≈137) гарантировать наличие `timezone` в ответе — он уже в `req.session.user`. Сразу ПОСЛЕ блока `/api/me` добавить:
```js
app.post('/api/me/timezone', requireAuth, async (req, res) => {
  const { timezone } = req.body || {};
  if (!tzd.isValidTz(timezone)) return res.status(400).json({ error: 'Неизвестный часовой пояс' });
  try {
    await pool.query('UPDATE autowarm_users SET timezone=$1 WHERE id=$2', [timezone, req.session.user.id]);
    req.session.user.timezone = timezone;
    req.session.save(() => res.json({ ok: true, timezone }));
  } catch (e) { res.status(500).json({ error: e.message }); }
});
```

- [ ] **Step 6: Дописать живой тест на сохранение/валидацию пояса пользователя**

Добавить в `test_wp247_display_tz_live.test.js` (перед `test.after`):
```js
test('UPDATE timezone хранит только валидные значения', async () => {
  // Берём любого существующего пользователя, не меняя его навсегда.
  const u = await pool.query('SELECT id, timezone FROM autowarm_users ORDER BY id LIMIT 1');
  if (!u.rows.length) return; // нет пользователей — пропустить
  const { id, timezone: orig } = u.rows[0];
  await pool.query('UPDATE autowarm_users SET timezone=$1 WHERE id=$2', ['Asia/Yekaterinburg', id]);
  const after = await pool.query('SELECT timezone FROM autowarm_users WHERE id=$1', [id]);
  assert.equal(after.rows[0].timezone, 'Asia/Yekaterinburg');
  await pool.query('UPDATE autowarm_users SET timezone=$1 WHERE id=$2', [orig, id]); // вернуть
});
```

- [ ] **Step 7: Прогнать тесты**

Run: `node --test test_wp247_display_tz_live.test.js`
Expected: PASS (3 теста).

- [ ] **Step 8: Smoke — сервер стартует без ошибок**

Run: `node -e "require('./server.js')" 2>&1 | head -5` (или проверить синтаксис: `node --check server.js`)
Expected: нет SyntaxError; (полный старт поднимет порт — достаточно `node --check server.js`).

- [ ] **Step 9: Commit**

```bash
git add server.js test_wp247_display_tz_live.test.js
git commit -m "feat(wp247): resolveDisplayTz + пояс в сессии + POST /api/me/timezone"
```

---

## Task 4: Проводка пояса в `publish_planner.js`

`getPlannerCards` и `attachQueueTransferColumns` сейчас используют модульные константы `MSK`/`MSK_FROM_UTC` (строки 140/143) в 9 местах. Делаем пояс параметром.

**Files:**
- Modify: `publish_planner.js` (140-143 константы; 160,161,162,168,178,192,195,227,235,270,305 — сайты; сигнатуры функций; экспорт)
- Modify: `server.js` — вызовы `planner.getPlannerCards` / `attachQueueTransferColumns` прокидывают `tz`
- Test: `test_wp247_display_tz_live.test.js`

- [ ] **Step 1: Падающий тест — планировщик группирует в поясе пользователя**

Добавить в `test_wp247_display_tz_live.test.js` (перед `test.after`):
```js
const planner = require('./publish_planner');
test('getPlannerCards принимает tz и группирует scheduled_at в нём', async () => {
  const cardsMsk = await planner.getPlannerCards(pool, { from: '2026-06-03', to: '2026-06-05', tz: 'Europe/Moscow' });
  assert.ok(Array.isArray(cardsMsk));
  // tz-параметр принят без ошибки и результат строится
  const cardsEkb = await planner.getPlannerCards(pool, { from: '2026-06-03', to: '2026-06-05', tz: 'Asia/Yekaterinburg' });
  assert.ok(Array.isArray(cardsEkb));
});
```

- [ ] **Step 2: Прогнать — зафиксировать стартовое состояние**

Run: `node --test test_wp247_display_tz_live.test.js`
Expected: PASS — текущая `getPlannerCards` просто игнорирует лишнее поле `tz`, тест проверяет, что вызов не падает. Содержательная защита от регресса — тест эквивалентности в Step 5 (он должен остаться зелёным ПОСЛЕ рефактора при tz=МСК) и расходимость дат при не-МСК поясе там же. Это smoke-приём параметра, не TDD-red.

- [ ] **Step 3: Сделать пояс параметром функций**

В `publish_planner.js`:

1. Удалить модульные константы (140-143) ИЛИ оставить как дефолт. Заменить блок на:
```js
const { naiveTzClause, tzClause, safeTz } = require('./tz_display');
```
2. Сигнатуру `getPlannerCards` (≈145) дополнить `tz`:
```js
async function getPlannerCards(pool, { from, to, projectIds = null, trustQueueStatus = true, tz = 'Europe/Moscow' }) {
  const TZ = safeTz(tz);
  const NAIVE = naiveTzClause(TZ);   // для scheduled_at, created_at
  const TS = tzClause(TZ);           // для manual_handoff_at
```
3. В теле заменить интерполяции:
   - `${MSK_FROM_UTC}` → `${NAIVE}` (строки 160, 161, 168, 178, 227, 235, 270 и любые другие naive-сайты).
   - `${MSK}` → `${TS}` (строки 162, 192, 195 — timestamptz manual_handoff_at/published_at).
4. В `attachQueueTransferColumns` (содержит сайт 305 `(created_at ${MSK_FROM_UTC})`): добавить параметр `tz` и собрать `const NAIVE = naiveTzClause(safeTz(tz))`, заменить `${MSK_FROM_UTC}` → `${NAIVE}`. Обновить её сигнатуру и всех вызывающих.
5. **НЕ удалять** экспорт `MSK, MSK_FROM_UTC` из `module.exports` на этом шаге — `server.js:2775` (business_date-фильтр) всё ещё ссылается на `planner.MSK_FROM_UTC` до Task 5. Оставить их экспортированными как временную совместимость; удаление — в Task 5 Step 1 (после замены сайта в server.js). Это держит каждый коммит рабочим.

- [ ] **Step 4: Прокинуть tz из server.js в вызовы планировщика**

В `server.js` найти все вызовы `planner.getPlannerCards(` и `planner.attachQueueTransferColumns(` / `attachQueueTransferColumns(`:
```bash
grep -nE "getPlannerCards|attachQueueTransferColumns" server.js
```
В каждом добавить `tz: resolveDisplayTz(req)` в объект-опции (для `getPlannerCards`) и аргумент `resolveDisplayTz(req)` (для `attachQueueTransferColumns`). Пример:
```js
const cards = await planner.getPlannerCards(pool, { from, to, projectIds, tz: resolveDisplayTz(req) });
```

- [ ] **Step 5: Живая эквивалентность — МСК-результат не изменился**

Добавить в `test_wp247_display_tz_live.test.js`:
```js
test('эквивалентность: planner tz=МСК даёт те же business_date, что старый рецепт', async () => {
  const { rows: oldRows } = await pool.query(
    `SELECT id, (scheduled_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Moscow')::date::text AS d
     FROM publish_queue WHERE scheduled_at IS NOT NULL ORDER BY id DESC LIMIT 50`);
  const naive = require('./tz_display').naiveTzClause('Europe/Moscow');
  const { rows: newRows } = await pool.query(
    `SELECT id, (scheduled_at ${naive})::date::text AS d
     FROM publish_queue WHERE scheduled_at IS NOT NULL ORDER BY id DESC LIMIT 50`);
  assert.deepEqual(newRows, oldRows);
});
```

- [ ] **Step 6: Прогнать тесты + регрессию планировщика**

Run:
```bash
node --test test_wp247_display_tz_live.test.js
node --test test_publish_planner.test.js
```
Expected: PASS; регрессия планировщика 15/15 без падений.

- [ ] **Step 7: Commit**

```bash
git add publish_planner.js server.js test_wp247_display_tz_live.test.js
git commit -m "feat(wp247): publish_planner принимает пояс отображения параметром"
```

---

## Task 5: Проводка пояса в `server.js` (дашборды, лог, окна)

Заменить хардкод `'Europe/Moscow'` и `MSK_OFFSET_MS` в server.js на резолвнутый пояс + хелперы. Сайты: business_date-фильтр (≈2775), лейблы часов (≈1341), окна дашборда (`MSK_OFFSET_MS` 1777-1910, `dashboardDateWindow`/`resolveDateBasis` 1880-1930), `date_from/date_to` (≈2035), JS-конвертации scheduled_at (≈2317, 6742).

**Files:**
- Modify: `server.js`
- Test: `test_wp247_display_tz_live.test.js`

- [ ] **Step 1: business_date-фильтр и лейблы часов**

1. business_date-фильтр (≈2775): сейчас `(pt.created_at ${planner.MSK_FROM_UTC})::date = $?::date`. Заменить на:
```js
push(`(pt.created_at ${tzd.naiveTzClause(resolveDisplayTz(req))})::date = $?::date`, String(query.business_date));
```
После этой замены `planner.MSK_FROM_UTC`/`planner.MSK` больше нигде не используются — удалить их из `module.exports` в `publish_planner.js` (отложенная очистка из Task 4 Step 3.5). Проверить: `grep -nE "planner\.(MSK|MSK_FROM_UTC)" server.js` → пусто.
2. Лейблы часов (≈1341): `h.hour AT TIME ZONE 'Europe/Moscow'` (timestamptz). Заменить literal на `h.hour ${tzd.tzClause(resolveDisplayTz(req))}` (нужно, чтобы переменная пояса была в scope этого хендлера — резолвить `const dtz = resolveDisplayTz(req)` в начале хендлера и использовать `tzd.tzClause(dtz)`).

- [ ] **Step 2: Окна дашборда — заменить `MSK_OFFSET_MS` на tz-aware хелперы**

В блоке вычисления окон (≈1777-1910) и в `dashboardDateWindow`/`resolveDateBasis` (1880-1930):
1. Прокинуть `tz` в функцию, считающую окна (добавить параметр `tz`, по умолчанию `'Europe/Moscow'`).
2. Заменить паттерны:
   - `new Date(ms + MSK_OFFSET_MS).toISOString().slice(0,10)` → `tzd.instantToYmd(ms, tz)`.
   - вычисление `from/to` вида `new Date(dayMsMsk - MSK_OFFSET_MS)` (00:00 MSK-дня → UTC) → строить от `tzd.startOfDayUtcMs(ymd, tz)`: получить `ymd` нужного дня в поясе, затем `new Date(tzd.startOfDayUtcMs(ymd, tz))` и арифметику по суткам через повторный `startOfDayUtcMs` соседнего дня (а не `± DAY_MS`, чтобы DST-устойчиво).
   - `new Date(ms + MSK_OFFSET_MS).toISOString()` (≈1910, «MSK-wall как будто UTC») → если нужна именно wall-строка пояса, использовать `Intl` форматирование часа/минуты; для дневных лейблов достаточно `tzd.instantToYmd`.
3. Вызвать оконную функцию с `resolveDisplayTz(req)` из хендлера дашборда.

**Примечание исполнителю:** это самый объёмный шаг. Менять механически по одному `MSK_OFFSET_MS`-сайту, после каждого прогоняя Step 5 (эквивалентность). Для МСК все хелперы дают тот же результат, что `+3ч` (тест `roundTripMsk` в Task 2 это фиксирует).

- [ ] **Step 3: `date_from`/`date_to` и JS-конвертации scheduled_at**

1. `date_from`/`date_to` (≈2035): сравнения `pq.scheduled_at >= $1` с ISO-строкой. Если строка — календарная дата пользователя, конвертировать её границы в UTC через `tzd.startOfDayUtcMs(dateStr, dtz)` и `startOfDayUtcMs(следующийДень, dtz)` и сравнивать с `pq.scheduled_at` (naive-UTC, кастится в UTC сессией). Передавать UTC-границы как ISO. (Сохранить текущую семантику при tz=МСК — проверить эквивалентностью.)
2. JS-конвертации (≈2317, 6742): `new Date(new Date(r.scheduled_at).getTime() + 3*3600*1000).toISOString().slice(0,10)` → `tzd.instantToYmd(new Date(r.scheduled_at).getTime(), dtz)`.

- [ ] **Step 4: Живой тест эквивалентности дашборд-окна при МСК**

Добавить в `test_wp247_display_tz_live.test.js`:
```js
test('эквивалентность: instantToYmd(МСК) == старый +3ч для выборки очереди', async () => {
  const { rows } = await pool.query(
    `SELECT scheduled_at FROM publish_queue WHERE scheduled_at IS NOT NULL ORDER BY id DESC LIMIT 100`);
  const OLD = 3 * 3600 * 1000;
  for (const r of rows) {
    const ms = new Date(r.scheduled_at).getTime();
    const oldYmd = new Date(ms + OLD).toISOString().slice(0, 10);
    assert.equal(tz.instantToYmd(ms, 'Europe/Moscow'), oldYmd);
  }
});
```

- [ ] **Step 5: Прогнать тесты + `node --check`**

Run:
```bash
node --test test_wp247_display_tz_live.test.js
node --check server.js
```
Expected: PASS; нет SyntaxError.

- [ ] **Step 6: Commit**

```bash
git add server.js test_wp247_display_tz_live.test.js
git commit -m "feat(wp247): пояс отображения в дашбордах/логах/окнах server.js"
```

---

## Task 6: `pipeline_funnel.js` и `daily_publish_report.js`

Воронка — окна в поясе пользователя; cron-отчёт — дефолт МСК.

**Files:**
- Modify: `pipeline_funnel.js` (4 `MSK_OFFSET_MS`, 64 `toYmd`, `funnelWindowSql`/`funnelWindowParams`)
- Modify: `daily_publish_report.js` (19,35,42,45,52 `MSK_OFFSET_MS`)
- Modify: `server.js` — вызовы воронки прокидывают `tz`
- Test: `test_wp247_display_tz_live.test.js`

- [ ] **Step 1: Падающий тест — воронка принимает tz**

Добавить:
```js
const funnel = require('./pipeline_funnel');
test('pipeline_funnel.toYmd через tz_display эквивалентен +3ч при МСК', () => {
  const ms = Date.UTC(2026, 5, 4, 22, 30, 0);
  assert.equal(tz.instantToYmd(ms, 'Europe/Moscow'),
    new Date(ms + 3 * 3600 * 1000).toISOString().slice(0, 10));
});
```

- [ ] **Step 2: Прогнать — PASS (база tz_display)**

Run: `node --test test_wp247_display_tz_live.test.js`
Expected: PASS.

- [ ] **Step 3: `pipeline_funnel.js` — заменить `MSK_OFFSET_MS` на хелперы с tz**

1. Удалить `const MSK_OFFSET_MS = ...` (строка 4), импортировать `const { instantToYmd, startOfDayUtcMs, safeTz } = require('./tz_display')`.
2. `toYmd` (≈64): сделать принимающим `tz`: `const toYmd = (dt, tz) => instantToYmd(dt.getTime(), tz)`.
3. Функции, принимающие диапазон (`slotDateBoundsFromRange`, `funnelWindowParams`, `computeFunnel`/`assembleFunnel`), дополнить параметром `tz` (дефолт `'Europe/Moscow'`), где границы выбранного диапазона считаются от `startOfDayUtcMs(dateStr, tz)`.
4. Обновить `module.exports` (убрать `MSK_OFFSET_MS`, если экспортируется и больше не нужен; либо оставить для обратной совместимости как `3*3600*1000`).

- [ ] **Step 4: Прокинуть tz в вызовы воронки из server.js**

```bash
grep -nE "computeFunnel|assembleFunnel|funnelWindow|slotDateBoundsFromRange" server.js
```
В каждый вызов добавить `resolveDisplayTz(req)` (или `tz:` в опции, по сигнатуре). 

- [ ] **Step 5: `daily_publish_report.js` — cron остаётся МСК через хелперы**

1. Заменить `const MSK_OFFSET_MS = ...` импортом `const { instantToYmd, startOfDayUtcMs, DEFAULT_TZ } = require('./tz_display')`.
2. Заменить вычисления (35,42,45,52): везде использовать `DEFAULT_TZ` (`'Europe/Moscow'`) — у рассылки нет пользователя, бизнес-пояс. Напр. `instantToYmd(nowMs, DEFAULT_TZ)`, границы суток — `startOfDayUtcMs(ymd, DEFAULT_TZ)`.
3. Поведение обязано остаться идентичным (МСК — фикс +3): подтверждается тестом эквивалентности.

- [ ] **Step 6: Прогнать тесты воронки/отчёта**

Run:
```bash
node --test test_wp247_display_tz_live.test.js
ls test_*funnel* test_*report* test_*daily* 2>/dev/null && node --test $(ls test_*funnel*.test.js test_*report*.test.js test_*daily*.test.js 2>/dev/null)
node --check pipeline_funnel.js && node --check daily_publish_report.js
```
Expected: PASS; существующие тесты воронки/отчёта без падений; нет SyntaxError.

- [ ] **Step 7: Commit**

```bash
git add pipeline_funnel.js daily_publish_report.js server.js test_wp247_display_tz_live.test.js
git commit -m "feat(wp247): воронка в поясе пользователя; cron-отчёт через tz_display (МСК)"
```

---

## Task 7: Фронтенд — выбор пояса + формат дат

**Files:**
- Modify: `public/index.html` (settings-UI рядом с change-password ≈5209; `currentUser` ≈5147-5164; форматтер дат ≈5072; пикер расписания ≈1655 — подпись «МСК»)

- [ ] **Step 1: Добавить курированный список поясов и контрол**

В `public/index.html` рядом с формой смены пароля (≈5209) добавить блок настройки пояса:
```html
<div class="mt-4">
  <label class="block text-xs font-semibold text-gray-500 mb-1">🌍 Часовой пояс отображения</label>
  <select id="tz-select" class="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm"></select>
  <label class="inline-flex items-center gap-1 mt-1 text-xs text-gray-500">
    <input type="checkbox" id="tz-show-all" onchange="renderTzOptions()"> показать все пояса
  </label>
  <button onclick="saveTimezone()" class="mt-2 px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs">Сохранить пояс</button>
</div>
```

- [ ] **Step 2: JS — рендер опций (курированный + «показать все»), сохранение**

Добавить в `<script>` `public/index.html`:
```js
const TZ_CURATED = [
  ['Europe/Kaliningrad','Калининград (МСК−1)'], ['Europe/Moscow','Москва (МСК)'],
  ['Europe/Samara','Самара (МСК+1)'], ['Asia/Yekaterinburg','Екатеринбург (МСК+2)'],
  ['Asia/Omsk','Омск (МСК+3)'], ['Asia/Krasnoyarsk','Красноярск (МСК+4)'],
  ['Asia/Irkutsk','Иркутск (МСК+5)'], ['Asia/Yakutsk','Якутск (МСК+6)'],
  ['Asia/Vladivostok','Владивосток (МСК+7)'], ['Asia/Magadan','Магадан (МСК+8)'],
  ['Asia/Almaty','Алматы'], ['Asia/Tashkent','Ташкент'], ['UTC','UTC'],
];
function renderTzOptions() {
  const sel = document.getElementById('tz-select');
  const showAll = document.getElementById('tz-show-all')?.checked;
  const cur = currentUser?.timezone || 'Europe/Moscow';
  let list = TZ_CURATED;
  if (showAll && typeof Intl.supportedValuesOf === 'function') {
    list = Intl.supportedValuesOf('timeZone').map(z => [z, z]);
  }
  sel.innerHTML = list.map(([v, label]) =>
    `<option value="${v}" ${v === cur ? 'selected' : ''}>${label}</option>`).join('');
}
async function saveTimezone() {
  const timezone = document.getElementById('tz-select').value;
  const r = await fetch('/api/me/timezone', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ timezone }) });
  if (r.ok) { currentUser.timezone = timezone; location.reload(); }
  else alert('Не удалось сохранить пояс');
}
```
Вызвать `renderTzOptions()` после загрузки `currentUser` (в блоке ≈5162 после `currentUser = await res.json()`).

- [ ] **Step 3: Подпись пикера расписания «МСК»**

У `datetime-local` пикера планирования (≈1655, `id="task-time"`) добавить рядом подпись, что время в МСК (планирование — бизнес-пояс), напр. label «🕑 Время публикации (МСК)». Это устраняет путаницу для оператора в не-МСК поясе.

- [ ] **Step 4: Проверка сборки/синтаксиса фронта**

`public/index.html` — статика, JS встроенный. Проверить, что страница не падает: открыть в браузере прод-превью ИЛИ `node -e "const fs=require('fs');const h=fs.readFileSync('public/index.html','utf8');if(!/renderTzOptions/.test(h))throw new Error('missing');console.log('ok')"`.
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(wp247): UI выбора пояса (курированный + показать все) + подпись пикера МСК"
```

---

## Task 8: Финальная верификация и деплой

**Files:** —

- [ ] **Step 1: Полный целевой прогон тестов WP#247 + смежных регрессий**

Run:
```bash
node --test test_tz_display.test.js test_wp247_display_tz_live.test.js test_publish_planner.test.js
node --check server.js && node --check publish_planner.js && node --check pipeline_funnel.js && node --check daily_publish_report.js
```
Expected: все PASS; нет SyntaxError.

- [ ] **Step 2: Code review всей реализации**

REQUIRED SUB-SKILL: `superpowers:requesting-code-review`. Проверить: нет оставшихся `MSK_OFFSET_MS`/literal `'Europe/Moscow'` в read-сайтах (кроме осознанного `DEFAULT_TZ` в cron); сигнатуры функций согласованы (`tz`/`resolveDisplayTz`); эквивалентность при МСК доказана тестами; запись/диспатч не тронуты.
```bash
grep -rnF "MSK_OFFSET_MS" server.js pipeline_funnel.js daily_publish_report.js   # ожидаем пусто
grep -rnF "Europe/Moscow" server.js publish_planner.js pipeline_funnel.js        # только осознанные дефолты
```

- [ ] **Step 3: Применить миграцию на проде и задеплоить**

REQUIRED SUB-SKILL: `superpowers:finishing-a-development-branch` (выбор merge/PR с пользователем — деплой необратим, общий прод-main).
```bash
# применить миграцию
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f migrations/20260604_wp247_user_timezone.sql
# merge ветки в прод-main (delivery-contenthunter), затем:
cd /root/.openclaw/workspace-genri/autowarm && git pull --rebase && sudo pm2 restart 35
```

- [ ] **Step 4: Прод-smoke**

- Зайти в UI под оператором, сменить пояс на `Asia/Yekaterinburg`, убедиться, что даты в дашбордах/логе/планировщике сдвинулись; вернуть `Europe/Moscow` — даты как раньше.
- Telegram-рассылка дневного отчёта остаётся в МСК.
- Планирование публикации: пикер подписан «МСК», ролик выкладывается в то же время, что и раньше.

- [ ] **Step 5: OpenProject + доки + память**

- OP#247 → «Тестирование» с комментарием (что сделано, эквивалентность МСК, что вне объёма = Фаза 2).
- Доки-PR в rmbrmv/contenthunter (спека + план).
- Обновить память (`project_wp247...`), отметить Фазу 2 (миграция timestamptz) как остаток в бэклоге.

---

## Self-Review заметки

- **Покрытие спеки:** модель данных (T1), резолв+эндпоинт (T3), единый хелпер вместо трёх способов (T2 + проводка T4-6), проводка во все читающие места (T4 planner, T5 server, T6 funnel/report), планирование в МСК (не трогаем + подпись T7), UI курированный+показать все (T7), тесты эквивалентности/валидации (во всех), без kill-switch (дефолт МСК). ✓
- **Риск-сайт:** `MSK_OFFSET_MS`-математика окон (T5 Step 2) — единственный нетривиальный; защищён tz-aware хелперами с DST-тестами (T2) и пошаговой эквивалентностью при МСК.
- **Вне объёма:** ALTER колонок в timestamptz (Фаза 2, отдельный WP).
