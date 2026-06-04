# WP#223 C1 — разведка источника тестбенч-DELETE

**Дата:** 2026-06-04
**Цель:** найти, кто удаляет `testbench=TRUE` строку из `publish_tasks` на стадии `awaiting_url` раньше записи терминального статуса/URL (смок #14496: COMMIT_FIRED→awaiting_url→строка исчезла).

## Проверенные источники — DELETE НЕ НАЙДЕН

| Источник | Результат |
|---|---|
| **DB-триггеры** на `publish_tasks` (`pg_trigger`) | Только `publish_tasks_failed_notify` (AFTER UPDATE, notify-on-fail). **DELETE-триггера нет.** |
| **DB-правила** (`pg_rules`) | Нет. |
| **crontab** (claude-user + root) | Пусто. |
| **/etc/cron.d** | `claude-code-update`, `e2scrub_all`, `sysstat`, `validator-assets-cleanup` — ни один не трогает publish_tasks. |
| **systemd-таймеры** | `autowarm-publish-media-sweeper` (удаляет только файлы `/tmp/publish_media` старше 6ч, НЕ строки БД); `autowarm-testbench-rollback`→`auto_rollback.py` (только SELECT testbench-строк, не DELETE). |
| **Статический grep** `DELETE FROM publish_tasks` / `TRUNCATE` / `.delete()` по обоим чекаутам (`/root/.openclaw/workspace-genri/autowarm` + `/home/claude-user/autowarm-testbench`), исключая тесты | **Пусто.** В проде нет ни одного DELETE по publish_tasks. |
| **testbench-start/stop.sh**, `canary_inserter.py` | DELETE по publish_tasks нет (DELETE `WHERE is_canary=TRUE` существует только в `test_canary_inserter.py` — тестовый teardown). |

## Вывод

Источник DELETE — **вне кодовой базы прода**: вероятнее всего ручное действие оператора во время триажа (ручной `DELETE FROM publish_tasks ...` для очистки доски) либо ad-hoc скрипт вне обоих чекаутов.

## Рекомендация для C2 (Task 7)

**Защитный BEFORE DELETE триггер** — двойного назначения:
1. **Фикс:** блокирует удаление `testbench=TRUE` строк в pre-terminal статусах (`pending`/`running`/`processing`/`awaiting_url`) → тестбенч-результаты доживают до терминала.
2. **Детектор:** при следующем срабатывании мистического делетера `RAISE EXCEPTION` покажет `pg_backend_pid()` и `application_name` в PG-логах → однозначная идентификация источника без интерактивного smoke.

Гард НЕ трогает прод-строки (`testbench` IS NULL/FALSE) и легитимную чистку терминальных тестбенч-строк (`done`/`failed`/`published_no_url`/`cancelled`).

**⚠️ Применение на ЖИВОЙ host-PG (`openclaw`@localhost:5432) — прод-изменение; согласовать с Данилом перед apply.**
