# WP#187 — Кнопка «Выложено авто» + отмена для ручной выкладки

- **OpenProject:** #187 «Добавить кнопку отмены для ручной выкладки» (assignee Данил, статус «В разработке»)
- **Автор спеки:** сессия Claude, 2026-05-29
- **Репозиторий кода:** `autowarm-testbench` (ветка реализации заводится отдельно); spec — в `contenthunter`
- **Дизайн:** Approach A (метрический учёт, без мутации `publish_queue`)

## Проблема

Периодически на ручную выкладку попадают слоты, которые на самом деле уже были выложены **автоматически** (false-negative хэндофф: авто-паблишер счёл задачу упавшей, но публикация фактически произошла — сразу или поздним ретраем). Оператору нечем честно закрыть такую строку: «Отметить выложенным» требует ссылку и засчитывает слот как **ручную** выкладку, раздувая метрику ручного труда; оставить как есть — пак висит «В очереди»/«Частично выложено».

## Цель

Дать оператору в карточке выкладки рядом с зелёной «Отметить выложенным» кнопку **«Выложено авто»**, которая:
1. закрывает строку платформы без обязательной ссылки;
2. засчитывается в метриках как **авто-успех**, а не как ручная выкладка (и **не** уходит в «Потеряно»);
3. имеет кнопку **«Отменить»** на случай ошибочного нажатия — возврат строки в **«В работе»**.

Пак становится «Выложено», когда все строки закрыты любым способом (`published` или `published_auto`). Отдельного «смешанного» статуса пака не вводим.

## Решённые продуктовые развилки (согласовано с Данилом 2026-05-29)

| Вопрос | Решение |
|---|---|
| Учёт в воронке (План = Авто + Ручная + Потеряно) | **Как АВТО-успех** |
| «Отменить» возвращает в статус | **«В работе»** (`in_progress`) |
| Ссылка на публикацию при «Выложено авто» | **Опционально** (можно вставить, не обязательно) |

## Выбор подхода

**Approach A — учёт в слое метрик (выбран).** Вводим новый терминальный `operator_status='published_auto'`. `publish_queue` **не трогаем** — он остаётся честной записью того, что реально сделал авто-паблишер. Атрибуцию «как авто» делаем в `pipeline_funnel.js`.

- ➕ Не вмешиваемся в стейт-машину авто-паблишера и retry-движка (WP#108); обратимо; «Отменить» тривиален (нет отката `done`).
- ➖ Правка воронки в нескольких местах (подсчёт + Q4 + сверка + строки дашборда/TG).

Отклонённые:
- **B (флип `publish_queue.status='done'`):** меньше правок воронки, но запись `done` без `publish_task_id`/URL в чужую таблицу, риск конфликта с retry-движком и dispatch-гардом (WP#183), сложный откат.
- **C (считать как ручную):** проще всего, но раздувает метрику ручного труда — против смысла задачи.

## Архитектура изменений

### 1. Модель данных (миграция)

Существующее ограничение:
```
ck_manual_pub_status CHECK (operator_status = ANY (ARRAY['queued','in_progress','published']))
```
Миграция `migrations/20260529_wp187_published_auto_status.sql` (+ `__rollback.sql`):
- `ALTER TABLE validator_manual_publish_queue DROP CONSTRAINT ck_manual_pub_status;`
- `... ADD CONSTRAINT ck_manual_pub_status CHECK (operator_status = ANY (ARRAY['queued','in_progress','published','published_auto']));`
- Rollback восстанавливает исходный набор (предусловие: предварительно перевести любые `published_auto` обратно — в rollback включить `UPDATE ... SET operator_status='in_progress' WHERE operator_status='published_auto'`, иначе CHECK не наложится).

`published_auto` — терминальный статус наравне с `published`.

### 2. Переходы (`manual_publish_queue.js`)

**`markPublishedAuto(pool, id, { postUrl })`** → новый эндпоинт `POST /api/publishing/manual-queue/:id/publish-auto`:
- Предусловие: `operator_status='in_progress'` и `cancelled_at IS NULL` (как у `markPublished`); иначе `failTransition`.
- `SET operator_status='published_auto', published_at=now(), post_url=$postUrl(nullable), updated_at=now()`.
- Опциональная ссылка пишется **только в строку очереди** (`post_url`, для отображения в карточке). `slot.matched_post_url` **НЕ трогаем** (codex P1: иначе слот цепляется к дисплейной метрике «реактивной ручной» выкладки). Один UPDATE — транзакция не нужна.

**`cancelPublishedAuto(pool, id, userId)`** → новый эндпоинт `POST /api/publishing/manual-queue/:id/cancel-auto`:
- Предусловие: `operator_status='published_auto'` и `cancelled_at IS NULL`; иначе `failTransition`.
- `SET operator_status='in_progress', post_url=NULL, published_at=NULL, taken_by_id=$userId, taken_at=now(), updated_at=now()`.
- Слот при подтверждении не трогали → откатывать нечего. Один UPDATE.

Серверные роуты — по образцу существующих в `server.js:5808/5816`, `userId` из `req.session.user.id`.

### 3. Агрегат пака (`mpqAgg`, фронт)

Сейчас:
```js
const pub = rows.filter(r => r.operator_status === 'published').length;
```
Станет: «закрытыми» считаются `published` **и** `published_auto`.
- если `closed === rows.length` → `published`;
- если `closed > 0` → `partial`;
- если есть `in_progress` → `in_progress`;
- иначе `queued`.

### 4. Фронтенд (`public/index.html`)

- `MPQ_STATUS`: добавить `published_auto: 'Выложено авто'`.
- Бейдж: фиолетовый стиль (цвета из мокапа: текст `#4a45c2`, фон `#ecebfb`).
- `mpqPlatformRowHtml`:
  - ветка `in_progress`: рядом с зелёной «Отметить выложенным» — вторая кнопка «Выложено авто» (индиго-аутлайн) → `mpqPublishAutoPlatform(id)`. Берёт ссылку из того же `#mpq-purl-{id}` (если введена — передаём `post_url`, иначе `null`). Один клик, ссылка не обязательна.
  - новая ветка `published_auto`: бейдж «Выложено авто»; в колонке ссылки — кликабельный URL, если есть, иначе «— выложено автовыкладкой»; кнопка «Отменить» (серая) → `mpqCancelAutoPlatform(id)`.
- `mpqCards().platforms_label`: для `published_auto` — отдельная пометка (напр. ` ⚡`).
- `mpqIsClaimable` и take/return-логика: `published_auto` не клеймится и не блокирует клейм остальных строк пака (как `published`).
- JS-функции `mpqPublishAutoPlatform`/`mpqCancelAutoPlatform` по образцу `mpqPublishPlatform`/`mpqReworkPlatform`; после ответа — `mpqLoad()`.
- `mpqCardComputeSig` уже включает `operator_status` и `publication_url` → карточка перерисуется на изменение.

### 5. Воронка (`pipeline_funnel.js` + рендер в `index.html`)

- Новый подсчёт `published_auto` в Q2: `COUNT(*) FILTER (WHERE operator_status='published_auto' AND NOT EXISTS(publish_queue ... status='done'))`, якорь по `COALESCE(s.slot_date, m.planned_date)` в окне. Дедуп `NOT EXISTS` (codex P1) исключает строки, уже учтённые в `auto_published`, — чтобы не было двойного счёта.
- Отнести в **«Авто»**: в `assembleFunnel` ввести `auto_acknowledged`, и:
  - `lost_count = clamp0(plan - auto_published - auto_acknowledged - manual_published_total)`;
  - отображаемый авто-успех = `auto_published + auto_acknowledged` (в сверке и `sr_total`).
- Q4 (loss_breakdown): в `NOT EXISTS (... operator_status='published')` добавить `OR operator_status='published_auto'`, чтобы такие слоты не попадали в разбивку «Потеряно».
- Рендер дашборда (`index.html` ~line 11948–11997) и TG-форматтер: добавить строку «Выложено авто (подтв. оператором)» и учесть её в формуле сверки.

### 6. Смежные точки (проверить при реализации)

- **Populator / `isAlreadyPublished` (WP#148):** `published_auto` тоже считать «уже выложено» — не реквеуить строку.
- **Dispatch-гард (WP#183):** проверяет `operator_status IN ('queued','in_progress')` — `published_auto` терминальный, авто-диспатч не блокирует. Ожидаемо корректно, подтвердить.
- **`manual_queue_assign.js`:** назначает `queued`-строки; `published_auto` назначать не должен.
- **Cleanup-скрипты (wp148/wp155):** не должны затрагивать `published_auto`.

### 7. Kill-switch

`MANUAL_PUBLISHED_AUTO_ENABLED` (env, default — согласовать; предложение: `true` после verify) гейтит новые эндпоинты (`publish-auto`/`cancel-auto`) и отрисовку кнопки «Выложено авто» на фронте. При `false` — поведение как до фичи.

## Тестирование

- Юнит (`manual_publish_queue.js`): `markPublishedAuto` (с/без `postUrl`, проставление/непроставление слота), `cancelPublishedAuto` (откат слота, перевод в `in_progress`, `taken_by_id`), `failTransition` на неверных предусловиях. Образец — `test_manual_publish_queue.test.js`.
- Юнит (`mpqAgg` pure): пак с миксом `published`/`published_auto`/`in_progress` → корректный агрегат. Образец — `test_mpq_pure.test.js`.
- Юнит (воронка): `published_auto` уходит в «Авто», не в «Потеряно»; сверка `Авто+Ручная+Потеряно=План` сходится.
- Live-smoke (по возможности): полный цикл `in_progress → published_auto → cancel → in_progress` на тестовой строке.

## Критерии готовности

1. Кнопка «Выложено авто» видна на строке `in_progress`, закрывает строку без обязательной ссылки.
2. Кнопка «Отменить» возвращает строку `published_auto → in_progress`.
3. Пак становится «Выложено», когда все строки ∈ {`published`, `published_auto`}.
4. В воронке слот считается авто-успехом и не попадает в «Потеряно»; сверка сходится.
5. Миграция накатывается/откатывается чисто; kill-switch выключает фичу без регрессий.
6. Все юнит-тесты зелёные; `codex review` спеки/плана — 0 P1.

## Вне scope

- Автоматическое детектирование «на самом деле выложено авто» (это решение оператора по кнопке).
- Изменение стейт-машины авто-паблишера/`publish_queue`.
- Платформы вне IG/TT/YT.
