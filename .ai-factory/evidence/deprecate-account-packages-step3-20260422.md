# Evidence — Шаг 3: deploy на prod + DROP TABLE account_packages

**Дата:** 2026-04-22 UTC (вечером, сразу после Шага 2)
**Prod path:** `/root/.openclaw/workspace-genri/autowarm/` (pm2 id=1 `autowarm`)
**Plan:** memory `project_account_packages_step3.md` (brief), без formal plan-файла
**Репо:** `GenGo2/delivery-contenthunter` ветка `main` — 3 коммита (6e3f4c3, 17b8961, 5c6c432)

## Сводка

`account_packages` **удалена** из БД. Prod переведён на factory-модель целиком. Sync helpers, `_upsert_auto_mapping`, `audit_sync_account_packages.py`, `batch_split_invariants.py`, `guard_snapshot_diff.py` удалены. DROP TABLE выполнен после smoke-теста.

## Состояние prod перед Шагом 3

Обнаружено отклонение от brief:
- **Prod-путь: `/root/.openclaw/workspace-genri/autowarm/`** (не `/root/autowarm/` как в старой memory).
- Prod запущен через `pm2 autowarm` (не systemd).
- Prod-репо — тот же `GenGo2/delivery-contenthunter`, но на ветке `main`, отстаёт от `origin/testbench` на 20+ коммитов.
- Prod main имел **5 uncommitted файлов + 10 untracked**: TT-publishing-resolution работа (T4/T5/T_FG в account_switcher.py, PUBLISH-NOTES.md обновления), scheduler.js фильтр `testbench=FALSE`, UI testbench icon, и частично скопированные sync helpers (`account_packages_sync.js`, `pack_name_resolver.js` — идентичные testbench-версиям).

## Выполненные шаги

### S1. Анализ prod state
- Диффы всех 5 modified файлов изучены. Все содержат prod-only работу, которую нужно сохранить.
- 10 untracked: 2 идентичны testbench (sync.js, resolver.js), остальные 8 — prod-only (TT plans/scripts/tests, dashboard, .ai-factory/patches).

### S2. Safety backup
- `pg_dump factory_* + account_packages > /tmp/step3-backup/db-data-only.sql` (173KB).
- Copy of 5 modified prod files + full prod public/, scripts/, tests/, .ai-factory/ tree to `/tmp/step3-backup/`.

### S3. Memory fix
- `project_account_packages_step3.md`: обновлён путь `/root/.openclaw/workspace-genri/autowarm/`, restart → `sudo pm2 restart autowarm`.

### S4. Git merge
- Удалены untracked copies identical-to-testbench (sync.js, resolver.js) + server.js.bak — их восстановит merge.
- Commit (6e3f4c3) `prod-local: TT-publishing-resolution + testbench=FALSE scheduler filter` — консолидирует 5 M файлов + 8 untracked prod-only файлов в main.
- `git merge origin/testbench` — auto-merged account_switcher.py (оба набора изменений сохранились: testbench SA-preflight + prod TT-logged-out markers). Conflict только в server.js (2 блока в `GET /api/packages` и `getSocialAccounts` — взяты factory-native versions).
- Merge commit 17b8961 — **20+ testbench коммитов (Шаг 1 + Шаг 2 + testbench-specific addons) попадают в main**.
- Удалён `node_modules`-symlink (self-reference на prod path). `npm install` восстановил модули (90 пакетов).

### S5-S6. pm2 restart + smoke
- `sudo pm2 restart autowarm` (NOPASSWD). uptime 3s, status online, restarts=170.
- `/api/devices` → 200, 89KB (тот же объём что до deploy).
- Snapshot-diff на prod: `644/646 matched (99.7%)`, 1 CRITICAL `kira_nelson8@RF8YA0V7FKW/TikTok` (ghost, accepted same as testbench), 0 config mismatches.

### S7. Regression watch
- Prod не производит задач вне working hours (последняя `testbench=FALSE` задача #710 в 06:52, сейчас 16:17). Живую проверку guard на prod трафике проверить не удалось — ждём следующего working hours цикла.
- PM2 logs clean (только routine `[assign-queue]`, `[collectDeviceMetrics]` — existing behavior).

### S8. Cleanup — remove dual-write
- `publisher.py`: удалён `_upsert_auto_mapping` + call site (line 6335). Log-strings с `account_packages` заменены на `factory`.
- `server.js` (12 мест):
  - 3 `syncPackIntoAccountPackages` вызова в admin CRUD (POST/PUT + rename loop) удалены.
  - `DELETE FROM account_packages WHERE pack_name=$1` в admin DELETE удалён.
  - `/api/devices/:serial/revision/apply`: убран sync-блок + `touchedPackIds`/`syncReports`/`PackInvariantError` handling.
  - `require('./account_packages_sync.js')` убран.
- `scripts/tt_session_audit.py`: 2 SQL-query `FROM account_packages` переписаны на `factory_inst_accounts ⨝ factory_pack_accounts ⨝ factory_device_numbers WHERE platform='tiktok'` (с инвертированной end_date-семантикой).
- Удалены **9 файлов**: `account_packages_sync.{py,js}`, `audit_sync_account_packages.py`, `migrations/batch_split_invariants.py`, `tests/test_account_packages_sync.{py,test.js}`, `tests/test_admin_packages_crud.test.js`, `tests/test_batch_split_invariants.py`, `tools/guard_snapshot_diff.py`.
- pm2 restart (171 restarts), `/api/devices` 200.

### S9. DROP TABLE
- Final backup: `pg_dump -t account_packages > /tmp/step3-backup/account_packages-final.sql` (51KB, 301 rows).
- `DROP TABLE account_packages;` executed.
- `SELECT to_regclass('public.account_packages')` → NULL (gone).
- pm2 restart (final), `/api/devices` 200, no errors in logs.

### S10. Commits

Prod main ветка:
```
5c6c432 chore(step3): deprecate account_packages — remove dual-write, DROP TABLE
17b8961 Merge branch 'testbench' into main
6e3f4c3 prod-local: TT-publishing-resolution + testbench=FALSE scheduler filter
```

Git-hook автоматически push'ит коммиты в `origin/main`.

## Post-conditions

- `account_packages` table **не существует**.
- Prod `publisher.py` читает `factory_pack_accounts ⨝ factory_inst_accounts ⨝ factory_device_numbers` + `publish_tasks.done` history.
- Prod `server.js` GET/POST/PUT/DELETE `/api/packages` работает через factory.
- `/api/devices`, `/api/farming/projects|packs`, `getSocialAccounts` — все читают factory + `validator_projects`.
- `_upsert_auto_mapping` удалён.
- Sync helpers удалены.
- 9 файлов удалены из репо, 2589 строк кода удалено.

## Backup artifacts

- `/tmp/step3-backup/db-data-only.sql` — pg_dump factory + ap (до DROP).
- `/tmp/step3-backup/account_packages-final.sql` — pg_dump account_packages (финальный, 301 строка).
- `/tmp/step3-backup/` — copy 5 modified prod files + public/, scripts/, tests/, .ai-factory/ tree.

Восстановление в случае проблем:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw < /tmp/step3-backup/account_packages-final.sql
cd /root/.openclaw/workspace-genri/autowarm && git reset --hard 6e3f4c3
sudo pm2 restart autowarm
```

## Known follow-ups

- **account_switcher.py:425 docstring** упоминает `account_packages` (комментарий, не runtime). Оставлен — исторический.
- **pack_name_resolver.py:4 docstring** упоминает `audit_sync_account_packages.py`. Оставлен.
- **tests/test_single_account_preflight.py** мокает psycopg2.connect; тесты возможно ломаются без сервиса (нужно проверить — не в scope Шага 3).
- **Live regression на prod-трафике** — первая prod-публикация в working hours покажет, работает ли guard на реальных задачах. Если нет — откат через /tmp/step3-backup.
