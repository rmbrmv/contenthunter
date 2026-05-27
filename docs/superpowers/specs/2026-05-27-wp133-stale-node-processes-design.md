# WP #133 — Зависшие процессы `node server.js` на VPS (с марта)

**Дата:** 2026-05-27
**Тип:** инфра/ops (не правка прод-кода)
**Статус:** дизайн на ревью
**OpenProject:** #133, assignee Данил, статус «В разработке»
**Ветка:** `worktree-wp133-stale-node-procs`

## Проблема

На `fra-1-vm-y49r` висят **6 процессов** `node server.js` без родителя (ppid=1), под root,
не управляются pm2. Похожи на мусор от ручных запусков. Нужно: опознать (cwd/exe/origin),
убедиться, что безопасны, аккуратно погасить и решить вопрос профилактики повторного накопления.

**Главное опасение** — прецедент [[feedback_stale_node_test_processes]] (22.05): утёкшие node
из удалённого worktree подняли **теневой autowarm**, ~20 ч диспатчивший боевую `publish_queue`
старым кодом. Значит «к боевой БД не подключены» — гипотеза, требующая проверки, а не факт.

## Что уже установлено (read-only разведка, 2026-05-27)

| PID | Запущен | cmd | CPU | RSS |
|---|---|---|---|---|
| 1292259 | 10 марта | `/usr/bin/node server.js` | 0.0% | 31 МБ |
| 3999492 | 11 марта | `/usr/bin/node server.js` | 0.0% | 34 МБ |
| 3999503 | 11 марта | `/usr/bin/node server.js` | 0.0% | 9 МБ |
| 3999515 | 11 марта | `/usr/bin/node server.js` | 0.0% | 36 МБ |
| 40742 | 12 марта | `/usr/bin/node server.js` | 0.0% | 36 МБ |
| 44622 | 12 марта | `/usr/bin/node server.js` | 0.0% | 12 МБ |

- Все 6 — **bare `server.js`** (относительный путь), `STAT Ssl` (спящие session-leader'ы), ~155 МБ RSS суммарно, 0% CPU. Не срочно.
- Легитимные pm2-процессы (autowarm PID 1760612, ch-auth 2221066) имеют ppid=58511 — **не цель**.
- **Гейт безопасности (БД):** в `pg_stat_activity` боевой `openclaw` нет ни одного client-backend старше **19 мая**. Постоянного пула из марта нет → 6 процессов **не держат постоянного соединения с боевой БД**. Риск прецедента в основном снят; финальное подтверждение — на Фазе 1 (проверка fd/сокетов конкретных PID).
- **Поправка к брифу:** `cmdline` у root-процессов читается; недоступны без root только `cwd`/`exe`/`fd`/`environ`.

## Блокер прав и выбранный подход

`claude-user` имеет NOPASSWD sudo только на `chown`/`pm2`/`systemctl` (см. [[feedback_server_access]]).
`readlink`/`cat`/`ls` по `/proc/<root-pid>` и `kill` — недоступны.

**Выбран вариант A (least-privilege через 2 скрипта).** Вместо широких грантов (`sudo cat`=чтение любых
секретов, `sudo kill`=любой процесс) вся привилегированная логика инкапсулируется в два root-owned
скрипта с жёстко зашитым списком 6 PID; sudoers разрешает запускать **только их и без аргументов**.
Грант **временный** — снимается по завершении задачи.

## Архитектура

Три артефакта, размещаемые оператором (Данилом) под root однократно; далее агент работает автономно.

### 1. `/usr/local/sbin/wp133-diag.sh` (root:root, 0755)

Read-only forensics по 6 PID. Печатает для каждого: cmdline, ppid, время старта, `cwd`, `exe`,
релевантные env-переменные (`PWD`, `NODE_*`, `PM2*`, `OPENCLAW*`, `DATABASE*`, `PG*` — чтобы увидеть,
был ли процесс сконфигурирован на боевую БД), открытые fd-сокеты и TCP-сокеты по `ss`.

```bash
#!/usr/bin/env bash
# WP #133 forensics for stale orphaned `node server.js`. Read-only. Hardcoded PIDs, no args.
set -uo pipefail
PIDS=(40742 44622 1292259 3999492 3999503 3999515)
for pid in "${PIDS[@]}"; do
  echo "===== PID $pid ====="
  if [ ! -d "/proc/$pid" ]; then echo "  (gone — no /proc/$pid)"; continue; fi
  echo "  cmdline : $(tr '\0' ' ' < "/proc/$pid/cmdline")"
  echo "  ppid    : $(awk '/^PPid:/{print $2}' "/proc/$pid/status")"
  echo "  started : $(ps -o lstart= -p "$pid")"
  echo "  cwd     : $(readlink "/proc/$pid/cwd")"
  echo "  exe     : $(readlink "/proc/$pid/exe")"
  echo "  env     :"; tr '\0' '\n' < "/proc/$pid/environ" \
      | grep -E '^(PWD|NODE_|PM2|OPENCLAW|DATABASE|PG)' | sed 's/^/    /' || echo "    (none matched)"
  echo "  fd (sockets/notable):"
  ls -l "/proc/$pid/fd" 2>/dev/null | grep -E 'socket|\.js|/root|/home' | sed 's/^/    /' || echo "    (none notable)"
  echo "  tcp sockets (ss):"
  ss -tnp 2>/dev/null | grep -w "pid=$pid" | sed 's/^/    /' || echo "    (none)"
done
```

### 2. `/usr/local/sbin/wp133-kill.sh` (root:root, 0755)

Гасит 6 PID, но **перед каждым kill заново валидирует** процесс (cmd=`node server.js`, ppid=1,
совпадение даты старта) — защита от переиспользования PID за 70 дней аптайма. `TERM`, пауза, `KILL`
для выживших. Список PID и ожидаемые даты зашиты.

```bash
#!/usr/bin/env bash
# WP #133 — kill the 6 stale orphaned `node server.js`. Re-validates each PID (PID-reuse guard). No args.
set -uo pipefail
PIDS=(40742 44622 1292259 3999492 3999503 3999515)
declare -A EXPECT_START=( [40742]="Mar 12" [44622]="Mar 12" [1292259]="Mar 10" \
  [3999492]="Mar 11" [3999503]="Mar 11" [3999515]="Mar 11" )
for pid in "${PIDS[@]}"; do
  if [ ! -d "/proc/$pid" ]; then echo "PID $pid: already gone, skip"; continue; fi
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline"); ppid=$(awk '/^PPid:/{print $2}' "/proc/$pid/status")
  start=$(ps -o lstart= -p "$pid")
  echo "$cmd" | grep -q 'node .*server\.js' || { echo "PID $pid: cmd mismatch ('$cmd') — REFUSE"; continue; }
  [ "$ppid" = "1" ] || { echo "PID $pid: ppid=$ppid (not orphaned) — REFUSE"; continue; }
  echo "$start" | grep -q "${EXPECT_START[$pid]}" || { echo "PID $pid: start '$start' != '${EXPECT_START[$pid]}' — REFUSE (reuse?)"; continue; }
  echo "PID $pid: validated → SIGTERM"; kill -TERM "$pid"
done
echo "waiting 5s..."; sleep 5
for pid in "${PIDS[@]}"; do
  [ -d "/proc/$pid" ] && { echo "PID $pid: survived TERM → SIGKILL"; kill -KILL "$pid" 2>/dev/null || true; }
done
echo "remaining orphan node server.js:"; pgrep -af 'node .*server\.js' | grep -v workspace-genri || echo "  (none)"
```

### 3. `/etc/sudoers.d/claude-user-wp133` (0440)

```
claude-user ALL = (root) NOPASSWD: /usr/local/sbin/wp133-diag.sh "", /usr/local/sbin/wp133-kill.sh ""
```

`""` запрещает любые аргументы. Валидация: `visudo -cf /etc/sudoers.d/claude-user-wp133`.

## Поток выполнения

### Фаза 1 — Диагностика
1. **Оператор (root, однократно):** создаёт 2 скрипта (контент выше, дословно), `chmod 755`,
   `chown root:root`; создаёт sudoers-файл, `chmod 440`, проверяет `visudo -cf`.
2. **Агент:** `sudo -n /usr/local/sbin/wp133-diag.sh` → анализ вывода.
3. **Критерий безопасности (gate):** kill разрешён только если для **всех** 6 PID forensics показывает:
   нет слушающего TCP-сокета на прод-портах, нет ESTABLISHED-соединения к :5432, env не указывает
   на боевую БД, exe/cwd соответствуют утёкшему ручному запуску (старый/удалённый каталог).
   Любое отклонение (активный сокет, признак боевой нагрузки) → **стоп, эскалация Данилу**, kill не делаем.

### Фаза 2 — Действие + профилактика
4. **Kill** (если gate пройден): `sudo -n /usr/local/sbin/wp133-kill.sh` → проверяю, что 6 PID исчезли,
   ~155 МБ освобождены, легитимный autowarm/ch-auth не затронуты.
5. **Профилактика (дерево решений по данным Фазы 1):**
   - **Разовый инцидент** (все из марта 10–12, источник — удалённые/старые worktree, рецидивов за 70 дней нет):
     профилактика = **запись практики** «`server.js` запускать только через pm2, не вручную из worktree»
     (memory-заметка `feedback`, линк на [[feedback_stale_node_test_processes]]). Watchdog **не делаем** (YAGNI).
   - **Системная причина** (forensics вскрыл крон/скрипт, регулярно плодящий orphan'ы): лёгкий
     **PM2-детектор с алертом в TG** (бот daily-report @gengo_tech_notify_1_bot, см. [[project_daily_publish_report]]),
     ищущий `node server.js` с ppid=1 вне pm2 старше порога (дефолт ~6 ч). **Без авто-kill** (авто-убийство root-процессов
     рискует погасить легитимную ручную отладку).
   - Текущие данные (всё за 3 дня в марте, 70 дней чисто) сильно склоняют к первому исходу.
6. **Снятие гранта:** оператор удаляет `/etc/sudoers.d/claude-user-wp133` (и при желании 2 скрипта) —
   временный доступ закрывается.

## Критерии готовности
- Forensics-вывод по 6 PID получен и зафиксирован в evidence (`docs/evidence/`) + комментарий в #133.
- Происхождение процессов опознано (ответ на «кто/зачем запускал»).
- Подтверждено отсутствие записи в боевую БД (gate Фазы 1) **до** гашения.
- 6 PID погашены (или принято обоснованное решение отложить), RAM освобождена, легитимные сервисы целы.
- Решение по профилактике принято и зафиксировано.
- Временный sudo-грант снят.
- #133 → «Тестирование»/«Готово» с evidence (house style [[feedback_openproject_practice]]).

## Риски и нерешённое
- **PID reuse** за 70 дней аптайма — закрыто ревалидацией в `wp133-kill.sh` (cmd+ppid+дата старта).
- **Транзиентная активность БД** (connect→write→disconnect) теоретически не видна по `backend_start`;
  снимается проверкой fd/сокетов в Фазе 1 + аргументом «70 дней без видимого двойного постинга».
- **Скрипты пишет оператор как root** — агент не может разместить root-owned файлы (нет `sudo cp`/`mv`,
  только `chown`). Контент даётся дословно для копипаста.
- **Второй postgres на :5433** — проверкой сокетов в Фазе 1 убеждаемся, что ни один PID к нему не подключён.
