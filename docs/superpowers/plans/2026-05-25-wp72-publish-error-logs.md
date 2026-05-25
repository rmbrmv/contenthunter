# WP #72 — Триаж логов выкладки (Эль-косметик + Онлайн-школа) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Разобрать причины фейлов выкладки у двух клиентов, разложить по корзинам (незакрытый код-баг / уже починено / аккаунт-устройство / не баг), отдельно выяснить причину остановки Онлайн-школы, и оформить результат как отчёт в #72 + дочерние WP — без правок кода.

**Architecture:** Чистый анализ данных Postgres (`publish_queue` + `publish_tasks.events`) с точечным vision-разбором видеозаписей. Артефакты: evidence-файл (технический) + комментарий в OpenProject (для Ани) + дочерние WP. Дисциплина — «evidence before claims»: каждый вывод подтверждён запросом, контроль сумм обязателен.

**Tech Stack:** PostgreSQL (jsonb `events`), `psql`, ffmpeg (кадры из screencast), OpenProject REST API v3, codex review, git.

**Спека:** `docs/superpowers/specs/2026-05-25-wp72-publish-error-logs-design.md`

**Соединение с БД (для всех SQL-шагов):** пароль в файл НЕ коммитим — берём openclaw-креды из
памяти проекта / локального secrets и экспортируем в своей сессии:
```bash
export PGPASSWORD='<пароль openclaw — из памяти проекта, не из репозитория>'
PSQL="psql -h localhost -U openclaw -d openclaw"
```
**Окна (per-client):** Эль-косметик (82): `created_at >= '2026-05-15'`. Онлайн-школа (84): `created_at >= '2026-04-15' AND created_at < '2026-05-07'`.

**NOISE-BLOCKLIST (единый источник истины):** стартово — `adb_devices_unreachable`, `process_interrupted`, `screencast_stop_failed`. **Финализируется в Task 1 Step 2.** Один и тот же список фигурирует в трёх запросах (Task 2, Task 4, Task 6) — и в `NOT IN (...)` внутри CTE `cause`, и во вложенных `NULLIF(...)` fallback'а по `error_code`. **При добавлении новой шумовой категории в Task 1 — обновить ВСЕ три запроса в обоих местах,** иначе тоталы и проверка рецидивов разойдутся между шагами.

---

## Task 1: Базовая линия датасета + проверка формы events

**Files:**
- Нет (разведочные запросы; результаты пойдут в evidence-файл в Task 8).

- [ ] **Step 1: Зафиксировать контрольные тоталы по статусам в окнах**

```bash
$PSQL -tA -c "
SELECT pq.project_id,
  count(*) FILTER (WHERE status='failed')          AS failed,
  count(*) FILTER (WHERE status='done')            AS done,
  count(*) FILTER (WHERE status='cancelled')       AS cancelled,
  count(*) FILTER (WHERE status='skipped')         AS skipped,
  count(*) FILTER (WHERE status='past_slot_dropped') AS past_slot,
  count(*) FILTER (WHERE status='pending')         AS pending,
  count(*) AS total
FROM publish_queue pq
WHERE (pq.project_id=82 AND pq.created_at>='2026-05-15')
   OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07')
GROUP BY 1 ORDER BY 1;"
```
Записать числа `failed` по каждому клиенту — это **контрольная сумма** для Task 2.

- [ ] **Step 2: Подтвердить, что у failed-строк причинная категория достаётся из events**

```bash
$PSQL -tA -c "
SELECT e->'meta'->>'category' AS cat, count(DISTINCT pt.id) AS n_tasks
FROM publish_queue pq
LEFT JOIN publish_tasks pt ON pt.id=pq.publish_task_id, jsonb_array_elements(COALESCE(pt.events,'[]'::jsonb)) e
WHERE ((pq.project_id=82 AND pq.created_at>='2026-05-15')
    OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07'))
  AND pq.status='failed' AND e->>'type'='error' AND e->'meta'->>'category' IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;"
```
**Цель шага:** финализировать noise-blocklist. Стартовый список (из спеки): `adb_devices_unreachable`, `process_interrupted`, `screencast_stop_failed`. Если в выводе всплывут другие явно не-причинные artifact/upload/cleanup категории — добавить их в список и зафиксировать в evidence-файле с обоснованием.

- [ ] **Step 3: Verify** — выписать (a) failed-тоталы на клиента, (b) финальный noise-blocklist. Без этих двух чисел/списка Task 2 не запускать.

---

## Task 2: Классификация по финальной причинной категории + контроль сумм

**Files:**
- Нет (запрос; результат → evidence Task 8).

- [ ] **Step 1: Прогнать классификацию (последняя причинная категория, исключая шум)**

```bash
$PSQL -tA -c "
WITH win AS (
  SELECT pq.id qid, pq.project_id, pq.status, pq.skip_reason,
         COALESCE(pt.platform, pq.platform) platform, pt.events, pt.error_code, pt.id tid
  FROM publish_queue pq LEFT JOIN publish_tasks pt ON pt.id=pq.publish_task_id
  WHERE ((pq.project_id=82 AND pq.created_at>='2026-05-15')
      OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07'))
    AND pq.status='failed'
),
cause AS (
  SELECT w.qid,
    (SELECT e->'meta'->>'category'
       FROM jsonb_array_elements(COALESCE(w.events,'[]'::jsonb)) WITH ORDINALITY t(e,ord)
      WHERE e->>'type'='error' AND e->'meta'->>'category' IS NOT NULL
        AND e->'meta'->>'category' NOT IN ('adb_devices_unreachable','process_interrupted','screencast_stop_failed')
      ORDER BY ord DESC LIMIT 1) final_cat
  FROM win w
)
SELECT w.project_id, w.platform,
       COALESCE(c.final_cat, NULLIF(NULLIF(NULLIF(NULLIF(w.error_code,''),'adb_devices_unreachable'),'process_interrupted'),'screencast_stop_failed'), 'uncategorized') category,
       count(*)
FROM win w LEFT JOIN cause c ON c.qid=w.qid
GROUP BY 1,2,3 ORDER BY 1,4 DESC;"
```
> При исполнении: финальный noise-blocklist из Task 1 Step 2 должен быть един в ОБОИХ местах —
> и в `NOT IN (...)` внутри `cause`, и во вложенных `NULLIF(...)` fallback'а по `error_code`
> (иначе шумовой код вернётся через fallback и исказит тоталы).

- [ ] **Step 2: Контроль сумм (ОБЯЗАТЕЛЬНО)**

```bash
$PSQL -tA -c "
WITH win AS (
  SELECT pq.id qid, pq.project_id FROM publish_queue pq
  WHERE ((pq.project_id=82 AND pq.created_at>='2026-05-15')
      OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07'))
    AND pq.status='failed')
SELECT project_id, count(*) FROM win GROUP BY 1 ORDER BY 1;"
```
Expected: суммы из Task 2 Step 1 (по каждому project_id) **точно равны** этим числам и числам failed из Task 1 Step 1. Если не сходится — найти потерянные строки (NULL-task, пустые events) и устранить расхождение перед продолжением.

- [ ] **Step 3: Verify** — расхождение = 0. Зафиксировать таблицу «клиент × платформа × категория».

---

## Task 3: Срезы по аккаунтам, устройствам, дням

**Files:**
- Нет (запросы; результат → evidence Task 8).

- [ ] **Step 1: По аккаунтам (ищем концентрацию на «плохих» аккаунтах)**

```bash
$PSQL -tA -c "
SELECT pq.project_id, pt.account,
  count(*) FILTER (WHERE pq.status='failed') failed,
  count(*) FILTER (WHERE pq.status='done')   done
FROM publish_queue pq LEFT JOIN publish_tasks pt ON pt.id=pq.publish_task_id
WHERE (pq.project_id=82 AND pq.created_at>='2026-05-15')
   OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07')
GROUP BY 1,2 ORDER BY 1, failed DESC;"
```

- [ ] **Step 2: По устройствам**

```bash
$PSQL -tA -c "
SELECT pq.project_id, pt.raspberry, pt.device_serial,
  count(*) FILTER (WHERE pq.status='failed') failed,
  count(*) FILTER (WHERE pq.status='done')   done
FROM publish_queue pq LEFT JOIN publish_tasks pt ON pt.id=pq.publish_task_id
WHERE (pq.project_id=82 AND pq.created_at>='2026-05-15')
   OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07')
GROUP BY 1,2,3 ORDER BY 1, failed DESC;"
```

- [ ] **Step 3: По дням (динамика)**

```bash
$PSQL -tA -c "
SELECT pq.project_id, pq.created_at::date d, pq.status, count(*)
FROM publish_queue pq
WHERE (pq.project_id=82 AND pq.created_at>='2026-05-15')
   OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07')
GROUP BY 1,2,3 ORDER BY 1,2;"
```

- [ ] **Step 4: Verify** — отметить аккаунты/устройства с долей фейлов >50% при ≥4 попытках (кандидаты в «аккаунт/устройство»-корзину). Помнить про поправку на выходные 23–24.05 (низкий трафик — слабый сигнал).

---

## Task 4: Сверка с релизами 18–22.05 (починено vs рецидив)

**Files:**
- Read-only `git log` в `/root/.openclaw/workspace-genri/autowarm` (prod-чекаут autowarm).

- [ ] **Step 1: Подтвердить даты фиксов по релевантным категориям**

Для категорий, всплывших в Task 2 и присутствующих в таблице релизов спеки (§4.3), подтвердить дату коммита/деплоя:
```bash
git -C /root/.openclaw/workspace-genri/autowarm log --since=2026-05-17 --until=2026-05-23 \
  --pretty='%h %ad %s' --date=short | grep -iE 'ig_|yt_|tt_|switch|picker|editor|launch|confirmation|modal'
```
Сопоставить каждую найденную в данных категорию с датой её фикса.

- [ ] **Step 2: Разметить каждую failed-строку релевантных категорий: до/после фикса**

Используем ту же финальную-категорию логику, что в Task 2 (НЕ сырой `error_code` — иначе рецидивы,
видимые только в `events.meta.category`, недосчитаются):
```bash
$PSQL -tA -c "
WITH win AS (
  SELECT pq.id qid, pq.project_id, pq.created_at, pt.events, pt.error_code
  FROM publish_queue pq LEFT JOIN publish_tasks pt ON pt.id=pq.publish_task_id
  WHERE ((pq.project_id=82 AND pq.created_at>='2026-05-15')
      OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07'))
    AND pq.status='failed'),
cause AS (
  SELECT w.qid,
    (SELECT e->'meta'->>'category'
       FROM jsonb_array_elements(COALESCE(w.events,'[]'::jsonb)) WITH ORDINALITY t(e,ord)
      WHERE e->>'type'='error' AND e->'meta'->>'category' IS NOT NULL
        AND e->'meta'->>'category' NOT IN ('adb_devices_unreachable','process_interrupted','screencast_stop_failed')
      ORDER BY ord DESC LIMIT 1) final_cat
  FROM win w)
SELECT w.project_id, w.created_at::date, count(*)
FROM win w LEFT JOIN cause c ON c.qid=w.qid
WHERE COALESCE(c.final_cat, NULLIF(NULLIF(NULLIF(NULLIF(w.error_code,''),'adb_devices_unreachable'),'process_interrupted'),'screencast_stop_failed'), 'uncategorized')
      = 'yt_editor_upload_timeout'   -- подставить проверяемую категорию из Task 2; повторить по списку
GROUP BY 1,2 ORDER BY 1,2;"
```

- [ ] **Step 3: Verify** — для каждой категории вывод: «закрыто (рецидивов после фикса нет)» / «рецидив (есть будние фейлы после фикса)» / «нельзя подтвердить (только школа, трафика после фикса нет)». Зафиксировать.

---

## Task 5: Расследование остановки Онлайн-школы (06.05)

**Files:**
- Нет (запросы + проверка флагов; результат → отдельный блок отчёта).

- [ ] **Step 1: Подтвердить дату последней активности и отсутствие более новых строк**

```bash
$PSQL -tA -c "
SELECT max(created_at) last_created, max(updated_at) last_updated
FROM publish_queue WHERE project_id=84;"
```
Expected: last_created ≈ 2026-05-06.

- [ ] **Step 2: Проверить, не на стороне ли «наполнителя» очереди (есть ли намерение выкладывать после 06.05)**

```bash
$PSQL -tA -c "
SELECT id, project, active, manual_publish, onboarding_stage FROM validator_projects WHERE id=84;"
$PSQL -tA -c "
SELECT column_name FROM information_schema.columns
WHERE table_name='validator_schedule_slots' ORDER BY 1;"
```
Затем по реальным колонкам `validator_schedule_slots` проверить, есть ли у проекта 84 слоты с датой после 06.05 (намерение публиковать), которые не превратились в строки очереди. Это разделяет «нет контента/слотов» (операционное) от «слоты есть, но очередь не наполнилась» (баг наполнителя).

- [ ] **Step 3: Verify** — сформулировать наиболее вероятную причину остановки одной фразой (нет слотов/контента / онбординг / отключение / баг наполнителя). Если упирается в нетехническое (контракт, контент от клиента) — это вопрос Ане/операторам, отметить как таковой.

---

## Task 6: Vision-разбор спорных (uncategorized + switch_failed_unspecified)

**Files:**
- Временные кадры в `/tmp/wp72_frames/` (создать).

- [ ] **Step 1: Выбрать представителей с видеозаписью — по ВСЕМ спорным категориям**

Отбор идёт по финальной причинной категории (та же логика, что в Task 2), а **не** по пустому `error_code` — иначе `switch_failed_unspecified` (у него `error_code` НЕ пустой) выпадет из выборки:

```bash
$PSQL -tA -c "
WITH win AS (
  SELECT pq.id qid, pq.project_id, pt.id tid, COALESCE(pt.platform,pq.platform) platform,
         pt.screen_record_url, pt.events, pt.error_code
  FROM publish_queue pq LEFT JOIN publish_tasks pt ON pt.id=pq.publish_task_id
  WHERE ((pq.project_id=82 AND pq.created_at>='2026-05-15')
      OR (pq.project_id=84 AND pq.created_at>='2026-04-15' AND pq.created_at<'2026-05-07'))
    AND pq.status='failed'),
cause AS (
  SELECT w.qid,
    (SELECT e->'meta'->>'category'
       FROM jsonb_array_elements(COALESCE(w.events,'[]'::jsonb)) WITH ORDINALITY t(e,ord)
      WHERE e->>'type'='error' AND e->'meta'->>'category' IS NOT NULL
        AND e->'meta'->>'category' NOT IN ('adb_devices_unreachable','process_interrupted','screencast_stop_failed')
      ORDER BY ord DESC LIMIT 1) final_cat
  FROM win w)
, withcat AS (
  SELECT w.project_id, w.tid, w.platform, w.screen_record_url,
    COALESCE(c.final_cat, NULLIF(NULLIF(NULLIF(NULLIF(w.error_code,''),'adb_devices_unreachable'),'process_interrupted'),'screencast_stop_failed'), 'uncategorized') category
  FROM win w LEFT JOIN cause c ON c.qid=w.qid
  WHERE w.screen_record_url IS NOT NULL)
SELECT project_id, tid, platform, category, screen_record_url
FROM (SELECT *, row_number() OVER (PARTITION BY category ORDER BY tid DESC) rn FROM withcat) z
WHERE category IN ('uncategorized','switch_failed_unspecified')  -- + любые иные спорные из Task 2
  AND rn <= 2
ORDER BY category, project_id;"
```
Партиционирование по категории + `rn<=2` гарантирует **до 2 представителей на КАЖДУЮ** спорную категорию независимо от объёма (как минимум `uncategorized` И `switch_failed_unspecified`; добавить в `IN (...)` иные неясные категории из Task 2).

- [ ] **Step 2: Скачать видеозапись и нарезать кадры**

```bash
mkdir -p /tmp/wp72_frames
# для каждого выбранного screen_record_url:
curl -s -o /tmp/wp72_frames/task_<TID>.mp4 "<screen_record_url>"
ffmpeg -nostdin -i /tmp/wp72_frames/task_<TID>.mp4 -vf fps=1/3 /tmp/wp72_frames/task_<TID>_%03d.jpg
```

- [ ] **Step 3: Прочитать кадры (Read tool) и определить, на каком экране реально завис**

Сопоставить визуальную причину с `vision_analysis_url` (если есть) и с цепочкой событий. Цель — понять, что прячется под пустой/неясной категорией: реальный экран, чужое приложение, аккаунт-проблема.

- [ ] **Step 4: Verify** — каждая спорная категория получила обоснованную интерпретацию (код-баг / аккаунт-устройство / уже починено). Если кадры неинформативны после 1–2 примеров — не углубляться (память: лимит итераций vision), пометить «нужен ручной разбор» и идти дальше.

---

## Task 7: Раскладка по корзинам + дедуп против открытых WP

**Files:**
- Нет (синтез + проверка OpenProject).

- [ ] **Step 1: Свести каждую категорию в одну из корзин (§5 спеки)**

Корзины: `код-баг-новый` / `код-баг-есть-WP` / `уже-починено` / `аккаунт-устройство` / `не-баг`.

- [ ] **Step 2: Дедуп — найти открытые WP проекта на те же сигнатуры**

Пагинируем по ВСЕМ WP проекта (любой статус — чтобы поймать и недавно закрытые сигнатуры, не только первые 200):
```bash
set -a && . ~/secrets/openproject.env && set +a
python3 - <<'PY'
import os, json, base64, urllib.request, urllib.parse
auth = base64.b64encode(f"apikey:{os.environ['OPENPROJECT_API_TOKEN']}".encode()).decode()
base = "https://openproject.contenthunter.ru/api/v3/work_packages"
filt = urllib.parse.quote('[{"project":{"operator":"=","values":["3"]}}]')
offset, size, out = 1, 100, []
while True:
    url = f"{base}?pageSize={size}&offset={offset}&filters={filt}"
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})))
    els = d.get("_embedded", {}).get("elements", [])
    out += els
    if not els or offset * size >= d.get("total", 0):
        break
    offset += 1
print(f"# total WP: {len(out)}")
for e in out:
    print(e["id"], e["_links"]["status"]["title"], "|", e["subject"])
PY
```
Сопоставить найденные категории с уже существующими WP (включая переоткрытые #117/#118/#119 и недавно
закрытые «Готово» — рецидив по такой сигнатуре = переоткрыть существующий, а не плодить новый).
Категория с существующим WP → корзина `код-баг-есть-WP` (не дублировать).

- [ ] **Step 3: Verify** — таблица «категория → корзина → (если есть) существующий WP». Список под-кандидатов на новые WP финализирован.

---

## Task 8: Evidence-файл + коммит

**Files:**
- Create: `docs/evidence/2026-05-25-wp72-publish-error-logs.md`

- [ ] **Step 1: Собрать evidence-файл**

Структура: окна и noise-blocklist (Task 1) → контрольные суммы (Task 2) → таблица категорий → срезы аккаунт/устройство/дни (Task 3) → сверка с релизами (Task 4) → расследование школы (Task 5) → vision-находки (Task 6) → итоговая раскладка по корзинам + дедуп (Task 7). Все SQL-запросы и их вывод — внутри. Технический язык допустим (это для нас).

- [ ] **Step 2: Коммит**

```bash
git add docs/evidence/2026-05-25-wp72-publish-error-logs.md
git commit -m "docs(wp72): evidence — publish error-log triage findings

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: Verify** — `git log --oneline -1` показывает коммит; файл содержит все семь блоков без TODO.

---

## Task 9: Черновик дочерних WP → ЧЕКПОЙНТ (стоп, утверждение Данила)

**Files:**
- Нет (сообщение пользователю).

- [ ] **Step 1: Сформировать черновой список новых WP**

Для каждой категории корзины `код-баг-новый`: предложить `subject` (плейн-язык), `priority` (по частоте), краткое «что происходит». Формат строки: `категория → subject → приоритет → у какого клиента/платформы`.

- [ ] **Step 2: ОСТАНОВКА** — показать список Данилу и дождаться явного «ок/правь». Дочерние WP **не создавать** до утверждения (DoD §6.4). Это outward-facing действие (видно команде).

---

## Task 10: Создание дочерних WP (после утверждения)

**Files:**
- Нет (OpenProject API).

- [ ] **Step 1: Создать каждый утверждённый WP**

```bash
set -a && . ~/secrets/openproject.env && set +a
curl -s -u apikey:$OPENPROJECT_API_TOKEN -X POST \
 "https://openproject.contenthunter.ru/api/v3/projects/3/work_packages" \
 -H "Content-Type: application/json" -d '{
   "subject":"<subject>",
   "_links":{
     "type":{"href":"/api/v3/types/<BUG_TYPE_ID>"},
     "assignee":{"href":"/api/v3/users/5"},
     "parent":{"href":"/api/v3/work_packages/72"},
     "priority":{"href":"/api/v3/priorities/<PRIO_ID>"}
   },
   "description":{"raw":"<плейн-язык: что ломается, у кого, как часто>"}
 }'
```
> Project-scoped эндпоинт (`/projects/3/work_packages`) — проект задаётся URL'ом, в теле `project` не нужен.
> Перед запуском: получить `<BUG_TYPE_ID>` (тип «Ошибка») и `<PRIO_ID>` из `/api/v3/projects/3/types` и
> `/api/v3/priorities`. Если POST вернёт ошибку схемы — свериться с `/api/v3/projects/3/work_packages/form`
> (POST с тем же телом возвращает валидную форму с разрешёнными значениями). Assignee=5 (Данил) обязателен — иначе WP теряются.

- [ ] **Step 2: Verify** — каждый созданный WP вернул id, имеет parent=72 и assignee=Данил. Выписать новые id для отчёта.

---

## Task 11: Отчёт в #72 (house-style) + статус → «Тестирование»

**Files:**
- Нет (OpenProject API).

- [ ] **Step 1: Сформировать комментарий house-style**

Структура: **Что было не так** → **Что сделано** → **Что осталось**. Плейн-язык, без жаргона (no «error_code», «meta.category», «PR», хэшей, путей). Обязательно: сколько «фейлов» — ручные отмены/просрочка; что уже починено; что осталось чинить (со ссылками на новые/существующие WP по номерам); что на стороне аккаунтов/устройств; **отдельный блок про Онлайн-школу** (молчит с 06.05, причина, что было до).

- [ ] **Step 2: Запостить комментарий**

```bash
set -a && . ~/secrets/openproject.env && set +a
curl -s -u apikey:$OPENPROJECT_API_TOKEN -X POST \
 "https://openproject.contenthunter.ru/api/v3/work_packages/72/activities" \
 -H "Content-Type: application/json" -d '{"comment":{"raw":"<markdown-текст>"}}'
```

- [ ] **Step 3: Перевести #72 в «Тестирование» (id 9)**

```bash
set -a && . ~/secrets/openproject.env && set +a
LV=$(curl -s -u apikey:$OPENPROJECT_API_TOKEN "https://openproject.contenthunter.ru/api/v3/work_packages/72" | python3 -c "import sys,json;print(json.load(sys.stdin)['lockVersion'])")
curl -s -u apikey:$OPENPROJECT_API_TOKEN -X PATCH \
 "https://openproject.contenthunter.ru/api/v3/work_packages/72" \
 -H "Content-Type: application/json" -d "{\"lockVersion\":$LV,\"_links\":{\"status\":{\"href\":\"/api/v3/statuses/9\"}}}"
```

- [ ] **Step 4: Verify** — комментарий виден в #72; статус = «Тестирование». Сообщить Данилу итог (новые WP, ключевые выводы, что у школы).

---

## Self-Review (заполняется при написании плана)

**Spec coverage:** §1 цель → Task 11 (отчёт) + блок школы (Task 5); §2 scope (без правок/re-queue) → ни одна задача код не трогает; §3 окна → встроены в каждый SQL; §4.1 финальная категория+noise → Task 1–2; §4.2 срезы → Task 3; §4.3 сверка с релизами → Task 4; §4.4 поправка на выходные → Task 3 Step 4; §4.5 vision → Task 6; §5 корзины+дедуп → Task 7; §6 DoD → Task 8–11; §7 контроль сумм → Task 2 Step 2 + codex; §8 допущения (форма events, NULL-task) → Task 1 + LEFT JOIN везде. Покрыто полностью.

**Placeholder scan:** `<TID>`, `<subject>`, `<BUG_TYPE_ID>` и т.п. — это значения, известные только в рантайме (id конкретных тасков/типов); каждое сопровождается шагом-инструкцией, как его получить. Это не плейсхолдеры логики.

**Type consistency:** окна (82: ≥15.05; 84: 15.04–06.05), noise-blocklist и колонки (`pt.account`, `pt.raspberry`, `pt.device_serial`, `pt.events`, `pt.screen_record_url`) одинаковы во всех задачах.
