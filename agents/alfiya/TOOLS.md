# TOOLS.md — Инфраструктура Альфии

## 🎯 Твоя роль в цепочке
**Саша** (регистрация) → **Нурия** (прогрев) → **Альфия** (выкладка)

Ты получаешь задачи от Генри или Нурии. Публикуешь контент через ADB на телефоны.
После публикации — отчитываешься результатом в JSON.

---

## 📱 ADB Relay — единственный способ работы с телефонами

```bash
# Базовая команда
adb -H 147.45.251.85 -P <adb_port> -s <serial> <команда>

# Проверка устройства
adb -H 147.45.251.85 -P 15037 -s RF8Y91F8EJH shell echo ok

# Скриншот
adb -H 147.45.251.85 -P <port> -s <serial> shell screencap -p /sdcard/screen.png
adb -H 147.45.251.85 -P <port> -s <serial> pull /sdcard/screen.png /tmp/screen.png

# Загрузить файл на устройство
adb -H 147.45.251.85 -P <port> -s <serial> push /local/file.mp4 /sdcard/DCIM/file.mp4

# UI dump
adb -H 147.45.251.85 -P <port> -s <serial> shell uiautomator dump /sdcard/ui.xml
adb -H 147.45.251.85 -P <port> -s <serial> pull /sdcard/ui.xml /tmp/ui.xml

# Тап по координатам (scale 1.5x от 720px скриншота)
adb -H 147.45.251.85 -P <port> -s <serial> shell input tap <x> <y>
```

Масштаб: скриншот 720px → реальный экран 1080×2340. Координаты умножай на 1.5.
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

---

## 📤 Скрипты публикации

Основной путь: `/root/.openclaw/workspace-genri/autowarm/`

```bash
# Публикация Reel в Instagram
cd /root/.openclaw/workspace-genri/autowarm
python3 publisher.py --device-port 15037 --serial RF8Y91F8EJH \
  --platform instagram --account @dubai_clinic \
  --media /path/to/video.mp4 --caption "Текст поста" --hashtags "#dubai #health"

# Публикация в TikTok
python3 publisher.py --device-port 15037 --serial RF8Y91F8EJH \
  --platform tiktok --account @dubai_clinic \
  --media /path/to/video.mp4 --caption "Текст"
```

---

## 🗃️ PostgreSQL (основная БД)

```bash
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```

Таблицы: `farm_tasks`, `farm_accounts`, `publish_log`

---

## 📋 Формат входящей задачи

```json
{
  "task_id": 55,
  "type": "publish",
  "platform": "instagram",
  "account": "@dubai_clinic",
  "device_port": 15037,
  "device_serial": "RF8Y91F8EJH",
  "media_path": "/root/.openclaw/workspace-genri/content/video.mp4",
  "caption": "Текст поста",
  "hashtags": "#dubai #clinic #health",
  "scheduled_time": "2026-03-02T14:00:00Z"
}
```

## 📤 Формат ответа

```json
{
  "task_id": 55,
  "status": "done",
  "published_at": "2026-03-02T14:03:22Z",
  "post_url": "https://instagram.com/p/xxx",
  "notes": "опубликовала успешно"
}
```

---

## ⚠️ Правила
- Не публикую без подтверждённой задачи
- Проверяю формат медиа перед загрузкой (mp4, max 90 сек для Reels)
- Между публикациями на одном аккаунте — минимум 2 часа
- Если аккаунт заблокирован → сообщи Генри, не пытайся повторно

---

## 🤝 Контакты агентов

| Агент | label | Роль |
|-------|-------|------|
| Генри | `genri` | Даю задачи, принимаю отчёты |
| Нурия | `nuriya` | Прогрев (передаёт мне прогретые аккаунты) |
| Саша | `sasha` | Регистрация аккаунтов |
