-- WP#111 — 4 нейтральные схемы (31-34) на новых оверлеях (content_video_index 11-14)
-- + одобрение для проекта Ирбис (103). Прод openclaw. Идемпотентно по одобрениям.
BEGIN;

-- 1. Клонируем одобренные Ирбисом схемы 6/17/25/26 → 31/32/33/34 (все колонки), меняем только override-поля.
CREATE TEMP TABLE _clones ON COMMIT DROP AS
  SELECT * FROM unic_schemes WHERE id IN (6, 17, 25, 26);

UPDATE _clones SET id=31, label='Схема 31', content_video_index=11, metadata_title='Creative Video 31' WHERE id=6;
UPDATE _clones SET id=32, label='Схема 32', content_video_index=12, metadata_title='Creative Video 32' WHERE id=17;
UPDATE _clones SET id=33, label='Схема 33', content_video_index=13, metadata_title='Creative Video 33' WHERE id=25;
UPDATE _clones SET id=34, label='Схема 34', content_video_index=14, metadata_title='Creative Video 34' WHERE id=26;
UPDATE _clones SET status=true, created_at=now(), updated_at=now(), synced_at=now();

INSERT INTO unic_schemes SELECT * FROM _clones;

-- 2. Одобряем 31-34 для Ирбиса (103). Старые 6/17/25/26 не трогаем.
INSERT INTO validator_scheme_preferences (project_id, scheme_id, status, notes, reviewed_at, created_at, updated_at)
VALUES
  (103, 31, 'approved', 'WP#111 нейтральные оверлеи', now(), now(), now()),
  (103, 32, 'approved', 'WP#111 нейтральные оверлеи', now(), now(), now()),
  (103, 33, 'approved', 'WP#111 нейтральные оверлеи', now(), now(), now()),
  (103, 34, 'approved', 'WP#111 нейтральные оверлеи', now(), now(), now())
ON CONFLICT (project_id, scheme_id)
  DO UPDATE SET status='approved', notes=EXCLUDED.notes, updated_at=now();

COMMIT;
