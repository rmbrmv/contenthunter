# Backlog tickets

## 2026-05-19 — IG: ig_app_launch_failed stale-uiautomator (WP #105)

### ✅ SHIPPED 2026-05-19 PR #76 (`f480219`)

Триаж IG-фейлов 7д (2026-05-12…2026-05-19) выявил топ-1 непокрытый класс `ig_app_launch_failed` — 14 fails/7д, 3 fails сегодня, 13 уникальных устройств на ВСЕХ 6 raspberries (Pi #2/3/5/7/9/10). Топ-1 (`ig_share_tap_no_progress`, WP #73), топ-3 (`ig_target_not_in_picker`, WP #102) уже в backlog'е; топ-2 (`ig_picker_wrong_candidate`, WP #61) и топ-6 (`ig_gallery_no_video_candidate`, WP #61/#68) уже Готово — 0 свежих fails после 2026-05-14/15 это подтверждает.

**Root cause (13/13 fails 7д):** два метода foreground detection используют разные источники. `_ensure_app_foregrounded` (pre-check) видит IG через `dumpsys topResumedActivity` и эмитит `ig_app_foregrounded_after_recovery: attempt=2` (success). Immediately после — `_open_app._foreground_pkg` использует `uiautomator dump` как primary; на Samsung S21 uiautomator отстаёт до 60-90s после `am start` — видит `com.sec.android.app.launcher` пока ActivityManager уже знает что IG в foreground. 3 am-start retries не помогают (IG уже запущен, uiautomator всё ещё stale). `_open_app` fails через 86s. Скриншот +1s после fail показывает IG на экране (task 7821 clickpay_now + task 7692 contentexpert_ — оба evidence-tasks 2026-05-19).

**Решение — defense-in-depth в `account_switcher.py:_open_app` (PR GenGo2/delivery-contenthunter#76, squash `f480219`):**

- **L1** `_foreground_pkg(target_pkg)` — cross-source check (dumpsys + uiautomator). Trust target когда `pkg_ui==target` (UI ground-truth) ИЛИ `pkg_dump==target && pkg_ui ∈ {launcher, empty}` с подтверждающим poll'ом до 2.4s. Для permission/sbrowser overlay возвращается uiautomator package — `_dismiss_blocking_overlays` отрабатывает (НЕ short-circuit на real overlay).
- **L2** Settle-wait до 15s polling после 3 am-start attempts — ловит race «IG arrives 1-5s после last poll».
- **L3** Observability: `switcher_foreground_pkg_disagree` event при расхождении источников + `current_pkg_dumpsys` в meta при final fail.

Codex review: **3 round'а до 0 P1/P2** (правки confirming-poll + permissioncontroller-safety из round 2/3). 7 новых mock-based тестов + 1 update в test_overlay_dismiss (cross-source меняет dumpsys call count). 74 теста зелёные в test_account_switcher + test_overlay_dismiss. Pre-existing main фейлы (vision/orchestrator/publish_guard/intermediate_probes) НЕ затронуты — verified `git stash` reproduction.

Deploy: PR #76 squash-merged 2026-05-19 11:46 UTC, prod автоматически синкнулся через git pull (f480219). PM2 restart НЕ требовался — Python публикатор spawnится свежим процессом на каждую задачу (server.js spawn).

**Метрики после deploy (T+217min, 5 IG задач):**
- `ig_app_launch_failed` fails post-deploy: **0** ✅ (vs baseline ~2/день)
- `switcher_foreground_pkg_disagree` events (L1): **1** ✅ proof-of-life (cross-source ловит реальное расхождение в проде)
- `switcher_settle_wait_recovered` events (L2): 0 (паттерн отлавливается L1 раньше — норма)
- Other post-deploy fails: 3 (camera/caption/picker — другие классы, не наш WP)

Verification window incomplete на момент закрытия — выкладочное окно сегодня закрылось в 12:00 UTC (publish_queue пуст), для статистики нужен следующий утренний цикл ~04-09 UTC. WP #105 в OpenProject — статус «Тестирование», переход в «Готово» после 24h positive verification.

Spec/plan/evidence: `docs/superpowers/specs/2026-05-19-wp105-ig-app-launch-stale-uiautomator-design.md` + `docs/superpowers/plans/2026-05-19-wp105-ig-app-launch-stale-uiautomator-plan.md` + `docs/evidence/2026-05-19-wp105-ig-app-launch-shipped.md`. OpenProject WP #105 (assignee Данил, comment id 282).

Memory: [[project_wp105_ig_app_launch_stale_uiautomator_shipped]].

### Связанные открытые WP

- **WP #73** `ig_share_tap_no_progress` (31 fails/7д, 5 сегодня) — топ-1 IG, в backlog'е, refresh-комментарий 2026-05-19 запостил
- **WP #102** `ig_target_not_in_picker` (19 fails/7д) — в backlog'е
- **WP #8** `ig_camera_open_failed` (8 fails/7д) — нет WP, низкий приоритет, не покрыт текущим фиксом
- **WP #74 Round 2** YT foreign-foreground guard — концептуально близкая защита pattern shipped 2026-05-18 PR #72

---

## 2026-05-18 — YT foreign-foreground guard (WP #74 Round 2)

### ✅ SHIPPED 2026-05-18 PR #72 (`c9f75d5`)

Round 1 (PR #64, 15.05) закрыл 2/2 исходных кейса `yt_gallery_no_video_candidate`. 18.05 task 6899 (axilorj_ewelry, raspberry 1) поймал новый класс: **`ForceLoginSamungAccountActivity` (Samsung Galaxy Store)** перехватил foreground после `_normalize_yt_state_pre_upload` — force-stop YT тут бессилен, это чужой пакет (`com.sec.android.app.samsungapps`, не `com.google.android.youtube`). Force-stop YT убирает только наш собственный процесс; foreign overlay/activity остаётся и блокирует gallery probe → fail-fast.

PR GenGo2/delivery-contenthunter#72 (squash `c9f75d5`): 11 atomic TDD-коммитов через subagent-driven-development. **Helper-функция** `_parse_top_resumed_activity` (module-level regex `r'topResumedActivity=ActivityRecord\{[^}]*?\s+([\w.]+)/([^\s/}]+)'` + `lstrip('.')`) — Task 1. **Skeleton** `_dismiss_foreign_foreground(*, source, allow_recovery=True)` с probe → allowlist check — Task 2. **Kill-switch** env-flag `YT_FOREIGN_FOREGROUND_GUARD_DISABLE=1` + `allow_recovery=False` — Task 3. **Escalation (a)** skip-tap (UI dump + tap по skip-keys) + helpers `_foreign_reprobe`, `_emit_foreign_foreground_outcome` — Task 4. **Escalation (b)** BACK×2 с re-probe между шагами — Task 5. **Escalation (c)** force-stop foreign + relaunch YT с blocklist halt для системных пакетов — Task 6. **Checkpoint #1** в хвост `_normalize_yt_state_pre_upload` (non-blocking) — Task 7. **Checkpoint #2** перед fail-fast в `_select_gallery_video` с 1-уровневой retry-рекурсией (`_foreign_retry_left` keyword param default=1) + meta enrichment — Task 8.

Allowlist (не считается foreign): `com.google.android.youtube{,.tv}`, `com.{android,google.android,samsung.android}.permissioncontroller`. Blocklist (no force-stop даже если foreground): `android`, `com.android.{systemui,settings}`, `com.google.android.{gms,packageinstaller}`. Зонтичный `error_code = yt_gallery_no_video_candidate` СОХРАНЁН для дашбордов; 7 новых meta-категорий (`yt_foreign_foreground_detected/recovered/unrecoverable/unrecoverable_blocklist/guard_disabled/probe_failed` + `yt_gallery_retry_after_foreign_recovery`).

12 unit + 4 integration = 16 новых тестов, 36/36 YT-suite зелёные. Codex review — 0 P1. Pre-merge live smoke на real testbench device (RF8Y80ZTVFZ через raspberry 1): real-world dumpsys корректно парсится (4/4 devices), Settings как foreign успешно triggers BACK×2 + blocklist halt (Settings в BLOCKLIST → halt без force-stop), event emission цепочка validated.

Prod deploy: PR squash-merged 18:31 UTC, `git pull origin main` в `/root/.openclaw/workspace-genri/autowarm/`, `sudo pm2 restart 34 autowarm` (uptime 0s, online). OpenProject WP #74 → Тестирование (id 9), comment id 266.

**24h live verify deadline ~2026-05-19 18:40 UTC** — acceptance:
1. Любой `yt_gallery_no_video_candidate` с `meta.foreign_foreground_recovered=true` → guard живой (success path сработал).
2. Любой `yt_gallery_no_video_candidate` БЕЗ `meta.foreign_foreground_detected` → старый класс фейлов (gallery не открылась) — НЕ регрессия от guard'а.
3. `meta.foreign_foreground_unrecoverable_reason='still_foreign'` — повторений 0 при ненулевом потоке YT-задач.

OpenProject WP #74, memory: [[project_yt_foreign_foreground_guard_shipped]]. Spec/plan/evidence: `docs/superpowers/specs/2026-05-18-yt-foreign-foreground-guard-design.md` + `docs/superpowers/plans/2026-05-18-yt-foreign-foreground-guard-plan.md` + `docs/evidence/2026-05-18-wp74-round2-smoke.md`.

### Открытые follow-up'ы

- **Launcher blocklist** (low priority, не блокер для verify): добавить `com.sec.android.app.launcher` (Samsung Home), `com.android.launcher`, `com.android.launcher3`, `com.google.android.apps.nexuslauncher` в `FOREIGN_FORCE_STOP_BLOCKLIST`. Symmetry с другими system pkgs (settings уже в blocklist). В pre-merge smoke Samsung Home выявлен как foreign — force-stop launcher технически работает (Android респавнит instantly), но heavy-handed. Стоимость: ~5 LOC + 1 тест. Можно отдельным mini-PR после verify.

---

## 2026-05-18 — Publish: задачи зависают в `awaiting_url` (WP #86)

### ✅ COMPLETE 2026-05-18 — 3 PRs SHIPPED (`d68b285` + `5e6c3b3` + `701d213`)

После успешной публикации задачи зависали в `awaiting_url` пока 48ч-timeout не сбрасывал их в `failed` (псевдо-провал, публикация-то прошла). Snapshot 2026-05-18 14:02 UTC: **45 stuck** (IG 27/TT 12/YT 6); за 24ч **0 задач** закрылись `done` с profile URL'ом — terminal-перехода для «опубликовано без specific URL» не существовало. 3 root cause: poller сломан (LIMIT 30 starvation новых задач + NULL `started_at` zombies + per-task budget отсутствовал) + однопроходная capture-механика (`_auto_get_*_url(45)`) + нет terminal-статуса для exhausted.

Решение — **β phased rollout 3 PR'а** (spec в `docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md`):

**PR1 foundation** (PR GenGo2/delivery-contenthunter#71, squash `d68b285`): schema migration (`url_capture_attempts INT`, `pre_publish_video_ids JSONB`, `url_capture_last_attempt_at TIMESTAMP` + partial index `idx_publish_tasks_status_updated WHERE status IN (processing, awaiting_url)`); url-poller fix (`LIMIT 30→100 env-driven`, `ORDER BY started_at→updated_at ASC` для fairness, `COALESCE(started_at, updated_at)` в 48ч timeout для NULL-zombie); attempts++ + промоут в новый terminal-статус `published_no_url` при `attempts >= URL_CAPTURE_MAX_ATTEMPTS` (default 30 = ~1ч); `syncQueueStatuses: published_no_url → pq.status='done'` (не `failed`, иначе re-queue → дубль публикации); жёлтый badge `✅ Без URL` в 4 publish_tasks renderers + status-filter dropdown + `pub-stat-done` counter; retroactive-cleanup миграция `20260518_wp86_retroactive_cleanup.sql` (15 stuck задач промоутнуто, publish_queue симметрично в `done`). Pure-helpers `shouldPromoteToPublishedNoUrl` + `getUrlPollerLimit` + `getUrlCaptureMaxAttempts` экспорт'нуты для tests (TDD, 17→23 unit tests). Subagent-driven dev через 18 tasks; codex/code-quality review нашёл 5 Important fixes + 2 dead-code reverts (audit lesson: `grep status='done'` находит hits на 3 разных таблицах — autowarm_tasks/publish_tasks/publish_queue — verify FROM-clause обязателен).

**PR3 server-side** (PR #73, squash `5e6c3b3`): A3 YouTube Data API через `scripts/yt_data_api_query.py` (Python CLI wrapper над `analytics_collector.youtube_api_get_videos`, exit code 2 на quota/403 → graceful fallback на yt-dlp); A5 differential id-diff — bot до publish сохраняет top-5 video-id'ов в `pre_publish_video_ids` JSONB (через `_snapshot_pre_publish_video_ids` helper в publisher_base, вызывается из TT+YT publishers), poller через `scrapeAllVideosDiff` pure-helper делает `current_ids - pre_snapshot - other_used = новые id`. Kill-switches `URL_CAPTURE_USE_YT_API=0`, `URL_CAPTURE_USE_DIFF=0`. 5 commits, 9 новых pytest + 5 unit tests JS, npm 150/150 pass. **Адаптация:** `youtube_api_get_videos` в analytics_collector возвращает только statistics — wrapper использует `playlistItems` endpoint напрямую (2 API calls).

**PR2 bot-side** (PR #74, squash `701d213`): A1 wave-retry для TT (3×45s с pull-to-refresh между waves, early-exit на specific URL через `_is_specific_reel_url`) — replaces single 45s attempt; A2 `_capture_via_notifications` helper (universal для TT+IG) через `adb shell dumpsys notification --noredact` + parse + foreign-account guard. **DONE_WITH_CONCERNS:** recon на тест-телефонах показал что TT/IG/YT **НЕ embed URL в text-полях** dumpsys notification — URL в PendingIntent (opaque для shell). A2 в текущем prod возвращает `None` для всех 3 платформ. Infra оставлена (~0.5s/publish overhead) с kill-switch `URL_CAPTURE_USE_NOTIF=0` + активируется автоматом если platform начнёт embed URL в notification text. **Реальная ценность PR2 = A1 TT wave-retry.** Kill-switches `URL_CAPTURE_BOT_WAVES=1` возвращает single-call legacy. 13 unit tests + recon evidence в `docs/evidence/2026-05-18-wp86-pr2-notification-recon.md`.

Все 3 PR'а merged squash, NO force-push. 1 merge conflict в `publisher_base.py` (оба PR добавили helpers рядом) — resolved через git merge, не rebase/force. 7 env-var kill-switches default ON. PM2 `restart 34 autowarm` (sudo) 18:04 UTC.

**Метрики после deploy** (6h window):
- `awaiting_url` stuck: **45 → 0**
- `published_no_url`: 0 → **20** (15 retroactive + 5 natural через PR1 poller)
- `done`: 31
- `failed`: 1

**24h post-deploy verify (~2026-05-19 18:00 UTC) acceptance:**
1. `awaiting_url` queue depth среднее <5 за сутки (vs 45 baseline).
2. `% specific-URL done` > 95% (vs ~85% baseline).
3. `published_no_url` < 5% от всех успешных публикаций (хвост невосстановимых через все 4 capture-механики).
4. Events `url_capture_via_yt_api` (PR3 A3) + `url_capture_via_diff` (PR3 A5) + `url_capture_via_share_wave` (PR2 A1) появляются > 0 для соответствующих платформ.
5. `failed` от 48h timeout (псевдо-провалы публикаций) ≈0/день (vs ~10% baseline).
6. Никаких regression'ов: посты не дублируются, `cleanupStuckTasks` совместим с новым `published_no_url`.

OpenProject WP #86 status «Готово», memory: [[project_wp86_published_no_url_complete]]. Spec/plans: `docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md` + `docs/superpowers/plans/2026-05-18-wp86-pr{1,2,3}-*-plan.md`. Evidence: `docs/evidence/2026-05-18-wp86-pr1-local-smoke.md` + `docs/evidence/2026-05-18-wp86-pr2-notification-recon.md`.

### Открытые backlog'и (отложены, не блокеры)

- **A1 wave-retry для IG/YT** — отложено в PR2 из-за multi-path complexity (IG имеет 2-step API+UI structure; YT имеет 6 call sites `_get_youtube_url_via_ui` с internal 3-try). Если метрики 24h покажут что IG/YT capture хвост существенный — отдельный mini-PR.
- **IG pre-snapshot (A5)** — в PR3 реализован только для TT+YT, IG требует отдельного path через `web_profile_info` API. Если IG diff matching ценен — отдельный mini-PR.
- **Notification scrape (A2) reality** — в текущем prod dead (URL в PendingIntent), но infra и helpers готовы. Если на новых телефонах notification permissions enable'ятся ИЛИ TT/IG embed URL в notification text в regional builds — A2 активируется через kill-switch.
- **Per-account shadowban detection** — если конкретные аккаунты постоянно дают `published_no_url` (yt-dlp/API возвращают 0 несмотря на successful publish) — это сигнал shadow-ban'а. Отдельная discovery WP при N+ повторений.

## 2026-05-18 — Publish-fails триаж (WP #79) — 8 child-WPs spawned

### ✅ SHIPPED 2026-05-18 (merge `dd4dbb7f6`, OpenProject WP #79 → Тестирование)

Discovery/triage WP от Анастасии — «проверить почему не выкладываются некоторые клиенты» (Релизми, Онлайн школа). Scope расширен по согласованию с пользователем на всех активных клиентов с fail-rate 7d >50% (18 пар client×platform, 11 клиентов) + клиентов с полным простоем (Pimble #79, Эль-косметик #82, Anecole #84).

**Главная находка** — `validator_unic_content = 0` у **14 активных проектов** при наличии `validator_content`. 3 простоя — видимая часть; остальные 11 живут на legacy approved-контенте, скоро встанут. Класс-уровневая блокировка uniqualization-стадии (worker упал / не enrol'ит новые проекты / изменилась схема).

Видео-анализ (5 буckets через ffmpeg + Vision Read) подтвердил:
- `switch_failed_unspecified::NULL` (17) = adb_push timeout на медиа >70MB (известный backlog, [[project_adb_push_network_issue]]).
- `switch_failed_unspecified::publish_failed_generic` (9) = **НОВЫЙ** — TT account-picker bottomsheet silently fails (tap'ом не открывается). НЕ покрыт WP #82.
- `NULL::NULL` (8) = **НОВЫЙ** YT false-negative — публикация прошла, watchdog URL polling 30с убил статус.
- `process_interrupted` (8) = PM2 deploy/restart kill, **infrastructure noise** ([[feedback_process_interrupted_is_pm2_noise]] — исключать из fail-rate).
- `adb_device_not_ready` (7) = ops, **единственное устройство RF8YA0V7LEH** в USB unauthorized.

**8 child-WP в OpenProject (parent=#79, assignee=danil):**
- **#95** [pipeline][P1] Uniqualization stall: 14 active projects with 0 `validator_unic_content` — **главный приоритет**, полная блокировка для 14 клиентов
- **#96** TT account-picker bottomsheet silently fails (publish_failed_generic, 9 fails 7d)
- **#97** YT post-publish URL polling даёт false-negative (NULL::NULL, 8 false-fails 7d, мгновенный backfill 8 тасков → done)
- **#98** adb_push chunked-push для медиа >70MB (17 fails 7d, известный backlog)
- **#99** [ops] re-cable / re-auth device RF8YA0V7LEH (USB unauthorized, 7 fails) — quick win
- **#100** [ops] re-login TT my_clickpay на RFGYC31P26P (account_not_in_list ×3)
- **#101** [ops] re-login TT clickpay_easy на RFGYC2VWBKN + my_clickpay (×5)
- **#102** [investigation] ig_target_not_in_picker — split ops (specific accounts/devices) vs code (UI parser race) (12 fails 7d)

**Already-shipped, упоминание без WP:** `tt_upload_confirmation_timeout` (40+6=46 fails, WP #82 PR #69), `yt_editor_upload_timeout` (3 fails, WP #80 PR #68). Мониторим 24-48ч.

**Tail-buckets без WP (9, с обоснованием в отчёте):** `ig_share_tap_no_progress` (24 — покрыт IG share retry tier2 shipped 2026-05-11), `tt_account_sheet_closed_before_parse` (20 — overlap с #96), `tt_post_switch_verify_unrecoverable` (17 — shipped 2026-05-11), `tt_profile_tab_broken` (17), `tt_account_menu_unknown_layout` (14 — overlap с #96), `date_mismatch::ig_picker_wrong_candidate` (11), `ig_gallery_no_video_candidate` (9), `ig_camera_open_failed` (8), `yt_create_menu_not_reached` (11 — частично WP #80). Открывать только при росте / regression к 2026-05-25.

**OTA-инцидент 2026-05-15** исключён из 7d окна как отдельный root cause ([[feedback_ota_screen_blocks_adb_preflight]]).

Spec/plan через 2 раунда codex review (0 P1) до коммита. Subagent-driven execution: 8 implementer-агентов sequential, summary комментарий id=259 на WP #79.

OpenProject WP #79 → «Тестирование» (lockVer 5→6). Memory: [[project_wp79_publish_fails_triage_shipped]] + [[feedback_process_interrupted_is_pm2_noise]]. Spec: `docs/superpowers/specs/2026-05-18-wp79-publish-fails-triage-design.md`, plan: `docs/superpowers/plans/2026-05-18-wp79-publish-fails-triage.md`, отчёт: `docs/evidence/2026-05-18-wp79-publish-triage.md`.

### Priority order для пользователя

1. **#95** (полная блокировка для 14 проектов) — начать с `pm2 list | grep -i uniq` + `pm2 logs <name>` на VPS.
2. **#99** ([ops] quick win — 7 fails выключается одним re-cable).
3. **#97** (дешёвый код-фикс — поднять watchdog или сменить success-detection на статус, backfill 8 тасков).
4. **#96 / #98** (средние код-фиксы).
5. **#100/#101** ([ops] параллельно с #99).
6. **#102** (investigation) — после фиксов остальных.

---

## 2026-05-18 — Validator video uniqueness: sha256 dedupe + backfill (WP #77)

### ✅ SHIPPED 2026-05-18 PR #13 (`c59fb9e`)

Жалоба Анастасии в WP #77 (2026-05-18): ролики 2123 (project 96) и 2132 (project 99) висели в «Требует одобрения», но не были дубликатами — разные файлы из одной серии (TT-стайл шорты ~18с с похожим CRF). Старая `uniqueness_service.check_uniqueness` использовала duration±0.5с + size diff<5%, что фактически ловит **любые два** коротких видео одного жанра. Поле `content_hash` существовало в схеме `ValidatorContent` с самого старта (`index=True`), но **никогда не вычислялось** — ложно-помеченных копий со временем накопилось 16/443.

PR GenGo2/validator-contenthunter#13 (squash `c59fb9e`): полная замена на `sha256(file_bytes).hexdigest()` в трёх точках записи видео:
- `routers/upload.py` `/file` (прямой multipart) — inline hashlib после `file.read()`.
- `routers/upload.py` `/complete` (presign+S3, **главный prod-путь** — обнаружено в code review P4, изначально пропустил в спеке) — backend сам стримит файл из S3 через `compute_s3_object_sha256(s3_key)` в `loop.run_in_executor`. Non-fatal: при S3 hiccup оставляет NULL, не валит upload.
- `routers/content.py` `/replace-video` — inline hashlib + явный сброс `is_duplicate`/`duplicate_of_id` (codex P12 P2 fix — без сброса UI видел stale state между commit и `_do_full_validation`).

Helper `compute_s3_object_sha256` вынесен в `backend/src/services/content_hash_service.py` (8MB chunks, `S3ObjectNotFoundError` для missing keys, переиспользует `get_s3_client()`). Этот же helper используется backfill-скриптом.

`check_uniqueness(project_id, content_hash, content_id, db)` использует `func.min(id)` over hash-группу INCLUDING саму проверяемую запись; `min_id == content_id → не дубль`. Это защищает от flip-бага: при re-validation самого раннего оригинала после появления более поздней копии запрос с `id != content_id ORDER BY id ASC LIMIT 1` вернул бы late-id и flip'нул бы оригинал в дубль (поймано codex review при review плана).

Backfill `backend/scripts/backfill_content_hash.py --dry-run|--apply [--limit N]`: 443 candidate rows, ORDER BY id ASC, stream-hash в executor. Dry-run использует in-memory `dry_seen_hashes: dict[(pid, sha)] → first_id` для предсказания same-batch duplicates (codex P12 P2 fix — без этого `--apply` показал бы non-zero `marked_duplicate` после dry-run с нулём). Auto-unblock правило: `(was is_duplicate=True AND status=needs_review AND moderation_status=passed) AND теперь не дубль → status=approved`. **НЕ зовёт `notify_content_approved` webhook** — explicit decision (риск массовых мгновенных уникализаций на исторические записи).

5 live-DB тестов в `backend/tests/test_uniqueness_hash.py` (autouse `engine.dispose` fixture из conftest):
- `test_identical_files_marked_duplicate` (RED-then-GREEN базовый кейс)
- `test_different_files_not_duplicate` (**regression-guard** на убитую duration+size эвристику — фикстуры sample_a/b.mp4: ~2с длительность, 4.44% size diff, разные sha)
- `test_same_file_different_projects` (project isolation)
- `test_backfill_false_positive_unblocks` (production-realistic seed: first=approved/no-dup, second=needs_review/is_duplicate→разблокировка БЕЗ webhook)
- `test_backfill_real_duplicate_stays_blocked` (пара 4 — identical bytes → second остаётся blocked)

Production --apply (2026-05-18 16:31 UTC, на checkout `/root/.openclaw/workspace-genri/validator/`):
- 443 processed, 65 marked_duplicate (real), **16 auto_unblocked** (false-positives), 0 errors, 0 skipped_missing
- 2123 → status=approved ✅ (главная жалоба)
- 2132 → is_duplicate=False (status уже был in_uniqualization — ручной override до backfill, не разблокирован)
- 2120/2130 → hash записан, статус не изменён (был ok)
- 2130 остался needs_review, но moderation_status=**flagged** — отдельная причина, не дубликат

Backend перезапущен через `sudo systemctl restart validator-backend.service` сразу после merge — новые uploads через `/complete` пишут hash сразу же.

11 коммитов, 12 файлов, +578/-30. Codex review full diff via stdin — 1 false-positive P1 (asyncio не импортирован — verified, import был ещё в origin/main) + 2 P2 поправлены. Frontend banner: «🛑 Это точная копия контента #N (тот же файл)» + кликабельный `<router-link>` на оригинал, обновлён в ContentDetail.vue + ValidationDetails.vue (по [[feedback_validator_two_slot_renderers]] — оба места рендеринга).

OpenProject WP #77 → «Готово» (comment id=261). Memory: [[project_wp77_content_hash_dedupe_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-18-wp77-duplicate-false-positive-design.md` + `docs/superpowers/plans/2026-05-18-wp77-content-hash-dedupe.md`.

### Out of scope (не сделано в этом PR)

- **Perceptual hash** для уникализированных копий (pHash от кадров + Hamming distance) — отдельная фича, если когда-нибудь понадобится ловить «тот же ролик, чуть пересжатый», то это новый WP. Текущая логика **по дизайну** пропускает re-encoded клоны.
- **Uniqueness для post/carousel** — клиент не жалуется, scope не расширяли (image uniqueness в `validation.py:235` так и оставлен `is_duplicate=False`).
- **Permission на «Одобрить дубль» для client** — кнопка остаётся manager/admin only (как и было). Permission-модель не трогали.
- **Composite index `(project_id, content_hash)` partial** — solo-index по content_hash из исходной схемы уже даёт selective план для текущих объёмов. Если EXPLAIN покажет seq-scan на росте — отдельная миграция.

## 2026-05-18 — TT post-switch promo-modal dismiss (WP #67 Layer 2)

### ✅ SHIPPED 2026-05-18 PR #70 (`aa11d63`)

После Layer 1 (PR #62 от 2026-05-14, `@`-handle priority) `tt_post_switch_verify_unrecoverable` упал с 16/день до 1–2/день. WP #67 18.05 переведён обратно в «В разработке» — за 4 суток (15-18 мая) пришло 5 residual fails, у которых **другая** root cause: после переключения TT показывает блокирующий promo-модал, profile скрыт за ним. 4/5 кейсов (6514/6631/6704/6786) — байт-в-байт идентичная модалка «Привязать номер телефона или эл. почту» / «Не сейчас» (7603 байт). 1/5 (task 7307) — после renav вылез другой модал «Сохранить данные для входа» / «Не сейчас».

PR GenGo2/delivery-contenthunter#70 (squash `aa11d63`): Variant A — module-level whitelist `_TT_POST_SWITCH_DISMISSIBLE_MODALS = ((title, button), ...)` (2 evidence-seeded entry) + pure module helper `_tt_try_dismiss_post_switch_modal(xml) -> Optional[(title, button)]` (требует ОБА: title_substr `in el.label` И clickable `el.label.strip().lower() == button.lower()`) + instance method `_try_dismiss_and_redump(...)` (probe → tap_element → POST_TAP_WAIT_S sleep → dump_ui → returns `(title, new_xml)`) + 2 probe-site вставки в `_tt_handle_post_switch_unknown` (pre-feed-detect + post-renav-re-verify). Cap=1 dismiss/site, total ≤2/handle. Никаких новых error_code — `_attempted` event до fail'а различает старый/новый путь.

3 новых event: `tt_post_switch_modal_dismiss_attempted` (info), `tt_post_switch_recovered_via_modal_dismiss` (account_switch), `tt_post_switch_modal_dismiss_no_recovery` (warning, `reverify_status ∈ {tap_failed, unknown, mismatch}`). Все 4 caller-side события содержат `title_substr` для triage (Codex iter#1 fix).

16 тестов (10 unit + 6 integration) на реальных prod-dumps (`tt_post_switch_modal_phone_email_6514.xml` + `tt_post_switch_modal_save_login_7307_renav.xml`). Full switcher suite — 214/215 passed (1 pre-existing fail baseline, 0 регрессий). Codex review full diff via stdin — 0 P1/P2.

Prod deploy: `git pull --ff-only` в `/root/.openclaw/workspace-genri/autowarm` + `sudo pm2 restart autowarm` (2026-05-18 14:15 UTC). PM2 exec cwd OK, restart clean (без tracebacks).

Smoke re-queued 2 из 5 residual:
- task 7373 (just_clickpay) → `done`, без модалки (happy path не сломан).
- task 7372 (expertcontentlab) → probe сработал корректно (XML 7603→19628, модалка закрылась), но post-dismiss попали на чужой профиль «ᵂᴴᴵᵀᴱ ＢＩＴＡ» — picker-bug, **не WP #67 scope**, заведён отдельный WP #93.

24h soak deadline ~2026-05-19 14:15 UTC — acceptance: `tt_post_switch_verify_unrecoverable` ≤1/день (учесть picker-bug). Новая модалка не из whitelist даст `tt_post_switch_handle_unknown` БЕЗ `_attempted` события → расширяется одной строкой в whitelist.

OpenProject WP #67 → «В тестировании» (комментарий id=239). Memory: [[project_tt_post_switch_modal_dismiss_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-18-tt-post-switch-modal-dismiss-design.md` + `docs/superpowers/plans/2026-05-18-tt-post-switch-modal-dismiss-plan.md`. Evidence: `docs/evidence/2026-05-18-tt-post-switch-modal-dismiss-shipped.md`.

### Follow-ups в backlog

- **WP #93 (новый):** picker-bug — task 7372 после dismiss попали на чужой профиль «WHITE BITA» вместо expertcontentlab. Account picker tap пошёл не в тот ряд. Низкоприоритетен пока не накопится ≥2 evidence.
- **Minor:** добавить тест-кейс `post_renav dismiss → reverify=mismatch` (низкий приоритет).
- **Refactor:** если IG/YT тоже потребуется dismiss — переименовать `_try_dismiss_and_redump` → `_tt_try_dismiss_and_redump` для platform-prefix consistency.

---

## 2026-05-18 — TT `tt_upload_confirmation_timeout` false-negative (WP #82)

### ✅ SHIPPED 2026-05-18 PR #69 (`ae41054`)

Триаж TT-фейлов за день (2026-05-18 UTC): 14 failed / 33 total. Топ — **10/14 `tt_upload_confirmation_timeout`** (≈71%) у разных аккаунтов и устройств. По iter1 UI-дампам видно — видео **уже опубликовано** (профиль `tkachenko_biohacking · 1 с. назад` + кнопка `Get more views`), но `_wait_upload_confirmation` 5+ минут крутится и убивается watchdog'ом. False-negative из-за 4 связанных багов в одной функции:

1. Success-detector `_tt_infer_post_publish_success` стоял ПОСЛЕ retap-ветки и generic dialog handler — они preemptили.
2. `share_btn_clickable` substring `'поделиться'` хватал overlay `«Поделиться видео. Уже поделились:»` на post-publish feed → false retap loop (6750/6788/6814).
3. `_detect_tt_contacts_perm` искал только `«доступ к контактам»` — FB-friends dialog `«доступ к списку ваших друзей в Facebook»` (6789/6809) проваливался в generic handler.
4. Promo-модал «Улучшенные входящие сообщения для бизнеса» (6750 iter10+/6804) re-presentился TT'ом после dismiss → infinite loop.

PR GenGo2/delivery-contenthunter#69 (squash `ae41054`): 7 atomic TDD-коммитов. **Change 1** early success-check в начале wait-loop с deduped dumpsys + `inferred_path_used` parity (`c320681`). **Change 2** fresh-post маркеры `Get more views` Button + timestamp regex `· N с. назад` (`da05399`) — работают и при flaky dumpsys. **Change 3** exact-match `('Поделиться', 'Post', 'Publish')` (`825df47`). **Change 4(a)** `_TT_PERM_DIALOG_VARIANTS` list (`e705498`). **4(b)** новый `_handle_tt_promo_inbox_modal` tri-state cap=5 → `inferred_success` (`8860111`). **4(c)** `_handle_tt_contacts_perm` тоже tri-state cap → `inferred_success` (`ee50743`). Plus реальные XML-fixtures (`7e46032`).

3 env kill-switches default ON: `TT_POSTPUBLISH_EARLY_CHECK_ENABLED`, `TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED`, `TT_PROMO_INBOX_MODAL_HANDLER_ENABLED`. 11 новых unit-тестов с реальными XML-fixtures из инцидента + 5 уточняющих fix-pass тестов через subagent-driven dev (codex review spec — clean; 3 круга code-quality review с fix-pass'ами для double-dumpsys, регекса, env-gate convention).

Prod deploy: `pm2 restart 34 autowarm` 10:30 UTC (sudo, после `git pull --ff-only origin main`). Re-queued 10 TT-задач инцидента (6750/6751/6768/6781/6788/6789/6792/6804/6809/6814) → publish_queue=pending для проверки fix'а в живую.

**24h live verify deadline ~2026-05-19 10:30 UTC** — acceptance:
1. `tt_upload_confirmation_timeout` count за 24h ≤2/день (вместо 10).
2. Events `tt_post_publish_inferred_fresh_post` / `_from_promo_loop` / `_from_perm_loop` появляются > 0 (доказательство что новые пути активны).
3. Re-queued 10 задач завершаются в `done` (не `failed`).
4. `tt_promo_inbox_modal_dismissed` events растут (если promo-модал реален).

OpenProject WP #82, memory: [[project_tt_upload_confirmation_false_negative_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md` + `docs/superpowers/plans/2026-05-18-tt-upload-confirmation-false-negative-plan.md`.

### Открытые runner-up'ы из триажа 2026-05-18 (не затикечены, малый объём)

- **`tt_profile_tab_broken` (3/день)** — tap «Я» не открывает профиль. Memory `project_tt_post_switch_renav_shipped` упоминает recovery PR #34; 3/день — приемлемо, не takeaction. Если вырастет 7+/день — взять в discovery.
- **`tt_post_switch_verify_unrecoverable` (1/день)** — `tt_post_switch_handle_unknown` без recovery success. PR #34 должен покрывать; пристальнее если повторится 5+/день.

## 2026-05-15 — TT commercial-music modal handler (WP #75)

### `tt_upload_confirmation_timeout` (новая сигнатура «Коммерческие треки → TikBiz playlist») — ✅ SHIPPED 2026-05-15 PR #66

Триаж TT-фейлов за день: 175 fails, 166 = сетевая `adb_devices_unreachable` (исключена, network уже починен), top non-network = 3 явных `tt_upload_confirmation_timeout` (tasks 6495/6510/6512) + 1 orphan (5202) с той же сигнатурой = 4/9 ≈ 44% non-network падений из одной корневой. На всех 3 screencast'ах TT застрял на одной и той же странице **«Коммерческие треки → TikBiz playlist»** (треки PONCHET, Yang Salah, Beat Automotivo, Happy/Vide..., Countless...) — публикатор не закрывает модал, AI vision возвращает `{x:null,y:null}` для кнопки «Опубликовать», 3-мин `wait_upload` timeout. Разные аккаунты (axilor_prive/brand, clickpay_under), разные устройства (RF8Y80ZTVFZ/RF8YA09S90H/RFGYC31P94Z), разные raspberry (#1/#9) — баг воспроизводим, не device-state. Это **НЕ** music-rights confirmation (диалог *согласия*, закрыт PR #28/#32), а новый **selector с принудительным выбором** коммерческого трека.

PR GenGo2/delivery-contenthunter#66 (squash `2dd53ff`): **3-level detector** (strict + fallback + evidence-only, аналог music-rights) → **cancel-select ladder** (`iter ≤ 2` → tap X, `iter > 2` → выбор 1-го трека через ✓, MAX=4 → `tt_commercial_music_stuck`) → wired в 2 hook'а (`_publish_share_loop` Шаг 5 — основной перед XML-сканом «Опубликовать», `_wait_upload_confirmation` outer loop — defensive). Env kill-switches `TT_COMMERCIAL_MUSIC_HANDLER_ENABLED` (default ON) + `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED` (default OFF). 9 новых event categories для триажа. 40 unit + 1 integration smoke + 305 passed в TT regression. Subagent-driven-development через 15 plan tasks, codex-review round 2 = 0 findings, final reviewer = ready to merge. PM2 `restart 34 autowarm` + `restart 33 autowarm-testbench` 18:22 UTC.

**24h live verify deadline ~2026-05-16 18:22 UTC** — acceptance:
1. 0 fails `tt_upload_confirmation_timeout` с сигнатурой `ai_find_tap_no_coords` на Publish-кнопке.
2. Распределение `tt_commercial_music_cancelled` vs `_track_selected` за 24h. Если 100% → select, cancel-X не закрывает модал, нужен switch policy на select-первым (iter2).
3. Нет `tt_commercial_music_stuck` events.
4. Если `tt_commercial_music_unhandled_suspect` (evidence-only) сработает — включить `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED=true` и собрать XML dumps в `/tmp/autowarm_ui_dumps/`.

Memory: [[project_tt_commercial_music_modal_wip]]. Spec/plan/evidence: `docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md` + `docs/superpowers/plans/2026-05-15-tt-commercial-music-modal-handler.md` + `docs/evidence/2026-05-15-tt-publish-fails-triage.md`.

### Открытые runner-up'ы из триажа 2026-05-15 (не затикечены, малый объём)

- **`tt_account_sheet_closed_before_parse` (2/день)** — bottomsheet со списком аккаунтов не открылся, target не добавлен на устройство. По msg выглядит как data-issue (онбординг аккаунта), не код-баг. Если повторится 7+ дней — взять в discovery.
- **`tt_profile_tab_broken` (2/день)** — tap «Я» не открывает профиль. Memory `project_tt_post_switch_renav_shipped` упоминает recovery PR #34. 2/день — приемлемый шум, не takeaction. Если вырастет — взять.
- **`tt_post_switch_verify_unrecoverable` (1/день)** — `tt_post_switch_handle_unknown` без recovery success. PR #34 (post-switch verify recovery) должен покрывать; пристальнее посмотреть если повторится 5+/день.

## 2026-05-15 — YT post-switch upload state normalization (WP #74)

### `yt_gallery_no_video_candidate` — ✅ SHIPPED 2026-05-15 PR #64

Триаж YT-фейлов за день: 166 fails, 164 = сетевая `adb_devices_unreachable` (исключена, network уже починен), 2 = `yt_gallery_no_video_candidate` (task 6513 oracle_spacee + 6515 oraclevisionn, raspberry 8, проект «Эзотерика Oleg»). На скринкастах оба раза YT после успешного `_ensure_correct_account` остаётся не в upload-state: 6513 завис на системном permission-диалоге «Откройте YouTube доступ к камере и микрофону», 6515 — на Shorts feed с открытой `Описание` bottom-sheet. Watchdog «post-account-switch» бил через 120s, picker фейлился с `all_clickable_count=0`.

PR #64 (3 коммита, squash `4722b81`): **A** `_normalize_yt_state_pre_upload` — `am force-stop` + `am start LAUNCHER` + 2 итерации permission-tap'ов перед probe'ом меню создания; **B** в `_select_gallery_video` parse loop добавлены 'При использовании приложения', 'Только в этот раз', 'Allow', 'Понятно'; **C** meta при fail-fast обогащена `top_resumed_activity` + `current_package` (категория `yt_gallery_no_video_candidate` сохранена — dashboards). 23 теста зелёные, codex без замечаний, prod `pm2 restart 34 autowarm` 16:42 UTC.

**24h live verify deadline ~2026-05-16 16:42 UTC** — acceptance: 0 fails `yt_gallery_no_video_candidate` за 24h при ненулевом потоке YT-задач. Memory: [[project_yt_post_switch_state_normalize_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-15-yt-post-switch-upload-state-normalization-design.md` + `docs/superpowers/plans/2026-05-15-yt-post-switch-upload-state-normalization.md`.

## 2026-05-15 — WP 63 scheduler status sync — ✅ SHIPPED

`fix(scheduler)` PR GenGo2/validator-contenthunter#12 (merged `520aaec`) — клиентский планировщик показывал «✅ Одобрено» уже когда `moderation_status=passed`, не учитывая `content_status`. Для контента с дублем (`passed + needs_review`) автовыкладка не запускалась (вебхук гейтит на `ContentStatus.approved` в `validation.py:132`), но UI рисовал готовность. Чистый классификатор в `frontend/src/utils/slotStatus.ts` + 23 unit-теста + согласованные цвет рамки/пилюли. WP 63 → `Тестирование`, ждём визуального подтверждения Анастасии. Evidence: `docs/evidence/2026-05-15-wp63-scheduler-status-fix-shipped.md`. Memory: [[project_wp63_scheduler_status_shipped]].

**Follow-up (low):** унификация manager-side `frontend/src/components/calendar/SlotCard.vue` на тот же `slotStatusInfo` — бага сейчас нет (manager уже смотрит на `content.status` напрямую), но единый классификатор уменьшит риск регрессии в будущем (из памяти `feedback_validator_two_slot_renderers` — два места рендеринга).

## 2026-05-14 — TT post-switch verify `@handle`-priority (WP #67)

### `tt_post_switch_verify_unrecoverable` — ✅ SHIPPED 2026-05-14 PR #62

Крупнейший незатикеченный баг дня (16/58 TT-падений, 16 устройств). `get_current_account_from_profile` брала верхний токен, прошедший `_looks_like_username` — на экране профиля TikTok это имя профиля / badge-счётчик НАД `@handle`. Свитч проходил, verify давал ложный mismatch. Фикс: ведущий разряд сортировки `is_bare` (`@`-токены приоритетнее). PR GenGo2/delivery-contenthunter#62 (squash `433c5b2`), в проде. Live smoke: 3/3 ре-выкладок распознали аккаунт через fast-path, 0 `tt_post_switch_verify_unrecoverable`. Memory: [[project-tt-post-switch-verify-handle-fix]]. Evidence: `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md`.

**24h soak deadline ~2026-05-15 16:00 UTC** — acceptance: `tt_post_switch_verify_unrecoverable` 16/24h → ~0. Query — в evidence-доке § «Запросы».

### Открытые runner-up'ы из триажа 2026-05-14 (не затикечены)

- **`tt_upload_confirmation_timeout` (7/день)** — свитч+verify проходят, видео заливается, экран подтверждения не детектится в таймаут (стадия `wait_upload`, не switcher). **Surfaced снова в smoke этого фикса** (tasks 5998/5999 дошли до publish-фазы и упали тут) — следующий кандидат на фикс по объёму.
- **`tt_profile_tab_broken` (5/день)** — tap «Я» не открывает профиль. PR #50 (TT security prompt dismiss) целился сюда с acceptance `< 2/24h` — 5/день на 2026-05-14 говорит, что PR #50 закрыл не всё; проверить на 24h-verify PR #50, возможно нужен отдельный заход.
- **retry-suffix gap мэппера** — триаж переподтвердил: `_SWITCHER_STEP_TO_CATEGORY` не матчит `_retry_N` шаги → реальная категория теряется в `publish_failed_generic` / `switch_failed_unspecified`. Уже описан ниже (секция «`switch_failed_unspecified` mapper retry-suffix gap»). 4 задачи 2026-05-14 замаскированы так.

## 2026-05-14 — WP 53 phantom schemes follow-up

### Router-level `unic_schemes` reads unfiltered (low priority)

WP 53 fix (PR #10) filtered `id > 0` in `schemes_service.get_schemes_with_preferences` + `get_summary` — the client-facing schemes screen. Three router-level reads in `backend/src/routers/schemes.py` still read `unic_schemes` unfiltered:

- `check_readiness` (`:141`) — `SELECT COUNT(*) FROM unic_schemes` → `total_schemes` (gates `previews_ready`)
- `generate_previews` (`:349`) — `SELECT * FROM unic_schemes ORDER BY id` → schemes sent to the render worker
- `approved_scheme_ids` (`:450`) — fallback `SELECT id FROM unic_schemes ORDER BY id`

Not urgent: the leak source is closed (`test_schemes_deficits._cleanup_project` now deletes `id <= -1`), so phantoms won't recur. But these are a latent inconsistency if a service row ever reappears via another path. Add `WHERE id > 0` for defense-in-depth when next touching that file. Evidence: `docs/evidence/2026-05-14-wp53-phantom-schemes-fix-shipped.md`.

## 2026-05-13 session follow-ups

### 24h verify (next day morning)

Четыре shipped PR в один день требуют 24h-verify SQL:

| PR | Topic | Deadline (UTC) | Acceptance |
|---|---|---|---|
| #48 | Watchdog ping regression | 2026-05-14 08:40 | Pi 3+5 `switch_failed_unspecified` < 5 / 24h |
| #49 | IG share OK fallback (Tier 1.5) | 2026-05-14 11:45 | `ok_rescued_24h / ok_attempted_24h ≥ 30%` |
| #50 | TT security prompt dismiss | 2026-05-14 13:25 | `tt_profile_tab_broken < 2/24h` AND `tt_security_prompt_dismissed > 0` |
| #52 | TT Pattern B (probe-and-pivot) | 2026-05-14 17:30 | `tt_account_sheet_closed_before_parse` ≤ 5/24h AND new codes ≤ 3/24h combined |

SQL pack в `docs/evidence/2026-05-13-*.md § "24h verify"` для каждого PR. PR #52 SQL — `jsonb_array_elements WITH ORDINALITY` (terminal `failed` event без category, нужно сканировать назад). После прогона — обновить evidence docs + memory entries (close OR iterate).

### TT Pattern B — `tt_account_sheet_closed_before_parse` ✅ SHIPPED 2026-05-13 PR #52

12-commit branch (`be62872..69a2dea`) squash-merged как `76ecd4f`. Probe-and-pivot orchestrator закрывает 19/24h root cause (TT app update — username tap открывает Stories/LIVE viewer вместо account-switcher bottomsheet). Memory: [[project_tt_pattern_b_shipped]]. Evidence: `docs/evidence/2026-05-13-tt-pattern-b-shipped.md`. Smoke pq 2149 live; 24h verify deadline 2026-05-14 17:30 UTC.

**Iteration #2 — 2-step settings-nested account switcher (HIGH priority, evidence in hand)**

Live smoke task 5572 (clickpay_go) post-hotfix: orchestrator successfully reached drawer search but `_find_tt_account_switcher_anchor_in_drawer` returned None. `drawer_labels[]` payload reveals new TT requires 2-step navigation: «Меню профиля» → «Настройки и конфиденциальность» → settings page → «Управление аккаунтами». Spec for iter#2 needed: add a settings-nested lookup pass to the orchestrator when first drawer search returns None. Anchors: `['настройки и конфиденциальность', 'настройки', 'settings and privacy', 'settings']`. Cap nesting at 1 level. See `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` § Second smoke for the full drawer label list.

**Open follow-ups (Minor, from final holistic opus review):**
1. Inline-vs-helper asymmetry on `tt_account_sheet_closed_before_parse` emission (functionally fine).
2. `menu_dump` redundancy with `back_dump` (~1-2s extra).
3. `_tap_profile_header` internal `_save_dump` overwritten by orchestrator under same step name (pre-existing).
4. End-to-end test of menu-path through `_switch_tiktok` missing — smoke is only true verification. **CAUGHT BY THIS — smoke caught `adb_shell→adb` regression (hotfix PR #54) that 6 codex rounds + 48 unit tests missed.**

### `switch_failed_unspecified` mapper retry-suffix gap (new, 2026-05-13)

24h фон 25 fails, после декомпозиции:
- 17 pre-PR-#48 watchdog-killed — закроется по 24h verify PR #48
- 6 pre-PR-#48 other (вероятно тоже watchdog или race)
- **2 post-PR-#48 non-watchdog** — реальный остаток после сегодняшних deploy'ов

Корень: `_SWITCHER_STEP_TO_CATEGORY` в `publisher_kernel.py:76` НЕ знает retry-суффиксы (`tt_1_feed_retry_1`, `tt_3_open_list_retry_1` и пр.) → Pass-2 fallback resolver'а дефолтится на `switch_failed_unspecified`.

Sample failing steps post-PR-#48:
- task 5326 (TT, datj2k5): fail step `tt_1_feed_retry_1` — TT не запустился после post-switch retry restart. Должен мэппиться на `tt_app_launch_failed`.
- task 5296 (TT, relisme_co): fail step `tt_3_open_list_retry_1` — switcher's retry. Должен мэппиться на `tt_account_sheet_closed_before_parse`.

Fix варианты:
1. Strip `_retry_N` suffix в resolver Pass-2 перед lookup (1 line in `publisher_base._set_error_code_from_events`).
2. Явные entries для каждой retry-suffixed step в `_SWITCHER_STEP_TO_CATEGORY` (явнее, шире diff).

**Не блокер сегодня:** 2/24h, и часть «25» исчезнет после PR #48 verify. Чинить завтра после 24h-verifies (2026-05-14 morning UTC).

### AI Unstuck не firing — possibly self-resolved by PR #48

До PR #48 (08:40 UTC): AI Unstuck не firing 0/22 в TT timeout кейсах. Hypothesis: watchdog regression обрывал AI Unstuck до того, как он успевал что-то сделать. Per memory `project_watchdog_ping_regression_shipped` — теперь watchdog продлевается активностью. Проверить 24h: возвращается ли AI Unstuck к нормальной частоте.

### YT `yt_editor_upload_timeout` — ✅ ROOT-CAUSED + FIXED 2026-05-14 PR #56

**НЕ self-resolved PR #48.** Триаж 2026-05-14 (OpenProject #59) нашёл 3 свежих `yt_editor_upload_timeout` (tasks 5685/5717/5724) — топ-причина YT-падений за день (3/6), #3 за 7д (14). Root cause: post-switch verify возвращает `'unknown'` → degrade-to-pass всегда, даже когда YouTube не на переднем плане → publisher уходит в 5-мин editor poll вслепую. Скринкасты: device на рабочем столе / Google voice search / Facebook prompt. 14/15 за 7д имеют precursor `yt_post_switch_handle_unknown`.

Фикс — `_switch_youtube` post-switch loop: degrade-to-pass на `'unknown'` теперь gated проверкой foreground-пакета; чужой app в foreground → fail fast с `yt_post_switch_app_not_foregrounded`. PR #56 squash-merge `348d495`, в проде 2026-05-14. Evidence: `docs/evidence/2026-05-14-yt-publish-triage.md`. Memory: [[project_yt_post_switch_foreground_guard]].

**24h verify deadline 2026-05-15 ~13:00 UTC** — SQL в evidence doc § "24h verify". Acceptance: `yt_editor_upload_timeout` после `yt_post_switch_handle_unknown` резко падает, вместо зависаний — быстрый `yt_post_switch_app_not_foregrounded`. Residual ~1/15 (editor genuinely stuck при YT в foreground) остаётся под item ниже.

---

## YT stabilization follow-ups (2026-05-12 session)

### Шаг D — yt_editor_upload_timeout (после AI Unstuck)

**STATUS 2026-05-14:** дублирующий precursor-вариант (`yt_post_switch_handle_unknown` → editor poll вслепую) закрыт PR #56 — см. item «YT `yt_editor_upload_timeout` — ✅ ROOT-CAUSED + FIXED» выше. ОСТАЁТСЯ residual: ~1/15 за 7д имели `yt_editor_stuck_detected` БЕЗ precursor'а — YouTube был в foreground, но редактор реально завис. Вот этот случай — то, что не покрыто PR #56 и описано ниже.

13 fails/week pre-2026-05-13, single-pattern `YouTube: редактор timeout — Загрузить не найдено (после AI)` в `publisher_youtube.py:1199-1205`. AI Unstuck вызывается (`ai_unstuck_result=True`), что-то делает, но кнопка «Загрузить» не появляется. Screen recordings analysis на task'ах 4892/4444/4441. Hypothesis: editor в caption-screen с задержанной generation animation; AI не дожидается. Fix варианты: лучший detection caption-screen + skip AI, или post-AI wait+retry с другими criteria.

### Port `device_tz` to `publisher_helpers.parse_picker_thumbnail_date`

PR #45 (IG-only device-tz fix для phone #9 / Asia/Almaty) live в `publisher_instagram._ig_parse_thumbnail_date(desc, device_tz=None)`. После PR #43 (YT cross-project leak) IG имеет own copy с device_tz, YT использует `publisher_helpers.parse_picker_thumbnail_date` БЕЗ device_tz. Если YT начнут публиковать на не-MSK phones — будет False-mismatch. Port `device_tz` parameter в shared helper и rewire IG обратно на shared.

### Lead_Content_1 (и похожие) data-drift cleanup

Аккаунт в `factory_inst_accounts` с `gmail=NULL`, на phone в YT picker отсутствует (display name `Lead_Content `, suffix `_1` отсутствует, handle row отсутствует). Backfill no-match. Sticky 3 fails / 7d. Опции: (a) manual deactivation в БД; (b) automated `account_revision` post-scroll detector + auto-deactivate; (c) periodic backfill no-match log → daily TG bot notification.

**NB 2026-05-14:** не все `yt_picker_target_absent` / `yt_target_not_in_picker_after_scroll` — реальные отсутствия. Триаж iter2 (task 5856) доказал false-negative: аккаунт *присутствует* в picker'е, но matcher его не находит — см. item «YT picker — matcher игнорирует имя канала» ниже (#66). Этот data-drift item остаётся валиден только для *реально* отсутствующих аккаунтов; перед deactivation проверять, что аккаунта правда нет (matcher-баг сначала фиксится).

### YT picker — matcher игнорирует имя канала — ✅ SHIPPED 2026-05-14 PR #63 (OpenProject #66)

**✅ SHIPPED 2026-05-14** — PR GenGo2/delivery-contenthunter#63 (squash `6189cd6`), в проде через `git pull --ff-only`. OpenProject #66 → Тестирование. Memory: [[project_yt_picker_channel_name_match_shipped]].

Корень: `_find_and_tap_account` (`account_switcher.py`) для YT — gmail-fast-path работает только при заполненном `_yt_target_gmail` (нет у ~19% аккаунтов); fallback `find_account_in_list` — handle/username-ориентирован и НЕ матчит target против имени канала YT, которое для *неактивных* строк picker'а единственное видимое поле (`"<ChannelName>,,<subs>"`, без `@handle`). Dump usable + target не сматчен → терминальный FAIL без vision. Подтверждено task 5856 (`relismee` → канал «Relisme»). Семейство (`yt_target_not_in_picker_after_scroll` 23 + `yt_picker_target_absent` 4 = 27/7д) — крупнейшая actionable категория YT-падений за неделю.

Фикс: новые `_alnum_norm` + `find_yt_channel_name_matches` (консервативный матч по имени канала — точное совпадение или префикс с разницей длины ровно 1, `min(len)>=4`; ambiguity-guard: при 2+ кандидатах честный fail, не угадываем). 12 тестов TDD, 0 регрессий, codex + 3 раунда subagent-review.

**Открытые follow-up'ы (отдельные тикеты, вне #66):** добить `factory_inst_accounts.gmail` backfill для непокрытых ~19%; разобрать 11/27 за неделю где gmail в БД есть, но публикация всё равно не находит аккаунт. Evidence: `docs/evidence/2026-05-14-yt-publish-triage-iter2.md`.

### 24h soak — new YT RC counts

После Шагов B+C ждать 24h, затем:
```sql
SELECT events->-1->'meta'->>'category', COUNT(*)
FROM publish_tasks
WHERE platform='YouTube'
  AND created_at >= '2026-05-12 20:30:00+00'
  AND status='failed'
GROUP BY 1 ORDER BY 2 DESC;
```
Expected: `yt_target_not_in_picker_after_scroll` падает, `yt_picker_dismissed` + `yt_picker_target_absent` + `yt_picker_wrong_candidate` + `yt_gallery_no_video_candidate` появляются. Если `yt_gallery_no_video_candidate > 5/24h` — investigate device-state (не код).

### Real RC of 23-sec dead-time (race в task 3970)

Что dismisses YT picker между tap'ом и parse'ом (Шаг C показал: video player через 23s после picker shown). Hypothesis: spurious adb_tap из background / launcher / system notification. Defensive guard в Шаге C достаточно для observability и recovery; deeper investigation deferred до evidence accumulates.

## После 2026-05-12-scheme-preview-remote-worker

### Other ffmpeg tasks → unic-worker (same pattern)

После успешной миграции scheme preview по unic-worker queue pattern, следующие validator-side ffmpeg-задачи можно мигрировать тем же способом:

- **OCR** (`backend/src/services/ocr_service.py`)
- **Transcription** (`backend/src/services/transcription_service.py`)
- **Video metadata extraction** (`backend/src/services/video_metadata.py`)

Подход: alembic 005 расширяет `ck_unic_tasks_task_type` на новый `task_type`. Worker добавляет `process_<type>_task` функцию + dispatcher branch. Validator endpoint пишет в `unic_tasks` с соответствующим `task_type`. payload_hash и last_task_id guards переиспользуются.

### Heartbeat для legacy unic-pipeline

Сейчас `stale_task_recovery_loop` watchdog не трогает `task_type='unic'` потому что `process_task` может рендерить одну тяжёлую схему >15 мин без обновления `updated_at`. Решение: heartbeat_loop в legacy pipeline тоже (тот же helper, просто wrap). После этого расширить watchdog WHERE на оба task_type.

### Async cancellation orphan ffmpeg при PM2 restart

Codex P2 backlog из PR validator#6: `asyncio.to_thread + subprocess.run` не отменяют ffmpeg при SIGTERM. Перейти на `asyncio.create_subprocess_exec` с явным `process.kill()` в finally. Сейчас не релевантно для scheme preview (рендер на worker'е), но legacy unic-pipeline в worker.py остаётся sync subprocess.run.

### TG-notification при watchdog 3-revert

Сейчас только `logger.warning` идёт в `pm2 logs unic-worker`. Подключить через bugs-bot infrastructure (см. memory `project_bugs_bot`) — TG-нотификация в чат когда задача стоит в processing с `watchdog_revert_count >= 3`.

### Frontend timeout-aware error display

`UsersManagement.vue:348` паттерн `e.response?.data?.detail || 'Ошибка'` оставляет axios timeout кейсы немыми (generic «Ошибка»). Заменить на:

```js
catch (e: any) {
  formError.value = e.response?.data?.detail
    || (e.code === 'ECONNABORTED' ? 'Превышено время ожидания, попробуйте ещё раз' : null)
    || e.message
    || 'Ошибка'
}
```

Применить ко всем catch-блокам где `e.response?.data?.detail` ловится — есть в нескольких компонентах validator frontend.

### Multi-worker horizontal scale

Архитектурно разрешено через `FOR UPDATE SKIP LOCKED` в `get_pending_task`. Поднимать второй unic-worker на другом IP если queue depth растёт (нужно сначала enforce'ить heartbeat для legacy unic + monitoring queue depth).

### Cleanup duplicated phase→status mapping

Маппинг DB phase → legacy frontend status field дублируется в:
- `backend/src/routers/schemes.py` (внутри `check_readiness`)
- `backend/src/services/scheme_preview_queue.py` (внутри `read_scheme_preview_status`)

Когда фронт перейдёт на унифицированный shape (только `phase`, без `status`) — убрать дублирование. Сейчас оставлено для backward compat.

### Cancel-on-supersede для processing scheme_preview

Сейчас supersede mark'ает только `pending` строки. Если первая task уже в processing — она доработает (3-5 минут на схему × ~15 схем = до 75 минут), а новый payload встаёт рядом в pending. Можно добавить cancellation механизм:

```python
current_status='cancel_requested'
```

Worker check'ает между схемами и stops. Не критично пока, потому что новая task в любом случае перепишет результаты последней.
