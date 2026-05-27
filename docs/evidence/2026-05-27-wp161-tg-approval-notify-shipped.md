# WP#161 — Telegram-уведомления одобрение/отсутствие контента — SHIPPED+DEPLOYED

**Дата:** 2026-05-27
**OpenProject:** #161 (исполнитель Данил) → «Тестирование»
**Спека/план:** `docs/superpowers/specs/2026-05-27-wp161-tg-approval-notify-design.md`, `docs/superpowers/plans/2026-05-27-wp161-tg-approval-notify.md`

## Проблема

Аня пропускала ролики, ожидающие ручного одобрения, и клиентов без загруженного контента → выкладка стартовала с опозданием на день. Нужна регулярная Telegram-сводка обоих пробелов.

## Зафиксированные решения (закрыты автором на брейншторме)

| Развилка | Решение |
|---|---|
| Адресат | Тред «Модерация и уникал» — `chat -1003262248975`, `thread 10477`, бот `@gengo_tech_notify_1_bot` |
| Каденция | Раз в час, окно **09–18 МСК**, пустые часы пропускаем |
| «На одобрении» | `validator_content.status = 'needs_review'` |
| «Нет контента» | Пустые слоты `validator_schedule_slots` (content_id NULL / status='empty') на завтра+послезавтра, активные проекты |
| Упоминание | `@gengo_care` в конце сообщения (env `APPROVAL_NOTIFY_MENTIONS`, ''=выкл) |

## Что сделано

- Новый модуль `approval_notify.js` (autowarm) по образцу `daily_publish_report.js` (WP#114) + общий хелпер `telegram_send.js` + миграция `approval_notify_runs` (per-hour claim идемпотентность) + регистрация крона в `server.js`.
- Один SQL по единой БД `openclaw` (валидатор + расписание в одной БД). Даты форматируются в SQL (tz-safe). Счётчик роликов = distinct `vc.id` (codex P2).
- Токен: фолбек `APPROVAL_NOTIFY_BOT_TOKEN ?? DAILY_REPORT_BOT_TOKEN` (тот же бот) — прод `.env` под root не правили.
- Kill-switch `APPROVAL_NOTIFY_ENABLED=0`. Окно `APPROVAL_NOTIFY_WINDOW=9-18`, `APPROVAL_NOTIFY_SUPPRESS_EMPTY=1`.
- TDD: 31 тест GREEN. codex review спеки/плана 0 P1. Subagent-driven (8 тасков, спека+качество ревью на каждый + live-SQL валидация) + финальное holistic-ревью (READY TO MERGE).

## Деплой

- Код → **GenGo2/delivery-contenthunter main** (push: фича `9ac3cc3`, упоминание `a507a64`). Прод (`/root/.openclaw/workspace-genri/autowarm`, ветка main) подтянул, `autowarm` перезапущен (PM2), крон зарегистрирован: `[approval-notify] scheduled hourly, MSK window 9-18`.
- Миграция `approval_notify_runs` применена к прод-openclaw.
- Доки (спека+план) → contenthunter `origin/main`.

## Верификация (прод)

- Смок `node approval_notify.js --once`: реальное сообщение ушло в тред «Модерация и уникал», `approval_notify_runs` → `status=sent`, `has_mention=t` (payload содержит `@gengo_care`), длина ~1886 симв (лимит TG 4096 — гард не нужен).
- Идемпотентность: повторный `--once` в тот же час → `skip (already sent)`.
- Живые данные на момент деплоя: 124 ролика на одобрении / 69 клиентов с пустыми слотами.

## Остаток

- Verify первой **автоматической** отправки крона в окне 09–18 МСК (~утро 28.05) → «Готово».

## Находки / решения по ходу

- **Прод autowarm крутится из `/root/.openclaw/workspace-genri/autowarm`, ветка `main`** (origin GenGo2/delivery-contenthunter), авто-пуллит. `feat/wp109-delivery-planner` — устаревшая локальная dev-ветка (НЕ прод); ранний merge туда откатан.
- Деплой кода = push в GenGo2 main → прод `git pull` (нужен root) → `sudo pm2 restart autowarm`. Прод `.env` под root — claude-user не правит (sudo только pm2/systemctl/chown).
- **Продуктовое решение (declined follow-up):** блок «на одобрении» показывает старые плановые даты (ролики висят с прошлых дат) — оставлено **по спеке**, фильтр `slot_date >= today` НЕ вводим (решение Данила).
