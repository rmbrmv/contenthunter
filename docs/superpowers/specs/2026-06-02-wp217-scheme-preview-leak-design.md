# WP#217 — Видео из уникализатора («отбор схем») протекает в автовыкладку

- **Дата:** 2026-06-02
- **Тип:** Ошибка (OpenProject WP#217, проект Content Hunter, assignee Данил)
- **Репозиторий фикса:** `delivery-contenthunter` (autowarm) — единственный затронутый
- **Ветка спеки:** `wp217-scheme-preview-leak`

## 1. Проблема

В уникализаторе есть режим **отбора схем**: заливают образец видео, прогоняют схемы, смотрят превью и выбирают подходящие. Валидатор создаёт под это задачу в `unic_tasks` с пометкой **`task_type = 'scheme_preview'`** (вход — `/scheme-previews/...`, без `content_id`, без `slot_date`, без слота в планировщике; см. `validator-contenthunter backend/src/services/scheme_preview_queue.py`).

Воркер уникализации пишет результаты превью в ту же таблицу `unic_results`, что и обычные публикуемые задачи. Авто-крон `unic_results → publish_queue` (`assignUnicResultsToQueue` → `selectAssignCandidates`, `assign_candidates.js`) **забирает все готовые `unic_results` подряд без фильтра по `task_type`**. Так как у превью-задачи нет `meta.slot_id`, D3-гард родословной слота уходит в «legacy»-ветку и **пропускается**, после чего строки попадают в `publish_queue` и публикуются.

### Подтверждение по проду (БД openclaw, 2026-06-02)

- Превью-таск `#3955` (Ирбис, 31.05 16:52; маркеры: `meta.sample_url` есть, `meta.source` нет, `input_video_url LIKE '%scheme-previews%'`, `content_id`/`slot_date` пустые) → 7 результатов → крон в 16:58 раскидал на `irbis.academy` / `irbis_talent` / `irbis.theatre` (YT/TT/IG); несколько YouTube ушли в `done` = ровно скриншоты из задачи.
- Утечка шире одного клиента: всего **105 строк** из `scheme_preview`-задач попали в `publish_queue` — **9 `done` (опубликовано)**, 21 `failed`, **75 `pending`**.
- Затронуты два активных проекта: **103 «Ирбис»** (15 строк, 31.05) и **117 «Мурат Димитров»** (90 строк, 01.06; из них 75 ещё `pending` → опубликовались бы при следующем диспатче).

### Корень

`selectAssignCandidates` (мост авто-выкладки) не различает публикуемые задачи и служебные прогоны отбора схем. Маркер для различения уже есть и надёжен: `unic_tasks.task_type` (колонка `NOT NULL DEFAULT 'unic'`; нормальные задачи = `'unic'`, превью = `'scheme_preview'`).

## 2. Решение (обзор)

Барьер ставится только в авто-мосте `unic_results → publish_queue` (в репо autowarm), в двух точках для defense-in-depth, плюс одноразовая зачистка уже утёкших строк. Валидатор и воркер не меняются — генерация превью остаётся как есть, валидатор продолжает читать превью из `unic_results`.

Подход — **allowlist** (`task_type = 'unic'`), fail-closed: любой будущий служебный `task_type` тоже не утечёт.

## 3. Компоненты

### A. Allowlist в кандидатном отборе — `assign_candidates.js::selectAssignCandidates`

Добавить в `WHERE` предикат публикуемости:

```sql
AND ut.task_type = 'unic'
```

Завернуть в kill-switch `ASSIGN_PUBLISHABLE_TASK_TYPE_GUARD_ENABLED` (default ON; `=false` → прежнее поведение без передеплоя — по образцу `ASSIGN_REQUEUE_MOVED_ENABLED` в этом же файле). Реализовать как чистый helper-предикат, чтобы тестировать без `require('./server')`.

### B. Зеркальная проверка на диспатче — `server.js::checkDispatchQueueSlotLineage`

В уже существующий `SELECT ut.meta, ut.content_id, ut.slot_date FROM unic_tasks ut JOIN unic_results ur …` добавить `ut.task_type`. Если `task_type <> 'unic'` — отменить строку очереди до публикации:

```sql
UPDATE publish_queue
SET status = 'cancelled', skip_reason = 'non_publishable_task_type', updated_at = now()
WHERE id = $1 AND status = 'pending'
```

и вернуть `{ skipped: true, skip_reason: 'non_publishable_task_type' }`. Проверку разместить рядом с существующим WP#125-рекчеком (единый чокпоинт диспатча), до «legacy»-возврата `meta_slot_id_missing`. Kill-switch `DISPATCH_TASK_TYPE_RECHECK_ENABLED` (default ON; по образцу соседнего `DISPATCH_MANUAL_RECHECK_ENABLED`). Назначение B — поймать строки, попавшие в очередь **до** деплоя или в окно раскатки (гонка между cleanup и активным крон-диспатчем).

### C. Одноразовый cleanup-скрипт — `cleanup_wp217_scheme_preview_leak.js`

По образцу `cleanup_wp216_inactive_project_queue.js`:

- Помечает `publish_queue` строки, где связанный `unic_task.task_type = 'scheme_preview'` и `status = 'pending'`, как `cancelled` + `skip_reason = 'scheme_preview_leak'`.
- Идемпотентно (`WHERE status='pending'`), **dry-run по умолчанию**, запись только при `--apply`.
- Печатает счётчики по проектам до/после.
- Закрывает текущие 75 `pending` (Мурат Димитров + остатки Ирбиса).

Скрипт не трогает `done`/`failed`/`running` — только `pending` (ещё не опубликованные).

## 4. Поток данных после фикса

```
scheme_preview task → воркер → unic_results (превью видны в валидаторе)
        → assign-крон ПРОПУСКАЕТ (A: task_type ≠ 'unic')   → в publish_queue не попадает
        → если строка уже в очереди: диспатч ОТМЕНЯЕТ (B)
        → уже лежащие pending: зачистка (C)
обычная unic task → task_type='unic' → проходит A и B как раньше
```

## 5. Edge-cases / обработка ошибок

- Kill-switch'и у A и B → мгновенный откат при регрессии без передеплоя.
- B обновляет только строки в статусе `pending` — не трогает уже бегущие/готовые.
- Ручная очередь оператора (`manual_queue_assign.js`) уже безопасна: она делает `INNER JOIN validator_schedule_slots ON vss.id = (ut.meta->>'slot_id')::int`; у превью-задач `slot_id` нет → JOIN их отбрасывает. Код не меняем, добавляем только защитный регресс-тест.
- `task_type` — `NOT NULL DEFAULT 'unic'`, поэтому NULL-кейса нет; allowlist `= 'unic'` корректен и полон.

## 6. Тестирование (TDD)

Все тесты — в репо autowarm.

- **`assign_candidates`**: (1) превью-результат (`task_type='scheme_preview'`) НЕ попадает в кандидаты; (2) обычный (`'unic'`) — попадает; (3) kill-switch `=false` → старое поведение (превью снова в кандидатах).
- **dispatch guard** (`checkDispatchQueueSlotLineage`): (1) строка превью-задачи → `cancelled` + `non_publishable_task_type`; (2) обычная — проходит к claim'у; (3) kill-switch `=false` → старое поведение.
- **cleanup-скрипт**: live-тест — метит pending превью-строки, не трогает не-pending и чужие (`task_type='unic'`); идемпотентность повторного запуска.
- **защитный тест ручной очереди**: превью-результаты не появляются в `selectAssignCandidates` для manual-пути.

## 7. Развёртывание

- Прод-каталог autowarm: `git pull` под `claude-user` (без sudo). Крон-диспатч и assign — внутри долгоживущего `server.js` процесса PM2 (id 35) → **нужен `sudo pm2 restart` id35** (в отличие от per-task publisher, A/B живут в server.js).
- Cleanup-скрипт C запускается вручную один раз после деплоя (dry-run → `--apply`).
- Kill-switch'и в `.env` (default ON).

## 8. Вне кода

9 уже опубликованных превью-роликов (YouTube `irbis.academy` / `irbis_talent`) — перечень URL/аккаунтов зафиксировать в комментарии к WP#217; физическое удаление с площадок = отдельная ops-задача операторам (у агента нет доступа к аккаунтам соцсетей).

## 9. Связанные

- `[[project_wp111_neutral_schemes_irbis]]` — отбор схем Ирбиса (тот самый превью-флоу).
- `[[project_wp216_disabled_client_manual_queue]]` — соседний фильтр пайплайна; cleanup-скрипт по тому же образцу.
- Кросс-репо контракт `assign_candidates.js` ↔ валидатор (`scheme_preview_queue.py` ставит `task_type`).
