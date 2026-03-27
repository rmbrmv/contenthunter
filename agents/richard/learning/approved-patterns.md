# Approved Patterns — что работает
_Формат: [дата] Задача | Результат | Урок_

---

## Backend / API

[2026-03-02] Диагностика API ошибок | Curl-тест ключа дал мгновенный ответ `insufficient_quota` | Всегда тестировать API key вручную через curl ПЕРЕД тем как копаться в коде — экономит время

[2026-03-02] Исправление опечатки в имени переменной (`LAOZHANG_BASE_URL` → `LAOZHANG_URL`) | `sed -i 's/.../.../' file` нашёл и заменил 4 вхождения за 1 команду | Для массовой замены имени переменной — `sed -i` надёжнее ручного поиска через grep+edit

[2026-03-02] Перенос Python-воркера на внешний сервер | MAX_WORKERS=4, подключение к БД по внешнему IP, pg_hba.conf настроен под конкретный /32 | Для тяжёлых CPU-задач (FFmpeg) — отдельный сервер с прямым доступом к БД через whitelist IP, локальный воркер останавливать

[2026-03-02] Добавление route для HTML-страницы в Express | `res.sendFile('public/monitor.html', { root: __dirname })` вместо абсолютного пути | Express sendFile требует `{ root: dir }` или строго абсолютный путь; `path.join(__dirname, 'file')` может конфликтовать с express.static

[2026-03-02] Синтаксическая проверка JS в HTML | `node -e "new Function(html_script_content)"` ловит ошибки до деплоя | Перед PM2 restart всегда прогонять JS через `new Function()` — экономит один цикл перезапуска при ошибке

---

## Frontend / HTML

[2026-03-02] Восстановление потерянной секции (section-generator) | Читал session JSONL Генри → нашёл все функции и логику → восстановил полностью | Когда код потерян (не закоммичен) — искать в `/root/.openclaw/agents/{id}/sessions/*.jsonl`, там полная история действий

[2026-03-02] Удаление дублирующихся JS функций | grep нашёл 4 функции дважды → удалил первый блок, оставил второй (полнее) | Дубли функций в одном `<script>` тихо ломают всё через `already been declared` — ловить через `node -e "new Function()"`

[2026-03-02] Защита от null DOM-элемента | `if (carDZ) { ... }` guard на getElementById в скрытой секции | Инициализирующий код для элементов в скрытых секциях ОБЯЗАТЕЛЬНО оборачивать в null-guard

---

## Frontend / Vue

[2026-03-03] NavItem active state для многоуровневых меню | startsWith("/producer") подсвечивал все дочерние пути одновременно | Для вложенных роутов — добавить `exact` prop: `startsWith(to + '/')` вместо `startsWith(to)`, родительский пункт помечать `:exact="true"`. Решение минимальное (3 строки).

[2026-03-03] SQL computed fields вместо дублирования в коде | `contractor_amount = COALESCE(quantity,1)*COALESCE(price_per_unit,0)` в SELECT → не нужно считать в Vue/Python | Расчётные поля лучше считать в SQL-запросе (single source of truth). Упрощает и API, и фронт — данные всегда консистентны.

[2026-03-03] Drag & drop Kanban без библиотек | HTML5 dragstart/dragover/drop + оптимистичное обновление стейта + PATCH в фоне | Для простого Kanban — нативный HTML5 DnD достаточен. Оптимистичное обновление (`o.stage = targetStage` до ответа сервера) делает UX плавным.

## D3.js / Визуализация

[2026-03-02] System Monitor граф агентов | D3 force-directed с double-layer (glow pass + sharp pass) для неоновых линий | Для neon glow эффекта: рисовать ребро дважды — сначала широкое полупрозрачное (filter glow), потом узкое чёткое поверх

[2026-03-02] Heatmap коммуникаций | d3.scaleSequential + interpolate для цветовой шкалы 0→N | Для разреженных матриц (много нулей) — colorScale от bg-цвета до neon, а не от белого

---

## FastAPI / Python

[2026-03-03] Проверка prefix у существующих роутеров перед добавлением нового | producer.py добавил с prefix `/producer` вместо `/api/producer` → 404 на все запросы | Перед написанием нового роутера: `grep "prefix=" *.py` — убедиться что формат `/api/...` соблюдён у всех соседей.

[2026-03-03] JOIN с validator_projects в producer роутере | project_name нужен в списке заказов → добавил `LEFT JOIN validator_projects p ON p.id = o.project_id` | Когда нужны данные смежной таблицы — JOIN в SQL запросе, не второй SELECT в Python.

## Инфраструктура

[2026-03-02] Валидация FFmpeg-результата | Проверка: размер ≥100 КБ, длительность ±50%, наличие видео+аудио потоков, blackdetect | После любой медиа-генерации — минимум 3 проверки: файл существует + размер + длительность

[2026-03-02] БД whitelist для внешнего сервера | pg_hba.conf: `host openclaw openclaw 91.98.180.103/32 md5` | PostgreSQL: для каждого внешнего сервера — отдельная строка /32, не /24

---

## Рефакторинг HTML-секций (Python)

[2026-03-04] Унификация WA/TG/Factory секций | Написал Python-функцию `make_section()` с параметрами → заменил 3 секции за один проход | При унификации похожих HTML-блоков — параметризованный генератор на Python эффективнее ручного копирования. Результат: идентичная структура без расхождений.

[2026-03-04] Замена нескольких секций Python-скриптом | `find_section_bounds()` находит блок по id, замена с конца (factory→tg→wa) чтобы не сдвигать offsets | Заменять множество секций нужно в обратном порядке (от конца файла) — тогда offsets предыдущих секций не смещаются.

## Схема factory в локальной БД

[2026-03-04] factory.* таблицы через schema prefix | `factory.factory_inst_accounts`, `factory.device_numbers`, `factory.raspberry_port` — всё в схеме `factory` локальной openclaw DB | НИКАКОГО отдельного пула для factory-данных. Всё через `pool` (openclaw@localhost) с `factory.tablename`. distPool = тоже openclaw@localhost.

[2026-03-04] raspberry_port.adb — правильная колонка | Пробовал `rp.adb_port` → ERROR: column doesn't exist. Правильно: `rp.adb` | В factory.raspberry_port колонки: raspberry_number, adb, host, scr, port. НЕ adb_port.

[2026-03-04] JOIN для пакетов/проектов | `factory.factory_inst_accounts → pack_accounts → autowarm_project_mapping (factory_project_id) → factory.device_numbers → factory.raspberry_port` | factory_projects не существует в локальной схеме. Используем `autowarm_project_mapping` для получения имени проекта.

## Навигация Autowarm

[2026-03-04] _showSubBlocks(prefix, show) | Функция show/hide блоков + подсветка табов одним вызовом | Паттерн: `display:none/''` для скрытия секций внутри одной страницы. Вызывать через `setTimeout(fn, 100)` после nav() чтобы дать DOM обновиться.

## ADB / инфраструктура

[2026-03-04] ADB хосты из factory.raspberry_port | Большинство Pi → host `147.45.251.85` (не 82.115.54.26!). Только Pi #9 → 82.115.54.26 | Перед ADB работой проверять реальный хост в DB: `SELECT adb, host FROM factory.raspberry_port`. Не полагаться на "все Pi одинаковые".

---

## Субагенты / Параллельная работа

[2026-03-08] Горизонтальный скролл офиса через двух субагентов | Субагент 1: canvas/scroll, Субагент 2: рассадка агентов — чёткое разделение задач, каждый работал независимо | Декомпозиция UI-задачи на независимые части + параллельный запуск субагентов ускоряет в 2x. Разделять по "что делает" (layout / данные), не по файлам.

[2026-03-08] Восстановление из бэкапа по имени | index-v1-backup.html (1716 строк) — изометрический 2D офис. Правильная версия нашлась сразу по имени | Перед крупным рефакторингом HTML: `cp index.html index-v{N}-backup.html`. Бэкап по версии быстрее git bisect.

[2026-03-08] Groq как замена LaoZhang vision | meta-llama/llama-4-scout-17b-16e-instruct поддерживает vision, бесплатный тир, работает через OpenAI-compatible API | Когда LaoZhang кончился — Groq (api_key в /root/.openclaw/workspace/integrations/groq/api_key.txt) как fallback для vision задач.

## Python / Параллелизм

[2026-03-08] ThreadPoolExecutor для параллельных ADB запросов | archive_scheduler.py: sequential 11 мин → ThreadPoolExecutor(20) → 15 сек | Для I/O-bound задач (ADB, HTTP) — всегда ThreadPoolExecutor. Последовательный перебор 100+ устройств = блокировка.

## Canvas / agent-office

[2026-03-08] SOUL.md парсинг с тире | `# SOUL.md — Имя` → split(' — ')[1]; если первая часть = "SOUL.md" → берём вторую | Нестандартный формат SOUL.md (с тире в заголовке) — добавить в парсер отдельную ветку. Не полагаться на format="# Имя".

[2026-03-09] Стол Ассистенты как overflow-буфер | Utility-боты (pisaka, vseznayka, akaketo, apochemu) → отдельный стол BOTS_TABLE x=2620 | Для UI с динамическим составом агентов: делать явный "overflow" стол для вспомогательных агентов вместо скрытия. Так видно что они есть в системе.

---

## ADB / Instagram UI парсинг

[2026-03-09] Instagram audience — рабочий маршрут навигации | Профиль → "Профессиональная панель" → "Новые подписчики" → "Подробная информация о подписчике" → tap "Страны" → свайпы для скроллинга | Правильный путь к аудитории: НЕ "Статистика аккаунта" → "Аудитория". Только через "Новые подписчики" → "Подробная информация". Зафиксировать как единственный рабочий маршрут.

[2026-03-09] ADB свайп: начинать до интерактивного графика | Барчарты Instagram перехватывают touch-события если начинать свайп внутри их bounds. Рабочий свайп: `900→422` (начало выше y=421 — верхней границы scrollable контейнера) | При отладке ADB свайпов — сначала `uiautomator dump` + grep scrollable, проверить bounds. Начинать свайп выше верхней границы scrollable.

[2026-03-09] ADB маленький свайп для скрытого контента | Последняя строка геолиста (Бразилия) пряталась за навигационной панелью. Фикс: дополнительный mini-свайп `2150→1850` (300px) после основного | Для списков с навигационной панелью внизу — делать два свайпа: один большой + один малый 200-300px чтобы вытащить последний элемент.

[2026-03-09] Groq дедупликация по имени страны | Дедупликация текстов удаляла второй `7.6%` (Иран и Турция с одинаковым %). Фикс: дедуплицировать по имени страны, не по строке | При парсинге списков с процентами — дедуплицировать по ключу (имя), не по значению. Одинаковые числа = разные записи.

## Vue / CRM

[2026-03-09] computed filteredContractors для фильтрации по формату | watch(content_type) сбрасывает contractor_id при смене формата — UX не ломается | Связанные dropdown'ы (формат → исполнитель): computed для отфильтрованного списка + watch для авто-сброса выбора. Паттерн чистый, без лишнего кода.

## agent-office / Мониторинг

[2026-03-09] getAgentCosts() с 60с кэшем | Читает JSONL-сессии за 7 дней, суммирует cost.total — добавлено в /api/agents. Кэш через `_costsCache[id] = {ts, data}` | Для дорогих вычислений (чтение файлов) в /api/agents — добавлять кэш с TTL прямо в замыкании. 60с достаточно для live-дашборда.

---

## Аналитика / SQL

[2026-03-11] Исправление завышенных просмотров | Переключился с account_daily_delta на factory_inst_reels_stats.sum_views | Поле sum_views — уже готовые дневные дельты. views_count — накопительный total. При суммировании views_count за несколько дней = многократный overcounting. Всегда использовать sum_views для периодической аналитики.

[2026-03-11] Консультация с профильным агентом | Спросил Фёдора-аналитика о методологии → получил точный SQL с нужными join'ами | Если есть специализированный агент (analytics, finance, etc.) — спросить его первым делом перед самостоятельным решением. Экономит часы отладки.

[2026-03-11] JOIN chain для аналитики | factory_inst_reels_stats → factory_inst_reels → factory_inst_accounts → account_packages → filter by project | Связь аккаунтов с проектами в validator: через account_packages.project (полное название, не api_name). fia.instagram_id = r.account_id (не fia.id!).

[2026-03-11] Пагинация + фильтры в API | /analytics/client/publications: days, platform, search, page, limit | COUNT(*) с теми же WHERE условиями для total, LIMIT/OFFSET для страниц. Позволяет гибко фильтровать 2748 записей без перегрузки.

---

## UX / Frontend

[2026-03-11] Onboarding tour без библиотек | TourGuide.vue — overlay с getBoundingClientRect + Teleport | Spotlight через box-shadow: 0 0 0 9999px rgba(). Tooltip позиционируется по rect элемента. localStorage флаг для "показать один раз". Кнопка ? в хедере для повтора.

[2026-03-11] Field quality indicator | FieldQuality.vue — 4 сегмента как у пароля, логика на поле | Каждое поле имеет свою метрику качества (длина, наличие ключевых слов, количество элементов). Animate через CSS transition на ширине сегментов.

[2026-03-11] Hints с Teleport | FieldHint.vue — fixed позиция справа через getBoundingClientRect | Tooltip в пустой зоне справа от формы: position:fixed, right:24px, top = rect.top + rect.height/2, transform:translateY(-50%). Не перекрывает контент формы.

[2026-03-11] Inline fill from external source | Заполнил форму распаковки из Airtable через API PUT | При наличии внешних данных — автозаполнение через PUT endpoint сразу, не ждать пока пользователь введёт вручную.

---

## Monitor / Дашборд

[2026-03-13] API key filter вместо model filter | Заменил фильтр по моделям на фильтр по Anthropic API ключам в Tokens tab | Маппинг agent→key делать на сервере в AGENT_API_KEY dict, прокидывать `apiKey` прямо в `/api/token-usage` response — не обогащать на фронте из отдельного кэшированного эндпоинта. Кэш 24ч ≠ период недели/месяца.

[2026-03-13] tokensDept filter через ORG_AGENT_MAP | org-structure.json встроен инлайн в JS, buildOrgMap() при старте, buildDeptFilter() рендерит только активные отделы | Фильтры "ключ + отдел" комбинируются последовательно: сначала по ключу, потом по отделу. ORG_DEPTS.find().agents даёт Set для быстрой фильтрации.

[2026-03-13] let declaration перед IIFE | Переместил `let tokensCustomFrom` с строки 964 → строки 330, выше IIFE на строке 367 | JS `let` — Temporal Dead Zone: если IIFE вызывает функцию которая обращается к let-переменной, объявление ОБЯЗАТЕЛЬНО должно быть выше IIFE. `var` — нет, но let/const — да.

## Auth / SSO

[2026-03-12] Cross-auth для незарегистрированных пользователей | ch-auth выдаёт crossToken даже незарегистрированному если есть ?redirect= | Для SSO-потока с инвайтами: auth-провайдер должен пропускать новых пользователей через cross-token, не блокировать. Регистрацию делает целевой сервис по инвайту.

[2026-03-12] Передача redirect через тело запроса | Frontend: `{...tgData, _redirect: params.get('redirect')}` → Backend: `const { _redirect, ...tgData } = req.body` | Чтобы backend знал о redirect-контексте при Telegram auth: передавать как отдельное поле в body, извлекать ДО верификации хэша (иначе hash check всегда fails).

---

## Документация

[2026-03-12] ARCHITECTURE.md для каждого сервиса | Producer Copilot + Validator получили полные ARCHITECTURE.md | Структура документации: 1) Обзор + стек, 2) Переменные окружения, 3) Сервисы/модули с внутренней логикой, 4) API Reference, 5) Ловушки/критические детали. Без этого — каждый новый разработчик тратит часы на реверс-инжиниринг.

---

## PM2 / Деплой

[2026-03-12] pm2 save после каждого pm2 start | `pm2 start server.js --name producer && pm2 save` | После ручного запуска нового процесса — сразу `pm2 save`, иначе после рестарта демона процесс потеряется. Это случилось трижды за день.

---

## Диагностика

[2026-03-10] Неверный порт в factory DB | Pi #9 записан как port 15108 (Pi#10), реальный 15098 (Pi#9) | Factory DB содержит ошибки в маппинге портов. При диагностике ADB подключения — проверять реальный порт через raspberry_port таблицу, не только factory_device_numbers.

[2026-03-10] Параллельный запуск по Pi | ThreadPoolExecutor: группировка аккаунтов по adb_port, один поток = одна малинка | ADB-зависимые задачи нельзя параллелить внутри одного устройства, но можно по разным Pi. При 10 Pi = 10x ускорение.

---

## OpenClaw Server Setup

[2026-03-14] Установка OpenClaw на чистый VPS | Систематика NL сервер поднят с нуля | Правильный порядок: 1) `curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard` 2) `openclaw gateway install` (с PTY `-tt`) 3) `loginctl enable-linger root` 4) `XDG_RUNTIME_DIR=/run/user/0 systemctl --user enable --now openclaw-gateway`. Installer script надёжнее ручного npm + onboard.

[2026-03-14] Bindings в openclaw.json — обязательны | Без bindings все сообщения шли на main (Джони), агенты не отвечали | После добавления Telegram аккаунтов ВСЕГДА создавать bindings array: `{"agentId": "X", "match": {"channel": "telegram", "accountId": "X"}}`. Генерировать через gen_bindings.py.

[2026-03-14] SSHFS для больших данных | RAG venv 7.1GB + 585 транскриптов смонтированы без копирования | Когда данные > 1GB и нужны на другом сервере: sshfs + systemd сервис лучше чем rsync/scp. SSH ключ заранее добавить в authorized_keys источника.

[2026-03-14] Whitelist в office monitor через KNOWN_META | Лишние агенты появлялись из KNOWN_META несмотря на фильтр | Правильный подход: 1) Почистить KNOWN_META от ненужных агентов 2) Удалить их папки из `/root/.openclaw/agents/` — тогда filter не нужен вообще. Фильтр в коде — временный костыль.

[2026-03-14] Скилл после сложной задачи | openclaw-server-setup.skill упаковал все реальные грабли дня | После нетривиальной задачи (новый сервис, новый сервер) — сразу писать скилл пока свежо в памяти. Включать Lessons Learned и Checklist.

---

## Перенос интеграций

[2026-03-15] Telethon сессии перенесены в Систематику | Оба аккаунта доступны агентам | Интеграции переносить как папку целиком (scp -r): config.json + *.session должны быть вместе. Без config.json сессия бесполезна.

[2026-03-15] Статус по проекту без доступа к таскам | Ответил Мише по Validator честно и с оговорками | Когда нет полного контекста по задаче — давать статус по тому что реально знаю + явно указывать что неизвестно. Не придумывать.

---

## OpenClaw / Агенты

[2026-03-16] Перенос агента между серверами | pa-ch перенесён на Систематику за один сеанс | Порядок: 1) rsync воркспейса, 2) добавить в agents.list + channels.telegram + bindings, 3) отключить на источнике (enabled:false), 4) рестарт gateway. Всё через python -c напрямую — надёжнее API.

[2026-03-16] Диагностика 409 Conflict | Нашёл дубликат токена (default + main) в openclaw.json Систематики | При 409 — сначала grep по токену внутри одного конфига: `grep "токен" openclaw.json | wc -l`. Если > 1 — дубль. Удалить duplicate аккаунт, рестартовать gateway.

[2026-03-16] Массовая проверка агентов скриптом | check_agents.py за 5 сек показал статус всех 27 агентов | Паттерн: python3 скрипт через scp + ssh для аудита remote сервера. Проверять: workspace, SOUL.md, shared/RULES.md, memory/, botToken, enabled.

[2026-03-16] Массовое создание shared/RULES.md | 12 агентов Систематики не имели RULES.md — починили одним скриптом | Копировать RULES.md от работающего агента (vseznayka) остальным через shutil.copy в цикле. Не создавать вручную каждый.

[2026-03-16] OpenClaw chatCompletions endpoint | Validator чат-виджет подключён к агенту через /v1/chat/completions | Включить: `gateway.http.endpoints.chatCompletions.enabled = true`. Модель: `"openclaw:agentId"`. Auth: Bearer gateway token. Работает с loopback.

[2026-03-16] Фронт без interceptor = 401 | SupportChat.vue использовал raw axios вместо api клиента — токен не добавлялся | Всегда использовать проектный `api` клиент (с interceptors) вместо raw axios. Проверить: `import api from '@/api/client'`, не `import axios from 'axios'`.

[2026-03-16] MTProto прокси за 2 минуты | telegrammessenger/proxy на VPS, env переменные SECRET/PORT | Для личного Telegram прокси: `docker run -d -p 443:443 -e PORT=443 -e SECRET=$(openssl rand -hex 16) telegrammessenger/proxy`. Ссылка t.me/proxy?... генерируется в логах автоматически.

---

## 2026-03-17

[2026-03-17] Puppeteer тестирование фронта | Нашёл баг с App.vue (onboarding не срабатывал) | Для отладки фронта на сервере: node + puppeteer-core + chromium-browser. Перехватывать API вызовы через page.on('response') — быстро видно что не вызывается и почему.

[2026-03-17] watch на route.path для перезапуска checkAuth | После логина onMounted уже отработал с 401 → onboardingStage оставался 5 | Паттерн: watch(() => route.path, (new, old) => { if (old === '/login') recheckAuth() }) — перезапускать проверку после логина.

[2026-03-17] provide/inject для передачи данных между OnboardingFlow и BrandPage | brandFillPercent передаётся через provide/inject без props | Для передачи данных вверх от дочернего к родителю через уровни: provide функцию-сеттер в родителе, inject в дочернем.

[2026-03-17] Сквозная история чата через БД | validator_support_history хранит переписку по project_id — работает и в виджете и в Telegram | Паттерн: общая таблица истории по project_id + передача последних N сообщений как контекст в system_prompt.

[2026-03-17] Кира — скрипт создания доступа | create_validator_access.py создаёт клиента в Validator по названию проекта, нечёткий поиск | Скрипт тестировать сразу: python3 script.py "Booster cap" → JSON. Нечёткий поиск по api_name + project name.

---

## 2026-03-18

[2026-03-18] Chrome для ADB автоматизации | Регистрация через Chrome вместо Settings | Chrome не блокирует screencap и uiautomator dump. Для любой WebView автоматизации на Samsung — использовать Chrome, не нативные системные экраны.

[2026-03-18] uiautomator dump вместо screencap для навигации | find_in_ui() по text/bounds надёжнее координат | Паттерн: adb_dump_ui() → regex bounds → tap(cx, cy). Координаты из скрина ненадёжны (зависят от DPI, шрифта). uiautomator даёт точные bounds.

[2026-03-18] Деплой скиллов на удалённый сервер через sshpass | zoom-parser + telegram-parser задеплоены в workspace-dinesh/skills/ и workspace-edward/skills/ | sshpass scp file.skill root@host:/path/skills/ — достаточно. Уведомление через botToken агента из openclaw.json того сервера.

[2026-03-18] Субдомен переключён без даунтайма | validator → client.contenthunter.ru | Порядок: 1) DNS уже указывает на сервер 2) Caddy конфиг → systemctl reload caddy → сертификат автоматом. Аудит всех упоминаний старого домена: grep -r "старый.домен" src/ docs/ SOUL.md scripts/

[2026-03-18] Скиллы из рабочего кода — паттерн | gmail/instagram/tiktok/youtube-register.skill из account_factory.py | Рабочий скрипт → скилл: init_skill.py → cp scripts → SKILL.md с быстрым стартом и SQL запросами → package_skill.py. Описание в description YAML — главный триггер, двоеточие внутри → обернуть в кавычки.

---

## 2026-03-19

[2026-03-19] Диагностика через БД при отсутствии лога | account_id=28 не имел данных в factory_reg_accounts → нашёл через SELECT, вручную обновил через UPDATE | Когда скрипт завершился без лога — проверять БД напрямую. UPDATE по gmail/email надёжнее чем повторный запуск.

[2026-03-19] Поиск агента по воркспейсу перед правкой | Проверил /root/.openclaw/agents/ и openclaw.json на Систематике перед переносом | Всегда смотреть workspace в openclaw.json.agents.list, не угадывать путь. Агент может жить в workspace-elena-hr-director, не в workspace-elena.

[2026-03-19] sshpass scp -r для переноса воркспейсов | 9 workspace скопированы с Систематики на CH за один цикл | Паттерн: for ws in list; do sshpass scp -r remote:path/$ws /local/path/; done. Надёжнее rsync когда не нужна синхронизация дельт.

[2026-03-19] Добавление агентов в конфиг через python -c | Обновил openclaw.json: Elena + 4 субагента добавлены через json.load/dump с проверкой existing_ids | Паттерн безопасного обновления: load → modify → validate (python -c json.load) → backup → replace. Никогда не редактировать JSON вручную через sed/awk.

[2026-03-19] Верификация через лог перед записью в БД | Проверил /tmp/factory_task_31.log чтобы понять паттерн успешного выполнения | При отладке скрипта: читать логи предыдущих успешных запусков как эталон. factory_task_{id}.log — основной источник правды для account_factory.py.

---

## 2026-03-20

[2026-03-20] Диагностика пустого canvas в офисе | Нашёл через puppeteer console logs: Mixed Content ws:// blocked | Для отладки WebSocket в браузере: interceptировать page.on('console') — Mixed Content ошибки видны сразу. Симптом: canvas пустой, WS не подключается.

[2026-03-20] Замена execSync на spawn | Сервер перестал зависать | execSync блокирует весь event loop Node.js. Для долгих команд (openclaw sessions, ADB) — только spawn/exec async. Признак проблемы: curl к серверу зависает на N секунд = N таймаут execSync.

[2026-03-20] Мультитенантный офис через /:token роут | Один сервер, много клиентов | Паттерн: `GET /:token` отдаёт тот же HTML, токен читается из `window.location.pathname` через regex. Early return во всех `/api/*` эндпоинтах если есть token — не показывать данные хоста клиенту.

[2026-03-20] Caddy regex роутинг перехватывает /api/* | Убрал regex, оставил один reverse_proxy | Если в Caddy есть `@matcher path_regexp ^/{token}` — он перехватывает /api/agents, /assets/ и т.д. Решение: роутинг по токену делать в самом Node.js сервере, не в Caddy.

[2026-03-20] Подсчёт токенов из JSONL — накопительное значение | totalTokens растёт внутри файла — берём максимум | totalTokens в JSONL строках накопительное. Нельзя суммировать все строки — будет многократное задвоение. Правильно: группировать строки по файлу (маркер type=session), брать max(totalTokens) из каждого файла.

[2026-03-20] Hetzner API для rescue/reset пароля | enable_rescue возвращает root_password | Hetzner API: `POST /v1/servers/{id}/actions/enable_rescue` → `root_password`. Для добавления SSH ключа в существующий аккаунт: `POST /v1/ssh_keys`.

[2026-03-20] Передача задачи агенту через его bot_token | Отправил задачу Динэшу через его Telegram бота | Когда нет активной сессии агента: взять botToken из openclaw.json и отправить через Bot API. chat_id = ID пользователя которому нужно передать задачу.

---

## 2026-03-22

[2026-03-22] Мокап диалога бота для поста | Реконструкция по коду bot.py через HTML+Puppeteer | Когда нет живого скриншота (бот не прошёл тест) — читаем реальные тексты из кода и делаем HTML-мокап. Честно сообщаем что это реконструкция, не скриншот.

[2026-03-22] Скриншот для поста через puppeteer setContent | page.setContent(html) обходит блокировку file:// | При открытии локального HTML через puppeteer: file:// блокируется. Решение: читать файл fs.readFileSync и передавать через page.setContent(). Не нужен локальный HTTP-сервер.

---

## 2026-03-23

[2026-03-23] Передача контекста агенту без доступа к серверу | Отправил полную инструкцию Динэшу через его Telegram бота | Когда нужно передать задачу агенту на другом сервере — использовать его botToken для отправки в Telegram напрямую через Bot API. Формат: python3 urllib.request + urlencode. Не нужен sessions_send.

[2026-03-23] Инструкция как живой документ | Написал инструкцию по офису с путями, кодом и примером теста | Хорошая инструкция включает: 1) где лежат файлы, 2) как работает архитектура, 3) маппинг данных, 4) готовый код copy-paste, 5) рабочий тест для проверки. Без пункта 5 разработчик не знает что "готово".

---

## 2026-03-24

[2026-03-24] Поиск chat_id через сессии других агентов | Нашёл Контактмастерс в сессиях Володи | Когда нужен chat_id группы и getUpdates пустой — искать grep по всем JSONL сессиям: `python3 -c "glob agents/*/sessions/*.jsonl → grep 'контактмастер' → re.findall(-100\d+)"`. Потом проверять через getChat.

[2026-03-24] IF existing_project в скрипте Киры | Скрипт возвращает флаг — SOUL.md выбирает нужный шаблон | Паттерн: скрипт возвращает метаданные (`existing_project`, `onboarding_stage`) → агент сам решает какой текст отправить. Не делать два разных скрипта.

[2026-03-24] Диагностика «бот не отвечает» | За 3 шага: сессии есть → ответ генерится → chat_id не в конфиге | Порядок диагностики бота: 1) ls sessions — новые появляются? 2) Если да — читаем JSONL, ответ есть? 3) Если ответ есть но не доходит — проверяем конфиг групп. Не спрашивать пользователя пока сам не прошёл все 3 шага.

---

## 2026-03-25

[2026-03-25] Диагностика упавших агентов через getMe | Нашёл все протухшие botToken за один скрипт | Паттерн: `for token in all_tokens: curl getMe → 401 = мёртвый`. Быстрее чем читать логи. Применимо для любого кол-ва агентов.

[2026-03-25] Ротация auth-profiles для всех агентов сразу | glob agents/*/agent/auth-profiles.json → обновил order всем | При изменении порядка API ключей — менять и в openclaw.json auth.order И в каждом agents/*/agent/auth-profiles.json. Без второго шага агенты используют старый порядок.

---

## 2026-03-27

[2026-03-27] Диагностика упавшего gateway через ручной запуск | За 1 шаг нашёл точную причину | Когда gateway крашится: запускать вручную `node /usr/lib/node_modules/openclaw/dist/index.js gateway --port N` — сразу виден текст ошибки валидации конфига. Быстрее чем journalctl.

[2026-03-27] Проверка конфига перед перезапуском | Запустил на другом порту, получил ошибку без прерывания работы | Паттерн: проверять конфиг на незанятом порту (18790, 18791) — так не мешает основному процессу и видна валидация.
