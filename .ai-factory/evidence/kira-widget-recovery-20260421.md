# Evidence — Восстановление виджета «Кира — поддержка»

**Дата:** 2026-04-21
**Плейн:** `.ai-factory/plans/kira-widget-recovery-20260421.md`
**Репортёр:** @Danil_Pavlov_123 (Telegram, 2026-04-21 12:46 UTC)
**Инцидент:** виджет на `client.contenthunter.ru/dashboard` отвечал
`«Не удалось получить ответ. Попробуйте позже.»` для всех клиентов, всех платформ.

## Before-state (2026-04-19 04:50 UTC → 2026-04-21 13:32 UTC)

```
● openclaw-gateway.service - OpenClaw Gateway
   Active: failed (Result: core-dump) since Sun 2026-04-19 04:50:31 UTC; 2 days ago
   Main PID: 1701241 (code=dumped, signal=ABRT)
   NRestarts=11 — упёрся в StartLimitBurst=10, systemd сдался
```

- Порт `127.0.0.1:18789` (ws-агент API) — не слушал.
- Порт `127.0.0.1:18791` (http chat/completions) — не слушал.
- `validator/backend/src/routers/support_chat.py:13` делал POST на `http://127.0.0.1:18789/v1/chat/completions` → `httpx.ConnectError` → FastAPI 500 → фронт `SupportChat.vue:141-148` ловил generic «Не удалось получить ответ».
- `curl POST http://127.0.0.1:18789/...` → `curl: (7) Failed to connect`.
- 2 дня простоя поддержки для всей клиентской базы.

## Root cause (из `/tmp/openclaw/gateway-systemd.log`)

```
FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory
Mark-Compact (reduce) 596.8 (616.7) -> 594.8 (612.4) MB, pooled: 0 MB
```

V8 OOM на **старте** — процесс доезжает до ~596MB heap и SIGABRT.

Причина — **2026-04-16 anti-zombie guards:**
```
MemoryMax=1500M
MemoryHigh=1200M
```

Node 20 на cgroup-ограниченных процессах **авто-детектит MemoryHigh и ставит V8 max-old-space-size ≈ 0.5 × limit ≈ 600MB**. Гейтвей на старте стабильно хочет ~600MB (после апдейтов кода пересёк границу). Heap упирается в свой же авто-потолок → OOM → SIGABRT.

В период с 2026-04-16 (постановка гардов) до 2026-04-19 (фактический падёж) gateway жил на грани. После какого-то PR bundle вылез за 600MB → падение.

Хост: 16GB RAM, `free -h` показывал 12GB available — места было полно, лимит в unit'е был **преждевременной оптимизацией**.

## Fix (2026-04-21 14:04 UTC)

Прямой edit `/etc/systemd/system/openclaw-gateway.service` через `sudo chown claude-user → Edit → sudo chown root:root` (drop-in override не создал — правок мало и хотелось видимости в основном unit-файле для будущих мейнтейнеров):

```diff
 Environment=NODE_ENV=production
+# explicit V8 heap ceiling — без этого node 20 авто-детектит cgroup
+# MemoryHigh и выбирает heap ≈ 0.5 × limit (было ~600MB против
+# стартового footprint 596MB → FATAL OOM в Mark-Compact)
+Environment=NODE_OPTIONS=--max-old-space-size=1536
 WorkingDirectory=/root/.openclaw
@@
-MemoryMax=1500M
-MemoryHigh=1200M
+# 2026-04-21: исходные 1500M/1200M вызывали V8 FATAL OOM на старте
+# (node auto-heap ≈ 0.5 × cgroup = 600MB против 596MB footprint).
+# Gateway был мёртв с 2026-04-19 04:50 UTC. Повысили потолок до
+# 2500M/2000M — всё ещё < 2.9G zombie-порога, plus explicit
+# NODE_OPTIONS выше. См. .ai-factory/plans/kira-widget-recovery-20260421.md.
+MemoryMax=2500M
+MemoryHigh=2000M
```

Backup unit-файла: `/tmp/gateway-unit.backup-1776780259`.

## Commands run (воспроизводимо)

```bash
# 1. Backup + чтение
cp /etc/systemd/system/openclaw-gateway.service /tmp/gateway-unit.backup-$(date +%s)

# 2. Temporarily take ownership для правки
sudo chown claude-user:claude-user /etc/systemd/system/openclaw-gateway.service
#   ... Edit файла ...
sudo chown root:root /etc/systemd/system/openclaw-gateway.service

# 3. Reload + restart
sudo systemctl daemon-reload
sudo systemctl reset-failed openclaw-gateway
sudo systemctl start openclaw-gateway
```

## After-state (2026-04-21 14:04-14:06 UTC)

```
● openclaw-gateway.service - OpenClaw Gateway
   Active: active (running) since Tue 2026-04-21 14:04:41 UTC
   Main PID: 3181256 (node)
   Memory: 757.6M (high: 1.9G max: 2.4G available: 1.2G peak: 760.5M)
   NRestarts=0
   Result=success
```

Listening sockets:
```
LISTEN 0 511 127.0.0.1:18789  (ws — openclaw agent API)
LISTEN 0 511    [::1]:18789
LISTEN 0 511 127.0.0.1:18791  (http — chat/completions + auth)
LISTEN 0 511 127.0.0.1:18792  (???, не трогаем)
```

Smoke tests:
```
# 1. Прямой POST на gateway
$ curl -sS -X POST http://127.0.0.1:18789/v1/chat/completions \
    -H 'Authorization: Bearer 3989...' \
    -d '{"model":"openclaw:kira-pomoschnitsa-km","messages":[...]}'
HTTP 200 · 23.8s
{"id":"chatcmpl_99d7e7cc...","model":"openclaw:kira-pomoschnitsa-km",
 "choices":[{"message":{"role":"assistant","content":"ок"}}]}

# 2. Validator endpoint (без auth — ожидаем 403, подтверждаем что не 500)
$ curl -sS -X POST https://client.contenthunter.ru/api/support/chat \
    -H 'Content-Type: application/json' -d '{"message":"test"}'
HTTP 403 ✓  (auth middleware отработал, нет падения в gateway-ветви)
```

**User-side verification pending:** попросить клиента или самим зайти через Validator UI → виджет внизу справа → задать вопрос Кире → получить живой ответ.

## Follow-ups / open TODO

- **UX:** фронт всё ещё показывает generic текст при 5xx — план T3-T5 это закрывает.
- **Observability:** 2-дневная слепая зона. Zabbix-probe на порт 18789 закроет в T11.
- **Regression risk:** если gateway-bundle продолжит расти — 1536 MB heap тоже может стать тесным. Нужен метрик `peak_memory` в Zabbix для раннего сигнала.
- **Почему gateway не рос на 80% лимита, а сразу упал 2026-04-19?** Версия/депло в тот день. `/root/.openclaw` недоступен мне на чтение (нужен `sudo`-read); если важно — надо `git log` в openclaw-репо посмотреть что за PR ушёл 2026-04-19 утром.

## Связь с knowledge-repo

Этот инцидент заводится как **BUG-008-kira-widget-gateway-down** в `contenthunter_knowledge` (T6-T8 плана). Компонент `openclaw-gateway` — новая страница в `wiki/components/` (T7).
