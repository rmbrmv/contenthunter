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

## PostgreSQL

### Основная БД (Docker, порт 5432) — ИСПОЛЬЗОВАТЬ ЭТУ
```bash
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```
- Таблицы: telegram_messages, mymeet.meetings
- ⚠️ ВСЕГДА указывать `-h localhost -p 5432`!

### Локальный PG 16 (порт 5433) — НЕ ИСПОЛЬЗОВАТЬ
- Это ловушка. `psql -U postgres` без `-h` попадает сюда.

### Factory DB (readonly)
```bash
python3 /root/.openclaw/workspace/shared/scripts/distribution_db.py query "SQL"
```
- Хост: 193.124.112.222:49002

## Shared ресурсы
- Users: `/root/.openclaw/workspace/shared/users.json`
- Scripts: `/root/.openclaw/workspace/shared/scripts/`
- Skills: `/root/.openclaw/workspace/shared/skills/`
- Docs: `/root/.openclaw/workspace/docs/`
