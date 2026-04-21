<<<<<<< HEAD
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
=======
# PLAN — Бэклог 2026-04-21: открытые задачи (umbrella)
>>>>>>> 3dccb2b0e (docs(plans): бэклог 2026-04-21 + T1 drag + T2 key ротация)

**Тип:** mixed (UI-fix + prod-hotfix + infra deploy + git housekeeping + passive review)
**Создан:** 2026-04-21
**Режим:** Fast — overwrite предыдущего PLAN.md (carousel rendering, все T1-T6 ✅ за 2026-04-20)
**Основа:** аудит `.ai-factory/plans/*.md` + memory `project_carousel_drag_wip`, `project_validator_anthropic_key`, `project_publish_followups` + git log по `contenthunter` / `validator` / `autowarm`

## Settings

| | |
|---|---|
| Testing | **по задаче** — T1 (drag): ручной smoke в браузере (UI-only); T3 (LLM T10): uses существующие pytest от T1-T8 как regression-guard; остальные — нет нового кода → no tests |
| Logging | **verbose** для T1 (drag) — console.debug на onDragStart/End/Update + state-snapshot; **standard** для остальных (SQL/bash логи в evidence) |
| Docs | **warn-only** — многодоменный план; полноценный docs-checkpoint сделаем только если T1 всплывёт новая UI-концепция |
| Roadmap linkage | skipped — `paths.roadmap` отсутствует |
| Language | ru (per config.yaml) |

## Открытый бэклог — фактические остатки на 2026-04-21

| # | Заголовок | Статус | Репо | Срочность |
|---|---|---|---|---|
| T1 | Carousel storyboard drag-n-drop (реордер) | ✅ 2026-04-21 (root cause: `chosen-class` с пробелом падал в SortableJS `classList.add`) | validator | **P1** — обещано клиенту на 2026-04-21 |
| T2 | Ротация validator `ANTHROPIC_API_KEY` (OAuth истёк) | ✅ 2026-04-21 (OAuth, expires 14:09 UTC) | validator | **P1** — `/upload/generate-description` сломан для клиентов |
| T3 | LLM-recovery T10 — enable pilot (autowarm) | ⚠️ blocked on API key (OAuth vs service) | autowarm | P2 — ждёт T2 (тот же класс ключа) |
| T4 | `feature/aif-global-reinstall` → main: push на origin | ⚠️ unrelated histories | contenthunter | P3 — housekeeping, по согласию force-with-lease |
| T5 | LLM-recovery T11 — pilot week-1 review | ⏳ pending (≈2026-04-27 при T3-approve) | contenthunter | passive wait |

**Закрыто за прошлые сессии и не входит в этот план:**
- Carousel rendering (ContentDetail.vue + ClientDashboard.vue) — ✅ commit `674818a`, `e93082e`.
- IG T7 24h verification, TT 48h, ADB T15 post-deploy — ✅ `1ba8d16f4`.
- `publish_failed_generic` catch-all триаж — ✅ `f2b98d5b6` (обнаружен пропущенный category → в T2 backfill).
- Guard-status backfill (20 TT + 18 YT) + TT/YT tests — ✅ `f355d03ea` + autowarm `5fbffc1`.
- LLM-recovery T1-T9 (DB+service+tests+SQL) — ✅ autowarm `92e4a8a`..`2fe9a33`.
- Residual task 444 (IG streak-counter escalation) — ✅ autowarm `ig-publishing-resolution.md` T1.
- ADB chunked-push — ✅ autowarm `5b9830d`, `73938df`.

**Out of scope:**
- ADB fundamental packet loss TimeWeb hop4 — user-owned трек (тикет в TimeWeb).
- VK/FB/X платформы (per memory `project_autowarm_scope`).
- Новые продуктовые фичи.

<<<<<<< HEAD
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
=======
## Граф зависимостей

```
T1 (drag)          — параллельно, начать сразу с DevTools-логов
T2 (validator key) — параллельно, quick smoke (запрос к Anthropic → замена → pm2 restart)
T3 (LLM T10)       — блокируется T2 (если используем тот же Console key)
T4 (aif merge)     — ортогонально, требует явного approve перед push
T5 (LLM review)    — блокируется T3 + 7d wait
```
>>>>>>> 3dccb2b0e (docs(plans): бэклог 2026-04-21 + T1 drag + T2 key ротация)

## Tasks

---

### T1 — Carousel storyboard drag-n-drop: диагностика + фикс

**Цель:** заставить реордер миниатюр на `https://client.contenthunter.ru/content/<id>` работать — drag визуально захватывает, но порядок не меняется, PATCH не улетает.

**Файлы:**
- `/root/.openclaw/workspace-genri/validator/frontend/src/components/validation/CarouselStoryboard.vue`
- `/root/.openclaw/workspace-genri/validator/frontend/src/pages/client/ContentDetail.vue`
- `/root/.openclaw/workspace-genri/validator/backend/src/routers/content.py` (endpoint уже работает, round-trip через curl прошёл — не трогаем).

**Уже пробовали (по memory, все попытки в `@main`):**
1. Убрать `handle=".drag-handle"` (был на item'е, не на дескенденте).
2. Вернуть handle + вынести на отдельный `<div>` сверху.
3. `isDragging` flag + `@start/@end` + `setTimeout(50)` для ignore click-after-drop.
4. `v-model="internalFiles"` вместо `:list="internalFiles"`.

**План:**

**Шаг 1 (диагностика, БЕЗ кода):** открыть `/content/1877` в DevTools → Console → попробовать drag.
- Если в консоли появляются `[CarouselStoryboard] drag start` / `drag end` — SortableJS работает, проблема в watch/reactivity (переходим к Шагу 2).
- Если **НЕ появляются** `drag start` — SortableJS не зарегистрировал listeners (Шаг 3).

**Шаг 2 (watch props.files сбрасывает порядок):**
- Закомментировать `watch(() => props.files, ...)` в `CarouselStoryboard.vue`.
- Сделать инициализацию `internalFiles` только через `onMounted` (разово).
- Ручной smoke: реордер → PATCH → после refresh порядок сохраняется.
- Если работает — оставить; если отваливается на refresh — ввести `watch` с явным guard `if (!isDragging.value) internalFiles.value = [...newFiles]`.

**Шаг 3 (если Шаг 1 не даёт drag-событий вообще):**
- Проверить `package.json` validator/frontend: `vuedraggable@^4.1.0` + peer `sortablejs`. Если `sortablejs` не в deps — `npm i sortablejs` → `npm run build` → re-test.
- Если peer OK — отказаться от `vuedraggable` в `CarouselStoryboard` и переписать на нативный HTML5 `@dragstart/@dragover/@drop` по образцу `SlotCard.vue` (там drag между слотами работает без vuedraggable).

**Логирование (verbose):**
- `console.debug("[CarouselStoryboard] drag start", { index, file })` в `@start`.
- `console.debug("[CarouselStoryboard] drag end", { oldIndex, newIndex, newOrder: internalFiles.value.map(f => f.name) })` в `@end`.
- `console.debug("[CarouselStoryboard] watch props.files fired", { len, internalLen })` в watch-коллбеке (если оставим watch).

**Acceptance:**
1. Клиент делает drag миниатюры из позиции 2 в позицию 4 → она визуально становится на 4-й → PATCH `/api/content/:id/images/order` с новым `order_index` уходит → 200 OK.
2. Refresh страницы — порядок сохраняется.
3. Smoke на одном из реальных content_id с ≥3 картинками (напр. 1877).

**Деплой:**
- `cd validator/frontend && npm run build` (postbuild копирует в `/var/www/validator/`).
- Без pm2 restart — это pure frontend.
- User-side verification: клиент Danil повторяет drag в DevTools.

**Коммит (validator repo):**
```
fix(validator): carousel storyboard drag — <гипотеза-фикс>

- <что именно поправили по итогам DevTools-лога>
- console.debug на старт/конец drag для быстрой диагностики
```

**Риски:**
- Если после Шага 3 всё ещё нет drag-событий — проблема может быть в Vue 3 reactivity с `<draggable>` + computed source. Fallback: переписать компонент с нуля на HTML5 drag — затратно по времени, поэтому только если 2 часа на Шаги 1-2 не дают результата.

**Оценка:** 30 мин диагностика + 30-60 мин фикс, если гипотеза «watch сбрасывает порядок» верна.

---

### T2 — Ротация Anthropic API key в validator/.env

**Цель:** восстановить `/upload/generate-description` для клиентов (истёк OAuth токен 2026-04-20 14:50 UTC → сегодня `/upload/generate-description` снова отдаёт 502).

**Файлы:**
- `/root/.openclaw/workspace-genri/validator/backend/.env` — единственная строка `ANTHROPIC_API_KEY=sk-ant-oat01-...` (OAuth из прошлой Claude Code session).
- Бэкап предыдущего протухшего ключа: `.env.bak-2026-04-20` (оставить).

**План:**

**Шаг 1 — verify live 502:**
```bash
cd /root/.openclaw/workspace-genri/validator/backend
KEY=$(grep ^ANTHROPIC .env | cut -d= -f2)
curl -s -X POST https://api.anthropic.com/v1/messages \
  -H "x-api-key: $KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5","max_tokens":10,"messages":[{"role":"user","content":"ping"}]}' \
  | jq '.error.type // .content[0].text'
```
Ожидание: `"authentication_error"` (если OAuth истёк) или `"invalid x-api-key"`.

**Шаг 2 — получить постоянный Console key:**
- User-side: зайти на https://console.anthropic.com/settings/keys → создать новый key `sk-ant-api03-...` (не OAuth) с именем `validator-contenthunter-prod`.
- **Запросить у пользователя:** ввести ключ в сессии (через dictation/paste) — я НЕ генерирую и НЕ запрашиваю ключи автономно.

**Шаг 3 — подстановка:**
```bash
cd /root/.openclaw/workspace-genri/validator/backend
cp .env .env.bak-2026-04-21-expired-oauth
sed -i 's|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=<NEW_KEY>|' .env
# verify:
grep ^ANTHROPIC .env | cut -c1-25
```

**Шаг 4 — restart + smoke:**
```bash
sudo -n pm2 restart validator --update-env
sleep 3
# Smoke через прод endpoint:
curl -s -X POST http://localhost:8000/api/upload/generate-description \
  -H "Authorization: Bearer <test_jwt>" \
  -F "image=@/tmp/sample.jpg" | jq '.description // .detail'
```
Должно вернуть реальный текст (либо валидный 4xx если файла нет — но НЕ 502).

**Логирование:** отдельного нет — стандартный `pm2 logs validator` достаточно (`log.info` на каждый generate-description call в `upload.py:238-253`).

**Acceptance:**
1. `curl https://api.anthropic.com/v1/messages` с новым key → 200 OK (не `authentication_error`).
2. `/api/upload/generate-description` возвращает описание или валидный 4xx — НЕ 502.
3. Memory `project_validator_anthropic_key.md` обновить: new expiry дата (permanent keys не истекают, но memo про rotation-workflow).

**Коммит:** нет (`.env` в `.gitignore`). Только memory update в `contenthunter`.

**Риски:**
- Если пользователь не готов создать key прямо сейчас — откладываем T2 и ставим второй OAuth из текущей Claude Code session (но это опять временное решение на 4h; прямо сказать пользователю: «нужен permanent Console key, иначе через 4h снова ломаемся»).
- Если `pm2 restart --update-env` не перечитывает `.env` (некоторые версии pm2 бывают с багом) — использовать `pm2 stop validator && pm2 start validator`.

**Оценка:** 5 мин curl-verify + ожидание ключа от пользователя + 5 мин подстановки и restart.

---

### T3 — LLM-recovery T10: enable pilot (ONE device) после Т2

**Цель:** снять блокер из `feat-screen-recovery-llm-ig-mvp-20260420.md` T10 — раньше deploy падал на `autowarm/.env` `ANTHROPIC_API_KEY=sk-ant-oat...` (OAuth, не работает для API).

**Блокируется:** T2 (получили permanent Console key). **Важно:** `autowarm/.env` и `validator/backend/.env` — разные файлы; нужен один и тот же Console key либо два отдельных.

**Вопрос к пользователю перед T3:** достаточно ли одного key на все сервисы, или нужен раздельный? Recommend: один key `sk-ant-api03-contenthunter-prod` на оба (проще rotate, общий budget).

**План:**

**Шаг 1 — подстановка в autowarm:**
```bash
cd /root/.openclaw/workspace-genri/autowarm
cp .env .env.bak-2026-04-21
# Если файл .env уже существует и там OAuth:
grep ^ANTHROPIC .env
# Подставить NEW_KEY (тот же или новый):
sed -i 's|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=<NEW_KEY>|' .env
```

**Шаг 2 — verify import + connection:**
```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "
from dotenv import load_dotenv; load_dotenv()
import os
from screen_recovery import ScreenRecoveryLLM
r = ScreenRecoveryLLM()
print('enabled:', r.enabled)
# Test actual API connectivity:
import anthropic
c = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
m = c.messages.create(model='claude-sonnet-4-6', max_tokens=10, messages=[{'role':'user','content':'ping'}])
print('api ok, tokens:', m.usage.input_tokens + m.usage.output_tokens)
"
```
Должно напечатать `enabled: False` (флаг по умолчанию OFF) + `api ok`.

**Шаг 3 — pm2 restart:**
```bash
sudo -n pm2 restart autowarm --update-env
sleep 3
pm2 logs autowarm --lines 30 --nostream | grep -iE 'import|error|traceback' | head -20
```
Ожидание: 0 новых import-errors / traceback.

**Шаг 4 — pilot activation (требует approve пользователя):**
- Выбрать pilot device: предложение `RF8YA0V7LEH` (активное IG-устройство из `tt_audit`).
- **ПЕРЕД включением флага** — подтверждение у пользователя: «Включить LLM recovery глобально на всех IG задачах? Budget $5/day, instant rollback одним SQL».
- После approve:
  ```sql
  PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
    -c "UPDATE autowarm_settings SET value='true' WHERE key='screen_recovery_llm_enabled';"
  ```

**Шаг 5 — live observe (1-2h):**
```bash
watch -n 60 'PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
  -f /root/.openclaw/workspace-genri/autowarm/scripts/llm_recovery_48h.sql | head -40'
```
Ждём первого `llm_recovery_attempt` event в `publish_tasks.events`.

**Rollback (при любом red flag):**
```sql
UPDATE autowarm_settings SET value='false' WHERE key='screen_recovery_llm_enabled';
```
Эффект мгновенный (следующий task не идёт в LLM).

**Acceptance:**
1. `python3 -c "from screen_recovery import ...; ..."` — 0 exceptions, `enabled: True` после Шага 4.
2. 0 новых `Traceback` в `pm2 logs autowarm` в течение 30 мин после restart.
3. Первый `llm_recovery_result` event в `publish_tasks.events` (в пределах 1-2h IG активности, либо 0 если не было задач с attempt==3).
4. `autowarm_llm_spend.spend_date=CURRENT_DATE` — либо пусто, либо несколько rows с `cost_usd < $0.05` каждый.

**Коммит:** нет (только SQL UPDATE + env). Evidence — в `contenthunter/.ai-factory/evidence/llm-recovery-deploy-20260421.md`.

**Оценка:** 15 мин подстановка + restart + smoke + monitoring первого часа.

**Блокируется:** T2.

---

### T4 — `feature/aif-global-reinstall` → main: разобрать push на origin

**Цель:** закрыть долг по `aif-global-reinstall.md` (все T1-T7 ✅), локальный merge готов, но push на origin был заблокирован «unrelated histories». Пользователь approve'нул force-with-lease.

**Файлы:** только git metadata в `/home/claude-user/contenthunter/.git/`.

**План:**

**Шаг 1 — расследование причины:**
```bash
cd /home/claude-user/contenthunter
git fetch origin
git log --oneline origin/main..HEAD | head -20
git log --oneline HEAD..origin/main | head -20
# Если origin/main ушёл вперёд — merge blocked = divergence, не unrelated.
# Если действительно unrelated (никакого LCA):
git merge-base origin/main HEAD && echo "has common base" || echo "NO common base — unrelated"
```
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> 9cf184661 (docs(evidence): round-6 seed (17 devices) + post-deploy analysis)
=======
=======
fix(validator): carousel preview вместо видео-плеера в ContentDetail; card title = [проект] · [тип]
>>>>>>> 91d2f733e (docs(plans): carousel rendering fix + content-card title — executed 2026-04-20)
=======
>>>>>>> 3dccb2b0e (docs(plans): бэклог 2026-04-21 + T1 drag + T2 key ротация)

**Шаг 2 — выбор стратегии** по результату Шага 1:

**Вариант A (есть common base, но divergence):**
```bash
git checkout feature/aif-global-reinstall
git rebase origin/main
# resolve conflicts if any (показать user-у `git status` + конфликтные файлы)
git checkout main
git merge --ff-only feature/aif-global-reinstall
git push origin main
git branch -d feature/aif-global-reinstall
git push origin --delete feature/aif-global-reinstall 2>/dev/null || true
```

**Вариант B (реально unrelated histories — `git push --force-with-lease`):**
- **ОБЯЗАТЕЛЬНЫЙ финальный approve пользователя** перед force-push на main.
- Показать `git log --graph --oneline --all | head -30` для наглядности.
```bash
git checkout main
git reset --hard feature/aif-global-reinstall  # локально перестраиваем main на ветку
git push --force-with-lease origin main        # force-with-lease страхует от race
```

**Вариант C (sync auto-update branch «мусорит» историю — уже видно в `git log`):**
- Если на origin/main сейчас 100+ sync-commits (`sync: auto-update ...`), возможно имеет смысл: squash локальную ветку в один commit → cherry-pick поверх origin/main → push обычным не-force способом.
- Это безопаснее force-with-lease, но сложнее; оставить fallback если A/B оба неприменимы.

**Шаг 3 — verify:**
```bash
git status
git log --oneline -5
ls .claude/skills/ | grep aif | wc -l   # should be 23
```

**Логирование:** стандартный git output. Evidence в evidence/aif-reinstall-merge-20260421.md (краткий: какая стратегия выбрана + SHA final commit).

<<<<<<< HEAD
<<<<<<< HEAD
## Next step

После review этого плана — `/aif-implement` запустит задачи T1–T7 последовательно.
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)
=======
- Пока **не делаем:** replace-файл для карусели (кнопка «🔄 Заменить» скрыта для carousel).
- Пока **не делаем:** preview карусели в списочных карточках слотов (сейчас только иконка 🖼️ + заголовок — достаточно).
- Если выяснится, что `content_type = 'post'` где-то в продакшене — сделать отдельный шаблон (сейчас — fallback-заглушка).
>>>>>>> 91d2f733e (docs(plans): carousel rendering fix + content-card title — executed 2026-04-20)
=======
**Acceptance:**
1. `git log --oneline origin/main | head -3` — последний commit = наш aif-reinstall (squash или FF).
2. `feature/aif-global-reinstall` удалена локально и на origin.
3. Память не меняется (план `aif-global-reinstall.md` уже ✅).

**Риски:**
- **Force-push на main** — destructive. Перед Шагом 2B обязательный явный approve + показать пользователю `git log origin/main..HEAD` (что мы принципиально добавляем) и `git log HEAD..origin/main` (что потеряем, если там что-то есть).
- Если 100+ sync-commits на origin/main и ветка их НЕ содержит — force-with-lease их снесёт. Это потенциально недопустимо → используем Вариант C (cherry-pick) в этом случае.

**Оценка:** 10 мин исследование + 5 мин merge + 5 мин verify (при благоприятном сценарии).

---

### T5 — LLM-recovery T11: pilot week-1 review (passive)

**Цель:** через 7 дней после включения флага T3 (ориентировочно 2026-04-28) прогнать `scripts/llm_recovery_48h.sql` на 7-дневном окне и принять решение continue / expand / rollback.

**Блокируется:** T3 (должен быть enabled ≥7 дней для осмысленного sample).

**Что проверить (из `feat-screen-recovery-llm-ig-mvp-20260420.md` T11):**
- `calls_total`, `total_cost_usd` — в пределах ли $5/day budget'а.
- `llm_success_rate_pct` — target ≥30%.
- Сравнение `ig_camera_open_failed` / day до и после включения.
- Red flags: `exception_count > tap_count`, `timeout_count > 30%`, `cost_usd > $5/day`.

**Deliverable:** `contenthunter/.ai-factory/evidence/llm-recovery-pilot-week1-20260428.md`.

**Действия:** нет — passive wait. Задача существует только чтобы не забыть. Можно поставить `ScheduleWakeup` или cron в будущей сессии (не в скоупе T5 сейчас).

**Оценка:** 30 мин evidence через 7 дней.

---

## Commit plan

Большая часть плана — 0 новых коммитов в contenthunter (правки кода в validator/autowarm).

### Commit 1 — validator repo (после T1)
```
fix(validator): carousel storyboard drag reorder working

- <root cause based on DevTools findings>
- console.debug на drag start/end для diagnosis
```

### Commit 2 — contenthunter (после T2 + T3)
```
docs(memory+evidence): ротация Anthropic key + LLM-recovery T10 pilot enabled

- memory/project_validator_anthropic_key.md: permanent Console key, rotation workflow
- evidence/llm-recovery-deploy-20260421.md: T10 deployment notes + first hour observation
```

### Commit 3 — contenthunter (после T4)
```
chore: merge feature/aif-global-reinstall into main

<details of chosen strategy (rebase/force-with-lease/cherry-pick)>
```

### Commit 4 — contenthunter (после T5, ~2026-04-28)
```
docs(evidence): LLM-recovery pilot week-1 review + decision

- continue / expand / rollback verdict
```

## Риски и контрмеры

| # | Риск | Мит. |
|---|---|---|
| R1 | T1 drag — 5-я попытка тоже не помогает | Fallback: HTML5 native drag как в SlotCard.vue. Не уходить в 6-ю гипотезу без DevTools-логов. |
| R2 | T2 — пользователь не готов создать permanent key сейчас | Честно сказать: временный OAuth даст 4h окно → 502 вернётся. Prefer wait до ключа. |
| R3 | T3 — после flag ON cost-спайк или exceptions | Instant rollback через SQL UPDATE. Budget-guard в коде уже страхует на $5/day. |
| R4 | T4 — force-with-lease снесёт sync-commits на origin/main | Перед force всегда показать `git log HEAD..origin/main` пользователю. Если там что-то важное — Вариант C (cherry-pick). |
| R5 | Параллелизм T1+T2 — конфликт CWD/контекста | T1 работает в browser (клиент), T2 — локальные .env + curl. Реально параллельны. |

## Что намеренно НЕ делаем

- **НЕ** создаём ветку в `contenthunter` — план живёт на `feature/aif-global-reinstall` (до T4 merge).
- **НЕ** копаем ADB packet loss (user-owned трек в TimeWeb).
- **НЕ** расширяем LLM-recovery на TT/YT (MVP = только IG).
- **НЕ** трогаем validator/backend/analytics / auth (R3/R4 из `el-kosmetik-upload-2026-04-20.md` уже закрыты commit `3ac979f`).
- **НЕ** делаем новые продуктовые фичи.

## Next step

После approve плана — `/aif-implement` пойдёт параллельно T1 + T2 (user prefer), затем T3 (при готовности permanent key), затем T4 (по явному approve force-push или rebase). T5 — отдельная сессия через неделю.

Оптимальный порядок:
1. **Сейчас:** T1 диагностика (Шаг 1 — DevTools-логи от пользователя) + T2 верификация 502 (curl).
2. **После получения ключа от пользователя:** T2 подстановка → T3 подстановка autowarm/.env → T3 pilot activation.
3. **По согласию:** T4 merge (с явным approve force-стратегии).
4. **Через 7 дней:** T5.
>>>>>>> 3dccb2b0e (docs(plans): бэклог 2026-04-21 + T1 drag + T2 key ротация)
