# WP#222 — Счётчик генерации превью схем уходит за 100% и зависает

**Дата:** 2026-06-02
**OpenProject:** WP#222 (тип «Ошибка», assignee Данил, статус «В разработке»)
**Ветка:** `wp222-unic-preview-progress-overflow`
**Репозитории:** `unic-worker`, `validator-contenthunter` (backend + frontend); docs → `contenthunter`

## Суть

В мастере «Схемы уникализации» на шаге «Генерация» индикатор «Генерация превью…» уходит за предел: пользователь видит `41 / 34` = `121 %` (обработанных больше, чем всего схем 34), прогресс не завершается, обновление страницы не помогает. Сообщил @Danil_Pavlov_123, 2026-06-02, скриншот.

## Корневая причина

Симптом — **реальное состояние БД**, не глюк отрисовки. Проверка живой `unic_tasks` (openclaw PG, контейнер 172.17.0.3):

| task_id | project | schemes_total | schemes_done | len(schemes JSON) | watchdog_revert_count |
|---|---|---|---|---|---|
| 3976 | 117 | 34 | **64** | 34 | 0 |
| 3955 | 103 | 4 | **7** | 4 | 0 |

`schemes_done` физически превышает `schemes_total`, при том что список схем в задаче равен `schemes_total`. Оба значения ≈ ×1.8 от истинного числа схем → почти двойной счёт с потерянными апдейтами.

**Механизм:** один и тот же `scheme_preview`-таск обрабатывается воркером **внахлёст дважды**, счётчик `schemes_done` накапливается выше реального числа схем. Защиты от двойного запуска оставляют дыры:

- `get_pending_task` берёт `pg_try_advisory_xact_lock(project_id)`, но это **транзакционный** lock — он держится только на короткой транзакции **захвата** и снимается на её COMMIT. Сама генерация (30–75 мин) идёт уже без advisory-lock, под защитой лишь committed-строки `current_status='processing'` (Level-1 `NOT EXISTS`-гард).
- Как только строку снимают из `processing` в `pending` — через `restart_stuck` (старт воркера сбрасывает ВСЕ `processing` → `pending` без guard) либо watchdog-ревёрт — второй воркер проходит `NOT EXISTS` и берёт таск, **пока первый ещё жив** → параллельная обработка → переполнение `schemes_done`.

Триггеров БД на `unic_tasks`/`unic_results` нет. Текущий чекаут воркера пишет прогресс абсолютным `SET schemes_done=done_count` (cap = `len(schemes)` = 34) — в одиночку 64 не даст; значит в проде идёт именно перекрытие обработки (возможно, в связке с инкрементной записью в задеплоенной версии). Фронтенд честно рисует значение из БД: `width: 121%`, бар «застревает», пока медленный второй воркер не завершит.

## Решение (Подход 1: владелец-эпоха + идемпотентный прогресс + зажим UI)

Три слоя, каждый закрывает свой провал. Без схемной миграции — `owner_run_id` живёт в существующем `meta jsonb`.

### Слой (а) — гард владельца таска. Репозиторий `unic-worker`, `worker.py`

Бьёт в первопричину (перекрытие обработки).

1. **Захват** (`get_pending_task`, шаг 3, пометка `processing`): дополнительно записать `meta = COALESCE(meta,'{}'::jsonb) || jsonb_build_object('owner_run_id', <uuid4>)`. Воркер удерживает токен в локальной переменной на всё время `process_scheme_preview_task`.
2. **Проверка владения в цикле** (`process_scheme_preview_task`, начало каждой итерации по схемам, ПЕРЕД тяжёлым ffmpeg): `SELECT meta->>'owner_run_id'`. Если ≠ свой токен → таск переотдали → воркер **тихо выходит** (`break` + `return` без финализации). Потеря — максимум один рендер схемы на перехват.
3. **Гард записей**: прогресс-`UPDATE` (строка ~798), `mark_task_done`, partial-success `UPDATE`, `mark_task_error` — все добавляют `AND meta->>'owner_run_id' = $token`. Записи «осиротевшего» воркера становятся no-op.

UPSERT в `validator_scheme_previews` уже идемпотентен (`ON CONFLICT (scheme_id, project_id)` + guard по `last_task_id`), поэтому старый воркер не плодит мусор в S3 и не портит чужие превью.

**Kill-switch** `SCHEME_PREVIEW_OWNER_GUARD_ENABLED` (env воркера, default ON). Off → токен не штампуется, `WHERE`-гарды не добавляются → текущее поведение.

### Слой (б) — зажим прогресса. Репозиторий `validator-contenthunter/backend`, `services/scheme_preview_queue.py`

`read_scheme_preview_status` зажимает прогресс на `schemes_total`:

```python
progress = int(row['done'])
total = int(row['total'])
if settings.scheme_preview_progress_clamp_enabled and total > 0:
    progress = min(progress, total)
```

`progress` физически не может превысить `total` → «121 %» невозможно даже если что-то проскочит мимо слоя (а). `total` остаётся `schemes_total`.

**Kill-switch** `scheme_preview_progress_clamp_enabled` (pydantic settings, default ON). Off → возвращать сырой `schemes_done` как раньше.

> **Разворот при реализации (02.06):** изначально слой (б) планировался как «идемпотентный прогресс» через `COUNT(*) FROM validator_scheme_previews WHERE last_task_id = <task_id>`. Проверка **живой БД** показала, что `last_task_id` заполнен ненадёжно (1057 из 1515 строк = NULL; у реального проекта 117 `COUNT` по свежему таску = 0, т.к. превью чистятся/sample-строки и CLI-вставки идут без `last_task_id`). COUNT-подход дал бы **вечный 0 %** в проде — хуже исходного бага. Заменён на зажим `LEAST(done, total)`: не зависит от persistence превью, не может дать >100 %, а корень (инфляцию `schemes_done`) лечит слой (а).

### Слой (в) — зажим UI. Репозиторий `validator-contenthunter/frontend`, `pages/client/SchemesPage.vue`

Последний рубеж, безусловный (тривиально безопасен):

- `genPercent = computed(() => genTotal ? Math.min(100, Math.round(genProgress / genTotal * 100)) : 0)`
- В отображении `{{ genProgress }} / {{ genTotal }}` — зажать числитель: `Math.min(genProgress, genTotal)`.

### Бэкфилл текущих залипших строк (делаем сразу)

Разово, по openclaw PG:

```sql
UPDATE unic_tasks
   SET schemes_done = LEAST(schemes_done, schemes_total), updated_at = NOW()
 WHERE task_type='scheme_preview' AND schemes_done > schemes_total;
```

Косметика для уже существующих строк (3976, 3955 и подобных). Они уже `done`, на новые генерации не влияют, но чистят историю.

## Что НЕ трогаем

- Watchdog и `restart_stuck` — логику переотдачи не меняем; теперь переотдача безопасна (новый pickup перештампует токен, старый воркер сам отвалится на проверке владения).
- Схему БД — миграции нет.
- Дедуп/supersede в `enqueue_scheme_preview` — корректны.

## Тестирование (TDD)

**worker** (`unic-worker/tests/`, рядом с `test_per_project_guard.py`):
- Перехват владения: после перештампа `owner_run_id` прогресс-`UPDATE`/`mark_done` старого воркера → no-op (строка не меняется).
- Проверка владения в цикле: воркер с чужим токеном выходит, не дописывая `schemes_done`.
- Итог: `schemes_done ≤ schemes_total` в сценарии перекрытия.
- Kill-switch off → старое поведение (нет `owner_run_id`, нет гард-`WHERE`).

**backend** (`scheme_preview_queue`):
- При искусственно раздутом `schemes_done=64`, `schemes_total=34`: `read_scheme_preview_status` возвращает `progress = 34` (зажато), `total = 34`. Flag-off → сырой `progress = 64`.
- Kill-switch off → `progress = schemes_done` как раньше.

**frontend** (`vitest`):
- `genPercent` зажат ≤ 100 при `genProgress > genTotal`.
- Числитель в отображении ≤ `genTotal`.

## Развёртывание

- `unic-worker` → хост `91.98.180.103`: git pull + рестарт воркера — **за Данилом** (SSH-ключей агента туда нет).
- `validator-contenthunter` backend → `/root/.openclaw/workspace-genri/validator`, PM2 **id24**: pull (агент, без sudo) + рестарт (`sudo pm2 restart 24`, за Данилом).
- frontend → `cd frontend && npm run build` → postbuild `cp` в `/var/www/validator`.
- Бэкфилл-SQL → разово на openclaw PG.
- env-флаги добавить в `.env` обоих сервисов.

После деплоя — OP#222 → «Тестирование», verify по следующей генерации (прогресс доходит до `N/N` = 100 % и завершается; в БД `schemes_done ≤ schemes_total`).
