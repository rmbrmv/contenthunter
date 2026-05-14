# Design — IG "Edits" promo banner dismissal across picker + editor

**Date:** 2026-05-14
**Branch (planned):** `fix-ig-edits-banner-dismiss-20260514`
**Scope:** harden the existing `_dismiss_ig_edits_promo` helper and wire it into the Reels picker (Шаг 5) and editor-loop stages of `publisher_instagram.py`, so the Instagram "Edits" promo bottom-sheet is cleared before it can hide gallery thumbnails or get its install button tapped. Honest fail-fast for the residual Play-Store-hijack case.
**OpenProject:** [#61](https://openproject.contenthunter.ru/work_packages/61) (Ошибка, parent epic #49 «Выкладка баги»)
**Triage evidence:** `docs/evidence/2026-05-14-ig-publish-failure-triage.md`
**Memory cross-links:** [[project_ig_gallery_no_video_2026_05_10]] (prior partial fixes — Mode A/C/D; this is the next layer), [[feedback_publish_fail_analysis_video_first]] (screencast-first triage that surfaced the banner), [[feedback_class_vs_instance_test_calls]] (module-fn vs method test discipline), [[feedback_ui_dump_app_recognition]], [[feedback_codex_review_specs]].

## 1. Problem

Over 7 days (08–14.05) 229 prod Instagram publish tasks failed. The largest single actionable cluster — **~34 failures/7d, 20 devices, 27 accounts, 6 raspberries, ongoing since 10.05** — has one root cause: a new Instagram bottom-sheet banner promoting the "Edits" app.

### Failure pattern (confirmed from screencasts)

Instagram shows a bottom-sheet banner — *«Сделайте свои видео лучше с помощью Edits»* / *«Усовершенствуйте свои видео с помощью Edits»*, with a large purple **«Установить приложение»** button — non-deterministically over the Reels composer (camera, gallery picker, editor). The publisher does not clear it, producing two symptoms under two different error codes:

| Symptom | Error code | Count/7d | Mechanism |
|---|---|--:|---|
| Banner covers picker thumbnails | `ig_picker_wrong_candidate` (`date_mismatch`, `mediastore_top_mismatch`) | 18 | Banner overlays the bottom ~45% of the "Недавние" grid. Only the top row of thumbnails is parsed; the wrong clip is selected; `_layer_a_pre_tap_verify_ok` catches the date/MediaStore mismatch and aborts. |
| Banner's install button gets tapped | `ig_gallery_no_video_candidate` (Play-Store sub-mode) | ~16 | A tap lands on «Установить приложение», Google Play opens to the "Edits" app page, Instagram drops to background. The subsequent gallery scan parses Play Store UI (`first_clickables` desc contains "отзыв", "скриншот N из 6", "возрастные ограничения") and fails "no video candidate". |

Screencast evidence: tasks **5031, 5026** show `picker → editor → Edits banner → Google Play`; tasks **5662, 5611** show the banner covering the picker at selection time.

### Root cause: why the existing fix misses it

A `_dismiss_ig_edits_promo` helper already exists (`publisher_instagram.py:1111`) but is incomplete:

1. **Wiring gap.** It is called from exactly one place — the camera-wait loop (`publisher_instagram.py:1482`, inside `_open_instagram_camera`). The screencasts show the banner biting at the **picker** (Шаг 5) and **editor** stages, which run *after* the camera loop. The banner that appears post-camera is never checked.
2. **Stale detection.** Markers `'Установить приложение' in ui and ('Edits' in ui or 'edits' in ui)` were confirmed against tasks from **2026-04-15** (month-old UI). Also `'Edits'` is the label of an ever-present composer *tab* (`[Edits] [Черновики] [Шаблоны]`), so `'Edits' in ui` is true even when no banner is shown — the helper relies on `'Установить приложение'` carrying the whole signal, and there is a smaller install-banner variant (Play-Store-style row "Edits: Видеомейкер … Установить") that the current marker set may not catch.
3. **Unreliable dismissal.** It dismisses via `back` keyevent; the helper's own comments record that `back` closed Instagram entirely (task #299), which is why a `force-stop + relaunch` escalation was bolted on. `force-stop` mid-picker/editor throws away all publish progress.
4. **Pre-picker guard is one-shot.** `_ig_classify_pre_picker_state` (`publisher_instagram.py:350`) runs once between Шаг 4 and Шаг 5 (`:1939`). It *would* catch `com.android.vending` as `ig_external_app_foreground` — but at that instant Instagram is still foreground; the banner appears and the install tap happens later, inside the Шаг 5 / editor loops, where no guard runs. This is why the triage shows 0 `ig_external_app_foreground` and 16 `ig_gallery_no_video_candidate` Play-Store-mode.

## 2. Fix

Approach **A** (chosen over: turning the pre-picker guard into a per-iteration guard — muddies one function with two contracts; and "just add more call sites for the existing helper" — leaves the stale markers and unreliable `back` in place). Centralize a hardened banner check/dismiss and call it at every UI-dump point in the picker + editor stages.

All code changes are in `publisher_instagram.py`. No schema changes, no changes to other publisher modules.

### 2.1 Detection — `_is_ig_edits_promo(ui_xml)` (new pure module-level function)

Module-level function (placed near `_ig_classify_pre_picker_state`), so it is unit-testable without an instance — per [[feedback_class_vs_instance_test_calls]].

Returns `True` only for the **banner**, never for the composer "Edits" tab. Detection: return `True` when the banner-specific promo phrase `с помощью Edits` is present **AND** the install-button text `Установить приложение` is present. Both strings are confirmed against a real UI dump (see below).

Guards: empty / `None` / unparseable XML → `False`. Substring matching is acceptable here (consistent with the file's existing detection helpers); `с помощью Edits` is the primary anchor because it is banner-copy that never appears as a tab/control label (the composer "Edits" *tab* is just `text="Edits"`).

> **Ground truth — real UI dump (task 5031, `gallery_blind_tap_after_step4`).** Screen 1080×2340. The banner is a Compose bottom-sheet under `resource-id=…:id/compose_bottom_sheet_container` / `bottom_sheet_compose_view`. Confirmed nodes:
> - `TextView` `text="Сделайте свои видео лучше с помощью Edits"` bounds `[237,1417][782,1633]`
> - `TextView` `text="Установить приложение"` bounds `[314,2075][766,2122]`; the clickable install control is `View` `resource-id=…:id/igds_button` bounds `[45,2031][1035,2166]` (centre `(540,2098)`)
> - **`Button` `content-desc="Закрыть панель"` bounds `[0,0][1080,1338]`** — a reliable, content-desc-addressable close affordance (the scrim above the sheet). This is the primary dismissal target — see 2.2.
> - the promo `ImageView` carries a long `content-desc` containing the word `видео` ("Рестайлинг этого **видео** сделан с помощью…") — this is *why* the gallery video-candidate parser can mis-pick the banner: its `'видео' in content-desc` heuristic matches banner copy. Dismissing the banner removes these nodes from the dump entirely, so the parser never sees them — no change to the parser heuristic is needed.

### 2.2 Dismissal — `_dismiss_ig_edits_promo(ui_xml=None)` (rewritten instance method)

Signature change: accepts an optional already-fetched `ui_xml` (callers in tight loops already hold a dump — avoid a redundant `dump_ui()`); when `None`, fetches one.

Return type changes from `bool` to a status string: `'absent'` | `'dismissed'` | `'still_present'`.

Logic:
1. If `not _is_ig_edits_promo(ui)` → return `'absent'`.
2. Dismissal ladder, re-dumping and re-checking `_is_ig_edits_promo` after each rung; stop as soon as the banner is gone. Ladder ordered by proven reliability against the real UI dump:
   1. **Close affordance** — tap the centre of the clickable node with `content-desc="Закрыть панель"` (confirmed present in the real dump). Primary method.
   2. **Swipe-down** — downward swipe within the sheet region (e.g. `(540,1450) → (540,2300)`) for IG builds where the close affordance is absent.
   3. **`back`** keyevent — last resort, single press (no repeat, no force-stop on this path).
3. After the ladder: if the banner is gone → emit `info` event `ig_edits_promo_dismissed` with `meta.method` ∈ `{close_button, swipe_down, back}` and return `'dismissed'`; if still present → return `'still_present'` (caller decides — see 2.4).

Never taps the `Установить приложение` / `igds_button` control. The `force-stop + relaunch` escalation is **removed from this helper** — it remains only as the camera-stage's own recovery (the camera loop can afford a relaunch; the picker/editor cannot).

### 2.3 Play-Store-hijack & undismissable — honest fail-fast

Two new error codes, emitted as `type='error'` events:

- **`ig_edits_promo_playstore_hijack`** — at the top of each video-candidate parse-loop iteration (and editor re-select iteration), check `_current_foreground_package()`; if `com.android.vending` → `_save_debug_artifacts`, `_safe_kb_probe`, emit `ig_edits_promo_playstore_hijack`, `return False`. Replaces the misleading `ig_gallery_no_video_candidate` for this case. No recovery attempt (per decision: fail-fast, dispatcher re-queues — see [[reference_publish_requeue_path]]).
- **`ig_edits_promo_undismissable`** — if `_dismiss_ig_edits_promo` returns `'still_present'` after the full ladder at a picker/editor call site → `_save_debug_artifacts`, emit `ig_edits_promo_undismissable`, `return False`. Distinguishes "banner present and we couldn't clear it" from "banner cleared but gallery still empty" (which stays `ig_gallery_no_video_candidate`).

### 2.4 Wiring — new call sites in `publisher_instagram.py`

| Location | Current behaviour | Change |
|---|---|---|
| Шаг 5 gallery-open retry loop, after `ui = self.dump_ui()` (~`:1960`) | dismisses location dialog, camera-permission dialog, generic OK | insert `_dismiss_ig_edits_promo(ui)` before the `gallery_grid_item_thumbnail` break-check; on `'dismissed'` → `continue`; on `'still_present'` → fail-fast `ig_edits_promo_undismissable` |
| Video-candidate parse loop, after `raw_ui = self.dump_ui()` (~`:1996`) | parses thumbnails, fail-fast RC-8 | (a) Play-Store foreground check → `ig_edits_promo_playstore_hijack`; (b) `_dismiss_ig_edits_promo(raw_ui)` → on `'dismissed'` retry the parse iteration; on `'still_present'` → `ig_edits_promo_undismissable` |
| Editor-loop gallery re-select paths (~`:2259`, ~`:2485`) | RC-8 fail-fast on empty re-select | same pair of checks (Play-Store foreground + banner dismiss) before the existing RC-8 emit |
| Existing camera-loop call site (`:1482`) | `if self._dismiss_ig_edits_promo():` (bool) | update to the new return type: treat `'dismissed'` and `'still_present'` as "was handled / present" to preserve the existing `streak`/escalation behaviour |

### 2.5 Out of design scope — what is deliberately *not* touched

- `_layer_a_pre_tap_verify_ok` (`:499`) and its `date_mismatch` / `mediastore_top_mismatch` checks stay exactly as-is. Once the banner is dismissed the picker shows the full grid, our pushed video is top, and Layer A passes naturally. Fixing the banner *is* the fix for `ig_picker_wrong_candidate`.
- The non-banner sub-modes of `ig_gallery_no_video_candidate` (empty "Черновики Reels" tab ~10/7d, editor/playback screen ~11/7d) — separate navigation bug, separate ticket, not in #61's scope.
- `_ig_classify_pre_picker_state` keeps its one-shot contract unchanged.

## 3. Test plan (TDD-first)

New test file `tests/test_ig_edits_banner_dismiss.py`. Write failing tests first.

**`_is_ig_edits_promo` (pure function):**
- Positive — bottom-sheet variant XML (contains `с помощью Edits` + `Установить приложение`).
- Positive — small install-banner variant XML (`Edits:` app-name + `Установить`, no `с помощью Edits`).
- **Negative — plain Reels picker** with only the `[Edits]` composer tab present and no banner → must return `False` (this is the regression guard against the stale-marker problem).
- Negative — empty string, `None`, malformed XML → `False`.

**`_dismiss_ig_edits_promo` (instance method, faked `dump_ui` / `adb` / `log_event`):**
- Banner absent → returns `'absent'`, no taps dispatched.
- Banner present, cleared by swipe-down → returns `'dismissed'`, `meta.method='swipe_down'`, `ig_edits_promo_dismissed` event emitted.
- Banner present, swipe-down fails, close-button clears it → `'dismissed'`, `meta.method='close_button'`.
- Banner persists through the whole ladder → `'still_present'`, no `ig_edits_promo_dismissed` event.
- `Установить приложение` node is never the target of a dispatched tap (assert on recorded tap coordinates).
- Malformed XML input → `'absent'` (no crash).

**Wiring / fail-fast:**
- Video-candidate parse loop with `_current_foreground_package` faked to `com.android.vending` → emits `ig_edits_promo_playstore_hijack`, returns `False`, does not emit `ig_gallery_no_video_candidate`.
- Шаг 5 loop with banner that won't dismiss → emits `ig_edits_promo_undismissable`.

Run the full existing IG suite (`tests/test_ig_*.py`, `tests/test_publisher_ig_*.py`) to confirm no regression. Pre-existing unrelated failures (per memory: TT switcher canonical-error-codes test) are not introduced by this change and are out of scope.

## 4. Rollout

- Branch `fix-ig-edits-banner-dismiss-20260514` in `GenGo2/delivery-contenthunter`, PR, squash-merge after `codex review` rounds reach 0 P1 and tests are green.
- Deploy: `git pull --ff-only` on the prod tree `/root/.openclaw/workspace-genri/autowarm/`. No PM2 reload required — `server.js` spawns `publisher.py` as a subprocess per task, so the next task picks up the new code. (Confirm prod tree is on `main` and fast-forwardable before pulling — per [[feedback_pm2_dump_path_drift]], [[feedback_subagent_force_push_risk]]: no force-push.)
- Optional pre-prod: one testbench live-smoke on phone #19 with a seeded IG task to confirm the banner path end-to-end, if a task can be made to surface the banner.

## 5. Live verify (24h post-deploy)

Query `publish_tasks` for the 24h after deploy:
- **`ig_edits_promo_dismissed`** info events appear → the helper is firing on real banners.
- **`ig_picker_wrong_candidate`** (`date_mismatch` + `mediastore_top_mismatch`) and **`ig_gallery_no_video_candidate`** Play-Store sub-mode drop sharply from the ~34/7d baseline.
- **`ig_edits_promo_playstore_hijack`** count is low (residual only) and **`ig_edits_promo_undismissable`** is near-zero — if either is non-trivial, the dismissal ladder or detection markers need another iteration.

### Acceptance band
Combined `ig_picker_wrong_candidate` + `ig_gallery_no_video_candidate`(Play-Store) down to **≤ 20%** of the pre-fix daily rate within 24h, with `ig_edits_promo_dismissed` events present (proving the path was exercised, not just quiet).

## 6. Rollback plan

Single-file, additive change. Rollback = revert the merge commit and `git pull --ff-only` on the prod tree. The new error codes are additive (no consumer asserts their absence); the `_dismiss_ig_edits_promo` return-type change is contained to `publisher_instagram.py` (one existing call site updated in the same commit).

## 7. Risks and limitations

- **Marker accuracy.** Markers (`с помощью Edits`, `Установить приложение`) are confirmed against a real UI dump (task 5031). Residual risk is IG changing the copy in a future build → `_is_ig_edits_promo` misses (banner not dismissed — no worse than today). The negative test against the plain composer-tab picker bounds the false-positive risk.
- **Dismissal geometry.** The primary rung taps the content-desc-addressable `Закрыть панель` node (no hard-coded coordinates). The swipe-down rung does use screen-relative coordinates; `back` is the final fallback.
- **Banner appearing between dumps.** The check runs at every dump point but not continuously; a banner that appears and is tapped within a single `sleep` window still slips through — that residual is exactly what `ig_edits_promo_playstore_hijack` fail-fast covers honestly.
- The non-banner `ig_gallery_no_video_candidate` modes remain — this fix does not move their count.

## 8. Out of scope (deferred)

- Empty "Черновики Reels" tab and editor/playback sub-modes of `ig_gallery_no_video_candidate` — separate navigation bug.
- `ig_app_launch_failed`, `ig_target_not_in_picker`, `ig_share_tap_no_progress` (already addressed by the 13.05 fix) — unrelated root causes.

## 9. Acceptance criteria summary

1. `_is_ig_edits_promo` detects both banner variants and does **not** match the plain composer with only the "Edits" tab.
2. `_dismiss_ig_edits_promo` clears the banner via swipe-down / close-button / back without `force-stop`, returns a 3-state status, and never taps «Установить приложение».
3. Banner dismissal runs at every UI-dump point in Шаг 5 and the editor re-select loops, not just the camera loop.
4. Play-Store foreground during the picker/editor → `ig_edits_promo_playstore_hijack` (honest), not `ig_gallery_no_video_candidate`.
5. New + existing IG tests green.
6. 24h post-deploy: `ig_edits_promo_dismissed` events present and the combined banner-attributable failure rate within the acceptance band.
