# Scheme preview generation → remote unic-worker ✅ shipped 2026-05-12

## Context

Hot-fix PR validator#6 (asyncio.to_thread) закрыл острый инцидент с фронтовым «Ошибка» в /admin/users (см. `2026-05-12-publisher-mediastore-outage-fix.md` и related), но архитектурное решение — вынести ffmpeg-рендер scheme preview на dedicated unic-worker на 91.98.180.103, чтобы validator backend никогда не блокировал event loop ffmpeg-задачами.

## Shipped

3 PR, merged в order:

| PR | Repo | Что |
|---|---|---|
| GenGo2/unic-worker#1 (PR #1, merged 2026-05-12T13:12Z) | unic-worker | worker pipeline: `process_scheme_preview_task` + `dispatch_task` + `heartbeat_loop` + `stale_task_recovery_loop` + per-project guard в `get_pending_task` |
| GenGo2/validator-contenthunter#7 (`d706e42`) | validator | alembic 004: `unic_tasks.task_type/payload_hash`, `slot_date` nullable, `validator_scheme_previews.last_task_id`, partial UNIQUE + polling/lookup indexes, расширенный CHECK constraint |
| GenGo2/validator-contenthunter#8 (`8572cea`) | validator | endpoint rewire: `POST /generate-previews/{pid}` пишет в `unic_tasks` через `enqueue_scheme_preview` (advisory lock + dedup + supersede); `GET /generation-status/{pid}` читает свежую строку с legacy `status` field для frontend backward compat; удалены `_run_generation` + `_build_ffmpeg_cmd` + `_download_file*` + `_s3_upload_with_retry` + `_generation_status` (~400 строк dead code) |

## Defense-in-depth (6 layers)

1. **`compute_payload_hash`** — полные scheme JSON'ы + sample/logo/pattern URLs + content_videos (id + file_path + chromakey_color)
2. **`pg_advisory_xact_lock` per project_id** — сериализует concurrent enqueue
3. **Dedup join по payload_hash** — двойной клик возвращает тот же task_id
4. **Supersede pending'ов** того же project с другим payload
5. **Per-project processing guard** в `get_pending_task` — не подхватывает второй pending пока первый processing
6. **`last_task_id` UPSERT guard** на `validator_scheme_previews` — старший task не перезаписывает свежие previews

## Live UI smoke (2026-05-12 13:51-13:56 UTC)

Имитация UI click через API на real prod project 107 «Еноты по полкам»:

| Шаг | Результат |
|---|---|
| `POST /api/schemes/generate-previews/107` | **HTTP 200 за 43 ms** → task_id=2173, status=queued, total=35 |
| Worker pickup (PM2 unic-worker @ 91.98.180.103) | ~3 sec → status='processing' |
| 3 schemes rendered | 56 sec (~18 sec/scheme) |
| `validator_scheme_previews` UPSERT с `last_task_id=2173` | 3 строки created, `generated_at` свежие |
| HEAD `https://save.gengo.io/scheme-previews/107/1/preview.mp4` | **HTTP/2 200, content-type: video/mp4** ✅ |
| `GET /generation-status/107` shape | `{task_id, status:'running' (legacy), phase:'processing' (new), progress, total, errors}` — frontend compat ✅ |
| **`/api/auth/me` × 3 пока ffmpeg рендерит** | **5-6 ms каждый** — event loop FREE ✅ |
| Финальное состояние (task 2173) | `current_status='done', schemes_done=30, schemes_error=5` |

**Errors=5** — все на legacy garbage в `unic_schemes` (5 строк с `id < 0`, empty label, NULL content_video_index). Pipeline isolation работает: per-scheme error не валит весь task.

**Speed:** ~18 sec на scheme — гораздо быстрее ожидаемых 2-5 min (project 107 не имеет overlay videos в `validator_unic_content` → ffmpeg filter_complex упрощён).

## Главное доказательство

**До миграции:** один scheme preview render блокировал validator event loop на 30-75 минут (sync `subprocess.run` в async background task). Все authenticated endpoints зависали → frontend axios timeout → generic «Ошибка». Это была причина оригинального инцидента с /admin/users.

**После миграции:** validator backend ни разу не запускает ffmpeg для scheme preview. Всё уходит на 91.98.180.103. `/api/auth/me` отвечает за 5-6 ms даже пока worker rendering — подтверждено smoke'ом.

## Codex review rounds

| Pass | Rounds | P1 findings addressed |
|---|---|---|
| Design spec | 3 | NULL hash guard, downgrade slot_date safety, advisory lock concurrency, payload_hash полные fields |
| Alembic 004 | 3 | NULL hash check constraint + downgrade DELETE preview rows |
| unic-worker PR | 2 | Per-project guard concurrency-safe через `pg_try_advisory_xact_lock` L2 |
| Validator PR | 2 | Legacy `status` field для frontend SchemesPage.vue polling + payload_hash includes content_videos full fields |

## Memory

- `project_scheme_preview_remote_worker_shipped.md` — детали + how-to-apply pattern для future ffmpeg-задач

## Backlog (см. `docs/superpowers/plans/BACKLOG.md`)

- Other ffmpeg tasks (OCR, transcription, video_metadata) → same pattern
- Heartbeat для legacy unic-pipeline
- Async cancellation orphan ffmpeg
- TG-notification при watchdog 3-revert
- Frontend timeout-aware error display
- Multi-worker horizontal scale
- Cleanup duplicated phase→status mapping
- Cancel-on-supersede для processing
