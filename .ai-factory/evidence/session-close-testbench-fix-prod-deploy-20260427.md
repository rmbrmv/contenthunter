# Session close — testbench NameError fix + prod deploy split (2026-04-27 PM)

## TL;DR

Пользователь открыл testbench-дашборд, увидел все задачи в `claimed` без ADB-активности на phone #19. Расследовал, нашёл — после publisher.py split (PR #3, 2026-04-25) `publisher_base.py:2550` вызывает `ensure_adbkeyboard()` без import. NameError на каждой publish_task → залипание в claimed → 30+ часов crash-loop. Починил, отгрузил в testbench, докатил split в prod.

## Что отгружено

### Боевой код

| Репо / ветка | Коммит | Содержимое |
|---|---|---|
| `GenGo2/delivery-contenthunter#testbench` | `febb616` | T2: восстановлен `from adb_utils import ensure_adbkeyboard, adb_text as _adb_text_util` в `publisher_base.py`. T3: `run_publish_task` exception-handler теперь UPDATE `status='failed'`. T4: `scripts/reset-stuck-claimed-20260427.sql` (push 32 застрявших). |
| `GenGo2/delivery-contenthunter#fix/posts-parser-revival-20260427` (prod) | `fd564da` (merge) | `git merge origin/testbench` в prod-dir → split + febb616 fix приехали в prod. Auto-pushed hook'ом. |

### AI-factory artifacts

| Репо / ветка | Коммит | Содержимое |
|---|---|---|
| `rmbrmv/contenthunter#fix/testbench-publisher-base-imports-20260427` | `3e2fe0dec` | Plan + evidence: `.ai-factory/plans/testbench-publisher-base-imports-20260427.md` + `.ai-factory/evidence/testbench-publisher-base-imports-20260427.md`. PR-create отказан токеном permission'ами; URL для UI-create в evidence. |

## Метрики ДО/ПОСЛЕ

| Метрика | ДО (24ч) | ПОСЛЕ (~60s после deploy split в prod) |
|---|---|---|
| testbench publish_tasks status=claimed | 29 | 0-1 (transitional) |
| testbench publish_tasks status=done/failed/awaiting_url | 0 | 5+ awaiting_url, 1 failed (T3 hardening сработал) |
| `pm2 autowarm-testbench` unstable restarts | 25 за 10 мин uptime | 0 |
| `NameError: ensure_adbkeyboard` в логах | каждые ~10s | 0 |
| `pm2 autowarm` (prod) после deploy split | 187 restarts, monolith | 188 restarts, 0 unstable, 0 NameError/ImportError |
| `adb_push_chunked_md5_mismatch` (старый P1) | blocker | пройден baseline (12 chunks за 29.2s, чисто) |

## Memory updates

- `project_publisher_modularization_wip.md` — обновлено prod state на `fd564da` (split + posts_parser revival merged). Добавлена regression-tail про NameError + lesson про smoke-test.
- `project_publish_testbench.md` — добавлена recovery-нота 2026-04-27. Memory ADB-port для phone #19 (15068, не 15088) подтверждён.
- `reference_github_tokens.md` — добавлен permission-gap: rmbrmv fine-grained PAT не имеет `pull-requests:write`, PR-create программно невозможен.
- `project_contenthunter_server.md` — уточнена 3-dir / 2-репо topology. `rmbrmv/contenthunter` = AI workspace ONLY (0 production-кода). Решение пользователя — оставлено как есть.

## Lessons

1. **Split-refactor smoke-tests должны делать runtime-exec, не только `import`.** `import publisher_base` НЕ ловит missing imports на module-level вызовы внутри методов, не вызываемых импортом. Минимум — AST-обход всех `Name`-нод и проверка resolve в module namespace; ещё лучше — фейковый `run_publish_task(test_task_id)` с mock DB.
2. **PM2 restart counter — диагностический сигнал.** 25 рестартов за 10 мин uptime = crash loop. Включить в стандартный health-check после deploy.
3. **Worker exception-handler ОБЯЗАН маркировать task'у failed.** Иначе залипание в `claimed` → 30-min stuck-reset → infinite loop. Метрики 1h success-rate показывают 0% running вместо 100% failed → triage classifier не получает сигнала, autofix не работает.
4. **«User diagnosis = signal, не ground truth»** (memory `feedback_user_diagnosis_is_signal.md` подтверждено): пользователь сказал «задачи в claimed, ничего не происходит» — точно симптом, но root cause нужно перепроверить независимо. Здесь user'ская гипотеза «не доделали старые задачи?» оказалась неверной; правда — новая регрессия от split'а.

## Pending follow-ups

- **PR в `rmbrmv/contenthunter`** — pushed `fix/testbench-publisher-base-imports-20260427`, программно создать не удалось (permission gap). UI: https://github.com/rmbrmv/contenthunter/pull/new/fix/testbench-publisher-base-imports-20260427
- **Old uncommitted state на `feature/farming-testbench-phone171`** — `M PLAN.md` + ~10 untracked plans/evidence из других сессий. Не моё, не трогаю.
- **3 stale claimed (1082/1083/1084) на testbench** — попали в sequential queue, разойдутся за ~30 мин. Если за 1 час не ушли — manual nudge.
- **Prod autowarm на split — observer первые 24-48 часов** — особенно `selector_drift`, multi-device edge cases, concurrent task processing. Если новые `unknown` или регрессии — `git revert fd564da && sudo pm2 restart autowarm`.
