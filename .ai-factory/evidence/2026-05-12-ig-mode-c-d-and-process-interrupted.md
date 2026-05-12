# Evidence — IG Mode C+D hardening + process_interrupted error_code (2026-05-12)

**Сессия:** вечер 2026-05-12 после Codex/PR #36/#37/#38 (early afternoon).
**Trigger:** триаж IG fail distribution + drill-down NULL error_code.

---

## 1. Стартовая картина (18:00 UTC)

```
error_code                         | h24 | d7
ig_share_tap_no_progress           |  18 | 25
ig_gallery_no_video_candidate      |   9 | 31  ← target
ig_upload_confirmation_timeout     |   0 | 27
switch_failed_unspecified          |   4 | 16
ig_caption_fill_failed             |   0 | 13
ig_target_not_in_picker            |   3 | 11
date_mismatch                      |   9 |  9
(null)                             |   3 |  9  ← target
ig_editor_timeout                  |   0 |  9
ig_camera_open_failed              |   2 |  5
watchdog_subprocess_hang           |   0 |  2
```

Success rate IG за 24ч: 13 done / 48 failed (~21%) против baseline 55-60%.

---

## 2. PR #41 — IG gallery Mode C+D hardening

**Merge:** `1f5be54` 2026-05-12 18:05 UTC, GenGo2/delivery-contenthunter.
**Spec:** `.ai-factory/specs/ig-gallery-mode-c-d-hardening-20260512.md`.

### Discovery

9 IG fails / 24ч с `error_code='ig_gallery_no_video_candidate'` декомпозированы через screenshot+events на 4 distinct visual mode'а:

| Mode | Tasks | Visual |
|---|---|---|
| **D — Play Store overlay** | 5031, 5026, 4937, 4857 (4/9) | TikTok Studio listing (Установить, 4,7★, bottom-nav Игры/Приложения/Поиск/Книги) |
| **F — IG Story mode** | 4869, 4930, 4861 (3/9) | Stories preview + emoji-row + «Задайте вопрос…» sticker |
| **E — Editor с нашим клипом** | 4932 (1/9) | Reels editor preloaded, Property «Мечта №24», 0:03/0:10 |
| **G — Editor с чужим клипом** | 4938 (1/9) | estate_m.ivanov editor preloaded мужчина 0:09/0:57 |

Dump 5031 `after step4_initial` (12:26:04) показал `clips_template_browser_fragment_holder` + `clips_action_bar_*` — мы в Templates browser. Screenshot post-task (12:27:09, через 65 sec) показал Play Store. Cascading drift через 5 retry blind-tap'ов в Шаг 5.

### Root cause

`publisher_instagram.py:1596-1605` (Шаг 4) — `tap_element(['Галерея','Gallery','галерея'])` → fallback hardcoded `adb_tap(95, 1995)`. `:1629` (Шаг 5 retry) — повтор blind-tap'а. Сумма: до 6 blind-tap'ов / task, каждый промах hijack'ает foreground на Templates / Story / Play Store.

### Fix

- **+4 module-level helpers:** `_ig_find_gallery_anchor_coord` (bounds lookup `gallery_grid_camera_item_icon` > `gallery_destination_item` > tray), `_ig_collect_state_markers`, `_ig_classify_pre_picker_state` (5-mode decision tree), `_ig_resource_id_selected`.
- **+1 instance method:** `InstagramMixin._current_foreground_package` (dumpsys topResumedActivity).
- **Шаг 4:** blind-tap → anchor lookup + structured fail-fast `ig_gallery_button_not_found`.
- **Pre-Шаг-5 state guard:** distinct error_code на mode (`ig_external_app_foreground`, `ig_camera_mode_drift_to_templates`, `ig_camera_mode_drift_to_story`, `ig_editor_preloaded_pre_picker`).
- **Шаг 5 break-loop:** substring text-match → resource-id `gallery_grid_item_thumbnail`.
- **Шаг 5 retry blind-tap** удалён.

### Tests

29 unit tests в `tests/test_ig_gallery_mode_c_d_hardening.py`. 79 cross-suite IG-helper tests green. Pre-existing fails (TT canonical, YT switcher, publish_guard, orchestrator KeyError, `test_reopen_via_home_taps_plus_then_reels_on_success_path`) confirmed на baseline через `git stash` — вне scope.

### Codex review

- Spec round 1: 0 actionable issues
- Impl round 1: 2 P2 (`'unknown'` foreground → IG default; `gallery_destination_item` overlap с pre-picker anchor) → fixed → round 2: 0 issues

---

## 3. PR #42 — process_interrupted error_code coverage

**Merge:** `66c70b4` 2026-05-12 18:22 UTC, GenGo2/delivery-contenthunter.

### Discovery

3 IG fails / 24ч с `error_code IS NULL`:

| Task | Account | Pi | Last error event |
|---|---|---|---|
| 5037 | clickpay_under | 9 | `category=process_interrupted` / `KeyboardInterrupt` |
| 5036 | just_clickpay | 9 | `category=process_interrupted` / `KeyboardInterrupt` |
| 4911 | gengo_sales | 3 | `category=process_interrupted` / `KeyboardInterrupt` |

ВСЕ имели structured event от Layer 3 BaseException catch (commit `69cf64b` 2026-05-04).

### Root cause

`publisher.py:_mark_task_failed_on_exit` UPDATE'ил `status='failed'` + log + events, но **НЕ `error_code`**. Layer 1 watchdog (server.js) тоже не fire'ил — status уже moved к 'failed', его overwrite-NULL-with-watchdog_subprocess_hang branch не активировался.

### Fix

1 строка SQL: `error_code=COALESCE(NULLIF(error_code,''), %s)` с `category` positional param. NULLIF guard защищает уже-выставленный код от triage.

### Tests

3 regression tests в `tests/test_process_interrupted_error_code.py` + 4 existing BaseException tests green. Codex review impl round 1: 0 P1.

---

## 4. Smoke validate PR #41

Re-queue через `UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE id IN (2021, 2255)`:

| New pt | Account | Pi | Status | error_code |
|---|---|---|---|---|
| 5126 | estate_m.ivanov | 5 | failed | `switch_failed_unspecified` (fail на switch ДО Шаг 4, не моя зона — PR #39+#40 territory) |
| 5127 | clickpay_under | 9 | failed | `date_mismatch` (scheduled_at 11:10 МСК > 7ч назад, slot expired — feature, не bug) |

Helper'ы PR #41 не активированы (fail происходит раньше). **Это not regression** — путь до Шаг 4/5 не достигнут. Real evidence ждать со следующим IG slot ~01:50 МСК (через ~4ч).

---

## 5. Deadlines

- **2026-05-13 18:22 UTC** — 24h verify PR #42 (NULL error_code IG count = 0; `process_interrupted` появляется если SIGINT случается)
- **2026-05-19 18:05 UTC** — 7d verify PR #41 (distribution 5 new error_code per mode; `ig_gallery_no_video_candidate` падает до ~0-2)

---

## 6. Закрытые memory pointers

- [[project_ig_gallery_mode_c_d_shipped_2026_05_12]] — PR #41 (новое)
- [[project_publisher_process_interrupted_error_code_2026_05_12]] — PR #42 (новое)
- [[project_ig_gallery_no_video_2026_05_10]] — Mode B "closed pending re-occurrence" → Mode D re-confirmed in PR #41

## 7. Open backlog (IG)

- Minor follow-ups #5-#8 от `project_ig_publish_fixes_followups_backlog` (observability noise, не блокеры)
- `project_ig_failing_accounts_audit_backlog` — 8 acc с 4-8 fail/7д, account-side discovery
- 24h side-effect monitoring PR #41 + #42

---

## 8. Parallel sessions (no conflict)

В момент работы две другие активные сессии:
- `feat-yt-cross-project-leak-fix-20260512` (YT)
- `fix/tt-switch-categories-20260512` (TT)

Worktree isolation per [[feedback_parallel_claude_sessions]]. Все 3 ветки рассинхронизированы по платформам, конфликтов не было.
