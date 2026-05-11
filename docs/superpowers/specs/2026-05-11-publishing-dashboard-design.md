# Publishing Dashboard — Design v1

**Date:** 2026-05-11  
**Topic:** Новый подраздел «📊 Дашборд» в модуле «📤 Выкладка» — сводные метрики по `publish_queue`.

> **Статус:** draft в брейнсторме (codex review round 1). User уже подтвердил:
> - 5 корзин статусов
> - `scheduled_at` как дата-поле
> - Календарные периоды в Europe/Moscow
> - Stack layout (Все + 3 платформенных блока)
> - Sidebar position: первой кнопкой

## 1. Цель и contextual fit

В модуле `Выкладка` сейчас 4 подраздела: Запланировано / Опубликовано / Расход токенов / План выкладки. Все они — операционные: «что в очереди», «что уже сделано». Нет агрегированного **read-only** обзора: «сколько в каких статусах за этот период, и какая success rate».

Цель — дашборд, который оператор открывает первым и за 3 секунды видит:
- сколько задач планировалось за выбранный период
- сколько из них доехало до `done`
- сколько в работе / ошибках / отменено
- разбивка по платформам (IG/TT/YT)

## 2. Source of truth

**Источник:** `publish_queue` (single table).

**Почему не `publish_tasks`:**
- На одну `publish_queue.id` может прийтись N `publish_tasks` из-за re-queue (`UPDATE publish_queue SET status='pending', publish_task_id=NULL`). Считать конверсию по tasks искажает: один пользовательский «слот» в плане = одна корзина, а не сумма попыток.
- Семантика «задача на публикацию», которую назвал пользователь, биективна именно `publish_queue`.

**Statuses observed in `publish_queue` (data, последние 7д):**  
`pending`, `running`, `done`, `failed`, `cancelled`, `skipped`, `past_slot_dropped`.

**Bucket mapping (утверждено user):**
| Bucket | Statuses |
|---|---|
| Ожидание | `pending` |
| Выполняются | `running` |
| Готово | `done` |
| Ошибки | `failed`, `past_slot_dropped` |
| Отменено/Пропущено | `cancelled`, `skipped` |

**Success rate:** `done / (done + failed + past_slot_dropped)`. `cancelled`/`skipped` исключаются — это решения системы ДО публикации (past-slot, config-missing), не результат выкладки. `pending`/`running` тоже не входят в знаменатель: они in-flight.

## 3. Backend

### 3.1 Endpoint

`GET /api/publish-queue/dashboard`

**Query params:**
| Param | Type | Required | Default |
|---|---|---|---|
| `preset` | `today` \| `week` \| `month` \| `custom` | no | `today` |
| `from` | ISO 8601 date (`YYYY-MM-DD`) | only if `preset=custom` | — |
| `to` | ISO 8601 date (`YYYY-MM-DD`) | only if `preset=custom` | — |

`preset=today/week/month` рассчитывается **на сервере** в `Europe/Moscow`:
- `today` → `[today 00:00 MSK, tomorrow 00:00 MSK)`
- `week` → `[понедельник 00:00 MSK, следующий понедельник 00:00 MSK)`
- `month` → `[1-е число текущего месяца 00:00 MSK, 1-е число следующего месяца 00:00 MSK)`
- `custom` → `[from 00:00 MSK, (to + 1 day) 00:00 MSK)` (полуоткрытый, inclusive-from/exclusive-to)

Validation: для `custom` `from` и `to` обязательны, `from <= to`, обе даты ≤ today + 60 дней (защита от шальных значений).

### 3.2 SQL

Один проход по `publish_queue` через `GROUPING SETS` (платформы + итого), фильтр по `scheduled_at`:

```sql
SELECT
  COALESCE(platform, 'all')                                            AS bucket,
  COUNT(*)                                                              AS total,
  COUNT(*) FILTER (WHERE status = 'pending')                            AS pending,
  COUNT(*) FILTER (WHERE status = 'running')                            AS running,
  COUNT(*) FILTER (WHERE status = 'done')                               AS done,
  COUNT(*) FILTER (WHERE status IN ('failed','past_slot_dropped'))      AS errors,
  COUNT(*) FILTER (WHERE status IN ('cancelled','skipped'))             AS cancelled_skipped
FROM publish_queue
WHERE scheduled_at >= $1 AND scheduled_at < $2
GROUP BY GROUPING SETS ((platform), ());
```

`GROUPING SETS ((platform), ())` даёт:
- N строк с группировкой по платформе
- 1 строку с `platform IS NULL` = общий итог

В Node-маппинге `platform IS NULL` → `bucket='all'`.

### 3.3 Response shape

```json
{
  "range": {
    "preset": "today",
    "from": "2026-05-11T00:00:00+03:00",
    "to": "2026-05-12T00:00:00+03:00",
    "tz": "Europe/Moscow"
  },
  "overall": {
    "total": 120,
    "pending": 8,
    "running": 2,
    "done": 95,
    "errors": 12,
    "cancelled_skipped": 3,
    "success_rate": 0.888
  },
  "by_platform": {
    "instagram": { "total": 40, "pending": 3, "running": 1, "done": 32, "errors": 4, "cancelled_skipped": 0, "success_rate": 0.889 },
    "tiktok":    { "total": 45, "pending": 3, "running": 1, "done": 38, "errors": 2, "cancelled_skipped": 1, "success_rate": 0.950 },
    "youtube":   { "total": 35, "pending": 2, "running": 0, "done": 25, "errors": 6, "cancelled_skipped": 2, "success_rate": 0.806 }
  }
}
```

`success_rate`:
- Если `done + errors == 0` → `null` (UI рисует `—` вместо `0%`, чтобы пустой период не выглядел как 100% failure rate).
- Иначе float ∈ [0,1] до 3 знаков.

`by_platform` всегда содержит ключи `instagram`, `tiktok`, `youtube` (даже если 0 задач — выводим нулевую запись, чтобы фронт не плясал из-за отсутствующих ключей). VK/FB/X out of scope (см. memory `project_autowarm_scope`).

### 3.4 Edge cases

- **Незнакомая платформа в БД** (например `vk`): аггрегируется в `overall`, но в `by_platform` НЕ попадает (мы рисуем только IG/TT/YT). Будет видна как «дельта» между overall.total и сумма платформ — в первой версии не визуализируем, в backlog можно добавить блок «Прочее».
- **`platform IS NULL`** в записи: попадает в overall, но не в by_platform — то же поведение.
- **Пустой диапазон**: все нули, `success_rate: null`.
- **`scheduled_at IS NULL`**: исключаются фильтром `scheduled_at >= $1` (NULL не сравнивается).

## 4. Frontend

### 4.1 Sidebar

```html
<nav id="sidebar-publishing">
  <button id="nav-publishing-dashboard" onclick="nav('publishing-dashboard')">📊 Дашборд</button>  <!-- NEW first -->
  <button id="nav-publishing"           onclick="nav('publishing'); upSwitchTab('queue');">📋 Запланировано</button>
  <button id="nav-publishing-results"   onclick="nav('publishing'); upSwitchTab('tasks');">✅ Опубликовано</button>
  <button id="nav-publishing-tokens"    onclick="nav('publishing-tokens')">🪙 Расход токенов</button>
  <button id="nav-validator-plan"       onclick="nav('validator-plan')">📅 План выкладки</button>
</nav>
```

`defaultSections.publishing` меняется с `'publishing'` (Запланировано) на `'publishing-dashboard'` (новый дашборд) — это первая вкладка при клике на module-tab `📤 Выкладка`.

`sidebarMap` дополняется: `'publishing-dashboard': 'publishing'`.

### 4.2 Section layout

```
┌──────────────────────────────────────────────────────────────────┐
│ 📊 Дашборд выкладки                                              │
│                                                                  │
│ [Сегодня] [Неделя] [Месяц] [Custom: from → to]   [🔄 Обновить]   │
├──────────────────────────────────────────────────────────────────┤
│ ВСЕ ЗАДАЧИ                                                       │
│                                                                  │
│   Всего  Ожидание  Выполняются  Готово  Ошибки  Отменено  Rate   │
│   120       8           2          95      12       3      89%   │
├──────────────────────────────────────────────────────────────────┤
│ 📷 Instagram   40   3   1   32   4   0   88%                     │
│ 🎵 TikTok       45   3   1   38   2   1   90%                     │
│ ▶️ YouTube       35   2   0   25   6   2   78%                     │
└──────────────────────────────────────────────────────────────────┘
```

**HTML structure:**
- `<div id="section-publishing-dashboard" class="section">`
- Шапка: title + date-presets-toolbar + custom-range-picker (hidden until `Custom` clicked) + refresh button
- KPI-блок «ВСЕ ЗАДАЧИ»: 7 tile-карточек в одну строку (как уже стилизовано в существующих stat-tiles, lines 2260-2285)
- 3 platform-блока: иконка + название платформы + те же 7 чисел в строку

**Date presets state:** preset выделяется визуально (bg-indigo-50/text-indigo-700, как nav-item active). Single-select. Кликая `Custom` — раскрывается input from/to + кнопка «Применить». При клике на любой пресет — custom-range collapses.

**No auto-refresh:** Manual refresh button. Консистентно с queue/tasks, данные не realtime-critical. Auto-refresh в backlog.

### 4.3 JS API call

```js
async function loadPublishingDashboard() {
  const preset = _dashCurrentPreset; // 'today' | 'week' | 'month' | 'custom'
  const params = new URLSearchParams({ preset });
  if (preset === 'custom') {
    params.set('from', _dashCustomFrom);
    params.set('to', _dashCustomTo);
  }
  const r = await fetch(`/api/publish-queue/dashboard?${params}`);
  const data = await r.json();
  renderDashboardOverall(data.overall);
  renderDashboardPlatforms(data.by_platform);
  renderDashboardRange(data.range);
}
```

Loading state: skeleton placeholder в каждой ячейке (текст `—`). Error state: красная плашка в шапке + сохранение последних успешных значений.

### 4.4 URL state

Use existing `setSubParam('dash:' + preset)` pattern, как в `upSwitchTab`. Custom range также сериализуется: `dash:custom:2026-05-01:2026-05-11`. Restore при page load.

## 5. Error handling и observability

- 4xx на invalid params (`from > to`, range > 60 days): JSON `{error: "..."}`, фронт показывает красную плашку.
- 5xx на SQL fail: фронт оставляет предыдущие данные, показывает «Ошибка обновления — попробуй ещё раз».
- Server-side logging: `console.log('[pub-dash]', ...)` в `server.js`, как в остальных endpoints.
- No new DB indexes: `publish_queue` ~1k записей в активном окне, full scan + filter < 50ms (verified для соседних endpoints в memory `paginated_tables_pilot`).

## 6. Testing

**Backend:** unit-тесты для:
- Bucket mapping (правильные статусы попадают в правильные ведра).
- Period calculation (preset → range): edges «полночь начала недели/месяца», DST не релевантен для Europe/Moscow (МСК всегда +3).
- `success_rate = null` когда `done + errors == 0`.
- `GROUPING SETS` — overall.total == sum(platform.total) для известных платформ + неизвестные.
- Custom range validation: `from > to`, `range > 60d` → 400.

**Frontend:** smoke только — нет JS unit-test setup в проекте.

**Manual verification после деплоя:**
- Открыть `https://delivery.contenthunter.ru/#publishing/publishing-dashboard`
- Проверить today: цифры совпадают с SQL `SELECT status, COUNT(*) FROM publish_queue WHERE scheduled_at >= today_msk AND scheduled_at < tomorrow_msk GROUP BY status`
- Проверить custom range, неделя, месяц
- Проверить разбивку по платформам — sum по платформам ≤ overall.total

## 7. Scope / YAGNI

**In scope:**
- 1 endpoint, 1 SQL, 1 frontend section.
- 5 buckets + success rate.
- 4 пресета периода + custom range.
- Stack layout: All + IG/TT/YT.

**Out of scope (backlog):**
- Фильтр по проекту/аккаунту (можно добавить позже dropdown'ами).
- Графики тренда (line/bar по дням).
- Сравнение с предыдущим периодом.
- Block «Прочие платформы» (если появятся записи vk/fb/x — заметим, добавим).
- Auto-refresh / live polling.
- Drill-down: клик по цифре «Ошибки» → переход в Запланировано с фильтром status=failed.

## 8. Deploy

Frontend: `index.html` правится напрямую в `/root/.openclaw/workspace-genri/autowarm/public/index.html` (auto-push hook в GenGo2/delivery-contenthunter).

Backend: `server.js` правится там же, потом `pm2 restart autowarm` (или соответствующая PM2-инстанция — проверить `pm2 list` перед рестартом).

No DB migrations. No новые таблицы/индексы. Кросс-репо grep не нужен.
