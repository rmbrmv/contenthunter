# 🔐 OpenClaw Dashboard

Безопасный веб-интерфейс для управления Telegram ботами OpenClaw.

## ✨ Возможности

- ✅ Управление Telegram ботами (добавление, удаление, обновление токенов)
- ✅ Управление allowlist пользователей для каждого бота
- ✅ Безопасная аутентификация с bcrypt
- ✅ CSRF protection
- ✅ Rate limiting
- ✅ Доступ только с localhost (127.0.0.1)
- ✅ Современный UI на Tailwind CSS

## 🛡️ Безопасность

Дашборд разработан с акцентом на безопасность:

- **Localhost only**: Сервер слушает только на `127.0.0.1` (никаких внешних подключений)
- **Bcrypt hashing**: Пароли хешируются с использованием bcrypt
- **CSRF protection**: Защита от межсайтовой подделки запросов
- **Rate limiting**: Ограничение количества запросов (защита от brute-force)
- **Express sessions**: Безопасное управление сессиями
- **Input validation**: Валидация всех входных данных

## 📋 Требования

- Node.js 14+ (рекомендуется 18+)
- npm или yarn
- OpenClaw установлен и настроен

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
cd /root/.openclaw/workspace/projects/openclaw-dashboard
npm install
```

### 2. Настройка пароля

**Вариант A: Использовать дефолтный пароль (НЕ ДЛЯ ПРОДАКШЕНА!)**

```bash
cp .env.example .env
```

Дефолтный пароль: `admin123`

**Вариант B: Сгенерировать свой пароль (РЕКОМЕНДУЕТСЯ)**

```bash
# Сгенерировать хеш для вашего пароля
node generate-password.js "ВашСуперСекретныйПароль"

# Скопировать вывод в .env файл
cp .env.example .env
nano .env  # Вставить сгенерированный хеш
```

### 3. Запуск сервера

```bash
npm start
```

Или для разработки:

```bash
npm run dev
```

### 4. Открыть в браузере

Откройте http://127.0.0.1:3000 в браузере

## 📁 Структура проекта

```
openclaw-dashboard/
├── server.js              # Backend сервер (Express)
├── package.json           # npm конфигурация
├── .env                   # Переменные окружения (НЕ коммитить!)
├── .env.example           # Пример конфигурации
├── generate-password.js   # Утилита для генерации хеша пароля
├── README.md              # Эта документация
└── public/                # Frontend файлы
    ├── index.html         # Главная страница (SPA)
    └── js/
        └── app.js         # JavaScript логика
```

## 🔧 Конфигурация

### Переменные окружения (.env)

```env
PORT=3000                                    # Порт сервера
SESSION_SECRET=your-secret-here              # Секрет для сессий
ADMIN_PASSWORD_HASH=$2b$10$...              # Bcrypt хеш пароля
```

### OpenClaw конфиг

Дашборд работает с конфигом OpenClaw: `~/.openclaw/openclaw.json`

Пример структуры:

```json
{
  "agents": {
    "main": {
      "channels": {
        "telegram": {
          "enabled": true,
          "accounts": [
            {
              "name": "Production Bot",
              "token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
              "allowlist": ["123456789", "987654321"]
            }
          ]
        }
      }
    }
  }
}
```

## 🌐 API Endpoints

### Authentication

- `POST /api/auth/login` - Вход в систему
- `POST /api/auth/logout` - Выход
- `GET /api/auth/status` - Проверка статуса авторизации
- `GET /api/csrf-token` - Получение CSRF токена

### Bots Management

- `GET /api/bots` - Список всех ботов
- `POST /api/bots` - Добавить нового бота
- `PUT /api/bots/:id/token` - Обновить токен бота
- `DELETE /api/bots/:id` - Удалить бота

### Allowlist Management

- `GET /api/bots/:id/allowlist` - Получить allowlist бота
- `POST /api/bots/:id/allowlist` - Добавить пользователя в allowlist
- `DELETE /api/bots/:id/allowlist/:userId` - Удалить пользователя из allowlist

## 🔐 Смена пароля

1. Сгенерировать новый хеш:

```bash
node generate-password.js "НовыйПароль123"
```

2. Скопировать вывод в `.env` файл:

```env
ADMIN_PASSWORD_HASH=$2b$10$новый_хеш_здесь
```

3. Перезапустить сервер

## 🐛 Отладка

### Логи

Все действия логируются в консоль:

```bash
npm start
# ✅ Конфиг OpenClaw успешно обновлен
# ✅ Успешный вход в систему
# ⚠️  Неудачная попытка входа
```

### Проблемы с доступом

Если не можете зайти:

1. Проверьте `.env` файл (должен существовать)
2. Проверьте хеш пароля в `.env`
3. Попробуйте сбросить пароль (сгенерируйте новый хеш)

### Проблемы с ботами

Если боты не отображаются:

1. Проверьте путь к `openclaw.json` (по умолчанию: `~/.openclaw/openclaw.json`)
2. Проверьте права доступа к файлу
3. Проверьте структуру JSON (должна соответствовать формату OpenClaw)

## 📊 Rate Limiting

Защита от brute-force атак:

- **API endpoints**: 100 запросов / 15 минут
- **Login endpoint**: 5 попыток / 15 минут

## 🔒 Безопасность в продакшене

### ⚠️ ВАЖНО!

1. **Смените дефолтный пароль!**
2. **Смените `SESSION_SECRET` в `.env`**
3. **Никогда не коммитьте `.env` файл**
4. **Используйте сложный пароль (минимум 12 символов)**
5. **Регулярно обновляйте зависимости**: `npm update`

### Дополнительные меры безопасности

Для еще большей безопасности:

1. **Запуск через SSH tunnel**:
```bash
ssh -L 3000:127.0.0.1:3000 user@server
```

2. **Запуск в Docker** (изоляция):
```bash
# Будет добавлено в будущих версиях
```

3. **Reverse proxy** (Nginx + SSL):
```nginx
# Пример конфига для Nginx
location /openclaw {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
}
```

## 🛠️ Разработка

### Запуск в режиме разработки

```bash
npm run dev
```

### Структура кода

- `server.js`: Backend логика (Express, API endpoints)
- `public/index.html`: UI разметка (Single Page App)
- `public/js/app.js`: Frontend логика (Vanilla JS)

### Добавление новых функций

1. Backend: Добавьте новый endpoint в `server.js`
2. Frontend: Добавьте UI и логику в `app.js`
3. Документация: Обновите README.md

## 📝 Лицензия

MIT License

## 👤 Автор

Создано для OpenClaw

## 🤝 Поддержка

Если возникли проблемы:

1. Проверьте логи в консоли
2. Убедитесь, что OpenClaw правильно установлен
3. Проверьте права доступа к файлам

## 📚 Дополнительные ресурсы

- [OpenClaw Documentation](https://openclaw.org)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Express.js](https://expressjs.com/)
- [Tailwind CSS](https://tailwindcss.com/)

---

**Важно**: Этот дашборд предназначен для локального использования. Не выставляйте его в интернет без дополнительных мер безопасности!
