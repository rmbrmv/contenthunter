# WP#222 — Счётчик генерации превью схем >100% (41/34) и зависание — SHIPPED+DEPLOYED 2026-06-02

## Симптом

Баг-репорт @Danil_Pavlov_123 (02.06, скриншот): мастер «Схемы уникализации» → шаг «Генерация» → индикатор «Генерация превью…» показывал `41 / 34` = `121 %`, прогресс не завершался, обновление страницы не помогало.

## Корневая причина (по живой БД openclaw, контейнер 172.17.0.3)

Симптом = реальное состояние `unic_tasks`, не глюк отрисовки:

| task_id | project | schemes_total | schemes_done | len(schemes JSON) | watchdog_revert_count |
|---|---|---|---|---|---|
| 3976 | 117 | 34 | **64** | 34 | 0 |
| 3955 | 103 | 4 | **7** | 4 | 0 |

`schemes_done` превышал `schemes_total` (≈×1.8 ≈ почти двойной счёт). Один `scheme_preview`-таск обрабатывался воркером **внахлёст дважды**: `unic-worker` крутит `MAX_WORKERS=2` цикла; `pg_try_advisory_xact_lock(project_id)` в `get_pending_task` держится только на короткой транзакции захвата, а генерация (30–75 мин) идёт под защитой лишь committed-строки `current_status='processing'`. Когда строку снимали в `pending` (`restart_stuck` при старте воркера или watchdog-ревёрт) — второй воркер проходил `NOT EXISTS`-гард и брал таск, пока первый ещё жив → конкурентная обработка → `schemes_done` суммировался выше реального числа схем. Триггеров БД нет.

## Фикс (3 слоя + бэкфилл)

**(а) owner-guard воркера** — `unic-worker/worker.py`. Захват таска (`get_pending_task`) штампует уникальный `owner_run_id` (uuid) в `meta jsonb`; все записи прогресса/финализации гардятся `WHERE id=$1 AND ($N::text IS NULL OR meta->>'owner_run_id' IS NOT DISTINCT FROM $N)`; в начале цикла рендера — проверка владельца → `break` при перехвате. Осиротевший воркер тихо отваливается, не дописывая счётчик и не финализируя; UPSERT в `validator_scheme_previews` идемпотентен (`ON CONFLICT (scheme_id, project_id)`), мусора в S3 нет. Хелперы `is_task_owner` / `update_scheme_progress`. Kill-switch `SCHEME_PREVIEW_OWNER_GUARD_ENABLED` (env, default ON).

**(б) зажим прогресса** — `validator-contenthunter/backend/src/services/scheme_preview_queue.py`. `read_scheme_preview_status`: `progress = min(schemes_done, schemes_total)` за флагом `scheme_preview_progress_clamp_enabled` (pydantic, default ON). `total` = `schemes_total`.

> **Разворот при реализации:** изначально слой (б) считал прогресс через `COUNT(*) FROM validator_scheme_previews WHERE last_task_id = <task_id>`. Проверка живой БД: `last_task_id` заполнен ненадёжно (1057 из 1515 строк = NULL; sample-строки `scheme_id=0` и CLI-вставки без него; превью проектов чистятся) → COUNT дал бы **вечный 0 %** в проде. Поймано на code-quality ревью + проверке БД, заменено на зажим.

**(в) зажим UI** — `validator-contenthunter/frontend/src/utils/progress.ts` + `pages/client/SchemesPage.vue`. Чистые `clampProgress`/`clampPercent` (≤ total, ≤ 100 %, пол на 0), подключены в `genPercent` и шаблон.

**Бэкфилл (применён):** `UPDATE unic_tasks SET schemes_done = LEAST(schemes_done, schemes_total) WHERE task_type='scheme_preview' AND schemes_done > schemes_total` → 2 строки (3976, 3955). После — 0 залипших.

## Тесты

- `unic-worker`: 22 passed (5 новых owner-guard, live-DB asyncpg, `project_id ≥ 100000`).
- backend: 10 passed (clamp on/off).
- frontend: 5 passed (vitest).
- Двойное ревью каждой задачи (spec compliance + code quality) + финальный холистик-ревью: готово к мержу, миграции нет (`meta jsonb` есть), порядок деплоя независим, in-flight таски безопасны (None-токен → legacy-поведение).

## Деплой (2026-06-02)

- **Воркер** → origin/main `63fb1ea`; прод `/root/unic-worker` на `91.98.180.103` (НЕ git — плоская копия): scp `worker.py` (бэкап `worker.py.bak-wp222`) + `pm2 restart unic-worker` (id0). Логи чистые. SSH ключом `~/.ssh/wp136_logo_bg_deploy`.
- **Валидатор** → origin/main `d2e638d`; прод `/root/.openclaw/workspace-genri/validator` имел свой неотправленный коммит (миграция wp152) → `git pull --rebase` (прод `61ff4be`) + `sudo pm2 restart 24` (uvicorn:8000 OK) + `npm run build` (postbuild cp `dist/*` → `/var/www/validator`).
- **docs** → origin/main `fe6d9e9`.
- Kill-switch'и default ON в коде, `.env` не менялись.

## Verify (осталось)

По следующей реальной генерации схем: индикатор доходит до `N/N` = 100 % и завершается (без «зависания» за 100 %); в БД `schemes_done ≤ schemes_total`; новых строк с `schemes_done > schemes_total` не появляется. OP#222 → «Тестирование».
