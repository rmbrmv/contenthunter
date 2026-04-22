# Revision → использует AccountSwitcher как UI-движок (вариант B / B2.5)

**Тип:** refactor + bug fix (UI scraping stability для phone #171)
**Создан:** 2026-04-22 UTC
**Режим:** Full (slug `refactor-revision-use-switcher-engine-20260422`)
**Целевые репо:**
- `/home/claude-user/autowarm-testbench/` (ветка `testbench`) — код switcher/revision + тесты
- `/home/claude-user/contenthunter/` (ветка `main`) — план + evidence
**НЕ трогаем:** `/root/autowarm/` (prod deploy — отдельной задачей после смок-теста на #171).

## Проблема (коротко)

На phone #171 (`RF8Y90GCWWL`) модалка `Ревизия аккаунтов` не обнаруживает реально залогиненных `born.trip90` / `ivana.world.class` в IG/TT/YT:

- **IG** «не запустился (foreground=instagram)» — из-за sanity-check'а на пустой (3KB) dump
- **TT** «wrong_foreground=instagram» — IG липнет после `force_stop`, Android возвращает его при запуске TT
- **YT** скрапер возвращает мусор (`ibydiva`, `@cxpnax`, `@russan`) — fallback regex `_extract_username_from_ui` читает первый «нетривиальный» текст из дампа, попадая в рекомендации меню
- **В factory на #171 уже лежат фейковые аккаунты** из старого прогона: `factory_inst_accounts.id=1630` (YT:`ivana`, pack 308/171a), `id=1631` (YT:`google`, pack 309/171b). Это последствие того же YT-мусор-бага.

`account_switcher.py` решает те же задачи надёжно (22/22 тестов, использует cold-start retry, `is_dump_usable`, smart-tap-profile, escape-shorts, retap_probe). В revision эти hardening-шаги отсутствуют, и бойлерплейт «launch → profile → dropdown → read» дублируется с дрифтом.

## Scope & non-scope

**В scope:**
1. В `account_switcher.py` добавить публичный read-only API `read_accounts_list(platform) -> dict` — единая точка «открыть приложение, дойти до профиля, открыть список аккаунтов, вернуть usernames, не переключать».
2. В `account_revision.py` переписать `discover_platform_accounts()` через новый API. Удалить дубликат-код запуска/нав/парсинга. Оставить в revision только: Gmail-scan (`dumpsys account`), inventory установленных APK (`pm list packages`), сборка итога для `server.js`.
3. Platform-specific hardening (попутно с рефакторингом, чтобы #171 реально починился):
   - IG: `is_dump_usable` guard + cold-start retry при non-usable dump
   - TT: KEYCODE_HOME + `pm clear` перед запуском, когда предыдущий foreground — IG
   - YT: убрать слепой regex-fallback в `_extract_username_from_ui` для YT (возвращать явную ошибку); явный search кнопки «Аккаунты» через resource-id fallback + retap_probe ×3
4. Чистка `factory_inst_accounts` 1630/1631 (фейковые YT-записи) + сброс pack 308/309 в «пустое» состояние либо удаление, чтобы live test сделал правильные записи.
5. Live-smoke на phone #171 (born.trip90 / ivana.world.class должны попасть в «Новые аккаунты» для IG+TT+YT).
6. Regression-тесты на phone #19 (publisher+switcher ротация продолжает работать, ensure_account не деградировал).

**НЕ в scope:**
- Изменение `AccountSwitcher.__init__` или `ensure_account()` сигнатуры — publisher не трогаем.
- Рефакторинг `publisher.py` / `testbench_orchestrator.py`.
- Prod deploy `/root/autowarm/` — отдельной задачей после смок-теста.
- Валидация username на стороне `server.js /api/devices/:serial/revision/apply` (это был вариант C — делаем позже, если нужно).
- Миграция на OCR/ai_find_tap для YT — оставляем retap_probe ×3.

## Settings

| | |
|---|---|
| Testing | **yes** — unit для нового `read_accounts_list()` с XML fixture'ами (re-use `tests/fixtures/`), unit для hardening-ветки IG/TT/YT, integration `test_revision_tiktok_virtual.py` обновить под новый API, smoke-live на #171 через `python3 account_revision.py --device-serial RF8Y90GCWWL --adb-host 82.115.54.26 --adb-port 15037 --device-num-id 268` |
| Logging | **verbose** — `[switcher-ro] platform=X launch=... dump_usable=... profile=... dropdown=... accounts=[...]`; на каждом retry-шаге — явный `action`; в revision — `[revision] platform=X → found_accounts=N`. Кэп на количество dumps в `/tmp/autowarm_revision_dumps/` не меняем |
| Docs | **mandatory checkpoint (T11)** — evidence + memory update (`project_publish_guard_schema.md`, `reference_autowarm_artifacts.md`), AGENTS.md обновить короткой секцией «Revision использует switcher как UI-движок» |
| Roadmap linkage | skipped — `paths.roadmap` не настроен |
| Git | autowarm-testbench: ветка `testbench`, `git push origin testbench`. contenthunter: `main`, `git push origin main`. Ни в `main` autowarm (отдельный repo в testbench), ни в prod — не пушим |

## Strategy

### B2.5 — Read-Only Micro-API (обоснование)

Три рассмотренных варианта:

| | B1: Extract Base Class | B2: `read_only` flag в `ensure_account` | **B2.5: Новый публичный `read_accounts_list()`** |
|---|---|---|---|
| Изменения в switcher | ~200–250 строк + MRO | ~20–25 строк, примесь логики в `ensure_account` | ~70–80 строк (только новый метод, без правок старого) |
| Риск для publisher | **HIGH** (сигнатура меняется) | MEDIUM (новая ветка в hot-path) | **ZERO** (`ensure_account` не трогается) |
| Revision | полный пере-rewrite наследования | вызов `ensure_account(read_only=True)` | вызов нового API |
| Тесты | много перепись | добавить кейсы на read-only | старые 37+11 as-is + 5 новых |
| Rollback | труден | средний | лёгкий (просто не вызывать новый метод) |

Выбираем B2.5. Revision вызывает `switcher.read_accounts_list(platform)`. Внутри switcher новый метод переиспользует приватные `_open_app`, `_go_to_profile_tab`, `_read_screen_hybrid`, `_open_accounts_dropdown`-эквивалент, `_read_accounts_list`-эквивалент — НО без `_find_and_tap_account` и без `_tap_plus_and_verify`.

### Зависимости switcher от publisher (важно для revision integration)

`AccountSwitcher(publisher)` использует: `p.dump_ui`, `p.adb_tap`, `p.adb`, `p.adb_shell`, `p.set_step`, `p.log_event`, `p.task_id`, `p.tap_element`, `p.find_element_bounds`, `p.ai_find_tap`, `p.ensure_unlocked`.

Revision не имеет Publisher-инстанса (он вызывается как CLI-скрипт). Решение: в revision сделать **лёгкий `_RevisionPublisherShim`** — класс с минимальным набором методов, дегелирующий `adb_*` на существующие методы `AccountRevision`, а `log_event/set_step/task_id` — на stdout в JSON-прогресс (revision уже делает `_progress()`). `ai_find_tap` — no-op (возвращает False), `ensure_unlocked` — no-op (telefon уже разблокирован через revision init).

Шим инкапсулирует разницу между CLI-контекстом revision и publisher-контекстом. Switcher в обоих случаях видит «publisher-интерфейс».

## Research Context

Research path не ведётся. Использую:
- memory: `project_publish_testbench.md` (22/22 тестов switcher), `reference_autowarm_artifacts.md` (`/tmp/autowarm_revision_dumps/`), `project_account_packages_deprecation.md` (DROP уже сделан), `feedback_execution_autonomy.md` (сам действую, не прячусь за AskUserQuestion)
- Артефакты ревизии #171: `/tmp/autowarm_revision_dumps/RF8Y90GCWWL_*` (17 xml-файлов за 10:57–17:04 UTC)
- Скриншот пользователя: `/tmp/phone171_revision.png` (Yandex Disk `qoptW9MMYvMFtw`) — модалка с `born.trip90`, `ivana.world.class` в Gmail, красный блок с IG/TT «не удалось запустить»
- БД: `factory_pack_accounts` (pack 308=171a, 309=171b), `factory_inst_accounts` (id=1630 YT:`ivana`, id=1631 YT:`google` — фейковые)

## Tasks

### Phase 1 — Чистка БД на #171 + зелёный baseline (T1)

**T1. ✅ Очистить фейковые `factory_inst_accounts` 1630/1631, оставить пустые паки 171a/171b** — DELETE 2, паки 308/309 acc_count=0 (см. evidence)

- SQL (идемпотентный, через `DO $$`):
  ```sql
  BEGIN;
  -- 1. Удалить фейковые YT-записи (скрапер в прошлом прогоне выдал мусорные ники)
  DELETE FROM factory_inst_accounts WHERE id IN (1630, 1631);
  -- 2. Оставить факт, что паки 171a/171b существуют — они будут наполнены live-прогоном T9.
  -- Не удаляем паки, чтобы сохранить id и pack_name для evidence и консистентности.
  COMMIT;
  ```
- Проверка: `SELECT fpa.id, fpa.pack_name, COUNT(fia.id) AS acc_count FROM factory_pack_accounts fpa LEFT JOIN factory_inst_accounts fia ON fia.pack_id=fpa.id WHERE fpa.device_num_id=268 GROUP BY fpa.id, fpa.pack_name ORDER BY fpa.id;` → обе строки с `acc_count=0`.
- Evidence: до/после selectы в `evidence/refactor-revision-use-switcher-engine-20260422.md` (создать при T12).

### Phase 2 — Новый API `read_accounts_list()` в switcher (T2, T3)

**T2. Добавить `read_accounts_list(platform) -> dict` в `AccountSwitcher`**  (blocks T3, T4, T5, T6)

- Файл: `/home/claude-user/autowarm-testbench/account_switcher.py`
- Позиция: после `ensure_account()` (~ строка 552+, перед `_switch_instagram`)
- Сигнатура:
  ```python
  def read_accounts_list(self, platform: str) -> dict:
      """Read-only обнаружение залогиненных аккаунтов на текущем устройстве.

      В отличие от ensure_account, НЕ выбирает аккаунт, НЕ тапает '+' и
      не изменяет состояние приложения кроме открытия dropdown'а. Возвращает
      список usernames, которые показаны в account-switcher dropdown'е.

      Args:
          platform: 'instagram' | 'tiktok' | 'youtube'

      Returns:
          {
              'platform': str,
              'status': 'found' | 'not_logged_in' | 'error',
              'current': str | None,     # активный аккаунт в профиле
              'accounts': [str],          # usernames из dropdown
              'reason': str | None,       # если status=error — причина
              'dumps': [str],             # paths к сохранённым xml (diagnostic)
          }
      """
  ```
- Внутренняя реализация — тонкая: вызывать те же `_open_app`, `_go_to_profile_tab`, `_read_screen_hybrid`, `_tap_profile_header`, `parse_account_list` / `find_anchor_bounds` / `ACCOUNT_LIST_ANCHORS`, что использует `_switch_*`, но:
  - **не** вызывать `_find_and_tap_account`
  - **не** вызывать `_tap_plus_and_verify`
  - при `is_dump_usable=False` — retry (cold-start с `pm clear $package && am start ...`, до 3 попыток, суммарный deadline 60s)
  - при IG/TT `wrong_foreground` — `input keyevent KEYCODE_HOME` + `pm clear` prev-foreground + relaunch
  - для YT — если после открытия профиля кнопка «Аккаунты» не найдена: retap_probe ×3 (port of `_yt_empty_profile_dump` recovery из switcher)
- Verbose logging: `publisher.log_event('switcher.read', f'platform={platform} step=launch attempt=...')`, на каждом подшаге.
- Исключения не бросает: все ошибки → `status='error'`, `reason='...'`.
- Побочный эффект: сохраняет диагностические xml в `self._dump_dir` (`/tmp/autowarm_ui_dumps` когда работает через publisher; revision-шим переадресует в `/tmp/autowarm_revision_dumps`).

**T3. Unit-тесты для `read_accounts_list`**  (blocked by T2; blocks T4, T5, T6)

- Файл: `/home/claude-user/autowarm-testbench/tests/test_switcher_read_only.py`
- Использовать существующие XML-fixtures в `tests/fixtures/` + mock Publisher из `tests/test_switcher_youtube.py:33-48` (scaffold скопировать).
- Кейсы (≥8):
  1. `test_ig_happy_path_returns_accounts` — mock publisher отдаёт валидный IG-dump → `{status: 'found', current: 'born.trip90', accounts: ['born.trip90', 'ivana.world.class']}`.
  2. `test_tt_happy_path` — TT own-profile dump → вернул список.
  3. `test_yt_happy_path` — YT profile → вернул accounts.
  4. `test_ig_not_logged_in` — dump содержит маркеры login-экрана (`LOGIN_SCREEN_MARKERS`) → `status='not_logged_in'`, accounts=[].
  5. `test_ig_non_usable_dump_retries_and_fails` — mock отдаёт 3× по 3KB «пустой» dump → `status='error'`, `reason='dump_not_usable_after_3_attempts'`.
  6. `test_tt_wrong_foreground_recovery_succeeds` — 1-я попытка foreground=instagram, 2-я после HOME+pm clear=tiktok → `status='found'`.
  7. `test_yt_accounts_button_not_found_no_fallback` — YT profile без кнопки «Аккаунты» → `status='error'`, `reason='accounts_button_not_found'`. **НЕТ мусорного regex-fallback'а**.
  8. `test_does_not_tap_plus` — после вызова `read_accounts_list` mock publisher НЕ получил `adb_tap` на координаты кнопки «+»/«Добавить аккаунт».
- Запуск: `cd /home/claude-user/autowarm-testbench && python3 -m pytest tests/test_switcher_read_only.py -v`
- Ожидание: 8/8 pass.
- Regression: все старые `pytest tests/test_account_switcher.py tests/test_switcher_youtube.py` остаются зелёными.

### Phase 3 — Platform-specific hardening в switcher (T4, T5, T6)

**T4. IG hardening — `is_dump_usable` + cold-start retry**  (blocked by T3; blocks T9)

- Файл: `account_switcher.py`, метод `_open_app` или новый хелпер `_ensure_usable_profile_dump(package, activity, deadline_s=60)`.
- Логика:
  1. `launch` через `am start`
  2. `dump_ui()` — если размер < 5KB или <50 node'ов, считаем dump non-usable
  3. если non-usable — `force_stop $package && pm clear $package && am start --activity-clear-task ...`
  4. wait `_wait_foreground` + 2s extra
  5. повтор до 3 попыток, total deadline 60s
- Re-use: `is_dump_usable` уже есть в switcher — проверить, что логика совпадает.
- Unit-тесты: 3 кейса (happy, 1 retry, 3 retry fail) в `test_switcher_read_only.py`.
- Правило: **hardening живёт в switcher**, не в revision. Этот же код подхватит publisher при ротации.

**T5. TT hardening — KEYCODE_HOME + `pm clear prev-pkg` при `wrong_foreground`**  (blocked by T3; blocks T9)

- Файл: `account_switcher.py`, добавить в `_open_app` branch:
  ```
  if expected_foreground != actual_foreground and actual_foreground in KNOWN_STICKY_PACKAGES:
      self.p.adb_shell('input keyevent KEYCODE_HOME')
      time.sleep(1.0)
      self.p.adb_shell(f'am force-stop {actual_foreground}')
      self.p.adb_shell(f'pm clear {actual_foreground}')  # агрессивно, но работает
      time.sleep(0.5)
      <retry launch>
  ```
- `KNOWN_STICKY_PACKAGES = {'com.instagram.android', 'com.zhiliaoapp.musically'}` — эмпирически эти два чаще всего «залипают».
- **Риск:** `pm clear` снесёт login-сессию. Это ОК для revision (мы и так собираемся прочитать список — после clear откроется login-screen и revision вернёт `not_logged_in`, не мусор). Для publisher это НЕ вызывается, т.к. `_ensure_right_account` в publisher сначала проверяет `current`, а не делает blind relaunch.
- Compromise: `pm clear` применяется только в `read_accounts_list` контексте. В `_open_app` добавить параметр `aggressive_reset: bool = False`, publisher не использует, revision — да. Альтернатива — только `force-stop` без `pm clear`, если выяснится что clear ломает какие-то сценарии.
- Unit-тест: 1 кейс на wrong_foreground → recovery → success.
- **Контрольный regression:** прогнать `test_publisher_ig_editor.py`, `test_publisher_ig_camera_recovery.py` — убедиться, что пути publisher не зацепили новый aggressive-branch.

**T6. YT hardening — убрать слепой regex-fallback, добавить retap_probe ×3**  (blocked by T3; blocks T9)

- Файл: `account_switcher.py`, методы `_yt_try_accounts_btn_with_retries` / `_yt_empty_profile_dump`, плюс порт этой логики в `read_accounts_list` YT-ветку.
- Удалить из `account_revision.py` вызов `_extract_username_from_ui` как fallback для YT — в revision после рефакторинга (T8) этого кода вообще не будет.
- В switcher `read_accounts_list` для YT:
  1. `_dismiss_overlays` (существующий)
  2. `_yt_escape_shorts` (существующий)
  3. `_go_to_profile_tab`
  4. **NEW:** `_yt_try_accounts_btn_with_retries(max_retries=3)` — ищет кнопку «Аккаунты»/«Accounts»/«Переключить аккаунт» по `content-desc` и по `text`, если не нашёл → повторный `_tap_profile_header` + retap_probe
  5. если после 3× не нашёл кнопку → `status='error', reason='accounts_button_not_found'` (не мусорный regex)
  6. если нашёл — `parse_account_list` через container_y_range = bounds dropdown'а
- Unit-тест: `test_yt_happy_path` + `test_yt_accounts_button_not_found_no_fallback` (уже в T3).

### Phase 4 — Revision refactor (T7, T8)

**T7. Реализовать `_RevisionPublisherShim`**  (blocked by T2)

- Файл: `/home/claude-user/autowarm-testbench/account_revision.py`
- Класс:
  ```python
  class _RevisionPublisherShim:
      """Минимальный Publisher-совместимый интерфейс для AccountSwitcher read_accounts_list.

      Делегирует adb_* на AccountRevision, остальное — логирует в _progress/stderr.
      ai_find_tap — no-op (возвращает False); ensure_unlocked — no-op.
      """
      def __init__(self, revision: 'AccountRevision'):
          self._r = revision
          self._step = None
          self.task_id = f'revision-{revision.serial}-{int(time.time())}'

      def adb(self, *args, **kw): return self._r.adb(*args, **kw)
      def adb_shell(self, cmd, **kw): return self._r.adb_shell(cmd, **kw)
      def adb_tap(self, x, y): return self._r.adb_tap(x, y)
      def dump_ui(self, retries=3): return self._r.adb_dump_ui(retries=retries)
      def set_step(self, step): self._step = step; self._r._progress(step, step, -1)
      def log_event(self, kind, payload): logger.info('[shim] %s | %s', kind, payload)
      def tap_element(self, xml, desc, clickable_only=True): ...  # port из switcher helpers
      def find_element_bounds(self, xml, desc): ...  # port
      def ai_find_tap(self, desc): return False
      def ensure_unlocked(self): return True
  ```
- Unit-тест: 1 smoke-case в `tests/test_revision_real_adb.py` — создать шим, вызвать `shim.dump_ui()` на моке, убедиться, что proxied правильно.

**T8. Переписать `discover_platform_accounts` через switcher.read_accounts_list**  (blocked by T2, T4, T5, T6, T7)

- Файл: `account_revision.py`
- Удалить: `launch_app`, `_tap_profile_tab`, `_open_accounts_dropdown`, `_read_accounts_list`, `_extract_username_from_ui`, `_tt_navigate_to_own_profile`. Всё это теперь живёт в switcher.
- Новая реализация `discover_platform_accounts`:
  ```python
  def discover_platform_accounts(self) -> dict:
      shim = _RevisionPublisherShim(self)
      switcher = AccountSwitcher(shim)
      result = {}
      for platform in ('instagram', 'tiktok', 'youtube'):
          if not self._is_app_installed(PLATFORM_PACKAGES[platform]):
              result[platform] = {'status': 'not_installed', 'accounts': []}
              continue
          ro = switcher.read_accounts_list(platform)
          result[platform] = {
              'status': ro['status'],
              'current': ro.get('current'),
              'accounts': ro.get('accounts', []),
              'reason': ro.get('reason'),
          }
          logger.info('[revision] platform=%s status=%s accounts=%s',
                      platform, ro['status'], ro.get('accounts'))
      return result
  ```
- `main()` / CLI entry-point revision — обновить, чтобы сериализовать `result` в JSON для server.js.
- Integration-тест `tests/test_revision_real_adb.py`, `tests/test_revision_tiktok_virtual.py` — адаптировать под новый API (было `AccountRevision.discover_platform_accounts` возвращала структуру — формат остался совместимым, просто другая имплементация).
- Ожидание: `python3 -m pytest tests/test_revision_*.py` — старые тесты проходят.

### Phase 5 — Live smoke + regression (T9, T10)

**T9. Live smoke на phone #171**  (blocked by T1, T4, T5, T6, T8)

- Предусловия: T1 (БД очищена), свежий код на ветке `testbench` pushed, revision запускается из CLI.
- Команда:
  ```bash
  cd /home/claude-user/autowarm-testbench
  python3 account_revision.py \
      --device-serial RF8Y90GCWWL \
      --adb-host 82.115.54.26 \
      --adb-port 15037 \
      --device-num-id 268 \
      2> /tmp/revision-171-$(date +%s).log
  ```
  (номер device-num-id = `factory_device_numbers.id=268`, проверено в T1-audit.)
- Ожидание:
  - IG: `status=found`, `accounts=['born.trip90', 'ivana.world.class']`
  - TT: `status=found`, `accounts=['born.trip90', 'ivana.world.class']`
  - YT: `status=found`, `accounts=['born.trip90', 'ivana.world.class']`
  - Фейковых `ibydiva/@cxpnax/@russan` в результате **нет**.
- Если TT падает с `wrong_foreground` после hardening — возможно нужно увеличить `pm clear` aggression или добавить доп. `sleep`; итерировать на `tests/test_switcher_read_only.py` сначала, потом повторный live.
- Если YT возвращает `accounts_button_not_found` — значит KZ-локаль YT действительно использует другую метку. Добавить недостающий литерал в `accounts_button_triggers` (switcher), обновить T6 тест, повторить.
- Evidence: `/tmp/revision-171-*.log` + dumps из `/tmp/autowarm_revision_dumps/RF8Y90GCWWL_*` — приложить в `evidence/refactor-revision-use-switcher-engine-20260422.md`.

**T10. Regression на phone #19 (publisher + switcher не деградировали)**  (blocked by T4, T5, T6)

- Запустить `testbench_orchestrator.py --once --dry-run` на свежем коде — убедиться, что IG/TT/YT ротации для phone #19 проходят.
- Проверить `publish_tasks` WHERE device_num_id=163 AND created_at > now() - interval '1 hour' — нет новых записей со `status='failed'` из-за switcher.
- Прогнать unit-тесты:
  ```bash
  pytest tests/test_account_switcher.py tests/test_switcher_youtube.py tests/test_overlay_dismiss.py -v
  ```
  Ожидание: 100% green (48 тестов минимум).
- Если хоть один тест упал — **блокер**; rollback ветки, диагностика через git diff на switcher.

### Phase 6 — Commit + docs + evidence (T11, T12)

**T11. Docs + memory update**  (blocked by T9, T10)

- Evidence файл: `/home/claude-user/contenthunter/.ai-factory/evidence/refactor-revision-use-switcher-engine-20260422.md`
  - Проблема (#171 + мусор в БД)
  - Выбранный вариант (B2.5) + обоснование
  - Diff-сводка: сколько строк добавлено/удалено в switcher/revision
  - Live-прогон #171 (до/после)
  - Regression phone #19 (зелёные тесты + orchestrator dry-run)
- Memory update:
  - `project_publish_guard_schema.md` — добавить параграф «Revision использует switcher.read_accounts_list как UI-движок; hardening IG/TT/YT живёт в switcher, переиспользуется publisher через ensure_account».
  - `reference_autowarm_artifacts.md` — уточнить, что dumps revision теперь могут попадать и в `/tmp/autowarm_ui_dumps` (если publisher-path), и в `/tmp/autowarm_revision_dumps` (если revision-shim).
  - (новый?) `feedback_revision_hardening_rules.md` — правило: при следующем баге UI-скрейпинга чинить в switcher, не в revision. Revision — thin CLI-wrapper.
- AGENTS.md (autowarm-testbench): короткая секция «Revision использует switcher как UI-движок» с 3-4 строками.

**T12. Коммиты + push**  (blocked by T11)

Все autowarm-testbench коммиты — на ветке `testbench`, `git push origin testbench`. Contenthunter — на `main`, `git push origin main`. В main autowarm НЕ мержим (prod deploy отдельно).

## Commit Plan

12 задач → 6 коммит-чекпоинтов:

| Commit | После задач | Репо | Сообщение |
|---|---|---|---|
| 1 | T1 | autowarm-testbench (testbench) | `chore(db): clean fake YT accounts 1630/1631 on phone #171` |
| 2 | T3 | autowarm-testbench | `feat(switcher): read_accounts_list read-only micro-API + unit tests` |
| 3 | T6 | autowarm-testbench | `fix(switcher): IG/TT/YT hardening — usable-dump retry, sticky-fg recovery, no regex-fallback` |
| 4 | T8 | autowarm-testbench | `refactor(revision): use switcher.read_accounts_list as UI engine` |
| 5 | T10 | autowarm-testbench | `test(revision): live smoke phone #171 + regression phone #19` |
| 6 | T12 | contenthunter (main) | `docs(plans): refactor-revision-use-switcher-engine + evidence` |

## Risks & rollback

- **R1 — hardening switcher ломает publisher на phone #19.** Самый критичный риск (publisher deliver'ит публикации 24/7). **Митиг:** T10 regression — все 48 unit-тестов + dry-run orchestrator до merge. `pm clear` в новом branch'е `_open_app` gated флагом `aggressive_reset=False` по умолчанию; publisher не передаёт True, switcher read-only — да. Rollback: `git revert` коммит 3.
- **R2 — KZ-локаль YT не покрыта `accounts_button_triggers`.** Если в YT на #171 кнопка «Аккаунты» локализована в казахский («Есептік жазбалар» или т.п.), T9 упадёт с `accounts_button_not_found`. **Митиг:** расширить trigger-list, добавить тест, повторить T9. Это быстрый фикс, не блокер.
- **R3 — Shim не полностью совместим со switcher.** Какой-то метод (`tap_element`, `find_element_bounds`, `ai_find_tap`) может вызваться неожиданно и упасть. **Митиг:** T7 unit-тест on shim + unit-тесты T3 в read-only покрывают прямые вызовы. Все методы шима возвращают «безопасный noop» вместо `raise`.
- **R4 — `_find_and_tap_account` в switcher вызывается из `_switch_*`, а не из `read_accounts_list`.** При переиспользовании нужно убедиться, что разделили функцию «открыть dropdown + спарсить» от «тапнуть цель». **Митиг:** T2 реализация не вызывает `_find_and_tap_account`, реюзит только `parse_account_list`/`find_anchor_bounds`. Проверяется unit-тестом T3.8 «does_not_tap_plus».
- **R5 — Deploy на prod отложен; phone #171 получит фикс только в testbench.** Пользователь ожидает, что после implement'а #171 реально чинится. **Митиг:** Scope plan'а именно на testbench; prod deploy — отдельной задачей после успешного T9. Зафиксирую это в evidence.
- **R6 — `pm clear com.instagram.android` снесёт login-сессию на тестовом аккаунте.** Для #171 это ОК (мы хотим обнаружить аккаунты, а не публиковать). Для прода — НЕ ОК. **Митиг:** `aggressive_reset` — не по умолчанию, только в revision. Публикатор не может случайно запустить.
- **R7 — uiautomator dump возвращает 3KB вне зависимости от retries.** Если на #171 ROM заблокировал `uiautomator dump` (FLAG_SECURE в IG на новой версии), hardening не поможет. **Митиг:** T9 покажет — если dump остаётся 3KB, фолбэк на accessibility service или screen recording (отдельная задача, не в scope). В evidence заведомо пишем возможный фолбэк.

## Rollback strategy

- Commit 1 (чистка БД) — обратный SQL: `INSERT INTO factory_inst_accounts (id, pack_id, platform, username, active, synced_at) VALUES (1630, 308, 'youtube', 'ivana', true, '2026-04-22 13:49:00'), (1631, 309, 'youtube', 'google', true, '2026-04-22 13:51:22');` (сохранено в evidence).
- Commit 2 (`read_accounts_list`) — добавление, `git revert` безопасен, publisher не затронут.
- Commit 3 (hardening) — если publisher сломался: `git revert`, прогнать тесты, диагностировать за одну итерацию. Пока `aggressive_reset=False` по умолчанию, risk is low.
- Commit 4 (revision refactor) — если revision упал на #171: `git revert` вернёт старый `discover_platform_accounts` с его старыми багами. Revision вернётся в исходное состояние (#171 не работает, но и не ухудшилось).
- Commit 5 (тесты) — дополнение, не влияет на runtime.

## Next step

После подтверждения плана — исполнять через `/aif-implement` (по `feedback_execution_autonomy.md` — пишу код/коммиты сам).

После Phase 5 (зелёный #171 + phone #19 regression) — evidence → memory update → commit 6 в contenthunter. Потом **отдельной задачей** deploy на `/root/autowarm/` — не в этом плане.
