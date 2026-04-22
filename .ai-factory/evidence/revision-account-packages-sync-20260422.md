# Evidence — Ревизия → account_packages sync (Шаг 1)

**Дата:** 2026-04-22 UTC
**Plan:** [`revision-account-packages-sync-20260422.md`](../plans/revision-account-packages-sync-20260422.md)
**Ветка:** `testbench` (autowarm-testbench), `main` (contenthunter)
**Статус:** ✅ все 11 задач выполнены, 5 коммитов запушены в `testbench`

## Коммиты

| # | Hash | Repo | Сообщение |
|---|------|------|-----------|
| C1 | `a74ceba` | autowarm-testbench | feat(revision): pack_name_resolver with Excel-like suffixes + unit tests |
| C2 | `86802c7` | autowarm-testbench | feat(revision): sync_pack_into_account_packages helper + integration tests |
| C3 | `0b1932e` | autowarm-testbench | feat(revision/apply): enforce one-per-platform pack rule + account_packages mirror |
| C4 | `8ef72f9` | autowarm-testbench | chore(migrate): split phone #19 legacy pack into 19a/19b |
| C5 | `a84ecf0` | autowarm-testbench | chore(audit): backfill account_packages from factory for all active accounts |
| C6 | `ba91401` | contenthunter | docs(plans): revision-account-packages-sync + evidence |
| C7 | `ca1bb8c` | autowarm-testbench | fix(packages): JOIN account_packages by pack_name, not by numeric id |

## Phone #19 — до/после

### Before (2026-04-22 09:22 UTC, момент регистрации новых аккаунтов)

**factory_pack_accounts (1 пак):**
```
id=249  pack_name='Тестовый проект_19'  project_id=10  device_num_id=163
```

**factory_inst_accounts (5 аккаунтов в одном паке — нарушение one-per-platform):**
```
1528  yt=Инакент-т2щ         (синхронизирован 2026-03-23)
1529  ig=inakent06           (2026-03-23)
1530  tt=user70415121188138  (2026-03-23)
1628  ig=gennadiya311        (2026-04-22 09:22)  ← новый
1629  tt=gennadiya4          (2026-04-22 09:22)  ← новый
```

**account_packages (3 строки, реально активна только одна):**
```
id=249  pack_name='Тестовый проект_19'   project='Тестовый проект'   колонки пустые   end_date=2026-01-10 (истёк)
id=295  pack_name=NULL                   project='manual-seed-20260417'   ig=inakent06,tt=user70415121188138,yt=Инакент-т2щ   end_date=NULL
id=319  pack_name='auto-youtube'         project='auto-from-publish'      yt=Инакент-т2щ (потом и ig=inakent06 добавился)   end_date=NULL
```

**Guard (`publisher.py:_GUARD_QUERY`):**
- IG: `[guard] gennadiya311 не в списке известных аккаунтов для RF8YA0W57EP/Instagram` (известны: `inakent06`)
- TT: `[guard] gennadiya4 не в списке известных аккаунтов для RF8YA0W57EP/TikTok` (известны: `user70415121188138`)

### After

**factory_pack_accounts (2 пака, один per платформа):**
```
id=249  pack_name='Тестовый проект_19a'  project_id=10  (старые)
id=307  pack_name='Тестовый проект_19b'  project_id=10  (новые)
```

**factory_inst_accounts (переразвязка pack_id):**
```
1528  yt=Инакент-т2щ          pack=249 (19a)
1529  ig=inakent06            pack=249 (19a)
1530  tt=user70415121188138   pack=249 (19a)
1628  ig=gennadiya311         pack=307 (19b)   ← переведён миграцией
1629  tt=gennadiya4           pack=307 (19b)   ← переведён миграцией
```

**account_packages (5 строк, все активны):**
```
id=249  'Тестовый проект_19a'  'Тестовый проект'     ig=inakent06,tt=user70415121188138,yt=Инакент-т2щ  end_date=NULL
id=340  'Тестовый проект_19b'  'Тестовый проект'     ig=gennadiya311,tt=gennadiya4                      end_date=NULL
id=295  NULL                   'manual-seed-20260417' (без изменений)
id=319  'auto-youtube'         'auto-from-publish'   (без изменений)
```

**Guard final check (все 5 аккаунтов):**
```
OK  Instagram/gennadiya311              matched=True  known=[gennadiya311, inakent06]
OK  TikTok   /gennadiya4                matched=True  known=[gennadiya4, user70415121188138]
OK  Instagram/inakent06                 matched=True
OK  TikTok   /user70415121188138        matched=True
OK  YouTube  /Инакент-т2щ               matched=True  known=[Инакент-т2щ]
```

## Phone #171 — до/после

### Before (сразу после user-инициированной ревизии через UI)

`factory_pack_accounts.id=308 "rev_test_project_dev171"` (старая схема именования) с 2 YT-аккаунтами в одном паке: `ivana` (id=1630), `google` (id=1631). `account_packages` для `RF8Y90GCWWL` пуст. Нарушение invariant.

### After migration (`migrations/20260422_split_phone171_legacy_pack.sql`)

```
factory_pack_accounts 308  'Тестовый проект_171a'  YT=ivana
factory_pack_accounts 309  'Тестовый проект_171b'  YT=google
account_packages      341  'Тестовый проект_171a'  youtube=ivana   end_date=NULL
account_packages      342  'Тестовый проект_171b'  youtube=google  end_date=NULL
```

Guard: `OK YouTube/ivana`, `OK YouTube/google`.

## Backfill (T9) — итог

| Категория | Паков | Комментарий |
|---|---|---|
| in_sync | 4 | phone 19a/19b + phone 171a/171b |
| out_of_sync | 165 | затерты в ap, end_date прошёл — warm-up завершён, backfill заполнил колонки из factory |
| missing_in_ap | 15 | `rev_*` паки созданы старой ревизией без ap-sync |
| **applied** | **180** | 0 failed |
| invariant skipped | 29 | `2+ active accounts one platform` — ждут индивидуальной миграции или Шаг-2 |
| остаточно out_of_sync после apply | 4 | дубль `pack_name` в factory_pack_accounts (два ряда `Content hunter_84`, два `Content hunter_105`) — baseline bug |

**Важное уточнение semantics (memory `project_account_packages_end_date.md`):** `end_date` — конец warm-up'а, не деактивация. Past end_date + пустые колонки = пак прогрет, просто whitelist не заполнен. Backfill — нормальный и безопасный.

Файлы логов:
- `/tmp/audit-20260422-dryrun.log`
- `/tmp/audit-20260422-dryrun-full.log`
- `/tmp/audit-20260422-apply.log`
- `/tmp/ap-backup-20260422.sql` — бэкап account_packages перед apply

## Тесты

| Тест | Pass | Детали |
|---|---|---|
| `tests/test_pack_name_resolver.py` | 17/17 | suffix math, resolve_pack_layout, Russian names, overflow z→aa→aaa |
| `tests/test_pack_name_resolver.test.js` | 17/17 | JS-двойник с идентичным набором кейсов |
| `tests/test_account_packages_sync.py` | 12/12 | insert/update/noop/clear/invariant/resurrect/diff, SAVEPOINT+ROLLBACK |
| `tests/test_account_packages_sync.test.js` | 5/5 | JS-smoke на реальной БД |
| **Regression (full pytest)** | **206 passed, 3 skipped** | без новых падений |

## Архитектурный итог Шага 1

1. **Новая модель имён паков:** `<validator_projects.project>_<device_number>[suffix]` с Excel-like суффиксами; первый пак проекта на устройстве — без суффикса, при появлении второго первый переименовывается в `_a`, новый получает `_b`. Реализовано в `pack_name_resolver.{py,js}`.
2. **Инвариант one-per-platform** на factory-паках. Нарушение — `PackInvariantError` из sync'а (не guesswork).
3. **Auto-sync factory → account_packages** по `pack_name` внутри транзакции `revision/apply`. Publisher guard сразу видит свежий whitelist.
4. **Идемпотентные миграции** phone #19 и #171 — с DO-блоком, проверяющим текущее имя пака; rollback-скрипт для #19 (для #171 — аналогичный паттерн при необходимости).
5. **Audit/backfill CLI** `audit_sync_account_packages.py` — dry-run + `--apply` + `--device-serial`/`--project-id` scope, exit codes для CI.

## Bug fix post-apply: JOIN by pack_name

Сразу после apply пользователь заметил, что UI `/api/packages` для новых паков 19b / 171a / 171b показывал `project='manual-seed-round-6-20260418'` вместо `Тестовый проект`. **Root cause:** два эндпоинта (`server.js:2394` GET `/api/packages` и `server.js:5340` getSocialAccounts) JOIN'или `account_packages` по **числовому id** (`ON ap.id = fpa.id` / `ON ap.id = fi.pack_id`) — а ID в factory и ap независимы и случайно совпали со строками seed'а round-6 (которые имели pack_name="round-6-null-seed").

**Fix (C7):** оба JOIN переписаны на `LEFT JOIN LATERAL` по `ap.pack_name = fpa.pack_name` с `ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 1`. После фикса все 4 новых пака корректно рендерятся как "Тестовый проект". Regression 206 py + 22 js.

## Остающиеся задачи (Шаг 2)

См. `memory/project_account_packages_deprecation.md`:

- 29 invariant-паков, требующих разбиения (список в `/tmp/audit-20260422-dryrun-full.log` с префиксом `WARN [audit] invariant violation`).
- 4 duplicate `pack_name` в `factory_pack_accounts` (Content hunter_84, Content hunter_105) — нужен dedupe.
- Консолидация модели: удалить `account_packages` как отдельную таблицу, переписать `publisher.py:_GUARD_QUERY`, `_upsert_auto_mapping`, 7 эндпоинтов `server.js`.
- Prod deploy: изменения живут в testbench-репо. Production `/root/autowarm/` ещё на старом коде. Планируется после observation-окна на testbench.

## Deploy note

Изменения на ветке `testbench` в `autowarm-testbench`. Production-сервер `/root/autowarm/` не получил их — guard'у старого production-кода всё ещё нужен account_packages, и backfill уже заполнил whitelist для всех 180 подошедших паков (БД общая, openclaw@localhost). Это значит: prod сразу получил **разблокировку 180 паков** без деплоя кода. Это безопасно (end_date=NULL корректен, прогрев окончен). Новый код revision/apply начнёт работать только после выкатки testbench→prod (отдельная задача).
