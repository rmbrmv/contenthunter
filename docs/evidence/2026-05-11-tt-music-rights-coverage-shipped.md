# TT Music-Rights Coverage + Post-Accept Instrumentation — Shipped 2026-05-11

**PR:** [GenGo2/delivery-contenthunter#32](https://github.com/GenGo2/delivery-contenthunter/pull/32)
**Merge commit:** `f9315cd` (squash; branch `feat/tt-mr-cov-20260511` deleted)
**Prod state:** `/root/.openclaw/workspace-genri/autowarm` @ `f9315cd`; PM2 autowarm (id=34) restarted (uptime ~10s at deploy time)
**Spec:** v12 (`docs/superpowers/specs/2026-05-11-tt-music-rights-coverage-and-post-accept-design.md`, Codex CLEAN после 12 ревизий)
**Plan:** v3 (`docs/superpowers/plans/2026-05-11-tt-music-rights-coverage-and-post-accept-plan.md`, Codex CLEAN после 3 ревизий)

## Context

После PR #28 (music-rights handler shipped 2026-05-10) — 0 успешных публикаций TT с music-rights диалогом за 72h. Разведка 2026-05-11 выявила:
- **RC-A ~40%**: handler не fires — TT обновил title-node (4536, 4488, 4482)
- **RC-B ~60%**: handler сработал, post-accept screen не находится (4542, 4541, 4540, 4539)

Критическое открытие: `_tt_infer_post_publish_success` (PR #29) уже в проде, но возвращает False для post-music-rights state — наш изначальный streak-gate не помог бы. Это привело к scope-cut v7+.

## Shipped

**6 новых helper-методов в `TikTokMixin`:**
1. `_save_dump_for_fallback_review(ui_xml, suffix)` — `task_` token в filename
2. `_detect_tt_music_rights_dialog_fallback(ui_xml)` — substring + checkbox-label EXACT + button EXACT + common Dialog ancestor
3. `_detect_tt_music_rights_dialog_evidence_only(ui_xml)` — substring + generic checkbox
4. `_init_music_rights_state()` — reset 4 state vars
5. `_after_music_rights_handled(wait)` — post-accept tracking + counter decouple
6. `_maybe_dump_post_music_rights_xml(wait, ui)` — triple-guard XML dump + log_event с top_activity meta

**`_handle_tt_music_rights_dialog` rewritten** — hybrid path (strict → fallback → evidence-only + throttle).

**`_tt_infer_post_publish_success` extended** — flag-gated SAASceneWrapperActivity → SEED через runtime branch.

**3 feature flag'а, all default false:**
- `TT_MUSIC_RIGHTS_FALLBACK_ENABLED`
- `TT_SEED_HARDENING_SAASCENE_ENABLED`
- `TT_DUMP_POST_MUSIC_RIGHTS_XML`

**27 новых unit-тестов** (46/46 PASS = 19 baseline + 27 new).

**10 commits** на ветке `feat/tt-mr-cov-20260511` (squashed).

## Execution stats

- **Spec:** brainstorm → v1..v12 (12 ревизий Codex; scope-cut RC-B после P1 reject на v6 round 1)
- **Plan:** v1..v3 (3 ревизии Codex; refactor inline-в-loop → 3 helpers)
- **Implementation:** 8 implementer subagent dispatches + 8 spec/quality review pairs. 1 review-loop iteration (Task 2 filename `task_` token fix).

## Rollout plan (post-merge, manual)

Deploy уже выполнен (prod pulled f9315cd, PM2 restarted). Все 3 flag default false → no-op rollout активен.

**Шаги активации:**

1. **TT_DUMP_POST_MUSIC_RIGHTS_XML=true** (1-2h evidence collection):
   ```bash
   cd /root/.openclaw/workspace-genri/autowarm
   sed -i '/^TT_DUMP_POST_MUSIC_RIGHTS_XML=/d' .env 2>/dev/null || true
   echo "TT_DUMP_POST_MUSIC_RIGHTS_XML=true" >> .env
   sudo -u root pm2 restart 34 --update-env
   ```
2. **TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true** (RC-A coverage):
   ```bash
   sed -i '/^TT_MUSIC_RIGHTS_FALLBACK_ENABLED=/d' .env 2>/dev/null || true
   echo "TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true" >> .env
   sudo -u root pm2 restart 34 --update-env
   ```
3. **TT_SEED_HARDENING_SAASCENE_ENABLED=true** ТОЛЬКО после evidence query показал `SAASceneWrapperActivity` в `top_activity` для failed post-accept tasks (см. spec Rollout Step 3a SQL).

## Activation log (Rollout Step 1 + Step 2)

| Flag | Activated at (UTC) | PM2 restart | Notes |
|---|---|---|---|
| `TT_DUMP_POST_MUSIC_RIGHTS_XML=true` | 2026-05-11 ~14:18 | id=34 restart=12 | Step 1 — evidence collection |
| `TT_MUSIC_RIGHTS_FALLBACK_ENABLED=true` | 2026-05-11 ~14:21 | id=34 restart=14 | Step 2 — RC-A coverage |

**Baseline events (24h pre-activation):**
- `tt_music_rights_accepted`: 13/24h (last 10:25 UTC) — strict matcher working
- `tt_music_rights_fallback_match`: 0 (новое поведение — ждём ≥1 за 24h)
- `tt_music_rights_unhandled_suspect`: 0 (FP guard target: 0 followed by `publish_failed_generic`)
- `tt_post_music_rights_dump`: 0 (evidence target: ≥5 от failed `mr_accept=true, pp_inferred=false`)

Прод TT публикации за 7 days: **277 failed / 1 done** (Top error_code: `tt_upload_confirmation_timeout` 26/48h). RC-A targets ~40% этих fails (handler не fires из-за обновлённого title-node).

`TT_SEED_HARDENING_SAASCENE_ENABLED` — пока **НЕ активирован**, ждёт XML evidence для подтверждения `SAASceneWrapperActivity` в top_activity.

## Success metrics

- **RC-A win condition:** ≥1 event `tt_music_rights_fallback_match` за первые 24h после activation.
- **RC-A FP guard:** 0 events `tt_music_rights_unhandled_suspect` followed by downstream `publish_failed_generic`.
- **SEED side-effect:** `tt_post_publish_success_inferred` rate drop ≤10% после activation.
- **Evidence for next round:** ≥5 XML dumps собрано для failed tasks `mr_accept=true, pp_inferred=false`.

## Not addressed (out of scope this round)

- RC-B success rate (60% post-accept timeouts) — `_tt_infer_post_publish_success` returns False; positive-path detection awaits XML evidence для next-round spec.

## Related

- PR #28 (music-rights handler v1): `8ec5c53`
- PR #29 (post-publish success detection): `f49e877`
- Memory: `project_tt_music_rights_dialog_shipped.md`, `project_tt_music_rights_v12_coverage_pr32.md`
