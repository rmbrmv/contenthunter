# Silent IG hangs on `ig_2_profile_tab_fg_guard` — discovery 2026-05-04

## Symptom

181 IG fail/7д с empty `error_code` (после `ig_caption_fill_failed=108`, теперь #1 категория после фикса caption). Pattern: `status='failed'`, `error_code IS NULL`, без error/fail event в `events` JSONB.

## Concrete tasks reviewed

| task | account | device | started | updated | elapsed | nev |
|---|---|---|---|---|---|---|
| 2826 | 1content_hunter | RFGYA19DNGZ | 18:57:18 | 19:04:55 | 457s | 18 |
| 2816 | autopostfactory | RFGYA19DNGZ | 18:18:01 | 18:25:18 | 437s | 12 |
| 2810 | anecole_education | RF8Y90LBZPJ | 18:10:01 | 18:25:18 | 917s | 37 |

Tasks 2810-2816 закрылись batch'ом в **18:25:18** = batch watchdog cycle.

## PM2 log evidence — task 2826

Last 3 log lines before silence:
```
19:00:48 [step] switcher: ig_2_profile_tab
19:00:48 [step] switcher: ig_2_profile_tab_fg_guard
19:00:48 💓 [Instagram] switcher: ig_2_profile_tab_fg_guard
```

Тишина 4+ минуты до updated_at=19:04:55. **Никаких log lines, никаких heartbeat (`💓`)**. То есть main Python thread полностью frozen / killed.

## Root cause analysis — 2 layers

### Layer 1 — `error_code=NULL` маскирует категорию (mapping bug)

`server.js:5994` — `watchdogRunningTasks` каждые 2 мин:
```js
WHERE pt.status = 'running' AND pt.updated_at < NOW() - INTERVAL '3 minutes'
// → UPDATE status='failed', log=COALESCE(log,'')||$1
```

Записывает строку только в `log` column. **Не пишет error event в `events` JSONB**.

`publisher_base.py::_set_error_code_from_events` итерирует events JSONB ища `type='error'`/`type='fail'`. Watchdog kill даёт только log entry → error_code остаётся NULL.

**Импакт:** все 181 silent hang за 7д не имеют категоризации в triage SQL.

### Layer 2 — stale step name → wrong watchdog timeout

`set_step('switcher: ig_2_profile_tab_fg_guard')` ставится в `_open_app` (`account_switcher.py:3188`) для foreground-guard фазы (deadline=45s). После возврата `_open_app` step name НЕ обновляется в:
- `_go_to_profile_tab` (продолжает с tap, dump, etc.)
- `_switch_instagram` post-`_go_to_profile_tab` → `_read_screen_hybrid('ig_3_profile_screen')` (нет set_step внутри)

`_lookup_step_timeout('switcher: ig_2_profile_tab_fg_guard')` — ни один STEP_TIMEOUTS pattern не substring-match → fallback `STEP_TIMEOUT_DEFAULT=120s`. Python WatchdogTimer 120s timer running на этом stale step.

**Известный паттерн** — комментарии в `publisher_base.py:1505` и `publisher_instagram.py:749` уже фиксили stale step для **success path** (`set_step('post-account-switch')` после happy switcher) и **camera open** (`set_step('open_camera')`). НО **failure/intermediate path** (когда `_open_app` returns False или после успеха продолжается _go_to_profile_tab) — НЕ покрыт.

### Layer 3 — что именно hangs (untested, hypotheses)

Heartbeat thread не fires после 19:00:48. Heartbeat thread = отдельная Python нить должна работать пока GIL свободен. То что она тоже остановилась — указывает на:
1. **Subprocess полностью frozen** (e.g., infinite C-call hold GIL) — маловероятно для adb subprocess
2. **SIGKILL процесса извне** — но server.js watchdog не киляет subprocess (только UPDATE), значит не он
3. **Process exit без cleanup** — но тогда был бы пустой proc, и cleanup post_task event не появился бы (он есть в events 2826 в 19:01:09)

Wait — cleanup post_task event в `events` есть в 19:01:09, но в pm2 log ничего после 19:00:48. Это противоречит. Возможно cleanup event записан **другим процессом** (orchestrator? watchdog log marker? ретраер?).

Нужны живые данные: py-spy dump или strace на следующем hung subprocess.

## Predicted hangs origin (rank by likelihood)

1. **adb subprocess infinite hang** — несмотря на `timeout=15s` + `killpg`, remote adb server (`-H 82.115.54.26 -P 15088`) при packet loss может вернуть partial response, и `proc.communicate(timeout=15)` всё равно срабатывает. Но если adb-сервер на той стороне сам hang'ит на ` uiautomator dump`, нашему коду должно прийти timeout. Так что это **отвечает за длинные задержки до 30-60s** но не за 4+ мин.
2. **`_dismiss_blocking_overlays` cycle** — внутри несколько adb tap + dump_ui calls. Если loop без bound — может циклить. Чтение кода: TODO.
3. **dump_ui infinite retry** в каком-то caller'е — внутри `_open_app` `dump_ui(retries=1)` × 4-5 раз сериально. Total 60-120s. Не объясняет 4 мин.

## Next steps (user decision needed)

### Quick wins (high confidence, low risk)

**Fix Layer 1 (mapping)** — server.js:5994 watchdog should write error event into `events` JSONB:
```js
const evt = {
  ts: new Date().toTimeString().slice(0,8),
  type: 'error',
  msg: `Watchdog: subprocess silent ${staleMin} мин`,
  meta: {
    category: 'watchdog_subprocess_hang',
    step: '<no step accessible from JS>',  // unless we add set_step → DB write
    stale_min: staleMin,
  }
};
await pool.query(
  `UPDATE publish_tasks SET events = COALESCE(events,'[]'::jsonb)||$1::jsonb WHERE id=$2`,
  [JSON.stringify([evt]), task.id]
);
```

После этого фикса: все 181/нед silent-hangs будут приходить с `error_code='watchdog_subprocess_hang'` → видимы в triage.

**Fix Layer 2 (stale step name)** — добавить `set_step` после `_open_app` в `_go_to_profile_tab` и в `_switch_instagram` после `_go_to_profile_tab`:
- `account_switcher.py:3294` (после `_open_app` в `_go_to_profile_tab`): добавить `self.p.set_step(f'switcher: {step_name}_tap_phase')`.
- `account_switcher.py:1196` (между `_go_to_profile_tab` и `_read_screen_hybrid`): no-op since `_read_screen_hybrid` сейчас не обновляет — лучше fix в `_read_screen_hybrid` itself.
- `_read_screen_hybrid:3389` нужен `self.p.set_step(f'switcher: {step_name}')` в начале.

После этого фикса: правильный per-step timeout (если STEP_TIMEOUTS pattern matches), правильный stuck-step name в watchdog log.

### Deep dive (Layer 3, требует live access)

- Запустить py-spy на следующий hung subprocess — увидим stack trace stuck thread.
- Strace -p на subprocess — покажет какой syscall блокирует.
- Альтернатива: добавить `signal.alarm(60)` на `_open_app` целиком чтобы получить SIGALRM trace.

## Memory references

- `project_ig_switch_silent_hang_backlog.md` — original backlog item
- `project_adb_push_network_issue.md` — packet loss VPS↔proxy hop 4 (related)
- `feedback_silent_crash_layered.md` — silent crash discovery pattern
- `feedback_publisher_error_code_misleading.md` — error_code map writes first event, not last
