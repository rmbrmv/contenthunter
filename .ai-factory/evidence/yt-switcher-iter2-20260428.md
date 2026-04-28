# Evidence — YT Switcher Iteration 2 (2026-04-28)

**Plan:** `.ai-factory/plans/yt-switcher-iter2-20260428.md`
**Spec:** `.ai-factory/specs/2026-04-28-yt-switcher-iter2-design.md`
**Branch (knowledge repo):** `fix/testbench-publisher-base-imports-20260427`

---

## T0 — Random import regression fix

**Status:** ✅ shipped

| Repo | Commit |
|---|---|
| `autowarm-testbench` (testbench tree) | `5a60b15` |
| `/root/.openclaw/workspace-genri/autowarm/` (prod, auto-pushed → GenGo2/delivery-contenthunter) | `fcfa851` |
| `contenthunter` (knowledge — triage tool) | `35e599e` (T1.1 prep, не часть T0) |

**T0_TS (prod commit timestamp):** `2026-04-28 08:18:35 UTC`

**TDD chain (Task T0-IMPL):**
- Step 2 fail: `FAILED tests/test_publisher_imports.py::test_publisher_base_random_imported` — AssertionError as expected.
- Step 4 pass: `PASSED [100%]` after `import random` added.
- Step 5 full: `11 passed in 0.06s` — no regressions in pre-existing 10 tests.

**Spec compliance review:** ✅ all 5 points verified (import location, test signature, docstring with line refs + date, scope = 2 files, regression suite green).

**Code quality review:** ✅ APPROVED. Reviewer noted backlog item (deferred): AST-walker test that validates every `<name>.<attr>` reference resolves to a module-level name — would catch this whole class of split-regression in 1 test. Not pulled into this iteration.

**Smoke verification (Task T0.5):**

| Field | Value |
|---|---|
| task_id | 1512 |
| platform | YouTube |
| account | makiavelli-o2u |
| device_serial | RF8YA0W57EP |
| adb_port | 15068 |
| media_path | /tmp/publish_media/pq_736_1777354462096.mp4 |
| pre_warm_videos | 1 |
| terminal status | **`done`** |
| `random not defined` in events | **false** |
| event count | 51 |
| runtime | 15m 35s |

**Conclusion:** prod runtime читает обновлённый `publisher_base.py` с `import random`, pre-warm проходит, switcher отрабатывает, makiavelli-o2u публикуется. T0 разблокировал систему.

**pm2 state observation:**

| App | PID | exec cwd | status |
|---|---|---|---|
| `autowarm` | 1482202 | `/root/.openclaw/workspace-genri/autowarm` | online (uptime 0s after restart) |
| `autowarm-testbench` | 1482216 | `/root/.openclaw/workspace-genri/autowarm` | online (uptime 0s after restart) |

**Drift note:** `autowarm-testbench` exec cwd = prod tree, не `/home/claude-user/autowarm-testbench/`. По факту обе pm2-аппы запускают prod-код. Subagent commit `5a60b15` в testbench-tree сейчас НЕ runtime — но содержит идентичную правку, так что состояние консистентно. Для T2 фиксов это означает: код менять В ПРОД (`/root/.openclaw/.../autowarm/`), не testbench tree, либо переключать pm2 cwd обратно.

---

## T1 — Live baseline gathering (in progress)

**Triage tool:** `.ai-factory/tools/yt_failure_triage.py` создан (T1.1, commit `35e599e`).

**T1.2 (wait for natural baseline):** активен — orchestrator should produce ≥10 YT задач на makiavelli + Инакент после T0_TS. Будет дополнен после.

---

## T0 deferred (in this iteration's backlog)

- AST-walker test для валидации `<name>.<attr>` → module-level name (предотвращает split-regression class). Кандидат на отдельный мини-fix после T3.
- pm2 cwd drift: `autowarm-testbench` точечно показывает prod tree, а не testbench. Возможно, потеряли отдельную dev-среду. Если T2 потребует разделения — починим.
