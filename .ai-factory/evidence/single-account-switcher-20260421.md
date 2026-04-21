# Single-account switcher short-circuit — evidence (2026-04-21)

**План:** `.ai-factory/plans/single-account-switcher-shortcircuit-20260421.md`
**Репо:** `/home/claude-user/autowarm-testbench/` (branch `testbench`)
**Commit SHA:** `6eb806a` — `feat(switcher): single-account short-circuit + Cyrillic username regex`
**Restart:** `sudo -n pm2 restart autowarm-testbench` выполнен 2026-04-21 ~15:29 UTC (uptime 12m на момент проверки, 15:41 UTC).
**Тесты:** 157 passed (+15 new, 1 skipped). `tests/test_single_account_preflight.py` — 9 кейсов preflight. `tests/test_account_switcher.py` — +6 SA-mode кейсов + Cyrillic regex.

## Before-rate (24h — 2h до deploy, testbench=true)

Window: `NOW() - INTERVAL '26 hours'` .. `NOW() - INTERVAL '2 hours'`.

```
          error_code           | count
-------------------------------+-------
 adb_push_chunked_failed       |    10   ← вне скоупа (ADB сеть)
 adb_push_chunked_md5_mismatch |     8   ← вне скоупа (ADB сеть)
 unknown                       |     5
 yt_accounts_btn_missing       |     2   ★ target
 tt_bottomsheet_closed         |     1   ★ target
```

Плюс (чуть ранее, после 14:00 UTC, 2h-window):

```
 tt_profile_tab_broken         |     1   ★ target (task #551, 14:14 UTC)
```

`★` — именно те ошибки, которые SA-fastpath / SA-degraded должны устранить на phone #19.

## After-rate (первые ~12 минут после deploy, 15:29—15:41 UTC)

```
 status |       error_code        | count
--------+-------------------------+-------
 failed | adb_push_chunked_failed |     3  (вне скоупа, hop4 packet loss)
 failed | yt_app_launch_failed    |     3  (приложение не запустилось — до switcher'а)
 failed | ig_camera_open_failed   |     2  (пост-switcher; известная отдельная регрессия)
 failed | unknown                 |     1  (pre-deploy task #557 дотикала)
 failed | tt_bottomsheet_closed   |     1  (task #554, pre-deploy 14:45 UTC)
 failed | publish_failed_generic  |     1
 failed | tt_profile_tab_broken   |     1  (task #551, pre-deploy 14:14 UTC)
```

Фактически post-deploy задачи:
- **#558** (YouTube, target=`Инакент-т2щ`) — 15:24 UTC, picked up после restart.
- **#559** (Instagram, target=`inakent06`) — 15:34 UTC, полностью post-deploy.

Остальные строки таблицы — задачи ДО restart (#551, #554, #556, #557), попавшие в 2h-окно по created_at.

## SA event-traces

### IG — task #559 (success SA-fastpath, `final_step=ig_sa_fastpath`)

Events (`account_switch.meta.category`):

```
15:35:12  sa_preflight  known=[inakent06]  platform=Instagram  single_account=true
15:35:12  account_switch  preflight single_account=True known=inakent06
15:35:34  ui_dump  label=ig_1_feed  usable=false
15:35:52  ui_dump  label=ig_2_profile_tab_fg_guard  usable=false
15:36:04  ui_dump  label=ig_2_profile_tab  usable=false
15:36:13  ui_dump  label=ig_3_profile_screen  usable=false
15:36:23  sa_fastpath  current_read=""  single_account=true
15:36:32  ui_dump  label=ig_sa_fastpath  usable=false
15:36:39  ok  step=ig_sa_fastpath  matched=true
15:36:39  done  matched=true  final=ig_sa_fastpath  dumps=5
```

Лог-подтверждение:

```
15:35:12 [INFO] [SA-preflight] task=#559 serial=RF8YA0W57EP platform=Instagram
         target='inakent06' known=['inakent06'] single_account=True
15:35:12 [INFO] [switcher] SA-hint: platform=Instagram target='inakent06' enabled=True
15:36:23 [INFO] [switcher] IG SA-fastpath: assuming current=target,
         skipping list-open (current_read=None)
15:36:39 [INFO] ✅ account OK: inakent06 (matched=True, final=ig_sa_fastpath)
```

→ switcher завершился успехом, несмотря на полный провал чтения current (все UI dumps `usable=false`). Последующий `ig_camera_open_failed` — уже пост-switcher регрессия камеры (известный отдельный кейс, в других задачах тоже есть).

### YT — task #558 (SA-preflight сработал; switcher не вызывался — app не запустился)

Events:

```
15:31:23  sa_preflight  known=[инакент-т2щ]  platform=YouTube  single_account=true
15:31:23  account_switch  preflight single_account=True known=инакент-т2щ
15:32:05  ui_dump  label=yt_1_feed  usable=true
→ yt_app_launch_failed (до switcher-branch)
```

Лог подтверждает Cyrillic-нормализацию: `target='Инакент-т2щ' known=['инакент-т2щ']` — regex `\w` + UNICODE распознал Cyrillic+дефис, `_normalize_username` корректно сматчил target.

### TT — task #554 (BEFORE deploy, для сравнения)

Pre-deploy trace (14:45—14:47 UTC) — демонстрирует починяемое поведение:

```
14:45:28  tt_1_feed
14:45:51  ui_dump  tt_1_feed  usable=true
14:46:11  ui_dump  tt_2_profile_tab_fg_guard  usable=true    (retap 1)
14:46:27  ui_dump  tt_2_profile_tab  usable=true            (retap 2)
14:46:41  ui_dump  tt_2_profile_screen  usable=true
14:46:53  ui_dump  tt_3_open_list  usable=true              ← list не открылся
14:47:09  ui_dump  tt_3_open_list_retry1  usable=true       ← retry тоже провалился
14:47:21  FAIL  step=tt_3_open_list  error_code=tt_bottomsheet_closed
```

Сейчас этот путь обрывается: при `single_account_mode=True` после provalа retap-loop'а switcher идёт в `tt_sa_degraded` fallback (tap+verify на текущем экране) вместо `_fail()`.

## Cyrillic regex verify (in-log)

```
15:31:23 target='Инакент-т2щ' known=['инакент-т2щ']  ← regex matched
15:35:12 target='inakent06'   known=['inakent06']     ← regression OK
```

Pre-fix: `_looks_like_username('Инакент-т2щ')` → False (ASCII-only regex) → SA-hint не включился бы. Post-fix: matched и нормализован до lowercase.

## Dashboard / classifier

- `analytics_collector_v2.py`: SA-события приходят с `type=account_switch` (не `error`), classifier их игнорирует — успешные switch'и не попадают в counters как failures. ✅
- `triage_classifier.py` (commit 6eb806a): добавлены комментарии к правилам `tt_bottomsheet_closed` / `yt_accounts_btn_missing` / `tt_profile_tab_broken` — «после 6eb806a часть случаев отфильтровывается upstream в switcher'е; если код залетает — это реальный logout или switcher-break, приоритет выше».
- `testbench.html` — TODO: бейдж `sa_fastpath` / `sa_degraded_fallback` (отдельный мелкий PR; не блокирует закрытие плана).

## Ожидания по error_code (2-часовое окно после накопления 5-10 задач)

| error_code | до | ожидание после | механизм |
|---|---|---|---|
| `tt_bottomsheet_closed` | 1/24h | 0 | SA-degraded → `tt_sa_degraded` |
| `yt_accounts_btn_missing` | 2/24h | 0 | SA-fastpath → `yt_sa_fastpath` |
| `tt_profile_tab_broken` | 1/24h | 0 | SA-degraded после retap-loop |
| `adb_push_chunked_*` | 18/24h | без изменений | ADB-скоуп, отдельно |
| `ig_camera_open_failed` | 1/24h | без изменений (возможен рост visibility) | пост-switcher регрессия |
| `yt_app_launch_failed` | 2/24h | без изменений | до switcher'а |

## Rollback-критерий

Не сработал. Из 2-х post-deploy задач (#558, #559) — 0 регрессий switcher'а: обе корректно выполнили preflight, #559 дошла до SA-fastpath success. `tt_bottomsheet_closed` / `yt_accounts_btn_missing` / `tt_profile_tab_broken` в post-deploy окне не наблюдались (но sample слишком мал — 2 задачи). Продолжить наблюдение 1-2 часа; если пик, откатить:

```bash
cd /home/claude-user/autowarm-testbench
git revert 6eb806a --no-edit
git push origin testbench
sudo -n pm2 restart autowarm-testbench
```

## Статус

**T1-T6:** ✅ реализованы и задеплоены в commit `6eb806a`.
**T7:** ✅ initial smoke (2 post-deploy задачи), SA-preflight/fastpath наблюдаются в логах, Cyrillic-нормализация подтверждена, evidence зафиксировано. Расширенное 2h-окно — пассивно (5-10 задач за час).
**T8:** ✅ memory + PLAN.md обновлены.

Повторная проверка через 1-2 часа (после ~10 задач): SQL выше + grep `sa_fastpath|sa_degraded` в pm2 logs. Если `tt_bottomsheet_closed` / `yt_accounts_btn_missing` / `tt_profile_tab_broken` остаются в нулях — план закрыт окончательно.
