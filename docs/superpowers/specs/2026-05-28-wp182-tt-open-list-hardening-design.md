# WP#182 — TT _open_tt_account_switcher hardening (design)

**Дата:** 2026-05-28
**WP:** [OP#182](https://openproject.contenthunter.ru/work_packages/182)
**Триаж:** `docs/evidence/2026-05-28-tt-failures-triage.md`
**Файл-цель:** `autowarm-testbench/account_switcher.py`, метод `_open_tt_account_switcher` (строки 4770-4872).

---

## 1. Проблема

За 27.05 и 28.05 TikTok-сигнатура `tt_account_sheet_closed_before_parse` вернулась на 5 + 5 случаев после нулевой полосы 23–26.05 (WP#96 был закрыт 26.05 как resolved-by-environment).

Корректное распределение 5 задач за 28.05 (после перепроверки с XML-дампами):

| подкласс | n | задачи | природа |
|---|--:|---|---|
| probe-тап не открывает sheet, dump валидный | 4 | 11554, 11565, 11658, 11673 | `@username` clickable=true, тап не открывает sheet на этом TT-UI-варианте |
| stale uiautomator после probe-тапа | 1 | 11668 | все 4 probe-dump usable=False / 18981B / 1 нода |

Исходная классификация в evidence (Stories editor / Search drift) — ошибочна; storyring-маркер был лишь индикатором аватарки, а «Поиск» — это `_top_labels` опакового dumpа. Скорректировано через прямое чтение дампов (`probe1_11673.xml`, `pr1_11565.xml`, `p1_11668.xml`).

## 2. Где ломается сейчас

`_open_tt_account_switcher` (account_switcher.py:4770-4872):

```
Phase 1: 2× probe via _tap_profile_header
  + parse_ui_dump
  + sheet detection (anchor || @-handle signature)
  → если sheet → success
  → если Stories detected → BACK + Phase 2 menu path
  → если ничего из выше → fail tt_account_sheet_closed_before_parse
```

Два пробела:

- **Пробел №1.** Phase 2 (menu-path через «Меню профиля» → drawer → «Управление аккаунтами») запускается **только** при `stories_seen=True`. Когда sheet просто не открылся (4/5 наших случаев) — fail без попытки Phase 2.
- **Пробел №2.** Случай stale uiautomator (probe_dump 18981B/1 нода, usable=False) на этой стадии не обрабатывается. Существующий WP#131-фикс (`_tt_probe_looks_stale` + `_tt_dumpsys_confirms_foreground`) работает в `tt_2_profile_tab` retap-петле, **до** Phase 1 probe этого метода.

## 3. Дизайн фикса

Два изменения внутри `_open_tt_account_switcher`, независимо ограждённые kill-switches (default ON).

### 3.1. Изменение №1 — stale-guard на probe dump

**Kill-switch:** `TT_OPEN_LIST_PROBE_STALE_GUARD` (default `1`).

**Logic.** Внутри цикла `for attempt in range(2):` Phase 1 probe — **после** `probe_elements = parse_ui_dump(probe_dump) if probe_dump else []` и **перед** sheet-detection. Эмит **только на последней (2-й) попытке**, чтобы дать первой возможность восстановиться (transient stale на 1-й попытке — известный пред-RC поведения):

```python
is_last_attempt = (attempt + 1 == 2)
if _tt_open_list_probe_stale_guard_enabled() \
        and is_last_attempt \
        and not is_dump_usable(probe_elements) \
        and self._tt_dumpsys_confirms_foreground(cfg['package']):
    variant = ('opaque_hierarchy'
               if (probe_dump and cfg['package'] in probe_dump)
               else 'launcher_empty')
    return _emit_error(
        'tt_open_list_probe_stale_ui',
        {'probe_attempt': attempt + 1,
         'variant': variant,
         'probe_empty': not bool(probe_dump),
         'target': target})
```

На 1-й попытке `attempt+1 == 1` гард не срабатывает — цикл переходит к 2-й probe (даём transient stale шанс восстановиться). На 2-й попытке `attempt+1 == 2`, если dump всё ещё stale → honest emit.

**Не делаем:** cold-restart внутри метода — это территория оркестратора (как в WP#131). Метод возвращает honest code, оркестратор решает что дальше.

**Покрывает:** 11668-класс (1/5 за день, потенциально больше — stale uiautomator имеет длинный хвост).

### 3.2. Изменение №2 — Phase 2 fallback при «sheet просто не открылся»

**Kill-switch:** `TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED` (default `1`).

**Logic.** После цикла 2-probe, в текущей ветке `if not stories_seen:` (account_switcher.py:4840) — **до** существующего `_emit_error('tt_account_sheet_closed_before_parse', …)`:

```python
if _tt_open_list_phase2_fallback_enabled() \
        and is_dump_usable(probe_elements) \
        and self._has_tt_profile_screen_signature(probe_elements):
    # Pivot to Phase 2 (тот же путь, что после Stories → BACK).
    # Перед прыжком — диагностический эмит для трассируемости.
    self.p.log_event(
        'account_switch',
        'tt_probe_fallback_to_phase2: dump valid + profile screen + '
        'no sheet/stories → пробуем menu-path',
        meta={'category': 'tt_open_list_probe_fallback_to_phase2',
              'target': target})
    # дальше — существующий код Phase 2 menu path (строки 4894–4872 текущей реализации
    # начиная с `menu_dump = self.p.dump_ui(retries=1)` после BACK)
    # вынесен в отдельный helper для общего вызова Stories-pivot и нашего fallback.
```

**Helper-рефактор.** Чтобы не дублировать Phase 2 код в двух местах, выносим логику «открыть drawer → найти trigger → settings-nested fallback → scroll-search» — то есть строки **начиная с комментария `# --- Phase 2: menu path (inline tap; orchestrator owns pre-tap dump) ---` (account_switcher.py:4894) и до конца метода** — в private helper `_run_tt_phase2_menu_path(target, step_base, anchors, cfg)`. Helper возвращает `(anchor_bounds, error_code)`, тот же контракт что и сам `_open_tt_account_switcher`. Helper НЕ включает Stories-BACK блок (4874-4892) — он остаётся inline в Stories-pivot ветке (BACK нужен только когда мы пришли через Stories).

Stories-pivot ветка (4874-4892) делает BACK + own-profile проверку, потом вызывает `_run_tt_phase2_menu_path(...)`. Новый fallback (3.2 этой спеки) сразу вызывает `_run_tt_phase2_menu_path(...)` — мы уже на профиле, BACK не нужен. Контракт helper'а: предполагает «foreground=TT, на собственном профиле». Это инвариант, который обе ветки гарантируют до вызова.

Рефактор узкий (~100 строк out, ~3 строки helper-call in) и сопровождается чёрно-ящичными тестами.

**Helper-метод сигнатуры:**
```
def _has_tt_profile_screen_signature(self, elements: list) -> bool:
    """True если в элементах есть «Меню профиля» button (content-desc).
    Используем как сигнал «мы всё ещё на профиле» — не Search/Feed/Stories."""
```

**Покрывает:** 4/5 (11554, 11565, 11658, 11673).

### 3.3. Что не меняется

- Существующий Stories-pivot путь (детект `_detect_tt_stories_viewer` + BACK + Phase 2) работает как сейчас — без изменения сигнатуры детектов.
- Сигнатура `_open_tt_account_switcher`: возвращает `(anchor_bounds, error_code)` — контракт не меняется. Новые ошибки добавляют коды, не ломают существующих callers.
- `_tap_profile_header` не трогаем — каретка-фикс из WP#96-кармана не нужен в этой итерации (Phase 2 fallback закрывает доминанту).

## 4. Новые элементы

| element | kind | scope |
|---|---|---|
| `TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED` env | feature-flag | module-level helper `_tt_open_list_phase2_fallback_enabled()` |
| `TT_OPEN_LIST_PROBE_STALE_GUARD` env | feature-flag | module-level helper `_tt_open_list_probe_stale_guard_enabled()` |
| `_has_tt_profile_screen_signature` | instance method | switcher class |
| `_run_tt_phase2_menu_path` | instance method (рефактор) | switcher class |
| `tt_open_list_probe_stale_ui` | error code | новый, под классификатор |
| `tt_open_list_probe_fallback_to_phase2` | event category | диагностический, тип `account_switch` |

## 5. Тестирование

### Unit (TDD, без устройства, по образцу `tests/test_account_switcher_tt.py`)

**1. `test_probe_stale_both_attempts_emits_honest_code`**
- Setup: мок `_tap_profile_header→True`, `dump_ui→<opaque 1-node XML>` для обеих probe-попыток, `_tt_dumpsys_confirms_foreground→True`.
- Expect: вернулся `(None, 'tt_open_list_probe_stale_ui')`, в `log_event` есть `meta.variant ∈ {opaque_hierarchy, launcher_empty}` и `meta.probe_attempt == 2`.

**2. `test_probe_stale_first_attempt_recovers_on_second`** (граничный кейс из codex P2)
- Setup: 1-я probe → `dump_ui→<opaque XML>` (stale). 2-я probe → `dump_ui→<dump со sheet-anchor>` (recovery).
- Expect: вернулся `(anchor_bounds, None)` (success), `tt_probe_opened_bottomsheet` эмит с `attempt=2`. Honest stale-code НЕ эмитится (мы пропустили его на 1-й попытке).

**3. `test_probe_stale_dump_but_foreground_drifted_falls_through`**
- Setup: обе probe → dump !usable + `_tt_dumpsys_confirms_foreground→False` (drift на другое приложение).
- Expect: stale-guard НЕ срабатывает (foreground drift — другая категория, дальше WP#130 / fg_drift логика на верхнем уровне `if not stories_seen:`).

**4. `test_probe_fail_valid_dump_triggers_phase2_fallback`**
- Setup: probe 2× → валидный dump с «Меню профиля» button (content-desc), без sheet-anchor, без Stories.
- Expect: `_run_tt_phase2_menu_path` вызван; emit `tt_open_list_probe_fallback_to_phase2` присутствует в log; legacy `tt_account_sheet_closed_before_parse` НЕ эмитится.

**5. `test_probe_fail_no_profile_signature_keeps_legacy_fail`**
- Setup: probe 2× → валидный dump БЕЗ «Меню профиля» button (не на профиле) + не Stories.
- Expect: `_run_tt_phase2_menu_path` НЕ вызывается; эмитится legacy `tt_account_sheet_closed_before_parse` (как сейчас).

**6. `test_kill_switches_off_keep_legacy`**
- Setup: env `TT_OPEN_LIST_PROBE_STALE_GUARD=0` и `TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED=0`.
- Expect: stale-dump на 2-й попытке → legacy `tt_account_sheet_closed_before_parse`, sheet-not-opened-valid-dump → legacy `tt_account_sheet_closed_before_parse`, Phase 2 fallback НЕ вызывается.

**7. `test_stories_pivot_still_works`**
- Регресс-тест: Stories detected на probe → BACK → `_tt_is_own_profile→True` → `_run_tt_phase2_menu_path` вызван. Та же helper-поверхность что у нового fallback, но через Stories-pivot путь.

### Smoke / live verification

- После TDD-GREEN: один canary TT (`is_canary=true`) через `publisher.py`. Ожидаем 0 регрессий в 1ч окне.
- Проверка в БД через час: `events::text LIKE '%tt_open_list_probe_fallback_to_phase2%'` или `'%tt_open_list_probe_stale_ui%'` — есть ли позитивные пойманные случаи.
- При 0 регрессий → раскатка через PM2 reload (без systemd, per [feedback_deploy_scope_constraints]).

## 6. Деплой и rollback

- Деплой: PM2 reload по auto-pull post-commit (per [reference_autowarm_git_hook]).
- Rollback быстрый: `TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED=0` и/или `TT_OPEN_LIST_PROBE_STALE_GUARD=0` в `.env` + reload (`load_dotenv` подхватит на спавн).

## 7. Метрики успеха

- За 48ч после релиза: signature `tt_account_sheet_closed_before_parse` в `publish_tasks.events::text` падает к 27.05-baseline ≥50%.
- Появляются позитивные эмиты `tt_open_list_probe_fallback_to_phase2` с дальнейшим success (sheet open via Phase 2).
- Появляются эмиты `tt_open_list_probe_stale_ui` (если stale случается) вместо `tt_account_sheet_closed_before_parse`.
- Нет всплеска Phase 2-path фейлов (`tt_drawer_tap_did_not_open_sheet`, `tt_account_menu_unknown_layout`).

## 8. Риски и митигация

| риск | вероятность | митигация |
|---|---|---|
| Phase 2 fallback срабатывает на не-профильном экране и попадает в drawer чужого приложения | низкая | `_has_tt_profile_screen_signature` гард на «Меню профиля» button + `is_dump_usable` гард |
| `_tt_dumpsys_confirms_foreground` ложно-True при опаковом dump (TT действительно показывает экран, но uiautomator stale) | средняя | Это и есть целевой кейс — `tt_open_list_probe_stale_ui` честный код, оркестратор решает recovery |
| Дублирование Phase 2 invocation через рефактор ломает Stories-pivot ветку | средняя | Тест `test_stories_pivot_still_works` + закрытые границы helper'а |
| Рост вызовов Phase 2 → нагрузка drawer-парсера | низкая | Phase 2 — единичный путь, не цикл; UI-dump уже делается |
| Classifier (WP#140 каталог) не знает кода `tt_open_list_probe_stale_ui` → 19 не назначит класс | низкая | Отдельный таск на каталог (WP#140 семейство) после деплоя |

## 9. Out-of-scope

- Cold-restart TT при stale dump — оркестратор/публикатор.
- Каретка `▾` детект — не нужен сейчас; если 4-class «sheet просто не открылся» повторится после фикса → отдельный WP.
- Обновление `publish_error_codes` каталога — отдельный таск семейства WP#140.
- Изменение `_detect_tt_stories_viewer` (editor variant) — подсигнатура не подтвердилась.

## 10. Этапы

1. Поднять worktree `autowarm-testbench/feat/wp182-tt-open-list-hardening`.
2. Написать 7 unit-тестов (RED).
3. Имплементация (степ-1 helper-рефактор; степ-2 stale-guard; степ-3 Phase 2 fallback). После каждого стега — целевые тесты GREEN.
4. Полный test suite GREEN.
5. `codex review` плана и diff — 0 P1.
6. Commit на feature branch.
7. Canary TT в проде, мониторинг 1ч.
8. Раскатка через post-commit auto-pull + PM2 reload.
9. Verify-окно 48ч — обновление [[project_wp182_tt_account_sheet_closed_recur]].

## 11. Ссылки

- WP: OP#182 — <https://openproject.contenthunter.ru/work_packages/182>
- Триаж: `docs/evidence/2026-05-28-tt-failures-triage.md` (commit ac60de909)
- WP#96 evidence (каретка-карман): `docs/evidence/2026-05-26-wp96-tt-bottomsheet-not-reproducing.md`
- WP#131 stale-guard зеркало: account_switcher.py:2781, 3130–3149 + kill-switch `TT_STALE_UI_OWN_PROFILE_GUARD`
- Memory: [[project_wp182_tt_account_sheet_closed_recur]], [[project_wp131_tt_profile_tab_stale_ui]]
