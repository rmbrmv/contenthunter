# Farming Reuse Matrix — 2026-04-19

Финальный артефакт плана `farming-reuse-research`. Содержит TL;DR + ссылки на детали в evidence/ + top-3 кандидатов для портирования + готовые follow-up /aif-plan команды.

## TL;DR

1. **Фарминг де-факто остановлен с 2026-04-06** — 0 задач последние 13 дней. Все выводы — по срезу 2026-03-20 → 2026-04-06.
2. **Success rate 6.5 %** (8/122), успех только на IG protocol_id=1; TikTok и YouTube протоколы (2/3) — 0 completions.
3. **Доминирующий fail — account-read upstream** (77/178 error-events = 43 %); основной mechanism: retry-loop без force-restart app.
4. **Watchdog — DB-only**: не убивает Python-процесс.
5. **Два чужих репо — разные стеки:** autowarm_worker = Celery+Airtest+daily modules, auto_public = Celery+LLM screen-recovery. В обоих account-switching почти не автоматизирован.
6. **Top-3 reuse-кандидатов:** (A) force-stop + start + 8s settle pre-verify, (D) LLM screen-recovery, (B) pid + real kill watchdog.

## Детальные evidence-файлы

| Раздел | Файл |
|---|---|
| T1 — SQL baseline 30д | `farming-baseline-sql-20260419.md` |
| T2 — Account-read deep-dive | `farming-t2-account-read-deepdive-20260419.md` |
| T3 — Watchdog/hang deep-dive | `farming-t3-watchdog-hang-deepdive-20260419.md` |
| T4 — Completed-8 audit | `farming-t4-completed-audit-20260419.md` |
| T5 — Consolidated baseline MD | `farming-baseline-20260419.md` |
| T6 — autowarm_worker audit | `farming-t6-autowarm-worker-audit-20260419.md` |
| T7 — auto_public audit | `farming-t7-auto-public-audit-20260419.md` |
| T8 — File-to-file mapping | `farming-t8-file-mapping-20260419.md` |
| T9 — Reuse matrix + scoring | `farming-t9-reuse-matrix-20260419.md` |

## Top-3 кандидатов для портирования

### 1️⃣ Candidate A — Force-stop + start_app + 8s settle pre-verify

**Score:** 25.0 (Gain 5 × Fit 5 / Risk 1 × Effort 1) — самый эффективный quick win.

**Что:** обёртка в `warmer.py::verify_and_switch_account()`, которая **до первого account-check** и перед **каждым retry** делает:
1. `am force-stop com.instagram.android|com.zhiliaoapp.musically|com.google.android.youtube`
2. `am start -n <pkg>/.<activity>` или `monkey -p <pkg> -c android.intent.category.LAUNCHER 1`
3. `time.sleep(8)` для cold-start settle
4. **Затем** делает `get_current_*_account()`

**Откуда берём:** паттерн из `autowarm_worker/app/modules/humanize_with_coords.py::_cleanup_device` + `auto_public/uploader/base.py::connect_and_restart_app`.

**Файлы для изменения:**
- `/root/.openclaw/workspace-genri/autowarm/warmer.py`
  - Новый helper `_reset_app_state(platform: str) -> None` (≈20 строк)
  - Модифицировать `verify_and_switch_account()` :730 — вызов `_reset_app_state()` ПЕРЕД loop и внутри else-ветки retry
- `/root/.openclaw/workspace-genri/autowarm/tests/test_warmer_reset_app.py` (новый)
  - `test_reset_app_state_calls_force_stop`
  - `test_verify_and_switch_calls_reset_on_first_entry`
  - `test_verify_and_switch_calls_reset_on_retry`
- Feature-flag: через `autowarm_settings` (row name=`warmer_force_reset_enabled`, default=true для новых, false для rollback)

**Метрики успеха (через 7 дней):**
- `Не удалось прочитать аккаунт X после 3 попыток` — снижение с 77/30д до <20/30д
- `meta.category='wa_account_read_success'` первичный — ≥70 % vs retry-2 — ≤20 %
- total farming time до первой успешной фазы поиска — медиана < 2 мин (сейчас 50+ сек × 2-5 retries)

**Rollback:** выставить `warmer_force_reset_enabled=false` в `autowarm_settings`.

**Follow-up /aif-plan команда:**
```
/aif-plan full "Force-restart social app в warmer.verify_and_switch_account перед каждым retry (fix account-read 3-fail mode)"
```

---

### 2️⃣ Candidate B — `pid` column + реальный `process.kill` в watchdog

**Score:** 5.0 (Gain 4 × Fit 5 / Risk 2 × Effort 2).

**Что:**
1. `ALTER TABLE autowarm_tasks ADD COLUMN pid INT;`
2. При спавне Python-процесса в `scheduler.js` — записывать `pid` в `autowarm_tasks.pid`
3. В `watchdogStuckTasks()` (scheduler.js:118-154) — добавить:
   ```js
   if (task.pid) {
     try { process.kill(task.pid, 'SIGTERM'); } catch(e) {}
     await new Promise(r => setTimeout(r, 5000));
     try { process.kill(task.pid, 'SIGKILL'); } catch(e) {}
   }
   ```
4. Сократить порог `status='running'` watchdog с 2h до 40 мин (параметр в `autowarm_settings`)
5. В Python (`warmer.py` / любой farming entry) — `signal.signal(SIGTERM, cleanup_handler)` → закрыть ADB-сессии + финализировать DB-запись.

**Откуда:** паттерн из `server.js:3547-3549` (для factory_reg_tasks) + Celery SIGKILL из autowarm_worker.

**Файлы для изменения:**
- `/root/.openclaw/workspace-genri/autowarm/scheduler.js` — модификация tick + watchdogStuckTasks + запись pid после spawn
- `/root/.openclaw/workspace-genri/autowarm/warmer.py` — SIGTERM handler в main или run_autowarm_task entry
- migrations — `ALTER TABLE` (вынести в `server.js` init)
- `/root/.openclaw/workspace-genri/autowarm/tests/test_watchdog_pid_kill.py` (новый)

**Метрики успеха:**
- `Watchdog: зависание 1000+ мин` — исчезает (0 за 7 дней)
- Среднее `Watchdog: зависание N мин` — снижается с 120-2710 до 40-45 мин
- Новый `meta.category='wa_watchdog_sigterm_sent'` + `wa_watchdog_sigkill_forced` (для метрик)

**Rollback:** feature-flag `watchdog_kill_process_enabled` (default=true). При выключении — старое поведение (только UPDATE).

**Follow-up /aif-plan команда:**
```
/aif-plan full "pid column + SIGTERM/SIGKILL в autowarm_tasks watchdog + 40-мин threshold (fix hang-cluster)"
```

---

### 3️⃣ Candidate D — LLM-based screen-state recovery

**Score:** 1.78 (Gain 4 × Fit 4 / Risk 3 × Effort 3).

Это средне-долгий кандидат, но самый высокий по capability-expansion. Генерализует существующий detector-chain (`_is_ig_highlights_empty_state`, `_reopen_ig_reels_via_home` из PLAN.md текущей сессии).

**Что:**
1. Новый модуль `autowarm/llm_screen_recovery.py` (Anthropic Claude 4.5/4.6 Sonnet) — адаптация `auto_public/services/llm_manager.py`.
2. Integration points:
   - `publisher.py::_open_instagram_camera` — в catch-all перед emit `ig_camera_open_failed` → попробовать 1 LLM-recovery (screen screenshot → LLM → touch/confirm/alert)
   - `warmer.py::verify_and_switch_account` — после 3-го неуспеха `get_current_*_account()` → LLM попытка
3. Prompt — адаптированный `system_rare.txt`, но translated to Russian + specific context (warming/publishing).
4. Cost control: limit 1-2 LLM-calls per task (env var `LLM_RECOVERY_MAX_PER_TASK=2`).
5. Telemetry через новые `meta.category`:
   - `ig_llm_recovery_invoked`
   - `ig_llm_recovery_confirmed` / `ig_llm_recovery_touched` / `ig_llm_recovery_alerted`
   - `ig_llm_recovery_resolved_screen` — если после recovery следующий detector сработал

**Откуда:** `auto_public/services/llm_manager.py` + `auto_public/prompts/system_rare.txt`.

**Зависимости:** `anthropic` Python SDK (не httpx-wrapper auto_public, а нативный). Переключение с OpenRouter на прямой Anthropic API (у нас, вероятно, уже есть ключ).

**Файлы для изменения:**
- `/root/.openclaw/workspace-genri/autowarm/llm_screen_recovery.py` (новый, ≈150 строк)
- `/root/.openclaw/workspace-genri/autowarm/prompts/screen_recovery_ru.txt` (новый, ≈40 строк)
- `/root/.openclaw/workspace-genri/autowarm/publisher.py` — интеграция в `_open_instagram_camera` unknown-state branch (≈10-20 строк diff)
- `/root/.openclaw/workspace-genri/autowarm/warmer.py` — интеграция в `verify_and_switch_account` (≈10-15 строк diff)
- `/root/.openclaw/workspace-genri/autowarm/tests/test_llm_screen_recovery.py` (новый, mock Anthropic client)
- `/root/.openclaw/workspace-genri/autowarm/.env` — добавить `ANTHROPIC_API_KEY` + `LLM_RECOVERY_MAX_PER_TASK=2`

**Pilot:** только IG highlights empty-state кейс (из round-6 PLAN.md) — узкая pilot-интеграция для валидации.

**Метрики успеха:**
- `ig_llm_recovery_invoked` — 0.5-2.0 call/task (не чаще)
- `ig_llm_recovery_resolved_screen / ig_llm_recovery_invoked` — ≥ 30 %
- LLM cost per день — <$1 (с limit=2/task и ≈50 tasks/day)

**Rollback:** feature-flag `llm_recovery_enabled` (default=false, включаем пилот → true для 5 % задач → 100 %).

**Follow-up /aif-plan команда:**
```
/aif-plan full "LLM-based screen-state recovery для publisher.py + warmer.py (port auto_public pattern, Anthropic Claude 4.6 Sonnet)"
```

---

## Бонус: дополнительные quick-wins (top-5 PORT)

Кроме top-3 выше, план также рекомендует портировать (все S-effort, высокий score):

### 4. Candidate C — `meta.category` везде в warmer.log_event

**Score:** 15.0. Эффорт: S (0.5 дня). Все 178 error-events warming-кода сейчас имеют `meta.category=NULL`. Просто добавить `category='wa_*'` в каждый `log_event('error'/'warning', ...)` call в `warmer.py` и account-switch методах.

```
/aif-plan fast "Добавить meta.category во все warmer.log_event (параллельно publisher.py pattern, fix monitoring blocker)"
```

### 5. Candidate K — pm2 recycling config

**Score:** 15.0. Эффорт: S (1-2 часа). Добавить в `ecosystem.config.js` для farming worker:
```js
{
  max_memory_restart: '350M',
  max_restarts: 5,
  min_uptime: '60s',
}
```
Аналог Celery `worker_max_memory_per_child=350` + `worker_max_tasks_per_child=2`.

```
/aif-plan fast "pm2 max_memory_restart + max_restarts config для autowarm workers (Celery-like recycling)"
```

### 6. Candidate H — Secure DB creds (.env)

**Score:** 7.5. Эффорт: S. Вынести `DB_CONFIG` из `publisher.py:41` в `.env` + `os.getenv`. Безопасность + гигиена.

```
/aif-plan fast "Вынести DB_CONFIG из publisher.py:41 в .env (security: password сейчас hardcoded в исходнике)"
```

## Next actions (готовый список follow-up команд)

В порядке рекомендуемого внедрения:

```bash
# Phase A — Quick wins (1-5 дней total)
/aif-plan fast "Добавить meta.category во все warmer.log_event (fix monitoring blocker)"
/aif-plan fast "pm2 max_memory_restart + max_restarts config для autowarm workers"
/aif-plan fast "Вынести DB_CONFIG из publisher.py:41 в .env (security)"
/aif-plan full "Force-restart social app в warmer.verify_and_switch_account перед каждым retry (fix account-read 3-fail mode)"
/aif-plan full "pid column + SIGTERM/SIGKILL в autowarm_tasks watchdog + 40-мин threshold"

# Phase B — Architectural (1-2 недели)
/aif-plan full "LLM-based screen-state recovery для publisher.py + warmer.py (pilot на IG highlights empty-state)"

# Phase C — Опционально, после результатов Phase A
/aif-plan full "Починить autowarm_protocols 2 (TikTok) и 3 (YouTube) — портирование daily modules из autowarm_worker"
```

## Риски рекомендованного плана

1. **Cumulative effect может маскировать regression.** Разворачивать по одному с 24-48h verify перед следующим.
2. **LLM-recovery (D) может скрыть баги, которые лучше фиксить кодом.** Telemetria `ig_llm_recovery_resolved_screen` каждые 7 дней — если один и тот же экран детектится LLM'кой >5 раз в неделю, значит пора писать rigid detector для него.
3. **Force-restart (A) может замедлить быстрые задачи.** +8 сек на каждый warming-start × 100 задач/день = +13 мин machine time. Приемлемо.
4. **pid-watchdog (B) может race-condition'ить с legit долгим publish'ем.** 40-мин threshold для farming безопасен (самая долгая фаза прогрева — watch_search_results <20 мин), но для publishing оставляем 2h.

## Что этот план НЕ делает

- Не чинит **protocols 2/3** (TT/YT) самостоятельно — это Phase C, после того как инфра-фиксы стабилизируют метрики
- Не мигрирует на Celery — benefit сомнителен, cost большой
- Не внедряет Poco — наш стек на ADB, Poco дал бы много зависимостей за малый выигрыш
- Не трогает `publish_tasks` watchdog (там 2h — правильный порог для долгих публикаций)
