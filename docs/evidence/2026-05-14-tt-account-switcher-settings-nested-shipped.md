# TT account-switcher settings-nested path (Pattern B iter#2) — SHIPPED 2026-05-14

**PR:** [#57](https://github.com/GenGo2/delivery-contenthunter/pull/57) — squash-merged `8e7623a`.
**Deploy:** prod-чекаут `/root/.openclaw/workspace-genri/autowarm` fast-forward `f21ee7b → 8e7623a`; PM2 `autowarm` restart, `exec cwd = /root/.openclaw/workspace-genri/autowarm` подтверждён (без path-drift).
**OpenProject:** WP [#60](https://openproject.contenthunter.ru/work_packages/60).
**Триаж:** `docs/evidence/2026-05-14-tt-publish-failures-triage.md`.
**План:** `docs/superpowers/plans/2026-05-14-tt-account-switcher-settings-nested-path.md` (codex review: 0 P1/P2).

## Что было не так

`tt_account_menu_unknown_layout` — **13 упавших задач TikTok-выкладки за 2026-05-14**, крупнейший одиночный баг дня (TT: 45 failed / 9 done, fail-rate ~79%). Свежий TikTok убрал вход в переключатель аккаунтов из drawer'а «Меню профиля» — он переехал на уровень глубже, под «Настройки и конфиденциальность» → «Управление аккаунтами». Оркестратор Pattern B (PR #52) доходил до drawer'а, не находил якорь `TT_DRAWER_ACCOUNT_TRIGGERS` и падал fail-fast.

Это была запланированная **iter#2** правка — диагноз был расписан в `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` § "Iteration #2", подтверждён триажём (идентичный `drawer_labels[]` на 4 задачах, UI-dump drawer'а task 5722, кадры скринкаста, blast radius 10 устройств).

## Что сделано

Аддитивная правка оркестратора `_open_tt_account_switcher` в `account_switcher.py`:

- `_find_tt_account_switcher_anchor_in_drawer` получил опциональный параметр `triggers` (default `TT_DRAWER_ACCOUNT_TRIGGERS`) — двухпроходный поиск кликабельного якоря переиспользуется как есть.
- Новая module-level константа `TT_DRAWER_SETTINGS_TRIGGERS` (`настройки и конфиденциальность` / `settings and privacy` / `настройки` / `settings`), специфичные двусловные строки впереди bare-fallback'ов.
- В `_open_tt_account_switcher`: когда якорь аккаунта в drawer'е не найден — **один** хоп в «Настройки» (tap по settings-row → re-dump под шагом `tt_3_open_list_settings` → повторный поиск якоря аккаунта уже на странице настроек). Глубина вложенности ограничена 1 уровнем — без рекурсии.
- Существующий блок tap-and-verify (`_has_tt_bottomsheet_signature` дискриминатор) переиспользован без изменений через переприсваивание `drawer_anchor`.
- Неверное предположение о layout'е падает мягко — та же ошибка `tt_account_menu_unknown_layout`, но с payload'ом `settings_labels[]` для следующей итерации.
- Маппер `_SWITCHER_STEP_TO_CATEGORY` и callsite `_TT_ERR_TO_STEP` не трогали: код ошибки тот же, `tt_3_open_list_settings` — только artifact-шаг для `_save_dump`, в `_fail` не передаётся.

**Коммиты ветки** (`fix/tt-account-switcher-settings-nested`):

| Commit | Тема |
|---|---|
| `263f87c` | `TT_DRAWER_SETTINGS_TRIGGERS` + `triggers` param на drawer anchor finder |
| `89e601b` | settings-nested fallback в `_open_tt_account_switcher` |

## Качество

- `tests/test_tt_account_switcher_open.py`: **55 passed** (48 baseline + 7 новых/изменённых). Новые тесты: 3× на `triggers`-param/константу, happy-path settings-hop, settings-hop-still-unknown (`settings_labels[]` enrichment), one-hop-only (recursion cap). Изменён `test_open_tt_account_switcher_unknown_layout` (его drawer использовал `text='Settings'`, теперь матчился бы новой константой).
- Шире: 346 passed; 2 фейла (`test_publish_guard::test_guard_skipped_when_tiktok_seeded_but_tiktok_column_null`, `test_switcher_read_only::test_yt_happy_path_returns_accounts`) — **pre-existing на `origin/main` (f21ee7b)**, не связаны с правкой (подтверждено прогоном на prod-чекауте).
- Codex review плана: 0 P1/P2 (1 раунд). Codex review диффа: "No discrete correctness issue".
- `py_compile` чисто (pyflakes недоступен в env; import-path покрыт 346 проходящими тестами).

## Известное допущение (smoke-gated)

Дамп самой страницы настроек TikTok не снимали — упавшие задачи останавливаются на drawer'е. Структура страницы («Управление аккаунтами» на 1 уровень под «Настройки и конфиденциальность») выведена из iter#2-диагноза. `TT_DRAWER_ACCOUNT_TRIGGERS` широкий (7 RU/EN-вариантов), падение graceful — неверное предположение даёт ту же `tt_account_menu_unknown_layout` с `settings_labels[]` payload'ом → iter#3 из этого evidence. Финальная проверка — прод-смоук (как и Pattern B iter#1).

## Live verify

**Smoke kickoff:** `publish_queue` id `2869` (`clickpay_go`, бывш. task 5732) перевыложен — `UPDATE publish_queue SET status='pending', publish_task_id=NULL`. `dispatchPublishQueue` (5-мин cron) создаст новый `publish_task`.

**Ожидаемо:** в событиях нового `publish_task` — `account_switch` с дампом под `tt_3_open_list_settings`, settings-хоп, затем либо `tt_menu_path_opened_bottomsheet` (успех), либо `tt_account_menu_unknown_layout` с заполненным `settings_labels[]` (→ iter#3).

**24h soak (deadline ~2026-05-15 10:00 UTC):** `tt_account_menu_unknown_layout` падает с 13/24ч к ~0; новых спайков error-кодов нет. Запрос — в `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` § "24h soak SQL".

## Что осталось

- [ ] Дождаться smoke-результата по queue_id 2869 — дописать сюда.
- [ ] 24h soak проверка.
- [ ] Если smoke вернёт `settings_labels[]` без успеха — iter#3 из этого payload'а.
- Runner-up из триажа `tt_post_switch_verify_unrecoverable` (~12/день) — в backlog, отдельной задачей.
