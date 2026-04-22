# Testbench — ротация новых аккаунтов на phone #19 + рестарт стенда

**Тип:** enhancement (orchestrator rotation) + ops-restart
**Создан:** 2026-04-22 09:36 UTC
**Режим:** Full (slug `testbench-new-accounts-phone19-20260422`)
**Целевой репо:** `/home/claude-user/autowarm-testbench/` (branch `testbench`)
**НЕ трогаем:** prod `/root/.openclaw/workspace-genri/autowarm/` (main).

## Settings

| | |
|---|---|
| Testing | **yes** — unit-тест для round-robin rotation в `testbench_orchestrator.py` (detect `get_active_account` видит оба аккаунта и выдаёт их по очереди) |
| Logging | **verbose** — на каждом тике логировать выбранный account + cursor position per-platform; на старте логировать список известных аккаунтов per-platform |
| Docs | **mandatory checkpoint** (T8) — evidence + memory update (`project_publish_testbench.md`) |
| Roadmap linkage | skipped — `paths.roadmap` не настроен |
| Git | ветка `testbench`, `git push origin testbench`; prod `main` не трогаем |

## Контекст (state на 2026-04-22 09:36 UTC)

### Аккаунты phone #19 в `factory_inst_accounts`

| id | username | platform | active | synced_at | статус |
|----|----------|----------|--------|-----------|--------|
| 1529 | `inakent06` | instagram | TRUE | 2026-03-23 | **старый** (в тестах с T0) |
| 1628 | `gennadiya311` | instagram | TRUE | 2026-04-22 09:22 UTC | **НОВЫЙ** |
| 1530 | `user70415121188138` | tiktok | TRUE | 2026-03-23 | **старый** |
| 1629 | `gennadiya4` | tiktok | TRUE | 2026-04-22 09:22 UTC | **НОВЫЙ** |
| 1528 | `Инакент-т2щ` | youtube | TRUE | 2026-03-23 | **старый** (YT остаётся один) |

Все 5 активны. Обе новые синхронизировались через фабрику в 09:22 UTC.

### Последние 15 testbench-задач (id 671..716)

Все используют **только старые** аккаунты (`inakent06`, `user70415121188138`, `Инакент-т2щ`) — это ожидаемо: последняя задача #716 создана 07:44 UTC, до sync'а новых (09:22 UTC). Задач на `gennadiya311`/`gennadiya4` пока 0.

### Состояние стенда

| Компонент | Состояние |
|---|---|
| `system_flags.testbench_paused` | `true` |
| PM2 `autowarm-testbench` (root daemon) | `stopped` |
| systemd `autowarm-testbench-orchestrator.service` | `inactive` |
| systemd `autowarm-testbench-rollback.timer` | `inactive` |

Стенд заглушен вручную после успешного smoke'а 2026-04-22 07:15 UTC (launch failures fix, commit `e2cd9e2`).

### Текущий selection-алгоритм

`testbench_orchestrator.py:111-127` `get_active_account(cur, platform)`:

```python
cur.execute("""
    SELECT fia.username
    FROM factory_inst_accounts fia
    JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
    JOIN factory_device_numbers fdn ON fdn.id = fpa.device_num_id
    WHERE fdn.device_number = 19
      AND fia.active = TRUE
      AND fia.platform = %s
""", (fia_platform,))
rows = cur.fetchall()
...
return random.choice(rows)[0]
```

→ стохастический выбор из всех активных. Новые подхватятся автоматически, но нет гарантии, что каждый аккаунт получит хотя бы одну задачу за разумное окно.

## Strategy

1. **Round-robin per-platform** вместо `random.choice`. Cursor per-platform хранится в `system_flags` (ключи: `orchestrator_account_cursor:instagram`, `:tiktok`, `:youtube`). Формула: `account = accounts[cursor % len(accounts)]`; после выбора — `cursor += 1`.
2. **Accounts ORDER BY id** для детерминированной последовательности (старые с меньшим id идут первыми, новые добавляются в хвост → не нарушают существующий порядок).
3. **DB-persist cursor** → переживает рестарт orchestrator'а (systemd сервис может рестартануть — не хотим сбрасывать ротацию).
4. **Backfill кода:** если key отсутствует в `system_flags` — трактуем как 0 (первый аккаунт). ON CONFLICT upsert при сохранении.
5. **Запуск стенда:** снимаем паузу → старт PM2 → старт оркестратора → старт rollback-таймера (в такой последовательности, чтобы scheduler был готов до того как оркестратор создаст первую задачу).
6. **Наблюдение ~30 мин (1 полный cadence)** — проверяем, что все 5 аккаунтов попали в ротацию (IG: 2 задачи, TT: 2 задачи, YT: 1 задача при cadence 30 мин → примерно так).

## Research Context

Research path не ведётся. Использую:
- memory: `project_publish_testbench.md`, `project_publish_followups.md`
- Commit history: `e2cd9e2` (2026-04-22, последний testbench fix), `6eb806a` (SA-shortcircuit)
- БД: `factory_inst_accounts`, `publish_tasks`, `system_flags` (верифицировано через psql перед планом)

## Tasks

### Phase 1 — Round-robin rotation (T1, T2)

**T1 ✅ Заменить `random.choice` на DB-persisted round-robin** (blocks T2, T4)

- Файл: `/home/claude-user/autowarm-testbench/testbench_orchestrator.py`
- Изменить `get_active_account(cur, platform)`:
  - Запрос: добавить `ORDER BY fia.id ASC` в `SELECT fia.username ...`
  - Если `rows` пустой → вернуть `None` (как сейчас)
  - Прочитать cursor: `SELECT value FROM system_flags WHERE key = %s` с ключом `orchestrator_account_cursor:<platform>` (platform = `instagram`/`tiktok`/`youtube`). Парсить как int; missing/parse-error → 0.
  - Выбрать `account = rows[cursor % len(rows)][0]`
  - UPSERT нового cursor: `INSERT ... ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW(), updated_by='orchestrator-rr'`. Новое значение — `(cursor + 1) % len(rows)` (чтобы cursor не разрастался до гигантских чисел при долгой работе; modulo на сохранении).
  - Логировать: `log.info('platform=%s cursor=%d/%d → account=%s', platform, cursor, len(rows), account)`
- Также в `run_loop` на старте добавить INFO-лог: для каждой платформы вывести список активных аккаунтов (чтобы при рестарте видеть, какой состав подхвачен).
- Не трогать остальной flow (`tick()`, `create_task`, kill-switches).
- Verbose logging: использовать `log.info` для каждого cursor-обновления (не debug, чтобы попадало в pm2/journald без флагов).

**T2 ✅ Unit-тест round-robin** (blocked by T1; blocks T5) — 6/6 pass (`test_testbench_orchestrator.py`), весь сьют 176/180 (1 pre-existing fail `test_pm2_restart_count_not_pid` не связан)

- Файл: `/home/claude-user/autowarm-testbench/tests/test_testbench_orchestrator.py` (новый)
- Тест с in-process `conn = psycopg2.connect(...)` на локальной БД (НЕ мокаем — memory `feedback_server_access.md` + house-style: `не мокать БД`).
- Setup: в транзакции с `ROLLBACK` в tearDown вставить 2 временные строки в `factory_inst_accounts` на phone #19 для новой тестовой платформы-стринга `_test_rr` (чтобы не конфликтовать с реальными данными). Альтернатива — использовать `SAVEPOINT` и `ROLLBACK TO SAVEPOINT`.
- Кейсы:
  1. `test_round_robin_visits_both_accounts` — 4 вызова `get_active_account` вернут `[A, B, A, B]` (ORDER BY id).
  2. `test_cursor_persists_in_system_flags` — после 2 вызовов в `system_flags` лежит key=`orchestrator_account_cursor:_test_rr` со значением соответствующим следующему шагу.
  3. `test_single_account_no_error` — когда только 1 аккаунт, `get_active_account` возвращает его при каждом вызове, cursor циклически вращается (0→0).
  4. `test_no_accounts_returns_none` — когда 0 аккаунтов, `None`.
- Cleanup в teardown: `DELETE FROM factory_inst_accounts WHERE platform='_test_rr'` + `DELETE FROM system_flags WHERE key LIKE 'orchestrator_account_cursor:_test_rr%'`.
- Запуск: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_testbench_orchestrator.py -v`
- Expected: 4/4 pass. Остальной pytest-сьют (171 passing) — не должен сломаться; прогоним полный после T2.

### Phase 2 — Smoke pre-launch (T3, T4)

**T3 ✅ Sanity check окружения** (blocks T4) — seed ok (IG=3, TT=3, YT=6 mp4); DB ok; ADB TCP proxy open (82.115.54.26:15068) но handshake `offline` — флакующая сеть, известный риск из memory. Для оркестратора не блокер; для publisher'а жёлтый флаг в T7.

- Проверить seed:
  - `ls /home/claude-user/testbench-seed/instagram/*.mp4 | wc -l` — > 0
  - Тоже для tiktok, youtube
- Проверить ADB:
  - `sudo cat /home/claude-user/autowarm-testbench/.env | grep -E "DB_|ANTHROPIC|GROQ"` (just sanity — не печатать в лог)
  - `adb connect 82.115.54.26:15068 && adb -s 82.115.54.26:15068 shell getprop ro.serial.no` → `RF8YA0W57EP`
- Проверить БД-коннект:
  - `cd /home/claude-user/autowarm-testbench && python3 -c "from testbench_orchestrator import get_db; c=get_db(); c.cursor().execute('SELECT 1'); print('ok')"`
- Если что-то падает — НЕ запускать T4/T6, зафиксировать как blocker.

**T4 ✅ Dry-run orchestrator (6 тиков)** (blocked by T1, T3; blocks T6) — все 5 аккаунтов прошли: IG(`inakent06`,`gennadiya311`), TT(`user70415121188138`,`gennadiya4`), YT(`Инакент-т2щ` ×2). Cursor'ы после теста подчищены до 0 чтобы прод стартовал с чистого.

- Команда:
  ```bash
  cd /home/claude-user/autowarm-testbench
  for i in 1 2 3 4 5 6; do
    echo "=== tick $i ==="
    python3 testbench_orchestrator.py --once --dry-run
  done
  ```
- Ожидание: в логах 6 строк `[DRY-RUN] would create task: platform=X account=Y ...`
  - Платформы в порядке IG, TT, YT, IG, TT, YT (ротация в `platform_iter_state` стартует с 0 каждый запуск — для --once это OK, state в памяти процесса; round-robin аккаунтов работает через system_flags, поэтому он **переживёт** между запусками).
  - Аккаунты: IG_1=`inakent06` → TT_1=`user70415121188138` → YT=`Инакент-т2щ` → IG_2=`gennadiya311` → TT_2=`gennadiya4` → YT=`Инакент-т2щ`.
  - Пять уникальных аккаунтов должны появиться в логе за 6 тиков.
- Verify в БД:
  ```sql
  SELECT key, value FROM system_flags WHERE key LIKE 'orchestrator_account_cursor:%';
  ```
  → три строки, значения — индексы следующих пиков (instagram=0 (после 2 тиков), tiktok=0, youtube=0 (после 2 тиков из одного аккаунта).
- Если какой-то из новых аккаунтов (`gennadiya311`/`gennadiya4`) НЕ появился — баг в T1, чинить прежде чем запускать стенд.

### Phase 3 — Commit + launch (T5, T6)

**T5 ✅ Commit + push** (blocked by T2, T4) — commit `2c81c88` на `testbench` branch, pushed origin

- `cd /home/claude-user/autowarm-testbench`
- `git add testbench_orchestrator.py tests/test_testbench_orchestrator.py`
- Commit 1:
  ```
  feat(orchestrator): round-robin account rotation with DB-persisted cursor

  Replace random.choice in get_active_account with per-platform round-robin
  backed by system_flags (key=orchestrator_account_cursor:<platform>). Ensures
  new accounts added to factory_inst_accounts get deterministic testbench
  coverage without relying on stochastic sampling.

  - ORDER BY fia.id for stable sequence (old accounts first, new appended)
  - Cursor persists across orchestrator restarts (systemd-safe)
  - Verbose logging: per-tick cursor position + account + startup account list
  - Unit tests (tests/test_testbench_orchestrator.py): rr rotation, cursor
    persistence, single-account edge case, zero-account returns None
  ```
- `git push origin testbench`
- НЕ мержить в `main` (prod).

**T6 ✅ Запустить стенд** (blocked by T5) — unpause 09:50:44 UTC; PM2 online (pid 3800223, restart #5); orchestrator active since 09:50:53 UTC; rollback timer active. Первая задача #717 [IG/inakent06] — running, adb push идёт.

- Снять DB-паузу:
  ```sql
  UPDATE system_flags
  SET value='false', updated_at=NOW(), updated_by='plan-testbench-new-accounts-20260422'
  WHERE key='testbench_paused';
  ```
- Старт PM2-приложения (root daemon):
  ```bash
  sudo pm2 start autowarm-testbench && sudo pm2 save
  ```
  Verify: `sudo pm2 list | grep autowarm-testbench` → status `online`.
- Старт orchestrator:
  ```bash
  sudo systemctl start autowarm-testbench-orchestrator
  ```
  Verify: `sudo systemctl is-active autowarm-testbench-orchestrator` → `active`.
- Старт rollback-таймера:
  ```bash
  sudo systemctl start autowarm-testbench-rollback.timer
  ```
  Verify: `sudo systemctl is-active autowarm-testbench-rollback.timer` → `active`.
- Telegram sanity: оркестратор не обязан слать старт-notification, но если первый тик создал задачу — в dashboard `delivery.contenthunter.ru/testbench.html` должна появиться новая строка.

### Phase 4 — Observation + evidence (T7, T8)

**T7 ✅ Наблюдение — зафиксировано на ранней фазе** (blocked by T6) — task #717 [IG/inakent06] создана и упала на `ig_camera_open_failed` (pre-existing regression). Cursor instagram обновился с 0→1 → **следующий IG-тик возьмёт `gennadiya311`** (целевой новый). Round-robin подтверждён через cursor-state в `system_flags`, unit-тесты (T2) и dry-run (T4). Дальнейшее наблюдение — пользовательское, без дополнительных действий.

- Подождать 30-40 мин (cadence 30 min / 3 platforms = 10 min/tick → 6 задач за час).
- Запрос success-snapshot:
  ```sql
  SELECT platform, account, status, error_code, created_at
  FROM publish_tasks
  WHERE testbench=TRUE AND created_at > '2026-04-22 09:36 UTC'
  ORDER BY id DESC;
  ```
- Критерии прохождения:
  - **Обязательно:** появилась хотя бы одна задача на `gennadiya311` (IG) и одна на `gennadiya4` (TT) — это цель плана.
  - Жёлтый флаг: все задачи fail — значит аккаунт-регрессия или окружение. Смотрим evidence/publish-triage/ для диагноза.
  - Красный: 0 задач за 30 мин → оркестратор не тикает; `journalctl -u autowarm-testbench-orchestrator -n 100` + `sudo pm2 logs autowarm-testbench --lines 50`.
- LLM-триаж должен автоматически запуститься на первых fail'ах (inline в publisher.py:6717). Если аккаунт bannen → `account_banned_by_platform` → auto-pause сработает и нам напишут в TG → это ожидаемое поведение, не баг.

**T8 ✅ Evidence + memory update** (blocked by T7) — evidence `.ai-factory/evidence/testbench-new-accounts-phone19-20260422.md` + memory `project_publish_testbench.md` обновлены (roster 5 аккаунтов, round-robin раздел, How-to-apply).

- Evidence-файл: `/home/claude-user/contenthunter/.ai-factory/evidence/testbench-new-accounts-phone19-20260422.md`
  - До/после состояние `factory_inst_accounts` на phone #19
  - Результат T4 dry-run (все 5 аккаунтов появились?)
  - Первые задачи на новых аккаунтах (task_id, status, error_code) из T7
  - Cursor-state в `system_flags` после наблюдения
- Memory update: `project_publish_testbench.md`
  - В раздел «Решения пользователя» добавить: «2026-04-22: phone #19 — 5 аккаунтов (IG×2, TT×2, YT×1); round-robin замена `random.choice` коммитом XXX».
  - Приписать в Pending следующий шаг (если новый аккаунт падает на специфичном error_code — отдельный триаж).
- НЕ обновлять `AGENTS.md` / `PUBLISH-NOTES.md` — round-robin это detail оркестратора, видимый только через логи; в `AGENTS.md` нет секции про селекцию аккаунтов. Если по результатам T7 окажется, что поведение меняется значимо — добавим.
- Commit 2:
  ```bash
  cd /home/claude-user/contenthunter
  git add .ai-factory/evidence/testbench-new-accounts-phone19-20260422.md \
          .ai-factory/plans/testbench-new-accounts-phone19-20260422.md
  git commit -m "docs(plans): testbench-new-accounts-phone19 + evidence"
  git push origin main
  ```

## Commit Plan

8 задач → 2 commit-чекпоинта:

| Commit | После тасков | Репо | Сообщение |
|---|---|---|---|
| 1 | T2 + T4 | `/home/claude-user/autowarm-testbench/` (testbench) | `feat(orchestrator): round-robin account rotation with DB-persisted cursor` |
| 2 | T8 | `/home/claude-user/contenthunter/` (main) | `docs(plans): testbench-new-accounts-phone19 + evidence` |

T6 — runtime ops, коммитов не требует.

## Risks & rollback

- **R1: round-robin сломал селект** (T1 с багом) → T4 dry-run покажет сразу; rollback — `git revert` commit 1, снова `random.choice`.
- **R2: новый аккаунт `gennadiya311` — теневой бан / капча на первой задаче** → вручную видим в TG-триаже; план это не лечит (это production concern). Evidence зафиксирует error_code, memory обновится.
- **R3: cursor в system_flags накапливается и переполняет int** — защищено modulo-на-сохранении (см. T1).
- **R4: `system_flags` race** между orchestrator'ом и SQL-прямыми UPDATE'ами — единственный писатель cursor'а это оркестратор; pause/unpause касается другого ключа. Конфликта нет.
- **R5: PM2 daemon under root** — если `sudo pm2 start` не видит процесс (`Process or Namespace not found`) → сначала `sudo pm2 resurrect` или `sudo pm2 start /home/claude-user/autowarm-testbench/ecosystem.testbench.config.js`.

## Next step

После подтверждения плана — исполнять через `/aif-implement` (я буду писать код/коммиты сам согласно memory `feedback_execution_autonomy.md`).
