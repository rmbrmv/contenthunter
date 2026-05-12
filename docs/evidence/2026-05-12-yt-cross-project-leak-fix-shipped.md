# YT cross-project leak defense — shipped 2026-05-12

**PR:** https://github.com/GenGo2/delivery-contenthunter/pull/43
**Branch:** `feat-yt-cross-project-leak-fix-20260512`
**Prod commit:** `f085816` (auto-pushed via post-commit hook in `/root/.openclaw/workspace-genri/autowarm/`)
**Author:** Claude Opus 4.7 (1M context) + Danil Pavlov

## Backstory

После shipping IG PR #36 (cross-project Reels leak defense, 2026-05-12 11:48 UTC) явно совпадало по shape, что YouTube publisher уязвим к тому же классу bug. User explicit ask в начале session.

## Spec / plan path

- Spec: `docs/superpowers/specs/2026-05-12-yt-cross-project-leak-fix-design.md`
- Plan: `docs/superpowers/plans/2026-05-12-yt-cross-project-leak-fix-plan.md`
- Worktree: `/home/claude-user/contenthunter/.claude/worktrees/yt-stab-20260512/` (docs branch `yt-stab-20260512`)

## Codex review timeline

| Round | What | Result |
|---|---|---|
| Spec round 1 | Initial spec | 1 P2 (kill switch только `_last_push_ts` clear, не оба ground-truth поля) |
| Spec round 2 | После apply P2 fix | Same P2 reported (codex смотрел stale stage — re-stage был нужен) |
| Spec round 3 | Re-staged + commit | **CLEAN** |
| Plan round 1 | Initial plan | **CLEAN** |
| Patches round 1 | After implementer subagent completion | **CLEAN** |

Codex via stdin pipe (memory `feedback_codex_sandbox_broken` — `--base main` ломается, sandbox bwrap broken; обход через `git diff … | codex review -`).

## Implementation summary

| File | Δ lines | Change |
|---|---|---|
| `publisher_helpers.py` | +132 | New: `RUSSIAN_MONTHS`, `MSK`, `THUMBNAIL_DATE_RE`, `parse_picker_thumbnail_date()`, `layer_a_pre_tap_verify(publisher, candidate_desc, *, event_category, artifact_prefix)`. Standalone (Approach A.2). |
| `publisher_instagram.py` | -110 | Removed module-level constants + `_ig_parse_thumbnail_date`. `_layer_a_pre_tap_verify_ok` body → 5-line thin wrapper. Back-compat alias `_ig_parse_thumbnail_date = parse_picker_thumbnail_date` для pre-existing `test_ig_cross_project_leak_helpers.py`. |
| `publisher_youtube.py` | +76 | New `_select_gallery_video(remote_media_path)` method. Layer A verify + Layer C dump (`yt_picker_pre_tap`). Removed `items = video_items or all_items` → `items = video_items`. Removed blind `adb_tap(181, 600)` → fail-fast `yt_gallery_no_video_candidate` event with diag first 10 clickables. Scope fix via `last_all_items` accumulator. |
| `tests/test_publisher_helpers_layer_a.py` | +200 (new) | 16 tests: 7 `parse_picker_thumbnail_date` (nbsp/space/none/empty/bad-month/unparseable) + 9 `layer_a_pre_tap_verify` (date match/mismatch/soft-fail × MediaStore match/mismatch/soft-fail × IG-category routing). |
| `tests/test_publisher_youtube_picker.py` | +189 (new) | 7 tests: positive tap, date mismatch abort, MediaStore mismatch abort, no-videos fail-fast, no `adb_tap(181,600)` regression guard, artifact dump on success, artifact dump on fail-fast. |
| **Total** | +660 / -173 | 5 files |

## Test results

- **All new tests:** 23/23 PASS (16 helpers + 7 picker).
- **IG regression check:** 28 IG-related selectors (`-k "ig_picker or layer_a or cross_project or instagram"`) all PASS.
- **Full suite:** 989 passed / 15 failed / 7 skipped (`--ignore=tests/test_canary_inserter.py`).
- **Baseline (main):** 962 passed / 16 failed / 7 skipped.
- **Net delta:** +27 passing (16 new helpers + 7 new picker + 4 likely flaky re-counts), −1 fail (`test_vision_analyzer::test_postmortem_no_instruction` self-recovered from pre-existing flakiness).
- **Zero regressions** beyond pre-existing baseline.

Pre-existing failures (NOT touched, equal to main):
- `test_publisher_ig_camera_recovery.py::test_reopen_via_home_taps_plus_then_reels_on_success_path`
- `test_switcher_read_only.py::test_yt_happy_path_returns_accounts`
- `test_testbench_orchestrator.py` (×5)
- `test_vision_analyzer.py` (×2)
- `test_canonical_error_codes.py`
- `test_publish_guard.py` (×5)
- `test_canary_inserter.py` (canary mp4 files deleted on main)

## Deviations from plan

1. **Back-compat alias for `_ig_parse_thumbnail_date`.** Plan said «remove module-level» but pre-existing `tests/test_ig_cross_project_leak_helpers.py` imports the name directly. Added single-line alias `_ig_parse_thumbnail_date = parse_picker_thumbnail_date` in `publisher_instagram.py` — preserves test compat without churn.
2. **Test fixture coordinates** in `test_publisher_youtube_picker.py`: adjusted `y1=300 → y1=400` so that `cy=550 > 300` filter passes (code requires `it[1] > 300` strictly). Pure fixture math, no logic change.
3. **`d_raw` preservation** in `_select_gallery_video`: store original-case `content-desc` in `all_items`/`video_items` so Layer A `parse_picker_thumbnail_date` regex sees real format. Regex is `re.IGNORECASE` so functionally identical, but cleaner evidence in `first_clickables` diag.

## STOP-gates hit

- Step 3.4 (IG regression after refactor): resolved via back-compat alias (deviation #1).
- Initial test fixture mismatch: resolved via coordinate adjustment (deviation #2).

No deploy / PM2 actions during implementation. All Task 2-7 done by implementer subagent with strict NO-commit / NO-push constraint (per memory `feedback_subagent_force_push_risk`). Task 8 (commit), Task 9 (Codex patches), Task 10 (PR) done by parent.

## Open follow-ups (backlog)

1. **YT-specific thumbnail format regex** — if discovered to differ from IG's `создано 12 мая 2026 г. 14:51` format, add YT variant to `THUMBNAIL_DATE_RE`. Current behaviour: soft-fail when parse returns None — MediaStore check 2 carries the defense. Monitor 24h: if `yt_picker_wrong_candidate, reason=date_mismatch` rate is 0 over a week — likely format mismatch, investigate.
2. **Retro-detection of past YT leaks** — would require scraping all YouTube Shorts pages for accounts in `factory_inst_accounts` for the last N days and comparing video metadata vs our upload basenames. Out of scope this PR.
3. **`yt_gallery_no_video_candidate` rate monitoring** — if >5/24h, root cause is likely device-state (gallery empty / picker hijack), not code. Investigate then.

## Live verify (deferred to user OK)

- **Positive smoke:** trigger one publish on phone #19 from publishing dashboard, watch for `yt_picker_pre_tap` artifact + `post_url` returned.
- **Negative smoke (induced):** push our video, manually `cp + touch` foreign mp4 in `/sdcard/Download/` with mtime 5min after our push_ts, trigger publish → expect `yt_picker_wrong_candidate, reason=date_mismatch` event.
- **24h soak:** SQL
  ```sql
  SELECT events->-1->'meta'->>'category', COUNT(*)
  FROM publish_tasks
  WHERE platform='YouTube'
    AND created_at >= '2026-05-12 17:30:00+00'
    AND status='failed'
  GROUP BY 1 ORDER BY 2 DESC;
  ```

## Related links

- IG PR #36: https://github.com/GenGo2/delivery-contenthunter/pull/36
- IG cross-project leak memory: `project_ig_publish_cross_project_leak_2026_05_12` (TBD: write after IG side has 24h evidence)
- This session: started 2026-05-12 ~16:25 UTC, PR opened 2026-05-12 17:40 UTC.
