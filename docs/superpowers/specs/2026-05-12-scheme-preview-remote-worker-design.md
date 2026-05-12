# Scheme preview generation — миграция на remote unic-worker

**Date:** 2026-05-12
**Status:** Design — under review
**Author:** Claude (interactive с Danil_Pavlov)
**Trigger:** инцидент 2026-05-12 — фронт показал «Ошибка» в `/admin/users` пока ffmpeg рендерил scheme preview на validator backend и блокировал event loop. Hot-fix `asyncio.to_thread` merged PR #6 (`fix(schemes): non-blocking ffmpeg в _run_generation`). Архитектурное решение — вынести все ffmpeg-задачи на dedicated remote worker.

## Goal

Перенести scheme preview generation из FastAPI background-task в validator backend на существующий unic-worker (PM2 process на 91.98.180.103, который уже обрабатывает финальную уникализацию через `unic_tasks`). Сделать это паттерном для будущих ffmpeg-задач (OCR, transcription, video metadata).

## Non-goals

- Не мигрируем OCR/transcription/video_metadata в этом spec (separate follow-up'ы по тому же паттерну).
- Не делаем UI cancel для активной генерации.
- Не реализуем horizontal scale-out нескольких worker-нод (architectural разрешено через `FOR UPDATE SKIP LOCKED`, но не deploy'им второй worker).
- Не трогаем frontend `e.response?.data?.detail || 'Ошибка'` паттерн (отдельный backlog-PR).

## Motivation

1. **Разгрузить validator VPS.** ffmpeg съедает CPU/RAM/IO на том же хосте где работает API → блокирует event loop при sync вызове → пользователи видят generic «Ошибка» в любых модалках. После миграции validator не запускает ffmpeg вообще для scheme preview.
2. **Единый source-of-truth для ffmpeg formula.** `generate_ffmpeg` в `worker.py:177` и `_build_ffmpeg_cmd` в `validator/schemes.py:382` — продублированный код. Worker'ская версия станет канонической.
3. **Reliability.** Текущий in-memory `_generation_status` + `BackgroundTasks.add_task` теряет всё при `pm2 restart validator`. БД-queue переживёт любые рестарты.
4. **Foundation для будущих ffmpeg-задач.** Same pattern → next migration trivial.

---

## Architecture

```
                ┌──────────────────────────┐
  Manager UI ──▶│   validator backend      │
  (схемы)       │   (FastAPI на VPS)       │
                │                          │
                │   POST /api/schemes/     │
                │   {id}/generate-previews │
                └────────────┬─────────────┘
                             │
                             │ INSERT unic_tasks (task_type='scheme_preview', payload_hash, ...)
                             ▼
                ┌────────────────────────────────┐
                │  Postgres openclaw on VPS      │◀── shared между validator и worker
                │  unic_tasks (новые колонки)    │
                └────────────────┬───────────────┘
                                 │ polling каждые 3с FOR UPDATE SKIP LOCKED
                                 ▼
                ┌────────────────────────────────┐
                │   unic-worker @ 91.98.180.103  │
                │   (PM2, asyncio, MAX_WORKERS=4)│
                │                                │
                │   dispatch по task_type:       │
                │     'unic'           ──▶ process_task (legacy)
                │     'scheme_preview' ──▶ process_scheme_preview_task (новое)
                └────────────────┬───────────────┘
                                 │ ffmpeg render → S3 upload
                                 │ INSERT validator_scheme_previews
                                 │ UPDATE unic_tasks (progress)
                                 ▼
                ┌────────────────────────────────┐
                │  S3 (save.gengo.io)            │
                │  scheme-previews/{pid}/{sid}/  │
                └────────────────────────────────┘

  UI poll: GET /api/schemes/{id}/generation-status →
           validator читает свежую unic_tasks WHERE task_type='scheme_preview'
           AND project_id={id} ORDER BY id DESC LIMIT 1 →
           отдаёт {phase, progress, total, error}
```

### Ключевые принципы

- Validator не запускает ffmpeg для scheme preview. Никакого `subprocess.run` в backend для этого pipeline.
- Источник истины статуса — таблица в БД, не in-memory `_generation_status`. Переживает любые рестарты.
- Worker и validator общаются **только через БД**. Никаких HTTP/RPC между ними. Postgres гарантирует ACID и порядок.
- `FOR UPDATE SKIP LOCKED` (как в существующем `get_pending_task`) даёт корректность для multiple worker-instances в будущем.

---

## Components

### `unic-worker/worker.py` (на 91.98.180.103)

**Новое:**

- `process_scheme_preview_task(pool, task)` — структурно как существующий `process_task`, но:
  - читает payload из `task['schemes']` (jsonb) и `task['meta']` (sample_url, logo_url, content_resources)
  - финал пишет в `validator_scheme_previews` (UPSERT по `(scheme_id, project_id)`), не в `unic_content`
  - между схемами обновляет `schemes_done`/`schemes_error`
- Dispatcher branch по `task['task_type']` в main poll loop:
  ```python
  if task['task_type'] == 'scheme_preview':
      await process_scheme_preview_task(pool, task)
  else:
      await process_task(pool, task)  # legacy 'unic'
  ```
- `stale_task_recovery_loop(pool)` — параллельный async-task раз в 5 мин: revert'ит processing-задачи старше 15 мин обратно в pending (с limit 3 revert'ов на task; см. Error handling).

**Что переиспользуется без изменений:**

- `get_pending_task` (1-line патч на расширение ORDER BY если приоритеты появятся в будущем; иначе без изменений)
- `generate_ffmpeg(scheme, files, chromakey_color, output_path)` — точно та же сигнатура, что в validator. Становится каноническим источником.
- `upload_to_s3`, `_pool`, `mark_task_done`, `mark_task_error`
- `_download_file_sync`, `tempfile.mkdtemp` cleanup pattern

### `validator-contenthunter/backend/src/routers/schemes.py`

**Удаляется (~400 строк):**

- `_run_generation` (async background task)
- `_build_ffmpeg_cmd`
- `_download_file` / `_download_file_sync`
- `_s3_upload_with_retry`
- in-memory `_generation_status` dict

**Меняется:**

- `POST /api/schemes/{id}/generate-previews`:
  - Считает `payload_hash = md5(canonical_json({project_id, scheme_ids_sorted, sample_url, logo_url, pattern_url, content_video_ids_sorted}))`
  - В одной транзакции:
    1. Dedup-check: SELECT существующая `pending/processing` с тем же hash. Если есть — RETURN её `task_id` + `joined_existing=true`. UI не различает.
    2. Supersede: UPDATE существующие `pending` строки того же `project_id` (но с другим hash) в `current_status='superseded'`.
    3. INSERT новой строки (с `payload_hash`, `meta={sample_url, logo_url, content_resources}`, `schemes` jsonb, `current_status='pending'`).
    4. RETURN `task_id`, `status='queued'`, `joined_existing=false`, `total=N`.
  - Catch `UniqueViolation` (race condition на partial index) → SELECT existing → return `joined_existing=true`.
- `GET /api/schemes/{id}/generation-status`:
  - SELECT свежей строки `unic_tasks WHERE task_type='scheme_preview' AND project_id=:pid ORDER BY id DESC LIMIT 1`
  - Маппит на тот же contract что UI ждёт сегодня: `{phase, progress, total, error}`
  - `phase` derived: `pending`/`queue_delayed`/`processing`/`done`/`error`/`superseded`
  - `queue_delayed` = `pending AND age(created_at) > 30s` (опционально, для лучшего UX)

**Что не трогаем:**

- Frontend `SchemesPage.vue` — endpoint contract (request body, response shape) сохраняется
- Все остальные routers
- Структура `validator_scheme_previews` (`scheme_id`, `project_id`, `thumb_url`, `video_url`, `generated_at`)

### БД (`openclaw.unic_tasks`)

См. **Schema changes** ниже.

---

## Data flow

### Happy path

1. Manager в `/client/schemes` жмёт «Generate previews» для project_id=53.
2. UI → `POST /api/schemes/53/generate-previews` body: `{logo_url, schemes:[{id,...}], content_resources:{videos, pattern}}`.
3. validator endpoint:
   - validate payload (как сейчас)
   - compute `payload_hash`
   - atomic dedup + supersede + INSERT
   - return `200 {task_id, status:'queued', joined_existing, total:N}`
4. UI начинает polling `GET /api/schemes/53/generation-status` каждые 2 сек:
   - validator: `SELECT * FROM unic_tasks WHERE task_type='scheme_preview' AND project_id=53 ORDER BY id DESC LIMIT 1`
   - returns `{phase:'pending', progress:0, total:N}`
5. Worker poll (параллельно):
   - `UPDATE unic_tasks SET current_status='processing' WHERE id=(SELECT id ... FOR UPDATE SKIP LOCKED) RETURNING *`
   - dispatcher → `process_scheme_preview_task(pool, task)`
6. `process_scheme_preview_task`:
   - download sample/logo/overlays/pattern в `/tmp/unic_worker/preview_{task_id}/`
   - for each scheme:
     - `generate_ffmpeg(...)` → render preview.mp4
     - thumbnail (frame 5)
     - S3 upload: `scheme-previews/{project_id}/{scheme_id}/preview.mp4` + thumb.jpg
     - UPSERT в `validator_scheme_previews`
     - `UPDATE unic_tasks SET schemes_done = i+1, updated_at = NOW()`
   - cleanup tmp/
   - `UPDATE unic_tasks SET current_status='done', updated_at=NOW()`
7. UI poll #N → `{phase:'done', progress:N, total:N}` → UI прекращает polling, обновляет грид.

### Dedup / supersede flow

```
3a. validator endpoint после payload validation:

    payload_hash = md5(canonical_json({
        project_id,
        scheme_ids = sorted([s.id for s in payload.schemes]),
        sample_url, logo_url, pattern_url,
        content_video_ids = sorted([v.id for v in content_resources.videos]),
    }))

3b. atomic в одной транзакции:

    BEGIN;
    SELECT id FROM unic_tasks
      WHERE task_type='scheme_preview'
        AND project_id = :pid
        AND payload_hash = :hash
        AND current_status IN ('pending','processing')
      ORDER BY id DESC LIMIT 1 FOR UPDATE;

    IF FOUND:
        COMMIT;
        RETURN {task_id, status:'queued', joined_existing:true};

    UPDATE unic_tasks
      SET current_status='superseded', updated_at=NOW()
      WHERE task_type='scheme_preview'
        AND project_id = :pid
        AND current_status = 'pending';

    INSERT INTO unic_tasks (..., payload_hash=:hash, ...) RETURNING id;
    COMMIT;
```

Partial unique index (БД-level гарантия даже на ms-race):

```sql
CREATE UNIQUE INDEX uniq_scheme_preview_active_payload
ON unic_tasks (project_id, payload_hash)
WHERE task_type='scheme_preview' AND current_status IN ('pending','processing');
```

### Effect на UI

- Двойной клик → тот же `task_id`, один progress bar.
- Менеджер сменил setup и жмёт ещё раз, пока первая `pending` → старая → `superseded`, новая → `pending`. UI polls «последнюю» → видит новую с progress=0.
- Если первая уже `processing` — она доработает (cancel-on-supersede не в этом scope). Новая встаёт в `pending` рядом. Когда `processing` завершится — старые preview обновятся в `validator_scheme_previews`, потом worker возьмёт новую с актуальным payload и перезапишет.

### S3 bucket decision

Worker сейчас пишет в `1cabe906ea6e-gengo` (beget, public URL `https://save.gengo.io`). Validator/legacy писал в `content-hunter` (default из config). **Решение:** оставляем worker'ский дефолт. До deploy'a (Rollout Phase 1) проверяем `https://save.gengo.io/scheme-previews/.../preview.mp4` открывается с frontend (CORS, mixed-content) — если нет, добавляем в worker env `S3_VALIDATOR_*` credentials и пишем в исходный бакет.

---

## Schema changes

### Миграция `2026-05-12-add-scheme-preview-task-type.sql`

```sql
BEGIN;

ALTER TABLE unic_tasks
  ADD COLUMN task_type   TEXT NOT NULL DEFAULT 'unic'
    CHECK (task_type IN ('unic', 'scheme_preview')),
  ADD COLUMN payload_hash TEXT NULL;

ALTER TABLE unic_tasks
  ALTER COLUMN slot_date DROP NOT NULL;

CREATE UNIQUE INDEX uniq_scheme_preview_active_payload
  ON unic_tasks (project_id, payload_hash)
  WHERE task_type = 'scheme_preview'
    AND current_status IN ('pending', 'processing');

CREATE INDEX idx_unic_tasks_polling
  ON unic_tasks (current_status, id)
  WHERE current_status = 'pending';

CREATE INDEX idx_unic_tasks_project_type
  ON unic_tasks (project_id, task_type, id DESC);

-- Если current_status имеет CHECK constraint — расширить его на 'superseded'.
-- (verified во время миграции через \d+ unic_tasks; на момент design — в БД
--  current_status это plain TEXT без CHECK, поэтому добавление 'superseded'
--  тривиально и не требует ALTER. Если CHECK появится — миграция расширяет.)

COMMIT;
```

### Никаких backfill'ов

- Все 1626 существующих строк → `task_type='unic'` через DEFAULT.
- `payload_hash NULL` для legacy unic-задач — partial index на них не распространяется.

### Cross-repo audit (memory rule `feedback_cross_repo_schema_changes`)

`unic_tasks` пишется/читается в:

- `unic-worker/worker.py` (91.98.180.103)
- `validator-contenthunter/backend/src/routers/schemes.py` (наш VPS)

Перед миграцией обязательно `grep -rn 'unic_tasks' --include="*.py"` через все валидатор/autowarm/contenthunter репо + `sshpass ... ssh root@91.98.180.103 'grep -rn unic_tasks /root/'`. Аудит каждого hit.

### Rollback

```sql
DROP INDEX uniq_scheme_preview_active_payload, idx_unic_tasks_polling, idx_unic_tasks_project_type;
ALTER TABLE unic_tasks DROP COLUMN payload_hash, DROP COLUMN task_type;
-- ALTER TABLE unic_tasks ALTER COLUMN slot_date SET NOT NULL;
-- ← только если все строки до миграции имели non-null slot_date
```

---

## Error handling

| Точка | Симптом | Реакция |
|---|---|---|
| Validator → DB INSERT | Postgres down | endpoint 503 → frontend toast «Сервис недоступен» (стандарт axios.error path) |
| UniqueViolation (dedup race) | Два запроса с одинаковым hash в один миллисек | catch IntegrityError → SELECT existing → return `joined_existing:true` |
| Worker не подхватил за 30 сек | Worker upal/PM2 stopped | Validator при `phase='pending' AND age(created_at) > 30s` возвращает `phase='queue_delayed'`. UI badge «Воркер занят, очередь» |
| Worker подхватил scheme_preview, упал в processing | `task_type='scheme_preview' AND current_status='processing' AND updated_at < NOW() - 15 min` | Watchdog cron на worker'е (5-мин interval): UPDATE обратно в `pending` + revert_count в meta. Limit 3 revert'ов, дальше остаётся processing для расследования. **Только scheme_preview** — legacy unic-задачи watchdog не трогает (одна сложная схема может рендериться >15 мин без обновления `updated_at`; пере-requeue вызвал бы duplicate processing). Для legacy unic — отдельный backlog (heartbeat внутри рендера, либо exclusion как сейчас). |
| ffmpeg returncode != 0 на схеме | Одна из N схем не отрендерилась | meta.scheme_errors[sid] = stderr_tail, продолжает оставшиеся. Финал — `done` если хоть одна успешна, `error` если все упали |
| S3 upload failed | beget недоступен | `upload_to_s3` retry=5 backoff [3,9,15,21,27]s (worker.py:48). После 5 — схема в meta error |
| Source video URL 404 | sample/overlay/logo умерли | `_download_file_sync` retry=3 с backoff. Если не скачалось — `current_status='error'`, error_message = `Failed to download sample video from {url[:80]}` |
| Worker crash прямо на INSERT validator_scheme_previews | повторный pickup после restart → UNIQUE conflict | UPSERT `ON CONFLICT (scheme_id, project_id) DO UPDATE` — идемпотентно |
| Disk full /tmp/unic_worker | ffmpeg падает на write | task error → cleanup через `try/finally tempfile.mkdtemp` |

### Watchdog implementation

```python
async def stale_task_recovery_loop(pool):
    """Каждые 5 минут возвращает в pending задачи processing > 15 мин."""
    while True:
        await asyncio.sleep(300)
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    UPDATE unic_tasks
                       SET current_status='pending',
                           updated_at=NOW(),
                           meta = COALESCE(meta, '{}'::jsonb) || jsonb_build_object(
                             'watchdog_revert_at', NOW()::text,
                             'watchdog_revert_count',
                                COALESCE((meta->>'watchdog_revert_count')::int, 0) + 1
                           )
                     WHERE current_status='processing'
                       AND updated_at < NOW() - INTERVAL '15 minutes'
                       AND task_type = 'scheme_preview'  -- legacy unic исключаем (см. Open Q + Out of scope)
                       AND COALESCE((meta->>'watchdog_revert_count')::int, 0) < 3
                    RETURNING id, task_type, (meta->>'watchdog_revert_count')::int as revert_count
                """)
                for r in rows:
                    logger.warning(
                        f'[watchdog] Reverted stale task id={r["id"]} type={r["task_type"]} '
                        f'(revert_count={r["revert_count"]})'
                    )
        except Exception as e:
            logger.exception(f'[watchdog] loop error: {e}')
```

После 3 revert'ов задача остаётся `processing` — сигнал для ручного расследования. В будущем — TG alert через bugs-bot.

### Алертинг

- `logger.error/warning` от worker'a → `pm2 logs unic-worker`
- Watchdog log line `[watchdog] Reverted stale task id=...` — grep'able сигнал
- Future: TG-нотификация при `watchdog_revert_count >= 3` (не в этом scope)

---

## Testing

### Unit tests (validator/backend, pytest, live-DB через `conftest.py engine.dispose` fixture)

1. **`test_generate_previews_endpoint_inserts_task.py`** — POST → ровно одна строка в `unic_tasks` с `task_type='scheme_preview'`, `current_status='pending'`, валидный `payload_hash` и `meta`. Endpoint вернул 200 с правильным контрактом.
2. **`test_generate_previews_dedup_join.py`** — два подряд POST'a с тем же payload → второй возвращает `joined_existing:true, task_id:X` (тот же id первого). В таблице одна строка.
3. **`test_generate_previews_supersede_pending.py`** — POST A → pending. POST B (другой payload) того же project → A → `superseded`, B → `pending`.
4. **`test_generate_previews_no_supersede_processing.py`** — pre-INSERT processing-строки. POST с другим payload → processing не тронут, новая pending.
5. **`test_generation_status_reads_latest.py`** — 3 строки (superseded, processing, pending). GET → данные pending (последней по id).
6. **`test_payload_hash_canonical.py`** — тот же payload с разным порядком keys/items → тот же hash. Изменение sample_url → другой hash.

### Worker tests (новые, `unic-worker/tests/`)

7. **`test_dispatch_by_task_type.py`** — mock на `process_task`/`process_scheme_preview_task`, dispatcher выбирает правильную ветку.
8. **`test_scheme_preview_pipeline_e2e.py`** — full pipeline с mock-S3 fixtures. INSERT task → run → assert files в mock-S3 + строки в `validator_scheme_previews`.
9. **`test_watchdog_reverts_stale.py`** — INSERT processing-задача `updated_at = NOW() - 20 min`, revert_count=0. Watchdog tick → pending + revert_count=1.
10. **`test_watchdog_skips_after_3_reverts.py`** — revert_count=3, processing 20 min ago. Watchdog не трогает.

### Integration smoke (manual, после deploy)

11. **Live smoke** — manager в UI жмёт «Generate». Проверяем:
    - `SELECT * FROM unic_tasks WHERE task_type='scheme_preview' ORDER BY id DESC LIMIT 1` — есть строка
    - `pm2 logs unic-worker --lines 50` на 91.98.180.103 — видим pickup + render
    - UI показывает progress 0 → ... → done
    - `SELECT video_url FROM validator_scheme_previews WHERE project_id={pid}` — новые записи
    - video_url открывается в браузере
    - Параллельный `curl /api/auth/me` на validator → отвечает мгновенно
12. **Dedup smoke** — два клика подряд. UI один progress bar, в `unic_tasks` одна строка.
13. **Supersede smoke** — клик → клик с другими scheme'ами. Старая `superseded`, новая `pending`.

### Regression checklist

- 1626 legacy unic_tasks продолжают обрабатываться (диспатчер видит `task_type='unic'`).
- Frontend SchemesPage `Generate previews` button → request/response contract unchanged.
- `validator_scheme_previews` schema diff после deploy = empty.
- `https://save.gengo.io/scheme-previews/...` URL'ы воспроизводятся фронтом.

### CI

- Pytest на каждый PR в validator (есть сейчас).
- unic-worker не имел CI — добавляем простой GitHub Actions runner с pytest как часть Rollout Phase 2.

---

## Rollout

### Phase 1: prep + миграция БД (без кода)

1. Cross-repo grep `unic_tasks`. Аудит каждого hit'a (особенно на nullable `slot_date`).
2. Бэкап: `pg_dump --table=unic_tasks openclaw > /tmp/unic_tasks_pre_scheme_preview_$(date +%s).sql`.
3. Применить миграцию (Schema changes).
4. Smoke: `\d unic_tasks` показывает новые колонки + indexes. Legacy unic-worker продолжает работать.

### Phase 2: deploy worker'a

5. Branch `feat/scheme-preview-task-type-20260512` в unic-worker репо.
6. Реализовать `process_scheme_preview_task` + dispatcher + watchdog loop. Pytest зелёный.
7. Codex review (план + diff, raunds до 0 P1).
8. PR → merge.
9. Deploy: `sshpass ... ssh root@91.98.180.103 'cd /root/unic-worker && git pull && pm2 restart unic-worker'`.
10. Smoke: `pm2 logs unic-worker` показывает dispatched task'и, нет ошибок при пустой scheme_preview очереди.

### Phase 3: deploy validator'а

11. Branch `feat/scheme-preview-via-worker-20260512` в validator-contenthunter.
12. Заменить `_run_generation` на DB INSERT; заменить `generation-status` endpoint на DB read. Удалить `_build_ffmpeg_cmd`, `_download_file*`, `_s3_upload_with_retry`, `_generation_status`.
13. Pytest зелёный (тесты 1-6).
14. Codex review.
15. PR → merge → cp в prod path `/root/.openclaw/workspace-genri/validator/backend/src/routers/schemes.py` + `sudo pm2 restart validator`.
16. Live smoke (тесты 11-13).

### Phase 4: cleanup

17. Memory update: новый `project_scheme_preview_remote_worker_shipped.md`.
18. Backlog tickets: OCR/transcription/video_metadata миграция по тому же паттерну.

---

## Out of scope

1. Frontend `e.response?.data?.detail || 'Ошибка'` улучшение — отдельный backlog. С миграцией scheme preview event loop больше не блокируется, axios timeout не возникает.
2. Удаление дублированного ffmpeg-кода из OCR / transcription / video_metadata — следующие миграции на том же паттерне.
3. UI cancel активной processing-task'и.
4. Async cancellation orphan ffmpeg при PM2 restart (codex P2 backlog из PR #6) — теперь не релевантно для scheme preview (рендер не в validator). Legacy unic-pipeline в worker.py остаётся sync subprocess.run, не регрессия.
5. Multi-worker horizontal scale — architecturally разрешено через `FOR UPDATE SKIP LOCKED`, но не deploy'им второй worker.
6. TG-нотификация при watchdog 3-revert — пока только лог.
7. Cancel-on-supersede для `processing` — только pending superseded'ятся.
8. Watchdog для legacy unic-задач — намеренно НЕ включаем в этом spec. Legacy `process_task` может рендерить одну тяжёлую схему >15 мин без heartbeat'а на `updated_at`, и watchdog-revert вызвал бы duplicate processing (P1 от codex review). Чтобы включить watchdog для unic — нужен сначала heartbeat (периодический `UPDATE updated_at=NOW()` каждые ~30s внутри рендера). Отдельный backlog.

---

## Future hooks (не реализуем, но spec их разрешает)

- **Other ffmpeg tasks → unic-worker:** `task_type='ocr'`, `'transcription'`, etc. Каждая — `process_*_task` + dispatcher branch.
- **Per-task priority:** колонка `priority INT DEFAULT 100`, ORDER BY priority DESC, id ASC. Preview приоритет 200 над batch-unic.
- **Backpressure:** при queue depth > 100 endpoint 503 `queue_full`.
- **Per-project rate limit:** уже покрыто supersede-механизмом.

---

## Capacity & SLA

- Нагрузка: ~3-5 scheme_preview/день.
- MAX_WORKERS=4 → spare capacity для preview без замедления unic.
- Latency на одну схему: 2-5 min ffmpeg render + 3s pickup polling. На один task с ~15 схемами **последовательно**: 30-75 min total (как сейчас в validator-side рендере, поведение не регрессирует). Если хотим ускорить — внутри одного task'а параллелить схемы через `asyncio.gather + Semaphore(MAX_WORKERS)` (отдельная оптимизация, не в scope этого spec).
- Worker и validator только через БД, никаких HTTP/RPC — нет network, нет auth, нет race на queue management.

---

## Open questions для review

1. Бакет save.gengo.io vs content-hunter — проверить CORS перед Phase 1 (Section 3 / S3 bucket decision).
2. Index на `(current_status, id) WHERE current_status='pending'` — если PostgreSQL версия < 12, partial indexes могут работать неоптимально. Проверить PG version (текущая prod).
3. Watchdog ставит revert_count в `meta` jsonb — нет structured query, нужно `(meta->>'watchdog_revert_count')::int`. Альтернатива — отдельная колонка `watchdog_revert_count INT DEFAULT 0`. Решить во время implementation.
