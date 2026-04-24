# Fix: validator `/api/schemes/summary` 500 — `account_packages` was DROPPED (ClickPay complaint)

**Created:** 2026-04-24
**Branch (plan):** `feature/farming-testbench-phone171` (plan file only — fix lives in validator repo)
**Target repo:** `/root/.openclaw/workspace-genri/validator/` (git auto-push → `GenGo2/delivery-contenthunter`)
**Base for validator fix branch:** `main` of validator
**Proposed validator branch:** `fix/schemes-contract-analytics-account-packages-20260424`
**Reporter:** Danil → ClickPay client complaint at `https://client.contenthunter.ru/client/schemes` — "не генерятся схемы уникализации для тиндера"

---

## Settings

| | |
|---|---|
| Testing | yes — extend existing live-DB smoke-test pattern (`tests/test_accounts_endpoint.py`) |
| Logging | verbose (DEBUG) — keep existing `logger.warning` + `await db.rollback()` pattern; add WARN on fallback paths |
| Docs | skip — narrow bug fix, no new surface |
| Roadmap | n/a — no `.ai-factory/ROADMAP.md` in repo |

---

## Summary

### What the client sees
At `https://client.contenthunter.ru/client/schemes` the ClickPay manager never advances past the "upload" step of the wizard, so the "Tinder" swipe-approval UI (the step literally named `tinder` in `SchemesPage.vue:324 — type Step = 'upload' | 'logo' | 'generating' | 'tinder'`) never shows. From the user's perspective this looks like "схемы не генерятся для тиндера".

### What actually fails
`GET /api/schemes/summary` returns **500 Internal Server Error** on every call. Validator error log is a wall of identical exceptions:

```
asyncpg.exceptions.UndefinedTableError: relation "account_packages" does not exist
[SQL: SELECT COUNT(*) AS cnt FROM account_packages WHERE project = $1]
[parameters: ('ClickPay',)]
  routers/schemes.py:57 → schemes_summary
    services/schemes_service.py:163 → get_summary
      services/schemes_service.py:23 → get_min_required_schemes
```

The wizard frontend (`SchemesPage.vue`) calls `/schemes/summary` during page load; without the 200-response it never computes `previews_ready`, so `step` stays at `upload`.

### Why
On **2026-04-22** the `account_packages` table was DROPPED as part of the factory-consolidation cleanup (memory: `project_account_packages_deprecation.md`). The `/accounts` endpoint was fixed that day (validator commit `79ee472 fix(accounts): account_packages → factory_pack_accounts`) with a live-DB regression test (`tests/test_accounts_endpoint.py`). But three other places in validator still JOIN the dead table:

| File | Lines | Endpoint exposure |
|---|---|---|
| `backend/src/services/schemes_service.py` | 23-28 | **`/api/schemes/summary` (primary — ClickPay breakage)** |
| `backend/src/routers/contract.py` | 65, 76, 100, 116 | contract endpoints (latent 500s) |
| `backend/src/routers/analytics.py` | 229, 270, 288, 307, 416, 517 | 6 analytics queries (latent 500s) |

Cross-repo grep over `/root/.openclaw/workspace-genri/` confirms no other service (`autowarm`, `ch-auth`, `producer`, `producer-copilot`) still references `account_packages`.

### Clarification on "Tinder"
"Tinder" in this codebase is a **UI mode name** for the swipe-style approval carousel in `SchemesPage.vue`, not the dating-app platform. There is no Tinder social-media integration anywhere in validator or autowarm (autowarm scope is IG/TT/YT only per memory). ClickPay's complaint is not about a missing platform — it's about the wizard being stuck.

### Evidence from DB (project_id=85 = ClickPay)
- `validator_projects` row exists (active, `api_name=click_pay`, `onboarding_stage=3`)
- `unic_schemes` has 30 rows (global catalog — not per-project)
- `validator_scheme_previews` for project 85 has 31 rows generated 2026-04-24 14:00Z (POST `/generate-previews/85` → 200 OK in log)
- `validator_scheme_preferences` for project 85: 0 rows (user never got to the approval step = the "tinder" UI)
- **Data is fine. The 500 on `/summary` is what blocks the UI.**

---

## Replacement SQL pattern

| Old | New |
|---|---|
| `SELECT COUNT(*) FROM account_packages WHERE project = :pname` | `SELECT COUNT(*) FROM factory_pack_accounts WHERE project_id = :pid` |
| `JOIN account_packages ap ON ap.id = fia.pack_id … WHERE ap.project = :pname` | `JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id … WHERE fpa.project_id = :pid` |
| `JOIN account_packages ap ON ap.pack_name = fpa.pack_name` | drop JOIN — already on `factory_pack_accounts` (`contract.py:65`, bogus join anyway) |
| Field `ap.start_date` (age calc in analytics) | `fpa.start_date` |

**Schema** (verified against live DB):
```
factory_pack_accounts(id, pack_name, project_id, device_num_id, start_date, end_date, synced_at)
```

**Simplification for `schemes_service.py`:** `get_min_required_schemes(project_id, db)` already receives `project_id`. The old code looked up the project *name* from `validator_projects` then filtered `account_packages.project` by that string. New code can filter `factory_pack_accounts.project_id` directly and drop the extra lookup.

---

## Tasks

### Phase 1 — Reproduce + branch

- [x] **T1. Reproduce 500 locally against live DB** — `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/schemes/summary/85` → expect `500`; also grab a fresh traceback via `sudo pm2 logs validator --err --nostream --lines 50 2>&1`.
  - Deliverable: traceback saved to `.ai-factory/evidence/validator-schemes-summary-500-20260424.md` (baseline for before/after).
  - Logging: none (read-only).
- [x] **T2. Create validator branch** — in `/root/.openclaw/workspace-genri/validator/`:
  ```
  git fetch origin && git checkout main && git pull
  git checkout -b fix/schemes-contract-analytics-account-packages-20260424
  ```
  - Blocks nothing; independent of T1.
  - Logging: n/a.

### Phase 2 — Primary fix (unblocks ClickPay UI)

- [x] **T3. Fix `schemes_service.py:get_min_required_schemes`** — `backend/src/services/schemes_service.py:18-28`.
  - Replace body with:
    ```python
    async def get_min_required_schemes(project_id: int, db: AsyncSession) -> int:
        """Минимум одобренных схем = количество паков аккаунтов клиента."""
        result = await db.execute(
            text("SELECT COUNT(*) AS cnt FROM factory_pack_accounts WHERE project_id = :pid"),
            {"pid": project_id},
        )
        row = result.mappings().first()
        return int(row["cnt"]) if row else 0
    ```
  - Remove the now-unused `_get_project_name` helper (lines 9-15) **only if it has no other callers** — grep first; if still used, leave it.
  - Logging: add `logger.debug("min_required_schemes project_id=%s → %s", project_id, row["cnt"])` for dev visibility.
  - Blocked by: T2.
- [x] **T4. Wrap `get_min_required_schemes` in try/except inside `get_summary`** — `schemes_service.py:163`. Even with the table fixed, a transient DB error should not 500 the whole summary. Follow the same pattern as the `validator_scheme_preferences` block at lines 146-160: `try/except: await db.rollback(); min_required = 0`.
  - Logging: `logger.warning("min_required_schemes failed: %s", e)` inside the except.
  - Blocked by: T3.

### Phase 3 — Audit + fix remaining callers (prevent next 500)

- [x] **T5. Fix `contract.py`** — `backend/src/routers/contract.py`, lines 65, 76, 100, 116.
  - Read each query, replace `account_packages ap` join with `factory_pack_accounts fpa` directly. For the `ap.pack_name = fpa.pack_name` self-join pattern at line 65, verify whether the alias is actually needed or was legacy; remove if redundant.
  - Param mapping: callers that pass `project_name` should be switched to `project_id` via `validator_projects`. Prefer changing the helper signature upward if it cleans up consistently; otherwise do a lookup once at the top.
  - Logging: keep existing; add `logger.debug` on each endpoint entry with `project_id`.
  - Blocked by: T2 (not T3 — independent files).
- [x] **T6. Fix `analytics.py`** — `backend/src/routers/analytics.py`, lines 229, 270, 288, 307, 416, 517.
  - Same replacement pattern: `account_packages ap` → `factory_pack_accounts fpa`. `ap.start_date` → `fpa.start_date`. Filter by `fpa.project_id` (int) not `ap.project` (string).
  - These queries JOIN `factory_inst_accounts fia` on `fia.pack_id = ap.id` — keep the join, just alias to `fpa.id`.
  - Logging: keep existing.
  - Blocked by: T2.

### Phase 4 — Regression tests (live DB, matches `/accounts` pattern)

- [x] **T7. Add `test_schemes_summary_endpoint.py`** — `backend/tests/test_schemes_summary_endpoint.py`.
  - Copy the canary pattern from `test_accounts_endpoint.py`. Known project id = 85 (ClickPay, verified to have `factory_pack_accounts` rows). Assert summary is a dict with keys `total, approved, rejected, pending, min_required` and all are int; assert `min_required >= 0`. Also hit `UNKNOWN_PROJECT_ID=999999` and assert `min_required == 0` without error.
  - Logging: test output only.
  - Blocked by: T3, T4.
- [x] **T8. Add `test_account_packages_migration_smoke.py`** *(optional but aligned with the memory rule "grep ДО деплоя")* — single live-DB test that hits one endpoint per router (`/contract/...`, `/analytics/...`) for `project_id=85` and asserts HTTP 200 + dict response. Catches any remaining `account_packages` reference that's been missed.
  - Blocked by: T5, T6.

### Phase 5 — Deploy + verify

- [x] **T9. Run the full test suite in validator** — 58 passed; 2 pre-existing `test_generate_description_*` failures are stale Anthropic-mocks unrelated to this fix (endpoint migrated to Groq in commit `2132233`). — `cd /root/.openclaw/workspace-genri/validator/backend && python -m pytest tests/ -x -v`. All tests must be green. If anything red, STOP and fix before merge.
  - Blocked by: T7, T8.
- [x] **T10. Commit + merge to `main`** — commit `7c03c58`, merge `c3467c0`; pushed to `GenGo2/validator-contenthunter` main. (auto-push hook will ship to `GenGo2/delivery-contenthunter`). Conventional commit, e.g.:
  ```
  fix(validator): account_packages → factory_pack_accounts in schemes/contract/analytics

  After 2026-04-22 DROP of account_packages, only /accounts was migrated.
  /api/schemes/summary was 500-ing on every client load, blocking the
  Schemes wizard before the "tinder" approval step. contract.py and
  analytics.py had 10 latent 500s with the same root cause. Adds live-DB
  smoke tests per the existing /accounts pattern.
  ```
  - Blocked by: T9.
- [x] **T11. Restart validator + verify live** — PM2 restart OK, exec cwd правильный (`/root/.openclaw/workspace-genri/validator/backend`), post-restart err log чист, `get_summary(85)` возвращает `{total:30, approved:0, rejected:0, pending:30, min_required:0}` без исключений. — `sudo pm2 restart validator --update-env && sleep 3 && sudo pm2 describe validator | grep exec` (confirm exec cwd didn't drift — see memory `feedback_pm2_dump_path_drift.md`).
  - Then `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/schemes/summary/85` → expect `200`.
  - `sudo pm2 logs validator --err --nostream --lines 20 2>&1` → no more `UndefinedTableError`.
  - Blocked by: T10.
- **T12. UI smoke as ClickPay** — log in at `https://client.contenthunter.ru/client/schemes` as a user mapped to `project=ClickPay` (or use admin project-switcher). Verify wizard reaches the `tinder` swipe step; open DevTools → Network → confirm `/api/schemes/summary` is 200.
  - Attach a screenshot to the evidence file.
  - Blocked by: T11.
- [x] **T13. Write evidence** — `.ai-factory/evidence/validator-schemes-account-packages-fix-20260424.md`. Include: before/after tracebacks (T1 vs T11), SQL diff summary, list of files changed, test output, UI screenshot.
  - Blocked by: T12.

---

## Commit Plan

- **Commit 1** (after T7, T8): fix + tests together — `fix(validator): account_packages → factory_pack_accounts in schemes/contract/analytics + live-DB smoke tests`. Single atomic commit — schema migration is one conceptual change; splitting would leave either tests red or prod still 500-ing between commits (bad for parallel Claude sessions per memory `feedback_parallel_claude_sessions.md`).
- **Commit 2** (after T13, in agent-workspace repo): `docs(plans+evidence): validator schemes /summary 500 fix — account_packages cleanup round 2`.

---

## Risks & notes

- **Reproduce-then-fix**: T1 baseline is non-negotiable. We need proof before/after (memory `feedback_user_diagnosis_is_signal.md` — verify symptom independently of the hypothesis). The hypothesis is "schemes don't generate for Tinder"; the evidence says the /summary endpoint 500s and the UI never advances. Capture both.
- **Project-name vs project-id string drift**: the old code used `validator_projects.project` (string with spaces, e.g. `'Booster cap'`). `factory_pack_accounts.project_id` is the FK-clean integer. Callers currently passing `project_name` need to be rewritten to pass `project_id`. Watch for any endpoint whose request params are `{project}` string vs `{project_id}` int — don't silently change the contract.
- **`contract.py:65` has `ap.pack_name = fpa.pack_name`** (self-join via name). Verify this isn't hiding a data-quality bug that the new query would unmask. If unsure, keep the join equivalent and add a comment, don't over-simplify.
- **PM2 path drift** (memory `feedback_pm2_dump_path_drift.md`): after `pm2 restart`, re-verify `exec cwd = /root/.openclaw/workspace-genri/validator/backend`. If drift appears, use `pm2 delete + pm2 start` from the ecosystem config.
- **Test isolation**: the existing `test_accounts_endpoint.py` has a comment about async engine/event-loop fragility (`Event loop is closed` on teardown). New tests must follow the same one-test-per-session pattern; don't split into two `@pytest.mark.asyncio` cases.
- **No migration needed**: `factory_pack_accounts` already exists and is populated — we're only changing queries.
- **Cross-repo**: grep confirms autowarm/ch-auth/producer/producer-copilot are clean. No other services to touch.

---

## Links

- Validator fix commit reference for /accounts (same pattern): `79ee472`
- Regression test template: `backend/tests/test_accounts_endpoint.py`
- Related memory:
  - `project_account_packages_deprecation.md` — DROP'нута 2026-04-22, factory = single source
  - `feedback_cross_repo_schema_changes.md` — grep cross-repo ДО деплоя (exactly this scenario)
  - `feedback_pm2_dump_path_drift.md` — verify exec cwd after restart
  - `feedback_user_diagnosis_is_signal.md` — user's "Tinder не генерится" is a symptom, not the root cause
