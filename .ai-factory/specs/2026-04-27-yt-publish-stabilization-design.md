# YT publish stabilization — design (2026-04-27)

**Цель:** За сегодня поднять success rate publish-задач на phone #19 testbench до **≥8/10 подряд** для YouTube. Дополнительно — закрыть класс багов «свитчер некорректно работает / непонятная ошибка в UI» по всем 3 платформам (IG/TT/YT).

**Источник проблемы:** см. baseline ниже + bug-report `sources/bugs/inbox/2026-04-27T160030Z-Danil_Pavlov_123-yt-переключение-акка.md` (видео + транскрипт пользователя).

---

## 1. Acceptance criteria

1. На phone #19 (`device_serial=RF8YA0W57EP`) последовательно прогоняем 10 testbench YT publish-задач — **минимум 8 в статусе `done`**.
2. Каждый failed-task в UI `/publishing/publishing` показывает понятный `error_code` (не `unknown` / `publish_failed_generic`), достаточный чтобы оператор сразу понял что делать руками.
3. На picker'е YT detection «другой аккаунт разлогинен» автоматически помечает соответствующую `factory_reg_accounts.yt_block` JSONB записи (без удаления target из ротации).
4. 2 deferred follow-up'а из evidence T5 (`vision_current_account` HTTPS bug, `_resolve_single_account_mode` import noise) закрыты.

## 2. Контекст и baseline

### 2.1. Состояние phone #19 на момент дизайна (post-fix окно ≥ 2026-04-27 10:33Z)

| Метрика | Значение |
|---|---|
| YT terminal-tasks за 24h | 8 (4 done + 4 failed + 1 awaiting_url) |
| `done` rate | 50 % (4/8) |
| Все done | `makiavelli-o2u` (4/4) |
| Все failed | `Инакент-т2щ` (4/4: 3× `publish_failed_generic`, 1× `unknown`) |
| Pending в очереди | 12 (6 makiavelli + 6 Инакент) |

### 2.2. Root-cause для failed-Инакент tasks (1083, 1202, 1244)

UI dump `task1244_switch_1244_yt_3_open_accounts_1777298485.xml` (4356 bytes, usable=False) содержит:

```
text="Не удалось войти в аккаунт"
text="Войдите в аккаунт"  (button)
```

Согласно bug-report пользователя (видео `2026-04-27T155951Z-33ec1aff.mp4`, транскрипт через Groq Whisper):

> «Если один из аккаунтов был забанен и разлогинился, мы попадаем на плашку "Не удалось войти в аккаунт". Скрипт залогиниться не может — нужно: нажать назад → дождаться пока уйдёт плашка → прокрутить вниз список аккаунтов → выбрать нужный.»

Frame 020 видео подтверждает: после dismiss модалки picker открыт с 3 rows:
- `makiavelli` (current, ✓)
- `Инакент` (`inakent06@gmail.com`) — рабочий target
- `vera.smith8872...` — с indicator `«Требуется действие. Нажмите, чтобы войти»`

То есть **target жив, но скрыт за модалкой, которую генерирует разлогиненный *другой* аккаунт `vera.smith`**.

### 2.3. Существующая инфраструктура (используем, не создаём заново)

- `account_switcher._vision_read_current_account` (`account_switcher.py:3077`) — vision-based read of current account. Используется в IG/TT/YT pre-switch verify. Содержит баг `[Errno 2] No such file or directory: 'https://...'` (см. evidence T5).
- `factory_inst_accounts.gmail` колонка (миграция 2026-04-24) + `_yt_gmail_hint`.
- `factory_reg_accounts.yt_block` JSONB (memory `project_account_blocks.md`).
- `_record_event(type, reason, message, meta)` — events JSONB на `publish_tasks`.
- `[guard] active account verified` лог-маркер (commit 9b382d4 от 2026-04-27).
- `ANTHROPIC_API_KEY` env-var уже читается 5-ю модулями autowarm — пользователь предоставил Console key, сохранён в `~/secrets/anthropic.env` (chmod 600).
- AI-tap fallback в YT switcher (видим в события task 1223 makiavelli: `AI tap: (449,227) — account username "makiavelli-o2u" in the currently visible l`) — уже работает.

### 2.4. NOT in scope (явно)

- Re-auth `vera.smith8872...@gmail.com` (физическое действие пользователя).
- Расширение vision-detection на каждый hang-point (отдельная сессия, опция C из brainstorm).
- Prod gmail-coverage backfill для оставшихся 51 аккаунта (отдельный backlog `yt-gmail-backlog-20260424.md`).
- TT/IG specific switcher баги (B1132/B1330) — будут адресованы B3 audit'ом, но конкретные фиксы не в scope этого спека (только error_code rename'ы).

## 3. Архитектура изменений

4 атомарных трека, 5 commit'ов в testbench → 1 cherry-pick в prod → 1 docs commit в contenthunter.

```
B1 — YT modal-dismiss + picker-scroll      [account_switcher.py]
B2 — Detect "Требуется действие" → yt_block [account_switcher.py + factory_reg_accounts]
B3 — Cross-platform error_code namespace   [account_switcher.py + publisher_base.py + server.js + index.html]
B4 — 2 atomic side-fixes                    [account_switcher.py:3079, publisher_base.py:1324]
```

### 3.1. B1 — YT modal-dismiss + picker-scroll

**Файл:** `/home/claude-user/autowarm-testbench/account_switcher.py` (YT switch path).

**Поведение до фикса:**
```
yt_3_pre_tap        → usable=True
yt_3_open_accounts  → usable=False bytes=4356  ← модалка «Не удалось войти»
yt_4_pick_account   → usable=False bytes=4356
fail step=yt_4_pick_account reason=аккаунт ... не привязан к устройству
```

**Поведение после фикса:**
```
yt_3_pre_tap                    → usable=True
yt_3_open_accounts              → usable=False bytes<5000
  ↳ _detect_login_modal() == True
  ↳ event: type=info reason=yt_login_modal_detected
  ↳ pre-back guard: dumpsys window mCurrentFocus ∈ YouTube? иначе — relaunch
  ↳ adb shell input keyevent KEYCODE_BACK
  ↳ poll UI dump (max 5 attempts, 500ms delay) до usable=True И modal absent
  ↳ event: type=info reason=yt_login_modal_dismissed attempts=N
yt_3_open_accounts_after_modal  → usable=True (новый ui_dump step)
  ↳ scroll-loop в picker (swipe y=900→400, max 3 stale rounds)
  ↳ event: type=info reason=yt_picker_scrolled rows_seen=N target_visible=bool
yt_4_pick_account               → tap по target row
ok step=yt_4_pick_account matched=True
```

**Хелпер `_dismiss_login_modal_if_present()`** вынесен в shared scope и вызывается также в pre-scroll и pre-tap гарантах (modal может появиться позже).

**Юнит-тесты** (`tests/test_switcher_youtube.py`, новые):
- `test_yt_modal_login_required_detected` — UI-dump c modal текстом → `_detect_login_modal()` == True.
- `test_yt_modal_dismiss_back_press_called` — modal на attempt 1, picker на attempt 2 → ровно один `KEYCODE_BACK` + `_record_event(reason='yt_login_modal_dismissed')`.
- `test_yt_picker_scroll_finds_target_below_viewport` — picker с 5 rows, target 5-я → scroll-loop срабатывает.

### 3.2. B2 — Detect «Требуется действие» в picker → write `yt_block`

**Файлы:** `account_switcher.py` (`parse_account_list` YT-mode, ~`:459-492`); `factory_reg_accounts.yt_block` JSONB.

**Логика:**

После B1 picker открыт. В `parse_account_list` для каждой row, если рядом (±120px по y) есть text матчащий regex `r'требуется\s+действие|нажмите.*чтобы\s+войти|tap\s+to\s+sign\s+in'` (re.I):
1. Извлечь gmail из той же row (как уже делает gmail-parse).
2. Если gmail найден →
   ```sql
   UPDATE factory_reg_accounts
   SET yt_block = jsonb_set(
     COALESCE(yt_block, '{}'::jsonb),
     '{logout}',
     jsonb_build_object(
       'detected_at', NOW(),
       'reason', 'yt_login_required_in_picker',
       'evidence_task_id', %s
     )
   )
   WHERE gmail = %s
   ```
3. `_record_event(type='warning', reason='yt_account_logout_marked', meta={gmail, target_unaffected: True})`.

**Что НЕ делаем:** `factory_inst_accounts.active=false` для этого аккаунта. `yt_block` достаточно — оператор сам решит когда re-auth'ить (требование «оперативно поправить вручную»).

**Юнит-тест:** `test_yt_picker_marks_logout_account_in_yt_block` — UI dump с 3 rows (1 active, 1 working, 1 «Требуется действие») → side-effect: `set_yt_block(gmail='vera.smith...@gmail.com')` вызван.

**Anti-false-positive guard:** текст `«Требуется действие»` **должен** находиться (a) в bounds picker-row, (b) с clickable=true ancestor, (c) row содержит @handle/gmail.

### 3.3. B3 — Cross-platform error_code namespace + UI status

**Файлы:** `account_switcher.py` (3-5 точечных rename'ов), `publisher_base.py:1380-1390` (mapping в `task.error_code`), `server.js` (payload), `index.html` (rendering).

**Audit (T-section в evidence):** grep по `account_switcher.py` всех мест где `success=False` или `_record_event(type='error', ...)` → таблица `(platform, step, current_reason, proposed_reason)`.

**Канонический namespace:** `<platform>_<phase>_<terminal-state>` (snake_case).

| Текущий error_code | Реальная причина | Канонический |
|---|---|---|
| `publish_failed_generic` (1244, 1202, 1083 Инакент) | YT modal blocked picker | `yt_login_modal_blocked_picker` (post-B1 не должно появляться) |
| `publish_failed_generic` Инакент (после B1, если упадёт) | switcher не нашёл target | `yt_target_not_in_picker_after_scroll` |
| `unknown` (1160 SQL-reset) | админский reset | `admin_reset` |
| `tt_bottomsheet_closed` (1132) | bottom-sheet race | `tt_account_sheet_closed_before_parse` |
| `tt_target_not_logged_in` (1330) | account не на устройстве | `tt_target_not_on_device` |
| `yt_3_open_accounts` 4× retries (1325, 1327) | picker не открылся | `yt_picker_failed_to_open` |
| IG editor_timeout как замена switcher fail | mishandled | разделить: `ig_target_not_in_picker`, `ig_picker_scroll_exhausted` |

**Гарантия в коде:** каждый `_record_event(type='error')` в switch fail-ветке указывает `reason` из канонического namespace; `publisher_base` мапит первый встретившийся switch-error reason → `task.error_code` (если ничего нет — `switch_failed_unspecified`).

**UI display:**
- Task-list строка: рядом с failed-status — `<small class="error-code">{error_code}</small>` (~5 строк CSS+HTML).
- Task-page шапка: блок «Error: `{error_code}` — `{first_error_event.message}`», красный.

`server.js` payload `pt.error_code` уже отдаётся (verified в schema).

**Юнит-тесты:** по одному кейсу на каждый новый canonical reason из таблицы (7 кейсов) в `tests/test_account_switcher.py` — assert `_record_event(reason=<canonical>)` вызван в соответствующей fail-ветке.

**Pre-flight для rename'ов:** `grep -rn "reason ==\|'<old_reason>'" triage_classifier.py agent_diagnose.py` → обновить читателей в **том же** commit'е (memory `feedback_cross_repo_schema_changes.md`).

### 3.4. B4.1 — `_vision_read_current_account` HTTPS-URL bug

**Файл:** `account_switcher.py:3077-3122`.

**Симптом:** `vision current_account error: [Errno 2] No such file or directory: 'https://save.gengo.io/...'`.

**Фикс:** в начале `_vision_read_current_account` после `shot = self._maybe_screenshot(...)`:
```python
if isinstance(shot, str) and shot.startswith(('http://', 'https://')):
    cache_dir = Path('/tmp/autowarm_vision_cache')
    cache_dir.mkdir(exist_ok=True)
    local_path = cache_dir / f'{hashlib.md5(shot.encode()).hexdigest()}.png'
    if not local_path.exists():
        with urllib.request.urlopen(shot, timeout=10) as resp, open(local_path, 'wb') as f:
            shutil.copyfileobj(resp, f)
    shot = str(local_path)
```
(Per-call `timeout=10` вместо `socket.setdefaulttimeout` — последний global, может задеть других читателей сетевых ресурсов в процессе.)

**Юнит-тест:** `test_vision_read_current_account_handles_https_shot` — мокает `_maybe_screenshot` → HTTPS URL, мокать `urllib.request.urlretrieve` → vision-call получает local path.

**Атомарность:** ~25 строк, 1 commit.

### 3.5. B4.2 — `_resolve_single_account_mode` import-path noise

**Файл:** `publisher_base.py:1324` (read), `publisher.py:196` (определение).

**Симптом:** `name '_resolve_single_account_mode' is not defined` → `[SA-preflight] ошибка, продолжаем без hint` (non-fatal).

**Pre-fix диагностика:**
```bash
cd /home/claude-user/autowarm-testbench && python -c "from publisher_base import _resolve_single_account_mode"
```
Если падает → top-level `from publisher import _resolve_single_account_mode` в `publisher_base.py`. Если REPL ОК но pm2 падает → искать circular / sys.path в pm2 env.

**Атомарность:** ~3-5 строк, 1 commit.

## 4. Testing план

| Уровень | Команда / действие | Когда |
|---|---|---|
| Unit | `pytest tests/test_switcher_youtube.py tests/test_account_switcher.py tests/test_publisher_imports.py` — все green | После B1, B2, B3, B4.1, B4.2 (по отдельности) |
| Integration smoke | 1 forced-fail task на phone #19 + наблюдать pm2 logs + `publish_tasks.events` | После B1 (Инакент), B2 (vera.smith yt_block), B4.1 (vision), B4.2 (SA-preflight) |
| Acceptance | 10 testbench YT задач подряд на phone #19 (mix Инакент+makiavelli), assert ≥8 done | В самом конце после prod sync |

## 5. Risk register

| ID | Риск | Mitigation |
|---|---|---|
| R1 | B1 back-press уносит из YT в launcher (если modal был fullscreen) | Pre-back guard: `dumpsys window mCurrentFocus` ∈ YouTube; иначе relaunch YT |
| R2 | B2 ложное срабатывание `yt_block` для still-working аккаунта | Triple-guard: text within picker-row bounds + clickable=true ancestor + handle/gmail in same row |
| R3 | B3 rename'ы reason'ов ломают triage_classifier / agent_diagnose | Pre-flight grep + обновление читателей в **том же** commit'е |
| R4 | B4.1 urllib.request hangs blocks main switcher loop | timeout=10s + try/except (фолбэк = «vision не сработал», как сейчас) |
| R5 | Commit-storm в prod: 4-5 коммитов, post-commit hook каждый раз пушит | Hook idempotent, нормально. Но `pm2 restart` делать **один раз** в конце |
| R6 | phone #19 unavailable (ADB drop) во время smoke | Fallback — phone #171 (`device_id=RF8Y90GCWWL`) |
| R7 | testbench и prod код-базы расходятся к моменту cherry-pick (соседняя сессия в prod) | `pm2 describe autowarm \| grep "exec cwd"` ДО prod-commit'а; `git log -1 --oneline` в обоих repo для сверки |

## 6. Rollback

Каждый commit изолирован → `git revert <sha>` в обоих repo (testbench + prod) + `pm2 restart`. B1 revert возвращает старый switcher fail на login-modal. B2 revert не уносит уже записанные `yt_block` (idempotent — записанные данные остаются, новые перестают писаться). B3 revert возвращает старые reason names + UI правки. B4.1/B4.2 revert изолированы.

## 7. Commit / PR plan

| # | Repo | Commit msg | Содержание |
|---|---|---|---|
| 1 | testbench | `fix(switch): YT modal-dismiss + picker-scroll on yt_3_open_accounts blocked` | B1 + tests |
| 2 | testbench | `feat(switch): mark yt_block on "Требуется действие" rows in YT picker` | B2 + tests |
| 3 | testbench | `refactor(switch): canonical error_code namespace + UI status display` | B3 + tests + index.html + server.js |
| 4 | testbench | `fix(switch): vision current_account handles HTTPS shot path` | B4.1 + tests |
| 5 | testbench | `fix(publisher): _resolve_single_account_mode import-path` | B4.2 + tests |
| 6 | prod (`/root/.openclaw/workspace-genri/autowarm/`) | `sync(switch+publisher): YT modal + yt_block + error namespace + 2 atomic fixes` | Cherry-pick 1-5 после testbench smoke green |
| 7 | contenthunter (текущая ветка) | `docs(plans+evidence+specs): yt-publish-stabilization-20260427 — design + executed` | Spec + plan + evidence |

**Не пушить commits 1-5 если smoke не green** (memory `feedback_parallel_claude_sessions.md` — atomic, no half-broken state).

## 8. Memory updates после имплементации

- Bump `project_publisher_modularization_wip.md` фактом «yt modal-dismiss + yt_block detection отгружено 2026-04-27».
- Если B3 раскрыл cross-platform паттерн — новая memory `feedback_switcher_error_namespace.md` с каноническим map.
- Update `project_publish_guard_schema.md` — реальные имена колонок (`device_serial`, `updated_at`, events JSONB вместо отдельной `publish_events` таблицы) — **существующая memory устарела, выяснилось при baseline**.
- Add `reference_anthropic_api_key.md` — путь `~/secrets/anthropic.env`, who reads it (5 модулей autowarm), формат `sk-ant-api03-...` (не OAuth).

## 9. Дальше

После approval этого спека:
1. Создаётся implementation-план через `/aif-plan` (или writing-plans skill) → `.ai-factory/plans/yt-publish-stabilization-20260427.md` с T1-T9.
2. Исполняется через `/aif-implement`.
3. Evidence пишется параллельно в `.ai-factory/evidence/yt-publish-stabilization-20260427.md`.
