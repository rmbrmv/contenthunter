# MEMORY.md — Long-term Memory

## User
- **Имя:** Роман (@rmbrmv)
- **Telegram ID:** 295230564
- **Язык:** русский
- **Проекты:** ContentHunter, Systematika

## Post-Update Procedures
- **После каждого обновления OpenClaw** → поставить задачу Володе-сисадмину (volodya-sisadmin) на проверку работоспособности всех сайтов и сервисов (dashboard, office, HR, agent-office и т.д.)
- Формат: отправить через `sessions_send` задачу с перечнем что проверить

## OpenClaw Rules
- **ЖЕЛЕЗНОЕ ПРАВИЛО**: Перед любой настройкой, конфигом, инструкцией агентам — СНАЧАЛА читай доки (`/usr/lib/node_modules/openclaw/docs/`). Не из головы. Не по памяти. Доки → План → Разрешение → Действие.
- Конфиг меняется между версиями.
- **Никогда не редактировать openclaw.json через json.dump** — использовать CLI-команды (`openclaw agents`, `openclaw channels`). Если только файл — делать бэкап и проверять что gateway не перезапишет.
- **tools.sessions.visibility=all** — нужно ставить явно, после обновления 2026.2.26 дефолт стал `self`
- **tools.agentToAgent удалено** — агент-к-агенту работает через `sessions_send`/`sessions_spawn` из коробки, без config.
- **После любых изменений config** — проверить `openclaw status --deep` что каналы OK.

## Key Decisions
- **Варенька (main agent) — священна**, никогда не модифицировать, не рисковать
- **Hybrid storage**: openclaw.json (только валидные поля OpenClaw) + dashboard-bots.json (metadata, allowlist, avatar, project)
- **Agent-to-agent с проверкой allowlist**: перед делегированием проверять что пользователь есть в allowlist целевого агента
- **Мульти-агенты — изолированные**, каждый со своим workspace, SOUL.md, session store, контекстом токенов

## Infrastructure
- **5 агентов**: main (Варенька), fyodor, genri, elena, client-service
- **Dashboard**: localhost:3000 + Cloudflare tunnel
- **Gateway**: openclaw-gateway (systemd не настроен, запускается вручную)
- Zoom API интеграция уже есть
- Роман хочет интеграции с российскими ВКС (Телемост и др.)

## UI Preferences
- Кнопки одинаковой ширины, 2 колонки
- Проект-бейдж под именем бота
- Токен скрыт
- "Список" → "Доступы"
- Дашборд на русском

## Model Distribution (Feb 2026)
- **Opus:** main (Варенька), misha-metodolog
- **Sonnet:** fyodor, genri, plahov-operdir, dasha-smyslovik, oleg-marketolog, pasha-novostnik
- **Haiku:** kira-pomoschnitsa-km, tolik-algoritmy, elena, li-razvedchitsa, volodya-sisadmin

## Infrastructure Services
- **Soul Watcher** (`soul-watcher.service`): inotify на SOUL.md всех агентов → автосброс сессий. 0 токенов, 0 CPU.

## Agents (20)
- main (Варенька) → default
- fyodor → fyodor-analitik
- genri → genri-dev
- elena → elena-hr
- kira-pomoschnitsa-km → kira-pomoschnitsa-km
- plahov-operdir → plahov-operdir
- dasha-smyslovik → dasha-smyslovik (смысловик/копирайтер)
- oleg-marketolog → ch_marketer_bot
- misha-metodolog → ch_method_bot
- pasha-novostnik → ch_ainews_bot
- tolik-algoritmy → ch_algoritms_bot
- li-razvedchitsa → ch_trend_bot (роль TBD)
- volodya-sisadmin → ch_sisadmin_bot (роль TBD, SOUL.md пустой)
- client-service → УДАЛЁН из config
- Agent-to-agent: enabled=true, allow=["*"]
- olezhka → @sys_metod1_bot (методолог-распаковщик, м, Sonnet, Систематика)
- tanyushka → @sys_metod2_bot (методолог-распаковщик, ж, Sonnet, Систематика)
- alenka → @sys_metod3_bot (методолог-распаковщик, ж, Sonnet, Систематика)
- nik-finmanager → @Sys_findir_bot (финдиректор, ж, Sonnet, Систематика)
- Общая база пользователей: /root/.openclaw/workspace/shared/users.json

## Telegram Parsing
- Telethon session получен и работает
- 14,638 сообщений из 34 чатов Content Hunter в PostgreSQL
- Groq Whisper для голосовых (whisper-large-v3-turbo)
- RAG с pgvector в процессе настройки
- Cron: каждые 3 часа инкрементальный парсинг

## Domains
- **office.contenthunter.ru** → офис агентов (порт 3847)
- **dashboard.contenthunter.ru** → дашборд управления (порт 3000)
- Caddy + auto SSL, DNS через Reg.ru

## Integrations
- Google Docs (Даша): /workspace-dasha-smyslovik/integrations/google-docs/token.json — работает
- Google Sheets (Кира): /workspace-kira-pomoschnitsa-km/integrations/google-sheets/token.json
- HR System: hr.contenthunter.ru порт 3852

## Rules
- **ЗАПРЕТ на установку скиллов из ClawHub** — только подглядывать и воспроизводить у себя, или писать с нуля (05.03)
- **contextPruning: off** — cache-ttl ломает контекст агентов после рестарта gateway (04.03)
- **Таймаут агентов: 1800с** — дефолтные 600с не хватает для ADB-задач (04.03)

## Optimization Rules (10.03)
- **SOUL.md на английском** — все 28 агентов переведены, 351KB→102KB (-71%)
- **File Router Pattern** — тяжёлые скиллы разбиты: SKILL.md ≤ 2KB + reference файлы
- **Memory Hygiene** — заменять, не дополнять. Max 15-20 правил в SOUL.md
- **Anthropic overloaded** — при 8 concurrent + heartbeat + cron = overloaded_error. Решение: снизить concurrent или второй ключ

## Agents (updates 10.03)
- **koordinator** → ОТКЛЮЧЁН, заменён на **redaktor**
- **redaktor** — координатор контент-команды Систематики (Sonnet), topics 7,8 в группе
- Галсон 5agents — купили, изучили, не устанавливали. Анализ в research/galson-5agents/ANALYSIS.md

## TODO
- [x] ~~Посадить дашборд на домен Романа~~
- [x] ~~Добавить токен client-service~~ (удалён)
- [x] ~~Распределение моделей~~
- [x] ~~SOUL.md всех агентов на английский (10.03)~~
- [x] ~~File Router для calculator, market-research, client-weekly-report (10.03)~~
- [ ] SOUL.md для Вовы-сисадмина (ждём описание от Романа)
- [ ] SOUL.md/роль для Ли-разведчицы (ждём от Романа)
- [ ] Интеграции с российскими ВКС
- [ ] RAG embeddings для telegram_messages
- [x] Починить Puppeteer для скриншотов калькулятора (npm install puppeteer в workspace)
- [x] Secrets Migration — 45 токенов на SecretRef (01.03)
- [x] Learning Loop + Memory System + Routing Table для всех агентов (01.03)
- [x] Market Research крон с 7 источниками (01.03)
- [ ] Рассмотреть Opus для Олега, Плахова
- [ ] Model Router (Генри делает) — автороутинг Haiku/Sonnet/Opus
- [ ] Presence Dashboard (Генри делает)
- [ ] Добавить бота Редактора в группу Систематики
- [ ] Решить проблему overloaded_error (concurrent / второй ключ)
- [ ] Внедрить RULE-коррекции и анти-ИИ протокол для контент-команды

## Andclaw (15.03.2026)
- **Решение: пока отказываемся**
- Andclaw (github.com/andforce/Andclaw, 82⭐) — AI-управление Android без ROOT через Accessibility Service
- Требует Android 12+, совместим с Samsung A17 (Android 15) ✅
- Работает без сброса до заводских (Device Owner не нужен для соцсетей)
- AI управляет телефоном (не скрипт) → гибче, но дороже (токены за каждое действие)
- Риск детекта соцсетями: средний (Accessibility Service виден Instagram)
- Отложили: стоимость токенов + нет срочной потребности vs текущих ADB-скиллов
- Вернуться к теме когда: ADB-скиллы начнут ломаться от обновлений Instagram/TikTok

## autowarm — url-poller Instagram: curl вместо https.get (2026-03-23)

**Симптом:** Instagram publish_tasks зависали в `awaiting_url` на часы.
**Причина:** Node.js `https.get` → 429 от Instagram (блокировка по TLS fingerprint). curl → 200.
**Фикс:** `scrapeAllVideos` (server.js, Instagram-блок) переписан на `curl` через `child_process.exec` с iPhone UA + `X-IG-App-ID: 936619743392459`.
**Правило:** Для Instagram API в server.js ВСЕГДА `curl`. `https.get`/`axios`/`fetch` → 429. Коммит `4a20727` в GenGo2/delivery-contenthunter.

## autowarm (delivery.contenthunter.ru) — критические баги навигации (2026-03-23)

Обнаружены и исправлены три взаимосвязанных бага которые приводили к тому что все пункты сайдбаров в интерфейсе не кликались:

1. **Backtick в HELP_CONTENT** — JS SyntaxError ломал nav(). Правило: в HELP_CONTENT нельзя использовать backtick внутри текста (они являются частью template literal).
2. **global-settings не в списках** — при добавлении нового модуля нужно обновлять все 3 места.
3. **ETag кэш** — отключён в express.static, теперь сервер всегда 200.

Все исправления в GenGo2/delivery-contenthunter.
