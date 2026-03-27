# License API — Systematika

REST API для управления лицензиями клиентов Систематики.  
При рестарте Gateway клиента сервис проверяет статус лицензии и блокирует агента при `status: inactive`.

**Версия:** 1.0.0  
**Порт:** 3855 (localhost → проксируется через Caddy)  
**Стек:** Node.js · Express · SQLite (better-sqlite3)

---

## Быстрый старт

### 1. Установка зависимостей

```bash
cd /opt/license-api   # или куда деплоишь
npm install
```

### 2. Конфиг

```bash
cp .env.example .env
# отредактируй .env — обязательно смени LICENSE_ADMIN_TOKEN
```

### 3. Запуск (разработка)

```bash
npm run dev
```

### 4. Запуск (production — systemd)

```bash
# Скопировать сервис в /opt
cp -r . /opt/license-api

# Создать .env с секретами
cp /opt/license-api/.env.example /opt/license-api/.env
nano /opt/license-api/.env

# Установить systemd unit
cp /opt/license-api/license-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now license-api

# Проверить
systemctl status license-api
curl http://127.0.0.1:3855/health
```

---

## API Reference

### Public

#### `GET /health`
Проверка работоспособности.

```json
{ "status": "ok", "version": "1.0.0" }
```

#### `GET /license/check?key={license_key}`
Проверить статус лицензии.

**Параметры:**
| Param | Тип    | Описание       |
|-------|--------|----------------|
| key   | string | UUID лицензии  |

**Ответ (лицензия найдена):**
```json
{
  "status": "active",
  "expiresAt": "2025-12-31T23:59:59.000Z",
  "clientName": "ООО Рога и Копыта",
  "plan": "pro"
}
```

**Ответ (не найдена):**
```json
{ "status": "inactive" }
```

**Статусы:** `active` | `inactive` | `trial`  
> Если `expires_at` истёк — возвращает `inactive` и автоматически деактивирует лицензию в БД.

---

### Admin (требует `Authorization: Bearer <LICENSE_ADMIN_TOKEN>`)

#### `POST /license/activate`
Создать новую лицензию.

**Body:**
```json
{
  "clientName": "ООО Рога и Копыта",
  "plan": "pro",
  "expiresAt": "2025-12-31T23:59:59Z",
  "contactTelegram": "@ivanov"
}
```

| Поле             | Тип    | Обяз. | Описание                             |
|------------------|--------|-------|--------------------------------------|
| clientName       | string | ✅    | Название клиента                     |
| plan             | string | ✅    | `trial` / `basic` / `pro`            |
| expiresAt        | string | ❌    | ISO 8601 дата окончания (null = ∞)   |
| contactTelegram  | string | ❌    | Telegram контакт                     |

**Ответ `201`:**
```json
{
  "licenseKey": "550e8400-e29b-41d4-a716-446655440000",
  "clientName": "ООО Рога и Копыта",
  "plan": "pro",
  "status": "active",
  "expiresAt": "2025-12-31T23:59:59Z",
  "contactTelegram": "@ivanov",
  "createdAt": "2024-03-10T12:00:00"
}
```
> Для `plan: "trial"` статус автоматически устанавливается `trial`.

---

#### `POST /license/deactivate`
Деактивировать лицензию.

**Body:**
```json
{ "licenseKey": "550e8400-e29b-41d4-a716-446655440000" }
```

**Ответ `200`:**
```json
{ "success": true, "licenseKey": "550e8400-...", "status": "inactive" }
```

---

#### `GET /license/list`
Список всех лицензий.

**Query params (опционально):**
| Param  | Описание                             |
|--------|--------------------------------------|
| status | Фильтр: `active` / `inactive` / `trial` |
| plan   | Фильтр: `trial` / `basic` / `pro`   |
| limit  | Кол-во записей (default: 100)        |
| offset | Смещение (default: 0)                |

**Ответ:**
```json
{
  "total": 42,
  "limit": 100,
  "offset": 0,
  "licenses": [
    {
      "id": 1,
      "licenseKey": "550e8400-...",
      "clientName": "ООО Рога и Копыта",
      "plan": "pro",
      "status": "active",
      "expiresAt": "2025-12-31T23:59:59Z",
      "contactTelegram": "@ivanov",
      "createdAt": "2024-03-10T12:00:00",
      "updatedAt": "2024-03-10T12:00:00"
    }
  ]
}
```

---

## Caddy конфиг (пример)

```caddy
api.systematika.pro {
  reverse_proxy /license* localhost:3855
  reverse_proxy /health   localhost:3855
}
```

---

## Переменные окружения

| Переменная           | Обяз. | Default        | Описание                          |
|----------------------|-------|----------------|-----------------------------------|
| PORT                 | ❌    | 3855           | Порт сервера                      |
| LICENSE_ADMIN_TOKEN  | ✅    | —              | Bearer token для admin endpoints  |
| DB_PATH              | ❌    | ./licenses.db  | Путь к SQLite файлу               |

---

## Миграция на PostgreSQL

Замени `better-sqlite3` на `pg` / `knex`, обнови `src/db.js` — структура таблицы идентична.

---

## Структура проекта

```
license-api/
├── src/
│   ├── index.js              # Entry point, Express app
│   ├── db.js                 # SQLite connection + schema
│   ├── middleware/
│   │   └── auth.js           # Bearer token middleware
│   └── routes/
│       └── license.js        # /license/* endpoints
├── license-api.service       # systemd unit
├── .env.example
├── .gitignore
├── package.json
└── README.md
```
