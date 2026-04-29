# PLAN — AI Unstuck hardening (anti-loop + observability)

**Тип:** fix (cost-guard + observability)
**Создан:** 2026-04-29
**Режим:** Full
**Источник:** memory `project_ai_unstuck_hardening_backlog.md`

**Репо:**
- Код: `/root/.openclaw/workspace-genri/autowarm/` (post-commit hook → `GenGo2/delivery-contenthunter`).
- Plan/evidence: `/home/claude-user/contenthunter/`.

## Settings

- Testing: yes — extract pure-function helpers + unit-тесты на anti-loop + missing-coords + S3-upload skip.
- Logging: structured events `ai_unstuck_*` для post-deploy наблюдения.
- Docs: warn-only — evidence обязателен.

## Контекст

`publisher_base.py:1669-1870` — `ai_unstuck(goal, max_attempts=5)`. Caller на IG-стороне `publisher_instagram.py:1676` дёргает `ai_unstuck(goal, max_attempts=4)` внутри upload-watcher loop'а до 30 итераций → теоретически до **120 Groq-vision вызовов на 1 fail** (~$1.20). На практике обычно ~16 outer × 4 inner = ~64 (~$0.64), но без anti-loop.

### Текущие проблемы (памятная дискуссия):

1. **No anti-loop guard** — один и тот же `(action, x, y)` исполняется без де-дупликации. Если AI зацикливается → платим за каждую идентичную попытку.
2. **Default `x=540, y=900` если AI опустит координаты** (line 1837-1838) → слепой центр-тап. Может сломать UI ещё больше.
3. **Promпт «if dialog IS part of flow → complete it»** провоцирует tap на чужих UI (Stories vs Reels — task 1532).
4. **Success-критерий = только `MainTabActivity`** (line 1861) — узкий, не покрывает TT/YT.
5. **Нет screenshot-URL в `meta` события** AI Unstuck — на ретроспективу нужно лезть в `/sdcard/debug_screenshots/` или `/tmp/autowarm_screenshots/`, S3-копии нет → потеря после restart'а.
6. **Не структурированный `meta` в `log_event`** — события AI Unstuck идут с пустой `meta`, что мешает фильтрации в дашбордах.

## Scope

**В scope (минимум для S-сессии):**
1. **T1 — Anti-loop guard** (главный cost-saving): trackим последние 3 `(action, x, y, key)`; если все идентичны → break + escalate event.
2. **T2 — S3 screenshot URL в meta**: загружать screenshot per-attempt в S3 через `upload_artifact_to_s3`, добавлять `screenshot_url` в `meta` каждого AI Unstuck event.
3. **T3 — Refuse blind tap** (защита от UI damage): если `action == 'tap'` и нет `x`/`y` → НЕ выполнять, log warning, continue к следующей attempt (но AI всё ещё дальше учится).
4. **T4 — Структурный meta в `log_event`** — каждый AI Unstuck-event получает category, platform, attempt, action, reason, screenshot_url.

**НЕ в scope (deferred):**
- (#3) Prompt revision — итеративная задача, нужны live данные после T1-T4 deploy для понимания где AI ошибается.
- (#4) Expanded success criterion (TT/YT markers) — отдельная задача с UI-исследованием.
- Refactor самой `ai_unstuck` функции — она 200 строк, сложная для refactor'а в одну сессию.

## Корневые причины

### RC-A: Anti-loop отсутствует

`for attempt in range(max_attempts)` (line 1720) без накопления action-history. Каждая итерация делает: screenshot → Groq vision call → execute → check MainTabActivity.

Если AI выдаёт одинаковое решение N раз — мы N раз делаем screenshot и Groq call. Cost: ~$0.01/call.

### RC-B: Default (540, 900) blind-tap

```python
x = int(action_data.get('x', 540))
y = int(action_data.get('y', 900))
```

Если Groq вернёт `{"action":"tap","reason":"..."}` без `x`/`y` (наблюдалось в логах) — мы тапаем центр экрана. Это ХУЖЕ чем no-op, потому что:
1. Может закрыть текущий dialog (false-positive recovery)
2. Может открыть другой dialog (deep recursion в ai_unstuck)
3. Пользователь не понимает что именно произошло

### RC-C: Screenshot lost после restart

Screenshot saved to `/tmp/autowarm_screenshots/unstuck_{task_id}_{ts}.png` (line 1724). После `pm2 restart autowarm` или OS reboot — local files могут протухнуть. Триаж past-fail'ов невозможен.

S3 upload helper уже есть (`upload_artifact_to_s3` импортирован в `publisher_base.py:50`), нужно только применить.

## Задачи

### T0. Pre-check — baseline AI Unstuck events за 7 дней

```sql
SELECT count(*) FILTER (WHERE e->>'msg' LIKE '%AI Unstuck%') AS unstuck_events,
       count(DISTINCT pt.id) FILTER (WHERE e->>'msg' LIKE '%AI Unstuck%') AS tasks_with_unstuck,
       count(*) FILTER (WHERE e->>'type'='warning' AND e->>'msg' LIKE '%anti%') AS anti_loop_pre
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.started_at >= NOW() - INTERVAL '7 days';
```

Baseline: знаем сколько AI Unstuck сессий было / сколько IG задач их триггерило / нулевой anti-loop сейчас.

### T1. Anti-loop guard в `ai_unstuck`

**Extract helper** в `publisher_base.py` (для testability):

```python
def _is_action_loop(recent_actions: list) -> bool:
    """Anti-loop guard: True если последние 3 действия идентичны.
    
    recent_actions — список tuple'ов (action, x_or_None, y_or_None, key_or_None).
    Используется ai_unstuck для де-дуплицирования зацикленных AI-решений.
    """
    if len(recent_actions) < 3:
        return False
    return recent_actions[-3] == recent_actions[-2] == recent_actions[-1]
```

**Wire в `ai_unstuck`** перед `for attempt`-циклом:
```python
recent_actions = []
```

**Внутри loop'а**, после parse'а action_data, ПЕРЕД execute:
```python
sig = (
    action,
    int(action_data['x']) if action == 'tap' and action_data.get('x') is not None else None,
    int(action_data['y']) if action == 'tap' and action_data.get('y') is not None else None,
    action_data.get('key') if action == 'keyevent' else None,
)
recent_actions.append(sig)
if _is_action_loop(recent_actions):
    log.warning(f'  🤖 ai_unstuck: anti-loop trip — 3 identical actions, escalating')
    self.log_event('warning',
                   f'🤖 AI Unstuck: anti-loop trip ({sig[0]} ×3) — escalating',
                   meta={'category': 'ai_unstuck_anti_loop',
                         'platform': self.platform,
                         'last_action': sig[0],
                         'attempt': attempt + 1,
                         'reason': reason})
    break
```

### T2. S3 screenshot URL в meta

После успешного локального screenshot'а (после `with open(local, 'rb') as f:` — line 1739), ДО Groq-call'а:

```python
# Upload screenshot to S3 для post-mortem analytics. Graceful — если упало,
# fallback на None (не блокируем AI Unstuck, screenshot уже у нас в base64).
shot_s3_url = None
try:
    shot_s3_url = upload_artifact_to_s3(
        local_path=local,
        platform=self.platform,
        task_id=self.task_id,
        kind='screenshot',
        content_type='image/png',
    )
except Exception as _us:
    log.debug(f'  ai_unstuck: S3 upload skipped: {_us}')
```

Использовать `shot_s3_url` в каждом `log_event` итерации (T4 ниже).

### T3. Refuse blind tap

**Extract helper** в `publisher_base.py`:
```python
def _validate_tap_coords(action_data: dict) -> Optional[Tuple[int, int]]:
    """Return (x, y) если оба числа предоставлены, иначе None.
    
    Защита от blind center-tap'а когда Groq возвращает tap без координат.
    Используется ai_unstuck — None означает 'пропустить эту attempt'.
    """
    raw_x = action_data.get('x')
    raw_y = action_data.get('y')
    if raw_x is None or raw_y is None:
        return None
    try:
        return (int(raw_x), int(raw_y))
    except (TypeError, ValueError):
        return None
```

**Wire в `ai_unstuck`** — заменить:
```python
if action == 'tap':
    x = int(action_data.get('x', 540))
    y = int(action_data.get('y', 900))
    log.info(f'  🤖 ai_unstuck: tap ({x},{y})')
    self.adb_tap(x, y)
```

на:
```python
if action == 'tap':
    coords = _validate_tap_coords(action_data)
    if coords is None:
        log.warning(f'  🤖 ai_unstuck: AI вернул tap без координат → пропуск')
        self.log_event('warning',
                       '🤖 AI Unstuck: tap без координат — пропуск',
                       meta={'category': 'ai_unstuck_tap_no_coords',
                             'platform': self.platform,
                             'attempt': attempt + 1,
                             'reason': reason,
                             'screenshot_url': shot_s3_url})
        continue  # пропускаем attempt без adb_tap (защита от blind tap)
    x, y = coords
    log.info(f'  🤖 ai_unstuck: tap ({x},{y})')
    self.adb_tap(x, y)
```

### T4. Структурный meta во всех AI Unstuck events

Заменить line 1833:
```python
self.log_event('info', f'🤖 AI Unstuck [{attempt+1}/{max_attempts}]: {action} — {reason}')
```

на:
```python
self.log_event('info',
               f'🤖 AI Unstuck [{attempt+1}/{max_attempts}]: {action} — {reason}',
               meta={'category': 'ai_unstuck_action',
                     'platform': self.platform,
                     'attempt': attempt + 1,
                     'action': action,
                     'reason': reason,
                     'screenshot_url': shot_s3_url})
```

Аналогично — добавить screenshot_url в success-event (line 1863) и финальный fail-event если есть.

### T5. Unit-тесты для helper'ов

Новый файл `tests/test_ai_unstuck_helpers.py`:

```python
def test_is_action_loop_empty_returns_false()
def test_is_action_loop_two_identical_returns_false()
def test_is_action_loop_three_identical_taps_returns_true()
def test_is_action_loop_three_identical_keyevents_returns_true()
def test_is_action_loop_mixed_returns_false()
def test_is_action_loop_three_identical_then_one_different_returns_false()
    # после break будем смотреть на последние 3, если последняя не та же — нет loop'а

def test_validate_tap_coords_happy_path()
def test_validate_tap_coords_missing_x_returns_none()
def test_validate_tap_coords_missing_y_returns_none()
def test_validate_tap_coords_string_coords_converts()
def test_validate_tap_coords_non_numeric_returns_none()
def test_validate_tap_coords_both_none_returns_none()
```

12 тестов, все на pure functions — нет MRO/DB зависимостей.

### T6. Smoke + restart

1. `python -m pytest tests/test_ai_unstuck_helpers.py -v` → 12/12 green.
2. Pre-restart queue check (`SELECT count(*) FILTER (WHERE status IN ('running','claimed'))`).
3. Если ≤1 — `sudo pm2 restart autowarm`.
4. `pm2 describe autowarm | grep -E "status|restarts|uptime"` — online, no unstable.
5. Logs `pm2 logs autowarm --lines 40 --nostream | grep -iE "error|exception|traceback"` — пусто.

### T7. Evidence + memory + commits

Evidence-файл `.ai-factory/evidence/ai-unstuck-hardening-20260429.md`:
- T0 baseline output
- Diff snippets T1/T2/T3/T4
- Pytest output
- Restart confirmation

Memory:
- `project_ai_unstuck_hardening_backlog.md` — обновить status на «✅ shipped 2026-04-29 (anti-loop + S3 URL + blind-tap guard); deferred: prompt revision + expanded success criterion».
- `MEMORY.md` — обновить entry.

**Commits:**

| # | Repo/branch | Message |
|---|---|---|
| 1 | prod autowarm | `feat(ai-unstuck): anti-loop guard + S3 screenshot URL + blind-tap refusal` |
| 2 | prod autowarm | `test(ai-unstuck): unit tests for helpers (12 tests)` |
| 3 | contenthunter | `docs(plans+evidence): AI Unstuck hardening — executed T0-T7` |

Можно объединить commits 1+2 если ROI ≤. Сделаем 2 atomic если diff большой, 1 если маленький.

## Commit Plan

3 коммита: 1-2 prod (atomic) + 1 docs.

## Риски

- **R1 — anti-loop ложно-срабатывает на legitimate sequence** (например AI делает 3 одинаковых back'а на одинаковый dialog в каскаде popups). Mitigation: смотрим `ai_unstuck_anti_loop` events после deploy; если >5% → расширить эвристику (например check ChangedUI после каждого шага).
- **R2 — S3 upload замедляет ai_unstuck loop** (по 1 RTT на каждом attempt × 5). Beget S3 обычно ≤500ms, итого +2.5s на 5 attempts. Mitigation: graceful — если timeout >2s, fallback в None (без блокировки публикации). Можно добавить `timeout=3` в boto3 config later.
- **R3 — blind-tap refusal оставляет AI без действия** для случаев, когда Groq возвращает invalid response. AI в next-attempt получит ту же UI и решение может остаться тем же. Mitigation: T1 anti-loop поймает, и мы выйдем break'ом.
- **R4 — параллельная сессия paginated etap-3** — НЕ пересекается (publisher_base.py vs server.js).

## Rollback

- Atomic commit 1 (T1+T2+T3+T4): `git revert` возвращает permissive ai_unstuck. Безопасно — старое поведение известно, T1-T4 — additive hardening.
- Commit 2 (tests): чистый additive.
- Commit 3 (docs): не нуждается.

## Дальше

T0 → T1 → T2 → T3 → T4 (правки в publisher_base.py одним pass'ом) → T5 (тесты) → T6 (pytest + restart) → T7 (docs).

**Stop-conditions:**
- T6 любой test fails → fix или revert изменений.
- Post-restart ImportError → revert через `git revert` + restart.
