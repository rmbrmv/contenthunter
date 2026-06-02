# WP#216 — Заморозка неактивных клиентов в пайплайне: Evidence

**Дата:** 2026-06-02
**Задача:** OpenProject #216 «проверить откуда появился отключенный клиент в ручной выкладке»
**Ветка (код):** `wp216-inactive-project-gate` в репозитории `delivery-contenthunter` (рабочая копия `/home/claude-user/autowarm-testbench`)
**Спека:** `docs/superpowers/specs/2026-06-02-wp216-inactive-project-pipeline-gate-design.md`
**План:** `docs/superpowers/plans/2026-06-02-wp216-inactive-project-pipeline-gate.md`

## Root cause (подтверждён данными прода)

Клиент **Септизим** (`validator_projects` id=83): `active=false` (неактивен) И `manual_publish=false`
(Автовыкладка). 29 строк в ручной очереди оператора попали туда **не через наполнитель**
(у всех 379 слотов и у проекта `manual_publish=false` → предикат наполнителя ложен), а через
**retry-handoff упавшей авто-выкладки** (`retry_controller.js → handoffToManual`): все 29
`unic_result_id` совпали с failed-строками `publish_queue` (55 failed / 207 pending), `manual_handoff_at`
проставлен 25 строкам 01.06 + 4 строкам 02.06.

**Дыра:** `validator_projects.active` не проверялся НИГДЕ в контент-пайплайне. Клиента
деактивировали, но in-flight работа (unic → авто-публикация → retry → handoff в ручную)
продолжала течь.

## Решение (Подход A, согласовано с Данилом): полная заморозка + очистка

Единый модуль-предикат `project_active_filter.js` + гейт во всех точках пайплайна и mutation-эндпоинтах +
разовая очистка накопленного. Kill-switch `INACTIVE_PROJECT_GATE_ENABLED` (default ON) — мгновенный откат.

### Семантика гейта

`activeProjectSql(alias)` → `(<alias>.active IS NOT FALSE)` когда ON, `'TRUE'` когда OFF.
**Морозим только ЯВНО неактивных** (`active=false`); NULL/unknown/orphan проходит — чтобы не
стрэндить активную/legacy работу. Гейт keys off **слот-резолвленного проекта**
(`COALESCE(slot.project_id, task.project_id)`) в ассайнерах, который сохраняется в
`publish_queue`/`validator_manual_publish_queue` → downstream-гейты видят тот же проект.

### Точки гейта (6) + mutation-эндпоинты

| Файл | Что |
|------|-----|
| `run_auto_unic.js` | генератор уникализации не создаёт задачи неактивного проекта (LEFT JOIN на content.project_id) |
| `assign_candidates.js` | авто-диспатч кандидатов: гейт по `COALESCE(slot,task)` проекту, он же возвращается/сохраняется |
| `retry_controller.js` | retry-цикл фильтрует неактивных в SQL **до LIMIT 200** (ни requeue, ни handoff) |
| `manual_queue_assign.js` | наполнитель ручной очереди: гейт по слот-проекту `p`, он же сохраняется |
| `manual_publish_queue.js listQueue` | оператор не видит строк неактивных (КРОМЕ `in_progress` — дозавершить начатое) |
| `server.js dispatchPublishQueue` | диспетчер публикаций не берёт `pending` неактивных (до LIMIT) |
| `manual_publish_queue.js takeItem/takeGroup` | нельзя ВЗЯТЬ queued-строку замороженного проекта (понятная 409) |
| `manual_publish_queue.js returnItem/returnGroup` | возврат in_progress замороженного → cancel (не скрытый лимб) |
| `server.js POST /api/publish/queue/manual` | отклоняет постановку, если неактивен пак ИЛИ resolved-проект (409) |

### Разовая очистка `cleanup_wp216_inactive_project_queue.js`

Идемпотентна, default dry-run, `--apply`, `--onlyProject=<id>` (изоляция). Для `active=false`:
ручная очередь `queued` → `cancelled_at` (in_progress/published не трогаем); `publish_queue` `pending`
→ `cancelled`. На момент диагностики Септизим: ~30 ручных queued + ~204 pending.

## Тесты

- `test_project_active_filter.test.js` — unit предиката + kill-switch + `projectNotFrozenSql`.
- `test_wp216_inactive_gate.test.js` — фикстуры (active/inactive-auto/inactive-manual) + contract/behavioral
  тесты всех гейтов и mutation (take/return/dispatch/list/retry/populator/unic), каждый с gate-ON/OFF.
- `test_cleanup_wp216_live.test.js` — dry-run/apply/идемпотентность/изоляция (scoped onlyProjects).
- Финальный прогон: **48/48 PASS** (WP216 + регресс `test_manual_publish_queue`/`test_retry_decision`/`test_client_manual_publish`).
- `node --check server.js` / `manual_publish_queue.js` — OK.

## Codex review — 11 раундов, сходимость

Прогнали `codex review` 11 раз, итеративно закрывая находки. Закрыто: P1 retry-starvation (фильтр в SQL до
LIMIT); P2 in_progress-видимость; P1b диспетчер (6-й гейт); P2c/round-10 источник project_id (слот-резолв);
takeGroup preempt-no-op; manual-enqueue для неактивного пака; return→скрытый лимб; mismatched pack/result.

**Решение об остановке (round-11):** оставшиеся замечания просят заменить денормализованный `project_id`
(в `publish_queue`/`validator_manual_publish_queue`) на слот-джойны во ВСЕХ read/cleanup-путях
(retry/dispatch/listQueue/cleanup). Это:
1. **Противоречит** более раннему round-6 (codex flip-flop: тогда требовал гейтить по `ut.project_id`, не по слоту).
2. Защищает **несуществующее** состояние: эмпирически **0** NULL/stale `project_id` в гейтируемых состояниях
   (проверка: 0 pending-null/stale, 0 failed-no-handoff-null/stale, 0 active-manual-null; 0/517 расхождений
   `ut.project_id` vs `slot.project_id`).
3. **Инвариант на write-стороне** предотвращает новые: `run_auto_unic` пишет `project_id` из `content.project_id`
   (NOT NULL); ассайнеры (round-10) сохраняют **слот-резолвленный** `COALESCE(slot,task)`; manual-эндпоинт
   бэкфилит из пака. Значит все новые строки несут авторитетный slot-проект.
4. Денормализованный `project_id` — намеренный дизайн (хранится, чтобы read-пути не ре-деривили через
   3-table join на каждом тике).

Per receiving-code-review (проверять, не реализовывать слепо): дальнейший слот-джойн в каждом read-пути —
вне scope (рефактор ради несуществующего состояния, против денормализации). Зафиксировано как осознанное
инженерное решение. Если в будущем появятся stale-строки — kill-switch + cleanup `--apply` покрывают.

## Деплой (за Данилом, вне TDD-цикла)

1. Код: `cd /root/.openclaw/workspace-genri/autowarm && git pull` (autowarm = delivery-contenthunter; каталог под claude-user).
2. Рестарт: `sudo pm2 restart` server.js (id35) + связанные cron-процессы (читают env/модули на старте).
3. Очистка: `node cleanup_wp216_inactive_project_queue.js` (dry-run, сверить ~30 ручных + ~204 pending), затем `--apply`.
4. Verify: в UI ручной выкладки строк Септизима нет; `SELECT count(*) FROM validator_manual_publish_queue WHERE project_id=83 AND cancelled_at IS NULL` = 0.
5. Откат: `INACTIVE_PROJECT_GATE_ENABLED=false` + рестарт. Миграций БД нет.

## Коммиты ветки (delivery-contenthunter `wp216-inactive-project-gate`)

14 функциональных + фиксы по codex (project_active_filter, 6 гейтов, cleanup, 11 раундов review-фиксов).
Файлы: `project_active_filter.js`, `run_auto_unic.js`, `assign_candidates.js`, `retry_controller.js`,
`manual_queue_assign.js`, `manual_publish_queue.js`, `server.js`, `cleanup_wp216_inactive_project_queue.js`
+ 3 тест-файла.
