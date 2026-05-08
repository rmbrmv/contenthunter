# Evidence — Publish Dup Incident 2026-05-08

## Symptom
Операторы (Наталья, Ирина):
- phones 127/128/129: вчера 2 одинаковых видоса в выкладке
- phones 142/143: видео на 15 мая выложилось сегодня
- @clickpay_now: «карусель документов» вместо нашего видео

## 3 Root Causes

| # | Bug | RC | Файл-источник |
|---|---|---|---|
| A | Past-slot backfill | RC-1..5 | autowarm: `unic_sweep.js`, `assignUnicResultsToQueue` server.js:5644; validator: `schedule.py` (RC-1 в Spec B) |
| B | Slot moved после pipeline picked | RC-7 | validator: `schedule.py:130-300` (3 endpoints без notify); autowarm: `assignUnicResultsToQueue`, `dispatchPublishQueue` без guard |
| C | IG gallery picker → wrong media | RC-8 | autowarm: `publisher_base.py:3267-3290` (single-MS check), `publisher_instagram.py:1255+1280` (unsafe фолбэки) |

## Stop-gap (выполнено ~11:00 UTC)
- 46 publish_queue rows cancelled (4 past-slot + 42 content 2022)
- unic-sweep отключён: `sudo pm2 set autowarm:UNIC_SWEEP_DISABLED 1 && sudo pm2 restart autowarm`
- Verify: 0 sweep ticks через 15 мин после restart

## Fixes shipped (commits на main)

### autowarm (origin/main: `7212e6c → fab52dc`, 9 commits, +2451 строк)
**Spec B (RC-7):**
- `c37fe00` — dedicated client + advisory lock в assignUnicResultsToQueue
- `88a731d` — dispatcher guard на slot lineage + race tests

**Spec A (RC-2/4/5):**
- `f7ee430` — trigger-immediate расширить на future slots (window=14d)
- `1ff3dc8` — clamp pubDate>=today + durable audit (status='past_slot_dropped')
- `82928ea` — cross-TZ + DST + concurrent webhook tests

**Spec C (RC-8):**
- `e59825c` — MediaStore double-query (video+images отдельно) + retry × 5
- `6815c3b` — gallery picker fail-fast (удалены all_clickable[0] + blind tap)
- `46f7d90` — cleanup screen recorder paths pre-push
- `fab52dc` — duration sanity check перед Share

### validator (origin/main: `bb33078 → cdda4a5`, 3 commits, +905 строк)
**Spec B (RC-1, RC-7):**
- `57d78a1` — pipeline_reversal service (acquire_slot_lock + cancel_downstream_for_content)
- `bab23cb` — wire pipeline_reversal в update_slot/swap_slots/move_unpublished

**Spec A (RC-4):**
- `cdda4a5` — notify autowarm после image validation approve

## Tests
- autowarm: 82 npm tests passed (B+A: 22 + C: на отдельном test file 22 + existing 38). +63 новых
- validator: 74 pytest passed (3 new для image notify + 9 для pipeline_reversal/schedule). 2 pre-existing failures (stale Anthropic mocks — НЕ регрессии)

## Codex review iterations
1. Brief Bug A → 5 RC уточнений
2. Brief Bug B + C → 5 уточнений каждому
3. Spec C v2 → 5 правок
4. Spec B v2 → critical (JS BEGIN/COMMIT, lineage filter, ordered locks, D5 backfill)
5. Spec A v2 → critical (PG DATE string, dedupe, durable audit)

## Deploy steps remaining (для пользователя)

1. **Prod pull (validator):** `cd /root/.../validator && git pull origin main`
2. **Prod pull (autowarm):** `cd /root/.../autowarm && git pull origin main`
3. **Restart prod services** (требует root SSH):
   - `pm2 restart validator` (или systemd unit)
   - `sudo pm2 restart autowarm`
4. **Re-enable sweep** после deploy (D3 clamp защищает):
   ```
   sudo pm2 unset autowarm:UNIC_SWEEP_DISABLED
   sudo pm2 restart autowarm
   ```
5. **Monitor 24ч:**
   - `past_slot_dropped` events в publish_queue: должно быть >0 первые часы (sweep ловит yesterday-slots), затем ↓ к 0
   - `slot_no_longer_valid` events: должны появляться при swap/move оператором
   - `media_store_pollution_pre_publish` events: метрика поллюции gallery
   - `awaiting_url` IG count: должно вернуться к 0 (сегодня было 8)

## Phase 2 (через 2-4 нед observation)
В backlog: убрать `yesterday` из sweep window (D4) после verification что trigger-immediate ловит все cases.

## Forensic queries для post-deploy verification

```sql
-- past_slot_dropped: сколько раз clamp защитил
SELECT count(*) FROM publish_queue WHERE status='past_slot_dropped' AND created_at > NOW() - interval '24 hours';

-- slot_no_longer_valid: сколько slot-moves обработано
-- (события в pm2 logs, не в БД — grep '"slot_no_longer_valid"')

-- awaiting_url IG регрессия:
SELECT count(*) FROM publish_tasks WHERE platform='Instagram' AND status='awaiting_url' AND created_at > NOW() - interval '24 hours';

-- past slot vs validator slot mismatch:
SELECT ut.id, ut.content_id, ut.slot_date AS unic_date, vss.slot_date AS validator_date
FROM unic_tasks ut JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int
WHERE ut.created_at > NOW() - interval '7 days' AND ut.slot_date != vss.slot_date;
-- Должно быть 0 после deploy (D7 guard cancel'нет stale)
```
