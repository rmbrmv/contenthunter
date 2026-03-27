# 🤖 Client Service Bot

Telegram бот-помощник для клиентского сервиса продакшн-студии.

## Возможности

### 📥 Автоматическое сохранение материалов
- Детекция файлов (видео, фото, документы)
- Распознавание ссылок на облачные хранилища
- Поиск ключевых слов ("материал", "бриф", "референс")
- Автоматическое сохранение в Airtable
- Подтверждение получения материалов

### 🤖 AI-ассистент
- Ответы на вопросы о процессах работы
- Поиск по базе материалов
- FAQ из базы знаний
- Интеграция с Claude/OpenAI

### 🔍 Команды бота
- `/start` - Начало работы
- `/help` - Список команд
- `/search [запрос]` - Поиск материалов
- `/status` - Статистика по материалам

## Технологии

- Python 3.11+
- python-telegram-bot 20.7
- Airtable API (pyairtable)
- OpenAI / Anthropic Claude
- PostgreSQL (опционально)
- Loguru для логирования

## Установка

### 1. Клонирование и зависимости

```bash
cd /root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot/

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
```

### 2. Создание бота в Telegram

1. Откройте [@BotFather](https://t.me/botfather) в Telegram
2. Отправьте `/newbot`
3. Введите имя бота (например: "ContenHunter Client Bot")
4. Введите username бота (например: "ch_client_bot")
5. Сохраните полученный **токен** — он понадобится для настройки

**Дополнительные настройки:**
```
/setdescription - Бот-помощник для клиентского сервиса
/setabouttext - Автоматическое сохранение материалов и AI-ассистент
/setprivacy - DISABLED (чтобы бот видел все сообщения в группах)
```

### 3. Настройка Airtable

1. Зайдите на [airtable.com](https://airtable.com)
2. Создайте новую базу: **"Client Service Bot"**
3. Создайте таблицу **"Client Materials"** со следующими полями:

| Field Name | Field Type | Options |
|------------|------------|---------|
| ID | Auto number | |
| Date | Date | Include time |
| Client | Single line text | |
| Chat ID | Single line text | |
| Type | Single select | video, photo, document, link, text |
| Description | Long text | |
| File URL | URL | |
| Telegram File ID | Single line text | |
| Status | Single select | new, processing, done |
| Notes | Long text | |

4. Получите API credentials:
   - Перейдите в [Account settings](https://airtable.com/account)
   - Создайте Personal Access Token с правами:
     - `data.records:read`
     - `data.records:write`
     - `schema.bases:read`
   - Скопируйте Base ID (из URL базы: `https://airtable.com/appXXXXXXXXXXXXXX`)

### 4. Настройка AI провайдера

#### Вариант A: Anthropic Claude (рекомендуется)
1. Зайдите на [console.anthropic.com](https://console.anthropic.com)
2. Создайте API key
3. Скопируйте ключ

#### Вариант B: OpenAI
1. Зайдите на [platform.openai.com](https://platform.openai.com)
2. Создайте API key
3. Скопируйте ключ

### 5. Конфигурация

Создайте файл `.env` на основе `.env.example`:

```bash
cp .env.example .env
nano .env
```

Заполните обязательные поля:

```env
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Airtable
AIRTABLE_API_KEY=patAbCdEfGhIjKlMnOpQrStUvWxYz.1234567890abcdefg
AIRTABLE_BASE_ID=appAbCdEfGhIjKlMn
AIRTABLE_TABLE_NAME=Client Materials

# AI Provider (выберите один)
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx

# Security (необязательно, но рекомендуется)
ALLOWED_CHAT_IDS=123456789,987654321
```

**Получение Chat ID:**
1. Добавьте бота [@userinfobot](https://t.me/userinfobot) в чат
2. Он покажет ID чата
3. Или используйте [@raw_data_bot](https://t.me/raw_data_bot)

### 6. Запуск

```bash
# Активация виртуального окружения
source venv/bin/activate

# Запуск бота
python bot.py
```

**Логи будут в:** `logs/bot.log`

### 7. Добавление бота в чаты

1. Создайте групповой чат для клиента
2. Добавьте бота в чат: Add Members → @your_bot_username
3. **Важно:** Сделайте бота администратором, чтобы он мог читать все сообщения
4. Отправьте `/start` для проверки

## Использование

### Для клиентов

**Отправка материалов:**
- Просто загрузите файл в чат
- Или отправьте ссылку на Google Drive / Dropbox
- Добавьте описание в caption (подпись к файлу)
- Бот автоматически сохранит всё

**Примеры:**
```
[Отправка видео с caption: "Исходник для монтажа"]
✅ Материал сохранён!
Тип: video
Описание: Исходник для монтажа

[Отправка ссылки]
https://drive.google.com/file/d/xxxxx
+ текст: "Референсы для проекта"
✅ Материал сохранён!
```

**Вопросы:**
```
@bot_name Сколько времени займёт монтаж?
🤖 Обычно монтаж занимает 2-5 дней...

/search логотип
🔍 Найдено материалов: 2
1. [photo] Логотип компании...
2. [document] Бренд-бук с логотипом...
```

### Для менеджеров

**Проверка статистики:**
```
/status

📊 Статистика материалов
Всего: 15

По типам:
  • video: 5
  • photo: 7
  • document: 3

По статусам:
  • new: 8
  • processing: 4
  • done: 3
```

**Общение с AI:**
```
@bot_name Как работает процесс правок?

🤖 Процесс правок:
1. Клиент описывает, что нужно исправить
2. Команда вносит правки в течение 1-2 дней
3. Стандартно включено 2 итерации правок
...
```

## Структура проекта

```
client-service-bot/
├── bot.py                  # Главный файл запуска
├── config.py               # Конфигурация
├── message_handler.py      # Обработка сообщений
├── airtable_client.py      # Работа с Airtable
├── ai_assistant.py         # AI-ассистент
├── requirements.txt        # Зависимости Python
├── .env.example            # Шаблон настроек
├── .env                    # Ваши настройки (не коммитить!)
├── README.md               # Документация
├── knowledge/              # База знаний
│   ├── faq.md             # FAQ
│   ├── processes.md       # Процессы работы
│   └── templates/         # Шаблоны сообщений
└── logs/                   # Логи бота
```

## Расширенная настройка

### PostgreSQL (опционально)

Для production рекомендуется добавить PostgreSQL для логирования:

```bash
# Установка PostgreSQL
sudo apt install postgresql postgresql-contrib

# Создание базы
sudo -u postgres psql
CREATE DATABASE client_service_bot;
CREATE USER botuser WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE client_service_bot TO botuser;
\q

# В .env
DATABASE_URL=postgresql://botuser:secure_password@localhost:5432/client_service_bot
```

### Systemd service (автозапуск)

Создайте файл `/etc/systemd/system/client-bot.service`:

```ini
[Unit]
Description=Client Service Telegram Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot
Environment="PATH=/root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot/venv/bin"
ExecStart=/root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Запуск:
```bash
sudo systemctl enable client-bot
sudo systemctl start client-bot
sudo systemctl status client-bot
```

### Docker (альтернатива)

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

```bash
docker build -t client-service-bot .
docker run -d --name client-bot --env-file .env client-service-bot
```

## Безопасность

✅ **Рекомендуется:**
- Используйте `ALLOWED_CHAT_IDS` для ограничения доступа
- Храните `.env` в секрете (добавьте в `.gitignore`)
- Регулярно обновляйте зависимости: `pip install --upgrade -r requirements.txt`
- Настройте backup Airtable базы
- Ограничьте права Airtable токена (только нужные таблицы)

⚠️ **Не делайте:**
- Не коммитьте `.env` в Git
- Не публикуйте токены и API ключи
- Не отключайте логирование
- Не запускайте бота с root правами

## Мониторинг

### Логи

```bash
# Последние 50 строк
tail -n 50 logs/bot.log

# Отслеживание в реальном времени
tail -f logs/bot.log

# Поиск ошибок
grep ERROR logs/bot.log
```

### Метрики (TODO)

- Количество обработанных сообщений
- Время ответа AI
- Количество сохранённых материалов
- Статистика по типам материалов

## Обновление

```bash
git pull  # Если используете Git
source venv/bin/activate
pip install --upgrade -r requirements.txt
sudo systemctl restart client-bot  # Если используете systemd
```

## FAQ

**Q: Бот не отвечает в группе**
A: Убедитесь, что бот является администратором и privacy mode отключен (`/setprivacy` в BotFather)

**Q: Ошибка Airtable API**
A: Проверьте права доступа Personal Access Token и правильность Base ID

**Q: AI не отвечает**
A: Проверьте баланс на аккаунте OpenAI/Anthropic и правильность API ключа

**Q: Как добавить новые команды?**
A: Редактируйте `message_handler.py`, добавьте обработчик в `handle_command()`

**Q: Можно ли использовать другой AI провайдер?**
A: Да, добавьте новый провайдер в `ai_assistant.py` по аналогии с существующими

## Поддержка

- **Документация:** См. этот README
- **Логи:** `logs/bot.log`
- **База знаний:** `knowledge/`

## Лицензия

Proprietary - ContenHunter Studio

---

**Версия:** 1.0.0  
**Дата:** 2024  
**Автор:** AI Assistant для ContenHunter Studio
