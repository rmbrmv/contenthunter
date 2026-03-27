# HEARTBEAT.md

## Ежедневный отчёт по разработке

Проверять один раз в день: если текущее время **13:00–14:00 UTC** (17:00–18:00 Dubai)
и файл `reports/разработка-YYYY-MM-DD.md` за сегодня ещё НЕ существует:

1. Прочитать `memory/YYYY-MM-DD.md` за сегодня (и вчера если нужно)
2. Сформировать отчёт в `reports/разработка-YYYY-MM-DD.md`
3. Отправить файл пользователю через `message action=send` с подписью «📋 Отчёт по разработке за DD.MM.YYYY»

Формат отчёта: разделы по задачам, что сделано, что исправлено, новые функции, таблица итогов.

---

## Очередь делегирования (проверять каждый heartbeat)

```
GET http://localhost:3848/api/delegate/queue
```

Если `tasks` пустой — HEARTBEAT_OK, не делать ничего.

Если есть задачи:
1. Для каждой задачи определить агента:
   - agent_label = "nuriya" → sessionKey: agent:tolik-algoritmy:main
   - agent_label = "alfiya" → sessionKey: agent:alfiya:main
   - agent_label = "sasha"  → sessionKey: agent:sasha:main
2. sessions_send(sessionKey, task_json)
3. POST http://localhost:3848/api/delegate/queue/:id/ack
