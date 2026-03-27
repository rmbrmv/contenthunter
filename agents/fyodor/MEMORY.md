# MEMORY.md — Долгосрочная память Фёдора

## Пользователь
- Имя: **Роман** (Telegram username: Вовлар, ID: 295230564)
- Язык общения: русский, неформальный
- Предпочитает голосовые сообщения на русском

## Архитектура данных

### Distribution DB (основная)
- Host: 193.124.112.222:49002, DB: factory, User: roman_ai_readonly
- project_id Synatra VPN = **57**
- Связь accounts→reels: `instagram_id = account_id` (НЕ через id!)
- Дата ввода в работу — брать из Google Sheets "В. Аккаунты" столбец O
- Считать просмотры ТОЛЬКО с даты ввода в работу (не с даты создания аккаунта)

### Локальная БД (openclaw)
- `PGPASSWORD='openclaw123' psql -h localhost -p 5432 -U openclaw -d openclaw`
- `public.telegram_messages` — все чаты (16K+ сообщений, 36 чатов)
- `mymeet.meetings` + `mymeet.meeting_chunks` — транскрипты митингов
- `knowledge.documents` — Vision, Playbook, распаковки (читать через python3/psycopg2 из-за encoding)
- `client_service.contracts`, `client_service.payments`

## Формат клиентского отчёта (финальный, утверждён Романом)

```
📊 [Клиент] — еженедельный отчёт
📅 [Даты]

📈 Метрики за неделю
▸ Публикаций: X (прошлая: Y)
▸ Просмотры новых роликов: X
▸ Просмотры из архива: X
▸ Просмотры всего: X (прошлая: Y, +Z%)   ← ОБЯЗАТЕЛЬНО итоговая строка
▸ Средний охват на ролик: X (прошлая: Y, +Z%)
▸ Активных аккаунтов: X
▸ Всего публикаций в архиве: X

📍 Накопительный итог: X из ПЛАН (X%)
📍 По плану на эту дату: ~Y (Z%)

[Комментарий — честный, по Vision]

🏆 ТОП-10 роликов недели
1. ▶️ YouTube — X 👁
https://...
...

🚀 Что делаем на следующей неделе
▸ ...

💬 Всегда на связи...
```

## График выполнения плана (1-й или 2-й сетап)
- Неделя 1: +10% (итого 10%)
- Неделя 2: +20% (итого 30%)
- Неделя 3: +30% (итого 60%)
- Неделя 4: +40% (итого 100%)

**Признавать отставание честно, не прятать за позитивным спином.**

## Vision клиентского сервиса (ключевые принципы для комментариев)
- Отчёт = ощущение роста и движения вперёд
- Опережающая коммуникация: объяснять что, почему, к чему ведёт
- Удерживать инициативу: идеи, гипотезы, план
- Не оправдываться, объяснять логику
- База: `knowledge.documents` ID 1 (Playbook), ID 2 (Vision)

## TTS/STT пайплайн
- STT: `curl -s https://api.groq.com/openai/v1/audio/transcriptions -H "Authorization: Bearer [REDACTED-GROQ-KEY]" -F file="@/tmp/voice.mp3" -F model="whisper-large-v3" -F language="ru"`
- TTS: `/root/.openclaw/shared/skills/edge-tts/scripts/tts-converter.js "текст" --voice ru-RU-DmitryNeural --output /tmp/out.mp3`
- Длинный текст → части → `ffmpeg concat` → конвертить в ogg → `message(asVoice: true)`

## Скриншоты аккаунтов (Puppeteer)
- Скрипт: `/tmp/screenshot.js` (шаблон готов)
- iPhone UA, viewport 390×844, deviceScaleFactor 2
- `waitUntil: 'networkidle2'` + 5 сек + скролл для lazy load
- Открывать `/shorts` вкладку YouTube каналов

## Делегирование Даше-смысловику
- `sessions_spawn(agentId="dasha-smyslovik", task=...)`
- Передавать: данные + Vision принципы + контекст клиента
- Даша делает 2 варианта, Роман выбирает
- Роман предпочитает Вариант 1 (уверенный и тёплый)

## Google Sheets
- Метрики: `1kMKgKgJKspoSny9rjZ5cKIyhXYe8IrD2Tstal4ZmpzY`
  - Лист "Профайл клиенты" строка 39 — план просмотров
- Аккаунты: `1RsFVfNTP7aj3fgjNw6Au5fPWM81eKvDbsECcQ0znX-I`
  - Лист "В. Аккаунты": M=статус (Факт/План), N=дата прогрева, O=дата ввода в работу
