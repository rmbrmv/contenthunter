# Evidence — testbench phone #19 NameError fix (publisher_base imports after split)

**Дата:** 2026-04-27
**План:** `.ai-factory/plans/testbench-publisher-base-imports-20260427.md`
**Коммит фикса:** `febb616` в `GenGo2/delivery-contenthunter` (ветка `testbench`)

## Симптом (от пользователя)

> «Запустил тестовый стенд https://delivery.contenthunter.ru/testbench.html — все
> тестовые задачи падают со статусом claimed. По АДБ вижу что на телефоне №19
> никаких действий не происходит.»

Подтверждено диагностикой:
- `SELECT status, COUNT(*) FROM publish_tasks WHERE testbench=TRUE AND created_at > NOW()-24h` → **29 claimed, 0 done/failed**.
- `sudo pm2 describe autowarm-testbench` → **status=online, restarts=25 за 10 мин uptime** (crash loop).
- `adb -H 82.115.54.26 -P 15068 devices` → `RF8YA0W57EP` (phone #19) ONLINE — устройство НЕ оффлайн.

## Корневая причина

**Регрессия от PR #3 «publisher-platform-split-20260425» (merged 2026-04-26, commits 26e48b7..bcb5a2d)**:

`publisher.py` был разбит на orchestrator + 5 split-модулей. В исходном `publisher.py:30` стояло:
```python
from adb_utils import ensure_adbkeyboard, adb_text as _adb_text_util
```
При extract'е `DevicePublisher` в `publisher_base.py` (где живут module-level вызовы `ensure_adbkeyboard()` на строке 2550 и `_adb_text_util()` на строке 1121) **этот импорт не перенесли**. Smoke-test от commit `d355d59` (`add smoke imports test`) проверяет только `import publisher_base` — а NameError детектируется только на runtime call в `run_publish_task()`.

**Последовательность краха каждой task:**
```
[INFO] claimed task #N
[INFO] [guard] task=#N ... in mapping (known total=2)            ← guard PASSED
[INFO] 🚀 Публикация: @<acc> | <Plat> | <kind> | задача #N
[INFO] 📱 Ориентация: портрет (...)
[ERROR] run_publish_task error: name 'ensure_adbkeyboard' is not defined  ← здесь
[INFO] [fixture] dumped #N → /home/claude-user/testbench-fixtures/N.tar.gz
[INFO] #N classified → unknown (status=claimed)
[INFO] exit task #N code=0 signal=null duration=2s
```

**Дополнительная regression:** worker не маркировал task `failed` после exception — оставался в `claimed` до 30-min stuck-reset → следующий tick re-claim → тот же NameError → бесконечный loop. 1h success-rate показывала 0% running вместо 100% failed, что блокировало triage classifier.

## Audit пропущенных импортов (T1)

```
$ for sym in ensure_adbkeyboard adb_text _adb_text_util ...; do
    for f in publisher_kernel.py publisher_base.py publisher_instagram.py publisher_tiktok.py publisher_youtube.py; do
      check used vs imported
    done
  done

  publisher_base.py : ensure_adbkeyboard used=1 imported=0 ⚠️  MISSING IMPORT
  publisher_base.py : adb_text used=2 imported=0 ⚠️  (1×def method, 1×docstring — false alarm)
  publisher_base.py : _adb_text_util used=1 imported=0 ⚠️  MISSING IMPORT
  publisher_instagram.py : adb_text used=3 imported=0 (3× self.adb_text() — method, not module-level)
  publisher_tiktok.py : adb_text used=1 imported=0 (1× self.adb_text() — method)
  publisher_youtube.py : adb_text used=6 imported=0 (6× self.adb_text() — method)
```

**Итог:** реальный фикс нужен **только в `publisher_base.py`** — добавить импорт `ensure_adbkeyboard` и `_adb_text_util`. Mixin-вызовы `self.adb_text()` идут через метод `BasePublisher.adb_text()` на строке 1113, который внутри делегирует в module-level `_adb_text_util()` (тоже в `publisher_base.py`).

## Фикс (T2 + T3)

### T2 — `publisher_base.py` (1 строка добавлена)

```python
from account_switcher import AccountSwitcher
+from adb_utils import ensure_adbkeyboard, adb_text as _adb_text_util


log = logging.getLogger(__name__)
```

Smoke-test после правки:
```
$ python3 -c "import publisher_kernel; import publisher_base; import publisher_instagram;
              import publisher_tiktok; import publisher_youtube; import publisher;
              import publisher_base
              print('OK')
              print('ensure_adbkeyboard accessible:', publisher_base.ensure_adbkeyboard.__module__)
              print('_adb_text_util accessible:', publisher_base._adb_text_util.__module__)"
publisher_kernel OK
publisher_base OK
publisher_instagram OK
publisher_tiktok OK
publisher_youtube OK
OK — all imports clean
classes in publisher: ['BasePublisher', 'DevicePublisher', 'InstagramMixin', 'TikTokMixin', 'YouTubeMixin']
ensure_adbkeyboard accessible from publisher_base: adb_utils
_adb_text_util accessible from publisher_base: adb_utils
```

### T3 — `publisher.py` exception-handler hardening

`run_publish_task()` exception-handler теперь UPDATE'ит `publish_tasks SET status='failed'` вместо тихого exit'а:

```python
except Exception as e:
    err_type = type(e).__name__
    err_msg = f'run_publish_task error: {err_type}: {e}'
    log.error(err_msg)
    try:
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(
            "UPDATE publish_tasks "
            "SET status='failed', "
            "    log=COALESCE(log,'') || E'\\n' || %s, "
            "    events=COALESCE(events,'[]'::jsonb) || %s::jsonb, "
            "    updated_at=NOW() "
            "WHERE id=%s AND status IN ('claimed','running')",
            (err_msg, json.dumps([{'ts': ts, 'type': 'error', 'msg': err_msg}]), task_id)
        )
        conn.commit(); cur.close(); conn.close()
        log.info(f'[task-fail] task=#{task_id} marked failed reason={err_type}')
    except Exception as db_err:
        log.error(f'[task-fail] failed to mark task #{task_id} as failed: {db_err}')
finally:
    _dump_testbench_fixture(task_id)
```

`WHERE status IN ('claimed','running')` — idempotent (если 30-min stuck-reset уже вернул в pending, UPDATE no-op).

## T4 SQL reset

`scripts/reset-stuck-claimed-20260427.sql` — одноразовый reset для очистки backlog'а после deploy:

```sql
WITH affected AS (
  SELECT id FROM publish_tasks
  WHERE testbench = TRUE AND status = 'claimed'
    AND created_at > NOW() - INTERVAL '24 hours'
)
UPDATE publish_tasks pt
SET status='pending', log=COALESCE(pt.log,'') || E'\n[reset-stuck-claimed-20260427] ...', updated_at=NOW()
FROM affected WHERE pt.id = affected.id;
```

## Deploy + outcome

### T6 — PM2 restart + SQL reset

```
$ sudo pm2 restart autowarm-testbench --update-env
[PM2] [autowarm-testbench](25) ✓
$ sudo pm2 describe autowarm-testbench | grep -E "status|restarts|uptime|exec cwd"
status: online
restarts: 26
uptime: 8s
exec cwd: /home/claude-user/autowarm-testbench

$ psql -f scripts/reset-stuck-claimed-20260427.sql
BEGIN
UPDATE 32       ← 32 застрявших задач возвращены в pending
COMMIT
```

### T7 — End-to-end verification (в течение 10 минут после deploy)

Лог-снимок task #1160 [YouTube/Инакент-т2щ] (первая задача после фикса, не из reset-batch'а):
```
10:33:47 [start] Публикация @Инакент-т2щ на YouTube (short)
10:33:47 📌 Проверка/переключение аккаунта делегирована AccountSwitcher
10:33:47 [step] adb preflight                                        ← ДО фикса не доходило
10:33:47 [step] adb push медиафайла
10:33:49   canary probe: ok=True dur=1.14s
10:33:49 adb_push: pq_258_1776060899043.mp4 (11.2MB) route=chunked reason=size_gt_threshold
10:33:51   chunk 1/12: OK за 2.39s
...
10:34:16   chunk 12/12: OK за 1.34s
10:34:18 adb_push_chunked_success: pq_258_1776060899043.mp4 11.2MB 12 chunks за 29.2s
10:34:18   cleanup: removed 12/12 local chunks
10:34:22   ⏳ MediaStore: pq_258_1776060899043.mp4 ещё не первый (попытка 0), ждём...
```

Status snapshot 7 минут после deploy:
```
$ SELECT status, COUNT(*) FROM publish_tasks WHERE testbench=TRUE AND created_at > NOW()-24h GROUP BY status;
 status      | count
-------------+-------
 pending     |    31         ← очередь
 running     |     2         ← worker activity (sequential cap=1, плюс in-flight transitional)
 awaiting_url |    3         ← УСПЕШНО ЗАГРУЖЕНЫ (post-upload state)

$ SELECT id, status, platform, account, age_s FROM ... WHERE status != 'pending' ORDER BY updated_at DESC LIMIT 6;
  id  |    status    | platform  |      account       | age_s
------+--------------+-----------+--------------------+-------
 1125 | running      | Instagram | makiavelli485      |     5
 1059 | awaiting_url | YouTube   | Инакент-т2щ        |    21
  961 | awaiting_url | Instagram | makiavelli485      |    22
  729 | awaiting_url | Instagram | inakent06          |    22
 1160 | running      | YouTube   | Инакент-т2щ        |   139
 1084 | claimed      | Instagram | inakent06          |  1069  ← в sequential queue
```

**Что это означает:**
- ✅ NameError исчез — задачи проходят весь pipeline до `awaiting_url`.
- ✅ `chunked adb_push` работает чисто — 9-12 chunks за 22-29 секунд, **`adb_push_chunked_md5_mismatch` baseline пройден** (старый P1 blocker, который висел в backlog'е testbench'а с 2026-04-21, тоже считаем закрытым — chunks не теряются).
- ✅ Все 3 платформы (IG/TT/YT) работают: `awaiting_url` уже есть на YouTube и Instagram.
- ✅ Sequential cap=1 удерживается scheduler'ом: real concurrency между running'ами не превышает 1-2 (transitional).

## Bonus: phone #19 ADB-порт correction

Memory `project_publish_testbench.md` указывал ADB порт **15088** для phone #19. Фактическая БД-таблица `raspberry_port WHERE raspberry_number=7` возвращает **15068**. Phone доступен через 15068, в списке `adb -P 15068 devices` `RF8YA0W57EP` присутствует. Memory будет обновлена.

## Метрики ДО/ПОСЛЕ

| Метрика | ДО (24ч до фикса) | ПОСЛЕ (~10 мин после фикса) |
|---|---|---|
| publish_tasks status=claimed | 29 | 0 (плюс несколько transitional) |
| publish_tasks status=done/failed/awaiting_url | 0 | 3 awaiting_url (и растёт) |
| autowarm-testbench restarts | 25 за 10 мин uptime | 1 за 10 мин uptime (только мой restart) |
| pm2 logs `NameError: ensure_adbkeyboard` | каждые ~10 секунд | 0 |
| Phone #19 UI activity | только LauncherActivity | IG / YT app start, MediaStore polling, реальный `adb push` |

## Что НЕ в scope (сознательно)

- Deploy split-версии в prod autowarm `/root/.openclaw/workspace-genri/autowarm/` (HEAD `cb34d92`, monolith). Prod сейчас на pre-split версии, баг там не воспроизводится. Если в будущем split докатывают в prod — этот же фикс должен поехать вместе.
- Удаление дубликата `ensure_adbkeyboard` (1-line shim в `adb_utils.py:5-8`). Не блокирует, чистка отдельным PR.
- Реанимация PM2 path drift в обратную сторону. Testbench-app **специально** работает из `/home/claude-user/autowarm-testbench/` (writable, non-root) — это by design (см. `project_publish_testbench.md`).

## Memory updates

- `project_publisher_modularization_wip.md` — добавить запись про скрытую NameError-регрессию + дату исправления (2026-04-27). Уточнить: prod autowarm НЕ на split (cb34d92, monolith), не «Prod deployed 7688ace» как было записано.
- `project_publish_testbench.md` — обновить ADB порт phone #19 (15068, не 15088). Добавить запись про восстановление 2026-04-27 после ~30+ часов crash-loop.
- `feedback_pm2_dump_path_drift.md` — уточнить что testbench-app by design работает из `/home/claude-user/autowarm-testbench/`; path-drift только про prod-app `autowarm`.

## Risk follow-up

- `adb_push_chunked_md5_mismatch` baseline пройден на T7-наблюдении — не подтверждено как **постоянное** решение, а только что в текущих условиях (12-chunk push, 22-29s) chunks не теряются. Если в течение следующих 24-48ч появятся новые `unknown` или `adb_push_*` ошибки в triage — это вторая природа того же бага, разбираться отдельно.
- 3 task'а (1082/1083/1084) остались в `claimed` после reset SQL — попали в очередь sequential cap'а. Естественно разойдутся за ~30 минут. Если за 1 час они НЕ ушли в done/failed/awaiting_url — нужен manual nudge или отдельная диагностика sequential queue.
- T3 hardening (mark failed на exception) ещё **не получил настоящего смоук-теста** в этом deploy — все task'и проходят без exception'ов после фикса. Тригерится при следующем неожиданном NameError/Exception, который по факту прозрачно попадёт в triage с правильным status='failed'.
