# TikTok publish-fails triage — 2026-05-29

Источник: `publish_tasks` (openclaw, localhost:5432), `platform='TikTok'`,
`created_at::date=current_date`, `testbench=false`, `is_canary=false`.

## Объём за сегодня

| status | count |
|---|---|
| done | 44 |
| **failed** | **22** |
| published_no_url | 10 |

`published_no_url` (10) — отдельная история URL-capture (контент опубликован, URL не снят),
не «падение публикации»; в триаж падений не включаю.

## Разбивка 22 упавших по ФИНАЛЬНОЙ категории ошибки

(берём последнее событие `type='error'` из `events`, т.к. `error_code` пишет ПЕРВУЮ ошибку и врёт)

| # | финальная категория | кол-во | природа |
|---|---|---|---|
| 1 | **tt_drawer_tap_did_not_open_sheet** | **5** | **БАГ кода (см. ниже) — выбран для фикса** |
| 2 | tt_upload_confirmation_timeout | 3 | подтверждение загрузки |
| 3 | tt_account_not_in_list | 3 | переключение аккаунтов |
| 4 | tt_account_sheet_closed_before_parse | 3 | переключение (WP#182, на тестировании) |
| 5 | tt_fg_drift_unrecoverable | 2 | foreground drift |
| 6 | tt_switch_blocked | 2 | аккаунт забанен (phone_or_email_link_required) — не баг кода |
| 7 | tt_post_switch_verify_unrecoverable | 1 | переключение |
| 8 | tt_stories_back_failed | 1 | навигация Stories |
| 9 | screencast_stop_failed | 1 | инфра/артефакт записи |
| 10 | screencast_pull_failed | 1 | инфра/артефакт записи |

Кластер «переключение аккаунтов» (1,3,4,5,6,7) = 16/22 ≈ 73% всех падений.
Единственная **доминирующая** причина с чистым, локализованным root-cause и готовым фиксом —
**№1 `tt_drawer_tap_did_not_open_sheet` (5/22 ≈ 23%)**.

## Root cause №1 — `tt_drawer_tap_did_not_open_sheet`

Затронутые задачи (все аккаунты проекта clickpay, 3 устройства):

| task | account | device | время |
|---|---|---|---|
| 11919 | clickpay_express | RFGYC31P1RH | 05:37 |
| 11944 | clickpay_life | RFGYC31P7DT | 06:32 |
| 12019 | clickpay_team | RFGYC31P7DT | 09:27 |
| 12025 | just_clickpay | RFGYC31P1RH | 09:37 |
| 12038 | clickpay_hub | RFGYC31P94Z | 10:07 |

### Доказательства (сошлись 4 источника)

1. **UI-дампы шага `tt_3_open_list_sheet`** у всех 5 задач: `usable=False`, ровно 8312 байт,
   но XML **читаемый** (23 ноды, валидный) — это страница **«Заблокированные аккаунты» /
   «Заблокированных аккаунтов нет»**, package `com.zhiliaoapp.musically`. Не шит выбора аккаунта.
2. **Скринкаст** task 12038 (`task12038_fail_screenrec_...mp4`, 185с): весь хвост (170–185с)
   статично висит на экране «Заблокированные аккаунты».
3. **Предыдущие шаги** (`probe/back/menu/drawer/settings/settings_scroll1`) — все `usable=True`.
   Промах происходит ровно на переходе к шиту.
4. **meta ошибки**: `sheet_open_signal=false`, `drawer_anchor_label=''` (пустой) — значит сработал
   Pass 2 матчера: текст-нода совпала с триггером, тапнут её clickable-контейнер без своего текста.

### Механизм

`account_switcher.py` → Settings-fallback в `_run_tt_phase2_menu_path`
(строки ~5263–5302). Когда прямого триггера в drawer нет, код заходит в
«Настройки и конфиденциальность» и скроллит страницу, на каждом шаге вызывая
`_find_tt_account_switcher_anchor_in_drawer(elements)` с дефолтными
`TT_DRAWER_ACCOUNT_TRIGGERS`.

Матчер (`account_switcher.py:4975` и `:4985`) использует **подстрочный** матч:
```python
if trigger in (el.label or '').lower():
```
Триггер `'аккаунты'` (`TT_DRAWER_ACCOUNT_TRIGGERS`, строка 146) является подстрокой
`'заблокированные аккаунты'`:
```python
>>> 'аккаунты' in 'заблокированные аккаунты'
True
```
→ строка **«Заблокированные аккаунты»** (раздел Приватность) ошибочно опознаётся как точка входа
в переключатель, тапается (строка 5302), приложение уходит на dead-end «Заблокированные аккаунты»,
шит не открывается → честный, но бесполезный `tt_drawer_tap_did_not_open_sheet` → ручная выкладка.

Это в точности тот substring-leak, от которого уже защитились regex-ом для «Добавить аккаунт»
(`_TT_ADD_ACCOUNT_RE`, строка 5003), и зеркало урока про bare `'аккаунт'` (iter#5 2026-05-14,
строки 148–154) — но множественное `'аккаунты'` всё ещё ловит «Заблокированные аккаунты».

### Предлагаемый фикс (направление, не реализация)

- Сделать матч `'аккаунты'/'accounts'` устойчивым к подстрокам: word-boundary / exact-row,
  ИЛИ добавить blocklist dead-end строк (`'заблокированные аккаунты'`, `'blocked accounts'`,
  плюс уже известные dead-end) и исключать их в `_find_tt_account_switcher_anchor_in_drawer`.
- Покрыть TDD-тестом: дамп settings-страницы с «Заблокированные аккаунты» НЕ должен выдавать anchor.
- Kill-switch по образцу прочих TT-гардов.
