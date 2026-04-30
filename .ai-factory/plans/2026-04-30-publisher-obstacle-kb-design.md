# Publisher Obstacle Knowledge Base + AI Unstuck v2 — Design

**Дата:** 2026-04-30
**Автор спека:** brainstorm-сессия Danil ↔ Claude
**Статус:** Awaiting user review → переход в `writing-plans` для implementation plan
**Связанные memory:** `project_publish_testbench.md`, `project_ai_unstuck_hardening_backlog.md`, `project_publisher_modularization_wip.md`, `project_publish_guard_schema.md`
**Связанные plans:** `ai-unstuck-hardening-20260429.md`, `publisher-vision-screencast-analysis-20260424.md`

---

## 1. Problem statement

Текущий `ai_unstuck` (`publisher_base.py:1698-1933`) — реактивный LLM-агент: при застревании отправляет screenshot в Groq Llama-4-Scout и получает action. После недавнего hardening (anti-loop guard, S3 screenshot, blind-tap refusal — commit `b75d587`) baseline за 7 дней:

- **70 событий AI Unstuck / 1 task / 0 success.**

То есть AI Unstuck **не помогает** — слепо тыкает, не учится из истории, на каждый stuck тратит $0.0002 + 1.5 sec без изменения исхода.

Параллельно в коде накопились hardcoded markers (`_IG_HUMAN_CHECK_MARKERS`, `_IG_EDITOR_RESOURCE_IDS`, `_is_ig_draft_continuation`, `_OZON_AD_MARKERS`, `_TT_REAUTH_MARKERS`, ig-about-account-modal detector, YT settings-activity fallback) — это **уже** работающая «база знаний» о препятствиях, но она:
- Раскидана по 3 mixin'ам без единого формата
- Не дополняется автоматически
- Не имеет outcome-телеметрии (мы не знаем, какой marker реально срабатывает)

**Задача:** превратить «реактивное LLM-тыкание» в **двухуровневую самообучающуюся систему**:
1. **Pattern-match shim** — fast-path по structured signature (XML → hash → DB lookup), применяет проверенный action без LLM-вызова.
2. **LLM-fallback с memoization** — если pattern не нашёлся, вызывается Claude Sonnet 4.6, и **успешный** result автоматически сохраняется как новый pattern.

Главная цель — measurable: повысить AI Unstuck overall success-rate с 0% до ≥40% за 6 недель.

## 2. Scope & non-goals

**В scope (MVP):**
- Все 3 платформы (IG / TT / YT)
- Online learning через `ai_unstuck` post-LLM hook
- Offline cold-start: миграция in-code constants (B1) + 30-day events corpus mining (B2)
- Tiered curation gate (T1 auto-promote / T2 Telegram human review / T3 auto-degrade)
- Admin UI на `delivery.contenthunter.ru/obstacles.html`
- Замена Groq → Claude Sonnet 4.6 для всего vision-pipeline

**Out of scope (V2 / future):**
- Pre-emptive obstacle scanning после каждого `set_step` (Опция 2 из brainstorm)
- Bandit / Thompson sampling auto-promotion (overkill для нашей нагрузки)
- 5%/25%/100% canary rollout (нагрузка слишком низкая для статистической значимости)
- Mining UI (запуск mining через UI кнопку — пока через CLI)
- Bulk operations / regex search / action_recipe JSON editor в admin UI
- Migration `_TT_REAUTH_MARKERS` / `agent_diagnose` text-pipeline на Claude (можно потом)
- VK / FB / X / Threads (вне scope autowarm в принципе)

## 3. Architecture

Три новых слоя поверх существующего `publisher_base.py`:

```
STUCK DETECTION (existing) — watchdog 30s → ai_unstuck()
   │
   ▼
LAYER 1: SIGNATURE EXTRACTION (новый, pure-function)
   obstacle_signatures.py: extract slim-features из XML → sha1 hash
   │
   ▼
LAYER 2: KNOWLEDGE BASE LOOKUP (новый, DB)
   obstacle_kb.py: SELECT publisher_obstacles WHERE id=$1
     ├─ stable    → apply action_recipe → record outcome → return continue
     ├─ candidate/exper → shadow-log match → fallthrough в LLM
     └─ no match  → fallthrough в LLM
   │
   ▼
LAYER 3: LLM FALLBACK (existing, Claude Sonnet 4.6)
   _call_anthropic_vision(screenshot, prompt) → action
     └─ on success: insert_or_increment(status='experimental',
                                        source='ai_unstuck_success')

CURATION (новый, async — внутри triage_loop тикер):
   obstacle_promoter.py:
     T1: experimental → stable (safe action_type + N successes + 0 fails)
     T2: experimental → candidate + Telegram review (destructive actions)
     T3: stable → experimental (drift: 3 fails / confidence<0.5 / stale 30d)
   contenthunter_bugs_bot/obstacle_handlers.py:
     callback_query: Approve / TryOnce / Blacklist / Comment

EXTRA HOOKS (новые):
   1. _force_clean_restart_via_recents → pre-check KB перед nuclear
   2. triage_classifier.process_failed_task → mining mining UI dumps
   3. ai_unstuck wiring lifted в base → TT/YT тоже подхватывают
```

**Что НЕ меняется:**
- `publisher.py` orchestrator (entry-point `run_publish_task`)
- `account_switcher.py` ensure_account / switch flows
- Mixin-структура (IG/TT/YT)
- Schema `publish_tasks.events` (продолжаем писать events как раньше)
- Существующий `publisher_fixes` registry (testbench code-fix loop — отдельный domain)

## 4. Data model

### 4.1. ObstacleSignature (slim-набор features)

Pure-function `extract_signature(xml, top_activity, platform, step)` возвращает:

| Поле | Источник | Назначение |
|---|---|---|
| `platform` | `task.platform` | ig/tt/yt — base bucket |
| `top_activity` | `dumpsys activity \| topResumedActivity` | главный discriminator пакета+экрана |
| `publisher_step` | `self.set_step()` value | контекст «где встретили» |
| `resource_ids` | sorted unique set из XML, stripped package prefix | главный signal — какие view-id видны |
| `key_texts` | tokenized text+content-desc, normalized | модалки идентифицируются по тексту |
| `dialog_indicator` | bool: class contains `Dialog`/`AlertDialog` или resource-id contains `dialog/alert/modal/sheet/bottomsheet` | помогает быстро фильтровать popup vs screen |

**Нормализация (детерминизм):**
- text → lowercase
- NBSP (`\xa0`) → space, multiple spaces collapsed
- digits → `<NUM>`
- `&apos;`/curly quotes → `'` (паттерн уже в `_ig_is_human_check`)
- resource_ids → strip package prefix (`com.instagram.android:id/foo` → `foo`)

**Хэш:**
```python
obstacle_id = sha1(json.dumps({
    platform, top_activity, publisher_step,
    resource_ids: sorted_list,
    key_texts: sorted_list,
    dialog_indicator
}, sort_keys=True))[:16]
```

**Исключено намеренно:** `bounds`, usernames, timestamps, view counts, dates, instance index, package (он уже в top_activity), clickable_count (избыточен — resource_ids + key_texts уже несут эту информацию).

### 4.2. Tables

```sql
CREATE TABLE publisher_obstacles (
    -- IDENTITY
    obstacle_id        TEXT PRIMARY KEY,           -- sha1(slim-набор)[:16]
    platform           TEXT NOT NULL,              -- ig/tt/yt
    top_activity       TEXT NOT NULL,
    publisher_step     TEXT,
    resource_ids       TEXT[] NOT NULL,            -- denormalized для дебага
    key_texts          TEXT[] NOT NULL,
    dialog_indicator   BOOLEAN NOT NULL,
    signature_raw      JSONB NOT NULL,             -- полный JSON до хэша

    -- ACTION RECIPE
    action_type        TEXT NOT NULL,              -- 'tap_resource_id'|'tap_text'|'keycode_back'|'force_stop'|'force_clean_recents'|'noop_wait'|'escalate'
    action_params      JSONB NOT NULL,
    action_description TEXT,                       -- human-readable

    -- OUTCOME STATS (rolling counters)
    success_count      INT NOT NULL DEFAULT 0,
    fail_count         INT NOT NULL DEFAULT 0,
    last_success_at    TIMESTAMPTZ,
    last_fail_at       TIMESTAMPTZ,
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- LIFECYCLE
    status             TEXT NOT NULL DEFAULT 'experimental',
                       -- 'experimental' | 'candidate' | 'stable' | 'blacklisted'
    confidence_score   REAL,
    apply_limit        INT,                         -- для Try Once UX
    promoted_at        TIMESTAMPTZ,
    promoted_by        TEXT,
    degraded_at        TIMESTAMPTZ,
    degraded_reason    TEXT,

    -- AUDIT
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source             TEXT NOT NULL,
                       -- 'ai_unstuck_success' | 'vision_postmortem' | 'manual_seed' | 'triage_mining' | 'offline_mining'
    source_task_id     BIGINT,
    notes              TEXT,

    -- DEBUG
    xml_sample_url     TEXT,
    screenshot_url     TEXT
);
CREATE INDEX idx_obstacles_platform_status ON publisher_obstacles (platform, status);
CREATE INDEX idx_obstacles_last_seen ON publisher_obstacles (last_seen_at DESC);
CREATE INDEX idx_obstacles_source ON publisher_obstacles (source);

CREATE TABLE publisher_obstacle_outcomes (
    id           BIGSERIAL PRIMARY KEY,
    obstacle_id  TEXT NOT NULL REFERENCES publisher_obstacles(obstacle_id),
    task_id      BIGINT NOT NULL,
    matched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    action_taken JSONB NOT NULL,                  -- snapshot recipe на момент применения
    outcome      TEXT NOT NULL,                   -- 'progressed' | 'still_stuck' | 'task_succeeded' | 'task_failed_other' | 'shadow_match'
    next_step    TEXT,
    notes        TEXT
);
CREATE INDEX idx_outcomes_obstacle ON publisher_obstacle_outcomes (obstacle_id, matched_at DESC);
CREATE INDEX idx_outcomes_task ON publisher_obstacle_outcomes (task_id);
```

`outcome='shadow_match'` — special row для experimental/candidate matches без apply (counterfactual evidence).

## 5. State machine (lifecycle)

```
                       ┌──────────────────┐
                       │   experimental   │  INSERT'ится здесь:
                       │ (default on add) │   • ai_unstuck_success (post-LLM)
                       │ shadow-log only, │   • triage_mining
                       │ apply=NO         │   • offline_mining (B2)
                       └────────┬─────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
       T1 (auto):         T2 (notify):        (stale 30d
       success≥5,         success≥3,           — optional GC)
       safe action,       destructive
       0 fails 7d,        action
       3+ tasks
              │                 │
              ▼                 ▼
       ┌──────────┐    ┌──────────────┐
       │  stable  │    │  candidate   │  ← Telegram review через bugs_catcher_bot
       │  apply=  │    │  apply=NO    │
       │  YES     │    │  ждёт human  │
       └──┬───────┘    └─┬──┬──┬──┬───┘
          │              │  │  │  │
          │              ✅ ⚠️  🚫 💬
          │           Approve│Blklst│
          │              │   │  │   │
          │              │  TryOnce │ (Comment — заметка без status change)
          │              │ apply_lim│
          │              │  =1, →   │
          │              │ candidate│
          │              │          │
          │              ▼          ▼
          │    ┌──────────┐  ┌──────────────┐
          │    │  stable  │  │ blacklisted  │
          │    │ promoted_│  │ never apply  │
          │    │ by=human │  └──────────────┘
          │    └──────────┘
          │
       T3 (auto-degrade):
       3 consec. fails OR
       confidence<0.5 last 30d OR
       last_seen >30d ago
          │
          ▼
       ┌──────────┐
       │experimental│
       │degraded=t │ → накапливает outcomes снова
       └──────────┘     или manual blacklist
```

**Tier 1 safe action whitelist:** `keycode_back`, `tap_resource_id` (exact match), `tap_text` (exact match), `noop_wait`. Эти actions reversible или idempotent.

**Tier 2 destructive whitelist:** `force_stop`, `force_clean_recents`, `escalate`, любой action с `restart_required=true` flag, blind-coords tap. Требуют human approval перед apply.

## 6. Components

### 6.1. Новые модули (~1550 LOC новый)

| Файл | LOC | Ответственность |
|---|---|---|
| `obstacle_signatures.py` | ~200 | Pure-function signature extraction. Без I/O — testable изолированно |
| `obstacle_kb.py` | ~350 | DB API: lookup / record_outcome / insert_or_increment / recompute_confidence |
| `obstacle_actions.py` | ~250 | Action dispatcher: apply_action(publisher, recipe) → outcome |
| `obstacle_promoter.py` | ~300 | Async tick (внутри triage_loop): T1/T2/T3 logic |
| `obstacle_seed.py` | ~200 | One-shot CLI: `from-constants` (B1) + `mine-events` (B2) |
| `contenthunter_bugs_bot/obstacle_handlers.py` | ~250 | aiogram 3 callback handlers + Telegram message builder |

### 6.2. Изменения existing файлов

| Файл | Что меняется | Изменение |
|---|---|---|
| `publisher_base.py` | `ai_unstuck()`: KB shim перед LLM + post-LLM hook + Anthropic switch | ~80 строк / +30 |
| `publisher_base.py` | `_force_clean_restart_via_recents`: pre-check KB | +20 строк |
| `publisher_base.py` | Lift wiring `ai_unstuck` для TT/YT (был IG-only) | +15 строк |
| `publisher_base.py` | Удаление `_IG_HUMAN_CHECK_MARKERS`, `_IG_EDITOR_RESOURCE_IDS`, ig-about-account-modal detector | -40 строк |
| `publisher_instagram.py` | Удаление `_is_ig_draft_continuation`, _IG_DRAFT_DIALOG_*; replace на DB lookup | -30 строк |
| `publisher_tiktok.py` | Удаление `_TT_REAUTH_MARKERS`; replace на DB lookup | -15 строк |
| `publisher_youtube.py` | Удаление YT settings-activity hardcoded markers | -15 строк |
| `account_switcher.py` | Удаление `_OZON_AD_MARKERS`, sbrowser CustomTab markers | -25 строк |
| `triage_classifier.py` (testbench) | finally-hook → mine_from_failed_task | +40 строк |
| `vision_analyzer.py` (testbench) | `_call_groq_vision` → `_call_anthropic_vision` switch (Sonnet 4.6) | ~60 строк |
| `server.js` (autowarm) | 5 endpoints `/api/obstacles/*` | +150 строк |
| `obstacles.html` (delivery) | Admin UI на frontend factory pattern | ~300 строк новый файл |
| `.env` (testbench) | `ANTHROPIC_API_KEY` swap (OAuth → Console key) + `VISION_PROVIDER=anthropic` | 2 строки |

### 6.3. Миграции (additive)

- `20260430_publisher_obstacles.sql` — table + 3 индекса
- `20260430_publisher_obstacle_outcomes.sql` — table + 2 индекса
- `20260430_obstacle_kill_switches.sql` — INSERT'ы в `system_flags`

### 6.4. PM2 / systemd — без новых сервисов

- `obstacle_promoter` — тикер внутри существующего `triage_loop` (cron каждые 30 мин по memory `project_farming_testbench.md`)
- `obstacle_handlers` — расширение существующего systemd unit `contenthunter_bugs_bot` (добавляется psycopg-connection к `openclaw`)
- Admin UI — расширение существующего Express handler в `server.js` autowarm

## 7. Data flows

### 7.1. Path A — KB hit (golden, ~150-300ms, $0)

`stuck → extract_signature → lookup → status=stable → apply_action → record_outcome=progressed → return continue`

### 7.2. Path B — KB miss → LLM fallback → learn

`stuck → lookup → MISS → _call_anthropic_vision(Claude Sonnet 4.6) → apply LLM action → on success: insert_or_increment(status='experimental', source='ai_unstuck_success')`

### 7.3. Path C — Triage mining

`publisher fail → triage_classifier finally → mine_from_failed_task: extract последние 5 UI dumps → insert_or_increment(experimental, source='triage_mining')`

### 7.4. Path D — Promoter tick (внутри triage_loop, каждые 30 мин)

```python
for obstacle in SELECT * FROM publisher_obstacles WHERE status IN ('experimental','candidate','stable'):
    if T1_criteria(obstacle): promote_to_stable()
    elif T2_criteria(obstacle): notify_telegram_review()
    elif T3_drift_detected(obstacle): degrade_to_experimental()
```

### 7.5. Path E — Telegram review (Tier 2)

`promoter finds candidate → bugs_catcher_bot.notify(message с inline buttons) → user taps → callback_query handler → DB UPDATE`

**Inline buttons (4):** `✅ Approve & Stable` / `⚠️ Try Once` / `🚫 Blacklist` / `💬 Comment`

**Outcome detection в Path A:** snapshot `topResumedActivity` ДО action + ПОСЛЕ. Если сменилось — `outcome='progressed'`. Если нет — `still_stuck`. Pre/post — через быстрый `dumpsys`, не full `dump_ui` (sub-100ms).

## 8. Cold-start migration

### 8.1. B1 — In-code constants (Day 0, automated)

`obstacle_seed.py from-constants` мигрирует ~10-15 patterns со `status='stable'` (proven в проде):

| Source constant | Action recipe |
|---|---|
| `_IG_HUMAN_CHECK_MARKERS` | escalate (account_block) |
| `_IG_EDITOR_RESOURCE_IDS` | meta-marker only (для outcome detection) |
| `_is_ig_draft_continuation` | tap_text "Начать новое видео" |
| `_OZON_AD_MARKERS` | force_stop sbrowser + KEYCODE_BACK |
| `_TT_REAUTH_MARKERS` | escalate (tt_block) |
| `_ig_is_on_unexpected_screen` | force_clean_recents |
| `ig_about_account_modal` | KEYCODE_BACK |
| YT settings-activity markers | am start Shell_SettingsActivity |

После миграции in-code constants **удаляются** (без fallback). Tests, использующие константы (`test_overlay_dismiss.py`, `test_publisher_ig_camera_recovery.py`, `test_recents_close_all_recovery.py`), обновляются на DB-mock.

### 8.2. B2 — 30-day events corpus mining (Day 7-10, semi-manual)

`obstacle_seed.py mine-events --days=30 --min-cluster=3`:

1. SELECT failed tasks за 30 дней с `meta.category LIKE 'ai_unstuck_%'`
2. Скачать XML+screenshot из S3
3. Extract signatures, group by obstacle_id, фильтр cluster_size ≥ 3
4. На top-cluster — один Claude vision call → suggested action
5. INSERT'ит candidates со `status='candidate'`, `source='offline_mining'`
6. Promoter находит свежие candidates → отправляет Telegram review (Tier 2 flow)
7. Human ack'ает по одному

`mining_report.md` генерируется как audit artifact / fallback при bulk-review.

**Ожидаемый результат на Day 10:** ~30-60 patterns total (B1 ~15 stable + B2 ~10-30 candidates + ~5-15 experimental от online accumulation за 7-10 days production).

## 9. Admin UI

`https://delivery.contenthunter.ru/obstacles.html` — paginated frontend factory pattern (memory `project_paginated_tables_pilot.md`).

| Page | Контент | Operations |
|---|---|---|
| `/obstacles.html` (list) | Paginated: obstacle_id, platform, top_activity, status, action_type, success/fail, confidence, last_seen | Filter by platform/status/source |
| `/obstacles.html#pattern/:id` (detail) | Все поля + screenshot inline + XML viewer + outcome history (last 50) + comment thread | Edit status / notes / blacklist / regenerate suggested action |
| `/obstacles.html#stats` (panel) | 4 KPI cards | Read-only |

**Backend (~150 LOC) в существующем `server.js`:**
- `GET /api/obstacles?platform=&status=&page=&per_page=`
- `GET /api/obstacles/:id`
- `PATCH /api/obstacles/:id`
- `GET /api/obstacles/:id/outcomes?page=`
- `GET /api/obstacles/stats`

Auth — тот же 401-protected pattern как `/api/publish/testbench/*`.

## 10. Kill-switches

| # | Switch | Эффект | Latency |
|---|---|---|---|
| 1 | `system_flags.obstacle_kb_disabled = true` | `lookup_obstacle()` возвращает None → AI Unstuck идёт прямо в LLM (как раньше). Outcomes продолжают писаться | <30 sec |
| 2 | `system_flags.obstacle_kb_lookup_only = true` | lookup работает, но apply для stable — noop (shadow mode) | <30 sec |
| 3 | `system_flags.obstacle_promoter_disabled = true` | promoter tick — noop. T1/T2/T3 не работают | <5 min |
| 4 | `system_flags.obstacle_kb_anthropic_disabled = true` | fallback на legacy `_call_groq_vision` | <30 sec |
| 5 | `system_flags.obstacle_curator_bot_disabled = true` | Telegram-уведомления не шлются. Patterns тихо в `candidate` | <5 min |
| 6 | Surgical: `UPDATE publisher_obstacles SET status='blacklisted' WHERE obstacle_id=$1` | Конкретный pattern перестаёт применяться | <30 sec |
| 7 | Nuclear: `DROP TABLE publisher_obstacles, publisher_obstacle_outcomes` | После: revert commit удаления in-code constants | manual ~10 min |

## 11. Observability

**SQL queries (новый файл `obs_queries.sql`):**
- Health: patterns by status + avg confidence
- Hit-rate 7d (KB applied vs LLM-fallback vs failures)
- Top-10 most-applied patterns
- Drift watch: stable patterns с `last_fail_at > last_success_at`

**Dashboard panel в `testbench.html`** — новый блок «Obstacle KB» с 4 KPI:
1. Total patterns by status
2. KB hit-rate 24h (% stuck с pattern-match)
3. Top-5 most-applied
4. Auto-degrade events 7d

**Cost tracking:** Anthropic vision calls пишутся в существующий `agent_runs` (как Groq calls). Новая запись в `agent_runs` с `agent='obstacle_kb_action'` и `cost_usd=0` — для подсчёта savings (сколько LLM-вызовов мы избежали через KB hit).

## 12. Testing strategy

| Module | Test count | Тип |
|---|---|---|
| `test_obstacle_signatures.py` | ~25 | Unit — нормализация, hash determinism, edge cases |
| `test_obstacle_kb.py` | ~15 | Unit + integration (real DB через autouse engine.dispose) |
| `test_obstacle_actions.py` | ~15 | Unit — все action_types + ADB error handling |
| `test_obstacle_promoter.py` | ~10 | Unit — T1/T2/T3 criteria |
| `test_obstacle_handlers.py` (в `contenthunter_bugs_bot/`) | ~8 | Unit — callback handlers (Approve/TryOnce/Blacklist/Comment) |
| `test_obstacle_full_flow.py` | ~5 | Integration — stuck→sig→lookup→apply→outcome |
| `test_obstacle_seed.py` | ~5 | Integration — B1 migration assertions |

**Smoke test (live на phone #19):** 24h baseline с `obstacle_kb_disabled=true` (shadow log only) → enable → 24h apply → compare success_rate.

## 13. Rollout plan (6 weeks)

| Week | Deploy | Готовность | Risk |
|---|---|---|---|
| **W1** | Migrations (3 SQL) + 5 kill-switches + skeleton modules | Schema готова, kill-switches verified | Low (additive only) |
| **W2** | `obstacle_signatures.py` + `obstacle_kb.py` + B1 seed + удаление in-code constants + замена на lookup. Anthropic switch enabled | Same code paths через DB | **Medium** (refactor existing) — нужен 100% test coverage перед deploy |
| **W3** | Integration shim в `ai_unstuck` (Опция 1+3 + lift в base) + post-LLM hook + triage mining hook. **Shadow mode** (`obstacle_kb_lookup_only=true`) | Hit-rate measured без apply риска | Low (только observation) |
| **W4** | Disable shadow mode → apply stable actions. Monitor success_rate delta. Vision postmortem на Claude | Production применение patterns | **Medium** — реальный apply, kill-switch readiness |
| **W5** | `obstacle_promoter` enabled. T1/T2/T3 active. `obstacle_handlers` в `bugs_catcher_bot`. **B2 mining** + Telegram review | Self-curating loop работает | Medium — bot-side risks |
| **W6** | `admin UI` (obstacles.html + 5 endpoints) + KPI panel в testbench.html | Full visibility | Low (read-mostly UI) |

## 14. Risks & mitigations

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | Signature collision (false-positive match) | Medium | Shadow-mode logging в W3 — увидим до apply. При детектe — добавить дискриминативные features |
| 2 | Stable pattern с broken action ломает task | Medium | Outcome detection (post-state check). T3 degrade на 3 consecutive fails. Manual blacklist |
| 3 | Anthropic outage — vision call падает | Low-Medium | Kill-switch #4 fallback на legacy Groq. Code оставлен на 1 release. Chaos-test через `/etc/hosts` |
| 4 | B1 migration ломает существующее поведение | **Medium-High** | W2 атомарный PR: добавить DB lookup → tests pass → удалить constants → tests pass → merge. Pre-commit grep-guard на reintroduction |
| 5 | Telegram bot не отвечает — `candidate` зависают | Low | Kill-switch + manual SQL approve. Health-check ping из promoter |
| 6 | DB load — каждый stuck = SELECT | Low | PK index на `obstacle_id`. Measure latency в W3. pgbouncer если >100ms |
| 7 | Cost runaway — Anthropic больше estimate | Low | `agent_runs` cost tracking. Telegram alert на $10/day threshold |
| 8 | In-code regression — PR re-introduce удалённые constants | Low-Medium | Pre-commit hook: grep `_IG_HUMAN_CHECK_MARKERS\|_IG_EDITOR_RESOURCE_IDS\|_OZON_AD_MARKERS` в `publisher_*.py` → reject |
| 9 | Triage mining шумит — мусорные candidates | Medium | Filter: `len(resource_ids) >= 3 AND len(key_texts) >= 2`. Поднять threshold если шум |
| 10 | `Try Once` button race | Low | Atomic SQL `UPDATE ... SET apply_limit = apply_limit - 1 WHERE apply_limit > 0 RETURNING *` |

## 15. Success criteria — Definition of "MVP shipped"

После W6:

- [ ] ≥30 patterns в `publisher_obstacles` (B1 + B2 + online accumulation)
- [ ] ≥10 patterns со `status='stable'`
- [ ] **KB hit-rate ≥30%** за rolling 7-day window (≥30% stuck'ов решаются без LLM)
- [ ] **AI Unstuck overall success-rate ≥40%** (KB applied OR LLM action progressed) — vs текущий 0%
- [ ] 0 false-positive incidents (apply сломал task'у которая бы прошла) — measured via before/after success_rate per platform
- [ ] Admin UI доступен, KPI panel показывает текущие metrics
- [ ] Все 7 kill-switches протестированы через manual chaos-test

## 16. Open questions / TBD

- **`agent_diagnose` text-pipeline на Claude vs Groq** — пользователь сказал «всё на Claude» но agent_diagnose это text-only narrative для investigations, не vision. Можно мигрировать в той же сессии или оставить на Groq. **Решение:** мигрировать тоже (single-stack принцип), но не блокирует MVP, можно отложить до W7+.
- **Per-platform kill-switches** — пользователь сказал «пока не знаю, оставим как есть». Можно добавить позже (additive в `system_flags`).
- **GC stale patterns (>30d no match)** — пока not in scope. Может вырасти до 1000+ patterns без чистки. Пересмотреть после 6 месяцев в проде.

---

**Конец спека. После user review → `writing-plans` для implementation plan по неделям W1-W6.**
