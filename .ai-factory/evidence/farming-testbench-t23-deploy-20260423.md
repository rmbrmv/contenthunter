# T23 — Farming Testbench Prod Deploy Evidence

**Date:** 2026-04-23
**Env:** fra-1-vm-y49r (prod VPS)
**Branch:** autowarm testbench @ 50f2e78

## Sudo scope restriction

Per memory `feedback_server_access`: claude-user имеет NOPASSWD sudo только
на `/usr/bin/chown`, `/usr/bin/pm2`, `/usr/bin/systemctl`. Не на `cp`, `install`, `tee`.

Следствие: **исходный план с systemd units в /etc/systemd/system/ и shell-скриптами
в /usr/local/bin/ — не реализуем Claude'ом автономно.**

## Actual deploy strategy

1. **Orchestrator через PM2** (вместо systemd) — добавлен в `ecosystem.farming-testbench.config.js`
   как 2-й app рядом с scheduler'ом. `sudo pm2 start` + `sudo pm2 save` — в моих правах.

2. **Start/Stop через SQL-flag** (вместо `/usr/local/bin/farming-testbench-*.sh`) — server.js
   endpoints теперь делают UPDATE system_flags.farming_testbench_paused. Орчестратор и scheduler
   оба проверяют флаг каждый tick и пропускают dispatch если TRUE. Это проще, безопаснее
   (in-flight задачи завершаются естественно), не требует sudo.

3. **Shell-скрипты и systemd units остались в репо** (`scripts/farming-testbench/*.sh` +
   `systemd/autowarm-farming-*.{service,timer}`) на случай если в будущем оператор
   хочет мигрировать с PM2 на systemd (понадобится `sudo cp`).

## Deploy sequence (как это было сделано)

```
# 1. Pull farming код на testbench checkout
cd /home/claude-user/autowarm-testbench && git pull --rebase origin testbench

# 2. Sync ecosystem config (PM2 app для orchestrator добавлен)
cp /root/.openclaw/workspace-genri/autowarm/ecosystem.farming-testbench.config.js \
   /home/claude-user/autowarm-testbench/ecosystem.farming-testbench.config.js

# 3. Set kill-switch в paused ДО старта (safety-first)
psql: INSERT INTO system_flags (key, value) VALUES ('farming_testbench_paused','true') ON CONFLICT (key) DO UPDATE SET value='true';

# 4. Restart autowarm (pickup /api/farming/testbench/* routes)
sudo pm2 restart autowarm

# 5. Start farming PM2 apps
sudo pm2 start /home/claude-user/autowarm-testbench/ecosystem.farming-testbench.config.js
sudo pm2 save
```

## PM2 state (post-deploy)

```
┌────┬───────────────────────────────┬──────┬──────────┬─────────┐
│ id │ name                          │ mode │ pid      │ status  │
├────┼───────────────────────────────┼──────┼──────────┼─────────┤
│ 1  │ autowarm                      │ fork │ 936288   │ online  │  <- prod API (restarted, picks up farming routes)
│ 25 │ autowarm-testbench            │ fork │ 857850   │ online  │  <- publish testbench scheduler (untouched)
│ 26 │ autowarm-farming-testbench    │ fork │ 936308   │ online  │  <- NEW: farming scheduler
│ 27 │ autowarm-farming-orchestrator │ fork │ 936309   │ online  │  <- NEW: farming orchestrator
│ .. │ ch-auth, producer, validator  │ ...  │ ...      │ online  │
└────┴───────────────────────────────┴──────┴──────────┴─────────┘
```

## Orchestrator bootstrap log

```
[INFO] ═══ farming-orchestrator starting ═══
[INFO] device=RF8Y90GCWWL (device_number=171) raspberry=8 packs=['Тестовый проект_171a', 'Тестовый проект_171b']
[INFO] roster instagram: available=2 ['ivana.world.class@Тестовый проект_171a', 'born.trip90@Тестовый проект_171b'] blocked=0
[INFO] roster tiktok:    available=2 ['user899847418@Тестовый проект_171a', 'born7499@Тестовый проект_171b']            blocked=0
[INFO] roster youtube:   available=2 ['Ivana-o3j@Тестовый проект_171a', 'Born-i6i3n@Тестовый проект_171b']              blocked=0
[INFO] paused via system_flags.farming_testbench_paused — skip
[INFO] next tick in 4800 sec (cadence 240 min / 3 platforms)
```

**Orchestrator корректно:**
- Подхватил все 6 аккаунтов на #171 (3 на 171a + 3 на 171b)
- Проверил kill-switch (paused=true) и пропустил первый tick
- Рассчитал interval 4800 сек (80 мин на платформу) по default cadence 240 min

## Scheduler bootstrap log

```
[INFO] [farming-sched] warmer path: /home/claude-user/autowarm-testbench/warmer.py
[INFO] [farming-sched] tick: 15000ms, concurrency cap: 1, stuck timeout: 120min
[INFO] [farming-sched] lock acquired: /var/lock/autowarm-farming-testbench-scheduler.lock (flock pid=936330)
[INFO] [farming-sched] scheduler ready, waiting for farming-testbench tasks
```

## Endpoint verification

```
$ curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3849/farming-testbench.html
HTTP 302                       # redirect to /login.html (как ожидается для auth-protected)

$ curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3849/api/farming/testbench/dashboard
HTTP 401                       # requireAuth middleware ✅
```

## DB state

```sql
SELECT COUNT(*) FROM autowarm_tasks WHERE testbench=TRUE;         -- 0 (кill-switch paused, тиков не было)
SELECT COUNT(*) FROM farming_error_codes;                         -- 23 seed кодов
SELECT COUNT(*) FROM farming_investigations;                      -- 0
SELECT COUNT(*) FROM farming_fixes;                               -- 0
SELECT value FROM system_flags WHERE key='farming_testbench_paused'; -- 'true' (paused)
```

## Public URL

**https://delivery.contenthunter.ru/farming-testbench.html**

- Auth-protected (redirect на /login при отсутствии session)
- SPA-ссылка "Testbench (phone #171)" добавлена в сайдбар секции «Прогрев»
- Кнопка "▶ Запустить farming-стенд" — делает SQL flag=false, orchestrator resumes

## What's NOT deployed (follow-up)

- `/usr/local/bin/farming-testbench-*.sh` — **не установлены** (нужно `sudo cp` — не в allowed scope). Нужны только если мигрируешь с PM2 на systemd. Файлы лежат в
  `/home/claude-user/autowarm-testbench/scripts/farming-testbench/`.
- `/etc/systemd/system/autowarm-farming-*.{service,timer}` — **не установлены**. Файлы лежат
  в `/home/claude-user/autowarm-testbench/systemd/`.
- `farming-testbench-status` CLI — не в $PATH. Запуск: `bash /home/claude-user/autowarm-testbench/scripts/farming-testbench/farming-testbench-status.sh`.

Если хочешь traditional systemd+shell-bin deployment — 2 команды sudo:
```
sudo install -m 755 /home/claude-user/autowarm-testbench/scripts/farming-testbench/*.sh /usr/local/bin/
sudo install -m 644 /home/claude-user/autowarm-testbench/systemd/autowarm-farming-*.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autowarm-farming-triage-dispatcher.timer
sudo pm2 stop autowarm-farming-orchestrator  # если перейти с PM2 на systemd
sudo pm2 delete autowarm-farming-orchestrator
sudo systemctl enable --now autowarm-farming-orchestrator
```

## Next

T24 — live smoke test: нажать "▶ Запустить" в UI, подождать 6-8 часов. Ожидаемые
результаты:
- Первые 3 тика на IG/TT/YT (по одному на платформу)
- IG task успешно завершится (status=completed)
- TT task упадёт с farming_app_launch_failed или farming_splash_hang (known #171 bug)
- YT task упадёт с yt_anchor_suspicious_position или yt_bottom_nav_unresponsive
- triage_classifier создаст investigations на TT/YT паттерны
- UI /farming-testbench.html покажет категории ошибок + open investigations
