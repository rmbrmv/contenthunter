# Data Engine — Центральный слой обработки данных

> Data Engine — это ядро системы Elena-HR. Все сырые данные проходят через него прежде чем попасть к агентам. Агенты никогда не читают сырые данные напрямую.

---

## Зачем нужен Data Engine

Без единого слоя обработки каждый агент вынужден сам интерпретировать сырые данные — это приводит к:
- Противоречиям: два агента могут по-разному оценить одно событие
- Дублированию вычислений: каждый агент считает одни и те же метрики
- Потере контекста: агент видит только свой кусок данных
- Невозможности калибровки: нет единой точки для применения обратной связи

Data Engine решает всё это: одна точка входа, одна точка расчёта, один стандартизированный JSON на выходе.

---

## 7 функций Data Engine

### 1. Сбор данных из источников
Подключается к 5 источникам через коннекторы. Работает в event-driven режиме: каждое событие в источнике немедленно попадает в очередь обработки. Нет polling'а по расписанию — только реакция на события.

### 2. Очистка данных
- Удаление дублей (одно сообщение попало из двух источников)
- Фильтрация нерелевантного контента (боты, системные сообщения, стикеры)
- Нормализация имён (Иван Иванов = @ivan_i = employee_id_042)
- Валидация форматов (корректная дата, корректный JSON отчёта)

### 3. Нормализация
Приведение всех событий к единому формату `UnifiedEvent`:
```json
{
  "event_id": "evt_20260316_001",
  "timestamp": "2026-03-16T09:14:22Z",
  "source": "telegram",
  "employee_id": "emp_042",
  "event_type": "message",
  "payload": {
    "text": "...",
    "chat_id": "corp_dev",
    "reply_to": null
  },
  "raw_ref": "tg_msg_8821937"
}
```

### 4. Расчёт командных метрик
Агрегирует нормализованные события в метрики по каждому сотруднику за период (день / неделя). Применяет веса и confidence scores. Подробно — в разделе «Метрики» ниже.

### 5. Построение графа коммуникаций
На основе событий типа `reply`, `mention`, `meeting_together` строит граф взаимодействий: кто с кем общается, как часто, в каком направлении. Обновляется еженедельно.

### 6. Формирование аналитических сигналов
Автоматически детектирует паттерны:
- `SHARP_DROP` — TPI упал на 3+ пункта за неделю
- `SILENT_DAY` — сотрудник не выходил на связь рабочий день
- `REPORT_COPY` — отчёт идентичен предыдущему (по хэшу)
- `TOXIC_CONFLICT` — негативная тональность в адрес коллеги
- `ZERO_PERFORMANCE` — факт = 0 при наличии плана
- `LOW_CONFIDENCE` — менее 30% ожидаемых точек данных за период

### 7. Передача результатов агентам
Формирует стандартный JSON-пакет и передаёт всем агентам одновременно. При наличии сигналов высокого приоритета — немедленная передача (не ждёт конца периода).

---

## Источники данных

### 1. Telegram-чаты
```json
{
  "source": "telegram",
  "event_type": "message",
  "fields": {
    "message_id": "string",
    "chat_id": "string",
    "chat_category": "internal|client|hr",
    "timestamp": "ISO-8601",
    "from_username": "string",
    "text": "string",
    "reply_to_message_id": "string|null",
    "mentions": ["@username"],
    "has_media": "boolean"
  }
}
```

### 2. Zoom / Онлайн-встречи
```json
{
  "source": "zoom",
  "event_type": "meeting_completed",
  "fields": {
    "meeting_id": "string",
    "title": "string",
    "started_at": "ISO-8601",
    "duration_minutes": "integer",
    "participants": ["employee_id"],
    "transcript_segments": [
      {
        "speaker_id": "string",
        "text": "string",
        "start_time_sec": "integer"
      }
    ]
  }
}
```

### 3. Ежедневные отчёты сотрудников
```json
{
  "source": "daily_report",
  "event_type": "report_submitted",
  "fields": {
    "employee_id": "string",
    "date": "YYYY-MM-DD",
    "done": "string",
    "not_done": "string",
    "blockers": "string|null",
    "waiting_from": "string|null",
    "plan_tomorrow": "string",
    "self_rating": "integer 1-10"
  }
}
```

### 4. CRM / Таск-трекер
```json
{
  "source": "crm|tasktracker",
  "event_type": "task_updated",
  "fields": {
    "task_id": "string",
    "assignee_id": "string",
    "title": "string",
    "status": "todo|in_progress|done|overdue",
    "due_date": "YYYY-MM-DD",
    "completed_at": "ISO-8601|null",
    "plan_value": "number|null",
    "fact_value": "number|null"
  }
}
```

### 5. Опросы (пульс / peer-review)
```json
{
  "source": "survey",
  "event_type": "survey_response",
  "fields": {
    "survey_type": "pulse|peer_review",
    "respondent_id": "string",
    "target_id": "string|null",
    "week": "YYYY-Www",
    "answers": {
      "asked_for_help": ["employee_id"],
      "helped": ["employee_id"],
      "blocker": "string|null",
      "self_rating": "integer 1-10",
      "peer_reliability": "integer 1-10",
      "advice_from": ["employee_id"],
      "hard_to_work_with": "string|null"
    }
  }
}
```

---

## Исходящий JSON-пакет метрик

Полная структура пакета, который Data Engine передаёт агентам:

```json
{
  "period": "2026-W11",
  "generated_at": "2026-03-17T08:00:00Z",
  "team_tpi": 7.2,
  "team_tpi_confidence": 0.84,
  "active_members_count": 8,
  "alerts": [
    {
      "type": "SHARP_DROP",
      "employee_id": "emp_007",
      "severity": "high",
      "details": "TPI упал с 8.1 до 5.2 за одну неделю"
    }
  ],
  "members": [
    {
      "employee_id": "emp_001",
      "name": "Андреева Мария",
      "status": "active",
      "tpi": 8.4,
      "tpi_prev": 7.8,
      "tpi_delta": 0.6,
      "ikn": 8.1,
      "ir": 8.6,
      "metrics": {
        "communication": { "score": 8.2, "confidence": 0.92 },
        "discipline": { "score": 8.5, "confidence": 0.97 },
        "engagement": { "score": 7.6, "confidence": 0.88 },
        "expertise": { "score": 8.9, "confidence": 0.85 },
        "performance": { "score": 8.3, "confidence": 0.91 }
      },
      "flags": [],
      "data_points": {
        "messages": 142,
        "reports_submitted": 5,
        "reports_expected": 5,
        "meetings_attended": 4,
        "meetings_total": 4,
        "tasks_done": 12,
        "tasks_planned": 13
      }
    },
    {
      "employee_id": "emp_007",
      "name": "Григорьев Алексей",
      "status": "active",
      "tpi": 5.2,
      "tpi_prev": 8.1,
      "tpi_delta": -2.9,
      "ikn": 4.8,
      "ir": 5.5,
      "metrics": {
        "communication": { "score": 4.5, "confidence": 0.87 },
        "discipline": { "score": 5.1, "confidence": 0.91 },
        "engagement": { "score": 4.8, "confidence": 0.82 },
        "expertise": { "score": 6.0, "confidence": 0.79 },
        "performance": { "score": 5.1, "confidence": 0.88 }
      },
      "flags": ["SHARP_DROP"],
      "data_points": {
        "messages": 31,
        "reports_submitted": 4,
        "reports_expected": 5,
        "meetings_attended": 3,
        "meetings_total": 4,
        "tasks_done": 6,
        "tasks_planned": 10
      }
    }
  ],
  "communication_graph": {
    "nodes": [...],
    "edges": [...]
  },
  "trends": {
    "team_tpi_4w": [6.8, 7.0, 7.1, 7.2],
    "rising": ["emp_001", "emp_003"],
    "falling": ["emp_007", "emp_008"]
  },
  "feedback_adjustments_applied": 2
}
```

---

## 5 базовых метрик

### Коммуникация (вес в ИКН: 40%)
| Под-метрика | Источник | Как считается |
|---|---|---|
| Плотность взаимодействия | Telegram | Кол-во сообщений / рабочих дней |
| Распределение общения | Telegram | Коэффициент Джини по чатам |
| Sentiment score | Telegram | NLP-анализ тональности (-1 до +1) |
| Response time | Telegram | Среднее время ответа на @mention (часы) |

### Дисциплина (вес в ИКН: 35%)
| Под-метрика | Источник | Как считается |
|---|---|---|
| Регулярность отчётов | Daily report | Факт/ожидаемые отчёты × 10 |
| Посещаемость встреч | Zoom | Посещённые/запланированные встречи × 10 |
| Выполнение задач в срок | CRM/Таскер | Задачи в срок / все задачи × 10 |

### Вовлечённость (вес в ИКН: 25%)
| Под-метрика | Источник | Как считается |
|---|---|---|
| Участие в обсуждениях | Telegram | Доля реплей и тредов от всех сообщений |
| Инициатива | Telegram + Отчёты | Сообщения без запроса, предложения в отчётах |
| Meeting contribution score | Zoom | Доля реплик сотрудника в транскрипте |
| Пульс-опрос | Survey | Средняя самооценка недели (нормализованная) |

### Экспертность (вес в ИР: 45%)
| Под-метрика | Источник | Как считается |
|---|---|---|
| Вклад в решения | Zoom + Telegram | NLP: frequency of solution-oriented phrases |
| Помощь коллегам | Survey (peer) | Кол-во раз упомянут как помощник в опросах |
| Качество ответов | Telegram (клиент) | Время ответа клиенту + sentiment клиента после |

### Результативность (вес в ИР: 55%)
| Под-метрика | Источник | Как считается |
|---|---|---|
| План-факт задач | CRM/Таскер | Сумма fact_value / plan_value × 10 |
| Завершённые проекты | CRM | Закрытые задачи / все задачи недели × 10 |
| KPI (если есть) | CRM | Индивидуальный KPI из системы |

---

## Агрегированный командный индекс

```
ИКН = Коммуникация×0.40 + Дисциплина×0.35 + Вовлечённость×0.25
ИР  = Экспертность×0.45 + Результативность×0.55
TPI = ИКН×0.45 + ИР×0.55

Team_TPI = среднее(TPI всех активных сотрудников)
Team_Confidence = среднее(confidence всех метрик всех сотрудников)
```

Confidence score считается как отношение фактических точек данных к ожидаемым:
- `< 0.5` → метрика ненадёжна, агент должен это явно указать
- `0.5–0.7` → интерпретировать осторожно
- `> 0.7` → стандартная интерпретация

---

## Граф коммуникаций

### Алгоритм построения
1. Собрать все события за период: reply, mention, joint_meeting
2. Для каждой пары (A, B) посчитать вес связи:
   `weight = replies(A→B) + mentions(A→B) + joint_meetings × 5`
3. Нормализовать веса (0–100)
4. Добавить узлы для всех активных сотрудников (включая изолированных)

### JSON структура
```json
{
  "nodes": [
    {
      "id": "emp_001",
      "name": "Андреева М.",
      "tpi": 8.4,
      "activity": 142,
      "dept": "dev",
      "is_hub": true,
      "is_isolated": false
    }
  ],
  "edges": [
    {
      "source": "emp_001",
      "target": "emp_002",
      "weight": 45,
      "direction": "bidirectional"
    }
  ],
  "insights": {
    "hubs": ["emp_001", "emp_006"],
    "isolated": ["emp_008"],
    "weak_bridges": [["dev", "sales"]]
  }
}
```

---

## Схема хранения данных

### events (immutable, append-only)
```sql
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(64) UNIQUE,
    timestamp TIMESTAMPTZ NOT NULL,
    source VARCHAR(20) NOT NULL,
    employee_id VARCHAR(20),
    event_type VARCHAR(30) NOT NULL,
    payload JSONB NOT NULL,
    raw_ref VARCHAR(100),
    corrects_event_id BIGINT REFERENCES events(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### metrics_cache (версионированные метрики)
```sql
CREATE TABLE metrics_cache (
    id BIGSERIAL PRIMARY KEY,
    period VARCHAR(10) NOT NULL,   -- '2026-W11'
    employee_id VARCHAR(20),
    metric_name VARCHAR(30),
    score FLOAT,
    confidence FLOAT,
    data_points INT,
    input_hash VARCHAR(64),
    calculated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### feedback_log (обратная связь руководителя)
```sql
CREATE TABLE feedback_log (
    id BIGSERIAL PRIMARY KEY,
    period VARCHAR(10),
    employee_id VARCHAR(20),
    metric_name VARCHAR(30),
    ai_score FLOAT,
    human_score FLOAT,
    human_comment TEXT,
    adjustment_applied BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Дополнительные сигналы

| Сигнал | Источник | Порог | Приоритет |
|---|---|---|---|
| Sentiment score | Telegram NLP | < -0.4 за день | High |
| Response time | Telegram | > 4 часов на @mention | Medium |
| Meeting contribution | Zoom | < 5% реплик при 60+ мин встрече | Low |
| Silent day flag | Все источники | 0 событий за рабочий день | High |
| Report copy flag | Daily report | Хэш совпадает с предыдущим | Medium |
