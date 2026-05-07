# Session 2026-05-07 — Publish P0 trio (id_parser / IG outer-cap / YT desc-fill)

**Branch:** `main` (delivery-contenthunter prod autowarm).
**Triage source:** memory `MEMORY.md` + project_publish_followups_2026_05_06.md, project_yt_desc_fill_vision_iter.md, project_id_parser_ig_broken.md.

## TL;DR

3 P0 публикации закрыты за день. Всё в проде, всё validated.

| # | Задача | Status | Validation |
|---|--------|--------|-----------|
| 3 | `id_parser.py` IG broken | ✅ closed | smoke `natgeo→user_id=787132` |
| 2 | IG AI Unstuck Share-loop | ✅ shipped | 6 unit tests, live trigger ждёт |
| 1 | YT desc-fill (21+ дней silent loss) | ✅ **fixed end-to-end** | task 3400 `description filled OK (53 chars)` |

## #3 — id_parser IG (CLOSED без кода)

Memory от 2026-04-23 (14 дней): Apify 403 + i.instagram 429 на VPS IP. Pre-action smoke `python3 id_parser.py instagram natgeo` сегодня вернул `{"ok": true, "user_id": "787132"}`. Самовосстановилось — Apify баланс/актёр или Meta-rate-limit. Memory переписана под CLOSED + recovery плейбук на случай рецидива.

**Lesson:** memory с infra/external dependencies обязательно verify smoke'ом перед действиями (per `feedback_plan_staleness.md`).

## #2 — IG AI Unstuck outer-cap (commit `0b501e4`)

**Repro:** task 3228 el_cosmetics7 2026-05-07 04:55-05:21 — 47 ai_unstuck_action + 10 anti-loop trips за **26 минут** одного `_wait_instagram_upload`. Anti-loop guard режет повтор внутри одного вызова, но caller (unknown ModalActivity branch на line 1840) перезапускал `ai_unstuck` снова и снова на том же UI.

**Fix:**
- `publisher_base.py`: pure helper `_should_break_unstuck_loop(failure_count, cap=2)`.
- `publisher_instagram.py`: счётчики `unstuck_failure_count`/`unstuck_call_count` в `_wait_instagram_upload`. После 2 безуспешных вызовов → break + structured `ig_unstuck_outer_cap_reached` event + S3 dump. Успешный `ai_result` сбрасывает серию.
- 6 TDD unit tests: zero/one/two failures, default/custom cap, defensive negatives.

**Effect:** ~$0.12+ Groq/инцидент сэкономлено, цикл 26 мин → ~5 мин, новый структурный error_code для триажа.

**Live validation pending:** сегодня нет IG fail с этим pattern (статистика дня, не регрессия).

## #1 — YT desc-fill ROOT CAUSE FIXED через iter6+7+8 (3 commits)

**Контекст:** 21+ дней YT-видео публиковались с пустым описанием. iter1-iter5 (2026-05-05) пытались чинить через prompt-инженерию + crop — все wrong_screen.

### Discovery: проблема была в ДВУХ местах

Pre-action verify показал: `.env` уже содержал `VISION_PROVIDER=anthropic` + `ANTHROPIC_API_KEY=sk-ant-api03-...` с момента W3.1 (commit `4cc16aa` 2026-05-04), а Claude Vision никогда не вызывался. Grep'нул — `publisher_base.ai_find_tap` хардкодил `httpx.post('https://api.groq.com/openai/v1/chat/completions', model='meta-llama/llama-4-scout')` в обход `vision_analyzer.call_vision` router'а.

### Iter6 (commit `8430038` → main `4b16da1`) — vision provider router

Заменил inline httpx-блок в `ai_find_tap` на `vision_analyzer.call_vision(system_prompt, user_text, image_blocks)`. Backward compat: provider=groq всё ещё работает (default), просто Anthropic-путь теперь актуально включён. Crop region `(0, 700, 1080, 1900)` сохранён.

**Live smoke task 3341 SpbProperty1Guide:**
- Sonnet 4.6 returns `(540, 681)` in crop → `(540, 1381)` in full-screen
- Visual marker confirmed: точно попадает в «Добавьте описание» row

НО detection возвращал `wrong_screen`. Iter6 fixed vision-провайдер, но раскрыл другой bug.

### Iter7 (commit `e169e4e` → main `5376cdd`) — diagnostic post-tap dump

Pure diagnostic коммит — нет behavior change. Добавил:
- `_save_debug_artifacts('yt_after_vision_tap')` ВСЕГДА после vision-tap
- Structural meta флаги в landed/wrong_screen events: `edittext_focused`, `parent_form_gone`

**Evidence от 5 живых тасков (3395-3399):**
```
coord=540,1381 edittext_focused=true parent_form_gone=true → wrong_screen
coord=540,1375 edittext_focused=true parent_form_gone=true → wrong_screen
coord=540,1381 edittext_focused=true parent_form_gone=true → wrong_screen
coord=540,1381 edittext_focused=true parent_form_gone=true → wrong_screen
coord=540,1385 edittext_focused=true parent_form_gone=true → wrong_screen
```

5/5: vision tap **landed correctly** (parent header gone + EditText focused), но detection всегда False. Причина: detection `'добавьте описание' in ui_l` искала видимый текст, а Compose-virt в desc-editor screen скрывает его — **та же первопричина что заставила использовать vision-fallback на metadata-form**.

### Iter8 (commit `ec66ecf`) — structural signals detection

Заменил text-marker check на:
```python
on_desc_screen = parent_form_gone AND edittext_focused
```

Оба сигнала в a11y-tree независимо от Compose virtualization. AND combination блокирует false-positive (COPPA radio buttons child screen — `parent_gone=true` но `edittext_focused=false`).

3 новых contract теста для iter8 signals: metadata-form-still-visible (no BACK), no-EditText-COPPA-recovery (BACK called), meta-flags-emitted. **46/46 yt_text_fill_verification green.**

### Live validation 2026-05-07 15:04 — task 3400 EliteCornersSpb

```
15:04:29  ai_find_tap → (540, 1381)  ← Claude Sonnet 4.6
15:04:43  yt_desc_vision_tap_landed ✅
15:04:43  YT шаг 2: vision-tap попал на экран "Добавьте описание"
15:04:44  adb_text: ADB_INPUT_B64 OK (53 chars)
15:04:47  YouTube: description filled OK (53 chars) ✅
```

DB: `landed=1, wrong=0`, `status=done`.

**21+ дней YT silent description loss остановлен.**

## Что осталось

**Active backlog (не из этой сессии):**
- #2 IG outer-cap live validation — нужно подождать естественного IG fail с unknown ModalActivity loop pattern
- AI Unstuck camera-screen detection (memory `project_publish_followups_2026_05_06`) — root cause «IG откатывается на камеру/Reels после Share» НЕ закрыт; outer-cap прерывает разорительный цикл, но не лечит причину
- born.trip90 phone #171 re-login (operator action)
- '10' мусор в IG picker phone #19 (low)

## Lessons captured

1. **`ai_find_tap` не использовала VISION_PROVIDER router** — урок: при добавлении новой функциональности (W3.1 Anthropic switch) проверять ВСЕ call-sites старого хардкода, не только основной путь.
2. **Detection text-markers vs structural signals** — Compose-virt прячет text от a11y-tree. Структурные signals (EditText focused, parent activity gone) надёжнее.
3. **Diagnostic commit перед logic fix** — iter7 evidence-collection без behavior change позволил написать iter8 на 100% уверенный fix вместо догадок.
4. **Pre-action smoke external dependencies** — id_parser memory была устаревшей 14 дней. Verify ДО планирования.

## Commits в `origin/main`

| SHA | Title |
|-----|-------|
| `58494f0` | merge fix/ig-share-unstuck-outer-cap-20260507 — outer cap для AI Unstuck в IG _wait_upload |
| `4b16da1` | merge fix/ai-find-tap-vision-router-20260507 — ai_find_tap routes through Claude Vision |
| `5376cdd` | merge fix/yt-desc-vision-detection-20260507 — diagnostic post-tap dump для iter8 |
| `ec66ecf` | merge fix/yt-desc-detection-iter8-20260507 — structural signals detection fix |
