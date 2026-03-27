# Secrets Map — Карта хранения ключей

> ⚠️ Этот файл НЕ содержит значений ключей — только их расположение.
> Обновлено: 2026-03-27

---

## 1. OpenClaw secrets.json
**Путь:** `/root/.openclaw/secrets.json`
**Доступ:** `openclaw secrets get <name>`

| Ключ | Описание |
|------|----------|
| `providers.anthropic.anthropic_default` | Основной Anthropic API ключ (main/все агенты) |
| `providers.anthropic.anthropic_manual` | Запасной Anthropic ключ |
| `providers.anthropic.anthropic_genri` | Anthropic ключ для Генри |
| `providers.anthropic.anthropic_systematika` | Anthropic ключ для Систематики |
| `channels.telegram.vseznayka.token` | Telegram бот Всезнайка |
| `channels.telegram.pisaka.token` | Telegram бот Писака |
| `channels.telegram.apochemu.token` | Telegram бот Апочему |
| `channels.telegram.akaketo.token` | Telegram бот Акакето |
| `channels.telegram.akaketo-v2-bot.token` | Telegram бот Акакето v2 |

---

## 2. .env файлы приложений
> ⚠️ Эти файлы нужны самим приложениям и НЕ переносятся в secrets.json

| Файл | Ключи |
|------|-------|
| `/root/.openclaw/workspace-health-coord/.env` | GARMIN_EMAIL, GARMIN_PASSWORD, TP_USERNAME, TP_PASSWORD |
| `/root/.openclaw/workspace-genri/autowarm/.env` | ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, YOUTUBE_API_KEY, LAOZHANG_API_KEY, GROQ_API_KEY, APIFY_API_KEY, OPENCLAW_GATEWAY_TOKEN |
| `/root/.openclaw/workspace-genri/producer-copilot/.env` | LAOZHANG_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN |
| `/root/.openclaw/workspace-genri/validator/.env` | DATABASE_URL, S3_*, JWT_SECRET, ADMIN_LOGIN/PASSWORD, FACTORY_DB_* |
| `/root/.openclaw/workspace-genri/ch-auth/.env` | TELEGRAM_BOT_TOKEN, JWT_SECRET, SESSION_SECRET |
| `/root/.openclaw/workspace-genri/task-tracker/.env` | TELEGRAM_BOT_TOKEN |
| `/root/.openclaw/workspace-genri/model-router/.env` | ANTHROPIC_API_KEY |
| `/root/.openclaw/.env` | OPENCLAW_GATEWAY_TOKEN |

---

## 3. OAuth токены (Google, Zoom, Miro)
> ⚠️ Токены OAuth привязаны к пути, не переносятся

| Файл | Описание |
|------|----------|
| `/root/.openclaw/workspace/integrations/google-calendar/token.json` | Google Calendar (Варенька) |
| `/root/.openclaw/workspace/integrations/google-docs/token.json` | Google Docs |
| `/root/.openclaw/workspace/integrations/zoom/token.json` | Zoom Account 1 (Роман) |
| `/root/.openclaw/workspace/integrations/zoom_account2/token.json` | Zoom Account 2 |
| `/root/.openclaw/workspace/integrations/zoom_account3/token.json` | Zoom Account 3 (Kirill) |
| `/root/.openclaw/workspace/integrations/zoom_account4/token.json` | Zoom Account 4 |
| `/root/.openclaw/workspace/integrations/miro/token.json` | Miro OAuth |
| `/root/.openclaw/workspace-dasha-smyslovik/integrations/google-docs/token.json` | Google Docs (Даша) |
| `/root/.openclaw/workspace-kira-pomoschnitsa-km/integrations/google-sheets/token.json` | Google Sheets (Кира) |
| `/root/.openclaw/shared/integrations/google-calendar/token.json` | Google Calendar (shared) |
| `/root/.openclaw/shared/integrations/zoom/token.json` | Zoom (shared) |
| `/root/.openclaw/shared/integrations/zoom_account2/token.json` | Zoom Account 2 (shared) |
| `/root/.openclaw/workspace/integrations/google-vision/credentials.json` | Google Vision API |

---

## 4. Mymeet credentials
| Файл | Описание |
|------|----------|
| `/root/.openclaw/workspace/integrations/mymeet/credentials.json` | Mymeet API |
| `/root/.openclaw/shared/integrations/mymeet/credentials.json` | Mymeet API (shared) |

---

## Правила безопасности

1. **Никогда не хранить** значения ключей в SOUL.md, MEMORY.md, чатах, memory/
2. **GitHub-sync** автоматически удаляет: token.json, credentials.json, .env, secrets.json
3. **Перед добавлением нового ключа** — сначала в secrets.json через `openclaw secrets set`, затем сюда запись
4. **Ротация ключей** — при компрометации немедленно менять + уведомить Вову
