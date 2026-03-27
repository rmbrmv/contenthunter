# ⚡ Quick Start - Payment OCR Module

## 🚨 3 шага до запуска

### 1️⃣ Активируйте Google Vision API (2 минуты)

**Откройте в браузере:**
```
https://console.developers.google.com/apis/api/vision.googleapis.com/overview?project=open-bot-487920
```

Нажмите **"ENABLE"** (Включить) и подождите 2-3 минуты.

---

### 2️⃣ Добавьте Anthropic API Key

**Получите ключ:**
- https://console.anthropic.com/ → Settings → API Keys

**Добавьте в .env:**
```bash
nano /root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot/.env

# Добавьте строку:
ANTHROPIC_API_KEY=[REDACTED-ANTHROPIC-KEY]
```

Или экспортируйте в систему:
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-xxxxxxxxx"
```

---

### 3️⃣ Получите PAYMENTS_CHAT_ID

**В Telegram:**
1. Добавьте бота в чат "Счета / оплаты / поступления"
2. Отправьте команду: `/chatid`
3. Скопируйте Chat ID (например: `-1002345678901`)

**Добавьте в .env:**
```bash
PAYMENTS_CHAT_ID=-1002345678901
PAYMENTS_TOPIC_NAME=Поступления
ENABLE_PAYMENT_OCR=true
```

---

## ✅ Проверка

```bash
cd /root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot
source venv/bin/activate

# Тест модулей (без записи в Sheets)
python test_payment_ocr.py
```

**Ожидаемый результат:**
```
✅ PASSED: ocr
✅ PASSED: ocr_extraction
✅ PASSED: ai_parsing
✅ PASSED: full_pipeline
```

---

## 🚀 Запуск бота

```bash
python bot.py
```

---

## 📝 Использование

1. Отправьте скриншот платёжки в чат "Счета / оплаты / поступления" → топик "Поступления"
2. Бот автоматически:
   - Распознает текст (OCR)
   - Извлечёт данные (дата, клиент, сумма, валюта)
   - Запишет в Google Sheets
   - Выделит строку синим
   - Ответит с номером строки

**Пример ответа:**
```
✅ Платёж добавлен в таблицу!

Клиент: Content Hunter
Сумма: 50,000₽
Дата: 23.02.2026

📊 Строка №15 (выделена синим)
🔗 Открыть таблицу
```

---

## 🐛 Проблемы?

**Vision API не работает:**
- Подождите 5-10 минут после активации
- Проверьте квоты: https://console.cloud.google.com/apis/api/vision.googleapis.com/quotas?project=open-bot-487920

**AI парсинг падает:**
- Проверьте `echo $ANTHROPIC_API_KEY`
- Убедитесь что ключ начинается с `sk-ant-api03-`

**Нет доступа к Sheets:**
- Добавьте service account в таблицу:
  - Email: `openclaw-bot@open-bot-487920.iam.gserviceaccount.com`
  - Права: Editor
  - Таблица: https://docs.google.com/spreadsheets/d/1kMKgKgJKspoSny9rjZ5cKIyhXYe8IrD2Tstal4ZmpzY/edit

---

## 📚 Документация

- **Полная документация:** `README_PAYMENT_OCR.md`
- **Настройка:** `SETUP_INSTRUCTIONS.md`
- **Пример .env:** `.env.example`
- **Итоги:** `PAYMENT_OCR_SUMMARY.md`

---

## 🎯 Готово!

После выполнения 3 шагов выше модуль полностью готов к работе.

**Время настройки:** ~5 минут  
**Поддержка:** Все логи в `logs/bot.log`
