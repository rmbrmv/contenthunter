# Instagram publish failure triage — 2026-05-14

**Scope:** all failed `publish_tasks` where `platform='Instagram'`, `status='failed'`, `testbench=false`, `created_at > now()-7d` (08.05–14.05).
**Total failed IG prod tasks in window:** 229.
**OpenProject ticket filed:** [#61 — рекламный баннер «Edits» перекрывает выбор видео](https://openproject.contenthunter.ru/work_packages/61) (type Ошибка, parent epic #49 «Выкладка баги»).

## Method

`error_code` on `publish_tasks` is unreliable — it records the *first* error (often a preflight noise event), not the terminal one. Failures were instead bucketed by the **last `type='error'` event's `meta.category`**, excluding post-failure cleanup noise (`screencast_pull_failed`, `screencast_stop_failed`, `device_artifacts_cleanup`). Screencasts (`screen_record_url` on S3) for the top buckets were pulled and frame-extracted with ffmpeg to confirm the visual failure mode.

## Ranked breakdown (terminal error category, 7 days)

| # | Terminal error | Tasks | % | Assessment |
|--:|---|--:|--:|---|
| 1 | `ig_share_tap_no_progress` | 40 | 17.5% | **Being fixed.** Spiked 12–13.05 (18+12), fix shipped 13.05 (`ig_share_ok` fallback, PR #49) → only 3 in last 24h. Covered by existing work. |
| 2 | `ig_gallery_no_video_candidate` | 40 | 17.5% | **Heterogeneous.** ~16 = Google Play foreground (this ticket), ~10 = empty Reels "Черновики" tab, ~11 = Reels editor/playback screen, ~3 blank. |
| 3 | `media_store_unreadable_pre_publish` | 32 | 14.0% | **Stale.** All on 08–09.05; this was the MediaStore outage already fixed. Zero since. |
| 4 | `ig_upload_confirmation_timeout` | 20 | 8.7% | **Stale.** All on 07–08.05. Not active. |
| 5 | `ig_picker_wrong_candidate` | 18 | 7.9% | **This ticket.** Entirely within last 72h, started 12.05. Edits banner covers thumbnails. |
| 6 | `ig_app_launch_failed` | 15 | 6.6% | Separate cause — device state (IG won't foreground). Spread thin across week. |
| 7 | `ig_target_not_in_picker` | 13 | 5.7% | Separate cause — account not bound to device / account-list parser picks up garbage ("устройстве." parsed as an account name). |
| 8 | `ig_editor_timeout` | 9 | 3.9% | Tail. |
| 9 | `ig_caption_fill_failed` | 9 | 3.9% | Tail. |
| 10 | `ig_camera_open_failed` | 9 | 3.9% | Tail. |
| — | `process_interrupted` | 8 | 3.5% | Task killed externally — not a publish-logic bug. |
| — | `(no real error event)` | 7 | 3.1% | Failed with no error event recorded. |
| — | `adb_device_not_ready` / `publish_failed_generic` | 3 / 3 | — | Tail. |
| — | `ig_gallery_button_not_found` / `media_store_pollution_pre_publish` / `critical_exception` | 1 / 1 / 1 | — | Tail. |

Activity check (last 24h / last 72h, for the live ones): `ig_share_tap_no_progress` 3/34 (dying off), `ig_picker_wrong_candidate` 4/18, `ig_gallery_no_video_candidate` 3/18, `ig_app_launch_failed` 3/11.

## Selected bug: Instagram "Edits" promo banner — ~34 failures/7d

`ig_picker_wrong_candidate` (18) and the Google-Play sub-mode of `ig_gallery_no_video_candidate` (16) share **one root cause**: a new Instagram bottom-sheet banner promoting the "Edits" app.

**Spread:** 34 tasks, 20 distinct devices, 27 accounts, 6 raspberries, 10.05 → 14.05 — systemic, not device-specific.

### Root cause (confirmed from screencasts)

Instagram now shows a bottom-sheet banner — *«Сделайте свои видео лучше с помощью Edits»* / *«Усовершенствуйте свои видео с помощью Edits»*, with a large purple **«Установить приложение»** button — that appears over the Reels media picker and editor. The publisher's IG flow does not dismiss it, producing two symptoms:

1. **Banner covers the picker thumbnails** → `ig_picker_wrong_candidate`. The banner overlays the bottom ~45% of the "Недавние" gallery grid. The publisher only sees the top row, selects the wrong clip; the date/MediaStore guard catches the mismatch and aborts (`date_mismatch`, `mediastore_top_mismatch`).
2. **Publisher taps the banner's "Установить приложение" button** → `ig_gallery_no_video_candidate`. The tap lands on the install button, Google Play opens to the "Edits" app page, Instagram drops to background. The subsequent gallery scan sees Play Store UI (the RC-8 `first_clickables` meta contains "отзыв", "скриншот N из 6", "возрастные ограничения" — Play Store controls) and fails "no video candidate".

### Screencast evidence

| Task | Mode | What the recording shows |
|---|---|---|
| 5031 | gallery → Play Store | picker (gallery visible) → Reels editor → **Edits banner** over preview → **Google Play "Edits: Видеомейкер"** page |
| 5026 | gallery → Play Store | picker → loading spinner → **Edits banner** with "Установить приложение" → Play Store ("TikTok Studio" page) |
| 5662 | banner over picker | Reels picker open, **Edits banner** covering bottom half of thumbnail grid; abort `mediastore_top_mismatch` (top-1 was the screen-recording file) |
| 5611 | banner over picker | same — **Edits banner** over picker; abort `date_mismatch` (thumbnail date 62s off expected push time) |

For contrast, the non-banner `ig_gallery_no_video_candidate` tasks (5318, 5286, 5281, 5348, 5183) end stuck on the empty "Черновики Reels" (Reels Drafts) tab — a *separate* navigation bug, deliberately left out of this ticket's scope.

### Suggested fix direction (not implemented in this session)

Extend the existing banner pre-dismissal mechanism in the IG publisher to recognise the "Edits" promo bottom-sheet (by its text anchors / the `Установить приложение` button) and dismiss it (swipe-down / close / tap-aside) **before** the gallery-select step — and never tap the install button.

## Not in scope here

- `ig_share_tap_no_progress` — already addressed (fix shipped 13.05).
- `ig_gallery_no_video_candidate` non-Play-Store modes (empty Drafts tab, editor screen) — separate navigation bug, candidate for a follow-up ticket.
- `ig_app_launch_failed`, `ig_target_not_in_picker` — separate root causes (device state; account binding / account-list parser).
