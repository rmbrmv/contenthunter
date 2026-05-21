# WP #107 — «Ручная выкладка» в delivery-дашборде (перенос из валидатора)

**Дата:** 2026-05-21
**Задача:** OpenProject WP #107 «Готовые уникализации для ручной выкладки» (статус «Тестирование»)
**Связано:** [[2026-05-20-wp107-manual-publish-queue-design]] (исходный спек — ошибочно разместил UI в валидаторе), WP #85 (флаг ручной выкладки + матчер).

## 0. Контекст и причина переделки

Задача #107 дословно требует: «Создаём в **разделе «Выкладка»** новый подраздел в **левом сайдбаре** «Ручная выкладка»». Раздел «Выкладка» с левым сайдбаром — это **delivery-дашборд** (autowarm, `delivery.contenthunter.ru`, модуль «📤 Выкладка», `#sidebar-publishing`).

Исходная реализация (PR validator#18 + delivery#86, смёржены 2026-05-20) ошибочно построила операторский UI в **админке валидатора** (`client.contenthunter.ru`, `/manual-publish`), даже создав там одноимённую секцию сайдбара. Бэкенд-наполнитель в autowarm (`manual_queue_assign.js`) при этом **не подключён** к шедулеру — очередь не наполняется.

Данный спек переносит фичу на правильный хост (delivery), переиспользуя готовую модель данных и логику переходов, и убирает валидаторную копию.

### Что переиспользуется без изменений
- Таблица `validator_manual_publish_queue` (openclaw) — **схема не меняется**. Создана alembic-миграцией `006` валидатора; владение миграциями остаётся у валидатора, autowarm становится вторым потребителем.
- Логика переходов и сериализатор-джойны — портируются один-в-один из `validator/backend/src/services/manual_publish_service.py` в JS.
- Эталонный UI и набор колонок — из `validator/frontend/.../ManualPublishingQueue.vue` + `PublicationCard.vue`.

## 1. Архитектура

```
delivery-дашборд (autowarm public/index.html, vanilla JS)
        │  fetch (cookie-сессия, requireAuth)
        ▼
autowarm server.js — эндпоинты /api/publishing/manual-queue*  (по образцу /api/validator/plan)
        │  pg pool
        ▼
openclaw.validator_manual_publish_queue  ◄── наполняет крон assignManualPublishQueue (autowarm)
                                          ◄── toggle-OFF cancel (остаётся в валидаторе, WP#85)
```

Delivery — единственный дом UI. Валидаторная копия удаляется (revert-PR), включая откат backend-роутера, задеплоенного 2026-05-21.

## 2. Данные и статусы

Таблица `validator_manual_publish_queue` (существует; ключевые поля): `id, slot_id, content_id, unic_result_id, scheme_id, project_id/name, pack_id/name, account_id, account_username, platform, device_serial, raspberry_number, phone_number, planned_date, operator_status, taken_by_id, taken_at, published_by_id, published_at, post_url, cancelled_at, created_at, updated_at`.

**Статусы (внутр. → UI):** `queued`→«В очереди», `in_progress`→«В работе», `published`→«Выложено». Отмена — через `cancelled_at IS NOT NULL` (НЕ значение статуса).

**Колонка «Публикация»:** `post_url` оператора, иначе `matched_post_url` слота (петля с матчером WP#85).

**Атрибуция оператора:** `taken_by_id`/`published_by_id` — FK на `validator_users`, а операторы delivery живут в `autowarm_users` (другая таблица/ID). В задаче #107 колонок «кто взял/выложил» нет, поэтому **эти FK не заполняем (NULL)** — без слома схемы. Время `taken_at`/`published_at` пишем. (Если позже понадобится атрибуция — добавить text-колонку `operator_login`; вне scope.)

## 3. Backend — autowarm `server.js` (под `requireAuth`)

Дашборд де-факто админский: все 9 пользователей `autowarm_users` имеют роль `admin`. Достаточно `requireAuth` (как у соседних `/api/validator/*`). Доп. проверка роли не требуется.

### 3.1 Список
`GET /api/publishing/manual-queue?status=`
- Порт `_JOINED_SELECT`: `validator_manual_publish_queue q` LEFT JOIN `validator_content vc (content_id)`, `unic_results ur (unic_result_id → output_url)`, `validator_schedule_slots s (slot_id → matched_post_url, matched_at)`, `validator_users tu/pu` (логины — отдадим, но в UI не показываем).
- `WHERE q.cancelled_at IS NULL AND ($1::text IS NULL OR q.operator_status = $1)`.
- `ORDER BY q.planned_date ASC, q.phone_number ASC, q.id ASC`.
- Каждая строка сериализуется: + `account_url` (см. 3.4), `publication_url = post_url ?? matched_post_url`, `publication_at = published_at ?? matched_at`, `hashtags ?? []`.
- Сорт/фильтр/группировка — на фронте (датасет ручных слотов мал).

### 3.2 Переходы (по одному эндпоинту, порт из `manual_publish_service.py`)
Каждый: `SELECT … FOR UPDATE` → проверка `cancelled_at` (409) → проверка текущего статуса (409 при несовпадении) → UPDATE → вернуть свежий сериализованный объект.

| Эндпоинт | Переход | Доп. |
|---|---|---|
| `POST .../:id/take` | `queued → in_progress` | `taken_at = now()` |
| `POST .../:id/return` | `in_progress → queued` | `taken_at = NULL` |
| `POST .../:id/publish` | `in_progress → published` | body `{published_at, post_url}` — **оба обязательны (422)**; `published_at` приходит в ISO/UTC (фронт конвертирует из МСК); затем `UPDATE validator_schedule_slots SET matched_post_url=$url, matched_at=$at, updated_at=now() WHERE id=$slot_id AND matched_post_url IS NULL` |
| `POST .../:id/rework` | `published → queued` | чистит `published_at, post_url, taken_at`; **+ чистит `slot.matched_post_url/matched_at`, только если они равны ссылке оператора** (`IS NOT DISTINCT FROM` старого `post_url`) — иначе повторный publish не обновит слот (`WHERE matched_post_url IS NULL`) и петля матчера зависнет; не затираем результат матчера WP#85, если он отличается |

Ошибки: 404 (нет строки), 409 (отменена / неверный статус), 422 (нет date/url в publish), 400 (битый body).

### 3.3 Идемпотентность/гонки
- **Однотабличные** (`take`/`return`) — атомарный условный `UPDATE … WHERE operator_status=<ожидаемый> AND cancelled_at IS NULL RETURNING …` (WHERE-гард = блокировка строки). Два оператора одновременно «Взять» → второй получит 409.
- **Многотабличные** (`publish`/`rework`, пишут `queue` + `slot`) — в **одной client-транзакции** (`BEGIN/COMMIT/ROLLBACK`); `rework` дополнительно `SELECT … FOR UPDATE` для захвата старого `post_url`. Краш между UPDATE'ами не оставляет рассинхрон (queue published / slot без штампа).

### 3.4 `account_url(platform, username)`
IG → `https://instagram.com/{u}`, TT → `https://www.tiktok.com/@{u}`, YT → `https://www.youtube.com/@{u}` (u = username без ведущего `@`). Иначе `null`.

## 4. Наполнитель очереди

`manual_queue_assign.js` экспортирует `assignManualPublishQueue(pool, log)`, `isEnabled`, `batchSize` — но **нигде не вызывается**. Подключаем по образцу `assignUnicResultsToQueue` (server.js:6277–6278):
```js
const { assignManualPublishQueue } = require('./manual_queue_assign');
// после старта пула:
assignManualPublishQueue(pool).catch(e => console.error('[manual-queue]', e.message));
setInterval(() => assignManualPublishQueue(pool).catch(e => console.error('[manual-queue]', e.message)), 30 * 60 * 1000);
```
Kill-switch `MANUAL_QUEUE_POPULATE_ENABLED` (default on) — уже внутри модуля (`isEnabled`). Авто-путь `assignUnicResultsToQueue` уже исключает `manual_publish=true` слоты — пересечения нет.

## 5. Frontend — autowarm `public/index.html` (vanilla JS)

### 5.1 Навигация
- Новый пункт в `#sidebar-publishing` (после «Дашборд», в духе соседних): `<button onclick="nav('publishing-manual')" id="nav-publishing-manual">📤 Ручная выкладка</button>`.
- Новая секция `<div id="section-publishing-manual" class="section …">`.
- Регистрация в `sidebarMap`: `'publishing-manual': 'publishing'`.
- Ветка рендера/фетча в обработчике `nav()` по образцу `if (section === 'publishing-dashboard')` — при активации грузит `GET /api/publishing/manual-queue`, рисует таблицу.

### 5.2 Таблица (поля по задаче #107)
`id | Тел. № | Проект | Платформа (IG/TT/YT) | Пак аккаунтов | Аккаунт (ник + ссылка) | Исх. видео (S3) | Уник. видео (S3) | Схема уник. | План дата выкл. | Статус | Публикация | Действие`.
- **Sticky-заголовки** — есть готовый CSS (`.table-wrap thead th`, паттерн `pkg-th`/`pkg-tf` для двойного ряда заголовок+фильтр).
- **Сортировка по клику** на заголовок: asc → desc → выкл; **мультисортировка при зажатом CTRL** (порядок ключей сохраняется).
- **Фильтры** — строка под заголовками: дропдауны где возможно (платформа, проект, пак, телефон, статус, схема), текст для аккаунта/дат. В колонке «Действие» (строка фильтров) — кнопка **сброса сортировки и фильтров** `⟲`.
- **Группировка по телефону** (как в эталоне).
- Сорт/фильтр/группировка — клиентские (датасет мал).

### 5.3 Кнопки «Действие» (по статусу)
- «В очереди» → **«Взять в работу»** (`take`).
- «В работе» → **«Вернуть в очередь»** (`return`) + **«Отметить выкладку»** (открывает карточку в режиме подтверждения).
- «Выложено» → **«Вернуть на доработку»** (`rework`).
После любого действия — рефреш строки/списка.

### 5.4 Карточка-модалка «Карточка публикации уник. контента»
Клик по строке (кроме кнопок/ссылок) открывает модалку:
- **Статус** (текущий).
- **Контентные поля с copy-on-click** (клик копирует в буфер): Заголовок видео, Описание, Хэштеги, Гео.
- **Видео**: нативный `<video controls>` (уник. видео), ссылки-скачивания (исх. + уник.).
- **Режим «Отметить выкладку»**: поле даты-времени (оператор вводит по **МСК**, фронт конвертирует в ISO/UTC) + поле ссылки на пост. Кнопка «Подтвердить выкладку» активна **только при заполнении обоих** полей; шлёт `publish`.

Модалку и copy-helper делаем в стиле существующего дашборда (vanilla JS; есть `copyToClipboard`-паттерны). Если в `index.html` нет переиспользуемой модалки — лёгкий локальный helper.

**XSS (обязательно):** контент из БД (заголовки/описания клиентов, ники, URL) — НЕдоверенный. Vue-эталон авто-эскейпил; vanilla `innerHTML` — нет. Все текстовые значения интерполируем через `esc()` (HTML-escape), URL — через `safeUrl()` (только `http(s)://`, иначе пусто). Copy-on-click копирует из JS-map по ключу, а не из inline-HTML.

## 6. Удаление из валидатора (revert-PR в `validator-contenthunter`)

Удаляем (фронт + backend):
- `frontend/src/pages/admin/ManualPublishingQueue.vue`, `components/manual-publish/PublicationCard.vue`, `composables/useManualPublishTable.ts`, `api/manualPublish.ts`, роут `/manual-publish` в `router/index.ts`, секцию «Выкладка» + `NavItem` в `AppSidebar.vue` (+ соответствующие тесты).
- `backend/src/routers/manual_publish.py` + его подключение в `main.py`; read/transition-функции в `manual_publish_service.py`.

**Оставляем:** `cancel_queued_for_slot()` + хук в `set_manual_publish` (WP#85: toggle-OFF отменяет `queued`-строки слота — целостность данных, пишет общую таблицу). Утилиты `clipboard.ts`/`accountUrl.ts`/`datetimeMsk.ts` — оставить, если используются ещё где-то; иначе удалить.

Пересборка фронта валидатора (postbuild авто-деплой во `/var/www/validator/`). Откат backend-роутера = частью этого PR (после merge — `git pull` + restart прод-чекаута валидатора).

## 7. Тестирование

- **`node --test` (autowarm, live-DB openclaw):** сериализатор-джойны + `account_url` по платформам + выбор `publication_url`; каждый переход (allowed); запрет недопустимых переходов (409); обязательность `published_at`+`post_url` в `publish` (422); проставление `matched_post_url` только при `IS NULL`; наполнитель — INSERT по ручному слоту + идемпотентность (повторный вызов не дублирует). Чистим тестовые строки в teardown (BEGIN/ROLLBACK или явный DELETE).
- **Frontend:** ручной smoke в delivery после наполнения очереди реальными ручными слотами (sticky/сорт/фильтр/сброс/группировка, кнопки по статусам, copy-on-click, блокировка «Подтвердить» до заполнения).
- **Codex review** спека и плана — раундами до 0 P1 перед отдачей пользователю (стандартная практика).

## 8. Деплой

1. **autowarm** (прод-чекаут `/root/.openclaw/workspace-genri/autowarm`, есть auto-push hook → `GenGo2/delivery-contenthunter`): коммит backend+frontend+wiring → `sudo pm2 restart autowarm` (это процесс autowarm, НЕ validator). Проверить, что наполнитель пошёл (`[manual-queue]` в логах) и очередь наполнилась.
2. **validator**: merge revert-PR → `git pull` прод-чекаута + restart + пересборка фронта.
3. Kill-switch `MANUAL_QUEUE_POPULATE_ENABLED=false` останавливает наполнение, не трогая код.

## 9. Вне scope (YAGNI)
- Серверная сорт/фильтр/пагинация (датасет мал).
- Атрибуция оператора delivery (кто взял/выложил) — не отображается в #107.
- Изменения схемы `validator_manual_publish_queue`.
- Двойной UI (валидатор удаляем).
