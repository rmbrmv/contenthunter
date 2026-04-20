<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
# Plan: Техдолг публикаций — guard + инфра (v2, пересобрано после проверки кода)

**Created:** 2026-04-16
**Mode:** Fast
**Branch:** `feature/aif-global-reinstall` (план здесь; фиксы — в `autowarm` и `validator` репо)

## Ревизия v1 → v2 (что изменилось после актуализации)
Первая версия плана предполагала, что 3 главных бага switcher'а (TT own-profile, YT shorts-trap, IG Edits-promo) ещё не закрыты. Проверка показала: закрыты в round 1-4 (commit `5b02c60`, 2026-04-15 14:25 UTC). При этом **54 failed задачи 15-16.04** всё равно падают — ключевая причина *целевой аккаунт не залогинен на устройстве*, switcher физически не может на него переключиться. Fix-план смещается с «переписать switcher» на «fast-fail + инфра-техдолг».

## Settings
- **Testing:** smoke-only (rerun 3 failed задач после T1; наблюдать exit-reason в event log + `pm2 logs`)
- **Logging:** verbose (`log.info` в guard: device/platform/account/source; `log.warning` на missing mapping → first-run allow; `log.error` на negative match → fail-fast)
- **Docs:** warn-only
- **Roadmap Linkage:** none

## Источники
- Память (обновлена этой сессией): `project_publish_switcher_bugs.md`.
- `pm2 logs autowarm --lines 2000 --nostream` + SQL по `publish_tasks`.
- `/tmp/autowarm_ui_dumps/publish_*_fail_*.xml` (свежие: 320 no_camera, 325 editor_timeout, 328 tt_2_not_own_profile, 333 yt_3_fg_failed).

## Приоритизация
| # | Приоритет | Задача | Влияние | Оценка |
|---|-----------|--------|---------|--------|
| T1 | **P0** | ✅ `account_packages` + `publish_tasks.done` mapping guard в `publisher.py` | Убирает ≈80% «пустой прогон → fail через 5 мин» из 54 ежедневных fail | 1-2ч |
| T2 | **P0** | ✅ Upsert mapping при `status='done'` | Guard становится строже без ручного seed | 30 мин |
| T3 | **P0** | ✅ Smoke: 5-кейсовая матрица guard'а (2 реальных + 3 синтетических) | Подтвердить что guard валит fast и не ломает legit публикации | 30 мин |
| T4 | **P1** | ✅ Анализ 3 xml-дампов (328/325/320) → 3 РАЗНЫХ round-5 бага, НЕ mapping-проблемы | Понять, нужен ли round-5 switcher-fix или guard закрывает | 30-45 мин |
| T5 | **P2** | ✅ `validator/backend/src/routers/schemes.py:_download_file` → `asyncio.to_thread` | Техдолг event-loop (background, но накапливается) | 45 мин |
| T6 | **P2** | ✅ openclaw-gateway systemd limits (MemoryMax=1500M, OOMPolicy=kill, TimeoutStopSec=20s) вместо патча vendor supervisor'а | Анти-zombie 89% CPU (случай 2026-04-16) | 1ч (нужно найти репо) |
| T7 | **P2** | ✅ Validator Vite assets: cron `find /var/www/validator/assets -mtime +7 -delete` | 4105 файлов / 72MB cruft после каждого deploy | 20 мин |
=======
# Plan: Публикация контента — round-6 (IG flow + guard block-on-NULL + TT anti-markers)
=======
# Plan: Fix `ig_camera_open_failed` regression (aneco/anecole кластер)
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)
=======
# PLAN — Carousel rendering fix + content-card title `[проект] + [тип]`
>>>>>>> 91d2f733e (docs(plans): carousel rendering fix + content-card title — executed 2026-04-20)

**Тип:** bugfix (frontend+backend) + small UX
**Создан:** 2026-04-20
**Инициатор:** bug-отчёт `@Danil_Pavlov_123` от 2026-04-20 13:08 UTC (`contenthunter_knowledge/sources/bugs/inbox/2026-04-20T130857Z-Danil_Pavlov_123-почему-то-у-меня-не-.md`) + устное добавление по заголовку карточки.
**Код:** `/root/.openclaw/workspace-genri/validator/` (PM2 `validator` + `/var/www/validator`).

## Settings

| | |
|---|---|
| Testing | **no** — UI-правки + маленькая серверная проекция; smoke через curl и ручной клик по `/content/1877`. Если к моменту реализации окажется, что backend-проекция задевает модели — ограничиться 1 pytest-снапшотом. |
| Logging | **verbose** — `log.debug("[content GET] id=%s type=%s images=%s")` в `_content_to_dict`; `console.debug("[ContentDetail] type=%s urls=%s")` при маунте; `[ClientDashboard] slot_title=%s %s" for project+type)` для быстрой диагностики в DevTools. |
| Docs | **no** |
| Roadmap linkage | skipped — реакция на bug-репорт |

## Research Context — что уже знаем

### Баг с каруселью (repro-линк в жалобе: `https://client.contenthunter.ru/content/1877`)

**Симптом:** клиент загружает карусель (несколько изображений), открывает карточку контента → видит шаблон под видео, а не карусель. «Для всех платформ».

**Что найдено в коде:**

<<<<<<< HEAD
<<<<<<< HEAD
### ⚠️ Новая регрессия (не в скоупе, follow-up)
**`ig_camera_open_failed`** — 6 событий за 48h на aneco/anecole кластере (RF8Y80ZT14T, RF8Y90LBX3L, RF8Y90LBZPJ). Падает **до** editor-loop (в `_open_instagram_camera()` publisher.py:2050). RF8Y90LBX3L имел done 2 дня назад — регрессия. Требует отдельного `/aif-fix`.
>>>>>>> 9cf184661 (docs(evidence): round-6 seed (17 devices) + post-deploy analysis)
=======
### Root cause — по XML-дампам из `/tmp/autowarm_ui_dumps/`
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)
=======
- Backend модель уже поддерживает `ValidatorCarouselImage` с `relationship("ValidatorCarouselImage", back_populates="content", cascade="all, delete-orphan")` в `backend/src/models/content.py:82`. Таблица `validator_carousel_images` с `content_id` FK (строки 85-98).
- Upload-поток для карусели (`POST /api/upload/images`) уже работает после фикса 2026-04-20 (`e4deb3c`) — preflight 1080×1920/1080×1080 в UI, backend пишет записи в `validator_carousel_images`.
- **Корень 1 (backend):** `GET /api/content/{content_id}` возвращает `_content_to_dict(c)` в `backend/src/routers/content.py:318-347`, и этот словарь **не содержит `carousel_images`** — только `s3_url` (для video оно указывает на mp4, для carousel — либо NULL, либо на первую картинку, нужно проверить по записи 1877). То есть фронт физически не получает список URL картинок.
- **Корень 2 (frontend):** `frontend/src/pages/client/ContentDetail.vue:347-360` рендерит `<video :src="content.s3_url">` **безусловно**, без ветвления по `content.content_type`. Даже если backend-словарь отдаст картинки — рендериться всё равно будет видео-плеер.
- Для списковых карточек в планировщике (`frontend/src/pages/client/ClientDashboard.vue:134-154`) отображается `contentTypeIcon(slot.content_type)` (🖼️ для carousel) + `slot.content_title || 'Контент'`. Иконку и тип видно, но клиент всё равно переходит по клику на `openContent(slot.content_id)` → попадает в сломанный `ContentDetail.vue`.
>>>>>>> 91d2f733e (docs(plans): carousel rendering fix + content-card title — executed 2026-04-20)

**Что проверить до кода (Task 1):**
- запись `validator_content.id = 1877` — что в ней: `content_type`, `s3_url`, сколько `validator_carousel_images` с `content_id=1877`, их `s3_url`-ы.

<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
### Phase P0 — Fast-fail guard

#### T1. Account→device mapping guard в `run_publish_task`
- **Файл:** `/root/.openclaw/workspace-genri/autowarm/publisher.py` (`run_publish_task`, строки 4513-4559).
- **Точка вставки:** сразу после unpacking `row` (строка 4539), до `DevicePublisher(...)` (4541).
- **Query (один statement, UNION из двух источников):**
  ```sql
  WITH declarative AS (
    SELECT instagram AS acc FROM account_packages
     WHERE device_serial=%(serial)s AND (end_date IS NULL OR end_date>=CURRENT_DATE)
       AND %(platform)s='Instagram' AND instagram IS NOT NULL AND instagram<>''
    UNION ALL
    SELECT tiktok FROM account_packages
     WHERE device_serial=%(serial)s AND (end_date IS NULL OR end_date>=CURRENT_DATE)
       AND %(platform)s='TikTok' AND tiktok IS NOT NULL AND tiktok<>''
    UNION ALL
    SELECT youtube FROM account_packages
     WHERE device_serial=%(serial)s AND (end_date IS NULL OR end_date>=CURRENT_DATE)
       AND %(platform)s='YouTube' AND youtube IS NOT NULL AND youtube<>''
  ),
  history AS (
    SELECT DISTINCT account AS acc FROM publish_tasks
     WHERE device_serial=%(serial)s AND platform=%(platform)s AND status='done'
  ),
  known AS (
    SELECT acc FROM declarative WHERE acc IS NOT NULL AND acc<>''
    UNION SELECT acc FROM history WHERE acc IS NOT NULL AND acc<>''
  )
  SELECT COUNT(*) AS total, BOOL_OR(acc=%(account)s) AS matched,
         string_agg(DISTINCT acc, ', ') AS known_list
    FROM known;
  ```
- **Решающая логика (после fetchone):**
  - `total=0` → `log.warning('[guard] no mapping for <serial>/<platform>: first-run allow')`. Continue.
  - `total>0 AND matched` → `log.info('[guard] <account>@<serial>/<platform> in mapping')`. Continue.
  - `total>0 AND NOT matched` → **fail-fast:** записать event с reason=`account_not_logged_in_on_device`, UPDATE `status='failed'`, return до `DevicePublisher`.
- **Event шаблон:**
  ```json
  {"ts":"HH:MM:SS","type":"error","msg":"[guard] <acc> не в списке известных для <serial>/<platform>",
   "meta":{"reason":"account_not_logged_in_on_device","known":["..."],"source":"account_packages+publish_tasks.done"}}
  ```
- **Важно:** переиспользовать уже открытый `conn`/`cur`; не плодить подключений.
- **Логирование:** `log.info` до query и после (total/matched/known_list).

#### T2. Upsert `account_packages` при успешной публикации
- **Файл:** `publisher.py` — финализация успешного `_publish_*` (после `✅ Публикация успешна`).
- **Механика:** 
  - Столбец по платформе: `Instagram→instagram`, `TikTok→tiktok`, `YouTube→youtube`.
  - Попытаться UPDATE: `UPDATE account_packages SET <col>=%s, updated_at=NOW() WHERE device_serial=%s AND project='auto-from-publish' AND (end_date IS NULL OR end_date>=CURRENT_DATE) AND (<col> IS NULL OR <col>='' OR <col>=%s)`. Если 0 rows — INSERT новой auto-строки с этим полем.
  - Не трогать строки с legit `project` (не `auto-from-publish`) — защита от перезаписи кураторского seed'а.
- **Логирование:** `log.info('[mapping] auto-upsert <acc>@<serial>/<platform>')`.

#### T3. Smoke rerun 3 задач 2026-04-16
- **Задачи:** #328 (TT `pay.abroad.easy`), #333 (YT `pay.anywhere_now`), #325 (IG `pay.anywhere.now`).
- **Rerun:** `UPDATE publish_tasks SET status='pending', events='[]'::jsonb WHERE id IN (328,333,325)` и позволить scheduler'у подхватить или прямой вызов `python3 -m autowarm.publisher <id>` из pm2 cwd.
- **Ожидание:**
  - Если mapping пуст для `RF8YA0V5KWN/<platform>` → warning + обычный fail (5 мин) — это baseline.
  - Если mapping **накопился** от кого-то другого (declarative или history для других устройств) → fast-fail за <10с.
- **Evidence:** `evidence/smoke-mapping-guard-<ts>.md`.

**Commit 1** (после T1+T2+T3): `feat(publisher): account-device mapping guard + auto-upsert on success`

### Phase P1 — Оставшиеся switcher regressions

#### T4. Анализ xml-дампов 328/325/320
- **Файлы:**
  - `/tmp/autowarm_ui_dumps/publish_328_fail_tt_2_not_own_profile_1776316706.xml`
  - `/tmp/autowarm_ui_dumps/publish_325_instagram_editor_timeout_1776315764.xml`
  - `/tmp/autowarm_ui_dumps/publish_320_instagram_no_camera_1776315453.xml`
- **Для каждого:** извлечь видимый `text=` / `content-desc=` верхнего уровня, определить экран (camera/Reels-editor/Edits-promo/…), решить:
  - «Mapping-проблема (target не залогинен)» → guard закроет, код не трогаем.
  - «Реальный switcher regression» → отдельный `/aif-fix` план.
- **Evidence:** `evidence/xml-triage-<ts>.md`.

### Phase P2 — Инфра-техдолг

#### T5. `schemes.py:_download_file` → async
- **Файл:** `validator/backend/src/routers/schemes.py:569-580` + call sites 608/616/636/647.
- **Фикс:** переименовать текущий `_download_file` → `_download_file_sync`; добавить `async def _download_file(...): return await asyncio.to_thread(_download_file_sync, ...)`; `await` во всех 4 call sites.
- **Grep-инвариант после:** `rg -nU "async def[\s\S]*?(req_lib|requests)\.(put|get|post)" backend/src/routers/` пусто.
- **Деплой:** `pm2 restart validator`.

#### T6. openclaw-gateway supervisor kill stale PID
- **Предварительно:** найти репо supervisor'а — `rg -n "lock timeout" /opt/openclaw/ /root/.openclaw/ -g '!node_modules'` или `ps aux | grep supervisor`. Если репо недоступно — оставить как TODO-evidence и остановить.
- **Логика (если доступ есть):** при `gateway already running; lock timeout after 5000ms` → прочитать PID из lockfile → `kill 0` → `SIGTERM` + 3с wait → повторная проверка → `SIGKILL` если жив → снять lockfile → повторить запуск. Лог.
- **Acceptance:** следующий race не оставляет zombie.

#### T7. Validator Vite assets cron cleanup
- **Файл:** `/etc/cron.d/validator-assets-cleanup`:
  ```
  0 4 * * * root find /var/www/validator/assets -type f -mtime +7 -delete 2>&1 | logger -t validator-assets-cleanup
  ```
- **Проверка:** первый прогон в 04:00 UTC → `journalctl -t validator-assets-cleanup --since "-1h"`.
- **Acceptance:** через 7+ дней `find /var/www/validator/assets | wc -l` стабильно <1000.

**Commit 2** (после T5, validator repo): `fix(schemes): async download via asyncio.to_thread (no event-loop block)`
**Commit 3** (после T6, gateway repo): `fix(supervisor): kill stale gateway PID on lock-timeout`
**Commit 4** (T7): cron-файл в infra-регистр.

## Деплой-нюансы
- После правок `publisher.py`: `pm2 restart autowarm` (в памяти процесса, git push не деплоит — memory #10 revision_landmines).
- После правок `schemes.py`: `pm2 restart validator`.

## Ordering
P0 → P1 → P2. P2 независим от P0/P1 (если P0/P1 ждут пользователя — можно брать параллельно).

## Next Steps
Start T1 в autowarm репо, ветка `fix/publisher-mapping-guard`.
=======
- `seed-round-6-20260418.sql` — idempotent SQL seed + rollback
- `seed-round-6-20260418.log` — вывод psql при выполнении
- `round-6-post-deploy-analysis-20260418.md` — полный анализ T7

## Rollback

Seed reverse'ится одной командой:
```sql
DELETE FROM account_packages WHERE project='manual-seed-round-6-20260418';
=======
**Экран A — Highlights empty-state** (4/6: #389, #382, #373, #372)
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)
```
action_bar_title  = "Добавление в актуальное"
text              = "Дополните свою историю"
text              = "Сохраняйте свои истории в архиве после того, как они исчезают…"
resource-id       = com.instagram.android:id/empty_state_view_root
resource-id       = com.instagram.android:id/empty_state_headline_component
resource-id       = com.instagram.android:id/igds_headline_emphasized_headline
```
IG приземлился в архив Highlights (пустой), а не в Reels-камеру. Новый регресс — не покрыт handler'ами round-5/6 (T1/T2/T7 в publisher.py:2020-2100).
=======
### Feature «заголовок карточки = [проект] + [тип]»
>>>>>>> 91d2f733e (docs(plans): carousel rendering fix + content-card title — executed 2026-04-20)

- Сейчас `ClientDashboard.vue:154` → `{{ slot.content_title || 'Контент' }}`. `slot.project_name` и `slot.content_type` уже есть в том же слоте (используются в бейдже «📁 {{ slot.project_name }}» на `:149-152` — **только в режиме `viewMode === 'all'`** — и в `contentTypeIcon` на `:136`).
- Клиент-дефолт (клиентский логин видит только свой проект) = `viewMode === 'my'` → бейдж проекта невидим, клиент видит только иконку типа и `slot.content_title` — т.е. в сегодняшней жалобе «карточка не как карусель» может быть усугублена тем, что по заголовку «Контент» непонятно, что это. Задача: на всех карточках ставить строковый заголовок `<project_name> · <content_type_label>` единообразно (и в client/all-видах).
- `content_title` сохраняем — но НЕ показываем как основной заголовок; он остаётся для `title` атрибута (hover) или второй строки (решим при реализации — скорее всего вторая строка, т.к. клиенты часто вручную вводили title).

## Tasks

### Task 1 — [x] зафиксировать состояние записи 1877 и DB-шему
**File:** SQL-запросы прямо в psql (`openclaw:openclaw123@localhost:5432`), результат — в `/home/claude-user/contenthunter/evidence/carousel-bug-1877-2026-04-20.md` (новый).
**Шаги:**
1. `SELECT id, content_type, s3_url, s3_key, title, status, project_id, created_at FROM validator_content WHERE id=1877;`
2. `SELECT id, content_id, s3_url, s3_key, order_index, width, height FROM validator_carousel_images WHERE content_id=1877 ORDER BY order_index;`
3. `\d validator_carousel_images` — зафиксировать точные имена колонок (order_index vs position; есть ли width/height).
4. Записать: что реально лежит у 1877, какие пути S3, видны ли картинки публично (`curl -I <s3_url>` → 200).
**Деливери:** evidence-файл с выдержкой + одним скриншотом ответа сервера на `GET /api/content/1877` под jwt клиента (`client_el_kosmetik_content_hunter`).
**Логирование:** n/a.

### Task 2 — [x] backend: включить `carousel_images` в ответ `GET /content/{id}` и список `GET /content`
**Files:**
- `/root/.openclaw/workspace-genri/validator/backend/src/routers/content.py` — `get_content` (стр. 85-116), `list_content` (вызывает `_content_to_dict` в цикле), `_content_to_dict` (стр. 318-347).
- `/root/.openclaw/workspace-genri/validator/backend/src/models/content.py` — проверить точные имена колонок `ValidatorCarouselImage` (order_index, s3_url, width, height).

**Деливери:**
- В `get_content` добавить eager-load: `select(ValidatorContent).options(selectinload(ValidatorContent.carousel_images)).where(...)`. Импорт `from sqlalchemy.orm import selectinload`.
- В `_content_to_dict` добавить ключ:
  ```python
  "carousel_images": [
      {"s3_url": img.s3_url, "order_index": img.order_index, "width": img.width, "height": img.height}
      for img in sorted(c.carousel_images or [], key=lambda x: x.order_index)
  ] if c.content_type and c.content_type.value == "carousel" else [],
  ```
  (сортировка — чтобы порядок был стабильный; имена полей подтвердить после Task 1).
- В `list_content` — тоже `selectinload(carousel_images)`, чтобы списковый эндпоинт тоже был честным (на случай если где-то нужен preview).
- `log.debug("[content GET] id=%s type=%s images=%s title=%r", c.id, c.content_type.value if c.content_type else None, len(c.carousel_images or []), c.title)` перед `return` в `_content_to_dict`.

**Acceptance:** `curl -s -H "Authorization: Bearer <jwt>" http://localhost:8000/api/content/1877 | jq '.content_type, (.carousel_images|length)'` → `"carousel"` + ненулевое число.

### Task 3 — [x] frontend: `ContentDetail.vue` — рендер карусели по `content_type`
**File:** `/root/.openclaw/workspace-genri/validator/frontend/src/pages/client/ContentDetail.vue`.

**Изменения в правой колонке (шаблон, стр. 317-365):**
- Обернуть текущий `<video>` в `<template v-if="content.content_type === 'video'">`.
- Для `content.content_type === 'carousel'`: рендерить слайдер:
  - Контейнер тех же размеров (`height: 65vh`, `width: calc(65vh * 9/16)` для 9:16 и `calc(65vh)` для 1:1 — определяем по `width === height` первой картинки).
  - Активная картинка `<img :src="activeImage.s3_url" class="w-full h-full object-contain" style="background:#000" />`.
  - Миниатюры под блоком: `<button v-for="(img, i) in content.carousel_images" @click="activeIndex = i" :class="{ 'ring-2 ring-indigo-500': i === activeIndex }"><img :src="img.s3_url" class="h-14 w-14 object-cover rounded" /></button>`.
  - Стрелки «◀ ▶» для навигации по клавишам/кликам.
  - Счётчик `{{ activeIndex + 1 }} / {{ content.carousel_images.length }}`.
- Для `content.content_type === 'post'`: fallback-заглушка «Текстовый пост» (без визуала) — чтобы тоже не падало на `<video>`.
- «⬇️ Скачать видео» (стр. 361-364) переименовать в `⬇️ Скачать {{ contentTypeLabel }}` и подменить `href`: для карусели — на текущую активную картинку.

**Изменения в левой колонке:**
- «🔄 Заменить видео» (стр. 100-112): `accept="video/mp4,..."` → для карусели скрыть кнопку (или показать «Замена недоступна для карусели») — не расширяем скоуп, замена для carousel — отдельная история.
- «Метаданные файла» (стр. 201-211): `duration_seconds` скрыть для carousel; вместо этого строка «Картинок: {{ count }}».
- «Файл» (стр. 97-115): `content.original_filename` для карусели скорее всего NULL → показать «Карусель из N картинок».
- «Технические требования» (стр. 213-222): для carousel — другой набор (размер ≤ 30 МБ/картинка, формат JPG/PNG, разрешение 1080×1920 или 1080×1080). Добавить computed `techRequirements(content_type)` вместо хардкода.

**Script:**
- `const activeIndex = ref(0)` + `const activeImage = computed(() => content.value?.carousel_images?.[activeIndex.value])`.
- `const contentTypeLabel = computed(() => { const m = {video: 'видео', carousel: 'карусель', post: 'пост'}; return m[content.value?.content_type] ?? 'контент' })`.
- `onMounted`: если `content_type === 'carousel'` и `carousel_images?.length === 0` — `console.warn("[ContentDetail] carousel without images", content.value.id)` + показать в UI предупреждение «Картинки не найдены».

**Логирование:**
- `console.debug("[ContentDetail] mounted", { id, content_type, images: content.carousel_images?.length, title })` в `onMounted` сразу после `content.value = res.data`.

**Acceptance:** открыть `https://client.contenthunter.ru/content/1877` под клиентом Эль-косметик → видна карусель с навигацией, миниатюрами, счётчиком.

### Task 4 — [x] card title: `[проект] + [тип]` в слотах планировщика
**File:** `/root/.openclaw/workspace-genri/validator/frontend/src/pages/client/ClientDashboard.vue` (основное место) + проверить другие места где виден `slot.content_title` (grep по repo).

**Деливери в `ClientDashboard.vue:122-164`:**
- Убрать ветку `v-if="viewMode === 'all'"` у бейджа проекта (:149) — показывать его **всегда**, если `slot.project_name` не пустой. В client-режиме проект один → бейдж будет всегда с одним названием; это ок, клиент лишний раз видит «в каком проекте я» — не вредит.
- Заменить основной текст:
  ```html
  <div class="text-xs font-medium text-gray-900 truncate">
    {{ (slot.project_name || 'Проект') }} · {{ contentTypeLabel(slot.content_type) }}
  </div>
  <div v-if="slot.content_title" class="text-[11px] text-gray-500 truncate" :title="slot.content_title">
    {{ slot.content_title }}
  </div>
  ```
- `contentTypeLabel` уже есть в файле (стр. 434-439) — переиспользовать.
- То же самое внести в `TransferTray.vue` / `SlotCard.vue` / `WeeklyGrid.vue`, если там рисуется отдельный компонент карточки слота. Grep `slot.content_title` по `frontend/src` — пройти по всем хитам и привести к единой форме «проект · тип / [title мелким]».

**Бэк-требование:** в `GET /api/schedule/slots` (или что даёт `slot`-массив дашборда) уже есть `project_name` и `content_type` (видно из существующего шаблона). Проверить, что endpoint действительно их отдаёт — если в `viewMode='my'` их не возвращает, добавить. Быстрый grep: `grep -rn "content_type\|project_name" backend/src/routers/schedule.py`.

**Логирование:**
- `console.debug("[ClientDashboard] cards", slots.value.slice(0,3).map(s => ({ project: s.project_name, type: s.content_type, title: s.content_title })))` после загрузки слотов — разово, чтобы по DevTools увидеть, что прилетает с бэка.

**Acceptance:** клиент Эль-косметик видит в каждой ячейке планировщика строку вида «Эль-косметик · Карусель» (или «Эль-косметик · Видео»), а `slot.content_title` — второй строкой мелким серым.

### Task 5 — [x] сборка + деплой фронта + рестарт бэка
**Команды (все в `/root/.openclaw/workspace-genri/validator`):**
1. Бэк: `sudo -n pm2 restart validator` (после Task 2). Дождаться `Application startup complete`.
2. Smoke бэка:
   ```
   curl -s -X POST http://localhost:8000/api/auth/login -d '{"login":"client_el_kosmetik_content_hunter","password":"<...>"}' -H 'Content-Type: application/json'
   curl -s -H "Authorization: Bearer <jwt>" http://localhost:8000/api/content/1877 | jq '.content_type, .carousel_images | length'
   ```
3. Фронт: `cd frontend && npm run build` (postbuild уже копирует `dist/*` в `/var/www/validator/`).
4. Если postbuild не скопировал или прав не хватило: `sudo -n cp -r dist/* /var/www/validator/`.
5. Live-проверка: `https://client.contenthunter.ru/content/1877` под клиентом.

**Логирование:** `tail -f /root/.pm2/logs/validator-out.log` на время smoke — убедиться что есть `[content GET] id=1877 type=carousel images=N`.

### Task 6 — [ ] закрыть bug-тикет + обновить memory
**Шаги:**
1. Переместить `sources/bugs/inbox/2026-04-20T130857Z-Danil_Pavlov_123-почему-то-у-меня-не-.md` в `sources/bugs/resolved/` с добавкой секции `## Resolution` (git-sha коммита + скриншот «до/после»).
2. Memory update: `project_publish_followups.md` не трогаем (это про autowarm publishing, не про UI карусели). Новая memory `feedback_validator_ui.md` — короткая запись «UI всегда рендерит по `content_type`; при добавлении нового типа — обновить `ContentDetail.vue` + `contentTypeLabel` + preview в `ClientDashboard`».

## Dependencies

- **Task 1** — первый, независим. Без evidence идти дальше рискованно (возможно у 1877 carousel_images = 0 и надо сначала понять, почему).
- **Task 2** — после Task 1 (подтверждаем точные поля FK). Независим от Task 3/4.
- **Task 3** — после Task 2 (фронт использует новое поле `carousel_images`).
- **Task 4** — независим от Task 2/3; можно делать параллельно с Task 3 (обе — фронт, в разных файлах).
- **Task 5** — после Task 2/3/4 (общий билд + restart).
- **Task 6** — после Task 5.

## Commit Plan

**Checkpoint 1 — backend projection:**
```
fix(validator): expose carousel_images in GET /content/{id}

- _content_to_dict возвращает массив {s3_url, order_index, width, height} для content_type=carousel
- selectinload на relationship чтобы не было N+1
- debug-лог "[content GET] id=... type=... images=..."
```
Tasks: 2. Деплой: `sudo -n pm2 restart validator`.

**Checkpoint 2 — frontend carousel render + card title:**
```
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> 9cf184661 (docs(evidence): round-6 seed (17 devices) + post-deploy analysis)
=======
=======
fix(validator): carousel preview вместо видео-плеера в ContentDetail; card title = [проект] · [тип]
>>>>>>> 91d2f733e (docs(plans): carousel rendering fix + content-card title — executed 2026-04-20)

- ContentDetail.vue: ветвление <video|slider|post-stub> по content_type
- слайдер с миниатюрами/стрелками/счётчиком для carousel
- метаданные/тех.требования по типу контента
- ClientDashboard.vue: заголовок карточки = {project} · {type}, content_title во второй строке
- console.debug для диагностики
```
Tasks: 3, 4. Деплой: `npm run build` → `/var/www/validator/`.

**Out-of-commit:** Task 1 (evidence в `contenthunter`), Task 6 (knowledge-repo git push — отдельный репозиторий).

## Acceptance (после деплоя)

1. `https://client.contenthunter.ru/content/1877` под клиентом Эль-косметик → слайдер картинок (не видео-плеер), видны миниатюры, стрелки работают.
2. Планировщик (dashboard) → в каждой filled-карточке слота заголовок вида «Эль-косметик · Карусель» / «Эль-косметик · Видео», content_title — серым мельче.
3. `curl /api/content/1877` возвращает `carousel_images: [...]` с непустым массивом.
4. В логах есть `[content GET] id=1877 type=carousel images=N`.
5. Bug-тикет в knowledge-repo перемещён в `resolved/` с SHA коммита.

## Follow-up (вне этого плана, но зафиксировать)

<<<<<<< HEAD
## Next step

После review этого плана — `/aif-implement` запустит задачи T1–T7 последовательно.
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)
=======
- Пока **не делаем:** replace-файл для карусели (кнопка «🔄 Заменить» скрыта для carousel).
- Пока **не делаем:** preview карусели в списочных карточках слотов (сейчас только иконка 🖼️ + заголовок — достаточно).
- Если выяснится, что `content_type = 'post'` где-то в продакшене — сделать отдельный шаблон (сейчас — fallback-заглушка).
>>>>>>> 91d2f733e (docs(plans): carousel rendering fix + content-card title — executed 2026-04-20)
