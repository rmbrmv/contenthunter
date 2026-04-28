# Evidence — YT Switcher Iteration 2 (2026-04-28)

**Plan:** `.ai-factory/plans/yt-switcher-iter2-20260428.md`
**Spec:** `.ai-factory/specs/2026-04-28-yt-switcher-iter2-design.md`
**Branch (knowledge repo):** `fix/testbench-publisher-base-imports-20260427`

---

## T0 — Random import regression fix

**Status:** ✅ shipped

| Repo | Commit |
|---|---|
| `autowarm-testbench` (testbench tree) | `5a60b15` |
| `/root/.openclaw/workspace-genri/autowarm/` (prod, auto-pushed → GenGo2/delivery-contenthunter) | `fcfa851` |
| `contenthunter` (knowledge — triage tool) | `35e599e` (T1.1 prep, не часть T0) |

**T0_TS (prod commit timestamp):** `2026-04-28 08:18:35 UTC`

**TDD chain (Task T0-IMPL):**
- Step 2 fail: `FAILED tests/test_publisher_imports.py::test_publisher_base_random_imported` — AssertionError as expected.
- Step 4 pass: `PASSED [100%]` after `import random` added.
- Step 5 full: `11 passed in 0.06s` — no regressions in pre-existing 10 tests.

**Spec compliance review:** ✅ all 5 points verified (import location, test signature, docstring with line refs + date, scope = 2 files, regression suite green).

**Code quality review:** ✅ APPROVED. Reviewer noted backlog item (deferred): AST-walker test that validates every `<name>.<attr>` reference resolves to a module-level name — would catch this whole class of split-regression in 1 test. Not pulled into this iteration.

**Smoke verification (Task T0.5):**

| Field | Value |
|---|---|
| task_id | 1512 |
| platform | YouTube |
| account | makiavelli-o2u |
| device_serial | RF8YA0W57EP |
| adb_port | 15068 |
| media_path | /tmp/publish_media/pq_736_1777354462096.mp4 |
| pre_warm_videos | 1 |
| terminal status | **`done`** |
| `random not defined` in events | **false** |
| event count | 51 |
| runtime | 15m 35s |

**Conclusion:** prod runtime читает обновлённый `publisher_base.py` с `import random`, pre-warm проходит, switcher отрабатывает, makiavelli-o2u публикуется. T0 разблокировал систему.

**pm2 state observation:**

| App | PID | exec cwd | status |
|---|---|---|---|
| `autowarm` | 1482202 | `/root/.openclaw/workspace-genri/autowarm` | online (uptime 0s after restart) |
| `autowarm-testbench` | 1482216 | `/root/.openclaw/workspace-genri/autowarm` | online (uptime 0s after restart) |

**Drift note:** `autowarm-testbench` exec cwd = prod tree, не `/home/claude-user/autowarm-testbench/`. По факту обе pm2-аппы запускают prod-код. Subagent commit `5a60b15` в testbench-tree сейчас НЕ runtime — но содержит идентичную правку, так что состояние консистентно. Для T2 фиксов это означает: код менять В ПРОД (`/root/.openclaw/.../autowarm/`), не testbench tree, либо переключать pm2 cwd обратно.

---

## T1 — Live baseline gathering ✅

**Triage tool:** `.ai-factory/tools/yt_failure_triage.py` создан (T1.1, commit `35e599e`).

**Baseline window:** 2026-04-28 08:20:13 → 08:37:42 UTC (10 задач, alternating M/I после 1513 для форсирования switcher на каждой задаче).

**Seeded tasks 1513-1521** (1512 был T0.5 smoke):

| id | account | status | error_code |
|---|---|---|---|
| 1512 | makiavelli-o2u | done | `unknown` |
| 1513 | makiavelli-o2u | done | `unknown` |
| 1514 | Инакент-т2щ | done | `unknown` |
| 1515 | makiavelli-o2u | done | `unknown` |
| 1516 | Инакент-т2щ | **failed** | `yt_post_switch_mismatch` |
| 1517 | makiavelli-o2u | done | `unknown` |
| 1518 | Инакент-т2щ | done | `unknown` |
| 1519 | makiavelli-o2u | done | `unknown` |
| 1520 | Инакент-т2щ | done | `unknown` |
| 1521 | makiavelli-o2u | done | `unknown` |

**Aggregated:**
- Total done: **9/10** (90%)
- makiavelli-o2u: 6/6 (100%)
- Инакент-т2щ: 3/4 (75%)
- B6 v3 foreground-guard hits: 0 (никто не упал на wrong-app foreground — B6 v3 работает без живых hit'ов в этом окне)
- Failure reasons: только `yt_post_switch_mismatch` × 1

**Acceptance threshold (формально):** done≥8 ✅, sanity ≥1 на каждый аккаунт ✅. **Pass даже без T2.**

---

## Discovery — `yt_post_switch_mismatch` root cause (task 1516 deep-dive)

**Симптом:** Switcher tапнул правильный gmail-row для Инакент-т2щ, но post-switch verify прочитал «скетч-шоу» как current account → fail.

**Root cause через анализ UI dump'а task 1516 (`/tmp/task1516_yt5_dump.xml`):**

После gmail-tap'а в picker'е YT возвращается на **home feed**, не на profile screen. Верхние 260px содержат filter-чипы YouTube ленты:

```
y= 96  desc='YouTube' / 'Введите запрос' / 'Уведомления'
y=231  desc='фильтры'
y=254  text='Меню "Навигатор"' / 'Все' / 'Сейчас в эфире' / 'Скетч-шоу' / 'Теленовеллы'
```

**«Скетч-шоу»** — это не имя канала, а категориальный фильтр-чип. `_looks_like_username` ошибочно матчит его (из-за дефиса), `get_current_account_from_profile` сортирует по y и возвращает первый username-like токен в y<260 → «скетч-шоу».

**Сравнение с task 1514 (Инакент done):** тот же UI dump, но в y<260 присутствовал только `'Меню "Навигатор"'` (без filter-чипов — вероятно, ещё не догрузились). `get_current_account_from_profile` вернул `None` → код упал в else-branch (line 2256) → soft warning + продолжение публикации без verify. **Чисто стохастический pass.**

**Подтверждение пользователя через скринкаст** (4:08 видео): visible баннер «Вы вошли как Инакент (inakent06@gmail.com)» — switch реальный, gmail правильный. Баннер — короткоживущий toast, через 8s sleep до dump'а уже отсутствует.

**Заключение:** verify проверяет UI на неправильном экране. Fix должен принудительно navigate на profile screen перед dump'ом.

---

## GATE — decision

**Numbers:** done_total=9, done_maki=6, done_inak=3, total=10 → формально **SKIP_T2 → T3** acceptance.

**Override:** пользователь явно требует «обязательно починить этот баг» (yt_post_switch_mismatch, task 1516). Risk обоснован: 1514 (Инакент done) прошёл случайно — verify вернул None, не verified. То есть из 4 Инакент-задач реально verified by-name только 0 (3 done — luck, 1 failed — bug). Без fix'а в production риск публикации в чужой канал.

**Decision:** **ENTER_T2** с одним locked candidate.

**T2 scope:**
- Fix candidate 1: **yt-post-switch-on-profile-screen** — после picker-tap'а forced navigate на profile tab перед verify dump.
  - Где: `account_switcher.py:2213` (после `time.sleep(AFTER_SWITCH_WAIT_S)`) + `:2225` (перед `parse_ui_dump(xml_post)`).
  - Helper уже существует: `_go_to_profile_tab(cfg, step_name)` (строка 3124) с pivot_bar detection + foreground-guard.
  - Rationale: post-switch dump текущий стохастически попадает на feed, header_y_max=260 ловит filter-chips. Profile screen имеет стабильный header в y<260 с реальным username канала.

---

## T0 deferred (in this iteration's backlog)

- AST-walker test для валидации `<name>.<attr>` → module-level name (предотвращает split-regression class). Кандидат на отдельный мини-fix после T3.
- pm2 cwd drift: `autowarm-testbench` точечно показывает prod tree, а не testbench. Возможно, потеряли отдельную dev-среду. Если T2 потребует разделения — починим.
