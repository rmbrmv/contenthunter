# WP #154 — Контент застревает после переноса слота: re-queue gap в популяторе delivery

- **Дата:** 2026-05-26
- **Ветка:** `wp154-enoty-requeue-on-reschedule`
- **Тип:** диагностика данных (read-only) → код-фикс (delivery / autowarm) + операционная разблокировка
- **БД:** `psql -h localhost -U openclaw -d openclaw`
- **Репозиторий фикса:** `GenGo2/delivery-contenthunter` (прод `/root/.openclaw/workspace-genri/autowarm/`, ветка main; авто-пуш post-commit)
- **Связано:** WP #72 (паттерн «клиент перестал публиковаться»), Spec B «pipeline reversal», Spec A «past-slot clamp», WP #148 (per-account dedup)

---

## 1. Жалоба (из WP #154)

- **«Еноты по полкам» (project_id=107)** — с 23.05 «висят в планировщике», в «Опубликовано» последние записи только от 22.05.
- **«Эль-косметик» (project_id=82)** — 25.05 «даже не пытался» выложиться; Аня вручную перенесла публикацию на другой день.

## 2. Что показала разведка (прод, read-only)

### 2.1 Премиса брифа (паттерн WP #72 = встала генерация) — ОПРОВЕРГНУТА
У обоих проектов уникализация здорова: все `unic_tasks` = `done`, ноль `error_message`.
Контент на будущие слоты сгенерирован (Эль — слот 27.05; Еноты — слоты 26–30.05, `content_id` 2328–2332).
Это НЕ класс Anecole/SVG (там генерация падала в FFmpeg). Стадия застревания — **ниже по конвейеру**.

### 2.2 Общий механизм: перенос слота менеджером
`validator_users.id=7 = anna` (admin) — та самая «Аня» из жалобы. Она переносит слоты в планировщике.
Перенос слота вызывает `schedule.py` → `update_downstream_dates_for_content` (Spec B), который:
1. **отменяет** pending-строки `publish_queue` (`status='cancelled', skip_reason='moved_from_slot_<src>_to_<dst>'`);
2. **переадресует** `unic_tasks.slot_date` + `meta.slot_id` на новый слот (НЕ cancel);
3. после commit вызывает `notify_content_approved(content_id)`, чтобы delivery-популятор пере-поставил контент в очередь на новую дату.

### 2.3 Эль-косметик (82) — ШТАТНОЕ ПОВЕДЕНИЕ, не баг
Перенос Ани на 27.05 **сработал**: `publish_queue` содержит 9 строк `pending` на 27.05 (созданы 25.05 06:09).
Контент опубликуется. Жалоба «25.05 не выложился» = ожидаемое следствие ручного переноса.
(Отдельно: у Эль есть ещё 6 «застрявших» результатов от того же бага — см. §2.5; они тоже восстановятся фиксом.)

### 2.4 Еноты по полкам (107) — РЕАЛЬНЫЙ БАГ застревания
22.05 Аня очистила слоты 23/24/25.05 и сдвинула контент вперёд на 26–30.05.
Старые строки очереди отменились (`moved_from_slot_*`), `unic_tasks` корректно переадресованы
(проверено: content 2330→slot 22824/29.05, 2331→22819/27.05, 2332→22821/28.05; `task_slot_date == cur_slot_date`,
все `filled`, `manual_publish=f`). НО **destination-слоты так и не пере-поставились в очередь** — ни одной
живой строки `publish_queue` после 22.05.

Прямое подтверждение: для каждого `unic_result` контента 2328–2332 — `result_status='done'`, и **только** строки
`publish_queue` со `status='cancelled'` и `skip_reason LIKE 'moved_from_slot%'`. Живых строк нет.
(Слот 26.05 = `manual_publish=t` — намеренно ручной, не баг; 27–30.05 = auto, должны были пере-поставиться.)

### 2.5 Первопричина (код)
Популятор `assignUnicResultsToQueue` (`server.js`, секция «КРОН: unic_results → publish_queue», ~6239)
отбирает кандидатов через **status-слепой** дедуп (`server.js:6260-6262`):

```sql
WHERE ur.status IN ('ready','done')
  AND NOT EXISTS (SELECT 1 FROM publish_queue pq WHERE pq.unic_result_id = ur.id)
  AND NOT EXISTS (... manual-slot guard ...)
```

`NOT EXISTS (... unic_result_id = ur.id)` срабатывает на **любой** строке, включая `cancelled`.
После переноса слота отменённая строка остаётся → результат считается «уже назначенным» → **никогда не пере-ставится**.
Контент навсегда зависает в filled-слоте.

Подтверждающие факты, что это именно дыра дедупа (а не задумка):
- **Per-account дедуп в том же файле УЖЕ status-aware** (`server.js:6479`): `pq.status NOT IN ('cancelled','skipped')`.
  Верхнеуровневый кандидатный дедуп с ним рассогласован — он и есть баг.
- **Намеренный супрессор удалённого контента — это D3 lineage-guard, а не дедуп.** Комментарий валидатора
  `pipeline_reversal.py:58-60`: после отмены «D3 assign-guard поймает результаты и пропустит INSERT».
  То есть подавление повторной вставки для случая «контент удалили из слота» должно приходить из
  `checkAssignQueueSlotLineage` (`server.js:6031`, проверяет «слот всё ещё filled этим content на эту дату»),
  а не из status-слепого дедупа. Дедуп — избыточный shortcut, который заодно убивает легитимный re-queue после переноса.

### 2.6 Blast radius (систематический баг, не один клиент)
«Застрявшие» результаты = `done/ready` + есть только move-cancelled строка + нет живой строки:
**~323 результата по 14 проектам** (ClickPay 96, Content hunter 56, Септизим 51, AXILOR 24, Еноты 20,
Ткаченко 16, Relisme 13, Forsal 12, Orakul 12, Ambassadori 7, Эль 6, Екатерина 4, Feminista 3, Сваровски 3).

Фикс auto-восстанавливает каждый случай ПРАВИЛЬНО (через существующие гарды):
- **future + filled + auto** → пере-ставится (клиенты возобновят выкладку). Еноты: 16 из 20 (4 — manual-слоты, исключены).
- **past-слоты** (≈половина у ClickPay/Content hunter/Relisme) → `clampPastSlot` дропнет как `past_slot_dropped` (без бэкфилл-спама).
- **слот очищен / контент заменён** → D3 lineage-guard пропустит (`slot_no_longer_valid`).
- **manual-слоты** → уже исключены кандидатным запросом (`effectiveManualSql`).

---

## 3. Дизайн фикса (Подход A — хирургический, delivery-side)

### 3.1 Суть
Сделать верхнеуровневый кандидатный дедуп **status-aware**: не считать «уже назначенным» результат, у которого
есть **только** move-cancelled строки. Доверить решение «пере-ставить или подавить» существующему D3 lineage-guard.

`server.js` ~6260, заменить:
```sql
AND NOT EXISTS (SELECT 1 FROM publish_queue pq WHERE pq.unic_result_id = ur.id)
```
на (под kill-switch):
```sql
AND NOT EXISTS (
  SELECT 1 FROM publish_queue pq
  WHERE pq.unic_result_id = ur.id
    AND NOT (pq.status = 'cancelled' AND COALESCE(pq.skip_reason, '') LIKE 'moved_from_slot%')
)
```

> **NULL-safety (codex P2).** Без `COALESCE` для `cancelled`-строки с `skip_reason IS NULL` выражение
> `skip_reason LIKE '...'` даёт `NULL` → `NOT (... AND NULL)` = `NULL` → строка НЕ учитывается `EXISTS`,
> т.е. не-move отмена с NULL-причиной ошибочно впускалась бы в re-queue. `COALESCE(skip_reason,'')`
> превращает NULL в пустую строку → `'' LIKE 'moved_from_slot%'` = FALSE → такая строка остаётся
> блокирующей (как и задумано в §3.2/§5.6).

### 3.2 Почему именно «только move-cancelled», а не «любой cancelled»
Чтобы **не загрязнять кандидатный набор**. Если исключать любые `cancelled`, то результаты с удалённым
контентом (lineage невалиден) каждый тик будут возвращаться в кандидаты и каждый раз отбрасываться гардом —
при `LIMIT 100 ORDER BY created_at ASC` это может вытеснять свежие легитимные результаты (starvation).
Сужение до `skip_reason LIKE 'moved_from_slot%'` впускает только перенесённый контент; после успешной
повторной вставки появляется живая (`pending`) строка → результат снова исключается дедупом → самозатухание.

### 3.3 Корректность по веткам (через существующие гарды, без новой логики)
- **Перенос, слот всё ещё filled этим content** → дедуп впускает → D3 lineage valid → INSERT на новую дату
  (`scheduled_at` пересчитывается из переадресованного `res.slot_date`, аккаунты — из пака). ✅
- **Перенос в прошлое** → `clampPastSlot` (внутри D3-транзакции) дропает как `past_slot_dropped`. ✅
- **Контент удалили/заменили в слоте** → D3 lineage invalid (`content_id`/`status` не совпали) → skip `slot_no_longer_valid`. ✅
- **Manual-слот** → исключён кандидатным `effectiveManualSql`; плюс D4 dispatch-recheck (`server.js:6122`). ✅
- **Дубли по аккаунту** → per-account дедуп (`server.js:6472-6486`, `status NOT IN ('cancelled','skipped')`) уже защищает. ✅

### 3.4 Kill-switch
- Env-флаг, напр. `ASSIGN_REQUEUE_MOVED_ENABLED` (default **ON** — активный простой у 14 проектов).
- При `=false` — выражение дедупа возвращается к status-слепому (текущее прод-поведение). Откат без передеплоя кода.
- Реализация: строить фрагмент `NOT (...)` условно в зависимости от флага (как в существующих kill-switch паттернах сервера).

### 3.5 Что НЕ трогаем (YAGNI)
- Валидатор (`pipeline_reversal.py`, `schedule.py`) — корректен: он переадресует `unic_tasks` и зовёт `notify_content_approved`.
  Подходы B (валидатор сам создаёт queue-строки) и C (UPDATE scheduled_at вместо cancel) отклонены: дублируют
  account/device/scheduling-логику популятора и/или не восстанавливают уже застрявший контент.
- D3/D4 lineage-guard, `clampPastSlot`, per-account дедуп — переиспользуем как есть.

---

## 4. Операционная разблокировка (после деплоя фикса)

Фикс самовосстанавливающийся: на ближайшем тике крона (каждые ~20–30 мин) популятор пере-ставит будущие
auto-слоты для всех 14 проектов. **Отдельный ручной SQL для Енотов не нужен** — после включения флага
Еноты 27–30.05 пере-ставятся автоматически (26.05 — manual, останется ручным по задумке Ани).

Смок-проверка сразу после деплоя:
1. Дождаться тика / при необходимости рестарт PM2-процесса delivery (`sudo pm2 restart <autowarm id 35>`).
2. Проверить, что у Енотов появились `pending` строки `publish_queue` на 27–30.05 (auto-слоты), `scheduled_at` = новые даты.
3. Проверить, что past-слоты получили `past_slot_dropped`, а manual-слоты (26.05) НЕ пере-ставлены.
4. Проверить отсутствие дублей (per-account дедуп) и здоровье крона в логах (`[assign-queue]`).

---

## 5. Тестирование

Unit/integration (по образцу существующих `test_*` в autowarm, live-DB через фикстуры):
1. **move-cancelled + slot filled (future, auto)** → результат впущен → INSERT на новую дату. (главный кейс Енотов)
2. **move-cancelled + slot filled (past)** → `past_slot_dropped`, без публикации.
3. **move-cancelled + slot очищен/контент заменён** → D3 skip `slot_no_longer_valid`, без INSERT.
4. **move-cancelled + manual-слот** → исключён кандидатным запросом, без INSERT.
5. **есть живая (pending/running/done) строка** → дедуп по-прежнему блокирует (нет дублей).
6. **cancelled с другим skip_reason** (не move, напр. `slot_moved`/manual_publish) → остаётся заблокирован (нет загрязнения кандидатов).
7. **kill-switch OFF** → поведение = текущее прод (status-слепой дедуп).

Регрессия: прогнать существующие тесты популятора/диспетчера перед коммитом (parallel-session правило — зелёный pytest/node --test).

---

## 6. Rollout (выбран: A + kill-switch, включить сразу)

1. Фикс под `ASSIGN_REQUEUE_MOVED_ENABLED` (default ON).
2. Codex review спеки и плана → 0 P1.
3. Реализация (TDD) → тесты зелёные → коммит в прод main (auto-push hook).
4. Деплой, смок на Енотах (см. §4), мониторинг волны re-queue по 14 проектам (объём INSERT, отсутствие дублей,
   доля `past_slot_dropped`, отсутствие всплеска fail-rate публикатора).
5. WP-комментарий (house-style): Эль = штатное; Еноты+13 проектов = системный re-queue gap, исправлен.
   Статус → «Тестирование», verify динамики выкладки ~27.05.

Откат: `ASSIGN_REQUEUE_MOVED_ENABLED=false` + restart (без передеплоя кода).

---

## 7. Открытые вопросы / риски

- **Волна re-queue при включении** (~323 результата). Ограничена `LIMIT 100` на тик; past дропаются; дубли
  защищены per-account дедупом. Мониторить первые тики.
- **Точное имя env-флага и место условной сборки SQL** — уточнить по существующим kill-switch паттернам в `server.js` на этапе плана.
- **`skip_reason` контракт.** Фикс завязан на литерал `moved_from_slot%` (его пишет `schedule.py:457`).
  Если валидатор сменит формулировку причины — дедуп перестанет впускать. Зафиксировать как shared-contract
  (комментарий в обоих репозиториях; кандидат на тест-«канарейку»).
