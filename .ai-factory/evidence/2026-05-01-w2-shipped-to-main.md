# W2 obstacle KB — SHIPPED to main + deployed (2026-05-01)

## TL;DR

W2 obstacle KB полностью смержен в `main` (single trunk), оба PM2 publisher-сервиса
рестартованы на свежем коде. Shadow probes гоняются live на 5 call-sites. Zoo из
26+ feature/fix branches убит — остался только `main`.

## Что отгружено сегодня

**26 коммитов** через 6 merge waterfalls в `GenGo2/delivery-contenthunter`:

| Commit | Что |
|---|---|
| `8a428cc` | W2.C — B1 seed (8 hardcoded markers → publisher_obstacles) |
| `2d9c1e7` | hash dedup → `compute_obstacle_id` helper |
| `b73abf7` | wildcard Tier-2 matcher + partial index |
| `8263928 + 3d1a627 + 42f1919` | W2.D Task 15 — IG draft probe + Critical lowercase-platform fix + Option II placement |
| `f3e301f` | W2.D Task 16 — probe lifted to BasePublisher + OZON switcher wire |
| `83abb3d` | W2.D Task 17a — TT retap loop probe |
| `8686d63` | W2.D Task 17b — IG human-check 2-site probe |
| `b09b5a0` | merge feature/obstacle-kb-w2 → testbench (W2.E) |
| `1e9ca34` | merge testbench → main (W2 в prod-trunk) |
| `56ffc29 / 04f2d1e / a05a590 / 8cd58de` | absorbed 4 stale branches in cleanup |

## Final state

- `origin/main` HEAD `8cd58de` — single trunk
- Удалено 26 веток на origin (testbench + 25 merged feature/fix)
- Worktree `/home/claude-user/autowarm-testbench` на main
- Prod path `/root/.openclaw/workspace-genri/autowarm` pulled main
- PM2 `autowarm` (id 1, prod) + `autowarm-testbench` (id 32) — оба рестартованы
- DB `publisher_obstacles` = 8 seed rows; `publisher_obstacle_outcomes` = 0 пока
- Kill-switches: `obstacle_kb_disabled=false`, `obstacle_kb_lookup_only=true` → shadow mode

## 5 probe call-sites (Option II — fires когда handlers не сматчили)

1. IG camera-recovery loop tail (`publisher_instagram.py:764`)
2. Switcher OZON overlay (`account_switcher.py:3015`)
3. Switcher TT retap loop (`account_switcher.py:1741`)
4. Switcher IG human-check Site 1 (`account_switcher.py:1187`)
5. Switcher IG human-check Site 2 (`account_switcher.py:1274`)

## Verification

- 197 passed на pytest sanity (6 suites: obstacle, IG-recovery, overlay, account_switcher, TT switcher, publisher imports)
- 1 pre-existing fail (`test_reopen_via_home_taps_plus_then_reels_on_success_path`) — unchanged from main HEAD до merges
- 11 другие pre-existing fails (publish_guard, switcher_read_only, testbench_orchestrator) — не от W2

## Что дальше (W3)

- Branch: `feature/obstacle-kb-w3` от main `8cd58de`
- Plan tasks 19-26: Anthropic Sonnet 4.6 vision + AI Unstuck shim shadow apply + 7-day soak
- См. `project_publisher_obstacle_kb.md` memory + `2026-04-30-publisher-obstacle-kb-implementation.md` plan
