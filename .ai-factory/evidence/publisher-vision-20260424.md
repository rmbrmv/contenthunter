# Publisher vision pipeline — evidence (2026-04-24)

**Plan:** `.ai-factory/plans/publisher-vision-screencast-analysis-20260424.md`
**Branch:** `testbench` (GenGo2/delivery-contenthunter)
**Phase 1 commit:** `8eae73c` — feat(vision): perceptual-dedup screencast analyzer + S3 + DB column
**Phase 2 commit:** `d1a27c8` — feat(publisher): vision inline-recovery + post-mortem + success audit
**Phase 3 commit:** `cd53c00` — fix(publisher): IG draft-continuation, YT settings-activity fallback, TT fg-check diagnostic
**Phase 4 commit:** `0759762` — test+docs: vision tests, dashboard badge

## Сводка тройки 922/923/924 (исходный диагноз)

| # | Платформа | error_code | Корень |
|---|---|---|---|
| 922 | Instagram | `ig_camera_open_failed` | switcher дошёл до `ig_6_type_sheet`, потом publisher застрял в `ig_stuck_on_profile` loop. Screencast: модалка «Продолжить редактирование черновика» поверх камеры (известный pending в memory) |
| 923 | TikTok | `tt_fg_drift_unrecoverable` | foreground = `com.sec.android.app.launcher` 3 раза подряд. Screencast: TikTok РЕАЛЬНО открыт (false-negative dumpsys-чека) |
| 924 | YouTube | `yt_accounts_btn_missing` | postmortem dump показывает headers feed-карточек («Воспроизвести видео», «Перейти на канал RUSTAMJON TV»), profile-tab tap не открыл profile. Тот же баг что в `project_revision_phone171_backlog` |

## Архитектура pipeline (deployed)

```
publisher.py (run_publish_task)
├── inline-recovery точки [T5 commit d1a27c8]:
│   ├── publish_instagram_reel @ ig_stuck_on_profile (publisher.py:3119)
│   ├── _switch_youtube @ yt_accounts_btn_missing_postmortem (account_switcher.py:1908)
│   └── _switch_tiktok @ tt_fg_drift_unrecoverable (account_switcher.py:1464)
│       → publisher_vision_recovery.attempt_vision_recovery(...)
│         (screencap → analyze_screencast(mode='inline') → tap/keycode/swipe)
│
├── фиксы [Phase 3 commit cd53c00]:
│   ├── T8 IG: _is_ig_draft_continuation + tap «Начать новое видео» (publisher.py)
│   ├── T9 YT: _yt_open_via_settings_activity (am start Shell_SettingsActivity → «Аккаунт» → «Смена…»)
│   └── T10 TT: _probe_fg_sources_diagnostic (топ + focus + recents) на streak>=2
│
└── finally (status='completed' OR 'failed'):
    ├── stop_and_upload_screen_record() → S3 (.mp4)
    ├── _dump_testbench_fixture() → /home/claude-user/testbench-fixtures/
    ├── if failed: triage_classifier.process_failed_task() [Phase 1+2]
    │   └── _run_vision_postmortem() → ffmpeg+phash → analyze_screencast(mode='postmortem')
    │       → upload_vision_artifacts() → publish_tasks.vision_analysis_url
    │       → agent_diagnose читает vision_report.md и вставляет в prompt
    └── if completed: triage_classifier.spawn_success_audit() [Phase 2]
        └── async thread (cap inflight=2, daily cap из system_flags) →
            run_success_audit() → если silent_regression → INSERT publish_investigations
```

## Smoke-результаты при разработке

**T2 (perceptual-hash dedup):** на скринкасте задачи 922 (250 сек):
- raw frames: 7490 (30 FPS × 250 сек)
- unique после phash dedup (threshold=8): 132
- ratio: 1.8% (динамика сохранена, статика отброшена)
- elapsed: 103 сек (ffmpeg + phash)

**T3 (S3 upload):** 3 frames + report + manifest за 1.2 сек. Public URL `https://save.gengo.io/autowarm/vision_frames/instagram/task999999/manifest.json` отдаётся `HTTP/2 200`, корректный JSON.

**T6 (fetch_vision_report):** `agent_diagnose.fetch_vision_report` корректно подкачивает 79 знаков прошлого smoke-отчёта из S3.

**T7 (success-audit cap):** 3 спавна одновременно → ровно 2 приняты (inflight cap), 3-й skipped. Корректно.

**T11 (тесты):** 42 новых unit-теста добавлены в `tests/test_vision_analyzer.py` + `tests/test_publisher_vision_fixes.py`. Все 42 passed.

## Pytest baseline и регрессия

**До работ (на коммите `f9e9a04`):**
- 11 fail (pre-existing — НЕ моя работа): 4 × `test_publish_guard.py` (DB schema после DROP `account_packages`), 5 × `test_testbench_orchestrator.py` (round-robin DB), 1 × `test_switcher_read_only.py` (читает prod state).
- 262 pass / 3 skipped.

**После всех 4 фаз:**
- 11 fail (тот же baseline) / **304 pass** (+42 за счёт T11) / 3 skipped.
- **Регрессий 0.**

## Известные limits + риски

1. **OAuth rate limits для Sonnet 4.6.** Текущий `sk-ant-oat01-...` может ограничивать ~5-10 RPM на vision-эндпоинте. Mitigation: cap 1 inline-recovery per stuck + `system_flags.vision_success_audit_daily_cap` (default 50). Если упрёмся — выписать `sk-ant-api03-...` из console.anthropic.com.
2. **Cost monitoring.** Все vision-вызовы пишутся в `agent_runs` с `agent='vision_*'`. Запрос `SELECT SUM(cost_usd) FROM agent_runs WHERE agent LIKE 'vision_%' AND finished_at >= NOW() - INTERVAL '24h'` даст daily spend. Auto-pause: env `VISION_RECOVERY_DISABLE=1` + `VISION_SUCCESS_AUDIT_DISABLE=1`.
3. **TT fg-check root cause** (T10): шаг A (diagnostic) собирает evidence. Через несколько production-инцидентов будет видно какой источник (`topResumedActivity` vs `mCurrentFocus` vs `recents`) даёт правду — отдельным фиксом переключим primary.
4. **Inline-recovery latency.** +5-10 сек на каждый stuck-инцидент. Для testbench (cadence 10 мин) приемлемо.
5. **Files API.** Не работает с OAuth (404 на `x-api-key` и `Bearer`) + не поддерживает .mp4 ни одним типом ключа. Frames через image content blocks (base64 JPEG) — единственный путь.

## Deploy путь (T13)

1. ✅ pytest зелёный (=304 pass, baseline 11 fail)
2. ✅ atomic commits (4 шт):
   - Phase 1: `8eae73c` (vision_analyzer + migration)
   - Phase 2: `d1a27c8` (publisher integration)
   - Phase 3: `cd53c00` (T8/T9/T10 фиксы)
   - Phase 4: `0759762` (tests + dashboard)
3. ✅ push в `origin/testbench` → авто-mirror в GenGo2/delivery-contenthunter (memory `reference_autowarm_git_hook.md`)
4. **НЕ в prod `main`** без ручного merge (memory `project_publish_testbench.md`)
5. После merge testbench → `pm2 describe autowarm-testbench | grep "exec cwd"` (memory `feedback_pm2_dump_path_drift.md`) → `pm2 restart autowarm-testbench`

## Файлы изменены (для review)

```
NEW vision_analyzer.py                                         (~520 lines)
NEW publisher_vision_recovery.py                               (~140 lines)
NEW migrations/20260424_publish_tasks_vision_analysis.sql      (~20 lines)
NEW migrations/20260424_publish_tasks_vision_analysis__rollback.sql
NEW tests/test_vision_analyzer.py                              (~280 lines, 32 tests)
NEW tests/test_publisher_vision_fixes.py                       (~110 lines, 10 tests)

MOD publisher.py                  +~100 lines (T5 hook, T7 spawn, T8 detector+handler)
MOD account_switcher.py           +~150 lines (T5 hook YT+TT, T9 _yt_open_via_settings, T10 _probe_fg_sources)
MOD triage_classifier.py          +~250 lines (_run_vision_postmortem, spawn_success_audit, run_success_audit)
MOD agent_diagnose.py             +~30 lines (fetch_vision_report + раздел в build_user_prompt)
MOD server.js                     +~2 lines (SELECT vision_analysis_url, vision_mode)
MOD public/testbench.html         +~3 lines (column «Vision»)
```

## Memory updates (T13)

- `project_publish_testbench.md` — раздел «Vision pipeline (2026-04-24)» с описанием 3 точек вызова. Closed Pending: «IG draft-continuation», «YT bottom-nav».
- `feedback_ui_automation_edge_cases.md` — запись «vision-fallback при стуке UI-автоматики».
- (TBD if newly discovered — `feedback_*` про OAuth rate limits на Sonnet 4.6 vision, если упрёмся в production).
