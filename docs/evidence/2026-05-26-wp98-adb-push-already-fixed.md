# WP #98 — adb_push timeout на больших медиа уже исправлен (resolved-by-prior-PR)

**Дата:** 2026-05-26
**Контекст:** авто-исполнитель прислал бриф `contenthunter_autoexec/briefs/98/brief.md` с вопросом — переоткрыть #98 как расследование «почему всё ещё падает» или реимплементировать chunked-push? Перед любым действием — свёрка брифа с прод-кодом и данными.
**Метод:** чтение прод-кода свитчера/паблишера (`/root/.openclaw/workspace-genri/autowarm`, ветка main), git-log коммитов фикса, разбор `publish_tasks.events` по `meta.step`/`meta.timeout_s`/`meta.size_mb`, привязка фейлов ко времени деплоя. DB `openclaw@localhost`.

---

## TL;DR

- Исходная посылка #98 («реализовать chunked-push для медиа >70MB») **устарела**: chunked-push (PR #48, `ec91909`) + size-aware watchdog (PR #53, `055161d`) **задеплоены 2026-05-13 и корректно работают**.
- Триггер chunked — **>3MB** (`CHUNKED_TRIGGER_MB=3.0`), не >70MB. Формулировка задачи неточна.
- 17 фейлов Bucket 6 из триажа WP #79 — это задачи **утра 2026-05-13 (05:27–06:13), ДО деплоя size-aware watchdog (20:45 того же дня)**. У них watchdog статический 180с при медиа 55–78MB. Триаж 18.05 захватил окно, перекрывающее фикс, и не учёл это.
- **После деплоя (2026-05-13 21:00) — НОЛЬ фейлов `adb push медиафайла` по всем проектам за 13 дней.** Проблема закрыта.
- Остаточные `switch_failed_unspecified` у Content hunter post-deploy = `adb preflight` (30с) **только 15.05 (OTA-инцидент, отдельный RC, уже в памяти)** + хвост 1–2/день 19–20.05, ноль с 20.05. Это preflight/сеть, не adb_push, и вне scope #98.
- Пункт «телеметрия loss-rate по hop'ам» оставлен на инфра-треке (тикет TimeWeb с mtr/RetransSegs) — внутри publisher дублировал бы инфра-мониторинг.

**Решение:** код не пишем, не реимплементируем. WP #98 → «Готово» (resolved-by-prior-PR #48/#53).

---

## Evidence

### 1. chunked-push + size-aware watchdog реализованы и подключены (прод-код)

- `publisher_kernel.py:61–96` — константы chunked (chunk 1MB, `CHUNKED_TRIGGER_MB=3.0`, per-chunk timeout 30с, 5 retry) + `compute_push_timeout(size_mb) = max(180, 60 + 4×size_mb)`.
- `publisher_base.py:4321–4327` — media-фаза считает реальный `size_mb` файла, `push_timeout_s = compute_push_timeout(size_mb)`, и **передаёт его явно** в `set_step('adb push медиафайла', timeout_s=push_timeout_s)`.
- `publisher_base.py:537–566` (`set_step`) — если `timeout_s` передан, watchdog вооружается им; иначе fallback на `STEP_TIMEOUTS` (где `'adb push': 180`). То есть в текущем коде size-aware timeout подключён корректно.

Калибровка (комментарий `publisher_kernel.py:73–86`): 10MB→180с (floor), 50MB→260с, 78MB→372с, 200MB→860с. Smoke до 200MB (`.ai-factory/smoke/smoke_adb_push_200mb.py`).

### 2. Время деплоя фикса vs время фейлов

| Коммит | Время (2026-05-13) | Содержание |
|---|---|---|
| `ec91909` (PR #48) | 11:39:45 | watchdog ping regression + per-chunk ping |
| `055161d` (PR #53) | **20:45:10** | **size-aware watchdog + 200MB** |

Фейлящие задачи Bucket 6 (примеры): 5165 (TikTok), 5170/5174/5176 (YouTube), 5177/5178 (Instagram) — `created_at` **2026-05-13 05:27–06:13**, т.е. за ~15 часов ДО деплоя size-aware watchdog.

Таймлайн задачи 5165 (медиа **57.52 MB**):
```
start → info(sz=57.52)
→ watchdog_fired   [adb push медиафайла] t=180.0
→ watchdog_relaunch[adb push медиафайла] t=180.0
→ relaunch_failed  [adb push медиафайла] t=180.0
```
Для 57.52MB корректный timeout = `max(180, 60+4×57.52)=290с`. Сработавшие 180с = старый статический код (до PR #53). После деплоя такой задачи нет ни одной.

### 3. watchdog_fired у Content hunter `switch_failed_unspecified` — два разных класса

| step | timeout_s | n | класс |
|---|---|--:|---|
| adb push медиафайла | 180.0 | 33 | **только pre-deploy** (утро 13.05) |
| adb preflight | 30.0 | 40 | preflight/сеть — **только 15.05 (OTA)** + хвост |

### 4. После деплоя (2026-05-13 21:00): adb-push watchdog — ноль

```
ALL projects, 'adb push медиафайла' watchdog_fired, created_at > 2026-05-13 21:00:
→ 0 строк (за 13 дней)
```

Остаток `switch_failed_unspecified` у Content hunter post-deploy по дням:
| Дата | n | что это |
|---|--:|---|
| 2026-05-15 | 40 (16 IG + 12 TT + 12 YT) | OTA-инцидент, `adb preflight` 30с |
| 2026-05-19 | 4 | хвост preflight |
| 2026-05-20 | 3 | хвост preflight |
| 2026-05-21 … 26 | **0** | — |

Content hunter активен (не «ноль фейлов из-за нуля активности»): post-deploy 109 done / 114 failed / 56 published_no_url / 5 awaiting_url / 2 pending.

---

## SQL для воспроизведения

```sql
-- §2/§3 watchdog step+timeout по фейлам Content hunter
SELECT ev#>>'{meta,step}' step, ev#>>'{meta,timeout_s}' t, count(*) n
FROM publish_tasks pt, jsonb_array_elements(pt.events) ev
WHERE pt.project ILIKE 'Content hunter_%' AND pt.error_code='switch_failed_unspecified'
  AND pt.created_at > now() - interval '20 days' AND ev->>'type'='watchdog_fired'
GROUP BY 1,2 ORDER BY n DESC;

-- §4 adb-push watchdog ПОСЛЕ деплоя size-aware (по всем проектам)
SELECT (pt.created_at)::date d, count(DISTINCT pt.id) tasks
FROM publish_tasks pt, jsonb_array_elements(pt.events) ev
WHERE pt.created_at > '2026-05-13 21:00'
  AND ev->>'type'='watchdog_fired' AND ev#>>'{meta,step}'='adb push медиафайла'
GROUP BY 1 ORDER BY 1 DESC;   -- → 0 строк

-- §4 остаток switch_failed_unspecified Content hunter по дням
SELECT created_at::date d, platform, count(*) n
FROM publish_tasks
WHERE project ILIKE 'Content hunter_%' AND error_code='switch_failed_unspecified'
  AND created_at > '2026-05-13 21:00'
GROUP BY 1,2 ORDER BY 1 DESC, 3 DESC;
```

---

## Out of scope (зафиксировано)

- **Реимплементация chunked-push** — отклонена: дублировала бы рабочий код (PR #48/#53).
- **Per-hop loss telemetry внутри publisher** — оставлено на инфра-треке (тикет TimeWeb, mtr hop 4 = 20% loss). См. память `project_adb_push_network_issue`.
- **Остаток adb_preflight / OTA 15.05** — отдельная первопричина (OTA-экран блокирует preflight), не adb_push; покрыта памятью `feedback_ota_screen_blocks_adb_preflight`.
