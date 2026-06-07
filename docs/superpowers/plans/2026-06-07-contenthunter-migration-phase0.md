# Переезд ContentHunter — Фаза 0: подготовка сервера, деплой-пайплайн, тест-стенд

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Подготовить новый сервер `46.225.145.245`, развернуть на нём 4 стенда (prod/test × client/delivery), настроить полностью автоматический деплой через GitHub Actions и поднять рабочий тестовый стенд на отдельной обезличенной БД — без какого-либо простоя боевого сервиса.

**Architecture:** Один сервер cpx62. Caddy (реверс-прокси + авто-TLS), PostgreSQL 16 (две БД: `contenthunter`, `contenthunter_test`), PM2 для процессов. Каждый стенд — отдельная папка-чекаут репозитория (prod=ветка `main`, test=ветка `develop`), свой `.env`, свой порт. Деплой: push в ветку → GitHub Actions по SSH делает `git pull` + миграции + рестарт + health-check. Серверные чекауты — deploy-only (руками не редактируются).

**Tech Stack:** Caddy, PostgreSQL 16, Node.js (delivery: Express), Python (delivery воркеры + unic-worker), Python/FastAPI + Vue (client/validator), PM2, GitHub Actions, bash.

**Источник истины по фактам:** спек `docs/superpowers/specs/2026-06-07-contenthunter-server-migration-design.md`.

**Соглашения:**
- Старый сервер = `OLD` (`72.56.107.157`, root@). Новый = `NEW` (`46.225.145.245`, root@, ключ `/root/cpx62-access/cpx62_key`).
- Команды на NEW запускаются как `ssh -i <key> root@46.225.145.245 '<cmd>'` либо из сессии на NEW.
- Базовый каталог стендов на NEW: `/opt/contenthunter/`.
- НИЧЕГО на боевом сервисе в этой фазе не останавливаем и не меняем (кроме чтения конфигов).

---

### Task 1: Доступ и проверка достижимости серверов

**Files:** нет (операционная задача). Зафиксировать результаты в `docs/superpowers/plans/_artifacts/phase0-recon.md` (создать).

- [ ] **Step 1: Запросить/получить расширенный sudo на OLD**

Данил выдаёт на OLD (`72.56.107.157`) расширенный sudo для пользователя `claude-user`. Минимально достаточная команда (выполняет Данил под root):

```bash
echo 'claude-user ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/claude-user-migration && chmod 440 /etc/sudoers.d/claude-user-migration && visudo -c
```

Expected: `visudo -c` → `/etc/sudoers.d/claude-user-migration: parsed OK`.

- [ ] **Step 2: Проверить sudo на OLD**

Run: `sudo -n cat /root/cpx62-access/connect.txt`
Expected: содержимое файла (данные доступа к NEW: IP, пользователь, порт, заметки) выводится без запроса пароля.

- [ ] **Step 3: Прочитать данные доступа к NEW и сохранить ключ в доступное место**

```bash
sudo cat /root/cpx62-access/connect.txt
sudo install -m 600 -o claude-user -g claude-user /root/cpx62-access/cpx62_key /home/claude-user/.ssh/cpx62_key
```

Expected: видим инструкции подключения; ключ скопирован и читается claude-user.

- [ ] **Step 4: Проверить SSH-доступ к NEW**

Run: `ssh -i /home/claude-user/.ssh/cpx62_key -o StrictHostKeyChecking=accept-new root@46.225.145.245 'hostname; uname -a; cat /etc/os-release | head -2'`
Expected: hostname/версия ОС NEW выводятся (подключение успешно).

- [ ] **Step 5: Снять инвентарь NEW (что уже стоит) и записать в артефакт**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  echo "=== OS ==="; cat /etc/os-release | head -2
  echo "=== CPU/RAM/DISK ==="; nproc; free -h; df -h /
  echo "=== installed ==="; for b in caddy psql node npm python3 pip3 adb pm2 git; do printf "%s: " "$b"; command -v $b || echo MISSING; done
  echo "=== listening ==="; ss -tlnp 2>/dev/null | grep -vE "127.0.0.53" || true
  echo "=== firewall ==="; ufw status 2>/dev/null || iptables -L -n | head
'
```

Создать `docs/superpowers/plans/_artifacts/phase0-recon.md` и вставить туда вывод (инвентарь NEW + connect.txt-заметки без секретов).

Expected: знаем, что на NEW уже есть/нет, объём диска/RAM, какие порты заняты.

- [ ] **Step 6: Commit артефакта**

```bash
git add docs/superpowers/plans/_artifacts/phase0-recon.md
git commit -m "docs(migration): recon нового сервера (Фаза 0)"
```

---

### Task 2: Разведка OLD — конфиги, состав БД, сетевые зависимости

**Files:** дополнить `docs/superpowers/plans/_artifacts/phase0-recon.md`.

- [ ] **Step 1: Снять реальные `.env` обоих сервисов (замаскировать секреты в артефакт, полные — отдельно)**

```bash
sudo cat /root/.openclaw/workspace-genri/autowarm/.env        # delivery
sudo cat /root/.openclaw/workspace-genri/validator/backend/.env  # client (путь уточнить ниже)
sudo find /root/.openclaw/workspace-genri/validator -maxdepth 2 -name '.env*'
```

Зафиксировать в артефакт СПИСОК ключей (без значений). Полные значения понадобятся для `.env` на NEW — хранить вне git (передать через GitHub Secrets на этапе Task 7).

Expected: знаем полный набор env-переменных каждого сервиса.

- [ ] **Step 2: Прочитать Caddyfile OLD (нужны точные блоки client/delivery)**

```bash
sudo cat /etc/caddy/Caddyfile
```

Скопировать в артефакт блоки `client.contenthunter.ru` и `delivery.contenthunter.ru` (они станут шаблоном для NEW + позже для редиректов).

Expected: видим директивы reverse_proxy, заголовки, особые маршруты (статика `/var/www/validator` и т.п.).

- [ ] **Step 3: Инвентаризовать БД `openclaw` — список таблиц и их размеры**

```bash
sudo -u postgres psql -d openclaw -c "\dt+" 
sudo -u postgres psql -d openclaw -c "SELECT schemaname, relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"
```

Записать список таблиц в артефакт. Определить, есть ли «чужие» таблицы (не от delivery/validator). Признак ContentHunter: префиксы `autowarm_*`, `publish_*`, `validator_*`, `pipeline_*`, обстакл/лог-таблицы и т.п.

Expected: полный список таблиц; пометка, какие принадлежат CH (для чистого дампа в окне переезда).

- [ ] **Step 4: Зафиксировать роль/пользователя БД, под которым ходят сервисы**

```bash
sudo -u postgres psql -c "\du"
sudo grep -rhiE "PGUSER|PGPASSWORD|user:|password:|connectionString|DATABASE_URL" /root/.openclaw/workspace-genri/autowarm/.env /root/.openclaw/workspace-genri/validator/backend/.env 2>/dev/null
sudo grep -nE "new Pool|user:|password:" /root/.openclaw/workspace-genri/autowarm/server.js | head
```

Expected: знаем имя роли БД и способ аутентификации (пароль/peer), чтобы воспроизвести на NEW.

- [ ] **Step 5: Проверить сетевую достижимость внешних зависимостей С НОВОГО сервера**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  echo "=== S3 Beget ==="; curl -s -o /dev/null -w "%{http_code}\n" --max-time 8 https://s3.ru1.storage.beget.cloud
  echo "=== ffmpeg host 91.98.180.103:22 ==="; timeout 8 bash -c "</dev/tcp/91.98.180.103/22" && echo OPEN || echo BLOCKED
  echo "=== device adb host 82.115.54.26 ==="; timeout 8 bash -c "</dev/tcp/82.115.54.26/5555" 2>/dev/null && echo OPEN || echo "CHECK (порт уточнить из БД raspberry)"
'
```

Expected: видим, доступны ли S3 / внешний уникализатор / устройства с NEW. Любой `BLOCKED` → записать в риски (нужен whitelist нового IP на стороне зависимости — решается до окна переезда).

- [ ] **Step 6: Commit обновлённого артефакта**

```bash
git add docs/superpowers/plans/_artifacts/phase0-recon.md
git commit -m "docs(migration): разведка OLD — конфиги, состав БД, сетевые зависимости"
```

---

### Task 3: Базовый провижн NEW (пакеты, каталоги, firewall)

**Files:** нет (операционная). Команды выполняются на NEW по SSH.

- [ ] **Step 1: Установить системные пакеты**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  apt-get update
  apt-get install -y postgresql-16 postgresql-client-16 nodejs npm python3 python3-venv python3-pip android-tools-adb git curl debian-keyring debian-archive-keyring apt-transport-https
  npm install -g pm2
'
```

Expected: пакеты установлены без ошибок.

- [ ] **Step 2: Установить Caddy (официальный репозиторий)**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  curl -1sLf "https://dl.cloudsmith.io/public/caddy/stable/gpg.key" | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf "https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt" > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update && apt-get install -y caddy
  systemctl enable --now caddy
'
```

- [ ] **Step 3: Создать дерево каталогов стендов**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  mkdir -p /opt/contenthunter/{prod-delivery,prod-client,test-delivery,test-client}
  mkdir -p /opt/contenthunter/_maintenance /var/log/contenthunter
  ls -la /opt/contenthunter
'
```

- [ ] **Step 4: Проверить версии и сервисы**

Run:
```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 'node -v; python3 -V; psql --version; caddy version; pm2 -v; systemctl is-active postgresql caddy'
```
Expected: версии печатаются; `postgresql` и `caddy` → `active`.

---

### Task 4: PostgreSQL — роль и две БД

**Files:** нет (операционная).

- [ ] **Step 1: Создать роль приложения и базы**

Имя роли/пароль берём из Task 2 Step 4 (воспроизводим как на OLD, чтобы строки подключения совпали). Пароль приложения подставить из секрета.

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
  CREATE ROLE contenthunter LOGIN PASSWORD :APP_DB_PASSWORD;
  CREATE DATABASE contenthunter OWNER contenthunter;
  CREATE DATABASE contenthunter_test OWNER contenthunter;
SQL
'
```

(`:APP_DB_PASSWORD` заменить реальным значением из секрета; не коммитить.)

- [ ] **Step 2: Проверить**

Run: `ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 'sudo -u postgres psql -c "\l" | grep contenthunter'`
Expected: видны `contenthunter` и `contenthunter_test`, владелец `contenthunter`.

---

### Task 5: Сделать имя БД конфигурируемым в delivery (правка кода через GitHub-флоу)

**Files:**
- Modify: `delivery-contenthunter` репо → `server.js` (строки ~74 и ~210-213, два места `database: 'openclaw'`)

Это первая правка через новый флоу: делается в feature-ветке репо `delivery-contenthunter`, вливается в `develop`. Здесь описываем правку; ветку/PR создаём в Task 8 после настройки пайплайна, либо вручную сейчас.

- [ ] **Step 1: Заменить захардкоженное имя БД на переменную окружения**

В `server.js`, оба объявления `new Pool(...)`:

```js
// было: database: 'openclaw',
database: process.env.PGDATABASE || 'contenthunter',
```

Также убедиться, что `host`/`user`/`password`/`port` берутся из env (`process.env.PGHOST` и т.д.) с дефолтами; если уже из env — не трогать.

- [ ] **Step 2: Проверить, что нет других вхождений `openclaw` в строках подключения**

Run (в чекауте delivery): `grep -nE "openclaw" *.js | grep -iE "database|dbname|connectionString"`
Expected: после правки — пусто (в коде подключения `openclaw` не осталось; вхождения в комментариях/тестах допустимы).

- [ ] **Step 3: Аналогично для client (validator) — подтвердить, что имя БД из env**

Run: `sudo grep -rnE "openclaw|POSTGRES_DB|DATABASE_URL|dbname" /root/.openclaw/workspace-genri/validator/backend/src | grep -iv test | head`
Если имя БД захардкожено — внести такую же правку (env с дефолтом `contenthunter`) в репо `validator-contenthunter`. Если уже из env — изменений не нужно, только выставим `PGDATABASE`/`DATABASE_URL` в `.env` стенда.

Expected: имя БД в обоих сервисах управляется через env.

- [ ] **Step 4: Commit (в репо приложения, ветка develop)**

```bash
# в чекауте delivery-contenthunter
git checkout -b chore/db-name-from-env
git add server.js
git commit -m "chore(db): имя БД из env (PGDATABASE), дефолт contenthunter"
# push + PR в develop делаем в Task 8 после создания ветки develop
```

---

### Task 6: GitHub — ветки `develop` и деплойный SSH-ключ

**Files:** нет (GitHub + сервер).

- [ ] **Step 1: Создать ветку `develop` от `main` в обоих репозиториях**

```bash
for r in delivery-contenthunter validator-contenthunter; do
  git ls-remote --heads https://github.com/GenGo2/$r.git develop
done
# если develop нет — создать:
# (в локальном чекауте каждого репо) git checkout main && git pull && git checkout -b develop && git push -u origin develop
```

Expected: в обоих репо есть ветки `main` и `develop`.

- [ ] **Step 2: Сгенерировать выделенный деплойный SSH-ключ и положить публичную часть на NEW**

```bash
ssh-keygen -t ed25519 -f /tmp/ch_deploy_key -N "" -C "github-actions-deploy"
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 "mkdir -p /root/.ssh && cat >> /root/.ssh/authorized_keys" < /tmp/ch_deploy_key.pub
```

Expected: публичный ключ добавлен в `authorized_keys` на NEW.

- [ ] **Step 3: Завести GitHub Secrets в обоих репозиториях**

Через `gh` CLI (или UI). Секреты: `DEPLOY_SSH_KEY` (приватный `/tmp/ch_deploy_key`), `DEPLOY_HOST=46.225.145.245`, `DEPLOY_USER=root`. Плюс по стендам — переменные `.env` (либо один секрет `PROD_ENV`/`TEST_ENV` с содержимым `.env`).

```bash
gh secret set DEPLOY_SSH_KEY < /tmp/ch_deploy_key --repo GenGo2/delivery-contenthunter
gh secret set DEPLOY_HOST --body "46.225.145.245" --repo GenGo2/delivery-contenthunter
gh secret set DEPLOY_USER --body "root" --repo GenGo2/delivery-contenthunter
# повторить для validator-contenthunter
```

- [ ] **Step 4: Удалить временный приватный ключ из /tmp**

```bash
shred -u /tmp/ch_deploy_key /tmp/ch_deploy_key.pub
```

Expected: приватный ключ существует только в GitHub Secrets и на NEW (authorized_keys — только публичный).

---

### Task 7: Клонировать стенды и разложить `.env`

**Files:** на NEW — чекауты в `/opt/contenthunter/<stand>/` + `.env` каждого стенда.

- [ ] **Step 1: Клонировать репозитории в 4 папки на нужных ветках**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  cd /opt/contenthunter
  git clone -b main    https://<PAT>@github.com/GenGo2/delivery-contenthunter.git  prod-delivery
  git clone -b main    https://<PAT>@github.com/GenGo2/validator-contenthunter.git prod-client
  git clone -b develop https://<PAT>@github.com/GenGo2/delivery-contenthunter.git  test-delivery
  git clone -b develop https://<PAT>@github.com/GenGo2/validator-contenthunter.git test-client
'
```

(PAT — из секретов GenGo2; те же, что в `.git/config` на OLD.)

- [ ] **Step 2: Собрать `.env` для каждого стенда из реальных значений OLD (Task 2 Step 1)**

Базис — `.env` с OLD. Изменения по стендам:
- **prod-delivery / prod-client:** `PGDATABASE=contenthunter`, `PGHOST=localhost`, порты prod (delivery `3848`, client `8000`), `S3_*`/`FFMPEG_HOST`/устройства — как на OLD.
- **test-delivery / test-client:** `PGDATABASE=contenthunter_test`, отдельные порты (delivery `3948`, client `8100`), **выключить реальную публикацию** (см. Task 10) — выставить `PUBLISH_DAILY_LIMITS_ENABLED`/dispatch-флаги в безопасный режим и/или `TEST_MODE=1`.

Разложить файлы как `/opt/contenthunter/<stand>/.env` (delivery) и соответствующий путь backend для client. Права `600`.

Expected: у каждого стенда корректный `.env`; prod указывает на `contenthunter`, test — на `contenthunter_test`.

- [ ] **Step 3: Установить зависимости в каждом чекауте**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  cd /opt/contenthunter/prod-delivery && npm ci
  cd /opt/contenthunter/test-delivery && npm ci
  cd /opt/contenthunter/prod-delivery/unic-worker && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  cd /opt/contenthunter/test-delivery/unic-worker && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  # client (validator): backend venv + frontend build
  cd /opt/contenthunter/prod-client/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  cd /opt/contenthunter/prod-client/frontend && npm ci && npm run build
  cd /opt/contenthunter/test-client/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  cd /opt/contenthunter/test-client/frontend && npm ci && npm run build
'
```

Expected: зависимости поставлены, фронт client собран в `dist`.

---

### Task 8: PM2 ecosystem-файлы и запуск процессов всех стендов

**Files:** на NEW — `/opt/contenthunter/ecosystem.config.js` (один файл, все стенды) либо по файлу на стенд.

- [ ] **Step 1: Создать PM2 ecosystem с уникальными именами и портами**

Имена: `prod-delivery`, `prod-delivery-unic`, `test-delivery`, `test-delivery-unic`, `prod-client`, `test-client`. Каждому — свой `cwd`, `env_file` (`.env` стенда), порт. Пример для одного процесса:

```js
// /opt/contenthunter/ecosystem.config.js
module.exports = { apps: [
  { name: 'prod-delivery', cwd: '/opt/contenthunter/prod-delivery', script: 'server.js',
    env: { PORT: '3848', PGDATABASE: 'contenthunter' } },
  { name: 'test-delivery', cwd: '/opt/contenthunter/test-delivery', script: 'server.js',
    env: { PORT: '3948', PGDATABASE: 'contenthunter_test' } },
  { name: 'prod-delivery-unic', cwd: '/opt/contenthunter/prod-delivery/unic-worker',
    interpreter: '/opt/contenthunter/prod-delivery/unic-worker/.venv/bin/python', script: 'worker.py' },
  { name: 'test-delivery-unic', cwd: '/opt/contenthunter/test-delivery/unic-worker',
    interpreter: '/opt/contenthunter/test-delivery/unic-worker/.venv/bin/python', script: 'worker.py' },
  { name: 'prod-client', cwd: '/opt/contenthunter/prod-client/backend',
    interpreter: '/opt/contenthunter/prod-client/backend/.venv/bin/python',
    script: '-m', args: 'uvicorn src.main:app --host 127.0.0.1 --port 8000' },
  { name: 'test-client', cwd: '/opt/contenthunter/test-client/backend',
    interpreter: '/opt/contenthunter/test-client/backend/.venv/bin/python',
    script: '-m', args: 'uvicorn src.main:app --host 127.0.0.1 --port 8100' },
]}
```

(Точные `script`/`args` client уточнить по OLD: `sudo cat /root/.openclaw/workspace-genri/validator/backend/<start-команда>` — взять как есть.)

- [ ] **Step 2: Запустить ТОЛЬКО тестовые процессы (prod пока не поднимаем — без данных)**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 '
  cd /opt/contenthunter
  pm2 start ecosystem.config.js --only test-delivery,test-delivery-unic,test-client
  pm2 save && pm2 startup systemd -u root --hp /root | tail -1
  pm2 ls
'
```

Expected: test-стенды `online`. (prod-стенды запустим в плане окна переезда, после заливки данных.)

- [ ] **Step 3: Проверить, что тестовые сервисы слушают порты**

Run: `ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 'curl -s -o /dev/null -w "delivery:%{http_code}\n" localhost:3948/login; curl -s -o /dev/null -w "client:%{http_code}\n" localhost:8100/'`
Expected: ненулевые HTTP-коды (сервисы отвечают). Если падают — смотреть `pm2 logs test-delivery`.

---

### Task 9: Caddy — сайты 4 доменов (test сразу, prod — заглушка-«готовится»)

**Files:** на NEW — `/etc/caddy/Caddyfile`.

- [ ] **Step 1: Прописать блоки Caddy**

```caddy
# /etc/caddy/Caddyfile
test-delivery.contenthunter.ru { reverse_proxy localhost:3948 }
test-client.contenthunter.ru {
    handle /api/* { reverse_proxy localhost:8100 }
    handle { root * /opt/contenthunter/test-client/frontend/dist; try_files {path} /index.html; file_server }
}
prod-delivery.contenthunter.ru { reverse_proxy localhost:3848 }
prod-client.contenthunter.ru {
    handle /api/* { reverse_proxy localhost:8000 }
    handle { root * /opt/contenthunter/prod-client/frontend/dist; try_files {path} /index.html; file_server }
}
```

(Маршрутизацию client `/api` vs статика выверить по Caddyfile OLD из Task 2 Step 2 — воспроизвести 1:1.)

- [ ] **Step 2: Валидировать и перезагрузить Caddy**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy'
```

Expected: `Valid configuration`; reload без ошибок; Caddy выписывает TLS для 4 доменов (A-записи уже на NEW).

- [ ] **Step 3: Проверить HTTPS тестовых доменов снаружи**

Run: `curl -s -o /dev/null -w "%{http_code}\n" https://test-delivery.contenthunter.ru/login; curl -s -o /dev/null -w "%{http_code}\n" https://test-client.contenthunter.ru/`
Expected: валидный TLS, осмысленные коды (200/302). prod-домены пока могут отдавать 502 (процессы не запущены) — это ожидаемо до окна переезда.

---

### Task 10: Обезличенный слепок БД для тест-стенда + выключение реальной публикации

**Files:** на NEW — скрипт `/opt/contenthunter/_ops/anonymize_test_db.sql` (создать).

- [ ] **Step 1: Залить структуру + данные из OLD во временную копию (для теста — это допустимо, OLD не трогаем)**

```bash
# дамп только CH-таблиц (список из Task 2 Step 3) — структура+данные
sudo -u postgres pg_dump -d openclaw --no-owner --no-privileges -t 'autowarm_*' -t 'publish_*' -t 'validator_*' -t 'pipeline_*' -F c -f /tmp/ch_seed.dump
# (полный список -t уточнить по Task 2 Step 3)
scp -i /home/claude-user/.ssh/cpx62_key /tmp/ch_seed.dump root@46.225.145.245:/tmp/
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 'sudo -u postgres pg_restore --no-owner --role=contenthunter -d contenthunter_test /tmp/ch_seed.dump; shred -u /tmp/ch_seed.dump'
sudo shred -u /tmp/ch_seed.dump
```

Expected: `contenthunter_test` содержит реальную структуру и данные.

- [ ] **Step 2: Написать скрипт обезличивания**

Создать `/opt/contenthunter/_ops/anonymize_test_db.sql` — занулить/замаскировать чувствительное: токены/cookie аккаунтов, пароли пользователей (заменить на известный тестовый хэш), персональные данные, ключи API в настройках. Точный список колонок — по схеме из Task 2 Step 3. Пример:

```sql
-- пароли всех пользователей → известный тестовый ('test12345')
UPDATE autowarm_users SET password_hash = '$2a$10$<known_test_hash>';
UPDATE validator_users SET password_hash = '<known_test_hash>';
-- занулить секреты/токены аккаунтов
UPDATE social_accounts SET auth_token = NULL, cookies = NULL, session_blob = NULL;
-- любые внешние ключи в настройках → пусто
UPDATE autowarm_settings SET value = '' WHERE key ~* 'key|token|secret|password';
```

- [ ] **Step 3: Применить обезличивание**

```bash
ssh -i /home/claude-user/.ssh/cpx62_key root@46.225.145.245 'sudo -u postgres psql -d contenthunter_test -v ON_ERROR_STOP=1 -f /opt/contenthunter/_ops/anonymize_test_db.sql'
```

Expected: запрос на поиск оставшихся секретов возвращает 0 строк (проверочный SELECT в конце скрипта).

- [ ] **Step 4: Гарантированно выключить реальную публикацию на тесте**

В `.env` test-стендов выставить безопасный режим: отключить флаги боевого диспатча/публикации (по факту kill-switch'ей delivery: `PUBLISH_DAILY_LIMITS_ENABLED` и т.п.) и/или ввести явный `TEST_MODE=1`, который воркер публикации проверяет перед отправкой на устройство. Если такого флага в коде нет — добавить минимальный guard в `dispatchPublishQueue` (через GitHub-флоу в `develop`): если `process.env.TEST_MODE==='1'` — публикация не отправляется на устройство, только лог.

Перезапустить test-delivery: `pm2 restart test-delivery test-delivery-unic`.

- [ ] **Step 5: Проверить, что тест НЕ публикует**

Run: проверить в логах `pm2 logs test-delivery --lines 50`, что диспатчер в test-режиме не отправляет реальные задачи на устройства (ищем маркер `TEST_MODE`/skip).
Expected: реальная публикация на тесте подавлена.

---

### Task 11: GitHub Actions — авто-деплой (develop→test, main→prod)

**Files:**
- Create в каждом репо: `.github/workflows/deploy.yml`
- Create на NEW: `/opt/contenthunter/_ops/deploy.sh`

- [ ] **Step 1: Серверный deploy-скрипт (идемпотентный, с health-check и откатом)**

`/opt/contenthunter/_ops/deploy.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
STAND="$1"   # prod-delivery | test-delivery | prod-client | test-client
DIR="/opt/contenthunter/$STAND"
cd "$DIR"
PREV=$(git rev-parse HEAD)
git fetch --quiet origin
git reset --hard "origin/$(git rev-parse --abbrev-ref HEAD)"
# зависимости
if [ -f package.json ]; then npm ci --omit=dev || npm ci; fi
if [ -d frontend ]; then (cd frontend && npm ci && npm run build); fi
if [ -f backend/requirements.txt ]; then backend/.venv/bin/pip install -r backend/requirements.txt; fi
# миграции (delivery: node migrate; client: alembic — уточнить по проекту)
[ -f migrate.js ] && node migrate.js || true
[ -d backend/alembic ] && backend/.venv/bin/alembic upgrade head || true
# рестарт + health-check
pm2 restart "$STAND" --update-env
PORT=$(grep -oE 'PORT=[0-9]+' .env | cut -d= -f2 || echo 0)
sleep 3
if ! curl -fsS -o /dev/null "http://localhost:${PORT}/healthz" 2>/dev/null && ! curl -fsS -o /dev/null "http://localhost:${PORT}/login" 2>/dev/null; then
  echo "HEALTHCHECK FAILED → откат на $PREV"; git reset --hard "$PREV"; pm2 restart "$STAND" --update-env; exit 1
fi
echo "deploy $STAND OK"
```

(Команды миграций client/delivery выверить по реальным проектам — alembic vs кастомный мигратор.)

- [ ] **Step 2: Workflow в `delivery-contenthunter`**

`.github/workflows/deploy.yml`:

```yaml
name: deploy
on:
  push:
    branches: [develop, main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: webfactory/ssh-agent@v0.9.0
        with: { ssh-private-key: ${{ secrets.DEPLOY_SSH_KEY }} }
      - name: Deploy
        run: |
          STAND=$([ "${{ github.ref_name }}" = "main" ] && echo prod-delivery || echo test-delivery)
          ssh -o StrictHostKeyChecking=accept-new ${{ secrets.DEPLOY_USER }}@${{ secrets.DEPLOY_HOST }} \
            "/opt/contenthunter/_ops/deploy.sh $STAND"
```

- [ ] **Step 3: Аналогичный workflow в `validator-contenthunter`** (STAND = `prod-client`/`test-client`).

- [ ] **Step 4: Закоммитить правку из Task 5 в `develop` и убедиться, что авто-деплой сработал на test**

```bash
# в репо delivery: смержить chore/db-name-from-env в develop (push в develop)
```
Открыть вкладку Actions → workflow зелёный; на NEW `cd /opt/contenthunter/test-delivery && git log -1` показывает новый коммит.

Expected: push в `develop` → test-delivery автоматически обновился, health-check прошёл.

---

### Task 12: Смоук-тест тест-стенда (приёмка Фазы 0)

**Files:** нет.

- [ ] **Step 1: Логин на оба тестовых интерфейса**

Войти на `https://test-delivery.contenthunter.ru/login` и `https://test-client.contenthunter.ru/` тестовым пользователем (пароль из обезличивания, Task 10 Step 2).
Expected: вход успешен, дашборды открываются, видны (обезличенные) данные.

- [ ] **Step 2: Проверить чтение БД и ключевые экраны**

Открыть дашборд delivery (очередь публикаций, аналитика), client (загрузка/модерация/планирование).
Expected: страницы рендерятся, ошибок 500 нет; данные из `contenthunter_test`.

- [ ] **Step 3: Подтвердить изоляцию: тест НЕ пишет в боевую БД и НЕ публикует**

Проверить `.env` (PGDATABASE=contenthunter_test) и логи диспатчера (TEST_MODE).
Expected: никаких обращений к боевой БД/устройствам в боевом режиме.

- [ ] **Step 4: Проверить полный цикл авто-деплоя ещё раз (тривиальная правка)**

Сделать безобидную правку (например, версия/коммент) в `develop` любого репо → убедиться, что через ~1-2 мин она на тест-стенде.
Expected: авто-деплой воспроизводим.

- [ ] **Step 5: Зафиксировать готовность Фазы 0**

Дополнить `docs/superpowers/plans/_artifacts/phase0-recon.md` итогом: что развёрнуто, порты, имена PM2, открытые риски для окна переезда. Commit.

```bash
git add docs/superpowers/plans/_artifacts/phase0-recon.md
git commit -m "docs(migration): Фаза 0 готова — тест-стенд живёт, авто-деплой работает"
```

**Результат Фазы 0:** Тест-стенд (test-client/test-delivery) работает на `contenthunter_test`, реальная публикация выключена, авто-деплой `develop→test` доказан. Prod-стенды развёрнуты и сконфигурированы, но не запущены/не переключены — это делает план окна переезда (Фаза 1–2), который пишется после Фазы 0 на основе собранных фактов.

---

## Self-Review (выполнено автором плана)

- **Покрытие спека:** топология (Task 3,8,9), деплой-пайплайн (Task 6,11), ветки develop/main (Task 6,11), БД rename openclaw→contenthunter (Task 4,5,7), test-БД обезличенная + выкл. публикации (Task 10), чистка легаси (вне Фазы 0: ch-auth/producer не клонируются вовсе — покрыто тем, что в Task 7 клонируются только 2 репо; косметика логина и окно переезда — в плане Фазы 1–2), внешние зависимости/сеть (Task 2 Step 5). Плашка/заморозка/дамп/редиректы — сознательно в плане Фазы 1–2.
- **Заглушки:** значения секретов и точные `-t` таблицы/команды миграций помечены как «уточнить из Task 2/по проекту» — это шаги сбора факта внутри плана, а не заглушки результата.
- **Согласованность имён:** стенды `prod-delivery/prod-client/test-delivery/test-client`, БД `contenthunter`/`contenthunter_test`, порты delivery 3848/3948, client 8000/8100 — единообразны по всем задачам.

---

## ПОПРАВКИ К ПЛАНУ ПОСЛЕ РАЗВЕДКИ (2026-06-07) — ПРИОРИТЕТНО

Разведка изменила картину БД. Эти поправки переопределяют соответствующие задачи выше. Подробности — в спеке, раздел «Обновление после разведки».

- **Task 3 (провижн):** добавить `docker` + `docker compose` плагин; добавить **swap** (на NEW swap=0, 30 ГБ RAM — создать 8–16 ГБ swapfile); НЕ ставить `postgresql-16` сервером (БД будет в Docker). `postgresql-client-16` оставить (для psql/pg_restore). Включить ufw с правилами (22/80/443).
- **Task 4 (PostgreSQL) → переписать как «Docker-compose pgvector»:** `/opt/contenthunter/_ops/db/compose.yml` с образом `pgvector/pgvector:pg16`, volume для данных, порт 5432 (только localhost), пароль роли из секрета. Внутри создать БД `contenthunter` и `contenthunter_test`, роль `contenthunter`, расширения `pg_trgm`+`pgcrypto` в обеих. Бэкап — на уровне volume + Hetzner-снапшоты.
- **Task 5 (имя БД в env) → расширить до «креды delivery полностью из env»:** `server.js` — `database/user/password/host/port` из `process.env.PG*` (дефолт БД `contenthunter`), убрать хардкод `openclaw/openclaw123`. Это правка через ветку `develop`.
- **Новая Task 5b (код-фиксы cross-schema → public, через `develop`):**
  - `sim_scanner.py:117` `factory.device_numbers`→`public.factory_device_numbers`; `:118` `factory.raspberry_port`→`public.raspberry_port`.
  - `server.js:8767` `factory.device_numbers`→`public.factory_device_numbers` (рядом, :8769, уже public — привести к согласованности).
  - `warmer.py:1198/2478` `factory.hashtags`→`public.factory_hashtags`.
  - Вычистить мёртвую `FACTORY_DB_*` из `validator/.env` (+ бэкап-копии).
  - Проверка: `grep -rnE "\b(factory|hr|team|finance)\.[a-z_]+"` по коду CH (искл. node_modules/ложные `.run(`) → пусто в SQL-контексте.
- **Task 10 (тестовый слепок) → переписать под выборочный дамп:**
  1. Дамп с OLD ТОЛЬКО CH-owned public-таблиц (схема public с `-T`-исключениями: убрать `LiteLLM_*`,`systematika_*`,`billing_*`,CRM `meetings/people/transcriptions/client_messages/telegram_messages`, 4 ничейные). Источник — Docker-контейнер: `sudo docker exec openclaw-postgres pg_dump -U openclaw -d openclaw --schema=public -T 'LiteLLM_*' -T 'systematika_*' ... -Fc -f /tmp/ch.dump` (полный список `-T` — из артефакта code-recon). Структуру `factory`/`hr`/`team`/`finance` НЕ включаем (по умолчанию `--schema=public` их и не берёт).
  2. Разово скопировать `factory.hashtags`→`public.factory_hashtags` (создать таблицу + данные) ДО дампа, чтобы попало в слепок.
  3. `pg_restore` в `contenthunter_test`; затем обезличивание (Task 10 Step 2-3) + выкл. реальной публикации (Step 4).
  4. Полные данные (включая `autowarm_device_metrics` 4.1 млн строк) — НЕ обрезать.
- **factory_sync:** на NEW **не переносим и не запускаем** `scripts/factory_sync.py`; внешний канал к `193.124.112.222` не нужен; схему `factory` не создаём.
- **farm-platform** — не разворачиваем.

Эти же поправки применяются и к плану окна переезда (Фаза 1–2), который пишется после Фазы 0.
