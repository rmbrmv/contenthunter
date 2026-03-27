# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## TTS (Text-to-Speech)

- **Engine:** edge-tts (Microsoft Edge neural TTS, бесплатный)
- **Preferred voice:** `ru-RU-SvetlanaNeural` (женский, русский)
- **Alternative:** `ru-RU-DmitryNeural` (мужской, русский)
- **Speed:** `+10%` (1.1x от обычной скорости)
- **Location:** `/root/.openclaw/workspace/skills/edge-tts/scripts`

**Использование (npx node-edge-tts):**
```bash
cd /root/.openclaw/workspace/skills/edge-tts/scripts
npx node-edge-tts -t "Текст для озвучки" -v ru-RU-SvetlanaNeural -r +10% -f /tmp/voice.mp3
```

**⚠️ Важно:**
- Для **длинных текстов** (>500 символов) может быть таймаут — сократить текст или разбить на части
- Скрипт `tts-converter.js` сломан — использовать `npx node-edge-tts` напрямую
- Голосовое отправлять через `message` tool с `asVoice: true`

## STT (Speech-to-Text)

- **Engine:** Groq Whisper API (приоритет #1, быстрый ⚡)
- **Fallback:** faster-whisper (если Groq не доступен)
- **Model:** whisper-large-v3 (Groq)
- **Speed:** 1-2 секунды (Groq) vs 2 минуты (faster-whisper)

Использование (Groq):
```bash
python3 /root/.openclaw/workspace/scripts/groq_whisper.py audio.ogg
```

Fallback (faster-whisper):
```python
from faster_whisper import WhisperModel
model = WhisperModel("medium", device="cpu")
segments, info = model.transcribe("audio.mp3", language="ru")
```

## Telegram

- Bot: @openclawromans_bot
- Chat ID: 295230564

## Автоисправление раскладки

- **Скрипт:** `/root/.openclaw/workspace/scripts/keyboard_layout.py`
- **Что делает:** Автоматически исправляет текст, написанный в неправильной раскладке (RU↔EN)

Примеры:
- `ltkfq` → `делай`
- `ghbdtn` → `привет`
- `hello` (в русской) → `hello` (исправлено)

Использование:
```bash
python3 /root/.openclaw/workspace/scripts/keyboard_layout.py "ltkfq"
```

**Правило:** Если входящее сообщение выглядит бессмысленным, автоматически проверяю обе раскладки и понимаю без уточнения.

---

Add whatever helps you do your job. This is your cheat sheet.

## Google Drive → PostgreSQL Sync (опциональный)

**Скрипт:** `/root/.openclaw/workspace/scripts/google_drive_sync.py`  
**Документация:** `/root/.openclaw/workspace/docs/GOOGLE_DRIVE_RAG.md`

**Возможности:**
- Синхронизация документов из Google Drive в PostgreSQL
- Embeddings для семантического поиска
- Batch processing (по умолчанию 5 файлов за раз)
- Инкрементальный sync (только измененные файлы)

**Использование:**
```bash
# Полная синхронизация всех документов Drive (ВНИМАНИЕ: долго!)
cd /root/.openclaw/workspace
source venv-google/bin/activate
python scripts/google_drive_sync.py sync --batch-size 10

# Инкрементальная синхронизация (только новые/измененные)
python scripts/google_drive_sync.py sync --incremental

# Статистика
python scripts/google_drive_sync.py stats

# Поиск по загруженным документам
python scripts/google_drive_sync.py search --query "ваш запрос" --limit 5
```

**По умолчанию:** НЕ запускается автоматически (доступно только при ручном вызове).
