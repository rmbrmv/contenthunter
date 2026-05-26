# YT yt_6: «+» открывает камеру Shorts напрямую (ложный yt_create_menu_not_reached) — design

**Date:** 2026-05-26
**WP:** OpenProject #134 «YouTube: на шаге создания вместо меню всплывает камера TikTok (подсигнатура B, связано с #132)»
**Repo:** `GenGo2/delivery-contenthunter` (prod: `/root/.openclaw/workspace-genri/autowarm`)
**Status:** approved by user 2026-05-26

## Контекст и разведка

WP#134 заведена как «подсигнатура B» триажа #132: на шаге создания YouTube после тапа «+» якобы всплывает **камера записи TikTok**, бот не находит меню → `yt_create_menu_not_reached`. Доказательная база — 3 падения за 21.05: задачи `9025` (raspberry 1, @SmartEstateSpb), `9092` (raspberry 5, @DriveSAndDeliver), `9108` (raspberry 10, @AromaLuxCollection). Все три — разные устройства и аккаунты.

**Разведка опровергла премису задачи.** Скачаны и просмотрены записи экрана всех трёх падений (`save.gengo.io/.../task{9025,9092,9108}_fail_*.mp4`). На всех трёх финальный экран — **нативная камера YouTube Shorts**, а не TikTok:

- нижние вкладки **«Видео | Shorts | Эфир | Запись»**, выбран Shorts;
- верх — **«♪ Добавить трек»**, таймер «15», карточка «Использовать этот трек»;
- красная кнопка записи, правый тулбар (флип/скорость/таймер/эффекты), галерея «Добавить» слева снизу;
- в статус-баре — иконка ▷ YouTube, никакого TikTok-брендинга.

У задачи 9092 в статус-баре есть значки уведомлений TikTok (фон), что, вероятно, и сбило исходный триаж — вертикальные камеры визуально похожи.

**Почему телеметрия молчала.** У всех трёх задач последовательность событий идентична: `yt_post_switch_handle_unknown` с `foreground_pkg=com.google.android.youtube` на `yt_5_target_profile` → сразу `yt_create_menu_not_reached` на `yt_6_create_menu_no_triggers`. События `yt_create_menu_app_not_foregrounded` **нет**, поля `foreground_pkg` на fail-событии пустые. То есть Layer C (WP#87) при своей единственной проверке foreground не увидел чужого пакета — потому что это **и есть YouTube**, просто другой его экран. Распознать это можно было только из видео.

## Корневая причина

Тап «+» («Создание видео») у этих аккаунтов открывает **камеру Shorts напрямую**, минуя bottom-sheet «меню создания». Шаг свича `yt_6` вызывает `_tap_plus_and_verify(strict_verify=True)` с `verify_triggers = cfg['editor_triggers']` (`['Добавить описание','Add description','Опубликовать','Upload','Видео','Прямой эфир','Live']`). Поверхность камеры даёт пустой/разреженный uiautomator-dump, exact-match триггеров возвращает `[]` → `_fail('yt_create_menu_not_reached')`.

Падение происходит в `_ensure_correct_account()` (`publisher_base.py:2045`, через `publisher_youtube.py:1321`) — **до** того, как публикатор доберётся до реального механизма загрузки.

**Ключевое наблюдение по архитектуре.** Загрузка в `publish_youtube_short` идёт через прямой интент **`Shell_UploadActivity`** (`am start -n …/Shell_UploadActivity -a android.intent.action.SEND -t video/mp4 --eu android.intent.extra.STREAM <uri>`), который **минует и камеру, и галерею** (`publisher_youtube.py:1366–1377`). Более того, перед загрузкой безусловно вызывается `_normalize_yt_state_pre_upload` (`publisher_youtube.py:1334`), который делает `am force-stop com.google.android.youtube` + relaunch на home-feed — то есть **меню создания, открытое на yt_6, в любом случае закрывается** до загрузки (а путь «выбрать Shorts из меню», стр. 1347–1364, в норме мёртв, т.к. `_is_create_menu_open` после normalize = False).

Вывод: строгая проверка create-menu на `yt_6` — **рудиментарный гейт**, который роняет задачу раньше, чем отрабатывает устойчивый путь загрузки. Аккаунт уже подтверждён раньше на `yt_5_target_profile`; для самой загрузки bottom-sheet меню не требуется.

Это исключает «починку навигацией камера → галерея»: галерея системе не нужна. Также исключает исходный вариант «force-stop TikTok»: TikTok ни при чём.

## Цель

Перестать фатально ронять `yt_6` с маскарадом `yt_create_menu_not_reached`, когда после тапа «+» мы остались **внутри YouTube** (камера Shorts или иной create-экран). Дать отработать устойчивому пути `_normalize_yt_state_pre_upload` → `Shell_UploadActivity`. Ожидаемо: 3 задачи сегодняшнего паттерна (и аналогичные) переходят из фатального fail в успешную загрузку; при остаточном сбое — честная downstream-атрибуция вместо маскарада.

## Архитектура

Все изменения локализованы в одном модуле — `account_switcher.py`:

- новый kill-switch-хелпер `_yt6_accept_nonmenu_foreground_enabled()` (рядом с `_guard_enabled` / `_premium_dismiss_enabled`, ~стр. 211/223);
- новый module-level хелпер-детектор `_yt_is_shorts_camera(xml)` (только для телеметрии, не гейтит);
- одна вставка в `_tap_plus_and_verify` в ветке `if strict_verify and not hits:` — **после** premium-promo recovery (WP#132 имеет приоритет) и **до** финального `_fail('yt_create_menu_not_reached')`.

Используются уже существующие хелперы: `_detect_foreground_pkg`, `self._ok`, `self.p.log_event`. Никаких новых модулей, таблиц БД или схема-миграций. Изменение касается **только YT-ветки** (`strict_verify=True`); IG/TT (`strict_verify=False`) не затронуты — это инвариант, проверяемый тестом.

## Логика soft-pass

В `_tap_plus_and_verify`, ветка `if strict_verify and not hits:` (текущая стр. ~5040):

```python
if strict_verify and not hits:
    # [WP #132] (существующее) premium-promo recovery — приоритет ...
    if _premium_dismiss_enabled() and _yt_is_premium_promo(ui2):
        ...   # без изменений

    # [WP #134] остались внутри YouTube, но не на bottom-sheet «меню создания»?
    # Камера Shorts (или иной create-экран) — НЕ фатально: загрузка идёт через
    # Shell_UploadActivity, которому bottom-sheet не нужен; аккаунт подтверждён
    # на yt_5. _normalize_yt_state_pre_upload всё равно закроет этот экран.
    if _yt6_accept_nonmenu_foreground_enabled():
        fg = self._detect_foreground_pkg()
        if fg and fg == cfg['package']:
            self.p.log_event(
                'warning', 'yt_create_menu_camera_direct',
                meta={'category': 'yt_create_menu_camera_direct',
                      'step': final_step,
                      'foreground_pkg': fg,
                      'shorts_camera_markers': _yt_is_shorts_camera(ui2)},
            )
            return self._ok(final_step, already_matched=already_matched)

    # (существующий) genuine fail — только если YT НЕ на переднем плане
    # ИЛИ kill-switch off ...
    fail_step = f'{final_step}_no_triggers'
    ...  # yt_create_menu_not_reached — без изменений
```

**Решения по дизайну:**

- **Гейт по `fg == cfg['package']`, а не по тексту вкладок.** Dump камеры пустой/разреженный — текстовый детект ненадёжен. Foreground-пакет читается через `_detect_foreground_pkg()` (dumpsys fallback) и устойчив к пустому XML. Drift (fg ≠ YT — лончер/sbrowser/чужой пакет) по-прежнему уходит в фатальный fail; вдобавок такой drift обычно уже отлавливается Layer C (стр. 4992) до этой ветки.
- **`_yt_is_shorts_camera(ui2)` — только под-флаг телеметрии**, не участвует в решении. Маркеры (content-desc/text): `'Добавить трек'`, `'Add sound'`, `'Add a sound'`, либо элемент галереи (content-desc содержит `'галере'`/`'gallery'`). Пустой/битый XML → `False`, без исключения.
- **Приоритет premium-promo сохранён**: если экран — промо Premium, отрабатывает ветка WP#132, до soft-pass дело не доходит.

## Что происходит дальше (почему это чинит)

`_ok` → `_ensure_correct_account` = `True` → `publish_youtube_short` продолжает → `_normalize_yt_state_pre_upload` (force-stop YT + home-feed — попутно убирает камеру) → `Shell_UploadActivity` грузит видео → `_verify_yt_editor_reached` → редактор → публикация. Это устойчивый путь, который сейчас блокируется фатальным fail на yt_6.

Если после soft-pass загрузка всё же упадёт (проблема `Shell_UploadActivity`/редактора) — это честный `yt_editor_not_reached`/downstream, а не маскарад `yt_create_menu_not_reached`. Чистый выигрыш для триажа.

## Наблюдаемость

- Новая категория события `yt_create_menu_camera_direct` (type `warning` — видно в дашбордах, но не error). Meta: `step`, `foreground_pkg`, `shorts_camera_markers`.
- SQL для verify (доля soft-pass и downstream-исход):

```sql
SELECT pt.status,
       (e->'meta'->>'shorts_camera_markers') AS markers,
       COUNT(*) hits
FROM publish_tasks pt, LATERAL jsonb_array_elements(pt.events) e
WHERE pt.platform='YouTube' AND pt.started_at > '<deploy_ts>'
  AND e->'meta'->>'category' = 'yt_create_menu_camera_direct'
GROUP BY 1,2 ORDER BY hits DESC;
```

## Kill-switch

`_yt6_accept_nonmenu_foreground_enabled()` читает env `YT6_ACCEPT_NONMENU_FOREGROUND` (default `'1'`, ON). По образцу `_guard_enabled()` (`YT_CREATE_MENU_GUARD_ENABLED`). Откат к строгому поведению: `YT6_ACCEPT_NONMENU_FOREGROUND=0` в PM2 ecosystem + restart.

## Тесты (unit, паттерн `_FakeProxy`)

В существующем тест-модуле switcher'а (рядом с тестами `_tap_plus_and_verify` / WP#87 / WP#132):

1. `strict_verify`, нет триггеров, `fg == youtube`, флаг ON → `_ok`, эмитится `yt_create_menu_camera_direct`.
2. `strict_verify`, нет триггеров, `fg != youtube` (лончер) → `_fail('…_no_triggers')` (поведение сохранено).
3. `strict_verify`, нет триггеров, `fg == youtube`, kill-switch OFF → legacy `_fail('yt_create_menu_not_reached')`.
4. Premium-промо имеет приоритет: `_yt_is_premium_promo=True` → premium-ветка, soft-pass не вызывается.
5. `_yt_is_shorts_camera`: dump камеры (с «Добавить трек») → `True`; dump меню → `False`; пустой/битый XML → `False` без краша.
6. Happy-path: триггеры найдены → `_ok`, событие камеры НЕ эмитится (без изменений).
7. Инвариант: `strict_verify=False` (IG/TT) — новая ветка не выполняется ни при каком `fg`.

**Mock-drift guard:** перед написанием тестов сверить, что `_FakeProxy`/тест-дубль имеет методы 1-в-1 с `DevicePublisher`: `_detect_foreground_pkg`, `dump_ui`, `log_event`, `tap_element`, `adb_tap` (урок mock-proxy-drift, PR #52).

## Живой смоук (согласован с пользователем)

На testbench/живом устройстве:

- (best) воспроизвести аккаунт, у которого «+» открывает камеру Shorts; прогнать публикацию; подтвердить в событиях `yt_create_menu_camera_direct` → затем успешную загрузку через `Shell_UploadActivity` (screenrecord + events).
- (min) подтвердить, что happy-path (обычный аккаунт с bottom-sheet меню) не сломан и публикуется как раньше.

## Деплой / откат

- Репо `GenGo2/delivery-contenthunter`, prod autowarm (`/root/.openclaw/workspace-genri/autowarm`, auto-push git-hook). PM2-перезапуск воркера публикаций.
- Откат: `YT6_ACCEPT_NONMENU_FOREGROUND=0` + restart.
- 24ч verify: динамика `yt_create_menu_not_reached` ↓ + появление `yt_create_menu_camera_direct` с последующим `status='done'`/awaiting_url у затронутых аккаунтов.

## Non-goals

- Не удаляю `yt_6` / тап «+» целиком (рудимент, но безвредный happy-path'у — будущая чистка отдельной WP).
- Не трогаю путь навигации галереи (системой не используется).
- Не force-stop'аю TikTok (исходная премиса исключена разведкой).
- Не меняю `Shell_UploadActivity` и `_normalize_yt_state_pre_upload`.

## Сопутствующее

- Корректирующий комментарий в OpenProject #134: это камера **YouTube Shorts**, а не TikTok; фикс снимает избыточную строгость гейта yt_6. Доказательства — записи экрана 9025/9092/9108.
- Связь: WP#87 (`_tap_plus_and_verify` Layer A–D, `yt_create_menu_app_not_foregrounded`), WP#132 (premium-promo recovery — приоритетная ветка), WP#74 (`_dismiss_foreign_foreground` — другой call-site, не yt_6).
