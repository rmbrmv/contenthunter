# YT Account Switcher — Iteration 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Достичь ≥8/10 done статуса на YT publish-задачах phone #19 для аккаунтов `[makiavelli-o2u, Инакент-т2щ]`, разблокировав текущую `name 'random' is not defined` регрессию и evidence-driven дочинив остаток.

**Architecture:** Линейный pipeline T0→T1→GATE→T2→T3. T0 atomic-fixит регрессию импорта в `publisher_base.py` (одна строка). T1 собирает live baseline через триаж-скрипт. GATE решает что делать дальше: skip T2 (если уже 8/10) или locked T2 scope (по top-N reasons). T2 выполняется через subagent-driven-development pattern: 1 фикс — 1 subagent — 1 live retest. T3 — финальная батч-проверка.

**Tech Stack:** Python 3 (publisher_base.py / autowarm), pytest (testbench), PostgreSQL openclaw, pm2 (root user), ADB через remote server (phone #19 = port 15068).

**Repos:**
- `/home/claude-user/contenthunter` — knowledge репо (текущий cwd, plans/evidence/specs)
- `/home/claude-user/autowarm-testbench` — testbench code (claude-user может писать)
- `/root/.openclaw/workspace-genri/autowarm` — prod code, post-commit hook → `GenGo2/delivery-contenthunter`

**Spec:** `/home/claude-user/contenthunter/.ai-factory/specs/2026-04-28-yt-switcher-iter2-design.md`

---

## File Structure

**Files created:**
- `/home/claude-user/contenthunter/.ai-factory/tools/yt_failure_triage.py` — read-only DB агрегатор (ставится в knowledge репо, запускается из любого места)
- `/home/claude-user/contenthunter/.ai-factory/evidence/yt-switcher-iter2-20260428.md` — incremental evidence file, обновляется по ходу всех фаз

**Files modified:**
- `/home/claude-user/autowarm-testbench/publisher_base.py:21` — добавить `import random`
- `/home/claude-user/autowarm-testbench/tests/test_publisher_imports.py` — добавить test_publisher_base_random_imported
- `/root/.openclaw/workspace-genri/autowarm/publisher_base.py` — cherry-pick того же фикса (auto-push hook → GenGo2)

**Files NOT touched (unless evidence forces):**
- `account_switcher.py` (только если T2 GATE решит что нужно)
- `publisher.py` / `publisher_kernel.py` / `publisher_helpers.py`

---

## Phase T0 — Random Import Regression Fix

### Task T0.1: Add failing test for `random` import

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/tests/test_publisher_imports.py`

- [ ] **Step 1: Add test function**

В конец файла `test_publisher_imports.py` добавить (после существующего `test_publisher_base_resolve_sa_mode_at_runtime`):

```python
def test_publisher_base_random_imported():
    """publisher_base.py использует random.randint/random.uniform/random.random
    в run_mini_warm и pre-warm pause helpers (lines 2370, 2376, 2384, 2789, 2936).
    Без `import random` runtime падает: 'name random is not defined'.
    Регрессия 2026-04-28 (lost-import после publisher.py split)."""
    import publisher_base
    assert hasattr(publisher_base, 'random'), (
        'publisher_base.random missing — runtime NameError in run_mini_warm pre-warm'
    )
    assert publisher_base.random.__name__ == 'random'
```

- [ ] **Step 2: Run test to verify it FAILS**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_publisher_imports.py::test_publisher_base_random_imported -v
```

Expected: `FAILED` с `AssertionError: publisher_base.random missing — runtime NameError in run_mini_warm pre-warm`.

Если PASSED — значит `import random` уже добавлен где-то ещё (transitive): grep'ом подтвердить, плана не отменять, перейти к smoke verification (Task T0.7).

### Task T0.2: Add `import random` to publisher_base.py

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/publisher_base.py:21`

- [ ] **Step 1: Insert import**

В файле `/home/claude-user/autowarm-testbench/publisher_base.py` найти строку 21 (`import os`) и добавить ПОСЛЕ неё новую строку:

```python
import os
import random
import re
```

(До правки строки 21-23 были `import os / import re / import time`. После — `import os / import random / import re / import time`.)

- [ ] **Step 2: Run test to verify PASS**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_publisher_imports.py::test_publisher_base_random_imported -v
```

Expected: `PASSED`.

- [ ] **Step 3: Run full imports test suite (regression check)**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_publisher_imports.py -v
```

Expected: 10 passed (9 existing + 1 new).

- [ ] **Step 4: Commit testbench**

```bash
cd /home/claude-user/autowarm-testbench
git add publisher_base.py tests/test_publisher_imports.py
git commit -m "$(cat <<'EOF'
fix(publisher): restore lost `import random` after publisher.py split

publisher_base.run_mini_warm + pre-warm pause helpers used random.uniform/randint
without importing random — runtime crash in pre-warm phase blocked all YT
publishes since 2026-04-27 (tasks 1499-1511 all failed identically).

Regression mirrors prior testbench-publisher-base-imports-20260427 fix
(commit 3e2fe0dec) — same lost-import pattern from publisher.py split.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit success, 1 file mod + 1 file mod (or 1 mod + 1 add).

### Task T0.3: Cherry-pick fix into prod

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_base.py:21`

- [ ] **Step 1: Apply same edit in prod tree**

```bash
sed -i '/^import os$/a import random' /root/.openclaw/workspace-genri/autowarm/publisher_base.py
```

Verification:

```bash
grep -n "^import random" /root/.openclaw/workspace-genri/autowarm/publisher_base.py
```

Expected: один hit вокруг строки 22.

- [ ] **Step 2: Commit in prod tree (post-commit hook auto-pushes)**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_base.py
git commit -m "$(cat <<'EOF'
fix(publisher): restore lost `import random` after publisher.py split

Regression unblocks pre-warm phase for YT/IG/TT publishes.
Mirrors testbench fix.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit success + auto-push hook output ~"Pushed to GenGo2/delivery-contenthunter".

Если auto-push fails — fail здесь, не двигаться дальше.

### Task T0.4: Verify pm2 cwd + restart

- [ ] **Step 1: Confirm pm2 cwd points at prod tree**

```bash
sudo -n pm2 describe autowarm | grep -E "exec cwd|status"
sudo -n pm2 describe autowarm-testbench | grep -E "exec cwd|status"
```

Expected:
- `autowarm` exec cwd: `/root/.openclaw/workspace-genri/autowarm`
- `autowarm-testbench` exec cwd: `/home/claude-user/autowarm-testbench` (memory `feedback_pm2_dump_path_drift.md`)
- both online

Если drift — `pm2 delete autowarm && pm2 start /root/.openclaw/workspace-genri/autowarm/ecosystem.config.js --only autowarm` (аналогично testbench из `/home/claude-user/autowarm-testbench/ecosystem.config.js`).

- [ ] **Step 2: pm2 restart**

```bash
sudo -n pm2 restart autowarm autowarm-testbench
```

Expected: оба `restarted`, status `online`.

- [ ] **Step 3: Tail logs 30s проверить чистый старт**

```bash
sudo -n pm2 logs autowarm --lines 50 --nostream | tail -30
```

Expected: нет stack traces, нет `name 'random' is not defined`.

### Task T0.5: Smoke 1 task — verify unblock

- [ ] **Step 1: Найти media_path из последней natural задачи (1499-1511 range)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT media_path FROM publish_tasks
WHERE platform='YouTube' AND id BETWEEN 1499 AND 1511
ORDER BY id DESC LIMIT 1;"
```

Expected: один путь вида `/tmp/publish_media/pq_<x>_<ts>.mp4`. Сохранить в shell variable `MEDIA_PATH`.

- [ ] **Step 2: Verify file exists on phone proxy host**

```bash
ls -la <MEDIA_PATH from step 1>
```

Expected: file present, size > 1MB. Если не существует — взять следующий из ID range.

- [ ] **Step 3: Inject 1 makiavelli smoke task**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
INSERT INTO publish_tasks
  (platform, account, media_path, description, status,
   pre_warm_videos, post_warm_videos, testbench, device_serial, adb_port)
SELECT 'YouTube', 'makiavelli-o2u', '<MEDIA_PATH>', 'iter2 T0 smoke',
       1, 1, true, device_serial, adb_port
FROM publish_tasks
WHERE platform='YouTube' AND account='makiavelli-o2u' AND status='done'
ORDER BY id DESC LIMIT 1
RETURNING id, account, status;"
```

Expected: новая задача, status `pending` или `awaiting_url`.

Замечание: `pre_warm_videos=1` (минимизировать pre-warm чтобы быстрее увидеть результат). Если orchestrator перезаписывает значение — оставить как есть.

- [ ] **Step 4: Wait + monitor**

```bash
TASK_ID=<id from step 3>
while true; do
  STATUS=$(PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tA -c \
    "SELECT status FROM publish_tasks WHERE id=$TASK_ID;")
  echo "$(date +%H:%M:%S) status=$STATUS"
  case "$STATUS" in
    done|failed|preflight_failed|stopped) break;;
  esac
  sleep 30
done
```

Expected: terminal status в течение 8-12 мин.

- [ ] **Step 5: Confirm random unblock**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, status,
  EXISTS(SELECT 1 FROM jsonb_array_elements(events) ev
         WHERE ev->>'msg' LIKE '%random%not defined%') as random_error
FROM publish_tasks WHERE id=$TASK_ID;"
```

Expected: `random_error=false`. Status может быть любой (done или failed по другой причине), главное — НЕТ `random not defined` в events.

Если `random_error=true` — fail T0, escalate (cwd drift не пофиксился, либо publisher_base.py не подтянулся).

### Task T0.6: Update evidence file with T0 results

**Files:**
- Create: `/home/claude-user/contenthunter/.ai-factory/evidence/yt-switcher-iter2-20260428.md`

- [ ] **Step 1: Initialize evidence file with T0 section**

```bash
cat > /home/claude-user/contenthunter/.ai-factory/evidence/yt-switcher-iter2-20260428.md <<'EOF'
# Evidence — YT Switcher Iteration 2 (2026-04-28)

**Plan:** `.ai-factory/plans/yt-switcher-iter2-20260428.md`
**Spec:** `.ai-factory/specs/2026-04-28-yt-switcher-iter2-design.md`
**Branch:** `fix/testbench-publisher-base-imports-20260427`

---

## T0 — Random import regression fix

**Status:** [✅ shipped / ❌ blocked]

| Repo | Commit |
|---|---|
| `autowarm-testbench` | `<sha>` |
| `/root/.openclaw/workspace-genri/autowarm/` (prod, auto-pushed → GenGo2/delivery-contenthunter) | `<sha>` |

**T0_TS:** `<UTC timestamp последнего prod commit>`

**Smoke verification (Task T0.5):**
- task_id: `<id>`
- account: makiavelli-o2u
- terminal status: `<done / failed / preflight_failed>`
- `random not defined` in events: `<true/false>`

**pm2 cwd verification:** `<paths from describe>`

EOF
```

- [ ] **Step 2: Заполнить плейсхолдеры реальными значениями из T0.1-T0.5**

Edit инструмент использовать чтобы заменить `<sha>`, `<UTC timestamp...>`, `<id>`, и т.д.

- [ ] **Step 3: Commit evidence в knowledge репо**

```bash
cd /home/claude-user/contenthunter
git add .ai-factory/evidence/yt-switcher-iter2-20260428.md
git commit -m "$(cat <<'EOF'
docs(evidence): yt-switcher-iter2 T0 — random import regression fixed

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase T1 — Live Baseline Gathering

### Task T1.1: Create yt_failure_triage.py

**Files:**
- Create: `/home/claude-user/contenthunter/.ai-factory/tools/yt_failure_triage.py`

- [ ] **Step 1: Создать директорию tools/**

```bash
mkdir -p /home/claude-user/contenthunter/.ai-factory/tools
```

- [ ] **Step 2: Написать триаж-скрипт**

`/home/claude-user/contenthunter/.ai-factory/tools/yt_failure_triage.py`:

```python
#!/usr/bin/env python3
"""YT failure triage — read-only агрегатор для T1 baseline / GATE decision.

Usage:
  python yt_failure_triage.py --since '2026-04-28T05:00:00+00' --limit 10

Output: markdown-ready табличный вывод (per-account ratio, reason histogram,
B6 hit/miss, last-step distribution).

Filters:
  - platform = 'YouTube'
  - account IN ('makiavelli-o2u', 'Инакент-т2щ')
  - created_at > since
  - status != 'awaiting_url'  (pending — пропускаем)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

import psycopg2
import psycopg2.extras

ACCOUNTS = ('makiavelli-o2u', 'Инакент-т2щ')
DB = dict(host='localhost', port=5432, dbname='openclaw',
          user='openclaw', password='openclaw123')


def fetch(since: str, limit: int):
    sql = """
    SELECT id, account, status, error_code, events, created_at, updated_at
    FROM publish_tasks
    WHERE platform='YouTube'
      AND account = ANY(%s)
      AND created_at > %s
      AND status != 'awaiting_url'
    ORDER BY id ASC
    LIMIT %s
    """
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (list(ACCOUNTS), since, limit))
            return cur.fetchall()
    finally:
        conn.close()


def reason_of(events):
    """Return first error event's meta.reason | meta.category | msg snippet."""
    if not events:
        return 'no_events'
    for ev in events:
        if ev.get('type') == 'error':
            meta = ev.get('meta') or {}
            return (meta.get('reason')
                    or meta.get('category')
                    or (ev.get('msg') or '')[:60]
                    or 'unlabeled_error')
    return 'no_error_event'


def last_step_of(events):
    if not events:
        return None
    for ev in reversed(events):
        if ev.get('type') in ('start', 'info'):
            msg = ev.get('msg') or ''
            return msg[:50]
    return None


def b6_hits_of(events):
    """Count foreground-guard related events."""
    if not events:
        return 0
    return sum(1 for ev in events
               if (ev.get('meta') or {}).get('category', '').startswith('yt_app_not_foregrounded')
               or (ev.get('meta') or {}).get('category', '').startswith('yt_foreground'))


def render(rows):
    if not rows:
        print('# T1 baseline\n\nNo tasks found in window.')
        return

    total = len(rows)
    by_status = Counter(r['status'] for r in rows)
    by_account = Counter(r['account'] for r in rows)
    done_by_account = Counter(r['account'] for r in rows if r['status'] == 'done')
    reasons = Counter(reason_of(r['events']) for r in rows if r['status'] != 'done')
    b6_total = sum(b6_hits_of(r['events']) for r in rows)
    last_steps = Counter(last_step_of(r['events']) for r in rows if r['status'] != 'done')

    print(f"# T1 baseline ({total} tasks)\n")
    print(f"**Window first→last:** {rows[0]['created_at']} → {rows[-1]['created_at']}\n")

    print("## Status counts\n")
    for st, n in by_status.most_common():
        print(f"- `{st}`: {n}")
    print()

    print("## Per-account ratio\n")
    print("| Account | done | total | rate |")
    print("|---|---|---|---|")
    for acc in ACCOUNTS:
        d, t = done_by_account[acc], by_account[acc]
        rate = f"{(100 * d / t):.0f}%" if t else 'n/a'
        print(f"| {acc} | {d} | {t} | {rate} |")
    print()

    print("## Failure reason histogram\n")
    if not reasons:
        print("(нет фейлов)\n")
    else:
        print("| Reason | Count |")
        print("|---|---|")
        for r, n in reasons.most_common(15):
            print(f"| `{r}` | {n} |")
        print()

    print(f"## B6 v3 foreground-guard hits\n\nTotal events: {b6_total}\n")

    print("## Last-step distribution (failed/preflight only)\n")
    if not last_steps:
        print("(нет фейлов)\n")
    else:
        print("| Last step | Count |")
        print("|---|---|")
        for s, n in last_steps.most_common(10):
            label = (s or '(none)').replace('|', '\\|')
            print(f"| {label} | {n} |")
        print()

    print("## Raw rows\n")
    print("| id | account | status | error_code |")
    print("|---|---|---|---|")
    for r in rows:
        ec = r['error_code'] or ''
        print(f"| {r['id']} | {r['account']} | {r['status']} | `{ec}` |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', required=True, help='ISO8601 lower bound (created_at)')
    ap.add_argument('--limit', type=int, default=10)
    args = ap.parse_args()
    rows = fetch(args.since, args.limit)
    render(rows)


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: Verify script runs (against historical window для self-check)**

```bash
cd /home/claude-user/contenthunter
python .ai-factory/tools/yt_failure_triage.py --since '2026-04-25T00:00:00+00' --limit 10
```

Expected: вывод markdown-таблиц без exception. По историческому окну должны быть строки с makiavelli и Инакент.

- [ ] **Step 4: Commit triage tool**

```bash
cd /home/claude-user/contenthunter
git add .ai-factory/tools/yt_failure_triage.py
git commit -m "$(cat <<'EOF'
feat(tools): yt_failure_triage.py — read-only baseline aggregator

Per-account ratio, reason histogram, B6 hit count, last-step distribution.
Used for T1 baseline + GATE decision in YT switcher iter2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task T1.2: Wait for natural baseline OR manual seed

- [ ] **Step 1: Set timestamp anchor**

```bash
# T0_TS = timestamp последнего prod-commit из T0.3
T0_TS='<UTC timestamp из evidence file>'  # e.g. '2026-04-28T11:30:00+00'
```

- [ ] **Step 2: Probe orchestrator activity (60-90 min wait)**

Каждые 15 минут check:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT account, status, COUNT(*)
FROM publish_tasks
WHERE platform='YouTube'
  AND account IN ('makiavelli-o2u', 'Инакент-т2щ')
  AND created_at > '$T0_TS'
GROUP BY 1,2 ORDER BY 1,2;"
```

Continue до тех пор пока:
- Каждый аккаунт имеет ≥5 terminated задач (sum done+failed+preflight_failed ≥ 5), ИЛИ
- Прошло 90 минут — переходим к Step 3 (manual seed).

- [ ] **Step 3 (conditional): Manual seed если не хватает**

Для каждого аккаунта где `terminated_count < 5`:

```bash
DEFICIT_ACC='Инакент-т2щ'  # пример
NEEDED=3  # 5 - existing terminated
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
WITH src AS (
  SELECT media_path, device_serial, adb_port
  FROM publish_tasks
  WHERE platform='YouTube' AND id BETWEEN 1499 AND 1511
  ORDER BY random() LIMIT $NEEDED
)
INSERT INTO publish_tasks
  (platform, account, media_path, description, status,
   pre_warm_videos, post_warm_videos, testbench, device_serial, adb_port)
SELECT 'YouTube', '$DEFICIT_ACC', media_path,
       'iter2 T1 manual seed', 'pending',
       1, 1, true, device_serial, adb_port
FROM src
RETURNING id;"
```

Wait до terminal status (через monitor loop из T0.5 step 4).

### Task T1.3: Run triage + capture baseline

- [ ] **Step 1: Запустить triage с T0_TS**

```bash
cd /home/claude-user/contenthunter
python .ai-factory/tools/yt_failure_triage.py --since "$T0_TS" --limit 10 \
  > /tmp/yt-iter2-t1-baseline.md
cat /tmp/yt-iter2-t1-baseline.md
```

Expected: 10 (или меньше если orchestrator не дал) задач, 2 аккаунта, full markdown.

- [ ] **Step 2: Append baseline в evidence file**

Через Edit-инструмент добавить в `.ai-factory/evidence/yt-switcher-iter2-20260428.md` после T0 секции:

```markdown
## T1 — Live baseline

**T0_TS:** `<value>`
**Window collected:** `<first task ts>` → `<last task ts>`
**Tasks counted:** `<n>`

<вставить сюда содержимое /tmp/yt-iter2-t1-baseline.md>
```

- [ ] **Step 3: Commit T1 baseline в evidence**

```bash
cd /home/claude-user/contenthunter
git add .ai-factory/evidence/yt-switcher-iter2-20260428.md
git commit -m "docs(evidence): yt-switcher-iter2 T1 baseline collected

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## GATE — Decision Point

### Task GATE.1: Compute decision from T1 baseline

- [ ] **Step 1: Read baseline numbers**

Из T1 evidence:
- `done_total` = COUNT(status='done')
- `done_maki` = makiavelli done
- `done_inak` = Инакент done
- `n` = total tasks counted (≤10)

- [ ] **Step 2: Apply decision matrix**

| Условие | Решение |
|---|---|
| `n >= 10 AND done_total >= 8 AND done_maki >= 1 AND done_inak >= 1` | **SKIP T2** → перейти к T3 (формальная acceptance проверка с тем же набором; Task T3.1) |
| `n < 10` | **WAIT** — продлить T1, добрать через manual seed |
| `n >= 10 AND done_total < 8` | **ENTER T2** — выбрать кандидатов из top-N reasons |
| `done_inak = 0` (и аккаунт не «logout») | **ENTER T2** с обязательной Инакент-investigation веткой |

- [ ] **Step 3: Записать GATE решение в evidence**

Append в evidence file:

```markdown
## GATE decision

**T1 numbers:** done_total=`<n>`, done_maki=`<m>`, done_inak=`<i>`, total=`<t>`

**Decision:** `<SKIP_T2 / ENTER_T2 / WAIT>`

**T2 scope (if ENTER_T2):**
- Fix candidate 1: `<reason>` — `<n hits>` — proposed approach: `<short>`
- Fix candidate 2: `<reason>` — `<n hits>` — proposed approach: `<short>`
- Инакент-specific: `<analysis if done_inak=0>`
```

Commit message: `docs(evidence): yt-switcher-iter2 GATE decision — <SKIP|ENTER>`.

---

## Phase T2 — Targeted Fixes (locked at GATE, evidence-driven)

> **Если GATE = SKIP_T2, эта секция пропускается целиком.** Перейти к T3.

### Task T2.process: Per-fix subagent dispatch loop

**Для КАЖДОГО fix candidate из GATE.3 evidence (sequential, NOT parallel):**

- [ ] **Step 1: Pre-flight grep API audit (3 мин)**

Перед написанием спеки фикса проверить реальный API:

```bash
cd /home/claude-user/autowarm-testbench
grep -nE "self\.p\.(log_event|adb|dump_ui|wait|tap|swipe)" account_switcher.py | head -10
grep -nE "def _" account_switcher.py | head -30
```

Запомнить — реальные методы `self.p.log_event/adb/dump_ui` (memory `reference_publisher_proxy_api.md`). НЕ использовать fictional `self._record_event` / `self.serial` / `_run_adb_shell` / `_dump_ui`.

- [ ] **Step 2: Spec the fix (короткая mini-spec, ≤30 строк)**

Создать в conversation либо в `.ai-factory/specs/2026-04-28-iter2-fix-<N>-<short>.md`:
- Проблема (1 параграф, со ссылкой на T1 reason histogram)
- Триггер (где в коде кончался контроль)
- Helper / fix (≤1 helper, ≤50 строк)
- Tests (≤3 unit tests с MagicMock publisher)

- [ ] **Step 3: Subagent dispatch — implementer**

Использовать general-purpose subagent. Prompt включает:
- Полный текст mini-spec
- Reference к memory `reference_publisher_proxy_api.md` (anti-pattern fictional API)
- Reference к `feedback_silent_crash_layered.md` (один фикс, не batch)
- Конкретные пути файлов
- TDD: тест сначала, fail → impl → green → commit

- [ ] **Step 4: Code-quality review subagent**

Использовать `superpowers:code-reviewer`. Prompt:
- Spec и git diff фикса
- Question: "Реальный API publisher_base используется? Tests cover positive+negative+anti-false-positive? Есть ли regressions в test_publisher_imports.py?"

Если review = blocker → revert или patch, перепрогнать.

- [ ] **Step 5: Cherry-pick prod**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch && git cherry-pick <testbench commit sha>  # или manual sed-equivalent
```

(Если git'ы не shared, сделать manual edit с точно теми же diff'ами через `diff -u` и `patch`.)

Commit + auto-push hook → GenGo2/delivery-contenthunter.

- [ ] **Step 6: pm2 restart**

```bash
sudo -n pm2 restart autowarm autowarm-testbench
```

- [ ] **Step 7: Live retest (1 task per fix)**

Повторить T0.5 (smoke 1 makiavelli задачу с media из 1499-1511 range). Дождаться terminal.

Verify через `yt_failure_triage.py --since "<this fix's deploy ts>" --limit 1`:
- Если этот фикс предотвратил конкретный reason — pass.
- Если новый dominant reason — это next T2 candidate.

- [ ] **Step 8: Append fix N в evidence**

```markdown
### T2.<N> — <fix name>

**Spec:** `.ai-factory/specs/2026-04-28-iter2-fix-<N>-<short>.md` (or inline)
**Commits:** testbench `<sha>`, prod `<sha>`
**Live retest:** task_id `<id>` → `<status>`, reason `<reason>`
**Verdict:** `<resolved / new dominant / regression>`
```

- [ ] **Step 9: Решить — ещё один T2 фикс или переход к T3**

Если все candidates из GATE evidence закрыты → T3.
Если новый dominant reason → repeat Task T2.process (Step 1-8) для нового фикса.

**Stop condition (max 3 фикса в одной сессии):** при >3 без успеха записать partial + остановиться.

---

## Phase T3 — Acceptance Batch

### Task T3.1: Set acceptance anchor

- [ ] **Step 1: Determine T_ANCHOR**

```bash
# Если T2 был skipped: T_ANCHOR = T0_TS
# Если T2 имел фиксы: T_ANCHOR = timestamp последнего T2 prod commit
T_ANCHOR='<UTC ts>'
```

Записать в evidence:

```markdown
## T3 — Acceptance batch

**T_ANCHOR:** `<value>`
**Source:** `<T2 last commit / T0 commit>`
```

### Task T3.2: Wait for 10 acceptance tasks

- [ ] **Step 1: Same as T1.2 monitor, но 10 задач, 2 аккаунта**

```bash
while true; do
  COUNT=$(PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tA -c "
    SELECT COUNT(*) FROM publish_tasks
    WHERE platform='YouTube'
      AND account IN ('makiavelli-o2u', 'Инакент-т2щ')
      AND created_at > '$T_ANCHOR'
      AND status IN ('done', 'failed', 'preflight_failed', 'stopped')")
  echo "$(date +%H:%M:%S) terminated=$COUNT"
  [ "$COUNT" -ge 10 ] && break
  sleep 60
done
```

Если orchestrator не выдаёт нужный mix (5 makiavelli + 5 Инакент за разумное время) — manual seed дополнительные через T1.2 step 3.

### Task T3.3: Run acceptance SQL

- [ ] **Step 1: List excluded ids (pm2-killed)**

Если в окне T_ANCHOR→now происходил pm2 restart, найти задачи которые попали под него:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id FROM publish_tasks
WHERE platform='YouTube' AND account IN ('makiavelli-o2u', 'Инакент-т2щ')
  AND created_at > '$T_ANCHOR' AND status='preflight_failed'
  AND error_code='unknown'
ORDER BY id;"
```

Просмотреть events каждой и решить (если task started, не дошла до switcher → exclude). Список ids → `EXCLUDED_IDS` (e.g. `(1492, 1495)`; если none — `(-1)`).

- [ ] **Step 2: Run formal acceptance query**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
WITH bucket AS (
  SELECT id, account, status FROM publish_tasks
  WHERE platform='YouTube'
    AND account IN ('makiavelli-o2u', 'Инакент-т2щ')
    AND created_at > '$T_ANCHOR'
    AND id NOT IN $EXCLUDED_IDS
  ORDER BY id LIMIT 10
)
SELECT
  COUNT(*) FILTER (WHERE status='done') AS done,
  COUNT(*) FILTER (WHERE status='done' AND account='makiavelli-o2u') AS done_maki,
  COUNT(*) FILTER (WHERE status='done' AND account='Инакент-т2щ') AS done_inak,
  COUNT(*) AS total
FROM bucket;"
```

Expected (acceptance pass): `done >= 8 AND done_maki >= 1 AND done_inak >= 1 AND total = 10`.

- [ ] **Step 3: Append T3 result в evidence**

```markdown
### T3 result

**Excluded ids:** `<EXCLUDED_IDS or none>`
**Counts:** done=`<n>`, done_maki=`<m>`, done_inak=`<i>`, total=`<t>`

**Verdict:** `<✅ PASS — 8/10 reached / ❌ FAIL — partial Y/10>`

**If FAIL — next steps:** `<short>`
```

- [ ] **Step 4: Final commit**

```bash
cd /home/claude-user/contenthunter
git add .ai-factory/evidence/yt-switcher-iter2-20260428.md
git commit -m "$(cat <<'EOF'
docs(evidence): yt-switcher-iter2 T3 acceptance — <PASS Y/10 / partial Y/10>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task T3.4: Memory updates

- [ ] **Step 1: Update `project_yt_publish_stabilization_partial.md`**

Поменять status memory:
- Если PASS → переименовать на `project_yt_publish_stabilization_done.md`, mark «iter2 closed, 8/10 reached».
- Если partial → bump «iter2 closed Y/10, deferred: <list>».

- [ ] **Step 2: Update `MEMORY.md` index**

Поправить one-line hook чтобы отражать iter2 result.

- [ ] **Step 3: New memories по необходимости**

Если в T2 нашли новый failure mode и зафиксили — новая `project_*` memory.
Если узнали новое практическое правило — `feedback_*` memory.

- [ ] **Step 4: Commit memory updates**

```bash
cd /home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory
git add . 2>/dev/null  # (если memory под git'ом; иначе файлы остаются on-disk)
```

(Memory dir может быть не git-tracked — в этом случае просто оставить на диске.)

---

## Anti-patterns to avoid (по урокам 2026-04-27)

1. **Не делать T2-фиксы пакетом** — каждый отдельным subagent с live retest. Memory `feedback_silent_crash_layered.md`.
2. **Не использовать fictional API** в специках T2 — `self.p.log_event/adb/dump_ui` обязательно. Memory `reference_publisher_proxy_api.md`.
3. **Не трогать `dumpsys window windows`** — memory `feedback_pm2_dump_path_drift.md` + B6 v2 урок: на Samsung One UI работает только `dumpsys window | grep mCurrentFocus` (но даже это даёт `null` на secondary display — лучше `dumpsys activity activities | grep topResumedActivity`).
4. **Не угадывать media_path** — копировать из существующих задач (`pq_*.mp4` из 1499-1511 диапазона). Memory `reference_testbench_smoke_paths.md`.
5. **Не пропускать pm2 cwd check** — pm2 может читать stale `/home/claude-user/autowarm-testbench/` для prod app. Memory `feedback_pm2_dump_path_drift.md`.
6. **Не trust step-name в UI dump'е** — проверять package в dump перед интерпретацией. Memory `feedback_ui_dump_app_recognition.md`.

---

## Stop conditions

- 3 T2-фикса не достигли acceptance → STOP partial, finalize evidence.
- Любой T0/T1 step blocked >2 раза → escalate, finalize partial.
- pm2 cwd drift не исправляется → STOP, infra issue.
- Инакент-т2щ помечен как «account-level dead» (logout / channel deleted / captcha) и реально не починим → STOP с partial 5/10 с отметкой sanity-fail.
