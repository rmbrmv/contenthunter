# WP#213-A «Правдивость Лога событий» — SHIPPED+DEPLOYED 03.06.2026

Под-проект A задачи WP#213 (баги read-model «Лога событий», п.1/4/6). Только display/read-model, без изменения поведения публикации, без миграции данных, за kill-switch `LIFECYCLE_TRUTHFUL_STAGE_ENABLED` (default ON).

## Диагностика (прод, read-only, БД openclaw@localhost:5432)

- **п.4 — «ЗАСТРЯЛ В РУЧНОЙ» ложный на 99.3%:** 2141 из 2157 строк stage-5. Корень: `lifecycle.js` ставил стадию «в ручной» по `pq.manual_handoff_at IS NOT NULL` без проверки живой строки в `validator_manual_publish_queue`. Все ложные = `failed`+handoff, строку в ручной отменили/вычистили. По бейджам роликов: **219 → 15**.
- **п.1 — LEX-012 (content 2445):** @LexisVoice_Sales (ig/tt/yt) реально застряли в АВТО (`process_interrupted`), в ручную НЕ переданы (~5 дней). Лог отображал корректно — это НЕ баг отображения. Ответ на вопрос Данила: «реально застряли, в ручную не передали».
- **п.6 — WAN-021 (content 2431):** `buildTimeline` не рисовал терминальные состояния → модалка отменённого аккаунта ложно заканчивалась «Запланирован» при бейдже «Не выложен».
- **бонус:** stage «Выложен» не учитывал `published_auto` (WP#187) → ложно «не выложен».

## Эффект (legacy → truthful, по роликам)

| worst-state | legacy | truthful |
|---|---|---|
| ЗАСТРЯЛ В РУЧНОЙ | 219 | **15** |
| ЗАСТРЯЛ В АВТО | 0 | 3 (LEX-012) |
| Не выложен | 24 | 65 |
| Запланирован | 70 | 233 |
| Выложен | 148 | 148 |

## Фикс (`lifecycle.js`, фронт `public/index.html`)

- `stageCaseSql(enabled)` — общий фрагмент для `rollupSql`+`accountsSql` (DRY). Новое: stage 5 требует `mq.id IS NOT NULL AND operator_status='queued'`; `manual_handoff_at + mq.id IS NULL` → stage 8 «Не выложен»; `published_auto` → stage 7; +агрегат `max_auto_days` (stage 3,4).
- `deriveWorstState` — новый бейдж `stuck_auto` «ЗАСТРЯЛ В АВТО».
- `buildTimeline` — терминальные точки (cancelled / слетел-из-ручной / published_auto).
- фронт: `LC_BADGE.stuck_auto` + пункт фильтра «Застрял в авто».
- `server.js` НЕ менялся (kill-switch читается внутри функций lifecycle.js).

## Решения владельца

A сначала отдельным PR; п.4 ложные → «Не выложен»; п.1 только честное отображение (механизм handoff не трогаем).

## Тесты

TDD, субагент-разработка (6 коммитов, two-stage review + финальный). Pure 20/20, Live 5/5 (инвариант «нет stage=5 без живой mq» = 0 на прод-БД, `published_auto`=stage 7). Регрессия при kill-switch OFF — зелёная.

## Деплой

- PR #153 (delivery-contenthunter) → merge main `3b4b538`.
- Прод: `git pull` в `/root/.openclaw/workspace-genri/autowarm` (owned claude-user, без sudo) + `sudo pm2 restart 35` (`autowarm`/server.js). pm2 online, 0 unstable restarts. Live-инвариант 5/5 на прод-коде.
- Docs спека+план: `docs/superpowers/{specs,plans}/2026-06-03-wp213-lifecycle-log-truthfulness*` (contenthunter main `2ff12364c`).
- OP#213 → «Тестирование» + коммент.

## Verify (по событию)

Аналитика → 📜 Лог событий: «застрял в ручной» ~15, LEX-012 = «застрял в авто», WAN-021 модалка отменённого аккаунта = «Не выложен».

## Остаток

Под-проект **B (п.2/3/5)** — коды роликов в ручной/планировщике + фильтр периодом — в работе отдельно. Отложенный авто-handoff из п.1 — см. BACKLOG.
