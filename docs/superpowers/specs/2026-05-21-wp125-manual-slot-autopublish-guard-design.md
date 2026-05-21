# WP #125 — Видео с пометкой ручной выкладки автовыложилось (хотфикс)

**Дата:** 2026-05-21
**Тип:** багфикс (autowarm publish-pipeline)
**Очередь:** выкатывается ПЕРВЫМ, до фич #123/#124
**Связанные:** WP #85 (признак ручной выкладки), WP #115 (client-level manual flag), WP #107 (очередь ручной выкладки)

## Проблема

Видео, помеченное оператором «ручная выкладка» (`validator_schedule_slots.manual_publish = true`), всё равно автоматически опубликовалось ботом-публикатором.

### Подтверждение по боевым данным (проект Feminista, телефоны 154/155/156)

Во всей БД сейчас 3 слота с `manual_publish=true`. Релевантный — slot **21246** (проект «Feminista патчи для глаз», content_id 2240, дата 2026-05-21). Хронология:

| Событие | Время (UTC) |
|---|---|
| Создан `unic_task` 2641 (meta slot_id=21246) + 4 `unic_results` (по паку на аккаунт) | 2026-05-19 12:17–12:18 |
| **Созданы строки `publish_queue` 4333–4342 со `status='pending'`** | **2026-05-19 12:30:03** |
| Оператор пометил слот `manual_publish=true` (`manual_publish_set_at`) | 2026-05-20 06:10:03 |
| `dispatchPublishQueue` **отправил их в публикацию** → `publish_tasks` 8778/8797/8835/… (есть `post_url`, статусы `done`/`published_no_url`) | 2026-05-21 05:00–08:30 |

Паки = телефоны из тикета: pack 402 «Feminista_154» (feminista.beauty, IG/TT/YT), 403 «_155» (feminista_patches), 404 «_156» (feminista_glow), 464 «_156a» (feminista_woman, только TT).

Соседний slot 21244 (content 2013) спасся **случайно**: его pending-строки были отменены из-за переноса слота (`skip_reason='moved_from_slot_21118_to_21244'`), а не из-за флага.

## Корневая причина

Флаг `manual_publish` ставится **после** того, как контент уже заехал в `publish_queue` (типичный случай — очередь наполняется заранее, оператор помечает позже). При этом:

1. **Включение флага не отменяет уже-`pending` строки `publish_queue`.** Insert-time guard в `assignUnicResultsToQueue` (server.js ~6157–6162, через `effectiveManualSql`) проверяет флаг только в момент вставки — для уже лежащих строк он бессилен.
2. **`dispatchPublishQueue` не перепроверяет `manual_publish` при отправке.** SELECT pending-строк (server.js ~6535–6540) и lineage-guard `checkDispatchQueueSlotLineage` (server.js ~5999–6085) проверяют дату/контент/слот, но НЕ флаг ручной выкладки. Диспетчер доверяет, что очередь уже отфильтрована на вставке.

Дополнительные незащищённые пути записи в `publish_queue` (риск тем же классом, чинятся слоем 1):
- watchdog re-queue упавшей задачи: `UPDATE publish_queue SET status='pending'` (server.js ~6928–6934) — без перепроверки флага;
- reschedule endpoint `PUT /api/publish/queue/:id/reschedule` (server.js ~2434–2446);
- force-enqueue endpoint `POST /api/publish/queue/manual` (server.js ~2268–2420) — прямой INSERT в `publish_queue` без проверки флага.

> Номера строк — индикативные (сняты разведкой на testbench-чекпоинте); реализатор сверяется с актуальным `server.js` перед правкой.

## Решение: защита в два слоя + разовая зачистка

### Слой 1 (главный чокпоинт) — перепроверка флага на диспатче

В `dispatchPublishQueue`, перед созданием `publish_task` из pending-строки, проверять `manual_publish` слота, к которому относится строка:

- Слот определяется по линии `unic_task` → `meta->>'slot_id'` (так же, как в insert-time guard). Если у строки нет `unic_task_id`/`slot_id`, применяем тот же безопасный фолбэк, что и существующий lineage-guard (не блокируем легаси-строки без линии — поведение как сейчас, чтобы не сломать авто-пайплайн).
- Проверка использует `effectiveManualSql('vss','p')` из `client_manual_filter.js`, чтобы покрыть и client-level флаг (WP #115).
- Если слот manual → **не диспатчить**: пометить строку терминально (`status='cancelled'` либо `status='skipped'` с `skip_reason='manual_publish'` — финальный выбор по существующему соглашению в коде, чтобы строка не подхватывалась снова) и записать понятную запись в лог.
- Иначе — диспатчить как раньше.

Этот слой ловит ВСЕ пути (auto-enqueue, watchdog re-queue, reschedule, force-enqueue) и любые тайминги (флаг до/после вставки), т.к. он на единственном выходе в публикацию.

### Слой 2 (чистый UX) — отмена pending при включении флага

При включении `manual_publish` для слота отменять ещё-`pending` строки `publish_queue` для этого слота/линии, чтобы они не висели «в очереди».

- Точку, где ставится флаг, реализатор уточняет на этапе плана: валидаторный `PATCH /api/schedule/slots/{id}/manual-publish` (WP #85, по памяти вызывает `cancel_downstream_for_content(keep_slot_id=slot_id)`) и/или delivery-сторона. Нужно проверить, **дотягивается ли** существующий `cancel_downstream` до `publish_queue`. Если нет — добавить отмену pending-строк линии слота.
- Слой 2 не является гарантией (ей служит слой 1) — это чистота очереди и UX.

### Разовая зачистка (safety)

Идемпотентно отменить текущие `pending` авто-строки `publish_queue` для слотов с `manual_publish=true` (одноразово при выкатке). Сейчас боевых таких строк нет (21246 уже `done`, 21244 `cancelled`, третий слот — тестовый проект), но закладываем как защиту от уже-затаившихся случаев.

## Поток данных (после фикса)

```
manual_publish=true слот
   ├── (слой 2) при включении флага → pending publish_queue линии слота → cancelled
   └── (слой 1) dispatchPublishQueue видит pending-строку
                 → resolve slot via unic_task.meta.slot_id
                 → effectiveManualSql → manual? ДА → строка terminal (skip), НЕ публикуем
                                              → НЕТ → публикуем как раньше
```

Manual-слоты публикуются только через оператора (очередь ручной выкладки `validator_manual_publish_queue`, WP #107) — авто-путь для них закрыт.

## Обработка ошибок / edge cases

- **Строка без `slot_id`/`unic_task`** (легаси): guard не блокирует (фолбэк как у существующего lineage-guard), поведение не меняется → нет регрессии авто-пайплайна.
- **Гонка**: даже если строка стала pending за миг до включения флага — слой 1 поймает её при следующем тике диспетчера.
- **Client-level флаг (WP #115)** учитывается через `effectiveManualSql` (когда `clientManualEnabled()`).

## Kill-switch

- ENV-флаг на слой-1 guard (например, `DISPATCH_MANUAL_RECHECK_ENABLED`, по умолчанию `true`) — выключить перепроверку без отката кода, если обнаружится ложноблок.

## Тесты (node --test, mock-pool)

- manual-слот (slot.manual_publish=true) → `dispatchPublishQueue` НЕ создаёт publish_task, помечает строку terminal;
- non-manual слот → диспатчится как раньше (анти-регрессия);
- строка без `slot_id`/линии → диспатчится (фолбэк, без блока);
- client-level флаг (`effectiveManualSql` с `clientManualEnabled()`) → блокируется;
- kill-switch off → guard не применяется (старое поведение).

## Деплой

- autowarm: `git pull` в prod-чекпоинт + `pm2 restart autowarm` (или per-task spawn — уточнить в плане), прод-чекпоинт с одобрения Данила.
- Smoke: проверить лог `dispatchPublishQueue` — manual-строки помечаются skip, non-manual идут; мониторить отсутствие ложноблоков первый день.
- Без миграций (чистый бэкенд-guard).

## Что вне скоупа

- UI/группировка очереди ручной выкладки (#123) и реалтайм (#124) — отдельный спек.
- Рефактор остальных незащищённых endpoint'ов сверх того, что покрывает слой 1 (слой 1 закрывает их по факту на чокпоинте; точечные правки — по необходимости в плане).
