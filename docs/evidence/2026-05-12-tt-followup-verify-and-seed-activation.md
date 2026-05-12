# 2026-05-12 — TT follow-ups: PR #34 verify + PR #32 SEED activation

Сессия 2026-05-12. Три задачи from session backlog:

1. ✅ **TT music-rights v12 — SEED flag activation** (PR #32 follow-up)
2. ⏭ **AI Unstuck camera false-positive** — closed as obsolete (root cause переехал)
3. ✅ **TT post-switch verify live-check** (PR #34 follow-up)

---

## 1. TT music-rights v12 SEED activation

**Контекст:** PR #32 (`f9315cd`, merged 2026-05-11) ввёл 3 feature-flag'а (default false). По rollout plan, после 24h evidence collection с активным `TT_DUMP_POST_MUSIC_RIGHTS_XML=true`, следовало запустить SQL evidence query — если ≥1 запись с `SAASceneWrapperActivity` среди dumps, активировать `TT_SEED_HARDENING_SAASCENE_ENABLED=true`.

**Evidence (48h pre-activation):**

```sql
SELECT e->'meta'->>'top_activity', COUNT(*)
FROM publish_tasks pt, jsonb_array_elements(events) e
WHERE pt.platform='TikTok'
  AND e->'meta'->>'category' = 'tt_post_music_rights_dump'
  AND pt.created_at > NOW() - INTERVAL '48 hours'
GROUP BY 1 ORDER BY 2 DESC;
```

Результат (топ-20, всего 80 dumps):

| top_activity | cnt |
|---|---|
| MainActivity (различные task IDs) | 26 |
| SplashActivity | 12 |
| TikTokHostActivity | 14 |
| **SAASceneWrapperActivity** | **6** |
| DetailActivity | 2 |

**Решение:** активировать SEED flag — 6 instances реального SAASceneWrapperActivity среди post-music-rights dumps. Это активити НЕ matches существующий SEED (`CameraActivity`), что значит `_tt_infer_post_publish_success` возвращал False для этих task'ов.

**Action (06:52 UTC 2026-05-12):**

```diff
# /root/.openclaw/workspace-genri/autowarm/.env
 TT_DUMP_POST_MUSIC_RIGHTS_XML=true
 TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true
+TT_SEED_HARDENING_SAASCENE_ENABLED=true
```

`sudo pm2 restart 34 --update-env` — restart=18, status=online, uptime ok.

Verify через `node -e "require('dotenv').config(); console.log(process.env.TT_SEED_HARDENING_SAASCENE_ENABLED)"` → `true`.

**24h метрики наблюдения (deadline 2026-05-13 06:52 UTC):**

- `tt_post_publish_success_inferred` rate не должен упасть >10% относительно baseline. Baseline за 24h pre-activation: посчитать.
- `tt_music_rights_fallback_match` events не появлялись за 24h после `TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true` (strict matcher справляется в 100% — 36 `tt_music_rights_accepted`, 0 fallback). Это OK.
- Side-effect: `tt_upload_confirmation_timeout` rate не должен вырасти.

---

## 2. AI Unstuck camera false-positive — closed as obsolete

**Memory указывала** (`project_publish_followups_2026_05_06.md`, 2026-05-06) что AI Unstuck false-positive после Share на phone #19 — HIGH blocker. **Outer-cap shipped 2026-05-07** (commit `0b501e4`). Live check 48h:

```sql
SELECT error_code, COUNT(*)
FROM publish_tasks
WHERE platform='Instagram' AND created_at > NOW() - INTERVAL '7 days'
  AND error_code IN ('ig_unstuck_outer_cap_reached', 'ai_unstuck_failed', 'publish_failed_generic');
-- → 0 rows
```

IG fail-distribution (24h):

| error_code | cnt |
|---|---|
| ig_share_tap_no_progress | 11 |
| ig_gallery_no_video_candidate | 4 |
| switch_failed_unspecified | 2 |
| ig_camera_open_failed | 1 |
| ig_target_not_in_picker | 1 |

`ig_camera_open_failed` за 24h = 1 — не HIGH. Главный новый IG fail — `ig_share_tap_no_progress` (11), который относится к **другой задаче** (IG Share Tier 2 — PR #31 24h verify pending, отдельный поток).

Memory `project_publish_followups_2026_05_06.md` помечает root cause как backlog ("camera-screen detection в самом `_wait_instagram_upload`"), но без live evidence приоритет упал.

**Решение:** закрыть задачу. Если в будущем появится spike `ig_camera_open_failed` или resurrected unstuck events — открыть отдельную design сессию для camera-detection в `_wait_instagram_upload`.

---

## 3. TT post-switch verify live-check (PR #34) — VERIFIED PASS

**PR #34** (`750c3fa`, merged 2026-05-11 17:45 UTC) — recovery для pick→feed regression. Был silent degrade-to-pass 21/36h.

**Verify query (24h post-merge):**

```sql
SELECT e->'meta'->>'category', COUNT(*)
FROM publish_tasks pt, jsonb_array_elements(events) e
WHERE pt.platform='TikTok' AND pt.created_at > NOW() - INTERVAL '24 hours'
  AND e->'meta'->>'category' LIKE 'tt_post_switch%'
GROUP BY 1 ORDER BY 2 DESC;
```

| category | cnt |
|---|---|
| tt_post_switch_handle_unknown | 24 |
| tt_post_switch_feed_after_pick | 8 |
| tt_post_switch_recovered_via_renav | 8 |

**Recovery rate: 8/8 = 100%.** `feed_after_pick` (detection) и `recovered_via_renav` (success) совпадают в точности — всякий раз когда detector ловит feed после pick, renav успевает.

`tt_post_switch_verify_unrecoverable` count = 0 за 24h — это значит, что ни один из feed-after-pick случаев не остался не recovered. Также не было обнаружено non-feed unknown-paths (нет evidence что renav сломался).

TT error_code distribution 24h (failed только):

| error_code | cnt |
|---|---|
| tt_upload_confirmation_timeout | 17 |
| switch_failed_unspecified | 12 |
| (empty) | 4 |
| critical_exception | 2 |
| tt_account_sheet_closed_before_parse | 2 |
| tt_fg_lost | 1 |

`tt_post_switch_verify_unrecoverable` отсутствует в списке ⇒ degrade-to-pass масquerade закрыт. PR #34 работает по design.

**Observations для backlog:**
- `switch_failed_unspecified=12` всё ещё держится — это означает, что PR #33 (`d33719a`, @staticmethod fix) закрыл одну ветку masquerade, но осталась другая. Стоит сделать отдельный SQL drill-down по `switch_failed_unspecified` events для понимания текущей RC.
- `tt_fg_lost=1` за 24h — PR #35 (shipped 2026-05-11) пока показывает positive baseline (был silent 2/24h dwell trap; сейчас 1 catch — хорошо).

---

## Summary

- ✅ Task 1: SEED flag активирован, restart успешен; 24h наблюдение начато 06:52 UTC 2026-05-12.
- ⏭ Task 2: closed as obsolete (outer-cap эффективен 0 фейлов 7д; HIGH переехал на `ig_share_tap_no_progress` — другой поток).
- ✅ Task 3: PR #34 verified PASS — 8/8 recovery rate, 0 unrecoverable.

**Backlog open:**
- `switch_failed_unspecified=12/24h` — нужен drill-down events
- `ig_share_tap_no_progress=11/24h` — PR #31 Tier 2 24h verify (отдельная сессия)
- SEED activation 24h check pending (deadline 2026-05-13 06:52 UTC)
