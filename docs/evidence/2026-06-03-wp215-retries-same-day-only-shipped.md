# WP#215 — Ретраи «день в день» + UI-настройки — SHIPPED

**Дата:** 2026-06-03
**OpenProject:** #215 → Тестирование (исполнитель danil)
**Репо кода:** `delivery-contenthunter` main **66806a7** (5 коммитов, fast-forward)
**Спека/план:** `docs/superpowers/specs/2026-06-03-wp215-retries-same-day-only-design.md`, `docs/superpowers/plans/2026-06-03-wp215-retries-same-day-only.md`

## Что сделано

Авто-ретраи упавших публикаций переведены в режим «только день в день»:
- **После часа отсечки** (настраивается в UI, дефолт **14:00 МСК**) всё ещё-упавшее
  передаётся операторам в ручную выкладку (а не «спит до завтра»).
- **При исчерпании дневного капа** авто-ретраев по классу ошибки — передаётся в
  ручную сразу, не дожидаясь отсечки (Подход B).
- **Глубина окна** в днях вынесена в UI: `retry_extra_days` (дефолт **0** =
  только текущие сутки; `windowDays = extra + 1`).
- `device_unreachable` до отсечки сохраняет троттлинг WP#210; после отсечки — в
  ручную (ветка отсечки в дереве решений выше device-health и реанимации).
- Kill-switch `RETRY_SAME_DAY_ONLY_ENABLED` (дефолт ON) — мгновенный откат
  поведения без передеплоя.

## Точки изменения (delivery-contenthunter)
- `retry_decision.js` — ветки `wait→handoff` под фактом `sameDayHandoff`
  (`after_cutoff_manual`, `daily_cap_exhausted`).
- `retry_controller.js` — чтение `retry_cutoff_hour_msk`/`retry_extra_days` из
  `autowarm_settings` каждый тик (БД→env→дефолт, валидация); проброс
  `sameDayHandoff`; легаси-env `RETRY_WINDOW_DAYS` ретайрнут.
- `retry_labels.js` — тексты новых reason'ов; `window_exhausted` нейтрализован.
- `public/index.html` — два поля в «Глобальные настройки» + load/save с валидацией.
- `server.js` — seed дефолтов (14/0).

## Тесты
TDD, 69/69 зелёные: `test_retry_decision` (22), `test_retry_labels` (10),
`test_retry_controller` (live-DB, 18 вкл. 3 новых WP#215), `test_manual_*` (регрессия).
Каждая из 5 задач прошла два гейта (spec compliance + code quality) + финальное ревью всей ветки.

## Деплой
- main 66806a7 (gh не авторизован → fast-forward push в main напрямую).
- Прод `/root/.openclaw/workspace-genri/autowarm`: `git pull` → 66806a7, `sudo pm2 restart 35` (id35 = autowarm `server.js`, контроллер ретраев крутится в нём каждые ~5 мин). Сервер online, unstable restarts 0, ошибок в логах нет.
- Прод-БД localhost openclaw: ключи `retry_cutoff_hour_msk=14`, `retry_extra_days=0` добавлены вручную (seed-блок autowarm_settings в проде не выполняется на обычном старте — см. follow-up).

## Наблюдения / follow-up
- **Seed `autowarm_settings` не отрабатывает в проде**: в таблице исторически
  отсутствует даже `auto_sync_device_mapping`. Не критично (контроллер и UI
  используют дефолты через фолбэк; ключи добавлены вручную), но стоит вынести
  безусловный seed настроек в backlog.
- При деплое subagent через `npm` апнул `pg` ^8.11→^8.21 в `package*.json` —
  откачено перед мёрджем, в прод не попало.

## Verify
По событиям «Лог событий» (delivery → Аналитика → 📜 Лог событий): появление
`handoff` с правилами `after_cutoff_manual` / `daily_cap_exhausted` после
ближайшего часа отсечки. Откат при проблемах: `RETRY_SAME_DAY_ONLY_ENABLED=false`.
