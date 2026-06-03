# WP#215 — Ретраи только «день в день», после 14:00 всё в ручную

**Дата:** 2026-06-03
**OpenProject:** #215 «ретраи оставить только день в день» (статус: В разработке, исполнитель: danil)
**Репозиторий реализации:** `delivery-contenthunter` (autowarm)
**Ветка спеки:** `worktree-wp215-retries-same-day-only` (репо `contenthunter`)

## Проблема

Статистика за прошлую неделю: на **второй день** упавшие публикации почти не
перевыкладываются. Авто-ретраи эффективны **день в день** и в основном
отрабатывают в первой половине дня. Текущая логика держит окно ретраев
**2 календарных дня** и после дневной отсечки (23:00 МСК) просто «досыпает» до
следующего дня — то есть тратит сутки на ретраи, которые статистически
бесполезны, вместо того чтобы вовремя отдать работу операторам.

## Цель

1. Ретраи — **только день в день** (окно 1 день вместо 2).
2. Авто-ретраи продолжаются **до 14:00 МСК**.
3. **После 14:00** всё ещё-упавшее **передаётся операторам в ручную выкладку**
   (а не «ждёт до завтра»).
4. Если задача **исчерпала дневной кап** авто-ретраев ещё до 14:00 — передаём в
   ручную **сразу** (не ждём 14:00).

## Контекст текущей реализации

- Контроллер `retry_controller.js` (`retryFailedPublishes`) запускается из
  `server.js:7333` каждые `RETRY_INTERVAL_MINUTES` (дефолт 5 мин). Это
  **единственный** потребитель `publish_queue.status='failed'`.
- Чистое решение принимает `retry_decision.js::decideRetry(facts)` →
  `{action: 'requeue'|'handoff'|'wait', reason}`. Без БД и побочных эффектов.
- Действия исполняет контроллер: `requeueOne` (вернуть в `pending`) и
  `handoffToManual` (per-account залив строки в ручную очередь через
  `enqueueManualRow`, гашение `publish_queue` в `cancelled` + событие в лог).
- Тексты событий — `retry_labels.js` (WP#138 visibility).

### Текущее дерево decideRetry (по порядку)

1. структурные (`banned`/`ui_changed`) и не реанимированы → **handoff** (в любое время);
2. после отсечки (`!beforeCutoff`) → **wait**;
3. `fixed_at` реанимация → **requeue**;
4. окно дней исчерпано (`days >= windowDays`) → **handoff**;
5. `device_unreachable` при включённом троттлинге (WP#210): сверх капа → **wait**, иначе → **requeue**;
6. дневной кап класса исчерпан → **wait**;
7. transient (`network`/`rate_limited`/`unknown`) или device-health без троттлинга → **requeue**;
8. иначе → **wait**.

### Текущие env-флаги (retry_controller.js)

| Флаг | Дефолт | Смысл |
|---|---|---|
| `RETRY_ENGINE_ENABLED` | on | общий выключатель движка |
| `RETRY_MAX_PER_CLASS_PER_DAY` | 3 | кап авто-ретраев на класс ошибки в день |
| `RETRY_WINDOW_DAYS` | 2 | окно ретраев в календарных днях |
| `RETRY_CUTOFF_HOUR_MSK` | 23 | час МСК, после которого ретраи не запускаются |
| `RETRY_MANUAL_HANDOFF_ENABLED` | on | разрешён ли перевод в ручную |
| `RETRY_DEVICE_HEALTH_THROTTLE_ENABLED` | on | троттлинг adb-unreachable (WP#210) |
| `RETRY_MAX_DEVICE_HEALTH_PER_DAY` | 2 | кап device-health ретраев в день |
| `RETRY_HANDOFF_PER_ACCOUNT` | on | per-account залив в ручную (WP#148) |
| `RETRY_VISIBILITY_ENABLED` | on | писать события retry/handoff в лог (WP#138) |

## Решение (Подход A — хирургические правки + один kill-switch)

Меняем семантику двух веток дерева с `wait` на `handoff` и переключаем дефолты
времени/окна под одним новым kill-switch'ем. Логика остаётся в одном чистом
месте (`decideRetry`); хендофф переиспользует готовый `handoffToManual`.

### Изменения по поведению

| Условие | Сейчас | Станет |
|---|---|---|
| transient, попыток < капа, до 14:00 | requeue | requeue (без изменений) |
| transient, дневной кап исчерпан, до 14:00 | wait | **handoff** (`daily_cap_exhausted`) |
| после 14:00 МСК, любой ещё-упавший (вкл. `device_unreachable`, вкл. `fixed_at`) | wait | **handoff** (`after_cutoff_manual`) |
| `device_unreachable` до 14:00, сверх капа | wait (троттлинг) | **без изменений** (WP#210 цел) |
| структурные (`banned`/`ui_changed`) | handoff сразу | без изменений |
| окно дней исчерпано | handoff (2 дня) | handoff (**1 день**) |

**Почему `device_unreachable` после 14:00 уходит в ручную автоматически:**
ветка отсечки (#2) в дереве стоит **выше** ветки device-health (#5), поэтому при
`!beforeCutoff` решение принимается раньше, чем дойдёт до троттлинга. До 14:00
дерево до ветки #5 доходит штатно и троттлинг WP#210 сохраняется.

**Почему `fixed_at` после 14:00 уходит в ручную:** ветка отсечки (#2) стоит выше
ветки реанимации (#3). Это осознанное упрощение «после обеда всё в ручную без
исключений, кроме структурных» (решение по итогам брейнсторма).

### Точки изменения (delivery-contenthunter)

**1. `retry_decision.js` — `decideRetry`**
Добавить во входные факты `sameDayHandoff` (bool). Изменить две ветки:

- ветка #2 (после отсечки):
  `!beforeCutoff` → `sameDayHandoff ? {handoff, 'after_cutoff_manual'} : {wait, 'after_cutoff'}`
- ветка #6 (кап класса исчерпан):
  `attemptsTodayThisClass >= maxPerClassPerDay`
  → `sameDayHandoff ? {handoff, 'daily_cap_exhausted'} : {wait, 'daily_limit_wait_tomorrow'}`

Ветка #5 (device-health троттлинг) — **не трогаем** (остаётся `wait`/`requeue`);
после 14:00 её перехватывает ветка #2.

**2. `retry_controller.js` — флаги/дефолты**
Один новый kill-switch определяет и поведение, и дефолты времени/окна:

```js
const sameDayOnly = process.env.RETRY_SAME_DAY_ONLY_ENABLED !== 'false'; // дефолт ON
const windowDays  = num(process.env.RETRY_WINDOW_DAYS,     sameDayOnly ? 1  : 2);
const cutoffHour  = num(process.env.RETRY_CUTOFF_HOUR_MSK, sameDayOnly ? 14 : 23);
```

Передать `sameDayHandoff: sameDayOnly` в `decideRetry`. При
`RETRY_SAME_DAY_ONLY_ENABLED=false` восстанавливается **ровно старое поведение**
(окно 2, отсечка 23, обе ветки `wait`). Явные env-оверрайды `RETRY_WINDOW_DAYS` /
`RETRY_CUTOFF_HOUR_MSK` работают поверх (использован `num(env, fallback)`).

**3. `retry_labels.js` — тексты событий (WP#138)**
Добавить в `HANDOFF_MSG_BY_RULE`:

- `after_cutoff_manual`: «После 14:00 автоматическая выкладка на сегодня
  завершена — задача передана на ручную выкладку.»
- `daily_cap_exhausted`: «Исчерпан дневной лимит авто-перезапусков — задача
  передана на ручную выкладку.»

Текст `window_exhausted` сделать нейтральным к числу дней: «Автоматически
опубликовать не удалось — задача передана на ручную выкладку.» (сейчас зашито
«За 2 дня…», после смены окна на 1 это неверно).

### Новый kill-switch

| Флаг | Дефолт | Эффект |
|---|---|---|
| `RETRY_SAME_DAY_ONLY_ENABLED` | on | окно 1 день, отсечка 14:00, `wait→handoff` в ветках #2/#6. `=false` → полный откат к старому поведению одним флагом. |

## Тестирование (TDD)

**`test_retry_decision.test.js`** — добавить кейсы (`base` получает `sameDayHandoff:true`):
- transient, кап исчерпан (3/3), до 14:00, `sameDayHandoff:true` → **handoff** (`daily_cap_exhausted`);
- transient, кап исчерпан, `sameDayHandoff:false` → **wait** (старое);
- transient, после отсечки, `sameDayHandoff:true` → **handoff** (`after_cutoff_manual`);
- transient, после отсечки, `sameDayHandoff:false` → **wait** (старое);
- `device_unreachable` после отсечки, `sameDayHandoff:true` → **handoff** (ветка #2 перехватывает);
- `device_unreachable` до 14:00, сверх капа (троттлинг on) → **wait** (WP#210 цел);
- `fixed_at` реанимация после отсечки, `sameDayHandoff:true` → **handoff** (отсечка выше реанимации);
- `fixed_at` реанимация до 14:00 → **requeue** (без изменений);
- структурные → **handoff** в любое время (регрессия);
- окно 1 день: `days>=1` → **handoff**.

**`test_retry_controller.test.js`** — интеграция:
- дефолты от `RETRY_SAME_DAY_ONLY_ENABLED` (on → window 1 / cutoff 14 / sameDayHandoff; off → 2 / 23 / wait);
- явный env-оверрайд `RETRY_WINDOW_DAYS`/`RETRY_CUTOFF_HOUR_MSK` поверх kill-switch;
- хендофф реально заливает строку в ручную очередь (как существующие live-тесты).

Регрессия: прогнать полный набор `test_retry_*` + `test_manual_*` — без падений.

## Деплой и откат

- Прод-каталог autowarm: `/root/.openclaw/workspace-genri/autowarm` (git pull),
  рестарт `sudo pm2 restart` id35 (контроллер живёт в долгоиграющем server.js,
  рестарт нужен).
- **Откат**: `RETRY_SAME_DAY_ONLY_ENABLED=false` — мгновенно, без передеплоя.
- Миграции БД не требуются.

## Вне рамок (YAGNI)

- Не трогаем размер дневного капа (`RETRY_MAX_PER_CLASS_PER_DAY=3`).
- Не меняем механику троттлинга device-health до 14:00 (WP#210).
- Не добавляем отдельный «послеобеденный» крон — свип идёт штатными тиками
  контроллера (≤5 мин после 14:00 всё уедет в ручную).
- Не меняем UI ручной очереди — хендофф пишет в неё существующим путём.
