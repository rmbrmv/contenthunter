# Spec D — Slot Move Updates Publish Date (SHIPPED 2026-05-13)

**PR:** [GenGo2/validator-contenthunter#9](https://github.com/GenGo2/validator-contenthunter/pull/9)
**Merge commit:** `eab5791`
**Branch:** `feat/slot-move-update-publish-date-20260513`
**Spec:** validator `.ai-factory/specs/spec-d-slot-move-update-publish-date.md`
**Plan:** validator `.ai-factory/plans/feat-slot-move-update-publish-date-20260513.md`

## Pain closed

Симптом (живой 2026-05-13 со слов пользователя): «клиент запланировал контент на дату, в тот день запустилась уникализация, поставилась publish_task; клиент двинул слот на другую дату → publish_task осталась с старой датой → пост вышел в старый день».

Spec B Phase 1 (shipped 2026-05-08) закрыла этот RC только для случая «pq.pending к моменту slot mutation» — cancel + регенерация. Но не закрыла:
1. **Class B/C** (тот же контент, новый slot) → cancel + regen теряет уникализацию, regenerate медленно.
2. **Race с running publisher** — если к моменту move'а pq уже claim'нул dispatcher (publish_task создан), Spec B по дизайну не отменяет (Non-Goal). Это и было источником живого симптома.

## Архитектура решения

**3-layer защита:**

| Слой | Файл | Что |
|---|---|---|
| L1 — UI lock | `frontend/src/components/calendar/SlotCard.vue` + `frontend/src/pages/client/ClientDashboard.vue` | `isPublishing` computed/checks → drag отключён + ⏳ публикуется badge (amber) + onDragStart JS guard |
| L2 — Backend 409 guard | `backend/src/routers/schedule.py` (3 endpoint'a) | `get_publishing_flags` проверяется ПЕРЕД mutation → 409 если контент `running` ИЛИ `claimed-pending` |
| L3 — Race-detect после UPDATE | `backend/src/services/pipeline_reversal.py` `update_downstream_dates_for_content` | `irrecoverable_running` теперь учитывает claimed-pending; caller raise 409 при `> 0` → rollback slot mutation |

**Class разделение:**
- **Class A (контент сменяется, `update_slot` X→Y или X→null)** — Spec B `cancel_downstream_for_content` без изменений.
- **Class B/C (тот же контент, новый slot — `move_unpublished` + `swap_slots`)** — новый helper `update_downstream_dates_for_content`: cancel pending pq + переадресовать `unic_tasks.slot_date`/`meta.slot_id` (не cancel), notify → autowarm пересоберёт pq через свой device-chaining.

**Critical safeguard:** `pq.publish_task_id IS NULL` в WHERE update'а — не трогаем pq, для которой dispatcher уже создал publish_task (race с claim).

## Commits (14 + 1 race-fix)

```
22fae85 fix(spec-d): race-detect claimed-pending после UPDATE (codex P1)
6e96932 feat(client-dashboard): is_publishing в inline slot renderer (Spec D D4)
5a00e8f feat(slot-card): is_publishing badge + drag guard (Spec D D4)
688c66e feat(schedule): is_publishing flag в /schedule response (Spec D D4 backend)
3b2cc5d fix(schedule): extract _PUBLISHING_GUARD_DETAIL constant + simplify test asserts
ad02773 feat(schedule): 409 guard блокирует move/swap/update_slot когда контент publishing (Spec D D3.b)
3789307 feat(publish-summary): add get_publishing_flags batch helper (Spec D D3.a)
ed9993a feat(schedule): swap_slots обновляет dates обоих контентов (Spec D D2.b)
6887a9f feat(schedule): move_unpublished обновляет dates вместо cancel (Spec D D2.a)
68228b3 fix(pipeline-reversal): quality nits для update_downstream helper
8cfca26 feat(pipeline-reversal): add update_downstream_dates_for_content helper (Spec D D1)
+ 4 spec/plan docs commits с codex P1 fixes
```

## Tests

- **Spec D suite:** 54/54 passed (`test_pipeline_reversal.py` + `test_schedule_pipeline_reversal.py` + `test_publish_summary_service.py` + `test_schedule_lock.py`).
- **+18 new tests:** D1 helper (6) + D2 move/swap (3) + D3 publishing_flags (3) + D4 schedule response (4) + race-detect (2).
- **0 regressions** в Spec B existing tests; updated 4 Spec B tests где expectations изменились (move/swap теперь redirect not cancel).

## Codex review history

6 раундов до 0 P1:
- **Spec round 1 (P2):** SQL canary join через `pq.unic_task_id` напрямую → переписан на `unic_results` для консистентности.
- **Plan round 1 (P1):** `get_publishing_flags` ловил только `running`, пропускал claimed-pending → расширен.
- **Plan round 2 (P1):** `update_slot` guard обёрнут в `if content_id is not None` → дыра для partial update; вытащен из wrapper'а, всегда проверяет `old_content_id`.
- **Plan round 3:** clean.
- **Final diff round 1 (P1):** TOCTOU race — между `get_publishing_flags` guard и UPDATE dispatcher может claim'нуть pq → fix: `irrecoverable_running` учитывает claimed-pending + callers raise 409 при `> 0`.
- **Final diff round 2:** clean.

## Deployment

- **Merge:** 2026-05-13, commit `eab5791` в `GenGo2/validator-contenthunter` main.
- **Prod deploy:** заблокирован uncommitted hot-patch на prod (schemes.py -470 lines + scheme_preview_queue.py untracked) — требует ручной resolve пользователем (stash/commit перед `git pull origin main`).
- **PM2 restart needed:** `sudo pm2 restart validator-backend` после prod pull.
- **Frontend build:** `cd /root/.openclaw/workspace-genri/validator/frontend && npm run build` (postbuild hook автодеплоит в `/var/www/validator/` per memory `feedback_validator_postbuild_autodeploy`).

## Post-deploy monitoring (24h)

```sql
-- canary: publish_task started_at в дне ≠ vss.slot_date → 0 ожидается
SELECT count(*) AS leaked_past_publishes
FROM publish_tasks pt
JOIN publish_queue pq ON pq.publish_task_id=pt.id
JOIN unic_results ur ON ur.id=pq.unic_result_id
JOIN unic_tasks ut ON ut.id=ur.task_id
JOIN validator_schedule_slots vss ON vss.id=(ut.meta->>'slot_id')::int
WHERE pt.created_at > now() - interval '24 hours'
  AND pt.started_at IS NOT NULL
  AND DATE(pt.started_at) != vss.slot_date;
```

```sql
-- 409 rate: guard работает, но не часто (rare race)
-- grep pm2 logs validator-backend на 'Контент уже в процессе публикации'
```

## Smoke (testbench phone #19, USER ACTION)

1. Запланировать контент на завтра → дождаться pq.pending (publish_task ещё не создан) → перетащить slot в другую дату через UI → SQL check:
   - `publish_queue` для контента: `status='cancelled'`, `skip_reason='moved_from_slot_*'`
   - `unic_tasks`: `slot_date=new_date`, `meta.slot_id=new_slot_id`, `current_status='done'` (не cancelled)
   - Через 1-2 мин: autowarm создал новый pq на новой дате
2. Дождаться `publish_task running` для контента → drag в UI должен быть заблокирован, ⏳ badge виден; форсированный POST `/schedule/move-direct` через curl → 409 «Контент уже в процессе публикации».

## Open follow-ups

- Manual smoke (Task 9 в плане) — пользователь делает после prod deploy.
- 24h post-deploy SQL canary мониторинг.
- Prod schemes.py hot-patch resolve (deploy blocker, не связан со Spec D).
- Race-detect coverage для `update_slot` (class A) — backlog: Spec B `cancel_downstream_for_content` имеет тот же изъян TOCTOU, но scope Spec D не покрывает.
