# WP #85 — Признак ручной выкладки в планировщике

**OpenProject:** [WP #85](https://openproject.contenthunter.ru/work_packages/85) "Добавить признак ручной выкладки в планировщик"
**Status:** Запланировано · **Priority:** Высокий · **Assignee:** Данил
**Date:** 2026-05-19
**Author:** Claude (брейншторм с Данилом)

---

## 1. Цель

Прозрачная статистика «сколько публикаций выкладывается автоматически vs вручную». Для этого:

1. Admin может пометить слот как «выкладывается вручную» → отключаем для него автопайплайн.
2. Парсер соцсетей (existing `posts_parser.py`) подтверждает факт публикации, проставляя `status='published'` на слот сопоставив пост по описанию.
3. Admin видит агрегаты «auto vs manual» в календаре и Analytics.

Парсер-confirmation работает **для всех слотов** (manual и auto) — для manual это единственный источник истины, для auto это backup-подтверждение если URL-capture фейлится.

---

## 2. Scope

**В скоупе:**
- Тогл `manual_publish` на слоте (admin-only RBAC).
- Cancel-downstream при включении (переиспользуем `cancel_downstream_for_content`).
- Matcher-cron в autowarm: factory_inst_reels → validator_schedule_slots на платформах IG / TT / YT.
- UI: тогл и баджи в SlotCard.vue; admin-метрика на calendar; новый блок в admin Analytics.
- Endpoint `GET /api/admin/publication-stats`.

**Out of scope:**
- VK / FB / X (не публикуем, парсер VK не используется для матча).
- Графики динамики по дням / по платформам (отдельный WP при запросе).
- Перерендер карточки контента (рендер слота централизован в `SlotCard.vue`).

---

## 3. RBAC

| Роль | Видит тогл | Меняет тогл | Видит matched_*, manual_* поля | Видит stats |
|------|:-:|:-:|:-:|:-:|
| client | ✗ | ✗ | ✗ | ✗ |
| manager | ✗ | ✗ | ✗ | ✗ |
| producer | ✗ | ✗ | ✗ | ✗ |
| admin | ✓ | ✓ | ✓ | ✓ |

Enforce на трёх уровнях: backend endpoint `require_role(UserRole.admin)`, `_slot_to_dict` фильтрует поля по `viewer_role`, frontend условный рендер по auth store.

---

## 4. Schema changes

Миграция alembic: `backend/alembic/versions/00X_wp85_manual_publish.py`

```sql
ALTER TABLE validator_schedule_slots
  ADD COLUMN manual_publish         boolean NOT NULL DEFAULT false,
  ADD COLUMN manual_publish_set_by_id integer NULL REFERENCES validator_users(id),
  ADD COLUMN manual_publish_set_at    timestamp with time zone NULL,
  ADD COLUMN matched_post_id          integer NULL,
  ADD COLUMN matched_post_url         text NULL,
  ADD COLUMN matched_at               timestamp with time zone NULL,
  ADD COLUMN match_confidence         numeric(4,3) NULL;

CREATE INDEX ix_slots_manual_unmatched
  ON validator_schedule_slots (project_id, slot_date)
  WHERE manual_publish = true AND matched_at IS NULL;

-- index для matcher-batch SELECT (если ещё нет):
CREATE INDEX IF NOT EXISTS ix_reels_synced_platform
  ON factory_inst_reels (synced_at, platform)
  WHERE udalen IS NULL;
```

Дополнительно к существующей `unic_settings` (id=1) — добавить через INSERT/UPDATE поле:

```sql
ALTER TABLE unic_settings
  ADD COLUMN IF NOT EXISTS matcher_enabled boolean NOT NULL DEFAULT true;
```

**Решения по схеме:**
- `matched_post_id` без FK — `factory_inst_reels` принадлежит autowarm-domain; FK создал бы cross-domain coupling и риск migration-break.
- `match_confidence numeric(4,3)` — диапазон 0.000–1.000.
- `status` enum не меняем: matcher переводит в существующее `'published'`.
- `manual_publish=false` по умолчанию ≡ автовыкладка (отдельной `auto_publish` колонки не нужно).

---

## 5. Backend API

### 5.1 Новый endpoint

```
PATCH /api/schedule/slots/{slot_id}/manual-publish
Body: {"manual_publish": bool}
RBAC: admin only
```

**Логика** (`backend/src/routers/schedule.py`):

```python
@router.patch("/slots/{slot_id}/manual-publish",
              dependencies=[Depends(require_role(UserRole.admin))])
async def set_manual_publish(slot_id: int, data: dict,
                              current_user, db):
    new_value = bool(data.get("manual_publish"))
    async with db.begin():
        slot = await db.execute(
            select(ValidatorScheduleSlot)
            .where(ValidatorScheduleSlot.id == slot_id)
            .with_for_update()
        )
        slot = slot.scalar_one_or_none()
        if not slot:
            raise HTTPException(404, "Slot not found")
        if not slot.content_id:
            raise HTTPException(400, "Slot is empty")
        if slot.status == SlotStatus.published:
            raise HTTPException(409, "Slot already published")

        await acquire_slot_lock(db, slot_id)

        warning = None
        if new_value and not slot.manual_publish:
            stats = await cancel_downstream_for_content(
                db, slot.content_id,
                keep_slot_id=None,
                reason=f"manual_publish_enabled_slot_{slot_id}",
            )
            if stats.get("irrecoverable_running", 0) > 0:
                warning = "publish-task в работе, дубль возможен"
            slot.manual_publish = True
            slot.manual_publish_set_by_id = current_user.id
            slot.manual_publish_set_at = func.now()
            log.info("[manual-publish] enabled slot=%d cancelled %s",
                     slot_id, stats)
        elif not new_value and slot.manual_publish:
            slot.manual_publish = False
            slot.manual_publish_set_by_id = current_user.id
            slot.manual_publish_set_at = func.now()
            # matched_* НЕ чистим
            log.info("[manual-publish] disabled slot=%d", slot_id)

    await db.refresh(slot)
    result = _slot_to_dict(slot, viewer_role=current_user.role)
    if warning:
        result["warning"] = warning
    return result
```

### 5.2 `_slot_to_dict(viewer_role=...)` фильтр

Admin-поля (`manual_publish`, `manual_publish_set_at`, `matched_post_id`, `matched_post_url`, `matched_at`, `match_confidence`) включаются в response только если `viewer_role == UserRole.admin`. Это исключает утечку признака клиенту даже если фронт по ошибке покажет поле.

### 5.3 `cancel_downstream_for_content` — extension

В `backend/src/services/pipeline_reversal.py`: при отвязке content от слота (move-сценарий) — обнуляем `matched_post_id`, `matched_post_url`, `matched_at`, `match_confidence` целевого слота. Иначе при переносе остаётся «mismatched» матч.

```python
# Внутри cancel_downstream_for_content, ветка где slot перепривязывается
if keep_slot_id is not None and keep_slot_id != target_slot.id:
    target_slot.matched_post_id = None
    target_slot.matched_post_url = None
    target_slot.matched_at = None
    target_slot.match_confidence = None
```

### 5.4 Stats endpoint

```
GET /api/admin/publication-stats?project_id=&from=&to=
RBAC: admin only
```

Response:

```json
{
  "period": {"from": "2026-05-12", "to": "2026-05-18"},
  "total_filled": 15,
  "auto": 11,
  "manual": 3,
  "manual_unconfirmed": 1,
  "by_project": [
    {"project_id": 3, "project": "Content Hunter",
     "auto": 11, "manual": 3, "manual_unconfirmed": 1}
  ]
}
```

Расчёт:
- **auto**: `manual_publish=false AND status='published'`.
- **manual**: `manual_publish=true AND status='published'`.
- **manual_unconfirmed**: `manual_publish=true AND status<>'published' AND slot_date < CURRENT_DATE`.
- **total_filled**: `content_id IS NOT NULL AND slot_date BETWEEN from AND to`.

Параметр `project_id` опционален — без него по всем доступным проектам.

---

## 6. Frontend (Vue)

### 6.1 SlotCard.vue — изменения

Новый блок ТОЛЬКО для admin внутри filled-секции:

```vue
<div v-if="isAdmin && slot.content_id" class="flex items-center gap-1 mt-1">
  <button @click.stop="$emit('toggle-manual', slot)"
    :class="manualBtnClass"
    :title="manualTooltip">
    {{ slot.manual_publish ? '✋ вручную' : '🤖 авто' }}
  </button>
  <span v-if="slot.manual_publish && !slot.matched_at && isSlotPast"
    class="text-[10px] px-1 py-0.5 rounded bg-orange-100 text-orange-700"
    title="Пост не найден в соцсети">⚠️ не найден</span>
  <span v-if="slot.matched_at"
    class="text-[10px] px-1 py-0.5 rounded bg-green-100 text-green-700"
    :title="`Подтверждён парсером ${matchedRelative} (similarity ${matchConfidence})`">
    ✓ подтв.
  </span>
</div>
```

Пропсы: `isAdmin: boolean` (из родителя, из auth store). Без пропа компонент рендерится как сейчас.

Event `toggle-manual` ловится в родителе (Calendar component), который дёргает `PATCH /slots/{id}/manual-publish`.

### 6.2 Calendar header (ManagerDashboard.vue)

Для admin рядом с week-switcher добавить компактный бадж:

```
📊 11 авто · 3 ✋ · ⚠️ 1 не подтв.
```

Источник — `GET /api/admin/publication-stats?project_id=<current>&from=<week_start>&to=<week_end>`. Refetch при смене недели.

### 6.3 AnalyticsPage.vue — новый блок

Admin раздел получает блок «Источник публикаций» — таблица по проектам с колонками **Авто / Вручную / Не подтв.**. Фильтр периода: `неделя | месяц | за всё время`. Источник — тот же endpoint с агрегацией.

---

## 7. Matcher cron (autowarm)

### 7.1 Локация

Новая функция `runSlotMatcher()` в `autowarm-testbench/server.js` (как `runPostsParser`). `setInterval(runSlotMatcher, MATCHER_INTERVAL_MS)`.

### 7.2 ENV / DB-flag

| Имя | Default | Назначение |
|-----|---------|------------|
| `SLOT_MATCHER_ENABLED` | `true` | Hard kill-switch. |
| `SLOT_MATCHER_INTERVAL_MS` | `300000` (5 min) | Период tick. |
| `SLOT_MATCHER_WINDOW_DAYS` | `3` | Окно ±N от slot_date. |
| `SLOT_MATCHER_SIMILARITY_MIN` | `0.7` | Порог fuzzy match. |
| `SLOT_MATCHER_BATCH` | `200` | Max постов за tick. |
| `MANUAL_PUBLISH_TOGGLE_ENABLED` | `true` | Soft-disable нового включения тогла (legacy не трогает). |
| DB `unic_settings.matcher_enabled` | `true` | Soft-switch без рестарта. Читается каждый tick. |

### 7.3 Алгоритм

**Шаг 1 — кандидаты** (один SQL):

```sql
WITH fresh_posts AS (
  SELECT r.id AS post_id, r.account_id, r.platform, r.caption, r.url,
         r.timestamp::timestamp AS post_ts, a.pack_id
  FROM factory_inst_reels r
  JOIN factory_inst_accounts a
    ON a.instagram_id = r.account_id AND a.platform = r.platform
  WHERE r.platform IN ('instagram','tiktok','youtube')
    AND r.synced_at > now() - interval '24 hours'
    AND r.udalen IS NULL
),
account_projects AS (
  SELECT DISTINCT fp.post_id, vp.id AS project_id
  FROM fresh_posts fp
  JOIN factory_reg_accounts fra ON fra.pack_id = fp.pack_id
  JOIN validator_projects vp ON vp.project = fra.project
)
SELECT fp.post_id, fp.caption, fp.url, fp.post_ts, ap.project_id,
       s.id AS slot_id, s.content_id, s.slot_date,
       s.manual_publish, c.description, c.title
FROM fresh_posts fp
JOIN account_projects ap ON ap.post_id = fp.post_id
JOIN validator_schedule_slots s ON s.project_id = ap.project_id
JOIN validator_content c ON c.id = s.content_id
WHERE s.content_id IS NOT NULL
  AND s.matched_at IS NULL
  -- matcher работает для: (a) manual слотов; (b) auto-слотов уже-published (backup-подтверждение).
  -- Filled auto-слоты не трогаем — это работа auto-pipeline; иначе создадим дубль публикации.
  AND (s.manual_publish = true OR s.status = 'published')
  AND s.slot_date BETWEEN (fp.post_ts::date - $WINDOW * interval '1 day')::date
                      AND (fp.post_ts::date + $WINDOW * interval '1 day')::date
LIMIT $BATCH;
```

**Скоп matcher'а по типу слота:**

| `manual_publish` | `status` | Действие matcher'а |
|:-:|:-:|---|
| `true` | `filled` | UPDATE: проставить `status='published'` + matched_*. Основной кейс. |
| `true` | `published` | UPDATE: matched_* (status уже published — не меняем). |
| `false` | `published` | UPDATE: matched_* (backup-confirmation URL/post evidence для auto). |
| `false` | `filled` | **Skip.** Auto-pipeline ещё в работе; matcher не должен опередить и сделать дубль. |

**Шаг 2 — match score** (для каждой пары post×slot):

```js
function normalizeText(s) {
  return (s || '').toLowerCase()
    .replace(/#\S+/g, ' ')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// substring exact → 1.0
// иначе pg_trgm similarity (батч через UNNEST)
```

**Шаг 3 — дезамбигуация:**
- Один пост → несколько слотов: берём `min(abs(slot_date - post_ts))`, tie → `min(slot_id)`.
- Один слот → несколько постов: берём `max(score)`, tie → `min(post_ts)`.
- Если для проекта в окне ≥2 слотов с одинаковым description (substring=1.0): требуем `score > 0.9` и ближайший slot_date, иначе skip (защита от false-positives).

**Шаг 4 — UPDATE** (idempotent guard):

```sql
-- Заполняем matched_* всегда; status переводим в 'published' только если ещё не published.
UPDATE validator_schedule_slots
SET status = CASE WHEN status <> 'published' THEN 'published'::slot_status ELSE status END,
    matched_post_id = $post_id,
    matched_post_url = $url,
    matched_at = now(),
    match_confidence = $score,
    updated_at = now()
WHERE id = $slot_id
  AND content_id = $expected_content_id
  AND matched_at IS NULL;        -- единственная idempotency guard
```

Сопутствующий UPDATE `validator_content.status='published'` (если ещё не published) — для consistency `is_published` UI-флага. Если content уже published, no-op.

### 7.4 Защита auto-pipeline от manual слотов

В `assignUnicResultsToQueue` (server.js) добавить JOIN-guard в WHERE:

```sql
... AND NOT EXISTS (
  SELECT 1 FROM validator_schedule_slots vss
  WHERE vss.id = (ut.meta->>'slot_id')::int
    AND vss.manual_publish = true
)
```

Без этого guard — toggle ON отменил pending pq, а следующий cron tick «воскресил» его.

### 7.5 is_published — расширение

`backend/src/services/publish_summary_service.get_published_flags` — расширяем: content_id считается published если хоть один из:
- Есть `publish_queue done`-row (текущее поведение).
- ИЛИ `validator_schedule_slots.matched_at IS NOT NULL` для слота с этим content_id.

---

## 8. Edge cases

| # | Сценарий | Поведение |
|---|----------|-----------|
| 1 | Toggle ON, pq running | Cancel pending OK, running остаётся; response warning. UI: toast. |
| 2 | Toggle ON, slot уже published | 409. |
| 3 | Toggle OFF до slot_date | `assignUnicResultsToQueue` поднимет unic_result → pq. |
| 4 | Toggle OFF, unic_results уже cancelled | Admin нажимает «Перезалить» (existing re-queue flow). |
| 5 | Matcher: 2 слота для 1 поста | `min(abs(slot_date - post_ts))`, tie → `min(slot_id)`. |
| 6 | Matcher: 2 поста для 1 слота | `max(score)`, tie → `min(post_ts)`. |
| 7 | `len(description) < 10` | Skip (защита от false-positives). |
| 8 | Дублирующиеся descriptions в проекте | Substring=1.0 + ≥2 кандидата → `score > 0.9` + ближайший slot_date обязательны. |
| 9 | Orphan account (нет factory_reg_accounts) | Skip + лог `[slot-matcher] orphan account=X`. |
| 10 | post_ts в будущем / >30 дней назад | Не попадает в окно. |
| 11 | `factory_inst_reels.udalen <> NULL` | Skip; уже сматченные не трогаем. |
| 12 | content.description поменялся после match | Не re-match (matched_at idempotent guard). |
| 13 | Move slot после match | `cancel_downstream_for_content` обнуляет matched_*. |
| 14 | Validator down | Matcher всё равно бежит (autowarm), пишет в общую БД. |
| 15 | Apify quota исчерпан | Парсер не обновил reels → matcher не найдёт пост → бадж «не найден» по окну. |
| 16 | Race: toggle и matcher одновременно | `with_for_update()` + matcher idempotent guard. |
| 17 | Race: matcher и `update_slot` (move content) | matcher проверяет `content_id = $expected` в UPDATE. |

---

## 9. Observability

Лог-tag `[slot-matcher]` для всех событий:
```
[slot-matcher] tick start
[slot-matcher] candidates=N posts=K slots=M
[slot-matcher] matched slot=X content=Y post=Z platform=instagram score=0.83 reason=similarity
[slot-matcher] ambiguous_dropped post=Z slots=[X,Y] reason=duplicate_description
[slot-matcher] orphan account=X platform=instagram
[slot-matcher] tick end matched=M skipped_short=K skipped_threshold=J ambiguous=A
```

Метрики (через existing audit-log если есть, иначе counter в логах):
- `matcher.ticks`
- `matcher.posts_seen`
- `matcher.matched`
- `matcher.skipped_short_desc`
- `matcher.skipped_below_threshold`
- `matcher.ambiguous_dropped`
- `matcher.orphan_accounts`

---

## 10. Testing strategy

### 10.1 Backend pytest (`backend/tests/test_manual_publish.py`, live-DB)

- `test_toggle_on_admin_succeeds` — admin может включить, поля заполнены.
- `test_toggle_on_producer_403`, `test_toggle_on_client_403` — RBAC.
- `test_toggle_on_empty_slot_400` — нет content_id.
- `test_toggle_on_published_slot_409` — уже published.
- `test_toggle_on_cancels_pending_pq` — pending pq → cancelled.
- `test_toggle_on_with_running_pq_warns` — running pq → 200 + warning.
- `test_toggle_off_re_enables_auto` — следующий assign-cron создаёт новый pq.
- `test_slot_dict_admin_sees_manual_fields` — admin response содержит все поля.
- `test_slot_dict_non_admin_hides_manual_fields` — producer/manager/client не видят.
- `test_publication_stats_endpoint_admin_only` — RBAC.
- `test_publication_stats_aggregation` — счётчики правильные.
- `test_cancel_downstream_clears_matched_on_move` — move обнуляет matched_*.

### 10.2 Matcher tests (`autowarm-testbench/test_slot_matcher.test.js`, node --test)

- `match_substring_exact_score_1`.
- `match_similarity_above_threshold`.
- `match_below_threshold_skipped`.
- `match_outside_window_skipped`.
- `match_short_description_skipped`.
- `match_ambiguous_two_slots_picks_closest_date`.
- `match_ambiguous_two_posts_picks_max_score`.
- `match_ambiguous_dup_descriptions_requires_higher_threshold`.
- `match_idempotent_second_run`.
- `match_skips_deleted_posts` (udalen).
- `match_skips_orphan_accounts`.
- `matcher_disabled_env_skips_all`.
- `matcher_disabled_db_flag_skips_all`.
- `match_respects_batch_limit`.
- `match_concurrent_with_toggle_off_idempotent`.
- `match_backfills_matched_on_already_published_auto_slot` — UPDATE заполняет matched_* без смены status.
- `match_skips_when_matched_at_already_set` — idempotency guard.
- `match_respects_slot_content_id_guard`.

### 10.3 Frontend (Vitest)

- `SlotCard.spec` — admin видит / не-admin не видит / event emit / баджи.
- `ManagerDashboard.spec` — stats badge fetch + render.

### 10.4 E2E smoke (manual checklist в `evidence/wp85_*.md`)

1. Создать filled slot → admin включает toggle → cancel pending pq verified в БД.
2. Внести pseudo-post в `factory_inst_reels` с caption ⊃ description → подождать 5 мин → slot.status=published, matched_at заполнено.
3. Toggle OFF → `assignUnicResultsToQueue` создаёт новый pq pending.
4. Producer пытается `PATCH /slots/{id}/manual-publish` → 403.

### 10.5 Codex review

Spec → `codex review` → fix P1 до 0 → user review → implementation plan (см. memory `feedback_codex_review_specs`).

---

## 11. Implementation order

1. **Migration** alembic + `unic_settings.matcher_enabled`.
2. **Backend endpoint** `PATCH /slots/{id}/manual-publish` + RBAC + tests.
3. **`_slot_to_dict` viewer_role filter** + tests.
4. **`cancel_downstream_for_content` extension** (matched_* очистка) + tests.
5. **`publish_summary_service.get_published_flags` extension** (matched_at OR done).
6. **Stats endpoint** + tests.
7. **Frontend SlotCard.vue** + Vitest.
8. **Frontend Calendar badge + AnalyticsPage block**.
9. **Matcher cron** в server.js + node --test.
10. **`assignUnicResultsToQueue` guard** для manual слотов.
11. **Smoke E2E** на testbench.
12. **PR + Codex review + deploy**.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| False-match (две публикации с одинаковым description) | Substring=1.0 + ≥2 кандидата → требуем score>0.9 + nearest date; иначе skip. |
| matcher отвалится → нет статистики | env+DB kill-switch + `[slot-matcher]` log-tag для мониторинга tick'ов. |
| Race toggle ↔ matcher | `with_for_update()` + idempotent guard `matched_at IS NULL` в UPDATE. |
| `factory_inst_reels` схема ломается | `matched_post_id` без FK; matcher graceful skip orphan accounts. |
| Apify quota исчерпан | Парсер существующий, matcher просто не находит → бадж «не найден». |
| validator down во время matcher | matcher живёт в autowarm и пишет в общую БД. |
| Duplicate publish если toggle ON но pq running | Documented в warning'е (physical cancel невозможен); accepted limitation. |
| Producer случайно увидит manual_publish | Тройная защита: endpoint RBAC + _slot_to_dict фильтр + frontend isAdmin. |

---

## 13. Definition of Done

- [ ] Migration применена на dev + prod.
- [ ] Backend tests зелёные (новые + регрессия `pipeline_reversal`).
- [ ] Matcher tests зелёные (node --test).
- [ ] Frontend tests зелёные.
- [ ] Smoke E2E пройден на testbench, evidence в `docs/evidence/wp85_*.md`.
- [ ] Codex review раундами до 0 P1.
- [ ] User review spec'а одобрен.
- [ ] PR смержен в `delivery-contenthunter`.
- [ ] Kill-switches проверены: hard-disable matcher (env), soft-disable matcher (DB), soft-disable toggle (env).
- [ ] WP #85 закрыт в OpenProject с комментарием по house style (Что было не так → Что сделано → Что осталось).
