# IG Share tap retry fix (Tier 1) — design spec

**Дата:** 2026-05-08
**Sub-project:** P1.1 IG post-switch regressions — Tier 1 fix
**Репо:** `autowarm-testbench` (auto-pushed в `GenGo2/delivery-contenthunter`)
**Триггер:** Phase 1.7 evidence показал что Share button tap не вызывает IG progression past editor (Mode B confirmed). 23 fails/24h `ig_upload_confirmation_timeout` — большая часть из этой категории.

---

## 1. Контекст и Phase 1 evidence

`publisher_instagram._fill_instagram_caption_and_publish` (line ~1635) ловит Share button через:
```python
if self.tap_element(ui, ['Поделиться', 'Share', 'Опубликовать'], exact=False, clickable_only=True):
    log.info('✅ Нажали Поделиться!')
    self.log_event('info', f'Instagram: кнопка Поделиться (шаг {step})')
    return self._wait_instagram_upload()
```

Phase 1.7 evidence (`docs/evidence/2026-05-08-ig-wait-upload-instrumentation-findings.md`):

- **Task 4123 fail (`just_clickpay`):** `tap_element` нашёл правильный `id/share_button` clickable bounds `[563,2025][1035,2149]` и `adb_tap(799, 2087)` выполнился. **26 sec позднее** iter0_diag показал editor still visible (caption + Share button + "Новое видео Reels"). **10 минут спустя** timeout_diag показал ИДЕНТИЧНЫЙ UI dump (editor unchanged 30 iterations).
- **Task 4098 success (`click_and_pay`):** идентичный путь — Share tap fired, **9 sec** позднее iter0_diag показал post-publish Reels confirmation screen (editor gone), **28 sec** позднее `Создать видео Reels` SUCCESS_KW match.

Sub-причины Mode B (B.1 race / B.2 anti-bot / B.3 layout-shift) пока не distinguished — n=1 fail, n=1 success post-deploy. **Tier 1 fix не зависит** от distribution: detect симптом, не первопричину.

Sample 24h Phase 1 broader data: 40/58 wait events fail tasks показали `InstagramMainActivity` (host of editor modal) vs 28/29 success on `MainTabActivity`. Binary signature.

## 2. Approach (recommended из 3)

### 2.1. Recommended — retry block в `_wait_instagram_upload`

Добавить detection + retry block ПОСЛЕ iter0 diag (`wait_upload_iter0_diag` event), ПЕРЕД main 30-iter loop. Используем уже-собранный `iter0_ui_xml` для первичной проверки. До 2 retries с 3-sec delay. После exhausted — fail-fast с новым error_code.

**Pros:** одна точка вмешательства, переиспользует iter0 dump.
**Cons:** scope expansion `_wait_instagram_upload`.

### 2.2. Альтернатива — retry в caller `_fill_instagram_caption_and_publish` (rejected)

Чище separation. Но требует new branch в outer step-loop, новый dump_ui call (не reuse iter0). Больше кода.

### 2.3. Альтернатива — adaptive timeout (rejected)

Расширить main loop 30 → 60 iter. Маскирует issue, не fix.

## 3. Архитектура

### 3.1. Pure helper

```python
def _is_ig_editor_still_visible(self, ui_xml: str) -> bool:
    """True if IG Reels editor markers present: caption_input_text_view +
    clickable id/share_button. Used by Tier 1 share retry logic.

    Editor signature (Phase 1.7 evidence):
      - caption_input_text_view resource-id present
      - id/share_button (NOT direct_share_button) clickable=true
    Post-publish screen has neither.
    """
    if not ui_xml or 'caption_input_text_view' not in ui_xml:
        return False
    try:
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(ui_xml)
    except Exception:
        return False
    for n in root.iter('node'):
        rid = n.get('resource-id', '')
        if rid.endswith(':id/share_button') and n.get('clickable') == 'true':
            return True
    return False
```

`endswith(':id/share_button')` точно matches `com.instagram.android:id/share_button` (не зацепляет `direct_share_button`).

### 3.2. Retry block

В `_wait_instagram_upload` после existing iter0 diag block, перед main `for wait in range(30)`:

```python
# === Tier 1 fix: detect editor-stuck and retry Share ===
# Phase 1.7 evidence: Share tap can be no-op (timing race / anti-bot / layout shift).
# Detect via editor markers; re-tap up to 2 times; fail-fast если progress нет.
share_no_progress = False  # signal вне try/except для unconditional return False
try:
    if self._is_ig_editor_still_visible(iter0_ui_xml):
        progressed = False
        for retry_n in range(1, 3):  # 2 retries
            time.sleep(3)
            retry_ui = self.dump_ui()
            if not self._is_ig_editor_still_visible(retry_ui):
                progressed = True
                break
            if self.tap_element(retry_ui, ['Поделиться', 'Share', 'Опубликовать'],
                                exact=False, clickable_only=True):
                self.log_event('info', f'Instagram: Share re-tap retry {retry_n}',
                               meta={'category': 'ig_share_retry',
                                     'platform': self.platform,
                                     'retry_n': retry_n})
                time.sleep(2)
            else:
                progressed = True  # share button gone
                break

        if not progressed and self._is_ig_editor_still_visible(self.dump_ui()):
            self.log_event('error',
                           'Instagram: Share tap не прогрессировал после retries',
                           meta={'category': 'ig_share_tap_no_progress',
                                 'platform': self.platform,
                                 'step': 'wait_upload',
                                 'retries_exhausted': 2})
            try:
                self._save_debug_artifacts('instagram_share_no_progress')
            except Exception as _art_e:
                log.warning(f'_save_debug_artifacts failed: {_art_e}')
            share_no_progress = True
except Exception as _retry_e:
    log.warning(f'wait_upload share retry block failed: {_retry_e}')

if share_no_progress:
    return False
```

Per Codex review: artifact save wrapped в inner try/except; `share_no_progress` flag signals fail-fast return ВНЕ outer try/except (artifact save failure НЕ должна bypass fail-fast). Outer try/except только для protection of detection/retry logic. Variable `iter0_ui_xml` initialized к `''` ВЫШЕ existing iter0 diag block (replaces `locals().get` non-idiomatic pattern).

### 3.3. Order of operations

```
_wait_instagram_upload entry
  set_step
  published = False
  iter0 diag block (captures iter0_ui_xml, iter0_act, iter0_dump_url, iter0_candidates)
  ===> Tier 1 retry block (if editor still visible)
        - up to 2 re-tap attempts
        - else fail-fast с ig_share_tap_no_progress
  for wait in range(30): ...  # existing main loop
  if not published: timeout diag block (existing)
```

## 4. Edge cases

| # | Случай | Поведение |
|---|---|---|
| 1 | Editor visible на iter0, retry 1 progressed | `ig_share_retry` event (1 emit), `progressed=True`, fall through к main loop |
| 2 | Editor visible на iter0, оба retry tapped, всё ещё editor → retries exhausted | `ig_share_retry` ×2, final check confirms editor → `ig_share_tap_no_progress` error, return False |
| 3 | Editor НЕ visible на iter0 (4098 success path) | Retry block skipped целиком |
| 4 | iter0 captures editor, retry check finds editor gone (transitional) | `progressed=True` без re-tap, break, main loop normally |
| 5 | Share button исчез без editor closing (rare) | `tap_element` returns False → `progressed=True` (assume IG progressed inflight) → break |
| 6 | iter0 dump_ui failed (`iter0_ui_xml` empty или undefined) | `_is_ig_editor_still_visible('')` → False, retry block skipped |
| 7 | Final check после retry loop: editor исчез между last retry и final check | `progressed=False` НО final `_is_ig_editor_still_visible(self.dump_ui())` → False → НЕ emit error_code, fall through к main loop |
| 8 | `_save_debug_artifacts` failed during error path | Wrapped exception swallowed by outer try/except, error event уже emit'нут, return False остаётся |

## 5. Тестирование

### 5.1. Pure helper (5 tests)

`tests/test_ig_editor_visible_helper.py`:

1. `test_editor_visible_returns_true_for_editor_xml` — synthetic с `caption_input_text_view` + clickable `:id/share_button` → True.
2. `test_editor_visible_returns_false_when_caption_input_absent` — share_button only → False.
3. `test_editor_visible_returns_false_when_share_not_clickable` — caption + non-clickable share → False.
4. `test_editor_visible_distinguishes_direct_share_button` — caption + clickable `direct_share_button` (но не `id/share_button`) → False.
5. `test_editor_visible_handles_empty_and_malformed` — `''` → False, `'<not-xml'` → False.

### 5.2. Behavior tests (2 tests)

`tests/test_publisher_instagram_share_retry.py`:

6. `test_share_retry_progresses_after_first_retry` — mock `dump_ui` side_effect=[editor_xml, post_publish_xml]; `tap_element` mocked. After 1 retry, editor gone → main loop entered → ig_share_tap_no_progress NOT emit. Asserts `ig_share_retry` retry_n=1 event emit'нут.

7. `test_share_retry_exhausted_emits_no_progress` — mock `dump_ui` always returns editor_xml. After 2 retries + final check (editor still visible), `ig_share_tap_no_progress` emit, function returns False. Asserts: 2 `ig_share_retry` events + 1 `ig_share_tap_no_progress` event.

Behavior tests используют тот же stub pattern что Phase 1.7 (`_make_publisher_stub` с InstagramMixin __new__).

### 5.3. Регрессия

Все existing IG tests остаются зелёными. iter0_diag/timeout_diag tests из Phase 1.7 не затронуты (retry block — между ними и main loop).

## 6. Out of scope

- **GrantPermissionsActivity handler** — отдельный sub-project (24% Phase 1 wait events).
- **IG version drift detection** (Mode A — disproven).
- **Caption_fill_failed regression** — residual baseline track.
- **Tier 2 fixes** (alternative tap methods, hardware events) — открываем только если `ig_share_tap_no_progress` rate показывает residual issue.

## 7. Risks

| ID | Риск | Mitigation |
|---|---|---|
| R1 | Re-tap вызывает double-publish | Detection через `_is_ig_editor_still_visible` гарантирует что Share tap не сработал (editor visible = нет progress). Re-tap безопасен. |
| R2 | Helper false-positive: caption_input + share_button visible на каком-то post-publish "Save draft" prompt | Editor markers specific. Post-publish screens НЕ имеют caption_input (verified 4098 dump). Низкий риск. |
| R3 | Anti-bot heuristic игнорирует ВСЕ taps (B.2) | Все 3 attempts fail → `ig_share_tap_no_progress`. Чистый signal для Tier 2 design. |
| R4 | Race: dump_ui между retries ловит editor перед IG transition complete → false retry | 3-sec delay должно быть достаточно. False retry — `tap_element` returns False (share gone) → break безопасный. |
| R5 | Existing happy path (Phase 1.7 success-detect) сбит | iter0 diag и main loop не меняются. Retry block — additive between them. Try/except по периметру блока. |
| R6 | `locals().get('iter0_ui_xml', '')` — non-idiomatic. Если iter0 diag block changes structure — переменная может пропасть | Existing iter0 block (Phase 1.7 prior session) определяет iter0_ui_xml в try block; outer scope не имеет этой переменной. `locals()` access безопасен (Python ловит). Альтернатива — initialize `iter0_ui_xml = ''` ВЫШЕ iter0 diag block для clean scope. Spec предпочитает explicit init. |

**Spec decision:** добавить `iter0_ui_xml = ''` (default) ВЫШЕ existing iter0 diag block для clean scope, заменив `locals().get(...)` на direct access. Cleaner и idiomatic.

## 8. Definition of Done

- `_is_ig_editor_still_visible(ui_xml: str) -> bool` pure helper added.
- `iter0_ui_xml = ''` initialized перед iter0 diag block (заменяет `locals().get`).
- Tier 1 retry block в `_wait_instagram_upload` после iter0 diag, перед main loop.
- 5 + 2 unit tests green.
- Existing publisher_instagram tests неизменны.
- Deploy в prod main → next 6-12h tracks 2 новых categories: `ig_share_retry` (recovery success), `ig_share_tap_no_progress` (recovery failure).
- Метрика после 24h: SQL query на distribution `ig_share_retry` count vs `ig_share_tap_no_progress` count определит:
  - Высокий retry-success rate → B.1 race condition (retry helps)
  - Высокий no_progress rate → B.2 anti-bot (retry также failed; нужен Tier 2)

## 9. Связанные памяти

- `project_ig_post_switch_regressions_2026_05_08.md` — investigation memory
- `project_ig_caption_fill_persistent_bug.md` — predecessor IG-fix
- `feedback_codex_review_specs.md` — этот spec пройдёт codex review
- `feedback_subagent_force_push_risk.md` — для Task 8 deploy (включить explicit "no force-push" instruction)
- Evidence file: `docs/evidence/2026-05-08-ig-wait-upload-instrumentation-findings.md`
