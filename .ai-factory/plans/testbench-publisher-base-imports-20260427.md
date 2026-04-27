# PLAN — testbench phone #19: tasks залипают в `claimed` (NameError `ensure_adbkeyboard`)

**Тип:** fix (regression от publisher.py split)
**Создан:** 2026-04-27
**Режим:** full (полноценный план + ветка перед deploy)

**Репо:**
- Код: `/home/claude-user/autowarm-testbench/` (ветка `testbench` — production target для testbench-стенда)
- Контекст плана/evidence: `/home/claude-user/contenthunter/` (создаём отдельную fix-ветку)
- Prod autowarm `/root/.openclaw/workspace-genri/autowarm/` — на этом баге **не страдает** (HEAD `cb34d92`, ещё monolithic publisher.py 7000+ строк, `ensure_adbkeyboard` определён прямо в нём). В scope этого плана prod-autowarm НЕ deploy.

## Settings

- **Testing:** yes — smoke `python3 -c "import publisher_base"` + повторить для всех новых модулей split (publisher_kernel, publisher_instagram, publisher_tiktok, publisher_youtube). Pytest-юнит — если корпус суще­ствует и быстро прогоняется.
- **Logging:** verbose — `[fix-import] module=publisher_base added=ensure_adbkeyboard,...` в коммит-message; `[stuck-claimed-reset] N tasks reset to pending reason=name_error_recovery` в SQL-скрипте; pm2-логи после restart должны содержать `🚀 Публикация` без `[ERROR] run_publish_task error: name 'X' is not defined`.
- **Docs:** warn-only — evidence в `.ai-factory/evidence/testbench-publisher-base-imports-20260427.md` обязателен. Memory update — да: `project_publisher_modularization_wip.md` (отметить regression-tail) + `project_publish_testbench.md` (текущее состояние стенда).
- **Roadmap linkage:** none (`paths.roadmap` не настроен).

## Контекст — что наблюдается

Пользователь запустил публичный тестовый стенд https://delivery.contenthunter.ru/testbench.html.
- Все publish_tasks с `testbench=TRUE` и `created_at > NOW()-24h` стоят в `status='claimed'` (29 шт.).
- На phone #19 (`RF8YA0W57EP`, raspberry #7, ADB `82.115.54.26:15068`) по ADB **никаких UI-действий не происходит**.
- Phone #19 ONLINE: `adb -P 15068 devices` показывает RF8YA0W57EP в списке (18 устройств).
- Системный flag `testbench_paused=false`, `auto_fix_enabled=true` — стенд формально активен.
- Orchestrator (`autowarm-testbench-orchestrator.service`) работает корректно: каждые 10 мин создаёт новые tasks (Instagram → TikTok → YouTube round-robin), Groq генерит metadata, media-cursor крутится. Последняя created task #1312 [TikTok/user70415121188138] @ 09:51:47.

## Корневая причина

### RC: `NameError: name 'ensure_adbkeyboard' is not defined` в `publisher_base.py:2550`

PM2-app `autowarm-testbench` (worker, restarts=25 за 10 мин uptime — crash loop) **читает код из** `/home/claude-user/autowarm-testbench/` (split-версия после PR #3 «publisher-platform-split-20260425»).

Каждая task в логах:
```
[INFO] 🚀 Публикация: @<acc> | <Plat> | <kind> | задача #N
[INFO] 📱 Ориентация: портрет (user_rotation=0, accelerometer_rotation=0)
[ERROR] run_publish_task error: name 'ensure_adbkeyboard' is not defined
[INFO] [fixture] dumped #N → /home/claude-user/testbench-fixtures/N.tar.gz (xml_dumps=0)
[INFO] #N classified → unknown (status=claimed)
[INFO] exit task #N code=0 signal=null duration=2s
```

**Прямая проверка:**
```
$ grep -n "ensure_adbkeyboard\|from adb_utils\|import adb_utils" publisher_base.py
2550:        ensure_adbkeyboard(self.device_serial, self.adb_port, self.adb_host, log_fn=log.info)
```
**Только вызов, ни одного импорта.** Когда `run_publish_task()` доходит до этой строки — Python поднимает `NameError`, fixture-dumper отлавливает (общий `except Exception`) и аккуратно завершает worker exit_code=0. Task остаётся в `status='claimed'` (worker не маркирует её failed). Через 30 мин `reset stuck claimed tasks back to pending` возвращает её в очередь — следующий tick re-claim → тот же NameError → бесконечный loop. Те же 29 «зависших» строк с разными `updated_at` отображают именно этот цикл reset/re-claim.

Регрессия пришла из коммитов 26e48b7..bcb5a2d (PR #3 от 2026-04-25, «publisher-platform-split»):
- `bcb5a2d refactor(publisher): cleanup publisher.py — orchestrator-only`
- `b97f09a refactor(publisher): extract TikTokMixin + YouTubeMixin`
- `4989f77 refactor(publisher): extract InstagramMixin → publisher_instagram.py`
- `d355d59 refactor(publisher): extract kernel + base, add smoke imports test`

`publisher.py:30 from adb_utils import ensure_adbkeyboard` уцелел в orchestrator-only `publisher.py`, но при extract в `publisher_base.py` (где живёт реальный publisher class) импорт не перенесли. Smoke-тест из `d355d59` (если он только проверяет `import publisher_kernel`/`import publisher_base` без exec'а пути с этой строкой) пропустил баг — NameError детектируется только на runtime call, не на import.

### Дополнительная regression: worker не маркирует task `failed` после exception

Когда `run_publish_task()` ловит исключение и пишет fixture, он не делает `UPDATE publish_tasks SET status='failed' WHERE id=N`. Task залипает в `claimed` до 30-min `reset stuck` rescue. В результате: метрики 1h success-rate выглядят как 0% running / 100% claimed (ложный сигнал «стенд жив, просто медленный»), а не как 100% failed (правильный сигнал для autofix).

## Scope

**В scope:**
1. Найти ВСЕ потерянные при split импорты в `publisher_base.py` / `publisher_kernel.py` / `publisher_instagram.py` / `publisher_tiktok.py` / `publisher_youtube.py` (не только `ensure_adbkeyboard` — могут быть `adb_text`, `parse_ui_dump`, `find_anchor_bounds` и т.д.).
2. Восстановить импорты — `from adb_utils import ensure_adbkeyboard, adb_text` и любые другие, которые показывает grep `<symbol>(` без соответствующего `import` / `from ... import`.
3. Smoke `python3 -c "import publisher; from publisher_base import *; ..."` — без runtime-exec, но проверить что все имена резолвятся.
4. SQL-скрипт reset 29 застрявших claimed-tasks (после деплоя фикса, чтобы scheduler сразу подхватил их и проверил публикации end-to-end).
5. Hardening: в `run_publish_task()` exception-handler добавить `UPDATE publish_tasks SET status='failed', log=COALESCE(log,'') || E'\n' || %s WHERE id=%s` перед fixture-dump'ом. Это закрывает второй баг (claimed-trap) и улучшает метрики.
6. Deploy в testbench-репо `/home/claude-user/autowarm-testbench/`: коммит, push origin/testbench, `sudo pm2 restart autowarm-testbench`.
7. Monitor 30 мин — у нескольких task statuses должны переходить `pending → scheduled → claimed → running → done|failed`. На phone #19 по `adb shell dumpsys activity top` должно быть видно реальное взаимодействие с IG/TT/YT.
8. Memory + evidence update.

**НЕ в scope:**
- Deploy в prod autowarm `/root/.openclaw/workspace-genri/autowarm/` — там монолит без split-bug. Если в будущем будет миграция prod на split — отдельная задача (B11 из publisher-vision-followups).
- Фикс `adb_push_chunked_md5_mismatch` (P1 blocker из старого testbench-плана) — отдельный backlog item, требует SSH в Raspberry #7. Не блокирует diagnosis: NameError ломает task до того, как мы доходим до chunked push.
- Реанимация PM2 dump path drift в обратную сторону (worker → prod-dir) — testbench by design читает из `/home/claude-user/autowarm-testbench/` (memory `project_publish_testbench.md` явно фиксирует это).
- Vision pipeline regressions — отдельный план.
- Удаление дубликата `ensure_adbkeyboard` (одинаковая 1-line wrapper в `adb_utils.py:5-8`) — не блокирует, чистка отдельным PR.

## Задачи

### T1. Полный аудит потерянных импортов в split-модулях

**Цель:** не зафиксить только `ensure_adbkeyboard` и потом завтра словить тот же `NameError` для следующего символа.

Для каждого файла в `[publisher_base.py, publisher_kernel.py, publisher_instagram.py, publisher_tiktok.py, publisher_youtube.py]`:
- Получить список используемых символов из соседних модулей (`adb_utils`, `account_switcher`, `groq_client`, и т.д.):
  ```bash
  cd /home/claude-user/autowarm-testbench
  for f in publisher_base.py publisher_kernel.py publisher_instagram.py publisher_tiktok.py publisher_youtube.py; do
    echo "=== $f ==="
    python3 -c "import ast,sys; tree=ast.parse(open('$f').read()); \
      imports={n.name for node in ast.walk(tree) if isinstance(node,ast.Import) for n in node.names} | \
              {n.name for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) for n in node.names}; \
      print('IMPORTS:', sorted(imports))"
  done
  ```
- Сравнить с символами из `publisher.py` ДО split (HEAD~5 history): `git show 8a76e9c:publisher.py | grep -E '^(from|import)'` (resolve реальный pre-split SHA).
- Diff: что было импортировано, но в новом файле отсутствует и при этом используется (`grep -wn "<sym>(" file.py` хоть один call).
- Лог: `[audit] file=<f> missing_imports=[...] suspicious_calls=[...]`.

**Артефакт:** список символов на T2 (минимум `ensure_adbkeyboard`, возможно — `adb_text`, `parse_ui_dump`, `find_anchor_bounds`, `wait_for_window`, и т.п.).

### T2. Восстановить импорты в split-модулях

Для каждого файла из T1, в начале (после shebang/encoding/`__future__`):
- Добавить `from adb_utils import ensure_adbkeyboard, adb_text as _adb_text_util` (или нужный набор по факту T1 audit).
- Если символ уже импортирован под alias'ом в одном из соседних файлов — использовать тот же alias для consistency.
- Логирование на module-level — НЕ нужно (импорты тихие).

**Файлы (минимум):**
- `publisher_base.py` — `ensure_adbkeyboard` (точно).
- + другие из T1.

**Smoke (после правки):**
```bash
cd /home/claude-user/autowarm-testbench
python3 -c "import publisher_base; print('publisher_base OK', dir(publisher_base)[:5])"
python3 -c "import publisher_kernel; print('publisher_kernel OK')"
python3 -c "import publisher_instagram; print('publisher_instagram OK')"
python3 -c "import publisher_tiktok; print('publisher_tiktok OK')"
python3 -c "import publisher_youtube; print('publisher_youtube OK')"
python3 -c "from publisher import Publisher; print('publisher orchestrator OK')"
```
Все 5 строк должны печатать «OK». Любой `NameError` / `ImportError` на этом этапе — return to T1.

### T3. Hardening: пометить task `failed` при exception в `run_publish_task()`

Файл: `publisher_base.py` (или `publisher_kernel.py`, в зависимости где живёт `run_publish_task`). Найти `try/except` обёртку вокруг основного pipeline.

**Было (по логам):**
```python
try:
    # ... orientation check, navigation, upload ...
except Exception as e:
    log.error(f"run_publish_task error: {e}")
    self._dump_fixture(task_id)
    self._classify(task_id)  # → 'unknown'
    return  # ← здесь task остаётся в claimed
```

**Станет:**
```python
except Exception as e:
    log.error(f"run_publish_task error: {e}")
    err_msg = f"run_publish_task error: {type(e).__name__}: {e}"
    try:
        with self.db_conn.cursor() as cur:
            cur.execute(
                "UPDATE publish_tasks "
                "SET status='failed', "
                "    log=COALESCE(log,'') || E'\\n' || %s, "
                "    updated_at=NOW() "
                "WHERE id=%s AND status IN ('claimed','running')",
                (err_msg, task_id)
            )
            self.db_conn.commit()
        log.info(f"[task-fail] task=#{task_id} marked failed reason={type(e).__name__}")
    except Exception as db_err:
        log.error(f"[task-fail] failed to mark task #{task_id} as failed: {db_err}")
    self._dump_fixture(task_id)
    self._classify(task_id)
    return
```

Лог: `[task-fail] task=#N marked failed reason=NameError`.

(Опционально, если время позволит — emit `task_event(type='error', code='unhandled_exception', detail=err_msg)` в `publish_events`. Но не блокирует: triage всё равно заберёт по dump'у.)

### T4. SQL-скрипт reset 29 застрявших claimed-tasks

Файл: `scripts/reset-stuck-claimed-20260427.sql` (одноразовый):
```sql
-- Reset 29 testbench tasks stuck in 'claimed' due to publisher_base NameError regression.
-- After T2 deploy, scheduler should pick them up and run end-to-end.
\set ON_ERROR_STOP on
BEGIN;
WITH affected AS (
  SELECT id FROM publish_tasks
  WHERE testbench=TRUE
    AND status='claimed'
    AND created_at > NOW() - INTERVAL '24 hours'
)
UPDATE publish_tasks
SET status='pending',
    log=COALESCE(log,'') || E'\n[reset-stuck-claimed-20260427] back to pending after publisher_base import fix',
    updated_at=NOW()
WHERE id IN (SELECT id FROM affected);
SELECT COUNT(*) AS reset_count FROM affected;
COMMIT;
```
Запустить после T2/T3 deploy (T6) — НЕ ДО.

Лог: `[reset-stuck-claimed] reset_count=N`.

### T5. Commit + push в testbench branch

Из `/home/claude-user/autowarm-testbench/`:
```bash
git checkout testbench
git pull --ff-only origin testbench
# T2/T3 patches already in working tree
git diff --stat
git add publisher_base.py publisher_kernel.py publisher_instagram.py publisher_tiktok.py publisher_youtube.py
git commit -m "fix(publisher): restore lost adb_utils imports after split + mark tasks failed on exception

Регрессия от PR #3 (publisher-platform-split-20260425): publisher_base.py:2550 вызывает
ensure_adbkeyboard() без import → NameError на каждой publish_task → залипание в claimed.

T2: восстановлены импорты в <list-from-T1>.
T3: run_publish_task exception-handler теперь UPDATE status='failed' (раньше задача
оставалась в claimed до 30-min stuck-reset, портило метрики 1h success-rate).
"
git push origin testbench
```

(Если репо `autowarm-testbench` использует force-with-lease policy — следовать тому же стандарту.)

### T6. Restart PM2 worker + run reset SQL

```bash
sudo pm2 restart autowarm-testbench --update-env
sleep 10
sudo pm2 describe autowarm-testbench | grep -E "status|restarts|uptime"
# Expected: status=online, restarts=N+1, uptime=~10s
sudo pm2 logs autowarm-testbench --lines 30 --nostream | grep -v "^$"
# Expected: NO "name 'ensure_adbkeyboard' is not defined" lines
```

Затем reset:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw openclaw -f \
  /home/claude-user/autowarm-testbench/scripts/reset-stuck-claimed-20260427.sql
```

### T7. Monitor 30 мин на живом стенде

**Период наблюдения:** 30 мин = 1 полный round-robin цикл (IG → TT → YT, 10 мин на платформу).

Каждые 5 мин:
```bash
# Status breakdown
PGPASSWORD=openclaw123 psql -h localhost -U openclaw openclaw -c \
  "SELECT status, COUNT(*) FROM publish_tasks WHERE testbench=TRUE \
   AND created_at > NOW() - INTERVAL '1 hour' GROUP BY status;"

# Latest 5 tasks
PGPASSWORD=openclaw123 psql -h localhost -U openclaw openclaw -c \
  "SELECT id, status, platform, account, \
          EXTRACT(epoch FROM (NOW()-updated_at))::int AS sec_since_update \
   FROM publish_tasks WHERE testbench=TRUE ORDER BY id DESC LIMIT 5;"

# Phone #19 actual UI activity
adb -H 82.115.54.26 -P 15068 -s RF8YA0W57EP shell dumpsys activity top | grep -E "ACTIVITY|mFocused|ResumedActivity" | head -5
```

**Критерии успеха:**
- ≥1 task переходит `pending → scheduled → claimed → running → done` (или `failed` с конкретным `error_code` ≠ `unknown`).
- На phone #19 в `dumpsys activity top` видно `com.instagram.android` / `com.zhiliaoapp.musically` (TT) / `com.google.android.youtube` (не Launcher).
- В pm2 logs появляются содержательные `[publisher.ig.upload]` / `[publisher.tt.upload]` / `[publisher.yt.upload]` строки, а не только orientation-check + NameError.
- Распределение status в 1h: `done` или `failed` ≥1, `running` ≤1 (sequential), `claimed` ≤1.

**Если за 30 мин ни одна task не сменила status дальше `claimed` → откатить T2/T3 коммит, escalate.**

### T8. Evidence + memory update + commit в contenthunter

Файл: `/home/claude-user/contenthunter/.ai-factory/evidence/testbench-publisher-base-imports-20260427.md`. Содержит:
- Корневую причину (NameError ↔ split regression) с цитатой из pm2-logs.
- T1 audit output (полный список missing imports).
- T2/T3 diffs (краткие, ссылки на коммит SHA).
- T6 pm2 restart confirmation (status=online, no NameError в logs).
- T7 monitor — таблица 30-минутного наблюдения + 1-2 успешных скриншота `dumpsys activity top` с phone #19.
- 24-hour outcome (по факту, дополняем когда наберётся): сколько task ушло в `done` vs `failed`, какие новые error_codes всплыли (если есть).

Memory updates:
- `project_publisher_modularization_wip.md` — снять `✅ ОТГРУЖЕНО` или добавить tail: «split shipped, hidden NameError regression в publisher_base.py разрулена 2026-04-27 (см. evidence/testbench-publisher-base-imports). Memory утверждение «Prod deployed 7688ace» неточно — prod на cb34d92, monolith. Split в prod НЕ выкачен.»
- `project_publish_testbench.md` — добавить запись «2026-04-27: восстановлен после 11+ часов crash loop autowarm-testbench (NameError 'ensure_adbkeyboard'); добавлен exception→failed mark, чтобы метрики не врали».
- `feedback_pm2_dump_path_drift.md` — добавить нюанс: testbench-app **специально** работает из `/home/claude-user/autowarm-testbench/`, это by design. Path drift про prod-app `autowarm`, не testbench.

Коммит в `/home/claude-user/contenthunter/`:
```bash
cd /home/claude-user/contenthunter
git checkout main
git pull origin main
git checkout -b fix/testbench-publisher-base-imports-20260427
git add .ai-factory/plans/testbench-publisher-base-imports-20260427.md \
        .ai-factory/evidence/testbench-publisher-base-imports-20260427.md
git commit -m "docs(plan+evidence): testbench phone #19 NameError fix — restore lost imports after publisher.py split"
```
(WIP файлы из feature/farming-testbench-phone171 не трогаем — они на той ветке.)

## Commit Plan

8 задач → 2 commit-чекпоинта:

| Commit | После задач | Репо | Сообщение |
|---|---|---|---|
| 1 | T5 | autowarm-testbench (testbench) | `fix(publisher): restore lost adb_utils imports after split + mark tasks failed on exception` |
| 2 | T8 | contenthunter (fix/testbench-publisher-base-imports-20260427) | `docs(plan+evidence): testbench phone #19 NameError fix` |

## Риски

- **R1 — fix только `ensure_adbkeyboard` оставит другие cascading NameError'ы.** Mitigate: T1 audit делает полный grep ДО T2; smoke в T2 проверяет import всех 5 split-модулей.
- **R2 — T3 (mark failed) может конфликтовать с уже работающим reset-stuck-claimed cycle.** Mitigate: `WHERE status IN ('claimed','running')` в UPDATE — гарантия idempotency. Если reset уже вернул в pending — UPDATE no-op.
- **R3 — `sudo pm2 restart autowarm-testbench` рвёт текущую in-flight task.** Mitigate: при NameError-loop'е никаких useful in-flight нет, restart безболезненный.
- **R4 — После T6 на phone #19 всплывёт следующий blocker (`adb_push_chunked_md5_mismatch` из старого backlog).** Это ОК — открываем отдельный issue, фикс этого плана уже валиден (метрики начнут показывать правду + auto-fix triage снова получит реальные error_codes для классификации). T7 фиксирует что мы видим.
- **R5 — Прод autowarm на cb34d92 (monolith) — не split, без бага. Если кто-то когда-нибудь zoo-merge-нёт split в prod — баг повторится в prod без warning'а.** Mitigate: memory note + smoke-test `python3 -c "import publisher_base"` стоит добавить в pre-deploy chec­klist (отдельная задача, не блокирует).
- **R6 — autowarm-testbench dir может уехать вперёд за время диагностики (соседний Claude session).** Mitigate: `git pull --ff-only origin testbench` в T5 перед коммитом; конфликт → re-audit с актуальным HEAD.

## Rollback

- Commit 1: `git revert <SHA>` в `/home/claude-user/autowarm-testbench/` + `sudo pm2 restart autowarm-testbench`. Возвращает прежнее состояние (NameError-loop, но известный — лучше чем неизвестный новый bug).
- Commit 2: docs-only, revert не нужен.
- SQL T4: одноразовый, само-completing — таски пройдут весь цикл pending→… в любом случае. Если revert-нем код — таски снова уйдут в claimed-loop, но это известное поведение «как было до фикса».

## Дальше

Исполнять через `/aif-implement`. Порядок: T1 → T2 → T3 → smoke → T5 (commit #1) → T6 → T4 SQL → T7 monitor (30 мин) → T8 → commit #2.
