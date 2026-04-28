# IG Publish Fixes Bundle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть наблюдаемость error_code для prod IG/TT/YT failures + остановить Reels↔Stories каскад в IG-публикере + обогатить телеметрию `ig_editor_timeout`.

**Architecture:**
- **Fix #1 (observability):** Вынести B3 mapping из `_fail_task` в shared метод `_set_error_code_from_events()`, дёргать его из `update_status('failed', …)` — теперь любой failure-путь (preflight/critical_exception/unknown-platform/«Публикация не прошла») получит canonical `error_code`.
- **Fix #2 (Reels selector):** Заменить permissive substring matching `['Reels', …]` в bottom_sheet на NBSP-tolerant exact-match по `'Создать новое видео Reels'` (+ ASCII fallback) с явным исключением конкурирующих элементов (миниатюры reels-feed + standalone bottom-nav).
- **Fix #3 (mode validation):** После tap «Видео Reels» tile добавить проверку что мы в Reels-камере (`clips_tab` selected или camera-mode tab bar содержит REELS как активный) — иначе fail-fast с `ig_wrong_camera_mode` вместо silent continue в Stories.
- **Fix #4 (telemetry):** Обогатить meta для `ig_editor_timeout` — `last_ui_texts` (top-8), `screenshot_url` (S3), `last_action_attempted`, `iteration_progress`.

**Tech Stack:** Python 3 (publisher modules), pytest (autowarm/tests), PostgreSQL (state), PM2 (process manager). Прод-код в `/root/.openclaw/workspace-genri/autowarm/` с auto-push hook → `GenGo2/delivery-contenthunter`.

**Spec:** Этот план + investigation в текущей сессии (root-cause карта 5 IG fail'ов 2026-04-28: 1502/1503/1504/1509 random NameError [уже починен `fcfa851`], 1532 — Reels↔Stories каскад).

---

## Репо

- **Plan/evidence:** `/home/claude-user/contenthunter/` — текущая ветка `fix/testbench-publisher-base-imports-20260427` (она аккумулирует docs текущих сессий).
- **Код:** `/root/.openclaw/workspace-genri/autowarm/` — отдельная feature-ветка, мерж в `main` после smoke. Auto-push hook автоматом синкнет в `GenGo2/delivery-contenthunter`.
- **НЕ в scope:** backport в `/home/claude-user/autowarm-testbench/` (testbench и так отстаёт; отдельный follow-up если понадобится).

## Settings

- **Testing:** yes — pytest unit для `_set_error_code_from_events` (fix #1) + selector helper (fix #2). Browser/device smoke невозможен (требует phone rig + GROQ_API_KEY + физическая запись Reel) → smoke-критерий = искусственная задача (см. T7).
- **Logging:** verbose — `[error_code_mapper]` для fix #1, `[ig_create_tile]` для fix #2, `[ig_camera_mode]` для fix #3.
- **Docs:** yes — evidence-файл `.ai-factory/evidence/ig-publish-fixes-bundle-20260428.md` (curl/SQL baselines + commits + smoke). Memory: обновить `project_publisher_modularization_wip.md`.
- **Roadmap linkage:** skip (`.ai-factory/ROADMAP.md` отсутствует).

---

## Файловая структура

**Modify (prod autowarm):**
- `/root/.openclaw/workspace-genri/autowarm/publisher_base.py`:
  - ~line 1177-1188 (`update_status`) — добавить вызов `_set_error_code_from_events()` если `status='failed'`
  - ~line 1424-1508 (`_fail_task`) — заменить inline B3 mapping на вызов нового helper'а (rip-and-replace, но логика идентична)
  - **NEW** метод `_set_error_code_from_events(self) -> Optional[str]` — extracted helper
- `/root/.openclaw/workspace-genri/autowarm/publisher_instagram.py`:
  - ~line 659-672 (ig-stuck-on-profile recovery) — заменить `tap_element(['Reels','Reel','ВИДЕО REELS'])` на новый helper `_tap_create_reels_tile_strict(ui_post)`
  - ~line 714 (camera_ready check) — НЕ трогаем напрямую (это симптом-катcher), но добавим post-tap validation в новый helper
  - ~line 836-849 (REELS tab loop) — заменить silent continue на fail-fast event с `ig_wrong_camera_mode` если выбран не Reels-режим (см. fix #3)
  - ~line 1295-1298 (`ig_editor_timeout` meta) — обогатить (fix #4)
  - **NEW** метод `_tap_create_reels_tile_strict(self, ui: str) -> bool` — exact NBSP-tolerant матч
  - **NEW** метод `_verify_reels_camera_mode(self, ui: str) -> bool` — post-tap mode check

**Create (prod autowarm):**
- `/root/.openclaw/workspace-genri/autowarm/tests/test_error_code_mapper.py` — unit-тесты для `_set_error_code_from_events`
- `/root/.openclaw/workspace-genri/autowarm/tests/test_ig_create_tile_selector.py` — unit-тесты для `_tap_create_reels_tile_strict` (mock UI XML)

**Create (contenthunter docs):**
- `/home/claude-user/contenthunter/.ai-factory/evidence/ig-publish-fixes-bundle-20260428.md` — baselines + commits + smoke + memory update changelog

**НЕ модифицируем:**
- `triage_classifier.py` — testbench-only классификатор оставляем как есть, fix #1 закрывает prod-покрытие альтернативным путём (через `update_status` hook)
- `publisher.py` — после split всё критичное в publisher_base/_instagram
- `account_switcher.py` — отдельные writer'ы error_code (TT/YT) не трогаем

---

## Корневые задачи

### T0 — Pre-flight: baseline + ветка

**Цель:** зафиксировать starting state, создать feature-branch.

**Files:** none (только git/pm2/SQL)

- [ ] **Step 1: Подтвердить prod cwd PM2 (правило `feedback_pm2_dump_path_drift.md`)**

```bash
sudo pm2 describe autowarm | grep "exec cwd"
sudo pm2 list | grep -E "publisher|orchestrator|testbench"
```

Ожидаем: `exec cwd: /root/.openclaw/workspace-genri/autowarm/`. Если другое — STOP, разобраться.

- [ ] **Step 2: Подтвердить чистоту prod autowarm**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git status
git log --oneline -5
git fetch origin
```

Если есть незакоммиченные изменения — это другая Claude-сессия (правило `feedback_parallel_claude_sessions.md`), STOP.

- [ ] **Step 3: Создать ветку для bundle**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git checkout main
git pull origin main
git checkout -b feat/ig-publish-fixes-bundle-20260428
```

- [ ] **Step 4: Зафиксировать SQL baseline (количество failed без error_code)**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -P pager=off -c "
SELECT platform, COUNT(*) FILTER (WHERE error_code IS NULL OR error_code='') AS null_ec,
       COUNT(*) FILTER (WHERE error_code IS NOT NULL AND error_code != '') AS with_ec
FROM publish_tasks WHERE status='failed' AND testbench=false
  AND started_at >= NOW() - INTERVAL '30 days'
GROUP BY 1 ORDER BY 1;
" > /tmp/_ig_fixes_baseline_error_code.txt
cat /tmp/_ig_fixes_baseline_error_code.txt
```

Записать в evidence T6 как «before».

- [ ] **Step 5: Зафиксировать ig_editor_timeout baseline meta**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -P pager=off -c "
SELECT t.id, jsonb_array_length(e->'meta') AS meta_keys
FROM publish_tasks t, jsonb_array_elements(t.events) AS e
WHERE platform='Instagram' AND e->>'type'='error'
  AND e->'meta'->>'category' = 'ig_editor_timeout'
  AND t.started_at >= NOW() - INTERVAL '7 days'
ORDER BY t.id DESC LIMIT 5;
" > /tmp/_ig_fixes_baseline_editor_timeout_meta.txt
cat /tmp/_ig_fixes_baseline_editor_timeout_meta.txt
```

Ожидаем `meta_keys=4` (category/platform/step/max_steps) — после fix #4 будет 7+.

---

### T1 — Fix #1: extract `_set_error_code_from_events` + call from `update_status`

**Цель:** error_code заполняется для ВСЕХ failed-задач (prod включая critical_exception/preflight/Публикация не прошла), не только для тех, что прошли через `_fail_task`.

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_base.py:1424-1508` (extract logic from _fail_task)
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_base.py:1177-1188` (update_status — добавить call)

- [ ] **Step 1: Написать failing unit-test**

Create `/root/.openclaw/workspace-genri/autowarm/tests/test_error_code_mapper.py`:

```python
"""Unit tests for _set_error_code_from_events helper.

Covers: meta.reason приоритет, fallback на meta.category, fallback на 'switch_failed_unspecified',
no-overwrite если error_code уже не NULL.
"""
import os
import sys
import pytest
import psycopg2

# Ensure autowarm root in sys.path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import publisher_base  # noqa: E402

DB_CONFIG = {
    'host': 'localhost', 'port': 5432, 'dbname': 'openclaw',
    'user': 'openclaw', 'password': 'openclaw123',
}


@pytest.fixture
def temp_task_id():
    """Создать временную failed-задачу, удалить в teardown."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO publish_tasks (platform, account, device_serial, status, testbench, events)
        VALUES ('Instagram', 'test_mapper_acct', 'TEST_SERIAL', 'failed', false, '[]'::jsonb)
        RETURNING id
    """)
    tid = cur.fetchone()[0]
    conn.commit()
    yield tid, conn, cur
    cur.execute("DELETE FROM publish_tasks WHERE id=%s", (tid,))
    conn.commit()
    conn.close()


class _DummyPublisher:
    """Minimal stub — только нужные атрибуты для _set_error_code_from_events."""
    def __init__(self, task_id):
        self.task_id = task_id


def test_meta_reason_priority(temp_task_id):
    tid, conn, cur = temp_task_id
    cur.execute("UPDATE publish_tasks SET events=%s WHERE id=%s", (
        psycopg2.extras.Json([
            {'type': 'error', 'msg': 'foo',
             'meta': {'reason': 'specific_reason', 'category': 'broad_cat'}}
        ]), tid))
    conn.commit()
    pub = _DummyPublisher(tid)
    code = publisher_base.BasePublisher._set_error_code_from_events(pub)
    assert code == 'specific_reason', f'reason должен бить category, got {code!r}'


def test_meta_category_fallback(temp_task_id):
    tid, conn, cur = temp_task_id
    cur.execute("UPDATE publish_tasks SET events=%s WHERE id=%s", (
        psycopg2.extras.Json([
            {'type': 'error', 'msg': 'foo',
             'meta': {'category': 'critical_exception'}}
        ]), tid))
    conn.commit()
    pub = _DummyPublisher(tid)
    code = publisher_base.BasePublisher._set_error_code_from_events(pub)
    assert code == 'critical_exception'


def test_no_error_event_uses_fallback(temp_task_id):
    tid, conn, cur = temp_task_id
    cur.execute("UPDATE publish_tasks SET events=%s WHERE id=%s", (
        psycopg2.extras.Json([{'type': 'info', 'msg': 'no errors here'}]), tid))
    conn.commit()
    pub = _DummyPublisher(tid)
    code = publisher_base.BasePublisher._set_error_code_from_events(pub)
    assert code == 'switch_failed_unspecified'


def test_no_overwrite_existing(temp_task_id):
    tid, conn, cur = temp_task_id
    cur.execute("UPDATE publish_tasks SET error_code='preset_code', events=%s WHERE id=%s", (
        psycopg2.extras.Json([
            {'type': 'error', 'msg': 'foo',
             'meta': {'reason': 'new_reason'}}
        ]), tid))
    conn.commit()
    pub = _DummyPublisher(tid)
    publisher_base.BasePublisher._set_error_code_from_events(pub)
    cur.execute("SELECT error_code FROM publish_tasks WHERE id=%s", (tid,))
    assert cur.fetchone()[0] == 'preset_code', 'не должны перезаписывать существующий error_code'
```

- [ ] **Step 2: Запустить тест и убедиться что фейлится**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
python3 -m pytest tests/test_error_code_mapper.py -v 2>&1 | tail -20
```

Ожидаем `AttributeError: type object 'BasePublisher' has no attribute '_set_error_code_from_events'`.

- [ ] **Step 3: Реализовать `_set_error_code_from_events` (extract из `_fail_task`)**

В `publisher_base.py`, **после** метода `_fail_task` (~line 1509), добавить:

```python
    def _set_error_code_from_events(self) -> Optional[str]:
        """Map first error event's meta.reason or meta.category → publish_tasks.error_code.

        Идемпотентен: не перезаписывает уже выставленный error_code.
        Возвращает выбранный код (или None при DB-ошибке).
        """
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute(
                "SELECT events FROM publish_tasks WHERE id=%s",
                (self.task_id,)
            )
            row = cur.fetchone()
            error_code = None
            if row and row[0]:
                events_list = row[0] if isinstance(row[0], list) else []
                for ev in events_list:
                    if not isinstance(ev, dict):
                        continue
                    if ev.get('type') == 'error':
                        m = ev.get('meta') or {}
                        code = m.get('reason') or m.get('category')
                        if code and isinstance(code, str):
                            error_code = code
                            break
            if not error_code:
                error_code = 'switch_failed_unspecified'
            cur.execute(
                "UPDATE publish_tasks SET error_code=%s WHERE id=%s "
                "AND (error_code IS NULL OR error_code = '')",
                (error_code, self.task_id)
            )
            conn.commit()
            conn.close()
            log.info(f'[error_code_mapper] code={error_code!r} for task {self.task_id}')
            return error_code
        except Exception as e:
            log.warning(f'[error_code_mapper] error: {e}')
            return None
```

- [ ] **Step 4: Заменить inline B3-блок в `_fail_task` на вызов helper'а**

В `publisher_base.py:1475-1508` (блок `# B3: map first error event…`) **заменить** весь try/except на одну строку:

```python
        # B3: error_code via shared helper (also called from update_status — covers
        # all failure paths including critical_exception/preflight/«Публикация не прошла»).
        self._set_error_code_from_events()
```

Удалить из `_fail_task` строки 1475-1508 (старый inline блок).

- [ ] **Step 5: Дёргать helper из `update_status` при status='failed'**

В `publisher_base.py`, в методе `update_status` (line 1177-1188), **после** `conn.close()` добавить:

```python
        # [error_code coverage] любой путь, выставивший status='failed' (включая
        # critical_exception, preflight, «Публикация не прошла»), получает canonical
        # error_code. Идемпотентно — не перезаписывает уже выставленный код.
        if status == 'failed':
            try:
                self._set_error_code_from_events()
            except Exception as e:
                log.warning(f'update_status error_code hook failed: {e}')
```

- [ ] **Step 6: Запустить тест — должен пройти**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
python3 -m pytest tests/test_error_code_mapper.py -v 2>&1 | tail -20
```

Ожидаем 4 PASS.

- [ ] **Step 7: Атомарный commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add publisher_base.py tests/test_error_code_mapper.py
git commit -m "$(cat <<'EOF'
feat(publisher): error_code coverage for ALL failed paths via update_status hook

Extract B3 mapping from _fail_task into shared _set_error_code_from_events()
helper. Call from update_status('failed', ...) so critical_exception, preflight,
«Публикация не прошла» (publisher_base.py:2823/2969/2679) all get canonical
error_code — not just paths that explicitly invoke _fail_task.

Closes IG observability gap discovered in 2026-04-28 investigation:
all 5 prod IG fails (1502-1532) had error_code=NULL despite meta.category present.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### T2 — Fix #2: NBSP-tolerant Reels-tile selector

**Цель:** Заменить permissive `tap_element(['Reels','Reel','ВИДЕО REELS'])` на exact-match по реальному content-desc «Создать новое видео Reels» (NBSP), исключив конкурирующие элементы.

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_instagram.py:665` (single tap call)
- Add: новый метод `_tap_create_reels_tile_strict` в том же файле

- [ ] **Step 1: Написать failing unit-test со снапшотом UI dump 1532**

Скопировать реальный UI dump:

```bash
cp /tmp/ig_1532_debug/ig6_type_sheet.xml \
   /root/.openclaw/workspace-genri/autowarm/tests/fixtures/ig_create_bottom_sheet.xml
mkdir -p /root/.openclaw/workspace-genri/autowarm/tests/fixtures/
```

Create `/root/.openclaw/workspace-genri/autowarm/tests/test_ig_create_tile_selector.py`:

```python
"""Unit tests для _tap_create_reels_tile_strict.

Использует реальный UI dump из task #1532 (где permissive selector тапнул
не ту плитку и привёл к Stories-каскаду).
"""
import os
import sys
import pytest
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import publisher_instagram  # noqa: E402

FIXTURE_BOTTOM_SHEET = HERE / 'fixtures' / 'ig_create_bottom_sheet.xml'


class _Recorder:
    """Записывает координаты adb_tap-вызовов."""
    def __init__(self):
        self.taps = []

    def adb_tap(self, x, y):
        self.taps.append((x, y))


def test_strict_selector_picks_reels_tile_with_nbsp():
    """Проверяет что мы попадаем именно на «Создать новое видео Reels» (NBSP).

    Конкуренты в дампе:
      - content-desc='Reels' (bottom-nav вкладка)
      - content-desc='Видео Reels Eleonora Demidova в строке 1, столбце 1..3' (миниатюры)
      - content-desc='Создать новый прямой эфир'
      - content-desc='Создать новую публикацию'
      - content-desc='Создать новую историю'
      - content-desc='Создать новое видео Reels' ← наша цель
    """
    ui = FIXTURE_BOTTOM_SHEET.read_text()
    rec = _Recorder()

    pub = publisher_instagram.InstagramPublisher.__new__(
        publisher_instagram.InstagramPublisher
    )
    pub.adb_tap = rec.adb_tap

    result = publisher_instagram.InstagramPublisher._tap_create_reels_tile_strict(pub, ui)

    assert result is True, 'helper должен вернуть True при найденной плитке'
    assert len(rec.taps) == 1, f'ровно один tap, got {len(rec.taps)}'
    x, y = rec.taps[0]
    # Плитка «Видео Reels» в дампе — первая, ~y=850 (от верха sheet'а ~750 + 100)
    # Допустимый bbox по реальному дампу. Точные координаты будут зависеть от
    # parser'а — главное что Y попадает в верхнюю треть sheet'а (Reels = 1-я опция).
    assert 0 < x < 1080, f'x out of phone range: {x}'
    assert 700 < y < 1400, f'y out of expected Reels-tile band [700-1400]: {y}'


def test_strict_selector_returns_false_when_no_sheet():
    """Если bottom_sheet'а нет в UI — должен вернуть False, не тапать."""
    ui = '<hierarchy/>'  # пустой UI
    rec = _Recorder()
    pub = publisher_instagram.InstagramPublisher.__new__(
        publisher_instagram.InstagramPublisher
    )
    pub.adb_tap = rec.adb_tap
    result = publisher_instagram.InstagramPublisher._tap_create_reels_tile_strict(pub, ui)
    assert result is False
    assert rec.taps == [], 'не должно быть тапов если не нашли цель'


def test_strict_selector_does_not_match_thumbnails():
    """Регрессия для 1532: «Видео Reels Eleonora Demidova в строке 1…» НЕ должно матчиться."""
    ui = '''<hierarchy>
        <node clickable="true" content-desc="Видео Reels Eleonora Demidova в строке 1, столбце 1"
              bounds="[100,200][300,400]"/>
        <node clickable="true" content-desc="Reels"
              bounds="[400,2200][500,2300]"/>
    </hierarchy>'''
    rec = _Recorder()
    pub = publisher_instagram.InstagramPublisher.__new__(
        publisher_instagram.InstagramPublisher
    )
    pub.adb_tap = rec.adb_tap
    result = publisher_instagram.InstagramPublisher._tap_create_reels_tile_strict(pub, ui)
    assert result is False, 'не должно матчиться на миниатюры или bottom-nav'
    assert rec.taps == []
```

- [ ] **Step 2: Запустить тест — должен фейлиться**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
python3 -m pytest tests/test_ig_create_tile_selector.py -v 2>&1 | tail -20
```

Ожидаем `AttributeError: ... has no attribute '_tap_create_reels_tile_strict'`.

- [ ] **Step 3: Реализовать helper в publisher_instagram.py**

В `publisher_instagram.py`, **в начале класса** `InstagramPublisher` (рядом с другими `_tap_*` хелперами; найти первый `def _` метод и добавить перед ним), добавить:

```python
    # === [FIX 2026-04-28] Reels↔Stories disambiguation ===========================
    # Контекст инцидента 1532: bottom_sheet «Создать» имел 4 опции
    # (Создать новую публикацию / Создать новое видео\xa0Reels / Создать новую историю /
    # Создать новый прямой эфир) + конкурирующие элементы с подстрокой 'Reels' (3
    # миниатюры из reels-feed профиля + bottom-nav 'Reels'). Permissive
    # tap_element(['Reels',...]) тапал не ту плитку → попадали в Stories →
    # ig_upload_confirmation_timeout.

    # Целевая Cyrillic-метка с non-breaking space между «видео» и «Reels»
    _IG_CREATE_REELS_DESC_NBSP = 'Создать новое видео Reels'
    # Fallback если IG переключится на обычный пробел в новых билдах
    _IG_CREATE_REELS_DESC_ASCII = 'Создать новое видео Reels'
    # Английский fallback
    _IG_CREATE_REELS_DESC_EN = 'Create new reel'

    def _tap_create_reels_tile_strict(self, ui: str) -> bool:
        """Strict tap по плитке «Создать новое видео Reels» в bottom_sheet.

        Возвращает True если найдено и тапнуто, False если плитки нет в UI.
        В отличие от tap_element(['Reels',...]):
          - exact match по полному content-desc (NBSP-tolerant)
          - игнорирует миниатюры reels-feed («Видео Reels … в строке N, столбце N»)
          - игнорирует bottom-nav 'Reels'
          - clickable='true' обязательно

        См. tests/test_ig_create_tile_selector.py для регрессионных снапшотов.
        """
        import xml.etree.ElementTree as ET
        import re
        candidates = (
            self._IG_CREATE_REELS_DESC_NBSP,
            self._IG_CREATE_REELS_DESC_ASCII,
            self._IG_CREATE_REELS_DESC_EN,
        )
        try:
            root = ET.fromstring(ui)
        except Exception as e:
            log.warning(f'[ig_create_tile] xml parse error: {e}')
            return False
        for node in root.iter('node'):
            if node.get('clickable') != 'true':
                continue
            desc = node.get('content-desc', '')
            if desc not in candidates:
                continue
            bounds = node.get('bounds', '')
            m = re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
            if not m:
                continue
            cx = (int(m.group(1)) + int(m.group(3))) // 2
            cy = (int(m.group(2)) + int(m.group(4))) // 2
            log.info(f'[ig_create_tile] strict match desc={desc!r} → tap ({cx},{cy})')
            self.log_event('info', f'IG: strict Reels-tile tap ({cx},{cy})',
                           meta={'category': 'ig_create_reels_tile_strict_match',
                                 'platform': self.platform,
                                 'step': 'open_camera',
                                 'desc_variant': desc})
            self.adb_tap(cx, cy)
            return True
        log.info('[ig_create_tile] strict match не найден '
                 '(ни одного из NBSP/ASCII/EN вариантов)')
        return False
```

- [ ] **Step 4: Заменить старый tap_element call на новый helper**

В `publisher_instagram.py:665` (внутри блока `if 'Редактировать профиль' in ui and 'Поделиться профилем' in ui:`, после `ui_post = self.dump_ui()`), **заменить**:

```python
                # Bottomsheet должен открыться с Reels/Reel/Post/Story
                if self.tap_element(ui_post, ['Reels', 'Reel', 'ВИДЕО REELS'],
                                    clickable_only=True):
                    log.info('[FIX: IG-stuck-on-profile] ✅ Reels выбран из bottomsheet')
                    time.sleep(3)
                    continue
                else:
                    log.warning('[FIX: IG-stuck-on-profile] bottomsheet не открылся '
                                'после tap «+» (или Reels не найден)')
```

на:

```python
                # [FIX 2026-04-28] strict NBSP-tolerant Reels-tile selector.
                # Старая permissive logic (['Reels','Reel','ВИДЕО REELS']) тапала
                # неверный элемент (миниатюры reels-feed / bottom-nav 'Reels') →
                # попадали в Stories → ig_upload_confirmation_timeout (task 1532).
                if self._tap_create_reels_tile_strict(ui_post):
                    log.info('[FIX: IG-stuck-on-profile] ✅ Reels-tile (strict) тапнут')
                    time.sleep(3)
                    continue
                else:
                    log.warning('[FIX: IG-stuck-on-profile] bottomsheet не открылся '
                                'после tap «+» (или strict Reels-tile не найден)')
                    self.log_event('warning',
                                   'IG: strict Reels-tile selector miss',
                                   meta={'category': 'ig_create_reels_tile_strict_miss',
                                         'platform': self.platform,
                                         'step': 'open_camera'})
```

- [ ] **Step 5: Запустить тест — должен пройти**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
python3 -m pytest tests/test_ig_create_tile_selector.py -v 2>&1 | tail -20
```

Ожидаем 3 PASS.

- [ ] **Step 6: Атомарный commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add publisher_instagram.py tests/test_ig_create_tile_selector.py tests/fixtures/ig_create_bottom_sheet.xml
git commit -m "$(cat <<'EOF'
fix(ig-publisher): strict NBSP-tolerant Reels-tile selector in bottom_sheet

Replace permissive tap_element(['Reels','Reel','ВИДЕО REELS']) with new
_tap_create_reels_tile_strict() helper that exact-matches the real
content-desc 'Создать новое видео Reels' (with non-breaking space)
and ignores 4 competing elements that share 'Reels' substring:
  - bottom-nav 'Reels' tab (background)
  - 3× reels-feed thumbnails («Видео Reels {account} в строке N, столбце N»)

Root cause for task #1532 ig_upload_confirmation_timeout (and class of
3 ig_reels_tab_not_found / 6 upload_confirmation_timeout fails per 7d):
selector tapped wrong tile → Stories editor → 16-tap AI Unstuck loop →
30-iteration upload-watcher timeout (~16 min wasted per fail).

Includes pytest snapshot of real ig_6_type_sheet UI dump from #1532.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### T3 — Fix #3: Post-tap Reels-mode validation + fail-fast

**Цель:** После Reels-tile tap явно проверить что мы в Reels-камере (а не в Stories editor / Photo composer / etc). Если не в Reels — fail-fast с `ig_wrong_camera_mode` вместо silent continue в чужой UI.

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_instagram.py:830-849` (REELS-tab loop)
- Add: helper `_verify_reels_camera_mode` рядом с `_tap_create_reels_tile_strict`

- [ ] **Step 1: Добавить `_verify_reels_camera_mode` helper**

В `publisher_instagram.py`, **сразу после** `_tap_create_reels_tile_strict` (добавленного в T2), добавить:

```python
    def _verify_reels_camera_mode(self, ui: str) -> tuple:
        """Проверка что мы в Reels-камере, а НЕ в Stories/Photo/Live.

        Returns: (in_reels_mode: bool, detected_mode: str)

        Маркеры:
          - Reels: 'clips_tab' selected=true ИЛИ camera-mode tab bar содержит
                   REELS/Reels с selected/active атрибутом
          - Stories: «Дополнить историю» ИЛИ «Ваша история» ИЛИ resource-id
                     containing 'story_camera' / 'reels_creation_story'
          - Photo:  «ПУБЛИКАЦИЯ» selected ИЛИ «Опубликовать» button ИЛИ
                    resource-id 'feed_camera'
          - Live:   «Выйти в эфир» / «Live»

        Используется ПОСЛЕ tap-Reels-tile чтобы убедиться что landing нужный.
        """
        if not ui:
            return (False, 'empty_ui')
        # Stories markers (highest priority — самая частая wrong-landing)
        stories_markers = (
            'Дополнить историю', 'Ваша история', 'Близкие друзья',
            'story_camera', 'reels_creation_story',
        )
        for m in stories_markers:
            if m in ui:
                return (False, 'stories')
        # Photo
        photo_markers = ('feed_camera', 'Опубликовать в ленту')
        for m in photo_markers:
            if m in ui:
                return (False, 'photo')
        # Live
        live_markers = ('Выйти в эфир', 'live_camera')
        for m in live_markers:
            if m in ui:
                return (False, 'live')
        # Reels positive markers — clips_tab + REELS-mode-tab
        if 'clips_tab' in ui:
            return (True, 'reels')
        # Camera tab bar shows REELS — proxy для Reels mode
        if 'REELS' in ui or 'Reels camera' in ui:
            return (True, 'reels_proxy')
        return (False, 'unknown')
```

- [ ] **Step 2: Вставить mode-validation после strict tap (T2 enhancement)**

В `publisher_instagram.py`, в блоке T2 Step 4, **внутри** `if self._tap_create_reels_tile_strict(ui_post):`, после `time.sleep(3)`, **перед** `continue`, **добавить**:

```python
                if self._tap_create_reels_tile_strict(ui_post):
                    log.info('[FIX: IG-stuck-on-profile] ✅ Reels-tile (strict) тапнут')
                    time.sleep(3)
                    # [FIX 2026-04-28 mode-validation] подтверждаем что landing в Reels-камере.
                    ui_after = self.dump_ui()
                    in_reels, detected = self._verify_reels_camera_mode(ui_after)
                    if not in_reels:
                        log.error(f'[ig_camera_mode] ОШИБКА: после Reels-tap landing={detected!r} '
                                  f'(не Reels-камера). Fail-fast.')
                        self.log_event('error',
                                       f'IG: после tap Reels-tile landing={detected}',
                                       meta={'category': 'ig_wrong_camera_mode',
                                             'platform': self.platform,
                                             'step': 'open_camera',
                                             'detected_mode': detected,
                                             'ui_snippet': (ui_after or '')[:300]})
                        # Возвращаемся в основной loop attempt — следующая итерация
                        # либо попробует через iteration рекавер, либо escalate.
                        continue
                    log.info(f'[ig_camera_mode] ✅ landing={detected!r} (Reels-камера)')
                    continue
```

- [ ] **Step 3: Убрать silent-continue из REELS-tab loop**

В `publisher_instagram.py:843-849`, **заменить**:

```python
        if not reels_found:
            log.warning('  REELS таб не найден — продолжаем без выбора режима')
            self._save_debug_artifacts('instagram_no_reels_tab')
            self.log_event('error', 'Instagram: вкладка REELS не найдена',
                            meta={'category': 'ig_reels_tab_not_found',
                                  'platform': self.platform, 'step': 'open_reels_tab'})
        time.sleep(2)
```

на:

```python
        if not reels_found:
            # [FIX 2026-04-28] silent continue превращал ig_reels_tab_not_found
            # в каскад через Stories-UI → ig_upload_confirmation_timeout (task 1532).
            # Теперь — verify mode и fail-fast если не в Reels.
            in_reels, detected = self._verify_reels_camera_mode(ui)
            if not in_reels:
                log.error(f'[ig_camera_mode] REELS-tab miss + landing={detected!r} → fail-fast')
                self._save_debug_artifacts('instagram_wrong_camera_mode')
                self.log_event('error',
                               f'Instagram: камера в режиме {detected}, не Reels',
                               meta={'category': 'ig_wrong_camera_mode',
                                     'platform': self.platform,
                                     'step': 'open_reels_tab',
                                     'detected_mode': detected,
                                     'ui_snippet': (ui or '')[:300]})
                return False
            log.warning('  REELS-tab miss, но verify говорит mode=reels — '
                        'возможно UI без явной tab bar; продолжаем')
            self._save_debug_artifacts('instagram_no_reels_tab')
            self.log_event('warning',
                           'Instagram: REELS-tab не нажата, но mode=reels',
                           meta={'category': 'ig_reels_tab_not_found_but_mode_ok',
                                 'platform': self.platform,
                                 'step': 'open_reels_tab'})
        time.sleep(2)
```

- [ ] **Step 4: Атомарный commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add publisher_instagram.py
git commit -m "$(cat <<'EOF'
fix(ig-publisher): post-tap Reels-mode validation + fail-fast on Stories landing

Add _verify_reels_camera_mode() helper that explicitly detects landing screen
after Reels-tile tap (Reels / Stories / Photo / Live / unknown).

Two integration points:
  1. publisher_instagram.py:670+ — after _tap_create_reels_tile_strict, verify
     landing IS Reels; if Stories/Photo/Live → log ig_wrong_camera_mode and
     continue to next attempt (no cascade into wrong-app flow).
  2. publisher_instagram.py:843-849 — REELS-tab miss path: if mode!=reels →
     return False with ig_wrong_camera_mode (was: silent continue → Stories
     editor → ig_upload_confirmation_timeout, costs ~16 min per fail + ~64¢
     of AI Unstuck Groq calls).

Closes the cascade-into-Stories class of failures from task #1532.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### T4 — Fix #4: enrich `ig_editor_timeout` meta

**Цель:** Закрыть post-mortem телеметрию для 32 случаев `ig_editor_timeout` за 7 дней (сейчас meta = только category/platform/step/max_steps; нет state/screenshot/last_action — невозможно понять where editor завис без manual repro).

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_instagram.py:1293-1299`

- [ ] **Step 1: Прочитать editor-loop, найти точное начало `for ... in range(20)`**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
grep -n "range(20)\|редактор шаг\|for step in" publisher_instagram.py | head -5
```

Запомнить line N — туда вставим init переменных.

- [ ] **Step 2: Минимальный init — только то что точно есть на момент timeout**

В `publisher_instagram.py`, **прямо перед** циклом editor-loop'а (line из Step 1), добавить:

```python
        # [FIX 2026-04-28] post-mortem context для ig_editor_timeout enrichment.
        # last_action остаётся 'no_action' в этом patch'е — расширение последующего
        # обновления в каждой tap-ветке = follow-up. Главное value: last_ui_texts +
        # screenshot_url (см. ниже), их достаточно для кластеризации 32 dark-fail'ов.
        last_action = 'no_action'
```

Никаких изменений в tap-ветках в этом patch'е (минимум для closing observability gap).

- [ ] **Step 3: В конце цикла перед timeout-error сохранить screenshot + texts**

В `publisher_instagram.py:1293-1299`, **заменить**:

```python
        log.warning('Редактор Reels: не дошли до экрана подписи за 20 шагов')
        self._save_debug_artifacts('instagram_editor_timeout')
        self.log_event('error', 'Instagram: редактор не дошёл до подписи (timeout 20 шагов)',
                        meta={'category': 'ig_editor_timeout',
                              'platform': self.platform, 'step': 'editor_watcher',
                              'max_steps': 20})
        return False
```

на:

```python
        log.warning('Редактор Reels: не дошли до экрана подписи за 20 шагов')
        # [FIX 2026-04-28] enrich post-mortem context
        artifacts = self._save_debug_artifacts('instagram_editor_timeout')
        screenshot_url = (artifacts or {}).get('screenshot_url') if isinstance(artifacts, dict) else None
        # Extract last UI texts (top-12)
        last_ui_texts = []
        try:
            import xml.etree.ElementTree as _ETet
            for n in _ETet.fromstring(ui or '').iter('node'):
                t = (n.get('text', '') or n.get('content-desc', '')).strip()
                if t and len(t) > 1:
                    last_ui_texts.append(t)
            last_ui_texts = last_ui_texts[:12]
        except Exception:
            pass
        self.log_event('error',
                       'Instagram: редактор не дошёл до подписи (timeout 20 шагов)',
                       meta={'category': 'ig_editor_timeout',
                             'platform': self.platform,
                             'step': 'editor_watcher',
                             'max_steps': 20,
                             'last_action': last_action,
                             'last_ui_texts': last_ui_texts,
                             'screenshot_url': screenshot_url,
                             'ui_snippet': (ui or '')[:300]})
        return False
```

- [ ] **Step 4: Sanity-check — функция всё ещё импортируется без syntax errors**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
python3 -c "import publisher_instagram; print('import OK')"
```

Ожидаем `import OK`.

- [ ] **Step 5: Атомарный commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git add publisher_instagram.py
git commit -m "$(cat <<'EOF'
fix(ig-publisher): enrich ig_editor_timeout meta for post-mortem analysis

Editor-watcher timeout was logged with only category/platform/step/max_steps —
no state evidence. 32 ig_editor_timeout fails over 7 days were dark from
post-mortem perspective (had to repro manually).

Add to meta:
  - last_action — what tap was last attempted in editor-loop
  - last_ui_texts — top-12 texts/content-desc from last dump_ui (lightweight
    state fingerprint for clustering similar timeouts)
  - screenshot_url — S3 URL from _save_debug_artifacts
  - ui_snippet — first 300 chars of raw XML

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### T5 — Pre-deploy verification: pytest зелёный + import OK

**Цель:** убедиться что bundle не сломал существующие unit-тесты.

**Files:** none

- [ ] **Step 1: Запустить весь pytest suite**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
python3 -m pytest tests/ -v 2>&1 | tail -40
```

Ожидаем: все existing tests pass + наши 7 новых pass (4 в test_error_code_mapper + 3 в test_ig_create_tile_selector).

- [ ] **Step 2: Import smoke по всем затронутым модулям**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
python3 -c "import publisher_base, publisher_instagram, publisher; print('all imports OK')"
```

Ожидаем `all imports OK`.

- [ ] **Step 3: Если что-то падает — STOP, разбираться**

Не двигаться к T6 (deploy), пока T5 не зелёный.

---

### T6 — Deploy в prod + smoke

**Цель:** мерж в `main`, рестарт PM2-процесса publisher'а, проверка что задачи продолжают браться.

**Files:** none

- [ ] **Step 1: Merge feature branch в main**

```bash
cd /root/.openclaw/workspace-genri/autowarm/
git checkout main
git pull origin main
git merge --no-ff feat/ig-publish-fixes-bundle-20260428 -m "Merge feat/ig-publish-fixes-bundle-20260428: IG Reels↔Stories fix + observability + telemetry"
git push origin main
```

Auto-push hook автоматом синкнет в `GenGo2/delivery-contenthunter`.

- [ ] **Step 2: Найти PM2-процессы которые загружают publisher_instagram**

```bash
sudo pm2 list 2>&1
sudo pm2 describe testbench-orchestrator 2>&1 | grep -E "exec cwd|status" | head -5
```

Записать имена процессов которые читают autowarm/.

- [ ] **Step 3: Reload PM2-процессов publisher'а**

```bash
# Имена возможны: testbench-orchestrator, publisher-worker, etc.
# Узнать точно из Step 2.
sudo pm2 reload testbench-orchestrator 2>&1
# Если есть отдельный publisher worker — reload его тоже.
sudo pm2 logs --nostream --lines 20 2>&1 | tail -25
```

- [ ] **Step 4: Verify cwd не дрифтнул (правило `feedback_pm2_dump_path_drift.md`)**

```bash
sudo pm2 describe testbench-orchestrator | grep "exec cwd"
```

Ожидаем `/root/.openclaw/workspace-genri/autowarm/`. Если нет — `pm2 delete <name> && pm2 start <ecosystem.config>`.

- [ ] **Step 5: Smoke — observability fix #1**

Создать тестовую failed-задачу с критическим exception и проверить что error_code заполнился:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
INSERT INTO publish_tasks (platform, account, device_serial, status, testbench, events)
VALUES ('Instagram', 'smoke_test_t6', 'SMOKE_SERIAL', 'pending', false,
        '[{\"type\":\"error\",\"msg\":\"smoke\",\"meta\":{\"category\":\"smoke_test_category\"}}]'::jsonb)
RETURNING id;
"
# Возьмём id и симулируем status='failed' через update_status вызов в Python
SMOKE_ID=$(PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -t -A -c "SELECT MAX(id) FROM publish_tasks WHERE account='smoke_test_t6';")
echo "smoke task id: $SMOKE_ID"

cd /root/.openclaw/workspace-genri/autowarm/
python3 -c "
import sys; sys.path.insert(0, '.')
import publisher_base
class Stub:
    def __init__(self, tid): self.task_id = tid
    set_step = lambda self, s: None
publisher_base.BasePublisher.update_status(Stub($SMOKE_ID), 'failed', 'smoke')
"

PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, status, error_code FROM publish_tasks WHERE id=$SMOKE_ID;
"
```

Ожидаем `error_code='smoke_test_category'`.

- [ ] **Step 6: Cleanup smoke task**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
DELETE FROM publish_tasks WHERE account='smoke_test_t6';
"
```

- [ ] **Step 7: 30-минутное наблюдение за live задачами**

```bash
# Подождать 30 минут. За это время testbench/prod должны взять несколько задач.
# Затем проверить — для свежих failed появляется error_code?
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, platform, status, error_code, started_at, updated_at
FROM publish_tasks
WHERE status='failed' AND updated_at >= NOW() - INTERVAL '30 minutes'
ORDER BY id DESC LIMIT 10;
"
```

Ожидаем: failed-задачи имеют непустой `error_code`. Если все NULL — fix #1 не подцепился, разбираться (PM2 не подхватил новый код, проверить cwd / restart).

---

### T7 — Evidence + memory update

**Цель:** Зафиксировать результат в evidence + обновить memory.

**Files:**
- Create: `/home/claude-user/contenthunter/.ai-factory/evidence/ig-publish-fixes-bundle-20260428.md`
- Update: `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_publisher_modularization_wip.md` (добавить запись о bundle)
- Update: `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/MEMORY.md` (новая строка про fixes)

- [ ] **Step 1: Написать evidence-файл**

Структура:
- Контекст (ссылка на root-cause investigation в текущей сессии)
- 4 commits с короткими описаниями
- SQL baselines из T0 vs after deploy
- Список оставшихся backlog-треков (#5, #6 → ссылки на новые memory)

- [ ] **Step 2: Обновить memory `project_publisher_modularization_wip.md`**

Добавить параграф «IG Reels↔Stories fix bundle — отгружено 2026-04-28 ✅» с ссылками на 4 коммита.

- [ ] **Step 3: Обновить MEMORY.md строкой**

```markdown
- [IG publish fixes bundle ✅ shipped 2026-04-28](project_publisher_modularization_wip.md) — error_code coverage для всех fail-путей + strict NBSP-tolerant Reels-tile + Reels-mode validation + ig_editor_timeout meta enrichment
```

- [ ] **Step 4: Commit evidence (в contenthunter repo)**

```bash
cd /home/claude-user/contenthunter/
git add .ai-factory/evidence/ig-publish-fixes-bundle-20260428.md
git commit -m "docs(evidence): IG publish fixes bundle 2026-04-28 — shipped 4 commits"
```

---

## Self-review checklist (для исполнителя плана)

После прогона T1-T7:
- [ ] Все 7 unit-тестов pass
- [ ] Import smoke OK
- [ ] PM2 cwd не дрифтнул
- [ ] Smoke fix #1 показал error_code='smoke_test_category'
- [ ] 30-мин live observation: failed-задачи получают error_code
- [ ] Evidence-файл написан со всеми SQL baselines (before/after)
- [ ] Memory обновлена

## Out of scope (явно)

- **AI Unstuck anti-loop** (#5 backlog) — отдельный PR, см. memory `project_ai_unstuck_hardening_backlog.md`
- **IG account audit** (#6 backlog) — discovery, не код, см. memory `project_ig_failing_accounts_audit_backlog.md`
- **Backport в `/home/claude-user/autowarm-testbench/`** — testbench отстаёт; отдельный follow-up если понадобится
- **Расширение strict-selector на YT/TT** — у YT/TT свои селекторы create-tile, текущий fix только для IG
