# Evidence — Migration 20260423_factory_accounts_id_sequence applied

**Applied:** 2026-04-23
**Target DB:** `openclaw@localhost:5432` (shared prod + testbench)
**Applied by:** claude-user via plan `fix-packages-add-account-id-20260423.md`

## Dry-run (BEGIN+ROLLBACK)

```
BEGIN
CREATE SEQUENCE
NOTICE:  [migration] factory_inst_accounts_id_seq: MAX(id)=1686 → setval=1686 (is_called=t)
DO
ALTER TABLE
CREATE SEQUENCE
NOTICE:  [migration] factory_pack_accounts_id_seq: MAX(id)=341 → setval=341 (is_called=t)
DO
ALTER TABLE
ROLLBACK
```

## Apply (actual)

```
$ psql -f migrations/20260423_factory_accounts_id_sequence.sql
BEGIN
CREATE SEQUENCE
NOTICE:  [migration] factory_inst_accounts_id_seq: MAX(id)=1686 → setval=1686 (is_called=t)
DO
ALTER TABLE
CREATE SEQUENCE
NOTICE:  [migration] factory_pack_accounts_id_seq: MAX(id)=341 → setval=341 (is_called=t)
DO
ALTER TABLE
COMMIT
```

## Post-apply verification

### DEFAULT expressions on id columns

```sql
SELECT c.relname, a.attname, pg_get_expr(ad.adbin, ad.adrelid) AS default
FROM pg_attrdef ad
JOIN pg_attribute a ON a.attrelid = ad.adrelid AND a.attnum = ad.adnum
JOIN pg_class c ON c.oid = ad.adrelid
WHERE c.relname IN ('factory_inst_accounts','factory_pack_accounts');
```

| table | column | default |
|---|---|---|
| factory_inst_accounts | id | `nextval('factory_inst_accounts_id_seq'::regclass)` |
| factory_pack_accounts | id | `nextval('factory_pack_accounts_id_seq'::regclass)` |
| factory_inst_accounts | synced_at | `now()` |
| factory_pack_accounts | synced_at | `now()` |

### Sequence state

```
factory_inst_accounts_id_seq: last_value=1686, is_called=t  (next nextval → 1687)
factory_pack_accounts_id_seq: last_value=341,  is_called=t  (next nextval → 342)
```

## Effect on live traffic

**Bug fixed immediately.** `server.js:3036` (POST /api/packages/:id/accounts) already omitted `id` from its INSERT — previously this produced NULL → NOT NULL violation. With the sequence DEFAULT now in place, that same INSERT now auto-assigns an id.

**No restart required** for this handler — the fix is at the DB layer. Server code stays as-is for this endpoint.

## Remaining work (T5+)

Other handlers still use manual `MAX(id)+1` counter-inserts (CREATE pack, split, revision/apply). They work correctly today (explicit id does not consume sequence), but introduce a **race condition**: a parallel counter INSERT + sequence INSERT can collide on the same id → PK violation.

Race is rare (requires simultaneous admin ops) but not zero. T5 refactors those handlers to drop counters and rely on sequence uniformly, eliminating the race.

## Rollback

If needed:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f migrations/20260423_factory_accounts_id_sequence__rollback.sql
```

**WARNING:** Rollback reintroduces the original bug. Apply only if every INSERT site in `server.js` is guaranteed to pass explicit `id`.
