# TODO - Backlog

## ✅ Готово

### 🌐 Chromium Headless - Полная настройка для автоматизации веб-сервисов

**Статус:** ✅ Готово (22.02.2026)  
**Решение:** Selenium + undetected-chromedriver

**Реализовано:**
- ✅ Mymeet scraper работает (`mymeet_to_postgres.py`)
- ✅ Selenium с обходом детекции
- ✅ PostgreSQL интеграция + embeddings
- ✅ Автоматическая загрузка транскриптов

---

## 🔥 Высокий приоритет

**Проблема:**
Mymeet.ai падает с JavaScript ошибкой при открытии в headless-shell режиме.
Headless браузер детектируется или не поддерживается их фронтендом.

**Что нужно сделать:**

#### 1. Установка полного Chromium (не headless-shell) (~30 мин)
```bash
# Установить полный браузер с GUI поддержкой
apt-get install chromium-browser chromium-chromedriver
# или скачать официальную сборку Chrome for Testing
```

#### 2. Настройка stealth mode для обхода детекции (~30 мин)
```python
# Playwright stealth plugin
# Настройка User-Agent, WebGL, Canvas fingerprinting
# Эмуляция реального браузера
# Отключение automation флагов
```

**Параметры для обхода детекции:**
- Custom User-Agent (последняя версия Chrome)
- Timezone = MSK
- Language = ru-RU
- WebGL Vendor/Renderer эмуляция
- Canvas/AudioContext fingerprint
- Отключить `navigator.webdriver`

#### 3. Настройка виртуального дисплея Xvfb (~15 мин)
```bash
# Виртуальный X-сервер для GUI браузера на headless сервере
apt-get install xvfb
# Запуск Chromium через Xvfb
xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" chromium
```

#### 4. Отладка Mymeet.ai (~30 мин)
- Открыть в консоли браузера (DevTools)
- Посмотреть JavaScript ошибки
- Проверить Network запросы
- Исправить селекторы если нужно

#### 5. Создание универсального scraper модуля (~15 мин)
```python
# /root/.openclaw/workspace/lib/browser.py
# Универсальный модуль с настроенным Playwright
# Может использоваться для любых сайтов
```

**Результат:**
- ✅ Полностью настроенный headless Chromium
- ✅ Обход детекции автоматизации
- ✅ Работающий Mymeet scraper
- ✅ Универсальный инструмент для автоматизации любых веб-сервисов

**Credentials (уже сохранены):**
`/root/.openclaw/workspace/integrations/mymeet/credentials.json`

**Скрипт (готов, нужно доделать):**
`/root/.openclaw/workspace/scripts/mymeet_scraper.py`

---

## 🔴 Блокеры (нужны действия от тебя)

### 1. Telegram Parser - Авторизация
**Статус:** API credentials получены, ждём решения проблемы с авторизацией  
**Блокер:** Telegram не отправляет код авторизации  
**Дата обновления:** 21.02.2026

**Что сделано:**
- ✅ API credentials получены (api_id: 39661391)
- ✅ Скрипт авторизации создан
- ✅ PostgreSQL schema создана (`sql/telegram_schema.sql`)
- ✅ Конфиг сохранён (`.telegram/config.json`)
- ✅ Обращение в @BotSupport отправлено

**Проблема:**
При попытке авторизации через Telethon код не приходит:
- Ни в Telegram приложение
- Ни через SMS
- Пробовали с VPN и без
- Пробовали разные номера

**Следующий шаг:**
Ждём ответ от @BotSupport (24-48 часов)

**Когда решится:**
- Session file с Windows → сервер
- Полный парсинг Telegram чатов
- Автоматизация через cron
- RAG поиск по истории

---

### 2. MAX Messenger - Bot Token
**Статус:** Код готов, ждёт Bot Token  
**Блокер:** Нужен токен от MAX BotFather-аналога

**Что сделано:**
- ✅ Скрипт `/root/.openclaw/workspace/scripts/max_client.py`
- ✅ Документация готова
- ✅ Config template готов

**Что нужно:** Bot Token для MAX

---

## 🟡 Отложенные задачи

### 3. VPS Security Hardening
**Статус:** План готов, не применён  
**Приоритет:** Средний (риск низкий пока firewall провайдера закрывает)

**Проблемы найдены:**
- PostgreSQL на 0.0.0.0:5432 (публично)
- SSH root login разрешён
- UFW не настроен
- CUPS запущен без нужды
- Опасный skill antigravity-image-gen

**План готов в:** `/root/.openclaw/workspace/docs/VPS_SECURITY_HARDENING.md`

**Применить?** Скажи когда готов, займёт ~15-20 минут

---

### 4. OpenAI Balance
**Статус:** Ключ есть, квота превышена  
**Нужно:** Пополнить $5-10 на https://platform.openai.com/account/billing

**Для чего:**
- Embeddings API (альтернатива sentence-transformers)
- Быстрее в 10 раз для больших объёмов

---

## 📝 Идеи на будущее (не начаты)

### ClawHub Publications
После тестирования опубликовать:
- Telegram Parser skill
- Distribution DB skill

### Automatic Reports & Alerts
- Distribution DB: алерты на падение метрик
- Team Performance: уведомления о критических оценках
- amoCRM: дейли/уикли дайджесты

---

## 📊 Google Sheets - Артефакты отделов

**Статус:** Не начато  
**Приоритет:** Средний

### Таблицы для синхронизации:

#### 1. Аккаунты для выкладки
**Отделы:** Дистрибуция + Продакшен  
**Что синхронизировать:** TBD (уточнить структуру листов)  
**PostgreSQL schema:** `distribution.accounts` / `production.accounts`

#### 2. Расчеты CPM Hunter  
**Отдел:** Клиентский сервис  
**Что синхронизировать:** Все листы (уточнить какие именно)  
**PostgreSQL schema:** `client_service.cpm_calculations`

### Что нужно сделать:

1. **Получить доступ к таблицам**
   - Ссылки на Google Sheets
   - OAuth разрешения (уже есть ✅)

2. **Изучить структуру**
   - Какие листы в каждой таблице
   - Какие колонки важны
   - Как часто обновляются

3. **Создать PostgreSQL schema**
   - Таблицы под каждый лист
   - Связи между таблицами
   - Indexes для быстрого поиска

4. **Написать скрипт синхронизации**
   - Аналогично существующему `google_sheets_sync.py`
   - Batch processing
   - Incremental updates

5. **Настроить cron (опционально)**
   - Ежедневная синхронизация или по требованию
   - Логирование изменений

### Примерная оценка:
~2-3 часа на таблицу (изучение + schema + скрипт + тесты)

### Следующий шаг:
Получить ссылки на таблицы + изучить структуру листов

---

### 5. Pitch Deck PDF - Загрузка в базу знаний

**Статус:** Ждёт файл от Романа  
**Приоритет:** Средний  
**Дата добавления:** 21.02.2026

**Что нужно:**
- PDF презентации (pitch deck) компании
- Для загрузки в knowledge base (категория: компания)

**Следующий шаг:**
- Напомнить Роману отправить файл

