# Obstacle KB — W1 shipped, W2 partial — 2026-04-30 evidence

**Session:** brainstorm → spec → plan → execute через superpowers chain (using-superpowers → brainstorming → writing-plans → subagent-driven-development).

**Outcome:** W1 (foundation) полностью отгружено в testbench. W2 — A+B (signature extraction + KB API) выполнено на feature branch, не merged. Пауза для context refresh; W2.C/D/E + W3-W6 backlog.

## Phase W1 — shipped to `testbench` ✅

**Branch lifecycle:** `feature/obstacle-kb-w1` → merge `--no-ff` → `testbench`. Pushed.

**Commits (in testbench):**

| SHA | Message | Туда |
|---|---|---|
| `fe2ad8e` | feat(migrations): publisher_obstacles table — main pattern KB | testbench |
| `3486edc` | feat(migrations): publisher_obstacle_outcomes — outcome log + FK | testbench |
| `7838f9a` | feat(migrations): obstacle KB kill-switches in system_flags | testbench |
| `8f38b7b` | feat(migrations): rollback companions for obstacle KB schema (convention parity) | testbench |
| `0ac8deb` | feat(obstacle-kb): skeleton modules for W2/W3/W5 implementation | testbench |
| `3338313` | test(obstacle-kb): smoke test for kill-switches | testbench |
| `8479957` | merge: W1 obstacle KB foundation | testbench HEAD |

**Files (12 new, 0 modified):**
- 6 SQL files (3 forward + 3 rollback) в `migrations/`
- 5 skeleton .py: `obstacle_signatures.py` (30 LOC), `obstacle_kb.py` (41), `obstacle_actions.py` (17), `obstacle_promoter.py` (8), `obstacle_seed.py` (35)
- 1 test: `tests/test_obstacle_kill_switches.py` (40)

**DB applied (live `openclaw`):**
- Table `publisher_obstacles`: 29 cols, 3 indexes, 2 CHECK constraints
- Table `publisher_obstacle_outcomes`: 8 cols, FK CASCADE, 2 indexes, 1 CHECK
- 5 rows в `system_flags` с правильными default values (shadow mode + promoter/bot OFF)

**Tests:** 2 smoke tests passing (kill-switch existence + values).

**Behavioral change:** **0**. publisher.py не импортирует ни одного нового модуля. Risk = 0.

**Reviews:**
- W1.A: spec ✅, code quality ✅ (1 Minor — rollback parity, fixed inline `8f38b7b`)
- W1.B: combined ✅ (Minor: unused `datetime` import in skeleton — deferred to W2 cleanup, fixed since)
- W1.C + W1 phase audit: combined ✅ (no blockers)

## Phase W2 — partial, на `feature/obstacle-kb-w2` (not merged)

**Branch state:** 8 commits ahead of testbench, pushed to `origin/feature/obstacle-kb-w2`.

**Commits:**

| SHA | Message | Phase |
|---|---|---|
| `5478ca6` | feat(obstacle-sig): normalize_text helper + 9 unit tests | W2.A |
| `4b81860` | feat(obstacle-sig): extract_resource_ids + 4 tests | W2.A |
| `4734d2b` | feat(obstacle-sig): extract_key_texts + 5 tests | W2.A |
| `2e66c83` | feat(obstacle-sig): detect_dialog_indicator + 10 tests | W2.A |
| `bf4ab01` | feat(obstacle-sig): extract_signature compose + 6 hash determinism tests | W2.A |
| `e390596` | feat(obstacle-kb): lookup_obstacle + 3 tests + conftest conn fixture | W2.B |
| `dbac7cb` | feat(obstacle-kb): insert_or_increment with UPSERT + 2 tests | W2.B |
| `ca7d95c` | feat(obstacle-kb): record_outcome + recompute_confidence + 4 tests | W2.B |

**Files:**
- `obstacle_signatures.py`: 30 → 130 LOC (W2.A — 5 pure functions, all tested)
- `obstacle_kb.py`: 41 → 172 LOC (W2.B — 4 implemented + 1 still stub for W3)
- `tests/test_obstacle_signatures.py`: new, 163 LOC, 34 tests
- `tests/test_obstacle_kb.py`: new, 155 LOC, 9 tests
- `tests/conftest.py`: extended (28 LOC) — added `conn` fixture beside existing `parse_ui_dump`

**Tests passing total:** 45 (34 sig + 9 kb + 2 kill-switches).

**Reviews:**
- W2.A: spec ✅, code quality ✅ (Minor: signature_raw stores tuples as lists for JSON serialization — dual-representation, harmless)
- W2.B: spec ✅, code quality ✅ (Minor 1: defensive coding for unknown outcome value; Minor 2: cleanup-before-insert не во всех тестах; Minor 3: connection-per-call vs pool — все non-blocking)

## TDD discipline observed

Каждая task в W2 следовала pattern: failing test → minimum implementation → pass → atomic commit с exact message. Verified в каждом commit `git show --stat` — tests + impl в одном commit.

Subagent dispatches: 2 implementer + 2 combined reviewer per phase batch. Implementer prompts включали exact code blocks. Все subagents reported DONE без BLOCKED/NEEDS_CONTEXT.

## Что НЕ done (backlog)

**W2 остаток (~3-4 часа в свежей сессии):**
- W2.C: B1 seed (Plan Task 14) — `obstacle_seed.from_constants()` мигрирует ~8-10 hardcoded markers в DB как `stable`. Mechanical.
- W2.D: instrument refactors (Tasks 15-17) — добавить shadow lookup beside existing handlers в publisher_instagram/account_switcher/publisher_tiktok/publisher_youtube. **Medium-high risk** — production code paths.
- W2.E: deploy verify (Task 18) — run B1, watch shadow_match накопление, merge → testbench.

**W3-W6 — designed, not coded:**
- W3: Anthropic Sonnet 4.6 switch + ai_unstuck shim integration в shadow apply mode (Tasks 19-26)
- W4: Disable shadow mode (kill-switch flip) + 24h soak (Task 27)
- W5: Promoter T1/T2/T3 + bugs_catcher_bot extension + B2 mining (Tasks 28-31)
- W6: Admin UI obstacles.html + KPI panel (Tasks 32-35)

## Где возобновить

1. Memory: `project_publisher_obstacle_kb.md` (создан в этой же сессии).
2. Spec: `.ai-factory/plans/2026-04-30-publisher-obstacle-kb-design.md` (commit `fbb57ab5`).
3. Plan: `.ai-factory/plans/2026-04-30-publisher-obstacle-kb-implementation.md` (commit `5c1f4b77a`).
4. Worktree: `/home/claude-user/autowarm-testbench-obstacle-w2` (clean, на `feature/obstacle-kb-w2`).
5. Continue с W2.C (Task 14) через `superpowers:subagent-driven-development`.

## Lessons из этой сессии

1. **Plan placeholder catch-and-fix loop работал хорошо** — self-review нашёл 3 inconsistencies до user review.
2. **Subagent batching pragmatic:** объединение 5 связанных pure-function tasks в один implementer dispatch (W2.A) дало 5 atomic commits + 34 tests за один dispatch вместо 5 отдельных dispatches. Качество не пострадало.
3. **Reviewer note об unused datetime в skeleton оказался корректным предупреждением** — обнаружено в W2.A что `datetime` import был добавлен в skeleton "на будущее" но никогда не использовался. Reviewer отловил.
4. **Worktree-первый подход спас от конфликтов** — main `autowarm-testbench` workspace был на `feat/packages-modal-redesign-20260428` (чужой WIP). Worktree из `origin/testbench` дал чистый изолированный контекст без disturbance чужой работы.
5. **Reality-check после plan creation спасло от ложных предположений** — плановый "26 columns" в verification был typo (правильно 29). Implementer subagent corrected it; reviewer подтвердил.
