# Client `/accounts` page — пустой список по всем проектам

**Created:** 2026-04-24
**Branch:** работаем в текущей ветке `feature/farming-testbench-phone171` (фикс — в другом репо, см. ниже)
**Owner repo для фикса:** `GenGo2/validator-contenthunter` (deploy: `/root/.openclaw/workspace-genri/validator/`, branch `main`, post-commit auto-push)

---

## Settings

- **Tests:** да — один smoke-файл против live DB (соглашение проекта; см. memory `feedback_validator_upload_rules.md` + `test_fixes_2026_04_20.py`).
- **Logging:** verbose в `accounts_service.py` (DEBUG для project_id/api_name resolution, INFO для row count, WARNING для unknown project).
- **Docs:** да — короткий evidence-файл в `.ai-factory/evidence/`.
- **Roadmap linkage:** none (roadmap не сконфигурирован в этом проекте).

## Roadmap Linkage

Milestone: "none"
Rationale: Roadmap артефакт в проекте не используется.

---

## Symptom (отчёт пользователя 2026-04-24)

`https://client.contenthunter.ru/accounts` показывает пустой список аккаунтов **по любому проекту, под любой ролью**. По данным БД аккаунты есть (1241 строка в `factory_inst_accounts`).

## Discovery (что подтвердил рекон)

**Цепочка вызова:** SPA `AccountsPage` → `GET /api/accounts` → `routers/accounts.py::list_accounts` → `services/accounts_service.py::get_project_accounts` → SQL.

**Корневая причина — строка 66 в `accounts_service.py`:**
```sql
JOIN account_packages ap ON ap.id = fia.pack_id
```
Таблица `account_packages` была **DROP'нута 2026-04-22** в рамках консолидации factory (см. memory `project_account_packages_deprecation`, autowarm step 3, commit `5c6c432`). Validator не был обновлён.

**Воспроизведение на живой БД:**
```
$ psql -c "SELECT count(*) FROM factory_inst_accounts fia JOIN account_packages ap ON ap.id = fia.pack_id;"
ERROR:  relation "account_packages" does not exist
```

Запрос крашится → FastAPI возвращает 500 (или handler глотает в `accounts: []` через `?? []` на фронте) → пустой список на UI для всех проектов независимо от auth/project_id фильтра (ошибка случается **до** применения фильтра).

**Схема замены подтверждена:**
| Старое (`account_packages`) | Новое (`factory_pack_accounts`) |
|---|---|
| `id` | `id` ✅ |
| `project` (text) | `project_id` (int → FK на `validator_projects.id`) |
| `start_date` | `start_date` ✅ |
| `pack_id` (на `factory_inst_accounts.pack_id`) | `id` ✅ |

Фиксированный JOIN отдаёт реальные данные:
```
 id | project          | accounts
----+------------------+----------
  9 | Relisme          |       57
 83 | Септизим         |       47
 16 | Джинсы Шелковица |       47
 12 | Symmetry         |       43
 ...
```

**Не root cause, исключено разведкой:** auth (`_resolve_project_id` корректен), фронт (`AccountsPage` корректно читает `data.accounts`), JWT/headers, остальные LATERAL JOIN'ы (`account_audience_snapshots`, `factory_inst_reels_stats`, `account_daily_delta` — таблицы существуют).

---

## Решение (минимальный диф)

В `/root/.openclaw/workspace-genri/validator/backend/src/services/accounts_service.py::get_project_accounts`:

```diff
-    proj_result = await db.execute(
-        text("SELECT api_name, project FROM validator_projects WHERE id = :pid"),
-        {"pid": project_id}
-    )
-    proj_row = proj_result.mappings().first()
-    if not proj_row:
-        return []
-    api_name     = proj_row["api_name"]
-    project_name = proj_row["project"]
+    proj_result = await db.execute(
+        text("SELECT api_name FROM validator_projects WHERE id = :pid"),
+        {"pid": project_id}
+    )
+    proj_row = proj_result.mappings().first()
+    if not proj_row:
+        logger.warning("[accounts] project_id=%s not found in validator_projects", project_id)
+        return []
+    api_name = proj_row["api_name"]
+    logger.debug("[accounts] project_id=%s api_name=%s", project_id, api_name)
```

```diff
-        FROM factory_inst_accounts fia
-        JOIN account_packages ap ON ap.id = fia.pack_id
+        FROM factory_inst_accounts fia
+        JOIN factory_pack_accounts ap ON ap.id = fia.pack_id
```

```diff
-        WHERE ap.project = :project_name
+        WHERE ap.project_id = :project_id
         ORDER BY acc.platform, acc.username
-    """), {"api_name": api_name, "project_name": project_name})
+    """), {"api_name": api_name, "project_id": project_id})
+    logger.info("[accounts] project_id=%s rows=%d", project_id, len(rows))
```

Остальной SQL (LATERAL для платформы, audience snapshots, reels stats, daily delta) **не трогаем** — таблицы существуют, инвариант сохранён.

---

## Tasks

### Phase 1 — Fix
- [x] **#1 Patch accounts_service.py SQL** — JOIN + WHERE + bind params + verbose logging. См. диф выше.

### Phase 2 — Tests (gate)
- [x] **#2 Add smoke test test_accounts_endpoint.py** (blocked by #1) — два кейса: known project (Relisme, id=9 → >0 rows) + unknown project (id=999999 → []). Live DB, без mock'ов (соглашение проекта).
- [x] **#3 Run pytest, fix on red** (blocked by #1, #2) — оба теста зелёные перед commit'ом.

### Phase 3 — Deploy
- [x] **#4 Commit + auto-push** (blocked by #3) — commit `79ee472`, hook ✅ pushed to GenGo2/validator-contenthunter.
- [x] **#5 pm2 restart validator + manual verify** — pm2 id=24 рестартован (sudo pm2), uvicorn online. Verify: id=9→57 rows, id=16→47, id=12→43, id=999999→[] (+ warning лог).

### Phase 4 — Docs
- [x] **#6 Evidence doc** — evidence + plan committed (`9b5f45641`) on `feature/farming-testbench-phone171`.

## Commit Plan

6 задач — нужны checkpoint'ы:

- **Commit A** (после #3): `fix(accounts): account_packages → factory_pack_accounts after factory consolidation` — патч + smoke-тест в одном коммите (validator репо, ветка `main`).
- **Commit B** (после #6): `docs(evidence): client /accounts empty — account_packages JOIN fix` — evidence (contenthunter репо, текущая ветка).

---

## Risk & rollback

- **Blast radius:** изолировано — один файл сервиса, один SQL. PM2 restart валидатора (~3s downtime client API).
- **Откат:** `git revert <sha>` в validator/main + `pm2 restart validator`. Post-commit hook задеплоит откат тем же путём.
- **Сосед-сессии:** другой код не трогаем. В contenthunter работаем в текущей ветке (где уже M PLAN.md и ?? plans/* от других сессий) — добавляем только новые файлы (plan + evidence), конфликтов с PLAN.md нет.

## Why no `--parallel` worktree

`/aif-plan` defaults to `full --parallel`, чтобы избежать перетирания `.ai-factory/PLAN.md` (memory `feedback_plan_full_mode_branch.md`). Здесь это не применимо:
1. Plan пишется в datated `plans/client-accounts-empty-fix-20260424.md`, не в PLAN.md → коллизий нет.
2. Code-fix живёт **в другом репо** (`/root/.openclaw/workspace-genri/validator/`) — worktree contenthunter не помогает редактировать validator.
3. Текущая ветка contenthunter — `feature/farming-testbench-phone171`, не main; правило "никогда fast в main" не нарушаем.
