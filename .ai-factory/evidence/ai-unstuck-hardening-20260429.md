# Evidence — AI Unstuck hardening (2026-04-29)

**Plan:** `.ai-factory/plans/ai-unstuck-hardening-20260429.md`
**Status:** ✅ **SHIPPED** to prod main as `b75d587` (auto-pushed by post-commit hook)
**PM2 restart:** 2026-04-29 ~07:55Z, restart #211, status=online, exec cwd correct, unstable_restarts=0

## Контекст

Memory-backlog `project_ai_unstuck_hardening_backlog.md` идентифицировал 6 проблем в `publisher_base.py:1669-1870` (`ai_unstuck`). Этот план закрывает 4 (anti-loop, S3 URL, blind-tap refusal, structured meta) — 2 deferred (prompt revision, expanded success criterion) требуют live data после deploy.

## T0 — Baseline (7 days)

```sql
SELECT count(*) FILTER (WHERE e->>'msg' LIKE '%AI Unstuck%') AS unstuck_events,
       count(DISTINCT pt.id) FILTER (WHERE e->>'msg' LIKE '%AI Unstuck%') AS tasks_with_unstuck,
       count(*) FILTER (WHERE e->>'msg' LIKE '%достигли MainTabActivity%' OR e->>'msg' LIKE '%цель достигнута%') AS unstuck_success
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.started_at >= NOW() - INTERVAL '7 days';
```

```
 unstuck_events | tasks_with_unstuck | unstuck_success 
----------------+--------------------+-----------------
             70 |                  1 |               0
```

**Insight:** 70 AI Unstuck events за 7 дней, все из 1 task. **0 success** — никогда не достигал MainTabActivity. Все 70 events — впустую (~$0.70 в Groq за 7 дней). Anti-loop точно нужен.

## Что отгружено (commit `b75d587`)

### T1 — Anti-loop guard

Pure-function helper в module scope:
```python
def _is_action_loop(recent_actions: list) -> bool:
    if len(recent_actions) < 3:
        return False
    return recent_actions[-3] == recent_actions[-2] == recent_actions[-1]
```

Wire в `ai_unstuck`:
- `recent_actions = []` перед `for attempt`-циклом
- После parse'а action_data: `sig = (action, x_or_None, y_or_None, key_or_None)`
- Append + check: если 3 идентичные → `log_event('warning', meta={'category': 'ai_unstuck_anti_loop', ...})` + `break`

### T2 — S3 screenshot URL в meta

После успешного локального screenshot'а:
```python
shot_s3_url = None
try:
    shot_s3_url = upload_artifact_to_s3(
        local_path=local, platform=self.platform, task_id=self.task_id,
        kind='screenshot', content_type='image/png',
    )
except Exception as _us:
    log.debug(f'  ai_unstuck: S3 upload skipped: {_us}')
```

`shot_s3_url` теперь в meta каждого AI Unstuck event'а (action / anti-loop / tap-no-coords / success).

### T3 — Blind-tap refusal

Pure-function helper:
```python
def _validate_tap_coords(action_data: dict):
    raw_x = action_data.get('x')
    raw_y = action_data.get('y')
    if raw_x is None or raw_y is None:
        return None
    try:
        return (int(raw_x), int(raw_y))
    except (TypeError, ValueError):
        return None
```

Wire: было `x = int(action_data.get('x', 540))` → стало `coords = _validate_tap_coords(action_data); if coords is None: continue`. Если AI вернул tap без координат — пишем warning event `ai_unstuck_tap_no_coords` и пропускаем attempt без adb_tap.

### T4 — Структурный meta во всех AI Unstuck events

Каждый `log_event` теперь включает:
```python
meta={'category': 'ai_unstuck_action',  # или anti_loop / tap_no_coords / success
      'platform': self.platform,
      'attempt': attempt + 1,
      'action': action,
      'reason': reason,
      'screenshot_url': shot_s3_url}
```

## Pytest

```
tests/test_ai_unstuck_helpers.py::test_is_action_loop_empty_returns_false PASSED
tests/test_ai_unstuck_helpers.py::test_is_action_loop_two_identical_returns_false PASSED
tests/test_ai_unstuck_helpers.py::test_is_action_loop_three_identical_taps_returns_true PASSED
tests/test_ai_unstuck_helpers.py::test_is_action_loop_three_identical_keyevents_returns_true PASSED
tests/test_ai_unstuck_helpers.py::test_is_action_loop_three_identical_waits_returns_true PASSED
tests/test_ai_unstuck_helpers.py::test_is_action_loop_mixed_three_returns_false PASSED
tests/test_ai_unstuck_helpers.py::test_is_action_loop_taps_with_different_coords_returns_false PASSED
tests/test_ai_unstuck_helpers.py::test_is_action_loop_only_checks_last_3 PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_happy_path PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_string_coords_converts PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_missing_x_returns_none PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_missing_y_returns_none PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_both_none_returns_none PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_explicit_none_returns_none PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_non_numeric_returns_none PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_float_truncates_to_int PASSED
tests/test_ai_unstuck_helpers.py::test_validate_tap_coords_negative_passes_through PASSED
============================== 17 passed in 0.10s ==============================
```

Полный publisher pytest gate: **53 passed** (IG + ai_unstuck + publisher_imports).

## Pre-restart queue check

```
 running | claimed 
---------+---------
       0 |       0
```

## PM2 restart

```
sudo pm2 restart autowarm
→ status=online, restarts=211, uptime=3s, exec cwd=/root/.openclaw/workspace-genri/autowarm
→ unstable_restarts=0
```

Logs (40 lines after restart): чисто, никаких ImportError / NameError / Traceback.

## Live observation (deferred organic)

Ближайшие IG fail'ы триггернут AI Unstuck. Следующая сессия должна проверить:

```sql
-- Anti-loop trip rate
SELECT count(*) FILTER (WHERE e->'meta'->>'category' = 'ai_unstuck_anti_loop') AS anti_loop_trips,
       count(*) FILTER (WHERE e->'meta'->>'category' = 'ai_unstuck_action') AS total_actions,
       count(*) FILTER (WHERE e->'meta'->>'category' = 'ai_unstuck_tap_no_coords') AS no_coords_skips,
       count(*) FILTER (WHERE e->'meta'->>'category' = 'ai_unstuck_success') AS successes
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.started_at >= '2026-04-29 07:55:00';
```

Ожидание:
- `anti_loop_trips > 0` — anti-loop работает (т.е. AI зацикливается, но мы выходим раньше).
- `no_coords_skips ≥ 0` — Groq иногда возвращает tap без x/y, защищены.
- `total_actions / tasks` < предыдущий baseline (70 / 1 = 70) — anti-loop сократил average attempts на task.
- `successes` — возможно по-прежнему 0; если так — нужен fix (#4) расширения success criterion на TT/YT.

## Open follow-ups (defer)

- **#3 Prompt revision** — пересмотреть «if dialog IS part of flow → complete it» (provokes wrong taps, e.g. Stories vs Reels). Нужны live samples после deploy.
- **#4 Expanded success criterion** — `MainTabActivity` Instagram-only, добавить TT/YT markers.

## Memory updates

- `project_ai_unstuck_hardening_backlog.md` — обновить status: «✅ Anti-loop + S3 URL + blind-tap shipped 2026-04-29 (b75d587). Deferred: prompt revision + success criterion».
- `MEMORY.md` — bump entry.

## Commits

| Repo | Branch | SHA | Message |
|---|---|---|---|
| `delivery-contenthunter` (prod) | `main` | `b75d587` | `feat(ai-unstuck): anti-loop guard + S3 screenshot URL + blind-tap refusal` |
| `contenthunter` | `fix/testbench-publisher-base-imports-20260427` | (pending) | `docs(plans+evidence): AI Unstuck hardening — executed T0-T7` |
