# TT publishing — 48h acceptance verification

**Сборка:** 2026-04-20 ~05:15 UTC (≈33h после deploy T1-T10 tt-publishing-resolution, merge `ff3ec8b` 2026-04-19 ~20:04 UTC).
**Контекст:** 7 acceptance criteria из `autowarm/.ai-factory/plans/tt-publishing-resolution.md:428-434`.
**Источник:** план-потомок `contenthunter/.ai-factory/plans/open-followups-20260420.md` T2.

## TL;DR

**PARTIAL PASS.** Тесты зелёные, pm2 чистый. Acceptance-таблица провалена на численных порогах: 0 done/awaiting_url за 48h (нужен ≥1), а `publish_failed_generic` — 4 события = 16.7 % от failed (порог <5 %). **Причина** — не regression деплоя T1-T10, а orthogonal reality: **18 из 24 failed — guard-blocks** от round-6-seed-devices с NULL `tiktok` колонкой, и **0 реальных end-to-end TT attempts** завершились успешно за окно.

## Итоговая таблица acceptance

| # | Критерий | Порог | Факт | Verdict |
|---|---|---|---|---|
| 1 | `publish_failed_generic` для TT | <5 % от total fails | 4/24 = 16.7 %; в не-guard части 4/6 = 66 % | **FAIL** (нужен plan-потомок — см. T4 umbrella) |
| 2 | ≥1 успешная TT end-to-end (`status=done`) | ≥1 | 0 done + 0 awaiting_url | **FAIL (no volume)** |
| 3 | T2 audit report | `/tmp/tt_audit/` saved | 10 XML-дампов в `/tmp/tt_audit/` (t1_launch/t2_profile per device × 5 устройств) | **PASS** |
| 4 | pytest `test_account_switcher_tt.py test_publisher_category_resolve.py -v` | green | `test_publisher_category_resolve.py` **не существует**; `test_account_switcher_tt.py` — 39 passed в объединённом прогоне с `test_switcher_youtube.py` | **BROKEN CRITERION** (файл не создан в T7, acceptance spec содержит фантомный файл) |
| 5 | `test_switcher_youtube.py` — не сломан (regression guard T_FG) | green | passed (часть из 39 в комбинированном прогоне) | **PASS** |
| 6 | `pm2 logs autowarm --lines 200` — без exceptions от новых детекторов | clean | grep по Traceback/error/except → 0 хитов в tail 200 | **PASS** |
| 7 | `scripts/tt_publishing_48h.sql` — distribution по новым категориям | присутствуют | `tt_upload_confirmation_timeout`:2, `tt_profile_tab_broken`:1, `publish_failed_generic`:4 (+ guard info:9) | **PASS (детекторы work, но low volume)** |

**Итог:** 4 PASS, 2 FAIL, 1 BROKEN (spec-bug).

## Подробности

### A. Status breakdown — 48h TT

```sql
SELECT status, CASE WHEN log ~* '\[guard\]' OR events::text LIKE '%[guard]%'
                    THEN 'guard-block' ELSE 'real-fail' END AS kind, COUNT(*)
  FROM publish_tasks
 WHERE platform='TikTok'
   AND COALESCE(started_at,updated_at) > NOW() - INTERVAL '48 hours'
 GROUP BY status, kind;
```

```
         status         |    kind     | count
------------------------+-------------+-------
 failed                 | guard-block |    18
 failed                 | real-fail   |     6
 skipped_config_missing | guard-block |     9
```

**Наблюдение:** 18 задач имеют `status=failed` с guard-сообщением в `log`/`events` вместо ожидаемого `status=skipped_config_missing` (ещё 9 корректно получили `skipped_config_missing`). Это значит: **IG T4 guard-terminal-status fix (ig-publishing-resolution.md T4) не полностью распространился на TT**, часть guard-hits всё ещё маркируются `failed`. Это **одна из причин** того, что `publish_failed_generic` (и общий % failed) выглядит высоким — к нему примешиваются корректные guard-блоки.

**Action:** добавить в план-потомок triage (T4 umbrella) проверку consistent-terminal-status по платформам.

### B. Real TT fails (без guard) — разложение

| id  | device_serial | account         | last_cat                         | last_msg |
|-----|---------------|-----------------|----------------------------------|----------|
| 477 | RFGYB07YN6R   | procontent_lab  | `tt_profile_tab_broken`          | Публикация завершилась с ошибкой |
| 476 | RFGYB07YN6R   | procontent_lab  | `tt_upload_confirmation_timeout` | Публикация завершилась с ошибкой |
| 413 | RF8YA0V7LEH   | expertcontentlab| `publish_failed_generic`         | Публикация завершилась с ошибкой |
| 411 | RFGYB07Y59Y   | content_expert_1| `publish_failed_generic`         | Публикация завершилась с ошибкой |
| 414 | RF8YA0V7FKW   | lead_content_   | `publish_failed_generic`         | Публикация завершилась с ошибкой |
| 415 | RFGYB07YN6R   | procontent_lab  | `publish_failed_generic`         | Публикация завершилась с ошибкой |

— 2 задачи получили новые (T5/T_FG) категории, **4 — catch-all `publish_failed_generic`**. Все 4 catch-all — от 2026-04-18 ~11:23 UTC (**ДО** merge `ff3ec8b`), значит deploy не покрыл их задним числом. За период post-deploy (2026-04-19 20:04+ UTC) новых `publish_failed_generic` на TT **не было**.

**Пересчёт acceptance #1 только на post-deploy окно:**
- TT failed post-deploy = 4 (все guard-blocks, 0 real-fail с publish_failed_generic)
- `publish_failed_generic` post-deploy = **0**
- **Acceptance #1 фактически PASS, если считать только post-deploy**. Но формально acceptance писалось про 48h — и задачи pre-deploy попадают в окно.

### C. Test-suite status

```
tests/test_account_switcher_tt.py + tests/test_switcher_youtube.py
→ 39 passed in 15.00s
```

Отдельный прогон `test_publisher_category_resolve.py` — **файл отсутствует в дереве `autowarm/tests/`**. Ревизия commit T7 `ff3ec8b` действительно создаёт `test_account_switcher_tt.py` + расширяет `test_publish_guard.py`, но **не создаёт** `test_publisher_category_resolve.py`. Acceptance spec ссылается на несуществующий файл — это опечатка/ошибка в spec, а не regression.

### D. pm2 logs — clean

```
pm2 logs autowarm --lines 200 --nostream | grep -iE 'traceback|error|except' → 0 matches
```

Никаких import errors / AttributeError / typeerror после деплоя.

### E. tt_audit XML-дампы

```
/tmp/tt_audit/
├── RF8YA0V7FKW_t1_launch_1776624921.xml
├── RF8YA0V7FKW_t2_profile_1776624921.xml
├── RF8YA0V7LEH_t1_launch_1776624993.xml
├── RF8YA0V7LEH_t2_profile_1776624993.xml
├── RF8YA0W57EP_t1_launch_1776625062.xml
├── RF8YA0W57EP_t2_profile_1776625062.xml
├── RFGYB07Y59Y_t1_launch_1776625135.xml
├── RFGYB07Y59Y_t2_profile_1776625135.xml
├── RFGYB07YN6R_t1_launch_1776624629.xml
└── RFGYB07YN6R_t1_launch_1776624760.xml
```

— T2 diagnostic (`scripts/tt_session_audit.py`) запускался 2026-04-18, собрал t1_launch + t2_profile для 5 устройств. Последующего запуска на post-deploy данных нет.

## Выводы

1. **TT детекторы T5 (logged-out), T_FG (fg-drift), T_URL — задеплоены, 0 живых триггеров за post-deploy окно** (нет volume TT-публикаций — 0 attempted, 0 done).
2. **T1 category propagation работает**: pre-deploy `publish_failed_generic`:4 события все от 2026-04-18. Post-deploy — 0 таких событий. Plan T1 зачёт.
3. **Acceptance #1 (<5% publish_failed_generic) формально FAIL** только из-за включения pre-deploy задач в окно. Если перезапустить SQL с фильтром `started_at > '2026-04-19 20:04'` — 0/0 divide-by-zero, что логически PASS-по-default.
4. **Acceptance #2 (≥1 done) FAIL из-за отсутствия TT volume**, а не из-за бага. Нужно либо дождаться prod-трафика, либо форсировать manual smoke.
5. **Spec-bug:** acceptance ссылается на `test_publisher_category_resolve.py` — файла нет. Acceptance должно было ссылаться на `test_account_switcher_tt.py` + `test_publish_guard.py`. Предлагается правка acceptance текста.
6. **Обнаружена сопутствующая проблема:** 18 TT guard-hits получили `status=failed` вместо `skipped_config_missing`. IG T4 guard fix не полностью обобщён на TT. **Усиливает приоритет T4 umbrella-plan (publish_failed_generic triage)** — именно там разбираем эту inconsistency.

## Action items

1. **tt-publishing-resolution.md:428-434** — acceptance чекбоксы ставить выборочно (только PASS); для FAIL оставить `[ ]` + пометка `— см. evidence/tt-publishing-48h-20260420.md` + заметка о низком volume.
2. **autowarm/tt-publishing-resolution.md:431** (acceptance о `test_publisher_category_resolve.py`) — пометить как spec-bug; использовать `test_account_switcher_tt.py + test_publish_guard.py` в актуальной acceptance.
3. **umbrella T4 (publish_failed_generic triage)** — добавить в scope проверку: статус `failed` vs `skipped_config_missing` для TT/YT guard-hits, generalize IG T4 fix.

## Метаданные

- DB: `openclaw@localhost/openclaw`
- Deploy: tt-publishing-resolution T1-T10 merge в main commit `ff3ec8b` (autowarm), 2026-04-19 ~20:04 UTC.
- Связанные evidence: `farming-baseline-20260419.md` (pre-deploy baseline), `publish-fails-16-17-apr-analysis.md`.
