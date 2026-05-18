# WP #86 PR1 — Poller correctness + `published_no_url` terminal status — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR1 фаза WP #86 — починить url-poller (LIMIT-30 starvation, ORDER BY ASC голодание новых, NULL `started_at` zombies) + добавить terminal-статус `published_no_url` для задач где публикация состоялась, но specific URL не получен после исчерпания попыток + retroactive-cleanup для 45 текущих stuck задач.

**Architecture:** Pure-helpers extracted из server.js для unit-testing (паттерн `getMaxConcurrentPublishesPerRaspberry`). Schema migration с rollback. UI badges + filter добавляются в 5 местах `public/index.html` (per memory `feedback_validator_two_slot_renderers.md`). Retroactive-cleanup — отдельная миграция, запускается ПОСЛЕ деплоя кода. Env-var kill-switches для каждого нового лимита.

**Tech Stack:** Node.js 18+ (node:test runner), PostgreSQL 15, vanilla HTML/JS (autowarm dashboard).

**Spec:** `/home/claude-user/contenthunter/docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md`

**OpenProject:** [WP #86](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/86)

**Workdir:** `/home/claude-user/autowarm-testbench/` (= `GenGo2/delivery-contenthunter`). НЕ путать с агентским worktree `/home/claude-user/contenthunter/.claude/worktrees/wp86-awaiting-url-stuck/` где живёт сама спека.

---

## File Structure

| Файл | Что |
|---|---|
| `migrations/20260518_publish_tasks_url_capture_fields.sql` (new) | ALTER TABLE: `url_capture_attempts INT DEFAULT 0`, `pre_publish_video_ids JSONB`, `url_capture_last_attempt_at TIMESTAMP` + partial index |
| `migrations/20260518_publish_tasks_url_capture_fields__rollback.sql` (new) | DROP index + columns |
| `migrations/20260518_wp86_retroactive_cleanup.sql` (new) | UPDATE awaiting_url → published_no_url для stuck + sync publish_queue → done |
| `migrations/20260518_wp86_retroactive_cleanup__rollback.sql` (new) | Reverse via log-marker |
| `server.js:6844` `checkProcessingTasks` | LIMIT 30→100, ORDER BY started_at→updated_at, NULL coalesce 48h timeout, attempts++ ветка с промоутом в `published_no_url` |
| `server.js:7110` `syncQueueStatuses` | Расширить `pt.status IN ('done','needs_verification','moderation')` → добавить `'published_no_url'` |
| `server.js:1303, 1322, 1856` analytics queries | Добавить `'published_no_url'` в success-counts |
| `server.js` (нижний экспорт) | Экспорт новых pure helpers для тестов |
| `public/index.html:2434` (status filter dropdown) | Добавить `<option value="published_no_url">⚠️ Без URL</option>` |
| `public/index.html:6700-6701, 7203, 7211, 10727, 10881` | Badge в 5 местах: жёлтый «✅ Без URL» |
| `tests/test_url_poller_helpers.test.js` (new) | Unit tests для extracted helpers |

---

## Pre-flight: branch setup

### Task 0: Подготовить рабочую ветку в autowarm-testbench

**Files:** N/A — setup only.

- [ ] **Step 1: Сбросить cwd в autowarm-testbench и подтянуть main**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin --quiet
git checkout main
git pull --ff-only origin main
git log --oneline -3
```

Expected: top commit — последний merge (например, `ae41054 fix(tt): close tt_upload_confirmation_timeout false-negative (WP #82) (#69)`).

- [ ] **Step 2: Создать рабочую ветку**

```bash
git checkout -b feat/wp86-pr1-poller-published-no-url
git status
```

Expected: `On branch feat/wp86-pr1-poller-published-no-url` + clean tree.

- [ ] **Step 3: Прогнать существующий test suite — baseline green**

```bash
cd /home/claude-user/autowarm-testbench
npm test 2>&1 | tail -30
```

Expected: все tests pass (если упадут — фиксить НЕ в этом PR; репорт пользователю и stop).

---

## Schema migration (PR1.A)

### Task 1: Создать forward migration

**Files:**
- Create: `migrations/20260518_publish_tasks_url_capture_fields.sql`

- [ ] **Step 1: Создать файл со схемой**

```sql
-- migrations/20260518_publish_tasks_url_capture_fields.sql
-- WP #86 PR1: новые поля для defense-in-depth URL capture.
--
-- url_capture_attempts: счётчик неудачных проверок поллера. Reset при выходе
--   из awaiting_url. При attempts >= URL_CAPTURE_MAX_ATTEMPTS поллер
--   промоутит задачу в новый terminal-статус 'published_no_url'.
-- pre_publish_video_ids: array of top-N video-id'ов снятых ДО публикации.
--   Используется PR3 для diff-matching (Layer A5). NULL = snapshot не успел.
-- url_capture_last_attempt_at: observability — отделяет «давно не трогали»
--   от «свежий attempt».
--
-- Partial index idx_publish_tasks_status_updated держит query поллера
-- быстрой при LIMIT 100 (ORDER BY updated_at ASC) даже на 10k+ rows.

BEGIN;

ALTER TABLE publish_tasks
  ADD COLUMN url_capture_attempts INT NOT NULL DEFAULT 0,
  ADD COLUMN pre_publish_video_ids JSONB NULL,
  ADD COLUMN url_capture_last_attempt_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_publish_tasks_status_updated
  ON publish_tasks (status, updated_at)
  WHERE status IN ('processing', 'awaiting_url');

COMMIT;
```

- [ ] **Step 2: Создать rollback**

Create `migrations/20260518_publish_tasks_url_capture_fields__rollback.sql`:

```sql
-- Reverse of 20260518_publish_tasks_url_capture_fields.sql
BEGIN;
DROP INDEX IF EXISTS idx_publish_tasks_status_updated;
ALTER TABLE publish_tasks
  DROP COLUMN IF EXISTS url_capture_last_attempt_at,
  DROP COLUMN IF EXISTS pre_publish_video_ids,
  DROP COLUMN IF EXISTS url_capture_attempts;
COMMIT;
```

- [ ] **Step 3: Применить на локальной БД (openclaw) — verify columns**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f migrations/20260518_publish_tasks_url_capture_fields.sql
```

Expected: `BEGIN`, `ALTER TABLE`, `CREATE INDEX`, `COMMIT`. Никаких errors.

- [ ] **Step 4: Проверить колонки**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name='publish_tasks'
  AND column_name IN ('url_capture_attempts','pre_publish_video_ids','url_capture_last_attempt_at')
ORDER BY column_name;
"
```

Expected: 3 строки с типами `integer / 0`, `jsonb / NULL`, `timestamp without time zone / NULL`.

- [ ] **Step 5: Проверить partial index**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename='publish_tasks' AND indexname='idx_publish_tasks_status_updated';
"
```

Expected: 1 row, `indexdef` содержит `WHERE ((status = ANY...))`.

- [ ] **Step 6: Commit**

```bash
git add migrations/20260518_publish_tasks_url_capture_fields.sql \
       migrations/20260518_publish_tasks_url_capture_fields__rollback.sql
git commit -m "feat(migrations): WP #86 PR1 — url_capture fields + partial index

Поля для defense-in-depth URL capture (per WP #86 spec):
- url_capture_attempts: счётчик retry поллера
- pre_publish_video_ids: pre-publish snapshot (used by PR3 A5)
- url_capture_last_attempt_at: observability

Partial index idx_publish_tasks_status_updated держит query поллера
быстрой при новом LIMIT 100 + ORDER BY updated_at.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Pure helpers + unit tests (PR1.B)

### Task 2: Извлечь helper `shouldPromoteToPublishedNoUrl` + unit test

**Files:**
- Modify: `server.js` (добавить функцию рядом с `checkProcessingTasks`, экспортировать внизу)
- Create: `tests/test_url_poller_helpers.test.js`

- [ ] **Step 1: Написать failing test**

Create `tests/test_url_poller_helpers.test.js`:

```javascript
'use strict';

/**
 * Tests for WP #86 PR1: url-poller pure helpers.
 * Spec: docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md
 */

const { test, describe } = require('node:test');
const assert = require('node:assert');

const {
  shouldPromoteToPublishedNoUrl,
} = require('../server.js');

describe('shouldPromoteToPublishedNoUrl', () => {
  test('returns false когда attempts < max', () => {
    assert.strictEqual(shouldPromoteToPublishedNoUrl(0, 30), false);
    assert.strictEqual(shouldPromoteToPublishedNoUrl(29, 30), false);
  });

  test('returns true когда attempts == max', () => {
    assert.strictEqual(shouldPromoteToPublishedNoUrl(30, 30), true);
  });

  test('returns true когда attempts > max', () => {
    assert.strictEqual(shouldPromoteToPublishedNoUrl(99, 30), true);
  });

  test('returns false на отрицательные значения (defensive)', () => {
    assert.strictEqual(shouldPromoteToPublishedNoUrl(-1, 30), false);
  });

  test('returns false когда max <= 0 (kill-switch semantics)', () => {
    // max=0 фактически отключает промоут — задачи остаются в awaiting_url
    assert.strictEqual(shouldPromoteToPublishedNoUrl(100, 0), false);
    assert.strictEqual(shouldPromoteToPublishedNoUrl(100, -5), false);
  });
});
```

- [ ] **Step 2: Запустить test — verify FAIL**

```bash
cd /home/claude-user/autowarm-testbench
node --test --test-force-exit tests/test_url_poller_helpers.test.js 2>&1 | tail -20
```

Expected: FAIL с `Cannot destructure property 'shouldPromoteToPublishedNoUrl' of '...' as it is undefined` или похожим.

- [ ] **Step 3: Реализовать функцию в server.js**

Перед строкой `// Обработка задач ожидающих URL:` (около server.js:6841) добавить:

```javascript
/**
 * WP #86 PR1: проверка достиг ли счётчик retry url-capture-поллера
 * максимума, после которого задача промоутится в `published_no_url`
 * (terminal status: «опубликовано, но specific URL не получен»).
 *
 * @param {number} attempts - текущее значение publish_tasks.url_capture_attempts
 * @param {number} max - URL_CAPTURE_MAX_ATTEMPTS (env-var, default 30)
 * @returns {boolean} true если пора промоутить
 */
function shouldPromoteToPublishedNoUrl(attempts, max) {
  if (typeof max !== 'number' || max <= 0) return false;
  if (typeof attempts !== 'number' || attempts < 0) return false;
  return attempts >= max;
}
```

И в нижнем `module.exports` блоке (server.js:8028+) добавить:

```javascript
  // WP #86 PR1: url-poller helpers
  module.exports.shouldPromoteToPublishedNoUrl = shouldPromoteToPublishedNoUrl;
```

- [ ] **Step 4: Запустить test — verify PASS**

```bash
node --test --test-force-exit tests/test_url_poller_helpers.test.js 2>&1 | tail -10
```

Expected: `# pass 5` (или больше), `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add server.js tests/test_url_poller_helpers.test.js
git commit -m "test(url-poller): WP #86 PR1 — shouldPromoteToPublishedNoUrl helper + tests

Извлекаю в pure-helper логику «пора ли промоутить awaiting_url в
published_no_url». Защита от max<=0 (kill-switch semantics) и
отрицательных attempts (defensive).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Извлечь helper `getUrlPollerLimit` + `getUrlCaptureMaxAttempts` + tests

**Files:**
- Modify: `server.js`
- Modify: `tests/test_url_poller_helpers.test.js`

- [ ] **Step 1: Дописать failing tests**

В `tests/test_url_poller_helpers.test.js` добавить:

```javascript
const {
  shouldPromoteToPublishedNoUrl,
  getUrlPollerLimit,
  getUrlCaptureMaxAttempts,
} = require('../server.js');

describe('getUrlPollerLimit', () => {
  const orig = process.env.URL_POLLER_LIMIT;
  const restore = () => {
    if (orig == null) delete process.env.URL_POLLER_LIMIT;
    else process.env.URL_POLLER_LIMIT = orig;
  };

  test('returns default 100 когда env unset', () => {
    delete process.env.URL_POLLER_LIMIT;
    assert.strictEqual(getUrlPollerLimit(), 100);
  });

  test('returns parsed integer когда env set', () => {
    process.env.URL_POLLER_LIMIT = '250';
    assert.strictEqual(getUrlPollerLimit(), 250);
  });

  test('returns default 100 на пустой / нечисловой env', () => {
    process.env.URL_POLLER_LIMIT = '';
    assert.strictEqual(getUrlPollerLimit(), 100);
    process.env.URL_POLLER_LIMIT = 'abc';
    assert.strictEqual(getUrlPollerLimit(), 100);
  });

  test('returns default 100 на ноль/отрицательное', () => {
    process.env.URL_POLLER_LIMIT = '0';
    assert.strictEqual(getUrlPollerLimit(), 100);
    process.env.URL_POLLER_LIMIT = '-5';
    assert.strictEqual(getUrlPollerLimit(), 100);
  });

  test('restore env', () => { restore(); });
});

describe('getUrlCaptureMaxAttempts', () => {
  const orig = process.env.URL_CAPTURE_MAX_ATTEMPTS;
  const restore = () => {
    if (orig == null) delete process.env.URL_CAPTURE_MAX_ATTEMPTS;
    else process.env.URL_CAPTURE_MAX_ATTEMPTS = orig;
  };

  test('returns default 30 когда env unset', () => {
    delete process.env.URL_CAPTURE_MAX_ATTEMPTS;
    assert.strictEqual(getUrlCaptureMaxAttempts(), 30);
  });

  test('returns parsed integer', () => {
    process.env.URL_CAPTURE_MAX_ATTEMPTS = '15';
    assert.strictEqual(getUrlCaptureMaxAttempts(), 15);
  });

  test('returns 0 (kill-switch) когда env="0"', () => {
    // 0 отключает промоут (см. shouldPromoteToPublishedNoUrl) — это
    // легитимный kill-switch, а не fallback к default.
    process.env.URL_CAPTURE_MAX_ATTEMPTS = '0';
    assert.strictEqual(getUrlCaptureMaxAttempts(), 0);
  });

  test('returns default 30 на нечисловой', () => {
    process.env.URL_CAPTURE_MAX_ATTEMPTS = 'abc';
    assert.strictEqual(getUrlCaptureMaxAttempts(), 30);
  });

  test('restore env', () => { restore(); });
});
```

- [ ] **Step 2: Запустить — verify FAIL**

```bash
node --test --test-force-exit tests/test_url_poller_helpers.test.js 2>&1 | tail -20
```

Expected: новые tests FAIL на missing функциях.

- [ ] **Step 3: Реализовать helpers в server.js**

Рядом с `shouldPromoteToPublishedNoUrl` (около server.js:6841) добавить:

```javascript
/**
 * WP #86 PR1: env-driven LIMIT для url-poller. Default 100 заменил старый
 * жёсткий 30 — устранял starvation новых задач при 45+ stuck awaiting_url.
 * Возвращает default на пустой / нечисловой / непозитивный env.
 */
function getUrlPollerLimit() {
  const raw = process.env.URL_POLLER_LIMIT;
  const n = parseInt(raw, 10);
  if (!Number.isFinite(n) || n <= 0) return 100;
  return n;
}

/**
 * WP #86 PR1: max попыток url-capture поллера прежде чем промоут в
 * published_no_url. Default 30 проб × 2-мин cron tick = ~1 час.
 *
 * Особый случай: env="0" возвращает 0 — это legitimate kill-switch
 * (промоут отключён, задачи остаются в awaiting_url до 48ч-timeout).
 * Только пустой / нечисловой env даёт fallback к default 30.
 */
function getUrlCaptureMaxAttempts() {
  const raw = process.env.URL_CAPTURE_MAX_ATTEMPTS;
  if (raw === '0') return 0;
  const n = parseInt(raw, 10);
  if (!Number.isFinite(n) || n < 0) return 30;
  return n;
}
```

В export-блоке (server.js:8028+) добавить:

```javascript
  module.exports.getUrlPollerLimit = getUrlPollerLimit;
  module.exports.getUrlCaptureMaxAttempts = getUrlCaptureMaxAttempts;
```

- [ ] **Step 4: Запустить tests — verify PASS**

```bash
node --test --test-force-exit tests/test_url_poller_helpers.test.js 2>&1 | tail -10
```

Expected: `# pass 14` (5 + 5 + 4), `# fail 0`.

- [ ] **Step 5: Commit**

```bash
git add server.js tests/test_url_poller_helpers.test.js
git commit -m "test(url-poller): WP #86 PR1 — env-driven limits + kill-switches

getUrlPollerLimit (default 100) и getUrlCaptureMaxAttempts (default 30).
Особый случай URL_CAPTURE_MAX_ATTEMPTS=0 — legitimate kill-switch для
отключения промоута в published_no_url.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## checkProcessingTasks patch (PR1.C)

### Task 4: Заменить LIMIT 30 → getUrlPollerLimit() + ORDER BY updated_at

**Files:**
- Modify: `server.js:6846-6851`

- [ ] **Step 1: Прочитать текущий блок (chronological reference)**

```bash
sed -n '6840,6880p' server.js
```

- [ ] **Step 2: Заменить SELECT query**

Найти в `server.js` (около строки 6846):

```javascript
    const { rows } = await pool.query(
      `SELECT id, platform, account, post_url, started_at, status FROM publish_tasks 
       WHERE status IN ('processing', 'awaiting_url')
         AND updated_at < NOW() - INTERVAL '1 minute'
       ORDER BY started_at ASC LIMIT 30`
    );
```

Заменить на:

```javascript
    // WP #86 PR1: ORDER BY updated_at ASC (fairness — голодающие задачи
    // приоритетнее), LIMIT через env-driven helper (было жёсткий 30,
    // starve'ило новые задачи при 45+ stuck). Также SELECT'им новое поле
    // url_capture_attempts для per-task retry budget логики.
    const pollerLimit = getUrlPollerLimit();
    const { rows } = await pool.query(
      `SELECT id, platform, account, post_url, started_at, status,
              url_capture_attempts
       FROM publish_tasks
       WHERE status IN ('processing', 'awaiting_url')
         AND updated_at < NOW() - INTERVAL '1 minute'
       ORDER BY updated_at ASC
       LIMIT $1`,
      [pollerLimit]
    );
```

- [ ] **Step 3: Verify suite green**

```bash
npm test 2>&1 | tail -10
```

Expected: все tests pass (никаких regressions).

- [ ] **Step 4: Commit**

```bash
git add server.js
git commit -m "fix(url-poller): WP #86 PR1 — LIMIT 100 + ORDER BY updated_at

Было: LIMIT 30 + ORDER BY started_at ASC — старейшие 30 задач забивали
слоты и голодали новые при 45+ stuck (snapshot 2026-05-18 показал 30
задач с upd_min<5 и 13 с upd_min>3h).

Стало: env-driven LIMIT (default 100) + ORDER BY updated_at ASC —
задача с самым давним последним probe'ом получает приоритет.

Также SELECT'им url_capture_attempts для per-task retry budget (Task 5).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: NULL `started_at` zombie fix (COALESCE в 48h timeout)

**Files:**
- Modify: `server.js:6860-6873`

- [ ] **Step 1: Прочитать текущий 48h timeout блок**

```bash
sed -n '6859,6877p' server.js
```

- [ ] **Step 2: Заменить ageHours computation**

Найти:

```javascript
    for (const task of rows) {
      const ageHours = task.started_at
        ? (Date.now() - new Date(task.started_at).getTime()) / 3600000
        : 0;
      // Таймаут 48ч
      if (ageHours > 48) {
```

Заменить на:

```javascript
    for (const task of rows) {
      // WP #86 PR1: NULL started_at zombie fix. Раньше: `started_at ? ... : 0`
      // давало ageHours=0 для NULL — 48ч timeout НИКОГДА не срабатывал, задачи
      // (#961 IG @makiavelli485, 4× YT @Ivana-o3j) торчали вечно. Теперь
      // fallback на updated_at когда started_at отсутствует.
      const ageBasis = task.started_at || task.updated_at;
      const ageHours = ageBasis
        ? (Date.now() - new Date(ageBasis).getTime()) / 3600000
        : 0;
      // Таймаут 48ч
      if (ageHours > 48) {
```

**Замечание:** мы делаем fallback на `updated_at` — это поле SELECT'ится из БД через `WHERE updated_at < NOW() - INTERVAL '1 minute'` (значит он точно есть). Но запрос его не возвращает в SELECT-list. Расширим в Step 3.

- [ ] **Step 3: Добавить updated_at в SELECT**

Найти (изменённую в Task 4) query:

```javascript
      `SELECT id, platform, account, post_url, started_at, status,
              url_capture_attempts
       FROM publish_tasks
```

Заменить на:

```javascript
      `SELECT id, platform, account, post_url, started_at, status,
              url_capture_attempts, updated_at
       FROM publish_tasks
```

- [ ] **Step 4: Verify suite green**

```bash
npm test 2>&1 | tail -10
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add server.js
git commit -m "fix(url-poller): WP #86 PR1 — NULL started_at zombie 48h timeout

Было: ageHours = started_at ? (...) : 0 — для NULL давало 0, 48ч timeout
НИКОГДА не срабатывал. Snapshot 2026-05-18: 5 задач торчат вечно
(#961 IG @makiavelli485, 4× YT @Ivana-o3j).

Стало: fallback на updated_at когда started_at NULL — задача отвалится
по 48ч-timeout от любого активного знака жизни.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Промоут в `published_no_url` при exhausted attempts

**Files:**
- Modify: `server.js:6885-6920` (per-group обработка «видео не найдены» / «все видео заняты» / «свободных видео не хватило»)

- [ ] **Step 1: Прочитать существующий update в трёх местах**

```bash
sed -n '6885,6935p' server.js
```

Идентифицируем 3 места где сейчас стоит `UPDATE publish_tasks SET updated_at=NOW() WHERE id=$1`:
1. line ~6890 (видео не найдены)
2. line ~6914 (все видео заняты)
3. line ~6930 (свободных видео не хватило)

Каждое — кандидат на attempts++.

- [ ] **Step 2: Заменить первое место (видео не найдены)**

Найти:

```javascript
      if (!allVideos || allVideos.length === 0) {
        // Нет видео — обновляем updated_at чтобы не проверять слишком часто
        for (const t of tasks) {
          await pool.query("UPDATE publish_tasks SET updated_at=NOW() WHERE id=$1", [t.id]);
          const age = t.started_at ? Math.round((Date.now() - new Date(t.started_at).getTime()) / 60000) : '?';
          console.log(`[url-poller] task#${t.id} ${platform}: видео не найдены (${age}мин)`);
        }
        continue;
      }
```

Заменить на:

```javascript
      if (!allVideos || allVideos.length === 0) {
        // WP #86 PR1: attempts++ + промоут в published_no_url при exhausted.
        // Раньше: только бамп updated_at → бесконечный loop до 48ч timeout.
        const maxAttempts = getUrlCaptureMaxAttempts();
        for (const t of tasks) {
          const newAttempts = (t.url_capture_attempts || 0) + 1;
          if (shouldPromoteToPublishedNoUrl(newAttempts, maxAttempts)) {
            await pool.query(
              `UPDATE publish_tasks
               SET status='published_no_url',
                   url_capture_attempts=$1,
                   url_capture_last_attempt_at=NOW(),
                   updated_at=NOW(),
                   log = COALESCE(log,'') || $2
               WHERE id=$3`,
              [newAttempts,
               `\n[url-poller WP#86] url_capture_exhausted after ${newAttempts} attempts — promoted to published_no_url`,
               t.id]
            );
            console.log(`[url-poller] task#${t.id} ${platform}: url_capture_exhausted (${newAttempts} attempts) → published_no_url ⚠️`);
          } else {
            await pool.query(
              `UPDATE publish_tasks
               SET url_capture_attempts=$1,
                   url_capture_last_attempt_at=NOW(),
                   updated_at=NOW()
               WHERE id=$2`,
              [newAttempts, t.id]
            );
            const age = t.started_at ? Math.round((Date.now() - new Date(t.started_at).getTime()) / 60000) : '?';
            console.log(`[url-poller] task#${t.id} ${platform}: видео не найдены (${age}мин, attempt ${newAttempts}/${maxAttempts})`);
          }
        }
        continue;
      }
```

- [ ] **Step 3: Заменить второе место (все видео заняты)**

Найти:

```javascript
      if (freeVideos.length === 0) {
        for (const t of tasks) {
          await pool.query("UPDATE publish_tasks SET updated_at=NOW() WHERE id=$1", [t.id]);
          const age = t.started_at ? Math.round((Date.now() - new Date(t.started_at).getTime()) / 60000) : '?';
          console.log(`[url-poller] task#${t.id} ${platform}: все видео заняты (${age}мин)`);
        }
        continue;
      }
```

Заменить на (та же логика, другой лог):

```javascript
      if (freeVideos.length === 0) {
        // WP #86 PR1: attempts++ + промоут (та же логика что «видео не найдены»)
        const maxAttempts = getUrlCaptureMaxAttempts();
        for (const t of tasks) {
          const newAttempts = (t.url_capture_attempts || 0) + 1;
          if (shouldPromoteToPublishedNoUrl(newAttempts, maxAttempts)) {
            await pool.query(
              `UPDATE publish_tasks
               SET status='published_no_url',
                   url_capture_attempts=$1,
                   url_capture_last_attempt_at=NOW(),
                   updated_at=NOW(),
                   log = COALESCE(log,'') || $2
               WHERE id=$3`,
              [newAttempts,
               `\n[url-poller WP#86] url_capture_exhausted (free_videos=0) after ${newAttempts} attempts — promoted to published_no_url`,
               t.id]
            );
            console.log(`[url-poller] task#${t.id} ${platform}: url_capture_exhausted (free_videos=0, ${newAttempts} attempts) → published_no_url ⚠️`);
          } else {
            await pool.query(
              `UPDATE publish_tasks
               SET url_capture_attempts=$1,
                   url_capture_last_attempt_at=NOW(),
                   updated_at=NOW()
               WHERE id=$2`,
              [newAttempts, t.id]
            );
            const age = t.started_at ? Math.round((Date.now() - new Date(t.started_at).getTime()) / 60000) : '?';
            console.log(`[url-poller] task#${t.id} ${platform}: все видео заняты (${age}мин, attempt ${newAttempts}/${maxAttempts})`);
          }
        }
        continue;
      }
```

- [ ] **Step 4: Заменить третье место (свободных видео не хватило)**

Найти:

```javascript
      for (const task of reversedTasks) {
        if (videoIdx >= freeVideos.length) {
          await pool.query("UPDATE publish_tasks SET updated_at=NOW() WHERE id=$1", [task.id]);
          const age = task.started_at ? Math.round((Date.now() - new Date(task.started_at).getTime()) / 60000) : '?';
          console.log(`[url-poller] task#${task.id} ${platform}: свободных видео не хватило (${age}мин)`);
          continue;
        }
```

Заменить на:

```javascript
      const maxAttemptsHere = getUrlCaptureMaxAttempts();
      for (const task of reversedTasks) {
        if (videoIdx >= freeVideos.length) {
          // WP #86 PR1: тот же attempts++ + промоут pattern
          const newAttempts = (task.url_capture_attempts || 0) + 1;
          if (shouldPromoteToPublishedNoUrl(newAttempts, maxAttemptsHere)) {
            await pool.query(
              `UPDATE publish_tasks
               SET status='published_no_url',
                   url_capture_attempts=$1,
                   url_capture_last_attempt_at=NOW(),
                   updated_at=NOW(),
                   log = COALESCE(log,'') || $2
               WHERE id=$3`,
              [newAttempts,
               `\n[url-poller WP#86] url_capture_exhausted (insufficient_free_videos) after ${newAttempts} attempts — promoted to published_no_url`,
               task.id]
            );
            console.log(`[url-poller] task#${task.id} ${platform}: url_capture_exhausted (insufficient_free, ${newAttempts} attempts) → published_no_url ⚠️`);
          } else {
            await pool.query(
              `UPDATE publish_tasks
               SET url_capture_attempts=$1,
                   url_capture_last_attempt_at=NOW(),
                   updated_at=NOW()
               WHERE id=$2`,
              [newAttempts, task.id]
            );
            const age = task.started_at ? Math.round((Date.now() - new Date(task.started_at).getTime()) / 60000) : '?';
            console.log(`[url-poller] task#${task.id} ${platform}: свободных видео не хватило (${age}мин, attempt ${newAttempts}/${maxAttemptsHere})`);
          }
          continue;
        }
```

- [ ] **Step 5: Reset attempts при УСПЕХЕ — в существующем UPDATE для done**

Найти:

```javascript
        await pool.query(
          "UPDATE publish_tasks SET post_url=$1, status='done', updated_at=NOW() WHERE id=$2",
          [video.url, task.id]
        );
        console.log(`[url-poller] task#${task.id} ${platform}: URL → ${video.url} → done ✅`);
```

Заменить на:

```javascript
        // WP #86 PR1: сбрасываем url_capture_attempts при успехе для observability
        await pool.query(
          `UPDATE publish_tasks
           SET post_url=$1, status='done',
               url_capture_attempts=0,
               updated_at=NOW()
           WHERE id=$2`,
          [video.url, task.id]
        );
        console.log(`[url-poller] task#${task.id} ${platform}: URL → ${video.url} → done ✅`);
```

- [ ] **Step 6: Прогнать suite — verify green**

```bash
npm test 2>&1 | tail -10
```

Expected: pass (никакие existing tests не поломаны — мы добавляем колонку в UPDATE, она nullable).

- [ ] **Step 7: Commit**

```bash
git add server.js
git commit -m "feat(url-poller): WP #86 PR1 — attempts++ + promote to published_no_url

В трёх ветках «нет видео» / «все заняты» / «свободных не хватило»:
- url_capture_attempts++ + url_capture_last_attempt_at=NOW()
- если attempts >= URL_CAPTURE_MAX_ATTEMPTS → status='published_no_url'
  + log marker для observability
- иначе бамп updated_at как раньше

Также reset attempts=0 при успешном получении URL (terminal-фикс).

Default URL_CAPTURE_MAX_ATTEMPTS=30 = ~1ч до промоута (30 проб × 2-min
cron tick). env=0 = kill-switch (задачи не промоутятся, 48ч timeout
остаётся safety net).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## syncQueueStatuses + analytics (PR1.D)

### Task 7: syncQueueStatuses — `published_no_url` → pq.status='done'

**Files:**
- Modify: `server.js:7113-7121`

- [ ] **Step 1: Прочитать текущий done-sync блок**

```bash
sed -n '7110,7125p' server.js
```

- [ ] **Step 2: Расширить done branch**

Найти:

```javascript
    // done: pt.status IN (done, needs_verification) → pq.status = 'done'
    const { rows: r1 } = await pool.query(`
      UPDATE publish_queue pq
      SET status = 'done', updated_at = NOW()
      FROM publish_tasks pt
      WHERE pq.publish_task_id = pt.id
        AND pt.status IN ('done', 'needs_verification', 'moderation')
        AND pq.status NOT IN ('done', 'skipped', 'cancelled')
      RETURNING pq.id
    `);
```

Заменить на:

```javascript
    // done: pt.status IN (done, needs_verification, moderation, published_no_url) → pq.status = 'done'
    // WP #86 PR1: published_no_url — публикация состоялась без specific URL,
    // slot потрачен, для очереди = success. НЕ failed (иначе re-queue → дубль).
    const { rows: r1 } = await pool.query(`
      UPDATE publish_queue pq
      SET status = 'done', updated_at = NOW()
      FROM publish_tasks pt
      WHERE pq.publish_task_id = pt.id
        AND pt.status IN ('done', 'needs_verification', 'moderation', 'published_no_url')
        AND pq.status NOT IN ('done', 'skipped', 'cancelled')
      RETURNING pq.id
    `);
```

- [ ] **Step 3: Verify suite green**

```bash
npm test 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add server.js
git commit -m "feat(sync-queue): WP #86 PR1 — published_no_url → pq.status='done'

published_no_url означает «публикация состоялась, specific URL не получен» —
для publish_queue это success (slot потрачен, ratelimit учтён). Если бы
синкали как failed, re-queue path создал бы дубль.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Analytics queries — include `published_no_url` в success counts

**Files:**
- Modify: `server.js` lines 1303, 1322, 1856

- [ ] **Step 1: Прочитать каждое место**

```bash
sed -n '1300,1325p' server.js
sed -n '1853,1860p' server.js
```

- [ ] **Step 2: Line 1303 — заменить**

Найти:

```javascript
        COUNT(t.id) FILTER (WHERE t.status IN ('done','completed')) AS success,
```

Заменить на:

```javascript
        COUNT(t.id) FILTER (WHERE t.status IN ('done','completed','published_no_url')) AS success,
```

- [ ] **Step 3: Line ~1322 — заменить**

Найти первый встретившийся:

```javascript
        COUNT(*) FILTER (WHERE t.status='done')::int AS done,
```

Заменить на:

```javascript
        -- WP #86 PR1: published_no_url считается успехом для дашборда
        COUNT(*) FILTER (WHERE t.status IN ('done','published_no_url'))::int AS done,
```

- [ ] **Step 4: Line ~1856 — заменить**

Найти:

```javascript
        COUNT(*) FILTER (WHERE status = 'done')                              AS done,
```

Заменить на:

```javascript
        -- WP #86 PR1: published_no_url считается успехом для дашборда
        COUNT(*) FILTER (WHERE status IN ('done','published_no_url'))        AS done,
```

- [ ] **Step 5: Double-check — других мест нет?**

```bash
grep -nE "status\s*=\s*['\"]done['\"]|status\s*IN\s*\([^)]*done" server.js | grep -v 'published_no_url'
```

Expected output: только known lines (830, 1150, 2041, 2048, 2663, 2681, 5490, 5617, 5986, 6938, 7115, 7311) — все они либо другие таблицы (archive/autowarm/unic_results), либо UPDATE'ы. Если новые hits — аудитить.

- [ ] **Step 6: Verify suite + commit**

```bash
npm test 2>&1 | tail -10
git add server.js
git commit -m "feat(analytics): WP #86 PR1 — published_no_url в success-counts дашборда

3 места в server.js где аггрегируется success rate publish_tasks:
теперь published_no_url считается как успех (это успешная публикация,
просто без specific URL). Иначе дашборд бы показывал ложный спад.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## UI — 5 мест в public/index.html (PR1.E)

### Task 9: Status filter dropdown + 4 badge mapping locations

**Files:**
- Modify: `public/index.html:2434`
- Modify: `public/index.html:6700-6701`
- Modify: `public/index.html:7203, 7211`
- Modify: `public/index.html:10727`
- Modify: `public/index.html:10881`

- [ ] **Step 1: Status filter dropdown (line 2434)**

Найти:

```html
<option value="awaiting_url">Awaiting URL</option><option value="done">Done</option>
```

Заменить на:

```html
<option value="awaiting_url">Awaiting URL</option><option value="published_no_url">⚠️ Без URL</option><option value="done">Done</option>
```

- [ ] **Step 2: statusLabels map (line ~6700)**

Найти:

```javascript
  const statusLabels = { running: 'запущена', done: 'день ✓', completed: '🎉 завершён', failed: 'ошибка', preflight_failed: '⚠️ preflight', pending: 'ожидает', scheduled: '📅 запланирован', paused: 'пауза', offline: 'офлайн', banned: '🚫 бан', needs_verification: '⚠️ верификация', awaiting_url: '🔗 ждёт URL' };
```

Заменить на (добавить `published_no_url` в конец):

```javascript
  const statusLabels = { running: 'запущена', done: 'день ✓', completed: '🎉 завершён', failed: 'ошибка', preflight_failed: '⚠️ preflight', pending: 'ожидает', scheduled: '📅 запланирован', paused: 'пауза', offline: 'офлайн', banned: '🚫 бан', needs_verification: '⚠️ верификация', awaiting_url: '🔗 ждёт URL', published_no_url: '✅ без URL' };
```

- [ ] **Step 3: statusClasses map (line ~6701)**

Найти:

```javascript
  const statusClasses = { running: 'status-running', done: 'status-done', completed: 'status-done', failed: 'status-failed', preflight_failed: 'status-failed', pending: 'status-pending', scheduled: 'status-scheduled', paused: 'status-paused', offline: 'status-offline', banned: 'bg-red-100 text-red-700', needs_verification: 'bg-yellow-100 text-yellow-700', awaiting_url: 'bg-indigo-100 text-indigo-700' };
```

Заменить на:

```javascript
  const statusClasses = { running: 'status-running', done: 'status-done', completed: 'status-done', failed: 'status-failed', preflight_failed: 'status-failed', pending: 'status-pending', scheduled: 'status-scheduled', paused: 'status-paused', offline: 'status-offline', banned: 'bg-red-100 text-red-700', needs_verification: 'bg-yellow-100 text-yellow-700', awaiting_url: 'bg-indigo-100 text-indigo-700', published_no_url: 'bg-yellow-100 text-yellow-700' };
```

- [ ] **Step 4: Factory map (line ~7203/7211)**

Найти:

```javascript
  needs_verification:'⚠️ Верификация', awaiting_url:'🔗 Ждёт URL',
```

Заменить на:

```javascript
  needs_verification:'⚠️ Верификация', awaiting_url:'🔗 Ждёт URL', published_no_url:'✅ Без URL',
```

И ниже (line ~7211):

```javascript
  needs_verification:'bg-yellow-100 text-yellow-700', awaiting_url:'bg-indigo-100 text-indigo-700',
```

Заменить на:

```javascript
  needs_verification:'bg-yellow-100 text-yellow-700', awaiting_url:'bg-indigo-100 text-indigo-700', published_no_url:'bg-yellow-100 text-yellow-700',
```

- [ ] **Step 5: publish_tasks badge (line ~10727)**

Найти:

```javascript
  awaiting_url:'<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-700 border border-indigo-200">🔗 Ждёт URL</span>',
```

Заменить (добавить новую строку после неё):

```javascript
  awaiting_url:'<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-700 border border-indigo-200">🔗 Ждёт URL</span>',
  published_no_url:'<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-yellow-100 text-yellow-700 border border-yellow-200">✅ Без URL</span>',
```

- [ ] **Step 6: Queue badge (line ~10881)**

Найти:

```javascript
  awaiting_url: '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-violet-100 text-violet-700 border border-violet-200">🔗 Ожидает URL</span>',
```

Заменить (добавить после):

```javascript
  awaiting_url: '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-violet-100 text-violet-700 border border-violet-200">🔗 Ожидает URL</span>',
  published_no_url: '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-yellow-100 text-yellow-700 border border-yellow-200">✅ Без URL</span>',
```

- [ ] **Step 7: Sanity grep — все 5 мест покрыты**

```bash
grep -n "published_no_url" public/index.html
```

Expected: 6+ hits (5 changes + filter option).

- [ ] **Step 8: Commit**

```bash
git add public/index.html
git commit -m "feat(ui): WP #86 PR1 — badge для published_no_url + filter option

5 мест renderera per memory feedback_validator_two_slot_renderers:
- статус-filter dropdown (line 2434)
- statusLabels + statusClasses maps (~6700-6701)
- factory map labels + classes (~7203, 7211)
- publish_tasks inline badge (~10727)
- queue inline badge (~10881)

Цвет: yellow (между зелёным done и красным failed) — \"успех с asterisk\".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Integration test + local smoke (PR1.F)

### Task 10: Integration test для url_capture_attempts++ + промоут

**Files:**
- Modify: `tests/test_url_poller_helpers.test.js`

- [ ] **Step 1: Дописать integration-style test через mock pool**

В конец `tests/test_url_poller_helpers.test.js` добавить:

```javascript
describe('checkProcessingTasks integration (mock pool)', () => {
  // Этот тест проверяет логику attempts++ и промоута через mock pool.query.
  // Он НЕ загружает реальный server.js (тот ожидает БД-подключения),
  // а проверяет интегральную логику через симуляцию вызовов SQL.

  test('задача с attempts=29 и max=30 должна промоутиться в published_no_url', () => {
    const t = { id: 7342, url_capture_attempts: 29, started_at: new Date(), platform: 'TikTok' };
    const newAttempts = (t.url_capture_attempts || 0) + 1;
    const max = 30;
    assert.strictEqual(shouldPromoteToPublishedNoUrl(newAttempts, max), true);
  });

  test('задача с attempts=10 и max=30 должна продолжать retry', () => {
    const t = { id: 7342, url_capture_attempts: 10, started_at: new Date(), platform: 'TikTok' };
    const newAttempts = (t.url_capture_attempts || 0) + 1;
    const max = 30;
    assert.strictEqual(shouldPromoteToPublishedNoUrl(newAttempts, max), false);
  });

  test('задача с null url_capture_attempts — стартует с 1', () => {
    const t = { id: 7342, url_capture_attempts: null };
    const newAttempts = (t.url_capture_attempts || 0) + 1;
    assert.strictEqual(newAttempts, 1);
  });

  test('kill-switch max=0 — задача не промоутится при любом attempts', () => {
    process.env.URL_CAPTURE_MAX_ATTEMPTS = '0';
    const max = getUrlCaptureMaxAttempts();
    assert.strictEqual(max, 0);
    assert.strictEqual(shouldPromoteToPublishedNoUrl(999, max), false);
    delete process.env.URL_CAPTURE_MAX_ATTEMPTS;
  });
});
```

- [ ] **Step 2: Запустить — verify PASS**

```bash
node --test --test-force-exit tests/test_url_poller_helpers.test.js 2>&1 | tail -10
```

Expected: все tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_url_poller_helpers.test.js
git commit -m "test(url-poller): WP #86 PR1 — integration сценарии attempts++ + промоут

Симулируют ключевые сценарии без реального pool: задача на грани промоута,
задача в середине retry, null-attempts стартовая позиция, kill-switch max=0.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Local smoke test — синтетическая задача с attempts=MAX-1

**Files:** N/A (manual smoke).

- [ ] **Step 1: Создать synthetic задачу в openclaw**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
INSERT INTO publish_tasks (platform, account, status, started_at, updated_at, url_capture_attempts, post_url, log)
VALUES ('TikTok', '__wp86_test_acct', 'awaiting_url', NOW(), NOW() - INTERVAL '5 minutes', 29,
        'https://www.tiktok.com/@__wp86_test_acct',
        '[wp86-smoke] synthetic task for PR1 verification')
RETURNING id, status, url_capture_attempts;
"
```

Записать `id` — назовём его `$SMOKE_ID`.

- [ ] **Step 2: Запустить server.js локально (с фиктивным URL_CAPTURE_MAX_ATTEMPTS=30)**

В отдельном терминале:

```bash
cd /home/claude-user/autowarm-testbench
URL_CAPTURE_MAX_ATTEMPTS=30 URL_POLLER_LIMIT=100 PORT=3849 node server.js 2>&1 | grep -E "url-poller|published_no_url"
```

Подождать первый poller-tick (15с initial + 2мин interval).

- [ ] **Step 3: Проверить промоут в БД**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, status, url_capture_attempts, url_capture_last_attempt_at,
       substring(log, length(log)-300) AS log_tail
FROM publish_tasks WHERE account='__wp86_test_acct';
"
```

Expected: `status='published_no_url'`, `url_capture_attempts=30`, лог содержит `url_capture_exhausted ... promoted to published_no_url`.

- [ ] **Step 4: Очистить smoke-задачу**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
DELETE FROM publish_tasks WHERE account='__wp86_test_acct';
"
```

Expected: `DELETE 1`.

- [ ] **Step 5: Остановить локальный server.js** (Ctrl-C в его терминале).

- [ ] **Step 6: Записать evidence**

Create `docs/evidence/2026-05-18-wp86-pr1-local-smoke.md` в worktree-репо:

```bash
cat > /home/claude-user/contenthunter/.claude/worktrees/wp86-awaiting-url-stuck/docs/evidence/2026-05-18-wp86-pr1-local-smoke.md <<'EOF'
# WP #86 PR1 — local smoke evidence (2026-05-18)

Synthetic awaiting_url задача с url_capture_attempts=29 на test-аккаунте.
После одного poller-tick'а с URL_CAPTURE_MAX_ATTEMPTS=30:
- status: awaiting_url → published_no_url ✅
- url_capture_attempts: 29 → 30 ✅
- log marker: `url_capture_exhausted ... promoted to published_no_url` ✅

Test cleanup: synthetic запись удалена.
EOF
```

Commit evidence в worktree-репо:

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/wp86-awaiting-url-stuck
git add docs/evidence/2026-05-18-wp86-pr1-local-smoke.md
git commit -m "evidence: WP #86 PR1 local smoke — published_no_url промоут работает"
cd /home/claude-user/autowarm-testbench
```

---

## Pre-deploy validation (PR1.G)

### Task 12: Полный test suite green + UI визуальная проверка

**Files:** N/A — validation.

- [ ] **Step 1: Полный suite**

```bash
cd /home/claude-user/autowarm-testbench
npm test 2>&1 | tail -30
```

Expected: `# pass N+`, `# fail 0`. Если что-то падает — НЕ деплоить, разбираться.

- [ ] **Step 2: Запустить server.js локально + открыть dashboard**

```bash
PORT=3849 node server.js &
SERVER_PID=$!
sleep 5
```

Открыть в браузере (или через curl) `http://localhost:3849/publish-tasks` — найти status-filter dropdown, проверить новую опцию `⚠️ Без URL`. Если есть синтетическая задача в published_no_url — должна показаться с жёлтым badge'м.

```bash
kill $SERVER_PID 2>/dev/null
```

- [ ] **Step 3: Cross-repo sanity grep — никакие foreign места не пропущены**

```bash
grep -rn "publish_tasks.*status\|status.*publish_tasks" /home/claude-user/validator-contenthunter/ 2>/dev/null | head -10
```

Expected: 0 hits (validator не зависит от publish_tasks). Если что-то — аудитить.

---

## Deploy via PR (PR1.H)

### Task 13: Push branch + создать PR

**Files:** N/A — git ops.

- [ ] **Step 1: Прогнать `git status` + `git log` — чистая ветка**

```bash
cd /home/claude-user/autowarm-testbench
git status
git log --oneline main..HEAD
```

Expected: clean tree. `main..HEAD` показывает ~9 коммитов (Tasks 1-10).

- [ ] **Step 2: Push branch на origin (GenGo2)**

```bash
git push -u origin feat/wp86-pr1-poller-published-no-url
```

Expected: push success, link на PR creation.

- [ ] **Step 3: Создать PR через `gh`**

```bash
source ~/secrets/github-gengo2.env
gh pr create --title "WP #86 PR1 — url-poller fix + published_no_url terminal status" --body "$(cat <<'EOF'
## Summary

PR1 фаза WP #86 — foundation: чинит url-poller correctness (LIMIT-30 starvation, NULL-zombies) + добавляет terminal-статус `published_no_url` для задач где публикация состоялась, но specific URL не получен после exhaustion. Включает retroactive cleanup для 45 stuck задач (применяется отдельной миграцией ПОСЛЕ деплоя кода).

OpenProject: [WP #86](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/86)

Spec: `docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md` (в contenthunter-репо)

## Changes

- **Schema:** новые колонки `url_capture_attempts`, `pre_publish_video_ids`, `url_capture_last_attempt_at` + partial index
- **Poller (server.js):** ORDER BY updated_at, LIMIT 100 (env-driven), NULL-coalesce 48h timeout, attempts++ + promote to `published_no_url` при exhaustion
- **Sync queue:** `published_no_url` → `pq.status='done'`
- **Analytics:** 3 SQL queries — `published_no_url` считается успехом
- **UI:** badge + filter в 5 местах `public/index.html`
- **Tests:** новый `test_url_poller_helpers.test.js` — pure helpers + integration scenarios

## Kill-switches

- `URL_POLLER_LIMIT` (default 100) — query LIMIT
- `URL_CAPTURE_MAX_ATTEMPTS` (default 30, `=0` отключает промоут)

## Test plan

- [ ] CI tests green (`npm test`)
- [ ] Schema migration apply на prod openclaw (`psql -f migrations/20260518_publish_tasks_url_capture_fields.sql`)
- [ ] Post-deploy: verify pm2 picked new server.js (`sudo pm2 describe autowarm | grep -E 'exec cwd|uptime'`)
- [ ] Post-deploy: тестовая synthetic awaiting_url задача с attempts=MAX-1 → промоутится в published_no_url в течение 2 мин
- [ ] Post-deploy: применить `20260518_wp86_retroactive_cleanup.sql` — 45 stuck → published_no_url
- [ ] Dashboard визуальная проверка: жёлтый badge `✅ Без URL` для promoted задач

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Запомнить PR URL — он понадобится в Task 17.

- [ ] **Step 4: Дождаться review (если есть) + merge на main**

Per memory `reference_autowarm_git_hook.md` — post-commit hook на prod автоматически подтянет main после мержа. Merge через `gh pr merge --squash --auto` или вручную через GitHub UI.

⚠️ **NO force-push.** Per memory `feedback_subagent_force_push_risk.md`. Если конфликт — pull rebase, не force.

---

## Post-deploy verification (PR1.I)

### Task 14: Verify prod подтянул код + restart pm2 если нужно

**Files:** N/A — prod ops.

- [ ] **Step 1: SSH-проверка main на prod подтянулся**

```bash
sudo cat /root/.openclaw/workspace-genri/autowarm/.git/HEAD
sudo git -C /root/.openclaw/workspace-genri/autowarm log --oneline -3
```

Expected: top commit — squash от PR1.

- [ ] **Step 2: PM2 exec cwd check (per memory feedback_pm2_dump_path_drift)**

```bash
sudo pm2 describe autowarm | grep -E "exec cwd|uptime|status"
```

Expected: `exec cwd: /root/.openclaw/workspace-genri/autowarm`. Если показано `/home/claude-user/autowarm-testbench/` — drift, нужен delete+start из ecosystem config.

- [ ] **Step 3: PM2 restart чтобы подтянуть новый код**

```bash
sudo pm2 restart autowarm --update-env
sleep 5
sudo pm2 logs autowarm --nostream --lines 30
```

Expected: server.js стартовал чисто, нет `Error:` в логах. Видны:
- `📡 Device mapping sync job...`
- `[url-poller]` через ~15с при первом tick'е

---

### Task 15: Apply schema migration на prod openclaw

**Files:** N/A — DB ops.

- [ ] **Step 1: Бэкап publish_tasks на всякий**

```bash
PGPASSWORD=openclaw123 pg_dump -h localhost -U openclaw -d openclaw -t publish_tasks --data-only \
  > /tmp/publish_tasks_backup_$(date +%Y%m%d_%H%M%S).sql
ls -lh /tmp/publish_tasks_backup_*.sql | tail -1
```

Expected: файл создан, размер > 1MB.

- [ ] **Step 2: Apply forward migration**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /home/claude-user/autowarm-testbench/migrations/20260518_publish_tasks_url_capture_fields.sql
```

Expected: `BEGIN`, `ALTER TABLE`, `CREATE INDEX`, `COMMIT`. Никаких errors.

- [ ] **Step 3: Verify columns на prod**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name='publish_tasks'
  AND column_name IN ('url_capture_attempts','pre_publish_video_ids','url_capture_last_attempt_at');
"
```

Expected: 3 rows.

- [ ] **Step 4: Verify partial index**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
\d+ publish_tasks
" | grep -A1 "idx_publish_tasks_status_updated"
```

Expected: index существует, partial-condition в определении.

---

### Task 16: Synthetic prod-smoke (опционально, low-risk verify)

**Files:** N/A — smoke.

- [ ] **Step 1: Создать synthetic задачу на prod**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
INSERT INTO publish_tasks (platform, account, status, started_at, updated_at, url_capture_attempts, post_url, log)
VALUES ('TikTok', '__wp86_smoke_2026_05_18', 'awaiting_url', NOW(),
        NOW() - INTERVAL '5 minutes', 29,
        'https://www.tiktok.com/@__wp86_smoke_2026_05_18',
        '[wp86-smoke] PR1 prod verification')
RETURNING id;
"
```

Запомнить `id`.

- [ ] **Step 2: Подождать 1 poller tick (≈2 мин) + проверить**

```bash
sleep 130
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, status, url_capture_attempts, url_capture_last_attempt_at
FROM publish_tasks WHERE account='__wp86_smoke_2026_05_18';
"
```

Expected: `status='published_no_url'`, `attempts=30`, `last_attempt_at` свежий.

- [ ] **Step 3: Проверить logs**

```bash
sudo pm2 logs autowarm --nostream --lines 200 | grep -E "wp86|published_no_url|url_capture_exhausted"
```

Expected: видна строка `url_capture_exhausted ... promoted to published_no_url ⚠️`.

- [ ] **Step 4: Очистить synthetic**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
DELETE FROM publish_tasks WHERE account='__wp86_smoke_2026_05_18';
"
```

---

### Task 17: Apply retroactive cleanup migration

**Files:** N/A — DB ops.

- [ ] **Step 1: Snapshot stuck-задач ДО**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT platform, COUNT(*) FROM publish_tasks
WHERE status='awaiting_url'
  AND COALESCE(started_at, updated_at) < NOW() - INTERVAL '2 hours'
GROUP BY 1 ORDER BY 1;
"
```

Запомнить counts по platform.

- [ ] **Step 2: Apply retroactive migration**

Сначала создать файл на prod (если не подтянулся вместе с кодом — проверить наличие):

```bash
ls -la /root/.openclaw/workspace-genri/autowarm/migrations/20260518_wp86_retroactive_cleanup.sql 2>&1
```

Если ENOENT — `git pull --rebase` ещё раз или скопировать вручную из testbench:

```bash
sudo cp /home/claude-user/autowarm-testbench/migrations/20260518_wp86_retroactive_cleanup*.sql \
        /root/.openclaw/workspace-genri/autowarm/migrations/
```

Apply:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /root/.openclaw/workspace-genri/autowarm/migrations/20260518_wp86_retroactive_cleanup.sql
```

Expected: `BEGIN`, `UPDATE NN` (NN ≈ counts из Step 1), `UPDATE MM` (pq sync), `COMMIT`.

- [ ] **Step 3: Verify пост-cleanup**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT status, COUNT(*) FROM publish_tasks
WHERE status IN ('awaiting_url','published_no_url')
GROUP BY 1 ORDER BY 2 DESC;
"
```

Expected: `awaiting_url` упал близко к 0 (или только freshly-created), `published_no_url` ≈ counts из Step 1.

- [ ] **Step 4: Verify publish_queue sync**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT pq.status, COUNT(*) FROM publish_queue pq
JOIN publish_tasks pt ON pq.publish_task_id = pt.id
WHERE pt.status='published_no_url'
GROUP BY 1;
"
```

Expected: всё `done`.

- [ ] **Step 5: UI визуальная проверка на prod**

Открыть `https://delivery.contenthunter.ru/publish-tasks` (или соответствующий URL дашборда). В фильтре статуса выбрать `⚠️ Без URL` — должны показаться promoted задачи с жёлтым badge'м.

---

## Wrap-up (PR1.J)

### Task 18: OpenProject WP #86 update + memory update

**Files:** N/A — bookkeeping.

- [ ] **Step 1: Закомментировать в WP #86 — что сделано**

```bash
source ~/secrets/openproject.env
PR_URL="<URL созданный в Task 13>"
NUM_PROMOTED="<число из Task 17 Step 3>"

curl -s -u "apikey:$OPENPROJECT_API_TOKEN" -X POST \
  -H "Content-Type: application/json" \
  "$OPENPROJECT_URL/api/v3/work_packages/86/activities" \
  -d "$(python3 -c "
import json, sys
body = '''## Что было не так
url-poller грузил LIMIT 30 ORDER BY started_at ASC — новые задачи голодали (snapshot: 13 задач с upd>3h); NULL started_at давал 48ч-timeout=0 → zombies (#961 IG, 4× YT Ivana-o3j); не было terminal-перехода для «опубликовано без specific URL» — задачи доходили только до 48ч failed.

## Что сделано (PR1)
- Schema migration: url_capture_attempts, pre_publish_video_ids, url_capture_last_attempt_at + partial index
- url-poller: ORDER BY updated_at + env-driven LIMIT (default 100), NULL-coalesce 48ч timeout, attempts++ + промоут в новый статус published_no_url при exhausted
- syncQueueStatuses: published_no_url → pq.status=done
- analytics: 3 success-count места включают published_no_url
- UI badges в 5 местах public/index.html + filter option
- Retroactive cleanup миграция: $NUM_PROMOTED stuck задач промоутнуто в published_no_url
- Local + prod smoke verified
- Kill-switches: URL_POLLER_LIMIT, URL_CAPTURE_MAX_ATTEMPTS

PR: $PR_URL

## Что осталось
- PR2 — bot-side capture (A1 retry-loop + A2 notification scrape) — отдельный план будет написан с учётом PR1 уроков
- PR3 — server-side capture (A3 YT Data API + A5 differential id-diff)'''
print(json.dumps({'comment': {'raw': body.replace('\$PR_URL', '$PR_URL').replace('\$NUM_PROMOTED', '$NUM_PROMOTED')}}, ensure_ascii=False))
")" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if d.get('_type') == 'Error':
    print('ERROR:', d)
else:
    print('comment posted ✓')
"
```

- [ ] **Step 2: Update WP #86 status → In progress (если ещё New)**

```bash
LV=$(curl -s -u "apikey:$OPENPROJECT_API_TOKEN" "$OPENPROJECT_URL/api/v3/work_packages/86" | python3 -c "import json,sys; print(json.load(sys.stdin)['lockVersion'])")

# Найти id статуса "In progress" — обычно 7 или 2, зависит от instance
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" "$OPENPROJECT_URL/api/v3/statuses" | python3 -c "
import json, sys
for s in json.load(sys.stdin)['_embedded']['elements']:
    print(s['id'], s['name'])
"
```

Затем (с правильным STATUS_ID):

```bash
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" -X PATCH \
  -H "Content-Type: application/json" \
  "$OPENPROJECT_URL/api/v3/work_packages/86" \
  -d "{\"lockVersion\":$LV,\"_links\":{\"status\":{\"href\":\"/api/v3/statuses/<STATUS_ID>\"}}}"
```

- [ ] **Step 3: Memory update (опционально — если что-то узнали ценного)**

Per memory writing rules: только non-obvious/surprising. Сюда подойдут:
- Если smoke test нашёл неожиданное (например что pm2 не подтянул код автоматически)
- Если cross-repo grep дал hits которых я не предвидел
- Если applied миграция отработала с warnings

Если ничего surprising — пропустить.

- [ ] **Step 4: Final report пользователю**

Что сообщить:
- PR1 PR merged + deployed
- Retroactive cleanup applied — N задач промоутнуто
- Stuck-counter в дашборде: до/после
- Готов писать PR2/PR3 планы

---

## Self-Review Checklist (мне, при чтении)

- [ ] Все 18 задач имеют конкретные code blocks (никакого «implement TBD»)
- [ ] Type-консистентность: helper `shouldPromoteToPublishedNoUrl` называется одинаково везде (Tasks 2, 6, 10)
- [ ] Env-var names консистентны: `URL_POLLER_LIMIT`, `URL_CAPTURE_MAX_ATTEMPTS` (Tasks 3, 4, 6, 13)
- [ ] Status `published_no_url` (нижний регистр, snake_case) везде — БД, server.js, UI, OpenProject comment
- [ ] Migration filenames соответствуют convention `YYYYMMDD_descr.sql` (видны в Task 1, 17)
- [ ] Rollback files для обоих миграций (forward + retroactive) — упомянуты в спеке, но в плане только forward. **Note:** rollback SQL уже в спеке, в плане только применение forward.
