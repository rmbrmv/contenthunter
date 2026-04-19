# Farming tasks baseline — 30-дневный анализ (T1-T4)

**Дата:** 2026-04-19
**Окно:** последние 30 дней (2026-03-20 → 2026-04-19)
**Источники:** `autowarm_tasks` (postgres openclaw@localhost:5432), warmer.py, scheduler.js, публичные клоны `/tmp/autowarm_worker`, `/tmp/auto_public`

## TL;DR

1. **Фарминг де-факто остановлен:** за последние 13 дней (с 2026-04-06) — 0 задач. Весь анализ — по срезу 2026-03-20 → 2026-04-06.
2. **Success rate 6.5 %** (8 completed / 122 total). Среди стартовавших — 8 % (8/100 excl. preflight_failed+offline).
3. **Все 8 успехов — `protocol_id=1` (Instagram базовый)**, достигли day=10. TikTok (`protocol_id=2`) и YouTube (`protocol_id=3`) протоколы **никогда** не доходили до завершения — умирают на day 1-4.
4. **Дoминирующий класс ошибок: upstream account-read fail** (77/178 error-events = **43 %**) — ещё до фитнес-действий. Детали в T2.
5. **Watchdog — только DB-accountant:** 19 событий «зависание 120-2710 мин». Python-процесс **не убивается**, только DB-статус флипается. Детали в T3.
6. **`events[].meta.category` не заполняется** ни в одном farming-событии (vs publish_tasks, где используется). Блокер для мониторинга/алертов.

## 1. Status distribution (30 дней, 122 задачи)

| status | count | % |
|---|---:|---:|
| failed | 77 | 63 % |
| preflight_failed | 22 | 18 % |
| offline | 8 | 6.5 % |
| completed | 8 | 6.5 % |
| paused | 7 | 5.7 % |

**Activity cliff:** пик активности 2026-03-23 (72 failed + 7 completed), после 2026-04-06 — 0 задач.

## 2. Top failure modes

| Кластер | Count | % error-events | Root cause (оценка) |
|---|---:|---:|---|
| **Account read fail (3 попытки)** | 77 | 43 % | `warmer.verify_and_switch_account()` retry window = 3×5s без state-reset; для TT — 1 regex `text="@..."`, ловит мусор |
| **Account mismatch** | ≈60 | 34 % | downstream от read-fail: если `current is None`, switcher не запускается; часть — реальный mismatch (61 уникальный аккаунт) |
| **Watchdog hang** | 19 | 11 % | scheduler.js только UPDATE status='failed'; python-процесс живёт, updated_at не менялся 2+ часа |
| Прочее | ≈22 | 12 % | — |

## 3. Preflight failures (22)

- **81 %** — `Устройство X недоступно по ADB` (9 уникальных девайсов). Физика/сеть/ADB-daemon — вне пайплайна.
- **19 %** — `Ключевые слова не найдены для проекта Волшебная футболка (validator)` — config-issue на стороне validator DB.

## 4. Device toxicity (≥ 2 задачи)

Устройства с 2+ failed per platform:

| device | TT fails | YT fails | IG fails | IG done |
|---|---:|---:|---:|---:|
| RFGYB07Y5TJ | 3 | — | 0 | 2 (!) |
| RFGYB07Y65V | 2 | 2 | — | — |
| RFGYA19BPJL | 2 | — | — | — |
| RF8YA0V57MV | — | 2 | — | — |
| RFGYA19DB8K | 1 | 2 | — | — |
| RF8Y80ZT5JB | — | — | 2 | — |

**Одно устройство `RFGYB07Y5TJ`:** 2/2 ✓ IG, но 3/3 ✗ TikTok. Это значит проблема не только «железо», а «железо × платформа × протокол».

## 5. Protocol breakdown (30 дней)

| protocol_id | name (table) | 30д total | failed | completed |
|---:|---|---:|---:|---:|
| 1 | Instagram базовый | 41 | 18 | 8 (20 %) |
| 2 | TikTok агрессивный | ≈38 | 28 | 0 |
| 3 | YouTube мягкий | ≈37 | 28 | 0 |

**Выводы:**
- Успешен только Instagram basic. Day 10 достигает 20 % IG-задач.
- TT/YT протоколы имеют **нулевую** конверсию в 30-дневной выборке. Падают на day 1-4.

## 6. Qualitative patterns

### Наш auto-retry работает (survived example)

Task 103 (`@slimvi_1`) — **9 error-событий в первые 38 минут** (account-read fails × 5), но **completed через 8.7 дней**. Система автоматически перезапустила задачу → пятая попытка была успешной → нормальный 10-дневный прогрев. Это важно: **наши ошибки частично self-healing**, просто засыпают логи.

### Watchdog — только DB-accountant

```js
// scheduler.js:134-149
UPDATE autowarm_tasks
SET status='failed', events = events || $2::jsonb
WHERE id=$3
```

Никакого `process.kill()`. Сравни с factory_reg_tasks в том же server.js:3547:
```js
const pid = rows[0].pid;
if (pid) { try { process.kill(pid, 'SIGKILL'); } catch(e) {} }
```

**Технический долг:** для farming паттерн с pid-трекингом не внедрён. Образец УЖЕ есть в том же репо.

### `meta.category` пустой во ВСЕХ 178 error-events

| category | platform | count |
|---|---|---:|
| NULL | TikTok | 70 |
| NULL | YouTube | 60 |
| NULL | Instagram | 48 |

Это блокер для любого monitoring (Prometheus/алерты). `publisher.py` уже использует `meta.category` для триажа. warmer.py и account-switch методы — нет.

## 7. Known unknowns (чего не хватает в events)

1. **meta.category** — не заполнено нигде в farming. Фиксится добавлением поля в `log_event` calls в warmer.py.
2. **Причина конкретного account-read fail** — `warmer.py:768-770` логирует только финальное «3 попыток не хватило». Что именно было в ui (empty/ad/splash/wrong-profile) — не записывается.
3. **`pid` колонка** — в autowarm_tasks нет, в factory_reg_tasks есть. Без этого watchdog ≠ killer.
4. **`days_config` JSON-dump в логах** — при fail day=1 не видно, какие шаги из протокола успели/не успели.
5. **Состояние ADB bridge** — для preflight_failed (18/22) «ADB недоступен», но нет детализации (timeout / connection refused / device offline). Это рядом с watchdog-hang по root cause.

## 8. Сигналы для Phase 2/3 (reuse-матрица)

Из baseline уже выкристаллизовались очевидные reuse-кандидаты:

| Кандидат | Источник | Target | Effort |
|---|---|---|---|
| `connect_and_restart_app` pattern (stop_app+start_app+sleep 8s) | `/tmp/auto_public/uploader/base.py:211-231` | warmer.py::verify_and_switch_account pre-step | S |
| pid-column + process.kill watchdog | уже есть в server.js:3547 для factory_reg_tasks | scheduler.js::watchdogStuckTasks | S |
| SoftTimeLimitExceeded pattern (in-process timeout) | `/tmp/autowarm_worker/app/entrypoints/worker.py:119-131` | warmer.py wrapper around Airtest/ADB calls | M |
| Poco instead of XML regex для account-read | `/tmp/auto_public/uploader/base.py:233-258` | warmer.py::get_current_*_account | M-L |
| Daily-protocol декларативный формат | `/tmp/autowarm_worker/app/modules/{tt,yt,ig}/dayN.py` | autowarm_protocols.days_config для TT/YT | L |
| `meta.category` везде в warmer.log_event | наш собственный технический долг | warmer.py | S |

## 9. Подтверждённые гипотезы перед T6/T7 аудитом

- ✅ Downstream-проблемы публикации (camera/editor) **не** являются главной причиной failed farming — у нас upstream блок (account-read) ещё до фитнес-действий.
- ✅ TT/YT протоколы **структурно** не работают, не «просто не повезло» — 0 из ≈75 задач.
- ✅ IG-протокол работает, но нестабилен (20 % success). Главные потери — account-read retry-loop и watchdog hang.
- ✅ `auto_public` почти не автоматизирует account-switch (стабы `return False`). Полезны только инфраструктурные wrapper'ы (restart-app, init-poco, humanize primitives).
- ✅ `autowarm_worker` имеет чистую Celery+daily-module архитектуру, но **не решает** нашу upstream-проблему (они предполагают «1 device = 1 account», пропускают account-verify).

## Next steps (Phase 2)

- T6: Deep-dive в `autowarm_worker/app/modules/humanize_with_coords.py` (635 строк — главный reuse-кандидат), + Celery setup
- T7: Deep-dive в `auto_public/by_images.py` (image-based detection) + `services/llm_manager.py`
- T8: Полное file-to-file mapping
- T9: Reuse matrix с scoring
- T10: Top-3 кандидатов + follow-up /aif-plan команды
