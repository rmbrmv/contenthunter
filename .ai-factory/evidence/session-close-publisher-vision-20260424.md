# Session close — Publisher vision pipeline (2026-04-24)

**Сессия:** /aif-plan full → /aif-implement → end-to-end smoke → vendor switch.
**Запрос пользователя:** «дочистить баги по публикации (тройка 922/923/924) + добавить AI-анализ скринкастов как обязательный этап в testbench».

## Что сделано

### Код (5 atomic коммитов в `testbench` ветке GenGo2/delivery-contenthunter)

| SHA | Что |
|---|---|
| `8eae73c` | **Phase 1:** `vision_analyzer.py` (ffmpeg @ 30 FPS + perceptual-hash dedup + Groq vision) + S3 upload в `autowarm/vision_frames/{platform}/task{id}/` + миграция `publish_tasks.vision_analysis_url, vision_mode` |
| `d1a27c8` | **Phase 2:** `publisher_vision_recovery.py` DRY-helper + 3 inline-recovery hooks (IG ig_stuck_on_profile, YT yt_accounts_btn_missing, TT tt_fg_drift_unrecoverable). Mandatory post-mortem в `triage_classifier.process_failed_task` + `agent_diagnose.fetch_vision_report`. Async success-audit (cap inflight=2, daily cap из `system_flags.vision_success_audit_daily_cap`) |
| `cd53c00` | **Phase 3:** T8 IG draft-continuation handler (`_is_ig_draft_continuation` + tap «Начать новое видео»), T9 YT Settings-Activity fallback (`_yt_open_via_settings_activity`), T10 TT fg-check diagnostic (`_probe_fg_sources_diagnostic`) |
| `0759762` | **Phase 4:** 42 unit-теста (`test_vision_analyzer.py` + `test_publisher_vision_fixes.py`) + dashboard «Vision» badge в testbench.html |
| `6f32745` | **Phase 5 (production-блокер):** Anthropic OAuth → Groq Llama 4 Scout. Sonnet 4.6 OAuth-токен `sk-ant-oat01-...` вернул `401 invalid x-api-key` на live API call (это proxy-токен Claude Code, не работает напрямую). Переход на Groq, MAX_FRAMES_PER_CALL=5 (Llama 4 Scout hard limit) |

### Документация (контекст, evidence)

- `.ai-factory/plans/publisher-vision-screencast-analysis-20260424.md` — full plan, 13 задач
- `.ai-factory/evidence/publisher-vision-20260424.md` — детальное evidence (включая Phase 5 vendor switch)
- `.ai-factory/evidence/session-close-publisher-vision-20260424.md` — этот файл

### Memory

- `feedback_oauth_token_no_direct_api.md` — НОВАЯ. `sk-ant-oat01-...` НЕ работает с api.anthropic.com напрямую. Backend требует Console key. Smoke-проверять SDK ДО planning.
- `project_publish_testbench.md` — расширен Vision pipeline (Phases 1-5). Pending list обновлён: ✅ IG draft-continuation, ✅ Dashboard vision badge.
- `project_revision_phone171_backlog.md` — отмечено что YT Settings-Activity fallback теперь и в publisher.

### Production state (на момент закрытия сессии)

- PM2 `autowarm-testbench` (id=25): **online, 25 restarts, uptime 2-30 мин**. Подхватил последний commit `6f32745`.
- `system_flags.testbench_paused = false`, `auto_fix_enabled = true` — testbench работает в обычном режиме.
- Vision активен (нет env kill-switch'ей). Cost-tracking автоматически в `agent_runs WHERE agent LIKE 'vision_%'`.
- Pytest baseline: **307 pass / 11 fail (=pre-existing) / 3 skipped**. Регрессий 0.

### End-to-end smoke на task 922 (validated)

- mp4 download → ffmpeg @ 30FPS → 7490 raw frames
- Perceptual-hash dedup → 132 unique (1.8% ratio за 103 сек)
- Groq vision call (5 frames из 132): 12397 input + 287 output tokens, **$0.0015**, 1.5 сек
- S3 upload (132 frames + report + manifest): 25.6 сек → `https://save.gengo.io/autowarm/vision_frames/instagram/task922`
- DB UPDATE + agent_runs запись ✅
- `vision_report.md` доступен по public URL

## Что вышло хуже ожиданий

### Quality vision

Llama 4 Scout на 5 frames task922 вернул общие фразы:
> «Frame 3: Экран Instagram с чужого аккаунта. Сбой начался в Frame 3, когда экран переключился на Instagram, но не смог открыть камеру. Возможно, это сопровождалось системным сообщением об ошибке.»

Известный мне реальный root-cause (модалка «Продолжить редактирование черновика») в narrative **не упомянут**. Это:
- Quality-limit Llama 4 Scout vs Sonnet 4.6 на UI-понимании
- Sample-limit (5 frames из 132 unique — модалка могла не попасть в выборку)

**Не баг pipeline'а** — pipeline работает end-to-end. Решение записано в runbook (`feedback_oauth_token_no_direct_api.md`): когда выпишут Console API key → 5-минутный возврат на Sonnet с MAX_FRAMES=20.

## Что НЕ сделано (намеренно или вне scope)

- ❌ Merge `testbench → main`. Memory `project_publish_testbench.md` явно: «НЕ коммитить в прод main без ручного merge».
- ❌ Получение Console API key — ваше действие, не моё.
- ❌ Pre-existing 11 fail в test_publish_guard.py / test_testbench_orchestrator.py — это работа другой сессии (DB schema deprecation после DROP `account_packages` 2026-04-22).
- ❌ Live-validation T8/T9/T10 фиксов на production phone #19 — нужно дождаться следующих failed runs IG/YT/TT (или manually re-trigger). См. backlog.

## Что мониторить в production (24h)

1. **Dashboard `https://delivery.contenthunter.ru/testbench.html`** — новая колонка «Vision» 🎥. На каждом fail должна появляться ссылка на `vision_report.md`.
2. **Cost**: `SELECT SUM(cost_usd), COUNT(*) FROM agent_runs WHERE agent LIKE 'vision_%' AND finished_at >= NOW() - INTERVAL '24h'`.
3. **Quality**: открыть 5-10 свежих vision_report'ов. Если Llama 4 Scout стабильно даёт общие фразы без конкретных UI-маркеров (text="X", coords) — сигнал получать Console key.
4. **Регрессии**: `SELECT error_code, COUNT(*) FROM publish_tasks WHERE testbench=true AND finished_at >= NOW() - INTERVAL '24h' GROUP BY error_code`. Не должно появиться **новых** error_code из-за наших изменений.
5. **TT fg-check disagreement**: `SELECT meta FROM events WHERE meta->>'category' = 'tt_fg_check_disagreement'` — после 5+ записей будет видно какой источник реально надёжнее.
