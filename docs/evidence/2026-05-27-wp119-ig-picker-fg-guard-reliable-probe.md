# WP #119 — IG picker fg-guard на надёжном пробнике: evidence

**Дата:** 2026-05-27
**Статус:** код-комплит, PR открыт; прод-флаг OFF; ожидает мерж + live-smoke + включение.
**PR:** https://github.com/GenGo2/delivery-contenthunter/pull/111 (ветка `feat/wp119-ig-picker-fg-guard-rework`, 4 коммита)
**Spec/Plan:** `docs/superpowers/specs|plans/2026-05-27-wp119-ig-picker-fg-guard-reliable-probe*`

## Что было не так
Гард `_ig_guard_picker_foreground` (account_switcher.py, шаг `ig_4_pick_account`) определял foreground
через `_detect_foreground_pkg`, который берёт **первый** `package="..."` из XML-дампа uiautomator —
а это почти всегда системный overlay/статус-бар (`com.android.systemui`)/лаунчер, не реальный
foreground. → ложный «foreign» почти на каждой задаче → массовый `ig_account_switcher_wrong_foreground`,
IG-успех 79%→22% (инцидент 26.05, 95/169). Гард откатили `IG_PICKER_FG_GUARD_ENABLED=0`.

## Что сделано
- `AccountSwitcher._reliable_foreground_pkg()` — делегирует в `_ig_probe_foreground_pkg`
  (bare-dumpsys `topResumedActivity`, WP #129/#135); fallback bare-dumpsys для шима (account_revision)
  с try/except; нормализация `'unknown'`/пусто/не-строка → `''` (undetermined = no-op).
- `_ig_guard_picker_foreground` → надёжный пробник + **2-sample confirm** (паттерн WP #129): чужой
  foreground только при двух подтверждениях подряд → одиночный транзиент лаунчера не триггерит recovery.
  + observability-лог `ig_picker_fg_probe`.
- Глобальный `_detect_foreground_pkg` НЕ тронут (YT/TT на нём держатся). Recovery + sheet-валидация гарда не изменены.
- Тесты: 5 новых прямых тестов гарда (вкл. регресс-тест инцидента 26.05); 8 интеграционных/канонических
  изолированы от гарда (мок no-op); dedicated-набор `test_account_switcher_ig_picker_fg_guard.py`
  обновлён под надёжный пробник + 2-sample, recovery-тесты сделаны не-вакуумными.

## Верификация
- `pytest test_account_switcher.py + test_canonical_error_codes.py + test_account_switcher_ig_picker_fg_guard.py` → **97 passed**.
- Полная сюита: **0 регрессий** — 15 pre-existing падений + 7 errors идентичны main (a47c49c) (publish_guard, testbench_orchestrator, unic_logo_resolver ModuleNotFoundError и т.п. — не связаны с #119).
- codex review полного диффа — **0 P1**.
- Независимое opus-ревью: единственный CHANGES-REQUESTED — упущенный dedicated-набор тестов гарда
  (мокал мёртвый `_detect_foreground_pkg`, 1 hard-fail + 3 вакуумных) — **устранён** (коммит 4ca603a).

## Заметные отклонения от плана (приняты осознанно)
1. **Идиом изоляции тестов:** план предлагал `setenv(IG_PICKER_FG_GUARD_ENABLED='0')`; реализовано через
   мок `_ig_guard_picker_foreground`→True в фикстуре (одно место, рефактор-безопаснее). Применено единообразно.
2. **Третий тест-файл:** план/baseline охватывали только 2 файла; финальное ревью поймало третий
   (`test_account_switcher_ig_picker_fg_guard.py`), мокавший старый пробник. Урок: при правке метода
   грепать ВСЕ тест-файлы по имени метода, не только «очевидные».

## Что осталось
- Гард под `IG_PICKER_FG_GUARD_ENABLED`, в проде **OFF** (`=0`) — остаётся OFF до проверки.
- После мержа PR #111: live-smoke на устройстве с гардом ON (рецепт смока #19, INSERT testbench-задача
  → `IG_PICKER_FG_GUARD_ENABLED=1 python3 publisher.py <id>`) → если чисто (0 wrong_foreground, в логе
  `ig_picker_fg_probe`=com.instagram.android, флоу до success) → флип прод `.env` на `=1`.
- Verify 24ч: IG success ≈79%; `ig_target_not_in_picker`→~0; `ig_account_switcher_wrong_foreground`
  только на реальных foreign; `ig_picker_fg_transient` редкие. Откат: `=0`.
- OpenProject #119 остаётся «В разработке» до SHIPPED+DEPLOYED (после включения флага).
