# Design — TT share-loop «Добавить в историю» overlay dismiss (reuse existing handlers, dark-launch)

**Date:** 2026-05-26
**OpenProject:** [#122](https://openproject.contenthunter.ru/wp/122)
**Triage brief:** `~/contenthunter_autoexec/briefs/122/brief.md`
**Rollout decision (WP #122 comment #605):** тёмный выкат — kill-switch **default OFF**, happy-path смок на testbench, затем ручное включение в проде с наблюдением за `tt_upload_confirmation_timeout`.
**Branch:** `wp122-tt-share-loop-overlay`

## Problem

Часть падений TikTok с кодом `tt_upload_confirmation_timeout` (≈4 из 7 за 2026-05-20) вызвана тем, что во время поиска кнопки «Опубликовать» (share-loop) экран перекрывается окном **«Добавить в историю»** — Samsung Galaxy Add-to-Story auto-suggest и/или встроенный TikTok Stories editor («Ваша история» / «Далее» / «Автомонтаж»). Кнопка публикации ищется по EXACT-тексту `Опубликовать`/`Post`/`Publish` (`publisher_tiktok.py:1903-1935`); под оверлеем она не находится, publisher уходит в fallback-координаты `(816,2130)` и тапает мимо → публикация не происходит → 3-мин `wait_upload` timeout.

**Это второй суб-режим того же `tt_upload_confirmation_timeout`, что и WP #118** (там закрыт пост-publish модал «Подтвердите видимость публикации», PR #89, прод `7414891`). Суб-режим A (этот) **сознательно не вошёл в PR #89 из-за более высокого риска**: правка затрагивает share-loop — основной путь публикации до нажатия кнопки, где регрессия ломает ВСЕ TikTok-публикации, а не только сегодняшние 4/7.

## Key insight — обработчики уже есть, нужна только новая фаза вызова

`publisher_tiktok.py` **уже содержит** готовые detect+dismiss для обоих оверлеев:

- `_detect_samsung_stories_overlay` / `_handle_samsung_stories_overlay` (`:345`, `:489`)
- `_detect_tt_inapp_stories` / `_handle_tt_inapp_stories` (`:381`, `:566`)

Они боевые с 2026-05-12 (spec `docs/superpowers/specs/2026-05-12-tt-wait-upload-overlay-handlers-design.md`), но вызываются **только в фазе `wait_upload`** (`_wait_upload_confirmation`, `:2276-2313`) — после нажатия «Опубликовать». В share-loop их нет, поэтому оверлей во время поиска кнопки не гасится.

**Фикс = добавить вызов тех же detect+dismiss в начало share-loop, под отдельным kill-switch (default OFF).** Новых детекторов/хендлеров/координат не пишем.

**Прецедент на основном пути уже обкатан:** в share-loop с 2026-05-15 (WP #75) работает аналогичный phase-aware хук `_run_tt_commercial_music_hook(ui, 'share_loop')` (`:1883`) — тот же контракт detect→dismiss-под-выключателем→`handled/stuck/clean`. То есть «трогать самый горячий путь» — не впервые; риск ниже, чем кажется по брифу.

## Goals

- Гасить окно «Добавить в историю» (Samsung overlay + TT in-app Stories) **в share-loop, перед поиском кнопки публикации**, переиспользуя существующие хелперы.
- Отдельный kill-switch `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED` (env, **default `'false'` — OFF**), чтобы выкатить тёмным и включить вручную после смока.
- Observability: события dismiss/stuck в share-loop помечены своим `step=tt_5_share_loop` (а dismissed-событие самого хука — ещё и `phase='share_loop'`), чтобы после включения в проде видеть, что dismiss реально сработал и `tt_upload_confirmation_timeout` падает.
- Не менять текущее поведение wait_upload — оно остаётся байт-в-байт.

## Non-goals

- IG/YT — оверлей только в TikTok.
- Новые детекторы/координаты/маркеры — не пишем, переиспользуем существующие.
- Прочие wait_upload-оверлеи (contacts-perm, Amplify, promo-inbox) — post-publish, **вне scope** этой правки. Только Samsung Add-to-Story + TT in-app Stories.
- Рефакторинг wait_upload-цепочки в общий orchestrator — не делаем (лишний риск на боевом коде без выгоды).
- Не меняем `error_code` задачи — он остаётся `tt_upload_confirmation_timeout`, но теперь дополнен явными share-loop dismissed/stuck событиями для триажа.

## Design

### Архитектура — новый share-loop orchestrator поверх существующих хелперов

Новый метод `_run_tt_stories_overlay_share_loop_hook(self, ui_xml, attempt) -> str`, по образцу `_run_tt_commercial_music_hook`. Контракт возврата идентичен:

- `'handled'` — оверлей был, dismiss-шаг отправлен (caller: `time.sleep(1.5); continue`).
- `'stuck'` — счётчик > MAX, событие `tt_*_stuck` уже записано хендлером + `set_step` (caller: `return False` = провал attempt).
- `'clean'` — оверлея нет или выключатель OFF (caller: продолжает обычную логику поиска кнопки).

```python
def _run_tt_stories_overlay_share_loop_hook(self, ui_xml: str, attempt: int) -> str:
    """Dismiss Samsung "Add to Story" / TT in-app Stories overlay during share_loop.

    Reuses the existing wait_upload detectors/handlers (WP #122). Gated by a
    SEPARATE kill-switch (default OFF) so wait_upload is unchanged and the main
    publish path can be enabled deliberately after a testbench smoke.

    Returns 'handled' | 'stuck' | 'clean' (same contract as the commercial-music hook).
    """
    if (os.environ.get('TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED', 'false').lower()
            != 'true'):
        return 'clean'

    # Samsung "Добавить в историю" overlay.
    if self._detect_samsung_stories_overlay(ui_xml):
        if not self._handle_samsung_stories_overlay(ui_xml, attempt, phase='share_loop'):
            return 'stuck'
        return 'handled'
    if self._samsung_overlay_iter > 0:
        self.log_event(
            'info', 'TikTok: Samsung overlay dismissed successfully (share_loop)',
            meta={'category': 'tt_samsung_overlay_dismissed',
                  'platform': self.platform, 'step': 'tt_5_share_loop',
                  'phase': 'share_loop', 'attempts': self._samsung_overlay_iter,
                  'wait_iter': attempt})
        self._samsung_overlay_iter = 0

    # TT in-app Stories editor.
    if self._detect_tt_inapp_stories(ui_xml):
        if not self._handle_tt_inapp_stories(ui_xml, attempt, phase='share_loop'):
            return 'stuck'
        return 'handled'
    if self._inapp_stories_iter > 0:
        self.log_event(
            'info', 'TikTok: in-app Stories dismissed successfully (share_loop)',
            meta={'category': 'tt_inapp_stories_dismissed',
                  'platform': self.platform, 'step': 'tt_5_share_loop',
                  'phase': 'share_loop', 'attempts': self._inapp_stories_iter,
                  'wait_iter': attempt})
        self._inapp_stories_iter = 0

    return 'clean'
```

Reset-ветки (`_iter > 0` когда оверлей уже не виден) зеркалят wait_upload call-site (`:2283-2295`, `:2304-2313`) и дают success-событие для триажа.

### Phase-параметр для существующих хендлеров (минимальная правка)

Хендлеры `_handle_samsung_stories_overlay` и `_handle_tt_inapp_stories` сейчас хардкодят `step='wait_upload'` в событиях. Чтобы share-loop события не мислейблились, добавляем **необязательный** параметр `phase: str = 'wait_upload'`, используемый ТОЛЬКО в `step`/`meta` событий:

```python
def _handle_samsung_stories_overlay(self, ui_xml: str, wait: int,
                                    phase: str = 'wait_upload') -> bool:
    ...
    _step = 'tt_5_share_loop' if phase == 'share_loop' else 'wait_upload'
    # во всех log_event этого метода: меняем ТОЛЬКО литерал 'step': 'wait_upload'
    # → 'step': _step. Новый ключ 'phase' в события хендлера НЕ добавляем —
    # иначе payload wait_upload перестанет быть идентичным. Различение фаз идёт
    # через сам 'step' ('wait_upload' vs 'tt_5_share_loop').
    # stuck-ветка: set_step остаётся 'tt_5_samsung_overlay_stuck' (как сейчас)
```

То же для `_handle_tt_inapp_stories`. **При default `phase='wait_upload'` `_step` резолвится в `'wait_upload'` и новых ключей не добавляется → payload событий wait_upload идентичен текущему (byte-for-byte); существующие call-sites (`:2279`, `:2300`) не передают параметр.** Единственная правка боевых хендлеров — замена литерала `'step': 'wait_upload'` на `'step': _step` (в share-loop резолвится в `'tt_5_share_loop'`). Ключ `'phase'` в события хендлера **не** добавляем; фазу несёт только `step` (и отдельное dismissed-событие самого хука).

### Hook point — начало share-loop

В `publish_tiktok`, внутри `for attempt in range(8):` (`:1878`), **сразу после** блока commercial-music hook (`:1883-1888`) и **до** гард-проверок геолокации/share-sheet и поиска кнопки (`:1890+`):

```python
        for attempt in range(8):
            ui = self.dump_ui()

            # Commercial-music modal handler (2026-05-15 / WP #75).
            _cm_res = self._run_tt_commercial_music_hook(ui, 'share_loop')
            if _cm_res == 'handled':
                time.sleep(2)
                continue
            if _cm_res == 'stuck':
                return False

            # WP #122 (2026-05-26): «Добавить в историю» overlay during share_loop.
            # Reuses wait_upload Samsung/in-app-stories handlers; kill-switch
            # default OFF (dark launch — enable after testbench smoke).
            _ov_res = self._run_tt_stories_overlay_share_loop_hook(ui, attempt)
            if _ov_res == 'handled':
                time.sleep(1.5)
                continue
            if _ov_res == 'stuck':
                return False

            # ... existing geolocation/share-sheet guards + button search ...
```

`sleep(1.5)` — как у wait_upload overlay-хендлеров (а не `2`, как у commercial-music), чтобы сохранить их каденс.

### Счётчики — переиспользуем существующие (shared cap per task)

Хук использует те же `self._samsung_overlay_iter` / `self._inapp_stories_iter`, инициализируемые в `_init_wait_upload_overlay_state` (`:330`, вызывается из `publish_tiktok` `:1629`). MAX — существующие `MAX_SAMSUNG_OVERLAY_ITERATIONS` / `MAX_INAPP_STORIES_ITERATIONS`.

**Следствие — общий cap на задачу через обе фазы** (как у commercial-music `_commercial_music_iter`). Это безопасно: wait_upload call-site сбрасывает счётчик в 0, как только оверлей перестаёт детектиться (`:2283`/`:2304`), а наш share-loop хук делает то же в reset-ветках. Если оверлей реально жил в share-loop и был погашен — счётчик обнулится до входа в wait_upload. Cap защищает от бесконечного цикла суммарно по задаче, что желательно.

### Риск share-loop, которого нет в wait_upload — `KEYCODE_BACK`

Хендлеры эскалируют до `KEYCODE_BACK` (Samsung iter 2-3, in-app iter 2). В share-loop рядом (`:1869`) явное предупреждение: **«KEYCODE_BACK без клавиатуры уйдёт с description screen обратно в редактор»** — то есть стрэй-BACK на композере навигирует назад со share-экрана.

**Почему это приемлемо (митигировано):**
1. `KEYCODE_BACK` шлётся хендлером ТОЛЬКО когда `_detect_*` вернул True на свежем дампе текущего прохода цикла (хук вызывается раз за `attempt`, перед каждым — свежий `dump_ui`). Эскалация до iter2 (BACK) происходит лишь если оверлей **подтверждён ещё present** на следующем проходе → BACK гасит сам оверлей (он top-окно), а не композер.
2. Детекторы строгие: Samsung — EXACT title `Добавить в историю` + ≥2 distinct вторичных маркера; in-app — primary EXACT + clickable `Далее` + ≥1 tertiary. Ложный позитив на чистом композере (где этих заголовков нет) маловероятен.
3. Остаточный риск = строгий детектор ложно сработал на композере → BACK увёл со share-экрана. Низкая вероятность, и это **именно тот регресс happy-path, который ловит смок на testbench** (см. Rollout) перед включением.

Доп. предохранитель не вводим (не усложняем боевой код) — полагаемся на OFF-default + смок + быстрый откат выключателем.

### Event categories

Новых категорий нет — переиспользуем существующие. В share-loop ветке события хендлера несут `step='tt_5_share_loop'` (вместо `wait_upload`); **новый ключ `phase` в события хендлера НЕ добавляется** (payload wait_upload-событий сохраняется). Только `*_dismissed`-события, эмитируемые самим хуком (новые, не из хендлера), несут `phase='share_loop'`:

| Category | Type | Когда (share_loop) |
|---|---|---|
| `tt_samsung_overlay_detected` | info | Samsung overlay впервые detected в share-loop (iter 1) |
| `tt_samsung_overlay_dismiss_attempt` | info | каждый dismiss-шаг (strategy: x_button_tap/keycode_back/coord_fallback) |
| `tt_samsung_overlay_dismissed` | info | counter>0, оверлей ушёл — recovery success |
| `tt_samsung_overlay_stuck` | error | iter > MAX → 'stuck' → fail attempt |
| `tt_inapp_stories_detected` | info | in-app Stories впервые detected в share-loop |
| `tt_inapp_stories_dismiss_attempt` | info | каждый dismiss-шаг (back_arrow_tap/keycode_back) |
| `tt_inapp_stories_dismissed` | info | counter>0, ушёл — recovery success |
| `tt_inapp_stories_stuck` | error | iter > MAX → 'stuck' → fail attempt |

Триаж после включения: `step='tt_5_share_loop'` (а у dismissed — `meta.phase='share_loop'`) отделяет share-loop dismiss от wait_upload; падение `tt_upload_confirmation_timeout` при росте `tt_samsung_overlay_dismissed`/`tt_inapp_stories_dismissed` (share_loop) = доказательство эффекта.

### Config

- Env `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED` — **default `'false'` (OFF)**. Единственный новый флаг.
- Существующие `TT_SAMSUNG_OVERLAY_HANDLER_ENABLED` / `TT_INAPP_STORIES_HANDLER_ENABLED` (default ON) — **не трогаем**; они гейтят wait_upload-ветку. Новый флаг — независимый, гейтит только share-loop.
- MAX — существующие `MAX_SAMSUNG_OVERLAY_ITERATIONS` / `MAX_INAPP_STORIES_ITERATIONS` (новых констант нет).

## Тесты

`tests/test_publisher_tt_share_loop_overlay.py` (XML-фикстуры inline; UI-ops мокаются):

**Kill-switch / happy-path (главный регресс-гард):**
- `test_hook_disabled_by_default` — флаг не выставлен → хук возвращает `'clean'`, `_detect_*` не вызывается (или его результат игнорируется), `adb_tap`/`adb` не вызываются. Это и есть проверка «не сломали рабочий путь».
- `test_hook_clean_when_no_overlay` — флаг ON + чистый composer XML → `'clean'`, без тапов.

**Detect+handle (флаг ON):**
- `test_hook_samsung_handled` — Samsung overlay XML → `'handled'`, dismiss-шаг отправлен, `_samsung_overlay_iter` инкрементирован.
- `test_hook_inapp_handled` — in-app Stories XML → `'handled'`.
- `test_hook_samsung_takes_priority_over_inapp` — оба detector'а True → обрабатывается Samsung первым (порядок в хуке), `'handled'`.

**Cap / stuck:**
- `test_hook_samsung_stuck_at_cap` — pre-set `_samsung_overlay_iter = MAX_SAMSUNG_OVERLAY_ITERATIONS` → следующий вызов → handler уходит > MAX → `'stuck'`, событие `tt_samsung_overlay_stuck`, `set_step('tt_5_samsung_overlay_stuck')`.
- `test_hook_inapp_stuck_at_cap` — аналогично для in-app.

**Observability / phase label:**
- `test_share_loop_handler_events_use_share_loop_step` — при `phase='share_loop'` события хендлера (detected/dismiss_attempt) несут `step='tt_5_share_loop'` и **не содержат** ключа `phase`.
- `test_hook_emits_dismissed_with_phase_after_recovery` — pre-set `_samsung_overlay_iter=2`, оверлея в текущем dump нет → новое событие `tt_samsung_overlay_dismissed` (хука) несёт `step='tt_5_share_loop'` + `meta['phase']='share_loop'` + сброс счётчика в 0.

**Регресс-гард wait_upload (правка phase-параметра нейтральна — payload идентичен):**
- `test_wait_upload_handler_default_phase_unchanged` — вызов `_handle_samsung_stories_overlay(ui, wait)` БЕЗ `phase` → событие по-прежнему `step='wait_upload'` и в `meta` **нет** ключа `phase` (payload byte-for-byte как до правки).
- `test_wait_upload_inapp_handler_default_phase_unchanged` — то же для in-app.

**Integration** (extend `test_publisher_tt_wait_upload_integration.py` или новый):
- `test_share_loop_overlay_then_publish` — флаг ON; `dump_ui` sequence: [overlay] → [clean composer с кнопкой «Опубликовать»]; первый проход хук `'handled'`+continue, второй проход `'clean'` → кнопка найдена и нажата.

## Кодовое расположение

- Новый метод `_run_tt_stories_overlay_share_loop_hook` — в `publisher_tiktok.py`, рядом с `_run_tt_commercial_music_hook` (`:1445`).
- Правка сигнатуры/событий `_handle_samsung_stories_overlay` (`:489`) и `_handle_tt_inapp_stories` (`:566`) — добавить `phase` param.
- Один call-site в `publish_tiktok` share-loop (`:1888+`).
- Никаких новых файлов кроме тестов. Никаких новых констант/координат.

## Что НЕ затрагиваем

- `_wait_upload_confirmation` цепочка overlay-хендлеров (`:2276-2313`) — без изменений.
- `publisher_kernel.py`, IG/YT publishers — out-of-scope.
- Детекторы `_detect_samsung_stories_overlay` / `_detect_tt_inapp_stories` — без изменений (переиспользуем как есть).
- Существующие env-флаги wait_upload-хендлеров — не трогаем.

## Rollout (по решению WP #122)

1. PR: код под `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED` **default OFF** + тесты → merge.
2. Деплой в прод (autowarm) — поведение не меняется (флаг OFF).
3. **Happy-path смок на testbench** (#19/#171, обычная TT-публикация без оверлея): убедиться, что хук возвращает `'clean'`, кнопка «Опубликовать» по-прежнему находится/нажимается, публикация проходит. Это закрывает главный регресс — поломку рабочего пути.
4. Включение `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true` в проде (PM2 ecosystem env воркера уникализации/autowarm) + рестарт воркера.
5. Наблюдение за утренней TT-пачкой: динамика `tt_upload_confirmation_timeout` ↓ + появление `tt_samsung_overlay_dismissed`/`tt_inapp_stories_dismissed` с `phase='share_loop'`.

## Rollback

- `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=false` → share-loop хук возвращает `'clean'` мгновенно, поведение share-loop = текущее (оверлей → кнопка не найдена → fallback-coords → timeout). wait_upload-ветка не затронута в любом случае.
- Откат кода: revert PR; phase-параметр хендлеров default-safe, отдельного отката не требует.

## Open questions / фокус смока

1. **`KEYCODE_BACK` на композере** — основной риск (см. «Риск share-loop»). На смоке проверить, что при ОТСУТСТВИИ оверлея хук не трогает экран (флаг ON + чистый композер → `'clean'`, без BACK), а при реальном оверлее BACK гасит оверлей, а не уводит со share-экрана. Если воспроизвести оверлей на testbench не удастся (он недетерминирован) — смок подтверждает только happy-path, а dismiss-путь валидируется уже в проде по событиям.
2. **Где выставляется env воркера** — подтвердить при деплое, как именно `TT_SHARE_LOOP_OVERLAY_HANDLER_ENABLED=true` доедет до процесса публикации (PM2 ecosystem env vs per-task spawn env). Влияет на шаг 4 rollout, не на дизайн.
3. **Shared cap взаимодействие** — если оверлей живёт И в share-loop, И в wait_upload одной задачи, суммарный cap может сработать раньше в wait_upload. Считаю желательным (anti-loop). Мониторить `*_stuck` после включения; при ложных stuck — развести счётчики по фазам (отдельная правка).
