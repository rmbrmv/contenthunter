# TikTok publish failures — триаж за 2026-05-14 (полный день, EOD)

**Когда:** 2026-05-14, выборка `created_at::date = '2026-05-14'`, `platform = 'TikTok'`, `testbench = false`.
**Снимок сделан в:** ~14:45 UTC (день почти закрыт).
**Ветка:** `worktree-tt-publish-triage-2026-05-14` (изоляция от параллельных сессий).
**Связь:** дополняет утренний снимок `docs/evidence/2026-05-14-tt-publish-failures-triage.md` (был сделан в 10:40 UTC, 45 failed) — здесь полный день и фокус на runner-up.
**OpenProject:** заведён WP [#67](https://openproject.contenthunter.ru/work_packages/67) — `tt_post_switch_verify_unrecoverable` (тип «Ошибка»).

## Масштаб

| platform | done | failed | fail-rate |
|---|---|---|---|
| TikTok | 14 | **58** | **~81%** |

TikTok остаётся худшей платформой дня.

## Набор ошибок с количеством

Категоризация — по `fail`-событию (несёт каноничную причину); снята маскировка
мэппера (`publish_failed_generic` от retry-suffix gap) и `screencast_pull_failed`.

| # | Ошибка | Кол-во | Стадия | Статус |
|---|---|---|---|---|
| 1 | `tt_account_menu_unknown_layout` | **17** | switcher: `tt_3_open_list_drawer` | **уже чинится сегодня** — iter#2–#5, PR #57–#60, WP #60 |
| 2 | **`tt_post_switch_verify_unrecoverable`** | **16** | switcher: `tt_4_target_profile[_renav/_retry]` | **не затикечен — выбран для фикса** |
| 3 | `tt_upload_confirmation_timeout` | 7 | publish: `wait_upload` | не затикечен |
| 4 | `tt_profile_tab_broken` (tap «Я» не открыл профиль) | 5 | switcher: `tt_2_not_own_profile` | не затикечен |
| 5 | `tt_account_sheet_closed_before_parse` | 3 | switcher: `tt_3_open_list` | остаточный симптом Pattern B |
| 6 | bottomsheet не открылся после post-switch retry | 3 | switcher: `tt_3_open_list_retry_1` | тот же retry-путь, что #2 |
| 7 | `tt_account_not_in_list` | 2 | switcher: `tt_3_pick_account` | data-issue (аккаунт не привязан к устройству) |
| 8 | `tt_fg_drift_unrecoverable` | 2 | switcher: fg-drift | TT не вышел на foreground |
| 9 | `tt_drawer_tap_did_not_open_sheet` | 1 | switcher: `tt_3_open_list_sheet` | task 5924 — smoke iter#4 серии WP #60 |
| 10 | `tt_app_not_foregrounded` | 1 | switcher: `tt_0_foreground_guard` | task 5730 |
| 11 | `adb_device_not_ready` | 1 | preflight | task 5664 — устройство `unauthorized` (инфра, не код) |

**Итого 58.** ~50 из 58 (≈86%) — падения на стадии переключения аккаунта TikTok.

### Почему топ-1 не выбран

`tt_account_menu_unknown_layout` (17) — крупнейший бакет по сырому счёту, **но он уже
закрывается прямо сегодня**: серия iter#2–iter#5 (PR #57, #58, #59, #60), WP #60,
путь к переключателю device-verified. Из 17 задач часть — это сами smoke-прогоны
итераций (5796, 5853, 5924, 5970-зона). Новый тикет был бы дублем WP #60. Осталась
только 24h-soak проверка.

Поэтому для фикса выбран крупнейший **незатикеченный** баг — `tt_post_switch_verify_unrecoverable`.

## Выбранный для фикса баг: `tt_post_switch_verify_unrecoverable` (16 задач)

### Почему именно он

- Крупнейший **незатикеченный** root cause (16 из 58, ~28% всех падений дня).
- **Детерминированный** — не флака: один и тот же механизм воспроизведён покадрово
  и репликацией кода на 3 независимых задачах.
- **Свитч физически проходит** — это чистый ложноотрицательный verify-гейт. Фикс
  превращает 16 падений/день в успешные публикации без изменения самого свитча.
- **Fleet-wide:** 16 задач, **16 разных устройств**, raspberry 1/2/7/9/10. Не device-specific.
- **Весь день:** 04:50–13:41 UTC, в т.ч. после всех switcher-фиксов серии WP #60.
- Runner-up из утреннего триажа («отдельный баг, отдельной задачей») — пора заводить.

### Root cause (подтверждён репликацией кода на 3 задачах)

После выбора аккаунта в bottomsheet свитчер открывает профиль и сверяет активный
аккаунт через `_post_switch_verify_handle` → `get_current_account_from_profile`
(`account_switcher.py`). Эта функция:

1. собирает все токены в полосе `y_top ≤ header_y_max` (для TikTok `header_y_max=700`),
   которые проходят эвристику `_looks_like_username`;
2. сортирует кандидатов по `y_top` и **возвращает самый верхний**.

Проблема: **`_looks_like_username` слишком широкая**, а на экране профиля TikTok
**имя профиля рендерится ВЫШЕ `@handle`**. Эвристика принимает за username:

- слова из отображаемого имени профиля — `Girl`, `Unpacking`, `Relisme`, `Unpack`
  (латиница, длина ≥4, не stopword);
- **любой токен с цифрой** — включая голые числа вроде `11` (badge/счётчик в топ-баре
  на `y≈164`).

Реальный `@handle` стабильно сидит на `y≈574` — **ниже** имени профиля и ниже
топ-баровых badge'ей. Префикс `@` — надёжный дискриминатор настоящего хэндла, но
функция его стрипает и не использует для приоритета. Итог: verify берёт мусорный
верхний токен → `_post_switch_verify_handle` возвращает `mismatch` (или `unknown`,
если `header_y_max=260`) → свитч трактуется как несостоявшийся → отрабатывает
renav + полный retry → `tt_post_switch_verify_unrecoverable`. Публикация не идёт,
**хотя аккаунт переключён правильно**.

### Доказательства

**1. Репликация `get_current_account_from_profile` на реальных `tt_4_target_profile_renav` дампах** (3 задачи, верный `@handle` присутствует в дампе и в полосе):

| task | target | `@handle` в дампе | имя профиля выше | verify(700) вернул | verify(260) вернул |
|---|---|---|---|---|---|
| 5817 | `relism_e` | `@relism_e` `y=574` | «Unpacking Girl» `y=503` | **`girl`** ❌ | `None` ❌ |
| 5593 | `mariaforsale` | `@mariaforsale` `y=574` | `mariaforsale` `y=503` | **`11`** ❌ (badge на `y=164`) | `11` ❌ |
| 5799 | `relis_unpack` | `@relis_unpack` `y=574` | «Relisme Unpack» `y=503` | **`relisme`** ❌ | `None` ❌ |

Во всех трёх случаях верный хэндл присутствует и в полосе — но возвращается не он.

**2. Скринкаст task 5817** (`task5817_fail_screenrec_5817_1778763391.mp4`):
- кадр ~237с: профиль `@relism_e` отрисован полностью и корректно, вкладка «Профиль»
  активна в нижней навигации — **переключение УДАЛОСЬ**;
- кадры ~260с/280с: на профиле открыта шторка «Сменить аккаунт», у `relism_e` стоит
  **галочка ✓** (это активный аккаунт) — свитч подтверждён самим TikTok'ом.

Свитч прошёл, аккаунт активен — а verify его «не увидел» и сжёг renav + retry.

**3. UI-dump `tt_4_target_profile_renav` task 5817:** нода
`text="@relism_e"` `bounds="[455,574][624,616]"` — настоящий хэндл; нода
`text="Unpacking Girl"` на `y=503` — имя профиля выше неё.

**4. `fail`-событие идентично на всех 16 задачах:**
`tt_post_switch_verify_unrecoverable: unknown header non-feed (target='<account>')`.

### Затронутые задачи (16)

`5584, 5593, 5620, 5621, 5634, 5669, 5699, 5700, 5703, 5713, 5716, 5725, 5799, 5800, 5817, 5960`
(аккаунты: `sale.for19`, `mariaforsale`, `smartestatespb`, `spbpropertyguide`,
`spbluxestate`, `goldenluxaroma`, `mysticluxaroma`, `aromaluxcollection`,
`auraperfumehouse`, `aromaluxspace`, `perfumeluxvibe`, `wellfresh_1`, `relis_unpack`,
`relisme_co`, `relism_e`, `datj2k5`).

### Предлагаемое направление фикса (для отдельной сессии)

`get_current_account_from_profile` должна возвращать настоящий `@handle`, а не верхний
проходящий токен. Варианты (выбрать в design-сессии):

- **Приоритет `@`-префиксных токенов:** на экране профиля TikTok настоящий хэндл идёт
  с `@`. Сначала искать токен, у которого исходный `raw` начинался с `@`; bare-токены —
  только fallback.
- **Ужесточить `_looks_like_username`** или вызывающую логику: отсекать голые числа
  (`11`, badge-счётчики) и токены из multi-word display name.
- Перепроверить против реальных дампов 5817/5593/5799 (`@handle` всегда `y≈574`) **до**
  деплоя — больше не вслепую.

⚠️ Это область рецидивов (PR #34 renav, PR #39 bool-return). Но **этот конкретный RC —
display name / badge затмевает `@handle` в выборе токена — новый** и теми PR не покрыт.

## Runner-up (в backlog, не в этот фикс)

- **`tt_upload_confirmation_timeout` (7)** — свитч прошёл, видео залилось, экран
  подтверждения не задетектился в таймаут. Стадия `wait_upload`, не switcher.
- **bottomsheet не открылся после post-switch retry (3)** — тот же retry-путь, что
  выбранный баг; вероятно закроется вместе с ним или близким фиксом.
- **`tt_profile_tab_broken` (5)** — tap «Я» не открыл профиль на нестандартном UI.
- **retry-suffix gap мэппера** (`_SWITCHER_STEP_TO_CATEGORY` не матчит шаги `_retry_N`)
  — наблюдаемость; уже в backlog.

## Запросы (воспроизводимость)

```sql
-- статусы TT за день
SELECT status, count(*) FROM publish_tasks
WHERE platform='TikTok' AND created_at::date='2026-05-14' AND testbench=false
GROUP BY status;

-- каноничная категоризация по последнему fail-событию
WITH fail_ev AS (
  SELECT pt.id, (e.value->>'msg') AS failmsg, e.ord
  FROM publish_tasks pt,
       LATERAL jsonb_array_elements(pt.events) WITH ORDINALITY AS e(value,ord)
  WHERE pt.platform='TikTok' AND pt.created_at::date='2026-05-14'
    AND pt.status='failed' AND e.value->>'type'='fail'
),
last_fail AS (SELECT DISTINCT ON (id) id, failmsg FROM fail_ev ORDER BY id, ord DESC)
SELECT failmsg LIKE '%tt_post_switch_verify_unrecoverable%' AS is_chosen_bug, count(*)
FROM last_fail GROUP BY 1;
```
