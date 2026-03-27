# TOOLS.md — Карта инфраструктуры Content Hunter

_Последнее обновление: 2026-02-26. Ответственный: Володя (сисадмин)._

---

## ⚠️ PostgreSQL — ДВА ИНСТАНСА

### 1. Docker PG (ОСНОВНАЯ — использовать эту!)
- **Порт:** 5432 (TCP, Docker proxy)
- **Контейнер:** `openclaw-postgres`
- **Подключение:**
  ```
  PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
  ```
- **Содержит:** telegram_messages, people, people_aliases, knowledge_base, meetings/transcriptions
- **Статус:** ✅ ACTIVE (Up)

### 2. Локальный PG 16 (НЕ ИСПОЛЬЗОВАТЬ для основной работы)
- **Порт:** 5433 (localhost only)
- **Подключение:** `psql -U postgres -p 5433`
- **⚠️ ЛОВУШКА:** `psql -U postgres` без `-h` попадает СЮДА, не в Docker!
- **Содержит:** почти пустой, служебный
- **Статус:** ✅ запущен, но не основной

---

## 🐳 Docker-контейнеры

| Контейнер | Статус | Порты |
|---|---|---|
| `openclaw-postgres` | ✅ Up | 0.0.0.0:5432→5432 |
| `telegram-mtproto` | ✅ Up | 0.0.0.0:8443→443 |

---

## 🔧 Сервисы (systemd)

| Сервис | Порт | Статус | Описание |
|---|---|---|---|
| `agent-office.service` | 3847 (localhost) | ✅ ACTIVE | Dashboard |
| `caddy` | 80, 443 | ✅ ACTIVE | Reverse proxy, auto SSL |
| producer-copilot (node) | 3850 (localhost) | ✅ слушает | Копилот для продюсеров |
| carousel-maker | 3851 (localhost) | ✅ ACTIVE | Поднят 2026-02-26 (был inactive) |
| uvicorn (Python API) | 8000 | ✅ слушает | `/usr/local/bin/uvicorn src.main:app` |

---

## 📋 Cron-задачи

| Расписание | Задача |
|---|---|
| `*/0 */3 * * *` | **Telegram парсер** → `telegram_parse_incremental.sh` |
| `0 6,14,22 * * *` | Telegram batch parse → `telegram_parse_batch.sh` |
| `0 3 * * *` | **PG Backup** → `backup_postgresql.sh` (ротация 7 дней) |
| `0 3 * * *` | Cleanup /tmp → `cleanup_tmp.sh 7` |
| `0 3 * * *` | CPM Hunter sync → `sync_cpm_hunter.py` |
| `0 3 * * *` | Team performance sync → `sync_team_performance_dynamic.py` |
| `*/30 * * * *` | Zoom transcribe account1 → `zoom_transcribe.py` |
| `*/30 * * * *` | Zoom transcribe account2 → `zoom_transcribe_account2.py` |
| `*/30 * * * *` | Zoom transcribe account3 → `zoom_transcribe_account3.py` |
| `0 * * * *` | Мониторинг ресурсов → `check_resources.py` |

---

## 📁 Скрипты мониторинга

```
/root/.openclaw/workspace/shared/scripts/monitoring/
├── check_and_alert.py       # Основной алерт-чекер
├── check_resources.py       # Ресурсы системы (CPU/RAM/disk) — крон каждый час
├── send_alert.py            # Отправка алертов
├── cleanup_tmp.sh           # Очистка /tmp
├── system_health.sh         # Общий healthcheck
└── system_health_check.sh   # Альтернативный healthcheck
```

---

## 📁 Скрипты парсинга / интеграций

```
/root/.openclaw/workspace/shared/scripts/
├── telegram_parse_incremental.sh   # Основной парсер (Telethon, крон 3ч)
├── telegram_parse_batch.sh         # Пакетный парсер
├── mymeet_*.py                     # MyMeet/Zoom синхронизация
├── zoom_*.py                       # Zoom транскрибация
├── backup_postgresql.sh            # PG бэкап
├── distribution_db.py              # Factory DB (только READ!)
└── knowledge_search.py             # Поиск по базе знаний
```

---

## 🏭 Factory DB (только READ!)

- **Host:** 193.124.112.222:49002
- **Доступ:** `python3 /root/.openclaw/workspace/shared/scripts/distribution_db.py query "SQL"`
- **⚠️ Только чтение! Не модифицировать.**
- **Содержит:** данные о 31 проекте, 635 аккаунтах

---

## 👥 Общие ресурсы

- `/root/.openclaw/workspace/shared/users.json` — команда (Роман, Аня и др.)
- `/root/.openclaw/workspace/shared/scripts/` — все скрипты
- `/root/.openclaw/workspace/docs/` — документация
- `/root/.openclaw/workspace/logs/` — логи всех сервисов

---

## 🤝 Разграничение с Генри (разработчик)

| Генри | Володя |
|---|---|
| Пишет новый код, фичи | Поддерживает, мониторит |
| Разрабатывает интеграции | Следит за крон-задачами |
| Архитектурные решения | Алерты, healthchecks |
| — | Чинит рутинные сбои |

**Правило:** не дублировать разработку, забирать рутину.

---

## 🚨 Экстренные команды

```bash
# Проверить Docker PG
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw -c "SELECT count(*) FROM telegram_messages;"

# Рестарт agent-office
systemctl restart agent-office

# Логи парсера
tail -50 /root/.openclaw/workspace/logs/telegram_incremental.log

# Статус всех контейнеров
docker ps

# Проверить порты
ss -tlnp | grep -E ':(3847|3850|3851|5432|8000|80|443)'
```

---

## 👤 users.json — ключевые контакты

| TG ID | Имя | Username | Роль |
|---|---|---|---|
| 295230564 | Роман | @rmbrmv | Операционный директор |
| 8161667050 | Аня | @gengo_care | Клиентский менеджер |
