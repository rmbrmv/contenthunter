# IG `_wait_instagram_upload` diagnostic instrumentation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить 2 structured diagnostic events (iter0 + timeout) в `_wait_instagram_upload` для capture full topResumedActivity + ui_dump_url + share-button candidates list, и расширить существующий wait-event meta. Это infrastructure для distinguishing 3 candidate root causes (A/B/C) спайка `ig_upload_confirmation_timeout` failures.

**Architecture:** Pure helper `_collect_share_candidates(ui_xml)` извлекает share-кандидаты через `xml.etree.ElementTree`. В `_wait_instagram_upload` добавлены 2 instrumentation блока (iter0 после `set_step`, timeout перед существующим error log). Existing helpers `_save_debug_ui_dump`, `dump_ui`, `adb`, `log_event` переиспользуются. Никаких behavior changes — только additive logging.

**Tech Stack:** Python 3 (stdlib `xml.etree.ElementTree`, `unittest.mock`), pytest. Repo `autowarm-testbench` (auto-pushed в `GenGo2/delivery-contenthunter`).

**Spec:** `docs/superpowers/specs/2026-05-08-ig-wait-upload-diag-instrumentation-design.md`

---

## Task 1: Изоляция — feature branch + worktree

**Files:**
- Create: `/home/claude-user/autowarm-testbench-ig-diag/` (worktree)

- [ ] **Step 1: `git fetch`**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git log --oneline origin/main -3
```

Expected: видим последний commit `1a90545` (или новее).

- [ ] **Step 2: Создать worktree на новой feature-ветке от свежего origin/main**

```bash
cd /home/claude-user/autowarm-testbench
git worktree add -b feature/ig-wait-upload-diag-2026-05-08 \
  /home/claude-user/autowarm-testbench-ig-diag origin/main
cd /home/claude-user/autowarm-testbench-ig-diag
git status
```

Expected: на новой ветке `feature/ig-wait-upload-diag-2026-05-08`, ahead of origin/main by 0, working tree clean.

- [ ] **Step 3: Baseline — все existing tests green**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
python3 -m pytest tests/ -x --tb=short 2>&1 | tail -10
```

Expected: full test suite passes (или те же pre-existing failures что и раньше). Если новые fails — STOP, состояние base broken.

---

## Task 2: TDD red — `_collect_share_candidates` 5 failing tests

**Files:**
- Create: `tests/test_ig_share_candidates.py`

- [ ] **Step 1: Создать test file**

Write to `/home/claude-user/autowarm-testbench-ig-diag/tests/test_ig_share_candidates.py`:

```python
"""Unit-тесты для _collect_share_candidates helper в publisher_instagram.

Pure-function helper извлекает все ноды UI XML где text/desc содержит
один из share-keyword'ов (Поделиться/Share/Опубликовать). Используется
wait_upload diag instrumentation для отладки 'Share button tapped wrong
element' гипотезы.

Запуск: cd /home/claude-user/autowarm-testbench && pytest tests/test_ig_share_candidates.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_stub():
    """Минимальный stub DevicePublisher для вызова _collect_share_candidates."""
    from publisher import DevicePublisher
    stub = DevicePublisher.__new__(DevicePublisher)
    return stub


def test_collect_share_candidates_finds_button_in_text():
    """Нода с text='Поделиться' clickable=true → 1 candidate с правильными полями."""
    stub = _make_stub()
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        '<hierarchy>'
        '<node text="Поделиться" content-desc="" bounds="[100,2000][900,2200]" '
        'clickable="true" resource-id="com.instagram.android:id/share_button"/>'
        '</hierarchy>'
    )
    out = stub._collect_share_candidates(xml)
    assert len(out) == 1
    c = out[0]
    assert c['text'] == 'Поделиться'
    assert c['content_desc'] == ''
    assert c['bounds'] == '[100,2000][900,2200]'
    assert c['resource_id'] == 'com.instagram.android:id/share_button'
    assert c['clickable'] is True


def test_collect_share_candidates_filters_non_matching():
    """XML без share-keyword → []."""
    stub = _make_stub()
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        '<hierarchy>'
        '<node text="Лента" content-desc="" bounds="[0,0][100,100]" clickable="true"/>'
        '<node text="Профиль" content-desc="" bounds="[100,0][200,100]" clickable="true"/>'
        '</hierarchy>'
    )
    out = stub._collect_share_candidates(xml)
    assert out == []


def test_collect_share_candidates_caps_at_10():
    """XML с 15 matching nodes → return 10 (limit)."""
    stub = _make_stub()
    nodes = ''.join(
        f'<node text="Поделиться {i}" content-desc="" bounds="[0,{i*100}][100,{(i+1)*100}]" clickable="false"/>'
        for i in range(15)
    )
    xml = f"<?xml version='1.0'?><hierarchy>{nodes}</hierarchy>"
    out = stub._collect_share_candidates(xml)
    assert len(out) == 10


def test_collect_share_candidates_handles_malformed_xml():
    """xml='' и xml='<not-xml' → []."""
    stub = _make_stub()
    assert stub._collect_share_candidates('') == []
    assert stub._collect_share_candidates('<not-xml') == []


def test_collect_share_candidates_includes_clickable_flag():
    """clickable=true и clickable=false ноды distinguished correctly."""
    stub = _make_stub()
    xml = (
        "<?xml version='1.0'?>"
        '<hierarchy>'
        '<node text="Поделиться" content-desc="" bounds="[0,0][100,100]" clickable="true"/>'
        '<node text="" content-desc="Поделиться профилем" bounds="[100,0][200,100]" clickable="false"/>'
        '</hierarchy>'
    )
    out = stub._collect_share_candidates(xml)
    assert len(out) == 2
    by_text = {c['text']: c for c in out}
    assert by_text['Поделиться']['clickable'] is True
    assert by_text['']['clickable'] is False
    assert by_text['']['content_desc'] == 'Поделиться профилем'
```

- [ ] **Step 2: Прогон новых тестов — все 5 должны падать**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
python3 -m pytest tests/test_ig_share_candidates.py -v
```

Expected: 5 failed (AttributeError: 'DevicePublisher' object has no attribute '_collect_share_candidates'). 

- [ ] **Step 3: Commit failing tests**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
git add tests/test_ig_share_candidates.py
git commit -m "test(ig-diag): add _collect_share_candidates tests (red)

5 unit tests за pure helper extracting share-button candidates from
UI XML. Tests fail until helper implemented в Task 3."
```

---

## Task 3: Implement `_collect_share_candidates` helper

**Files:**
- Modify: `publisher_instagram.py` (add helper near other meta-extraction helpers)

- [ ] **Step 1: Найти подходящее место для helper**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
grep -n "_build_ig_editor_timeout_meta\|^    def _" publisher_instagram.py | head -10
```

Expected: видим `_build_ig_editor_timeout_meta` или похожий helper. Helper `_collect_share_candidates` добавляется рядом (cohesion).

- [ ] **Step 2: Добавить `_collect_share_candidates` метод**

Insert ПОСЛЕ метода `_build_ig_editor_timeout_meta` (или похожего helper в районе line 1655). Точное расположение — за концом existing helper, перед `def _wait_instagram_upload`.

```python
    def _collect_share_candidates(self, ui_xml: str) -> list[dict]:
        """Найти все ноды UI XML где text/desc содержит Share-keyword.

        Возвращает list[dict] (≤10) с per-candidate: text, content_desc, bounds,
        resource_id, clickable. Используется wait_upload diag instrumentation для
        отладки 'Share button tapped wrong element' гипотезы.
        """
        SHARE_KW = ('Поделиться', 'Share', 'Опубликовать')
        out: list[dict] = []
        if not ui_xml:
            return out
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return out
        for node in root.iter('node'):
            text = (node.get('text') or '').strip()
            desc = (node.get('content-desc') or '').strip()
            if not any(kw in text or kw in desc for kw in SHARE_KW):
                continue
            out.append({
                'text': text[:80],
                'content_desc': desc[:80],
                'bounds': node.get('bounds', ''),
                'resource_id': node.get('resource-id', ''),
                'clickable': node.get('clickable') == 'true',
            })
            if len(out) >= 10:
                break
        return out
```

- [ ] **Step 3: Прогон тестов helper'а — все 5 green**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
python3 -m pytest tests/test_ig_share_candidates.py -v
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add publisher_instagram.py
git commit -m "feat(ig-diag): add _collect_share_candidates pure helper

Pure function extracts all UI XML nodes where text/content-desc
contains Share-keyword (Поделиться/Share/Опубликовать). Used by
upcoming wait_upload diag instrumentation. Cap 10 candidates,
graceful on malformed XML.

5/5 tests green."
```

---

## Task 4: TDD red — diag events behavior tests

**Files:**
- Create: `tests/test_publisher_instagram_wait_upload_diag.py`

- [ ] **Step 1: Создать test file с 2 failing tests**

Write to `/home/claude-user/autowarm-testbench-ig-diag/tests/test_publisher_instagram_wait_upload_diag.py`:

```python
"""Unit-тесты для diag events в _wait_instagram_upload.

Цель: instrumentation events на iter0 (start) и timeout (exhaustion)
содержат полные данные (topResumedActivity, ui_dump_url, share_candidates)
для отладки ig_upload_confirmation_timeout failures.

Запуск: cd /home/claude-user/autowarm-testbench && pytest tests/test_publisher_instagram_wait_upload_diag.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_publisher_stub(adb_responses=None, dump_ui_response=None,
                          ui_dump_url='https://s3/test_dump.xml'):
    """Минимальный stub DevicePublisher для вызова _wait_instagram_upload."""
    from publisher import DevicePublisher
    stub = DevicePublisher.__new__(DevicePublisher)
    stub.task_id = 9999
    stub.adb_host = '127.0.0.1'
    stub.adb_port = 1234
    stub.device_serial = 'TESTSERIAL'
    stub.platform = 'Instagram'
    stub.account = 'test_user'
    stub._collected_screenshots = []
    stub._collected_ui_dumps = []
    stub.set_step = MagicMock()
    stub.log_event = MagicMock()
    stub._safe_kb_probe = MagicMock()
    stub._save_debug_artifacts = MagicMock()
    stub._save_debug_ui_dump = MagicMock(return_value=ui_dump_url)
    stub._save_debug_screenshot = MagicMock(return_value=None)
    stub.dismiss_location_dialog = MagicMock(return_value=False)
    stub.dismiss_overlay_dialogs = MagicMock(return_value=False)
    stub.tap_element = MagicMock(return_value=False)
    # adb mock — поочерёдные ответы либо single string
    if isinstance(adb_responses, list):
        stub.adb = MagicMock(side_effect=adb_responses)
    else:
        stub.adb = MagicMock(return_value=adb_responses or '')
    stub.dump_ui = MagicMock(return_value=dump_ui_response or '<hierarchy/>')
    return stub


def test_wait_upload_iter0_diag_event_logged():
    """На старте wait_upload должен emit'нуться wait_upload_iter0_diag event.

    Verifies always-fire (даже на success path где iteration 0 уже finds MainTabActivity).
    """
    # adb returns MainTabActivity → loop ends fast (1 iteration)
    activity_str = 'topResumedActivity=ActivityRecord{abc u0 com.instagram.android/.activity.MainTabActivity t123}'
    ui_xml = (
        "<?xml version='1.0'?><hierarchy>"
        '<node text="Поделиться" content-desc="" bounds="[100,2000][900,2200]" '
        'clickable="true" resource-id="com.instagram.android:id/share_button"/>'
        '</hierarchy>'
    )
    stub = _make_publisher_stub(adb_responses=activity_str, dump_ui_response=ui_xml,
                                  ui_dump_url='https://s3/iter0.xml')

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    # Find iter0_diag log_event call
    iter0_calls = [
        call for call in stub.log_event.call_args_list
        if call.kwargs.get('meta', {}).get('category') == 'wait_upload_iter0_diag'
    ]
    assert len(iter0_calls) == 1, f'expected 1 iter0_diag event, got {len(iter0_calls)}: {stub.log_event.call_args_list}'
    meta = iter0_calls[0].kwargs['meta']
    assert 'topResumedActivity' in meta
    assert 'MainTabActivity' in meta['topResumedActivity']
    assert meta['ui_dump_url'] == 'https://s3/iter0.xml'
    assert isinstance(meta['share_candidates'], list)
    assert len(meta['share_candidates']) == 1
    assert meta['share_candidates'][0]['text'] == 'Поделиться'


def test_wait_upload_timeout_diag_event_logged():
    """На timeout-exhaustion должен emit'нуться wait_upload_timeout_diag event."""
    # adb всегда возвращает InstagramMainActivity (не MainTabActivity) → 30 iterations exhaust
    stuck_activity = 'topResumedActivity=ActivityRecord{abc u0 com.instagram.android/com.instagram.mainactivity.InstagramMainActivity t456}'
    ui_xml = '<hierarchy/>'
    stub = _make_publisher_stub(adb_responses=stuck_activity, dump_ui_response=ui_xml,
                                  ui_dump_url='https://s3/timeout.xml')

    with patch('time.sleep'):
        stub._wait_instagram_upload()

    timeout_calls = [
        call for call in stub.log_event.call_args_list
        if call.kwargs.get('meta', {}).get('category') == 'wait_upload_timeout_diag'
    ]
    assert len(timeout_calls) == 1, f'expected 1 timeout_diag event, got {len(timeout_calls)}'
    meta = timeout_calls[0].kwargs['meta']
    assert 'topResumedActivity' in meta
    assert 'InstagramMainActivity' in meta['topResumedActivity']
    assert meta['ui_dump_url'] == 'https://s3/timeout.xml'
    assert isinstance(meta['share_candidates'], list)
```

- [ ] **Step 2: Прогон новых тестов — оба должны падать**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
python3 -m pytest tests/test_publisher_instagram_wait_upload_diag.py -v
```

Expected: 2 failed (instrumentation events не emit'ятся пока).

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_publisher_instagram_wait_upload_diag.py
git commit -m "test(ig-diag): wait_upload iter0+timeout diag events (red)

2 behavior tests verifying instrumentation events emit на старте и
timeout. Stub mocks adb/dump_ui/_save_debug_ui_dump. Tests fail until
implementation в Task 5."
```

---

## Task 5: Implement iter0 + timeout diag в `_wait_instagram_upload`

**Files:**
- Modify: `publisher_instagram.py:1659-1965` (existing `_wait_instagram_upload`)

- [ ] **Step 1: Добавить iter0 diag block ПОСЛЕ `set_step` и `published = False`, перед `for wait in range(30)`**

Найти location:
```bash
cd /home/claude-user/autowarm-testbench-ig-diag
grep -n "self.set_step('Instagram: ожидание загрузки" publisher_instagram.py
```

Expected: находим line ~1663.

Insert после `published = False` (одна-две строки ниже set_step) и перед `# Строгие признаки успеха` или `SUCCESS_KW =`:

```python
        # === Diagnostic instrumentation iter0 ===
        # Capture state IMMEDIATELY post-Share для post-mortem analysis ig_upload_confirmation_timeout.
        try:
            iter0_act = self.adb('dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
                                  timeout=8) or ''
            iter0_ui_xml = self.dump_ui()
            iter0_dump_url = self._save_debug_ui_dump('wait_upload_iter0')
            iter0_candidates = self._collect_share_candidates(iter0_ui_xml)
            self.log_event('info', 'Instagram: wait_upload iter0 diag',
                           meta={'category': 'wait_upload_iter0_diag',
                                 'platform': self.platform,
                                 'topResumedActivity': iter0_act.strip()[:300],
                                 'ui_dump_url': iter0_dump_url,
                                 'share_candidates': iter0_candidates})
        except Exception as _diag_e:
            log.warning(f'wait_upload iter0 diag failed: {_diag_e}')
```

- [ ] **Step 2: Добавить timeout diag block внутри `if not published:`, ПЕРЕД `_safe_kb_probe`**

Найти location:
```bash
grep -n "if not published:" publisher_instagram.py | head -3
```

Expected: видим line ~1958. Insert ПОСЛЕ `if not published:` line, ПЕРЕД `# 'ui' is bound by the range(30) loop above`:

```python
        if not published:
            # === Diagnostic instrumentation timeout ===
            try:
                timeout_act = self.adb('dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
                                        timeout=8) or ''
                timeout_ui_xml = self.dump_ui()
                timeout_dump_url = self._save_debug_ui_dump('wait_upload_timeout')
                timeout_candidates = self._collect_share_candidates(timeout_ui_xml)
                self.log_event('info', 'Instagram: wait_upload timeout diag',
                               meta={'category': 'wait_upload_timeout_diag',
                                     'platform': self.platform,
                                     'topResumedActivity': timeout_act.strip()[:300],
                                     'ui_dump_url': timeout_dump_url,
                                     'share_candidates': timeout_candidates})
            except Exception as _tdiag_e:
                log.warning(f'wait_upload timeout diag failed: {_tdiag_e}')

            # `ui` is bound by the range(30) loop above (always iterates ≥1).
            self._safe_kb_probe(ui, step='ig_upload_confirmation_timeout')
            ...
```

(Existing code under `if not published:` остаётся неизменным, добавляется только diag block в начале.)

- [ ] **Step 3: Прогон новых diag-тестов — оба green**

```bash
python3 -m pytest tests/test_publisher_instagram_wait_upload_diag.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Прогон существующих publisher_instagram-тестов — green**

```bash
python3 -m pytest tests/test_publisher_ig_camera_recovery.py tests/test_ig_*.py -v 2>&1 | tail -10
```

Expected: все existing IG tests stay green (no behavior change).

- [ ] **Step 5: Commit**

```bash
git add publisher_instagram.py
git commit -m "feat(ig-diag): emit iter0+timeout diag events in _wait_instagram_upload

Captures full topResumedActivity (no truncation), S3 ui_dump_url,
и share-button candidates list at:
- iter0: directly after Share tap, pre-loop
- timeout: после 30-iteration exhaustion, before _safe_kb_probe

Both wrapped в try/except — diag failure не должно ломать publish.
2/2 new behavior tests green. Existing IG tests unchanged."
```

---

## Task 6: Расширить existing wait-event meta

**Files:**
- Modify: `publisher_instagram.py:1900` (existing `Instagram: wait {wait}` log_event)

- [ ] **Step 1: Найти existing log_event call**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
grep -n "Instagram: wait {wait}" publisher_instagram.py
```

Expected: видим line ~1900.

- [ ] **Step 2: Расширить meta**

Заменить existing call с meta=None (или без meta) на:

Существующий код примерно:
```python
self.log_event('info', f'Instagram: wait {wait} — act={act_diag.strip()[-50:]}, ui={str(_ig_texts)[:150]}')
```

Заменить на:
```python
self.log_event('info', f'Instagram: wait {wait} — act={act_diag.strip()[-50:]}, ui={str(_ig_texts)[:150]}',
               meta={'category': 'wait_upload_iter_diag',
                     'iteration': wait,
                     'topResumedActivity_full': act_diag.strip()[:300],
                     'ui_brief': _ig_texts[:8]})
```

- [ ] **Step 3: Прогон IG tests**

```bash
python3 -m pytest tests/test_publisher_instagram_wait_upload_diag.py tests/test_ig_*.py -v 2>&1 | tail -15
```

Expected: все green.

- [ ] **Step 4: Commit**

```bash
git add publisher_instagram.py
git commit -m "feat(ig-diag): enrich existing wait events с full topResumedActivity

Existing wait events на line ~1900 ловили только act_diag.strip()[-50:]
(truncated). Добавлен meta с topResumedActivity_full (300-char limit) и
ui_brief list. Existing log msg остаётся (back-compat для existing
analytics patterns). Diagnostic enrichment for ig_upload_confirmation_timeout."
```

---

## Task 7: Final pytest gate

**Files:**
- Run: pytest на полном тестбенче

- [ ] **Step 1: Full test suite**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
python3 -m pytest tests/ -x --tb=short 2>&1 | tail -15
```

Expected: все tests green (новые 7 + existing).

- [ ] **Step 2: Sanity offline check — модуль импортируется**

```bash
python3 -c "from publisher_instagram import InstagramMixin; print('OK', hasattr(InstagramMixin, '_collect_share_candidates'))"
```

Expected: `OK True`.

---

## Task 8: Push + merge → main + prod deploy

**Files:**
- Operate: branches на autowarm-testbench и `/root/.openclaw/workspace-genri/autowarm/` prod

- [ ] **Step 1: Push feature branch**

```bash
cd /home/claude-user/autowarm-testbench-ig-diag
git push -u origin feature/ig-wait-upload-diag-2026-05-08
```

- [ ] **Step 2: Merge → autowarm-testbench main**

```bash
cd /home/claude-user/autowarm-testbench
git checkout main
git pull --ff-only origin main
git merge --no-ff feature/ig-wait-upload-diag-2026-05-08 \
  -m "merge feature/ig-wait-upload-diag-2026-05-08 — IG wait_upload diag instrumentation"
git push origin main
```

- [ ] **Step 3: Cleanup worktree + local branch**

```bash
git worktree remove /home/claude-user/autowarm-testbench-ig-diag
git branch -d feature/ig-wait-upload-diag-2026-05-08
```

- [ ] **Step 4: Pull в prod + reload pm2**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git pull --ff-only origin main
git log --oneline -3
sudo -n pm2 reload autowarm
sudo -n pm2 status autowarm | head -3
```

Expected: 
- Видим merge commit на top.
- pm2 status=online, restart counter +1.

- [ ] **Step 5: Verify cwd**

```bash
sudo -n pm2 describe autowarm | grep "exec cwd"
```

Expected: `exec cwd = /root/.openclaw/workspace-genri/autowarm`. Если другая — `pm2 delete autowarm && pm2 start ecosystem.config.js && pm2 save`.

---

## Task 9: Live evidence collection

**Files:**
- Read: `publish_tasks.events` JSONB через psql

- [ ] **Step 1: Wait period — let natural fails accumulate**

Текущий rate ~1-2 ig_upload_confirmation_timeout fails/час. Через 60-90 минут после deploy ожидаем 2-3 свежих fail tasks с iter0_diag и timeout_diag events.

Schedule wakeup или просто wait и проверить через ~75 минут:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT pt.id, pt.account, pt.error_code,
       COUNT(*) FILTER (WHERE e->'meta'->>'category' = 'wait_upload_iter0_diag') AS iter0,
       COUNT(*) FILTER (WHERE e->'meta'->>'category' = 'wait_upload_timeout_diag') AS timeout_diag
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.platform='Instagram' 
  AND pt.error_code='ig_upload_confirmation_timeout'
  AND pt.started_at > NOW() - INTERVAL '2 hours'
GROUP BY pt.id, pt.account, pt.error_code
ORDER BY pt.id DESC LIMIT 10;
"
```

Expected: новые fail tasks имеют 1 iter0 + 1 timeout_diag event каждый. Если 0 — instrumentation не сработал, диагностировать pm2 cwd / import errors.

- [ ] **Step 2: Извлечь iter0+timeout meta для analysis**

Для одной свежей fail-задачи (например LATEST_TIMEOUT_TASK_ID найден в Step 1):

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT e->'meta' AS meta
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.id = <LATEST_TIMEOUT_TASK_ID>
  AND e->'meta'->>'category' IN ('wait_upload_iter0_diag', 'wait_upload_timeout_diag')
ORDER BY e->>'ts';
"
```

Expected output показывает full topResumedActivity, ui_dump_url, share_candidates list.

- [ ] **Step 3: Скачать UI dump из iter0**

```bash
curl -s '<URL_FROM_meta_ui_dump_url>' -o /tmp/ig_diag_iter0.xml
wc -c /tmp/ig_diag_iter0.xml
```

Expected: XML downloaded (~30-80KB).

- [ ] **Step 4: Inspect what's actually visible на iter0 screen**

```bash
python3 -c "
import xml.etree.ElementTree as ET
xml = open('/tmp/ig_diag_iter0.xml').read()
root = ET.fromstring(xml)
for n in root.iter('node'):
    text = (n.get('text') or '').strip()
    desc = (n.get('content-desc') or '').strip()
    if text or desc:
        print(f'  text={text[:50]!r} desc={desc[:50]!r} clickable={n.get(\"clickable\")} bounds={n.get(\"bounds\")}')
" | head -30
```

Expected: видим какие UI elements visible immediately after Share tap. Если editor caption + Share button visible → tap не доставлен (Mode B). Если другой layout → другая mode.

- [ ] **Step 5: Determine root cause (A/B/C)**

На основе данных шагов 2-4 — один из 3 cases:

- **A — IG version drift** (`InstagramMainActivity` legitimate post-publish destination): UI dump shows feed/empty UI, не editor; share_candidates list пуст или absent.
- **B — Share tap не доставлен** (selector ambiguous): UI dump показывает editor caption screen; share_candidates list НЕ пуст; clickable=true Share button присутствует.
- **C — Transient dialog auto-dismissed**: UI dump показывает editor (как B), но между iter0 и timeout видим другие events (audio dialog, linked-content dialog).

Записать findings в evidence-файл `docs/evidence/2026-05-08-ig-wait-upload-instrumentation-findings.md`.

- [ ] **Step 6: Commit evidence**

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/2026-05-08-ig-wait-upload-instrumentation-findings.md
git commit -m "docs(evidence): IG wait_upload instrumentation — root cause findings

Iter0+timeout diag events deployed to prod. <N> live fail tasks
analyzed, root cause = <A/B/C>. Next: spec for actual fix."
```

---

## Self-review checklist

1. **Spec coverage:**
   - ✅ Section 2.1 (extend, not replace) → Tasks 5-6 additive only.
   - ✅ Section 3.1 iter0 event → Task 5 Step 1.
   - ✅ Section 3.2 timeout event → Task 5 Step 2.
   - ✅ Section 3.3 wait-event meta enrichment → Task 6.
   - ✅ Section 4 `_collect_share_candidates` helper → Tasks 2-3.
   - ✅ Section 5.1 5 pure helper tests → Task 2.
   - ✅ Section 5.2 2 behavior tests → Task 4.
   - ✅ Section 7 R1-R5 risks — все mitigated в коде (try/except wraps; existing helpers; limit 10).
   - ✅ Section 8 DoD — все pieces в Tasks 2-9.

2. **Placeholder scan:** все exact paths, complete code blocks. No "TBD"/"TODO". `<LATEST_TIMEOUT_TASK_ID>` в Task 9 Step 2 — это PLACEHOLDER но contextual (filled at runtime from Step 1 query).

3. **Type consistency:**
   - `_collect_share_candidates(self, ui_xml: str) -> list[dict]` ✅
   - log_event meta keys: `category`, `platform`, `topResumedActivity`, `ui_dump_url`, `share_candidates` (consistent через iter0 + timeout) ✅
   - `topResumedActivity_full` (only in Task 6 wait-event meta) — different key from `topResumedActivity` (iter0/timeout) — intentional ✅

4. **Branch isolation:** Task 1 явно использует `git worktree add` в `/home/claude-user/autowarm-testbench-ig-diag/` — не stомпает на other claude sessions.
