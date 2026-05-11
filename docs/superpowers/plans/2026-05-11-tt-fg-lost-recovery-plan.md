# TT fg-lost app-switch recovery — Implementation Plan v1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть silent `tt_fg_lost` failure-mode (2/24h, 10-15 мин dwell каждый) через reactive recovery в `_wait_upload_confirmation` outer loop: при non-TT foreground pkg вызвать `monkey ... LAUNCHER 1` (reorder-to-front), 1 attempt + reset overlay_streak.

**Architecture:** Approach A из spec — helper `_attempt_tt_fg_recovery` в TikTokMixin; wire-in в `publisher_tiktok.py:1042-1043` (после `if dismissed: continue`, перед `if overlay_streak >= 3`). Per-task flag через lazy `getattr`. 3 новых events для observability.

**Tech Stack:** Python 3.11, pytest, MagicMock. ADB и live phone НЕ требуются для unit-тестов.

**Path conventions:**
- **Spec & plan & evidence:** `/home/claude-user/contenthunter/` (agent workspace, main branch).
- **Deploy tree (code + tests):** `/root/.openclaw/workspace-genri/autowarm/` (PR-driven, auto-push hook → GenGo2/delivery-contenthunter).
- **Branch:** `fix/tt-fg-lost-recovery-20260511` (autowarm tree).

**Spec:** `docs/superpowers/specs/2026-05-11-tt-fg-lost-app-switch-recovery-design.md` (v1, Codex CLEAN после 2 rounds).

---

## Task 1: Branch setup + baseline green

**Tree:** deploy (`/root/.openclaw/workspace-genri/autowarm/`)

- [ ] **Step 1: Sync with origin/main and create branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git checkout main
git pull --ff-only origin main
git checkout -b fix/tt-fg-lost-recovery-20260511
git log -1 --oneline  # should be at least 750c3fa (TT post-switch renav merged)
```

Expected: branch создан от latest main (750c3fa или новее).

- [ ] **Step 2: Confirm key symbols exist**

```bash
cd /root/.openclaw/workspace-genri/autowarm
grep -n "class TikTokMixin\|tt_fg_lost\|def dismiss_overlay_dialogs\|topResumedActivity" publisher_tiktok.py publisher_base.py | head -10
```

Expected:
- `class TikTokMixin:` ~line 160 в `publisher_tiktok.py`
- `tt_fg_lost` ~line 1048-1051 (emit point)
- `dismiss_overlay_dialogs` defined в `publisher_base.py`
- `topResumedActivity` inline check ~line 998-1002

Если что-то не находится — STOP, обновить план до продолжения.

- [ ] **Step 3: Run baseline test suite**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_account_switcher_tt.py -v 2>&1 | tail -5
```

Expected: all PASS (32 tests). Записать как baseline.

---

## Task 2: `_attempt_tt_fg_recovery` helper (TDD)

**Tree:** deploy
**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/test_tt_fg_recovery.py`
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py` (add method в `TikTokMixin`)

> **Why first:** Helper изолированно тестируется без mocks outer loop state. Wire-in в Task 3 вызывает только этот helper.

- [ ] **Step 1: Write 5 helper tests (red)**

Create `/root/.openclaw/workspace-genri/autowarm/tests/test_tt_fg_recovery.py`:

```python
"""Tests for TT fg-lost app-switch recovery (Approach A).

Covers:
  - `_attempt_tt_fg_recovery` helper (TT reorder-to-front recovery, 5 tests).

Run:
    cd /root/.openclaw/workspace-genri/autowarm
    pytest tests/test_tt_fg_recovery.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_tiktok import TikTokMixin  # noqa: E402


def _make_mixin(adb_responses: list):
    """Build a TikTokMixin instance с mocked adb.

    `adb_responses` — list of strings возвращается последовательно при каждом
    вызове `self.adb`. Первый — для monkey reorder (обычно ''), второй — для
    re-check topResumedActivity (либо содержит 'musically' для success, либо
    pkg другого app для failure).
    """
    mx = TikTokMixin.__new__(TikTokMixin)
    mx.adb = MagicMock(side_effect=adb_responses)
    mx.log_event = MagicMock()
    mx.platform = 'TikTok'
    return mx


def test_attempt_recovery_success_returns_true():
    """monkey reorder + recheck shows musically → True + success event."""
    adb_responses = [
        '',  # monkey command
        'topResumedActivity=ActivityRecord{u0 com.zhiliaoapp.musically/.main.MainActivity}',
    ]
    mx = _make_mixin(adb_responses)
    result = mx._attempt_tt_fg_recovery('com.sec.android.app.launcher', overlay_streak=3)
    assert result is True
    assert mx._tt_fg_recovery_attempted is True
    emitted_categories = [
        call.kwargs.get('meta', {}).get('category')
        for call in mx.log_event.call_args_list
    ]
    assert 'tt_fg_recovery_attempt' in emitted_categories
    assert 'tt_fg_recovery_success' in emitted_categories


def test_attempt_recovery_failed_returns_false():
    """monkey reorder + recheck still non-TT → False + failed event."""
    adb_responses = [
        '',  # monkey command
        'topResumedActivity=ActivityRecord{u0 com.sec.android.app.launcher/.Launcher}',
    ]
    mx = _make_mixin(adb_responses)
    result = mx._attempt_tt_fg_recovery('com.sec.android.app.launcher', overlay_streak=3)
    assert result is False
    assert mx._tt_fg_recovery_attempted is True
    emitted_categories = [
        call.kwargs.get('meta', {}).get('category')
        for call in mx.log_event.call_args_list
    ]
    assert 'tt_fg_recovery_attempt' in emitted_categories
    assert 'tt_fg_recovery_failed' in emitted_categories


def test_attempt_recovery_emits_attempt_event_with_meta():
    """Attempt event имеет overlay_pkg + overlay_streak + step в meta."""
    adb_responses = ['', 'topResumedActivity=...musically...']
    mx = _make_mixin(adb_responses)
    mx._attempt_tt_fg_recovery('com.sec.android.app.camera', overlay_streak=2)
    attempt_call = None
    for call in mx.log_event.call_args_list:
        cat = call.kwargs.get('meta', {}).get('category')
        if cat == 'tt_fg_recovery_attempt':
            attempt_call = call
            break
    assert attempt_call is not None
    meta = attempt_call.kwargs.get('meta', {})
    assert meta.get('overlay_pkg') == 'com.sec.android.app.camera'
    assert meta.get('overlay_streak') == 2
    assert meta.get('step') == 'wait_upload'
    assert meta.get('platform') == 'TikTok'


def test_attempt_recovery_sets_attempted_flag_even_on_failure():
    """Per-task flag устанавливается всегда, даже после неудачного recovery."""
    adb_responses = ['', 'topResumedActivity=...com.sec.android.app.launcher...']
    mx = _make_mixin(adb_responses)
    assert getattr(mx, '_tt_fg_recovery_attempted', False) is False
    mx._attempt_tt_fg_recovery('com.sec.android.app.launcher', overlay_streak=3)
    assert mx._tt_fg_recovery_attempted is True


def test_attempt_recovery_uses_monkey_command():
    """Первый adb call — monkey -p com.zhiliaoapp.musically LAUNCHER intent."""
    adb_responses = ['', 'topResumedActivity=...musically...']
    mx = _make_mixin(adb_responses)
    mx._attempt_tt_fg_recovery('com.sec.android.app.launcher', overlay_streak=3)
    # First call — monkey command
    first_call_args = mx.adb.call_args_list[0]
    cmd = first_call_args.args[0] if first_call_args.args else ''
    assert 'monkey' in cmd
    assert 'com.zhiliaoapp.musically' in cmd
    assert 'LAUNCHER' in cmd
```

- [ ] **Step 2: Run tests, verify all red**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_tt_fg_recovery.py -v 2>&1 | tail -15
```

Expected: 5 FAILED — `AttributeError: ... '_attempt_tt_fg_recovery'`.

- [ ] **Step 3: Implement `_attempt_tt_fg_recovery` method**

В `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py`. Найти `class TikTokMixin:` (line 160) и рядом с другими helper-методами (например рядом с `_safe_kb_probe` или `_handle_tt_music_rights_dialog`), добавить:

```python
    def _attempt_tt_fg_recovery(self, overlay_pkg: str, overlay_streak: int) -> bool:
        """[tt_fg_recovery 2026-05-11] Попытаться вернуть TT на foreground.

        Используется в `_wait_upload_confirmation` outer loop когда foreground
        улетел в non-TT pkg (Samsung Launcher / Camera / etc) после AI Unstuck
        или blind-tap edge zone. Один attempt per task (lazy flag).
        НЕ делает cold-restart (publish state preservation).

        Returns:
            True — TT вернулся на foreground (recheck topResumedActivity
                   содержит 'musically'). Caller сбрасывает overlay_streak.
            False — recovery не помог. Caller продолжит в legacy path
                    (overlay_streak растёт → tt_fg_lost fail).
        """
        self.log_event(
            'info', f'TikTok fg-lost: recovery attempt (pkg={overlay_pkg})',
            meta={'category': 'tt_fg_recovery_attempt',
                  'platform': self.platform, 'step': 'wait_upload',
                  'overlay_pkg': overlay_pkg, 'overlay_streak': overlay_streak},
        )
        self.adb('monkey -p com.zhiliaoapp.musically '
                 '-c android.intent.category.LAUNCHER 1')
        time.sleep(2.5)
        act_after = self.adb(
            'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
            timeout=8,
        ) or ''
        self._tt_fg_recovery_attempted = True

        if 'musically' in act_after:
            self.log_event(
                'info', 'TikTok fg-lost: recovery success — TT back on foreground',
                meta={'category': 'tt_fg_recovery_success',
                      'platform': self.platform, 'step': 'wait_upload',
                      'recovered_from_pkg': overlay_pkg},
            )
            return True

        self.log_event(
            'warning',
            f'TikTok fg-lost: recovery failed — fg act={act_after.strip()[:80]!r}',
            meta={'category': 'tt_fg_recovery_failed',
                  'platform': self.platform, 'step': 'wait_upload',
                  'overlay_pkg': overlay_pkg,
                  'after_recovery_act': act_after.strip()[:120]},
        )
        return False
```

`time` уже импортирован в publisher_tiktok.py (проверить через `grep -E "^(import time|from .* import.*time)" publisher_tiktok.py`).

- [ ] **Step 4: Run tests, verify all green**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_tt_fg_recovery.py -v 2>&1 | tail -15
```

Expected: 5 PASSED.

- [ ] **Step 5: Class-level hasattr smoke check** (per `feedback_class_vs_instance_test_calls`)

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "from publisher_tiktok import TikTokMixin; assert hasattr(TikTokMixin, '_attempt_tt_fg_recovery'); print('class-level OK')"
```

Expected: `class-level OK`. Если ошибка — method placed wrong (instance attr вместо class method).

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add tests/test_tt_fg_recovery.py publisher_tiktok.py
git commit -m "feat(publisher-tt): _attempt_tt_fg_recovery helper (monkey reorder-to-front)"
```

---

## Task 3: Wire-in в `_wait_upload_confirmation` outer loop

**Tree:** deploy
**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py:1037-1054` (overlay branch в wait_upload loop)

> **Why:** Helper готов. Теперь wire его перед existing `if overlay_streak >= 3` final-fail.

- [ ] **Step 1: Read current overlay branch context**

```bash
sed -n '988,1058p' /root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py
```

Confirm точная структура:
- Line ~989-991: `log.info('  Ждём подтверждения загрузки TikTok ...'); overlay_streak = 0; for wait in range(60):`
- Line ~1037-1042: `dismissed = self.dismiss_overlay_dialogs(ui); if dismissed: ... overlay_streak = 0; continue`
- Line ~1045-1054: `if overlay_streak >= 3: ... self.log_event('error', ..., meta={'category': 'tt_fg_lost', ...}); break`
- Line ~1054 (end): `continue # ждём ещё`

Wire-in делается в 2 точках:
1. **At loop start** (line ~990 рядом с `overlay_streak = 0`) — reset `_tt_fg_recovery_attempted` flag.
2. **Inside overlay branch** МЕЖДУ existing `if dismissed: continue` и `if overlay_streak >= 3:` check — recovery dispatch.

> **Why reset at loop start (Codex round 1 P2 catch):** flag `_tt_fg_recovery_attempted` — instance attr на publisher object. Без explicit reset при новом upload-task он останется `True` от previous task → recovery skip'нется forever в long-lived worker process. Reset at `_wait_upload_confirmation` start даёт "one attempt per task" semantics.

- [ ] **Step 2: Apply wire-in edits (2 places)**

**Place 1 — at `_wait_upload_confirmation` start** (line ~990):

Найти существующее:

```python
        log.info('  Ждём подтверждения загрузки TikTok (до 3 мин)...')
        overlay_streak = 0  # сколько итераций подряд НЕ TikTok на переднем плане
        for wait in range(60):  # 60 × ~8-9 сек = ~8-9 минут реально
```

Заменить middle line (или добавить новую перед `for`) чтобы выглядело:

```python
        log.info('  Ждём подтверждения загрузки TikTok (до 3 мин)...')
        overlay_streak = 0  # сколько итераций подряд НЕ TikTok на переднем плане
        # [tt_fg_recovery 2026-05-11] Reset per-task flag: long-lived worker
        # переиспользует publisher instance → без reset flag remains True
        # после first attempt → recovery skip'нется forever (Codex P2 catch).
        self._tt_fg_recovery_attempted = False
        for wait in range(60):  # 60 × ~8-9 сек = ~8-9 минут реально
```

**Place 2 — inside overlay branch** (между `if dismissed: continue` и `if overlay_streak >= 3:`):

В `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py`, между existing line ~1042 (`continue` после `if dismissed:`) и line ~1044 (`# Если TikTok не вернулся ...` comment + `if overlay_streak >= 3:`), вставить:

В `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py`, между existing line ~1042 (`continue` после `if dismissed:`) и line ~1044 (`# Если TikTok не вернулся ...` comment + `if overlay_streak >= 3:`), вставить:

```python
                # === NEW [tt_fg_recovery 2026-05-11]: app-switch recovery
                # перед streak fail-out (Approach A из spec). При non-TT pkg
                # (Samsung Launcher / Camera / etc) монкеем поднимаем TT на
                # foreground через reorder-to-front (publish state сохраняется).
                # Один attempt per task; exclusion для permissioncontroller
                # (let existing handlers manage).
                if (_pkg != 'com.zhiliaoapp.musically'
                        and _pkg != 'com.android.permissioncontroller'
                        and not getattr(self, '_tt_fg_recovery_attempted', False)):
                    if self._attempt_tt_fg_recovery(_pkg, overlay_streak):
                        overlay_streak = 0
                        continue
                    # recovery failed → fall through to existing streak check
```

ВАЖНО: indentation должна совпадать с окружающим кодом — `if not tiktok_active:` блок индент'нут на 12 spaces (3 уровня). Внутри блока `if`/`continue` — 16 spaces.

После вставки, существующий блок `if overlay_streak >= 3:` остаётся unchanged.

- [ ] **Step 3: Run existing tests — verify no regression**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_tt_fg_recovery.py tests/test_account_switcher_tt.py -v 2>&1 | tail -10
```

Expected: 5 new + 32 baseline = 37 PASS (no regression от wire-in).

- [ ] **Step 4: Smoke import check**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import publisher_tiktok; print('OK')"
```

Expected: `OK` (no SyntaxError от wire-in).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_tiktok.py
git commit -m "feat(publisher-tt): wire tt_fg_recovery в wait_upload loop"
```

---

## Task 4: Full suite + lint + final pre-PR checks

**Tree:** deploy

- [ ] **Step 1: Run full publisher_tiktok test suite**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/ -v -k 'tiktok or tt_ or publisher_tiktok' 2>&1 | tail -20
```

Expected: all PASS. Если есть pre-existing failures — записать их и убедиться что они не от наших changes (см. T1 baseline).

- [ ] **Step 2: Run focused integration tests (account_switcher TT)**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_account_switcher_tt.py tests/test_tt_fg_recovery.py tests/test_post_switch_renav.py -v 2>&1 | tail -10
```

Expected: 32 baseline + 5 new fg_recovery + 12 existing renav (from PR #34) = 49 PASS.

- [ ] **Step 3: Diff review pre-push**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git log --oneline main..HEAD
git diff main...HEAD --stat
```

Expected: 2 commits (T2 helper, T3 wire-in), ≤150 lines added (helper ~40 + tests ~110 + wire-in ~12).

---

## Task 5: PR + Codex review round

**Tree:** deploy

- [ ] **Step 1: Push branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git push -u origin fix/tt-fg-lost-recovery-20260511
```

- [ ] **Step 2: Codex review uncommitted diff vs main**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git diff main...HEAD | ~/.local/bin/codex review -
```

Expected: review output. Если P1 → STOP, apply fix, commit `fix(...): apply Codex round N`, re-run Codex round N+1. Loop до 0 P1.

Если P2/P3 → собрать в один commit `fix(...): apply Codex round 1 (M P2 + K P3)`.

- [ ] **Step 3: Create PR via gh CLI**

После 0 P1:

```bash
cd /root/.openclaw/workspace-genri/autowarm
source ~/secrets/github-gengo2.env
export GH_TOKEN=$GITHUB_TOKEN_GENGO2
gh pr create --repo GenGo2/delivery-contenthunter \
  --base main \
  --head fix/tt-fg-lost-recovery-20260511 \
  --title "TT fg-lost app-switch recovery (monkey reorder-to-front)" \
  --body "$(cat <<'EOF'
## Summary
- Закрывает `tt_fg_lost` failure-mode (2/24h pre-deploy, 10-15 мин dwell каждый кейс).
- Reactive recovery в `_wait_upload_confirmation` outer loop при detection non-TT foreground pkg → `monkey -p com.zhiliaoapp.musically LAUNCHER 1` (reorder-to-front, publish state preserved).
- 1 attempt per task + reset overlay_streak. 3 новых event categories.

## Root cause

AI Unstuck blind-tap'ы (или blind FALLBACK coords при caption fill) попадают в edge UI зоны → launches Samsung Launcher / Camera. `dismiss_overlay_dialogs` (publisher_base.py:489) handle'ит только dialog-level overlays, НЕ app-switch. После 3 iter `overlay_streak >= 3` → `tt_fg_lost` fail.

Evidence: pt 4523 (clickpay_world, launcher overlay), pt 4624 (clickpay_world, camera overlay) — оба в memory `project_publish_followups_2026_05_06.md`.

## Spec & plan
- Spec: `docs/superpowers/specs/2026-05-11-tt-fg-lost-app-switch-recovery-design.md` (v1, Codex CLEAN 2 rounds)
- Plan: `docs/superpowers/plans/2026-05-11-tt-fg-lost-recovery-plan.md` (v1)

## Tests
- 5 unit tests (`tests/test_tt_fg_recovery.py`) — success/failed/event_meta/flag/monkey_cmd paths
- Class-level hasattr smoke (`feedback_class_vs_instance_test_calls`)
- No regression in 32 baseline TT switcher + 12 renav (PR #34) tests

## New events
- `tt_fg_recovery_attempt` (info) — 1st bad-pkg detect, before monkey
- `tt_fg_recovery_success` (info) — after monkey TT вернулся
- `tt_fg_recovery_failed` (warning) — после monkey foreground всё не TT
- `tt_fg_lost` (error) — unchanged, fires только если recovery already attempted

## Test plan
- [x] 5/5 new tests + 0 regressions
- [x] Codex CLEAN 0 P1 на full PR diff
- [ ] Post-merge 24h: ≥1 `tt_fg_recovery_success` event
- [ ] Post-merge: recovery rate ≥50% (success/attempt)
- [ ] Post-merge: `tt_fg_lost` count drop vs baseline 2/24h

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Записать PR URL для evidence-doc.

---

## Task 6: Post-merge evidence + memory

**Tree:** working (`/home/claude-user/contenthunter/`)

- [ ] **Step 1: Wait for PR merge (user action)**

- [ ] **Step 2: Sync prod tree + verify PM2 restart**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git checkout main
git pull --ff-only origin main
sudo -u root pm2 restart 34 --update-env  # explicit restart, auto-hook may not pull
sleep 5
sudo -u root pm2 jlist | python3 -c "import json,sys,datetime
d=json.load(sys.stdin)
for p in d:
  if p['name']=='autowarm':
    e=p.get('pm2_env',{})
    rt=e.get('restart_time',0)
    ut=e.get('pm_uptime',0)
    print(f'restart_time={rt}, last_start={datetime.datetime.fromtimestamp(ut/1000).isoformat()}')"
```

Expected: restart_time incremented, last_start recent.

- [ ] **Step 3: Verify symbols deployed**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "from publisher_tiktok import TikTokMixin; print(hasattr(TikTokMixin, '_attempt_tt_fg_recovery'))"
```

Expected: `True`.

- [ ] **Step 4: Write evidence doc**

Create `/home/claude-user/contenthunter/docs/evidence/2026-05-11-tt-fg-recovery-shipped.md`:

```markdown
# TT fg-lost app-switch recovery — Shipped <DATE>

**PR:** <PR_URL>
**Merge commit:** <SHA> (squash; branch fix/tt-fg-lost-recovery-20260511 deleted)
**Merged at:** <DATETIME>
**Prod state:** /root/.openclaw/workspace-genri/autowarm @ <SHA>; PM2 autowarm restart_time=<N>
**Spec:** docs/superpowers/specs/2026-05-11-tt-fg-lost-app-switch-recovery-design.md (v1, Codex CLEAN 2 rounds)
**Plan:** docs/superpowers/plans/2026-05-11-tt-fg-lost-recovery-plan.md (v1)

## Context
[Same root-cause summary as spec]

## Shipped
- `_attempt_tt_fg_recovery` helper (monkey reorder-to-front + recheck)
- Wire-in в `_wait_upload_confirmation` outer loop ~line 1042
- 3 new event categories (attempt/success/failed)
- 5 unit tests
- Per-task lazy flag `_tt_fg_recovery_attempted`

## Success metrics tracking (24h)
- [ ] ≥1 `tt_fg_recovery_success` event
- [ ] recovery rate ≥50% (success / attempt)
- [ ] `tt_fg_lost` count drop vs baseline 2/24h

## SQL queries

(копировать из spec Verify path секции)
```

Commit:

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/2026-05-11-tt-fg-recovery-shipped.md
git commit -m "docs(evidence): TT fg-lost recovery shipped <DATE>"
git push origin main
```

- [ ] **Step 5: Update memory**

Create `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_tt_fg_recovery_shipped.md`:

```markdown
---
name: TT fg-lost app-switch recovery — shipped <DATE> PR #<N>
description: pkg-switch (Launcher/Camera) после AI Unstuck → monkey reorder-to-front + reset overlay_streak; 1 attempt per task
type: project
---

## Context
2026-05-11 discovery: tt_fg_lost (2/24h) — AI Unstuck blind-tap → edge UI → Samsung Launcher/Camera. dismiss_overlay_dialogs не handle'ит app-switch.

## Shipped
- `_attempt_tt_fg_recovery(overlay_pkg, overlay_streak) -> bool` в TikTokMixin
- Wire-in в `_wait_upload_confirmation` outer loop при `_pkg != 'com.zhiliaoapp.musically' and != 'com.android.permissioncontroller' and not _tt_fg_recovery_attempted`
- monkey -p com.zhiliaoapp.musically LAUNCHER 1 + 2.5s sleep + recheck topResumedActivity
- 1 attempt per task через lazy `getattr` flag
- 3 events: tt_fg_recovery_attempt / _success / _failed
- PR <PR_URL>

## How to apply
Если жалобы на TT publishing fails:
1. error_code='tt_fg_lost' → recovery не помог (или уже attempted). Группируй по `events.meta.category`:
   - `tt_fg_recovery_attempt` → bad pkg detected
   - `tt_fg_recovery_success` → recovery вернул TT (но потом опять fg-lost?)
   - `tt_fg_recovery_failed` → monkey не помог; cold-restart needed?
2. Если recovery rate <30% → TT process killed too aggressively, рассмотреть cold-restart fallback в follow-up spec.
3. Если recovery rate >70% → fix work; root cause prevention (B/C в backlog) low priority.
```

Add to MEMORY.md (под TT-related группой):

```
- [TT fg-lost recovery ✅ SHIPPED <DATE> PR #<N>](project_tt_fg_recovery_shipped.md) — app-switch (Launcher/Camera) → monkey reorder-to-front; 1 attempt + reset streak; 3 new events
```

- [ ] **Step 6: Update BACKLOG**

В `/home/claude-user/contenthunter/agents/genri/BACKLOG.md`, section "🔴 TT followups (после 24ч verify)", удалить пункт 1 (`tt_fg_lost` downstream) — он shipped. Если есть пункт про "prevention" (Approach B/C blind-tap clamp) — оставить как low-priority.

Commit + push:

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/ agents/genri/BACKLOG.md
git commit -m "docs(evidence+backlog): TT fg-lost recovery shipped <DATE>"
git push origin main
```

---

## Definition of Done

- 5 helper tests — 5 PASSED
- Wire-in в wait_upload loop — no regression в 32 baseline + 12 renav tests
- Class-level hasattr `True`
- Codex review CLEAN (0 P1) на full PR diff
- PR merged, prod autowarm на новой sha
- PM2 restart_time incremented
- Evidence doc committed
- Memory entry created + indexed
- 24h success metric tracked в evidence-doc (deferred)

## Backlog (после shipped)

- Approach B: clamp blind FALLBACK coords + AI Unstuck taps от edge zones (y<100, y>2270, x<30, x>1050) — prevention. Low priority после recovery shipped.
- Approach C: AI Unstuck post-tap topResumedActivity check + abort если не TikTok — vision call cost overhead, deferred.
- Cold-restart fallback в `_attempt_tt_fg_recovery` если monkey reorder fails (TT process killed by Android memory pressure). Conditional на recovery_rate <30% observed в проде.
- IG/YT similar app-switch detection — если когда-то возникнет в их wait_upload loops.
