# WP #122 — Активация share-loop overlay handler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Безопасно активировать уже задеплоенный (OFF) хендлер окна «Добавить в историю» в TT share-loop: смок на стенде → включить рубильник в проде → отмониторить → закрыть WP.

**Architecture:** Нового кода нет. Хендлер `_run_tt_stories_overlay_share_loop_hook` в проде (`publisher_tiktok.py:1533`, вызов `:1958`), читается рубильник `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED` (`os.environ.get(...,'false')`, default OFF). `publisher.py:33 load_dotenv('.env')` на каждый спавн → флаг подхватывается новыми воркерами. Прод и testbench пишут в одну БД `openclaw`; разделение фолтов — по `device_serial` и колонке `testbench`.

**Tech Stack:** Python (publisher.py), Node (server.js, PM2 id 35), PostgreSQL `openclaw:openclaw123@localhost:5432/openclaw`, ADB, PM2.

**Spec:** `docs/superpowers/specs/2026-05-27-wp122-tt-share-loop-activation-design.md`

**Подтверждённые константы (разведка 27.05):**
- Прод autowarm: `/root/.openclaw/workspace-genri/autowarm` (owned `claude-user` → правка без sudo), PM2 app `autowarm` (id 35).
- Testbench: `/home/claude-user/autowarm-testbench`, ветка `main` HEAD `2d994db` (БЕЗ WP#122), PM2 app `autowarm-farming-testbench`.
- #19 → serial `RF8YA0W57EP` (raspberry 7); #171 → serial `RF8Y90GCWWL` (raspberry 1). Оба active, TT-capable.
- События: `publish_tasks.events` (JSONB-массив), элемент `{type, message, meta:{category, step, phase, ...}}`.

---

## Task 1: Обновить testbench до кода WP#122 + восстановить флот

**Files:**
- Modify (checkout): `/home/claude-user/autowarm-testbench` (git pull, без правки кода)

- [ ] **Step 1: Снимок текущего состояния (защита от потери локальных правок)**

Run:
```bash
cd /home/claude-user/autowarm-testbench
git branch --show-current; git log --oneline -1; git status --porcelain
readlink node_modules || echo "(node_modules не symlink / отсутствует)"
```
Expected: branch `main`, HEAD `2d994db ...`. **Запомнить вывод `readlink node_modules`** как `<NM_TARGET>` (понадобится в Step 4, если pull сломает symlink). Если `git status --porcelain` непуст — НЕ продолжать вслепую: разобрать локальные изменения (`git stash list`, `git diff`), при необходимости `git stash push -m wp122-preupdate`. `.env` в gitignore и pull его не трогает.

- [ ] **Step 2: Fast-forward pull до актуального main (вносит merge `2972cce`/WP#122)**

Run:
```bash
cd /home/claude-user/autowarm-testbench
git fetch origin main
git pull --ff-only origin main
git log --oneline -3
```
Expected: pull проходит без конфликтов; в `git log` появляется `2972cce` (Merge PR#106) и более новые. Если `--ff-only` отказал (расхождение) — STOP, разобрать (локальные коммиты на testbench main).

- [ ] **Step 3: Проверка паритета кода (хендлер реально подтянулся)**

Run:
```bash
cd /home/claude-user/autowarm-testbench
grep -c "TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED" publisher_tiktok.py
grep -n "_run_tt_stories_overlay_share_loop_hook" publisher_tiktok.py | head -2
python3 -c "import ast; ast.parse(open('publisher_tiktok.py').read()); print('parse OK')"
```
Expected: счётчик ≥ 1; определение метода на ~`:1533` + вызов; `parse OK`.

- [ ] **Step 4: Починить node_modules symlink + рестарт планировщика (известная гоча)**

> node_modules нужен только node-демону (server.js/scheduler), НЕ python-смоку. Чиним, чтобы не оставить testbench-флот сломанным.

Run:
```bash
cd /home/claude-user/autowarm-testbench
ls -ld node_modules; test -e node_modules && echo "node_modules OK" || echo "BROKEN"
# если BROKEN и в Step 1 был <NM_TARGET> — восстановить тем же таргетом:
#   ln -sfn <NM_TARGET> node_modules
sudo pm2 restart autowarm-farming-testbench --update-env
sudo pm2 status autowarm-farming-testbench
```
Expected: `node_modules OK` (symlink резолвится); pm2 `autowarm-farming-testbench` → `online`. Если `BROKEN` — пересоздать symlink захваченным `<NM_TARGET>` (`ln -sfn <NM_TARGET> node_modules`), затем рестарт.

---

## Task 2: Включить рубильник в `.env` стенда

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/.env`

- [ ] **Step 1: Проверить, что флага ещё нет, и добавить его**

Run:
```bash
cd /home/claude-user/autowarm-testbench
grep -n "TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED" .env || echo "NOT SET — добавляю"
printf '\nTT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true\n' >> .env
tail -3 .env
```
Expected: до — «NOT SET»; после — последняя строка `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true`.

- [ ] **Step 2: Подтвердить, что python-процесс прочитает флаг из этого .env**

Run:
```bash
cd /home/claude-user/autowarm-testbench
python3 -c "from dotenv import load_dotenv; import os; load_dotenv('.env'); print('flag=', os.environ.get('TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED'))"
```
Expected: `flag= true`.

---

## Task 3: Управляемый TT-смок на #19 (gate: happy-path не сломан)

**Files:** только БД + запуск `publisher.py`. Целевое устройство #19 (`RF8YA0W57EP`); запасное #171 (`RF8Y90GCWWL`).

- [ ] **Step 1: Устройство онлайн + есть TT-аккаунт/медиа для клонирования**

Run:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -x -c "
SELECT id, device_serial, adb_port, adb_host, raspberry, account, project,
       media_path, media_type, status, created_at
FROM publish_tasks
WHERE testbench=true AND platform='TikTok' AND device_serial='RF8YA0W57EP'
  AND status IN ('done','awaiting_url')
ORDER BY id DESC LIMIT 1;"
```
Expected: одна строка — донор для клона (реальные `media_path`, `account`, `adb_port`, `adb_host`). Если пусто — взять `status` любой (последняя TT-задача) ради валидных `account/adb_port`, а `media_path` взять из последней `done` TT-задачи любого устройства, **проверив существование файла** (`ls -l <media_path>`). Если и так пусто — переключиться на #171 (`RF8Y90GCWWL`).

- [ ] **Step 2: Проверить, что seed-медиа реально на диске (иначе preflight_failed)**

Run:
```bash
ls -l <media_path_из_шага_1>
```
Expected: файл существует, размер > 0. (Память: выдуманный путь → `preflight_failed` до switcher'а.)

- [ ] **Step 3: Создать свежую pending смок-задачу (клон донора), вернуть id**

Run (подставить значения донора из Step 1):
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -c "
INSERT INTO publish_tasks
  (device_serial, adb_port, adb_host, raspberry, platform, account, project,
   media_path, media_type, caption, status, testbench, created_at, updated_at)
SELECT device_serial, adb_port, adb_host, raspberry, platform, account, 'smoke-wp122',
       media_path, media_type, 'wp122 share-loop smoke', 'pending', true, NOW(), NOW()
FROM publish_tasks
WHERE id = <DONOR_ID>
RETURNING id;"
```
Expected: `RETURNING id` → запомнить как `<SMOKE_ID>`.

- [ ] **Step 4: Запустить публикацию вручную (читает свежий код + .env с флагом ON)**

Run:
```bash
cd /home/claude-user/autowarm-testbench
nohup python3 -u publisher.py <SMOKE_ID> > /tmp/wp122_smoke_<SMOKE_ID>.log 2>&1 &
echo "PID $!"; sleep 5; tail -20 /tmp/wp122_smoke_<SMOKE_ID>.log
```
Expected: процесс стартовал, в логе — старт публикации (switcher → share-loop). Следить за логом до завершения (`tail -f`); типично 2-5 минут.
> Запуск идёт как `claude-user` (БД через `.env`, ADB через `adb_host:adb_port` задачи). Если упрётся в права (например, root-only артефакты) — fallback: задача уже `pending`+`testbench=true`, её подхватит штатный testbench-планировщик (root, тот же `.env` с флагом ON) — мониторить тот же `<SMOKE_ID>`.

- [ ] **Step 5: GATE — проверить исход и отсутствие ложного срабатывания хука**

Run:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -x -c "
SELECT pt.id, pt.status,
       COUNT(*) FILTER (WHERE e->'meta'->>'phase'='share_loop')                          AS share_loop_evts,
       COUNT(*) FILTER (WHERE e->'meta'->>'category' IN ('tt_samsung_overlay_dismissed','tt_inapp_stories_dismissed')) AS dismissed,
       COUNT(*) FILTER (WHERE e->'meta'->>'step' LIKE 'tt_5_share_loop%' AND e->>'type' IN ('error','warning')) AS share_loop_stuck,
       COUNT(*) FILTER (WHERE e->'meta'->>'category'='tt_upload_confirmation_timeout')    AS timeouts
FROM publish_tasks pt
     LEFT JOIN LATERAL jsonb_array_elements(pt.events::jsonb) AS e ON true
WHERE pt.id = <SMOKE_ID>
GROUP BY pt.id, pt.status;"
```
**GREEN (можно включать прод):** `status` ∈ {`done`,`awaiting_url`} (публикация прошла); `share_loop_stuck=0`; `timeouts=0`. Если оверлея не было — `dismissed=0`, `share_loop_evts=0` (хук вернул `clean`, основной путь не тронут — это и есть гард). Если оверлей всплыл сам — `dismissed≥1` И публикация всё равно `done`/`awaiting_url` (бонус-подтверждение).
**RED (НЕ включать прод):** публикация `failed` с `timeouts≥1` или `share_loop_stuck≥1`, ИЛИ ложный `dismissed≥1` на прогоне без реального оверлея (false-fire). → STOP, это дефект кода: собрать ui-dump/screenrecord, вернуться к code-spec, завести правку.

- [ ] **Step 6: Сохранить evidence смока**

Run:
```bash
ls -lt /tmp/autowarm_ui_dumps/ 2>/dev/null | head
# screenrecord URL (если есть) — из событий задачи:
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -tA -c "
SELECT e->'meta'->>'screen_record_url'
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events::jsonb) e
WHERE pt.id=<SMOKE_ID> AND e->'meta'->>'screen_record_url' IS NOT NULL LIMIT 1;"
```
Expected: путь(и) к ui-dump и/или URL screencast — приложить к evidence-доку (Task 6).

> **Чекпоинт:** при RED — остановиться и доложить Данилу. Прод НЕ включать.

---

## Task 4: Включить рубильник в проде (после GREEN-смока)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/.env`

- [ ] **Step 1: Проверить, что флага ещё нет, и добавить**

Run:
```bash
P=/root/.openclaw/workspace-genri/autowarm
grep -n "TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED" $P/.env || echo "NOT SET — добавляю"
printf '\nTT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true\n' >> $P/.env
tail -3 $P/.env
```
Expected: до — «NOT SET»; после — строка с `=true`.

- [ ] **Step 2: Рестарт прод-воркера с обновлением env**

Run:
```bash
sudo pm2 restart 35 --update-env
sudo pm2 status autowarm
```
Expected: `autowarm` (id 35) → `online`, свежий рестарт.

- [ ] **Step 3: Подтвердить, что флаг виден воркеру**

Run:
```bash
P=/root/.openclaw/workspace-genri/autowarm
python3 -c "from dotenv import load_dotenv; import os; load_dotenv('$P/.env'); print('flag=', os.environ.get('TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED'))"
sudo pm2 env 35 2>/dev/null | grep -i SHARE_LOOP || echo "(env смотреть после первого спавна publisher.py)"
```
Expected: `flag= true`. (publisher.py всё равно делает load_dotenv на спавн — следующая TT-публикация подхватит флаг.)

---

## Task 5: Мониторинг прод-пачки + гейт отката

**Files:** только чтение БД.

- [ ] **Step 1: Базовый дашборд — статус TT за 24ч, исключая watchdog-шум**

Run:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -c "
SELECT pt.status, COUNT(*) AS n
FROM publish_tasks pt
WHERE pt.platform='TikTok' AND pt.created_at >= NOW() - INTERVAL '24 hours'
  AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(pt.events::jsonb) e
                  WHERE e->'meta'->>'category'='watchdog_subprocess_hang')
GROUP BY pt.status ORDER BY n DESC;"
```
Expected: распределение статусов; `done`/`awaiting_url` доля не ниже baseline (вне watchdog).

- [ ] **Step 2: Целевая метрика — динамика `tt_upload_confirmation_timeout` по часам**

Run:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -c "
SELECT date_trunc('hour', pt.created_at) AS hr,
       COUNT(*) FILTER (WHERE e->'meta'->>'category'='tt_upload_confirmation_timeout') AS timeouts
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events::jsonb) e
WHERE pt.platform='TikTok' AND pt.created_at >= NOW() - INTERVAL '36 hours'
GROUP BY 1 ORDER BY 1 DESC;"
```
Expected: после включения timeouts не растут (в идеале ↓ относительно до-включения).

- [ ] **Step 3: Эффективность — dismiss-события в share_loop (хук реально гасит окно)**

Run:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -c "
SELECT pt.id, pt.device_serial, pt.status,
       e->'meta'->>'category' AS category, e->'meta'->>'phase' AS phase, pt.created_at
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events::jsonb) e
WHERE pt.platform='TikTok' AND pt.created_at >= NOW() - INTERVAL '24 hours'
  AND e->'meta'->>'phase'='share_loop'
ORDER BY pt.created_at DESC LIMIT 50;"
```
Expected (GREEN): ≥1 `tt_samsung_overlay_dismissed`/`tt_inapp_stories_dismissed` с `phase=share_loop` И соответствующие задачи завершились (`done`/`awaiting_url`).

- [ ] **Step 4: Регресс-сигналы — share_loop stuck / срывы после share-loop**

Run:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -c "
SELECT pt.id, pt.status, e->'meta'->>'step' AS step, e->'meta'->>'category' AS category, e->>'type' AS typ
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events::jsonb) e
WHERE pt.platform='TikTok' AND pt.created_at >= NOW() - INTERVAL '24 hours'
  AND e->'meta'->>'step' LIKE 'tt_5_share_loop%' AND e->>'type' IN ('error','warning')
ORDER BY pt.created_at DESC LIMIT 50;"
```
**RED → откат:** всплеск `tt_5_share_loop_*_stuck`, ИЛИ общий TT success (Step 1) просел к baseline вне watchdog-шума, ИЛИ массовые срывы сразу после share-loop (признак ухода `KEYCODE_BACK` с композера).

- [ ] **Step 5: Процедура отката (если RED)**

Run:
```bash
P=/root/.openclaw/workspace-genri/autowarm
# убрать строку с флагом из .env:
grep -v "TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED" $P/.env > $P/.env.tmp && mv $P/.env.tmp $P/.env
grep -c "TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED" $P/.env   # должно быть 0
sudo pm2 restart 35 --update-env
```
Expected: флага в `.env` нет (0), воркер рестартнут → поведение вернулось к dark-OFF. Зафиксировать причину отката в evidence + сообщить Данилу.

> **Чекпоинт:** дождаться ≥1 утренней TT-пачки. GREEN → Task 6. RED → откат + доклад.

---

## Task 6: Закрытие — evidence, OpenProject, память, merge

**Files:**
- Create: `docs/evidence/2026-05-27-wp122-tt-share-loop-activation.md`
- Modify (memory): `project_wp122_tt_share_loop_overlay.md` + `MEMORY.md`

- [ ] **Step 1: Написать evidence-док (house style: что было не так → что сделано → что осталось)**

Содержимое: результат смока (`<SMOKE_ID>`, status, gate-метрики, ui-dump/screencast), факт включения в проде (commit/время), сводка мониторинга (timeouts до/после, dismissed-наблюдения, регресс=нет), вывод. Файл — в worktree, коммит в ветку `wp122-tt-share-loop-rollout`.

- [ ] **Step 2: Коммит evidence в worktree**

Run:
```bash
cd /home/claude-user/contenthunter/.claude/worktrees/wp122-tt-share-loop-rollout
git add docs/evidence/2026-05-27-wp122-tt-share-loop-activation.md
git commit -m "docs(wp122): evidence — активация share-loop overlay (смок+включение+мониторинг)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
Expected: коммит создан на ветке `wp122-tt-share-loop-rollout`.

- [ ] **Step 3: Комментарий в OpenProject #122 + статус → «Тестирование»**

Через API (`~/secrets/openproject.env`): house-style комментарий (Что было не так → Что сделано → Что осталось, без футера), затем перевод статуса в «Тестирование» (id выяснить из `/api/v3/statuses`). Остаток: длиннохвостое наблюдение динамики → «Готово».

- [ ] **Step 4: Обновить память**

Обновить `project_wp122_tt_share_loop_overlay.md`: активация выполнена 27.05, результат смока + мониторинга, статус. Поправить строку в `MEMORY.md`.

- [ ] **Step 5: Влить доки в main + финализация worktree**

Через skill `superpowers:finishing-a-development-branch`: смержить ветку `wp122-tt-share-loop-rollout` (только docs/) в main `rmbrmv/contenthunter`, запушить, зачистить worktree. Прод-autowarm `.env` уже изменён напрямую (вне git) — это деплой, не коммит.

---

## Заметки по исполнению

- **Чекпоинт после Task 3 (смок) и после Task 5 (мониторинг):** при RED — стоп + доклад Данилу, прод не трогать / откатить.
- Прод-`.env` правится напрямую (claude-user-owned), это деплой-действие, не git-коммит.
- Все sudo — только `pm2`/`systemctl` (в скоупе). Никаких force-push, `--amend` на shared HEAD; работаем в worktree-ветке.
