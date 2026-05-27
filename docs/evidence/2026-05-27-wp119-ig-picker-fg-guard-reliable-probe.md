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

---

## ФИНАЛ 2026-05-27 — задеплоено, гард ВКЛ, #119 → «Тестирование»

**Обе итерации в проде, флаг `IG_PICKER_FG_GUARD_ENABLED=1`:**
- **PR #111** (merge `48d27a4`) — foreground-пробник `_reliable_foreground_pkg` + 2-sample.
- **PR #112** (merge `e265dbc`) — освежение маркеров sheet-детектора.

**Хронология выкатки (осторожная, с мониторингом):**
1. Мерж #111 → прод pull → live read-only smoke: пробник на флоте отдаёт реальный `topResumedActivity` (IG→com.instagram.android, лаунчер→лаунчер) → флип флага `=1` + рестарт autowarm id35.
2. **Мониторинг вскрыл ВТОРОЙ over-fire** (не пробник): sheet-валидация `_ig_on_account_switcher_sheet` (PR#102) со stale-маркерами `account_switcher_recycler`/`bottom_sheet_container` → 3/3 guard-reaching задачи (11324/11327/11337) упали `ig_picker_wrong_screen`→`wrong_foreground`. **Откат** `=0` за минуты (осторожная выкатка поймала на 3 задачах, не за ночь как R2).
3. Root cause по прод-дампу (18KB открытого sheet): текущий IG использует `recycler_view_container_id` + тексты «Добавьте аккаунт Instagram»/«Перейти в Центр аккаунтов» (проверено: нет на профиле/Modal/MediaCapture). → **PR #112** освежил маркеры (legacy + текущие) + DRY `_ig_is_on_unexpected_screen`.
4. Мерж #112 → прод pull → флаг `=1` снова + рестарт. **Over-fire НЕ повторился.** Единственная live-guard-задача (11354, expertestate1) = реальный стойкий **TikTok-hijack** (probe=`com.zhiliaoapp.musically`, дамп 100% TikTok) → гард поймал foreign→recovery→TikTok вернулся→честный `wrong_foreground`. Это КОРРЕКТНО: с гардом OFF была бы misleading `ig_target_not_in_picker`. `wrong_foreground`=1 (не флуд).

**Вывод:** обе первопричины (#119) закрыты — foreground-определение (пробник) + stale sheet-маркеры. Гард ВКЛ и ведёт себя корректно (over-fire не воспроизводится; честные отказы на реальных hijack).

**Что осталось:** живой позитив «реальный sheet прошёл гард и опубликовался» НЕ пойман — дневной объём IG ~0 + шум от рестартов/watchdog #165. Verify — на **утреннем daily-batch** (24ч): IG success не просел; `ig_target_not_in_picker`→~0; `ig_account_switcher_wrong_foreground` только на реальных hijack. Откат `=0` наготове; daily-report 9:50 МСК ловит обвал. #119 → «Тестирование» (по решению Данила).

**Также закрыт бэклог «8 IG-тестов красные на main»** — они краснели из-за этого же гарда; изолированы/обновлены в рамках #111/#112.
