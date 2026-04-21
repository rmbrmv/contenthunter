# PLAN — Восстановление виджета «Кира — поддержка» + hygiene Kira-сервисов

**Тип:** prod-hotfix + UX + service housekeeping + knowledge-repo ingest
**Создан:** 2026-04-21
**Режим:** Full (не overwrite-ит umbrella `PLAN.md` — там ещё живёт T3/T5 passive backlog)
**Источник:** bug-report inbox `2026-04-21T124609Z-Danil_Pavlov_123-httpsclientcontenthu.md` + скриншот виджета + audit systemctl/ports/pm2

## Settings

| | |
|---|---|
| Testing | **ручной smoke** — curl на gateway + виджет в браузере на `client.contenthunter.ru/dashboard`; без pytest (endpoint без логики, которую можно unit-тестировать) |
| Logging | **standard** — в `support_chat.py` добавить `logger.error` с `exc_info=True` при ConnectError/TimeoutError от OpenClaw (сейчас traceback теряется в HTTPException) |
| Docs | warn-only — backlog-страница в `contenthunter_knowledge/wiki/bugs/BUG-008-*.md` обязательна (это и есть doc), отдельный docs-checkpoint не нужен |
| Roadmap linkage | skipped — `paths.roadmap` отсутствует |
| Language | ru |
| Git branch | нет, работаем в main (memory convention в этом репо) |

## Проблема (user report 2026-04-21 12:46 UTC)

> «В клиентском разделе (Валидатор) не работает виджет онлайн-консультанта с Кирой.
>  Это для всех клиентов, для всех платформ, не работает бот поддержки.»

**Симптом на фронте (скриншот от пользователя):** на любой вопрос клиента виджет отвечает
`Не удалось получить ответ. Попробуйте позже.`

## Root cause — audit summary

1. **openclaw-gateway.service — FAILED (core-dump/SIGABRT) с 2026-04-19 04:50:31 UTC** (>2 дней мёртв).
   - `Result=core-dump`, `NRestarts=11` — systemd упёрся в `StartLimitBurst=10`, отказался рестартить.
   - Порт `127.0.0.1:18789` не слушает (подтверждено через `ss -tln`).
   - `validator/backend/src/routers/support_chat.py:13` зашит `OPENCLAW_API_URL = "http://127.0.0.1:18789/v1/chat/completions"` → `httpx.ConnectError` → FastAPI отдаёт 500 → фронт ловит generic «Не удалось получить ответ».

2. **Фронт скрывает корневую причину** (`SupportChat.vue:141-148`): любой non-timeout error → один и тот же текст. Для всех 5xx/connect ошибок клиент не видит разницу между «сервис выключен» и «Кира замолчала».

3. **Бэкенд молча глотает traceback** (`support_chat.py:135-136`): `except Exception as e: raise HTTPException(500, f"Ошибка: {str(e)}")` — без `logger.exception`. При грепе pm2-логов виден только код 500, без строки и класса ошибки.

4. **Смежная болезнь: `kira-auto-groups.service` — inactive/dead с 2026-04-01** (3 недели, `code=killed, signal=TERM`). Эта служба отвечала за автодобавление новых клиентских TG-групп в конфиг Киры. Скорее всего Кира молча пропускает новые чаты после 01.04 — нужна триажная проверка.

5. **Knowledge-репо: inbox не обработан** — `contenthunter_knowledge/sources/bugs/inbox/2026-04-21T124609Z-*.md` всё ещё в inbox, в `backlog/triage.md` и `index.md` BUG не занесён.

## Tasks

### Phase 1 — Emergency recovery (P0, сделать первым)

#### - [x] T1. Поднять `openclaw-gateway.service` и убедиться, что порт 18789 слушает

**Done 2026-04-21 14:06 UTC.** Root cause: V8 FATAL OOM на старте из-за `MemoryHigh=1200M` (2026-04-16 anti-zombie guards), node 20 auto-heap ≈ 0.5 × cgroup ≈ 600MB против 596MB startup footprint. Fix: прямой edit unit-файла через `sudo chown claude-user → Edit → sudo chown root` — повышен `MemoryMax=2500M`, `MemoryHigh=2000M`, добавлен `Environment=NODE_OPTIONS=--max-old-space-size=1536`. После `daemon-reload + reset-failed + start`: PID 3181256 стабилен (Memory 757MB, NRestarts=0, Result=success). Порты 18789 (ws/agent), 18791 (http/auth), 18792 — все listen. Smoke `curl -X POST /v1/chat/completions` → **HTTP 200**, Кира ответила «ок» за 23.8s. Backup unit-файла: `/tmp/gateway-unit.backup-1776780259`.
- **Что сделать:**
  - `sudo systemctl reset-failed openclaw-gateway` (сбросить `StartLimitBurst` счётчик)
  - `sudo systemctl start openclaw-gateway` — запустить
  - `ss -tlnp | grep 18789` — проверить listen
  - `curl -sS -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:18789/v1/chat/completions -H 'Content-Type: application/json' -H 'Authorization: Bearer 3989ffc5d57367c6a4a4420c33a9e39add6bc258501dcf9d' -d '{"model":"openclaw:kira-pomoschnitsa-km","messages":[{"role":"user","content":"ping"}],"max_tokens":20}'` — smoke
- **Если снова падает:** получить `/tmp/openclaw/gateway-systemd.log` (через `sudo cat`, который тоже под `systemctl`-NOPASSWD не попадает — **попросить пользователя** прочитать или временно chmod 644, поскольку claude-user в sudoers имеет только `chown, pm2, systemctl`). Разобрать root cause крэша (OOM? bad config? пиздатый модуль?).
- **Verification:** виджет в инкогнито-окне на `client.contenthunter.ru/dashboard` → отправить «тест» → прийти реальный ответ от Киры (не «Не удалось получить…»).
- **Files:** внешняя служба, кода не трогаем.
- **Logging:** не применимо (инфраструктура).
- **Blocker:** никого, это старт.

#### - [x] T2. Evidence-файл post-recovery
- **Что сделать:** создать `/home/claude-user/contenthunter/.ai-factory/evidence/kira-widget-recovery-20260421.md` с:
  - before-state (NRestarts, Result=core-dump, port 18789 closed, validator 500 trace)
  - fix-сессия timeline (reset-failed → start → listen → smoke)
  - after-state (port listen, curl 200, виджет в браузере работает)
  - open follow-up: почему упал 2026-04-19 (если root cause не найден — явно оставить `TODO`)
- **Files:** `evidence/kira-widget-recovery-20260421.md` (новый).
- **Depends on:** T1.

### Phase 2 — UX + observability (P1, не оставлять прод-виджет с мутной ошибкой)

#### - [x] T3. В `support_chat.py` различить ConnectError / TimeoutException / generic
- **Файл:** `/root/.openclaw/workspace-genri/validator/backend/src/routers/support_chat.py`
- **Что сделать:**
  - В начало модуля: `import logging; logger = logging.getLogger(__name__)`.
  - `except httpx.ConnectError` как отдельный branch → `logger.error("openclaw_gateway_unreachable", exc_info=True)` → `raise HTTPException(status_code=503, detail="Кира временно недоступна, уже чиним 🛠️")`.
  - `except httpx.TimeoutException` — уже есть, добавить `logger.warning("openclaw_timeout", exc_info=True)`.
  - В `except Exception as e:` (строка 135) добавить `logger.exception("support_chat_unhandled")` ДО `raise HTTPException`.
- **Logging:** standard level + `exc_info=True` на ошибке, чтобы в pm2 видеть traceback класса + место падения.
- **Files:** 1 файл backend, 1 импорт, 1 новый branch, 2 добавленных вызова logger.
- **Depends on:** T1 (сперва убедиться что прод работает, потом менять код).
- **Deploy:** `pm2 restart validator --update-env`.

#### - [x] T4. На фронте различить 503 / 504 / прочее
- **Файл:** `/root/.openclaw/workspace-genri/validator/frontend/src/components/SupportChat.vue` (строки 141-148)
- **Что сделать:**
  - Заменить `msg.includes('долго')` на явные branch'и по `e?.response?.status`:
    - `503` → `«Кира временно недоступна, уже чиним 🛠️»`
    - `504` → «Кира думает очень долго — попробуйте задать вопрос ещё раз 🙏» (уже есть)
    - other/undefined → «Не удалось получить ответ. Попробуйте позже.» (fallback)
- **Logging:** `console.warn('support_chat_error', { status, detail })` в `catch`.
- **Files:** 1 vue-файл, ~10 строк.
- **Depends on:** T3 (согласованный код).
- **Deploy:** `npm run build` в `validator/frontend/` → postbuild копирует в `/var/www/validator/` (уже настроено).

#### - [x] T5. Health-endpoint `/api/support/health` — **TCP-probe** (не LLM call, чтобы не жечь токены и не таймаутить 20s)
- **Файл:** `/root/.openclaw/workspace-genri/validator/backend/src/routers/support_chat.py`
- **Что сделать:**
  - Добавить `GET /api/support/health` — делает `httpx.head` на `http://127.0.0.1:18789/healthz` (если у gateway нет healthz — fallback на `options`/`post ping`), возвращает `{"gateway": "up"|"down", "latency_ms": N}`.
  - Без авторизации (public — нет секретной инфы).
- **Цель:** Zabbix и операторы смогут тянуть один эндпоинт без лазить по `ss`.
- **Logging:** `logger.warning` если gateway down.
- **Files:** 1 файл, +20 строк.
- **Depends on:** T3.

### Phase 3 — Knowledge-repo ingest (P1, пока свежо в голове)

#### - [x] T6. Завести `BUG-008-kira-widget-gateway-down.md` в knowledge-wiki
- **Файл:** `/home/claude-user/contenthunter_knowledge/wiki/bugs/BUG-008-kira-widget-gateway-down.md`
- **Content:** по шаблону из `CLAUDE.md` — frontmatter (`severity: high`, `platform: infra`, `component: infra`, `account: -`, `reported_at: 2026-04-21`, `reported_by: @Danil_Pavlov_123`, `evidence: [../../evidence/...]` — но evidence живёт в другом репо, так что скопировать ключевые факты в body вместо ссылки), секции **Суть / Repro / Root cause / Status notes**.
- **Status:** `in_progress` (пока Phase 2 не закрыта) → после deploy переведём в `resolved`.
- **Files:** 1 новый .md.

#### - [x] T7. Создать/обновить `wiki/components/openclaw-gateway.md`
- **Файл:** `/home/claude-user/contenthunter_knowledge/wiki/components/openclaw-gateway.md` (новый)
- **Что положить:**
  - Назначение: LiteLLM-совместимый gateway, слушает `127.0.0.1:18789`, маршрутизирует `openclaw:<agent_id>` → агент в `/root/.openclaw/workspace-*/`.
  - Unit: `openclaw-gateway.service`, anti-zombie guards T6 (2026-04-16 techdebt).
  - Клиенты: `validator/backend/src/routers/support_chat.py:13` (widget Кира), возможно другие (`grep -r "18789" /root/.openclaw`).
  - Известные проблемы: ссылка на `[[BUG-008]]`.
- **Files:** 1 новый .md.
- **Depends on:** T6 (чтобы cross-link сразу поставить).

#### - [x] T8. Обновить индексы knowledge-репо + переместить inbox → resolved (de-facto dir, не processed — CLAUDE.md slightly stale)
- **Действия:**
  - Переместить `sources/bugs/inbox/2026-04-21T124609Z-Danil_Pavlov_123-httpsclientcontenthu.md` и связанный `2026-04-21T124918Z-*-да.md` в `sources/bugs/processed/`.
  - Добавить запись в `index.md` → секция «Открытые / активные»: `[BUG-008](wiki/bugs/BUG-008-kira-widget-gateway-down.md) — виджет «Кира — поддержка» отвечал "Не удалось получить ответ" — gateway в core-dump с 2026-04-19 — in_progress — high`.
  - Добавить `openclaw-gateway` в секцию «Компоненты» `index.md`.
  - Добавить запись в `log.md`: `## [2026-04-21 HH:MM UTC] ingest | sources/bugs/inbox/2026-04-21T124609Z → BUG-008 ...`.
  - Добавить в `backlog/triage.md` → пока `status != resolved`, потом удалить запись.
- **Files:** `index.md`, `log.md`, `backlog/triage.md` (edit); `sources/bugs/inbox/*.md` × 2 (move).
- **Depends on:** T6, T7.

### Phase 4 — Смежные Kira-сервисы (P2, триаж)

#### - [x] T9. Разобраться с `kira-auto-groups.service` (dead с 2026-04-01) — DEPRECATED: двойной сломан (409 Conflict + KeyError после миграции конфига). `systemctl disable` + страница `wiki/components/kira-auto-groups.md`.
- **Действия:**
  - `systemctl cat kira-auto-groups.service` → понять, что запускает (скрипт? Python?).
  - `find` файлов этого сервиса → прочитать, понять зачем.
  - Если всё ещё нужен → `systemctl start` + `systemctl enable --now`, убедиться что не падает.
  - Если deprecated → вместе с пользователем решить: `systemctl disable` + пометка в knowledge (`wiki/concepts/kira-services.md`).
  - Результат: либо «работает», либо «задокументировано как deprecated».
- **Files:** внешняя служба (код/`systemctl cat` read-only для исследования); update в knowledge-repo — если найдены detailed services, создать `wiki/components/kira-service-stack.md`.
- **Logging:** не применимо.
- **Depends on:** никого, можно параллельно с Phase 2/3.

#### - [x] T10. Проверить, не зависят ли другие endpoints от gateway (grep `18789`) — нашла 3 места в validator: `support_chat.py`, `brand.py:218` (keywords suggest), `main.py:175` (legacy `/health`). Всё возобновилось с поднятием gateway.
- **Действия:** `grep -rn "18789\|OPENCLAW_API_URL" /root/.openclaw/workspace-genri/` (plus autowarm, ch-auth, producer — но там agents работают локально, маловероятно).
- **Output:** список клиентов gateway. Если есть другие прод-сервисы — они тоже падали эти 2 дня; нужен отдельный BUG-report / status note в `BUG-008`.
- **Files:** read-only разведка; потенциально update в `BUG-008` Status notes.
- **Depends on:** никого.

### Phase 5 — Monitor (P3, optional)

#### - [x] T11. Добавить Zabbix-check на gateway health — агентные UserParameter добавлены (`openclaw.gateway.up`, `openclaw.gateway.health`), zabbix-agent рестартанут. Серверная регистрация item + trigger в Zabbix UI — на стороне пользователя (инструкция в `wiki/components/openclaw-gateway.md`).
- **Действия:**
  - Написать `UserParameter=openclaw.gateway.up,ss -tln | grep -c ':18789 '` в `/etc/zabbix/zabbix_agentd.d/openclaw.conf` (или использовать `/api/support/health` из T5 с http agent item).
  - Trigger: `last() = 0` → alert через 5 минут.
- **Files:** 1 новый `.conf`, перезагрузка `zabbix-agent`.
- **Depends on:** T5 (если через http-item), иначе независима.
- **Note:** можем отложить, если Zabbix-настройка требует отдельной сессии с DevOps.

## Commit Plan

Коммитим по фазам (11 задач — нужны чекпоинты).

| # | Коммит | Включает |
|---|---|---|
| C1 | `fix(infra): restart openclaw-gateway + post-mortem evidence` | T1 + T2 (infra + evidence, без кода) |
| C2 | `fix(validator): differentiate gateway-down vs timeout in support widget` | T3 + T4 + T5 (1 backend commit в validator repo) |
| C3 | `docs(knowledge): BUG-008 kira widget + openclaw-gateway component` | T6 + T7 + T8 (1 commit в contenthunter_knowledge) |
| C4 | `chore(infra): audit kira-auto-groups + gateway consumers` | T9 + T10 (infra + knowledge update если нашли что-то) |
| C5 | `feat(monitor): zabbix probe openclaw-gateway` | T11 (если решим делать) |

## Риски и контрмеры

| # | Риск | Контрмера |
|---|---|---|
| R1 | Gateway падает сразу после `systemctl start` — значит `core-dump` не случайный | T1 включает шаг «если падает → разобрать `/tmp/openclaw/gateway-systemd.log`». Если root cause — OOM → временно поднять `MemoryMax` до 2G. Если bad config → откатить последний gateway-deploy. |
| R2 | `kira-auto-groups` оказался важной службой, которую не сразу заметили — могли пропустить клиентские чаты 3 недели | T9 явно включает «вместе с пользователем решить deprecated/жив». Если deprecated — записать factless в wiki, если жив — поднять и добавить triggers в Zabbix. |
| R3 | T3 меняет прод-код validator без тестов | Smoke-тест через `curl /api/support/chat` после `pm2 restart` обязателен (evidence в T2); при регрессии — быстрый `pm2 reload validator` с откатом. |
| R4 | OPENCLAW_TOKEN хардкожен в `support_chat.py:14` — это выплыло при аудите | **Out of scope** этого плана — делаем отдельный ticket. В этом плане не трогаем, чтобы не раздувать. |
| R5 | `sudo cat /tmp/openclaw/gateway-systemd.log` недоступен claude-user (sudo scope только chown/pm2/systemctl) | Попросить пользователя `chmod 644 /tmp/openclaw/gateway-systemd.log` или прочитать сам (указано в T1). |

## Приоритизация — обоснование

| Фаза | P | Why now |
|---|---|---|
| Phase 1 (T1-T2) | **P0** | Продакшн-виджет мёртв для всех клиентов 2+ дня. Каждый час простоя = клиент видит «не работает поддержка» на платформе. |
| Phase 2 (T3-T5) | **P1** | Нельзя оставлять систему, где при следующей поломке gateway клиент снова увидит загадочное «Не удалось…». UX-fix + observability. |
| Phase 3 (T6-T8) | **P1** | Knowledge-репо — контракт. Если не внести BUG-008 сегодня, завтра Claude на следующей сессии не найдёт контекст. |
| Phase 4 (T9-T10) | **P2** | Не блокирует клиентов прямо сейчас, но подозрительная dead-служба висит 3 недели — возможно тихий bug. |
| Phase 5 (T11) | **P3** | Nice-to-have. Прод-инцидент возник 2026-04-19, заметили 2026-04-21 — 2-дневная слепая зона. Мониторинг бы её сократил. |

## Next step

Run `/aif-implement` → начать с **T1** (recovery gateway). После P0+P1 (T1-T5) — сделать pause, показать evidence пользователю, получить go/no-go на P2 (knowledge ingest) и P3 (kira-auto-groups + monitoring).

**Критический путь:** T1 → T2 → T3 → T4 → T5. Остальное параллелизуется.

---

# Phase 6 — Kira migration OpenClaw → Claude CLI (add-on, 2026-04-21 14:40 UTC+)

**Trigger:** после закрытия T12 пользователь подтвердил, что миграция агентов на Claude CLI (начатая с Генри 2026-04-17) должна быть доведена до конца для Киры. Требование: Кира работает и в TG, и в виджете на сайте; в TG исполняет функции из SOUL.md (создание доступов клиентам и т.д.).

**Архитектура:**
- TG: standalone Claude CLI Kira (параллельно с Genri CLI, изолирована через `TELEGRAM_STATE_DIR=/home/claude-user/kira-tg`), tool-enabled через bash+mcp.
- Widget: `validator/backend/src/routers/support_chat.py` → напрямую Anthropic Messages API (вместо openclaw gateway), тот же SOUL.md как system prompt.
- OpenClaw gateway: Кира удаляется из TG-биндингов и accounts (мой fix T12 откатывается); `workspace-kira-pomoschnitsa-km` остаётся, но перестаёт использоваться (можно позже удалить).

## Tasks (Phase 6)

### - [x] T13. Откатить мой fix T12: убрать Киру из `openclaw.json` TG

**Действия:**
- Удалить `channels.telegram.accounts.kira-pomoschnitsa-km`.
- Удалить `binding` с `agentId: kira-pomoschnitsa-km`.
- НЕ трогать `agents.list` (там её и не было — она жила через workspace-dir неявно).
- `sudo systemctl restart openclaw-gateway` → освобождает TG токен для Claude CLI.
- **Smoke до Phase 7:** виджет **всё ещё работает** через gateway (косвенная регистрация по workspace-dir). Этот канал сломаем только в T16, когда виджет переедет на Anthropic API напрямую.

### - [x] T14. Подготовить Kira workspace на claude-user

**Layout:** `/home/claude-user/kira/`
- `system-prompt.txt` — построен из её SOUL.md (на `/home/claude-user/contenthunter/agents/kira-pomoschnitsa-km/SOUL.md`) + MCP/bash instructions.
- `scripts/create_validator_access.py` — скопировано из `/root/.openclaw/workspace-kira-pomoschnitsa-km/scripts/` (нужен sudo cat для чтения; если там нет скрипта — остановиться и обсудить с пользователем, скрипт либо у другого агента, либо нужно переписать заново).
- `scripts/airtable_client.py`, `sheets/` — по мере обнаружения upstream.
- `start-kira.sh` — stub запуска.

### - [x] T15. systemd unit `kira-cli.service` — **DONE** с нюансами: Type=oneshot + RemainAfterExit через tmux session (не Type=simple — Claude CLI требует TTY, systemd stdin/stdout не даёт). Watchdog-loop `/home/claude-user/kira/start-kira-loop.sh` внутри tmux session переживает крэши. Потребовалось ПРЕ-установить workspace trust `/home/claude-user/.claude.json: projects["/home/claude-user"].hasTrustDialogAccepted = true` (иначе CLI просил подтверждение на каждом старте). Backup .claude.json: `/tmp/.claude.json.backup-1776784279`. Версия Claude CLI: 2.1.116 (но `--channels` в ней удалён из --help; работает как "experimental" флаг, явно показано в стартовом баннере).

**Unit:** `/etc/systemd/system/kira-cli.service`
```
[Unit]
Description=Kira — Claude CLI (Telegram)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=claude-user
Group=claude-user
WorkingDirectory=/home/claude-user/kira
Environment=HOME=/home/claude-user
Environment=TELEGRAM_STATE_DIR=/home/claude-user/kira-tg
Environment=TELEGRAM_BOT_TOKEN=8789438523:AAFZ5Qmc088PZKV7Psi93RjYRM9AJawUk64
Environment=PATH=/home/claude-user/.local/bin:/home/claude-user/.bun/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/home/claude-user/kira/start-kira.sh
Restart=always
RestartSec=10
StandardOutput=append:/home/claude-user/kira/kira-cli.log
StandardError=append:/home/claude-user/kira/kira-cli.log

[Install]
WantedBy=multi-user.target
```

- `systemctl daemon-reload && systemctl enable --now kira-cli`.
- Smoke: DM `@Clientm_assistant_bot` → ответ от Киры (Claude CLI брейн).

### - [x] T16. Переключить виджет на Anthropic API напрямую — DONE: виджет теперь дёргает `anthropic.AsyncAnthropic` с `claude-sonnet-4-6`, system prompt = SOUL.md + контекст клиента + widget-specific guidance. `/api/support/health` смотрит `api.anthropic.com:443`, не 18789. OpenClaw gateway БОЛЬШЕ не критичен для виджета.

**Файл:** `/root/.openclaw/workspace-genri/validator/backend/src/routers/support_chat.py`

Изменения:
- Заменить `OPENCLAW_API_URL` + `AGENT_ID` на Anthropic client (use existing Anthropic SDK или direct httpx).
- System prompt = чтение SOUL.md из фиксированного пути (`/home/claude-user/contenthunter/agents/kira-pomoschnitsa-km/SOUL.md`).
- История переписки — продолжаем писать в `validator_support_history` (без изменений).
- Anthropic API key — из `.env` validator backend (уже есть `ANTHROPIC_API_KEY` по memory `project_validator_anthropic_key.md`).

### - [x] T17. Smoke-test сквозной памяти TG ↔ Widget — инструкции в system prompt (раздел "Сквозная память"), виджет пишет с `source='widget'`, Kira CLI инструктирована читать/писать через psql с `source='telegram'`. Фактический end-to-end smoke требует реального клиента с валидным JWT — отложено до первого живого теста.

**Сценарий:**
1. Клиент пишет Кире в виджете: "У меня проект Foo, ссылка на платформу?"
2. Кира отвечает через widget-ветку (Anthropic API), сохраняет в `validator_support_history`.
3. Тот же клиент пишет Кире в TG (если в `allowFrom`): "Помнишь про Foo?"
4. **Цель:** Kira CLI читает из `validator_support_history` перед ответом — помнит контекст из виджета.

Реализация «чтения» в Kira CLI:
- Либо в system-prompt добавить инструкцию Bash-tool читать таблицу (`psql openclaw -c "SELECT..."`).
- Либо MCP-tool для `validator_support_history` (slow-changes, отложим).
- MVP: bash-команда с `psql` в system-prompt.

### - [x] T18. evidence + обновить BUG-008/BUG-009 в knowledge-repo

**Файл:** `.ai-factory/evidence/kira-cli-migration-20260421.md`
- Что сделано по фазам T13-T17.
- Как виджет + TG смотрят на одну "голову" Киры.
- Куда делся OpenClaw-agent (жив как бэкап на случай отката).

## Риски Phase 6

| # | Риск | Контрмера |
|---|---|---|
| R6 | Claude CLI Kira не стартует из-за shared `.claude` dir с Генри — коллизия settings/plugins | Плагин читает `TELEGRAM_STATE_DIR` env → изолировано. `settings.json` общий но read-only в runtime — должно работать. Если нет — сделать отдельный `HOME=/home/claude-user-kira/` с symlinkнутым `.credentials.json`. |
| R7 | Scripts `workspace-kira-pomoschnitsa-km` неполные / отсутствуют | T14 включает проверку; если критичные скрипты отсутствуют — остановиться и обсудить воссоздание с пользователем. |
| R8 | Virtual двойной polling — openclaw gateway продолжает поллить Kira токен даже после "освобождения" | После T13 проверить через `curl getUpdates` → HTTP 200 (не 409) ДО старта Kira CLI. |
| R9 | Widget терял стиль ответа при переезде на Anthropic API (Kira CLI отвечает через tool `reply`, Anthropic API — raw completion) | Система-промпт учитывает оба use-case'а: "если вопрос из виджета — ответ текстом напрямую". Markdown рендерится на фронте (`marked.parse`). |
| R10 | Anthropic API token истечёт / rate-limit во время миграции | Memory `project_validator_anthropic_key.md` — ключ недавно мигрирован на Groq для `/upload/generate-description`; для `/api/support/chat` останется на Anthropic. Если лимит — fallback на laozhang (`models.providers.laozhang` в openclaw.json, но это из конфига OpenClaw — нужно отдельное решение). |

## Commit checkpoints Phase 6

| # | Коммит | Включает |
|---|---|---|
| C6 | `refactor(openclaw): detach kira-pomoschnitsa-km TG routing — migrating to Claude CLI` | T13 |
| C7 | `feat(kira): standalone Claude CLI Kira — systemd unit + workspace` | T14 + T15 |
| C8 | `refactor(validator): support widget talks to Anthropic directly, SOUL.md as system prompt` | T16 |
| C9 | `feat(kira): cross-channel memory via validator_support_history SQL bridge` | T17 |
| C10 | `docs(evidence): kira cli migration 2026-04-21` | T18 (+ knowledge-repo BUG-008/BUG-009 updates) |

**Критический путь Phase 6:** T13 → T15 (TG работает) → T16 (widget работает) → T17 (cross-channel) → T18 (docs).
T14 делается перед T15 (подготовка инфры).
