# YouTube publish failures — triage 2026-05-14

**Scope:** all `publish_tasks` with `platform='YouTube'` and `status='failed'` created on 2026-05-14 (UTC).
**Goal:** rank failure causes by volume, pick the top one, open an OpenProject bug.
**OpenProject ticket:** [#59 — Выкладка (YouTube: после переключения аккаунта публикация уходит в 5-минутный таймаут yt_editor_upload_timeout)](https://openproject.contenthunter.ru/work_packages/59) (type Ошибка, parent Epic #49 «Выкладка баги»).
**Fix:** PR [GenGo2/delivery-contenthunter#56](https://github.com/GenGo2/delivery-contenthunter/pull/56) — branch `fix/yt-post-switch-foreground-guard`, commit `59e0a61`. Status: open, awaiting review/merge. See [Fix](#fix) below.

## Today's failed YT tasks (6 total)

| Task | Account | Project | Phone | Final error (last error-event category) | Real root signature |
|---|---|---|---|---|---|
| 5685 | DubaiRealEstate-home | Ambassadori_112 | 5 | `yt_editor_upload_timeout` | post-switch handle unknown → editor flow runs blind |
| 5717 | Mystic_Aroma | Парфюмерия_21 | 10 | `yt_editor_upload_timeout` | post-switch handle unknown → editor flow runs blind |
| 5724 | miss_Arishka_aroma | Парфюмерия_31 | 10 | `yt_editor_upload_timeout` | post-switch handle unknown → editor flow runs blind |
| 5592 | wellroomfresh | Forsal_11 | 10 | `publish_failed_generic` | `yt_app_not_foregrounded: failed after 2 retries` — focus stuck on `com.sec.android.app.*` |
| 5718 | wellfresh_1 | Forsal_154 | 9 | `publish_failed_generic` | `yt_1_shorts_trap` — YT stuck in Shorts player, 3 back-taps didn't help |
| 5672 | DubaiHomes-est | Ambassadori_114 | 5 | `adb_device_not_ready` | ADB preflight failed, no screencast — device-side, not a code bug |

### Error frequency (today)

| Cause | Count | Share |
|---|---:|---:|
| **`yt_editor_upload_timeout` (post-switch handle unknown → blind editor)** | **3** | **50%** |
| `yt_app_not_foregrounded` | 1 | 17% |
| `yt_1_shorts_trap` (stuck in Shorts player) | 1 | 17% |
| `adb_device_not_ready` (device-side) | 1 | 17% |

`yt_editor_upload_timeout` is the single largest cause of YouTube publish failures today (3/6).

## 7-day context (created_at ≥ 2026-05-08)

YT failures by last error-event category:

| Category | Fails (7d) |
|---|---:|
| `media_store_unreadable_pre_publish` | 30 |
| `yt_target_not_in_picker_after_scroll` | 17 |
| **`yt_editor_upload_timeout`** | **14** |
| `process_interrupted` | 13 |
| (none) | 7 |
| `yt_accounts_btn_missing` | 6 |
| `publish_failed_generic` | 5 |
| `adb_device_not_ready` | 3 |
| `screencast_stop_failed` | 2 |

`yt_editor_upload_timeout` is #3 over the week — a persistent, high-volume pattern, not a one-day blip.

**Correlation:** of 15 tasks with a `yt_editor_upload_timeout` error event in the last 7 days, **14 are preceded by a `yt_post_switch_handle_unknown` warning** (the 15th has `yt_editor_stuck_detected` instead). The chain is ~93% consistent.

## Root cause (the chosen bug)

All three of today's `yt_editor_upload_timeout` tasks share an identical event chain:

```
yt_post_switch_handle_unknown (warning)
  → yt_editor_diag × ~15  (polling editor fields for ~5 min)
  → yt_editor_stuck_detected
  → yt_title_fill_failed
  → yt_desc_field_not_found
  → ai_unstuck_action × 2 → ai_unstuck_anti_loop
  → yt_editor_upload_timeout (error)  "редактор timeout — Загрузить не найдено"
  → watchdog_fired
```

### Screencast review

The screencasts prove YouTube is **not in the foreground** during the entire "editor" phase:

- **5685** — Google Voice Search overlay ("Голос/Трек", "Говорите…", "Не удалось распознать запрос").
- **5717** — Samsung app drawer / home screen the whole time, then a blank loading spinner.
- **5724** — editor briefly opens ("Добавьте информацию" + spinner, never loads), then a Facebook "Обновите приложение Facebook" prompt, then the home screen.

The editor flow keeps polling `yt_editor_diag` against whatever app happens to be foregrounded, AI-unstuck flails, anti-loop trips, and the run finally times out because the "Загрузить" button is never found — it can't be, YouTube isn't there.

### Where it is in the code

`account_switcher.py`:

- **`_post_switch_verify_handle`** returns `'unknown'` when it can't read the `@username` off the profile header (sparse dump). Its docstring (`account_switcher.py:3917-3924`) deliberately tells callers to treat `'unknown'` as **degrade-to-pass, NOT retry** — to avoid infinite loops on a consistently broken dump.
- **`_select_youtube`** loop (`account_switcher.py:2971-2983`): on `'unknown'` it logs `yt_post_switch_handle_unknown` and `break`s — then falls straight through to `_tap_plus_and_verify(...)` at `account_switcher.py:3010` as if the switch succeeded.
- **`_tap_plus_and_verify`** (`account_switcher.py:3897-3905`): if **none** of the editor `verify_triggers` are on screen, it logs `"no expected triggers — continuing (FLAG_SECURE/unknown layout)"` and **still `return self._ok(...)`**.

Neither degrade-to-pass gate checks the foreground package. The "sparse dump" they tolerate is, in these failures, caused by YouTube not being foregrounded at all (home screen / voice search / Facebook / Shorts trap). A foreground-package check (`_detect_foreground_pkg()` already exists at `account_switcher.py:3017`) at either gate would convert a silent 5-minute timeout into a fast, correctly-attributed failure — or hand off to the existing `_yt_ensure_foreground` recovery.

## Evidence pointers

- Screencasts: `screen_record_url` on `publish_tasks` 5685 / 5717 / 5724.
- Frames extracted to `/tmp/yt_triage_0514/frames_<id>/` during triage (ephemeral).
- DB: `publish_tasks.events` JSONB — group by last `events[].meta.category` where `type='error'`.

## Fix

**PR:** [GenGo2/delivery-contenthunter#56](https://github.com/GenGo2/delivery-contenthunter/pull/56) · branch `fix/yt-post-switch-foreground-guard` · commit `59e0a61` · base `f21ee7b`.

**Change** — `account_switcher.py`, `_switch_youtube` post-switch loop, the `status == 'unknown'` branch:

Before, `'unknown'` from `_post_switch_verify_handle` was unconditionally degrade-to-pass (`break` → `_tap_plus_and_verify` → `_ok()`). Now the degrade-to-pass is gated on a foreground-package check via `_detect_foreground_pkg()` (already in the file):

- **Foreign app positively detected in foreground** → `return self._fail(...)` with `error_code = yt_post_switch_app_not_foregrounded`. Converts the silent ~5-min editor-poll timeout into a fast, correctly-attributed failure that frees the device and re-queues cleanly.
- **YouTube foregrounded, or package undetectable** → conservative degrade-to-pass preserved unchanged — no behaviour change for the FLAG_SECURE / sparse-dump-on-the-right-screen case the original code was protecting.

`_post_switch_verify_handle` docstring updated to match the new caller contract.

**Tests** — 3 new cases in `tests/test_yt_post_switch_verify.py` (TDD: foreign-fg case went RED → GREEN; the other two lock in the conservative edges):

| Test | Scenario | Expected |
|---|---|---|
| `..._unknown_with_foreign_foreground_fails` | dump unreadable + foreign app fg | fail fast, never reaches editor flow |
| `..._unknown_with_yt_foreground_degrades_to_pass` | dump unreadable + YT fg | degrade-to-pass preserved |
| `..._unknown_with_undetectable_foreground_degrades_to_pass` | dump unreadable + fg undetectable | degrade-to-pass preserved |

`test_yt_post_switch_verify.py` 9/9 · `account_switcher` suite 83/83 · broad YT/switcher sweep 296 passed. One pre-existing unrelated failure — `test_switcher_read_only.py::test_yt_happy_path_returns_accounts` (read-only `read_accounts_list` path) — confirmed failing on clean baseline `f21ee7b`, not a regression of this change. Codex review: clean, no P1.

**Open follow-up** — after merge + prod deploy, run a 24h check that `yt_editor_upload_timeout` failures preceded by `yt_post_switch_handle_unknown` drop, replaced by fast `yt_post_switch_app_not_foregrounded`. This fix makes the failure *fast and correctly-labelled*; it does not by itself recover the publish — if the device-state cause (YT not foregrounded after switch) is frequent enough, a follow-up recovery step (`_yt_ensure_foreground` re-entry) may be worth it.
