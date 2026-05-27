# WP #140 — Классификатор error-кодов (`publish_error_codes`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить ~35 реальных прод-кодов падений в справочник `publish_error_codes` с корректным `error_class`, чтобы движок ретраев WP#108 маршрутизировал их осознанно (UI → сразу в ручную; транзиентные → ретраи→handoff), и ни один прод-код не дефолтился в `unknown` из-за отсутствия в каталоге.

**Architecture:** Чистое изменение данных справочника + перекласовка ещё-в-полёте задач. Одна forward-миграция (`INSERT ... ON CONFLICT` + scoped backfill через CTE `INSERT ... RETURNING`) и парный rollback. Поведение движка (`retry_decision.js`) НЕ меняется — он уже различает STRUCTURAL (`ui_changed`/`banned` → handoff сразу) и TRANSIENT (`network`/`unknown` → ретраи, окно 2 дня). `severity`/`retry_strategy` — описательные (движок их не читает), заполняем по паттерну существующих строк.

**Tech Stack:** PostgreSQL (`openclaw@localhost`), SQL-миграции в `<autowarm-repo>/migrations/`, тесты `node --test` (`pg.Pool`, транзакция с ROLLBACK — без мутации прода).

**Спека:** `docs/superpowers/specs/2026-05-27-wp140-error-class-catalog-design.md`.
**Репозиторий кода:** autowarm `GenGo2/delivery-contenthunter`. Тестбенч: `/home/claude-user/autowarm-testbench/` (origin = тот же delivery-репо; post-commit hook авто-пушит ветку). Прод: `/root/.openclaw/workspace-genri/autowarm/` (ветка `main`, pm2 id=1).

---

## Pre-task: изолированный воркспейс (выполнить ПЕРЕД Task 1)

Реализация идёт в репозитории autowarm (тестбенч), НЕ в `contenthunter`. Создать рабочую ветку/worktree в тестбенче (REQUIRED SUB-SKILL: superpowers:using-git-worktrees):

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add ../autowarm-wp140 -b wp140-error-class-catalog origin/main
cd /home/claude-user/autowarm-testbench/../autowarm-wp140  # = /home/claude-user/autowarm-wp140
```

Все пути файлов ниже — относительно корня тестбенча (`migrations/`, `test_*.test.js` в корне). Работать в worktree `/home/claude-user/autowarm-wp140`.

⚠️ БД `openclaw@localhost` — **живой прод**. Все проверки выполнять в транзакции с `ROLLBACK` (паттерн уже в `test_client_publish_id.test.js`). Реальный апплай — только в Task 4 после отмашки Данила.

---

## Task 1: Forward-миграция + интеграционный тест (TDD)

**Files:**
- Create: `test_wp140_error_class_catalog.test.js` (корень тестбенча)
- Create: `migrations/20260527_wp140_error_class_catalog.sql`

- [ ] **Step 1: Написать падающий тест**

Файл `test_wp140_error_class_catalog.test.js`:

```js
// Run: node --test --test-force-exit test_wp140_error_class_catalog.test.js
//
// WP #140: справочник publish_error_codes покрывает все прод-коды, миграция
// классифицирует их корректно и backfill перекласовывает in-flight задачи.
// Миграция применяется ВНУТРИ транзакции с ROLLBACK — прод не мутируется
// (урок live-DB инцидента WP#108/#147).
const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { Pool } = require('pg');

const pool = new Pool({ host: 'localhost', user: 'openclaw', password: 'openclaw123', database: 'openclaw' });
after(async () => { await pool.end(); });

const MIGRATION = path.join(__dirname, 'migrations', '20260527_wp140_error_class_catalog.sql');

// Ожидаемая классификация — независимая кодировка намерения спеки (НЕ копия миграции).
const EXPECTED = {
  yt_editor_not_reached: 'ui_changed',
  ig_share_tap_no_progress: 'ui_changed',
  ig_account_switcher_wrong_foreground: 'ui_changed',
  tt_account_not_in_list: 'ui_changed',
  yt_app_not_foregrounded: 'ui_changed',
  ig_gallery_no_video_candidate: 'ui_changed',
  tt_post_switch_verify_unrecoverable: 'ui_changed',
  yt_picker_dismissed: 'ui_changed',
  ig_caption_screen_not_reached: 'ui_changed',
  tt_account_menu_unknown_layout: 'ui_changed',
  yt_picker_target_absent: 'ui_changed',
  ig_app_not_foregrounded: 'ui_changed',
  anchor_not_found: 'ui_changed',
  ig_gallery_button_not_found: 'ui_changed',
  tt_drawer_tap_did_not_open_sheet: 'ui_changed',
  tt_stories_back_failed: 'ui_changed',
  ig_editor_falsely_detected_as_gallery: 'ui_changed',
  yt_gallery_no_video_candidate: 'ui_changed',
  tt_app_not_foregrounded: 'ui_changed',
  tt_post_switch_renav_failed: 'ui_changed',
  ig_external_app_foreground: 'ui_changed',
  yt_post_switch_app_not_foregrounded: 'ui_changed',
  yt_foreign_foreground_unrecoverable: 'ui_changed',
  tt_perm_dialog_stuck: 'ui_changed',
  phone_or_email_link_required: 'banned',
  tt_logged_out: 'banned',
  watchdog_subprocess_hang: 'network',
  timeout: 'network',
  switch_failed_unspecified: 'unknown',
  media_store_unreadable_pre_publish: 'unknown',
  date_mismatch: 'unknown',
  mediastore_top_mismatch: 'unknown',
  not_first_in_video: 'unknown',
  manual_smoke_abort: 'unknown',
  orphaned_no_events: 'unknown',
};

// Снять обёртку BEGIN;/COMMIT; — выполняем тело внутри тест-транзакции.
function migrationBody() {
  const raw = fs.readFileSync(MIGRATION, 'utf8');
  return raw.replace(/^\s*BEGIN;\s*/i, '').replace(/\s*COMMIT;\s*$/i, '');
}

test('wp140: миграция классифицирует прод-коды, не оставляет дыр и backfill-ит in-flight (rollback)', async () => {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query(migrationBody());

    // 1) каждый код имеет ожидаемый error_class
    const codes = Object.keys(EXPECTED);
    const { rows } = await client.query(
      'SELECT code, error_class FROM publish_error_codes WHERE code = ANY($1)', [codes]);
    const got = Object.fromEntries(rows.map(r => [r.code, r.error_class]));
    for (const code of codes) {
      assert.equal(got[code], EXPECTED[code], `error_class для ${code}`);
    }

    // 2) ни один прод-код (30д) не отсутствует в каталоге
    const { rows: missing } = await client.query(`
      SELECT DISTINCT pt.error_code
      FROM publish_tasks pt
      WHERE pt.status IN ('failed','preflight_failed')
        AND pt.created_at >= now() - interval '30 days'
        AND COALESCE(pt.error_code,'') NOT IN ('','process_interrupted')
        AND NOT EXISTS (SELECT 1 FROM publish_error_codes ec WHERE ec.code = pt.error_code)`);
    assert.equal(missing.length, 0,
      'остались некаталогизированные прод-коды: ' + missing.map(r => r.error_code).join(','));

    // 3) backfill: ни одна in-flight (не отданная в ручную) упавшая задача с этими кодами
    //    не осталась со stale error_class
    const { rows: stale } = await client.query(`
      SELECT count(*)::int AS n
      FROM publish_tasks pt
      JOIN publish_queue pq ON pq.publish_task_id = pt.id
      WHERE pt.status IN ('failed','preflight_failed')
        AND pq.manual_handoff_at IS NULL
        AND pt.error_code = ANY($1)
        AND pt.error_class IS DISTINCT FROM
            (SELECT ec.error_class FROM publish_error_codes ec WHERE ec.code = pt.error_code)`,
      [codes]);
    assert.equal(stale[0].n, 0, 'backfill не покрыл часть in-flight задач');
  } finally {
    await client.query('ROLLBACK');
    client.release();
  }
});
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-wp140 && node --test --test-force-exit test_wp140_error_class_catalog.test.js`
Expected: FAIL — `ENOENT ... 20260527_wp140_error_class_catalog.sql` (файл миграции ещё не создан).

- [ ] **Step 3: Написать миграцию**

Файл `migrations/20260527_wp140_error_class_catalog.sql`:

```sql
-- WP #140: недостающие прод-коды падений → publish_error_codes (error_class).
-- error_class управляет движком ретраев (WP#108): ui_changed/banned → сразу в ручную;
-- network/unknown → ретраи, потом handoff после окна 2 дня.
-- severity/retry_strategy — описательные (движок их не читает), по паттерну каталога.
-- Идемпотентно: ON CONFLICT (code) DO UPDATE.
BEGIN;

WITH upsert AS (
  INSERT INTO publish_error_codes
    (code, error_class, severity, retry_strategy, is_known, is_auto_fixable, description)
  VALUES
    -- ui_changed (UI-навигация: экран/пикер/фокус/anchor) → сразу в ручную
    ('yt_editor_not_reached','ui_changed','error','manual',true,false,'Редактор YouTube не достигнут'),
    ('ig_share_tap_no_progress','ui_changed','error','manual',true,false,'Тап Share в Instagram без прогресса'),
    ('ig_account_switcher_wrong_foreground','ui_changed','error','manual',true,false,'Чужой foreground при переключении аккаунта IG'),
    ('tt_account_not_in_list','ui_changed','error','manual',true,false,'Целевой аккаунт TikTok не найден в списке переключателя'),
    ('yt_app_not_foregrounded','ui_changed','error','manual',true,false,'YouTube не на переднем плане'),
    ('ig_gallery_no_video_candidate','ui_changed','error','manual',true,false,'В галерее IG нет кандидата-видео'),
    ('tt_post_switch_verify_unrecoverable','ui_changed','error','manual',true,false,'Проверка после переключения TikTok невосстановима'),
    ('yt_picker_dismissed','ui_changed','error','manual',true,false,'Пикер аккаунта YouTube закрылся'),
    ('ig_caption_screen_not_reached','ui_changed','error','manual',true,false,'Экран подписи IG не достигнут'),
    ('tt_account_menu_unknown_layout','ui_changed','error','manual',true,false,'Неизвестный layout меню аккаунта TikTok'),
    ('yt_picker_target_absent','ui_changed','error','manual',true,false,'Целевой аккаунт отсутствует в пикере YouTube'),
    ('ig_app_not_foregrounded','ui_changed','error','manual',true,false,'Instagram не на переднем плане'),
    ('anchor_not_found','ui_changed','error','manual',true,false,'UI-anchor не найден в переключателе аккаунтов'),
    ('ig_gallery_button_not_found','ui_changed','error','manual',true,false,'Кнопка галереи IG не найдена'),
    ('tt_drawer_tap_did_not_open_sheet','ui_changed','error','manual',true,false,'Тап по drawer TikTok не открыл sheet'),
    ('tt_stories_back_failed','ui_changed','error','manual',true,false,'Возврат из Stories TikTok не удался'),
    ('ig_editor_falsely_detected_as_gallery','ui_changed','error','manual',true,false,'Редактор IG ошибочно принят за галерею'),
    ('yt_gallery_no_video_candidate','ui_changed','error','manual',true,false,'В галерее YouTube нет кандидата-видео'),
    ('tt_app_not_foregrounded','ui_changed','error','manual',true,false,'TikTok не на переднем плане'),
    ('tt_post_switch_renav_failed','ui_changed','error','manual',true,false,'Ренавигация после переключения TikTok не удалась'),
    ('ig_external_app_foreground','ui_changed','error','manual',true,false,'Стороннее приложение на переднем плане (IG)'),
    ('yt_post_switch_app_not_foregrounded','ui_changed','error','manual',true,false,'YouTube не на переднем плане после переключения'),
    ('yt_foreign_foreground_unrecoverable','ui_changed','error','manual',true,false,'Чужой foreground YouTube невосстановим'),
    ('tt_perm_dialog_stuck','ui_changed','error','manual',true,false,'Диалог разрешений TikTok завис'),
    -- banned (аккаунт требует ручного вмешательства) → сразу в ручную
    ('phone_or_email_link_required','banned','critical','manual',true,false,'Аккаунт требует привязки телефона/почты («Необходимо обновить аккаунт»)'),
    ('tt_logged_out','banned','critical','manual',true,false,'Выход из аккаунта TikTok — нужен ручной вход'),
    -- network (инфра/таймаут) → ретраи
    ('watchdog_subprocess_hang','network','warn','none',true,false,'Watchdog убил зависший subprocess (инфра)'),
    ('timeout','network','error','backoff',true,false,'Дженерик-таймаут операции'),
    -- unknown (микс/контент-верификация) → ретраи, потом handoff после окна
    ('switch_failed_unspecified','unknown','error','backoff',true,false,'Переключение аккаунта упало, конкретный шаг не определён (catch-all)'),
    ('media_store_unreadable_pre_publish','unknown','error','backoff',true,false,'MediaStore нечитаем на префлайте (re-push может починить)'),
    ('date_mismatch','unknown','error','backoff',true,false,'Дата ролика в пикере расходится с push-таймстампом'),
    ('mediastore_top_mismatch','unknown','error','backoff',true,false,'Top-1 MediaStore не совпадает с ожидаемым файлом'),
    ('not_first_in_video','unknown','error','backoff',true,false,'Целевое видео не первое в списке'),
    ('manual_smoke_abort','unknown','info','none',true,false,'Артефакт ручного смок-теста (не реальное падение)'),
    ('orphaned_no_events','unknown','info','none',true,false,'Задача без событий (артефакт)')
  ON CONFLICT (code) DO UPDATE SET
    error_class    = EXCLUDED.error_class,
    severity       = EXCLUDED.severity,
    retry_strategy = EXCLUDED.retry_strategy,
    is_known       = EXCLUDED.is_known,
    description    = EXCLUDED.description
  RETURNING code, error_class
)
-- Scoped backfill: перекласовать ещё-в-полёте упавшие задачи (НЕ отданные в ручную),
-- чтобы фикс заработал немедленно. Скоуп = ровно коды этой миграции (через RETURNING upsert).
-- manual_handoff_at IS NULL: не трогаем завершённые хэндофы (иначе перепишем леджер).
UPDATE publish_tasks pt
SET error_class = u.error_class
FROM upsert u, publish_queue pq
WHERE u.code = pt.error_code
  AND pq.publish_task_id = pt.id
  AND pt.status IN ('failed','preflight_failed')
  AND pq.manual_handoff_at IS NULL
  AND pt.error_class IS DISTINCT FROM u.error_class;

COMMIT;
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd /home/claude-user/autowarm-wp140 && node --test --test-force-exit test_wp140_error_class_catalog.test.js`
Expected: PASS (1 test). Прод не изменён (миграция применялась в транзакции с ROLLBACK).
Если остались висящие процессы: `pkill -f "test_wp140_error_class_catalog.test.js"` (урок stale-node-процессов).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-wp140
git add migrations/20260527_wp140_error_class_catalog.sql test_wp140_error_class_catalog.test.js
git commit -m "feat(wp140): forward-миграция publish_error_codes + интеграционный тест

35 прод-кодов → error_class (ui_changed/banned/network/unknown) + scoped
backfill in-flight задач через CTE INSERT...RETURNING. Тест применяет
миграцию в транзакции с ROLLBACK (без мутации прода).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Rollback-миграция + проверка обратимости

**Files:**
- Create: `migrations/20260527_wp140_error_class_catalog__rollback.sql`
- Modify: `test_wp140_error_class_catalog.test.js` (добавить тест обратимости)

- [ ] **Step 1: Написать падающий тест обратимости**

Добавить в `test_wp140_error_class_catalog.test.js` (после первого `test(...)`):

```js
const ROLLBACK = path.join(__dirname, 'migrations', '20260527_wp140_error_class_catalog__rollback.sql');
function rollbackBody() {
  const raw = fs.readFileSync(ROLLBACK, 'utf8');
  return raw.replace(/^\s*BEGIN;\s*/i, '').replace(/\s*COMMIT;\s*$/i, '');
}

test('wp140: rollback убирает добавленные коды, прочий каталог цел (rollback-txn)', async () => {
  const codes = Object.keys(EXPECTED);
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    // Нормализуем старт внутри транзакции (откатится): убираем 35 кодов, чтобы тест был
    // робастен к пост-деплой состоянию, где коды уже в каталоге (ON CONFLICT их не «добавит»).
    await client.query('DELETE FROM publish_error_codes WHERE code = ANY($1)', [codes]);
    const othersBefore = (await client.query(
      'SELECT count(*)::int n FROM publish_error_codes WHERE NOT (code = ANY($1))', [codes])).rows[0].n;

    await client.query(migrationBody());
    const present = (await client.query(
      'SELECT count(*)::int n FROM publish_error_codes WHERE code = ANY($1)', [codes])).rows[0].n;
    assert.equal(present, codes.length, 'после миграции присутствуют все 35 кодов');

    await client.query(rollbackBody());
    const leftover = (await client.query(
      'SELECT count(*)::int n FROM publish_error_codes WHERE code = ANY($1)', [codes])).rows[0].n;
    assert.equal(leftover, 0, 'после rollback добавленных кодов нет');

    const othersAfter = (await client.query(
      'SELECT count(*)::int n FROM publish_error_codes WHERE NOT (code = ANY($1))', [codes])).rows[0].n;
    assert.equal(othersAfter, othersBefore, 'rollback не тронул прочие строки каталога');
  } finally {
    await client.query('ROLLBACK');
    client.release();
  }
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/autowarm-wp140 && node --test --test-force-exit test_wp140_error_class_catalog.test.js`
Expected: FAIL — `ENOENT ... __rollback.sql` (второй тест), первый тест PASS.

- [ ] **Step 3: Написать rollback**

Файл `migrations/20260527_wp140_error_class_catalog__rollback.sql`:

```sql
-- Откат WP #140. ПРЕДУСЛОВИЕ: все 35 кодов на момент деплоя отсутствовали в каталоге
-- (проверено прод-выгрузкой; БД одна — openclaw@localhost, отдельных клонов каталога нет),
-- поэтому DELETE удаляет ровно строки, созданные forward-миграцией, и не трогает чужих.
-- Если запускать в среде, где часть кодов уже была — сверить перечень перед откатом.
-- Backfill publish_tasks.error_class НЕОБРАТИМ по дизайну (правка денормализованной
-- копии-леджера; так же необратим backfill WP#108).
BEGIN;

DELETE FROM publish_error_codes WHERE code IN (
  'yt_editor_not_reached','ig_share_tap_no_progress','ig_account_switcher_wrong_foreground',
  'tt_account_not_in_list','yt_app_not_foregrounded','ig_gallery_no_video_candidate',
  'tt_post_switch_verify_unrecoverable','yt_picker_dismissed','ig_caption_screen_not_reached',
  'tt_account_menu_unknown_layout','yt_picker_target_absent','ig_app_not_foregrounded',
  'anchor_not_found','ig_gallery_button_not_found','tt_drawer_tap_did_not_open_sheet',
  'tt_stories_back_failed','ig_editor_falsely_detected_as_gallery','yt_gallery_no_video_candidate',
  'tt_app_not_foregrounded','tt_post_switch_renav_failed','ig_external_app_foreground',
  'yt_post_switch_app_not_foregrounded','yt_foreign_foreground_unrecoverable','tt_perm_dialog_stuck',
  'phone_or_email_link_required','tt_logged_out',
  'watchdog_subprocess_hang','timeout',
  'switch_failed_unspecified','media_store_unreadable_pre_publish','date_mismatch',
  'mediastore_top_mismatch','not_first_in_video','manual_smoke_abort','orphaned_no_events'
);

COMMIT;
```

- [ ] **Step 4: Запустить — убедиться, что оба теста проходят**

Run: `cd /home/claude-user/autowarm-wp140 && node --test --test-force-exit test_wp140_error_class_catalog.test.js`
Expected: PASS (2 tests).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/autowarm-wp140
git add migrations/20260527_wp140_error_class_catalog__rollback.sql test_wp140_error_class_catalog.test.js
git commit -m "feat(wp140): rollback-миграция + тест обратимости

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Антирегресс движка + ревью

**Files:** (только запуск, без правок)
- `test_retry_decision.test.js`

- [ ] **Step 1: Прогнать существующие тесты решения о ретрае**

Движок не менялся, но классификация — это контракт с ним. Подтвердить, что семантика STRUCTURAL/TRANSIENT цела.

Run: `cd /home/claude-user/autowarm-wp140 && node --test --test-force-exit test_retry_decision.test.js`
Expected: PASS (все кейсы). Если файла нет под этим именем — найти: `ls test_retry*.test.js`.

- [ ] **Step 2: Codex-ревью диффа**

```bash
cd /home/claude-user/autowarm-wp140
git diff origin/main...HEAD | ~/.local/bin/codex review -
```
Expected: 0 P1. P2/P3 — починить инлайн и амендить соответствующий коммит, повторять до 0 P1.

- [ ] **Step 3: Пуш ветки + PR**

```bash
cd /home/claude-user/autowarm-wp140
git push -u origin wp140-error-class-catalog   # post-commit hook мог уже запушить — не страшно
gh pr create --repo GenGo2/delivery-contenthunter --base main \
  --title "WP #140: классификатор error-кодов publish_error_codes" \
  --body "Добавляет 35 прод-кодов в справочник classификации + scoped backfill in-flight задач. Спека/план: contenthunter docs/superpowers (2026-05-27-wp140). Миграция идемпотентна (ON CONFLICT), rollback прилагается.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Task 4: Деплой на прод (⚠️ требует отмашки Данила — правка живых данных)

Применение миграции = реальный `INSERT` в каталог + backfill ~23 in-flight задач. Выполнять ТОЛЬКО после явного согласия и (обычно) merge PR.

- [ ] **Step 1: Дождаться merge PR в `main`** (или явного «деплой» от Данила).

- [ ] **Step 2: Подтянуть код на проде**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git pull --ff-only origin main
```
(или из текущего деплой-флоу autowarm; pm2 id=1.)

- [ ] **Step 3: Применить миграцию на проде**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /root/.openclaw/workspace-genri/autowarm/migrations/20260527_wp140_error_class_catalog.sql
```
Expected: `INSERT 0 35` (или строка про upsert) + `UPDATE <n>` (backfill, ~23) + `COMMIT`.

- [ ] **Step 4: Пост-проверка инварианта (READ-ONLY)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -At -c "
SELECT count(*) AS missing FROM publish_tasks pt
WHERE pt.status IN ('failed','preflight_failed')
  AND pt.created_at >= now()-interval '30 days'
  AND COALESCE(pt.error_code,'') NOT IN ('','process_interrupted')
  AND NOT EXISTS (SELECT 1 FROM publish_error_codes ec WHERE ec.code=pt.error_code);"
```
Expected: `0`. (Перезапуск НЕ нужен: публикатор читает каталог живым SQL на каждом падении; контроллер читает уже-материализованный `pt.error_class`.)

- [ ] **Step 5: Наблюдение (1–2 дня)**

В логах retry-контроллера UI-падения (`yt_*`/`ig_*`/`tt_*`) дают `structural_error` (сразу handoff), а не `requeue`. Транзиентные (`switch_failed_unspecified` и др.) — `transient_within_limits`, и при исчерпании окна — `window_exhausted` → handoff. Откат при проблеме: `psql -f ..._rollback.sql`.

- [ ] **Step 6: Обновить OpenProject #140** — статус → «Тестирование» (id 9), комментарий в house-style (Что было не так → Что сделано → Что осталось, без подписи).

---

## Self-Review (выполнено автором плана)

- **Покрытие спеки:** §4 решения → Task 1 (классификация в VALUES); §5 таблица 35 кодов → Task 1 INSERT (сверено: 24 ui_changed + 2 banned + 2 network + 7 unknown = 35); §6 миграция+backfill+rollback → Task 1+2; §7 acceptance №1/№2 → тест Step «invariant»; §8 верификация (юнит/миграц-смок/rollback-смок/прод-наблюдение) → Task 3 Step 1 + Task 1/2 тесты + Task 4 Step 4-5; §9 открытые заметки → вынесены в #166 (вне скоупа).
- **Плейсхолдеры:** нет — весь SQL и JS приведён полностью.
- **Консистентность типов:** `EXPECTED` (тест) ↔ `VALUES` (миграция) ↔ rollback `IN (...)` — один и тот же набор из 35 кодов и классов; тест независимо проверяет соответствие.
```
