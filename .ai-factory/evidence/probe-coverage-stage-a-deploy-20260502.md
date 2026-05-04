# Stage A Deploy Evidence — Probe Coverage Expansion

**PR:** [#7](https://github.com/GenGo2/delivery-contenthunter/pull/7) merged 2026-05-02 09:53 UTC
**Main HEAD:** `77a0d36` (merge commit) — fast-forward target `29769d1`
**Base before merge:** `8cd58de`
**Branch:** `feature/obstacle-kb-probe-coverage-20260502` (deleted after merge)

## Commits in PR

| SHA | Title |
|---|---|
| `8d5ca04` | refactor(obstacle-kb): extract `_safe_kb_probe` helper, dedup 5 call-sites |
| `3252137` | feat(obstacle-kb): tier-final shadow probe inside `_fail_task` |
| `e7320de` | feat(obstacle-kb): probe IG caption-fill obstacle states (4 sites) |
| `9e2b9dc` | test(obstacle-kb): pin step↔category bidirectional contract |
| `f88188f` | feat(obstacle-kb): probe IG camera+editor (16 sites) |
| `9840d28` | refactor(obstacle-kb): drop locals().get + switch tests to fixture injection |
| `ba9b122` | feat(obstacle-kb): probe TT publish (4 sites) |
| `29769d1` | feat(obstacle-kb): probe YT publish (4 sites) + factory mixin stub |

## Coverage delta

| Tier | Before | After | Δ |
|---|---|---|---|
| Tier-final (`_fail_task`) | 0 | 1 | +1 |
| Tier-intermediate IG | 1 (open_camera) | 21 | +20 |
| Tier-intermediate TT | 0 | 4 | +4 |
| Tier-intermediate YT | 0 | 4 | +4 |
| Switcher (pre-existing) | 4 | 4 | 0 |
| **Total active probes** | **5** | **34** | **+29** |

## Deploy state

**PM2 restart:** 2026-05-02 09:53:31 UTC
- `autowarm` (id 1) — online, 0 unstable restarts post-deploy
- `autowarm-testbench` (id 32) — online, 0 unstable restarts post-deploy

**Worktrees synced:**
- `/root/.openclaw/workspace-genri/autowarm/` — `77a0d36`
- `/home/claude-user/autowarm-testbench` — `77a0d36`

**Startup logs:** clean. No Python import errors / NameError / AttributeError. Pre-existing ADB network errors on Pi #4 (15038) and Pi #6 (15058) unchanged — known infra issue per `project_adb_push_network_issue` memory, not from this deploy.

## Baseline KB state (at deploy moment)

| Metric | Value |
|---|---|
| `publisher_obstacles` (B1 seed, `source='manual_seed:hardcoded'`) | 8 |
| `publisher_obstacle_outcomes` total | 0 |
| `publisher_obstacle_outcomes WHERE outcome='shadow_match'` | 0 |
| Kill switches | `obstacle_kb_disabled=false`, `obstacle_kb_lookup_only=true` |

KB is in shadow mode; probes record outcomes but do NOT influence publisher behavior.

## Soak window — observed

- **Deploy:** 2026-05-02 09:53:31 UTC
- **Final check:** 2026-05-02 10:54:47 UTC (+61 min)
- **Schema correction:** column name is `matched_at` not `created_at` (fixed in queries; baseline doc-level reference pre-existed)

### Observed traffic in soak window

| Metric | Count |
|---|---|
| `publish_tasks` post-deploy | 2 |
| `publish_tasks WHERE status='failed'` | 0 |
| `publish_tasks WHERE status='awaiting_url'` (success) | 2 |
| `publisher_obstacle_outcomes` post-deploy | 0 |
| `publisher_obstacle_outcomes WHERE outcome='shadow_match'` | 0 |

### Interpretation

**Soak result: deploy clean, KB validation pending natural fail traffic.**

Why 0 outcomes: zero fails in the 61-min window. Both probes-tiers depend on actual obstacle states or fail-paths to fire:
- Tier-final fires only on `_fail_task` invocation — no fails ⇒ no fires
- Tier-intermediate fires only when publisher hits a `meta.category` site — both publish_tasks went through happy-path

**What's confirmed:**
- ✅ PM2 services stable on new code (no Python import/AttributeError after restart)
- ✅ Probes do NOT break success-path (2/2 success in soak window — no false-positive blocking)
- ✅ Wiring verified: 15 new probe-coverage tests passed in pre-merge full pytest

**What's pending validation:**
- Real `shadow_match` row when production hits a B1-seeded obstacle state. Per 24h history (44 fails total — 14 `ig_caption_fill_failed`, 21 `adb_devices_unreachable`, 4 `switch_failed_unspecified`, etc.), fails cluster in 15:00–19:00 UTC peak. Next natural validation window: 2026-05-02 ~15:00 UTC (~4h after deploy).

### Follow-up

- Schedule a background check at ~16:00 UTC 2026-05-02 to verify shadow_match rows appear after peak fail-traffic window.
- If `ig_caption_fill_failed` tasks land in the next window without producing shadow_match outcomes, dig into the probe call sites — may indicate the seeded obstacle signatures don't match the actual UI state at fail-time (signature-tuning required, not a wiring bug).

---

## Stage A.1 + Tier-2 wildcard fix — SHIPPED 2026-05-02 16:26 UTC ✅

After Stage A 60-min soak showed 0 outcomes (no fails in window), 29 failed tasks were re-queued for validation. Investigation surfaced two gaps fixed via Stage A.1 + a follow-up Tier-2 SQL fix:

### Gap 1: Tier-final probe lived only in `_fail_task` — caption fails bypass it

Caption-fill fails don't call `_fail_task` directly — they go through `update_status('failed')` → `_set_error_code_from_events`. Stage A's tier-final probe missed all caption-path failures.

**Fix (PR #8 merge `50c4cea`):** Relocated probe from `_fail_task` to `_set_error_code_from_events` — the common funnel called from BOTH `_fail_task` AND `update_status('failed')`. Step kwarg = canonical `error_code` (preserves step↔category alignment).

### Gap 2: B1 seed had no caption-screen pattern

Probe at `publisher_instagram.py:2089` fired correctly but `lookup_obstacle_by_signature` returned None — B1's 8 patterns covered camera/picker/draft/about-account/sbrowser/TT-reauth, none matched caption screen.

**Fix (PR #8):** Added B1.9 seed extracted from real UI dump of task 2331:
- `top_activity='com.instagram.android/.*'` (wildcard)
- `key_texts=['добавьте подпись и хэштеги...', 'поделиться']`
- `dialog_indicator=False`, `status='experimental'`
- `source='manual_seed:caption_fill_extension_20260502'`

### Gap 3: Tier-2 wildcard SQL trick broken for absolute-path activities

After Stage A.1 deployed, **still 0 outcomes** for 6+ caption fails. Diagnostic logging revealed real production `top_activity='com.instagram.android/com.instagram.modal.ModalActivity'` (absolute path), not `com.instagram.android/.modal.ModalActivity` (relative shorthand) that the SQL assumed.

The substring trick `substring(top_activity, 1, length-1)` stripped only `*` (1 char), leaving `'/.'` which forced runtime to start with literal `/.<name>` — impossible for absolute-path activities like `/com.instagram.modal.X`.

**Fix (PR #10 merge `e8cc7a0`):** Strip 2 chars (`.*`) instead of 1, so the LIKE prefix becomes the package + slash, matching anything past the slash regardless of whether Android dumpsys returned relative or absolute form.

### Validation — pipeline ALIVE end-to-end

Final validation (5 caption_fill_failed tasks 2511-2515 re-queued at 16:14 UTC):
- Probes fired correctly for both `caption_verify_failed` (mid-loop) and `ig_caption_fill_failed` (final)
- Lookup matched B1.9 via Tier-2 wildcard
- `record_outcome` wrote 25 `shadow_match` rows to `publisher_obstacle_outcomes`
- Match obstacle: `9bb9e1baac7431ae` (B1.9 caption-fill seed)

```
First MATCH log: 2026-05-02 16:24:53 UTC (publish#2515)
Total shadow_match outcomes: 25
Per-task average: ~5 matches (3 caption_verify retries + 1 caption_fill + 1-2 tier-final from _set_error_code_from_events double-fire)
```

### Open follow-ups (next session)

1. **Probe double-fire deduplication** — `_set_error_code_from_events` is called from both `_fail_task` AND `update_status('failed')` for the same task; probe fires twice. Track per-task probed flag to dedupe.
2. **Debug log cleanup** — `[obstacle-kb-debug]` info lines in `_obstacle_kb_shadow_probe` are useful for ongoing observability; revisit cleanup later.
3. **Resource_ids filter in Tier-2** — currently ignored (only key_texts overlap + dialog_indicator + platform). Tightening would reduce false-positive surface (relevant when promoting B1.9 from experimental → candidate → stable).
4. **Status='probationary' DB constraint** — DB CHECK only allows `experimental|candidate|stable|blacklisted`. W2 design implied `probationary` tier; reconcile in W5 promoter.

## Test plan reference

- Pre-merge full pytest: 543 passed, 12 baseline failed (test_publish_guard, test_testbench_orchestrator, test_switcher_read_only, ig_camera_recovery — all pre-existing on `8cd58de`), 7 skipped
- 15 new probe-coverage tests (4 helper + 2 tier-final + 9 intermediate)

## Conventions established (apply to Stage B+)

1. **step↔category char-for-char** — analytics join key. Bidirectional contract in tests.
2. **No `locals().get(...)`** — code smell that hides clearer alternatives.
3. **pytest fixture injection** — no `sys.path.insert + from conftest import` anti-pattern.
4. **`_stub_publisher_mixin(mixin_cls, platform)` factory** — single source for IG/TT/YT mixin stubs in `tests/conftest.py`.
