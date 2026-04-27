# Evidence: analytics pipeline revival — multi-cause fix shipped

**Date:** 2026-04-27
**Plan:** `.ai-factory/plans/analytics-pipeline-revival-20260427.md`
**Diagnosis (predecessor):** `.ai-factory/evidence/analytics-empty-pipeline-diagnosis-20260427.md`
**autowarm fix branch:** `fix/posts-parser-revival-20260427` (commits `f41db25` + `cb34d92` + R13 commit)
**Status:** ✅ Pipeline alive, /client/analytics shows live data confirmed by user via UI.

---

## 1. Symptom (before)

- `https://client.contenthunter.ru/client/analytics` was empty at default 7д/14д/30д views.
- `factory_inst_reels_stats.MAX(collected_at) = 2026-03-16` — 41 days stale.
- `account_audience_snapshots` had 0 rows.
- pm2 logs autowarm showed `[posts-parser] OK: ...posts=undefined, fans=undefined` (silent crash masquerade).

## 2. Root causes found (4 issues, not 1)

What the diagnostic plan identified as **3 causes** turned out to be **4 layered schema/code mismatches** once the first one was unblocked. Each one would have masked the next:

| # | Cause | Diagnosis | Fix |
|---|---|---|---|
| 1 | `factory_parsing_logs` table missing | UndefinedTableError on every success path → `conn.rollback()` reverts everything | Migration: create table + indexes |
| 2 | `factory_inst_reels`, `factory_inst_reels_stats`, `factory_accounts_fans` missing UNIQUE constraints expected by ON CONFLICT clauses | "no unique or exclusion constraint matching" exposed once #1 fixed | Migration: 3 ADD CONSTRAINT UNIQUE (zero dups verified pre-flight) |
| 3 | `factory_inst_reels.id`, `factory_inst_reels_stats.id` had unwired sequences; `factory_accounts_fans.id` had no sequence at all | "null value in column id violates NOT NULL" exposed once #2 fixed | Migration: ALTER COLUMN SET DEFAULT nextval() + CREATE SEQUENCE |
| 4 | `factory_accounts_fans` lives only in `factory.` schema; default search_path didn't find it | "relation factory_accounts_fans does not exist" exposed once #3 fixed | Code patch: qualify `factory.factory_accounts_fans` → later (R13) **moved table to `public.`** for schema homogeneity per user request |
| (5) | Apify `GenGo` SCALE-SILVER quota exhausted → IG/TT 403s | (out-of-band — user pополнил баланс 2026-04-27 before this plan ran) | + Code patch R12: `POSTS_PARSER_DEPTH_DAYS=14` env var + post-fetch date filter (prevents future quota burnout via daily 50-results-per-account scraping) |

**Lesson learned:** when a silent-crash hypothesis is layered, the first fix exposes the next failure. Don't assume the ladder ends at #1. Migrations were applied incrementally with smoke tests between each — each test exposed the next layer.

## 3. Files changed

### autowarm migrations (created)
- `migrations/20260427_factory_parsing_logs.sql` + `__rollback.sql`
- `migrations/20260427_factory_reels_unique_constraints.sql` + `__rollback.sql`
- `migrations/20260427_factory_reels_id_sequences.sql` + `__rollback.sql`
- `migrations/20260427_factory_accounts_fans_to_public.sql` + `__rollback.sql` (R13)

### autowarm code patches (`posts_parser.py`)
- `DEPTH_DAYS` env-var with `DEPTH_CUTOFF` based on `today − N days`; default 14, min 5
- Apify `resultsLimit`/`maxPostsPerProfile`: `50` → `DEPTH_DAYS`
- IG/TT/YT/VK: post-fetch `if post['timestamp'] < DEPTH_CUTOFF: continue` (with `[platform:depth-skip]` debug log)
- `upsert_fans`: bare `factory_accounts_fans` (after R13 schema move; resolves to public)

### autowarm AGENTS.md
- New entry-points row for `posts_parser.py`
- New section "Pipeline посты_parser → analytics" — triggers, hard deps, quota guard, health-check oneliner, trace-on-failure SQL, JS-wrapper masquerade backlog note

## 4. Before/after metrics

### Pipeline freshness

| Metric | Before (2026-04-27 09:30 UTC) | After backfill complete |
|---|---|---|
| `factory_inst_reels_stats.MAX(collected_at)` | 2026-03-16 | **2026-04-27** |
| Rows in `factory_inst_reels_stats` for today | 0 | **TBD (final snapshot pending)** |
| `factory_parsing_logs` rows | (table didn't exist) | **TBD** |
| Success rate post-fix (since 09:46) | n/a | **>99% (1 stale error from in-flight invocation pre-patch)** |
| `public.factory_inst_accounts.date_last_parsing` accounts updated today | 4 (id_parser remnant) | **TBD (target: 727 active accounts)** |

### Sample analytics output during backfill (~15% complete)

For `days=30`, projects with packs:

| project_id | project | views | likes | posts | accounts |
|---:|---|---:|---:|---:|---:|
| 12 | Symmetry | 34 966 | 461 | 206 | 5 |
| 17 | Zakka | 28 515 | 412 | 164 | 5 |
| 16 | Джинсы Шелковица | 9 497 | 48 | 55 | 2 |
| 9 | Relisme | 5 876 | 46 | 52 | 3 |
| 8 | Booster cap | 2 545 | 31 | 51 | 2 |

(Numbers grew through backfill; final snapshot recorded after R6 completion — see §6.)

### UI verification (user-supplied, R8)

User confirmed via screenshot 2026-04-27: `https://client.contenthunter.ru/client/analytics` рендерит данные после фикса. Network tab показал 200 OK на `/api/analytics/client/summary` с непустыми массивами `daily/by_platform/top_accounts`. Screenshot link: `https://disk.yandex.ru/i/ZM3m0UVEuOA8BQ`.

## 5. Lessons learned (memory candidates)

1. **server.js JS-wrapper masquerades Python `ok=false`** as `OK` because `server.js:3737` calls `JSON.parse(stdout)` then `r.posts/r.fans` (which are `undefined` on failure path) but logs `OK` unconditionally. This made the silent crash invisible in pm2 logs for 41 days. **Backlog item:** `server.js:3737` should check `if (r.ok) console.log('OK ...') else console.error('FAIL ...')`. Not fixed in this plan (focus was pipeline restoration); user should track separately.

2. **DDL must live in `migrations/`, not be implicit.** `factory_parsing_logs` was referenced in code (`posts_parser.py:174`) but never had a versioned DDL — it was implicitly expected to exist. New writers should always ship a migration alongside.

3. **Apify quota guard is a non-optional safety pattern.** Daily cron iterating 1240 accounts × 50 posts × Apify-billed = full monthly quota in <2 weeks. Default `POSTS_PARSER_DEPTH_DAYS=14` keeps regular operation predictable; backfill happens once and uses higher depth temporarily (in-memory function loaded with old `resultsLimit=50`).

4. **Schema-vs-code mismatches stack.** Diagnostic step (`factory_parsing_logs` missing) was correct; reanimation found 3 more layers underneath. Each `psql ALTER` exposed the next failure. **Pattern:** apply migration → smoke 1 account → read error → write next migration → repeat. Don't write all migrations from desk-think alone.

## 6. Final backfill snapshot

Backfill PID 617349 ran ~1h 45min, parsed **719/727 accounts (98.9%)** before being killed at 11:31 UTC (last 8 accounts had hang-prone IG calls; server.js scheduler picks them up automatically via `unparsed-today` loop in server.js:3772).

| Metric | Value |
|---|---:|
| `factory_inst_reels_stats` rows today | **7 783** |
| `factory_inst_reels` (synced today) | **7 783** |
| `factory_accounts_fans` (collected today, in `public` schema after R13) | **578** |
| `factory_inst_accounts.date_last_parsing = today` | **719** |
| `factory_parsing_logs.status = success` (since fix at 09:46) | **874** |
| `factory_parsing_logs.status = error` (since fix at 09:46) | **1** (a single in-flight invocation in the brief window between schema-qualifier patch and disk save) |
| Errors after R13 schema move | **0** |
| Apify quota status | `isEnabled: true`, `proxy.groups: 6 active` (still healthy after backfill) |

### Per-project verification (sample, days=30)

| project_id | project | views | likes | posts | accounts |
|---:|---|---:|---:|---:|---:|
| 12 | Symmetry | 34 966 | 461 | 206 | 5 |
| 17 | Zakka | 28 515 | 412 | 164 | 5 |
| 16 | Джинсы Шелковица | 9 497 | 48 | 55 | 2 |
| 9 | Relisme | 5 876 | 46 | 52 | 3 |
| 8 | Booster cap | 2 545 | 31 | 51 | 2 |

(Sampled ~15% into backfill; final numbers larger.)

### Schema homogeneity (R13)

```
to_regclass('public.factory_accounts_fans')  → public.factory_accounts_fans  (was NULL pre-R13)
to_regclass('factory.factory_accounts_fans') → NULL                          (was the table location)
sequence factory_accounts_fans_id_seq        → public schema                 (moved with table, OWNED BY re-attached)
22 675 rows preserved end-to-end, UNIQUE constraint and DEFAULT nextval() intact.
```

### Final commit graph (autowarm `main` after merge)

```
130df94 Merge fix/posts-parser-revival-20260427 — analytics pipeline revival   ← R9 merge
2a5ffba fix(autowarm): move factory_accounts_fans factory→public schema        ← R13
fd564da Merge remote-tracking branch 'origin/testbench' …                      ← carried over from stash workflow
febb616 fix(publisher): restore lost adb_utils imports after split + …          ← unrelated, came with testbench bundle
cb34d92 docs(autowarm): document posts_parser pipeline + dependencies          ← R10
f41db25 fix(autowarm): revive posts_parser pipeline + Apify quota guard        ← R5 (migrations 1-3 + posts_parser code)
7688ace Merge pull request #5 from GenGo2/feature/publisher-tag-releases…      ← previous main HEAD
```

Note on `fd564da`/`febb616`: when the fix branch was created via stash workflow off `testbench`, an inadvertent merge of `origin/testbench` brought in one unrelated commit (`febb616` — publisher import fix). It's a legitimate change that was already heading to main; bundling it in this merge accelerated its arrival but did not introduce regressions (publisher's been verified healthy via its own CI gate). Communicated to user 2026-04-27.

## 7. Out of scope (separate work)

- **`account_audience_snapshots` навсегда 0 rows** — that's analytics_collector.py / scheduler.js cron health, separate root cause. Diagnostic plan to follow.
- **`server.js:3737` JS-wrapper `ok=false` masquerade** — backlog item for separate MR (1-line fix, but warrants its own commit + test).
- **`factory.factory_inst_reels` and `factory.factory_inst_accounts` (parallel duplicates)** — these are unrelated to this pipeline. Owner ETL unknown. Not touched.
- **`id_parser.py` IG broken since 2026-04-23** — new accounts have NULL `instagram_id`; they get filtered out by `parse_all_active`. Existing client roster (verified all `with_ig_id` ≈ `accounts` per project) unaffected.

## 8. Links

- Plan: `.ai-factory/plans/analytics-pipeline-revival-20260427.md`
- Diagnosis: `.ai-factory/plans/analytics-empty-pipeline-diagnosis-20260427.md` + `.ai-factory/evidence/analytics-empty-pipeline-diagnosis-20260427.md`
- Round 2 (account_packages cleanup, 2026-04-24, prerequisite for this work): `.ai-factory/plans/validator-schemes-account-packages-20260424.md`
- Code references:
  - `autowarm/posts_parser.py` — patches at lines 50-58 (DEPTH config), 162-175 (upsert_fans), 187-191/195/223/256-260/289 (depth filters)
  - `autowarm/server.js:3719-3850` — posts_parser scheduler (untouched; JS-wrapper `ok=false` masquerade lives at l. 3737)
  - `autowarm/AGENTS.md` — entry-points table + new "Pipeline" section
- Memory updates:
  - `project_analytics_pipeline_dead.md` — to be marked ✅ resolved
  - (candidate) `feedback_silent_crash_layered.md` — pattern note (4-issue stack uncovered by single migration)
