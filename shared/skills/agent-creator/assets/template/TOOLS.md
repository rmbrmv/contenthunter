# TOOLS.md - Local Notes

## What Goes Here
- SSH hosts and credentials
- API keys specific to this agent
- Service URLs and ports
- Telegram groups and topic IDs
- Device/camera names
- Any environment-specific details

## Examples
```
### SSH
- server-name → 192.168.1.100, user: root

### Services
- my-service → localhost:3001
- docs → https://...

### Credentials
- API key location: /root/.openclaw/credentials/...

### Telegram Groups
- Group Name: chat_id=-100XXXXXXXXX
  - General: thread_id не нужен (topic 0)
  - На публикацию: thread_id=NNN
  - Критика: thread_id=NNN
  - Настройки: thread_id=NNN

### Agent Communication
# Отправить агенту напрямую:
#   sessions_send(label="agentId", message="...", timeoutSeconds=0)
# Отправить в Telegram топик:
#   message(action=send, channel=telegram, target="-100CHAT_ID", threadId=TOPIC_ID, message="...")
```
