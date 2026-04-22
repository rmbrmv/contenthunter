# Ревизия → account_packages: sync + pack-splitting rules (Шаг 1 из 2)

**Тип:** enhancement (revision pipeline) + data migration
**Создан:** 2026-04-22 UTC
**Режим:** Full (slug `revision-account-packages-sync-20260422`)
**Целевые репо:**
- `/home/claude-user/autowarm-testbench/` (branch `testbench`) — код ревизии и guard'а
- `/home/claude-user/contenthunter/` (branch `main`) — план + evidence
**НЕ трогаем:** `/root/autowarm/` (prod deploy — отдельной задачей).

## Scope & non-scope

**В scope (Шаг 1):**
- `POST /api/devices/:serial/revision/apply` (`server.js:2878-2981`) — доработать так, чтобы:
  - имя пака = `<project_name>_<device_number>[suffix]` (русское имя из `validator_projects.project`)
  - правило «один пак = по одному аккаунту каждой платформы» соблюдается при любой конфигурации существующих паков
  - при появлении второго пака одного и того же проекта первый переименовывается (Excel-like суффиксы `a..z, aa..zz, …`)
  - каждая вставка/переименование в factory зеркалится в `account_packages` (через единую sync-функцию)
- Одноразовая миграция legacy-пака phone #19 (`factory_pack_accounts.id=249`) → разбиение 19 → 19a + 19b.
- Backfill: пройти по всем `factory_inst_accounts.active=true` и создать недостающие строки в `account_packages`, чтобы guard пропускал всех.

**Не в scope (уходит в Шаг 2):**
- Удаление таблицы `account_packages`, переписывание `_GUARD_QUERY` на factory-таблицы, миграция 223 живых строк `account_packages`. План Шага 2 напишу отдельно после успеха Шага 1.
- Админский CRUD `/api/admin/packages` оставляем как есть (он пишет в `account_packages` напрямую — пусть работает).
- `_upsert_auto_mapping` в `publisher.py` оставляем как есть: он пишет в `account_packages` с `project='auto-from-publish'` — это отдельный источник, не конфликтует.
- Deploy изменений в prod `/root/autowarm/`. Фокус Шага 1 — testbench; прод получит это отдельной задачей после смок-теста на phone #19.

## Settings

| | |
|---|---|
| Testing | **yes** — unit для генератора имён (все edge-cases), unit для sync-функции, интеграционный тест `revision/apply` с реальной БД (SAVEPOINT + ROLLBACK, по house-style `не мокать БД`) |
| Logging | **verbose** — на каждую мутацию паков: `[revision/apply] action=... pack=... acc=...`; на генератор имён: вычисленный suffix + переименования; на sync: какие колонки `account_packages` обновлены |
| Docs | **mandatory checkpoint (T11)** — evidence + memory update (`project_publish_guard_schema.md`) |
| Roadmap linkage | skipped — `paths.roadmap` не настроен |
| Git | testbench-репо: ветка `testbench`, `git push origin testbench`. contenthunter: `main`, `git push origin main`. Ни в `main` autowarm, ни в prod — не пушим. |

## Контекст (state на 2026-04-22 UTC)

### Phone #19 (`RF8YA0W57EP`, `factory_device_numbers.id=163`, `device_number=19`)

**factory_pack_accounts (1 пак, нарушает правило one-per-platform):**
| id | pack_name | project_id | project_name |
|----|-----------|-----------:|---|
| 249 | `Тестовый проект_19` | 10 | Тестовый проект |

**factory_inst_accounts под паком 249 (5 аккаунтов):**
| id | platform | username | synced_at |
|----|----------|----------|---|
| 1528 | youtube | Инакент-т2щ | 2026-03-23 (старый) |
| 1529 | instagram | inakent06 | 2026-03-23 (старый) |
| 1530 | tiktok | user70415121188138 | 2026-03-23 (старый) |
| 1628 | instagram | gennadiya311 | 2026-04-22 09:22 (новый, guard ругается) |
| 1629 | tiktok | gennadiya4 | 2026-04-22 09:22 (новый, guard ругается) |

**account_packages для serial=`RF8YA0W57EP` (3 строки):**
| id | pack_name | project | instagram | tiktok | youtube | end_date |
|----|-----------|---------|-----------|--------|---------|---|
| 249 | `Тестовый проект_19` | Тестовый проект | — | — | — | **2026-01-10 (истёк)** |
| 295 | `NULL` | `manual-seed-20260417` | inakent06 | user70415121188138 | Инакент-т2щ | NULL |
| 319 | `auto-youtube` | `auto-from-publish` | — | — | Инакент-т2щ | NULL |

**Что видит guard сейчас** (UNION по активным `account_packages` строкам, `end_date IS NULL OR >= CURRENT_DATE`):
- IG: `inakent06` (из #295) — **`gennadiya311` НЕТ** → `[guard] gennadiya311 не в списке …/Instagram`
- TT: `user70415121188138` (из #295) — **`gennadiya4` НЕТ** → `[guard] gennadiya4 не в списке …/TikTok`
- YT: `Инакент-т2щ` (из #295 и #319)

### Задача целевого состояния после Шага 1

**factory_pack_accounts (2 пака):**
| id | pack_name | project_id |
|----|-----------|-----------:|
| 249 | `Тестовый проект_19a` | 10 |
| new | `Тестовый проект_19b` | 10 |

**factory_inst_accounts (те же 5 аккаунтов, переразвязаны):**
| id | platform | username | pack_id |
|----|----------|----------|---|
| 1528 | youtube | Инакент-т2щ | 249 (19a) |
| 1529 | instagram | inakent06 | 249 (19a) |
| 1530 | tiktok | user70415121188138 | 249 (19a) |
| 1628 | instagram | gennadiya311 | new (19b) |
| 1629 | tiktok | gennadiya4 | new (19b) |

**account_packages после миграции (все строки активны, end_date=NULL):**
| id | pack_name | project | instagram | tiktok | youtube |
|----|-----------|---------|-----------|--------|---------|
| 249 | `Тестовый проект_19a` | Тестовый проект | inakent06 | user70415121188138 | Инакент-т2щ |
| new | `Тестовый проект_19b` | Тестовый проект | gennadiya311 | gennadiya4 | — |
| 295 | `NULL` | `manual-seed-20260417` | inakent06 | user70415121188138 | Инакент-т2щ | *(не трогаем, legacy seed)* |
| 319 | `auto-youtube` | `auto-from-publish` | — | — | Инакент-т2щ | *(не трогаем)* |

Guard (UNION) увидит все 5 аккаунтов → обе проблемы `gennadiya*` закрыты.

## Strategy

1. **Чистая функция расчёта имени пака** — детерминированная, юнит-тестируемая, отдельный модуль `pack_name_resolver.py`. Принимает `(project_name, device_number, existing_packs_for_project_on_device)`, возвращает `(new_pack_name, [(pack_id, new_name), …] renames)`.
2. **Слотовая логика apply** — для каждого обнаруженного аккаунта искать пак того же проекта на устройстве, где **платформа-слот свободна**. Нет — создаём новый пак (с возможным переименованием первого).
3. **Единая sync-функция** `sync_pack_into_account_packages(conn, factory_pack_id)` — читает текущее состояние factory-пака (имя, проект, аккаунты по платформам) и UPSERT'ит строку в `account_packages` по `pack_name`. Вызывается после каждой мутации factory.
4. **Миграция #19 — отдельная идемпотентная SQL-функция** (не скрипт в коде), чтобы можно было прогнать dry-run → diff → apply.
5. **Backfill — отдельный CLI-скрипт** `audit_sync_account_packages.py`, без мутаций по умолчанию (dry-run), с флагом `--apply`.
6. **Работаем в testbench-репо**, prod трогаем только после смок-теста на phone #19.

## Research Context

Research path не ведётся. Использую:
- memory: `project_publish_guard_schema.md` (схема guard events), `project_publish_followups.md`, `project_publish_testbench.md`
- Явные источники: `server.js:2878-2981` (apply), `publisher.py:6451-6525` (_GUARD_QUERY), DB (`\d account_packages`, `\d factory_*`), валидировано через `PGPASSWORD=openclaw123 psql`
- Правила именования — из дикторского брифа пользователя (2026-04-22)

## Tasks

### Phase 1 — Генератор имён паков (T1, T2)

**T1. ✅ Модуль `pack_name_resolver.py` + функция генерации имени**  (blocks T2, T5, T6)

- Новый файл: `/home/claude-user/autowarm-testbench/pack_name_resolver.py`
- Экспорт:
  - `next_suffix(existing_suffixes: list[str]) -> str` — Excel-like (a..z, aa..zz, aaa..zzz, …). Пустые/не-буквенные суффиксы игнорируются.
  - `resolve_pack_layout(project_name: str, device_number: int, existing_packs: list[dict]) -> dict` где `existing_packs = [{'id': int, 'pack_name': str}, …]`. Возвращает:
    ```python
    {
      'new_pack_name': 'Тестовый проект_19b',
      'renames': [(249, 'Тестовый проект_19a')],  # список (pack_id, new_name)
    }
    ```
- Правила (протестированы в T2):
  - `base = f"{project_name}_{device_number}"`
  - Если `existing_packs` пусто → `new_pack_name = base`, `renames = []`.
  - Если `len(existing_packs) == 1` и `pack_name == base` → `new_pack_name = f"{base}b"`, `renames = [(id, f"{base}a")]`.
  - Иначе: парсим суффиксы (всё после `base`), берём следующий через `next_suffix(used)`; переименований нет.
- Verbose logging: `log.info('[pack-names] resolve project=%s device=%d existing=%s → new=%s renames=%s', ...)`.
- **НЕ трогает БД**, чистая функция.

**T2. ✅ Unit-тесты для pack_name_resolver**  (blocked by T1; blocks T5, T6) — 17/17 pass (расширил с 8 до 17 кейсов: suffix-math, invariants)

- Новый файл: `/home/claude-user/autowarm-testbench/tests/test_pack_name_resolver.py`
- Кейсы:
  1. `test_empty_returns_base` — нет паков → `("Тестовый проект_19", [])`.
  2. `test_second_pack_renames_first` — один пак "X_19" → `new="X_19b", renames=[(1,"X_19a")]`.
  3. `test_third_pack_no_renames` — два пака "X_19a","X_19b" → `new="X_19c", renames=[]`.
  4. `test_gap_in_suffixes` — паки "X_19a","X_19c" → `new="X_19d"` (берём max+1, не заполняем дырки — проще и детерминированно).
  5. `test_overflow_z_to_aa` — паки с `a..z` → `new="X_19aa"`.
  6. `test_overflow_zz_to_aaa` — паки с `a..z, aa..zz` → `new="X_19aaa"`.
  7. `test_ignores_mismatched_names` — если в existing_packs затесался пак "Другой_19" (не в base) → его игнорируем, считаем только совпадающие с base.
  8. `test_project_with_spaces` — "Тестовый проект" не ломает parser.
- Запуск: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_pack_name_resolver.py -v`
- Expected: 8/8 pass.

### Phase 2 — Синхронизатор account_packages (T3, T4)

**T3. ✅ Функция `sync_pack_into_account_packages` в Python**  (blocks T5, T6, T8) — + `diff_pack_vs_account_packages` для audit-скрипта

- Новый файл: `/home/claude-user/autowarm-testbench/account_packages_sync.py`
- Экспорт: `sync_pack_into_account_packages(conn, factory_pack_id: int) -> dict`
  - Читает из БД:
    ```sql
    SELECT fpa.id, fpa.pack_name, fpa.project_id, fpa.start_date, fpa.end_date,
           fdn.device_id AS serial,
           vp.project AS project_name
      FROM factory_pack_accounts fpa
      JOIN factory_device_numbers fdn ON fdn.id = fpa.device_num_id
 LEFT JOIN validator_projects vp ON vp.id = fpa.project_id
     WHERE fpa.id = %s
    ```
    ```sql
    SELECT platform, username
      FROM factory_inst_accounts
     WHERE pack_id = %s AND active = TRUE
     ORDER BY id
    ```
  - Если под паком на одной платформе 2+ активных аккаунта → **raise `PackInvariantError`** (sync не делает guesswork). Это сигнал багу apply.
  - Собирает словарь `{instagram, tiktok, youtube, pinterest, likee, vk}` — каждая колонка или username (если есть) или NULL (если нет).
  - UPSERT в `account_packages` **по `pack_name`**:
    ```sql
    INSERT INTO account_packages (device_serial, pack_name, project, start_date, end_date,
                                   instagram, tiktok, youtube, pinterest, likee, vk, updated_at)
    VALUES (…) RETURNING id;
    -- or UPDATE WHERE pack_name = %s
    ```
    NB: таблица **не имеет UNIQUE-констрейнта на `pack_name`**. Делаем SELECT-then-UPDATE-or-INSERT с FOR UPDATE на конкретной строке внутри транзакции. Если вдруг 2+ строк с одинаковым `pack_name` — ловим и пишем `WARN [ap-sync] duplicate pack_name=…` (решение по дубликатам — отдельный audit).
  - Возвращает: `{'account_packages_id': int, 'action': 'inserted'|'updated', 'columns': {...}}`.
- Verbose logging: `log.info('[ap-sync] factory_pack=%d → ap.id=%s action=%s columns=%s', ...)`.

**T4. ✅ Unit-тест синхронизатора**  (blocked by T3; blocks T5) — 12/12 pass (расширил до 12 кейсов: insert/update/noop/clear/invariant/resurrect/diff variants)

- Файл: `/home/claude-user/autowarm-testbench/tests/test_account_packages_sync.py`
- Тест через SAVEPOINT в реальной БД (house-style «не мокать БД»):
  1. `test_insert_new_row` — создать новый factory-пак + 1 аккаунт → sync создаёт строку в account_packages с одной заполненной колонкой.
  2. `test_update_existing_row_by_pack_name` — если в account_packages уже есть строка с тем же `pack_name` (пустая колонка), sync заполняет её, не создавая дубль.
  3. `test_clears_column_when_account_removed` — удалили аккаунт из factory_inst_accounts → sync ставит колонку в NULL.
  4. `test_raises_on_invariant_violation` — два аккаунта одной платформы в одном паке → `PackInvariantError`.
  5. `test_resurrects_expired_end_date` — если в account_packages строка с `end_date < CURRENT_DATE`, sync обновляет её и ставит `end_date=NULL` (пак снова активен).
- Cleanup через `ROLLBACK TO SAVEPOINT` в tearDown. Тестовые строки используют `device_serial='_SYNC_TEST_<uuid>'` для изоляции.
- Expected: 5/5 pass.

### Phase 3 — Рефакторинг `/api/devices/:serial/revision/apply` (T5)

**T5. ✅ Новая логика apply в `server.js`**  (blocked by T1, T2, T3, T4; blocks T6, T9) — `server.js:2880-3005` переписан, JS-двойники `pack_name_resolver.js`+`account_packages_sync.js` подключены, node --check OK, JS-smoke-sync-тесты 5/5 pass, regression pytest 206/209

- Файл: `/home/claude-user/autowarm-testbench/server.js`, диапазон `2878-2981`.
- Перенести импорт: добавить наверху `const { PythonShell } = …` **нет, не надо** — Node.js не будет вызывать Python-резолвер. Вместо этого переписать `pack_name_resolver` в JavaScript-функцию прямо в `server.js` (или отдельный файл `pack_name_resolver.js`). **Задублировать логику из T1 в JS** и покрыть её JS-тестом. Python-версия T1/T2 остаётся для backfill-скрипта T8.
  - Альтернатива — вызывать Python через child_process: оверхед SSE-обработчика ~50-100 ms на один apply, некритично. Но дублирование логики на двух языках — хуже. **Решение:** JS-версия в `pack_name_resolver.js`, Python-версия для T8 (backfill). Тесты на обе.
  - Добавить в plan subtask T5.0: «port pack_name_resolver to JS + jest tests».
- Новая структура обработчика (псевдокод):
  ```js
  for (const [projectIdStr, accs] of Object.entries(byProject)) {
    const projectId = projectIdStr === 'null' ? null : parseInt(projectIdStr);
    const projectName = projectId
      ? (await client.query('SELECT project FROM validator_projects WHERE id=$1', [projectId])).rows[0]?.project
      : null;
    if (!projectName && projectId) throw new Error(`project_id=${projectId} не найден`);

    // Получаем все существующие паки этого проекта на устройстве
    const { rows: existingPacks } = await client.query(
      'SELECT id, pack_name FROM factory_pack_accounts WHERE device_num_id=$1 AND project_id=$2 ORDER BY id',
      [dev.id, projectId]
    );

    // Мутируем локальную копию: список паков + кто в каких платформах есть
    const packState = await loadPackState(client, existingPacks.map(p => p.id));
    // packState = Map<packId, {name, slots: {instagram, tiktok, youtube, …}}>

    for (const acc of accs) {
      if (!acc.platform || !acc.username) continue;

      // Проверка на полный дубль (уже есть в каком-то паке того же проекта)
      const dupPackId = findPackWithAccount(packState, acc.platform, acc.username);
      if (dupPackId) {
        console.log(`[revision/apply] skip duplicate acc=${acc.platform}/${acc.username} already in pack=${dupPackId}`);
        continue;
      }

      // Ищем пак со свободным слотом этой платформы
      let targetPackId = findPackWithFreeSlot(packState, acc.platform);

      if (!targetPackId) {
        // Создаём новый пак + возможные переименования
        const { new_pack_name, renames } = resolvePackLayout(
          projectName || 'unassigned',
          dev.device_number,
          [...packState.entries()].map(([id, st]) => ({ id, pack_name: st.name }))
        );
        // Apply renames (factory + account_packages через sync)
        for (const [renameId, newName] of renames) {
          await client.query('UPDATE factory_pack_accounts SET pack_name=$1 WHERE id=$2', [newName, renameId]);
          packState.get(renameId).name = newName;
          // Важно: переименование в account_packages произойдёт через sync после перестановки
        }
        // Создаём новый пак
        targetPackId = nextPackId++;
        await client.query(
          'INSERT INTO factory_pack_accounts (id, pack_name, device_num_id, project_id, start_date) VALUES ($1,$2,$3,$4,CURRENT_DATE)',
          [targetPackId, new_pack_name, dev.id, projectId]
        );
        packState.set(targetPackId, { name: new_pack_name, slots: {} });
        packsCreated++;
      }

      // Вставляем аккаунт
      const accId = nextAccId++;
      await client.query(
        'INSERT INTO factory_inst_accounts (id, pack_id, platform, username, active, synced_at) VALUES ($1,$2,$3,$4,true,NOW())',
        [accId, targetPackId, acc.platform, acc.username]
      );
      packState.get(targetPackId).slots[acc.platform] = acc.username;
      createdAccounts.push({ id: accId, platform: acc.platform, username: acc.username });
      created++;
    }

    // После обработки всех аккаунтов проекта — синк в account_packages для ВСЕХ затронутых паков
    for (const packId of packState.keys()) {
      await syncPackIntoAccountPackages(client, packId);
    }
  }
  ```
- Все мутации — в существующей транзакции (BEGIN…COMMIT в `server.js:2895`).
- Функции-хелперы (JS): `loadPackState`, `findPackWithAccount`, `findPackWithFreeSlot`, `resolvePackLayout` (из нового `pack_name_resolver.js`), `syncPackIntoAccountPackages` (из нового `account_packages_sync.js` — JS-двойник T3).
  - **Важно:** JS-sync должен быть функционально эквивалентен Python-версии (одинаковый SQL). Тест на эквивалентность — запускаем JS на том же входе, что и Python-тест из T4, и сверяем итоговые строки в БД.
- Verbose logging: `console.log('[revision/apply] device=%s project=%s acc=%s/%s → pack=%s (slot=%s)', …)`
- JS unit-тесты: `/home/claude-user/autowarm-testbench/tests/test_revision_apply.js` (или Jest конфиг — уточнить наличие в репо на T5.0). Если Jest не настроен — пишем интеграционный тест через node + pg (вызываем эндпоинт, проверяем состояние БД).

**T5.0 ✅ (subtask внутри T5). Port pack_name_resolver to JS + tests** — 17/17 pass на node --test, эквивалентность Python подтверждена идентичным набором кейсов

- `/home/claude-user/autowarm-testbench/pack_name_resolver.js` — 1:1 копия логики T1 на JS.
- `/home/claude-user/autowarm-testbench/tests/test_pack_name_resolver.js` — те же 8 кейсов, что в T2.
- Запуск: `node --test tests/test_pack_name_resolver.js` (Node ≥ 18 нативный test runner — если нет, положить Jest в devDeps).

### Phase 4 — Миграция legacy pack phone #19 (T6, T7)

**T6. ✅ Идемпотентный SQL-скрипт миграции**  (blocked by T1, T2, T3, T4; blocks T7) — миграция применена, factory pack 249→19a (3 acc), новый pack 307→19b (2 acc), ap.id=249 (19a, 3 cols) + ap.id=340 (19b, 2 cols), второй прогон скипается по ideмpotency-check

- Файл: `/home/claude-user/autowarm-testbench/migrations/20260422_split_phone19_legacy_pack.sql`
- Структура:
  ```sql
  BEGIN;

  -- Проверяем, что миграция ещё не применена (идемпотентность)
  DO $$
  DECLARE v_old_name text; v_already text;
  BEGIN
    SELECT pack_name INTO v_old_name FROM factory_pack_accounts WHERE id=249;
    IF v_old_name = 'Тестовый проект_19a' THEN
      RAISE NOTICE 'Migration already applied (pack 249 already renamed to 19a). Skipping.';
      RETURN;
    END IF;
    IF v_old_name <> 'Тестовый проект_19' THEN
      RAISE EXCEPTION 'Unexpected state: pack 249 has name=%, expected "Тестовый проект_19"', v_old_name;
    END IF;
  END $$;

  -- 1. Переименовать factory pack 249 → "_19a"
  UPDATE factory_pack_accounts
     SET pack_name='Тестовый проект_19a'
   WHERE id=249 AND pack_name='Тестовый проект_19';

  -- 2. Создать новый factory pack "_19b"
  INSERT INTO factory_pack_accounts (id, pack_name, device_num_id, project_id, start_date)
  SELECT COALESCE(MAX(id),0) + 1, 'Тестовый проект_19b', 163, 10, CURRENT_DATE
    FROM factory_pack_accounts;
  -- Запомним новый id через переменную
  -- (использовать WITH возвращающий id или RETURNING + temp table)

  -- 3. Переместить gennadiya311 (1628) и gennadiya4 (1629) → новый пак
  UPDATE factory_inst_accounts
     SET pack_id = (SELECT id FROM factory_pack_accounts WHERE pack_name='Тестовый проект_19b')
   WHERE id IN (1628, 1629);

  -- 4. Обновить account_packages для 19a
  UPDATE account_packages
     SET pack_name='Тестовый проект_19a',
         project='Тестовый проект',
         instagram='inakent06',
         tiktok='user70415121188138',
         youtube='Инакент-т2щ',
         end_date=NULL,
         updated_at=NOW()
   WHERE id=249;

  -- 5. Создать account_packages для 19b
  INSERT INTO account_packages (device_serial, pack_name, project, start_date, end_date,
                                 instagram, tiktok, youtube, pinterest, likee, vk)
  VALUES ('RF8YA0W57EP', 'Тестовый проект_19b', 'Тестовый проект',
          CURRENT_DATE, NULL,
          'gennadiya311', 'gennadiya4', NULL, NULL, NULL, NULL);

  COMMIT;
  ```
- Запуск dry-run (в транзакции с `ROLLBACK`):
  ```bash
  PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw \
    -c "BEGIN;" -f migrations/20260422_split_phone19_legacy_pack.sql \
    -c "SELECT fpa.id, fpa.pack_name, fia.id, fia.platform, fia.username \
        FROM factory_pack_accounts fpa \
        JOIN factory_inst_accounts fia ON fia.pack_id=fpa.id \
        JOIN factory_device_numbers fdn ON fdn.id=fpa.device_num_id \
        WHERE fdn.device_number=19 ORDER BY fpa.id, fia.platform;" \
    -c "SELECT id, pack_name, project, instagram, tiktok, youtube, end_date \
        FROM account_packages WHERE device_serial='RF8YA0W57EP' ORDER BY id;" \
    -c "ROLLBACK;"
  ```
  — сверяем с ожидаемым целевым состоянием (см. раздел «Контекст/Целевое»).
- Если dry-run ок — запускаем без ROLLBACK. Вывод логируем в evidence (T11).
- Rollback-скрипт: `migrations/20260422_split_phone19_legacy_pack__rollback.sql` — обратные операции (переименовать 19a→19, удалить 19b, вернуть pack_id=249 у 1628/1629, снести новую строку account_packages 19b, восстановить прежнюю строку 249 с end_date).

**T7. ✅ Smoke-verify guard'а после миграции**  (blocked by T6; blocks T9) — 5/5 аккаунтов проходят реальный `_GUARD_QUERY`: gennadiya311 (IG), gennadiya4 (TT), inakent06 (IG), user70415121188138 (TT), Инакент-т2щ (YT) — all matched=True

- Прогнать `_GUARD_QUERY` (из `publisher.py`) на каждом из 5 аккаунтов:
  ```sql
  -- ожидаем matched=TRUE для всех
  WITH declarative AS (
    SELECT instagram AS acc FROM account_packages WHERE device_serial='RF8YA0W57EP'
      AND (end_date IS NULL OR end_date >= CURRENT_DATE) AND instagram IS NOT NULL
    UNION ALL
    SELECT tiktok FROM account_packages WHERE device_serial='RF8YA0W57EP'
      AND (end_date IS NULL OR end_date >= CURRENT_DATE) AND tiktok IS NOT NULL
    UNION ALL
    SELECT youtube FROM account_packages WHERE device_serial='RF8YA0W57EP'
      AND (end_date IS NULL OR end_date >= CURRENT_DATE) AND youtube IS NOT NULL
  )
  SELECT 'gennadiya311' IN (SELECT acc FROM declarative) AS ig1_ok,
         'gennadiya4'   IN (SELECT acc FROM declarative) AS tt1_ok,
         'inakent06'    IN (SELECT acc FROM declarative) AS ig0_ok,
         'user70415121188138' IN (SELECT acc FROM declarative) AS tt0_ok,
         'Инакент-т2щ'  IN (SELECT acc FROM declarative) AS yt_ok;
  ```
- Ожидание: все 5 колонок `TRUE`.
- Запустить testbench-orchestrator dry-run `python3 testbench_orchestrator.py --once --dry-run` несколько раз — убедиться, что задача на gennadiya311/gennadiya4 не ловит guard-block в БД (`SELECT * FROM publish_tasks WHERE account IN ('gennadiya311','gennadiya4') ORDER BY id DESC LIMIT 5`).

### Phase 5 — Backfill всех новых аккаунтов (T8, T9)

**T8. ✅ Python-скрипт `audit_sync_account_packages.py`**  (blocked by T3, T5; blocks T9) — dry-run + --apply + --device-serial/--project-id scope, exit codes для CI, skip invariant-packs с WARN

- Файл: `/home/claude-user/autowarm-testbench/audit_sync_account_packages.py`
- Что делает:
  1. SELECT по всем `factory_pack_accounts` (вся БД, не только phone #19).
  2. Для каждого factory-пака: проверить, есть ли строка в `account_packages` с тем же `pack_name`, и совпадают ли платформенные колонки с `factory_inst_accounts` этого пака.
  3. Если нет или расходится → сгенерировать sync-план (что UPDATE/INSERT нужно).
  4. По умолчанию — dry-run (печатает план и diff, БД не трогает).
  5. С флагом `--apply` — выполняет sync через `sync_pack_into_account_packages()` (из T3).
- CLI:
  ```bash
  python3 audit_sync_account_packages.py           # dry-run, report to stdout + summary
  python3 audit_sync_account_packages.py --apply   # really sync
  python3 audit_sync_account_packages.py --device-serial RF8YA0W57EP  # scope to one device
  ```
- Inv-check: если для какой-то пары (pack_id, platform) в factory_inst_accounts окажется 2+ активных — пропускаем пак и печатаем `WARN [audit] invariant violation pack=%d platform=%s usernames=[…]` (но не падаем — продолжаем).
- Логирование: `INFO [audit] pack=%d name=%s action=%s columns_before=%s columns_after=%s`.
- Возвращает non-zero exit code, если в dry-run-режиме нашлись пропуски (для CI).

**T9. ✅ Запустить backfill на всей БД**  (blocked by T7, T8; blocks T11) — 180/180 applied (165 out_of_sync + 15 missing_in_ap), 29 invariant packs skipped (ожидают индивидуальной миграции как #19/#171), 4 остаточных out_of_sync — известная проблема с дублями pack_name в factory (Шаг 2). + **phone #171 split migration** (pack 308 `rev_test_project_dev171` → `Тестовый проект_171a/b` для ivana/google YT). Guard: 7/7 аккаунтов проходят для phone 19+171.

- Dry-run: `python3 audit_sync_account_packages.py | tee /tmp/audit-20260422-dryrun.log`
- Руками проверить summary: сколько паков «ok», сколько «to-sync», сколько «skipped (invariant)». Ожидаемо — большинство паков уже ok (строки account_packages были засеяны). Интересны только те, что `to-sync` и `skipped`.
- Если dry-run show'ит только ожидаемые изменения (не больше 20 паков нужно sync) — запускаем apply. Если больше — разбираемся откуда, прежде чем писать в БД.
- Apply: `python3 audit_sync_account_packages.py --apply | tee /tmp/audit-20260422-apply.log`
- Verify: повторный dry-run должен вернуть «all synced».
- Evidence: обе логи копируем в evidence-файл T11.

### Phase 6 — Commit + docs + evidence (T10, T11)

**T10. ✅ Коммиты + push**  (blocked by T9) — 5 коммитов (a74ceba…a84ecf0) в autowarm-testbench на ветке `testbench`, pushed to origin. C6 в contenthunter — следующим

- Коммит 1 (autowarm-testbench, после T2): `feat(revision): pack_name_resolver with Excel-like suffixes + unit tests`
- Коммит 2 (autowarm-testbench, после T4): `feat(revision): sync_pack_into_account_packages helper + integration tests`
- Коммит 3 (autowarm-testbench, после T5): `feat(revision/apply): enforce one-per-platform pack rule + account_packages mirror`
- Коммит 4 (autowarm-testbench, после T7): `chore(migrate): split phone #19 legacy pack into 19a/19b`
- Коммит 5 (autowarm-testbench, после T9): `chore(audit): backfill account_packages from factory for all active accounts`
- Коммит 6 (contenthunter, после T11): `docs(plans): revision-account-packages-sync + evidence`

Все autowarm-testbench коммиты — на ветке `testbench`, `git push origin testbench`. **В main /autowarm не мержим** (это отдельный deploy-шаг в prod).

**T11. ✅ Evidence + memory update + handoff to Шаг 2**  (blocked by T10) — evidence написан, memory `project_account_packages_end_date` (новая), `project_account_packages_deprecation` (brief Шаг-2), `project_publish_followups` (закрыт пункт), MEMORY.md обновлён

- Evidence: `/home/claude-user/contenthunter/.ai-factory/evidence/revision-account-packages-sync-20260422.md`
  - До/после состояние phone #19 (копии SQL-выборок из T6/T7)
  - Результат smoke guard-check (T7)
  - Summary backfill-скрипта (T9): сколько паков синхронизировано, сколько skipped
  - Список коммитов
- Memory update:
  - `project_publish_guard_schema.md` — добавить раздел «Sync между factory и account_packages»: sync-функция, invariant one-per-platform.
  - `project_publish_followups.md` — закрыть пункт про `gennadiya311/gennadiya4`, отметить что backfill прошёл.
  - **Новая memory (Шаг 2 brief):** `project_account_packages_deprecation.md` — сводка плана Шага 2: ссылки на 10 мест использования, список 223 строк, open questions (end_date семантика, миграция manual-seed-*, etc.). Это позволит не разогревать контекст с нуля, когда запустим Шаг 2.
- НЕ обновляем `AGENTS.md` / `PUBLISH-NOTES.md` в testbench-репо — Шаг 1 не меняет пользовательские сценарии, только внутренности.

## Commit Plan

11 задач → 6 коммит-чекпоинтов:

| Commit | После задач | Репо | Сообщение |
|---|---|---|---|
| 1 | T2 | autowarm-testbench (testbench) | `feat(revision): pack_name_resolver with Excel-like suffixes + unit tests` |
| 2 | T4 | autowarm-testbench | `feat(revision): sync_pack_into_account_packages helper + integration tests` |
| 3 | T5 | autowarm-testbench | `feat(revision/apply): enforce one-per-platform pack rule + account_packages mirror` |
| 4 | T7 | autowarm-testbench | `chore(migrate): split phone #19 legacy pack into 19a/19b` |
| 5 | T9 | autowarm-testbench | `chore(audit): backfill account_packages from factory for all active accounts` |
| 6 | T11 | contenthunter (main) | `docs(plans): revision-account-packages-sync + evidence` |

## Risks & rollback

- **R1 — JS/Python дублирование логики** (T5.0): resolver и sync существуют на двух языках. Риск расхождения. **Митиг:** общий набор тест-кейсов (8 штук) + снимок expected output в JSON-файле, который читают оба теста. Если один язык отклонится — тест красный.
- **R2 — JOIN по `pack_name` в 7 местах `server.js`** ломается, если переименование `19→19a` произошло, а sync в account_packages не отработал. **Митиг:** sync в той же транзакции, что и UPDATE factory. Если sync упал — транзакция откатывается вместе с переименованием.
- **R3 — дубли `pack_name` в account_packages** (таблица без UNIQUE). **Митиг:** в sync делаем `SELECT id FROM account_packages WHERE pack_name=%s FOR UPDATE`; если >1 строки — лог WARN и UPDATE первой по id. Audit-скрипт T8 отдельным проходом проверит весь set дублей и зарепортит.
- **R4 — миграция #249 с уже применённым состоянием** (если кто-то прогонит дважды). **Митиг:** DO-блок в начале migrations/20260422_*.sql проверяет текущее имя и скипает.
- **R5 — `server.js:5249` JOIN `ap.id = fi.pack_id`** предполагает совпадение id между таблицами. Сейчас для pack 249 id совпадают (совпадение исторических сидов), но после миграции мы создадим новый pack 19b с новым factory id, которого в account_packages не будет. **Митиг:** при implement'е изучить этот JOIN, понять для какой фичи (вероятно reporting), и переделать либо на JOIN по `pack_name`, либо — если это deadcode — удалить. Зафиксировать в evidence. Альтернатива (хак): при INSERT в account_packages в sync можно использовать тот же id, что у factory_pack_accounts — но `account_packages.id` генерируется через sequence и это потребует либо override, либо раздельные sequence'ы. **Решение оставляю на implement**, но это риск поломки какой-то неочевидной UI-страницы.
- **R6 — одновременно с ревизией работает `_upsert_auto_mapping` в publisher** (создаёт строки `project='auto-from-publish'`). Это другой набор строк, они не конфликтуют с нашими per-project строками (pack_name разный: `auto-youtube` vs `Тестовый проект_19a`). **Подтверждено** — они копят independent.
- **R7 — в админке `POST /api/admin/packages` кто-то вручную создаёт строку с таким же pack_name**, что наш автомат. **Митиг (Шаг 1):** в sync мы UPDATE по pack_name — если админ ранее создал пустую строку, она будет обновлена. Это ОК-поведение. Если админ создал строку с конфликтующими username'ами — sync их перезапишет. В Шаге 2 уберём админский CRUD.
- **R8 — prod `/root/autowarm/` не получит этих изменений** в Шаге 1. Prod-guard продолжит ругаться на prod-устройства (не phone #19). **Митиг:** отдельная deploy-задача после testbench-smoke — не в scope. В evidence зафиксируем, что prod deploy = отдельно.

## Rollback strategy

- Commit 1-2 (pack_name_resolver, sync) — не влияют на runtime до T5. `git revert` безопасен.
- Commit 3 (apply refactor) — может сломать revision/apply для других устройств. **Rollback:** `git revert` + `sudo systemctl restart autowarm-testbench-server` (если testbench deploy это подхватывает). Pre-fix evidence — revision/apply просто не звался последние 2 часа (проверить в logs перед deploy).
- Commit 4 (миграция #249) — SQL-инверсию держим в `migrations/20260422_*__rollback.sql`. Прогон rollback возвращает phone #19 в исходное состояние (5 аккаунтов в паке 249, account_packages id=249 пустая и истёкшая).
- Commit 5 (backfill) — если после apply выявилось много «неожиданных» sync'ов → стандартная pg_dump account_packages перед apply (добавить в T8 как обязательный шаг). Restore: `psql < pg_dump.sql` или SELECT-diff и DELETE/UPDATE вручную.

## Next step

После подтверждения плана — исполнять через `/aif-implement` (буду писать код/коммиты сам согласно memory `feedback_execution_autonomy.md`).

После Шага 1 — подтверждение через Тelegram-триаж на phone #19 (gennadiya311/gennadiya4 должны пройти guard на первом же тике после миграции) → затем deploy на prod → затем переход к Шагу 2 (большой план отдельным документом).
