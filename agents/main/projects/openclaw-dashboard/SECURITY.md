# 🔒 Руководство по безопасности

## Основные принципы безопасности

OpenClaw Dashboard разработан с приоритетом на безопасность. Следуйте этим рекомендациям для максимальной защиты.

---

## 🛡️ Встроенные меры безопасности

### 1. Localhost-only доступ
- Сервер привязан к `127.0.0.1`
- Невозможно подключиться извне без SSH туннеля
- Защита от прямых атак из интернета

### 2. Bcrypt хеширование
- Пароли хешируются с использованием bcrypt (cost factor: 10)
- Невозможно восстановить пароль из хеша
- Защита от rainbow table атак

### 3. CSRF Protection
- Каждый POST/PUT/DELETE запрос требует валидный CSRF токен
- Защита от межсайтовой подделки запросов
- Токены уникальны для каждой сессии

### 4. Rate Limiting
- **API endpoints**: максимум 100 запросов за 15 минут
- **Login endpoint**: максимум 5 попыток за 15 минут
- Автоматическая блокировка при превышении лимита
- Защита от brute-force атак

### 5. Express Sessions
- Secure cookie settings
- HttpOnly cookies (защита от XSS)
- SameSite: strict (защита от CSRF)
- Автоматическое истечение сессии (24 часа)

### 6. Input Validation
- Валидация всех входных данных
- Проверка формата Telegram токенов
- Проверка формата User ID
- Санитизация HTML (защита от XSS)

---

## ⚠️ Обязательные действия после установки

### 1. Смените дефолтный пароль!

```bash
node generate-password.js "ВашСильныйПароль123!"
# Скопируйте вывод в .env
```

**Требования к паролю:**
- Минимум 12 символов
- Буквы в разных регистрах
- Цифры
- Специальные символы
- Не используйте словарные слова

❌ Плохие пароли: `admin`, `password`, `123456`, `qwerty`  
✅ Хорошие пароли: `M7#xK$pQ9!vL2&nR`, `MyC0mpl3x!P@ssw0rd`

### 2. Смените SESSION_SECRET

Отредактируйте `.env`:

```env
SESSION_SECRET=сгенерируйте_случайную_строку_минимум_32_символа
```

Генерация случайной строки:

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

### 3. Защитите .env файл

```bash
chmod 600 .env
```

Убедитесь, что `.env` в `.gitignore`:

```bash
cat .gitignore | grep .env
```

---

## 🚨 Что НЕ делать

### ❌ Никогда не делайте это:

1. **Не выставляйте порт в интернет**
   - Не меняйте `HOST` на `0.0.0.0`
   - Не открывайте порт 3000 в firewall для внешних подключений

2. **Не коммитьте .env файл**
   - `.env` содержит пароли
   - Всегда проверяйте `.gitignore`

3. **Не используйте слабые пароли**
   - `admin123` - только для первого запуска!
   - Сразу смените на сильный пароль

4. **Не отключайте CSRF protection**
   - Не удаляйте `csrfProtection` middleware

5. **Не отключайте rate limiting**
   - Защита от brute-force критична

6. **Не запускайте от root** (если возможно)
   - Создайте отдельного пользователя для сервера

7. **Не логируйте пароли/токены**
   - Проверяйте, что sensitive данные не попадают в логи

---

## 🔐 Дополнительные меры безопасности

### 1. SSH Туннель (для удаленного доступа)

Вместо открытия порта в интернет используйте SSH туннель:

```bash
# На локальной машине
ssh -L 3000:127.0.0.1:3000 user@remote-server

# Теперь http://127.0.0.1:3000 на локальной машине -> сервер
```

### 2. Reverse Proxy с SSL (Nginx)

Если нужен веб-доступ, используйте Nginx с SSL:

```nginx
server {
    listen 443 ssl http2;
    server_name dashboard.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # IP whitelist (опционально)
    allow 203.0.113.0/24;  # Ваша сеть
    deny all;
}
```

### 3. Firewall правила

```bash
# ufw (Ubuntu/Debian)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw enable

# НЕ открывайте порт 3000 извне!
```

### 4. Fail2Ban (защита от brute-force)

Создайте фильтр для логов дашборда:

```ini
# /etc/fail2ban/filter.d/openclaw-dashboard.conf
[Definition]
failregex = ^.*⚠️\s+Неудачная попытка входа.*<HOST>.*$
ignoreregex =
```

```ini
# /etc/fail2ban/jail.local
[openclaw-dashboard]
enabled = true
filter = openclaw-dashboard
logpath = /var/log/openclaw-dashboard.log
maxretry = 3
bantime = 3600
findtime = 600
```

### 5. Мониторинг логов

```bash
# Следите за подозрительной активностью
tail -f /var/log/openclaw-dashboard.log | grep "Неудачная попытка"
```

### 6. Регулярные обновления

```bash
# Обновляйте зависимости
npm audit
npm audit fix

# Проверяйте уязвимости
npm outdated
```

---

## 📊 Аудит безопасности

### Чеклист проверки:

- [ ] Дефолтный пароль изменен
- [ ] SESSION_SECRET изменен
- [ ] .env файл защищен (chmod 600)
- [ ] .env в .gitignore
- [ ] Сервер слушает только на 127.0.0.1
- [ ] CSRF protection активен
- [ ] Rate limiting активен
- [ ] npm audit показывает 0 critical vulnerabilities
- [ ] Используется SSH туннель для удаленного доступа
- [ ] Логи не содержат sensitive данных

### Команды для проверки:

```bash
# Проверка зависимостей
npm audit

# Проверка прав доступа
ls -la .env

# Проверка активного порта
netstat -tlnp | grep 3000
# Должен быть: 127.0.0.1:3000 (НЕ 0.0.0.0:3000!)

# Проверка .gitignore
cat .gitignore | grep .env
```

---

## 🆘 Что делать в случае компрометации

### 1. Немедленно:

```bash
# Остановить сервер
pkill -f "node server.js"

# Сменить пароль
node generate-password.js "НовыйЭкстраБезопасныйПароль!"
nano .env

# Сменить SESSION_SECRET
nano .env

# Перезапустить сервер
npm start
```

### 2. Проверить логи:

```bash
# Найти подозрительные запросы
grep "Неудачная попытка" logs/*.log
grep "POST /api" logs/*.log
```

### 3. Проверить конфиг OpenClaw:

```bash
cat ~/.openclaw/openclaw.json
# Проверить, не добавлены ли неизвестные боты/пользователи
```

### 4. Пересоздать ключи:

```bash
# Новый SESSION_SECRET
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"

# Обновить .env
nano .env
```

---

## 📚 Дополнительные ресурсы

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Node.js Security Best Practices](https://nodejs.org/en/docs/guides/security/)
- [Express Security Best Practices](https://expressjs.com/en/advanced/best-practice-security.html)
- [Bcrypt NPM](https://www.npmjs.com/package/bcrypt)

---

## 📞 Контакт

При обнаружении уязвимости:

1. **НЕ публикуйте** информацию публично
2. Свяжитесь с разработчиком напрямую
3. Дайте время на исправление (responsible disclosure)

---

**Помните**: Безопасность - это процесс, а не состояние. Регулярно проверяйте и обновляйте систему!
