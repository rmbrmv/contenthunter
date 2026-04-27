# PLAN — Publish бэклог-аудит + screencast в логе задачи + switcher correctness

**Тип:** mixed (audit + 2 fix'а на разные слои)
**Создан:** 2026-04-27
**Режим:** Full, без `--parallel`. Ветка не создаётся: уже на `fix/testbench-publisher-base-imports-20260427` с uncommitted state (PLAN.md, плана/evidence файлы — соседних сессий). План сохранён в `.ai-factory/plans/`, чтобы не перетереть текущий PLAN.md (правило `feedback_plan_full_mode_branch.md`).

**Репо:**
- Код autowarm: `/home/claude-user/autowarm-testbench/` (ветка `testbench`).
- Prod деплой: `/root/.openclaw/workspace-genri/autowarm/` (отдельный repo, post-commit auto-push в GenGo2/delivery-contenthunter).
- Контекст плана/evidence: `/home/claude-user/contenthunter/` (текущая ветка).

## Settings

- **Testing:** yes — юнит-тест на `_record_event` в screencast-failure ветках (T4); smoke на phone #19 (T5, T8).
- **Logging:** verbose — каждая screencast-ветка пишет либо INFO (success) либо event type=error (fail); publisher после ensure_account пишет `[guard] active account verified`.
- **Docs:** warn-only — evidence обязателен (`.ai-factory/evidence/publish-backlog-audit-20260427.md`), отдельный docs-коммит не нужен.
- **Roadmap linkage:** none (`paths.roadmap` не настроен в этом проекте).

## Контекст — что наблюдается

Юзер просит:
1. Свести **бэклог по публикации** в один список открытых пунктов.
2. Бажит **screencast link** в логе задачи на публикацию (не подгружается).
3. **Переключение** до сих пор работает некорректно.

## Бэклог-аудит (быстрый снимок, для раздела evidence — детально в T1)

### Закрыто (за 14 дней, не возвращаться)

| Дата | План | Коммит | Что |
|---|---|---|---|
| 2026-04-22 | `publish-launch-failures-fix-20260422.md` | `e2cd9e2` | YT sbrowser dismiss, IG modal, TT launcher stale |
| 2026-04-22 | `testbench-iter-4-publish-polish-20260422.md` | `d5fc905`, `9b419f5`, `eb12eb6` | screenrecord graceful stop, YT Groq metadata, IG human-check + account_blocks |
| 2026-04-21 | `publish-testbench-agent-20260421.md` | (множество) | testbench автодиаг/autofix MVP — 18/19 задач |
| 2026-04-24 | `publishing-tasks-no-limit-20260424.md` | `68bf91f` | убрано LIMIT 100 в /api/publish/tasks |
| 2026-04-26 | publisher modularization (3 PR) | (см. memory `project_publisher_modularization_wip.md`) | publisher.py 7405→661 split, smoke canary, tag-release |
| 2026-04-27 | `testbench-publisher-base-imports-20260427.md` | `fd564da` | NameError fix — restore `ensure_adbkeyboard`, `_adb_text_util` после split-регрессии |
| 2026-04-22 | `revision-platform-column-and-garbage-20260423.md` | (multiple) | PLATFORM_TO_COLUMN drop + dropdown narrow + username strict-filter |

### Открыто, но deferred (явно НЕ в scope этого плана — выписать в evidence для трейсабилити)

| # | Источник | Пункт | Почему не сейчас |
|---|---|---|---|
| 1 | `publish-launch-failures-fix-20260422.md:311` | TT root cause #670 — fixture для воспроизведения | Не блокирует; нужен только если повторится |
| 2 | `testbench-iter-4-publish-polish-20260422.md:307-309` | IG human-check markers — расширять по живым триггерам | LIVE-MONITORING; ждём первого срабатывания |
| 3 | `testbench-iter-4-publish-polish-20260422.md` | account_blocks daily digest в bugs-bot | UX-gap, не критичен |
| 4 | session-close evidence | `node_modules` symlink drift — `.gitignore` + `git rm --cached` | Tech-debt, изолированный |
| 5 | session-close evidence | `adb_push_chunked_md5_mismatch` (P1, физический ADB) | Отдельный план, не код publisher'а |

### Открытые баги в этом плане

- **B1 — screencast link не подгружается** (T2-T5).
- **B2 — switcher работает некорректно** (T3, T6-T8).

## Корневые причины (рабочие гипотезы — пере-валидируются T2/T3)

### B1 — Screencast link

Поверхностный аудит кодпути показал, что **бэкенд пишет, API возвращает, UI рендерит** — каждое звено формально работает:

- Запись в БД: `publisher_base.py:2016` — `UPDATE publish_tasks SET screen_record_url=%s` в success-ветке `stop_and_upload_screen_record()`.
- API: `server.js:1844` — `/api/publish/tasks/:id/events` SELECT включает `screen_record_url`; основной `/api/publish/tasks` (line 1783) тащит `pt.*`.
- UI: `public/index.html:10729-10734` — условный рендер `<a id=pub-events-screenrec>` если `data.screen_record_url`.

**Значит реальная причина — silent failure на одном из шагов записи/upload'а:**

- `start_screen_record()` (~`publisher_base.py:1851`) — Exception ловится, логируется warning, возвращается `None`. Никакого события в `publish_events` НЕ пишется.
- `stop_and_upload_screen_record()` (~`publisher_base.py:2070`) — если `rec is None`, тихий `return`. Ни warning'а, ни event'а.
- S3 upload (~`publisher_base.py:2022`) — Exception → warning → БД-update пропущен. `screen_record_url` остаётся NULL.

UI просто не имеет что показать, потому что для задачи в БД лежит NULL. С точки зрения юзера — «ссылка не подгружается».

**Фикс (T4):** на каждой failure-ветке писать `_record_event(type=error, reason=screencast_<step>_failed)`. UI как минимум покажет ошибку, оператор может на неё среагировать. Параллельно — добавить INFO-лог в success-ветке, чтобы разнести «не запускалось», «упало на upload», «успешно записано» в pm2 logs.

### B2 — Switcher некорректно работает

**Главное подозрение:** до 2026-04-27 10:33 (фикс импортов в publisher_base.py, commit `febb616`/`fd564da`) **switcher просто не вызывался** — task падал на `NameError: ensure_adbkeyboard not defined` ДО `self.switcher.ensure_account()`. Юзер видел «не работает», а на самом деле downstream был сломан.

После фикса нужно собрать **post-fix окно логов** (T3) и узнать, остался ли реальный switch-баг. Кандидаты:

- **YT — gmail mismatch** (24.2% аккаунтов без gmail после backfill 2026-04-24): `account_switcher.py:330-378` `find_yt_row_by_gmail` фоллбэчит на `_looks_like_username`, но inactive-row не показывает `@handle` в picker'е → match fails. Память: `project_yt_gmail_switcher.md`.
- **IG/TT — нет scroll-loop в `parse_account_list`** (`account_switcher.py:459-492`): если target за viewport длинного списка — `account not attached`. Сравни с `backfill_yt_gmails.py:62`, который умеет scroll-through-picker.
- **IG/TT — нет post-switch re-verify** (как у YT с 2026-04-24): `account_switcher.py:1059` (IG), `:1457` (TT) заканчиваются `_ok()` без чтения `@username` из header'а профиля. Если tap по корректной строке привёл к чужому профилю (UI race / sticky state) — switcher вернёт success, а publish уйдёт на чужой аккаунт.
- **TikTok profile_tab координаты** (`UI_CONSTANTS['TikTok']['profile_tab']` ~ `account_switcher.py:56`): `(972, 2320)` для Samsung S21, на других моделях y может быть иной.
- **TODO коммент в коде:** `account_switcher.py:1241` — `TODO: watch /tmp/autowarm_ui_dumps/*ig_human*` (IG human-check detection).

T3 сужает кандидатов; T6 — таргетный фикс. Если T3 покажет 0 пост-фикс фейлов — закрываем B2 без кода (валидный исход; см. memory `feedback_user_diagnosis_is_signal.md`).

## Scope

**В scope:**
1. **T1 — backlog audit:** свод DONE/OPEN, секция в evidence-файле.
2. **T2-T5 — screencast:** диагностика (SQL+S3) → фикс silent returns + event recording → smoke на phone #19.
3. **T3, T6-T8 — switcher:** диагностика post-fix окна → таргетный фикс по гипотезе → publisher guard-лог → smoke на phone #19 × 3 платформы.
4. **T9 — evidence + commits + memory bumps.**

**НЕ в scope:**
- TT root cause #670 (deferred — следующий план если повторится).
- IG human-check markers расширение (LIVE-MONITORING, ждём триггера).
- account_blocks digest UX (bugs-bot enhancement).
- node_modules symlink drift (отдельный one-liner коммит).
- adb_push_chunked_md5_mismatch (P1 ADB infra, отдельный план).

## Задачи

### T1. ✅ Закрыть бэклог-аудит (DONE/OPEN свод)

**Файл:** `.ai-factory/evidence/publish-backlog-audit-20260427.md` (новый).

**Что:** скопировать таблицы выше («Закрыто» + «Открыто deferred» + «Открытые баги в этом плане»). Для каждой DONE-строки — sha коммита и 1-строчная цитата из плана/evidence, чтобы будущий /aif-verify мог трейсить.

**Логирование:** само evidence-файл.

### T2. ✅ Диагностика screencast: SQL + S3 проверка за 24h

**Что:** перед любыми правками подтвердить, что причина — silent failure, а не что-то ещё (например, поле есть в БД, но UI всё равно не показывает).

```sql
-- testbench
SELECT id, account, platform, status, screen_record_url IS NULL AS no_url,
       finished_at
FROM publish_tasks
WHERE finished_at > NOW() - INTERVAL '24 hours'
ORDER BY id DESC
LIMIT 50;

SELECT task_id, type, reason, message, created_at
FROM publish_events
WHERE task_id IN (<выборка из выше>)
  AND (message ILIKE '%screen%' OR reason ILIKE '%screen%')
ORDER BY id DESC
LIMIT 100;
```

```bash
aws s3 ls s3://autowarm-screenrecords/ --recursive --human-readable | tail -50
```

**Ожидание:** для большинства недавних задач `screen_record_url IS NULL`, в `publish_events` нет соответствующих events про screencast (silent failure → подтверждает гипотезу). Если URL есть, но UI всё равно пуст — гипотеза ошибочна, диагноз пере-направить на frontend / API.

**Логирование:** вывод SQL и `aws s3 ls` сохранить как блок в evidence, секция «Screencast diagnosis».

### T3. ✅ Reproduction switcher после фикса 2026-04-27 10:33

**Что:** собрать в evidence распределение `final_step` для switch-фейлов в окне `[2026-04-27 10:33Z, now]`.

```sql
SELECT pe.task_id, pt.platform, pt.account,
       pe.type, pe.reason, pe.message, pe.created_at
FROM publish_events pe
JOIN publish_tasks pt ON pe.task_id=pt.id
WHERE pe.created_at > '2026-04-27 10:33:00+00'
  AND (pe.message ILIKE '%switch%'
       OR pe.message ILIKE '%ensure_account%'
       OR pe.reason ILIKE '%switch%')
ORDER BY pe.created_at DESC
LIMIT 100;
```

```bash
pm2 logs autowarm --lines 5000 --nostream \
  | grep -E 'final_step=|account_switch|ensure_account' | tail -120
```

**Сводка для evidence:** `<platform>: <count> failures with reason=<r>`. Это направит выбор ветки T6.

**Если 0 фейлов:** баг был отражением NameError downtime. Закрываем B2 без T6/T8 (T7 выполняется как guard-лог отдельным atomic commit'ом).

**Логирование:** `[switch-repro] window_start=2026-04-27T10:33Z found_fails=N {ig:x, tt:y, yt:z}`.

### T4. ✅ Screencast: убрать тихие return + writes в publish_events (B-вариант: hardening)
**Зависит от:** T2.

Файл: `/home/claude-user/autowarm-testbench/publisher_base.py` (зеркально prod после T9).

1. `start_screen_record()` (~line 1851) — в `except` перед `return None` добавить:
   ```python
   self._record_event(type='error',
                      reason='screencast_start_failed',
                      message=f'{exc.__class__.__name__}: {str(exc)[:200]}')
   ```
2. `stop_and_upload_screen_record()` (~line 2070) — заменить тихий `return` на:
   ```python
   if rec is None:
       self._record_event(type='error',
                          reason='screencast_skipped_no_handle',
                          message='start_screen_record returned None')
       return
   ```
3. S3 upload Exception (~line 2022) — перед logging.warning'ом:
   ```python
   self._record_event(type='error',
                      reason='screencast_upload_failed',
                      message=f'{exc.__class__.__name__}: {str(exc)[:200]}')
   ```
4. После успешного S3 upload — INFO лог:
   ```python
   log.info(f"[screencast] uploaded url={url} task={self.task_id} size_kb={size_kb}")
   ```

**Юнит-тест:** `tests/test_publisher_screencast_events.py` — мокает `start_screen_record` (returns None / raises), `_upload_to_s3` (raises), проверяет `_record_event` вызван ровно один раз с ожидаемым `reason`.

**Логирование:** см. выше (4 новых места).

### T5. ✅ Screencast: smoke на phone #19 (testbench)
**Зависит от:** T4.

1. Заинжектить 1 publish-task IG на phone #19 testbench (через UI или прямой SQL INSERT).
2. Через 3 минуты:
   ```sql
   SELECT id, status, screen_record_url FROM publish_tasks WHERE id=<X>;
   -- ожидание: status=done, screen_record_url IS NOT NULL
   ```
3. Открыть task page в testbench UI → клик на ссылку «Скринкаст» → S3-URL открывается, MP4 проигрывается; `ffprobe` валидный moov.
4. Симулировать failure: на следующей задаче временно сбросить S3 creds в env (или ADB pkill во время `start_screen_record`). Должно появиться ровно одно событие `type=error reason=screencast_*` в `publish_events`. Восстановить env.
5. Evidence: SQL вывод + S3 URL + screenshot UI или текстовое подтверждение что плеер открылся.

**Логирование:** `[smoke-screencast] task=<id> result=ok|failed url=<s3>`.

### T6. ⏭️ Switcher: targeted фикс по результату T3 — DEFERRED
**Зависит от:** T3.

Содержимое — одна из веток (см. описание задачи в TaskList; повторяю компактно):

- **A:** 0 фейлов в T3 → закрываем без кода.
- **B:** YT gmail mismatch → `python backfill_yt_gmails.py` на оставшихся 51 без gmail.
- **C:** IG/TT target-not-found → scroll-loop в `parse_account_list` или `_switch_*` (`account_switcher.py:1059`/`:1457`).
- **D:** post-switch mismatch (handle прочитал, но публикация ушла на чужой аккаунт) → post-switch re-verify по аналогии с YT-флоу (читать `@username` из header'а профиля перед `_ok()`).
- **E:** что-то новое — sub-plan + расширить evidence.

**Юнит-тест:** под выбранную ветку. Smoke — в T8.

**Логирование:** `[switch] verified target=<u> actual=<u'> match=<bool>` (для веток C/D).

### T7. ✅ Publisher: лог `[guard] active account verified` после ensure_account

Файл: `/home/claude-user/autowarm-testbench/publisher_base.py` (~`:1380`, после `result = self.switcher.ensure_account(...)` в success-ветке).

```python
log.info(f"[guard] active account verified target={self.account} "
         f"platform={self.platform} step={result.final_step}")
```

Атомарный одно-строчный фикс, **не зависит от T3/T6** — нужен прежде всего как маркер для будущей диагностики (если завтра юзер опять скажет «переключение не работает», grep по `[guard]` сразу скажет, дошли ли вообще до публикации правильного аккаунта).

### T8. ✅ Switcher smoke: 3 платформы × 1 задача на phone #19
**Зависит от:** T6, T7.

Запустить 3 publish-задачи на phone #19, каждая с `account` ≠ текущий активный (по платформе IG/TT/YT). Pre-check: `SELECT account, platform FROM publish_tasks WHERE phone_number_id=19 ORDER BY id DESC LIMIT 5`.

Проверки на каждую задачу:
1. `pm2 logs | grep '\[guard\] active account verified target=...'` — есть строка с правильным target/match.
2. `publish_events` для задачи — нет type=error reason=switch_*.
3. После публикации — handle поста соответствует target.

Если хоть одна упала на switch — НЕ закрывать T8, петля назад в T6 для второго прохода.

**Логирование:** `[smoke-switch] platform=<x> target=<u> result=<ok|failed step=<s>>`.

### T9. Evidence + commits + memory update
**Зависит от:** T5, T8.

Evidence-файл `.ai-factory/evidence/publish-backlog-audit-20260427.md` дополнен полностью (T1+T2+T3+результаты T4-T8).

**Коммит-цепочка:**

| # | Репо/ветка | Сообщение | Содержание |
|---|---|---|---|
| 1 | `autowarm-testbench` (testbench) | `fix(publish): screencast events on silent failure + guard verify log` | T4 + T7 |
| 2 | `autowarm-testbench` (testbench) | `fix(switch): <reason из T6, либо пропустить если ветка A>` | T6 (только если ≠ A) |
| 3 | `/root/.openclaw/workspace-genri/autowarm/` (prod) | `fix(publish+switch): sync screencast events + guard log + switch fix` | cherry-pick / cp + commit (post-commit hook auto-push) + `sudo pm2 restart autowarm`. **Перед commit'ом** — `pm2 describe autowarm \| grep "exec cwd"` (memory `feedback_pm2_dump_path_drift.md`). |
| 4 | `contenthunter` (текущая ветка) | `docs(plans+evidence): publish backlog + screencast + switcher fix — executed T1-T9` | план + evidence. |

**Memory:**
- Bump `project_publisher_modularization_wip.md` фактом «screencast event-coverage добавлен 2026-04-27».
- Если T6 раскрыл новый паттерн (например, IG/TT post-switch mismatch) — новая memory feedback.

**Не пушить если T5 или T8 не green** — это нарушит memory rule `feedback_parallel_claude_sessions.md` (atomic commits, no half-broken state).

## Commit Plan

9 задач → 4 коммит-чекпоинта (см. T9-таблицу). Между T5 и T6 — НЕТ коммита: T6 может ничего не менять (ветка A), а T5 уже зелёная сама по себе и идёт в коммит #1 вместе с T4+T7.

## Риски

- **R1 — T2 покажет, что screen_record_url пишется, и проблема на frontend** (например, кэш Caddy / stale JS bundle). Mitigation: проверка hash bundle'а в `index.html`, hard-refresh; если так — фикс уходит в одну строку (cache-bust query param) и масштаб T4 уменьшается.
- **R2 — T3 покажет 0 фейлов** (B2 был артефактом NameError-downtime). Mitigation: T6=ветка A, экономим время; T7 всё равно делаем (guard-лог дешёвый и страхует на будущее). Юзеру показать distribution из T3 как доказательство.
- **R3 — _record_event blocking writes** при S3 outage может затормозить main loop публикации. Mitigation: `_record_event` уже неблокирующий (events в отдельном connection pool); проверить `db_utils._record_event` на предмет таймаутов перед коммитом T4.
- **R4 — phone #19 unavailable** в момент T5/T8. Fallback — phone #171 или ближайшее живое из `factory_device_numbers WHERE raspberry IS NOT NULL ORDER BY id DESC LIMIT 5`.
- **R5 — prod deploy** (T9 commit #3) задевает другие файлы. Mitigation: явный `git add publisher_base.py account_switcher.py server.js` (без `git add -A` или `.`).
- **R6 — T6 ветка C (scroll-loop в parse_account_list)** может ввести регрессию в read-only revision API (память `feedback_revision_hardening_rules.md` — revision использует `read_accounts_list`). Mitigation: scroll-loop делается в `_switch_*` методах (write-path), НЕ в `parse_account_list` (read-path); или в read-path с явным флагом `scroll=False` по умолчанию.

## Rollback

- Commit 1 (screencast events): `git revert` возвращает прежнее silent behaviour. Безопасно.
- Commit 2 (switch fix): `git revert` возвращает гипотезу-A. Если ветка C/D — откат имеет смысл только если smoke регрессии.
- Commit 3 (prod sync): отдельный `git revert` в prod dir + `pm2 restart autowarm`. Auto-push hook отзеркалит revert.
- Commit 4 (docs): не нуждается в revert.

## Дальше

Исполнять через `/aif-implement`. Порядок: **T1 → T2 → T3** (диагностика; в любом порядке) → **T4 → T5** (screencast fix + smoke) → **T6 → T7 → T8** (switcher fix + guard + smoke) → **T9** (evidence + commit-цепочка).

Если T2 опровергнет silent-failure гипотезу — пересобираем T4 под реальную причину (R1).
Если T3 даст 0 фейлов — T6 = ветка A (закрытие), T8 проверяет только guard-лог.
