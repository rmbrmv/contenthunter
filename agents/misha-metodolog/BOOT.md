# BOOT.md — Gateway Restart Checklist

*Runs automatically on gateway restart. Keep short — max 20 lines.*

## On Restart
1. Check `current-task.md` — was I in the middle of something?
2. If active task found → notify user: "Перезапустился, продолжаю: {task}"
3. Check `shared/BACKLOG.md` — any urgent/overdue items?
4. If urgent items → notify user

## Notify Format
Send via message tool to owner:
"🔄 Перезапустился. {current task or 'Всё чисто, готов к работе'}"

Only send if something needs attention. Silent restart is fine if nothing urgent.
