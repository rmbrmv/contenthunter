# IG Share retry Tier 2 — long-press escalation ladder (design spec)

**Дата:** 2026-05-09
**Sub-project:** P1.1 IG post-switch regressions — Tier 2 escalation
**Репо:** `autowarm-testbench` (auto-pushed в `GenGo2/delivery-contenthunter`)
**Триггер:** Tier 1 (commit `b89b694`, 2026-05-08 17:52 UTC) детектит editor-stuck и делает 2 re-tap'а через `tap_element` с fail-fast `ig_share_tap_no_progress`. Per Tier 1 spec section "Расширенный fix (Tier 2)" — escalation через alternative tap method ladder.
**Live evidence:** post Tier 1 deploy + закрытие MediaStore outage (commits `2a2ebb8`+`14570a1`, 2026-05-09 14:55 UTC) re-queue probe task #4410 (clickpay_me, IG) → `ig_share_tap_no_progress`. Подтверждает что Tier 1 fail-fast срабатывает на реальных данных, и нужен следующий escalation-шаг.

---

## 1. Контекст

### 1.1. Состояние pipeline

После 2 фикcов 2026-05-09:
- MediaStore double-query check работает на Android 15 (cmd shape + filename basename)
- Tier 1 IG share retry активен в проде

**Live evidence Tier 1 effectiveness (7 дней, 2026-05-04→11):**
- `ig_share_retry` events: **12** (Tier 1 actual taps)
- Unique IG tasks где Tier 1 fired: **6** (2 retry events per task)
- Из них `status=done`: **0**
- Из них `status=failed`: **6**

**Tier 1 retry rescue rate: 0/6 = 0%.** Zero-duration tap-retry не помогает в этом scenario'ии — strong justification для Tier 2 long-press. Sample достаточен для решения mode-agnostic Tier 2.

### 1.2. Что Tier 1 делает сейчас

`publisher_base.py::_wait_instagram_upload`, после iter0 diag:

```
1. Проверка _is_ig_editor_still_visible(iter0_ui_xml)
2. Если True (editor stuck):
   for retry_n in 1..2:
     sleep 3
     dump_ui → если editor gone → progressed=True, break
     tap_element(['Поделиться','Share','Опубликовать'], clickable_only=True)
     log_event ig_share_retry
     sleep 2
3. Если retry exhausted без progress:
   _last_push_err = ig_share_tap_no_progress
   return False
```

Tap метод — обычный `input tap cx cy` (zero-duration touch).

### 1.3. Гипотеза почему Tier 1 не покрывает 100%

- **B.1 race condition** — editor layout не финализирован к моменту tap'а; повторный обычный tap случается в том же transient state
- **B.2 anti-bot heuristic** — IG silently игнорирует synthetic taps c подозрительными timing/duration сигнатурами; повторный обычный tap имеет ту же сигнатуру → также игнорируется
- **B.3 long caption layout shift** — caption_input auto-expand двигает Share button bounds; обычный tap по stale координатам также промахивается

Все 3 sub-причины могут адресоваться **non-zero-duration tap** в одной точке (long-press swipe).

---

## 2. Approach

User decision (brainstorming 2026-05-09):
- **Mode-agnostic Tier 2** (опция А из 4)
- **In-place ladder после Tier 1** (без replace, без external re-queue)
- **Single new method**: long-press swipe (sendevent / KEYCODE_DPAD / re-open camera — отложены)
- **2 attempts × 200ms hold**

Альтернативы рассмотрены и отклонены:
- *Replace Tier 1 ladder'ом* — теряем дешёвый fast-path (zero-duration retry часто хватает для B.1 race)
- *External re-queue с флагом alternative-tap* — billing/idempotency complexity без выгоды для in-place
- *sendevent ladder rung* — высокая сложность (per-device input event mapping), нет evidence что нужно
- *Re-open Reels camera (full restart)* — 60-90s стоимость, риск двойной публикации

---

## 3. Архитектура

### 3.1. Instance helper в `publisher_instagram.py`

> **Codex round 1 fix (P3.1 + P1.3):** Helper не «pure» (зовёт `self.adb`); переименовано в «instance helper». Файл расположения — `publisher_instagram.py` (рядом с `_is_ig_editor_still_visible`:400 и `_wait_instagram_upload`:1850), не `publisher_base.py` как в v1.

```python
def _long_press_share_button(self, ui_xml: str, hold_ms: int = 200) -> bool:
    """Найти clickable id/share_button в ui_xml и сделать long-press tap
    через `input swipe cx cy cx cy <hold_ms>`.

    Long-press на одной точке (start==end) интерпретируется Android как
    DOWN→hold(hold_ms)→UP, что:
      - даёт layout время финализироваться (B.1 race / B.3 caption-shift)
      - не выглядит как zero-duration synthetic tap (B.2 anti-bot signature)

    hold_ms=200 — сладкое место: достаточно для timing, ниже long-press
    menu threshold (~500ms на Android default theme) → context menu не
    триггерится.

    Returns:
        True если Share button найден и swipe-команда отправлена;
        False если button нет в dump (editor mог измениться) — caller
        обрабатывает next attempt / fall-through.
    """
    if not ui_xml:
        return False
    try:
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(ui_xml)
    except Exception:
        return False
    for n in root.iter('node'):
        rid = n.get('resource-id', '')
        if rid.endswith(':id/share_button') and n.get('clickable') == 'true':
            bounds = n.get('bounds', '')
            # bounds формат "[x1,y1][x2,y2]"
            m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
            if not m:
                return False
            x1, y1, x2, y2 = (int(m.group(i)) for i in (1, 2, 3, 4))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            try:
                self.adb(f'input swipe {cx} {cy} {cx} {cy} {hold_ms}')
                return True
            except Exception:
                return False
    return False
```

Регекс bounds — копия паттерна из `tap_element`. resource-id endswith — копия логики `_is_ig_editor_still_visible` для consistency.

### 3.2. Tier 2 ladder block

В `_wait_instagram_upload`, **сразу после** Tier 1 retry-блока. Tier 1 заканчивается на:

```python
# Tier 1 (publisher_instagram.py:1906-1922)
if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
    self.log_event('error', '...', meta={'category': 'ig_share_tap_no_progress', ...})
    self._save_debug_artifacts('instagram_share_no_progress')
    share_no_progress = True
...
if share_no_progress:
    return False
```

**Codex round 1 critical fixes:**
- ❗ P1.1 (`pass` ничего не делает): убрана ветка `if tier2_progressed: pass` — управление возвращается в естественный flow (после блока — main wait loop) через `break` из цикла без явного маркера.
- ❗ P1.2 (`_last_push_err` mismatch): Tier 1 **не ставит** `_last_push_err` для этого пути (verified в `publisher_instagram.py:1907-1922`). Tier 2 тоже не ставит. error_code будет вычислен post-hoc из `events.meta.category` (per `feedback_publisher_error_code_misleading.md`).
- ❗ P2.1 (`tier2_button_not_found` mis-classify): теперь counter `tier2_button_not_found_count`; meta flag ставится только когда **все** attempts не нашли button.

Tier 2 ladder заменяет однократный `if share_no_progress: return False`:

```python
# Spec: docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md
TIER2_LP_ATTEMPTS = 2
TIER2_LP_HOLD_MS = 200
TIER2_LP_PRE_DELAY_S = 3
TIER2_LP_POST_DELAY_S = 2

if share_no_progress:
    # === Tier 2 long-press escalation ===
    tier2_progressed = False
    tier2_button_not_found_count = 0
    long_press_sent_count = 0  # Codex round 4 P2 fix: считает РЕАЛЬНО отправленные swipe,
                               # не вход в attempt. Используется для attempts_used в meta.
    for lp_attempt in range(1, TIER2_LP_ATTEMPTS + 1):
        time.sleep(TIER2_LP_PRE_DELAY_S)
        lp_ui = self.dump_ui()
        if not self._is_ig_editor_still_visible(lp_ui):
            tier2_progressed = True
            # Codex round 3 P2.3 fix: разделить «editor пропал без нашего тапа» от
            # «long-press помог». long_press_sent_count=0 = первый сценарий.
            if long_press_sent_count == 0:
                category = 'ig_share_progressed_pre_long_press'
            else:
                category = 'ig_share_long_press_progressed'
            self.log_event(
                'info',
                f'Instagram: Share PROGRESSED before attempt {lp_attempt} (long_press_sent={long_press_sent_count})',
                meta={'category': category,
                      'platform': self.platform,
                      'step': 'wait_upload',
                      'attempts_used': long_press_sent_count,
                      'hold_ms': TIER2_LP_HOLD_MS},
            )
            break
        if not self._long_press_share_button(lp_ui, hold_ms=TIER2_LP_HOLD_MS):
            tier2_button_not_found_count += 1
            # button gone — продолжаем next attempt с новым dump (НЕ инкрементируем long_press_sent_count)
            continue
        long_press_sent_count += 1
        self.log_event(
            'info',
            f'Instagram: long-press Share retry {lp_attempt}',
            meta={'category': 'ig_share_long_press_retry',
                  'platform': self.platform,
                  'step': 'wait_upload',
                  'attempt': lp_attempt,
                  'hold_ms': TIER2_LP_HOLD_MS},
        )
        time.sleep(TIER2_LP_POST_DELAY_S)

    # P1.1 round 2 fix: post-loop final progress check.
    # Без этого финальный (N-й) long-press attempt никогда не проверяется на
    # progressed — даже если он сработал, цикл выходит и мы летим в fail.
    if not tier2_progressed:
        final_ui = self.dump_ui()
        if not self._is_ig_editor_still_visible(final_ui):
            tier2_progressed = True
            # Codex round 4 P2 fix: категория зависит от ФАКТА long-press, не от вход в loop.
            # Если все attempts были button_not_found (long_press_sent_count=0)
            # но editor пропал ПОСЛЕ loop'а — это auto-recovery, не Tier 2 заслуга.
            if long_press_sent_count == 0:
                category = 'ig_share_progressed_pre_long_press'
            else:
                category = 'ig_share_long_press_progressed'
            self.log_event(
                'info',
                f'Instagram: Share PROGRESSED post-loop (long_press_sent={long_press_sent_count})',
                meta={'category': category,
                      'platform': self.platform,
                      'step': 'wait_upload',
                      'attempts_used': long_press_sent_count,
                      'hold_ms': TIER2_LP_HOLD_MS},
            )

    if not tier2_progressed:
        err_meta = {
            'category': 'ig_share_tap_no_progress',
            'platform': self.platform,
            'step': 'wait_upload',
            'retries_exhausted': 2,        # Tier 1 (preserve существующий ключ)
            'tier2_attempted': True,
            'lp_attempts': TIER2_LP_ATTEMPTS,
            'long_press_sent_count': long_press_sent_count,
            'hold_ms': TIER2_LP_HOLD_MS,
        }
        # P2.1 round 1 fix: flag только если ВСЕ attempts не нашли button
        if tier2_button_not_found_count == TIER2_LP_ATTEMPTS:
            err_meta['tier2_button_not_found'] = True
        self.log_event(
            'error',
            'Instagram: Tier 2 long-press exhausted — abort',
            meta=err_meta,
        )
        return False
    # tier2_progressed: fall through в existing main wait loop ниже
```

**Codex round 2 P2.1 mitigation — Tier 1 pre-Tier-2 error event:**

Tier 1 currently emits `error` `ig_share_tap_no_progress` BEFORE Tier 2 ladder runs (см. `publisher_instagram.py:1907`). Если Tier 2 progressed — этот event остаётся в `events.jsonb` и может сбить event-only triage.

**Mitigation (1-line Tier 1 modification, в scope этого spec'а):**

В `publisher_instagram.py:1907`, изменить:
```python
# Было:
self.log_event('error', 'Instagram: Share tap не прогрессировал после retries',
               meta={'category': 'ig_share_tap_no_progress', ...})
# Стало:
self.log_event('warning', 'Instagram: Tier 1 Share retries exhausted — escalating to Tier 2',
               meta={'category': 'ig_share_tier1_exhausted',
                     'platform': self.platform,
                     'step': 'wait_upload',
                     'retries_exhausted': 2})
```

Финальный `error` `ig_share_tap_no_progress` теперь эмитится **только** в Tier 2 fail-блоке. Семантика error_code улучшается: post-deploy `ig_share_tap_no_progress` означает «Tier 1 + Tier 2 оба исчерпаны», pre-deploy означало «Tier 1 исчерпан». Это легитимный semantic-rename + одно-строчная правка Tier 1.

**Triage импликации:** dashboards SQL из §6 остаются valid (фильтр по error_code + tier2_attempted=true). Pre-Tier-2 deploy данных хвост (raw error events with `ig_share_tap_no_progress`) до 2026-05-11 остаётся в исторических данных, разделим по `started_at` cutoff.

**Замечание (после round 2 Tier 1 mod):** Tier 1 final emit downgrade'нут — он эмитит `warning level='warning', category='ig_share_tier1_exhausted'`. Tier 2 fail эмитит `error level='error', category='ig_share_tap_no_progress'` (единственное место в новом коде, где эта канонічна категория появляется). `_set_error_code_from_events` post-deploy получит error_code = ig_share_tap_no_progress только когда Tier 1+Tier 2 оба исчерпаны. Дашборд читает meta с `tier2_attempted=True` для split (см. §6).

### 3.3. Точки вмешательства

Файл — `publisher_instagram.py` (NOT `publisher_base.py` — Codex round 1 fix P1.3). Изменения:

1. **`_long_press_share_button` (новый)** — instance helper рядом с `_is_ig_editor_still_visible:400`.
2. **`_wait_instagram_upload:1850`** — Tier 2 ladder wrap'ит существующий `if share_no_progress: return False` block (см. §3.2).
3. **`_wait_instagram_upload:1907`** — Tier 1 final emit меняется с `level='error', category='ig_share_tap_no_progress'` на `level='warning', category='ig_share_tier1_exhausted'` (Codex round 2 P2.1 mitigation; cm. §3.2 footer).

### 3.4. Время escalation

| Шаг | Latency |
|---|---|
| Tier 1 retry attempts (existing) | ~10s (2 × (3s pre + 2s post)) |
| Tier 2 attempt 1 | ~5.2s (3s pre + dump_ui ~1s + swipe 0.2s + 2s post) или ~4s (если button gone, без swipe/post) |
| Tier 2 attempt 2 | ~5.2s |
| **Total escalation budget** | ~20.4s до fail-fast |

Main 30-iter wait loop **остаётся** в случае Tier 2 progressed → даёт ещё ≥60s на upload completion. Бюджет приемлем — IG fail-fast ранее был после Tier 1 ~10s, теперь ~20s; уменьшение throughput незначительно, поскольку fails — sub-1% от total.

---

## 4. Тесты

Файл: `tests/test_ig_share_tier2.py` (новый) или extension в `tests/test_ig_share_retry.py` если существует.

### 4.1. Helper unit tests (4)

1. **test_long_press_helper_cmd_shape** — UI с `id/share_button bounds=[563,2025][1035,2149] clickable=true` → `_long_press_share_button(ui)` зовёт `self.adb('input swipe 799 2087 799 2087 200')`. Assertion на cmd-string match.
2. **test_long_press_helper_returns_true_on_success** — same scenario → returns True.
3. **test_long_press_helper_returns_false_no_button** — UI без share_button → returns False, `self.adb` не зовётся.
4. **test_long_press_helper_returns_false_malformed_bounds** — share_button присутствует, но bounds bad-format → returns False, no adb call.

### 4.2. Tier 2 ladder behavior tests (6)

5. **test_tier2_progressed_on_attempt_1** — `_is_ig_editor_still_visible` returns [True (Tier 1 baseline), True×2 (Tier 1 retries fail), True (Tier 1 final check → share_no_progress=True), False (Tier 2 pre-attempt-1 check)] → tier2_progressed на attempt 1 pre-check; `ig_share_progressed_pre_long_press` info event с `attempts_used=0`; main wait loop entered. **NOTE:** Эта ветка означает «Tier 2 даже не успел tap'нуть — editor disappeared между Tier 1 fail и Tier 2 ladder entry» — НЕ заслуга long-press, отдельная категория (Codex round 3 P2.3 fix).
6. **test_tier2_progressed_on_attempt_2_precheck** — editor visible на attempt 1 pre-check, не visible на attempt 2 pre-check → tier2_progressed; `attempts_used=1`.
7. **test_tier2_progressed_on_postloop_check** — editor visible на всех pre-checks attempt 1+2, не visible на final post-loop check → tier2_progressed; `attempts_used=2` (P1.1 round 2 fix coverage).
8. **test_tier2_exhausted_fail** — editor visible везде (включая post-loop) → `ig_share_tap_no_progress` error event с `tier2_attempted=True, lp_attempts=2, tier2_attempts_used=2, hold_ms=200, step='wait_upload', retries_exhausted=2`. **`_last_push_err` НЕ ставится** (consistent с Tier 1, который тоже не ставит — verified `publisher_instagram.py:1907-1922`).
9. **test_tier2_button_not_found_all** — `_long_press_share_button` returns False на ВСЕХ 2 attempts → fail с `tier2_button_not_found=True` в meta.
10. **test_tier2_button_not_found_partial** — `_long_press_share_button` returns False на attempt 1, True на attempt 2 → `tier2_button_not_found` НЕ в meta (Codex round 1 P2.1 fix coverage).

### 4.3. Regression tests (2)

11. **test_tier1_success_skips_tier2** — Tier 1 retry-1 progresses → `_long_press_share_button` НЕ зовётся (`stub.adb` not called с `input swipe`-pattern). Защита: Tier 2 не запускается когда не нужен.
12. **test_no_stuck_skips_both_tiers** — `_is_ig_editor_still_visible` returns False сразу после iter0 → ни Tier 1 ни Tier 2 не invoked, main wait loop сразу.

### 4.4. Tier 1 telemetry mod regression (1)

13. **test_tier1_exhausted_emits_warning_not_error** — после Codex round 2 P2.1 mitigation Tier 1 final emit стал `warning` с `category=ig_share_tier1_exhausted`. Тест проверяет: при share_no_progress event[level]='warning' AND meta.category='ig_share_tier1_exhausted' (NOT 'ig_share_tap_no_progress'). Final `ig_share_tap_no_progress` теперь приходит только из Tier 2 fail.

**Total: 4 + 6 + 2 + 1 = 13 tests.**

---

## 5. Edge cases & defensive handling

| Случай | Поведение |
|---|---|
| Share button bounds исчезли в Tier 2 dump | `_long_press_share_button` returns False; ladder продолжает next attempt с новым dump_ui; если на всех attempt'ах False → fail-fast с `tier2_button_not_found=True` (отличает «tap послан и не сработал» от «нечего тапнуть») |
| `adb shell input swipe` timeout / exception | Swallowed внутри helper, returns False; ladder продолжает (best-effort, как Tier 1) |
| `dump_ui` returns пустую строку | `_is_ig_editor_still_visible('')` → False (existing); ladder ошибочно решит progressed → upload main loop поймает реальный timeout как `ig_upload_confirmation_timeout`. Acceptable trade-off: dump fails редки, false-positive прогрессирования ведёт к timeout, не к ложному success |
| 200ms hold случайно открыл context menu | Не должно (200 < ~500ms threshold), но если evidence покажет — снизим до 150ms или добавим 1-2px diagonal jitter в follow-up PR |
| Tier 2 progressed но main loop timeout | Existing flow: `ig_upload_confirmation_timeout` — отдельный error_code, не путается с Tier 2 |

---

## 6. Telemetry

**Новые info events:**
- `ig_share_long_press_retry` — per attempt (фиксирует long-press fired). meta: `attempt`, `hold_ms`, `platform`.
- `ig_share_long_press_progressed` — успех ПОСЛЕ хотя бы одного long-press (attempts_used ≥ 1). meta: `attempts_used`, `hold_ms`, `platform`. **Это реальная заслуга long-press.**
- `ig_share_progressed_pre_long_press` — editor исчез ДО первого long-press (attempts_used = 0). Long-press не фигурировал; считается как "auto-recovery between Tier 1 fail and Tier 2 entry", НЕ как Tier 2 success. Отдельная категория, чтобы не overstate long-press effectiveness (Codex round 3 P2.3 fix).

**Обогащённый error meta** на final fail (тот же error_code `ig_share_tap_no_progress`):
- `tier2_attempted: True` (всегда, если Tier 2 ladder отработал)
- `lp_attempts: 2`
- `hold_ms: 200`
- `tier2_button_not_found: True` (опционально, если все attempts провалились на button-search)

**Dashboard split** (на стороне triage; event name живёт в `meta.category`, не `msg` — Codex round 1 fix P2.2):

В терминах event'ов из `publish_tasks.events::jsonb`:
- **Tier 2 long-press rescue** (реальная заслуга long-press):
  ```sql
  events[].type='info' AND events[].meta->>'category'='ig_share_long_press_progressed'
  ```
- **Pre-long-press auto-recovery** (Tier 1 finished, editor исчез сам до Tier 2 tap):
  ```sql
  events[].type='info' AND events[].meta->>'category'='ig_share_progressed_pre_long_press'
  ```
- **Tier 2 exhausted** (escalation не помог):
  ```sql
  pt.error_code='ig_share_tap_no_progress'
    AND EXISTS (SELECT 1 FROM jsonb_array_elements(pt.events::jsonb) e
                WHERE e->'meta'->>'category'='ig_share_tap_no_progress'
                  AND (e->'meta'->>'tier2_attempted')::boolean = true)
  ```
- **Pre-deploy хвост** (Tier 1-only fail, до 2026-05-11 deploy cutoff — данные останутся в исторических): same error_code БЕЗ `tier2_attempted=true` в event'ах:
  ```sql
  pt.error_code='ig_share_tap_no_progress'
    AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(pt.events::jsonb) e
                    WHERE (e->'meta'->>'tier2_attempted')::boolean = true)
    AND pt.started_at < '2026-05-11'  -- post-deploy всё проходит через Tier 2
  ```
  (Codex round 3 P2.2 fix: убрана wrong claim про "Tier 2 helper exception" — exceptions проглатываются `_long_press_share_button=False`, Tier 2 фейл всё равно эмитит `tier2_attempted=True`.)

**Decision criterion для Tier 3** (out of scope этого spec'а):
- 24h post-deploy: count Tier 2 successes vs Tier 2 exhausted
- Если Tier 2 success > 30% → отлично, оставляем
- Если Tier 2 success < 10% → нужен sendevent / другой method (отдельный design)
- 10-30% → keep + monitor; рассмотреть jitter / hold_ms tuning

---

## 7. Out of scope

- **sendevent rung** — отложен до evidence что long-press недостаточно (B.2 anti-bot dominant)
- **KEYCODE_DPAD_CENTER rung** — отложен (требует focusable Share button, не verified)
- **Re-open Reels camera (full restart)** — отложен (60-90s стоимость, риск двойной публикации)
- **Jitter pattern (1-2px diagonal)** — добавим reactively если 200ms hold вызывает context menu
- **Separate publish_queue re-queue path** — не нужен, in-place ladder покрывает
- **GrantPermissionsActivity handler** — отдельный sub-project (24% Phase 1 wait events, не overlap с Mode B)

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| 200ms hold открывает context menu вместо tap | Choose < default long-press threshold; revert plan: snap to 150ms или add diagonal jitter в follow-up PR |
| Tier 2 не помогает в N% case → false hope | Telemetry split (см. Section 6) даёт точное число; Tier 3 design triggered evidence-based |
| Long-press на double-publishing scenario (если first tap actually went through, just response delayed) | Existing `_is_ig_editor_still_visible` check ПЕРЕД long-press: если editor gone между attempts — НЕ tap'аем, ladder exit'ит progressed; защищает от over-tap |
| Tier 2 latency искажает throughput метрики | +10s к fail path (был ~10s, стал ~20s); fails ~1% от total → impact на throughput < 0.1% |

---

## 9. Acceptance criteria

1. Все 13 unit tests green (4 helper + 6 ladder + 2 regression + 1 Tier 1 mod)
2. Existing 24 tests `test_ig_gallery_picker_hardening.py` green (no regression)
3. Live verification: re-queue 1 IG задачу с известным `ig_share_tap_no_progress` history; observe meta `tier2_attempted=True` в final fail OR success path с `ig_share_long_press_progressed` event
4. Dashboard может различать Tier 1-only vs Tier 2-also fails (через meta keys)
5. Codex review (`codex review --uncommitted` после спеца, потом после кода) применён

---

## 10. Связанные документы

- Tier 1 design: `docs/superpowers/specs/2026-05-08-ig-share-tap-retry-fix-design.md`
- Tier 1 plan: `docs/superpowers/plans/2026-05-08-ig-share-tap-retry-fix-plan.md`
- Phase 1.7 evidence: `docs/evidence/2026-05-08-ig-wait-upload-instrumentation-findings.md`
- MediaStore outage memory: `~/.claude/projects/.../memory/project_publisher_outage_2026_05_09.md`
- Session memory: `project_session_2026_05_08_shipped.md` (раздел "In-flight evidence collection")
