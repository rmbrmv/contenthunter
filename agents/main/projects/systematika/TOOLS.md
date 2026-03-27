# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## TTS (Text-to-Speech)

- **Engine:** edge-tts (Microsoft Edge neural TTS, бесплатный)
- **Preferred voice:** `ru-RU-SvetlanaNeural` (женский, русский)
- **Speed:** `+10%` (1.1x от обычной скорости)
- **Location:** `/root/.openclaw/workspace/shared/skills/edge-tts/scripts`

**Использование (npx node-edge-tts):**
```bash
cd /root/.openclaw/workspace/shared/skills/edge-tts/scripts
npx node-edge-tts -t "Текст для озвучки" -v ru-RU-SvetlanaNeural -r +10% -f /tmp/voice.mp3
```

## STT (Speech-to-Text)

- **Engine:** Groq Whisper API (приоритет #1, быстрый ⚡)
- **Fallback:** faster-whisper (если Groq не доступен)
- **Model:** whisper-large-v3 (Groq)

Использование (Groq):
```bash
python3 /root/.openclaw/workspace/shared/scripts/groq_whisper.py audio.ogg
```

## Автоисправление раскладки

- **Скрипт:** `/root/.openclaw/workspace/shared/scripts/keyboard_layout.py`
- **Что делает:** Автоматически исправляет текст, написанный в неправильной раскладке (RU↔EN)

Использование:
```bash
python3 /root/.openclaw/workspace/shared/scripts/keyboard_layout.py "ltkfq"
```

---

Add whatever helps you do your job. This is your cheat sheet.
