# TOOLS.md - Local Notes

## TTS (голосовые ответы)
- Язык: **русский**
- Всегда отвечать голосовыми на русском языке

## STT (распознавание голоса)
- Groq Whisper: `[REDACTED-GROQ-KEY]`
- Файл ключа: `/root/.openclaw/shared/integrations/groq/api_key.txt`
- Модель: whisper-large-v3
- Язык: ru
- Конвертить ogg → mp3 через ffmpeg перед отправкой

## TTS (русские голосовые)
- Edge-TTS скрипт: `/root/.openclaw/shared/skills/edge-tts/scripts/tts-converter.js`
- Голос: `ru-RU-DmitryNeural`
- Длинный текст → части → `ffmpeg concat` → ogg opus → `message(asVoice: true)`

## Puppeteer (скриншоты)
- Шаблон скрипта: `/tmp/screenshot.js`
- Viewport: 390×844, deviceScaleFactor: 2, isMobile: true
- iPhone UA, waitUntil networkidle2 + 5 сек + скролл
- YouTube каналы: открывать `/shorts` вкладку

## PostgreSQL — ⚠️ ВАЖНО

### Основная база (Docker, порт 5432) — ИСПОЛЬЗОВАТЬ ЭТУ
```bash
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```
- Таблицы: telegram_messages (16K+ сообщений, 36 чатов), mymeet.meetings (293 встречи)
- **ВСЕГДА указывать `-h localhost -p 5432`!**
- Локальный PG 16 (порт 5433) — НЕ использовать, ловушка!

### Factory DB (Distribution DB) — ОСНОВНАЯ РАБОЧАЯ
- Host: 193.124.112.222:49002
- DB: factory
- User: roman_ai_readonly (READ ONLY)
- Config: `/root/.openclaw/shared/integrations/distribution-db/config.json`
- Скрипт: `python3 /root/.openclaw/workspace/shared/scripts/distribution_db.py query "SQL"`
- Документация (⭐ библия): `/root/.openclaw/workspace/shared/skills/distribution-db/`
  - DATABASE_SCHEMA.md, QUERIES.md, BEST_PRACTICES.md

### Алиасы таблиц Distribution DB
- `fp` → factory_projects
- `pa` → pack_accounts
- `fia` → factory_inst_accounts
- `fir` → factory_inst_reels
- `firs` → factory_inst_reels_stats

### ⚠️ Ключевые правила Distribution DB
- `sum_views`, `sum_likes` и др. `sum_*` — значения за КОНКРЕТНЫЕ сутки, НЕ накопительные!
- Для итогов за период — SUM(sum_views)
- Связь accounts→reels через `instagram_id = account_id` (НЕ через id!)
- Всегда фильтровать по `collected_at` — там индекс

## Google Sheets
- Credentials: `/root/.openclaw/shared/integrations/google-calendar/credentials.json`
- Token: `/root/.openclaw/shared/integrations/google-calendar/token.json`
- Таблица метрик: `1kMKgKgJKspoSny9rjZ5cKIyhXYe8IrD2Tstal4ZmpzY`
  - Лист "Профайл клиенты" строка 39 — план просмотров по клиентам
