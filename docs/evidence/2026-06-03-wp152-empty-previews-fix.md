# WP#152 — схемы 35-70 давали пустые превью: разбор и фикс (2026-06-03)

## ✅ SHIPPED+DEPLOYED 2026-06-03 — OpenProject #152 «Новые схемы уникализации» → Тестирование

Превью схем уникализации 35-70 (36 гибридных схем WP#152) не генерировались — в UI Тестового проекта пусто начиная с 35-й. Скриншоты от Данила: тестовый прогон 70 превью, всё с 35-й схемы пустое.

Оказалось — **две независимые причины**.

## Причина 1 (главная): гонка двух unic-воркеров на одну БД

Два воркера поллят один и тот же `unic_tasks` (БД `72.56.107.157:5432/openclaw`):

| | standalone id0 (91.98.180.103) | delivery id36 (72.56.107.157) |
|---|---|---|
| Репозиторий | GenGo2/unic-worker, `/root/unic-worker` (scp-деплой) | delivery-contenthunter, `/root/.openclaw/workspace-genri/autowarm/unic-worker` |
| `get_pending_task` | клеймит `unic` + `scheme_preview` (per-project guard + owner-guard WP#222) | клеймил **ЛЮБОЙ** pending без фильтра `task_type` |
| scheme_preview | ✅ `dispatch_task` → `process_scheme_preview` → пишет превью в **`validator_scheme_previews`** (читает UI) | ❌ обработки нет → всегда `process_task` (unic) → мис-парсит схемы (крутил только 1-4), писал в **`unic_results`** |

Когда delivery id36 выигрывал гонку за scheme_preview-таск, превью в `validator_scheme_previews` не появлялись вовсе → в UI пусто.

**Диагностика по данным** (`unic_results`): задачи 4254/4257/4280 — 64 строки, `distinct scheme_id = {1,2,3,4}`, URL `save.gengo.io/autowarm/unic/...` (= delivery S3-префикс). Лог delivery id36: `Task 4280 finished: 64 ok, 0 err` — крутил схемы 1,3,4 по кругу. Превью 1-34 в UI остались от старых прогонов, где гонку выигрывал standalone.

**Фикс:** гейт `task_type = 'unic'` в `_pending_task_query` delivery-воркера под kill-switch `UNIC_WORKER_TASK_TYPE_GUARD_ENABLED` (default ON). Зеркало WP#217. Теперь scheme_preview идёт только в standalone.
delivery-contenthunter **PR #152**.

## Причина 2: NULL-параметры схем + `.get(k, default)` не ловит None

У схем 35-70 в `unic_schemes` были NULL в `logo_scale`, `logo_alpha`, `logo_offset_x/y`, `pattern_scale_add`, `pattern_alpha`, `overlay_video_offset_x/y`, `overlay_audio_volume`, `audio_bitrate` (у 1-34 всё заполнено — заполнили только «эффектные» колонки при вставке).

Воркер делал `int(scheme.get('logo_scale', 100))`. **`dict.get(key, default)` подставляет default ТОЛЬКО при отсутствии ключа** — а из БД (и из встроенного в задачу JSON-снимка) ключ присутствует со значением `None` → `int(None)`/`float(None)`/`str(None)` роняли `generate_ffmpeg` ДО/во время ffmpeg. Тот же класс бага уже чинили для `audio_bitrate` (delivery `f31c753`), но забыли logo/pattern.

Подтверждение: `meta.scheme_errors` задачи 4253 — `int() argument ... not 'NoneType'` × 36 (ровно схемы 35-70).

**Фикс:** `scheme.get(k) or default` для всех затронутых полей.
- delivery-contenthunter **PR #151** (logo_scale/logo_alpha/pattern_scale_add/pattern_alpha/crop_offset_x|y/overlay_video_scale_w|h)
- GenGo2/unic-worker **PR #2** (то же + audio_bitrate — standalone отставал от delivery)
- **Бэкфилл данных:** NULL у схем 35-70 в прод-БД заполнены дефолтами кода (idempotent `WHERE ... IS NULL`, 36×10 колонок). Бэкфилл уже чинит на старом коде — новые таски вшивают ненулевой JSON-снимок.

## ⚠️ Урок

`scheme.get(key, default)` НЕ защищает от NULL-значения ключа из БД/JSON — нужно `scheme.get(key) or default`. Аудитить все `int()/float()/str()` над `.get(k, d)` в рендер-пайплайне.

## Деплой

- delivery: `git pull` в `/root/.openclaw/workspace-genri/autowarm` + `sudo pm2 restart 36` (PR #151 и #152).
- standalone: `scp worker.py root@91.98.180.103:/root/unic-worker/` + `pm2 restart 0` (PR #2).
- БД: бэкфилл + переименование схем 35-70 → стандарт «Схема 35»…«Схема 70».

## Тесты и верификация

- standalone: +8 (`test_null_safe_scheme_params`), регрессия 30/30.
- delivery: +6 (`test_shake_filter`, null-safe) + 3 (`test_task_type_guard`), регрессия 38/38.
- E2E: ручной прогон `generate-previews` по Тестовому проекту (10) → задача 4281 **done, 70/70 схем, 0 ошибок**; `validator_scheme_previews` проекта 10 = 70 строк (1-70), 36 из них 35-70, URL `scheme-previews/10/NN/preview.mp4`.

## Что дальше

- Verify Данилом в UI Тестового проекта (все 70 превью, включая 35-70).
- Реальные клиентские проекты: превью 35-70 тоже были затронуты — достаточно нажать «Сгенерировать превью» по проекту, теперь отработает.
- Бэклог: консолидация двух unic-воркеров (split-brain на одну БД) + NOT NULL/defaults на `unic_schemes` (превентив).

Память: `project_wp152_null_scheme_params_empty_previews`. Связь: WP#217 (task_type leak), WP#222 (double-processing).
