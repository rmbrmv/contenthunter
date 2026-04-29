# Evidence — IG Publish Follow-ups #1-#4 (2026-04-29)

**Plan:** `.ai-factory/plans/ig-publish-followups-1-to-4-20260429.md`
**Status:** ✅ **SHIPPED** to prod main (4 atomic commits, auto-pushed by post-commit hook to GenGo2/delivery-contenthunter)
**PM2 restart:** 2026-04-29 ~07:30Z, restart #210, uptime stable, exec cwd correct (no PM2 cwd drift)

## Контекст

Bundle `4b8ad20` от 2026-04-28 закрыл основной класс IG Reels↔Stories каскадных fail'ов. Финальный code-reviewer одобрил «as shipped» и идентифицировал 8 follow-ups; этот план — **4 Important** (#1-#4).

| # | Описание | Commit |
|---|---|---|
| #1 | Раскатка strict Reels-tile selector на 2 ещё bottomsheet'а (включая happy-path :581 — самый частый код-путь) | `21d56a2` |
| #2 | Unit-тесты для `_verify_reels_camera_mode` (5 mode-веток без покрытия) | `730b394` |
| #3 | Refactor T4 enrichment в helper + unit-тесты (защита от silent break) | `80a8c96` |
| #4 | Attribute-scoped matching в `_verify_reels_camera_mode` (anti false-positive «Близкие друзья») | `82859a9` |

## T0 — pre-check (live SQL verify, before changes)

```
SELECT id, platform, status, error_code, started_at, updated_at
FROM publish_tasks
WHERE updated_at >= '2026-04-28 18:50:00' AND status='failed'
ORDER BY id DESC LIMIT 20;
```

**Результат:** все 20 свежих failed-задач имеют непустой `error_code` (T1 bundle применился чисто). Distribution:
- `ig_editor_timeout` × 5 — самый частый IG fail (как раз тот, который T3 защищает)
- `ig_human_check_required` × 2
- `ig_camera_open_failed` × 1
- `switch_failed_unspecified` × 4
- `yt_target_not_in_picker_after_scroll` × 3
- `tt_target_not_on_device` × 3
- `tt_upload_confirmation_timeout` × 1
- `tt_account_sheet_closed_before_parse` × 1

Нет null-coverage → нет PM2 cwd drift → safe to proceed.

## T1 — Strict-selector раскатка (commit `21d56a2`)

**Файлы:** `publisher_instagram.py:410, 581` (+26/-9).

Заменены 2 permissive `tap_element(['Reels', 'Reel', 'ВИДЕО REELS'], clickable_only=True)` на `_tap_create_reels_tile_strict()` helper.

- **`:410`** (FIX-IG-reopen-via-home recovery branch) — fallback при miss = camera-wait loop доделает + warning event.
- **`:581`** (main happy-path bottomsheet) — fallback при miss = deeplink retry `instagram://reels-camera` + warning event.

Warning event category `ig_create_tile_strict_miss` для post-deploy мониторинга. Существующие 3 unit-теста (`test_ig_create_tile_selector.py`) автоматически покрывают helper'ом — green.

## T2 — Unit-тесты `_verify_reels_camera_mode` (commit `730b394`)

**Файл:** `tests/test_ig_camera_mode_verifier.py` (+143).

11 тестов покрывают все 5 mode-веток + edge cases:

```
test_reels_mode_via_clips_tab_resource_id ✅
test_reels_proxy_via_camera_tab_bar_text ✅
test_stories_mode_via_text_marker ✅
test_stories_mode_via_resource_id ✅
test_stories_mode_close_friends_marker ✅
test_photo_mode_via_resource_id ✅
test_photo_mode_via_text ✅
test_live_mode_via_text ✅
test_empty_ui_returns_empty_ui_marker ✅
test_unknown_mode_when_no_markers ✅
test_stories_priority_beats_reels_marker ✅
```

Pattern `InstagramMixin.__new__` без `__init__` (как в `test_ig_create_tile_selector.py`) — pure-helper тестируемость без MRO/DB зависимостей.

Использование `Class.method(instance, ...)` явно — избегает регрессий типа `feedback_class_vs_instance_test_calls.md` (instance-call vs class-call mismatch).

## T3 — Refactor T4 enrichment + тесты (commit `80a8c96`)

**Файлы:** `publisher_instagram.py` (+34/-23 — extract helper), `tests/test_ig_editor_timeout_meta.py` (+125).

Extract inline-блок (publish_instagram_reel:1448-1477) в `_build_ig_editor_timeout_meta(ui, last_action)` → возвращает dict с 8 ключами.

Reason: T4 enrichment ловил все exception'ы внутри try/except и не имел unit-test'ов → silent break possible. Сам T4 implementer попался на план-ошибке (`(artifacts or {}).get('screenshot_url')` вместо `self._collected_screenshots[-1]`) во время bundle-сессии. Тест мог поймать на test-time.

10 тестов:
```
test_meta_happy_path_all_keys_present ✅
test_meta_empty_screenshots_fallback_to_none ✅
test_meta_no_screenshots_attribute_at_all ✅
test_meta_invalid_xml_does_not_break ✅
test_meta_filters_short_texts ✅
test_meta_caps_at_12_texts ✅
test_meta_ui_snippet_capped_at_300 ✅
test_meta_uses_last_screenshot_when_multiple ✅
test_meta_content_desc_falls_back_when_text_empty ✅
test_meta_none_ui_does_not_crash ✅
```

Behaviour identical к pre-refactor (тесты прошли на свежем helper'е и одновременно служат regression-suite если кто-то изменит логику).

## T4 — Attribute-scoped matching (commit `82859a9`)

**Файлы:** `publisher_instagram.py:106-148` (rewrite), `tests/test_ig_camera_mode_verifier.py` (+2 теста).

Логика:
```
До: if 'marker' in ui (raw substring scan по всему XML)
После: ET.fromstring(ui) → собрать text/content-desc/resource-id 
       → text/desc — exact match, resource-id — substring match
```

Защищает от false-positive когда:
- 'REELS' / 'story_camera' / etc встретится в случайном attribute (class, package, bounds) — раньше триггерил, теперь нет.
- Сломанный XML → `(False, 'parse_error')` вместо raw substring lookup.

Docstring явно предупреждает: pre-camera-only (после audience-picker'а 'Близкие друзья' — валидная Reels-share опция, helper там даст false-positive 'stories' detection).

+2 regression теста:
- `test_attribute_scoped_ignores_bounds_substring` — bounds/class/package с 'REELS'/'story_camera' substring → mode='unknown'.
- `test_parse_error_returns_parse_error_marker` — `<malformed_no_closing_tag` → `(False, 'parse_error')`.

Все 11 существующих T2 фикстур работают без изменений (они уже использовали правильные `text=`/`content-desc=`/`resource-id=` атрибуты).

## T5 — Smoke + restart

### Pytest gate

```
tests/test_ig_camera_mode_verifier.py 13 passed
tests/test_ig_create_tile_selector.py  3 passed
tests/test_ig_editor_timeout_meta.py  10 passed
============================== 26 passed in 0.10s ==============================
```

### Pre-restart queue check

```
 running | claimed | pending 
---------+---------+---------
       0 |       0 |       0
```

Полностью пустая очередь — нулевой риск прерывания running-задач.

### PM2 restart

```
sudo pm2 restart autowarm
→ status=online, restarts=210, uptime=3s, exec cwd=/root/.openclaw/workspace-genri/autowarm
→ unstable_restarts=0
```

### Post-restart logs (40 lines)

Чисто:
- `[assign-queue] Обрабатываем 4 результатов уникализации...`
- `📅 Scheduler запущен`
- `[collectDeviceMetrics] 📡 Начинаю сбор метрик... 10 малинок, 169 устройств`
- Никаких `ImportError` / `NameError` / `Traceback`.

### Live SQL verify (deferred to next session — organic)

Очередь была пустой в момент deploy → fresh failed-задач для observation нет. Live verification произойдёт органически с ближайшими IG/TT/YT publish задачами. Следующая сессия должна проверить:

```sql
-- Strict-selector miss-rate (T1 monitor)
SELECT count(*) FILTER (WHERE category='ig_create_tile_strict_miss') AS strict_miss,
       count(*) FILTER (WHERE category='ig_wrong_camera_mode') AS wrong_mode,
       count(*) FILTER (WHERE category='ig_editor_timeout') AS editor_timeout
FROM publish_events
WHERE created_at >= '2026-04-29 07:30:00'
  AND meta->>'platform' = 'Instagram';
```

Ожидание: `strict_miss` низкий (≤5% от IG задач). Если >30% — strict-helper отвергает валидные плитки, нужно расширять candidate list.

## Open follow-ups (не закрыты этим планом)

### Из исходного backlog'а — оставшиеся 4 (Minor)

- **#5 Live SQL verification** — не отдельная задача, defered organic check (см. выше).
- **#6 `last_action='no_action'` всегда в meta** — либо убрать ключ, либо thread через editor-loop tap-ветви. Janitorial.
- **#7 Loop bound `range(30)` vs `max_steps: 20`** — pre-existing рассинхрон, аккуратно с deduplication-key в Grafana.
- **#8 Testbench backport бундла + этих 4 коммитов** — отдельная сессия. Cherry-pick `fa8570f`, `87c203a`, `39d60eb`, `faf91ea`, `21d56a2`, `730b394`, `80a8c96`, `82859a9` в `/home/claude-user/autowarm-testbench/` ветка `testbench`. Проверить node_modules symlink (memory `feedback_autowarm_testbench_deploy.md`).

## Pytest summary

```
26 passed in 0.10s (всего IG-related тестов)
- 3 test_ig_create_tile_selector
- 13 test_ig_camera_mode_verifier (включая 2 regression-теста для T4)
- 10 test_ig_editor_timeout_meta
```

## Memory updates

- `MEMORY.md` — entry про IG publish follow-ups #1-#4 closed.
- `project_ig_publish_fixes_followups_backlog.md` — вычеркнуть #1-#4 как closed (с SHA).
- `project_publisher_modularization_wip.md` — параграф «IG follow-ups #1-#4 — отгружено 2026-04-29».

## Commits

| Repo | Branch | SHA | Message |
|---|---|---|---|
| `delivery-contenthunter` (prod) | `main` | `21d56a2` | `fix(ig-publisher): rollout strict Reels-tile selector to 2 more bottomsheets` |
| `delivery-contenthunter` (prod) | `main` | `730b394` | `test(ig-publisher): unit tests for _verify_reels_camera_mode (5 modes)` |
| `delivery-contenthunter` (prod) | `main` | `80a8c96` | `test(ig-publisher): unit tests for ig_editor_timeout meta enrichment` |
| `delivery-contenthunter` (prod) | `main` | `82859a9` | `fix(ig-publisher): attribute-scoped markers in _verify_reels_camera_mode` |
| `contenthunter` | `fix/testbench-publisher-base-imports-20260427` | (pending) | `docs(plans+evidence): IG publish follow-ups #1-#4 — executed T0-T6` |

Все 4 prod commit'а auto-pushнуты hook'ом в `GenGo2/delivery-contenthunter`.
