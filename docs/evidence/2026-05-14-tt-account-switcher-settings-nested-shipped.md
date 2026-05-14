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

**Smoke kickoff:** `publish_queue` id `2869` (`clickpay_go`, бывш. task 5732) перевыложен. `dispatchPublishQueue` создал task `5796` (started 12:33 UTC).

**Smoke результат (task 5796, `failed`, 12:40 UTC) — settings-хоп подтверждён, найден iter#3:**

События прошли по новому пути: `tt_3_open_list_probe` → `tt_3_open_list_back` → `tt_3_open_list_menu` → `tt_3_open_list_drawer` → **`tt_3_open_list_settings`** (settings-хоп отработал, дамп сохранён) → `tt_account_menu_unknown_layout`.

`settings_labels[]` payload (settings-хоп **приземлился на правильную страницу настроек**):
```json
["Вернуться к предыдущему экрану", "Настройки и конфиденциальность Настройки",
 "Предпочитаемый контент", "Время и благополучие", "Семейные настройки",
 "Аккаунт Аккаунт", "Аккаунт", "Конфиденциальность", "Безопасность и разрешения",
 "Поделиться профилем", "Контент и отображение Контент и отображе", "Уведомления", "ЭФИР"]
```

**Диагноз iter#3:** на странице настроек строка аккаунтов есть — `«Аккаунт»` (единственное число) — но `TT_DRAWER_ACCOUNT_TRIGGERS` содержит только `аккаунты` / `управление аккаунтами` / `accounts`. `'аккаунты' in 'аккаунт'` → False. Singular `'аккаунт'` не триггер.

**iter#3 (одна строка):** добавить `'аккаунт'` (singular) в `TT_DRAWER_ACCOUNT_TRIGGERS` (в конец, после `accounts` — он подстрока более специфичных, поэтому priority-порядок сохраняется). Закрывает цепочку drawer → Настройки → Аккаунт → switcher. Механизм settings-хопа verified на живом устройстве, graceful-failure отработал точно по дизайну.

**iter#3 SHIPPED:** PR #58 (`0c8518f`) — `'аккаунт'` (singular) добавлен в `TT_DRAWER_ACCOUNT_TRIGGERS` + codex-P2 fix (исключение `«+ Добавить аккаунт»` из anchor-поиска через `_TT_ADD_ACCOUNT_RE`). 60 tests green. Prod deployed (PM2 autowarm restart).

**Smoke iter#3 (task 5853, `clickpay_me`, `failed` 13:13 UTC) — settings-хоп снова отработал, но finder опять None. Реальный XML дал точную причину:**

Скачан `tt_3_open_list_settings` dump (task 5853). Структура страницы настроек:
```
View click=true [23,868][1057,1032]          ← строка-кнопка «Семейные настройки»
TextView text='Аккаунт' desc='Аккаунт' click=false [46,1032][286,1148]  ← СИРОТА в зазоре между строками
View click=true [23,1148][1057,1312]         ← настоящая строка-кнопка «Аккаунт»
  TextView text='Аккаунт' click=false [165,1210][348,1267]   ← её метка (center внутри контейнера)
```

**Root cause iter#4:** `_find_tt_account_switcher_anchor_in_drawer` Pass 2 берёт **первое** совпадение по тексту и коммитится на него. Первая «Аккаунт» — сирота в зазоре `[46,1032][286,1148]` (center y=1090), вокруг неё нет кликабельного контейнера (`[...,1032]` и `[1148,...]` её не покрывают) → `best=None` → Pass 2 идёт к следующему триггеру, **не пробуя вторую «Аккаунт»** внутри настоящего кликабельного `[23,1148][1057,1312]`.

**iter#4 fix:** Pass 2 должен перебирать **все** элементы, совпавшие с триггером, и для каждого пробовать найти кликабельный контейнер — возвращать первую пару (text_el, container), которая срабатывает. Общее улучшение, не костыль. Проверяется против реального XML (`/tmp/tt5853_settings.xml`) ДО деплоя — больше не вслепую.

**24h soak:** актуально после iter#4.

## Что осталось

- [x] Smoke iter#2 (task 5796) — settings-хоп работает, iter#3 найден.
- [x] iter#3 SHIPPED (PR #58) — singular `'аккаунт'` + codex-P2 add-account exclusion.
- [x] Smoke iter#3 (task 5853) — settings-хоп работает, iter#4 root cause найден по реальному XML.
- [ ] **iter#4** — Pass 2 перебирает все text-совпадения, не только первое. Verify против `/tmp/tt5853_settings.xml` до деплоя.
- [ ] 24h soak после iter#4.
- Runner-up из триажа `tt_post_switch_verify_unrecoverable` (~12/день) — в backlog, отдельной задачей.
