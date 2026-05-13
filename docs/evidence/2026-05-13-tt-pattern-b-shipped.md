# TT Pattern B — SHIPPED 2026-05-13

**PR:** [#52](https://github.com/GenGo2/delivery-contenthunter/pull/52) — squash-merged `76ecd4f` at 2026-05-13 17:29:34 UTC.
**Hotfix PR:** [#54](https://github.com/GenGo2/delivery-contenthunter/pull/54) — squash-merged `967d95e` at 2026-05-13 17:45:03 UTC. Live smoke caught `AttributeError: 'DevicePublisher' object has no attribute 'adb_shell'` — the orchestrator called `self.p.adb_shell(...)` for the Stories-pivot BACK keyevent, but the proxy exposes `self.p.adb(...)`. Unit tests masked the bug because `_FakeProxy` defined the wrong method name. 1-character production fix + mock-shape sync.
**Deploy:** PM2 `autowarm` restart at 2026-05-13 17:30:50 UTC (PR #52) + 2026-05-13 17:45:13 UTC (PR #54 hotfix). `exec cwd = /root/.openclaw/workspace-genri/autowarm` verified.
**Spec:** `docs/superpowers/specs/2026-05-13-tt-pattern-b-profile-header-anchor-design.md` (codex clean ×6 rounds).
**Plan:** `docs/superpowers/plans/2026-05-13-tt-pattern-b-profile-header-anchor-plan.md` (codex clean ×6 rounds, subagent-driven execution).

## What shipped

Probe-and-pivot orchestrator for the TikTok account-switcher. Closes the 19/24h `tt_account_sheet_closed_before_parse` spike caused by TT changing the profile-username tap behaviour — tap now opens Stories/LIVE viewer instead of the account-switcher bottomsheet.

**Architecture:**
- New orchestrator `_open_tt_account_switcher` in `AccountSwitcher`. Phase 1: probe old path up to 2× (preserves older TT versions). Phase 2 (on Stories detection): `adb keyevent KEYCODE_BACK` → tap «Меню профиля» (RU+EN cd) → search drawer for broad-anchor trigger → tap → verify bottomsheet via positive signature (`+ Добавить/Add аккаунт/account` OR ≥2 `@handles` below y=600).
- 3 new pure-function helpers (`_detect_tt_stories_viewer`, `_find_tt_account_switcher_anchor_in_drawer`, `_has_tt_bottomsheet_signature`).
- Module-level `TT_DRAWER_ACCOUNT_TRIGGERS` priority list + `_top_labels` forensic helper.
- Callsite in `_switch_tiktok` (L2298–L2323) collapsed from 44-line retry loop to 26 lines (orchestrator call + `_TT_ERR_TO_STEP` mapping → `_fail`).
- 6 new entries in `publisher_kernel._SWITCHER_STEP_TO_CATEGORY` for Pass-2 step-fallback resolution.

**5 invariants enforced and tested:**
1. Every non-success return emits exactly one `error`-type `log_event` with `meta.category == returned_code`.
2. Every `dump_ui` paired with `_save_dump` under stable step name (`_probe`, `_probe_retry1`, `_back`, `_menu`, `_drawer`, `_sheet`) — including the failure path of menu-button-not-found.
3. Sheet detection robust against drawer-still-open false positives (positive signature OR anchor-bounds mismatch with drawer trigger).
4. 2-attempt probe retry preserved from old retry loop.
5. `_fail` does not emit a competing canonical event; mapper resolves from `meta.category` on the most recent `error` event before the terminal `failed` event.

## Branch summary

12 commits, 3 files, +1300/-42:

| Commit | Topic |
|---|---|
| `be62872` | T1: TT_DRAWER_ACCOUNT_TRIGGERS + _top_labels |
| `3f31215` | T1 noqa F401 cleanup |
| `fb64d3a` | T2: _detect_tt_stories_viewer (RU+EN) |
| `f71eb8e` | T2 hit_time discrimination gap |
| `c4de69c` | T3: _find_..._anchor_in_drawer (two-pass) |
| `5df303a` | T3 smallest-area tie-breaker |
| `eadeec4` | T4: _has_tt_bottomsheet_signature |
| `a7775c0` | T5: orchestrator Phase 1 (probe + retry + Stories pivot) |
| `35b59d9` | T5 stub time.sleep in test module |
| `136f85b` | T6: orchestrator Phase 2 (menu → drawer → sheet) |
| `d4a4134` | T7: discriminator + canonical-event + signature regression tests |
| `69a2dea` | T8: callsite refactor + mapper extension |

## Quality gates passed

- Codex review of spec: 6 rounds, 0 P1/P2 final.
- Codex review of plan: 6 rounds, 0 P1/P2 final.
- Per-task spec compliance + code quality reviews (T1–T8): each clean after iteration (typically 1–2 fix rounds per task).
- Final holistic opus review of full branch: **APPROVED**, GO for PR, zero critical/important findings, 5 minor follow-ups deferred.
- 48 new unit tests + 73 pre-existing TT tests all green; 14 baseline failures elsewhere unchanged (DB-mock unrelated).

## Live verify

### Smoke (live)

**First smoke (pre-hotfix):** pq 2149 → task 5571 (clickpay_under). Status `failed`, `error_code='switch_failed_unspecified'`. Events show `tt_username_tap_opened_stories` detected (Stories pivot correctly identified), then crashed with `AttributeError: 'DevicePublisher' object has no attribute 'adb_shell'` at the BACK keyevent. Triggered hotfix PR #54.

**Second smoke (post-hotfix):** pq 2071 → task 5572 (clickpay_go). Completed 2026-05-13 ~17:57 UTC with `error_code='tt_account_menu_unknown_layout'`. **This is the acceptable first-iteration outcome** — orchestrator walked the full new path:

1. Phase 1 probe → Stories detected ✓
2. KEYCODE_BACK → returned to own profile (verified by `_tt_is_own_profile`) ✓
3. Tapped `cd='Меню профиля'` ✓
4. Drawer dumped + searched for broad-anchor → **no match** → fail-fast with `drawer_labels[]` payload ✓

**Iteration #2 design — diagnosed from `drawer_labels[]`:**

```json
[
  "0", "Лайки", "Повседневные расчёты в цифровом формате\n",
  "Понравившиеся видео", "Лайк", "Поделиться",
  "Меню профиля", "Профиль", "Ресурсы", "Баланс",
  "Личные инструменты", "Центр активности", "Время",
  "Видео офлайн", "Скачать", "Ваш QR-код",
  "Инструменты для творчества и бизнеса", "Инструменты для бизнеса",
  "Магазин", "TikTok Studio", "Инструменты автора",
  "Настройки и конфиденциальность", "Настройки"
]
```

**Finding:** No `TT_DRAWER_ACCOUNT_TRIGGERS` strings present. The new TT requires **2-step navigation** from the profile menu drawer: tap «Настройки и конфиденциальность» (or «Настройки») → opens a settings page → tap «Управление аккаунтами» on that page.

**Iteration #2 task:** Add a settings-nested path to the orchestrator — if `_find_tt_account_switcher_anchor_in_drawer` returns None, fall through to a second lookup against `['настройки и конфиденциальность', 'настройки', 'settings and privacy', 'settings']` → tap → re-dump → re-run `_find_tt_account_switcher_anchor_in_drawer`. Cap nesting at 1 level to avoid infinite recursion.

### 24h soak SQL (deadline: 2026-05-14 17:30 UTC)

```sql
WITH last_err AS (
  SELECT pt.id, MAX(ev.idx) AS idx
  FROM publish_tasks pt,
       jsonb_array_elements(pt.events) WITH ORDINALITY AS ev(value, idx)
  WHERE pt.platform = 'TikTok'
    AND pt.created_at >= '2026-05-13 17:30:50+00'
    AND pt.status = 'failed'
    AND ev.value->>'type' = 'error'
    AND ev.value->'meta'->>'category' IS NOT NULL
  GROUP BY pt.id
)
SELECT (pt.events->(le.idx::int - 1)->'meta'->>'category') AS cat,
       COUNT(*) AS n
FROM publish_tasks pt
JOIN last_err le ON le.id = pt.id
GROUP BY 1 ORDER BY 2 DESC;
```

**Acceptance:**
- `tt_account_sheet_closed_before_parse` falls from 19/24h pre-deploy to ≤5/24h.
- New codes (`tt_account_menu_unknown_layout` + `tt_drawer_tap_did_not_open_sheet`) ≤3/24h combined.
- If `tt_account_menu_unknown_layout > 3/24h` → iteration #2 from the `drawer_labels` evidence.

## Open follow-ups

From final holistic review (all Minor, none blocking):

1. Inline-vs-helper asymmetry on `tt_account_sheet_closed_before_parse` emission (single divergent path; functionally equivalent).
2. `menu_dump` redundancy with `back_dump` (same UI state; one extra `dump_ui` ~1-2s).
3. `_tap_profile_header` internal `_save_dump` is overwritten by orchestrator's `_save_dump` under same step name — pre-existing, low priority.
4. Plan said `PublisherBase`, code uses `BasePublisher` — implementation resolved silently.
5. No end-to-end test of menu-path through `_switch_tiktok` — smoke is the only true verification before prod.
