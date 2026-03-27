# Аналитические дашборды Elena-HR

---

## Дашборд недели

### Блоки дашборда

| # | Блок | Источник | Обязательный |
|---|------|----------|--------------|
| 1 | Заголовок и период | Data Engine | ✅ |
| 2 | Командный TPI | Data Engine | ✅ |
| 3 | Таблица сотрудников | Data Engine + Аналитик | ✅ |
| 4 | Топ-3 инсайта | Аналитик | ✅ |
| 5 | Алерты и сигналы | Data Engine | Если есть |
| 6 | Рекомендации Коуча | Коуч | ✅ |
| 7 | Кадровые события | Администратор | Если есть |
| 8 | Граф коммуникаций (миниатюра) | Data Engine | Раз в месяц |

### JSON структура дашборда

```json
{
  "dashboard_id": "dashboard_2026-W11",
  "week": "2026-W11",
  "period": "10–16 марта 2026",
  "generated_at": "2026-03-17T08:00:00Z",
  "generated_by": "hr_director",

  "team_tpi": {
    "value": 7.2,
    "prev_value": 6.8,
    "delta": 0.4,
    "confidence": 0.84,
    "business_potential": "≈ ₽2.1M",
    "trend_4w": [6.5, 6.8, 7.0, 7.2]
  },

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
      "overall_confidence": 0.91
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
      "overall_confidence": 0.85
    }
  ],

  "insights": [
    {
      "type": "positive",
      "text": "Командный TPI вырос четыре недели подряд. Основной драйвер — дисциплина: регулярность отчётов выросла с 76% до 94% за месяц.",
      "confidence": 0.91,
      "source": "analyst"
    },
    {
      "type": "negative",
      "text": "Григорьев А.: TPI 8.1 → 5.2 за одну неделю. Все метрики упали синхронно — признак внешнего стресс-фактора.",
      "confidence": 0.85,
      "source": "analyst"
    },
    {
      "type": "neutral",
      "text": "Захаров И. изолирован в графе коммуникаций уже вторую неделю подряд. Связан только с одним сотрудником.",
      "confidence": 0.78,
      "source": "sociologist"
    }
  ],

  "alerts": [
    {
      "id": "alert_001",
      "severity": "high",
      "type": "SHARP_DROP",
      "employee_id": "emp_007",
      "employee_name": "Григорьев Алексей",
      "description": "TPI упал с 8.1 до 5.2 за одну неделю (-2.9)",
      "recommended_action": "Провести 1-on-1 до пятницы",
      "created_at": "2026-03-16T09:00:00Z",
      "status": "open"
    }
  ],

  "recommendations": [
    {
      "priority": 1,
      "employee_id": "emp_007",
      "employee_name": "Григорьев Алексей",
      "action": "1-on-1 сегодня или завтра",
      "why": "TPI упал с 8.1 до 5.2. Синхронное падение всех метрик — нетипично, возможен личный стресс-фактор.",
      "script_preview": "«Алексей, как ты? Есть что-то, что мешает работать в привычном ритме?»",
      "timing": "До пятницы 20 марта",
      "source": "coach"
    },
    {
      "priority": 2,
      "employee_id": "emp_008",
      "employee_name": "Захаров Иван",
      "action": "Назначить ментора из основного кластера",
      "why": "Изолирован 2 недели. TPI падает постепенно.",
      "timing": "На следующей неделе",
      "source": "coach"
    }
  ],

  "hr_events": [
    {
      "type": "hire",
      "employee_name": "Козлов Сергей",
      "date": "2026-03-14",
      "note": "Активирован онбординг-режим. Мягкие пороги на 4 недели.",
      "team_tpi_impact": null
    }
  ],

  "data_quality": {
    "overall_confidence": 0.84,
    "warnings": [
      "CRM не подключён. Метрика Результативность — только по отчётам.",
      "Ефимов П.: coverage 30%, данных мало — confidence 0.45"
    ]
  }
}
```

---

## Граф команды

### Что показывает

| Элемент | Что означает |
|---------|-------------|
| **Узел (круг)** | Сотрудник |
| **Размер узла** | Активность (количество взаимодействий за неделю) |
| **Цвет узла** | TPI: 🔴 < 5.0 / 🟠 5.0–7.0 / 🟢 > 7.0 |
| **Ребро (линия)** | Коммуникационная связь между двумя сотрудниками |
| **Толщина ребра** | Интенсивность связи (количество взаимодействий) |
| **Пунктирное ребро** | Слабая связь (< 5 взаимодействий за неделю) |

### Как читать граф

**Хабы (крупные узлы с многими рёбрами):**
Неформальные центры коммуникации. Обычно это лидеры мнений или ключевые коммуникаторы. Если хаб уйдёт — команда потеряет связность.

**Изолированные узлы:**
Сотрудники с малым числом связей. Риск: они не интегрированы в команду, информация до них доходит медленно. Требуют внимания руководителя.

**Слабые мосты:**
Одна связь между двумя кластерами. Если эта связь разрушится — кластеры окажутся изолированы друг от друга.

**Кластеры:**
Плотные группы. Могут соответствовать формальным отделам или формироваться органически. Слабые связи между кластерами — сигнал о разрывах в коммуникации.

### JSON структура графа

```json
{
  "graph_id": "graph_2026-W11",
  "period": "2026-W11",
  "generated_at": "2026-03-17T08:00:00Z",
  "nodes": [
    {
      "id": "emp_001",
      "name": "Андреева М.",
      "tpi": 8.4,
      "activity": 142,
      "dept": "dev",
      "is_hub": true,
      "is_isolated": false,
      "centrality": 0.87
    },
    {
      "id": "emp_008",
      "name": "Захаров И.",
      "tpi": 3.4,
      "activity": 12,
      "dept": "support",
      "is_hub": false,
      "is_isolated": true,
      "centrality": 0.08
    }
  ],
  "edges": [
    {
      "source": "emp_001",
      "target": "emp_002",
      "weight": 45,
      "type": "strong"
    },
    {
      "source": "emp_008",
      "target": "emp_007",
      "weight": 8,
      "type": "weak"
    }
  ],
  "insights": {
    "hubs": ["emp_001", "emp_006"],
    "isolated": ["emp_008"],
    "clusters": [
      {"name": "dev", "members": ["emp_001", "emp_002", "emp_004", "emp_006"]},
      {"name": "support", "members": ["emp_007", "emp_008"]}
    ],
    "weak_bridges": ["dev ↔ support: 1 связь"],
    "cohesion_index": 0.67
  }
}
```
