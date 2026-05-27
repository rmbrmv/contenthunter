# WP #165 — Инфра-инцидент `watchdog_subprocess_hang`: разведка + защита

**Дата:** 2026-05-27
**Тип:** Ошибка (разведка + решение)
**Ветка:** `wp165-watchdog-hang-triage`
**Статус:** спека на ревью

---

## 1. Суть инцидента

Ночью **21:00 МСК 26.05 → 02:59 МСК 27.05** publish-subprocess'ы массово зависали (нет
heartbeat) и убивались watchdog'ом по всем трём платформам. `error_code =
watchdog_subprocess_hang`: Instagram 473 + TikTok 60 + YouTube 31. В пике (02:00 МСК /
23:00 UTC) Instagram = 205/205 = 100% падений. Успех IG: 25.05 = 79% → 26.05 = 24.7% →
27.05 = **11.1%**. Резкое восстановление ровно в **03:00 МСК** (00:00 UTC: 25 успехов из
42 задач, 0 hang).

Тикет просил разведку причины и решение, нужна ли защита. **Разведка проведена** (раздел 2),
по итогам выбрана защита (раздел 4).

---

## 2. Разведка: что показала форензика

Все временные окна — UTC; МСК = UTC+3. Окно инцидента = 18:00–23:59 UTC 26.05.

### 2.1. Сигнатура (100% одинаковая на 551 задаче)
- Задача переведена в `running` (started_at проставлен), дальше **0 событий в `events`,
  heartbeat не сработал НИ РАЗУ** (`updated_at` замёрз на `started_at`), kill watchdog'ом
  ровно на пороге 3 мин.
- **0 внутренних `watchdog_fired`** (per-step timeout не срабатывал) → процесс
  блокировался/умирал **до** того, как поднялись heartbeat-поток (`publisher_base.py:503`)
  и per-step watchdog, и **до** первого DB-write в `run()` (`update_status('running')`,
  `publisher_base.py:4266`, двигает `updated_at`).

### 2.2. Масштаб — это ретрай-шторм
- 551 hang = **всего 28 уникальных публикаций** (28 `client_publish_id`, 27 аккаунтов,
  26 устройств). Каждая ретраилась ~20× (топ-аккаунты по 32–35 hang).
- Механизм раздувания: watchdog kill → `publish_queue.status='pending'`
  (`server.js:7061-7065`) → `dispatchPublishQueue` (каждые 5 мин) пересоздаёт publish_task →
  scheduler запускает → снова hang. **У этого цикла нет ограничения по cpid.**
- WP#108 retry-движок (лимит 3/класс/день) тут **ни при чём**: он запускается в 05:00 МСК,
  ПОСЛЕ окна. Раздувал именно watchdog-реквью.

### 2.3. Что ИСКЛЮЧЕНО (доказательно)
| Версия | Опровержение |
|---|---|
| Перегрузка хоста (CPU/RAM/IO) | `sar` за окно: CPU 85–98% idle, iowait≈0, RAM 13–18% (~5 ГБ free), load-avg <2.4 (один всплеск 12.1), 0 заблокированных процессов, 0 swap. В 23:00 UTC система фактически спала, и при этом 205/205 hang. |
| Исчерпание коннектов Postgres | PG-лог за сутки крошечный (1.5–1.8 КБ), ни одного `FATAL: too many clients`, journald по PG за окно пуст. Пиковая конкурентность publisher'ов = 25 при `max_connections=100`. Коннекты не отвергались. |
| Зависание на ADB-мосту | heartbeat пишет в **localhost-Postgres**, не через мост. Блок на мосту не заморозил бы heartbeat. К тому же до heartbeat нет ни одного adb-вызова (`publisher.py:506–532` — только localhost DB connect/fetch/маппинг). |
| Конкурирующие autowarm-scheduler'ы | 6 «лишних» `node server.js` — это ДРУГИЕ сервисы (`hr-payroll`, `producer-copilot`, `farm-platform`, `openclaw-dashboard`, `carousel-maker`, `task-tracker`). Autowarm-scheduler ровно один (pid 1760612). |

### 2.4. Вероятная первопричина (с честной неопределённостью)
В ночном окне publish-subprocess'ы **не могли завершить раннюю запись в localhost-Postgres**
(heartbeat + status) и убивались до начала работы. Хост, ёмкость коннектов и ADB-мост —
**все были здоровы**. Наиболее вероятный механизм — **блокировка на пути записи**
(lock-wait на `publish_tasks`); это согласуется с «idle CPU + мёртвые DB-writes», но
**не доказано**, т.к. `log_lock_waits=off`.

**Точный триггер не восстановим из retained-данных**, потому что система слепа:
- watchdog при kill не сохраняет шаг, на котором стоял процесс;
- subprocess ничего не пишет в перехватываемый stdout (`[publish#id]`-строк нет ни в одном часу);
- heartbeat **глотает исключение** (`except: log.warning`, `publisher_base.py:530`) и молча
  перестаёт двигать `updated_at`;
- `log_lock_waits=off`, `log_connections=off` в Postgres;
- даже лог запусков терялся: в 00:00 UTC `📤 Запуск`==стартовавшие задачи (42=42), а в
  21–23 UTC — 15/6/0 запусков логировано против 187/193/205 реально стартовавших.

**Главный вывод:** мы **не видим** этот класс инцидента. Наблюдаемость+алерт и ограничение
ретрай-шторма — необходимость, а не опция.

---

## 3. Цели и не-цели

**Цели:**
1. Остановить ретрай-шторм: ограничить бесконечный watchdog → pending → dispatch цикл по
   одной публикации.
2. Сделать инцидент **видимым** в реальном времени (алерт при всплеске hang).
3. Закрыть слепые пятна диагностики, чтобы рецидив можно было доразобрать.

**Не-цели (явно вне scope, с обоснованием):**
- **ADB-preflight перед батчем** — разведка показала, что мост в инциденте здоров и
  heartbeat=localhost; preflight этот инцидент бы не поймал и рискует ложно блокировать
  живой батч (прецедент over-fire WP#119: IG 79%→22%).
- **Чистка «зомби» / единый scheduler** — основано на опровергнутой гипотезе; autowarm-scheduler
  уже единственный, остальные процессы — другие сервисы.
- **Починка самой первопричины блокировки DB-write** — триггер не локализован; данная WP даёт
  защиту от класса проблемы и инструменты для локализации рецидива.

---

## 4. Дизайн

Три независимых компонента, каждый за своим kill-switch.

### 4.1. Компонент A — Circuit-breaker ретрай-шторма

**Где:** `server.js` `watchdogRunningTasks()`, в точке реквью (стр. 7060-7065).

**Идентичность публикации:** `publish_queue.id` стабилен между ретраями (watchdog сбрасывает
ту же строку pq в pending; dispatch создаёт новый publish_task, но pq тот же). Поэтому счётчик
живёт на `publish_queue`.

**Миграция:** `publish_queue.watchdog_hang_streak INT NOT NULL DEFAULT 0`
(файл `migrations/`, см. [[feedback_migrations_for_writers]]).

**Логика:**
1. При watchdog-kill задачи, привязанной к pq: `watchdog_hang_streak = watchdog_hang_streak + 1`.
2. Если `watchdog_hang_streak < WATCHDOG_BREAKER_MAX_STREAK` (default 3):
   реквью как сейчас (`pq → pending`, `publish_task_id=NULL`).
3. Если `watchdog_hang_streak >= WATCHDOG_BREAKER_MAX_STREAK`:
   **не реквьюить в pending.** Вместо этого — маршрутизировать в ручную очередь через
   существующий хелпер `handoffToManual(pq, reason='watchdog_hang_breaker')`
   (`retry_controller.js:98`): он ставит `pq.status='cancelled'`, `skip_reason`,
   `manual_handoff_at` и вставляет строку в ручную очередь. Так публикация **гарантированно
   не теряется** и попадает к человеку. Записать событие + засчитать в алерт (компонент B).
   *Открытая суб-развилка:* если связывать breaker с handoff-плумбингом нежелательно —
   fallback-вариант «просто park: `pq.status='cancelled'` + `skip_reason` + алерт» (тогда
   восстановление только ручное по алерту). Рекомендую handoff-вариант.
4. Сброс `watchdog_hang_streak=0` на успешной публикации (success-путь sync-queue/dispatch,
   где `pq → done`).

**Эффект:** 28 публикаций × ~20 ретраев → максимум 28 × 3 = 84 hang вместо 551, и ночь
устройств не сжигается впустую.

**Kill-switch:** `WATCHDOG_BREAKER_ENABLED` (default `'true'`). При `'false'` — старое
безусловное реквью. `WATCHDOG_BREAKER_MAX_STREAK` (default 3).

### 4.2. Компонент B — Алерт при всплеске hang

**Где:** новая функция в `server.js`, отдельный `setInterval` (или хвост `watchdogRunningTasks`).

**Логика:** считаем `count(*) FROM publish_tasks WHERE error_code='watchdog_subprocess_hang'
AND updated_at > NOW() - INTERVAL 'WATCHDOG_ALERT_WINDOW_MIN minutes'`. Если
`>= WATCHDOG_ALERT_THRESHOLD` — отправляем TG-алерт. **Дедуп:** не чаще раза в
`WATCHDOG_ALERT_COOLDOWN_MIN` (in-memory timestamp), чтобы не спамить весь шторм.

**TG-плумбинг:** переиспользуем существующий (`daily_publish_report.js:235` —
`https://api.telegram.org/bot${token}/sendMessage`), env `DAILY_REPORT_BOT_TOKEN` /
`DAILY_REPORT_CHAT_ID`. Текст: окно, число hang, разбивка по платформам, число затронутых cpid.

**Kill-switch:** `WATCHDOG_ALERT_ENABLED` (default `'true'`). Пороги:
`WATCHDOG_ALERT_THRESHOLD` (default 20), `WATCHDOG_ALERT_WINDOW_MIN` (default 30),
`WATCHDOG_ALERT_COOLDOWN_MIN` (default 60).

### 4.3. Компонент C — Диагностика (закрыть слепые пятна)

**C1. Сохранять шаг при kill (server.js watchdog).** Парсить из `task.log` последнюю строку
`💓 [platform] {current_step}` (heartbeat пишет current_step в `log`) и класть в
`meta.last_step` kill-события. Если heartbeat не сработал (как в этом инциденте) — `meta.last_step=null`,
что само по себе сигнал «умер до первого heartbeat».

**C2. Сделать сбой heartbeat видимым (publisher_base.py:530).** Сейчас исключение глотается.
Поскольку при сбое DB-write писать в ту же БД бессмысленно, дублировать текст исключения в
**stderr** (его перехватывает scheduler с префиксом `[publish#id]`) и в файл-fallback
`/tmp/autowarm_heartbeat_fail/<task_id>.log`. Так при рецидиве будет видно, чем именно падает
connect/UPDATE (lock / timeout / refused).

**C3. `log_lock_waits=on` в Postgres.** Правка `postgresql.conf` + `sudo systemctl reload
postgresql` (reload, не restart; sudo systemctl — в scope). Логирует только ожидания лока
> `deadlock_timeout` (дёшево). Закрывает слепоту именно по версии lock-wait. Только
`log_lock_waits` — `log_connections` НЕ включаем (connect-per-event дизайн → флуд).

**Kill-switch:** `WATCHDOG_DIAG_ENABLED` (default `'true'`) гейтит C1/C2. C3 — конфиг PG,
откат = вернуть `off` + reload.

---

## 5. Тестирование

- **Юнит (node):** `test_watchdog_breaker.test.js` — streak инкремент/сброс, граница порога
  (N-1 → реквью, N → breaker), путь NULL-cpid (по pq_id). Стиль live-теста как
  `test_retry_controller.test.js` (dedicated client, BEGIN/ROLLBACK).
- **Юнит:** алерт — порог, дедуп-cooldown, формат текста (мок fetch).
- **Юнит:** парсинг `last_step` из `log` (есть строка `💓` / пустой log → null).
- **Python smoke:** heartbeat-сбой пишет в stderr + файл-fallback (мок `psycopg2.connect`
  кидает исключение).
- **Live-smoke на testbench:** искусственно заморозить subprocess (sleep до watchdog) →
  проверить инкремент streak, срабатывание breaker на N, алерт.
- `codex review` спеки и плана (раундами до 0 P1), затем юзеру (см. [[feedback_codex_review_specs]]).

---

## 6. Деплой

- `server.js` + `migrations/` + `publisher_base.py` → прод autowarm через git post-commit
  hook ([[reference_autowarm_git_hook]]) + PM2 restart `autowarm`.
- Миграция: применить `ALTER TABLE publish_queue ADD COLUMN ...` ДО рестарта кода-консьюмера
  (backfill default 0 безопасен).
- C3: правка `postgresql.conf` + `sudo systemctl reload postgresql`.
- Все компоненты дарк-/лайт-launch за env в `ecosystem.production.config.js`; конвенция —
  SQL/env kill-switches, не systemd ([[feedback_deploy_scope_constraints]]).

---

## 7. Риски

| Риск | Митигация |
|---|---|
| Breaker остановит публикацию, которая бы дожала | Порог 3 (не 1); публикация уходит в WP#108-движок/ручную, не теряется; kill-switch. |
| Сброс streak не отрабатывает → ложные срабатывания | Покрыть тестом success→reset; при сомнении поднять порог через env. |
| Алерт-спам в шторм | Cooldown-дедуп (default 60 мин). |
| Реальная первопричина (lock?) не устранена | Осознанно: WP даёт защиту от класса + диагностику (C3/C2) для локализации рецидива. |
| Миграция на горячей таблице | `ADD COLUMN ... DEFAULT 0` — метаданные-only в PG16, без переписи таблицы. |

---

## 8. Остаточная неопределённость и follow-up

- Точный триггер блокировки DB-write 21:00–03:00 МСК **не локализован**. Если C2/C3 при
  рецидиве укажут на конкретный лок/процесс — завести дочернюю WP на устранение первопричины.
- Разрыв «лог запусков терялся в окне» (console.log не доходил, а DB-write проходил) —
  отдельная аномалия наблюдаемости; зафиксировать наблюдение, при повторении — отдельный триаж.
- Связь с **#135** (IG foreground-гарды): инцидент блокировал чистую проверку #135; после
  стабилизации — перепроверить #135 под нормальной нагрузкой.
