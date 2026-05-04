# Wildcard `top_activity` matcher — design brief

**Date:** 2026-05-01
**Branch:** `design/publisher-obstacle-kb-20260430` (this brief), implementation on `feature/obstacle-kb-w2`
**Author:** picked up during W2.C code review (Important #1 from `8a428cc`)
**Decision required before:** W2.D shadow-lookup instrumentation (Plan tasks 15-17)

---

## Problem

W2.C seed (`obstacle_seed.from_constants` → `publisher_obstacles`, commit `8a428cc`) inserts 8 patterns. Two of them use a wildcard literal in `top_activity`:

| # | Pattern | `top_activity` | Action |
|---|---|---|---|
| 1 | IG human-check escalation | `com.instagram.android/.*` | `escalate` (set_block + notify) |
| 5 | TT reauth escalation | `com.zhiliaoapp.musically/.*` | `escalate` (set_block + notify) |

The runtime obstacle_id (computed by `extract_signature` in `obstacle_signatures.py`) hashes the **literal** Activity name observed at the moment of failure — e.g. `com.instagram.android/.activity.MainTabActivity`, `com.instagram.android/.modal.ModalActivity`, `com.zhiliaoapp.musically/.MainActivity`. The literal `/.*` is never a real foreground Activity.

**Therefore:** `lookup_obstacle(obstacle_id)` keyed on `compute_obstacle_id(canonical)` will **never** match these two seed rows. They are dead seed data until matcher logic is augmented.

Empirically (memory `project_publish_followups`), IG human-check appears across at least 3 IG Activities (`MainTabActivity`, `MediaCaptureActivity`, profile-tab Activity), and TT reauth modal can appear on either `MainActivity` or session-recovery activities — so we cannot just hardcode one Activity per escalation pattern without losing recall.

## Why we hit it now

1. The plan (Tasks 14, lines 1461 / 1510) explicitly prescribed `/.*` as a "match any sub-Activity" sentinel — but the matcher was never designed to honor that semantics.
2. The current matcher path is exact obstacle_id equality (sha1[:16] over canonical dict), which has no concept of partial / wildcard fields.
3. Without a fix, W2.D shadow-lookup will report `0 matches` for every IG human-check and TT reauth event, masquerading as a false-negative signal until someone investigates the seed list.

## Options

### Option A — Wildcard-tolerant matcher tier (reviewer's preference)

Add a second lookup path beside `lookup_obstacle(obstacle_id)`:

```python
def lookup_obstacle_by_signature(sig: ObstacleSignature) -> Obstacle | None:
    # Tier 1: exact match on obstacle_id (current)
    obs = lookup_obstacle(sig.obstacle_id)
    if obs:
        return obs

    # Tier 2: wildcard-friendly match on partial signature
    return _lookup_wildcard(sig.platform, sig.top_activity, sig.key_texts, sig.dialog_indicator)
```

Storage: keep `obstacle_id` as PK (deterministic for non-wildcard rows). For rows whose `top_activity` ends in `/.*`, mark them with a flag column or rely on a `LIKE` query:

```sql
CREATE INDEX IF NOT EXISTS publisher_obstacles_wildcard_idx
  ON publisher_obstacles (platform)
  WHERE top_activity LIKE '%/.\*';

-- Tier 2 query (read-time)
SELECT * FROM publisher_obstacles
WHERE status IN ('stable','candidate','experimental')
  AND platform = $1
  AND top_activity LIKE 'com.instagram.android/.%' ESCAPE '\'  -- replace tail with %
  AND key_texts && $2::text[]                                  -- array overlap on normalized texts
  AND dialog_indicator = $3
ORDER BY confidence_score DESC NULLS LAST, last_seen_at DESC
LIMIT 1;
```

The `key_texts && $2` array overlap is the discriminator — if any of the seed's `key_texts` appears among the runtime sig's normalized texts, it's a hit.

**Pros:**
- Preserves the curator's intent: "match any IG Activity where the dialog says X".
- Single seed row per logical obstacle (no row explosion).
- Migration-free: works against existing `publisher_obstacles` schema (only adds an index).

**Cons:**
- Two query paths to maintain; reviewer must read both to understand recall.
- Wildcard rows have an `obstacle_id` that is forever unreachable via Tier 1 — confusing dead PK.
- Tier-2 cost is one extra query per ai_unstuck event when Tier 1 misses (≈70 events/week, negligible).

**LOC estimate:** ~50 in `obstacle_kb.py` + 1 migration for the index + 6-8 unit tests.

### Option B — Per-Activity concrete rows

Replace each wildcard pattern with N concrete rows, one per known Activity name.

```python
# Instead of one row with com.instagram.android/.*, seed three:
{"top_activity": "com.instagram.android/.activity.MainTabActivity", ...},
{"top_activity": "com.instagram.android/.activity.MediaCaptureActivity", ...},
{"top_activity": "com.instagram.android/.modal.ModalActivity", ...},
```

**Pros:**
- Zero matcher complexity; existing exact-id lookup works untouched.
- Each row is independently observable in `publisher_obstacles` admin UI (W6).
- Aligns with KB philosophy: each `obstacle_id` is one observable scenario.

**Cons:**
- Row explosion: IG human-check across 3+ Activities × 4 normalized text variants = 3 rows; TT reauth × 2 Activities = 2 rows. Total seed grows from 8 → ~13.
- Recall depends on us enumerating Activities correctly — first time IG ships a new "human check on Settings activity", we get a false negative.
- Curator (W5) and admin UI (W6) get cluttered with near-duplicate rows.
- Doesn't actually solve the problem long-term — every Activity rename or new path needs a manual seed.

**LOC estimate:** ~30 LOC in `obstacle_seed.py`; no matcher work; **but** 5 new seed rows means ~5 future maintenance touchpoints.

### Option C — `top_activity=None` + key_texts-only matching for escalation patterns

For escalation patterns specifically (IG human-check, TT reauth), set `top_activity` to a sentinel (`None` or `"*"`) and rely entirely on `key_texts` overlap.

**Pros:**
- Simple seed shape: one row per logical pattern.
- Works for any future Activity without touching seed.

**Cons:**
- Requires the same matcher refactor as Option A (a second query path) — so we don't avoid the work.
- Loses Activity-level safety: a popup with "log back in" appearing on a non-TT Activity (e.g. some YT WebView) would falsely match the TT reauth row. Activity is a useful prior we shouldn't throw away.
- Schema/CHECK constraint: current `top_activity TEXT NOT NULL` would need to allow sentinel; either widen the column to nullable or treat empty-string as wildcard.

**LOC estimate:** comparable to Option A (~50 LOC) but with fuzzier semantics.

## Recommendation: Option A

Reasoning:
1. **Preserves recall:** The curator's mental model ("any IG Activity where the dialog says human-check phrases") survives, including future Activity additions.
2. **Single seed row per obstacle:** The KB stays diagnostically interpretable in admin UI (W6) — one row = one logical obstacle.
3. **Existing `obstacle_id` semantics unchanged for the other 6 (and all future non-wildcard) patterns.** Tier 1 stays the hot path; Tier 2 fires only when Tier 1 misses on platforms that have wildcard rows.
4. **Activity prior preserved:** Wildcard match still requires `platform` + Activity-prefix + `key_texts` overlap, so cross-platform false positives (Option C's risk) are avoided.

Tradeoff accepted: two query paths in `obstacle_kb.py`. We document this in the module docstring with a one-paragraph "matcher tiers" explanation.

## Implementation impact on W2.D

The original Plan tasks 15-17 (instrument refactors in `publisher_instagram.py`, `account_switcher.py`, `publisher_tiktok.py`, `publisher_youtube.py`) need a small upstream change before we wire them:

1. **New module:** `obstacle_kb.lookup_obstacle_by_signature(sig: ObstacleSignature) -> Obstacle | None` — calls Tier 1 then Tier 2.
2. **New helper:** `_lookup_wildcard` (private) — runs the SQL above with parameter-bound `top_activity LIKE pattern_prefix || '%'`.
3. **One additive migration:** `migrations/20260501_publisher_obstacles_wildcard_idx.sql` adding the partial index. Rollback companion stays the convention.
4. **Test additions:**
   - `test_lookup_wildcard_matches_ig_human_check_across_activities` (3 cases: MainTab / Modal / MediaCapture)
   - `test_lookup_wildcard_no_match_when_key_texts_disjoint`
   - `test_lookup_wildcard_respects_platform` (TT reauth doesn't match IG signature even with shared key_texts)
   - `test_lookup_wildcard_skips_non_wildcard_rows` (concrete-Activity rows are not double-served)
   - `test_lookup_wildcard_status_filter` (blacklisted not returned)
   - `test_lookup_obstacle_by_signature_tier1_wins` (exact id match preferred over wildcard)
5. **Tasks 15-17 wiring:** call `lookup_obstacle_by_signature` instead of `lookup_obstacle`. No other change.

Estimate: ~1 day to implement (migration + helper + 6 tests + 1 test for tier-fallthrough). Then proceed to Plan tasks 15-17 unchanged.

## Why not just delete the two wildcard seed rows?

Then we lose two of the strongest curator-known patterns from the seed. IG human-check accounts for the bulk of `escalate`-class events on the platform — silently dropping it from the KB during W2.D shadow-soak would distort the hit-rate metric and may delay W4 kill-switch flip.

## Decision

User chooses A / B / C / "delete those two rows for now" / something else.

If A: I propose to land it as a separate small PR before W2.D begins, so W2.D plan (tasks 15-17) remains unchanged. Estimate: 1 day implementation + review.
