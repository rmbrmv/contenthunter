# 📖 Пошаговое руководство по настройке бота

## Шаг 1: Создание Telegram бота

### 1.1. Откройте BotFather
- Откройте Telegram
- Найдите [@BotFather](https://t.me/botfather)
- Отправьте команду `/start`

### 1.2. Создайте нового бота
```
/newbot
```

BotFather спросит имя бота:
```
Alright, a new bot. How are we going to call it? Please choose a name for your bot.
```

Введите, например:
```
ContenHunter Client Service
```

Затем BotFather попросит username:
```
Good. Now let's choose a username for your bot. It must end in `bot`. Like this, for example: TetrisBot or tetris_bot.
```

Введите, например:
```
ch_client_service_bot
```

### 1.3. Сохраните токен

BotFather отправит сообщение вида:
```
Done! Congratulations on your new bot. You will find it at t.me/ch_client_service_bot.

Use this token to access the HTTP API:
1234567890:ABCdefGHIjklMNOpqrsTUVwxyzABCDEFGHI

Keep your token secure and store it safely...
```

**Сохраните этот токен** — он понадобится в `.env` файле.

### 1.4. Настройте бота

Отправьте следующие команды BotFather:

#### Описание бота
```
/setdescription
```
Выберите вашего бота, затем отправьте:
```
Бот-помощник для клиентского сервиса. Автоматически сохраняет материалы от клиентов и отвечает на вопросы.
```

#### О боте
```
/setabouttext
```
```
Автоматическое сохранение материалов и AI-ассистент для клиентского сервиса.
```

#### Команды бота
```
/setcommands
```
Выберите бота и отправьте:
```
start - Начать работу с ботом
help - Список доступных команд
search - Поиск материалов в базе
status - Статистика по материалам
```

#### Privacy Mode (важно!)
```
/setprivacy
```
Выберите бота, затем:
```
Disable
```

Это позволит боту видеть все сообщения в группах.

### 1.5. Готово!
Ваш бот создан. Токен сохранён.

---

## Шаг 2: Настройка Airtable

### 2.1. Создание аккаунта
- Перейдите на [airtable.com](https://airtable.com)
- Зарегистрируйтесь или войдите

### 2.2. Создание базы
1. Нажмите "Add a base"
2. Выберите "Start from scratch"
3. Назовите базу: **"Client Service Bot"**

### 2.3. Создание таблицы
1. Переименуйте первую таблицу в **"Client Materials"**
2. Создайте следующие поля (Add field):

| Имя поля | Тип поля | Настройки |
|----------|----------|-----------|
| **ID** | Autonumber | - |
| **Date** | Date | ✅ Include time |
| **Client** | Single line text | - |
| **Chat ID** | Single line text | - |
| **Type** | Single select | Options: `video`, `photo`, `document`, `link`, `text` |
| **Description** | Long text | - |
| **File URL** | URL | - |
| **Telegram File ID** | Single line text | - |
| **Status** | Single select | Options: `new`, `processing`, `done` |
| **Notes** | Long text | - |

### 2.4. Получение Base ID
1. Откройте вашу базу в браузере
2. URL будет выглядеть так:
   ```
   https://airtable.com/appXXXXXXXXXXXXXX/tblYYYYYYYYYYYYYY
   ```
3. **Base ID** — это часть `appXXXXXXXXXXXXXX`
4. Сохраните его

### 2.5. Создание Personal Access Token
1. Перейдите в [Account settings](https://airtable.com/account)
2. Откройте вкладку "Developer"
3. Нажмите "Create token"
4. Назовите токен: "Client Service Bot"
5. Выберите scopes:
   - `data.records:read`
   - `data.records:write`
   - `schema.bases:read`
6. Выберите доступ к базе "Client Service Bot"
7. Нажмите "Create token"
8. **Скопируйте токен** — он больше не покажется!

Токен выглядит так:
```
patAbCdEfGhIjKlMnOpQrStUvWxYz.1234567890abcdefghijklmnopqrstuvwxyz
```

---

## Шаг 3: Настройка AI провайдера

### Вариант A: Anthropic Claude (рекомендуется)

1. Перейдите на [console.anthropic.com](https://console.anthropic.com)
2. Зарегистрируйтесь / войдите
3. Перейдите в "API Keys"
4. Нажмите "Create Key"
5. Скопируйте ключ (начинается с `sk-ant-api03-...`)

### Вариант B: OpenAI

1. Перейдите на [platform.openai.com](https://platform.openai.com)
2. Зарегистрируйтесь / войдите
3. Перейдите в "API keys"
4. Нажмите "Create new secret key"
5. Скопируйте ключ (начинается с `sk-...`)

---

## Шаг 4: Установка и конфигурация

### 4.1. Установка зависимостей

```bash
cd /root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot/

# Запуск скрипта установки
chmod +x setup.sh
./setup.sh
```

### 4.2. Заполнение .env

Откройте файл `.env`:
```bash
nano .env
```

Заполните обязательные поля:

```env
# Telegram
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyzABCDEFGHI

# Airtable
AIRTABLE_API_KEY=patAbCdEfGhIjKlMnOpQrStUvWxYz.1234567890abcdefg
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
AIRTABLE_TABLE_NAME=Client Materials

# AI Provider
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
ANTHROPIC_MODEL=claude-3-sonnet-20240229

# Security (опционально, но рекомендуется)
# Получите ID чата через @userinfobot
ALLOWED_CHAT_IDS=123456789,987654321
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

### 4.3. Проверка конфигурации

```bash
python check_config.py
```

Вы должны увидеть:
```
✅ ВСЁ ОТЛИЧНО! Бот готов к запуску.
```

Если есть ошибки — исправьте их согласно подсказкам.

---

## Шаг 5: Запуск бота

### 5.1. Первый запуск

```bash
chmod +x run.sh
./run.sh
```

Вы должны увидеть:
```
🚀 Запуск Client Service Bot...
Бот запущен. Провайдер AI: anthropic
Детекция материалов: ✅
AI ассистент: ✅
```

### 5.2. Тестирование

Откройте Telegram и найдите вашего бота.

Отправьте команду:
```
/start
```

Бот должен ответить приветствием.

---

## Шаг 6: Добавление в чаты

### 6.1. Получение Chat ID

1. Добавьте [@userinfobot](https://t.me/userinfobot) в ваш чат
2. Он отправит сообщение с информацией о чате
3. Найдите `Chat ID`, например: `-1001234567890`
4. Удалите @userinfobot из чата

### 6.2. Добавление в allowlist

Добавьте Chat ID в `.env`:
```env
ALLOWED_CHAT_IDS=-1001234567890,-1009876543210
```

Перезапустите бота.

### 6.3. Добавление бота в чат

1. Откройте групповой чат
2. Нажмите на название чата → "Add members"
3. Найдите вашего бота и добавьте
4. **Важно:** Сделайте бота администратором:
   - Нажмите на бота → "Edit Admin Rights"
   - Включите минимально: "Delete messages" (чтобы бот мог читать сообщения)
5. Отправьте `/start` для проверки

### 6.4. Тест детекции материалов

Отправьте в чат:
- Любой файл (фото, видео, документ)
- Или ссылку на Google Drive / Dropbox

Бот должен ответить:
```
✅ Материал сохранён!
Тип: video
Описание: Ваше описание
```

Проверьте Airtable — там должна появиться новая запись.

---

## Шаг 7: Production настройка (опционально)

### Автозапуск через systemd

Создайте файл `/etc/systemd/system/client-bot.service`:

```bash
sudo nano /etc/systemd/system/client-bot.service
```

Содержимое:
```ini
[Unit]
Description=Client Service Telegram Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot
Environment="PATH=/root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot/venv/bin"
ExecStart=/root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Активируйте:
```bash
sudo systemctl daemon-reload
sudo systemctl enable client-bot
sudo systemctl start client-bot
sudo systemctl status client-bot
```

---

## Готово! 🎉

Ваш бот полностью настроен и работает.

### Полезные команды

**Просмотр логов:**
```bash
tail -f logs/bot.log
```

**Перезапуск бота:**
```bash
sudo systemctl restart client-bot
```

**Проверка статуса:**
```bash
sudo systemctl status client-bot
```

**Обновление:**
```bash
git pull
source venv/bin/activate
pip install --upgrade -r requirements.txt
sudo systemctl restart client-bot
```

---

## Поддержка

- **Проблемы с настройкой:** См. раздел FAQ в README.md
- **Логи:** `logs/bot.log`
- **Проверка конфигурации:** `python check_config.py`
