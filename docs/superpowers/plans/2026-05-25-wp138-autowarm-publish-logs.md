# WP #138 — Логи и статусы автовыкладки (ретрай / перевод на ручную) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать видимыми в дашборде autowarm (delivery.contenthunter.ru) уже работающие авто-ретраи и авто-переводы на ручную выкладку: писать человекочитаемое событие в лог задачи + показывать два статуса-бейджа с причиной/правилом. Логику ретраев не меняем.

**Architecture:** `retry_controller.js` при `requeue`/`handoff` дополнительно пишет структурное событие в `publish_tasks.events` (атомарно, в одной транзакции с переходом статуса) и проставляет `publish_queue.last_retry_reason`. Тексты причин — в чистом модуле `retry_labels.js`. Дашборд (`public/index.html`) рендерит два бейджа в таблицах очереди/задач и маркеры на карточках планировщика; в модалке событий — новые иконки. Подход B (минимальная миграция: 2 nullable-поля). Число попыток уже считает `attachQueueTransferColumns` (`attempt_count`) — новый только `last_retry_reason`.

**Tech Stack:** Node.js (Express `server.js`, `retry_controller.js`, `publish_planner.js`), PostgreSQL (`openclaw` @ localhost:5432, user/pass `openclaw`/`openclaw123`), `node:test` (live-DB + pure-unit), статический фронт `public/index.html` (vanilla JS + Tailwind).

**Спека:** `docs/superpowers/specs/2026-05-25-wp138-autowarm-publish-logs-design.md`

---

## Рабочее окружение (выполнить ОДИН раз перед Task 1)

Код живёт в репозитории `GenGo2/delivery-contenthunter`. Прод-checkout `/root/.openclaw/workspace-genri/autowarm/` сейчас на чужой ветке `wp128-...` (параллельная сессия) — **НЕ трогать**. Работаем в изолированном worktree от `origin/main`.

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add -b wp138-autowarm-publish-logs /home/claude-user/wt-wp138 origin/main
cd /home/claude-user/wt-wp138
# node_modules для node:test (pg). Симлинк на testbench (не копируем — экономим место):
ln -s /home/claude-user/autowarm-testbench/node_modules /home/claude-user/wt-wp138/node_modules
```

ВСЕ дальнейшие пути файлов — относительно `/home/claude-user/wt-wp138/`. Тесты и команды запускать из этого каталога.

**Помни:** post-commit hook этого репо пушит текущую ветку на origin. Это ОК — прод тянет только `main`, feature-ветку он не деплоит. Никаких `--force`.

---

## Task 1: Миграция — `last_retry_reason` + `last_retried_at` в `publish_queue`

**Files:**
- Create: `migrations/20260525_wp138_retry_visibility.sql`
- Create: `migrations/20260525_wp138_retry_visibility__rollback.sql`

- [ ] **Step 1: Cross-repo grep `publish_queue` (не словить чужую поломку `SELECT *`)**

Поля добавочные и nullable — `SELECT *` не ломают, но убеждаемся, что никто не делает `INSERT ... SELECT *` между таблицами с фиксированным числом колонок.

Run:
```bash
grep -rn "publish_queue" /root/.openclaw/workspace-genri/validator/ 2>/dev/null | grep -i "insert\|select \*" | head
grep -rn "INSERT INTO publish_queue" /home/claude-user/wt-wp138/*.js | head
```
Expected: никаких `INSERT INTO ... SELECT *` в `publish_queue`. (Вставки идут с явным списком колонок — безопасно.)

- [ ] **Step 2: Написать миграцию**

Создать `migrations/20260525_wp138_retry_visibility.sql`:
```sql
-- WP #138: видимость авто-ретраев. Идемпотентно (IF NOT EXISTS).
-- last_retry_reason — правило последнего авто-перезапуска (см. retry_decision.js).
-- last_retried_at  — когда контроллер последний раз перезапустил эту строку.
-- retry_count НЕ добавляем: число попыток уже считает attachQueueTransferColumns → attempt_count.
BEGIN;

ALTER TABLE publish_queue
  ADD COLUMN IF NOT EXISTS last_retry_reason text,
  ADD COLUMN IF NOT EXISTS last_retried_at   timestamptz;

COMMIT;
```

- [ ] **Step 3: Написать rollback**

Создать `migrations/20260525_wp138_retry_visibility__rollback.sql`:
```sql
BEGIN;
ALTER TABLE publish_queue
  DROP COLUMN IF EXISTS last_retry_reason,
  DROP COLUMN IF EXISTS last_retried_at;
COMMIT;
```

- [ ] **Step 4: Применить миграцию к локальной БД**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f migrations/20260525_wp138_retry_visibility.sql
```
Expected: `BEGIN` / `ALTER TABLE` / `COMMIT` без ошибок.

- [ ] **Step 5: Проверить, что колонки на месте**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='publish_queue' AND column_name IN ('last_retry_reason','last_retried_at') ORDER BY 1;"
```
Expected:
```
last_retried_at
last_retry_reason
```

- [ ] **Step 6: Commit**

```bash
git add migrations/20260525_wp138_retry_visibility.sql migrations/20260525_wp138_retry_visibility__rollback.sql
git commit -m "$(printf 'feat(wp138): migration — last_retry_reason/last_retried_at on publish_queue\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 2: `retry_labels.js` — чистый словарь причин → русский текст

**Files:**
- Create: `retry_labels.js`
- Test: `test_retry_labels.test.js`

- [ ] **Step 1: Написать падающий тест**

Создать `test_retry_labels.test.js`:
```js
// Run: node --test --test-force-exit test_retry_labels.test.js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { retryMessage, handoffMessage, withSource } = require('./retry_labels');

test('retryMessage: transient → про временный сбой', () => {
  assert.match(retryMessage('transient_within_limits'), /перезапущена/);
  assert.match(retryMessage('transient_within_limits'), /[Вв]ременн/);
});
test('retryMessage: fixed_at → про устранённую ошибку', () => {
  assert.match(retryMessage('fixed_at_reanimated'), /устранили/);
});
test('retryMessage: неизвестное правило → дефолт', () => {
  assert.match(retryMessage('что-то_новое'), /перезапущена/);
});
test('handoffMessage: structural+banned → про блокировку', () => {
  assert.match(handoffMessage('structural_error', 'banned'), /заблокирован/);
  assert.match(handoffMessage('structural_error', 'banned'), /ручную/);
});
test('handoffMessage: structural+ui_changed → про интерфейс', () => {
  assert.match(handoffMessage('structural_error', 'ui_changed'), /интерфейс/);
});
test('handoffMessage: window_exhausted → про 2 дня', () => {
  assert.match(handoffMessage('window_exhausted', 'network'), /2 дня/);
});
test('withSource добавляет исходную ошибку', () => {
  assert.equal(withSource('Текст.', 'adb_push_timeout'), 'Текст. Исходная ошибка: adb_push_timeout.');
  assert.equal(withSource('Текст.', null), 'Текст.');
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `node --test --test-force-exit test_retry_labels.test.js`
Expected: FAIL — `Cannot find module './retry_labels'`.

- [ ] **Step 3: Реализовать модуль**

Создать `retry_labels.js`:
```js
'use strict';
// WP #138: человекочитаемые тексты причин авто-ретрая / перевода на ручную.
// Правила (rule) приходят из retry_decision.js (decideRetry().reason).

const RETRY_MSG = {
  transient_within_limits: 'Временный сбой публикации (сеть или ограничение площадки). Задача автоматически перезапущена.',
  fixed_at_reanimated:     'Ошибку в системе устранили — задача автоматически перезапущена.',
};
const HANDOFF_MSG_BY_CLASS = {
  banned:     'Аккаунт заблокирован площадкой — задача передана на ручную выкладку.',
  ui_changed: 'Изменился интерфейс приложения — задача передана на ручную выкладку.',
};
const HANDOFF_MSG_BY_RULE = {
  window_exhausted: 'За 2 дня опубликовать автоматически не удалось — задача передана на ручную выкладку.',
};

function retryMessage(rule) {
  return RETRY_MSG[rule] || 'Задача автоматически перезапущена после ошибки.';
}
function handoffMessage(rule, errorClass) {
  if (rule === 'structural_error')
    return HANDOFF_MSG_BY_CLASS[errorClass] || 'Серьёзная ошибка — задача передана на ручную выкладку.';
  return HANDOFF_MSG_BY_RULE[rule] || 'Задача передана на ручную выкладку.';
}
function withSource(msg, errorCode) {
  return errorCode ? `${msg} Исходная ошибка: ${errorCode}.` : msg;
}

module.exports = { retryMessage, handoffMessage, withSource, RETRY_MSG, HANDOFF_MSG_BY_CLASS, HANDOFF_MSG_BY_RULE };
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_retry_labels.test.js`
Expected: PASS (7 тестов).

- [ ] **Step 5: Commit**

```bash
git add retry_labels.js test_retry_labels.test.js
git commit -m "$(printf 'feat(wp138): retry_labels — словарь причин ретрая/перевода на ручную\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 3: `retry_controller.js` — событие + `last_retry_reason` на `requeue` (атомарно)

**Files:**
- Modify: `retry_controller.js`
- Test: `test_retry_controller.test.js` (добавить кейсы)

- [ ] **Step 1: Добавить падающий тест в `test_retry_controller.test.js`**

Вставить ПЕРЕД строкой `test('kill-switch RETRY_ENGINE_ENABLED=false ...` следующие два теста:
```js
test('requeue (network) → last_retry_reason проставлен + событие retry в логе упавшей задачи', async()=>{
  await seedFailed('adb_devices_unreachable','network');
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00'), onlyClientPublishId: CPID });
  const q = (await pool.query('SELECT status, last_retry_reason FROM publish_queue WHERE id=$1',[PQ])).rows[0];
  assert.equal(q.status, 'pending');
  assert.equal(q.last_retry_reason, 'transient_within_limits');
  const ev = (await pool.query('SELECT events FROM publish_tasks WHERE id=$1',[PT])).rows[0].events || [];
  const retryEv = ev.find(e => e.type === 'retry');
  assert.ok(retryEv, 'должно быть событие type=retry');
  assert.equal(retryEv.meta.rule, 'transient_within_limits');
  assert.match(retryEv.msg, /перезапущена/);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: FAIL на новом тесте — `last_retry_reason` = undefined/null и/или нет события `type=retry`.

- [ ] **Step 3: Подключить `retry_labels` и хелпер времени в `retry_controller.js`**

В начало файла, после `const { decideRetry } = require('./retry_decision');`, добавить:
```js
const { retryMessage, handoffMessage, withSource } = require('./retry_labels');
const nowTs = () => new Date().toLocaleTimeString('ru-RU', { timeZone: 'Europe/Moscow', hour12: false });
```

- [ ] **Step 4: Добавить `lt.id` в основной SELECT**

В `retryFailedPublishes` в LATERAL-подзапросе заменить:
```js
       SELECT pt.error_code, pt.error_class, pt.updated_at AS last_failed_at
```
на:
```js
       SELECT pt.id, pt.error_code, pt.error_class, pt.updated_at AS last_failed_at
```
И во внешнем SELECT заменить:
```js
           lt.error_code, lt.error_class, lt.last_failed_at,
```
на:
```js
           lt.id AS last_task_id, lt.error_code, lt.error_class, lt.last_failed_at,
```

- [ ] **Step 5: Вычислить флаг видимости и переписать ветку `requeue` транзакционно**

В `retryFailedPublishes`, сразу после строки `const handoffEnabled = process.env.RETRY_MANUAL_HANDOFF_ENABLED !== 'false';` добавить:
```js
  const visibility = process.env.RETRY_VISIBILITY_ENABLED !== 'false'; // WP #138 kill-switch
```

Заменить весь блок:
```js
    if (decision.action === 'requeue') {
      const upd = await pool.query(
        `UPDATE publish_queue SET status='pending', publish_task_id=NULL, updated_at=NOW()
         WHERE id=$1 AND status='failed' AND manual_handoff_at IS NULL`, [r.pq_id]);
      if (upd.rowCount === 1)
        console.log(`[retry-controller] requeue pq#${r.pq_id} (${r.error_class}, ${decision.reason})`);
      else
        console.log(`[retry-controller] skip requeue pq#${r.pq_id} — строка изменилась под нами`);
    } else if (decision.action === 'handoff' && handoffEnabled) {
      await handoffToManual(pool, r, decision.reason);
    } // 'wait' / handoff-disabled — ничего не делаем
```
на:
```js
    if (decision.action === 'requeue') {
      await requeueOne(pool, r, decision.reason, visibility);
    } else if (decision.action === 'handoff' && handoffEnabled) {
      await handoffToManual(pool, r, decision.reason, visibility);
    } // 'wait' / handoff-disabled — ничего не делаем
```

- [ ] **Step 6: Добавить функцию `requeueOne` (транзакция: переход + событие атомарно)**

Перед `module.exports = ...` добавить:
```js
/** Перезапуск строки очереди + запись события в лог упавшей задачи — атомарно. */
async function requeueOne(pool, r, reason, visibility) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const upd = await client.query(
      `UPDATE publish_queue
         SET status='pending', publish_task_id=NULL, updated_at=NOW(),
             last_retry_reason = CASE WHEN $3 THEN $2 ELSE last_retry_reason END,
             last_retried_at   = CASE WHEN $3 THEN NOW() ELSE last_retried_at END
       WHERE id=$1 AND status='failed' AND manual_handoff_at IS NULL`,
      [r.pq_id, reason, visibility]);
    if (upd.rowCount !== 1) {
      await client.query('ROLLBACK');
      console.log(`[retry-controller] skip requeue pq#${r.pq_id} — строка изменилась под нами`);
      return;
    }
    if (visibility && r.last_task_id) {
      const evt = { ts: nowTs(), type: 'retry',
        msg: withSource(retryMessage(reason), r.error_code),
        meta: { rule: reason, error_class: r.error_class, error_code: r.error_code } };
      await client.query(
        `UPDATE publish_tasks SET events = COALESCE(events,'[]'::jsonb) || $2::jsonb WHERE id=$1`,
        [r.last_task_id, JSON.stringify([evt])]);
    }
    await client.query('COMMIT');
    console.log(`[retry-controller] requeue pq#${r.pq_id} (${r.error_class}, ${reason})`);
  } catch (e) {
    await client.query('ROLLBACK');
    console.error(`[retry-controller] requeue error pq#${r.pq_id}: ${e.message}`);
  } finally { client.release(); }
}
```

Также обновить экспорт (для возможных будущих тестов):
```js
module.exports = { retryFailedPublishes, handoffToManual, requeueOne };
```

- [ ] **Step 7: Запустить тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: PASS — все тесты, включая новый requeue-кейс. (Существующий тест «network с 1 попыткой → pending» тоже зелёный.)

- [ ] **Step 8: Commit**

```bash
git add retry_controller.js test_retry_controller.test.js
git commit -m "$(printf 'feat(wp138): retry_controller — событие retry + last_retry_reason на requeue (атомарно)\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 4: `retry_controller.js` — событие `handoff` внутри транзакции `handoffToManual`

**Files:**
- Modify: `retry_controller.js`
- Test: `test_retry_controller.test.js`

- [ ] **Step 1: Добавить падающий тест**

Вставить ПЕРЕД `test('kill-switch ...` (рядом с requeue-тестом из Task 3):
```js
test('handoff (banned) → событие handoff в логе упавшей задачи', async()=>{
  await seedFailed('account_banned','banned');
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00'), onlyClientPublishId: CPID });
  const ev = (await pool.query('SELECT events FROM publish_tasks WHERE id=$1',[PT])).rows[0].events || [];
  const hEv = ev.find(e => e.type === 'handoff');
  assert.ok(hEv, 'должно быть событие type=handoff');
  assert.equal(hEv.meta.rule, 'structural_error');
  assert.match(hEv.msg, /ручную/);
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: FAIL на handoff-тесте — нет события `type=handoff`.

- [ ] **Step 3: Принять `visibility` и писать событие внутри транзакции**

В сигнатуре заменить:
```js
async function handoffToManual(pool, r, reason) {
```
на:
```js
async function handoffToManual(pool, r, reason, visibility) {
```

Внутри транзакции, СРАЗУ ПОСЛЕ блока `UPDATE publish_queue SET status='cancelled', skip_reason=$2, manual_handoff_at=now()...` и ПЕРЕД `await client.query('COMMIT');`, добавить:
```js
    if (visibility && r.last_task_id) {
      const evt = { ts: nowTs(), type: 'handoff',
        msg: withSource(handoffMessage(reason, r.error_class), r.error_code),
        meta: { rule: reason, error_class: r.error_class, error_code: r.error_code } };
      await client.query(
        `UPDATE publish_tasks SET events = COALESCE(events,'[]'::jsonb) || $2::jsonb WHERE id=$1`,
        [r.last_task_id, JSON.stringify([evt])]);
    }
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: PASS — все тесты (requeue, handoff, banned-handoff существующий, kill-switch, race-guard).

- [ ] **Step 5: Commit**

```bash
git add retry_controller.js test_retry_controller.test.js
git commit -m "$(printf 'feat(wp138): retry_controller — событие handoff внутри транзакции перевода на ручную\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 5: Kill-switch `RETRY_VISIBILITY_ENABLED=false` — не пишет события/причину, но ретрай работает

**Files:**
- Test: `test_retry_controller.test.js`

- [ ] **Step 1: Добавить тест**

Вставить рядом с другими WP#138-тестами:
```js
test('RETRY_VISIBILITY_ENABLED=false → requeue работает, но без события и без last_retry_reason', async()=>{
  await seedFailed('adb_devices_unreachable','network');
  process.env.RETRY_VISIBILITY_ENABLED='false';
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00'), onlyClientPublishId: CPID });
  delete process.env.RETRY_VISIBILITY_ENABLED;
  const q = (await pool.query('SELECT status, last_retry_reason FROM publish_queue WHERE id=$1',[PQ])).rows[0];
  assert.equal(q.status, 'pending');               // поведение ретрая не изменилось
  assert.equal(q.last_retry_reason, null);          // причину не писали
  const ev = (await pool.query('SELECT events FROM publish_tasks WHERE id=$1',[PT])).rows[0].events || [];
  assert.equal(ev.find(e => e.type === 'retry'), undefined); // события нет
});
```

- [ ] **Step 2: Запустить — убедиться, что проходит сразу**

Логика kill-switch уже реализована в Task 3 (флаг `visibility`). Тест проверяет её.

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: PASS — все тесты, включая kill-switch видимости.

- [ ] **Step 3: Commit**

```bash
git add test_retry_controller.test.js
git commit -m "$(printf 'test(wp138): kill-switch RETRY_VISIBILITY_ENABLED — ретрай без записи лога\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 6: Проверка — список задач отдаёт `events` (бейджи задач строим из событий, не из join)

**Files:** — (проверка, без правок кода)

> **Почему не правим `PUBLISH_TASKS_SELECT`:** после `requeue` (Task 3) `publish_queue.publish_task_id` обнуляется, а `/api/publish/tasks` джойнит `LEFT JOIN publish_queue pq ON pq.publish_task_id = pt.id`. Для перезапущенной упавшей задачи этот join не сматчит → любые `pq.*`-поля (`last_retry_reason`/`skip_reason`) пришли бы `null`, и бейдж повтора в таблице задач НЕ отрисовался бы. Поэтому в таблице задач бейджи строим из `pt.events` (наша запись `type:'retry'/'handoff'` лежит именно там, на упавшей задаче) — Task 9.

- [ ] **Step 1: Подтвердить, что `events` есть в payload списка задач и не вырезается**

Run:
```bash
grep -n 'const PUBLISH_TASKS_SELECT = `pt.\*' server.js
grep -n "delete .*events\|\.events *=" server.js
```
Expected: `PUBLISH_TASKS_SELECT` начинается с `pt.*` (значит `events` jsonb включён); никакого стриппинга `events` нет. Вывод во второй команде — пусто.

(Кода менять не нужно — это гейт перед Task 9.)

---

## Task 7: `publish_planner.js` — флаги `had_retry` / `auto_handoff` на карточках

**Files:**
- Modify: `publish_planner.js` (`buildPlannerCards`)
- Test: `test_publish_planner.test.js`

- [ ] **Step 1: Добавить падающий тест**

В конец `test_publish_planner.test.js` добавить:
```js
test('WP138: had_retry=true когда у аккаунта ≥2 реальных попыток', () => {
  const intents = [intent('slot:7', 'a0', '2026-05-20',
    [{ date: '2026-05-20', status: 'failed', error_code: 'adb_push_timeout', via_manual: false },
     { date: '2026-05-21', status: 'done',   error_code: null,             via_manual: false }])];
  const cards = buildPlannerCards(intents, WIN);
  assert.ok(cards.length >= 1);
  assert.ok(cards.every(c => c.had_retry === true));
  assert.ok(cards.every(c => c.auto_handoff === false));
});

test('WP138: auto_handoff=true когда у intent есть manual_handoff_date', () => {
  const it = intent('slot:8', 'a0', '2026-05-20',
    [{ date: '2026-05-20', status: 'failed', error_code: 'account_banned', via_manual: false }]);
  it.manual_handoff_date = '2026-05-20';
  const cards = buildPlannerCards([it], WIN);
  assert.ok(cards.length >= 1);
  assert.ok(cards.every(c => c.auto_handoff === true));
});

test('WP138: без ретраев/handoff флаги false', () => {
  const intents = [intent('slot:9', 'a0', '2026-05-20',
    [{ date: '2026-05-20', status: 'done', error_code: null, via_manual: false }])];
  const cards = buildPlannerCards(intents, WIN);
  assert.ok(cards.every(c => c.had_retry === false && c.auto_handoff === false));
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit test_publish_planner.test.js`
Expected: FAIL — `c.had_retry`/`c.auto_handoff` === undefined.

- [ ] **Step 3: Вычислить флаги в `buildPlannerCards` и положить в карточку**

В `publish_planner.js`, внутри `for (const [chainId, group] of chains) {`, ПОСЛЕ строки `const D0 = group.map(g => g.scheduled_date).sort()[0];` добавить:
```js
    // WP #138: флаги цепочки для маркеров на карточке.
    const hadRetry = group.some(it =>
      (it.attempts || []).filter(a => a.error_code !== 'process_interrupted').length >= 2);
    const autoHandoff = group.some(it => !!it.manual_handoff_date);
```

В объект `cards.push({ ... })` (ветка full, с `chain_id: chainId, business_date: Dk, ...`) добавить два поля (например, после `closed_transfer_from: ...`):
```js
        had_retry: hadRetry,
        auto_handoff: autoHandoff,
```

- [ ] **Step 4: Проставить дефолты в двух других ветках (консистентная форма карточки)**

В ветке деградации (`else { ... cards.push({ ... mode: 'auto', carried_in_from: null, ... })`) добавить в объект:
```js
        had_retry: false, auto_handoff: false,
```
И в ветке плановых карточек (`for (const r of prows) { cards.push({ ... mode: 'auto', carried_in_from: null, ... }) }`) добавить:
```js
        had_retry: false, auto_handoff: false,
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `node --test --test-force-exit test_publish_planner.test.js`
Expected: PASS — все существующие сценарии + 3 новых WP138-теста.

- [ ] **Step 6: Commit**

```bash
git add publish_planner.js test_publish_planner.test.js
git commit -m "$(printf 'feat(wp138): planner cards — флаги had_retry/auto_handoff\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 8: Фронт — словарь подписей + бейджи в таблице очереди (`upqRenderRow`)

> Фронт `public/index.html` — статический браузерный файл, JS-тест-харнесса нет. Верификация — `node --check` невозможен для HTML; используем точечные правки + grep-подтверждение + визуальную проверку (Task 12). Файл большой и его правит WP #128 — перед каждой правкой `grep -n` якоря, правки держим аддитивными.

**Files:**
- Modify: `public/index.html`

- [ ] **Step 1: Добавить общие helper'ы подписей (один раз, рядом с `UPT_STATUS_BADGE`)**

Найти якорь: `grep -n "const UPT_STATUS_BADGE = {" public/index.html`. ПЕРЕД этой строкой вставить:
```js
// WP #138: короткие подписи правил ретрая/перевода на ручную + helper'ы бейджей.
const WP138_RETRY_RULE = { transient_within_limits: 'временный сбой (сеть/площадка)', fixed_at_reanimated: 'ошибку в системе устранили' };
const WP138_HANDOFF_RULE = { structural_error: 'серьёзная ошибка площадки', window_exhausted: 'не удалось за 2 дня' };
function wp138HandoffRule(skipReason) {
  if (!skipReason || skipReason.indexOf('retry_handoff:') !== 0) return null;
  return skipReason.slice('retry_handoff:'.length);
}
function wp138RetryBadge(row) {
  if (!row.last_retry_reason) return '';
  const n = row.attempt_count ? ` · попытка ${row.attempt_count}` : '';
  const tip = (WP138_RETRY_RULE[row.last_retry_reason] || row.last_retry_reason);
  return `<span title="Авто-перезапуск: ${tip}" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-sky-100 text-sky-700 border border-sky-200">🔁 Повтор после ошибки${n}</span>`;
}
function wp138HandoffBadge(status, skipReason) {
  const rule = (status === 'cancelled') ? wp138HandoffRule(skipReason) : null;
  if (!rule) return '';
  const tip = (WP138_HANDOFF_RULE[rule] || rule);
  return `<span title="Переведено на ручную: ${tip}" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-100 text-rose-700 border border-rose-200">❗→✋ Ошибка → ручная</span>`;
}
// Для таблицы задач: бейджи из событий самой задачи (pt.events), т.к. после requeue
// pq.publish_task_id обнулён и join pq↔pt для упавшей задачи не сматчит.
function wp138BadgesFromEvents(events) {
  const evs = Array.isArray(events) ? events : [];
  let out = '';
  const r = evs.find(e => e.type === 'retry');
  if (r) {
    const tip = WP138_RETRY_RULE[(r.meta||{}).rule] || (r.meta||{}).rule || '';
    out += `<span title="Авто-перезапуск: ${tip}" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-sky-100 text-sky-700 border border-sky-200">🔁 Повтор после ошибки</span>`;
  }
  const h = evs.find(e => e.type === 'handoff');
  if (h) {
    const tip = WP138_HANDOFF_RULE[(h.meta||{}).rule] || (h.meta||{}).rule || '';
    out += `<span title="Переведено на ручную: ${tip}" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-100 text-rose-700 border border-rose-200">❗→✋ Ошибка → ручная</span>`;
  }
  return out;
}
```

- [ ] **Step 2: Вставить бейджи в ячейку статуса очереди**

В функции `upqRenderRow` найти строку (якорь `grep -n "td class=\"px-3 py-2.5\">\${badge}\${skipNote}" public/index.html` — это строка в `upqRenderRow`):
```js
    <td class="px-3 py-2.5">${badge}${skipNote}</td>
```
Заменить на:
```js
    <td class="px-3 py-2.5">${badge}${wp138RetryBadge(row)}${wp138HandoffBadge(row.status, row.skip_reason)}${skipNote}</td>
```

- [ ] **Step 3: Подтвердить правки grep'ом**

Run:
```bash
grep -n "wp138RetryBadge\|wp138HandoffBadge\|WP138_RETRY_RULE" public/index.html
```
Expected: определения (Step 1) + вызов в `upqRenderRow` (Step 2).

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "$(printf 'feat(wp138): бейджи повтор/ошибка→ручная в таблице очереди\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 9: Фронт — бейджи в таблице задач из событий (`uptRenderRow`)

**Files:**
- Modify: `public/index.html`

> Хелпер `wp138BadgesFromEvents` уже добавлен в Task 8. Здесь только вызываем его. Сигнал — `pt.events` самой задачи (см. Task 6: join `pq↔pt` после requeue не сматчит, `pq.*` был бы null).

- [ ] **Step 1: Вставить бейджи в ячейку статуса задачи**

В `uptRenderRow` найти (якорь `grep -n "const badge = UPT_STATUS_BADGE\[row.status\]" public/index.html`):
```js
  const badge = UPT_STATUS_BADGE[row.status] || `<span class="text-xs text-gray-500">${row.status}</span>`;
```
Сразу ПОСЛЕ этой строки добавить:
```js
  const wp138Badges = wp138BadgesFromEvents(row.events);
```
Затем найти строку рендера ячейки статуса в возвращаемом `<tr>` (якорь `grep -n "<td class=\"px-3 py-2.5\">\${badge}</td>" public/index.html` — в `uptRenderRow`):
```js
    <td class="px-3 py-2.5">${badge}</td>
```
Заменить на:
```js
    <td class="px-3 py-2.5">${badge}${wp138Badges}</td>
```

- [ ] **Step 2: Подтвердить grep'ом**

Run: `grep -n "wp138Badges" public/index.html`
Expected: 2 совпадения (объявление + вставка в `<tr>`).

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "$(printf 'feat(wp138): бейджи повтор/ошибка→ручная в таблице задач\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 10: Фронт — маркеры на карточках планировщика (`plannerCardHtml`)

**Files:**
- Modify: `public/index.html`

- [ ] **Step 1: Добавить маркеры рядом с бейджем режима**

В `plannerCardHtml` найти блок (якорь `grep -n "const mode = c.mode === 'manual'" public/index.html`):
```js
  const mode = c.mode === 'manual'
    ? `<span class="inline-flex items-center gap-1 bg-violet-100 text-violet-700 px-2 py-0.5 rounded-lg text-[10px]">👋 вручную</span>`
    : `<span class="inline-flex items-center gap-1 bg-gray-100 text-gray-600 px-2 py-0.5 rounded-lg text-[10px]">🤖 авто</span>`;
```
Сразу ПОСЛЕ него добавить:
```js
  const wp138Marks = (c.auto_handoff
      ? `<span title="После ошибки переведено на ручную выкладку" class="inline-flex items-center gap-1 bg-rose-100 text-rose-700 px-2 py-0.5 rounded-lg text-[10px]">❗→✋ ошибка→ручная</span>` : '')
    + (c.had_retry
      ? `<span title="Был автоматический повтор после ошибки" class="inline-flex items-center gap-1 bg-sky-100 text-sky-700 px-2 py-0.5 rounded-lg text-[10px]">🔁 был повтор</span>` : '');
```
Затем найти строку рендера режима в возвращаемом шаблоне (якорь `grep -n "<div class=\"mt-1\">\${mode}</div>" public/index.html`):
```js
    <div class="mt-1">${mode}</div>
```
Заменить на:
```js
    <div class="mt-1 flex flex-wrap gap-1">${mode}${wp138Marks}</div>
```

- [ ] **Step 2: Подтвердить grep'ом**

Run: `grep -n "wp138Marks" public/index.html`
Expected: 2 совпадения.

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "$(printf 'feat(wp138): маркеры повтор/ошибка→ручная на карточках планировщика\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 11: Фронт — иконки событий retry/handoff в модалке лога

**Files:**
- Modify: `public/index.html`

- [ ] **Step 1: Добавить иконки и фон для новых типов событий**

Найти (якорь `grep -n "const typeIcon = { start:'🚀', info:'ℹ️', error:'❌', warning:'⚠️', day_done:'✅', success:'✅' };" public/index.html` — это в рендере модалки событий, рядом со строкой 11438):
```js
    const typeIcon = { start:'🚀', info:'ℹ️', error:'❌', warning:'⚠️', day_done:'✅', success:'✅' };
    const typeBg   = { start:'bg-indigo-50 border-indigo-200', info:'bg-gray-50 border-gray-100',
                       error:'bg-red-50 border-red-200', warning:'bg-yellow-50 border-yellow-200',
                       day_done:'bg-green-50 border-green-200', success:'bg-green-50 border-green-200' };
```
Заменить на:
```js
    const typeIcon = { start:'🚀', info:'ℹ️', error:'❌', warning:'⚠️', day_done:'✅', success:'✅', retry:'🔁', handoff:'🤚' };
    const typeBg   = { start:'bg-indigo-50 border-indigo-200', info:'bg-gray-50 border-gray-100',
                       error:'bg-red-50 border-red-200', warning:'bg-yellow-50 border-yellow-200',
                       day_done:'bg-green-50 border-green-200', success:'bg-green-50 border-green-200',
                       retry:'bg-sky-50 border-sky-200', handoff:'bg-rose-50 border-rose-200' };
```

- [ ] **Step 2: Подтвердить grep'ом**

Run: `grep -n "retry:'🔁', handoff:'🤚'" public/index.html`
Expected: 1 совпадение.

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "$(printf 'feat(wp138): иконки событий retry/handoff в модалке лога\n\nCo-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 12: Полный прогон тестов + визуальный smoke + подготовка к деплою

**Files:** —

- [ ] **Step 1: Прогнать все WP#138-тесты**

Run:
```bash
cd /home/claude-user/wt-wp138
node --test --test-force-exit test_retry_labels.test.js test_retry_controller.test.js test_publish_planner.test.js
```
Expected: PASS, 0 fail. (Если live-DB тесты конфликтуют с чужими zombie-процессами — см. memory `feedback_stale_node_test_processes`: `pkill -f test_retry_controller`.)

- [ ] **Step 2: Синтаксис server.js**

Run: `node --check server.js`
Expected: без вывода.

- [ ] **Step 3: Визуальный smoke на testbench-дашборде (seed → API → глаза)**

Засеять 3 показательные строки и убедиться, что эндпоинты отдают новые поля:
```bash
# retry-кейс: pending с last_retry_reason
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "SELECT id,status,last_retry_reason,skip_reason FROM publish_queue WHERE last_retry_reason IS NOT NULL OR skip_reason LIKE 'retry_handoff:%' LIMIT 5;"
```
Expected: видны строки с `last_retry_reason` (после реальных тиков контроллера) и/или `skip_reason='retry_handoff:...'`. Затем открыть дашборд autowarm (delivery.contenthunter.ru для прод / testbench-URL для теста), вкладки «Очередь» и «Опубликовано» — проверить бейджи; открыть 📋 на упавшей задаче — увидеть событие 🔁/🤚 человеческим текстом; на «Планировщике» — маркеры на карточке.

> Если в БД нет естественных кейсов — допускается ручной seed строки `publish_queue` (status='pending', last_retry_reason='transient_within_limits') и связанной `publish_tasks` с событием, затем удалить после проверки. Не коммитить тестовые данные.

- [ ] **Step 4: Финальная сверка с WP #128 (конфликт-зона `public/index.html`)**

Run:
```bash
git fetch origin
git log --oneline origin/main -5
git merge-base --is-ancestor origin/main HEAD && echo "up-to-date" || echo "REBASE NEEDED on origin/main before PR"
```
Если нужен rebase — `git rebase origin/main`, разрешить конфликты в `public/index.html` (наши правки аддитивны: helper'ы + вставки в 3 render-функции + iconmap), повторить Step 1–2.

- [ ] **Step 5: Открыть PR (НЕ мержить без согласования с Данилом и WP #128)**

```bash
gh pr create --repo GenGo2/delivery-contenthunter --base main --head wp138-autowarm-publish-logs \
  --title "WP #138 — логи и статусы автовыкладки (ретрай/ручная)" \
  --body "$(printf 'Observability поверх retry engine (WP #108): человекочитаемые события в лог задачи (модалка) + 2 бейджа (повтор после ошибки / ошибка→ручная) в очереди, задачах и на карточках планировщика.\n\n- Миграция: publish_queue.last_retry_reason/last_retried_at (аддитивно, nullable)\n- retry_controller: события retry/handoff атомарно с переходом статуса\n- Kill-switch: RETRY_VISIBILITY_ENABLED\n- Тесты: retry_labels (unit), retry_controller (live-DB), publish_planner (unit)\n\n⚠️ Пересекается с WP #128 по public/index.html — согласовать порядок merge.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)')"
```

**Деплой (после merge в main, выполняет с согласования):**
1. Применить миграцию на prod БД: `psql ... -f migrations/20260525_wp138_retry_visibility.sql` (аддитивно, безопасно).
2. `cd /root/.openclaw/workspace-genri/autowarm && git pull --ff-only origin main`.
3. `sudo -n pm2 restart autowarm`.
4. Откат фичи без отката кода: `RETRY_VISIBILITY_ENABLED=false` (новые причины/события перестают писаться; бейджи без данных не показываются).

---

## Self-Review (заполняется автором плана)

- **Покрытие спеки:** §4 правила→текст → Task 2 (`retry_labels`). §5.1 миграция → Task 1. §5.2 события+атомарность → Task 3 (requeue) + Task 4 (handoff) + Task 5 (kill-switch, вкл. условный `last_retried_at`). §5.3 список задач отдаёт `events` → Task 6 (верификация), planner-флаги → Task 7. §5.4 UI: очередь (из `pq.last_retry_reason`/`skip_reason`) → Task 8, задачи (из `pt.events`) → Task 9, карточки → Task 10, модалка → Task 11. §7 тесты → Tasks 2/3/4/5/7 + Task 12 прогон. §8 деплой/координация → Task 12.
- **P2/P3 codex (2026-05-25):** P2 — таблица задач строит бейджи из `pt.events` (join `pq↔pt` после requeue не сматчит) → Task 6/9 переписаны, правка `PUBLISH_TASKS_SELECT` убрана. P3 — `last_retried_at` под kill-switch (CASE WHEN visibility) → Task 3 Step 6.
- **Плейсхолдеры:** нет — весь код приведён целиком.
- **Согласованность имён:** `wp138RetryBadge`/`wp138HandoffBadge`/`wp138HandoffRule` — определены в Task 8, переиспользованы в Task 9. `requeueOne(pool,r,reason,visibility)` и `handoffToManual(pool,r,reason,visibility)` — сигнатуры согласованы (Task 3/4). Поля `last_retry_reason`/`pq_skip_reason`/`pq_manual_handoff_at` — заданы в миграции/Task 6, использованы во фронте. Флаги `had_retry`/`auto_handoff` — Task 7 → Task 10.
