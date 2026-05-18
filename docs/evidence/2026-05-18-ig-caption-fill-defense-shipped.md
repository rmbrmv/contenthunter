# IG caption-fill defense + observability — SHIPPED 2026-05-18

**WP:** [#81](https://openproject.contenthunter.ru/work_packages/81) (Ошибка)
**PR:** [#67](https://github.com/GenGo2/delivery-contenthunter/pull/67) — merged `b4215eb`
**Commit:** `75d2985` (source) → `b4215eb` (squash-merge)
**Branch:** `fix-ig-caption-fill-defense-20260518` (deleted on merge)
**Deploy:** `git pull` в `/root/.openclaw/workspace-genri/autowarm` + `sudo pm2 restart autowarm`

## Триаж (что искал)

`ig_caption_fill_failed` за 7д — 11 fails (15-18 мая), активная регрессия (5/24h на 2026-05-18 утром) после стабильного периода 12-14 мая (0 fails при 31-42 OK/день). Аккаунты разные, устройства разные → системная регрессия.

Топ-7 IG-fails / 7д (без `switch_failed_unspecified` = ADB preflight, по просьбе юзера игнор):

| error_code | 7д | 3д | 24ч |
|---|---|---|---|
| `ig_share_tap_no_progress` | 42 | 8 | 5 |
| `ig_gallery_no_video_candidate` | 21 | 0 | 0 |
| `date_mismatch` | 19 | 2 | 0 |
| `ig_target_not_in_picker` | 16 | 5 | 1 |
| **`ig_caption_fill_failed`** | **11** | **11** | **5** |
| `ig_app_launch_failed` | 10 | 3 | 0 |
| `ig_camera_open_failed` | 8 | 2 | 1 |

Выбран `ig_caption_fill_failed` — свежая регрессия, паттерн идентичен у всех, и фикс 2026-05-03 (PR #15 ADB_INPUT_B64) был про другой подсимптом (shell escape).

## Что нашли в S3 UI dumps (4 задачи: 6722, 6740, 6745, 6771)

Все 11 fails: `caption_focus_node_missing → 3× adb_text blind → caption_verify_failed → ig_caption_fill_failed`. К моменту `_focus_caption_input_surgical → dump_ui` экран **не caption**:

- **6722, 6745** — IG Reels Editor + новый туториал-overlay «Проведите по экрану вверх или вниз, чтобы установить размер для режима предпросмотра. Понятно»
- **6771** — голый IG Reels Editor (clips_action_bar, «Добавить аудио/Текст/Стикеры», кнопка «Далее»)
- **6740** — sub-screen «Аудитория» (Кто может видеть ваше видео Reels) — radio-list «Все/Близкие друзья», `'Аудитория'` matched в CAPTION_MARKERS как false positive

Старый код после `_focus_caption_input_surgical=False` всё равно лил `adb_text(caption)` 3 раза → текст в случайное `EditText` на wrong screen.

## Что сделано (PR #67, +60/−19 в publisher_instagram.py)

1. **Early-abort в `_fill_instagram_caption_and_publish`** (l. 3556+): если `focused=False` — emit `error` event `category=ig_caption_screen_not_reached`, `_save_debug_artifacts`, `return False`. Никаких `adb_text` вслепую.
2. **`IG_CAPTION_SCREEN_MARKERS`** вынесен в module-level constant (l. 367+) для unit-test coverage; **`'Аудитория'` удалена** (false positive для audience sub-screen).
3. **Editor loop** (l. 2547+): `_save_debug_ui_dump('caption_marker_detected_step{step}')` в момент detection — evidence для root-cause hunt (фрейм при detection может отличаться от того, что увидит focus_surgical через ~3-5s; гипотетический race condition).

**Это defense + observability fix, НЕ root cause.** Реальный mechanism wrong-screen jump (race condition / IG layout change / tutorial timing) станет видим только после ≥1 fail с новым `caption_marker_detected_step*` dump'ом.

## Tests

- 6 новых unit-тестов в `tests/test_caption_screen_not_reached_abort.py`:
  - `adb_text` НЕ вызывается при focus-fail
  - emit `error` event `category=ig_caption_screen_not_reached`
  - `_save_debug_artifacts('ig_caption_screen_not_reached')` вызывается
  - пустой caption + focus-fail → тоже abort
  - `IG_CAPTION_SCREEN_MARKERS` не содержит `'Аудитория'`
  - `IG_CAPTION_SCREEN_MARKERS` сохраняет `'Добавьте подпись'`
- 53/53 caption-related тестов pass
- Полный suite: 613 pass, 4 skip, 1 pre-existing fail (`test_publish_guard::test_guard_allow_on_match` — падает и на main, не связан)
- Codex review (`codex review -` через stdin): 0 P0/P1

## Что осталось

- [ ] **24h live verify**: SQL `SELECT error_code, COUNT(*) FROM publish_tasks WHERE platform='Instagram' AND status='failed' AND created_at > NOW() - INTERVAL '24 hours' GROUP BY 1 ORDER BY 2 DESC;` — ожидаем появление `ig_caption_screen_not_reached`. Если 11/3д распадётся на чистые wrong-screen aborts → defense работает.
- [ ] **Root-cause hunt**: собрать 2-3 fails с `caption_marker_detected_step*` dump'ом из новой observability, сравнить с `caption_verify_fail_0` dump'ом — это покажет, что меняется в UI между detection и focus_surgical. Возможные кандидаты: race с tutorial overlay, IG layout change, false positive другого marker'а.
- [ ] Если root cause найден → отдельный root-cause fix PR.

## Evidence

- S3 UI dumps: `s3://1cabe906ea6e-gengo/autowarm/ui_dumps/instagram/task{6722,6740,6745,6771}_publish_*_caption_verify_fail_*_adb_text_*.xml`
- Screenshots: `https://save.gengo.io/autowarm/screenshots/instagram/task{6722,6740,6745,6771}_publish_*_instagram_caption_fill_failed_*.png`
- Memory: `project_ig_caption_fill_2026_05_18_defense.md`
