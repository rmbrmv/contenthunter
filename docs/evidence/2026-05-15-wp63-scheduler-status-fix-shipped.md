# WP 63 — рассинхрон статусов в планировщике — shipped 2026-05-15

**OpenProject:** WP 63 «Поправить корректность отображения статусов в планировщике» → status `Тестирование` (awaiting visual confirmation by Анастасия)
**PR:** https://github.com/GenGo2/validator-contenthunter/pull/12 — merged `520aaec`
**Branch:** `fix/wp63-scheduler-status-20260515` (deleted post-merge)
**Prod:** validator `main` пересобран и `npm run build` postbuild автоматически разложил dist в `/var/www/validator/` (новый чанк `ClientDashboard-fc0eGys6.js`)
**Author:** Claude Opus 4.7 (1M context) + Danil Pavlov

## Backstory

Анастасия в WP 63 (скриншоты): в планировщике слот «2 свитшота в одном — п...» на пятницу горит «✅ Одобрено», но если открыть карточку контента — там жёлтое «⏳ Требует одобрения», и без снятия этого статуса контент **не идёт** на автовыкладку. Пользователь видит, что всё одобрено и недоумевает, почему ролик не публикуется.

Direct bug research (`systematic-debugging` Phase 1+2) → fix согласован с пользователем → TDD-имплементация.

## Корень

Карточка слота в `frontend/src/pages/client/ClientDashboard.vue:188-195` смотрела **только на `moderation_status`**. Логика была:

```ts
function moderationLabel(status: string) {
  if (status === 'passed') return '✅ Одобрено'
  if (status === 'blocked' || status === 'rejected') return '❌ Отклонено'
  return '⏳ На проверке'
}
```

Но `moderation_status` — это статус автоматической LLM-модерации (`pending/passed/flagged/blocked`), а финальный статус контента — `ValidatorContent.status` (`ContentStatus` enum: `uploaded/validating/approved/needs_review/rejected/scheduled/in_uniqualization/published/archived`).

В `backend/src/routers/validation.py:121-126` логика финального статуса:
```python
if mod["status"] == "blocked":
    content.status = ContentStatus.rejected
elif mod["status"] == "flagged" or uniq["is_duplicate"]:
    content.status = ContentStatus.needs_review
else:
    content.status = ContentStatus.approved
```

И вебхук автовыкладки уходит ТОЛЬКО при `approved` (`validation.py:132`):
```python
if content.status == ContentStatus.approved:
    from ..services.delivery_webhook import notify_content_approved
    await notify_content_approved(content.id)
```

Сценарий рассинхрона: модерация прошла (`passed`) + контент задетектен как дубль → `content.status = needs_review`. Планировщик видит `moderation_status=passed` и рисует «✅ Одобрено». Карточка контента видит `content.status=needs_review` и рисует «⏳ Требует одобрения». Вебхук не уходит. Пользователь думает, что всё ок.

API уже отдавал оба поля — `backend/src/services/schedule_service.py:233,246` возвращает и `moderation_status`, и `content_status`. Дело было только в UI.

Manager-side `frontend/src/components/calendar/SlotCard.vue:125-147` смотрел напрямую на `content.status` — не страдал багом. То есть из памяти `feedback_validator_two_slot_renderers` — два места рендеринга, но баг был только в клиентском.

## Fix

Вынес классификатор в чистый модуль `frontend/src/utils/slotStatus.ts`:

- `slotStatusInfo(slot)` — возвращает `{ label, tone }` по приоритету:
  1. `is_published` → "📣 опубликовано" (фиолет)
  2. `is_publishing` → "⏳ публикуется" (жёлтый)
  3. `moderation_status ∈ {blocked, rejected}` или `content_status='rejected'` → "❌ Отклонено" (красный)
  4. `content_status ∈ {approved, scheduled, in_uniqualization, published}` → "✅ Одобрено" (зелёный)
  5. `content_status='needs_review'` → "⏳ Требует одобрения" (жёлтый) — **ЭТО НОВОЕ**
  6. `moderation_status='passed'` без финала → "✅ Модерация пройдена" (бледно-зелёный)
  7. остальное → "⏳ На проверке" (серый)
- `slotStatusPillClass(tone)` / `slotStatusBorderClass(tone)` — Tailwind-классы. Рамка карточки теперь согласована с пилюлей (раньше всегда `border-green-400` у filled-слота, что усиливало впечатление «всё готово»).

`ClientDashboard.vue` теперь импортирует и использует эти хелперы. Старая `moderationLabel` удалена.

Файлы:
- `frontend/src/utils/slotStatus.ts` (+95)
- `frontend/src/utils/slotStatus.test.ts` (+159)
- `frontend/src/pages/client/ClientDashboard.vue` (+5/-26)

## TDD

23 unit-теста через `node --test --experimental-strip-types` (без vitest — node 22 native). Покрытие:
- Приоритеты `is_published` / `is_publishing` над всем
- Все ветки `moderation_status × content_status`
- Все `tone`-классы пилюли и рамки

```
$ node --experimental-strip-types --test src/utils/slotStatus.test.ts
# tests 23
# pass 23
# fail 0
```

`vue-tsc --noEmit` exit 0. `codex review` без P1.

## Scope

Только клиентский планировщик. Manager-side `SlotCard.vue` уже использует `content.status` — не трогаю чтобы не вносить риск регрессии вне scope WP #63. Унификация SlotCard.vue на общий `slotStatusInfo` — кандидат на follow-up backlog.

## Что осталось

- [ ] Визуальная проверка Анастасией на превью — пилюля «⏳ Требует одобрения» в планировщике для контента с `needs_review`
- [ ] (follow-up) Унификация manager-side `SlotCard.vue` на общий классификатор — низкий приоритет, бага сейчас нет

## Validation после деплоя

Прод-фронт обновлён (новый чанк `ClientDashboard-fc0eGys6.js` разложен в `/var/www/validator/`). Юзерам с открытым планировщиком нужен hard reload (Ctrl+Shift+R) чтобы подцепить новый chunk — из памяти `feedback_vite_outage_user_hard_reload`.

Карточка слота для `content_status=needs_review` (дубль или flagged) теперь рендерится с жёлтой пилюлей «⏳ Требует одобрения» вместо ложного зелёного «✅ Одобрено». Зелёный остаётся только для финально одобренного контента.
