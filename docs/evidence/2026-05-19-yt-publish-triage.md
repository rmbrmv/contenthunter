# YT publish triage — 2026-05-19

Triage timestamp: 2026-05-19 10:36 UTC (день не закончен, выборка фиксируется на этом моменте).

## Сводка

За 2026-05-19 (UTC) создано 39 YT publish-задач:
- failed: 35 (на момент запроса), к 11:00 UTC — уже 39 строк failed
- pending: 3
- done: 0

Fail-rate ≈ 97%. 8 разных raspberry, 35+ разных аккаунтов. Это не account-side проблема, а системная регрессия.

## Распределение error_code

| error_code | count | примечание |
|---|---|---|
| `yt_create_menu_not_reached` | 26 | топ |
| `yt_editor_not_reached` | 7 | |
| `adb_push_chunked_exception` | 2 | оба на raspberry 2 и 5 |
| `switch_failed_unspecified` | 1 | ADB preflight — сетевой шум, **игнор по указанию пользователя** |

## Root cause (предварительный)

**24 из 25** случаев `yt_create_menu_not_reached` сопровождаются warning'ом `yt_post_switch_handle_unknown` на шаге `yt_5_target_profile` — то есть свич не подтверждён, но мы всё равно идём в Create-меню.

UI-dump проверка на 6 задачах (7726, 7729, 7740, 7766, 7847, 7867):
- На шаге `yt_5_target_profile` foreground = **`com.google.android.youtube`** (YT в фокусе ✅).
- На шаге `yt_6_create_menu` (после tap «+») foreground = **`com.sec.android.app.launcher`** (YouTube свернулся в Samsung-лончер ❌).

strict_verify читает дамп лончера, не находит триггеров «Видео/Опубликовать/Прямой эфир» и фейлит как `yt_create_menu_not_reached`. Это совпадает у всех 6 проверенных задач.

## Полный список failed-задач сегодня

| pt_id | account | raspberry | error_code | screen_record |
|---|---|---|---|---|
| 7726 | enoty_po_polkam_hub | 2 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7726_fail_screenrec_7726_1779169541.mp4) |
| 7727 | contenthunter-x1e | 5 | switch_failed_unspecified (ADB шум) | — |
| 7728 | Lead_Content_1 | 5 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7728_fail_screenrec_7728_1779169165.mp4) |
| 7729 | ell-cosmo | 2 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7729_fail_screenrec_7729_1779169729.mp4) |
| 7730 | elcosmetics | 1 | yt_create_menu_not_reached | — |
| 7731 | feminista.beauty | 9 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7731_fail_screenrec_7731_1779169242.mp4) |
| 7732 | feminista_patches | 9 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7732_fail_screenrec_7732_1779169774.mp4) |
| 7737 | swarovski.beauty | 2 | adb_push_chunked_exception | — |
| 7739 | DubaiHomes-est | 5 | adb_push_chunked_exception | — |
| 7740 | feminista_glow | 9 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7740_fail_screenrec_7740_1779170657.mp4) |
| 7745 | enoty-po-polkam-poker | 2 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7745_fail_screenrec_7745_1779170242.mp4) |
| 7746 | swarovski_life | 2 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7746_fail_screenrec_7746_1779170262.mp4) |
| 7747 | autopostfactory | 3 | yt_editor_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7747_fail_screenrec_7747_1779170740.mp4) |
| 7748 | content_expert | 3 | yt_editor_not_reached | — |
| 7766 | AzureDubaiEstates | 1 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7766_fail_screenrec_7766_1779171501.mp4) |
| 7777 | elcosmo_beauty | 1 | yt_editor_not_reached | — |
| 7834 | clickpay_app | 7 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7834_fail_screenrec_7834_1779182551.mp4) |
| 7842 | ivanov_expert | 3 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7842_fail_screenrec_7842_1779183171.mp4) |
| 7845 | maksim_estate-o6x | 8 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7845_fail_screenrec_7845_1779183503.mp4) |
| 7846 | EliteSPBHouse | 8 | yt_editor_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7846_fail_screenrec_7846_1779183493.mp4) |
| 7847 | PrimeEstate-o7x | 2 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7847_fail_screenrec_7847_1779184590.mp4) |
| 7848 | SPBEliteEstate | 3 | yt_editor_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7848_fail_screenrec_7848_1779183679.mp4) |
| 7852 | axilor_prive | 1 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7852_fail_screenrec_7852_1779183739.mp4) |
| 7853 | clickpay_now | 7 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7853_fail_screenrec_7853_1779183851.mp4) |
| 7854 | nofomo-c9m | 3 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7854_fail_screenrec_7854_1779183962.mp4) |
| 7857 | gerog-r7z | 5 | yt_editor_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7857_fail_screenrec_7857_1779186044.mp4) |
| 7859 | axilor_brand | 1 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7859_fail_screenrec_7859_1779184221.mp4) |
| 7862 | elcosmetics | 1 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7862_fail_screenrec_7862_1779184793.mp4) |
| 7863 | SpbProperty1Guide | 2 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7863_fail_screenrec_7863_1779185145.mp4) |
| 7864 | Golden_Aroma | 10 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7864_fail_screenrec_7864_1779185518.mp4) |
| 7865 | procontent_lab | 3 | yt_editor_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7865_fail_screenrec_7865_1779184638.mp4) |
| 7867 | YieldDubaiEstates | 1 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7867_fail_screenrec_7867_1779185216.mp4) |
| 7869 | EliteCornersSpb | 2 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7869_fail_screenrec_7869_1779185261.mp4) |
| 7876 | content.hunter1 | 3 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7876_fail_screenrec_7876_1779185543.mp4) |
| 7877 | DubaiAssetExpert | 1 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7877_fail_screenrec_7877_1779186234.mp4) |
| 7882 | kiroch_kaNova | 10 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7882_fail_screenrec_7882_1779187349.mp4) |
| 7886 | SmartEstatesDubai | 1 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7886_fail_screenrec_7886_1779186881.mp4) |
| 7888 | quickrouterider | 5 | yt_editor_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7888_fail_screenrec_7888_1779187533.mp4) |
| 7895 | swarovski.health | 2 | yt_create_menu_not_reached | [mp4](https://save.gengo.io/autowarm/screenrecords/youtube/task7895_fail_screenrec_7895_1779187331.mp4) |

## UI dumps (foreground evidence)

Перед tap «+» (foreground = YouTube):
- https://save.gengo.io/autowarm/ui_dumps/youtube/task7726_switch_7726_yt_5_target_profile_1779169790.xml → `package="com.google.android.youtube"`
- https://save.gengo.io/autowarm/ui_dumps/youtube/task7766_switch_7766_yt_5_target_profile_1779171784.xml → `package="com.google.android.youtube"`

После tap «+» (foreground = Samsung launcher):
- https://save.gengo.io/autowarm/ui_dumps/youtube/task7726_publish_7726_fail_yt_6_create_menu_no_triggers_1779169817.xml → `package="com.sec.android.app.launcher"`
- https://save.gengo.io/autowarm/ui_dumps/youtube/task7729_publish_7729_fail_yt_6_create_menu_no_triggers_1779169978.xml → `package="com.sec.android.app.launcher"`
- https://save.gengo.io/autowarm/ui_dumps/youtube/task7740_publish_7740_fail_yt_6_create_menu_no_triggers_1779170911.xml → `package="com.sec.android.app.launcher"`
- https://save.gengo.io/autowarm/ui_dumps/youtube/task7766_publish_7766_fail_yt_6_create_menu_no_triggers_1779171811.xml → `package="com.sec.android.app.launcher"`
- https://save.gengo.io/autowarm/ui_dumps/youtube/task7847_publish_7847_fail_yt_6_create_menu_no_triggers_1779184857.xml → `package="com.sec.android.app.launcher"`
- https://save.gengo.io/autowarm/ui_dumps/youtube/task7867_publish_7867_fail_yt_6_create_menu_no_triggers_1779185483.xml → `package="com.sec.android.app.launcher"`

## OpenProject

WP #87 — существующая, обновлена комментарием (activity #281). Приоритет поднят: Обычный → Высокий.
