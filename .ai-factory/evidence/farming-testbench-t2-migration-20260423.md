# T2 — autowarm_tasks.testbench column migration

**Date:** 2026-04-23
**Migration:** `20260423_farming_testbench_autowarm_tasks_col.sql` + rollback

## Apply result

```
BEGIN
ALTER TABLE
CREATE INDEX
NOTICE:  [migration] autowarm_tasks.testbench column: present=t
NOTICE:  [migration] idx_autowarm_tasks_testbench index: present=t
COMMIT
```

## Verify SQL

```sql
-- column present:
\d autowarm_tasks
-- testbench | boolean | not null | false
-- Indexes:  "idx_autowarm_tasks_testbench" btree (id DESC) WHERE testbench = true

-- prod rows untouched:
SELECT COUNT(*) FILTER (WHERE testbench=FALSE) as prod_rows,
       COUNT(*) FILTER (WHERE testbench=TRUE)  as testbench_rows
  FROM autowarm_tasks;
-- prod_rows=140, testbench_rows=0
```

## Rollback (hot path)

```
psql openclaw < /root/.openclaw/workspace-genri/autowarm/migrations/20260423_farming_testbench_autowarm_tasks_col__rollback.sql
```

Drop INDEX + DROP COLUMN. Безопасно пока farming-testbench не накопил задач — после старта orchestrator'а задачи на testbench=TRUE потеряют пометку при откате и сольются с прод-очередью.

## Next steps

T3 — Smoke-preflight сессий IG/TT/YT на phone #171 (подтвердить own-profile state на всех 3 платформах, потому что T1 показал что TT мог быть stuck в чужом профиле перед ручным логином).
