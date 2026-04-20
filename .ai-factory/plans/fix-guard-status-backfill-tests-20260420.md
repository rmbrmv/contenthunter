# План: Backfill pre-deploy guard-status leaks + расширение тестов на TT/YT

**Создан:** 2026-04-20
**Режим:** Full (cleanup + defensive tests, не новая фича)
**Slug:** `fix-guard-status-backfill-tests`
**Ветка в contenthunter:** нет (план живёт в agents workspace, правки в autowarm и evidence в contenthunter)
**Ветка в autowarm:** без feature-ветки — convention autowarm: pre-commit hook auto-push в main
**Источник:** план-потомок `contenthunter/.ai-factory/plans/open-followups-20260420.md` T4 (follow-up «Generalize guard-terminal-status»)

## Контекст (уже проверено на этапе планирования)

Изначальная формулировка «Generalize guard-terminal-status (IG T4) на TT/YT» предполагала, что фикс split-статуса работает только для IG. **Проверка показала, что это не так:**

- `_mark_task_failed_by_guard` (publisher.py:6407) делает `if reason == 'platform_not_configured_for_device'` — **platform-agnostic**, уже применяется ко всем платформам.
- Merge `ff3ec8b` (2026-04-19 20:04 UTC) — тот же коммит, что задеплоил TT-детекторы T1-T10, **параллельно** задеплоил и этот split-статус фикс для всех платформ.

**Фактическая проблема** — **исторические pre-deploy задачи** с `status=failed` и reason=`platform_not_configured_for_device`:

| Platform | Status | Count (30d) | Window |
|---|---|---|---|
| TikTok  | failed | 20 | все до 2026-04-19 20:04 UTC |
| YouTube | failed | 18 | все до 2026-04-19 20:04 UTC |
| Instagram | failed | 0 | (IG был фикснут раньше) |
| TikTok  | skipped_config_missing | 9 | post-deploy — корректно |

**Test coverage gap** (`tests/test_publish_guard.py`):
- 9 упоминаний Instagram
- 1 упоминание TikTok
- 0 упоминаний YouTube

Существующие 10 тестов коварно проходят платформенно-специфичную логику только для IG; TT и YT полагаются на то, что path один и тот же, но **эффективное покрытие** TT/YT = 0 строк.

## Settings

| | |
|---|---|
| Testing | **yes** — T2 явно добавляет TT + YT test cases |
| Logging | **standard** — SQL-dominated, 0 нового runtime-кода |
| Docs | **warn-only** — user-facing поведение guard'а уже описано в docstring; backfill+тесты docs не меняют |
| Roadmap linkage | skipped — `paths.roadmap` отсутствует |

## Граф зависимостей

```
T1 (backfill SQL dry-run) ──► T2 (backfill execute) ──► T4 (verify clean)
T3 (TT/YT tests)            ──────────────────────────► T4
```

## Tasks (4)

### T1 — Dry-run SQL backfill: каталогизировать ВСЕ pre-deploy leaks ✅ (2026-04-20; 38 rows, 0 post-deploy)

**Что сделать:**

1. SQL-запрос (read-only) — полный список `publish_tasks` с `status=failed` И `reason=platform_not_configured_for_device`, все платформы:
   ```sql
   SELECT id, platform, device_serial, account, started_at, updated_at
     FROM publish_tasks
    WHERE status = 'failed'
      AND events::text LIKE '%platform_not_configured_for_device%'
    ORDER BY platform, started_at;
   ```
2. Разбить на группы:
   - TikTok pre-deploy (ожидаемо 20)
   - YouTube pre-deploy (ожидаемо 18)
   - Instagram (ожидаемо 0 — sanity check)
3. Сохранить raw-листинг + summary в `contenthunter/.ai-factory/evidence/guard-status-backfill-catalog-20260420.md`.
4. Для каждой строки проверить, что status=failed действительно artifact'ом pre-deploy времени (started_at < 2026-04-19 20:04 UTC) — **если найдётся post-deploy case**, это НОВЫЙ баг и T2 backfill приостанавливается до расследования.

**Файл-артефакт:** `contenthunter/.ai-factory/evidence/guard-status-backfill-catalog-20260420.md`

**Логи:** standard — только SQL-вывод в evidence.

**Commit:** нет отдельного коммита, этот evidence уйдёт в один commit с T2.

---

### T2 — Execute backfill: UPDATE 38 pre-deploy leaks на `skipped_config_missing` ✅ (2026-04-20; 20 TT + 18 YT, 0 leftover)

**Что сделать:**

1. **UPDATE SQL** (idempotent — только для задач которые ДО сих пор `status=failed` И имеют reason:
   ```sql
   BEGIN;
   UPDATE publish_tasks
      SET status = 'skipped_config_missing',
          updated_at = NOW(),
          log = COALESCE(log, '') ||
                E'\n[backfill 2026-04-20] status=failed→skipped_config_missing (pre-deploy guard-split)'
    WHERE status = 'failed'
      AND events::text LIKE '%platform_not_configured_for_device%'
      AND started_at < '2026-04-19 20:04'
    RETURNING id, platform;
   -- Проверить что RETURNING вернуло ожидаемые 38 строк (20 TT + 18 YT)
   -- Если да — COMMIT; если нет — ROLLBACK и в evidence документ расхождение.
   COMMIT;
   ```
2. **Не добавляем** новый `info`-event (как делает `_mark_task_failed_by_guard` для post-deploy), чтобы не искажать jsonb history свыше текстовой пометки в `log`.
3. Сохранить итоговую raw-выборку (до/после) в том же evidence-файле.

**Файл-артефакт:** дополнение `contenthunter/.ai-factory/evidence/guard-status-backfill-catalog-20260420.md` (секция "Backfill executed").

**Логи:** standard — SQL returning + post-query count.

**Риски:**
- Нет rollback-плана на SQL-уровне после COMMIT — но идемпотентно (повторный запуск вернёт 0 rows).
- Если есть UI/метрики, кэширующие счётчик failed tasks — они обновятся на следующем cron-сборе, не сейчас. Acceptable.

**Блокируется:** T1 (dry-run должен сойтись с ожидаемыми числами).

---

### T3 — Расширить `tests/test_publish_guard.py` на TT + YT ✅ (2026-04-20; 10→14 passed)

**Что сделать:**

Добавить явные test cases для TikTok и YouTube paths (сейчас 10 тестов, в основном Instagram):

1. `test_guard_skipped_when_tiktok_seeded_but_tiktok_column_null` — fixture как `test_guard_skipped_when_device_seeded_but_platform_column_null` но с `platform='TikTok'`.
2. `test_guard_skipped_when_youtube_seeded_but_youtube_column_null` — аналогично с `platform='YouTube'`.
3. `test_mark_task_failed_by_guard_skipped_works_for_tiktok` — копия `test_mark_task_failed_by_guard_uses_skipped_status_for_config_missing` с `platform='TikTok'`. Assert что `_PLATFORM_COLUMN['TikTok']='tiktok'` попадает в msg.
4. `test_mark_task_failed_by_guard_skipped_works_for_youtube` — аналогично для YouTube.
5. (опционально) `test_guard_query_selects_tiktok_column` — параметризованный тест, проверяющий что `_GUARD_QUERY` с `platform='TikTok'` фильтрует именно по `tiktok` column (через mock psycopg2.connect с capture'ом реального вызова `cur.execute` и inspect параметров).

Все 4-5 новых тестов должны reuse `_make_mock_psycopg2()` фабрику уже существующую в файле.

**Файлы:**
- `/root/.openclaw/workspace-genri/autowarm/tests/test_publish_guard.py` (дополнение)

**Acceptance:**
- `pytest tests/test_publish_guard.py -v` — 14-15 passed (было 10).
- grep coverage по `TikTok|tiktok` в тесте — ≥3; по `YouTube|youtube` — ≥3.

**Логи:** standard — стандартные pytest assertion сообщения + `caplog` для проверки log.info/log.error.

**Коммит:** отдельный в autowarm: `test(publish-guard): explicit TT/YT coverage for platform-agnostic split-status fix`.

---

### T4 — 48h post-backfill verification + observability SQL ✅ (2026-04-20; 0 rows инcoнсистентности, 48h-waiter не нужен)

**Что сделать:**

1. Post-backfill SQL (должен вернуть 0 rows):
   ```sql
   -- Ожидание: 0 rows. Если не 0 — regression после backfill или новый баг.
   SELECT id, platform, status, started_at
     FROM publish_tasks
    WHERE status = 'failed'
      AND events::text LIKE '%platform_not_configured_for_device%';
   ```
2. Создать `autowarm/scripts/guard_status_consistency.sql` (reusable observability):
   ```sql
   -- Guard-status consistency check (должно давать 0 rows).
   -- Если появляется >0 — _mark_task_failed_by_guard сломался для какой-то платформы.
   SELECT platform, status, COUNT(*)
     FROM publish_tasks
    WHERE events::text LIKE '%platform_not_configured_for_device%'
      AND status != 'skipped_config_missing'
    GROUP BY platform, status;
   ```
3. Запустить через 48 часов (≈ 2026-04-22) и приложить output в тот же evidence-файл. **Регламент:** следующая сессия проверит, 0 ли rows возвращает; если 0 — T4 закрыт.

**Файлы:**
- `/root/.openclaw/workspace-genri/autowarm/scripts/guard_status_consistency.sql` (новый)
- Дополнение `contenthunter/.ai-factory/evidence/guard-status-backfill-catalog-20260420.md`

**Acceptance:**
- `psql -f scripts/guard_status_consistency.sql` возвращает 0 rows через 48h после backfill.
- Никаких новых post-backfill leak'ов.

**Логи:** standard.

**Блокируется:** T2 (backfill executed) + T3 (тесты зелёные).

## Commit plan

4 задачи → без отдельных commit checkpoint'ов (правило ≥5). Три коммита:

1. **autowarm:** `test(publish-guard): explicit TT/YT coverage for platform-agnostic split-status fix` (T3).
2. **autowarm:** `chore(scripts): guard_status_consistency.sql for post-backfill monitoring` (T4 часть).
3. **contenthunter:** `docs(evidence): guard-status pre-deploy backfill (20 TT + 18 YT tasks) + monitoring SQL` (T1+T2+T4 evidence).

## Риски и контрмеры

| Риск | Вероятность | Митигация |
|---|---|---|
| T1 dry-run находит post-deploy case → НОВЫЙ баг | low | Приостановить T2, завести fix-plan |
| T2 `UPDATE` повлияет на задачи, которые кто-то планирует retry'ить | low | Задачи уже `failed`, retry всё равно произойдёт через scheduler — смена статуса на `skipped_config_missing` только корректирует терминологию |
| T3 тесты раскрывают несостоятельность mock-фабрики для не-IG платформы | med | fixture factory `_make_mock_psycopg2()` принимает платформу как параметр — если что, доточить |
| T4 через 48h видно новый leak → regression | low | Observability SQL для регулярного run'а (можно в pm2-cron) |

## Что намеренно НЕ делаем

- **Не меняем код `_mark_task_failed_by_guard`** — он уже platform-agnostic.
- **Не меняем `_check_account_device_mapping`** — тоже platform-agnostic.
- **Не меняем SQL queries `_GUARD_QUERY` / `_GUARD_PLATFORM_CONFIG_QUERY`** — они уже корректно фильтруют по платформе.
- **Не добавляем info-event при backfill** — только текст в `log`, чтобы не загрязнять jsonb истории.
- **Не трогаем IG задачи** — их нет в backlog (Instagram фикс был раньше `ff3ec8b`).
- **Не создаём ветку** ни в contenthunter (планы тут без ветки), ни в autowarm (auto-push convention).

## Next step

После review — `/aif-implement` пойдёт по T1→T2 (последовательно, с проверкой dry-run count) → T3 (параллельно-возможно) → T4.

Оценка времени: T1 ~5 мин, T2 ~2 мин, T3 ~15 мин, T4 (сегодня, без 48h-waiter) ~5 мин. Итого ~30 мин до коммитов, +48 часов для final T4 verdict.
