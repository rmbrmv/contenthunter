# Single-account switcher short-circuit — autowarm-testbench

**Тип:** fix + enhancement (account_switcher + publisher)
**Создан:** 2026-04-21
**Режим:** Full (slug `single-account-switcher-shortcircuit-20260421`)
**Целевой репо:** `/home/claude-user/autowarm-testbench/` (branch `testbench`) — **НЕ prod** `/root/.openclaw/workspace-genri/autowarm/`
**Контекст:** phone #19 (`RF8YA0W57EP`) заведён с одним паком `manual-seed-20260417` (IG=`inakent06`, TT=`user70415121188138`, YT=`Инакент-т2щ`). Переключаться некуда, но switcher каждый раз идёт в полный flow и падает на шаге open-list / own-profile-detection.

## Settings

| | |
|---|---|
| Testing | **yes** — расширить `tests/test_account_switcher.py` + новый `tests/test_single_account_preflight.py` (см. T5) |
| Logging | **verbose** — `log.info` на preflight-решение, `log.warning` на SA-fastpath/SA-degraded-fallback; `log_event('account_switch', meta={'category': 'sa_fastpath', 'single_account': True})` для дашборда |
| Docs | warn-only — изменения локальны к switcher-модулю, публичный API стабилен; отдельный docs-checkpoint не нужен |
| Roadmap linkage | skipped — `paths.roadmap` отсутствует |
| Git | `testbench` branch, `git push origin testbench`, prod `main` не трогаем |

## Проблема и root cause (evidence)

### Симптомы (последние 24 ч на phone #19)

```
error_code                     |  count
-------------------------------+-------
adb_push_chunked_failed        |  13   ← отдельная ADB-проблема (вне скоупа)
adb_push_chunked_md5_mismatch  |   8   ← то же самое
unknown                        |   5
yt_app_launch_failed           |   2
tt_bottomsheet_closed          |   2   ★ скоуп
yt_accounts_btn_missing        |   2   ★ скоуп
ig_camera_open_failed          |   1
tt_profile_tab_broken          |   1   ★ скоуп
```

### Пример #554 (TikTok, target=`user70415121188138`)

```
14:45:44 switcher: tt_1_feed
14:46:14 switcher: tt_2_profile_tab_fg_guard  (retap 1)
14:46:44 switcher: tt_2_profile_tab_fg_guard  (retap 2 — _tt_is_own_profile=False)
14:47:14 switcher: tt_2_profile_tab_fg_guard  (retap 3 — cold-start relaunch)
14:47:21 FAIL: bottomsheet со списком аккаунтов не открылся — вероятно, 
         в TikTok залогинен только один аккаунт (target 'user70415121188138' не добавлен)
         step=tt_3_open_list
```

Оно правильно диагностировало ситуацию в fail-сообщении («залогинен только один аккаунт»), но не смогло этого **избежать**: switcher всё равно прошёл через cold-start + retap-loop + попытку открыть list.

### Пример #540 (YouTube, target=`Инакент-т2щ`)

Cyrillic + дефис в username. `_USERNAME_RE = r'^@?([a-zA-Z0-9._]{2,30})$'` (`account_switcher.py:222`) — ASCII-only. `_looks_like_username('Инакент-т2щ')` возвращает False → `get_current_account_from_profile` → None → vision-fallback (не всегда надёжен) → в общем случае `current=None` → падаем в switch-branch → ищем «Аккаунты»-кнопку → её нет, потому что один аккаунт → `yt_accounts_btn_missing`.

### Root causes

1. **Отсутствует DB-информированный pre-flight.** `publisher.py:1549-1568` вызывает `self.switcher.ensure_account(platform, account)` без передачи информации о том, сколько и каких аккаунтов реально посажено на устройство. Эта информация есть в `account_packages` и в `SELECT DISTINCT account FROM publish_tasks WHERE device_serial=... AND status='done'`.

2. **Cyrillic / дефис username не парсятся.** `account_switcher.py:222`.

3. **Fast-path зависит от успешного чтения `current`.** `account_switcher.py:457, 685, 860` — `if current and current == target` — если `current=None`, падаем в switch-branch вместо того чтобы в SA-режиме предположить match.

4. **Нет degraded fallback для single-account девайсов.** `account_switcher.py:721-728, 898-902` — `return self._fail(...)` даже когда мы в принципе не могли переключиться (список не существует).

### Что лишнего делается

- Cold-start приложения (force-stop + am start) на каждой публикации, хотя app уже был foreground на нужном аккаунте с прошлой публикации (10 мин назад).
- `_tt_is_own_profile` retap×3 + cold-start как страховка против uiautomator-race → 3 дампа + relaunch даже когда один аккаунт залогинен и это и так наш.
- Полный путь tap-header → bottomsheet/Аккаунты → pick-target в single-account раскладке — заведомо провальный.

## Стратегия (strategy A: DB pre-flight + degrade gracefully)

**Принцип:** switcher узнаёт от publisher'а перед вызовом, что на этом `device+platform` известен ровно один аккаунт и он же target. В этом режиме:

- fast-path работает даже при провале чтения `current` (предполагаем match).
- `tt_bottomsheet_closed` и `yt_accounts_btn_missing` не фейлят задачу — делают degraded fallback через `_tap_plus_and_verify` на текущем экране.
- Финальный `_check_account_device_mapping` guard (`publisher.py:5307`) и post-publish verification остаются как safety net — если SA-hint врёт и на устройстве реально другой аккаунт, задача всё равно будет отловлена на уровне post-url / success-page username check.

**Почему безопасно:**

- SA-hint вычисляется из `account_packages` + `publish_tasks.done` history; для phone #19 это всё курируемые данные, которые сам publisher и поддерживает (`_upsert_auto_mapping` на `publisher.py:5422`).
- Для мульти-account устройств SA-hint=False → алгоритм работает ровно как сейчас, без изменений.
- Cyrillic fix — только расширяет набор матчущихся имён, существующие тесты (`tests/test_account_switcher.py`) не должны сломаться.

## Research Context

Research path не ведётся (`paths.research` не настроен). Используется:

- git log autowarm-testbench: commits `fef2b4c..5b9830d` — последние fix'ы switcher / ADB / screen-recovery.
- memory: `project_publish_testbench.md`, `project_autowarm_code.md`, `project_adb_push_network_issue.md`.
- Evidence file: `.ai-factory/evidence/publish-testbench-20260421.md`.

## Tasks

### Phase 1 — Parallel-safe правки (T1, T2)

**T1 ✅ DB pre-flight: определить `single_account_mode` для device+platform** (blocks T3, T5)

Файл: `/home/claude-user/autowarm-testbench/publisher.py`.

- Добавить хелпер `_resolve_single_account_mode(serial: str, platform: str, target: str) -> tuple[bool, list[str]]` рядом с `_check_account_device_mapping` (~:6435). Query:
  ```sql
  WITH declarative AS (
      SELECT instagram AS acc FROM account_packages
       WHERE device_serial=%(serial)s
         AND (end_date IS NULL OR end_date >= CURRENT_DATE)
         AND %(platform)s='Instagram' AND instagram IS NOT NULL AND instagram<>''
      UNION ALL
      SELECT tiktok FROM account_packages WHERE ... %(platform)s='TikTok' ...
      UNION ALL
      SELECT youtube FROM account_packages WHERE ... %(platform)s='YouTube' ...
  ),
  history AS (
      SELECT DISTINCT account FROM publish_tasks
       WHERE device_serial=%(serial)s AND platform=%(platform)s AND status='done'
  )
  SELECT DISTINCT acc FROM (SELECT * FROM declarative UNION SELECT * FROM history) u
  WHERE acc IS NOT NULL AND acc<>'';
  ```
- Нормализовать все результаты через `AccountSwitcher._normalize_username` (trim, lstrip @, lower).
- Вернуть `(True, [target_norm])` iff `len(distinct_normalized)==1` AND `distinct_normalized[0] == target_norm`. Иначе `(False, distinct_list)`.
- В `_ensure_correct_account` (publisher.py:1539-1568) перед `self.switcher.ensure_account(...)`: вызвать `sa_mode, known = _resolve_single_account_mode(self.device_serial, self.platform, self.account)`, затем `self.switcher.set_single_account_hint(self.platform, self.account, sa_mode)`.
- Логгирование: `log.info(f'[switcher-preflight] serial={...} platform={...} target={...} single_account={sa_mode} known={known}')`.
- Event: `self.log_event('account_switch', f'preflight single_account={sa_mode} known={",".join(known)}', meta={'category': 'sa_preflight', 'single_account': sa_mode})`.

**T2 ✅ Cyrillic + дефис в `_looks_like_username`** (blocks T3, T5)

Файл: `/home/claude-user/autowarm-testbench/account_switcher.py`.

- `:222` — regex: `_USERNAME_RE = re.compile(r'^@?([\w.\-]{2,40})$', re.UNICODE)`.
  - `\w` в UNICODE-flag покрывает `[a-zA-Z0-9_]` + Cyrillic + прочие алфавиты.
  - Добавлен `\-` и верхняя граница поднята до 40 (YT-каналы бывают длиннее).
- `:254` — `has_digit_or_sep = any(c.isdigit() or c in '._-' for c in s)`.
- `_USERNAME_STOPWORDS` — добавить `'главная', 'подписки', 'лента', 'магазин', 'shop', 'for you'`. Также добавить `'аккаунты', 'accounts', 'менеджер', 'inbox'` если их нет.
- `_normalize_username` (:1474) не трогать — дефис и так сохраняется через `.lower()`.

### Phase 2 — Switcher изменения (T3, T4)

**T3 ✅ Single-account fast-path в switcher (IG/TT/YT)** (blocked by T1, T2; blocks T4, T5)

Файл: `account_switcher.py`.

1. `AccountSwitcher.__init__` (:380-400): добавить
   ```python
   self._single_account_mode = False
   self._single_account_target = ''
   self._single_account_platform = ''
   ```

2. Новый метод:
   ```python
   def set_single_account_hint(self, platform: str, target: str, enabled: bool) -> None:
       """Установить hint «на этом устройстве для этой платформы известен
       единственный аккаунт, и это target». При enabled=True switcher срежет
       list-open и tap-target-in-list шаги."""
       self._single_account_mode = bool(enabled)
       self._single_account_target = self._normalize_username(target) if enabled else ''
       self._single_account_platform = platform if enabled else ''
       log.info(f'[switcher] SA-hint set: platform={platform} target={target} enabled={enabled}')
   ```

3. `ensure_account` (:403) — в начале сбрасывать hint если platform не совпадает:
   ```python
   if self._single_account_platform and self._single_account_platform != platform:
       log.debug(f'[switcher] SA-hint platform mismatch ({self._single_account_platform} != {platform}), clearing')
       self._single_account_mode = False
   ```

4. `_switch_instagram` (:439-485) — вставить ПОСЛЕ `_go_to_profile_tab` и ДО tap_profile_header (:463-475):
   ```python
   if self._single_account_mode:
       log.info(f'[switcher] IG SA-fastpath: assuming current={target}, skipping list-open')
       self.p.log_event('account_switch', 
                        f'sa_fastpath platform=Instagram target={target}',
                        meta={'category': 'sa_fastpath', 'single_account': True})
       return self._tap_plus_and_verify(
           cfg, step_prefix='ig_sa', final_step='ig_sa_fastpath',
           verify_triggers=cfg['type_sheet_triggers'],
           already_matched=True,
       )
   ```
   (Существующий `if current and current == target:` fast-path остаётся выше — он срабатывает когда uiautomator всё же прочитал имя; SA-fastpath это страховка для случаев пустого/невалидного дампа.)

5. `_switch_tiktok` (:595-750) — ПОСЛЕ retap-loop (:668) и _read_screen_hybrid (:676-683):
   ```python
   if self._single_account_mode and (not current or current != target):
       log.info(f'[switcher] TT SA-fastpath (current={current!r}, target={target!r})')
       self.p.log_event('account_switch',
                        f'sa_fastpath platform=TikTok target={target}',
                        meta={'category': 'sa_fastpath', 'single_account': True})
       return self._tap_plus_and_verify(
           cfg, step_prefix='tt_sa', final_step='tt_sa_fastpath',
           verify_triggers=cfg['editor_triggers'],
           already_matched=True,
       )
   ```

6. `_switch_youtube` (:795-920) — ПОСЛЕ probe-attempts (:832-857):
   ```python
   if self._single_account_mode and (not current or current != target):
       log.info(f'[switcher] YT SA-fastpath (current={current!r}, target={target!r})')
       self.p.log_event('account_switch',
                        f'sa_fastpath platform=YouTube target={target}',
                        meta={'category': 'sa_fastpath', 'single_account': True})
       return self._tap_plus_and_verify(
           cfg, step_prefix='yt_sa', final_step='yt_sa_fastpath',
           verify_triggers=cfg['editor_triggers'],
           already_matched=True,
       )
   ```

**T4 ✅ Degraded fallback для bottomsheet_closed / accounts_btn_missing при SA-mode** (blocked by T3; blocks T5)

Файл: `account_switcher.py`.

- Если `_tt_is_own_profile` retap-loop в `_switch_tiktok` провалился (сейчас `return self._fail(...)` на :669-674) — при `self._single_account_mode`: не fail, а SA-fastpath (даже если мы не на своём профиле, попробуем tap-и-verify на текущем экране).
- Если `bottomsheet не открылся` (`_switch_tiktok` :721-728) — при SA-mode вместо fail: log warning, try `_tap_plus_and_verify` на текущем экране (мы остались на profile screen).
- Если `yt_accounts_btn_missing` (`_switch_youtube` :898-902) — при SA-mode аналогично.

Паттерн:
```python
if self._single_account_mode:
    log.warning(f'[switcher] SA-mode degraded fallback at {step}: expected on single-account device')
    self.p.log_event('account_switch',
                     f'sa_degraded_fallback step={step} platform={platform}',
                     meta={'category': 'sa_degraded_fallback', 'single_account': True,
                           'original_step': step})
    return self._tap_plus_and_verify(
        cfg, step_prefix=f'{prefix}_sa_deg', final_step=f'{prefix}_sa_degraded',
        verify_triggers=cfg['editor_triggers'],  # или 'type_sheet_triggers' для IG
        already_matched=True,
    )
return self._fail(...)  # fallback to original behaviour when SA-mode=False
```

Safety net: если `_tap_plus_and_verify` сам упадёт на verify-шаге (triggers не найдены → значит мы действительно не на profile/editor) — SwitchResult вернёт success=False → задача упадёт с понятным step='{platform}_sa_degraded' и `_check_account_device_mapping` как последний guard.

### Phase 3 — Тесты (T5)

**T5 ✅ Unit-тесты: preflight + Cyrillic regex + SA fast-path** (blocked by T1, T2, T3, T4; blocks T7)

Файлы:
- `tests/test_account_switcher.py` — расширить
- `tests/test_single_account_preflight.py` — новый

Кейсы:

1. **Cyrillic username regex** (расширение `test_looks_like_username` или новый):
   - `_looks_like_username('Инакент-т2щ')` → True
   - `_looks_like_username('user70415121188138')` → True (18 chars, в [2,40])
   - `_looks_like_username('inakent06')` → True
   - `_looks_like_username('Профиль')` → False (stopword)
   - `_looks_like_username('Аккаунты')` → False (stopword)
   - `_looks_like_username('Главная')` → False (stopword)
   - `_looks_like_username('abc')` → False (длина < 5, нет digit/sep)

2. **`get_current_account_from_profile` с Cyrillic**:
   - Construct elements-list с `UIElement(text='Инакент-т2щ', bounds=(100, 50, 400, 120))` в header-zone → возврат `'инакент-т2щ'` (normalized).

3. **`_resolve_single_account_mode`** (новый модуль):
   - (a) 1 pack с target='inakent06' (IG) → (True, ['inakent06']).
   - (b) 1 pack + history с другим аккаунтом → (False, [...]).
   - (c) 1 pack но target не совпадает → (False, [...]).
   - (d) 0 packs + 0 history → (False, []).
   - (e) Cyrillic target: pack.youtube='Инакент-т2щ', target='Инакент-т2щ' → (True, ['инакент-т2щ']).

4. **`test_switcher_sa_mode_ig_fastpath`**:
   - Mock publisher: `set_single_account_hint('Instagram', 'inakent06', True)`.
   - Mock `_open_app` → True; `_go_to_profile_tab` → True; `_tap_plus_and_verify` → `_ok('ig_sa_fastpath', already_matched=True)`.
   - Assert: `ensure_account('Instagram', 'inakent06').success == True` AND `already_matched == True` AND `final_step == 'ig_sa_fastpath'` AND `_find_and_tap_account` НЕ вызывался.

5. **`test_switcher_sa_mode_tt_degraded_fallback`**:
   - Mock `_tt_is_own_profile` → False (3 раза), `_find_anchor_bounds` → None (bottomsheet не открылся).
   - С SA-mode=True → `result.success == True`, `final_step == 'tt_sa_degraded'`.
   - С SA-mode=False → `result.success == False`, `final_step == 'tt_3_open_list'` (текущее поведение — regression guard).

6. **`test_switcher_sa_mode_disabled_keeps_current_behavior`** (regression):
   - Запустить существующие test_account_switcher тесты без SA-hint — все должны зеленить без изменений.

Команда локального прогона: `cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_account_switcher.py tests/test_single_account_preflight.py -v`.

### Phase 4 — Классификатор + Deploy (T6, T7)

**T6 ✅ Триажный классификатор: распознавать `sa_fastpath` / `sa_degraded_fallback`** (может идти параллельно с T5)

- `sa_fastpath` / `sa_degraded_fallback` приходят в events как успешные — `result.success=True` → задача НЕ failed → `triage_classifier.process_failed_task` не вызывается. Никаких SQL-изменений не нужно.
- Проверить `analytics_collector_v2.py` / dashboard `testbench.html`: добавить фильтр/бейдж для events с `meta.category='sa_fastpath'` чтобы отличать от обычных `account_switch ok`.
- Комментарии в `triage_classifier.py` возле правил для `tt_bottomsheet_closed` / `yt_accounts_btn_missing`: «При SA-mode часть случаев отфильтровывается upstream в switcher'е; если код всё-таки залетает — это реальный logout/switcher-break, приоритет выше».

**T7 ✅ Evidence + smoke на phone #19** (blocked by T5, T6; blocks T8)

1. Коммит + push (ТОЛЬКО `testbench` branch):
   ```bash
   cd /home/claude-user/autowarm-testbench
   git status   # проверить что мы на testbench
   git add publisher.py account_switcher.py tests/test_account_switcher.py tests/test_single_account_preflight.py
   git commit -m "feat(switcher): single-account pre-flight short-circuit + Cyrillic username regex"
   git push origin testbench
   ```
2. Restart testbench:
   ```bash
   sudo -n pm2 restart autowarm-testbench --update-env
   sudo -n pm2 logs autowarm-testbench --lines 50 --nostream | grep -E 'SA-|preflight'
   ```
3. Мониторинг 1-2 часа (5-10 задач):
   ```bash
   tail -f /home/claude-user/autowarm-testbench/logs/publisher*.log 2>/dev/null \
     | grep -E 'SA-mode|sa_fastpath|sa_degraded|preflight'
   ```
4. SQL verify:
   ```sql
   SELECT error_code, COUNT(*)
     FROM publish_tasks
    WHERE testbench=true
      AND created_at > NOW() - INTERVAL '2 hours'
    GROUP BY error_code ORDER BY 2 DESC;
   -- Ожидаем: 0 tt_bottomsheet_closed / yt_accounts_btn_missing / tt_profile_tab_broken

   SELECT jsonb_path_query(events, '$.meta.category') AS cat, COUNT(*)
     FROM publish_tasks
    WHERE testbench=true
      AND created_at > NOW() - INTERVAL '2 hours'
    GROUP BY cat;
   -- Ожидаем видеть sa_fastpath / sa_preflight в counters
   ```
5. Evidence файл: `.ai-factory/evidence/single-account-switcher-20260421.md`
   - Before-rate per error_code (копия из текущего запроса).
   - After-rate per error_code.
   - Копипаст event-trace для одной IG / одной TT / одной YT задачи с SA-fastpath.
   - Таймстамп restart + commit SHA.

**Rollback-критерий:** если за 2 часа после deploy success-rate упал ниже 50% от базового ИЛИ появились новые error_code (не из списка):
```bash
cd /home/claude-user/autowarm-testbench
git revert HEAD --no-edit
git push origin testbench
sudo -n pm2 restart autowarm-testbench
```

### Phase 5 — Housekeeping (T8)

**T8 ✅ Обновить memory + PLAN.md** (blocked by T7)

- `memory/project_publish_testbench.md`: добавить запись «Single-account short-circuit внедрён 2026-04-21: switcher читает account_packages на pre-flight, при `single_account_mode=True` пропускает list-open-branch (IG/TT/YT) и делает tap+verify сразу. Cyrillic username regex расширен до `\w.\-` + UNICODE. Phone #19 стабильно публикуется без switch-failures».
- `.ai-factory/PLAN.md` (umbrella): дополнить строкой T8 про этот план (статус на момент закрытия).
- Memory НЕ для project_autowarm_code.md — там prod код, наши правки в testbench-клоне.

## Commit Plan

План содержит 8 задач → нужны чекпоинты.

| Чекпоинт | После задач | Commit message |
|---|---|---|
| C1 | T1, T2 | `fix(switcher): Cyrillic username regex + DB pre-flight hook for single-account devices` |
| C2 | T3, T4 | `feat(switcher): single-account fast-path + degraded fallback (IG/TT/YT)` |
| C3 | T5, T6 | `test(switcher): SA-mode unit coverage + classifier annotations` |
| C4 | T7 | `chore(evidence): SA-switcher smoke results on phone #19 (2026-04-21)` |
| C5 | T8 | `docs(memory): SA-switcher short-circuit notes` |

Все коммиты — на ветке `testbench` в `/home/claude-user/autowarm-testbench/`. Prod `main` НЕ трогаем до явного ручного merge.

## Риски и контрмеры

| # | Риск | Контрмера |
|---|---|---|
| R1 | SA-hint врёт (например, `account_packages` устарел, пользователь пере-логинился на другой аккаунт вручную) | Post-publish verification + `_check_account_device_mapping` guard остаются как safety net. SwitchResult с SA-fastpath фиксируется в events, post-mortem по post_url выявит mismatch. |
| R2 | `_tap_plus_and_verify` на SA-fastpath падает на verify (мы не на profile/editor) | SwitchResult.success=False → задача падает с понятным step (`{platform}_sa_fastpath`); триаж увидит новую ошибку → возврат к manual. |
| R3 | Regex расширение ломает существующие тесты username-detection | T5 case 6 (regression guard) поймает; если сломано — правим стоп-лист перед деплоем. |
| R4 | SA-mode включается для мульти-account девайсов из-за бага в preflight-query | Query имеет `DISTINCT` + UNION history; защита: hint enabled только когда `len(distinct) == 1`. Unit-тест кейс (b) проверяет. |
| R5 | Cyrillic в SQL-параметрах (`target='Инакент-т2щ'`) ломает psycopg2 | psycopg2 UTF-8 из коробки; DB уже содержит такие значения (pack manual-seed-20260417 работает). |
| R6 | `_upsert_auto_mapping` (publisher.py:5422) пишет в `project='auto-from-publish'` другие аккаунты → SA-hint выключится | Это ожидаемое поведение: если история показывает >1 аккаунтов для этого устройства, SA-hint False → возврат к текущему flow. |

## Next step

1. `/aif-implement` для реализации T1-T8 последовательно (blockedBy-цепочка уже проставлена: T1,T2 → T3 → T4 → T5,T6 → T7 → T8).
2. После C4 (T7) — пользователь подтверждает по evidence, что `error_code`-сломы пропали; если ok → C5 (T8) и закрытие плана.
3. В случае rollback — evidence-файл обязательно фиксирует что пошло не так (для будущего повторного подхода).
