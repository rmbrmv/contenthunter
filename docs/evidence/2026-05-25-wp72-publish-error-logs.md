# WP #72 — Evidence: триаж логов выкладки (Эль-косметик + Онлайн-школа)

- **Дата анализа:** 2026-05-25
- **Ветка:** `wp72-publish-error-logs`
- **План:** `docs/superpowers/plans/2026-05-25-wp72-publish-error-logs.md`
- **Спека:** `docs/superpowers/specs/2026-05-25-wp72-publish-error-logs-design.md`
- **БД:** `psql -h localhost -U openclaw -d openclaw` (localhost dev)
- **Тип:** чистый анализ данных. Код не менялся, re-queue не делался, WP не создавались.

---

## 0. Окна и NOISE-BLOCKLIST (Task 1)

**Окна (per-client):**
- Эль-косметик (82): `created_at >= '2026-05-15'`.
- Онлайн-школа Anecole (84): `created_at >= '2026-04-15' AND created_at < '2026-05-07'`.

**Финальная причинная категория** = последняя `events[].meta.category` (type='error'), исключая noise;
fallback на очищенный `error_code`, иначе `uncategorized`. LEFT JOIN `publish_tasks` (NULL-task строки сохранены).

**NOISE-BLOCKLIST (финал):**
1. `adb_devices_unreachable` — preflight/сетевой шум.
2. `process_interrupted` — PM2 deploy-kill, не баг.
3. `screencast_stop_failed` — cleanup-ошибка ПОСЛЕ фейла, не причина.
4. `yt_accounts_btn_missing_postmortem` — **добавлено 25.05.** Postmortem-аннотация к `yt_accounts_btn_missing`.
   Проверено на tasks 1320/1325: событие всегда идёт ПЕРЕД реальным `yt_accounts_btn_missing`
   (ord 45<48, 47<50), т.е. не самостоятельная причина. Без блокировки одна и та же поломка
   двоилась бы на две категории.

Список применён ЕДИНЫМ во всех запросах (Task 2/4/6) — и в `NOT IN (...)`, и в `NULLIF(...)` fallback'е.

**Landscape категорий (Task 1 Step 2, до классификации, по числу тасков с событием):**
```
tt_target_on_device 11 | tt_profile_tab_broken 8 | yt_editor_not_reached 7 | ig_editor_timeout 6 |
critical_exception 6 | ig_camera_open_failed 4 | screencast_stop_failed 4 (NOISE) | ig_app_launch_failed 4 |
yt_editor_upload_timeout 3 | yt_accounts_btn_missing 2 | yt_accounts_btn_missing_postmortem 2 (NOISE) |
ig_upload_confirmation_timeout 2 | tt_target_not_logged_in 1 | tt_account_sheet_closed_before_parse 1 |
ig_reels_tab_not_found 1
```

---

## 1. Контрольные суммы (Task 1 Step 1 + Task 2 Step 2) — СОШЛОСЬ

| project_id | failed | done | cancelled | skipped | pending | total |
|---|---|---|---|---|---|---|
| 82 (Эль) | **18** | 35 | 28 | 0 | 9 | 90 |
| 84 (Школа) | **67** | 44 | 0 | 1 | 0 | 112 |

Σ по категориям (Task 2) == failed total (Task 1) для каждого клиента:
- Эль: 7+3+3+2+1+1+1 = **18 == 18** ✓
- Школа: 15+11+7+7+6+5+4+4+2+1+1+1+1+1+1 = **67 == 67** ✓

Потерянных строк нет. Заметка: «108 failed» из спеки — это ~40 дней; в окне (≥15.05) у Эль только 18.

---

## 2. Таблица категорий (клиент × платформа × финальная_категория × кол-во) (Task 2)

| project | platform | category | n |
|---|---|---|---|
| 82 | YouTube | yt_editor_not_reached | 7 |
| 82 | Instagram | ig_app_launch_failed | 3 |
| 82 | YouTube | yt_editor_upload_timeout | 3 |
| 82 | youtube* | uncategorized | 2 |
| 82 | TikTok | tt_profile_tab_broken | 1 |
| 82 | Instagram | ig_upload_confirmation_timeout | 1 |
| 82 | Instagram | ig_editor_timeout | 1 |
| 84 | Instagram | uncategorized | 15 |
| 84 | TikTok | tt_target_not_on_device | 11 |
| 84 | TikTok | tt_profile_tab_broken | 7 |
| 84 | TikTok | uncategorized | 7 |
| 84 | YouTube | uncategorized | 6 |
| 84 | Instagram | ig_editor_timeout | 5 |
| 84 | Instagram | ig_camera_open_failed | 4 |
| 84 | Instagram | critical_exception | 4 |
| 84 | YouTube | yt_accounts_btn_missing | 2 |
| 84 | TikTok | tt_target_not_logged_in | 1 |
| 84 | TikTok | tt_account_sheet_closed_before_parse | 1 |
| 84 | TikTok | critical_exception | 1 |
| 84 | YouTube | critical_exception | 1 |
| 84 | Instagram | ig_upload_confirmation_timeout | 1 |
| 84 | Instagram | ig_app_launch_failed | 1 |

\* `82|youtube|uncategorized|2` — строки `publish_task_id IS NULL` (qid 3986, 4199), `skip_reason='retry_clean_slate_20260522'`.
Это НЕ публикационный фейл, а ручная retry-уборка 22.05. LEFT JOIN их сохранил (см. §6).

---

## 3. Концентрация по аккаунтам и устройствам (Task 3)

### Аккаунты, >50% фейлов при ≥4 попытках
| project | account | failed | total | % |
|---|---|---|---|---|
| 82 | elcosmetics | 4 | 6 | 67 |
| 82 | elcosmo_beauty | 3 | 5 | 60 |
| 82 | ell-cosmo | 3 | 5 | 60 |
| 84 | aneco_le | 16 | 16 | **100** |
| 84 | aneco.le_edu | 12 | 16 | 75 |
| 84 | anecole | 8 | 10 | 80 |
| 84 | 89venlshfzm | 6 | 6 | **100** |

Школа: жёсткая концентрация. `aneco_le` 16/16 и `89venlshfzm` 6/6 — 100% фейл.
`89venlshfzm` и `memorialcarede` (3/0) — имена не похожи на anecole → подозрение на чужие/не те аккаунты на устройстве.
Эль: умеренно, ни одного 100%-fail аккаунта; `el_cosmetics7` 0/12 и `ell.cosmetics` 0/6 — здоровы.

### Устройства, >50% фейлов при ≥4 попытках
| project | raspberry | device_serial | failed | total | % |
|---|---|---|---|---|---|
| 84 | 10 | RF8Y80ZT14T | 28 | 38 | 74 |
| 84 | 10 | RF8Y90LBZPJ | 22 | 42 | 52 |
| 84 | 10 | RF8Y90LBX3L | 17 | 31 | 55 |

Школа: **все три телефона на raspberry 10 нездоровы** (52–74% фейлов). Эль ни одного устройства >50% при объёме
(1/RF8Y90LBD1Y 7/18, 2/RF8Y80ZT5JB 6/16, 1/RF8YA09SLQA 3/17 — распределено).

### Динамика по дням
- **Эль:** активность только 18.05 (24 done / 12 failed / 18 cancelled), 19.05 (3 done / 6 failed),
  23.05 (8 done / 0 failed / 10 cancelled — выходной, низкий трафик), 9 pending на 25.05.
  Все фейлы — 18–19.05. Поправка на выходные: 0 failed 23.05 — слабый сигнал, не «починено».
- **Школа:** непрерывно 15.04 → 06.05, далее ТИШИНА. Последний failed — 06.05 (4 fail / 5 done).

---

## 4. Сверка с релизами 18–22.05 (Task 4)

Git-лог `/root/.openclaw/workspace-genri/autowarm` (read-only). Сопоставление даты фейла с датой фикса:

| Категория | Фикс (commit / дата / WP) | Фейлы Эль | Фейлы Школы | Вывод |
|---|---|---|---|---|
| `yt_editor_not_reached` | `de02f17` 20.05 / #113 | 18.05 (5), 19.05 (2) — всё ДО фикса | — | **закрыто, рецидивов нет** (будних фейлов после 20.05 нет) |
| `yt_editor_upload_timeout` | `0c01f7e`/`50f1cce` 18.05 / #117 | 18.05 (3) — день базового фикса | — | **есть WP #117** (рецидив, переоткрыт 25.05). Не дублировать. |
| `ig_app_launch_failed` | `862ce81` 22.05 / #105 R2 | 18.05 (3) — ДО фикса | 06.05 (1) | **закрыто** у Эль; школа — пре-фикс, проверить нельзя |
| `tt_profile_tab_broken` | `b7b653c` 19.05 / #106 (+#131 backlog) | 19.05 (1) — день фикса | 03.05 (3),04.05 (3),05.05 (1) — пре-фикс | **закрыто** (#106); остаточный сигнал #131 |
| `ig_upload_confirmation_timeout` | #129 22.05 (wait_upload fg-guard) | 19.05 (1) — ДО фикса | 25.04 (1) | **закрыто** (#129); низкий объём |
| `ig_editor_timeout` | смежно #129 22.05 | 19.05 (1) | 25.04(1),29.04(2),04.05(1),05.05(1) | низкий объём; Эль 1 ДО #129, школа пре-фикс |
| `yt_accounts_btn_missing` | #66 / Готово | — | пре-06.05 (2) | **закрыто** (#66); школа пре-фикс |
| `tt_account_sheet_closed_before_parse` | #112 20.05 / Готово | — | пре-06.05 (1) | **закрыто** (#112) |

**Важно про школу:** все фейлы школы — до 06.05, т.е. до релизов 18–22.05. Для школы «починено» подтвердить НЕЛЬЗЯ
(нет трафика после фикса). Формулировка: «категория чинилась релизом, но на этом клиенте проверить нечем».

---

## 5. Расследование остановки Онлайн-школы 06.05 (Task 5)

**Факты:**
1. `publish_queue` project_id=84: `max(created_at) = 2026-05-06 01:54:08`. `max(updated_at)=2026-05-21`
   (поздний апдейт — смена статуса, не новая активность). Очередь молчит с 06.05.
2. Глобальный наполнитель очереди ЗДОРОВ: другие проекты (106, 80, 112, 82, 102, 65, 85, 53...) получали
   строки очереди вплоть до 25.05. Это НЕ общий сбой.
3. `validator_projects` id=84: `active=t`, `manual_publish=f`, `onboarding_stage=5`. Конфиг идентичен активной
   Эль (id=82) — проект НЕ отключали вручную, не на онбординге, contract-поля NULL у обоих.
4. Расписание школы продолжает наполняться: слоты `status='filled'` с `content_id` существуют на даты ПОСЛЕ 06.05 —
   07,08,09,10,12,13,14.05; 18–22.05; 25–29.05 (content_id до 2149). НО ни один из этих filled-слотов не превратился
   в строку очереди. `planned_time`/`matched_at` у них NULL (но это норма — у Эль тоже NULL, при этом Эль публикуется).
5. Источник очереди для обоих клиентов — НЕ `validator_unic_content` (у 82 и 84 там 0 строк; оба ведутся
   autowarm-side пакетами). Школа крутится на dev/revision-пакетах
   `rev_onlayn_shkola_anecole_content_hunter_dev3X` (pack_id 282/284/285). Эль на своих пакетах продолжает
   генерить очередь (90 строк ≥15.05), школа — нет (последняя пачка 06.05 01:54).
6. `validator_unic_content` для проекта 84 = **0 строк** — точное совпадение с сигнатурой WP #95
   (uniqualization stall у 14 active projects: 0 validator_unic_content).

**Вывод (одной фразой):** выкладка школы остановилась 06.05 потому, что autowarm-side пайплайн пакетов/уникализации
перестал поставлять контент в очередь для проекта 84 (наполнитель здоров для всех других, конфиг проекта в норме,
слоты продолжают наполняться контентом, но в очередь не попадают; 0 `validator_unic_content`) — это
**операционная/провижн-причина (пакеты/уникализация), а не баг публикатора**. Совпадает с открытой WP #95
(uniqualization stall, Anecole в списке). Вопрос к операторам/Ане, не код-баг публикации.

---

## 6. Vision-находки по спорным категориям (Task 6)

Спорные категории: `uncategorized` (82:2, 84:28) и `critical_exception` (84:6). `switch_failed_unspecified` в данных не встретился.

### `uncategorized`
- **82 (×2)** — NULL-task строки 3986/4199, `skip_reason='retry_clean_slate_20260522'`. Ручная retry-уборка 22.05,
  НЕ публикационный фейл. → корзина «не-баг».
- **84 (×28, всё пре-06.05)** — два под-типа:
  - короткие (`nev`=1 и 4): ранний abort, события без категории/сообщений (апрельская эра логирования).
  - длинные (`nev`=18–104, `error_class='unknown'`): шли долго, кончились watchdog'ом без категории.
  Все сообщения событий пусты — апрельская эра ДО зрелого `meta.category`. Диагностики в логах нет, только vision.
- **Vision (task 434, школа IG, 5 мин записи):** телефон завис в ленте Reels ЧУЖОГО аккаунта `diyor_uz_1`
  (узбекская недвижимость), до экрана публикации/камеры так и не дошёл, watchdog сработал через ~5 мин.
  Классическая потеря foreground / wrong-screen апрельской эры — ровно то, что закрывали майские guard-фиксы
  (foreground guards, app-launch trust, editor-reached verify). Все пре-06.05 и пре-фикс → «школа: чинилось
  релизом, проверить нельзя» (а не новый код-баг).
  (Vision-лимит соблюдён: 1 информативный пример + текстовый разбор события; дальше не углублялся.)

### `critical_exception` (84 ×6)
- Screen_record_url отсутствует — vision невозможен.
- Все 6 — **один день, 28.04**, по IG/TT/YT, по 9 событий каждый, на 6 РАЗНЫХ аккаунтах
  (aneco.le_edu, anecole_education, anecole.online, aneco_le, anecole, memorialcarede).
- Кросс-платформенный, кросс-аккаунтный всплеск generic-исключений за один день = сигнатура
  **инфраструктурного/средового инцидента 28.04** (краш деплоя / проблема хоста-малинки / транзиентный
  runtime), а не per-platform код-баг. Пре-06.05, только школа. → не текущий код-баг.

### `tt_target_not_on_device` (84 ×11) — текстовый разбор
- Концентрация по аккаунтам: `aneco_le` (4), `Ane_cole` (4), `89venlshfzm` (3). Категория буквально означает
  «целевой аккаунт отсутствует на устройстве» → **аккаунт/устройство-провижн** (аккаунт не залогинен на телефоне).
  Имя `89venlshfzm` усиливает гипотезу о чужих/не тех аккаунтах. → корзина «аккаунт-устройство».

---

## 7. Итоговая раскладка по корзинам + дедуп (Task 7)

Всего открытых WP проекта content-hunter (id=3) спагинировано: **103**.

| Категория (клиент) | Корзина | Существующий WP / комментарий |
|---|---|---|
| `yt_editor_not_reached` (82:7) | **уже-починено** | #113 Готово (фикс 20.05); фейлы Эль 18–19.05 пре-фикс, рецидивов нет |
| `yt_editor_upload_timeout` (82:3) | **код-баг-есть-WP** | **#117** В разработке (рецидив, переоткрыт 25.05) — не дублировать |
| `ig_app_launch_failed` (82:3,84:1) | **уже-починено** | #105 Готово (фикс 22.05); Эль пре-фикс, школа пре-фикс |
| `tt_profile_tab_broken` (82:1,84:7) | **код-баг-есть-WP** | #106 Готово + **#131** Бэклог (остаточный 22.05) — не дублировать |
| `ig_upload_confirmation_timeout` (82:1,84:1) | **уже-починено** | #129 Готово (фикс 22.05); низкий объём |
| `ig_editor_timeout` (82:1,84:5) | **уже-починено / низкий объём** | смежно #129; Эль 1 пре-фикс, школа пре-фикс — нового WP не нужно |
| `ig_camera_open_failed` (84:4) | **уже-починено (школа, пре-фикс)** | смежно IG-launch/fg guards #105/#129; school-only пре-06.05 |
| `yt_accounts_btn_missing` (84:2) | **уже-починено** | #66 Готово; школа пре-фикс |
| `tt_account_sheet_closed_before_parse` (84:1) | **уже-починено** | #112 Готово (20.05) |
| `tt_target_not_on_device` (84:11) | **аккаунт-устройство** | не код. Аккаунты aneco_le/Ane_cole/89venlshfzm не залогинены/не те. См. ops #100/#101 |
| `tt_target_not_logged_in` (84:1) | **аккаунт-устройство** | не код |
| `critical_exception` (84:6) | **не-баг (инфра-инцидент 28.04)** | разовый кросс-платформенный всплеск 28.04, пре-06.05 |
| `uncategorized` 84 (×28) | **уже-починено (школа, пре-фикс, стейл-лог)** | апрельская эра wrong-screen/lost-foreground; покрыто майскими guard-фиксами |
| `uncategorized` 82 (×2) | **не-баг** | retry_clean_slate_20260522 (ручная уборка), не публикационный фейл |

**Остановка школы 06.05** → отдельная корзина: операционная/провижн (autowarm пакеты/уникализация),
сигнатура совпадает с **WP #95** (uniqualization stall). Не код-баг публикатора.

**Корзина «код-баг-новый»:** ПУСТА. Все код-сигнатуры в данных либо уже починены релизами 18–22.05,
либо имеют открытый WP (#117, #131), либо относятся к аккаунтам/устройствам, либо к остановке школы (#95),
либо к стейл-логам апрельской эры. Новых дочерних WP заводить НЕ требуется.

---

## Приложение: ключевые SQL

Все запросы выполнялись с `export PGPASSWORD=…; psql -h localhost -U openclaw -d openclaw`.
Полные тексты — в плане (Task 1–6). Финальный noise-blocklist (4 элемента) применён ЕДИНЫМ
в `NOT IN(...)` и в `NULLIF(...)` во всех классификационных запросах.
