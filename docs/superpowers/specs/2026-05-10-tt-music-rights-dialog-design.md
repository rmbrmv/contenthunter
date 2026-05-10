# TikTok music rights confirmation dialog handler — design spec

**Дата:** 2026-05-10
**Sub-project:** TT publish stabilization — music rights overlay handler
**Репо:** `autowarm-testbench` (auto-pushed → `GenGo2/delivery-contenthunter`)

---

## 1. Контекст

### 1.1. Симптом

`tt_upload_confirmation_timeout` — top TT failure 24ч (12 fails на raspberry=9 за 24ч 2026-05-10, 0 done). YT/IG на том же телефоне работают (95%/32% success), TT — 100% timeout. Не device-state.

Распределение по аккаунтам: 11 разных accounts с этим error_code за 24ч, каждый по 1 attempt. Не account-bound, systemic.

### 1.2. Root cause (Phase 1 investigation)

AI Unstuck screenshot (task 4488 unstuck step 1, `https://save.gengo.io/autowarm/screenshots/tiktok/task4488_unstuck_4488_1778417268.png`) показывает диалог TikTok после tap «Опубликовать»:

- Заголовок: «Подтвердить и опубликовать видео?»
- Текст: «Если вы решите опубликовать это видео, то автоматически подтвердите наличие прав на использование музыки.»
- Красный link: «Подтверждение прав на использование музыки >» (ведёт на детальный экран)
- Кнопка: **«Опубликовать видео»** (внутри диалога)
- Кнопка: «Отмена»
- Чекбокс снизу: «Я принимаю Подтверждение прав на использование музыки» (НЕ отмечен)
- Большая красная «Опубликовать» внизу экрана (вне диалога)

Publisher тапает основную «Опубликовать» (publisher_tiktok.py:314 / fallback path) → TT поднимает music rights confirmation dialog → publisher не имеет handler → wait_upload loop крутится 60 итераций (~3 минуты) → timeout.

AI Unstuck тапает «Подтверждение прав на использование музыки >» (link на детали) — это не accept, dialog остаётся.

Confirmed на 5 samples (4488, 4482, 4470, 4468, 4416, 4439, 4432, 4466, 4429), все на raspberry=9, разные accounts. Системный publisher gap.

### 1.3. Почему сейчас и почему #9

- Music rights dialog — новая или усиленная TikTok feature (UX rollout). Возможно А/Б-тест попал именно на #9, или конкретные ClickPay/Wellfresh видео содержат detected copyright music. Точная этиология вне scope этого спека — fix должен покрывать любое появление dialog'а на любом телефоне.
- За 7 дней: tt_upload_confirmation_timeout cnt по raspberry: #9=14, #3=3, #5=2, #7=2, #10=1, #2=1, #1=1. До 2026-05-09 — единичные events. Резкий рост 2026-05-10 на #9 → fix будет pre-empt'ить расширение на другие устройства.

### 1.4. User decision (brainstorming 2026-05-10)

**Auto-accept + проставить чекбокс для persistence.** Текст dialog'а явно говорит: «если вы решите опубликовать — автоматически подтверждаете наличие прав». Tap «Опубликовать видео» = accept от имени клиента. Чекбокс — для persistence, чтобы dialog не возвращался на этом аккаунте/устройстве.

---

## 2. Approach

**Approach A** из 3 предложенных: handler в `wait_upload` loop рядом с `_tt_notif_markers` / `_tt_audio_markers`. Pure helper в TikTokMixin, returns True если dialog обработан. Caller делает `continue`.

Альтернативы рассмотрены и отклонены:
- *Approach B (handler в still_on_editor)*: dialog — overlay, не editor screen. Misidentified semantics.
- *Approach C (pre-Share probe + loop handler)*: 8s sleep после tap «Опубликовать» уже даёт буфер; дополнительный probe — premature optimization для 12 fails/24h.

---

## 3. Архитектура

### 3.1. Constants

Module-level в `publisher_tiktok.py` (рядом с существующим `MAX_AUDIO_DIALOG_ITERATIONS`):

```python
MAX_MUSIC_RIGHTS_ITERATIONS = 5
```

Class constants в `TikTokMixin`, рядом с `_tt_notif_markers` / `_tt_audio_markers` (которые тоже class-level в текущем коде):

```python
_TT_MUSIC_RIGHTS_MARKERS = [
    'Подтвердить и опубликовать видео',
    'Confirm and publish video',
    'Подтверждение прав на использование музыки',
    'music usage rights',
]
_TT_MUSIC_RIGHTS_BUTTON = ['Опубликовать видео', 'Publish video']
_TT_MUSIC_RIGHTS_CHECKBOX = [
    'Я принимаю Подтверждение прав на использование музыки',
    'I accept the Music Usage Rights Confirmation',
]
```

Markers — class const (полиморфизм через mixin). Cap — module const (соответствует `MAX_AUDIO_DIALOG_ITERATIONS`).

### 3.2. Pure helper

```python
def _handle_tt_music_rights_dialog(self, ui_xml: str) -> bool:
    """Detect и accept TT music rights confirmation dialog.

    Returns:
        True если dialog matched И кнопка «Опубликовать видео» успешно
        тапнута. False если markers не найдены ИЛИ кнопка не нашлась
        (caller интерпретирует False как "нет dialog'а" или "ошибка handle").
    """
    if not ui_xml:
        return False
    if not any(m in ui_xml for m in self._TT_MUSIC_RIGHTS_MARKERS):
        return False
    # 1. Persistence: проставить чекбокс если не отмечен
    checkbox_set = self._tick_unchecked_checkbox(
        ui_xml, self._TT_MUSIC_RIGHTS_CHECKBOX)
    # 2. Tap «Опубликовать видео» внутри диалога (exact, clickable)
    tapped = self.tap_element(
        ui_xml, self._TT_MUSIC_RIGHTS_BUTTON,
        exact=True, clickable_only=True)
    if tapped:
        self.log_event(
            'info',
            'TikTok: music rights dialog accepted',
            meta={'category': 'tt_music_rights_accepted',
                  'platform': self.platform,
                  'checkbox_set': checkbox_set,
                  'button_tapped': True})
    else:
        self.log_event(
            'warning',
            'TikTok: music rights dialog detected, accept button not found',
            meta={'category': 'tt_music_rights_button_not_found',
                  'platform': self.platform,
                  'checkbox_set': checkbox_set})
    return tapped
```

### 3.3. Checkbox helper

```python
def _tick_unchecked_checkbox(self, ui_xml: str,
                              text_candidates: List[str]) -> bool:
    """Tap по чекбоксу если он clickable=true И checked=false И text/desc
    matches one of candidates. Returns True если tap отправлен."""
    if not ui_xml:
        return False
    try:
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(ui_xml)
    except Exception:
        return False
    for n in root.iter('node'):
        if n.get('clickable') != 'true':
            continue
        if n.get('checked') != 'false':
            continue
        txt = (n.get('text', '') or n.get('content-desc', '')).strip()
        if not any(c in txt for c in text_candidates):
            continue
        bounds = n.get('bounds', '')
        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
        if not m:
            return False
        cx = (int(m.group(1)) + int(m.group(3))) // 2
        cy = (int(m.group(2)) + int(m.group(4))) // 2
        try:
            self.adb_tap(cx, cy)
            return True
        except Exception:
            return False
    return False
```

### 3.4. Wired в `publish_tiktok` wait_upload loop

В `publisher_tiktok.py::publish_tiktok`, **перед** `_tt_audio_markers` block (line ~538), **после** `_tt_notif_markers` block (line ~497-516), ВНУТРИ `else: overlay_streak = 0` ветки (когда TT активен — line ~471):

```python
# === Music rights confirmation dialog (новый TT UX 2026-05-10) ===
# Появляется ПОСЛЕ tap «Опубликовать» если видео имеет detected copyright
# music. User decision: auto-accept + persistence checkbox.
# Spec: docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md
if any(m in ui for m in self._TT_MUSIC_RIGHTS_MARKERS):
    if not hasattr(self, '_music_rights_iter'):
        self._music_rights_iter = 0
    self._music_rights_iter += 1
    if self._music_rights_iter > MAX_MUSIC_RIGHTS_ITERATIONS:
        log.error(f'  ❌ TikTok: music rights dialog stuck > '
                  f'{MAX_MUSIC_RIGHTS_ITERATIONS} итераций — fail')
        self.log_event(
            'error',
            f'tt_music_rights_stuck: dialog persists > {MAX_MUSIC_RIGHTS_ITERATIONS} iter',
            meta={'category': 'tt_music_rights_stuck',
                  'iterations': self._music_rights_iter,
                  'step': 'wait_upload',
                  'platform': self.platform})
        self.set_step('tt_music_rights_stuck')
        return False
    handled = self._handle_tt_music_rights_dialog(ui)
    log.info(f'  🎵 TikTok: music rights dialog (wait {wait}, '
             f'iter {self._music_rights_iter}/{MAX_MUSIC_RIGHTS_ITERATIONS}) '
             f'handled={handled}')
    time.sleep(2)
    continue
```

### 3.5. Точка вмешательства

Единственная: `publish_tiktok` метод в `publisher_tiktok.py`. Helpers — новые рядом с существующими TikTokMixin методами. Существующий код **не трогается**.

### 3.6. Порядок overlay handlers внутри loop

После изменения порядок такой (важно для anti-overlap):

1. `_tt_notif_markers` — закрыть post-publish notifications (уже success состояние)
2. **Music rights** ← новое
3. **UPLOAD_OK early check** (уже существующий — Phase 1.5)
4. `_tt_audio_markers` — audio dialog
5. `still_on_editor` re-tap

Music rights ДО UPLOAD_OK — потому что дилог появляется ДО публикации, а UPLOAD_OK matches feed-state. Если dialog overlays feed (race condition) — handle dialog first, UPLOAD_OK поймает на следующей итерации.

---

## 4. Тесты

Файл: `tests/test_publisher_tt_music_rights.py` (новый, 8 тестов).

### 4.1. Helper unit tests (5)

1. **test_handle_dialog_detected_taps_publish_video** — UI с marker «Подтвердить и опубликовать видео» + clickable node text='Опубликовать видео' → `tap_element` called с `(['Опубликовать видео', 'Publish video'], exact=True, clickable_only=True)`, returns True, info event logged
2. **test_handle_dialog_no_marker_returns_false_no_taps** — UI без marker → False сразу, no `tap_element` calls (guard)
3. **test_handle_dialog_ticks_unchecked_checkbox** — checkbox node `text='Я принимаю Подтверждение прав на использование музыки' checked='false' clickable='true' bounds='[100,2200][1000,2280]'` → `adb_tap` called с (550, 2240), then publish button. Meta `checkbox_set: True`
4. **test_handle_dialog_skips_already_checked_checkbox** — checkbox `checked='true'` → `adb_tap` НЕ зовётся для checkbox, но publish button tapped. Meta `checkbox_set: False`
5. **test_handle_dialog_button_not_found_logs_warning** — markers match, но «Опубликовать видео» отсутствует в UI → returns False, warning event `tt_music_rights_button_not_found` logged

### 4.2. Integration tests (2)

6. **test_loop_iteration_cap_fails_with_stuck_code** — `_music_rights_iter` доходит до 6 → error event `tt_music_rights_stuck` + `set_step('tt_music_rights_stuck')` + return False from publish. Cap value 5.
7. **test_loop_does_not_consume_upload_ok_state** — UI содержит 'Опубликовано' (UPLOAD_OK) и НЕ содержит music rights markers → handler returns False (не false-positive consume), main loop UPLOAD_OK check срабатывает на той же итерации

### 4.3. Regression (1)

8. **test_existing_audio_dialog_handler_independent** — UI matches только `_tt_audio_markers` (не music rights) → music rights handler returns False, audio dialog handler срабатывает (порядок handlers не ломает audio path)

---

## 5. Edge cases & defensive handling

| Случай | Поведение |
|---|---|
| `dump_ui` returns пустую строку | `_handle_tt_music_rights_dialog('')` → False сразу (guard); ладдер не triggers, main loop продолжает existing checks |
| Markers найдены но ни кнопка ни чекбокс не clickable | `tap_element` returns False; helper лог warning `tt_music_rights_button_not_found`, returns False; cap counter инкрементится; на 6-м iter — `tt_music_rights_stuck` |
| TT поменял лейбл «Опубликовать видео» → «Post» (только English) | EN markers в `_TT_MUSIC_RIGHTS_BUTTON` (`'Publish video'`) — но если лейбл поменялся на третий вариант, helper упадёт в `tt_music_rights_button_not_found`. Markers расширяются reactive в follow-up PR на основе live evidence |
| Dialog появился НЕ в wait_upload, а раньше (e.g. между tap «Опубликовать» и sleep(8)) | Не покрыто этим spec'ом. Текущее наблюдение — dialog появляется ПОСЛЕ tap, и 8s sleep + первый dump_ui успевают его поймать |
| Multiple dialog instances (camera + photos analog для IG Mode A) | Пока не наблюдается на TT. Если появится — каждая итерация loop'а handle одну инстанцию, до 5 раз |
| Race: tap «Опубликовать видео» внутри dialog'а попадает в момент перерисовки → tap игнорируется | Cap 5 iter × 2s loop sleep = до 10s grace; обычно достаточно |
| TT показал dialog, но клиент НЕ имеет prав (фейк-аккаунт TT, abusive content) | Auto-accept всё равно тапается; если TT откажет позже — другой error_code (tt_post_rejected, future) |

---

## 6. Telemetry

**Новые events:**

- `tt_music_rights_accepted` (info) — на каждый успешный handle. Meta:
  - `checkbox_set: bool` — был ли persistence checkbox проставлен на этом hit'е
  - `button_tapped: True`
  - `platform: 'TikTok'`
- `tt_music_rights_button_not_found` (warning) — markers match, кнопка не нашлась. Meta:
  - `checkbox_set: bool`
  - `platform: 'TikTok'`
- `tt_music_rights_stuck` (error) — cap exceeded. Final error_code; mirrors `tt_audio_dialog_stuck`. Meta:
  - `iterations: 6` (cap+1)
  - `step: 'wait_upload'`
  - `platform: 'TikTok'`

**Dashboard split (post-deploy triage):**

- `done AND events @> '[{"meta":{"category":"tt_music_rights_accepted"}}]'` — recovered tasks (метрика эффективности)
- `failed AND error_code='tt_music_rights_stuck'` — auto-accept не помог (escalation case)
- `failed AND error_code='tt_upload_confirmation_timeout' AND events @> '[{"meta":{"category":"tt_music_rights_accepted"}}]'` — handler сработал, но upload потом всё равно провалился (other root cause downstream)

**Decision criterion (24-48ч post-deploy):**

- `tt_music_rights_accepted` events / total TT publishes > 10% → music rights — действительно systemic, fix correct
- `tt_music_rights_stuck` > 0 → требуется markers expansion или другой strategy (alternative tap method)
- `tt_upload_confirmation_timeout` на #9 за 24ч должен упасть с 12 до < 3 (residual = другие причины)

---

## 7. Out of scope

- **Pre-Share probe** (Approach C): не нужен, sleep(8) + первый dump_ui уже buffer
- **Music rights detection в still_on_editor path** (Approach B): семантически dialog overlay, не editor stuck
- **Bypass dialog через app config / settings** (если есть «не показывать снова» в TT settings): требует session-level navigation, scope роста; persistence checkbox должен достичь того же эффекта
- **Расширение markers на третий язык** (zh/ko/ja): YAGNI, current accounts EN/RU
- **Telemetry для checkbox state перед tap** (`checkbox_initially_unchecked: bool` и т.д.): достаточно `checkbox_set` в success event
- **Vision fallback** (если markers не сработали): YAGNI, приоритет — прямой text/XML match

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Music rights dialog имеет другие лейблы кнопки на части TT-инстансов | EN+RU markers покрывают основное; reactive expansion на основе `tt_music_rights_button_not_found` events |
| `_tick_unchecked_checkbox` неправильно интерпретирует другой checkbox в UI (false positive) | Filter по `text` matches `_TT_MUSIC_RIGHTS_CHECKBOX` candidates — высокая специфичность |
| Persistence checkbox реально требует extra confirmation step (modal: «Запомнить выбор?») | Не наблюдается; если появится — будет отдельный handler (но скорее всего auto-accept всё равно достаточно для текущей публикации) |
| Cap 5 iter × 2s = 10s доп latency на edge case | Acceptable; baseline TT publish ~30-60s, 10s = ~15% overhead в worst case |
| Auto-accept music rights юридически некорректен (клиент не давал явного consent на этот dialog specifically) | User decision 2026-05-10: клиент уже дал consent через ToS использования сервиса, бот действует от имени клиента. Out of scope технического spec'а |

---

## 9. Acceptance criteria

1. Все 8 unit/integration тестов green
2. Существующий TT publish suite зелёный (`tests/test_publisher_tt_*.py`, `tests/test_publish_*tiktok*.py`) — no regression
3. Live verification: re-queue 1 known fail (e.g. 4488 clickpay_world через `UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE id=<qid>`) → ожидаем `tt_music_rights_accepted` event в новом publish_task + успешный post_url
4. Dashboard може различать recovered (`tt_music_rights_accepted`) vs stuck (`tt_music_rights_stuck`)
5. 24h post-deploy: `tt_upload_confirmation_timeout` на #9 < 3/24h (was 12)
6. Codex review (`codex review --uncommitted` после spec'а, потом после кода) применён ИЛИ задокументировано почему пропущен (per `feedback_codex_sandbox_broken.md`)

---

## 10. Связанные документы

- TT publish stabilization Phase 1+1.5+2: `docs/superpowers/specs/2026-05-08-tiktok-publish-stabilization-design.md`
- Audio dialog stuck pattern (analog cap mechanism): `publisher_tiktok.py::MAX_AUDIO_DIALOG_ITERATIONS`
- Memory: `project_tt_publish_phases_shipped.md` (TT Phase 1+1.5+2 done 2026-05-08)
- Memory: `feedback_codex_review_specs.md` (правило аудита спека)
- Memory: `feedback_codex_sandbox_broken.md` (известная проблема codex sandbox)
- Memory: `feedback_python_in_op_case_sensitive.md` (RU+EN markers, case)
- AI Unstuck evidence screenshot: `https://save.gengo.io/autowarm/screenshots/tiktok/task4488_unstuck_4488_1778417268.png` (saved local: `/tmp/tt_4488_unstuck_step1.png`)
