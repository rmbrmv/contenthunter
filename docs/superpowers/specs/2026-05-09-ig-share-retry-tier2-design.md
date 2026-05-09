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

Distribution IG за ~21h после Tier 1 deploy сильно искажена outage'ем (17/21 IG fails = MediaStore). Tier 1 fail-fast зафиксирован 1 раз. Sample недостаточен для precise B.1/B.2/B.3 distribution, но достаточен для решения mode-agnostic Tier 2 (user decision).

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

### 3.1. Pure helper в `publisher_base.py`

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

В `_wait_instagram_upload`, **сразу после** Tier 1 retry-блока, **перед** установкой `_last_push_err = ig_share_tap_no_progress`:

```python
# === Tier 2 long-press escalation ===
# Tier 1 (zero-duration tap retry) исчерпан; пробуем 2 long-press attempt'а.
# Спецификация: docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md
TIER2_LP_ATTEMPTS = 2
TIER2_LP_HOLD_MS = 200
TIER2_LP_PRE_DELAY_S = 3
TIER2_LP_POST_DELAY_S = 2
tier2_progressed = False
tier2_button_not_found = False
for lp_attempt in range(1, TIER2_LP_ATTEMPTS + 1):
    time.sleep(TIER2_LP_PRE_DELAY_S)
    lp_ui = self.dump_ui()
    if not self._is_ig_editor_still_visible(lp_ui):
        tier2_progressed = True
        self.log_event(
            'info',
            f'Instagram: long-press Share PROGRESSED after attempt {lp_attempt - 1}',
            meta={'category': 'ig_share_long_press_progressed',
                  'platform': self.platform,
                  'attempts_used': lp_attempt - 1,
                  'hold_ms': TIER2_LP_HOLD_MS}
        )
        break
    if not self._long_press_share_button(lp_ui, hold_ms=TIER2_LP_HOLD_MS):
        tier2_button_not_found = True
        # button gone — продолжаем next attempt с новым dump,
        # но если на всех attempt'ах False → отдельный сигнал в final meta
        continue
    self.log_event(
        'info',
        f'Instagram: long-press Share retry {lp_attempt}',
        meta={'category': 'ig_share_long_press_retry',
              'platform': self.platform,
              'attempt': lp_attempt,
              'hold_ms': TIER2_LP_HOLD_MS}
    )
    time.sleep(TIER2_LP_POST_DELAY_S)

if tier2_progressed:
    # Continue в existing main 30-iter wait loop (без изменений)
    pass
else:
    # Tier 2 exhausted — fail-fast с тем же error_code, но обогащённым meta
    err_meta = {
        'category': 'ig_share_tap_no_progress',
        'platform': self.platform,
        'tier2_attempted': True,
        'lp_attempts': TIER2_LP_ATTEMPTS,
        'hold_ms': TIER2_LP_HOLD_MS,
    }
    if tier2_button_not_found:
        err_meta['tier2_button_not_found'] = True
    self.log_event(
        'error',
        f'Instagram: Tier 2 long-press exhausted — abort',
        meta=err_meta
    )
    self._last_push_err = err_meta
    return False
```

### 3.3. Точка вмешательства

Единственная: `_wait_instagram_upload` в `publisher_base.py`. `_long_press_share_button` — новый pure helper рядом с `_is_ig_editor_still_visible`. Tier 1 код **не трогается** — просто между Tier 1 fail-condition и `return False` вставляется Tier 2 ladder.

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

### 4.2. Tier 2 ladder behavior tests (4)

5. **test_tier2_progressed_on_attempt_1** — `_is_ig_editor_still_visible` returns [True (Tier 1 baseline), True×2 (Tier 1 retries fail), False (Tier 2 attempt 1)] → tier2_progressed; no error event; main wait loop entered.
6. **test_tier2_progressed_on_attempt_2** — editor visible на всех Tier 1 + Tier 2 attempt 1, не visible на attempt 2 → tier2_progressed; `ig_share_long_press_progressed` info event с `attempts_used=1`.
7. **test_tier2_exhausted_fail** — editor visible везде → `ig_share_tap_no_progress` error event с `tier2_attempted=True, lp_attempts=2, hold_ms=200`. `_last_push_err` зеркалирует.
8. **test_tier2_button_not_found** — `_long_press_share_button` returns False на обоих attempts (UI не имеет button) → fail с дополнительным `tier2_button_not_found=True` в meta.

### 4.3. Regression tests (2)

9. **test_tier1_success_skips_tier2** — Tier 1 retry-1 progresses → `_long_press_share_button` НЕ зовётся (`stub.adb` not called с `input swipe`-pattern). Защита: Tier 2 не запускается когда не нужен.
10. **test_no_stuck_skips_both_tiers** — `_is_ig_editor_still_visible` returns False сразу после iter0 → ни Tier 1 ни Tier 2 не invoked, main wait loop сразу.

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
- `ig_share_long_press_retry` — per attempt (фиксирует Tier 2 fired). meta: `attempt`, `hold_ms`, `platform`.
- `ig_share_long_press_progressed` — успех Tier 2. meta: `attempts_used`, `hold_ms`, `platform`. **Только при success** — позволяет считать % effectiveness Tier 2 vs Tier 1 фильтром по событиям.

**Обогащённый error meta** на final fail (тот же error_code `ig_share_tap_no_progress`):
- `tier2_attempted: True` (всегда, если Tier 2 ladder отработал)
- `lp_attempts: 2`
- `hold_ms: 200`
- `tier2_button_not_found: True` (опционально, если все attempts провалились на button-search)

**Dashboard split** (на стороне triage):
- `failed AND error_code=ig_share_tap_no_progress AND meta->>'tier2_attempted' IS NULL` → Tier 1-only fail (старый pre-Tier-2 хвост или regression)
- `failed AND error_code=ig_share_tap_no_progress AND meta->>'tier2_attempted'='true'` → Tier 2 exhausted (escalation не помог)
- `info AND msg='ig_share_long_press_progressed'` → Tier 2 success (recovery hit) — для подсчёта эффективности

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

1. Все 10 unit tests green (4 helper + 4 ladder + 2 regression)
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
