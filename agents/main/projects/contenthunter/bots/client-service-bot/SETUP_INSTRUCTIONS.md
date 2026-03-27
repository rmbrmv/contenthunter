# Setup Instructions - Payment OCR Module

## 🚨 Необходимые настройки перед использованием

### 1. Активация Google Cloud Vision API

**Проблема:** `Cloud Vision API has not been used in project 832673742167 before or it is disabled`

**Решение:**

1. Откройте Google Cloud Console:
   https://console.developers.google.com/apis/api/vision.googleapis.com/overview?project=open-bot-487920

2. Нажмите "Enable" (Включить) для активации Vision API

3. Подождите 2-3 минуты для распространения изменений

4. Проверьте квоты:
   https://console.cloud.google.com/apis/api/vision.googleapis.com/quotas?project=open-bot-487920

**Альтернативный способ через gcloud CLI:**

```bash
gcloud services enable vision.googleapis.com --project=open-bot-487920
```

### 2. Настройка Anthropic API Key

**Проблема:** `ANTHROPIC_API_KEY не установлен в .env`

**Решение:**

1. Получите API ключ:
   - Откройте https://console.anthropic.com/
   - Войдите в аккаунт
   - Перейдите в Settings → API Keys
   - Создайте новый ключ или скопируйте существующий

2. Добавьте в `.env`:

```bash
cd /root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot

# Отредактируйте .env
nano .env

# Добавьте строку:
ANTHROPIC_API_KEY=[REDACTED-ANTHROPIC-KEY]
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

3. Или используйте переменную окружения системы:

```bash
export ANTHROPIC_API_KEY="sk-ant-api03-xxxxxxxxxxxx"
```

### 3. Настройка PAYMENTS_CHAT_ID

**Чтобы получить Chat ID:**

1. Добавьте бота в нужный чат
2. Отправьте команду `/chatid`
3. Скопируйте Chat ID из ответа
4. Добавьте в `.env`:

```env
PAYMENTS_CHAT_ID=-1002345678901
PAYMENTS_TOPIC_NAME="Поступления"
```

### 4. Проверка настроек Google Sheets

**Убедитесь что:**

1. Service account имеет доступ к таблице:
   - Email: `openclaw-bot@open-bot-487920.iam.gserviceaccount.com`
   - Права: Editor (Редактор)

2. В таблице есть лист "Оплаты":
   https://docs.google.com/spreadsheets/d/1kMKgKgJKspoSny9rjZ5cKIyhXYe8IrD2Tstal4ZmpzY/edit

3. Структура листа:
   | A: Дата | B: Клиент | C: Сумма | D: Валюта | E: Примечания |

**Если нет доступа:**

```
File → Share → Add people
Введите: openclaw-bot@open-bot-487920.iam.gserviceaccount.com
Права: Editor
```

### 5. Проверка после настройки

```bash
cd /root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot
source venv/bin/activate

# Тест OCR (после активации Vision API)
python -c "from payment_ocr import PaymentOCR; ocr = PaymentOCR(); print('✅ OCR OK')"

# Тест AI парсинга (после добавления ANTHROPIC_API_KEY)
python -c "from ai_parser import AIPaymentParser; parser = AIPaymentParser(); print('✅ AI Parser OK')"

# Тест Google Sheets
python -c "from sheets_writer import SheetsWriter; w = SheetsWriter(); print(f'✅ Sheets OK. Last row: {w.get_last_row_number()}')"

# Полный тест
python test_payment_ocr.py
```

## 📋 Итоговый .env файл

```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Airtable (если используется)
AIRTABLE_API_KEY=your_airtable_key
AIRTABLE_BASE_ID=your_base_id
AIRTABLE_TABLE_ID=your_table_id

# AI Provider
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=[REDACTED-ANTHROPIC-KEY]
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# Or OpenAI alternative:
# AI_PROVIDER=openai
# OPENAI_API_KEY=[REDACTED-API-KEY]
# OPENAI_MODEL=gpt-4-turbo-preview

# Payment OCR
ENABLE_PAYMENT_OCR=true
PAYMENTS_CHAT_ID=-1002345678901
PAYMENTS_TOPIC_NAME=Поступления

# Google Credentials
GOOGLE_APPLICATION_CREDENTIALS=/root/.openclaw/workspace/integrations/google-vision/credentials.json
GOOGLE_SHEETS_SPREADSHEET_ID=1kMKgKgJKspoSny9rjZ5cKIyhXYe8IrD2Tstal4ZmpzY

# Logging
LOG_LEVEL=INFO
```

## 🔍 Troubleshooting

### Vision API всё ещё не работает после активации

**Подождите 5-10 минут** после активации API в консоли.

Если не помогло:

```bash
# Проверьте статус API
gcloud services list --enabled --project=open-bot-487920 | grep vision

# Принудительно включите
gcloud services enable vision.googleapis.com --project=open-bot-487920

# Проверьте квоты
gcloud alpha services quota list --service=vision.googleapis.com --project=open-bot-487920
```

### Anthropic API ошибки

**429 Too Many Requests** - превышен лимит:
- Проверьте квоты: https://console.anthropic.com/
- Подождите или увеличьте лимит

**401 Unauthorized** - неверный ключ:
- Убедитесь что ключ начинается с `sk-ant-api03-`
- Проверьте что ключ активен
- Создайте новый ключ

### Google Sheets Permission Denied

**403 Forbidden:**

```bash
# Проверьте что service account добавлен в таблицу
# Email: openclaw-bot@open-bot-487920.iam.gserviceaccount.com

# Проверьте права:
python -c "
from sheets_writer import SheetsWriter
w = SheetsWriter()
try:
    print(f'Последняя строка: {w.get_last_row_number()}')
    print('✅ Доступ есть')
except Exception as e:
    print(f'❌ Ошибка доступа: {e}')
"
```

## 📞 Поддержка

Если проблемы остались:

1. Проверьте логи: `tail -f logs/bot.log`
2. Запустите debug тесты с подробным выводом
3. Проверьте permissions в Google Cloud Console

---

**Дата создания:** 23.02.2026  
**Версия модуля:** 1.0.0
