# WP#161 iter2 — доработка TG-уведомлений: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Починить ложные срабатывания блока «нет контента», отфильтровать устаревшие ролики в блоке «на одобрении», разделить дни на отдельные абзацы и сменить каденцию на 1 раз в 09:00 МСК.

**Architecture:** Точечная правка живого модуля `approval_notify.js` (autowarm). Меняются два SQL в `buildApprovalSummary`, структура её возврата, `formatMessage`, и механизм расписания (почасовое окно → однократная отправка по образцу `daily_publish_report.js`). Чистые функции (`formatMessage`, `isReportDue`, `mskSendDate`) покрываются юнит-тестами; SQL-семантика — смоком на живой БД `openclaw`.

**Tech Stack:** Node.js, `node:test`, `pg`, PostgreSQL (БД `openclaw`), Telegram Bot API.

**Спека:** `docs/superpowers/specs/2026-05-29-wp161-iter2-approval-notify-refine-design.md`

**Репозиторий кода:** autowarm (GenGo2/delivery-contenthunter). Перед реализацией создать worktree в чекауте autowarm (`/home/claude-user/autowarm-testbench`) — НЕ редактировать shared checkout напрямую. Файлы ниже даны относительно корня autowarm.

---

## Файловая структура

| Файл | Ответственность | Изменение |
|---|---|---|
| `approval_notify.js` | сбор сводки, форматирование, расписание, claim | модифицируется |
| `tests/test_approval_notify.test.js` | юнит-тесты модуля | модифицируется |
| `telegram_send.js` | отправка в TG | без изменений |
| `migrations/20260527_approval_notify_runs.sql` | таблица claim | без изменений (переиспользуется) |

Текущая сигнатура `buildApprovalSummary` возвращает `{ pendingApproval, emptySlots }`. После задач 1–2 будет возвращать:

```js
{
  pendingApproval: [{ client, contentId, dates: ['YYYY-MM-DD'...] }],  // dates уже >= today
  emptyTomorrow:  ['Клиент'...],   // клиенты с полностью пустым «завтра»
  emptyDayAfter:  ['Клиент'...],   // клиенты с полностью пустым «послезавтра»
  labels: { tomorrow: 'DD.MM', dayAfter: 'DD.MM' },
}
```

---

## Task 1: Блок «нет контента» — правило «весь день пуст» + разбивка по дням

**Files:**
- Modify: `approval_notify.js` (`buildApprovalSummary`, SQL #2 + сборка возврата)
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Обновить тест `buildApprovalSummary` под новую структуру**

Заменить существующий блок `describe('approval_notify.buildApprovalSummary', ...)` (строки ~132-153) целиком на:

```js
describe('approval_notify.buildApprovalSummary', () => {
  test('блок «нет контента»: SQL #2 даёт (client, day) → раскладка по завтра/послезавтра', async () => {
    const pool = fakePool([
      { match: "vc.status = 'needs_review'", rows: [
        { client: 'Клиент A', content_id: 1, slot_dates: ['2026-05-28'] },
      ]},
      { match: 'FROM validator_schedule_slots s', rows: [
        { client: 'AXILOR Private', day: '2026-05-29' }, // послезавтра
        { client: 'Бета', day: '2026-05-28' },           // завтра
      ]},
    ]);
    const now = Date.UTC(2026, 4, 27, 9, 0); // 12:00 МСК 27.05 → завтра 28.05, послезавтра 29.05
    const s = await an.buildApprovalSummary(pool, { nowMs: now });

    assert.deepEqual(s.emptyTomorrow, ['Бета']);
    assert.deepEqual(s.emptyDayAfter, ['AXILOR Private']);
    assert.deepEqual(s.labels, { tomorrow: '28.05', dayAfter: '29.05' });

    // SQL #2 получил завтра+послезавтра и фильтрует по «весь день пуст»
    const emptyCall = pool.calls.find(c => c.sql.includes('FROM validator_schedule_slots s'));
    assert.deepEqual(emptyCall.params, ['2026-05-28', '2026-05-29']);
    assert.match(emptyCall.sql, /content_id IS NOT NULL\) = 0/);
  });
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | grep -A3 "нет контента"`
Expected: FAIL (текущий код возвращает `emptySlots`, а не `emptyTomorrow`/`emptyDayAfter`; SQL не содержит `content_id IS NOT NULL) = 0`).

- [ ] **Step 3: Переписать SQL #2 и сборку возврата в `buildApprovalSummary`**

Заменить блок «Блок 2» (строки ~121-135) на:

```js
  // Блок 2: активные клиенты, у которых ДЕНЬ полностью пуст (0 заполненных слотов)
  // на завтра/послезавтра. content_id IS NOT NULL = слот заполнен. HAVING отсекает дни,
  // где есть хоть один заполненный слот (фикс ложных срабатываний при 1 пустом из 2).
  const { rows: emptyRows } = await pool.query(`
    SELECT vp.project AS client,
           to_char(s.slot_date, 'YYYY-MM-DD') AS day
    FROM validator_schedule_slots s
    JOIN validator_projects vp ON vp.id = s.project_id
    WHERE s.slot_date IN ($1::date, $2::date)
      AND vp.active = true
    GROUP BY vp.project, s.slot_date
    HAVING count(*) FILTER (WHERE s.content_id IS NOT NULL) = 0
    ORDER BY s.slot_date, vp.project
  `, [tomorrow, dayAfter]);

  return {
    pendingApproval: pendingRows.map(r => ({ client: r.client, contentId: r.content_id, dates: r.slot_dates || [] })),
    emptyTomorrow: emptyRows.filter(r => r.day === tomorrow).map(r => r.client),
    emptyDayAfter: emptyRows.filter(r => r.day === dayAfter).map(r => r.client),
    labels: { tomorrow: _isoToDDMM(tomorrow), dayAfter: _isoToDDMM(dayAfter) },
  };
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | grep -A3 "нет контента"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "fix(wp161): блок «нет контента» — правило «весь день пуст» + разбивка завтра/послезавтра"
```

---

## Task 2: Блок «на одобрении» — фильтр плановой даты ≥ сегодня

**Files:**
- Modify: `approval_notify.js` (`buildApprovalSummary`, SQL #1)
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Добавить тест на фильтр дат в SQL #1**

В `describe('approval_notify.buildApprovalSummary', ...)` добавить тест:

```js
  test('блок «на одобрении»: SQL #1 фильтрует по дате >= сегодня (МСК), бездатные скрыты', async () => {
    const pool = fakePool([
      { match: "vc.status = 'needs_review'", rows: [
        { client: 'Клиент A', content_id: 1, slot_dates: ['2026-05-28'] },
      ]},
      { match: 'FROM validator_schedule_slots s', rows: [] },
    ]);
    const now = Date.UTC(2026, 4, 27, 9, 0); // сегодня (МСК) = 27.05
    await an.buildApprovalSummary(pool, { nowMs: now });

    const pendCall = pool.calls.find(c => c.sql.includes("vc.status = 'needs_review'"));
    assert.deepEqual(pendCall.params, ['2026-05-27']);             // today МСК
    assert.match(pendCall.sql, /slot_date >= \$1::date/);          // фильтр дат в array_agg
    assert.match(pendCall.sql, /HAVING count\(\*\) FILTER/);       // отсечение «только прошлые/без даты»
    assert.match(pendCall.sql, /JOIN validator_schedule_slots/);   // INNER JOIN (бездатные выпадают)
  });
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | grep -A3 "на одобрении"`
Expected: FAIL (текущий SQL #1 — `LEFT JOIN`, без `$1::date` и без `HAVING`; и `buildApprovalSummary` не передаёт `today` параметром).

- [ ] **Step 3: Переписать SQL #1 + добавить `today` в `buildApprovalSummary`**

В начале `buildApprovalSummary` (после вычисления `tomorrow`/`dayAfter`) добавить:

```js
  const today = mskDateOffset(nowMs, 0);
```

Заменить блок «Блок 1» (строки ~105-119) на:

```js
  // Блок 1: ролики needs_review с плановой датой >= сегодня. INNER JOIN отсекает
  // ролики без слотов (бездатные скрываем); HAVING отсекает ролики, у которых все
  // слоты в прошлом. В вывод идут только будущие даты (FILTER в array_agg).
  const { rows: pendingRows } = await pool.query(`
    SELECT vp.project AS client,
           vc.id AS content_id,
           array_agg(to_char(vss.slot_date, 'YYYY-MM-DD') ORDER BY vss.slot_date)
             FILTER (WHERE vss.slot_date >= $1::date) AS slot_dates
    FROM validator_content vc
    JOIN validator_projects vp ON vp.id = vc.project_id
    JOIN validator_schedule_slots vss ON vss.content_id = vc.id
    WHERE vc.status = 'needs_review'
    GROUP BY vp.project, vc.id
    HAVING count(*) FILTER (WHERE vss.slot_date >= $1::date) > 0
    ORDER BY vp.project, vc.id
  `, [today]);
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | grep -A3 "на одобрении"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "fix(wp161): блок «на одобрении» — фильтр плановой даты >= сегодня, бездатные скрыты"
```

---

## Task 3: `formatMessage` — раздельные абзацы «завтра» / «послезавтра»

**Files:**
- Modify: `approval_notify.js` (`formatMessage`)
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Заменить тесты `formatMessage` под новую структуру**

В `describe('approval_notify.formatMessage', ...)` заменить тесты, которые ссылаются на `emptySlots` и `Контент не загружен на завтра/послезавтра`, на следующие (остальные тесты блока «на одобрении» оставить):

```js
  test('блок «нет контента»: раздельные абзацы завтра/послезавтра', () => {
    const txt = an.formatMessage({
      pendingApproval: [],
      emptyTomorrow: ['Бета'],
      emptyDayAfter: ['AXILOR Private'],
      labels: { tomorrow: '30.05', dayAfter: '31.05' },
    });
    assert.match(txt, /Нет контента на завтра \(30\.05\):/);
    assert.match(txt, /Бета/);
    assert.match(txt, /Нет контента на послезавтра \(31\.05\):/);
    assert.match(txt, /AXILOR Private/);
  });
  test('абзац дня скрыт, если в нём нет клиентов', () => {
    const txt = an.formatMessage({
      pendingApproval: [],
      emptyTomorrow: [],
      emptyDayAfter: ['AXILOR Private'],
      labels: { tomorrow: '30.05', dayAfter: '31.05' },
    });
    assert.doesNotMatch(txt, /на завтра/);
    assert.match(txt, /на послезавтра \(31\.05\)/);
  });
  test('оба дня и одобрение пусты → «всё чисто»', () => {
    const txt = an.formatMessage({ pendingApproval: [], emptyTomorrow: [], emptyDayAfter: [], labels: { tomorrow: '30.05', dayAfter: '31.05' } });
    assert.match(txt, /Всё одобрено/);
  });
  test('escape опасных символов в имени клиента (нет контента)', () => {
    const txt = an.formatMessage({ pendingApproval: [], emptyTomorrow: ['A & <b>'], emptyDayAfter: [], labels: { tomorrow: '30.05', dayAfter: '31.05' } });
    assert.match(txt, /A &amp; &lt;b&gt;/);
  });
  test('mentions добавляются в конец', () => {
    const txt = an.formatMessage({ pendingApproval: [], emptyTomorrow: ['Y'], emptyDayAfter: [], labels: { tomorrow: '30.05', dayAfter: '31.05' } }, { mentions: '@gengo_care' });
    assert.match(txt, /@gengo_care$/);
  });
```

Также в тестах блока «на одобрении» (которые остаются — `оба блока`, `склонение`, `дедуп`) добавить в объект `emptyTomorrow: [], emptyDayAfter: [], labels: { tomorrow: '30.05', dayAfter: '31.05' }` вместо `emptySlots`. Тест `только блок «нет контента»` заменён тестами выше — удалить его старую версию.

- [ ] **Step 2: Запустить тесты `formatMessage` — убедиться, что падают**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | grep -A3 "formatMessage\|нет контента\|послезавтра"`
Expected: FAIL (текущий `formatMessage` читает `summary.emptySlots`).

- [ ] **Step 3: Переписать блок «нет контента» в `formatMessage`**

Заменить блок `if (empty.length) { ... }` (строки ~88-93) на:

```js
  const emptyTomorrow = summary.emptyTomorrow || [];
  const emptyDayAfter = summary.emptyDayAfter || [];
  const labels = summary.labels || {};
  if (emptyTomorrow.length) {
    if (lines.length) lines.push('');
    lines.push(`📭 <b>Нет контента на завтра (${labels.tomorrow}):</b>`);
    lines.push(emptyTomorrow.map(escapeHtml).join(', '));
  }
  if (emptyDayAfter.length) {
    if (lines.length) lines.push('');
    lines.push(`📭 <b>Нет контента на послезавтра (${labels.dayAfter}):</b>`);
    lines.push(emptyDayAfter.map(escapeHtml).join(', '));
  }
```

Удалить строку `const empty = summary.emptySlots || [];` в начале `formatMessage`.

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | grep -A3 "formatMessage\|послезавтра"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "feat(wp161): formatMessage — раздельные абзацы «нет контента» завтра/послезавтра"
```

---

## Task 4: Каденция — почасовое окно → 1 раз в 09:00 МСК

**Files:**
- Modify: `approval_notify.js` (`mskSendDate`, `isReportDue`, `runApprovalNotify` claim-ключ + isEmpty, `_tickOnce`, `startApprovalNotifyCron`, экспорты; удалить `parseWindow`/`isInWindow`/`hourBucket`/`mskHour`)
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Заменить тесты расписания (`hourBucket`/`mskHour`/`parseWindow`/`isInWindow`/`_tickOnce`)**

Удалить блоки `describe` для `hourBucket`, `mskHour`, `parseWindow`, `isInWindow` (строки ~20-43) и заменить блок `_tickOnce` (строки ~202-219). Добавить:

```js
describe('approval_notify.mskSendDate', () => {
  test('UTC-момент → дата в МСК (YYYY-MM-DD)', () => {
    assert.equal(an.mskSendDate(Date.UTC(2026, 4, 27, 9, 0)), '2026-05-27');  // 12:00 МСК
    assert.equal(an.mskSendDate(Date.UTC(2026, 4, 27, 21, 30)), '2026-05-28'); // 00:30 МСК след. сутки
  });
});

describe('approval_notify.isReportDue', () => {
  test('до целевого времени → null', () => {
    assert.equal(an.isReportDue(Date.UTC(2026, 4, 27, 5, 59), '09:00'), null); // 08:59 МСК
  });
  test('ровно в целевое время → дата отправки', () => {
    assert.equal(an.isReportDue(Date.UTC(2026, 4, 27, 6, 0), '09:00'), '2026-05-27'); // 09:00 МСК
  });
  test('позже целевого времени (catch-up) → дата отправки', () => {
    assert.equal(an.isReportDue(Date.UTC(2026, 4, 27, 12, 0), '09:00'), '2026-05-27'); // 15:00 МСК
  });
});

describe('approval_notify._tickOnce', () => {
  test('до времени → runFn не вызывается', async () => {
    let called = 0;
    await an._tickOnce({ pool: {}, nowMs: Date.UTC(2026, 4, 27, 5, 0), timeMsk: '09:00', runFn: async () => { called++; } });
    assert.equal(called, 0);
  });
  test('в/после времени → runFn вызывается с nowMs', async () => {
    let gotNow = null;
    await an._tickOnce({ pool: {}, nowMs: Date.UTC(2026, 4, 27, 6, 0), timeMsk: '09:00', runFn: async (_p, o) => { gotNow = o.nowMs; } });
    assert.equal(gotNow, Date.UTC(2026, 4, 27, 6, 0));
  });
  test('ошибка в runFn не пробрасывается наружу', async () => {
    await an._tickOnce({ pool: {}, nowMs: Date.UTC(2026, 4, 27, 6, 0), timeMsk: '09:00', runFn: async () => { throw new Error('boom'); } });
    assert.ok(true);
  });
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | grep -A3 "mskSendDate\|isReportDue"`
Expected: FAIL (`an.mskSendDate`/`an.isReportDue` не определены; `_tickOnce` ждёт `window`, а не `timeMsk`).

- [ ] **Step 3: Реализовать single-time расписание в `approval_notify.js`**

Удалить функции `hourBucket`, `mskHour`, `parseWindow`, `isInWindow` (строки ~24-47). Добавить вместо них:

```js
// Дата в МСК (YYYY-MM-DD) для UTC-момента — дневной ключ идемпотентности.
function mskSendDate(nowMs) { return mskDateOffset(nowMs, 0); }

// Если в МСК уже >= HH:MM — вернуть дату отправки (catch-up в течение суток), иначе null.
function isReportDue(nowMs, targetHHMM) {
  const msk = new Date(nowMs + MSK_OFFSET_MS);
  const [th, tm] = String(targetHHMM || '09:00').split(':').map(Number);
  const hh = msk.getUTCHours(), mm = msk.getUTCMinutes();
  if (hh > th || (hh === th && mm >= tm)) return mskSendDate(nowMs);
  return null;
}
```

В `runApprovalNotify`:
- Обновить `isEmpty`:
  ```js
  const isEmpty = summary.pendingApproval.length === 0
    && summary.emptyTomorrow.length === 0 && summary.emptyDayAfter.length === 0;
  ```
- Заменить claim-ключ `const bucket = hourBucket(nowMs);` на `const bucket = mskSendDate(nowMs);` и лог `${bucket.toISOString()}` → `${bucket}` (две строки: skip и sent).

Заменить `_tickOnce`:

```js
async function _tickOnce({ pool, nowMs, timeMsk, runFn }) {
  if (!isReportDue(nowMs, timeMsk)) return;
  if (_running) { console.log('[approval-notify] tick skipped: previous run still in progress'); return; }
  _running = true;
  try { await runFn(pool, { nowMs }); }
  catch (e) { console.error('[approval-notify] tick error:', e.message); }
  finally { _running = false; }
}
```

Заменить `startApprovalNotifyCron`:

```js
function startApprovalNotifyCron(pool) {
  if (process.env.APPROVAL_NOTIFY_ENABLED === '0') {
    console.log('[approval-notify] disabled via APPROVAL_NOTIFY_ENABLED=0');
    return;
  }
  const timeMsk = process.env.APPROVAL_NOTIFY_TIME_MSK || '09:00';
  console.log(`[approval-notify] scheduled daily at ${timeMsk} MSK (60s tick, catch-up enabled)`);
  setInterval(() => {
    _tickOnce({ pool, nowMs: Date.now(), timeMsk, runFn: runApprovalNotify })
      .catch(e => console.error('[approval-notify] tick error:', e.message));
  }, 60 * 1000);
}
```

Обновить `module.exports`: убрать `hourBucket, mskHour, parseWindow, isInWindow`; добавить `mskSendDate, isReportDue`. Обновить ENV-комментарий в шапке файла: `APPROVAL_NOTIFY_WINDOW` → `APPROVAL_NOTIFY_TIME_MSK (09:00) — время отправки в МСК (HH:MM), catch-up до конца суток`.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | tail -5`
Expected: все тесты PASS.

- [ ] **Step 5: Commit**

```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "feat(wp161): каденция — 1 раз в 09:00 МСК (APPROVAL_NOTIFY_TIME_MSK), дневной claim"
```

---

## Task 5: Прогон всех тестов + смок на живой БД

**Files:** нет (верификация)

- [ ] **Step 1: Полный прогон юнит-тестов**

Run: `node --test tests/test_approval_notify.test.js 2>&1 | tail -8`
Expected: `pass N`, `fail 0`.

- [ ] **Step 2: Смок на живой БД (dry-run, без отправки)**

Run: `node approval_notify.js --dry-run`
Expected: печатается текст сводки. Проверить вручную:
- Блок «нет контента»: на 31.05 присутствует **AXILOR Private**; **ClickPay / Splus / PANDAFiT** ОТСУТСТВУЮТ (у них есть заполненный слот на оба дня).
- Блок «на одобрении»: даты всех роликов ≥ сегодня; роликов с прошлыми датами и «дата не назначена» нет.
- Два отдельных абзаца «на завтра» / «на послезавтра» (тот, где нет клиентов, отсутствует).

- [ ] **Step 3: Точечная сверка SQL #2 на БД**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "
SELECT vp.project, to_char(s.slot_date,'YYYY-MM-DD') AS day
FROM validator_schedule_slots s JOIN validator_projects vp ON vp.id=s.project_id
WHERE s.slot_date IN ((now() AT TIME ZONE 'Europe/Moscow')::date + 1,
                      (now() AT TIME ZONE 'Europe/Moscow')::date + 2)
  AND vp.active = true
GROUP BY vp.project, s.slot_date
HAVING count(*) FILTER (WHERE s.content_id IS NOT NULL) = 0
ORDER BY s.slot_date, vp.project;"
```
Expected: список совпадает с блоком «нет контента» из dry-run (sanity-чек, что SQL в коде эквивалентен).

- [ ] **Step 4: Commit (если остались несохранённые правки)**

```bash
git status --short
# при необходимости:
git add -A && git commit -m "test(wp161): верификация iter2 (юниты + смок живой БД)"
```

---

## Деплой (после approval)

1. Push ветки autowarm в **GenGo2/delivery-contenthunter `main`** (или PR → merge).
2. Прод (`/root/.openclaw/workspace-genri/autowarm`, ветка main): `git pull`.
3. `sudo pm2 restart autowarm` — крон перечитает `APPROVAL_NOTIFY_TIME_MSK` (default 09:00), залогирует `[approval-notify] scheduled daily at 09:00 MSK`.
4. Прод `.env` (под root): `APPROVAL_NOTIFY_WINDOW` можно удалить (игнорируется); явный `APPROVAL_NOTIFY_TIME_MSK` не обязателен.
5. Смок в проде: `node approval_notify.js --dry-run` → сверить оба блока.
6. Миграция не требуется (`approval_notify_runs` переиспользуется, дневной ключ пишется в существующую `report_hour::timestamptz`).

Kill-switch `APPROVAL_NOTIFY_ENABLED=0` наготове. Verify первой автоматической отправки в 09:00 МСК следующего дня → OpenProject «Тестирование» → «Готово».
