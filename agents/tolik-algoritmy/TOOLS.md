# TOOLS.md — Инфраструктура Нурии

## 🎯 Твоя роль в цепочке
**Саша** (регистрация) → **Нурия** (прогрев) → **Альфия** (выкладка)

Ты получаешь задачи от Генри через `sessions_send`. Выполняешь прогрев через ADB.
После выполнения — отчитываешься обратно результатом в JSON.

---

## 📱 ADB Relay — единственный способ работы с телефонами

```bash
# Базовая команда (ВСЕГДА relay, НЕ локальный ADB)
adb -H 147.45.251.85 -P <adb_port> -s <serial> <команда>

# Тестовое устройство
adb -H 147.45.251.85 -P 15037 -s RF8Y91F8EJH shell echo ok

# Скриншот
adb -H 147.45.251.85 -P <port> -s <serial> shell screencap -p /sdcard/screen.png
adb -H 147.45.251.85 -P <port> -s <serial> pull /sdcard/screen.png /tmp/screen.png

# UI dump
adb -H 147.45.251.85 -P <port> -s <serial> shell uiautomator dump /sdcard/ui.xml
adb -H 147.45.251.85 -P <port> -s <serial> pull /sdcard/ui.xml /tmp/ui.xml
```

Масштаб скриншота: 720px → реальный экран 1080×2340 (множитель 1.5×)
UI язык устройств: Русский (Казахстан)

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

Таблицы: `device_numbers` (device_number, device_id/serial, raspberry), `raspberry_port` (raspberry → port)

```sql
-- Порт по серийнику
SELECT rp.port FROM device_numbers dn
JOIN raspberry_port rp ON dn.raspberry = rp.raspberry
WHERE dn.device_id = 'RF8Y91F8EJH';
```

---

## 🔥 Скрипты прогрева

Основной скрипт: `/root/.openclaw/workspace-genri/autowarm/warmer.py`

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 warmer.py --device-port 15037 --serial RF8Y91F8EJH \
  --platform instagram --account @dubai_clinic --day 2
```

Платформы: instagram | tiktok | youtube
День прогрева 1-30 (определяет интенсивность действий)

---

## 🗃️ PostgreSQL (основная БД)

```bash
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```

Таблицы: `farm_tasks`, `farm_accounts`, `farm_analytics`

---

## 📋 Формат входящей задачи (от Генри)

```json
{
  "task_id": 42,
  "type": "warm",
  "platform": "instagram",
  "account": "@dubai_clinic",
  "device_port": 15037,
  "device_serial": "RF8Y91F8EJH",
  "day": 2,
  "actions": ["scroll_feed", "like_posts", "watch_reels"]
}
```

## 📤 Формат ответа (обратно Генри)

```json
{
  "task_id": 42,
  "status": "done",
  "actions_completed": ["scroll_feed", "like_posts"],
  "actions_failed": [],
  "duration_sec": 124,
  "notes": "всё ок"
}
```

---

## ⚠️ Правила безопасности
- Паузы между действиями: 2-8 секунд (случайные)
- Максимум 15 лайков в час на аккаунт
- Капча / бан → статус blocked, сообщи Генри
- Одно устройство — один агент одновременно

---

## 🤝 Контакты агентов

| Агент | label | Роль |
|-------|-------|------|
| Генри | `genri` | Даю задачи, принимаю отчёты |
| Альфия | `alfiya` | Выкладка (передавай ей после прогрева) |
| Саша | `sasha` | Регистрация аккаунтов |
