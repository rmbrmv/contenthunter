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

### 4.1. Компонент A — Circuit-breaker ретрай-шторма (оконный + backoff)

**Где:** `server.js` `watchdogRunningTasks()`, в точке реквью (стр. 7060-7065).

**Идентичность публикации:** `client_publish_id` (cpid) персистентен на `publish_tasks`
между ретраями (в инциденте все 551 hang имели cpid, NULL = 0). Используем оконный запрос
по cpid — **без персистентного счётчика, без миграции, без reset-хука** (само-заживает по
скользящему окну). Это сознательное упрощение vs первоначальный вариант со счётчиком на
`publish_queue` (тот требовал миграцию + хук сброса на успехе — лишний риск).

**Логика (после того как watchdog уже пометил задачу `failed` с error_code):**
1. Если `cpid IS NULL` → обычное немедленное реквью (`pq → pending`), breaker неприменим
   (безопасный дефолт).
2. Иначе посчитать:
   `SELECT count(*) FROM publish_tasks WHERE client_publish_id = $cpid
    AND error_code='watchdog_subprocess_hang'
    AND updated_at > NOW() - (WATCHDOG_BREAKER_WINDOW_MIN || ' minutes')::interval`
   (включает текущую только что упавшую задачу).
3. Если `count < WATCHDOG_BREAKER_MAX_HANGS` (default 3): реквью как сейчас —
   `pq → pending`, `publish_task_id=NULL`, `scheduled_at` не трогаем (немедленный ретрай).
4. Если `count >= WATCHDOG_BREAKER_MAX_HANGS`: **backoff-реквью** —
   `pq → pending`, `publish_task_id=NULL`,
   `scheduled_at = NOW() + (WATCHDOG_BREAKER_BACKOFF_HOURS || ' hours')::interval` (default 6).
   `dispatchPublishQueue` берёт только `scheduled_at <= NOW()+10min`, поэтому публикация
   **выходит из тугого 5-мин цикла**, но **не теряется** — повторится после cooldown (когда
   ночное окно уже закончится). Записать событие + засчитать в алерт (компонент B).

**Эффект:** вместо ~20 немедленных ретраев за ночь — максимум 3 в окне, затем откат на 6ч.
28 публикаций → десятки hang вместо 551; ночь устройств не сжигается. Если триггер устойчив,
после cooldown будет максимум +1 hang/6ч на публикацию (это и есть желаемый backoff).

**Kill-switch:** `WATCHDOG_BREAKER_ENABLED` (default `'true'`). При `'false'` — старое
безусловное немедленное реквью. Параметры: `WATCHDOG_BREAKER_MAX_HANGS` (default 3),
`WATCHDOG_BREAKER_WINDOW_MIN` (default 60), `WATCHDOG_BREAKER_BACKOFF_HOURS` (default 6).

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

- **Live-DB тест (node):** `test_watchdog_breaker.test.js` (стиль `test_retry_controller.test.js`
  — реальный `Pool`, высокие fixture-id, cleanup). Сидим N−1 прошлых hang по cpid →
  немедленное реквью (`scheduled_at` ≈ now); сидим N hang → backoff-реквью (`scheduled_at` ≈
  now+6ч). Путь NULL-cpid → обычное реквью.
- **Live-DB тест:** алерт — порог (N−1 нет отправки, N есть), дедуп-cooldown, формат текста
  (мок `fetch`).
- **Юнит:** парсинг `last_step` из `log` (есть строка `💓` / пустой log → null).
- **Python smoke:** heartbeat-сбой пишет в stderr + файл-fallback (мок `psycopg2.connect`
  кидает исключение).
- `codex review` спеки и плана (раундами до 0 P1), затем юзеру (правило feedback_codex_review_specs).

---

## 6. Деплой

- `server.js` + `publisher_base.py` → прод autowarm через git post-commit hook
  (reference_autowarm_git_hook) + PM2 restart `autowarm`. **Схема БД не меняется** (компонент A
  — оконный запрос, миграции нет).
- C3: правка `postgresql.conf` + `sudo systemctl reload postgresql`.
- Все компоненты дарк-/лайт-launch за env в `ecosystem.production.config.js`; конвенция —
  env/SQL kill-switches, не systemd (feedback_deploy_scope_constraints).

---

## 7. Риски

| Риск | Митигация |
|---|---|
| Breaker задержит публикацию, которая бы дожала | Порог 3 в окне (не 1); это backoff, а не отмена — публикация **не теряется**, повторится после cooldown; kill-switch. |
| Backoff лишь сдвигает шторм на 6ч | Желаемое поведение: max +1 hang/6ч вместо ~20/ночь; ночное окно к моменту повтора закрыто; алерт уведомит. |
| Публикации без cpid не покрыты breaker'ом | Безопасный дефолт (обычное реквью); в инциденте NULL-cpid = 0; редкий кейс. |
| Алерт-спам в шторм | Cooldown-дедуп (default 60 мин, in-memory). |
| Реальная первопричина (lock?) не устранена | Осознанно: WP даёт защиту от класса + диагностику (C3/C2) для локализации рецидива. |

---

## 8. Остаточная неопределённость и follow-up

- Точный триггер блокировки DB-write 21:00–03:00 МСК **не локализован**. Если C2/C3 при
  рецидиве укажут на конкретный лок/процесс — завести дочернюю WP на устранение первопричины.
- Разрыв «лог запусков терялся в окне» (console.log не доходил, а DB-write проходил) —
  отдельная аномалия наблюдаемости; зафиксировать наблюдение, при повторении — отдельный триаж.
- Связь с **#135** (IG foreground-гарды): инцидент блокировал чистую проверку #135; после
  стабилизации — перепроверить #135 под нормальной нагрузкой.
