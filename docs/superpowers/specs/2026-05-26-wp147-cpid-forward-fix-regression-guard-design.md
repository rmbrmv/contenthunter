# WP #147 — `publish_tasks.client_publish_id`: антирегресс-гард forward-пути (дизайн)

**Дата:** 2026-05-26
**Репозиторий-цель:** `GenGo2/delivery-contenthunter` (сервис autowarm, прод `/root/.openclaw/workspace-genri/autowarm`)
**Класс задачи:** B (рискованная зона: прод-пайплайн публикаций + общая БД `openclaw`), но scope после разведки — маленький.

---

## 1. Контекст и первопричина (подтверждено разведкой)

Симптом из задачи: `publish_tasks.client_publish_id` (cpid — связка задачи публикации со строкой `publish_queue`) часто пустой, и «интермиттентно по дням» (22.05 — 76% NULL, 19.05 — 39%, 20/23/24/25.05 — 0%). Из-за NULL cpid агрегат «попытка» в очереди занижался — это первопричина бага #127 («0/12» при реально выложенных роликах).

**Разведка 2026-05-26 (read-only) показала, что это НЕ живой баг-путь:**

1. Колонка `publish_tasks.client_publish_id` **появилась только в WP #108** (миграция `f59e9f1`). До #108 связи задача↔очередь в этой таблице физически не было.
2. **Историческая интермиттентность = неполный разовый бэкфилл `d2baaf8`** (часть #108). Он матчил
   ```sql
   UPDATE publish_tasks pt SET client_publish_id = pq.client_publish_id
   FROM publish_queue pq
   WHERE pq.publish_task_id = pt.id AND pt.client_publish_id IS NULL;
   ```
   т.е. связывал только задачи, на которые очередь **всё ещё указывает**. **Перетёртые попытки ретраев** (старые `failed`-задачи, на смену которым очередь получила новую задачу) сматчить нельзя → они остались NULL.
   - Дни с массой ретраев (05-15 — равномерно по IG/TT/YT; 05-19 — почти весь NULL это YouTube, 141/216) → много перетёртых → высокий NULL%.
   - Тихие дни (16/17/20/21) → почти нет ретраев → 0%.
   Это полностью объясняет «интермиттентность» — скрытого старого пути нет.
3. **Forward-путь уже закрыт #108 (`ce4429b`) и проверен живьём:**
   - Единственные INSERT в `publish_tasks`: dispatch (`server.js:6813`) и ручной админ-эндпоинт (`server.js:2754`).
   - dispatch берёт cpid из `SELECT * FROM publish_queue → item.client_publish_id`; колонка очереди `NOT NULL DEFAULT gen_random_uuid()` → `item.client_publish_id` всегда есть.
   - **Re-queue** переиспользует тот же dispatch → cpid ставится. url-poller (WP #86) задачи **не создаёт**, только UPDATE → не источник NULL.
   - Данные: **все 1832 NULL-строки имеют дату ≤ 2026-05-22; после деплоя — ни одной**; 23–26.05 = 0% NULL при 29 активных retry-handoff-ах.
4. Единственный остаточный путь без cpid — `POST /api/publish/tasks` (`server.js:2754`, ручное создание задачи напрямую из тела запроса, **без строки очереди**). Здесь cpid=NULL **семантически корректен**: линковать не к чему.

**Вывод:** «forward-fix во всех путях» по сути выполнен #108. User-facing импакт #127 уже снят (планировщик доверяет `publish_queue.status`, коммит `b2fa826`). Расследование интермиттентности завершено.

## 2. Решения (согласованы с Данилом 2026-05-26)

- **Бэкфилл исторических NULL: НЕ делать.** Импакт снят; из ~1832 NULL безопасно восстановимо back-ref'ом лишь ~194, остальные ~1600 — перетёртые попытки, восстановимы только нечётким матчингом = рискованная мутация общей прод-таблицы ради косметики исторического счётчика. Не оправдано.
- **Forward-hardening: антирегресс-гард + закрыть WP.** dispatch уже ставит cpid — гарантируем, что будущий рефактор INSERT-а не уронит колонку молча.
- **Ручной эндпоинт `POST /api/publish/tasks`: НЕ трогаем** — cpid-less by design, документируем.

## 3. Артефакт 1 — антирегресс-гард (source-contract тест)

### Почему source-contract, а не поведенческий
Память фиксирует инцидент #108: live-DB тест dispatch/retry-контроллера **однажды реально мутировал 494 строки + 113 слотов на проде**. Поэтому гард **не запускает `dispatchPublishQueue` и не пишет в БД**. Он статически проверяет исходник `server.js`: что INSERT внутри `dispatchPublishQueue` несёт `client_publish_id`. Это ловит ровно ту регрессию, которой мы боимся («кто-то отредактировал column-list и выкинул cpid»), и зеркалит уже принятый в репо паттерн `tests/test_stats_from_filter_contract.test.js`.

### Где
Перепрофилировать существующий **`test_client_publish_id.test.js`** (сейчас он назван обманчиво — проверяет лишь DB-дефолт на `publish_queue`, а не проброс в `publish_tasks`). Файл станет единым источником истины для «cpid не теряется на пути очередь→задача»:
- **Тест 1 (оставить, уточнить комментарий/имя):** `publish_queue.client_publish_id` имеет NOT NULL DEFAULT — upstream-гарантия, что `item.client_publish_id` в dispatch никогда не NULL. Read-only.
- **Тест 2 (новый, source-contract):** INSERT внутри `dispatchPublishQueue` несёт `client_publish_id` в column-list и `item.client_publish_id` в params.

### Логика теста 2 (надёжное извлечение, без номеров строк)
```js
const fs = require('fs');
const src = fs.readFileSync(require.resolve('./server.js'), 'utf8');

// 1) изолировать тело dispatchPublishQueue (до следующего top-level 'async function ')
const fnStart = src.indexOf('async function dispatchPublishQueue');
assert.ok(fnStart > 0, 'dispatchPublishQueue найдена в server.js');
const after = src.slice(fnStart + 1);
const nextFn = after.indexOf('\nasync function ');
const fnBody = nextFn > 0 ? after.slice(0, nextFn) : after;

// 2) внутри тела найти INSERT INTO publish_tasks и его params-массив
const insIdx = fnBody.indexOf('INSERT INTO publish_tasks');
assert.ok(insIdx > 0, 'dispatch содержит INSERT INTO publish_tasks');
const endIdx = fnBody.indexOf(']);', insIdx);          // конец pool.query(`...`, [ ... ])
assert.ok(endIdx > insIdx, 'нашёлся блок INSERT+params');
const block = fnBody.slice(insIdx, endIdx);

// 3) контракт: cpid в column-list И в params
assert.match(block, /client_publish_id/,        'column-list dispatch-INSERT обязан включать client_publish_id');
assert.match(block, /item\.client_publish_id/,  'params dispatch-INSERT обязан передавать item.client_publish_id');
```
Якоримся на имени функции и ключевом слове INSERT (не на номерах строк / фиксированных окнах) → устойчиво к форматированию. Точно различает dispatch-INSERT (с cpid) и ручной INSERT на 2754 (без cpid), т.к. ищем строго внутри тела `dispatchPublishQueue`.

### Запуск
`node --test --test-force-exit test_client_publish_id.test.js` (в корне repo; package.json `test` гоняет `tests/*.test.js`, корневые тесты — этой же командой по имени, как остальные `test_*.test.js`).

### Acceptance
- Тест 2 **зелёный** на текущем `server.js`.
- Негатив-проверка вручную при разработке: временно убрать `client_publish_id` из column-list → тест **краснеет** (доказывает, что гард ловит регрессию). Откатить.
- Существующий тест 1 продолжает проходить.

## 4. Артефакт 2 — эвиденс-док

`docs/evidence/2026-05-26-wp147-cpid-root-cause-forward-already-fixed.md`. Фиксирует: первопричину (неполный бэкфилл `d2baaf8`), что forward закрыт #108 (`ce4429b`), данные (все 1832 NULL ≤22.05, 0% после, 4 дня чисто, 29 handoff-ов), решение «без бэкфилла», добавленный гард, ручной эндпоинт cpid-less by design.

## 5. Артефакт 3 — закрыть WP #147

House-style комментарий в OpenProject (Что было не так → Что сделано → Что осталось, без жаргона/футера) + статус. Содержание: первопричина не живой баг, forward закрыт #108, добавлен антирегресс-гард, бэкфилл сознательно не делаем (обоснование), импакт #127 снят.

## 6. Non-goals (явно)
- Никакого бэкфилла (ни безопасного ~194, ни нечёткого ~1600).
- Не менять `dispatchPublishQueue` (он уже корректен).
- Не менять `POST /api/publish/tasks` (cpid-less by design).
- Не запускать live-dispatch/мутирующие тесты на проде (урок #108).
- Не лезть в планировщик #127 (фоллбэк на queue.status уже на проде).

## 7. План деплоя
Изменение — только новый тест (+ комментарий). Деплоить в прод-autowarm нечего (тест не влияет на рантайм). Достаточно коммита в `GenGo2/delivery-contenthunter` через стандартный auto-push hook прод-репо; pm2 restart **не требуется**.
