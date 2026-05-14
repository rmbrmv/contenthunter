# IG "Edits" promo banner dismissal — SHIPPED ✅ 2026-05-14

**Merge commit:** `5372d18` (`Merge: IG "Edits" promo banner dismissal (OpenProject #61)`) on `GenGo2/delivery-contenthunter` `main`.
**Branch:** `fix-ig-edits-banner-dismiss-20260514` (10 commits, +432/−48, 3 files) — merged `--no-ff`, branch + worktree cleaned up.
**Deployed to prod tree:** `/root/.openclaw/workspace-genri/autowarm/` on `5372d18`. No PM2 reload — `server.js` spawns `publisher.py` per task, next IG publish picks up the new code.
**OpenProject:** [#61](https://openproject.contenthunter.ru/work_packages/61) — status → `Тестирование` (shipped, pending 24h verify).
**Spec:** `docs/superpowers/specs/2026-05-14-ig-edits-banner-dismiss-design.md`
**Plan:** `docs/superpowers/plans/2026-05-14-ig-edits-banner-dismiss.md`
**Triage that found it:** `docs/evidence/2026-05-14-ig-publish-failure-triage.md`

## Why

7-day IG triage (08–14.05, 229 prod failures) found the largest single actionable cluster — **~34 failures/7d, 20 devices, 27 accounts, 6 raspberries, ongoing since 10.05** — had one root cause: Instagram's new "Edits" app promo bottom-sheet. Two symptoms:

- `ig_picker_wrong_candidate` (18/7d) — the banner overlays the picker grid; the publisher selects the wrong clip; the date / MediaStore guard aborts.
- `ig_gallery_no_video_candidate` Play-Store sub-mode (~16/7d) — the publisher's tap lands on the banner's «Установить приложение» button → Google Play opens → Instagram backgrounds → the gallery scan parses Play Store UI and fails "no video candidate".

Confirmed from screencasts (tasks 5031, 5026, 5662, 5611) and a real UI dump (task 5031): the banner is a Compose bottom-sheet carrying `… с помощью Edits` + `Установить приложение`, with a `Закрыть панель` close affordance. A pre-existing `_dismiss_ig_edits_promo` helper existed but was wired only into the camera stage, used stale month-old markers, and dismissed via `back` (which could close IG entirely).

## What

All in `publisher_instagram.py` + one new test file.

- **`_is_ig_edits_promo(ui_xml)`** — pure module-level detector. Requires BOTH `с помощью Edits` AND `Установить приложение` — so it never matches the ever-present composer "Edits" *tab*.
- **`_dismiss_ig_edits_promo(self, ui_xml=None) -> str`** — rewritten from the old `bool`/`back`×2/`force-stop` version. 3-state return (`absent` / `dismissed` / `still_present`); dismissal ladder, re-checked after each rung: tap `Закрыть панель` → swipe-down → single `back`. No `force-stop` on this path (picker/editor can't afford a relaunch). Never taps the install control. Accepts a pre-fetched dump.
- **`_ig_handle_edits_promo_at_picker(self, ui_xml, step) -> str`** — orchestration helper. Play-Store-foreground check first → emits `ig_edits_promo_playstore_hijack` + returns `failed`; else dismisses → on `still_present` emits `ig_edits_promo_undismissable` + returns `failed`; else `clear` / `dismissed`. Two new honest error codes replace the misleading `ig_gallery_no_video_candidate` attribution for these cases.
- **Wired into 4 call sites** in `publish_instagram_reel`: Шаг-5 gallery-open retry loop (`gallery_open`), video-candidate parse loop (`gallery_select`), and the two editor-loop re-select paths (`editor_loop_1` / `editor_loop_2`). The pre-existing camera-loop call site was updated for the new 3-state return.
- **17 new tests** in `tests/test_ig_edits_banner_dismiss.py`, fixtures derived from the real task-5031 UI dump (including the critical regression guard: a plain picker with only the "Edits" tab must NOT be detected as the banner).

`_layer_a_pre_tap_verify_ok` (the `date_mismatch` / `mediastore_top_mismatch` checks) was left untouched — once the banner is dismissed the picker shows the full grid and Layer A passes naturally.

## How it was built

5 TDD tasks via subagent-driven development; each task got spec-compliance + code-quality review with fix loops. Review catches worth noting:
- Task 2 — `exact=True` on the `Закрыть панель` tap was flagged fragile (`tap_element` does full-label match; a future IG build adding a `text` attr would silently miss) → changed to `exact=False`.
- Task 4 — the new parse-loop `continue` could skip the `try`-block where `all_clickable` is initialized → hoisted `all_clickable = []` before the loop (also hardens a pre-existing latent NameError).
- Final whole-branch review — stale `return_value=False` mocks of `_dismiss_ig_edits_promo` in `test_publisher_ig_camera_recovery.py` (its contract changed bool→str) → aligned 10 occurrences to the string API as mock+condition pairs.
- `codex review` of the full branch diff: no regressions, 0 P1.

**Tests on the merged prod tree:** 410 passed, 3 failed — the 3 failures (`test_reopen_via_home_taps_plus_then_reels_on_success_path`, `test_ig_wrong_camera_mode_invokes_probe`, `test_ig_about_account_modal_invokes_probe`) are pre-existing, verified failing on the base commits, not introduced by this branch.

## Live verify (24h post-deploy) — PENDING

Query `publish_tasks` for the 24h after 2026-05-14:
- `ig_edits_promo_dismissed` info events present → the helper is firing on real banners.
- `ig_picker_wrong_candidate` + `ig_gallery_no_video_candidate` Play-Store sub-mode drop sharply from the ~34/7d (~4.9/day) baseline.
- `ig_edits_promo_playstore_hijack` low (residual only); `ig_edits_promo_undismissable` near-zero — if either is non-trivial, the dismissal ladder / markers need another iteration.

**Acceptance band:** combined `ig_picker_wrong_candidate` + `ig_gallery_no_video_candidate`(Play-Store) ≤ 20% of the pre-fix daily rate within 24h, with `ig_edits_promo_dismissed` events present (proving the path was exercised).

## Rollback

`git revert 5372d18` on the prod tree + `git push origin main`. Single additive change confined to `publisher_instagram.py` + test files; the new error codes are additive (no consumer asserts their absence).

## Open / backlog

- 24h live verify (above) — the one remaining gate before `Тестирование` → `Готово`.
- Non-banner sub-modes of `ig_gallery_no_video_candidate` (empty "Черновики Reels" tab ~10/7d, editor/playback screen ~11/7d) — separate navigation bug, separate ticket, out of #61's scope.
- Noted by the Task-4 reviewer (not blocking): `_ig_handle_edits_promo_at_picker` calls `_current_foreground_package()` (one `dumpsys`) on every iteration even on the no-banner path; a future cleanup could gate it behind `_is_ig_edits_promo(ui_xml)` first.
