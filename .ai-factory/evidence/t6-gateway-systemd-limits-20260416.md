# T6: openclaw-gateway zombie mitigation — 2026-04-16 16:58 UTC

## Контекст
Исходная задача: добавить в openclaw-gateway supervisor kill stale PID при lock-timeout. Обнаружено:
- `openclaw-gateway` — **upstream npm package** (`/usr/lib/node_modules/openclaw/dist/gateway-cli-CuZs0RlJ.js`), не наш код.
- Minified bundle, патчить impractical (вендор обновит → overwrite).
- Зато запускается через **наш** systemd-юнит `openclaw-gateway.service` (PID 1 parent).

## Решение: systemd-resource-limits вместо патча supervisor'а

Вместо изменения кода supervisor'а настроены systemd-guards, которые решают ту же проблему более простым способом:

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `MemoryMax=1500M` | 1572864000 bytes | В инциденте 2026-04-16 gateway имел 2.9GB RSS (утечка). 1.5GB = hard cap, systemd убьёт кgroup при превышении. |
| `MemoryHigh=1200M` | 1258291200 bytes | Soft pressure — свопит страницы при 1.2GB, пытается не допустить 1.5GB. |
| `OOMPolicy=kill` | kill cgroup | При OOM убить всю cgroup (а не только leaking child), чтобы Restart=always поднял свежий. |
| `TimeoutStopSec=20s` | 20 сек | SIGTERM→SIGKILL эскалация через 20с (default 90с) — zombie не зависнет. |
| `StartLimitIntervalSec=600` + `StartLimitBurst=10` (в [Unit]) | 10 попыток за 10 мин | Больше restart-budget при flapping (не лочит unit). |

## Что решается этими лимитами
1. **Memory leak 2.9GB** — blocks at 1.5GB (OOM-kill + auto-restart).
2. **SIGTERM-ignored zombie** — systemd эскалирует в SIGKILL через 20с.
3. **lock-timeout после restart race** — TimeoutStopSec+Restart=always гарантирует чистый cycle: SIGKILL old → spawn new.

## Что НЕ решается (остаётся в upstream)
- Сам `gateway already running; lock timeout after 5000ms` — по-прежнему race-баг в supervisor'е (наше SIGKILL помогает, но не лечит причину). Это upstream issue, мы не правим.

## Acceptance
- `systemctl show openclaw-gateway.service` показывает новые limits — ✅
- `systemd-analyze verify openclaw-gateway.service` — clean ✅
- Ждать следующего инцидента чтобы подтвердить поведение (OOM-kill при 1.5GB). Если повторится >1 раза при нормальной нагрузке — MemoryMax подвинуть.

## Откат
`git log /etc/systemd/system/openclaw-gateway.service` — коммит в infra-registr/shared (см. session-summary).
