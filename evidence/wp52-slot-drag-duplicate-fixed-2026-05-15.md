# WP #52 — Slot duplicate on drag-from-past-day → FIXED 2026-05-15

## Симптом
Drag слота из прошедшего дня в будущий иногда оставлял один и тот же контент в обоих днях. Аня воспроизводила несколько раз, описание в OpenProject: «обычно я из прошедших дней перетягивала, думала что из-за этого так».

Скрин из WP: «Твое тело скажет "Спас..."» на ср/13 и чт/14 одновременно, оба «На проверке».

## Root cause

`frontend/src/pages/client/ClientDashboard.vue:onDrop` делал **2 несатомарных PATCH'а** (старый код):

```ts
await apiClient.patch(`/schedule/slots/${targetSlot.id}`, { content_id: src.content_id })  // 1. target = X
await apiClient.patch(`/schedule/slots/${src.id}`, { content_id: 0 })                       // 2. source = 0
await loadSlots()
```

Бэкенд `update_slot` (`backend/src/routers/schedule.py:181-187`) отвергает мутации в day_locked-слоте:

```python
if content_id is not None:
    if day_locked:
        raise HTTPException(status_code=409, detail="День заблокирован для изменений (после 15:00 GMT+4)")
```

`is_day_locked` (`backend/src/services/schedule_service.py:25-45`) → True для прошлых дат и сегодня после 15:00 GMT+4.

**Сценарий бага:**
1. Drag из прошедшего дня (source.slot_date < today) в будущий (target.slot_date > today).
2. PATCH#1 (target) — OK, бэк ставит `target.content_id = X`, `status = filled`.
3. PATCH#2 (source) — **409**, source — day_locked.
4. Frontend ловит в `catch (e) { console.error(...) }`. `loadSlots()` не вызывается.
5. В БД остаются оба слота с `content_id = X`. UI на странице показывает stale-состояние до следующего ручного reload.
6. На reload пользователь видит дубликат.

«Random» — потому что зависит от lock-status источника, который меняется день ото дня и от 15:00 GMT+4 пограничного времени.

## Что сделано

Один атомарный POST `/schedule/move-unpublished` вместо двух PATCH'ей. Эндпоинт уже существовал и использовался флоу TransferTray (`tray.placeTo` → `placeFromTray`):

```ts
await apiClient.post('/schedule/move-unpublished', {
  source_slot_id: src.id,
  target_slot_id: targetSlot.id,
})
```

`_perform_move_unpublished` (`schedule.py:340-478`):
- транзакционный (advisory + row-locks на оба слота)
- **явно разрешает source в day_locked-дне** — там нет `is_day_locked(source.slot_date)` guard, только проверка `is_slot_movable_unpublished` (не опубликовано) и target-day-locked
- покрыт backend тестами: `test_schedule_pipeline_reversal.py` T7/T8/T9/T10 + `test_schedule_lock.py:test_move_unpublished_*`

Вторичный фикс UX:
- `loadSlots()` теперь в `finally` — UI рефрешится и при отказе (раньше при ошибке UI оставался в stale-состоянии)
- `alert(detail)` при ошибке — консистентно с `placeFromTray`

## Diff

```diff
   // Вариант 2: локальный DnD между слотами на этой же странице.
+  // Атомарный endpoint: source может быть в day_locked-дне (PATCH на source
+  // упал бы 409 и оставил контент в обоих слотах — см. WP #52).
   if (!dragSlot.value || dragSlot.value.id === targetSlot.id) return
   const src = dragSlot.value
   dragSlot.value = null

   try {
-    // Перемещаем контент в целевой слот
-    await apiClient.patch(`/schedule/slots/${targetSlot.id}`, { content_id: src.content_id })
-    // Освобождаем исходный слот
-    await apiClient.patch(`/schedule/slots/${src.id}`, { content_id: 0 })
+    await apiClient.post('/schedule/move-unpublished', {
+      source_slot_id: src.id,
+      target_slot_id: targetSlot.id,
+    })
+  } catch (err: any) {
+    console.error('[dashboard] DnD move failed', err)
+    const msg = err?.response?.data?.detail || 'Не удалось перенести контент'
+    alert(msg)
+  } finally {
     await loadSlots()
-  } catch (e) {
-    console.error('DnD move failed:', e)
   }
 }
```

## Deploy

- PR: https://github.com/GenGo2/validator-contenthunter/pull/11
- Merged into `main` as squash commit `98f1114` (2026-05-15 16:39 UTC)
- `npm run build` → postbuild автоматом скопировал `dist/*` в `/var/www/validator/`
- Новый bundle: `assets/ClientDashboard-DnoDkm23.js` (72KB)
- Live verify: `curl https://client.contenthunter.ru/assets/ClientDashboard-DnoDkm23.js` → 200

## Что осталось (verify в проде)

- Аня — после **hard reload** (Vite hashed assets — без него старый код в памяти) — drag из прошедшего дня в будущий → source освобождается, target заполняется, дубликата нет.
- При неудаче (например, content уже publishing) — alert с текстом из бэка.
- После Аниного подтверждения — закрыть WP #52 → «Готово».

## Уроки

1. **Любой slot DnD-флоу должен использовать `/schedule/move-unpublished`** (или `/schedule/swap` для занятых↔занятых). 2-PATCH "сначала target, потом source" — НЕ атомарно и валится на day-locked источнике.
2. **При ошибке всегда `loadSlots()` в `finally`** — иначе UI зависает в stale-состоянии и пользователь видит "rollback" на следующем reload как баг.
3. **«Random» баги, привязанные к датам** — кандидат на проверку `is_day_locked` / cutoff logic. Пользователь часто ловит корреляцию («обычно из прошедших») быстрее, чем код её показывает.
