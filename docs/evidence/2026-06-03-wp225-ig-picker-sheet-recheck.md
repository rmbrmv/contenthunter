# WP#225 — IG `ig_picker_sheet_not_opened` пост-тап re-check (реализация)

**OpenProject:** WP#225 (тип «Ошибка»). **Репо кода:** `delivery-contenthunter` (autowarm), ветка `wp225-ig-picker-sheet-not-opened` от origin/main `7f434f5`. **Триаж:** [2026-06-03-ig-fail-triage.md](2026-06-03-ig-fail-triage.md).

## Корень (подтверждён код + скринкасты)

`account_switcher.py::_ig_guard_picker_foreground` гоняет reguard-цикл `for attempt in range(2)`; re-чек `_ig_on_account_switcher_sheet(xml)` стоит **только в начале** каждой итерации. Sheet, открывшийся/догрузившийся **после** финального `_tap_profile_header` тапа, никогда не перепроверяется → ложный `ig_picker_sheet_not_opened`, `попыток=1`. Остаток после WP#219 (тот закрыл только дрейф на аудио-страницу Reels).

Доказательства (пост-деплой WP#219, audio-escape НЕ срабатывал):
- **task 14646** (clickpay): скринкаст на момент фейла — sheet **полностью открыт**, целевой `clickpay_world` виден в списке; цикл исчерпан без пост-тап ре-чека → fail.
- **task 14746** (born.trip90): sheet **завис на спиннере загрузки**, 2 итерации не дождались прогрузки → fail.

## Фикс (TDD, kill-switch `IG_PICKER_SHEET_RECHECK_ENABLED` default ON)

1. Kill-switch `_ig_picker_sheet_recheck_enabled()`.
2. Метод `_ig_poll_account_switcher_sheet(attempts=3, interval=1.0)` — после тапа re-dump'ит экран до `attempts` раз с паузой `interval`, возвращает True как только `_ig_on_account_switcher_sheet` распознал sheet; логирует `ig_picker_sheet_opened_after_recheck`.
3. Интеграция: одна точка вставки в reguard-цикл после `_tap_profile_header` тапа + sleep — `if recheck_enabled and self._ig_poll_account_switcher_sheet(): return True`.

Минимальная правка, одна точка вставки. Закрывает оба кейса: sheet открылся на финальном тапе (14646) и sheet догружается на спиннере (14746) — даёт ~2.0с (существующий sleep) + до 2×1.0с поллинга на прогрузку.

## Проверки

- Новый набор `tests/test_account_switcher_ig_picker_sheet_recheck.py` — 6 тестов (kill-switch on/off; poll true/false; loop возвращает True при позднем открытии sheet; legacy-поведение при выключенном switch). RED подтверждён (ImportError) → GREEN.
- Регрессия соседних наборов (audio_escape / reguard_harden / picker_fg_guard / canonical_error_codes): 58 passed.
- ⚠️ Замедление набора: poll добавляет реальные `time.sleep` в тестах, где sheet никогда не появляется (recheck ON по умолчанию) — корректно, но reguard-наборы идут ~2 мин.

## Не вошло в скоуп (осознанно)

- «Не делать BACK по полу-открытому sheet» (overlay/audio-escape) — пост-тап poll и так восстанавливает: даже если escape сделал BACK на attempt0, attempt1 ре-тапает и poll ловит открытый sheet. Без прямого XML-доказательства конкретного overlay-маркера спекулятивную правку не вносил.

## Деплой (за пределами этой сессии)

`git pull` в прод-каталоге autowarm (`/root/.openclaw/workspace-genri/autowarm`); PM2-restart НЕ нужен (publisher per-task spawn). После мержа PR в `delivery-contenthunter` main. Verify по событию `ig_picker_sheet_opened_after_recheck` + падение `ig_picker_sheet_not_opened`.
