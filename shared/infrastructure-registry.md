# Infrastructure Registry — Реестр сервисов и доступов

> Все агенты обязаны регистрировать здесь созданные сервисы и доступы.
> Володя-сисадмин ежедневно проверяет работоспособность всего из этого списка.

## Формат записи

```
### [Название сервиса]
- **URL:** [endpoint]
- **Тип:** API key / OAuth / login-password / SSH / token
- **Credentials:** [путь к файлу с ключами]
- **Создал:** [кто]
- **Дата:** YYYY-MM-DD
- **Срок действия:** [если есть]
- **Статус:** ✅ работает / ⚠️ проверить / ❌ не работает
- **Последняя проверка:** YYYY-MM-DD
```

---

## Сервисы

### Dashboard (управление агентами)
- **URL:** https://dashboard.contenthunter.ru (localhost:3000)
- **Тип:** Web UI
- **Credentials:** —
- **Создал:** Генри
- **Статус:** ✅ работает (HTTP 200)
- **Последняя проверка:** 2026-03-23 02:00 UTC

### Office (виртуальный офис агентов)
- **URL:** https://office.contenthunter.ru (localhost:3847)
- **Тип:** Web UI
- **Credentials:** —
- **Создал:** Марк/Генри
- **Статус:** ✅ работает (HTTP 200)
- **Последняя проверка:** 2026-03-23 02:00 UTC

### HR System
- **URL:** https://hr.contenthunter.ru (localhost:3852)
- **Тип:** Web UI
- **Credentials:** —
- **Создал:** Генри
- **Статус:** ✅ работает (HTTP 302 redirect OK)
- **Последняя проверка:** 2026-03-23 02:00 UTC

### Google Calendar (Варенька)
- **URL:** Google Calendar API
- **Тип:** OAuth token
- **Credentials:** /root/.openclaw/workspace/integrations/google-calendar/token.json
- **Создал:** Варенька
- **Статус:** ❌ КРИТИЧНО: token EXPIRED (истёк более 22 дня назад)
- **Последняя проверка:** 2026-04-01 02:00 UTC
- **Требуется:** Ручная переавторизация через OAuth consent screen

### Google Docs (Даша)
- **URL:** Google Docs API
- **Тип:** OAuth token
- **Credentials:** /root/.openclaw/workspace-dasha-smyslovik/integrations/google-docs/token.json
- **Создал:** Даша
- **Статус:** ⚠️ ПРОВЕРИТЬ: expires_at=null в файле, но refresh_token присутствует. Может потребоваться переавторизация.
- **Последняя проверка:** 2026-04-03 02:00 UTC

### Google Sheets (Кира)
- **URL:** Google Sheets API
- **Тип:** OAuth token
- **Credentials:** /root/.openclaw/workspace-kira-pomoschnitsa-km/integrations/google-sheets/token.json
- **Создал:** Кира
- **Статус:** ❌ КРИТИЧНО: token EXPIRED (истёк более 22 дня назад)
- **Последняя проверка:** 2026-04-01 02:00 UTC
- **Требуется:** Ручная переавторизация через OAuth consent screen

### Zoom API (Account 1 — Роман)
- **URL:** Zoom API
- **Тип:** OAuth
- **Credentials:** /root/.openclaw/workspace/shared/scripts/zoom_transcribe.py (встроенные)
- **Создал:** Варенька
- **Статус:** ✅ работает

### Zoom API (Account 3 — Kirill Popov)
- **URL:** Zoom API
- **Тип:** OAuth
- **Credentials:** /root/.openclaw/workspace/integrations/zoom_account3/config.json
- **Создал:** Варенька
- **Статус:** ✅ работает

### Telethon (Telegram parser)
- **URL:** Telegram MTProto
- **Тип:** Session + API credentials
- **Credentials:** /root/.openclaw/workspace/.telegram/config.json + session.session
- **Создал:** Варенька
- **Статус:** ✅ работает

### LaoZhang API (GPT-4o proxy)
- **URL:** https://api.laozhang.ai/v1
- **Тип:** API key
- **Credentials:** openclaw.json (models.providers.laozhang)
- **Создал:** Варенька
- **Статус:** ✅ работает

### PostgreSQL (mymeet)
- **URL:** localhost:5432
- **Тип:** login-password
- **Credentials:** user=openclaw, db=openclaw
- **Создал:** система
- **Статус:** ✅ работает (LiteLLM таблицы OK, контейнер up 3+ недели)
- **Последняя проверка:** 2026-03-23 02:00 UTC

---
_Последнее обновление: 2026-04-01 02:00 UTC_

## rizz.market — проект MP2
- **URL:** https://app.rizz.market
- **Логин:** +79226827222
- **Пароль:** HiqyXuXVvfkymQ3
- **Источник:** Зуфар Гарипов (@Faspid), 10.03.2026
- **Ответственный агент:** Яна (yan)

## Anthropic API Key #2 (резервный)
- **Добавлен:** 2026-03-13
- **Статус:** сохранён, НЕ подключён
- **Файл:** /root/.openclaw/credentials/anthropic-key-2.txt
- **Назначение:** TBD (второй ключ для распределения нагрузки / решение overloaded_error)
 68% used (105G of 154G)
- **Статус:** ✅ OK (в норме)
- **Рекомендация:** мониторить, очищать логи при ~70%
- **Последняя проверка:** 2026-03-23 02:00 UTC

### Открытые порты
- **HTTP (80):** ✅ слушает
- **HTTPS (443):** ✅ слушает
- **PostgreSQL (5432):** ✅ слушает
- **API (8000):** ✅ слушает
- **Services (3000, 3847, 3850, 3851, 3852):** ✅ все слушают
- **Последняя проверка:** 2026-03-16 02:00 UTC

### OpenClaw Gateway
- **Статус:** ✅ systemd installed · enabled · running
- **Agents:** 67 detected · 145 sessions active
- **Memory:** sources ready · vector ready · fts ready
- **Heartbeat:** 1h (main)
- **Последняя проверка:** 2026-03-27 02:00 UTC
- **⚠️ SECURITY:** 7 critical, 4 warn findings (open groupPolicy, Telegram DMs, wildcard allowlist). Требует внимания.

### PM2 services
- **autowarm:** ✅ online (uptime 2D, 71 restarts)
- **ch-auth:** ✅ online (uptime 5D, 4 restarts)
- **office:** ✅ online (uptime 5D, 21 restarts)
- **office2:** ✅ online (uptime 8D, 7 restarts)
- **producer:** ✅ online (uptime 10D, 0 restarts)
- **validator:** ✅ online (uptime 14h, 0 restarts)
- **Последняя проверка:** 2026-03-23 02:00 UTC

### Docker containers
- **openclaw-postgres:** ✅ Up 4 weeks (0.0.0.0:5432→5432)
- **telegram-mtproto:** ✅ Up 4 weeks (0.0.0.0:8443→443)
- **Последняя проверка:** 2026-03-23 02:00 UTC

### Systemd services
- **agent-office:** ✅ active · enabled (since 2026-03-13 08:05, 14D uptime)
- **caddy:** ✅ active · enabled (since 2026-03-18 10:34, 9D uptime)
- **Последняя проверка:** 2026-03-27 02:00 UTC

### Open ports
- **HTTP (80):** ✅ caddy listening
- **HTTPS (443):** ✅ caddy listening
- **PostgreSQL (5432):** ✅ docker-proxy listening
- **API (8000):** ✅ uvicorn listening
- **Services (3000, 3847, 3850, 3851, 3852):** ✅ all listening
- **Последняя проверка:** 2026-03-20 02:00 UTC



## rizz.market — проект MP2
- **URL:** https://app.rizz.market
- **Логин:** +79226827222
- **Пароль:** HiqyXuXVvfkymQ3
- **Источник:** Зуфар Гарипов (@Faspid), 10.03.2026
- **Ответственный агент:** Яна (yan)

## Anthropic API Key #2 (резервный)
- **Добавлен:** 2026-03-13
- **Статус:** сохранён, НЕ подключён
- **Файл:** /root/.openclaw/credentials/anthropic-key-2.txt
- **Назначение:** TBD (второй ключ для распределения нагрузки / решение overloaded_error)
als/anthropic-key-2.txt
- **Назначение:** TBD (второй ключ для распределения нагрузки / решение overloaded_error)
�юч для распределения нагрузки / решение overloaded_error)
aded_error)
рузки / решение overloaded_error)
ed_error)
