# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

## Базы данных

### PostgreSQL (Docker, порт 5432) — ОСНОВНАЯ
```bash
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```
Таблицы: `telegram_messages` (16K+ сообщений, 36 чатов), `mymeet.meetings`

⚠️ Порт 5433 — ловушка, НЕ использовать!

### Factory DB (193.124.112.222:49002) — distribution
```bash
python3 /root/.openclaw/workspace/shared/scripts/distribution_db.py query "SQL"
```

## Скрипты и инструменты

### Google Sheets
```bash
python3 /root/.openclaw/workspace/shared/scripts/google_sheets.py
```
Таблица: `1kMKgKgJKspoSny9rjZ5cKIyhXYe8IrD2Tstal4ZmpzY`

**Прямой доступ через API (токен):**
- Credentials: `/root/.openclaw/workspace-kira-pomoschnitsa-km/integrations/google-sheets/credentials.json`
- Token: `/root/.openclaw/workspace-kira-pomoschnitsa-km/integrations/google-sheets/token.json`
- Скоупы: `calendar` + `spreadsheets`

### Airtable — база клиентов
```bash
python3 /root/.openclaw/workspace/shared/scripts/airtable_client.py
```
База: `app7fFym01YjkYHB8`, таблица `Table 1`

### amoCRM
```bash
python3 /root/.openclaw/workspace/shared/scripts/amocrm_client.py
```

### Калькулятор роликов
```
/root/.openclaw/workspace/shared/skills/calculator/
```

### Локальные модули (client-service-bot)
- `payment_ocr.py` — OCR платёжек
- `sheets_writer.py` — запись оплат в Sheets
- `sheets_profile.py` — профайл клиентов
- `airtable_client.py` — создание клиентов

## Общие ресурсы
- `/root/.openclaw/workspace/shared/users.json`
- `/root/.openclaw/workspace/shared/scripts/`
- `/root/.openclaw/workspace/shared/skills/`
- `/root/.openclaw/workspace/docs/`

## Чаты
- Производство: `-1002880939807`
- Заказы: `-1003218747283`
- Оплаты: `-1002499378249` (топик "Поступления")

## Делегирование
- Фёдор (`fyodor`) — аналитика, данные, метрики
- Даша (`dasha-smyslovik`) — копирайтинг

Add whatever helps you do your job. This is your cheat sheet.
