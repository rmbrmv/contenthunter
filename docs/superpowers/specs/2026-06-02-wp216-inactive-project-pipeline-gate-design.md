# WP#216 — Заморозка неактивных клиентов в пайплайне выкладки

**Дата:** 2026-06-02
**Задача OpenProject:** #216 «проверить откуда появился отключенный клиент в ручной выкладке»
**Тип:** Ошибка
**Репозиторий кода:** `delivery-contenthunter` (autowarm); прод-каталог `/root/.openclaw/workspace-genri/autowarm`
**Ветка:** `wp216-disabled-client-manual-queue`

## Что было не так (root cause)

Клиент **Септизим** (`validator_projects` id=83) имеет `active=false` (неактивен) и
`manual_publish=false` (тип выкладки = «Автовыкладка»). То есть клиент **выключен** и
**не ручной**. Тем не менее в ручной выкладке оператора появилось 29 строк
(`validator_manual_publish_queue`, все `operator_status='queued'`).

Происхождение строк подтверждено данными прода:

- Все 379 слотов проекта 83 имеют `manual_publish=false`, проект тоже
  `manual_publish=false` → предикат наполнителя `effectiveManualSql`
  (`slot.manual_publish OR project.manual_publish`) для них **ложен**. Значит строки
  пришли **не через наполнитель** `assignManualPublishQueue`.
- Все 29 `unic_result_id` ручной очереди совпадают с failed-строками авто-тракта
  (`publish_queue`, project 83: 55 failed, 207 pending). Строки попали в ручную через
  **retry-handoff** (`retry_controller.js → handoffToManual`): `manual_handoff_at`
  проставлен 25 строкам 01.06 и 4 строкам 02.06.

Цепочка: клиент когда-то был активен → `run_auto_unic` нагенерил `unic_tasks` для его
filled+approved слотов → авто-выкладка падала → клиента деактивировали, но **in-flight
работа осталась** → `retry_controller` по исчерпании окна ретраев сдал упавшие задачи в
ручную очередь.

**Корневая дыра:** ни `run_auto_unic.js`, ни авто-диспатч (`assign_candidates.js`), ни
`retry_controller.js`, ни наполнитель ручной очереди не проверяют
`validator_projects.active`. Колонка `active` существует и используется в других местах
(`approval_notify.js`, девайсы `fdn.active`), но в контент-пайплайне игнорируется.

**Бласт-радиус:** на момент диагностики затронут только проект 83 (других неактивных
проектов со строками в ручной очереди нет).

## Решение по поведению (согласовано)

- При `active=false` клиент **полностью заморожен**: не генерится unic, не диспатчится
  авто, не сдаётся в ручную, не показывается в очереди оператора.
- Уже накопившееся чистим **в рамках этой задачи** (29 фантомных строк ручной очереди +
  207 pending авто-задач).

## Архитектура фикса (Подход A — слоёный гейт + разовая очистка)

Повторяет принятый в репо паттерн single-source SQL-predicate + kill-switch + TDD
(как `client_manual_filter.js`).

### 1. Общий модуль-предикат `project_active_filter.js`

```js
// Kill-switch: INACTIVE_PROJECT_GATE_ENABLED=false возвращает до-WP#216 поведение
function projectGateEnabled() {
  return process.env.INACTIVE_PROJECT_GATE_ENABLED !== 'false';
}

// SQL-фрагмент. projAlias = алиас validator_projects (caller (LEFT) JOIN-ит его).
// Гейт выключен → 'TRUE' (no-op, LEFT JOIN можно не трогать).
function activeProjectSql(projAlias) {
  return projectGateEnabled() ? `(${projAlias}.active = true)` : 'TRUE';
}

// Точечная проверка для не-SQL путей (retry-handoff). db = pg Pool|client.
// Гейт выключен → всегда true. Проект не найден → трактуем как НЕ активный (fail-closed).
async function projectIsActive(db, projectId) {
  if (!projectGateEnabled()) return true;
  if (!projectId) return false;
  const { rows } = await db.query(
    'SELECT active FROM validator_projects WHERE id = $1', [projectId]);
  return rows.length > 0 && rows[0].active === true;
}

module.exports = { projectGateEnabled, activeProjectSql, projectIsActive };
```

### 2. Гейт в 5 точках утечки

| # | Файл | Изменение |
|---|------|-----------|
| 1 | `run_auto_unic.js` | `JOIN validator_projects vp ON vp.id = c.project_id` + `AND ${activeProjectSql('vp')}` в SELECT слотов |
| 2 | `assign_candidates.js` (`selectAssignCandidates`) | в подзапросе слота (уже `LEFT JOIN validator_projects p`) добавить `AND ${activeProjectSql('p')}` |
| 3 | `retry_controller.js` | в ретрай-цикле перед решением requeue/handoff: `if (!await projectIsActive(pool, r.project_id)) → skip` (ни requeue, ни handoff; строка остаётся failed, добивает чистка) |
| 4 | `manual_queue_assign.js` (`assignManualPublishQueue`) | `AND ${activeProjectSql('p')}` в основной SELECT (уже `LEFT JOIN validator_projects p`) — defense-in-depth |
| 5 | `manual_publish_queue.js` (`listQueue` / `JOINED_SELECT`) | `JOIN validator_projects vp ON vp.id = q.project_id` + `AND ${activeProjectSql('vp')}` — оператор не видит строк неактивных проектов |

Все пять используют один модуль и один рубильник `INACTIVE_PROJECT_GATE_ENABLED`.

### 3. Разовая очистка `cleanup_wp216_inactive_project_queue.js`

По образцу `cleanup_wp148_manual_queue_dups.js` / `cleanup_wp155_manual_queue_overdue.js`:
идемпотентный, флаг `--dry-run`, подробные counts в лог. Для всех проектов с
`active=false`:

- **Ручная очередь:** `UPDATE validator_manual_publish_queue SET cancelled_at=now(),
  updated_at=now() WHERE cancelled_at IS NULL AND operator_status IN ('queued','in_progress')
  AND project_id IN (SELECT id FROM validator_projects WHERE active=false)`.
  Терминальные (`published`) **не трогаем**.
- **Авто-тракт:** `UPDATE publish_queue SET status='cancelled', updated_at=now()
  WHERE status='pending' AND project_id IN (... active=false)`.
  Это источник churn (207 строк у Септизима). Failed/done/cancelled не трогаем.

Запуск — разовый из прод-каталога, не cron.

### 4. Тесты (TDD, обязательно до реализации)

- **unit `test_project_active_filter.test.js`:** `activeProjectSql` on/off; `projectIsActive`
  для active / inactive / отсутствующего проекта / при выключенном гейте.
- **интеграционные** (по образцу `test_client_manual_publish.test.js`, live-БД): неактивный
  проект не проходит каждую из 5 точек; активный — проходит без изменений.
- **тест очистки** (по образцу `test_cleanup_wp155_overdue_live.test.js`): идемпотентность
  (повторный прогон — 0 изменений), отменяются только неактивные, терминальные строки не
  трогаются, активные проекты не затронуты.

### 5. Краевые случаи

- **Ре-активация:** гейт переоценивается каждым тиком cron (`run_auto_unic`,
  `assignUnicResultsToQueue` каждые 30 мин) — клиент возобновляется автоматически.
  Отменённые при очистке строки не воскресают (`cancelled_at` + партиал-индекс
  `ON CONFLICT WHERE cancelled_at IS NULL` допускает честный повторный enqueue).
- **Производительность:** каждый гейт — дешёвый JOIN по PK `validator_projects.id`.
- **Откат:** `INACTIVE_PROJECT_GATE_ENABLED=false` мгновенно возвращает старое поведение
  без редеплоя.
- **fail-closed:** `projectIsActive` для несуществующего/NULL project_id возвращает
  `false` — лучше перестраховаться, чем пропустить осиротевшую строку.

## Вне scope (follow-up)

- **Каскад по событию деактивации** (Подход C): повесить атомарную отмену in-flight на
  админ-тоггл «Неактивен» в репозитории `validator-contenthunter`. Чище семантически, но
  трогает второй репозиторий; гейт из A покрывает повторные прогоны и ре-активацию.
  Вынести отдельной задачей.

## Деплой

- Код: `git pull` в `/root/.openclaw/workspace-genri/autowarm`. PM2-рестарт нужен для
  long-running процессов (server.js id35, croны) — уточнить при выполнении: cron-функции
  читают env на старте процесса, новые модули требуют рестарта процесса.
- Разовая очистка: запустить скрипт вручную после деплоя кода (сначала `--dry-run`).
- Миграции БД нет (новых колонок не добавляем).
