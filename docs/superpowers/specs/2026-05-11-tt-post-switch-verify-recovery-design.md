# TT post-switch verify recovery — design spec v1

**Date:** 2026-05-11
**Status:** Draft (awaiting Codex review)
**Related:** PR #33 (`switch_failed_unspecified` fix, shipped 2026-05-11), Phase 1 (`tt_bound_nav`, shipped 2026-05-08)

## Problem

После недавнего обновления TikTok UI поведение account-switch'а изменилось: после `_find_and_tap_account` (bottomsheet picker) TT автоматически открывает **feed** (`Смотреть` / `Подписки` / `Рекомендации` / `Поиск` в top 260px), а не **profile screen** как раньше.

Switcher вызывает `_post_switch_verify_handle(target, xml_after_pick, header_y_max)` (`account_switcher.py:3396`). Функция ищет username в header'е (`get_current_account_from_profile`, `header_y_max=260`). На feed-экране там навигационные tabs, а не username → `current=None` → возвращает `('unknown', None)`.

Caller (`account_switcher.py:2275-2287`) логирует `tt_post_switch_handle_unknown` (warning), делает `break` и продолжает publish с **неверифицированным state**. Comment в коде это маркирует как намеренный degrade-to-pass (защита от infinite loop на стабильно сломанном dump'е), но в новом поведении это **маскирует system-wide regression**.

### Evidence (32h pre-fix)

- **21 hit** events `tt_post_switch_handle_unknown` за 36h (2026-05-10 04:50 → 2026-05-11 14:24).
- Все на `step=tt_4_target_profile, attempt=1` (первая попытка picker).
- Затронуты различные packs: `clickpay_*` (10+), `wellroom_*`, `feminista.beauty`, `mariaforsale`, `sale.for19`, `el_cosmetics7`.
- 2 dump'а проверены вручную (pt 4691 `tt_4_target_profile` свежий + pt 4451 24h назад) — оба показывают TikTok feed top-bar (4 tab-кнопки).
- XML usable=True, bytes ≈ 26KB (не sparse / не FLAG_SECURE).
- Downstream impact:
  - `tt_upload_confirmation_timeout` — большинство; publisher стартует в editor с неверного state.
  - `switch_failed_unspecified` — после PR #33 unmask.
  - NULL error_code — в процессе.
- TT publish stats: **277 failed / 1 done за 7 дней**.

## Goals

1. Перестать публиковать слепо — при unknown active actively восстановить state или fail с явным error_code.
2. Восстановить invariant `_post_switch_verify_handle = (match | mismatch | unknown)` где unknown = действительно невосстановимое состояние (FLAG_SECURE, sparse dump).
3. Добавить observability — отдельные event categories для (a) feed-after-pick detection, (b) successful re-nav recovery, (c) unrecoverable verify.

## Non-goals

- Не менять Instagram / YouTube switchers — у них своя verify-схема, и evidence указывает только на TT.
- Не вводить feature flag — это bug fix, не feature. Прежний degrade-to-pass — баг защита, маскирующая reality.
- Не трогать `_post_switch_verify_handle` (line 3396) — функция остаётся pure read+verify, без side-effects.

## Approach

**Approach A — recovery в TT-caller** (выбран после обсуждения user, 2026-05-11):

В TT switcher path в месте вызова `_post_switch_verify_handle` (`account_switcher.py:2257-2287`, ветка `if status == 'unknown'`) добавить recovery:

1. Детектить TT feed-маркеры в XML top 260px.
2. Если feed → log event `tt_post_switch_feed_after_pick` (warning) → вызвать `_navigate_to_profile_tab` (Phase 1 `tt_bound_nav`, уже работает) → re-dump → второй `_post_switch_verify_handle`.
3. Если второй verify = `match` → log `tt_post_switch_recovered_via_renav` → break (success).
4. Если второй verify = `mismatch` → проваливаемся в существующий mismatch-handler (line 2289+), который обработает MAX_PICK_ATTEMPTS retry.
5. Если второй verify = `unknown` → `_fail` с error_code `tt_post_switch_verify_unrecoverable`.
6. Если feed-маркеров **нет** в первом XML (т.е. unknown по причине FLAG_SECURE / sparse / другой UI) → также `_fail` с `tt_post_switch_verify_unrecoverable` (user decision, 2026-05-11).

### Why Approach A (vs B / C)

| Approach | Pro | Con |
|---|---|---|
| **A (recovery в callsite)** | side-effect (navigate) изолирован в recovery path; не меняет contract `_post_switch_verify_handle`; targeted к найденному signal | дублирование, если IG/YT когда-то получат similar UI change |
| B (recovery в verify_handle) | DRY — переиспользует на IG/YT | смешивает read+side-effect; требует platform-aware navigate dispatch; ломает invariant |
| C (безусловный nav после pick) | простой | лишний tap в happy path, потенциальная UI jitter |

## File map

**Modify:**
- `account_switcher.py` — расширить ветку `status == 'unknown'` в TT-switch loop (line 2275-2287); добавить helper `_is_tt_feed_after_pick(xml, header_y_max)`.
- `publisher_kernel.py` — добавить mapping `'tt_4_target_profile': 'tt_post_switch_verify_unrecoverable'` (или эквивалент на этапе post-switch verify recovery).

**Create:**
- `tests/test_post_switch_renav.py` — TDD-тесты.

**No changes:**
- `_post_switch_verify_handle` (line 3396) — остаётся как есть.
- `_navigate_to_profile_tab` (Phase 1) — переиспользуется без модификации.
- IG / YT switcher paths.

## Recovery flow (pseudo-code)

```python
# account_switcher.py around line 2275
if status == 'unknown':
    self.p.log_event(
        'warning', 'tt_post_switch_handle_unknown',
        meta={'category': 'tt_post_switch_handle_unknown',
              'target': target, 'step': label, 'attempt': attempt + 1},
    )
    is_feed = self._is_tt_feed_after_pick(xml_after_pick, header_y_max)
    if is_feed:
        self.p.log_event(
            'warning', 'tt_post_switch_feed_after_pick',
            meta={'category': 'tt_post_switch_feed_after_pick',
                  'target': target, 'step': label,
                  'attempt': attempt + 1},
        )
        # Reuse Phase 1 bound-nav. Idempotent: no-op if уже на profile.
        nav_ok = self._navigate_to_profile_tab()
        xml_after_renav = self.p.dump_ui(retries=1) or ''
        self._save_dump(f'{label}_renav', xml_after_renav)
        status, current = self._post_switch_verify_handle(
            target, xml_after_renav, header_y_max=header_y_max,
        )
        if status == 'match':
            self.p.log_event(
                'account_switch', 'tt_post_switch_recovered_via_renav',
                meta={'category': 'tt_post_switch_recovered_via_renav',
                      'target': target, 'current': current,
                      'attempt': attempt + 1},
            )
            break
        if status == 'mismatch':
            # falls through to existing mismatch handler at line 2289+
            pass
        else:
            # still unknown after re-nav
            return self._fail(
                f'tt_post_switch_verify_unrecoverable: no profile after re-nav '
                f'(target={target!r})',
                step=f'{label}_renav',
            )
    else:
        # non-feed unknown (FLAG_SECURE / sparse / unrecognised UI)
        return self._fail(
            f'tt_post_switch_verify_unrecoverable: unknown header non-feed '
            f'(target={target!r})',
            step=label,
        )
```

### `_is_tt_feed_after_pick` helper

```python
_TT_FEED_MARKERS = ('Смотреть', 'Подписки', 'Рекомендации')

def _is_tt_feed_after_pick(self, xml: str, header_y_max: int = 260) -> bool:
    """Detect TikTok feed top-bar after account-pick.

    Returns True if ≥2 of `_TT_FEED_MARKERS` present in top header_y_max px.
    Threshold 2/3 conservative: single marker insufficient (could be unrelated
    label), 2+ — strong signal of feed state.
    """
    if not xml:
        return False
    elements = parse_ui_dump(xml)
    if not elements:
        return False
    hits = 0
    for el in elements:
        y_top = el.bounds[1]
        if y_top > header_y_max:
            continue
        for marker in _TT_FEED_MARKERS:
            if marker in (el.text or '') or marker in (el.content_desc or ''):
                hits += 1
                break
    return hits >= 2
```

## Event taxonomy

| Name (= category) | type | When emitted | Meta fields |
|---|---|---|---|
| `tt_post_switch_handle_unknown` | warning | existing — first verify returned unknown | target, step, attempt |
| `tt_post_switch_feed_after_pick` | warning | new — unknown + feed markers detected | target, step, attempt |
| `tt_post_switch_recovered_via_renav` | account_switch | new — re-verify after navigate = match | target, current, attempt |
| `tt_post_switch_verify_unrecoverable` | error | new — final fail (after recovery OR non-feed unknown) | target, step, was_feed |

### Error_code

New: `tt_post_switch_verify_unrecoverable`. Maps from step `tt_4_target_profile` (or its `_renav` variant) via `publisher_kernel.py` step→category mapping update.

## Tests (TDD order)

Создать `tests/test_post_switch_renav.py`:

1. **test_is_tt_feed_two_markers_returns_true** — XML с 2/3 marker'ами в top 260px → `True`.
2. **test_is_tt_feed_one_marker_returns_false** — 1/3 → `False` (threshold ≥2).
3. **test_is_tt_feed_below_header_returns_false** — все 3 marker'а ниже y=260 → `False`.
4. **test_is_tt_feed_empty_xml_returns_false** — пустая строка → `False`.
5. **test_unknown_with_feed_triggers_navigate_and_renav_match** — mock первый verify → unknown, feed-markers present; mock `_navigate_to_profile_tab` returns True; mock второй verify → match. Assert: `_navigate_to_profile_tab` called once, success path breaks, event `tt_post_switch_recovered_via_renav` logged.
6. **test_unknown_with_feed_renav_still_unknown_fails** — оба verify unknown; assert `_fail` called with message containing `tt_post_switch_verify_unrecoverable`.
7. **test_unknown_with_feed_renav_mismatch_falls_through** — re-verify returns mismatch; assert mismatch-path engaged (existing retry logic).
8. **test_unknown_non_feed_fails_immediately** — XML без feed-markers; assert `_navigate_to_profile_tab` NOT called, `_fail` called with `tt_post_switch_verify_unrecoverable` (was_feed=False).
9. **test_publisher_kernel_step_to_category_mapping** — assert `_SWITCHER_STEP_TO_CATEGORY['tt_4_target_profile']` resolves to `tt_post_switch_verify_unrecoverable` (or the equivalent recovery-step entry).

## Rollout

**No feature flag** — straight deploy. Reasoning:
- Degrade-to-pass был bug — добавить визибл fail path сразу правильнее.
- 21 silent fail/36h → новый явный error_code = visibility, не regression.

**Verify path:**
1. Deploy (commit на ветку → PR → merge → prod автоматом через auto-push hook).
2. PM2 `autowarm` restart (auto через post-commit).
3. Через 24h SQL query:
   - ≥1 `tt_post_switch_recovered_via_renav` event → recovery работает на real traffic.
   - Сравнить `tt_upload_confirmation_timeout` count за 24h до/после deploy — ожидается падение, поскольку часть кейсов теперь либо recovered (success), либо fail c явным error_code (нет cascade в editor).
   - `tt_post_switch_verify_unrecoverable` count за 24h: baseline для будущих iterations (если значимо > 0, копать non-feed unknown).

**Rollback:** `git revert` 1 коммита если массовый regression (>50% TT publishes fail с новым error_code) → возврат к legacy degrade-to-pass.

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Legacy unknown-кейсы (FLAG_SECURE / sparse) теперь fail вместо silent-pass | Low | Evidence из 21 hit за 36h — все usable=True XML с feed; FLAG_SECURE редок. Если возникает → новый error_code даёт visibility для diagnosis. |
| `_navigate_to_profile_tab` (Phase 1) fail на feed | Low | Phase 1 `tt_bound_nav` validated 9/24h (см. baseline в evidence music-rights). Idempotent helper; если уже на profile — no-op. |
| Threshold 2/3 marker'ов слишком aggressive (false positive — non-feed UI с 2 совпадениями) | Very Low | TT feed UI имеет все 3 marker'а в фиксированном top-bar. False positive потребует чтобы 2 из {Смотреть, Подписки, Рекомендации} оказались в первых 260px на не-feed экране — маловероятно. |
| Race: re-dump после `_navigate_to_profile_tab` слишком быстрый, header ещё не успел отрисоваться | Medium | Reuse существующего `dump_ui(retries=1)` (включает internal retry); `_navigate_to_profile_tab` уже включает после-нав sleep. Если flaky → расширим в follow-up на base существующего instrumentation. |

## Success metrics (24h post-deploy)

- ≥1 `tt_post_switch_recovered_via_renav` event (recovery работает).
- `tt_post_switch_verify_unrecoverable` count documented (baseline для follow-up).
- TT publish `done` count за 24h > baseline (1/7d) — если RC-A + RC-B (separate работы) тоже engage.

## Open questions

Нет. Все ключевые решения зафиксированы в обсуждении 2026-05-11.

## References

- Memory: `feedback_publisher_error_code_misleading.md` (error_code врёт без events.meta.category lookup), `feedback_user_diagnosis_is_signal.md` (cross-check symptom + component), `feedback_codex_review_specs.md` (Codex round до 0 P1).
- Evidence: pt 4691 dump `task4691_switch_4691_tt_4_target_profile_1778510958.xml` (свежий), pt 4451 dump (24h назад).
- Code:
  - `account_switcher.py:430` — `get_current_account_from_profile`
  - `account_switcher.py:2257-2287` — TT switch verify callsite (target)
  - `account_switcher.py:3396` — `_post_switch_verify_handle` (unchanged)
  - Phase 1: `_navigate_to_profile_tab` + `_tt_bottom_nav_profile_bounds_from_xml`
