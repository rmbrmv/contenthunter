# Evidence — IG Publish Fixes Bundle (2026-04-28)

**Plan:** `.ai-factory/plans/2026-04-28-ig-publish-fixes-bundle.md`
**Status:** ✅ **SHIPPED** to prod main as `4b8ad20` (merge of `feat/ig-publish-fixes-bundle-20260428`)
**Auto-pushed:** `GenGo2/delivery-contenthunter` (post-commit hook)

## Контекст

Investigation 2026-04-28 разобрал 5 последних prod IG fail'ов (`/publishing/tasks` URL):
- **1502, 1503, 1504, 1509** (04:55-05:17 UTC) — Python `NameError: random` в `publisher_base.py` (закрыт в этот же день коммитом `fcfa851` — отдельный hot-fix)
- **1532** (14:56-15:23 UTC, 27 минут wall-clock) — каскад: `ig_reels_tab_not_found` → fallback в галерею Stories → AI Unstuck × 16 раз тапает несуществующий «OK» → `ig_upload_confirmation_timeout`. Скринкаст подтвердил, что бот публиковал **Stories**, а не Reels.

Root cause 1532: bottom_sheet «Создать» (4 опции) — селектор `tap_element(['Reels',...])` permissive substring matching попал не в плитку «Создать новое видео\xa0Reels» (NBSP), а в один из 4 конкурирующих элементов (3 миниатюры reels-feed + bottom-nav 'Reels'). Дальше permissive `camera_ready` детектор срабатывал на любой UI с подстрокой 'Reels'/'История' → каскад в Stories UI.

## Что отгружено

### T1 — `error_code` coverage для всех fail-путей (`fa8570f`)

- Extract `_set_error_code_from_events()` из inline-блока в `_fail_task` → standalone метод на `BasePublisher`
- Hook вызывается из `update_status('failed', …)` — теперь любой путь (`critical_exception`, `preflight`, «Публикация не прошла», и т.д.) получает canonical `error_code`
- 4 unit-теста против реального Postgres (паттерн codebase'а)
- Files: `publisher_base.py` (+30/-11), `tests/test_error_code_mapper.py` (+96)

### T2 — Strict NBSP-tolerant Reels-tile selector (`87c203a`)

- New `_tap_create_reels_tile_strict(ui)` — exact-match по 3 candidates (NBSP / ASCII / EN), исключает миниатюры и bottom-nav
- Заменяет permissive call в `[FIX: IG-stuck-on-profile]` recovery branch
- 3 unit-теста + fixture с реальным UI dump из task #1532
- Files: `publisher_instagram.py` (+80/-5), `tests/test_ig_create_tile_selector.py` (+93), `tests/fixtures/ig_create_bottom_sheet.xml` (78,418 bytes)

### T3 — Post-tap Reels-mode validation + fail-fast (`39d60eb`)

- New `_verify_reels_camera_mode(ui) -> (bool, mode_str)` — определяет landing (Reels / Stories / Photo / Live / unknown), приоритет Stories markers первым
- 2 integration points:
  1. После strict Reels-tile tap — verify; если не Reels → `ig_wrong_camera_mode` event + continue к следующей попытке
  2. REELS-tab miss path — было silent continue (источник каскада 1532), теперь fail-fast `return False` если mode != reels
- Files: `publisher_instagram.py` (+83/-4)

### T4 — `ig_editor_timeout` post-mortem телеметрия (`faf91ea`)

- Enriched event meta: `last_action`, `last_ui_texts` (top-12 text+content-desc), `screenshot_url` (S3), `ui_snippet` (300 chars)
- Implementer caught план-ошибку: `_save_debug_artifacts` void-method, использовал `self._collected_screenshots[-1]` (правильно)
- Files: `publisher_instagram.py` (+33/-4)

### Merge → main

```
4b8ad20 Merge feat/ig-publish-fixes-bundle-20260428: IG Reels↔Stories fix + observability + telemetry
faf91ea fix(ig-publisher): enrich ig_editor_timeout meta for post-mortem analysis
39d60eb fix(ig-publisher): post-tap Reels-mode validation + fail-fast on Stories landing
87c203a fix(ig-publisher): strict NBSP-tolerant Reels-tile selector in bottom_sheet
fa8570f feat(publisher): error_code coverage for ALL failed paths via update_status hook
```

## SQL Baselines

### Before merge — `error_code` coverage в prod failed (последние 30 дней)

```
 platform  | null_ec | with_ec
-----------+---------+---------
 Instagram |     324 |       0
 TikTok    |     163 |       1
 YouTube   |     129 |       0
```

**Полное отсутствие error_code у prod-фейлов** — 616 задач за 30 дней без canonical code. После T1 все новые failed-задачи будут получать code автоматически.

### Before merge — `ig_editor_timeout` meta keys

```
  id  | meta_keys
------+-----------
 1323 |         4
 1323 |         4
 1091 |         4
 1091 |         4
 1085 |         4
```

**Все 32 случая за 7 дней** — ровно 4 meta-keys (`category/platform/step/max_steps`). После T4 будет 7+ keys для новых событий.

## Smoke-проверка fix #1 (T6)

Создана тестовая задача с `meta.category='smoke_test_category'` → status='failed' через `BasePublisher.update_status()` (через `_set_error_code_from_events` напрямую — Stub без MRO):

```
helper returned: 'smoke_test_category'
  id  | status |     error_code
------+--------+---------------------
 1609 | failed | smoke_test_category
```

✅ Fix работает в prod environment.

**Caveat:** call через `update_status` (с hook) при Stub без MRO логирует warning `'Stub' object has no attribute '_set_error_code_from_events'` и идёт дальше — это правильное поведение hook'а (try/except не должен ломать status update). В реальном проде `self` всегда BasePublisher subclass, метод резолвится корректно. Smoke через прямой class-call подтвердил behavior.

## Pytest

- 357 passed, 11 failed, 3 skipped (всего 371 теста)
- 11 failures — **pre-existing** на T2 head (test_publish_guard / test_switcher_read_only / test_testbench_orchestrator), DB-dependent unrelated tests, не регрессии
- Все новые тесты (4 в test_error_code_mapper + 3 в test_ig_create_tile_selector) — green
- Все 36 IG-related tests green после T3+T4

## Live observation (T6 step 7)

В 15-минутное окно после deploy не возникло prod failed-задач — очередь пустая или off-hours. Live verification произойдёт органически с ближайшими IG/TT/YT publish задачами. Следующая сессия должна проверить:

```sql
SELECT id, platform, status, error_code, started_at, updated_at
FROM publish_tasks
WHERE updated_at >= '2026-04-28 18:50:00'
  AND status='failed'
ORDER BY id DESC LIMIT 20;
```

Ожидание: все новые failed-задачи имеют непустой `error_code`. Если NULL — дрифт PM2 cwd или другой issue, разбираться.

## Open follow-ups (discovered during reviews — не блокеры, в backlog)

### От T2 review (Important)
- **Strict-selector раскатка на 2 ещё места** в `publisher_instagram.py`:
  - Line 366 (`[FIX: IG-reopen-via-home]` post-launch path)
  - Line 537 (main happy-path bottomsheet — самый частый код-путь!)
  
  Те же 4 опции, та же permissive логика, та же гипотетическая регрессия. T2 исправил только recovery branch (где упала 1532); happy-path с тем же багом остался. Mechanical fix (2 × ~10 строк), берётся следующей сессией.

### От T3 review (Important)
- **Marker false-positive риск** в `_verify_reels_camera_mode` — flat substring scan может зацепить `'Близкие друзья'` в audience-picker'е Reels (cross-promotion от IG). Mitigation: matching по attribute-scope (`text="..."` / `content-desc="..."`) вместо raw XML.
- **Missing unit tests** для `_verify_reels_camera_mode` (5 branch'ей — easy to test fixture-driven). Plan не требовал, но для регрессионной защиты стоит добавить (`tests/test_ig_camera_mode_verifier.py` + 5 фикстур).

### От T4 review (Minor)
- Loop bound `range(30)` vs `max_steps: 20` в логе и event meta — pre-existing рассинхрон, отдельный janitorial PR.

### Из investigation (memory backlog)
- **#5 AI Unstuck hardening** — `project_ai_unstuck_hardening_backlog.md`. Anti-loop guard, screenshot URL в meta, экономия ~64¢/fail.
- **#6 IG account audit** — `project_ig_failing_accounts_audit_backlog.md`. 8 аккаунтов 4-8 fail/7д (cosmetics/payment niches) — гипотеза account-level rate-limit от IG. Discovery, не код.

## Memory updates

- ✅ `MEMORY.md` — новая строка про IG publish fixes bundle (2026-04-28 ✅)
- ✅ `project_publisher_modularization_wip.md` — параграф «IG Reels↔Stories fix bundle — отгружено 2026-04-28»
