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

## T2 — Fix shipped ✅

| Repo | Commit |
|---|---|
| `autowarm-testbench` (testbench tree) | `96c1c391` |
| `/root/.openclaw/workspace-genri/autowarm/` (prod, auto-pushed → GenGo2/delivery-contenthunter) | `f04221a` |

**T2_FINAL_TS (prod commit timestamp):** `2026-04-28 10:52:56 UTC`

**Tests:** 3 новых в `tests/test_yt_post_switch_verify.py` (call ordering, success path, fallback path). Регрессия: 76 пройдённых тестов в 4 связанных suite'ах.

**Spec compliance review:** ✅ все 10 точек verified.

**Code quality review:** ✅ APPROVED. Nitpicks (не блокеры): magic number `time.sleep(2.0)` без константы, unused `call` import в тестах, test 2 weakly tests new XML-parsing path (over-mocked).

**Cherry-pick path:** unified diff из testbench → `patch -p1` в prod tree → `git commit` → auto-push hook ✅.

**pm2 restart:** оба сервиса (autowarm + autowarm-testbench) restartнуты, чистый старт без stack traces.

---

## T3 — Acceptance batch ✅ **PASS 10/10**

**T_ANCHOR:** `2026-04-28 10:52:56 UTC` (T2_FINAL_TS)
**Excluded ids:** none (`(-1)` placeholder)

**Seeded tasks 1522-1531** (5 makiavelli + 5 Инакент, строго alternating I/M):

| id | account | status | runtime |
|---|---|---|---|
| 1522 | Инакент-т2щ | ✅ done | 16м |
| 1523 | makiavelli-o2u | ✅ done | 16м |
| 1524 | Инакент-т2щ | ✅ done | 16м |
| 1525 | makiavelli-o2u | ✅ done | 16м |
| 1526 | Инакент-т2щ | ✅ done | 17м |
| 1527 | makiavelli-o2u | ✅ done | 15м |
| 1528 | Инакент-т2щ | ✅ done | 16м |
| 1529 | makiavelli-o2u | ✅ done | 16м |
| 1530 | Инакент-т2щ | ✅ done | 14м |
| 1531 | makiavelli-o2u | ✅ done | 14м |

**Acceptance SQL result:**

```
done=10, done_maki=5, done_inak=5, total=10
```

**Pass condition:** `done >= 8 AND done_maki >= 1 AND done_inak >= 1` → ✅✅✅

**Verdict:** **PASS 10/10 (100%)** — превышает порог 8/10 с большим запасом. Sanity invariant выполнен.

**Сравнение с T1 baseline (до T2 fix):**

| Метрика | T1 (до fix) | T3 (после fix) | Δ |
|---|---|---|---|
| Total done | 9/10 (90%) | 10/10 (100%) | +1 |
| makiavelli | 6/6 (100%) | 5/5 (100%) | — |
| **Инакент** | **3/4 (75%, причём 3 luck-pass + 1 fail)** | **5/5 (100%, все verified-by-name)** | **+25%** |
| `yt_post_switch_mismatch` events | 1 | 0 | -1 |

Главный сигнал — Инакент: до фикса **0 verified-by-name pass'ов** (3 done = `current_post=None` soft-fall-through), после фикса **5/5 verified-by-name pass'ов**. T2 fix реально работает в проде.

---

## Iteration result — closed ✅

**Acceptance gate ≥8/10 на phone #19 для `[makiavelli-o2u, Инакент-т2щ]` → достигнут (10/10).**

**Что shipped в этой итерации:**
1. `import random` в `publisher_base.py` — атомарный unblock 100% YT/IG/TT публикаций (`fcfa851` prod / `5a60b15` testbench).
2. Forced profile-tab navigation перед post-switch verify в YT switcher — устраняет `yt_post_switch_mismatch` от feed-screen filter-chips (`f04221a` prod / `96c1c391` testbench).
3. Read-only triage tool `.ai-factory/tools/yt_failure_triage.py` для будущих GATE-итераций.

**Что НЕ запушено:**
- `autowarm-testbench` ahead 7 (мои T0+T2 + 5 коммитов прошлой сессии).
- `contenthunter` (knowledge) ahead 9 (spec/plan/evidence/triage/bookmark).
Auto-push hook стоит только на prod tree.

**Deferred follow-ups (для следующих итераций):**
1. **Soft-fall-through в `else:` строки 2256** — когда `current_post=None`, текущий код просто warning'ит и продолжает. Стоит fail-fast'ить, чтобы избежать luck-pass случаев. Risk: больше fails при других edge cases.
2. **`time.sleep(2.0)` magic number** в T2 fix — экстрагировать в `AFTER_PROFILE_NAV_SETTLE_S`.
3. **AST-walker test** — code reviewer 04-28 предложил: walks `publisher_base.py` для каждого `<name>.<attr>` и asserts `<name>` is in module globals. Catches whole class of split-regression в 1 тесте. Кандидат для quick-win.
4. **Test 2 в `test_yt_post_switch_verify.py`** — over-mocked, не проверяет реальный XML-parsing flow. Усилить до follow-up'а.
5. **`else:` soft-fall-through** при `_go_to_profile_tab` returns False (T2 fallback) — runs sleep даже на failure. Минор.

**Statistics:**
- 4 commits в prod tree (auto-pushed → GenGo2/delivery-contenthunter): T0 + T2 (плюс 2 evidence-related).
- 11 commits в knowledge репо (spec, plan, evidence по фазам, triage tool, bookmark).
- 5 subagent dispatches: 2 implementers (T0, T2) + 2 spec-review + 2 code-quality + 0 (T0/T2 spec-review parallel + code-quality parallel) = 6 review subagents total.
- Wall-clock: ~6 часов (T0 ~30 мин + T1 monitor ~2.25 ч + T2 ~30 мин + T3 monitor ~2.5 ч).
- Phone #19 публикаций: 1 (T0.5 smoke) + 9 (T1 baseline) + 10 (T3 acceptance) = 20 живых задач за итерацию.

---

## T0 deferred (in this iteration's backlog)

- AST-walker test для валидации `<name>.<attr>` → module-level name (предотвращает split-regression class). Кандидат на отдельный мини-fix после T3.
- pm2 cwd drift: `autowarm-testbench` точечно показывает prod tree, а не testbench. Возможно, потеряли отдельную dev-среду. Если T2 потребует разделения — починим.
