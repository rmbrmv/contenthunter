# 2026-05-12 — Codex review scope расширен на backend Python diff'ы + retroactive review последних коммитов

## Why

Prod-инцидент 2026-05-12 (slot PATCH 500, `AmbiguousParameterError`) случился потому что backend Python diff'ы не прогонялись через Codex — только spec/plan для фичи Spec B шёл через Codex review. Реализация в commits `57d78a1` + `bab23cb` ушла в прод как есть.

После hotfix user попросил: (a) расширить scope правила Codex review, (b) прогнать Codex по последним коммитам ретроактивно.

## Расширение правила

Memory `feedback_codex_review_specs.md` обновлён: scope теперь включает любой backend Python diff с **SQL / async DB code / новым endpoint'ом**. Особое внимание: asyncpg type-inference quirks, SQL injection, transaction boundaries, missing await, race conditions.

Invocation для backend diff'ов: `codex review --commit <sha>` после коммита, перед deploy/pm restart.

## Retroactive Codex review

### 1. `57d78a1` — `feat(validator): pipeline_reversal service для slot move (Spec B D1)`

**Codex finding [P1]:**
> Cast keep_slot_id bind parameters in SQL predicates — pipeline_reversal.py:75-76.
> With asyncpg, the `:keep_slot_id IS NULL` / `IS DISTINCT FROM :keep_slot_id` pattern can be prepared as an untyped parameter and raise `AmbiguousParameterError`, especially when `keep_slot_id=None`; the same pattern appears in all three statements in this helper. Cast the bind explicitly, e.g. `CAST(:keep_slot_id AS integer) IS NULL`...

**Verdict:** **точно тот же баг что я нашёл вручную при дебаге prod 500.** Codex поймал бы его до deploy. Это прямое доказательство ценности расширенного scope.

### 2. `bab23cb` — `feat(validator-schedule): wire pipeline_reversal в 3 mutation endpoints`

**Codex finding [P2]:**
> Validate swap slot ids before locking — schedule.py:223.
> When `slot_a_id` or `slot_b_id` is omitted/null или provided with incompatible types, `sorted([slot_a_id, slot_b_id])` can raise before the endpoint returns a controlled 4xx response. Also, if both ids are equal, the new cancellation/notification path runs for a no-op swap and can cancel/notify the same content unnecessarily.

**Verdict:** валидный input-validation gap. Backlog для отдельного follow-up.

### 3. `2280edf` — `fix(pipeline_reversal): cast :keep_slot_id to integer for asyncpg` (мой hotfix)

**Codex sanity:**
> The production SQL fix appears complete: all three queries cast `:keep_slot_id` on both the `IS NULL` and `IS DISTINCT FROM` sides.

**Finding [P2]:**
> Gate live DB regression tests behind an integration marker — test_pipeline_reversal.py:20.
> These new tests unconditionally open `AsyncSessionLocal()`, so any normal `pytest` run in an environment without a configured/reachable PostgreSQL schema will now fail during test execution rather than simply running the existing mocked tests.

**Verdict:** валидный CI-concern, но **существующая конвенция в репо** — 5 других live-DB тестов (test_content_publish_response, test_schemes_summary_endpoint, test_account_packages_migration_smoke, test_schemes_deficits, test_accounts_endpoint) тоже без markers. Фиксить надо разом — backlog для отдельной сессии (введение `@pytest.mark.integration` + conftest skip-if-no-db).

## Backlog (от Codex 2026-05-12)

1. **Swap-slots input validation** (`schedule.py:223`) — проверять что `slot_a_id` + `slot_b_id` присутствуют, integer, и distinct до `sorted()` и acquire_slot_lock. P2.
2. **Live-DB tests integration marker** — ввести `@pytest.mark.integration` на все 7 live-DB тестов в validator backend + conftest skip-if-no-db. P2.

## Lessons

- Codex знает asyncpg type-inference quirks и ловит их при review реального кода. Spec/plan через Codex не достаточно — backend Python diff обязателен.
- Codex `--commit <sha>` сейчас ломается на bubblewrap sandbox; обход — stdin `(echo "<prompt>"; git show <sha>) | codex review -`. Memory `feedback_codex_sandbox_broken` обновить с этим примером.
