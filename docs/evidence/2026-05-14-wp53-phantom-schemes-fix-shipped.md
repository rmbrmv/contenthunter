# WP 53 — phantom "Схема -5..-1" in client /schemes — shipped 2026-05-14

**OpenProject:** WP 53 «убрать лишние схемы» → status `Тестирование` (awaiting visual confirmation by Анастасия)
**PR:** https://github.com/GenGo2/validator-contenthunter/pull/10
**Branch:** `fix/wp53-phantom-schemes-filter-20260514`
**Prod commit:** `070760c` (validator `main`, deployed to `/root/.openclaw/workspace-genri/validator`)
**Author:** Claude Opus 4.7 (1M context) + Danil Pavlov

## Backstory

Анастасия reported (WP 53, screenshot): the client «Схемы уникализации» screen shows 5 empty cards «Схема -5» … «Схема -1» at the **top** of the list — no preview, no params. Her question in the description: *"откуда схемы создаются? из админки? или это баг просто?"*

No spec/plan — direct bug research (`systematic-debugging` Phase 1+2) → 3-point fix approved by user → `TDD` implementation.

## Root cause

`backend/tests/test_schemes_deficits.py` seeds fixture rows with **negative ids** straight into the shared prod `unic_schemes` table (`_seed_project_with_packs_and_approved`: `scheme_id = -1 - i`, max `n_approved=5` → ids -5..-1). Validator tests run against the **live prod DB** by design (see memory `feedback-validator-test-engine-dispose`).

The bug: `_cleanup_project` deleted from `validator_scheme_preferences` + `factory_pack_accounts` but **never `unic_schemes`** — so the rows leaked permanently. Leak timestamp `2026-05-12 12:28:05` (identical `synced_at` on all 5 — that column has `DEFAULT now()`, the rest of the row is all-NULL).

Contrast: autowarm's `tests/test_unic_sweep_integration.test.js` cleans the same table (`DELETE FROM unic_schemes WHERE id <= -1`) — no leak there.

Three symptoms, all explained:
- **not generated** — the rows have every transform column NULL → preview worker has nothing to render; 0 rows in `validator_scheme_previews` for them.
- **at the front** — `get_schemes_with_preferences` does `ORDER BY us.id`; negative ids sort first.
- **exactly +5** — = the fixture count of the largest test (`n_approved=5`).

Extra damage: real projects 48/93/102/108 had `validator_scheme_preferences` rows pointing at these phantoms (all `rejected`) — clients had been swiping invalid cards.

## Fix (3 parts)

| Part | Change |
|---|---|
| **1 — data cleanup** | One tx on prod: `DELETE FROM unic_schemes WHERE id <= -1` (0 rows — already cleared as a side effect of running the fixed test suite) + `DELETE FROM validator_scheme_preferences WHERE scheme_id <= -1` (**17 rows**, projects 48/93/102/108). |
| **2 — leak source** | `test_schemes_deficits.py._cleanup_project` now also `DELETE FROM unic_schemes WHERE id <= -1`. New test `test_cleanup_project_removes_phantom_unic_schemes` asserts teardown is complete. |
| **3 — UI defense** | `schemes_service.get_schemes_with_preferences` (main + fallback) and `get_summary` filter `id > 0`. Both feed the same screen — the card list and the `total` counter must agree. New file `test_schemes_excludes_service_rows.py` covers both (self-seeded positive + negative fixtures). |

Files: `backend/src/services/schemes_service.py` (+15/-3), `backend/tests/test_schemes_deficits.py` (+26), `backend/tests/test_schemes_excludes_service_rows.py` (+88 new).

## TDD

RED → GREEN verified for all 3 new tests. After Codex feedback rewrote the two service-filter tests, re-verified RED by reverting the prod code (`git show HEAD:…schemes_service.py`) — both still failed for the right reason — then GREEN against the fixed code.

## Test results

- 3 new tests: PASS. All scheme tests (`test_schemes_*`, `test_scheme_preview_*`): **31 passed**.
- Full backend suite: **113 passed / 2 failed**. The 2 failures are `test_fixes_2026_04_20.py::test_generate_description_{auth_error,rate_limit}` — pre-existing stale Groq mocks (memory `project-validator-stale-generate-description-tests`), not a regression.

## Codex review

`git diff --cached | codex review -` (one round). 1× **P2**: the regression tests depended on live-DB having positive-id schemes (`assert ids` was a precondition, not the behavior under test). The premise of a "fresh/CI database" doesn't match this project — but the brittleness was real. Fixed: both tests now seed their own positive **and** negative fixture rows, proving the filter self-containedly. Re-review not needed (mechanical fix).

## Deploy

Validator backend runs under **pm2** (`validator`, id 24, root) — **not** systemd (`validator-backend.service` exists but is `inactive`). Deploy: `git pull` in prod checkout `/root/.openclaw/workspace-genri/validator` (auto-push hooks, no auto-pull) + `sudo pm2 restart validator`.

## Live verification

Against deployed code + cleaned DB: `get_schemes_with_preferences` / `get_summary` for projects 102 (was polluted) and 85 → 30 schemes, ids 1..30, no negatives, `list length == summary.total`.

## Follow-ups

See `docs/superpowers/plans/BACKLOG.md` → "2026-05-14 — WP 53 phantom schemes follow-up": router-level `unic_schemes` reads (`check_readiness`, `generate_previews`, `approved_scheme_ids`) are still unfiltered — low priority, the leak source is closed so phantoms won't recur.
