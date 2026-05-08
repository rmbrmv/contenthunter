# TT publish stabilization Phase 1.5 — audio-dialog fix + inventory

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan.

**Goal:** Закрыть `tt_upload_confirmation_timeout` audio-dialog stuck loop (corrupt main publish-stage failure mode после Phase-1 unblock'а switcher) и почистить inventory `gennadiya4` на phone #19. Цель — TT smoke на phone #19 даёт ≥80%/5 done через user70415121188138.

**Architecture:** Изменения в `publisher_tiktok.py` (audio-dialog detector loop расширение) + `publisher_kernel.py` (новый error_code mapping). Inventory cleanup — SQL (`factory_inst_accounts.active=false`). Тесты — pytest, fixtures в `tests/fixtures/`.

**Path conventions:**
- **Working tree (specs/plans/evidence):** `/home/claude-user/contenthunter/.claude/worktrees/tt-publish-design-20260508/`. Branch `worktree-tt-publish-design-20260508`.
- **Deploy tree (autowarm code):** `/root/.openclaw/workspace-genri/autowarm/`. Branch `fix/tt-bound-nav-phase1` (continue Phase-1 branch — Phase 1.5 commits stack on top).

**Tech Stack:** Python 3.11, pytest, MagicMock, ADB; vision через `publisher_vision_recovery.attempt_vision_recovery`.

## Context — what we know

Из Phase-1 smoke (evidence `2026-05-08-tt-publish-phase1-phone19-smoke.md`):

- TT publish-stage (после успешного switcher на active account) показывает audio-dialog с markers `Sound name`/`Original sound`/etc.
- `publisher_tiktok.py:514-537` ловит этот dialog, пытается `tap_element` на `Пропустить`/`Skip`/`Закрыть`/`Готово`/`Использовать`/`Use` (clickable_only=True/False).
- Если ничего не находит → `adb_tap(830, 1950)` blind fallback.
- TT 44.4.3: ни text-based tap, ни blind tap не закрывают dialog. Loop из 54-59 итераций → `tt_upload_confirmation_timeout`.
- Inventory: `gennadiya4` (pack 19b, fia.id=1629) не залогинен в TT app phone #19, но active=true в DB.

## File map

**Modify (deploy tree):**
- `publisher_tiktok.py` — audio-dialog branch (lines ~514-537).
- `publisher_kernel.py` — new step→category mapping для `tt_audio_dialog_stuck`.

**Create (deploy tree):**
- `tests/test_tt_audio_dialog.py` — TDD tests для audio-dialog logic.

**Working tree:**
- `docs/evidence/2026-05-08-tt-publish-phase1_5-smoke.md` (T7).

**SQL action:**
- `UPDATE factory_inst_accounts SET active=false WHERE id=1629` (gennadiya4 deactivate).

---

## Task 1: Inventory cleanup — gennadiya4 deactivate

**Tree:** DB only

> **Why first:** не хотим тратить smoke time на gennadiya4 fails (5/10 во время Phase-1 smoke).

- [ ] **Step 1: Verify accounts state**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT fia.id, fia.username, fia.active, fpa.pack_name
FROM factory_inst_accounts fia
JOIN factory_pack_accounts fpa ON fia.pack_id = fpa.id
JOIN factory_device_numbers fdn ON fdn.id = fpa.device_num_id
WHERE fdn.device_number = 19 AND fia.platform='tiktok'
ORDER BY fia.id DESC;
"
```

Expected: `gennadiya4 id=1629 active=t`, `user70415121188138 active=t`.

- [ ] **Step 2: Live phone check — confirm gennadiya4 not logged in**

```bash
ADB="adb -H 82.115.54.26 -P 15068 -s RF8YA0W57EP"
$ADB shell am force-stop com.zhiliaoapp.musically
sleep 2
$ADB shell monkey -p com.zhiliaoapp.musically -c android.intent.category.LAUNCHER 1
sleep 12
$ADB shell uiautomator dump --compressed /sdcard/d.xml
$ADB pull /sdcard/d.xml /tmp/tt_phone19_active.xml
grep -oE 'text="@?[\w._]+"' /tmp/tt_phone19_active.xml | grep -E 'gennadiya4|user70415' | head -5
```

If only `user70415121188138` matches → confirms gennadiya4 not on device.

If `gennadiya4` is also visible (in account-switcher, switched-out state) → re-evaluate; maybe just inactive but logged in. In that case do NOT deactivate (operator action — manual switch).

- [ ] **Step 3 (only if Step 2 confirms not-logged-in): Deactivate**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
UPDATE factory_inst_accounts SET active=false
WHERE id = 1629 AND username = 'gennadiya4' AND platform='tiktok';
SELECT id, username, active FROM factory_inst_accounts WHERE id = 1629;
"
```

Expected: 1 row updated, active=f.

- [ ] **Step 4: Document in evidence**

Add a short note in `docs/evidence/2026-05-08-tt-publish-phase1_5-smoke.md` (will create in T7) — "gennadiya4 deactivated 2026-05-08 due to phone #19 logout drift; needs manual re-login if продолжать использовать".

No commits in this task — DB state change only. Audit log captured in `factory_inst_accounts.synced_at`.

---

## Task 2: Add `tt_audio_dialog_stuck` step→category mapping

**Tree:** deploy

- [ ] **Step 1: Add mapping**

In `publisher_kernel.py`, after the existing TT entries (around the entries we added in Phase-1 T2), append:

```python
    # [Phase 1.5 2026-05-08] Audio-dialog stuck loop — TT 44.4.3 button drift.
    # Triggered when audio-dialog detector runs >MAX_AUDIO_DIALOG_ITERATIONS
    # без UPLOAD_OK confirmation (publisher_tiktok.py audio-dialog branch).
    'tt_5_audio_dialog_stuck': 'tt_audio_dialog_stuck',
```

- [ ] **Step 2: Add test**

Create `tests/test_tt_audio_dialog.py`:

```python
"""Phase 1.5 TT audio-dialog stabilization tests.

Запуск:
    cd /root/.openclaw/workspace-genri/autowarm
    pytest tests/test_tt_audio_dialog.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publisher_kernel import _SWITCHER_STEP_TO_CATEGORY  # noqa: E402

FIXTURES = ROOT / 'tests' / 'fixtures'


def test_audio_dialog_stuck_category_mapped():
    """Phase 1.5: новая категория для audio-dialog stuck."""
    assert _SWITCHER_STEP_TO_CATEGORY['tt_5_audio_dialog_stuck'] == 'tt_audio_dialog_stuck'
```

- [ ] **Step 3: Run + commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_tt_audio_dialog.py -v
git add publisher_kernel.py tests/test_tt_audio_dialog.py
git commit -m "feat(switcher): tt_audio_dialog_stuck step→category — Phase 1.5"
```

---

## Task 3: Add ui_dump instrumentation + retry cap

**Tree:** deploy
**Files:**
- Modify: `publisher_tiktok.py:514-537` (audio-dialog branch)
- Modify: `tests/test_tt_audio_dialog.py`

> **Why:** publish-stage сейчас не сохраняет ui_dump (только switcher через `_save_dump`). Без dump'а evidence невозможен. Cap прервёт unbounded loop.

- [ ] **Step 1: Read existing audio-dialog branch**

```bash
sed -n '510,545p' /root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py
```

Note that `wait` is the outer loop's iteration counter (in `_publish_tiktok`'s confirmation loop). Audio-dialog hits don't break out — they `continue`, so the outer counter increments но specific audio-dialog hits не считаются отдельно.

- [ ] **Step 2: Add MAX constant + helper**

In `publisher_tiktok.py`, near the top of the file (before classes/methods), add:

```python
# Phase 1.5 — audio-dialog retry cap. После N итераций audio-dialog
# detector → fail с tt_audio_dialog_stuck (вместо unbounded loop).
MAX_AUDIO_DIALOG_ITERATIONS = 10
```

Choose 10 as conservative cap — Phase-1 saw 54+ unbounded; 10 attempts × ~12s = ~2 min, before existing 3-min outer timeout.

- [ ] **Step 3: Add audio_dialog_iter counter в audio-dialog branch**

Modify `publisher_tiktok.py:514-537` (the audio-dialog branch). Replace it with:

```python
            # === TikTok: аудио-диалог после публикации ===
            # TikTok может показать диалог "Sound" / "Звук" / "Добавить звук" / "Original sound"
            # после нажатия Поделиться — нужно закрыть/пропустить его
            _tt_audio_markers = [
                'Sound name', 'Название звука', 'Original sound', 'Оригинальный звук',
                'Add sound', 'Добавить звук', 'Your sound', 'Ваш звук',
                'Audio track name', 'Название аудиодорожки',
            ]
            if any(m in ui for m in _tt_audio_markers):
                # [Phase 1.5 2026-05-08] Track audio-dialog iter counter and cap.
                if not hasattr(self, '_audio_dialog_iter'):
                    self._audio_dialog_iter = 0
                self._audio_dialog_iter += 1
                # Save UI dump on first hit (evidence) + every 5 iterations.
                if self._audio_dialog_iter == 1 or self._audio_dialog_iter % 5 == 0:
                    self._publish_save_audio_dialog_dump(ui, self._audio_dialog_iter)
                if self._audio_dialog_iter > MAX_AUDIO_DIALOG_ITERATIONS:
                    log.error(f'  ❌ TikTok: audio-dialog stuck loop > {MAX_AUDIO_DIALOG_ITERATIONS} '
                             f'итераций — fail с tt_audio_dialog_stuck')
                    self.log_event(
                        'error',
                        f'tt_audio_dialog_stuck: audio-dialog loop exceeded {MAX_AUDIO_DIALOG_ITERATIONS} iterations',
                        meta={'category': 'tt_audio_dialog_stuck',
                              'iterations': self._audio_dialog_iter,
                              'step': 'tt_5_audio_dialog_stuck'},
                    )
                    self.set_step('tt_5_audio_dialog_stuck')
                    return False
                log.info(f'  🎵 TikTok: аудио-диалог после публикации — закрываем '
                         f'(шаг {wait}, iter {self._audio_dialog_iter}/{MAX_AUDIO_DIALOG_ITERATIONS})')
                self.log_event(
                    'info',
                    f'TikTok: аудио-диалог → пропускаем (wait {wait}, iter {self._audio_dialog_iter})',
                    meta={'category': 'tt_audio_dialog_attempt',
                          'iter': self._audio_dialog_iter,
                          'wait': wait},
                )
                tapped_tt_audio = self.tap_element(ui, ['Пропустить', 'Skip', 'Не сейчас', 'Not now',
                                                        'Закрыть', 'Close', 'Готово', 'Done',
                                                        'Использовать', 'Use'], clickable_only=True)
                if not tapped_tt_audio:
                    tapped_tt_audio = self.tap_element(ui, ['Пропустить', 'Skip', 'Не сейчас', 'Not now',
                                                             'Закрыть', 'Close', 'Готово', 'Done',
                                                             'Использовать', 'Use'], clickable_only=False)
                if not tapped_tt_audio:
                    log.warning(f'  ⚠️ TikTok: аудио-диалог — кнопка не найдена, fallback tap (830,1950)')
                    self.adb_tap(830, 1950)
                    self.log_event('info', f'TikTok: аудио-диалог fallback tap (830,1950) (wait {wait})')
                time.sleep(2)
                continue
```

- [ ] **Step 4: Add `_publish_save_audio_dialog_dump` helper**

Locate `publisher_tiktok.py` end of class (just before file end). Add helper method:

```python
    def _publish_save_audio_dialog_dump(self, ui_xml: str, iter_num: int) -> None:
        """[Phase 1.5 2026-05-08] Save UI dump на entry в audio-dialog branch.
        Без этого publish-stage не имеет XML evidence (только switcher
        через _save_dump). Reuses publisher.upload_artifact_to_s3 API.
        """
        try:
            from publisher import upload_artifact_to_s3, _cleanup_local_artifact
            import os, tempfile
            fname = f'audio_dialog_iter{iter_num}_{self.task_id}.xml'
            path = os.path.join('/tmp', fname)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(ui_xml or '')
            s3_url = upload_artifact_to_s3(path, 'TikTok', self.task_id, 'ui_dump', 'application/xml')
            url = s3_url or f'/ui_dumps/{fname}'
            _cleanup_local_artifact(path, s3_url)
            self.log_event(
                'info',
                f'audio_dialog_dump iter={iter_num} url={url}',
                meta={'category': 'tt_audio_dialog_dump',
                      'iter': iter_num,
                      'url': url, 'bytes': len(ui_xml or '')},
            )
        except Exception as e:
            log.warning(f'_publish_save_audio_dialog_dump iter={iter_num} error: {e}')
```

- [ ] **Step 5: Tests for retry cap**

In `tests/test_tt_audio_dialog.py`, add:

```python
def test_audio_dialog_retry_cap_constant():
    """Phase 1.5: cap должен быть финитный (10 attempts default)."""
    from publisher_tiktok import MAX_AUDIO_DIALOG_ITERATIONS
    assert isinstance(MAX_AUDIO_DIALOG_ITERATIONS, int)
    assert 5 <= MAX_AUDIO_DIALOG_ITERATIONS <= 20, (
        f'Cap should be conservative; got {MAX_AUDIO_DIALOG_ITERATIONS}'
    )
```

- [ ] **Step 6: Run + commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_tt_audio_dialog.py -v
git add publisher_tiktok.py tests/test_tt_audio_dialog.py
git commit -m "feat(tt-publish): audio-dialog retry cap + UI dump instrumentation (Phase 1.5)"
```

> Note: testing the actual retry-cap behavior end-to-end requires a publish flow context with `wait` loop, which is hard to mock. Focus tests on constant + category mapping. Behavior verified via T6 smoke.

---

## Task 4: Smoke pass 1 — capture audio-dialog UI dumps

**Tree:** deploy + working
**Files:**
- Create (working): `docs/evidence/2026-05-08-tt-publish-phase1_5-smoke.md`
- DB INSERT for tasks

> **Why:** With T3's instrumentation, next smoke produces XML dumps of the audio-dialog. Use these dumps to design T5 (markers/coords/labels update).

- [ ] **Step 1: Restart testbench process to pick up new code**

```bash
sudo pm2 reload autowarm-testbench --update-env
sleep 3
sudo pm2 logs autowarm-testbench --lines 20 --nostream
```

(`TT_BOUND_NAV_ENABLED=true` already set — testbench restored from T9.)

- [ ] **Step 2: Create 5 testbench publish_tasks for user70415121188138 only**

Use the same `<MEDIA_PATH>` as Phase-1 smoke.

```sql
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<EOF
INSERT INTO publish_tasks (
  device_serial, adb_port, adb_host, raspberry, platform, account, project,
  media_path, media_type, caption, hashtags, status, testbench
) VALUES
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_5_smoke',
   '<MEDIA_PATH>', 'video', 'Phase 1.5 #1', '["test"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_5_smoke',
   '<MEDIA_PATH>', 'video', 'Phase 1.5 #2', '["test","tt"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_5_smoke',
   '<MEDIA_PATH>', 'video', 'Phase 1.5 #3', '[]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_5_smoke',
   '<MEDIA_PATH>', 'video', 'Phase 1.5 #4', '["a","b"]'::jsonb, 'pending', true),
  ('RF8YA0W57EP', 15068, '82.115.54.26', 7, 'TikTok', 'user70415121188138', 'phase1_5_smoke',
   '<MEDIA_PATH>', 'video', 'Phase 1.5 #5', '["only"]'::jsonb, 'pending', true);
EOF
```

- [ ] **Step 3: Watch first task to settle (cap'ировано retry → ~2-3 min vs ~10 min unbounded)**

```bash
for i in $(seq 1 15); do
  STATUS=$(PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -t -A -c "
    SELECT id || ':' || status FROM publish_tasks
    WHERE testbench=true AND project='phase1_5_smoke' ORDER BY id LIMIT 1;
  ")
  echo "[$(date +%H:%M:%S)] first task: $STATUS"
  if [[ "$STATUS" != *"running"* && "$STATUS" != *"pending"* ]]; then
    break
  fi
  sleep 60
done
```

If first task settles with `tt_audio_dialog_stuck` (after ~10 retry-cap iterations) → cap works.
If still timeouts at outer 3-min `tt_upload_confirmation_timeout` → cap not engaged (verify in events).

- [ ] **Step 4: Pull audio-dialog UI dumps**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -t -A -c "
SELECT events FROM publish_tasks
WHERE testbench=true AND project='phase1_5_smoke' ORDER BY id LIMIT 1;
" | python3 -c "
import sys, json
events = json.loads(sys.stdin.read())
for e in events:
    msg = (e.get('message','') or e.get('msg',''))
    if 'audio_dialog_dump' in msg:
        for tok in msg.split():
            if tok.startswith('url='):
                print(tok[4:])
"
```

curl each URL, save as `tests/fixtures/tt_audio_dialog_iter1.xml`, etc.

- [ ] **Step 5: Inspect dumps — find what button labels are actually present**

```bash
grep -oE '(text|content-desc|resource-id)="[^"]{1,80}"' tests/fixtures/tt_audio_dialog_iter1.xml | sort -u | head -50
```

Look for buttons that look like "skip"/"continue"/"next"/"done". Record findings into evidence (T7).

- [ ] **Step 6: Wait for all 5 to settle**

(Same polling approach. With cap, each takes ~2-3 min after publish stage = ~6-7 min total.)

- [ ] **Step 7: Document interim results in evidence file**

Create `docs/evidence/2026-05-08-tt-publish-phase1_5-smoke.md` (working tree). Sections:
- Pass 1 results (status counts, tap_method distribution).
- Audio-dialog dump analysis (what real labels/coords are present).
- Recommended T5 changes based on dump evidence.
- Commit (working tree branch).

---

## Task 5: Update audio-dialog detector based on T4 evidence

**Tree:** deploy

> **Why:** Now we have real UI dumps. Update markers/coords/labels accordingly, AND add vision-fallback if no static labels are reliable.

This task's exact code depends on T4 findings — controller will fill in specific changes. Plan-template:

- [ ] **Step 1: Update marker/label list**

In `publisher_tiktok.py`, expand `_tt_audio_markers` (detector) and the `tap_element` button labels list based on T4 dump evidence. Examples (placeholder — will be filled after T4):

```python
# Expand if T4 dumps show new patterns
_tt_audio_markers = [
    # ... existing markers ...
    # T4-discovered marker if any
]

# Update button labels for tap_element
tapped_tt_audio = self.tap_element(ui, [
    # ... existing labels ...
    # T4-discovered labels
], clickable_only=True)
```

- [ ] **Step 2: Add vision-fallback after `tap_element` fails**

Same pattern as Phase-1 T7 vision-fallback. After both `tap_element` attempts fail, BEFORE the blind `(830, 1950)`:

```python
if not tapped_tt_audio:
    # [Phase 1.5 2026-05-08] Vision-fallback for audio-dialog skip button
    try:
        from publisher_vision_recovery import attempt_vision_recovery
        instr = attempt_vision_recovery(
            self.publisher,  # or self if self IS the publisher
            task_id=self.task_id,
            platform='TikTok',
            account=self.account,
            step='tt_5_audio_dialog_skip_button',
            error_code='tt_audio_dialog_button_unreachable',
            extra_hint='Найди кнопку «Пропустить»/«Skip»/«Готово»/«Done» в audio-dialog '
                       'после публикации TikTok. Верни action="tap" с координатами центра кнопки. '
                       'Это диалог выбора звука с big preview thumbnail и одной/двумя кнопками внизу.',
        )
        if instr and getattr(instr, 'action', None) == 'tap':
            self.log_event('info', f'TikTok: audio-dialog vision-tap success', 
                          meta={'category': 'tt_audio_dialog_vision_tap', 'iter': self._audio_dialog_iter})
            # vision recovery already executed tap; just continue
            time.sleep(2)
            continue
    except Exception as e:
        log.warning(f'TikTok audio-dialog vision-fallback failed: {e}')
    # Last fallback: blind tap (legacy)
    log.warning(f'  ⚠️ TikTok: аудио-диалог — кнопка не найдена, fallback tap (830,1950)')
    self.adb_tap(830, 1950)
    self.log_event('info', f'TikTok: аудио-диалог fallback tap (830,1950) (wait {wait})')
```

> Same no-double-tap discipline as Phase-1 T7 — vision recovery already taps internally, don't add `adb_tap` after.

- [ ] **Step 3: Add tests for new markers/labels (if added)**

Append to `tests/test_tt_audio_dialog.py` — small tests verifying that detector recognizes new markers, button label list includes new entries.

- [ ] **Step 4: Run + commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_tt_audio_dialog.py -v
pytest tests/test_account_switcher_tt.py -v 2>&1 | tail -5
git add publisher_tiktok.py tests/test_tt_audio_dialog.py
git commit -m "feat(tt-publish): audio-dialog markers/coords + vision-fallback (Phase 1.5)"
```

---

## Task 6: Smoke pass 2 — verify fix works

**Tree:** deploy + working

- [ ] **Step 1: Restart testbench**

```bash
sudo pm2 reload autowarm-testbench --update-env
sleep 3
```

- [ ] **Step 2: Create 5 fresh testbench tasks**

Same SQL pattern as T4 Step 2, project='phase1_5_smoke_pass2'.

- [ ] **Step 3: Watch settle**

Same polling approach. With audio-dialog fix + cap, expected:
- ≥3-4 done out of 5 (60-80%).
- Remaining failures should NOT be `tt_audio_dialog_stuck` (means cap worked, fix worked).

- [ ] **Step 4: Compute distributions**

Same SQL queries как Phase-1 evidence (status / tap_method / category breakdowns).

---

## Task 7: Final evidence document

**Tree:** working

- [ ] **Step 1: Update `docs/evidence/2026-05-08-tt-publish-phase1_5-smoke.md`**

Comprehensive evidence:
- Pass 1 results (T4) + dump analysis.
- Pass 2 results (T6) + verification of fix.
- Phase 1.5 verdict — works / partial / requires more iteration.
- Recommendations для Phase 2 canary (or further iterations).

- [ ] **Step 2: Commit (working tree)**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/tt-publish-design-20260508
git add docs/evidence/2026-05-08-tt-publish-phase1_5-smoke.md
git commit -m "docs(evidence): TT publish Phase 1.5 — audio-dialog fix verified"
```

---

## Definition of Done

- 0 audio-dialog unbounded loops (cap engages → `tt_audio_dialog_stuck` if needed).
- Real audio-dialog UI dumps captured + analyzed.
- Markers/labels expanded based on real evidence.
- Vision-fallback wired для skip button.
- Smoke pass 2 shows ≥60% done на phone #19 / 5 attempts user70415121188138.
- Evidence committed.

## Backlog (отдельно)

- Phase 2 canary (30 attempts / 4 raspberry / 2 screen classes) — после Phase 1.5 done.
- IG/YT same audio-dialog issue check (memory: 14 cases /7d у TT, IG может иметь similar).
- Production rollout (`TT_BOUND_NAV_ENABLED=true` global) — после Phase 2 success.
