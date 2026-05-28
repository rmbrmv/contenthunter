# TT publish-fails triage — 2026-05-28

**Дата:** 2026-05-28 (МСК ~14:00, окно за полдня)
**Платформа:** TikTok only.
**Метод:** `publish_tasks` (non-testbench) с `(created_at AT TIME ZONE 'Europe/Moscow')::date = '2026-05-28'`. Группировка по `error_code` и по последнему `events[].meta.category` (по правилу [[feedback_publisher_error_code_misleading]] — error_code пишет ПЕРВУЮ ошибку, надёжнее последний meta.category). БД openclaw@172.17.0.3 (Docker).

---

## TL;DR

- TT задач сегодня: **92** (done 55 / failed 23 / published_no_url 5 / pending 4 / awaiting_url 3 / running 2).
- Проблемных = **28** (failed 23 + published_no_url 5).
- Топ-1 по реальному meta.category = **`tt_account_sheet_closed_before_parse` — 5** (18% от проблемных). Это **возврат сигнатуры WP#96**, ранее закрытой 26.05 как resolved-by-environment.
- Тренд 8 дней: 20.05=10, 21.05=1, 22.05=4, **23–26.05=0**, **27.05=5**, **28.05=5**. Регрессия началась 27.05.
- Выбор для фикса: **`tt_account_sheet_closed_before_parse`** — заведён отдельный WP.

---

## Распределение проблемных TT-задач (28 шт.)

### По `error_code` (как пишет publisher — первая ошибка)

| error_code | count | status |
|---|--:|---|
| tt_account_sheet_closed_before_parse | 5 | failed |
| (null) | 5 | published_no_url |
| phone_or_email_link_required | 3 | failed |
| tt_drawer_tap_did_not_open_sheet | 3 | failed |
| tt_post_switch_verify_unrecoverable | 3 | failed |
| tt_upload_confirmation_timeout | 3 | failed |
| tt_account_switcher_wrong_foreground | 2 | failed |
| tt_app_not_foregrounded | 1 | failed |
| switch_failed_unspecified | 1 | failed |
| tt_account_menu_unknown_layout | 1 | failed |
| tt_profile_tab_broken | 1 | failed |

### По последнему `meta.category` (надёжнее)

| last meta.category | count |
|---|--:|
| tt_account_sheet_closed_before_parse | 5 |
| (none — published_no_url) | 4 |
| tt_post_switch_verify_unrecoverable | 3 |
| tt_drawer_tap_did_not_open_sheet | 3 |
| tt_upload_confirmation_timeout | 3 |
| tt_switch_blocked | 3 |
| screencast_stop_failed | 2 |
| tt_fg_drift_unrecoverable | 1 |
| publish_failed_generic | 1 |
| tt_account_menu_unknown_layout | 1 |
| adb_device_not_ready | 1 |
| tt_profile_tab_broken | 1 |

Заметки:
- `phone_or_email_link_required` (3 по error_code) перекрылся в `tt_switch_blocked` (3 по meta) — это account-side requirement, тематика WP#93, не infra-bug.
- `published_no_url` (5) — известный класс [[project_wp86_published_no_url_complete]] (terminal-статус exhausted awaiting_url), не новый баг.
- `screencast_stop_failed` (2) в meta — пост-фейл, маскирующий, не первопричина.

---

## Топ-1: `tt_account_sheet_closed_before_parse` (5)

### Задачи

| id | account | device_serial | created (МСК) | screencast |
|---:|---|---|---|---|
| 11554 | thespbpropertyguide | RF8YA0V5TAH | 07:26 | [save.gengo.io/.../task11554_fail_screenrec_11554_1779954035.mp4](https://save.gengo.io/autowarm/screenrecords/tiktok/task11554_fail_screenrec_11554_1779954035.mp4) |
| 11565 | tkachenko_health2 | RF8Y80ZTGFK | 07:46 | [.../task11565_...](https://save.gengo.io/autowarm/screenrecords/tiktok/task11565_fail_screenrec_11565_1779955721.mp4) |
| 11658 | tkachenko_pro5 | RF8Y80ZTGFK | 10:26 | [.../task11658_...](https://save.gengo.io/autowarm/screenrecords/tiktok/task11658_fail_screenrec_11658_1779965604.mp4) |
| 11668 | clickbriz5y | RFGYC31P26P | 10:41 | [.../task11668_...](https://save.gengo.io/autowarm/screenrecords/tiktok/task11668_fail_screenrec_11668_1779965516.mp4) |
| 11673 | enoty.po.polkam.p | RF8Y80ZTGHZ | 10:46 | [.../task11673_...](https://save.gengo.io/autowarm/screenrecords/tiktok/task11673_fail_screenrec_11673_1779966212.mp4) |

4 разных аккаунта × 3 разных device_serial → не привязано к одному устройству.

### Тренд 8 дней (`testbench=false`, signature в events::text)

| дата | count |
|---|--:|
| 2026-05-20 | 10 |
| 2026-05-21 | 1 |
| 2026-05-22 | 4 |
| 2026-05-23 … 26 | **0** |
| 2026-05-27 | **5** |
| 2026-05-28 | **5** |

→ **Регрессия началась 27.05** (после нулевой полосы 23–26.05).

### Сэмпл логики из `account_switcher.py:4798–4872`

```
Phase 1: probe via _tap_profile_header up to 2 times.
  - tap, dump UI, check signature (anchor || @-handles count ≥2)
  - if signature → success
  - if Stories viewer → BACK + pivot to Phase 2
  - else → emit tt_account_sheet_closed_before_parse
```

### probe_top_labels из meta (что было на экране после probe-тапа)

| id | подсигнатура |
|---:|---|
| 11554 | обычный профиль (`@thespbpropertyguide`) — sheet просто не появился |
| 11565 | **`storyringhas_consumed_story_true`** + "Создать", "Закрыть", "Создайте потрясающий монтаж" → тап ушёл в Stories editor / модалка, но `_detect_tt_stories_viewer` не сработал |
| 11658 | **`storyringhas_consumed_story_true`** + обычные пункты профиля → аналогично 11565 |
| 11668 | `["Поиск"]` — тап увёл в Search tab (foreground всё ещё TikTok, fg-guard не ловит) |
| 11673 | обычный профиль (`@spb.home`) — на устройстве другой аккаунт, sheet не появился |

### Разложение причин (5 задач)

| подкласс | count | гипотеза |
|---|--:|---|
| тап no-op на стабильном profile-screen | 3 (11554, 11658, 11673) | вернулась проблема каретки `▾` из эпохи WP#96 — `@username` button получает тап, но не открывает sheet. Дамп `@spb.home` clickable="true" → реакции нет |
| тап увёл в Stories editor через storyring | 1 (11565)\* | `_detect_tt_stories_viewer` не распознаёт editor-вариант (есть `storyringhas_consumed_story_true` маркер, но детектор ищет viewer) |
| тап увёл в Search tab | 1 (11668) | tap координаты сбились на нижний навбар → Search; fg-guard не помогает (Search всё ещё TikTok package) |

\* 11658 имеет storyring-маркер, но top labels — обычный профиль, не editor. Возможно тап был no-op, а маркер из xml — индикатор был, не действие. Помечаю гипотезу как «3+1+1» с оговоркой.

### Что чинить

WP#96-evidence от 26.05 явно держало «каретка-фикс в кармане на случай возврата TT-UI». Сейчас этот случай. Минимальный план фикса (без TDD-этапа здесь — это решит автор реализации):

1. **probe_top_labels-аналитика** уже даёт сигнатуры — добавить в `_open_tt_account_switcher` детект «каретка/маркер открытия» (символы `▾ ▼ ⌄ ▽` или `@username + clickable arrow icon`) и тап по нему вместо/после username.
2. **storyring 11565** — расширить `_detect_tt_stories_viewer` под маркер editor-flow (`storyringhas_consumed_story_true` + "Создать"/"Создайте").
3. **Search tab 11668** — добавить пост-probe чек: если в dump есть `text="Поиск"` без `text="Профиль"` → fall-fast как `tt_probe_tap_drifted_to_search`, retry с возвратом на profile tab.

### Артефакты

- UI dumps (3 probe-attempts, все MD5-identical 57352B):
  - <https://save.gengo.io/autowarm/ui_dumps/tiktok/task11673_switch_11673_tt_3_open_list_probe_1779966369.xml>
  - <https://save.gengo.io/autowarm/ui_dumps/tiktok/task11673_switch_11673_tt_3_open_list_probe_1779966379.xml>
  - <https://save.gengo.io/autowarm/ui_dumps/tiktok/task11673_switch_11673_tt_3_open_list_probe_retry1_1779966384.xml>
- Скринкаст 11673: см. таблицу выше.

---

## Что НЕ выбрано для фикса (но в бэклоге)

- **`tt_drawer_tap_did_not_open_sheet` (3)** — Phase 2 menu-path не открывает drawer. По меньшему числу и иной природе — заслуживает отдельного WP позже.
- **`tt_post_switch_verify_unrecoverable` (3)** — известный flow WP#67; не новый рецидив.
- **`tt_upload_confirmation_timeout` (3)** — WP#82/#118/#122; продолжающийся длиннохвост.
- **`tt_switch_blocked` / phone_or_email_link_required (3)** — WP#93 account-side requirement.
- **`published_no_url` (5)** — WP#86 COMPLETE, terminal-статус.
- **`screencast_stop_failed` (2)** — пост-фейл маскирующий.

---

## SQL для воспроизведения

```sql
-- Распределение по error_code за день
SELECT status, COALESCE(error_code,'(null)'), count(*)
FROM publish_tasks
WHERE platform='TikTok' AND status IN ('failed','published_no_url')
  AND (created_at AT TIME ZONE 'Europe/Moscow')::date = '2026-05-28'
GROUP BY 1,2 ORDER BY 1,3 DESC;

-- Последний meta.category на ошибочных событиях
WITH errs AS (
  SELECT pt.id,
    (SELECT ev->'meta'->>'category' FROM jsonb_array_elements(pt.events) ev
     WHERE ev->>'type'='error' AND ev->'meta'->>'category' IS NOT NULL
     ORDER BY (ev->>'ts') DESC LIMIT 1) AS last_err_category
  FROM publish_tasks pt
  WHERE platform='TikTok' AND status IN ('failed','published_no_url')
    AND (created_at AT TIME ZONE 'Europe/Moscow')::date = '2026-05-28'
)
SELECT COALESCE(last_err_category,'(none)'), count(*)
FROM errs GROUP BY 1 ORDER BY 2 DESC;

-- Тренд 8 дней
SELECT created_at::date d, count(*) FROM publish_tasks
WHERE platform='TikTok' AND testbench=false
  AND (created_at AT TIME ZONE 'Europe/Moscow')::date >= '2026-05-20'
  AND events::text LIKE '%tt_account_sheet_closed_before_parse%'
GROUP BY 1 ORDER BY 1;
```
