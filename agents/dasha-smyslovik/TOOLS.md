# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## Google Docs

✅ **Полный доступ: чтение И запись** (скоуп `documents` = create/read/edit/append)
📌 `drive.readonly` — только поиск по Drive, запись документов НЕ ограничивает

**Активировать окружение:**
```bash
cd /root/.openclaw/workspace/integrations/google-calendar && source venv/bin/activate
```

**Чтение документа:**
```bash
python3 /root/.openclaw/workspace-dasha-smyslovik/integrations/google-docs/docs_client.py read --id <DOC_ID>
```

**Создание нового документа:**
```bash
python3 /root/.openclaw/workspace-dasha-smyslovik/integrations/google-docs/docs_client.py create --title "Название" --content "Текст"
```

**Поиск документов:**
```bash
python3 /root/.openclaw/workspace-dasha-smyslovik/integrations/google-docs/docs_client.py list --query "ключевое слово"
```

- Token: `/root/.openclaw/workspace-dasha-smyslovik/integrations/google-docs/token.json`
- Script: `/root/.openclaw/workspace-dasha-smyslovik/integrations/google-docs/docs_client.py`

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

Add whatever helps you do your job. This is your cheat sheet.

---

## PostgreSQL

### openclaw (локальный Docker, порт 5432)
```
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```
Таблицы: `telegram_messages`, `mymeet.meetings`
⚠️ Порт 5433 — НЕ использовать!

### factory (distribution DB, 193.124.112.222:49002)
```
python3 /root/.openclaw/workspace/shared/scripts/distribution_db.py query "SQL"
```

## Airtable — база клиентов
```
python3 /root/.openclaw/workspace/shared/scripts/airtable_client.py
```
Проекты, ЦА, ключевые фразы клиентов.

## Документация о компании
- `/root/.openclaw/workspace/docs/` — продукт, услуги, кейсы
- `/root/.openclaw/workspace/docs/CONTENT_HUNTER_VISION.txt` — видение клиентского сервиса

## Общие ресурсы
- `/root/.openclaw/workspace/shared/users.json` — база пользователей (Роман, Аня)
- `/root/.openclaw/workspace/shared/scripts/` — скрипты
- `/root/.openclaw/workspace/shared/skills/` — навыки
- `/root/.openclaw/workspace/shared/docs/` — документация
