# Remote Factory DB — Полный Phase-Out (Design)

> **Статус:** Design / spec. Реализация планируется отдельно через `writing-plans` (см. в конце).
> **Дата:** 2026-04-30
> **Автор:** Danil Pavlov + Claude (brainstorm session)

## Контекст

В новом сервисе `contenthunter.ru` остались привязки к старой внешней БД master-системы `factory@193.124.112.222:49002` (read-only пользователь `roman_ai_readonly`). Старая система продолжает работать в ручном режиме у партнёров, но **новый сервис должен полностью отключиться** от неё. Любая связка с `193.124.112.222` рассматривается как legacy-долг к выпилу.

### Текущее состояние (баланс на 2026-04-30)

Активный мост validator ↔ remote:
- `validator/sync_sources.py` — cron `*/15 * * * *` (предположительно root). Тянет `users` + `contentlab_videos_upload` с remote → пишет в local `factory_users` и `factory.contentlab_videos_upload`. Возвращает обратно UPDATE статусов валидации.
- За 24ч: 5 новых видео, за 7д: 42. Канал живой.
- TCP-сессии VPS → 193.124.112.222:49002 видны в `ss -tn` (FIN-WAIT-2).

Привязки в autowarm (12 файлов, найдены `git grep "193\.124\.112\.222"`):

| Файл | Read remote | Write remote | Триггер | Liveness |
|---|---|---|---|---|
| `analytics_collector.py` | `pack_accounts`, `device_numbers`, `factory_projects` | — | `scheduler.js` 00:00 UTC | живой (но падает — `account_audience_snapshots` пуста за 7д) |
| `analytics_collector_v2.py` | те же | — | manual / `triage_classifier.py` | альтернатива v1, в scheduler не вшит |
| `instagram_archiver.py` | — | INSERT `archive_tasks` | `server.js` (archiver pipeline) | живой |
| `archive_scheduler.py` | archive_tasks queue | — | `server.js` | живой |
| `social_audit.py` | разное | — | `server.js`, `run_parallel_audit.py` | живой |
| `profile_inspector.py` | разное | — | `server.js` | живой |
| `whatsapp_warmer.py` | — | INSERT `wa_accounts` | `phone_warmer.py` | живой |
| `warmer.py` | разное | — | `scheduler.js`, `farming_testbench_scheduler.js`, `adb_utils.py` | живой |
| `archiver_base.py` | const только (база) | — | `tiktok_archiver.py`, `youtube_archiver.py` | живой |
| `telegram_warmer.py` | — | INSERT `tg_accounts` | DEAD (нет caller'ов) | dead |
| `wa_register_all.py` | разное | — | DEAD | dead |
| `run_retry_audit.py` | разное | — | DEAD | dead |

Парсинг постов (`posts_parser.py` + `id_parser.py`): уже подключён только к local. Не трогаем.

## Не-цель / out of scope

- **Не дропаем** локальную таблицу `factory.contentlab_videos_upload` и схему `factory` — оставляем как архив (1537 записей могут пригодиться для отчётов). Дроп — отдельным решением позже.
- **Не правим** UI-страницы которые работают на новом контуре (Планировщик `/dashboard`, `/contracts`, `/schemes`, `/analytics` и т.д.).
- **Не блокируем** outbound на 193.124.112.222 в firewall — по решению user'а.
- **Не делаем** аудит agent workspace (`/tmp/contenthunter/agents/*/MEMORY.md` и т.п.) — это персональные памятки агентов с историческими IP-адресами, никакого активного кода там нет.

## Цель / Acceptance Criteria

После выполнения:
1. `git grep -nE "193\.124\.112\.222|49002"` в `GenGo2/validator-contenthunter` и `GenGo2/delivery-contenthunter` (=autowarm prod) возвращает **пусто** (исключения — `evidence/`, `docs/`, `*.md` истории).
2. `ss -tn dst 193.124.112.222:49002` через 24ч после деплоя — **пусто**.
3. `pm2 logs --lines 500 | grep -E "193\.|49002|connection refused.*49002"` — **пусто**.
4. Никакой код в новом сервисе не имеет ни читающих, ни пишущих обращений к remote factory.
5. SourcesPage `/sources` удалена из фронта; backend `/api/sources` удалён; cron `sync_sources.py` снят; код моста удалён.
6. Все ранее живые autowarm-collector/warmer/archiver работают на local openclaw без regression в `pm2 logs`.
7. `account_audience_snapshots` начинает наполняться после ближайшего scheduler-тика 00:00 UTC (приятный side-effect Ф2 — починим dead pipeline).

## Архитектура решения — фазы

### Ф0. Заморозка моста (5 минут, обратимо)
- Закомментировать строку `*/15 * * * * python3 /root/.openclaw/workspace-genri/validator/sync_sources.py >> /var/log/validator_sync.log 2>&1` в crontab root.
- **Smoke:** `sudo crontab -l | grep sync_sources` показывает закомментированную строку. Через 30 минут: `ss -tn dst 193.124.112.222:49002` пусто, новых записей в `factory.contentlab_videos_upload` нет.
- **Rollback:** раскомментировать строку. Поток восстановится в течение 15 минут.

### Ф1. Удаление legacy-канала валидатора
- В `GenGo2/validator-contenthunter`, ветка `feat/remove-sync-sources-20260430`, **один атомарный коммит**:
  - Удалить `validator/sync_sources.py`.
  - Удалить `backend/src/routers/sources.py`.
  - Удалить `from .routers import ... sources, ...` и `app.include_router(sources.router)` в `backend/src/main.py`.
  - Удалить `frontend/src/pages/client/SourcesPage.vue`.
  - Удалить строку route `/sources` в `frontend/src/router/index.ts`.
- **Smoke:** `pytest backend/tests` зелёный; frontend билдится; `curl /api/sources` возвращает 404; страницы `/sources` нет.
- **Rollback:** `git revert <SHA>` + восстановить cron-строку (Ф0 ручное действие на сервере, не в git).
- **Pre-condition:** Ф0 уже выполнено (cron заморожен), иначе deployed код будет периодически пытаться импортировать удалённый модуль через cron.

### Ф2. analytics_collector ×2 → local
- В `GenGo2/delivery-contenthunter` (=autowarm prod), ветка `feat/remote-factory-phaseout-20260430`:
  - **Коммит 1:** `analytics_collector.py` — переписать `get_active_accounts()`:
    - Удалить `DIST_DB_CONFIG`.
    - Заменить SQL на:
      ```sql
      SELECT
          fia.username AS account,
          fia.platform,
          vp.project   AS project,           -- было fp.api_name
          dn.device_id AS device_serial,
          rp.adb       AS adb_port,
          rp.host      AS adb_host
      FROM factory_inst_accounts fia
      JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id     -- было pack_accounts
      JOIN validator_projects vp     ON vp.id = fpa.project_id   -- было factory_projects
      JOIN factory_device_numbers dn ON dn.id = fpa.device_num_id -- было device_numbers
      JOIN raspberry_port rp         ON rp.raspberry_number = dn.raspberry
      WHERE fia.active = true
        AND LOWER(fia.platform) IN ('instagram','tiktok','youtube')
        AND dn.active = true
      ORDER BY dn.device_id, fia.username;
      ```
    - Pre-flight: `\d factory_pack_accounts`, `\d factory_device_numbers`, `\d validator_projects` сравнить колонки с remote-эквивалентом. Колонки `pack_id`, `project_id`, `device_num_id`, `raspberry_number`, `device_id`, `adb`, `host`, `active` — должны совпасть; иначе stop, отдельная миграция.
  - **Коммит 2:** `analytics_collector_v2.py` — то же самое (удалить `DB_FACTORY` + `get_factory_db()`).
- **Smoke:** `python3 analytics_collector.py --account <test_account> --dry-run` возвращает аккаунты, без TimeoutError. После деплоя — следующий scheduler-тик 00:00 UTC: `SELECT COUNT(*) FROM account_audience_snapshots WHERE snapshot_date=CURRENT_DATE` > 0.
- **Rollback:** `git revert <SHA>` отдельных коммитов; auto-push hook доставит rollback.

### Ф3. Живые autowarm-файлы → local (1 файл = 1 коммит)
В рамках той же ветки `feat/remote-factory-phaseout-20260430`, последовательность коммитов:

| # | Файл | Что меняется |
|---|---|---|
| 3 | `instagram_archiver.py` | `FACTORY` const → удалить; INSERT в `archive_tasks` через локальный pool |
| 4 | `archive_scheduler.py` | `FACTORY` const → удалить; SELECT/UPDATE через local |
| 5 | `archiver_base.py` | base `FACTORY` const убрать; убедиться что `tiktok_archiver.py` и `youtube_archiver.py` не падают (если унаследовали константу — заменить на local pool) |
| 6 | `social_audit.py` | `DIST_DB_CONFIG` → удалить; все SELECT через local |
| 7 | `profile_inspector.py` | то же |
| 8 | `whatsapp_warmer.py` | `factory_db` connect → local; INSERT в `wa_accounts` через local pool |
| 9 | `warmer.py` | `DIST_DB_CONFIG` → удалить; перевести SELECT/INSERT на local |

Для каждого файла **pre-flight**: `\d <table>` сравнение колонок ДО переписывания. Если колонок не хватает в local — отдельная миграция (или пометить файл dead).

**Smoke per-file:** entry-point dry-run где возможен (например `python3 archive_scheduler.py --dry-run`), либо вызов из родительского скрипта на тестовом устройстве. После каждого коммита — `pm2 logs autowarm --lines 100 | grep -E "193\.|49002|ConnectionError|TimeoutError"` пусто.

**Rollback:** атомарные коммиты — откатываем точечно тот файл который сломался, без задевания соседних.

### Ф4. Удаление dead кода
**Коммит 10:** удалить целиком файлы без caller'ов:
- `telegram_warmer.py`
- `wa_register_all.py`
- `run_retry_audit.py`

**Pre-flight:** `git grep -nE "telegram_warmer|wa_register_all|run_retry_audit"` в обоих репо → пусто (помимо самих себя).
**Smoke:** `pm2 status` все online после рестарта.
**Rollback:** `git revert`, файлы вернутся.

### Ф5. Финальный аудит и evidence
**Коммит 11:** `.ai-factory/evidence/2026-04-30-remote-factory-phaseout-evidence.md`:
- Вывод `git grep -nE "193\.124\.112\.222|49002"` (должен быть пусто или только в `evidence/`/`docs/`/`*.md`).
- Вывод `ss -tn dst 193.124.112.222:49002` через 24ч после деплоя.
- Список фактических SHA коммитов в обоих репо.
- Выписка из `pm2 logs --lines 500 | grep -E "193\.|49002"` (пусто).
- Подтверждение что `account_audience_snapshots` ожила (count за 24ч после Ф2).

## Маппинг таблиц remote → local (canonical)

| Remote (193.124.112.222:49002 / `factory`) | Local (`openclaw`) | Заметка |
|---|---|---|
| `pack_accounts` | `factory_pack_accounts` | Совпадают по ключевым колонкам после консолидации 2026-04-22 |
| `device_numbers` | `factory_device_numbers` | Совпадают по `device_id`/`raspberry`/`active` |
| `factory_projects` | `validator_projects` | `api_name` (remote) → `project` (local) |
| `users` | `factory_users` | После Ф0 синк прекращается; в autowarm нигде не используется |
| `archive_tasks` | `archive_tasks` (одноимённая) | Совместимы |
| `tg_accounts` | `tg_accounts` | Используется только dead `telegram_warmer` |
| `wa_accounts` | `wa_accounts` | Используется живым `whatsapp_warmer` через `phone_warmer.py` |
| `factory.contentlab_videos_upload` | `factory.contentlab_videos_upload` | После Ф1 — заархивирована, не пополняется |

## Риски

1. **Скрытое использование remote-only таблицы** — если по ходу Ф3 выяснится что какой-то из 8 файлов читает таблицу/колонку которой локально нет вовсе. Митигация: pre-flight `\d <table>` для каждого файла перед переписыванием. Решение per-case (миграция / упрощение SQL / признать dead).
2. **PM2 dump path drift** (`feedback_pm2_dump_path_drift.md`) — после коммита в prod autowarm проверить `sudo pm2 describe <app> | grep "exec cwd"` чтобы не запускался stale-код из `/home/claude-user/autowarm-testbench/`.
3. **Параллельные сессии** (`feedback_parallel_claude_sessions.md`) — `git fetch` перед стартом, atomic коммиты, не оставлять half-broken state.
4. **Cross-repo schema drift** (`feedback_cross_repo_schema_changes.md`) — после Ф1 запустить `grep -rn` в обоих репозиториях для проверки что `routers/sources.py` нигде не импортируется кроме `main.py`.
5. **Auto-push hook** (`reference_autowarm_git_hook.md`) — каждый коммит в autowarm prod main автоматом летит в `GenGo2/delivery-contenthunter`. Поэтому атомарность коммитов критична — каждый должен оставлять prod в рабочем состоянии.

## Что произойдёт у пользователей

- **Клиенты валидатора:** страница «📁 Журнал исходников» (`/sources`) исчезнет из доступных URL. По пользовательскому решению — она и так не используется в новом контуре. Прямые URL дадут 404.
- **Operators legacy-системы (если ещё есть):** их видео из master-системы перестанут попадать в кабинет валидатора через автомат. Если кому-то реально нужно — придётся загружать через Планировщик `/dashboard`.
- **Аналитика клиентского кабинета (`/analytics`):** не меняется (она и так на local — см. подтверждение в начале сессии). Может улучшиться side-effect от Ф2 (если `account_audience_snapshots` оживёт).
- **Фарминг / публикация / парсинг:** не меняется поведение, только источник данных переключается с remote на local.

## Следующий шаг

После одобрения этого spec — переход в `superpowers:writing-plans` для создания детального implementation plan с разбивкой на T0/T1/T2/... задачи и checkbox-tracking.

Реализация будет идти в трёх ветках:
- `GenGo2/validator-contenthunter` → `feat/remove-sync-sources-20260430` (Ф0+Ф1)
- `GenGo2/delivery-contenthunter` (autowarm) → `feat/remote-factory-phaseout-20260430` (Ф2+Ф3+Ф4)
- `rmbrmv/contenthunter` (этот репо) → `design/remote-factory-phaseout-20260430` (текущая ветка для дизайна и evidence; spec уже здесь, evidence добавится в Ф5)
