# Plan: Исследование логов фарминга + аудит чужих репо для reuse в autowarm

**Created:** 2026-04-19
**Mode:** Full (research/investigation, без ветки — план только)
**Slug:** `farming-reuse-research`
**Плановый артефакт-итог:** `/home/claude-user/contenthunter/.ai-factory/evidence/farming-reuse-matrix-20260419.md` (reuse-матрица + сырой анализ)
**Репо-объекты исследования:**
- `GenGo2/autowarm_worker` (локальный клон: `/tmp/autowarm_worker`, last commit `3a19703` 2026-04-17)
- `GenGo2/auto_public` (локальный клон: `/tmp/auto_public`, last commit `2aa9b4c` 2026-04-17)
- Наш боевой код: `/root/.openclaw/workspace-genri/autowarm/` (`GenGo2/delivery-contenthunter`)

## Settings

| | |
|---|---|
| Testing | **no** — research-план, продуцирует MD-отчёты, а не код |
| Logging | **standard** — не применимо (нет кодовых задач); при портировании конкретных модулей в отдельных плана-потомках будет переопределено на verbose |
| Docs | **warn-only** — output = evidence MD (не docs/), drift маловероятен |
| Roadmap linkage | skipped — ROADMAP.md в проекте отсутствует |
| Git branch | **нет ветки** — per user, работа только читающая и аналитическая |

## Исходный контекст (уже верифицировано при планировании)

### Farming = `autowarm_tasks` (не `publish_tasks`)
UI раздел `#farming/tasks` читает таблицу `autowarm_tasks` (поля: `id, device_serial, account, project, protocol_id, current_day, status, progress jsonb, started_at, updated_at, log, adb_port, platform, pack_name, resume_at, events jsonb, tokens_used, screen_record_url, preflight_errors jsonb`).

**Важно:** отдельная таблица от `publish_tasks`; нет колонки `created_at` — фильтровать по `COALESCE(started_at, updated_at)`.

### Факт-срез 30 дней (на 2026-04-19)

Распределение статусов:

| status | count | % |
|---|---:|---:|
| failed | 77 | 63 % |
| preflight_failed | 22 | 18 % |
| offline | 8 | 6.5 % |
| completed | **8** | **6.5 %** |
| paused | 7 | 5.7 % |

Completed 8/8 — **все Instagram, все старше 10 дней** (свежайшая 2026-04-08 ivanov_estate1). Последние 11 дней — **0 успехов** ни на одной платформе. Это baseline задачи: фарминг де-факто сломан ~с 2026-04-09.

Топ error-сообщений в failed (30д, только `events[].type='error'`):

| msg | count |
|---|---:|
| Не удалось прочитать аккаунт TikTok после 3 попыток — задача прервана | 32 |
| Не удалось прочитать аккаунт YouTube после 3 попыток — задача прервана | 25 |
| Не удалось прочитать аккаунт Instagram после 3 попыток — задача прервана | 20 |
| Watchdog: зависание 120/187/213/1154 мин | 17 |
| Аккаунт @X не совпадает с активным — задача прервана | ~25 |

**Диагноз first-pass:** ~77/89 error-событий (86 %) — account read failure в `account_switcher.py`-эквиваленте farming-пайплайна, т.е. upstream-этап, до fitness-действий (лайки/подписки/просмотры).

### Архитектура репо (быстрый скан)

**`autowarm_worker`** — Celery-based worker, чистая модульность:
```
app/
├── celery.py              — Celery app + очередь autowarm, soft_time=35m, hard=40m
├── celery_signals.py
├── consts.py
├── db.py                  — SessionMaker
├── entrypoints/
│   ├── worker.py          — run_autowarm(device, day, platform) Celery task
│   └── cmd.py             — CLI-entrypoint (python -m app.entrypoints.cmd --day N --device … --social …)
├── exceptions.py
├── logging_setup.py
├── models.py              — ORM?
├── modules/
│   ├── humanize_with_coords.py  — 635 строк (кандидат #1 на reuse)
│   ├── ig/{day1,day2,day3,day4}.py
│   ├── tiktok/{day1…day4,day4_6,publish_video}.py  (138 стр. publish_video)
│   └── yt/{day1…day4}.py
├── repositories/
│   ├── autowarm_tasks.py  — DAO
│   └── raspberry.py       — device info (host, adb_port)
└── services/
    └── subject_service.py
```
Технологии: **Celery + Redis/broker URL**, Poetry, Docker, subprocess-based command dispatch (`cmd.py` запускается как отдельный процесс на устройство), `billiard.SoftTimeLimitExceeded` timeout handling.

**`auto_public`** — тот же стек (видно по `celery_signals.py`), image-based UI через Airtest:
```
├── main.py                — CLI entry (173 строки)
├── remote_worker.py       — 2756 байт — видимо отдельный запускатор
├── celery_signals.py
├── by_images.py           — 174 строки, image-based tap/find (cv)
├── uploader/
│   ├── base.py            — 515 строк (общий uploader)
│   ├── instagram.py       — 139
│   ├── tiktok.py          — 95
│   ├── vk.py              — 83
│   └── youtube.py         — 84
├── llm_providers/
│   ├── anthropic.py
│   └── open_router.py
├── services/
│   └── llm_manager.py
├── scheduler/
│   └── scheduler_autopublic.py
├── utils/
│   ├── database.py
│   ├── models.py
│   └── draw.py
├── elems/                 — element screenshots?
└── images/                — ui reference images
```
Ключевое отличие: **image-based детекция** (cv2/Airtest templates) вместо нашего XML-dump + content-desc подхода. Другой trade-off по устойчивости к IG/TT-редизайнам.

## Задачи

Три фазы: лог-анализ (baseline), аудит репо (кандидаты), reuse-матрица (решение).

- [x] T1 — SQL-анализ failed/preflight_failed farming-задач за 30 дней (events aggregation)
- [x] T2 — Deep-dive: account-read failure mode (77 кейсов, 86 % от всех ошибок)
- [x] T3 — Deep-dive: watchdog/hang кластер (17+ событий, 120→1154 мин timeout)
- [x] T4 — Completed-8 audit: общие признаки 8 успешных задач
- [x] T5 — Baseline-evidence MD (T1-T4 consolidated)
- [x] T6 — Структурный аудит `autowarm_worker` + reuse-candidates list
- [x] T7 — Структурный аудит `auto_public` + reuse-candidates list
- [x] T8 — File-to-file mapping: чужой модуль ↔ наш файл в `/root/.openclaw/workspace-genri/autowarm/`
- [x] T9 — Reuse-matrix (порт / адапт / отклонить) с gain×risk×effort оценкой
- [x] T10 — Top-3 prioritized candidates + rough sizing для follow-up планов

## Phase 1: Baseline log analysis (T1-T5)

### T1 — SQL-свод по failed/preflight_failed 30д

**Что сделать:**
1. Общая таблица по msg (уже получено при планировании — см. «Топ error-сообщений»). Сохранить полный TOP-30 + count+percentage.
2. Разбивка по `platform × meta.category` (если присутствует в `events[].meta.category`):
   ```sql
   SELECT ev->'meta'->>'category' AS cat, platform, COUNT(*)
   FROM autowarm_tasks t, LATERAL jsonb_array_elements(events) ev
   WHERE COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
     AND ev->>'type' = 'error'
   GROUP BY cat, platform
   ORDER BY COUNT(*) DESC
   LIMIT 30;
   ```
3. Разбивка по `device_serial × platform` — есть ли «токсичные» устройства?
4. Разбивка `protocol_id × current_day × status` — падают на первом дне или позже?
5. `preflight_errors` jsonb: что триггерит preflight_failed (22 случая).

**DB подключение:** `PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw`

**Файл-артефакт (создаётся):** `/home/claude-user/contenthunter/.ai-factory/evidence/farming-baseline-sql-20260419.md` — чистые SQL + raw-результаты таблицами.

### T2 — Account-read failure mode deep-dive

**Что сделать:**
1. Выбрать 5 репрезентативных failed-задач с msg=«Не удалось прочитать аккаунт X после 3 попыток»:
   ```sql
   SELECT id, device_serial, account, platform, pack_name, started_at, updated_at, events, log
   FROM autowarm_tasks
   WHERE status='failed'
     AND events::text LIKE '%не удалось прочитать аккаунт%'
     AND COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
   ORDER BY RANDOM() LIMIT 5;
   ```
2. По каждой: прочитать `log` (полный text-лог) и `events` (jsonb-timeline). Вынуть:
   - На каком шаге упало (заход в профиль / swipe-меню / чтение username)
   - Какой exact anti-marker или timeout сработал
   - Связано ли с app-version (из log, если есть)
3. Найти в `/root/.openclaw/workspace-genri/autowarm/` соответствующий код:
   - Grep по частям msg («прочитать аккаунт», «после 3 попыток»)
   - Определить модуль: `account_switcher.py`? `warmer.py`? `account_revision.py`?
4. Сравнить с тем, как account-read сделан в `autowarm_worker/app/modules/*/day1.py` (первый день обычно содержит login/verify) и `auto_public/uploader/base.py`.

**Артефакт:** раздел в evidence-MD с гипотезой «почему ломается именно этот этап + что чужие репо делают иначе».

### T3 — Watchdog / hang deep-dive

**Что сделать:**
1. Найти 17+ задач с msg LIKE 'Watchdog: зависание%' — на каком шаге задача висела, какой последний `events[].step/category` до киллинга.
2. Коррелировать с `tests/test_watchdog_timer.py` (есть в нашем репо) — уточнить настройку таймаута в нашем коде.
3. Сравнить с `autowarm_worker/app/entrypoints/worker.py`:
   - `soft_time_limit=60*40`, `time_limit=60*45` (Celery)
   - `process.wait(timeout=60*40)` + subprocess.kill на timeout
   - handlers: `SoftTimeLimitExceeded` → kill process (return -2)
4. Оценить, даёт ли Celery-подход более надёжный watchdog, чем наш (какой у нас механизм — pm2 level? inline timer?).

### T4 — Completed-8 audit

**Что сделать:**
Для 8 успешных (все IG, 2026-04-02…2026-04-08):
```sql
SELECT id, device_serial, account, pack_name, protocol_id, current_day,
       progress, tokens_used, screen_record_url, started_at, updated_at,
       jsonb_array_length(events) AS n_events
FROM autowarm_tasks
WHERE status='completed'
ORDER BY updated_at DESC LIMIT 10;
```
Вынести:
- Общий protocol_id / pack_name / current_day
- Какое устройство + была ли история успехов на нём
- Токены (стоимость)
- Длительность (updated_at - started_at)
- Есть ли `screen_record_url` (для последующего просмотра)

Гипотезы: какой общий knob отличает их от 77 failed.

### T5 — Consolidated baseline MD

Собрать T1-T4 в единый `.ai-factory/evidence/farming-baseline-20260419.md`:
- TL;DR на 5-10 строк (3 ключевых класса фейлов + их доли)
- Квантитативные таблицы (T1)
- Качественные разборы (T2, T3, T4) с цитатами из логов
- Список «известных неизвестных» (чего в events не хватает)

## Phase 2: Repo audit (T6-T8)

### T6 — Структурный аудит `autowarm_worker`

**Что сделать:**
1. **Entry points & orchestration:**
   - `app/celery.py` + `app/entrypoints/worker.py` + `app/entrypoints/cmd.py` — разобрать цепочку
   - `start_device_workers.sh` — шаблон spawn-а воркеров per-device
   - `celery_signals.py` — какие сигналы слушает
2. **Daily modules** (`app/modules/{ig,tiktok,yt}/dayN.py`):
   - Открыть day1-day4 каждой платформы (всего 12 файлов, маленькие — day1.py по 22 строки для IG/YT)
   - Извлечь: какие действия делаются на каждый день, как оформлен rate-limit/humanization hook
   - Для TT: `day4_6.py` (переход в более активный режим?), `publish_video.py` (138 строк)
3. **humanize_with_coords.py (635 строк)** — главный кандидат на reuse:
   - Что именно делает (скроллы/тапы/паузы с рандомизацией?)
   - Какие API Airtest использует
   - Можно ли выделить чистую функцию-генератор координат без Airtest-зависимости
4. **Repositories + DB model:**
   - `repositories/autowarm_tasks.py` — DAO API (сравнить с нашим publisher.py inline SQL)
   - `repositories/raspberry.py` — device registry (host/adb_port per device)
5. **Exceptions + logging:**
   - `app/exceptions.py` — таксономия ошибок
   - `app/logging_setup.py` — формат логов, structured?

**Артефакт:** раздел в reuse-matrix с list-of-files и оценкой «size» (строки) + «fit» (что из стека совпадает с нашим).

### T7 — Структурный аудит `auto_public`

**Что сделать:**
1. **Entry:** `main.py` (173 стр.) + `remote_worker.py` (~65 стр.) + `scheduler/scheduler_autopublic.py`
2. **by_images.py (174 стр.)** — image-based UI detection:
   - Какие примитивы (tap_by_image, wait_for_image, …?)
   - Использует cv2/Airtest `Template`?
   - Что в `images/` и `elems/` — предзаписанные скриншоты элементов
   - **Сравнить** с нашим `_tap_element` / `dump_ui` / XML-based подходом
3. **uploader/** (515 + 139 + 95 + 83 + 84 = 916 строк):
   - `base.py` — общий flow (open app → pick media → caption → publish → verify)
   - Платформенные overrides — что именно переопределяется
   - Сравнить с нашим `publisher.py` (352 KB, 5546 строк) — какие эвристики у них простые/быстрые
4. **LLM-интеграция:**
   - `llm_providers/anthropic.py`, `open_router.py`
   - `services/llm_manager.py`
   - Для чего применяется LLM в фарминге/публишинге (генерация caption? классификация экрана?)
5. **utils/database.py, utils/models.py** — ORM/DAO pattern

**Артефакт:** аналогично T6.

### T8 — File-to-file mapping

Построить таблицу (в reuse-matrix MD):

| Чужой модуль | Наш аналог (/root/…/autowarm/) | Наша LOC | Их LOC | Статус |
|---|---|---:|---:|---|
| autowarm_worker/app/celery.py + entrypoints/worker.py | pm2 service + `server.js` + scheduler | ? | ~180 | альтернативная архитектура |
| autowarm_worker/app/modules/humanize_with_coords.py | (отсутствует / разрозненно в publisher.py) | ? | 635 | **reuse-ready** |
| autowarm_worker/app/modules/ig/dayN.py | autowarm_protocols table + warmer.py | ? | ~22-60 | альтернативная декларативность |
| auto_public/by_images.py | dump_ui + content-desc matching в publisher.py | ~100? | 174 | **альтернативный подход** |
| auto_public/uploader/base.py | publisher.py (5546 стр.) | 5546 | 515 | их проще — смотреть как decomposed |
| auto_public/uploader/instagram.py | publisher.py::publish_instagram_reel | ~500? | 139 | сравнение эвристик |
| auto_public/services/llm_manager.py | (отсутствует) | 0 | ? | **новая фича — интересно** |
| autowarm_worker/app/repositories/ | inline SQL в publisher.py/account_switcher.py | — | ~80 | **рефактор-кандидат** |

**Команды для LOC нашей стороны:**
```
wc -l /root/.openclaw/workspace-genri/autowarm/publisher.py
wc -l /root/.openclaw/workspace-genri/autowarm/account_switcher.py
wc -l /root/.openclaw/workspace-genri/autowarm/warmer.py
wc -l /root/.openclaw/workspace-genri/autowarm/account_revision.py
grep -c "def " /root/.openclaw/workspace-genri/autowarm/publisher.py
```

## Phase 3: Reuse matrix (T9-T10)

### T9 — Reuse-matrix с оценкой gain × risk × effort

**Формат:**

| Кандидат | Что портируем | Gain | Risk | Effort | Связь с baseline-фейлами |
|---|---|---|---|---|---|
| `humanize_with_coords.py` | screen-independent humanize helpers | high | low | S (1-2 дня) | может снизить anti-bot detection = часть watchdog-зависаний |
| `by_images.py` image-based fallback | image-детектор экрана как 3-й источник (после XML dump + content-desc) | med-high | med (cv2 deps) | M (3-5 дней) | может помочь на экранах с динамичной вёрсткой (IG highlights empty-state) |
| `llm_manager.py` + `anthropic.py` | LLM-классификатор экрана при unknown-state | med | med | M | может ускорить recovery от unknown-screen |
| `repositories/autowarm_tasks.py` DAO pattern | выделить DAO из publisher.py | low-med | low | M | рефактор, не фикс |
| `modules/{ig,tiktok,yt}/dayN.py` | сравнить декларативный day-based протокол с нашим autowarm_protocols table | med | low | S (paper-only исследование) | ортогонально |
| `entrypoints/worker.py` Celery + subprocess | альтернатива pm2 scheduler | low | high (инфра-миграция) | L | не трогать пока |

**Scoring:** Каждому — финальный `score = (gain × fit) / (risk × effort)`. Cut-off по top-3.

### T10 — Top-3 кандидатов + rough sizing

Для каждого из top-3 (ориентировочно: humanize_with_coords, by_images, llm_manager):

- Какие файлы создаются/меняются в нашем репо
- Дифф-scope (примерный список функций/классов)
- Тесты, которые нужно добавить
- Интеграционная точка (где в `publisher.py` / `warmer.py` / `account_switcher.py` вызов)
- Метрики успеха (какие event.category должны пропасть / снизиться)
- Rollback-стратегия (feature-flag?)

**Вывод T10:** готовый список follow-up /aif-plan команд, например:
```
/aif-plan full "Порт humanize_with_coords.py из autowarm_worker в autowarm (helper-модуль + unit-тесты)"
/aif-plan full "Image-based fallback detector (by_images) для IG unknown-screen recovery"
/aif-plan full "LLM-классификатор screen-state для recovery в publisher.py"
```

**Итоговый артефакт:** `/home/claude-user/contenthunter/.ai-factory/evidence/farming-reuse-matrix-20260419.md` со структурой:
```
# Farming reuse research — 2026-04-19
## TL;DR (3 key takeaways)
## Baseline (from T1-T5)
## Repo audit (T6-T8)
## Reuse matrix (T9)
## Top-3 candidates with sizing (T10)
## Next actions (follow-up /aif-plan commands)
```

## Commit plan

Research-план — выход в `.ai-factory/evidence/`. Коммиты только в `contenthunter` (текущий репо), НЕ в `GenGo2/delivery-contenthunter`.

**Checkpoint 1 — после T5 (baseline complete):**
```
docs(evidence): farming tasks baseline analysis 30d (8 ok / 77 fail / 22 preflight)
```

**Checkpoint 2 — после T8 (audits complete):**
```
docs(evidence): autowarm_worker + auto_public structural audit for reuse
```

**Checkpoint 3 — после T10 (final):**
```
docs(evidence): farming reuse matrix + top-3 candidates for port
```

## Guardrails / чего в этом плане НЕТ

- **Нет изменений** в `/root/.openclaw/workspace-genri/autowarm/` — только read-only анализ
- **Нет pm2 restart / деплоя** — всё чтение
- **Нет коммитов** в `delivery-contenthunter` — чужой код остаётся в `/tmp/`
- **Нет pilot-патча** — по выбору пользователя в opts ("Анализ + Аудит + Reuse-матрица" без pilot)
- **Нет клонирования через gh** — оба репо приватные, локальные копии в `/tmp/` (sufficient); при rerun можно обновить `git -C /tmp/<repo> pull` если нужны свежие коммиты
- **Не трогаем `publish_tasks`** — здесь работаем только с `autowarm_tasks`

## Риски / что может сбить с курса

1. **Локальные клоны в `/tmp/` могут быть зачищены** при ребуте. Перед T6/T7 снять `git log --oneline -1` обоих + `du -sh /tmp/auto*`. Если пропали — попросить у пользователя re-clone.
2. **Memory lag (feedback_plan_staleness.md):** наша /root/.../autowarm/ живёт быстро. Перед T8 выполнить `git -C /root/.openclaw/workspace-genri/autowarm log --oneline -20` чтобы не сравнивать с устаревшим снимком.
3. **Объём publisher.py (5546 строк):** не читать целиком — по grep/landmark (из memory: :41, :2050, :2327, :2377, :5307, :5457).
4. **events jsonb-aggregation**: `jsonb_array_elements` только в `LATERAL` (не в WHERE) — напоминание себе.

## Next step

После review этого плана → `/aif-implement` выполнит T1-T10 последовательно, с commit-checkpoint'ами после T5 и T8. Финал — `.ai-factory/evidence/farming-reuse-matrix-20260419.md` + список готовых follow-up `/aif-plan` команд для портирования top-3 кандидатов.
