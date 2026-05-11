# TT post-publish success detection in `wait_upload` — design v1

**Date:** 2026-05-11
**Author:** Claude (session с Danil Pavlov)
**Repo:** `GenGo2/delivery-contenthunter` (autowarm publisher)
**Trigger:** Post-mortem pt 4523 (clickpay_world raspberry=9, 2026-05-10) — frame-by-frame analysis screen recording'а показал что публикация успешно состоялась в ~19:42, но `_wait_tiktok_upload` не распознал post-publish auto-навигацию TT в feed/inbox и продолжил 12 минут вызывать AI Unstuck, который случайно тапнул «+» в bottom nav, открыл Camera, и в итоге устройство улетело в Launcher (`tt_fg_lost`).

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

1. **PRIMARY:** `wait_upload` UPLOAD_OK markers (строковые, см. publisher_tiktok.py top: `UPLOAD_OK = [...]`) ищут текст на publish-screen. После реальной публикации TT auto-навигирует в feed/inbox — этих markers там нет.
2. **CASCADE:** `_cur_act_tt` guard в AI Unstuck triggering условии (`'musically' in _cur_act_tt or 'tiktok' in _cur_act_tt.lower()`) — True для всех TT-activity, включая Inbox/Feed. AI Unstuck вызван с goal «complete publishing», на Inbox screen нашёл «+» в bottom nav (это TT «Create» button), тапнул → открыл Camera.
3. **TERTIARY:** AI Unstuck inner anti-loop работает по `(action, x, y, key)` — корректно режет 3 идентичных тапа. Но caller `wait_upload` перезапускает `ai_unstuck()` снова и снова на каждой 5-й итерации wait_upload без outer-cap. 7 рестартов = 21 tap за 12 минут.

### Frequency

- `tt_fg_lost` 7 дней: 3 кейса. 1 из 3 (pt 4523) — с этим pattern. Низкая частота, **но** этот pattern представляет ситуацию «ложный fail» — публикация была, а dashboard показывает failed → operator видит fake-проблему.
- `tt_upload_confirmation_timeout` 24h: 16 (12 на raspberry=9 — все pre-music-rights-handler-ship). Часть из них может быть тот же pattern (success not detected) — backlog re-audit.

## Цель design'а

Распознавать post-publish success **до** того как AI Unstuck начнёт хаотично тапать. Закрыть PRIMARY баг.

CASCADE и TERTIARY баги (anti-loop bypass + AI Unstuck open Camera) — отдельный backlog как safety net (см. секцию «Out of scope»).

## Design

### Где меняем код

`publisher_tiktok.py:648-977` — функция `_wait_tiktok_upload` (или внутри `publish_tiktok` если не вынесено).

Loop сейчас:
```python
upload_confirmed = False
for wait in range(60):  # 60 × ~8с = ~8 мин
    time.sleep(4)
    ui = self.dump_ui()
    # ... existing checks: audio_dialog, still_on_editor, UPLOAD_OK match ...
    matched = [kw for kw in UPLOAD_OK if kw in ui]
    if matched:
        upload_confirmed = True
        break
    # ... больше checks ...
    # последняя ветка: AI Unstuck на wait%5==4
```

### Что добавляем

После `ui = self.dump_ui()` и **перед** существующими markers — новый блок activity-based success detection:

```python
# [POST-PUBLISH SUCCESS DETECTION 2026-05-11]
# After tapping "Поделиться", TT auto-navigates from publish-screen to
# feed/inbox/profile on success. Existing UPLOAD_OK markers only match
# the publish-screen text — they will never fire after auto-navigation.
# Detect success via topResumedActivity NOT in composer set + visible
# bottom-nav text markers.
#
# Skip iter 0 to allow Поделиться tap to register and TT to navigate.
if wait >= 1:
    cur_act_post = self.adb(
        'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
        timeout=8,
    ) or ''
    on_composer = any(a in cur_act_post for a in TT_COMPOSER_ACTIVITIES)
    on_tiktok = 'musically' in cur_act_post or 'tiktok' in cur_act_post.lower()
    nav_hits = sum(1 for m in TT_FEED_NAV_MARKERS if m in ui)
    if on_tiktok and not on_composer and nav_hits >= 3:
        log.info(f'  ✅ TikTok: post-publish success inferred '
                 f'(act={cur_act_post[:80]}, nav_hits={nav_hits}, wait={wait})')
        self.log_event(
            'info',
            f'TikTok: post-publish success inferred — left composer (act={cur_act_post[:60]})',
            meta={'category': 'tt_post_publish_success_inferred',
                  'platform': self.platform,
                  'wait_iteration': wait,
                  'top_activity': cur_act_post[:160],
                  'nav_hits': nav_hits},
        )
        upload_confirmed = True
        break
```

### Module-level constants (top of publisher_tiktok.py)

```python
# Activities, на которых TT находится во время composer/publish-flow.
# Если topResumedActivity содержит любой из них — НЕ считаем success'ом.
# Substring match → ловит подварианты (BaseLoginPostActivity, MusicSelectListActivity, etc).
TT_COMPOSER_ACTIVITIES = (
    'PostActivity',         # post-edit screen
    'EditActivity',          # video editor
    'PublishActivity',       # publish confirmation
    'CameraActivity',        # camera/recording (важно — куда AI Unstuck улетает)
    'PermissionActivity',    # Android permission dialogs
    'MusicSelectActivity',   # выбор музыки
    'CutVideoActivity',      # обрезка видео
    'CoverActivity',         # выбор обложки
)

# Текст-маркеры bottom nav TT main app. На composer screen их НЕТ
# (там X в углу + кнопка Поделиться, без bottom nav).
# Требуем 3 из 4 (защита от частичного match'а / А/B-теста).
TT_FEED_NAV_MARKERS = ('Главная', 'Друзья', 'Входящие', 'Профиль')
```

### Почему именно эти проверки (defensive layering)

| Layer | Что ловит | Защита от false-positive |
|---|---|---|
| `wait >= 1` (skip iter 0) | Race: dump_ui до того как tap «Поделиться» зарегистрировался | Composer screen тоже есть TT-activity — без задержки можем попасть в момент когда topResumedActivity ещё publish-screen, но UI уже имеет nav |
| `on_tiktok` | Если TT улетел в Launcher / другое app — НЕ считаем success | `tt_fg_lost` сработает позже legitimately |
| `not on_composer` | Главный признак — TT сменил activity | Substring match с blacklist'ом |
| `nav_hits >= 3` | Подтверждение через UI: bottom nav 4-tab феда видна | Защита от UI крашей где dump_ui может вернуть неполный XML |

Нужны **все 4 layer'а** одновременно. Если любой не выполнен — ждём дальше. Conservative bias: лучше ложно подождать ещё 8с, чем ложно declare success.

## Components

| Файл | Изменение |
|---|---|
| `publisher_tiktok.py` | + 2 константы (top), + ~25 строк detection блока в wait_upload loop |
| `tests/test_publisher_tt_wait_upload.py` (новый или существующий) | 4 unit теста (см. ниже) |

## Data flow

1. `publish_tiktok` → tap Поделиться → enter `_wait_tiktok_upload` loop
2. Iter 0: `wait=0`, skip detection (даём 4-8s после tap'а)
3. Iter 1: `wait=1`, detection блок
   - Если TT перешёл в feed/inbox + nav видна → `tt_post_publish_success_inferred` event + `upload_confirmed=True` + break
   - Если ещё на composer → continue к existing markers
4. Iter 2-N: повтор
5. Если ни одна итерация не зафиксировала success → existing fallback'и работают (UPLOAD_OK string match, audio dialog handler, AI Unstuck на wait%5==4)
6. Если 60 итераций без upload_confirmed → existing `tt_upload_confirmation_timeout`

## Error handling

- **No new error_code.** Это success path.
- **New event category:** `tt_post_publish_success_inferred` (`type: info`). Поля meta:
  - `category` (str): "tt_post_publish_success_inferred"
  - `platform` (str): self.platform
  - `wait_iteration` (int): wait counter value
  - `top_activity` (str): topResumedActivity output (truncated 160 chars)
  - `nav_hits` (int): сколько из 4 markers найдено
- Existing `tt_upload_confirmation_timeout` остаётся для случаев реального fail'а.

## Tests

Файл `backend/tests/test_publisher_tt_wait_upload.py` (или extend existing TT test file).

```python
# Каждый тест mock'ает self.adb (для dumpsys), self.dump_ui (для UI text),
# self.log_event (capture), self.tap_element (no-op), time.sleep (no-op).
# Subject under test — публичная или package-private функция wait_upload или
# вся publish_tiktok. Если она private — тестируем через TikTokMixin instance.

def test_wait_upload_success_inferred_when_left_composer_with_nav():
    """Wait iter 1: topResumedActivity = MainTabActivity, UI содержит 3+ nav markers
       → tt_post_publish_success_inferred event + return True."""

def test_wait_upload_keep_waiting_when_still_on_composer():
    """Wait iter 1: topResumedActivity содержит 'PostActivity' → НЕ trigger
       success, UPLOAD_OK string check продолжает работать как раньше."""

def test_wait_upload_keep_waiting_when_partial_nav_visible():
    """Wait iter 1: feed activity, но nav_hits=2 (только 2 из 4 markers) →
       НЕ trigger success (защита от частичного UI dump'а)."""

def test_wait_upload_no_success_when_left_tiktok_to_launcher():
    """Wait iter 1: topResumedActivity = launcher → НЕ trigger success
       (on_tiktok=False guard); existing tt_fg_lost path сработает позже."""
```

Все тесты — pure-mock, без реального ADB. Pattern взять из существующих `test_publisher_tt_*.py` если есть, иначе — новый файл.

## Live verification plan

1. Deploy fix → push на main → auto-pull в `/root/.openclaw/workspace-genri/autowarm/` (git hook).
2. Re-queue pt 4488 (clickpay_world same account):
   ```sql
   UPDATE publish_queue SET status='pending', publish_task_id=NULL
   WHERE id=(SELECT publish_queue_id FROM publish_tasks WHERE id=4488);
   ```
3. Через 5-10 мин: проверить новый pt:
   ```sql
   SELECT id, account, status, error_code,
          jsonb_array_length(events) AS n_events,
          (SELECT COUNT(*) FROM jsonb_array_elements(events) e
           WHERE e->'meta'->>'category'='tt_post_publish_success_inferred') AS success_inferred_count,
          (SELECT MAX((e->'meta'->>'wait_iteration')::int) FROM jsonb_array_elements(events) e
           WHERE e->'meta'->>'category'='tt_post_publish_success_inferred') AS detect_at_wait
   FROM publish_tasks
   WHERE account='clickpay_world' AND created_at > NOW() - INTERVAL '15 min';
   ```
4. Expected:
   - `status = awaiting_url`
   - `success_inferred_count = 1`
   - `detect_at_wait` ≤ 5 (success в первые ~24 секунды после Поделиться)
   - Total task time ≤ 90s vs текущие 12+ мин
5. Если live ОК — measure 7-day metric:
   ```sql
   SELECT COUNT(*) AS detected_per_week
   FROM publish_tasks
   WHERE platform='tiktok'
     AND updated_at >= NOW() - INTERVAL '7 days'
     AND events @> '[{"meta":{"category":"tt_post_publish_success_inferred"}}]'::jsonb;
   ```
   Это число — публикации, которые без fix'а превратились бы в timeout/fg_lost.

## Risks

| Риск | Вероятность | Impact | Mitigation |
|---|---|---|---|
| **False positive — TT показывает feed-нав ДО реальной публикации** (e.g. composer crash → fallback) | Низкая | Publisher запишет success, real network upload не дойдёт → пост не появится у пользователя, но dashboard покажет «awaiting_url» (ждёт URL который не придёт) | `_auto_get_tiktok_url(wait_secs=45)` уже handle'ит timeout: возвращает profile fallback URL. Не critical fail. Можно добавить post-success URL polling с явным timeout-и-mark-failed если совсем нет /video/<id> URL. **Defer** до evidence в live. |
| **TT UI evolution: activity названия меняются** | Средняя (TT агрессивно А/B-тестирует) | False negative: detection не сработает, поведение = baseline (текущее) | Substring match даёт slack. Periodic audit: смотреть `top_activity` field в `tt_post_publish_success_inferred` events на новых версиях TT |
| **TT bottom nav текст меняется** (А/B локализация) | Средняя | False negative | nav_hits≥3 из 4 даёт slack. Можно добавить англ. варианты ('Home', 'Friends', 'Inbox', 'Profile') |
| **Race condition в iter 1** — между tap'ом Поделиться и dump'ом TT не успел сменить activity, но nav markers уже подгрузились | Низкая | False positive | `wait >= 1` + проверка activity (не только UI) — двойная защита. iter 0 skip даёт 4s buffer (sleep при entry в loop) |
| **dumpsys overhead** ~50-200ms × 60 итераций = 3-12s extra per task | Низкая | Slowdown | Acceptable: existing AI Unstuck path тоже вызывает dumpsys. Net win: success detection экономит 8+ минут when triggered |

## Out of scope (отдельный backlog)

1. **AI Unstuck outer-cap для TT** (cascade fix, был v1 design) — оставляем как safety net на случай если success detection не сработал (TT UI changed). Низкий приоритет: если primary fix снимет 90% кейсов, secondary не критичен. Backlog tag: `ai-unstuck-outer-cap-tt`.

2. **AI Unstuck composer-screen guard** — добавить проверку «если попали на CameraActivity / PostActivity → не вызывать AI Unstuck вообще, потому что мы уже промахнулись с публикации». Этот fix предотвратит cascade в Camera. Backlog: `ai-unstuck-composer-screen-skip`.

3. **AI Unstuck reason-rephrasing anti-loop bypass** — anti-loop key из `(action, x, y, key)` дополнить `(intent_hash или global N-tap cap regardless of reason)`. Backlog: `ai-unstuck-reason-rephrasing`.

4. **Re-audit `tt_upload_confirmation_timeout` history** на subset кейсов с тем же pattern (publication actually succeeded but not detected). Если пропорция большая — приоритезировать deploy success-detection. Discovery, не код.

## Open questions for review

1. **Activity blacklist completeness:** мы перечислили 8 composer-related activities. Есть ли более авторитетный источник (TT release notes / decompiled APK / manual screen tour)? **Решение:** начать с этого списка + `top_activity` логирование позволит расширять по мере evidence в проде.

2. **wait threshold** = 1 (skip iter 0). Достаточно ли 4s? Если TT долго навигирует — может быть не успеть. **Решение:** conservative `wait >= 1` (то есть с 8s после entry). Если live evidence покажет miss'ы — поднять до `wait >= 2`.

3. **Тест coverage:** покрываем 4 кейса. Достаточно? **Решение:** пока да; добавим cases по live evidence.

## Implementation plan reference

После approval этого design'а — invoke writing-plans skill для разбиения на atomic tasks (TDD-driven).

---

**Status:** v1 ready for Codex review + user review.
