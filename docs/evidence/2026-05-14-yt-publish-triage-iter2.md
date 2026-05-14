# YouTube publish failures — triage 2026-05-14 (iter 2, full day)

**Scope:** all `publish_tasks` with `platform='YouTube'` and `status='failed'`, `created_at` on 2026-05-14 (UTC). Full-day snapshot taken ~14:45 UTC.
**Goal:** rank failure causes by volume, pick the top *remaining* actionable bug, open an OpenProject ticket.
**Relationship to iter 1:** the earlier same-day triage (`2026-05-14-yt-publish-triage.md`) ran ~10:30 UTC, saw 6 tasks, picked `yt_editor_upload_timeout`, and **shipped a fix** — OpenProject [#59](https://openproject.contenthunter.ru/work_packages/59), PR [GenGo2/delivery-contenthunter#56](https://github.com/GenGo2/delivery-contenthunter/pull/56), merged `348d495`. This iter covers the **whole day (12 tasks)** and confirms that fix is live.
**This iter's ticket:** [#66 — Выкладка (YouTube): аккаунт-пикер не находит аккаунт по имени канала → ложный «аккаунт не привязан к устройству»](https://openproject.contenthunter.ru/work_packages/66) (type Ошибка, parent Epic #49 «Выкладка баги»).
**Fix:** ✅ SHIPPED 2026-05-14 — PR [GenGo2/delivery-contenthunter#63](https://github.com/GenGo2/delivery-contenthunter/pull/63), squash-merge `6189cd6`, deployed to the prod tree via `git pull --ff-only` (no PM2 restart — `publisher.py` is a per-task subprocess). See [Fix](#fix--shipped-2026-05-14) below.

## Today's failed YT tasks (12 total)

| Task | Time UTC | Account | Phone | `error_code` (log) | Verdict after screencast review |
|---|---|---|---|---|---|
| 5592 | 05:11 | wellroomfresh | 10 | `yt_app_not_foregrounded` | **Foreground contention** — Samsung Calculator kept stealing focus; recovery taps even typed "7" into it |
| 5672 | 07:25 | DubaiHomes-est | 5 | `switch_failed_unspecified` | Device-side — `adb_device_not_ready` preflight fail, no screencast |
| 5685 | 07:45 | DubaiRealEstate-home | 5 | `yt_editor_upload_timeout` | ✅ class **fixed** by #59 / PR #56 |
| 5717 | 09:15 | Mystic_Aroma | 10 | `yt_editor_upload_timeout` | ✅ class **fixed** by #59 / PR #56 |
| 5718 | 09:15 | wellfresh_1 | 9 | `switch_failed_unspecified` | **Shorts-detector false-positive** — switcher *did* escape Shorts; detector counted recurring re-entries as one persistent trap |
| 5724 | 09:40 | miss_Arishka_aroma | 10 | `yt_editor_upload_timeout` | ✅ class **fixed** by #59 / PR #56 |
| 5739 | 10:35 | just_clickpay | 9 | `yt_accounts_btn_missing_postmortem` | **Foreground contention** — a TikTok publish session held the foreground; switcher dumped TikTok's UI (the "Опубликовать"/"Предпросмотр" postmortem texts are TikTok's), never saw "Аккаунты" |
| 5803 | 12:47 | RelisMeGirl | 2 | `process_interrupted` | Infra mass-kill — `KeyboardInterrupt`, no real work done |
| 5818 | 12:52 | relisme-n9s | 7 | `process_interrupted` | Infra mass-kill — `KeyboardInterrupt`, no real work done |
| 5850 | 12:57 | WowRelisme | 3 | `process_interrupted` | Infra mass-kill — clean linear progress to the upload screen, then SIGINT mid-step |
| 5854 | 13:05 | relisme-j6f | 7 | `yt_post_switch_app_not_foregrounded` | **Picker mis-tap** — switcher tapped "Добавить аккаунт ребенка" (the menu row below the target) → GMS child-account wizard opened. PR #56's new guard then correctly fast-failed |
| 5856 | 13:15 | relismee | 7 | *(none)* / `yt_picker_target_absent` | **Picker matcher bug** — target IS in the picker (channel "Relisme", 275 subs); matcher only checked gmail/handle, not the channel display name → false "account not bound to device" |

## Error frequency — today

### Raw `error_code` count (as the logs label it)

| `error_code` | Count |
|---|---:|
| `yt_editor_upload_timeout` | 3 |
| `process_interrupted` | 3 |
| `switch_failed_unspecified` | 2 |
| `yt_app_not_foregrounded` | 1 |
| `yt_accounts_btn_missing_postmortem` | 1 |
| `yt_post_switch_app_not_foregrounded` | 1 |
| *(none)* | 1 |

The raw count is misleading — `error_code` records the *first* error, not the real cause (known pitfall). Screencast review (mandatory per house practice — the real RC is often hidden) re-groups today's 12 as below.

### True root-cause grouping (after screencast review)

| Root cause | Tasks | Count | Actionable now? |
|---|---|---:|---|
| **YT account-picker selection** (5854 mis-tap, 5856 channel-name miss) | 5854, 5856 | **2** | ✅ **yes — chosen** |
| **Foreground contention** (foreign app holds the screen during/before the switch) | 5592, 5739 | 2 | partly — PR #56 covers the post-switch variant; pre-/mid-switch open |
| `yt_editor_upload_timeout` | 5685, 5717, 5724 | 3 | ✅ already fixed (#59 / PR #56) |
| `process_interrupted` (single infra mass-kill ~13:05 UTC) | 5803, 5818, 5850 | 3 | not a publish-flow bug — orchestration/infra |
| Shorts-detector false-positive | 5718 | 1 | open (lower volume) |
| Device-side `adb_device_not_ready` | 5672 | 1 | not a code bug |

**Why the two count-3 buckets are not the pick:**
- `yt_editor_upload_timeout` (3) — already fixed earlier today by the parallel session (#59 / PR #56). Task 5854 proves the fix is live: it shows the new `yt_post_switch_app_not_foregrounded` fast-fail code firing in prod.
- `process_interrupted` (3) — all three are `KeyboardInterrupt`; 5803 and 5818 were killed at the *exact same second* (13:05:27). That is one external event (a `server.js`/PM2 restart or deploy around 13:05 UTC) killing the publisher subprocesses — not three independent publish-flow bugs. 5850's screencast confirms: clean forward progress right up to the upload screen, then a frozen-but-valid frame. This belongs to orchestration/infra, not the publish flow.

So the largest **remaining, genuine, actionable publish-flow code-bug bucket today is the YT account-picker (2 tasks)** — and it has by far the strongest 7-day backing (below).

## 7-day context (created_at ≥ 2026-05-07)

The picker family is the single largest actionable YT failure category over the week:

| Category | Tasks (7d) |
|---|---:|
| `yt_target_not_in_picker_after_scroll` | 23 |
| `yt_picker_target_absent` | 4 |
| **picker family total** | **27** |

(iter 1's 7-day table also had `media_store_unreadable_pre_publish` at 30, but that class produced **zero** failures today — the 2026-05-09 MediaStore outage fix cleared it. And `yt_editor_upload_timeout`'s 14 is now addressed by #56.)

Not all 27 are the matcher bug — some accounts are genuinely not on the device (YT switcher gmail coverage is ~81%, 224/278). But task 5856 **proves the false-negative exists**: a fully working account, 275 subscribers, visible on screen the entire time, thrown away. How big the false-negative share is will only be known after the fix + re-measure.

## Chosen bug — YT account-picker matcher ignores channel display name

**Task 5856, @relismee, phone #7, 13:15 UTC.** Filed as OpenProject **[#66](https://openproject.contenthunter.ru/work_packages/66)**.

### Event chain
```
sa_preflight  known=boost_c,septic.solution,relismee,septicfixer   (no yt_gmail_hint event)
shorts_detected attempt=1
yt_picker_scrolled ×4
yt_picker_scroll_exhausted: rounds=5 stale=3
yt_picker_target_absent: target='relismee'
fail step=yt_4_pick_account reason="аккаунт 'relismee' не привязан к устройству"
```

### What the screencast + `picker_diag` prove
The account picker was open and fully on screen the whole time. `picker_diag` meta captured:
```
gmail   : null
handles : []
displays: ["Добавить аккаунт",
           "Вы выбрали аккаунт septicfixer,@septicfixer,Нет подписчиков",
           "Параметры канала ...",
           "septic.solution ,,Нет подписчиков",
           "Relisme,,275 подписчиков",        ← THIS is target 'relismee'
           "BoosterCap,,18 подписчиков",
           "Francisco Trainer,,128 подписчиков", ...]
```
The target `relismee` is the channel **"Relisme"** (same magenta RELISMEE avatar, 275 subs). The parser saw it. The matcher didn't connect `relismee` ↔ `Relisme` (trailing "e" + casing). The 5 scroll rounds were pointless — the whole list fit on screen; "Relisme" was visible in every scroll position.

### Where it is in the code
`account_switcher.py`, `_find_and_tap_account` (~line 3939):
- The YT gmail-hint fast path (`find_yt_row_by_gmail`, the `[FIX 2026-04-24 yt-gmail-picker-match]` block) only fires when `self._yt_target_gmail` is set. `relismee` has no gmail backfilled (`factory_inst_accounts.gmail`) — it's in the uncovered ~19% — so this path is skipped entirely.
- Fallback `find_account_in_list(elements, target)` is handle/username-oriented and does not match `target` against the YT **channel display name** shown for *inactive* picker rows (`"<ChannelName>,,<subs>"` — no `@handle` for non-active accounts).
- When the dump is usable and the target isn't matched, it `FAIL`s immediately with no vision fallback (deliberately, to avoid false-positives on similar names) — so the false negative is terminal.

`_sample_picker_diag` (~line 258) is the snapshot collector.

### Fix — ✅ SHIPPED 2026-05-14

PR [GenGo2/delivery-contenthunter#63](https://github.com/GenGo2/delivery-contenthunter/pull/63) · squash-merge `6189cd6` · deployed to the prod tree (`/root/.openclaw/workspace-genri/autowarm/`) via `git pull --ff-only`. No PM2 restart — `publisher.py` is `spawn`'d as a fresh subprocess per task, so `account_switcher.py` is re-imported on the next publish.

**Change** — `account_switcher.py`:
- New pure helper `_alnum_norm` (casefold + strip non-alphanumerics, Unicode-aware so Cyrillic survives) and pure function `find_yt_channel_name_matches(elements, target)`. Conservative match rule: `_alnum_norm` equality **or** one normalised string is a prefix of the other with length-delta exactly 1 (the observed `relisme`/`relismee` handle-uniquification pattern), `min(len) >= 4`. Returns **all** matching rows.
- Wired into `_find_and_tap_account` between the handle-match and the terminal-FAIL: **exactly one match → tap + log `yt_channel_name_match`**; **2+ matches → `return False` + log `yt_channel_name_ambiguous`** — never guesses (a single picker can hold both `relisme` and `RelismeWear`, so a loose match would risk publishing to the wrong channel).

**Tests** — 12 new cases in `tests/test_switcher_youtube.py` (TDD), including a regression built from the real task-5856 picker dump and an active-row no-false-match guard. Full YT/switcher suites green; the broad sweep's 8 failures all confirmed identical on a clean `origin/main` checkout → **0 regressions**. Plan codex-reviewed (2 rounds, clean); spec + code-quality + final-implementation review via subagents.

**Out of scope (separate follow-ups):** the `factory_inst_accounts.gmail` backfill for the uncovered ~19%; the 11/27 weekly failures where the gmail *is* in the DB but the task still fails; genuinely-absent accounts. The conservative match rule + ambiguity guard protect those from false matches.

### 24–48h verify

Watch for `yt_channel_name_match` events appearing in `publish_tasks.events`, and the gmail-empty subset of the `yt_target_not_in_picker_after_scroll` / `yt_picker_target_absent` rate (27/7d before the fix) dropping. Frequent `yt_channel_name_ambiguous` would signal the gmail-backfill follow-up is worth prioritising.

## Related findings (logged, not chosen)

- **5854 — picker mis-tap.** Same component (`yt_4_pick_account`), different mechanism: the switcher tapped "Добавить аккаунт ребенка" (the static menu row below the account list) instead of the target email, launching the GMS child-account wizard. PR #56's post-switch foreground guard then correctly fast-failed (`yt_post_switch_app_not_foregrounded`) — good defence-in-depth, but the upstream mis-tap is the real bug. Worth folding into the #66 effort or a sibling ticket.
- **5592 / 5739 — foreground contention.** A foreign app (Samsung Calculator; an active TikTok publish session) holds the screen while the YT publisher operates blind against the wrong app's UI. Structurally the same family PR #56 addressed for the *post-switch* point; here it's the *pre-switch* guard (5592, gives up after 2 retries) and *mid-switch* (5739, no guard). 5739's TikTok session also raises a possible per-device concurrency question — separate investigation.
- **5718 — Shorts-detector false-positive.** The switcher escaped Shorts repeatedly, but YT auto-returned to Shorts surfaces (cold-launch lands in Shorts; back-nav from edit screens drops into Shorts). The detector counts recurring re-entries within ~22s as one persistent trap and aborts after 3. `switch_failed_unspecified` masks a partially-successful switch.
- **process_interrupted ×3** — recommend a quick infra check of what restarted around 13:05 UTC, and whether interrupted tasks re-queue cleanly.

## Evidence pointers

- Screencasts: `screen_record_url` on `publish_tasks` 5592 / 5718 / 5739 / 5850 / 5854 / 5856 (5672/5803/5818 have none). Mirrored to `/tmp/yt_triage_0514b/rec_<id>.mp4`, frames in `/tmp/yt_triage_0514b/f<id>/` (ephemeral).
- DB: `publish_tasks.events` JSONB — group by last `events[].meta.category` where `type='error'`; `yt_picker_target_absent` events carry a `picker_diag` snapshot in `meta`.
- Code: `account_switcher.py` `_find_and_tap_account` (~3939), `_sample_picker_diag` (~258).
