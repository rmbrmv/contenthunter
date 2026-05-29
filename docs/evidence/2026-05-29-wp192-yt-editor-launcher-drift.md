# WP#192 — YT editor recovery при дрейфе foreground на launcher (SHIPPED+DEPLOYED 2026-05-29)

## Контекст
Триаж YT-фейлов 29.05 (`2026-05-29-yt-fails-triage.md`): из 12 фейлов 3 = `yt_editor_not_reached`
на 3 разных аккаунтах/устройствах (SpbProperty1Guide, bodyrelieflab_1, estate-z5i).

## Root cause
Во всех трёх в момент `_verify_yt_editor_reached` `top_activity =
com.sec.android.app.launcher/.activities.LauncherActivity`, `edit_fields_count=0`.

Трасса (publisher_youtube.py `publish_youtube_short`, direct_upload path):
1. `Shell_UploadActivity` стартует с SEND-интентом → topResumedActivity кратко = youtube
   → `direct_upload=True`.
2. `time.sleep(5)` + 4-шаговый dialog-dismiss loop.
3. За это время YouTube уходит в фон, на foreground всплывает Samsung launcher.
4. `_verify_yt_editor_reached` (3 итерации, ~6с) видит launcher, не находит editor →
   `yt_editor_not_reached` → `return False` (fail-fast, **без восстановления**).

Прекурсор `yt_post_switch_handle_unknown` (2/3) + `yt_foreign_foreground_probe_failed`
(probe foreign-foreground гарда WP#74 не сработал — не распознал launcher как foreign).

## Фикс
`_yt_recover_editor_from_launcher_drift(remote_media_path, prev_meta)`:
- если editor не достигнут И YouTube НЕ на foreground (fresh-probe topResumedActivity,
  fallback prev_meta.top_activity) → один `_yt_restart_upload_activity` (зеркало
  desc-trap-recovery WP#117) + дисмисс начальных диалогов + повторный `_verify_yt_editor_reached`;
- если YouTube уже на foreground → не launcher-drift, fail-fast как раньше.

Интеграция в `publish_youtube_short`: после первого fail `_verify_yt_editor_reached` —
один вызов recovery перед `return False`.

Kill-switch `YT_EDITOR_LAUNCHER_DRIFT_RECOVERY_ENABLED` (default ON). Новые события:
`yt_editor_launcher_drift_detected` / `_recovered` / `_unrecovered`.

## Качество
- 6 unit-тестов (`tests/test_yt_editor_launcher_drift_recovery.py`) — GREEN.
- 0 регрессий: 81 passed в YT/editor/switcher/foreign-foreground/state-normalize наборах;
  2 фейла `test_publisher_intermediate_probes.py` (IG camera/about-account) — pre-existing
  на чистом main `b1ee6d2`, не связаны.
- codex review — 0 findings.

## Деплой
- PR `GenGo2/delivery-contenthunter#125` squash-merged → main.
- Прод `/root/.openclaw/workspace-genri/autowarm` ff-pull → `a37f299`.
- Python (publisher_youtube.py) спавнится per-task из server.js → PM2-restart не нужен.

## Verify
Утренняя пачка 30.05: ожидаем `yt_editor_launcher_drift_recovered` события и спад
`yt_editor_not_reached`. Rollback: `YT_EDITOR_LAUNCHER_DRIFT_RECOVERY_ENABLED=0`.
