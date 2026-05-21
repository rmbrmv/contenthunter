# Publishing Dashboard — график Success rate в динамике + фильтры — Design

**Date:** 2026-05-21
**WP:** OpenProject #90 (content-hunter, тип «Задача», parent «Аналитика», assignee Данил)
**Topic:** Добавить на дашборд выкладки (`section-publishing-dashboard`) линейный график success rate **в динамике по платформам** + фильтры (проект/платформа/аккаунт/пак) + два новых пресета периода. Все фильтры применяются и к плиткам, и к графику.

> **Базовая фича:** дашборд уже существует — см. [2026-05-11-publishing-dashboard-design.md](2026-05-11-publishing-dashboard-design.md). Это инкремент поверх неё.

## 0. Постановка (из WP #90)

> добавить график Success rate в динамике по платформам (все текущие фильтры должны применяться и к графику). желательно на графике сразу отображать метки данных, чтобы % был виден сразу, а не только при наведении. если получается нечитаемо, то при наведении легенду по каждой платформе.

Решения, утверждённые пользователем в брейнсторме (2026-05-21):
- **Гранулярность:** диапазон ≤ 1 дня → бакеты по часам (Сегодня, Вчера); иначе → по дням.
- **Линии графика:** 3 платформы (Instagram/TikTok/YouTube) **+ «Все»** (общий success rate). 4 датасета.
- **Фильтры:** Проект, Платформа, Аккаунт, Пак — серверные, применяются к плиткам И графику.
- **Пресеты дат:** к существующим Сегодня/Неделя/Месяц/Custom добавить **«Вчера»** и **«Последние 3 дня»** (у кнопки «Последние 3 дня» подсказка `title`: «3 календарных дня включая сегодня»).
- **Backend-архитектура:** один эндпоинт отдаёт и плитки, и серию (см. §3).
- Фильтры в URL в v1 **не** сохраняем (только пресет, как сейчас).

## 1. Источник и метрика (без изменений)

- **Источник:** `publish_queue` (single table). Семантика «слот публикации» биективна `publish_queue` (re-queue не двоит — см. базовую спеку §2).
- **Success rate** = `done / (done + errors)`, где `errors = failed + past_slot_dropped`. `cancelled`/`skipped`/`pending`/`running` в знаменатель не входят. `null`, если `done + errors == 0` (рисуем разрыв линии, не `0%`).
- Переиспользуется существующий хелпер `computeSuccessRate(done, errors)` (server.js:1740) — формула уже совпадает с дневным отчётом.
- Скоуп платформ: IG/TT/YT (VK/Pinterest/Likee/`NULL` входят в `overall.total`, но не рисуются — см. memory `project_autowarm_scope`).

## 2. Бакетирование по времени

Шаг бакета сервер выбирает по длине диапазона `[from, to)`:

| Условие | Шаг (`unit`) | Применяется к пресетам |
|---|---|---|
| `to - from <= 1 day` | `hour` | Сегодня, Вчера |
| иначе | `day` | Последние 3 дня, Неделя, Месяц, Custom |

**TZ:** `scheduled_at` хранится как `timestamp without time zone` в UTC-naive (подтверждено: существующий дашборд сравнивает `scheduled_at` с UTC-инстантами из `calcDashboardRange`). Для MSK-бакетов сдвигаем `scheduled_at + interval '3 hours'` ПЕРЕД `date_trunc` — тот же принцип фиксированного MSK=UTC+3, что в `calcDashboardRange` (MSK без DST).

**Полная ось бакетов:** сервер генерирует полную последовательность бакетов на интервале через `generate_series` (на MSK-сдвинутой рамке), чтобы пустые часы/дни давали `null` (разрыв линии), а не «склейку». Массивы серий выровнены по этой оси по индексу.

## 3. Backend — расширение существующего эндпоинта

Подход **A**: расширяем `GET /api/publish-queue/dashboard` (server.js:1832). Один запрос → плитки и график считаются по одному и тому же диапазону+фильтрам (не разъедутся).

### 3.1 Query-параметры

| Param | Назначение | Источник логики |
|---|---|---|
| `preset` | `today｜yesterday｜last3｜week｜month｜custom` | `calcDashboardRange` (+2 новых ветки) |
| `from`, `to` | `YYYY-MM-DD` для `custom` | как сейчас |
| `project` | имя проекта (точное совпадение) | `buildPublishQueueFilters` |
| `platform` | `instagram｜tiktok｜youtube` | `buildPublishQueueFilters` |
| `account_username` | подстрока (ILIKE) | `buildPublishQueueFilters` |
| `pack_name` | подстрока (ILIKE) | `buildPublishQueueFilters` |

`status` намеренно НЕ принимаем — фильтр по статусу ломает саму метрику success rate.

### 3.2 Новые пресеты в `calcDashboardRange`

- `yesterday` → `[вчера 00:00 MSK, сегодня 00:00 MSK)` (один день → бакеты по часам).
- `last3` → `[(сегодня − 2 дня) 00:00 MSK, завтра 00:00 MSK)` — **3 календарных дня, включая сегодня**.

Реализация — по образцу ветки `today` (сдвиг `dayMsMsk ± N*DAY_MS − MSK_OFFSET_MS`). `MAX_DASHBOARD_RANGE_DAYS=60` и валидация `custom` без изменений.

### 3.3 Фильтры

Новый хелпер `buildDashboardFilters(query)` — подмножество `buildPublishQueueFilters` (server.js:1796) ровно для `project / platform / account_username / pack_name`, теми же SQL-фрагментами:
- `project` → `COALESCE(vp.project, vp2.project) = $?` (требует JOIN на `validator_projects`, как в `PUBLISH_QUEUE_FROM` server.js:1783)
- `platform` → `LOWER(pq.platform) = $?`
- `account_username` → `pq.account_username ILIKE '%..%'`
- `pack_name` → `pq.pack_name ILIKE '%..%'`

Чтобы семантика проекта 1-в-1 совпадала с таблицей «Запланировано», FROM дашборда переводим на `PUBLISH_QUEUE_FROM` (`publish_queue pq` + JOIN `validator_projects vp/vp2` + `unic_results/unic_tasks`). Фильтры приклеиваются к `WHERE pq.scheduled_at >= $1 AND pq.scheduled_at < $2 [AND ...]`.

> Параметризация: range-границы — `$1/$2`, далее фильтры добавляют свои `$3..$n`, затем `unit` для серии — `$n+1`. Использовать единый массив `params`.

### 3.4 SQL №1 — плитки (snapshot)

Текущий запрос (server.js:1845) + `pq`-алиас + `PUBLISH_QUEUE_FROM` + `[фильтры]`. Группировка та же: `GROUP BY GROUPING SETS ((pq.platform), ())`. Маппинг через существующий `mapDashboardRows` (server.js:1766) — без изменений.

### 3.5 SQL №2 — серия (timeseries)

```sql
WITH bucketed AS (
  SELECT
    date_trunc($unit, pq.scheduled_at + interval '3 hours') AS bkt,   -- MSK-wall, naive
    LOWER(pq.platform)                                       AS plat,
    pq.status                                                AS status
  {PUBLISH_QUEUE_FROM}
  WHERE pq.scheduled_at >= $1 AND pq.scheduled_at < $2 [AND <filters>]
)
SELECT
  bkt,
  CASE WHEN GROUPING(plat) = 1 THEN 'all'
       WHEN plat IS NULL       THEN 'unknown'
       ELSE plat END                                          AS platform_key,
  GROUPING(plat)                                              AS is_all,
  COUNT(*) FILTER (WHERE status = 'done')                     AS done,
  COUNT(*) FILTER (WHERE status IN ('failed','past_slot_dropped')) AS errors,
  COUNT(*)                                                    AS total
FROM bucketed
GROUP BY GROUPING SETS ((bkt, plat), (bkt))
ORDER BY bkt;
```

- `$unit` ∈ `{'hour','day'}` — валидируется на сервере перед биндом (whitelist).
- `'unknown'`/прочие платформы в `platform_key` отбрасываются при сборке (как в плитках); входят только в `all` через grand-total строки `is_all=1`.
- Ось бакетов: отдельный `generate_series(date_trunc($unit, from_msk), date_trunc($unit, to_msk - eps), ('1 '||$unit)::interval)`. Сервер раскладывает done/errors по `(bkt, platform_key)` и считает `computeSuccessRate` для каждого бакета каждой линии; отсутствующий бакет/линия → `null`.

### 3.6 Форма ответа

```jsonc
{
  "range": { "preset": "week", "from": "...Z", "to": "...Z", "tz": "Europe/Moscow" },
  "filters": { "project": null, "platform": null, "account_username": null, "pack_name": null },
  "overall":     { "total": ..., "pending": ..., "running": ..., "done": ..., "errors": ..., "cancelled_skipped": ..., "success_rate": 0.88 },
  "by_platform": { "instagram": {…}, "tiktok": {…}, "youtube": {…} },
  "series": {
    "unit": "day",                                  // "hour" | "day"
    "buckets": ["2026-05-19", "2026-05-20", "2026-05-21"],   // hour → "2026-05-21 14:00"
    "all":       [0.91, 0.85, null],
    "instagram": [0.88, 0.80, null],
    "tiktok":    [0.95, 0.90, null],
    "youtube":   [0.80, 0.75, null]
  }
}
```

- `buckets[i]` ↔ `all[i]`/`instagram[i]`/… по индексу. `null` = нет данных (`done+errors==0`) → разрыв линии.
- `overall`/`by_platform` остаются обратносовместимыми (старый фронт не сломается).
- Формат метки бакета: `day` → `YYYY-MM-DD`; `hour` → `YYYY-MM-DD HH:00` (MSK). Фронт сам форматирует для оси.

## 4. Frontend — фильтры и пресеты

В шапке `section-publishing-dashboard`:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 📊 Дашборд выкладки                                                      │
│ [Сегодня][Вчера][Последние 3 дня][Неделя][Месяц][Custom: from→to] [🔄]   │
│ Проект:[▾все]  Платформа:[▾все]  Аккаунт:[____]  Пак:[____]  [Сбросить]  │
├────────────────────────────────────────────────────────────────────────┤
│ KPI-плитки «ВСЕ ЗАДАЧИ» + 3 платформенных блока (как сейчас)             │
├────────────────────────────────────────────────────────────────────────┤
│ ГРАФИК success rate (новый)                                             │
└────────────────────────────────────────────────────────────────────────┘
```

- **Пресеты:** добавить кнопки «Вчера» и «Последние 3 дня» в существующий toolbar. У «Последние 3 дня» — `title="3 календарных дня включая сегодня"`. Single-select, активный подсвечивается (как сейчас). Пресет сериализуется в sub-param: `dash:yesterday`, `dash:last3` (расширяем существующий `setSubParam('dash:'+preset)`).
- **Фильтры:**
  - Проект — `<select>`, наполняется из `/api/publish/queue/projects` (тот же эндпоинт, что у таблицы; option `все` = пусто).
  - Платформа — `<select>` (все/instagram/tiktok/youtube).
  - Аккаунт — `<input type=text>` (подстрока).
  - Пак — `<input type=text>` (подстрока).
  - «Сбросить» — очищает все 4 фильтра.
- Любое изменение пресета/фильтра/Применить (custom) → `loadPublishingDashboard()` (один перезапрос: плитки + график). Текстовые поля — с debounce ~400мс.
- Фильтры **сессионные** (хранятся в JS-переменных), в URL не пишем (v1). URL-persist фильтров — backlog.

## 5. Frontend — график

- Chart.js (уже подключён, CDN, index.html:11; паттерн `new Chart(ctx, …)` — как у фарминга/SLA/токенов).
- `<canvas>` в новой карточке под платформенными блоками, фикс-высота (~300–340px), `responsive:true`, `maintainAspectRatio:false`.
- Тип `line`, 4 датасета: **Все / Instagram / TikTok / YouTube**. Цвета — консистентно с существующей палитрой платформ (IG, TT, YT) + нейтральный для «Все».
- Ось Y: success rate в **процентах** 0–100 (`min:0, max:100`, тики с `%`). Данные приходят как доли [0,1] → умножаем на 100 при подаче в датасет (или форматтер). `spanGaps:false` — `null` рвёт линию.
- Ось X: `buckets` (категориальная). Подписи: day → `DD.MM`; hour → `HH:00`.
- Легенда: сверху, клик прячет/показывает линию (нативно Chart.js) — это и есть «фильтр платформ глазами».
- **Тултип:** `mode:'index', intersect:false` — при наведении на бакет показывает ВСЕ линии разом + для каждой `XX% (done/total)` (знаменатель тащим в `series` или отдельным массивом, чтобы «100% из 1/1» был очевиден). Это и есть «при наведении легенду по каждой платформе» из WP.
- Один Chart-инстанс хранится в переменной; на перезагрузке — `chart.data=…; chart.update()` (не пересоздавать).
- Пустая серия (нет бакетов с данными) → плашка «Нет данных за период» поверх области графика.

## 6. Метки данных и читаемость (ядро WP)

- Плагин **`chartjs-plugin-datalabels`** — добавить CDN-`<script>` после chart.js (index.html ~строка 11).
- ⚠️ **РИСК РЕГРЕССИИ:** плагин при глобальном `Chart.register(ChartDataLabels)` авто-включает метки на ВСЕХ графиках страницы (фарминг/SLA/токены). Поэтому регистрируем **локально только на этом графике** через `plugins: [ChartDataLabels]` в конфиге инстанса, НЕ глобально. (Альтернатива, если глобальная регистрация уже где-то есть: `Chart.defaults.plugins.datalabels.display=false` и включать только у нас — но предпочтителен локальный путь.)
- **Поведение меток (адаптивно, по тексту WP):**
  - По умолчанию метки `%` включены.
  - Если `buckets.length × видимых_линий` превышает порог читаемости (ориентир: > ~24 меток) → метки авто-скрываются, значения доступны в тултипе при наведении. Порог вынести в константу.
  - Чекбокс «Значения на графике» — ручной тумблер, перекрывает авто-логику.
- Метки: формат `NN%`, без десятичных; цвет по линии; `null`-точки метки не рисуют.

## 7. Edge-cases

- **Пустой период:** плитки нули; график — плашка «нет данных».
- **Незнакомая платформа / `platform IS NULL`** (`past_slot_dropped` audit-строки): в `overall`/`all`, не в линиях платформ (как в плитках).
- **Фильтр платформы + разбивка по линиям:** останется 1 линия выбранной платформы + «Все» (которая ≈ той же платформе). Консистентно, не баг.
- **`success_rate=null` на бакете:** разрыв линии, метка не рисуется, в тултипе `—`.
- **Диапазон > 60 дней (custom):** 400 (как сейчас, `MAX_DASHBOARD_RANGE_DAYS`).
- **Часовые бакеты для будущих часов «сегодня»:** бакеты есть до `to` (конец дня), будущие часы без данных → `null` (разрыв) — ок.
- **`scheduled_at IS NULL`:** отсекается `scheduled_at >= $1` (NULL не проходит сравнение).

## 8. Тестирование

**Backend (unit, Node `--test`, как в проекте):**
- `calcDashboardRange('yesterday'|'last3')` — точные MSK-границы (вкл. границу месяца/года для `last3`).
- Выбор `unit`: `today`/`yesterday`→`hour`, остальные→`day`; граница ровно 1 день.
- `buildDashboardFilters` — корректные SQL-фрагменты и params для project/platform/account/pack; пустой query → пустой фильтр.
- Сборка серии: выравнивание по полной оси бакетов; пропуски → `null`; `success_rate` по бакету = `computeSuccessRate`; `all` = grand-total.
- Whitelist `unit` (инъекция исключена).
- Обратная совместимость: ответ всё ещё содержит `overall`/`by_platform`.
- Custom `from>to` / `>60д` → 400.

**Frontend:** smoke (JS-unit-сетапа в проекте нет) — открыть дашборд, переключить пресеты/фильтры, убедиться, что график перерисовывается и метки/тултип работают; проверить, что метки НЕ появились на других графиках (anti-regression datalabels).

**Ручная верификация после деплоя:** сверить точки графика с прямым SQL по `publish_queue` за тот же период/фильтр; проверить часовые бакеты на «Сегодня»/«Вчера»; неделя/месяц по дням; фильтр проекта совпадает с поведением таблицы «Запланировано».

## 9. Observability

- `console.log('[pub-dash]', …)` в server.js — как у соседних эндпоинтов; логировать выбранные preset/unit/фильтры и кол-во бакетов.
- 4xx на невалидные params (как сейчас) → красная плашка во фронте.
- 5xx → фронт оставляет предыдущие данные + «Ошибка обновления».

## 10. Деплой

- `index.html` (фильтры, пресеты, canvas, JS) + `server.js` (новые пресеты, `buildDashboardFilters`, SQL №2, форма ответа) правятся в `/root/.openclaw/workspace-genri/autowarm/`; auto-push hook → `GenGo2/delivery-contenthunter`; `pm2 restart` нужной инстанции (проверить `pm2 list` + `exec cwd` перед рестартом — memory `pm2_dump_path_drift`).
- Один новый CDN-`<script>` (`chartjs-plugin-datalabels`).
- **Без миграций / новых таблиц / индексов** — `publish_queue` ~1k строк в активном окне; два прохода (плитки + серия) на отфильтрованном наборе < 50мс. Кросс-репо grep не нужен (нет DDL).
- **Kill-switch:** env-флаг `DASHBOARD_TIMESERIES_ENABLED` (default on). При `=0` эндпоинт не считает серию (`series:null`), фронт скрывает график — плитки/фильтры продолжают работать. Дешёвая страховка для read-only фичи.
- ⚠️ Перед `git pull`/ff прода — проверить чужую незакоммиченную WIP в прод-чекауте (memory `project_daily_publish_report` готчи); правки при необходимости вносить хирургически.

## 11. Scope / YAGNI

**In scope:** 1 расширенный эндпоинт (плитки+серия), 2 новых пресета, 4 фильтра, 1 линейный график (4 линии) с метками/тултипом, env kill-switch.

**Out of scope (backlog):**
- URL-persist фильтров.
- Auto-refresh / live polling.
- Сравнение с предыдущим периодом.
- Блок «Прочие платформы» (vk/pinterest/likee).
- Drill-down по точке графика → таблица с фильтром.
- Экспорт CSV/PNG.
