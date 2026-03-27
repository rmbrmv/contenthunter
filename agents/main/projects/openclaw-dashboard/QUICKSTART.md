# ⚡ Быстрый старт за 2 минуты

## Шаг 1: Установка (30 секунд)

```bash
cd /root/.openclaw/workspace/projects/openclaw-dashboard
npm install
```

## Шаг 2: Запуск (5 секунд)

```bash
./START.sh
```

Или:

```bash
npm start
```

## Шаг 3: Вход (30 секунд)

1. Откройте http://127.0.0.1:3000
2. Введите пароль: **admin123**
3. Нажмите "Войти"

## Шаг 4: Смена пароля (1 минута)

⚠️ **ОБЯЗАТЕЛЬНО!** Сразу после входа смените пароль:

```bash
# В новом терминале
cd /root/.openclaw/workspace/projects/openclaw-dashboard
node generate-password.js "ВашНовыйСуперПароль123"

# Скопируйте вывод в .env файл
nano .env
# Замените ADMIN_PASSWORD_HASH на новый

# Перезапустите сервер (Ctrl+C в первом терминале, затем ./START.sh)
```

---

## 🎯 Основные возможности

### Добавить бота

1. Нажмите "+ Добавить бота"
2. Введите название (например, "Production Bot")
3. Вставьте токен от [@BotFather](https://t.me/BotFather)
4. Нажмите "Добавить"

### Управление allowlist

1. Нажмите "Управление доступом" на карточке бота
2. Введите Telegram User ID
3. Нажмите "Добавить"

### Получить Telegram User ID

Напишите боту [@userinfobot](https://t.me/userinfobot) в Telegram - он покажет ваш ID

---

## 🔒 Безопасность

✅ **Что уже защищено:**
- Доступ только с localhost
- Bcrypt хеширование паролей
- CSRF protection
- Rate limiting (защита от brute-force)
- Автоматическое истечение сессий

⚠️ **Что нужно сделать:**
- [ ] Смените пароль (см. Шаг 4)
- [ ] Смените SESSION_SECRET в .env
- [ ] Не выставляйте порт в интернет
- [ ] Используйте SSH туннель для удаленного доступа

---

## 📁 Структура файлов

```
openclaw-dashboard/
├── server.js           # Backend (Express API)
├── public/
│   ├── index.html      # Frontend UI
│   └── js/app.js       # Frontend логика
├── .env                # Конфигурация (пароль здесь!)
├── package.json        # npm зависимости
├── START.sh            # Скрипт запуска
├── README.md           # Полная документация
├── SECURITY.md         # Руководство по безопасности
└── generate-password.js # Генератор хеша пароля
```

---

## 🆘 Проблемы?

### Не могу войти

```bash
# Сбросьте пароль
node generate-password.js "admin123"
# Скопируйте хеш в .env
```

### Порт занят

```bash
# Измените порт в .env
PORT=3001

# Перезапустите сервер
```

### Ботов не видно

Проверьте конфиг OpenClaw:

```bash
cat ~/.openclaw/openclaw.json
```

---

## 📚 Документация

- **README.md** - Полная документация
- **SECURITY.md** - Руководство по безопасности
- **INSTALL.md** - Детальная установка

---

## 🚀 Готово!

Теперь вы можете:
- ✅ Управлять Telegram ботами
- ✅ Добавлять/удалять пользователей из allowlist
- ✅ Безопасно работать с localhost
- ✅ Контролировать доступ к вашим ботам

**Приятной работы с OpenClaw Dashboard! 🎉**
