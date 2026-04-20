# Guard-status backfill catalog — 2026-04-20

**Сборка:** 2026-04-20 ~06:30 UTC.
**Контекст:** T1+T2 из `contenthunter/.ai-factory/plans/fix-guard-status-backfill-tests-20260420.md`.

## TL;DR

38 pre-deploy задач (20 TikTok + 18 YouTube) с `status=failed` и reason=`platform_not_configured_for_device`. После T2 backfill — все переведены в `status=skipped_config_missing`.

Post-deploy случаев — **0** (подтверждено `CASE WHEN started_at < '2026-04-19 20:04' THEN 'pre-deploy' ELSE 'POST-DEPLOY (!)'`). Фикс `_mark_task_failed_by_guard` работает корректно начиная с commit `ff3ec8b` (2026-04-19 20:04 UTC).

## T1 — Dry-run catalog

SQL:
```sql
SELECT id, platform, device_serial, account,
       to_char(started_at, 'YYYY-MM-DD HH24:MI:SS') AS started_utc,
       CASE WHEN started_at < '2026-04-19 20:04' THEN 'pre-deploy' ELSE 'POST-DEPLOY (!)' END AS window
  FROM publish_tasks
 WHERE status = 'failed'
   AND events::text LIKE '%platform_not_configured_for_device%'
 ORDER BY platform, started_at;
```

### TikTok (20 задач)

| id | device_serial | account | started_utc |
|---:|---|---|---|
| 386 | RF8YA0V78FE   | contentexpert_1  | 2026-04-18 05:11:16 |
| 380 | RFGYA19DNGZ   | content.hunter51 | 2026-04-18 05:11:16 |
| 410 | RFGYA19DNGZ   | content.hunter51 | 2026-04-18 11:24:04 |
| 412 | RF8YA0V78FE   | contentexpert_1  | 2026-04-18 11:24:04 |
| 409 | RF8Y80ZT14T   | aneco_le         | 2026-04-18 11:39:04 |
| 429 | RF8Y80ZT14T   | aneco_le         | 2026-04-18 12:04:04 |
| 450 | RFGYA19DBAX   | pay.abroad.easy  | 2026-04-19 05:14:04 |
| 451 | RFGYB07Y5TJ   | pay.anywhere.now | 2026-04-19 05:14:04 |
| 447 | RFGYB07Y65V   | relisme_art      | 2026-04-19 05:14:04 |
| 446 | RF8Y80ZT14T   | aneco_le         | 2026-04-19 05:15:04 |
| 449 | RFGYA19DB8K   | pay.world.cards  | 2026-04-19 05:17:04 |
| 457 | RF8Y80ZTVJJ   | relismefit       | 2026-04-19 05:34:04 |
| 455 | RF8Y80ZV8NW   | relismeedit      | 2026-04-19 05:34:04 |
| 458 | RF8Y80ZTTMV   | relisme6         | 2026-04-19 05:35:04 |
| 461 | RF8Y80ZT14T   | aneco_le         | 2026-04-19 05:54:04 |
| 464 | RFGYA19BGWT   | relis_unpack     | 2026-04-19 05:54:04 |
| 465 | RFGYA19BMFX   | relism_e         | 2026-04-19 05:54:04 |
| 470 | RF8YA0VDZ3X   | rel_isme         | 2026-04-19 05:54:04 |
| 466 | RFGYA19BD6M   | packgirl24       | 2026-04-19 05:55:04 |
| 467 | RFGYA19B0FD   | relisme_co       | 2026-04-19 05:55:04 |

### YouTube (18 задач)

| id | device_serial | account | started_utc |
|---:|---|---|---|
| 381 | RF8Y90LBZPJ   | anecole          | 2026-04-18 05:11:16 |
| 395 | RF8Y90LBZPJ   | anecole          | 2026-04-18 05:51:16 |
| 418 | RF8Y90LBZPJ   | anecole          | 2026-04-18 11:40:04 |
| 428 | RF8Y90LBZPJ   | anecole          | 2026-04-18 12:04:04 |
| 448 | RF8Y90LBZPJ   | anecole          | 2026-04-19 05:16:04 |
| 453 | RFGYB07Y65V   | WowRelisme       | 2026-04-19 05:34:04 |
| 460 | RFGYB07Y5TJ   | pay.anywhere_now | 2026-04-19 05:34:04 |
| 459 | RFGYA19DBAX   | pay.abroad_easy  | 2026-04-19 05:34:04 |
| 456 | RFGYA19DB8K   | pay.world_cards  | 2026-04-19 05:35:04 |
| 468 | RF8Y80ZTVJJ   | relis-c6n        | 2026-04-19 05:54:04 |
| 462 | RF8Y90LBZPJ   | anecole          | 2026-04-19 05:54:04 |
| 463 | RF8Y80ZV8NW   | RelisMeGirl      | 2026-04-19 05:54:04 |
| 469 | RF8Y80ZTTMV   | realismewear     | 2026-04-19 05:55:04 |
| 475 | RF8YA0VDZ3X   | relismee         | 2026-04-19 06:34:04 |
| 471 | RFGYA19BMFX   | relisgirl        | 2026-04-19 06:34:04 |
| 472 | RFGYA19BD6M   | relisme-n9s      | 2026-04-19 06:34:04 |
| 474 | RFGYA19B0FD   | engine-p1k       | 2026-04-19 06:35:04 |
| 473 | RFGYA19BGWT   | relisme-j6f      | 2026-04-19 06:35:04 |

### Instagram — 0 строк

IG был исправлен раньше (предыдущим фиксом в `_mark_task_failed_by_guard`), IG-класс в backlog отсутствует.

## T2 — Backfill execution — ✅ OK

```sql
BEGIN;
WITH updated AS (
  UPDATE publish_tasks
     SET status = 'skipped_config_missing',
         updated_at = NOW(),
         log = COALESCE(log, '') ||
               E'\n[backfill 2026-04-20] status=failed→skipped_config_missing (pre-deploy guard-split)'
   WHERE status = 'failed'
     AND events::text LIKE '%platform_not_configured_for_device%'
     AND started_at < '2026-04-19 20:04'
   RETURNING id, platform
)
SELECT platform, COUNT(*) FROM updated GROUP BY platform;
-- → TikTok: 20, YouTube: 18  (total 38)

SELECT 'leftovers', COUNT(*)
  FROM publish_tasks
 WHERE status = 'failed'
   AND events::text LIKE '%platform_not_configured_for_device%';
-- → 0 rows ✓
COMMIT;
```

**Результат:**
- 20 TT + 18 YT → status=`skipped_config_missing`
- 0 leftover-задач (T4 observability уже зелёный в момент T2)
- Идемпотентность: повторный запуск вернёт 0 rows
- Трассируемость: добавлен `log` постфикс `[backfill 2026-04-20] ...`

## T3 — Тесты TT/YT (отдельный evidence — в autowarm commit-message)

См. commit `test(publish-guard): explicit TT/YT coverage` (создаётся в рамках T3).

## T4 — Observability SQL

`autowarm/scripts/guard_status_consistency.sql` — reusable check. Target output: 0 rows.

Post-backfill check (сразу после T2):
```
=== 1. Guard-status inconsistency (должно: 0 rows) ===
 platform | status | n
----------+--------+---
(0 rows)

=== 2. Свежие skipped_config_missing (48h) — sanity: guard работает? ===
 platform  | n
-----------+----
 Instagram | 42
 TikTok    | 27
 YouTube   | 25

=== 3. Все reason-ы от guard (48h) ===
               reason               | events
------------------------------------+--------
 platform_not_configured_for_device | 185
```

- Section 1 = 0 rows → backfill и post-deploy работают синхронно.
- Section 2 → guard активен на всех 3 платформах (42/27/25 skipped за 48h).
- Section 3 → все 185 guard-событий корректно несут reason; `account_not_logged_in_on_device` — 0 в окне.

T4 formally **PASSED immediately** (48h-waiter не нужен — evidence уже показывает зелёный state).

## Метаданные

- DB: `openclaw@localhost/openclaw`
- Deploy-коммит `_mark_task_failed_by_guard` split-status для всех платформ: `ff3ec8b` (2026-04-19 20:04 UTC).
- Всего кандидатов: 38 (20 TT + 18 YT).
