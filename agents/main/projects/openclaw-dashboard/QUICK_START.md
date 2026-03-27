# 🚀 Quick Start - OpenClaw Dashboard v2.0

## Запуск

```bash
cd /root/.openclaw/workspace/projects/openclaw-dashboard
node server.js
```

## Доступ

- **URL:** http://127.0.0.1:3000
- **Пароль:** `admin123`

## API Endpoints

### Основные операции

```bash
# Получить список ботов
GET /api/bots

# Добавить нового бота
POST /api/bots
{
  "name": "Новый бот",
  "token": "123456789:ABC...",
  "project": "contenthunter",
  "description": "Описание"
}

# Обновить бота
PUT /api/bots/:id
{
  "name": "Обновленное имя",
  "token": "...",
  "project": "systematika",
  "description": "...",
  "avatar": "..."
}

# Удалить бота
DELETE /api/bots/:id
```

### Управление доступом

```bash
# Получить allowlist
GET /api/bots/:id/allowlist

# Добавить пользователя
POST /api/bots/:id/allowlist
{ "userId": "123456789" }

# Удалить пользователя
DELETE /api/bots/:id/allowlist/:userId
```

### Входящие запросы

```bash
# Получить pending requests
GET /api/bots/:id/pending

# Одобрить запрос
POST /api/bots/:id/pending/approve
{ "userId": "987654321" }
```

## Структура файлов

```
/root/.openclaw/
├── openclaw.json                          # Главный конфиг OpenClaw
│   └── channels.telegram.accounts[id]    # Боты (name, token, policies)
│
└── workspace/projects/openclaw-dashboard/
    ├── server.js                         # Бэкенд сервер
    ├── dashboard-bots.json               # Metadata (allowlist, project, etc)
    ├── public/
    │   ├── index.html                    # Frontend
    │   └── js/app.js                     # Frontend логика
    └── .env                              # Пароль администратора
```

## Тестирование

```bash
# Запустить полные тесты
/tmp/test-dashboard-full.sh

# Тесты записи (CRUD)
/tmp/test-dashboard-write.sh

# Edge cases
/tmp/test-edge-cases.sh
```

## Важные детали

### ID Mapping
- **botId** (0, 1, 2...) - индекс в API
- **accountId** ("fyodor-analitik", "genri-dev"...) - ключ в конфигах

### Данные разделены
- **openclaw.json:** технические данные (token, policies)
- **dashboard-bots.json:** дополнительные данные (allowlist, project, description, avatar)

### Безопасность
- CSRF токены на всех write операциях
- Session-based авторизация
- Rate limiting (100 req/15min)
- bcrypt для паролей

## Статус

✅ Все endpoints работают  
✅ Все тесты пройдены (100%)  
✅ Frontend доступен  
✅ Данные корректно сохраняются  

**Production Ready!**
