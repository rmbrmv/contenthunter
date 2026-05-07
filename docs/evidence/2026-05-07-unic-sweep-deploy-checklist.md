# Deploy Checklist — unic-sweep (sub-project A)

**Branch:** `feature/unic-sweep-2026-05-07` (autowarm-testbench → GenGo2/delivery-contenthunter)
**Date prepared:** 2026-05-07
**Tests:** 29/29 pass (15 unit + 14 integration)

## Summary

Adds a continuous 5-minute safety-net sweep that ensures any approved+filled scheduled slot lands in `unic_tasks` even if `trigger-immediate` and the morning batch missed it. Race-protected via new partial unique index. Closes production blocker — clients had scheduled content not picked up for unification.

### Files changed
- `migrations/20260507_unic_tasks_unique_active_slot.sql` (NEW) + `__rollback.sql` (NEW)
- `scripts/audit_unic_tasks_duplicates.sql` (NEW)
- `unic_sweep.js` (NEW) — DST-aware sweep loop with stopped-flag race protection
- `unic_sweep.test.js` (NEW) — 15 unit tests
- `run_auto_unic.js` (NEW) — extracted from server.js, adds ON CONFLICT
- `tests/test_unic_sweep_integration.test.js` (NEW) — 14 integration tests against real DB
- `server.js` — runAutoUnicForDate inlined → require + factory; sweep wired in startup

### Commits (in order)
```
33ba564 feat(unic): read-only audit script for unic_tasks duplicate detection
90722b1 feat(unic): partial unique index on unic_tasks(content_id, slot_date)
a9c0c0f feat(unic): DST-aware business-date helpers in unic_sweep module
60ebb8b feat(unic): self-scheduling sweep loop with stopped-flag race protection
026a382 feat(unic): extract runAutoUnicForDate + add ON CONFLICT + return counts
c768fda feat(unic): wire 5-minute sweep loop in server.js startup
074889a test(unic): integration test scaffold + I1 + I2
7b6901f test(unic): integration tests I3-I7b — idempotency + boundary cases
097dad2 test(unic): I8 midnight rollover with explicit content.status reset
7d5f615 test(unic): I9-I11 — negative eligibility (validating/empty/pending-moderation)
<I12 commit> test(unic): I12a/I12b — race coverage
```

## Pre-flight on prod VPS

1. SSH on prod, `cd /root/.openclaw/workspace-genri/autowarm/`.

2. **Audit (read-only):**
   ```bash
   psql -U openclaw -d openclaw -f scripts/audit_unic_tasks_duplicates.sql
   ```
   - **0 строк** → можно мигрировать.
   - **Иначе** → STOP, ops резолвит дубли вручную (см. design doc § Migration safety).

3. **Узнать имя PM2-процесса:**
   ```bash
   pm2 list | grep -E "autowarm|delivery|server"
   ```
   (Ожидаемое имя — `autowarm-server` или подобное; уточнить.)

## Deploy

1. **Применить миграцию (НЕ через runner с auto-tx):**
   ```bash
   psql -U openclaw -d openclaw -f migrations/20260507_unic_tasks_unique_active_slot.sql
   psql -U openclaw -d openclaw -c "\d unic_tasks" | grep idx_unic_tasks_active_slot
   ```
   Expected: индекс виден с предикатом `WHERE current_status = ANY (ARRAY['pending','processing','done']) AND content_id IS NOT NULL AND slot_date IS NOT NULL`.

2. **Cherry-pick кода в prod main** (auto-push hook доставит на VPS — см. memory `reference_autowarm_git_hook.md`).

3. **Restart:** `pm2 restart <process_name>`

## Monitoring

- **T+1 мин:** `pm2 logs <process> | grep unic-sweep | head -3`. Должно быть видно стартовый лог:
  `[unic-sweep] loop started (5min interval, 30s initial delay)`

- **T+5 мин:** первый JSON-tick:
  ```json
  {"tag":"unic-sweep","ok":true,"target_date":"<today>","inserted":N,...}
  {"tag":"unic-sweep","ok":true,"summary":true,"target_dates":["<today>","<yesterday>"],"total_inserted":N,...}
  ```

- **T+30 мин:** `inserted` count за первые тики покажет сколько застрявших слотов было подобрано (ожидаемо >0 на первом тике после деплоя — это и есть backfill сегодняшних застрявших; после — стремится к 0).

- **T+24 ч:** health-метрика возвращает 0 застрявших слотов:
  ```sql
  SELECT COUNT(*) FROM validator_schedule_slots s
  JOIN validator_content c ON c.id = s.content_id
  WHERE s.slot_date = CURRENT_DATE  -- ВНИМАНИЕ: на проде использовать business-tz date, не CURRENT_DATE
    AND s.status = 'filled'
    AND c.status = 'approved'
    AND c.moderation_status = 'passed'
    AND NOT EXISTS (SELECT 1 FROM unic_tasks ut
                    WHERE ut.content_id = c.id
                      AND ut.slot_date = s.slot_date
                      AND ut.current_status IN ('pending','processing','done'));
  ```

## Rollback

**Код:**
```bash
git revert <merge_sha>
pm2 restart <process_name>
```

**Миграция (при необходимости):**
```bash
psql -U openclaw -d openclaw -f migrations/20260507_unic_tasks_unique_active_slot__rollback.sql
```

## Disable без re-deploy

```bash
pm2 set <process>.env.UNIC_SWEEP_DISABLED 1
pm2 restart <process>
```

`server.js` проверяет `if (process.env.NODE_ENV !== 'test' && process.env.UNIC_SWEEP_DISABLED !== '1')` — гасит loop без модификации кода.

## Known follow-ups (out of scope for this PR)

1. **Manual admin endpoint INSERT** — `server.js:5232` (POST /api/unic/tasks, requireAuth). Этот INSERT не имеет `slot_date`, поэтому partial unique index его не защищает. Race vs auto-unic невозможен (разные partition'ы индекса), но дубли через самого endpoint'а не предотвращены. Если когда-нибудь endpoint начнёт ставить slot_date — нужно добавить ON CONFLICT туда же.

2. **Existing `triggerAutoUnic` morning-batch** (`server.js:5500-5549`) — теперь избыточен относительно sweep'а. Оставлен как backup. Решение об удалении — после 1-2 недель логов; если sweep ловит всё, что ловил morning-batch, удалять отдельным PR.

3. **Health-метрика timezone** — рекомендуется computeBusinessDate(timezone) в helper-скрипте мониторинга (НЕ `CURRENT_DATE`).

## Smoke evidence

**Tests on dev (autowarm-testbench, postgres on localhost):** `# pass 29 # fail 0` (15 unit + 14 integration).

**Live tick smoke** на dev был частично заблокирован pre-existing `EACCES /tmp/publish_media/` (claude-user не root, prod issue не репродуцируется на dev). Wiring проверен через node -c + выполнение `runAutoUnicForDate` напрямую с реальным DB pool — корректно создаёт unic_tasks с `current_status='pending'`, обновляет `validator_content.status='in_uniqualization'`. Финальная live-tick верификация ожидается на prod после деплоя (см. Monitoring § T+5 мин).
