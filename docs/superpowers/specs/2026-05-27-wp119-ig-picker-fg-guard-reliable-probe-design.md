# WP #119 — IG picker foreground-guard на надёжном пробнике (форвард-фикс over-fire)

**Дата:** 2026-05-27
**Задача:** OpenProject #119 (Ошибка, «В разработке», assignee Данил)
**Репозиторий кода:** `GenGo2/delivery-contenthunter` (prod `/root/.openclaw/workspace-genri/autowarm`, ветка `main`)
**Файл:** `account_switcher.py`

## Контекст

`_ig_guard_picker_foreground` (account_switcher.py:1799) — гард, добавленный в WP #119,
чтобы перед чтением списка аккаунтов на шаге `ig_4_pick_account` убедиться, что на
переднем плане Instagram, а не чужое приложение. Корень исходного бага: `ig_target_not_in_picker`
(0–5/день) — на этом шаге foreground иногда уходит в YouTube/TikTok/лаунчер, парсер скребёт
чужой экран и эмитит вводящий в заблуждение «аккаунт не привязан к устройству».

**Инцидент 2026-05-26 (регрессия).** Гард с включённым флагом `IG_PICKER_FG_GUARD_ENABLED`
обрушил общий успех IG **79% → 22%** за сутки (95 hard-fail `ig_account_switcher_wrong_foreground`
из 169 задач, 0 публикаций, 7 устройств). Митигация — `IG_PICKER_FG_GUARD_ENABLED=0` в прод `.env`
(гард сейчас OFF, мелкий `ig_target_not_in_picker` вернулся как «меньшее зло»).

**Корень over-fire (подтверждён по коду).** Гард определяет foreground через
`_detect_foreground_pkg` (account_switcher.py:3940), который берёт **первый**
`package="..."` из XML-дампа uiautomator (`re.search(r'package="([^"]+)"', xml)`).
В дампе таких атрибутов десятки (по одному на узел), и первый — почти всегда системный
overlay / статус-бар / nav-бар (`com.android.systemui`, лаунчер), а не реальное
foreground-приложение. → гард видит «чужой пакет» даже когда IG на переднем плане →
массовый ложный `ig_account_switcher_wrong_foreground`.

**Надёжный пробник уже есть.** `_ig_probe_foreground_pkg` (`publisher_instagram.py:899`,
WP #129/#135) использует bare-dumpsys `topResumedActivity` и возвращает реальный
foreground-пакет (или `'unknown'`). WP #135 уже SHIPPED и в «Тестировании» — пробник
стабилен в проде; коллизии «двух пробников в полёте», из-за которой комментарий v9 (26.05)
предлагал свернуть фикс в #135, больше нет.

## Цель

1. Перевести гард `_ig_guard_picker_foreground` на надёжный пробник, устранив over-fire.
2. Сохранить kill-switch `IG_PICKER_FG_GUARD_ENABLED` и recovery-логику.
3. После live-проверки снова включить гард в проде (`IG_PICKER_FG_GUARD_ENABLED=1`).
4. Починить 8 связанных IG-тестов, красных на main (тот же гард-сёрфейс).

## Решения (утверждены Данилом 2026-05-27)

- **Цель:** переделать гард на надёжный пробник и снова включить (не оставлять OFF).
- **Где:** в рамках #119 (в `account_switcher.py`), потребляя стабильный пробник #135;
  саму #135 не трогаем, её 24ч-верификацию не размываем.
- **Hardening 2-sample:** включаем (см. ниже).

## Дизайн

### 1. Надёжный пробник в `AccountSwitcher`

Новый метод `_reliable_foreground_pkg() -> str`:

- Если у `self.p` есть `_ig_probe_foreground_pkg` (бой — `DevicePublisher` с `InstagramMixin`) —
  делегируем туда (DRY, единый источник истины с #135).
- Иначе (шим из `account_revision.py:375`, у которого может не быть IG-методов) —
  fallback на локальный bare-dumpsys через `self.p.adb`:
  `dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"`,
  парс `ActivityRecord\{[^}]*?\s([\w.]+)/`.
- **Нормализация:** `'unknown'` / пустая строка → возвращаем `''` (= «не определили»).
  Критично: иначе `foreign = ('unknown' != cfg['package'])` ложно сработал бы — это была бы
  новая over-fire-ловушка. `''` сохраняет существующую семантику «не определили → no-op».

`getattr(self.p, '_ig_probe_foreground_pkg', None)` + проверка `callable` — безопасно для шима.

### 2. Гард `_ig_guard_picker_foreground`

Единственная правка источника foreground: `self._detect_foreground_pkg()` →
`self._reliable_foreground_pkg()`. **Глобальный `_detect_foreground_pkg` НЕ трогаем** —
на нём держатся YT-fg-drift и TT-детекты, менять его поведение глобально вне скоупа #119.

Recovery при genuine foreign (`_ensure_app_foregrounded('Instagram')` + re-nav в список) и
screen-validation `_ig_on_account_switcher_sheet` (sheet-guard под `IG_PICKER_SHEET_GUARD_ENABLED`)
уже реализованы — оставляем как есть. False из гарда → caller эмитит честный
`ig_account_switcher_wrong_foreground` вместо `ig_target_not_in_picker`.

### 3. Защита от транзиента (2-sample confirm)

Зеркалим паттерн WP #129 (`_ig_wait_upload_fg_step`, `lost_streak>=2`): считаем foreground
чужим только если **два последовательных** замера `_reliable_foreground_pkg()` согласны, что
пакет чужой (между замерами `time.sleep(~0.5)`). Одиночный транзиент (лаунчер мелькнул во
время анимации) → no-op, гард не вмешивается.

Обоснование: пробник через `topResumedActivity` надёжен, но на шаге picker возможен
кратковременный транзиент; recovery хоть и benign, лишние re-nav нежелательны. Учитывая
катастрофичную историю гарда — дешёвая страховка от повторного over-fire. Согласовано.

### 4. Observability

Логируем определённый пакет на каждом входе в гард (debug/info, не gated), чтобы в проде
подтвердить: пробник отдаёт `com.instagram.android`, а не `systemui`/лаунчер. Существующий
`ig_picker_fg_foreign` warning при genuine foreign сохраняем.

## Тесты (TDD)

Новые:
- **Регресс инцидента 26.05:** `_reliable_foreground_pkg`/пробник = IG, но `dump_ui` XML с
  первым узлом `com.android.systemui`/лаунчер → гард **не** срабатывает (no-op, True).
  Этот тест поймал бы инцидент.
- **`'unknown'`/пусто → no-op** (True, undetermined).
- **Genuine foreign → recovery:** успех recovery → True; неуспех → False (→ честный
  `ig_account_switcher_wrong_foreground`).
- **2-sample:** одиночный foreign-замер → no-op; два подряд → recovery.

Чиним 8 существующих красных на main (`test_account_switcher.py` ×6 + `test_canonical_error_codes.py` ×2):
мокаем надёжный пробник (`stub._ig_probe_foreground_pkg` / `switcher._reliable_foreground_pkg`)
вместо first-package-из-`dump_ui`. После фикса вся switcher-сюита зелёная.

## Выкатка и верификация

1. Мерж PR в `delivery-contenthunter` main → прод `git pull` (per-task spawn публишера →
   рестарт PM2 не нужен). Код приезжает под тем же kill-switch.
2. **Live-smoke** на устройстве с `IG_PICKER_FG_GUARD_ENABLED=1` (рецепт смока #19,
   task 10064): account-switch чисто, 0 `wrong_foreground`, флоу до success.
3. Если смок чист — флип прод `.env`: `IG_PICKER_FG_GUARD_ENABLED=1` (убрать `=0`).
4. **Verify 24ч:** IG success-rate не просел (≈79%); `ig_target_not_in_picker` → ~0;
   `ig_account_switcher_wrong_foreground` только на реальных foreign (единицы, не всплеск).
5. **Откат:** `IG_PICKER_FG_GUARD_ENABLED=0`.

⚠️ Флаг живёт только в `.env` autowarm — при передеплое из свежего checkout без `.env` гард
вернётся к дефолту. После включения дефолт-ON корректен (фикс устраняет over-fire), но
помнить о связности `.env`.

## Вне скоупа

- Глобальный рефактор `_detect_foreground_pkg` (подход B) — риск регрессий YT/TT.
- Подслучай «IG на переднем плане, верный пакет, но не тот экран» уже закрыт sheet-guard'ом
  (`_ig_on_account_switcher_sheet`, `IG_PICKER_SHEET_GUARD_ENABLED`).
- WP #135 (`_current_foreground_package` / pre-Шаг-5 gallery guard) — не трогаем.

## Связано

- WP #135 (`_ig_probe_foreground_pkg`, источник надёжного пробника, в «Тестировании»).
- WP #129 (паттерн `lost_streak>=2`).
- WP #121 (Samsung launcher-hijack — родственная foreground-нестабильность).
- Бэклог «8 IG-тестов красные на main» — закрывается этим фиксом.
