# Publish: задачи зависают в `awaiting_url` — defense-in-depth URL capture + новый terminal-статус — design

**Дата:** 2026-05-18
**OpenProject:** [WP #86](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/86)
**Branch (worktree):** `worktree-wp86-awaiting-url-stuck`
**Затрагиваемые файлы (по PR):**

| PR | Файл / артефакт | Изменения |
|---|---|---|
| PR1 | `server.js` — `checkProcessingTasks`, `syncQueueStatuses`, `resetZombieTasks`, status-фильтры | LIMIT 30→100, ORDER BY started_at→updated_at, NULL-zombie COALESCE, `url_capture_attempts++` ветка, `published_no_url` → pq.status='done' sync |
| PR1 | `public/index.html` lines **6700 (statusLabels), 7211 (factory map), 10727 (publish_tasks badge), 10881 (queue badge)** + status-filter dropdown line **2434** | Новое значение `published_no_url` во **всех 5 местах** (badge label «✅ Без URL», цвет yellow), фильтр-option |
| PR1 | `migrations/20260518_publish_tasks_url_capture_fields.sql` + `__rollback.sql` | ALTER TABLE + partial index |
| PR1 (deploy step) | `migrations/20260518_wp86_retroactive_cleanup.sql` + `__rollback.sql` | UPDATE awaiting_url → published_no_url для old stuck |
| PR2 | `publisher_base.py` — новые helpers | `_capture_via_notifications(platform, account)`, `_capture_via_share_loop(waves=3, gap=15s)` |
| PR2 | `publisher_tiktok.py:2472+`, `publisher_instagram.py:3322+`, `publisher_youtube.py:385+` | Заменить single `_auto_get_*_url(45)` на `_capture_via_notifications → _capture_via_share_loop` оркестратор |
| PR3 | `publisher_base.py` — pre-snapshot helper | До `publish_*`: snapshot top-5 ids → `pre_publish_video_ids` JSONB |
| PR3 | `server.js` — новые `scrapeAllVideosViaApi` (YT), `scrapeAllVideosDiff` (wrapper) | A3: YT API path с fallback; A5: diff matching против pre-snapshot |
| PR3 | `analytics_collector.py` (read-only reuse) | Порт `youtube_api_get_channel_id` + `youtube_api_get_videos` логики в JS-equivalent для server.js (или через python child_process — выбрать в plan'е) |

---

## Проблема

После успешной публикации задача переходит в `awaiting_url`. Бот возвращает `True` из `publish_<platform>`, но `post_url` остаётся profile fallback (`https://www.tiktok.com/@<acct>`, без `/video/<id>`). Сервер-cron `url-poller` (server.js:6844, каждые 2 мин) должен через `yt-dlp` найти видео в свежей ленте и сделать `_update_post_url_final` → status `done`. На практике задачи зависают часами / днями и доходят только до 48ч-timeout → `failed` (псевдо-провал — публикация-то состоялась).

**Снимок 2026-05-18 14:02 UTC — 45 stuck задач:**

| Platform | Count | Oldest |
|---|---|---|
| Instagram | 27 | 9.0 ч |
| TikTok | 12 | 8.8 ч |
| YouTube | 6 | 4.9 ч |

**За последние 24 ч** на всех платформах **0 задач** закрылись `done` с profile URL — текущий код вообще не имеет terminal-перехода для «опубликовано, но specific-URL не получен». Только два исхода: либо poller достал `/video/<id>` (или эквивалент) → `done`, либо 48ч timeout → `failed` (искажает статистику).

## Корневые причины

### RC #1 — нет terminal-состояния для «published без specific URL»

Цикл `awaiting_url` бесконечен пока поллер не достанет specific URL или не сработает 48ч-timeout. Profile URL приемлем для UI («✅ опубликовано»), но `_save_post_url(profile_url, final=False)` ставит `awaiting_url`, а `_save_post_url(profile_url, final=True)` поставил бы `done` с врущим semantics (мы соврали бы что URL final). Третьего варианта нет.

### RC #2 — capture-механика однопроходная

Бот вызывает `_auto_get_*_url(wait_secs=45)` ровно один раз (`publisher_tiktok.py:2472` и эквиваленты в IG/YT publishers). Если share-sheet в TT за 45с не открылся / в IG copy-link не сработал — повторов нет, бот завершается, девайс отпускается. Поллер потом 2 мин/раз дёргает yt-dlp снаружи, что часто бьётся в TT-блокировки и shadowban'ы. Никаких альтернатив (notification scrape, API, diff) нет.

### RC #3 — поллер сам сломан

`server.js:6846` query:
```sql
SELECT ... FROM publish_tasks
WHERE status IN ('processing', 'awaiting_url')
  AND updated_at < NOW() - INTERVAL '1 minute'
ORDER BY started_at ASC
LIMIT 30
```

Три бага в одной query:

1. **`LIMIT 30` starvation.** При 45+ stuck первые 30 (oldest) забивают слоты, остальные ждут пока старые отвалятся 48ч-timeout'ом. Snapshot: 30 задач имеют `updated_at < 5min` (поллер их крутит), 13 — `updated_at > 3h` (голодают). Из голодающих 12 — TT задачи 7274/7342-7360 (post-WP82 re-queue), новейшие.
2. **`ORDER BY started_at ASC`.** Когда yt-dlp возвращает 0 видео для аккаунта, тот же набор oldest-tasks гонится снова и снова. Новые задачи никогда не доходят до проверки.
3. **`NULL started_at` zombies.** 5 задач в текущем снапшоте (`#961` IG @makiavelli485, 4× YT @Ivana-o3j) имеют `started_at=NULL`. Логика 48ч-timeout (`server.js:6862`) использует `ageHours = started_at ? ... : 0` — для NULL получает 0, никогда не выходит по timeout, торчит вечно.

### RC #4 — нет per-task бюджета попыток

Поллер не считает сколько раз он пытался достать URL для конкретной задачи. Если аккаунт стабильно возвращает 0 видео (shadowban / TT-блокировка) — задача останется в `awaiting_url` пока не сработает 48ч-таймаут. Нужен счётчик попыток → промоут в terminal-статус при exhaustion.

---

## Решение — 3 слоя, β phased rollout

### Layer C (PR1) — новый terminal-статус `published_no_url`

Новое значение `publish_tasks.status` (TEXT, без enum-миграции). Семантика:
- Публикация состоялась (видео в соцсети, slot occupied).
- Specific URL (`/video/<id>`, `/reel/<code>`, `/shorts/<id>`) не получен после исчерпания всех capture-механик.
- В `publish_queue` синкается как `done` (slot потрачен, ratelimit учитывается) — НЕ `failed` (иначе re-queue → дубль публикации).
- На UI — отдельный жёлтый badge «✅ Опубликовано · URL не получен».
- Не триггерит re-publish, не считается провалом в SLA-метриках.

### Layer B (PR1) — поллер correctness

Один PR с тремя fix'ами:

1. **`LIMIT 30 → 100`** (env-overridable `URL_POLLER_LIMIT`). Расчёт: 100 задач × один yt-dlp call per (platform,account) group ≈ <30 group-calls на tick (group reuse сейчас уже есть), 2-3 сек на call → укладываемся в 2-min interval с запасом.
2. **`ORDER BY started_at ASC → ORDER BY updated_at ASC`** (fairness). Задача с самым давним «последним dotouchem» получает приоритет — гарантирует что новые не голодают.
3. **NULL-zombie fix:** `WHERE COALESCE(started_at, updated_at) < NOW() - INTERVAL '48 hours'` в 48ч-timeout ветке.
4. **Per-task бюджет:** новая колонка `url_capture_attempts INT DEFAULT 0`. Инкремент при «0 свободных видео» / «diff пуст». При `attempts >= URL_CAPTURE_MAX_ATTEMPTS` (default 30 = ~1 час) → промоут в `published_no_url` + `log_event('url_capture_exhausted')`.

Индекс `idx_publish_tasks_status_updated ON publish_tasks(status, updated_at)` чтобы LIMIT 100 + ORDER BY updated_at не делал seq-scan.

### Layer A — capture механики

**PR2 — bot-side (A1 + A2):**

- **A1 — `_capture_via_share_loop`:** обёртка над существующим `_auto_get_*_url`. 3 wave × `wait_secs=45` с pull-to-refresh между waves. Бот не отпускает девайс до успеха или исчерпания 3 wave (≈ 3 мин budget сверху текущего). Останавливается на первой specific URL (`_is_specific_reel_url`).
- **A2 — `_capture_via_notifications`:** перед A1 — `adb shell dumpsys notification --noredact` → грепаем пакет соцсети → regex поиск URL pattern в `text` / `subText` / `bigText`. **Защита от foreign-account:** URL принимается только если содержит substring `@{acct}` или `/{acct}/`, иначе отбрасывается. Если notification permissions не выданы / dump пуст — `log_event('url_capture_a2_unavailable')` + skip к A1.

Порядок: A2 (дёшево, секундный probe) → если пусто, A1 (3 wave). На любой specific URL → `_update_post_url_final` → `status='done'` → return.

**PR3 — server-side (A3 + A5):**

- **A3 — YouTube Data API.** Реюз `analytics_collector.youtube_api_get_channel_id(handle)` + `youtube_api_get_videos(channel_id)` из `analytics_collector.py:496-560`. Вместо `yt-dlp` для YT — `playlistItems.list(uploads)`. Возвращает 5 newest deterministically. Quota: 1 unit на `channels.list` + 1 на `playlistItems.list` = 2 units / probe / account; 6 YT-задач × 30 probes ≈ 360 units/day — copecks от 10k daily-quota. Kill-switch `URL_CAPTURE_USE_YT_API=0` для отката.
- **A5 — Differential id-diff.** До `publish_*` бот делает pre-publish snapshot: top-5 video-id'ов аккаунта через тот же scraper что и поллер → сохраняет в новой колонке `publish_tasks.pre_publish_video_ids JSONB`. Поллер при матчинге берёт current list, делает `set(current) - set(pre_snapshot)` → новые id'ы = только что опубликованные. Работает даже если поллер видит «грязный» список (другие задачи аккаунта). Защита от дублей: в diff'е исключаем id'ы из `pre_publish_video_ids` других `awaiting_url` задач этого же аккаунта (иначе A5 может приписать новой задаче видео старой).

### Retroactive cleanup (после деплоя PR1)

Отдельная миграция, запускается **после** schema migration и деплоя PR1 кода:

```sql
-- migrations/20260518_wp86_retroactive_cleanup.sql
BEGIN;
UPDATE publish_tasks
SET status = 'published_no_url',
    log = COALESCE(log,'') || E'\n[WP #86 retroactive 2026-05-18] poller exhausted before fix — promoted from awaiting_url'
WHERE status = 'awaiting_url'
  AND COALESCE(started_at, updated_at) < NOW() - INTERVAL '2 hours';

UPDATE publish_queue pq SET status='done', updated_at=NOW()
  FROM publish_tasks pt
  WHERE pq.publish_task_id = pt.id
    AND pt.status='published_no_url'
    AND pq.status NOT IN ('done','failed','skipped','cancelled');
COMMIT;
```

```sql
-- migrations/20260518_wp86_retroactive_cleanup__rollback.sql
-- Возвращает только что промоутнутые задачи обратно в awaiting_url
-- + симметрично возвращает publish_queue в 'running' (естественное состояние
-- in-flight задачи: dispatchPublishQueue ставит running, syncQueueStatuses
-- для awaiting_url ничего не делает — см. server.js).
BEGIN;

WITH reverted AS (
  UPDATE publish_tasks
  SET status = 'awaiting_url',
      log = COALESCE(log,'') || E'\n[WP #86 rollback 2026-05-18] reverted to awaiting_url'
  WHERE status = 'published_no_url'
    AND log LIKE '%[WP #86 retroactive 2026-05-18]%'
  RETURNING id
)
UPDATE publish_queue pq
SET status='running', updated_at=NOW()
FROM reverted r
WHERE pq.publish_task_id = r.id
  AND pq.status = 'done';  -- защита: не трогаем pq которые БЫЛИ done легитимно
COMMIT;
```

**Замечание по rollback semantics:** rollback симметричен forward'у, но не «time-machine»-точен — пары pt/pq могут быть в неуместном состоянии если за окно между forward'ом и rollback'ом другие cron'ы их трогали. Это приемлемо: rollback — emergency-инструмент, не штатный flow.

**Порядок выката PR1:** (1) schema migration → (2) deploy кода (server.js, UI) → (3) verify через тестовую запись → (4) retroactive cleanup migration. Иначе orphan-зомби (старая логика поллера + новый статус которого она не понимает).

---

## Архитектурный data flow

```
┌─ Bot session (publisher_*.py) ────────────────────────────────────────┐
│  publish_<platform>()  →  upload success                              │
│         │                                                              │
│         ▼                                                              │
│  PRE-PUBLISH SNAPSHOT (A5): top-5 video_ids → pre_publish_video_ids   │
│  [происходит ДО самой публикации, в начале publish_*]                 │
│                                                                        │
│  ... publish flow ...                                                  │
│                                                                        │
│  A2: _capture_via_notifications (dumpsys notification, foreign guard) │
│         │ ─ specific URL? → _update_post_url_final → 'done' → return  │
│         ▼ нет                                                         │
│  A1: _capture_via_share_loop (3 wave × _auto_get_*_url(45s))          │
│         │ ─ specific URL? → _update_post_url_final → 'done' → return  │
│         ▼ нет                                                         │
│  _save_post_url(profile, final=False) → status='awaiting_url',        │
│       url_capture_attempts=0                                          │
└───────────────────────────────────────────────────────────────────────┘
                          ↓ device released
┌─ Server cron url-poller (server.js, каждые 2 мин) ────────────────────┐
│  SELECT awaiting_url WHERE updated_at < NOW() - INTERVAL '1 min'      │
│  ORDER BY updated_at ASC  ← fairness fix                              │
│  LIMIT 100                ← starvation fix                            │
│         │                                                              │
│         ▼                                                              │
│  per (platform, account) group:                                        │
│    if platform=YT and URL_CAPTURE_USE_YT_API:                          │
│        A3 → youtube_api_get_videos(channel_id)                         │
│        (на quota-fail → fallback на A5/legacy yt-dlp)                  │
│    else: scrapeAllVideos (existing yt-dlp / web_profile_info)         │
│         │                                                              │
│         ▼                                                              │
│  A5 diff: current_ids - pre_publish_video_ids - foreign_used_ids      │
│         │                                                              │
│         ▼                                                              │
│  found → 'done' + specific URL + log_event('url_capture_via_*')       │
│  not found:                                                            │
│    url_capture_attempts++, url_capture_last_attempt_at=NOW()           │
│    if attempts >= URL_CAPTURE_MAX_ATTEMPTS:                            │
│      status='published_no_url' + log_event('url_capture_exhausted')   │
└───────────────────────────────────────────────────────────────────────┘
                          ↓
       syncQueueStatuses: published_no_url → pq.status='done'
                          ↓
                NULL-zombie 48h timeout (COALESCE)
                          ↓
                  resetZombieTasks → failed
```

---

## Schema changes (PR1 миграция)

```sql
-- migrations/20260518_publish_tasks_url_capture_fields.sql
BEGIN;

ALTER TABLE publish_tasks
  ADD COLUMN url_capture_attempts INT NOT NULL DEFAULT 0,
  ADD COLUMN pre_publish_video_ids JSONB NULL,
  ADD COLUMN url_capture_last_attempt_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_publish_tasks_status_updated
  ON publish_tasks (status, updated_at)
  WHERE status IN ('processing', 'awaiting_url');  -- partial index, узкий

COMMIT;
```

```sql
-- migrations/20260518_publish_tasks_url_capture_fields__rollback.sql
BEGIN;
DROP INDEX IF EXISTS idx_publish_tasks_status_updated;
ALTER TABLE publish_tasks
  DROP COLUMN IF EXISTS url_capture_last_attempt_at,
  DROP COLUMN IF EXISTS pre_publish_video_ids,
  DROP COLUMN IF EXISTS url_capture_attempts;
COMMIT;
```

| Колонка | Назначение |
|---|---|
| `url_capture_attempts` | Счётчик неудачных проверок поллера. Reset на выходе из `awaiting_url`. |
| `pre_publish_video_ids` | Массив top-5 video-id'ов до публикации. NULL если pre-snapshot не успел. |
| `url_capture_last_attempt_at` | Observability: «давно не трогали» vs «свежий attempt». |

Status `published_no_url` — просто новое строковое значение в `publish_tasks.status` (TEXT-колонка, без enum).

---

## Конфиг — env vars + defaults

| Var | Default | Где |
|---|---|---|
| `URL_CAPTURE_MAX_ATTEMPTS` | `30` | `server.js` поллер. 30 × 2мин = 1ч до промоута в `published_no_url`. |
| `URL_POLLER_LIMIT` | `100` | `server.js` query LIMIT. |
| `URL_CAPTURE_BOT_WAVES` | `3` | `publisher_base._capture_via_share_loop` |
| `URL_CAPTURE_BOT_WAVE_GAP_SEC` | `15` | пауза между waves |
| `URL_CAPTURE_USE_YT_API` | `1` | A3 kill-switch |
| `URL_CAPTURE_USE_DIFF` | `1` | A5 kill-switch |
| `URL_CAPTURE_USE_NOTIF` | `1` | A2 kill-switch |

Per memory `feedback_deploy_scope_constraints.md` — kill-switches обязательны для prod-safe rollback каждой капчи.

---

## Error handling

| Layer | Failure | Behaviour |
|---|---|---|
| A1 (bot) | `_auto_get_*_url` exception | Try/except локально → лог → next wave. После всех waves продолжить (`status='awaiting_url'`, profile fallback). НЕ ронять `publish_*`. |
| A1 (bot) | Device disconnect между waves | `ensure_unlocked`-reconnect; если не вернулся за 30с — bail с partial URL. |
| A2 (bot) | `dumpsys notification` пустой / нет permission | `log_event('url_capture_a2_unavailable')` + skip к A1. |
| A2 (bot) | Regex поймал foreign-account video id | Matcher проверяет substring `@{acct}` или `/{acct}/` — иначе пропуск. Foreign-account рискован: чужой URL хуже чем «нет URL». |
| A3 (poller) | YT API quota 403 / network | `console.warn('[url-poller] YT API quota/network, fallback to yt-dlp')` + откат на legacy yt-dlp в той же группе. НЕ инкрементить attempts — это infra-сбой. |
| A3 (poller) | `YOUTUBE_API_KEY` отсутствует | Лог при первом probe + skip A3 ветка, дальше A5/legacy. |
| A5 (poller) | `pre_publish_video_ids IS NULL` | Fallback на полный list. Дать 5 проверок forgiveness прежде чем aggressive attempts++. |
| Layer B | Query медленнее на больших N | Partial index `idx_publish_tasks_status_updated` смягчает; 5к строк seq-scan приемлемо в worst case. |
| Layer C | Foreign код тестит `status='done'` напрямую | Cross-repo grep уже выполнен (per memory `feedback_cross_repo_schema_changes.md`). Результаты: validator-contenthunter — 0 hits. autowarm-testbench `server.js` — concrete audit list для PR1 (где `published_no_url` ДОЛЖЕН считаться как успех): line **1303** `status IN ('done','completed')` → добавить `'published_no_url'`; line **1322** `status='done'` filter; line **1856** аналогично; line **7118** `syncQueueStatuses` mirror — пометить. Lines 830, 1150, 5490, 5617, 7311 — другие таблицы (archive/autowarm/factory), не относятся. |

**Защита от дублей в A5:**
Текущий поллер уже фильтрует `usedUrls = SELECT post_url FROM publish_tasks WHERE post_url != '' AND id != ALL(...)`. Расширяю: добавить video-id'ы из `pre_publish_video_ids` ВСЕХ awaiting_url-задач этого аккаунта в exclusion-list — иначе A5 может приписать новой задаче видео которое существовало до её публикации (другая задача аккаунта).

---

## Testing strategy

| Тест | Тип | Файл |
|---|---|---|
| `published_no_url` accepted в `_save_post_url` | unit Python | `tests/test_publisher_base.py` (создать если нет) |
| `_capture_via_share_loop` — 3 wave / early-exit на specific URL | unit Python | `tests/test_capture_helpers.py` (new) |
| `_capture_via_notifications` — foreign-account guard | unit Python | same |
| Poller `ORDER BY updated_at ASC` + `LIMIT 100` fairness | unit JS (node:test) | `tests/test_url_poller.test.js` (new или расширить) |
| Poller NULL `started_at` → COALESCE-branch timeout | unit JS | same |
| `url_capture_attempts++` → промоут в `published_no_url` при MAX | integration JS | mock pool.query, fake clock |
| A5 diff: pre=['a','b'], current=['c','a','b'] → newest='c' | unit JS | same |
| A5 foreign-exclude: pre другой задачи перекрывает | unit JS | same |
| A3 YT API quota-fail → fallback на yt-dlp | unit JS | mock httpx, проверка лога |
| `syncQueueStatuses`: `published_no_url` → `pq.status='done'` | integration JS | расширить существующий тест |
| Retroactive SQL: dry-run на снапшоте openclaw — exactly N rows | manual smoke | `evidence/2026-05-18-wp86-retroactive-dryrun.md` |

**Live-smoke план (после деплоя каждого PR):**
- **PR1:** создать тестовую `publish_task(status='awaiting_url', url_capture_attempts=URL_CAPTURE_MAX_ATTEMPTS-1)`, дождаться poller-tick → проверить промоут в `published_no_url` + event log. Проверить UI badge на dashboard.
- **PR2:** запустить реальную TT-публикацию на тестовом телефоне (per memory `reference_testbench_smoke_paths.md` — реальные seed media), посмотреть лог waves в pm2 + новый event `category='url_capture_via_share_wave'` или `url_capture_via_notification`.
- **PR3:** YT-задача → проверить `url_capture_via_yt_api`; TT-задача с pre-snapshot → `url_capture_via_diff`.

---

## Observability — новые event categories

| category | level | meta |
|---|---|---|
| `url_capture_via_notification` | info | `{platform, wave_or_probe_idx, url_sample}` |
| `url_capture_via_share_wave` | info | `{platform, wave_idx, url_sample}` |
| `url_capture_via_yt_api` | info | `{channel_id, latency_ms}` |
| `url_capture_via_diff` | info | `{new_ids_count, pre_snapshot_size}` |
| `url_capture_via_legacy_list` | info | `{group_size}` (текущий path) |
| `url_capture_a2_unavailable` | warning | `{platform, reason}` |
| `url_capture_yt_api_quota` | warning | `{quota_used, fallback='yt-dlp'}` |
| `url_capture_exhausted` | warning | `{attempts, profile_url, layers_tried}` |

Дашборд-query для триажа (после стабилизации): `% capture-success per layer per platform` → понятно куда инвестировать дальше.

---

## Rollback план

**PR1 (Layer B + C + миграция):**
- Поллер-изменения: revert код в `server.js` → старый LIMIT/ORDER возвращается. Колонки `url_capture_attempts`, `pre_publish_video_ids`, `url_capture_last_attempt_at` остаются в БД (пустые) — non-breaking.
- Status `published_no_url` обратим: `UPDATE publish_tasks SET status='failed' WHERE status='published_no_url'` — за полчаса не подведёт под 48ч-timeout трешхолд.
- Retroactive миграция обратима тем же UPDATE'ом.
- Partial index можно дропнуть без последствий: `DROP INDEX idx_publish_tasks_status_updated`.

**PR2 (bot capture A1+A2):**
- Kill-switch `URL_CAPTURE_USE_NOTIF=0` отрубает A2.
- Для A1: `URL_CAPTURE_BOT_WAVES=1` возвращает single-call поведение.

**PR3 (server capture A3+A5):**
- `URL_CAPTURE_USE_YT_API=0` отрубает A3 — fallback на legacy yt-dlp.
- `URL_CAPTURE_USE_DIFF=0` отрубает diff — fallback на полный list matching.

Все kill-switches читаются на каждом cron-tick (без рестарта pm2).

---

## YAGNI — что НЕ делаем

- **A4 — server-side ADB-capture orchestration.** Тяжёлая device-lock семантика (что если бот сейчас публикует на этом телефоне?), отложен на отдельный backlog item если A1-A5 окажется недостаточно.
- **Per-account shadowban detection** (если аккаунт всегда возвращает 0 → автоматический flag). Это симптом-разбор, не root-fix; отдельный WP если данные после стабилизации это поднимут.
- **Notification permission auto-setup** на телефонах. Предполагаем что включены; если recon покажет что не — sub-issue.
- **Migration статуса на enum** (vs TEXT). Текущий TEXT работает, enum-конверсия не приоритет.

---

## Метрики успеха (post-rollout)

После всех 3 PR (≈ 5 дней):

| Метрика | Сейчас | Цель |
|---|---|---|
| `awaiting_url` queue depth (avg за сутки) | 45 | < 5 (стабильно дренируется) |
| `done` с specific URL (% от всех успешных публикаций) | ~85% | > 95% |
| `published_no_url` (% от всех успешных) | 0 (статуса нет) | < 5% (хвост невосстановимых) |
| `failed` из-за 48ч timeout (псевдо-провалы) | ~10% / день | ~0% |
| Время до terminal-статуса (от publish-success) | 0-48ч | < 60 мин для 95% |

Метрики снимать из event-log + `publish_tasks` daily aggregation в `evidence/`.
