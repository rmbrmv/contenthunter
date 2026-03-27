# HEARTBEAT.md

## ⏰ Ежедневная проверка Zoom → RAG (раз в день, в рабочее время)

**Когда проверять:** 1 раз в сутки, если прошло >20 часов с последней проверки.  
**Состояние:** `/root/.openclaw/workspace-volodya-sisadmin/memory/zoom-monitor-state.json`

### Алгоритм проверки:

1. **Свежие встречи в БД** (Python + psycopg2):
   ```sql
   SELECT meeting_date::date, count(*) FROM mymeet.meetings
   WHERE meeting_date >= now() - interval '2 days'
   GROUP BY 1 ORDER BY 1
   ```
   - Если за сегодня И вчера — 0 встреч (рабочий день пн-пт) → **алерт Роману в Telegram** (@rmbrmv, ID 295230564)
   - Алерт: "🚨 Zoom RAG: за последние 2 дня нет новых встреч в базе. Проверить zoom_transcribe.py"

2. **Ошибки в логах**:
   ```bash
   grep -i "error\|failed\|expired" /root/.openclaw/workspace/logs/zoom_*.log | tail -20
   ```
   - Если `Access token is expired` встречается >3 раз подряд → алерт Роману
   - `Failed to delete from cloud: 400` — некритично, пропускать

3. **Рост чанков**:
   ```sql
   SELECT count(*) FROM mymeet.meeting_chunks
   ```
   - Сравнить с предыдущим значением из state-файла
   - Если не растёт >48 часов при наличии встреч — алерт

4. **Сохранить состояние** в `memory/zoom-monitor-state.json`:
   ```json
   {
     "lastCheck": <unix_timestamp>,
     "lastChunkCount": <число>,
     "lastMeetingCount": <число>
   }
   ```

### Алерт Роману:
```python
# channel=telegram, target=295230564 (или @rmbrmv)
```
Использовать `message` tool: `action=send`, `target=295230564`, `channel=telegram`

### Текущий статус (26.02.2026):
- ✅ Встречи идут: 6 за 25.02, 7 за 26.02
- ✅ Аккаунт 1 (Роман): работает, последний запуск 17:30 UTC
- ⚠️ `Access token is expired` был в логах (но последние запуски успешны — token обновился)
- ⚠️ `Failed to delete from cloud: 400` — повторяется, некритично (права на удаление)
- Чанков: 3749, встреч: 334
