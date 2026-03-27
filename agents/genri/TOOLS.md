# TOOLS.md — Инфраструктурная карта Генри

## Content Hunter
CEO: Кирилл Попов | Опердир: Роман (@rmbrmv) | КМ: Аня (@gengo_care)

---

## PostgreSQL — ⚠️ ДВА ИНСТАНСА

### 1. Docker PG (порт 5432, TCP) — ОСНОВНАЯ
```bash
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```
- **БД `openclaw`:**
  - `telegram_messages` (16K+ записей)
  - `mymeet.meetings` (293 записи)
  - `mymeet.meeting_chunks` (пустой — нужна нарезка!)
- **БД `knowledge_base`:**
  - `documents`

### 2. Локальный PG 16 (порт 5433, Unix socket) — ⚠️ НЕ ИСПОЛЬЗОВАТЬ
```bash
# psql -U postgres  ← БЕЗ -h попадёшь СЮДА — ловушка!
```
Почти пустой. Всегда указывать `-h localhost -p 5432`.

### 3. Factory DB (readonly)
- Хост: `193.124.112.222:49002`
- БД: `distribution`
```bash
python3 /root/.openclaw/workspace/shared/scripts/distribution_db.py query "SQL"
```

---

## 🖥️ Внешний сервер — 91.98.180.103 (ресурсоёмкие задачи)
> **Политика**: ресурсоёмкие задачи (ffmpeg, ML, обработка видео) выносятся на этот сервер — он мощнее основного.

- **SSH**: `sshpass -p 'MNcwMPCiyiYtM5' ssh root@91.98.180.103`
- **OS**: Ubuntu 22.04, Python 3.10, ffmpeg 4.4, PM2 6.x
- **Диск**: 1.71TB

### Сервисы на 91.98.180.103
| PM2 имя | Расположение | Назначение |
|---------|-------------|-----------|
| unic-worker | `/root/unic-worker/` | ⚠️ **ЕДИНСТВЕННОЕ место запуска уникализации** |

### ⚠️ unic-worker — ТОЛЬКО на 91.98.180.103
- Подключается к основной БД по внешнему IP: `72.56.107.157:5432`
- **НЕ запускать локально** — конфликт с удалённым воркером, задачи падают
- Управление: `sshpass ... ssh root@91.98.180.103 "pm2 restart unic-worker"`
- Логи: `sshpass ... ssh root@91.98.180.103 "pm2 logs unic-worker --lines 50"`
- MAX_WORKERS=4, POLL_INTERVAL=3

---

## Сервисы — PM2 локальный (⚠️ ТОЛЬКО через PM2, никогда node server.js &)

| PM2 имя | Порт | Домен |
|---------|------|-------|
| autowarm | 3848 | delivery.contenthunter.ru |
| hr-payroll | 3852 | delivery.contenthunter.ru:3852 |
| producer | 3850 | — |
| office | 3847 | office.contenthunter.ru |
| farm | 3853 | — |
| carousel | 3851 | — |
| tasks | 3849 | — |

### ⚠️ Правила PM2 (аудит 2026-03-01)
- **НИКОГДА** не запускать через `node server.js &` или `nohup` — только PM2
- Новый сервис: `pm2 start server.js --name <имя> --cwd <папка>`
- После добавления: `pm2 save`
- Проверка: `pm2 list`
- Причина: orphan node-процессы занимают порты → PM2 версии уходят в crash loop
- **НИКОГДА не делать `pm2 save` из чужой папки с ecosystem.config.js** — перезапишет глобальный dump и убьёт другие процессы!

| Сервис | Заметки |
|--------|---------|
| OpenClaw Gateway | Запуск вручную, systemd не настроен |
| Caddy | reverse proxy + auto SSL, DNS через Reg.ru |
| Telegram парсер | Telethon, крон 3ч, `telegram_parse_incremental.sh` |
| PG Backups | daily 3:00 AM, ротация 7 дней |

---

## Интеграции (`/root/.openclaw/workspace/integrations/`)
- Google OAuth (Calendar, Sheets, Drive)
- Zoom OAuth
- Groq Whisper
- amoCRM
- Airtable
- Telethon (Telegram parser)

---

## Мониторинг
- Пороги: disk 80%/90%, memory 85%/95%, CPU 80%/95%
- Скрипт: `scripts/monitoring/check_and_alert.py`

---

## Shared-ресурсы
- Пользователи: `/root/.openclaw/workspace/shared/users.json`
- Скрипты: `/root/.openclaw/workspace/shared/scripts/`
- Скиллы: `/root/.openclaw/workspace/shared/skills/`
- Документация: `/root/.openclaw/workspace/docs/`

---

## Команда агентов
Варенька (main, **СВЯЩЕННА**), Фёдор (аналитик), Даша (копирайтер), Кира (помощница КМ), Елена (HR), Генри (я, dev), Плахов (виртуальный опердир), Миша (методолог), Олег (маркетолог), Паша (новостник), Ли (разведчица)

## Правила
- Варенька — НЕ ТРОГАТЬ
- `trash` > `rm`
- Git: github.com/rmbrmv/openclaw-workspace
