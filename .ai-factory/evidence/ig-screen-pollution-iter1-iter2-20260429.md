# Evidence: IG screen-pollution cleanup + recents-recovery + iter 2 stuck-detection

**Date:** 2026-04-29 (EOD)
**Triggered by:** bug-report `2026-04-29T182116Z-Danil_Pavlov_123-ig-телефон-19-алгори.md` + voice transcript
**Plan:** `.ai-factory/plans/ig-screen-pollution-cleanup-recents-recovery-20260429.md`
**Branches → main:**
- `c4ab6b1` fix(yt-switch): hardened sbrowser cleanup + ai_find_tap silent-fail logging
- `603d7ed` fix(ig+yt+tt): clean stale device artifacts + nuclear recents-recovery (L1+L2)
- `a7c9575` fix(ig-switch): detect stuck-on-editor + recents-recovery before flow (iter 2)

## Original signal

Phone 19 IG batch 1664-1673 (после ручного логаута третьей блок-учётки):
- 1664 makiavelli485 → `ig_wrong_camera_mode` (прошёл picker через fast-path)
- 1665-1673 → `ig_target_not_in_picker` × 9, picker visible items = `['миниат.юра', '28', '2026', 'г.', '27', '25']` (parser noise from screenshots)

User's voice transcript (Whisper):
1. *«нам после того как задача упала... надо удалять с телефона... иначе они забивают память и мешают работе»*
2. *«когда телефон/любое приложение подвисает — три полоски → закрыть все → начинаем сначала»*

## Layer 1 — `_cleanup_device_artifacts(scope)`

`publisher_base.py` (~+98 lines). Whitelist:
```
/sdcard/proof_ig_*.png, proof_tt_*.png, proof_yt_*.png
/sdcard/screen.png
/sdcard/comment_screen.png
/sdcard/unstuck_init.png
/sdcard/gmail_proof_final.png
/sdcard/canary_*.txt
+ (post_task) /sdcard/DCIM/autowarm_<filename>.mp4 (только если remote_media_path задан)
```

**Sources of pollution** (grep по autowarm/):
- `register_social.py:89,102,115` → `proof_ig/tt/yt_*.png`
- `account_factory.py:2492` → `gmail_proof_final.png`
- `warmer.py:341,1590,1966` → `unstuck_init.png`, `screen.png`, `comment_screen.png`
- `publisher_base.py:2364` → `DCIM/autowarm_*.mp4` (после publish остаётся)

`/sdcard/debug_screenshots/` уже защищён `.nomedia` — не трогается.

**Wire:**
- `push_media_to_device` начало (pre-adb_push) — защита от тасков, упавших без post_task cleanup
- `run()` finally после `stop_and_upload_screen_record` (post_task) — chain'ed cleanup

## Layer 2 — `_force_clean_restart_via_recents(target_pkg, activity, step_name)`

`publisher_base.py` (~+135 lines). Universal nuclear-recovery:
1. KEYCODE_APP_SWITCH (187) → recent-apps overlay
2. `dump_ui` → найти `<node clickable=true>` с content-desc/text/resource-id ∈ {`Закрыть все`, `Close all`, `Очистить все`, `Clear all`, `clearAll`, `close_all_button`, `dismiss_all`} → tap center
3. Если кнопка не найдена — blind tap (540, 1900) + warn event `recents_close_all_blind_tap`
4. `am start -n target_pkg/activity`
5. `dumpsys activity` verify foreground == target_pkg
6. log_event `recents_close_all_recovery` с meta {step, before_fg, after_fg, mode, button_resolved, ok}

**Wire-points (один из трёх запускает):**
- `publisher_instagram._open_instagram_camera` финальный fallback (после `ESCALATION_CAP` soft-restart'ов)
- `account_switcher._ensure_foreground` финальная ступень (YT/TT/IG)
- `account_switcher._switch_instagram` после `_open_app` если `_ig_is_on_unexpected_screen` True (iter 2)

**Anti-loop guard:** `_recents_recovery_attempted` (per-switcher-instance) + `_ig_recents_recovery_attempted` (per-publish-task) — recovery строго один раз.

## Iter 2 — `_ig_is_on_unexpected_screen(xml)` detection

Smoke 1710-1712 показал: после `ig_editor_timeout` IG остаётся foreground но застревает на share/editor screen. Все subsequent dumps возвращают **тот же editor-XML** (1711: 7 ui_dumps подряд по 30637 bytes). `_ensure_foreground` считает IG foreground'ным (pkg matches), не проверяет на каком экране.

**Detection markers** (`_IG_EDITOR_RESOURCE_IDS` в account_switcher.py):
```
caption_input_text_view, share_button_container, share_button,
cover_photo_preview, metadata_location_row, map_content_education,
caption_add_on_recyclerview, clip_thumbnail_layout, clip_thumbnail_image
```

Whitelist: `account_switcher_recycler`, `bottom_sheet_container` (это нужный picker, не stuck).

**Wire:** `_switch_instagram` сразу после `_open_app` — dump UI, check helper, if stuck → log_event `ig_stuck_on_editor_detected` → `_force_clean_restart_via_recents` → re-`_open_app`.

## Smoke results (phone 19, RF8YA0W57EP)

### L1+L2 deploy (commit 603d7ed, restart 19:09)

| Task | Account | Status | Cleanup fired | Picker noise |
|---|---|---|---|---|
| 1710 | makiavelli485 | `ig_editor_timeout` (past picker) | ✅ pre+post | (n/a, fast-path) |
| 1711 | inakent06 | `ig_target_not_in_picker` | ✅ pre+post | `['хэштеги...','карте.','ии.']` (3 items, **не из screenshots**) |
| 1712 | makiavelli485 | `ig_target_not_in_picker` | ✅ pre+post | same as 1711 |

**L1 эффект подтверждён:** picker noise снизился с 6 items (1665) до 3 items (1711). Оставшийся шум — IG share-screen text (`caption_input_text_view`, `metadata_location_row`), не наши proof-png'и.

### Iter 2 deploy (commit a7c9575, restart 19:45)

| Task | Account | Status | `ig_stuck_on_editor_detected` | `recents_close_all_recovery` ok? |
|---|---|---|---|---|
| 1713 | inakent06 | `ig_target_not_in_picker` | ✅ fired | ❌ ok=False (before/after fg empty) |
| 1714 | makiavelli485 | `ig_target_not_in_picker` | ✅ fired | ❌ ok=False (same) |

**Detection works**, но recovery не решает проблему — `before_fg=''` и `after_fg=''` (dumpsys empty), blind (540, 1900) не закрывает apps на Samsung A17 / One UI 6+.

## Known limitations / next-session backlog

1. **Recovery `ok=False` на phone 19** — `dumpsys activity activities | grep` возвращает пустую строку через `self.adb()`. Гипотезы:
   - `shell` prefix не нужен в `adb -H host -P port -s serial`-mode (ADB-server)
   - stderr/stdout merging — output попадает в stderr, не в stdout
   - exit code != 0 → `adb()` возвращает `''`
   **Action:** ручная проверка `adb -H 82.115.54.26 -P 15068 -s RF8YA0W57EP shell dumpsys activity activities | grep -m1 -E 'topResumedActivity|ResumedActivity'`

2. **Recents-overlay button discovery** — blind (540, 1900) на Samsung A17 не находит «Закрыть все». На One UI 6+ кнопка может быть переименована в «Очистить» или иметь resource-id отличный от `clearAll`.
   **Action:** KEYCODE_APP_SWITCH вручную → screencap + dump_ui → собрать ground-truth XML → обновить selectors.

3. **«After recovery» feed verification** — recovery возвращает True по pkg-match (`com.instagram.android` in foreground), но IG может быть на splash screen / loading. Нужно ждать `feed_recycler_view` или `main_tab_bar` в dump перед продолжением switch-flow.

4. **Phone 171 DB-vs-device mismatch** — `factory_inst_accounts` active=t для ivana.world.class/born.trip90, но picker phone 171 показал ['jennymahalo','starly','kavkaz','jenny','content','creator','just','celebrating','someone','23.','12'] (10 чужих handles). DB factory_inst_accounts.gmail для phone 171 IG account'ов не synced с device state.

## Tests added (full sweep 116 passed на затронутых модулях)

| File | Cases |
|---|---|
| `tests/test_device_artifacts_cleanup.py` | 12 (pre_push/post_task scopes, whitelists, swallow errors, MEDIA_SCAN, log_event) |
| `tests/test_recents_close_all_recovery.py` | 5 (button-by-content-desc / by-resource-id / blind-tap / fg-verify-fail / log-meta) |
| `tests/test_ig_stuck_on_editor_detection.py` | 7 (positive editor markers / negative feed/profile/picker/empty) |
| `tests/test_overlay_dismiss.py` | refresh: безусловный force-stop sbrowser + persistence-warning |
| `tests/test_switcher_youtube.py` | `_returns_true_when_recents_recovery_succeeds` + updated contract |

Pre-existing failures на main (НЕ от наших правок): `test_publish_guard.py`, `test_testbench_orchestrator.py`, `test_publisher_ig_camera_recovery::reopen_via_home_taps_plus_then_reels`, `test_switcher_read_only::yt_happy_path`. На main без наших коммитов — те же 7 failures.
