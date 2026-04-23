# Fix — POST `/api/packages/:id/accounts`: NOT NULL violation на `factory_inst_accounts.id`

**Тип:** fix (regression в admin CRUD после deprecate-account-packages)
**Создан:** 2026-04-23
**Режим:** full (без `--parallel`). Plan-файл уникален → коллизий с соседями нет.
**Target repo (код):** `/home/claude-user/autowarm-testbench/` (ветка `testbench`) → auto-deploy в prod через post-commit hook в `/root/.openclaw/workspace-genri/autowarm/`
**Context repo (этот план + evidence):** `/home/claude-user/contenthunter/` (текущая ветка `feature/farming-testbench-phone171` — план-файл безопасно ложится рядом, он docs-only)

## Settings

- **Testing:** yes — node:test regression на POST-хэндлер (fixture: временный pack, POST + проверка 200 + id!=null + DB-row existence); pytest smoke на `id_parser.py` (опционально: проверить, что резолвер IG/YT/TT живой — см. T6).
- **Logging:** verbose — `[api/packages/accounts] insert pack=<id> platform=<p> username=<u> → new_id=<id>`; `[id_parser/trigger] platform=<p> username=<u> timeout=<s>`; в миграции SQL — `RAISE NOTICE` при setval.
- **Docs:** warn-only — evidence обязателен (до/после dump, SQL-доказательство sequence), CLAUDE.md / memory обновляем только если найдём новое правило.
- **Roadmap:** none (`paths.roadmap` не настроен).

## Корневая причина (подтверждено разведкой)

**Таблица `factory_inst_accounts` (prod DB):**
```
id  | integer | not null | (no DEFAULT, no sequence)
PRIMARY KEY (id)
```

**Handler `POST /api/packages/:id/accounts`** в `server.js:3010-3045`:
```js
INSERT INTO factory_inst_accounts (pack_id, platform, username, instagram_id, active, synced_at)
VALUES ($1,$2,$3,$4,$5,NOW()) RETURNING id, username, instagram_id AS user_id, ...
```

Колонка `id` не указана → Postgres пытается вставить NULL (DEFAULT нет) → `NOT NULL violation`.

**Похожая аномалия уже была замечена 2026-03-11** (commit `2e176e9` "fix: pack split — manual ID generation (no sequence on factory tables)"): в split-handler (`server.js:2817-2912`) завели ручной `nextAccId++`. В POST-accounts-handler **тот же паттерн забыли применить**. Баг дремал до 2026-04-22 (миграции factory-only в `736d37f`), потом проявился первой же попыткой добавить аккаунт через админку.

**Важно (для плана — user clarification):** парсер ≠ этот баг.
- `id` в `factory_inst_accounts` — локальный PK (integer).
- Платформенный id (IG user_id, YT channel_id, TT numeric) хранится в `instagram_id` (text, single column для всех платформ).
- Парсер `id_parser.py` вызывается из `server.js:3431 triggerIdParsing()` **после** INSERT через `execFile('python3', ...)` — и пишет UPDATE с WHERE id=<newAcc.id>. До него не доходит, т.к. INSERT падает.
- Парсер проверим отдельно (T6) — он не в причине текущей ошибки, но раз пользователь упоминает его как «сломанный», лучше верифицировать.

## Стратегия

**Выбрана стратегия A — SEQUENCE на PK** (вместо точечного MAX(id)+1 в обоих handler'ах):
- Одноразовая миграция гасит техдолг.
- Убирает race-condition при параллельных INSERT'ах (split + add одновременно).
- Упрощает все будущие INSERT'ы в factory-таблицы (не надо ручной id-counter).
- Заодно — применим тот же паттерн к `factory_pack_accounts.id` (такая же схема: integer NOT NULL без default). Проверим, есть ли там аналогичные проблемные INSERT'ы.

**Rollback:** обратимо — `DROP SEQUENCE` и `ALTER COLUMN DROP DEFAULT`. Существующие строки не трогаем.

## Tasks

### Phase 1 — Аудит (перед изменением схемы)

#### T1. Найти все INSERT'ы в `factory_inst_accounts` и `factory_pack_accounts`
- **Deliverable:** `.ai-factory/evidence/fix-packages-add-account-id-audit-20260423.md` — список всех мест в `server.js`, `*.py`, миграциях, где идёт INSERT в эти две таблицы, с file:line и состоянием id-колонки (явный/через counter/отсутствует).
- **Action:** `grep -rn "INSERT INTO factory_inst_accounts" /home/claude-user/autowarm-testbench/` и то же для `factory_pack_accounts`. Для каждого совпадения классифицировать: (a) явный id → SAFE, (b) counter `nextAccId++` → будет дубликат после sequence, нужно упростить, (c) без id → UNSAFE (как наш bug).
- **Log:** нет (аудит)
- **Files:** evidence-файл выше

#### T2. Проверить, нет ли других мест, которые читают `factory_inst_accounts.id` с ожиданием конкретной монотонности или плотности
- **Deliverable:** пометка в том же evidence-файле — «использования id: PK/JOIN only, sequence safe» или «найдено <X> — требует доп. action».
- **Action:** `grep -rn "factory_inst_accounts.id\|fia.id" server.js publisher.py account_switcher.py account_factory.py` — убедиться, что id везде используется только как PK / FK, без ожиданий типа «id растёт по возрастанию времени создания» или «id кодирует platform_id».
- **Log:** нет

### Phase 2 — SQL-миграция

#### T3. Написать миграцию `migrations/20260423_factory_accounts_id_sequence.sql` + rollback
- **Deliverable:** SQL-файл в `/home/claude-user/autowarm-testbench/migrations/`.
- **Contents:**
  ```sql
  -- factory_inst_accounts
  CREATE SEQUENCE IF NOT EXISTS factory_inst_accounts_id_seq
    OWNED BY factory_inst_accounts.id;
  SELECT setval('factory_inst_accounts_id_seq',
                GREATEST((SELECT COALESCE(MAX(id), 0) FROM factory_inst_accounts), 1));
  ALTER TABLE factory_inst_accounts
    ALTER COLUMN id SET DEFAULT nextval('factory_inst_accounts_id_seq');

  -- factory_pack_accounts (тот же паттерн для симметрии)
  CREATE SEQUENCE IF NOT EXISTS factory_pack_accounts_id_seq
    OWNED BY factory_pack_accounts.id;
  SELECT setval('factory_pack_accounts_id_seq',
                GREATEST((SELECT COALESCE(MAX(id), 0) FROM factory_pack_accounts), 1));
  ALTER TABLE factory_pack_accounts
    ALTER COLUMN id SET DEFAULT nextval('factory_pack_accounts_id_seq');
  ```
- **Rollback (`.rollback.sql`):**
  ```sql
  ALTER TABLE factory_inst_accounts ALTER COLUMN id DROP DEFAULT;
  DROP SEQUENCE IF EXISTS factory_inst_accounts_id_seq;
  ALTER TABLE factory_pack_accounts ALTER COLUMN id DROP DEFAULT;
  DROP SEQUENCE IF EXISTS factory_pack_accounts_id_seq;
  ```
- **Log:** в SQL — `RAISE NOTICE '[migration] factory_inst_accounts seq started at <val>'` (опционально, через DO-блок).
- **Verify после применения:**
  ```
  SELECT pg_get_expr(adbin, adrelid)
  FROM pg_attrdef
  WHERE adrelid = 'factory_inst_accounts'::regclass;
  -- ожидается: nextval('factory_inst_accounts_id_seq'::regclass)
  ```
- **Files:** `/home/claude-user/autowarm-testbench/migrations/20260423_factory_accounts_id_sequence.sql` + `.rollback.sql`

#### T4. Применить миграцию на prod DB
- **Deliverable:** вывод `psql` с подтверждением setval и изменённого DEFAULT.
- **Action:** `PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f migrations/20260423_factory_accounts_id_sequence.sql`
- **Log:** capture stdout+stderr в `.ai-factory/evidence/fix-packages-add-account-id-migration-20260423.md`
- **Verify:** `SELECT nextval('factory_inst_accounts_id_seq');` → должно вернуть `MAX(id)+1` (на момент разведки MAX=1686, ожидаем 1687 после первого nextval).

### Phase 3 — Упрощение кода (после миграции)

#### T5. Почистить POST `/api/packages/:id/accounts` в `server.js:3010-3045`
- **Deliverable:** handler просто делает INSERT без указания id, полагаясь на DEFAULT nextval.
- **Diff:** INSERT остаётся как есть (колонка id не указана — теперь это корректно с sequence). Добавить verbose log:
  ```js
  console.log(`[api/packages/accounts] insert pack=${packId} platform=${platform} username=${username} → new_id=${rows[0].id}`);
  ```
- **Проверить:** ничего другого в handler'е не завязано на отсутствие sequence.
- **Log:** один INFO-log на удачный путь, WARN на duplicate (если платформа+username уже есть).

#### T6. (опционально) Упростить split-handler `server.js:2817-2912`
- **Deliverable:** убрать `nextAccId++` counter, INSERT'ы в split полагаются на sequence.
- **Why optional:** split-handler сейчас работает — фикс PK через counter функционально корректен, хоть и многословен. Упрощение снижает техдолг, но не блокирует основной баг.
- **Решение:** сделать в этой же PR, чтобы применить паттерн системно; если diff вырастет — вынести в отдельный follow-up.
- **Verify:** unit-тест split (если есть) остаётся зелёным.

#### T7. Smoke-прогон `id_parser.py` (верификация парсера платформенных id)
- **Deliverable:** evidence-раздел «Parser smoke» с результатом запуска резолвера для 1 IG + 1 YT + 1 TT тестового username.
- **Action:**
  ```bash
  cd /home/claude-user/autowarm-testbench
  python3 id_parser.py instagram someknown_handle
  python3 id_parser.py youtube someknown_handle
  python3 id_parser.py tiktok someknown_handle
  ```
- **Rationale:** пользователь считал, что причина в парсере. Парсер НЕ является причиной текущей ошибки, но убедимся, что он живой (RapidAPI-ключи, apify actor, YouTube Data API quota не исчерпаны). Если парсер действительно лежит — отдельный follow-up plan, не блокируем эту PR.
- **Log:** stdout/stderr в evidence.

### Phase 4 — Regression test

#### T8. `tests/test_packages_add_account.mjs` — node:test regression
- **Deliverable:** node-тест, который:
  1. Создаёт временный pack (INSERT factory_pack_accounts) через прямой SQL (fixture).
  2. Вызывает POST `/api/packages/<tmpPackId>/accounts` с `{platform:'instagram', username:'__test_regression_<ts>', user_id:null, active:true}`.
  3. Ожидает HTTP 200 + JSON с `id` (number, >0).
  4. SELECT строку из БД — проверяет, что `id` действительно совпадает.
  5. Cleanup: DELETE тестовой строки + pack.
- **Log:** verbose — тест печатает `[test] insert returned id=<n>`.
- **Files:** `/home/claude-user/autowarm-testbench/tests/test_packages_add_account.mjs`
- **CI:** добавить в `package.json` test script (если ещё нет) — подключить к `node --test tests/`.

### Phase 5 — Deploy + evidence

#### T9. Commit в testbench + auto-deploy + pm2 restart
- **Deliverable:** 1-2 коммита в `autowarm-testbench` (ветка `testbench`):
  - `fix(packages): add sequence for factory_inst_accounts.id + factory_pack_accounts.id` (миграция + handler cleanup)
  - (если T6 сделан в той же PR) `refactor(packages): drop manual nextAccId counter in split-handler`
- **Action:** `git add migrations/ server.js tests/` → commit → push.
- **Deploy:** post-commit hook в `/root/.openclaw/workspace-genri/autowarm/` тянет → `sudo pm2 restart autowarm`.

#### T10. Live-верификация через `delivery.contenthunter.ru/#devices/packages`
- **Deliverable:** скриншот / evidence: добавление нового аккаунта в пак успешно, запись в БД появилась, `triggerIdParsing` запустился (логи pm2 autowarm).
- **Action:**
  1. Создать временный pack через UI.
  2. Добавить один тестовый аккаунт с реальным @username на IG.
  3. Проверить: HTTP 200, запись в `factory_inst_accounts` с числовым id и `instagram_id` после ~5-15 секунд (таймаут parser'а).
  4. Удалить тестовый pack и аккаунт.
- **Log:** собрать фрагмент `pm2 logs autowarm` за период тестирования.

#### T11. Evidence-файл + memory update
- **Deliverable:** `.ai-factory/evidence/fix-packages-add-account-id-20260423.md` — свёрстанный итог: RC, diff, миграция, тест, live-проверка, ссылки на коммиты.
- **Memory:** если в процессе обнаружилось ещё одно place без sequence (через T1 audit) или правило «все factory-таблицы должны иметь sequence» — обновить memory `project_account_packages_deprecation.md` или создать новую запись.

## Commit Plan

- **Commit 1** (после T4): миграция SQL применена — `feat(migrations): factory accounts id sequence` (`migrations/20260423_factory_accounts_id_sequence.sql` + `.rollback.sql`). Текст коммита: `feat(db): add sequence for factory_inst_accounts.id + factory_pack_accounts.id — fixes NOT NULL violation on POST /api/packages/:id/accounts`.
- **Commit 2** (после T5-T7): код-чистка + логи — `fix(server): POST /api/packages/:id/accounts полагается на sequence (+ optional split simplification)`.
- **Commit 3** (после T8): regression test — `test(packages): node:test regression for add-account endpoint`.
- **Финальный push** (после T10): всё в testbench → post-commit hook → pm2 restart → verify.

## Риски и митигации

- **R1: Sequence стартует с неправильного значения.** Миграция использует `setval(..., GREATEST(MAX(id), 1))` — безопасно даже на пустой таблице.
- **R2: В какой-то части кода есть hardcoded ожидание, что id непрерывен.** Митиг: T2 audit. Маловероятно, PK обычно не предполагает плотности.
- **R3: Split-handler после упрощения даст коллизию, если старый код параллельно не обновлён на prod.** Митиг: T3 миграция + T5-T6 в одной PR, одновременный deploy.
- **R4: Парсер `id_parser.py` действительно сломан** (например, протух ключ RapidAPI). Это **не блокирует** фикс INSERT'а (INSERT теперь проходит), но INSERT без platform_id → `instagram_id=NULL` → publish guard может позже не резолвить аккаунт. Митиг: T7 smoke; если парсер мёртв — отдельный follow-up plan.
- **R5: pm2 restart autowarm убивает активные publish/warmer child-process'ы.** Митиг: рестарт в нерабочее время либо в момент, когда `scheduler.js tick` не активен. Стандартная практика для прода.

## Что НЕ делаем в этой PR

- Не меняем фронтенд-payload (текущий `{platform, username, user_id, active}` корректен).
- Не переделываем `id_parser.py` (отдельная ответственность — см. R4).
- Не трогаем другие factory-таблицы (`factory_device_numbers`, `factory_sync_exclusions` и т.п.) — их схемы в этой PR не в скоупе, пусть audit T1 покажет.
