# Publisher vision pipeline + 3 точечных фикса (922/923/924)

**Создано:** 2026-04-24
**Ветка:** `feature/farming-testbench-phone171` (текущая, отдельную ветку под этот план не создавали — план-документ, не блокирует параллельные сессии)
**Triage origin:** publish_tasks 922 (IG / `ig_camera_open_failed`), 923 (TT / `tt_fg_drift_unrecoverable`), 924 (YT / `yt_accounts_btn_missing`) — все упали 2026-04-24 на phone #19.

## Settings

- **Testing:** yes (verbose unit + integration)
- **Logging:** verbose (DEBUG для vision pipeline; cost/tokens на каждый API call)
- **Docs:** yes — обязательное обновление memory + evidence в T13
- **Roadmap Linkage:** skipped (нет roadmap-файла в `.ai-factory/`)

## Контекст падений (по триажу)

| # | Платформа | error_code | Где упёрся |
|---|---|---|---|
| 922 | Instagram | `ig_camera_open_failed` | switcher дошёл до `ig_6_type_sheet`. После этого publisher 2× видит «застряли на профиле» (`ig_stuck_on_profile`) → escalation → таймаут камеры. По screencast: модалка **"Продолжить редактирование черновика"** (известный pending в `project_publish_testbench.md`) |
| 923 | TikTok | `tt_fg_drift_unrecoverable` | foreground остаётся `com.sec.android.app.launcher` 3 раза подряд после `am start`. force-stop launcher + retry не помогли. По screencast: TikTok **реально открыт**, foreground-чек врёт |
| 924 | YouTube | `yt_accounts_btn_missing` | postmortem dump показывает headers feed-карточек (`Воспроизвести видео`, `Перейти на канал RUSTAMJON TV`), profile-tab tap не открыл profile screen. Тот же баг что в memory `project_revision_phone171_backlog.md`. В **revision** уже есть Settings-Activity fallback (memory `reference_yt_accounts_settings_path.md`) — в **publisher** ещё не применён |

## Решения архитектуры

| Вопрос | Решение | Альтернативы (отвергнуты) |
|---|---|---|
| Vision LLM | **Anthropic Claude Sonnet 4.6** через текущий OAuth `sk-ant-oat01-...` | Groq llama-3.2-90b-vision (хуже качество); Hybrid (сложнее) |
| Что подаём | **frames @ 30 FPS + perceptual-hash dedup** (image content blocks, base64) | Files API (не поддерживает .mp4 ни одним типом ключа); pure-покадрово без dedup (~$1000/день) |
| Точки вызова | **Все три:** inline recovery (publisher stuck-points) + mandatory post-mortem (triage_classifier) + success-audit (silent regression) | One-of (не покрывает все классы багов) |
| Стоимость | dedup ratio типично ~5-10% → ~50-150 unique frames из 1800 → **~$0.10-0.30 per fail run** + cap 50 success-audits/день через `system_flags` | Без cap — риск unbounded spend |
| API key | Текущий **OAuth** (vision работает, Files API нам не нужен) | Console API key (не нужен пока не упрёмся в OAuth rate limits) |
| S3 layout | **Новый prefix** `autowarm/vision_frames/{platform}/task{id}/frame_NNN.jpg` + `vision_report.md` + `manifest.json` | смешивать со screenshots (труднее фильтровать) |
| DB | **Новые колонки** `publish_tasks.vision_analysis_url, .vision_mode` | внешняя таблица (overkill) |

## Архитектура pipeline

```
publisher.py (run_publish_task)
├── inline-recovery точки [T5]:
│   ├── publish_instagram_reel @ ig_stuck_on_profile (publisher.py:3084)
│   ├── _switch_youtube @ yt_accounts_btn_missing_postmortem (account_switcher.py:1835)
│   └── _switch_tiktok @ tt_fg_drift_unrecoverable (account_switcher.py:1387)
│       → vision_analyzer.analyze_screencast(screenshot, mode='inline')
│       → 1 retry с tap/keycode-инструкцией от LLM
│       → cap: 1 vision-attempt per stuck-инцидент
│
└── finally (status='completed' OR 'failed'):
    ├── stop_and_upload_screen_record() → S3
    ├── if status='failed':
    │     triage_classifier.process_failed_task(task_id) [T6]
    │     └── vision_analyzer.run_postmortem(screen_record_url)
    │         → ffmpeg @ 30 FPS → perceptual-hash dedup
    │         → batch на Claude (max 20 frames из unique-set)
    │         → S3 upload (frames + vision_report.md + manifest.json)
    │         → UPDATE publish_tasks SET vision_analysis_url, vision_mode='postmortem'
    │         → передать текст в agent_diagnose как доп.контекст
    └── if status='completed':
          spawn async vision_analyzer.run_success_audit(task_id) [T7]
          → cap 50 audit/day (system_flags.vision_success_audit_daily_cap)
          → если detect silent error → INSERT publish_investigations + Telegram
```

## Tasks (13 шт, see TaskCreate IDs 1-13)

### Phase 1: Vision infrastructure (foundation, 4 task)

- [x] **T1** `vision_analyzer.py` модуль — frame-extraction + Claude API call core. Public API: `extract_frames_dedup(mp4_path, hamming_threshold=8)`, `analyze_screencast(frames, context, mode)`. anthropic SDK с image content blocks (base64). Cap 20 frames per call.
- [x] **T2** `[blockedBy: T1]` ffmpeg + perceptual-hash helpers. `_extract_frames_30fps`, `_dedup_by_phash`, `_resize_for_claude`. Smoke на mp4 задачи 922 — проверить что draft-modal попал в выборку. **Smoke-результат: 7490 raw → 132 unique (1.8% dedup ratio) за 103с.**
- [x] **T3** `[blockedBy: T1, T2]` S3 upload helper. Новый prefix, переиспользовать boto3 setup из `publisher.py:101-115`. Graceful fallback на `file://` при S3-ошибке. **Smoke: HTTP 200 на `task999999/manifest.json`.**
- [x] **T4** `[blockedBy: T3]` миграция `publish_tasks.vision_analysis_url, .vision_mode`. Cross-repo grep на `publish_tasks` SELECT/INSERT (memory `feedback_cross_repo_schema_changes.md`). **Применена в prod БД, cross-repo grep clean (только autowarm + autowarm-testbench, оба используют named-column UPDATE — safe).**

### Phase 2: 3 точки вызова (3 task)

- [x] **T5** `[blockedBy: T1, T4]` Inline recovery hook в publisher (3 stuck-точки). Парсинг JSON-ответа от Claude → tap/keycode/noop. Cap 1 попытка per incident. Tests с mock-vision. **Реализовано через `publisher_vision_recovery.py` (DRY-helper). IG @ profile_stuck (publisher.py), YT @ accounts_btn_missing + TT @ fg_drift (account_switcher.py).**
- [x] **T6** `[blockedBy: T1, T2, T3, T4]` Mandatory post-mortem в `triage_classifier.process_failed_task`. Расширение `agent_diagnose.build_user_prompt` с разделом vision-postmortem. agent_runs запись `agent='vision_postmortem'`. **Helper `_run_vision_postmortem`. agent_diagnose читает `vision_analysis_url`, скачивает `vision_report.md` через `fetch_vision_report`, вставляет в prompt.**
- [x] **T7** `[blockedBy: T1, T2, T3, T4]` Success-run audit (silent regression). Async через thread-pool. Daily cap через `system_flags`. Создание `publish_investigations` при detected regression. **`spawn_success_audit` + `run_success_audit` в triage_classifier. Cap inflight=2, daily cap из `system_flags.vision_success_audit_daily_cap` (default 50). Hook в publisher `_dump_testbench_fixture`.**

### Phase 3: Точечные фиксы 3 задач (3 task, parallel с Phase 2)

- [x] **T8** `[blockedBy: T1]` IG draft-continuation handler — фикс задачи 922. `_IG_DRAFT_CONTINUATION_MARKERS` + handler "Начать новое видео". 2 теста. **`_is_ig_draft_continuation` + handler в IG camera-loop. Тесты в T11.**
- [x] **T9** `[blockedBy: T1]` YT Settings-Activity fallback в publisher — фикс задачи 924. Применить known-good путь из revision. Helper из `backfill_yt_gmails.py.live_probe_picker`. 1 тест. **`_yt_open_via_settings_activity(target, cfg)` в account_switcher. Встроен как fallback после T5 vision-recovery, до final fail.**
- [x] **T10** `[blockedBy: T1]` TT foreground-check diagnostic + vision-fallback — фикс задачи 923. Шаг A: 3 источника одновременно (`topResumedActivity` + `mCurrentFocus` + `recents`). Шаг B: vision-fallback при подтверждённом drift. 2 теста. **`_probe_fg_sources_diagnostic` + event `{prefix}_fg_check_disagreement` на streak>=2. Vision-fallback (Шаг B) уже встроен в T5.**

### Phase 4: Tests + observability + docs (3 task)

- [x] **T11** `[blockedBy: T1, T2]` Unit + integration тесты vision_analyzer. Mock anthropic.Anthropic, perceptual-hash на synthetic frames. `@pytest.mark.live` для real-API smoke. **42 новых теста (test_vision_analyzer.py + test_publisher_vision_fixes.py). Suite: 304/318 pass (11 baseline + 3 skipped, без регрессий).**
- [x] **T12** `[blockedBy: T4]` Dashboard badge vision-runs. Cosmetic, низкий приоритет — не блокирует. **server.js: SELECT расширен на vision_analysis_url + vision_mode. testbench.html: новая колонка «Vision» с link 🎥 → vision_report.md.**
- [x] **T13** `[blockedBy: T5, T6, T7, T8, T9, T10, T11]` Update memory + evidence + commit-push. Memory updates в `project_publish_testbench.md`, `feedback_ui_automation_edge_cases.md`. Evidence `.ai-factory/evidence/publisher-vision-20260424.md`. Deploy через `testbench` ветку (НЕ в `main`). **4 atomic commit'а в testbench: `8eae73c` `d1a27c8` `cd53c00` `0759762` — pushed в origin/testbench. Memory обновлена. Evidence создан.**

## Commit Plan (5+ tasks → нужны checkpoints)

1. **После T1-T4:** `feat(vision): perceptual-dedup screencast analyzer + S3 + DB column`
2. **После T5-T7:** `feat(publisher): vision inline-recovery + post-mortem + success audit`
3. **После T8-T10:** `fix(publisher): IG draft-continuation, YT settings-activity fallback, TT fg-check diagnostic`
4. **После T11-T13:** `test+docs: vision tests, dashboard badge, memory updates, evidence`

Atomic commits — pytest зелёный перед каждым (memory `feedback_parallel_claude_sessions.md`). Не оставлять half-broken state для соседних сессий.

## Risks / Open questions

1. **OAuth rate limits для Sonnet 4.6.** Текущий OAuth-токен (Claude Code) может ограничивать ~5-10 RPM на vision. Если упрёмся — вытаскивать `sk-ant-api03-...` из console.anthropic.com (memory `project_publish_testbench.md` → Pending). Mitigation: cap 1 inline-recovery per stuck + daily cap на success-audit.
2. **Cost monitoring.** Добавить трекинг в существующий `agent_runs` table с `agent='vision_*'`. Если daily spend > $100 — auto-pause через `system_flags.vision_paused=true` (новый flag).
3. **TT fg-check root cause** (T10): диагноз гипотетический. Сначала diagnostic-этап (шаг A) собирает данные, потом отдельным фиксом переключаем primary source. Vision-fallback (шаг B) — safety net пока корень не найден.
4. **Inline-recovery latency.** +5-10 сек на каждый stuck-инцидент. Для testbench приемлемо (cadence 10 мин). Для prod — может потребоваться отдельный feature flag.
5. **JSON-парсинг ответа vision.** Claude может выдать markdown вместо строгого JSON. Mitigation: использовать `response_format` если поддерживается, иначе — defensive regex extract.
6. **Перцептивный hash на mobile UI.** Рекомендации (memory `feedback_ui_automation_edge_cases.md` про bottom-nav): keep-alive анимации могут давать false-changes. Если dedup-ratio < 0.5% (то есть почти все frames уникальны из-за животной анимации) — повысить hamming threshold с 8 до 12.

## Ссылки

- Скринкасты: `https://save.gengo.io/autowarm/screenrecords/{platform}/task{922,923,924}_fail_screenrec_*.mp4`
- Fixtures: `/home/claude-user/testbench-fixtures/{922,923,924}.tar.gz`
- Memory: `project_publish_testbench.md`, `reference_yt_accounts_settings_path.md`, `feedback_ui_automation_edge_cases.md`, `reference_bug_video_pipeline.md`, `project_revision_phone171_backlog.md`
- Известный bug-video pipeline (frames + Whisper): `/home/claude-user/contenthunter_bugs_bot/` (memory `reference_bug_video_pipeline.md`) — переиспользовать ffmpeg-pattern
