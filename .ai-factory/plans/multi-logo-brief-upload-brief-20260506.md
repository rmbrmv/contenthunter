# Несколько логотипов в брифе клиента — backlog brief

**Дата:** 2026-05-06
**Триггер:** после фикса `resolve_logo` (commit `bead397`) клиент в /client/brand загружает один лого, и воркер уникализации использует именно его. Пользователь хочет дать клиенту возможность загружать несколько вариантов лого, чтобы они ротировались по `unic_schemes.content_logo_index`, как это уже умеет legacy-пул `validator_unic_content`.
**Репо:** `validator-contenthunter` (frontend + backend) + `autowarm` (worker).

---

## Контекст

Текущая модель данных:

- `validator_brand_profiles.logo_url TEXT` — одна ссылка.
- BrandPage.vue — одно поле + кнопка «загрузить файл», write через `POST /api/brand/upload-image (field=logo)`, save через `PUT /api/brand/profile`.
- Воркер: `resolve_logo(conn, project_id, logo_idx)` — если `logo_url` непуст, возвращает один файл (логотип не ротируется); fallback на `validator_unic_content` (legacy, поддерживает ротацию).

После апгрейда: клиент сам управляет 1..N логотипами, ротация по индексу схемы возможна и без legacy-пула.

---

## Опции схемы

**Опция A — `logo_urls JSONB` массив рядом с существующим `logo_url`.**
- Миграция: `ALTER TABLE validator_brand_profiles ADD COLUMN logo_urls JSONB DEFAULT '[]'::jsonb;`
- Чтение: если `logo_urls` непуст → ротация; иначе если `logo_url` непуст → один файл (back-compat); иначе fallback unic_content.
- Плюсы: минимум изменений в коде (один SELECT на профиль), back-compat без миграции данных.
- Минусы: два поля для одной сущности; нужно синхронизировать или решить какое «главное».

**Опция B — отдельная таблица `validator_brand_logos(project_id, ord, url)`.**
- Миграция: `CREATE TABLE validator_brand_logos (id SERIAL PK, project_id INT REFERENCES validator_projects(id) ON DELETE CASCADE, ord INT NOT NULL DEFAULT 0, url TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW(), UNIQUE(project_id, ord));`
- Чтение: `SELECT url FROM validator_brand_logos WHERE project_id=$1 ORDER BY ord, id`.
- Запись из BrandPage: drag&drop reorder + add/remove + per-file upload.
- Плюсы: чистая модель, легко добавлять/удалять/переупорядочивать, мажорно поддерживает любое N.
- Минусы: миграция данных существующих `logo_url` → `validator_brand_logos` (одна строка на проект).

**Рекомендация — Опция B.** Чище семантически, готова к доп. полям (alpha override, scale override per-logo) если потребуется. Опция A — компромисс если хочется ускоренный merge.

---

## Затронутые точки

### Backend (`validator-contenthunter`)

- `backend/migrations/` — добавить миграцию (новая таблица или новая колонка).
- `backend/src/routers/brand.py`:
  - GET `/api/brand/profile` — возвращать `logos: [...]` (массив URL).
  - POST `/api/brand/upload-image` — после успешного upload в S3 делать INSERT в `validator_brand_logos` (вариант B) или append в `logo_urls` JSONB (вариант A).
  - DELETE `/api/brand/logo/:id` — новый endpoint для удаления.
  - PUT `/api/brand/logos/reorder` — массивы новых `ord`.

### Frontend (`validator-contenthunter`)

- `frontend/src/pages/client/BrandPage.vue`:
  - Сегодня: одно поле + одна кнопка + одно превью (line 81-93).
  - После: список карточек логотипов с drag-handle, кнопка «+ добавить ещё» (multi-file `<input>`), per-card delete.
  - State: `form.logos: string[]` (или `{id, url, ord}[]` для варианта B).

### Worker (`autowarm/unic-worker/worker.py`)

- `resolve_logo` — расширить: брать массив (через JOIN или второй SELECT) вместо одного `logo_url`. Ротация по `(logo_idx-1) % len(logos)` идентичная legacy-логике. Если массив пустой — fallback на `validator_unic_content`.
- Тесты: добавить кейс в `tests/test_unic_logo_resolver.py` — массив из N клиентских лого ротируется корректно.

---

## Риски/задачи на потом

- **Миграция legacy `logo_url`** для уже заполненных проектов: для каждого `validator_brand_profiles.logo_url IS NOT NULL` — INSERT в `validator_brand_logos` (если Opt B). Нужен SQL-скрипт + rollback план.
- **UI confirmation для удаления** — клиент случайно может стереть единственный лого.
- **Мax N** — практически разумно ограничить (10–20?).
- **Размер** — current MAX 10 MB на файл; при N лого total upload может стать значительным, но не критичным.

---

## Definition of Done

- Клиент загружает 5+ лого в /client/brand, видит карточки, может удалять и менять порядок.
- Запускает уникализацию пакета из 5 схем — каждая схема получает разный лого согласно `content_logo_index`.
- Если ни одного лого не загружено — fallback на `validator_unic_content` (legacy) ещё работает.
- `pytest tests/test_unic_logo_resolver.py` зелёный с новым кейсом.

---

## Связанное

- Главный фикс (single-logo + fallback): commit `bead397` 2026-05-06.
- Inverted-priority C explained: см. memory `project_unic_logo_resolver.md`.
