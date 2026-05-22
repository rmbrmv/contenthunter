# 2026-05-22 — WP #108 пост-деплой: осиротевший бэклог упавших + success-rate (handoff=fail) + fix stats vp-баг

**Код-репо:** GenGo2/delivery-contenthunter `main` (прямые коммиты + auto-push hook, без PR).
**Коммиты:** `9735330` (success-rate handoff=fail), `c861597` (fix /publish/stats vp).
**Деплой:** оба — `pm2 restart autowarm` (id 35) в окно 0 задач в полёте; origin/main синхрон 0/0.
**OpenProject:** комментарий к WP #108 + новые WP (success-rate, stats-vp); ранее заведены WP #140 (классификатор error-кодов), WP #141 (видимость ручной выкладки на дашборде).
**Память:** `project_wp108_retry_engine_orphan_backlog`, обновлён `project_daily_publish_report`.

---

## 1. Осиротевший бэклог упавших (триггер обращения Данила)

**Симптом:** «за сегодня упало 56 задач, они должны были уйти в ретрай, но висят failed».

**Корень:** WP #108 (движок ретраев) задеплоен сегодня ~10:46 UTC. Контроллер связывает упавшую строку очереди с её падением **только через `client_publish_id`** (`retry_controller.js:39`), а guard `if (!r.error_class) continue` молча пропускает строки без класса. Но проброс `client_publish_id` в `publish_tasks` приехал **в ТОМ ЖЕ деплое** (коммит `ce4429b`). Значит все ~57 задач, упавших **до** деплоя, имели `publish_tasks.client_publish_id = NULL` → JOIN контроллера их не находил → они не ретраились и не уходили в ручную, просто висели `failed`.

**Доказательство (timeline по деплою):**
- failed-задачи с `client_publish_id`: до 10:34 — **57 шт NULL**, после — заполнен.
- `error_class`: NULL в часы 04–10, заполнен с 11:00.
- PM2 `autowarm` рестарт 10:46 UTC (uptime подтвердил), `retry_handoff:structural_error` в очереди → контроллер живой.
- Бакет 24 застрявших строк: latest task по `publish_task_id` имеет `client_publish_id IS NULL` (до-деплойные); 16 из них — `process_interrupted` (убиты рестартом самого деплоя, контроллер их исключает по дизайну).

**Ремонт (вариант А, выбран Данилом):**
- 16 `process_interrupted` (деплой-киллы) → `pending` напрямую (контроллер их не трогает; это не реальные фейлы — прерванные публикации).
- 9 осиротевшим задачам — backfill `client_publish_id` из `publish_queue.publish_task_id` (`error_class` уже был проставлен маппером).
- Контроллер на тике **14:31** отработал по дизайну: **5 → requeue** (`unknown`/transient), **4 → handoff** (`ui_changed` → ручная выкладка, слоты 2060/2733/4189). Лог `[retry-controller] requeue/handoff pq#5016/5019/…`.

**Урок:** если новый consumer ключуется по колонке, которую проставляет код того же деплоя, — все до-деплойные строки осиротеют. Нужен backfill-скрипт **в составе деплоя** либо fallback-связка по `publish_task_id`. Разовый эффект миграции, будущие деплои не пострадают (`client_publish_id` теперь проставляется всегда).

## 2. Success rate: задачи в ручной выкладке (handoff) считаются фейлами

**Что было не так:** когда публикация многократно падает, движок отдаёт её в ручную (строка `failed` → `cancelled` + `manual_handoff_at`, skip_reason `retry_handoff:...`). А `cancelled` целиком исключался из метрики → реальные фейлы выпадали из знаменателя → success rate **завышался**.

**Что сделано (`9735330`):** `cancelled` с `manual_handoff_at IS NOT NULL` (retry-handoff) теперь = **ошибка** (`errors`); из `cancelled_skipped` исключается. Проактивный `manual_publish` (админ/клиент) и переносы слотов (`moved_from_slot`, `manual_handoff_at IS NULL`) остаются исключёнными — это не фейлы. Поправлены **обе** точки метрики: дашборд pub-dash (плитки + timeseries, `server.js`) и ежедневный Telegram-отчёт (`buildReport` + `buildErrorBreakdown`, `daily_publish_report.js`). Добавлен live-DB тест `buildReport`.

**Проверка (живые данные сегодня):** errors 32 → **37** (+5 handoff), cancelled_skipped 16 → 11, success rate 86.2% → **84.4%**. Тесты: дашборд 45/45, отчёт 37/37, интеграция 9/9 (+ новый кейс), оба SQL прогнаны на проде.

## 3. Fix: /api/publish/(queue|tasks)/stats — 500 «missing FROM-clause entry for table vp»

**Что было не так (пред-существующий, ~43 ошибки/сегодня, не связан с #108):** stats-эндпоинты падали 500 при фильтре по проекту: их stats-FROM опускал `validator_projects`, а билдеры фильтров (`buildPublishQueueFilters`/`buildPublishTasksFilters`) при `?project=` подставляют предикат на `COALESCE(vp.project, vp2.project)` / `vp.project`. Рассинхрон FROM↔WHERE.

**Что сделано (`c861597`):** `PUBLISH_QUEUE_FROM_STATS` теперь JOIN'ит `vp`+`vp2`; inline-FROM в `tasks/stats` вынесен в именованную `PUBLISH_TASKS_FROM_STATS` (с `vp`). LEFT JOIN на PK `project_id` → без фан-аута, `COUNT(*)` по статусам не искажается. Добавлен регресс-тест `tests/test_stats_from_filter_contract.test.js` — собирает реальный stats-SQL (FROM из server.js + WHERE из билдера с project-фильтром) и исполняет на БД, ловит любой будущий FROM↔filter рассинхрон.

**Проверка:** баг воспроизведён (missing-FROM без JOIN), фикс отрабатывает на живой БД для обоих эндпоинтов; регресс-тест 2/2; после рестарта 16:39 — ни одной vp-ошибки.

## Follow-ups
- **WP #140** — классификатор error-кодов: занести реальные UI-коды (`yt_picker_target_absent`, `yt_app_not_foregrounded`, `yt_picker_dismissed`, `switch_failed_unspecified`…) в `publish_error_codes` как `ui_changed`, иначе они дефолтятся в `unknown` и ретраятся вечно вместо handoff (как pq#5069).
- **WP #141** — дашборд + графики: показывать count и % задач, ушедших в ручную выкладку (раздельно retry-handoff vs проактивный manual_publish).
