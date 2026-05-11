# TT post-switch verify recovery — Implementation Plan v1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть silent `tt_post_switch_handle_unknown` regression (21/36h) — после неудачного верификации хедера на TT-фиде вызвать `_navigate_to_profile_tab` и повторить верификацию, либо fail с явным `tt_post_switch_verify_unrecoverable`.

**Architecture:** Approach A из spec — recovery в TT-caller `account_switcher.py:2275-2287` (НЕ менять `_post_switch_verify_handle`). Добавляется helper `_is_tt_feed_after_pick` (distinct markers через set). Reuse Phase 1 `_navigate_to_profile_tab`. Новый error_code маппится в `publisher_kernel.py`.

**Tech Stack:** Python 3.11, pytest, `MagicMock`/`patch.object`. ADB и live phone не требуются для unit-тестов (всё mock).

**Path conventions:**
- **Spec & plan & evidence:** `/home/claude-user/contenthunter/` (agent workspace, main branch — commit-friendly).
- **Deploy tree (code + tests):** `/root/.openclaw/workspace-genri/autowarm/` (PR-driven, auto-push hook → GenGo2/delivery-contenthunter).
- **Branch:** `fix/tt-post-switch-renav-20260511` (autowarm tree).

**Spec:** `docs/superpowers/specs/2026-05-11-tt-post-switch-verify-recovery-design.md` (v2, Codex CLEAN после 1 round).

---

## Task 1: Branch setup + baseline green

**Tree:** deploy (`/root/.openclaw/workspace-genri/autowarm/`)

- [ ] **Step 1: Sync with origin/main and create branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git checkout main
git pull --ff-only origin main
git checkout -b fix/tt-post-switch-renav-20260511
git log -1 --oneline  # confirm starting commit
```

Expected: branch создан, latest main pulled.

- [ ] **Step 2: Verify baseline test suite green**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_account_switcher_tt.py -v 2>&1 | tail -15
```

Expected: all PASS (memory `feedback_validator_test_engine_dispose` про conftest НЕ касается autowarm). Если есть pre-existing fail — записать его и продолжить (не наш baseline).

- [ ] **Step 3: Confirm key symbols exist**

```bash
cd /root/.openclaw/workspace-genri/autowarm
grep -n "def _post_switch_verify_handle\|def _navigate_to_profile_tab\|def get_current_account_from_profile\|MAX_PICK_ATTEMPTS" account_switcher.py | head -10
grep -n "_SWITCHER_STEP_TO_CATEGORY" publisher_kernel.py | head -5
```

Expected:
- `_post_switch_verify_handle` at line 3396 (spec)
- `_navigate_to_profile_tab` exists (Phase 1)
- `get_current_account_from_profile` at line 430
- `_SWITCHER_STEP_TO_CATEGORY` exists в publisher_kernel.py

Если symbol missing — STOP, обновить spec, не продолжать.

---

## Task 2: `_is_tt_feed_after_pick` helper (TDD)

**Tree:** deploy
**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/test_post_switch_renav.py`
- Modify: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (add module-level constant + method)

> **Why first:** Helper изолированно тестируется без mocks switcher state. Завязывает остальные tests через known-good detector.

- [ ] **Step 1: Write 5 helper tests (red)**

Create `/root/.openclaw/workspace-genri/autowarm/tests/test_post_switch_renav.py`:

```python
"""Tests for TT post-switch verify recovery (Approach A).

Covers:
  - `_is_tt_feed_after_pick` helper (TT feed-top-bar detector, 5 tests).
  - Recovery flow в `_handle_tt_account_switch` (mock-based, 4 tests).
  - publisher_kernel.py step→category mapping (1 test).

Run:
    cd /root/.openclaw/workspace-genri/autowarm
    pytest tests/test_post_switch_renav.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from account_switcher import AccountSwitcher  # noqa: E402


def _make_xml_with(bounds_text_desc: list[tuple[str, str, str]]) -> str:
    """Build minimal Android UI XML from (bounds, text, content-desc) tuples.

    `bounds` like '[x1,y1][x2,y2]'.
    """
    nodes = '\n'.join(
        f'<node bounds="{b}" text="{t}" content-desc="{d}" '
        f'class="android.widget.TextView" />'
        for b, t, d in bounds_text_desc
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<hierarchy rotation="0">\n'
        f'  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">\n'
        f'    {nodes}\n'
        '  </node>\n'
        '</hierarchy>'
    )


# ─── _is_tt_feed_after_pick helper tests ────────────────────────────────────


def test_is_tt_feed_two_markers_returns_true():
    """2 distinct markers в top 260px → True."""
    sw = AccountSwitcher.__new__(AccountSwitcher)
    xml = _make_xml_with([
        ('[100,96][300,200]', 'Смотреть', ''),
        ('[300,96][500,200]', 'Подписки', ''),
        ('[100,1000][300,1100]', 'Other', ''),
    ])
    assert sw._is_tt_feed_after_pick(xml, header_y_max=260) is True


def test_is_tt_feed_one_marker_returns_false():
    """1/3 distinct → False (threshold ≥2)."""
    sw = AccountSwitcher.__new__(AccountSwitcher)
    xml = _make_xml_with([
        ('[100,96][300,200]', 'Смотреть', ''),
        ('[100,1000][300,1100]', 'Подписки', ''),  # below header
    ])
    assert sw._is_tt_feed_after_pick(xml, header_y_max=260) is False


def test_is_tt_feed_duplicate_marker_returns_false():
    """Same marker «Смотреть» в text vs content-desc разных нод → distinct {Смотреть}=1 → False.

    Защита от counter-based false-positive (Codex round 1).
    """
    sw = AccountSwitcher.__new__(AccountSwitcher)
    xml = _make_xml_with([
        ('[100,96][300,200]', 'Смотреть', ''),
        ('[100,96][300,200]', '', 'Смотреть'),
    ])
    assert sw._is_tt_feed_after_pick(xml, header_y_max=260) is False


def test_is_tt_feed_below_header_returns_false():
    """Все 3 marker'а ниже y=260 → False."""
    sw = AccountSwitcher.__new__(AccountSwitcher)
    xml = _make_xml_with([
        ('[100,500][300,600]', 'Смотреть', ''),
        ('[300,500][500,600]', 'Подписки', ''),
        ('[500,500][700,600]', 'Рекомендации', ''),
    ])
    assert sw._is_tt_feed_after_pick(xml, header_y_max=260) is False


def test_is_tt_feed_empty_xml_returns_false():
    """Empty / falsy xml → False."""
    sw = AccountSwitcher.__new__(AccountSwitcher)
    assert sw._is_tt_feed_after_pick('', header_y_max=260) is False
    assert sw._is_tt_feed_after_pick(None, header_y_max=260) is False  # type: ignore[arg-type]
```

- [ ] **Step 2: Run tests, verify all red**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_post_switch_renav.py -v 2>&1 | tail -20
```

Expected: 5 FAILED — `AttributeError: 'AccountSwitcher' object has no attribute '_is_tt_feed_after_pick'` (или подобное).

- [ ] **Step 3: Implement `_TT_FEED_MARKERS` + `_is_tt_feed_after_pick`**

В `/root/.openclaw/workspace-genri/autowarm/account_switcher.py`. Найти module-level constants block (рядом с другими `_TT_*` константами; например `_TT_MUSIC_RIGHTS_BUTTON`). Добавить:

```python
# [tt_post_switch_renav 2026-05-11] TikTok feed top-bar markers — detector
# для recovery после pick→feed (вместо expected pick→profile).
# Threshold ≥2 distinct (set, не counter) защита от false-positive когда TT
# дублирует label в text+content-desc разных нод.
_TT_FEED_MARKERS: tuple = ('Смотреть', 'Подписки', 'Рекомендации')
```

В classе `AccountSwitcher`, рядом с другими TT-helper'ами (например после `_post_switch_verify_handle` на line ~3450), добавить метод:

```python
    def _is_tt_feed_after_pick(self, xml: str, header_y_max: int = 260) -> bool:
        """Detect TikTok feed top-bar после account-pick.

        TikTok после переключения через bottomsheet может открыть feed
        (не profile, как ожидает switcher). Detector ищет ≥2 distinct
        markers из `_TT_FEED_MARKERS` в первых `header_y_max` px.

        Distinct (set) НЕ counter: TT часто дублирует label в `text`/
        `content-desc` смежных нод — counter дал бы false-positive.
        """
        if not xml:
            return False
        elements = parse_ui_dump(xml)
        if not elements:
            return False
        seen = set()
        for el in elements:
            y_top = el.bounds[1]
            if y_top > header_y_max:
                continue
            combined = f'{el.text or ""} {el.content_desc or ""}'
            for marker in _TT_FEED_MARKERS:
                if marker in combined:
                    seen.add(marker)
        return len(seen) >= 2
```

(Note: `parse_ui_dump` уже импортируется/использует в account_switcher.py — проверить top-of-file imports на наличие; если parse_ui_dump module-level в том же файле, ОК.)

- [ ] **Step 4: Run tests, verify all green**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_post_switch_renav.py -v 2>&1 | tail -20
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add tests/test_post_switch_renav.py account_switcher.py
git commit -m "feat(switcher): _is_tt_feed_after_pick helper (TT pick→feed detector)"
```

---

## Task 3: Recovery logic в TT-caller (TDD)

**Tree:** deploy
**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py:2275-2287` (TT switcher `unknown` branch)
- Modify: `/root/.openclaw/workspace-genri/autowarm/tests/test_post_switch_renav.py` (append integration tests)

> **Why:** Helper готов и протестирован. Теперь wire его в actual recovery flow.

- [ ] **Step 1: Read current TT-caller context**

```bash
sed -n '2240,2295p' /root/.openclaw/workspace-genri/autowarm/account_switcher.py
```

Зафиксировать: какой класс содержит этот метод (вероятно `AccountSwitcher` или `TikTokSwitcherMixin`), какое имя обрамляющего метода (содержит `for attempt in range(MAX_PICK_ATTEMPTS):` loop).

Note: Recovery должно быть вставлено ВНУТРИ existing `if status == 'unknown':` блока, ПОСЛЕ existing log_event (line 2280-2286), ПЕРЕД `break`.

- [ ] **Step 2: Append 4 recovery integration tests (red)**

В конец `/root/.openclaw/workspace-genri/autowarm/tests/test_post_switch_renav.py` добавить:

```python
# ─── Recovery flow в TT-caller tests ────────────────────────────────────────


def _build_switcher_for_recovery(verify_results, feed_xml, navigate_returns=True):
    """Build AccountSwitcher с моками для recovery-path тестов.

    verify_results: list of ('match'/'mismatch'/'unknown', current) — возвращается
                    последовательно при каждом вызове _post_switch_verify_handle.
    feed_xml:       XML строка для _is_tt_feed_after_pick (mock _make_xml_with).
    navigate_returns: возвращаемое значение _navigate_to_profile_tab.
    """
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.p = MagicMock()
    sw.p.dump_ui = MagicMock(side_effect=[feed_xml, feed_xml])  # initial + post-renav
    sw.p.log_event = MagicMock()
    sw._save_dump = MagicMock()
    sw._maybe_screenshot = MagicMock()
    sw._fail = MagicMock(return_value=False)
    sw._navigate_to_profile_tab = MagicMock(return_value=navigate_returns)
    sw._post_switch_verify_handle = MagicMock(side_effect=verify_results)
    return sw


def test_unknown_with_feed_triggers_navigate_and_renav_match():
    """unknown + feed-markers + renav match → success path + recovered event."""
    feed_xml = _make_xml_with([
        ('[100,96][300,200]', 'Смотреть', ''),
        ('[300,96][500,200]', 'Подписки', ''),
        ('[500,96][700,200]', 'Рекомендации', ''),
    ])
    sw = _build_switcher_for_recovery(
        verify_results=[('unknown', None), ('match', 'targetuser')],
        feed_xml=feed_xml,
    )
    # Invoke the slice of _handle_tt_account_switch that runs the recovery.
    # Implementation detail: helper method `_tt_handle_post_switch_unknown` that we'll
    # extract for testability (see Step 3).
    result = sw._tt_handle_post_switch_unknown(
        target='targetuser', xml_after_pick=feed_xml,
        header_y_max=260, label='tt_4_target_profile', attempt=0,
    )
    assert result == 'recovered'
    assert sw._navigate_to_profile_tab.call_count == 1
    # Check that recovered event was emitted
    emitted_categories = [
        call.kwargs.get('meta', {}).get('category')
        for call in sw.p.log_event.call_args_list
    ]
    assert 'tt_post_switch_feed_after_pick' in emitted_categories
    assert 'tt_post_switch_recovered_via_renav' in emitted_categories


def test_unknown_with_feed_renav_still_unknown_fails():
    """unknown + feed + renav still unknown → _fail с tt_post_switch_verify_unrecoverable."""
    feed_xml = _make_xml_with([
        ('[100,96][300,200]', 'Смотреть', ''),
        ('[300,96][500,200]', 'Подписки', ''),
        ('[500,96][700,200]', 'Рекомендации', ''),
    ])
    sw = _build_switcher_for_recovery(
        verify_results=[('unknown', None), ('unknown', None)],
        feed_xml=feed_xml,
    )
    result = sw._tt_handle_post_switch_unknown(
        target='targetuser', xml_after_pick=feed_xml,
        header_y_max=260, label='tt_4_target_profile', attempt=0,
    )
    assert result == 'failed'
    sw._fail.assert_called_once()
    fail_msg = sw._fail.call_args.args[0]
    assert 'tt_post_switch_verify_unrecoverable' in fail_msg


def test_unknown_with_feed_renav_mismatch_falls_through():
    """unknown + feed + renav mismatch → возвращает 'mismatch' (caller обработает retry)."""
    feed_xml = _make_xml_with([
        ('[100,96][300,200]', 'Смотреть', ''),
        ('[300,96][500,200]', 'Подписки', ''),
        ('[500,96][700,200]', 'Рекомендации', ''),
    ])
    sw = _build_switcher_for_recovery(
        verify_results=[('unknown', None), ('mismatch', 'otheruser')],
        feed_xml=feed_xml,
    )
    result = sw._tt_handle_post_switch_unknown(
        target='targetuser', xml_after_pick=feed_xml,
        header_y_max=260, label='tt_4_target_profile', attempt=0,
    )
    assert result == 'mismatch'
    sw._fail.assert_not_called()


def test_unknown_non_feed_fails_immediately():
    """unknown без feed-markers → _fail сразу, без navigate."""
    no_feed_xml = _make_xml_with([
        ('[100,1500][300,1600]', 'Loading', ''),  # ниже header
    ])
    sw = _build_switcher_for_recovery(
        verify_results=[('unknown', None)],
        feed_xml=no_feed_xml,
    )
    result = sw._tt_handle_post_switch_unknown(
        target='targetuser', xml_after_pick=no_feed_xml,
        header_y_max=260, label='tt_4_target_profile', attempt=0,
    )
    assert result == 'failed'
    sw._navigate_to_profile_tab.assert_not_called()
    fail_msg = sw._fail.call_args.args[0]
    assert 'tt_post_switch_verify_unrecoverable' in fail_msg
    assert 'non-feed' in fail_msg.lower()
```

- [ ] **Step 3: Run tests, verify all red**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_post_switch_renav.py -v -k 'recovery or unknown_with or unknown_non' 2>&1 | tail -20
```

Expected: 4 FAILED — `AttributeError: ... '_tt_handle_post_switch_unknown'`.

- [ ] **Step 4: Implement `_tt_handle_post_switch_unknown` method**

В `/root/.openclaw/workspace-genri/autowarm/account_switcher.py`, рядом с другими TT-helper'ами (например после `_is_tt_feed_after_pick` из Task 2):

```python
    def _tt_handle_post_switch_unknown(self, target: str, xml_after_pick: str,
                                       header_y_max: int, label: str,
                                       attempt: int) -> str:
        """[tt_post_switch_renav 2026-05-11] Recovery для unknown verify status.

        После того как `_post_switch_verify_handle` вернул unknown в TT
        switcher loop:
          1. Детектим TT feed-top-bar в первичном XML.
          2. Если feed → log + navigate-to-profile + re-dump + re-verify.
          3. По re-verify результату:
             - match    → лог recovered_via_renav, return 'recovered' (caller breaks)
             - mismatch → return 'mismatch' (caller продолжает в existing
                          mismatch-handler с MAX_PICK_ATTEMPTS retry)
             - unknown  → _fail с tt_post_switch_verify_unrecoverable
          4. Если в первичном XML feed-markers НЕТ (FLAG_SECURE / sparse /
             непредвиденный UI) → _fail сразу без navigate.

        Returns: 'recovered' | 'mismatch' | 'failed'.
        """
        is_feed = self._is_tt_feed_after_pick(xml_after_pick, header_y_max)
        if not is_feed:
            # Non-feed unknown — нет signal recovery, fail с explicit error_code.
            self._fail(
                f'tt_post_switch_verify_unrecoverable: unknown header non-feed '
                f'(target={target!r})',
                step=label,
            )
            return 'failed'

        # Feed-after-pick — известное regression в новом TT UX.
        self.p.log_event(
            'warning', 'tt_post_switch_feed_after_pick',
            meta={'category': 'tt_post_switch_feed_after_pick',
                  'target': target, 'step': label,
                  'attempt': attempt + 1},
        )
        # Reuse Phase 1 bound-nav. Idempotent: no-op if уже на profile.
        self._navigate_to_profile_tab()
        xml_after_renav = self.p.dump_ui(retries=1) or ''
        self._save_dump(f'{label}_renav', xml_after_renav)
        status, current = self._post_switch_verify_handle(
            target, xml_after_renav, header_y_max=header_y_max,
        )
        if status == 'match':
            self.p.log_event(
                'account_switch', 'tt_post_switch_recovered_via_renav',
                meta={'category': 'tt_post_switch_recovered_via_renav',
                      'target': target, 'current': current,
                      'attempt': attempt + 1},
            )
            return 'recovered'
        if status == 'mismatch':
            # Caller продолжит в existing mismatch-handler retry loop.
            return 'mismatch'
        # status == 'unknown' — recovery не удался.
        self._fail(
            f'tt_post_switch_verify_unrecoverable: no profile after re-nav '
            f'(target={target!r})',
            step=f'{label}_renav',
        )
        return 'failed'
```

- [ ] **Step 5: Run tests, verify all 4 recovery tests green**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_post_switch_renav.py -v 2>&1 | tail -20
```

Expected: 9 PASSED (5 helper + 4 recovery).

- [ ] **Step 6: Wire helper в существующую `if status == 'unknown'` ветку TT switcher**

В `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` найти block 2275-2287 (текущее `if status == 'unknown':`):

```python
            if status == 'unknown':
                log.warning(
                    f'[switcher] TT post-switch verify UNKNOWN '
                    f'(header read failed) attempt={attempt + 1} — proceeding'
                )
                self.p.log_event(
                    'warning', 'tt_post_switch_handle_unknown',
                    meta={'category': 'tt_post_switch_handle_unknown',
                          'target': target,
                          'step': label,
                          'attempt': attempt + 1},
                )
                break
```

Заменить `break` (последнюю строку) на call recovery + dispatch на возврат:

```python
            if status == 'unknown':
                log.warning(
                    f'[switcher] TT post-switch verify UNKNOWN '
                    f'(header read failed) attempt={attempt + 1} — recovery'
                )
                self.p.log_event(
                    'warning', 'tt_post_switch_handle_unknown',
                    meta={'category': 'tt_post_switch_handle_unknown',
                          'target': target,
                          'step': label,
                          'attempt': attempt + 1},
                )
                outcome = self._tt_handle_post_switch_unknown(
                    target=target, xml_after_pick=xml_after_pick,
                    header_y_max=header_y_max, label=label, attempt=attempt,
                )
                if outcome == 'recovered':
                    break
                if outcome == 'failed':
                    return False
                # outcome == 'mismatch' — continue в existing mismatch handler
                # ниже (line 2289+), update current to renav-current?
                # Note: existing mismatch handler reads `current` from the SAME
                # scope — for falls-through correctness, we need to update
                # `current` after recovery. Implementation detail: пересохранить
                # current через nonlocal или вернуть из recovery вместе с status.
                # Simplest: повторить _post_switch_verify_handle на свежий dump
                # в mismatch-path. Уже сейчас этот path делает retry через
                # _find_and_tap_account loop.
                # Поскольку наш recovery emit'нул event, и outcome=mismatch
                # значит re-verify дал mismatch ≡ existing handler работает.
                pass  # fall through to mismatch handler
```

Note: outcome=`'mismatch'` означает что после navigate мы РЕАЛЬНО на чужом профиле. Существующий mismatch-handler ниже (line 2289+) сделает retry pick через `MAX_PICK_ATTEMPTS`. Variable `current` для mismatch-handler нужен — но он перезаписывается на следующей итерации через `xml_after_pick = self.p.dump_ui()` и второй `_post_switch_verify_handle(...)` (или handler сразу делает retry pick без чтения current).

ПРОВЕРКА на этом шаге (если есть concern о scope): прочитать lines 2289-2330 (mismatch handler), убедиться что `current` берётся из локальной переменной (не нужно update после recovery).

- [ ] **Step 7: Run full file's test suite (no regression in adjacent tests)**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_post_switch_renav.py tests/test_account_switcher_tt.py -v 2>&1 | tail -25
```

Expected: 9 new + N existing PASS.

- [ ] **Step 8: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add tests/test_post_switch_renav.py account_switcher.py
git commit -m "feat(switcher): TT post-switch verify recovery (feed-detect + renav)"
```

---

## Task 4: `publisher_kernel.py` step→category mapping

**Tree:** deploy
**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_kernel.py`
- Modify: `/root/.openclaw/workspace-genri/autowarm/tests/test_post_switch_renav.py` (append 1 test)

> **Why:** Чтобы `_fail(... step=label_or_renav)` финализировался в `error_code='tt_post_switch_verify_unrecoverable'` (видимо в publish_tasks.error_code), нужен mapping в `_SWITCHER_STEP_TO_CATEGORY`.

- [ ] **Step 1: Read current mapping for context**

```bash
grep -n "_SWITCHER_STEP_TO_CATEGORY\|tt_4_target_profile\|tt_post_switch" /root/.openclaw/workspace-genri/autowarm/publisher_kernel.py | head -20
```

Идентифицировать: какой формат entries, есть ли уже `tt_4_target_profile` mapping, и куда добавлять.

- [ ] **Step 2: Write test (red)**

В конец `/root/.openclaw/workspace-genri/autowarm/tests/test_post_switch_renav.py`:

```python
# ─── publisher_kernel.py step→category mapping ──────────────────────────────


def test_publisher_kernel_tt_4_target_profile_mapped():
    """`tt_4_target_profile` step резолвится в tt_post_switch_verify_unrecoverable."""
    from publisher_kernel import _SWITCHER_STEP_TO_CATEGORY  # noqa: E402
    assert _SWITCHER_STEP_TO_CATEGORY.get('tt_4_target_profile') == \
        'tt_post_switch_verify_unrecoverable'


def test_publisher_kernel_tt_4_target_profile_renav_mapped():
    """`tt_4_target_profile_renav` (post-recovery fail step) тоже резолвится."""
    from publisher_kernel import _SWITCHER_STEP_TO_CATEGORY  # noqa: E402
    assert _SWITCHER_STEP_TO_CATEGORY.get('tt_4_target_profile_renav') == \
        'tt_post_switch_verify_unrecoverable'
```

Run:

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_post_switch_renav.py::test_publisher_kernel_tt_4_target_profile_mapped tests/test_post_switch_renav.py::test_publisher_kernel_tt_4_target_profile_renav_mapped -v 2>&1 | tail -10
```

Expected: 2 FAILED (mapping не существует).

- [ ] **Step 3: Add mapping**

В `/root/.openclaw/workspace-genri/autowarm/publisher_kernel.py`, рядом с другими `tt_*` entries:

```python
    # [tt_post_switch_renav 2026-05-11] Recovery в _post_switch_verify_handle
    # после pick→feed regression. См. spec
    # docs/superpowers/specs/2026-05-11-tt-post-switch-verify-recovery-design.md
    'tt_4_target_profile': 'tt_post_switch_verify_unrecoverable',
    'tt_4_target_profile_renav': 'tt_post_switch_verify_unrecoverable',
```

> Note: если в текущем dict уже есть key `tt_4_target_profile` с другим значением (НЕ должно быть, see Task 1 Step 3), STOP — обновить spec / план перед перезаписью.

- [ ] **Step 4: Run tests, verify green**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_post_switch_renav.py -v 2>&1 | tail -15
```

Expected: 11 PASSED (5 helper + 4 recovery + 2 mapping).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add tests/test_post_switch_renav.py publisher_kernel.py
git commit -m "feat(kernel): map tt_4_target_profile* → tt_post_switch_verify_unrecoverable"
```

---

## Task 5: Full suite + lint + final pre-PR checks

**Tree:** deploy

- [ ] **Step 1: Run full account_switcher test suite**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/test_account_switcher_tt.py tests/test_post_switch_renav.py -v 2>&1 | tail -30
```

Expected: all PASS, no new failures vs baseline (Task 1 Step 2).

- [ ] **Step 2: Run broader publisher test suite**

```bash
cd /root/.openclaw/workspace-genri/autowarm
pytest tests/ -v -k 'switcher or publisher_tiktok or post_switch' 2>&1 | tail -30
```

Expected: всё, что было green, остаётся green.

- [ ] **Step 3: Smoke import check**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import account_switcher, publisher_kernel; print('OK')"
```

Expected: `OK` (никаких ImportError / SyntaxError).

- [ ] **Step 4: Review diff before push**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git log --oneline main..HEAD
git diff main...HEAD --stat
```

Expected: 3 commits (Task 2, Task 3, Task 4), ≤200 lines added (helper + recovery + mapping + tests).

---

## Task 6: PR + Codex review round

**Tree:** deploy

> **Why:** Per memory `feedback_codex_review_specs.md` — все code-changes идут через Codex review до 0 P1 перед user review.

- [ ] **Step 1: Push branch to remote**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git push -u origin fix/tt-post-switch-renav-20260511
```

Expected: branch pushed (auto-push hook НЕ сработает на feature branch — он только для main).

- [ ] **Step 2: Codex review uncommitted diff (full PR diff vs main)**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git diff main...HEAD | ~/.local/bin/codex review -
```

Expected: review output. Если any P1 → STOP, apply fix, commit `fix(...): apply Codex round N` (новый commit на ветке), re-run Codex round N+1. Loop until 0 P1.

Если P2/P3 → собрать в один commit `fix(...): apply Codex round 1 (M P2 + K P3)` и apply.

- [ ] **Step 3: Create PR via gh CLI**

После 0 P1 round'а:

```bash
cd /root/.openclaw/workspace-genri/autowarm
source ~/secrets/github-gengo2.env  # GenGo2 token
gh pr create --repo GenGo2/delivery-contenthunter \
  --base main \
  --head fix/tt-post-switch-renav-20260511 \
  --title "TT post-switch verify recovery (renav + tt_post_switch_verify_unrecoverable)" \
  --body "$(cat <<'EOF'
## Summary
- Закрывает silent `tt_post_switch_handle_unknown` regression (21/36h на момент discovery 2026-05-11).
- Approach A: feed-detect в TT-caller → `_navigate_to_profile_tab` (Phase 1) → re-verify → `match`/`mismatch`/`fail`.
- Новый error_code `tt_post_switch_verify_unrecoverable` для visibility вместо degrade-to-pass.

## Spec & evidence
- Spec: `docs/superpowers/specs/2026-05-11-tt-post-switch-verify-recovery-design.md` (commit 020bce7, Codex CLEAN после 1 round)
- Evidence: pt 4691 + pt 4451 UI dumps подтверждают TT feed-top-bar после bottomsheet-pick

## Tests
- 5 helper tests (`_is_tt_feed_after_pick`) — distinct markers через set
- 4 recovery integration tests (mock verify + navigate) — match/unknown/mismatch/non-feed
- 2 mapping tests (`publisher_kernel.py` step→category)

## Test plan
- [x] Все тесты зелёные локально
- [x] Codex review: 0 P1
- [ ] Post-merge smoke: ≥1 `tt_post_switch_recovered_via_renav` event за 24h в проде (см. spec Success metrics)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL returned. Записать для evidence-doc.

---

## Task 7: Post-merge evidence + memory update

**Tree:** working (`/home/claude-user/contenthunter/`)

> **Why:** После merge auto-push hook deploys в prod autowarm + PM2 restart. Нужна evidence-doc + memory note.

- [ ] **Step 1: Wait for PR merge (user action / passing CI)**

Не auto-merge — пользователь сам решает.

- [ ] **Step 2: Verify deploy reached prod autowarm**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin
git log -1 origin/main --oneline  # должен быть PR merge commit
sudo -u root pm2 jlist | python3 -c "import json,sys; [print(p['name'], 'restart', p.get('pm2_env',{}).get('restart_time',0)) for p in json.load(sys.stdin) if p['name']=='autowarm']"
```

Expected: prod на merge commit, PM2 restart counter incremented (post-commit hook auto-restarts).

- [ ] **Step 3: Initial 1h smoke check**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT
  (e->'meta'->>'category') AS category,
  COUNT(*) cnt,
  COUNT(DISTINCT pt.id) tasks
FROM publish_tasks pt, jsonb_array_elements(pt.events) e
WHERE pt.platform='TikTok'
  AND pt.created_at > NOW() - INTERVAL '2 hours'
  AND e->'meta'->>'category' LIKE 'tt_post_switch%'
GROUP BY category
ORDER BY cnt DESC;
"
```

Expected (1-2h после merge): какой-то pattern из `tt_post_switch_feed_after_pick` (если TT тыкает feed) + либо `tt_post_switch_recovered_via_renav` (recovery работает) либо `tt_post_switch_verify_unrecoverable` (recovery не справляется).

- [ ] **Step 4: Write evidence doc**

Создать `/home/claude-user/contenthunter/docs/evidence/2026-05-11-tt-post-switch-renav-shipped.md`:

```markdown
# TT post-switch verify recovery — Shipped <DATE>

**PR:** <PR_URL>
**Merge commit:** <SHA> (squash; branch fix/tt-post-switch-renav-20260511 deleted)
**Prod state:** /root/.openclaw/workspace-genri/autowarm @ <SHA>; PM2 autowarm restart <N>
**Spec:** docs/superpowers/specs/2026-05-11-tt-post-switch-verify-recovery-design.md (v2, Codex CLEAN)
**Plan:** docs/superpowers/plans/2026-05-11-tt-post-switch-verify-recovery-plan.md (v1)

## Context
[Same root-cause summary as spec]

## Shipped
- `_is_tt_feed_after_pick` helper + `_TT_FEED_MARKERS` constant
- `_tt_handle_post_switch_unknown` recovery method
- Wire в TT switcher unknown-branch (`account_switcher.py` ~line 2275)
- `publisher_kernel.py` mapping (2 entries)
- 11 unit tests (5 helper + 4 recovery + 2 mapping)
- N commits на ветке, Codex CLEAN после <N> rounds

## Initial 1-2h smoke
[Categories breakdown, counts, observations]

## Success metrics tracking (24h)
- [ ] ≥1 `tt_post_switch_recovered_via_renav` event
- [ ] `tt_post_switch_verify_unrecoverable` baseline measured
- [ ] TT `done` count за 24h vs baseline (1/7d)
```

Commit:

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/2026-05-11-tt-post-switch-renav-shipped.md
git commit -m "docs(evidence): TT post-switch renav shipped <DATE>"
```

- [ ] **Step 5: Update memory**

Создать `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_tt_post_switch_renav_shipped.md`:

```markdown
---
name: TT post-switch verify recovery — shipped <DATE>
description: pick→feed regression закрыт через feed-detect + navigate_to_profile + re-verify
type: project
---

## Context
2026-05-11 discovery: TikTok после bottomsheet-pick стал открывать feed (Смотреть/Подписки/Рекомендации), а не profile. `_post_switch_verify_handle` возвращал unknown → silent degrade-to-pass → publish blind. 21 hit /36h.

## Shipped
- Approach A: recovery в TT-caller (account_switcher.py ~line 2275)
- Helper `_is_tt_feed_after_pick` (distinct markers через set, threshold ≥2/3)
- `_tt_handle_post_switch_unknown` dispatcher (recovered/mismatch/failed)
- Reuse `_navigate_to_profile_tab` (Phase 1)
- Новый error_code `tt_post_switch_verify_unrecoverable`
- PR <PR_URL>, merged <DATE>

## How to apply
Если жалобы на TT publishing fails:
1. error_code='tt_post_switch_verify_unrecoverable' → recovery не справился, копать non-feed UI или Phase 1 navigate
2. error_code='tt_upload_confirmation_timeout' БЕЗ `tt_post_switch_recovered_via_renav` event → publish failure ниже по pipeline (music-rights RC-B или Phase 1.5 audio-dialog regression)
```

В `MEMORY.md` добавить новую строку (под TT-related группой):

```
- [TT post-switch renav shipped](project_tt_post_switch_renav_shipped.md) — pick→feed regression закрыт PR <#>
```

---

## Definition of Done

- 5 helper tests + 4 recovery tests + 2 mapping tests — 11 PASSED
- Codex review CLEAN (0 P1) на full PR diff
- PR merged, prod autowarm на новой sha
- Evidence doc committed в `/home/claude-user/contenthunter`
- Memory entry created + indexed
- 1-2h initial smoke shows expected event categories
- 24h success metric: ≥1 `tt_post_switch_recovered_via_renav` (deferred, документировать в evidence-doc)

## Backlog (после shipped)

- IG / YT same pattern check — если когда-то pick→non-profile появится на IG/YT, Approach A generalized в Approach B candidate.
- Phase 2 canary с включённым recovery — но это уже legacy; canary path не активирован в текущей итерации.
- RC-B (60% music-rights post-accept timeout) — independent от этого фикса, ждёт XML evidence от `TT_DUMP_POST_MUSIC_RIGHTS_XML` (активирован сегодня).
