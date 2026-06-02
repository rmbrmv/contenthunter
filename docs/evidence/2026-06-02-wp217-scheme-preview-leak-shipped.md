# WP#217 — Барьер scheme_preview в автовыкладке: SHIPPED+DEPLOYED 2026-06-02

- **OpenProject:** WP#217 (Ошибка, Ирбис+Мурат Димитров) → **Тестирование**.
- **Код:** GenGo2/delivery-contenthunter PR **#147** → merge `466d056` в main.
- **Docs:** rmbrmv/contenthunter ветка `wp217-scheme-preview-leak` (спека+план+это evidence).

## Корень
Видео грузили только в уникализатор для **отбора схем** — валидатор создаёт `unic_tasks.task_type='scheme_preview'` (`scheme_preview_queue.py`; вход `/scheme-previews/`, без `content_id`/`slot_date`/слота, с обязательным `payload_hash`). Воркер пишет превью в общую `unic_results`, а авто-крон выкладки `unic_results → publish_queue` (`assign_candidates.js::selectAssignCandidates`) **не фильтровал `task_type`** → превью-прогоны уезжали в автовыкладку (D3-гард родословной слота пропускался: у превью нет `slot_id` → legacy-ветка). Подтверждено по проду: **105 строк** в publish_queue из scheme_preview-задач, проекты 103 (Ирбис) и 117 (Мурат Димитров).

## Фикс (3 слоя)
- **A. Allowlist** `ut.task_type='unic'` в `selectAssignCandidates` (kill-switch `ASSIGN_PUBLISHABLE_TASK_TYPE_GUARD_ENABLED`, default ON, fail-closed).
- **B. Зеркало на диспатче** `server.js::checkDispatchQueueSlotLineage` — добавлен `ut.task_type` в lineage-SELECT + отмена не-`unic` строк (`skip_reason='non_publishable_task_type'`) ДО legacy-ветки (kill-switch `DISPATCH_TASK_TYPE_RECHECK_ENABLED`, default ON). Ловит строки, попавшие в очередь до раскатки A.
- **C. Cleanup-скрипт** `cleanup_wp217_scheme_preview_leak.js` (dry-run/`--apply`, идемпотентно) — отменяет уже утёкшие pending-строки.

Ручная очередь оператора (`manual_queue_assign.js`) уже безопасна по построению (INNER JOIN по `slot_id`) — добавлен защитный регресс-тест `test_manual_queue_preview_safe_live.test.js`; явный гард — follow-up (backlog).

## Тесты
- DB-free unit `tests/test_assign_publishable_type.test.js` (clause ON/OFF + kill-switch) — 5/5.
- LIVE: `test_assign_publishable_type_live.test.js` (2), `test_dispatch_task_type_guard.test.js` (2), `test_cleanup_wp217_live.test.js` (3), `test_manual_queue_preview_safe_live.test.js` (1) — 8/8.
- Полный `npm test` после merge с main: наши изменения зелёные; 2 fail вне scope — `tests/test_preempt_for_device.test.js` (WP#214, флак) и `tests/test_manual_publish_queue.test.js::takeItem: 404` (pre-existing на чистом origin/main).
- Codex-review (`codex exec review --base origin/main`): продакшн одобрен; 1 P1 (тест импортирует `server.js` → будит cron) **принят как существующая идиома репо** (ср. `test_dispatch_manual_guard.test.js` WP#125).

## Деплой
1. PR#147 merged → main `466d056`.
2. Прод autowarm `/root/.openclaw/workspace-genri/autowarm`: `git pull origin main --ff-only` (5dd8e25 → 466d056).
3. `sudo pm2 restart 35` (autowarm/server.js — гарды A/B живут в долгоживущем процессе). Online, без ошибок старта.
4. **Cleanup отработал на проде:** `node cleanup_wp217_scheme_preview_leak.js --apply` → **64 pending отменены** (`skip_reason='scheme_preview_leak'`); повторный dry-run = 0 (идемпотентно). Активная публикация остановлена; дедуп assign не пускает повторно (`scheme_preview_leak` ≠ `moved_from_slot%`).

## Процесс
brainstorm → spec → plan → subagent-driven (4 таска, two-stage review: spec-compliance + code-quality каждый, opus final-review) → codex → merge → deploy.

## Остаток
1. **Ops:** удалить **11 опубликованных** превью-роликов (Ирбис `irbis_talent`/`irbis.academy` + Мурат `Murat_Invest_Flow`, YT Shorts + TikTok) — URL в коментах OpenProject #217 (id 993).
2. **Verify (~сутки):** 0 новых `scheme_preview` в publish_queue; счётчик `non_publishable_task_type` в логах диспатча → WP#217 «Готово».
3. **Follow-up (backlog):** явный `task_type='unic'` гард в `manual_queue_assign.js` (defense-in-depth).

## Kill-switches (default ON, откат без передеплоя)
- `ASSIGN_PUBLISHABLE_TASK_TYPE_GUARD_ENABLED=false` — отключить allowlist A.
- `DISPATCH_TASK_TYPE_RECHECK_ENABLED=false` — отключить зеркало B.
