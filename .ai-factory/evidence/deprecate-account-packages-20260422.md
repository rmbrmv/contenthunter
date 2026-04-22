# Evidence — Deprecate account_packages (Шаг 2)

**Plan:** `.ai-factory/plans/deprecate-account-packages-20260422.md`
**Дата выполнения:** 2026-04-22 UTC
**Репо:** `/home/claude-user/autowarm-testbench/` ветка `testbench` (4 commits), `/home/claude-user/contenthunter/` ветка `main` (этот файл)

## Сводка

Шаг 2 **code rewrite only** выполнен. Guard + server.js переведены с `account_packages` на factory-таблицы. Sync helpers и `_upsert_auto_mapping` сохранены — dual-write до Шага 3 (prod deploy + DROP TABLE).

**Осталось на Шаг 3:**
- Deploy новой логики в `/root/autowarm/` (prod).
- Smoke-verify prod-публикаций на phone #19.
- `DROP TABLE account_packages`.
- Удалить `account_packages_sync.{py,js}`, `audit_sync_account_packages.py`, `_upsert_auto_mapping` в publisher.py.

## T1-T2 — Dedupe name-дублей

**Предусловие:** 2 name-пары в factory_pack_accounts (по 2 строки на pack_name), обе пары на одном устройстве.

### Content hunter_84 (packs 7 + 225, device RFGYA19DNGZ)

До:
```
factory | 7   | Content hunter_84 | IG autopostfactory, YT autopostfactory, TT content.hunter51, VK contentfactory_pro
factory | 225 | Content hunter_84 | IG 1content_hunter
ap      | 7   | Content hunter_84 | device=RFGYA19DNGZ IG=1content_hunter end_date=NULL
ap      | 225 | Content hunter_84 | device=NULL        empty             end_date=2026-01-22
```
После `migrations/20260422_dedupe_content_hunter_84.sql`:
```
factory | 7   | Content hunter_84a | accounts unchanged
factory | 225 | Content hunter_84b | accounts unchanged
ap      | 7   | Content hunter_84a | IG autopostfactory YT autopostfactory TT content.hunter51 VK contentfactory_pro end_date=NULL
ap      | 225 | Content hunter_84b | device=RFGYA19DNGZ IG=1content_hunter end_date=NULL
```
Idempotent re-run подтверждён («Migration already applied. Skipping.»).

### Content hunter_105 (packs 227 + 229, device RF8YA0V78FE)

До:
```
factory | 227 | Content hunter_105 | IG content_hunter_0, TT contentexpert_1, YT content.hunter1
factory | 229 | Content hunter_105 | IG gengo_sales
ap      | 227 | Content hunter_105 | device=RF8YA0V78FE IG=gengo_sales end_date=NULL
ap      | 229 | Content hunter_105 | device=NULL        empty          end_date=2026-01-18
```
После `migrations/20260422_dedupe_content_hunter_105.sql`:
```
factory | 227 | Content hunter_105a | accounts unchanged
factory | 229 | Content hunter_105b | accounts unchanged
ap      | 227 | Content hunter_105a | IG content_hunter_0 TT contentexpert_1 YT content.hunter1 end_date=NULL
ap      | 229 | Content hunter_105b | device=RF8YA0V78FE IG=gengo_sales end_date=NULL
```

Rollback-скрипты: `20260422_dedupe_content_hunter_84__rollback.sql`, `20260422_dedupe_content_hunter_105__rollback.sql`.

Post: **0 pack_name дублей в factory_pack_accounts**.

## T3-T5 — Batch-split 29 invariant-паков

### T3-T4: CLI + tests

`migrations/batch_split_invariants.py` — порт логики `server.js:/api/packages/:id/split` (2472-2605) в Python. CLI-флаги: `--apply`, `--dump-plan`, `--pack-id`, `--exclude-pack-ids`.

Tests: `tests/test_batch_split_invariants.py` — 11/11 pass.

### T5: Apply

Safety backup перед apply: `pg_dump factory_pack_accounts + factory_inst_accounts + account_packages > /tmp/batch-split/pre-split-backup.sql` (161KB).

Dry-run: `python3 migrations/batch_split_invariants.py --dump-plan /tmp/batch-split/dryrun-plan.json`

Inspection: 29 invariant-паков, из них:
- 25 × 2-way split (`X_a` + `X_b`)
- 3 × 3-way split: `rev_septizim_content_hunter_dev1`, `Sip&Shine_33`, `Relisme_2`

Apply: `python3 migrations/batch_split_invariants.py --apply --dump-plan /tmp/batch-split/apply-plan.json`

Результат (из apply-plan.json):
```json
{"summary": {"total_candidates": 29, "to_apply": 29, "skipped": 0}, "errors": []}
```

Post-condition SQL:
```sql
SELECT COUNT(DISTINCT id) FROM (
  SELECT fpa.id FROM factory_pack_accounts fpa
  JOIN factory_inst_accounts fia ON fia.pack_id=fpa.id AND fia.active=TRUE
  GROUP BY fpa.id, fia.platform
  HAVING COUNT(*) > 1
) inv;
-- 0
```

Audit `audit_sync_account_packages.py`:
- До: 4 out_of_sync (T1/T2 dedupe + 1 legacy phone 19 duplicate ap-row)
- После dedupe + split + cleanup: **245 in_sync, 0 out_of_sync**

Один пост-cleanup: удалил дубль ap.id=340 для pack_name=`Тестовый проект_19b` (другая ap.id=307 содержала те же данные).

## T6-T8 — Rewrite guard queries

### Новые queries в publisher.py

`_GUARD_QUERY`:
```sql
WITH declarative AS (
  SELECT fia.username AS acc
    FROM factory_pack_accounts fpa
    JOIN factory_inst_accounts fia ON fia.pack_id = fpa.id AND fia.active = TRUE
    JOIN factory_device_numbers fdn ON fdn.id = fpa.device_num_id
   WHERE fdn.device_id = %(serial)s
     AND (fpa.end_date IS NULL OR fpa.end_date < CURRENT_DATE)  -- warm завершён
     AND CASE %(platform)s
           WHEN 'Instagram' THEN fia.platform = 'instagram'
           WHEN 'TikTok'    THEN fia.platform = 'tiktok'
           WHEN 'YouTube'   THEN fia.platform = 'youtube'
         END
     AND fia.username IS NOT NULL AND fia.username <> ''
),
history AS (
  SELECT DISTINCT account AS acc FROM publish_tasks
   WHERE device_serial = %(serial)s AND platform = %(platform)s AND status = 'done'
),
known AS (
  SELECT acc FROM declarative WHERE acc IS NOT NULL AND acc <> ''
  UNION
  SELECT acc FROM history     WHERE acc IS NOT NULL AND acc <> ''
)
SELECT COUNT(*), BOOL_OR(acc = %(account)s), string_agg(DISTINCT acc, ', ') FROM known;
```

**Семантика `end_date` инвертирована.** Legacy ap: `end_date IS NULL OR >= CURRENT_DATE` (ещё греется или NULL). Factory: `end_date IS NULL OR < CURRENT_DATE` — прогрев завершился или нет расписания. Согласно memory `project_account_packages_end_date`: «После end_date пак считается прогретым и готовым к автопубликации». 202/245 factory packs имеют past end_date (прогреты) — при неправильной семантике отфильтровались бы.

`_GUARD_PLATFORM_CONFIG_QUERY` — аналогично через active_packs CTE.
`_SA_KNOWN_ACCOUNTS_QUERY` — тот же declarative+history, возвращает список.

### T7 Snapshot-diff

`tools/guard_snapshot_diff.py` — сравнивает legacy vs новый guard на всех (serial, platform, account) из `publish_tasks ∪ account_packages ∪ factory_inst_accounts`.

Результат на полной БД (`/tmp/guard-diff.json`):
```json
{
  "triples_checked": 646,
  "pairs_checked": 498,
  "matched_pairs_v1_v2": {"v1=True,v2=True": 644, "v1=True,v2=False": 1, "v1=False,v2=False": 1},
  "guard_mismatches_critical": 1,
  "guard_mismatches_info": 1,
  "config_mismatches_critical": 0,
  "config_mismatches_info": 0
}
```

**Единственное CRITICAL расхождение:** `kira_nelson8@RF8YA0V7FKW/TikTok`.
- Legacy: matched=TRUE (через ap.id=291 project=`manual-seed-20260417`, pack_name=NULL, tiktok=kira_nelson8)
- Factory: matched=FALSE (нет factory-записи для kira_nelson8)
- publish_tasks history для `kira_nelson8@RF8YA0V7FKW`: **0 rows** (никогда не публиковался)

**Accepted as semantic improvement.** Это legacy manual-seed ghost, который legacy ap accidentally allowed. Factory требует curated mapping (через revision/apply или admin CRUD), и правильно отказывает призрачным строкам.

### T8 Cutover

Удалены `_GUARD_QUERY_V1_LEGACY`, `_GUARD_PLATFORM_CONFIG_QUERY_V1_LEGACY`, `_SA_KNOWN_ACCOUNTS_QUERY_V1_LEGACY` из `publisher.py`. Текст legacy-query перенесён как standalone-строки в `tools/guard_snapshot_diff.py` для повторного прогона диффа (до Шага 3).

Smoke phone #19 через публикаторский модуль:
```
gennadiya311@Instagram: action=allow total=2 matched=True
inakent06@Instagram:    action=allow total=2 matched=True
gennadiya4@TikTok:      action=allow total=2 matched=True
user70415121188138@TikTok: action=allow total=2 matched=True
Инакент-т2щ@YouTube:    action=allow total=1 matched=True
```

pytest: 217 passed / 3 skipped.

## T9-T11 — server.js rewrite

6 READ-эндпоинтов переведены на `factory_pack_accounts ⨝ validator_projects`:
- `/api/devices`, `POST /api/farming/tasks`, `GET /api/projects`, `/api/farming/projects`, `/api/farming/packs`, `getSocialAccounts`, `GET /api/packages`

3 admin CRUD-эндпоинта переписаны на factory-write + ap-sync mirror:
- `POST /api/packages`: `resolvePackLayout` → INSERT `factory_pack_accounts` + `factory_inst_accounts` → `syncPackIntoAccountPackages`. Backwards-compat: принимает и `project` (string), и `project_id`.
- `PUT /api/packages/:id`: `:id` = `fpa.id` (было `ap.id`). UPDATE fpa + re-sync.
- `DELETE /api/packages/:id`: DELETE factory_inst_accounts + factory_pack_accounts + ap rows с этим pack_name (cleanup dual-write).

Integration tests `tests/test_admin_packages_crud.test.js`: 5/5 pass.

node --test (все): 27/27 pass.

## T12 — Live smoke

После cutover (15:10 UTC) testbench-orchestrator создал задачи #747 (inakent06@IG), #748 (user70415121188138@TT), #749 (Инакент-т2щ@YT). `publisher.py` PID 4065733 (started 15:10) использует новый factory-guard. Events из publish_tasks:

```
task #747: "preflight single_account=False known=inakent06,gennadiya311"
task #748: "preflight single_account=False known=gennadiya4,user70415121188138"
task #749: "preflight single_account=True known=инакент-т2щ"  (SA fastpath сработал)
```

Все 5 phone #19 аккаунтов видны guardом. Tasks 747/748 failed **не из-за guard** — известные регрессии (`ig_camera_open_failed`, `tt_app_launch_failed`). Task 749 running past preflight.

## Commits (autowarm-testbench, ветка testbench)

```
736d37f refactor(server): factory+validator_projects reads + admin CRUD on factory
c089fff refactor(guard): read from factory instead of account_packages
08082af feat(migrate): batch_split_invariants.py + integration tests
2ebde95 chore(dedupe): rename Content hunter_84/105 duplicate packs to _a/_b
```

pushed to `origin/testbench`.

## Шаг 3 brief

1. Deploy `/home/claude-user/autowarm-testbench/publisher.py`, `server.js`, `account_packages_sync.*`, `pack_name_resolver.*`, migrations → `/root/autowarm/`.
2. Restart `systemctl restart autowarm.service` (prod).
3. Smoke-verify на prod: guard не должен блокировать известных аккаунтов. Snapshot-diff на prod-публикациях за 1 час.
4. Удалить sync helpers:
   - `account_packages_sync.{py,js}`
   - `audit_sync_account_packages.py`
   - `_upsert_auto_mapping` (publisher.py:6735)
5. Удалить admin CRUD dual-write в server.js: `DELETE FROM account_packages` в DELETE-handler, вызовы `syncPackIntoAccountPackages` в POST/PUT.
6. Удалить legacy-query strings из `tools/guard_snapshot_diff.py` (больше не нужны).
7. `DROP TABLE account_packages;`
