# 📦 Инструкция по установке и запуску

## Быстрый старт (5 минут)

### Шаг 1: Установка зависимостей

```bash
cd /root/.openclaw/workspace/projects/openclaw-dashboard
npm install
```

### Шаг 2: Запуск сервера

```bash
npm start
```

Сервер запустится на http://127.0.0.1:3000

### Шаг 3: Вход в дашборд

1. Откройте браузер
2. Перейдите на http://127.0.0.1:3000
3. Введите дефолтный пароль: **admin123**

⚠️ **ВАЖНО**: После первого входа ОБЯЗАТЕЛЬНО смените пароль!

---

## Смена пароля

### Способ 1: Через генератор

```bash
cd /root/.openclaw/workspace/projects/openclaw-dashboard

# Сгенерировать новый хеш
node generate-password.js "ВашНовыйСуперПароль123"

# Скопировать вывод и вставить в .env
nano .env
```

Замените строку `ADMIN_PASSWORD_HASH=...` на новый хеш

### Способ 2: Вручную через Node.js

```bash
node -e "const bcrypt = require('bcrypt'); bcrypt.hash('НовыйПароль', 10).then(console.log)"
```

Скопируйте вывод в `.env` файл

---

## Проверка установки

### 1. Проверка зависимостей

```bash
npm list --depth=0
```

Должны быть установлены:
- express
- express-session
- express-rate-limit
- bcrypt
- dotenv
- csurf
- cookie-parser

### 2. Проверка .env файла

```bash
cat .env
```

Должны быть установлены:
- PORT
- SESSION_SECRET
- ADMIN_PASSWORD_HASH

### 3. Проверка OpenClaw конфига

```bash
cat ~/.openclaw/openclaw.json
```

Должна быть правильная структура JSON

---

## Остановка сервера

Нажмите `Ctrl + C` в терминале

---

## Автозапуск (опционально)

### Способ 1: systemd (Linux)

Создайте файл `/etc/systemd/system/openclaw-dashboard.service`:

```ini
[Unit]
Description=OpenClaw Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/.openclaw/workspace/projects/openclaw-dashboard
ExecStart=/usr/bin/node server.js
Restart=on-failure
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
```

Активируйте:

```bash
sudo systemctl enable openclaw-dashboard
sudo systemctl start openclaw-dashboard
sudo systemctl status openclaw-dashboard
```

### Способ 2: PM2 (Process Manager)

```bash
npm install -g pm2

cd /root/.openclaw/workspace/projects/openclaw-dashboard
pm2 start server.js --name openclaw-dashboard
pm2 save
pm2 startup
```

---

## Доступ через SSH туннель (удаленный доступ)

Если сервер на удаленной машине:

```bash
# На локальной машине
ssh -L 3000:127.0.0.1:3000 user@remote-server

# Затем откройте http://127.0.0.1:3000 в локальном браузере
```

---

## Обновление

```bash
cd /root/.openclaw/workspace/projects/openclaw-dashboard
git pull  # Если используете git
npm install
npm start
```

---

## Удаление

```bash
cd /root/.openclaw/workspace/projects
rm -rf openclaw-dashboard
```

---

## Поддержка

Если возникли проблемы, проверьте:

1. Логи сервера (в консоли)
2. `.env` файл (должен существовать)
3. `~/.openclaw/openclaw.json` (должен быть валидный JSON)
4. Права доступа к файлам

---

**🔒 Безопасность**: Дашборд доступен только с localhost. Никогда не выставляйте его в интернет без дополнительной защиты!
