# SQL — Выборка данных для TPI

> Запросы для сбора данных по сотруднику за неделю.
> База: PostgreSQL, схема public + team + mymeet.
> Запускается автоматически перед формированием промпта.

---

## 1. Сообщения из Telegram-чатов

### Внутренние корпоративные чаты

```sql
-- Все сообщения сотрудника за неделю во внутренних чатах
SELECT
    tm.message_date,
    tm.chat_title,
    tm.text
FROM telegram_messages tm
JOIN team.employees e ON e.telegram_username = tm.username
WHERE
    e.name = :employee_name
    AND tm.message_date >= :date_from
    AND tm.message_date < :date_to
    AND tm.category IN ('team', 'internal', 'general')
ORDER BY tm.message_date ASC;
```

### Клиентские чаты

```sql
-- Сообщения сотрудника в клиентских чатах
SELECT
    tm.message_date,
    tm.chat_title,
    tm.text
FROM telegram_messages tm
JOIN team.employees e ON e.telegram_username = tm.username
WHERE
    e.name = :employee_name
    AND tm.message_date >= :date_from
    AND tm.message_date < :date_to
    AND tm.category IN ('client', 'project')
ORDER BY tm.message_date ASC;
```

### Контекст: теги и ответы на сотрудника

```sql
-- Сообщения где тегали сотрудника (для проверки времени ответа)
SELECT
    tm.message_date,
    tm.chat_title,
    tm.username AS sender,
    tm.text
FROM telegram_messages tm
JOIN team.employees e ON tm.text ILIKE '%@' || e.telegram_username || '%'
WHERE
    e.name = :employee_name
    AND tm.message_date >= :date_from
    AND tm.message_date < :date_to
ORDER BY tm.message_date ASC;
```

---

## 2. Zoom-транскрипты

```sql
-- Фрагменты транскриптов где упоминается или говорит сотрудник
SELECT
    m.meeting_date,
    m.title,
    m.participants,
    -- Извлекаем только реплики сотрудника (по имени/алиасу)
    m.content_text
FROM mymeet.meetings m
JOIN team.people_aliases pa ON
    m.participants ILIKE '%' || pa.zoom_name || '%'
    OR m.content_text ILIKE '%' || pa.zoom_name || ':%'
WHERE
    pa.employee_id = (SELECT id FROM team.employees WHERE name = :employee_name)
    AND m.meeting_date >= :date_from
    AND m.meeting_date < :date_to
ORDER BY m.meeting_date ASC;
```

---

## 3. Статистика дисциплины

```sql
-- Активность по дням (для выявления "молчащих дней")
SELECT
    DATE(tm.message_date) AS day,
    COUNT(*) AS message_count,
    MIN(tm.message_date) AS first_message,
    MAX(tm.message_date) AS last_message
FROM telegram_messages tm
JOIN team.employees e ON e.telegram_username = tm.username
WHERE
    e.name = :employee_name
    AND tm.message_date >= :date_from
    AND tm.message_date < :date_to
GROUP BY DATE(tm.message_date)
ORDER BY day;
```

---

## 4. Предыдущая оценка TPI (для динамики)

```sql
-- Последняя оценка сотрудника (если есть)
SELECT
    pr.rating_date,
    pr.communication,
    pr.discipline,
    pr.engagement,
    pr.expertise,
    pr.performance,
    pr.ikn,
    pr.ir,
    pr.tpi,
    pr.notes
FROM people_ratings pr
JOIN people p ON p.id = pr.person_id
WHERE
    p.canonical_name = :employee_name
ORDER BY pr.rating_date DESC
LIMIT 1;
```

---

## 5. Итоговый сводный запрос (для скрипта)

```python
# Псевдокод для скрипта сборки данных

def collect_tpi_data(employee_name: str, date_from: date, date_to: date) -> dict:
    return {
        "employee": get_employee_info(employee_name),
        "internal_messages": get_internal_messages(employee_name, date_from, date_to),
        "client_messages": get_client_messages(employee_name, date_from, date_to),
        "tags_context": get_tag_mentions(employee_name, date_from, date_to),
        "zoom_excerpts": get_zoom_excerpts(employee_name, date_from, date_to),
        "daily_reports": get_daily_reports(employee_name, date_from, date_to),  # из отчётного чата
        "activity_by_day": get_daily_activity(employee_name, date_from, date_to),
        "previous_tpi": get_previous_tpi(employee_name),
    }
```

---

## Важные примечания

### Категории чатов
Текущая таблица `telegram_messages` содержит поле `category`. Нужно уточнить у Вареньки актуальные значения категорий для фильтрации:
- internal / team / general → корпоративные
- client / project → клиентские

```sql
-- Проверить актуальные категории
SELECT DISTINCT category, COUNT(*) FROM telegram_messages GROUP BY category ORDER BY count DESC;
```

### Ежедневные отчёты
Отчёты скорее всего приходят в отдельный чат. Нужно уточнить `chat_id` или `chat_title` отчётного чата:

```sql
-- Найти чат с отчётами
SELECT DISTINCT chat_title, COUNT(*) FROM telegram_messages GROUP BY chat_title ORDER BY count DESC;
```

### Zoom-транскрипты
Проверить структуру `mymeet.meetings` — поля могут отличаться от ожидаемых:

```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema = 'mymeet' AND table_name = 'meetings';
```

---

## Связанные документы
- [[TPI-мастер-промпт]]
- [[TPI-шаблон-данных]]
- [[Операционный ритм TPI]]
