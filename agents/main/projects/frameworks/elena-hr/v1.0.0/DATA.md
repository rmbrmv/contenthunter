# Elena-HR — Источники данных

## PostgreSQL
- **Host:** localhost:5432
- **DB:** openclaw
- **User:** openclaw / **Pass:** openclaw123

## Telegram-чаты (20 136 сообщений)
```sql
SELECT chat_id, chat_title, username, text, message_date, metadata
FROM telegram_messages
WHERE message_type = 'message'
ORDER BY message_date DESC;
```

Поля `metadata` (JSONB) могут содержать дополнительный контекст (reply_to, reactions и др.).

## Zoom-транскрипты (115 встреч)
```sql
SELECT topic, host_email, start_time, duration_minutes, transcription
FROM meetings.transcriptions
ORDER BY start_time DESC;
```

## Доступные чаты (примеры)
```sql
SELECT DISTINCT chat_title, chat_id, COUNT(*) msg_count
FROM telegram_messages
GROUP BY chat_title, chat_id
ORDER BY msg_count DESC;
```

## RAG (семантический поиск)
Поле `embedding` (vector 384) — доступен семантический поиск через pgvector:
```sql
-- Поиск похожих сообщений
SELECT username, text, message_date
FROM telegram_messages
ORDER BY embedding <=> '[...vector...]'
LIMIT 10;
```

## Скрипты парсинга
- `/root/.openclaw/workspace/shared/scripts/telegram_parser.py`
- `/root/.openclaw/workspace/shared/scripts/zoom_transcribe.py`
- `/root/.openclaw/workspace/shared/scripts/zoom_transcribe_account2.py`
