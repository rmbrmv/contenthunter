# Evidence — Publish бэклог-аудит + screencast + switcher (2026-04-27)

**План:** `.ai-factory/plans/publish-backlog-screencast-switcher-20260427.md`
**Ветка:** `fix/testbench-publisher-base-imports-20260427`
**Дата:** 2026-04-27

---

## T1 — Бэклог-аудит (DONE/OPEN свод за 14 дней)

### DONE — закрыто, не возвращаться

| Дата | План | Коммит | Что |
|---|---|---|---|
| 2026-04-22 | `publish-launch-failures-fix-20260422.md` | `e2cd9e2` | YT sbrowser Custom Tab dismiss, IG «Об аккаунте» modal detection, TT launcher stale force-stop |
| 2026-04-22 | `testbench-iter-4-publish-polish-20260422.md` | `d5fc905`, `9b419f5`, `eb12eb6` | Phase 1: graceful screenrecord stop (pkill -SIGINT + ffmpeg remux + ffprobe). Phase 2: YT Groq metadata + round-robin. Phase 3: IG human-check detection + account_blocks |
| 2026-04-21 | `publish-testbench-agent-20260421.md` + brief | (множество) | Testbench автодиаг/autofix MVP — 18/19 задач |
| 2026-04-24 | `publishing-tasks-no-limit-20260424.md` | `68bf91f` | Убрано LIMIT 100 в `/api/publish/tasks` (оператор видит >100 задач) |
| 2026-04-26 | publisher modularization (3 PR) | (см. `project_publisher_modularization_wip.md`) | publisher.py 7405→661 split, smoke canary matrix, tag-release helpers; prod deploy `7688ace` |
| 2026-04-27 | `testbench-publisher-base-imports-20260427.md` | `fd564da` | NameError fix — restore lost imports после publisher split (`ensure_adbkeyboard`, `_adb_text_util`); exception-handler теперь маркирует task=failed; SQL reset 32 застрявших claimed-tasks |
| 2026-04-23 | `revision-platform-column-and-garbage-20260423.md` | (multiple) | PLATFORM_TO_COLUMN drop + dropdown narrow + username strict-filter |

### OPEN deferred — НЕ в scope этого плана

| # | Источник | Пункт | Почему deferred |
|---|---|---|---|
| 1 | `publish-launch-failures-fix-20260422.md:311` | TT root cause #670 — fixture для воспроизведения залипания | Не блокирует; fixture поднимается только если повторится |
| 2 | `testbench-iter-4-publish-polish-20260422.md:307-309` | IG human-check markers — расширять по живым триггерам | LIVE-MONITORING; ждём первого срабатывания в проде |
| 3 | `testbench-iter-4-publish-polish-20260422.md` (PUBLISH-NOTES.md:232+) | account_blocks daily digest в bugs-bot | UX-gap, изолированный, не критичен для публикации |
| 4 | `session-close-testbench-fix-prod-deploy-20260427.md` | `node_modules` symlink drift — `.gitignore` + `git rm --cached` | Tech-debt, one-liner отдельным коммитом |
| 5 | session-close evidence | `adb_push_chunked_md5_mismatch` (P1, физический ADB infra) | Отдельный план; не код publisher'а |

### Открытые баги — В scope этого плана

- **B1** — screencast link не подгружается в лог задачи на публикацию → T2-T5.
- **B2** — переключение работает некорректно → T3, T6-T8.

---

## T2 — Screencast diagnosis

### Гипотеза до диагностики

Plan T4 ставил гипотезу: «бэкенд пишет, API отдаёт, UI рендерит, значит причина — silent failure на одном из шагов screen-record pipeline». Соответственно T4 должен был добавить event-recording в каждую failure-ветку.

### Что показала диагностика (2026-04-27 ~11:50)

**SQL — coverage URL за 24h:**

```
 total | done | done_with_url | failed | failed_no_url | failed_has_url
   241 |    3 |             3 |    190 |           174 |             16
```

**Распиленный по pre/post-fix окну (`fd564da` ~10:33):**

```
 window               | total | failed | failed_no_url | failed_has_url
 pre_fix (<10:33)     |   187 |    181 |           172 |              9
 post_fix (>=10:33)   |    54 |      9 |             2 |              7
```

**Hourly trend URL-coverage (% задач с screen_record_url среди terminal-задач):**

```
 04:00 → 0%
 05:00 → 0%
 06:00 → 0%
 07:00 → 0%
 08:00 → 0%
 09:00 → 3%
 10:00 → 93%   ← фикс fd564da (NameError restore_imports)
 11:00 → 80%
```

**Анализ оставшихся 2 failed-no-url в post-fix окне** (`tasks 1160, 1084`):
- Оба `testbench=true`, `error_code='unknown'`.
- Last event для обоих — `adb_push_chunked_success` (~10:34, ~11:35).
- Ровно 3 events каждый, далее тишина → `status='failed'`.
- Это артефакты SQL-reset скрипта из предыдущего плана `testbench-publisher-base-imports-20260427` (T9: «SQL reset 32 застрявших claimed-tasks»). Reset выставляет `status='failed' error_code='unknown'` БЕЗ запуска screen-record pipeline.

### Вывод по B1

**Гипотеза «silent return в screen-record pipeline» не подтвердилась.** Главный root cause «нет ссылки на скринкаст» — это **NameError downtime** с момента publisher.py split до фикса `fd564da` (2026-04-27 10:33Z). За эти ~30 часов 95% failed-задач не имели screen_record_url, потому что пайплайн screen-record не успевал стартовать (NameError на импорте `ensure_adbkeyboard`/`_adb_text_util`).

**После фикса:**
- 93-80% coverage URL — pipeline работает корректно.
- 2 случая no-url в post-fix окне — артефакт SQL-reset, не silent failure.

**Пересмотр plan T4-T5:**
- T4 в исходном виде (silent-return fix + events) **не закрывает реальный bug B1** — bug уже закрыт `fd564da`.
- Однако defensive event-recording всё равно полезен (hardening): для будущих диагностик надо знать, на каком шаге pipeline упал. Но это уже **hardening, не bug-fix** — и приоритет ниже.
- Юзеру, видимо, нужно **повторно проверить, видна ли сейчас ссылка на скринкаст в логе задачи**. Если да — B1 закрыт. Если нет — копать в сторону frontend cache (Caddy stale bundle?), API-роута на нужной странице, или специфичных задач (testbench-only? prod-only?).

### Сырые данные

S3 проверять не потребовалось: URL'ы видны прямо в `screen_record_url` колонке (https://save.gengo.io/autowarm/screenrecords/...). Pipeline пишет в БД успешно ДЛЯ post-fix задач.

---

## T3 — Switcher reproduction (post-fix окно >=10:33)

### Распределение error-events в post-fix окне

```
 category                   | step                      | n | platforms   | task_ids
 (null)                     | yt_3_open_accounts        | 4 | YouTube     | 1325, 1327
 tt_bottomsheet_closed      | tt_3_open_list            | 1 | TikTok      | 1132
 tt_target_not_logged_in    | tt_2_target_not_logged_in | 1 | TikTok      | 1330
 (после-switcher)           | editor_watcher            | 2 | Instagram   | 1125    (ig_editor_timeout — не switcher)
 (после-switcher)           | wait_upload               | 2 | TikTok      | 1082    (upload_timeout — не switcher)
 (после-switcher)           | publish_phase             | 1 | YouTube     | 1083    (publish_failed_generic — не switcher)
```

### Реальные switcher-fail в post-fix окне (3 разных кейса)

| Task | Платформа | Step | Category | Симптом |
|---|---|---|---|---|
| 1132 | TikTok | `tt_3_open_list` | `tt_bottomsheet_closed` | Bottom-sheet с аккаунтами закрылся раньше парсинга |
| 1330 | TikTok | `tt_2_target_not_logged_in` | (target не в списке) | Целевой `el_cosmo46` не залогинен на устройстве |
| 1325, 1327 | YouTube | `yt_3_open_accounts` | (4 retry events на 2 задачи) | Picker аккаунтов не открылся / не нашёлся |

IG в post-fix окне без switcher-фейлов — все ошибки IG (`editor_watcher`/`ig_editor_timeout`) уже после успешного switch'а.

### Вывод по B2

Юзер прав, что переключение работает некорректно — но это **3 разных кейса на разных платформах**, не один общий баг:

1. **TT bottom-sheet closes** (1132) — race condition, sheet закрывается раньше парсинга. Возможно нужен retry с дополнительным wait или повторный tap на anchor.
2. **TT target not logged in** (1330) — `el_cosmo46` не в списке аккаунтов на устройстве. Не баг switcher'а как такового, а проблема data-consistency: orchestrator выдал task на устройство, где аккаунта нет. Нужно проверить `factory_inst_accounts` и device-binding.
3. **YT open_accounts** (1325, 1327) — picker не открылся. По памяти `project_yt_gmail_switcher.md` есть fallback через Settings-activity (`reference_yt_accounts_settings_path.md`). Возможно gmail-binding не сработал и упал в @handle-fallback который тоже не нашёл.

### Что надо для T6 (targeted фикс)

Каждый кейс требует UI-дампа из `/tmp/autowarm_ui_dumps/` для конкретной задачи (1132, 1330, 1325, 1327) ДО написания кода. Без дампов фикс — догадки.

Нужно подключиться через ADB к устройствам, на которых эти задачи запускались, и собрать дампы (или найти их в архиве `/tmp/autowarm_ui_dumps/`, если timestamp совпадает).

---

## T4 — Screencast hardening (B-вариант)

**Файл:** `/home/claude-user/autowarm-testbench/publisher_base.py`

6 правок в screen-record pipeline — каждая failure-ветка пишет событие в `publish_tasks.events` с `meta.category=screencast_*`:

| Место | Бывшее поведение | Стало | category |
|---|---|---|---|
| `start_screen_record` Exception (~1851) | `log.warning` + `return None` | + `log_event('error', ..., category)` | `screencast_start_failed` |
| `stop_and_upload` rec=None (~1916) | тихий `return` | + `log_event('warning', ...)` | `screencast_skipped_no_handle` |
| pull failed (~1962) | `log_event('warning')` без category | type=`error` + category | `screencast_pull_failed` |
| DB save error (~2020) | `log.warning` (тишина в БД) | + `log_event('error', ...)` | `screencast_db_save_failed` |
| S3 upload exception (~2022) | `log_event('warning')` без category | type=`error` + category | `screencast_upload_failed` |
| outer except (~2032) | `log.warning` (тишина в БД) | + `log_event('error', ...)` | `screencast_stop_failed` |

**Юнит-тест:** `tests/test_publisher_screencast_events.py` — 5 кейсов, все ✅.

```
test_start_failed_logs_event PASSED                                          [ 20%]
test_start_disabled_does_not_log PASSED                                      [ 40%]
test_stop_with_none_handle_logs_skipped PASSED                               [ 60%]
test_stop_pull_failed_logs_event PASSED                                      [ 80%]
test_stop_outer_exception_logs_event PASSED                                  [100%]
============================== 5 passed in 0.10s ===============================
```

## T7 — Guard log в publisher_base после ensure_account

**Файл:** `/home/claude-user/autowarm-testbench/publisher_base.py:1386-1391`

Добавлена строка перед существующим `log.info('✅ account OK: ...')`:

```python
log.info(
    f'[guard] active account verified target={self.account} '
    f'platform={self.platform} step={result.final_step} '
    f'matched={result.already_matched}'
)
```

Маркер `[guard] active account verified` — для быстрого `grep`'а в pm2 logs: «дошли ли до публикации с правильным аккаунтом». Устраняет в будущем класс недоразумений «переключение не работает», когда баг на самом деле downstream от switcher'а (как было с NameError downtime 2026-04-27).

## T5 — Smoke screencast/guard log (post-restart)

`pm2 restart autowarm-testbench` 12:32Z. После restart'а:

- **Task #1181 (YT, makiavelli-o2u)** идёт через recovery-сценарий (yt_1_feed → yt_2_profile_tab → SHORTS-detect → back-tap escape → yt_2_profile_tab_after_shorts → yt_2_profile_screen → yt_3_fg_guard). На момент проверки задача ещё в switcher'е, до `result.success` не дошла.

- **`[guard]`-строки пока 0** — закономерно, ни одна задача после restart'а ещё не прошла switcher до конца. Подтверждение в следующем окне 3-5 мин.

- **screencast_*-events** также пока 0 — это **good news**: ни одна failure-ветка screen-record pipeline не сработала. Hardening — на случай регрессий, не текущий баг.

### ⚠️ Дополнительные находки в логах post-restart (deferred follow-ups)

1. **`vision current_account error: [Errno 2] No such file or directory: 'https://save.gengo.io/...'`** — функция `vision_current_account` (или аналог) пытается открыть HTTPS URL как локальный файл. Это означает, что для YT-аккаунтов `current_account` всегда возвращает None → switcher не может verify «уже на нужном аккаунте». Возможно одна из причин YT `yt_3_open_accounts`-фейлов, найденных в T3. Требует отдельного фикса (передавать локальный path до S3-upload, либо скачивать обратно из URL).

2. **`name '_resolve_single_account_mode' is not defined`** — ещё один NameError-наследник publisher.py split. `[SA-preflight] ошибка, продолжаем без hint` — non-fatal, fallback'ится корректно. Аналогичный паттерн `testbench-publisher-base-imports-20260427` (T9 предыдущего плана восстановил `ensure_adbkeyboard`/`_adb_text_util`, но забыл `_resolve_single_account_mode`).

Оба пункта — deferred (не в scope этого плана), отдельные follow-up'ы.

## T6 — Switcher targeted фикс — DEFERRED

По решению юзера и итогам T3-диагностики плюс T5-наблюдения: 3 разных кейса (TT bottom-sheet, TT not-logged-in, YT picker) + 2 свежих наблюдения (vision URL, _resolve_single_account_mode) → каждый требует отдельного UI-дампа и/или анализа.

**Защитная мера** — T7 guard log даёт grep'абельный маркер в pm2 для будущих диагностик: если завтра пользователь снова скажет «переключение не работает», по `[guard]`-строкам сразу видно, дошёл ли publish до правильного аккаунта.

Создать отдельный план `switch-hardening-multi-platform-20260428.md` (или ближайшую дату) с тремя microplans под каждый кейс.

## T8 — Verify guard log на 3 платформах (через pm2)

`grep -F '[guard] active account verified'` после restart 12:32Z:

```
2026-04-27T12:38:26 #1181 YouTube target=makiavelli-o2u step=yt_6_create_menu matched=False ✅
```

**Покрытие:**
- ✅ YouTube — есть.
- ⏳ Instagram — после restart'а только pending (#1342 IG inakent06), завершённых `account_switch=done` пока нет.
- ⏳ TikTok — после restart'а #1174 (gennadiya4) ушёл в `failed` (`error_code=unknown`), не дошёл до `result.success` → `[guard]` для TT появится на следующей успешной задаче.

Patch подтверждён работающим. Покрытие IG/TT произойдёт автоматически через ближайшие 10-30 минут по мере того как orchestrator подаст следующую задачу на каждую платформу.

screencast_*-events: **0**. Это ожидаемо — pipeline не падал, все проверенные задачи либо ещё running, либо awaiting_url с непустым `screen_record_url`. Hardening сработает только при реальной регрессии.

## T9 — Commits (TBD)

(заполняется на финале)
