# WP #133 — Зависшие процессы `node server.js` на VPS: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **NB:** Это ops-задача с зависимостью от оператора (Данил размещает root-файлы и снимает грант). Шаги помечены **[ОПЕРАТОР]** (выполняет человек в root-сессии) и **[АГЕНТ]** (выполняю я). Из-за human-in-the-loop рекомендуется **inline-исполнение в этой сессии**, а не диспатч субагентов.

**Goal:** Безопасно опознать и погасить 6 осиротевших root-процессов `node server.js` (с марта) на `fra-1-vm-y49r`, подтвердив до гашения отсутствие записи в боевую БД, и зафиксировать профилактику.

**Architecture:** Least-privilege (вариант A): вся привилегированная логика — в двух root-owned скриптах (`wp133-diag.sh` forensics, `wp133-kill.sh` с ревалидацией PID); sudoers разрешает запускать только их и без аргументов; грант временный. Спека: `docs/superpowers/specs/2026-05-27-wp133-stale-node-processes-design.md`.

**Tech Stack:** bash, `/proc`, `ss`, `pg_stat_activity` (psql), sudo (NOPASSWD drop-in), OpenProject API v3, PM2 (только если выявится системная причина).

**Цели (PID, зафиксированы 2026-05-27):** `40742 44622 1292259 3999492 3999503 3999515` (все ppid=1, root, `node server.js`, март 10–12). НЕ трогать: autowarm PID 1760612 и ch-auth 2221066 (ppid=58511, pm2-managed).

---

### Task 1: Бутстрап привилегированных артефактов (оператор, однократно)

**Files (создаёт оператор как root на сервере):**
- Create: `/usr/local/sbin/wp133-diag.sh` (root:root, 0755)
- Create: `/usr/local/sbin/wp133-kill.sh` (root:root, 0755)
- Create: `/etc/sudoers.d/claude-user-wp133` (root:root, 0440)

- [ ] **Step 1 [ОПЕРАТОР]: Создать оба скрипта одним блоком (root-сессия).**

> Вставить целиком. Heredoc-разделители **в кавычках** (`'WP133DIAG'`) — содержимое пишется буквально, без подстановки `$pid`.

```bash
cat > /usr/local/sbin/wp133-diag.sh <<'WP133DIAG'
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
  echo "  tcp sockets incl. LISTEN (ss -tan):"
  ss -tanp 2>/dev/null | grep -w "pid=$pid" | sed 's/^/    /' || echo "    (none)"
done
WP133DIAG

cat > /usr/local/sbin/wp133-kill.sh <<'WP133KILL'
#!/usr/bin/env bash
# WP #133 — kill the 6 stale orphaned `node server.js`. Re-validates each PID (PID-reuse guard). No args.
set -uo pipefail
PIDS=(40742 44622 1292259 3999492 3999503 3999515)
declare -A EXPECT_START=( [40742]="Mar 12" [44622]="Mar 12" [1292259]="Mar 10" \
  [3999492]="Mar 11" [3999503]="Mar 11" [3999515]="Mar 11" )
VALIDATED=()
for pid in "${PIDS[@]}"; do
  if [ ! -d "/proc/$pid" ]; then echo "PID $pid: already gone, skip"; continue; fi
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline"); ppid=$(awk '/^PPid:/{print $2}' "/proc/$pid/status")
  start=$(ps -o lstart= -p "$pid")
  echo "$cmd" | grep -q 'node .*server\.js' || { echo "PID $pid: cmd mismatch ('$cmd') — REFUSE"; continue; }
  [ "$ppid" = "1" ] || { echo "PID $pid: ppid=$ppid (not orphaned) — REFUSE"; continue; }
  echo "$start" | grep -q "${EXPECT_START[$pid]}" || { echo "PID $pid: start '$start' != '${EXPECT_START[$pid]}' — REFUSE (reuse?)"; continue; }
  echo "PID $pid: validated → SIGTERM"; kill -TERM "$pid"; VALIDATED+=("$pid")
done
if [ ${#VALIDATED[@]} -gt 0 ]; then
  echo "waiting 5s..."; sleep 5
  for pid in "${VALIDATED[@]}"; do
    [ -d "/proc/$pid" ] && { echo "PID $pid: survived TERM → SIGKILL"; kill -KILL "$pid" 2>/dev/null || true; }
  done
fi
echo "remaining orphan node server.js:"; pgrep -af 'node .*server\.js' | grep -v workspace-genri || echo "  (none)"
WP133KILL

chmod 0755 /usr/local/sbin/wp133-diag.sh /usr/local/sbin/wp133-kill.sh
chown root:root /usr/local/sbin/wp133-diag.sh /usr/local/sbin/wp133-kill.sh
```

- [ ] **Step 2 [ОПЕРАТОР]: Проверить синтаксис скриптов (без запуска).**

Run:
```bash
bash -n /usr/local/sbin/wp133-diag.sh && bash -n /usr/local/sbin/wp133-kill.sh && echo "syntax OK"
```
Expected: `syntax OK`

- [ ] **Step 3 [ОПЕРАТОР]: Создать sudoers-грант и провалидировать.**

```bash
cat > /etc/sudoers.d/claude-user-wp133 <<'WP133SUDO'
claude-user ALL = (root) NOPASSWD: /usr/local/sbin/wp133-diag.sh "", /usr/local/sbin/wp133-kill.sh ""
WP133SUDO
chmod 0440 /etc/sudoers.d/claude-user-wp133
visudo -cf /etc/sudoers.d/claude-user-wp133
```
Expected: `/etc/sudoers.d/claude-user-wp133: parsed OK`

- [ ] **Step 4 [АГЕНТ]: Подтвердить, что грант виден claude-user.**

Run: `sudo -ln | grep wp133`
Expected: две строки с `wp133-diag.sh ""` и `wp133-kill.sh ""`. Если пусто → грант не применился, вернуться к оператору.

- [ ] **Step 5 [АГЕНТ]: Зафиксировать факт бутстрапа в evidence-черновике (без commit пока).**

Завести `docs/evidence/2026-05-27-wp133-stale-node-cleanup.md`, секция «Бутстрап» (что размещено, вывод `visudo -cf` и `sudo -ln`).

---

### Task 2: Forensics 6 PID

**Files:**
- Append: `docs/evidence/2026-05-27-wp133-stale-node-cleanup.md`

- [ ] **Step 1 [АГЕНТ]: Запустить forensics, сохранить вывод.**

Run:
```bash
sudo -n /usr/local/sbin/wp133-diag.sh | tee /tmp/wp133-diag.out
```
Expected: 6 блоков `===== PID <n> =====`, в каждом заполнены `cwd`, `exe`, `env`, `fd`, `tcp sockets`.

- [ ] **Step 2 [АГЕНТ]: Записать полный вывод forensics в evidence.**

Вставить содержимое `/tmp/wp133-diag.out` в секцию «Forensics» evidence-файла. Не коммитить пока (commit на Task 7).

---

### Task 3: Анализ + гейт безопасности (GO / NO-GO)

**Files:**
- Append: `docs/evidence/2026-05-27-wp133-stale-node-cleanup.md`

- [ ] **Step 1 [АГЕНТ]: Проверить каждый PID по критериям гейта.**

Для каждого из 6 PID подтвердить ВСЕ пункты:
1. `cmdline` = `node server.js`, `ppid` = 1 (всё ещё осиротевший).
2. В блоке `tcp sockets incl. LISTEN` — **нет** строк `LISTEN` и **нет** ESTAB к `:5432`/`:5433`.
3. В `fd (sockets/notable)` — нет открытых сокетов к БД; открытые `.js`/каталоги указывают на старый/удалённый/нерабочий путь, не на текущий прод.
4. `env` не содержит указателей на боевую БД (`DATABASE_URL`/`PG*`/`OPENCLAW*` с прод-хостом).

- [ ] **Step 2 [АГЕНТ]: Кросс-проверка по БД (вторая линия).**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -p 5432 -d openclaw -tAc \
"SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND backend_start < '2026-05-01';"
```
Expected: `0` (нет client-backend старше мая → нет постоянного писателя из марта). Записать в evidence.

- [ ] **Step 3 [АГЕНТ]: Вынести вердикт гейта.**

Записать в evidence явный вердикт:
- **GO** — все 6 прошли все критерии (нет LISTEN/ESTAB к БД, env/cwd/exe = утёкший ручной запуск). Переход к Task 4.
- **NO-GO** — хотя бы один держит активный сокет / признаки боевой нагрузки. **Остановиться, эскалировать Данилу** с конкретикой по PID. Task 4 НЕ выполнять.

---

### Task 4: Гашение (только при вердикте GO)

**Files:**
- Append: `docs/evidence/2026-05-27-wp133-stale-node-cleanup.md`

- [ ] **Step 1 [АГЕНТ]: Снять baseline памяти/процессов до kill.**

Run:
```bash
ps -o pid,rss,etimes,cmd -p 40742,44622,1292259,3999492,3999503,3999515; free -m | awk 'NR<=2'
```
Записать в evidence (для сравнения «до/после»).

- [ ] **Step 2 [АГЕНТ]: Выполнить гашение.**

Run:
```bash
sudo -n /usr/local/sbin/wp133-kill.sh | tee /tmp/wp133-kill.out
```
Expected: по каждому PID `validated → SIGTERM`; в конце `remaining orphan node server.js: (none)`. Любая строка `REFUSE` → разобрать причину (reuse-guard сработал), не форсить.

- [ ] **Step 3 [АГЕНТ]: Верифицировать результат.**

Run:
```bash
ps -p 40742,44622,1292259,3999492,3999503,3999515 -o pid= 2>/dev/null && echo "STILL ALIVE" || echo "all 6 gone"
ps -o pid,ppid,cmd -p 1760612,2221066    # легитимные autowarm+ch-auth должны быть живы
free -m | awk 'NR<=2'
```
Expected: `all 6 gone`; PID 1760612 и 2221066 живы с ppid=58511; свободной RAM примерно на ~155 МБ больше.

- [ ] **Step 4 [АГЕНТ]: Записать вывод kill + «после» в evidence.**

---

### Task 5: Решение по профилактике

**Files:**
- Create (вероятный исход): memory `.../memory/feedback_no_manual_server_js_outside_pm2.md` + строка в `MEMORY.md`
- Append: `docs/evidence/2026-05-27-wp133-stale-node-cleanup.md`

- [ ] **Step 1 [АГЕНТ]: Классифицировать причину по forensics (Task 2).**

- **Разовый инцидент** (cwd всех 6 = удалённые/старые worktree, кластер март 10–12, рецидивов за 70 дней нет): → Step 2 (только фиксация практики). Watchdog НЕ делаем (YAGNI).
- **Системная причина** (cwd/родительская цепочка указывает на крон/скрипт, продолжающий плодить orphan'ы): → НЕ строить watchdog спекулятивно; завести **дочерний WP** «PM2-детектор осиротевших node server.js (alert-only)» с конкретной первопричиной и согласовать с Данилом отдельно.

- [ ] **Step 2 [АГЕНТ]: Зафиксировать практику (исход «разовый»).**

Создать memory-файл `feedback`: «`server.js` (autowarm/ch-auth) запускать только через pm2; ручной запуск из worktree → осиротевший процесс при выходе оболочки». В теле — линк `[[feedback_stale_node_test_processes]]` и `[[project_wp133...]]`. Добавить строку-указатель в `MEMORY.md`.

---

### Task 6: Снятие временного гранта (оператор)

- [ ] **Step 1 [АГЕНТ]: Сообщить оператору, что привилегированные шаги завершены.**

- [ ] **Step 2 [ОПЕРАТОР]: Удалить грант (и при желании скрипты).**

```bash
rm -f /etc/sudoers.d/claude-user-wp133
visudo -c
# опционально: rm -f /usr/local/sbin/wp133-diag.sh /usr/local/sbin/wp133-kill.sh
```
Expected: `visudo -c` → все файлы `parsed OK`.

- [ ] **Step 3 [АГЕНТ]: Подтвердить, что грант снят.**

Run: `sudo -ln | grep wp133 || echo "grant removed"`
Expected: `grant removed`. Записать в evidence.

---

### Task 7: Evidence, OpenProject, память, завершение ветки

**Files:**
- Finalize: `docs/evidence/2026-05-27-wp133-stale-node-cleanup.md`
- Update: `.../memory/MEMORY.md` (+ project-memory для #133)

- [ ] **Step 1 [АГЕНТ]: Финализировать evidence-файл.**

Структура: Бутстрап → Forensics → Гейт (GO/NO-GO + кросс-проверка БД) → Kill (до/после) → Профилактика → Снятие гранта. С итогом: сколько погашено, RAM освобождена, причина, решение.

- [ ] **Step 2 [АГЕНТ]: Закоммитить doc-артефакты в ветке worktree.**

```bash
git add docs/evidence/2026-05-27-wp133-stale-node-cleanup.md
git commit -m "docs(wp133): evidence — forensics + гашение 6 осиротевших node server.js"
```

- [ ] **Step 3 [АГЕНТ]: Комментарий в #133 (house style [[feedback_openproject_practice]]: Что было не так → Что сделано → Что осталось, без футера).**

```bash
source ~/secrets/openproject.env
curl -s -u apikey:$OPENPROJECT_API_TOKEN -H 'Content-Type: application/json' \
  -X POST "https://openproject.contenthunter.ru/api/v3/work_packages/133/activities" \
  -d '{"comment":{"raw":"<markdown итог>"}}'
```

- [ ] **Step 4 [АГЕНТ]: Перевести #133 в статус (по факту: «Тестирование» id 9 или «Готово» id 12).**

Сначала GET свежий `lockVersion`, затем PATCH `_links.status.href`. (См. [[reference_openproject_access]].)

- [ ] **Step 5 [АГЕНТ]: Обновить память.**

Создать/обновить project-memory `project_wp133_stale_node_procs.md` (итог + решение) и строку в `MEMORY.md`.

- [ ] **Step 6 [АГЕНТ]: Завершить ветку.**

Использовать `superpowers:finishing-a-development-branch` — мердж doc-изменений в main или PR, по согласованию с Данилом.

---

## Self-Review

**Spec coverage:**
- Бутстрап least-priv (2 скрипта + sudoers, вариант A) → Task 1. ✓
- Forensics (cwd/exe/env/fd/sockets) → Task 2. ✓
- Гейт безопасности до kill (нет LISTEN/ESTAB к БД, env) + кросс-проверка pg_stat_activity → Task 3. ✓
- Kill с ревалидацией + проверка «до/после», легитимные сервисы целы → Task 4. ✓
- Профилактика (дерево: разовый → практика; системный → дочерний WP) → Task 5. ✓
- Снятие временного гранта → Task 6. ✓
- Evidence + #133 (house style) + статус + память → Task 7. ✓

**Placeholder scan:** Скрипты приведены дословно; команды конкретны. `<markdown итог>` в Task 7/Step 3 — содержимое сочиняется по фактическим результатам (по дизайну), не плейсхолдер-логики.

**Type/идентификаторы consistency:** Имена скриптов (`wp133-diag.sh`/`wp133-kill.sh`), список PID и `EXPECT_START` совпадают во всех тасках и в спеке. ✓
