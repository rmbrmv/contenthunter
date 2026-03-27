# TPI — Схема БД

## Подключение
```
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
```

## Ключевые таблицы

### team.employees — команда
```sql
SELECT name, telegram_username, position, department, status
FROM team.employees WHERE status = 'active';
-- 27 сотрудников, все с telegram_username
```

### public.telegram_messages — сообщения
```sql
-- Поля: id, chat_id, chat_title, message_id, user_id, username, text,
--       message_type, category, message_date, metadata, embedding
-- username = telegram_username БЕЗ @ (например: oleg_ezhkov, rmbrmv)
-- category: проверить актуальные значения:
SELECT DISTINCT category, COUNT(*) FROM telegram_messages GROUP BY category ORDER BY count DESC;
```

### mymeet.meetings — Zoom-транскрипты
```sql
-- Проверить структуру:
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'mymeet' AND table_name = 'meetings';
-- Поля: meeting_date, title, participants, content_text
```

### public.people — база людей (для people_ratings)
```sql
-- canonical_name должен совпадать с team.employees.name
SELECT canonical_name FROM people WHERE canonical_name IN (
  SELECT name FROM team.employees WHERE status = 'active'
);
```

### public.people_ratings — оценки TPI
```sql
-- Структура (нужно проверить/создать если не существует):
CREATE TABLE IF NOT EXISTS people_ratings (
    id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    person_id   uuid REFERENCES people(id),
    rating_date date NOT NULL,
    communication  numeric(4,2),
    discipline     numeric(4,2),
    engagement     numeric(4,2),
    expertise      numeric(4,2),
    performance    numeric(4,2),
    ikn            numeric(4,2),
    ir             numeric(4,2),
    tpi            numeric(4,2),
    notes          text,
    created_at     timestamptz DEFAULT now(),
    UNIQUE(person_id, rating_date)
);
```

## Полезные запросы

### Активность сотрудника за неделю
```sql
SELECT DATE(message_date) as day, COUNT(*) as msgs
FROM telegram_messages
WHERE username = 'oleg_ezhkov'
  AND message_date >= '2026-02-24' AND message_date < '2026-03-03'
GROUP BY DATE(message_date) ORDER BY day;
```

### Последние оценки команды
```sql
SELECT e.name, pr.rating_date, pr.tpi, pr.ikn, pr.ir
FROM team.employees e
JOIN people p ON p.canonical_name = e.name
JOIN people_ratings pr ON pr.person_id = p.id
WHERE e.status = 'active'
ORDER BY pr.rating_date DESC, pr.tpi DESC;
```

### Чаты в которых активен сотрудник
```sql
SELECT chat_title, COUNT(*) as msgs
FROM telegram_messages
WHERE username = 'oleg_ezhkov'
GROUP BY chat_title ORDER BY msgs DESC;
```
