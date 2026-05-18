# WP #77 — Дубликат-детектор: переход на content_hash (sha256)

- **Статус:** Design approved (2026-05-18)
- **OpenProject WP:** [#77 «Требует одобрение из-за дубликата контента, но это уникальный ролик»](https://op.contenthunter.ru/work_packages/77)
- **Author:** Danil + Claude
- **Repo:** `validator-contenthunter`
- **Database:** `openclaw` (Postgres), таблица `validator_content`

## Background

Анастасия (роль `client` в проекте Content Hunter) загрузила два разных коротких ролика, которые валидатор пометил как дубликаты уже существующего контента. На скрине жалобы (WP #77 attachment) виден баннер «⚠️ Похоже на дубликат контента #N» и блокирующий статус «Требует одобрения». Затронутые записи:

| id   | project_id | filename                                       | file_size | duration | duplicate_of_id |
|------|------------|------------------------------------------------|-----------|----------|-----------------|
| 2123 | 96         | copy_0CDBBE9C-…-51082305C76A.mov               | 34 163 011 | 18.067   | 2120            |
| 2132 | 99         | дата2.mp4                                       |  6 611 525 | 18.552744 | 2130            |

Пары 2120↔2123 и 2130↔2132 имеют разные размеры файлов (1.3% и 0.12% diff) и почти-равную длительность (0.28с и 0.0с diff) — это и есть классические false-positives текущей эвристики.

### Текущая логика (`backend/src/services/uniqueness_service.py`)
```python
# Дубликат: duration ±0.5 сек И file_size diff < 5%
if duration_diff <= 0.5 and size_diff < 0.05:
    return {"is_duplicate": True, ...}
```

Эвристика пыталась ловить «уникализированные» (пере-сжатые) копии, но в реальности тегирует любые два коротких видео с типовой длиной и CRF-битрейтом одного жанра. Поле `content_hash` в схеме `ValidatorContent` существует с самого старта и проиндексировано, но **никогда не вычисляется** (NULL во всех записях).

### Текущий UX-эффект
- `is_duplicate=True` → `status=needs_review` (блокирует пайплайн)
- В UI: баннер «⚠️ Похоже на дубликат контента #N»
- Кнопка «✅ Одобрить дубль» — **только manager/admin** (`/api/content/{id}/approve`). Client (как Анастасия) разблокировать сам не может → жалоба.

## Goal

На этапе загрузки контента ловить **только полные клоны** (защита от случайного повторного дублирования). Не пытаться ловить уникализированные/пере-сжатые копии — это другая задача и не часть этой фичи.

«Полный клон» = байт-идентичный файл в рамках того же `project_id`.

## Non-goals

- **Perceptual hash / video fingerprint** (pHash от кадров) — отдельная фича. Если когда-нибудь понадобится smart-dedupe — это будет новая задача.
- **Uniqueness для post/carousel** — out of scope. Клиент жалуется на video; image/carousel uniqueness сейчас не вычисляется (`validation.py:235` устанавливает `is_duplicate=False`), оставляем как есть.
- **Изменение permission «Одобрить дубль»** — кнопка остаётся manager-only. Permission-модель не трогаем.
- **Cross-project dedup** — намеренно остаёмся в `project_id` scope. Один и тот же файл, загруженный в два разных проекта, дублем не считается.

## Architecture

Точка истины для дубля — **`content_hash` (sha256 hex от байтов файла)** в рамках `project_id` и `content_type=video`. Старая эвристика `duration+size` удаляется целиком.

### Точки записи hash
В обоих местах `file_bytes` уже целиком в памяти к моменту S3-upload, sha256 — одна строка без extra I/O:

- `backend/src/routers/upload.py:~312` — первичный upload видео
- `backend/src/routers/content.py:~381` — replace-video endpoint

Только для `content_type == video`. Для post/carousel — не считаем (см. Non-goals).

### Точка чтения hash
`backend/src/services/uniqueness_service.py` — новый `check_uniqueness(project_id, content_hash, content_id, db)`. Сигнатура меняется. Call site: `validation.py:113`.

### Миграция
**Не требуется.** Столбец `content_hash` уже существует в схеме `ValidatorContent` с одиночным индексом (`Column(String, nullable=True, index=True)`). При наших объёмах (десятки тысяч записей максимум) этот single-column btree-index уже покрывает runtime SELECT `WHERE content_hash = X` (selectivity sha256 hex почти уникальна → план запроса использует index, дальше фильтрует по `project_id` и `content_type` на одной-двух строках). Композитный partial-index можно добавить позже, если EXPLAIN покажет необходимость. YAGNI.

## Backend changes

### 1. `services/uniqueness_service.py` — переписать

```python
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from ..models.content import ValidatorContent, ContentType


async def check_uniqueness(
    project_id: int,
    content_hash: Optional[str],
    content_id: int,
    db: AsyncSession,
) -> dict:
    """
    Полный клон: тот же sha256 в рамках одного project_id (только video).
    «Оригинал» = запись с минимальным id в hash-группе, ВКЛЮЧАЯ
    проверяемую. Если проверяемая запись и есть min(id) — не дубль.
    """
    if not content_hash:
        return {"is_duplicate": False, "duplicate_of_id": None}

    result = await db.execute(
        select(func.min(ValidatorContent.id)).where(
            ValidatorContent.project_id == project_id,
            ValidatorContent.content_hash == content_hash,
            ValidatorContent.content_type == ContentType.video,
        )
    )
    min_id = result.scalar_one_or_none()
    if min_id is None or min_id == content_id:
        return {"is_duplicate": False, "duplicate_of_id": None}
    return {"is_duplicate": True, "duplicate_of_id": min_id}
```

Заметки по поведению:
- В hash-группу включаем саму проверяемую запись (через `func.min`, БЕЗ `id != content_id`). Иначе при re-validation самого раннего оригинала после появления более поздней копии запрос вернёт late-id и **flip'нет оригинал в дубль** — это то, чего быть не должно. Сравнение `min_id == content_id` корректно идентифицирует «я и есть оригинал».
- При трёх копиях `id ∈ {100, 105, 110}`: 100→not_dup, 105→100, 110→100. Стабильно.
- Добавить `log.info("uniqueness: content_id=%s min_in_group=%s", content_id, min_id)` для триаж-видимости.

### 2. `routers/upload.py` — добавить sha256

После `file_bytes = await file.read()` и до создания/обновления записи:
```python
import hashlib
...
content.content_hash = hashlib.sha256(file_bytes).hexdigest()
```
Только в ветке video-upload. Для carousel/post — не трогаем.

### 3. `routers/content.py` (replace-video) — то же самое

После `file_bytes = await file.read()`:
```python
content.content_hash = hashlib.sha256(file_bytes).hexdigest()
```
Строки `content.is_duplicate = False` / `content.duplicate_of_id = None` (`content.py:423-424`) **можно убрать** — `_do_full_validation` всё равно пересчитает через новый `check_uniqueness`.

### 4. `routers/validation.py:113-118` — обновить call site

```python
uniq = await check_uniqueness(
    content.project_id, content.content_hash, content.id, db
)
```

Финальный статус (line 121-126) НЕ меняется — `uniq["is_duplicate"]` всё так же кидает в `needs_review`.

### 5. Migration

Не нужна — см. секцию «Architecture → Миграция».

## Backfill script

`backend/scripts/backfill_content_hash.py` — однократный management script.

### Логика
```python
# Псевдокод
async def main(dry_run: bool, limit: int | None):
    async with SessionLocal() as db:
        rows = await db.execute(
            select(ValidatorContent).where(
                ValidatorContent.content_type == ContentType.video,
                ValidatorContent.content_hash.is_(None),
                ValidatorContent.s3_key.isnot(None),
            ).order_by(ValidatorContent.id.asc()).limit(limit)
        )
        stats = {"processed": 0, "marked_duplicate": 0, "auto_unblocked": 0, "skipped_missing": 0}
        for content in rows.scalars():
            try:
                sha = await stream_sha256_from_s3(content.s3_key)
            except S3KeyMissing:
                stats["skipped_missing"] += 1
                log.warning("skip id=%s — s3 key missing", content.id)
                continue
            if dry_run:
                log.info("would set id=%s hash=%s", content.id, sha[:12])
                continue
            content.content_hash = sha
            uniq = await check_uniqueness(content.project_id, sha, content.id, db)
            was_blocked_by_dup = (
                content.is_duplicate is True
                and content.status == ContentStatus.needs_review
                and content.moderation_status == ModerationStatus.passed
            )
            content.is_duplicate = uniq["is_duplicate"]
            content.duplicate_of_id = uniq["duplicate_of_id"]
            if not uniq["is_duplicate"] and was_blocked_by_dup:
                # снимаем блок false-positive'а, БЕЗ Delivery webhook
                content.status = ContentStatus.approved
                stats["auto_unblocked"] += 1
            if uniq["is_duplicate"]:
                stats["marked_duplicate"] += 1
            stats["processed"] += 1
            await db.commit()
        log.info("backfill done: %s", stats)
```

### Ключевые решения
- **Stream-hash из S3**: `boto3.client('s3').get_object(...)`, `iter_chunks(chunk_size=8*1024*1024)`, `sha256.update(chunk)` — не держим файл целиком в памяти.
- **Порядок обхода**: `ORDER BY id ASC` совпадает с runtime-логикой `check_uniqueness` — старший id всегда «оригинал», поздние помечаются как его дубли.
- **Auto-approve правило**: разблокируем только записи, которые были в `needs_review` **исключительно** из-за false-positive (модерация уже `passed`). Записи с другими модерационными проблемами оставляем как есть.
- **Webhook**: `notify_content_approved` **не зовётся**. Backfill только обновляет флаги/статус в БД. Если Delivery подхватывает approved-контент по своим путям — подхватит. Массовый запуск webhook'ов на исторических данных нежелателен (риск массовой мгновенной уникализации).
- **Идемпотентность**: фильтр `content_hash IS NULL` → повторный запуск пропускает уже обработанные.
- **Запуск**: ручной, два прогона. Сначала `python -m scripts.backfill_content_hash --dry-run`, проверка по stats и log sample. Затем `--apply`.
- **Размер работы**: оценить заранее: `SELECT count(*), SUM(file_size_bytes) FROM validator_content WHERE content_type='video' AND content_hash IS NULL AND s3_key IS NOT NULL`. Если суммарный объём огромен — гонять пачками `--limit N`.

## Frontend changes

Минимум. Текст banner в **обоих** местах рендера ([[feedback_validator_two_slot_renderers]]):

- `frontend/src/pages/client/ContentDetail.vue:345-347`
- `frontend/src/components/validation/ValidationDetails.vue:85-87`

Было:
```vue
<div v-if="content.is_duplicate" class="...">
  ⚠️ Похоже на дубликат контента #{{ content.duplicate_of_id }}
</div>
```

Станет:
```vue
<div v-if="content.is_duplicate" class="...">
  🛑 Это точная копия контента
  <router-link :to="`/content/${content.duplicate_of_id}`">
    #{{ content.duplicate_of_id }}
  </router-link>
  (тот же файл)
</div>
```

Семантика `is_duplicate` boolean не меняется — список карточек, dashboard'ы, фильтры работают без правок. Кнопка «✅ Одобрить дубль» (manager/admin only) остаётся как есть — это теперь осознанный «грузим копию, я знаю».

## Tests

`backend/tests/test_uniqueness_hash.py` — live-DB тесты, использующие autouse `engine.dispose` fixture из `conftest.py` ([[feedback_validator_test_engine_dispose]]).

1. **`test_identical_files_marked_duplicate`** — тот же `file_bytes` дважды через upload endpoint в одном `project_id` → второй `is_duplicate=True`, `duplicate_of_id=<id_первого>`, `status=needs_review`.

2. **`test_different_files_not_duplicate`** — два разных коротких видео с одинаковой `duration` и близким `file_size` (как 2120/2123 и 2130/2132 — duration diff <0.5с, size diff <5%) → оба `is_duplicate=False`. **Regression-guard** на убитую duration+size эвристику.

3. **`test_same_file_different_projects`** — тот же файл, разные `project_id` → оба `is_duplicate=False`. Изоляция по проекту.

4. **`test_backfill_false_positive_unblocks`** — pre-seed два video-record в одном `project_id`, обе с `content_hash=NULL`, **разные** sha256 (через мок `stream_sha256_from_s3`). Первая в production-style: `is_duplicate=False`, `status=approved`. Вторая — ложно помечена старой эвристикой: `is_duplicate=True`, `status=needs_review`, `moderation_status=passed`. После backfill вторая `is_duplicate=False` и `status` переходит `needs_review`→`approved`, `notify_content_approved` **не вызывался** (mock not called).

5. **`test_backfill_real_duplicate_stays_blocked`** — pre-seed два video-record с **одинаковыми** sha256 (через мок). Первая `is_duplicate=False/approved`, вторая ранее `is_duplicate=True/needs_review/passed`. Backfill: первая остаётся `approved` (получает hash), **вторая остаётся `is_duplicate=True` и `status=needs_review`** (real-positive не разблокируется). Парный regression-guard к тесту 4.

### Покрытие replace-video
Отдельного unit-теста на `content.py:replace-video` нет — endpoint требует multipart+S3+auth plumbing, а одностраничный mirror-test всего лишь повторно подтвердил бы, что `hashlib.sha256` работает. Покрытие изменения обеспечивается: (a) codex review PR-диффа, (b) production smoke-проверкой 2123/2132 после backfill, (c) ручной QA через UI после деплоя.

### Фикстуры
Два маленьких .mp4 в `backend/tests/fixtures/` (по 10-20 КБ), проходящие preflight (есть video stream + audio stream). Если подходящих нет — генерим через ffmpeg один раз и коммитим.

### НЕ тестируем
- Сам факт sha256 (это `hashlib` — доверяем).
- S3 streaming end-to-end (требует moto/localstack — overkill; для backfill достаточно функционального теста с замоканной `stream_sha256_from_s3`).

## Risks

1. **Backfill compute**. При ~10 000+ видео по 30+ МБ скачка из S3 займёт часы. Mitigation: `--dry-run` сначала, оценка по `SELECT count + SUM(file_size_bytes)`, `--limit` пачками, при огромном объёме — ночной прогон.

2. **Auto-approve в backfill**. Возможны редкие записи, которые `moderation_status=passed`, но менеджер сознательно держал в `needs_review` по нефиксированной в системе причине. Mitigation: `--dry-run` отчёт показывает «N записей будут переведены needs_review→approved» + sample 10 строк; смотрим глазами перед `--apply`.

3. **Race: одновременная загрузка двух одинаковых файлов**. Теоретически оба могут пройти SELECT до коммита первого → оба останутся `is_duplicate=False`. Реальная вероятность пренебрежима (UI грузит последовательно), последствия — мягкие («не пометили дублем», не ошибка). Не чиним.

4. **sha256 collision**. Пренебрежимо. Не рассматриваем.

## Open questions

Нет открытых вопросов на момент design approval.

## Done criteria

- [ ] Backend: `check_uniqueness` использует `content_hash`, sha256 пишется в upload+replace-video
- [ ] Frontend: banner-текст обновлён в `ContentDetail.vue` и `ValidationDetails.vue`
- [ ] Все 5 тестов зелёные на live-DB
- [ ] Backfill script написан, прогнан `--dry-run`, stats посмотрены, прогнан `--apply`
- [ ] Записи 2123 и 2132 (и аналогичные false-positives) фактически разблокированы и `status=approved` (либо явно отмечены как НЕ-разблокируемые с причиной)
- [ ] WP #77 — комментарий с house-style summary (Что было не так → Что сделано → Что осталось) и close
- [ ] PR review (codex review --uncommitted) — 0 P1

## Next step

После approval этой спеки — переход в `superpowers:writing-plans` для детализированного implementation plan.

## Implementation note (post-mortem, 2026-05-18)

Во время P4 code review выяснилось, что у валидатора есть **второй (главный)** upload-путь, не учтённый в этой спеке: `/api/upload/presign` → client uploads to S3 directly → `/api/upload/complete`. В `/complete` handler у backend'а нет `file_bytes` — файл уже в S3. Spec ошибочно покрывал только `/upload/file` (direct multipart) и `replace-video`.

Scope расширен прямо в имплементации:
- Добавлена точка записи hash в `/upload/complete` (видео-ветка) — backend стримит файл из S3 в executor, считает sha256.
- Helper `compute_s3_object_sha256(s3_key) -> str` вынесен в новый файл `backend/src/services/content_hash_service.py` — переиспользуется и `/complete` handler'ом, и backfill-скриптом (хотя план изначально предполагал inline-helper только в backfill).
- В `/complete` хеш считается non-fatal: при S3 hiccup лог warning + content_hash=NULL, upload не падает. Backfill подхватит позже.

Это закрыло critical gap: без `/complete` фикс был бы мёртвым для production (большинство uploads идут через presign-путь).

Также во время codex review плана был пойман flip-баг: в первоначальной формулировке `check_uniqueness` использовала `WHERE id != content_id ORDER BY id ASC LIMIT 1`, что при re-validation самого раннего оригинала после появления более поздней копии flip'нуло бы оригинал в дубль. Правильная семантика — `func.min(id)` over hash-группу INCLUDING саму запись, с проверкой `min_id == content_id`. Эта секция в спеке выше уже исправлена; план зафиксировал правильную версию с первого implementer-dispatch'а.
