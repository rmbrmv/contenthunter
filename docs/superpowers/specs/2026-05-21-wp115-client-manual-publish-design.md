# WP #115 — Признак ручной выкладки на уровне клиента — Design Spec

- **Дата:** 2026-05-21
- **OpenProject:** WP #115 «добавить признак ручной выкладки клиенту» (тип «Задача», автор Анастасия, assignee Данил)
- **Ветка (docs):** `docs/wp115-client-manual-publish-flag-2026-05-21`
- **Базируется на:** WP #85 (послотовый флаг `manual_publish` + матчер) и WP #107 (очередь ручной выкладки)

## 1. Постановка задачи

В справочнике «Клиенты» (https://client.contenthunter.ru/clients) добавить глобальный признак типа выкладки на уровне клиента:

- **«Ручная выкладка»** — весь контент клиента из планировщика проходит уникализатор и передаётся в ручную выкладку (очередь WP #107).
- **«Автовыкладка»** (по умолчанию) — стандартный путь: планировщик → уникализатор → автовыкладка. При этом, если **конкретный слот** помечен послотовым признаком «Ручная выкладка» (WP #85), этот контент уходит в ручную выкладку, а не в авто.

То есть клиентский флаг — это глобальный дефолт того же признака, что WP #85 ввела на уровне слота.

## 2. Решения, согласованные с заказчиком

1. **Ретроактивность (переключение в «Ручную»):** неопубликованный контент клиента, уже стоящий в авто-очереди, **отзывается** из авто и перенаправляется в ручную выкладку (то же поведение, что у послотового тумблера WP #85). Уже опубликованное не трогаем.
2. **Без исключений в ручном режиме:** клиент «Ручная» = весь контент вручную. Двухзначная логика, послотовый тумблер при ручном клиенте просто не влияет (всё и так вручную). Никаких per-slot «авто-исключений» у ручного клиента (в задаче описан только переход авто-клиент → ручной-слот, не наоборот).
3. **RBAC:** менять тип выкладки клиента может **только админ**. Менеджер видит значение (read-only). Клиент (role=client) страницу `/clients` не видит вовсе.

## 3. Ключевая модель данных (как есть в коде)

- **«Клиент» = проект.** Отдельной таблицы клиентов нет. Страница `/clients` (`frontend/src/pages/admin/ProjectsPage.vue`, маршрут `router/index.ts:24`, роли `['admin','manager']`) показывает строки таблицы **`validator_projects`** (доступ через сырой SQL, ORM-модели у таблицы нет). У клиент-пользователя один `validator_users.project_id`.
- **Связь со слотами:** `validator_schedule_slots.project_id` → `validator_projects.id` (integer; `models/schedule.py:27`).
- **Прецедент per-project настроек:** простые скалярные колонки в `validator_projects` (`onboarding_stage`, `manager`, `plan_*`, `contract_*`) — добавляем ещё одну тем же способом.

### Единственная точка решения «авто vs ручная»

Сейчас это булев `validator_schedule_slots.manual_publish` (`models/schedule.py:34`). Читается ровно в 3 SQL-местах autowarm:

| # | Место | Файл:строка | Текущее условие |
|---|-------|-------------|-----------------|
| 1 | Авто-наполнитель `assignUnicResultsToQueue` | `server.js:5992-5996` | `NOT EXISTS (… vss.manual_publish = true)` (исключает ручные) |
| 2 | Ручной наполнитель `assignManualPublishQueue` | `manual_queue_assign.js:16-32` | `WHERE vss.manual_publish = true` (включает ручные) |
| 3 | Матчер `runSlotMatcher` | `slot_matcher_cron.js:60` | `(s.manual_publish = true OR s.status = 'published')` |

Все три анкерятся (или могут анкериться) на слот, у которого есть `project_id`.

## 4. Выбранная архитектура — Вариант A: вычислять «эффективную ручную» на лету

Колонка на уровне проекта = **единый источник правды**. Слоты НЕ мутируем. Определяем предикат:

```
effective_manual(slot) = slot.manual_publish OR project.manual_publish
```

Наполнители пересчитывают каждые ~30 мин, поэтому и новый, и существующий контент автоматически следует флагу клиента — без каскадной мутации слотов и без бухгалтерии «кто проставил флаг».

**Отвергнутый Вариант B** (каскадом проставлять `manual_publish=true` на все слоты клиента): требует признак «проставлено каскадом vs вручную» (иначе откат затирает реальные послотовые тумблеры), отдельного наследования для новых слотов, борьбы с гонками — дублирование состояния, рассадник багов.

## 5. Схема — миграция 007 (validator backend)

Цепляется за `006_wp107_manual_publish_queue` (текущий head в `backend/alembic/versions/`).

```sql
ALTER TABLE validator_projects
  ADD COLUMN IF NOT EXISTS manual_publish boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS manual_publish_set_by_id integer NULL REFERENCES validator_users(id),
  ADD COLUMN IF NOT EXISTS manual_publish_set_at timestamp with time zone NULL;
```

- `manual_publish = true` → клиент на «Ручной выкладке».
- Дефолт `false` → все существующие клиенты остаются на автовыкладке, поведение не меняется (безопасный rollout).
- `set_by_id` / `set_at` — аудит, зеркало послотовых полей WP #85.
- Индекс не нужен: `validator_projects` — маленькая таблица.

## 6. Изменения в autowarm (3 SQL-места)

Во всех трёх местах добавляем учёт клиентского флага через join к `validator_projects` по `slot.project_id` (надёжный integer-FK). **`unic_tasks.project_id` НЕ используем** — там строковый идентификатор/имя проекта, матчер для связи с `validator_projects` ходит по имени (`slot_matcher_cron.js`: `vp.project = fra.project`).

1. **`assignUnicResultsToQueue` (`server.js`):** расширить guard-подзапрос —
   ```sql
   NOT EXISTS (
     SELECT 1 FROM validator_schedule_slots vss
     LEFT JOIN validator_projects p ON p.id = vss.project_id
     WHERE vss.id = (ut.meta->>'slot_id')::int
       AND (vss.manual_publish = true OR p.manual_publish = true)
   )
   ```
2. **`assignManualPublishQueue` (`manual_queue_assign.js`):** join `validator_projects p ON p.id = vss.project_id`, условие → `WHERE (vss.manual_publish = true OR p.manual_publish = true)`.
3. **`runSlotMatcher` (`slot_matcher_cron.js`):** в финальном `SELECT` join (или CTE `account_projects` уже несёт `vp.id`) → условие `(s.manual_publish = true OR p.manual_publish = true OR s.status = 'published')`.

**Kill-switch:** env `CLIENT_MANUAL_PUBLISH_ENABLED` (default `true`). При `false` все три места игнорируют `p.manual_publish` (откат на чисто послотовое поведение WP #85 без передеплоя валидатора). Реализация: ветвление SQL по флагу или включение `p.manual_publish = true` только когда флаг включён.

DB-pool autowarm: жёстко `openclaw/openclaw123@localhost:5432/openclaw` (`server.js:171-177`) — общий с валидатором, дополнительной конфигурации не требует.

## 7. Backend валидатора — эндпоинт и сервис

### Эндпоинт
`PATCH /api/projects/{project_id}/publish-mode` (новый, в `backend/src/routers/projects.py`), `dependencies=[Depends(require_role(UserRole.admin))]` (`dependencies.py:35-43`). Body (Pydantic): `{ "manual_publish": bool }`. Ответ: новое состояние + статистика отозванного/перемещённого.

Сама запись и каскад — в новой сервис-функции `apply_client_publish_mode(db, project_id, manual_publish, user_id)` (в `services/manual_publish_service.py`), всё в **одной транзакции**, с записью `manual_publish_set_by_id` / `manual_publish_set_at` и идемпотентностью (no-op, если значение не меняется).

### Каскад при переключении (ретроактивно)

- **Авто → Ручная:** для всех слотов проекта с контентом, ещё **не** опубликованным, отменяем pending авто-путь. Базовый примитив — `cancel_downstream_for_content(db, content_id, keep_slot_id=slot_id, reason='client_manual_enabled')` (`services/pipeline_reversal.py:42-149`), он уже отменяет pending `publish_queue` + `unic_tasks` по контенту. Для проекта это применяется ко всем его «живым» слотам.
  - *Деталь реализации (решить на этапе плана, прочитав `pipeline_reversal.py`):* цикл по контенту проекта vs set-based bulk-SQL с теми же эффектами. Предпочтительно set-based (один UPDATE по проекту), т.к. у клиента могут быть сотни слотов. Семантика обязана совпадать с per-slot WP #85.
  - После отмены ручной наполнитель сам подхватит контент (`effective_manual` теперь true) на следующем тике; опционально дёрнуть `assignManualPublishQueue` сразу не нужно — достаточно тика.
- **Ручная → Авто:** отменяем ещё-не-взятые строки ручной очереди клиента **только для слотов, где `slot.manual_publish = false`** (они были ручными исключительно из-за клиента). Зеркало `cancel_queued_for_slot` (`manual_publish_service.py:177-191`), но scope = проект, фильтр `operator_status='queued' AND cancelled_at IS NULL` и подзапрос «слот не помечен ручным послотово»:
  ```sql
  UPDATE validator_manual_publish_queue q
  SET cancelled_at = now(), updated_at = now()
  WHERE q.operator_status = 'queued' AND q.cancelled_at IS NULL
    AND q.slot_id IN (
      SELECT vss.id FROM validator_schedule_slots vss
      WHERE vss.project_id = :project_id AND vss.manual_publish = false
    )
  ```
  «В работе»/опубликованные строки сохраняем (история). Слоты с `slot.manual_publish=true` остаются в ручной очереди (их послотовый флаг по-прежнему действует). Авто-наполнитель возобновит отменённые на следующем тике.

### Сериализатор слота (опционально, для бейджей в календаре)
В `_slot_to_dict` (`services/schedule_service.py:214-256`, admin-only ветка 243-255) добавить вычисляемое `effective_manual_publish = slot.manual_publish OR project.manual_publish`. Требует, чтобы вызывающий код знал `project.manual_publish` (передать в сериализатор или подгрузить join'ом). Поле admin-only, как и остальные `manual_*`.

## 8. Frontend — страница `/clients` (`ProjectsPage.vue`)

- Новая колонка **«Тип выкладки»** в таблице клиентов:
  - бейдж `🤖 Автовыкладка` (нейтральный) / `✋ Ручная выкладка` (фиолетовый, в тон WP #85);
  - **админ** — кликабельный тумблер, дергает `api.patch('/projects/{id}/publish-mode', { manual_publish })` (axios-singleton `api/client.ts` с JWT);
  - **менеджер** — только бейдж, без кнопки (`v-if="auth.isAdmin"` для интерактива; `auth.isAdmin` — `stores/auth.ts:24`).
- При переключении в «Ручную» — модалка-подтверждение: «Весь неопубликованный контент клиента будет перенаправлен в ручную выкладку. Продолжить?» (действие ретроактивное и массовое). Переключение обратно в «Авто» — без обязательной модалки (или мягкое подтверждение).
- После успеха — обновить строку (показать новое значение + кол-во перемещённых, если вернёт API).
- (Опц.) В календаре/слотах: если добавили `effective_manual_publish`, бейдж «вручную» на `SlotCard.vue` зажигается и для слотов ручного клиента — чтобы оператор/админ видел причину. Минимально-необходимое для задачи — только колонка на `/clients`; календарные бейджи — приятное дополнение.

## 9. RBAC (тройная защита, как в WP #85)

- Backend: `require_role(UserRole.admin)` на эндпоинте publish-mode.
- Сериализация проекта: `manual_publish` отдаётся в `GET /api/projects` всем, кто имеет доступ к странице (admin+manager) — для отображения бейджа. Менять — только админ (эндпоинт). Клиентам (role=client) страница недоступна по маршруту.
- Frontend: интерактивный тумблер под `v-if="auth.isAdmin"`; менеджер видит read-only бейдж.

## 10. Kill-switches

- **autowarm** env `CLIENT_MANUAL_PUBLISH_ENABLED=false` — наполнители/матчер игнорируют клиентский флаг (откат на послотовое поведение WP #85). Без передеплоя валидатора.
- **validator** env `MANUAL_PUBLISH_TOGGLE_ENABLED=false` (уже есть для послотового тумблера WP #85) — расширяем/добавляем гейт и для клиентского publish-mode эндпоинта (блокировать новые переключения).
- Существующий `MANUAL_QUEUE_POPULATE_ENABLED` (autowarm) продолжает работать как общий стоп ручного наполнителя.

> ⚠️ **Согласованность kill-switch'ей (важно для эксплуатации).** Валидаторный эндпоинт НЕ читает autowarm-env `CLIENT_MANUAL_PUBLISH_ENABLED`. Если выключить `CLIENT_MANUAL_PUBLISH_ENABLED=false` в autowarm, но оставить валидаторный тумблер включённым и перевести клиента в «Ручную» — валидатор отменит pending авто-контент, а autowarm проигнорирует клиентский флаг (контент не попадёт ни в авто, ни в ручную очередь → застрянет, починка только через БД). **Правило эксплуатации:** выключая `CLIENT_MANUAL_PUBLISH_ENABLED`, одновременно выставляй `MANUAL_PUBLISH_TOGGLE_ENABLED=false` на валидаторе (блокирует новые переключения), а уже-ручных клиентов сначала верни в «Авто». Найдено финальным холистическим ревью; код-гейт между репозиториями признан непропорциональным — фиксируем как runbook-правило.

## 11. Тесты

- **Backend pytest:**
  - `apply_client_publish_mode`: переключение Авто→Ручная отзывает pending авто-контент проекта; Ручная→Авто отменяет только `queued`-строки слотов с `slot.manual_publish=false`, не трогает послотово-ручные и in_progress/published; идемпотентность (повторный PATCH тем же значением — no-op); запись set_by/set_at.
  - RBAC: 403 для не-админа.
  - Live-DB (с фикстурой `engine.dispose`, см. практику валидатора).
  - Миграция применяется/откатывается.
- **autowarm `node --test`:** для всех 3 SQL-мест — слот авто-клиента с `slot.manual_publish=false`, но `project.manual_publish=true`, классифицируется как ручной (исключён из авто, включён в ручную, виден матчеру); `CLIENT_MANUAL_PUBLISH_ENABLED=false` возвращает старое поведение.
- **frontend Vitest:** колонка рендерит правильный бейдж по `manual_publish`; тумблер виден только админу; менеджер — read-only; модалка подтверждения при включении «Ручной».
- **E2E smoke** на testbench: реальный проект → переключить в «Ручную» через API → убедиться, что pending авто-строки отменены и слоты попадают в `validator_manual_publish_queue`; вернуть в «Авто» → `queued`-строки клиента (для не-послотово-ручных слотов) отменены.

## 12. Деплой

Порядок (передать Данилу):
1. **Validator backend:** `git pull` в prod-чекаут → `alembic upgrade head` (миграция 007 добавит колонки) → перезапуск (PM2 `validator`, id=24).
2. **Validator frontend:** `npm run build` (postbuild автодеплой в `/var/www/validator/`).
3. **autowarm:** `git pull` → `pm2 restart autowarm` (подхватит обновлённые SQL-места + новый env-флаг).
4. Проверить env-флаги (по умолчанию всё включено; `CLIENT_MANUAL_PUBLISH_ENABLED` можно не задавать).

**Зависимость/риск (проверить на проде ДО деплоя #115):** клиентский флаг полезен, только если ручной путь реально работает. По памяти WP #107, в prod-autowarm (`63408f2`) `assignManualPublishQueue` мог быть **не подключён** в шедулер (определён+тестирован, но не вызывался) — в dev-чекауте подключён (`server.js:6247-6249`). Если в проде не подключён, контент ручного клиента (как и послотово-ручной) не дойдёт до очереди. Это деплой-зависимость WP #107, но #115 её усиливает (затрагивает весь контент клиента). Свериться с прод-`server.js` перед раскаткой.

## 13. Non-goals / YAGNI

- Третий режим выкладки (только «Авто»/«Ручная»). Если позже понадобится — мигрировать boolean → enum.
- Per-slot «авто-исключения» у ручного клиента (решение #2: нет).
- Откат `matched_*` истории при rework (наследуем известное ограничение WP #107).
- Изменение того, ГДЕ живёт UI очереди WP #107 (валидатор vs delivery-дашборд) — вне scope #115; #115 трогает только страницу `/clients` и 3 SQL-места.

## 14. Открытые вопросы

- Точная реализация bulk-каскада Авто→Ручная (цикл по `cancel_downstream_for_content` vs set-based SQL) — решается на этапе плана после чтения `pipeline_reversal.py`. На дизайн не влияет.
