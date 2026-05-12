# YT cross-project leak — Implementation Plan v1

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) или superpowers:executing-plans. Tasks tracked through `- [ ]` checkboxes.

**Goal:** Port IG cross-project leak defense (PR #36 Layer A + RC-8 D2/D3 fail-fast + Layer C dump) в `publisher_youtube.py` picker, переиспользуя shared helpers, без regressions в IG path.

**Architecture (Approach A из spec, Codex CLEAN):**
- Standalone helper `layer_a_pre_tap_verify(publisher_self, candidate_desc, *, event_category, artifact_prefix) -> bool` в `publisher_helpers.py`.
- IG переходит на shared helper (regression-guarded test).
- YT picker получает Layer A verify + Layer C dump + удаляет `items = video_items or all_items` + `(181,600)` blind fallback → fail-fast `yt_gallery_no_video_candidate`.

**Decisions (resolved Codex open questions от spec round 3):**
1. Standalone function (Approach A.2), не mixin — меньше связности.
2. Event category `yt_picker_wrong_candidate` (зеркалит `ig_picker_wrong_candidate`).
3. Artifact prefix `yt_picker_wrong_candidate_date` / `yt_picker_wrong_mediastore_top` (зеркалит IG).
4. Immediate fail-fast на blind paths — без транзитной warning-only phase.
5. Mirror IG `try/except Exception: pass` для `_save_debug_artifacts`.

**Tech stack:** Python 3.11, pytest, MagicMock/patch.object. Live ADB не требуется для unit/integration тестов.

**Path conventions:**
- **Spec & plan & evidence:** `/home/claude-user/contenthunter/.claude/worktrees/yt-stab-20260512/` (docs branch `yt-stab-20260512`).
- **Deploy tree (code + tests):** `/root/.openclaw/workspace-genri/autowarm/`.
- **Branch:** `feat-yt-cross-project-leak-fix-20260512` (autowarm tree, уже создана).
- **NO --force-push** в любых видах (memory: `feedback_subagent_force_push_risk`).

**Spec:** `docs/superpowers/specs/2026-05-12-yt-cross-project-leak-fix-design.md` (v1, Codex CLEAN после round 3).

---

## Task 1: Branch baseline + sanity

**Tree:** deploy (`/root/.openclaw/workspace-genri/autowarm/`)

- [ ] **Step 1.1:** Confirm branch exists and on it
  ```bash
  cd /root/.openclaw/workspace-genri/autowarm
  git rev-parse --abbrev-ref HEAD  # → feat-yt-cross-project-leak-fix-20260512
  git log -1 --oneline             # → starting commit (should be at or near main HEAD)
  ```
- [ ] **Step 1.2:** Baseline test suite green
  ```bash
  pytest tests/ -x -q 2>&1 | tail -20
  ```
  Expected: all PASS. Pre-existing fails — записать в evidence, не наша регрессия.
- [ ] **Step 1.3:** Confirm key symbols exist
  ```bash
  grep -n "def _layer_a_pre_tap_verify_ok\|_ig_parse_thumbnail_date\|_IG_THUMBNAIL_DATE_RE\|_RUSSIAN_MONTHS\|_MSK" publisher_instagram.py | head -10
  grep -n "self._last_push_ts\|self._last_expected_basename\|def _ms_query" publisher_base.py | head -10
  grep -n "items = video_items or all_items\|adb_tap(181, 600)" publisher_youtube.py
  ```
  Expected: all matches present (per spec evidence). Missing → STOP, update spec.

---

## Task 2: Extract helpers into `publisher_helpers.py`

**Tree:** deploy

- [ ] **Step 2.1:** Read source of truth (IG)
  ```bash
  sed -n '110,160p' publisher_instagram.py   # constants + _ig_parse_thumbnail_date
  sed -n '261,340p' publisher_instagram.py   # _layer_a_pre_tap_verify_ok body
  ```
  Capture exact body for verbatim port.

- [ ] **Step 2.2:** Add to `publisher_helpers.py`:
  ```python
  # === Picker thumbnail date parsing — shared by IG + YT publishers =============
  from zoneinfo import ZoneInfo
  from datetime import datetime
  import re

  RUSSIAN_MONTHS = {'января':1,'февраля':2,'марта':3,'апреля':4,'мая':5,'июня':6,
                    'июля':7,'августа':8,'сентября':9,'октября':10,'ноября':11,'декабря':12}
  MSK = ZoneInfo('Europe/Moscow')
  # IG-format regex with NBSP-or-space tolerance; matches "12 мая 2026 г. 14:51"
  THUMBNAIL_DATE_RE = re.compile(
      r'(\d{1,2})\s+([а-яА-Я]+)\s+(\d{4})[\s\xa0]*г?\.?\s+(\d{1,2}):(\d{2})'
  )

  def parse_picker_thumbnail_date(desc):
      """Parse picker thumbnail content-desc into tz-aware MSK datetime.

      Same format as IG (system gallery) — captures "12 мая 2026 г. 14:51"
      with NBSP-or-space separator. Returns None on any parse error.
      """
      if not desc: return None
      try:
          m = THUMBNAIL_DATE_RE.search(desc)
          if not m: return None
          day, month_ru, year, hour, minute = m.groups()
          month = RUSSIAN_MONTHS.get(month_ru.lower())
          if month is None: return None
          return datetime(int(year), month, int(day), int(hour), int(minute), tzinfo=MSK)
      except Exception:
          return None


  def layer_a_pre_tap_verify(publisher, candidate_desc, *, event_category, artifact_prefix):
      """Cross-project leak defense before tapping a gallery candidate.

      Two independent checks (both soft-fail when ground truth missing):
      1. Date: thumbnail date vs publisher._last_push_ts ± 60s.
      2. MediaStore: top-1 video _display_name == publisher._last_expected_basename.

      On hard-fail logs error event (event_category, reason='date_mismatch' or
      'mediastore_top_mismatch') + saves debug artifact (artifact_prefix_date /
      artifact_prefix_mediastore_top). Returns False to caller, which then
      propagates as publish abort.
      """
      # Check 1 — date
      thumb_dt = parse_picker_thumbnail_date(candidate_desc)
      push_dt = getattr(publisher, '_last_push_ts', None)
      if thumb_dt is not None and push_dt is not None:
          try: delta_s = abs((thumb_dt - push_dt).total_seconds())
          except Exception: delta_s = None
          if delta_s is not None and delta_s > 60:
              publisher.log_event(
                  'error',
                  f'picker candidate дата thumbnail={thumb_dt.isoformat()} '
                  f'расходится с push={push_dt.isoformat()} на {delta_s:.0f}s — abort',
                  meta={'category': event_category,
                        'reason': 'date_mismatch',
                        'thumb_date': thumb_dt.isoformat(),
                        'push_date': push_dt.isoformat(),
                        'delta_s': round(delta_s, 1),
                        'platform': publisher.platform})
              try: publisher._save_debug_artifacts(f'{artifact_prefix}_date')
              except Exception: pass
              return False

      # Check 2 — MediaStore top-1
      expected = getattr(publisher, '_last_expected_basename', None)
      if expected:
          try: top_name, _ts, ok = publisher._ms_query('content://media/external/video/media')
          except Exception: top_name, ok = '', False
          if ok and top_name and top_name != expected:
              publisher.log_event(
                  'error',
                  f'MediaStore top-1={top_name!r} ≠ expected={expected!r} — abort',
                  meta={'category': event_category,
                        'reason': 'mediastore_top_mismatch',
                        'top_name': top_name,
                        'expected_basename': expected,
                        'platform': publisher.platform})
              try: publisher._save_debug_artifacts(f'{artifact_prefix}_mediastore_top')
              except Exception: pass
              return False
      return True
  ```

- [ ] **Step 2.3:** Smoke import
  ```bash
  python3 -c "from publisher_helpers import parse_picker_thumbnail_date, layer_a_pre_tap_verify; print('ok')"
  ```

---

## Task 3: Re-wire IG to shared helper (regression-guarded)

**Tree:** deploy

- [ ] **Step 3.1:** В `publisher_instagram.py`:
  - **Удалить** module-level `_RUSSIAN_MONTHS`, `_MSK`, `_IG_THUMBNAIL_DATE_RE`, `_ig_parse_thumbnail_date` (lines ~110-156).
  - **Заменить body** `_layer_a_pre_tap_verify_ok` (line 261-337) на:
    ```python
    def _layer_a_pre_tap_verify_ok(self, candidate_desc: str) -> bool:
        """Cross-project leak defense before tapping IG gallery candidate."""
        from publisher_helpers import layer_a_pre_tap_verify
        return layer_a_pre_tap_verify(
            self, candidate_desc,
            event_category='ig_picker_wrong_candidate',
            artifact_prefix='ig_picker_wrong_candidate',
        )
    ```
  - Удалить unused imports (`datetime`, `re`, `ZoneInfo`) если они больше не используются в module (но скорее всего ещё нужны). Verify через `grep` ДО удаления.

- [ ] **Step 3.2:** Smoke: импорт + класс инстанцируется
  ```bash
  python3 -c "from publisher_instagram import PublisherInstagram; print('ok')"
  ```

- [ ] **Step 3.3:** Run IG-related test suite (regression guard)
  ```bash
  pytest tests/test_publisher_instagram.py -v 2>&1 | tail -20
  pytest tests/ -k "ig_picker or layer_a or cross_project" -v 2>&1 | tail -20
  ```
  Expected: all PASS — refactor preserves behaviour.

- [ ] **Step 3.4:** STOP-gate
  Если любой IG-test упал → STOP, fix in-place; не продолжать к YT.

---

## Task 4: Unit tests for `publisher_helpers` Layer A

**Tree:** deploy. **New test file:** `tests/test_publisher_helpers_layer_a.py`

- [ ] **Step 4.1:** Test `parse_picker_thumbnail_date`
  ```python
  from datetime import datetime
  from zoneinfo import ZoneInfo
  from publisher_helpers import parse_picker_thumbnail_date, MSK

  def test_parse_nbsp():
      d = parse_picker_thumbnail_date('Миниатюра видео создано 12 мая 2026\xa0г. 14:51')
      assert d == datetime(2026, 5, 12, 14, 51, tzinfo=MSK)

  def test_parse_space():
      d = parse_picker_thumbnail_date('создано 12 мая 2026 г. 14:51')
      assert d == datetime(2026, 5, 12, 14, 51, tzinfo=MSK)

  def test_parse_no_year_separator():
      # с/без точки после "г"
      d = parse_picker_thumbnail_date('12 января 2026 09:00')
      assert d == datetime(2026, 1, 12, 9, 0, tzinfo=MSK)

  def test_parse_none(): assert parse_picker_thumbnail_date(None) is None
  def test_parse_empty(): assert parse_picker_thumbnail_date('') is None
  def test_parse_no_date(): assert parse_picker_thumbnail_date('просто текст без даты') is None
  def test_parse_bad_month(): assert parse_picker_thumbnail_date('12 fakemonth 2026 г. 14:51') is None
  ```

- [ ] **Step 4.2:** Test `layer_a_pre_tap_verify` — pure logic
  ```python
  from unittest.mock import MagicMock
  from datetime import datetime, timedelta
  from publisher_helpers import layer_a_pre_tap_verify, MSK

  def _make_pub(push_ts=None, expected=None, ms_top=None, ms_ok=True):
      pub = MagicMock()
      pub.platform = 'youtube'
      pub._last_push_ts = push_ts
      pub._last_expected_basename = expected
      pub._ms_query = MagicMock(return_value=(ms_top, None, ms_ok))
      pub.log_event = MagicMock()
      pub._save_debug_artifacts = MagicMock()
      return pub

  def test_layer_a_date_within_60s():
      ts = datetime(2026, 5, 12, 14, 51, tzinfo=MSK)
      pub = _make_pub(push_ts=ts)
      ok = layer_a_pre_tap_verify(pub, 'создано 12 мая 2026 г. 14:51',
                                   event_category='yt_picker_wrong_candidate',
                                   artifact_prefix='yt_picker_wrong_candidate')
      assert ok is True
      pub.log_event.assert_not_called()

  def test_layer_a_date_mismatch_2min():
      push = datetime(2026, 5, 12, 14, 51, tzinfo=MSK)
      pub = _make_pub(push_ts=push)
      ok = layer_a_pre_tap_verify(pub, 'создано 12 мая 2026 г. 14:53',  # +2min
                                   event_category='yt_picker_wrong_candidate',
                                   artifact_prefix='yt_picker_wrong_candidate')
      assert ok is False
      pub.log_event.assert_called_once()
      args = pub.log_event.call_args
      assert args[1]['meta']['category'] == 'yt_picker_wrong_candidate'
      assert args[1]['meta']['reason'] == 'date_mismatch'
      pub._save_debug_artifacts.assert_called_with('yt_picker_wrong_candidate_date')

  def test_layer_a_softfail_no_push_ts():
      pub = _make_pub(push_ts=None)
      ok = layer_a_pre_tap_verify(pub, 'создано 12 мая 2026 г. 14:55',
                                   event_category='yt_picker_wrong_candidate',
                                   artifact_prefix='yt_picker_wrong_candidate')
      assert ok is True  # soft-fail: no ground truth

  def test_layer_a_ms_mismatch():
      pub = _make_pub(expected='autowarm_pq_123.mp4', ms_top='foreign.mp4', ms_ok=True)
      ok = layer_a_pre_tap_verify(pub, 'irrelevant desc',
                                   event_category='yt_picker_wrong_candidate',
                                   artifact_prefix='yt_picker_wrong_candidate')
      assert ok is False
      args = pub.log_event.call_args
      assert args[1]['meta']['reason'] == 'mediastore_top_mismatch'
      pub._save_debug_artifacts.assert_called_with('yt_picker_wrong_candidate_mediastore_top')

  def test_layer_a_ms_match():
      pub = _make_pub(expected='autowarm_pq_123.mp4', ms_top='autowarm_pq_123.mp4', ms_ok=True)
      ok = layer_a_pre_tap_verify(pub, 'no date',
                                   event_category='yt_picker_wrong_candidate',
                                   artifact_prefix='yt_picker_wrong_candidate')
      assert ok is True

  def test_layer_a_softfail_no_expected():
      pub = _make_pub(expected=None, ms_top='foreign.mp4', ms_ok=True)
      ok = layer_a_pre_tap_verify(pub, 'no date',
                                   event_category='yt_picker_wrong_candidate',
                                   artifact_prefix='yt_picker_wrong_candidate')
      assert ok is True  # MediaStore check skipped without expected_basename

  def test_layer_a_ms_query_fails():
      pub = _make_pub(expected='autowarm_pq_123.mp4', ms_top='', ms_ok=False)
      ok = layer_a_pre_tap_verify(pub, 'no date',
                                   event_category='yt_picker_wrong_candidate',
                                   artifact_prefix='yt_picker_wrong_candidate')
      # _ms_query returned ok=False → check 2 soft-fails too
      assert ok is True

  def test_layer_a_ig_category():
      """Verify event_category param routes correctly."""
      push = datetime(2026, 5, 12, 14, 51, tzinfo=MSK)
      pub = _make_pub(push_ts=push)
      ok = layer_a_pre_tap_verify(pub, 'создано 12 мая 2026 г. 14:55',
                                   event_category='ig_picker_wrong_candidate',
                                   artifact_prefix='ig_picker_wrong_candidate')
      assert ok is False
      assert pub.log_event.call_args[1]['meta']['category'] == 'ig_picker_wrong_candidate'
      pub._save_debug_artifacts.assert_called_with('ig_picker_wrong_candidate_date')
  ```

- [ ] **Step 4.3:** Run new tests
  ```bash
  pytest tests/test_publisher_helpers_layer_a.py -v 2>&1 | tail -25
  ```
  All PASS expected.

---

## Task 5: Patch `publisher_youtube.py` — Layer A + Layer C + remove blind paths

**Tree:** deploy

- [ ] **Step 5.1:** Add import at top
  ```python
  from publisher_helpers import layer_a_pre_tap_verify
  ```

- [ ] **Step 5.2:** Replace line 1326 fallback
  ```diff
  - items = video_items or all_items
  + items = video_items
  ```

- [ ] **Step 5.3:** Insert Layer A + Layer C перед `self.adb_tap(cx, cy)` (около line 1334-1336):
  ```python
                  _, _, _, _, cx, cy, d = content_items[0]
                  log.info(f'  Тапаем первое видео ({cx},{cy}): {d[:60]}')
                  # === Layer A — pre-tap verify «candidate == our push» ===
                  if not layer_a_pre_tap_verify(
                          self, d,
                          event_category='yt_picker_wrong_candidate',
                          artifact_prefix='yt_picker_wrong_candidate'):
                      return False
                  # === Layer C — diagnostic dump перед tap'ом ===
                  try: self._save_debug_artifacts('yt_picker_pre_tap')
                  except Exception: pass
                  self.adb_tap(cx, cy)
                  video_selected = True; time.sleep(4)
                  break
  ```

- [ ] **Step 5.4:** Replace blind `(181, 600)` fallback (line 1343-1345) с fail-fast:
  ```python
  if not video_selected:
      log.error('YouTube: видео не найдено в gallery picker — abort')
      try: self._save_debug_artifacts('yt_gallery_no_video')
      except Exception: pass
      diag = [{'cx': it[4], 'cy': it[5], 'desc': it[6][:120]}
              for it in (all_items or [])[:10]]
      self.log_event(
          'error',
          'YT: видео не найдено в gallery picker — fail-fast',
          meta={'category': 'yt_gallery_no_video_candidate',
                'platform': self.platform,
                'step': 'yt_gallery_select',
                'all_clickable_count': len(all_items or []),
                'first_clickables': diag},
      )
      return False
  ```
  > **Note:** `all_items` определён внутри for-loop. Если parse-attempts ни разу не успели наполнить, `all_items` будет undefined — wrap в `all_items if 'all_items' in dir() else []` или init `all_items=[]` перед циклом. Решение: init `all_items=[]` ВНЕ цикла, then accumulate.

- [ ] **Step 5.5:** Init `all_items=[]` перед `for parse_attempt in range(4)` (line 1303) — фикс scope:
  ```diff
  +       all_items = []
          for parse_attempt in range(4):
              ...
              try:
  -               video_items, all_items = [], []
  +               video_items = []
                  for node in root_el.iter('node'):
                      ...
  ```
  
  Но это меняет accumulating-vs-resetting per-attempt. Для diag не критично — но безопаснее сохранить per-attempt logic и init `last_all_items = []` отдельно:
  ```diff
  +       last_all_items = []
          for parse_attempt in range(4):
              try:
                  video_items, all_items = [], []
                  ...
  +               last_all_items = all_items
  ```
  И в fail-fast блоке использовать `last_all_items`.

- [ ] **Step 5.6:** Smoke
  ```bash
  python3 -c "from publisher_youtube import PublisherYouTube; print('ok')"
  grep -n "adb_tap(181, 600)\|items = video_items or all_items" publisher_youtube.py
  # Expected: пусто (паттерны удалены)
  grep -n "layer_a_pre_tap_verify\|yt_picker_pre_tap\|yt_gallery_no_video_candidate" publisher_youtube.py
  # Expected: 3+ matches
  ```

---

## Task 6: Integration tests for YT picker

**Tree:** deploy. **New test file:** `tests/test_publisher_youtube_picker.py`

- [ ] **Step 6.1:** Fixture XML — video gallery with 3 candidates
  ```python
  YT_PICKER_XML_3_VIDEOS = '''<hierarchy>
  <node bounds="[10,300][350,600]" clickable="true" content-desc="Видео, 0:15, создано 12 мая 2026 г. 14:51"/>
  <node bounds="[360,300][700,600]" clickable="true" content-desc="Видео, 0:20, создано 11 мая 2026 г. 18:00"/>
  <node bounds="[710,300][1050,600]" clickable="true" content-desc="Видео, 0:10, создано 10 мая 2026 г. 09:00"/>
  </hierarchy>'''

  YT_PICKER_XML_NO_VIDEOS = '''<hierarchy>
  <node bounds="[10,300][350,600]" clickable="true" content-desc="Фото, 5 МБ"/>
  <node bounds="[10,1700][350,1900]" clickable="true" content-desc="Кнопка"/>
  </hierarchy>'''
  ```

- [ ] **Step 6.2:** Helper to construct minimal YT publisher for testing
  ```python
  def _make_yt_publisher(*, push_ts=None, expected_basename=None, ms_top=None):
      pub = MagicMock(spec=PublisherYouTube)
      pub.platform = 'youtube'
      pub.account = 'test_acc'
      pub.media_type = 'video'
      pub._last_push_ts = push_ts
      pub._last_expected_basename = expected_basename
      pub._ms_query = MagicMock(return_value=(ms_top, None, True))
      pub.log_event = MagicMock()
      pub.adb_tap = MagicMock()
      pub._save_debug_artifacts = MagicMock()
      pub.dump_ui = MagicMock()
      pub.dismiss_location_dialog = MagicMock(return_value=False)
      pub.tap_element = MagicMock(return_value=False)
      # bind real method
      from publisher_youtube import PublisherYouTube as _RY
      pub._select_gallery_video = _RY._select_gallery_video.__get__(pub)  # if extracted; else test через full path
      return pub
  ```
  > **Note:** В YT публишере gallery picker — это inline блок в большом `publish()` методе. Для testability желательно extract в `_select_gallery_video(self, remote_media_path) -> bool`. Это **refactor** (Task 5.x подзадача), оборачивает существующий код без изменения behaviour. Spec'и не требовали — но без extract тесты получаются heavy (mock всего publish flow). Решение: extract как часть Task 5.

- [ ] **Step 6.3:** Extract `_select_gallery_video` (refactor, behaviour identical)
  - Lines 1298-1346 → method `_select_gallery_video(self, remote_media_path: str) -> bool`.
  - Replace inline code в `publish()` с `if not self._select_gallery_video(remote_media_path): return False`.
  - Smoke: existing YT-tests pass.

- [ ] **Step 6.4:** Tests for `_select_gallery_video`:
  1. `test_yt_picker_taps_first_video_when_layer_a_passes`: push_ts соответствует thumbnail dt → adb_tap(180, 450) called (центр первого fixture).
  2. `test_yt_picker_aborts_on_date_mismatch`: push_ts 14:51, thumbnail "14:55" (5min off на втором кандидате — но первый = 14:51, match → tap). Усложнить fixture: первый кандидат 14:55, push_ts 14:51 → abort.
  3. `test_yt_picker_aborts_on_mediastore_mismatch`: expected_basename='autowarm.mp4', ms_query returns 'foreign.mp4' → abort с reason='mediastore_top_mismatch'.
  4. `test_yt_picker_no_videos_fails_fast`: fixture `YT_PICKER_XML_NO_VIDEOS` → `yt_gallery_no_video_candidate` event, return False, **adb_tap НЕ вызвано**.
  5. `test_yt_picker_no_blind_181_600`: grep на исходник — `assert 'adb_tap(181, 600)' not in open('publisher_youtube.py').read()`.
  6. `test_yt_picker_dumps_artifact_on_success`: success path → `_save_debug_artifacts('yt_picker_pre_tap')` called.
  7. `test_yt_picker_dumps_artifact_on_fail_fast`: no-videos path → `_save_debug_artifacts('yt_gallery_no_video')` called.

- [ ] **Step 6.5:** Run new tests
  ```bash
  pytest tests/test_publisher_youtube_picker.py -v 2>&1 | tail -30
  ```

---

## Task 7: Full suite green

**Tree:** deploy

- [ ] **Step 7.1:**
  ```bash
  pytest tests/ -x -q 2>&1 | tail -10
  ```
  Expected: all PASS (включая Task 4 + Task 6 newcomers + Task 3 regression).
- [ ] **Step 7.2:** Если что-то pre-existing fail и не наш — записать в evidence как known. Не править здесь.

---

## Task 8: Commit + push branch

**Tree:** deploy

- [ ] **Step 8.1:** Stage:
  ```bash
  git add publisher_helpers.py publisher_instagram.py publisher_youtube.py \
          tests/test_publisher_helpers_layer_a.py tests/test_publisher_youtube_picker.py
  git status --short
  ```
- [ ] **Step 8.2:** Single commit:
  ```bash
  git commit -m "$(cat <<'EOF'
  fix(yt-publisher): cross-project leak defense — Layer A + remove blind paths

  Port IG PR #36 protections to YouTube gallery picker:
  - Extract _ig_parse_thumbnail_date + _layer_a_pre_tap_verify_ok logic to
    publisher_helpers.layer_a_pre_tap_verify (standalone, accepts publisher_self).
  - Re-wire publisher_instagram to call shared helper (regression-guarded).
  - Add Layer A verify (date ±60s + MediaStore top-1 basename match) before
    YT picker adb_tap; soft-fail when ground truth missing, abort with
    yt_picker_wrong_candidate on mismatch.
  - Layer C dump yt_picker_pre_tap before each successful tap.
  - Remove `items = video_items or all_items` fallback at line 1326.
  - Remove blind adb_tap(181, 600) fallback at line 1343-1345.
  - On exhausted parse attempts → fail-fast yt_gallery_no_video_candidate
    with diagnostic first_clickables[:10].
  - Extract _select_gallery_video method for testability.

  Spec: docs/superpowers/specs/2026-05-12-yt-cross-project-leak-fix-design.md
  Plan: docs/superpowers/plans/2026-05-12-yt-cross-project-leak-fix-plan.md
  Tests: 16 (helpers Layer A) + 7 (YT picker integration).
  Codex review: rounds TBD (after this commit).

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```
- [ ] **Step 8.3:** Push branch (no --force, no --force-with-lease):
  ```bash
  source ~/secrets/github-gengo2.env  # if needed for push auth
  git push -u origin feat-yt-cross-project-leak-fix-20260512
  ```
  > **STOP-gate:** перед push verify current HEAD == intended branch и НЕ main.

---

## Task 9: Codex review on patches (rounds до 0 P1)

**Tree:** deploy

- [ ] **Step 9.1:** Codex review against main (через stdin pipe — memory `feedback_codex_sandbox_broken`):
  ```bash
  cd /root/.openclaw/workspace-genri/autowarm
  git diff main...feat-yt-cross-project-leak-fix-20260512 \
      -- publisher_helpers.py publisher_instagram.py publisher_youtube.py \
         tests/test_publisher_helpers_layer_a.py tests/test_publisher_youtube_picker.py \
      | ~/.local/bin/codex review -
  ```
- [ ] **Step 9.2:** Apply все P1 findings (новый commit). Repeat round.
- [ ] **Step 9.3:** Стопаем на raund где **0 P1**. P2 logged в evidence (apply если quick, defer если deep refactor).

---

## Task 10: Open PR

**Tree:** GitHub (через `gh` CLI)

- [ ] **Step 10.1:**
  ```bash
  source ~/secrets/github-gengo2.env  # GenGo2 admin token
  gh pr create --base main --head feat-yt-cross-project-leak-fix-20260512 \
    --title "fix(yt-publisher): cross-project leak defense (port IG PR #36)" \
    --body "$(cat <<'EOF'
  ## Summary
  - Port IG cross-project leak Layer A + RC-8 D2/D3 fail-fast to YouTube picker
  - Extract Layer A logic to publisher_helpers.layer_a_pre_tap_verify (shared IG+YT)
  - Remove `items = video_items or all_items` and `adb_tap(181, 600)` blind paths

  ## Evidence
  - Spec: contenthunter/docs/superpowers/specs/2026-05-12-yt-cross-project-leak-fix-design.md (Codex CLEAN round 3)
  - Plan: contenthunter/docs/superpowers/plans/2026-05-12-yt-cross-project-leak-fix-plan.md
  - Vulnerability map: publisher_youtube.py:1298-1346 — see spec evidence section
  - IG reference: PR #36 (commits 3815dd5/f518a3f/85ed0e9)

  ## Test plan
  - [x] Unit: publisher_helpers Layer A (9 tests in test_publisher_helpers_layer_a.py)
  - [x] Regression: IG picker tests pass after refactor
  - [x] Integration: YT picker (7 tests in test_publisher_youtube_picker.py)
  - [ ] Live verify phone #19: positive publish + induced negative (foreign mp4 in /sdcard/Download/)
  - [ ] 24h soak: monitor yt_picker_wrong_candidate + yt_gallery_no_video_candidate events

  ## Rollout
  - Single PR, no feature flag (bug-fix). Mid-flight kill: clear both
    `_last_push_ts` AND `_last_expected_basename` in publisher_base to soft-fail
    both Layer A checks.
  - Rollback: `git revert` + auto-push hook.

  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  EOF
  )"
  ```
- [ ] **Step 10.2:** Returned PR URL → записать в evidence.

---

## Task 11: Evidence file

**Tree:** docs (`/home/claude-user/contenthunter/.claude/worktrees/yt-stab-20260512/`)

- [ ] **Step 11.1:** Создать `docs/evidence/2026-05-12-yt-cross-project-leak-fix-shipped.md` после merge:
  - PR URL
  - Commits list
  - Codex review rounds результаты
  - Test counts
  - Live verify результаты (positive + negative)
  - 24h soak link (если уже есть)
  - Open follow-ups (если YT thumbnail format ≠ IG → backlog regex)

---

## Out of scope (для отдельных PRs)

- Retro-detection past YT leaks (requires page scraping)
- YT-specific thumbnail format regex if discovered to differ from IG (separate enhancement PR)
- gmail-coverage / `yt_target_not_in_picker` flow → Шаг C (этот же session)
- `yt_editor_upload_timeout (после AI)` → Шаг D (этот же session)
