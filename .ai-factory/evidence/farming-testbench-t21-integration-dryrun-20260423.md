# T21 — Farming Testbench Integration Dry-Run Evidence

**Date:** 2026-04-23
**Scope:** Проверка полного контура (orchestrator → triage → rollback) в dry-run режиме
**Reason:** Без реального запуска стенда (требует prod deploy, T23) убедиться что все модули корректно бутстрапятся, читают БД и выполняют свою роль.

## 1. Orchestrator dry-run

```
$ cd /root/.openclaw/workspace-genri/autowarm && python3 farming_orchestrator.py --dry-run --once
2026-04-23 16:02:08 [INFO] [farming-orchestrator] account platform=instagram cursor=1/2 → born.trip90@pack=Тестовый проект_171b (next=0)
2026-04-23 16:02:08 [INFO] [farming-orchestrator] [DRY-RUN] would create farming task: platform=Instagram account=born.trip90 pack=Тестовый проект_171b adb=82.115.54.26:15088 protocol=1
```

**Rotation history** (3 предыдущих --dry-run --once подтвердили rotation):
- Tick 1 (cursor=0): IG → ivana.world.class@171a · protocol=1
- Tick 2 (cursor=1): TT → user899847418@171a · protocol=2
- Tick 3 (cursor=0, second loop started): YT → Ivana-o3j@171a · protocol=3
- Tick 4 (этот — cursor=1): IG → born.trip90@171b · protocol=1

**Verifies:**
- ✅ DB connection OK (psycopg2 + .env fallback DB_CONFIG)
- ✅ system_flags reads (paused + cadence + platform_cursor + account_cursor:*)
- ✅ factory_* SQL JOIN корректно ограничивает на device #171
- ✅ Round-robin курсоры инкрементятся (platform cursor wraps 0→1→2→0)
- ✅ Account-cursor per-platform независим (видно как 171b попадает во 2-й прогон IG)
- ✅ Protocol lookup по platform (3 seed protocols в DB)
- ✅ ADB config load из raspberry_port (raspberry=8 → 82.115.54.26:15088)
- ✅ Dry-run не INSERT'ит строки (verified через `SELECT count(*) FROM autowarm_tasks WHERE testbench=TRUE`: 0 до, 0 после)

## 2. Triage classifier dry-run

```
$ python3 farming_triage_classifier.py --scan-recent --window-min 60
2026-04-23 16:02:08,782 [INFO] [farming-triage] scan_recent: 0 tasks в окне 60 мин
2026-04-23 16:02:08,782 [INFO] [farming-triage] scan_recent done: classified 0/0 tasks
```

**Verifies:**
- ✅ scan_recent корректно работает с пустым окном (в последний час реальных задач нет — ожидаемо)
- ✅ Внутренний regex-тест: 4/4 passed (см. commit 578b14a)

## 3. Auto-rollback alert-only

```
$ python3 farming_auto_rollback.py --dry-run
2026-04-23 16:02:08,893 [INFO] [farming-rollback] check_all_applied_fixes: no active fixes to monitor
alerts: 0
```

**Verifies:**
- ✅ Читает farming_fixes WHERE enabled=TRUE AND applied_at IS NOT NULL — находит 0 (никто не применён)
- ✅ Не крашится на пустой выборке

## 4. Unit tests

```
$ cd /root/.openclaw/workspace-genri/autowarm && python3 -m pytest tests/test_farming_orchestrator.py tests/test_farming_errors.py -v
```

- `test_farming_orchestrator.py`: 11/11 ✅
- `test_farming_errors.py`: 8/8 ✅
- **Итого 19/19 unit-тестов зелёные.**

## 5. Schema integrity check

```sql
-- Все миграции применены:
SELECT 'autowarm_tasks.testbench' AS check, EXISTS (
  SELECT 1 FROM information_schema.columns
   WHERE table_name='autowarm_tasks' AND column_name='testbench'
) AS ok;  -- t

SELECT 'farming_error_codes' AS check, (SELECT COUNT(*) FROM farming_error_codes) AS count;
-- 23

SELECT 'farming_investigations' AS check, EXISTS (
  SELECT 1 FROM information_schema.tables WHERE table_name='farming_investigations'
) AS ok;  -- t

SELECT 'farming_fixes' AS check, EXISTS (
  SELECT 1 FROM information_schema.tables WHERE table_name='farming_fixes'
) AS ok;  -- t
```

## 6. Readiness summary

| Компонент | Status | Blocker для live-smoke? |
|-----------|--------|--------------------------|
| Orchestrator `farming_orchestrator.py` | ✅ dry-run OK | нет |
| Scheduler `farming_testbench_scheduler.js` | ✅ syntax OK | нет (live prover будет в T24) |
| Errors emitter `farming_errors.py` | ✅ 8/8 unit-tests | нет |
| Triage `farming_triage_classifier.py` | ✅ dry-run + regex tests | нет |
| Diagnose `farming_agent_diagnose.py` | ✅ syntax + import OK | LLM-call не тестирован без credentials (будет в T24) |
| Apply `farming_agent_apply.py` | ✅ REVIEW-mode MVP | нет |
| Rollback `farming_auto_rollback.py` | ✅ alert-only, dry-run OK | нет |
| Backend `/api/farming/testbench/*` | ✅ server.js syntax OK | нет |
| Frontend `/farming-testbench.html` | ✅ standalone page | нет |
| Shell scripts `farming-testbench-{start,stop,status}.sh` | ✅ bash -n OK | **Нужен sudo-deploy в /usr/local/bin/ (T23)** |
| Systemd units | ✅ написаны | **Нужен sudo install (T23)** |
| PM2 ecosystem | ✅ написан | **Нужен sudo pm2 start (T23)** |

## 7. Next steps

T22 — docs + runbook. T23 — prod deploy (requires sudo for /usr/local/bin/ + systemctl enable + pm2 start). T24 — 6-8h live smoke.
