-- Seed round-6: NULL-columns для 17 устройств без done-истории
-- Created: 2026-04-18
-- DB: openclaw @ localhost:5432
-- Motivation: все 51 (device,platform,account) triple за 14д имеют 0 done'ов
--             на любом устройстве за 90д → аккаунты не залогинены нигде.
--             Guard block-on-NULL (publisher.py:5286) заблокирует эти задачи за <5с.
-- Rollback:   DELETE FROM account_packages WHERE project='manual-seed-round-6-20260418';
-- Онбординг: чтобы разблокировать конкретное (device, platform) — UPDATE колонку:
--   UPDATE account_packages SET instagram='new_acc', updated_at=NOW()
--    WHERE device_serial='RFGYA19DBAX' AND project='manual-seed-round-6-20260418';
--   или DELETE и дать _upsert_auto_mapping работать естественно.

BEGIN;

-- Idempotent: INSERT только если строки с этим project ещё нет
INSERT INTO account_packages
  (device_serial, pack_name, project, instagram, tiktok, youtube, start_date, end_date)
SELECT d.serial,
       'round-6-null-seed',
       'manual-seed-round-6-20260418',
       NULL, NULL, NULL,
       CURRENT_DATE,
       NULL  -- permanent until manually deleted/updated
  FROM (VALUES
    ('RF8Y80ZT14T'),
    ('RF8Y80ZTTMV'),
    ('RF8Y80ZTVJJ'),
    ('RF8Y80ZV8NW'),
    ('RF8YA0V5KWN'),
    ('RF8YA0VDZ3X'),
    ('RFGYA19B0FD'),
    ('RFGYA19BD6M'),
    ('RFGYA19BGWT'),
    ('RFGYA19BMFX'),
    ('RFGYA19DB8K'),
    ('RFGYA19DBAX'),
    ('RFGYB07Y65V'),
    ('RFGYB1EBCBA'),
    ('RFGYC2VWBKN'),
    ('RFGYC31P1RH'),
    ('RFGYC31P7DT')
  ) AS d(serial)
 WHERE NOT EXISTS (
   SELECT 1 FROM account_packages ap
    WHERE ap.device_serial = d.serial
      AND ap.project = 'manual-seed-round-6-20260418'
 );

-- Verification: итоговый count и sanity-check
SELECT 'inserted' AS kind, COUNT(*) FROM account_packages
 WHERE project='manual-seed-round-6-20260418';

-- Все NULL-колонки корректны
SELECT device_serial, instagram, tiktok, youtube
  FROM account_packages
 WHERE project='manual-seed-round-6-20260418'
 ORDER BY device_serial;

-- Проверка: платформы, которые guard должен заблокировать для каждого устройства
-- (все 3 платформы × 17 устройств = 51 потенциальных block'ов)
WITH seeded AS (
  SELECT device_serial FROM account_packages
   WHERE project='manual-seed-round-6-20260418'
)
SELECT COUNT(DISTINCT s.device_serial) AS devices,
       COUNT(DISTINCT s.device_serial) * 3 AS blocking_triples
  FROM seeded s;

COMMIT;
