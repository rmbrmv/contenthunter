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

**Approach A** из 3 предложенных: handler в `wait_upload` loop рядом с `_tt_notif_markers` / `_tt_audio_markers`. Pure helper в TikTokMixin. **Returns True ТОЛЬКО если** structural detector сработал И strict-tap «Опубликовать видео» успешен (checkbox tick — best-effort, не влияет на return value). Caller делает `continue` **только при handled=True** — на False продолжает downstream handlers (audio dialog, still_on_editor re-tap, AI Unstuck).

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
# Codex round 2: title-EXACT-node как structural anchor (не substring).
# Body markers удалены — detector не использует их (body match слишком
# широкий, mistake-prone). Identity dialog'а = title-node + checkbox/button
# структура.
_TT_MUSIC_RIGHTS_TITLE_MARKERS = [
    'Подтвердить и опубликовать видео',
    'Confirm and publish video',
]
_TT_MUSIC_RIGHTS_BUTTON = ['Опубликовать видео', 'Publish video']
_TT_MUSIC_RIGHTS_CHECKBOX = [
    'Я принимаю Подтверждение прав на использование музыки',
    'I accept the Music Usage Rights Confirmation',
]
```

Markers — class const (полиморфизм через mixin). Cap — module const (соответствует `MAX_AUDIO_DIALOG_ITERATIONS`). **Title** — единственный structural identity anchor; checkbox/button — supporting structure для confirmation что это action-dialog а не info-banner.

### 3.2. Structured detection (anti-false-positive, button-may-be-disabled-safe)

**Codex round 1 finding #2:** plain substring match `'music usage rights' in ui` слишком широкий — может match copyright educational banner, music selector copy, link tooltip.

**Codex round 2 finding:** требование `clickable=true` для button небезопасно — если TT disable'ит «Опубликовать видео» до tick'а checkbox'а, detection вернёт False, checkbox не будет проставлен → infinite loop avoided через cap, но fix не сработает. Detection должен опираться на **title-node + checkbox-structure** (и то и другое присутствует до checkbox tick), а button strict-tap'ается ПОСЛЕ checkbox + re-dump.

```python
def _detect_tt_music_rights_dialog(self, ui_xml: str) -> bool:
    """Strict structural detector — TITLE node AND checkbox-or-button structure.

    Не требует button=clickable (TT может disable до acceptance). Требует:
    - parseable XML
    - node с text/desc EXACT-match одного из _TT_MUSIC_RIGHTS_TITLE_MARKERS
    - дополнительно: либо checkbox-node с music-rights label, либо
      publish-video button-node (clickable=any) — что-то из dialog-структуры
    """
    if not ui_xml:
        return False
    # Cheap pre-filter: title substring (fast bail-out)
    if not any(m in ui_xml for m in self._TT_MUSIC_RIGHTS_TITLE_MARKERS):
        return False
    try:
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(ui_xml)
    except Exception:
        return False
    has_title_node = False
    has_checkbox_or_button = False
    for n in root.iter('node'):
        txt = (n.get('text', '') or '').strip()
        desc = (n.get('content-desc', '') or '').strip()
        # Title node — exact match (parsed, не substring)
        if not has_title_node and (txt in self._TT_MUSIC_RIGHTS_TITLE_MARKERS
                                   or desc in self._TT_MUSIC_RIGHTS_TITLE_MARKERS):
            has_title_node = True
        # Checkbox-presence (label или CheckBox class) ИЛИ button (any clickable state)
        if not has_checkbox_or_button:
            if any(c in txt or c in desc for c in self._TT_MUSIC_RIGHTS_CHECKBOX):
                has_checkbox_or_button = True
            elif (txt in self._TT_MUSIC_RIGHTS_BUTTON
                  or desc in self._TT_MUSIC_RIGHTS_BUTTON):
                has_checkbox_or_button = True
            elif n.get('checkable') == 'true' or 'CheckBox' in n.get('class', ''):
                # generic checkbox node (не music-specific) — sufficient
                # only if title was already found
                if has_title_node:
                    has_checkbox_or_button = True
        if has_title_node and has_checkbox_or_button:
            return True
    return False
```

Detection теперь: title-node EXACT + (checkbox-label OR button-node OR generic-checkbox-with-title). Button НЕ обязан быть clickable на этом этапе — его strict-tap происходит в `_handle_*` после checkbox tick + re-dump.

### 3.3. Pure helper (handle)

```python
def _handle_tt_music_rights_dialog(self, ui_xml: str) -> bool:
    """Detect (через _detect_*) и accept TT music rights confirmation dialog.

    Returns:
        True ТОЛЬКО если dialog detected И кнопка «Опубликовать видео»
        успешно тапнута. False иначе (caller НЕ должен continue если False).
    """
    if not self._detect_tt_music_rights_dialog(ui_xml):
        return False
    # 1. Persistence: tick checkbox if unchecked (best-effort)
    checkbox_set = self._tick_tt_music_rights_checkbox(ui_xml)
    # 2. Если checkbox tapped — re-dump UI (Codex #6: button bounds могут
    #    сместиться, button может стать enabled, текст/clickable может
    #    переключиться). Без re-dump tap по stale coords — игнор.
    if checkbox_set:
        time.sleep(0.5)
        try:
            ui_xml = self.dump_ui() or ui_xml
        except Exception:
            pass  # best-effort; продолжаем со старым xml
    # 3. Strict tap «Опубликовать видео» (НЕ через tap_element — у него
    #    fallback find_element_bounds игнорирует exact/clickable_only,
    #    может тапнуть link «Подтверждение прав на использование музыки >»).
    tapped = self._strict_tap_clickable(ui_xml, self._TT_MUSIC_RIGHTS_BUTTON)
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

`_find_strict_clickable(ui_xml, candidates) -> Optional[(cx, cy)]` и `_strict_tap_clickable(ui_xml, candidates) -> bool` — новые helpers рядом с существующими XML-парсерами в `publisher_base.py` или `publisher_tiktok.py` (file scope обсуждается в plan'е). Логика: parse XML, для каждого node искать `clickable='true'` AND (`text` OR `content-desc`) **exact-equals** одному из candidates. Никакого fallback на regex/find_element_bounds.

### 3.4. Checkbox helper (handles label/checkbox split nodes)

**Codex finding #7:** Android UIAutomator часто разделяет checkbox и label на разные ноды (CheckBox node + sibling/parent TextView с лейблом). Помимо «label-is-checkbox» сценария, helper должен покрыть «label-near-checkbox» паттерн.

```python
def _tick_tt_music_rights_checkbox(self, ui_xml: str) -> bool:
    """Tap по unchecked music-rights checkbox.

    Покрывает 2 паттерна:
      A) Single node: clickable=true AND checked=false AND text/desc
         matches '_TT_MUSIC_RIGHTS_CHECKBOX' candidates.
      B) Split: CheckBox node (class=android.widget.CheckBox или
         checkable=true) с checked=false, а лейбл — в сиблинге/parent'е
         с matching text. Tap по checkbox bounds (НЕ по label).

    Returns True если tap отправлен. False if уже checked / нет нодов.
    """
    if not ui_xml:
        return False
    try:
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(ui_xml)
    except Exception:
        return False
    # Pattern A: single self-labeled checkbox
    for n in root.iter('node'):
        if n.get('clickable') != 'true' or n.get('checked') != 'false':
            continue
        txt = (n.get('text', '') or n.get('content-desc', '')).strip()
        if any(c in txt for c in self._TT_MUSIC_RIGHTS_CHECKBOX):
            return self._tap_node_bounds(n)
    # Pattern B: separate checkbox + nearby label
    # Найти все checkable=true|class=CheckBox unchecked nodes,
    # найти label-node с music-rights текстом, выбрать checkbox
    # с минимальным расстоянием центра bounds к центру label.
    cb_nodes = [n for n in root.iter('node')
                if (n.get('checkable') == 'true' or
                    'CheckBox' in n.get('class', ''))
                and n.get('checked') == 'false']
    label_nodes = []
    for n in root.iter('node'):
        txt = (n.get('text', '') or n.get('content-desc', '')).strip()
        if any(c in txt for c in self._TT_MUSIC_RIGHTS_CHECKBOX):
            label_nodes.append(n)
    if not cb_nodes or not label_nodes:
        return False
    # Берём label с самым «обычным» bounds + ближайший checkbox
    nearest = self._nearest_checkbox_to_label(cb_nodes, label_nodes)
    if nearest is None:
        return False
    return self._tap_node_bounds(nearest)
```

`_tap_node_bounds(n) -> bool` и `_nearest_checkbox_to_label(cbs, labels) -> Optional[node]` — внутренние helpers (parse bounds, compute center, return node с минимальной L2 distance). Реализация — детали plan'а.

**Notes:**
- `n.get('checked') != 'false'` пропускает уже отмеченный checkbox (idempotent на повторных hit'ах).
- Если ни Pattern A, ни Pattern B не нашли → return False (best-effort, не error). Persistence не критична для текущего publish — главное accept button сработает.

### 3.5. Wired в `publish_tiktok` wait_upload loop

**Codex finding #4:** Reset `_music_rights_iter` в начале `publish_tiktok`, не полагаться на hasattr-check (publisher instance может переиспользоваться → counter переползёт в next publish и failnет на ранней итерации).

В **начале** `publish_tiktok` (после set_step но до основного flow):

```python
# Reset per-publish counters (Codex feedback 2026-05-10).
self._music_rights_iter = 0
```

Затем в `wait_upload` loop, **ПОСЛЕ** UPLOAD_OK early check (line ~518-533), **ПЕРЕД** `_tt_audio_markers` block (line ~538):

```python
# === Music rights confirmation dialog (новый TT UX 2026-05-10) ===
# Появляется ПОСЛЕ tap «Опубликовать» при detected copyright music.
# User decision: auto-accept + persistence checkbox.
# Spec: docs/superpowers/specs/2026-05-10-tt-music-rights-dialog-design.md
if self._detect_tt_music_rights_dialog(ui):
    self._music_rights_iter += 1
    if self._music_rights_iter > MAX_MUSIC_RIGHTS_ITERATIONS:
        log.error(f'  ❌ TikTok: music rights dialog stuck > '
                  f'{MAX_MUSIC_RIGHTS_ITERATIONS} итераций — fail')
        self.log_event(
            'error',
            f'tt_music_rights_stuck: dialog persists > {MAX_MUSIC_RIGHTS_ITERATIONS} iter',
            meta={'category': 'tt_music_rights_stuck',
                  'iterations': self._music_rights_iter,
                  'step': 'tt_5_music_rights_stuck',
                  'platform': self.platform})
        self.set_step('tt_5_music_rights_stuck')
        return False
    handled = self._handle_tt_music_rights_dialog(ui)
    log.info(f'  🎵 TikTok: music rights dialog (wait {wait}, '
             f'iter {self._music_rights_iter}/{MAX_MUSIC_RIGHTS_ITERATIONS}) '
             f'handled={handled}')
    if handled:
        time.sleep(2)
        continue  # Codex #1: continue ТОЛЬКО при успешном handle
    # handled=False — markers were strict-matched но button tap failed.
    # НЕ continue — пусть существующие downstream handlers (audio,
    # still_on_editor re-tap, AI Unstuck) попробуют resolve.
    # Counter уже инкрементирован → защита от infinite loop.
```

### 3.6. set_step и kernel mapping

**Codex finding #9:** `tt_music_rights_stuck` должен быть mapped в `_SWITCHER_STEP_TO_CATEGORY` (`publisher_kernel.py:96-99`), иначе dashboard не увидит canonical error_code.

Изменение в `publisher_kernel.py` рядом с существующим `'tt_5_audio_dialog_stuck': 'tt_audio_dialog_stuck',`:

```python
# [2026-05-10] Music rights confirmation dialog stuck — TT UX rollout.
# Triggered when music-rights detector runs >MAX_MUSIC_RIGHTS_ITERATIONS
# без passing button tap (publisher_tiktok.py music-rights branch).
'tt_5_music_rights_stuck': 'tt_music_rights_stuck',
```

`set_step('tt_5_music_rights_stuck')` (с префиксом `tt_5_` per существующая convention) → kernel mapping в canonical category `tt_music_rights_stuck`.

### 3.7. Точка вмешательства

Cross-file:
- `publisher_tiktok.py` — основной handler (constants, helpers, wait_upload integration)
- `publisher_kernel.py` — одна строчка в `_SWITCHER_STEP_TO_CATEGORY`
- (опционально) `publisher_base.py` — strict tap helpers если решено разместить там (детали в plan'е)

### 3.8. Порядок overlay handlers внутри loop

**Codex finding #3:** Сохраняем существующий invariant Phase 1.5 — UPLOAD_OK FIRST. Музыкальный диалог — только после UPLOAD_OK check'а:

1. `_tt_notif_markers` — post-publish notifications dismiss
2. **UPLOAD_OK early check** — success state poll (Phase 1.5 invariant)
3. **Music rights** ← новое (после UPLOAD_OK; structural detection защищает от false-positive consume success state)
4. `_tt_audio_markers` — audio dialog
5. `still_on_editor` re-tap

Strict structural detection из 3.2 (требование button-node) делает невозможным false-match feed-content. Если post-success screen случайно содержит маркеры (банер с copyright info), без clickable button «Опубликовать видео» детектор вернёт False, UPLOAD_OK на следующей итерации поймает success.

---

## 4. Тесты

Файл: `tests/test_publisher_tt_music_rights.py` (новый, 18 тестов).

### 4.1. Detector tests (4)

1. **test_detect_returns_true_when_title_and_button_present** — UI с title-node EXACT «Подтвердить и опубликовать видео» + button-node «Опубликовать видео» (clickable=any) → True
2. **test_detect_returns_true_when_title_and_disabled_button** — same UI но button `clickable='false'` → True (button может быть disabled до checkbox tick — round 2 fix)
3. **test_detect_returns_false_when_only_body_substring_no_title_node** — UI содержит «music usage rights» в body/link (substring), но title как EXACT-node отсутствует → False (body substring не идентифицирует dialog без title-node)
4. **test_detect_returns_false_no_marker** — Empty UI / UI без title markers → False сразу

### 4.2. Handle/checkbox helper tests (5)

4. **test_handle_taps_publish_via_strict_helper** — detected dialog → `_strict_tap_clickable` called с (`['Опубликовать видео', 'Publish video']`), returns True, info event `tt_music_rights_accepted` logged. **Не использует** `tap_element` (Codex #5).
5. **test_handle_redumps_ui_after_checkbox_tick** — checkbox tap → `dump_ui` зовётся **до** button tap. Verify через mock call ordering (Codex #6).
6. **test_checkbox_pattern_a_self_labeled** — node `text='Я принимаю Подтверждение прав на использование музыки' checked='false' clickable='true' bounds='[100,2200][1000,2280]'` → `adb_tap(550, 2240)`. Meta `checkbox_set: True`
7. **test_checkbox_pattern_b_split_label_and_checkbox** — отдельная нода `class='android.widget.CheckBox' checked='false' clickable='true' bounds='[40,2200][120,2280]'` + sibling-label TextView с music-rights текстом → tap по checkbox bounds (80, 2240), не по label (Codex #7)
8. **test_handle_button_not_found_returns_false_no_continue** — detected=True (title+button оба есть для detector pre-check) но `_strict_tap_clickable` failed (race: button исчез между detect и tap) → returns False, warning event `tt_music_rights_button_not_found` logged

### 4.3. Loop integration tests (3)

9. **test_loop_continues_only_on_handled_true** — handler returns False → loop **НЕ** делает `continue` (downstream handlers получают шанс). Иначе — `continue`. Codex #1.
10. **test_loop_iteration_cap_fails_with_stuck_code** — `_music_rights_iter` доходит до 6 → error event `tt_music_rights_stuck` + `set_step('tt_5_music_rights_stuck')` + return False from publish.
11. **test_per_publish_counter_reset** — second `publish_tiktok()` call на same publisher instance → `_music_rights_iter == 0` в начале (не наследует из prev publish). Codex #4.

### 4.4. Ordering & regression tests (3)

12. **test_upload_ok_check_runs_before_music_rights** — UI marker'ы UPLOAD_OK ('Опубликовано') + music rights — UPLOAD_OK выигрывает (early break), music rights handler **не** вызывается на той же итерации. Codex round 1 #3 invariant.
13. **test_existing_audio_dialog_handler_independent** — UI matches только `_tt_audio_markers` (не music rights) → music rights detector returns False, audio dialog handler срабатывает. Не ломает Phase 1.5 path.
14. **test_kernel_mapping_includes_music_rights** — `from publisher_kernel import _SWITCHER_STEP_TO_CATEGORY` → assert `_SWITCHER_STEP_TO_CATEGORY['tt_5_music_rights_stuck'] == 'tt_music_rights_stuck'`. Codex round 1 #9.

### 4.5. Strict tap helper direct tests (4) — Codex round 2

15. **test_strict_tap_exact_text_match** — node `text='Опубликовать видео' clickable='true'` → tap по center bounds, returns True
16. **test_strict_tap_exact_desc_match** — node `content-desc='Publish video' clickable='true'` (text empty) → tap по center bounds, returns True
17. **test_strict_tap_rejects_substring** — node `text='Опубликовать видео и поделиться' clickable='true'` (substring matches '_TT_MUSIC_RIGHTS_BUTTON' value but не exact) → returns False, no tap
18. **test_strict_tap_rejects_non_clickable** — node `text='Опубликовать видео' clickable='false'` → returns False, no tap (НЕ fall through на find_element_bounds vs `tap_element` baseline behavior)

---

## 5. Edge cases & defensive handling

| Случай | Поведение |
|---|---|
| `dump_ui` returns пустую строку | `_detect_tt_music_rights_dialog('')` → False сразу (guard); main loop продолжает existing checks |
| Title marker substring матчится но title как EXACT-node + checkbox/button-структура отсутствуют | `_detect_*` returns False (structural check — round 2 fix); handler не вызывается, downstream продолжает |
| Title-node EXACT + button-node disabled (clickable=false) — TT enable'ит после checkbox tick | `_detect_*` returns True (button clickability игнорируется на detection — round 2 fix); handler ticks checkbox → re-dump → strict-tap button (теперь enabled) |
| Detected, но button tap failed (race: dialog dismissed между detect и tap) | helper returns False, warning event logged. Loop **НЕ** continues — downstream handlers получают chance (Codex #1). Counter инкрементирован → защита от infinite loop |
| TT поменял лейбл «Опубликовать видео» → «Post» (только English или новый текст) | EN markers (`'Publish video'`) в candidates list. Если лейбл новый — `tt_music_rights_button_not_found` event. Reactive expansion в follow-up PR на основе live evidence |
| Persistence checkbox split: `class='android.widget.CheckBox'` + sibling label | Pattern B в `_tick_tt_music_rights_checkbox` (Codex #7) — match по checkable/CheckBox class + nearest label, tap по checkbox bounds |
| Dialog появился до wait_upload (e.g. между tap «Опубликовать» и sleep(8)) | sleep(8) + первый dump_ui в loop iter 0 ловят dialog. Pre-Share probe не нужен (Approach C отброшен) |
| Multiple dialog instances (race: дилог пересоздаётся) | Cap=5 покрывает; на 6-м iter — `tt_music_rights_stuck` |
| Race: button tap по stale coords (checkbox redraw сместил button) | After `checkbox_set=True` → `time.sleep(0.5) + dump_ui()` (Codex #6) перед button tap |
| TT показал dialog, но клиент НЕ имеет prав (фейк-аккаунт, abusive content) | Auto-accept всё равно тапается; если TT откажет позже — другой error_code (downstream, не наша зона) |
| Publisher instance переиспользован между tasks (long-lived) | Counter reset в начале `publish_tiktok` (Codex #4) — `self._music_rights_iter = 0` |

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
  - `step: 'tt_5_music_rights_stuck'` (per kernel mapping convention; canonicalized в `tt_music_rights_stuck`)
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
| Music rights dialog имеет другие лейблы кнопки на части TT-инстансов | EN+RU markers покрывают основное; structural check + `tt_music_rights_button_not_found` event сигнализирует о расширении (reactive PR) |
| Markers дают false-positive на feed/banner | Codex round 1+2: structural detector требует title-node EXACT + (checkbox-label OR button-node OR generic-checkable-with-title). Substring без structural anchor → dialog не считается detected |
| Checkbox реально использует Switch/ToggleButton класс, не CheckBox | Pattern B покрывает любой `checkable=true` node, не только CheckBox class |
| Cap 5 iter × ~3s loop interval = 15s доп latency на edge case | Acceptable; baseline TT publish ~30-60s, 15s = ~25% worst-case overhead. Cap критичен для anti-infinite-loop |
| Auto-accept music rights юридически некорректен | User decision 2026-05-10: клиент дал consent через ToS использования сервиса; бот действует от имени клиента. Out of scope технического spec'а |
| Detection строгая → пропустит variant dialog (e.g. без чекбокса, только button) | Acceptable: false-negative безопаснее false-positive (timeout fail vs ложный consume success state). Reactive expansion при live evidence |
| Race: button tapped, но TT не зарегистрировал → loop iter 2 пытается снова | Detector check на следующей итерации поймёт что dialog исчез → handler не вызывается → cap не исчерпывается. Worst case — button был tapped дважды (TT идемпотентно для повторного tap «Опубликовать видео») |

---

## 9. Acceptance criteria

1. Все 18 unit/integration тестов green
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
