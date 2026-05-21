# WP #108 — Движок ретраев для выкладок — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Авто-ретраить упавшие публикации с классификацией ошибок, бюджетом попыток (3/сутки/класс, окно 2 дня до 23:00 МСК) и передачей в ручную выкладку при исчерпании; не дублировать публикацию при ретрае.

**Architecture:** Подход 1 — крон-контроллер `retryFailedPublishes` поверх существующей `publish_queue`/`dispatchPublishQueue`. Состояние попыток читается из `publish_tasks` (каждая попытка = строка, отдельный леджер не нужен). Классификация — колонка `error_class` в `publish_error_codes` + `fixed_at`. Передача в ручную переиспользует сагу #85/#107/#115/#125 (`slot.manual_publish=true` → существующий гард `checkDispatchQueueSlotLineage` + наполнитель `assignManualPublishQueue`). Идемпотентность — хук в Python-publisher перед Share по `client_publish_id`.

**Tech Stack:** Node.js (`server.js`, `pg` Pool), Python (`publisher_base.py`, psycopg2), Postgres `openclaw`. Тесты: `node --test --test-force-exit` (live-DB фикстуры с высокими ID + cleanup) и `pytest` (с autouse `engine.dispose` фикстурой для live-DB — см. практику валидатора, для autowarm-Python используется psycopg2 напрямую).

**Спека:** `docs/superpowers/specs/2026-05-21-wp108-publish-retry-engine-design.md`

## Предусловия (проверить ДО старта)

- **#125 (`checkDispatchQueueSlotLineage`, `slotIsEffectivelyManual`) уже присутствует** в прод-чекауте `/root/.openclaw/workspace-genri/autowarm` (есть `test_dispatch_manual_guard.test.js`). Подтвердить `git log`/наличие функций перед стартом; гейт на мёрдж #125 фактически снят, но **сверить, что эти функции экспортированы из `server.js`**.
- Работать в актуальном чекауте после `git fetch` + сверки с origin/main (параллельные сессии).
- Прогон тестов — против live `openclaw` на сервере. Перед commit — зелёный прогон затронутых тестов.
- Номера строк в задачах **индикативные** (сняты разведкой 2026-05-21) — сверять с актуальным `server.js`/`publisher_base.py`.

---

## File Structure

**Создаём:**
- `migrations/20260521_wp108_retry_engine.sql` + `migrations/20260521_wp108_retry_engine__rollback.sql` — 3 ALTER, индексы, backfill `client_publish_id`, seed `error_class`.
- `retry_decision.js` — чистая функция `decideRetry(facts)` → действие (без БД, легко тестировать).
- `retry_controller.js` — `retryFailedPublishes(pool)`: читает упавшие строки, собирает факты, вызывает `decideRetry`, исполняет ре-queue/handoff.
- `test_retry_decision.test.js` — юнит-тесты чистой функции.
- `test_retry_controller.test.js` — live-DB тесты контроллера.
- `tests/test_error_class_resolution.py` — pytest классификатора.
- `tests/test_publish_idempotency.py` — pytest хука идемпотентности.
- `publish_idempotency.py` — helper хука идемпотентности (вызывается publisher перед Share).

**Модифицируем:**
- `publisher_base.py` (~2110–2193) — `_set_error_code_from_events`: дополнительно резолвить и писать `error_class`.
- `server.js` — `assignUnicResultsToQueue` (insert `client_publish_id`), force-enqueue endpoint (`POST /api/publish/queue/manual`, ~2268), `dispatchPublishQueue` (копировать `client_publish_id` в `publish_task`), регистрация `setInterval` для контроллера.
- publisher (Python, точка перед Share — найти грепом) — вызов `publish_idempotency.should_skip(...)`.
- Данные: `UPDATE unic_settings SET timezone='Europe/Moscow', publish_start='05:00:00' WHERE id=1`.

---

## Task 1: Миграция схемы

**Files:**
- Create: `migrations/20260521_wp108_retry_engine.sql`
- Create: `migrations/20260521_wp108_retry_engine__rollback.sql`

- [ ] **Step 1: Написать миграцию**

`migrations/20260521_wp108_retry_engine.sql`:
```sql
-- WP #108 движок ретраев. Идемпотентно (IF NOT EXISTS).
BEGIN;

-- publish_queue: стабильный ID намерения + отметка передачи в ручную
ALTER TABLE publish_queue
  ADD COLUMN IF NOT EXISTS client_publish_id uuid,
  ADD COLUMN IF NOT EXISTS manual_handoff_at timestamptz NULL;

-- DEFAULT на уровне БД: ЛЮБОЙ путь вставки (server.js, ручной SQL, будущий
-- endpoint, другой сервис) автоматически получает ID — нельзя молча «опт-аут»
-- из ретраев/идемпотентности (контроллер пропускает строки с NULL).
ALTER TABLE publish_queue ALTER COLUMN client_publish_id SET DEFAULT gen_random_uuid();

-- backfill существующих строк, затем NOT NULL (контракт «у каждой строки есть ID»).
UPDATE publish_queue SET client_publish_id = gen_random_uuid() WHERE client_publish_id IS NULL;
ALTER TABLE publish_queue ALTER COLUMN client_publish_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_publish_queue_client_publish_id
  ON publish_queue (client_publish_id);

-- publish_tasks: копия ID намерения + класс ошибки (леджер попыток)
ALTER TABLE publish_tasks
  ADD COLUMN IF NOT EXISTS client_publish_id uuid,
  ADD COLUMN IF NOT EXISTS error_class text NULL;

CREATE INDEX IF NOT EXISTS idx_publish_tasks_intent_class_created
  ON publish_tasks (client_publish_id, error_class, created_at);

-- publish_error_codes: таксономия + реестр фиксов
ALTER TABLE publish_error_codes
  ADD COLUMN IF NOT EXISTS error_class text NOT NULL DEFAULT 'unknown',
  ADD COLUMN IF NOT EXISTS fixed_at timestamptz NULL;

-- CHECK через DO (idempotent — не падать если уже есть)
DO $$ BEGIN
  ALTER TABLE publish_error_codes
    ADD CONSTRAINT publish_error_codes_error_class_chk
    CHECK (error_class IN ('network','ui_changed','banned','rate_limited','unknown'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMIT;
```

`migrations/20260521_wp108_retry_engine__rollback.sql`:
```sql
BEGIN;
ALTER TABLE publish_error_codes DROP CONSTRAINT IF EXISTS publish_error_codes_error_class_chk;
ALTER TABLE publish_error_codes DROP COLUMN IF EXISTS fixed_at, DROP COLUMN IF EXISTS error_class;
DROP INDEX IF EXISTS idx_publish_tasks_intent_class_created;
ALTER TABLE publish_tasks DROP COLUMN IF EXISTS error_class, DROP COLUMN IF EXISTS client_publish_id;
DROP INDEX IF EXISTS idx_publish_queue_client_publish_id;
ALTER TABLE publish_queue DROP COLUMN IF EXISTS manual_handoff_at, DROP COLUMN IF EXISTS client_publish_id;
COMMIT;
```

- [ ] **Step 2: Применить и проверить колонки**

Run:
```bash
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -f migrations/20260521_wp108_retry_engine.sql
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -c "\d publish_queue" | grep -E "client_publish_id|manual_handoff_at"
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -c "\d publish_error_codes" | grep -E "error_class|fixed_at"
```
Expected: обе колонки в каждой таблице присутствуют; `\d publish_tasks` показывает `client_publish_id`, `error_class`.

- [ ] **Step 3: Проверить откат и заново накатить**

Run:
```bash
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -f migrations/20260521_wp108_retry_engine__rollback.sql
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -c "\d publish_queue" | grep -c manual_handoff_at   # → 0
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -f migrations/20260521_wp108_retry_engine.sql       # накатить обратно
```
Expected: после rollback колонок нет (grep -c → 0), после повторного наката — есть.

- [ ] **Step 4: Commit**

```bash
git add migrations/20260521_wp108_retry_engine.sql migrations/20260521_wp108_retry_engine__rollback.sql
git commit -m "feat(wp108): миграция схемы движка ретраев (client_publish_id, error_class, fixed_at)"
```

---

## Task 2: Сид-маппинг error_class + backfill существующих данных

**Files:**
- Create: `migrations/20260521_wp108_error_class_seed.sql` (+ `__rollback.sql`)

- [ ] **Step 1: Снять фактические коды из прода**

Run:
```bash
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -c \
 "SELECT code, severity, retry_strategy FROM publish_error_codes ORDER BY code;"
```
Expected: список реальных кодов. На его основе заполнить маппинг ниже (классы для кодов, которых нет в примере, оставить дефолтом `unknown`).

- [ ] **Step 2: Написать seed**

`migrations/20260521_wp108_error_class_seed.sql` (скорректировать списки под реальные коды из Step 1):
```sql
BEGIN;
-- network: сетевые/устройство-недоступно/зависания
UPDATE publish_error_codes SET error_class='network'
  WHERE code IN ('adb_devices_unreachable','adb_push_timeout','watchdog_subprocess_hang',
                 'adb_push_chunked_failed','s3_upload_failed');
-- ui_changed: экран/элемент не найден, шаг автоматизации сломался
UPDATE publish_error_codes SET error_class='ui_changed'
  WHERE code LIKE '%target_not_in_picker%' OR code LIKE '%editor_not_reached%'
     OR code LIKE '%create_menu_not_reached%' OR code='caption_fill_failed'
     OR code LIKE '%switch_verify_failed%' OR code='switch_failed_unspecified';
-- banned: блокировки аккаунта
UPDATE publish_error_codes SET error_class='banned'
  WHERE code LIKE '%banned%' OR code LIKE '%account_block%'
     OR code IN ('phone_or_email_link_required');
-- rate_limited: лимиты площадки
UPDATE publish_error_codes SET error_class='rate_limited'
  WHERE code LIKE '%rate_limit%' OR code LIKE '%try_again_later%';
-- остальное остаётся 'unknown' (дефолт)

-- ── Backfill существующих данных (выполняется ПОСЛЕ сида error_class выше) ──
-- Иначе уже-упавшие на момент деплоя выкладки не подхватятся: контроллер джойнит
-- publish_tasks по client_publish_id и пропускает строки без error_class.
-- 1) связать существующие publish_tasks с client_publish_id их строки очереди
UPDATE publish_tasks pt
SET client_publish_id = pq.client_publish_id
FROM publish_queue pq
WHERE pq.publish_task_id = pt.id AND pt.client_publish_id IS NULL;
-- 2) проставить error_class существующим упавшим задачам из справочника по error_code
UPDATE publish_tasks pt
SET error_class = COALESCE(
      (SELECT ec.error_class FROM publish_error_codes ec WHERE ec.code = pt.error_code), 'unknown')
WHERE pt.error_class IS NULL AND pt.status IN ('failed','preflight_failed');
COMMIT;
```
> Best-effort: связывается текущая `publish_task` каждой строки очереди (`publish_queue.publish_task_id`). Исторические задачи прошлых ре-queue до деплоя остаются без линии — для счётчика попыток это допустимо (считаем вперёд от деплоя); цель backfill — чтобы уже-упавшие строки очереди не «зависли» вне движка.

`migrations/20260521_wp108_error_class_seed__rollback.sql`:
```sql
BEGIN;
UPDATE publish_error_codes SET error_class='unknown';
COMMIT;
```

- [ ] **Step 3: Применить и проверить распределение**

Run:
```bash
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -f migrations/20260521_wp108_error_class_seed.sql
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -c \
 "SELECT error_class, count(*) FROM publish_error_codes GROUP BY 1 ORDER BY 2 DESC;"
# backfill: существующие упавшие задачи получили линию и класс
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -c \
 "SELECT count(*) AS failed_tasks_without_class FROM publish_tasks WHERE status IN ('failed','preflight_failed') AND error_class IS NULL;"
```
Expected: коды распределены по классам; `unknown` только у неклассифицированных; `failed_tasks_without_class` → 0 (все упавшие задачи получили класс через backfill).

- [ ] **Step 4: Commit**

```bash
git add migrations/20260521_wp108_error_class_seed.sql migrations/20260521_wp108_error_class_seed__rollback.sql
git commit -m "feat(wp108): сид error_class для известных публикационных кодов"
```

---

## Task 3: Классификатор — писать error_class в publish_tasks

**Files:**
- Modify: `publisher_base.py` (`_set_error_code_from_events`, ~2160)
- Test: `tests/test_error_class_resolution.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_error_class_resolution.py`:
```python
import psycopg2
from publisher_base import DB_CONFIG, BasePublisher

# Использует фикстуру с высоким ID, чистит за собой.
TASK_ID = 99108001
CODE = 'wp108_test_ui_code'

def _conn():
    return psycopg2.connect(**DB_CONFIG)

def setup_function():
    c = _conn(); cur = c.cursor()
    cur.execute("DELETE FROM publish_tasks WHERE id=%s", (TASK_ID,))
    cur.execute("DELETE FROM publish_error_codes WHERE code=%s", (CODE,))
    cur.execute("INSERT INTO publish_error_codes (code, severity, retry_strategy, is_known, error_class) "
                "VALUES (%s,'warn','manual',true,'ui_changed')", (CODE,))
    cur.execute("INSERT INTO publish_tasks (id, platform, account, status, events) "
                "VALUES (%s,'instagram','acc','failed', %s::jsonb)",
                (TASK_ID, '[{"type":"error","meta":{"category":"%s"}}]' % CODE))
    c.commit(); c.close()

def teardown_function():
    c = _conn(); cur = c.cursor()
    cur.execute("DELETE FROM publish_tasks WHERE id=%s", (TASK_ID,))
    cur.execute("DELETE FROM publish_error_codes WHERE code=%s", (CODE,))
    c.commit(); c.close()

def test_error_class_written_alongside_error_code():
    pub = BasePublisher.__new__(BasePublisher)   # минимальный стаб без __init__
    pub.task_id = TASK_ID
    pub._tier_final_probe_fired = True            # отключить shadow-probe в тесте
    pub._set_error_code_from_events()
    c = _conn(); cur = c.cursor()
    cur.execute("SELECT error_code, error_class FROM publish_tasks WHERE id=%s", (TASK_ID,))
    code, klass = cur.fetchone(); c.close()
    assert code == CODE
    assert klass == 'ui_changed'
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /root/.openclaw/workspace-genri/autowarm && python -m pytest tests/test_error_class_resolution.py -v`
Expected: FAIL — `error_class` is None (классификатор ещё не пишет класс).

- [ ] **Step 3: Реализовать запись error_class**

В `publisher_base.py`, внутри `_set_error_code_from_events`, **после** успешного `UPDATE ... SET error_code=...` (после строки ~2164, до `conn.commit()`), добавить:
```python
            # WP #108: резолвим error_class из справочника и пишем в задачу.
            # Идемпотентно: только если ещё не проставлен.
            cur.execute(
                "UPDATE publish_tasks pt "
                "SET error_class = COALESCE("
                "      (SELECT ec.error_class FROM publish_error_codes ec WHERE ec.code = %s),"
                "      'unknown') "
                "WHERE pt.id = %s AND pt.error_class IS NULL",
                (error_code, self.task_id)
            )
```
(Запрос ставит `unknown`, если кода ещё нет в справочнике — `triage_classifier` зарегистрирует его позже.)

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_error_class_resolution.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add publisher_base.py tests/test_error_class_resolution.py
git commit -m "feat(wp108): классификатор пишет error_class в publish_tasks"
```

---

## Task 4: client_publish_id при создании очереди и при диспатче

**Files:**
- Modify: `server.js` — `assignUnicResultsToQueue` (INSERT в `publish_queue`, ~6160–6260), force-enqueue `POST /api/publish/queue/manual` (~2268–2420), `dispatchPublishQueue` (создание `publish_task`, ~6696–6725)
- Test: `test_client_publish_id.test.js`

- [ ] **Step 1: Написать падающий тест (live-DB)**

`test_client_publish_id.test.js` (по образцу `test_dispatch_manual_guard.test.js`):
```javascript
// Run: node --test --test-force-exit test_client_publish_id.test.js
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

const PQ = 99108010;
after(async () => {
  await pool.query('DELETE FROM publish_queue WHERE id=$1', [PQ]).catch(()=>{});
  await pool.end();
});

test('INSERT БЕЗ колонки client_publish_id → DB-дефолт всё равно проставляет ID', async () => {
  // Колонка НЕ перечислена в INSERT — проверяем, что DEFAULT gen_random_uuid() сработал.
  await pool.query(
    `INSERT INTO publish_queue (id, account_username, platform, media_url, scheduled_at, status)
     VALUES ($1,'acc','instagram','https://x/y.mp4', NOW(), 'pending')`, [PQ]);
  const { rows } = await pool.query('SELECT client_publish_id FROM publish_queue WHERE id=$1', [PQ]);
  assert.ok(rows[0].client_publish_id, 'client_publish_id должен быть проставлен DB-дефолтом');
});
```
(Тест фиксирует контракт «любая строка очереди имеет client_publish_id», обеспеченный DB-дефолтом из Task 1 — даже если какой-то путь вставки не перечислит колонку.)

- [ ] **Step 2: Запустить — убедиться, что проходит на default, затем найти INSERT-места**

Run: `node --test --test-force-exit test_client_publish_id.test.js`
Expected: PASS (тест фиксирует контракт). Затем найти все INSERT в `publish_queue`:
```bash
grep -n "INSERT INTO publish_queue" server.js
```
Expected: список мест (auto-path `assignUnicResultsToQueue`, force-enqueue endpoint). Каждое — кандидат на добавление `client_publish_id`.

- [ ] **Step 3: Скопировать client_publish_id в publish_task при диспатче (ОБЯЗАТЕЛЬНО)**

Колонку в `publish_queue` уже заполняет DB-дефолт (Task 1), поэтому добавлять `client_publish_id` в списки колонок `INSERT INTO publish_queue` **не обязательно** (можно для явности — со значением `gen_random_uuid()`, Postgres-side). **Обязательная** правка — копирование ID в `publish_task` при диспатче, иначе леджер попыток (`publish_tasks`) не свяжется с намерением.

В `dispatchPublishQueue`, при создании `publish_task` (~6696–6717), **скопировать** `client_publish_id` из строки очереди в задачу:
```javascript
// при SELECT pending-строк убедиться, что выбирается pq.client_publish_id;
// в INSERT INTO publish_tasks (...) добавить колонку client_publish_id
//   со значением из строки очереди (queueRow.client_publish_id).
```

- [ ] **Step 4: Тест диспатча копирует client_publish_id в publish_task**

Дополнить `test_client_publish_id.test.js`:
```javascript
test('dispatchPublishQueue копирует client_publish_id в publish_task', async () => {
  // Подготовить pending-строку с известным client_publish_id + минимальную линию unic_task/result,
  // вызвать экспортируемую часть диспатча (или dispatchPublishQueue целиком на тестовой строке),
  // проверить, что созданный publish_task несёт тот же client_publish_id.
  // Реализатор: сверить сигнатуру dispatchPublishQueue и при необходимости извлечь
  // создание publish_task в экспортируемый хелпер createPublishTaskFromQueueRow(client, queueRow).
});
```
Run: `node --test --test-force-exit test_client_publish_id.test.js`
Expected: PASS (после реализации Step 3 и при необходимости извлечения хелпера).

- [ ] **Step 5: Commit**

```bash
git add server.js test_client_publish_id.test.js
git commit -m "feat(wp108): client_publish_id на всех INSERT publish_queue + копирование в publish_task"
```

---

## Task 5: Чистая функция решения о ретрае

**Files:**
- Create: `retry_decision.js`
- Test: `test_retry_decision.test.js`

- [ ] **Step 1: Написать падающие тесты (без БД)**

`test_retry_decision.test.js`:
```javascript
// Run: node --test test_retry_decision.test.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { decideRetry } = require('./retry_decision');

// facts: { errorClass, attemptsTodayThisClass, daysSinceFirstAttempt, fixedAtAfterLastFail,
//          beforeCutoff, maxPerClassPerDay, windowDays }
const base = { maxPerClassPerDay: 3, windowDays: 2, beforeCutoff: true,
               fixedAtAfterLastFail: false, daysSinceFirstAttempt: 0 };

test('fixed_at новее падения → reanimate (даже ui_changed)', () => {
  assert.equal(decideRetry({ ...base, errorClass:'ui_changed', attemptsTodayThisClass:9,
                             daysSinceFirstAttempt:5, fixedAtAfterLastFail:true }).action, 'requeue');
});
test('banned → handoff', () => {
  assert.equal(decideRetry({ ...base, errorClass:'banned', attemptsTodayThisClass:0 }).action, 'handoff');
});
test('ui_changed → handoff', () => {
  assert.equal(decideRetry({ ...base, errorClass:'ui_changed', attemptsTodayThisClass:0 }).action, 'handoff');
});
test('network, попыток < 3, в окне, до отсечки → requeue', () => {
  assert.equal(decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:2 }).action, 'requeue');
});
test('network, дневной лимит = 3 → wait (завтра счётчик сбросится, окно ещё не вышло)', () => {
  assert.equal(decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:3 }).action, 'wait');
});
test('network, окно 2 дня исчерпано → handoff', () => {
  assert.equal(decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:0,
                             daysSinceFirstAttempt:2 }).action, 'handoff');
});
test('network, после отсечки 23:00 → wait (ни requeue, ни handoff)', () => {
  assert.equal(decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:0,
                             beforeCutoff:false }).action, 'wait');
});
test('после отсечки дневной лимит НЕ уводит в handoff → wait', () => {
  assert.equal(decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:3,
                             beforeCutoff:false }).action, 'wait');
});
test('unknown трактуется как временный → requeue', () => {
  assert.equal(decideRetry({ ...base, errorClass:'unknown', attemptsTodayThisClass:0 }).action, 'requeue');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test test_retry_decision.test.js`
Expected: FAIL — `Cannot find module './retry_decision'`.

- [ ] **Step 3: Реализовать decideRetry**

`retry_decision.js`:
```javascript
'use strict';
const TRANSIENT = new Set(['network', 'rate_limited', 'unknown']);
const STRUCTURAL = new Set(['banned', 'ui_changed']);

/**
 * Чистое решение по упавшей строке очереди. Без БД и без побочных эффектов.
 * @returns {{action:'requeue'|'handoff'|'wait', reason:string}}
 */
function decideRetry(f) {
  // 1) Структурные (banned/ui_changed) — сразу в ручную, в любое время (не тратим ретраи).
  //    Исключение: fixed_at реанимирует (баг починен) → не считаем структурной.
  if (STRUCTURAL.has(f.errorClass) && !f.fixedAtAfterLastFail)
    return { action: 'handoff', reason: 'structural_error' };
  // 2) Вне активного окна дня (после 23:00 МСК) — контроллер ничего не делает.
  //    Проверяем ДО ветвей, порождающих действия (requeue/handoff по лимитам).
  if (!f.beforeCutoff) return { action: 'wait', reason: 'after_cutoff' };
  // 3) Реанимация: баг починен после последнего падения — пробуем снова.
  if (f.fixedAtAfterLastFail) return { action: 'requeue', reason: 'fixed_at_reanimated' };
  // 4) Окно 2 календарных дня исчерпано — терминальный give-up в ручную.
  if (f.daysSinceFirstAttempt >= f.windowDays) return { action: 'handoff', reason: 'window_exhausted' };
  // 5) Дневной лимит по классу исчерпан — ЖДЁМ завтрашнего сброса счётчика (НЕ handoff:
  //    окно 2 дней ещё не вышло, завтра будут новые попытки).
  if (f.attemptsTodayThisClass >= f.maxPerClassPerDay) return { action: 'wait', reason: 'daily_limit_wait_tomorrow' };
  // 6) Временная ошибка в пределах лимитов — ретраим.
  if (TRANSIENT.has(f.errorClass)) return { action: 'requeue', reason: 'transient_within_limits' };
  // Неизвестный класс не из TRANSIENT/STRUCTURAL — консервативно ждём.
  return { action: 'wait', reason: 'unclassified' };
}

module.exports = { decideRetry, TRANSIENT, STRUCTURAL };
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test test_retry_decision.test.js`
Expected: PASS (все 8 тестов).

- [ ] **Step 5: Commit**

```bash
git add retry_decision.js test_retry_decision.test.js
git commit -m "feat(wp108): чистая функция decideRetry (requeue/handoff/wait)"
```

---

## Task 6: Контроллер — сбор фактов из БД + исполнение

**Files:**
- Create: `retry_controller.js`
- Test: `test_retry_controller.test.js`

- [ ] **Step 1: Написать падающий live-DB тест**

`test_retry_controller.test.js` (образец — `test_dispatch_manual_guard.test.js`; высокие ID, cleanup):
```javascript
// Run: node --test --test-force-exit test_retry_controller.test.js
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { Pool } = require('pg');
const { retryFailedPublishes } = require('./retry_controller');
const pool = new Pool({ host:'localhost', user:'openclaw', password:'openclaw123', database:'openclaw' });

const PID=991080, CONTENT=9910800, SLOT=9910800, TASK=9910800, RESULT=9910800;
const PQ=9910800, PT=9910800;
const CPID='aaaaaaaa-0000-0000-0000-000000099108';

async function cleanup(){
  await pool.query('DELETE FROM publish_tasks WHERE id=$1',[PT]).catch(()=>{});
  await pool.query('DELETE FROM publish_queue WHERE id=$1',[PQ]).catch(()=>{});
  await pool.query('DELETE FROM unic_results WHERE id=$1',[RESULT]).catch(()=>{});
  await pool.query('DELETE FROM unic_tasks WHERE id=$1',[TASK]).catch(()=>{});
  await pool.query('DELETE FROM validator_schedule_slots WHERE id=$1',[SLOT]).catch(()=>{});
  await pool.query('DELETE FROM validator_content WHERE id=$1',[CONTENT]).catch(()=>{});
  await pool.query('DELETE FROM validator_projects WHERE id=$1',[PID]).catch(()=>{});
}
async function seedFailed(errorCode, errorClass){
  await cleanup();
  await pool.query(`INSERT INTO validator_projects (id,project,api_name,active,manual_publish) VALUES ($1,'WP108','wp108',true,false)`,[PID]);
  await pool.query(`INSERT INTO validator_content (id,project_id,description,status,content_type,uploader_id) VALUES ($1,$2,'wp108','approved','video',1)`,[CONTENT,PID]);
  await pool.query(`INSERT INTO validator_schedule_slots (id,project_id,slot_date,slot_position,content_id,slot_type,status,manual_publish) VALUES ($1,$2,CURRENT_DATE,1,$3,'client','filled',false)`,[SLOT,PID,CONTENT]);
  await pool.query(`INSERT INTO unic_tasks (id,content_id,project_id,slot_date,current_status,meta) VALUES ($1,$2,$3,CURRENT_DATE,'done',jsonb_build_object('slot_id',$4::text))`,[TASK,CONTENT,PID,SLOT]);
  await pool.query(`INSERT INTO unic_results (id,task_id,scheme_id,output_url,status,created_at) VALUES ($1,$2,NULL,'https://x/y.mp4','done',now())`,[RESULT,TASK]);
  await pool.query(`INSERT INTO publish_queue (id,unic_result_id,unic_task_id,project_id,account_username,platform,device_serial,media_url,scheduled_at,status,client_publish_id)
                    VALUES ($1,$2,$3,$4,'acc','instagram','SER','https://x/y.mp4',NOW(),'failed',$5)`,[PQ,RESULT,TASK,PID,CPID]);
  await pool.query(`INSERT INTO publish_tasks (id,platform,account,status,error_code,error_class,client_publish_id,created_at)
                    VALUES ($1,'instagram','acc','failed',$2,$3,$4, now())`,[PT,errorCode,errorClass,CPID]);
}
before(async()=>{ delete process.env.RETRY_ENGINE_ENABLED; });
after(async()=>{ await cleanup(); await pool.end(); });

test('network с 1 попыткой → строка возвращается в pending (requeue)', async()=>{
  await seedFailed('adb_devices_unreachable','network');
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00') });
  const { rows } = await pool.query('SELECT status, publish_task_id FROM publish_queue WHERE id=$1',[PQ]);
  assert.equal(rows[0].status, 'pending');
  assert.equal(rows[0].publish_task_id, null);
});

test('banned → handoff: слот помечен manual_publish, очередь погашена, manual_handoff_at выставлен', async()=>{
  await seedFailed('account_banned','banned');
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00') });
  const q = (await pool.query('SELECT status, manual_handoff_at FROM publish_queue WHERE id=$1',[PQ])).rows[0];
  const s = (await pool.query('SELECT manual_publish FROM validator_schedule_slots WHERE id=$1',[SLOT])).rows[0];
  assert.ok(['cancelled','skipped'].includes(q.status));
  assert.ok(q.manual_handoff_at);
  assert.equal(s.manual_publish, true);
});

test('kill-switch RETRY_ENGINE_ENABLED=false → no-op', async()=>{
  await seedFailed('adb_devices_unreachable','network');
  process.env.RETRY_ENGINE_ENABLED='false';
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00') });
  delete process.env.RETRY_ENGINE_ENABLED;
  const { rows } = await pool.query('SELECT status FROM publish_queue WHERE id=$1',[PQ]);
  assert.equal(rows[0].status, 'failed');  // не тронули
});

test('строка уже не failed (running) → контроллер её не трогает (guard от гонок)', async()=>{
  await seedFailed('adb_devices_unreachable','network');
  await pool.query(`UPDATE publish_queue SET status='running' WHERE id=$1`, [PQ]);
  await retryFailedPublishes(pool, { nowMsk: new Date('2026-05-21T08:00:00+03:00') });
  const { rows } = await pool.query('SELECT status FROM publish_queue WHERE id=$1',[PQ]);
  assert.equal(rows[0].status, 'running');  // SELECT берёт только failed; running не сбрасывается в pending
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: FAIL — `Cannot find module './retry_controller'`.

- [ ] **Step 3: Реализовать контроллер**

`retry_controller.js`:
```javascript
'use strict';
const { decideRetry } = require('./retry_decision');

const num = (v, d) => { const n = parseInt(v, 10); return Number.isFinite(n) ? n : d; };

/**
 * Один тик контроллера ретраев. Идемпотентен. Все «календарные дни» — в Europe/Moscow.
 * @param {Pool} pool
 * @param {object} [opts] { nowMsk?: Date } — для тестов; в проде берётся now() в МСК на стороне БД.
 */
async function retryFailedPublishes(pool, opts = {}) {
  if (process.env.RETRY_ENGINE_ENABLED === 'false') return { skipped: 'kill_switch' };

  const maxPerClassPerDay = num(process.env.RETRY_MAX_PER_CLASS_PER_DAY, 3);
  const windowDays        = num(process.env.RETRY_WINDOW_DAYS, 2);
  const cutoffHourMsk     = num(process.env.RETRY_CUTOFF_HOUR_MSK, 23);
  const handoffEnabled    = process.env.RETRY_MANUAL_HANDOFF_ENABLED !== 'false';

  // Единый «эффективный момент» для ВСЕХ вычислений (час отсечки, попытки, окно).
  // В проде = NULL → SQL берёт now(); в тестах = opts.nowMsk (абсолютный instant).
  // Передаётся параметром в каждый запрос — никакого смешения с локальным now().
  const nowParam = opts.nowMsk ? opts.nowMsk.toISOString() : null;

  // Час МСК считаем тем же эффективным моментом (никакого JS getUTCHours-хака).
  const nowMskHour = (await pool.query(
    `SELECT extract(hour from (COALESCE($1::timestamptz, now()) AT TIME ZONE 'Europe/Moscow'))::int AS h`,
    [nowParam])).rows[0].h;
  const beforeCutoff = nowMskHour < cutoffHourMsk;

  // Берём упавшие строки очереди без handoff. error_class/last_fail — из последней publish_task намерения.
  const { rows } = await pool.query(`
    SELECT pq.id AS pq_id, pq.client_publish_id, pq.unic_task_id,
           lt.error_code, lt.error_class, lt.last_failed_at,
           (pq.client_publish_id IS NULL) AS no_intent
    FROM publish_queue pq
    LEFT JOIN LATERAL (
       SELECT pt.error_code, pt.error_class, pt.updated_at AS last_failed_at
       FROM publish_tasks pt
       WHERE pt.client_publish_id = pq.client_publish_id
         AND pt.status IN ('failed','preflight_failed')
         AND COALESCE(pt.error_code,'') <> 'process_interrupted'
       ORDER BY pt.updated_at DESC LIMIT 1
    ) lt ON true
    WHERE pq.status = 'failed' AND pq.manual_handoff_at IS NULL
    LIMIT 200
  `);

  for (const r of rows) {
    if (r.no_intent || !r.error_class) continue;            // легаси-строка без линии — пропускаем

    // attempts сегодня по этому классу (МСК-дата эффективного момента $3)
    const a = await pool.query(`
      SELECT count(*)::int AS n FROM publish_tasks
      WHERE client_publish_id=$1 AND error_class=$2
        AND (created_at AT TIME ZONE 'Europe/Moscow')::date
            = (COALESCE($3::timestamptz, now()) AT TIME ZONE 'Europe/Moscow')::date
        AND status IN ('failed','preflight_failed') AND COALESCE(error_code,'') <> 'process_interrupted'
    `, [r.client_publish_id, r.error_class, nowParam]);

    // дни от первой попытки (МСК-даты, та же база отсчёта $2)
    const d = await pool.query(`
      SELECT ((COALESCE($2::timestamptz, now()) AT TIME ZONE 'Europe/Moscow')::date
              - (min(created_at) AT TIME ZONE 'Europe/Moscow')::date)::int AS days
      FROM publish_tasks WHERE client_publish_id=$1
    `, [r.client_publish_id, nowParam]);

    // fixed_at новее последнего падения?
    const fx = await pool.query(`
      SELECT (ec.fixed_at IS NOT NULL AND ec.fixed_at > $2) AS reanimate
      FROM publish_error_codes ec WHERE ec.code = $1
    `, [r.error_code, r.last_failed_at]);

    const decision = decideRetry({
      errorClass: r.error_class,
      attemptsTodayThisClass: a.rows[0].n,
      daysSinceFirstAttempt: d.rows[0].days,
      fixedAtAfterLastFail: !!(fx.rows[0] && fx.rows[0].reanimate),
      beforeCutoff, maxPerClassPerDay, windowDays,
    });

    if (decision.action === 'requeue') {
      // Guard от гонок: апдейтим ТОЛЬКО если строка всё ещё failed без handoff.
      // Иначе пересекающийся тик/диспатч мог увести строку в running → не сбрасываем.
      const upd = await pool.query(
        `UPDATE publish_queue SET status='pending', publish_task_id=NULL, updated_at=NOW()
         WHERE id=$1 AND status='failed' AND manual_handoff_at IS NULL`,
        [r.pq_id]);
      if (upd.rowCount === 1)
        console.log(`[retry-controller] requeue pq#${r.pq_id} (${r.error_class}, ${decision.reason})`);
      else
        console.log(`[retry-controller] skip requeue pq#${r.pq_id} — строка изменилась под нами`);
    } else if (decision.action === 'handoff' && handoffEnabled) {
      await handoffToManual(pool, r, decision.reason);
    } // 'wait' / handoff-disabled — ничего не делаем в этот тик
  }
  return { processed: rows.length };
}

/** Передать намерение в ручную выкладку: пометить слот manual, погасить очередь, проставить handoff. */
async function handoffToManual(pool, r, reason) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    // Guard от гонок: захватываем строку и подтверждаем, что она ВСЁ ЕЩЁ failed без handoff.
    // FOR UPDATE сериализует с пересекающимися тиками; rowCount=0 → строку уже изменили
    // (диспатч/соседний тик) → откатываемся и НЕ помечаем слот manual.
    const guard = await client.query(
      `SELECT id FROM publish_queue
       WHERE id=$1 AND status='failed' AND manual_handoff_at IS NULL
       FOR UPDATE`, [r.pq_id]);
    if (guard.rowCount === 0) {
      await client.query('ROLLBACK');
      console.log(`[retry-controller] skip handoff pq#${r.pq_id} — строка изменилась под нами`);
      return;
    }
    // слот из линии unic_task.meta.slot_id
    const slot = await client.query(
      `SELECT (ut.meta->>'slot_id')::int AS slot_id FROM unic_tasks ut WHERE ut.id=$1`, [r.unic_task_id]);
    const slotId = slot.rows[0] && slot.rows[0].slot_id;
    if (slotId) {
      await client.query(
        `UPDATE validator_schedule_slots
         SET manual_publish=true, manual_publish_set_at=now()
         WHERE id=$1 AND manual_publish=false`, [slotId]);
    }
    await client.query(
      `UPDATE publish_queue SET status='cancelled', skip_reason=$2, manual_handoff_at=now(), updated_at=NOW() WHERE id=$1`,
      [r.pq_id, `retry_handoff:${reason}`]);
    await client.query('COMMIT');
    console.log(`[retry-controller] handoff pq#${r.pq_id} slot#${slotId} (${reason})`);
  } catch (e) {
    await client.query('ROLLBACK');
    console.error(`[retry-controller] handoff error pq#${r.pq_id}: ${e.message}`);
  } finally { client.release(); }
}

module.exports = { retryFailedPublishes, handoffToManual };
```
> Примечание реализатору: если у `validator_schedule_slots` колонка аудита называется иначе (`manual_publish_set_by_id` ожидает FK на пользователя — для системного актора оставить NULL и помечать причину в `skip_reason`/логе), сверить с миграцией #85/#115. Если требуется системный актор-маркер — уточнить, есть ли «system»-пользователь, иначе достаточно `set_at` + лог.

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: PASS (3 теста: requeue, handoff, kill-switch).

- [ ] **Step 5: Commit**

```bash
git add retry_controller.js test_retry_controller.test.js
git commit -m "feat(wp108): крон-контроллер retryFailedPublishes (requeue + handoff в ручную)"
```

---

## Task 7: Регистрация крона + интеграция в server.js

**Files:**
- Modify: `server.js` (рядом с регистрацией `setInterval(dispatchPublishQueue, ...)`, ~6859)

- [ ] **Step 1: Подключить контроллер и зарегистрировать интервал**

В `server.js`, рядом с другими `require` контроллеров очереди:
```javascript
const { retryFailedPublishes } = require('./retry_controller');
```
Рядом с регистрацией интервала диспатча (~6859) добавить:
```javascript
// WP #108: контроллер ретраев. Каденс RETRY_INTERVAL_MINUTES (3–5 мин).
// Внутри сам уважает RETRY_ENGINE_ENABLED и отсечку 23:00 МСК.
const RETRY_INTERVAL_MS = (parseInt(process.env.RETRY_INTERVAL_MINUTES,10) || 5) * 60 * 1000;
setInterval(() => {
  retryFailedPublishes(pool).catch(e => console.error('[retry-controller] tick error:', e.message));
}, RETRY_INTERVAL_MS);
```

- [ ] **Step 2: Smoke — сервер стартует, тик не падает**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm
node -e "require('./retry_controller'); console.log('require ok')"
node --check server.js && echo "syntax ok"
```
Expected: `require ok` и `syntax ok`. (Полный старт сервера не делаем в тесте — он поднимает HTTP и интервалы; синтаксис + резолв модуля достаточно.)

- [ ] **Step 3: Commit**

```bash
git add server.js
git commit -m "feat(wp108): регистрация крона retryFailedPublishes в server.js"
```

---

## Task 8: Хук идемпотентности перед Share (publisher)

**Files:**
- Create: `publish_idempotency.py`
- Modify: publisher (точка перед нажатием Share — найти грепом)
- Test: `tests/test_publish_idempotency.py`

- [ ] **Step 1: Написать падающий тест**

`tests/test_publish_idempotency.py`:
```python
import psycopg2
from publisher_base import DB_CONFIG
from publish_idempotency import already_published

CPID = '00000000-0000-0000-0000-000000099108'
def _conn(): return psycopg2.connect(**DB_CONFIG)

def teardown_function():
    c=_conn(); cur=c.cursor()
    cur.execute("DELETE FROM publish_tasks WHERE client_publish_id=%s", (CPID,))
    c.commit(); c.close()

def _insert(status, post_url):
    c=_conn(); cur=c.cursor()
    cur.execute("INSERT INTO publish_tasks (platform,account,status,post_url,client_publish_id) "
                "VALUES ('instagram','acc',%s,%s,%s)", (status, post_url, CPID))
    c.commit(); c.close()

def test_terminal_published_with_url_skips():
    _insert('done', 'https://instagram.com/p/abc')
    assert already_published(CPID) is True

def test_published_no_url_treated_as_published_skips():
    _insert('published_no_url', None)
    assert already_published(CPID) is True   # консервативно: вероятно опубликовано (#86)

def test_only_failed_does_not_skip():
    _insert('failed', None)
    assert already_published(CPID) is False
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_publish_idempotency.py -v`
Expected: FAIL — `No module named 'publish_idempotency'`.

- [ ] **Step 3: Реализовать helper**

`publish_idempotency.py`:
```python
"""WP #108 — идемпотентность публикации по client_publish_id.

v1: внутренний трекинг. Если по этому намерению уже есть терминально-
опубликованная задача (с пойманным post_url) ИЛИ published_no_url
(вероятно опубликовано, #86) — считаем, что публиковать не нужно.

Скрейп последних N постов аккаунта для подтверждения неоднозначных случаев —
документированный follow-up (см. спеку §16 п.2); в v1 не вызывается.
"""
import os
import psycopg2
from publisher_base import DB_CONFIG

def already_published(client_publish_id) -> bool:
    if os.environ.get('IDEMPOTENCY_CHECK_ENABLED') == 'false':
        return False
    if not client_publish_id:
        return False
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM publish_tasks "
            "WHERE client_publish_id=%s AND ("
            "  (status IN ('done','published') AND post_url IS NOT NULL)"
            "  OR status='published_no_url'"
            ") LIMIT 1",
            (str(client_publish_id),)
        )
        return cur.fetchone() is not None
    finally:
        conn.close()
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_publish_idempotency.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Встроить вызов перед Share**

Найти точку публикации (нажатие Share/«Поделиться»):
```bash
grep -rn "Share\|Поделиться\|def publish\|tap_share\|do_publish" publisher.py publisher_base.py | head
```
В начале публикующего метода, **до** нажатия Share, добавить ранний выход (где доступен `client_publish_id` задачи — прокинуть его в publisher из строки очереди/задачи; если ещё не прокинут — добавить чтение `publish_tasks.client_publish_id` по `self.task_id`):
```python
from publish_idempotency import already_published
# ... в начале публикации:
cpid = getattr(self, 'client_publish_id', None)
if cpid and already_published(cpid):
    self.log_event('info', 'idempotency_skip',
                   meta={'category': 'idempotency_skip', 'client_publish_id': str(cpid)})
    self.update_status('done')   # уже выложено в прошлом ретрае — не дублируем
    return
```
> Реализатор: сверить имя публикующего метода и как задача узнаёт `client_publish_id` (прокинуть из `dispatchPublishQueue` через аргументы publisher или прочитать из `publish_tasks` по `self.task_id`). Терминальный статус при skip согласовать с тем, как `syncQueueStatuses` трактует `done`.

- [ ] **Step 6: Регресс-прогон publisher-тестов**

Run: `python -m pytest tests/test_publish_idempotency.py tests/test_account_switcher.py -v`
Expected: PASS (новый хук не ломает существующее; при необходимости — узкий smoke публикующего метода).

- [ ] **Step 7: Commit**

```bash
git add publish_idempotency.py tests/test_publish_idempotency.py publisher.py publisher_base.py
git commit -m "feat(wp108): хук идемпотентности перед Share по client_publish_id"
```

---

## Task 9: Переход расписания на МСК (пункт 6)

**Files:**
- Данные: `unic_settings` (UPDATE)
- Verify: `unic_sweep.js` (`computeBusinessDate`), `server.js` (`tzOffsets`)

- [ ] **Step 1: Проверить поддержку Europe/Moscow в коде**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm
grep -n "Europe/Moscow" server.js unic_sweep.js
node -e "const {computeBusinessDate}=require('./unic_sweep'); console.log('MSK today:', computeBusinessDate('Europe/Moscow'));"
```
Expected: `tzOffsets` содержит `'Europe/Moscow': 3` (есть); `computeBusinessDate('Europe/Moscow')` возвращает корректную дату. Подтвердить, что `slot_date` — это PG `DATE` (календарная дата, не сместится): `psql ... -c "\d validator_schedule_slots" | grep slot_date` → тип `date`.

- [ ] **Step 2: Сменить настройки (после подтверждения Step 1)**

Run:
```bash
psql "postgresql://openclaw:openclaw123@localhost:5432/openclaw" -c \
 "UPDATE unic_settings SET timezone='Europe/Moscow', publish_start='05:00:00' WHERE id=1 RETURNING timezone, publish_start;"
```
Expected: `Europe/Moscow | 05:00:00`.

- [ ] **Step 3: Проверить вычисление времени старта**

Run:
```bash
node -e "process.env.TZ='UTC'; const {computeBusinessDate}=require('./unic_sweep'); console.log(computeBusinessDate('Europe/Moscow'));"
```
Expected: дата соответствует МСК-дню. (Поведение `triggerAutoUnic` со старта 05:00 МСК проверяется на проде первым утренним прогоном — занести в smoke §деплой.)

- [ ] **Step 4: Commit (документируем смену настройки — кода нет)**

Смена `unic_settings` — это данные, не код. Зафиксировать факт в evidence:
```bash
echo "2026-05-21 WP#108: unic_settings.timezone=Europe/Moscow, publish_start=05:00:00 (старт партии 05:00 МСК)" >> docs/evidence/2026-05-21-wp108-msk-switch.md   # в docs-репо
```
> Примечание: правка `unic_settings` выполняется на деплое (см. §Деплой), не коммитом кода. Если в проекте есть seed/migration для `unic_settings` — добавить туда.

---

## Task 10: Параллелизм (пункт 7) — конфиг, без кода

**Files:** нет (env-настройка)

- [ ] **Step 1: Зафиксировать политику тюнинга**

`MAX_CONCURRENT_PUBLISHES_PER_RASPBERRY` остаётся env-настройкой, дефолт **3**. Поднимать постепенно (Рома допускает до 8) с мониторингом fail-rate (раньше снижали до 3 из-за роста ошибок). На телефон — 1 (неизменно). Кода в этой задаче не пишется.

- [ ] **Step 2: Документировать в runbook деплоя** (см. §Деплой). Изменений в репозитории нет — задача-плейсхолдер для явного решения «не трогаем число на старте».

---

## Деплой

Порядок (с одобрения Данила; прод-чекаут `/root/.openclaw/workspace-genri/autowarm`; **без force-push**):

1. **Cross-repo grep** (общая БД `openclaw`): `client_publish_id`, `error_class`, `manual_handoff_at` — по валидатору и delivery; убедиться, что нет коллизий имён/схемы (см. практику schema-changes — аудитить каждый hit).
2. **Миграции:** `20260521_wp108_retry_engine.sql` → `20260521_wp108_error_class_seed.sql`.
3. **Настройки:** `UPDATE unic_settings ... Europe/Moscow / 05:00:00` (Task 9 Step 2) — после подтверждения, что `slot_date` это `DATE` и tzOffsets знает Москву.
4. **Код:** `git pull` в прод-чекаут → проверить `pm2 describe autowarm | grep "exec cwd"` (drift!) → `pm2 restart autowarm`. Publisher запускается per-task (spawn) — подхватит обновлённый Python без отдельного рестарта; подтвердить.
5. **Env-флаги:** по умолчанию всё включено (`RETRY_ENGINE_ENABLED`, `RETRY_MANUAL_HANDOFF_ENABLED`, `IDEMPOTENCY_CHECK_ENABLED` — не задавать = true). При проблеме — `RETRY_ENGINE_ENABLED=false` + restart.
6. **Smoke (первый день):**
   - лог `[retry-controller]`: упавшие строки получают `requeue`/`handoff`, нет циклов;
   - нет ложных handoff (слоты, помеченные `manual_publish` контроллером, действительно исчерпали лимиты);
   - утренний прогон партии в 05:00 МСК состоялся;
   - идемпотентность: нет дублей в реальных аккаунтах после ре-queue.

## Self-Review заметки (для исполнителя)

- Открытый вопрос §16.1 спеки (хранение времён) **закрыт**: `slot_date` — PG `DATE`, сдвига нет; МСК-переход безопасен (Task 9 Step 1 подтверждает).
- Открытый вопрос §16.2 (скрейп) — вынесен в follow-up; v1 идемпотентности консервативен (Task 8).
- Открытый вопрос §16.3 (точки INSERT client_publish_id) — Task 4 Step 2 перечисляет грепом.
- Открытый вопрос §16.4 (сид error_class) — Task 2 снимает фактические коды из прода.
- Системный актор для handoff (`manual_publish_set_by_id` NULL + причина в `skip_reason`/логе) — помечено в Task 6 Step 3 как сверку с миграцией #85/#115.
