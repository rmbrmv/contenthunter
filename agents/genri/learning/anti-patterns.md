## 2026-03-25 — _verify_like() добавлен как строгая проверка без понимания SurfaceView
Context: like_content → _verify_like() → Instagram Reels
Mistake: Вчера добавили _verify_like() как обязательную проверку. Сегодня выяснилось что Instagram Reels рендерится через SurfaceView → uiautomator dump пустой → always False → 0 лайков на всех задачах.
Why: SurfaceView-ограничение uiautomator не проверялось при проектировании фичи.
Fix: Перед добавлением UI-верификации для мобильного приложения — проверить: рендерится ли целевой экран через SurfaceView/TextureView? Если да — uiautomator не работает. Fallback: screencap + цветовой анализ, или доверять тапу.

## 2026-03-25 — pm2 restart без ожидания → тесты идут на старом коде
Context: все три итерации фикса switch_instagram_account сегодня
Mistake: После pm2 restart сразу сбрасывали задачи в pending. Scheduler успевал подхватить задачи до того как PM2 поднялся с новым кодом → тесты шли на старом Python warmer.py. Итог: 3 раунда «снова не работает» при уже правильном коде.
Why: pm2 restart асинхронный, warmer.py запускается из scheduler как subprocess — при overlap старый процесс мог доработать.
Fix: После pm2 restart подождать ≥5 сек и убедиться в `pm2 list` что uptime > 0, только потом сбрасывать задачи.

## 2026-03-25 — 3 итерации фикса одной функции без предварительной разведки устройства
Context: switch_instagram_account — коммиты 978fa98, 4ae95dc, a43e9d9
Mistake: Каждый раз фиксили одну проблему, запускали, видели новую. В итоге 3 коммита на одну функцию за 2 часа.
Why: Не сделали полный ADB dump + анализ ДО написания первой версии фикса.
Fix: Перед правкой ADB-функции: (1) снять реальный dump, (2) прогнать все паттерны через python3 -c прямо в консоли, (3) убедиться что target-элемент матчится. Только потом коммит. Один правильный коммит > три итеративных.

## 2026-03-23 — screen recording без mkdir -p — screenrecord молча падал
Context: warmer.py, start_screen_record()
Mistake: `screenrecord /sdcard/debug_screenshots/...` без предварительного создания директории. Android молча не создаёт файл, adb pull падает с пустой ошибкой.
Why: Предположили что директория уже есть на устройстве.
Fix: ВСЕГДА `adb shell mkdir -p /path/` перед любым `screenrecord` или записью файла на устройство. Правило: Android не создаёт директории автоматически.

## 2026-03-20 — Удалил таблицы с данными через CREATE OR REPLACE VIEW
Context: Нужно было создать мост между factory.* схемой и public schema
Mistake: Создал VIEW с именами существующих таблиц (factory_device_numbers, factory_pack_accounts, factory_inst_accounts, raspberry_port) — это удалило реальные таблицы с данными и заменило их VIEW-ами. factory_sync.py каждый час обновлял эти таблицы свежими данными с remote.
Why: Не проверил существующие таблицы перед созданием VIEW. Не знал про sync-скрипты (factory_sync.py, sync_sources.py). Не проверил pg_class.relkind перед CREATE OR REPLACE VIEW.
Fix:
1. ВСЕГДА проверять `SELECT relname, relkind FROM pg_class WHERE relname='...'` перед CREATE VIEW/TABLE
2. ВСЕГДА проверять cron + sync скрипты перед изменением схемы БД
3. ВСЕГДА делать pg_dump ПЕРЕД любыми DDL-изменениями
4. Настроить полный бэкап (сделано: public + factory schemas)

## 2026-03-25 — pm2 restart без паузы → тесты идут на старом коде
Context: switch_instagram_account — 3 итерации «снова не работает» при уже правильном коде
Mistake: После `pm2 restart autowarm` сразу сбрасывали задачи в pending. scheduler.js успевал запустить старый warmer.py subprocess до того как PM2 полностью поднялся.
Why: PM2 restart асинхронный. Сброс задач сразу после команды = race condition.
Fix: После `pm2 restart` → `sleep 5` → проверить `pm2 list` что uptime > 0 → только потом сбрасывать задачи в pending.

## 2026-03-25 — UIAutomator атрибуты в обратном порядке — повторная ошибка
Context: switch_instagram_account — regex `text="..."[^>]*resource-id="..."`
Mistake: Предполагали порядок text → resource-id. Реальный UIAutomator XML: resource-id → text. Паттерн не матчился ни разу, несмотря на то что ошибка уже была описана в anti-patterns для ADB.
Why: При написании нового regex на UIAutomator не проверили dump перед кодированием.
Fix: Перед ЛЮБЫМ regex на UIAutomator XML — снять dump + `python3 -c "print(re.findall(pattern, ui))"`. Без реального теста в консоли — не писать regex.

## 2026-03-25 — _verify_like() как строгая проверка без учёта SurfaceView
Context: like_content → _verify_like() добавлена как обязательная верификация
Mistake: Добавили строгую проверку через uiautomator. Instagram Reels рендерится через SurfaceView → dump всегда пустой → _verify_like() always False → 0 лайков на всех задачах.
Why: Не проверили работает ли UIAutomator на целевом экране до реализации.
Fix: Перед любой UI-верификацией через UIAutomator: проверить `adb shell uiautomator dump` на целевом экране. Если < 200 байт → экран через SurfaceView, строгая верификация невозможна.

## 2026-03-26 — Массовое создание клиентов без проверки onboarding_stage
Context: create_client_users.py — 38 пользователей для всех активных проектов
Mistake: Скрипт взял все активные проекты из factory, не проверив `onboarding_stage`. Действующие проекты (ikomek, Relisme) получили stage=5 → клиенты сразу видели планировщик вместо онбординга.
Why: Предположили что «активный = новый». Не было проверки реального статуса проекта.
Fix: При bulk-создании client-пользователей — обязательно `SELECT id, project, onboarding_stage FROM validator_projects` и проверять логику: stage=5 → действующий, не трогать или явно сбрасывать на нужный этап.

## 2026-03-30 — Колонки в INSERT без проверки схемы → ошибка на каждую задачу
Context: autowarm/warmer.py → save_day_log() → INSERT в autowarm_day_logs с views, profile_visits и др.
Mistake: Код использует 6 колонок которых не было в таблице. Ошибка `column "views" does not exist` падала на каждую задачу фарминга с 25 марта (5 дней!), статистика дня не сохранялась.
Why: Колонки добавлены в INSERT при написании кода, но ALTER TABLE не сделан. Ошибка silent — только в PM2 логах, в UI не видна.
Fix: Добавлены 6 колонок ALTER TABLE. Правило: перед деплоем INSERT с новыми полями → `\d table_name`, убедиться что все поля существуют. Если нет — сначала ALTER TABLE, потом код.

## 2026-03-30 — Anthropic ключ в warmer.py не обновлён после ротации
Context: warmer.py → analyze_audience_with_ai → Anthropic API → 403 Forbidden
Mistake: warmer.py использует Anthropic ключ напрямую. После ротации ключей (25 марта: anthropic_genri → anthropic_default) validator обновили, но warmer.py — нет. Все AI-анализы аудитории дают 403.
Why: Ключи обновлялись точечно в одном месте, не проверялись все сервисы использующие тот же ключ.
Fix: При ротации API ключей — grep по всем сервисам: `grep -rn "ANTHROPIC\|anthropic" /root/.openclaw/workspace-genri/` и обновить везде синхронно.

## 2026-03-27 — Router написан под схему БД которой не существует
Context: validator/backend/src/routers/contract.py — GET /api/contract/status
Mistake: `contract.py` делает SELECT `plan_phones, plan_accounts, plan_publications, plan_views, contract_start, contract_end` из `validator_projects`. Ни одной из этих колонок в таблице нет. Каждый вызов → 500.
Why: Роутер написан заранее «под будущую схему» без создания миграции. Код задеплоен, таблица — нет.
Fix: Перед деплоем любого нового роутера — проверить что все используемые колонки и таблицы существуют в БД: `\d table_name`. Если нет — сначала миграция, потом деплой кода.

## 2026-03-27 — autowarm_day_logs: колонка views отсутствует — молчаливая потеря данных
Context: warmer.py → save_day_log() → INSERT в autowarm_day_logs с полем views
Mistake: `save_day_log` падает с `column "views" of relation "autowarm_day_logs" does not exist` — статистика дня не сохраняется, ошибка только в PM2 логах, в UI не видна.
Why: Колонка добавлена в код но не добавлена в схему БД (нет ALTER TABLE или миграции).
Fix: При добавлении нового поля в INSERT/UPDATE — сначала ALTER TABLE, потом деплой кода. Порядок: БД → код, не наоборот.

## 2026-03-26 — Создание таблицы БД без миграции в коде
Context: validator_support_history — таблица создана прямым SQL, не через Alembic миграцию
Mistake: Таблица создана через `psql CREATE TABLE` напрямую. В коде нет миграции → при следующем `alembic upgrade head` или деплое на чистый сервер таблицы не будет.
Why: Быстрое исправление без учёта lifecycle базы данных.
Fix: После исправления через прямой SQL — добавить Alembic миграцию или задокументировать в README validator как ручной шаг. Хранить DDL в `validator/backend/migrations/` или `scripts/`.

## 2026-04-01 — Appium + ADB relay = несовместимо без доп. проксирования
Context: Appium UiAutomator2 + устройства через ADB relay (82.115.54.26:15068)
Mistake: Appium устанавливает `adb forward tcp:8200` на relay-сервере, но сам пытается подключиться к localhost:8200. Инструментация запускается, но Appium не достучится → timeout 120с на каждом запуске.
Why: ADB relay мультиплексирует устройства на одном порту — нестандартная архитектура. Appium не предназначен для этого.
Fix: Для Appium с relay нужен socat tunnel (localhost:8200 → relay:8200). Либо запускать Appium на raspberry где устройства подключены напрямую. Либо ChromeDriver через DevTools Protocol (порт 9222 уже forwarded через relay).

## 2026-04-01 — Vision model для координат UI — ненадёжно (ошибка 300-700px)
Context: Groq llama-4-scout для поиска координат кнопок Google registration form
Mistake: Vision говорила «Далее: (601, 1430)», реальная координата — (900, 2103). 3+ итерации из-за промахов.
Why: Vision оценивает позицию визуально и не учитывает реальный scale. Rendering scale ≠ device pixels.
Fix: Vision → только «что на экране». Координаты → UIAutomator bounds или `input tap Y_candidate + проверка реакции UI`.

## 2026-04-01 — Chrome WebView при регистрации Google — UIAutomator бесполезен
Context: Google account registration Chrome → UIAutomator dump показывает только URL адресной строки
Mistake: Потрачено 3+ часа на UIAutomator в Chrome WebView. Он физически не может получить DOM Chrome.
Why: Chrome renderer process изолирован от accessibility tree. UIAutomator получает только native UI chrome, не страницу.
Fix: Для Chrome WebView: (1) Appium + ChromeDriver, (2) adb forward 9222 + selenium CDP, (3) нативный Settings flow. UIAutomator в Chrome = waste of time.

## 2026-04-02 — Незавершённый фикс при переключении на другую задачу
Context: validator validation.py + schedule.py — фикс начат но не закоммичен при получении ревью-задачи
Mistake: Правки кода на половине — переключился. Незафиксированный WIP может быть перезаписан или запутать следующую сессию.
Why: Новая задача (ревью) пришла в середине исправления.
Fix: Перед любым переключением — либо `git commit -m "wip: ..."`, либо запись в memory что именно не завершено и на каком шаге.

## 2026-04-03 — WIP schedule.py PATCH: начатый фикс не закоммичен (повтор)
Context: PATCH /schedule/slots/{id} должен возвращать content данные (title, type) — фикс начат 01.04 но не закоммичен
Mistake: Второй раз за неделю один и тот же паттерн: начал фикс → переключился → потерял WIP.
Why: Переключение на рефлексию/ревью без фиксации состояния.
Fix: Жёсткое правило: если open editor с несохранёнными правками — СТОП. Сначала `git commit -m "wip: ..."` или полный откат, потом переключение.

## 2026-04-03 — Перегенерация слотов без проверки существующих данных
Context: Перегенерация 55 проектов × 26 недель — могла затронуть слоты с уже назначенным контентом
Mistake: Скрипт перегенерации выполнен широко (2026-02-16 → 2026-08-17), без проверки есть ли в слотах content_id.
Why: Предположили что все слоты пустые.
Fix: Перед массовой перегенерацией слотов — `SELECT COUNT(*) FROM validator_schedule_slots WHERE content_id IS NOT NULL`. Если > 0 — перегенерировать только пустые, не трогать заполненные.
