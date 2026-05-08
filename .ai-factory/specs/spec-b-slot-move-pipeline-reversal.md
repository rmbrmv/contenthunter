# Spec B — Slot Move Pipeline Reversal (RC-7)

**Дата:** 2026-05-08
**Инцидент:** content 2022 загружен в slot 5381 (05-08), pipeline создал unic_task 1670 со slot_date=05-08, оператор в 08:24 переместил в slot 5395 (05-15), но pipeline продолжил публиковать сегодня → 48 публикаций «видео на 15 мая» сегодня
**Codex review:** прошёл (см. `incident-brief-v2.md` секция RC-7)

---

## 1. Background

Pipeline в autowarm берёт `unic_task.slot_date` как **snapshot** в момент создания unic_task. Если оператор после этого переносит контент через `update_slot` / `swap_slots` / `move_unpublished` в другой слот (другая дата), downstream артефакты (unic_results, publish_queue, publish_tasks) **продолжают катиться по старому slot_date**.

### Forensic timeline (DB facts)

| Время (UTC) | Событие |
|---|---|
| 06:23:08 | Контент 2022 загружен (validator) |
| 06:23-06:24 | Контент попал в `slot.id=5381`, `slot_date=2026-05-08` (сегодня), position=2 |
| 06:24:59 | autowarm создал `unic_task.id=1670` со `slot_date=2026-05-08`, `meta.slot_id=5381` |
| 06:24-08:24 | unic прогнал → 16 unic_results → assignUnicResultsToQueue создал **48 строк publish_queue** на сегодня |
| **08:24:04** | Оператор перенёс content 2022 из slot 5381 в `slot.id=5395`, `slot_date=2026-05-15` (через 7 дней) |
| 09:08-10:03 | 6 публикаций состоялись на phones 142/143 (raspberry 7) — **slot 5395 уже филлед на 05-15, но pipeline опубликовал сегодня** |
| 10:30+ | 42 строки в pending — остановили SQL stop-gap'ом |

Запрос для воспроизведения:
```sql
SELECT ut.id AS unic_task_id, ut.content_id, ut.slot_date AS unic_slot_date,
       vss.slot_date AS validator_slot_date, vss.id AS validator_slot_id,
       (ut.meta->>'slot_id')::int AS lineage_slot_id
FROM unic_tasks ut
JOIN validator_schedule_slots vss ON vss.id = (ut.meta->>'slot_id')::int  -- Codex: JOIN по lineage, не content_id
WHERE ut.created_at > now() - interval '7 days'
  AND ut.content_id IS NOT NULL
  AND vss.status = 'filled'  -- Codex flag
  AND ut.slot_date != vss.slot_date;
```

### Где код шарашит не то

#### Validator side (`validator-contenthunter/backend/src/routers/schedule.py`)

**`update_slot:130-165`** — заполняет/чистит slot:
```python
slot.content_id = content_id
slot.status = SlotStatus.filled
slot.assigned_by_id = current_user.id
await db.commit()
# НЕТ: notify_content_approved, cancel downstream
```

**`swap_slots:168-197`** — меняет content между двумя slots:
```python
slot_a.content_id, slot_b.content_id = slot_b.content_id, slot_a.content_id
slot_a.status = SlotStatus.filled if slot_a.content_id else SlotStatus.empty
slot_b.status = SlotStatus.filled if slot_b.content_id else SlotStatus.empty
await db.commit()
# НЕТ: cancel/re-notify ни для одного из контентов
```

**`_perform_move_unpublished:200-299`** (вызывается из 2 эндпоинтов) — переносит контент source→target:
```python
target.content_id = moved_content_id
target.status = SlotStatus.filled
source.content_id = None
source.status = SlotStatus.empty
# НЕТ: cancel/re-notify
```

#### Autowarm side (`autowarm-testbench/server.js`)

**`assignUnicResultsToQueue:5547-5760`** — создаёт `publish_queue` строки. Проверяет дедуп по `(content_id, account, platform)`, но не по slot lineage. Не валидирует, что slot всё ещё содержит этот контент.

**`dispatchPublishQueue:5821+`** — берёт `pending` строки и создаёт `publish_task` без финальной проверки.

---

## 2. Goals

1. Любая мутация slot (update/swap/move) должна **отменить активные downstream артефакты** для затронутых content_id с устаревшим slot_date.
2. Если новый slot_date в будущем — pipeline должен начать заново с правильным slot_date.
3. **3-layer guard** в autowarm — даже если cancel опоздал, assign и dispatcher имеют sanity-check.
4. **Advisory lock по slot_id** в трёх местах (schedule.py, assign, dispatch) — гарантия что slot mutation и pipeline не работают одновременно.

## Non-Goals

- Не реализуем UI «hold for operator review» (отдельный backlog).
- Не отменяем published посты ретроспективно (необратимо).
- Не трогаем бизнес-логику swap_slots (правила доступа, проверки day_locked).
- `processing` / `running` / `done` publish_queue / publish_tasks — НЕ отменяем (необратимо без kill protocol). Оставляем как есть, фиксируем в логах.

---

## 3. Design

### D1. Helper в schedule.py: `cancel_downstream_for_content`
**Файл:** `validator-contenthunter/backend/src/services/pipeline_reversal.py` (новый)

```python
import logging
from datetime import date as Date
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# Codex: использовать advisory lock по slot_id чтобы schedule.py / assign / dispatch
# не работали одновременно с одним и тем же lineage
ADVISORY_LOCK_NAMESPACE = 0x73  # 's' for slot

async def acquire_slot_lock(db: AsyncSession, slot_id: int) -> None:
    """Берём pg_advisory_xact_lock — освобождается на commit/rollback.
    Same lock берётся в autowarm SQL перед assign/dispatch."""
    await db.execute(text(
        'SELECT pg_advisory_xact_lock(:ns, :id)'
    ), {'ns': ADVISORY_LOCK_NAMESPACE, 'id': slot_id})


async def cancel_downstream_for_content(
    db: AsyncSession,
    content_id: int,
    *,
    keep_slot_id: int | None = None,
    reason: str = 'slot_moved',
) -> dict:
    """Отменяет все pending publish_queue + active unic_tasks для content_id,
    КРОМЕ тех, что соответствуют keep_slot_id (lineage-based, не date-based).

    ВАЖНО: вызывать ВНУТРИ той же транзакции, что и slot mutation (Codex).
    Иначе advisory lock уже освобождён и race возможна.

    Returns: dict со счётчиками для логов/UI feedback.
    """
    # Codex: idempotent transition pending->cancelled только с WHERE status='pending'
    # Codex: lineage-based filter через ut.meta->>'slot_id', а не slot_date
    pq_result = await db.execute(text("""
        UPDATE publish_queue pq
        SET status='cancelled',
            skip_reason=:reason,
            updated_at=now()
        FROM unic_results ur
        JOIN unic_tasks ut ON ut.id = ur.task_id
        WHERE pq.unic_result_id = ur.id
          AND ut.content_id = :content_id
          AND pq.status = 'pending'
          AND (:keep_slot_id IS NULL
               OR (ut.meta->>'slot_id')::int IS DISTINCT FROM :keep_slot_id)
        RETURNING pq.id
    """), {
        'content_id': content_id,
        'reason': reason,
        'keep_slot_id': keep_slot_id,
    })
    cancelled_pq = len(pq_result.fetchall())

    # Codex Non-Goals consistency: НЕ трогаем processing — может быть в работе у unic-worker'а.
    # Только pending. Если processing завершит → unic_result создастся → assign проверит lineage
    # через D3 guard и пропустит INSERT в publish_queue. Race закрыт guard'ом, не cancel'ом здесь.
    ut_result = await db.execute(text("""
        UPDATE unic_tasks
        SET current_status='cancelled',
            updated_at=now(),
            error_message=COALESCE(error_message,'') || E'\\n[' || :reason || ']'
        WHERE content_id = :content_id
          AND current_status = 'pending'
          AND (:keep_slot_id IS NULL
               OR (meta->>'slot_id')::int IS DISTINCT FROM :keep_slot_id)
        RETURNING id
    """), {
        'content_id': content_id,
        'reason': reason,
        'keep_slot_id': keep_slot_id,
    })
    cancelled_ut = len(ut_result.fetchall())

    # Подсветить уже-running строки которые ОТМЕНИТЬ нельзя — для логирования
    running_result = await db.execute(text("""
        SELECT count(*) FROM publish_queue pq
        JOIN unic_results ur ON ur.id = pq.unic_result_id
        JOIN unic_tasks ut ON ut.id = ur.task_id
        WHERE ut.content_id = :content_id
          AND pq.status IN ('running')
          AND (:keep_date IS NULL OR ut.slot_date != :keep_date)
    """), {'content_id': content_id, 'keep_date': keep_slot_date})
    running_count = running_result.scalar() or 0

    log.info(
        "[pipeline-reversal] content=%s reason=%s: cancelled %d publish_queue + %d unic_tasks "
        "(%d running irrecoverable)",
        content_id, reason, cancelled_pq, cancelled_ut, running_count,
    )
    return {
        'content_id': content_id,
        'cancelled_publish_queue': cancelled_pq,
        'cancelled_unic_tasks': cancelled_ut,
        'irrecoverable_running': running_count,
        'reason': reason,
    }
```

### D2. Wire в schedule.py — все 3 эндпоинта

**`update_slot` — переписан с правильным transaction lifecycle (Codex CRITICAL):**
```python
from ..services.pipeline_reversal import (
    acquire_slot_lock, cancel_downstream_for_content,
)
from ..services.delivery_webhook import notify_content_approved

# === В ОДНОЙ ТРАНЗАКЦИИ: lock → load → mutate → cancel → commit ===

# 1. Load slot (берёт row-level lock через FOR UPDATE)
result = await db.execute(
    select(ValidatorScheduleSlot)
    .where(ValidatorScheduleSlot.id == slot_id)
    .with_for_update()  # row lock на slot
)
slot = result.scalar_one_or_none()
if not slot:
    raise HTTPException(status_code=404, detail="Slot not found")

# 2. Acquire advisory lock — освобождается на commit (тот же scope что cancel)
await acquire_slot_lock(db, slot_id)

# 3. Capture old_content_id ИЗ DB (Codex: не из client payload!)
old_content_id = slot.content_id

# 4. (existing access checks)
if current_user.role == UserRole.client and slot.project_id != current_user.project_id:
    raise HTTPException(status_code=403, detail="Access denied")
day_locked = is_day_locked(slot.slot_date)
content_id = data.get("content_id")
...

# 5. Mutate slot
if content_id is not None:
    if day_locked:
        raise HTTPException(...)
    if content_id == 0:
        slot.content_id = None
        slot.status = SlotStatus.empty
    else:
        slot.content_id = content_id
        slot.status = SlotStatus.filled
        slot.assigned_by_id = current_user.id

# 6. Cancel downstream BEFORE commit (Codex CRITICAL):
#    advisory lock ещё держится → assign/dispatch ждут
if old_content_id and old_content_id != slot.content_id:
    await cancel_downstream_for_content(
        db, old_content_id,
        keep_slot_id=None,  # отменить всё для старого контента
        reason=f'unbound_from_slot_{slot.id}',
    )
if slot.content_id and slot.content_id != old_content_id:
    await cancel_downstream_for_content(
        db, slot.content_id,
        keep_slot_id=slot.id,  # lineage-based: keep только текущий slot
        reason=f'rebound_to_slot_{slot.id}',
    )

# 7. Commit — освобождает advisory lock + row lock
await db.commit()
await db.refresh(slot)

# 8. AFTER commit: notify autowarm (blocking httpx) — outside transaction scope
if slot.content_id:
    await notify_content_approved(slot.content_id)

return _slot_to_dict(slot)
```

**Codex fixes applied:**
- ✅ Lock + mutation + cancel в одной транзакции
- ✅ `old_content_id` из DB, не из client payload
- ✅ Lineage-based `keep_slot_id` вместо `keep_slot_date`
- ✅ Notify ПОСЛЕ commit (но outside lock)

**`swap_slots` — переписан (Codex упрощение + ordered locks для deadlock prevention):**
```python
# === В ОДНОЙ ТРАНЗАКЦИИ ===

# 1. Acquire BOTH advisory locks в ORDER min(id), max(id) — anti-deadlock (Codex)
sorted_ids = sorted([slot_a_id, slot_b_id])
await acquire_slot_lock(db, sorted_ids[0])
await acquire_slot_lock(db, sorted_ids[1])

# 2. Load both slots с FOR UPDATE
r_a = await db.execute(
    select(ValidatorScheduleSlot).where(ValidatorScheduleSlot.id == slot_a_id)
    .with_for_update()
)
slot_a = r_a.scalar_one_or_none()
r_b = await db.execute(
    select(ValidatorScheduleSlot).where(ValidatorScheduleSlot.id == slot_b_id)
    .with_for_update()
)
slot_b = r_b.scalar_one_or_none()
if not slot_a or not slot_b:
    raise HTTPException(status_code=404, detail="Slot not found")

# 3. Capture old contents ДО swap (из DB)
old_a_content = slot_a.content_id
old_b_content = slot_b.content_id

# 4. Validate
if is_day_locked(slot_a.slot_date) or is_day_locked(slot_b.slot_date):
    raise HTTPException(status_code=409, detail="...")

# 5. Mutate
slot_a.content_id, slot_b.content_id = slot_b.content_id, slot_a.content_id
slot_a.status = SlotStatus.filled if slot_a.content_id else SlotStatus.empty
slot_b.status = SlotStatus.filled if slot_b.content_id else SlotStatus.empty

# 6. Cancel downstream BEFORE commit для обоих контентов
if old_a_content:  # был в slot_a, теперь lineage = slot_b
    await cancel_downstream_for_content(
        db, old_a_content,
        keep_slot_id=slot_b.id,
        reason=f'swapped_to_slot_{slot_b.id}',
    )
if old_b_content:  # был в slot_b, теперь lineage = slot_a
    await cancel_downstream_for_content(
        db, old_b_content,
        keep_slot_id=slot_a.id,
        reason=f'swapped_to_slot_{slot_a.id}',
    )

# 7. Commit
await db.commit()

# 8. AFTER commit: notify обоих
if old_a_content:
    await notify_content_approved(old_a_content)
if old_b_content:
    await notify_content_approved(old_b_content)

return {"ok": True, "slot_a": _slot_to_dict(slot_a), "slot_b": _slot_to_dict(slot_b)}
```

**`_perform_move_unpublished` — переписан с правильным transaction lifecycle:**
Move уже использует `with_for_update()` row locks — добавить advisory locks по обоим slot (sorted), cancel BEFORE commit, notify after.

```python
# Inside _perform_move_unpublished, после row-locks:
sorted_ids = sorted([source_slot_id, target_slot_id])
await acquire_slot_lock(db, sorted_ids[0])
await acquire_slot_lock(db, sorted_ids[1])

# (existing source/target loads + access checks + movability checks)

moved_content_id = source.content_id
target.content_id = moved_content_id
target.status = SlotStatus.filled
target.assigned_by_id = current_user.id
source.content_id = None
source.status = SlotStatus.empty

# Cancel BEFORE commit
if moved_content_id:
    await cancel_downstream_for_content(
        db, moved_content_id,
        keep_slot_id=target.id,
        reason=f'moved_from_slot_{source.id}_to_{target.id}',
    )

# Caller commits

# Caller notifies AFTER commit
```

### D3. Guard в `assignUnicResultsToQueue` (autowarm)
**Файл:** `autowarm-testbench/server.js:5582` (внутри `for (const res of results)`)

**Codex CRITICAL: pool.query без BEGIN не держит advisory_xact_lock — нужен dedicated client с явной транзакцией.**

```javascript
// Codex: использовать advisory lock + JOIN по slot_id+slot_date, не только content_id
const lockSlotId = parseInt(res.meta?.slot_id);
if (!lockSlotId) {
  console.warn(JSON.stringify({
    tag: 'assign-queue', warning: true, reason: 'meta_slot_id_missing',
    result_id: res.result_id, content_id: contentId,
  }));
  // legacy fallback: продолжаем без guard. См. D5 для миграции.
} else {
  // Codex: dedicated client + BEGIN/COMMIT для advisory lock scope
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock($1, $2)', [0x73, lockSlotId]);

    // Codex: проверять lineage (slot_id) И slot_date — слот может вернуться с другой датой
    const slotCheck = await client.query(`
      SELECT 1 FROM validator_schedule_slots
      WHERE id = $1 AND content_id = $2 AND slot_date = $3 AND status = 'filled'
      LIMIT 1
    `, [lockSlotId, contentId, res.slot_date]);

    if (slotCheck.rows.length === 0) {
      console.log(JSON.stringify({
        tag: 'assign-queue', skipped: true, reason: 'slot_no_longer_valid',
        result_id: res.result_id, content_id: contentId, slot_id: lockSlotId,
        slot_date: res.slot_date,
      }));
      await client.query('COMMIT');
      continue;
    }

    // Lineage validна → INSERT publish_queue В ТОЙ ЖЕ транзакции (lock держится)
    await client.query(`
      INSERT INTO publish_queue (...) VALUES (...)
      ON CONFLICT DO NOTHING
    `, [...]);

    await client.query('COMMIT');
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}
```

**Альтернатива** для уменьшения изменений: вынести assignUnicResultsToQueue в helper, обёрнутый в `withTransaction(async client => { ... })`.

### D4. Guard в `dispatchPublishQueue` (autowarm)
**Файл:** `autowarm-testbench/server.js:5821+` (перед созданием publish_task)

**Codex CRITICAL: dedicated client + BEGIN. Codex flag: проверять slot_date тоже, не только slot_id+content_id.**

```javascript
for (const pq of pendingRows) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');

    // Lookup lineage
    const ut = await client.query(`
      SELECT ut.meta, ut.content_id, ut.slot_date
      FROM unic_tasks ut
      JOIN unic_results ur ON ur.task_id = ut.id
      WHERE ur.id = $1
    `, [pq.unic_result_id]);

    const slotId = parseInt(ut.rows[0]?.meta?.slot_id);
    const contentId = ut.rows[0]?.content_id;
    const slotDate = ut.rows[0]?.slot_date;

    if (!slotId || !contentId) {
      // legacy fallback (см. D5)
      await client.query('COMMIT');
      // proceed with dispatch без guard
    } else {
      // Acquire same advisory lock — ждём если validator держит
      await client.query('SELECT pg_advisory_xact_lock($1, $2)', [0x73, slotId]);

      // Codex: проверять slot_id + content_id + slot_date + status (не только id)
      const valid = await client.query(`
        SELECT 1 FROM validator_schedule_slots
        WHERE id = $1 AND content_id = $2 AND slot_date = $3 AND status = 'filled'
        LIMIT 1
      `, [slotId, contentId, slotDate]);

      if (valid.rows.length === 0) {
        // Slot уже не наш — cancel в той же транзакции, continue
        await client.query(`
          UPDATE publish_queue
          SET status='cancelled',
              skip_reason='slot_no_longer_valid_at_dispatch',
              updated_at=now()
          WHERE id = $1 AND status = 'pending'
        `, [pq.id]);
        await client.query('COMMIT');
        console.log(JSON.stringify({
          tag: 'dispatch', skipped: true, reason: 'slot_no_longer_valid',
          publish_queue_id: pq.id, slot_id: slotId,
          content_id: contentId, slot_date: slotDate,
        }));
        continue;
      }

      // Atomically: claim pending → running, create publish_task в той же транзакции
      const claim = await client.query(`
        UPDATE publish_queue SET status='running', updated_at=now()
        WHERE id = $1 AND status = 'pending'
        RETURNING id
      `, [pq.id]);
      if (claim.rows.length === 0) {
        // race: кто-то уже claimed — skip
        await client.query('COMMIT');
        continue;
      }
      // ... create publish_task in this transaction ...
      await client.query('COMMIT');
    }
    // (existing publish_task spawn code outside transaction)
  } catch (e) {
    await client.query('ROLLBACK');
    throw e;
  } finally {
    client.release();
  }
}
```

### D5. Migration / data hygiene (Codex risk hole)
- Существующие `unic_tasks.meta` могут НЕ содержать `slot_id` для старых записей. Guard'ы делают graceful fallback — но это сохраняет risk RC-7 для legacy данных.
- **Pre-deploy audit обязателен:**
  ```sql
  SELECT count(*) AS legacy_active
  FROM unic_tasks
  WHERE current_status IN ('pending', 'processing')
    AND (meta IS NULL OR meta->>'slot_id' IS NULL);
  ```
- **Если legacy_active = 0** — fallback можно оставить graceful skip (никого не задевает).
- **Если legacy_active > 0** — нужен один из вариантов:
  - **Backfill migration**: `UPDATE unic_tasks SET meta = jsonb_set(coalesce(meta,'{}'::jsonb), '{slot_id}', to_jsonb(vss.id)) FROM validator_schedule_slots vss WHERE vss.content_id = unic_tasks.content_id AND vss.slot_date = unic_tasks.slot_date AND vss.status = 'filled' AND meta->>'slot_id' IS NULL;` — заполнить slot_id для legacy
  - **Hold policy**: legacy без `slot_id` → `current_status='paused'` (новый статус) с comment, оператор решает вручную. Безопаснее, но требует UI для review.
  - **Cancel policy** (агрессивно): legacy без `slot_id` → `cancelled` с reason='legacy_no_lineage'. Слоты потеряются, sweep подберёт.
- MVP: backfill migration перед deploy + graceful skip для будущих edge cases.

### D6. Lock namespace audit
**Codex flag:** проверить, что namespace `0x73` нигде не используется. Grep по обеим кодовым базам:
```bash
grep -rn "pg_advisory_xact_lock\|pg_advisory_lock" /home/claude-user/{validator,autowarm}-* | grep -v test
```
Если не пусто — выбрать другой namespace и централизовать в shared constant.

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| Race: cancel в schedule.py успевает до того как assign запустится → unic_task=cancelled, but assign читает unic_results готовые. | Advisory lock + slot_id check в assign закрывают это. Если cancel сработал и slot изменился, assign пропустит INSERT. |
| Race: assign уже создал publish_queue.pending. Slot мутирует. cancel в schedule.py обновит pending→cancelled. Dispatcher параллельно берёт ту же row. | `WHERE status='pending'` в обоих UPDATE — последний выигрывает. Если dispatcher обновил pending→running ПЕРЕД нашим cancel — наша UPDATE no-op (rowcount=0). Dispatcher продолжит. На D4 будет финальная проверка перед publish_task. |
| Race: publish_task уже создан и worker стартовал. Slot мутирует. Worker завершает publication. | Необратимо — это `running` состояние. Логируем `irrecoverable_running` count для feedback оператору ("вы пытались отменить, но публикация уже шла"). |
| Advisory lock deadlock: schedule.py взял lock(slot_5381), assign параллельно ждёт lock(slot_5381), затем нужен lock(slot_5395) — может перекреститься | Locks берём только по ОДНОМУ slot_id за транзакцию. swap_slots взял оба → потенциал deadlock. Mitigation: в swap_slots всегда брать locks в order min(slot_a.id, slot_b.id) сначала. |
| `cancel_downstream_for_content` на множество контентов в swap делает 2× SQL → задержка в API ответ | 2 простых UPDATE — десятки мс. Не блокер. |
| Старые unic_tasks без `meta.slot_id` пропускают guard | Logged warning. Не критично, поскольку для старых записей slot уже не двигают |
| **NEW (Codex):** notify_content_approved — blocking httpx внутри request path → медленный autowarm тормозит UI | Можно вынести в outbox/background задачу, но MVP — accept blocking, monitor latency. Если P95 страдает — следующая итерация. |
| **NEW:** `dispatchPublishQueue` теперь делает 2 extra SQL на каждую pending row → выше нагрузка | Lookup по unic_results+unic_tasks с JOIN индексирован. <5ms на row. На 100 pending = <500ms total. Acceptable. |
| **NEW (Codex CRITICAL):** JS pool.query без BEGIN не держит advisory_xact_lock — false security | Mitigation: dedicated client (`pool.connect()`) + явные `BEGIN/COMMIT/ROLLBACK` (D3, D4). Тест 11 (race) обязателен. |
| **NEW (Codex CRITICAL):** старые unic_tasks без `meta.slot_id` пропускают guard полностью | Mitigation: D5 backfill migration перед deploy + audit. Без миграции — частичный fix. |
| **NEW (Codex):** processing unic_tasks завершают ПОСЛЕ cancel и создают новые publish_queue | Mitigation: D3 assign-guard ловит это (slot уже не valid → пропускает INSERT). Но требует verify через test 14 (Codex). |
| **NEW (Codex):** namespace `0x73` потенциальная коллизия с другими advisory locks | D6 audit grep'ом перед deploy. Если коллизия — выбрать unused namespace, централизовать в shared constant. |
| **NEW (Codex):** swap_slots ordered locks `min(id), max(id)` если кто-то ещё берёт locks в обратном порядке → deadlock | Все locks по slot_id ВСЕГДА в order min→max. Документировать в shared constant comment. |

---

## 5. Test plan

### Unit (pytest для validator + jest/mocha для autowarm)

**Validator (`backend/tests/test_pipeline_reversal.py`):**
1. `test_cancel_downstream_for_content_pending_only` — мок DB с pending+running+done → assert только pending обновлён
2. `test_cancel_downstream_for_content_keep_slot_date` — мок с 2 active unic_tasks (разные slot_dates) → assert keep_date НЕ отменяется
3. `test_cancel_downstream_irrecoverable_running_count` — мок с running → assert returned в dict, но не обновлён
4. `test_acquire_slot_lock_uses_correct_namespace` — assert `pg_advisory_xact_lock(0x73, slot_id)`

**schedule.py integration:**
5. `test_update_slot_cancels_old_content_downstream` — fixture: content X в slot A с pending publish_queue; вызвать update_slot заменив content X на content Y; assert все pending для X отменены
6. `test_update_slot_rebind_keeps_only_new_slot_date` — fixture: content X запланирован на slot_date=05-08, имеет pending publish_queue; update_slot переносит в slot 05-15; assert pending на 05-08 отменены, новый pipeline для 05-15 запущен
7. `test_swap_slots_cancels_both_and_renotifies` — fixture: 2 контента в 2 slots; swap; assert downstream для обоих отменён, notify вызван 2 раза
8. `test_move_unpublished_cancels_old_creates_new` — full flow
9. `test_advisory_lock_serializes_concurrent_updates` — 2 concurrent update_slot на same slot → должны не deadlock'нуться

**Autowarm (`tests/test_pipeline_guards.test.js`):**
10. `test_assign_queue_skips_when_slot_no_longer_valid` — fixture unic_result + unic_task с slot_id=X; vss с slot_id=X не filled → assert no INSERT в publish_queue
11. **NEW (Codex CRITICAL):** `test_assign_queue_uses_dedicated_client_with_begin` — assert pool.connect() + BEGIN/COMMIT, не raw pool.query (lock не работает без транзакции)
12. `test_assign_queue_advisory_lock_blocks_until_validator_commits` — concurrent: validator update_slot держит lock; assign запускается → ждёт; validator commits; assign продолжает с обновленным state
13. **NEW (Codex):** `test_assign_queue_processing_unic_completes_after_cancel` — unic_task=processing на старый slot, validator cancel'нул, processing завершился → создал unic_result → assign увидел что slot не valid → пропустил INSERT
14. `test_dispatch_queue_cancels_stale_pending_at_dispatch` — fixture pending row + slot уже не filled → assert pending→cancelled, no publish_task
15. `test_dispatch_queue_skips_check_when_meta_slot_id_missing` — старая unic_task без meta → assert publish_task всё-таки создан (graceful fallback)
16. **NEW (Codex):** `test_dispatch_queue_validates_slot_date_too` — slot_id+content_id matches, но slot_date другой → assert cancelled, не dispatched

### Integration (если есть testbench):
17. End-to-end: загрузить контент → дождаться pending publish_queue → переместить slot → assert publish_queue cancelled → notify_content_approved сработал → новый unic_task создан с правильным slot_id+slot_date

### Race / concurrency (Codex flagged additions):
18. **Race assign-vs-validator:** assign внутри транзакции с lock, validator update_slot ждёт lock; assign проверил slot и committed; validator получил lock и cancel'нул — old result stale, dispatcher cancel'нет на D4
19. **Race dispatcher-vs-validator:** dispatcher claim'нул pending→running, validator move'нул slot ДО publish_task insert → publish_task не создаётся, running pq orphan'ится в БД (нужен очиститель stuck-running)
20. **Swap concurrent с assign по обоим slot:** ordered locks (min, max) предотвращают deadlock — verify через 2 параллельных swap_slots с пересекающимися slot pairs
21. **Legacy missing slot_id:** explicit policy test — assert ожидаемое поведение (graceful skip = current MVP, или paused, или cancel)

### Smoke (manual):
15. На testbench phone #19: воспроизвести RC-7 сценарий через UI, убедиться что после move pipeline переориентируется

---

## 6. Rollout

**Codex: НЕБЕЗОПАСНО до полного применения transaction-boundary fixes (D2/D3/D4) и D5 backfill.**

1. Implement в worktree (`spec-b-slot-move-reversal-20260508`)
2. Все unit-тесты зелёные (Python validator + Node autowarm)
3. **MUST PASS:** test 11 (dedicated client + BEGIN) и test 13 (processing-after-cancel)
4. Race tests 18-20 проходят
5. Integration test 17 если testbench доступен
6. D6 audit: `grep pg_advisory` чтобы убедиться что namespace 0x73 свободен
7. D5 audit: count legacy unic_tasks без `meta.slot_id` → решение по policy
8. Если legacy > 0 — backfill migration выполнить ДО deploy
9. Cherry-pick в prod main → auto-push hook деплоит

### Monitoring post-deploy
- Метрика: count `slot_no_longer_valid` events / day. Должна быть >0 (= guard работает) когда оператор делает swaps. Должна быть 0 если оператор ничего не двигает.
- Метрика: count `irrecoverable_running` per cancel call. Если высокая — оператор слишком поздно двигает; можно добавить UI warning.
- Метрика: P95 latency на `update_slot` / `swap_slots` / `move`. Не должна вырасти >100ms.

---

## 7. Open questions

- **Notify blocking vs background**: блокирующий `notify_content_approved` в request path или вынести в background queue (Celery/RQ)? MVP — blocking, потом смотрим P95.
- **Migration `meta.slot_id` для старых unic_tasks**: автоматически заполнить или оставить graceful fallback навсегда?
- **Lock scope**: namespace `0x73` достаточно изолирован? Или коллизировать с другими advisory locks в системе? (audit нужен)
