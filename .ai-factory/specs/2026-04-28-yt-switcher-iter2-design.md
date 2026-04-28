# YT Account Switcher — Iteration 2 (Design)

**Date:** 2026-04-28
**Author:** Danil Pavlov
**Status:** Draft → User review pending
**Predecessor:** `.ai-factory/specs/2026-04-27-yt-publish-stabilization-design.md`
**Predecessor evidence:** `.ai-factory/evidence/yt-publish-stabilization-20260427.md`

---

## 1. Background

Сессия 04-27 отгрузила 6 фиксов в YT switcher (T2-T7) + B6 v3 foreground guard, но live acceptance — 0/13. Главная причина: smoke-инжекты использовали несуществующий `media_path`, B6 v3 ни разу не получил валидного запуска.

После закрытия сессии testbench-orchestrator самостоятельно запустил ~13 YT-задач (id 1499-1511, 04-28 01:54-02:34 UTC). **Все failed.** Причина — единая регрессия:

```
Критическая ошибка: name 'random' is not defined
category=critical_exception, platform=YouTube, ts=05:36:12
```

`publisher_base.py` использует `random.*` 5 раз (строки 2370, 2376, 2384, 2789, 2936), но `import random` отсутствует среди импортов (строки 21-33). Это lost-import паттерн от publisher.py split, ровно тот же класс ошибки, что и предыдущая `testbench-publisher-base-imports-20260427` (commit `3e2fe0dec`).

Fail происходит **в pre-warm phase, до того как `_switch_youtube` запускается**, поэтому B6 v3 / T2-T7 helpers ни разу не отработали в продакшен-сценарии.

## 2. Goal

≥8 из 10 первых testbench YT publish-задач на phone #19 в статусе `done`, где задачи отфильтрованы по аккаунтам `[makiavelli-o2u, Инакент-т2щ]` после финального T2 deploy.

**Sanity invariant:** ≥1 done на каждом из двух аккаунтов (нельзя пройти gate, если один аккаунт даёт 0/5).

## 3. Non-goals

- TT и IG switcher hardening (вне scope; cross-platform error namespace уже отгружен в T7).
- Pre-warm refactoring (трогаем минимально — только missing import).
- Любые UI / frontend изменения (T7 уже дал `error_code` badge + banner).
- Promo-modal scenario — не было screenshot evidence; deferred до появления.

## 4. Architecture — Phasing & decision gate

```
T0 ── random fix (atomic unblock, ≤10 min)
 │
 ▼
T1 ── Live baseline gathering (60-90 min, free run)
 │
 ▼
[GATE]  top-N failure reasons + per-account ratio
 │
 ├─► already 8/10 ─────────────► T3 acceptance ─► DONE
 │
 ▼
T2 ── Targeted fixes (subagent-driven, scope locked at gate)
 │     1 fix → 1 subagent → 1 live retest
 │
 ▼
T3 ── Acceptance batch (10 первых задач после финального T2 deploy)
```

**Свойства:**
- GATE — единственная точка где T2 scope материализуется. Phase 2 фиксы — evidence-driven, не desk-think.
- Между фиксами: apply → smoke 1 → read events → next (per memory `feedback_silent_crash_layered.md`).
- Не batchаем 8 фиксов сразу (урок 04-27 lessons learned 1, 6).

## 5. Components

### 5.1 T0 — `import random` regression fix

| Что | Где |
|---|---|
| Добавить `import random` после строки 21 (`import os`) | `autowarm-testbench/publisher_base.py` |
| Cherry-pick того же коммита в prod | `/root/.openclaw/workspace-genri/autowarm/publisher_base.py` (auto-push hook → `GenGo2/delivery-contenthunter`) |
| Unit test | новый `test_publisher_base_imports.py::test_random_imported`: `import publisher_base; assert hasattr(publisher_base, 'random')` |
| Smoke verification до T1 | `pytest tests/test_publisher_base_imports.py -v` (зелёный gate перед deploy) |
| pm2 restart | `pm2 restart autowarm autowarm-testbench` (под root) |
| Cwd drift check | `pm2 describe autowarm \| grep "exec cwd"` — должен указывать на `/root/.openclaw/workspace-genri/autowarm/`. Если нет: `pm2 delete autowarm && pm2 start ecosystem.config.js --only autowarm`. |

### 5.2 T1 — Live baseline gathering

| Артефакт | Содержание |
|---|---|
| Триаж-скрипт `tools/yt_failure_triage.py` | агрегатор по 10 первым YT-задачам после T0_TS, фильтр аккаунтов `[makiavelli-o2u, Инакент-т2щ]`. Output: reason histogram, per-account ratio, B6 hit/miss counter, last-step distribution |
| Evidence-файл `.ai-factory/evidence/yt-switcher-iter2-20260428.md` | T0 commits, T1 baseline numbers, GATE decision, T2 scope justification, T3 acceptance result |
| DB read-only | `publish_tasks.events` JSONB, фильтр `created_at > T0_TS` |
| Manual seed fallback | если orchestrator за 90 мин не нагенерит ≥5 задач на каждый аккаунт, копируем 5+5 `media_path` из последних естественных задач (`/tmp/publish_media/pq_*.mp4`) и инжектим вручную |

### 5.3 T2 — Targeted fixes (locked at GATE)

**Правила (per memory `reference_publisher_proxy_api.md`, `feedback_silent_crash_layered.md`):**
1. Pre-flight grep `self.p.log_event/adb/dump_ui` API в `publisher_base.py` ДО написания spec.
2. Один фикс — один subagent dispatch (spec-review → implementer → code-quality).
3. Один фикс — один коммит — один live retest.
4. Spec для каждого T2-фикса короткий: 1 проблема, 1 helper, ≤3 unit tests.

**Кандидаты на T2 (приоритизируются после GATE по частоте):**
- T7 mapper precedence: overwrite старого `error_code` каноническим, если первый writer set'ит pre-canonical (deferred follow-up #2 из 04-27).
- Pre-existing `dumpsys window windows` в `account_switcher.py:2305, 2463` (B6 v2 урок, deferred #3).
- Инакент-specific failure investigation (4% historical pass rate — обязательная T2-ветка).
- Любой новый dominant `meta.reason` из T1 histogram.

### 5.4 T3 — Acceptance batch

| Параметр | Значение |
|---|---|
| Source | testbench-orchestrator natural rotation после финального T2 deploy |
| Кол-во | 10 (5 makiavelli + 5 Инакент) |
| Acceptance | `done >= 8` AND `done(makiavelli) >= 1` AND `done(Инакент) >= 1` |
| PM2-restart-killed | excluded from counting вручную (если pm2 restart произошёл во время batch'а — список id фиксируется в evidence-файле и исключается из COUNT в SQL ниже) |

## 6. Data flow at T1

```
T0 deploy (T_0)
 │
 ▼
testbench-orchestrator → publish_tasks (auto-seed)
 │
 ▼
publisher.py executes → account_switcher.py (B6 v3, T2-T7 helpers)
 │
 ▼
status ∈ {done, failed, preflight_failed}
 │
 ▼
yt_failure_triage.py:
 ├─► histogram(error events): meta.reason → count
 ├─► breakdown by account: makiavelli vs Инакент
 ├─► B6 v3 hits: events с category='yt_app_not_foregrounded'/'yt_foreground_relaunched'
 └─► last-step distribution
 │
 ▼
GATE input → T2 spec.md justification
```

## 7. Error handling & testing

### 7.1 T0

| Сценарий | Поведение |
|---|---|
| pytest `import publisher_base` падает | блокер для merge, ревью |
| pm2 restart фейлит | revert commit, escalate |
| После deploy всё равно `name 'random' is not defined` | cwd drift fix (5.1 last row) |
| Всплывает другой NameError | T0 расширяется на full-imports audit `publisher_base.py` через grep `r"^[a-z_]+\."` |

### 7.2 T1

| Сценарий | Поведение |
|---|---|
| Orchestrator seedит чужой аккаунт | filter в триаж-скрипте; если systematic — fix orchestrator config до GATE |
| 0 свежих задач за 90 мин | manual inject 5+5 (media_path из 1499-1511) |
| events JSONB пуст | `pm2 logs autowarm --lines 200` для stderr trace |

### 7.3 T2

Каждый фикс по правилам 5.3. Между фиксами apply→smoke→read→next.

### 7.4 T3

| Сценарий | Поведение |
|---|---|
| 8/10 done + sanity ok | success, evidence финализируется, memory updates |
| 5-7 done | partial — re-triage, новый T2 цикл или stop с честным partial |
| <5 done | regression — git bisect T2 commits, откат подозрительного |
| pm2 restart killed mid-flight | task excluded |

## 8. Unit tests summary

- `test_publisher_base_imports.py::test_random_imported` (новый, T0)
- T2-fix tests — определяются после GATE, по 1-3 на фикс

## 9. Acceptance criterion (formal)

**Timestamp anchor:** `T_ANCHOR` = timestamp последнего T2 deploy. Если GATE решил skip T2 (T1 baseline уже даёт 8/10) → `T_ANCHOR = T0_TS`.

**Excluded ids:** список id задач, убитых pm2 restart во время batch'а — фиксируется руками в evidence-файле, подставляется в SQL.

```sql
WITH bucket AS (
  SELECT id, account, status FROM publish_tasks
  WHERE platform='YouTube'
    AND account IN ('makiavelli-o2u', 'Инакент-т2щ')
    AND created_at > '<T_ANCHOR>'
    AND id NOT IN (<EXCLUDED_IDS>)  -- pm2-killed list, e.g. (1234, 1235); use (-1) if none
  ORDER BY id LIMIT 10
)
SELECT
  COUNT(*) FILTER (WHERE status='done') AS done,
  COUNT(*) FILTER (WHERE status='done' AND account='makiavelli-o2u') AS done_maki,
  COUNT(*) FILTER (WHERE status='done' AND account='Инакент-т2щ') AS done_inak,
  COUNT(*) AS total
FROM bucket;
-- pass: done >= 8 AND done_maki >= 1 AND done_inak >= 1
```

**Template placeholders** (`<T_ANCHOR>`, `<EXCLUDED_IDS>`) заполняются в evidence-файле во время выполнения T3.

## 10. Risks

- **GATE может найти что Инакент-т2щ broken на уровне аккаунта (logout, captcha, channel deleted).** В таком случае T2 = `_check_picker_for_logout_rows` уже отгружен в T4, но не сработал — нужен инвестигейт почему. Если аккаунт реально мёртв, sanity invariant блокирует acceptance — придётся ремонтировать аккаунт или менять scope.
- **B6 v3 регрессия:** `topResumedActivity` может вернуть пусто при определённых состояниях (lock screen, sleep). T1 покажет.
- **Orchestrator seed pool:** в логах видны чужие аккаунты (anecole, forchil) — возможно cross-phone seeding. Если так, нужен фильтр на phone-level до T3.

## 11. Memory updates после iteration

- `project_yt_publish_stabilization_partial.md` → mark «iter2 closed» с финальным результатом.
- Если new dominant reason — новая memory.
- `reference_testbench_smoke_paths.md` — добавить факт что `/tmp/publish_media/pq_*.mp4` это runtime-generated, не seed pool.
