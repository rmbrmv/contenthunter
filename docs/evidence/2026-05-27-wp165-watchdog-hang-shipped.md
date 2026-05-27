# WP #165 — Evidence: SHIPPED + DEPLOYED 2026-05-27

## Что было не так
Ночь 21:00–02:59 МСК (26→27.05): массовый `watchdog_subprocess_hang` на всех платформах (551),
обвал IG-успеха до 11%, резкое восстановление в 03:00 МСК.

## Разведка (итог)
- 551 hang = **28 уникальных публикаций** (ретрай-шторм: watchdog kill → pq→pending → редиспатч
  каждые 5 мин, без cap по cpid).
- Сигнатура: 0 событий, heartbeat ни разу, kill до начала работы (0 внутренних `watchdog_fired`).
- **Доказательно исключено:** перегрузка хоста (sar: CPU 85–98% idle, RAM 14%, 0 swap, 0 blocked),
  исчерпание коннектов (PG-лог пуст, 0 FATAL), ADB-мост (heartbeat=localhost), конкурирующие
  scheduler'ы (6 «зомби» = systemd-сервисы других проектов, обработано в WP#133).
- Вероятная причина: блокировка пути записи в localhost-Postgres в окне; точный триггер не
  локализован (система была слепа — закрыто компонентом C).

## Что сделано (SHIPPED)
Прод autowarm merge **ccdf4b4** (ветка `wp165-watchdog-hang` → main), reload PM2 `autowarm` (id 35).

**A. Circuit-breaker** (`watchdog_breaker.js` + `server.js` watchdog): после ≥3 `watchdog_subprocess_hang`
по одному cpid в окне 60 мин — backoff-реквью (`scheduled_at = NOW()+6ч`) вместо немедленного;
выводит публикацию из тугого 5-мин цикла, не теряя её. Kill-switch `WATCHDOG_BREAKER_ENABLED`.

**B. TG-алерт** (`watchdog_alert.js`, fire-and-forget из watchdog-тика): при ≥20 hang за 30 мин —
алерт в TG (плумбинг daily-report), cooldown-дедуп 60 мин, time-bounded in-flight guard, fetch-timeout.
Kill-switch `WATCHDOG_ALERT_ENABLED`.

**C. Диагностика** (kill-switch `WATCHDOG_DIAG_ENABLED`): `last_step` в meta kill-события (парс из `log`);
видимый heartbeat-сбой (`publisher_base.py` → stderr `[heartbeat_fail task=N]` + файл `/tmp/autowarm_heartbeat_fail/N.log`);
`log_lock_waits=on` в Postgres (ops-шаг, см. «Что осталось»).

Вне scope (обосновано): ADB-preflight (мост был здоров), чистка «зомби» (это WP#133).

## Верификация
- Тесты: `watchdog_breaker` 6/6, `watchdog_alert` 4/4 (baseline-aware, серийно), `heartbeat_visibility` 2/2.
  Пост-merge гейт в прод-чекауте: 10 node + 2 python — все зелёные.
- `codex review` спеки, плана и полного диффа реализации — **0 P1** (3 реальных P2 в alert-пути
  пойманы и исправлены: cooldown-init, unbounded fetch, дубль на перекрытии тиков).
- Пост-деплой: `autowarm` online, unstable restarts = 0, exec cwd корректный, все `WATCHDOG_*`
  env применены, ошибок загрузки модулей нет.

## Что осталось
- **C3 (вручную, нужен postgres-superuser):** `ALTER SYSTEM SET log_lock_waits = on;` + reload —
  включить до ближайшей ночи, чтобы при рецидиве видеть lock-wait.
- Наблюдение: при следующем ночном окне проверить `[watchdog] ... [backoff]` и алерт; при рецидиве
  C2/C3 локализуют точный триггер → дочерняя WP на первопричину.
- Развязка с **#135** (перепроверить IG foreground-гарды под нормальной нагрузкой).
