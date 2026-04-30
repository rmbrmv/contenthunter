# Remote Factory DB Phase-Out — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Полностью отключить новый сервис contenthunter.ru от внешней legacy-БД factory@193.124.112.222:49002 — все парсинг/аналитика/warmer'ы переходят на локальную openclaw, мост `sync_sources.py` + страница `/sources` в валидаторе удаляются.

**Architecture:** 6 фаз из дизайна. **Ф0** — заморозка cron `sync_sources.py` (ручное действие на сервере). **Ф1** — удаление моста и legacy UI в `GenGo2/validator-contenthunter`. **Ф2-Ф4** — серия атомарных коммитов в `GenGo2/delivery-contenthunter` (autowarm prod, есть auto-push hook): `analytics_collector.py` ×2, 7 живых autowarm-файлов (1 файл = 1 коммит), удаление 3 dead-файлов. **Ф5** — финальный аудит и evidence в `rmbrmv/contenthunter`.

**Tech Stack:** Python 3 + psycopg2 (autowarm), FastAPI + SQLAlchemy + Vue 3 (validator), PostgreSQL 14 (local openclaw), PM2 (process manager). Auto-push git-hook в prod autowarm `/root/.openclaw/workspace-genri/autowarm/` синхронизирует main → `GenGo2/delivery-contenthunter`.

**Spec:** `.ai-factory/plans/2026-04-30-remote-factory-phaseout-design.md`

---

## Репо и ветки

| Репо | Путь на VPS | Ветка | Что делает |
|---|---|---|---|
| `rmbrmv/contenthunter` | `/home/claude-user/contenthunter` | `design/remote-factory-phaseout-20260430` | Дизайн (готов), evidence в Ф5 |
| `GenGo2/validator-contenthunter` | `/tmp/validator-fix` | `feat/remove-sync-sources-20260430` (создаётся в T2) | Ф1 — удаление моста |
| `GenGo2/delivery-contenthunter` (autowarm prod) | `/root/.openclaw/workspace-genri/autowarm/` | `feat/remote-factory-phaseout-20260430` (создаётся в T3) | Ф2/Ф3/Ф4 — переписать на local |

## Settings

- **Testing:** smoke per-file (dry-run скриптов где есть entry-point) + post-deploy наблюдение `pm2 logs`. Unit-тесты не пишем — для большинства файлов их нет, и suite на autowarm/tests минимален.
- **Logging:** verbose stdout — каждый scheduler/cron-цикл в `pm2 logs autowarm`.
- **Docs:** evidence-файл в `rmbrmv/contenthunter` после Ф5 (Task T14).
- **Memory update:** в конце — добавить запись `project_remote_factory_phaseout.md` в `~/.claude/projects/-home-claude-user-contenthunter/memory/` (Task T15).

---

## Code Mapping (canonical для всех Ф2-Ф3 task'ов)

При переписывании любого SQL применяй ровно эти замены — DRY:

| Remote (193.124.112.222:49002 / `factory`) | Local (`openclaw`) |
|---|---|
| `pack_accounts pa` | `factory_pack_accounts fpa` (изменить alias!) |
| `device_numbers dn` | `factory_device_numbers dn` (alias оставить) |
| `factory_projects fp` (с `fp.api_name`) | `validator_projects vp` (с `vp.project`) |
| `pa.id`, `pa.device_num_id`, `pa.project_id` | `fpa.id`, `fpa.device_num_id`, `fpa.project_id` |
| `users` | `factory_users` (только если код реально джойнит — в autowarm не встречается) |

**Удаление** в каждом файле:
- Константа `DIST_DB_CONFIG = {...}` / `DB_FACTORY = dict(...)` / `FACTORY = dict(...)` — целиком.
- `import psycopg2 as pg2` если он только для factory connection (убедиться что не используется ещё где-то в файле).
- `psycopg2.connect(**DIST_DB_CONFIG)` / `psycopg2.connect(**DB_FACTORY)` / `psycopg2.connect(**FACTORY)` → `psycopg2.connect(**DB_CONFIG)` (или `**DB_MAIN` — посмотреть как названа local-константа в файле).

---

## Файловая структура

**Validator (T2):**
- Delete: `validator/sync_sources.py`, `backend/src/routers/sources.py`, `frontend/src/pages/client/SourcesPage.vue`
- Modify: `backend/src/main.py` (удалить import sources + include_router), `frontend/src/router/index.ts` (удалить route `/sources`)

**Autowarm — переписать на local (T3-T11, 1 файл = 1 коммит):**
- Modify: `analytics_collector.py:42-50, 130-149`
- Modify: `analytics_collector_v2.py:27-29, 47-80`
- Modify: `instagram_archiver.py:514-516, 520-528`
- Modify: `archive_scheduler.py:12-13, 41-58`
- Modify: `archiver_base.py:11-12` (+ tiktok_archiver.py:11,278; youtube_archiver.py:12,361)
- Modify: `social_audit.py:78-82, 95-110, 126-132, 148-160`
- Modify: `profile_inspector.py:62-66, 77-91, 107-113`
- Modify: `whatsapp_warmer.py:948-964` (только функция `scan_all_phones`)
- Modify: `warmer.py:78-84` (удаление dead-const)

**Autowarm — удалить целиком (T12):**
- Delete: `telegram_warmer.py`, `wa_register_all.py`, `run_retry_audit.py`

**Evidence (T14):**
- Create: `/home/claude-user/contenthunter/.ai-factory/evidence/2026-04-30-remote-factory-phaseout-evidence.md`

---

## Tasks

### Task T0 — Pre-flight: baseline + проверка состояния

**Files:** none (только проверки)

- [ ] **Step 1: Подтвердить prod cwd PM2** (`feedback_pm2_dump_path_drift.md`)

```bash
sudo pm2 describe autowarm | grep "exec cwd"
```

Ожидаем: `exec cwd: /root/.openclaw/workspace-genri/autowarm`. Если другое — STOP, разобраться.

- [ ] **Step 2: Зафиксировать baseline grep**

```bash
cd /tmp/validator-fix && git grep -nE "193\.124\.112\.222|49002" | wc -l
cd /root/.openclaw/workspace-genri/autowarm && git grep -nE "193\.124\.112\.222|49002" -- ':!*.bak*' ':!*.md' ':!docs/' ':!evidence/' | wc -l
```

Записать оба числа — на финале (T13) они должны стать 0.

- [ ] **Step 3: Зафиксировать baseline TCP**

```bash
ss -tn dst 193.124.112.222:49002 | wc -l
```

Записать число (сейчас FIN-WAIT-2 присутствуют).

- [ ] **Step 4: Зафиксировать baseline данных**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT
  (SELECT MAX(upload_date) FROM factory.contentlab_videos_upload) AS contentlab_max_date,
  (SELECT COUNT(*) FROM factory.contentlab_videos_upload WHERE upload_date > NOW() - INTERVAL '1 day') AS contentlab_24h,
  (SELECT MAX(snapshot_date) FROM account_audience_snapshots) AS audience_max_date,
  (SELECT COUNT(*) FROM account_audience_snapshots WHERE snapshot_date > CURRENT_DATE - 7) AS audience_7d;
"
```

Записать значения. После Ф0 `contentlab_24h` должна перестать расти. После Ф2 `audience_max_date` должна оживать.

- [ ] **Step 5: Подтвердить наличие всех целевых таблиц локально**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "
SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN ('factory_pack_accounts','factory_device_numbers','validator_projects','archive_tasks','tg_accounts','wa_accounts','factory_inst_accounts','raspberry_port')
ORDER BY table_name;
"
```

Ожидаем 8 строк. Если меньше — STOP, нужна миграция.

- [ ] **Step 6: Подтвердить совместимость колонок**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d factory_pack_accounts" | head -20
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d factory_device_numbers" | head -20
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d validator_projects" | head -20
```

Проверить что присутствуют:
- `factory_pack_accounts`: `id`, `device_num_id`, `project_id`
- `factory_device_numbers`: `id`, `device_id`, `raspberry`, `active`
- `validator_projects`: `id`, `project`

Если какой-то колонки нет — STOP, миграция отдельно.

---

### Task T1 — Ф0: заморозить cron sync_sources.py

**Files:** crontab root (на сервере, не в git)

- [ ] **Step 1: Показать текущий cron**

```bash
sudo crontab -l -u root | grep -n sync_sources
```

Ожидаем строку вида `*/15 * * * * python3 /root/.openclaw/workspace-genri/validator/sync_sources.py >> /var/log/validator_sync.log 2>&1`. Запомнить точную строку.

- [ ] **Step 2: Закомментировать строку**

```bash
sudo crontab -l -u root > /tmp/cron-backup-20260430.txt
sudo crontab -l -u root | sed 's|^\(\*/15 \* \* \* \* python3 /root/.openclaw/workspace-genri/validator/sync_sources.py.*\)|# DISABLED 2026-04-30 phase-out: \1|' | sudo crontab -u root -
```

- [ ] **Step 3: Verify**

```bash
sudo crontab -l -u root | grep sync_sources
```

Ожидаем строку с префиксом `# DISABLED 2026-04-30 phase-out:`.

- [ ] **Step 4: Smoke (через 30 минут)**

```bash
ss -tn dst 193.124.112.222:49002 | wc -l
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "SELECT COUNT(*) FROM factory.contentlab_videos_upload WHERE upload_date > NOW() - INTERVAL '30 minutes'"
```

Ожидаем: TCP — 0, INSERTs за 30 минут — 0.

**Rollback:** `sudo crontab -u root - < /tmp/cron-backup-20260430.txt`.

---

### Task T2 — Ф1: удалить мост sync_sources + страницу /sources

**Files:**
- Delete: `/tmp/validator-fix/validator/sync_sources.py`
- Delete: `/tmp/validator-fix/backend/src/routers/sources.py`
- Modify: `/tmp/validator-fix/backend/src/main.py`
- Delete: `/tmp/validator-fix/frontend/src/pages/client/SourcesPage.vue`
- Modify: `/tmp/validator-fix/frontend/src/router/index.ts`

- [ ] **Step 1: Подготовить ветку**

```bash
cd /tmp/validator-fix
git fetch origin main
git checkout main
git pull
git checkout -b feat/remove-sync-sources-20260430
```

- [ ] **Step 2: Удалить файлы**

```bash
rm /tmp/validator-fix/validator/sync_sources.py
rm /tmp/validator-fix/backend/src/routers/sources.py
rm /tmp/validator-fix/frontend/src/pages/client/SourcesPage.vue
```

- [ ] **Step 3: Убрать из main.py**

В файле `/tmp/validator-fix/backend/src/main.py` найти строку:

```python
from .routers import auth, projects, sources, upload, content, validation, schedule, accounts, admin, dashboard
```

Заменить на (убрать `sources,`):

```python
from .routers import auth, projects, upload, content, validation, schedule, accounts, admin, dashboard
```

И найти/удалить строку:

```python
app.include_router(sources.router)
```

- [ ] **Step 4: Убрать route из frontend router**

В `/tmp/validator-fix/frontend/src/router/index.ts` найти и удалить строку:

```typescript
{ path: '/sources', component: () => import('@/pages/client/SourcesPage.vue'), meta: { roles: ['client', 'manager', 'producer', 'admin'] } },
```

- [ ] **Step 5: Smoke — backend**

```bash
cd /tmp/validator-fix/backend
python3 -c "from src.main import app; print([r.path for r in app.routes if 'sources' in r.path])"
```

Ожидаем: пустой список `[]`.

- [ ] **Step 6: Smoke — frontend компиляция**

```bash
cd /tmp/validator-fix/frontend
grep -rn "SourcesPage\|/sources" src/ --include="*.vue" --include="*.ts"
```

Ожидаем: пустой вывод (никаких ссылок не осталось).

- [ ] **Step 7: Commit**

```bash
cd /tmp/validator-fix
git add -A
git commit -m "$(cat <<'EOF'
feat: remove legacy factory@193.124.112.222 sync bridge and /sources page

Phase-out internal: новый сервис не использует master-систему 193.124.
Удалены sync_sources.py (cron мост), routers/sources.py + его include
в main.py, SourcesPage.vue + route /sources в frontend. Локальная таблица
factory.contentlab_videos_upload оставлена как архив (не дропаем сейчас).

Pre-condition: cron `sync_sources.py` заморожен в Ф0 на сервере.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Push + PR**

```bash
git push -u origin feat/remove-sync-sources-20260430
gh pr create --title "Remove legacy factory@193.124 sync bridge + /sources page" --body "$(cat <<'EOF'
## Summary
- Drop validator/sync_sources.py cron bridge to remote factory@193.124.112.222:49002
- Drop backend /api/sources router
- Drop frontend /sources page (Журнал исходников)

Part of remote factory phase-out — see design at `rmbrmv/contenthunter:.ai-factory/plans/2026-04-30-remote-factory-phaseout-design.md`.

Pre-condition: cron `*/15 * * * * sync_sources.py` already disabled on the server (Ф0).

Local table `factory.contentlab_videos_upload` is kept as archive — drop is a separate decision.

## Test plan
- [ ] backend pytest зелёный
- [ ] frontend `npm run build` зелёный
- [ ] curl /api/sources → 404
- [ ] открыть /sources в браузере → не существует

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

### Task T3 — Ф2.1: analytics_collector.py → local

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/analytics_collector.py:42-50, 130-149`

- [ ] **Step 1: Подготовить ветку в autowarm prod**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin main
git checkout main
git pull
git checkout -b feat/remote-factory-phaseout-20260430
```

- [ ] **Step 2: Удалить DIST_DB_CONFIG**

В `/root/.openclaw/workspace-genri/autowarm/analytics_collector.py` найти блок (строки 46-50):

```python
DIST_DB_CONFIG = {
    'host': '193.124.112.222', 'port': 49002,
    'dbname': 'factory', 'user': 'roman_ai_readonly',
    'password': 'Bo37H#Kla8dl0chQnL0@3jSlcY', 'connect_timeout': 10
}
```

Удалить целиком (5 строк включая закрывающую `}`).

- [ ] **Step 3: Переписать get_active_accounts()**

Найти блок начиная со строки 130 (`conn = psycopg2.connect(**DIST_DB_CONFIG)`):

```python
        conn = psycopg2.connect(**DIST_DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT
                fia.username       AS account,
                fia.platform,
                fp.api_name        AS project,
                dn.device_id       AS device_serial,
                rp.adb             AS adb_port,
                rp.host            AS adb_host
            FROM factory_inst_accounts fia
            JOIN pack_accounts pa   ON pa.id = fia.pack_id
            JOIN factory_projects fp ON fp.id = pa.project_id
            JOIN device_numbers dn  ON dn.id = pa.device_num_id
            JOIN raspberry_port rp  ON rp.raspberry_number = dn.raspberry
            WHERE fia.active = true
              AND LOWER(fia.platform) IN ('instagram', 'tiktok', 'youtube')
              AND dn.active = true
            ORDER BY dn.device_id, fia.username
        """)
```

Заменить на (внимание: `pa` → `fpa`, `factory_projects fp` → `validator_projects vp`, `fp.api_name` → `vp.project`, `device_numbers` → `factory_device_numbers`, connect использует `DB_CONFIG`):

```python
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT
                fia.username       AS account,
                fia.platform,
                vp.project         AS project,
                dn.device_id       AS device_serial,
                rp.adb             AS adb_port,
                rp.host            AS adb_host
            FROM factory_inst_accounts fia
            JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
            JOIN validator_projects vp     ON vp.id = fpa.project_id
            JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id
            JOIN raspberry_port rp         ON rp.raspberry_number = dn.raspberry
            WHERE fia.active = true
              AND LOWER(fia.platform) IN ('instagram', 'tiktok', 'youtube')
              AND dn.active = true
            ORDER BY dn.device_id, fia.username
        """)
```

- [ ] **Step 4: Smoke — sanity check syntax**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import analytics_collector; print('import ok')"
```

Ожидаем: `import ok`.

- [ ] **Step 5: Smoke — get_active_accounts работает**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "
from analytics_collector import get_active_accounts
accounts = get_active_accounts()
print(f'Got {len(accounts)} accounts')
for a in accounts[:3]:
    print(a)
"
```

Ожидаем: число > 0, формат записей `{'account', 'platform', 'project', 'device_serial', 'adb_port', 'adb_host'}`.

- [ ] **Step 6: Подтвердить чистоту от 193.124**

```bash
grep -n "193\.124\|49002\|DIST_DB_CONFIG" /root/.openclaw/workspace-genri/autowarm/analytics_collector.py
```

Ожидаем: пустой вывод.

- [ ] **Step 7: Commit (atomic — auto-push hook доставит в prod)**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add analytics_collector.py
git commit -m "$(cat <<'EOF'
feat(analytics): collector reads accounts from local openclaw

Replace remote factory@193.124.112.222:49002 lookups with local equivalents:
- pack_accounts → factory_pack_accounts
- device_numbers → factory_device_numbers
- factory_projects (fp.api_name) → validator_projects (vp.project)

Drops DIST_DB_CONFIG. Side-effect: should revive account_audience_snapshots
pipeline (currently empty; collector likely failing silently on remote read).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Verify auto-push deploy**

```bash
sleep 5
git log --oneline -1
# на GenGo2/delivery-contenthunter тот же SHA должен появиться через секунды
```

---

### Task T4 — Ф2.2: analytics_collector_v2.py → local

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/analytics_collector_v2.py:27-29, 47-80`

- [ ] **Step 1: Удалить DB_FACTORY и get_factory_db()**

В `/root/.openclaw/workspace-genri/autowarm/analytics_collector_v2.py` найти строки 27-29:

```python
DB_MAIN    = dict(host='localhost', port=5432, dbname='openclaw', user='openclaw', password='openclaw123')
DB_FACTORY = dict(host='193.124.112.222', port=49002, dbname='factory',
                  user='roman_ai_readonly', password='Bo37H#Kla8dl0chQnL0@3jSlcY', connect_timeout=10)
```

Заменить на:

```python
DB_MAIN = dict(host='localhost', port=5432, dbname='openclaw', user='openclaw', password='openclaw123')
```

И найти на строках 47-48:

```python
def get_factory_db():
    return psycopg2.connect(**DB_FACTORY)
```

Удалить функцию целиком (2 строки).

- [ ] **Step 2: Переписать get_active_accounts()**

Найти блок начиная со строки 50:

```python
def get_active_accounts(platform_filter: str = None, account_filter: str = None) -> List[Dict]:
    try:
        conn = get_factory_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        q = """
            SELECT fia.username AS account,
                   fia.platform,
                   dn.device_id  AS device_serial,
                   rp.adb::int   AS adb_port,
                   dn.raspberry  AS raspberry_number,
                   ''            AS project
            FROM factory_inst_accounts fia
            JOIN pack_accounts pa  ON pa.id = fia.pack_id
            JOIN device_numbers dn ON dn.id = pa.device_num_id
            JOIN raspberry_port rp ON rp.raspberry_number = dn.raspberry
            WHERE fia.active = true AND dn.active = true
        """
```

Заменить на:

```python
def get_active_accounts(platform_filter: str = None, account_filter: str = None) -> List[Dict]:
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        q = """
            SELECT fia.username AS account,
                   fia.platform,
                   dn.device_id  AS device_serial,
                   rp.adb::int   AS adb_port,
                   dn.raspberry  AS raspberry_number,
                   COALESCE(vp.project, '') AS project
            FROM factory_inst_accounts fia
            JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
            JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id
            JOIN raspberry_port rp         ON rp.raspberry_number = dn.raspberry
            LEFT JOIN validator_projects vp ON vp.id = fpa.project_id
            WHERE fia.active = true AND dn.active = true
        """
```

- [ ] **Step 3: Smoke — import + run**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "
from analytics_collector_v2 import get_active_accounts
accounts = get_active_accounts()
print(f'v2 got {len(accounts)} accounts')
print(accounts[0] if accounts else 'EMPTY')
"
```

Ожидаем: число > 0.

- [ ] **Step 4: Подтвердить чистоту**

```bash
grep -n "193\.124\|49002\|DB_FACTORY\|get_factory_db" /root/.openclaw/workspace-genri/autowarm/analytics_collector_v2.py
```

Ожидаем: пустой вывод.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add analytics_collector_v2.py
git commit -m "$(cat <<'EOF'
feat(analytics): collector_v2 reads accounts from local openclaw

Same migration as v1: pack_accounts → factory_pack_accounts,
device_numbers → factory_device_numbers, +validator_projects join
for project label. Drops DB_FACTORY const + get_factory_db().

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T5 — Ф3: instagram_archiver.py → local

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/instagram_archiver.py:511-528`

- [ ] **Step 1: Удалить FACTORY const + переписать query**

В `/root/.openclaw/workspace-genri/autowarm/instagram_archiver.py` найти блок (строки 511-528):

```python
    # Получаем ADB данные из factory
    import psycopg2 as pg2
    FACTORY = dict(host='193.124.112.222', port=49002, dbname='factory',
                   user='roman_ai_readonly', password='Bo37H#Kla8dl0chQnL0@3jSlcY',
                   connect_timeout=10)
    try:
        fc = pg2.connect(**FACTORY)
        fcu = fc.cursor()
        fcu.execute("""
            SELECT rp.host, rp.adb
            FROM factory_inst_accounts fia
            JOIN pack_accounts pa ON pa.id = fia.pack_id
            JOIN device_numbers dn ON dn.id = pa.device_num_id
            JOIN raspberry_port rp ON rp.raspberry_number = dn.raspberry
            WHERE fia.username = %s AND fia.active = true
            LIMIT 1
        """, (account,))
        r = fcu.fetchone()
        fc.close()
```

Заменить на (используем уже импортированный `psycopg2` + локальный `DB_CONFIG` из этого файла):

```python
    # Получаем ADB данные из локальной БД
    try:
        fc = psycopg2.connect(**DB_CONFIG)
        fcu = fc.cursor()
        fcu.execute("""
            SELECT rp.host, rp.adb
            FROM factory_inst_accounts fia
            JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
            JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id
            JOIN raspberry_port rp         ON rp.raspberry_number = dn.raspberry
            WHERE fia.username = %s AND fia.active = true
            LIMIT 1
        """, (account,))
        r = fcu.fetchone()
        fc.close()
```

- [ ] **Step 2: Подтвердить что DB_CONFIG доступен**

```bash
grep -n "^DB_CONFIG\|^from .* import .* DB_CONFIG\|^import" /root/.openclaw/workspace-genri/autowarm/instagram_archiver.py | head -10
```

Если `DB_CONFIG` не определён в файле и не импортирован — добавить импорт `from archiver_base import DB_CONFIG` в начале файла.

- [ ] **Step 3: Smoke — import**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import instagram_archiver; print('ok')"
```

- [ ] **Step 4: Подтвердить чистоту**

```bash
grep -n "193\.124\|49002\|pg2\.connect" /root/.openclaw/workspace-genri/autowarm/instagram_archiver.py
```

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add instagram_archiver.py
git commit -m "feat(archiver): instagram_archiver reads ADB metadata from local openclaw

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T6 — Ф3: archive_scheduler.py → local

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/archive_scheduler.py:7-15, 41-58`

- [ ] **Step 1: Заменить FACTORY на DB_CONFIG**

В `/root/.openclaw/workspace-genri/autowarm/archive_scheduler.py` найти строки 12-13:

```python
FACTORY = dict(host='193.124.112.222', port=49002, dbname='factory',
               user='roman_ai_readonly', password='Bo37H#Kla8dl0chQnL0@3jSlcY', connect_timeout=10)
```

Заменить на:

```python
DB_CONFIG = dict(host='localhost', port=5432, dbname='openclaw', user='openclaw', password='openclaw123')
```

- [ ] **Step 2: Переписать SELECT в main()**

Найти блок (строки 41-58):

```python
    conn = psycopg2.connect(**FACTORY)
    cur  = conn.cursor()
    cur.execute("""
        SELECT fia.username, dn.device_id, fia.platform
        FROM factory_inst_accounts fia
        JOIN pack_accounts pa ON pa.id = fia.pack_id
        JOIN device_numbers dn ON dn.id = pa.device_num_id
        JOIN raspberry_port rp ON rp.raspberry_number = dn.raspberry
        WHERE fia.active = true
          AND fia.platform = ANY(%s)
          AND dn.device_id IS NOT NULL
          AND rp.host IS NOT NULL
        ORDER BY fia.platform, fia.username
    """, (PLATFORMS,))
```

Заменить на:

```python
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()
    cur.execute("""
        SELECT fia.username, dn.device_id, fia.platform
        FROM factory_inst_accounts fia
        JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
        JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id
        JOIN raspberry_port rp         ON rp.raspberry_number = dn.raspberry
        WHERE fia.active = true
          AND fia.platform = ANY(%s)
          AND dn.device_id IS NOT NULL
          AND rp.host IS NOT NULL
        ORDER BY fia.platform, fia.username
    """, (PLATFORMS,))
```

- [ ] **Step 3: Smoke — dry-run main**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "
import archive_scheduler
import psycopg2
conn = psycopg2.connect(**archive_scheduler.DB_CONFIG)
cur = conn.cursor()
cur.execute('''
    SELECT COUNT(*)
    FROM factory_inst_accounts fia
    JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
    JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id
    JOIN raspberry_port rp ON rp.raspberry_number = dn.raspberry
    WHERE fia.active = true AND fia.platform = ANY(%s)
''', (['instagram','tiktok','youtube'],))
print('Active accounts:', cur.fetchone()[0])
"
```

Ожидаем: число > 0.

- [ ] **Step 4: Подтвердить чистоту**

```bash
grep -n "193\.124\|49002\|FACTORY" /root/.openclaw/workspace-genri/autowarm/archive_scheduler.py
```

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add archive_scheduler.py
git commit -m "feat(archiver): archive_scheduler reads accounts from local openclaw

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T7 — Ф3: archiver_base.py + tiktok_archiver.py + youtube_archiver.py

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/archiver_base.py:11-12`
- Modify: `/root/.openclaw/workspace-genri/autowarm/tiktok_archiver.py:11, 278-...`
- Modify: `/root/.openclaw/workspace-genri/autowarm/youtube_archiver.py:12, 361-...`

Эти 3 файла связаны: `tiktok_archiver` и `youtube_archiver` импортируют `FACTORY` из `archiver_base`. Все 3 правятся в одном коммите.

- [ ] **Step 1: Прочитать query в наследниках**

```bash
sed -n '275,300p' /root/.openclaw/workspace-genri/autowarm/tiktok_archiver.py
sed -n '358,385p' /root/.openclaw/workspace-genri/autowarm/youtube_archiver.py
```

Записать какие SQL они выполняют через `fc = pg2.connect(**FACTORY)` — обычно та же query что в `instagram_archiver.py:520-528`.

- [ ] **Step 2: Удалить FACTORY из archiver_base.py**

В `/root/.openclaw/workspace-genri/autowarm/archiver_base.py` найти строки 11-12:

```python
FACTORY   = dict(host='193.124.112.222', port=49002, dbname='factory',
                 user='roman_ai_readonly', password='Bo37H#Kla8dl0chQnL0@3jSlcY', connect_timeout=10)
```

Удалить целиком (2 строки).

- [ ] **Step 3: Поправить import в tiktok_archiver.py**

В `/root/.openclaw/workspace-genri/autowarm/tiktok_archiver.py` строка 11:

```python
from archiver_base import BaseArchiver, ADB, parse_days_ago, parse_views, human_sleep, long_sleep, DB_CONFIG, FACTORY
```

Заменить на (убрать `, FACTORY`):

```python
from archiver_base import BaseArchiver, ADB, parse_days_ago, parse_views, human_sleep, long_sleep, DB_CONFIG
```

- [ ] **Step 4: Переписать query в tiktok_archiver.py**

Найти блок начиная с `fc = pg2.connect(**FACTORY)` (около строки 278). Заменить на `fc = psycopg2.connect(**DB_CONFIG)`. В SQL поменять (используя Code Mapping):
- `pack_accounts pa` → `factory_pack_accounts fpa`
- `pa.id`, `pa.device_num_id` → `fpa.id`, `fpa.device_num_id`
- `device_numbers dn` → `factory_device_numbers dn`

И убрать `import psycopg2 as pg2` (если pg2 более нигде не используется в файле — проверить grep).

- [ ] **Step 5: То же для youtube_archiver.py** (строка 12, строка 361)

То же что и Step 3-4 — для `youtube_archiver.py`.

- [ ] **Step 6: Smoke — import всех трёх**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import archiver_base; import tiktok_archiver; import youtube_archiver; print('ok')"
```

- [ ] **Step 7: Подтвердить чистоту**

```bash
grep -n "193\.124\|49002\|FACTORY\|pg2" /root/.openclaw/workspace-genri/autowarm/archiver_base.py /root/.openclaw/workspace-genri/autowarm/tiktok_archiver.py /root/.openclaw/workspace-genri/autowarm/youtube_archiver.py
```

- [ ] **Step 8: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add archiver_base.py tiktok_archiver.py youtube_archiver.py
git commit -m "feat(archiver): drop FACTORY const from archiver_base, switch tt/yt to local

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T8 — Ф3: social_audit.py → local

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/social_audit.py:78-82, 95-110, 126-132, 148-160`

- [ ] **Step 1: Удалить DIST_DB_CONFIG**

В `/root/.openclaw/workspace-genri/autowarm/social_audit.py` найти строки 78-82:

```python
DIST_DB_CONFIG = {
    'host': '193.124.112.222', 'port': 49002,
    'dbname': 'factory', 'user': 'roman_ai_readonly',
    'password': 'Bo37H#Kla8dl0chQnL0@3jSlcY', 'connect_timeout': 10
}
```

Удалить целиком (5 строк).

- [ ] **Step 2: Подтвердить наличие DB_CONFIG в файле**

```bash
grep -n "^DB_CONFIG\|^from .* import .* DB_CONFIG" /root/.openclaw/workspace-genri/autowarm/social_audit.py
```

Если нет — добавить после удалённого блока:

```python
DB_CONFIG = dict(host='localhost', port=5432, dbname='openclaw', user='openclaw', password='openclaw123')
```

- [ ] **Step 3: Заменить connect-вызовы**

Глобальный поиск-замена в файле:

```bash
sed -i 's|psycopg2\.connect(\*\*DIST_DB_CONFIG)|psycopg2.connect(**DB_CONFIG)|g' /root/.openclaw/workspace-genri/autowarm/social_audit.py
```

- [ ] **Step 4: Переписать query #1 (около строки 95)**

Найти блок:

```python
        cur.execute("""
            SELECT
                dn.device_id  AS device_serial,
                rp.adb        AS adb_port,
                fp.api_name   AS project
            FROM factory_inst_accounts fia
            JOIN pack_accounts pa    ON pa.id = fia.pack_id
            JOIN factory_projects fp ON fp.id = pa.project_id
            JOIN device_numbers dn   ON dn.id = pa.device_num_id
            JOIN raspberry_port rp   ON rp.raspberry_number = dn.raspberry
            WHERE LOWER(fia.username) = LOWER(%s)
              AND fia.platform = %s
              AND fia.active = true
              AND dn.active = true
            LIMIT 1
        """, (account, platform))
```

Заменить на:

```python
        cur.execute("""
            SELECT
                dn.device_id  AS device_serial,
                rp.adb        AS adb_port,
                vp.project    AS project
            FROM factory_inst_accounts fia
            JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
            JOIN validator_projects vp     ON vp.id = fpa.project_id
            JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id
            JOIN raspberry_port rp         ON rp.raspberry_number = dn.raspberry
            WHERE LOWER(fia.username) = LOWER(%s)
              AND fia.platform = %s
              AND fia.active = true
              AND dn.active = true
            LIMIT 1
        """, (account, platform))
```

- [ ] **Step 5: Переписать query #2 (около строки 126)**

Найти блок:

```python
        cur.execute("""
            SELECT DISTINCT dn.device_id, rp.adb
            FROM device_numbers dn
            JOIN raspberry_port rp ON rp.raspberry_number = dn.raspberry
            WHERE dn.active = true
            LIMIT 1
        """)
```

Заменить `device_numbers dn` на `factory_device_numbers dn`.

- [ ] **Step 6: Переписать query #3 (около строки 148)**

Найти блок:

```python
        cur.execute("""
            SELECT fia.username, fia.platform, dn.device_id, rp.adb
            FROM factory_inst_accounts fia
            JOIN pack_accounts pa    ON pa.id = fia.pack_id
            JOIN factory_projects fp ON fp.id = pa.project_id
            JOIN device_numbers dn   ON dn.id = pa.device_num_id
            JOIN raspberry_port rp   ON rp.raspberry_number = dn.raspberry
            WHERE LOWER(fp.api_name) LIKE LOWER(%s)
              AND fia.active = true
              AND dn.active = true
              AND fia.platform IN ('instagram', 'tiktok', 'youtube')
```

Заменить на:

```python
        cur.execute("""
            SELECT fia.username, fia.platform, dn.device_id, rp.adb
            FROM factory_inst_accounts fia
            JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
            JOIN validator_projects vp     ON vp.id = fpa.project_id
            JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id
            JOIN raspberry_port rp         ON rp.raspberry_number = dn.raspberry
            WHERE LOWER(vp.project) LIKE LOWER(%s)
              AND fia.active = true
              AND dn.active = true
              AND fia.platform IN ('instagram', 'tiktok', 'youtube')
```

- [ ] **Step 7: Smoke — import**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import social_audit; print('ok')"
```

- [ ] **Step 8: Подтвердить чистоту**

```bash
grep -n "193\.124\|49002\|DIST_DB_CONFIG\|pack_accounts \|device_numbers \|factory_projects" /root/.openclaw/workspace-genri/autowarm/social_audit.py
```

- [ ] **Step 9: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add social_audit.py
git commit -m "feat(audit): social_audit reads from local openclaw

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T9 — Ф3: profile_inspector.py → local

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/profile_inspector.py:62-66, 77-91, 107-113`

Аналогично T8, но проще (2 query).

- [ ] **Step 1: Удалить DIST_DB_CONFIG (строки 62-66)**

Удалить блок:

```python
DIST_DB_CONFIG = {
    'host': '193.124.112.222', 'port': 49002,
    'dbname': 'factory', 'user': 'roman_ai_readonly',
    'password': 'Bo37H#Kla8dl0chQnL0@3jSlcY', 'connect_timeout': 10
}
```

- [ ] **Step 2: Подтвердить или добавить DB_CONFIG**

```bash
grep -n "^DB_CONFIG\|^from .* import .* DB_CONFIG" /root/.openclaw/workspace-genri/autowarm/profile_inspector.py
```

Если нет — добавить:

```python
DB_CONFIG = dict(host='localhost', port=5432, dbname='openclaw', user='openclaw', password='openclaw123')
```

- [ ] **Step 3: Заменить connect**

```bash
sed -i 's|psycopg2\.connect(\*\*DIST_DB_CONFIG)|psycopg2.connect(**DB_CONFIG)|g' /root/.openclaw/workspace-genri/autowarm/profile_inspector.py
```

- [ ] **Step 4: Переписать query #1 (строки 77-91)**

Найти:

```python
        cur.execute("""
            SELECT
                dn.device_id  AS device_serial,
                rp.adb        AS adb_port,
                fp.api_name   AS project
            FROM factory_inst_accounts fia
            JOIN pack_accounts pa    ON pa.id = fia.pack_id
            JOIN factory_projects fp ON fp.id = pa.project_id
            JOIN device_numbers dn   ON dn.id = pa.device_num_id
            JOIN raspberry_port rp   ON rp.raspberry_number = dn.raspberry
            WHERE LOWER(fia.username) = LOWER(%s)
              AND fia.active = true
              AND dn.active = true
            LIMIT 1
        """, (account,))
```

Заменить на:

```python
        cur.execute("""
            SELECT
                dn.device_id  AS device_serial,
                rp.adb        AS adb_port,
                vp.project    AS project
            FROM factory_inst_accounts fia
            JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
            JOIN validator_projects vp     ON vp.id = fpa.project_id
            JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id
            JOIN raspberry_port rp         ON rp.raspberry_number = dn.raspberry
            WHERE LOWER(fia.username) = LOWER(%s)
              AND fia.active = true
              AND dn.active = true
            LIMIT 1
        """, (account,))
```

- [ ] **Step 5: Переписать query #2 (строки 107-113)**

Найти:

```python
        cur.execute("""
            SELECT DISTINCT dn.device_id, rp.adb
            FROM device_numbers dn
            JOIN raspberry_port rp ON rp.raspberry_number = dn.raspberry
            WHERE dn.active = true
            LIMIT 1
        """)
```

Заменить `device_numbers dn` на `factory_device_numbers dn`.

- [ ] **Step 6: Smoke + чистота**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import profile_inspector; print('ok')"
grep -n "193\.124\|49002\|DIST_DB_CONFIG\|pack_accounts \|factory_projects\|device_numbers " profile_inspector.py
```

Чистота: пустой вывод.

- [ ] **Step 7: Commit**

```bash
git add profile_inspector.py
git commit -m "feat(inspector): profile_inspector reads from local openclaw

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T10 — Ф3: whatsapp_warmer.py → local

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/whatsapp_warmer.py:948-964`

Только функция `scan_all_phones()` (на L948+) использует remote — остальной код уже на local. Главная задача — заменить inline factory connection и `device_numbers` → `factory_device_numbers`.

- [ ] **Step 1: Прочитать актуальный блок**

```bash
sed -n '945,985p' /root/.openclaw/workspace-genri/autowarm/whatsapp_warmer.py
```

- [ ] **Step 2: Заменить factory connection на DB_CONFIG**

В `/root/.openclaw/workspace-genri/autowarm/whatsapp_warmer.py` найти блок (строки 948-964):

```python
def scan_all_phones():
    print("Scanning phone numbers from all devices...")
    try:
        import psycopg2 as pg
        factory_db = pg.connect(
            host='193.124.112.222', port=49002, dbname='factory',
            user='roman_ai_readonly', password='Bo37H#Kla8dl0chQnL0@3jSlcY'
        )
        factory_db.autocommit = True
        with factory_db.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT dn.device_id, rp.adb as adb_port
                FROM device_numbers dn
                JOIN raspberry_port rp ON rp.raspberry_number = dn.raspberry
                WHERE dn.active = true
                LIMIT 173
            """)
            devices = cur.fetchall()
        factory_db.close()
    except Exception as e:
        print(f"Factory DB error: {e}")
        return
```

Заменить на:

```python
def scan_all_phones():
    print("Scanning phone numbers from all devices...")
    try:
        local_db = psycopg2.connect(**DB_CONFIG)
        local_db.autocommit = True
        with local_db.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT dn.device_id, rp.adb as adb_port
                FROM factory_device_numbers dn
                JOIN raspberry_port rp ON rp.raspberry_number = dn.raspberry
                WHERE dn.active = true
                LIMIT 173
            """)
            devices = cur.fetchall()
        local_db.close()
    except Exception as e:
        print(f"Local DB error: {e}")
        return
```

- [ ] **Step 3: Smoke + чистота**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import whatsapp_warmer; print('ok')"
grep -n "193\.124\|49002\|factory_db\|FROM device_numbers" /root/.openclaw/workspace-genri/autowarm/whatsapp_warmer.py
```

- [ ] **Step 4: Commit**

```bash
git add whatsapp_warmer.py
git commit -m "feat(whatsapp): scan_all_phones uses local openclaw

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T11 — Ф3: warmer.py — удалить мёртвый DIST_DB_CONFIG

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/warmer.py:78-84`

`warmer.py` уже использует local БД для всех queries. Осталась только мёртвая константа `DIST_DB_CONFIG` без caller'ов.

- [ ] **Step 1: Подтвердить что DIST_DB_CONFIG не используется в файле**

```bash
grep -nE "DIST_DB_CONFIG" /root/.openclaw/workspace-genri/autowarm/warmer.py
```

Ожидаем только определение на L78 и **никаких** `connect(**DIST_DB_CONFIG)`. Если есть — STOP, файл сложнее, требует расширенного task'а.

- [ ] **Step 2: Удалить блок**

В `/root/.openclaw/workspace-genri/autowarm/warmer.py` найти строки 78-84:

```python
DIST_DB_CONFIG = {
    'host': '193.124.112.222',
    'port': 49002,
    'dbname': 'factory',
    'user': 'roman_ai_readonly',
    'password': 'Bo37H#Kla8dl0chQnL0@3jSlcY'
}
```

Удалить целиком (7 строк).

- [ ] **Step 3: Smoke + чистота**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "import warmer; print('ok')"
grep -n "193\.124\|49002\|DIST_DB_CONFIG" /root/.openclaw/workspace-genri/autowarm/warmer.py
```

- [ ] **Step 4: Commit**

```bash
git add warmer.py
git commit -m "feat(warmer): drop dead DIST_DB_CONFIG (warmer already on local)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task T12 — Ф4: удалить dead-файлы

**Files:**
- Delete: `/root/.openclaw/workspace-genri/autowarm/telegram_warmer.py`
- Delete: `/root/.openclaw/workspace-genri/autowarm/wa_register_all.py`
- Delete: `/root/.openclaw/workspace-genri/autowarm/run_retry_audit.py`

- [ ] **Step 1: Pre-flight — подтвердить отсутствие caller'ов**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git grep -nE "telegram_warmer|wa_register_all|run_retry_audit" -- ':!telegram_warmer.py' ':!wa_register_all.py' ':!run_retry_audit.py'
```

Ожидаем: пустой вывод. Если есть hits — STOP, файлы не dead, нужен анализ.

- [ ] **Step 2: Удалить файлы**

```bash
cd /root/.openclaw/workspace-genri/autowarm
rm telegram_warmer.py wa_register_all.py run_retry_audit.py
```

- [ ] **Step 3: PM2 sanity**

```bash
sudo pm2 list | grep -E "online|status" | head
```

Ожидаем: все процессы остаются `online`.

- [ ] **Step 4: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add -A
git commit -m "$(cat <<'EOF'
chore: remove dead remote-factory files

- telegram_warmer.py: no callers, last-modified months ago
- wa_register_all.py: no callers (whatsapp_warmer covers production path)
- run_retry_audit.py: no callers, ad-hoc audit replaced

Все три читают/пишут factory@193.124.112.222:49002 напрямую и являются
последними держателями этой зависимости в репо. Их удаление завершает
phase-out remote factory в autowarm.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T13 — autowarm: push ветку, мержить в main

**Files:** none (git operations)

- [ ] **Step 1: Push feature branch**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git push -u origin feat/remote-factory-phaseout-20260430
```

- [ ] **Step 2: Создать PR в GenGo2/delivery-contenthunter**

```bash
gh pr create --title "Remote factory@193.124.112.222 phase-out (analytics + autowarm)" --body "$(cat <<'EOF'
## Summary
Полный отказ autowarm от внешней БД factory@193.124.112.222:49002. 11 атомарных коммитов:

- T3-T4: analytics_collector.py + v2 → local openclaw
- T5: instagram_archiver.py → local
- T6: archive_scheduler.py → local
- T7: archiver_base.py + tiktok_archiver.py + youtube_archiver.py → local
- T8: social_audit.py → local
- T9: profile_inspector.py → local
- T10: whatsapp_warmer.py → local
- T11: warmer.py — drop dead DIST_DB_CONFIG
- T12: удаление dead-файлов (telegram_warmer, wa_register_all, run_retry_audit)

Маппинг таблиц: pack_accounts → factory_pack_accounts, device_numbers → factory_device_numbers, factory_projects (api_name) → validator_projects (project).

Part of remote factory phase-out — design at `rmbrmv/contenthunter:.ai-factory/plans/2026-04-30-remote-factory-phaseout-design.md`.

## Test plan
- [ ] `git grep "193\.124\.112\.222\|49002"` в репо — пусто (модулo *.bak/*.md)
- [ ] `pm2 logs autowarm --lines 200` после рестарта — нет ConnectionError/TimeoutError по 193.124
- [ ] `account_audience_snapshots` начинает наполняться после следующего scheduler-тика 00:00 UTC
- [ ] `pm2 list` все процессы online

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Дождаться review, мержить**

После approve:

```bash
cd /root/.openclaw/workspace-genri/autowarm
gh pr merge --merge  # plain merge, не squash — атомарность коммитов важна для rollback
git checkout main
git pull
```

- [ ] **Step 4: Verify PM2 cwd после мержа** (`feedback_pm2_dump_path_drift.md`)

```bash
sudo pm2 describe autowarm | grep "exec cwd"
sudo pm2 list | head
```

Ожидаем: `exec cwd: /root/.openclaw/workspace-genri/autowarm`. Все online.

Если cwd сменился — `delete + start from ecosystem config`:

```bash
sudo pm2 delete autowarm
cd /root/.openclaw/workspace-genri/autowarm
sudo pm2 start ecosystem.config.js --only autowarm
sudo pm2 save
```

- [ ] **Step 5: Smoke — проверить что 193.124 ушёл**

```bash
sleep 30
ss -tn dst 193.124.112.222:49002 | wc -l
sudo pm2 logs autowarm --lines 200 --nostream | grep -E "193\.|49002|ConnectionError|TimeoutError" || echo "CLEAN"
```

Ожидаем: TCP — 0, log — `CLEAN`.

---

### Task T14 — Ф5: финальный аудит + evidence

**Files:**
- Create: `/home/claude-user/contenthunter/.ai-factory/evidence/2026-04-30-remote-factory-phaseout-evidence.md`

- [ ] **Step 1: Cross-repo audit grep**

```bash
echo "=== validator-contenthunter ==="
cd /tmp/validator-fix
git grep -nE "193\.124\.112\.222|49002" -- ':!*.md' ':!docs/'
echo ""
echo "=== autowarm prod ==="
cd /root/.openclaw/workspace-genri/autowarm
git grep -nE "193\.124\.112\.222|49002" -- ':!*.md' ':!docs/' ':!evidence/' ':!*.bak*'
echo ""
echo "=== contenthunter (этот репо) — кроме design/evidence ==="
cd /home/claude-user/contenthunter
git grep -nE "193\.124\.112\.222|49002" -- ':!.ai-factory/plans/2026-04-30-remote-factory-phaseout-*' ':!.ai-factory/evidence/' ':!*.md'
```

Ожидаем: пустой вывод во всех трёх блоках.

- [ ] **Step 2: TCP-трафик**

```bash
ss -tn dst 193.124.112.222:49002
```

Ожидаем: пусто.

- [ ] **Step 3: PM2 logs**

```bash
sudo pm2 logs --lines 500 --nostream | grep -E "193\.|49002|ConnectionError.*49002|TimeoutError.*193" | head
```

Ожидаем: пусто.

- [ ] **Step 4: Cron status**

```bash
sudo crontab -l -u root | grep sync_sources
```

Ожидаем: только закомментированная строка от T1 (или вообще нет если убрали).

- [ ] **Step 5: Account audience snapshots — оживление**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT MAX(snapshot_date), COUNT(*) FILTER (WHERE snapshot_date > CURRENT_DATE - 1) AS last_24h
FROM account_audience_snapshots;
"
```

Ожидаем: `MAX(snapshot_date) = CURRENT_DATE` (если прошло 00:00 UTC после Ф2), `last_24h > 0`.

- [ ] **Step 6: Записать evidence**

Создать `/home/claude-user/contenthunter/.ai-factory/evidence/2026-04-30-remote-factory-phaseout-evidence.md` со структурой:

```markdown
# Remote Factory DB Phase-Out — Evidence

**Дата завершения:** 2026-MM-DD
**Дизайн:** `.ai-factory/plans/2026-04-30-remote-factory-phaseout-design.md`
**План:** `.ai-factory/plans/2026-04-30-remote-factory-phaseout-implementation.md`

## Коммиты

- **validator-contenthunter** PR #N (`feat/remove-sync-sources-20260430`):
  - <SHA1> feat: remove legacy factory sync bridge and /sources page
- **delivery-contenthunter / autowarm prod** PR #N (`feat/remote-factory-phaseout-20260430`):
  - <SHA T3..T12> (11 коммитов)
- **rmbrmv/contenthunter** (этот репо, ветка `design/remote-factory-phaseout-20260430`):
  - <SHA design>
  - <SHA evidence>

## Cron status

```
$ sudo crontab -l -u root | grep sync_sources
# DISABLED 2026-04-30 phase-out: */15 * * * * python3 /root/.openclaw/workspace-genri/validator/sync_sources.py >> /var/log/validator_sync.log 2>&1
```

## Cross-repo grep (после)

```
=== validator-contenthunter ===
(пусто)

=== autowarm prod ===
(пусто)
```

## TCP

```
$ ss -tn dst 193.124.112.222:49002
(пусто)
```

## PM2 logs

```
$ sudo pm2 logs --lines 500 --nostream | grep -E "193\.|49002"
(пусто)
```

## Side-effect: account_audience_snapshots оживлена

| Метрика | До (baseline) | После |
|---|---|---|
| MAX(snapshot_date) | <baseline> | <new> |
| count за 24ч | 0 | <N> |

## Затронутые файлы (Ф2-Ф4)

Modified (autowarm):
- analytics_collector.py
- analytics_collector_v2.py
- instagram_archiver.py
- archive_scheduler.py
- archiver_base.py
- tiktok_archiver.py
- youtube_archiver.py
- social_audit.py
- profile_inspector.py
- whatsapp_warmer.py
- warmer.py

Deleted (autowarm):
- telegram_warmer.py
- wa_register_all.py
- run_retry_audit.py

Modified (validator):
- backend/src/main.py

Deleted (validator):
- validator/sync_sources.py
- backend/src/routers/sources.py
- frontend/src/pages/client/SourcesPage.vue
- (route в frontend/src/router/index.ts)
```

Заменить плейсхолдеры `<SHA...>`, `<baseline>`, `<new>`, `<N>`, дату завершения на актуальные значения из шагов 1-5.

- [ ] **Step 7: Commit evidence**

```bash
cd /home/claude-user/contenthunter
git add .ai-factory/evidence/2026-04-30-remote-factory-phaseout-evidence.md
git commit -m "$(cat <<'EOF'
docs(evidence): remote factory@193.124.112.222 phase-out completed

Все 6 фаз дизайна выполнены: cron sync_sources заморожен (Ф0), мост и
/sources страница удалены (Ф1), 11 файлов autowarm переведены на local
openclaw (Ф2-Ф4). Cross-repo grep чистый, TCP к 193.124 — нет, PM2 logs
без ConnectionError. Side-effect: account_audience_snapshots ожила.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin design/remote-factory-phaseout-20260430
gh pr create --title "docs: remote factory phase-out design + evidence" --body "Дизайн (закоммичен ранее) + evidence по завершении. Меняет только .ai-factory/."
```

---

### Task T15 — Memory update

**Files:**
- Create: `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_remote_factory_phaseout.md`
- Modify: `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/MEMORY.md`

- [ ] **Step 1: Создать memory entry**

Файл `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/project_remote_factory_phaseout.md`:

```markdown
---
name: Remote factory@193.124.112.222 phase-out — DONE
description: Старая legacy-БД master-системы полностью отключена от нового сервиса 2026-04-30. Любые ссылки на 193.124.112.222 / 49002 в новом коде = баг.
type: project
---

Старая мастер-БД factory@193.124.112.222:49002 (master-system предыдущего сервиса) полностью отключена от contenthunter.ru на 2026-04-30:

- validator/sync_sources.py — удалён (мост cron */15 мин)
- /api/sources router + SourcesPage.vue (Журнал исходников) — удалены
- 11 файлов autowarm переведены на local openclaw: analytics_collector ×2, instagram/tiktok/youtube_archiver, archive_scheduler, archiver_base (FACTORY const dropped), social_audit, profile_inspector, whatsapp_warmer (scan_all_phones), warmer (dead const)
- 3 dead-файла удалены: telegram_warmer.py, wa_register_all.py, run_retry_audit.py

Маппинг таблиц remote→local (canonical):
- pack_accounts → factory_pack_accounts (alias обычно меняется pa → fpa)
- device_numbers → factory_device_numbers
- factory_projects (fp.api_name) → validator_projects (vp.project)

Локальная таблица factory.contentlab_videos_upload оставлена как архив (1537 записей) — не пополняется. Дроп — отдельным решением.

**Why:** старая система продолжает работать в ручном режиме у партнёров, но новый сервис должен быть от неё независим. Любая привязка к 193.124 = риск регресса.

**How to apply:** при появлении 193.124.112.222 / 49002 в новом коде — это баг, удалять. Любые JOIN'ы в SQL должны использовать factory_pack_accounts/factory_device_numbers/validator_projects, а не legacy-имена. Side-effect фикса: account_audience_snapshots ожила (была пуста с момента деплоя collector).
```

- [ ] **Step 2: Добавить в MEMORY.md**

Открыть `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/MEMORY.md` и добавить строку (вставить в логичное место рядом с `account_packages deprecated`):

```markdown
- [Remote factory phase-out — DONE](project_remote_factory_phaseout.md) — 193.124.112.222 отключён 2026-04-30; mapping pack_accounts→factory_pack_accounts, device_numbers→factory_device_numbers, factory_projects→validator_projects
```

---

## Self-Review (skill checklist)

- [x] **Spec coverage:** Все 6 фаз дизайна (Ф0-Ф5) покрыты задачами T1-T14. Acceptance criteria из spec проверяются в T0 (baseline) и T14 (после).
- [x] **Placeholder scan:** Никаких "TBD"/"TODO"/"add validation" — все шаги имеют конкретный код или команду. Плейсхолдеры в evidence-шаблоне T14 (`<SHA>`, `<baseline>`) — это ожидаемые значения для заполнения по факту, не неполнота плана.
- [x] **Type consistency:** SQL-маппинг применяется единообразно во всех task'ах согласно Code Mapping секции. `fpa` — alias для `factory_pack_accounts` везде; `vp` — для `validator_projects`. Никаких рассогласований.

## Execution Handoff

Plan complete and saved to `.ai-factory/plans/2026-04-30-remote-factory-phaseout-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — диспатчу свежий subagent на каждую задачу через `subagent-driven-development`, между задачами я review-первая ступень. Более быстрая итерация, лучше для длинного плана с 14 задачами.

**2. Inline Execution** — выполняю задачи в текущей сессии через `executing-plans`, batch с чекпоинтами для ревью.

Которым путём идём?
