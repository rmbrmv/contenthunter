# T1 — SQL-свод farming-задач за 30 дней

**Source:** `autowarm_tasks` (postgres `openclaw@localhost:5432`)
**Date:** 2026-04-19
**Window:** `COALESCE(started_at, updated_at) > NOW() - INTERVAL '30 days'` ⇒ с ~2026-03-20

## 0. Headline — фарминг де-факто остановлен

| Метрика | Значение |
|---|---:|
| Задач за 30 дней | **122** |
| Задач за 14 дней | **1** |
| Задач за 7 дней | **0** |
| Самая свежая задача | **2026-04-06 16:54** |
| Completed за 30 дней | 8 (все Instagram, ни одной за последние 13 дней) |

**Вывод:** Последние ~13 дней фарминг не запускался. Работаем с лог-срезом **2026-03-20 → 2026-04-06** (17 активных дней из 30).

## 1. Распределение по status (30 дней)

```sql
SELECT status, COUNT(*)
FROM autowarm_tasks
WHERE COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
GROUP BY status ORDER BY COUNT(*) DESC;
```

| status | count | % от total |
|---|---:|---:|
| failed | 77 | 63.1 % |
| preflight_failed | 22 | 18.0 % |
| offline | 8 | 6.5 % |
| **completed** | **8** | **6.5 %** |
| paused | 7 | 5.7 % |
| pending/running | 0 | 0 % |

**Success rate:** 8/122 = **6.5 %**. С учётом того что 22 вообще не стартовали (preflight) — среди стартовавших 8/100 = **8 %**.

## 2. TOP-30 error-сообщений в `events[].type='error'`

```sql
SELECT ev->>'msg' AS msg, COUNT(*)
FROM autowarm_tasks t, LATERAL jsonb_array_elements(events) ev
WHERE COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
  AND status IN ('failed','preflight_failed')
  AND ev->>'type' = 'error'
GROUP BY msg ORDER BY COUNT(*) DESC LIMIT 30;
```

**Кластеризация:**

| Кластер | Примеры msg | Count | % |
|---|---|---:|---:|
| **Account read fail (3 попытки)** | `Не удалось прочитать аккаунт TikTok/YouTube/Instagram после 3 попыток — задача прервана` | 32+25+20 = **77** | ≈ 43 % от всех error-событий |
| **Account mismatch** | `Аккаунт @X не совпадает с активным — задача прервана` (61 различных аккаунтов!) | ≈ 60 | ≈ 34 % |
| **Watchdog hang** | `Watchdog: зависание {120, 121, 187, 213, 1154} мин — принудительно failed` | 19 | ≈ 11 % |
| Прочее | — | ≈ 22 | ≈ 12 % |

**Диагноз уровня 1:** ~77 % всех error-событий сосредоточены в upstream-этапе *переключение/проверка аккаунта перед фармингом* (read + match). Fitness-действия (лайки/просмотры) до них часто не доходят.

## 3. `events[].meta.category` × platform

```sql
SELECT ev->'meta'->>'category' AS category, platform, COUNT(*)
FROM autowarm_tasks t, LATERAL jsonb_array_elements(events) ev
WHERE COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
  AND status IN ('failed','preflight_failed')
  AND ev->>'type' = 'error'
GROUP BY category, platform ORDER BY COUNT(*) DESC;
```

| category | platform | count |
|---|---|---:|
| **NULL** | TikTok | 70 |
| **NULL** | YouTube | 60 |
| **NULL** | Instagram | 48 |

**Структурная находка:** в отличие от `publish_tasks` (`meta.category` используется для триажа), **farming-события НЕ заполняют `meta.category`**. Вся классификация опирается на matching по `msg`-строке. Это усложняет мониторинг и построение алертов/метрик.

**→ Candidate rule для будущих задач:** при трогании warming-кода добавлять `meta.category` в `log_event(...)` по тому же паттерну, что в `publisher.py` (категории типа `wa_account_read_failed_3x`, `wa_account_mismatch`, `wa_watchdog_hang`).

## 4. Device × platform failure rate (≥ 2 задачи)

```sql
SELECT device_serial, platform, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE status='failed') AS failed,
       COUNT(*) FILTER (WHERE status='completed') AS done
FROM autowarm_tasks
WHERE COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
GROUP BY device_serial, platform
HAVING COUNT(*) >= 2 ORDER BY failed DESC;
```

| device | platform | total | failed | done |
|---|---|---:|---:|---:|
| RFGYB07Y5TJ | TikTok | 3 | **3** | 0 |
| RFGYA19BPJL | TikTok | 2 | 2 | 0 |
| RFGYB07Y65V | TikTok | 2 | 2 | 0 |
| RF8YA0V57MV | YouTube | 2 | 2 | 0 |
| RF8Y90PCSJF | Instagram | 2 | 2 | 0 |
| RFGYA19DB8K | YouTube | 2 | 2 | 0 |
| RF8Y80ZT5JB | Instagram | 2 | 2 | 0 |
| RFGYA19BGWT | YouTube | 2 | 2 | 0 |
| RFGYA19DBAX | YouTube | 2 | 2 | 0 |
| RFGYA19BEBK | Instagram | 2 | 0 | **2** |
| RFGYB07Y5TJ | Instagram | 2 | 0 | **2** |

**Аномалия:** `RFGYB07Y5TJ` — 2/2 ✓ на IG, 3/3 ✗ на TikTok. Показатель того что проблема устройство-специфичная только частично, платформа-специфичная доля больше.

**→ Candidate rule:** auto-pause для пары (device, platform), если 3+ подряд fails за 7 дней, до ручной разблокировки.

## 5. Протокол × день × status

```sql
SELECT protocol_id, current_day, status, COUNT(*)
FROM autowarm_tasks
WHERE COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
GROUP BY protocol_id, current_day, status
ORDER BY protocol_id, current_day;
```

Summary:

| protocol_id | Fails day 1 | Fails day 2 | … | Day 10 | Total done |
|---:|---:|---:|---|---:|---:|
| 1 | 8 | 7 | … | **8 completed** | **8** |
| 2 | 15 | 8 | … | 0 | 0 |
| 3 | 16 | 8 | … | 0 | 0 |

**Наблюдение:**
- **Все 8 completions — protocol_id=1, day=10** (т.е. завершение).
- **Protocols 2 и 3 не дошли ни до одного завершения**, умирают на day 1-4.
- Failure cliff на day 1: protocol_id=2 — 15 failed, protocol_id=3 — 16 failed. Это не постепенный drop-off, это «с порога не заходит».

**→ Гипотеза:** protocols 2 и 3 содержат какой-то шаг, несовместимый с текущим UI-состоянием IG/TT/YT (возможно, устаревший happy-path до IG-редизайна). Надо сверить с датой создания protocols.

## 6. Preflight errors (22 случая)

```sql
SELECT pe, COUNT(*)
FROM autowarm_tasks t, LATERAL jsonb_array_elements_text(preflight_errors) pe
WHERE status='preflight_failed'
  AND COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
GROUP BY pe ORDER BY COUNT(*) DESC;
```

| preflight_error | count |
|---|---:|
| Устройство X недоступно по ADB — проверь подключение | 18 (81 %) |
| Ключевые слова не найдены для проекта «Волшебная футболка» — заполни в Распаковке (validator) | 4 (19 %) |

**Диагноз:** 81 % preflight-фейлов — физическая/ADB-связность устройств (9 уникальных устройств). 19 % — config-issue на стороне validator/DB, **без** участия пайплайна.

## 7. Distinct dimensions

```sql
SELECT
  COUNT(DISTINCT account) FILTER (WHERE status='failed') AS distinct_failed_accounts,
  COUNT(DISTINCT account) FILTER (WHERE status='completed') AS distinct_done_accounts,
  COUNT(DISTINCT device_serial) FILTER (WHERE status='failed') AS distinct_failed_devices,
  COUNT(DISTINCT pack_name) FILTER (WHERE status='failed') AS distinct_failed_packs
FROM autowarm_tasks
WHERE COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days';
```

| Метрика | Value |
|---|---:|
| distinct failed accounts | **61** |
| distinct done accounts | 7 |
| distinct failed devices | 41 |
| distinct failed packs | 43 |

77 fails распределены по 61 уникальному аккаунту (≈1.3 fail/account) — т.е. проблема **широкая**, не «один-два аккаунта зациклились».

## 8. Weekly trend

```sql
SELECT date_trunc('week', COALESCE(started_at,updated_at))::date AS week,
       COUNT(*) FILTER (WHERE status='completed') AS done,
       COUNT(*) FILTER (WHERE status='failed') AS failed,
       COUNT(*) FILTER (WHERE status='preflight_failed') AS preflight_failed
FROM autowarm_tasks
WHERE COALESCE(started_at,updated_at) > NOW() - INTERVAL '30 days'
GROUP BY week ORDER BY week;
```

| week (Mon) | done | failed | preflight_failed |
|---|---:|---:|---:|
| 2026-03-23 | 7 | 72 | 18 |
| 2026-03-30 | 1 | 5 | 3 |
| 2026-04-06 | 0 | 0 | 1 |
| 2026-04-13 | — | — | — |
| 2026-04-20 (текущая) | — | — | — |

**Интерпретация:** Пик активности и fail-rate — неделя 2026-03-23 (первая полная после старта). После 2026-04-06 фарминг вообще не запускался. Это говорит о ручной остановке (скорее всего оператором), а не «вот сейчас плохо».

## Итоговая гипотеза (для T2/T3/T4 deep-dive)

1. **77 % error-событий — account-read/match этап** (до фитнес-действий). Код: предположительно `account_switcher.py` / `account_revision.py` в `/root/.openclaw/workspace-genri/autowarm/`. Deep-dive в T2.
2. **~11 % error-событий — watchdog kill**, таймауты 120, 187, 213 мин, один outlier 1154 мин (~19 часов). Deep-dive в T3.
3. **Protocols 2/3 вовсе не работают** — 0 completions, падают день 1-4. Completed только протокол 1 (8 случаев). Deep-dive в T4.
4. **`meta.category` не заполняется** в farming-события — блокер для monitoring-инфраструктуры. **Candidate for immediate follow-up.**
5. **Фарминг остановлен 2026-04-06** — этот план и будет базой для restart plan.
