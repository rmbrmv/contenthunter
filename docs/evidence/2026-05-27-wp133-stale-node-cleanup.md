# WP #133 — Evidence: «зависшие node server.js» оказались systemd-сервисами

**Дата:** 2026-05-27 · **Ветка:** `worktree-wp133-stale-node-procs` · **Спека/план:** `docs/superpowers/specs/2026-05-27-wp133-stale-node-processes-design.md`, `docs/superpowers/plans/2026-05-27-wp133-stale-node-processes.md`

## Итог (TL;DR)
6 процессов `node server.js` с `ppid=1` (с марта) — **НЕ мусор и не утечка**, а **активные systemd-сервисы** Content Hunter. Премиса WP («осиротевшие, к БД не подключены, погасить») ошибочна: `ppid=1` у systemd-сервиса — норма (родитель = systemd, PID 1). По решению Данила все 6 **выведены из эксплуатации** (`systemctl disable --now`). Действие обратимо.

## Бутстрап (least-priv, вариант A)
Оператор разместил root-owned `/usr/local/sbin/wp133-diag.sh` + `wp133-kill.sh` и sudoers `/etc/sudoers.d/claude-user-wp133` (только эти 2 скрипта, без аргументов). Грант подтверждён `sudo -ln`; базовый sudo (chown/pm2/systemctl) цел.

## Forensics (`wp133-diag.sh`, read-only)
| PID(старый) | cwd | слушал | env-ключи | cgroup → unit |
|---|---|---|---|---|
| 40742 | hr-payroll | `127.0.0.1:3852` | PGHOST/PORT/DB/USER/PASSWORD | `hr-payroll.service` |
| 44622 | producer-copilot | — | NODE_ENV | `producer-copilot.service` |
| 1292259 | farm-platform | — (исходящие FIN-WAIT-2 → 193.124.112.222:49002) | — | `farm-platform.service` |
| 3999492 | workspace/projects/openclaw-dashboard | `127.0.0.1:3000` | — | `openclaw-dashboard.service` |
| 3999503 | carousel-maker | `127.0.0.1:3851` | NODE_ENV | `carousel-maker.service` |
| 3999515 | task-tracker | `*:3849` | NODE_ENV | `task-tracker.service` |

**По боевой БД:** ни один не держал соединения к `:5432` (в fd — только слушающие сокеты + stdout/stderr); `pg_stat_activity` — нет client-backend старше 19.05. Прецедент теневого autowarm не подтвердился.

**Решающее доказательство природы:** `cat /proc/<pid>/cgroup` → `/system.slice/<имя>.service`; `systemctl list-units` показал все 6 как `loaded active running`. Юниты в `/etc/systemd/system/*.service`, у всех `ExecStart=/usr/bin/node server.js`, `WorkingDirectory=<проект>`, `Restart=always`, User=root.

## Зонд-kill (раскрыл природу)
`wp133-kill.sh` (с ревалидацией) отбил все 6 по SIGTERM. Через ~секунды systemd по `Restart=always` поднял их заново (мы увидели «респаун» 2672154…2672184, счётчик вернулся к 6). Это и показало, что процессы — supervised systemd-сервисы. **Вреда/нетто-изменений от зонда нет** — сервисы авто-восстановились.

## Действие: вывод из эксплуатации (по решению Данила)
Состояние ДО: все active; enabled у всех, КРОМЕ `carousel-maker` (был active, но `disabled`).
Выполнено `sudo systemctl disable --now <svc>` для всех 6. Штатный `stop` ⇒ `Restart=` не срабатывает ⇒ держатся внизу.

Состояние ПОСЛЕ (проверено): все 6 `enabled=disabled`, `active=inactive`; bare `node server.js` = 0; порты 3000/3849/3851/3852 свободны; autowarm(1760612)+ch-auth(2221066) не тронуты. Повторная проверка спустя время — остаются inactive (респауна нет).

## Профилактика
Не требуется: «накопление» было артефактом неверной трактовки — это были намеренно настроенные сервисы, а «респаун» = штатный `Restart=`. После `disable` причина устранена. Watchdog не нужен.

## Откат (если выяснится, что сервис нужен)
```bash
sudo systemctl enable --now hr-payroll producer-copilot farm-platform openclaw-dashboard task-tracker
sudo systemctl start carousel-maker     # был active, но disabled — только start, без enable
```
Юнит-файлы в `/etc/systemd/system/` НЕ удалялись — откат полный и тривиальный.

## Снятие временного гранта (оператор) — ✅ ВЫПОЛНЕНО 27.05
```bash
rm -f /etc/sudoers.d/claude-user-wp133 && visudo -c
rm -f /usr/local/sbin/wp133-diag.sh /usr/local/sbin/wp133-kill.sh
```
Проверено: `sudo -ln` больше не показывает wp133-гранта; скрипты удалены; базовый sudo (chown/pm2/systemctl) цел. Все 6 сервисов остаются `disabled`/`inactive` (фоллаут-рестартов нет).

## Урок
`ppid=1` ≠ «осиротевший мусор»: для systemd-сервиса это нормальная родительская связь. Перед гашением «осиротевших» процессов проверять `cat /proc/<pid>/cgroup` / `systemctl list-units` — это снимает вопрос за один шаг и не требует sudo.
