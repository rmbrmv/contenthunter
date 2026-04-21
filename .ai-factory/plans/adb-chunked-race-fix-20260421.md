# PLAN — Fix `adb_push_chunked_failed` race + testbench hygiene (full)

**Создан:** 2026-04-21
**Тип:** fix (infra + publisher.py + scheduler)
**Статус:** ready-for-approve (ждёт «да, делаем» → кодим)
**Целевой репо:** `/home/claude-user/autowarm-testbench/` (ветка `testbench`, НЕ прод `main`)
**План живёт:** `contenthunter/.ai-factory/plans/adb-chunked-race-fix-20260421.md`
**Память:** `project_publish_testbench.md`, `project_adb_push_network_issue.md`
**Правило:** `agents/main/AGENTS.md` — Show Plan First → Wait for "go" → Then Act.

## Settings

| | |
|---|---|
| Testing | smoke-only — pytest `tests/test_adb_push_chunked.py` расширить кейсом concurrent-call; ручной smoke через orchestrator на phone #19 |
| Logging | **verbose** для scheduler tick/claim и для chunked-push path (каждый параллельный tap → event + stderr) |
| Docs | warn-only (инфра-фикс, без продуктовых доков) |
| Roadmap linkage | skipped |
| Language | ru |
| Branches | `testbench` (уже чекаут) — commit'им туда, `main` прод publisher'а не трогаем |

## 0. TL;DR

14 × `adb_push_chunked_failed` + 11 × `adb_push_chunked_md5_mismatch` за сутки — **не баг chunked-push**, а гонка двух параллельных `testbench_scheduler.js` (PID 3033737 claude-user + 3087290 root), которые оба читают `publish_tasks WHERE testbench=TRUE AND status='pending' ORDER BY id LIMIT 1` **без** `FOR UPDATE SKIP LOCKED` и спавнят два `publisher.py` на одну задачу. Параллельные `_adb_push_chunked` пушат одни и те же chunk-пути на устройстве, один успевает `cat > remote && rm -f chunks`, второй ловит `cat_merge_failed` (или оба перетирают друг друга → remote_md5 = MD5 пустого файла `d41d8cd9…`).

Fix в 3 слоя: (T1) убить дубликат + flock, (T2) `FOR UPDATE SKIP LOCKED` + транзакционный `claim`, (T3) уникальный UUID-suffix в remote chunk path на вызов. (T4) — документационный: синхронизировать память с реальной inline-triage архитектурой.

Отказ от нарезки чанков **не рассматриваем** — она введена из-за 20% packet loss на hop 4 (TimeWeb, user-owned ticket), убрать = вернуть `adb_push_timeout` на медиа >5MB.

## 1. Задачи

Обозначения: **F** = fast (< 1h), **M** = medium (1-4h). Все пути в `/home/claude-user/autowarm-testbench/` если не указано иное.

### T1 [F] — Убить дубликат scheduler'а + flock [code ready; deployed 14:09 UTC]

- **Диагноз:** `pm2 list` пустой, но `ps aux | grep testbench_scheduler` → 2 процесса (PID 3033737 `node -e require(./testbench_scheduler.js)` и 3087290 `node /home/.../testbench_scheduler.js`). Ни один не под PM2.
- **Действия:**
  1. `SIGTERM` обоим Node PID (graceful): `kill 3033737 3087290` (через 60с форс-check). **ВНИМАНИЕ:** в момент kill'а может быть запущенный publisher.py — подождать `running.size == 0` в логах или явный exit-код publisher.
  2. Старт одного процесса под PM2: `cd /home/claude-user/autowarm-testbench && pm2 start ecosystem.testbench.config.js`. (Может потребоваться `sudo pm2` — проверить, чей pm2-daemon владеет списком. Memory `feedback_server_access.md` даёт NOPASSWD на pm2.)
  3. В `testbench_scheduler.js` — перед `await main()` добавить flock через native `fs.openSync` + `flock` (npm пакет `proper-lockfile` или syscall через `child_process.execSync('flock -xn /var/lock/autowarm-testbench-scheduler.lock -c true')`). Если lock не взят → `log('FATAL', 'another scheduler instance holds the lock')` + `process.exit(1)`.
- **Файл:** `testbench_scheduler.js` — после dotenv.config, до `main()`.
- **Логирование:** `log('INFO', 'lock acquired: /var/lock/autowarm-testbench-scheduler.lock')` на старте, `log('ERROR', 'lock held by PID=<x>, exiting')` на коллизии.
- **Test:** после T1 старт `pm2 start ecosystem.testbench.config.js` дважды подряд → второй PM2-воркер сразу падает с ERROR в логах. `pm2 list` → ровно 1 инстанс в `online`.

### T2 [F] — `FOR UPDATE SKIP LOCKED` + транзакционный claim [code ready]

- **Файл:** `testbench_scheduler.js` — функция `tick()` (строки 46-83).
- **Диагноз:** сейчас `SELECT id FROM publish_tasks WHERE testbench=TRUE AND status='pending' ORDER BY id LIMIT 1` → любой конкурентный читатель видит ту же задачу.
- **Действия:**
  1. Обернуть SELECT + UPDATE в одну транзакцию через `pool.connect()` + `BEGIN/COMMIT`.
  2. SQL:
     ```sql
     BEGIN;
     SELECT id, device_serial, platform, account, project
       FROM publish_tasks
       WHERE testbench = TRUE AND status = 'pending'
       ORDER BY id ASC LIMIT 1
       FOR UPDATE SKIP LOCKED;
     -- если есть row:
     UPDATE publish_tasks SET status = 'claimed', updated_at = NOW() WHERE id = $1;
     COMMIT;
     ```
  3. Publisher.py уже ставит `status='running'` при старте и `status='failed'/'completed'` на выходе → статус `claimed` читается только scheduler'ом, publisher'ом переписывается (это OK, semantics clean).
  4. Bonus: cleanup старых `claimed` (stuck >30 мин) в `cleanFinished()` → `UPDATE ... SET status='pending' WHERE status='claimed' AND updated_at < NOW() - INTERVAL '30 minutes'` (резерв от зависшего scheduler'а).
- **Логирование:** `log('DEBUG', 'claim failed — no pending tasks')` на пусто, `log('INFO', 'claimed task #N')` на success, `log('WARN', 'reset N stuck claimed tasks')` при cleanup.
- **Test:** ручной INSERT двух `pending` testbench-задач. Запустить два scheduler'а одновременно в тестовой среде (docker или `flock -u` override) → каждый получает свою, не одну и ту же. SELECT из `publish_tasks` показывает `claimed`/`running`, не конфликтует.

### T3 [F] — Уникальный UUID-suffix в remote chunk path [code ready]

- **Файл:** `publisher.py` — функция `_adb_push_chunked` (строки 669-856), функция `_split_file_into_chunks` (552-576), helper `_cleanup_chunks_on_device` (590-612).
- **Диагноз:** `task_tag = str(os.getpid())` (line 680) уникален per-process, но если кто-то запустит два publisher'а на одной Pi с одним device_serial (race case Т1/Т2 пропущен, или future concurrency > 1) — remote_chunk paths столкнутся: `{remote_path}.chunk.0001` одинаковый.
- **Действия:**
  1. В `_adb_push_chunked` строка 680: заменить
     ```python
     task_tag = str(os.getpid())
     ```
     на
     ```python
     import uuid
     task_tag = f'{os.getpid()}-{uuid.uuid4().hex[:8]}'
     ```
  2. Remote path формируется из `task_tag` → в строке 710 изменить на:
     ```python
     remote_chunk = f'{remote_path}.{task_tag}.chunk.{idx:04d}'
     ```
     (добавить task_tag в имя, не только в local).
  3. После cat-merge (строки 739-762) успешно — chunks с уникальным suffix уже удалены через `&& rm -f`. Defensive cleanup в `finally:` (`_cleanup_chunks_on_device`) остаётся.
  4. Final merged file = `remote_path` (без task_tag) — оригинальный контракт с caller сохранён.
- **Логирование:** `log.info(f'  chunked path isolation: task_tag={task_tag}')` в `_adb_push_chunked` сразу после генерации tag'а.
- **Test:** `tests/test_adb_push_chunked.py` — добавлен кейс `test_concurrent_chunked_push_remote_paths_isolated` [11/11 passed]:
  ```python
  def test_concurrent_chunked_push_isolation(tmp_path, monkeypatch, mock_adb):
      """Два параллельных _adb_push_chunked на одном device не должны столкнуться."""
      # mock_adb шлёт все cat-cmd и rm-cmd в список, проверяем что chunk paths
      # не пересекаются между двумя вызовами.
      import threading
      pub1 = build_publisher(...)
      pub2 = build_publisher(...)
      media = tmp_path / 'video.mp4'
      media.write_bytes(b'X' * (3 * 1024 * 1024))  # 3MB → 3 chunks
      results = []
      def run(p): results.append(p._adb_push_chunked(str(media), '/sdcard/out.mp4',
                                                     reason='test', size_mb=3, canary_ms=100))
      t1 = threading.Thread(target=run, args=(pub1,))
      t2 = threading.Thread(target=run, args=(pub2,))
      t1.start(); t2.start(); t1.join(); t2.join()
      # Оба должны вернуть (True, None); mock_adb НЕ должен видеть дубликаты chunk paths.
      assert all(r[0] for r in results)
      all_chunk_paths = [cmd for cmd in mock_adb.commands if '.chunk.' in cmd]
      assert len(all_chunk_paths) == len(set(all_chunk_paths))
  ```

### T4 [F] — Синхронизация памяти + inline-triage фиксация [done]

- **Диагноз (found during this investigation):** `triage_dispatcher.py` **никогда не был написан**. `autowarm-triage-dispatcher.service` systemd unit **никогда не существовал** на VPS. Оригинальный T5 из `publish-testbench-agent-20260421.md` заменён на inline-вызов `triage_classifier.process_failed_task(task_id)` из `publisher.py:6717` finally-блока. Inline-архитектура работает (cadence 10 мин, диагноз ~30 сек, очередь не растёт). Агент-диагност дал 5 отчётов, $0.0087 суммарно.
- **Действия:**
  1. Обновить memory `project_publish_testbench.md` — секция «Компоненты на VPS»: удалить строку про `autowarm-triage-dispatcher.service`. Секция «Flow полной петли»: заменить `triage_dispatcher.process_failed_task` на `triage_classifier.process_failed_task` (inline in publisher.py).
  2. В этом плане (adb-chunked-race-fix-20260421.md) оставить decision-log о том, что inline-архитектура — принятое упрощение относительно оригинального T5 (задокументировано здесь + в memory).
  3. НЕ строить dispatcher сейчас. Критерий переезда на async NOTIFY: cadence > 6/час ИЛИ диагноз > 2 мин ИЛИ очередь failed блокирует scheduler. Текущая нагрузка — inline ок.
- **Файл:** `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_publish_testbench.md`.
- **Логирование:** `publisher.py:6715-6720` уже логирует triage-вызов на info; проверить, что есть `triage_err` fallback в warn при фейле classifier'а — если нет, добавить.
- **Test:** grep после edit — все упоминания `triage_dispatcher` остаются только в явных отрицаниях («НЕ через dispatcher», «не построен»); `triage_classifier` упомянут как inline-реализация. [actual: 1 негация + 1 classifier — зафиксировано как принятая архитектура]

## 2. Acceptance — стенд здоров

После всех четырёх T'ов запустить orchestrator на 1 час (6 задач) и получить:
- `testbench-status.sh`: `pm2 list` показывает 1 inst `autowarm-testbench online`.
- `ps aux | grep testbench_scheduler` ровно 1 Node PID.
- `publish_tasks WHERE testbench=TRUE AND created_at > NOW()-INTERVAL '1 hour'`: **≥ 1 success**, `adb_push_chunked_failed=0`, `adb_push_chunked_md5_mismatch=0`.
- В events.json любого fixture — ровно один `adb_push_chunked_started` на task (не два).

Если за 1 час 0 success, но также 0 chunked errors — значит race убрали, но вылезла другая (`unknown`/`yt_accounts_btn_missing`/selector_drift). Это уже не в scope этого плана — отдельный триаж.

## 3. Commit Plan

< 5 задач — один commit в конце всех четырёх T'ов:

```
fix(testbench): eliminate adb_push_chunked race caused by duplicate scheduler

- scheduler: flock + FOR UPDATE SKIP LOCKED transactional claim
- publisher: UUID-suffix in remote chunk paths (defense-in-depth)
- memory: sync inline-triage architecture (no dispatcher service)

Root cause: two testbench_scheduler.js processes (claude-user PID 3033737 +
root PID 3087290) read 'pending' tasks without row lock, spawn parallel
publisher.py on same task_id → _adb_push_chunked race on identical remote
chunk paths → cat_merge_failed or remote_md5=empty file.

Fix verified by 1h orchestrator run on phone #19 after deploy.

Ref: .ai-factory/plans/adb-chunked-race-fix-20260421.md
```

Untracked evidence files (`evidence/publish-triage/tt_bottomsheet_closed-*.md`,
`unknown-*.md`) — закоммитить отдельным `chore(evidence)` либо оставить untracked
(они дампятся per-run, вопрос housekeeping'а, не этого фикса).

## 4. Post-implementation housekeeping (опционально, не блокирует close)

- Починить `/usr/local/bin/testbench-status.sh` — сейчас показывает `restarts: 3087290` (это PID, а не restart count). Скрипт парсит `pm2 describe` когда app не в PM2 — возвращает garbage. Fix: проверить `pm2 jlist | jq '.[] | select(.name=="autowarm-testbench")'` сначала, fallback на «not in PM2».
- Добавить в `agent_diagnose` error_code `adb_push_chunked_failed` маркер `human_review_required=true` (он уже так помечен в отчёте, но не в DB `publish_error_codes.is_auto_fixable` — хотя там `f`, значит OK).
- Рассмотреть повышение `publish_error_codes.adb_push_chunked_failed.is_auto_fixable` до TRUE **после** T1-T3 фикса, с fix_module = «восстановление через direct push без chunks, если canary_ms < 200». Отдельная задача, не в этом плане.
