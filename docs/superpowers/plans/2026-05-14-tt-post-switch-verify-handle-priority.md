# TT post-switch verify — `@handle` priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `tt_post_switch_verify_unrecoverable` (16 TikTok publish failures on 2026-05-14) — post-switch verify must read the `@handle`, not the profile display name or a badge counter rendered above it.

**Architecture:** Single-function change in `account_switcher.py`. `get_current_account_from_profile` currently returns the topmost `_looks_like_username` token; the fix adds a leading sort key `is_bare` (0 for `@`-prefixed tokens, 1 otherwise) so `@`-tokens win. When no `@`-token exists (IG/YT headers) the sort degenerates to the prior `(y_top, norm)` order — behaviour unchanged.

**Tech Stack:** Python 3, pytest. Code repo: `GenGo2/delivery-contenthunter` (the "autowarm" repo). Spec: `docs/superpowers/specs/2026-05-14-tt-post-switch-verify-handle-priority-design.md`. Triage: `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md`. OpenProject: WP #67.

---

## Environment (already set up)

- **Code worktree:** `/home/claude-user/autowarm-wt-tt-verify-handle-20260514`, branch `fix/tt-post-switch-verify-handle-20260514` (off `origin/main` `5372d18`). Run all code/test/git commands here.
- **Post-commit hook:** the autowarm repo auto-pushes the *current branch* on every commit (`git push origin <branch>`). This is expected — it puts the feature branch on GitHub for the PR. It does NOT push `main`.
- **Fixtures already staged** (untracked, real production dumps — added by the planning step): `tests/fixtures/tt_post_switch_5817_relism_e.xml`, `tests/fixtures/tt_post_switch_5593_mariaforsale.xml`, `tests/fixtures/tt_post_switch_5799_relis_unpack.xml`. They are committed in Task 2.
- **Baseline (verified):** `pytest tests/test_account_switcher.py tests/test_post_switch_renav.py tests/test_switcher_read_only.py tests/test_yt_post_switch_verify.py` → **83 passed, 1 failed**. The 1 failure — `tests/test_switcher_read_only.py::test_yt_happy_path_returns_accounts` — is **pre-existing on `origin/main`** (documented in `docs/evidence/2026-05-14-tt-account-switcher-settings-nested-shipped.md`), not a regression. Do not try to fix it.
- **Docs worktree** (this plan, evidence updates): `/home/claude-user/contenthunter/.claude/worktrees/tt-publish-triage-2026-05-14`, branch `worktree-tt-publish-triage-2026-05-14` (repo `contenthunter`).

## File Structure

| File | Repo | Responsibility | Action |
|---|---|---|---|
| `account_switcher.py` | autowarm | `get_current_account_from_profile` token-selection logic | Modify (lines ~566–588) |
| `tests/test_account_switcher.py` | autowarm | Unit tests for the function | Modify (add 5 tests) |
| `tests/fixtures/tt_post_switch_5817_relism_e.xml` | autowarm | Real dump: display name above `@handle` | Already present → commit |
| `tests/fixtures/tt_post_switch_5593_mariaforsale.xml` | autowarm | Real dump: badge counter above `@handle` | Already present → commit |
| `tests/fixtures/tt_post_switch_5799_relis_unpack.xml` | autowarm | Real dump: display name above `@handle` | Already present → commit |
| `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md` | contenthunter | Triage evidence — close-out note | Modify (Task 7) |

---

### Task 1: Failing tests for `@handle` priority

**Files:**
- Modify: `tests/test_account_switcher.py` (insert after `test_get_current_ignores_elements_below_header`, before the `# ─── find_account_in_list ───` separator — around line 75)
- Fixtures: `tests/fixtures/tt_post_switch_5817_relism_e.xml`, `tests/fixtures/tt_post_switch_5593_mariaforsale.xml`, `tests/fixtures/tt_post_switch_5799_relis_unpack.xml` (already present in the worktree, untracked)

- [ ] **Step 1: Add the five tests**

Insert into `tests/test_account_switcher.py` after `test_get_current_ignores_elements_below_header`:

```python
# ─── WP #67: @handle priority over display name / badge counter ──────────────
# Реальные `tt_4_target_profile_renav` дампы упавших задач 2026-05-14: на экране
# профиля TikTok display name (и числовые badge'и) рендерятся ВЫШЕ @handle, а
# _looks_like_username принимает их за username. Verify обязан вернуть @handle.
def test_get_current_prefers_at_handle_over_display_name_5817():
    """task 5817: display name «Unpacking Girl» (y=503) выше @relism_e (y=574)."""
    elements = parse_ui_dump(_load('tt_post_switch_5817_relism_e.xml'))
    assert get_current_account_from_profile(elements, header_y_max=700) == 'relism_e'


def test_get_current_prefers_at_handle_over_badge_5593():
    """task 5593: числовой badge «11» (y=164) выше @mariaforsale (y=574)."""
    elements = parse_ui_dump(_load('tt_post_switch_5593_mariaforsale.xml'))
    assert get_current_account_from_profile(elements, header_y_max=700) == 'mariaforsale'


def test_get_current_prefers_at_handle_over_display_name_5799():
    """task 5799: display name «Relisme Unpack» (y=503) выше @relis_unpack (y=574)."""
    elements = parse_ui_dump(_load('tt_post_switch_5799_relis_unpack.xml'))
    assert get_current_account_from_profile(elements, header_y_max=700) == 'relis_unpack'


def test_get_current_at_handle_priority_beats_y_top():
    """@-токен ниже bare-токена в полосе всё равно выигрывает — приоритет
    префикса важнее вертикальной позиции."""
    xml = '''<?xml version="1.0"?><hierarchy rotation="0">
      <node text="Unpacking Girl" content-desc="" clickable="false" bounds="[200,100][600,160]"/>
      <node text="@relism_e" content-desc="" clickable="true" bounds="[200,300][500,360]"/>
    </hierarchy>'''
    assert get_current_account_from_profile(parse_ui_dump(xml), header_y_max=700) == 'relism_e'


def test_get_current_no_at_token_keeps_topmost_bare():
    """Регресс-гард для IG/YT: без @-токенов поведение прежнее — верхний
    bare-токен по y_top."""
    xml = '''<?xml version="1.0"?><hierarchy rotation="0">
      <node text="acme_brand" content-desc="" clickable="false" bounds="[50,120][400,180]"/>
      <node text="other_user" content-desc="" clickable="false" bounds="[50,400][400,460]"/>
    </hierarchy>'''
    assert get_current_account_from_profile(parse_ui_dump(xml), header_y_max=700) == 'acme_brand'
```

- [ ] **Step 2: Run the new tests to verify they fail (TDD red)**

Run: `cd /home/claude-user/autowarm-wt-tt-verify-handle-20260514 && python3 -m pytest tests/test_account_switcher.py -k "prefers_at_handle or at_handle_priority or no_at_token_keeps" -v`

Expected: **4 FAILED, 1 PASSED**.
- `test_get_current_prefers_at_handle_over_display_name_5817` → FAIL (current code returns `'girl'`)
- `test_get_current_prefers_at_handle_over_badge_5593` → FAIL (returns `'11'`)
- `test_get_current_prefers_at_handle_over_display_name_5799` → FAIL (returns `'relisme'`)
- `test_get_current_at_handle_priority_beats_y_top` → FAIL (returns `'girl'`)
- `test_get_current_no_at_token_keeps_topmost_bare` → PASS (regression guard — current code already satisfies it; this is intentional)

---

### Task 2: Implement `@handle` priority

**Files:**
- Modify: `account_switcher.py` — function `get_current_account_from_profile` (lines ~566–588)

- [ ] **Step 1: Replace the function body**

Find this exact current code in `account_switcher.py`:

```python
def get_current_account_from_profile(elements: list,
                                     header_y_max: int = 260) -> Optional[str]:
    """Извлечь username текущего аккаунта из header'а экрана профиля.

    На экране профиля имя активного аккаунта отображается в верхнем title bar
    (в пределах первых ~260px по вертикали). Берём первый элемент c непустым
    text/content-desc в этой полосе, который выглядит как username.
    """
    candidates = []
    for el in elements:
        y_top = el.bounds[1]
        if y_top > header_y_max:
            continue
        for raw in (el.text, el.content_desc):
            if not raw:
                continue
            for tok in re.split(r'\s+|\n', raw):
                if _looks_like_username(tok):
                    candidates.append((y_top, AccountSwitcher._normalize_username(tok)))
    if not candidates:
        return None
    candidates.sort()  # сверху вниз
    return candidates[0][1]
```

Replace it with:

```python
def get_current_account_from_profile(elements: list,
                                     header_y_max: int = 260) -> Optional[str]:
    """Извлечь username текущего аккаунта из header'а экрана профиля.

    На экране профиля имя активного аккаунта отображается в верхнем title bar
    (в пределах первых ~260px по вертикали). Берём первый элемент c непустым
    text/content-desc в этой полосе, который выглядит как username.

    Приоритет `@`-префиксных токенов (WP #67): на экране профиля TikTok
    отображаемое имя профиля рендерится ВЫШЕ `@handle`, а `_looks_like_username`
    принимает слова из display name (и числовые badge'и в топ-баре) за username.
    Настоящий handle идёт с префиксом `@` — поэтому `@`-токены в полосе
    приоритетнее bare-токенов. Если `@`-токенов нет (IG/YT — у них в header'е
    `@` обычно отсутствует), сортировка вырождается в прежнюю `(y_top, norm)` —
    поведение не меняется.
    """
    candidates = []
    for el in elements:
        y_top = el.bounds[1]
        if y_top > header_y_max:
            continue
        for raw in (el.text, el.content_desc):
            if not raw:
                continue
            for tok in re.split(r'\s+|\n', raw):
                if _looks_like_username(tok):
                    is_bare = 0 if tok.lstrip().startswith('@') else 1
                    candidates.append(
                        (is_bare, y_top, AccountSwitcher._normalize_username(tok))
                    )
    if not candidates:
        return None
    candidates.sort()  # @-токены вперёд, внутри группы — сверху вниз
    return candidates[0][2]
```

- [ ] **Step 2: Run the new tests to verify they pass (TDD green)**

Run: `cd /home/claude-user/autowarm-wt-tt-verify-handle-20260514 && python3 -m pytest tests/test_account_switcher.py -k "prefers_at_handle or at_handle_priority or no_at_token_keeps" -v`

Expected: **5 PASSED**.

---

### Task 3: Regression + commit

**Files:** none modified — verification and commit only.

- [ ] **Step 1: Run the full switcher regression suite**

Run: `cd /home/claude-user/autowarm-wt-tt-verify-handle-20260514 && python3 -m pytest tests/test_account_switcher.py tests/test_post_switch_renav.py tests/test_switcher_read_only.py tests/test_yt_post_switch_verify.py -q`

Expected: **88 passed, 1 failed**. The 88 = 83 baseline + 5 new. The 1 failure must be exactly `tests/test_switcher_read_only.py::test_yt_happy_path_returns_accounts` (pre-existing on `origin/main`). If any *other* test fails, STOP — that is a regression; investigate before continuing.

- [ ] **Step 2: Run the wider test suite as a sanity check**

Run: `cd /home/claude-user/autowarm-wt-tt-verify-handle-20260514 && python3 -m pytest -q 2>&1 | tail -15`

Expected: all green except the 2 known pre-existing failures on `origin/main`: `test_switcher_read_only.py::test_yt_happy_path_returns_accounts` and `tests/test_publish_guard.py::test_guard_skipped_when_tiktok_seeded_but_tiktok_column_null`. If any other test fails, STOP and investigate.

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-wt-tt-verify-handle-20260514
git add account_switcher.py tests/test_account_switcher.py \
        tests/fixtures/tt_post_switch_5817_relism_e.xml \
        tests/fixtures/tt_post_switch_5593_mariaforsale.xml \
        tests/fixtures/tt_post_switch_5799_relis_unpack.xml
git commit -m "$(cat <<'EOF'
fix(tt-switcher): prefer @handle over display name in post-switch verify (WP #67)

get_current_account_from_profile returned the topmost _looks_like_username
token. On the TikTok profile screen the display name (and numeric badge
counters) render ABOVE the @handle and pass the loose username heuristic, so
post-switch verify read e.g. "girl"/"11"/"relisme" instead of the real handle
and reported a false mismatch — even though the account switch succeeded.
Closes tt_post_switch_verify_unrecoverable: 16 TikTok publish failures on
2026-05-14, 16 devices.

Fix: add a leading sort key is_bare (0 for @-prefixed tokens, 1 otherwise) so
@-tokens win. With no @-token (IG/YT headers) the sort degenerates to the
prior (y_top, norm) order — behaviour unchanged. New tests use real failing
production dumps (tasks 5817/5593/5799) + synthetic priority/invariance cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

The post-commit hook pushes `fix/tt-post-switch-verify-handle-20260514` to GitHub. Confirm the hook printed `[git-hook] ✅ Pushed`.

---

### Task 4: Codex review

**Files:** none — review only, fixes (if any) folded into a follow-up commit.

- [ ] **Step 1: Run codex review on the diff**

Run: `cd /home/claude-user/autowarm-wt-tt-verify-handle-20260514 && git diff origin/main...HEAD -- account_switcher.py tests/test_account_switcher.py | ~/.local/bin/codex review -`

(The `git diff | codex review -` form is required — `--base main` is broken in this env, per memory `feedback_codex_sandbox_broken`. The bubblewrap warning is benign.)

- [ ] **Step 2: Apply P1/P2 feedback, if any**

If codex reports P1 or P2 issues: apply the fixes to `account_switcher.py` / `tests/test_account_switcher.py`, re-run Task 3 Step 1 (regression), commit with message `fix(tt-switcher): codex review round N — <summary>` (Co-Authored-By footer), and re-run Step 1 of this task. Repeat until codex reports 0 P1/P2. If codex reports 0 P1/P2 immediately, record that and proceed.

---

### Task 5: Pull request

**Files:** none.

- [ ] **Step 1: Open the PR**

```bash
cd /home/claude-user/autowarm-wt-tt-verify-handle-20260514
gh pr create --repo GenGo2/delivery-contenthunter \
  --base main --head fix/tt-post-switch-verify-handle-20260514 \
  --title "fix(tt-switcher): prefer @handle over display name in post-switch verify (WP #67)" \
  --body "$(cat <<'EOF'
## Что было не так

`tt_post_switch_verify_unrecoverable` — 16 упавших задач TikTok-выкладки за 2026-05-14 (16 устройств, raspberry 1/2/7/9/10, весь день 04:50–13:41). Крупнейший незатикеченный баг дня.

После выбора аккаунта в свитчере `get_current_account_from_profile` возвращала верхний токен, прошедший `_looks_like_username`. На экране профиля TikTok отображаемое имя профиля (и числовые badge-счётчики в топ-баре) рендерятся ВЫШЕ `@handle` и проходят слишком широкую эвристику — verify читал «girl» / «11» / «relisme» вместо настоящего хэндла и сообщал ложный mismatch. Свитч при этом физически проходил (TikTok ставил аккаунту галочку), но publish не шёл дальше свитчера.

## Что сделано

`get_current_account_from_profile`: ключ сортировки кандидатов получил ведущий разряд `is_bare` (0 для `@`-префиксных токенов, 1 для bare) — `@`-токены выигрывают. При отсутствии `@`-токенов (IG/YT) сортировка вырождается в прежнюю `(y_top, norm)` — поведение не меняется. `_looks_like_username` и `header_y_max` не трогали.

Новые тесты — на реальных упавших дампах задач 5817 / 5593 / 5799 + синтетические кейсы приоритета и IG-инвариантности.

## Проверка

- `tests/test_account_switcher.py` + `test_post_switch_renav.py` + `test_switcher_read_only.py` + `test_yt_post_switch_verify.py`: 88 passed, 1 failed (`test_yt_happy_path_returns_accounts` — pre-existing на `origin/main`, не регрессия).
- Codex review диффа: 0 P1/P2.
- Триаж: `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md` (репозиторий contenthunter).
- Дизайн: `docs/superpowers/specs/2026-05-14-tt-post-switch-verify-handle-priority-design.md`.

OpenProject: WP #67.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Squash-merge the PR**

Run: `gh pr merge --repo GenGo2/delivery-contenthunter --squash --delete-branch fix/tt-post-switch-verify-handle-20260514`

Record the squash commit SHA on `main` (printed by `gh pr merge`, or via `gh pr view <n> --json mergeCommit`).

---

### Task 6: Prod deploy + live smoke

**Files:** none — operations on the prod checkout `/root/.openclaw/workspace-genri/autowarm`.

- [ ] **Step 1: Fast-forward the prod checkout**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git rev-parse --abbrev-ref HEAD          # MUST print "main" — if not, STOP (do not deploy onto a foreign branch)
git fetch origin -q
git merge --ff-only origin/main          # fast-forward only — never force, never merge-commit
git log --oneline -1                     # confirm HEAD is the PR's squash commit
```

If `git merge --ff-only` fails (prod checkout has diverged), STOP and report — do not force.

- [ ] **Step 2: Restart the PM2 service and confirm no path-drift**

```bash
pm2 restart autowarm
pm2 describe autowarm | grep -E "exec cwd|status"
```

Expected: `exec cwd` is `/root/.openclaw/workspace-genri/autowarm` (not `/home/claude-user/autowarm-testbench`), status `online`. If `exec cwd` is wrong, `pm2 delete autowarm && pm2 start <ecosystem config>` from the prod dir (memory `feedback_pm2_dump_path_drift`).

- [ ] **Step 3: Re-queue one of the 16 failed tasks for a live smoke**

Pick task `5817` (`relism_e`) — it has the clearest evidence. Find its `publish_queue` row and reset it:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
  "SELECT id, status, publish_task_id FROM publish_queue WHERE publish_task_id = 5817;"
```

Then, for the returned `publish_queue.id` (call it `<QID>`):

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
  "UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE id=<QID>;"
```

`dispatchPublishQueue` (runs every 5 min) will create a fresh `publish_task`. Do NOT touch `publish_tasks` directly (memory `reference_publish_requeue_path`).

- [ ] **Step 4: Verify the smoke result**

Wait for the new task to run (poll every ~3–5 min). Find it:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c \
  "SELECT id, status, error_code, created_at FROM publish_tasks
   WHERE account='relism_e' AND platform='TikTok' AND created_at > now() - interval '30 min'
   ORDER BY id DESC LIMIT 1;"
```

Success criterion for *this fix*: the new task's events show post-switch verify resolved — i.e. a `tt_post_switch_recovered_via_renav` / `match` event, OR the task progressed past the switcher into the publish phase (any non-switcher step or `done`). It must NOT fail with `tt_post_switch_verify_unrecoverable`. Pull the events to confirm:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tA -c \
  "SELECT jsonb_pretty(events) FROM publish_tasks WHERE id=<NEW_TASK_ID>;" | grep -iE "verify|renav|post_switch|tt_4|fail"
```

If the new task still fails at `tt_post_switch_verify_unrecoverable`, the fix did not hold on the live device — STOP, capture the new `tt_4_target_profile*` dump, and re-open analysis. (A failure for a *different* reason — e.g. `tt_upload_confirmation_timeout` — means the switcher verify is fixed and the task hit a separate, known bug; that counts as this fix succeeding.)

---

### Task 7: Close out — WP #67 + evidence doc

**Files:**
- Modify: `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md` (repo `contenthunter`, docs worktree `/home/claude-user/contenthunter/.claude/worktrees/tt-publish-triage-2026-05-14`)

- [ ] **Step 1: Append a close-out section to the evidence doc**

In `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md`, after the `## Запросы (воспроизводимость)` section, append:

```markdown

## SHIPPED 2026-05-14

- **PR:** GenGo2/delivery-contenthunter #<PR_NUMBER> — squash `<SQUASH_SHA>`.
- **Fix:** `get_current_account_from_profile` — `@handle`-priority sort key. `_looks_like_username` / `header_y_max` untouched.
- **Tests:** switcher suite 88 passed, 1 pre-existing fail. Codex review: 0 P1/P2.
- **Deploy:** prod checkout fast-forwarded to `<SQUASH_SHA>`, PM2 `autowarm` restarted (`exec cwd` confirmed).
- **Live smoke:** task `<NEW_TASK_ID>` (`relism_e`) — <result: post-switch verify resolved / progressed past switcher>.
- **24h soak:** `tt_post_switch_verify_unrecoverable` 16/24h → expect ~0 (deadline ~2026-05-15 ~15:00 UTC).
```

Fill in `<PR_NUMBER>`, `<SQUASH_SHA>`, `<NEW_TASK_ID>` and the smoke result from Tasks 5–6.

- [ ] **Step 2: Commit the evidence doc update**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/tt-publish-triage-2026-05-14
git add docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md
git commit -m "$(cat <<'EOF'
docs(evidence): TT post-switch verify @handle-priority — SHIPPED 2026-05-14

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Update OpenProject WP #67**

Post a house-style comment (Что было не так → Что сделано → Что осталось, plain language, no footer) and move the status to "В тестировании" (id 9):

```bash
set -a; . ~/secrets/openproject.env; set +a
# fetch current lockVersion
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" "$OPENPROJECT_URL/api/v3/work_packages/67" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["lockVersion"])'
# post comment (replace <PR_NUMBER>, <NEW_TASK_ID>, smoke result)
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" -H "Content-Type: application/json" \
  -X POST "$OPENPROJECT_URL/api/v3/work_packages/67/activities" \
  --data '{"comment":{"raw":"**Что было не так:** проверка после переключения аккаунта в TikTok читала с экрана не @-логин, а отображаемое имя профиля (или число-счётчик из верхней панели) — они нарисованы выше @-логина. Из-за этого 16 успешных переключений за день были отбракованы, публикация не шла.\n\n**Что сделано:** проверка теперь отдаёт приоритет тексту с «@» — настоящему логину. Для Instagram и YouTube, где «@» в шапке нет, поведение не изменилось. PR GenGo2/delivery-contenthunter #<PR_NUMBER>, выкачено на прод. Тесты на реальных экранах 3 упавших задач — зелёные.\n\n**Что осталось:** живой смоук на ре-выкладке (задача <NEW_TASK_ID>) — <результат>. Финальное подтверждение — суточная сводка: 16 падений/день → ожидаем ~0 к ~2026-05-15."}}'
# move status to "В тестировании" (id 9) — use the lockVersion from above
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" -H "Content-Type: application/json" \
  -X PATCH "$OPENPROJECT_URL/api/v3/work_packages/67" \
  --data '{"lockVersion":<LOCK_VERSION>,"_links":{"status":{"href":"/api/v3/statuses/9"}}}'
```

---

## Self-Review

**Spec coverage:**
- Problem / root cause → Tasks 1–2 (failing tests on real dumps + fix). ✓
- Solution (`is_bare` sort key) → Task 2 Step 1, exact code. ✓
- IG/YT safety → Task 1 `test_get_current_no_at_token_keeps_topmost_bare` + Task 3 regression. ✓
- Testing section (3 real-dump tests + IG-invariance + priority + regression) → Task 1 + Task 3. ✓
- Rollout (TDD → codex → PR → prod deploy → live smoke → WP/evidence) → Tasks 3–7. ✓
- Not-in-scope items → not touched (no task modifies `_looks_like_username` or `header_y_max`). ✓

**Placeholder scan:** Code steps show full code. Operational placeholders (`<QID>`, `<PR_NUMBER>`, `<SQUASH_SHA>`, `<NEW_TASK_ID>`, `<LOCK_VERSION>`) are runtime values produced by earlier steps, not unspecified design — each is explicitly sourced. No TBD/TODO.

**Type consistency:** `get_current_account_from_profile(elements, header_y_max=...)` signature unchanged across all tasks. `is_bare` introduced and used only within Task 2. `_load`, `parse_ui_dump` used per the existing test-file conventions. Fixture filenames identical in Task 1, Task 3 commit, and File Structure table.
