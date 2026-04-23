# Evidence — testbench не создавал задачи 11 часов (root cause + fix)

**Дата:** 2026-04-23
**Тип:** fix + diagnostic
**Связанные скрипты:** `/usr/local/bin/testbench-start.sh`, `/usr/local/bin/testbench-stop.sh`
**Инцидент:** пользователь спросил, почему на тестовом стенде нет запущенных задач.

## Наблюдения при входе

- `systemctl status autowarm-testbench-orchestrator.service` → `inactive (dead) since 2026-04-22 18:56:54 UTC` (11ч без работы).
- Последняя созданная задача — `#772 YouTube/Инакент-т2щ`, 2026-04-22 18:54:40.
- `system_flags.testbench_paused = false, updated_by=testbench-start, updated_at=2026-04-23 05:35:16` — SQL-флаг показывает, что кто-то пытался стартовать.
- Между 18:56:54 и 06:15 (мой ручной `systemctl start`) journal orchestrator'а **пуст** — сервис никогда не поднимался после стопа.

## Таймлайн

| Время (UTC) | Событие |
|---|---|
| 2026-04-22 18:56:39 | `sudo pm2 stop autowarm-testbench` (claude-user в прошлой сессии) |
| 2026-04-22 18:56:53 | `sudo systemctl stop autowarm-testbench-orchestrator` |
| 2026-04-22 18:56:54 | orchestrator SIGTERM → `inactive` |
| 2026-04-23 05:35:16 | smoke-тест UI start/stop кнопки: `testbench-start.sh` вызван, flag в БД переключился на `false`, **но** orchestrator НЕ стартанул (баг скрипта, см. Root cause) |
| 2026-04-23 06:00–06:10 | диагностика (этой сессии): grep-условие в скрипте кажется корректным, ручной `sudo systemctl start autowarm-testbench-orchestrator.service` → `active` |
| 2026-04-23 06:11:41 | orchestrator создал `task #796 [TikTok/gennadiya4]` — 24/7-цикл восстановлен |

## Root cause

Классический баг `set -o pipefail` + `grep -q`:

```bash
# Было в testbench-start.sh и testbench-stop.sh:
if systemctl list-unit-files 2>/dev/null | grep -q '^autowarm-testbench-orchestrator\.service'; then
  sudo systemctl start autowarm-testbench-orchestrator
fi
```

`grep -q` завершает чтение после первого совпадения и закрывает pipe. `systemctl list-unit-files` получает `SIGPIPE` и падает с ненулевым exit code. Под `set -o pipefail` это помечает весь pipeline как failed → условие `if` получает false → ветка `then` пропускается → скрипт пишет `⏭ unit не установлен` и молча идёт дальше.

Репродукция (минимальная):

```bash
$ bash -c 'systemctl list-unit-files 2>/dev/null | grep -q "^autowarm-testbench-orchestrator\.service" && echo MATCH || echo NOMATCH'
MATCH
$ bash -c 'set -euo pipefail; systemctl list-unit-files 2>/dev/null | grep -q "^autowarm-testbench-orchestrator\.service" && echo MATCH || echo NOMATCH'
NOMATCH
```

Тот же паттерн ломал stop-скрипт симметрично (orchestrator «останавливался», но реально к нему не прикасались — SIGTERM прилетел 22 апреля напрямую через `systemctl stop`).

**Почему это никогда не стрельнуло раньше:** шаг `[4/4] SQL flag` в start-скрипте (INSERT INTO system_flags) работает в любом случае. Т.к. в ручной prod-установке 22 апреля сервис был остановлен ТОЛЬКО через `systemctl stop`, флаг и состояние совпали. Только повторный `testbench-start` через UI обнажил проблему: флаг снялся, но сервис не поднялся.

## Фикс

Заменил два места в обоих скриптах:

1. `systemctl list-unit-files | grep -q '^unit\.service'` → `systemctl cat unit.service >/dev/null 2>&1`
   → не использует pipe, не уязвим к pipefail.
2. `sudo pm2 list | grep -q 'autowarm-testbench'` → читаем `pm2 list` в переменную и проверяем `[[ $var == *name* ]]`
   → тоже без pipe.

Плюс добавлено:

- `exec > >(tee -a $LOG_FILE) 2>&1` → всё stdout/stderr дублируется в `/var/log/testbench-{start,stop}.log` (fallback `/tmp/` если /var/log not-writable).
- `step_systemctl_start` / `step_systemctl_stop` проверяют `is-active` после действия и возвращают non-zero, если сервис не перешёл в ожидаемое состояние.
- Убраны `|| true` с критичных шагов (pm2 start, systemctl start orchestrator).
- Финальный assert в конце start: `systemctl is-active autowarm-testbench-orchestrator.service == active` — иначе `exit 1`.
- Header-строка с timestamp, `${SUDO_USER:-$USER}`, `pid`, путём лога — чтобы будущий дебаг был проще.

## Smoke

Dry-cycle `testbench-stop --force` → `testbench-start` на живом стенде (вторая итерация, после фикса):

```
[2026-04-23T06:18:18+00:00] ═══ testbench-stop invoked by claude-user pid=535199 force=1 log=/tmp/testbench-stop.log ═══
[stop] step=flag sql_ok=1
[stop] step=orchestrator unit=autowarm-testbench-orchestrator exit_code=0 is_active=inactive
[stop] step=dispatcher skipped=unit-not-installed      ← корректно, unit реально не установлен
[stop] step=pm2 exit_code=0
[stop] done

[2026-04-23T06:18:19+00:00] ═══ testbench-start invoked by claude-user pid=535280 log=/tmp/testbench-start.log ═══
[start] step=pm2 exit_code=0
[start] step=dispatcher skipped=unit-not-installed      ← корректно
[start] step=orchestrator unit=autowarm-testbench-orchestrator exit_code=0 is_active=active
[start] step=flag sql_ok=1
[start] done assert=active                              ← финальный assert проходит
```

| Проверка | Результат |
|---|---|
| `bash -n testbench-start.sh` | ✅ SYNTAX_OK |
| `bash -n testbench-stop.sh` | ✅ SYNTAX_OK |
| `stop → is-active` | ✅ `inactive` (реально остановился, раньше был false-skipped) |
| `start → is-active` | ✅ `active` (реально запустился) |
| Новая задача после восстановления | ✅ `#796 TikTok/gennadiya4 @ 2026-04-23 06:11:41` |
| Owner скриптов | ✅ `root:root` (restored) |

## Файлы

- `/usr/local/bin/testbench-start.sh` — переписан (см. фикс выше).
- `/usr/local/bin/testbench-stop.sh` — переписан симметрично.
- `/tmp/testbench-start.sh.bak-1776924913` — бэкап оригинала.
- `/tmp/testbench-stop.sh.bak-1776924913` — бэкап оригинала.

## Что НЕ сделано (отложено по причине смены PLAN.md)

- **T4 оригинального плана — структурированный ответ эндпоинта `/api/publish/testbench/{start,stop}`** (`{ok, exitCode, tail}` + alert с tail'ом в UI при ошибке). Сейчас, когда скрипты надёжно падают с non-zero и пишут trace в `/var/log/testbench-{start,stop}.log`, UI-кнопка при неуспехе получит 500 от `execFile`, но без tail'а. Приемлемо до отдельного тикета — если повторится подобный silent-skip, его видно в логе скрипта. Задним числом это дополнительный UX-полиш, не fix.

## Почему PLAN.md не отражает эту работу

Во время выполнения `/aif-implement` параллельная Claude-сессия перезаписала `.ai-factory/PLAN.md` на другой fix (Revision UI + `PLATFORM_TO_COLUMN`). Этот evidence-файл — авторитетный источник для текущего фикса.

Вывод для памяти:
- Параллельные сессии действительно гоняют plan'ы друг у друга (уже зафиксировано в `feedback_parallel_claude_sessions.md`).
- Когда scope мал и уже выполнен — atomic commit через evidence-файл спасает.
