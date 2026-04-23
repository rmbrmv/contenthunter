# Session Resume: farming-testbench-phone171-20260423

**Last active:** 2026-04-23 ~16:30 UTC
**Session branch:** `feature/farming-testbench-phone171` (в contenthunter repo)
**Autowarm branch:** `testbench` (в `/root/.openclaw/workspace-genri/autowarm/`)
**Plan file:** `.ai-factory/plans/farming-testbench-phone171-20260423.md`
**Last commit (contenthunter):** `864efb170 docs(evidence): farming-testbench T23 ✅ prod deploy`
**Last commit (autowarm):** `50f2e78 deploy(farming-testbench): PM2-managed orchestrator + SQL-flag start/stop`

## Progress: 23/24 (96%)

Только T24 остался — live smoke test идёт.

## Что сделано последним

1. ✅ T23 prod deploy — PM2 apps online (`autowarm-farming-testbench`, `autowarm-farming-orchestrator`).
2. ✅ User запустил стенд через UI (`farming_testbench_paused=false`).
3. Cadence временно снижен до **15 мин** (с default 240) для быстрого smoke. После теста — вернуть на 240.
4. **Task #158** создана orchestrator'ом: TikTok/born7499@171b → status=failed через 2 мин. Warmer упал на `wa_account_read_fail` (не удалось прочитать активный TT-аккаунт после 3 попыток).
5. Triage classifier не поймал — **regex gap** для `wa_account_read_fail`.

## Завтра продолжить T24 — 3 задачи

### 1. Мониторинг накопленных fail'ов

```bash
# Посмотреть накопленные task'и:
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
  SELECT id, platform, account, status, started_at, updated_at,
         jsonb_array_length(events) as events_n
  FROM autowarm_tasks WHERE testbench=TRUE ORDER BY id DESC LIMIT 20;
"

# Запустить triage для обработки events:
cd /home/claude-user/autowarm-testbench && python3 farming_triage_classifier.py --scan-recent --window-min 720

# Investigations:
psql -c "SELECT * FROM farming_investigations ORDER BY id DESC LIMIT 10;"
```

### 2. Закрыть regex gap (wa_account_read_fail)

**Проблема:** `farming_triage_classifier.py::MSG_REGEX_RULES` не содержит паттернов для TikTok account-read failures. Task #158 имел event:

```json
{
  "ts": "16:29:10",
  "type": "error",
  "msg": "Не удалось прочитать аккаунт TikTok после 3 попыток — задача прервана",
  "meta": {"attempts": 3, "category": "wa_account_read_fail", "platform": "TikTok"}
}
```

**Что сделать:**

1. Добавить новый код в `farming_error_codes`:
   ```sql
   INSERT INTO farming_error_codes (code, severity, retry_strategy, is_known, is_auto_fixable, description) VALUES
     ('tt_account_read_fail', 'error', 'backoff', TRUE, TRUE,
      'TT switcher не смог прочитать активный аккаунт после 3 cold-restart попыток. Кандидат на fix switcher.py');
   ```

2. Добавить regex в `farming_triage_classifier.py::MSG_REGEX_RULES`:
   ```python
   (re.compile(r'не удалось прочитать аккаунт|account.*read.*fail|wa_account_read_fail', re.I),
    'tt_account_read_fail'),
   ```
   Также возможно добавить классификацию по `meta.category` (publish triage так делает).

3. Restart triage (no-op — оно скрипт, запускается ad-hoc):
   ```bash
   cd /home/claude-user/autowarm-testbench && python3 farming_triage_classifier.py --scan-recent --window-min 720
   ```

4. Убедиться что investigation создался: `SELECT * FROM farming_investigations WHERE error_code='tt_account_read_fail';`

### 3. Завершить smoke + вернуть каданс

```bash
# Восстановить каданс на production default (4h):
psql -c "UPDATE system_flags SET value='240' WHERE key='farming_orchestrator_cadence_min';"

# Restart orchestrator чтоб подхватил:
sudo pm2 restart autowarm-farming-orchestrator

# Остановить стенд (если smoke завершил свою цель):
psql -c "UPDATE system_flags SET value='true' WHERE key='farming_testbench_paused';"
# или через UI кнопку "🛑 Остановить"
```

После этого — пометить T24 ✅ completed в TaskList.

## Ссылки

- **UI:** https://delivery.contenthunter.ru/farming-testbench.html (login → sidebar "Прогрев" → "Testbench")
- **Plan:** `.ai-factory/plans/farming-testbench-phone171-20260423.md`
- **Evidence (3 файла):** `.ai-factory/evidence/farming-testbench-*20260423.md`
- **Documentation:** `/root/.openclaw/workspace-genri/autowarm/docs/farming-testbench.md`
- **Memory entries:** `project_farming_testbench.md` + `feedback_deploy_scope_constraints.md`

## PM2 state at session end

```
autowarm                      (prod API — перезапущен, подхватил /api/farming/testbench/*)
autowarm-testbench            (publish-testbench, независим)
autowarm-farming-testbench    (новый scheduler)
autowarm-farming-orchestrator (новый orchestrator, paused после user's stop ИЛИ active после user's start)
```

## Если что-то совсем сломалось — recovery

```bash
# 1. Hard stop всё farming:
sudo pm2 stop autowarm-farming-orchestrator autowarm-farming-testbench

# 2. Сбросить state:
psql -c "UPDATE autowarm_tasks SET status='cancelled'
         WHERE testbench=TRUE AND status IN ('pending','claimed','running');"
psql -c "UPDATE farming_investigations SET status='closed_fixed', closed_at=NOW()
         WHERE status='open';"
psql -c "DELETE FROM system_flags WHERE key LIKE 'farming_orchestrator_%cursor%';"

# 3. Рестарт:
sudo pm2 start autowarm-farming-orchestrator autowarm-farming-testbench
```
