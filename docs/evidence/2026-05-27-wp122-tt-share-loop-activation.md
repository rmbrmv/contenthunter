# WP #122 — Активация share-loop overlay handler — EVIDENCE (2026-05-27)

**OpenProject:** [#122](https://openproject.contenthunter.ru/wp/122)
**PR (код, ранее):** [GenGo2/delivery-contenthunter #106](https://github.com/GenGo2/delivery-contenthunter/pull/106) (merge `2972cce`, прод)
**Spec:** `docs/superpowers/specs/2026-05-27-wp122-tt-share-loop-activation-design.md`
**Plan:** `docs/superpowers/plans/2026-05-27-wp122-tt-share-loop-activation.md`

## Что было не так

Код WP #122 (детект+dismiss окна «Добавить в историю» в TT share-loop) был в проде с 26.05, но рубильник `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED` стоял OFF и в `.env` не выставлялся → фикс в бою не работал, `tt_upload_confirmation_timeout` сохранялся. 24h-verify 27.05 переоткрыл WP. Остаток: смок → включить → мониторить.

## Что сделано (27.05)

**Task 1 — testbench → WP#122.** `/home/claude-user/autowarm-testbench` `git pull --ff-only` до `a47c49c` (вносит merge `2972cce`). Паритет: хендлер `_run_tt_stories_overlay_share_loop_hook` присутствует (`publisher_tiktok.py:1533`, вызов `:1958`). `node_modules` — реальная директория (symlink-гоча не сработала). pm2 `autowarm-farming-testbench` рестартнут.

**Task 2 — флаг на стенде.** `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true` в `.env` стенда (идемпотентно).

**Task 3 — смок на #19 (`RF8YA0W57EP`), ГЕЙТ зелёный.**
- Канонический смок: INSERT pending `testbench=true` TT-задачи (seed `/home/claude-user/testbench-seed/tiktok/pq_251_...mp4`, аккаунт `user70415121188138`), диспетчер запускает.
- Результат задачи **11241**: `awaiting_url` (видео опубликовано: `tt_post_publish_success_inferred` → `post_url_partial`), `error_code` пуст.
- Гейт-метрики: `share_loop_evts=0`, `dismissed=0`, `tt_5_share_loop_*_stuck=0`, `tt_upload_confirmation_timeout=0`. Оверлея в прогоне не было (спорадический) → хук вернул `clean`, **основной путь публикации не сломан** — главный регресс-гард пройден.

**Task 4 — включение в проде, без рестарта.**
- Флаг дописан в `/root/.openclaw/workspace-genri/autowarm/.env` (owned `claude-user`, без sudo). Время ~12:10 МСК.
- **Рестарт не требуется:** `publisher.py:33 load_dotenv('.env')` выполняется на каждом спавне, флаг python-сторонний (server.js его не читает) → новые публикации подхватывают флаг, in-flight не тронуты (zero disruption). Дефинитивно проверено: `env -u TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED python3 -c "load_dotenv(); ..."` → `true`.

**Task 5 — ранний health-чек (12:10–13:25, flag-ON cohort: TT-прод, 11 задач).**
- Исход: 7 ok (`done`/`awaiting_url`), 3 failed, 1 pending.
- WP#122-сигналы: `tt_5_share_loop_*_stuck=0`, `*_dismissed (samsung/inapp, phase=share_loop)=0` → **ноль ложных срабатываний/залипаний хендлера на критичном пути**.
- 3 падения — НЕ регресс #122: `11339` `process_interrupted` (PM2-шум), `11341` `tt_account_sheet_closed_before_parse` (свитчер, не share-loop), `11353` `tt_upload_confirmation_timeout` но БЕЗ samsung/inapp-overlay-события (таймаут по другой причине, вне субрежима #122).
- Success 7/10 (≈78% без PM2-шума) — в норме (baseline сегодня 58-67%). **Регресса нет.**

## Урок (поправки к плану)

1. **Testbench-публикатор PM2 id 33 `autowarm-testbench`** (cwd прод-дир) САМ диспатчит pending `testbench=true` `publish_tasks` (поллит таблицу, не только `publish_queue`). Канонический смок = **только INSERT**; ручной `publisher.py <id>` создаёт гонку двух процессов на устройстве (на 1й попытке смока, 11149, пришлось отменить; чужой root-процесс `sudo kill` вне скоупа — дождался завершения, перезапустил чисто).
2. **Включение env-флага publisher не требует рестарта** server.js (load_dotenv на спавн). Рестарт `pm2 35` ВРЕДЕН: на старте `pkill -f publisher.py` (server.js:8698) прервал бы in-flight, а прод публикует непрерывно (окна running=0 нет).

## Что осталось

- **Эффективность (длиннохвост):** окно «Добавить в историю» спорадическое — в смоке и в раннем чеке не всплыло, поэтому реальный dismiss ещё не наблюдался. Подтвердить на последующих пачках по `tt_samsung_overlay_dismissed`/`tt_inapp_stories_dismissed` (phase=share_loop) + динамике `tt_upload_confirmation_timeout`. До тех пор WP в «Тестировании».
- **Откат (если регресс):** убрать строку `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED` из прод `.env` — новые публикации вернутся к OFF (рестарт не нужен).

## Статус

Фикс активирован в проде (флаг ON с ~12:10 27.05), ранний health-чек зелёный (регресса нет). WP #122 → «Тестирование» под длиннохвостое наблюдение эффективности.
