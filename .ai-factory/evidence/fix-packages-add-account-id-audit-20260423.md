# Audit — INSERT'ы и использование id в factory_inst_accounts/factory_pack_accounts

**Date:** 2026-04-23
**Scope:** `/home/claude-user/autowarm-testbench/` (branch `testbench`)
**Purpose:** Pre-migration audit для `fix-packages-add-account-id-20260423.md` — убедиться, что sequence безопасна.

## INSERT INTO factory_inst_accounts — 5 мест

| # | File:Line | Handler | Columns | id-стратегия | Safe с sequence? |
|---|---|---|---|---|---|
| 1 | `tests/test_testbench_orchestrator.py:65,165` | test fixture | (id, username, platform, active, pack_id) | explicit | ✅ SAFE (тестовые id не конфликтуют, но в тесте лучше тоже убрать или обновить setval fixture) |
| 2 | `server.js:2638` | POST /api/packages (CREATE pack + initial accounts) | (id, pack_id, platform, username, active, synced_at) | counter `nextAccId++ = MAX(id)+1` | ⚠️ RACE: counter vs sequence выдаст тот же id |
| 3 | `server.js:2877` | POST /api/packages/:id/split | (id, pack_id, platform, username, instagram_id, active, synced_at) | counter `nextAccId++ = MAX(id)+1` | ⚠️ RACE: counter vs sequence |
| 4 | **`server.js:3036`** | **POST /api/packages/:id/accounts (add one)** | (pack_id, platform, username, instagram_id, active, synced_at) | **НЕТ** | ❌ THE BUG — id=NULL → violation |
| 5 | `server.js:3389` | POST /api/revision/apply | (id, pack_id, platform, username, active, synced_at) | counter `nextAccId++ = MAX(id)+1` | ⚠️ RACE: counter vs sequence |

## INSERT INTO factory_pack_accounts — 5 мест

| # | File:Line | Handler | id-стратегия | Safe с sequence? |
|---|---|---|---|---|
| 1 | `migrations/20260422_split_phone19_legacy_pack.sql:50` | manual migration | explicit | ✅ (одноразово, в прошлом) |
| 2 | `migrations/20260422_split_phone171_legacy_pack.sql:42` | manual migration | explicit | ✅ |
| 3 | `server.js:2626` | POST /api/packages (CREATE pack) | counter `MAX(id)+1` | ⚠️ RACE с sequence |
| 4 | `server.js:2872` | POST /api/packages/:id/split | counter `nextPackId++` | ⚠️ RACE |
| 5 | `server.js:3378` | POST /api/revision/apply | counter `nextPackId++` | ⚠️ RACE |

## Использования `factory_inst_accounts.id` и `factory_pack_accounts.id` (read-side)

Все — PK / FK / ORDER BY. Никаких предположений о **семантике** id (не кодирует платформу, не монотонен во времени, не плотен).

Конкретика:
- `server.js:2458` — `SELECT DISTINCT ON (fia.username) fia.id, ...` → возвращает id для UI.
- `server.js:2534-2535,2762,2767,2769` — `COUNT(fia.id) FILTER (WHERE fia.active = true)`, `ORDER BY ... fia.id` — агрегация, PK-filter.
- `server.js:2759-2761` — `JSON_AGG({'id', fia.id, ...}) ORDER BY fia.platform, fia.id` — стабильная сортировка.
- `server.js:3395` — verbose log.
- `account_revision.py:462` — `SELECT fia.id ... FROM factory_inst_accounts fia` — прямой select PK.
- `testbench_orchestrator.py:177,216` — `ORDER BY fia.id ASC` — стабильная сортировка.

**Вывод: ни одного места не зависит от конкретных значений id.**

## Внешний sync — мёртв

- **`factory_sync.py`** — файла в репо НЕТ. Комментарии в `server.js:2884, 2957` ссылаются на него как на «защиту от перезаписи», но самого процесса не существует.
- **`factory_sync_exclusions`** — табличка живая, но без читающего её процесса = легаси-механизм, не влияет на текущий код-путь.
- **cron / systemd / pm2 / ecosystem.config.js** — ни одной ссылки на factory_sync.
- **Memory `project_account_packages_deprecation.md` (2026-04-22)** подтверждает: после Шага 3 factory — единственный источник, внешний sync отсутствует.

## Вывод по стратегии

**SEQUENCE безопасно добавить** — id везде PK, внешний sync мёртв.

**Но** — оставить counter'ы `MAX(id)+1` в 4 других handler'ах после добавления sequence даст **race-condition**: одновременный INSERT (counter+explicit) и INSERT (sequence+DEFAULT) могут выдать одинаковый id → PK violation.

**Решение:** перевести ВСЕ 5 handler'ов (server.js:2626, 2638, 2872, 2877, 3036, 3378, 3389) на sequence — убрать `MAX(id)+1` блоки и explicit `id` в INSERT. Это монолитная замена с одинаковым риском.

Scope update:
- **T3 migration** — остаётся как есть (sequence на factory_inst_accounts + factory_pack_accounts).
- **T5** — расширяется: чистим POST /api/packages/:id/accounts **+ CREATE pack (2621-2643) + split (2850-2882) + revision/apply (3350-3395) от counter-блоков и explicit id**.
- **T6** сливается в T5 (split — часть общей замены).

Тесты `test_testbench_orchestrator.py` оставляем с explicit id — тестовые фикстуры могут указывать id явно, sequence не возражает (DEFAULT применяется только при отсутствии значения).
