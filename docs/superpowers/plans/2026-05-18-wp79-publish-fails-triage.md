# WP #79 — Publish fails triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Выполнить discovery/triage по WP #79 — собрать данные по всем клиентам с publish-проблемами за 7 дней, разложить фейлы по root cause-бакетам, завести child-WP под каждый уникальный root cause, опубликовать summary-комментарий на #79.

**Architecture:** Последовательное выполнение 6 шагов методологии из spec'а. Каждая задача — конкретные SQL-запросы / shell-команды / OpenProject API-вызовы. Никакого нового кода: только запросы к БД, pull screencast'ов, видео-анализ, REST-вызовы. Артефакты: один markdown-отчёт + N child-WP + один комментарий.

**Tech Stack:** psql (БД openclaw), ffmpeg + Read tool с vision (видео-анализ), curl (OpenProject API v3), bash, Python для json-парсинга event'ов.

**Spec:** `docs/superpowers/specs/2026-05-18-wp79-publish-fails-triage-design.md`

**Parent WP:** OpenProject #79 (assignee=danil id=5, parent для всех child-WP).

---

## Pre-flight

- [ ] **Step 0a: Verify worktree + branch**

Run: `git branch --show-current && pwd`
Expected:
```
worktree-wp79-clients-not-publishing
/home/claude-user/contenthunter/.claude/worktrees/wp79-clients-not-publishing
```

- [ ] **Step 0b: Verify OpenProject token + DB access**

Run:
```bash
source ~/secrets/openproject.env && \
  curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
    "https://openproject.contenthunter.ru/api/v3/work_packages/79" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['subject'], '|', d['_links']['assignee']['title'])"
```
Expected: `проверить почему не выкладываются некоторые клиенты | Данил .`

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -At -c "SELECT 1"
```
Expected: `1`

---

## Task 1: Run Query 1a (high-fail-rate clients per platform)

**Files:**
- Create: `/tmp/wp79_query_1a.csv` (рабочий файл, не комитим)

- [ ] **Step 1.1: Запустить SQL 1a и сохранить результат**

Run (group/select по `lower(pt.platform)` чтобы Instagram/instagram не разделились):
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
SELECT vp.id, vp.project, lower(pt.platform) AS platform,
       COUNT(*) FILTER (WHERE pt.status='done') AS done,
       COUNT(*) FILTER (WHERE pt.status='failed') AS failed,
       COUNT(*) FILTER (WHERE pt.status='cancelled') AS cancelled
FROM validator_projects vp
JOIN publish_queue pq ON pq.project_id = vp.id
JOIN publish_tasks pt ON pt.id = pq.publish_task_id
WHERE vp.active = true
  AND vp.project NOT IN ('Tatyana.demo', 'Ann.demo', 'demo for onboarding')
  AND lower(pt.platform) IN ('instagram', 'tiktok', 'youtube')
  AND pt.created_at >= now() - interval '7 days'
  AND pt.created_at::date <> DATE '2026-05-15'
GROUP BY vp.id, vp.project, lower(pt.platform)
HAVING COUNT(*) FILTER (WHERE pt.status IN ('done','failed')) >= 5
ORDER BY (COUNT(*) FILTER (WHERE pt.status='failed'))::float /
         NULLIF(COUNT(*) FILTER (WHERE pt.status IN ('done','failed')), 0) DESC;
" > /tmp/wp79_query_1a.csv
```

- [ ] **Step 1.2: Отфильтровать по fail-rate >50% и зафиксировать целевой список**

Run:
```bash
python3 <<'EOF'
import csv
with open('/tmp/wp79_query_1a.csv') as f:
    rows = list(csv.reader(f, delimiter='|'))
header, data = rows[0], rows[1:-1]  # skip last "(N rows)" line
targets = []
for r in data:
    pid, project, platform, done, failed, cancelled = r
    done, failed = int(done), int(failed)
    if done + failed == 0:
        continue
    rate = failed / (done + failed)
    if rate > 0.5:
        targets.append((pid, project, platform, done, failed, round(rate, 2)))
print("project_id|project|platform|done|failed|fail_rate")
for t in targets:
    print('|'.join(str(x) for x in t))
EOF
```
Expected: список из ≥2 строк (минимум Релизми по 3 платформам). Сохранить вывод — он войдёт в раздел «Сводка» отчёта.

- [ ] **Step 1.3: Сравнить с raw fail-rate (без OTA-фильтра) для аудита**

Run тот же запрос, убрав строку `AND pt.created_at::date <> DATE '2026-05-15'`. Если raw fail-rate почти равен OTA-отфильтрованному — значит OTA не единственный плохой день, продолжаем. Если расхождение большое (>15%) — отмечаем в отчёте.

---

## Task 2: Run Query 1b (full downtime detection)

**Files:**
- Create: `/tmp/wp79_query_1b.csv`

- [ ] **Step 2.1: Запустить SQL 1b**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
WITH expected AS (
  SELECT vss.project_id, COUNT(*) AS filled_slots
  FROM validator_schedule_slots vss
  WHERE vss.status = 'filled'
    AND vss.slot_date > current_date - 7
    AND vss.slot_date <= current_date
  GROUP BY vss.project_id
),
attempts AS (
  SELECT pq.project_id, COUNT(pt.id) AS attempts_n
  FROM publish_queue pq
  JOIN publish_tasks pt ON pt.id = pq.publish_task_id
  WHERE pt.created_at >= now() - interval '7 days'
    AND lower(pt.platform) IN ('instagram', 'tiktok', 'youtube')
  GROUP BY pq.project_id
)
SELECT vp.id, vp.project, e.filled_slots, COALESCE(a.attempts_n, 0) AS attempts_n
FROM validator_projects vp
JOIN expected e ON e.project_id = vp.id
LEFT JOIN attempts a ON a.project_id = vp.id
WHERE vp.active = true
  AND vp.project NOT IN ('Tatyana.demo', 'Ann.demo', 'demo for onboarding')
  AND COALESCE(a.attempts_n, 0) = 0
  AND e.filled_slots > 0;
" > /tmp/wp79_query_1b.csv
```

- [ ] **Step 2.2: Зафиксировать список «полный простой»**

Если в выводе есть строки — это клиенты с полным простоем. Минимум ожидается Anecole (id=84). Записать в `targets_downtime` для дальнейшего pipeline-разбора в Task 4.

---

## Task 3: Bucket failed tasks по error_code + last events.meta.category

**Files:**
- Create: `/tmp/wp79_buckets.txt`

- [ ] **Step 3.1: Для каждого (client × platform) из Task 1, собрать distribution бакетов**

Для каждой таргет-пары запустить:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
SELECT pt.error_code,
       (
         SELECT e->'meta'->>'category'
         FROM jsonb_array_elements(pt.events) e
         WHERE e->>'type' = 'error'
         ORDER BY (e->>'ts')::timestamp DESC
         LIMIT 1
       ) AS last_error_category,
       COUNT(*) AS n,
       MIN(pt.id) AS sample_pt_id
FROM publish_tasks pt
JOIN publish_queue pq ON pq.publish_task_id = pt.id
WHERE pq.project_id = <PROJECT_ID>
  AND lower(pt.platform) = '<PLATFORM>'
  AND pt.status = 'failed'
  AND pt.created_at >= now() - interval '7 days'
  AND pt.created_at::date <> DATE '2026-05-15'
GROUP BY 1, 2
ORDER BY n DESC;
"
```

Подставить `<PROJECT_ID>` и `<PLATFORM>` (lowercase: instagram/tiktok/youtube) для каждой целевой пары. Записать в `/tmp/wp79_buckets.txt` секцию вида:
```
=== project_id=9 (Relisme) × tiktok ===
error_code|last_error_category|n|sample_pt_id
switch_failed_unspecified|adb_push_timeout|13|12345
tt_profile_tab_broken|tt_profile_tab|7|12346
...
```

- [ ] **Step 3.2: Объединить дубликаты RC между клиентами**

Один и тот же `(error_code, last_error_category)` от разных клиентов = один code-bug bucket. Составить таблицу:
```
bucket_key=(error_code, last_category)|total_n|affected_clients|sample_pt_id
```
Сохранить как Python-словарь или JSON в `/tmp/wp79_global_buckets.json` для удобства Task 6/7.

- [ ] **Step 3.3: Пометить бакеты-кандидаты на video-проверку**

Кандидаты для Task 5 (video sample):
- `switch_failed_unspecified` (память: маскировка adb_push_timeout)
- `process_interrupted` (без явного RC)
- Любой bucket, где `last_error_category` равен NULL или совпадает с `error_code` (нет уточнения)
- Любой bucket, который не маппится на known issue из памяти / git log

Отметить их в `/tmp/wp79_global_buckets.json` флагом `needs_video=true`.

---

## Task 4: Content-pipeline разбор для клиентов с простоем

Для каждого клиента из `targets_downtime` (Task 2):

- [ ] **Step 4.1: Status distribution по `validator_content`**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
SELECT status::text, content_type, COUNT(*), 
       MIN(created_at)::date AS first_at, MAX(updated_at)::date AS last_at
FROM validator_content WHERE project_id = <PROJECT_ID>
  AND created_at > now() - interval '30 days'
GROUP BY 1, 2 ORDER BY 3 DESC;
"
```
Записать какой статус доминирует (`in_uniqualization` / `needs_review` / `rejected` / `approved`).

- [ ] **Step 4.2: Проверить `validator_unic_content`**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
SELECT COUNT(*) AS total, MAX(id) AS last_id,
       MAX(file_params->>'created_at')::timestamp AS last_created_at_from_params
FROM validator_unic_content WHERE project_id = <PROJECT_ID>;
"
```

Заметка: у `validator_unic_content` нет колонки `created_at`/`updated_at` напрямую (см. spec § Methodology), поэтому temporal-evidence можно вытащить только из `file_params` JSONB если оно туда пишется, либо из `MIN(vc.created_at)` для связанных rows в `validator_content` через `validator_unic_content.label`/joins. Если ни того ни другого нет — использовать `MAX(id)` **только как косвенный признак** и проверять через `validator_content`:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
SELECT MAX(vc.updated_at)::date AS last_vc_update,
       MAX(vc.created_at)::date AS last_vc_create
FROM validator_content vc WHERE project_id = <PROJECT_ID> AND status::text = 'approved';
"
```
Если `total = 0` или `last_vc_update` старше окна простоя — пайплайн залип на стадии uniqualization, контент не дотекает до approved.

- [ ] **Step 4.3: Проверить filled-слоты vs queue**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
SELECT slot_date, COUNT(*) FILTER (WHERE status::text='filled') AS filled,
       COUNT(*) FILTER (WHERE status::text='empty') AS empty
FROM validator_schedule_slots
WHERE project_id = <PROJECT_ID>
  AND slot_date BETWEEN current_date - 7 AND current_date + 3
GROUP BY slot_date ORDER BY slot_date;
"
```

Записать стейдж, на котором пайплайн залип. Зафиксировать гипотезу (worker не запущен / контент не апрувится / нет approved unic_content и т.д.).

- [ ] **Step 4.4: (опц.) Проверить pm2-логи uniqualizer на VPS**

Если есть подозрение на worker — `ssh fra-1-vm-y49r 'pm2 logs <unic-worker-name> --lines 200 --nostream'`. Имя сервиса найти через `pm2 list`. Не нашёл — отметить в отчёте «pm2 worker не идентифицирован, нужно investigation-WP».

---

## Task 5: Video sample для подозрительных бакетов

Для каждого bucket из Task 3 с флагом `needs_video=true`:

- [ ] **Step 5.1: Достать sample pt + screen_record_url**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
SELECT id, error_code, platform, account, screen_record_url, vision_analysis_url
FROM publish_tasks WHERE id = <SAMPLE_PT_ID>;
"
```

- [ ] **Step 5.2: Скачать запись + извлечь кадры**

Run (важно: URL в **одинарных** кавычках, чтобы `&`/`?` из signed S3 URL не пытались интерпретироваться shell'ом):
```bash
PT=<SAMPLE_PT_ID>
URL='<screen_record_url>'   # одинарные кавычки обязательны
wget -q "$URL" -O /tmp/wp79_rec_${PT}.mp4 && \
  ffmpeg -y -hide_banner -loglevel error \
    -i /tmp/wp79_rec_${PT}.mp4 \
    -vf fps=1/5 /tmp/wp79_frame_${PT}_%03d.jpg && \
  ls -la /tmp/wp79_frame_${PT}_*.jpg
```

- [ ] **Step 5.3: Визуальный анализ через Read tool (vision)**

Claude Code Read tool поддерживает image input (PNG/JPG) — кадры рендерятся через vision-возможности модели. На 3-5 ключевых кадрах (последние перед фейлом) запустить:
```
Read tool с file_path=/tmp/wp79_frame_<PT>_<NNN>.jpg
```
По кадру идентифицировать: что показано на экране телефона в момент фейла (стейт IG/TT/YT приложения, модальные окна, ошибки). Сверить с предполагаемым RC.

- [ ] **Step 5.4: Зафиксировать вывод**

В `/tmp/wp79_global_buckets.json` обновить bucket с полем `verified_rc` (что реально видно на видео) и `notes`. Если RC отличается от `last_error_category` — это новый bucket, добавить отдельно.

- [ ] **Step 5.5: Cleanup временных файлов**

Run: `rm /tmp/wp79_rec_*.mp4 /tmp/wp79_frame_*.jpg`

---

## Task 6: Device/account drift проверка для ops-кейсов

Для бакетов, где `last_error_category` или `error_code` указывает на mismatch аккаунта (`tt_target_not_on_device`, `*_account_not_in_list`, `*_target_not_in_picker`):

- [ ] **Step 6.1: Получить связку (account, device, pack) из БД**

Run:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -A -F'|' -c "
SELECT pq.account_username, pq.device_serial, pq.adb_port, pq.raspberry_number, pq.pack_id, pq.pack_name
FROM publish_queue pq
JOIN publish_tasks pt ON pt.id = pq.publish_task_id
WHERE pt.id = <SAMPLE_PT_ID>;
"
```

- [ ] **Step 6.2: Свериться с фактом на телефоне через revision**

В зависимости от платформы:
- **IG/TT:** запустить `python3 -m switcher_audit --device <serial> --platform <platform>` (если есть revision-helper) ИЛИ через `python3 -c "from AccountSwitcher import read_accounts_list; print(read_accounts_list(...))"`. Точная команда зависит от прод-структуры — если не найдена, использовать adb dump:
  ```bash
  adb -s <serial> shell uiautomator dump /sdcard/dump.xml && \
    adb -s <serial> pull /sdcard/dump.xml /tmp/wp79_ui_${PT}.xml
  ```
- **YT:** `am start com.google.android.youtube/.app.application.Shell_SettingsActivity` → swipe до «Аккаунт» → dump (память `reference_yt_accounts_settings_path`).

- [ ] **Step 6.3: Сверить факт с ожиданием**

Если на устройстве нет ожидаемого аккаунта (разлогинен / удалён / другой пользователь) — это **operations bucket**, не code bucket. Зафиксировать в `/tmp/wp79_global_buckets.json` с типом `ops` и `affected_keys=[(client, account, device), ...]`.

---

## Task 7: Сборка отчёта

**Files:**
- Create: `docs/evidence/2026-05-18-wp79-publish-triage.md`

- [ ] **Step 7.1: Создать skeleton отчёта**

Структура (по spec'у §4):
```markdown
# WP #79 — Publish-fails triage отчёт

**Дата:** 2026-05-18
**Окно:** 2026-05-11 — 2026-05-18 (7 дней, исключая 2026-05-15 OTA-инцидент)
**Источник методологии:** docs/superpowers/specs/2026-05-18-wp79-publish-fails-triage-design.md

## Сводка

| client | platform | done | failed | fail-rate | downtime | root cause | child-WP / status |
|--------|----------|------|--------|-----------|----------|------------|-------------------|
| ... (заполняется из Task 1 + Task 6 mapping) |

## Per-client

### Релизми (id=9)
- IG: ...
- TT: ...
- YT: ...

### Anecole (id=84)
- Pipeline-затор: ... (из Task 4)
- TT account drift: ... (из Task 6)

### <остальные затронутые клиенты>
...

## Buckets

### Bucket: `<error_code> / <last_category>`
- **Симптом:** ...
- **Затронуты:** N тасков, M клиентов
- **Sample pt_id:** <N>
- **Screencast:** <S3 url>
- **Verified RC:** ... (из Task 5)
- **Status:** SHIPPED 2026-05-18 PR #X / child-WP #N / investigation
```

- [ ] **Step 7.2: Заполнить раздел «Сводка»**

Из `/tmp/wp79_global_buckets.json` собрать таблицу. Каждая строка — (client, platform, root_cause).

- [ ] **Step 7.3: Заполнить раздел «Per-client»**

По одному подразделу на каждого клиента из union(Task1, Task2). Включать ссылки на семплы pt_id, screen_record_url.

- [ ] **Step 7.4: Заполнить раздел «Buckets»**

Один параграф на bucket из `/tmp/wp79_global_buckets.json`. Для already-shipped — пометить `Status: SHIPPED 2026-05-18 PR #X (не открываем WP)`.

- [ ] **Step 7.5: Commit отчёта (placeholder для WP-ссылок)**

В этот момент WP ещё не созданы (Task 8). Оставить плейсхолдер `<WP #TBD>` для child-WP — заполним после Task 8.

Run:
```bash
git add docs/evidence/2026-05-18-wp79-publish-triage.md
git commit -m "docs(wp79): triage report skeleton + sweeps (pre-WP creation)"
```

---

## Task 8: Создание child-WP в OpenProject

Для каждого bucket из `/tmp/wp79_global_buckets.json`, который **не** SHIPPED:

- [ ] **Step 8.0: Маппинг bucket-type → subject prefix + TYPE_ID**

| bucket type | subject prefix | TYPE_ID | пример subject |
|-------------|----------------|---------|----------------|
| code-bug | (нет) | 2 (Ошибка) | `tt_profile_tab_broken: нет fallback на /Profile` |
| operations | `[ops]` | 1 (Задача) | `[ops] re-login Anecole TT-аккаунтов на dev72/73/74` |
| pipeline (downtime <7d) | `[pipeline]` | 2 (Ошибка) | `[pipeline] Anecole content залип в in_uniqualization` |
| pipeline (downtime ≥7d) | `[pipeline][P1]` | 2 (Ошибка) | `[pipeline][P1] Anecole 12-day publishing outage` |
| investigation | `[investigation]` | 1 (Задача) | `[investigation] switch_failed_unspecified — что в видео` |

- [ ] **Step 8.1: Подготовить body шаблон**

Для каждого bucket собрать markdown:
```markdown
**Что происходит**
[error_code]: [симптом]. За 7 дней — [N] фейлов на [M] клиентах ([client list]). Платформа: [IG/TT/YT].

**Evidence**
- Отчёт: docs/evidence/2026-05-18-wp79-publish-triage.md#bucket-<anchor>
- Семпл pt id: [N]
- Screencast: [S3 url]

**Гипотеза root cause**
[verified_rc из Task 5 или DB-вывод из Task 3]

**Что должно быть сделано**
- [ ] [действие 1, зависит от типа bucket]
- [ ] [действие 2]
```

- [ ] **Step 8.2: POST work_package per bucket**

Для каждого bucket:
```bash
source ~/secrets/openproject.env

# Тип: 1 = Задача (ops/pipeline/investigation), 2 = Ошибка (code-bug)
TYPE_ID=<1_or_2>
SUBJECT="[ops] re-login Anecole TT-аккаунтов на dev72/73/74"  # пример
BODY_FILE="/tmp/wp79_wp_body_<bucket_id>.md"

curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
  -X POST "https://openproject.contenthunter.ru/api/v3/work_packages" \
  -H "Content-Type: application/json" \
  -d @<(jq -n \
    --arg subj "$SUBJECT" \
    --arg body "$(cat "$BODY_FILE")" \
    --argjson type_id "$TYPE_ID" '
    {
      subject: $subj,
      description: {format: "markdown", raw: $body},
      _links: {
        type: {href: ("/api/v3/types/" + ($type_id|tostring))},
        project: {href: "/api/v3/projects/3"},
        assignee: {href: "/api/v3/users/5"},
        parent: {href: "/api/v3/work_packages/79"}
      }
    }
  ') | jq '{id, subject, parent: ._links.parent.title}'
```

Зафиксировать `id` каждого созданного WP. Сохранить mapping в `/tmp/wp79_wp_ids.tsv` со строгим TSV-форматом `<bucket_id>\t<wp_id>\t<subject>` (одна строка на bucket):
```
b001	101	[ops] re-login Anecole TT-аккаунтов на dev72/73/74
b002	102	tt_profile_tab_broken: нет fallback на /Profile
...
```

- [ ] **Step 8.3: Verify все WP в OpenProject**

Run (парсим TSV-колонку 2 = wp_id):
```bash
source ~/secrets/openproject.env
while IFS=$'\t' read -r bucket_id wp_id subject; do
  curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
    "https://openproject.contenthunter.ru/api/v3/work_packages/$wp_id" \
    | jq -r '"\(.id) | \(.subject) | parent=\(._links.parent.title) | assignee=\(._links.assignee.title)"'
done < /tmp/wp79_wp_ids.tsv
```
Expected: каждая строка содержит `parent=проверить почему не выкладываются некоторые клиенты` и `assignee=Данил .`.

---

## Task 9: Обновить отчёт ссылками на WP + commit

- [ ] **Step 9.1: Заменить плейсхолдеры в отчёте**

Run sed для каждого `<WP #TBD>` → реальный `<WP #N>` из `/tmp/wp79_wp_ids.tsv` (TSV-колонки: bucket_id, wp_id, subject). Использовать grep/Edit вручную если sed-замена ненадёжна.

- [ ] **Step 9.2: Commit финального отчёта**

Run:
```bash
git add docs/evidence/2026-05-18-wp79-publish-triage.md
git commit -m "docs(wp79): fill child-WP links in triage report"
```

---

## Task 10: Summary-комментарий на WP #79

- [ ] **Step 10.1: Составить комментарий в стиле «Что было / Что сделано / Что осталось»**

Шаблон (без footer, без эмодзи, по памяти `feedback_openproject_practice`):
```markdown
**Что было не так**
За 7 дней (исключая OTA-инцидент 2026-05-15) — N клиентов с fail-rate >50% по IG/TT/YT и M клиентов с полным простоем (есть filled-слоты, 0 attempts). У Релизми (id=9) основной симптом — chronic high fail rate из смеси известных багов. У Anecole (id=84) — content-pipeline затор на стадии uniqualization (12 дней простоя).

**Что сделано**
- Триаж и сводный отчёт: docs/evidence/2026-05-18-wp79-publish-triage.md
- Заведены child-WP под каждый уникальный root cause:
  - #<N1> — [subject]
  - #<N2> — [subject]
  - ...
- Уже SHIPPED фиксы 2026-05-18 (PR #68 yt_editor_upload_timeout, PR #69 tt_upload_confirmation_timeout) — указаны в отчёте, отдельных WP не открыты.

**Что осталось**
Прохождение child-WP — отдельные циклы. Этот WP можно закрыть после ревью отчёта.
```

- [ ] **Step 10.2: POST комментарий**

Run:
```bash
source ~/secrets/openproject.env
BODY_FILE=/tmp/wp79_summary_comment.md
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
  -X POST "https://openproject.contenthunter.ru/api/v3/work_packages/79/activities" \
  -H "Content-Type: application/json" \
  -d @<(jq -n --arg body "$(cat "$BODY_FILE")" '{comment: {raw: $body}}') \
  | jq '{id, comment: .comment.raw[:80]}'
```
Expected: вернётся объект с `id` и началом текста комментария.

- [ ] **Step 10.3: Verify комментарий на WP**

Run:
```bash
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
  "https://openproject.contenthunter.ru/api/v3/work_packages/79/activities" \
  | jq '._embedded.elements[-1] | {id, comment: .comment.raw[:120], user: ._links.user.title}'
```
Expected: последний элемент — наш summary, user=`Данил .`.

---

## Task 11: Финальный cleanup + push

- [ ] **Step 11.1: Удалить временные файлы**

Run:
```bash
rm -f /tmp/wp79_query_1a.csv /tmp/wp79_query_1b.csv \
      /tmp/wp79_buckets.txt /tmp/wp79_global_buckets.json \
      /tmp/wp79_wp_body_*.md /tmp/wp79_wp_ids.tsv \
      /tmp/wp79_summary_comment.md /tmp/wp79_ui_*.xml
```

- [ ] **Step 11.2: Проверить git-state и push ветку**

Run:
```bash
git status
git log --oneline -5
git push -u origin worktree-wp79-clients-not-publishing
```
Expected: чистый working tree, 2-3 коммита (spec + plan + report), ветка запушена.

- [ ] **Step 11.3: Финальная проверка #79**

Run:
```bash
source ~/secrets/openproject.env
curl -s -u "apikey:$OPENPROJECT_API_TOKEN" \
  "https://openproject.contenthunter.ru/api/v3/work_packages?filters=%5B%7B%22parent%22%3A%7B%22operator%22%3A%22%3D%22%2C%22values%22%3A%5B%2279%22%5D%7D%7D%5D" \
  | jq '._embedded.elements | length, [.[] | {id, subject, assignee: ._links.assignee.title}]'
```
Expected: number = количество child-WP из Task 8, все assigned to `Данил .`.

---

## Out of scope (по spec'у)

- Не пишем код, не делаем re-queue, не лечим OTA-инцидент, не оптимизируем триаж в долгую, не диагностируем VK/FB/Pinterest/Likee.
- Каждый child-WP проходит отдельный цикл brainstorming → spec → plan → implement.
