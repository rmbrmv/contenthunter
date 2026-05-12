# YT picker-state guard — shipped 2026-05-12

**PR:** https://github.com/GenGo2/delivery-contenthunter/pull/47
**Branch:** `fix-yt-picker-state-guard-20260512`
**Spec:** `docs/superpowers/specs/2026-05-12-yt-picker-state-guard-design.md` (Codex CLEAN после 6 rounds)
**Plan:** `docs/superpowers/plans/2026-05-12-yt-picker-state-guard-plan.md` (Codex CLEAN)

## RC discovery

Через live picker probe + S3 dump retrieval за tasks 3970/5054/4889 выявлено: умbrella `yt_target_not_in_picker_after_scroll` (21 fails/7d) маскирует 2 разных RC:

1. **Picker dismissed mid-flight (race)** — 2/3 sample fails:
   - 3970: picker → video player (23-sec dead time)
   - 5054: picker → recents tray
2. **Target absent in picker (data drift)** — 1/3 sample fails:
   - 4889 (Lead_Content_1): handle отсутствует на phone, БД устарела, gmail=NULL

## Implementation

- New helpers: `_is_yt_picker_present`, `_sample_picker_diag`, `_yt_try_reopen_picker`
- `_scroll_picker_for_target` signature: добавлены `cfg, step`, return → `(found: bool, reason: str)`
- Reasons: `'found'` / `'exhausted'` (list-end proved) / `'max_iter_no_stale'` (cap, not proved) / `'dismissed_unrecovered'` (race after failed reopen)
- Caller line ~2660: emits `yt_picker_target_absent` (exhausted + picker present) / `yt_picker_dismissed` (race) / legacy fallback
- Picker-state guard gated на `attempt > 1` — first iter тoler но layout-quirks
- Heuristic: 2 footer-markers + ≥2 distinct gmail addresses (regex dedup)

## Codex review rounds (spec + plan + patches)

| Stage | Round | Findings |
|---|---|---|
| Spec | 1 | 1 P2 — exhausted RC vs target-absent gating |
| Spec | 2 | 2 P2 — implementation outline contradictions (return tuple, gating) |
| Spec | 3 | 1 P2 — first-dump dismissed must trigger reopen |
| Spec | 4 | 1 P2 — cfg/step needed in `_scroll_picker_for_target` |
| Spec | 5 | 1 P2 + 1 P3 — max_iter ≠ list-end |
| Spec | 6 | CLEAN ✅ |
| Plan | 1 | CLEAN ✅ |
| Patches | 1 | 1 P2 — Russian inflection «аккаунтом» missing |
| Patches | 2 | 1 P2 — target-scan before dismissal heuristic |
| Patches | 3 | 1 P2 — «Аккаунт(ом) Google» ambiguous between picker/profile |
| Patches | 4 | 1 P2 — distinct gmail count (dedup) |
| Patches | 5 | 1 P2 — first iter layout-quirk → gate at attempt>1 |

Round 6 spec + plan + final patch state: shipped с documented attempt>1 fallback as known design choice (not P2).

## Test summary

| | New | Total |
|---|---|---|
| Unit (`test_yt_picker_state_guard.py`) | 9 | 9 |
| Integration (`test_yt_picker_dismissed_recovery.py`) | 6 | 6 |
| **All pass** | | 15 |

Regression: 980 passed / 16 failed / 7 skipped, identical 16 fails as baseline.

## Out of scope (backlog)

- **Real RC of 23-sec dead time** на task 3970 — что dismisses picker. Hypothesis: spurious navigation / system overlay / launcher-press. Defensive guard первичен.
- **Lead_Content_1 data drift cleanup** — handle отсутствует на phone, БД ожидает. Manual deactivation или automated `account_revision` step.
- **24h soak SQL** для счёта новых RC:
  ```sql
  SELECT events->-1->'meta'->>'category', COUNT(*)
  FROM publish_tasks
  WHERE platform='YouTube' AND created_at >= NOW() - INTERVAL '24 hours' AND status='failed'
  GROUP BY 1 ORDER BY 2 DESC;
  ```
- **Шаг D (yt_editor_upload_timeout после AI Unstuck)** — следующая сессия. 13 fails/week, требует screen recordings analysis.

## Files changed

- `account_switcher.py` (+233 / −12)
- `tests/test_canonical_error_codes.py` (+4 / −2)
- `tests/test_switcher_youtube.py` (+13 / −3)
- `tests/test_yt_post_switch_verify.py` (+2 / −1)
- `tests/test_yt_picker_state_guard.py` (+122 new)
- `tests/test_yt_picker_dismissed_recovery.py` (+236 new)
- `tests/fixtures/yt_picker_*.xml` (4 fixtures)
