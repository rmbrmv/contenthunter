# Reanimation: analytics pipeline — `factory_parsing_logs` + 14-day depth guard

**Created:** 2026-04-27
**Branch (plan):** `feature/farming-testbench-phone171` (plan-only — fix лежит в autowarm)
**Target repo:** `/root/.openclaw/workspace-genri/autowarm/` (auto-push → `GenGo2/delivery-contenthunter`)
**Proposed autowarm branch:** `fix/posts-parser-revival-20260427`
**Reporter:** Danil → "запустили план починки analytics, Apify пополнили"
**Predecessor plan:** `.ai-factory/plans/analytics-empty-pipeline-diagnosis-20260427.md`
**Evidence (diagnosis):** `.ai-factory/evidence/analytics-empty-pipeline-diagnosis-20260427.md`

---

## Settings

| | |
|---|---|
| Testing | yes — smoke (R4: 1 acc per platform) + integration (R7: SQL-проверка эндпоинта) |
| Logging | verbose — DEBUG в posts_parser на каждый Apify-вызов / INSERT-результат / skip-older-than-depth |
| Docs | yes — обновить `autowarm/AGENTS.md` или `README.md` (R10): что делает posts_parser, его deps (`factory_parsing_logs`, Apify quota), 14-day depth policy, manual backfill команда |
| Roadmap | n/a — нет `.ai-factory/ROADMAP.md` |

---

## TL;DR — состояние ДО плана (закреплено evidence-файлом)

3 root causes делали `/client/analytics` пустой:

1. **`factory_parsing_logs` table missing** → `posts_parser.py:174` raises на каждом success-path, `conn.rollback()` откатывает посты/stats/fans/UPDATE → JS-обёртка маскирует логом `[posts-parser] OK: ... posts=undefined, fans=undefined`. → **Этот план**
2. **Apify monthly quota exhausted** (GenGo SCALE-SILVER, $199/mo) → IG/TT actors HTTP 403. → **✅ Решено пользователем (баланс пополнен 2026-04-27)** — verifying в R1.
3. **`account_audience_snapshots` навсегда 0 rows** (analytics_collector.py из cron не пишет). → **Отдельный план** (диагностика TBD).

После reanimation:
- `factory_parsing_logs` создан → `posts_parser.py` работает success-path без crash
- Backfill 41 дня закрывает gap → analytics за 30д/90д не пустой
- 14-day depth limit в posts_parser → ongoing daily runs не съедают Apify квоту циклически (защита от повторения апрельского инцидента)

---

## Tasks

### Phase 1 — Pre-flight (Apify alive)

- [x] **R1. Verify Apify quota restored** (см. TaskGet #10)
  - `curl "https://api.apify.com/v2/users/me?token=$APIFY_KEY"` → `proxy.groups != []`, нет `platform-feature-disabled`.
  - Dry-run `apify~instagram-scraper` для @rel_isme `resultsLimit=1` → HTTP 200 + ≥1 item.
  - Если 403 → STOP, эскалировать.
  - Logging: stdout полный JSON каждого запроса.

### Phase 2 — Schema fix (DDL)

- [x] **R2. DDL для `factory_parsing_logs` migration файл** (#11)
  - File: `migrations/20260427_factory_parsing_logs.sql` + rollback.
  - Поля совпадают с `posts_parser.py:174-178`: `id SERIAL PK, account_id TEXT, platform TEXT NOT NULL, status TEXT NOT NULL, error_category TEXT, error_message TEXT, raw_response JSONB, created_at TIMESTAMPTZ DEFAULT NOW()`.
  - Индексы: `(created_at DESC)` для recent-tail; `(account_id, status, created_at DESC)` для per-account error-tracking.
  - Blocked by: R1.

- [x] **R3. Apply migration на prod** (#12)
  - `psql -h localhost -U openclaw -d openclaw -f migrations/20260427_factory_parsing_logs.sql`
  - Verify: `SELECT to_regclass('factory_parsing_logs')` not null + 8 columns + 2 indexes.
  - **Critical**: НЕ продолжать дальше если migration не применилась — иначе R4 опять silent-crash.
  - Blocked by: R2.

### Phase 3 — Smoke (1 account per platform)

- [x] **R4. Smoke-run posts_parser для IG/TT/YT** (#13)
  - 3 manual инвокации (Relisme accounts).
  - Verify: `factory_parsing_logs` имеет успехи; `factory_inst_reels_stats.collected_at = CURRENT_DATE`; `factory_inst_reels.synced_at >= NOW() - 5min`.
  - JSON-ответ posts_parser должен быть `{"ok":true, "posts": N, "fans": M}` с числами — не `undefined`.
  - При `ok=false` → диагностируем error_message в factory_parsing_logs ДО R6.
  - Blocked by: R3.

### Phase 4 — Full backfill (закрываем 41-дневную дыру)

- [x] **R6. Backfill всех 1240 активных аккаунтов** (#15)
  - **С текущим resultsLimit=50** (R12 ещё НЕ применён) — нужно для full catch-up: 50 последних постов покрывает любой gap для активных аккаунтов.
  - `nohup python3 -c "from posts_parser import parse_all_active; parse_all_active()" > /tmp/backfill_20260427.log 2>&1 &`
  - Прогресс: `tail -f /tmp/backfill_20260427.log` + periodic SQL `SELECT COUNT(*) FROM factory_inst_reels_stats WHERE collected_at = CURRENT_DATE`.
  - Apify quota watch: если `factory_parsing_logs` начнёт давать массовые `apify_error: Monthly usage hard limit exceeded` — STOP, эскалировать (квота кончилась снова — может быть нужен upgrade тарифа).
  - Длительность: 1240 acc × ~5 sec (sleep+Apify) = ~100 минут на круг (может быть больше при медленном Apify).
  - Blocked by: R4.

### Phase 5 — Apify quota guard (post-backfill regular operation)

- [x] **R12. Patch posts_parser — depth limit 14 days** (#21)
  - **Только ПОСЛЕ R6** (иначе backfill не закроет дыру).
  - Env var `POSTS_PARSER_DEPTH_DAYS=14` (default 14, override в `.env`).
  - IG/TT: `resultsLimit/maxPostsPerProfile = max(POSTS_PARSER_DEPTH_DAYS, 5)`.
  - Post-fetch date filter (idempotency): `if fmt_date(post['timestamp']) < CURRENT_DATE - 14 days: skip upsert`.
  - YouTube: оставить `maxResults=50` (бесплатно через Google API), фильтр post-fetch по дате.
  - Smoke: 5 IG accounts → `factory_parsing_logs` показывает `status=success`, posts ≤ 14 per account, ноль ошибок.
  - Apify-credit-usage diff: snapshot `users/me` ДО/ПОСЛЕ — оценить экономию credits per run.
  - Logging: verbose DEBUG `[posts-parser:depth-skip] account=X timestamp=Y > now()-14d`.
  - Blocked by: R6.

### Phase 6 — Branch + commit (atomic: migration + code patch вместе)

- [x] **R5. autowarm fix-branch** (#14)
  - В `/root/.openclaw/workspace-genri/autowarm/`:
    ```
    git fetch origin && git checkout main && git pull
    git checkout -b fix/posts-parser-revival-20260427
    git add migrations/20260427_factory_parsing_logs.sql migrations/20260427_factory_parsing_logs__rollback.sql posts_parser.py
    git commit -m "fix(autowarm): create factory_parsing_logs + 14-day depth guard for posts_parser

    Two issues fixed in one commit (atomic):
    1. factory_parsing_logs table was missing → posts_parser silently
       crashed on every invocation (UndefinedTableError → conn.rollback()),
       producing empty /client/analytics since 2026-03-16.
    2. resultsLimit=50 + no date filter → daily cron repeatedly fetched
       50 historical posts per account, exhausting Apify monthly quota
       (incident 2026-03-?? → 2026-04-27 outage).

    POSTS_PARSER_DEPTH_DAYS env var (default 14) controls future depth.
    See: .ai-factory/evidence/analytics-pipeline-revival-20260427.md"
    git push -u origin fix/posts-parser-revival-20260427
    ```
  - PR description ссылается на evidence + diagnosis plan.
  - Auto-push hook (memory `reference_autowarm_git_hook.md`) синкнет в `GenGo2/delivery-contenthunter`.
  - Blocked by: R12.

### Phase 7 — Verify

- [x] **R7. SQL-проверка `/api/analytics/client/summary`** (#16)
  - Direct SQL для project_id=9, 16, 12, 8 + days=30 → views > 0, posts > 0 для всех 4.
  - Bonus: curl с auth-cookie (если пользователь даст — необязательно) → JSON 200 с непустыми массивами.
  - Если хотя бы один проект 0 после backfill → диагностируем по factory_parsing_logs (что вернул Apify).
  - Blocked by: R5.

- [x] **R8. UI smoke — пользователь подтверждает** (#17)
  - Открыть `https://client.contenthunter.ru/client/analytics` (admin или client login).
  - DevTools → Network → `/api/analytics/client/summary` 200 + non-zero.
  - Скриншот в evidence.
  - Blocked by: R7.

### Phase 7.5 — Schema homogeneity (user request 2026-04-27)

- [x] **R13. Move `factory_accounts_fans` to `public` schema** (#22)
  - User: "мне нужно чтобы все было однотипно и в одной схеме". Все остальные analytics-таблицы — в `public`. Эта была одна-единственная в `factory.`.
  - Migration: `migrations/20260427_factory_accounts_fans_to_public.sql` (BEGIN; SET SCHEMA для table+sequence; COMMIT;) — instant.
  - Patch posts_parser.py upsert_fans: убрать `factory.` qualifier → bare `factory_accounts_fans`.
  - Smoke 1 account.
  - **Только после R6** — backfill в памяти держит старый qualified-код, ALTER mid-run сломает в-полёте посты.
  - Blocked by: R6.

### Phase 8 — Merge

- [x] **R9. Merge fix-branch → main → autowarm restart (если нужно)** (#18)
  - PR review → merge `fix/posts-parser-revival-20260427` в main.
  - Auto-push в delivery-contenthunter (per memory).
  - Verify `pm2 describe autowarm | grep "exec cwd"` указывает на `/root/.openclaw/workspace-genri/autowarm` (memory `feedback_pm2_dump_path_drift.md`).
  - Если drift → `sudo pm2 delete autowarm && sudo pm2 start ecosystem.config.js --only autowarm`.
  - Blocked by: R8.

### Phase 9 — Documentation

- [x] **R10. Обновить `autowarm/AGENTS.md` (или README)** (#19)
  - Добавить раздел "posts_parser pipeline":
    - Что делает (1 строка)
    - Triggers (server.js:3719-3850 — 3 mechanisms)
    - Hard deps: `factory_parsing_logs` table, Apify quota (`proxy.groups != []`)
    - 14-day depth policy + env var `POSTS_PARSER_DEPTH_DAYS`
    - Manual backfill: `python3 -c "from posts_parser import parse_all_active; parse_all_active()"`
    - Health-check oneliner: `psql -c "SELECT MAX(collected_at) FROM factory_inst_reels_stats"` → должен быть `>= CURRENT_DATE - 1`
  - ~30-40 строк markdown.
  - Blocked by: R9.

### Phase 10 — Evidence + memory

- [x] **R11. Evidence file + memory update** (#20)
  - File: `.ai-factory/evidence/analytics-pipeline-revival-20260427.md`.
  - Sections:
    1. Before/after metrics (`MAX(collected_at)`, daily insert counts, `users/me` credit-usage)
    2. factory_parsing_logs sample (10 success rows + любые errors)
    3. /api/analytics/client/summary diff for project_id=9 (Relisme): zeros → non-zeros
    4. UI screenshot из R8
    5. Lessons learned:
       - **server.js масquerades ok=false как OK** — JS-обёртка не проверяет `r.ok` перед логом → backlog item
       - **DDL-таблицы должны быть в migrations/, не неявные** — следующий новый writer всегда добавляет migration файл
       - **Apify quota guard** — обязательный паттерн, не опциональный
  - Memory:
    - Update `project_analytics_pipeline_dead.md` → `(✅ resolved 2026-04-27)` + ссылка на evidence
    - Опционально: `feedback_silent_crash_pattern.md` — если паттерн "JS-обёртка маскирует Python ok=false как OK" повторяется в кодбейзе (TBD при review)
  - Blocked by: R10.

---

## Commit Plan

- **Commit 1** (после R12, в autowarm `fix/posts-parser-revival-20260427`):
  ```
  fix(autowarm): create factory_parsing_logs + 14-day depth guard for posts_parser
  ```
  Atomic: миграция + код-патч в одном коммите. Half-broken state нельзя оставлять (memory `feedback_parallel_claude_sessions.md`).

- **Commit 2** (после R10, в autowarm same branch):
  ```
  docs(autowarm): document posts_parser pipeline + dependencies
  ```
  Отдельным коммитом потому что docs живут дольше — git blame будет чище.

- **Commit 3** (после R11, в agent-workspace `feature/farming-testbench-phone171`):
  ```
  docs(plan+evidence): analytics pipeline revival — factory_parsing_logs + 14d depth
  ```
  План + evidence-файл + memory-апдейт.

---

## Risks & notes

- **R3 → R4 порядок критичен**: миграция должна примениться на prod ДО smoke. Иначе smoke даст тот же silent-crash что был в production.
- **R6 → R12 порядок критичен**: backfill ДО depth-limit. Если задеплоить depth=14 раньше, backfill упрётся в 14-дневный фильтр и не закроет 41-дневную дыру.
- **R5 атомарность**: миграция + код-патч в одном коммите. Если split — между двумя коммитами prod уже бы прыгал на новый код без миграции (uncommitted SQL уже применили в R3, но в репе её нет — это короткий "drift" до R5).
- **Apify квота watch**: backfill 1240 IG+TT через Apify съест значительные credits. R6 description явно требует мониторинга `factory_parsing_logs.error_category='apify_error'` — если массово => STOP.
- **Auto-push hook** (memory `reference_autowarm_git_hook.md`): commit в autowarm main → auto-deploy в `GenGo2/delivery-contenthunter`. R5 push'ит fix-branch (не main), R9 merge'ит в main → авто-деплой только после R8 verify.
- **PM2 path drift** (memory `feedback_pm2_dump_path_drift.md`): R9 явно проверяет `exec cwd` после restart. Если автоwarm читает stale dev-копию из `/home/claude-user/autowarm-testbench/` — `posts_parser.py` patch не сработает в prod.
- **Silent-crash JS-обёртка остаётся** (server.js:3737): `console.log('OK: ...')` без проверки `r.ok` — это **известный лог-bug**, который в этом плане НЕ чинится (focus — pipeline). Backlog item для отдельного MR.
- **`account_audience_snapshots`** (root cause №3 из диагностики) — НЕ в этом плане. Отдельная задача (`/aif-plan` после R11).
- **8/38 проектов с 0 historical_reels** (Септизим, Wanttopay etc.) — после backfill они БУДУТ показывать данные (новые посты, спарсенные сегодня). Если по-прежнему пустые → отдельная диагностика (возможно, у них аккаунты заблокированы / private).
- **Memory `project_id_parser_ig_broken.md`**: новые аккаунты после 2026-04-23 имеют `instagram_id=NULL`. `posts_parser.parse_all_active` фильтрует `WHERE instagram_id IS NOT NULL AND != ''` → они автоматически пропускаются. Нужно отдельно лечить id_parser, не блокирует этот план.

---

## Links

- Diagnostic plan + evidence: `.ai-factory/plans/analytics-empty-pipeline-diagnosis-20260427.md`, `.ai-factory/evidence/analytics-empty-pipeline-diagnosis-20260427.md`
- Round 2 (account_packages cleanup, 2026-04-24, для контекста): `.ai-factory/plans/validator-schemes-account-packages-20260424.md`
- Code:
  - `autowarm/posts_parser.py` (576 lines, single commit `61b9e46`)
  - `autowarm/server.js:3719-3850` (posts_parser scheduler)
  - `autowarm/scheduler.js:19,468-509` (analytics_collector cron)
  - `autowarm/migrations/` (validate naming convention from existing files like `20260423_factory_accounts_id_sequence.sql`)
- Relevant memory:
  - `project_analytics_pipeline_dead.md` (создан в diagnostic-сессии 2026-04-27)
  - `reference_autowarm_git_hook.md` — auto-push в delivery-contenthunter
  - `feedback_pm2_dump_path_drift.md` — verify exec cwd после restart
  - `feedback_deploy_scope_constraints.md` — PM2 vs systemd
  - `project_factory_tables_sequence.md` — naming convention для migrations
  - `feedback_parallel_claude_sessions.md` — atomic commits, no half-broken state
