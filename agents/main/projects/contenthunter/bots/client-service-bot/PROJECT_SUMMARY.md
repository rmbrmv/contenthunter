# 📋 Client Service Bot - Краткий обзор проекта

## Что это?

Telegram бот для автоматизации клиентского сервиса продакшн-студии.

## Основные функции

### 1. 📥 Автоматическое сохранение материалов
Бот распознаёт и сохраняет в Airtable:
- Видео, фото, документы
- Ссылки на облачные хранилища
- Текстовые описания и брифы

### 2. 🤖 AI-ассистент
Отвечает на вопросы:
- О процессах работы
- По базе знаний (FAQ)
- Помогает искать материалы

### 3. 📊 Управление материалами
- Поиск по базе (`/search`)
- Статистика (`/status`)
- Автоматическая категоризация

## Технологии

- **Язык:** Python 3.11+
- **Telegram API:** python-telegram-bot 20.7
- **База данных:** Airtable (+ PostgreSQL опционально)
- **AI:** OpenAI GPT-4 / Anthropic Claude
- **Логирование:** Loguru

## Структура файлов

```
client-service-bot/
├── bot.py                  # 🚀 Главный файл (точка входа)
├── config.py               # ⚙️ Конфигурация
├── message_handler.py      # 📨 Обработка сообщений
├── airtable_client.py      # 💾 Работа с Airtable
├── ai_assistant.py         # 🤖 AI-ассистент
├── requirements.txt        # 📦 Зависимости
├── .env.example            # 📝 Шаблон настроек
├── .env                    # 🔐 Ваши настройки (создаётся вручную)
│
├── knowledge/              # 📚 База знаний
│   ├── faq.md             # Часто задаваемые вопросы
│   ├── processes.md       # Процессы работы
│   └── templates/         # Шаблоны сообщений
│
├── logs/                   # 📊 Логи бота
│
├── README.md               # 📖 Полная документация
├── SETUP_GUIDE.md         # 🔧 Инструкция по установке
├── USAGE_EXAMPLES.md      # 💡 Примеры использования
├── CHANGELOG.md           # 📝 История изменений
│
├── setup.sh               # 🛠️ Скрипт установки
├── run.sh                 # ▶️ Скрипт запуска
└── check_config.py        # ✅ Проверка настроек
```

## Быстрый старт

### 1. Установка

```bash
cd /root/.openclaw/workspace/projects/contenthunter/bots/client-service-bot/
./setup.sh
```

### 2. Настройка

```bash
# Скопировать шаблон
cp .env.example .env

# Заполнить credentials
nano .env
```

Необходимо заполнить:
- `TELEGRAM_BOT_TOKEN` (от @BotFather)
- `AIRTABLE_API_KEY` + `AIRTABLE_BASE_ID`
- `ANTHROPIC_API_KEY` или `OPENAI_API_KEY`

### 3. Проверка

```bash
python check_config.py
```

### 4. Запуск

```bash
./run.sh
```

## Основные команды

| Команда | Описание |
|---------|----------|
| `/start` | Начало работы |
| `/help` | Список команд |
| `/search [запрос]` | Поиск материалов |
| `/status` | Статистика |

## Примеры использования

### Клиент отправляет материал

```
[Загружает видео с caption: "Исходник для монтажа"]

✅ Материал сохранён!
Тип: video
Описание: Исходник для монтажа
```

### Вопрос к боту

```
@bot Сколько времени займёт монтаж?

🤖 Обычно монтаж занимает 2-5 дней после получения всех материалов...
```

### Поиск материалов

```
/search логотип

🔍 Найдено материалов: 2
1. [photo] Логотип компании...
2. [document] Бренд-бук...
```

## Безопасность

✅ **Реализовано:**
- Allowlist чатов (только разрешённые)
- Валидация файлов (размер, расширения)
- Rate limiting
- Логирование всех действий
- Credentials в .env (не коммитится в Git)

## Интеграции

- **Telegram** - основная платформа
- **Airtable** - хранение материалов
- **OpenAI / Claude** - AI ответы
- **PostgreSQL** - логирование (опционально)

## Workflow

```
Клиент отправляет → Бот детектирует → Сохранение в Airtable
     сообщение              тип материала        ↓
                                              Подтверждение
                                              клиенту
```

## Airtable структура

Таблица: **Client Materials**

| Поле | Тип | Описание |
|------|-----|----------|
| Date | Date | Дата получения |
| Client | Text | Имя клиента |
| Chat ID | Text | ID чата |
| Type | Select | video/photo/document/link/text |
| Description | Long Text | Описание материала |
| File URL | URL | Ссылка на файл |
| Telegram File ID | Text | File ID из Telegram |
| Status | Select | new/processing/done |
| Notes | Long Text | Заметки |

## Метрики

После запуска бот собирает:
- Количество обработанных сообщений
- Количество сохранённых материалов
- Типы материалов (статистика)
- Логи всех действий

Просмотр: `tail -f logs/bot.log`

## Production deployment

### Вариант 1: systemd (Linux)

```bash
sudo systemctl enable client-bot
sudo systemctl start client-bot
```

### Вариант 2: Docker

```bash
docker build -t client-service-bot .
docker run -d --name client-bot --env-file .env client-service-bot
```

## Мониторинг

```bash
# Логи в реальном времени
tail -f logs/bot.log

# Поиск ошибок
grep ERROR logs/bot.log

# Статус (если systemd)
sudo systemctl status client-bot
```

## Расширение функциональности

### Добавление новой команды

1. Редактируем `message_handler.py`
2. Добавляем обработчик в `handle_command()`
3. Регистрируем в `bot.py` (если нужно)

### Изменение детекции материалов

1. Редактируем `config.py`:
   - `MATERIAL_KEYWORDS` - ключевые слова
   - `EXTERNAL_LINK_DOMAINS` - домены ссылок
   - `ALLOWED_FILE_EXTENSIONS` - расширения файлов

### Обновление базы знаний

1. Редактируем `knowledge/faq.md`
2. Редактируем `knowledge/processes.md`
3. Перезапускаем бота

## Поддержка

📖 **Документация:**
- `README.md` - полная документация
- `SETUP_GUIDE.md` - пошаговая установка
- `USAGE_EXAMPLES.md` - примеры

🔧 **Утилиты:**
- `check_config.py` - проверка настроек
- `logs/bot.log` - логи

## Требования к окружению

- Python 3.11+
- Виртуальное окружение (venv)
- Доступ к интернету (Telegram API, Airtable, AI API)
- Минимум 512 MB RAM
- Минимум 100 MB дискового пространства

## Лицензия

Proprietary - ContenHunter Studio

---

**Версия:** 1.0.0  
**Статус:** ✅ Production Ready  
**Дата создания:** 2024-02-23

**Автор:** AI Assistant  
**Для:** ContenHunter Studio
