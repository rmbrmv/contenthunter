# Триаж упавших публикаций TikTok — 2026-05-20

Ветка: `tt-publish-fails-triage-2026-05-20`. Скоуп — только TikTok, только сегодняшние
`publish_tasks.status='failed'`. Группировка по **последнему** error-event'у
(`meta.category`), а не по `error_code` (он врёт — фиксирует первую ошибку, см.
`feedback_publisher_error_code_misleading`). Транзиентный `adb_devices_unreachable`
(сетевая проблема, уже починена) из анализа исключён по указанию пользователя.

## Распределение фейлов (27 задач)

| # | Категория | Кол-во | Доля | Задачи |
|---|-----------|:---:|:---:|--------|
| 1 | **tt_account_sheet_closed_before_parse** | **10** | **37%** | 8528, 8562, 8565, 8569, 8578, 8618, 8621, 8658, 8667, 8702 |
| 2 | tt_account_not_in_list | 3 | 11% | 8617, 8627, 8673 |
| 2 | tt_upload_confirmation_timeout | 3 | 11% | 8544, 8545, 8576 |
| 2 | tt_post_switch_verify_unrecoverable | 3 | 11% | 8573, 8616, 8685 |
| 2 | tt_profile_tab_broken | 3 | 11% | 8523, 8664, 8669 |
| 6 | tt_switch_blocked | 1 | 4% | 8539 |
| 6 | adb_device_not_ready | 1 | 4% | 8541 |
| 6 | tt_share_activity_not_opened | 1 | 4% | 8522 |
| 6 | tt_drawer_tap_did_not_open_sheet | 1 | 4% | 8543 |
| 6 | tt_fg_drift_unrecoverable | 1 | 4% | 8701 |

Лидер с большим отрывом — `tt_account_sheet_closed_before_parse` (10/27, 37%, в 3 раза
больше любого другого бакета). Выбран для фикса.

## Root cause выбранного бага

**Симптом:** на шаге переключения аккаунта (`tt_3_open_list`) bottomsheet со списком
аккаунтов «не открывается». Текст ошибки в логе гипотетизирует «залогинен только один
аккаунт» — **это неверно**, ошибка вводит в заблуждение.

**Что происходит на самом деле** (подтверждено логами, UI-dump'ами и скринкастами
8528 и 8702, маркер воспроизводится на 7/10 задачах бакета, разные устройства и проекты):

1. TikTok выкатил **Stories на аватарку профиля**. Узел аватарки теперь несёт
   `content-desc="storyringhas_consumed_story_true"` (+ подсказка «Поболтаем», промо-баннер
   «Создайте лучшие моменты с историями»).
2. `_tap_profile_header()` (`account_switcher.py:3868`) перебирает узлы в зоне
   `y_top ≤ 700` и тапает ПЕРВЫЙ, где токен проходит `_looks_like_username()`.
3. `_looks_like_username()` (`account_switcher.py:619`) по правилу «любой токен с цифрой
   или разделителем — безусловно username» матчит строку `storyringhas_consumed_story_true`
   (в ней есть `_`) → **True**.
4. Аватарка идёт в dump'е РАНЬШЕ настоящего username'а (`clickpay_world`, y_top≈503-574),
   поэтому тап уходит в центр аватарки **(540, 337)** — а это аватарка с активным
   story-кольцом → **открывается просмотрщик Stories**, а не переключатель аккаунтов.
5. Recovery-ветка (`_detect_tt_stories_viewer` → BACK → Phase 2 через «Меню профиля»)
   **не срабатывает надёжно**: dump после тапа ловит профиль/переходное состояние, а не
   Stories; плюс кнопка закрытия Stories — иконка-крестик, чей `content-desc` может не
   совпасть с маркерами `Закрыть`/`Close` (детектору нужно ≥2 из 3 признаков,
   `account_switcher.py:3898`). Обе probe-попытки в тупике → легаси-код
   `tt_account_sheet_closed_before_parse`.

**Координаты-улики (dump 8528, retry1):**
- аватарка `Фото профиля` / `storyring…`: bounds `[360,180][720,495]`, центр `(540,337)`
- username `clickpay_world`: bounds `[329,503][751,565]` (правильная цель тапа)
- `@clickpay_world`: bounds `[401,574][679,616]`

## Направление фикса (для последующей сессии)

- В `_tap_profile_header`/`_looks_like_username` исключить служебные `content-desc`
  аватарки (`storyring*`, `Фото профиля`) — матчить username по `text`, а не по
  `content-desc`, либо явный blocklist на `storyring`-токены.
- Предпочесть текстовый узел username'а и/или сузить зону тапа до диапазона
  «ниже аватарки, выше строки статистики» (между y≈500 и y≈640).
- Добить надёжность Stories-recovery: расширить `_detect_tt_stories_viewer` под
  иконку-крестик и/или добавить settle-wait перед detect (post-tap dump ловит профиль).
- Исправить вводящий в заблуждение текст ошибки (сейчас валит на «один аккаунт»).

## Артефакты
- Скринкасты: `https://save.gengo.io/autowarm/screenrecords/tiktok/task8528_fail_screenrec_8528_1779254164.mp4`,
  `…/task8702_fail_screenrec_8702_1779271664.mp4`
- UI-dump (момент фейла, 8528): `https://save.gengo.io/autowarm/ui_dumps/tiktok/task8528_switch_8528_tt_3_open_list_probe_retry1_1779254600.xml`
- Код: `account_switcher.py:619` (`_looks_like_username`), `:3868` (`_tap_profile_header`),
  `:3898` (`_detect_tt_stories_viewer`), `:4019` (`_open_tt_account_switcher`)
