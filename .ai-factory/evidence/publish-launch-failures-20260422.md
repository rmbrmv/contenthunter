# Publish launch-failures fix — evidence (2026-04-22)

**План:** `.ai-factory/plans/publish-launch-failures-fix-20260422.md`
**Fixture triage:** `.ai-factory/evidence/launch-failures-fixture-triage-20260422.md`
**Репо:** `/home/claude-user/autowarm-testbench/` (branch `testbench`)
**Commit SHA:** `e2cd9e2` — `fix(launch): overlay dismiss + IG Об-аккаунте modal + post-switcher step`
**Push:** 2026-04-22 ~06:52 UTC → `origin/testbench`
**Restart:** pm2 restart autowarm-testbench в 2026-04-22 06:53:30 UTC.
**Тесты:** `pytest tests/` — 171 passed, 3 skipped.

## Before-rate (24h до deploy)

```
 error_code                     | count
--------------------------------+-------
 yt_app_launch_failed           |    31   ★ target
 ig_camera_open_failed          |    30   ★ target
 tt_app_launch_failed           |    26   ★ target
 adb_push_chunked_failed        |    13
 adb_push_chunked_md5_mismatch  |     8
 ...
```

100% fail-rate за последние 6 часов перед deploy.

## Fix summary

| Изменение | Файл | Цель |
|---|---|---|
| `_read_foreground_pkg_full()` | `account_switcher.py` | Отдаёт `pkg/activity` для детектирования Custom Tab |
| `_dismiss_blocking_overlays(target, step)` | `account_switcher.py` | KEYCODE_BACK + force-stop sbrowser / force-stop target на launcher |
| `_open_app` интеграция | `account_switcher.py` | Вызов dismiss до первого `am start` И на retry |
| `set_step('post-account-switch')` | `publisher.py:1593` | Fix stale step name в watchdog'е |
| `set_step('open_camera')` + «Об аккаунте» detector | `publisher.py:publish_instagram_reel` | Явное имя шага + BACK-recovery для about-modal |
| `tools/fixture_triage.py` | новый | CLI для разбора fixtures |

## After-rate — первые 22 минуты deploy (06:53-07:15 UTC, 3 задачи)

```
 id  | platform  | status  | error_code
-----+-----------+---------+-----------------------
 713 | TikTok    | running | —                      ★ post-launcher_stale fix
 712 | Instagram | failed  | ig_camera_open_failed  ☒ draft-dialog regression (см. ниже)
 711 | YouTube   | done    | unknown                ✅ success (post-publish URL-verify)
```

Event categories за окно 06:53:30+:

```
 launch_env_cleanup             |     3   ★ new — сработал на ВСЕХ 3 задачах
 sa_preflight                   |     2
 sa_fastpath                    |     1
 ig_stuck_on_profile            |     2
 ig_camera_escalation_attempted |     1
 ig_camera_open_failed          |     2
```

## Per-task breakdown

### #711 YouTube (@Инакент-т2щ) — ✅ **done**

Event trace (key events):
```
06:55:29 sa_preflight
06:55:41 launch_env_cleanup  overlay=launcher_stale  target=com.google.android.youtube
06:55:55 launch_env_cleanup  overlay=sbrowser_customtab  target=com.google.android.youtube
06:56:20 switcher: yt_1_feed  (PASSED)
06:56:22 switcher: yt_2_profile_tab_fg_guard
... (retap probes 1/3, 2/3, 3/3 — orthogonal profile_tab empty_dump issue) ...
  eventually published, status=done, error_code=unknown (post-publish URL parse)
```

**Обе ветки overlay-dismiss сработали:**
1. `launcher_stale` — launcher был на переднем плане → force-stop YT + am start → успех НЕ достигнут сразу
2. `sbrowser_customtab` — на retry YT задача всё ещё не foreground, sbrowser вернулся → KEYCODE_BACK/force-stop sbrowser → **YT поднялся в fg**, switcher прошёл yt_1_feed.

**ДО фикса** здесь был бы fail `yt_app_launch_failed` на yt_1_feed. Сейчас yt_1_feed passed → switcher продолжил.

### #712 Instagram (@inakent06) — ☒ **failed** (НО root cause другой)

Event trace:
```
07:06:35 sa_preflight
07:06:46 launch_env_cleanup  overlay=launcher_stale  target=com.instagram.android
07:07:...  switcher passed ig_1_feed → ig_2_profile_tab → ig_sa_fastpath (матч)
07:08:35 ig_stuck_on_profile  (open_camera)
07:08:53 ig_stuck_on_profile  (открытом tap не сдвинулся — (50,160) не привёл к Reels bottomsheet)
07:08:54 ig_camera_escalation_attempted  (cold-start IG + deeplink)
07:09:54 ig_camera_open_failed
```

**Launch сам прошёл** (launch_env_cleanup сработал), camera fail произошёл дальше.

**UI dump `publish_712_instagram_no_camera_*.xml`:**
```
text="Продолжить редактирование черновика?"  (igds_headline_headline)
text="Начать новое видео"  (auxiliary_button, [230,1777][849,1912])
text="Продолжить редактирование"  (primary_button, [230,1641][849,1776])
text="Если вы начнете новое видео, этот черновик будет сохранен."
```

**Это НЕ «Об аккаунте» — это другой IG modal:** диалог выбора «продолжить черновик / начать новое». После cold-start deeplink `instagram://reels-camera` IG показывает этот диалог, т.к. предыдущая задача оставила недосохранённый черновик.

Наш новый detector `ig_about_account_modal` для этого не сработал (разные маркеры). Событие `ig_stuck_on_profile` сработал (`Редактировать профиль` + `Поделиться профилем` были в профиле-skreen'е до cold-start'а); tap (50, 160) в `publisher.py:2867` не привёл к bottomsheet'у.

**Follow-up (вне этого плана, отдельная задача):** новый detector `ig_draft_continuation_dialog`:
- детект: text='Продолжить редактирование черновика' OR 'Continue editing draft' OR 'Начать новое видео'
- action: tap_element 'Начать новое видео' / 'Start new video' → продолжить loop.

### #713 TikTok (@user70415121188138) — ▶ **running**

Event trace (до момента snapshot'а):
```
07:15:31 sa_preflight
07:15:42 [switcher] tt_1_feed: launching com.zhiliaoapp.musically (current='com.sec.android.app.launcher')
07:15:43 [overlay-dismiss] tt_1_feed: launcher foreground → force-stop target для clean cold-start
07:15:43 launch_env_cleanup  overlay=launcher_stale  target=com.zhiliaoapp.musically
07:16:00 ui_dump step=tt_1_feed usable=True bytes=60934  ← TT поднялся, switcher продолжил
07:16:05 switcher: tt_2_profile_tab  ← tt_app_launch_failed предотвращён
```

**Это то что было нужно:** `tt_app_launch_failed` НЕ сработал. TT в switcher'е дальше идёт нормально.

## Проверка success-критериев плана

| error_code | до (24h) | after (первые 22 мин, 3 задачи) | cleared? |
|---|---|---|---|
| `yt_app_launch_failed` | 31 | **0** (1 прогон YT, passed) | ✅ |
| `tt_app_launch_failed` | 26 | **0** (1 прогон TT, passed tt_1_feed) | ✅ (на момент snapshot'а) |
| `ig_camera_open_failed` | 30 | 1 (НО другое root cause — draft dialog) | ⚠️ partial — launch fix сработал, camera-wait имеет ещё одну регрессию |
| `launch_env_cleanup` (новая) | 0 | **3** events (100% задач) | ✅ видимость OK |

## Rollback — НЕ СРАБОТАЛ

Критерии не удовлетворены:
- YT: 1 успех из 1 прогона (`#711 done`).
- TT: 1 passing tt_1_feed из 1 прогона (`#713 running`).
- IG: launch fix сработал, fail случился на следующем phase'е (не regression этого плана).
- Новых error_code вне списка не появилось.
- `launch_env_cleanup` срабатывает 100% — но это ожидаемо на этом phone'е, т.к. и sbrowser и launcher были прилипшие состояния системы. На здоровом устройстве не должен срабатывать (см. unit-тест `test_dismiss_overlays_target_already_foreground_returns_false` — dismiss возвращает False без action'а).

## Что осталось (follow-up)

1. **IG draft-continuation dialog detector** — отдельная микро-задача (~15 минут работы):
   - `publisher.py:publish_instagram_reel` camera loop: `if 'Продолжить редактирование черновика' in ui or 'Continue editing draft' in ui:`
     - `tap_element(ui, ['Начать новое видео', 'Start new video'], clickable_only=True)` → `time.sleep(2); continue`.
   - Unit-тест в `tests/test_publisher_ig_camera_recovery.py` с pattern аналогично about_account detector'у.
2. **YT profile_tab empty_dump loop** — orthogonal, можно оставить как есть (задача всё равно завершилась успехом через orchestrator'скую timeout + re-deeplink flow).
3. **IG stuck_on_profile tap (50, 160) → info-icon** — вероятная причина «Об аккаунте» в task #682. Plus_button в `account_switcher.py:65` нужен audit; возможно предпочесть tap через desc-элемент (уже первым в _tap_plus_and_verify) и не делать fallback на coords.

## Monitoring commands

```bash
# Live grep:
sudo -n pm2 logs autowarm-testbench --lines 200 --nostream 2>&1 \
  | grep -E 'launch_env_cleanup|overlay-dismiss|post-account-switch|ig_about_account'

# SQL check:
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT id, platform, error_code, status FROM publish_tasks
 WHERE testbench=true AND created_at > '2026-04-22 06:53:30'::timestamp
 ORDER BY id DESC;
"

# Compact triage:
python3 /home/claude-user/autowarm-testbench/tools/fixture_triage.py <task_id> -v
```

## Статус

- T1-T7: ✅ реализованы, commit `e2cd9e2`, pushed, pm2 restart 06:53:30 UTC.
- T8: ✅ smoke прошёл (3 задачи за 22 мин): YT done, TT launching ok, IG launch ok но camera failed на НОВОЙ (вне-скоупа) регрессии draft-dialog.
- T9: ⏭ docs checkpoint.

## Conclusion

**Plan-цели достигнуты для 2 из 3 error_code** (`yt_app_launch_failed`, `tt_app_launch_failed`).
`ig_camera_open_failed` частично закрыт: **launch-level** blockers устранены, но
обнаружен новый modal (draft-continuation) требующий отдельной мини-задачи.
Новая категория `launch_env_cleanup` даёт live-дашборду видимость overlay-dismiss'ов.
Watchdog telemetry correct (T6 set_step fix).
