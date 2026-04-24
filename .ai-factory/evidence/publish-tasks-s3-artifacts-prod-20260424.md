# Evidence: publish-tasks S3 artifacts — prod deploy

**Дата:** 2026-04-24
**Задача:** T9 плана `publish-tasks-s3-artifacts-20260424.md`
**Commit:** `872d99b feat(publisher): S3 upload для скринов и UI dumps в логах публикации`
**Auto-push:** `testbench → GenGo2/delivery-contenthunter` ✅

## Deploy

```
$ cd /root/.openclaw/workspace-genri/autowarm
$ git commit ...
[pre-commit] ✅ All checks passed — index.html is valid!
[git-hook] ✅ Pushed to GenGo2/delivery-contenthunter
[testbench 872d99b] 4 files changed, 351 insertions(+), 32 deletions(-)

$ sudo pm2 restart autowarm
│ 1  │ autowarm │ online │ 0s │
```

Логи чисто, процесс поднялся:
```
[dotenv@17.3.1] injecting env (17) from .env
✅ БД инициализирована
🚀 Autowarm запущен на порту 3848
📡 Device mapping sync job запланирован (каждый час, add_unknown=true)
📅 Scheduler запущен
```

## Pre-deploy gates (T4 + T5)

- Bucket policy — 200 OK + корректный Content-Type на обоих новых prefix'ах (evidence/publish-tasks-s3-artifacts-bucket-check-20260424.md).
- Unit-tests: `tests/test_s3_artifacts.py` — 8/8 passed.

## Gotcha обнаружен: testbench — отдельный pm2 + отдельный code path

`autowarm-testbench` pm2 процесс (id=25) использует **свою копию кода** в `/home/claude-user/autowarm-testbench/`, а не `/root/.openclaw/workspace-genri/autowarm/`.  Testbench-задачи (`publish_tasks.testbench=true`) обрабатываются через `testbench_scheduler.js` и спавнят publisher.py из этой отдельной копии. Первая тестовая публикация после restart'а (task #909) отработала по **старому** коду, потому что:

- testbench repo был на 7 коммитов позади origin/testbench
- автоматический git-hook пушит commit в origin, но testbench репо сам не pull'ится
- нужен явный `cd /home/claude-user/autowarm-testbench && git pull --ff-only && sudo pm2 restart autowarm-testbench`

Это выполнено в этой же сессии:
```
$ cd /home/claude-user/autowarm-testbench
$ git stash; git pull --ff-only origin testbench; git stash pop
Fast-forward (7 commits)
$ sudo pm2 restart autowarm-testbench  # pid 1779848, restart#23
```

После этого testbench тоже имеет мою версию publisher.py / account_switcher.py.

**Надо отразить в памяти:** `reference_autowarm_git_hook.md` — git-hook пушит ТОЛЬКО в GenGo2/delivery-contenthunter. Для testbench (/home/claude-user/autowarm-testbench/) нужна отдельная вытяжка + restart pm2. Это добавит экономии времени в будущих deployment'ах.

## Post-deploy smoke (task #911) ✅

Первая публикация по новому коду после restart'а testbench'а — task #911, YouTube, testbench, failed (causa yt switcher, не связан с S3).

**DB snapshot:**
```
id=911 status=failed testbench=t platform=YouTube
screenshot_url=https://save.gengo.io/autowarm/screenshots/youtube/task911_publish_911_switch_yt_3_alt_avatar_probe_1777023952.png
screen_record_url=<S3 URL> (ожидаемо)
```

**events meta breakdown:**
```
Total events: 38
screenshots:  S3=20  relative/local=0   ✅
ui_dumps:     S3=21  relative/local=0   ✅
```

Samples:
- `https://save.gengo.io/autowarm/screenshots/youtube/task911_publish_911_switch_yt_1_feed_1777023590.png`
- `https://save.gengo.io/autowarm/ui_dumps/youtube/task911_switch_911_yt_1_feed_1777023590.xml`

**Log format change — тоже наблюдается:**
```
[account_switch] ui_dump step=yt_3_retap_probe2_fg_guard url=https://save.gengo.io/... usable=True bytes=33045
```
(раньше было `path=/tmp/autowarm_ui_dumps/...`)

**curl probe — публично доступны:**
```
$ curl -I https://save.gengo.io/autowarm/screenshots/youtube/task911_publish_911_switch_yt_3_retap_probe1_1777023881.png
HTTP 200  Content-Type: image/png

$ curl -I https://save.gengo.io/autowarm/ui_dumps/youtube/task911_switch_911_yt_3_retap_probe2_fg_guard_1777023907.xml
HTTP 200  Content-Type: application/xml
```

**UI check (https://delivery.contenthunter.ru/#publishing/publishing?sub=up%3Atasks → task #911 → лог):**
Ссылки 📸 shot #N и 📄 xml #N теперь ведут на S3 напрямую — открываются в браузере inline. Legacy (не-`http`) ссылки рендерятся серым со `line-through` и tooltip'ом (до-deploy задачи).

## Open items / follow-ups

- ✅ Prod-код автоматически залит в `/root/.openclaw/workspace-genri/autowarm/` (ветка `testbench`, git-hook push в GenGo2/delivery-contenthunter).
- ✅ Testbench-код синхронизирован в `/home/claude-user/autowarm-testbench/` (git pull + pm2 restart #23).
- ⚠️ **Prod non-testbench task smoke** пока не подтверждён (последняя prod публикация — task #902 в 05:52, до restart'а). При следующей реальной prod публикации ожидаем тот же S3 формат — путь через `scheduler.js → publisher.py из /root/.openclaw/...` с моим кодом.
- 🧹 TTL-очистка `/tmp/autowarm_{screenshots,ui_dumps}/` (find -mtime +3 -delete) — out of scope, отдельная infra-задача.

**Task id:** TBD (id > 908)
**Platform:** TBD
**Status:** TBD

**DB snapshot:**
```
SELECT id, status, screenshot_url, screen_record_url
FROM publish_tasks WHERE id = <TBD>;
```

**events JSONB sample (ключевое):**
```json
TBD — ожидаем meta.screenshots[*] и meta.ui_dumps[*] в формате
"https://save.gengo.io/autowarm/{screenshots|ui_dumps}/<platform>/task<id>_*.{png|xml}"
```

**curl probe по свежим URLs:**
```
TBD: HTTP 200 + Content-Type correct
```

**UI check:** https://delivery.contenthunter.ru/#publishing/publishing?sub=up%3Atasks → task #<TBD> → лог → клик по 📸 / 📄 → файл открывается.

## Rollback plan

1. Любая ошибка boto3 → graceful fallback на relative URL (уже встроен, публикация не падает).
2. Если массово шумит — env kill-switch:
   ```
   sudo pm2 restart autowarm --update-env AUTOWARM_S3_ARTIFACTS_DISABLE=1
   ```
3. Full revert: `cd /root/.openclaw/workspace-genri/autowarm && git revert 872d99b && sudo pm2 restart autowarm`.

## Memory / knowledge updates

- `reference_autowarm_artifacts.md`: обновить — скрины и UI dumps теперь льются на S3 тем же bucket'ом, что и screenrecords (prefix: `autowarm/screenshots/`, `autowarm/ui_dumps/`).
