<<<<<<< HEAD
<<<<<<< HEAD
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
=======
# Plan: Публикация контента — round-6 (IG flow + guard block-on-NULL + TT anti-markers)
=======
# Plan: Fix `ig_camera_open_failed` regression (aneco/anecole кластер)
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)

**Created:** 2026-04-18
**Mode:** Fast
**Follow-up от:** `.ai-factory/evidence/round-6-post-deploy-analysis-20260418.md` (раздел «⚠️ Новая regression»)
**Репо с кодом:** `GenGo2/delivery-contenthunter` (`/root/.openclaw/workspace-genri/autowarm/`)
**Репо с evidence/планом:** contenthunter (текущий)

## Settings

| | |
|---|---|
| Testing | **yes** — юнит-тесты на детекторы + recovery-пути (по образцу `tests/test_publisher_ig_editor.py`) |
| Logging | **verbose** — DEBUG-логи на каждом детекторе + отдельные event-категории для триажа |
| Docs | **warn-only** — баг-фикс в боевом модуле, docs-drift маловероятен |
| Roadmap linkage | skipped — регрессия, не milestone |

## Контекст регрессии (6 fails / 48h)

6 задач на 3 устройствах aneco/anecole кластера:

| task_id | device | account | date |
|---|---|---|---|
| 389 | RF8Y90LBZPJ | anecole_education | 2026-04-18 |
| 388 | RF8Y80ZT14T | aneco.le_edu | 2026-04-18 |
| 382 | RF8Y90LBX3L | anecole.online | 2026-04-18 |
| 373 | RF8Y90LBX3L | anecole.online | 2026-04-18 |
| 370 | RF8Y80ZT14T | aneco.le_edu | 2026-04-18 |
| 372 | RF8Y90LBZPJ | anecole_education | 2026-04-18 |

`RF8Y90LBX3L/anecole.online` и `RF8Y90LBZPJ/anecole_education` имели успешные done'ы **2026-04-16** → истинная регрессия, не first-run.

<<<<<<< HEAD
### ⚠️ Новая регрессия (не в скоупе, follow-up)
**`ig_camera_open_failed`** — 6 событий за 48h на aneco/anecole кластере (RF8Y80ZT14T, RF8Y90LBX3L, RF8Y90LBZPJ). Падает **до** editor-loop (в `_open_instagram_camera()` publisher.py:2050). RF8Y90LBX3L имел done 2 дня назад — регрессия. Требует отдельного `/aif-fix`.
>>>>>>> 9cf184661 (docs(evidence): round-6 seed (17 devices) + post-deploy analysis)
=======
### Root cause — по XML-дампам из `/tmp/autowarm_ui_dumps/`
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)

Две разные конечные стадии (обе падают в общем catch-all `ig_camera_open_failed` в `publisher.py:2050`):

<<<<<<< HEAD
<<<<<<< HEAD
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
=======
- `seed-round-6-20260418.sql` — idempotent SQL seed + rollback
- `seed-round-6-20260418.log` — вывод psql при выполнении
- `round-6-post-deploy-analysis-20260418.md` — полный анализ T7

## Rollback

Seed reverse'ится одной командой:
```sql
DELETE FROM account_packages WHERE project='manual-seed-round-6-20260418';
=======
**Экран A — Highlights empty-state** (4/6: #389, #382, #373, #372)
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)
```
action_bar_title  = "Добавление в актуальное"
text              = "Дополните свою историю"
text              = "Сохраняйте свои истории в архиве после того, как они исчезают…"
resource-id       = com.instagram.android:id/empty_state_view_root
resource-id       = com.instagram.android:id/empty_state_headline_component
resource-id       = com.instagram.android:id/igds_headline_emphasized_headline
```
IG приземлился в архив Highlights (пустой), а не в Reels-камеру. Новый регресс — не покрыт handler'ами round-5/6 (T1/T2/T7 в publisher.py:2020-2100).

**Экран B — gallery_picker-only** (2/6: #388, #370)
```
resource-id       = com.instagram.android:id/gallery_picker_view
resource-id       = com.instagram.android:id/feed_gallery_app_bar
resource-id       = com.instagram.android:id/gallery_folder_menu_container
content-desc      = "Выбрано Миниат.юра видео создано 18 апреля 2026 г. …"
content-desc      = "Отмена"
```
Тот же паттерн что исторический #320 (2026-04-16 triage). **T2 gallery-picker fallback** (commit `8b7ca95`, publisher.py:2377, helper :813) **есть** в коде, но срабатывает уже ПОСЛЕ камера-wait-loop (т.е. после того как `ig_camera_open_failed` уже залогирован). Для текущей регрессии fallback фактически не триггерится в нужной точке.

### Диагноз

Оба экрана — симптом того же первичного сбоя:
- Либо `instagram://reels-camera` deeplink срабатывает некорректно когда IG уже foreground (в последнем known state: Stories/Highlights или Gallery)
- Либо bottomsheet-fallback (publisher.py:1988-1993) ведёт к home-экрану, но "+" тап (top-left, coords 50,160 из FIX-IG-stuck-on-profile) на profile-screen иногда открывает Highlights/Story-editing вместо Reels bottomsheet

## Tasks

- [x] T1 — Детектор+recovery для Highlights empty-state (publisher.py)
- [x] T2 — Gallery-picker detector в camera-wait loop (publisher.py)
- [x] T3 — Unified unknown-screen recovery после 3 попыток (publisher.py)
- [x] T4 — Расширенный fail meta (detected_state + ui_snippet + ui_dumps)
- [x] T5 — Юнит-тесты на детекторы и recovery-ветки (14 passed)
- [x] T6 — Deploy + pm2 restart + scheduler smoke (evidence: `ig-camera-fix-deploy-20260418.md`)
- [ ] T7 — Post-deploy 24h verification (через 24ч, 2026-04-19)

### T1 — Детектор+recovery для экрана «Добавление в актуальное» (Highlights empty-state)

**Что:**
- Добавить helper `_is_ig_highlights_empty_state(ui: str) -> bool` в `publisher.py` (по образцу существующих `_dismiss_ig_edits_promo`).
  Маркеры (all-match): `'empty_state_view_root'` + (`'Добавление в актуальное'` or `'Дополните свою историю'`).
- Встроить в camera-wait loop (publisher.py:2020-2050) **после** `_dismiss_ig_edits_promo()` и **до** check на `'Редактировать профиль'`:
  ```
  if self._is_ig_highlights_empty_state(ui):
      log.warning(f'[FIX: IG-highlights-empty-state] попытка {attempt} → reset IG')
      self.log_event('info', 'IG: экран Highlights empty-state',
                     meta={'category': 'ig_highlights_empty_state_seen',
                           'platform': self.platform, 'step': 'open_camera',
                           'attempt': attempt})
      # Recovery: force-stop + am start MainTabActivity (чистое переоткрытие)
      self.adb(f'am force-stop {package}')
      time.sleep(1)
      self.ensure_unlocked()
      self.adb(f'am start -n {package}/.activity.MainTabActivity')
      time.sleep(5)
      # После reset — повторяем bottomsheet path (tap "+" → Reels)
      # (логика вынесена в helper `_reopen_ig_reels_via_home()`)
      self._reopen_ig_reels_via_home()
      continue
  ```
- Helper `_reopen_ig_reels_via_home()`: dump_ui → если видим home feed (маркеры `home_tab` / bottom-nav «Главная»/«Home»), тапаем «+» через `tap_element(['Создать','Create','Новая публикация'], clickable_only=True)` → опционально fallback на известные coords профиля.

**Логирование (verbose):**
- `DEBUG` на каждый dump_ui в recovery
- `log_event('info', ...)` с категорией `ig_highlights_empty_state_seen` на первую детекцию (по которой мы сможем трекать в live-логах, работает ли фикс)

**Файлы:**
- `publisher.py` (автоwarm-репо) — helpers + встройка в loop
- Тест — отдельно в T5

### T2 — Встроить gallery-picker-detector в camera-wait loop

**Что:**
- Существующий helper для gallery-picker (publisher.py:~813, shipped в 8b7ca95) срабатывает позже — в editor-loop. Для текущей регрессии `gallery_picker_view` виден **в camera-wait loop**, т.е. до editor.
- Добавить в тот же loop (сразу после T1-чека) проверку:
  ```
  if 'gallery_picker_view' in ui or 'gallery_coordinator' in ui:
      log.warning(f'[FIX: IG-gallery-picker-in-camera-loop] попытка {attempt}')
      self.log_event('info', 'IG: gallery picker вместо camera',
                     meta={'category': 'ig_gallery_picker_in_camera_loop',
                           'platform': self.platform, 'step': 'open_camera',
                           'attempt': attempt})
      # Стратегия: tap "Отмена" (action_bar_cancel) → вернёмся в feed → повтор bottomsheet path
      if self.tap_element(ui, ['Отмена', 'Cancel'], clickable_only=True):
          time.sleep(2)
          self._reopen_ig_reels_via_home()
      continue
  ```
- Категория `ig_gallery_picker_in_camera_loop` — отличается от существующей `gallery_shown_no_camera_option` (та ловит gallery в editor-loop, после успешной camera-open) чтобы не путать при триаже.

**Файлы:**
- `publisher.py` — встройка в loop publisher.py:2020-2050

### T3 — Unified «unknown-screen» recovery после 3 неудачных попыток

**Что:**
- Текущий loop крутится 6 × 2s = 12s всё равно в unknown state. Добавить: если `attempt >= 3` и **ни один** детектор не сработал, и ни один из camera-маркеров не найден — принудительный reset (force-stop + MainTabActivity) до остатка попыток.
- Чтобы не зациклиться: флаг `tried_full_reset` — максимум **один** full-reset за весь вызов `publish_instagram_reel`.
- Дополнительно собираем `_save_debug_artifacts('instagram_pre_reset')` на момент reset — чтобы после deploy видеть, в каком новом состоянии IG приземляется.

**Логирование:**
- `log_event('warn', ...)` с категорией `ig_camera_open_reset_attempted` + дампом UI snippet в meta (первые 200 символов ui)

**Файлы:**
- `publisher.py` — одна модификация в camera-wait loop

### T4 — Расширенный fail meta для post-mortem

**Что:**
В `log_event('error', 'Instagram: не удалось открыть камеру', meta=…)` (publisher.py:2050) добавить в `meta`:
- `ui_snippet` — последние 300 символов `ui` с последней попытки
- `detected_state` — одно из `{'highlights_empty_state','gallery_picker','profile_stuck','unknown'}` — заполняется на основе тех же детекторов что в T1/T2/existing profile-stuck-fix
- Список URL-ов собранных `_collected_ui_dumps` (уже есть, но убедиться что прикрепляется)

**Файлы:**
- `publisher.py` — блок `if not camera_ready` (строка ~2045-2055)

### T5 — Юнит-тесты на детекторы и recovery-ветки

**Что:**
Новый файл `tests/test_publisher_ig_camera_recovery.py`:
- `test_is_highlights_empty_state_true` — fixture = содержимое `/tmp/autowarm_ui_dumps/publish_389_instagram_no_camera_1776490674.xml` (скопировать в `tests/fixtures/ig_ui_dumps/`)
- `test_is_highlights_empty_state_false_on_camera_screen` — negative sample (собрать из любого successful xml)
- `test_gallery_picker_in_camera_loop_detection` — fixture = `publish_388_instagram_no_camera_*.xml`
- `test_reopen_ig_reels_via_home_taps_plus_button` — mock `self.adb`, `self.dump_ui`, `self.tap_element`, assert вызова с `['Создать','Create','Новая публикация']`
- `test_camera_loop_triggers_full_reset_after_3_failed_attempts` — mock dump_ui → возвращает unknown screen 3 раза, assert вызова `am force-stop`

**Логирование:**
В тестах проверяем что `log_event` был вызван с корректной `category` (mock `self.log_event` → assert call_args).

**Файлы:**
- `tests/test_publisher_ig_camera_recovery.py` (новый)
- `tests/fixtures/ig_ui_dumps/publish_389_highlights_empty.xml` (скопировать из /tmp/)
- `tests/fixtures/ig_ui_dumps/publish_388_gallery_picker.xml` (скопировать из /tmp/)

### T6 — Deploy + live smoke

**Что:**
1. Коммит автоwarm изменений в `GenGo2/delivery-contenthunter` (conventional: `fix(publisher): recover IG camera open on highlights/gallery screens`).
2. `pm2 restart autowarm` на fra-1-vm-y49r.
3. Проверить `pm2 logs autowarm --lines 50` — pm2 поднялся без ошибок импорта.
4. Re-run одной из failed tasks: `#389 RF8Y90LBZPJ anecole_education` или `#382 RF8Y90LBX3L anecole.online` (через scheduler rerun или вручную `python publisher.py --task-id 389`).
5. Мониторить event-категории 1h: должно появиться `ig_highlights_empty_state_seen` (с recovery), но **не** `ig_camera_open_failed` с тем же detected_state.

**Evidence:**
- `/home/claude-user/contenthunter/.ai-factory/evidence/ig-camera-fix-smoke-20260418.md` — snippet логов + query результат.

### T7 — Post-deploy verification (24h)

**Что:**
Через 24ч проверить в task_events:
```sql
SELECT meta->>'category' AS cat, meta->>'detected_state' AS state, COUNT(*)
 FROM task_events
WHERE created_at > NOW() - INTERVAL '24 hours'
  AND meta->>'category' LIKE 'ig_camera_%' OR meta->>'category' LIKE 'ig_highlights_%' OR meta->>'category' LIKE 'ig_gallery_picker_%'
GROUP BY cat, state
ORDER BY COUNT(*) DESC;
```
**Success criteria:**
- `ig_camera_open_failed` на aneco/anecole кластере: < 1/24h (с 6/48h → практически 0)
- `ig_highlights_empty_state_seen` с последующим успехом задачи ≥ 3 events (доказательство что recovery работает)
- Нет новых `ig_camera_open_reset_attempted` без последующего успеха (признак бесконечного reset-loop'а)

**Evidence:**
- `.ai-factory/evidence/ig-camera-fix-24h-20260419.md`

## Commit plan

Два commit'а в автоwarm-репо + один evidence-commit в contenthunter.

**Checkpoint 1 — после T1+T2+T3+T4 (core fix):**
```
fix(publisher): recover IG camera open on highlights/gallery screens

- detect highlights empty-state and full-reset IG (fixes anecole cluster regression)
- detect gallery_picker in camera-wait loop (was handled only in editor-loop)
- single full-reset fallback after 3 unknown-screen attempts
- enriched fail meta with detected_state + ui_snippet
- new event categories: ig_highlights_empty_state_seen, ig_gallery_picker_in_camera_loop, ig_camera_open_reset_attempted
```
<<<<<<< HEAD
>>>>>>> 9cf184661 (docs(evidence): round-6 seed (17 devices) + post-deploy analysis)
=======

**Checkpoint 2 — после T5 (тесты):**
```
test(publisher): unit coverage for IG camera recovery paths

fixtures from live xml dumps (publish_389/388), covers highlights detection,
gallery-picker-in-camera-loop detection, and full-reset-after-3-attempts branch.
```

**Checkpoint 3 — evidence в contenthunter (после T6+T7):**
```
docs(evidence): ig_camera_open_failed fix — deploy smoke + 24h verification
```

## Rollback

Если после deploy появятся новые fail-категории или количество `ig_camera_open_failed` вырастет:
```bash
cd /root/.openclaw/workspace-genri/autowarm/
git revert <fix-commit-hash>
pm2 restart autowarm
```
Риск низкий — изменения аддитивные (новые ветки в loop), старые handler'ы не трогаем.

## Next step

После review этого плана — `/aif-implement` запустит задачи T1–T7 последовательно.
>>>>>>> 04d176b47 (docs(evidence): ig_camera_open_failed fix — T1-T6 deploy evidence)
