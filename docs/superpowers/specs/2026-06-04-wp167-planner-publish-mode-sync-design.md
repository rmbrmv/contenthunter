# WP#167 — Синхронизация статуса авто/ручной выкладки между админкой и карточкой планировщика

**Дата:** 2026-06-04
**Тип:** Ошибка (рассинхрон отображения)
**OpenProject:** #167 — «Синхронизировать статусы авто/ручной выкладки из админки и в карточке планировщика»
**Репозиторий реализации:** `delivery-contenthunter` (autowarm-дашборд)

## Проблема

Когда клиента переводят на ручную выкладку, карточки в планировщике дашборда продолжают
показывать бейдж 🤖 авто.

Пример из тикета: **Feminista «патчи для глаз»** — клиента перевели на ручную (21.05),
но в планировщике слоты по-прежнему помечены «авто».

## Корень (подтверждён на живой БД)

Источник истины для режима выкладки — флаг `manual_publish`:
- `validator_projects.manual_publish` — клиент-уровень, проставляется в админке валидатора;
- `validator_schedule_slots.manual_publish` — слот-уровень (в т.ч. ставит авто-тракт при хэндоффе после ошибки).

Авто-тракт (диспатч, populator, slot-matcher) уважает обоюдный предикат через единый
модуль `client_manual_filter.js`:
```
effective_manual = slot.manual_publish OR project.manual_publish   (с kill-switch CLIENT_MANUAL_PUBLISH_ENABLED)
```

**Планировщик (`publish_planner.js`) этот предикат не читает вообще.** Бейдж `mode`
вычисляется из факта исполнения, а не из конфигурации:
- **Плановые карточки** (будущие дни, ещё не выложенные) — `mode: 'auto'` захардкожен (≈стр. 279). ← кейс Feminista.
- **Degradation-ветка** (нет колонок WP#108) — тоже захардкожен `'auto'` (≈стр. 245).
- **Основная ветка** (`buildPlannerCards`, ≈стр. 92) — `mode = todayManual ? 'manual' : 'auto'`,
  где `todayManual` = «слот был выложен через ручную очередь» (ретроспектива исполнения).

Проверка на проде (`openclaw` PG, `localhost:5432`):
- `validator_projects` id=100 «Feminista патчи для глаз»: `manual_publish = true` — админка флаг проставила корректно.
- Колонки `manual_publish` + `manual_publish_set_at` есть в обеих таблицах.
- 40 слотов имеют собственный `manual_publish = true`.
- Вторая причина рассинхрона отсутствует — планировщик просто игнорирует флаг.

## Решение

Бейдж `mode` карточки планировщика вычисляется из **конфигурации**, единым предикатом
с авто-трактом. Фронтенд не меняется (он уже рисует бейдж по `c.mode`).

### Семантика бейджа (утверждено)

`mode` = **текущая конфигурация выкладки** (как в админке):
```
mode = isEffectivelyManual(slot.manual_publish, project.manual_publish) ? 'manual' : 'auto'
```
Применяется ко **всем** карточкам (плановым, текущим, прошлым). Перевели клиента на
ручную → все его карточки показывают 👋 вручную, полная синхронность с админкой.

Факт «было авто, ушло на ручную после ошибки» и «был автоповтор» отображают **отдельные**
маркеры ❗→✋ (`auto_handoff`) и 🔁 (`had_retry`) — они остаются без изменений.

### Компоненты

**1. `client_manual_filter.js` — новый JS-хелпер (единый источник истины):**
```js
function isEffectivelyManual({ slotManual, projectManual }) {
  return clientManualEnabled() ? (!!slotManual || !!projectManual) : !!slotManual;
}
```
Зеркалит логику `effectiveManualSql`, но для значений (не SQL-алиасов). Уважает
существующий kill-switch `CLIENT_MANUAL_PUBLISH_ENABLED`.

**2. `publish_planner.js` — три ветки построения карточек берут режим из конфигурации:**

- **Плановые карточки** (`prows`): запрос уже джойнит `validator_schedule_slots s` и
  `validator_projects vp` → добавить выборку `s.manual_publish`, `vp.manual_publish`;
  `mode` через хелпер.
- **Degradation-ветка**: добавить LEFT JOIN слота по `ut.meta->>'slot_id'` + флаг проекта;
  `mode` через хелпер.
- **Основная ветка** (`buildPlannerCards`): пробросить `slot_manual`/`project_manual`
  в `intent` (через LEFT JOIN слота в основном запросе `getPlannerCards`); внутри
  `buildPlannerCards` заменить `mode: todayManual ? 'manual' : 'auto'` на
  `mode: isEffectivelyManual(...)`. Конфиг — свойство цепочки (`meta = group[0]`).

### Kill-switch

`PLANNER_MODE_FROM_CONFIG_ENABLED` (дефолт **ON**). OFF → прежнее поведение
(хардкод `auto` в плановых/degradation + `via_manual` в основной ветке). Откат без редеплоя.

## Тестирование (TDD)

- `isEffectivelyManual`: project-manual / slot-manual / оба / ни одного → boolean;
  `CLIENT_MANUAL_PUBLISH_ENABLED=false` → учитывается только слот.
- `buildPlannerCards`: `effective_manual` true/false → `mode` manual/auto **независимо** от `via_manual`;
  маркеры `auto_handoff`/`had_retry` не затронуты.
- `PLANNER_MODE_FROM_CONFIG_ENABLED=false` → старое поведение сохранено.
- Регрессия существующего `test_publish_planner.test.js`.

## Границы (не входит)

- Админка валидатора — пишет флаг корректно, не трогаем.
- Фронтенд `index.html` — рисует по `c.mode`, не трогаем.
- Миграции БД — колонки уже существуют, не нужны.

## Развёртывание

- Работа в изолированном git worktree от `delivery-contenthunter` (отдельная ветка),
  чтобы не мешать параллельным сессиям на общем прод-чекауте.
- Деплой: git pull в autowarm + `pm2 restart` (server.js — дашборд).
- Правка read-only и обратима (kill-switch + чистое чтение конфигурации).
