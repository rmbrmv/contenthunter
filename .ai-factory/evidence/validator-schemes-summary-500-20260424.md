# Evidence — baseline: `/api/schemes/summary` 500 (pre-fix)

**Captured:** 2026-04-24
**Reporter:** ClickPay client complaint — "не генерятся схемы уникализации для тиндера" at `https://client.contenthunter.ru/client/schemes`
**Actual fault:** `/api/schemes/summary` returns 500 on every authenticated call; client UI wizard can never advance past the `upload` step, so the `tinder` swipe-approval step never shows.

## Repro

### Unauthenticated curl from localhost (sanity)

```
$ curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8000/api/schemes/summary/85
HTTP 403
body: {"detail":"Not authenticated"}
```

Endpoint requires auth — 403 is expected. The 500 only surfaces for authenticated client sessions, which is how it was observed in the PM2 err log.

### Traceback from authenticated client requests (pm2 err log)

Source: `sudo pm2 logs validator --err --nostream --lines 60 2>&1` — the log is 100% this traceback on repeat, once per client page load.

```
File "/root/.openclaw/workspace-genri/validator/backend/src/routers/schemes.py", line 69, in schemes_summary_by_project
    return await schemes_service.get_summary(project_id, db)
File "/root/.openclaw/workspace-genri/validator/backend/src/services/schemes_service.py", line 163, in get_summary
    min_required = await get_min_required_schemes(project_id, db)
File "/root/.openclaw/workspace-genri/validator/backend/src/services/schemes_service.py", line 23, in get_min_required_schemes
    result = await db.execute(
...
sqlalchemy.exc.ProgrammingError:
  (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError)
  <class 'asyncpg.exceptions.UndefinedTableError'>:
  relation "account_packages" does not exist
[SQL: SELECT COUNT(*) AS cnt FROM account_packages WHERE project = $1]
[parameters: ('ClickPay',)]
```

## Root cause

`account_packages` table was DROPPED 2026-04-22 (see memory `project_account_packages_deprecation.md`). `/accounts` was migrated to `factory_pack_accounts` at that time (validator commit `79ee472`), but `schemes_service.py`, `contract.py`, and `analytics.py` were missed during the cross-repo grep.

## DB state for project ClickPay (id=85)

- `validator_projects`: active, `api_name=click_pay`, `onboarding_stage=3`, created 2026-04-21
- `unic_schemes`: 30 rows (global catalog, not per-project)
- `validator_scheme_previews` for project 85: 31 rows, generated 2026-04-24 ~14:00Z (POST `/generate-previews/85` → 200 OK visible in out log)
- `validator_scheme_preferences` for project 85: 0 rows — UI never got past `/summary` to reach the approval step

The data is fine. The bug is the 500 on `/summary` that blocks the frontend wizard state machine.
