# TOOLS.md — Инфраструктура Саши

## 🎯 Твоя роль в цепочке
**Саша** (регистрация) → **Нурия** (прогрев) → **Альфия** (выкладка)

Ты регистрируешь новые аккаунты через UI телефона по ADB.
Получаешь задачи от Романа или Генри. После регистрации — передаёшь данные Нурии.

---

## 📱 ADB Relay

```bash
# Единственный способ работы с телефонами — relay
adb -H 147.45.251.85 -P <adb_port> -s <serial> <команда>

# Тестовое устройство
adb -H 147.45.251.85 -P 15037 -s RF8Y91F8EJH shell echo ok
```

Масштаб скриншота: 720px → реальный экран 1080×2340 (множитель 1.5×)
UI язык устройств: Русский (Казахстан)

---

## 🏭 Account Factory — основной скрипт регистрации

**Путь:** `/root/.openclaw/workspace-genri/autowarm/account_factory.py`

### Запуск

```bash
cd /root/.openclaw/workspace-genri/autowarm

# Полный цикл: Gmail + Instagram + TikTok + YouTube
python3 account_factory.py --device RF8Y91F8EJH --adb-port 15037

# Только один шаг
python3 account_factory.py --device RF8Y91F8EJH --adb-port 15037 --step gmail
python3 account_factory.py --device RF8Y91F8EJH --adb-port 15037 --step instagram
python3 account_factory.py --device RF8Y91F8EJH --adb-port 15037 --step tiktok
python3 account_factory.py --device RF8Y91F8EJH --adb-port 15037 --step youtube
```

### Что делает скрипт
1. **Генерирует персону** — имя, фамилия, дата рождения, пароль, username
2. **create_gmail()** — регистрирует Google аккаунт через Settings → Add account
3. **register_instagram()** — регистрирует Instagram через APK
4. **register_tiktok()** — регистрирует TikTok через APK
5. **create_youtube_channel()** — создаёт YouTube канал через Gmail
6. **Сохраняет** все данные в PostgreSQL (`farm_accounts`)

### Верификация

**SMS-код (SIM карта):**
```python
# Скрипт читает SMS автоматически через ADB
code = factory.read_sms_code(timeout=90)
# Ищет 6-значный код в content://sms/inbox
```

**Email-код (письмо от Google):**
```python
# Открывает Gmail app, читает код из UI dump
code = factory.read_email_code_from_gmail_app(sender_keyword="Google", timeout=120)
```

Если код не пришёл за timeout — скрипт логирует ошибку, сообщи Генри.

---

## 🗄️ Factory DB (список устройств, readonly)

```python
import psycopg2
conn = psycopg2.connect(
    host="193.124.112.222", port=49002,
    dbname="factory", user="roman_ai_readonly",
    password="Bo37H#Kla8dl0chQnL0@3jSlcY"
)
```

```sql
-- Свободные устройства (без активной задачи)
SELECT dn.device_id, rp.port
FROM device_numbers dn
JOIN raspberry_port rp ON dn.raspberry = rp.raspberry
WHERE dn.device_id NOT IN (
  SELECT device_serial FROM autowarm_tasks WHERE status IN ('running','delegated')
)
LIMIT 5;
```

---

## 🗃️ PostgreSQL (основная БД)

```bash
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```

После регистрации аккаунт автоматически сохраняется в `farm_accounts`.
Проверить:
```sql
SELECT id, username, platform, status, device_id, created_at
FROM farm_accounts ORDER BY created_at DESC LIMIT 10;
```

---

## 📋 Формат входящей задачи (от Генри)

```json
{
  "task_id": 10,
  "type": "register",
  "device_serial": "RF8Y91F8EJH",
  "device_port": 15037,
  "platforms": ["gmail", "instagram", "tiktok", "youtube"],
  "count": 1,
  "from_agent": "genri"
}
```

## 📤 Формат ответа (обратно Генри)

```json
{
  "task_id": 10,
  "status": "done",
  "accounts": [
    {
      "gmail": "alex.smith1234@gmail.com",
      "gmail_password": "Xk9mW3!qP",
      "instagram": "@alex_smith_uae",
      "tiktok": "@alexsmith_cool",
      "youtube": "Alex Smith",
      "device_serial": "RF8Y91F8EJH"
    }
  ],
  "notes": "всё зарегистрировано, SMS пришёл"
}
```

После успешной регистрации — передай данные Нурии для прогрева:
```
sessions_send(sessionKey="agent:tolik-algoritmy:main", message=task_json)
```

---

## ⚠️ Правила
- Один аккаунт = одно устройство = одна SIM карта
- Между регистрациями на одном устройстве — минимум 30 минут
- Если Google просит верификацию по телефону — скрипт читает SMS автоматически
- Если капча или блокировка — остановись, сообщи Генри
- Пароли и данные аккаунтов — только в личку Роману, не в группы

---

## 🤝 Контакты агентов

| Агент | sessionKey | Роль |
|-------|-----------|------|
| Генри | `agent:genri:main` | Даю задачи, принимаю отчёты |
| Нурия | `agent:tolik-algoritmy:main` | Прогрев (передавай ей после регистрации) |
| Альфия | `agent:alfiya:main` | Выкладка контента |

---

## 📲 register_social.py — регистрация соцсетей на готовый Gmail

**Путь:** `/root/.openclaw/workspace-genri/autowarm/register_social.py`

Используй этот скрипт когда Gmail уже создан — нужно только зарегистрировать соцсети.

### Запуск

```bash
cd /root/.openclaw/workspace-genri/autowarm

# Instagram + TikTok + YouTube на готовый Gmail
python3 register_social.py \
  --device RF8Y91F8EJH --adb-port 15037 \
  --gmail user@gmail.com --password Passw0rd! \
  --name "Alex Smith" \
  --platforms instagram tiktok youtube

# Только Instagram
python3 register_social.py \
  --device RF8Y91F8EJH --adb-port 15037 \
  --gmail user@gmail.com --password Passw0rd! \
  --name "Alex Smith" \
  --platforms instagram

# Только TikTok + YouTube
python3 register_social.py \
  --device RF8Y91F8EJH --adb-port 15037 \
  --gmail user@gmail.com --password Passw0rd! \
  --name "Alex Smith" \
  --platforms tiktok youtube
```

### Что делает
1. Принимает готовый Gmail — не создаёт новый
2. Регистрирует Instagram через email (тот же Gmail)
3. Регистрирует TikTok через email (тот же Gmail)
4. Создаёт YouTube канал (Gmail уже залогинен на устройстве)
5. Читает SMS/email коды автоматически при верификации
6. Сохраняет результат в БД (`farm_accounts`)

### Если нужна верификация с почты
Скрипт сам читает код — либо из SMS (SIM карта), либо из Gmail app на устройстве.
Если код не пришёл за 90 сек → ошибка в логе → сообщи Генри.
