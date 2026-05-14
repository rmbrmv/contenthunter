# TikTok publish failures — триаж за 2026-05-14

**Когда:** 2026-05-14, выборка `updated_at::date = '2026-05-14'`, `testbench = false`.
**Снимок сделан в:** ~10:40 UTC (день ещё не закрыт — числа неполные, но картина уже однозначная).
**Ветка:** `tt-publish-triage-2026-05-14` (изоляция от параллельных сессий).

## Масштаб

| platform | done | failed | awaiting_url | fail-rate |
|---|---|---|---|---|
| TikTok | 9 | **45** | 3 | **~79%** |
| Instagram | 25 | 17 | 14 | — |
| YouTube | 40 | 8 | 3 (+2 running, 3 pending) | — |

TikTok — худшая платформа дня: 45 упавших задач против 9 успешных.

## Набор ошибок с количеством

Считал двумя способами: по полю `error_code` и по `meta.category` последнего `error`-события
(поле `error_code` врёт — пишет первую ошибку, часто preflight; ось истины — последнее
categorized error-событие). Плюс снял маскировку двух известных багов мэппера (см. ниже).

| # | Ошибка | Кол-во | Стадия | Комментарий |
|---|---|---|---|---|
| 1 | **`tt_account_menu_unknown_layout`** | **13** | switcher: `tt_3_open_list_drawer` | TikTok убрал вход в переключатель аккаунтов из меню профиля. **Выбрано для фикса.** |
| 2 | `tt_post_switch_verify_unrecoverable` | 12 | switcher: `tt_4_target_profile[_renav]` | 9 прямых + 1 замаскирован под `screencast_pull_failed` (task 5669) + 2 замаскированы под `switch_failed_unspecified` (5593, 5620 — retry-suffix gap мэппера) |
| 3 | `tt_upload_confirmation_timeout` | 6 | publish: `wait_upload` | Свитч прошёл, видео залилось, экран подтверждения не задетектился в таймаут |
| 4 | `tt_profile_tab_broken` | 4 | switcher: `tt_2_not_own_profile` | Не смогли подтвердить, что стоим на своём профиле до открытия списка |
| 5 | `tt_account_sheet_closed_before_parse` | 2 | switcher: `tt_3_open_list` | Исходный симптом Pattern B; было 19/24ч до PR #52 — Pattern B сработал |
| 6 | `tt_account_not_in_list` | 2 | switcher: `tt_3_pick_account` | Лист открылся и распарсился, целевого аккаунта нет (похоже на data-issue) |
| 7 | `tt_fg_drift_unrecoverable` | 2 | switcher | TT потерял foreground во время свитча, recovery не помог |
| 8 | bottomsheet не открылся после post-switch | 2 | switcher (retry path) | 5726, 5731 — замаскированы под `switch_failed_unspecified` |
| 9 | `tt_app_not_foregrounded` | 1 | switcher | task 5730 |
| 10 | `adb_device_not_ready` | 1 | preflight | task 5664 — устройство `RFGYB07YP7H` в статусе `unauthorized` (инфра, не код) |

**Итого 45.** ~37 из 45 (≈82%) — это падения на стадии переключения аккаунта TikTok.
Два бакета доминируют и оба switcher-стадия: `tt_account_menu_unknown_layout` (13) и
`tt_post_switch_verify_unrecoverable` (12).

### Замечание про маскировку (наблюдаемость)

- **retry-suffix gap мэппера** (известный backlog): шаги вида `tt_4_target_profile_retry_1`
  не матчатся в `_SWITCHER_STEP_TO_CATEGORY`, мэппер падает в fallback →
  `switch_failed_unspecified` / `publish_failed_generic`. 2 из 4 таких задач (5593, 5620) —
  на деле `tt_post_switch_verify_unrecoverable`.
- **`screencast_pull_failed` как последнее error-событие** (task 5669): pull скринкаста
  падает уже на cleanup, ПОСЛЕ реального фейла. `error_code` у задачи —
  `tt_post_switch_verify_unrecoverable`. Группировка строго по «последнему error-событию»
  без этой поправки врёт.

## Выбранный для фикса баг: `tt_account_menu_unknown_layout` (13 задач)

### Почему именно он

- Самый большой одиночный **подтверждённый** root cause (13, против 12 у post_switch_verify,
  который ещё и более размытый — «unknown header» детект, уже 2 PR #34/#39, длинный хвост).
- **Детерминированный**: один и тот же layout на всех 13 задачах, не флака.
- **Уже продиагностирован**: iter#2 design расписан в `docs/evidence/2026-05-13-tt-pattern-b-shipped.md`.
- **Растёт**: завязан на версию TikTok — будет расползаться по мере обновления приложения на устройствах.
- Превышает порог приёмки 24h-soak Pattern B в **4 раза** (порог ≤3/24ч, факт 13).

### Root cause (подтверждён 5 источниками)

TikTok в новой версии приложения **убрал вход в переключатель аккаунтов из меню профиля
(drawer)**. Раньше переключатель открывался из drawer'а по якорям `TT_DRAWER_ACCOUNT_TRIGGERS`
(«Управление аккаунтами» / «Переключить аккаунт» / «+ Добавить аккаунт»). Теперь drawer
содержит только: Баланс, Центр активности, Видео офлайн, Ваш QR-код, Инструменты для бизнеса,
TikTok Studio, **Настройки и конфиденциальность**. Вход в переключатель аккаунтов
переехал **на уровень глубже** — внутрь «Настройки и конфиденциальность» → «Управление аккаунтами».

Оркестратор `_open_tt_account_switcher` (Pattern B, PR #52) проходит весь новый путь
(probe → Stories detect → BACK → «Меню профиля» → drawer), ищет в drawer'е якорь
`_find_tt_account_switcher_anchor_in_drawer` → **не находит** → fail-fast с payload `drawer_labels[]`.
Это и есть «acceptable first-iteration outcome», описанный в evidence-доке Pattern B.

### Доказательства

**1. Распределение `error_code` — 13/45, крупнейший бакет (совпадает с группировкой по последнему error-событию).**

**2. `drawer_labels[]` идентичен на всех просмотренных задачах** (5588, 5660, 5722, 5732):
```json
["0","Лайки","Понравившиеся видео","Лайк","Поделиться","Меню профиля","Профиль",
 "Ресурсы","Баланс","Личные инструменты","Центр активности","Время","Видео офлайн",
 "Скачать","Ваш QR-код","Инструменты для творчества и бизнеса","Инструменты для бизнеса",
 "Магазин","TikTok Studio","Инструменты автора","Настройки и конфиденциальность","Настройки"]
```
Ни одной строки из `TT_DRAWER_ACCOUNT_TRIGGERS`. Совпадает с iter#2-диагнозом из evidence Pattern B.

**3. UI-dump drawer'а** (`task5722_..._tt_3_open_list_drawer_1778752296.xml`): нода
«Настройки и конфиденциальность» — кликабельный контейнер `[201,1254][1041,1444]`
(`clickable=true`); «Управление аккаунтами» в drawer'е **отсутствует** (вложено глубже).

**4. Скринкаст** (`task5722_fail_screenrec_5722_1778752156.mp4`, кадры на 125с/135с/142с):
видно открытый профиль `click_and_pay` → открытый drawer профиля → внизу drawer'а
«Настройки и конфиденциальность», никакого пункта про аккаунты. Кадр статичен — свитчер
просто стоит с открытым drawer'ом и фейлится.

**5. Blast radius:** 10 разных устройств, raspberry 5/7/9. Не device-specific — версия TikTok.
Успешные TT-задачи дня (9 done) — на других устройствах (raspberry 2/3/5/10), где,
вероятно, ещё старая версия TT и старый путь probe срабатывает.

### Затронутые задачи

`5588, 5589, 5590, 5591, 5633, 5637, 5642, 5652, 5657, 5660, 5722, 5729, 5732`
(аккаунты: преимущественно `clickpay_*` + `click_and_pay`, плюс `expertcontentlab`, `lead_content_`).

### Предлагаемый фикс (iter#2, из evidence Pattern B)

Добавить в оркестратор `_open_tt_account_switcher` settings-nested путь: если
`_find_tt_account_switcher_anchor_in_drawer` вернул `None` — fallback-поиск по
`['настройки и конфиденциальность','настройки','settings and privacy','settings']` →
tap по кликабельному контейнеру → re-dump → повторный `_find_tt_account_switcher_anchor_in_drawer`
уже на странице настроек (искать «Управление аккаунтами» / «Аккаунт» / «Переключить аккаунт»).
Вложенность ограничить 1 уровнем (защита от рекурсии). Сохранять dump под стабильным шагом
(`tt_3_open_list_settings`). Реализация — отдельной сессией по design в evidence Pattern B.

## Runner-up (в backlog, не в этот фикс)

- **`tt_post_switch_verify_unrecoverable` (~12)** — `tt_4_target_profile`: свитч аккаунт
  выбрал, но post-switch верификация профиля («unknown header» / «no profile after renav»)
  не подтверждает приземление. Уже 2 PR (#34 renav, #39 bool-return) — рецидив, нужен
  отдельный заход. Частично переплетён с observability-багом мэппера.
- **retry-suffix gap мэппера** — `_SWITCHER_STEP_TO_CATEGORY` не матчит шаги с суффиксом
  `_retry_N` → реальная категория теряется в `switch_failed_unspecified`. Уже в backlog
  (commit `f216a08cc`). Чинить вместе с наблюдаемостью switcher'а.

## Запросы (воспроизводимость)

```sql
-- распределение по платформам/статусам за день
SELECT platform, status, count(*) FROM publish_tasks
WHERE updated_at::date='2026-05-14' AND testbench=false
GROUP BY platform, status ORDER BY platform, count(*) DESC;

-- последнее categorized error-событие на каждую упавшую TT-задачу
WITH ev AS (
  SELECT pt.id, e.value->>'type' AS etype,
         e.value->'meta'->>'category' AS cat, e.ord
  FROM publish_tasks pt,
       LATERAL jsonb_array_elements(pt.events) WITH ORDINALITY e(value,ord)
  WHERE pt.platform='TikTok' AND pt.status='failed'
    AND pt.updated_at::date='2026-05-14' AND pt.testbench=false
),
last_err AS (
  SELECT DISTINCT ON (id) id, cat FROM ev WHERE etype='error'
  ORDER BY id, ord DESC
)
SELECT cat, count(*) FROM last_err GROUP BY cat ORDER BY 2 DESC;
```
