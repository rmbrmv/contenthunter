# Design — TT commercial-music modal handler (cancel-first ladder)

**Date:** 2026-05-15
**OpenProject:** [#75](https://openproject.contenthunter.ru/wp/75)
**Evidence:** `docs/evidence/2026-05-15-tt-publish-fails-triage.md`
**Branch:** `tt-publish-fails-triage-2026-05-15`

## Problem

TikTok начал для части аккаунтов принудительно открывать модал **«Коммерческие треки»** (commercial-music selector) на стадии композера — между post-switch verify и Шагом 5 («Опубликовать»). Модал перекрывает кнопку «Опубликовать», publisher не находит её в XML и через AI vision (`{x:null,y:null}`), fallback-coords тапают по случайным элементам модала (заходим в плейлист `TikBiz`), composer не возвращается → 3-мин `wait_upload` timeout → `tt_upload_confirmation_timeout`.

**Объём за сутки 2026-05-15:** 3 явных task'а (6495, 6510, 6512) + 1 orphan (5202) с той же сигнатурой = **44% non-network TT-фейлов**. Все на разных аккаунтах/устройствах/raspberry — баг воспроизводимый, не device-state.

Это **не** music-rights confirmation (PR #28 от 2026-05-10 и v12 в PR #32 от 2026-05-11) — тот был про диалог согласия с правами; здесь TT-новый **selector с принудительным выбором** коммерческого трека.

## Goals

- Распознать модал «Коммерческие треки» в TT-композере перед нажатием «Опубликовать».
- Закрыть модал (cancel-X) — если TT даёт продолжить публикацию без commercial-music, это безопаснее (никакой случайной музыки на контенте клиента).
- Если cancel-X не срабатывает (модал переоткрывается) — fallback: выбрать первый трек с ✓ для прогресса вперёд.
- Логировать новый класс ошибки `tt_commercial_music_stuck` (и success-категории), чтобы триаж видел эффект.
- Реализация — feature-кnob `TT_COMMERCIAL_MUSIC_HANDLER_ENABLED` (env, default ON).

## Non-goals

- IG/YT — модал только в TikTok.
- Не пишем «правильную» music-policy для бизнес-аккаунтов (требует discovery на стороне TT настроек профиля).
- Не блокируем publish при первой неудаче cancel — fallback select обеспечивает forward progress.
- Не правим существующий `_handle_tt_music_rights_dialog` (другая UI-сущность).

## Design

### Архитектура — следуем существующему overlay-handler паттерну

publisher_tiktok.py уже содержит цепочку overlay-handler'ов в `_wait_upload_confirmation` (Samsung Stories overlay, in-app Stories, contacts perm, audio dialog, music rights). Каждый handler имеет:

- `_detect_X(ui_xml) -> bool`
- `_handle_X(ui_xml) -> bool` (True = handled, False = stuck/unrecoverable)
- counter `self._X_iter`
- `MAX_X_ITERATIONS` constant
- env-flag (default ON)
- `tt_X_dismissed` (info) + `tt_X_stuck` (error) events

Новый handler — `_handle_tt_commercial_music_modal` — собирается ровно по этому шаблону, плюс отдельный ladder (cancel→select).

### Detection — три уровня

```python
_TT_COMMERCIAL_MUSIC_TITLE_MARKERS = (
    'Коммерческие треки',
    'Commercial music',
    'Commercial sounds',
)
_TT_COMMERCIAL_MUSIC_FALLBACK_SUBSTRINGS = (
    'коммерчески',  # lowercase RU stem
    'commercial mus',
    'commercial sou',
)
_TT_COMMERCIAL_MUSIC_TAB_LABELS = (
    'Интересное', 'Избранное', 'For You', 'Favorites',
)
_TT_COMMERCIAL_MUSIC_PLAYLIST_HINTS = (
    'TikBiz', 'TikTok Viral', 'New Releases', 'Emerging Artists',
)
```

**Strict** (`_detect_tt_commercial_music_modal`): title-node EXACT по text **или** desc на одном из `_TT_COMMERCIAL_MUSIC_TITLE_MARKERS`, **И** одна из двух структур: (a) хотя бы один tab-label из `_TT_COMMERCIAL_MUSIC_TAB_LABELS`, или (b) хотя бы один playlist-hint из `_TT_COMMERCIAL_MUSIC_PLAYLIST_HINTS` как text/desc. Title без структуры → False (защита от false-positive на settings-странице где может оказаться слово "Коммерческие").

**Fallback** (`_detect_tt_commercial_music_modal_fallback`): case-insensitive substring из `_TT_COMMERCIAL_MUSIC_FALLBACK_SUBSTRINGS`, плюс хотя бы один clickable близкий к top-left (y<200, x<200) — кандидат на close-X, плюс хотя бы один track-row (узнаваем по структуре «обложка слева + текст + ✓ справа», см. ниже).

**Evidence-only** (`_detect_tt_commercial_music_modal_evidence_only`): substring + title-marker без явной модальной структуры. **Не handle'ит** — только dump+log. Throttle через `self._commercial_music_evidence_dumped` (как у music-rights).

Все три используют `xml.etree.ElementTree.fromstring` с try/except (плохой XML → False, как в существующих detectors).

### Action ladder — cancel → select

`MAX_COMMERCIAL_MUSIC_ITERATIONS = 4`. Counter и evidence-флаг хранятся на `self` и инициализируются helper'ом `_init_commercial_music_state` (детали в «Counter init» ниже).

**Разделение обязанностей** (важно для покрытия fallback / evidence-only путей — Codex round 1, P2 #1):

- **Outer gate** (в hook'ах, см. ниже) — решает «обрабатывать ли сейчас». Учитывает БОТЬ strict и fallback detector'ы (когда `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED=true`), и сам обрабатывает evidence-only/dismissed-логирование. Это позволяет fallback-варианту title попадать в handler.
- **`_handle_tt_commercial_music_modal(ui_xml, matched_via)`** — выполняет только action ladder (cancel или select). Counter уже инкрементирован outer'ом до вызова. `matched_via ∈ {'strict','fallback'}` пробрасывается в meta.

```python
def _handle_tt_commercial_music_modal(self, ui_xml: str, matched_via: str) -> bool:
    if self._commercial_music_iter <= 2:
        # Path A: cancel via X
        tapped = self._tap_tt_commercial_music_close(ui_xml)
        category = 'tt_commercial_music_cancelled' if tapped \
                   else 'tt_commercial_music_close_not_found'
        phase = 'cancel'
    else:
        # Path B: select 1st track
        tapped = self._tap_tt_commercial_music_first_track(ui_xml)
        category = 'tt_commercial_music_track_selected' if tapped \
                   else 'tt_commercial_music_track_not_found'
        phase = 'select'

    self.log_event('info' if tapped else 'warning',
                   f'TikTok: commercial-music modal {category}',
                   meta={'category': category, 'platform': 'TikTok',
                         'matched_via': matched_via,
                         'iter': self._commercial_music_iter,
                         'phase': phase})
    return tapped
```

### Close-X tap (`_tap_tt_commercial_music_close`)

Кандидаты на X-кнопку:
1. clickable node, content-desc / text in `('Close', 'Закрыть', 'Cancel', 'Отмена', '×', 'X')`
2. clickable ImageView/ImageButton class, bounds в top-left zone (cx < 200 AND cy < 250)
3. Берём первого подходящего по приоритету (1) перед (2). Tap по центру bounds.

Возвращает True если tap отправлен. Если кандидаты не найдены — False (logger пишет `tt_commercial_music_close_not_found`).

### Fallback select first track (`_tap_tt_commercial_music_first_track`)

Track-row identity (узнаваем по совместному наличию):
- clickable node с ✓-glyph (`'✓'`, `'✓'` в text/desc, либо content-desc/text containing `'Select'/'Выбрать'/'Confirm'`).
- Альтернатива (на случай XML без unicode-glyph): rightmost clickable node в строке с заданным y, где левее в той же строке есть text-node с длинной name (длина > 3) и playable-icon (`'play'` в content-desc).

Алгоритм:
1. Парсим узлы, собираем list `(y_top, ✓_node)` всех ✓-кандидатов из node-tree (отсортированных по y_top).
2. Берём первый из списка с `y_top > header_threshold` (header_threshold = 250) — пропускаем тап-кнопки заголовка.
3. Tap по центру bounds. False если list пуст.

### Hook points

Outer gate включает strict ИЛИ fallback (когда флаг включён) — это покрывает оба пути detector'а; evidence-only — в else-ветке. Реализация защищена `getattr` на случай, если hook сработает до init (см. Counter init).

1. **`_publish_share_loop` Шаг 5** (publisher_tiktok.py:1256+):
   Внутри `for attempt in range(8):`, в самом начале после `ui = self.dump_ui()`, добавить:
   ```python
   if env('TT_COMMERCIAL_MUSIC_HANDLER_ENABLED', 'true') == 'true':
       fb_enabled = env('TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED', 'false') == 'true'
       matched_via = None
       if self._detect_tt_commercial_music_modal(ui):
           matched_via = 'strict'
       elif fb_enabled and self._detect_tt_commercial_music_modal_fallback(ui):
           matched_via = 'fallback'
           dump_path = self._save_dump_for_commercial_music_review(ui, 'fallback')
           self.log_event('info', 'TikTok: commercial-music modal matched via fallback',
                          meta={'category': 'tt_commercial_music_fallback_match',
                                'dump_path': dump_path, 'platform': 'TikTok'})

       if matched_via is not None:
           self._commercial_music_iter = getattr(self, '_commercial_music_iter', 0) + 1
           if self._commercial_music_iter > MAX_COMMERCIAL_MUSIC_ITERATIONS:
               self.log_event('error',
                   f'tt_commercial_music_stuck: modal persists > '
                   f'{MAX_COMMERCIAL_MUSIC_ITERATIONS} iterations',
                   meta={'category': 'tt_commercial_music_stuck',
                         'iterations': self._commercial_music_iter,
                         'platform': 'TikTok', 'step': 'tt_5_share_loop'})
               return False
           handled = self._handle_tt_commercial_music_modal(ui, matched_via)
           time.sleep(2)
           continue
       # matched_via is None — модал не обнаружен.
       if (fb_enabled
           and not getattr(self, '_commercial_music_evidence_dumped', False)
           and self._detect_tt_commercial_music_modal_evidence_only(ui)):
           dump_path = self._save_dump_for_commercial_music_review(ui, 'unhandled_suspect')
           self.log_event('warning',
               'TikTok: commercial-music modal-like suspect, not auto-handled',
               meta={'category': 'tt_commercial_music_unhandled_suspect',
                     'dump_path': dump_path, 'platform': 'TikTok'})
           self._commercial_music_evidence_dumped = True
       if getattr(self, '_commercial_music_iter', 0) > 0:
           self.log_event('info', 'TikTok: commercial-music modal dismissed',
                          meta={'category': 'tt_commercial_music_dismissed',
                                'platform': 'TikTok',
                                'attempts': self._commercial_music_iter,
                                'phase': 'share_loop'})
           self._commercial_music_iter = 0
   ```

2. **`_wait_upload_confirmation` outer loop** (publisher_tiktok.py:~1568, рядом с другими overlay-handlers): такой же snippet, но `phase='wait_upload'` и `step='wait_upload'` в `tt_commercial_music_stuck` meta. Defensive — если модал появится после нажатия Share.

### Counter init

Новый helper `_init_commercial_music_state(self)`:
```python
def _init_commercial_music_state(self) -> None:
    self._commercial_music_iter = 0
    self._commercial_music_evidence_dumped = False
```

Вызывается из `publish_tiktok` (publisher_tiktok.py:1006+) сразу после `self._init_music_rights_state()` и `self._init_wait_upload_overlay_state()` (строки 1012, 1015). Это гарантирует, что атрибуты существуют до входа в share-loop (Codex round 1, P2 #2). В дополнение все обращения в hook'ах используют `getattr(self, '_commercial_music_iter', 0)` / `getattr(self, '_commercial_music_evidence_dumped', False)` — defensive, на случай вызова handler'а из контекста, где init ещё не отработал (тесты).

### Event categories (новые)

| Category | Type | Когда |
|---|---|---|
| `tt_commercial_music_modal_detected` | info | strict detector сработал в первый раз per task (опционально, можно опустить и использовать только cancelled/selected) |
| `tt_commercial_music_cancelled` | info | X-tap отправлен (фаза cancel) |
| `tt_commercial_music_close_not_found` | warning | X не нашли в первой фазе |
| `tt_commercial_music_track_selected` | info | ✓-tap отправлен (фаза select) |
| `tt_commercial_music_track_not_found` | warning | ✓ не нашли в фазе select |
| `tt_commercial_music_dismissed` | info | counter > 0, модал больше не detected — recovery success |
| `tt_commercial_music_stuck` | error | iter > MAX → fail attempt |
| `tt_commercial_music_fallback_match` | info | matched через fallback detector |
| `tt_commercial_music_unhandled_suspect` | warning | evidence-only detector (с dump) |

`step` field — `tt_5_share_loop` или `wait_upload` в зависимости от hook'а.

### Config

- `MAX_COMMERCIAL_MUSIC_ITERATIONS = 4` (2 cancel + 2 select).
- Env `TT_COMMERCIAL_MUSIC_HANDLER_ENABLED` — default `'true'`.
- Env `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED` — default `'false'` (вкл. через PM2 ecosystem после первой evidence-only dump).

### Тесты

`tests/test_publisher_tt_commercial_music_modal.py`:

**Detector unit tests** (XML fixtures inline в тестах):
- `test_detect_strict_match_ru` — title="Коммерческие треки" + tab "Интересное" → True.
- `test_detect_strict_match_en` — title="Commercial music" + playlist hint "TikBiz" → True.
- `test_detect_strict_no_title` — нет title-marker → False.
- `test_detect_strict_no_structure` — title есть, нет ни tabs ни playlists → False.
- `test_detect_fallback_match` — substring + close-x candidate + track row → True.
- `test_detect_fallback_disabled_by_default` — strict miss → handle returns False (без fallback).
- `test_detect_evidence_only_dump_throttled` — два подряд evidence-only вызова с TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED=true → dump только раз.

**Action ladder tests** (mock UI ops; counter инкрементируется hook'ом, handler сам только тапает):
- `test_handle_iter1_cancels` — pre-set `_commercial_music_iter=1`, handler вызывает `_tap_tt_commercial_music_close`, событие `tt_commercial_music_cancelled`.
- `test_handle_iter3_selects_first_track` — pre-set `_commercial_music_iter=3` (>2), handler вызывает `_tap_tt_commercial_music_first_track`, событие `tt_commercial_music_track_selected`.
- `test_handle_logs_warning_on_close_not_found` — handler возвращает False, event `tt_commercial_music_close_not_found`.
- `test_hook_stuck_when_iter_exceeds_max` — pre-set `_commercial_music_iter=4`, повторный hook → counter уйдёт в 5 > MAX → event `tt_commercial_music_stuck`, hook возвращает False (вне handler).
- `test_hook_init_independent_of_wait_upload` — share-loop hook отрабатывает корректно когда `_init_wait_upload_overlay_state()` ещё не вызывался (получает `_commercial_music_iter` через `_init_commercial_music_state()` или getattr).

**Close-X tap tests:**
- `test_close_button_by_desc_close` — content-desc="Close" → tap.
- `test_close_button_by_desc_zakryt` — content-desc="Закрыть" → tap.
- `test_close_button_by_topleft_zone` — нет desc, но clickable ImageView в (x<200,y<200) → tap.
- `test_close_button_not_found` → return False.

**First-track tap tests:**
- `test_first_track_by_checkmark_unicode` — ✓ glyph → tap.
- `test_first_track_skips_header_zone` — есть ✓ в (y<250) и в (y>500) → выбран нижний.
- `test_first_track_not_found` → return False.

**Integration** (`test_publisher_tt_wait_upload_integration.py` extended):
- `test_commercial_music_modal_then_publish` — модал в share_loop iter 0 → handled (cancel) → следующий dump без модала → publish proceeds (mock через несколько dump_ui sequences).

### Кодовое расположение

- Все методы — в `publisher_tiktok.py` (как и `_handle_tt_music_rights_dialog`).
- Никаких новых файлов.
- Константы (markers, MAX, labels) — в начале файла, рядом с `MAX_MUSIC_RIGHTS_ITERATIONS`.
- Helper `_save_dump_for_commercial_music_review(self, ui_xml, suffix)` — копия `_save_dump_for_fallback_review` с другим filename-prefix (`tt_commercial_music_<suffix>_task_<id>_<ts>_<uid>.xml`). Никогда не raise'ит.

### Что НЕ затрагиваем

- `publisher_kernel.py` — не трогаем.
- IG/YT publishers — out-of-scope.
- Existing music_rights handler — orthogonal, не трогаем.
- Не меняем error_code на task — он остаётся `tt_upload_confirmation_timeout` если все попытки cancel+select исчерпались, но теперь дополнен явным `tt_commercial_music_stuck` event для триажа.

## Rollback plan

Если handler делает хуже (false-positives, ломает чистый share-loop):
- `TT_COMMERCIAL_MUSIC_HANDLER_ENABLED=false` в PM2 ecosystem → handler полностью disabled, fallback на старое поведение (модал → ai_find_tap_no_coords → timeout).
- Если только fallback detector проблемный — `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED=false` оставляет strict.

## Open questions

1. **Cancel-X actually dismisses?** — без live observation мы не знаем, закроет ли X модал навсегда или TT снова откроет на следующем publish-tap. Counter ≤ 2 для cancel — даём 2 попытки, потом переключаемся на select. После shipping будем мониторить распределение `tt_commercial_music_cancelled` vs `tt_commercial_music_track_selected` — если cancel-фаза всегда уходит в track_selected, значит cancel не работает, и нужно переходить на select-первым.
2. **«Бизнес-аккаунт only»?** — все 3 task'а сегодня — на бренд-аккаунтах (axilor_prive/brand, clickpay_under). Возможно это специфично для business profile. Имя `clickpay` намекает на коммерческую тематику. Долгосрочный фикс — выяснить настройку «Использовать коммерческую музыку» в TT и выставить её на стороне профиля. Это вне scope этого PR.
3. **AI-vision промпт надо обновлять?** — нет: даже если на чистом экране vision стабильно находит «Опубликовать», на модале без неё она правильно отдаёт null. Проблема не в vision, а в том что publisher не убирает оверлей перед поиском кнопки. Handler делает это.
