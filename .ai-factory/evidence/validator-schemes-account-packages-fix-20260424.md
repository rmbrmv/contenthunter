# Evidence — validator `/api/schemes/summary` 500 fix (ClickPay)

**Date:** 2026-04-24
**Reporter:** Danil → ClickPay client complaint at `https://client.contenthunter.ru/client/schemes`
**Symptom observed by user:** "не генерятся схемы уникализации для тиндера"
**Actual symptom:** `GET /api/schemes/summary` → 500 on every auth'd call → client wizard stalls on `upload` step, never reaches the `tinder` swipe-approval step
**Root cause:** `account_packages` table was DROPPED 2026-04-22; `/accounts` was migrated at the time, but `schemes_service.py`, `contract.py`, and `analytics.py` were missed in the cross-repo grep
**Branch:** `fix/schemes-contract-analytics-account-packages-20260424` → merged to `main` as `c3467c0` (merge) over `7c03c58` (fix)
**Repo:** `GenGo2/validator-contenthunter`

---

## Before (baseline, from pm2 err log)

```
File "/root/.openclaw/workspace-genri/validator/backend/src/routers/schemes.py", line 69, in schemes_summary_by_project
    return await schemes_service.get_summary(project_id, db)
File "/root/.openclaw/workspace-genri/validator/backend/src/services/schemes_service.py", line 163, in get_summary
    min_required = await get_min_required_schemes(project_id, db)
File ".../services/schemes_service.py", line 23, in get_min_required_schemes
    result = await db.execute(
...
sqlalchemy.exc.ProgrammingError:
  <class 'asyncpg.exceptions.UndefinedTableError'>:
  relation "account_packages" does not exist
[SQL: SELECT COUNT(*) AS cnt FROM account_packages WHERE project = $1]
[parameters: ('ClickPay',)]
```

Full err log was 100% this traceback on repeat, once per client page load. Also observed: 10 latent 500s in `contract.py` and `analytics.py` with identical root cause.

## After (post-deploy, same DB, live validator service)

```
$ python -c "from src.database import AsyncSessionLocal; from src.services import schemes_service; ..."
project_id=85 (ClickPay) /summary: {
  'total': 30,
  'approved': 0,
  'rejected': 0,
  'pending': 30,
  'min_required': 0
}
```

- No exception
- `/summary` returns the expected shape
- `validator-error.log` post-restart is clean — only `INFO: Uvicorn running on ...` lines

Wizard readiness inputs for ClickPay (project_id=85):
- `unic_schemes` total = **30**
- `validator_scheme_previews` for project 85 = **31**
- `previews_ready = (31 >= 30 AND 30 > 0) = True`

So the `/client/schemes` wizard should now advance past `upload → logo → generating → tinder` and display the swipe-approval UI.

`min_required=0` is not a bug — ClickPay has 0 rows in `factory_pack_accounts` (onboarding_stage=3, created 2026-04-21; device packs apparently not assigned yet). Separate data/ops question, not a code issue.

---

## SQL diff summary

| File | Lines changed | Pattern |
|---|---|---|
| `backend/src/services/schemes_service.py` | -20 / +13 | drop `_get_project_name` helper; query `factory_pack_accounts WHERE project_id = :pid` directly; wrap min_required call in try/except inside `get_summary` |
| `backend/src/routers/contract.py` | -4 joins, -1 param rename | `JOIN account_packages ap ON … WHERE ap.project = :project` → `JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id WHERE fpa.project_id = :pid` ×4; params dict uses `pid`, drops `project` name |
| `backend/src/routers/analytics.py` | -6 joins, -2 param renames | same pattern ×6 across `/client/summary` (base_join + bp_rows + top_rows + g_row), `/client/top-posts`, `/client/publications` CTE |

## Files changed

```
 backend/src/routers/analytics.py                     | 33 +++++------
 backend/src/routers/contract.py                      | 22 ++++----
 backend/src/services/schemes_service.py              | 33 ++++++-----
 backend/tests/conftest.py                            | 22 ++++++++
 backend/tests/test_account_packages_migration_smoke.py | 66 ++++++++++++++++++++++
 backend/tests/test_schemes_summary_endpoint.py       | 48 ++++++++++++++++
 6 files changed, 180 insertions(+), 44 deletions(-)
```

## Tests

New tests (live-DB smoke, same pattern as existing `test_accounts_endpoint.py`):

- `test_schemes_summary_endpoint.py::test_schemes_summary_live_db_does_not_500` — primary canary. `get_summary(85)` must not raise, must return dict with int keys total/approved/rejected/pending/min_required. Unknown project_id → min_required=0.
- `test_account_packages_migration_smoke.py::test_factory_pack_accounts_replaces_account_packages_across_routers` — executes one representative SQL pattern per router (contract phones, contract accounts, analytics base_join, schemes min_required) to catch any future `account_packages` regression.
- `conftest.py` — autouse fixture `await engine.dispose()` after each test. Fixes `RuntimeError: Event loop is closed` that surfaced when running ≥2 live-DB tests in one pytest invocation (asyncpg pool got bound to test-1's loop).

## Suite result

```
$ python -m pytest tests/
======== 58 passed, 2 failed, 16 warnings in 5.40s ========
```

**Unrelated to this fix (pre-existing, also fail on main without my changes):**
- `test_fixes_2026_04_20.py::test_generate_description_auth_error_returns_503`
- `test_fixes_2026_04_20.py::test_generate_description_rate_limit_returns_503`

Both mock `anthropic.AsyncAnthropic`, but `/generate-description` was migrated to Groq in commit `2132233` — the mocks no longer intercept the actual code path, so the expected `HTTPException` is never raised. Stale tests, should be deleted or rewritten against Groq. Out of scope for this fix.

## PM2 restart

```
$ sudo pm2 restart validator --update-env
$ sudo pm2 describe validator | grep -E "status|exec cwd|restarts|uptime"
status            online
restarts          13
uptime            3s
exec cwd          /root/.openclaw/workspace-genri/validator/backend
unstable restarts 0
```

No PM2 path drift (memory `feedback_pm2_dump_path_drift.md`).

## Cross-repo audit

```
$ grep -rln account_packages /root/.openclaw/workspace-genri/ | grep -v node_modules | grep -v __pycache__ | grep -v validator/docs
(only validator/ has refs; autowarm, ch-auth, producer, producer-copilot all clean)
```

After this fix, remaining `account_packages` occurrences in validator are all in comments, docs/, or NOTES.md — no executable code references.

## Open item (user-verifiable)

**T12 — UI smoke as ClickPay client:** log in at `https://client.contenthunter.ru/client/schemes` with a user mapped to project ClickPay; confirm wizard reaches `tinder` swipe step and DevTools Network shows `/api/schemes/summary` = 200. Backend-level verification above is strong, but live UI confirmation seals it.

## Lessons / memory updates to consider

- The cross-repo-grep rule (memory `feedback_cross_repo_schema_changes.md`) already exists and was authored after the 2026-04-22 `account_packages` drop. This incident shows the rule was only partially applied — only `/accounts` was grepped/migrated at the time. Future schema DROPs should run `grep -rn <table> /root/.openclaw/workspace-genri/` **without** additional filters (no `| head`) and audit every hit before deploy.
- Live-DB smoke tests in validator need a shared-engine-dispose pattern. The new `tests/conftest.py` documents it; future live-DB tests inherit the fixture automatically.
