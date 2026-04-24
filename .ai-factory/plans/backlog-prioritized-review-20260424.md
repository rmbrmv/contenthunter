# PLAN — Бэклог: что осталось + приоритезация (2026-04-24)

**Тип:** umbrella / backlog review (не код)
**Создан:** 2026-04-24
**Режим:** full (one plan; каждый приоритет — либо готов к `/aif-plan full` спавну, либо закрыт как "нет действий")
**Репо:** `contenthunter` (main context), real fixes уйдут в `autowarm-testbench` и `/root/.openclaw/workspace-genri/autowarm/`.
**Branch:** живёт на `feature/farming-testbench-phone171` (текущая рабочая); сам файл — план-документ, кода не трогает.

## Settings

- **Testing:** n/a (план-обзор, кода нет; по каждой задаче плана-потомка — свои настройки)
- **Logging:** n/a
- **Docs:** warn-only
- **Roadmap linkage:** none

## Методика

1. Прошёлся по 21 плану в `.ai-factory/plans/` + свежие evidence 2026-04-23/24.
2. Скрестил со статусом в git log (последние 40 коммитов) и memory (`project_*`, `feedback_*`).
3. Проверил live-состояние: `farming_investigations` (5 open), `factory_inst_accounts` (IG parser coverage 284/288), `system_flags` (testbench paused=false, cadence=240).

## Сводная таблица: статус планов

| Plan | Tasks | Shipped? | Комментарий |
|---|---|---|---|
| farming-testbench-phone171-20260423 | 24 | ✅ | Все T1-T24 отгружены, live работает, cadence=240. Follow-ups — ниже P2/P5/P8. |
| revision-timeout-fix-20260423 | 10 | ✅ | 180→600s + partial_result deployed (22262db testbench, prod synced). |
| publishing-tasks-no-limit-20260424 | 3 | ✅ | `LIMIT 100` убран, pm2 restart ok. Follow-ups — P7/P9. |
| fix-packages-add-account-id-20260423 | 11 | ✅ | Sequence-миграция, live-verify на YT phone #19b. Markers `[x]` в плане не проставлены, но git + evidence подтверждают. |
| farming-testbench triage hardening (follow-up 2026-04-24) | 3 блока | ✅ | launch_failed + mismatch dedup + is_auto_fixable flip. Породил **5 open investigations** — входы для P2/P5. |
| revision PLAN.md (platform-column + garbage) | 8 | ✅ | T1-T8 все ✅. Включил uncommitted diff (uncommitted PLAN.md в git status — сам файл перестал быть актуальным после этого плана; новые планы идут в `/plans/`). |
| deprecate-account-packages-20260422 | — | ✅ | DROP TABLE 2026-04-22, память `project_account_packages_deprecation.md`. |
| publish-launch-failures-fix-20260422 | 9 | ✅ | commit 9d415f494. |
| testbench-new-accounts-phone19-20260422 | — | ✅ | commit 48e6a6ef0. |
| testbench-iter-4-publish-polish-20260422 | 11 | ✅ | commit bc80e332c. |
| refactor-revision-use-switcher-engine-20260422 | 8 | ✅ | T1-T8. |
| revision-account-packages-sync-20260422 | — | ✅ | commit ba914011c. |
| publish-testbench-agent-20260421 | 19 | ✅ | 18/19 (memory `project_publish_testbench.md`). |
| single-account-switcher-shortcircuit-20260421 | 8 | ✅ | commit 443acd585. |
| kira-widget-recovery-20260421 | 18 | ✅ | commit b00a55188. |
| adb-chunked-race-fix-20260421 | 7 | ✅ | commit a06748b3c (7/7). |
| feat-screen-recovery-llm-ig-mvp-20260420 | 9 | ✅ | commit 9d5bec3fa. |
| fix-guard-status-backfill-tests-20260420 | — | ✅ | shipped. |
| open-followups-20260420 | 7 | ⚠️ 6/7 | T7 `feature/aif-global-reinstall` merge — локальный FF ок, push на origin blocked (unrelated histories) — см. P10. |
| llm-screen-recovery-brief-20260420 | — | ✅ (brief) | Материализовано в feat-screen-recovery-llm-ig-mvp. |
| farming-reuse-research.md | — | research | Результат — матрица кандидатов. Закрыт, новых действий нет. |

**Итого:** из 21 плана ≥20 полностью отгружены. Open-followups T7 — единственный «висяк», и даже тот частично (локально влит).

## Живой source-of-truth: 5 open farming investigations (актуально сейчас)

```
          error_code           | status | occurrences | tasks
-------------------------------+--------+-------------+-------
 yt_account_read_fail          | open   |          50 |    18   ← phone #171 YT-bug
 tt_account_read_fail          | open   |          47 |    17   ← phone #171 TT-bug
 farming_app_launch_failed     | open   |          23 |    12   ← smoke artefact
 account_mismatch_after_switch | open   |           6 |     6   ← IG switch_instagram_account() bug (clean case B)
 ig_account_read_fail          | open   |           3 |     1   ← outlier
```

Эти 5 — **главные candidate'ы для следующих fix-планов**.

---

## Остались задачи (backlog по приоритетам)

### P1 🔴 — IG `switch_instagram_account()` switch-failure (6 clean fixture tasks)

**Status:** investigation готова, auto-diagnose может предложить fix, но apply в review-only MVP — оператор ничего не видел/включил.

**Почему P1:**
- Чистый case B: read работает, но переключение аккаунта в IG падает.
- 6 fixture task'ов накоплены на phone #171 (ivana.world.class × 4 + born.trip90 × 2) — конкретные воспроизводимые кейсы.
- Баг blocks IG-фарминг на phone #171 (а значит и продакшн-фарминг на аналогичных устройствах, если UI-паттерн совпадает).
- Триаж + diagnose уже сделал половину работы: всё evidence собрано, нужен только investigator + fix.

**Next action:**
```
/aif-plan full "Investigate IG switch_instagram_account() failure на phone #171 — 6 case B fixtures, погрузиться в retry-loop + UI navigation в account_switcher.py"
```

**Evidence:** `.ai-factory/evidence/farming-testbench-triage-hardening-20260424.md` §2

**Оценка:** 2-4 часа (UI XML-дампы уже есть в `/tmp/autowarm_ui_dumps/`, осталось прочитать retry-loop и воспроизвести).

---

### P2 🔴 — Phone #171 TT залип в чужом `@rahat.mobile.agncy.31`

**Status:** memory `project_revision_phone171_backlog.md` (с 2026-04-22). Фиксировано: ручная чистка или Activity-intent. Triage классифицирует это как `tt_account_read_fail` (47 occurrences / 17 tasks — уже самая крупная investigation).

**Почему P1/P2:**
- Блокирует TT-фарминг на phone #171 полностью.
- Рубит половину TT-coverage в тестбенче (второй аккаунт born7499 может быть в порядке, но foreign-profile stuck блокирует read).
- Тесно связан с P5 (YT bottom-nav) — обе беды phone #171.

**Next action (выбрать один путь):**

1. **Быстрый ручной fix (20 мин):** user руками на устройстве выйти из чужого аккаунта через TT Settings → Accounts → Log out всех → re-login только нужных.
2. **Программный workaround (4-6ч):** новый план → `am start` Activity-intent бьёт напрямую в TT Account Management Activity (аналогично YT Settings-activity workaround из memory `reference_yt_accounts_settings_path.md`).

**Рекомендация:** начать с (1) — быстрая проверка гипотезы; если через неделю опять залипнет — делать (2).

**Next action command:**
```
# сначала (1) manual cleanup на phone #171 TT
# если не сработало → /aif-plan full "TT foreign-profile stuck Activity-intent workaround"
```

---

### P3 🔴 — `id_parser.py` IG broken (Apify 403 + IG mobile 429)

**Status:** memory `project_id_parser_ig_broken.md` (с 2026-04-23). YT/TT работают, IG — нет. instagram_id остаётся NULL для новых аккаунтов.

**Live check:** `factory_inst_accounts WHERE platform='instagram'` → 4 NULL / 284 ok / 288 total. **Только 4 NULL** — значит парсер либо работает частично, либо нет поступления новых IG-аккаунтов за эту неделю. Всё равно баг присутствует, просто не "горит".

**Почему P3 (не P1):**
- Не блокирует текущую работу (284/288 покрыты), но блокирует onboarding новых IG-аккаунтов.
- publish guard без instagram_id не всегда проваливается — зависит от `account_packages` drop + factory-mapping, который сейчас резолвится по username.
- Фикс требует работы с rate-limits и провайдерами — не одна итерация.

**Next action:**
```
/aif-plan full "Восстановить id_parser.py для Instagram — Apify rotate-proxy / альтернативный endpoint / fallback-стратегия при 429"
```

**Оценка:** 3-6ч (разведка провайдеров + rate-limit config + тесты).

---

### P4 🟡 — Farming triage classifier: автоматизировать (cron/timer)

**Status:** memory `project_farming_testbench.md` — "Triage classifier запускается вручную (timer не ставил)".

Plan `farming-testbench-phone171-20260423.md` T16 отмечен ✅ (systemd autowarm-farming-triage-dispatcher.service + .timer), но на prod `feedback_deploy_scope_constraints.md` говорит: claude-user не может `sudo cp .service`. Судя по PM2-orchestrator подходу — тогда timer реализован был через PM2 cron-restart или пропущен вовсе.

**Проверить на месте:**
```bash
sudo pm2 list | grep triage
sudo systemctl list-timers | grep farming-triage
```

**Next action:**
- Если не поставлен: короткий план → PM2 cron-restart schedule или отдельный node-script с setInterval (30 мин tick).
- Короткая задача (1-2ч), но не блокирующая — пользователь сейчас сам гоняет `python3 farming_triage_classifier.py --scan-recent`.

```
/aif-plan fast "farming_triage_classifier автопрогон каждые 30 мин через PM2 cron-restart"
```

---

### P5 🟡 — Phone #171 YT bottom-nav (972,2320) не открывает профиль

**Status:** memory `project_revision_phone171_backlog.md` + `reference_yt_accounts_settings_path.md`. Workaround есть: `am start com.google.android.youtube/.app.application.Shell_SettingsActivity` → «Аккаунт» → «Смена или настройка аккаунта». Показывает emails + «Нет канала» если channel не создан.

**Почему не P1:** workaround известен, можно подключить как первичный path для phone #171 (и опционально всегда — Settings-activity устойчивее bottom-nav).

**Next action:**
```
/aif-plan full "YT account detection через Settings-activity как primary path (fallback на bottom-nav) в account_switcher.read_active_yt_account"
```

**Оценка:** 3-4ч (Activity-intent команда уже в memory, осталось wire-up и тесты).

---

### P6 🟡 — Revision `partial_result` на `code != 0` крахи (follow-up из revision-timeout-fix)

**Status:** в plan `revision-timeout-fix-20260423.md` явно отмечен как "not in scope, follow-up". Сейчас partial_result эмитится только при killTimer (timeout). Если Python-скрипт упал exit-кодом 1-255 — фронт получает старый `event: error` + теряет platformResults, даже если IG/TT успели.

**Почему P6:** UX-улучшение, не критикал. Частота краша-до-результата в проде не измерена.

**Next action (после метрик):**
```sql
-- собрать частоту крашей за неделю
SELECT COUNT(*) FROM ... WHERE event_type='error' AND timer_fired=false; -- или из pm2 logs
```
Если ≥5/неделю → делать. Иначе отложить.

```
# когда будет метрика
/aif-plan fast "revision partial_result также на child exit!=0 (не только timeout)"
```

**Оценка:** 1-2ч (мелкий патч server.js).

---

### P7 🟢 — server.js: унифицировать остальные хардкод `LIMIT` (archive_tasks/ad_hoc_runs/phone_warm_tasks)

**Status:** publishing-tasks-no-limit-20260424 явно вывел в "Out of scope" — user сказал только central Upload Tasks. Но 4 соседних эндпоинта имеют те же хардкоды:
- `archive_tasks LIMIT 200` (line 698)
- `ad_hoc_runs LIMIT 100` (line 790)
- `phone_warm_tasks LIMIT 200` (line 1197)
- `LIMIT 500` (line 1462)

**Почему P7:** user не запрашивал. Превентивно — только если user сам пожалуется. Иначе YAGNI.

**Next action:**
- Не делать, пока user не попросит.

---

### P8 🟢 — Farming `apply` upgrade: review-only → opt-in auto-apply с git commit + rollback

**Status:** triage-hardening evidence §Follow-ups #3: "After накопления confident proposals (≥7/10) имеет смысл добавить opt-in auto-apply с git commit + rollback".

**Почему P8:** сейчас diagnose пишет `## Proposed Fix` в `farming_fixes` с `enabled=FALSE`. Это safe review-mode. Перевод в auto-apply — риск регрессий. Нужно сначала **набрать метрику** — сколько diagnose proposals были бы валидны, если бы автоматически применились.

**Next action (когда накопится 20+ proposals):**
```
-- собрать статистику
SELECT COUNT(*), AVG(confidence_score) FROM farming_fixes WHERE created_at > NOW() - INTERVAL '2 weeks';
```
Если средний confidence ≥0.7 и <10% false-positive — делать план.

**Оценка:** 6-8ч (git hooks + rollback infra + UI).

---

### P9 🟢 — Performance/index audit на `publish_tasks` (follow-up publishing-tasks-no-limit)

**Status:** при 906 строк всё нормально. При росте > 10K — нужны:
- `CREATE INDEX ON publish_queue (publish_task_id)` (если нет)
- `CREATE INDEX ON factory_device_numbers (device_id)` (если нет)
- Server-side cap `LIMIT 5000` или infinite-scroll

**Next action:** проверить `\di publish_tasks; \di publish_queue;` — возможно всё уже есть. Иначе не делать, пока объём не вырастет.

---

### P10 🟢 — Merge `feature/aif-global-reinstall` в main (open-followups T7)

**Status:** 2026-04-20, локальный FF-merge ок, но push на origin заблокирован "unrelated histories". Это был реинсталл 23 aif-skills + MCP handoff.

**Проверить:**
```bash
git branch -a | grep aif-global-reinstall   # ветка ещё существует?
git log --oneline main..origin/main | head  # origin main ушёл вперёд?
```

Возможно, за 4 дня вопрос снялся сам собой — новый aif уже установлен через другой путь (memory `project_ai_factory.md` подтверждает v2.9.3 global).

**Next action:** либо удалить ветку (если контент уже на main через другие коммиты), либо force-resolve через `rebase --onto` если содержимое ещё нужно.

**Оценка:** 30 мин (проверка) + 0 или 1-2ч (resolve).

---

## Рекомендация по порядку

**На ближайшую сессию (1-2 рабочих дня):**

1. **P2** manual TT cleanup на phone #171 (20 мин, user действие) — unblocks TT farming
2. **P4** farming triage timer — 1-2ч, low-risk ops win
3. **P1** IG switch_instagram_account() — 2-4ч, самый ценный debug с готовыми fixtures

**Следующая неделя:**

4. **P5** YT Settings-activity path — 3-4ч, гасит tt/yt read_fail investigations
5. **P3** id_parser IG — 3-6ч, техдолг, но не горит

**Отложить до триггера:**

6. **P6/P8/P9** — ждать метрики / явного запроса пользователя.
7. **P7** — только если user сам попросит.
8. **P10** — 30-мин проверка, возможно уже снят.

## Что НЕ вошло

- Новые фичи (VK/FB/X, за scope per memory `project_autowarm_scope`).
- PLAN.md uncommitted diff в root — это старый revision-platform-column plan, полностью заменён новыми plans/*.md; файл можно удалить или оставить как placeholder. Отдельной задачи не создаю.
- Bugs bot intake / knowledge repo — отдельный живой contour (`project_bugs_bot.md`, `feedback_knowledge_stack.md`), не в scope этого обзора.

## Риски

- **R1:** P1/P2/P5 все завязаны на phone #171 (один физический девайс). Одновременно не распараллелить — только sequential ADB session.
- **R2:** Farming testbench всё ещё running (`farming_testbench_paused=false`, cadence=240). Будет продолжать генерить новые investigations. Perk: evidence растёт сам по себе. Риск: если apply кода затрагивает warmer/switcher — проводить fixes в нерабочее время.
- **R3:** P3 (id_parser) может внезапно стать блокером, если пользователь начнёт массовый onboarding новых IG-аккаунтов. Сейчас буфер 284/4, но трендить стоит.

## Next step

Этот план — **план-обзор**. По каждому P1-P10 выше спроэктирована команда для `/aif-plan full` (или ручного действия).

User выбирает, что делаем первым. Моё предложение — начать с P2 (manual TT cleanup, 20 мин) для разблокировки testbench coverage, затем P1 (IG switch bug, самый ценный debug).
