# План: Закрытие открытых follow-up'ов (состояние на 2026-04-20)

**Создан:** 2026-04-20
**Режим:** Full (umbrella over heterogeneous scope)
**Ветка:** без новой ветки — план живёт в contenthunter; реальные правки в autowarm-репо (`/root/.openclaw/workspace-genri/autowarm/`) через точечные plans-потомки
**Slug:** `open-followups-20260420`
**Источники (аудит 2026-04-20):** `.ai-factory/PLAN.md` (IG T7), `.ai-factory/plans/*.md`, autowarm `.ai-factory/plans/*.md`, память `project_publish_followups.md` + `project_adb_push_network_issue.md`, `.ai-factory/evidence/farming-reuse-matrix-20260419.md`.

## Settings

| | |
|---|---|
| Testing | **yes** для кодовых задач (guard tests, LLM-recovery); **no** для verification-закрытия (evidence only) |
| Logging | **verbose** для кодовых задач; **standard** для verification (SQL/observability) |
| Docs | **warn-only** — многодоменный план; полноценный docs-чекпоинт сделать в плане-потомке LLM-recovery (там новая фича) |
| Roadmap linkage | skipped — `paths.roadmap` отсутствует |

## Scope и границы

**ВХОДИТ:**
- Закрытие verification-окон (IG/TT/ADB) — evidence + отметки
- Триаж `publish_failed_generic` catch-all → отдельный plan-потомок
- LLM-screen-recovery (farming Candidate D) → отдельный plan-потомок
- Guard unit tests (publisher.py:5286-5373)
- Merge housekeeping `feature/aif-global-reinstall`

**НЕ ВХОДИТ:**
- Top-3 farming candidates A и B — уже реализованы (autowarm `fix-warmer-force-reset-app.md`, `feat-publisher-watchdog.md` — все задачи ✅)
- Новые продуктовые фичи фарминга/публишинга
- VK/FB/X (out of scope per memory `project_autowarm_scope`)

## Граф зависимостей

```
T1 (IG T7) ─┐
T2 (TT 48h)├──► T4 (pf_generic триаж) ─┐
T3 (ADB T15)┘                          ├──► (future plans)
                                       │
T5 (Candidate D plan-потомок) ─────────┤
T6 (Guard tests) ──────────────────────┤
T7 (aif-reinstall merge) ──────────────┘  (ортогонально)
```
T4 блокируется T1-T3 только мягко: желательно видеть свежие 48h-метрики до того, как разбирать catch-all.

---

## Tasks

### Phase 1 — Verification closure (T1-T3)

Задачи без нового кода. Цель — собрать evidence и отметить чекбоксы в уже закрытых планах.

#### T1. IG camera T7 — 24h post-deploy verification ✅ (2026-04-20)

**Файл-чекбокс:** `/home/claude-user/contenthunter/.ai-factory/PLAN.md:72` (`- [ ] T7 — Post-deploy 24h verification`).

**Что сделать:**
1. Выполнить SQL (publisher.py event aggregation) на фактических данных 2026-04-18…2026-04-20:
   ```sql
   SELECT meta->>'category' AS cat,
          meta->>'detected_state' AS state,
          COUNT(*)
     FROM task_events
    WHERE created_at > NOW() - INTERVAL '48 hours'
      AND (meta->>'category' LIKE 'ig_camera_%'
        OR meta->>'category' LIKE 'ig_highlights_%'
        OR meta->>'category' LIKE 'ig_gallery_picker_%')
    GROUP BY cat, state
    ORDER BY COUNT(*) DESC;
   ```
   DB: `PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw`.
2. Success criteria (из PLAN.md §T7):
   - `ig_camera_open_failed` на aneco/anecole кластере: **< 1/24h**
   - `ig_highlights_empty_state_seen` с последующим успехом ≥ 3 events
   - Нет бесконечного `ig_camera_open_reset_attempted` loop'а
3. Отдельно зачекать residual task 444 (`pay.anywhere.now`, RFGYB07Y5TJ) — вошёл ли он в fix из autowarm `ig-publishing-resolution.md` T1 (streak-counter + cold-start escalation).

**Evidence:** `.ai-factory/evidence/ig-camera-fix-24h-20260420.md` (дата смещена, т.к. делаем 2026-04-20).

**После evidence:** в `contenthunter/.ai-factory/PLAN.md` поменять `- [ ] T7` → `- [x] T7` со ссылкой на evidence-файл.

**Логи:** standard — просто фиксируем SQL + счётчики в evidence.

---

#### T2. TT publishing — 48h acceptance criteria ✅ (2026-04-20, PARTIAL PASS)

**Файл-чекбоксы:** `autowarm/.ai-factory/plans/tt-publishing-resolution.md:428-434` (7 пунктов).

**Что сделать:**
1. Запустить `scripts/tt_publishing_48h.sql` (существует в autowarm) — снять distribution по новым категориям.
2. Проверить каждый пункт:
   - `publish_failed_generic` для TT: доля < 5%
   - ≥1 end-to-end `status=done` TT-задача с 2026-04-19 ~20:00 UTC
   - audit-отчёт `/tmp/tt_audit/` — прикрепить листинг и сводку
   - `pytest tests/test_account_switcher_tt.py tests/test_publisher_category_resolve.py -v` — зелёный
   - `pytest tests/test_switcher_youtube.py` — не сломан (regression guard для T_FG)
   - `pm2 logs autowarm --lines 200` — без исключений от новых детекторов (grep по Traceback / ошибке импорта)
3. Для каждой провалившейся acceptance — зафиксировать root-cause в evidence и решить: fix-сейчас vs follow-up-plan.

**Evidence:** `.ai-factory/evidence/tt-publishing-48h-20260420.md` (в contenthunter).

**Отметить чекбоксы:** в `autowarm/.ai-factory/plans/tt-publishing-resolution.md:428-434`.

**Логи:** standard.

---

#### T3. ADB chunked-push T15 — post-deploy smoke ⚠️→✅ (2026-04-20: FAIL найден, fix задеплоен commit `73938df` autowarm/main)

**Файл-чекбокс:** `autowarm/.ai-factory/plans/infra-adb-chunked-push.md:170` (T15 ⏳).

**Что сделать:**
1. Запустить `scripts/adb_push_chunked_48h.sql` — посмотреть:
   - Сколько push'ей попали в chunked-path vs direct
   - Распределение `adb_push_chunked_start/chunk_ok/md5_ok/done/failed`
   - Есть ли `adb_push_timeout` на медиа >5MB (должно снизиться)
2. Проверить pm2 logs на пример хотя бы одного chunked push (ищем `[adb-chunked]`-логи или `log.info('chunk i/N: OK')`).
3. Cross-check mtr: `mtr -c 10 82.115.54.26` — packet-loss на hop 4 сохраняется? (параллельный трек у пользователя с TimeWeb — упомянуть в evidence).
4. Unit regression: `pytest tests/test_adb_push_chunked.py -v` + `pytest tests/` overall (из плана: 101 passed, 3 skipped).

**Evidence:** `.ai-factory/evidence/adb-chunked-smoke-20260420.md`.

**Отметить чекбокс:** `infra-adb-chunked-push.md:170` → `T15. Post-deploy smoke ✅`.

**Логи:** standard.

---

### Phase 2 — Triage: publish_failed_generic catch-all (T4)

#### T4. Триаж `publish_failed_generic` (15 events/48h) → spawn plan-потомок ✅ (2026-04-20; catch-all closed, найден real follow-up: guard-status generalize)

**Источник:** память `project_publish_followups.md` §2.

**Что сделать:**
1. Собрать актуальную выборку (окно 7 дней, т.к. 48h — мало):
   ```sql
   SELECT id, platform, device_serial, account,
          events, log, started_at, updated_at
     FROM publish_tasks
    WHERE status='failed'
      AND events::text LIKE '%publish_failed_generic%'
      AND COALESCE(started_at,updated_at) > NOW() - INTERVAL '7 days'
    ORDER BY updated_at DESC LIMIT 30;
   ```
2. Для каждого case классифицировать по underlying cause (читая `log` tail + события до ошибки):
   - account-switch fail (уже есть specific categories — почему не propagated?)
   - ADB transport / `adb_push_timeout` (должно было быть поглощено T3)
   - UI-driver unknown screen (кандидат для LLM-recovery из T5)
   - infra (pm2 restart / OOM)
   - **true** catch-all без специфики
3. Результат классификации → таблица в evidence + решение для каждого bucket: existing plan покрывает / нужен новый plan / уже закрыто.
4. Если `unknown screen` bucket — большой (>30%), это усиливает приоритет T5.

**Evidence:** `.ai-factory/evidence/publish-failed-generic-triage-20260420.md`.

**Deliverable:** команда для plan-потомка вида
```
/aif-plan full "Разложить publish_failed_generic catch-all по конкретным category (propagation fix)"
```
с приложенной классификацией. **Эту команду НЕ запускать в рамках T4** — только сформировать.

**Логи:** standard; при выявлении пропущенного event-category записать `TODO(category)` комментарий в evidence.

---

### Phase 3 — Farming Candidate D: LLM screen-recovery (T5)

#### T5. Создать отдельный plan-потомок `/aif-plan full` под LLM-classifier screen-state ✅ (2026-04-20; brief готов)

**Источник:** `.ai-factory/evidence/farming-reuse-matrix-20260419.md` §Top-3 Candidate D + структурный аудит `.ai-factory/evidence/farming-t7-auto-public-audit-20260419.md` (llm_manager + anthropic/open_router providers).

**Scope T5 — ТОЛЬКО планирование**, не кодинг. Цель: sizing и entry point.

**Что сделать:**
1. Прочитать `/tmp/auto_public/services/llm_manager.py` + `/tmp/auto_public/llm_providers/anthropic.py`/`open_router.py` (при отсутствии клона — запросить `git -C /tmp/auto_public pull` или повторный clone).
2. Определить точку интеграции в нашем коде:
   - `publisher.py` camera-wait loop (:2020-2050) — `unknown-state recovery` после T3 (автоwarm plan) уже делает `_save_debug_artifacts('instagram_pre_reset')`. Можно вклинить LLM-классификатор ПЕРЕД force-reset, чтобы сэкономить reset на предсказуемых экранах.
   - Или `warmer.py::verify_and_switch_account` — перед 3-м retry.
3. Определить contract LLM-сервиса:
   - Input: last UI dump (xml) + last screen-record thumbnail (если есть) + текущий `step` + platform
   - Output: `{'screen_category': str, 'suggested_action': str, 'confidence': float}`
   - Обязателен **fallback** если LLM недоступен / confidence < 0.7 → текущий flow (не регрессировать).
4. Оценить cost: tokens/call × ожидаемая частота (prod-срез `unknown_state` events за 7 дней).
5. Записать команду plan-потомка с sizing:
   ```
   /aif-plan full "LLM-классификатор screen-state для publisher unknown-screen recovery (port services/llm_manager из auto_public)"
   ```

**Deliverable:** `.ai-factory/plans/llm-screen-recovery-brief-20260420.md` (brief, не полный plan) — служит основой для следующего `/aif-plan full` под этот слой.

**Логи:** для будущей имплементации planируется verbose (в plan-потомке), здесь не применимо.

---

### Phase 4 — Guard unit tests (T6)

#### T6. Unit tests для `_check_account_device_mapping`

**Источник:** память `project_publish_followups.md` §3, landmark `publisher.py:5286-5373`.

**Что сделать:**
1. Прочитать `publisher.py:5286-5373` (`_check_account_device_mapping`) + schema `account_packages` (память `project_publish_guard_schema`).
2. Новый файл `autowarm/tests/test_publisher_account_device_guard.py`:
   - `test_guard_passes_for_matching_device_account_platform` — happy path
   - `test_guard_blocks_mismatched_account` — account не совпадает с `account_packages.account`
   - `test_guard_blocks_null_account_triple` — NULL-column (seed-round-6 scenario)
   - `test_guard_allows_auto_from_publish_row` — авто-маппинг с project `auto-from-publish`
   - `test_guard_logs_block_event_with_category` — mock `self.log_event`, assert category `account_device_mapping_block` (или текущая live-категория — прочитать из кода)
3. Fixtures: `tests/fixtures/account_packages_guard.json` — несколько packages row-ов для разных кейсов; mock БД через `unittest.mock.patch` на DAO-функцию.
4. `pytest autowarm/tests/test_publisher_account_device_guard.py -v` — все passed.

**Файлы:**
- `autowarm/tests/test_publisher_account_device_guard.py` (новый)
- `autowarm/tests/fixtures/account_packages_guard.json` (новый)
- **Не трогать** `publisher.py` — только тесты. Если в ходе T6 обнаружится баг в guard, завести отдельный fix-plan.

**Логи:** verbose в тестах (`caplog` capture + assert сообщений).

---

### Phase 5 — Housekeeping (T7)

#### T7. Merge `feature/aif-global-reinstall` в main

**Источник:** текущая ветка `feature/aif-global-reinstall`; `contenthunter/.ai-factory/plans/aif-global-reinstall.md` — все T1-T7 ✅.

**Что сделать:**
1. `git status` — убедиться что нет uncommitted изменений (кроме запланированного удаления `.claude/scheduled_tasks.lock` — его зачем-то сносил sync).
2. `git log --oneline main..feature/aif-global-reinstall` — собрать cherry-pick list.
3. Решить: fast-forward merge или squash. Для chore/инфраструктуры — **squash** в один commit `chore: global AIF reinstall (23 skills + MCP handoff)`.
4. `git checkout main && git merge --squash feature/aif-global-reinstall && git commit -m "..."` (или через PR если есть GitHub remote).
5. После merge — `git branch -d feature/aif-global-reinstall` (локально) + push main.

**Осторожно:**
- Пользователь запретил force-push на main.
- Перед `git branch -d` убедиться что локальный main обновился с remote.
- **Подтвердить у пользователя** перед push — merge в main затрагивает shared state.

**Логи:** standard — `git log`/`git status` вывод в evidence не нужен.

---

## Commit Plan

Работа растянута по 2 репо (contenthunter + autowarm). Ниже — план коммитов по фазам.

### Checkpoint 1 — после T1+T2+T3 (verification closure)

**contenthunter:**
```
docs(evidence): follow-ups verification — IG T7 / TT 48h / ADB T15 (2026-04-20)

- ig-camera-fix-24h-20260420.md: 24h post-deploy metrics, residual-444 check
- tt-publishing-48h-20260420.md: 7 acceptance criteria pass/fail table
- adb-chunked-smoke-20260420.md: chunked vs direct distribution, timeout trend
- PLAN.md T7 closed
```
**autowarm (commits пользователь делает сам — правит планы):**
```
docs(plans): mark tt-publishing-resolution acceptance + adb-chunked T15 as done
```

### Checkpoint 2 — после T4 (triage)

**contenthunter:**
```
docs(evidence): publish_failed_generic catch-all triage (7d window, 30 cases classified)
```

### Checkpoint 3 — после T5 (LLM-recovery brief)

**contenthunter:**
```
docs(plans): brief for LLM screen-recovery (farming Candidate D, port from auto_public)
```

### Checkpoint 4 — после T6 (guard tests)

**autowarm:**
```
test(publisher): unit coverage for _check_account_device_mapping (5 scenarios)
```

### Checkpoint 5 — после T7 (reinstall merge)

**contenthunter:**
```
chore: global AIF reinstall (23 skills + MCP handoff)
```
— squash-merge `feature/aif-global-reinstall` → main.

---

## Риски и контр-меры

1. **48h-окно для TT/ADB уже истекло** — данные должны быть полные, но если `scripts/tt_publishing_48h.sql` показывает `0 rows` — это ранний знак что deploy не дошёл до прода. **Контрмера:** до T1-T3 проверить `pm2 status autowarm` и `autowarm_tasks.updated_at MAX` — живёт ли сервис.
2. **LLM-recovery (T5) — новая зависимость на внешний API (Anthropic/OpenRouter).** Может ввести latency и cost. **Контрмера:** T5 — только BRIEF; решение о рантайм-интеграции принимает пользователь на основе sizing.
3. **aif-global-reinstall merge (T7)** — shared-state change. **Контрмера:** `git diff main..feature/aif-global-reinstall` показать пользователю **до** merge; подтверждение обязательно.
4. **Cross-repo plan** — commits идут в два репо, легко потерять синхронизацию. **Контрмера:** в каждом evidence-файле явно указывать SHA коммитов в autowarm (из `git -C /root/.openclaw/workspace-genri/autowarm log -1`).

## Что намеренно НЕ делаем

- **Не запускаем имплементацию T5 (LLM-recovery)** — только brief. Full-plan и код — отдельной сессией после approval.
- **Не трогаем publisher.py** в T6 — только тесты. Если тест обнажает баг — отдельный fix-plan.
- **Не делаем force-push** ни в одном репо.
- **Не трогаем VK/FB/X** — out of scope per memory `project_autowarm_scope`.
- **Не создаём ветку** в contenthunter под этот план — план и evidence живут на текущей ветке (или main после T7), правки кода — в autowarm с его pre-commit-hook auto-push conventions.

## Next step

После approve плана — `/aif-implement` по T1-T7 последовательно. Оптимальный порядок: T1→T2→T3 (batch verification) → Checkpoint 1 → T4 → T5 → T6 → T7 (под подтверждение).
