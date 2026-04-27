# Evidence: `/client/analytics` пустая — multi-cause pipeline failure

**Created:** 2026-04-27
**Plan:** `.ai-factory/plans/analytics-empty-pipeline-diagnosis-20260427.md`
**Reporter:** Danil → "нет данных в `https://client.contenthunter.ru/client/analytics`, возможно привязка через старую неактуальную таблицу"
**Verdict:** Backend SQL правильный (Round 2 fix отработал). Аналитика пустая из-за **трёх независимых причин в data pipeline**, каждая нуждается в отдельном фиксе.

---

## 1. Симптом

### Server-side воспроизведение (D1)

Эндпоинт `/api/analytics/client/summary` сам по себе работает (HTTP 403 без auth — это ожидаемое поведение FastAPI:`Depends(get_current_user)`). Эмуляция запроса прямо в Postgres для `project_id=9 (Relisme)` с `days=30` (UI-дефолт):

| `days` | total_views | total_likes | total_posts | accounts |
|---|---:|---:|---:|---:|
| `30` (UI default) | **0** | **0** | **0** | **0** |
| `365` | 974 141 | 10 293 | 4 378 | 46 |

Данные ЕСТЬ за более широкий диапазон, но дефолтное окно UI (`7д` / `14д` / `30д`) полностью пустое.

### Кандидаты для UI-репро (для пользователя)

| project_id | name | packs | accs | historical reels |
|---|---|---:|---:|---:|
| 9 | Relisme | 14 | 57 | 4 495 |
| 16 | Джинсы Шелковица | 11 | 47 | 7 471 |
| 12 | Symmetry | 15 | 43 | 1 536 |
| 8 | Booster cap | 9 | 32 | 2 931 |
| 83 | Септизим | 17 | 46 | **0** |
| 81 | Wanttopay | 5 | 15 | **0** |
| 85 | ClickPay (no packs) | 0 | 0 | n/a |

---

## 2. Backend SQL — невиновен

### Round 2 fix (commit `7c03c58`, merge `c3467c0`, 2026-04-24)

```bash
$ grep -rn "account_packages" /root/.openclaw/workspace-genri/validator/backend/src/
backend/src/routers/analytics.py:212:    # factory_pack_accounts.project_id заменяет account_packages.project после DROP 2026-04-22.
backend/src/services/schemes_service.py:12:    Источник — factory_pack_accounts (после DROP account_packages 2026-04-22).
backend/src/routers/contract.py:62:    # factory_pack_accounts.project_id заменяет account_packages.project после DROP 2026-04-22.
```

→ только комментарии. Ноль реальных ссылок на дроп-нутую таблицу.

### Эндпоинты `/api/analytics/client/*` (3 шт) и их JOIN-цепочка

```
factory_inst_reels_stats firs
  JOIN factory_inst_reels r        ON r.ig_media_id = firs.ig_media_id
  JOIN factory_inst_accounts fia   ON fia.instagram_id = r.account_id
  JOIN factory_pack_accounts fpa   ON fpa.id = fia.pack_id
  WHERE fpa.project_id = :pid
    AND firs.collected_at >= CURRENT_DATE - :days
```

JOIN-семантика верна, типы совпадают (instagram_id text ↔ account_id text), `factory_pack_accounts.project_id` int ↔ `validator_projects.id` int — без implicit cast. Frontend `AnalyticsPage.vue:505,526` корректно шлёт `X-Project-Id` через `projectStore.projectHeaders()`.

---

## 3. Freshness matrix (D2)

| Таблица | Latest | Earliest | Rows | Comment |
|---|---|---|---:|---|
| `factory_inst_reels_stats.collected_at` | **2026-03-16** 00:00 | 2025-10-01 | 2 217 479 | **Главная причина пустоты UI**: окно `days=30` это всё пропускает |
| `public.factory_inst_reels.timestamp` | **2026-03-15** | 2000-01-01 | 65 021 | "2000-01-01" — null/garbage сентинели |
| `public.factory_inst_reels.synced_at` | **2026-03-23 11:00:02.948** | 2026-03-23 11:00:02.948 | 65 021 | **Все строки синхронизированы в один момент** — это bulk-копия из `factory.factory_inst_reels` |
| `factory.factory_inst_reels.timestamp` | 2026-03-02 | 2000-01-01 | 62 371 | Параллельная схема (text-vs-typed) — origin неизвестен |
| `public.factory_inst_accounts.synced_at` | 2026-04-24 | 2026-03-23 | 1 240 | Аккаунты пишутся свежими (autowarm registration), но без reels |
| `factory.factory_inst_accounts.date_last_parsing` | 2026-03-20 | 2026-01-26 | 1 133 | Параллельная копия |
| `factory_pack_accounts.synced_at` | 2026-04-22 | 2026-03-23 | 244 | Свежие |
| **`account_audience_snapshots.snapshot_date`** | **(empty)** | (empty) | **0** | **`/audience/latest`, `/audience` эндпоинты — пусты** |
| `factory.factory_accounts_fans` | (не запрошен) | | | Записывается posts_parser, но он крашится (см. §4) |
| `validator_projects` | n/a | n/a | 63 | OK |

**Two parallel schemas** — `public.factory_inst_reels` и `factory.factory_inst_reels` — содержат разные данные с разными сроками. `analytics.py` читает unqualified имена → search_path по умолчанию `"$user", public` → читает `public`. `public` версия = bulk-снимок от 2026-03-23 (все `synced_at` идентичны).

---

## 4. Pipeline death timeline + root causes (D3 + D7)

### Timeline

| Date | Event |
|---|---|
| **2026-03-10** 16:50 | `posts_parser.py` создан в autowarm (commit `61b9e46`) — единственный коммит, никогда не модифицирован |
| 2026-02-15 → 2026-03-15 | Daily 4 000-5 300 строк/день в `factory_inst_reels_stats` (нормальная работа) |
| **2026-03-16** | Резкий обрыв: 2 358 строк (partial-day), затем 0 строк/день навсегда |
| **2026-03-23** 11:00:02 | Bulk-копия `factory.factory_inst_reels → public.factory_inst_reels` (одномоментный SELECT INTO?) |
| 2026-03-23 → today | `account_audience_snapshots` всегда 0 строк, `factory_inst_reels_stats` без новых INSERTов |
| **2026-04-22** | DROP `account_packages` (отдельный schema-cleanup, не связан напрямую) |
| **2026-04-24** | Round 2 fix `analytics.py` (account_packages → factory_pack_accounts) |
| **2026-04-27 (today)** | User reports пустую аналитику. Последние reels — 41+ дней назад. |

### Root cause №1: `factory_parsing_logs` НЕ СУЩЕСТВУЕТ — silent crash подтверждён

```sql
SELECT table_schema, table_name FROM information_schema.tables WHERE table_name = 'factory_parsing_logs';
→ (empty)
```

`posts_parser.py:174-178` всегда вызывает `INSERT INTO factory_parsing_logs (...)` в success-path. Таблицы нет → исключение `relation "factory_parsing_logs" does not exist`.

Поток в `parse_instagram` (line 199-248):
1. `try`: upsert_post + upsert_stats + UPDATE `factory_inst_accounts.date_last_parsing` + `log_result(success)` ← crash
2. `except`: `conn.rollback()` ← откатывает ВСЁ выше (post, stats, fans, UPDATE)
3. ВНУТРИ except снова `log_result(error)` ← опять crash
4. Exception всплывает в `parse_account` (l. 530), который ловит и возвращает `{'ok': False, 'error': '...'}`

→ **каждая инвокация откатывает все данные, returning ok=false**.

### Root cause №2: posts_parser.py АКТИВНО ЗАПУСКАЕТСЯ — но JS-обёртка маскирует ошибку

В `server.js:3719+` есть scheduler для posts_parser (полный суточный прогон + догон непарсенных за день + per-account auto-trigger). Текущие pm2-логи `autowarm`:

```
[posts-parser] Авто-запуск: instagram/@lead_content_0
[posts-parser] OK: instagram/@lead_content_0 — posts=undefined, fans=undefined
[posts-parser] Авто-запуск: tiktok/@expertcontentlab
[posts-parser] OK: tiktok/@expertcontentlab — posts=undefined, fans=undefined
...
```

`posts=undefined, fans=undefined` — это симптом `JSON.parse({"ok":false, "error":"..."})` → `r.posts` undefined. JS логирует "OK" безусловно, не проверяя `r.ok`.

**Вывод:** parser работает, в нем по 1 inv/sec (видно по логам), но каждое исполнение rolls-back-all. Data flow мёртв 41+ дней при том что parser считается "running".

### Root cause №3: Apify monthly quota EXHAUSTED — IG/TT actors 403

```bash
$ curl -X POST "https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items?token=..."
HTTP 403
{"error":{"type":"platform-feature-disabled","message":"Monthly usage hard limit exceeded"}}

$ curl -X POST "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/run-sync-get-dataset-items?token=..."
HTTP 403  (тот же ответ)

$ curl "https://api.apify.com/v2/users/me?token=..."
{"data":{"username":"GenGo","plan":{"id":"SCALE","tier":"SILVER","monthlyBasePriceUsd":199,"monthlyUsageCreditsUsd":199},"proxy":{"groups":[]}}}
```

Аккаунт Apify `GenGo`, тариф SCALE-SILVER ($199/mo), кредиты исчерпаны → `proxy.groups: []` (locked out).

**Даже если бы причины №1+№2 были исправлены — IG и TikTok парсинг возвращал бы пустоту до сброса биллинга или повышения лимита.**

### Root cause №4 (cross-reference): YouTube — alive

```bash
$ curl "https://www.googleapis.com/youtube/v3/channels?part=statistics,snippet&id=...&key=..."
HTTP 200  (1929 bytes, JSON ok)
```

YouTube API работает. Так что после фикса №1+№2 хотя бы YT-данные потекли бы.

---

## 5. Cross-repo writers map (D5)

| Таблица | Кто пишет | Wired где | Стейтус |
|---|---|---|---|
| `factory_inst_reels` | `autowarm/posts_parser.py:110` (ЕДИНСТВЕННЫЙ writer) | `autowarm/server.js:3719+` через execFile | Crashes |
| `factory_inst_reels_stats` | `autowarm/posts_parser.py:135` | то же | Crashes |
| `factory_accounts_fans` | `autowarm/posts_parser.py:164` | то же | Crashes |
| `account_audience_snapshots` | `autowarm/analytics_collector.py:1473` (+ v2:535) | `autowarm/scheduler.js:497` (cron 00:00 UTC) | **Пусто навсегда — root cause TBD** (отдельная задача) |
| `account_post_snapshots` | `analytics_collector.py:634` (+ v2:480) | то же | Не проверено |
| `account_daily_delta` | `analytics_collector.py:709` (+ v2:504) | то же | Не проверено |

Producer / producer-copilot / ch-auth / kira / validator — **никто** не пишет в analytics-таблицы. Это эксклюзивная зона autowarm.

---

## 6. Per-project impact (D6)

Полная таблица — все 38 проектов с `factory_pack_accounts` rows (`project_id=85 ClickPay` ИСКЛЮЧЁН — нет packs):

| project_id | project | packs | accs | with_ig_id | historical_reels |
|---:|---|---:|---:|---:|---:|
| 9 | Relisme | 14 | 57 | 57 | 4 495 |
| 16 | Джинсы Шелковица | 11 | 47 | 47 | **7 471** |
| 83 | Септизим | 17 | 46 | 46 | **0** |
| 12 | Symmetry | 15 | 43 | 43 | 1 536 |
| 48 | CSGO | 13 | 41 | 41 | 765 |
| 8 | Booster cap | 9 | 32 | 32 | 2 931 |
| 47 | Flor | 10 | 32 | 31 | 931 |
| 51 | Вельвет | 9 | 27 | 27 | 443 |
| 49 | Art Estate | 9 | 27 | 27 | 710 |
| 59 | ikomek | 9 | 27 | 27 | 271 |
| 17 | Zakka | 8 | 27 | 27 | 2 093 |
| 14 | Волшебная футболка | 4 | 24 | 24 | 953 |
| 13 | Sip&Shine | 9 | 24 | 24 | 1 248 |
| 58 | Ambassadori | 8 | 24 | 24 | 238 |
| 11 | SlimViona | 8 | 23 | 23 | 883 |
| 53 | Content hunter | 8 | 23 | 23 | 939 |
| 55 | Celebration Station | 6 | 21 | 21 | 407 |
| 71 | Максим Иванов | 6 | 18 | 18 | 88 |
| 54 | Ортокрафт | 6 | 18 | 18 | 576 |
| 50 | Quingi | 5 | 15 | 15 | 343 |
| 81 | Wanttopay | 5 | 15 | 15 | **0** |
| 10 | Тестовый проект | 4 | 13 | 10 | **0** |
| 65 | Forsal | 6 | 12 | 12 | 156 |
| 60 | BigKefBot | 3 | 11 | 11 | 270 |
| 82 | Эль-косметик | 4 | 10 | 10 | **0** |
| 52 | Кирилл Попов | 3 | 9 | 9 | 293 |
| 57 | Synatra VPN | 3 | 9 | 9 | 233 |
| 61 | Алёна Пантюхина | 3 | 9 | 9 | 108 |
| 62 | Luni | 3 | 9 | 9 | 133 |
| 63 | Beaconix | 3 | 9 | 9 | 116 |
| 64 | Trend Clone | 3 | 9 | 9 | 150 |
| 67 | Hobruk | 3 | 9 | 9 | 81 |
| 68 | Laser Cube | 3 | 9 | 9 | 117 |
| 84 | Анеcole | 5 | 7 | 7 | **0** |
| 87 | Forchil | 3 | 6 | 6 | **0** |
| 79 | Pimble | 2 | 3 | 3 | **0** |
| 66 | Семантика | 3 | 3 | 3 | **0** |
| 91 | Покерадон | 1 | 1 | 1 | **0** |

### Bucket A — Most existing accounts have `instagram_id` (no id_parser dependency)
**Все 38 проектов**: `with_ig_id ≈ accounts`. Существующий клиентский ростер не зависит от починки `id_parser` (memory `project_id_parser_ig_broken.md` касается только новых аккаунтов после 2026-04-23).

### Bucket B — 30/38 проектов имеют исторические reels
После реанимации pipeline эти проекты сразу же покажут хотя бы старые данные (если выбрать диапазон `>= 90 дней` в date-picker). После backfill — будут показывать всё.

### Bucket C — 8/38 проектов с 0 historical_reels
**Текущий пустой статус не лечится бэкфиллом** — у них в принципе никогда не было reels:

- `83` Септизим (17 packs, 46 accs!) — **самый странный**: много packs/аккаунтов, но никогда не парсились
- `81` Wanttopay
- `10` Тестовый проект
- `82` Эль-косметик
- `84` Анеcole
- `87` Forchil
- `79` Pimble
- `66` Семантика
- `91` Покерадон

Эти получат данные ТОЛЬКО после фикса №1+№2+№3 — full upstream + parser revival. Backfill бесполезен (нечего бэкфиллить).

---

## 7. Frontend behavior (D8)

`AnalyticsPage.vue`:

- **Loading state** (l. 67): `<div v-if="loading">…</div>` — спиннер на запросах ✓
- **Empty state messages** (l. 106, 164, 240): "Нет данных по платформам", "Нет данных за {{ activeDays }} дней", "Нет данных для отображения" ✓
- **Error handling** (l. 512-514): `catch (e) { console.error('analytics error', e) }` — ошибки **молча** идут в console.log, без toast/banner. Любой 500/4xx ⇒ экран как пустой.
- **Time chips** (l. 53): `[7,14,30,90]` — fixed presets. Дефолт `activeDays = 7` (l. ~387) → видим только за 7 последних дней → пусто.
- **DateRangePicker** доступен (l. ~58) — пользователь *может* вручную выставить `date_from` старее чем 41 день, но это no-affordance for non-tech users.
- **`BrandPage.vue`, `PublicationsPage.vue`** — те же источники, тот же симптом.

→ User UX: спиннер → "Нет данных за 7 дней". Никаких намёков на причину. Никакой проверки `MAX(collected_at)` для health-индикатора.

---

## 8. RECOMMENDATIONS — варианты реанимационного плана

| Вариант | Effort | Impact | Описание | Зависимости |
|---|---|---|---|---|
| **A. Full pipeline revival + backfill** | 2-3 дня | Highest | (1) `CREATE TABLE factory_parsing_logs`. (2) Apify quota: top-up или повышение тарифа. (3) Backfill за 41 день через ручной запуск posts_parser в loop. (4) Health-monitor: alert если `MAX(collected_at) < CURRENT_DATE - 3`. | Apify $$$ (квота), доступ к Apify console |
| **B. Partial revival — YT only** | 1 день | Medium | (1) `CREATE TABLE factory_parsing_logs`. (2) Запустить parse_youtube для всех YT-аккаунтов вручную. IG/TT остаются мёртвыми до квоты Apify. UI покажет данные только по YT. | Только YT API (live) |
| **C. Staleness-banner на UI** | <1 день | Косметика | (1) Backend: `/api/analytics/client/health` возвращает `MAX(collected_at)`. (2) Frontend `AnalyticsPage.vue`: если `>3 дня` — баннер "Данные устарели на N дней — pipeline восстанавливается". Pipeline остаётся мёртвым; это только коммуникация. | n/a |
| **D. Defer — wait for Apify quota reset** | 0 | Очень низкий | Подождать сброса месячного лимита (~1-е число следующего месяца → ~2026-05-01). Ничего не делать. Не лечит root cause №1 (factory_parsing_logs missing) → revive всё равно нужен. | Время |
| **E. Combined A+C (Recommended)** | 2-3 дня | Highest+UX | A полностью + C на время восстановления как safety-net. После backfill убрать баннер. | Apify $$$ |

### Рекомендую **E (A + C)**

- **Phase 1 (sprint-fix, ≤4ч):** `CREATE TABLE factory_parsing_logs (id serial, account_id text, platform text, status text, error_category text, error_message text, raw_response jsonb, created_at timestamptz default now())`. Это сразу разморозит posts_parser для YT (Apify не нужен). Tested by смотрим в pm2 logs autowarm — `[posts-parser] OK: ... posts=N, fans=M` (с числами вместо undefined).
- **Phase 2 (ASAP, ≤4ч):** Apify quota — тут пользовательское решение: top-up или upgrade тарифа.
- **Phase 3 (1-2 дня):** Backfill loop за 41 день. Скрипт-обёртка `python3 posts_parser.py` для всех 1240 active accounts с `time.sleep(2)` (как в `parse_all_active`).
- **Phase 4 (≤2ч):** Staleness-banner на UI — оставить включённым на время backfill, потом убрать или сделать threshold `>7 дней`.
- **Phase 5 (≤2ч):** Health endpoint + monitoring alert.

### Альтернативный путь — **переписать posts_parser**
Не предлагаю как primary, но опция: переписать так, чтобы log_result() было опциональным (try/except внутри), чтобы missing log table не блокировала pipeline. Это патч на 1 файл, ~10 строк. Может быть выполнен в Phase 1 как hot-fix без миграции БД.

---

## 9. Open questions для пользователя ДО написания реанимационного плана

1. **Apify квота**: топ-апить текущий $199/mo тариф (быстрее) или upgrade на следующий tier? Кто owner Apify-аккаунта `GenGo`? Reset биллинга ожидается **~1 мая 2026** (через 4 дня) — может, подождать?
2. **`factory_parsing_logs` schema**: создаём пустой `id+ts+account_id+platform+status+error_*` или есть архивная DDL из прошлого, которую надо найти? (git history autowarm не нашёл — таблица никогда не была версионирована).
3. **`account_audience_snapshots` (0 rows навсегда)** — это отдельный root cause. Включаем в этот же план или отдельный? `analytics_collector.py` запускается каждый день в 00:00 UTC, но не пишет — нужна отдельная диагностика.
4. **Backfill scope**: за 41 день (с 2026-03-16) или только последние 7-14 (быстрее)?
5. **Тиббинг в Apify-плане** vs **переписать posts_parser без log_result** — какой подход для Phase 1?
6. **Hot-fix через staleness banner**: разворачиваем сначала, или сразу идём на full revival?

---

## Links

- Plan: `.ai-factory/plans/analytics-empty-pipeline-diagnosis-20260427.md`
- Round 2 backend fix (account_packages cleanup): `.ai-factory/plans/validator-schemes-account-packages-20260424.md`, evidence: `.ai-factory/evidence/validator-schemes-account-packages-fix-20260424.md`
- Code references:
  - `validator/backend/src/routers/analytics.py` (591 lines)
  - `validator/frontend/src/pages/client/AnalyticsPage.vue` (l. 505, 526, 67, 106, 164, 240, 303, 386, 494, 512)
  - `autowarm/posts_parser.py` (576 lines, single commit `61b9e46`)
  - `autowarm/server.js:3719-3850` (posts_parser scheduler)
  - `autowarm/scheduler.js:19,468-509` (analytics_collector cron)
- Relevant memory:
  - `project_account_packages_deprecation.md`
  - `feedback_user_diagnosis_is_signal.md` — гипотеза vs ground truth
  - `project_id_parser_ig_broken.md` — Apify 403 + IG mobile 429 (parallel issue)
  - `feedback_pm2_dump_path_drift.md`
  - `feedback_deploy_scope_constraints.md` — PM2 vs systemd
