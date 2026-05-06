# Session 2026-05-06 — published-mark UX follow-ups

Доработки к фиче `📣 Опубликовано` (shipped 2026-05-04, см. `evidence/session-2026-05-04-publisher-stack-hardening.md` и `project_published_mark_source_content.md` в memory).

## Проблемы (от пользователя)

1. На `/dashboard` опубликованные слоты остаются draggable: бэк-guard `is_slot_movable_unpublished` отклоняет PATCH'и, но фронт даёт пользователю начать перенос → fake-promise UX.
2. На `/content/<id>` одновременно показываются два статуса:
   - top-right badge `⏳ В обработке` (fallback `contentStatusLabel` для content.status='pending')
   - блок `📣 Опубликовано` (PublishedBlock, рендерится при is_published=true)

   Должен быть только один.

## Корневые причины

1. `ClientDashboard.vue:122-169` (inline filled-slot) использует raw `draggable="true"` — не зависит от `slot.is_published`. Memory `feedback_validator_two_slot_renderers` явно предупреждает: SlotCard.vue (manager) и inline ClientDashboard.vue — два разных рендерера, при изменении логики патчить оба. SlotCard.vue в shipping-релизе уже использовал `slot.movable_unpublished` (бэк-флаг) → manager view был корректен. Inline на client /dashboard — нет.
2. `ContentDetail.vue:27-37` — top-status badge рендерится безусловно, fallback `bg-gray-100 text-gray-500 + ⏳ В обработке` срабатывает для content.status='pending' (опубликованный контент остаётся pending по оси модерации, см. spec §4.3 «is_published — ортогональная ось, не переписывает enum»).

## Изменения

### `frontend/src/pages/client/ClientDashboard.vue` (commit `1717e86`)

- `:draggable="!slot.is_published"` (was `draggable="true"`)
- guard `event.preventDefault()` в `onDragStart` если `slot.is_published`
- cursor `pointer` вместо `grab` + рамка `border-purple-300` для published (визуальная подсказка)

📥 pickToTray button уже был скрыт (line 141: `v-if="... && !slot.is_published"`) — drag-n-drop был оставшимся вектором.

### `frontend/src/pages/client/ContentDetail.vue` (commit `bfc8169`)

- top-status block получил `v-if="!content.is_published"`. На опубликованном контенте остаётся только `📣 Опубликовано` через `PublishedBlock` (line 40).

## Verification

- `npx vue-tsc --noEmit` — exit 0.
- `npm run build` → vite build OK + postbuild auto-deploy в `/var/www/validator/`.
- Manual UI smoke (пользователь на client.contenthunter.ru) — оба сценария отрабатывают.

## Push

`bfc8169..1717e86 main -> main` в `GenGo2/validator-contenthunter`.

## Не покрыто

- Manager view (`SlotCard.vue` через `WeeklyGrid`) — уже корректен с момента published-mark shipping (canDrag → isMovableUnpublished → slot.movable_unpublished флаг с бэка). Не трогали.
- E2E-тестов на фронте нет в этом репо (нет vitest/playwright). Smoke остаётся ручной.
