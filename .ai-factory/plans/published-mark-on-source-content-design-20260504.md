# Published mark on source content — design spec (2026-05-04)

## 1. Контекст и проблема

Source-видео в `validator_content` не получают визуального индикатора публикации, хотя цепочка `validator_content → unic_tasks → unic_results → publish_queue → publish_tasks` уже даёт всё нужное для подсчёта.

- `ContentStatus.published` определён в enum, но физически нигде не выставляется (мёртвый код, проверено `grep` в `backend/src/`).
- На проде 0 записей `validator_content.status='published'`, при этом 177 строк `publish_queue.status='done'`.
- В `SlotCard.vue` уже зарезервирован визуальный стиль для `published`-статуса (`statusMap.published = 📣 + bg-purple-100`), но он недостижим.

**Цель.** Одним взглядом видеть в Планировщике (`/dashboard`), что слот опубликован хотя бы где-то, а внутри карточки контента (`/content/<id>`) — на каких платформах и в скольких аккаунтах.

## 2. Сценарии

1. Юзер открывает `/dashboard` → у слотов с уже опубликованным контентом виден один общий бейдж `📣 опубликовано` (фиолетовый), вместо approval-бейджа.
2. Юзер открывает `/content/1894` → видит блок «📣 Опубликовано» с тремя плитками IG/TT/YT и счётчиком аккаунтов под каждой; клик по плитке с `accounts > 0` раскрывает список `@usernames`.
3. Drag-n-drop опубликованного слота **не работает** — backend помечает слот как immovable, фронт через `slot.movable_unpublished=false` не даёт перетащить.

## 3. Источник правды и SQL

**Никаких изменений схемы.** Источник истины — `publish_queue.status='done'` через JOIN с `unic_tasks/unic_results` (видео-путь) или прямой `pq.carousel_content_id` (карусели).

### 3.1. SQL для одного контента (`get_publish_summary`)

```sql
WITH published AS (
  SELECT pq.platform, pq.account_username
  FROM unic_tasks ut
  JOIN unic_results ur ON ur.task_id = ut.id
  JOIN publish_queue pq ON pq.unic_result_id = ur.id
  WHERE ut.content_id = :content_id
    AND pq.status = 'done'
    AND lower(pq.platform) IN ('instagram','tiktok','youtube')
    AND pq.account_username IS NOT NULL

  UNION ALL

  SELECT pq.platform, pq.account_username
  FROM publish_queue pq
  WHERE pq.carousel_content_id = :content_id
    AND pq.status = 'done'
    AND lower(pq.platform) IN ('instagram','tiktok','youtube')
    AND pq.account_username IS NOT NULL
)
SELECT
  lower(platform) AS platform,
  count(DISTINCT account_username) AS accounts,
  array_agg(DISTINCT account_username ORDER BY account_username) AS account_list
FROM published
GROUP BY lower(platform);
```

И отдельно `first_published_at`:

```sql
SELECT min(pq.updated_at)
FROM publish_queue pq
LEFT JOIN unic_results ur ON ur.id = pq.unic_result_id
LEFT JOIN unic_tasks ut ON ut.id = ur.task_id
WHERE pq.status = 'done'
  AND lower(pq.platform) IN ('instagram','tiktok','youtube')
  AND (ut.content_id = :content_id OR pq.carousel_content_id = :content_id);
```

### 3.2. SQL для bulk-вызова (`get_published_flags`)

Возвращает `{content_id: bool}` для всех слотов недели одним запросом:

```sql
SELECT content_id, true AS is_published
FROM (
  SELECT ut.content_id
  FROM publish_queue pq
  JOIN unic_results ur ON ur.id = pq.unic_result_id
  JOIN unic_tasks ut ON ut.id = ur.task_id
  WHERE pq.status = 'done'
    AND lower(pq.platform) IN ('instagram','tiktok','youtube')
    AND ut.content_id = ANY(:content_ids)

  UNION

  SELECT pq.carousel_content_id AS content_id
  FROM publish_queue pq
  WHERE pq.status = 'done'
    AND lower(pq.platform) IN ('instagram','tiktok','youtube')
    AND pq.carousel_content_id = ANY(:content_ids)
) t
GROUP BY content_id;
```

Контенты без `done`-строк просто не попадают в результат → в Python-словаре `is_published` для них = `False`.

### 3.3. Индексы (миграция Alembic)

```python
def upgrade():
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_unic_tasks_content_id
            ON unic_tasks (content_id) WHERE content_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS ix_publish_queue_unic_result_done
            ON publish_queue (unic_result_id) WHERE status = 'done';
        CREATE INDEX IF NOT EXISTS ix_publish_queue_carousel_done
            ON publish_queue (carousel_content_id)
            WHERE status = 'done' AND carousel_content_id IS NOT NULL;
    """)

def downgrade():
    op.execute("""
        DROP INDEX IF EXISTS ix_unic_tasks_content_id;
        DROP INDEX IF EXISTS ix_publish_queue_unic_result_done;
        DROP INDEX IF EXISTS ix_publish_queue_carousel_done;
    """)
```

`CONCURRENTLY` не нужен (`publish_queue` ~940 строк, `unic_tasks` ~1555). Бэкфилл не требуется — счётчики вычисляются от существующих 177 `done`-строк сразу после деплоя.

## 4. API-контракт

### 4.1. Новый сервис `backend/src/services/publish_summary_service.py`

```python
async def get_publish_summary(content_id: int, db: AsyncSession) -> dict:
    """
    Detail-уровень для ContentDetail. Структура:
    {
      "instagram": {"accounts": 5, "account_list": ["@a","@b",...]},
      "tiktok":    {"accounts": 2, "account_list": [...]},
      "youtube":   {"accounts": 0, "account_list": []},
      "first_published_at": "2026-04-15T12:34:56Z" | None,
      "is_published": True
    }
    """

async def get_published_flags(
    content_ids: list[int], db: AsyncSession
) -> dict[int, bool]:
    """Bulk-флаг для дашборда. Один SQL, см. §3.2."""
```

`publish_queue/unic_tasks/unic_results` намеренно НЕ моделируем в валидаторском ORM — SQL шлём через `text()`, чтобы не размазывать ownership с autowarm.

Платформа всегда нормализуется к `lower()`. SQL из §3.1 возвращает только платформы с непустыми `done`-строками; в Python-слое после запроса добиваем недостающие платформы из whitelist'а (`instagram`/`tiktok`/`youtube`) до полного объекта с `accounts=0`, `account_list=[]` — чтобы фронт всегда получал три плитки.

### 4.2. Изменения в существующих handler'ах

| Где | Что добавляется |
|---|---|
| `_content_to_dict` (`backend/src/routers/content.py:446`) | Вызывает `get_publish_summary(c.id)`. В response: `published_summary` (объект из §4.1), `is_published: bool`. **`status` НЕ переписывается** — остаётся осью одобрения. |
| `get_week_slots` (`backend/src/services/schedule_service.py:116`) | После SELECT слотов недели — один bulk-вызов `get_published_flags([content_ids])`. В `_slot_to_dict_with_content` добавляется `is_published: bool`. |
| `is_slot_movable_unpublished` (`backend/src/services/schedule_service.py`) | Расширяется: возвращает `False` если для контента слота `is_published=True` (даже если physical `slot.status` и `content.status` — не `'published'`). Защита drag/drop. |

`_content_to_dict` сейчас sync. Решение: sync-сигнатуру оставляем (для коллеров без db-сессии — `_content_short` в `dashboard.py`), а в `routers/content.py` все продовые коллеры уже в async-контексте — добавляем рядом async-обёртку `_content_to_dict_with_publish` и зовём её там, где нужен `published_summary`.

**Никаких изменений в autowarm/publisher** — фича чисто аддитивна на стороне валидатора.

### 4.3. Архитектурное решение по `status`

Lazy-override `status='published'` в API-слое **отвергнут**: `content.status` enum читается в логике (CSS-ветки `ContentDetail.vue:30-33` для approval-палитры, `_slot_to_dict.196` и т.д.). Override создаст коллатеральный ущерб (зелёная плашка одобрения исчезнет, drag-условия станут зависеть от строкового совпадения).

Вместо этого вводим **новую ортогональную ось** `is_published: bool`. SlotCard и ContentDetail читают её отдельно от `status`. Так публикация и одобрение остаются независимыми.

`ContentStatus.published` и `SlotStatus.published` enum-значения остаются в коде (не удаляем — backwards compat), но **не выставляются**. Считаем их deprecated.

## 5. UI

### 5.1. SlotCard.vue (`frontend/src/components/calendar/SlotCard.vue`)

```ts
const isPublished = computed(() => !!props.content?.is_published)

const statusLabel = computed(() =>
  isPublished.value
    ? '📣 опубликовано'
    : statusMap[props.content?.status]?.label ?? '📁'
)
const statusBadgeClass = computed(() =>
  isPublished.value
    ? 'bg-purple-100 text-purple-700'
    : statusMap[props.content?.status]?.cls ?? 'bg-gray-100 text-gray-600'
)
```

Один бейдж на слот. Approved/needs_review/rejected показываются пока публикации нет; первый `done` в `publish_queue` переключает на «📣 опубликовано».

Drag-логика SlotCard **не меняется** — `canDrag.value` зависит от `isMovableUnpublished.computed`, которое читает `slot.movable_unpublished` (приходит с бэка). Backend-side фикс `is_slot_movable_unpublished` (§4.2) автоматически блокирует drag.

### 5.2. PublishedBlock.vue (новый компонент)

`frontend/src/components/content/PublishedBlock.vue`. Принимает `summary: PublishSummary`. Рендерится в `ContentDetail.vue` отдельной секцией; точное место — см. §11.1 (кандидат: между блоком статуса и блоком модерации).

**Поведение:**

- Если `summary.is_published === false` → блок не рендерится (ничего, чтобы не было пустой шумной секции).
- Иначе заголовок «📣 Опубликовано» + три плитки IG/TT/YT в ряду, **всегда все три**.
- Плитка с `accounts === 0` → `opacity-50`, без курсора-pointer, без раскрытия.
- Плитка с `accounts > 0` → `cursor-pointer`, клик переключает раскрытый список юзернеймов под плитками (accordion внутри блока, не popover).
- Склонение: helper `pluralize(n, ['аккаунт','аккаунта','аккаунтов'])` по правилам ru-RU.

**Эскиз:**

```
📣 Опубликовано

┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ 📷 Instagram│  │ 🎵 TikTok   │  │ ▶ YouTube   │
│ ▼ 5 аккаунтов│ │ 2 аккаунта  │  │ —           │
└─────────────┘  └─────────────┘  └─────────────┘
  @user_a
  @user_b
  @user_c
  @user_d
  @user_e
```

**Палитра** (без новой иконочной либы — emoji + Tailwind, как в SlotCard):

| Платформа | bg | text | emoji |
|---|---|---|---|
| Instagram | `bg-pink-50` | `text-pink-700` | 📷 |
| TikTok | `bg-gray-50` | `text-gray-900` | 🎵 |
| YouTube | `bg-red-50` | `text-red-700` | ▶ |

## 6. Edge cases

| Кейс | Поведение |
|---|---|
| `pq.platform IS NULL` или `pq.account_username IS NULL` | Отфильтровывается в `WHERE`. Не должно проходить guard publisher'а, но защита в SQL стоит. |
| Legacy платформы (`vk`/`x`/`facebook`) | Whitelist `lower(platform) IN ('instagram','tiktok','youtube')`. Из autowarm scope (`project_autowarm_scope`). |
| Один аккаунт получил контент через разные схемы (две `pq` строки) | `count(DISTINCT account_username)` сворачивает к 1. Семантика «на скольких аккаунтах» корректна. |
| `failed → retry → done` в одной задаче | Считаем только `done`. Failed-строка не попадает в `is_published`. |
| Re-queue (повторная публикация в новый аккаунт через месяц) | Счётчик растёт. Накопленное распространение контента — by design. |
| Карусели | UNION ALL по `pq.carousel_content_id`. Сейчас 0 done-строк, но контракт готов. |
| Удалённый `validator_content` с висячим `pq` | Нет точки входа — нигде не отображается. Висячий мусор в `pq` — не наша проблема. |
| Cross-project content (контент проекта A опубликован в queue проекта B) | Не фильтруем по project_id. Видим все аккаунты. |
| Контент без `done` в очереди | `is_published=false`, блок не рендерится, бейдж в SlotCard показывает approval-статус. |
| Slot с `content.status='published'` (наследие enum) | Безопасно: `is_published` вычисляется независимо от enum, вытеснит наследие. |

## 7. Performance

Замер на проде с текущими 940 `pq` / 1555 `unic_tasks` строками **без новых индексов**:

- 1 контент через pkey: **~1ms**
- 11 контентов одним запросом (для дашборда): **4.5ms** (`EXPLAIN ANALYZE`)

После добавления индексов §3.3 → ожидаемо <1ms на 30 контентов недели.

Bulk-вариант принципиален: дашборд **не делает N+1** — один SQL на массив `content_ids`.

## 8. План раскатки

Аддитивно, **никаких изменений в autowarm/publisher**:

1. Миграция (3 partial-индекса) — `alembic upgrade head` на проде.
2. Backend:
   - `services/publish_summary_service.py` (новый файл).
   - Патчи `_content_to_dict`, `get_week_slots`, `is_slot_movable_unpublished`.
   - Тесты (см. §9).
3. Frontend:
   - `components/content/PublishedBlock.vue` (новый).
   - Правка `SlotCard.vue` (бейдж).
   - Правка `ContentDetail.vue` (вставка `<PublishedBlock>`).
   - Типы (`is_published`, `published_summary`).
4. Деплой backend → деплой frontend (Vite build + sync на nginx). Проверить hard-reload поведение по `feedback_vite_outage_user_hard_reload`.

**Backout:** убрать `is_published` и `published_summary` из ответа API → фронт деградирует чисто (бейдж старый, блока нет, drag по `is_published` вернётся к старому поведению через `slot.status`). Индексы можно оставить — не мешают.

## 9. Тесты

| Слой | Что проверяем |
|---|---|
| Backend unit (`tests/services/test_publish_summary.py`) | Пустой контент → `is_published=false`. Контент с 2 IG аккаунтами + 1 YT → `instagram.accounts=2, youtube.accounts=1, tiktok.accounts=0`. Carousel-путь работает. Whitelist режет `vk`. Distinct по `account_username` (повтор через 2 схемы → 1). |
| Backend integration (live DB через autouse `engine.dispose` fixture, см. `feedback_validator_test_engine_dispose`) | `GET /api/content/:id` возвращает `published_summary` и `is_published`. `GET /api/schedule?week_start=…` отдаёт `is_published` на нужных слотах. `is_slot_movable_unpublished` → False для опубликованного слота. |
| Frontend (Vue Test Utils) | `PublishedBlock` рендерит 3 плитки, склонение работает (1/2-4/5+), click toggle списка. `SlotCard` переключает бейдж при `is_published=true`. |
| Manual on prod | `https://client.contenthunter.ru/content/1894` (12 done в IG+YT) → блок видно, IG=N, YT=M, TT=0. Дашборд проекта этого контента — слот фиолетовый «опубликовано». |

## 10. Что НЕ входит в этот спек

- **Запись `published_summary` в `validator_content`** (write-coupling с autowarm) — отвергнуто как явный YAGNI: live JOIN <10ms.
- **Бейдж «частично опубликовано» / прогресс-индикатор `done/planned`** — выводим только бинарно. Прогресс смотрят на странице публикаций.
- **Фильтр в дашборде «только неопубликованные слоты»** — не запрашивалось.
- **Lazy-override `content.status='published'`** — отвергнуто, см. §4.3 (коллатеральный ущерб для CSS-веток одобрения).

## 11. Открытые вопросы (на имплементацию)

1. **Точное место `<PublishedBlock>` в `ContentDetail.vue`** — кандидат №1: между блоком статуса (`line 26-35`) и блоком модерации (`line ~270`). Финал решается эмпирически в ходе имплементации, после препревью.
2. **Лейбл бейджа SlotCard** — зафиксирован: `📣 опубликовано`. Если по факту не помещается в узкие слоты — fallback `📣 опубл.` (но решение по фактическому замеру, не сейчас).
3. **Иконка-набор плиток** — emoji 📷/🎵/▶ для MVP; если в проекте уже подключена Lucide или подобная — заменить на платформенные SVG в имплементации, не блокер.
