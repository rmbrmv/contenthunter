# Instagram publish failures — triage 2026-05-14

**Scope:** all `publish_tasks` with `platform='Instagram'` and `status='failed'`,
non-testbench, non-canary (799 all-time; ~232 in the last 7 days, 2026-05-07→05-14).
**Goal:** rank failure causes by volume, pick the top one, open an OpenProject bug.
**Method:** group by the *last* `events[].type='error'` event's `meta.category`
(the task-level `error_code` column is unreliable — it records the *first* error,
usually a preflight one). Logs + screencasts reviewed for the top 4 categories.
**OpenProject ticket:** [#68 — Выкладка Instagram: после открытия галереи робот
попадает на пустую вкладку «Черновики Reels» вместо «Недавние»](https://openproject.contenthunter.ru/work_packages/68)
(type Ошибка, parent Epic #49 «Выкладка баги»).

> **Mid-triage correction:** the two highest categories were *already* tracked.
> `ig_picker_wrong_candidate` + the Edits-banner part of `ig_gallery_no_video_candidate`
> are **WP #61** (fix merged `5372d18`, 2026-05-14 14:22 UTC, status Тестирование).
> `ig_share_tap_no_progress` is being fixed via GitHub PRs (#49/#51, "выкатили 13.05"
> per WP #61). So the only *unfiled* high-volume cause is the `ig_gallery_no_video_candidate`
> **empty-«Черновики» sub-mode** → that is what WP #68 covers. No duplicates were filed.

## 7-day catalog (created_at ≥ 2026-05-07, prod-real IG failed tasks)

| Category | 7d | 3d | today | Status / verdict |
|---|---:|---:|---:|---|
| **`ig_gallery_no_video_candidate`** | **39** | 17 | 2 | **ACTIVE** — gallery-open lands on the wrong screen |
| `ig_share_tap_no_progress` | 33 | 26 | 0 | active until 05-13 09:47, quiet ~28h since |
| `media_store_unreadable_pre_publish` | 32 | 0 | 0 | **dead** — stopped 05-09, = the 2026-05-09 `_ms_query` Android-15 outage (fixed) |
| **`ig_picker_wrong_candidate`** | **15** | 15 | 2 | **ACTIVE + NEW** — first seen 05-12, false-positive guard aborts |
| `ig_app_launch_failed` | 14 | 11 | 3 | device-state — IG process won't foreground |
| `ig_target_not_in_picker` | 14 | 9 | 2 | config — account not provisioned on the device |
| `ig_upload_confirmation_timeout` | 13 | 0 | 0 | dead — stopped after 05-08 |
| `process_interrupted` | 12 | 7 | 4 | task killed mid-run (orchestrator/restart) |
| `screencast_stop_failed` | 11 | 6 | 1 | screencast infra, not a publish bug |
| `screencast_pull_failed` | 10 | 9 | 6 | screencast infra, not a publish bug |
| `ig_editor_timeout` | 9 | 1 | 1 | mostly tailed off after 05-08 |
| `ig_camera_open_failed` | 9 | 6 | 2 | active, low volume |
| (no error-event) | 7 | 7 | 0 | all `error_code=switch_failed_unspecified`, 05-13 |
| `ig_caption_fill_failed` | 4 | 0 | 0 | dead — root-caused & fixed 2026-05-03 |
| `adb_device_not_ready` | 3 | 2 | 1 | device-side |
| `publish_failed_generic` | 3 | 2 | 2 | generic |
| `ig_gallery_button_not_found` / `media_store_pollution_pre_publish` / `ig_wrong_camera_mode` / `critical_exception` | 1 each | — | — | long tail |

**Largest currently-active cause: `ig_gallery_no_video_candidate` (39 / 7d).**
Two clean false-positive runner-ups are in `ig_picker_wrong_candidate` (15 / 7d, brand new).

> Note: `media_store_unreadable_pre_publish` (32) and `ig_upload_confirmation_timeout`
> (13) together are 45 fails but both stopped firing 5–6 days ago — not actionable.

## Root cause — top categories (logs + screencast)

### 1. `ig_gallery_no_video_candidate` — 39 (gallery-open navigates to the wrong screen) → **WP #68**

Event chain is identical across samples: account-switch → `ig_create_reels_tile_strict_match`
→ «камера открыта» → «шаг 4 — открытие галереи» → «шаг 5 — выбор видео из галереи»
→ `IG: видео не найдено в gallery picker — fail-fast (RC-8)`.

The RC-8 fail-fast is correct — there genuinely is no video candidate, **because the
publisher is not on the gallery picker at all.** Screencasts show two wrong
destinations, and one dominates:

- **Empty «Черновики Reels» Drafts screen — 6 of 8 sampled tasks** (5870, 5788, 5348,
  5318, 5286, 5281). The whole failure window shows «← Черновики Reels / Черновиков
  пока нет». The gallery picker has tabs «Недавние / Черновики / Шаблоны»
  (`publisher_instagram.py:2293`); the publisher ends up on the empty Drafts tab
  instead of «Недавние». **This is the unfiled bug WP #68 was opened for.**
- **Google Play hijack — 1 of 8 sampled** (5031, `clickpay_under`, rpi 9) — Play Store
  on the "TikTok Studio" page; a blind tap hits system nav / Recents
  (`publisher_instagram.py:675` `_log_blind_tap_diag`, "Mode B"). Note WP #61 attributes
  *its* Play-Store hijacks to the Edits-banner install button — 5031 looks like a
  separate Recents hijack, low volume, not separately filed.

WP #61's description estimated the Drafts/editor remainder at "~24 of 40"; the 6/8
sample suggests it is actually the **majority** (~29 of 39) of this category.

### 2. `ig_share_tap_no_progress` — 33 (Share tapped, upload never confirmed)

Chain: caption verified → «кнопка Поделиться нажата» → `wait_upload_iter0_diag` →
`ig_share_retry` ×2 → `ig_share_tap_no_progress`. Screencasts for 5277/5321 show
Instagram **back on the Reels feed** during the whole wait window — i.e. the share
sheet was dismissed/left, but `wait_upload` never saw an upload indicator. None of the
sampled tasks have a `post_url`. Ambiguous: the post may have published silently
(false-negative detection → duplicate-publish risk) or the Share tap missed. Needs a
dedicated screencast pass before this one is filed. Went quiet ~28h ago.

### 3. `ig_picker_wrong_candidate` — 15 (Layer-A pre-tap guard false-positives) — NEW → **WP #61**

> Already tracked as **WP #61** (root cause there: the Edits promo banner covers the
> lower previews so the picker selects a wrong/older video, which the date /
> MediaStore checks then correctly reject). Fix merged today, in Тестирование — not
> re-filed. The independent observation below (60 s tolerance is too tight on its own)
> is worth a comment on #61 *if* picker false-positives continue after the banner fix
> verifies.


`_layer_a_pre_tap_verify_ok` (`publisher_instagram.py:525`, `publisher_helpers.py:180`)
was introduced ~05-12 to reject foreign media. It is aborting on the *correct* video:

- **`date_mismatch` — 14/15.** e.g. task 5611:
  `thumbnail=2026-05-14T11:13:00+05:00` vs `push=2026-05-14T09:14:02+03:00` →
  Δ **62 s**, tolerance is **60 s**. Normalized to UTC the two times are essentially
  equal. The thumbnail content-desc is rendered by Android Gallery **truncated to the
  minute** (`:00` seconds), so up to ~59 s of precision is lost on top of the
  date_added-vs-mtime quantization the 60 s budget was meant to cover. Every observed
  delta is 62–65 s — just over the cliff. Screencasts (5611) confirm the gallery picker
  shows the correct video thumbnails; the guard simply mis-rejects them.
- **`mediastore_top_mismatch` — 1/15.** Task 5662: `MediaStore top-1='screenrec_5662_…
  .mp4' ≠ expected='autowarm_pq_…'`. The publisher's *own screen-recording file*
  (`screenrec_<task>_*.mp4`) lands in MediaStore and out-sorts the pushed media. The
  Layer-A check does not exclude `screenrec_*` names.

This is a self-inflicted regression: a guard meant to catch cross-project leaks is
instead the 4th-largest failure cause within 2 days of shipping, and every sampled
case is a false positive.

## Non-code causes (do not file as publisher bugs)

- `ig_target_not_in_picker` (14) — target account is not linked to the device
  (e.g. 5791: `'relisssme' не привязан к устройству`). Account provisioning.
- `ig_app_launch_failed` (14) — IG process won't come to foreground (stuck on
  `com.sec.android.app.launcher`). Device-state.
- `screencast_pull_failed` / `screencast_stop_failed` (21) — recording infra.
- `process_interrupted` (12) — task killed mid-run.

## Outcome

Filed **WP #68** — `ig_gallery_no_video_candidate` / empty «Черновики Reels» sub-mode.
This is the single largest *unfiled* IG publish-failure cause (~29 of 39 / week,
active daily). Fix direction: ensure the picker is on the «Недавние» tab before
searching for a video candidate.

Not filed (already tracked, no duplicates created):
- `ig_picker_wrong_candidate` + Edits-banner part of `ig_gallery_no_video_candidate`
  → **WP #61** (fix merged today, Тестирование).
- `ig_share_tap_no_progress` → GitHub PRs #49/#51, "выкатили 13.05" (no OpenProject WP;
  worth confirming whether one is wanted).

Watch-list after the #61 fix verifies: if `ig_picker_wrong_candidate` `date_mismatch`
keeps firing, the 60 s tolerance vs minute-truncated thumbnail is a real second cause
— comment on #61 rather than a new WP.

## Evidence

Screencasts pulled to `/tmp/ig_triage/` and montaged for the failure window:
5870, 5031 (`ig_gallery_no_video_candidate`); 5277, 5321 (`ig_share_tap_no_progress`);
5611, 5662 (`ig_picker_wrong_candidate`).
