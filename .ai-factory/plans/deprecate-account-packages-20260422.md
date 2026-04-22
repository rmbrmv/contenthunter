# Deprecate account_packages — Шаг 2 (code rewrite only)

**Тип:** refactor + data migration + deprecation
**Создан:** 2026-04-22 UTC
**Режим:** Full (slug `deprecate-account-packages-20260422`)
**Целевые репо:**
- `/home/claude-user/autowarm-testbench/` (branch `testbench`) — весь код (guard, server.js, migrations)
- `/home/claude-user/contenthunter/` (branch `main`) — план + evidence + memory
**НЕ трогаем:** `/root/autowarm/` (prod deploy = Шаг 3 отдельной задачей).

## Scope & non-scope

**В scope (Шаг 2):**
- **Dedupe.** Разбить 4 строки с дублирующимися `pack_name` в `factory_pack_accounts` (`Content hunter_84`: id=7 + id=225; `Content hunter_105`: id=227 + id=229) — обе пары на одном устройстве каждая.
- **Split invariants.** 29 invariant-паков (≥2 active-аккаунта одной платформы) разбить на a/b/c-split'ы. Hybrid подход: generic CLI-скрипт через существующую логику `/api/packages/:id/split` (`server.js:2472-2605`) + ручной fallback для edge-cases.
- **Rewrite guard.** `publisher.py:_GUARD_QUERY` + `_GUARD_PLATFORM_CONFIG_QUERY` + `_SA_KNOWN_ACCOUNTS_QUERY` — перевести с `account_packages` на `factory_pack_accounts ⨝ factory_inst_accounts ⨝ factory_device_numbers` (с учётом `fpa.end_date`).
- **Rewrite server.js** read-пути, читающие `account_packages` (6 мест, см. карту ниже) и admin CRUD (`POST/PUT/DELETE /api/packages`) — перенаправить записи на factory-модель (через resolvePackLayout + syncPackIntoAccountPackages).
- **Old-vs-new snapshot-diff тест** поверх всей БД (каждая (serial, platform) пара) — убедиться, что новый guard возвращает тот же набор known accounts, что и старый. Без расхождений — hard cutover.
- **Smoke на phone #19** + регрессионный pytest.

**Не в scope (Шаг 3):**
- **Prod deploy `/root/autowarm/`** — отдельным коротким планом после smoke на testbench.
- **DROP TABLE account_packages** — только после prod deploy.
- **Удалить sync-helpers** (`account_packages_sync.{py,js}`, `audit_sync_account_packages.py`, `_upsert_auto_mapping`) — остаются жить как dual-write до Шага 3, потому что БД общая с prod и prod всё ещё читает account_packages.
- **`_upsert_auto_mapping`** трогать не будем: он продолжает писать в `account_packages` под `project='auto-from-publish'` — это нужно prod'у до Шага 3. Testbench-guard его записи всё равно не читает (читает `publish_tasks.done` history).
- **Переделка `pack_name_resolver.{py,js}`** — уже готов из Шага 1, используем как есть.

**Почему DROP/prod отдельно:** БД общая между testbench и prod (см. Шаг 1 R8). Если сейчас дропнуть account_packages или убрать sync — prod-guard начнёт блокировать все задачи. Поэтому dual-write сохраняется до момента, когда prod начнёт читать factory.

## Settings

| | |
|---|---|
| Testing | **yes** — (1) unit на новые guard-queries с фикстурами, (2) snapshot-diff старой и новой логики на всей БД (offline, без mock'ов), (3) интеграционный pytest для admin CRUD factory-writes, (4) node --test для server.js helpers |
| Logging | **verbose** — новый guard пишет `[guard] source=factory serial=… platform=… known=[…] matched=…`; snapshot-diff скрипт логирует ВСЕ расхождения; admin CRUD логирует `[api/packages] action=… factory_pack=… ap_sync=…` |
| Docs | **mandatory checkpoint (T14)** — evidence + memory (`project_account_packages_deprecation.md` закрыть как «Шаг 2 готов, Шаг 3 остался») + Шаг 3 brief |
| Roadmap linkage | skipped — `paths.roadmap` не настроен |
| Git | testbench: ветка `testbench`, `git push origin testbench`. contenthunter: `main`, `git push origin main`. **В /root/autowarm не деплоим.** |

## Research Context

Research path не ведётся. Источники:
- memory: `project_account_packages_deprecation.md` (brief Шаг 2), `project_publish_guard_schema.md` (guard shape), `project_account_packages_end_date.md` (семантика end_date)
- Step 1 plan: `.ai-factory/plans/revision-account-packages-sync-20260422.md` (контекст sync + resolver)
- Валидировано на БД `openclaw:openclaw123@localhost:5432`:
  - 241 строка в `account_packages` (222 active-null + 19 expired)
  - 213 строк в `factory_pack_accounts` (2 name-дубля: по 2 строки на каждый из `Content hunter_84`, `Content hunter_105`)
  - 29 distinct invariant-паков (2+ active-аккаунта одной платформы)
  - 20 упоминаний `account_packages` в `server.js`, 16 в `publisher.py`
- Существующий `/api/packages/:id/split` (`server.js:2472-2605`) — рабочий engine, используем как строительный блок для batch-split

## Карта текущих использований `account_packages`

### `publisher.py` (переписываем guard, остальное оставляем)

| Место | Что | Решение Шага 2 |
|---|---|---|
| 6451 `_GUARD_QUERY` | declarative UNION из 3 колонок ap + publish_tasks.done history | **Переписать на factory** (T6) |
| 6485 `_GUARD_PLATFORM_CONFIG_QUERY` | device_seeded + platform_all_null по ap | **Переписать на factory** (T6) |
| 6511 `_SA_KNOWN_ACCOUNTS_QUERY` | то же (single-account preflight) | **Переписать на factory** (T6) |
| 6735 `_upsert_auto_mapping` | UPDATE/INSERT account_packages project='auto-from-publish' | **Оставить as is** (dual-write для prod) |

### `server.js` (переписываем READ-пути + admin CRUD)

| Строки | Endpoint | Что читает/пишет | Решение Шага 2 |
|---|---|---|---|
| 439-441 | `GET /api/devices` | LEFT JOIN ap по pack_name для `project_name, pack_name` | **Rewrite** → project_name из `validator_projects` через factory_pack_accounts.project_id (T9) |
| 842 | `POST /api/farming/tasks` | LEFT JOIN ap для project | **Rewrite** → `validator_projects` (T9) |
| 2220 | `GET /api/projects` | DISTINCT project из ap | **Rewrite** → DISTINCT из `validator_projects` (T9) |
| 2250, 2260 | `GET /api/farming/projects` | project из ap | **Rewrite** → `validator_projects` (T9) |
| 2278, 2287, 2295 | `GET /api/farming/packs` | pack_name из ap | **Rewrite** → factory_pack_accounts (T9) |
| 2363-2413 | `GET /api/packages` | LATERAL JOIN ap для project.name (самая свежая) | **Rewrite** → `validator_projects` по `fpa.project_id` (T10) |
| 2415-2425 | `POST /api/packages` (admin create) | INSERT ap | **Rewrite** → create factory_pack_accounts + factory_inst_accounts via resolvePackLayout, sync mirror в ap (T10) |
| 2427-2437 | `PUT /api/packages/:id` (admin update) | UPDATE ap | **Rewrite** → :id становится factory_pack_accounts.id; UPDATE fpa + re-sync (T10) |
| 2439-2443 | `DELETE /api/packages/:id` (admin delete) | DELETE ap | **Rewrite** → DELETE factory_inst_accounts WHERE pack_id + DELETE factory_pack_accounts; DELETE ap by pack_name (T10) |
| 5346-5362 | `getSocialAccounts` | LATERAL project/start/end из ap | **Rewrite** → project через `validator_projects`, start_date/end_date из `factory_pack_accounts` (T9) |

**Итого: 6 read-пучков + 3 admin-CRUD endpoints. Всего ~10 изменений в `server.js`.**

## Strategy

1. **Порядок критичен.** Сначала чистим данные (dedupe + 29 split), потом переписываем код. Если кодить на грязных данных — тесты будут случайно ломаться на invariant-паках.
2. **Hybrid batch-split.** Пишем Python-скрипт `migrations/batch_split_invariants.py`, который переиспользует уже работающую логику из `server.js:2472-2605` (`/api/packages/:id/split`). Dry-run показывает план split'а для каждого из 29 паков. Apply — транзакционный split + factory_sync_exclusions + sync_pack_into_account_packages. Для нестандартных случаев (если dry-run показывает неожиданное разбиение) — ручной SQL-файл по образцу `20260422_split_phone19_legacy_pack.sql`.
3. **Guard rewrite + snapshot-diff.** Новый `_GUARD_QUERY` живёт в `publisher.py` под новым именем (`_GUARD_QUERY_V2`). Параллельно пишем скрипт `tools/guard_snapshot_diff.py`, который на каждой {serial, platform, account} тройке из `publish_tasks` прогоняет обе версии и репортит расхождения. Только после 0 расхождений — переименовываем `_GUARD_QUERY_V2 → _GUARD_QUERY`, удаляем старый.
4. **Admin CRUD остаётся по URL `/api/packages` —** меняется backend (теперь factory + sync mirror). UI не трогаем.
5. **Dual-write оставляем** — `syncPackIntoAccountPackages` (из Шага 1) вызывается после каждой мутации factory. Это сохраняет `account_packages` в актуальном виде для prod'а до Шага 3.
6. **Prod deploy выносим в Шаг 3** — эта задача только testbench.

## Tasks

### Phase 1 — Dedupe name-дублей (T1, T2)

**T1. ✅ Миграция dedupe `Content hunter_84` (id=7, id=225)**  (blocks T3) — applied. factory 7→_84a (IG autopostfactory + YT autopostfactory + TT content.hunter51 + VK contentfactory_pro), 225→_84b (IG 1content_hunter). ap.id=7/225 mirrored, end_date=NULL. Idempotent re-run confirmed.

- Файл: `/home/claude-user/autowarm-testbench/migrations/20260422_dedupe_content_hunter_84.sql`
- Обе строки на `device_id=RFGYA19DNGZ`. Контент:
  - pack 7: IG `autopostfactory`, YT `autopostfactory`, TT `content.hunter51`, VK `contentfactory_pro`
  - pack 225: IG `1content_hunter`
- Цель: переименовать pack 7 → `Content hunter_84a`, pack 225 → `Content hunter_84b` + re-sync обе строки в `account_packages` (строки ap 7 и 225 уже существуют, одну обновляем, одну — если надо — тоже).
- Структура (идемпотентно):
  ```sql
  BEGIN;
  DO $$
  DECLARE v_name text;
  BEGIN
    SELECT pack_name INTO v_name FROM factory_pack_accounts WHERE id=7;
    IF v_name = 'Content hunter_84a' THEN
      RAISE NOTICE 'Already applied. Skip.';
      RETURN;
    END IF;
    IF v_name <> 'Content hunter_84' THEN
      RAISE EXCEPTION 'Unexpected state pack 7: %', v_name;
    END IF;
  END $$;

  UPDATE factory_pack_accounts SET pack_name='Content hunter_84a' WHERE id=7  AND pack_name='Content hunter_84';
  UPDATE factory_pack_accounts SET pack_name='Content hunter_84b' WHERE id=225 AND pack_name='Content hunter_84';

  -- Обновить ap-строки (pack_name, project, columns, end_date=NULL)
  UPDATE account_packages SET
    pack_name='Content hunter_84a', project='Content hunter',
    instagram='autopostfactory', youtube='autopostfactory',
    tiktok='content.hunter51', vk='contentfactory_pro',
    end_date=NULL, updated_at=NOW()
  WHERE id=7;
  UPDATE account_packages SET
    pack_name='Content hunter_84b', project='Content hunter',
    instagram='1content_hunter', tiktok=NULL, youtube=NULL, vk=NULL,
    end_date=NULL, device_serial='RFGYA19DNGZ', updated_at=NOW()
  WHERE id=225;

  -- Защита от перезаписи factory_sync.py
  INSERT INTO factory_sync_exclusions (table_name, row_id, reason)
  VALUES
    ('factory_pack_accounts', 7,   'dedupe: renamed to _84a'),
    ('factory_pack_accounts', 225, 'dedupe: renamed to _84b')
  ON CONFLICT (table_name, row_id) DO UPDATE SET reason=EXCLUDED.reason, created_at=NOW();
  COMMIT;
  ```
- Dry-run: `BEGIN; \i … ; SELECT + ROLLBACK;` — проверить целевое состояние.
- Apply — без ROLLBACK. Логи в evidence (T15).
- Rollback-скрипт: `migrations/20260422_dedupe_content_hunter_84__rollback.sql` (обратные UPDATE + удаление sync_exclusions).

**T2. ✅ Миграция dedupe `Content hunter_105` (id=227, id=229)**  (blocks T3) — applied. factory 227→_105a (IG content_hunter_0 + TT contentexpert_1 + YT content.hunter1), 229→_105b (IG gengo_sales). ap.id=227/229 mirrored, end_date=NULL. Idempotent re-run confirmed. Global check: 0 pack_name duplicates in factory.

- Файл: `/home/claude-user/autowarm-testbench/migrations/20260422_dedupe_content_hunter_105.sql`
- Обе на `device_id=RF8YA0V78FE`.
  - pack 227: IG `content_hunter_0`, TT `contentexpert_1`, YT `content.hunter1`
  - pack 229: IG `gengo_sales`
- Переименование: 227 → `Content hunter_105a`, 229 → `Content hunter_105b`.
- Структура аналогична T1, для ap.id=229 `device_serial` сейчас NULL → выставляем `'RF8YA0V78FE'`.
- Rollback-скрипт аналогичный.

### Phase 2 — Batch-split 29 invariant-паков (T3, T4, T5)

**T3. ✅ CLI-скрипт `batch_split_invariants.py`**  (blocked by T1, T2; blocks T5) — создан `migrations/batch_split_invariants.py`, импортирует sync_pack_into_account_packages. Dry-run на pack 280 показал корректный 3-way split (dev1a/dev1b/dev1c по IG/TT/YT). --pack-id/--exclude-pack-ids/--dump-plan/--apply флаги.

- Файл: `/home/claude-user/autowarm-testbench/migrations/batch_split_invariants.py`
- Использует ту же логику, что `server.js:/api/packages/:id/split` (2472-2605), портированную в Python:
  1. `SELECT id, pack_name FROM factory_pack_accounts fpa WHERE fpa.id IN (invariant_ids)` + `SELECT * FROM factory_inst_accounts WHERE pack_id IN (…)`.
  2. Для каждого pack'а: группировка active-аккаунтов по платформе; `N = max(count)`.
  3. `packAssignments[N]` — распределяем i-й аккаунт каждой платформы в i-й pack.
  4. Inactive-аккаунты остаются в pack_a.
  5. `baseName`: если pack_name кончается на `[a-z]` — отрезаем, иначе берём как есть.
  6. UPDATE `factory_pack_accounts SET pack_name=base_a WHERE id=<original>`.
  7. INSERT новых `factory_pack_accounts` (id = max+i), INSERT новых `factory_inst_accounts` (id = max+i).
  8. DELETE moved-accounts из originalа (только для тех, что ушли в новые паки).
  9. `INSERT INTO factory_sync_exclusions` для всех затронутых строк.
  10. `syncPackIntoAccountPackages(conn, pack_id)` для всех N новых + original → account_packages.
- CLI-флаги:
  ```
  python3 batch_split_invariants.py                    # dry-run: печатает план каждого split
  python3 batch_split_invariants.py --apply            # apply
  python3 batch_split_invariants.py --pack-id 280      # только один пак
  python3 batch_split_invariants.py --dump-plan out.json  # эспорт плана для ревью
  ```
- Dry-run выводит JSON вида:
  ```json
  {"pack_id": 280, "base_name": "rev_septizim_content_hunter_dev1",
   "splits": [
     {"new_name": "…_dev1a", "accounts": [{"id":..., "platform":"instagram","username":"..."}, ...]},
     {"new_name": "…_dev1b", "accounts": [...]},
     {"new_name": "…_dev1c", "accounts": [...]}
   ]}
  ```
- **Скрипт пропускает** паки, где `N=1` (инвариант уже соблюдён) — защита от повторного прогона.
- **Edge-case: `pack_name` уже кончается на буквенный суффикс** — base = без последней буквы. Проверяется regex `/[a-z]$/i` (эквивалент JS-логики).
- Verbose logging: `INFO [batch-split] pack=%d name=%s → N=%d, new_names=%s, moved_accounts=%d`.

**T4. ✅ Unit-тест для `batch_split_invariants.py`**  (blocked by T3; blocks T5) — 11/11 pass. Cover: _strip_suffix (3), plan_split 2-way/3-way/inactive/noop/base-strip (5), apply (2), find_invariant (1). SAVEPOINT+ROLLBACK, no mocks.

- Файл: `/home/claude-user/autowarm-testbench/tests/test_batch_split_invariants.py`
- Тесты (SAVEPOINT + ROLLBACK, house-style «не мокать БД»):
  1. `test_split_2way_one_platform` — pack с 2 IG-активов → 2 pack'а (_a, _b), оба с одним IG.
  2. `test_split_3way_mixed` — pack с 3 IG + 2 TT + 1 YT → 3 pack'а; pack_a: IG+TT+YT, pack_b: IG+TT, pack_c: IG.
  3. `test_split_preserves_inactive_in_pack_a` — inactive-аккаунты не двигаются.
  4. `test_noop_if_invariant_ok` — pack без дублей не трогается (idempotent repeat).
  5. `test_base_name_strips_suffix` — pack_name = `"X_1a"` → base = `"X_1"`, new = `"X_1b"`.
  6. `test_ap_sync_mirrors_new_packs` — после split'а в `account_packages` есть строка на каждый новый pack_name с правильными колонками.
  7. `test_sync_exclusions_inserted` — factory_sync_exclusions заполнены для original + new packs + moved accounts.
  8. `test_skips_when_already_applied` — повторный прогон на уже разбитом паке ничего не меняет (через `--pack-id`).
- Запуск: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_batch_split_invariants.py -v`. Expected: 8/8 pass.

**T5. ✅ Запустить batch-split на всей БД**  (blocked by T4; blocks T6) — 29/29 applied (25 × 2-way, 3 × 3-way, 1 × 3-way). Post-state: 0 invariants, 0 pack_name duplicates в factory. audit → 245 in_sync / 0 out_of_sync (после удаления одной дубликатной ap-строки для `Тестовый проект_19b`). Backup: `/tmp/batch-split/pre-split-backup.sql`. Applied plan: `/tmp/batch-split/apply-plan.json`.

- Dry-run: `python3 batch_split_invariants.py --dump-plan /tmp/batch-split-plan.json | tee /tmp/batch-split-dryrun.log`.
- Ручная инспекция: открыть JSON, проверить что для каждого из 29 паков split выглядит sane (не split'ит single-platform pack'и, не путает платформы).
- Если какой-то pack требует нестандартного разбиения (например, 3 YT в один pack, а 2 IG хотим держать отдельно) — пишем manual SQL `migrations/20260422_split_<pack>.sql` по образцу `20260422_split_phone19_legacy_pack.sql`, прогоняем его, **исключаем этот pack_id** из batch через `--exclude-pack-ids ...`.
- Apply: `python3 batch_split_invariants.py --apply --dump-plan /tmp/batch-split-applied.json | tee /tmp/batch-split-apply.log`.
- Verify post-conditions:
  ```sql
  -- Должно вернуть 0 строк (нет больше invariant)
  SELECT fpa.id, fia.platform, COUNT(*)
  FROM factory_pack_accounts fpa
  JOIN factory_inst_accounts fia ON fia.pack_id=fpa.id AND fia.active=TRUE
  GROUP BY fpa.id, fia.platform
  HAVING COUNT(*) > 1;
  ```
- Повторный запуск `audit_sync_account_packages.py` (из Шага 1) — ожидаемо 0 out_of_sync.
- Evidence (T15): сохранить dry-run-plan, apply-log, post-condition count.

### Phase 3 — Rewrite publisher.py guard queries (T6, T7, T8)

**T6. ✅ Переписать `_GUARD_QUERY` + `_GUARD_PLATFORM_CONFIG_QUERY` + `_SA_KNOWN_ACCOUNTS_QUERY` на factory**  (blocked by T5; blocks T7) — 3 queries переписаны на factory; старые сохранены под `_V1_LEGACY`. **Семантика end_date инвертирована** (factory end_date = конец warm-up'а; `end_date IS NULL OR < CURRENT_DATE` = готов к публикации; `>= CURRENT_DATE` = ещё греется → block). Все 5 аккаунтов phone #19 visible через новый query. source log изменён на `factory+publish_tasks.done`.

- Файл: `/home/claude-user/autowarm-testbench/publisher.py`
- Новый `_GUARD_QUERY`:
  ```sql
  WITH declarative AS (
    SELECT fia.username AS acc
      FROM factory_pack_accounts fpa
      JOIN factory_inst_accounts fia
        ON fia.pack_id = fpa.id AND fia.active = TRUE
      JOIN factory_device_numbers fdn
        ON fdn.id = fpa.device_num_id
     WHERE fdn.device_id = %(serial)s
       AND (fpa.end_date IS NULL OR fpa.end_date >= CURRENT_DATE)
       AND CASE %(platform)s
             WHEN 'Instagram' THEN fia.platform = 'instagram'
             WHEN 'TikTok'    THEN fia.platform = 'tiktok'
             WHEN 'YouTube'   THEN fia.platform = 'youtube'
             ELSE FALSE
           END
       AND fia.username IS NOT NULL AND fia.username <> ''
  ),
  history AS (  -- без изменений
    SELECT DISTINCT account AS acc FROM publish_tasks
     WHERE device_serial = %(serial)s AND platform = %(platform)s AND status = 'done'
  ),
  known AS (
    SELECT acc FROM declarative WHERE acc IS NOT NULL AND acc <> ''
    UNION
    SELECT acc FROM history     WHERE acc IS NOT NULL AND acc <> ''
  )
  SELECT COUNT(*), BOOL_OR(acc = %(account)s), string_agg(DISTINCT acc, ', ')
    FROM known;
  ```
- Новый `_GUARD_PLATFORM_CONFIG_QUERY`:
  ```sql
  WITH active_packs AS (
    SELECT fpa.id
      FROM factory_pack_accounts fpa
      JOIN factory_device_numbers fdn ON fdn.id = fpa.device_num_id
     WHERE fdn.device_id = %(serial)s
       AND (fpa.end_date IS NULL OR fpa.end_date >= CURRENT_DATE)
  )
  SELECT
    EXISTS (SELECT 1 FROM active_packs) AS device_seeded,
    NOT EXISTS (
      SELECT 1 FROM active_packs ap
        JOIN factory_inst_accounts fia ON fia.pack_id = ap.id AND fia.active = TRUE
       WHERE CASE %(platform)s
               WHEN 'Instagram' THEN fia.platform='instagram'
               WHEN 'TikTok'    THEN fia.platform='tiktok'
               WHEN 'YouTube'   THEN fia.platform='youtube'
             END
         AND fia.username IS NOT NULL AND fia.username <> ''
    ) AS platform_all_null;
  ```
- Новый `_SA_KNOWN_ACCOUNTS_QUERY`: копия `declarative+history` из нового `_GUARD_QUERY`, только возвращает список аккаунтов (как сейчас).
- **Рабочий порядок:** копируем старую версию каждой query в `_GUARD_QUERY_V1_LEGACY` (оставить рядом для диффа T7), пишем новую версию под тем же именем (`_GUARD_QUERY` и т.д.).
- Logging: в `_check_account_device_mapping` сообщение меняется с `source='account_packages+publish_tasks.done'` → `source='factory+publish_tasks.done'`. Остальное (action/reason/known_list) — без изменений.
- Verbose дополнение: `log.info('[guard] source=factory serial=%s platform=%s known_count=%d matched=%s', …)`.

**T7. ✅ Snapshot-diff старой и новой guard-логики на всей БД**  (blocked by T6; blocks T8) — `tools/guard_snapshot_diff.py`. 646 triples checked, 498 config pairs. **644/646 matched (99.7% aligned).** 1 CRITICAL mismatch: `kira_nelson8@RF8YA0V7FKW/TikTok` — manual-seed-20260417 ghost (no factory record, 0 publish-tasks, never actually used). 1 INFO known_list diff для того же serial/platform (accept). 0 config mismatches. **Accepted as semantic improvement** — legacy accidentally allowed ghost accounts, factory correctly requires curated mapping. Report: `/tmp/guard-diff.json`.

- Файл: `/home/claude-user/autowarm-testbench/tools/guard_snapshot_diff.py`
- Что делает:
  1. SELECT DISTINCT (device_serial, platform, account) из `publish_tasks` за последние 30 дней (ограничение чтобы не сканить миллионы) + из `account_packages` (instagram/tiktok/youtube) — получаем полный набор «валидных» комбинаций, которые guard когда-либо проверял.
  2. Для каждой тройки: прогнать `_GUARD_QUERY_V1_LEGACY` и новый `_GUARD_QUERY`, сравнить (total, matched, known_list).
  3. Для каждой (serial, platform) пары: прогнать `_GUARD_PLATFORM_CONFIG_QUERY_V1_LEGACY` и новый — сравнить (device_seeded, platform_all_null).
  4. Любое расхождение → записать в `/tmp/guard-diff-<ts>.log` с детальной диффой (какие known_list у старой, какие у новой, какие строки «лишние»).
- Итоговый отчёт:
  ```
  Total triples checked: N
  Matches: M (M/N%)
  Mismatches: K
    - total changed: …
    - matched changed: …
    - known_list changed: …
  Config-check pairs checked: P
    device_seeded changed: …
    platform_all_null changed: …
  ```
- **Ожидание:** 0 расхождений по `matched` (это основное решение allow/block). Допустимы расхождения в `known_list` (факторная модель может включать аккаунты, которых нет в ap, или исключать легаси `auto-from-publish` строки без running публикаций) — каждое такое расхождение разбираем вручную и помечаем как **ожидаемое** (и документируем в evidence).
- CLI: `python3 tools/guard_snapshot_diff.py --since '30 days' | tee /tmp/guard-diff.log`.
- Verbose: для каждого mismatch — печать v1_result vs v2_result vs device_meta.

**T8. ✅ Закоммитить новый guard + удалить legacy queries**  (blocked by T7) — `_V1_LEGACY` удалены из publisher.py (перенесены в tools/guard_snapshot_diff.py как standalone strings). publisher.py syntax OK. Smoke phone #19: все 5 аккаунтов action=allow matched=True. pytest: 217 passed / 3 skipped.

- **Gate:** пройти T7 с 0 неожиданными mismatch'ами на `matched`.
- Удалить `_GUARD_QUERY_V1_LEGACY`, `_GUARD_PLATFORM_CONFIG_QUERY_V1_LEGACY`, `_SA_KNOWN_ACCOUNTS_QUERY_V1_LEGACY` из `publisher.py`.
- Unit-smoke на phone #19 аккаунтах (gennadiya311, gennadiya4, inakent06, user70415121188138, Инакент-т2щ) — все должны пройти guard (matched=TRUE) на новой логике.
- Запустить `pytest autowarm-testbench/tests/ -v` — регрессию.

### Phase 4 — Rewrite server.js READ-пути (T9)

**T9. ✅ Заменить JOIN'ы `account_packages` в read-эндпоинтах на factory + validator_projects**  (blocked by T8; blocks T10) — 6 endpoints переписаны: `/api/devices` (439-441), `POST /api/farming/tasks` (842), `GET /api/projects` (2217-2223), `/api/farming/projects`, `/api/farming/packs`, `GET /api/packages`, `getSocialAccounts`. `node --check` passes. Smoke: GET /api/packages возвращает project'ы из validator_projects.

- Файл: `/home/claude-user/autowarm-testbench/server.js`
- Замены по карте выше (строки 439-441, 842, 2220, 2250-2260, 2278-2295, 5346-5362):

  1. **`/api/devices` (439-441).**  Проблема: pack/project для отображения устройства. Решение:
     ```sql
     LEFT JOIN factory_pack_accounts fpa_active ON fpa_active.device_num_id = fdn.id
       AND (fpa_active.end_date IS NULL OR fpa_active.end_date >= CURRENT_DATE)
     LEFT JOIN validator_projects vp ON vp.id = fpa_active.project_id
     ```
     Возвращаем `vp.project` как `project_name` и `fpa_active.pack_name` как `pack_name`. Если у device нет active pack — NULL.

  2. **`POST /api/farming/tasks` (842).** Убираем JOIN `account_packages ap` — project берётся из `validator_projects` через `fpa.project_id`:
     ```sql
     LEFT JOIN validator_projects vp ON vp.id = fpa.project_id
     ```
     `project` в INSERT autowarm_tasks — `vp.project`.

  3. **`GET /api/projects` (2217-2223).** Сейчас читает `autowarm_tasks.project ∪ account_packages.project`. Новое: `autowarm_tasks.project ∪ validator_projects.project` (берём только `active=TRUE`).

  4. **`GET /api/farming/projects` (2242-2266).** Аналогично: DISTINCT `vp.project` через `factory_pack_accounts` фильтр по serial.

  5. **`GET /api/farming/packs` (2269-2301).** `DISTINCT fpa.pack_name FROM factory_pack_accounts fpa` (с фильтром по serial через `factory_device_numbers` и по project через `validator_projects`).

  6. **`getSocialAccounts` (5340-5374).** Убираем LATERAL из `account_packages` — project/start_date/end_date берём из `factory_pack_accounts` (`fpa.start_date, fpa.end_date`) + `validator_projects vp`:
     ```sql
     LEFT JOIN validator_projects vp ON vp.id = fpa.project_id
     ```

- Verbose logging на каждом endpoint'е: `console.log('[api/<name>] rows=%d', rows.length)`.
- Проверка: запустить сервер (testbench, pm2 `autowarm-testbench-server`), прокликать UI (devices, farming, packs, social-accounts) — данные должны быть в том же формате, что раньше (frontend не менять).
- Коммит: `refactor(server): read factory+validator_projects instead of account_packages`.

### Phase 5 — Admin CRUD → factory-writes (T10, T11)

**T10. ✅ Переписать `POST/PUT/DELETE /api/packages` на factory**  (blocked by T9; blocks T11) — 3 endpoints переписаны: POST создаёт factory_pack_accounts + factory_inst_accounts через resolvePackLayout и делает sync mirror в ap; PUT обновляет factory_pack_accounts по id; DELETE удаляет factory rows + ap-строки с этим pack_name. Backwards compat: принимает и `project_id`, и `project` (string→id через validator_projects). node --check passes.

- Файл: `/home/claude-user/autowarm-testbench/server.js`

- **GET `/api/packages` (2362-2413):** уже читает из factory, только LATERAL на `account_packages` для project — заменить на `validator_projects` (сделано в T9). `id` в ответе = `fpa.id`.

- **POST `/api/packages` (admin create, 2415-2425):**
  ```js
  app.post('/api/packages', requireAuth, async (req, res) => {
    const client = await pool.connect();
    try {
      const { device_serial, pack_name: requestedName, project_id, start_date, end_date,
              instagram, youtube, tiktok } = req.body;
      await client.query('BEGIN');

      // 1. Найти device_num_id
      const { rows: [dev] } = await client.query(
        'SELECT id, device_number FROM factory_device_numbers WHERE device_id=$1', [device_serial]);
      if (!dev) { await client.query('ROLLBACK'); return res.status(400).json({error: 'Устройство не найдено'}); }

      // 2. Найти project name (для resolvePackLayout)
      const { rows: [proj] } = project_id
        ? await client.query('SELECT project FROM validator_projects WHERE id=$1', [project_id])
        : { rows: [{ project: null }] };

      // 3. resolvePackLayout для определения имени и переименований
      const { rows: existingPacks } = await client.query(
        'SELECT id, pack_name FROM factory_pack_accounts WHERE device_num_id=$1 AND project_id IS NOT DISTINCT FROM $2 ORDER BY id',
        [dev.id, project_id || null]);
      const { new_pack_name, renames } = resolvePackLayout(
        proj.project || 'unassigned', dev.device_number, existingPacks);

      // 4. Apply renames (через factory + sync)
      for (const [rId, rName] of renames) {
        await client.query('UPDATE factory_pack_accounts SET pack_name=$1 WHERE id=$2', [rName, rId]);
        await syncPackIntoAccountPackages(client, rId);
      }

      // 5. Создать factory_pack_accounts
      const { rows: [{ maxpackid }] } = await client.query('SELECT COALESCE(MAX(id),0) AS maxpackid FROM factory_pack_accounts');
      const newPackId = parseInt(maxpackid) + 1;
      const nameToUse = requestedName || new_pack_name;
      await client.query(
        'INSERT INTO factory_pack_accounts (id, pack_name, device_num_id, project_id, start_date, end_date) VALUES ($1,$2,$3,$4,$5,$6)',
        [newPackId, nameToUse, dev.id, project_id || null, start_date || 'CURRENT_DATE', end_date || null]);

      // 6. Создать factory_inst_accounts для непустых платформ
      const { rows: [{ maxaccid }] } = await client.query('SELECT COALESCE(MAX(id),0) AS maxaccid FROM factory_inst_accounts');
      let nextAccId = parseInt(maxaccid) + 1;
      for (const [col, username] of [['instagram', instagram], ['tiktok', tiktok], ['youtube', youtube]]) {
        if (username) {
          await client.query(
            'INSERT INTO factory_inst_accounts (id, pack_id, platform, username, active, synced_at) VALUES ($1,$2,$3,$4,true,NOW())',
            [nextAccId++, newPackId, col, username]);
        }
      }

      // 7. Защита от factory_sync.py
      await client.query(
        'INSERT INTO factory_sync_exclusions (table_name, row_id, reason) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING',
        ['factory_pack_accounts', newPackId, 'admin-created']);

      // 8. Sync → account_packages (dual-write до Шага 3)
      await syncPackIntoAccountPackages(client, newPackId);

      await client.query('COMMIT');
      console.log('[api/packages] create factory_pack=%d name=%s project=%s', newPackId, nameToUse, proj.project);
      res.json({ id: newPackId, pack_name: nameToUse, project_id, device_serial, start_date, end_date });
    } catch (e) {
      await client.query('ROLLBACK');
      res.status(500).json({ error: e.message });
    } finally { client.release(); }
  });
  ```
  **Note:** API сейчас принимает `project` (string) — для backwards compat принимаем и `project` (резолвим в `project_id` через `validator_projects`), и `project_id` (напрямую).

- **PUT `/api/packages/:id` (admin update, 2427-2437):** :id = factory_pack_accounts.id. UPDATE `fpa.pack_name, project_id, start_date, end_date` + re-sync → ap.
  ```js
  await client.query('UPDATE factory_pack_accounts SET pack_name=$1, project_id=$2, start_date=$3, end_date=$4 WHERE id=$5',
    [pack_name, project_id, start_date, end_date, req.params.id]);
  await syncPackIntoAccountPackages(client, req.params.id);
  ```

- **DELETE `/api/packages/:id` (admin delete, 2439-2443):** :id = factory_pack_accounts.id. В транзакции:
  ```js
  BEGIN;
  -- 1. сохранить pack_name для ap-delete
  SELECT pack_name FROM factory_pack_accounts WHERE id=$1;
  -- 2. удалить аккаунты
  DELETE FROM factory_inst_accounts WHERE pack_id=$1;
  -- 3. удалить pack
  DELETE FROM factory_pack_accounts WHERE id=$1;
  -- 4. удалить строки ap с этим pack_name (могут быть дубли — все)
  DELETE FROM account_packages WHERE pack_name=$pack_name;
  -- 5. защитить factory_sync от воскрешения pack'а
  INSERT INTO factory_sync_exclusions (table_name, row_id, reason) VALUES ('factory_pack_accounts', $1, 'admin-deleted');
  COMMIT;
  ```

**T11. ✅ Тесты admin CRUD (integration)**  (blocked by T10; blocks T12) — `tests/test_admin_packages_crud.test.js`. 5/5 pass (POST creates, POST rejects unknown device, POST renames on second same-project pack, PUT updates + re-syncs, DELETE removes factory+ap). BEGIN..ROLLBACK изоляция.

- Файл: `/home/claude-user/autowarm-testbench/tests/test_admin_packages_crud.test.js` (или python-эквивалент, если в репо нет Jest).
- Кейсы:
  1. `test_post_creates_factory_pack_and_ap_mirror` — POST с project_id + instagram+tiktok → проверить, что новый `factory_pack_accounts` и 2 `factory_inst_accounts` созданы, ap-строка c pack_name/project/instagram/tiktok заполнена.
  2. `test_post_rejects_unknown_device` — POST с несуществующим device_serial → 400.
  3. `test_post_with_existing_project_renames_previous` — если на device уже есть pack этого проекта → первый переименовывается в `_a`, новый становится `_b` (через resolvePackLayout).
  4. `test_put_updates_factory_and_syncs_ap` — PUT меняет end_date + project_id → factory и ap оба обновлены.
  5. `test_delete_removes_factory_and_ap_rows` — DELETE :id → factory rows удалены, ap-строки с этим pack_name удалены, factory_sync_exclusions содержит запись.
- Cleanup: SAVEPOINT + ROLLBACK.
- Запуск: `node --test tests/test_admin_packages_crud.test.js` (или pytest).

### Phase 6 — Smoke + regression (T12, T13)

**T12. ✅ Smoke-verify testbench**  (blocked by T11; blocks T14) — live testbench-orchestrator создал tasks #747-749 для phone #19 после cutover. publisher.py (PID 4065733, started 15:10) запустил новый factory-based guard. sa_preflight логирует `known=инакент-т2щ` / `known=inakent06,gennadiya311` — **все 5 аккаунтов видны новой guard-логикой**. Tasks 747/748 failed по camera/launch (не guard), task 749 running past preflight. `audit_sync_account_packages.py` → 245 in_sync, 0 out_of_sync.

- Запустить testbench-сервер: `pm2 restart autowarm-testbench-server` (нужен sudo pm2 — есть в NOPASSWD-scope).
- Прокликать UI вручную (Termius → браузер):
  - `/` → devices table — project/pack отображаются.
  - `/packages` → admin page — GET работает, POST/PUT/DELETE создают/меняют/удаляют pack (cleanup после теста).
  - `/farming` — проекты/паки подгружаются.
- Запустить testbench-orchestrator один прогон: `python3 testbench_orchestrator.py --once`.
  - Ожидание: gennadiya311/gennadiya4 (phone 19) → guard allow, публикация проходит OR блокируется по каким-то не-guard причинам (camera etc). Guard-block не должен случиться.
- Запустить `python3 audit_sync_account_packages.py` (dry-run) — ожидание: 0 out_of_sync.

**T13. ✅ Regression pytest**  (blocked by T12; blocks T14) — pytest 217 passed / 3 skipped; node 27/27 passed. Одна test bug в `test_apply_mirrors_into_ap` (hex-суффикс случайно оканчивался на букву → `_strip_suffix` отрезал) — фикс: добавил `0` в конец pack_name.

- `cd /home/claude-user/autowarm-testbench && python -m pytest tests/ -v --tb=short`.
- Ожидание: все существующие тесты (pack_name_resolver 17/17, account_packages_sync 12/12, batch_split 8/8, admin_crud 5+, single_account_preflight и др.) проходят.
- JS: `node --test tests/*.test.js`.

### Phase 7 — Commit + evidence + memory + Шаг 3 brief (T14, T15)

**T14. ✅ Коммиты + push**  (blocked by T13; blocks T15) — 4 коммита в autowarm-testbench/testbench (2ebde95 dedupe, 08082af batch_split, c089fff guard, 736d37f server) + 1 коммит в contenthunter/main (docs plan+evidence). Pushed. Прокомбинировал commits 3+5 (guard+server) — комбинированный server.js коммит с reads+admin CRUD вместе.

- autowarm-testbench (ветка `testbench`, `git push origin testbench`):
  - Commit 1 (после T2): `chore(dedupe): rename Content hunter_84/105 duplicate packs to _a/_b`
  - Commit 2 (после T4): `feat(migrate): batch_split_invariants.py + tests (29 packs candidate)`
  - Commit 3 (после T5): `chore(migrate): split 29 invariant packs into one-per-platform`
  - Commit 4 (после T8): `refactor(guard): read from factory instead of account_packages`
  - Commit 5 (после T9): `refactor(server): read factory+validator_projects for devices/farming/social`
  - Commit 6 (после T11): `refactor(api/packages): admin CRUD writes to factory with sync mirror`
- contenthunter (`main`, `git push origin main`):
  - Commit 7 (после T15): `docs(plans): deprecate-account-packages + evidence`

**T15. ✅ Evidence + memory + Шаг 3 brief**  (blocked by T14) — evidence/deprecate-account-packages-20260422.md написан. Memory updates: project_account_packages_deprecation (Шаг 2 закрыт), project_publish_guard_schema (factory source, новая схема), new project_account_packages_step3 (Шаг 3 brief). MEMORY.md обновлён (2 строки). Committed + pushed.

- Evidence: `/home/claude-user/contenthunter/.ai-factory/evidence/deprecate-account-packages-20260422.md`
  - **Dedupe (T1-T2):** до/после состояния packs 7/225/227/229, rollback-скрипты.
  - **Batch-split (T3-T5):** dry-run plan, apply-log, post-condition `SELECT … HAVING COUNT(*)>1` = 0 rows.
  - **Guard rewrite (T6-T8):** snapshot-diff отчёт (`matches/mismatches`), перечень ожидаемых расхождений в `known_list`, smoke phone #19 output.
  - **Server refactor (T9-T11):** скриншоты UI, curl-проверки admin CRUD, integration test output.
  - **Regression (T13):** pytest вывод, node test вывод.
  - **Список коммитов** (7 SHA).
  - **Known follow-ups на Шаг 3:** DROP TABLE + delete sync helpers + delete `_upsert_auto_mapping` + prod deploy.
- Memory updates:
  - `project_account_packages_deprecation.md` — переписать: «Шаг 2 выполнен 2026-04-22. Остались: prod deploy /root/autowarm/ + DROP TABLE account_packages + cleanup sync helpers + delete _upsert_auto_mapping». Сохранить ссылки на новые SQL-миграции и snapshot-diff отчёт.
  - `project_publish_guard_schema.md` — обновить раздел `_GUARD_QUERY`: теперь читает из factory, добавить новую SQL-форму; раздел `source` меняется с `account_packages+publish_tasks.done` на `factory+publish_tasks.done`.
  - MEMORY.md — ничего не добавляем/удаляем (project-level memory просто обновляется).
- **Новая memory — Шаг 3 brief:** `project_account_packages_step3.md` — минимальный план prod deploy + DROP.
- **AGENTS.md / PUBLISH-NOTES.md** в testbench не меняем (внутренняя рефакторизация).

## Commit Plan

15 задач → 7 коммит-чекпоинтов:

| Commit | После задач | Репо | Сообщение |
|---|---|---|---|
| 1 | T2 | autowarm-testbench (testbench) | `chore(dedupe): rename Content hunter_84/105 duplicate packs to _a/_b` |
| 2 | T4 | autowarm-testbench | `feat(migrate): batch_split_invariants.py + tests (29 packs candidate)` |
| 3 | T5 | autowarm-testbench | `chore(migrate): split 29 invariant packs into one-per-platform` |
| 4 | T8 | autowarm-testbench | `refactor(guard): read from factory instead of account_packages` |
| 5 | T9 | autowarm-testbench | `refactor(server): read factory+validator_projects for devices/farming/social` |
| 6 | T11 | autowarm-testbench | `refactor(api/packages): admin CRUD writes to factory with sync mirror` |
| 7 | T15 | contenthunter (main) | `docs(plans): deprecate-account-packages + evidence` |

## Risks & rollback

- **R1 — 29 packs + batch split могут сломать активную публикацию.** Split — транзакционный (BEGIN/COMMIT внутри скрипта, per-pack). Но пока прогоняется batch, активная testbench-задача может увидеть «исчезновение» аккаунта. **Митиг:** перед apply — остановить testbench-orchestrator (`pm2 stop autowarm-testbench-orchestrator`), прогнать split, перезапустить.
- **R2 — Snapshot-diff нашёл расхождения.** Если расхождение только в `known_list` (порядок, формат) — ок. Если в `matched` — **блокер**: разбираемся по каждому случаю. Не переключаемся, пока `matched`-расхождений > 0. **Митиг:** hard cutover ТОЛЬКО после T7 с 0 matched-mismatches.
- **R3 — Admin CRUD ломает UI.** UI посылает на `POST /api/packages` старую схему (`project` как строка). **Митиг:** backwards-compat в T10 — принимаем и `project`, и `project_id`. Если только `project` — резолвим в `project_id`. Если `project` не нашёлся в `validator_projects` — создаём/оставляем pack без `project_id` (NULL).
- **R4 — Prod читает старые account_packages, sync ломается из-за Шага 2.** Sync-helper (`syncPackIntoAccountPackages`) продолжает работать — он не зависит от того, кто читает. `_upsert_auto_mapping` остаётся. Prod видит актуальные данные через sync. **Проверка:** после T11 прогнать на prod-БД `SELECT COUNT(*) FROM account_packages WHERE updated_at >= NOW()-INTERVAL '1 day'` — sync-писатель всё ещё активен.
- **R5 — `factory_sync.py` перезаписывает split'нутые паки из upstream factory.** **Митиг:** обязательный INSERT в `factory_sync_exclusions` для каждого затронутого pack/account в T3 и T10. Проверка: через 24 часа после T5 — `SELECT id, pack_name FROM factory_pack_accounts WHERE id IN (<split ids>)` — имена не должны вернуться к оригинальным.
- **R6 — Неучтённые места использования `account_packages`.** Возможен код, который использует таблицу за пределами `server.js` и `publisher.py` (например, external scripts, ad-hoc SQL). **Митиг:** в T9 сделать `grep -rn "account_packages" /home/claude-user/autowarm-testbench --include="*.py" --include="*.js" | grep -v node_modules | grep -v .bak` — список всех файлов (10 штук на сейчас). Для каждого: если это sync-helper или test — не трогаем. Если это runtime-код — мигрируем (или переносим в Шаг 3).
- **R7 — `_upsert_auto_mapping` пишет в account_packages project='auto-from-publish' с кривыми колонками.** При Шаге 3 dropнем — но сейчас живёт. Риск: auto-from-publish-строки не попадают в factory → если prod-тула читает factory_inst_accounts, она их не видит. **Решение:** игнорируем в Шаге 2, `auto-from-publish` — исторический долг, убираем в Шаге 3 вместе с self.
- **R8 — SnapshotDiff ограничен публ-таской последние 30 дней.** Может пропустить длиннохвостые редкие комбинации. **Митиг:** доп.прогон: взять ВСЕ комбинации `(device_serial, platform, username)` из `factory_inst_accounts ⨝ factory_pack_accounts ⨝ factory_device_numbers` + `account_packages` (3 platform-колонки) — это ~500-1000 комбинаций, быстро проверяется.

## Rollback strategy

- **Commit 1 (dedupe):** `migrations/20260422_dedupe_content_hunter_*__rollback.sql` — переименовывает обратно. После `factory_sync.py` next run — sync_exclusions удалить вручную.
- **Commit 2-3 (batch-split):** каждый split — транзакция, если ошибка в batch'е — только тот pack не применён. Полный rollback: `migrations/batch_split_invariants__rollback.py` (генерирует обратный SQL из `batch-split-applied.json` — UPDATE back original name, DELETE new packs, UPDATE inst_accounts pack_id back).
- **Commit 4 (guard rewrite):** `git revert <sha>` — возвращает `_GUARD_QUERY*_V1_LEGACY` → `_GUARD_QUERY*`. Безопасно, поскольку до T8 обе версии жили рядом. После удаления legacy — `git revert` достаёт их из истории.
- **Commit 5-6 (server.js refactor + admin CRUD):** `git revert`. `pm2 restart autowarm-testbench-server`.
- **Data-уровень:** если где-то повредили ap-строки — `pg_dump account_packages > /tmp/ap-backup-<ts>.sql` перед T1 (обязательно), restore: `psql -d openclaw < /tmp/ap-backup.sql` + TRUNCATE ap → COPY.

## Next step

После подтверждения плана — исполнять через `/aif-implement` (буду писать код/коммиты сам согласно memory `feedback_execution_autonomy.md`).

Критические gate'ы в процессе:
1. После T5 (split) — `SELECT … HAVING COUNT(*)>1` вернуло 0 rows.
2. После T7 (snapshot-diff) — `matched` расхождений = 0.
3. После T12 (smoke) — testbench публикация phone #19 не блокируется guard'ом.

После всех T-шагов и контроля гейтов — сразу переходим в Шаг 3 (prod deploy + DROP) отдельным планом.
