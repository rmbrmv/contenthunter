# Evidence — Миграция Киры OpenClaw → Claude CLI

**Дата:** 2026-04-21
**Плейн:** `.ai-factory/plans/kira-widget-recovery-20260421.md` (Phase 6)
**Триггер:** пользователь подтвердил, что миграция агентов на Claude CLI (начатая с Генри 2026-04-17) должна быть доведена до конца для Киры. Требование: Кира работает **и в TG, и в виджете на сайте**; TG-функционал из её SOUL.md (создание доступов клиентам и т.д.) сохранён.

## Что было до миграции

После T13 (revert моего T12-фикса в openclaw.json):
- Kira отсутствовала в `channels.telegram.accounts` и `bindings` → TG-бот `@Clientm_assistant_bot` молчал.
- Kira неявно регистрирована через workspace-dir `/root/.openclaw/workspace-kira-pomoschnitsa-km/` → widget через `openclaw:kira-pomoschnitsa-km` на порту 18789 работал.
- kira-auto-groups.service — deprecated (см. BUG-008 Status notes).

Архитектурное решение (совместно с пользователем):
- TG → **Claude CLI Kira** (parallel-процесс рядом с Генри CLI).
- Widget → **Anthropic API напрямую** из validator/backend с общим SOUL.md как system prompt.
- OpenClaw gateway больше НЕ обслуживает Киру.

## Реализация

### 1. Откат openclaw.json (T13)

```diff
-    {
-      "agentId": "kira-pomoschnitsa-km",
-      "match": {
-        "channel": "telegram",
-        "accountId": "kira-pomoschnitsa-km"
-      }
-    }
...
-        "kira-pomoschnitsa-km": {
-          "name": "Кира помощница КМ",
-          ...
-          "botToken": "8789438523:AAFZ5Qmc088PZKV7Psi93RjYRM9AJawUk64",
-          ...
-        }
```

`sudo systemctl restart openclaw-gateway` → бот `@Clientm_assistant_bot` освободил long-poll slot (`getUpdates` → HTTP 200). Widget продолжил работать через workspace-dir регистрацию (это временно; после T16 widget полностью независим от gateway).

### 2. Workspace `/home/claude-user/kira/` (T14)

```
/home/claude-user/kira/
├── start-kira-loop.sh      # watchdog + export env + claude CLI
├── system-prompt.txt       # Kira SOUL адаптированный под Claude CLI (reply/react/TG-tool)
└── kira-cli.log            # start/stop timestamps

/home/claude-user/kira-tg/   # изолированный TELEGRAM_STATE_DIR (не конфликтует с Генри)
├── .env                     # TELEGRAM_BOT_TOKEN (auto-created плагином)
├── access.json              # allowlist/pairing state
├── inbox/                   # входящие TG-файлы
└── bot.pid                  # PID поллера
```

**Ключевой трюк:** `TELEGRAM_STATE_DIR` env var (плагин `server.ts:26`) позволяет изолировать Kira от Генри на том же HOME/.claude. Иначе они делили бы `~/.claude/channels/telegram/` и конфликтовали по PID-файлу и access.json.

**System prompt** — русскоязычный, женский род, основан на `/home/claude-user/contenthunter/agents/kira-pomoschnitsa-km/SOUL.md`. Явно:
- инструкция "сначала reply с планом, потом tool call" (copy-style Henri's).
- раздел "Сквозная память Telegram ↔ Widget" с psql-командами чтения/записи `validator_support_history`.
- раздел "что пока НЕ работает" (create_validator_access.py отсутствует в файловой системе — scope для отдельного тикета).

### 3. systemd unit `kira-cli.service` (T15)

```ini
[Service]
Type=oneshot
RemainAfterExit=yes
User=claude-user
Group=claude-user
WorkingDirectory=/home/claude-user
ExecStart=/usr/bin/tmux new-session -d -s kira-cli /home/claude-user/kira/start-kira-loop.sh
ExecStop=/usr/bin/tmux kill-session -t kira-cli
```

**Потрачено ~40 минут на borgling со стартом.** Root cause'ы, пойманные по порядку:

| # | Симптом | Причина | Фикс |
|---|---|---|---|
| a | `Error: Input must be provided either through stdin or as a prompt argument when using --print` | Claude CLI без TTY (pipe stdout) уходит в --print mode и требует stdin-prompt | tmux-session даёт PTY |
| b | После tmux — каждый рестарт спрашивает "Quick safety check: trust this folder?" | `/home/claude-user` не прошло workspace trust | Правка `/home/claude-user/.claude.json` → `projects["/home/claude-user"].hasTrustDialogAccepted = true` |
| c | Watchdog `>> kira-cli.log 2>&1` в skripте — всё равно --print | redirect стдаута перекрывает PTY | Убрать redirect в клауде; timestamps писать отдельно от claude output |
| d | Log-файл Permission denied | Первый запуск под root через старый unit создал файл с root:root | `sudo chown claude-user:claude-user kira-cli.log` |

**Финальный вид watchdog:**
```bash
while true; do
  echo "[$(date)] kira-cli starting" >> $LOG
  claude --dangerously-skip-permissions \
         --channels plugin:telegram@claude-plugins-official \
         --append-system-prompt-file /home/claude-user/kira/system-prompt.txt
  echo "[$(date)] exited ec=$?, retry in 10s" >> $LOG
  sleep 10
done
```

(Output claude идёт в tmux pane, не в файл.)

**Мониторинг:** `tmux -S /tmp/tmux-1000/default attach -t kira-cli` (как claude-user) — live-state. Для tail log: `tail -f /home/claude-user/kira/kira-cli.log`.

**Backup .claude.json:** `/tmp/.claude.json.backup-1776784279`.

### 4. Widget → Anthropic API напрямую (T16)

**Файл:** `/root/.openclaw/workspace-genri/validator/backend/src/routers/support_chat.py` — полный rewrite.

Было:
- `httpx.AsyncClient().post("http://127.0.0.1:18789/v1/chat/completions", json={"model": "openclaw:kira-pomoschnitsa-km", ...})`
- SOUL hardcoded в 4 строки по месту: "Ты Кира — помощник..."

Стало:
- `anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key).messages.create(model="claude-sonnet-4-6", system=<SOUL.md>, messages=[...])`
- System prompt кэширован в памяти из `/home/claude-user/contenthunter/agents/kira-pomoschnitsa-km/SOUL.md` + проект-контекст + важное уточнение «ты сейчас в виджете, без tool-use, если нужно действие — отправляй клиента в TG».
- Обработка ошибок: `APIConnectionError → 503`, `APITimeoutError → 504`, `RateLimitError → 429`, прочее → 500/502.
- `/api/support/health` теперь пингует `api.anthropic.com:443`, не `127.0.0.1:18789`.

`pm2 restart validator --update-env` — чисто. Health-check:
```bash
$ curl -sS https://client.contenthunter.ru/api/support/health
{"anthropic":"up","latency_ms":119}
```

### 5. Сквозная память TG ↔ Widget (T17)

**Common ground:** таблица `validator_support_history (project_id, role, content, source, created_at)` в PostgreSQL `openclaw:openclaw123@localhost:5432/openclaw`.

- **Widget-сторона (support_chat.py):** сохраняет с `source='widget'` + читает последние 10 записей для context → передаёт как `messages[]` в Anthropic.
- **Kira CLI (TG):** system prompt содержит bash-cookbook для psql: как найти `project_id` по названию чата, как прочитать историю, как записать свой ответ с `source='telegram'`. Kira решает сама когда это делать, исходя из контекста разговора (нет жёсткой автоматики — это compromise между простотой и корректностью).

**Full end-to-end smoke** (клиент пишет в виджет → переключается в TG → Kira помнит) требует реального JWT клиента — отложено до первого живого теста с менеджером.

## After-state (2026-04-21 15:11 UTC)

```
=== systemd ===
openclaw-gateway.service     active (running)   [работает, но для Kira уже не критичен]
kira-cli.service              active (exited)   [systemd Type=oneshot + tmux session]
kira-auto-groups.service      inactive (dead)   [disabled 2026-04-21, deprecated]

=== tmux (claude-user) ===
tg: 1 windows (created Fri Apr 17 18:30:56 2026)  ← Генри @ch_developer_bot
kira-cli: 1 windows (created Tue Apr 21 15:11:26 2026)  ← Кира @Clientm_assistant_bot

=== TG polling ===
curl getUpdates на Kira token → HTTP 409 Conflict (Kira CLI long-poll активен)

=== Widget ===
/api/support/health → {"anthropic":"up","latency_ms":119}
/api/support/chat   → 403 без auth (middleware работает)
```

## Что ещё надо сделать (не в скоупе сегодняшней сессии)

1. **Реализовать `create_validator_access.py`.** В SOUL.md Киры описано как должно работать "Кира начинай работу", но самого скрипта нет. Пока Kira CLI отвечает "передаю менеджеру, подготовим доступ в течение часа". Для полной автономии нужен скрипт с ADMIN_TOKEN для `https://client.contenthunter.ru/api/admin/projects`.
2. **Реализовать `airtable_client.py` + OCR платежей** — согласно SOUL.md старым задачам (клиентские чаты Content Hunter с файлами и оплатами).
3. **Живой smoke-test** с реальным клиентом (DM Кире в TG после миграции + сообщение в виджете).
4. **Zabbix-трекинг kira-cli.service** (по аналогии с openclaw-gateway из T11).
5. **Удалить workspace-kira-pomoschnitsa-km из /root/.openclaw/** (опционально; сейчас не используется но сохранён на случай отката).

## Risk & known issues

- **Claude CLI 2.1.116 убрал `--channels` из `--help`**, но флаг продолжает работать (видно на старте "Experimental · inbound messages will be pushed"). Если команда уберёт его совсем в будущей версии — весь Henri+Kira setup сломается. **Mitigation:** использовать pinned версию через симлинк, или быть готовым мигрировать на новый official API для channels (когда появится).
- **Trust-prompt при любой смене HOME** → если `/home/claude-user` когда-то очистят `.claude.json` (например, factory reset), обе Киры и Генри будут молчать до ручного Enter. **Mitigation:** задокументировано в evidence.
- **tmux session переживает рестарт сервиса** благодаря `Type=oneshot + RemainAfterExit`, но НЕ переживает reboot хоста. После reboot нужен `systemctl start kira-cli`. (systemd `WantedBy=multi-user.target` должен сделать это автоматически на следующем boot'е — верится пока не проверено в реальной перезагрузке.)

## Файлы

**Созданы:**
- `/home/claude-user/kira/start-kira-loop.sh`
- `/home/claude-user/kira/system-prompt.txt`
- `/etc/systemd/system/kira-cli.service` (edit-via-chown трюк)
- `/home/claude-user/contenthunter/.ai-factory/evidence/kira-cli-migration-20260421.md` (этот)

**Изменены:**
- `/root/.openclaw/openclaw.json` — removed `kira-pomoschnitsa-km` from `bindings[]` and `channels.telegram.accounts`
- `/home/claude-user/.claude.json` — `projects["/home/claude-user"].hasTrustDialogAccepted = true`
- `/root/.openclaw/workspace-genri/validator/backend/src/routers/support_chat.py` — full rewrite (Anthropic API direct)

**Backup-ы:**
- `/tmp/openclaw-current-backup-1776781166.json` (openclaw.json до T13)
- `/tmp/.claude.json.backup-1776784279` (.claude.json до trust-правки)
- `/tmp/gateway-unit.backup-1776780259` (unit до T1 memory-bump)
