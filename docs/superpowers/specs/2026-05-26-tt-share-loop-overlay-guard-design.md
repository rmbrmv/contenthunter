# WP #122 — TikTok: «Добавить в историю» перекрывает share-loop (overlay-guard)

**Дата:** 2026-05-26
**Тип:** Ошибка (суб-режим A `tt_upload_confirmation_timeout`)
**Репозиторий кода:** `GenGo2/delivery-contenthunter` (autowarm), файл `publisher_tiktok.py`
**Прод на момент разведки:** ветка `main`, HEAD `f569f5d`
**Связанные WP:** #118 (суб-режим B — модал «Подтвердите видимость», PR #89), #117/#119 (тройка рецидива)

---

## 1. Проблема

Часть падений TikTok-публикаций с кодом `tt_upload_confirmation_timeout` (≈4 из 7 за 20.05) вызвана тем, что во время поиска кнопки «Опубликовать» (share-loop) экран перекрывается окном «Добавить в историю»: либо Samsung Galaxy Add-to-Story auto-suggest, либо встроенный TikTok Stories-редактор. Из-за перекрытия кнопка публикации не находится в XML, бот уходит в слепой fallback (тапы по запасным координатам мимо кнопки) → публикация не уходит → таймаут ожидания подтверждения.

## 2. Корневая причина (подтверждено в коде)

Share-loop живёт в `publish_tiktok`, цикл `for attempt in range(8)` (строка ~1878). На каждой итерации:

1. dump_ui;
2. commercial-music hook (`_run_tt_commercial_music_hook(ui, 'share_loop')`);
3. гард геолокации / Android share-sheet;
4. XML-поиск clickable-узла с точным текстом `Опубликовать`/`Post`/`Publish` → tap → `_tapped_post = True` → `if _tapped_post: break` (строка ~1934);
5. **fallback** при `attempt >= 2` (строка ~1939): AI-vision tap (attempt==2) → затем слепые `FALLBACK_COORDS = [(816,2130),(808,2109),(825,2145)]` (строка ~1969).

Когда оверлей «Добавить в историю» перекрывает экран, кнопки публикации в XML нет → шаг 4 не находит её → управление доходит до шага 5 → слепые тапы бьют по оверлею, а не по кнопке → публикация не уходит → `wait_upload` (до 3 мин) таймаутит → `tt_upload_confirmation_timeout`.

Хендлеры этих окон **уже существуют и проверены в бою**, но вызываются только в фазе `wait_upload` (строки ~2276–2313), то есть **после** нажатия кнопки публикации:

- `_detect_samsung_stories_overlay` (строка ~345) / `_handle_samsung_stories_overlay` (строка ~489), cap `MAX_SAMSUNG_OVERLAY_ITERATIONS = 5`;
- `_detect_tt_inapp_stories` (строка ~381) / `_handle_tt_inapp_stories` (строка ~566), cap `MAX_INAPP_STORIES_ITERATIONS = 3`.

В share-loop их вызова нет → окно во время share-loop не закрывается.

Это сознательно отложенный суб-режим A: суб-режим B (модал «Подтвердите видимость публикации») зашит в PR #89, а A не вошёл из-за более высокого риска — правка затрагивает **основной путь публикации**.

## 3. Дизайн

Переиспользовать существующие detect+dismiss хендлеры в share-loop, под отдельным kill-switch, по умолчанию **выключенным** (тёмный выкат). Новых хендлеров не пишем.

### 3.1. Точка вставки — только когда кнопка не найдена

Новый блок вставляется внутри цикла `for attempt in range(8)`, **после** `if _tapped_post: break` (строка ~1935) и **перед** блоком `if attempt >= 2:` (строка ~1939).

Обоснование blast-radius: если кнопка «Опубликовать» найдена в XML, выполнение уже сделало `break` и до нового блока **не доходит** — happy-path не затрагивается вообще. Управление достигает нового блока **только когда кнопки в XML нет** — ровно та ситуация, когда оверлей перекрыл экран. Тогда:

```
if TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED:
    # Samsung "Добавить в историю"
    if _detect_samsung_stories_overlay(ui):
        if not _handle_samsung_stories_overlay(ui, attempt, phase='share_loop'):
            return False          # cap превышен → tt_samsung_overlay_stuck
        time.sleep(1.5); continue # перепроверить кнопку на след. итерации
    elif _samsung_overlay_iter > 0:
        log_event(... 'tt_samsung_overlay_dismissed' ..., step='share_loop')
        _samsung_overlay_iter = 0
    # TT in-app Stories
    if _detect_tt_inapp_stories(ui):
        if not _handle_tt_inapp_stories(ui, attempt, phase='share_loop'):
            return False          # cap превышен → tt_inapp_stories_stuck
        time.sleep(1.5); continue
    elif _inapp_stories_iter > 0:
        log_event(... 'tt_inapp_stories_dismissed' ..., step='share_loop')
        _inapp_stories_iter = 0
```

`continue` после dismiss возвращает цикл к dump_ui + XML-поиску кнопки → следующая итерация увидит уже очищенный экран. Блок зеркалит структуру wait_upload (детект → хендл → continue; либо reset-on-success при `iter > 0`).

### 3.2. Kill-switch — новый, default OFF

```
os.environ.get('TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED', 'false').lower() == 'true'
```

Отдельный рубильник, по умолчанию **`false`** (тёмный выкат). Гейтит **только** новый share-loop блок.

Существующие `TT_SAMSUNG_OVERLAY_HANDLER_ENABLED` / `TT_INAPP_STORIES_HANDLER_ENABLED` (default `true`) **не трогаем** — они продолжают гейтить wait_upload. Раздельные флаги нужны именно для того, чтобы wait_upload оставался ON, а share-loop был OFF до смоука.

### 3.3. Метка фазы в событиях (`phase`)

Оба хендлера сейчас хардкодят `'step': 'wait_upload'` в meta событий (detected / dismiss_attempt). Чтобы триаж не путал, из какой фазы пришло событие, добавляем в **оба** хендлера опциональный параметр:

```
def _handle_samsung_stories_overlay(self, ui_xml, wait, phase='wait_upload'):
def _handle_tt_inapp_stories(self, ui_xml, wait, phase='wait_upload'):
```

Внутри хендлеров `'step': 'wait_upload'` заменяется на `'step': phase` (для `*_detected` и `*_dismiss_attempt`); событие `*_stuck` сохраняет свой явный `tt_5_*_stuck` step без изменений. Значение по умолчанию `'wait_upload'` гарантирует, что **существующие вызовы из wait_upload остаются байт-в-байт идентичными** (positional-вызов `_handle_..._overlay(ui, wait)` не меняется). Из share-loop передаём `phase='share_loop'`.

Параметр `wait` в новом вызове получает значение `attempt` (номер итерации share-loop) — он идёт в meta как `wait_iter` для диагностики.

### 3.4. Счётчики и cap

`_samsung_overlay_iter` / `_inapp_stories_iter` сбрасываются per-publish в `_init_wait_upload_overlay_state()` (вызывается в начале `publish_tiktok`). Счётчики **общие** на публикацию: если оверлей дисмиссится и в share-loop, и в wait_upload, cap (5 / 3) суммируется по обеим фазам. Это желаемое поведение — ограничивает суммарное число попыток дисмисса за публикацию, а не даёт удвоенный бюджет.

При превышении cap хендлер вызывает `set_step('tt_5_*_stuck')` + `log_event('error', ...)` и возвращает `False` → новый блок делает `return False` из `publish_tiktok` (как в wait_upload). Это превращает «слепой таймаут» в честный код отказа `tt_samsung_overlay_stuck` / `tt_inapp_stories_stuck` ещё на стадии share-loop.

### 3.5. Что НЕ меняется

- wait_upload call site (строки ~2276–2313) — без изменений;
- существующие env-флаги wait_upload — без изменений;
- тела детекторов и стратегии дисмисса — без изменений;
- happy-path share-loop (кнопка найдена в XML) — без изменений;
- слепой fallback (`attempt >= 2`) — остаётся как есть; новый блок просто перехватывает оверлей **до** него.

## 4. Тестирование (TDD)

Юнит-тесты через мок-публишер (`_FakeProxy`, имена методов 1-в-1 с DevicePublisher) + подменённый `dump_ui`:

1. **detect+dismiss в share-loop:** dump_ui отдаёт XML с Samsung-оверлеем (нет кнопки публикации) → `_detect_samsung_stories_overlay=True` → вызвана стратегия дисмисса → `continue` (кнопка не нажата на этой итерации).
2. **in-app Stories аналогично.**
3. **happy-path не затронут:** XML содержит кнопку `Опубликовать` → `break`, новый overlay-блок не выполняется (детектор не зовётся).
4. **kill-switch OFF:** `TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED` unset/`false` → новый блок пропущен целиком даже при наличии оверлея в XML.
5. **cap → return False:** оверлей персистит > cap → `publish_tiktok` возвращает False + событие `tt_samsung_overlay_stuck` (соотв. `tt_inapp_stories_stuck`) со `step='tt_5_*_stuck'`.
6. **phase в meta:** событие `tt_samsung_overlay_detected` из share-loop имеет `meta.step == 'share_loop'`; регресс-тест на wait_upload — `meta.step == 'wait_upload'` (дефолт сохранён).
7. **reset-on-success:** после дисмисса оверлей исчезает (`iter > 0`, детект=False) → событие `tt_*_dismissed` + счётчик сброшен.

Прогон в прод-копии (или testbench-копии) `pytest` зелёный перед коммитом.

## 5. Выкат, смоук, верификация

1. Код + тесты → PR в `GenGo2/delivery-contenthunter`, флаг `TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED` отсутствует/`false` → **в бою блок неактивен** (тёмный выкат). Прод-поведение TikTok не меняется.
2. Контролируемый смоук на testbench с `TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED=true` на реальной TikTok-публикации, по возможности с воспроизведением оверлея «Добавить в историю». Проверяем: оверлей закрывается в share-loop, кнопка находится, публикация уходит; happy-path без оверлея не сломан.
3. После зелёного смоука — ручное включение флага в проде (env воркера autowarm).
4. WP #122 остаётся в «В разработке» с явной пометкой про шаг ручного включения, чтобы фикс не остался забыто-выключенным.

**Верификация после включения** (на нормальной TT-пачке): доля `tt_upload_confirmation_timeout` падает; появляются события `tt_samsung_overlay_detected`/`tt_inapp_stories_detected` со `step='share_loop'` и `tt_*_dismissed` (успешные восстановления). Группировать по финальной `meta.category` (исключая `adb_devices_unreachable`/`process_interrupted`).

## 6. Откат

`TT_SHARE_LOOP_OVERLAY_GUARD_ENABLED=false` (или удалить env-var) → новый блок отключается мгновенно без релиза. wait_upload-хендлеры не затронуты.

## 7. Риски

- **Happy-path:** ≈ ноль — новый блок недостижим при найденной в XML кнопке (после `break`).
- **Ложный детект оверлея:** детектор Samsung требует точный заголовок «Добавить в историю» + ≥2 различных маркера; in-app Stories — свою сигнатуру. Срабатывает только когда кнопки в XML уже нет (мы и так в проблемной ветке). При ложном дисмиссе — cap + честный `*_stuck`, не бесконечный цикл.
- **Главный путь публикации:** именно поэтому выкат тёмный (OFF) + смоук на testbench до включения; откат — флаг.
- **Сигнатуры хендлеров:** `phase` добавлен как trailing-kwarg с default → существующие positional-вызовы из wait_upload не ломаются (покрыто регресс-тестом).

## 8. Объём

Один файл `publisher_tiktok.py`: +1 блок в share-loop (~25 строк), +1 опциональный параметр в двух хендлерах с заменой хардкода step, +1 env-флаг. Плюс тесты. Диф тугой, изменение локализованное.
