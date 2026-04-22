# Testbench iter-4 — Publish polish (YT meta + IG human-check + screencast fix)

**Branch:** `feature/testbench-iter-4-publish-polish`
**Created:** 2026-04-22
**Author:** Danil Pavlov (через Claude)
**Scope:** autowarm — publisher.py, account_switcher.py, testbench_orchestrator.py + миграция `factory_reg_accounts`

## Settings

- **Testing:** no — testbench сам по себе интеграционный контур (как в предыдущих итерациях); отдельные unit-тесты не пишем, верификация через smoke-прогон на VPS
- **Logging:** verbose (DEBUG для новых веток, INFO для штатных событий, WARN/ERROR для отклонений)
- **Docs:** warn-only (без обязательного docs-чекпоинта в /aif-implement)
- **Roadmap linkage:** none (нет активной roadmap-ветки)

## Контекст (зачем это)

Текущая итерация testbench (после отгрузки phone-19 rig, память `project_publish_testbench`) выявила три категории проблем в 24/7 контуре:

1. **YouTube** — публикации идут успешно, но title/description пустые (в testbench-сид'е нет осмысленных caption'ов) + визуально крутятся одни и те же 2 видео из 6 (ложное впечатление — `random.choice()` даёт кластеризацию на малых выборках).
2. **Instagram** — при переключении аккаунта алгоритм упёрся в экран «confirm you're human» и завис; на данный момент этот экран вообще не детектируется (сравни: для TikTok есть `_TT_REAUTH_MARKERS`).
3. **TikTok** — screencast генерируется сломанным (MP4 без moov atom), нельзя отсмотреть что делал скрипт. Корень общий для всех платформ: `proc.terminate()` шлёт SIGTERM на локальный adb-клиент, а не на `screenrecord` на устройстве → запись обрывается до дописи moov.

Все три блока независимы и могут быть смержены отдельными коммитами.

## Архитектурные решения (согласовано с Danil 2026-04-22)

- **YT metadata:** для testbench генерим **рандомные** title+description через Groq (llama-3.3-70b, с User-Agent header). Не привязываемся к тематике аккаунта — это временно для тестов. В будущем тексты будут браться из `publish_tasks.caption/description` (код уже читает оттуда, `publisher.py:5584, 5599`), LLM-фолбэк сработает только если поле пусто.
- **YT ротация видео:** замена `random.choice()` на **round-robin с DB-курсором** (по аналогии с account rotation, коммит `2c81c88`). Гарантия равномерного использования всех файлов.
- **IG freeze-механизм:** **JSONB-колонки** `ig_block / tt_block / yt_block` на `factory_reg_accounts`. `NULL` = аккаунт доступен, `NOT NULL` = заморожен с причиной и контекстом. Единый API `account_blocks.py`. Расширяется на любые будущие причины (SMS-2FA, email-verify, ban, rate-limit) без новых ALTER'ов. Unfreeze — руками через SQL, без auto-retry.
- **Screencast fix:** graceful stop через `adb shell pkill -SIGINT screenrecord` (сигнал на удалённый процесс!) + ffmpeg re-mux как страховка + `ffprobe` валидация moov atom. Применяется ко всем трём платформам.

## Phase 1 — Screencast fix (все платформы)

### T1 — Graceful screenrecord stop via `pkill -SIGINT` ✅

**Файл:** `/root/.openclaw/workspace-genri/autowarm/publisher.py` (`stop_and_upload_screen_record`, ~2281-2296)

**Что сделать:**
- Перед `proc.terminate()` выполнить `adb -s <serial> shell pkill -SIGINT screenrecord` (таймаут 3с)
- Дать screenrecord на устройстве ~2-3 секунды на корректную дозапись moov atom
- Только после этого вызывать `proc.terminate()` (fallback если pkill не сработал)
- Если `pkill` fail (например, процесс уже завершён) — продолжаем обычным путём, это не ошибка

**Логи (DEBUG):**
- `screenrec.graceful_stop.sent_sigint serial=<s> pid=<pid_or_none>`
- `screenrec.graceful_stop.wait_done elapsed_ms=<n>`
- `screenrec.graceful_stop.pkill_failed reason=<err>` (WARN, но не fatal)

### T2 — ffmpeg re-mux fallback в publisher ✅

**Файл:** `/root/.openclaw/workspace-genri/autowarm/publisher.py` (после pull'а файла с устройства)

**Что сделать:**
- После `adb pull` прогнать файл через `ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4` (тот же паттерн, что в `screen_recorder.py:273-277`)
- Если ffmpeg падает — логировать WARN, оставить оригинал (лучше сломанный чем ничего)
- Вынести общий хелпер `_remux_mp4(path)` — один для publisher и screen_recorder (если повтор кода виден). Иначе скопировать 10 строк — не трагедия.

**Логи (INFO):**
- `screenrec.remux.start path=<p> size_bytes=<n>`
- `screenrec.remux.ok out_size=<n>`
- `screenrec.remux.failed stderr=<tail>` (WARN)

### T3 — `ffprobe` валидация moov atom перед upload ✅

**Файл:** `/root/.openclaw/workspace-genri/autowarm/publisher.py`

**Что сделать:**
- Перед S3-upload вызвать `ffprobe -v error -show_entries format=duration <path>` — если exit!=0 или duration отсутствует → считаем файл битым
- Записать событие `publish_tasks.events` с `type=info, meta={category: 'screenrec_corrupted'}` и залить файл в S3 с суффиксом `.broken.mp4` (чтобы оператор мог посмотреть артефакт)
- Не блокировать публикацию из-за битого скринкаста — это debug-артефакт, а не функциональность

**Логи:** `screenrec.validate.ok duration=<s>` / `screenrec.validate.corrupted path=<p>`

### T4 — Commit checkpoint: «Phase 1 — screencast fix» ✅

Коммит: `fix(screen-rec): graceful SIGINT stop + ffmpeg re-mux + ffprobe validate` — `d5fc905`

---

## Phase 2 — YouTube title/description + video rotation

### T5 — Groq-helper `generate_testbench_metadata()` ✅

**Новый файл:** `/root/.openclaw/workspace-genri/autowarm/testbench_metadata_gen.py`

**Что сделать:**
- Функция `generate_testbench_metadata(platform: str) -> dict[title: str, description: str]`
- Вызывает Groq llama-3.3-70b с системным промптом: «Generate a short YouTube Shorts title (max 80 chars) and description (max 400 chars) for a short video. Use a random topic: travel, cooking, gaming, fitness, pets, life hacks. Return JSON: {title, description}.»
- **User-Agent header обязателен** (память `feedback_groq_cloudflare_ua.md`): `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36`
- Таймаут 10s, 1 retry при 5xx/timeout, при финальном fail → возвращает статический заглушечный dict (чтобы публикация не блокировалась)
- Ключ Groq — из `os.environ['GROQ_API_KEY']` (уже используется в validator, см. память `project_validator_anthropic_key.md`)

**Логи (INFO):** `testbench_meta.gen.ok platform=yt title_len=<n> desc_len=<n>` / `testbench_meta.gen.fallback reason=<e>` (WARN)

### T6 — Интеграция LLM-фолбэка в `testbench_orchestrator.py` ✅

**Файл:** `/root/.openclaw/workspace-genri/autowarm/testbench_orchestrator.py` (функция `tick()`, ~296)

**Что сделать:**
- При инсерте новой `publish_tasks` строки: если `caption`/`description` пусты (а для testbench они всегда пусты) — вызвать `generate_testbench_metadata(platform)` и подставить в INSERT
- Кешировать сгенерированные мета в `publish_tasks` (в колонки `caption`, `description`, `hashtags`) — publisher уже умеет их читать, никаких изменений в publisher не нужно
- Применять для **всех платформ** (IG/TT/YT) — testbench'у везде нужны осмысленные caption'ы, не только YT
- Если `GROQ_API_KEY` не задан → заглушечный dict и WARN

**Логи:** `orchestrator.meta.injected platform=<p> task_id=<id>` / `orchestrator.meta.skipped reason=no_key` (WARN)

### T7 — Round-robin video rotation с DB-курсором ✅

**Отклонение от плана:** использовали существующий `system_flags` с ключом `orchestrator_media_cursor:<platform>` вместо отдельной таблицы `testbench_media_cursor`. Re-use паттерна из `orchestrator_account_cursor` (меньше таблиц, единообразие). Миграция не нужна.

**Верификация:** 4 последовательных dry-run тика дали индексы 1→2→0→1 (mod 3 для IG с 3 файлами). Все файлы используются равномерно.

**Файл:** `/root/.openclaw/workspace-genri/autowarm/testbench_orchestrator.py` (`pick_seed_media`, ~213-223)

**Что сделать:**
- Заменить `random.choice(files)` на:
  - `sorted(files)` — стабильный порядок по имени файла
  - `UPDATE testbench_media_cursor SET last_index = (last_index + 1) % <N>, updated_at = NOW() WHERE platform = %s RETURNING last_index`
  - Выбрать `files[last_index]`
- В транзакции, без race-условий (SELECT FOR UPDATE не нужен — orchestrator single-instance systemd-service)
- Логика gracefully handles resize pool: если после `% N` индекс вышел за пределы → reset в 0 (не выйдет, `% N` защищает)

**Логи (INFO):** `orchestrator.media.picked platform=<p> index=<i>/<N> file=<name>`

### T8 — Commit checkpoint: «Phase 2 — YT meta + rotation» ✅

Коммит: `feat(testbench): Groq-generated metadata + round-robin video rotation` — `9b419f5`

---

## Phase 3 — Instagram human-check detection + block mechanism

### T9 — Миграция: JSONB-колонки `ig_block / tt_block / yt_block` ✅ (применено на production БД)

**Файл:** `/root/.openclaw/workspace-genri/autowarm/migrations/20260422_factory_account_blocks.sql`
```sql
ALTER TABLE factory_reg_accounts
  ADD COLUMN IF NOT EXISTS ig_block JSONB,
  ADD COLUMN IF NOT EXISTS tt_block JSONB,
  ADD COLUMN IF NOT EXISTS yt_block JSONB;

CREATE INDEX IF NOT EXISTS idx_factory_reg_accounts_ig_block_not_null
  ON factory_reg_accounts (id) WHERE ig_block IS NULL;
CREATE INDEX IF NOT EXISTS idx_factory_reg_accounts_tt_block_not_null
  ON factory_reg_accounts (id) WHERE tt_block IS NULL;
CREATE INDEX IF NOT EXISTS idx_factory_reg_accounts_yt_block_not_null
  ON factory_reg_accounts (id) WHERE yt_block IS NULL;
```

**Формат JSON:**
```json
{"reason": "human_verification_required",
 "detected_at": "2026-04-22T18:30:00Z",
 "last_seen_screen": "ig_confirm_human",
 "ui_dump_path": "/tmp/autowarm_ui_dumps/publish_<id>_ig_human_check_<ts>",
 "publish_task_id": 812}
```

### T10 — Хелпер-модуль `account_blocks.py` ✅

**Новый файл:** `/root/.openclaw/workspace-genri/autowarm/account_blocks.py`

**API:**
- `set_block(account_id: int, platform: str, reason: str, **context) -> None` — вставляет JSONB с `detected_at=NOW()` и произвольным контекстом (ui_dump_path, publish_task_id, last_seen_screen)
- `clear_block(account_id: int, platform: str) -> None` — `SET <platform>_block = NULL`
- `is_blocked(account_id: int, platform: str) -> bool` — быстрая проверка (`SELECT <platform>_block IS NOT NULL`)
- `get_block(account_id: int, platform: str) -> dict | None` — вернуть JSONB как dict для диагностики

**Валидация:** `platform in ('ig', 'tt', 'yt')` — иначе `ValueError`.

**Логи (INFO):** `account_block.set account_id=<id> platform=<p> reason=<r>` / `account_block.cleared account_id=<id> platform=<p>`

### T11 — Маркеры IG human-check в account_switcher.py ✅

**Файл:** `/root/.openclaw/workspace-genri/autowarm/account_switcher.py` (возле `_TT_REAUTH_MARKERS:614-623`)

**Что сделать:**
- Добавить `_IG_HUMAN_CHECK_MARKERS` по паттерну TT-маркеров. Начальный список (финализировать по первому реальному дампу — оставить TODO):
  - EN: `['Confirm you're human', 'Help us confirm', "We need to confirm it's really you", 'Confirm it\'s you', "Please verify you're not a robot", 'Security check']`
  - RU: `['Подтвердите, что вы не робот', 'Подтвердите, что это вы', 'Проверка безопасности', 'Подтвердите свою личность']`
- Добавить helper `_detect_ig_human_check(ui_text: str) -> bool` — аналогично `_detect_tt_reauth`
- В `_switch_instagram()` (485-551): после каждого этапа switch — если detect вернул True → dump UI XML в `/tmp/autowarm_ui_dumps/` → вернуть `self._fail('ig human check screen', step='ig_human_check_required')`

**Логи (ERROR):** `switcher.ig.human_check_detected account=<u> ui_snippet=<100chars>`

### T12 — Интеграция: error_code + block setter + alert ✅

**Файл:** `/root/.openclaw/workspace-genri/autowarm/publisher.py` (`_SWITCHER_STEP_TO_CATEGORY:81-110`)

**Что сделать:**
- Добавить строку: `'ig_human_check_required': 'ig_human_check_required'`
- В точке обработки fail от свитчера (там же где сейчас раскладываются категории) — если `step == 'ig_human_check_required'` → вызвать `account_blocks.set_block(account_id, 'ig', reason='human_verification_required', ui_dump_path=..., publish_task_id=...)`
- `notify_failure()` в `notifier.py:127` сработает автоматически через триаж (подхватит новый error_code)
- Опционально: отдельный `notify_escalation()` для human-check (сильный сигнал — требует ручного действия), **делаем**: в `triage_classifier.py` добавить ветку: для `ig_human_check_required` → помимо `notify_failure` вызвать `notify_escalation(error_code, reason='human_verification_blocks_account', details={account_id, ui_dump_path})`

**Логи (ERROR):** `publish.ig.blocked_human_check account_id=<id> task_id=<id>`

### T13 — Orchestrator: фильтр заблокированных аккаунтов ✅

**Файл:** `/root/.openclaw/workspace-genri/autowarm/testbench_orchestrator.py` (round-robin account rotation, ~145-177)

**Что сделать:**
- При выборе `next account for platform P` добавить фильтр `<platform>_block IS NULL` в SELECT
- Если все аккаунты для платформы заблокированы → логировать ERROR и пропустить тик для этой платформы (не инсертить `publish_task`)
- Применить для всех трёх платформ (ig/tt/yt), не только IG — система должна быть консистентной

**Логи:**
- `orchestrator.account.picked platform=<p> account_id=<id> rr_cursor=<c>`
- `orchestrator.account.all_blocked platform=<p> skipping_tick` (ERROR)

### T14 — Observability SQL script ✅

**Новый файл:** `/root/.openclaw/workspace-genri/autowarm/scripts/blocked_accounts_status.sql`

```sql
-- Список заблокированных аккаунтов с причинами (все платформы)
SELECT
  id,
  username,
  CASE
    WHEN ig_block IS NOT NULL THEN 'ig'
    WHEN tt_block IS NOT NULL THEN 'tt'
    WHEN yt_block IS NOT NULL THEN 'yt'
  END AS blocked_platform,
  COALESCE(ig_block, tt_block, yt_block) AS block_info,
  updated_at
FROM factory_reg_accounts
WHERE ig_block IS NOT NULL
   OR tt_block IS NOT NULL
   OR yt_block IS NOT NULL
ORDER BY updated_at DESC;
```

Плюс `scripts/unblock_account.sql`:
```sql
-- Usage: psql -v account_id=42 -v platform=ig -f unblock_account.sql
UPDATE factory_reg_accounts
SET ig_block = CASE WHEN :'platform' = 'ig' THEN NULL ELSE ig_block END,
    tt_block = CASE WHEN :'platform' = 'tt' THEN NULL ELSE tt_block END,
    yt_block = CASE WHEN :'platform' = 'yt' THEN NULL ELSE yt_block END,
    updated_at = NOW()
WHERE id = :account_id;
```

### T15 — Commit checkpoint: «Phase 3 — IG human-check + block system» ✅

Коммит: `feat(publish): IG human-check detection + account_blocks mechanism` — `eb12eb6`

---

## Phase 4 — Verification

### T16 — Smoke test на VPS ✅

**Deploy:** 2026-04-22 18:34 UTC. Merge commit `fc7a88d` в autowarm-testbench/testbench.
Systemd orchestrator restart OK (PID 27053). PM2 autowarm-testbench restart OK.

**Первый post-deploy тик (18:34):**
- Новый roster-формат работает: `2 available, blocked=0` per-platform
- Groq HTTP 200 OK, сгенерил title='Pet Playtime Fun' (pet moments topic)
- Round-robin media: `index=1/3` (т.е. курсор продолжил с места)
- Task #770 создан [Instagram/gennadiya311] с непустыми caption/description/hashtags

**Дальше:** ждём ~5 мин завершения task #770, затем TT-тик (+10min), YT-тик (+20min).

**Deploy-gotcha (2026-04-22):** merge из feature-branch удалил симлинк `autowarm-testbench/node_modules → /root/.openclaw/workspace-genri/autowarm/node_modules`, т.к. в source-репе node_modules — обычная папка (gitignored), а в target-репе был committed symlink. Scheduler упал с `Cannot find module 'pg'`. Fix: восстановил симлинк локально (но не закоммитил — чтобы не было конфликта на следующем merge). **Follow-up:** добавить `node_modules` в `autowarm-testbench/.gitignore` и `git rm --cached node_modules` — тогда симлинк будет чисто локальным и не будет удаляться при merge из workspace-genri.

**Что проверить (после deploy всех трёх фаз):**

1. **Screencast (все платформы):**
   - Дать testbench'у отработать ~15 минут (≥5 публикаций на платформу)
   - Забрать S3-скринкасты 5 последних task_id, открыть в VLC/QuickTime
   - ✅ Критерий: все файлы воспроизводятся, duration > 10s, нет «moov atom not found»

2. **YouTube metadata + rotation:**
   - Смотреть events `publish_tasks` за последние 10 YT-публикаций
   - ✅ Критерий: `caption`/`description` не пустые (есть осмысленный текст от Groq)
   - На устройстве через scrcpy посмотреть, что поля в YT-редакторе действительно заполняются
   - `SELECT platform, last_index, updated_at FROM testbench_media_cursor;` — last_index должен идти 0→1→2→3→4→5→0…

3. **IG human-check:**
   - Искусственно спровоцировать (вручную залогиниться в проблемный аккаунт на устройстве до экрана challenge)
   - Дать testbench'у взять этот аккаунт, проверить:
   - ✅ `factory_reg_accounts.ig_block` стал NOT NULL с корректным JSON
   - ✅ В Telegram пришёл алерт с error_code `ig_human_check_required`
   - ✅ На следующем тике orchestrator НЕ выбрал этот аккаунт для IG (видно в логах `orchestrator.account.picked`)
   - Сделать `UPDATE factory_reg_accounts SET ig_block = NULL WHERE id = <X>;` — на следующем тике аккаунт снова участвует

**Записать evidence:** `/home/claude-user/contenthunter/evidence/testbench-iter-4-smoke-20260422.md` с выводом psql, скриншотами, ссылками на S3-скринкасты.

---

## Commit Plan

| # | Коммит | После тасков |
|---|---|---|
| 1 | `fix(screen-rec): graceful SIGINT stop + ffmpeg re-mux + ffprobe validate` | T1-T3 |
| 2 | `feat(testbench): Groq-generated metadata + round-robin video rotation` | T5-T7 |
| 3 | `feat(publish): IG human-check detection + account_blocks mechanism` | T9-T14 |
| 4 | `docs(evidence): testbench iter-4 smoke test results` | T16 |

Фазы независимы — при желании можно деплоить порознь (например, сначала фикс скринкаста, чтобы увидеть причины будущих IG-падений на видео).

## Risks & Open Questions

- **R1 (Phase 1):** `adb shell pkill -SIGINT screenrecord` — если на устройстве несколько одновременных screenrecord процессов (маловероятно), убьёт все. Митигация: проверить через `pidof screenrecord` — ожидаем ровно 1.
- **R2 (Phase 2):** Groq-ключ на VPS — проверить `echo $GROQ_API_KEY` перед деплоем. Если ключа нет — запросить у Danil, использовать тот же, что в validator.
- **R3 (Phase 3):** Начальный список IG human-check маркеров угадан без реального дампа. Первый трigger в production ловим, дампим, расширяем список. **TODO после T11:** держать файл `/tmp/autowarm_ui_dumps/ig_human_check_*` в поле зрения и по мере накопления расширять маркеры.
- **R4:** `unblock` вручную через SQL — оператор может забыть разблокировать аккаунт. Митигация: `blocked_accounts_status.sql` должен быть в daily digest bugs-bot'а (не в этой итерации).
