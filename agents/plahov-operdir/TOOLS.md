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

Add whatever helps you do your job. This is your cheat sheet.

### PostgreSQL

⚠️ **ВАЖНО: два инстанса PostgreSQL!**
- **Docker (порт 5432, TCP)** — основная база, сюда пишут все скрипты
  - `PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw`
- **Локальный PG 16 (порт 5433, Unix socket)** — почти пустой, НЕ использовать
  - `psql -U postgres` без -h попадает СЮДА — это ловушка!

### Distribution DB (factory)
- Host: 193.124.112.222:49002
- User: roman_ai_readonly (readonly)
- Скрипт: `python3 /root/.openclaw/workspace/shared/scripts/distribution_db.py query "SQL"`
