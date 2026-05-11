# Publishing Dashboard — shipped 2026-05-11

**Spec:** [docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md](../docs/superpowers/specs/2026-05-11-publishing-dashboard-design.md)
**Plan:** [docs/superpowers/plans/2026-05-11-publishing-dashboard-implementation.md](../docs/superpowers/plans/2026-05-11-publishing-dashboard-implementation.md)
**Endpoint:** `GET /api/publish-queue/dashboard`
**UI:** https://delivery.contenthunter.ru/#publishing/publishing-dashboard

## Что отгружено

Новый подраздел «📊 Дашборд» в модуле «📤 Выкладка» с KPI-карточками (`Всего / Ожидание / Выполняются / Готово / Ошибки / Отменено / Success rate`) и разбивкой по платформам IG/TT/YT. Пресеты `Сегодня / Неделя / Месяц / Свой диапазон` рассчитываются на сервере в Europe/Moscow (календарные границы, UTC+3 fixed). Восстановление состояния из URL hash для bookmark'ов.

## Commits (в `/root/.openclaw/workspace-genri/autowarm/`)

| # | SHA | Сообщение |
|---|---|---|
| 1 | `db00c97a6` | feat(publish-dashboard): add pure helpers — calcDashboardRange/mapDashboardRows/computeSuccessRate |
| 2 | `8fe32da` | docs(publish-dashboard): restore MSK-frame / cutoff WHY-comments + contract test |
| 3 | `146eb92` | feat(publish-dashboard): add GET /api/publish-queue/dashboard endpoint |
| 4 | `839a16b` | feat(publish-dashboard): add sidebar nav + section scaffold + JS stubs |
| 5 | `4fb11ff` | feat(publish-dashboard): replace stubs with preset state + custom range |
| 6 | `5ac3806` | feat(publish-dashboard): wire data load + render overall/platforms |
| 7 | `0c26a03` | feat(publish-dashboard): restore preset + custom range from URL hash |

Auto-push hook отправил все 7 коммитов в `GenGo2/delivery-contenthunter` automatic.

## Архитектура

**Backend** (`server.js`, ~125 строк):
- 3 pure-функции: `calcDashboardRange(preset, fromStr, toStr, nowMs)` → `{preset, from: Date, to: Date}`; `computeSuccessRate(done, errors)` → `0..1 | null`; `mapDashboardRows(rows)` → `{overall, by_platform}`.
- 1 endpoint `GET /api/publish-queue/dashboard` с `requireAuth`. SQL — один `GROUPING SETS ((platform), ())` запрос с `GROUPING(platform) AS is_grand_total` чтобы разделить grand-total от реальных `NULL`-platform строк (`past_slot_dropped` audit-вставки).
- 25 unit-тестов в `tests/test_publish_dashboard.test.js`. Полная JS-suite: 107/107 pass.

**Frontend** (`public/index.html`, ~140 строк):
- Новая кнопка «📊 Дашборд» первой в `sidebar-publishing`; новая секция `section-publishing-dashboard`.
- `defaultSections.publishing` смещён с `'publishing'` → `'publishing-dashboard'` (клик на module-tab Выкладка теперь открывает дашборд).
- `sidebarMap['publishing-dashboard'] = 'publishing'`.
- State: `_dashCurrentPreset / _dashCustomFrom / _dashCustomTo`.
- 4 функции: `switchDashboardPreset(preset)`, `applyDashboardCustom()`, `loadPublishingDashboard()` (async fetch), `renderDashboardOverall(o)` + `renderDashboardPlatforms(bp)`.
- URL restore в `nav('publishing-dashboard')` через `getSubParam()` → parse `dash:<preset>[:from:to]` → set state → `switchDashboardPreset` (один fetch, без double-load).

## Verification

| Check | Result |
|---|---|
| Unit tests (helpers) | 25/25 pass |
| Full JS suite | 107/107 pass |
| PM2 reload `autowarm` | online, uptime confirmed, no errors |
| HTTP `/api/publish-queue/dashboard?preset=today` (no auth) | 401 (route registered, middleware fires) |
| Live SQL cross-check (today) | overall=58, IG=19, TT=20, YT=19 — sums consistent |

## Codex review rounds

| File | Round | Verdict |
|---|---|---|
| Spec v1 | 1 | 1 P2 (GROUPING(platform) разделить grand-total от NULL-platform) |
| Spec v2 | 2 | CLEAN |
| Plan v1 | 1 | 1 P1 + 2 P2 (stub-before-nav-wire; custom-restore без load; per-date cutoff отсутствовал) |
| Plan v2 | 2 | 2 P2 (тесты противоречили span-check) |
| Plan v3 | 3 | CLEAN |

## Known limitations / backlog

- Нет project/account фильтра в дашборде.
- Нет графиков тренда (line chart за 30 дней).
- Нет drill-down: клик по «Ошибки» NOT переходит в Запланировано с фильтром.
- Платформы `vk` / `pinterest` / `likee` / NULL учитываются в `overall.total`, но не показаны отдельной строкой → возможна «дельта» между overall и sum(IG+TT+YT). Visible only via SQL.
- No auto-refresh — manual только.

## Memory note

Создать `~/.claude/projects/-home-claude-user-contenthunter/memory/project_publishing_dashboard_shipped.md` с краткой ссылкой на endpoint + sidebar route + scope.
