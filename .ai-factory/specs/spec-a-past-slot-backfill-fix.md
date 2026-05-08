# Spec A — Past-Slot Backfill Fix (RC-1..5 / Bug A)

**Дата:** 2026-05-08
**Инцидент:** unic-sweep подбирает slot_date=yesterday → создаёт unic_task → publish_queue с scheduled_at в прошлом → dispatcher публикует СЕГОДНЯ. Результат: дубль публикаций. Сегодня 75 строк publish_queue с slot_date=05-07.
**Codex review:** прошёл (см. `incident-brief.md` + v2)

**Зависимости:** RC-1 (notify в schedule.py update_slot/swap/move) уже покрыт **Spec B** — здесь не дублируем.

---

## 1. Background

Pipeline в `unic_tasks` имеет 3 entrypoint. Изначально trigger-immediate + morning batch покрывали happy-path, но образовались дыры:
- **RC-2:** trigger-immediate restricted to `slot.slot_date = today` — будущие slots никогда не пройдут
- **RC-3:** morning batch — single-shot ±30 мин окно UTC 01:00-01:30; vulnerable to server restart, in-memory `autoUnicLastTriggeredDate` reset
- **RC-4:** `_do_image_validation` (validation.py:244) ставит `status=approved` но не вызывает `notify_content_approved` — параллельная дыра для post/carousel
- **RC-5:** unic-sweep заглядывает на `[today, yesterday]` (`unic_sweep.js:28-33`); past-slot уезжает в publish_queue с `pubDate=res.slot_date`, scheduled_at в прошлом → dispatcher публикует сегодня

**RC-1 (update_slot/swap/move без notify):** покрыт в Spec B через advisory-lock + cancel + notify.

### Forensic timeline

| content | project | slot_date | unic_queued (sweep, sec since slot_date) | symptom |
|---|---|---|---|---|
| 1930 | 65 | 05-06 | 05-07 11:50 (~30h late) | published 05-07 |
| 1948 | 85 | 05-07 | 05-08 06:19 (~25h late) | published 05-08 |
| 1993 | 49 | 05-06 | 05-07 11:50 (~30h late) | -//- |
| 1994 | 60 | 05-06 | 05-07 11:50 (~30h late) | -//- |
| 2004 | 81 | 05-07 | 05-08 06:24 (~25h late) | -//- |

Все попали через sweep (за пределами trigger-immediate / morning batch).

---

## 2. Goals

1. **Trigger-immediate должен ловить future slots**, не только today — тогда контент, запланированный заранее, не зависит от morning batch.
2. **Image validation должна звать notify_content_approved** — закрыть RC-4.
3. **Past-slot НЕ должен публиковаться автоматически** — либо clamp на завтра, либо hold для оператора, либо drop.
4. **Sweep window сократить** до today (yesterday убрать) ПОСЛЕ того как trigger paths надёжны.

## Non-Goals

- Не исправляем reliability morning batch (RC-3) — это reliability fix, отдельный backlog. После RC-2 fix morning batch становится 2nd-line defense, а sweep — 3rd-line.
- Не реализуем UI для past-slot review (можно как backlog к Spec C).
- Не трогаем `runAutoUnicForDate` — она будет вызываться с разными slot_date'ами, логика идентичная.
- RC-1 — Spec B (validator schedule.py notify hooks).

---

## 3. Design

### D1. RC-2: расширить trigger-immediate на будущие слоты
**Файл:** `autowarm-testbench/server.js:5395-5440`

```javascript
app.post('/api/unic/trigger-immediate', async (req, res) => {
  try {
    const { content_id } = req.body;
    if (!content_id) return res.status(400).json({ error: 'content_id required' });

    const { rows: settingsRows } = await pool.query('SELECT * FROM unic_settings WHERE id=1');
    const settings = settingsRows[0] || {};
    const timezone = settings.timezone || 'Asia/Dubai';
    // Codex flag: использовать business timezone consistently
    const today = computeBusinessDate(timezone);  // импорт из unic_sweep
    // Codex: окно [today, today + N дней] — guard от случайного pre-process слотов на месяц вперёд
    const FUTURE_WINDOW_DAYS = parseInt(process.env.TRIGGER_IMMEDIATE_FUTURE_DAYS) || 14;
    const futureLimit = computeBusinessDate(timezone, Date.now() + FUTURE_WINDOW_DAYS * 86400000);

    // Find ALL slots для этого контента в окне [today, today + N]
    // Codex: status='filled' + content.status='approved' + moderation='passed' + no active unic_task
    // Codex CRITICAL: slot_date — PG DATE → возвращать как STRING (to_char), не JS Date object
    //                 (иначе off-by-one near TZ boundaries)
    const { rows: slots } = await pool.query(`
      SELECT s.id AS slot_id,
             to_char(s.slot_date, 'YYYY-MM-DD') AS slot_date_str,
             c.id AS content_id, c.s3_url, c.project_id, c.title
      FROM validator_schedule_slots s
      JOIN validator_content c ON c.id = s.content_id
      WHERE s.content_id = $1
        AND s.slot_date >= $2::date AND s.slot_date <= $3::date
        AND s.status = 'filled'
        AND c.status = 'approved'
        AND c.moderation_status = 'passed'
        AND NOT EXISTS (
          SELECT 1 FROM unic_tasks ut
          WHERE ut.content_id = c.id
            AND ut.slot_date = s.slot_date
            AND ut.current_status IN ('pending','processing','done')
        )
      ORDER BY s.slot_date ASC
    `, [content_id, today, futureLimit]);

    if (!slots.length) {
      return res.json({ triggered: false, reason: 'no eligible slots in window',
                       window: [today, futureLimit] });
    }

    // Codex: dedupe по slot_date — runAutoUnicForDate один раз на дату
    // (если контент в 2 slots на одну дату, runAutoUnicForDate сам обработает оба)
    const uniqueDates = [...new Set(slots.map(s => s.slot_date_str))];
    const triggered = [];
    for (const slotDate of uniqueDates) {
      console.log(`[trigger-immediate] 🚀 content_id=${content_id} slot_date=${slotDate} → запуск уникализации`);
      await runAutoUnicForDate(slotDate, settings);
      triggered.push({ slot_date: slotDate });
    }

    res.json({ triggered: true, count: triggered.length, slots: triggered });
  } catch(e) {
    console.error('[trigger-immediate] ❌', e.message);
    res.status(500).json({ error: e.message });
  }
});
```

**Codex applied:**
- ✅ snять `s.slot_date = today` restriction
- ✅ guard окно `[today, today + N]`
- ✅ запускать `runAutoUnicForDate(slot.slot_date)` для КАЖДОГО найденного, не today
- ✅ business timezone consistency

### D2. RC-4: notify в image validation
**Файл:** `validator-contenthunter/backend/src/routers/validation.py:244` (в `_do_image_validation`)

```python
# (после: content.status = ContentStatus.approved)
content.status = ContentStatus.approved

await db.commit()
await db.refresh(content)
log.info("image validation done: content_id=%s status=%s", content.id, content.status.value)

# Параллельно с _do_video_validation:132 — notify autowarm если approved
if content.status == ContentStatus.approved:
    from ..services.delivery_webhook import notify_content_approved
    await notify_content_approved(content.id)

return {...}
```

Симметрия с video flow восстановлена.

### D3. RC-5: clamp pubDate в assignUnicResultsToQueue + DURABLE AUDIT (Codex)
**Файл:** `autowarm-testbench/server.js:5644-5666` + новая SQL в `assignUnicResultsToQueue` query

**Codex CRITICAL: PG DATE через JS Date может дать off-by-one. SQL должен возвращать slot_date как STRING.**

Изменить SELECT в `assignUnicResultsToQueue` (server.js:5550):
```sql
-- было:
ut.slot_date,
-- станет:
to_char(ut.slot_date, 'YYYY-MM-DD') AS slot_date,
```

Затем в обработке:
```javascript
const todayBusiness = computeBusinessDate(timezone);  // импорт из unic_sweep
let pubDate;
if (res.slot_date) {
  // Codex: res.slot_date теперь string из to_char, не JS Date — off-by-one fix
  const slotDateStr = res.slot_date;  // 'YYYY-MM-DD'
  if (slotDateStr < todayBusiness) {
    // Codex CRITICAL: durable audit event — не silent log, оператор видит
    // INSERT в new event-table OR в существующую (publish_queue с особым статусом)
    await pool.query(`
      INSERT INTO publish_queue (
        unic_result_id, unic_task_id, project_id, pack_id, pack_name,
        account_username, platform, device_serial, raspberry_number,
        media_url, status, skip_reason, scheduled_at, created_at, updated_at
      )
      SELECT $1, $2, $3, NULL, NULL, NULL, NULL, NULL, NULL,
             $4, 'past_slot_dropped', 'sweep_picked_past_slot_dropped_by_clamp', $5, now(), now()
      WHERE NOT EXISTS (
        SELECT 1 FROM publish_queue
        WHERE unic_result_id = $1 AND status = 'past_slot_dropped'
      )
    `, [res.result_id, res.task_id, res.project_id, res.output_url, slotDateStr]);
    console.log(JSON.stringify({
      tag: 'assign-queue', skipped: true, reason: 'past_slot_dropped',
      result_id: res.result_id, content_id: contentId,
      slot_date: slotDateStr, today_business: todayBusiness,
    }));
    continue;  // НЕ INSERT'ить нормальные публикационные строки
  }
  pubDate = slotDateStr;
} else {
  pubDate = computeBusinessDate(timezone, Date.now() + 86400000);  // tomorrow
}
```

**Codex applied:**
- ✅ Durable audit через `publish_queue.status='past_slot_dropped'` — оператор видит через published_mark / dashboard, не через PM2 логи
- ✅ Idempotent (NOT EXISTS guard)

**Альтернативы (open question, по убыванию строгости):**
- A. **Drop with durable audit** (MVP, текущий design) — past-slot не публикуется, но запись в publish_queue с особым статусом видна в UI
- B. **Clamp на завтра** — past-slot публикуется завтра. Контент сдвигается без согласия
- C. **Hold с manual_dispatch_required** — operator UI approve

MVP — **A**. Если operator жалуется что хочет clamp/hold — переключаемся.

### D4. RC-5 (alt path): убрать yesterday из sweep window
**Файл:** `autowarm-testbench/unic_sweep.js:28-33`

```javascript
function computeBusinessDateWindow(timezone, baseTime) {
  // Codex flag: убрать yesterday только ПОСЛЕ применения D1 (RC-2 fix)
  // Иначе miss'нем legitimate slots контента, который approved late ночью UTC.
  const t = (baseTime !== undefined && baseTime !== null) ? baseTime : Date.now();
  return [computeBusinessDate(timezone, t)];  // только today
}
```

**Codex caveat:** убирать yesterday безопасно ТОЛЬКО после деплоя D1+D2 + Spec B. Иначе late-night approval (особенно cross-TZ) выпадает в дыру.

**Phasing:**
- Phase 1: D1+D2+D3 (RC-2+RC-4+RC-5 clamp). Sweep window остаётся [today, yesterday].
- Phase 2: Verify 1-2 недели в проде что нет miss'ed slots (метрика: sweep insertion count для yesterday → 0). Тогда применить D4.
- Phase 3: alternative — sweep оставляем как safety net forever, но с clamp в D3 он становится безопасным даже с yesterday.

### D5. computeBusinessDate import в server.js
**Файл:** `autowarm-testbench/server.js`

`computeBusinessDate` сейчас экспортируется только из `unic_sweep.js`. Нужно либо:
- A. Импортировать из unic_sweep: `const { computeBusinessDate } = require('./unic_sweep');` ← простой
- B. Вынести в отдельный модуль `lib/business_date.js`

MVP: A.

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| D1 расширение trigger-immediate на будущие slots → создаются unic_tasks за N дней вперёд | Guard `+14 дней` ограничивает. Если оператор планирует на месяц вперёд — task'и в работе будут стрельнуть позже. Это OK: процесс `runAutoUnicForDate` идёмпотентен (UNIQUE index)|
| D1 трафик на trigger-immediate webhook вырастет — каждое approval запустит N unic_tasks (если контент в N будущих slots) | В реальности контент обычно в 1 slot. Trigger срабатывает на approval, оператор обычно ставит в slot потом. Spec B notify hooks тоже trigger'ят. Не ожидается значимого ↑ |
| D2 image validation может дребезжать если notify сломается | `notify_content_approved` уже catches exceptions (delivery_webhook.py:36) — не блокирует validation. Не блокер |
| D3 drop past-slot — оператор не узнает что слот пропустил | Codex: НЕ silent log, а durable audit row в publish_queue с status='past_slot_dropped'. UI видит через published_mark / dashboard. Метрика count past_slot_dropped — early warning. |
| D4 убрать yesterday — late-night approval (между business midnight и UTC midnight) выпадет | НЕ применять D4 до Phase 2 verification. Sweep [today, yesterday] остаётся как safety net. Codex: 2-4 недели observation safer than 1-2 |
| Cross-TZ edge case: validator пишет slot_date как UTC date, business TZ — Asia/Dubai — 4-часовой mismatch | computeBusinessDate uniform во всех 3 entrypoints. **Codex CRITICAL:** PG DATE через JS Date object даёт off-by-one near TZ boundaries → SQL должен возвращать `to_char(slot_date, 'YYYY-MM-DD')` (D1, D3 fixed). Тесты #14, #18 покрывают |
| **NEW (Codex):** D1 `(content_id, slot_date)` granularity — если content в 2 slots на одну дату, второй slot не создаст отдельный task | Текущий бизнес-инвариант: 1 content per slot per date — UNIQUE `uq_slot (project_id, slot_date, slot_position)` это позволяет (разные positions могут иметь разный content). НО: один content в 2 positions того же дня — теоретически возможно. Если бизнес-правило это запрещает — добавить check. Если разрешает — нужен `slot_id` granularity (Spec B уже использует `meta.slot_id`). MVP: documenting. Test 5 покрывает обнаружение |
| **NEW (Codex):** D1 `runAutoUnicForDate` вызывается N раз для одной даты | Mitigation: dedupe `[...new Set(slots.map(s => s.slot_date_str))]` (D1 fixed) |
| **NEW (Codex):** PG DATE → JS Date off-by-one | Mitigation: `to_char(..., 'YYYY-MM-DD')` всегда (D1, D3 fixed). Test 12 (cross-TZ) обязателен |
| **NEW (Codex):** Re-enable sweep после Phase 1 без verification | Mitigation: после deploy 24ч monitor `past_slot_dropped` count, если spike → investigate (могут быть legitimate slots выпадают, не Bug A) |

---

## 5. Test plan

### Unit (новые тесты)

**autowarm `tests/test_trigger_immediate.test.js`:**
1. `test_trigger_immediate_finds_today_slot` — content в slot today → trigger creates unic_task
2. `test_trigger_immediate_finds_future_slot_within_window` — content в slot today+7 → trigger creates unic_task с slot_date=today+7
3. `test_trigger_immediate_skips_outside_window` — content в slot today+30 → skipped (FUTURE_WINDOW_DAYS=14)
4. `test_trigger_immediate_skips_past_slot` — content в slot yesterday (manually) → skipped (slot_date < today)
5. `test_trigger_immediate_processes_all_eligible_slots` — content в 2 future slots → создаёт 2 unic_task (по одному на каждый slot_date)

**validator `backend/tests/test_image_notify.py`:**
6. `test_image_validation_notifies_on_approved` — image content приходит на validate → status=approved → notify_content_approved вызвана
7. `test_image_validation_no_notify_on_rejected` — image rejected → notify не вызывается
8. `test_image_notify_failure_does_not_block_validation` — notify_content_approved бросает → validation продолжается

**autowarm `tests/test_assign_queue_clamp.test.js`:**
9. `test_assign_queue_drops_past_slot_with_audit_row` — unic_result со slot_date=yesterday → publish_queue row с status='past_slot_dropped' создан, нормальная INSERT не выполнена
10. `test_assign_queue_processes_today_slot_normally` — slot_date=today → publish_queue created
11. `test_assign_queue_processes_future_slot_normally` — slot_date=tomorrow → publish_queue created с scheduled_at=tomorrow
12. **NEW (Codex):** `test_assign_queue_uses_string_slot_date_not_js_date` — мок DB вернёт slot_date как string из to_char → assert no off-by-one, не используется `new Date()`
13. `test_assign_queue_uses_business_timezone_for_today` — settings.timezone=Asia/Dubai, UTC=23:30 → today для assign = next business day
14. **NEW (Codex):** `test_assign_queue_audit_idempotent` — второй assign того же result не дублирует past_slot_dropped row

**autowarm `tests/test_sweep_window.test.js` (Phase 2):**
15. `test_sweep_window_today_only_after_phase_2` — после применения D4: window = [today]
16. `test_sweep_late_night_cross_tz_handled_by_d1_d2` — content approved at UTC 23:50 на slot=tomorrow_business → trigger-immediate подбирает (D1), не sweep

**Codex extra:**
17. **NEW:** `test_d1_dedupes_runautounic_by_date` — content в 2 slots на одну дату → runAutoUnicForDate вызвана 1 раз, не 2
18. **NEW:** `test_cross_tz_boundaries` — UTC 20:30, 23:30, 00:30 при Asia/Dubai → корректный business date
19. **NEW:** `test_d1_handles_dst_timezone` — Europe/Berlin как business TZ → корректный today/futureLimit (DST transitions)
20. **NEW:** `test_two_simultaneous_trigger_immediate_no_duplicate` — 2 параллельных trigger webhooks для same content/date → UNIQUE index не даёт duplicate active task

### Integration:
15. End-to-end: загрузить контент → assign в slot today+5 → trigger fires → unic_task created → unic processes → assign-queue creates publish_queue с scheduled_at=today+5+publishStart
16. End-to-end: simulate sweep insert past-slot (через manual SQL) → assign-queue dropps без INSERT
17. End-to-end: image content → validate → notify → trigger → unic_task

---

## 6. Rollout

**Phasing (Codex flag):**

### Phase 1 (immediate after Spec B deploy)
1. Implement D1 + D2 + D3 в worktree (`spec-a-past-slot-fix-20260508`)
2. Все unit-тесты зелёные
3. Cherry-pick в prod main → auto-push deploy
4. Sweep остаётся [today, yesterday] как safety net
5. Monitor: count `past_slot_holds` events / day. Должно быть >0 первые дни (от sweep yesterday + late approvals), потом постепенно к 0 как trigger-immediate ловит больше.

### Phase 2 (Codex: 2-4 недели после Phase 1, не 1-2)
6. Проверить метрику: sweep yesterday insertion count = ~0 (т.е. trigger-immediate всё ловит)
7. Применить D4 (sweep window = today only)
8. Monitor: ничего не должно сломаться, late-night cross-TZ approvals идут через trigger-immediate

### Phase 3 (опциональный backlog)
- UI feedback оператору: «пропущенные слоты» (через published_mark / dashboard delta)
- RC-3 morning batch reliability fix (отдельный design)

### Re-enable sweep on prod
После Phase 1 deploy — `sudo pm2 unset autowarm:UNIC_SWEEP_DISABLED && sudo pm2 restart autowarm`. Past-slot drop в D3 защищает от дублей даже если sweep подберёт что-то старое.

---

## 7. Open questions

- D3 policy MVP: drop silently vs clamp_tomorrow vs hold? Spec предлагает drop silently. Операторская перспектива возможно потребует hold через UI — backlog. Если оператор будет жаловаться «пропали публикации» — переключиться на clamp_tomorrow.
- FUTURE_WINDOW_DAYS = 14 разумно? Контент за месяц вперёд должен ждать morning batch / sweep на свой день. Если оператор планирует far ahead — нужен ли больший window?
- Phase 1→2 timing: 1-2 недели достаточно для verification? Или сразу применить D4 раз уж там тесты + clamp защищает?
- Sweep остаётся в проде как safety net? После D3 clamp — да, безопасно. После D4 (Phase 2) — sweep становится тонким (только today, узкое окно miss).
