# Evidence — ротация новых аккаунтов phone #19 + рестарт стенда

**Дата:** 2026-04-22
**План:** `.ai-factory/plans/testbench-new-accounts-phone19-20260422.md`
**Commit (autowarm-testbench):** `2c81c88` на ветке `testbench` (pushed origin)

## До — состояние перед изменениями

### Аккаунты в `factory_inst_accounts` (phone #19)

```
 fia.id | username           | platform  | active | synced_at                 
--------+--------------------+-----------+--------+----------------------------
 1529   | inakent06          | instagram | TRUE   | 2026-03-23 (старый)
 1628   | gennadiya311       | instagram | TRUE   | 2026-04-22 09:22 UTC (НОВЫЙ)
 1530   | user70415121188138 | tiktok    | TRUE   | 2026-03-23 (старый)
 1629   | gennadiya4         | tiktok    | TRUE   | 2026-04-22 09:22 UTC (НОВЫЙ)
 1528   | Инакент-т2щ        | youtube   | TRUE   | 2026-03-23 (один)
```

### Testbench-задачи за 24h до изменений (id 671-716)

Все 46 задач исполнялись только на 3 старых аккаунтах (`inakent06`, `user70415121188138`, `Инакент-т2щ`).
Новые `gennadiya311`/`gennadiya4` имели 0 задач — появились в `factory_inst_accounts` позже последней задачи (`synced_at` = 09:22 UTC, `created_at` последней задачи #716 = 07:44 UTC).

### Состояние стенда

| Компонент | Было | Стало |
|---|---|---|
| `system_flags.testbench_paused` | `true` | `false` (unpaused 09:50:44 UTC by `plan-testbench-new-accounts-20260422`) |
| PM2 `autowarm-testbench` | `stopped` | `online` (pid 3800223, restart #5) |
| systemd `autowarm-testbench-orchestrator.service` | `inactive` | `active` (since 09:50:53 UTC) |
| systemd `autowarm-testbench-rollback.timer` | `inactive` | `active` |

## Изменения кода

### Commit `2c81c88` (`testbench` branch)

**Файл:** `testbench_orchestrator.py`

Заменён `random.choice` в `get_active_account(cur, platform)` на DB-persisted round-robin:

1. `SELECT ... ORDER BY fia.id ASC` — стабильный порядок (старые с меньшим id первыми, новые добавляются в хвост).
2. Cursor читается из `system_flags` по ключу `orchestrator_account_cursor:<platform>` (instagram/tiktok/youtube). Отсутствие ключа → 0.
3. Аккаунт выбирается как `rows[cursor % len(rows)]`.
4. Cursor обновляется через `INSERT ... ON CONFLICT (key) DO UPDATE` со значением `(cursor + 1) % len(rows)` — модуль применяется на сохранении, так что значение никогда не разрастается.
5. Verbose-лог на каждом выборе: `platform=X cursor=N/M → account=Y (next_cursor=Z)`.
6. Новая функция `log_account_roster(cur)` на старте `run_loop` — логирует список активных аккаунтов per-platform, чтобы при рестарте оркестратора видеть состав.

**Файл (новый):** `tests/test_testbench_orchestrator.py`

6 тестов против реальной БД (не мокаем — см. memory `feedback_server_access.md`) с транзакционной изоляцией (connection без autocommit + rollback в teardown, фейковые платформы `_test_rr_*`, id-диапазон 99990+):

- `test_round_robin_visits_both_accounts` — 4 вызова дают `[A,B,A,B]` в порядке ORDER BY id.
- `test_cursor_persists_in_system_flags` — после N вызовов cursor-state в `system_flags` = `N % len(accs)`.
- `test_cursor_key_format` — контракт имени ключа (`orchestrator_account_cursor:<lc-platform>`).
- `test_single_account_returns_same` — 1 аккаунт → все вызовы возвращают его, cursor вращается 0→0.
- `test_no_accounts_returns_none` — 0 аккаунтов → `None`, cursor не создаётся.
- `test_inactive_accounts_skipped` — `active=FALSE` строки не попадают в ротацию.

Все 6 новых pass. Полный сьют: **176 passed**, 3 skipped, 1 pre-existing fail (`test_pm2_restart_count_not_pid` — к этому изменению не относится, известный баг `testbench-status.sh` из memory).

## T4 — Dry-run (6 тиков) перед стартом

Результат прямого прогона `get_active_account` по ротации IG→TT→YT×2 (до очистки cursor'ов):

```
tick 1: Instagram  → inakent06               (cursor=0/2, next=1)
tick 2: TikTok     → user70415121188138      (cursor=0/2, next=1)
tick 3: YouTube    → Инакент-т2щ             (cursor=0/1, next=0)
tick 4: Instagram  → gennadiya311            (cursor=1/2, next=0)  ← НОВЫЙ
tick 5: TikTok     → gennadiya4              (cursor=1/2, next=0)  ← НОВЫЙ
tick 6: YouTube    → Инакент-т2щ             (cursor=0/1, next=0)
```

Все 5 уникальных активных аккаунтов прошли за первые 6 тиков — как и ожидалось. Cursor-строки удалены после dry-run, чтобы прод-старт начался с чистого 0.

## T6 — Старт стенда

Порядок (2026-04-22 09:50 UTC):

```
1. UPDATE system_flags SET value='false' WHERE key='testbench_paused'  → 09:50:44 UTC
2. sudo pm2 start autowarm-testbench                                   → pid 3800223
3. sudo pm2 save
4. sudo systemctl start autowarm-testbench-orchestrator.service       → 09:50:53 UTC
5. sudo systemctl start autowarm-testbench-rollback.timer
```

### Первый тик оркестратора (из systemd journal)

```
09:50:53 [INFO] project=Тестовый проект_19 device=RF8YA0W57EP raspberry=7
09:50:53 [INFO] seed dir: /home/claude-user/testbench-seed
09:50:53 [INFO] roster instagram: 2 active accounts ['inakent06', 'gennadiya311'] (cursor=0)
09:50:53 [INFO] roster tiktok: 2 active accounts ['user70415121188138', 'gennadiya4'] (cursor=0)
09:50:53 [INFO] roster youtube: 1 active accounts ['Инакент-т2щ'] (cursor=0)
09:50:53 [INFO] platform=instagram cursor=0/2 → account=inakent06 (next_cursor=1)
09:50:53 [INFO] created task #717 [Instagram/inakent06] media=pq_247_1776057299045.mp4
09:50:53 [INFO] next tick in 600 sec (cadence 30 min / 3 platforms)
```

Ростер видит обоих новых, round-robin ticks работают.

### Scheduler подхватил задачу сразу

Task #717 ушла в `running` через ~18 сек после INSERT (scheduler tick 10s + claim). Publisher начал `adb push` chunked (9×1024KB, chunk 1 за 2.35s). ADB работает, несмотря на ранее наблюдаемый `device offline` (флап сети, не блокер).

## T7 — Наблюдение 45-50 мин

**Ожидаемая последовательность** (cadence 30 min / 3 платформы = 600 sec/tick):

| Тик | Время (UTC) | Платформа | Ожидаемый аккаунт | Примечание |
|-----|-------------|-----------|-------------------|------------|
| 1 | 09:50 | IG | `inakent06` | старый — уже создан (#717) |
| 2 | 10:00 | TT | `user70415121188138` | старый |
| 3 | 10:10 | YT | `Инакент-т2щ` | (YT один) |
| 4 | 10:20 | IG | `gennadiya311` | **НОВЫЙ — целевой** |
| 5 | 10:30 | TT | `gennadiya4` | **НОВЫЙ — целевой** |
| 6 | 10:40 | YT | `Инакент-т2щ` | (YT) |
| 7 | 10:50 | IG | `inakent06` | старый (второй круг) |

Минимум до покрытия обоих новых — тик 5 (~10:30 UTC). Снапшот автоматически собирается background-командой ~10:37 UTC.

### Промежуточный snapshot (09:57 UTC, +7 мин от старта)

По запросу пользователя evidence зафиксирован на ранней фазе наблюдения — до первой задачи на новом аккаунте. Round-robin подтверждается через **cursor-state**, а не через множество созданных задач.

**Задачи:**

```
 id  | platform  |  account  | status | error_code             | created_at
 717 | Instagram | inakent06 | failed | ig_camera_open_failed  | 09:50:53
```

**Cursor-state в `system_flags`:**

```
 orchestrator_account_cursor:instagram = 1  (updated 09:50:53)
```

- Cursor instagram сдвинулся с 0 на 1 — подтверждение, что UPSERT в `_write_cursor` работает в проде.
- **Следующий IG-тик (~10:20 UTC) возьмёт `rows[1 % 2] = gennadiya311`** — это целевой новый аккаунт. Логика round-robin валидирована.
- TT/YT cursor'ы ещё не созданы (первый TT-тик через ~3 мин, YT через ~13 мин).

**Диагноз task #717:**

Failure `ig_camera_open_failed` на старом аккаунте `inakent06` — **regression не связан с ротацией аккаунтов**. Этот error_code известен с 2026-04-21 и продолжал фейлиться до commit e2cd9e2 (launch failures fix, 2026-04-22 утро); evidence `.ai-factory/evidence/publish-launch-failures-20260422.md` показал, что utром #711-#713 фикс сработал, но task #712 (тот же поток) всё равно упал на `draft-continuation dialog` — это pending follow-up в memory `project_publish_testbench.md`. Наш план не фиксит публикационные баги, только ротацию — но LLM-триаж и auto-fix loop запустятся как обычно и могут поднять новый диагноз.

### Валидация round-robin — через 2 подхода

1. **Unit-тесты (T2)** — 6 passing на реальной БД с rollback-изоляцией (см. коммит).
2. **Dry-run до старта (T4)** — все 5 аккаунтов посещены за 6 тиков с проверкой порядка.
3. **Cursor-UPSERT в проде (T7)** — `orchestrator_account_cursor:instagram` обновился на первом тике; следующие тики продолжат ротацию детерминированно.

Итого: логика round-robin подтверждена на 3 уровнях. Фактическое создание задач на `gennadiya311`/`gennadiya4` произойдёт на тиках 4-5 (~10:20-10:30 UTC) без дополнительных действий с моей стороны — оркестратор уже делает это сам.

### Дополнительный контроль после фиксации

Для доверки результата пользователь может через 30-50 мин проверить:

```sql
SELECT platform, account, COUNT(*) FROM publish_tasks
WHERE testbench=TRUE AND created_at > '2026-04-22 09:50:00'
GROUP BY platform, account ORDER BY platform, account;
```

Ожидание: все 5 аккаунтов появятся; `gennadiya311` и `gennadiya4` по ≥1 задаче.

Либо команда:

```bash
sudo systemctl status autowarm-testbench-orchestrator.service | tail -20
```

→ в логах увидите цепочку `platform=... cursor=N/M → account=...`

## Kill-switches (остались живы)

- SQL: `UPDATE system_flags SET value='true' WHERE key='testbench_paused'` — мягкая пауза оркестратора.
- `sudo systemctl stop autowarm-testbench-orchestrator` — новые задачи не создаются.
- `sudo pm2 stop autowarm-testbench` — текущая попытка прерывается.
- `testbench-stop.sh` — всё сразу.

## Выводы

1. **Новые аккаунты `gennadiya311`/`gennadiya4` теперь детерминированно попадают в ротацию** — не полагаемся на `random.choice`.
2. **Порядок стабильный:** ORDER BY id ASC → новые добавляются в хвост очереди, не нарушая прежний порядок старых аккаунтов.
3. **Cursor переживает рестарт** — если systemd перезапустит оркестратор, ротация продолжится с того же места (через `system_flags`).
4. **Добавление нового аккаунта в `factory_inst_accounts` → автоматически подхватится** на следующем тике без переразвёртывания оркестратора (roster логируется только на старте, но `get_active_account` всегда делает свежий SELECT).

## Follow-ups (пока не критичны)

- `datetime.utcnow()` deprecated — см. журнал `testbench_orchestrator.py:230`. Косметический refactor (не влияет на поведение).
- Pre-existing `test_pm2_restart_count_not_pid` fail — из memory известно, что `testbench-status.sh` врёт при пустом pm2; починка уже в очереди но не в scope этого плана.
- ADB `device offline` ранее на sanity-check → сейчас работает. Флап сети VPS↔proxy (memory `project_adb_push_network_issue.md`) — мониторим error_code'ы `adb_*` в T7.
