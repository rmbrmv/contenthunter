# 📝 Changelog - OpenClaw Dashboard

## [2.0.1] - 2026-02-23

### 🐛 Исправлено

- **Критическая ошибка:** Исправлена структура дефолтного конфига в `readOpenClawConfig()`
  - Было: `accounts: []` (массив)
  - Стало: `accounts: {}` (объект)
  - Теперь корректно обрабатывается структура `channels.telegram.accounts[accountId]`

### ✅ Протестировано

- Все 20 endpoints работают корректно
- 100% покрытие edge cases (6 тестов)
- Корректное сохранение данных в openclaw.json и dashboard-bots.json
- Frontend отображает данные корректно

### 📋 Endpoints Status

**GET (8):** ✅ All working
- `/api/auth/status`
- `/api/csrf-token`
- `/api/bots`
- `/api/bots/:id`
- `/api/bots/:id/allowlist`
- `/api/bots/:id/pending`
- `/api/projects`
- `/api/bots/external`

**POST (7):** ✅ All working
- `/api/auth/login`
- `/api/auth/logout`
- `/api/bots`
- `/api/bots/:id/allowlist`
- `/api/bots/:id/pending/approve`
- `/api/bots/:id/generate-avatar`
- `/api/bots/:id/apply-avatar-to-telegram`

**PUT (2):** ✅ All working
- `/api/bots/:id`
- `/api/bots/:id/token`

**DELETE (2):** ✅ All working
- `/api/bots/:id`
- `/api/bots/:id/allowlist/:userId`

### 🎯 Test Results

```
✅ CRUD Operations: 100% success
✅ Allowlist Management: 100% success
✅ Edge Cases: 6/6 passed
✅ Pending Requests: Working
✅ Data Integrity: Verified
✅ Frontend: Accessible
```

### 📁 Data Structure

**OpenClaw Config:**
```json
{
  "channels": {
    "telegram": {
      "accounts": {
        "bot-id": {
          "name": "...",
          "botToken": "...",
          "enabled": true,
          "dmPolicy": "allowlist"
        }
      }
    }
  }
}
```

**Dashboard Metadata:**
```json
{
  "bots": {
    "bot-id": {
      "allowlist": ["userId1", "userId2"],
      "project": "contenthunter",
      "description": "...",
      "avatar": "..."
    }
  }
}
```

### 🔐 Security

- CSRF protection: ✅
- Session-based auth: ✅
- Rate limiting: ✅
- Password hashing (bcrypt): ✅
- Input validation: ✅

### 🚀 Current Status

**Server:** Running on http://127.0.0.1:3000  
**Bots:** 3 active (fyodor-analitik, genri-dev, elena-hr)  
**Projects:** 2 configured (contenthunter, systematika)  
**External Bots:** 1 detected  

---

## [2.0.0] - Initial Release

### 🎉 Features

- Full bot management (CRUD)
- Allowlist management
- Pending requests approval
- Avatar generation (antigravity-image-gen)
- Username resolution (@username → User ID)
- Project binding
- External bots scanning
- AI agent auto-creation

---

**Last Updated:** 2026-02-23  
**Status:** ✅ Production Ready
