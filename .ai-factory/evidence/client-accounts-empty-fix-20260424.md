# Evidence — client `/accounts` пустой по всем проектам

**Date:** 2026-04-24
**Plan:** [`plans/client-accounts-empty-fix-20260424.md`](../plans/client-accounts-empty-fix-20260424.md)
**Validator commit:** `79ee472` (GenGo2/validator-contenthunter, ветка main, auto-pushed via post-commit hook)

## Symptom

Пользователь (2026-04-24): на `https://client.contenthunter.ru/accounts` под любой ролью и в любом проекте — пустой список аккаунтов. По данным БД они есть.

## Root cause

`accounts_service.py::get_project_accounts` строил SQL с `JOIN account_packages`. Таблица `account_packages` была **DROP'нута 2026-04-22** в рамках консолидации factory (см. `project_account_packages_deprecation` в memory; commit autowarm `5c6c432`). Validator не был обновлён вместе с autowarm.

Запрос крашился до применения project-фильтра → 500 / `accounts: []` на фронте через `?? []` fallback. Поэтому пусто **независимо** от проекта и роли.

Reproduction (live psql) до фикса:
```
$ psql -c "SELECT count(*) FROM factory_inst_accounts fia JOIN account_packages ap ON ap.id = fia.pack_id;"
ERROR:  relation "account_packages" does not exist
```

В pm2-логах `validator` за минуту до рестарта: `WHERE ap.project = $2 / parameters: ('forchill', 'Forchil')` + `relation "account_packages" does not exist`.

## Fix

`/root/.openclaw/workspace-genri/validator/backend/src/services/accounts_service.py`:

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

-        FROM factory_inst_accounts fia
-        JOIN account_packages ap ON ap.id = fia.pack_id
+        FROM factory_inst_accounts fia
+        JOIN factory_pack_accounts ap ON ap.id = fia.pack_id

-        WHERE ap.project = :project_name
-    """), {"api_name": api_name, "project_name": project_name})
+        WHERE ap.project_id = :project_id
+    """), {"api_name": api_name, "project_id": project_id})
+    logger.info("[accounts] project_id=%s rows=%d", project_id, len(rows))
```

Никакие LATERAL/LEFT JOIN'ы не трогали — `account_audience_snapshots`, `factory_inst_reels_stats`, `factory_inst_reels`, `account_daily_delta` все существуют.

## Verification

После `sudo pm2 restart validator` (id=24) — прямой вызов сервиса на live DB:

| project_id | name | rows |
|---|---|---|
| 9 | Relisme | 57 |
| 16 | Джинсы Шелковица | 47 |
| 12 | Symmetry | 43 |
| 999999 | (unknown) | 0 + WARNING `[accounts] project_id=999999 not found` |

Smoke-тест `tests/test_accounts_endpoint.py::test_accounts_endpoint_smoke_against_live_db` зелёный.

## Follow-ups

- LATERAL CROSS JOIN с regex-инференсом платформы (`acc.platform`) написан до того, как у `factory_inst_accounts.platform` появилась реальная колонка. Сейчас он делает round-about: COALESCE'ит `fia.platform` сам с собой через CASE по `instagram_id`. Это кандидат на упрощение в будущем (вне текущего scope, не блокер).
- Тестов на /accounts больше не было — добавлен один smoke. Не расширяем здесь, чтобы не выходить за scope.

## Why it slipped

Drop `account_packages` был выполнен в autowarm (Step 3 миграции factory) с проверкой dual-write и read-paths внутри autowarm. Validator — отдельный репо/деплой/команда, и cross-repo grep не делался. Memory `project_account_packages_deprecation` фиксирует завершение DROP'а, но не упоминает validator как потребителя.
