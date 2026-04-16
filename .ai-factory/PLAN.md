# Plan: Техдолг публикаций — guard + инфра (v2, пересобрано после проверки кода)

**Created:** 2026-04-16
**Mode:** Fast
**Branch:** `feature/aif-global-reinstall` (план здесь; фиксы — в `autowarm` и `validator` репо)

## Ревизия v1 → v2 (что изменилось после актуализации)
Первая версия плана предполагала, что 3 главных бага switcher'а (TT own-profile, YT shorts-trap, IG Edits-promo) ещё не закрыты. Проверка показала: закрыты в round 1-4 (commit `5b02c60`, 2026-04-15 14:25 UTC). При этом **54 failed задачи 15-16.04** всё равно падают — ключевая причина *целевой аккаунт не залогинен на устройстве*, switcher физически не может на него переключиться. Fix-план смещается с «переписать switcher» на «fast-fail + инфра-техдолг».

## Settings
- **Testing:** smoke-only (rerun 3 failed задач после T1; наблюдать exit-reason в event log + `pm2 logs`)
- **Logging:** verbose (`log.info` в guard: device/platform/account/source; `log.warning` на missing mapping → first-run allow; `log.error` на negative match → fail-fast)
- **Docs:** warn-only
- **Roadmap Linkage:** none

## Источники
- Память (обновлена этой сессией): `project_publish_switcher_bugs.md`.
- `pm2 logs autowarm --lines 2000 --nostream` + SQL по `publish_tasks`.
- `/tmp/autowarm_ui_dumps/publish_*_fail_*.xml` (свежие: 320 no_camera, 325 editor_timeout, 328 tt_2_not_own_profile, 333 yt_3_fg_failed).

## Приоритизация
| # | Приоритет | Задача | Влияние | Оценка |
|---|-----------|--------|---------|--------|
| T1 | **P0** | ✅ `account_packages` + `publish_tasks.done` mapping guard в `publisher.py` | Убирает ≈80% «пустой прогон → fail через 5 мин» из 54 ежедневных fail | 1-2ч |
| T2 | **P0** | ✅ Upsert mapping при `status='done'` | Guard становится строже без ручного seed | 30 мин |
| T3 | **P0** | ✅ Smoke: 5-кейсовая матрица guard'а (2 реальных + 3 синтетических) | Подтвердить что guard валит fast и не ломает legit публикации | 30 мин |
| T4 | **P1** | ✅ Анализ 3 xml-дампов (328/325/320) → 3 РАЗНЫХ round-5 бага, НЕ mapping-проблемы | Понять, нужен ли round-5 switcher-fix или guard закрывает | 30-45 мин |
| T5 | **P2** | ✅ `validator/backend/src/routers/schemes.py:_download_file` → `asyncio.to_thread` | Техдолг event-loop (background, но накапливается) | 45 мин |
| T6 | **P2** | ✅ openclaw-gateway systemd limits (MemoryMax=1500M, OOMPolicy=kill, TimeoutStopSec=20s) вместо патча vendor supervisor'а | Анти-zombie 89% CPU (случай 2026-04-16) | 1ч (нужно найти репо) |
| T7 | **P2** | ✅ Validator Vite assets: cron `find /var/www/validator/assets -mtime +7 -delete` | 4105 файлов / 72MB cruft после каждого deploy | 20 мин |

## Tasks

### Phase P0 — Fast-fail guard

#### T1. Account→device mapping guard в `run_publish_task`
- **Файл:** `/root/.openclaw/workspace-genri/autowarm/publisher.py` (`run_publish_task`, строки 4513-4559).
- **Точка вставки:** сразу после unpacking `row` (строка 4539), до `DevicePublisher(...)` (4541).
- **Query (один statement, UNION из двух источников):**
  ```sql
  WITH declarative AS (
    SELECT instagram AS acc FROM account_packages
     WHERE device_serial=%(serial)s AND (end_date IS NULL OR end_date>=CURRENT_DATE)
       AND %(platform)s='Instagram' AND instagram IS NOT NULL AND instagram<>''
    UNION ALL
    SELECT tiktok FROM account_packages
     WHERE device_serial=%(serial)s AND (end_date IS NULL OR end_date>=CURRENT_DATE)
       AND %(platform)s='TikTok' AND tiktok IS NOT NULL AND tiktok<>''
    UNION ALL
    SELECT youtube FROM account_packages
     WHERE device_serial=%(serial)s AND (end_date IS NULL OR end_date>=CURRENT_DATE)
       AND %(platform)s='YouTube' AND youtube IS NOT NULL AND youtube<>''
  ),
  history AS (
    SELECT DISTINCT account AS acc FROM publish_tasks
     WHERE device_serial=%(serial)s AND platform=%(platform)s AND status='done'
  ),
  known AS (
    SELECT acc FROM declarative WHERE acc IS NOT NULL AND acc<>''
    UNION SELECT acc FROM history WHERE acc IS NOT NULL AND acc<>''
  )
  SELECT COUNT(*) AS total, BOOL_OR(acc=%(account)s) AS matched,
         string_agg(DISTINCT acc, ', ') AS known_list
    FROM known;
  ```
- **Решающая логика (после fetchone):**
  - `total=0` → `log.warning('[guard] no mapping for <serial>/<platform>: first-run allow')`. Continue.
  - `total>0 AND matched` → `log.info('[guard] <account>@<serial>/<platform> in mapping')`. Continue.
  - `total>0 AND NOT matched` → **fail-fast:** записать event с reason=`account_not_logged_in_on_device`, UPDATE `status='failed'`, return до `DevicePublisher`.
- **Event шаблон:**
  ```json
  {"ts":"HH:MM:SS","type":"error","msg":"[guard] <acc> не в списке известных для <serial>/<platform>",
   "meta":{"reason":"account_not_logged_in_on_device","known":["..."],"source":"account_packages+publish_tasks.done"}}
  ```
- **Важно:** переиспользовать уже открытый `conn`/`cur`; не плодить подключений.
- **Логирование:** `log.info` до query и после (total/matched/known_list).

#### T2. Upsert `account_packages` при успешной публикации
- **Файл:** `publisher.py` — финализация успешного `_publish_*` (после `✅ Публикация успешна`).
- **Механика:** 
  - Столбец по платформе: `Instagram→instagram`, `TikTok→tiktok`, `YouTube→youtube`.
  - Попытаться UPDATE: `UPDATE account_packages SET <col>=%s, updated_at=NOW() WHERE device_serial=%s AND project='auto-from-publish' AND (end_date IS NULL OR end_date>=CURRENT_DATE) AND (<col> IS NULL OR <col>='' OR <col>=%s)`. Если 0 rows — INSERT новой auto-строки с этим полем.
  - Не трогать строки с legit `project` (не `auto-from-publish`) — защита от перезаписи кураторского seed'а.
- **Логирование:** `log.info('[mapping] auto-upsert <acc>@<serial>/<platform>')`.

#### T3. Smoke rerun 3 задач 2026-04-16
- **Задачи:** #328 (TT `pay.abroad.easy`), #333 (YT `pay.anywhere_now`), #325 (IG `pay.anywhere.now`).
- **Rerun:** `UPDATE publish_tasks SET status='pending', events='[]'::jsonb WHERE id IN (328,333,325)` и позволить scheduler'у подхватить или прямой вызов `python3 -m autowarm.publisher <id>` из pm2 cwd.
- **Ожидание:**
  - Если mapping пуст для `RF8YA0V5KWN/<platform>` → warning + обычный fail (5 мин) — это baseline.
  - Если mapping **накопился** от кого-то другого (declarative или history для других устройств) → fast-fail за <10с.
- **Evidence:** `evidence/smoke-mapping-guard-<ts>.md`.

**Commit 1** (после T1+T2+T3): `feat(publisher): account-device mapping guard + auto-upsert on success`

### Phase P1 — Оставшиеся switcher regressions

#### T4. Анализ xml-дампов 328/325/320
- **Файлы:**
  - `/tmp/autowarm_ui_dumps/publish_328_fail_tt_2_not_own_profile_1776316706.xml`
  - `/tmp/autowarm_ui_dumps/publish_325_instagram_editor_timeout_1776315764.xml`
  - `/tmp/autowarm_ui_dumps/publish_320_instagram_no_camera_1776315453.xml`
- **Для каждого:** извлечь видимый `text=` / `content-desc=` верхнего уровня, определить экран (camera/Reels-editor/Edits-promo/…), решить:
  - «Mapping-проблема (target не залогинен)» → guard закроет, код не трогаем.
  - «Реальный switcher regression» → отдельный `/aif-fix` план.
- **Evidence:** `evidence/xml-triage-<ts>.md`.

### Phase P2 — Инфра-техдолг

#### T5. `schemes.py:_download_file` → async
- **Файл:** `validator/backend/src/routers/schemes.py:569-580` + call sites 608/616/636/647.
- **Фикс:** переименовать текущий `_download_file` → `_download_file_sync`; добавить `async def _download_file(...): return await asyncio.to_thread(_download_file_sync, ...)`; `await` во всех 4 call sites.
- **Grep-инвариант после:** `rg -nU "async def[\s\S]*?(req_lib|requests)\.(put|get|post)" backend/src/routers/` пусто.
- **Деплой:** `pm2 restart validator`.

#### T6. openclaw-gateway supervisor kill stale PID
- **Предварительно:** найти репо supervisor'а — `rg -n "lock timeout" /opt/openclaw/ /root/.openclaw/ -g '!node_modules'` или `ps aux | grep supervisor`. Если репо недоступно — оставить как TODO-evidence и остановить.
- **Логика (если доступ есть):** при `gateway already running; lock timeout after 5000ms` → прочитать PID из lockfile → `kill 0` → `SIGTERM` + 3с wait → повторная проверка → `SIGKILL` если жив → снять lockfile → повторить запуск. Лог.
- **Acceptance:** следующий race не оставляет zombie.

#### T7. Validator Vite assets cron cleanup
- **Файл:** `/etc/cron.d/validator-assets-cleanup`:
  ```
  0 4 * * * root find /var/www/validator/assets -type f -mtime +7 -delete 2>&1 | logger -t validator-assets-cleanup
  ```
- **Проверка:** первый прогон в 04:00 UTC → `journalctl -t validator-assets-cleanup --since "-1h"`.
- **Acceptance:** через 7+ дней `find /var/www/validator/assets | wc -l` стабильно <1000.

**Commit 2** (после T5, validator repo): `fix(schemes): async download via asyncio.to_thread (no event-loop block)`
**Commit 3** (после T6, gateway repo): `fix(supervisor): kill stale gateway PID on lock-timeout`
**Commit 4** (T7): cron-файл в infra-регистр.

## Деплой-нюансы
- После правок `publisher.py`: `pm2 restart autowarm` (в памяти процесса, git push не деплоит — memory #10 revision_landmines).
- После правок `schemes.py`: `pm2 restart validator`.

## Ordering
P0 → P1 → P2. P2 независим от P0/P1 (если P0/P1 ждут пользователя — можно брать параллельно).

## Next Steps
Start T1 в autowarm репо, ветка `fix/publisher-mapping-guard`.
