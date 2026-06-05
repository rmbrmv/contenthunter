# Дизайн: приоритет проектных логотипов в уникализации

**Дата:** 2026-06-05
**Ветка:** `feat-unic-project-logo-priority-2026-06-05`
**Статус:** дизайн согласован, переход к плану реализации

## Проблема

В разделе загрузки контента для уникализации можно загрузить логотипы под
конкретный проект (`validator_unic_content`, `content_type='image'`,
`label LIKE 'logo%'`, `project_id=<конкретный>`). Но ни превью схем, ни
финальный рендер уникализации эти логотипы не используют — берётся только
логотип из «распаковки» клиента (`validator_brand_profiles.logo_url`).

Причина — инвертированный приоритет источника логотипа в двух местах кода.

## Цель

Новый порядок выбора логотипа:

1. **Логотипы под конкретный проект** — `validator_unic_content`,
   `content_type='image'`, `label LIKE 'logo%'`, `project_id=<конкретный>`.
2. Если проектных нет — **распаковка**, `validator_brand_profiles.logo_url`.
3. Legacy fallback — `validator_projects.logo_url` (только в превью; в проде
   пуст у всех проектов, оставляем как есть).

Универсальные логотипы (`project_id=0`) распаковку **не** перебивают —
override делают только логотипы, привязанные к конкретному проекту.

## Согласованные решения

- **Скоуп:** и превью схем (validator), и финальный рендер (unic-worker).
- **Несколько логотипов под проект:** ротация по схемам через существующий
  `content_logo_index` (в рендере); в превью — первый логотип.
- **Универсальные `project_id=0`:** не перебивают распаковку.

## Компонент 1 — финальный рендер

**Файл:** `unic-worker/worker.py`, функция `resolve_logo` (стр. ~266).

Текущее поведение (приоритет инвертирован относительно желаемого):
1. `validator_brand_profiles.logo_url` (распаковка) — первым.
2. `validator_unic_content` проектные логотипы — fallback, с ротацией по
   `logo_idx` (`logos[(logo_idx-1) % len(logos)]`).

Новое поведение:
1. Запрос проектных логотипов:
   ```sql
   SELECT * FROM validator_unic_content
   WHERE content_type='image' AND label LIKE 'logo%' AND project_id=$1
   ORDER BY id
   ```
   Пустые/NULL `file_path` отфильтровываются. Если есть непустые — берётся
   `logos[(logo_idx-1) % len(logos)]` (ротация по `content_logo_index`,
   механизм уже есть в коде, сейчас мёртв из-за приоритета brand_profile).
2. Если проектных логотипов нет — `validator_brand_profiles.logo_url`.
3. Иначе — `None`.

Дополнительно:
- Обновить docstring (описывает старый приоритет).
- Kill-switch: env `UNIC_PROJECT_LOGO_PRIORITY_ENABLED`. Default ON.
  OFF → старое поведение (brand_profile первым).

## Компонент 2 — превью схем

**Файл:** `validator-contenthunter/backend/src/routers/schemes.py`,
резолв `logo_url` (стр. ~357).

Текущее поведение:
```python
logo_url = logo_row["logo_url"] or logo_row["project_logo"]
# brand_profile.logo_url или validator_projects.logo_url
```

Новое поведение — перед резолвом добавить запрос первого проектного логотипа:
```sql
SELECT file_path FROM validator_unic_content
WHERE content_type='image' AND label LIKE 'logo%' AND project_id=:pid
  AND file_path IS NOT NULL AND file_path <> ''
ORDER BY id LIMIT 1
```
Порядок: проектный логотип → `brand_profile.logo_url` →
`validator_projects.logo_url`.

В превью используется **первый** проектный логотип (без ротации — превью
одно на схему). За тем же kill-switch `UNIC_PROJECT_LOGO_PRIORITY_ENABLED`
(OFF → старое поведение).

Побочный эффект: `payload_hash` включает `logo_url`, поэтому смена резолва
триггерит перегенерацию превью. Это идемпотентно и ожидаемо.

## Поток данных

```
Проект с логотипами в "контенте"?  (validator_unic_content, project_id=N, label logo%)
   ├─ ДА  → проектный логотип
   │         рендер  : ротация по content_logo_index (logos[(idx-1) % len])
   │         превью  : первый логотип (ORDER BY id LIMIT 1)
   └─ НЕТ → brand_profile.logo_url (распаковка)
             └─ (legacy: validator_projects.logo_url — только превью)
```

## Тестирование (TDD)

**worker (`unic-worker`):**
- Проектные логотипы есть → берётся проектный, не brand_profile.
- Проектных нет → brand_profile.
- Ротация: `content_logo_index` = 1 / 2 / N (включая modulo-обёртку).
- Логотип с пустым/NULL `file_path` пропускается.
- Универсальные `project_id=0` логотипы не учитываются (запрос по `project_id=$1`).
- Kill-switch OFF → старое поведение (brand_profile первым).

**validator (`schemes.py`):**
- Первый проектный логотип попадает в payload `logo_url`.
- Проектных нет → fallback на brand_profile → projects.logo_url.
- Универсальные `project_id=0` логотипы игнорируются.
- Kill-switch OFF → старое поведение.

## Вне скоупа (YAGNI)

- AI-варианты логотипов (`logo_variants` / `logo_selections`, WP#137) —
  отдельная нерешённая задача интеграции, не трогаем.
- Универсальные логотипы `project_id=0` — поведение не меняем.
- Паттерны, overlay-видео, звук, шрифты — не трогаем.
- Миграции БД не требуются (используем существующие таблицы/колонки).

## Деплой (предварительно)

- unic-worker: реальный prod-воркер — standalone PM2 id0 на `91.98.180.103`
  (каталог не под git → scp `worker.py` + `pm2 restart`).
- validator: backend pull + `pm2 restart` (id24 на 72.56.107.157); фронт не
  затрагивается.
- Kill-switch'и обоих компонентов — через `.env` соответствующих сервисов.
