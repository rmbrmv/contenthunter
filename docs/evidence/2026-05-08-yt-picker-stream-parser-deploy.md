# YT picker hierarchical parser — deploy + evidence

**Дата:** 2026-05-08
**Sub-project:** YT (P1.4 — parser, P0.1 — empirical re-queue validation)
**Spec:** `docs/superpowers/specs/2026-05-08-yt-picker-stream-parser-design.md`
**Plan:** `docs/superpowers/plans/2026-05-08-yt-picker-stream-parser-plan.md`

## TL;DR

- **Парсер (P1.4) — отгружено в prod main `1a90545`.** 19/19 unit tests green. 118 NULL-gmail YT аккаунтов теперь могут быть дозаполнены через `backfill_yt_gmails.py` (раньше парсер возвращал `[]` для иерархичного picker'а).
- **Switcher (P0.1) — закрыт без code-fix.** Live evidence показал что после deploy `bb7c140` (sub-project B вчера) Feminista YT publish'ится успешно: tasks 3653/3654/3655/3694/3700/3701 = `done`. Original 3243/3246/3247 fails были pre-deploy состоянием. Re-queue не потребовался.
- **Parser fix реально нужен другим аккаунтам.** 7 из 9 recent (последний час) YT-fail аккаунтов с error_code `yt_target_not_in_picker_after_scroll` имеют NULL gmail в `factory_inst_accounts`. После backfill (теперь работает на иерархичном picker'е) они получат gmail и `find_yt_row_by_gmail` сможет их матчить.

## Хронология

| Время (UTC) | Событие |
|---|---|
| 2026-05-08 ~06:30 | Начат brainstorming + spec через Codex review |
| 2026-05-08 ~07:30 | Spec approved, plan написан + Codex review |
| 2026-05-08 ~08:00–09:00 | Tasks 1-5 в worktree через subagent-driven workflow |
| 2026-05-08 ~09:05 | Task 6: push branch → merge `1a90545` в `autowarm-testbench` main → auto-push в `GenGo2/delivery-contenthunter` |
| 2026-05-08 ~09:10 | Task 7: pull `1a90545` в `/root/.openclaw/workspace-genri/autowarm/`, `sudo pm2 reload autowarm` (restart 268) |

## Code state

### Tests
```
$ cd /home/claude-user/autowarm-testbench-yt-parser
$ python3 -m pytest tests/test_yt_gmail_probe.py -v
============================= 19 passed in 0.05s =============================
```

11 existing tests + 8 new hierarchical tests, все green.

### Smoke (prod)
```
$ cd /root/.openclaw/workspace-genri/autowarm
$ python3 -c "
from yt_gmail_probe import extract_yt_picker_pairs
xml = open('tests/fixtures/yt_picker_hierarchical_154.xml').read()
print(extract_yt_picker_pairs(xml))
"
[('feminista.beauty', 'veronikamavrikeva@gmail.com'), ('WellFresh_1', 'zxclesya154@gmail.com')]
```

Bogus `('zxclesya154@gmail.com', 'zxclesya154@gmail.com')` отсутствует — `_finalize_pairs` фильтр работает.

## Архитектура парсера

| Helper | Роль |
|---|---|
| `_extract_legacy_format_pairs` | Старая логика — `(text, gmail)` из нод где gmail в `desc` |
| `_extract_legacy_format_deleted_pairs` | Зеркало legacy для `«Канал удалён»` rows |
| `_extract_hierarchical_pairs(xml, deleted_only)` | NEW — stream state-machine, `current_gmail` из gmail-header нод, emit'ит handle/display из clickable container'ов |
| `_finalize_pairs` | Drop bogus `(gmail, gmail)` + dedup по `(lowercase identifier, lowercase gmail)` |
| `extract_yt_picker_pairs` (public) | `_finalize_pairs(legacy + hierarchical(deleted_only=False))` |
| `extract_yt_picker_deleted_pairs` (public) | `_finalize_pairs(legacy + hierarchical(deleted_only=True))` |

Критический invariant: gmail-header detect выполняется ДО deleted_only filter (codex review caught — иначе deleted-only path не работает на иерархичном picker'е).

## Original P0.1 hypothesis disproven

Spec предполагал что 3243/3246/3247 могут провалиться повторно из-за `find_yt_row_by_gmail` + современный picker. Реальность:

| publish_task | account | started_at | status | error_code |
|---|---|---|---|---|
| 3243 | feminista.beauty | 2026-05-07 05:50 | failed | yt_target_not_in_picker_after_scroll (pre-deploy) |
| 3246 | feminista_patches | 2026-05-07 05:58 | failed | (pre-deploy) |
| 3247 | feminista_glow | 2026-05-07 06:07 | failed | (pre-deploy) |
| 3653 | feminista.beauty | 2026-05-07 18:20 | **done** | — |
| 3654 | feminista_patches | 2026-05-07 18:20 | **done** | — |
| 3655 | feminista_glow | 2026-05-07 18:38 | **done** | — |
| 3694 | feminista.beauty | 2026-05-08 06:05 | **done** | — |
| 3700 | feminista_glow | 2026-05-08 06:23 | **done** | — |
| 3701 | feminista_patches | 2026-05-08 06:27 | **done** | — |

То есть после deploy `bb7c140` (sub-project B sub-task — gmail column + ручной fill 3 паков) switcher уже работал на этих аккаунтах через `find_yt_row_by_gmail`. Offline analysis dump'ов `/tmp/yt_debug_154/round_*.xml` подтвердил то же — `find_yt_row_by_gmail('veronikamavrikeva@gmail.com')` возвращает координаты внутри clickable Feminista row.

**Вывод:** `find_yt_row_by_gmail` универсален (работает на UIElement[] с label содержащим gmail + ближайший clickable row). Не нужен code-fix. Brainstorming сессия 2026-05-07 переоценила риск.

## Реальная ценность parser fix

`backfill_yt_gmails.py` запускается ДО switcher'а — задача backfill: для каждого `factory_inst_accounts` row с `gmail IS NULL` пройтись по YT picker'у и через `match_gmail_to_handle(handle, pairs)` найти gmail.

Pre-deploy: парсер возвращал `[]` для иерархичного picker'а → 0 кандидатов → backfill ничего не дозаполнял. Post-deploy: парсер возвращает корректные пары → backfill заполняет gmail → switcher позже работает.

**Метрика:**

```
factory_inst_accounts WHERE platform='youtube' AND active=true:
  total: 280
  with_gmail: 162 (58%)
  null_gmail: 118 (42%)
```

**118 NULL-gmail accounts** теперь могут быть дозаполнены backfill'ом.

**Cohort recent fails:** 7 из 9 task'ов с `yt_target_not_in_picker_after_scroll` за последний час (clickpay_express/clickpay_hub/clickpay_life/clickpay_me/clickpay_officia/easy.virtualpay/smart.card.system) имеют NULL gmail. Эти аккаунты — реальные кандидаты для backfill теперь когда парсер починен.

## Решения

- ✅ Sub-project YT closed: parser fix отгружен, switcher empirically работает.
- ✅ P0.1 (switcher) — closed без code-fix.
- ✅ P1.4 (parser) — closed, code в prod.
- ✅ **Backfill batch выполнен:** `backfill_yt_gmails.py --all --parallel 8` (09:20–09:30 UTC, ~10.5 мин). Результат: **64 NULL→filled gmail UPDATEs** (118 → 54 NULL). Coverage 58% → 81%. 16 минор-ошибок (device unavailable / picker не загрузился) — не блокеры. Лог: `/tmp/backfill_yt_2026-05-08.log`.
- ⏭️ **54 оставшихся NULL** — accounts либо не залогинены на устройствах, либо имеют не-`@gmail.com` домены (out of scope per spec R6). Operational track: оператор re-login batch'ом или explicitly skip.

## Связанные коммиты

| SHA | Где | Описание |
|---|---|---|
| `bf49450` | autowarm-testbench feature branch | 4 fixtures (Task 1 v1) |
| `d22c707` | feature branch | drop orphan + add live-sibling (Task 1 review fix) |
| `5b043a4` | feature branch | refactor legacy → helpers (Task 2) |
| `c9b36a5` | feature branch | docstring expand (Task 2 review fix) |
| `190ac01` | feature branch | `_finalize_pairs` (Task 3) |
| `7ba347d` | feature branch | 8 failing tests red (Task 4) |
| `1e3e945` | feature branch | hierarchical parser + wire (Task 5) |
| **`1a90545`** | **autowarm-testbench main** | merge — 7 commits, 19/19 tests green |

## Memory updates (требуются)

- `project_session_2026_05_07_shipped.md` — закрыть пункты `B-YT-parser` (✅ shipped) и `B-YT-switcher` (✅ closed без code-fix).
- Можно создать новую memory `project_yt_picker_parser_shipped.md` — но проще обновить session memory inline.
