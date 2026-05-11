# TT post-switch verify recovery — Shipped 2026-05-11

**PR:** [GenGo2/delivery-contenthunter#34](https://github.com/GenGo2/delivery-contenthunter/pull/34)
**Merge commit:** `750c3fa0267605161e34acece001e427e6693cbb` (squash; branch `fix/tt-post-switch-renav-20260511` deleted)
**Merged at:** 2026-05-11 17:45:26 UTC
**Prod state:** `/root/.openclaw/workspace-genri/autowarm` @ `750c3fa`; PM2 autowarm (id=34) restart_time=15, last_start=2026-05-11T17:45:58 UTC
**Spec:** `docs/superpowers/specs/2026-05-11-tt-post-switch-verify-recovery-design.md` (v2, Codex CLEAN после 1 round)
**Plan:** `docs/superpowers/plans/2026-05-11-tt-post-switch-verify-recovery-plan.md` (v4, Codex CLEAN после 3 rounds)

## Context

Discovery 2026-05-11 (этой сессии): после обновления TikTok bottomsheet-pick стал открывать **feed** (`Смотреть` / `Подписки` / `Рекомендации` в top-bar), а не **profile screen**. Switcher делает `_post_switch_verify_handle` на feed-state, не находит username в header (первые 260px), возвращает `('unknown', None)` → `break` (комментарий «degrade-to-pass чтобы не зацикливаться») → publisher продолжает в editor **слепо**.

### Evidence

- pt 4691 (свежий 2026-05-11 14:24 UTC) + pt 4451 (2026-05-10 06:15 UTC) — 2 UI dump'а скачаны из S3; оба показывают TikTok feed top-bar (4 tab-кнопки).
- XML usable=True, bytes ≈ 26KB (не sparse / не FLAG_SECURE).
- **21 hit** events `tt_post_switch_handle_unknown` за 36ч (2026-05-10 04:50 → 2026-05-11 14:24).
- Все на `step=tt_4_target_profile, attempt=1` (первая попытка picker, recovery-loop не engage).
- Затронуты разнообразные packs: `clickpay_*` (10+), `wellroom_*`, `feminista.beauty` ×2, `mariaforsale`, `sale.for19`, `el_cosmetics7`, `forsal32`.
- Downstream impact:
  - `tt_upload_confirmation_timeout` — большинство; publisher стартует в editor с неверного state
  - `switch_failed_unspecified` — после PR #33 unmask
  - NULL error_code — в процессе
- TT publish stats (7 дней до merge): **277 failed / 1 done**.

## Shipped

### Approach A — recovery в TT-caller `account_switcher.py:2275-2287`

Wire-in: в существующей `if status == 'unknown':` ветке после log_event добавлен dispatch в `_tt_handle_post_switch_unknown`. Outcome handling:
- `'recovered'` → break (success path как match)
- `'failed'` → return False (hard fail)
- `'mismatch'` → update local `status='mismatch'` + `current=recovered_current`, fall through в existing mismatch handler (`MAX_PICK_ATTEMPTS` retry)

### 3 новых helper-метода в `AccountSwitcher` class

1. `_is_tt_feed_after_pick(self, xml, header_y_max=260) -> bool` — distinct markers через `set` (threshold ≥2/3); защита от counter-based false-positive (Codex round 1).
2. `_navigate_to_profile_tab(self) -> bool` — wrapper над Phase 1 `_tt_smart_tap_profile` + `time.sleep(2.0)` post-tap.
3. `_tt_handle_post_switch_unknown(self, target, xml_after_pick, header_y_max, label, attempt) -> tuple[str, Optional[str]]` — recovery dispatcher, 5 paths (non-feed-fail / nav-fail / verify-match / verify-mismatch / verify-unknown).

### `publisher_kernel.py:_SWITCHER_STEP_TO_CATEGORY`

2 новых mapping для observability через `error_code` поле:
- `'tt_4_target_profile': 'tt_post_switch_verify_unrecoverable'`
- `'tt_4_target_profile_renav': 'tt_post_switch_verify_unrecoverable'`

### 4 новых event categories

| Name | type | Семантика |
|---|---|---|
| `tt_post_switch_feed_after_pick` | warning | unknown + feed-markers detected (новое TT UX) |
| `tt_post_switch_renav_failed` | error | `_navigate_to_profile_tab` returned False (Phase 1 bound-nav fail) |
| `tt_post_switch_recovered_via_renav` | account_switch | re-verify after navigate = match (recovery успешен) |
| `tt_post_switch_verify_unrecoverable` | error | final fail (non-feed / nav-fail / verify-unknown after renav) |

### Tests

`tests/test_post_switch_renav.py` — 12 unit-тестов:
- 5 helper tests (включая `test_is_tt_feed_duplicate_marker_returns_false` — regression guard для Codex round 1)
- 5 recovery tests (4 paths + 1 defensive nav-fail)
- 2 mapping tests

Live: 12/12 PASS + 32/32 baseline TT switcher tests PASS = 44 PASSED локально.

## Execution stats

- **Spec:** brainstorm → v1 → Codex v1-round-1 (1 P2) → v2 CLEAN
- **Plan:** v1 → Codex v1-round-1 (2 P2) → v2 → Codex v2-round-1 (1 P2) → v3 → Codex v3-round-1 (1 P3) → v4 CLEAN
- **Implementation:** subagent-driven-development; 5 task dispatches:
  - T1: branch setup (inline)
  - T2: helper TDD (implementer + spec review + code review + 1 fix iteration)
  - T3: dispatcher + wire-in (implementer + spec review + code review + 1 **Critical fix** — `_navigate_to_profile_tab` не существовал, поймано через `feedback_class_vs_instance_test_calls`)
  - T4: kernel mapping (implementer + combined review)
  - T5: full suite (inline)
- **Final pre-merge review:** SHIP 🟢
- **Codex review на full PR diff:** CLEAN, 0 issues
- **5 commits** на ветке (squashed)

## Critical catch

Code reviewer T3 поймал что `_navigate_to_profile_tab` НЕ существовал в коде — spec и plan оба ошибочно treated его как Phase 1 deliverable, но Phase 1 (`aec09a9`) добавил только `_tt_bottom_nav_profile_bounds_from_xml` (low-level bounds helper). Тесты passed потому что mocked на instance (`sw._navigate_to_profile_tab = MagicMock(...)`) — bypassing class-level AttributeError. В прод бы получили `AttributeError` → masquerade как `switch_failed_unspecified` (тот самый error_code, который только что закрыли PR #33).

Fix: добавлен thin wrapper над `_tt_smart_tap_profile` (line 1830, no-arg `-> bool`, Phase 1 label-based bottom-nav) + 2s post-tap sleep.

Лесон: memory `feedback_class_vs_instance_test_calls` (инцидент 2026-04-28 `_is_specific_reel_url` 46h регрессия) — pattern полностью повторился. Class-level hasattr check добавлен в T3 fix subagent prompt для smoke-проверки перед commit.

## Success metrics (24h post-deploy)

Tracking deferred to background — собрать через 24ч (≈2026-05-12 18:00 UTC). SQL queries:

```sql
-- 1. Recovery работает на real traffic
SELECT meta->>'target', meta->>'attempt', created_at
FROM publish_tasks, jsonb_array_elements(events) e
WHERE e->'meta'->>'category' = 'tt_post_switch_recovered_via_renav'
  AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
-- Expect: ≥1 row (recovery engages on real feed-after-pick).

-- 2. Unrecoverable baseline (non-feed unknown / nav-fail)
SELECT e->'meta'->>'category', e->'meta'->>'step', COUNT(*)
FROM publish_tasks pt, jsonb_array_elements(events) e
WHERE pt.platform='TikTok'
  AND e->'meta'->>'category' = 'tt_post_switch_verify_unrecoverable'
  AND pt.created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1, 2;
-- Expect: small count; investigate если значимо.

-- 3. tt_upload_confirmation_timeout drop vs pre-deploy
SELECT DATE(created_at), COUNT(*)
FROM publish_tasks
WHERE platform='TikTok' AND error_code='tt_upload_confirmation_timeout'
  AND created_at > NOW() - INTERVAL '48 hours'
GROUP BY 1 ORDER BY 1;
-- Expect: count за 2026-05-12 < count за 2026-05-11.

-- 4. tt_post_switch_handle_unknown → feed-detect chain coverage
WITH ev AS (
  SELECT pt.id, e->'meta'->>'category' AS cat
  FROM publish_tasks pt, jsonb_array_elements(events) e
  WHERE pt.platform='TikTok' AND pt.created_at > NOW() - INTERVAL '24 hours'
)
SELECT
  SUM(CASE WHEN cat='tt_post_switch_handle_unknown' THEN 1 ELSE 0 END) AS unknowns,
  SUM(CASE WHEN cat='tt_post_switch_feed_after_pick' THEN 1 ELSE 0 END) AS feed_detected,
  SUM(CASE WHEN cat='tt_post_switch_recovered_via_renav' THEN 1 ELSE 0 END) AS recovered,
  SUM(CASE WHEN cat='tt_post_switch_renav_failed' THEN 1 ELSE 0 END) AS nav_failed
FROM ev;
-- Expect: feed_detected ≈ unknowns (most unknowns now have feed markers); recovered = subset of feed_detected.
```

## Backlog (separate items, not in this PR)

- `tt_fg_lost` downstream music-rights accept (P1) — AI Unstuck кликает nav buttons после accept → TikTok уходит в background. Pattern из pt 4523 / 4624.
- RC-B (60% music-rights post-accept timeouts) — ждёт ≥5 XML dump'ов от `TT_DUMP_POST_MUSIC_RIGHTS_XML` (активирован 2026-05-11 14:21 UTC, evidence collection ongoing).
- `TT_SEED_HARDENING_SAASCENE_ENABLED` activation — ждёт XML evidence про `SAASceneWrapperActivity` в top_activity.
- IG / YT same pattern check — если когда-то pick→non-profile появится на IG/YT, Approach A generalized в Approach B candidate (shared verify-handle с recovery).
- `was_feed` structured meta field на `tt_post_switch_verify_unrecoverable` event — сейчас implicit в reason string; structured field нужен только при automated triage parsing.

## Related

- PR #28 (`8ec5c53`) — TT music rights confirmation dialog handler
- PR #29 (`f49e877`) — TT post-publish success detection
- PR #32 (`f9315cd`) — TT music-rights coverage + post-accept instrumentation
- PR #33 (`d33719a`) — TT `switch_failed_unspecified` root cause fix (PRs #34 unblocked one of its downstream patterns)
- Phase 1 (`aec09a9`) — TT `_tt_bottom_nav_profile_bounds_from_xml` + bound-nav (reused via `_tt_smart_tap_profile` в `_navigate_to_profile_tab` wrapper)
