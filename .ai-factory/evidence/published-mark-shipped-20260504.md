# Published mark on source content — SHIPPED 2026-05-04

## Резюме

Реализована фича «отметка о публикации» на исходник видео — пользователь видит на дашборде бейдж «📣 опубликовано» сразу после первой успешной выкладки, и в карточке контента — блок с разбивкой по платформам (IG/TT/YT, счётчик аккаунтов, click-to-expand до списка @usernames).

End-to-end задеплоено: миграция, backend, frontend. PR #5 merged + hotfix `66497f4`.

## Артефакты

- **Spec:** `.ai-factory/plans/published-mark-on-source-content-design-20260504.md` (commit `6e029605a`)
- **Plan:** `.ai-factory/plans/published-mark-on-source-content-plan-20260504.md` (10 tasks, TDD)
- **PR:** https://github.com/GenGo2/validator-contenthunter/pull/5
- **Backend tests:** 25/25 pass на проде

## Хронология

1. **Brainstorm** — 5 секций дизайна (data model + API + UI + edge cases + spec structure), 3 уточняющих вопроса, рекомендация → live JOIN + новая ось `is_published` (отказ от lazy-override `status` enum'а во избежание коллатерального ущерба CSS-веткам approval).
2. **Implementation plan** — 10 задач с TDD-циклами (failing test → impl → green → commit) и точными путями файлов.
3. **Subagent-driven execution** — 9 имплементационных агентов + 7 ревьюверов (spec compliance + code quality), все задачи прошли с ⚠️minor либо ✅Ship.
4. **Прод-деплой** — миграция (3 partial-индекса), pm2 restart validator, frontend через npm postbuild hook (auto-cp в `/var/www/validator/`).
5. **Hotfix** — выяснилось что клиентский /dashboard рендерит слоты inline в `ClientDashboard.vue` (не через `SlotCard.vue`); фикс `66497f4` повторил бейдж-логику в inline-разметке.

## Урок (зафиксировано в memory)

`feedback_validator_two_slot_renderers` — Validator имеет ДВА места рендеринга карточки слота: `SlotCard.vue` (manager-view) и inline в `ClientDashboard.vue` (клиентский /dashboard). При изменении логики бейджа/drag — патчить оба.

`feedback_validator_postbuild_autodeploy` — `npm run build` валидатора через `postbuild` hook сразу выкатывает в прод (`/var/www/validator/`). Pre-flight `package.json` перед фронтовой работой.

## Открытые follow-ups

1. `routers/content.py:90` — N+1 в list endpoint `/api/content` (заменить на bulk `get_published_flags`)
2. `routers/schedule.py:367` — N+1 в `tray_validate` цикле (вынести bulk-fetch перед циклом)
3. `_content_to_dict_with_publish` — type-hints + docstring polish

Закрыть единым cleanup-коммитом, не блокер для прода.

## Технические детали

- **Источник истины:** live JOIN `validator_content ← unic_tasks ← unic_results ← publish_queue WHERE status='done'` + carousel-arm через `pq.carousel_content_id`. Whitelist `lower(platform) IN ('instagram','tiktok','youtube')`.
- **Performance:** замер 4.5ms на 11 контентов без новых индексов; с partial-индексами уйдёт под 1ms на 30 слотов недели.
- **Bulk-pattern:** `get_published_flags([content_ids])` — один SQL для дашборда, без N+1 (за исключением tray_validate, см. follow-up).
- **Backout:** убрать `is_published` / `published_summary` из API response → фронт деградирует graceful'но (badge старый, блок не рендерится).

## Безопасность

В ходе работы три GitHub-токена попали в conversation transcript:
- `GITHUB_TOKEN_GENGO2` (classic PAT, `ghp_yt...`)
- Fine-grained PAT в prod git remote `/root/.openclaw/workspace-genri/validator/` (`github_pat_11BW...`)
- `rmbrmv/contenthunter` token из `~/secrets/github.env` (`ghp_w3...`)

Рекомендована ротация всех трёх + обновление `~/secrets/*.env` и затронутых git remote URL'ов.
