# HEARTBEAT.md

## System Health (каждый heartbeat)
- Запустить `/root/.openclaw/workspace/shared/scripts/monitoring/check_and_alert.py`
- Если есть алерты (WARNING/CRITICAL) → отправить сообщение Роману
- Если всё OK → молчать

## Периодические задачи (ротация)
Проверять не чаще 1 раза в день каждую:

### Email (TODO: когда настроим)
- Проверить важные непрочитанные

### Calendar (TODO: когда настроим)  
- Предстоящие события (<2h)

## Фоновая работа
- Memory maintenance (review daily files → update MEMORY.md) - раз в неделю
