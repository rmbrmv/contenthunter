# TT publish fails — triage 2026-05-15

## Window

`publish_tasks` где `platform='TikTok'`, `status='failed'`, `updated_at >= 2026-05-15 00:00 UTC` (т. е. за сегодня UTC).

DB clock на момент анализа: `2026-05-15 15:42 UTC`.

## Распределение по последней error-категории

| Категория (последний `events[].meta.category` с `type=error`) | Кол-во | Комментарий |
|---|---:|---|
| `adb_devices_unreachable` | 166 | **Игнорируем** — сетевая проблема VPS↔proxy, по словам пользователя уже починена. Сигнатура: watchdog_fired на `adb preflight` + ADB devices unreachable на 82.115.54.26:150xx (15-секундный таймаут). |
| **`tt_upload_confirmation_timeout`** | **3** | **Top non-network.** Tasks 6512, 6510, 6495. |
| `tt_account_sheet_closed_before_parse` | 2 | Tasks 6529, 6522. По msg: «target ... не добавлен», т. е. целевой аккаунт не залогинен на устройстве — **данные/онбординг**, не баг кода. |
| `tt_profile_tab_broken` | 2 | Tasks 6511, 6509. Не разбирали глубоко в этой итерации. |
| `tt_post_switch_verify_unrecoverable` | 1 | Task 6514. Recovery исчерпался после `tt_post_switch_handle_unknown`. |
| _(нет error-event, `error_code` пуст)_ | 1 | Task 5202 — но в events видим тот же `ai_find_tap_no_coords` для кнопки Publish, что и в Top-категории. Скорее всего тот же баг, просто закрылся через другую ветку. |

Итого failed без сетевых = **9 задач**. Если приклеить task 5202 к top-категории по сигнатуре (vision не нашёл Publish), получаем **4/9 ≈ 44% non-network падений = одна корневая причина**.

## Top-1 root cause (для фикса)

**`tt_upload_confirmation_timeout` → AI vision не находит кнопку Publish/Опубликовать/Поделиться, потому что приложение зависает на новом TT-экране «Коммерческие треки → TikBiz playlist»**

### Сигнатура (одинаковая для всех 3 task'ов 6495 / 6510 / 6512)

Хронология из `events`:
1. `tt_foreground_recovery` (norm: фокус ушёл с TT в launcher → восстановили)
2. `tt_post_switch_handle_unknown` + `tt_post_switch_feed_after_pick` (post-switch verify не подтвердил @handle, но flow продолжен)
3. `ai_find_tap_no_coords` с `desc='the Publish/Post/Опубликовать/Поделиться button in TikTok vi'` → `resp='{"x": null, "y": null}'` — vision возвращает null для Publish-кнопки
4. Ждём 3 минуты подтверждения upload
5. `tt_upload_confirmation_timeout` + `Публикация завершилась с ошибкой` (step=`wait_upload`)

### Что показывает screencast (verified visually на task 6512)

Кадры — все 8 равномерно через ~90s в записи длиной 12 мин:

| Момент | Экран |
|---|---|
| ~17:55 | Профиль `@axilor_prive` в TT (post-switch ОК) |
| ~17:57 | Открылся модал **«Коммерческие треки»** (commercial music selector) с табами «Интересное / Избранное», баннером "casey baer", блоком «Рекомендации» (Beat Automotivo, Creepy Violins, Chill Vibes) и плейлистами «TikTok Viral», **«TikBiz»** и др. |
| ~17:58 | Подплейлист **TikBiz** открыт. Треки: PONCHET, Yang Salah, Main Sadqay Ya Rasool Allah, Beat Automotivo Tan Tan Ta..., **Happy / Vide...** (с pause-иконкой и розовым ✓ — кто-то/что-то тапнуло «выбрать»), Countless, Cooking Time, GodKKilla, Jakasoro |
| ~18:00 | Тот же TikBiz, ✓-кнопка пропала — трек либо подтверждён, либо selection state сбросился |
| 18:01-18:04 | **Намертво** на TikBiz playlist 3+ мин до taskout |

### Это **тот же экран** на других 2 task'ах

Скриншоты `t6495_07.jpg` (16:45) и `t6510_07.jpg` (17:52) — **идентичная** TikBiz playlist страница с тем же списком треков. Т.е. это не случайность и не device-state — это воспроизводимое поведение TT для нашего публикационного потока.

### Гипотеза root cause

TT начал принудительно требовать выбор коммерческого трека (Commercial Music Library) для каких-то аккаунтов перед публикацией. Текущий music-rights handler (PR #28 на 2026-05-10 + v12 coverage в PR #32 на 2026-05-11) был на **диалоге согласия на права** — это другой UI. Здесь — **selector** с обязательным выбором.

Publisher:
- открывает modal
- проваливается на подплейлист (вероятно tap по тайтлу/обложке вместо ✓)
- не закрывает модал, не отменяет, не возвращается к composer
- pollит «найди Publish» → vision возвращает null → таймаут 3 мин

### Затронутые задачи (samples для разработчика)

| Task | Account | Project | Phone | Device | Screencast |
|---|---|---|---:|---|---|
| 6512 | axilor_prive | AXILOR Private_43a | 1 | RF8Y80ZTVFZ | `task6512_fail_screenrec_6512_1778849602.mp4` |
| 6510 | axilor_brand | AXILOR Private_44a | 1 | RF8YA09S90H | `task6510_fail_screenrec_6510_1778848987.mp4` |
| 6495 | clickpay_under | ClickPay_153b | 9 | RFGYC31P94Z | `task6495_fail_screenrec_6495_1778844939.mp4` |
| 5202 _(orphan, тот же signature)_ | moon_echo_2 | — | — | — | _(не качал)_ |

Все на `https://save.gengo.io/autowarm/screenrecords/tiktok/<file>`.

## Что НЕ trial'но проверено в этой итерации (для следующей)

- `tt_profile_tab_broken` (2 task'а 6511/6509) — events заканчиваются на самом этом коде; recovery-логика была отгружена ранее (PR #28 для button-bar etc), но что-то пробивается. Скринкасты не смотрел.
- `tt_post_switch_verify_unrecoverable` (1 task 6514) — `tt_post_switch_handle_unknown` без recovery success; ПР #34 (2026-05-11) должен это покрывать, надо проверить почему не сработало.
- `tt_account_sheet_closed_before_parse` (2 task'а 6529/6522) — по msg похоже на data drift (target account не залогинен). Не код.

## SQL для воспроизведения

```sql
-- Top categories with grouping by last error event
WITH errs AS (
  SELECT pt.id, e->>'ts' AS ts, e->'meta'->>'category' AS category
  FROM publish_tasks pt, jsonb_array_elements(pt.events) e
  WHERE pt.platform='TikTok' AND pt.status='failed'
    AND pt.updated_at >= '2026-05-15 00:00:00'
    AND e->>'type'='error'
),
last_err AS (
  SELECT DISTINCT ON (id) id, category
  FROM errs ORDER BY id, ts DESC
)
SELECT COALESCE(category, '(no error event)') AS last_category, count(*)
FROM last_err GROUP BY 1 ORDER BY 2 DESC;
```
