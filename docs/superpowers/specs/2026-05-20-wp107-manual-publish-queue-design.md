# WP #107 — «Готовые уникализации для ручной выкладки» (design)

- **Дата:** 2026-05-20
- **OpenProject:** WP #107 (проект Content Hunter, тип «Задача», приоритет «Немедленно», assignee Данил, автор Анастасия)
- **Зависит от:** WP #85 (флаг `manual_publish` на слотах + matcher-крон — уже в проде)
- **Репозитории:** `validator-contenthunter` (миграция, backend, frontend) + `delivery-contenthunter`/autowarm (наполнитель очереди)
- **БД:** общая `openclaw` (validator backend, autowarm и factory-таблицы — один кластер)

## 1. Цель и контекст

WP #85 дал админам тогл «слот → ручная выкладка». Теперь нужен **операторский интерфейс-очередь**: для каждого слота, помеченного на ручную выкладку, оператор получает готовую пару «одно конкретное уникализированное видео под один конкретный аккаунт и публикацию», берёт её в работу, публикует вручную на телефоне и отмечает результат.

Операторы — это **должность**, не роль: работают под админской ролью. Раздел — admin-only.

### Что уже есть (факты разведки)

- `publish_queue` — каноническая гранулярность авто-пайплайна: 1 строка = (уник.результат × аккаунт × платформа × устройство) со всеми полями. Наполняет `assignUnicResultsToQueue()` (autowarm `server.js`), диспетчит на телефоны `dispatchPublishQueue()` (берёт строго `status='pending'`).
- Для слотов `manual_publish=true` авто-пайплайн **не формирует** очередь: WP #85 добавил guard `NOT EXISTS (... vss.manual_publish=true)` в `assignUnicResultsToQueue`, а `cancel_downstream_for_content(keep_slot_id=slot_id)` отменяет pending `publish_queue`/`unic_tasks` **других** слотов того же контента. Уникализация **самого** ручного слота сохраняется (`keep_slot_id`) → `unic_results` для него появляются, но в очередь не попадают.
- Спаривание scheme→pack→account→device: `unic_results.scheme_id` → pack через `unic_tasks.meta.pack_scheme_map` (или позиционно: `unic_tasks.schemes` ↔ паки проекта по `id ASC`) → устройство через `factory_pack_accounts.device_num_id → factory_device_numbers` → активные аккаунты пака `DISTINCT ON(platform)`.
- Источники полей: исходное видео `validator_content.s3_url`; уник.видео `unic_results.output_url`; схема `unic_results.scheme_id`; телефон `factory_device_numbers.device_number`; план-дата `validator_schedule_slots.slot_date`; заголовок/описание/хэштеги/гео `validator_content`.
- Роли: `client|manager|producer|admin` (роли `operator` нет — и не добавляем). `require_role(UserRole.admin)` — паттерн admin-only endpoint'ов.
- Frontend: Vue 3 + TS + Tailwind, без UI-китов. Переиспользуемой таблицы нет, но есть проверенный паттерн сорт/фильтр/sticky-thead (`pages/admin/UsersManagement.vue`) и модалки через `Teleport` (`components/schemes/SchemeDetailModal.vue`). Видеоплеер — нативный `<video controls>`. Copy-to-clipboard есть в `ManagerDashboard.vue` (вынести в утилиту).
- Backend tests: `backend/tests/` + autouse `engine.dispose()` фикстура в `conftest.py` (обязательна для live-DB тестов). Последняя миграция alembic — `005_wp85_manual_publish`.

### Архитектура (выбран Вариант A)

Отдельная таблица `validator_manual_publish_queue` в openclaw, физически изолированная от `publish_queue` (ноль риска случайной автопубликации). Наполняет её **autowarm** отдельной cron-функцией (переиспользует канонический пайринг, авто-путь не трогаем). Операторский статус, действия и UI — на стороне validator.

## 2. Модель данных — `validator_manual_publish_queue`

Гранулярность = 1 строка на (уник.результат × аккаунт × платформа). Денормализуем факты пайринга (вычисляются один раз при назначении); текст контента и медиа-ссылки тянем live-джойном, чтобы правки контента сразу отражались у оператора.

| Колонка | Тип | Nullable | Источник / смысл |
|---|---|---|---|
| `id` | serial PK | no | — |
| `slot_id` | int FK→`validator_schedule_slots(id)` | no | через `unic_tasks.meta.slot_id` |
| `content_id` | int | no | `unic_tasks.content_id` |
| `unic_result_id` | int | no | конкретное уник.видео (схема) |
| `unic_task_id` | int | no | — |
| `scheme_id` | int | yes | «Схема уник.» = `unic_results.scheme_id` |
| `project_id` | int | no | проект |
| `project_name` | text | yes | денорм. имя проекта |
| `pack_id` | int | yes | «Пак аккаунтов» |
| `pack_name` | text | yes | денорм. имя пака |
| `account_id` | int | yes | `factory_inst_accounts.id` (для ссылки) |
| `account_username` | text | no | «Аккаунт» (ник) |
| `platform` | text | no | `instagram`/`tiktok`/`youtube` |
| `device_serial` | text | yes | устройство |
| `raspberry_number` | int | yes | Pi |
| `phone_number` | int | yes | «Тел.№» = `factory_device_numbers.device_number` |
| `planned_date` | date | no | «План дата выкл.» = `slot_date` |
| `operator_status` | enum `manual_pub_status` | no | `queued`/`in_progress`/`published` (default `queued`) |
| `taken_by_id` | int FK→`validator_users(id)` | yes | кто «взял в работу» |
| `taken_at` | timestamptz | yes | — |
| `published_by_id` | int FK→`validator_users(id)` | yes | кто отметил выкладку |
| `published_at` | timestamptz | yes | **дата-время публикации, введённое оператором** (на UI — МСК) |
| `post_url` | text | yes | ссылка на пост (введена оператором) |
| `cancelled_at` | timestamptz | yes | для строк, отменённых при toggle OFF |
| `created_at` | timestamptz | no | default now() |
| `updated_at` | timestamptz | no | default now() |

**Enum** `manual_pub_status`: `queued | in_progress | published`. (Состояние «отменена» — через `cancelled_at IS NOT NULL`, чтобы не плодить значения enum.)

**Индексы:**
- UNIQUE `(unic_result_id, account_username, platform)` **WHERE `cancelled_at IS NULL`** (partial) — идемпотентность наполнителя; отменённые строки не блокируют пересоздание после цикла вкл→выкл→вкл.
- `(operator_status, planned_date)` WHERE `cancelled_at IS NULL` — основной список.
- `(slot_id)` — обработка toggle OFF и связь со слотом.
- `(phone_number, planned_date)` — группировка по телефону.

**Live-джойн при чтении (НЕ дублируем в таблице):**
- `validator_content`: `title`, `description`, `hashtags`, `geo`, `s3_url` (исходное видео).
- `unic_results`: `output_url` (уник.видео).
- `validator_schedule_slots`: `matched_post_url`, `matched_at` (подтверждение матчера WP #85).

**Дедуп при наполнении:** не вставлять строку, если для `(content_id, account_username, platform)` уже есть незакрытая запись (зеркало дедупа `assignUnicResultsToQueue`).

**Миграция:** alembic `006_wp107_manual_publish_queue` в validator (validator — владелец схемы). autowarm-наполнитель деплоится только после неё.

## 3. Статусная машина и колонка «Действие»

Кнопки в колонке «Действие» зависят от статуса; переходы валидируются на бэке (перескок запрещён).

```
[В очереди]  --«Взять в работу»-->        [В работе]   set taken_by_id, taken_at
[В работе]   --«Вернуть в очередь»-->      [В очереди]  clear taken_*
[В работе]   --«Отметить выкладку»-->      (открыть модалку публикации, см. §5.3)
                  └─ подтверждение в модалке --> [Выложено]  set published_*, post_url
[Выложено]   --«Вернуть на доработку»-->   [В очереди]  clear published_*, post_url, taken_*
```

- «Взять в работу» проставляет `taken_by_id` = текущий пользователь, `taken_at`.
- «Отметить выкладку» **не публикует напрямую**: открывает «Карточку публикации» в режиме подтверждения (§5.3). Переход в `published` происходит только после ввода даты-времени и ссылки.
- «Вернуть на доработку» (из `Выложено`) → `queued`, очищает `published_by_id`/`published_at`/`post_url` **и `taken_by_id`/`taken_at`** (запись снова свободна для любого оператора). Связанные `matched_*` на слоте — оставляем как историю.

Очередь — общая «живая»: оператор берёт любую запись (не по конкретным аккаунтам). `taken_by_id` фиксирует, кто взял, для прозрачности.

## 4. Наполнение очереди — autowarm

Новая cron-функция `assignManualPublishQueue()` рядом с `assignUnicResultsToQueue()` (горячий авто-путь не трогаем):

1. SELECT `unic_results` со `status IN ('ready','done')`, чей слот (`unic_tasks.meta.slot_id`) имеет `manual_publish=true`, и для которых **ещё нет** строки в `validator_manual_publish_queue`.
2. Резолвинг scheme→pack→device→accounts — **тот же**, что в `assignUnicResultsToQueue`. Чтобы не разъезжалось внутри autowarm, общий резолвинг выносим в helper'ы (`resolvePackForScheme`, `resolveDevice`, `resolvePackAccounts`), используемые обеими функциями. Рефактор без смены поведения, под существующими node-тестами (`test_slot_matcher.test.js` и др.).
3. `planned_date = slot_date`; для каждой пары (аккаунт × платформа) — INSERT с `operator_status='queued'`, `ON CONFLICT (unic_result_id, account_username, platform) DO NOTHING`, с дедупом по `(content_id, account_username, platform)`.
4. Запуск сразу + `setInterval` (как у соседей). Kill-switch: `MANUAL_QUEUE_POPULATE_ENABLED` (default true), `MANUAL_QUEUE_POPULATE_INTERVAL_MS`, `MANUAL_QUEUE_POPULATE_BATCH`.

**Связка с WP #85:**
- toggle ON: ничего дополнительно — уникализация слота сохранена (`keep_slot_id`), наполнитель сам подхватит `unic_results`.
- toggle OFF (в validator `set_manual_publish`): пометить `cancelled_at=now()` строки этого `slot_id` в статусе `queued` (строки `in_progress`/`published` оставить для истории).

**Замыкание петли «Публикация» (режим «оба»):** при подтверждении выкладки в карточке (с введённой ссылкой) validator проставляет `matched_post_url`/`matched_at` на слоте с пометкой источника `operator`, если они ещё пустые; matcher WP #85 позже подтверждает/дополняет. Колонка «Публикация» на UI показывает `post_url` оператора, иначе `matched_post_url`.

## 5. Backend (validator) — всё admin-only

Новый роутер `src/routers/manual_publish.py` + сервис `src/services/manual_publish_service.py`. Все endpoint'ы под `Depends(require_role(UserRole.admin))`.

### 5.1 Чтение
- `GET /api/manual-publish/queue` → массив строк (сериализатор с live-джойнами). Опц. query-фильтр `status`. Сорт/фильтр/группировку выполняет фронт (датасет ограничен ручными слотами); сервер отдаёт активные (`cancelled_at IS NULL`) строки, по умолчанию `planned_date ASC`.
- `GET /api/manual-publish/queue/{id}` → данные карточки (те же джойны + поля публикации).

Сериализатор отдаёт: `id, phone_number, project_name, platform, pack_name, account_username, account_url, source_video_url, unic_video_url, scheme_id, planned_date, operator_status, post_url (или matched_post_url), published_at (или matched_at), title, description, hashtags, geo, taken_by, published_by`. `account_url` строится по платформе: IG `https://instagram.com/{username}`, TT `https://www.tiktok.com/@{username}`, YT — best-effort (по `username`/`gmail`; при невозможности — null).

### 5.2 Действия (валидация перехода на сервере, 409 при недопустимом)
- `POST /api/manual-publish/queue/{id}/take` → `in_progress` (set `taken_by_id`,`taken_at`). Разрешено только из `queued`.
- `POST /api/manual-publish/queue/{id}/return` → `queued` (clear `taken_*`). Только из `in_progress`.
- `POST /api/manual-publish/queue/{id}/publish` body `{published_at: ISO, post_url: str}` → `published`. Только из `in_progress`. **Оба поля обязательны** (валидация Pydantic; пустые → 422). Доп. эффект: запись `matched_*` на слоте (источник operator), если пусто.
- `POST /api/manual-publish/queue/{id}/rework` → `queued` (clear `published_*`,`post_url`,`taken_*`). Только из `published`.

### 5.3 Карточка-модалка (контракт для фронта)
`GET .../{id}` возвращает данные; режим подтверждения — на фронте (см. §5.4). Endpoint `publish` принимает `published_at` (оператор вводит по МСК — фронт конвертирует в ISO/UTC) и `post_url`.

## 6. Frontend (validator, Vue 3 + Tailwind)

### 6.1 Навигация
- Новая секция сайдбара «Выкладка» (в admin-блоке `AppSidebar.vue`) → `NavItem` «Ручная выкладка» → `/manual-publish`.
- Роут в `router/index.ts` с `meta: { roles: ['admin'] }`.
- Новый API-модуль `src/api/manualPublish.ts` (паттерн `content.ts`).

### 6.2 Страница `pages/admin/ManualPublishingQueue.vue` (таблица по образцу `UsersManagement.vue`)
Колонки: id, Тел.№, Проект, Платформа, Пак, Аккаунт (ник→ссылка), Исх. видео (ссылка/иконка), Уник. видео, Схема, План дата выкл., Статус, Публикация (ссылка), Действие.
- **Закреплённые заголовки:** `<thead class="sticky top-0 z-10">`.
- **Сортировка** кликом по заголовку: возрастание → убывание → сброс (хронологический/исходный порядок). **Мультисортировка при зажатом CTRL** — упорядоченный список ключей (`sortKeys: [{col,dir}, ...]`), индикатор приоритета (1,2,3) у заголовков.
- **Фильтры** — строка под заголовками: выпадающие списки где возможно (платформа, проект, пак, телефон, статус, схема); текст для аккаунта/дат. В колонке «Действие» (строка фильтров) — кнопка **сброса фильтров и сортировки** (`⟲`).
- **Сорт по умолчанию:** `planned_date` ↑ (старые вверху). **Группировка по телефону:** строки-заголовки групп по `phone_number`, группы упорядочены по самой старой `planned_date` внутри группы (быстрее освобождать телефон).
- Кнопки «Действие» по статусу (§3). Клик по строке (вне кнопок/ссылок) открывает карточку.
- Авто-обновление списка после действий; периодический рефетч (как в других страницах).

### 6.3 Карточка `components/manual-publish/PublicationCard.vue` (Teleport-оверлей)
- **Статус** записи сверху.
- Группа контентных полей с **копированием по клику** (Заголовок видео; Описание + хэштеги; Гео) — клик копирует в буфер, показывает «Скопировано» ~2 c.
- **Видеоплеер** (нативный `<video controls>`, уник.видео). Под ним ссылки «Скачать уникализированное видео» и «Скачать исходное видео».
- Группа «Публикация»: дата-время по МСК + ссылка на пост.
- **Кнопка действия** меняется по статусу.
- **Режим подтверждения выкладки:** при нажатии «Отметить выкладку» (из таблицы или из карточки для записи `in_progress`) карточка открывается/переключается в режим подтверждения:
  - Сверху **красный баннер**: «Введите дата-время публикации и ссылку на публикацию».
  - Активны поля: дата-время публикации (по МСК) и ссылка на пост.
  - Кнопка «Подтвердить выкладку» **заблокирована, пока оба поля не заполнены**; по подтверждению → `POST .../publish` → статус `Выложено`.

### 6.4 Утилиты
- `src/utils/clipboard.ts` — вынести `copyToClipboard()` из `ManagerDashboard.vue` (navigator.clipboard + textarea-fallback).
- хелпер `accountProfileUrl(platform, username)` (зеркало backend-логики, для прямых ссылок).

## 7. RBAC, kill-switches

- **RBAC (тройная защита):** endpoint `require_role(UserRole.admin)` + route `meta.roles:['admin']` + сайдбар в admin-блоке. Non-admin → 403/redirect.
- **Kill-switches:** `MANUAL_QUEUE_POPULATE_ENABLED=false` (autowarm — остановить наполнение). UI закрыт ролью; отдельный флаг не нужен.

## 8. Тесты

- **pytest (validator, live-DB, autouse `engine.dispose`):** сериализатор (джойны, `account_url` по платформам, выбор `post_url` vs `matched_post_url`); каждый переход статуса (allowed); запрет недопустимых переходов (409); обязательность `published_at`+`post_url` в `publish` (422); RBAC non-admin (403); toggle OFF → `cancelled_at` на `queued`-строках слота.
- **node --test (autowarm):** `assignManualPublishQueue` — пайринг scheme→pack→account→device, дедуп, идемпотентность (`ON CONFLICT`), guard `manual_publish=true`, kill-switch; регресс-тесты вынесенных helper'ов (поведение `assignUnicResultsToQueue` не изменилось).
- **Vitest (frontend):** мультисортировка (CTRL, порядок ключей), фильтры (дропдауны + сброс), группировка по телефону, видимость кнопок по статусу, копирование полей, блокировка «Подтвердить выкладку» до заполнения полей.

## 9. Порядок деплоя

1. validator: `git pull` → `alembic upgrade head` (создаёт таблицу + enum).
2. autowarm: `git pull` → restart (подхватить `assignManualPublishQueue`). Проверить лог наполнителя.
3. validator: `npm run build` (postbuild авто-деплой фронта во `/var/www/validator/`).
4. Мониторить лог наполнителя на дубли/промахи пайринга первую неделю.

(Деплой выполняет Данил по чек-листу; код не пушим в prod без явного запроса.)

## 10. Вне объёма (YAGNI / будущее)

- Роль `operator` как отдельная сущность (сейчас — админская роль).
- Серверная сорт/фильтр/пагинация (датасет ручных слотов мал; делаем на фронте).
- Авто-капча/верификация ссылки на пост (матчер WP #85 это закрывает).
- Уведомления оператора (telegram/push) о новых записях.

## 11. Решённые вопросы

- Доступ: админская роль (оператор — должность). ✅
- «Публикация»: оба пути — оператор вводит дату-время+ссылку (обязательно), матчер подтверждает/дополняет. ✅
- Объём: полный (закреп заголовков, мультисортировка CTRL, выпадающие фильтры, сброс, группировка по телефону, карточка, полный статусный цикл). ✅
- «Вернуть на доработку» → «В очереди». ✅
- «Отметить выкладку» → открывает модалку с красным баннером «Введите дата-время публикации и ссылку на публикацию»; подтверждение из карточки. ✅
