# Fix — POST /api/packages/:id/accounts: NULL violation на factory_inst_accounts.id

**Date:** 2026-04-23
**Branch:** `testbench` (autowarm-testbench + prod autowarm)
**Commit:** `4561d32` — `fix(packages): add sequence for factory_inst_accounts.id + factory_pack_accounts.id`
**Status:** ✅ Deployed (testbench + prod), migration applied, 4/4 regression tests green.

## Проблема (as reported)

Пользователь: на https://delivery.contenthunter.ru/#devices/packages в модалке редактирования пака добавляет аккаунт → «Сохранить» → `Ошибка: null value in column "id" of relation "factory_inst_accounts" violates not-null constraint`. Гипотеза пользователя: «парсер сломался».

## Actual root cause (диагноз)

Гипотеза про парсер — **не подтвердилась**. Парсер (`id_parser.py`) вызывается через `triggerIdParsing()` в `server.js:3431` **после** INSERT и пишет в колонку `instagram_id` (text), не в `id`. До него дело не доходило.

**Реальная причина:** таблица `factory_inst_accounts` имеет колонку `id INTEGER NOT NULL` **без DEFAULT и без SEQUENCE**. Handler `POST /api/packages/:id/accounts` (`server.js:3036`) делает INSERT без явной колонки `id`:

```sql
INSERT INTO factory_inst_accounts (pack_id, platform, username, instagram_id, active, synced_at)
VALUES ($1,$2,$3,$4,$5,NOW()) RETURNING id, ...
```

Postgres пытается вставить NULL в `id` (DEFAULT нет) → NOT NULL violation. До `triggerIdParsing` никогда не доходит.

### Git-история регрессии

| Commit | Date | Что сделал |
|---|---|---|
| `54e21d1` | 2026-03-10 | Создал этот handler — расчёт на SEQUENCE (которой не было) |
| `2e176e9` | 2026-03-11 | В **split**-handler'е обнаружили «no sequence on factory tables», пофиксили manual `nextAccId++`. **В add-account-handler'е тот же фикс забыли.** |
| `736d37f` | 2026-04-22 | Factory-only refactor (DROP TABLE account_packages) — обработчик не трогали |
| `4561d32` | 2026-04-23 | **Этот фикс** |

Баг дремал до первой попытки пользователя добавить аккаунт через админку.

## Стратегия фикса (применена)

**Вариант A — SEQUENCE на PK** (вместо точечного MAX(id)+1 в конкретном handler'е).

Причины:
1. Устраняет root cause, а не симптом.
2. Убирает race-condition между counter-INSERT'ами (split, create-pack, revision/apply) и прогрессом sequence.
3. Упрощает все будущие INSERT'ы (можно положиться на DEFAULT).
4. Внешний `factory_sync.py` отсутствует (audit подтвердил) — id-space никто кроме Postgres не трогает.

## Что поменялось

### DB

**Применена миграция** `migrations/20260423_factory_accounts_id_sequence.sql` на `openclaw@localhost:5432`:

- `CREATE SEQUENCE factory_inst_accounts_id_seq` + setval(1686) + `ALTER ... DEFAULT nextval(...)`
- То же для `factory_pack_accounts_id_seq` (setval=341).
- Rollback-файл `*__rollback.sql` приложен.

Проверка после commit:
```
             table         |  column   |                      default
-----------------------+-----------+---------------------------------------------------
 factory_inst_accounts | id        | nextval('factory_inst_accounts_id_seq'::regclass)
 factory_pack_accounts | id        | nextval('factory_pack_accounts_id_seq'::regclass)
```

### Код (server.js, 4 handler'а переведены на sequence)

| Handler | Line | Изменения |
|---|---|---|
| `POST /api/packages` (CREATE pack) | ~2620 | Убран `MAX(id)+1` блок, INSERT с RETURNING id; verbose log |
| `POST /api/packages/:id/split` | ~2848 | Убран комментарий «таблицы без sequence», убраны `nextPackId/nextAccId++`, INSERT с RETURNING id; verbose logs |
| **`POST /api/packages/:id/accounts`** | ~3035 | INSERT не меняется (уже был без id — это и был bug), добавлен verbose log |
| `POST /api/revision/apply` | ~3250-3380 | Убран counter-блок; `targetPackId = nextPackId++` → INSERT с RETURNING; `accId = nextAccId++` → INSERT с RETURNING |

**Net:** +220/-45 строк в 4 файлах (migrations×2 + server.js + tests).

### Тест

`tests/test_packages_add_account.test.js` — node:test regression:
1. CREATE pack INSERT RETURNING id → ✅ id=342 (новый после setval)
2. add account INSERT → ✅ id=1687
3. second INSERT → ✅ id=1688 (монотонный)
4. readback row → ✅ все колонки корректны

Результат локального прогона:
```
# tests 4
# pass 4
# fail 0
```

Cleanup-блок `after()` удаляет testовые строки — проверено, `SELECT COUNT(*) WHERE username LIKE '__test_regression_%'` = 0.

## Deploy

### Testbench
- `autowarm-testbench` (pm2 id=25) рестартован, uptime 0s, online.
- Тест прогнан из `/home/claude-user/autowarm-testbench/` — 4/4 green.

### Prod
- Fast-forward pull `/root/.openclaw/workspace-genri/autowarm/` (branch `testbench`, `8b6f7f6..4561d32`) — 4 files changed, 220/45.
- `sudo -n pm2 restart autowarm` (id=1) — uptime 0s, online.
- Startup logs: scheduler started, assign-queue working, no migration/syntax errors.
- Миграция на БД применена ещё до restart (T4) — bug был исправлен в момент применения миграции, restart нужен только для подтягивания новых verbose logs и устранения race-condition.

## Known follow-up (не в этой PR)

**IG-резолвер id_parser.py не работает.** Smoke-прогон:
- ✅ YT: `google` → `UCK8sQmJBp8GCxrOtXWBpyEA`
- ✅ TT: `khaby.lame` → `127905465618821121`
- ❌ IG: `natgeo` → `{ok: false, error: "User ID not found"}`

Debug:
- Apify (`apify~instagram-profile-scraper`) возвращает **HTTP 403** — протухший/невалидный `APIFY_API_KEY` или исчерпаны кредиты.
- Fallback `i.instagram.com/api/v1/users/web_profile_info` возвращает **HTTP 429** — rate-limited на этом IP.

**Симптом на проде после нашего фикса:** новые IG-аккаунты успешно INSERT'ятся (sequence выдаёт id), но `instagram_id` остаётся NULL. Для `publish_guard` это может быть блокером — нужен отдельный follow-up plan:
1. Обновить `APIFY_API_KEY` в `/root/.openclaw/workspace-genri/autowarm/.env` (и в testbench) либо перейти на другой Apify actor с работающим free-tier.
2. Или — проксировать i.instagram.com через residential proxy (задаче ADB packet-loss уже известно).

Это **не блокирует** текущий фикс (пользователь снова может добавлять аккаунты; id присваивается), но остаётся реальным пробелом в автоматическом заполнении `instagram_id`.

## Files

**Code (autowarm-testbench, commit `4561d32`):**
- `migrations/20260423_factory_accounts_id_sequence.sql`
- `migrations/20260423_factory_accounts_id_sequence__rollback.sql`
- `server.js` (4 handler'а)
- `tests/test_packages_add_account.test.js`

**Context (contenthunter/.ai-factory):**
- `plans/fix-packages-add-account-id-20260423.md`
- `evidence/fix-packages-add-account-id-audit-20260423.md`
- `evidence/fix-packages-add-account-id-migration-20260423.md`
- `evidence/fix-packages-add-account-id-20260423.md` (этот файл)

## Verification — live (2026-04-23)

- [x] Пользователь воспроизвёл путь: пак «Тестовый проект_19b» → добавлен новый YT-аккаунт → сохранён корректно. Ошибка `null value in column "id"` ушла.
- [x] Parser (YT) подхватил user_id сразу после INSERT — подтверждает, что весь pipeline (INSERT → triggerIdParsing → id_parser.py → UPDATE instagram_id) работает end-to-end для YT.
- [x] IG parser по-прежнему не работает (ожидаемо — известный follow-up, см. memory `project_id_parser_ig_broken.md`).
