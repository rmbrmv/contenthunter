# WP#161 — Telegram-уведомления одобрение/отсутствие контента — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Раз в час (в окне 09–18 МСК) слать в Telegram-тред «Модерация и уникал» сводку: ролики на ручном одобрении (`needs_review`) с плановыми датами по клиентам + клиенты с пустыми слотами на завтра/послезавтра.

**Architecture:** Новый самостоятельный модуль `approval_notify.js` в autowarm-репо по образцу рабочего `daily_publish_report.js` (WP#114): `setInterval`-тик 60с, окно МСК, per-hour claim для идемпотентности (таблица `approval_notify_runs`), ретраи, kill-switch. Данные — два SELECT по единой БД `openclaw` (там и `validator_*`, и расписание). Отправка через общий хелпер `telegram_send.js`.

**Tech Stack:** Node.js (CommonJS), `node:test` + `node:assert/strict`, PostgreSQL (`pg` Pool), глобальный `fetch`, Telegram Bot API.

**Repo / ветка:** реализация в autowarm-репо (`workspace-genri/autowarm`, локальный чекаут `/home/claude-user/wp109-autowarm`). Перед началом создать изолированный worktree (`git worktree add`), чтобы не мешать параллельной сессии на этом чекауте; базовая ветка — текущая прод-ветка autowarm (подтвердить перед стартом, по умолчанию та, что задеплоена). Спека: `docs/superpowers/specs/2026-05-27-wp161-tg-approval-notify-design.md` (репо contenthunter).

**Все пути ниже — относительно корня autowarm-репо.** Команды тестов: `node --test --test-force-exit tests/test_approval_notify.test.js`.

---

## File Structure

| Файл | Ответственность |
|---|---|
| `telegram_send.js` (создать) | Общий хелпер: `escapeHtml` + `sendTelegram` (POST sendMessage + ретраи). Только для нового модуля; `daily_publish_report.js` не трогаем |
| `approval_notify.js` (создать) | Весь модуль: time/window-хелперы, `buildApprovalSummary` (2 SQL), `formatMessage`, `_claim`, `runApprovalNotify`, `_tickOnce`, `startApprovalNotifyCron`, CLI |
| `migrations/20260527_approval_notify_runs.sql` (создать) | Таблица идемпотентности `approval_notify_runs` |
| `migrations/20260527_approval_notify_runs__rollback.sql` (создать) | Откат (DROP) |
| `tests/test_approval_notify.test.js` (создать) | Unit-тесты чистых функций + орк-путей через fake pool |
| `server.js` (изменить, ~строка 6939) | Регистрация `startApprovalNotifyCron(pool)` после `startDailyReportCron(pool)` |

---

## Task 1: Миграция `approval_notify_runs`

**Files:**
- Create: `migrations/20260527_approval_notify_runs.sql`
- Create: `migrations/20260527_approval_notify_runs__rollback.sql`

- [ ] **Step 1: Создать миграцию**

`migrations/20260527_approval_notify_runs.sql`:
```sql
-- WP#161: почасовые TG-уведомления одобрение/отсутствие контента — журнал идемпотентности.
-- Spec: docs/superpowers/specs/2026-05-27-wp161-tg-approval-notify-design.md
CREATE TABLE IF NOT EXISTS approval_notify_runs (
  report_hour timestamptz PRIMARY KEY,                  -- начало UTC-часа (= МСК-часа, UTC+3 без DST)
  status      text        NOT NULL DEFAULT 'pending',   -- pending | sending | sent | failed
  sent_at     timestamptz,
  claimed_at  timestamptz,
  attempts    int         NOT NULL DEFAULT 0,
  payload     text
);
```

- [ ] **Step 2: Создать rollback**

`migrations/20260527_approval_notify_runs__rollback.sql`:
```sql
DROP TABLE IF EXISTS approval_notify_runs;
```

- [ ] **Step 3: Применить миграцию к openclaw и проверить**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f migrations/20260527_approval_notify_runs.sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d approval_notify_runs"
```
Expected: `CREATE TABLE`, затем описание таблицы с колонкой `report_hour timestamptz` PRIMARY KEY. Таблица аддитивная — рисков нет.

- [ ] **Step 4: Commit**
```bash
git add migrations/20260527_approval_notify_runs.sql migrations/20260527_approval_notify_runs__rollback.sql
git commit -m "feat(wp161): миграция approval_notify_runs (идемпотентность почасовых TG-уведомлений)"
```

---

## Task 2: `telegram_send.js` — общий хелпер + тест `escapeHtml`

**Files:**
- Create: `telegram_send.js`
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Написать падающий тест**

`tests/test_approval_notify.test.js` (новый файл):
```js
'use strict';
const { test, describe } = require('node:test');
const assert = require('node:assert/strict');

const tg = require('../telegram_send.js');

describe('telegram_send.escapeHtml', () => {
  test('экранирует & < > для parse_mode=HTML', () => {
    assert.equal(tg.escapeHtml('A & B <c> "d"'), 'A &amp; B &lt;c&gt; "d"');
  });
  test('не-строку приводит к строке', () => {
    assert.equal(tg.escapeHtml(42), '42');
  });
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: FAIL — `Cannot find module '../telegram_send.js'`.

- [ ] **Step 3: Реализовать `telegram_send.js`**

`telegram_send.js`:
```js
'use strict';
// Общий хелпер отправки в Telegram (escape HTML + sendMessage + ретраи).
// Используется approval_notify.js (WP#161). daily_publish_report.js имеет
// собственную копию и от этого модуля не зависит.

// Экранирование для parse_mode=HTML: имена клиентов могут содержать < > &
// (иначе Telegram отвергает всё сообщение с parse error).
function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const _sleep = ms => new Promise(r => setTimeout(r, ms));

async function sendTelegram(text, { token, chatId, threadId, maxAttempts = 3, backoffMs = 1000 }) {
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const payload = { chat_id: chatId, text, parse_mode: 'HTML', disable_web_page_preview: true };
  if (threadId) payload.message_thread_id = threadId;

  let lastErr = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const resp = await fetch(url, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
      });
      if (resp.ok) return { ok: true };
      const data = await resp.json().catch(() => ({}));
      lastErr = `http ${resp.status} ${data.description || ''}`.trim();
    } catch (e) { lastErr = e.message; }
    if (attempt < maxAttempts) await _sleep(backoffMs * Math.pow(2, attempt - 1));
  }
  return { ok: false, description: lastErr };
}

module.exports = { escapeHtml, sendTelegram };
```

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**
```bash
git add telegram_send.js tests/test_approval_notify.test.js
git commit -m "feat(wp161): telegram_send.js — общий хелпер escapeHtml + sendTelegram"
```

---

## Task 3: `approval_notify.js` — time/window-хелперы + тесты

**Files:**
- Create: `approval_notify.js`
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Дописать падающие тесты**

Добавить в `tests/test_approval_notify.test.js`:
```js
const an = require('../approval_notify.js');

describe('approval_notify.hourBucket', () => {
  test('усекает до начала UTC-часа', () => {
    assert.equal(an.hourBucket(Date.UTC(2026, 4, 27, 10, 37, 12)).toISOString(), '2026-05-27T10:00:00.000Z');
  });
});

describe('approval_notify.mskHour', () => {
  test('06:00 UTC → 09 МСК', () => assert.equal(an.mskHour(Date.UTC(2026, 4, 27, 6, 0)), 9));
  test('21:30 UTC → 00 МСК (след. сутки)', () => assert.equal(an.mskHour(Date.UTC(2026, 4, 27, 21, 30)), 0));
});

describe('approval_notify.parseWindow', () => {
  test('"9-18" → {9,18}', () => assert.deepEqual(an.parseWindow('9-18'), { startH: 9, endH: 18 }));
  test('пусто → дефолт 9-18', () => assert.deepEqual(an.parseWindow(''), { startH: 9, endH: 18 }));
  test('мусор → дефолт 9-18', () => assert.deepEqual(an.parseWindow('abc'), { startH: 9, endH: 18 }));
});

describe('approval_notify.isInWindow', () => {
  const w = { startH: 9, endH: 18 };
  test('09 МСК (06 UTC) — в окне', () => assert.equal(an.isInWindow(Date.UTC(2026, 4, 27, 6, 0), w), true));
  test('08:59 МСК (05:59 UTC) — вне окна', () => assert.equal(an.isInWindow(Date.UTC(2026, 4, 27, 5, 59), w), false));
  test('18:30 МСК (15:30 UTC) — в окне (час 18 включительно)', () => assert.equal(an.isInWindow(Date.UTC(2026, 4, 27, 15, 30), w), true));
  test('19:00 МСК (16:00 UTC) — вне окна', () => assert.equal(an.isInWindow(Date.UTC(2026, 4, 27, 16, 0), w), false));
});

describe('approval_notify.mskDateOffset', () => {
  test('+1 / +2 дня в МСК', () => {
    const now = Date.UTC(2026, 4, 27, 9, 0); // 12:00 МСК 27.05
    assert.equal(an.mskDateOffset(now, 1), '2026-05-28');
    assert.equal(an.mskDateOffset(now, 2), '2026-05-29');
  });
  test('поздний МСК-час корректно перекатывает дату', () => {
    const now = Date.UTC(2026, 4, 27, 21, 30); // 00:30 МСК 28.05
    assert.equal(an.mskDateOffset(now, 1), '2026-05-29');
  });
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: FAIL — `Cannot find module '../approval_notify.js'`.

- [ ] **Step 3: Создать `approval_notify.js` с константами и хелперами**

`approval_notify.js`:
```js
'use strict';
// WP#161 — почасовые TG-уведомления: ролики на одобрении (needs_review) +
// клиенты с пустыми слотами на завтра/послезавтра. Тред «Модерация и уникал».
// Spec: docs/superpowers/specs/2026-05-27-wp161-tg-approval-notify-design.md
//
// ENV (дефолты в скобках):
//   APPROVAL_NOTIFY_ENABLED        (1)  — '0' выключает cron целиком
//   APPROVAL_NOTIFY_BOT_TOKEN      — токен @gengo_tech_notify_1_bot (обязателен)
//   APPROVAL_NOTIFY_CHAT_ID        (-1003262248975) — целевой чат
//   APPROVAL_NOTIFY_THREAD_ID      (10477) — message_thread_id топика
//   APPROVAL_NOTIFY_WINDOW         (9-18) — окно часов МСК включительно, формат start-end
//   APPROVAL_NOTIFY_SUPPRESS_EMPTY (1)  — '0' слать даже когда оба списка пусты
//   APPROVAL_NOTIFY_MAX_ATTEMPTS   (3)  — макс. попыток claim+send на один час
const { escapeHtml, sendTelegram } = require('./telegram_send.js');

const MSK_OFFSET_MS = 3 * 60 * 60 * 1000; // МСК = UTC+3 (без DST)
const HOUR_MS = 60 * 60 * 1000;
const DEFAULT_CHAT_ID = '-1003262248975';
const DEFAULT_THREAD_ID = '10477';

const _p2 = n => String(n).padStart(2, '0');

// Начало текущего UTC-часа (= начало МСК-часа, т.к. UTC+3) как Date — ключ идемпотентности.
function hourBucket(nowMs) {
  return new Date(Math.floor(nowMs / HOUR_MS) * HOUR_MS);
}

// Час в МСК (0..23) для UTC-момента.
function mskHour(nowMs) {
  return new Date(nowMs + MSK_OFFSET_MS).getUTCHours();
}

// 'start-end' → {startH, endH}; невалидное → дефолт 9-18.
function parseWindow(spec) {
  const m = String(spec || '').match(/^(\d{1,2})-(\d{1,2})$/);
  if (!m) return { startH: 9, endH: 18 };
  const startH = Math.max(0, Math.min(23, parseInt(m[1], 10)));
  const endH = Math.max(0, Math.min(23, parseInt(m[2], 10)));
  return { startH, endH };
}

// Час МСК в окне [startH, endH] включительно.
function isInWindow(nowMs, { startH, endH }) {
  const h = mskHour(nowMs);
  return h >= startH && h <= endH;
}

// Дата в МСК со сдвигом days дней, формат 'YYYY-MM-DD'.
function mskDateOffset(nowMs, days) {
  const msk = new Date(nowMs + MSK_OFFSET_MS + days * 24 * HOUR_MS);
  return `${msk.getUTCFullYear()}-${_p2(msk.getUTCMonth() + 1)}-${_p2(msk.getUTCDate())}`;
}

module.exports = {
  MSK_OFFSET_MS, HOUR_MS, DEFAULT_CHAT_ID, DEFAULT_THREAD_ID,
  hourBucket, mskHour, parseWindow, isInWindow, mskDateOffset,
};
```

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: PASS (все тесты, включая Task 2).

- [ ] **Step 5: Commit**
```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "feat(wp161): approval_notify.js — time/window-хелперы (МСК, окно, hour-bucket)"
```

---

## Task 4: `formatMessage` + склонение числительных + тесты

**Files:**
- Modify: `approval_notify.js`
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Дописать падающие тесты**

Добавить в `tests/test_approval_notify.test.js`:
```js
describe('approval_notify.formatMessage', () => {
  test('оба блока: счётчик роликов, клиенты с датами, escape', () => {
    const txt = an.formatMessage({
      pendingApproval: [
        { client: 'Клиент A', contentId: 1, dates: ['2026-05-28', '2026-05-29'] },
        { client: 'Клиент B', contentId: 2, dates: ['2026-05-28'] },
        { client: 'Клиент C', contentId: 3, dates: [] },
      ],
      emptySlots: ['Клиент 1', 'Клиент 2'],
    });
    assert.match(txt, /На одобрении: 3 ролика/);
    assert.match(txt, /Клиент A — 28\.05, 29\.05/);
    assert.match(txt, /Клиент B — 28\.05/);
    assert.match(txt, /Клиент C — дата не назначена/);
    assert.match(txt, /Контент не загружен на завтра\/послезавтра \(2\)/);
    assert.match(txt, /Клиент 1, Клиент 2/);
  });
  test('склонение: 1 ролик, 5 роликов', () => {
    const one = an.formatMessage({ pendingApproval: [{ client: 'X', contentId: 1, dates: ['2026-05-28'] }], emptySlots: [] });
    assert.match(one, /На одобрении: 1 ролик(?!\w)/);
    const five = an.formatMessage({
      pendingApproval: Array.from({ length: 5 }, (_, i) => ({ client: 'C' + i, contentId: i, dates: [] })),
      emptySlots: [],
    });
    assert.match(five, /На одобрении: 5 роликов/);
  });
  test('даты одного клиента из нескольких роликов: дедуп + сортировка', () => {
    const txt = an.formatMessage({
      pendingApproval: [
        { client: 'Дубль', contentId: 1, dates: ['2026-05-29'] },
        { client: 'Дубль', contentId: 2, dates: ['2026-05-28', '2026-05-29'] },
      ],
      emptySlots: [],
    });
    assert.match(txt, /Дубль — 28\.05, 29\.05/);
  });
  test('только блок «нет контента»', () => {
    const txt = an.formatMessage({ pendingApproval: [], emptySlots: ['Y'] });
    assert.doesNotMatch(txt, /На одобрении/);
    assert.match(txt, /Контент не загружен на завтра\/послезавтра \(1\)/);
  });
  test('escape опасных символов в имени клиента', () => {
    const txt = an.formatMessage({ pendingApproval: [], emptySlots: ['A & <b>'] });
    assert.match(txt, /A &amp; &lt;b&gt;/);
  });
  test('оба пусты → «всё чисто»', () => {
    assert.match(an.formatMessage({ pendingApproval: [], emptySlots: [] }), /Всё одобрено/);
  });
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: FAIL — `an.formatMessage is not a function`.

- [ ] **Step 3: Реализовать `formatMessage` (+ хелперы) и добавить в экспорт**

В `approval_notify.js` добавить перед `module.exports`:
```js
// Русское склонение: 1 ролик / 2-4 ролика / 5+ роликов (с учётом 11-14).
function _plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

// 'YYYY-MM-DD' → 'DD.MM'.
function _isoToDDMM(iso) { const [, m, d] = iso.split('-'); return `${d}.${m}`; }

// summary = { pendingApproval: [{client, contentId, dates:['YYYY-MM-DD'...]}], emptySlots: ['Клиент'...] }
function formatMessage(summary) {
  const pending = summary.pendingApproval || [];
  const empty = summary.emptySlots || [];
  const lines = [];

  if (pending.length) {
    const n = pending.length; // одна строка = один ролик needs_review
    lines.push(`🎬 <b>На одобрении: ${n} ${_plural(n, 'ролик', 'ролика', 'роликов')}</b>`);
    // Группируем по клиенту, объединяя даты всех его роликов.
    const byClient = new Map();
    for (const row of pending) {
      if (!byClient.has(row.client)) byClient.set(row.client, new Set());
      for (const d of (row.dates || [])) byClient.get(row.client).add(d);
    }
    for (const [client, dateSet] of byClient) {
      const dates = Array.from(dateSet).sort(); // ISO сортируется хронологически
      const datesStr = dates.length ? dates.map(_isoToDDMM).join(', ') : 'дата не назначена';
      lines.push(`• ${escapeHtml(client)} — ${datesStr}`);
    }
  }

  if (empty.length) {
    if (lines.length) lines.push('');
    const m = empty.length;
    lines.push(`📭 <b>Контент не загружен на завтра/послезавтра (${m}):</b>`);
    lines.push(empty.map(escapeHtml).join(', '));
  }

  if (!lines.length) return '✅ Всё одобрено, контент на завтра/послезавтра загружен.';
  return lines.join('\n');
}
```

Обновить `module.exports`, добавив: `_plural, formatMessage`.

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "feat(wp161): formatMessage — сводка одобрение/нет контента + склонение"
```

---

## Task 5: `buildApprovalSummary` (2 SQL) + тест на fake pool

**Files:**
- Modify: `approval_notify.js`
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Дописать падающий тест (fake pool)**

Добавить в `tests/test_approval_notify.test.js`:
```js
// Fake pool: отдаёт канонные строки по подстроке в SQL.
function fakePool(handlers) {
  const calls = [];
  return {
    calls,
    async query(sql, params) {
      calls.push({ sql, params });
      for (const h of handlers) {
        if (sql.includes(h.match)) {
          return { rows: h.rows || [], rowCount: h.rowCount ?? (h.rows ? h.rows.length : 0) };
        }
      }
      return { rows: [], rowCount: 0 };
    },
  };
}

describe('approval_notify.buildApprovalSummary', () => {
  test('маппит needs_review-строки и пустые слоты; даты вычислены в МСК', async () => {
    const pool = fakePool([
      { match: "vc.status = 'needs_review'", rows: [
        { client: 'Клиент A', content_id: 1, slot_dates: ['2026-05-28'] },
        { client: 'Клиент B', content_id: 2, slot_dates: null },
      ]},
      { match: 'validator_schedule_slots s', rows: [{ client: 'Клиент Z' }] },
    ]);
    const now = Date.UTC(2026, 4, 27, 9, 0); // 12:00 МСК 27.05
    const s = await an.buildApprovalSummary(pool, { nowMs: now });

    assert.deepEqual(s.pendingApproval, [
      { client: 'Клиент A', contentId: 1, dates: ['2026-05-28'] },
      { client: 'Клиент B', contentId: 2, dates: [] },
    ]);
    assert.deepEqual(s.emptySlots, ['Клиент Z']);
    // второй запрос получил завтра+послезавтра в МСК
    const emptyCall = pool.calls.find(c => c.sql.includes('validator_schedule_slots s'));
    assert.deepEqual(emptyCall.params, ['2026-05-28', '2026-05-29']);
  });
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: FAIL — `an.buildApprovalSummary is not a function`.

- [ ] **Step 3: Реализовать `buildApprovalSummary`**

В `approval_notify.js` добавить перед `module.exports`:
```js
async function buildApprovalSummary(pool, opts = {}) {
  const nowMs = opts.nowMs ?? Date.now();
  const tomorrow = mskDateOffset(nowMs, 1);
  const dayAfter = mskDateOffset(nowMs, 2);

  // Блок 1: ролики needs_review + плановые даты. Даты форматируем в SQL (ISO-текст,
  // сортируемо, обходит tz-парсинг DATE в node-pg). GROUP BY vc.id → одна строка на ролик
  // (LEFT JOIN не размножает; счётчик = число строк).
  const { rows: pendingRows } = await pool.query(`
    SELECT vp.project AS client,
           vc.id AS content_id,
           array_agg(to_char(s.slot_date, 'YYYY-MM-DD') ORDER BY s.slot_date)
             FILTER (WHERE s.slot_date IS NOT NULL) AS slot_dates
    FROM validator_content vc
    JOIN validator_projects vp ON vp.id = vc.project_id
    LEFT JOIN validator_schedule_slots s ON s.content_id = vc.id
    WHERE vc.status = 'needs_review'
    GROUP BY vp.project, vc.id
    ORDER BY vp.project, vc.id
  `);

  // Блок 2: активные клиенты с пустым слотом на завтра/послезавтра.
  const { rows: emptyRows } = await pool.query(`
    SELECT DISTINCT vp.project AS client
    FROM validator_schedule_slots s
    JOIN validator_projects vp ON vp.id = s.project_id
    WHERE s.slot_date IN ($1::date, $2::date)
      AND (s.content_id IS NULL OR s.status = 'empty')
      AND vp.active = true
    ORDER BY vp.project
  `, [tomorrow, dayAfter]);

  return {
    pendingApproval: pendingRows.map(r => ({ client: r.client, contentId: r.content_id, dates: r.slot_dates || [] })),
    emptySlots: emptyRows.map(r => r.client),
  };
}
```

Обновить `module.exports`, добавив: `buildApprovalSummary`.

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "feat(wp161): buildApprovalSummary — 2 SQL по openclaw (needs_review + пустые слоты)"
```

---

## Task 6: `_claim` + `runApprovalNotify` (оркестрация) + тесты путей

**Files:**
- Modify: `approval_notify.js`
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Дописать падающие тесты**

Добавить в `tests/test_approval_notify.test.js`:
```js
describe('approval_notify.runApprovalNotify', () => {
  const nonEmpty = [
    { match: "vc.status = 'needs_review'", rows: [{ client: 'A', content_id: 1, slot_dates: ['2026-05-28'] }] },
    { match: 'validator_schedule_slots s', rows: [] },
  ];

  test('нет токена → misconfigured, без запросов к БД', async () => {
    const pool = fakePool([]);
    const r = await an.runApprovalNotify(pool, { nowMs: Date.UTC(2026, 4, 27, 9, 0), token: '' });
    assert.equal(r.status, 'misconfigured');
    assert.equal(pool.calls.length, 0);
  });

  test('оба списка пусты + suppress → skipped_empty, без claim', async () => {
    const pool = fakePool([
      { match: "vc.status = 'needs_review'", rows: [] },
      { match: 'validator_schedule_slots s', rows: [] },
    ]);
    const r = await an.runApprovalNotify(pool, {
      nowMs: Date.UTC(2026, 4, 27, 9, 0), token: 'T', suppressEmpty: true,
    });
    assert.equal(r.status, 'skipped_empty');
    assert.ok(!pool.calls.some(c => c.sql.includes('INSERT INTO approval_notify_runs')));
  });

  test('dry-run с данными → текст без отправки/claim', async () => {
    const pool = fakePool(nonEmpty);
    const r = await an.runApprovalNotify(pool, {
      nowMs: Date.UTC(2026, 4, 27, 9, 0), token: 'T', dryRun: true,
    });
    assert.equal(r.status, 'dry-run');
    assert.match(r.text, /На одобрении: 1 ролик/);
    assert.ok(!pool.calls.some(c => c.sql.includes('INSERT INTO approval_notify_runs')));
  });

  test('claim не удался → skipped (без отправки)', async () => {
    const pool = fakePool([
      ...nonEmpty,
      { match: 'INSERT INTO approval_notify_runs', rows: [], rowCount: 0 },
    ]);
    const r = await an.runApprovalNotify(pool, {
      nowMs: Date.UTC(2026, 4, 27, 9, 0), token: 'T', suppressEmpty: true,
    });
    assert.equal(r.status, 'skipped');
  });
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: FAIL — `an.runApprovalNotify is not a function`.

- [ ] **Step 3: Реализовать `_claim` и `runApprovalNotify`**

В `approval_notify.js` добавить перед `module.exports`:
```js
// Кросс-процессная идемпотентность: claim ставит транзиентный status='sending'.
// Краш во время отправки оставит 'sending' — переклеймится через 10 мин (staleness).
// Зеркало daily_publish_report._claim.
async function _claim(pool, hourBucketDate, maxAttempts) {
  const r = await pool.query(`
    INSERT INTO approval_notify_runs (report_hour, status, attempts, claimed_at)
    VALUES ($1, 'sending', 1, now())
    ON CONFLICT (report_hour) DO UPDATE
      SET attempts = approval_notify_runs.attempts + 1,
          status = 'sending',
          claimed_at = now()
    WHERE approval_notify_runs.status <> 'sent'
      AND approval_notify_runs.attempts < $2
      AND (approval_notify_runs.status <> 'sending'
           OR approval_notify_runs.claimed_at < now() - interval '10 minutes')
    RETURNING report_hour
  `, [hourBucketDate, maxAttempts]);
  return r.rowCount === 1;
}

async function runApprovalNotify(pool, opts = {}) {
  const nowMs = opts.nowMs ?? Date.now();
  const dryRun = !!opts.dryRun;
  const maxAttempts = opts.maxAttempts ?? parseInt(process.env.APPROVAL_NOTIFY_MAX_ATTEMPTS || '3', 10);
  const suppressEmpty = opts.suppressEmpty ?? (process.env.APPROVAL_NOTIFY_SUPPRESS_EMPTY !== '0');
  const token = opts.token ?? process.env.APPROVAL_NOTIFY_BOT_TOKEN;
  const chatId = opts.chatId ?? (process.env.APPROVAL_NOTIFY_CHAT_ID || DEFAULT_CHAT_ID);
  const threadId = opts.threadId ?? (process.env.APPROVAL_NOTIFY_THREAD_ID || DEFAULT_THREAD_ID);

  // Preflight ДО claim: пустой token не должен сжигать maxAttempts на провальных отправках.
  if (!dryRun && !token) {
    console.error('[approval-notify] missing APPROVAL_NOTIFY_BOT_TOKEN — skip without claiming (fix env, retry next tick)');
    return { status: 'misconfigured' };
  }

  // Сводку строим ДО claim — пустые часы не оставляют строк в журнале.
  const summary = await buildApprovalSummary(pool, { nowMs });
  const isEmpty = summary.pendingApproval.length === 0 && summary.emptySlots.length === 0;
  if (isEmpty && suppressEmpty) {
    console.log('[approval-notify] nothing to report this hour — skip (suppress empty)');
    return { status: 'skipped_empty' };
  }

  const text = formatMessage(summary);
  if (dryRun) { console.log('[approval-notify] DRY-RUN:\n' + text); return { status: 'dry-run', text }; }

  const bucket = hourBucket(nowMs);
  const claimed = await _claim(pool, bucket, maxAttempts);
  if (!claimed) {
    console.log(`[approval-notify] ${bucket.toISOString()}: skip (already sent or attempts exhausted)`);
    return { status: 'skipped' };
  }

  const res = await sendTelegram(text, { token, chatId, threadId });
  if (res.ok) {
    await pool.query(`UPDATE approval_notify_runs SET status='sent', sent_at=now(), payload=$2 WHERE report_hour=$1`, [bucket, text]);
    console.log(`[approval-notify] ${bucket.toISOString()}: sent`);
    return { status: 'sent', text };
  }
  await pool.query(`UPDATE approval_notify_runs SET status='failed', payload=$2 WHERE report_hour=$1`, [bucket, text]);
  console.error(`[approval-notify] ${bucket.toISOString()}: send failed: ${res.description}`);
  return { status: 'failed', description: res.description };
}
```

Обновить `module.exports`, добавив: `_claim, runApprovalNotify`.

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "feat(wp161): runApprovalNotify + _claim — оркестрация с per-hour идемпотентностью"
```

---

## Task 7: `_tickOnce` + `startApprovalNotifyCron` + CLI + тесты тика

**Files:**
- Modify: `approval_notify.js`
- Test: `tests/test_approval_notify.test.js`

- [ ] **Step 1: Дописать падающие тесты**

Добавить в `tests/test_approval_notify.test.js`:
```js
describe('approval_notify._tickOnce', () => {
  const w = { startH: 9, endH: 18 };
  test('вне окна → runFn не вызывается', async () => {
    let called = 0;
    await an._tickOnce({ pool: {}, nowMs: Date.UTC(2026, 4, 27, 16, 0), window: w, runFn: async () => { called++; } });
    assert.equal(called, 0);
  });
  test('в окне → runFn вызывается с nowMs', async () => {
    let gotNow = null;
    await an._tickOnce({ pool: {}, nowMs: Date.UTC(2026, 4, 27, 6, 0), window: w, runFn: async (_p, o) => { gotNow = o.nowMs; } });
    assert.equal(gotNow, Date.UTC(2026, 4, 27, 6, 0));
  });
  test('ошибка в runFn не пробрасывается наружу', async () => {
    await an._tickOnce({ pool: {}, nowMs: Date.UTC(2026, 4, 27, 6, 0), window: w, runFn: async () => { throw new Error('boom'); } });
    // если дошли сюда без throw — ок
    assert.ok(true);
  });
});

describe('approval_notify.startApprovalNotifyCron', () => {
  test('ENABLED=0 → cron не стартует (возвращает undefined без таймера)', () => {
    const prev = process.env.APPROVAL_NOTIFY_ENABLED;
    process.env.APPROVAL_NOTIFY_ENABLED = '0';
    try {
      const r = an.startApprovalNotifyCron({});
      assert.equal(r, undefined);
    } finally {
      if (prev === undefined) delete process.env.APPROVAL_NOTIFY_ENABLED; else process.env.APPROVAL_NOTIFY_ENABLED = prev;
    }
  });
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: FAIL — `an._tickOnce is not a function`.

- [ ] **Step 3: Реализовать `_tickOnce`, `startApprovalNotifyCron`, CLI**

В `approval_notify.js` добавить перед `module.exports`:
```js
// Одна итерация тика (вынесена для тестируемости). _running guard защищает от overlap:
// setInterval не ждёт async; при прогоне >60с следующий тик иначе мог бы дублировать.
let _running = false;
async function _tickOnce({ pool, nowMs, window, runFn }) {
  if (!isInWindow(nowMs, window)) return;
  if (_running) { console.log('[approval-notify] tick skipped: previous run still in progress'); return; }
  _running = true;
  try { await runFn(pool, { nowMs }); }
  catch (e) { console.error('[approval-notify] tick error:', e.message); }
  finally { _running = false; }
}

function startApprovalNotifyCron(pool) {
  if (process.env.APPROVAL_NOTIFY_ENABLED === '0') {
    console.log('[approval-notify] disabled via APPROVAL_NOTIFY_ENABLED=0');
    return;
  }
  const window = parseWindow(process.env.APPROVAL_NOTIFY_WINDOW || '9-18');
  console.log(`[approval-notify] scheduled hourly, MSK window ${window.startH}-${window.endH} (60s tick)`);
  setInterval(() => {
    _tickOnce({ pool, nowMs: Date.now(), window, runFn: runApprovalNotify })
      .catch(e => console.error('[approval-notify] tick error:', e.message));
  }, 60 * 1000);
}
```

Обновить `module.exports`, добавив: `_tickOnce, startApprovalNotifyCron`.

В самый конец файла добавить CLI-блок:
```js
// CLI: `node approval_notify.js --once` (отправить сейчас, игнорируя окно) | `--dry-run` (печать)
if (require.main === module) {
  require('dotenv').config();
  const { Pool } = require('pg');
  const pool = new Pool({
    host: process.env.DB_HOST || 'localhost', port: parseInt(process.env.DB_PORT || '5432', 10),
    user: process.env.DB_USER || 'openclaw', password: process.env.DB_PASS || 'openclaw123',
    database: process.env.DB_NAME || 'openclaw',
  });
  const args = process.argv.slice(2);
  const once = args.includes('--once');
  const dryRun = args.includes('--dry-run') || !once; // по умолчанию безопасно: dry-run
  if (!once && !args.includes('--dry-run')) {
    console.log('[approval-notify] no flag → dry-run (use --once to actually send)');
  }
  runApprovalNotify(pool, { dryRun })
    .then(r => { console.log('[approval-notify] result:', JSON.stringify(r.status)); return pool.end(); })
    .then(() => process.exit(0))
    .catch(e => { console.error('[approval-notify] fatal:', e); process.exit(1); });
}
```

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `node --test --test-force-exit tests/test_approval_notify.test.js`
Expected: PASS (весь файл).

- [ ] **Step 5: Commit**
```bash
git add approval_notify.js tests/test_approval_notify.test.js
git commit -m "feat(wp161): _tickOnce + startApprovalNotifyCron + CLI (dry-run/once)"
```

---

## Task 8: Регистрация в `server.js` + смок против реальной БД

**Files:**
- Modify: `server.js` (после строки 6939)

- [ ] **Step 1: Добавить регистрацию крона**

В `server.js` найти (≈строки 6937-6939):
```js
// Daily publish success-rate report → Telegram (spec 2026-05-20).
const { startDailyReportCron } = require('./daily_publish_report');
startDailyReportCron(pool);
```
Добавить сразу после:
```js

// WP#161: почасовые уведомления одобрение/отсутствие контента → Telegram (spec 2026-05-27).
const { startApprovalNotifyCron } = require('./approval_notify');
startApprovalNotifyCron(pool);
```

- [ ] **Step 2: Прогнать весь тест-сьют (нет регрессий)**

Run: `node --test --test-force-exit tests/*.test.js`
Expected: PASS (включая существующие тесты — ничего не сломали).

- [ ] **Step 3: Смок dry-run против реальной openclaw**

Run: `node approval_notify.js --dry-run`
Expected: печать сводки `[approval-notify] DRY-RUN:` с реальными данными (или «✅ Всё одобрено…», если пусто) и `result: "dry-run"`. Sanity-проверить: счётчик роликов и список клиентов выглядят правдоподобно.

- [ ] **Step 4: Смок реальной отправки в тред (ОДИН раз)**

Предусловие: бот `@gengo_tech_notify_1_bot` должен состоять в группе `-1003262248975` и иметь доступ к топику `10477`. `APPROVAL_NOTIFY_BOT_TOKEN` в `.env`.

Run:
```bash
APPROVAL_NOTIFY_SUPPRESS_EMPTY=0 node approval_notify.js --once
```
Expected: `result: "sent"`, сообщение появилось в треде «Модерация и уникал». (`SUPPRESS_EMPTY=0` — чтобы получить тестовое сообщение даже при пустых списках.) Проверить запись: `psql ... -c "SELECT report_hour,status,sent_at FROM approval_notify_runs ORDER BY report_hour DESC LIMIT 3"`.

- [ ] **Step 5: Commit**
```bash
git add server.js
git commit -m "feat(wp161): подключить почасовые TG-уведомления одобрение/нет контента в server.js"
```

---

## Деплой и kill-switch (после мерджа)

- Проставить в прод-`.env` autowarm: `APPROVAL_NOTIFY_BOT_TOKEN` (= токен `@gengo_tech_notify_1_bot`). Остальные имеют дефолты (`CHAT_ID=-1003262248975`, `THREAD_ID=10477`, `WINDOW=9-18`, `SUPPRESS_EMPTY=1`).
- Применить миграцию `20260527_approval_notify_runs.sql` к прод-openclaw.
- Рестарт autowarm-процесса (PM2), чтобы `startApprovalNotifyCron` поднялся.
- Мгновенный откат: `APPROVAL_NOTIFY_ENABLED='0'` в прод-`.env` + рестарт.

---

## Self-Review (выполнено автором плана)

**Spec coverage:** §3 решения → дефолты env (Task 3/6) + queries (Task 5); §4 архитектура → Task 2/3/8; §5 запросы → Task 5 (verbatim, имена колонок верифицированы); §6 формат → Task 4; §7 расписание/идемпотентность → Task 6/7 + Task 1; §8 миграция → Task 1; §9 env → Task 3/6; §10 тесты → Tasks 2-7; §11 предусловия → Task 8 Step 4; §12 kill-switch → Task 7 (ENABLED=0) + деплой-блок. Покрыто полностью.

**Placeholder scan:** плейсхолдеров нет — весь код приведён целиком.

**Type consistency:** имена функций/полей едины во всех тасках: `escapeHtml`, `sendTelegram`, `hourBucket`, `mskHour`, `parseWindow`, `isInWindow`, `mskDateOffset`, `_plural`, `formatMessage`, `buildApprovalSummary`, `_claim`, `runApprovalNotify`, `_tickOnce`, `startApprovalNotifyCron`. Форма summary `{pendingApproval:[{client,contentId,dates}], emptySlots:[client]}` совпадает в Tasks 4/5/6. Статусы `runApprovalNotify` (`misconfigured`/`skipped_empty`/`dry-run`/`skipped`/`sent`/`failed`) согласованы с тестами.
