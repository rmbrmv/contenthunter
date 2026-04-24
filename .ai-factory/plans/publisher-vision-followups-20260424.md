# Publisher vision pipeline — follow-ups & гипотезы

**Создано:** 2026-04-24 (session-close после plan `publisher-vision-screencast-analysis-20260424.md`)
**Контекст:** vision pipeline отгружен 5-ю фазами, end-to-end работает, но Llama 4 Scout даёт quality ниже ожиданий. Точечные фиксы 922/923/924 готовы и **не зависят от vision** — они отдельная ценность.

## P1 — критично для quality vision

### B1. Console API key для Anthropic + возврат на Sonnet 4.6

**Why:** Llama 4 Scout на 5 frames task922 не разглядел известный draft-continuation modal. Quality-limit модели + малой выборки.

**Пререкизит:** пользователю выписать `sk-ant-api03-...` на console.anthropic.com.

**После того как ключ есть:** runbook в memory `feedback_oauth_token_no_direct_api.md` («Runbook: возврат с Groq на Anthropic Sonnet»). Изменения локальны в `vision_analyzer.py`:
- `MODEL = 'claude-sonnet-4-6'`, `MAX_FRAMES_PER_CALL = 20`
- `_call_groq_vision` → `_call_anthropic_vision` через anthropic SDK
- Stratification вернуть к first-5 + middle-5 + last-10
- Tests: моки `urllib.request.urlopen` → `anthropic.Anthropic`

**Cost impact:** $0.05/день → $1-2/день при 10 fail/день. Приемлемо.

### B2. Live validation тройки 922/923/924 фиксов в prod

**Why:** T8/T9/T10 проверены unit-тестами (43 пройдено), но ни один **не отработал на реальном устройстве** в ходе сессии — нужны failed runs того же класса для IG draft-continuation, YT accounts_btn missing, TT fg drift.

**Как:**
- Дождаться 24h orchestrator runs на phone #19 (cadence ~10 мин) — должны появиться все 3 класса fail'ов
- Проверить events на новые категории: `ig_draft_continuation_dismissed`, `yt_settings_activity_fallback_success`, `tt_fg_check_disagreement`
- При появлении — открыть task в дашборде и убедиться что run **прошёл** благодаря фиксу

**Кейс не отработал** — диагностировать (UI поменялся? координаты другие?) и доработать.

## P2 — quality улучшения vision

### B3. Chunked vision pipeline для post-mortem

**Гипотеза:** разбить 132 unique frames на чанки по 5, делать 26+ Groq-вызовов параллельно, мерджить narrative. Решает sample-limit (сейчас Llama видит 4% frames).

**Cost impact:** ×26 на инцидент = ~$0.04/инцидент (всё ещё в 25× дешевле Sonnet). Latency: 1.5с × 26 / parallelism. С `concurrent.futures` и cap=5 параллельных = ~10 сек.

**Когда делать:** **только если** B1 не выполнен (Sonnet снимает sample-limit nativeно через MAX_FRAMES=20). Не заниматься preemptively.

### B4. Подавать `events.meta.screenshots` в vision вместо/вместе с ffmpeg-сэмплами

**Гипотеза:** publisher уже сохраняет screenshot на КАЖДОМ ключевом step (по task 924 их было 17). Это **значимые** moments (не random sample). Если подать их Llama 4 Scout вместо равномерных ffmpeg-frames — vision увидит критические UI-стейты целенаправленно.

**Реализация:** в `_run_vision_postmortem` добавить ветку: если в `events` есть `meta.screenshots` URL'ы — подкачать их + добавить в outset frames. Cap 5 всё равно остаётся.

**Risk:** screenshot'ы публикатор делает в моменты которые ОН считает важными — сам про модалки часто не знает (про что vision и должен сказать). Но как «контекст» это лучше чем blind sample.

### B5. Vision-cache по error_code + UI-fingerprint

**Гипотеза:** если `ig_camera_open_failed` 5 раз подряд даёт одинаковый XML-stick + одинаковый narrative — нет смысла дёргать LLM на каждой повторе. Использовать fingerprint (hash of last_ui XML или phash первого frame'а) как cache key, hit → копировать report от первой задачи.

**Реализация:** `vision_cache` table или Redis. На new_cluster — fingerprint → если match с прошлым → INSERT INTO publish_tasks vision_analysis_url из кэша + skip Groq call.

**Cost saving:** ~80-90% на повторных кластерах. Прежде чем делать — посмотреть production logs за неделю: какой % failed runs повторяет уже existing investigation.

## P3 — архитектурное / observability

### B6. Хранить только `frame_count_sent` frames в S3, не все unique

**Why:** сейчас `upload_vision_artifacts` льёт все 132 unique frames на S3. Это ~9.59MB на инцидент. Realно использованы Groq'ом только 5. Storage waste ~95%.

**Fix:** изменить `upload_vision_artifacts(...)` чтобы принимал `selected_frames` отдельно от `all_unique_frames`. Лить в S3 только `selected`. `all_unique` оставить локально в `/tmp/vision_frames/...` до cleanup (или вообще не сохранять).

**Saving:** ~50% storage в `autowarm/vision_frames/` prefix.

### B7. Frames preview в dashboard

**Why:** сейчас в `testbench.html` колонка «Vision» имеет только link на `.md`. Удобнее видеть thumbnails 5 frames прямо в expanded строке инцидента.

**Реализация:** при click на 🎥 → expand row с `<img>` тегами на `frame_0000.jpg` ... `frame_0004.jpg` из `vision_analysis_url + '/frame_NNNN.jpg'`.

### B8. TT fg-check root cause после N инцидентов

**Why:** T10 диагностический сейчас в production. После 5-10 production fail'ов посмотреть `meta.category='tt_fg_check_disagreement'` events в `publish_tasks.events`. Если стабильно `mCurrentFocus` показывает TikTok когда `topResumedActivity` показывает launcher — переключить primary `_detect_foreground_pkg` на `mCurrentFocus`.

**SQL для мониторинга:**
```sql
SELECT
  meta->>'top_resumed_activity_pkg' AS top,
  meta->>'m_current_focus_pkg' AS focus,
  meta->>'recents_first_pkg' AS recents,
  COUNT(*) AS n
FROM publish_tasks pt,
     LATERAL jsonb_array_elements(pt.events) e
WHERE e->>'type' = 'warning'
  AND e->'meta'->>'category' LIKE '%_fg_check_disagreement'
  AND pt.updated_at > NOW() - INTERVAL '7 days'
GROUP BY 1,2,3
ORDER BY n DESC;
```

## P4 — nice to have

### B9. Vision-recovery для других IG-стейтов помимо `ig_stuck_on_profile`

**Why:** в IG camera-loop есть и другие detectors (highlights_empty_state, gallery_picker, about_account_modal). Сейчас vision-recovery только на profile_stuck. Можно расширить на любой stuck-стейт где streak >= 2.

**Risk:** растёт latency на каждый incident, многих видит как vision-кейсов. Лучше делать ПОСЛЕ B1 (Sonnet) когда quality надёжный.

### B10. Skip vision postmortem если error_code = известный low-value

**Why:** для `adb_push_chunked_md5_mismatch` или `media_not_found` vision абсолютно бесполезен (это backend-ошибки, не UI). Сейчас тратим $0.0015 + 25 сек S3 upload зря.

**Fix:** в `_run_vision_postmortem` вначале — `if error_code in SKIP_VISION_CODES: return None`. Список начать с: `adb_push_*`, `media_*`, `account_banned_by_platform`, `critical_exception`.

## Гипотезы для будущей разработки

### H1. **Llama 4 Maverick (если станет доступна на Groq)** — большая sister-модель Scout, больше context + возможно больше images per request. Проверить через `GET /v1/models` периодически.

### H2. **Frame-level OCR pre-pass** — прогнать tesseract по frames, извлечь видимый ru/en-текст, подать Groq как `extra_hint` в structured form. Llama 4 Scout vision phasе сможет фокусироваться на layout/coords, а текст уже распознан надёжно.

### H3. **Vision использовать для самого publisher inline detector building** — вместо hard-coded `_is_ig_draft_continuation` (который мы будем плодить на каждый новый modal) — общий «describe and propose detector» pipeline: vision видит UI, генерит regex-маркеры + tap-coords, мы аппрувим и инжектим. Это уже next-level autonomy. Записать как research direction.

### H4. **Sonnet 4.6 + caching** — system prompt одинаковый между inline-recovery вызовами одной задачи. Anthropic prompt-caching может срезать стоимость inline-режима ×3.

## Pre-existing test failures (НЕ scope этой сессии)

11 pre-existing fail в `tests/test_publish_guard.py` (4) и `tests/test_testbench_orchestrator.py` (5) и `tests/test_switcher_read_only.py` (1) — это последствия DB schema deprecation после DROP `account_packages` 2026-04-22 (memory `project_account_packages_deprecation.md`). Эти тесты ожидают `account_packages` table. Отдельная задача:

### B11. Починить pre-existing 11 failing tests после `account_packages` DROP

Update test fixtures на использование `factory_inst_accounts` + `factory_pack_accounts` (новый source of truth, memory `project_account_packages_deprecation.md`).
