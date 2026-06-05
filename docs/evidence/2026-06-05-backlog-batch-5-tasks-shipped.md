# Бэклог-батч (5 задач, не-ошибки-публикации / не-ops) — SHIPPED+DEPLOYED 2026-06-05

Реализованы субагентами (TDD, по одному агенту на задачу, изолированные git-worktree), собраны
в ветку `backlog-integration`, прошли холистическое кросс-задачное код-ревью (блокеров нет),
fast-forward в `delivery-contenthunter/main` (`cdf72d4 → 88655f7`), задеплоены на прод
`/root/.openclaw/workspace-genri/autowarm` (git pull + `pm2 restart 35`). Миграции БД не требовались.

Прод-верификация: сервер (порт 3848) поднялся, `/api/health` 200, отданный фронт содержит все
правки (`platformIcon` ×25, `dash-manual-share` ×12, `_dashSubString` ×6, datetime-local→UTC в
`submitPublishTask`). Интегрированный тест-сьют: **460/461 pass** (единственный fail —
предсуществующий `test_manual_publish_queue › takeItem: 404`, воспроизводится на baseline).

Все 5 тикетов → OpenProject «Тестирование».

---

## OP#252 — done_count в degradation-планировщике учитывает `published_no_url`

- **Файл:** `publish_planner.js` (degradation-ветка `getPlannerCards`, путь без колонок WP#108).
- **Баг:** `done_count = COUNT(*) FILTER (WHERE pq.status IN ('done','published'))`, тогда как
  `SUCCESS_STATUSES = {'done','published','published_no_url'}`. Ролик, выложенный без URL,
  занижал `done_count` → ложный `partial` вместо `published`. Пре-существующий (не внесён WP#167),
  только в degradation-пути.
- **Фикс:** добавлен `'published_no_url'` в FILTER. Единственный хардкод-FILTER в файле; остальные
  проверки идут через `SUCCESS_STATUSES.has()`.
- Без kill-switch/миграции. TDD: 21/21.
- Коммит `6624fc6`.

## OP#253 — submitPublishTask конвертит datetime-local в UTC-ISO (follow-up WP#247 Ф2)

- **Файл:** `public/index.html` (`submitPublishTask`, ~8196).
- **Баг:** форма слала сырую `datetime-local`-строку без оффсета, тогда как соседний путь
  `urSubmitPublish` (~12199, тот же эндпоинт `/api/publish/queue/manual`) уже конвертил через
  `new Date(v).toISOString()`. Оператор получал скрытый сдвиг относительно намерения. Не риск
  корректности миграции (момент трактуется как UTC и до, и после Ф2), но рассинхрон UX.
- **Фикс:** зеркалирование проверенного соседа: `schedRaw ? new Date(schedRaw).toISOString() : null`
  (пустое → `null` сохранено).
- Без kill-switch/миграции. Inline-фронт без тест-харнеса → минимизация риска точным зеркалированием.
  Прод отдаёт правку (verified).
- Коммит `09a45d3`.

## OP#245 — buildErrorBreakdown basis-aware + URL-state базиса (follow-up WP#239)

- **Файлы:** `daily_publish_report.js`, `public/index.html`.
- **(1) Backend:** `buildErrorBreakdown` был жёстко привязан к scheduled_at-окну, игнорируя
  `date_basis`. Стал basis-aware через существующие `reportWindowSql(basis)` + `winParams`
  (без нового механизма окна). Квалификатор колонок `w.col || 'publish_queue.'` — против
  `ambiguous column` при JOIN `publish_tasks` (поймано live-integration тестом).
- **(2) Frontend:** `switchDashboardBasis` не сохранял базис в URL → рефреш сбрасывал на `planned`.
  Введён общий `_dashSubString()` (кодирует базис хвостом `~b=<basis>` в том же `?sub`-слоте, чтобы
  не ломать `:`-парсинг `dash:custom:from:to`), на него переведены basis/preset/custom-переключатели;
  restore при `nav('publishing-dashboard')` через `_dashHighlightBasis()`.
- Без kill-switch/миграции. TDD: 46/46 + live-integration 9/9.
- Коммит `0e04f40`.

## OP#92 — иконки платформ (эмодзи) в UI

- **Файлы:** новый `platform_icons.js` + inline-дубль в `public/index.html` (байт-идентичны),
  ~17 мест отображения.
- **Что:** `platformIcon()`/`platformLabel()` с маппингом
  📸 Instagram · ▶️ YouTube · 🎵 TikTok · 📌 Pinterest · ❤️ Likee · 🔵 VK · 🎬 Rutube · 🟡 Dzen ·
  🧵 Threads · 🌊 Wibes. Иконка добавляется к **отображаемому тексту**; машинные `value`
  фильтров/параметров запросов не изменены (ревью проверило поимённо в 6 местах — фильтры целы),
  регистр ключей нормализуется (`.toLowerCase()`), неизвестная платформа → fallback на текст.
- Без kill-switch/миграции. Unit-тест маппинга 7/7.
- Коммит `3a1cfc8`.

## OP#141 — метрика count/% ручной выкладки на дашборде

- **Файлы:** `server.js` (`GET /api/publish-queue/dashboard`), `public/index.html`.
- **Что:** отдельная видимость объёма ручной выкладки — count и % за выбранный период/платформу,
  разделённые на два источника:
  - **retry-handoff** (бот провалил → ручная): `status='cancelled' AND manual_handoff_at IS NOT NULL`;
  - **проактивная** (админ/клиент заранее): `manual_handoff_at IS NULL AND (skip_reason='manual_publish'
    OR slot.manual_publish) AND skip_reason NOT LIKE 'moved_from_slot%'`.
  Переносы слотов исключены. Плитки + линии динамики. Переиспользованы существующие helper'ы окна/
  фильтра дашборда (`calcDashboardRange`/`dashboardDateWindow`/`buildDashboardFilters`/`DASHBOARD_QUEUE_FROM`).
- **Аддитивность:** новые `COUNT(*) FILTER`-колонки не сдвигают существующие тоталы/success_rate/errors
  (ревью подтвердило); двойного счёта нет (`manual_handoff_at IS NULL` vs `IS NOT NULL`
  взаимоисключающи); деление на ноль закрыто (`null` при total=0).
- **Kill-switch:** `DASHBOARD_MANUAL_SHARE_ENABLED` (default ON); OFF-путь отдаёт `null`, фронт прячет
  блоки без падения.
- TDD: 73/73. UI-приёмка — за Данилом.
- Коммит `051ca47`.

---

## Деплой

- `delivery-contenthunter/main`: `cdf72d4 → 88655f7` (FF, 5 merge-коммитов сохранены).
- Прод `/root/.openclaw/workspace-genri/autowarm`: `git pull --ff-only` → `88655f7`, `pm2 restart 35`
  (`autowarm` = server.js: дашборд + крон). Publisher не затронут (правки только в dashboard/server-слое).
- Миграции БД: не требуются ни для одной задачи.
- Откат: `DASHBOARD_MANUAL_SHARE_ENABLED=0` гасит #141; прочие — revert коммитов + restart.

## Холистическое ревью (итог)

Блокеров (CRITICAL/HIGH/MEDIUM) нет. Подтверждено: целостность `value` фильтров #92, неизменность
тоталов дашборда #141, отсутствие межзадачных коллизий в `index.html` (все новые идентификаторы
объявлены по одному разу). LOW-замечания (мёртвая `planned`-ветка в `buildErrorBreakdown`, хрупкий
контракт `winParams`, неквалифицированный `scheduled_at`) — косметика на будущее, мержу не мешали.
