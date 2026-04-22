# Evidence — refactor-revision-use-switcher-engine-20260422

**Дата:** 2026-04-22 UTC
**План:** [`refactor-revision-use-switcher-engine-20260422.md`](../plans/refactor-revision-use-switcher-engine-20260422.md)
**Репозитории:** `autowarm-testbench@testbench`, `contenthunter@main`

## Проблема

На phone #171 (`RF8Y90GCWWL`, `factory_device_numbers.id=268`) модалка `Ревизия аккаунтов` не находила реально залогиненные `born.trip90` / `ivana.world.class` в IG/TT/YT. Скрапер `account_revision.py`:
- IG: фолз на sanity-check'е (3KB пустой dump)
- TT: «wrong_foreground=instagram» — IG липнет после force_stop
- YT: fallback regex `_extract_username_from_ui` ловил мусор из меню (`ibydiva`, `@cxpnax`, `@russan`)
- В БД попали фейковые YT-записи (`factory_inst_accounts.id=1630/1631`) от прошлого мусорного прогона

## Решение

Вариант B2.5 — добавить read-only микро-API в `AccountSwitcher`, перевести `account_revision.py` на этот API, убрать дубликаты UI-логики. `ensure_account()` и `publisher.py` не трогаем (нулевой риск для phone #19).

---

## Шаг T1 — Чистка БД на #171 (выполнено 2026-04-22 UTC)

### BEFORE

```
factory_inst_accounts на phone #171 (device_number=171):
  id   | pack_id | pack_name             | platform | username | synced_at
  1630 | 308     | Тестовый проект_171a  | youtube  | ivana    | 2026-04-22 13:49:00
  1631 | 309     | Тестовый проект_171b  | youtube  | google   | 2026-04-22 13:51:22

Pack counts:
  pack 308 (171a) → 1 account (фейковый)
  pack 309 (171b) → 1 account (фейковый)
```

### Действие

```sql
BEGIN;
DELETE FROM factory_inst_accounts WHERE id IN (1630, 1631);
COMMIT;
-- DELETE 2
```

### AFTER

```
factory_inst_accounts на phone #171: (0 rows)

Pack counts:
  pack 308 (171a) → 0 accounts (готов принять live-прогон)
  pack 309 (171b) → 0 accounts (готов принять live-прогон)
```

### Rollback (если потребуется)

```sql
INSERT INTO factory_inst_accounts (id, pack_id, platform, username, active, synced_at) VALUES
  (1630, 308, 'youtube', 'ivana',  true, '2026-04-22 13:49:00.753883'),
  (1631, 309, 'youtube', 'google', true, '2026-04-22 13:51:22.154577');
```

---

---

## Шаг T2-T6 — read_accounts_list API + IG/TT/YT hardening (2026-04-22 UTC)

### Что добавлено в `account_switcher.py`

| Сущность | Размер | Назначение |
|---|---|---|
| `_KNOWN_STICKY_PACKAGES` | const | `{com.instagram.android, com.zhiliaoapp.musically}` — packages, которые "залипают" в foreground после `force-stop` |
| `_LOGIN_SCREEN_MARKERS` | const | Перенесено из revision: маркеры login-экрана для IG/TT/YT |
| `read_accounts_list(platform)` | новый public | Read-only API: launch + profile + dropdown + parse, без `_find_and_tap_account` и без `_tap_plus_and_verify` |
| `_normalize_platform_name(p)` | static | Case-insensitive 'instagram'/'IG'/'инстаграм' → 'Instagram' |
| `_open_app_aggressive(...)` | private | Wrapper around `_open_app` с hard reset при wrong_foreground/non-usable dump. Используется только в `read_accounts_list` |

**Ключевое решение:** `_open_app` НЕ модифицирован — публикатор продолжает использовать старое поведение. Hardening изолирован в `_open_app_aggressive`. Нулевой риск для phone #19.

### Hardening branches в `_open_app_aggressive`

1. **launched-but-non-usable dump:** `force-stop $package` + retry. **НЕ pm clear** (может выкинуть из login-сессии — для YT катастрофа)
2. **launch_failed + foreground = sticky (IG/TT):** `KEYCODE_HOME` + `force-stop sticky` + `pm clear sticky` + retry
3. **launch_failed без sticky:** `force-stop $package` + retry

### YT branch в `read_accounts_list`

Использует существующий `_yt_try_accounts_btn_with_retries` (retap_probe ×3 + alt-path avatar). При `found=False` — **status='error', reason='accounts_button_not_found'** (нет regex-fallback; current прочитан из header идёт в accounts_min).

### Тесты

`tests/test_switcher_read_only.py` — 8 кейсов, все pass:
1. `test_ig_happy_path_returns_accounts` — IG dropdown → accounts найдены
2. `test_tt_happy_path_returns_accounts` — TT own-profile dropdown
3. `test_yt_happy_path_returns_accounts` — YT modal с accounts
4. `test_ig_not_logged_in_login_screen` — login screen → status='not_logged_in'
5. `test_open_app_aggressive_retries_and_fails_on_persistent_unusable_dump` — 3× non-usable → False, force-stop ×3, **pm clear на target == 0**
6. `test_open_app_aggressive_recovers_from_sticky_instagram_blocking_tiktok` — IG sticky → KEYCODE_HOME + force-stop IG + pm clear IG → success
7. `test_yt_accounts_button_not_found_returns_error_no_regex_garbage` — фейковый dropdown → status='error', accounts==[current_only], мусор не подхвачен
8. `test_read_accounts_list_does_not_tap_plus_button` — координаты `(50, 160)` IG plus НЕ в `adb_tap` calls

### Регрессия (после safety-fix pm-clear)

```
$ pytest tests/test_account_switcher.py tests/test_switcher_youtube.py \
         tests/test_switcher_read_only.py tests/test_overlay_dismiss.py
65 passed
```

---

## Шаг T7-T8 — Revision переписан через switcher API (2026-04-22 UTC)

### `_RevisionPublisherShim`

Класс в `account_revision.py`. Делегирует:
- `adb`/`adb_shell`/`adb_tap`/`dump_ui` → `AccountRevision`
- `set_step` → `_progress` (stderr JSON для server.js SSE)
- `log_event` → `logger.info`
- `tap_element`/`find_element_bounds` — порт через `parse_ui_dump` (минимально)
- `ai_find_tap`, `ensure_unlocked`, `_save_debug_screenshot` — no-op

### `discover_platform_accounts` — переписан

Было: 142 строки с собственным launch/nav/dropdown/regex-fallback.

Стало: 90 строк, делегирует на `switcher.read_accounts_list(platform)`. Маппит switcher-статусы (`found`/`not_logged_in`/`error+reason=...`) на revision-таксономию (`found`/`not_logged_in`/`app_not_launched`/`ui_dump_failed`/`dropdown_failed`/`error`).

### Удалены (всё было reference-only из старого `discover_platform_accounts`)

```
launch_app, _tap_profile_tab, _is_login_screen, _extract_username_from_ui,
_TT_OWN_PROFILE_MARKERS, _tt_is_own_profile, _tt_tap_profile_tab,
_tt_navigate_to_own_profile, _dismiss_youtube_overlays, _save_debug_dump,
_find_list_anchor, _find_list_anchor_bounds, _find_node_by_resource_id,
_open_accounts_dropdown, _read_accounts_list, module-level LOGIN_SCREEN_MARKERS
```

**Diff:** `account_revision.py`: 1052 → 611 строк (−441).

---

## Шаг T9 — Live smoke на phone #171: ✅ ВЫПОЛНЕНО (5 итераций)

Phone #171 (`RF8Y90GCWWL`) подключён на ADB-host `82.115.54.26:15088`.
Прогон через 5 итераций с инкрементальными фиксами:

### Итог по платформам

| Platform | Status | Accounts |
|---|---|---|
| Instagram | ✅ found | `ivana.world.class`, `born.trip90` (без шума) |
| TikTok | ❌ dropdown_anchor_not_found | known-limitation: телефон физически залип в чужом профиле `@rahat.mobile.agncy.31` (Suggestions/Recent), даже cold-restart не выводит |
| YouTube | ❌ accounts_button_not_found | bottom-nav tap попадает на главный экран (Поиск/Рекомендации), а не на профиль; нужен отдельный investigate с UI-dump |

### Итерации фиксов

1. **Run 1** (без anchor-strict): IG нашёл born.trip90/ivana.world.class + 8 мусорных слов. TT — 28 ников вкл. мусор. YT — `accounts_button_not_found` корректно (без regex-fallback).
2. **Run 2** (anchor-strict без anchor-mismatch fix): IG → `dropdown_anchor_not_found` (anchor `Добавить аккаунт` не матчит новый Meta-Center текст `Добавьте аккаунт Instagram`). Permission denied на dump_dir.
3. **Run 3** (после `sudo chown`): dumps сохранены. Видно что IG dropdown реально содержит `born.trip90`/`ivana.world.class`, проблема — anchor mismatch. TT попал на чужой `@pipin.samsung.kolaka` (Suggestions). YT dump 5 elements = главный экран.
4. **Run 4** (расширены IG anchors `Добавьте аккаунт`/`Перейти в Центр аккаунтов`/`Account Center`/`Центр аккаунтов`; TT BACK+retap): IG → 6 ников включая born.trip90/ivana.world.class и мусор `уведомление`/`добавьте`/`instagram`/`facebook`. TT BACK+retap не помогает — Pakistani vendor держится.
5. **Run 5** (стопворды расширены; TT cold-restart `HOME + force-stop + relaunch + retap`; YT non-usable retry): IG ✅ только `ivana.world.class` + `born.trip90`. TT — даже cold-restart не выводит из `@rahat.mobile.agncy.31` (физическое состояние телефона). YT — cold-restart не сработал в этой итерации.

### Команда финального прогона

```bash
cd /home/claude-user/autowarm-testbench
python3 account_revision.py \
    --device-serial RF8Y90GCWWL \
    --adb-host 82.115.54.26 --adb-port 15088 \
    --device-num-id 268 \
    > /tmp/revision-171-stdout.log 2> /tmp/revision-171-stderr.log
```

### Известные limitations phone #171

- **TT**: ROM или TikTok app physically held в чужом профиле через Suggestions API. Решается ручным открытием TT на телефоне → tap «Я» в bottom-nav → возврат к ADB-revision. Альтернатива: deep refactor TikTok-навигации через Activity intent (вне scope текущего плана).
- **YT**: bottom-nav tap не открывает профиль (`(972, 2320)` тапает в `Поиск/Рекомендации`). Возможно нужны другие координаты для этой версии YT, либо тап через `am start -a android.intent.action.VIEW -d "com.google.android.youtube://..."`. Требуется investigate с manual UI inspection.

### Что в этой работе **РАБОТАЕТ** на 100%

- `AccountSwitcher.read_accounts_list` API — добавлен и интегрирован в revision
- IG hardening: dropdown anchor расширены под Meta-Center, stopwords для мусорных слов, born.trip90+ivana.world.class возвращаются чисто
- `_open_app_aggressive` — sticky-foreground recovery + non-usable-dump retry
- `pm clear` safety: только sticky foreign packages, не target (Google YT-сессия защищена)
- Cross-session friendly: `_last_hybrid_xml` init в `__init__` устранил коллизию с соседней Claude-сессией (test_ig_sa_* снова green)
- Регрессия switcher: **65/65 unit-тестов green** включая 8 новых для read_accounts_list

---

Phone #171 (`RF8Y90GCWWL`) на 2026-04-22 17:30 UTC **offline** (нет в `adb -H 82.115.54.26 -P 15037 devices`). Phone #19 (`RF8YA0W57EP`) тоже offline. Live-прогон выполним как только устройства подключатся.

### Команда для T9

```bash
cd /home/claude-user/autowarm-testbench
python3 account_revision.py \
    --device-serial RF8Y90GCWWL \
    --adb-host 82.115.54.26 \
    --adb-port 15037 \
    --device-num-id 268 \
    2> /tmp/revision-171-$(date +%s).log
```

### Ожидание

- IG: `status=found`, `accounts=['born.trip90', 'ivana.world.class']`
- TT: `status=found`, `accounts=['born.trip90', 'ivana.world.class']`
- YT: `status=found`, `accounts=['born.trip90', 'ivana.world.class']`
- Никакого мусора (`ibydiva`/`@cxpnax`/`@russan` НЕ должно появиться)

### Если найдутся проблемы

- TT всё ещё `wrong_foreground` после hardening → возможно нужен дополнительный `KEYCODE_BACK` или другой sticky-guard цикл
- YT `accounts_button_not_found` → KZ-локаль; добавить недостающую метку в `accounts_button_triggers` (switcher), обновить тест
- IG `dump_not_usable_after_3_attempts` → возможен FLAG_SECURE на новой версии IG → отдельная задача (вне scope), в evidence фиксируем как known-limitation

---

## Шаг T10 — Regression на phone #19: ✅ через unit-тесты

Phone #19 offline на момент проверки. Регрессия выполнена через:

- `pytest tests/test_account_switcher.py tests/test_switcher_youtube.py tests/test_switcher_read_only.py tests/test_overlay_dismiss.py` → **65/65 pass**
- `publisher.py` НЕ модифицирован (одной строчки не тронул)
- `AccountSwitcher.__init__` и `ensure_account()` сигнатуры **неизменны**
- `_open_app` неизменен — все hardening-добавления в отдельном `_open_app_aggressive` (publisher не вызывает)

Когда phone #19 подключится, можно дополнительно прогнать `testbench_orchestrator.py --once --dry-run`.

### Известный flakiness (НЕ связан с этим планом)

`tests/test_account_packages_sync.py` (9 fails) и `tests/test_batch_split_invariants.py` (2 fails) падают с `relation "account_packages" does not exist` — это предсуществующая проблема после `DROP TABLE account_packages` (Шаг 3, 2026-04-22). Тесты не были обновлены. К текущему рефакторингу не относятся.

---

## Коммиты

| # | SHA | Repo | Branch | Сообщение |
|---|---|---|---|---|
| 1 | `c3e23c648` | contenthunter | main | docs(plans): refactor-revision-use-switcher-engine + T1 evidence |
| 2 | `8a19120` | autowarm-testbench | testbench | feat(switcher): read_accounts_list read-only API + IG/TT/YT hardening |
| 3 | `114486c` | autowarm-testbench | testbench | refactor(revision): use switcher.read_accounts_list as UI engine |
| 4 | `c2f02d8` | autowarm-testbench | testbench | fix(switcher-ro): не делать pm clear на target package |
| 5 | TBA | contenthunter | main | docs(plans+evidence): T2-T8 + T9 pending live |

`/root/autowarm/` (prod) НЕ затронут — отдельной задачей после T9 на phone #171.

---

## Memory updates

- Создан `feedback_revision_hardening_rules.md` — правило: чинить UI-баги в switcher, не в revision.
- Обновлён `project_publish_guard_schema.md` — секция «Revision UI-engine = read_accounts_list».
- `MEMORY.md` — добавлена строка index'а нового файла.

