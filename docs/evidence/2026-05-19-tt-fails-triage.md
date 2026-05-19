# TT publish-fails triage — 2026-05-19

Дата сбора: 2026-05-19 10:36 UTC.
Источник: `publish_tasks WHERE platform='TikTok' AND testbench=false AND status='failed' AND created_at >= '2026-05-19'::date`.

## Сводка дня (TikTok)

Всего тасок: 59. По статусу:

| status | count |
|---|---|
| done | 31 |
| failed | 18 |
| running | 5 |
| awaiting_url | 3 |
| pending | 2 |

`failed` за день = 18.

## Распределение причин

Группировка по `publish_tasks.error_code` (для случаев где он надёжен — это последний emitted error_code), плюс перепроверка через последнее `events[].meta.category` (по памяти `error_code` может врать). 1 кейс исключён по указанию (сетевая проблема, уже починена).

| # | error_code | count | excluded | задача-примеры |
|---|---|---|---|---|
| 1 | **tt_profile_tab_broken** | **4** | — | 7827, 7861, 7870, 7884 |
| 2 | tt_account_sheet_closed_before_parse | 3 | — | 7708, 7724, 7749 |
| 3 | tt_account_not_in_list | 2 | — | 7742, 7743 |
| 4 | switch_failed_unspecified | 1 | ✅ (last_cat=adb_device_not_ready, сетевое — фикс уже в проде) | 7712 |
| 5 | tt_app_not_foregrounded | 1 | — | 7776 |
| 6 | tt_fg_drift_unrecoverable | 1 | — | 7855 |
| 7 | tt_post_switch_verify_unrecoverable | 1 | — | 7715 |
| 8 | tt_stories_back_failed | 1 | — | 7718 |
| 9 | tt_upload_confirmation_timeout | 1 | — | 7722 |
| 10 | adb_push_chunked_exception | 1 | — | 7736 |
| 11 | watchdog_subprocess_hang | 1 | — | 7778 |
| 12 | phone_or_email_link_required | 1 | — | 7725 (покрыт WP #93 / PR #75) |

После исключения сетевой: **17 фейлов**, топ-1 = `tt_profile_tab_broken` = **4 (24%)**.

## Topic deep-dive: `tt_profile_tab_broken`

### Семидневная динамика

| день | count |
|---|---|
| 2026-05-19 | 4 |
| 2026-05-18 | 7 |
| 2026-05-17 | 1 |
| 2026-05-16 | 3 |
| 2026-05-15 | 3 |
| 2026-05-14 | 6 |
| 2026-05-13 | 7 |

Итого 31/7д — это устойчивый bleeder, а не однодневный всплеск.

### Симптом

В `account_switcher.py::_switch_tiktok` после `_go_to_profile_tab` цикл из 3 retap (обычный → smart_tap → cold-start). На каждой попытке `dump_ui` → `_tt_is_own_profile(xml_probe)` возвращает False, и после 3 retap эмитится:

```
fail step=tt_2_not_own_profile reason=tap «Я» не открыл свой профиль
   (3 retap, включая smart_tap и cold-start relaunch) —
   возможно UI TikTok на этом устройстве нестандартный
```

### Root cause из UI-дампов

Скачал retap1/2/3 для всех 4 тасок (`/tmp/tt-triage-2026-05-19/`). Все 4 retap1-дампа показывают **modal-диалог TikTok поверх профиля**, а не собственно профиль:

| task | account | устройство | модалка |
|---|---|---|---|
| 7827 | clickpay_app | RFGYA16W2DT | Контакты: «Чтобы связаться в TikTok со своими знакомыми, разрешите приложению доступ к контактам в настройках устройства.» — кнопки «Открыть настройки» / «Не разрешать» |
| 7861 | my_clickpay | RFGYC31P26P | то же (контакты) |
| 7884 | swarovski.health | RF8Y90LASMJ | то же (контакты) |
| 7870 | clickpay_officia | RFGYC31P6TX | Facebook: «Разрешить TikTok доступ к списку ваших друзей в Facebook и почтовому адресу?» — кнопки «OK» / «Не разрешать» |

retap2 и retap3 дампы идентичны retap1 (модалка sticky, переживает cold-start `am force-stop` + relaunch).

Финальный `_publish_*_fail_tt_2_not_own_profile_*.xml` (снят уже после `_fail` возврата) — у всех показывает **полноценный свой профиль** (own-markers: `Меню профиля`, `Создать историю`, `Просмотры профиля`, `Приватные видео`). То есть модалка в момент финального снимка успела самораствориться, но к этому времени switcher уже отказал.

### Почему текущий dismisser не сработал

`_tt_dismiss_security_prompt` (line 2177) вызывается перед `_tt_is_own_profile` (line 2326), но whitelist у него узкий: матчит только `'Быстрая проверка безопасности'` + `'Нижняя шторка'`. Сегодняшние диалоги:
- DESC=`Диалог` (а не «Нижняя шторка»)
- TEXT=`Чтобы связаться в TikTok…` / `Разрешить TikTok доступ к списку ваших друзей…`

→ не матчатся, не закрываются.

### Сходство с WP #67 Layer 2 (PR #70)

WP #67 (SHIPPED 2026-05-18) добавила whitelist post-switch promo-modal dismiss на probe-сайтах `pre_feed` / `post_renav` — но это уже ПОСЛЕ успешного `_switch_tiktok`. Сегодняшние 4 фейла — ВНУТРИ switcher'а на профиль-табе, до того как WP #67 защита включается. Условно «Layer 3» того же паттерна.

### Предложение фикса (для WP)

В `_tt_dismiss_security_prompt` либо рядом с ним (отдельная функция `_tt_dismiss_promo_dialog`) добавить whitelist:

| title_substring | dismiss_button | scope |
|---|---|---|
| `Чтобы связаться в TikTok` (контакты promo) | `Не разрешать` | ru |
| `Разрешить TikTok доступ к списку ваших друзей` (Facebook promo) | `Не разрешать` | ru |
| (+ EN-варианты после grep по более старым дампам) | `Don't allow` / `Cancel` | en |

Вызов — в том же месте перед `_tt_is_own_profile(xml_probe)` в retap-loop (line 2326), плюс log_event с категорией `tt_promo_dialog_dismissed` + meta {variant}. Если матчнули — `time.sleep` + повторный `dump_ui` и продолжаем цикл (как сейчас сделано для security prompt).

Защиту обвешать env-flag kill-switch (`TT_PROMO_DISMISS_DISABLED=1`) на случай ложных срабатываний.

### Tests

- юнит `test_account_switcher_tt.py`: подсунуть фиксированные XML-дампы из `/tmp/tt-triage-2026-05-19/7827_retap1.xml`, проверить что `_tt_dismiss_promo_dialog` вернул True и сделал tap по корректным координатам.
- интеграция (или manual smoke): re-queue одну из 4 сегодняшних тасок (например 7884), проверить что switcher проходит.

## Артефакты

UI-дампы скачаны в `/tmp/tt-triage-2026-05-19/` (на VPS).

Ссылки на screenrecord:

- 7827: https://save.gengo.io/autowarm/screenrecords/tiktok/task7827_fail_screenrec_7827_1779181951.mp4
- 7861: https://save.gengo.io/autowarm/screenrecords/tiktok/task7861_fail_screenrec_7861_1779185501.mp4
- 7870: https://save.gengo.io/autowarm/screenrecords/tiktok/task7870_fail_screenrec_7870_1779185884.mp4
- 7884: https://save.gengo.io/autowarm/screenrecords/tiktok/task7884_fail_screenrec_7884_1779186287.mp4

## Decision

Кандидат для следующей фикс-итерации = `tt_profile_tab_broken` (4 кейса / 24% сегодня, 31 за 7д, устойчивая динамика, root cause локализован, фикс по образцу WP #67 Layer 2). Заводим WP в OpenProject.
