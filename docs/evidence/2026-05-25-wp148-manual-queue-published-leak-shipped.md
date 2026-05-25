# WP #148 — Опубликованная автовыкладка ушла в ручную — SHIPPED+DEPLOYED 2026-05-25

**Задача:** OpenProject #148 «Опубликованная автовыкладка ушла в ручную» (клиент Art Estate, тел. 63/64/65/103/104/108).
**Артефакты:** spec `docs/superpowers/specs/2026-05-25-wp148-manual-queue-published-leak-design.md`, plan `docs/superpowers/plans/2026-05-25-wp148-manual-queue-published-leak.md`.

## Что было не так
Контент, уже успешно опубликованный автовыкладкой (`publish_queue.status='done'`), ошибочно сваливался в ручную очередь (`validator_manual_publish_queue`). Корень — несоответствие гранулярности: падение публикации происходит на уровне аккаунт×платформа (строка `publish_queue`), а перевод в ручную — на уровне слота (весь пак клиента).

По проду 25.05 (контент 2317, слот 11029): один YouTube-аккаунт (EliteCornersSpb) упал со структурной ошибкой `ui_changed` (`yt_editor_upload_timeout`) → `retry_controller.handoffToManual` пометил **весь слот** `manual_publish=true` → dispatch-guard отменил 5 ещё не отправленных → `manual_queue_assign` залил в ручную очередь **все 27** комбинаций пака, включая 21 уже успешно опубликованную. Масштаб по системе: 311 из 722 живых строк ручной очереди (43%) дублировали уже-`done` (174 queued + 137 published), затронуты и авто-клиенты (через handoff), и ручные клиенты Ambassadori/Feminista (через populator, когда часть пака вышла автоматом до перевода в ручной режим).

## Что сделано
Две протечки закрыты (репозиторий autowarm `GenGo2/delivery-contenthunter`):
- **`retry_controller.handoffToManual` стал per-account**: gather-запрос по одной упавшей строке `publish_queue` + общий хелпер `enqueueManualRow`; слот целиком **не** помечается ручным — остальные аккаунты пака продолжают авто-выкладку. No-silent-drop: если не удалось собрать `slot_id/content_id` — строка НЕ гасится (ROLLBACK), остаётся `failed`. Kill-switch `RETRY_HANDOFF_PER_ACCOUNT=false` → легаси флип слота.
- **`manual_queue_assign` (populator) исключает уже опубликованное**: `isAlreadyPublished` пропускает аккаунт×платформа с `publish_queue.status='done'`. Kill-switch `MANUAL_QUEUE_EXCLUDE_PUBLISHED=false`. Закрывает протечку и по ручным клиентам.
- **Общий идемпотентный хелпер `enqueueManualRow`** (единственная точка INSERT в `validator_manual_publish_queue`, ON CONFLICT по `uq_manual_pub_result_account`).
- **Ретро-зачистка** `cleanup_wp148_manual_queue_dups.js` (dry-run default + `onlyResultId` тест-изоляция): отменены `queued`-дубли, `published` оставлены как исторические.

## Реализация и проверка
- Прод main `5009575` (содержит слияние с параллельной WP #138 — события retry/handoff в логе; слито вручную, событие-логирование сохранено внутри `if (didHandoff)`).
- Тесты `node --test`: **45/45** зелёные (per-account handoff, idempotency, оба kill-switch, no-silent-drop, populator skip + kill-switch, cleanup isolation/idempotency/dry-run, + сохранённые тесты WP #138).
- Per-task ревью: 2 spec-review + 2 code-quality review субагентами на каждую из 4 задач + 2 раунда codex (реальный P2 «silent-drop» починен; P2 о недостижимой mock-ветке — подтверждённый false-positive, отклонён) + финальное holistic-ревью (opus, Ready to merge).
- Gather-запрос валидирован на реальной упавшей строке прода (pq.id=5117): все enrichment-поля резолвятся (phone_number=40, account_id=1099, slot_id=11029, content_id=2317).
- Деплой: прод-checkout `/root/.openclaw/workspace-genri/autowarm` (`git pull`), **ROOT PM2 id=35 `autowarm`** рестарт (`sudo pm2 restart autowarm`) — online, exec cwd корректный, краны работают.
- Ретро-зачистка применена: отменено **195** `queued`-дублей (174 + 21 после деплоя), `published` (137) не тронуты, live queued-дублей = **0**. После полного тика populator'а дубли не вернулись.
- Прямой вызов задеплоенного `isAlreadyPublished` на проде: `done`→true, bogus→false.

## Что осталось (backlog)
- Live-верификация пару дней, что лишние позиции в ручной выкладке не появляются (OpenProject #148 → Тестирование). Очередь Art Estate уже чистая.
- Минорные (не блокеры, см. BACKLOG): sync-lag окно false-negative populator'а (≤30 мин до `syncQueueStatuses`); handoff берёт device-поля из снапшота `publish_queue` (не ре-резолв); индекс `uq_manual_pub_result_account` не покрыт миграцией (пре-existing).
