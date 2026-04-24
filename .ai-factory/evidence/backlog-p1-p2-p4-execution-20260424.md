# Backlog execution 2026-04-24 — P2/P4/P1 session

**План:** `.ai-factory/plans/backlog-prioritized-review-20260424.md`
**Коммиты (autowarm):** `cdd0fba`, `77bc44c`, `527ee2e`
**Ветка:** `testbench` (prod autowarm), auto-push → `GenGo2/delivery-contenthunter`.

## P4 ✅ — Farming triage PM2 timer (30m loop)

Заменил ненаставленный systemd-таймер на PM2 app `autowarm-farming-triage`.

| Элемент | Путь |
|---|---|
| Wrapper | `scripts/farming-testbench/farming-triage-loop.sh` |
| PM2 config | `ecosystem.farming-testbench.config.js` (+новый app) |
| Env | `TRIAGE_INTERVAL_SEC=1800`, `TRIAGE_WINDOW_MIN=60` |

**Verify:**
- `sudo pm2 describe autowarm-farming-triage` → status=online, 0 restarts.
- Первый scan: `[farming-triage] scan_recent done: classified 0/2 tasks` — triage смотрит на testbench задачи за последние 60 мин.
- `sudo pm2 save` — persist across reboots.

**Commit:** `cdd0fba feat(farming-testbench): PM2 app autowarm-farming-triage — 30m loop`

## P2 ⏸ — Phone #171 TT cleanup (BLOCKED: сеть)

**Статус:** заблокировано network outage.

- `ping -c 3 82.115.54.26` → 100% loss.
- `mtr --report 82.115.54.26` → hop 5-6 все пакеты дропаются (до proxy не доходит).
- Memory `project_adb_push_network_issue.md` уже описывал 20% loss hop 4; сейчас — 100%. Провайдерская проблема.

**Когда proxy вернётся:**
1. `adb connect 82.115.54.26:15088`
2. `adb -s 82.115.54.26:15088 shell pm clear com.zhiliaoapp.musically`
3. User вручную залогинивает `born7499` (171b) + `user899847418` (171a) в TT
4. `python3 farming_triage_classifier.py --scan-recent --window-min 720` — closed tt_account_read_fail должна прекратить расти

**Bonus insight (P1 разведка):** эта же проблема распространяется на IG — foreign accounts на phone #171 IG (`reels`, `store`, `google`, `dr.maratovna01`) вытесняют `ivana.world.class` / `born.trip90` из IG switcher. После TT re-login имеет смысл одновременно:

```bash
adb shell pm clear com.instagram.android  # wipe все сессии
# user re-login born.trip90 + ivana.world.class
```

## P1 ✅ — IG switch failure taxonomy (case-B split)

**Разведка:** прочитал events 6 fixture tasks (`298,286,280,271,265,262`) — оказалось **не monolithic switcher bug**:

| Task | Dropdown вернул | Case | Корень |
|---|---|---|---|
| 298 | `['reels']` | B1 | ivana не залогинена |
| 286 | `['store', 'google']` | B1 | ivana не залогинена |
| 280 | `[]` | B1 | dropdown пуст |
| 271 | `[]` | B1 | dropdown пуст |
| 265 | `['dr.maratovna01']` | B1 | born не залогинен |
| 262 | `['born.trip90', 'ivana.world.class']` | **B3** | оба found, verify=@None после tap |

5/6 — **data issue** (нужен re-login, НЕ bug switcher). Только task 262 — real switcher UI-settle bug.

### Код-фикс

**warmer.py::switch_instagram_account**:
- Post-tap verify: до 3 попыток `get_current_instagram_account()` с sleep 2s между. Раньше — одна попытка, settle 3s.
- Когда new_acc=None после 3 попыток → emit `type=error` с `meta.category='ig_switch_verify_failed'`.
- Когда target не в `all_found` → emit `type=error` с `meta.category='ig_target_not_in_switcher'` (дополнительно к старому warning).

**farming_triage_classifier.py**:
- Добавлены regex для `ig_target_not_in_switcher` и `ig_switch_verify_failed` (размещены ДО generic `account_mismatch_after_switch`).
- `canonical_codes` dedup расширен: при наличии любого из B1/B3 кодов — убираем mismatch (как раньше работало для `*_account_read_fail`).
- **Идемпотентность (fix 527ee2e)**: `already_emitted` pre-collects codes из events, финальный фильтр `codes_found - already_emitted`. Инцидент: без этого stale-investigation account_mismatch_after_switch переоткрывалась при каждом 30m triage тике.

**migrations/20260424_ig_switch_error_codes_seed.sql**:
- `ig_target_not_in_switcher` (error, retry=none, is_auto_fixable=FALSE)
- `ig_switch_verify_failed` (error, retry=backoff, is_auto_fixable=TRUE)

**tests/test_farming_triage_classifier.py** — 7 pytest зелёные:
- B1/B3 happy path
- Pure B2 (bounds missing) — mismatch сохраняется
- Read_fail dedup regression
- Explicit-code skip
- Idempotent re-scan (инцидент-driven)
- Canonical dedup via already_emitted

### Backfill + final state

Ручной SQL backfill для 6 fixtures (regex не захватывает исторические `type=warning` events — только новые `type=error`):

```sql
UPDATE farming_investigations SET status='closed_fixed' WHERE error_code='account_mismatch_after_switch' AND status='open';
INSERT INTO farming_investigations (error_code, status, first_task_id, fixture_task_ids, occurrences_count) VALUES
  ('ig_target_not_in_switcher', 'open', 265, '{298,286,280,271,265}', 5),
  ('ig_switch_verify_failed',   'open', 262, '{262}', 1);
```

**Final open investigations:**

```
          error_code        | occurrences | n_tasks
----------------------------+-------------+--------
 ig_account_read_fail       |           3 |       1
 ig_switch_verify_failed    |           1 |       1   ← real UI-settle bug, smoke needed
 ig_target_not_in_switcher  |           5 |       5   ← требуется pm clear + re-login
 tt_account_read_fail       |          47 |      17   ← phone #171 TT foreign (P2)
 yt_account_read_fail       |          50 |      18   ← phone #171 YT bottom-nav
 farming_app_launch_failed  |          23 |      12
```

### Next actions (blocked on ADB restore)

1. **Case B1 cleanup**: `adb shell pm clear com.instagram.android` на phone #171 + user re-logs ivana + born. Должна закрыть `ig_target_not_in_switcher` investigation.
2. **Case B3 smoke**: после re-login — запустить farming задачу на IG. Если retry-verify (3× 2s) починит проблему — `ig_switch_verify_failed` закроется автоматически новым emit_farming_error с кодом и investigation will remain open только пока не retriage.
3. **TT parallel cleanup** (P2): тот же `pm clear com.zhiliaoapp.musically` + re-login born7499 + user899847418.

## Deployment

Все 3 коммита в prod `/root/.openclaw/workspace-genri/autowarm/` ветка testbench, auto-pushed в `GenGo2/delivery-contenthunter`:

```
527ee2e fix(triage): idempotent classify_events — skip codes уже эмитированные ранее
77bc44c fix(warmer+triage): разделить IG switch failure cases (B1/B3)
cdd0fba feat(farming-testbench): PM2 app autowarm-farming-triage — 30m loop
```

PM2 перезапущен: `autowarm` (PID 1645374 → new), `autowarm-farming-triage` (новый app id=28, PID 1760144).

Тесты:
- `pytest tests/test_farming_triage_classifier.py -v` → 7 passed
- `pytest tests/test_farming_errors.py tests/test_farming_orchestrator.py -q` → 19 passed (regression clean)

## Observations

- **Phone #171 foreign sessions — систематическая проблема** на всех 3 платформах (TT — @rahat.mobile.agncy.31; IG — reels/store/google/dr.maratovna01; YT — возможно тот же паттерн). Root cause: устройство использовалось в прошлом для других проектов, accounts не выпилены. Решение: **single pm clear sweep** на всех трёх apps + fresh re-login factory accounts.
- **Classifier self-reentry baseline check** должен быть базовым inv паттерном. Сохранил в тестах — если другая команда добавит новый regex без `already_emitted` pre-filter, тест `test_idempotent_rescan_does_not_repeat_already_emitted_code` отлично её поймает.
- **Bonus gotcha**: старые events имеют `type=warning`, classifier смотрит только на `error`/`status`. Исторические фикстуры не retriage без manual backfill — ок для one-shot, но если BE хочет reclassify старые tasks после каждого regex update → нужна отдельная CLI `--force-rescan` flag + scan всех events.
