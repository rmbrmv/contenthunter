# WP#182 — SHIPPED+DEPLOYED 2026-05-28

**WP:** [OP#182](https://openproject.contenthunter.ru/work_packages/182)
**Триаж:** `docs/evidence/2026-05-28-tt-failures-triage.md`
**Spec:** `docs/superpowers/specs/2026-05-28-wp182-tt-open-list-hardening-design.md`
**Plan:** `docs/superpowers/plans/2026-05-28-wp182-tt-open-list-hardening.md`
**Code PR:** [GenGo2/delivery-contenthunter#123](https://github.com/GenGo2/delivery-contenthunter/pull/123) (merge commit `f8ca9e8`)
**Docs PR:** [rmbrmv/contenthunter#24](https://github.com/rmbrmv/contenthunter/pull/24)

---

## TL;DR

- Закрыли рецидив `tt_account_sheet_closed_before_parse` (10 случаев 27.05+28.05 после нулевой полосы 23–26.05).
- 2 независимых kill-switch в `_open_tt_account_switcher` (`autowarm-testbench/account_switcher.py`):
  - **`TT_OPEN_LIST_PROBE_STALE_GUARD_ENABLED`** (default ON) — на последней probe-попытке если dump !usable + dumpsys=TikTok → honest `tt_open_list_probe_stale_ui` (зеркало WP#131 на стадии открытия списка).
  - **`TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED`** (default ON) — после неудачных probes если dump валиден + есть `Меню профиля` button → Phase 2 menu-path helper вместо legacy generic-fail.
- Helper-рефактор: текущая Phase 2 menu-path вынесена в `_run_tt_phase2_menu_path` — вызывается из Stories-pivot ветки и нового fallback (общая поверхность).

## Что закрывает

| подкласс | n | задачи |
|---|--:|---|
| probe-тап не открывает sheet, dump валидный | 4 | 11554, 11565, 11658, 11673 |
| stale uiautomator после probe-тапа | 1 | 11668 |

Первый класс → закрывается Phase 2 fallback (Изменение №2). Второй → stale-guard (Изменение №1) с честным кодом `tt_open_list_probe_stale_ui`.

## Что не входило (бэклог)

- Каретка `▾` детект (из WP#96-кармана) — если 4-class «sheet просто не открылся» повторится после фикса → отдельный WP.
- Обновление каталога `publish_error_codes` под новый код `tt_open_list_probe_stale_ui` — отдельный таск семейства WP#140.
- Cold-restart TT при stale dump — оркестратору.

## Реализация (8 коммитов на feat/wp182-tt-open-list-hardening)

| commit | что |
|---|---|
| `b5ddb11` | env-helpers `_tt_open_list_{phase2_fallback,probe_stale_guard}_enabled` |
| `5a3f151` | rename → `_ENABLED` суффикс (code review fix) |
| `78d2fca` | `_has_tt_profile_screen_signature` helper |
| `a8c2b0b` | рефактор Phase 2 menu-path в `_run_tt_phase2_menu_path` |
| `fcf5a15` | stale-guard на probe (Изменение №1) |
| `928d4e3` | Phase 2 fallback при sheet-not-opened (Изменение №2) |
| `dd869d0` | kill-switches OFF keep legacy (regression-страховка) |
| `fbd8000` | Stories-pivot still works (regression) |

## Тесты

- **15 unit-тестов** в `tests/test_account_switcher_tt_open_list_hardening.py` (env-flags 4, profile-signature 4, stale-guard 3, Phase 2 fallback 2, kill-switches off 1, Stories-pivot regression 1).
- **132 TT baseline GREEN** (`test_account_switcher_tt`, `_stale_ui`, `_switch_fg_guard`, `_retry_fg_drift`, `_tt_account_switcher_open`, `_canonical_error_codes`).
- **29 IG/YT smoke GREEN** (`test_publisher_instagram_share_retry`, `test_account_switcher_yt_stale_ui` — параллельные WP#180/#181).
- **Pre-existing failures** (`test_testbench_orchestrator`, `test_switcher_read_only`, `test_unic_logo_resolver`) — НЕ связаны с этим PR, идентичны на main.

## Codex review

- **0 P1.** Один P2 (codex говорит «fallback срабатывает на первой probe») — **false-positive**: код в `if not stories_seen:` ветке (account_switcher.py:5053), которая отрабатывает только ПОСЛЕ окончания `for attempt in range(2)`. Покрыто тестом `test_probe_fail_valid_dump_triggers_phase2_fallback` (`side_effect=[dump,dump]` — две probe).

## Деплой

- 2026-05-28 14:53 UTC — merge в `main` (autowarm-testbench `f8ca9e8`).
- Post-commit auto-pull (per [reference_autowarm_git_hook]) подхватил прод checkout.
- Рестарт PM2 не требуется (env-flags читаются на спавн задачи через `os.environ.get`).
- 0 регрессий на baseline + 0 P1 codex → раскатка без canary (доминанта 5/28 = 18 % дневных TT-фейлов, риск low/medium).

## Метрики успеха (verify-окно 48ч)

- За 48ч: signature `tt_account_sheet_closed_before_parse` в `publish_tasks.events::text` ≥50% спад относительно 27-28.05 baseline (10 случаев суммарно).
- Появляются позитивные эмиты `tt_open_list_probe_fallback_to_phase2` → дальнейший success (Phase 2 открыл sheet).
- Появляются эмиты `tt_open_list_probe_stale_ui` (если stale случается) вместо `tt_account_sheet_closed_before_parse`.
- Нет всплеска `tt_drawer_tap_did_not_open_sheet`, `tt_account_menu_unknown_layout` (Phase 2 path не ломается под нагрузкой).

## Rollback

- `TT_OPEN_LIST_PHASE2_FALLBACK_ENABLED=0` и/или `TT_OPEN_LIST_PROBE_STALE_GUARD_ENABLED=0` в `.env` прод autowarm.
- Без рестарта PM2 — `load_dotenv` подхватывает на спавн задачи.

## SQL для verify (1ч/24ч/48ч)

```sql
-- Позитивы за час
SELECT id, status, error_code FROM publish_tasks
WHERE platform='TikTok' AND testbench=false
  AND created_at > now() - interval '1 hour'
  AND events::text LIKE '%tt_open_list_probe_fallback_to_phase2%';

-- Тренд сигнатуры (сравнение с baseline 27-28.05)
SELECT created_at::date d, count(*) FROM publish_tasks
WHERE platform='TikTok' AND testbench=false
  AND created_at > '2026-05-27'
  AND events::text LIKE '%tt_account_sheet_closed_before_parse%'
GROUP BY 1 ORDER BY 1;

-- Новые честные эмиты
SELECT created_at::date, count(*) FROM publish_tasks
WHERE platform='TikTok' AND testbench=false
  AND events::text LIKE '%tt_open_list_probe_stale_ui%'
GROUP BY 1 ORDER BY 1;
```
