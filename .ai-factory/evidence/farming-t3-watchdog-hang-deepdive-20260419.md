# T3 — Deep-dive: watchdog/hang кластер (19 случаев, ≈11% error-событий)

## Наш watchdog

**Файл:** `/root/.openclaw/workspace-genri/autowarm/scheduler.js` :118-154

```js
async function watchdogStuckTasks() {
  const TWO_HOURS_AGO = new Date(Date.now() - 2 * 60 * 60 * 1000);
  const { rows } = await pool.query(`
    SELECT id, account, platform, device_serial, updated_at
    FROM autowarm_tasks
    WHERE status = 'running' AND updated_at < $1
  `, [TWO_HOURS_AGO]);

  for (const task of rows) {
    const stuckMin = Math.round((Date.now() - new Date(task.updated_at).getTime()) / 60000);
    await pool.query(`
      UPDATE autowarm_tasks
      SET status = 'failed', updated_at = NOW(),
          log = log || $1,
          events = events || $2::jsonb
      WHERE id = $3
    `, [
      `\n[WATCHDOG] Задача зависла в running ${stuckMin} мин — принудительно failed`,
      JSON.stringify([{
        ts: new Date().toTimeString().slice(0,8),
        type: 'error',
        msg: `Watchdog: зависание ${stuckMin} мин — принудительно failed`
      }]),
      task.id
    ]);
  }
}
// tick() вызывает watchdogStuckTasks() в общем цикле (scheduler.js:162)
```

**Триггер:** `status='running' AND updated_at < NOW() - 2 hours`.
**Действие:** ТОЛЬКО UPDATE в DB. **Python-процесс не убивается.**

## Распределение зависаний (30д, 19 событий)

| Bucket | Count |
|---|---:|
| 120-129 мин (минимальный порог — только что пересекли 2ч) | 10 |
| 150-199 мин | 3 |
| 200-299 мин | 4 |
| ~1000-1199 мин (≈20ч) | 4 |
| 2500+ мин (1.5+ дня) | 3 |

**Две принципиально разные когорты:**
- **Короткие зависания 120-300 мин (17 случаев):** Python-процесс реально висит на ADB/network call. Watchdog обнаруживает при следующем tick'е (~каждые 5 мин по scheduler.js:163+), флипает DB, Python остаётся zombie.
- **Длинные зависания 1000+ мин (7 случаев):** либо весь scheduler.js / pm2 был down несколько часов, либо задача была забыта при миграции / pm2 restart / crash. Самый длинный: **2710 мин = 45 часов** (task 7, `@louna_unpack`, IG, day 1, n_events=4 — задача стартовала, залогировала 4 события, молчала ~45ч до watchdog).

## Примеры

| task | platform | account | device | day | stuck мин | n_events | log байт |
|---:|---|---|---|---:|---:|---:|---:|
| 104 | Instagram | relisme_art | RFGYB07Y65V | 1 | 120 | 50 | 100 |
| 102 | Instagram | self_mindful_ | RFGYB07Y5SA | 1 | 120 | 51 | 100 |
| 108 | YouTube | self_mindful | RFGYB07Y5SA | 1 | 120 | 10 | 100 |
| 110 | YouTube | WowRelisme | RFGYB07Y65V | 1 | 121 | 10 | 100 |
| 56 | YouTube | EliteCornersSpb | RF8Y80ZT5JB | 1 | 1154 | 18 | 101 |
| 7 | Instagram | louna_unpack | RFGYA19BD6M | 1 | 2710 | 4 | 101 |
| 12 | TikTok | ivanov_estate | RFGYB07Y5TJ | 1 | 2534 | 6 | 101 |

**Паттерн short-hangs:** 50 events, но log только 100 байт. Значит события логируются в DB нормально, а log-строка (с переносами) — не заполняется после старта. Python жив(был), но либо намертво застрял в блокирующем ADB-вызове, либо в long sleep, и по какой-то причине не апдейтил `updated_at`.

**Два устройства `RFGYB07Y5SA` и `RFGYB07Y65V` — 4 hang'а за один день:** скорее всего в тот день ADB bridge был нестабилен / адб daemon умер / сеть до эмулятор-хоста 82.115.54.26 пропала.

## Сравнение с чужими репо

### `autowarm_worker` (Celery + billiard)

**Файл:** `app/celery.py`, `app/entrypoints/worker.py`

**Два уровня timeout (billiard.exceptions.SoftTimeLimitExceeded):**

```python
# app/celery.py
celery_app.conf.update(
    task_time_limit=60 * 40,        # HARD limit — Celery SIGKILL воркера на 40 мин
    task_soft_time_limit=60 * 35,   # SOFT limit — exception внутри воркера на 35 мин
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_pool="prefork",
    worker_max_tasks_per_child=2,          # рестарт воркера каждые 2 задачи
    worker_max_memory_per_child=350,       # рестарт при >350MB
    broker_transport_options={"visibility_timeout": 60 * 60},
)
```

**В worker.py task:**
```python
@celery_app.task(name="run_autowarm", acks_late=True,
                 soft_time_limit=60*40, time_limit=60*45)
def run_autowarm(device_number, day_input, platform):
    process = subprocess.Popen(cmd, ...)
    for line in process.stdout:
        logger.info(line, extra={"source": "script_stdout", ...})
    try:
        process.wait(timeout=60 * 40)
    except subprocess.TimeoutExpired:
        process.kill()
        return -1
    except SoftTimeLimitExceeded:
        logger.error("SoftTimeLimitExceeded — убиваем Airtest")
        process.kill()
        return -2
```

**Что они делают правильно (в нашей терминологии):**
1. **In-process awareness:** код внутри воркера получает `SoftTimeLimitExceeded` — может очистить ресурсы, попытаться отключить ADB, записать partial result.
2. **Real kill:** при hard-timeout Celery посылает SIGKILL воркеру, который в свою очередь process.kill() на subprocess → Airtest/adb завершается.
3. **Worker recycling:** `worker_max_tasks_per_child=2` + `worker_max_memory_per_child=350` — воркер перезапускается каждые 2 задачи или при росте памяти >350MB → препятствует накоплению утечек / висящих ADB-сессий.
4. **Structured logs:** каждая строка stdout субпроцесса логируется с `extra={source, device, day, platform, component}` — облегчает триаж.

### `auto_public`

Использует тот же Celery pattern (видно `celery_signals.py` рядом с `main.py`) плюс Airtest-native timeouts на уровне `stop_app/start_app`. Меньше выражено чем в autowarm_worker.

## Сравнение

| Аспект | Наш scheduler.js watchdog | autowarm_worker Celery watchdog |
|---|---|---|
| Порог | 2 часа fixed | 35 min soft / 40 min hard |
| Уведомление Python-процесса | **нет** | SoftTimeLimitExceeded exception in-process |
| Hard kill Python | **нет** (только DB UPDATE) | Celery SIGKILL + subprocess.kill() |
| Worker recycling | **нет** | каждые 2 задачи / 350MB |
| Structured log | plain text appended to `log` column | `extra=` dict на каждой записи |
| Overhead инфраструктуры | 0 (Node + Postgres) | Redis + Celery + beat + workers |

## Диагноз

Наш watchdog — **DB-accountant, не executor**. Он только «помечает» зависшую задачу в DB; реальный Python-процесс может:

- Всё ещё держать ADB-сессию и мешать следующему запуску на том же device_serial (pm2 не в курсе).
- Накапливать память (IG app restart + uiautomator dump repeatedly).
- Перезаписать статус обратно на running, если неожиданно оттаял (редко, но возможно → race condition с watchdog UPDATE).

Последствия по логам:
- 10 из 19 зависаний — ровно 120-129 мин, т.е. на самом ближайшем тике после превышения 2-часового порога. Это **системный минимум**, который нельзя снизить без более агрессивного watchdog'а.
- 3 из 19 — >1000 мин: признак того что scheduler сам был недоступен (перезапуск pm2 / crash).

## Reuse-кандидаты на hang-cluster

| Идея | Откуда | Gain | Effort |
|---|---|---|---|
| **In-process timeout через SIGTERM + threading.Event** (эквивалент SoftTimeLimitExceeded) в warmer.py | autowarm_worker pattern, реализуемо без Celery | high — Python очищает ADB + отмечает cleanup | M (2-3 дня) |
| **Сокращение threshold до 35-40 мин + добавление os.kill по pid** в watchdogStuckTasks | adapted from autowarm_worker | high | S (1 день) |
| **`pid` column в autowarm_tasks + process.kill(pid, 'SIGKILL')** (как уже сделано в factory_reg_tasks — server.js:3547-3549) | inspired by existing pattern в этом же проекте | high | S (1 день — column + UPDATE) |
| **Worker memory/task recycling** — pm2 restart policy per 2 задачи или >350MB | autowarm_worker Celery settings → pm2 equivalent | medium | S (config) |
| **meta.category на watchdog-событии** (сейчас пусто) | наш собственный баг, связан с T1 finding | medium | S |

**TOP приоритет:** `pid` column в `autowarm_tasks` + реальный `process.kill()` в watchdog (паттерн УЖЕ есть в `server.js:3547-3549` для factory_reg_tasks — переиспользовать тот же подход). Это **локальный фикс без чужих зависимостей**, дающий максимум эффекта.

**Вторичный:** сокращение порога до 40-45 мин. Текущие 2 часа — наследие публикационного кода (где действия длинные), для фарминга этот порог избыточен.
