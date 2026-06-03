# WP#213-B «Коды роликов и фильтры» — SHIPPED+DEPLOYED 03.06.2026

Под-проект B задачи WP#213 (п.2/3/5). Аддитивный UI, без миграции БД, без kill-switch. Закрывает WP#213 полностью (вместе с под-проектом A «Правдивость лога», PR #153).

## Что сделано

- **`content_code.js`** — общий хелпер `formatContentCode(prefix, number)` → `PREFIX-NNN` (number<1000 → lpad3, иначе как есть; null если нет prefix/number). DRY.
- **п.2 — код в ручной выкладке:** `manual_publish_queue.js` `JOINED_SELECT` (+`vp.code_prefix, vc.code_number`) + `rowToDict.code`; фронт `public/index.html` — колонка «Код» (первая, копируемая) + текстовый поиск/фильтр.
- **п.3 — код в планировщике:** `publish_planner.js` — код в 3 SQL-ветках `getPlannerCards` (full/legacy/plan) + `buildPlannerCards`; фронт `plannerCardHtml` показывает код ТОЛЬКО админам (`currentUser.role==='admin'`).
- **п.5 — период в «Логе событий»:** фронт `lcFilterRow` — второй `<input date_to>`; бэкенд (`applyClientSideFilters`/эндпоинт) диапазон уже поддерживал.

## Решения владельца

п.2 = код-колонка + поиск (статус-фильтр уже есть); п.5 = диапазон только в Логе (в ручной уже есть); п.3 = гейт на фронте по role admin; B одним PR.

## Тесты

TDD, субагент-разработка (6 коммитов, two-stage review каждой задачи + финальный). Pure 20/20 (`content_code`, `manual_code`, `publish_planner`). Live 16/16 (`planner_code_live` + `manual_publish_queue`).

**Code-review критбаг (устранён до мержа):** в legacy-ветке планировщика вставка код-колонок после `video_title` сдвинула `business_date` на позицию 7, а `GROUP BY 1,2,3,4,5,...` его терял → SQL-ошибка (ветка недостижима в проде, full активна). Фикс: `GROUP BY 1,2,3,4,5,6,7`, проверен прямым прогоном legacy-SQL (724 строки, без ошибки).

## Деплой

- PR #154 (delivery-contenthunter) → merge main `56501a0`.
- Прод: `git pull` в `/root/.openclaw/workspace-genri/autowarm` (owned claude-user, без sudo) + `sudo pm2 restart 35`. pm2 online, 0 unstable restarts. Live smoke 16/16 на прод-коде.
- Docs спека+план: `docs/superpowers/{specs,plans}/2026-06-03-wp213-codes-and-filters*`.

## Verify (по событию)

Ручная выкладка — колонка «Код» + поиск по коду. Планировщик под админом — код в карточке (под не-админом нет). «Лог событий» — фильтр диапазоном дат (с/по).

## Итог по тикету WP#213

Обе части закрыты и задеплоены 03.06: **A** (правдивость лога, PR #153, main 3b4b538) + **B** (коды и фильтры, PR #154, main 56501a0). OP#213 → «Тестирование», ждёт финальной UI-проверки владельцем → «Готово».
