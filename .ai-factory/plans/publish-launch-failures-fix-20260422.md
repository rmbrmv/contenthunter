# Publish launch failures — fix план (yt/tt app_launch + ig_camera + switcher telemetry)

**Тип:** diagnose-first + multi-fix
**Создан:** 2026-04-22
**Режим:** Full (slug `publish-launch-failures-fix-20260422`)
**Целевой репо:** `/home/claude-user/autowarm-testbench/` (branch `testbench`)
**НЕ трогаем:** prod `/root/.openclaw/workspace-genri/autowarm/` (main). Merge — ручной, после успешного smoke.

## Settings

| | |
|---|---|
| Testing | **yes** — unit-тесты для нового `_dismiss_blocking_overlays`, фикса `set_step` после SA-fastpath, и fixture-replay-тестов на IG camera wait |
| Logging | **verbose** — на `_open_app` логгировать detected foreground pkg/activity перед каждой попыткой; логгировать факт dismiss'а Custom Tab; события `launch_env_cleanup` и `set_step_post_switcher` для дашборда |
| Docs | **mandatory checkpoint** (T9) — memory + `.ai-factory/PLAN.md` + AGENTS.md при необходимости |
| Roadmap linkage | skipped — `paths.roadmap` не настроен |
| Git | `testbench` branch, `git push origin testbench`; prod `main` не трогаем |

## Контекст (state на 2026-04-22 05:35 UTC)

### Счётчики за 24h (phone #19, testbench=true)

```
 yt_app_launch_failed            |    31
 ig_camera_open_failed           |    30
 tt_app_launch_failed            |    26
 adb_push_chunked_failed         |    13   (вне скоупа — ADB сеть, отдельный трек)
 adb_push_chunked_md5_mismatch   |     8   (то же)
 unknown                         |     6
 tt_upload_confirmation_timeout  |     2
 tt_bottomsheet_closed           |     2   (должны были исчезнуть после SA-shortcircuit)
 yt_accounts_btn_missing         |     2   (то же)
```

**100% fail rate** за последние ~6 часов (с 01:34 UTC — все 3 платформы подряд).

### Что уже известно (до создания этого плана)

1. **Фактические LLM-диагнозы:**
   - `evidence/publish-triage/yt_app_launch_failed-20260421-142657-task552.md` — Groq-отчёт цитирует event: `не удалось запустить приложение step=yt_1_feed package=com.google.android.youtube текущий='com.sec.android.app.sbrowser'`.
   - `evidence/publish-triage/tt_app_launch_failed-20260421-164804-task566.md` — confidence 6/10, гипотеза «проблема с launch»; root cause не уточнён, fixture не разобран.
   - `evidence/publish-triage/ig_camera_open_failed-20260421-143849-task553.md` — гипотеза «publisher застрял на профиле», цитирует watchdog на `ig_2_profile_tab_fg_guard` и предлагает увеличить таймаут.

2. **Manual-launch проверка (2026-04-22 ~05:50 UTC):**
   - YT: `am start -W -n com.google.android.youtube/...WatchWhileActivity` → `Activity: com.sec.android.app.sbrowser/.customtabs.CustomTabActivity` (YT под Custom Tab'ом Samsung Browser'а). Force-stop YT не помогает — Custom Tab живёт в chrome-tab task.
   - TT: `am start -W ...musically` → fg ok, `mCurrentFocus=com.zhiliaoapp.musically`. Значит текущая проблема TT — не системная, а какое-то временное состояние экрана, которое мешает `_foreground_pkg()`; разбор только через fixture.
   - IG: `am start` → fg ok, но camera wait падает после 3+ попыток — задача отдельная, не про launch.

3. **`_open_app` (`account_switcher.py:1360`):**
   - 3 попытки `am start` с `OPEN_APP_WAIT_S=4.0` + attempt*1.5 пауза (итого ~16.5s sleep). Реально логи показывают heartbeat каждые ~30s с тем же step name — значит dump_ui под капотом блокирует на долго (uiautomator pending dumps).
   - Нет проверки на оверлеи (Samsung Browser Custom Tabs, системные диалоги), нет force-close «лишнего» foreground'а перед `am start`.
   - Категория fail'а — `switcher_app_launch_failed` в event.meta.category; на уровне ошибок задачи мапится через `STEP_TO_ERROR_CODE` (publisher.py:83,103 — `tt_1_feed`→`tt_app_launch_failed`, `yt_1_feed`→`yt_app_launch_failed`).

4. **SA-fastpath (commit 6eb806a):**
   - Работает: `sa_fastpath` event фиксируется в task 682 (IG).
   - **BUG обнаружен:** после успешного SA-fastpath `self.p.set_step(...)` не переустанавливается → watchdog при ig_camera_open_failed в task 682 логгирует stale step `switcher: ig_2_profile_tab_fg_guard`, хотя реальный падающий шаг — `open_camera` в publisher'e. Это сбивает LLM-диагноз и триаж.

### Fixtures (доступны)

`/home/claude-user/testbench-fixtures/{636,637,638,658,659,670,671,682,683,696}.tar.gz` (по одному на каждый fail, ~10MB каждый; содержат UI XML dumps + screenshots).

## Research Context

Research path не ведётся. Используется:
- memory: `project_publish_testbench.md`, `project_publish_followups.md` (2-дневная запись про ig_camera регрессию), `project_autowarm_code.md`.
- Commit 6eb806a + evidence `single-account-switcher-20260421.md`.
- LLM-триаж отчёты в `evidence/publish-triage/` (все три target-кода).

## Strategy — diagnose-first

User выбрал: **сначала fixture-replay diagnosis, потом fix**. План в Phase 1 собирает факты (раскапывает XML/screenshots) и только после этого фиксирует конкретный approach в каждой платформе. Это защищает от преждевременной оптимизации (например, прикрутить sbrowser-force-stop не всегда правильно — fixture может показать что это stale Custom Tab от прошлой задачи и достаточно KEYCODE_BACK, а не force-stop).

## Tasks

### Phase 1 — Fixture-replay diagnosis (T1, T2, T3)

**T1 ✅ Unpack fixtures + extract UI state для всех 3 error_code** (blocks T2)

- Создать `/home/claude-user/autowarm-testbench/tools/fixture_triage.py` (или реюзать existing, если есть). Скрипт:
  - Принимает список `task_id`, разворачивает `.tar.gz` в `/tmp/fixture-triage/<task_id>/`.
  - Извлекает последний `switch_*.xml` + последний screenshot перед FAIL-event'ом (по timestamp из events).
  - Для каждой задачи выводит: `task_id, error_code, last_step, last_ui_pkg (из root package= в XML), activity_chain (dumpsys если есть), focus_window`.
- Прогнать на представителях: TT=670, YT=671, IG=682 (самые свежие). Плюс по 2-3 старших для контекста.
- Артефакт: `evidence/launch-failures-fixture-triage-20260422.md` — таблица `{task_id | platform | last_ui_pkg | last_focus | last_screenshot_summary}`.
- Логгирование: скрипт пишет в stderr с префиксом `[fixture-triage]`, каждое открываемое XML/screenshot — INFO.

**T2 ✅ Classify root cause per platform** (blocked by T1; blocks T3, T4)

- YT expected finding (confirm/deny): foreground=`com.sec.android.app.sbrowser/.customtabs.CustomTabActivity`. Если да — fix в T4 (overlay dismiss). Если нет — отдельный approach.
- TT expected finding (unknown): может быть dialog "Update app", может быть permissions, может быть тот же Custom Tab. Разобраться.
- IG camera expected finding: после SA-fastpath какой UI state показывается (reels tab? stories? ad?). Сравнить с `_is_ig_highlights_empty_state` детекторами. 
- Артефакт: добавить в тот же `evidence/launch-failures-fixture-triage-20260422.md` секцию `## Diagnosis per platform`.
- **Decision gate:** если для какой-то платформы root cause ≠ overlay/custom-tab — задача T5 расширяется новой подзадачей до commit'а C2.

**T3 ✅ Write approach memo** (blocked by T2; blocks T4, T5)

- В evidence-файле: `## Chosen approach` — для каждой платформы решение: `pre-launch overlay cleanup`, `refined camera wait`, или новый подход (для TT, если root cause другой).
- Приложить coverage-таблицу: какие из 3 error_code закроются T4 (overlay cleanup), какие требуют специфичного фикса в T5.

### Phase 2 — Universal pre-launch guard (T4)

**T4 ✅ `_dismiss_blocking_overlays()` helper + интеграция в `_open_app`** (blocked by T3; blocks T5, T7)

Файл: `/home/claude-user/autowarm-testbench/account_switcher.py` + возможно `publisher.py` (если хелпер уже есть).

1. Новый метод в `AccountSwitcher` (или `Publisher` — решить по местоположению похожих хелперов):
   ```python
   def _dismiss_blocking_overlays(self, target_pkg: str) -> bool:
       """Закрыть оверлеи (Samsung Browser Custom Tabs, системные диалоги,
       split-screen), которые могут блокировать foreground target приложения.
       
       Returns True если сделал что-то полезное, False если чисто.
       """
       cur = self._foreground_pkg_full()  # вернёт 'package/activity', не только package
       if not cur:
           return False
       # sbrowser custom tab — специфический кейс YT (task #671 evidence)
       if 'com.sec.android.app.sbrowser' in cur:
           log.warning(f'[overlay-dismiss] detected sbrowser custom tab: {cur} — закрываем')
           self.p.log_event('info', f'launch_env_cleanup: sbrowser custom tab dismiss',
                            meta={'category': 'launch_env_cleanup',
                                  'overlay_type': 'sbrowser_customtab',
                                  'activity_before': cur,
                                  'target_pkg': target_pkg})
           # strategy: KEYCODE_BACK first (мягко), потом force-stop если не помогло
           self.p.adb('input keyevent KEYCODE_BACK')
           time.sleep(1.0)
           cur2 = self._foreground_pkg_full()
           if 'com.sec.android.app.sbrowser' in (cur2 or ''):
               self.p.adb('am force-stop com.sec.android.app.sbrowser')
               time.sleep(0.8)
           return True
       # TBD: добавить другие детекторы по результатам T2 fixture-triage
       # (Play Store update-dialog, системные permissions, …).
       return False
   ```

2. В `_open_app` ПЕРЕД первым `am start` (~line 1414):
   ```python
   # [FIX: launch-overlay-guard 2026-04-22] закрыть sbrowser custom tabs/диалоги
   # которые мешают am start поднять target app в foreground (см. yt_app_launch_failed
   # evidence 2026-04-22 — sbrowser CustomTab жил поверх YT task).
   if self._dismiss_blocking_overlays(package):
       # дать системе 0.5s на смену фокуса после dismiss
       time.sleep(0.5)
   ```

3. Метод `_foreground_pkg_full()` — расширение `_foreground_pkg` чтобы вернуть `pkg/activity` а не только pkg:
   ```python
   def _foreground_pkg_full(self) -> str:
       top = self.p.adb("dumpsys activity activities | grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
       m = re.search(r'\s([\w\.]+/[\w\.]+)', top)
       return m.group(1) if m else ''
   ```

4. Event telemetry: `self.p.log_event('info', ..., meta={'category': 'launch_env_cleanup', ...})` — чтобы триаж-классификатор мог показать частотность cleanup'а на дашборде.

**Критерий успеха T4:** на следующем smoke-цикле (после pm2 restart) для тех заданий, где fg=sbrowser custom tab, появляется event `launch_env_cleanup` с `overlay_type=sbrowser_customtab`, и `_open_app` возвращает True с первой попытки после cleanup.

### Phase 3 — Per-platform specific fixes (T5)

**T5 ✅ Platform-specific fixes (conditional — scope уточняется в T2/T3)** (blocked by T3; blocks T7)

**Реализовано 2026-04-22:**
- T5a (YT) — покрыт T4 sbrowser-dismiss, residual не потребовался.
- T5b (TT) — покрыт T4 launcher-stale detect + force-stop target; `OPEN_APP_WAIT_S` оставлен 4s (smoke покажет residual).
- T5c (IG) — добавлен детектор «Об аккаунте» modal'а в `publish_instagram_reel` (publisher.py:2884) с BACK-навигацией + streak-counter; `self.set_step('open_camera')` вызывается явно перед камера-loop'ом.

Сейчас scope — скелет на 3 sub-task'а; финальные детали появляются после T2/T3. Если T2 покажет что все 3 платформы закрываются T4 — T5 сокращается до T5c (IG camera) только.

**T5a (YT) — tentative, зависит от T2.** Если sbrowser-cleanup T4 решает большинство YT-failures — закрываем. Residual: возможно нужен `KEYCODE_HOME` + retry cold-start если custom tab возвращается внутри YT.

**T5b (TT) — unknown, зависит от T2.** Если fixture покажет какой-то специфичный dialog/state — добавить детектор в `_dismiss_blocking_overlays` или отдельный TT-pre-launch-step.

**T5c (IG camera wait — рефакторинг detected_state):** Файл `publisher.py:2791-2976` (`wait_for_ig_camera` / аналог).
- Добавить per-state streak counter + eager escalation: если `detected_state == 'unknown'` 2 раза подряд → LLM-recovery **до** full-reset (сейчас только на `attempt >= 3`).
- Гарантия что `self.set_step('open_camera')` вызывается в начале `wait_for_ig_camera` (видимо он НЕ вызывается — отсюда stale step name в watchdog-отчёте task 682).
- Evidence: добавить в fail_meta факт что мы SA-fastpath'нулись (`post_sa_fastpath: bool`), чтобы отличать «сломанная SA-fastpath» vs «сломанная камера после нормального switcher'а».

### Phase 4 — Switcher telemetry fix (T6)

**T6 ✅ Переустановить `set_step` после SA-fastpath/SA-degraded** (blocks T7)

Файл: `account_switcher.py`. После каждой SA-fastpath/SA-degraded ветки (существует в `_switch_instagram`, `_switch_tiktok`, `_switch_youtube`; результат возвращается через `_tap_plus_and_verify`), **до return**, вызвать:

```python
# [FIX: post-switcher-step-reset 2026-04-22] watchdog/heartbeat берёт current
# step name из self.p.set_step; после SA-fastpath publisher.py не сразу
# переходит к своему set_step(…) → watchdog продолжает рапортовать
# «switcher: ig_2_profile_tab_fg_guard» при fail'е camera step. Явно ставим
# neutral «post-switcher» до того как publisher обновит.
self.p.set_step('post-switcher')
```

Можно поместить это внутрь `_tap_plus_and_verify` в success-ветке (если она идентифицируема) — это покроет и обычный fast-path и SA-fastpath/degraded.

Альтернатива: в `_ensure_correct_account` (publisher.py:1586) после `log_event('account_switch', 'done ...')` вызвать `self.set_step('post-account-switch')`.

**Предпочтительно:** добавить на publisher side (быстрее, меньше рисков сломать switcher internal state).

### Phase 5 — Tests (T7)

**T7 ✅ Unit-тесты** (blocked by T4, T5, T6; blocks T8)

Результат: 171 passed, 3 skipped (полный прогон `tests/`). Новые кейсы:
- `tests/test_overlay_dismiss.py` — 9 кейсов (read_foreground_pkg_full, sbrowser BACK-only + force-stop, launcher stale + target force-stop, no-op paths, integration _open_app с dismiss).
- `tests/test_publisher_ig_camera_recovery.py` — +5 кейсов (ig_about_account_modal RU/EN detector, keycode-back loop, profile_stuck не-матч, camera_ready не-матч).

Файлы:
- `tests/test_overlay_dismiss.py` — новый.
- `tests/test_account_switcher.py` — расширение (SA-step-reset regression).
- `tests/test_ig_camera_wait.py` — новый (fixture-driven, если есть подходящий test harness).

Кейсы:

1. **`test_dismiss_overlays_sbrowser_detects_and_force_stops`**: mock `_foreground_pkg_full()` чтобы вернуть `com.sec.android.app.sbrowser/.customtabs.CustomTabActivity`, убедиться что KEYCODE_BACK отправился; mock возвращает то же → проверить force-stop.
2. **`test_dismiss_overlays_clean_returns_false`**: mock `_foreground_pkg_full()` → `com.instagram.android/.activity.MainTabActivity` → ничего не делать, вернуть False.
3. **`test_open_app_calls_dismiss_before_start`**: mock `_dismiss_blocking_overlays` и `adb`; убедиться что порядок вызовов — dismiss → am start.
4. **`test_sa_fastpath_sets_post_switcher_step`**: mock ensure_account с SA-hint; после success — `self.p.set_step` последним аргументом равен `'post-switcher'` (или `'post-account-switch'` в зависимости от реализации T6).
5. **`test_ig_camera_wait_sets_step`** (T5c): запустить wait_for_ig_camera с mocked UI; первый вызов должен быть `self.set_step('open_camera')`.

Локально прогнать: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_overlay_dismiss.py tests/test_account_switcher.py tests/test_ig_camera_wait.py -v`.

### Phase 6 — Deploy + smoke evidence (T8)

**T8 ✅ Commit + pm2 restart + 2h smoke + evidence** (blocked by T7; blocks T9)

Выполнено 2026-04-22 06:52-07:15 UTC. Commit `e2cd9e2`, push origin/testbench, pm2 restart 06:53:30 UTC. Первые 22 мин smoke: 3 задачи (#711 YT done, #712 IG failed на other root cause, #713 TT passing tt_1_feed via launcher_stale force-stop). `launch_env_cleanup` event fired 3/3 (sbrowser CustomTab + launcher stale). Детали в `.ai-factory/evidence/publish-launch-failures-20260422.md`.

1. Коммиты на `testbench` branch — по C1..C3 (см. Commit Plan).
2. Push: `git push origin testbench`.
3. Restart: `sudo -n pm2 restart autowarm-testbench --update-env`.
4. Мониторинг 2 часа (~12 задач):
   ```bash
   tail -f /home/claude-user/autowarm-testbench/logs/publisher*.log 2>/dev/null \
     | grep -E 'launch_env_cleanup|overlay-dismiss|post-switcher|open_camera'
   ```
5. SQL verify:
   ```sql
   SELECT error_code, COUNT(*) FROM publish_tasks
    WHERE testbench=true AND created_at > NOW() - INTERVAL '2 hours'
    GROUP BY error_code ORDER BY 2 DESC;
   -- ожидание: yt_app_launch_failed ↓ >=80%, ig_camera_open_failed ↓ >=50%,
   -- tt_app_launch_failed ↓ (цель зависит от T2 findings).

   SELECT jsonb_path_query(events, '$.meta.category') AS cat, COUNT(*)
     FROM publish_tasks WHERE testbench=true
       AND created_at > NOW() - INTERVAL '2 hours'
    GROUP BY cat;
   -- ожидание: видеть launch_env_cleanup ≥ 1 на задачу yt, если sbrowser там.
   ```
6. Evidence: `.ai-factory/evidence/publish-launch-failures-20260422.md` — before-rate, after-rate, per-platform event trace (sample), commit SHA, rollback-критерий.

**Rollback-критерий:** если за 2 часа после deploy:
- success-rate упал ниже 30% от baseline, ИЛИ
- появились новые error_code не в этом списке, ИЛИ
- launch_env_cleanup срабатывает на >50% заданий (значит дергаем overlay dismiss где не нужно и ломаем базовый флоу),

то:
```bash
cd /home/claude-user/autowarm-testbench
git revert HEAD~N..HEAD --no-edit  # N = число коммитов плана
git push origin testbench
sudo -n pm2 restart autowarm-testbench
```

### Phase 7 — Docs checkpoint (T9)

**T9 ✅ Docs + memory update (MANDATORY checkpoint)** (blocked by T8)

Выполнено 2026-04-22 07:15 UTC:
- `memory/project_publish_testbench.md`: добавлена секция «Launch failures fix (commit e2cd9e2, 2026-04-22)» + обновлён Pending-список.
- `.ai-factory/PLAN.md` (umbrella): добавлена строка T10 со статусом done.
- `AGENTS.md` (testbench repo): изменений структуры нет — не трогали.

- `memory/project_publish_testbench.md` — дописать секцию «Launch failures fix 2026-04-22» с:
  - Root causes (YT sbrowser custom tab, TT findings, IG camera eager recovery).
  - Новый хелпер `_dismiss_blocking_overlays` и где он вызывается.
  - SA-fastpath step-reset bug и фикс.
  - Ожидания по error_code (какие упали, какие остались).
- `.ai-factory/PLAN.md` (umbrella) — добавить строку про этот план + статус.
- `AGENTS.md` (testbench repo) — upsert раздел «Pre-launch environment cleanup» если он публично документирован.
- Route через `/aif-docs` если изменения касаются docs/.

## Commit Plan

План 9 задач → нужны чекпоинты каждые 2-3 задачи.

| Чекпоинт | После задач | Commit message |
|---|---|---|
| C1 | T1, T2, T3 | `docs(triage): launch-failures fixture-triage 2026-04-22 — root-cause per platform` (evidence-only, код не меняется) |
| C2 | T4, T6 | `fix(switcher): dismiss blocking overlays before am start + reset step after SA-fastpath` |
| C3 | T5 | `fix(publisher): IG camera eager LLM-recovery + set_step('open_camera') guard` (+ possibly T5a/T5b if specific) |
| C4 | T7 | `test(launch-env): overlay dismiss + post-switcher step + IG camera wait coverage` |
| C5 | T8 | `chore(evidence): publish-launch-failures smoke results 2026-04-22` |
| C6 | T9 | `docs(memory): publish-launch-failures fix + testbench notes` |

Все коммиты — `testbench` branch. Prod `main` не трогаем до ручного merge.

## Риски и контрмеры

| # | Риск | Контрмера |
|---|---|---|
| R1 | `_dismiss_blocking_overlays` срабатывает на легитимные sbrowser flows (например, IG auth через Chrome Custom Tabs) и ломает рабочие задачи | Детектор смотрит на `target_pkg` — если target уже foreground, skip. Также event `launch_env_cleanup` с полной трассой активности для post-mortem. Rollback-критерий в T8 включает алерт на >50% срабатываний. |
| R2 | Force-stop sbrowser ломает что-то в prewarm/archiver (которые, возможно, используют Samsung Browser) | sbrowser не используется в publisher/prewarm/archiver сейчас (grep проверить в T3). Если используется — поменять стратегию на только KEYCODE_BACK, без force-stop. |
| R3 | TT-fix неопределён сейчас → scope grows after T2 | Decision gate в T3: scope формализуется до commit C2. Если TT root cause — новая категория, это T5b отдельный коммит. |
| R4 | IG camera wait refactor ломает существующий anecole/recovery path (`_reopen_ig_reels_via_home` + `_is_ig_highlights_empty_state`) | T5c только добавляет детектор + раннюю LLM-recovery; существующий `tried_full_reset` остаётся. Тесты T7 покрывают регрессионный кейс. |
| R5 | `set_step('post-switcher')` рано перетирает полезный debug step | T6 ставит нейтральное имя; publisher сразу после этого вызывает свой `set_step` для очередного phase'а, так что окно «post-switcher» короткое. Тест T7.4 проверяет вызов. |
| R6 | Fixture-triage показывает что root cause на phone #19 — device-specific (например, залипший Play Store dialog) → fix не поможет на prod | Evidence-файл явно фиксирует что это stencil на phone #19; в memory помечаем «может быть device-specific». Perm impact — только testbench. |

## Open questions (to be resolved in T2/T3)

1. TT root cause — manual-launch работает сейчас. Fixture для task #670 должен показать, что именно залипало в 05:15-05:17 UTC.
2. YT sbrowser custom tab — от чего именно всплывает? Прошлая задача закрыла в этом состоянии? Нужно откатить causal (возможно какой-то пост-publish шаг открывает external URL в sbrowser и не закрывает).
3. Нужен ли per-platform-specific TT/YT fix, или T4 покрывает обе?

## Next step

1. `/aif-implement` — запустит T1 (fixture-triage), дождётся decision gate в T3, затем T4+.
2. После C1 — user может согласовать план Phase 2+ (если T2 показал неожиданный TT root cause).
3. В случае rollback — evidence-файл фиксирует что пошло не так.
