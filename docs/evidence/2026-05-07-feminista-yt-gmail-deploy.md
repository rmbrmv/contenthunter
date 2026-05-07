# Feminista YT-gmail — deploy evidence (2026-05-07)

## Scope
Sub-project B (YT-only). IG/TT failures — отдельные sub-tasks.

## Артефакты
- Spec: `docs/superpowers/specs/2026-05-07-feminista-yt-gmail-design.md`
- Plan: `docs/superpowers/plans/2026-05-07-feminista-yt-gmail-plan.md`
- Branch: `feature/feminista-yt-gmail-2026-05-07` (in `autowarm-testbench`)
- Worktree: `/home/claude-user/work-trees/feminista-yt-gmail`
- Repo: `GenGo2/delivery-contenthunter` (testbench → main)

## Commits (19)
```
4dc4ca8 feat(packages-ui): gmail render+edit on YT account rows with clear-protection
ca2321d feat(packages-ui): gmail input in add-account row (required for YT)
1c55406 feat(packages): GET endpoints return gmail field
ddda174 fix(packages): add console.log on PUT /accounts for parity with POST
2101718 feat(packages): PUT /accounts accepts gmail with clear-to-NULL protection
dabd7f6 feat(packages): POST /accounts validates+persists gmail (YT required)
200873e fix(revision): use pairs directly instead of reconstructing from result
1e3859e feat(revision): backfill NULL gmail for registered YT accounts on device
c4d2d97 fix(revision): docstring update + gmails_pairs in result initializer
d414b32 refactor(revision): discover_gmails via yt_gmail_probe + backward-compat result.gmails
8b9f149 fix(yt-gmail): consolidate adb_shell + deleted_pairs returns gmail
6b8378b fix(yt-gmail): restore deleted-channel auto-deactivation in backfill
c0b612e refactor(yt-gmail): migrate backfill_yt_gmails.py onto shared probe module
5215ca5 fix(yt-gmail): catch TimeoutExpired in adb wrappers + makedirs in try
0372125 feat(yt-gmail): add probe_yt_gmails_live ADB wrapper (thin)
0099c8f fix(yt-gmail): empty-handle guard + docstring + test import position
e103152 feat(yt-gmail): add match_gmail_to_handle with ambiguity handling
70baca9 fix(yt-gmail): NODE_RE order-independent + GMAIL_RE narrowed to @gmail.com
34329b2 feat(yt-gmail): add yt_gmail_probe.extract_yt_picker_pairs
```

## File diff stats
```
 account_revision.py                              |  97 +++-
 backfill_yt_gmails.py                            | 660 +++--------------------
 public/index.html                                |  46 +-
 server.js                                        |  67 ++-
 tests/fixtures/yt_picker_attr_order_reversed.xml |   5 +
 tests/fixtures/yt_picker_empty.xml               |   4 +
 tests/fixtures/yt_picker_two_rows.xml            |   6 +
 tests/fixtures/yt_picker_with_deleted.xml        |   5 +
 tests/test_yt_gmail_probe.py                     |  92 ++++
 yt_gmail_probe.py                                | 531 ++++++++++++++++++
 10 files changed, 873 insertions(+), 640 deletions(-)
```

`backfill_yt_gmails.py` сократился на 660 строк (вынесли parsing/nav в `yt_gmail_probe.py`); чистый прирост код-базы — 233 строки.

## Pre-deploy smoke
- `tests/test_yt_gmail_probe.py`: **11/11 passed** (0.05s)
- Полный `tests/`: 753 passed, 12 failed, 4 skipped — все 12 failures pre-existing (`test_testbench_orchestrator.py`, не связано с этим спеком; verified via stash check в Task 5).
- `node --check server.js`: **syntax-ok**
- HTML grep `new-acc-gmail|acc-gmail-input|acc-gmail-display` в `public/index.html`: **8 references** (new-row input + 2 lookups; existing-row input + edit-toggle + display span + clear-protection check + ...).

## Deploy steps (run by controller / operator)

1. **Merge feature branch → main** (см. `superpowers:finishing-a-development-branch`).
2. **Push to `GenGo2/delivery-contenthunter`** origin/main.
3. **Sync prod cwd**: `cd /root/.openclaw/workspace-genri/autowarm/ && sudo git pull origin main`.
4. **`sudo pm2 reload autowarm`** — server.js забирает новые endpoints. Frontend `public/index.html` отдаётся либо самим autowarm, либо nginx'ом — проверить `pm2 describe autowarm | grep "exec cwd"` (см. `feedback_pm2_dump_path_drift.md`).
5. Smoke validate сразу: открыть `https://delivery.contenthunter.ru/...` (testbench UI) → раздел Паки → попробовать создать pack с YT-аккаунтом → должно требовать gmail.

## Post-deploy ops (manual для Feminista)

1. **Восстановить gmail для Feminista пакетов 402/403/404**:
   - **Manual UI:** открыть Паки → каждый из 3 паков (Феминиста_154/155/156) → edit YT-row → ввести gmail оператора → save.
   - **OR** если YT-аккаунты уже залогинены на phones #154/155/156:
     ```bash
     cd /root/.openclaw/workspace-genri/autowarm/ && \
       python3 backfill_yt_gmails.py --device-number 154 --device-number 155 --device-number 156 --dry-run
     # If dry-run looks right, apply без --dry-run.
     ```

2. **Re-queue YT-only failing tasks** (3 из 9 — IG/TT остаются в backlog):
   ```sql
   UPDATE publish_queue pq SET status='pending', publish_task_id=NULL
     FROM publish_tasks pt
     WHERE pq.publish_task_id = pt.id
       AND pt.id IN (3243, 3246, 3247);
   ```

3. **T+30 min smoke**:
   ```sql
   SELECT id, account, platform, status, error_code,
     to_char(created_at AT TIME ZONE 'Europe/Moscow', 'MM-DD HH24:MI') ts
   FROM publish_tasks
   WHERE account ILIKE 'feminista%' AND platform='YouTube'
   ORDER BY created_at DESC LIMIT 5;
   ```
   Expected: новые YT задачи без `yt_target_not_in_picker_after_scroll: gmail=None`.

## Известные follow-ups (out of scope этого спека)

- IG `ig_target_not_in_picker` для `feminista_glow` / `feminista_patches` → sub-task **B-IG**.
- TT `tt_target_not_on_device` → sub-task **B-TT**.
- 100+ legacy YT NULL gmails (cross-project audit) → разовый прогон `backfill_yt_gmails.py --all --parallel 8` post-deploy.
- Code-review минорные items, отложенные на будущий cleanup (см. commit-сообщения 0099c8f, 5215ca5, 8b9f149).

## Memory updates after deploy
- Обновить `project_session_2026_05_07_shipped.md` — добавить B-YT в Отгружено, B-IG/B-TT остаются в Backlog.
- При желании — `project_yt_gmail_switcher.md` дополнить тем, что nav-логика теперь в `yt_gmail_probe.py` (прежде была inline в `backfill_yt_gmails.py`).
