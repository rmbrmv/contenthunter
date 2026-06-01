# WP#199 — Честная классификация preflight/media-фейлов (устранение `switch_failed_unspecified`-маски)

**Дата:** 2026-06-01
**Статус:** Дизайн утверждён → план реализации
**OpenProject:** #199 (assignee Данил, «В разработке»)
**Целевой репо (код):** `autowarm-testbench` (`GenGo2/delivery-contenthunter`), ветка `wp199-preflight-honest-classify`
**Связанные:** #140 (каталог error_codes), #195 (device-health gate), #196 (adb_push_chunked), #207/#208 (preflight-ordering — **уже в проде**), #210 (троттлинг ретраев device-unreachable)

---

## ⚠️ РЕВИЗИЯ 2026-06-01 (re-scope → media-only)

Во время реализации origin/main ушёл вперёд (параллельные сессии): смержены и задеплоены в прод **PR#138 (WP#207/#208)** — preflight-ordering через helper `_fail_with_preflight_error`, и **PR#139 (WP#210)** — троттлинг ретраев device-unreachable. Следствия:

1. **Preflight-часть этого WP стала избыточной** — уже в проде (другим способом). WP#199 **пересобран в media-only**.
2. **Поведение ретраев НЕ меняется** (исходная формулировка «263 задачи уйдут на manual» — неверна): движок `retry_decision.js`/`retry_controller.js` ключуется на `error_class` (network=adb_devices_unreachable/media → TRANSIENT, как и старый unknown). `retry_strategy` в каталоге — описательный, движком не используется. Эффект фикса — **чисто observability** (честный error_code на дашборде/триаже), net-neutral. Churn'ом device-unreachable отдельно занялся #210.
3. **relaunch_failed/relaunch_skipped** (рядом в media-`try`) имеют ту же очерёдность, НО swap их не лечит (тип события не `error`/`fail` → Pass-1/2 не покрывают, нужен error-event + каталожный код) → вынесено в **отдельный follow-up WP**.

**Итоговый scope WP#199:** helper `_fail_with_media_error(msg, err)` (зеркало #138) + вызов из media-блока (`if not remote_path:`) + поведенческий real-DB тест. Ветка `wp199-media-honest-classify` от origin/main. Разделы ниже отражают исходную диагностику (preflight+media); к реализации применима только media-часть.

## 1. Проблема и реальный root cause

### Премиса брифа (отклонена)
Бриф предлагал править `triage_classifier.py` и выбрать правило «first vs last error-event». Расследование показало, что это **не** причина:

1. **`triage_classifier.classify_events` уже корректен** — берёт *последний* error-event с `meta.category` (L407–413).
2. **Он не работает по проду** — `process_failed_task` выходит на `if not testbench: return` (L494). Прод-задачи он не классифицирует.

### Фактический root cause — баг порядка событий
Реальный писатель `error_code` в проде — `publisher_base._set_error_code_from_events`, вызываемый хуком из `update_status('failed')` (`publisher_base.py:1842`). Маппер читает `events` из БД и берёт первый error-event с `meta.reason|category`; если не нашёл → Pass 2 (switcher `fail`-step) → иначе `switch_failed_unspecified`.

Анти-паттерн в 2 точках call-flow: `update_status('failed')` вызывается **до** `log_event('error', meta={category})`. Поскольку `update_status` синхронно запускает маппер, а `log_event` синхронно дописывает event в БД **позже**, маппер не видит категорию и падает в catch-all.

**Точка 1 — ADB preflight** (`publisher_base.py`, origin/main L4330–4331):
```python
self.update_status('failed', f'ADB preflight: {category}')   # ← триггерит маппер, events ещё без error-event
self.log_event('error', f'ADB preflight failed: {category}', meta=adb_err)  # ← категория пишется ПОСЛЕ
return
```

**Точка 2 — media-фаза** (origin/main L4457–4458, при `media_phase_err`):
```python
self.update_status('failed', msg)
self.log_event('error', msg, meta=err)
return
```

### Эмпирическое подтверждение (прод, 7 дней)
Из **371** задач с `error_code='switch_failed_unspecified'`:
- **108** содержат в events `adb_device_not_ready`
- **237** — `adb_devices_unreachable`
- **26** — media/`adb_push_*`
- **0** «настоящих» catch-all (без preflight/media-категории)

То есть `switch_failed_unspecified` сейчас ~на 100% — артефакт-маска этого бага. Это и есть причина «слепых» ADB-инцидентов (#198: 86 задач на одном телефоне, 11ч без алерта).

---

## 2. Решение

### Изменение: swap порядка в 2 точках
В обеих точках сначала `log_event('error', …, meta=…)`, затем `update_status('failed', …)`. Маппер при срабатывании из `update_status` уже видит error-event с категорией → Pass 1 пишет корректный код.

`log_event` (`publisher_base.py:731`) пишет синхронно `UPDATE … events = events || %s; commit` — порядок гарантирован.

Чинит разом все категории через эти точки: `adb_device_not_ready`, `adb_devices_unreachable`, `adb_device_offline`, `media_not_found`, `media_empty`, `adb_push_failed/timeout/exception`.

### Что НЕ меняем
- **`triage_classifier.py`** — корректен и не работает по проду. Не трогаем.
- **Каталог `publish_error_codes`** — все коды уже зарегистрированы с верным `error_class` (#140):
  | код | error_class | retry_strategy |
  |---|---|---|
  | adb_device_not_ready | network | backoff |
  | adb_device_offline | network | backoff |
  | adb_devices_unreachable | network | **manual** |
  | adb_push_failed/timeout/exception | network | backoff |
  | media_not_found / media_empty | unknown | **manual** |
  | switch_failed_unspecified | unknown | backoff |

  Новые коды не нужны.
- **Без kill-switch** — изменение = 4 строки, откат тривиален через git revert.

### Принятый побочный эффект (решение утверждено)
~263 задачи/нед (`adb_devices_unreachable` 237 + media 26) перейдут с авто-`backoff` на `manual` → авто-ретраи по ним прекратятся. Это корректно: мёртвый adb-шлюз / битое медиа авто-ретраить бессмысленно, нужен ops-разбор. Это и есть цель observability — инциденты станут видны под честным кодом и честной retry-политикой.

---

## 3. Тестирование (TDD)

Регресс-тест зеркалит `tests/test_error_code_mapper.py`:
1. **Reproduce (red):** последовательность, где на момент `update_status('failed')` events ещё без error-event с категорией → маппер даёт `switch_failed_unspecified`.
2. **Fix (green):** при порядке «error-event первым» маппер для тех же входов даёт `adb_device_not_ready` (и аналог для `adb_devices_unreachable`, `media_not_found`).

Точный харнесс (мок DB/events) уточняется на этапе плана по образцу существующих тестов маппера.

---

## 4. Деконфликт с соседними WP

- **#195** (device-health gate в scheduler) — превентивно не спавнит publish на мёртвые девайсы (снижает объём фейлов). #199 — честный код для проскочивших. Кода не пересекают.
- **#196** (adb_push_chunked) — про сам push-флоу/целостность. #199 — только классификация. Не пересекаются.
- **#207** (Бэклог) — независимая находка того же ordering-бага из TT-триажа (шлюз-SPOF 147.45.251.85). Закрывается этим WP по коду.

## 5. Out of scope (noted follow-up)
Путь «Публикация не прошла» (origin/main L4516+: `update_status('failed', 'Публикация не прошла')` до `log_event` с `_resolve_publish_fail_category`) содержит тот же латентный ordering-баг, но эмпирически в `switch_failed_unspecified` сейчас не попадает (0 случаев/7д; его fallback — `publish_failed_generic`, switcher ловится Pass 2). По решению «точечно 2 точки» — не трогаем; зафиксировано как возможный follow-up.

---

## 6. Локации
- **Код:** `autowarm-testbench`, worktree `.worktrees/wp199`, ветка `wp199-preflight-honest-classify`. Файл `publisher_base.py` (2 точки) + `tests/`.
- **Spec/plan/evidence:** `contenthunter`, worktree `worktrees/wp199-docs`, ветка `wp199-preflight-honest-classify`.
