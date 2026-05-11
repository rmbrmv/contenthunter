# TT post-publish success detection in `wait_upload` — design v2

**Date:** 2026-05-11
**Author:** Claude (session с Danil Pavlov)
**Repo:** `GenGo2/delivery-contenthunter` (autowarm publisher)
**Trigger:** Post-mortem pt 4523 (clickpay_world raspberry=9, 2026-05-10) — frame-by-frame analysis screen recording'а показал что публикация успешно состоялась в ~19:42, но `_wait_tiktok_upload` не распознал post-publish auto-навигацию TT в feed/inbox и продолжил 12 минут вызывать AI Unstuck, который случайно тапнул «+» в bottom nav, открыл Camera, и в итоге устройство улетело в Launcher (`tt_fg_lost`).

**Changelog v1→v2 (2026-05-11):** applied Codex design review (5 P1 + 6 P2 + 4 P3 finds). Major rewrites:
- Replaced raw substring `nav_hits` matching with bounds-scoped XML parsing + group-based label set with EN/RU variants
- Added AI Unstuck pre-call guard into scope (was out-of-scope; cascade evidence показал что main-nav-skip критичен)
- Activity blacklist помечен как seed (verified-from-code only `MainActivity`, `DetailActivity`, `SystemShareActivity`)
- Added post-success URL classification path (`tt_success_inferred_but_no_video_url`)
- Fixed SQL re-queue path (`publish_queue.publish_task_id`)
- Fixed timing description (real wait=0 = ~11s after Поделиться tap)
- Reworked test cases (Интересное, share-sheet, malformed XML, DetailActivity)
- Detection extracted в pure helper `_tt_infer_post_publish_success`

## Контекст и evidence

### pt 4523 timeline (visual reconstruction)

| Время UTC | Source | Что было на экране | Что думал publisher |
|---|---|---|---|
| ~19:42:30 | screenrec offset ~350s | TT auto-навигация в feed «Друзья», видео clickpay_world показывается «1 с. назад» | wait_upload итерация, UPLOAD_OK markers не сработали |
| 19:42:59 | publish_tasks.screenshot_url | TT «Друзья» feed, видео опубликовано | retap step 2 (publisher тапнул «Поделиться» повторно?) |
| 19:43:36 (frame_420s) | screenrec | TT «Входящие» (Inbox) — bottom nav: Главная/Друзья/+/Входящие/Профиль | wait_upload продолжает |
| 19:43:45 — 19:44:15 | events | Inbox screen | AI Unstuck вызван 2× → anti-loop trip |
| 19:45:06 (frame_510s) | screenrec | Inbox screen (всё ещё) | wait_upload restart #N |
| **19:45:36 (frame_540s)** | screenrec | **TikTok Camera «ПУБЛИКАЦИЯ»** — экран съёмки нового видео | AI Unstuck тапнул «+» в bottom nav |
| 19:46:38 — 19:54:00 | events | Camera screen, AI Unstuck бесполезно тапает shutter / «Добавить музыку» chip | publisher всё ещё «не понял» |
| 19:55:07 | events | overlay_pkg=`com.sec.android.app.launcher` | `tt_fg_lost` финальный |

### Root cause: 3-bag stack

1. **PRIMARY:** `wait_upload` UPLOAD_OK markers (строковые, см. publisher_tiktok.py top: `UPLOAD_OK = [...]`) ищут текст на publish-screen. После реальной публикации TT auto-навигирует в feed/inbox — этих markers там нет. **Бонус observation:** existing `DetailActivity` success branch (publisher_tiktok.py:680) находится внутри `if not tiktok_active` (line 661) — но `DetailActivity` ВСЕГДА содержит `com.zhiliaoapp.musically` → branch dead, никогда не срабатывает. v2 fix лечит и это.

2. **CASCADE:** `_cur_act_tt` guard в AI Unstuck triggering условии (`'musically' in _cur_act_tt or 'tiktok' in _cur_act_tt.lower()`) — True для всех TT-activity, включая Inbox/Feed. AI Unstuck вызван с goal «complete publishing», на Inbox screen нашёл «+» в bottom nav (это TT «Create» button), тапнул → открыл Camera. **v2 включает AI Unstuck pre-call guard — bundle с primary fix.**

3. **TERTIARY:** AI Unstuck inner anti-loop работает по `(action, x, y, key)` — корректно режет 3 идентичных тапа. Но caller `wait_upload` перезапускает `ai_unstuck()` снова и снова на каждой 5-й итерации wait_upload без outer-cap. 7 рестартов = 21 tap за 12 минут. **Out of scope для этой PR; backlog — `ai-unstuck-outer-cap-tt`.**

### Frequency

- `tt_fg_lost` 7 дней: 3 кейса. 1 из 3 (pt 4523) — с этим pattern. Низкая частота, **но** этот pattern представляет ситуацию «ложный fail» — публикация была, а dashboard показывает failed → operator видит fake-проблему.
- `tt_upload_confirmation_timeout` 24h: 16 (12 на raspberry=9 — все pre-music-rights-handler-ship). Часть из них может быть тот же pattern (success not detected) — backlog re-audit.

## Цель design'а

1. Распознавать post-publish success **до** того как AI Unstuck начнёт хаотично тапать. (Primary)
2. Предотвратить cascade: не вызывать AI Unstuck когда видна main nav / non-composer TT screen. (Bundle, was out-of-scope в v1)
3. Distinct event для inferred success без `/video/<id>` URL — не молча превращать cancelled publish в "awaiting_url". (Defensive)

Anti-loop bypass (Bug #3) — отдельный backlog (см. секцию «Out of scope»).

## Design

### Где меняем код

`publisher_tiktok.py` — функция `_wait_tiktok_upload` (loop ~648-977), и AI Unstuck call site ~976.

### Module-level constants (top of publisher_tiktok.py)

```python
# ─────────────────────────────────────────────────────────────────────────────
# Post-publish success detection 2026-05-11
# ─────────────────────────────────────────────────────────────────────────────

# TT bottom-nav label groups. Каждый group = синонимы одного таба (RU/EN/А-B).
# 5 групп = ровно 5 табов TT main nav: Home, Discover/Friends, Create, Inbox,
# Profile. На composer screen NONE of these visible (только X в углу + кнопка
# «Поделиться»). На любом main screen видны все 5.
TT_MAIN_NAV_LABEL_GROUPS = (
    ('Главная', 'Home'),
    ('Друзья', 'Интересное', 'Friends', 'Discover'),
    ('Создать', 'Create'),
    ('Входящие', 'Inbox'),
    ('Профиль', 'Profile', 'Me'),
)

# TT activities trustworthy from code grep (publisher_tiktok.py + tests):
#   - 'MainActivity' (com.zhiliaoapp.musically/.main.app.MainActivity) — confirmed
#   - 'DetailActivity' (видео страница после публикации) — confirmed line 680
#   - 'SystemShareActivity' — confirmed line 316
#
# TT_COMPOSER_ACTIVITIES — SEED blacklist для composer/edit/permission flow.
# НЕ verified в коде, нужны live dumpsys observations. Расширять по evidence
# через top_activity field в логированных событиях.
# Substring match защищает от подвариантов (BaseLoginPostActivity etc).
TT_COMPOSER_ACTIVITIES_SEED = (
    'PostActivity',
    'EditActivity',
    'PublishActivity',
    'CameraActivity',
    'PermissionActivity',
    'MusicSelectActivity',
    'CutVideoActivity',
    'CoverActivity',
)

# Phase-1: только для logging/debug, чтобы не использовать blacklist как
# источник истины. Use `_tt_infer_post_publish_success` через positive признаки
# (main nav visible + non-composer + TT active), не через NOT-in-blacklist.
```

### Pure helper для testability (P3.2)

```python
def _tt_infer_post_publish_success(
    ui: str,
    top_activity: str,
    wait_iter: int,
    *,
    nav_label_groups=TT_MAIN_NAV_LABEL_GROUPS,
    composer_seed=TT_COMPOSER_ACTIVITIES_SEED,
    bottom_band_y_min: float = 0.80,  # bottom 20% of screen
) -> tuple[bool, dict]:
    """Detect post-publish success via topResumedActivity + bottom-nav XML parse.

    Returns: (success_bool, debug_meta_dict)
    debug_meta_dict содержит: nav_groups_visible, top_activity, on_composer_seed,
    on_tiktok, reason (string explaining decision).

    Rationale: TT auto-navigates from publish-screen to feed/inbox/profile after
    successful publish. Existing UPLOAD_OK markers only match publish-screen text.
    Detect via:
      1. top_activity contains 'tiktok' or 'musically' (TT in foreground).
      2. EITHER top_activity contains 'DetailActivity' (видео страница — strongest
         signal, не требует bottom nav check) OR
         bottom-nav XML check: ≥3 of 5 nav label groups visible in bottom 20% of
         screen, AND top_activity does NOT match composer seed list.
    """
    meta = {
        'top_activity': (top_activity or '')[:160],
        'on_tiktok': False,
        'on_composer_seed': False,
        'nav_groups_visible': [],
        'detail_activity': False,
        'reason': '',
    }
    cur_act = (top_activity or '')
    on_tiktok = ('musically' in cur_act) or ('tiktok' in cur_act.lower())
    meta['on_tiktok'] = on_tiktok
    if not on_tiktok:
        meta['reason'] = 'not_on_tiktok'
        return False, meta

    # DetailActivity = TT video detail page after publish (strongest single signal)
    if 'DetailActivity' in cur_act:
        meta['detail_activity'] = True
        meta['reason'] = 'detail_activity'
        return True, meta

    on_composer = any(a in cur_act for a in composer_seed)
    meta['on_composer_seed'] = on_composer
    if on_composer:
        meta['reason'] = 'on_composer_seed'
        return False, meta

    # Bottom-nav XML parse
    try:
        import xml.etree.ElementTree as ET, re as _re
        root_el = ET.fromstring(ui or '<hierarchy/>')
        # Determine screen height from root bounds (first node with bounds)
        screen_h = 0
        for node in root_el.iter('node'):
            b = node.get('bounds', '')
            m = _re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', b)
            if m:
                screen_h = max(screen_h, int(m.group(4)))
        if screen_h < 1000:  # sanity — TT phones are ≥1500px tall
            meta['reason'] = 'screen_height_implausible'
            return False, meta
        bottom_threshold = int(screen_h * bottom_band_y_min)
        groups_visible = []
        for group in nav_label_groups:
            for node in root_el.iter('node'):
                txt = (node.get('text', '') or '').strip()
                desc = (node.get('content-desc', '') or '').strip()
                b = node.get('bounds', '')
                m = _re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', b)
                if not m:
                    continue
                cy = (int(m.group(2)) + int(m.group(4))) // 2
                if cy < bottom_threshold:
                    continue
                if any(label in txt or label in desc for label in group):
                    groups_visible.append(group[0])
                    break
        meta['nav_groups_visible'] = groups_visible
        if len(groups_visible) >= 3:
            meta['reason'] = f'main_nav_{len(groups_visible)}_groups'
            return True, meta
        meta['reason'] = f'main_nav_only_{len(groups_visible)}_groups'
        return False, meta
    except Exception as exc:
        meta['reason'] = f'xml_parse_error: {type(exc).__name__}'
        return False, meta
```

### Block placement в `_wait_tiktok_upload`

**Order constraints (per Codex P2.1):** existing checks order in publisher_tiktok.py wait_upload loop is:
foreground guard → notification modal → UPLOAD_OK → music-rights → audio-dialog → still_on_editor → share-sheet failure → retap → AI Unstuck.

**New block placement:** **AFTER** music-rights/audio-dialog/still_on_editor/share-sheet checks (which are blocking dialogs that may render WITH main nav behind), **BEFORE** AI Unstuck. This avoids inferring success while a blocking dialog is still on screen.

```python
# After existing dialog/blocker checks (music-rights, audio-dialog, still_on_editor,
# share-sheet failure), before AI Unstuck call site.
# [POST-PUBLISH SUCCESS DETECTION 2026-05-11 v2]
cur_act_post = self.adb(
    'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
    timeout=8,
) or ''
success, meta = _tt_infer_post_publish_success(ui, cur_act_post, wait)
if success:
    log.info(f'  ✅ TikTok: post-publish success inferred '
             f'(reason={meta["reason"]}, nav_groups={meta["nav_groups_visible"]}, '
             f'wait={wait})')
    self.log_event(
        'info',
        f'TikTok: post-publish success inferred — {meta["reason"]}',
        meta={'category': 'tt_post_publish_success_inferred',
              'platform': self.platform,
              'wait_iteration': wait,
              **meta},
    )
    upload_confirmed = True
    break
```

### AI Unstuck pre-call guard (NEW в scope, P1.5)

В существующем коде на line ~966-976 — guard расширить **перед** вызовом AI Unstuck:

```python
if wait > 0 and wait % 5 == 4:
    _cur_act_tt = self.adb(
        'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
        timeout=8,
    ) or ''
    tiktok_active = 'musically' in _cur_act_tt or 'tiktok' in _cur_act_tt.lower()
    if not tiktok_active:
        # AI только если TT активен (не ждём его возврата). Existing behavior preserved.
        continue

    # [NEW P1.5 2026-05-11] Skip AI Unstuck когда видна main nav (мы уже
    # на post-publish screen) или non-composer activity. Это предотвращает
    # cascade pt 4523: AI на Inbox тапает «+» → открывает Camera.
    success_check, gmeta = _tt_infer_post_publish_success(ui, _cur_act_tt, wait)
    if success_check:
        # Already success-positive but somehow not caught earlier — skip AI
        log.info(f'  🛑 TikTok: skip AI Unstuck — main nav/DetailActivity '
                 f'visible (reason={gmeta["reason"]})')
        self.log_event(
            'info',
            f'TikTok: skip AI Unstuck — likely post-publish ({gmeta["reason"]})',
            meta={'category': 'tt_unstuck_skipped_post_publish',
                  'platform': self.platform,
                  'wait_iteration': wait,
                  **gmeta},
        )
        # don't infer success here — let next iter detection block handle it
        continue
    # Composer/edit screen — also skip (we are on wrong screen для retry publishing)
    if any(a in _cur_act_tt for a in TT_COMPOSER_ACTIVITIES_SEED):
        log.info(f'  🛑 TikTok: skip AI Unstuck — composer activity '
                 f'({_cur_act_tt[:80]})')
        self.log_event(
            'info',
            f'TikTok: skip AI Unstuck — composer activity',
            meta={'category': 'tt_unstuck_skipped_composer',
                  'platform': self.platform,
                  'wait_iteration': wait,
                  'top_activity': _cur_act_tt[:160]},
        )
        continue

    log.info(f'  🤖 TikTok: неизвестное состояние {wait} итераций — AI Unstuck')
    _tt_goal = (
        f'Publish {self.media_type} on TikTok for account @{self.account}. '
        f'The Share/Post button was tapped. '
        f'An unexpected screen is blocking the upload confirmation. '
        f'Dismiss any dialogs or complete required steps to finish publishing.'
    )
    self.ai_unstuck(_tt_goal, max_attempts=3)
```

### Post-success URL classification (P1.4)

После `upload_confirmed=True` (любая ветка), при попытке `_auto_get_tiktok_url`:

```python
real_url = self._auto_get_tiktok_url(wait_secs=45)
if real_url and '/video/' in real_url:
    self._update_post_url_final(real_url)
    log.info(f'  ✅ Реальный URL: {real_url}')
    # existing tt_url_final event
elif inferred_path_used:  # set True если success пришёл через _tt_infer_post_publish_success
    log.warning(f'  ⚠️ TikTok: success inferred but no /video/ URL — '
                f'возможно cancelled/no-op publish')
    self.log_event(
        'warning',
        'TikTok: success inferred но specific URL не получен — '
        'возможно cancelled publish (operator проверка нужна)',
        meta={'category': 'tt_success_inferred_but_no_video_url',
              'platform': self.platform,
              'profile_url_fallback': profile_url},
    )
    # Status остаётся awaiting_url (не failed) для backwards-compat,
    # но new event позволит дашборду показать distinct warning.
```

### Why это работает (defensive layering)

| Layer | Что ловит | Защита от false-positive |
|---|---|---|
| `on_tiktok` | TT не улетел в Launcher | `tt_fg_lost` сработает legitimately |
| Block placement after dialog blockers | music-rights/audio-dialog/share-sheet могут render с main nav behind | Существующие blocker-handlers consume их first |
| `DetailActivity` (highest signal) | Видео страница = публикация состоялась | DetailActivity не появляется без real publish |
| `nav_groups_visible >= 3 of 5` + bounds-scoped | Main nav = post-publish state | Bounds scoping на bottom 20% защищает от false match `Профиль` в content/comments |
| Composer seed blacklist | Composer activities блокируют success | Не source of truth — only deny path |
| `wait` iter no longer hard threshold | DetailActivity может появиться сразу | Главный гейт — UI signals, не time |

## Components

| Файл | Изменение |
|---|---|
| `publisher_tiktok.py` | + 2 const groups (`TT_MAIN_NAV_LABEL_GROUPS`, `TT_COMPOSER_ACTIVITIES_SEED`) + helper `_tt_infer_post_publish_success` (~70 строк) + detection block в wait_upload (~15 строк) + AI Unstuck pre-call guard (~25 строк) + post-success URL classification (~15 строк) |
| `tests/test_publisher_tt_post_publish_success.py` (новый) | 9 unit tests (см. ниже) |

## Data flow

1. `publish_tiktok` → tap Поделиться → enter `_wait_tiktok_upload` loop
2. Each iter: dump_ui → existing blocker checks (music-rights, audio, etc.) → **NEW success detection block** → existing UPLOAD_OK string check → **NEW AI Unstuck guard** (если wait%5==4) → AI Unstuck (если guards passed)
3. Success path:
   - `_tt_infer_post_publish_success` → True → `tt_post_publish_success_inferred` event + `upload_confirmed=True` + break
   - OR existing UPLOAD_OK match → break
4. URL fetch:
   - `/video/<id>` URL → existing `tt_url_final` event
   - profile fallback only AND inferred path used → `tt_success_inferred_but_no_video_url` warning event
5. Stuck path:
   - 60 итераций без upload_confirmed → existing `tt_upload_confirmation_timeout`
   - AI Unstuck guards могут блокировать calls → если все iter'ы skipped → ai_unstuck call_count=0, that's OK

## Error handling

- **No new error_code.** Это success path + одна warning category.
- **New event categories:**
  - `tt_post_publish_success_inferred` (info) — main success detection. Meta: top_activity, nav_groups_visible, on_tiktok, on_composer_seed, detail_activity, reason, wait_iteration.
  - `tt_unstuck_skipped_post_publish` (info) — AI Unstuck guard fired due to main-nav. Meta: same as above + wait_iteration.
  - `tt_unstuck_skipped_composer` (info) — AI Unstuck guard fired due to composer activity. Meta: top_activity, wait_iteration.
  - `tt_success_inferred_but_no_video_url` (warning) — inferred success без specific video URL. Meta: profile_url_fallback.

## Tests

Файл `tests/test_publisher_tt_post_publish_success.py` (новый — pure helper testing).

```python
# Все тесты — pure call to _tt_infer_post_publish_success(ui, top_activity, wait).
# Не нужны mock'и self.adb / log_event. Простая функция → простые тесты.

def test_detail_activity_returns_success():
    """DetailActivity → True независимо от nav."""
    ui = '<hierarchy/>'
    act = 'topResumedActivity=ActivityRecord{... com.zhiliaoapp.musically/.detail.DetailActivity ...}'
    ok, meta = _tt_infer_post_publish_success(ui, act, wait_iter=0)
    assert ok and meta['reason'] == 'detail_activity'

def test_main_nav_5_groups_returns_success():
    """5/5 nav groups в bottom 20% + non-composer activity → True."""
    # Build XML with 5 nodes at y=2400-2520 (bottom of 2520-px screen)
    ...
    assert ok and meta['nav_groups_visible'] == ['Главная', 'Друзья', 'Создать', 'Входящие', 'Профиль']

def test_main_nav_3_groups_returns_success():
    """3/5 nav groups (минимум) → True."""
    ...
    assert ok and len(meta['nav_groups_visible']) == 3

def test_main_nav_2_groups_returns_keep_waiting():
    """2/5 nav groups (порог не достигнут) → False."""
    ...
    assert not ok and 'main_nav_only_2' in meta['reason']

def test_diskoveru_variant_recognized():
    """'Интересное' (RU вариант Discover/Friends) → group recognized."""
    ...

def test_composer_activity_keeps_waiting():
    """topResumedActivity содержит 'PostActivity' → False."""
    act = '... com.zhiliaoapp.musically/.post.PostActivity ...'
    ...
    assert not ok and meta['reason'] == 'on_composer_seed'

def test_launcher_activity_keeps_waiting():
    """topResumedActivity = launcher → False (on_tiktok=False)."""
    act = '... com.sec.android.app.launcher/.LauncherActivity ...'
    ...
    assert not ok and meta['reason'] == 'not_on_tiktok'

def test_main_nav_label_outside_bottom_band_ignored():
    """'Профиль' as section heading в content (cy=400 на 2520-px screen) → НЕ
       counts. Защита от false match в feed/profile content."""
    ...
    # 1 group in bottom + 'Профиль' высоко в content → only 1 group counts → False

def test_share_sheet_does_not_infer_success():
    """Android share sheet 'Поделиться в TikTok / Видео / Сообщение' с main
       activity → НЕ trigger success (composer-related path в нашем case;
       или existing share-sheet failure handler сработает раньше)."""
    # Existing checks ловят share-sheet до нашего блока — тест что наш блок
    # не trigger'ится на share-sheet activity.
    ...

def test_malformed_xml_returns_keep_waiting():
    """Empty/invalid XML → graceful False, не crash."""
    ok, meta = _tt_infer_post_publish_success('<not-valid', 'com.zhiliaoapp.musically/.MainActivity', 1)
    assert not ok and 'xml_parse_error' in meta['reason']
```

## Live verification plan

1. Deploy fix → push на main → auto-pull в `/root/.openclaw/workspace-genri/autowarm/` (git hook).
2. Re-queue pt 4488 (clickpay_world same account):
   ```sql
   UPDATE publish_queue
   SET status='pending',
       publish_task_id=NULL,
       updated_at=NOW()
   WHERE publish_task_id=4488
   RETURNING id, status, publish_task_id;
   ```
3. Через 5-10 мин: проверить новый pt:
   ```sql
   SELECT id, account, status, error_code,
          jsonb_array_length(events) AS n_events,
          (SELECT COUNT(*) FROM jsonb_array_elements(events) e
           WHERE e->'meta'->>'category'='tt_post_publish_success_inferred') AS success_inferred_count,
          (SELECT MAX((e->'meta'->>'wait_iteration')::int) FROM jsonb_array_elements(events) e
           WHERE e->'meta'->>'category'='tt_post_publish_success_inferred') AS detect_at_wait,
          (SELECT bool_or(e->'meta'->>'category' = 'tt_unstuck_skipped_post_publish') FROM jsonb_array_elements(events) e) AS unstuck_skipped
   FROM publish_tasks
   WHERE account='clickpay_world' AND created_at > NOW() - INTERVAL '15 min'
   ORDER BY id DESC LIMIT 5;
   ```
4. Expected:
   - `status = awaiting_url` или `done`
   - `success_inferred_count >= 1` (или existing UPLOAD_OK сработал — оба OK)
   - Total task time ≤ 90s vs текущие 12+ мин
5. Если live ОК — measure 7-day candidate-impact metric:
   ```sql
   SELECT COUNT(*) AS detected_per_week
   FROM publish_tasks
   WHERE platform='tiktok'
     AND updated_at >= NOW() - INTERVAL '7 days'
     AND events @> '[{"meta":{"category":"tt_post_publish_success_inferred"}}]'::jsonb;
   ```
   **Caveat:** это candidate impact — публикации, где новый path сработал первым. Часть могла бы быть caught existing UPLOAD_OK markers через несколько итераций позже. Treat as upper bound на спасённые tasks.

## Risks

| Риск | Вероятность | Impact | Mitigation |
|---|---|---|---|
| **False positive — TT показывает feed-нав ДО реальной публикации** (e.g. composer crash → fallback) | Низкая | Publisher запишет success → `_auto_get_tiktok_url` вернёт profile fallback → `tt_success_inferred_but_no_video_url` warning event для operator visibility | P1.4 fix: distinct warning event. Backlog: bumping status to 'failed' if URL absent — defer until live evidence |
| **TT UI evolution: activity названия меняются** | Средняя (TT агрессивно А/B-тестирует) | False negative: detection не сработает → behavior baseline (текущее) | Logging `top_activity` в каждом event позволит monitor'ить. Periodic audit query: `SELECT DISTINCT meta->>'top_activity' FROM events WHERE category LIKE 'tt_%'`|
| **TT bottom nav текст меняется** (А/B локализация) | Средняя | False negative | Group-based markers с EN/RU вариантами. Bounds-scoped (only bottom 20%) защищает от false match с обычным текстом |
| **screen_height detection fails** (некоторые devices give малый XML) | Низкая | Helper возвращает False с reason='screen_height_implausible' → keep waiting | sanity check 1000px минимум. Тест `test_malformed_xml_returns_keep_waiting` покрывает |
| **AI Unstuck guard ломает legit AI-recovery scenarios** | Средняя | TT застрял в edge-case dialog где AI Unstuck сейчас помогает | Guards: skip только когда (success_check=True) ИЛИ composer activity. Other dialogs (audio/music-rights) consumed by existing blocker handlers до AI call — guards не trigger |
| **dumpsys overhead** ~50-200ms × 60 итераций × 2 (detection + guard) = до 24s extra per task | Низкая | Slowdown | Net win: success detection экономит 8+ минут when triggered. Optimization: cache cur_act per iter (один call вместо двух) — defer |

## Out of scope (отдельный backlog)

1. **AI Unstuck reason-rephrasing anti-loop bypass** — anti-loop key из `(action, x, y, key)` дополнить `(intent_hash или global N-tap cap regardless of reason)`. Backlog: `ai-unstuck-reason-rephrasing-bypass`.

2. **AI Unstuck outer-cap для TT wait_upload** — secondary safety net на случай если new guards и success detection не сработают. Backlog: `ai-unstuck-outer-cap-tt`.

3. **Re-audit `tt_upload_confirmation_timeout` history** на subset кейсов с тем же pattern (publication actually succeeded but not detected). Если пропорция большая — bumping priority deploy. Discovery, не код.

4. **Status bumping для `tt_success_inferred_but_no_video_url`** — defer до evidence в проде. Если operator-confirmed что cancelled publish регулярно false-positive'ит — добавить логику mark task as failed.

## Open questions for review

1. **Activity blacklist — насколько aggressive?** v2 spec говорит «seed, не authoritative». Compromise: shipping с seed list, расширяя по top_activity logging evidence. Альтернатива — wait для manual device tour. **Решение:** ship with seed (low risk: blacklist используется только в guard для AI Unstuck skip; не как main success signal).

2. **wait threshold для detection block.** v1 предлагал `wait >= 1` (skip iter 0). v2 убирает это — DetailActivity / strong nav signal могут появиться сразу. Risk: detection fires в iter 0 пока tap «Поделиться» не зарегистрировался. Mitigation: detection block размещён ПОСЛЕ existing blocker checks (still_on_editor catches «ещё на publisher screen» сценарий). **Решение:** убрать wait threshold, полагаться на UI signals.

3. **post-success URL fallback path.** Сейчас тест `'/video/' in real_url` не учитывает edge case когда `real_url` пуст. Добавить `if real_url and '/video/' in real_url:` (already в snippet) — это Right Thing.

## Implementation plan reference

После approval этого design'а — invoke writing-plans skill для разбиения на atomic tasks (TDD-driven). Plan будет содержать:
- Task 1: const + pure helper (red→green tests)
- Task 2: detection block в wait_upload (integration test через subset mock)
- Task 3: AI Unstuck pre-call guard (integration test)
- Task 4: post-success URL classification (event test)
- Task 5: deploy → live verify pt 4488 → 24h metric

---

**Status:** v2 ready for second-round Codex review + user review.
**Codex review history:**
- v1 → v2 applied 5 P1 + 6 P2 + 4 P3 finds (2026-05-11). Re-review pending.
