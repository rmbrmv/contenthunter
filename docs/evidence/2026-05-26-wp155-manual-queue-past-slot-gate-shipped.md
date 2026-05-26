# WP #155 — SHIPPED+DEPLOYED 2026-05-26

**Гейт просрочки в ручной очереди выкладки.** Спека/план: `docs/superpowers/{specs,plans}/2026-05-26-wp155-manual-queue-past-slot-gate*`.

## Вердикт расследования
«Ручная дата (25.05) раньше План даты (26–29.05)» — **НЕ баг данных.** Обе даты корректны; снимок `planned_date` в очереди точно совпадает с текущим `slot_date` (гипотеза автора про устаревший снимок из-за переносов планировщика — опровергнута по БД). Симптом = следствие двух ожидаемых механик:
- **Перевод проекта в ручной режим задним числом** (`validator_projects.manual_publish_set_at`: Ambassadori 25.05 07:27, Feminista 21.05 13:51) → наполнитель смёл в ручную весь готовый архив проекта, включая слоты с план-датой 2-недельной давности.
- **Уникализация опережает план-дату** → будущие слоты падают в ручную в момент готовности (25.05), раньше плановой публикации (26–29).

Корневое несоответствие: авто-тракт дропает прошедшие слоты (`clampPastSlot`, `server.js`), а ручной наполнитель — нет.

## Что задеплоено (репо GenGo2/delivery-contenthunter, PR #109, merge `6aab91f`)
- **Гейт** в `manual_queue_assign.js`: SQL-фильтр `to_char(vss.slot_date,'YYYY-MM-DD') >= cutoff`, `cutoff = computeBusinessDate(tz, now − grace)`, tz из `unic_settings`. Фильтр в SQL обязателен (иначе старьё голодит батч под `ORDER BY created_at ASC LIMIT`).
- **Флаги:** `MANUAL_QUEUE_DROP_PAST_SLOTS` (kill-switch, default on), `MANUAL_QUEUE_PAST_SLOT_GRACE_DAYS` (default 3). Смена — через `pm2 restart autowarm --update-env`.
- **One-off** `cleanup_wp155_manual_queue_overdue.js` (dry-run default, `--apply`, `--onlyProject`).
- **Ярлык** `public/index.html`: «Ручная дата» → «Добавлено в очередь».
- Осознанное расхождение: авто = 0 грейса, ручная = 3 дня (человеческий догон).

## Деплой
- Прод `/root/.openclaw/workspace-genri/autowarm` → `git pull` (ff на `6aab91f`) → `sudo pm2 restart autowarm` (ROOT PM2 id=35, exec cwd корректный).
- Бэкенд-лог подтвердил гейт: `[manual-queue] past-slot gate ON: cutoff=2026-05-23 grace=3d`; прогон 18:30 нашёл 2 результата (без флуда), ошибок нет.

## Ретро-зачистка
- dry-run: 148 кандидатов (cutoff 2026-05-23). Apply: Feminista 62 (смок) + глобально 86 = **148 отменено**; `published`/`in_progress` не тронуты; остаток просрочки `queued` = 0; повторный dry-run = 0 (идемпотентно).

## Тесты
- `tests/test_manual_queue_assign.test.js` — 10/10 (гейт ON/OFF, грейс из env, fallback'и грейса и таймзоны).
- `test_cleanup_wp155_overdue_live.test.js` — 3/3 (dry-run / apply scoped / идемпотентность).

## Осталось / verify
- Проследить динамику ручной очереди ~27.05: новые переводы проектов в ручной не засыпают оператора просрочкой; свежая просрочка (≤3 дня) и будущее по-прежнему попадают.
- OpenProject WP #155 → «Тестирование».

## Follow-up (бэклог)
- **Авто-публикация Ambassadori сыпалась до перевода в ручной** (масса `failed` + `retry_clean_slate_20260522`) — отдельный сюжет авто-тракта, вне scope #155. Кандидат на отдельную WP.
- Минорный тех-долг: логика cutoff (grace + `computeBusinessDate`) продублирована в гейте и one-off скрипте; зафиксирована тестами, но общий хелпер сделал бы комплементарность структурной. Скрипт одноразовый — низкий приоритет.
