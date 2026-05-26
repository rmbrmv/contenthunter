# 2026-05-26 — WP #147 `publish_tasks.client_publish_id`: первопричина + forward уже закрыт #108, добавлен антирегресс-гард

**Код-репо:** `GenGo2/delivery-contenthunter` `main` (autowarm, прод `/root/.openclaw/workspace-genri/autowarm`).
**Изменение:** только тест (`test_client_publish_id.test.js`) — рантайм не затронут, pm2 restart не требуется.
**Спека:** `docs/superpowers/specs/2026-05-26-wp147-cpid-forward-fix-regression-guard-design.md` (codex-clean).
**Решения Данила:** бэкфилл — НЕ делать; forward — антирегресс-гард + закрыть WP.

---

## Что было не так (по версии задачи)
`publish_tasks.client_publish_id` (cpid — связка задачи публикации со строкой `publish_queue`) часто пустой и «интермиттентно по дням»: 22.05 — 76% NULL, 19.05 — 39%, 20/23/24/25.05 — 0%. NULL cpid занижал агрегат «попытка» в очереди — первопричина бага #127 («0/12» при реально выложенных роликах). Бриф подозревал скрытый старый нестабильный путь, теряющий cpid.

## Что нашёл (read-only разведка)
Скрытого живого бага НЕТ. Интермиттентность объясняется полностью:

1. Колонка `publish_tasks.client_publish_id` **появилась только в WP #108** (миграция `f59e9f1`). До #108 связи задача↔очередь в этой таблице не было физически.
2. **Историческая интермиттентность = неполный разовый бэкфилл `d2baaf8`** (часть #108):
   ```sql
   UPDATE publish_tasks pt SET client_publish_id = pq.client_publish_id
   FROM publish_queue pq
   WHERE pq.publish_task_id = pt.id AND pt.client_publish_id IS NULL;
   ```
   Матчил только задачи, на которые очередь **всё ещё указывает**. **Перетёртые попытки ретраев** (старые `failed`, на смену которым очередь получила новую задачу) сматчить нельзя → остались NULL.
   - Дни с массой ретраев → много перетёртых → высокий NULL%. **05-15** — равномерно по IG/TT/YT (~50% каждая); **05-19** — почти весь NULL это **YouTube** (141/216), IG/TT почти чисто.
   - Тихие дни (16/17/20/21) → почти нет ретраев → 0%.
3. **Forward-путь уже закрыт #108 (`ce4429b`) и подтверждён данными:**
   - Единственные INSERT в `publish_tasks`: dispatch (`server.js:6813`) и ручной админ-эндпоинт (`server.js:2754`).
   - dispatch берёт cpid из `SELECT * FROM publish_queue → item.client_publish_id`; колонка очереди `NOT NULL DEFAULT gen_random_uuid()`.
   - Re-queue переиспользует dispatch → cpid ставится. url-poller (WP #86) задачи **не создаёт** (только UPDATE) → не источник NULL.
   - **Данные:** все **1832 NULL-строки имеют дату ≤ 2026-05-22; после деплоя — НИ ОДНОЙ.** 23–26.05 = 0% NULL при 29 активных retry-handoff-ах.
4. Ручной `POST /api/publish/tasks` (`server.js:2754`) cpid не ставит — но эти задачи создаются **без строки очереди**, линковать не к чему → cpid=NULL **семантически корректен**.

## Что сделано
1. **Антирегресс-гард** в `test_client_publish_id.test.js` (репозиторий autowarm). Файл переименован по смыслу в «cpid не теряется на пути очередь→задача»:
   - тест 1 (уточнён): `publish_queue.client_publish_id` имеет NOT NULL DEFAULT (upstream-гарантия, что `item.client_publish_id` не NULL);
   - тест 2 (новый, **source-contract**): INSERT внутри `dispatchPublishQueue` обязан нести `client_publish_id` в column-list и `item.client_publish_id` в params.
   - **Почему source-contract, а не live:** урок инцидента #108 — live-DB тест этого контроллера однажды мутировал прод (494 строки + 113 слотов). Гард статически читает `server.js`, не запускает dispatch и не пишет в БД. Зеркалит `tests/test_stats_from_filter_contract.test.js`.
2. **Бэкфилл сознательно НЕ делаем.** User-facing импакт #127 уже снят (планировщик доверяет `publish_queue.status`, `b2fa826`). Из ~1832 NULL безопасно восстановимо back-ref'ом лишь ~194; остальные ~1600 — перетёртые попытки, восстановимы только нечётким матчингом = рискованная мутация общей прод-таблицы ради косметики исторического счётчика.

## Проверка
- `node --test --test-force-exit test_client_publish_id.test.js` → **2/2 pass** на реальном `server.js`.
- Негатив-проверка (на копии в /tmp, прод не тронут): убрал `client_publish_id` из dispatch-INSERT → гард **краснеет**, как и задумано. Прод `server.js` не изменялся.

## Что осталось
- Ничего по коду. Расследование интермиттентности завершено (корень доказан, не живой баг).
- Будущим деплоям ничего не грозит: dispatch ставит cpid, гард ловит регрессию column-list.
