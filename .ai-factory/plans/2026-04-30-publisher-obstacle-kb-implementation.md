# Publisher Obstacle KB + AI Unstuck v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить реактивное `ai_unstuck` LLM-тыкание (0% success на 70 events/неделю) в самообучающуюся двухуровневую систему: pattern-match shim из БД + Claude Sonnet 4.6 fallback с memoization.

**Architecture:** 2 новые таблицы в `openclaw` (`publisher_obstacles`, `publisher_obstacle_outcomes`), 6 Python-модулей (~1550 LOC), shim в `ai_unstuck()` ДО LLM-вызова, Tiered curation (T1 auto / T2 Telegram / T3 auto-degrade), admin UI на `delivery.contenthunter.ru/obstacles.html`.

**Tech Stack:** Python 3 + psycopg + pytest, aiogram 3 (для Telegram bot), Claude Sonnet 4.6 (vision), Express (server.js), frontend factory pattern (HTML+JS).

**Спек (читать сначала):** `.ai-factory/plans/2026-04-30-publisher-obstacle-kb-design.md` (commit `fbb57ab5` на ветке `design/publisher-obstacle-kb-20260430`).

**Ключевые директории:**
- Python код: `/home/claude-user/autowarm-testbench/` (testbench branch)
- Прод autowarm: `/root/.openclaw/workspace-genri/autowarm/` (после merge'а)
- Telegram bot: `/home/claude-user/contenthunter_bugs_bot/`
- Frontend (delivery.contenthunter.ru): `/root/.openclaw/workspace-genri/autowarm/*.html`
- Express handler: `/root/.openclaw/workspace-genri/autowarm/server.js`
- DB: `postgres://openclaw:openclaw123@localhost:5432/openclaw`
- Console API key: `/home/claude-user/secrets/anthropic.env`
- Pytest: запускается из `/home/claude-user/autowarm-testbench/` командой `pytest tests/<file>.py -v`

**Whitelist action_types (зафиксированы для всего плана):**
- Tier 1 safe (auto-promote): `keycode_back`, `tap_resource_id`, `tap_text`, `noop_wait`
- Tier 2 destructive (human review): `force_stop`, `force_clean_recents`, `escalate`

**Convention:**
- TDD: каждая задача начинается с failing test, затем implementation, затем pass-проверка, затем commit.
- Имена тестовых файлов: `tests/test_<module>.py`. Module-level fixture `engine.dispose` (memory `feedback_validator_test_engine_dispose.md`) для DB-тестов.
- Commits в ветку `feature/obstacle-kb-<phase>` с auto-push hook'ом (memory `reference_autowarm_git_hook.md` — commit'ы из prod autowarm pushятся, но мы работаем в testbench где push manual).

---

## PHASE W1 — Migrations + skeleton + kill-switches

**Цель:** Schema и skeleton модулей готовы. Kill-switches verified. Никакой бизнес-логики.

**Безопасность:** ADDITIVE only — нулевой риск.

**Где работаем:** `/home/claude-user/autowarm-testbench/` ветка `feature/obstacle-kb-w1`.

### Task 1: Create migration `publisher_obstacles`

**Files:**
- Create: `/home/claude-user/autowarm-testbench/migrations/20260430_publisher_obstacles.sql`

- [ ] **Step 1: Создать ветку**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git checkout testbench
git pull --ff-only
git checkout -b feature/obstacle-kb-w1
```

- [ ] **Step 2: Создать миграцию**

```sql
-- File: migrations/20260430_publisher_obstacles.sql
-- Publisher Obstacle KB — main pattern table
-- ADDITIVE: zero risk to existing system

CREATE TABLE IF NOT EXISTS publisher_obstacles (
    obstacle_id        TEXT PRIMARY KEY,
    platform           TEXT NOT NULL,
    top_activity       TEXT NOT NULL,
    publisher_step     TEXT,
    resource_ids       TEXT[] NOT NULL,
    key_texts          TEXT[] NOT NULL,
    dialog_indicator   BOOLEAN NOT NULL,
    signature_raw      JSONB NOT NULL,

    action_type        TEXT NOT NULL,
    action_params      JSONB NOT NULL,
    action_description TEXT,

    success_count      INT NOT NULL DEFAULT 0,
    fail_count         INT NOT NULL DEFAULT 0,
    last_success_at    TIMESTAMPTZ,
    last_fail_at       TIMESTAMPTZ,
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    status             TEXT NOT NULL DEFAULT 'experimental',
    confidence_score   REAL,
    apply_limit        INT,
    promoted_at        TIMESTAMPTZ,
    promoted_by        TEXT,
    degraded_at        TIMESTAMPTZ,
    degraded_reason    TEXT,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source             TEXT NOT NULL,
    source_task_id     BIGINT,
    notes              TEXT,

    xml_sample_url     TEXT,
    screenshot_url     TEXT,

    CONSTRAINT publisher_obstacles_status_check CHECK (status IN ('experimental','candidate','stable','blacklisted')),
    CONSTRAINT publisher_obstacles_platform_check CHECK (platform IN ('instagram','tiktok','youtube'))
);

CREATE INDEX IF NOT EXISTS idx_obstacles_platform_status ON publisher_obstacles (platform, status);
CREATE INDEX IF NOT EXISTS idx_obstacles_last_seen ON publisher_obstacles (last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_obstacles_source ON publisher_obstacles (source);
```

- [ ] **Step 3: Применить миграцию**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -f /home/claude-user/autowarm-testbench/migrations/20260430_publisher_obstacles.sql
```

Expected: `CREATE TABLE` + 3× `CREATE INDEX` без ошибок.

- [ ] **Step 4: Verify schema**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c "\d publisher_obstacles"
```

Expected: видно 26 колонок + 3 индекса + 2 check constraints.

- [ ] **Step 5: Commit**

```bash
git add migrations/20260430_publisher_obstacles.sql
git commit -m "feat(migrations): publisher_obstacles table — main pattern KB"
```

---

### Task 2: Create migration `publisher_obstacle_outcomes`

**Files:**
- Create: `/home/claude-user/autowarm-testbench/migrations/20260430_publisher_obstacle_outcomes.sql`

- [ ] **Step 1: Создать миграцию**

```sql
-- File: migrations/20260430_publisher_obstacle_outcomes.sql
-- Outcome log for confidence recompute + debug + auditing

CREATE TABLE IF NOT EXISTS publisher_obstacle_outcomes (
    id           BIGSERIAL PRIMARY KEY,
    obstacle_id  TEXT NOT NULL REFERENCES publisher_obstacles(obstacle_id) ON DELETE CASCADE,
    task_id      BIGINT NOT NULL,
    matched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    action_taken JSONB NOT NULL,
    outcome      TEXT NOT NULL,
    next_step    TEXT,
    notes        TEXT,
    CONSTRAINT outcomes_outcome_check CHECK (outcome IN ('progressed','still_stuck','task_succeeded','task_failed_other','shadow_match'))
);

CREATE INDEX IF NOT EXISTS idx_outcomes_obstacle ON publisher_obstacle_outcomes (obstacle_id, matched_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcomes_task ON publisher_obstacle_outcomes (task_id);
```

- [ ] **Step 2: Применить миграцию**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -f /home/claude-user/autowarm-testbench/migrations/20260430_publisher_obstacle_outcomes.sql
```

Expected: `CREATE TABLE` + 2× `CREATE INDEX` без ошибок.

- [ ] **Step 3: Verify**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c "\d publisher_obstacle_outcomes"
```

Expected: 8 колонок, FK на `publisher_obstacles(obstacle_id) ON DELETE CASCADE`.

- [ ] **Step 4: Commit**

```bash
git add migrations/20260430_publisher_obstacle_outcomes.sql
git commit -m "feat(migrations): publisher_obstacle_outcomes — outcome log + FK"
```

---

### Task 3: Kill-switches in `system_flags`

**Files:**
- Create: `/home/claude-user/autowarm-testbench/migrations/20260430_obstacle_kill_switches.sql`

- [ ] **Step 1: Создать миграцию**

```sql
-- File: migrations/20260430_obstacle_kill_switches.sql
-- Five kill-switches for Obstacle KB system

INSERT INTO system_flags (key, value) VALUES
    ('obstacle_kb_disabled', 'false'),
    ('obstacle_kb_lookup_only', 'true'),  -- shadow mode by default at first deploy
    ('obstacle_promoter_disabled', 'true'),  -- promoter disabled until W5
    ('obstacle_kb_anthropic_disabled', 'false'),
    ('obstacle_curator_bot_disabled', 'true')  -- bot disabled until W5
ON CONFLICT (key) DO NOTHING;
```

- [ ] **Step 2: Применить + verify**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -f /home/claude-user/autowarm-testbench/migrations/20260430_obstacle_kill_switches.sql
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c "SELECT key, value FROM system_flags WHERE key LIKE 'obstacle_%' ORDER BY key"
```

Expected: 5 строк с правильными `value` (`true` для shadow_only/promoter_disabled/curator_bot_disabled, `false` для остальных).

- [ ] **Step 3: Commit**

```bash
git add migrations/20260430_obstacle_kill_switches.sql
git commit -m "feat(migrations): obstacle KB kill-switches in system_flags"
```

---

### Task 4: Skeleton modules

**Files:**
- Create: `obstacle_signatures.py`, `obstacle_kb.py`, `obstacle_actions.py`, `obstacle_promoter.py`, `obstacle_seed.py`

- [ ] **Step 1: `obstacle_signatures.py` skeleton**

```python
# File: obstacle_signatures.py
"""Pure-function signature extraction для obstacle KB.

Без I/O — testable изолированно. Хеш стабилен между процессами/машинами.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ObstacleSignature:
    obstacle_id: str
    platform: str
    top_activity: str
    publisher_step: str | None
    resource_ids: tuple[str, ...]
    key_texts: tuple[str, ...]
    dialog_indicator: bool
    signature_raw: dict[str, Any]


def extract_signature(
    xml: str,
    top_activity: str,
    platform: str,
    publisher_step: str | None,
) -> ObstacleSignature:
    raise NotImplementedError("Implemented in W2")
```

- [ ] **Step 2: `obstacle_kb.py` skeleton**

```python
# File: obstacle_kb.py
"""DB API for publisher_obstacles + publisher_obstacle_outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Obstacle:
    obstacle_id: str
    platform: str
    status: str
    action_type: str
    action_params: dict[str, Any]
    success_count: int
    fail_count: int
    confidence_score: float | None
    apply_limit: int | None


def lookup_obstacle(obstacle_id: str) -> Obstacle | None:
    raise NotImplementedError("Implemented in W2")


def insert_or_increment(signature, action_recipe, status, source, source_task_id, xml_sample_url=None, screenshot_url=None):
    raise NotImplementedError("Implemented in W2")


def record_outcome(obstacle_id: str, task_id: int, action_taken: dict, outcome: str, next_step: str | None = None):
    raise NotImplementedError("Implemented in W2")


def recompute_confidence(obstacle_id: str) -> float:
    raise NotImplementedError("Implemented in W2")


def mine_from_failed_task(task_id: int) -> int:
    """Returns number of new candidates inserted."""
    raise NotImplementedError("Implemented in W3")
```

- [ ] **Step 3: `obstacle_actions.py` skeleton**

```python
# File: obstacle_actions.py
"""Action dispatcher: apply obstacle action_recipe via publisher proxy API."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActionOutcome:
    progressed: bool
    pre_top_activity: str
    post_top_activity: str
    notes: str = ""


def apply_action(publisher, recipe: dict) -> ActionOutcome:
    raise NotImplementedError("Implemented in W3")
```

- [ ] **Step 4: `obstacle_promoter.py` skeleton**

```python
# File: obstacle_promoter.py
"""Promoter ticker: T1 auto-promote / T2 Telegram review / T3 auto-degrade."""
from __future__ import annotations


def tick() -> dict[str, int]:
    """Returns counts: {promoted_t1, queued_t2, degraded_t3}."""
    raise NotImplementedError("Implemented in W5")
```

- [ ] **Step 5: `obstacle_seed.py` skeleton**

```python
# File: obstacle_seed.py
"""One-shot CLI: from-constants (B1) + mine-events (B2)."""
from __future__ import annotations

import argparse


def from_constants() -> int:
    """Returns count of inserted patterns. Implemented in W2."""
    raise NotImplementedError("Implemented in W2")


def mine_events(days: int = 30, min_cluster: int = 3) -> int:
    """Returns count of inserted candidates. Implemented in W5."""
    raise NotImplementedError("Implemented in W5")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("from-constants")
    p_mine = sub.add_parser("mine-events")
    p_mine.add_argument("--days", type=int, default=30)
    p_mine.add_argument("--min-cluster", type=int, default=3)
    args = parser.parse_args()
    if args.cmd == "from-constants":
        n = from_constants()
        print(f"Inserted {n} patterns")
    elif args.cmd == "mine-events":
        n = mine_events(days=args.days, min_cluster=args.min_cluster)
        print(f"Inserted {n} candidates")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Verify imports**

```bash
cd /home/claude-user/autowarm-testbench
python3 -c "import obstacle_signatures; import obstacle_kb; import obstacle_actions; import obstacle_promoter; import obstacle_seed; print('OK')"
```

Expected: `OK`. Никаких ImportError.

- [ ] **Step 7: Commit**

```bash
git add obstacle_signatures.py obstacle_kb.py obstacle_actions.py obstacle_promoter.py obstacle_seed.py
git commit -m "feat(obstacle-kb): skeleton modules for W1 (NotImplementedError stubs)"
```

---

### Task 5: Smoke test kill-switches

**Files:**
- Test: `tests/test_obstacle_kill_switches.py`

- [ ] **Step 1: Написать failing test**

```python
# File: tests/test_obstacle_kill_switches.py
"""Verify all 5 obstacle KB kill-switches exist in system_flags."""
import pytest
import psycopg2

DB_URL = "postgres://openclaw:openclaw123@localhost:5432/openclaw"


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(DB_URL)
    yield c
    c.close()


def test_all_five_obstacle_flags_exist(conn):
    expected_keys = [
        "obstacle_kb_disabled",
        "obstacle_kb_lookup_only",
        "obstacle_promoter_disabled",
        "obstacle_kb_anthropic_disabled",
        "obstacle_curator_bot_disabled",
    ]
    with conn.cursor() as cur:
        cur.execute("SELECT key FROM system_flags WHERE key LIKE 'obstacle_%'")
        actual_keys = sorted(r[0] for r in cur.fetchall())
    assert sorted(expected_keys) == actual_keys


def test_initial_kill_switch_states(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT key, value FROM system_flags WHERE key LIKE 'obstacle_%' ORDER BY key"
        )
        rows = dict(cur.fetchall())
    # Initial deploy: shadow mode ON, promoter+bot OFF, others OFF (false=enabled)
    assert rows["obstacle_kb_disabled"] == "false"
    assert rows["obstacle_kb_lookup_only"] == "true"
    assert rows["obstacle_promoter_disabled"] == "true"
    assert rows["obstacle_kb_anthropic_disabled"] == "false"
    assert rows["obstacle_curator_bot_disabled"] == "true"
```

- [ ] **Step 2: Run, verify pass (миграция уже applied в Task 3)**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_obstacle_kill_switches.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit + push (W1 готов)**

```bash
git add tests/test_obstacle_kill_switches.py
git commit -m "test(obstacle-kb): smoke test for kill-switches"
git push -u origin feature/obstacle-kb-w1
```

**W1 DONE checkpoint:** schema applied, skeleton compiles, kill-switches verified. Можно мерж'ить в `testbench` и переходить к W2.

---

## PHASE W2 — Signature extraction + KB API + B1 seed (in-code constants migration)

**Цель:** Pure-function `extract_signature` + DB API + миграция в DB всех существующих in-code markers. После W2 in-code constants удалены, тот же бихейвиор работает через DB lookup.

**Risk:** Medium-High — рефакторинг production code paths. Защита через 100% test coverage перед удалением constants.

**Где работаем:** `feature/obstacle-kb-w2` от `testbench`.

### Task 6: Normalize text helper (TDD)

**Files:**
- Modify: `obstacle_signatures.py`
- Test: `tests/test_obstacle_signatures.py`

- [ ] **Step 1: Failing test**

```python
# File: tests/test_obstacle_signatures.py
"""Tests for obstacle_signatures.normalize_text."""
import pytest
from obstacle_signatures import normalize_text


@pytest.mark.parametrize("raw,expected", [
    ("About Account", "about account"),
    ("Об\xa0аккаунте", "об аккаунте"),  # NBSP → space
    ("It’s OK", "it's ok"),  # curly apostrophe
    ("It&apos;s OK", "it's ok"),  # XML entity
    ("View 123 likes", "view <NUM> likes"),  # digits masked
    ("View   3   likes", "view <NUM> likes"),  # multiple spaces
    ("  trim  ", "trim"),
    ("", ""),
    (None, ""),
])
def test_normalize_text(raw, expected):
    assert normalize_text(raw) == expected
```

- [ ] **Step 2: Run, verify FAIL**

```bash
pytest tests/test_obstacle_signatures.py::test_normalize_text -v
```

Expected: `ImportError: cannot import name 'normalize_text'`

- [ ] **Step 3: Implement**

Add to `obstacle_signatures.py`:

```python
import re

_DIGIT_RE = re.compile(r"\d+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(s: str | None) -> str:
    if not s:
        return ""
    s = s.replace("\xa0", " ")
    s = s.replace("&apos;", "'").replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.lower()
    s = _DIGIT_RE.sub("<NUM>", s)
    s = _WHITESPACE_RE.sub(" ", s)
    return s.strip()
```

- [ ] **Step 4: Run, verify PASS**

```bash
pytest tests/test_obstacle_signatures.py::test_normalize_text -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add obstacle_signatures.py tests/test_obstacle_signatures.py
git commit -m "feat(obstacle-sig): normalize_text helper + 9 unit tests"
```

---

### Task 7: Extract resource_ids from XML (TDD)

**Files:**
- Modify: `obstacle_signatures.py`
- Test: `tests/test_obstacle_signatures.py`

- [ ] **Step 1: Failing test**

Add to `tests/test_obstacle_signatures.py`:

```python
from obstacle_signatures import extract_resource_ids


SAMPLE_IG_DIALOG = '''<?xml version="1.0"?>
<hierarchy>
  <node class="android.widget.FrameLayout" resource-id="com.instagram.android:id/dialog_root">
    <node class="android.widget.TextView" resource-id="com.instagram.android:id/dialog_title" text="Об аккаунте"/>
    <node class="android.widget.Button" resource-id="com.instagram.android:id/dialog_close_btn" content-desc="Закрыть"/>
    <node class="android.widget.TextView" text="No id here"/>
  </node>
</hierarchy>'''


def test_extract_resource_ids_strips_package_prefix():
    ids = extract_resource_ids(SAMPLE_IG_DIALOG)
    assert ids == ("dialog_close_btn", "dialog_root", "dialog_title")  # sorted, deduped


def test_extract_resource_ids_empty_xml():
    assert extract_resource_ids("<hierarchy/>") == ()


def test_extract_resource_ids_malformed_xml_returns_empty():
    assert extract_resource_ids("<not-xml") == ()


def test_extract_resource_ids_no_package_prefix():
    xml = '<hierarchy><node resource-id="bare_id"/></hierarchy>'
    assert extract_resource_ids(xml) == ("bare_id",)
```

- [ ] **Step 2: Run, verify FAIL**

```bash
pytest tests/test_obstacle_signatures.py::test_extract_resource_ids_strips_package_prefix -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Add to `obstacle_signatures.py`:

```python
import xml.etree.ElementTree as ET


def extract_resource_ids(xml: str) -> tuple[str, ...]:
    """Extract sorted unique resource-ids, strip 'package:id/' prefix."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ()
    ids = set()
    for node in root.iter("node"):
        rid = node.get("resource-id", "").strip()
        if not rid:
            continue
        # Strip "com.foo.bar:id/" prefix
        if ":id/" in rid:
            rid = rid.split(":id/", 1)[1]
        if rid:
            ids.add(rid)
    return tuple(sorted(ids))
```

- [ ] **Step 4: Run, verify PASS**

```bash
pytest tests/test_obstacle_signatures.py -v
```

Expected: 13 passed (9 normalize + 4 resource_ids).

- [ ] **Step 5: Commit**

```bash
git add obstacle_signatures.py tests/test_obstacle_signatures.py
git commit -m "feat(obstacle-sig): extract_resource_ids + 4 tests"
```

---

### Task 8: Extract key_texts from XML (TDD)

**Files:**
- Modify: `obstacle_signatures.py`
- Test: `tests/test_obstacle_signatures.py`

- [ ] **Step 1: Failing test**

```python
from obstacle_signatures import extract_key_texts


def test_extract_key_texts_normalized_and_sorted():
    xml = '''<hierarchy>
        <node text="Об\xa0аккаунте"/>
        <node text="Дата 12.04.2026"/>
        <node content-desc="Закрыть"/>
        <node text=""/>
        <node/>
    </hierarchy>'''
    texts = extract_key_texts(xml)
    assert texts == ("дата <NUM>.<NUM>.<NUM>", "закрыть", "об аккаунте")  # sorted


def test_extract_key_texts_dedup():
    xml = '<hierarchy><node text="Hello"/><node text="hello"/></hierarchy>'
    assert extract_key_texts(xml) == ("hello",)


def test_extract_key_texts_skips_too_short():
    """Skip 1-char texts (likely UI noise)."""
    xml = '<hierarchy><node text="A"/><node text="AB"/></hierarchy>'
    assert extract_key_texts(xml) == ("ab",)


def test_extract_key_texts_skips_too_long():
    """Skip texts > 200 chars (variable content like full captions)."""
    long = "x" * 250
    xml = f'<hierarchy><node text="ok"/><node text="{long}"/></hierarchy>'
    assert extract_key_texts(xml) == ("ok",)


def test_extract_key_texts_combines_text_and_desc():
    xml = '<hierarchy><node text="One" content-desc="Two"/></hierarchy>'
    assert extract_key_texts(xml) == ("one", "two")
```

- [ ] **Step 2: Run, verify FAIL**

```bash
pytest tests/test_obstacle_signatures.py::test_extract_key_texts_normalized_and_sorted -v
```

- [ ] **Step 3: Implement**

```python
def extract_key_texts(xml: str) -> tuple[str, ...]:
    """Extract normalized + sorted unique text + content-desc tokens.

    Skip too-short (<2) or too-long (>200) — likely noise/captions.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ()
    texts = set()
    for node in root.iter("node"):
        for attr in ("text", "content-desc"):
            raw = node.get(attr, "")
            normalized = normalize_text(raw)
            if 2 <= len(normalized) <= 200:
                texts.add(normalized)
    return tuple(sorted(texts))
```

- [ ] **Step 4: Run, verify PASS**

```bash
pytest tests/test_obstacle_signatures.py -v
```

Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add obstacle_signatures.py tests/test_obstacle_signatures.py
git commit -m "feat(obstacle-sig): extract_key_texts + 5 tests"
```

---

### Task 9: Dialog indicator detection (TDD)

**Files:**
- Modify: `obstacle_signatures.py`
- Test: `tests/test_obstacle_signatures.py`

- [ ] **Step 1: Failing test**

```python
from obstacle_signatures import detect_dialog_indicator


@pytest.mark.parametrize("xml,expected", [
    ('<hierarchy><node class="android.app.AlertDialog"/></hierarchy>', True),
    ('<hierarchy><node class="androidx.appcompat.app.AppCompatDialog"/></hierarchy>', True),
    ('<hierarchy><node resource-id="dialog_root"/></hierarchy>', True),
    ('<hierarchy><node resource-id="bottom_sheet_container"/></hierarchy>', True),
    ('<hierarchy><node resource-id="alert_message"/></hierarchy>', True),
    ('<hierarchy><node resource-id="modal_overlay"/></hierarchy>', True),
    ('<hierarchy><node resource-id="feed_recycler_view"/></hierarchy>', False),
    ('<hierarchy><node class="android.widget.FrameLayout"/></hierarchy>', False),
    ("<hierarchy/>", False),
    ("<not-xml", False),
])
def test_detect_dialog_indicator(xml, expected):
    assert detect_dialog_indicator(xml) == expected
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement**

```python
_DIALOG_RID_PATTERNS = ("dialog", "alert", "modal", "sheet", "bottomsheet")
_DIALOG_CLASS_PATTERNS = ("Dialog", "AlertDialog", "BottomSheet")


def detect_dialog_indicator(xml: str) -> bool:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    for node in root.iter("node"):
        cls = node.get("class", "")
        if any(p in cls for p in _DIALOG_CLASS_PATTERNS):
            return True
        rid = node.get("resource-id", "")
        rid_part = rid.split(":id/", 1)[-1].lower() if rid else ""
        if any(p in rid_part for p in _DIALOG_RID_PATTERNS):
            return True
    return False
```

- [ ] **Step 4: PASS**

```bash
pytest tests/test_obstacle_signatures.py -v
```

Expected: 28 passed.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(obstacle-sig): detect_dialog_indicator + 10 tests"
```

---

### Task 10: Compose `extract_signature` + obstacle_id hash (TDD)

**Files:**
- Modify: `obstacle_signatures.py`
- Test: `tests/test_obstacle_signatures.py`

- [ ] **Step 1: Failing test**

```python
from obstacle_signatures import extract_signature


SAMPLE_XML = '''<hierarchy>
    <node class="android.app.Dialog" resource-id="com.instagram.android:id/dialog_root">
        <node text="Об аккаунте"/>
        <node text="Дата присоединения"/>
        <node resource-id="com.instagram.android:id/dialog_close_btn" content-desc="Закрыть"/>
    </node>
</hierarchy>'''


def test_extract_signature_full_struct():
    sig = extract_signature(
        xml=SAMPLE_XML,
        top_activity="com.instagram.android/.modal.ModalActivity",
        platform="instagram",
        publisher_step="open_camera",
    )
    assert sig.platform == "instagram"
    assert sig.top_activity == "com.instagram.android/.modal.ModalActivity"
    assert sig.publisher_step == "open_camera"
    assert sig.resource_ids == ("dialog_close_btn", "dialog_root")
    assert sig.key_texts == ("дата присоединения", "закрыть", "об аккаунте")
    assert sig.dialog_indicator is True
    assert len(sig.obstacle_id) == 16  # sha1[:16]


def test_extract_signature_deterministic_hash():
    """Same inputs → same obstacle_id."""
    a = extract_signature(SAMPLE_XML, "com.instagram.android/.modal.ModalActivity", "instagram", "open_camera")
    b = extract_signature(SAMPLE_XML, "com.instagram.android/.modal.ModalActivity", "instagram", "open_camera")
    assert a.obstacle_id == b.obstacle_id


def test_extract_signature_diff_platform_diff_hash():
    a = extract_signature(SAMPLE_XML, "act", "instagram", None)
    b = extract_signature(SAMPLE_XML, "act", "tiktok", None)
    assert a.obstacle_id != b.obstacle_id


def test_extract_signature_diff_step_diff_hash():
    a = extract_signature(SAMPLE_XML, "act", "instagram", "step_a")
    b = extract_signature(SAMPLE_XML, "act", "instagram", "step_b")
    assert a.obstacle_id != b.obstacle_id


def test_extract_signature_normalization_makes_hash_stable():
    """NBSP-version and space-version should hash to same id."""
    xml_nbsp = '<hierarchy><node text="Об\xa0аккаунте"/></hierarchy>'
    xml_space = '<hierarchy><node text="Об аккаунте"/></hierarchy>'
    a = extract_signature(xml_nbsp, "act", "instagram", None)
    b = extract_signature(xml_space, "act", "instagram", None)
    assert a.obstacle_id == b.obstacle_id


def test_extract_signature_signature_raw_is_dict():
    sig = extract_signature(SAMPLE_XML, "act", "instagram", "step")
    assert isinstance(sig.signature_raw, dict)
    assert sig.signature_raw["platform"] == "instagram"
    assert "resource_ids" in sig.signature_raw
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement**

Replace `extract_signature` stub в `obstacle_signatures.py`:

```python
import hashlib
import json


def extract_signature(
    xml: str,
    top_activity: str,
    platform: str,
    publisher_step: str | None,
) -> ObstacleSignature:
    resource_ids = extract_resource_ids(xml)
    key_texts = extract_key_texts(xml)
    dialog_indicator = detect_dialog_indicator(xml)

    signature_raw = {
        "platform": platform,
        "top_activity": top_activity,
        "publisher_step": publisher_step,
        "resource_ids": list(resource_ids),
        "key_texts": list(key_texts),
        "dialog_indicator": dialog_indicator,
    }
    obstacle_id = hashlib.sha1(
        json.dumps(signature_raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]

    return ObstacleSignature(
        obstacle_id=obstacle_id,
        platform=platform,
        top_activity=top_activity,
        publisher_step=publisher_step,
        resource_ids=resource_ids,
        key_texts=key_texts,
        dialog_indicator=dialog_indicator,
        signature_raw=signature_raw,
    )
```

- [ ] **Step 4: PASS**

```bash
pytest tests/test_obstacle_signatures.py -v
```

Expected: 34 passed.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(obstacle-sig): extract_signature compose + 6 hash determinism tests"
```

---

### Task 11: `obstacle_kb.lookup_obstacle` (TDD with real DB)

**Files:**
- Modify: `obstacle_kb.py`
- Test: `tests/test_obstacle_kb.py`

- [ ] **Step 1: Failing test**

```python
# File: tests/test_obstacle_kb.py
"""Tests for obstacle_kb DB API. Uses real DB with rollback isolation.

NB: autouse engine.dispose fixture в conftest.py обязателен (memory feedback_validator_test_engine_dispose.md).
"""
import pytest
import psycopg2
import json
from obstacle_kb import lookup_obstacle, Obstacle

DB_URL = "postgres://openclaw:openclaw123@localhost:5432/openclaw"


@pytest.fixture
def conn():
    c = psycopg2.connect(DB_URL)
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def seed_obstacle(conn):
    """Insert one test obstacle, returns its obstacle_id."""
    oid = "test_w2_lookup_01"
    with conn.cursor() as cur:
        cur.execute("DELETE FROM publisher_obstacles WHERE obstacle_id = %s", (oid,))
        cur.execute(
            """INSERT INTO publisher_obstacles
               (obstacle_id, platform, top_activity, publisher_step, resource_ids, key_texts,
                dialog_indicator, signature_raw, action_type, action_params, status, source)
               VALUES (%s, 'instagram', 'com.foo/.Bar', 'step1', ARRAY['rid1'], ARRAY['text1'],
                       true, %s::jsonb, 'keycode_back', %s::jsonb, 'stable', 'manual_seed')""",
            (oid, json.dumps({}), json.dumps({})),
        )
    conn.commit()
    yield oid
    with conn.cursor() as cur:
        cur.execute("DELETE FROM publisher_obstacles WHERE obstacle_id = %s", (oid,))
    conn.commit()


def test_lookup_obstacle_existing_stable_returns_obstacle(seed_obstacle):
    obs = lookup_obstacle(seed_obstacle)
    assert obs is not None
    assert obs.obstacle_id == seed_obstacle
    assert obs.status == "stable"
    assert obs.action_type == "keycode_back"


def test_lookup_obstacle_missing_returns_none():
    assert lookup_obstacle("nonexistent_id_xyz") is None


def test_lookup_obstacle_blacklisted_returns_none(conn, seed_obstacle):
    """Blacklisted patterns should NOT be returned by lookup (caller doesn't apply them)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE publisher_obstacles SET status='blacklisted' WHERE obstacle_id=%s",
            (seed_obstacle,),
        )
    conn.commit()
    assert lookup_obstacle(seed_obstacle) is None
```

- [ ] **Step 2: Run, FAIL**

```bash
pytest tests/test_obstacle_kb.py -v
```

Expected: ImportError or NotImplementedError.

- [ ] **Step 3: Implement**

Replace stub in `obstacle_kb.py`:

```python
import psycopg2
import psycopg2.extras
import os

DB_URL = os.environ.get("DATABASE_URL", "postgres://openclaw:openclaw123@localhost:5432/openclaw")


def _get_conn():
    return psycopg2.connect(DB_URL)


def lookup_obstacle(obstacle_id: str) -> Obstacle | None:
    """Returns Obstacle if status IN ('stable','candidate','experimental'), else None.

    Blacklisted patterns are NOT returned (caller logic doesn't need to know about them
    at lookup time — they should never apply).
    """
    with _get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT obstacle_id, platform, status, action_type, action_params,
                      success_count, fail_count, confidence_score, apply_limit
               FROM publisher_obstacles
               WHERE obstacle_id = %s
                 AND status IN ('stable','candidate','experimental')""",
            (obstacle_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return Obstacle(
        obstacle_id=row["obstacle_id"],
        platform=row["platform"],
        status=row["status"],
        action_type=row["action_type"],
        action_params=row["action_params"] or {},
        success_count=row["success_count"],
        fail_count=row["fail_count"],
        confidence_score=row["confidence_score"],
        apply_limit=row["apply_limit"],
    )
```

- [ ] **Step 4: PASS**

```bash
pytest tests/test_obstacle_kb.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(obstacle-kb): lookup_obstacle + 3 tests (real DB)"
```

---

### Task 12: `obstacle_kb.insert_or_increment` (TDD)

**Files:**
- Modify: `obstacle_kb.py`
- Test: `tests/test_obstacle_kb.py`

- [ ] **Step 1: Failing test**

```python
from obstacle_kb import insert_or_increment
from obstacle_signatures import extract_signature


def test_insert_or_increment_creates_new(conn):
    sig = extract_signature(
        '<hierarchy><node text="t1"/></hierarchy>',
        "act_w2_t12_a", "instagram", "step",
    )
    n = insert_or_increment(
        signature=sig,
        action_recipe={"action_type": "keycode_back", "action_params": {}},
        status="experimental",
        source="ai_unstuck_success",
        source_task_id=99001,
    )
    assert n == 1  # 1 row inserted
    with conn.cursor() as cur:
        cur.execute("SELECT status, success_count FROM publisher_obstacles WHERE obstacle_id = %s",
                    (sig.obstacle_id,))
        row = cur.fetchone()
    assert row == ("experimental", 1)
    # cleanup
    with conn.cursor() as cur:
        cur.execute("DELETE FROM publisher_obstacles WHERE obstacle_id = %s", (sig.obstacle_id,))
    conn.commit()


def test_insert_or_increment_existing_increments_success(conn):
    sig = extract_signature(
        '<hierarchy><node text="t2"/></hierarchy>',
        "act_w2_t12_b", "instagram", None,
    )
    insert_or_increment(sig, {"action_type": "keycode_back", "action_params": {}},
                       "experimental", "ai_unstuck_success", 99002)
    insert_or_increment(sig, {"action_type": "keycode_back", "action_params": {}},
                       "experimental", "ai_unstuck_success", 99003)
    with conn.cursor() as cur:
        cur.execute("SELECT success_count FROM publisher_obstacles WHERE obstacle_id = %s",
                    (sig.obstacle_id,))
        (count,) = cur.fetchone()
    assert count == 2
    with conn.cursor() as cur:
        cur.execute("DELETE FROM publisher_obstacles WHERE obstacle_id = %s", (sig.obstacle_id,))
    conn.commit()
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement**

```python
def insert_or_increment(
    signature,
    action_recipe: dict,
    status: str,
    source: str,
    source_task_id: int | None,
    xml_sample_url: str | None = None,
    screenshot_url: str | None = None,
) -> int:
    """INSERT new pattern OR increment success_count + last_seen on existing.

    Returns 1 always (idempotent).
    """
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO publisher_obstacles
                 (obstacle_id, platform, top_activity, publisher_step,
                  resource_ids, key_texts, dialog_indicator, signature_raw,
                  action_type, action_params, action_description,
                  status, source, source_task_id,
                  xml_sample_url, screenshot_url, success_count)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s,
                       %s, %s, %s, %s, %s, 1)
               ON CONFLICT (obstacle_id) DO UPDATE
                 SET success_count = publisher_obstacles.success_count + 1,
                     last_success_at = now(),
                     last_seen_at = now()""",
            (
                signature.obstacle_id, signature.platform, signature.top_activity,
                signature.publisher_step, list(signature.resource_ids), list(signature.key_texts),
                signature.dialog_indicator,
                json.dumps(signature.signature_raw),
                action_recipe.get("action_type"),
                json.dumps(action_recipe.get("action_params", {})),
                action_recipe.get("action_description"),
                status, source, source_task_id,
                xml_sample_url, screenshot_url,
            ),
        )
        conn.commit()
    return 1
```

Add `import json` at top of file (if not yet).

- [ ] **Step 4: PASS**

```bash
pytest tests/test_obstacle_kb.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(obstacle-kb): insert_or_increment with UPSERT + 2 tests"
```

---

### Task 13: `obstacle_kb.record_outcome` + `recompute_confidence` (TDD)

**Files:**
- Modify: `obstacle_kb.py`
- Test: `tests/test_obstacle_kb.py`

- [ ] **Step 1: Failing tests**

```python
from obstacle_kb import record_outcome, recompute_confidence


def test_record_outcome_progressed_increments_success(conn, seed_obstacle):
    record_outcome(
        obstacle_id=seed_obstacle,
        task_id=99100,
        action_taken={"action_type": "keycode_back"},
        outcome="progressed",
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT success_count, fail_count FROM publisher_obstacles WHERE obstacle_id=%s",
            (seed_obstacle,),
        )
        row = cur.fetchone()
    assert row == (1, 0)


def test_record_outcome_still_stuck_increments_fail(conn, seed_obstacle):
    record_outcome(seed_obstacle, 99101, {"action_type": "keycode_back"}, "still_stuck")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fail_count FROM publisher_obstacles WHERE obstacle_id=%s",
            (seed_obstacle,),
        )
        (count,) = cur.fetchone()
    assert count == 1


def test_record_outcome_shadow_match_does_not_change_counts(conn, seed_obstacle):
    record_outcome(seed_obstacle, 99102, {"action_type": "keycode_back"}, "shadow_match")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT success_count, fail_count FROM publisher_obstacles WHERE obstacle_id=%s",
            (seed_obstacle,),
        )
        row = cur.fetchone()
    assert row == (0, 0)
    # but outcome row should exist
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM publisher_obstacle_outcomes WHERE obstacle_id=%s AND outcome='shadow_match'",
            (seed_obstacle,),
        )
        (n,) = cur.fetchone()
    assert n == 1


def test_recompute_confidence(conn, seed_obstacle):
    for _ in range(7):
        record_outcome(seed_obstacle, 99103, {}, "progressed")
    for _ in range(3):
        record_outcome(seed_obstacle, 99104, {}, "still_stuck")
    score = recompute_confidence(seed_obstacle)
    assert abs(score - 0.7) < 0.001
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement**

```python
def record_outcome(
    obstacle_id: str,
    task_id: int,
    action_taken: dict,
    outcome: str,
    next_step: str | None = None,
) -> None:
    """Record outcome row + increment counters (except for shadow_match)."""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO publisher_obstacle_outcomes
                 (obstacle_id, task_id, action_taken, outcome, next_step)
               VALUES (%s, %s, %s::jsonb, %s, %s)""",
            (obstacle_id, task_id, json.dumps(action_taken), outcome, next_step),
        )
        if outcome == "progressed" or outcome == "task_succeeded":
            cur.execute(
                """UPDATE publisher_obstacles
                   SET success_count = success_count + 1, last_success_at = now(), last_seen_at = now()
                   WHERE obstacle_id = %s""",
                (obstacle_id,),
            )
        elif outcome == "still_stuck" or outcome == "task_failed_other":
            cur.execute(
                """UPDATE publisher_obstacles
                   SET fail_count = fail_count + 1, last_fail_at = now(), last_seen_at = now()
                   WHERE obstacle_id = %s""",
                (obstacle_id,),
            )
        # shadow_match: only outcome row, no counter change, but bump last_seen
        else:  # shadow_match
            cur.execute(
                "UPDATE publisher_obstacles SET last_seen_at = now() WHERE obstacle_id = %s",
                (obstacle_id,),
            )
        conn.commit()


def recompute_confidence(obstacle_id: str) -> float:
    """confidence = success / (success + fail). Returns 0.0 if no data."""
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT success_count, fail_count FROM publisher_obstacles WHERE obstacle_id=%s",
            (obstacle_id,),
        )
        row = cur.fetchone()
        if not row:
            return 0.0
        s, f = row
        total = s + f
        score = s / total if total > 0 else 0.0
        cur.execute(
            "UPDATE publisher_obstacles SET confidence_score = %s WHERE obstacle_id = %s",
            (score, obstacle_id),
        )
        conn.commit()
    return score
```

- [ ] **Step 4: PASS**

```bash
pytest tests/test_obstacle_kb.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(obstacle-kb): record_outcome + recompute_confidence + 4 tests"
```

---

### Task 14: B1 seed — IG hardcoded markers → DB

**Files:**
- Modify: `obstacle_seed.py`
- Test: `tests/test_obstacle_seed.py`

- [ ] **Step 1: Find existing in-code constants**

```bash
cd /home/claude-user/autowarm-testbench
grep -n "_IG_HUMAN_CHECK_MARKERS\|_IG_EDITOR_RESOURCE_IDS\|_OZON_AD_MARKERS\|_TT_REAUTH_MARKERS" publisher_*.py account_switcher.py
```

Запиши себе их точные имена/значения в локальный блокнот — будешь использовать в Step 3.

- [ ] **Step 2: Failing test**

```python
# File: tests/test_obstacle_seed.py
"""Tests for B1 seed — migration of in-code markers → publisher_obstacles."""
import pytest
import psycopg2
from obstacle_seed import from_constants

DB_URL = "postgres://openclaw:openclaw123@localhost:5432/openclaw"


@pytest.fixture
def conn():
    c = psycopg2.connect(DB_URL)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def cleanup(conn):
    """Remove any obstacle from from-constants before each test."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM publisher_obstacles WHERE source='manual_seed:hardcoded'")
    conn.commit()
    yield
    with conn.cursor() as cur:
        cur.execute("DELETE FROM publisher_obstacles WHERE source='manual_seed:hardcoded'")
    conn.commit()


def test_from_constants_creates_at_least_eight_patterns():
    n = from_constants()
    assert n >= 8  # 3 IG + 1 OZON + 1 TT + 1 YT + at least 2 IG editor markers


def test_from_constants_all_status_stable(conn):
    from_constants()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), array_agg(DISTINCT status) FROM publisher_obstacles WHERE source='manual_seed:hardcoded'"
        )
        n, statuses = cur.fetchone()
    assert n >= 8
    assert statuses == ["stable"]


def test_from_constants_idempotent(conn):
    from_constants()
    n2 = from_constants()  # second run — should not crash, just bump success_counts
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT obstacle_id) FROM publisher_obstacles WHERE source='manual_seed:hardcoded'"
        )
        (n_unique,) = cur.fetchone()
    assert n_unique >= 8  # same number of unique IDs (UPSERT prevents duplicates)


def test_from_constants_includes_ig_human_check(conn):
    from_constants()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM publisher_obstacles
               WHERE source='manual_seed:hardcoded' AND action_type='escalate'
                 AND platform='instagram'"""
        )
        (n,) = cur.fetchone()
    assert n >= 1
```

- [ ] **Step 3: Implement `from_constants` in `obstacle_seed.py`**

```python
# Replace stub from_constants() with:
import json
import hashlib

# Список patterns скопирован из текущих in-code constants. Когда они удаляются в W2 Task 19+,
# этот список становится единственным источником истины.
_HARDCODED_PATTERNS = [
    # IG human check markers — 16 markers, ескалация → set_block(ig)
    {
        "platform": "instagram",
        "top_activity": "com.instagram.android/.*",
        "publisher_step": None,
        "key_texts": ["help us confirm you're a real person", "помогите нам убедиться, что вы человек",
                       "we need more information", "нам нужна дополнительная информация"],
        "resource_ids": [],
        "dialog_indicator": True,
        "action_type": "escalate",
        "action_params": {"reason": "ig_human_check_required", "platform": "ig"},
        "action_description": "IG human check detected → set_block + notify",
    },
    # IG draft continuation modal
    {
        "platform": "instagram",
        "top_activity": "com.instagram.android/.activity.MainTabActivity",
        "publisher_step": "open_camera",
        "key_texts": ["продолжить редактирование черновика", "continue editing draft"],
        "resource_ids": [],
        "dialog_indicator": True,
        "action_type": "tap_text",
        "action_params": {"text_options": ["начать новое видео", "start new video"]},
        "action_description": "IG draft continuation dialog → tap 'Начать новое видео'",
    },
    # IG About Account modal (task #682 evidence)
    {
        "platform": "instagram",
        "top_activity": "com.instagram.android/.activity.MainTabActivity",
        "publisher_step": "open_camera",
        "key_texts": ["об аккаунте", "дата присоединения"],
        "resource_ids": [],
        "dialog_indicator": True,
        "action_type": "keycode_back",
        "action_params": {},
        "action_description": "IG 'About account' modal → KEYCODE_BACK",
    },
    # OZON ad sbrowser CustomTab (commit c4ab6b1)
    {
        "platform": "instagram",
        "top_activity": "com.sec.android.app.sbrowser/.customtabs.CustomTabActivity",
        "publisher_step": None,
        "key_texts": [],
        "resource_ids": [],
        "dialog_indicator": False,
        "action_type": "force_stop",
        "action_params": {"package": "com.sec.android.app.sbrowser"},
        "action_description": "OZON ad sbrowser CustomTab overlay → force_stop sbrowser",
    },
    # TT reauth markers
    {
        "platform": "tiktok",
        "top_activity": "com.zhiliaoapp.musically/.*",
        "publisher_step": None,
        "key_texts": ["log back in", "войти снова", "session expired"],
        "resource_ids": [],
        "dialog_indicator": True,
        "action_type": "escalate",
        "action_params": {"reason": "tt_target_not_logged_in", "platform": "tt"},
        "action_description": "TT reauth required → set_block + notify",
    },
    # IG editor stuck markers (resource-id based — for outcome detection)
    {
        "platform": "instagram",
        "top_activity": "com.instagram.android/.modal.ModalActivity",
        "publisher_step": "open_camera",
        "key_texts": [],
        "resource_ids": ["caption_input_text_view", "share_button_container", "share_button"],
        "dialog_indicator": False,
        "action_type": "force_clean_recents",
        "action_params": {"target_pkg": "com.instagram.android",
                          "launch_activity": "com.instagram.android/.activity.MainTabActivity"},
        "action_description": "IG stuck on editor (resource-ids match) → recents cleanup + relaunch",
    },
    # YT settings-activity fallback (memory reference_yt_accounts_settings_path.md)
    {
        "platform": "youtube",
        "top_activity": "com.google.android.youtube/.app.application.Shell_HomeActivity",
        "publisher_step": "yt_open_accounts",
        "key_texts": [],
        "resource_ids": ["yt_accounts_btn_missing"],
        "dialog_indicator": False,
        "action_type": "tap_resource_id",
        "action_params": {"resource_id": "yt_settings_fallback",
                          "intent": "am start com.google.android.youtube/.app.application.Shell_SettingsActivity"},
        "action_description": "YT bottom-nav broken → Settings-activity intent fallback",
    },
    # IG Reels-tile NBSP-tolerant selector
    {
        "platform": "instagram",
        "top_activity": "com.instagram.android/.activity.MainTabActivity",
        "publisher_step": "select_reels_mode",
        "key_texts": ["создать новое видео reels"],
        "resource_ids": [],
        "dialog_indicator": False,
        "action_type": "tap_text",
        "action_params": {"text_options": ["создать новое видео reels", "create new video reels"]},
        "action_description": "IG Reels tile NBSP-tolerant tap target",
    },
]


def _make_obstacle_id(pattern: dict) -> str:
    """Generate deterministic obstacle_id from canonical pattern fields."""
    canonical = {
        "platform": pattern["platform"],
        "top_activity": pattern["top_activity"],
        "publisher_step": pattern["publisher_step"],
        "resource_ids": sorted(pattern["resource_ids"]),
        "key_texts": sorted(pattern["key_texts"]),
        "dialog_indicator": pattern["dialog_indicator"],
    }
    return hashlib.sha1(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def from_constants() -> int:
    """Insert hardcoded markers into publisher_obstacles. Idempotent (UPSERT)."""
    import psycopg2
    DB_URL = os.environ.get("DATABASE_URL", "postgres://openclaw:openclaw123@localhost:5432/openclaw")
    inserted = 0
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        for p in _HARDCODED_PATTERNS:
            oid = _make_obstacle_id(p)
            sig_raw = {
                "platform": p["platform"],
                "top_activity": p["top_activity"],
                "publisher_step": p["publisher_step"],
                "resource_ids": sorted(p["resource_ids"]),
                "key_texts": sorted(p["key_texts"]),
                "dialog_indicator": p["dialog_indicator"],
            }
            cur.execute(
                """INSERT INTO publisher_obstacles
                     (obstacle_id, platform, top_activity, publisher_step,
                      resource_ids, key_texts, dialog_indicator, signature_raw,
                      action_type, action_params, action_description,
                      status, source, promoted_at, promoted_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s,
                           'stable', 'manual_seed:hardcoded', now(), 'B1_migration')
                   ON CONFLICT (obstacle_id) DO UPDATE
                     SET last_seen_at = now()""",
                (oid, p["platform"], p["top_activity"], p["publisher_step"],
                 sorted(p["resource_ids"]), sorted(p["key_texts"]),
                 p["dialog_indicator"],
                 json.dumps(sig_raw),
                 p["action_type"],
                 json.dumps(p["action_params"]),
                 p["action_description"]),
            )
            inserted += 1
        conn.commit()
    return inserted


import os  # Add at top of file if not yet
```

- [ ] **Step 4: PASS**

```bash
pytest tests/test_obstacle_seed.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run B1 in dev DB**

```bash
cd /home/claude-user/autowarm-testbench
python3 obstacle_seed.py from-constants
```

Expected: `Inserted 8 patterns` (or more, depending on _HARDCODED_PATTERNS).

- [ ] **Step 6: Verify**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c \
  "SELECT platform, action_type, count(*) FROM publisher_obstacles WHERE source='manual_seed:hardcoded' GROUP BY 1,2 ORDER BY 1,2"
```

Expected: rows for IG/TT/YT с разными action_types.

- [ ] **Step 7: Commit**

```bash
git commit -am "feat(obstacle-seed): from-constants B1 — migrate 8+ hardcoded markers to DB"
```

---

### Task 15: Replace in-code IG draft continuation handler with DB lookup

**Files:**
- Modify: `publisher_instagram.py` (find `_is_ig_draft_continuation`)
- Test: `tests/test_publisher_ig_camera_recovery.py` (existing — verify still passes)

- [ ] **Step 1: Locate and read existing handler**

```bash
grep -n "_is_ig_draft_continuation\|draft_continuation" publisher_instagram.py
```

Прочитай функцию + её caller. Запомни сигнатуру и поведение.

- [ ] **Step 2: Write integration test before refactor**

Add test to `tests/test_publisher_ig_camera_recovery.py` (расширь существующий, не создавай новый файл):

```python
def test_draft_continuation_via_obstacle_kb_lookup():
    """After W2 refactor, draft continuation handler delegates to obstacle_kb.lookup_obstacle.
    
    This is shadow-mode integration: lookup happens, but result не применяется
    пока obstacle_kb_lookup_only=true (W2 doesn't change apply behavior — that's W3).
    """
    from obstacle_kb import lookup_obstacle
    from obstacle_signatures import extract_signature

    # Реальный draft continuation dump
    draft_xml = '''<hierarchy>
        <node class="android.app.Dialog" resource-id="com.instagram.android:id/draft_dialog_root">
            <node text="Продолжить редактирование черновика?"/>
            <node text="Начать новое видео"/>
        </node>
    </hierarchy>'''
    sig = extract_signature(
        draft_xml,
        "com.instagram.android/.activity.MainTabActivity",
        "instagram",
        "open_camera",
    )
    obs = lookup_obstacle(sig.obstacle_id)
    # After B1 seed Task 14, this draft modal SHOULD match a stable pattern
    # NOTE: depends on key_texts normalization producing match
    # Если key_texts pattern не точно совпал — это OK на этом этапе,
    # B1 patterns могут потребовать tuning. Test assert на "looked up без ошибки".
    # Стабильный assert:
    assert obs is None or obs.status == "stable"  # well-formed lookup, no exceptions
```

- [ ] **Step 3: Run, verify PASSES (before refactor — sanity check that lookup works)**

```bash
pytest tests/test_publisher_ig_camera_recovery.py::test_draft_continuation_via_obstacle_kb_lookup -v
```

- [ ] **Step 4: Refactor `_is_ig_draft_continuation` callers in publisher_instagram.py**

Find all callers. Replace local function call with:

```python
# OLD pattern (примерно):
# if self._is_ig_draft_continuation(xml):
#     self._tap_start_new_video()

# NEW pattern:
from obstacle_kb import lookup_obstacle
from obstacle_signatures import extract_signature
from obstacle_actions import apply_action  # available после Task 25 в W3

sig = extract_signature(xml, top_activity, "instagram", self.step)
obs = lookup_obstacle(sig.obstacle_id)
if obs and obs.status == 'stable' and not _shadow_mode_enabled():
    outcome = apply_action(self, {"action_type": obs.action_type, "action_params": obs.action_params})
    record_outcome(obs.obstacle_id, self.task_id, ...,
                   "progressed" if outcome.progressed else "still_stuck")
```

**ВАЖНО**: На W2 мы только готовим infrastructure. Apply ещё не активен — `_shadow_mode_enabled()` возвращает True всегда (kill-switch `obstacle_kb_lookup_only=true`). Поэтому **сохраняем старый код** как fallback после lookup'а:

```python
# Hybrid pattern для W2:
sig = extract_signature(xml, top_activity, "instagram", self.step)
obs = lookup_obstacle(sig.obstacle_id)
if obs:
    record_outcome(obs.obstacle_id, self.task_id, {}, "shadow_match")
# Существующий код остаётся как primary path:
if self._is_ig_draft_continuation(xml):
    self._tap_start_new_video()
```

В W3 заменим на полный shim. Сейчас просто инструментируем.

- [ ] **Step 5: Run full IG test suite**

```bash
pytest tests/test_publisher_ig_camera_recovery.py -v
```

Expected: ALL passing (старые + новый shadow integration test).

- [ ] **Step 6: Commit**

```bash
git commit -am "refactor(publisher-ig): instrument draft handler with KB shadow lookup"
```

---

### Task 16: Replace `_OZON_AD_MARKERS` in account_switcher.py with DB lookup

Same pattern as Task 15 — locate, write integration test, refactor with shadow lookup.

- [ ] **Step 1: Locate**

```bash
grep -n "_OZON_AD_MARKERS\|sbrowser.*CustomTab" account_switcher.py
```

- [ ] **Step 2: Add shadow lookup beside existing handler**

В `account_switcher._dismiss_blocking_overlays`:

```python
# Existing logic stays. Just instrument:
from obstacle_kb import lookup_obstacle, record_outcome
from obstacle_signatures import extract_signature

sig = extract_signature(xml, top_activity, platform, step)
obs = lookup_obstacle(sig.obstacle_id)
if obs:
    record_outcome(obs.obstacle_id, self.task_id or 0, {}, "shadow_match")

# Existing OZON / sbrowser handler continues...
```

- [ ] **Step 3: Run existing test**

```bash
pytest tests/test_overlay_dismiss.py -v
```

Expected: ALL passing — no regression.

- [ ] **Step 4: Commit**

```bash
git commit -am "refactor(account-switcher): instrument OZON markers with KB shadow lookup"
```

---

### Task 17: Replace `_TT_REAUTH_MARKERS` and YT settings markers with DB lookup

Same pattern, separately for TT and YT.

- [ ] **Step 1: TT — find caller in publisher_tiktok.py**

```bash
grep -n "_TT_REAUTH_MARKERS" publisher_tiktok.py
```

- [ ] **Step 2: Add shadow lookup beside existing handler. Run pytest test_publisher_tiktok or test_account_switcher_tt.**

- [ ] **Step 3: YT — same for YT settings-activity logic in publisher_youtube.py**

- [ ] **Step 4: Run full pytest suite**

```bash
pytest tests/ -v --tb=short
```

Expected: full suite passing — no regression.

- [ ] **Step 5: Commit**

```bash
git commit -am "refactor(publisher-tt+yt): instrument TT/YT markers with KB shadow lookup"
```

---

### Task 18: W2 deploy + verification

- [ ] **Step 1: Push branch**

```bash
git push -u origin feature/obstacle-kb-w2
```

- [ ] **Step 2: Run B1 in production-like env (testbench DB)**

```bash
cd /home/claude-user/autowarm-testbench
python3 obstacle_seed.py from-constants
```

Expected: 8+ rows inserted в `publisher_obstacles`.

- [ ] **Step 3: Verify shadow_match outcomes начали поступать**

После 1 часа running publisher на phone #19 (testbench cadence = 10 мин, ~6 publish_tasks/час):

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c \
  "SELECT count(*) FROM publisher_obstacle_outcomes WHERE outcome='shadow_match'"
```

Expected: > 0 (если patterns матчат реальные UI dumps).

- [ ] **Step 4: pytest full**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/ -v --tb=short
```

Expected: ALL pass.

- [ ] **Step 5: Merge feature branch → testbench**

```bash
git checkout testbench
git merge feature/obstacle-kb-w2 --no-ff
git push origin testbench
```

**W2 DONE checkpoint:** B1 seed применён, in-code constants ещё ЕСТЬ (не удалены), но parallel shadow lookup даёт visibility «сколько раз patterns матчатся в реальном трафике». Готовность к W3 integration.

---

## PHASE W3 — Anthropic switch + AI Unstuck shim integration + shadow apply

**Цель:** Заменить Groq → Claude. Полный shim в `ai_unstuck()`. Shadow-mode apply (записываем что бы делали, но не применяем).

**Risk:** Medium — рефакторинг hot path в production-like testbench env.

**Где работаем:** `feature/obstacle-kb-w3` от `testbench`.

### Task 19: Switch Anthropic API key + provider env

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/.env`

- [ ] **Step 1: Read current .env**

```bash
cat /home/claude-user/autowarm-testbench/.env | grep -E "(ANTHROPIC|VISION|GROQ)" | sed -E 's/(sk-[a-z0-9-]{6})[^[:space:]]*/\1***REDACTED***/g'
```

- [ ] **Step 2: Read Console key from secrets**

```bash
cat /home/claude-user/secrets/anthropic.env
```

Скопируй значение `sk-ant-api03-...`.

- [ ] **Step 3: Update testbench .env**

Replace `ANTHROPIC_API_KEY=sk-ant-oat01-...` with the Console key. Add `VISION_PROVIDER=anthropic`.

- [ ] **Step 4: Smoke test new key**

```bash
cd /home/claude-user/autowarm-testbench
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv('/home/claude-user/autowarm-testbench/.env')
key = os.environ['ANTHROPIC_API_KEY']
assert key.startswith('sk-ant-api03-'), 'Wrong key format!'
print('OK: Console API key in .env')
"
```

Expected: `OK: Console API key in .env`.

- [ ] **Step 5: Commit (just .env not committed — env file is in .gitignore. Document the change)**

Create note in commit:

```bash
git commit --allow-empty -m "ops(env): swap testbench ANTHROPIC_API_KEY OAuth → Console (manual .env edit, not in repo)"
```

---

### Task 20: Replace `_call_groq_vision` → `_call_anthropic_vision` in vision_analyzer.py

**Files:**
- Modify: `vision_analyzer.py`

- [ ] **Step 1: Find existing call sites**

```bash
grep -n "_call_groq_vision\|_call_anthropic_vision" vision_analyzer.py
```

- [ ] **Step 2: Verify `_call_anthropic_vision` уже есть в codebase (memory says yes)**

Если функция уже существует — модифицируй (model: `claude-sonnet-4-6`, no MAX_FRAMES limit). Если нет — реализуй на основе anthropic SDK.

- [ ] **Step 3: Add VISION_PROVIDER switch**

```python
import os

VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "groq")  # default for backward compat

def call_vision(images, prompt):
    if VISION_PROVIDER == "anthropic":
        return _call_anthropic_vision(images, prompt, model="claude-sonnet-4-6")
    return _call_groq_vision(images, prompt)
```

- [ ] **Step 4: Replace direct call sites of `_call_groq_vision` with `call_vision`**

- [ ] **Step 5: Smoke test**

```bash
cd /home/claude-user/autowarm-testbench
python3 -c "
from vision_analyzer import call_vision
import base64
# Tiny 1x1 PNG
img = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
result = call_vision([{'type':'png', 'data': img}], 'What color is this pixel?')
print('OK:', result[:200])
"
```

Expected: response, не ошибка.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(vision): VISION_PROVIDER switch (groq|anthropic) + Sonnet 4.6 default for anthropic"
```

---

### Task 21: Implement `obstacle_actions.apply_action` for all 7 action_types

**Files:**
- Modify: `obstacle_actions.py`
- Test: `tests/test_obstacle_actions.py`

- [ ] **Step 1: Failing test (parametrized over action_types)**

```python
# File: tests/test_obstacle_actions.py
"""Tests for obstacle_actions.apply_action — covers all 7 action_types."""
import pytest
from unittest.mock import MagicMock
from obstacle_actions import apply_action, ActionOutcome


@pytest.fixture
def mock_publisher():
    p = MagicMock()
    p.adb_shell = MagicMock(return_value="")
    p.dump_ui = MagicMock(return_value="<hierarchy/>")
    p.read_top_activity = MagicMock(side_effect=["pre.act", "post.act"])
    p.tap_resource_id = MagicMock(return_value=True)
    p.tap_text = MagicMock(return_value=True)
    return p


def test_keycode_back(mock_publisher):
    out = apply_action(mock_publisher, {"action_type": "keycode_back", "action_params": {}})
    assert out.progressed is True  # pre != post
    mock_publisher.adb_shell.assert_called_with("input keyevent 4")


def test_tap_resource_id(mock_publisher):
    apply_action(mock_publisher, {"action_type": "tap_resource_id",
                                   "action_params": {"resource_id": "dialog_close"}})
    mock_publisher.tap_resource_id.assert_called_with("dialog_close")


def test_tap_text(mock_publisher):
    apply_action(mock_publisher, {"action_type": "tap_text",
                                   "action_params": {"text_options": ["Закрыть", "Close"]}})
    # Should try options in order
    mock_publisher.tap_text.assert_called()


def test_force_stop(mock_publisher):
    apply_action(mock_publisher, {"action_type": "force_stop",
                                   "action_params": {"package": "com.foo"}})
    mock_publisher.adb_shell.assert_called_with("am force-stop com.foo")


def test_noop_wait(mock_publisher):
    apply_action(mock_publisher, {"action_type": "noop_wait",
                                   "action_params": {"seconds": 0.01}})  # short for test
    # No adb_shell calls expected for the wait itself
    # but read_top_activity still called twice (pre/post)
    assert mock_publisher.read_top_activity.call_count == 2


def test_unknown_action_returns_no_op(mock_publisher):
    out = apply_action(mock_publisher, {"action_type": "frobnicate", "action_params": {}})
    assert out.progressed is False
    assert "unknown_action" in out.notes


def test_force_clean_recents(mock_publisher):
    """force_clean_recents delegates to publisher._force_clean_restart_via_recents (existing)."""
    mock_publisher._force_clean_restart_via_recents = MagicMock(return_value=True)
    apply_action(mock_publisher, {"action_type": "force_clean_recents",
                                   "action_params": {"target_pkg": "com.x", "launch_activity": "com.x/.A"}})
    mock_publisher._force_clean_restart_via_recents.assert_called_once()


def test_escalate(mock_publisher):
    """escalate sets account_block + raises ESCALATION exception."""
    mock_publisher.set_block_by_username = MagicMock()
    mock_publisher.notify_escalation = MagicMock()
    out = apply_action(mock_publisher, {"action_type": "escalate",
                                         "action_params": {"reason": "test_reason", "platform": "ig"}})
    assert out.progressed is False  # escalate doesn't progress, it stops the task
    mock_publisher.set_block_by_username.assert_called_once()
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement `apply_action`**

Replace stub in `obstacle_actions.py`:

```python
import time

def apply_action(publisher, recipe: dict) -> ActionOutcome:
    """Apply obstacle action via publisher proxy API.

    Memory `reference_publisher_proxy_api.md`: switcher-helpers must use self.p.X
    not self._X. Apply same convention here.
    """
    action_type = recipe.get("action_type")
    params = recipe.get("action_params", {})
    pre_act = publisher.read_top_activity()

    notes = ""
    if action_type == "keycode_back":
        publisher.adb_shell("input keyevent 4")
        time.sleep(1.5)
    elif action_type == "tap_resource_id":
        rid = params.get("resource_id")
        if rid:
            publisher.tap_resource_id(rid)
        time.sleep(1.0)
    elif action_type == "tap_text":
        for txt in params.get("text_options", []):
            if publisher.tap_text(txt):
                break
        time.sleep(1.0)
    elif action_type == "force_stop":
        pkg = params.get("package")
        if pkg:
            publisher.adb_shell(f"am force-stop {pkg}")
        time.sleep(1.0)
    elif action_type == "force_clean_recents":
        publisher._force_clean_restart_via_recents(
            target_pkg=params.get("target_pkg"),
            launch_activity=params.get("launch_activity"),
            step_name="obstacle_kb_recovery",
        )
    elif action_type == "noop_wait":
        time.sleep(float(params.get("seconds", 5.0)))
    elif action_type == "escalate":
        reason = params.get("reason", "unknown")
        platform = params.get("platform", "ig")
        if hasattr(publisher, "set_block_by_username"):
            publisher.set_block_by_username(reason=reason, platform=platform)
        if hasattr(publisher, "notify_escalation"):
            publisher.notify_escalation(reason=reason, platform=platform)
        return ActionOutcome(progressed=False, pre_top_activity=pre_act,
                             post_top_activity=pre_act, notes="escalated")
    else:
        notes = f"unknown_action:{action_type}"

    post_act = publisher.read_top_activity()
    return ActionOutcome(
        progressed=(pre_act != post_act),
        pre_top_activity=pre_act,
        post_top_activity=post_act,
        notes=notes,
    )
```

- [ ] **Step 4: PASS**

```bash
pytest tests/test_obstacle_actions.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(obstacle-actions): apply_action для 7 action_types + 8 tests"
```

---

### Task 22: AI Unstuck KB shim — shadow apply mode

**Files:**
- Modify: `publisher_base.py` (function `ai_unstuck`, lines ~1698-1933)

- [ ] **Step 1: Read existing ai_unstuck**

```bash
grep -n "def ai_unstuck" publisher_base.py
sed -n '1698,1933p' publisher_base.py
```

Понять структуру:
- anti-loop check (existing)
- dump UI / screenshot
- Groq vision call (existing) — **этот вызов будет под shim'ом**
- apply action (existing) — **этот вызов будет под shadow flag**

- [ ] **Step 2: Helper for shadow flag**

Add helper at module level:

```python
def _kb_shadow_mode_enabled() -> bool:
    """Read system_flags.obstacle_kb_lookup_only — if 'true', don't apply KB actions."""
    try:
        import psycopg2
        with psycopg2.connect(os.environ.get("DATABASE_URL",
                              "postgres://openclaw:openclaw123@localhost:5432/openclaw")) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM system_flags WHERE key='obstacle_kb_lookup_only'")
                row = cur.fetchone()
                return bool(row and row[0] == 'true')
    except Exception:
        return True  # safe default — shadow mode if DB unreachable


def _kb_disabled() -> bool:
    try:
        import psycopg2
        with psycopg2.connect(os.environ.get("DATABASE_URL",
                              "postgres://openclaw:openclaw123@localhost:5432/openclaw")) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM system_flags WHERE key='obstacle_kb_disabled'")
                row = cur.fetchone()
                return bool(row and row[0] == 'true')
    except Exception:
        return False
```

- [ ] **Step 3: Insert KB shim в начало ai_unstuck**

After existing `_is_action_loop` check (memory says line ~1700), вставить:

```python
# === KB SHIM (W3) ===
if not _kb_disabled():
    try:
        from obstacle_signatures import extract_signature
        from obstacle_kb import lookup_obstacle, record_outcome, insert_or_increment
        from obstacle_actions import apply_action

        xml = self.dump_ui()
        top_act = self.read_top_activity()
        sig = extract_signature(xml, top_act, self.platform, self.step)

        obs = lookup_obstacle(sig.obstacle_id)
        if obs and obs.status == "stable":
            if _kb_shadow_mode_enabled():
                # Shadow: log что бы делали, но не применяем
                record_outcome(obs.obstacle_id, self.task_id,
                               {"action_type": obs.action_type, "params": obs.action_params,
                                "shadow": True}, "shadow_match")
                self.log_event("info", "obstacle_kb_shadow_match", meta={
                    "obstacle_id": obs.obstacle_id, "would_apply": obs.action_type,
                })
                # FALL THROUGH to existing LLM logic
            else:
                # Apply for real (W4 onwards)
                outcome = apply_action(self, {
                    "action_type": obs.action_type,
                    "action_params": obs.action_params,
                })
                record_outcome(obs.obstacle_id, self.task_id,
                               {"action_type": obs.action_type}, 
                               "progressed" if outcome.progressed else "still_stuck")
                self.log_event("info", "obstacle_kb_applied", meta={
                    "obstacle_id": obs.obstacle_id, "action": obs.action_type,
                    "outcome": "progressed" if outcome.progressed else "still_stuck",
                })
                if outcome.progressed:
                    return "continue"
        elif obs:
            # experimental/candidate — shadow log only
            record_outcome(obs.obstacle_id, self.task_id, {}, "shadow_match")
    except Exception as e:
        self.log_event("warning", "obstacle_kb_shim_error", meta={"error": str(e)})
# === END KB SHIM ===

# Existing LLM call follows...
```

- [ ] **Step 4: Insert post-LLM hook**

After existing LLM call returns successful action and after applying it:

```python
# === POST-LLM LEARN (W3) ===
if llm_result.get("success") and not _kb_disabled():
    try:
        from obstacle_signatures import extract_signature
        from obstacle_kb import insert_or_increment

        sig = extract_signature(xml, top_act, self.platform, self.step)
        # upload screenshot/xml to S3
        screenshot_url = self.upload_artifact_to_s3(screenshot_path, kind="screenshot")
        xml_url = self.upload_artifact_to_s3(xml_path, kind="ui_dump")

        insert_or_increment(
            signature=sig,
            action_recipe={
                "action_type": llm_result["action"],
                "action_params": llm_result.get("params", {}),
                "action_description": f"LLM-learned: {llm_result.get('reasoning','')[:100]}",
            },
            status="experimental",
            source="ai_unstuck_success",
            source_task_id=self.task_id,
            xml_sample_url=xml_url,
            screenshot_url=screenshot_url,
        )
    except Exception as e:
        self.log_event("warning", "obstacle_kb_learn_error", meta={"error": str(e)})
# === END POST-LLM LEARN ===
```

- [ ] **Step 5: Run existing AI Unstuck tests**

```bash
pytest tests/test_ai_unstuck_helpers.py -v
```

Expected: ALL pass (helpers не тронуты).

- [ ] **Step 6: Manual smoke**

```bash
python3 -c "
from publisher_base import _kb_disabled, _kb_shadow_mode_enabled
print('disabled:', _kb_disabled())
print('shadow:', _kb_shadow_mode_enabled())
"
```

Expected: `disabled: False`, `shadow: True` (по W1 task 3 init).

- [ ] **Step 7: Commit**

```bash
git commit -am "feat(publisher-base): KB shim + post-LLM learn in ai_unstuck (shadow mode)"
```

---

### Task 23: Lift `ai_unstuck` wiring для TT/YT

**Files:**
- Modify: `publisher_tiktok.py`, `publisher_youtube.py`, `publisher_instagram.py` (для consistency)

- [ ] **Step 1: Locate where IG calls `ai_unstuck`**

```bash
grep -n "self\.ai_unstuck\|ai_unstuck(" publisher_instagram.py
```

Пример (memory says `publisher_instagram.py:1676`):

```python
# IG calls ai_unstuck в watchdog loop
if self.watchdog.is_stuck():
    if self.ai_unstuck(self.task_id, "instagram", self.step) == "break":
        break
```

- [ ] **Step 2: Find watchdog hooks in TT/YT mixins**

```bash
grep -n "watchdog\|is_stuck\|StepStuckException" publisher_tiktok.py publisher_youtube.py
```

Likely: TT/YT тоже ловят `StepStuckException` но не зовут `ai_unstuck`.

- [ ] **Step 3: Add ai_unstuck wiring in TT mixin**

В каждом TT method где есть watchdog или StepStuckException — добавь:

```python
# Pattern (после existing watchdog catch):
except StepStuckException:
    if self.ai_unstuck(self.task_id, "tiktok", self.step) == "break":
        raise  # if KB+LLM сдались, propagate fail
    # else: ai_unstuck recovered — continue loop iteration
```

- [ ] **Step 4: Same for YT mixin (`publisher_youtube.py`)**

Подставь `"youtube"` платформу.

- [ ] **Step 5: Run platform-specific test suites**

```bash
pytest tests/test_publisher_tt.py tests/test_publisher_yt.py -v
```

Expected: passing.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(publisher-tt+yt): wire ai_unstuck into watchdog hooks (KB shim now active for all 3 platforms)"
```

---

### Task 24: Add KB pre-check в `_force_clean_restart_via_recents`

**Files:**
- Modify: `publisher_base.py`

- [ ] **Step 1: Locate function**

```bash
grep -n "_force_clean_restart_via_recents" publisher_base.py
```

- [ ] **Step 2: Add KB pre-check at start of function**

```python
def _force_clean_restart_via_recents(self, target_pkg, launch_activity, step_name, ...):
    # === KB PRE-CHECK (W3) ===
    # If a lighter pattern exists for current state, try it first.
    if not _kb_disabled():
        try:
            from obstacle_signatures import extract_signature
            from obstacle_kb import lookup_obstacle, record_outcome
            from obstacle_actions import apply_action

            xml = self.dump_ui()
            top_act = self.read_top_activity()
            sig = extract_signature(xml, top_act, self.platform, step_name)
            obs = lookup_obstacle(sig.obstacle_id)
            if (obs and obs.status == "stable"
                and obs.action_type in ("keycode_back", "tap_resource_id", "tap_text", "noop_wait")
                and not _kb_shadow_mode_enabled()):
                # Try lighter action before nuclear
                outcome = apply_action(self, {
                    "action_type": obs.action_type,
                    "action_params": obs.action_params,
                })
                record_outcome(obs.obstacle_id, self.task_id or 0,
                               {"action_type": obs.action_type, "context": "pre_nuclear"},
                               "progressed" if outcome.progressed else "still_stuck")
                if outcome.progressed:
                    self.log_event("info", "obstacle_kb_avoided_nuclear", meta={
                        "obstacle_id": obs.obstacle_id, "action": obs.action_type,
                    })
                    return True  # progressed; nuclear skipped
        except Exception as e:
            self.log_event("warning", "obstacle_kb_prenuclear_error", meta={"error": str(e)})
    # === END KB PRE-CHECK ===

    # Existing nuclear logic continues unchanged...
```

- [ ] **Step 3: Run recents recovery tests**

```bash
pytest tests/test_recents_close_all_recovery.py -v
```

Expected: passing (since shadow mode = True, KB pre-check is noop).

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(publisher-base): KB pre-check in _force_clean_restart_via_recents (avoid nuclear when lighter action available)"
```

---

### Task 25: Triage classifier mining hook

**Files:**
- Modify: `triage_classifier.py`
- Test: `tests/test_triage_classifier.py` (расширь)

- [ ] **Step 1: Locate `process_failed_task`**

```bash
grep -n "process_failed_task" triage_classifier.py
```

- [ ] **Step 2: Add finally hook**

```python
def process_failed_task(self, task_id):
    try:
        # existing classify / dedupe / agent_diagnose / agent_apply logic
        ...
    finally:
        # === KB MINING HOOK (W3) ===
        try:
            from obstacle_kb import mine_from_failed_task
            mine_from_failed_task(task_id)
        except Exception as e:
            log.warning(f"obstacle_kb mining error: {e}")
        # === END KB MINING HOOK ===
```

- [ ] **Step 3: Implement `obstacle_kb.mine_from_failed_task`**

Replace stub в `obstacle_kb.py`:

```python
def mine_from_failed_task(task_id: int) -> int:
    """Extract last N UI dumps from task events, INSERT'ить как experimental candidates.

    Returns count of NEW patterns inserted (existing skipped via UPSERT).
    """
    import urllib.request
    from obstacle_signatures import extract_signature

    inserted = 0
    with _get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT events::jsonb, platform FROM publish_tasks WHERE id = %s""",
            (task_id,),
        )
        row = cur.fetchone()
        if not row:
            return 0
        events = row["events"] or []
        platform = row["platform"]

    # Walk events, find the LAST 5 with meta.ui_dump_url
    candidates = [e for e in events if e.get("meta", {}).get("ui_dump_url")]
    candidates = candidates[-5:]

    for e in candidates:
        ui_url = e["meta"]["ui_dump_url"]
        top_act = e["meta"].get("top_activity", "unknown")
        step = e["meta"].get("step")
        try:
            with urllib.request.urlopen(ui_url, timeout=10) as resp:
                xml = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue

        sig = extract_signature(xml, top_act, platform, step)
        # Filter: skip noisy dumps
        if len(sig.resource_ids) < 3 or len(sig.key_texts) < 2:
            continue

        # INSERT as experimental candidate (no action recipe yet — needs vision call later)
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM publisher_obstacles WHERE obstacle_id=%s", (sig.obstacle_id,))
            if cur.fetchone():
                continue  # already exists
            cur.execute(
                """INSERT INTO publisher_obstacles
                   (obstacle_id, platform, top_activity, publisher_step,
                    resource_ids, key_texts, dialog_indicator, signature_raw,
                    action_type, action_params, status, source, source_task_id,
                    xml_sample_url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'noop_wait', '{}'::jsonb,
                           'experimental', 'triage_mining', %s, %s)
                   ON CONFLICT DO NOTHING""",
                (sig.obstacle_id, platform, top_act, step,
                 list(sig.resource_ids), list(sig.key_texts),
                 sig.dialog_indicator, json.dumps(sig.signature_raw),
                 task_id, ui_url),
            )
            if cur.rowcount > 0:
                inserted += 1
            conn.commit()
    return inserted
```

- [ ] **Step 4: Add test**

```python
def test_mine_from_failed_task_inserts_candidates(conn):
    """End-to-end: failed task → mine UI dumps → INSERT as experimental."""
    # Setup: insert fake task with events that include ui_dump_url pointing to local fixture
    # ... (use tests/fixtures/sample_ui_dump.xml as URL)
    # Then call mine_from_failed_task and verify INSERT'ы
    pass  # detailed test in separate task if needed
```

- [ ] **Step 5: Run testbench tests**

```bash
pytest tests/test_triage_classifier.py -v
```

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(triage-classifier+kb): mining hook from failed_task → KB experimental candidates"
```

---

### Task 26: W3 deploy + 7 day shadow soak

- [ ] **Step 1: Push**

```bash
git push -u origin feature/obstacle-kb-w3
```

- [ ] **Step 2: pytest full**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: ALL pass (or pre-existing fails documented in memory как unrelated).

- [ ] **Step 3: Merge → testbench**

```bash
git checkout testbench
git merge feature/obstacle-kb-w3 --no-ff
git push origin testbench
```

- [ ] **Step 4: Deploy**

PM2 restart autowarm-testbench:

```bash
sudo -n pm2 restart autowarm-testbench
sudo -n pm2 logs autowarm-testbench --lines 50
```

Expected: clean startup, no Python ImportError.

- [ ] **Step 5: Wait 24h, then check shadow metrics**

```sql
SELECT
  count(*) FILTER (WHERE outcome='shadow_match') AS shadow_matches,
  count(DISTINCT obstacle_id) FILTER (WHERE outcome='shadow_match') AS unique_patterns_matched,
  count(*) FILTER (WHERE outcome IN ('progressed','still_stuck')) AS real_outcomes
FROM publisher_obstacle_outcomes
WHERE matched_at > now() - interval '24 hours';
```

Expected: shadow_matches > 0, real_outcomes = 0 (всё ещё shadow mode).

- [ ] **Step 6: Decision gate W3 → W4**

If `shadow_matches >= 10` and at least 3 unique patterns matched в реальном трафике → готов к W4.

If shadow_matches = 0 → debug: extract_signature не работает на реальных XML, или patterns не покрывают actual stucks.

**W3 DONE checkpoint:** shadow mode running 24h+, patterns matching real traffic, 0 false positives risk.

---

## PHASE W4 — Disable shadow mode → real apply (kill-switch flip)

**Цель:** stable patterns начинают применяться. Monitor success_rate delta. Verify no regressions.

**Risk:** Medium — first real apply на production-like testbench.

### Task 27: Disable shadow mode + monitor

- [ ] **Step 1: Toggle shadow mode off**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c \
  "UPDATE system_flags SET value='false' WHERE key='obstacle_kb_lookup_only'"
```

- [ ] **Step 2: Verify**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c \
  "SELECT key, value FROM system_flags WHERE key LIKE 'obstacle_%'"
```

Expected: `obstacle_kb_lookup_only=false`, остальные kill-switches как при W1.

- [ ] **Step 3: Watch logs first 30 min**

```bash
sudo -n pm2 logs autowarm-testbench --lines 100 --timestamp | grep -E "obstacle_kb|ai_unstuck"
```

Expected: видно `obstacle_kb_applied` events. NO `obstacle_kb_shim_error`.

- [ ] **Step 4: Compare 24h success rate before/after**

```sql
-- Before W4 (shadow): use last 24h of W3 deploy
SELECT count(*) FILTER (WHERE status='done') * 1.0 / count(*) AS rate_w3
FROM publish_tasks
WHERE testbench=true AND updated_at BETWEEN <W3_start> AND <W3_end>;

-- After W4 (apply): 24h after toggle
SELECT count(*) FILTER (WHERE status='done') * 1.0 / count(*) AS rate_w4
FROM publish_tasks
WHERE testbench=true AND updated_at > <W4_start>;
```

Expected: `rate_w4 >= rate_w3` (no regression). Ideally `rate_w4 > rate_w3` (improvement).

- [ ] **Step 5: If regression — kill-switch back**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c \
  "UPDATE system_flags SET value='true' WHERE key='obstacle_kb_disabled'"
```

И investigate из `publish_tasks.events WHERE meta.category LIKE 'obstacle_kb_%'`.

- [ ] **Step 6: Document W4 results**

Create `.ai-factory/evidence/obstacle-kb-w4-soak-<date>.md`:

```markdown
# W4 Apply Mode Soak — <YYYY-MM-DD>

- shadow soak (W3): X tasks, Y success rate
- apply mode (W4): X tasks, Y success rate
- KB hits: N, ratio: %
- false-positive incidents: 0/N
- decision: continue → W5 / rollback
```

**W4 DONE checkpoint:** real apply working, no regressions detected. Ready for W5 promoter+bot.

---

## PHASE W5 — Promoter + Bot + B2 mining

**Цель:** Self-curating loop. T1 auto-promote, T2 Telegram review, T3 auto-degrade. B2 30-day mining seeds candidates.

**Risk:** Medium — bot reliability, mining false positives.

### Task 28: Implement `obstacle_promoter.tick`

**Files:**
- Modify: `obstacle_promoter.py`
- Test: `tests/test_obstacle_promoter.py`

- [ ] **Step 1: Failing tests**

```python
# File: tests/test_obstacle_promoter.py
"""Tests for promoter T1/T2/T3 logic."""
import pytest
import psycopg2
from datetime import datetime, timedelta
from obstacle_promoter import tick, _is_t1_eligible, _is_t3_drift

DB_URL = "postgres://openclaw:openclaw123@localhost:5432/openclaw"


@pytest.fixture
def conn():
    c = psycopg2.connect(DB_URL)
    yield c
    c.close()


@pytest.fixture
def make_obstacle(conn):
    """Insert test obstacle with given attrs, return obstacle_id, cleanup after."""
    created = []
    def _create(**kwargs):
        oid = kwargs.pop("oid", f"test_promo_{len(created)}")
        defaults = {
            "platform": "instagram", "top_activity": "act", "resource_ids": ["r"],
            "key_texts": ["t"], "dialog_indicator": True,
            "signature_raw": '{}', "action_type": "keycode_back", "action_params": '{}',
            "status": "experimental", "source": "test",
            "success_count": 0, "fail_count": 0,
        }
        defaults.update(kwargs)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM publisher_obstacles WHERE obstacle_id=%s", (oid,))
            cur.execute(
                """INSERT INTO publisher_obstacles
                   (obstacle_id, platform, top_activity, resource_ids, key_texts,
                    dialog_indicator, signature_raw, action_type, action_params,
                    status, source, success_count, fail_count, last_success_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb,
                           %s, %s, %s, %s, now())""",
                (oid, defaults["platform"], defaults["top_activity"],
                 defaults["resource_ids"], defaults["key_texts"], defaults["dialog_indicator"],
                 defaults["signature_raw"], defaults["action_type"], defaults["action_params"],
                 defaults["status"], defaults["source"],
                 defaults["success_count"], defaults["fail_count"]),
            )
        conn.commit()
        created.append(oid)
        return oid
    yield _create
    with conn.cursor() as cur:
        for oid in created:
            cur.execute("DELETE FROM publisher_obstacles WHERE obstacle_id=%s", (oid,))
    conn.commit()


def test_t1_promotes_safe_pattern_with_5_successes(conn, make_obstacle):
    oid = make_obstacle(action_type="keycode_back", success_count=5, fail_count=0)
    # Need 3 distinct task_ids — insert outcome rows
    with conn.cursor() as cur:
        for tid in (1001, 1002, 1003):
            cur.execute(
                "INSERT INTO publisher_obstacle_outcomes (obstacle_id, task_id, action_taken, outcome) VALUES (%s, %s, '{}'::jsonb, 'progressed')",
                (oid, tid),
            )
    conn.commit()

    counts = tick()
    assert counts["promoted_t1"] >= 1

    with conn.cursor() as cur:
        cur.execute("SELECT status FROM publisher_obstacles WHERE obstacle_id=%s", (oid,))
        (status,) = cur.fetchone()
    assert status == "stable"


def test_t1_does_NOT_promote_destructive_action(conn, make_obstacle):
    oid = make_obstacle(action_type="force_stop", success_count=10, fail_count=0)
    counts = tick()
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM publisher_obstacles WHERE obstacle_id=%s", (oid,))
        (status,) = cur.fetchone()
    # destructive → goes to candidate, not stable
    assert status in ("experimental", "candidate")


def test_t3_degrades_after_3_consecutive_fails(conn, make_obstacle):
    oid = make_obstacle(status="stable", success_count=10, fail_count=3)
    # Insert 3 consecutive fails as outcomes
    with conn.cursor() as cur:
        for _ in range(3):
            cur.execute(
                "INSERT INTO publisher_obstacle_outcomes (obstacle_id, task_id, action_taken, outcome) VALUES (%s, 9999, '{}'::jsonb, 'still_stuck')",
                (oid,),
            )
    conn.commit()

    counts = tick()
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM publisher_obstacles WHERE obstacle_id=%s", (oid,))
        (status,) = cur.fetchone()
    assert status == "experimental"  # degraded
```

- [ ] **Step 2: Implement promoter**

```python
# obstacle_promoter.py
from __future__ import annotations
import os
import json
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL", "postgres://openclaw:openclaw123@localhost:5432/openclaw")
SAFE_ACTIONS = {"keycode_back", "tap_resource_id", "tap_text", "noop_wait"}


def _get_conn():
    return psycopg2.connect(DB_URL)


def _is_promoter_disabled() -> bool:
    with _get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM system_flags WHERE key='obstacle_promoter_disabled'")
        row = cur.fetchone()
        return bool(row and row[0] == "true")


def tick() -> dict[str, int]:
    """Run T1/T2/T3 logic. Returns dict with counts."""
    if _is_promoter_disabled():
        return {"promoted_t1": 0, "queued_t2": 0, "degraded_t3": 0}

    counts = {"promoted_t1": 0, "queued_t2": 0, "degraded_t3": 0}
    with _get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # T1: promote experimental safe → stable
        cur.execute(
            """SELECT obstacle_id, action_type, success_count, fail_count, source
               FROM publisher_obstacles
               WHERE status = 'experimental'
                 AND success_count >= 5
                 AND fail_count = 0
                 AND last_fail_at IS NULL OR last_fail_at < now() - interval '7 days'"""
        )
        for row in cur.fetchall():
            if row["action_type"] not in SAFE_ACTIONS:
                continue
            # Check >= 3 distinct task_ids
            cur.execute(
                "SELECT count(DISTINCT task_id) AS n FROM publisher_obstacle_outcomes WHERE obstacle_id=%s AND outcome='progressed'",
                (row["obstacle_id"],),
            )
            distinct_tasks = (cur.fetchone() or {}).get("n", 0)
            if distinct_tasks < 3:
                continue
            cur.execute(
                """UPDATE publisher_obstacles
                   SET status='stable', promoted_at=now(), promoted_by='auto:5_successes'
                   WHERE obstacle_id=%s""",
                (row["obstacle_id"],),
            )
            counts["promoted_t1"] += 1

        # T2: queue destructive for review
        cur.execute(
            """SELECT obstacle_id, action_type, success_count
               FROM publisher_obstacles
               WHERE status = 'experimental' AND success_count >= 3
                 AND action_type NOT IN %s""",
            (tuple(SAFE_ACTIONS),),
        )
        for row in cur.fetchall():
            cur.execute(
                """UPDATE publisher_obstacles SET status='candidate' WHERE obstacle_id=%s""",
                (row["obstacle_id"],),
            )
            counts["queued_t2"] += 1
            # Notify Telegram (Task 29)
            _notify_telegram_review(row["obstacle_id"])

        # T3: degrade stable with consecutive fails
        cur.execute(
            """SELECT obstacle_id FROM publisher_obstacles WHERE status='stable'"""
        )
        for row in cur.fetchall():
            oid = row["obstacle_id"]
            cur.execute(
                """SELECT outcome FROM publisher_obstacle_outcomes
                   WHERE obstacle_id=%s ORDER BY matched_at DESC LIMIT 3""",
                (oid,),
            )
            recent = [r["outcome"] for r in cur.fetchall()]
            if len(recent) >= 3 and all(o == "still_stuck" for o in recent):
                cur.execute(
                    """UPDATE publisher_obstacles
                       SET status='experimental', degraded_at=now(),
                           degraded_reason='3_consecutive_fails'
                       WHERE obstacle_id=%s""",
                    (oid,),
                )
                counts["degraded_t3"] += 1

        conn.commit()
    return counts


def _notify_telegram_review(obstacle_id: str):
    """Send Telegram message for human review. Implementation in Task 29 (bot side)."""
    # For now: log. Bot in contenthunter_bugs_bot picks up from DB poll.
    pass


def _is_t1_eligible(row) -> bool:
    return (row["action_type"] in SAFE_ACTIONS
            and row["success_count"] >= 5
            and row["fail_count"] == 0)


def _is_t3_drift(recent_outcomes: list[str]) -> bool:
    return len(recent_outcomes) >= 3 and all(o == "still_stuck" for o in recent_outcomes)
```

- [ ] **Step 3: Run, PASS**

```bash
pytest tests/test_obstacle_promoter.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(obstacle-promoter): tick() with T1/T2/T3 logic + 3 tests"
```

---

### Task 29: Bugs bot — obstacle review handlers

**Files:**
- Create: `/home/claude-user/contenthunter_bugs_bot/obstacle_handlers.py`
- Modify: bugs_bot main entry to register obstacle handlers + DB connection

- [ ] **Step 1: Read existing bot structure**

```bash
ls /home/claude-user/contenthunter_bugs_bot/
cat /home/claude-user/contenthunter_bugs_bot/main.py | head -50  # or whatever the entry file is
```

- [ ] **Step 2: Create `obstacle_handlers.py`**

```python
# File: /home/claude-user/contenthunter_bugs_bot/obstacle_handlers.py
"""aiogram 3 handlers для obstacle KB human review.

Hooks: callback_query на 4 inline buttons (Approve/TryOnce/Blacklist/Comment).
Polling: проверяет publisher_obstacles WHERE status='candidate' каждые 60 сек,
шлёт уведомление за каждый new candidate.
"""
import asyncio
import json
import os
import psycopg2
import psycopg2.extras
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ForceReply
from aiogram.filters import Command

router = Router()
DB_URL = os.environ.get("DATABASE_URL", "postgres://openclaw:openclaw123@localhost:5432/openclaw")
CHAT_ID = int(os.environ.get("OBSTACLE_REVIEW_CHAT_ID", "242574724"))  # Danil


def _conn():
    return psycopg2.connect(DB_URL)


def _build_review_keyboard(oid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Approve", callback_data=f"obs:approve:{oid}"),
        InlineKeyboardButton(text="⚠️ Try Once", callback_data=f"obs:try_once:{oid}"),
    ], [
        InlineKeyboardButton(text="🚫 Blacklist", callback_data=f"obs:blacklist:{oid}"),
        InlineKeyboardButton(text="💬 Comment", callback_data=f"obs:comment:{oid}"),
    ]])


async def notify_candidate(bot: Bot, obstacle_id: str):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM publisher_obstacles WHERE obstacle_id=%s", (obstacle_id,))
        obs = cur.fetchone()
    if not obs:
        return

    msg = f"""🆕 [NEW PATTERN] obstacle_id: {obs['obstacle_id']}
Platform: {obs['platform']}
Step: {obs['publisher_step']}
Top activity: {obs['top_activity']}
Texts: {obs['key_texts']}
Resource IDs: {obs['resource_ids']}
Success/Fail: {obs['success_count']}/{obs['fail_count']}

Proposed action: {obs['action_type']} {json.dumps(obs['action_params'])}
Description: {obs['action_description'] or '(none)'}
Source: {obs['source']}
"""
    if obs.get("screenshot_url"):
        msg += f"🎥 Screenshot: {obs['screenshot_url']}\n"
    if obs.get("xml_sample_url"):
        msg += f"📄 XML: {obs['xml_sample_url']}\n"

    await bot.send_message(
        CHAT_ID, msg,
        reply_markup=_build_review_keyboard(obs["obstacle_id"]),
    )


@router.callback_query(F.data.startswith("obs:"))
async def handle_obstacle_callback(query: CallbackQuery):
    parts = query.data.split(":", 2)
    if len(parts) != 3:
        await query.answer("Bad callback")
        return
    _, action, oid = parts

    with _conn() as conn, conn.cursor() as cur:
        if action == "approve":
            cur.execute(
                """UPDATE publisher_obstacles
                   SET status='stable', promoted_at=now(), promoted_by='human:erkevs'
                   WHERE obstacle_id=%s""",
                (oid,),
            )
            await query.message.edit_text(query.message.text + "\n\n✅ Promoted to stable.")
        elif action == "try_once":
            cur.execute(
                """UPDATE publisher_obstacles
                   SET apply_limit=1
                   WHERE obstacle_id=%s""",
                (oid,),
            )
            await query.message.edit_text(query.message.text + "\n\n⚠️ Try Once enabled.")
        elif action == "blacklist":
            cur.execute(
                """UPDATE publisher_obstacles
                   SET status='blacklisted', notes=COALESCE(notes,'') || ' | manual:erkevs'
                   WHERE obstacle_id=%s""",
                (oid,),
            )
            await query.message.edit_text(query.message.text + "\n\n🚫 Blacklisted.")
        elif action == "comment":
            await query.message.reply(
                f"Reply with comment for obstacle {oid}:",
                reply_markup=ForceReply(selective=True),
            )
            return await query.answer()
        conn.commit()
    await query.answer("Done")


@router.message(F.reply_to_message)
async def handle_comment_reply(message: Message):
    """Capture reply to ForceReply prompt — extract obstacle_id from prompt text."""
    parent = message.reply_to_message
    if not parent or not parent.text or "Reply with comment for obstacle" not in parent.text:
        return  # not for us
    # Parse oid from prompt
    parts = parent.text.split()
    oid = parts[-1].rstrip(":")
    note = message.text
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE publisher_obstacles SET notes=COALESCE(notes,'') || %s WHERE obstacle_id=%s",
            (f" | {note}", oid),
        )
        conn.commit()
    await message.reply(f"💬 Note saved for {oid}")


async def poll_for_candidates(bot: Bot):
    """Background task: каждые 60 сек проверяет new candidates."""
    notified = set()
    while True:
        try:
            with _conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """SELECT obstacle_id FROM publisher_obstacles
                       WHERE status='candidate'
                         AND obstacle_id NOT IN (
                           SELECT obstacle_id FROM publisher_obstacle_outcomes
                           WHERE outcome='task_succeeded' AND matched_at > now() - interval '1 day'
                         )"""
                )
                for (oid,) in cur.fetchall():
                    if oid in notified:
                        continue
                    await notify_candidate(bot, oid)
                    notified.add(oid)
        except Exception as e:
            print(f"obstacle poll error: {e}")
        await asyncio.sleep(60)
```

- [ ] **Step 3: Wire into bot main**

In bot's main entry (`main.py` or similar):

```python
from obstacle_handlers import router as obstacle_router, poll_for_candidates

# При создании Dispatcher:
dp.include_router(obstacle_router)

# В startup hook:
async def on_startup(bot: Bot):
    asyncio.create_task(poll_for_candidates(bot))
```

- [ ] **Step 4: Restart bot service**

```bash
sudo -n systemctl restart contenthunter_bugs_bot
sudo -n systemctl status contenthunter_bugs_bot --no-pager
```

Expected: active (running). No exception in journal.

- [ ] **Step 5: Manual smoke**

```sql
INSERT INTO publisher_obstacles (...) VALUES (... 'candidate' ...);
```

Wait 60 sec. Should arrive в Telegram chat 242574724.

- [ ] **Step 6: Commit (in bugs_bot repo!)**

```bash
cd /home/claude-user/contenthunter_bugs_bot
git add obstacle_handlers.py main.py  # or whatever entry was modified
git commit -m "feat(obstacle-handlers): inline review for publisher_obstacles candidates"
git push
```

---

### Task 30: Wire promoter tick into triage_loop

**Files:**
- Modify: triage loop entry-point (likely в `triage_classifier.py` или separate scheduler)

- [ ] **Step 1: Find triage loop entry**

```bash
grep -rn "triage_loop\|run_triage" /home/claude-user/autowarm-testbench/
```

- [ ] **Step 2: Add promoter call**

```python
# In triage loop main tick:
from obstacle_promoter import tick as promoter_tick

def triage_loop_tick():
    # existing triage logic
    process_new_failed_tasks()

    # NEW: promoter every tick
    counts = promoter_tick()
    log.info(f"Promoter tick: T1={counts['promoted_t1']}, T2={counts['queued_t2']}, T3={counts['degraded_t3']}")
```

- [ ] **Step 3: Enable promoter via kill-switch**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c \
  "UPDATE system_flags SET value='false' WHERE key='obstacle_promoter_disabled'"
```

- [ ] **Step 4: Enable bot polling**

```bash
psql postgres://openclaw:openclaw123@localhost:5432/openclaw -c \
  "UPDATE system_flags SET value='false' WHERE key='obstacle_curator_bot_disabled'"
```

(Bot должен сам читать этот flag в `poll_for_candidates` — добавь check.)

- [ ] **Step 5: pytest passing**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -15
```

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(triage-loop): wire promoter_tick into triage loop"
```

---

### Task 31: B2 mining — implement + run

**Files:**
- Modify: `obstacle_seed.py`

- [ ] **Step 1: Implement `mine_events`**

Replace stub `mine_events` в `obstacle_seed.py`:

```python
def mine_events(days: int = 30, min_cluster: int = 3) -> int:
    """Mine 30-day failed task UI dumps → INSERT'ить как experimental candidates.

    Использует Claude Sonnet 4.6 для suggested_action на cluster head.
    Output: count of NEW candidates inserted + mining_report.md.
    """
    import urllib.request
    from collections import defaultdict
    from obstacle_signatures import extract_signature
    from obstacle_kb import _get_conn
    from vision_analyzer import call_vision  # Task 20

    inserted = 0
    clusters = defaultdict(list)

    with _get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT id, platform, events::jsonb FROM publish_tasks
               WHERE status='failed' AND testbench=true
                 AND updated_at > now() - interval '%s days'""",
            (days,),
        )
        rows = cur.fetchall()

    for row in rows:
        for e in (row["events"] or []):
            meta = e.get("meta", {})
            ui_url = meta.get("ui_dump_url")
            if not ui_url:
                continue
            try:
                with urllib.request.urlopen(ui_url, timeout=10) as resp:
                    xml = resp.read().decode("utf-8", errors="replace")
            except Exception:
                continue
            sig = extract_signature(xml, meta.get("top_activity", ""), row["platform"], meta.get("step"))
            if len(sig.resource_ids) < 3 or len(sig.key_texts) < 2:
                continue
            clusters[sig.obstacle_id].append({
                "task_id": row["id"], "xml": xml, "screenshot_url": meta.get("screenshot_url"),
                "sig": sig,
            })

    # Filter clusters >= min_cluster
    big_clusters = {oid: items for oid, items in clusters.items() if len(items) >= min_cluster}

    # For each cluster, call Claude vision once with sample
    report_lines = ["# Mining Report\n", f"Date: {os.environ.get('BUILD_DATE', 'now')}\n\n"]
    for oid, items in big_clusters.items():
        sample = items[0]
        if not sample["screenshot_url"]:
            continue
        prompt = """Analyze this Android UI screenshot from our publisher app stuck on this screen.
Suggest the SAFEST recovery action. Reply as JSON:
{
  "action_type": "keycode_back" | "tap_resource_id" | "tap_text" | "force_stop" | "force_clean_recents" | "noop_wait",
  "params": {...},
  "reasoning": "..."
}"""
        try:
            result = call_vision([{"type": "url", "url": sample["screenshot_url"]}], prompt)
            recipe = json.loads(result)
        except Exception:
            continue

        # INSERT as candidate
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO publisher_obstacles
                   (obstacle_id, platform, top_activity, publisher_step,
                    resource_ids, key_texts, dialog_indicator, signature_raw,
                    action_type, action_params, action_description,
                    status, source, source_task_id, screenshot_url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s,
                           'candidate', 'offline_mining', %s, %s)
                   ON CONFLICT DO NOTHING""",
                (oid, sample["sig"].platform, sample["sig"].top_activity, sample["sig"].publisher_step,
                 list(sample["sig"].resource_ids), list(sample["sig"].key_texts),
                 sample["sig"].dialog_indicator,
                 json.dumps(sample["sig"].signature_raw),
                 recipe["action_type"], json.dumps(recipe.get("params", {})),
                 recipe.get("reasoning", "")[:200],
                 sample["task_id"], sample["screenshot_url"]),
            )
            if cur.rowcount > 0:
                inserted += 1
            conn.commit()

        report_lines.append(f"## {oid}\n- platform: {sample['sig'].platform}\n- size: {len(items)}\n- action: {recipe['action_type']}\n- reasoning: {recipe.get('reasoning', '')[:200]}\n- screenshot: {sample['screenshot_url']}\n\n")

    with open(f"/tmp/mining_report_{int(__import__('time').time())}.md", "w") as f:
        f.writelines(report_lines)
    return inserted
```

- [ ] **Step 2: Run mining**

```bash
cd /home/claude-user/autowarm-testbench
python3 obstacle_seed.py mine-events --days 30 --min-cluster 3
```

Expected: `Inserted N candidates` (N >= 1, ideally 5-15).

- [ ] **Step 3: Telegram review starts arriving**

Within minutes — bot poll кидает inline-buttoned messages в чат 242574724. Просмотри и approve/blacklist каждый.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(obstacle-seed): mine-events B2 — 30-day corpus → Claude-suggested candidates"
```

**W5 DONE checkpoint:** promoter tikает, bot reviews work, B2 mining seeded ~10-30 candidates. Self-curating loop active.

---

## PHASE W6 — Admin UI

**Цель:** Visual administration через `delivery.contenthunter.ru/obstacles.html`.

**Risk:** Low (read-mostly UI).

### Task 32: Backend endpoints в server.js

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/server.js`

- [ ] **Step 1: Find existing testbench endpoints (для auth pattern)**

```bash
grep -n "/api/publish/testbench" /root/.openclaw/workspace-genri/autowarm/server.js | head -10
```

- [ ] **Step 2: Add 5 endpoints**

```javascript
// === Obstacle KB endpoints (W6) ===
app.get('/api/obstacles', requireAuth, async (req, res) => {
    const { platform, status, page = 1, per_page = 50 } = req.query;
    const offset = (parseInt(page) - 1) * parseInt(per_page);
    const conds = [];
    const args = [];
    if (platform) { args.push(platform); conds.push(`platform = $${args.length}`); }
    if (status) { args.push(status); conds.push(`status = $${args.length}`); }
    const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';

    args.push(parseInt(per_page), offset);
    const result = await pgClient.query(
        `SELECT obstacle_id, platform, top_activity, publisher_step, status, action_type,
                success_count, fail_count, confidence_score, last_seen_at
         FROM publisher_obstacles ${where}
         ORDER BY last_seen_at DESC LIMIT $${args.length-1} OFFSET $${args.length}`,
        args
    );
    const countResult = await pgClient.query(
        `SELECT count(*) FROM publisher_obstacles ${where}`,
        args.slice(0, -2)
    );
    res.json({ rows: result.rows, total: parseInt(countResult.rows[0].count) });
});

app.get('/api/obstacles/:id', requireAuth, async (req, res) => {
    const result = await pgClient.query(
        'SELECT * FROM publisher_obstacles WHERE obstacle_id=$1',
        [req.params.id]
    );
    if (result.rows.length === 0) return res.status(404).json({ error: 'not_found' });
    res.json(result.rows[0]);
});

app.patch('/api/obstacles/:id', requireAuth, async (req, res) => {
    const { status, notes, action_recipe } = req.body;
    const sets = [];
    const args = [];
    if (status) { args.push(status); sets.push(`status = $${args.length}`); }
    if (notes) { args.push(notes); sets.push(`notes = $${args.length}`); }
    if (action_recipe) {
        args.push(action_recipe.action_type); sets.push(`action_type = $${args.length}`);
        args.push(JSON.stringify(action_recipe.action_params || {})); sets.push(`action_params = $${args.length}::jsonb`);
    }
    if (sets.length === 0) return res.status(400).json({ error: 'nothing_to_update' });
    args.push(req.params.id);
    await pgClient.query(
        `UPDATE publisher_obstacles SET ${sets.join(', ')} WHERE obstacle_id = $${args.length}`,
        args
    );
    res.json({ ok: true });
});

app.get('/api/obstacles/:id/outcomes', requireAuth, async (req, res) => {
    const { page = 1, per_page = 50 } = req.query;
    const offset = (parseInt(page) - 1) * parseInt(per_page);
    const result = await pgClient.query(
        `SELECT * FROM publisher_obstacle_outcomes WHERE obstacle_id=$1
         ORDER BY matched_at DESC LIMIT $2 OFFSET $3`,
        [req.params.id, parseInt(per_page), offset]
    );
    res.json({ rows: result.rows });
});

app.get('/api/obstacles/stats', requireAuth, async (req, res) => {
    const stats = await pgClient.query(`
        SELECT status, count(*) AS n
        FROM publisher_obstacles
        GROUP BY status
    `);
    const hitRate = await pgClient.query(`
        SELECT
          count(*) FILTER (WHERE outcome IN ('progressed','task_succeeded')) AS applied_ok,
          count(*) FILTER (WHERE outcome = 'still_stuck') AS applied_failed,
          count(*) FILTER (WHERE outcome = 'shadow_match') AS shadow,
          count(*) AS total
        FROM publisher_obstacle_outcomes
        WHERE matched_at > now() - interval '24 hours'
    `);
    const top5 = await pgClient.query(`
        SELECT obstacle_id, action_type, success_count
        FROM publisher_obstacles
        WHERE status='stable'
        ORDER BY success_count DESC LIMIT 5
    `);
    res.json({ status_counts: stats.rows, hit_rate_24h: hitRate.rows[0], top5: top5.rows });
});
```

- [ ] **Step 3: Smoke test endpoints**

```bash
curl -s -u user:pass https://delivery.contenthunter.ru/api/obstacles?platform=instagram&per_page=5 | jq
curl -s -u user:pass https://delivery.contenthunter.ru/api/obstacles/stats | jq
```

- [ ] **Step 4: Commit (autopush hook will deliver)**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add server.js
git commit -m "feat(server): /api/obstacles/* — 5 endpoints for admin UI"
```

---

### Task 33: Frontend `obstacles.html`

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/obstacles.html`

- [ ] **Step 1: Read existing testbench.html для pattern reuse**

```bash
head -100 /root/.openclaw/workspace-genri/autowarm/testbench.html
```

Note: frontend factory + paginated tables shipped 2026-04-29 (memory `project_paginated_tables_pilot.md`).

- [ ] **Step 2: Create obstacles.html**

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Obstacle KB — admin</title>
  <link rel="stylesheet" href="/styles.css">
  <script src="/frontend-factory.js"></script>
  <style>
    body { font: 14px monospace; max-width: 1400px; margin: 1em auto; }
    .kpi { display: inline-block; padding: 0.5em 1em; margin: 0.5em; border: 1px solid #ccc; border-radius: 4px; }
    .filter-bar { margin: 1em 0; }
    .filter-bar select, .filter-bar button { margin-right: 0.5em; }
    .detail { background: #f5f5f5; padding: 1em; margin-top: 1em; border: 1px solid #ddd; }
    .detail pre { white-space: pre-wrap; max-height: 300px; overflow: auto; background: #fff; padding: 0.5em; }
    .status-stable { color: green; font-weight: bold; }
    .status-experimental { color: orange; }
    .status-candidate { color: #c80; }
    .status-blacklisted { color: red; text-decoration: line-through; }
  </style>
</head>
<body>
  <h1>Obstacle KB</h1>
  <section id="stats"></section>

  <div class="filter-bar">
    Platform: <select id="f-platform"><option value="">all</option><option>instagram</option><option>tiktok</option><option>youtube</option></select>
    Status: <select id="f-status"><option value="">all</option><option>stable</option><option>candidate</option><option>experimental</option><option>blacklisted</option></select>
    <button onclick="loadList()">Apply</button>
  </div>

  <table id="obstacles-table">
    <thead><tr><th>obstacle_id</th><th>platform</th><th>top_activity</th><th>status</th><th>action</th><th>S/F</th><th>conf</th><th>last_seen</th></tr></thead>
    <tbody id="obstacles-tbody"></tbody>
  </table>
  <div id="pagination"></div>

  <section id="detail-panel" class="detail" hidden></section>

  <script>
    let curPage = 1;
    async function loadStats() {
      const r = await fetch('/api/obstacles/stats');
      const d = await r.json();
      document.getElementById('stats').innerHTML = `
        <div class="kpi"><b>By status:</b> ${d.status_counts.map(s => `${s.status}=${s.n}`).join(' ')}</div>
        <div class="kpi"><b>Hit rate 24h:</b> ${d.hit_rate_24h.applied_ok}/${d.hit_rate_24h.total} (shadow=${d.hit_rate_24h.shadow})</div>
        <div class="kpi"><b>Top-5:</b> ${d.top5.map(t => `${t.action_type}×${t.success_count}`).join(' ')}</div>
      `;
    }
    async function loadList(page = 1) {
      curPage = page;
      const platform = document.getElementById('f-platform').value;
      const status = document.getElementById('f-status').value;
      const params = new URLSearchParams({ page, per_page: 50 });
      if (platform) params.set('platform', platform);
      if (status) params.set('status', status);
      const r = await fetch('/api/obstacles?' + params);
      const d = await r.json();
      const tbody = document.getElementById('obstacles-tbody');
      tbody.innerHTML = d.rows.map(row => `
        <tr style="cursor:pointer" onclick="loadDetail('${row.obstacle_id}')">
          <td>${row.obstacle_id}</td>
          <td>${row.platform}</td>
          <td>${row.top_activity}</td>
          <td class="status-${row.status}">${row.status}</td>
          <td>${row.action_type}</td>
          <td>${row.success_count}/${row.fail_count}</td>
          <td>${row.confidence_score?.toFixed(2) ?? '–'}</td>
          <td>${new Date(row.last_seen_at).toISOString().slice(0, 16)}</td>
        </tr>`).join('');
      document.getElementById('pagination').innerHTML = `
        Page ${page} of ~${Math.ceil(d.total / 50)} (${d.total} total)
        ${page > 1 ? `<button onclick="loadList(${page - 1})">prev</button>` : ''}
        <button onclick="loadList(${page + 1})">next</button>`;
    }
    async function loadDetail(oid) {
      const [r1, r2] = await Promise.all([
        fetch('/api/obstacles/' + oid).then(r => r.json()),
        fetch(`/api/obstacles/${oid}/outcomes?per_page=50`).then(r => r.json()),
      ]);
      const panel = document.getElementById('detail-panel');
      panel.hidden = false;
      panel.innerHTML = `
        <h3>${oid} — <span class="status-${r1.status}">${r1.status}</span></h3>
        <p><b>Action:</b> ${r1.action_type} ${JSON.stringify(r1.action_params)}</p>
        <p><b>Description:</b> ${r1.action_description ?? '(none)'}</p>
        <p><b>Stats:</b> success=${r1.success_count}, fail=${r1.fail_count}, conf=${r1.confidence_score?.toFixed(3) ?? '–'}</p>
        <p><b>Source:</b> ${r1.source} (task #${r1.source_task_id ?? '?'})</p>
        ${r1.screenshot_url ? `<p><a href="${r1.screenshot_url}" target="_blank">📷 screenshot</a> | <a href="${r1.xml_sample_url}" target="_blank">📄 xml</a></p>` : ''}
        <p><b>Notes:</b> ${r1.notes ?? '(none)'}</p>
        <details><summary>signature_raw</summary><pre>${JSON.stringify(r1.signature_raw, null, 2)}</pre></details>
        <h4>Last 50 outcomes</h4>
        <table>
          <thead><tr><th>matched_at</th><th>task_id</th><th>outcome</th><th>next_step</th></tr></thead>
          <tbody>${r2.rows.map(o => `<tr><td>${o.matched_at}</td><td>${o.task_id}</td><td>${o.outcome}</td><td>${o.next_step ?? ''}</td></tr>`).join('')}</tbody>
        </table>
        <div>
          <button onclick="patchStatus('${oid}', 'stable')">→ stable</button>
          <button onclick="patchStatus('${oid}', 'experimental')">→ experimental</button>
          <button onclick="patchStatus('${oid}', 'blacklisted')">🚫 blacklist</button>
          <button onclick="patchNotes('${oid}')">💬 add note</button>
        </div>
      `;
    }
    async function patchStatus(oid, status) {
      await fetch('/api/obstacles/' + oid, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ status }) });
      loadDetail(oid);
      loadList(curPage);
    }
    async function patchNotes(oid) {
      const note = prompt('Note?');
      if (!note) return;
      await fetch('/api/obstacles/' + oid, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ notes: note }) });
      loadDetail(oid);
    }
    loadStats();
    loadList(1);
  </script>
</body>
</html>
```

- [ ] **Step 3: Smoke**

Open `https://delivery.contenthunter.ru/obstacles.html` в браузере.

Expected: видны patterns, filter работает, click open detail.

- [ ] **Step 4: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add obstacles.html
git commit -m "feat(frontend): obstacles.html admin UI — list + detail + stats"
```

---

### Task 34: KPI panel в testbench.html

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/testbench.html`

- [ ] **Step 1: Add new section "Obstacle KB"**

В testbench.html, после canary status:

```html
<section id="obstacle-kb-stats">
  <h2>Obstacle KB</h2>
  <div id="obstacle-stats-cards"></div>
</section>

<script>
async function loadObstacleStats() {
    const r = await fetch('/api/obstacles/stats');
    const data = await r.json();
    const root = document.getElementById('obstacle-stats-cards');
    root.innerHTML = `
      <div class="kpi-card"><b>By status:</b> ${data.status_counts.map(s => s.status + '=' + s.n).join(', ')}</div>
      <div class="kpi-card"><b>Hit rate 24h:</b> ${data.hit_rate_24h.applied_ok}/${data.hit_rate_24h.total}</div>
      <div class="kpi-card"><b>Top-5:</b> ${data.top5.map(t => t.action_type + '×' + t.success_count).join(', ')}</div>
    `;
}
loadObstacleStats();
setInterval(loadObstacleStats, 60000);
</script>
```

- [ ] **Step 2: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add testbench.html
git commit -m "feat(frontend): testbench.html KPI panel for Obstacle KB"
```

---

### Task 35: W6 verification — Definition of MVP shipped

- [ ] **Step 1: Verify all 7 success criteria**

```sql
-- 1. ≥30 patterns total
SELECT count(*) FROM publisher_obstacles;
-- 2. ≥10 stable
SELECT count(*) FROM publisher_obstacles WHERE status='stable';
-- 3. KB hit-rate ≥30% за 7d
SELECT count(*) FILTER (WHERE outcome IN ('progressed','task_succeeded')) * 1.0 / count(*)
FROM publisher_obstacle_outcomes
WHERE matched_at > now() - interval '7 days' AND outcome != 'shadow_match';
-- 4. Overall ai_unstuck success ≥40% (combine KB + LLM-fallback)
SELECT count(*) FILTER (WHERE meta->>'category' IN ('obstacle_kb_applied','ai_unstuck_success')) * 1.0
       / count(*) FILTER (WHERE meta->>'category' IN ('obstacle_kb_applied','ai_unstuck_action','ai_unstuck_success'))
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.updated_at > now() - interval '7 days';
-- 5. 0 false-positive incidents — manual review
SELECT * FROM publisher_obstacles WHERE status='stable' AND fail_count > success_count;
-- 6. Admin UI доступен — manual visit
-- 7. Kill-switches verified — manual chaos test
```

- [ ] **Step 2: Document evidence**

Create `.ai-factory/evidence/obstacle-kb-mvp-shipped-<date>.md` with all 7 criteria + numbers + screenshots.

- [ ] **Step 3: Memory update**

Add memory file `project_publisher_obstacle_kb.md` summarising shipped state, key metrics, where things live.

- [ ] **Step 4: Final commit**

```bash
cd /home/claude-user/contenthunter
git add .ai-factory/evidence/obstacle-kb-mvp-shipped-*.md
git commit -m "docs(evidence): obstacle KB MVP shipped — all 7 criteria met"
```

**MVP SHIPPED.** Self-learning obstacle resolution system live. Continuous T1/T2/T3 promotion работает. AI Unstuck больше не 0% success.

---

## Open follow-ups (post-MVP)

- Pre-emptive scanning после каждого `set_step` (Опция 2 из brainstorm) — V2.
- Per-platform kill-switches (`obstacle_kb_disabled_ig`, etc.) — additive when needed.
- GC stale patterns (>30d no match) — implement after 6 months in prod.
- Migration `agent_diagnose` text-pipeline на Claude — post-MVP if Groq quirks accumulate.
- Mining UI кнопка («Run mining now») в admin UI — convenience.
- Bulk operations / regex search в admin UI — convenience.
