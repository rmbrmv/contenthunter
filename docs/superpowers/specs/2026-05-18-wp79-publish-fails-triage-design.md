# WP #79 — Publish fails triage (Релизми, Anecole, и все active клиенты с fail-rate >50%)

**Тип:** discovery / triage spec  
**Parent WP:** OpenProject #79 «проверить почему не выкладываются некоторые клиенты»  
**Автор треда:** Анастасия (OpenProject id=6), назначено на danil (id=5)  
**Дата:** 2026-05-18

## Контекст

Анастасия завела #79 с упоминанием двух клиентов — «Релизми» и «Онлайн школа». Разведка показала:

- **Релизми** = `validator_projects` id=9, api_name=`relisme`. Публикует активно (последняя попытка 2026-05-17), но за 7 дней fail-rate ~50–60% по IG/TT/YT. Top error_codes: `switch_failed_unspecified` ×32 (известная маскировка adb_push_timeout), `ig_gallery_no_video_candidate`, `tt_profile_tab_broken`, `yt_editor_upload_timeout`. Часть из них уже SHIPPED сегодня — WP #80 (yt_editor) и #82 (tt_upload_confirmation).
- **Онлайн-школа Anecole** = `validator_projects` id=84, api_name=`onlayn_shkola_anecole_content_hunter`. Публикация **полностью встала с 2026-05-06 (12 дней)**. `publish_queue` после id=1081 пуст. 22 контента залипли в `validator_content.status='in_uniqualization'`, в `validator_unic_content` для project_id=84 — 0 строк. Никакой контент не доходит до публикации. До простоя: TT 100% fail с `tt_target_not_on_device` для всех 3 TT-аккаунтов.

То есть это два разных failure-mode под одним WP: chronic high-fail-rate (Релизми) vs полный pipeline-затор (Anecole). Анастасия и пользователь подтвердили: scope расширяем на всех активных клиентов с похожими симптомами, выход = триаж + child-WP, фиксы — потом отдельными циклами.

## Цель

Выдать триаж-отчёт по всем активным клиентам с publish-проблемами и завести child-WP под каждый уникальный root cause. Сам WP #79 закрывается отчётом + сводным комментарием.

## Acceptance criteria

1. В `docs/evidence/2026-05-18-wp79-publish-triage.md` лежит структурированный отчёт: клиент → платформа → fail-rate 7d → root cause → ссылка на child-WP или пометка `SHIPPED 2026-05-18 PR #X`.
2. Для каждого нового root cause в OpenProject создан child-WP (parent=#79, project=content-hunter id=3, assignee=danil id=5). Для already-shipped error_codes (`yt_editor_upload_timeout`, `tt_upload_confirmation_timeout`) — только упоминание в отчёте, без WP.
3. На WP #79 опубликован summary-комментарий в формате «Что было не так → Что сделано → Что осталось» со ссылками на отчёт и все child-WP.
4. Anecole content-pipeline затор — отдельный child-WP с маркером `[P1]` в subject (полный простой ≥7 дней).
5. WP с device/account drift — с тегом `[ops]` в subject.

## Scope

### Включаем
- Любой `validator_projects.active=true` проект, у которого за `now() - interval '7 days'` fail-rate `failed / (failed + done) > 0.5` при `(failed + done) >= 5` attempts на платформу.
- Плюс любой активный проект с **полным простоем** за 7 дней (0 attempts) при наличии filled-слотов в `validator_schedule_slots` на это окно. Этот критерий ловит Anecole-style content-pipeline заторы, которые fail-rate не покажет.

### Исключаем
- Платформы вне autowarm-scope: VK, FB, Pinterest, Likee (память `project_autowarm_scope` — 2026-04-17). В `publish_queue` они есть как `skipped`/`cancelled`, в fail-rate не учитываем.
- Demo-проекты: `Tatyana.demo`, `Ann.demo`, `demo for onboarding`.
- Фейлы 2026-05-15 — отдельный root cause (OTA-screen, память `feedback_ota_screen_blocks_adb_preflight`). В bucket'ы не идут, помечаются меткой `OTA-2026-05-15` в отчёте.
- Already-shipped 2026-05-18 фиксы (PR #68 `yt_editor_upload_timeout`, PR #69 `tt_upload_confirmation_timeout`) — упоминание в отчёте, новых WP не открываем.

### Out of scope
- Никакого код-фикса в рамках #79 — это discovery WP, выход = отчёт + child-WP.
- Re-queue failed публикаций (`publish_queue → pending`, память `reference_publish_requeue_path`) — решение пользователя по итогам отчёта, не действие #79.
- Оптимизация / автоматизация самой методологии триажа — отдельный WP при желании.
- Расследование OTA-инцидента 2026-05-15 — отдельный root cause, отражён в памяти.

## Методология

### Шаг 1 — список целевых клиентов (SQL)

Два независимых запроса. **Окно:** `now() - interval '7 days'`, **исключая** дату OTA-инцидента `2026-05-15` (иначе fail-rate раздут — память `feedback_ota_screen_blocks_adb_preflight`).

**Запрос 1a — high-fail-rate клиенты** (исключения из scope зашиты в WHERE: demo-проекты, не-autowarm платформы, OTA-день):
```sql
SELECT vp.id, vp.project, pt.platform,
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
GROUP BY vp.id, vp.project, pt.platform
HAVING COUNT(*) FILTER (WHERE pt.status IN ('done','failed')) >= 5;
```
Из результата отбираем строки с `failed / (failed+done) > 0.5`. Для аудита параллельно считаем raw fail-rate без OTA-фильтра, чтобы заметить если 2026-05-15 — не единственный плохой день.

**Запрос 1b — полный простой (`expected > 0`, `attempts == 0`):**
Driver = `validator_schedule_slots` (filled-слоты), LEFT JOIN на `publish_tasks` через `publish_queue`. «Полный простой» = `attempts_in_window == 0` для autowarm-платформ (IG/TT/YT), не «`publish_queue` пуст» — у клиента могут быть `cancelled`/`skipped` строки или non-autowarm платформы при нулевых attempts на IG/TT/YT. `slot_date` диапазон строго 7 дней (`> current_date - 7`, не `BETWEEN` чтобы не словить 8 дат).

Заметка: `validator_schedule_slots` — project-level, без поля platform. Если в будущем появится платформа в slots — переделать на per-platform.

```sql
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
```

### Шаг 2 — разбор failed-тасков по бакетам

Для каждой пары (клиент × платформа), которая прошла фильтр Шага 1:
- Группируем `publish_tasks` со `status='failed'` по `error_code`.
- Для каждой группы пересчитываем реальный root cause через последнюю запись `events[].meta.category` в jsonb (память `feedback_publisher_error_code_misleading` — `error_code` пишет первую ошибку, часто preflight `adb_devices_unreachable`).
- Считаем число тасков на бакет. Бакеты с ≥3 тасками идут в отчёт, единичные — упоминаются с пометкой «tail».

Пример SQL для перепроверки RC через events (вытаскиваем именно `meta.category`, плюс сырое `meta` для аудита):
```sql
SELECT pt.id, pt.error_code,
       (
         SELECT e->'meta'->>'category'
         FROM jsonb_array_elements(pt.events) e
         WHERE e->>'type' = 'error'
         ORDER BY (e->>'ts')::timestamp DESC
         LIMIT 1
       ) AS last_error_category,
       (
         SELECT e->'meta'
         FROM jsonb_array_elements(pt.events) e
         WHERE e->>'type' = 'error'
         ORDER BY (e->>'ts')::timestamp DESC
         LIMIT 1
       ) AS last_error_meta_raw
FROM publish_tasks pt
WHERE pt.status='failed' AND pt.id IN (...);
```

### Шаг 3 — video sample для подозрительных бакетов

Для бакетов с неочевидным RC (`switch_failed_unspecified`, `process_interrupted`, любые без явного code-маппинга или ранее не задокументированные) — 1–2 семпла:
- Достать `screen_record_url` и `vision_analysis_url` из `publish_tasks`.
- `wget -q "$URL" -O /tmp/wp79_rec_<id>.mp4 && ffmpeg -i /tmp/wp79_rec_<id>.mp4 -vf fps=1/5 /tmp/wp79_frames_<id>_%03d.jpg`
- Прочитать ключевые кадры через Read tool (per памяти `feedback_publish_fail_analysis_video_first` — primary RC часто скрыт под secondary).
- Если RC совпал с известным WP/PR — маппим в отчёт. Если новый — выписываем отдельным bucket'ом.

### Шаг 4 — content-pipeline проверка для клиентов с простоем

Для каждого клиента из «полный простой» списка:
- `validator_content`: распределение по статусам (`in_uniqualization`, `needs_review`, `rejected`, `approved`). Где залипает.
- `validator_unic_content`: есть ли вообще output uniqualization для этого `project_id`.
- `validator_schedule_slots`: сколько filled-слотов на ближайшие 7 дней, и почему они не превратились в `publish_queue` (вероятно нет approved unic_content).
- Если есть подозрение на сломанный worker — `pm2 logs` соответствующего сервиса за последние 24ч на VPS (`fra-1-vm-y49r`).

### Шаг 5 — account/device drift проверка

Для бакетов вида `tt_target_not_on_device`, `*_account_not_in_list`, `*_target_not_in_picker`:
- Сверить `factory_pack_accounts.device_num_id` с фактическим состоянием на телефоне через revision-механизмы:
  - IG/TT: `AccountSwitcher.read_accounts_list` (память `feedback_revision_hardening_rules`).
  - YT: `am start com.google.android.youtube/.app.application.Shell_SettingsActivity` → «Аккаунт» (память `reference_yt_accounts_settings_path`).
- Если drift (аккаунт удалён, разлогинен, другой аккаунт залогинен) — операционный child-WP, **не код-WP**.

### Шаг 6 — bucket → WP маппинг

**Группировка по типу:**
- **Code-bug bucket** → один WP **на уникальный root cause** (один RC = один WP, все затронутые клиенты перечислены в теле).
- **Operations bucket** (account/device drift) → один WP **на затронутую (client, account, device) тройку или связку**. Один RC может породить несколько WP, потому что лечится по-разному на каждом устройстве.
- **Pipeline bucket** → один WP на (клиент, стейдж залипания) — Anecole-style.
- **Investigation bucket** → один WP на RC, если нужно ещё расследование.

Тело по шаблону:

```markdown
**Что происходит**
Симптом, error_code, частота за 7д, затронутые клиенты/аккаунты.

**Evidence**
- Отчёт: docs/evidence/2026-05-18-wp79-publish-triage.md#<anchor>
- Семпл pt id: <N>
- Screencast: <S3 url>

**Гипотеза root cause**
Короткая формулировка.

**Что должно быть сделано**
- [ ] действие 1
- [ ] действие 2
```

Заводится через OpenProject API:
```
POST /api/v3/work_packages
{
  "subject": "...",
  "_links": {
    "type": {"href": "/api/v3/types/1"},       # «Задача» или /api/v3/types/2 для «Ошибка»
    "project": {"href": "/api/v3/projects/3"},
    "assignee": {"href": "/api/v3/users/5"},
    "parent": {"href": "/api/v3/work_packages/79"}
  },
  "description": {"raw": "...markdown..."}
}
```

## Типы child-WP

- **Code-bug WP** — новый/неизвестный error_code → assignee=danil, без тега. Тип «Ошибка» (id=2).
- **Operations WP** — drift аккаунта на устройстве, разлогин, нужно вручную пере-залогинить → `[ops]` в subject, assignee=danil, тип «Задача» (id=1).
- **Pipeline WP** — Anecole-style затор в `validator_content`/`validator_unic_content` → assignee=danil, `[P1]` в subject если простой >7д, тип «Ошибка».
- **Investigation WP** — для бакетов, где видео+events не дали однозначный root cause за 1 семпл → assignee=danil, «нужно расширенное расследование», тип «Задача», не блокер #79.

## Артефакты

1. **`docs/evidence/2026-05-18-wp79-publish-triage.md`** — отчёт. Структура:
   - Раздел «Сводка» — таблица: клиент / платформа / done / failed / fail-rate / простой / root cause / статус (WP-link или SHIPPED).
   - Раздел «Per-client» — детали на каждого затронутого клиента: SQL-выборки, ссылки на семплы screen_record_url, выводы по pipeline.
   - Раздел «Buckets» — каждый root cause: симптом, как диагностирован, evidence, связанный WP/PR.
2. **Child-WP** в OpenProject (один на root cause).
3. **Комментарий на WP #79** — summary в формате «Что было не так → Что сделано → Что осталось» (память `feedback_openproject_practice`), со ссылками на отчёт и все child-WP. Без footer.
4. **Сам spec** — `docs/superpowers/specs/2026-05-18-wp79-publish-fails-triage-design.md` (этот файл).

## Риски

- **Memory drift** — часть memory-фактов про error_codes / SHIPPED PR могут быть устаревшими. Перед закрытием бакета как «уже починено» — `gh pr view <N>` и `git log` проверка (память `feedback_plan_staleness`).
- **OTA-инцидент маскирует** — если плохо отфильтруем 2026-05-15, fail-rate в 7d окне завышен. Считаем без этого дня.
- **`error_code` врёт** — Шаг 2 обязателен, без events-перепроверки бакеты будут смещены.
- **Anecole pipeline** — заглушка может быть на стороне worker'а, недоступная без VPS pm2 логов. Если из логов не понятно — открываем investigation-WP вместо code-WP.
- **Скоп раздувается** — если активных клиентов с fail-rate >50% окажется >10, риск overflow. Митигация: bucket'ы с <3 тасков идут в `tail`, не в отчёт.

## Что НЕ делаем в этом WP

- Не пишем код.
- Не делаем re-queue.
- Не лечим OTA-инцидент 2026-05-15.
- Не оптимизируем триаж в долгую (отдельный WP при желании).
- Не диагностируем VK/FB/Pinterest/Likee.
