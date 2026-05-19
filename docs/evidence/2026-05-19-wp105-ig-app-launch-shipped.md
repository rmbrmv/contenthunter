# Evidence — WP #105 SHIPPED 2026-05-19

**WP:** https://openproject.contenthunter.ru/wp/105 (статус → Тестирование)
**PR:** https://github.com/GenGo2/delivery-contenthunter/pull/76 (squash-merged f480219)
**Branch:** `feat/wp105-ig-app-launch-stale-uiautomator` (deleted после merge)

## Триаж

- 14 fails `ig_app_launch_failed` за 7д (2026-05-13…2026-05-19), 3 сегодня
- 13 уникальных устройств на всех 6 raspberries (Pi #2/3/5/7/9/10) — НЕ device-specific
- 13/13 фейлов: pre-check `_ensure_app_foregrounded` success → `_open_app` fail ~86s
- Screenshot +1s после fail показывает IG уже на экране

## Root cause

Два метода foreground detection использовали разные источники:
- `_ensure_app_foregrounded` → `dumpsys topResumedActivity` (fresh ActivityManager state)
- `_open_app._foreground_pkg` → `uiautomator dump` primary, dumpsys fallback (отставал до 60-90s на Samsung S21)

После `am start` ActivityManager сразу регистрирует IG как `topResumedActivity`, но uiautomator продолжал возвращать дамп launcher'а ещё ~80s. `_open_app` через 3 am-start attempts по uiautomator всё ещё видел launcher → fail.

## Что сделано

Defense-in-depth в `account_switcher.py:_open_app`:

**L1 — cross-source `_foreground_pkg(target_pkg)`**
- Spahивает оба источника параллельно
- Trust target когда uiautomator==target (UI ground-truth)
- Trust target когда dumpsys==target И uiautomator ∈ {launcher, empty} — с подтверждающим poll до 2.4s (отсекает теоретический dumpsys-stale-after-crash)
- Для permission/sbrowser overlay возвращает uiautomator package → `_dismiss_blocking_overlays` отрабатывает

**L2 — settle-wait 15s** после 3 am-start attempts, polling каждую секунду. Ловит race где IG появляется 1-5s после last poll.

**L3 — observability**: event `switcher_foreground_pkg_disagree` при расхождении источников + `current_pkg_dumpsys` в meta при final fail.

## Codex review

3 round'а:
1. Round 1 (spec): 0 issues
2. Round 2 (impl): P2 — повторный shortcut на permissioncontroller overlay → ограничил stale-pattern launcher/empty
3. Round 3 (impl v2): P2 — dumpsys-stale-after-crash false positive → добавил подтверждающий poll 2.4s
4. Round 4 (final): 0 issues

## Tests

- 7 новых mock-based в `tests/test_account_switcher.py`:
  - `test_open_app_dumpsys_target_uiautomator_stale_then_catches_up_returns_true` — основной bug scenario
  - `test_open_app_uiautomator_target_dumpsys_launcher_returns_true` — symmetric
  - `test_open_app_both_sources_launcher_returns_false` — real fail
  - `test_open_app_both_sources_target_returns_true_no_disagree` — healthy
  - `test_open_app_dumpsys_target_uiautomator_permissioncontroller_does_not_shortcut` — Codex P2 round 2
  - `test_open_app_dumpsys_target_uiautomator_persistent_launcher_does_not_shortcut` — Codex P2 round 3
  - `test_open_app_settle_wait_catches_late_arrival` — L2
  - `test_open_app_settle_wait_respects_deadline` — L2 safety
- 1 update в `tests/test_overlay_dismiss.py` — adapt sbrowser test к cross-source dumpsys call count
- 74 теста в test_account_switcher.py + test_overlay_dismiss.py зелёные
- Pre-existing main фейлы (vision/orchestrator/publish_guard/intermediate_probes) НЕ затронуты — verified `git stash` reproduction

## Deploy

- PR #76 squash-merged 2026-05-19 11:46 UTC
- Prod `/root/.openclaw/workspace-genri/autowarm/` → git pull → f480219
- PM2 restart НЕ нужен: Python публикатор spawnится свежим на каждую задачу (server.js execFile)

## Verification window 24h

- T+1h: проверить что новые `ig_app_launch_failed` fails не растут
- T+6h: query events для `switcher_settle_wait_recovered` — сколько раз L2 ловит race
- T+24h: финальная метрика `ig_app_launch_failed` < 2 fails/день

Acceptance criteria fulfilled:
- [x] 7 unit-тестов passing
- [x] Healthy IG-switch на testbench не регрессирует (74/74 зелёные)
- [x] Cherry-pick / PR merge в prod без конфликтов (fast-forward)
- [ ] 24h после prod: `ig_app_launch_failed` < 2/день (verify pending)
- [ ] `switcher_settle_wait_recovered` event minimum 1 раз (verify pending)
- [ ] WP #105 → Готово после positive verification

## Связанные

- WP #73 — `ig_share_tap_no_progress` (топ-1 IG fail, 31 fails 7д, 5 сегодня) — отдельный backlog, refresh-комментарий запостил
- WP #74 Round 2 — YT foreign-foreground guard (PR #72 SHIPPED 2026-05-18) — концептуально близко
- WP #102 — `ig_target_not_in_picker` (топ-3, 19 fails 7д) — отдельный backlog
