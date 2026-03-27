# HEARTBEAT.md

## System Health (каждый heartbeat)
- **Полная диагностика системы:**
  - Запустить `/root/.openclaw/workspace/shared/scripts/monitoring/system_health_check.sh`
  - Если есть ⚠️ WARNING → отправить сообщение Роману с деталями
  - **Auto-approve pending devices:** `/root/.openclaw/workspace/shared/scripts/gateway_auto_approve.sh`
  - Если Gateway не работает → перезапустить: `systemctl --user restart openclaw-gateway`
- Если всё ✅ OK → молчать

## Периодические задачи (ротация)
Проверять не чаще 1 раза в день каждую:

### Email (TODO: когда настроим)
- Проверить важные непрочитанные

### Calendar (TODO: когда настроим)  
- Предстоящие события (<2h)

## Фоновая работа
- Memory maintenance (review daily files → update MEMORY.md) - раз в неделю
