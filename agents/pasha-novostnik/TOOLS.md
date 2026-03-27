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
```
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```
Таблицы: telegram_messages, mymeet.meetings

⚠️ Локальный PG 16 (порт 5433) — НЕ использовать! `psql -U postgres` без `-h` = ловушка.
ВСЕГДА указывать `-h localhost -p 5432`.

### Factory DB (readonly)
```
python3 /root/.openclaw/workspace/shared/scripts/distribution_db.py query "SQL"
```
Хост: 193.124.112.222:49002

## Shared-ресурсы
- users.json: `/root/.openclaw/workspace/shared/users.json`
- Скрипты: `/root/.openclaw/workspace/shared/scripts/`
- Скиллы: `/root/.openclaw/workspace/shared/skills/`
- Документация: `/root/.openclaw/workspace/docs/`

## Парсинг AI-новостей (Puppeteer)

**ОБЯЗАТЕЛЬНО** перед составлением #ии_новости:

```bash
node /root/.openclaw/workspace-pasha-novostnik/scripts/fetch_ai_news.js
```

Скрипт парсит TechCrunch AI + VentureBeat AI, возвращает JSON с заголовками и ссылками.

### Правила:
- Брать только реальные новости из вывода скрипта
- Никогда не генерировать/выдумывать новости из головы
- К каждой новости добавлять ссылку 🔗 [Читать](URL)
- Если скрипт вернул пустой массив — сообщить об ошибке, не выдумывать
