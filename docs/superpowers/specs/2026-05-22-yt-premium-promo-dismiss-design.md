# WP #132 (подсигнатура A) — YT create-menu: снятие промо YouTube Premium

**Дата**: 2026-05-22
**WP**: [OpenProject #132](https://openproject.contenthunter.ru/work_packages/132)
**Связанные**:
- WP #87 (`yt-create-menu-fg-guard`, SHIPPED 2026-05-19) — тот же шаг `yt_6`, тот же метод `_tap_plus_and_verify`; добавил Layer B/C foreground-guard.
- WP #106 (`tt-profile-promo-dismiss`, SHIPPED 2026-05-19) и WP #67 Layer 2 — тот же паттерн «распознать promo-модалку → закрыть → re-verify».
- WP #74 (`yt-foreign-foreground-guard`) — родственный whitelist/escalation-подход.

**Evidence**: `docs/evidence/2026-05-22-yt-publish-fails-triage.md` (ветка `docs/yt-triage-2026-05-22`).

## 1. Контекст и симптом

За последние 24 часа топ реальная YouTube-ошибка — `yt_create_menu_not_reached` (5 из 8 реальных падений, 62%; PM2-шум `process_interrupted` и сетевой `adb_devices_unreachable` исключены). По скринкастам корзина неоднородна — две подсигнатуры:

- **A. Интерстишл «YouTube Premium»** (2 из 5 — задачи 9084, 9253; 9253 — сегодня). Эта спека — про неё.
- **B. Всплывает камера TikTok** (3 из 5 — 9025, 9092, 9108). Вне scope, отдельная задача.

Поток падения (подсигнатура A): account switch **успешен** (бот доходит до профиля целевого канала), затем тап «+» (FAB создания), но поверх create-flow вылезает **полноэкранное промо подписки YouTube Premium**. `foreground_pkg` остаётся `com.google.android.youtube`, поэтому Layer C fg-guard (WP #87) не срабатывает. `_tap_plus_and_verify` со `strict_verify=True` не находит ни одного `editor_triggers` → `_fail(step='yt_6_create_menu_no_triggers')` → `error_code='yt_create_menu_not_reached'`.

Наблюдаемые варианты промо (из скринкастов):

| задача | заголовок/маркеры | CTA подписки | закрытие |
|---|---|---|---|
| 9084 | «Оформить YouTube Premium», «Весь YouTube без рекламы», «2 пробных месяца за 0 KZT» | «2 месяца за 0 KZT» | крестик ✕ слева сверху |
| 9253 | «Попробуйте семейную подписку YouTube Premium», «YouTube без рекламы» | «Попробуйте на 1 месяц» | крестик ✕ справа сверху |

**Почему существующее снятие не помогает:**
1. `_dismiss_overlays(cfg['dismiss_buttons'], ...)` вызывается только на старте (`yt_1_dismiss`, account_switcher.py:3028/3040), а **не** внутри `_tap_plus_and_verify` (шаг `yt_6`). Промо появляется уже после тапа «+».
2. Даже если бы вызывалось: `_dismiss_overlays` ищет clickable-кнопку с текстом из whitelist'а. На интерстишле Premium закрытие — это **крестик ✕ (иконка)**, а единственные текстовые кнопки — это CTA подписки («Попробуйте на 1 месяц» / «2 месяца за 0 KZT»). Тапать их **нельзя** — это оформление платной подписки.
3. Layer C fg-guard ловит только смену foreground-пакета; здесь foreground остаётся YouTube.

## 2. Цель

Когда на шаге `yt_6` create-меню не найдено **и** распознан интерстишл YouTube Premium — закрыть его безопасно (аппаратной кнопкой Back, без тапов по экрану), переоткрыть меню и довести публикацию (recovery). Если промо жёстко гейтит «+» и не снимается в рамках бюджета — упасть с **отдельным** `error_code`, отделяющим подсигнатуру A от общего `yt_create_menu_not_reached`.

**Success criteria:**
- Задачи с промо Premium (тип 9084/9253) при повторе проходят шаг create-меню и публикуются.
- Доля `yt_create_menu_not_reached` снижается; «настоящие» промо-кейсы либо recovered, либо видны под `yt_create_menu_premium_blocking` (чистый триаж).
- **0 тапов по CTA подписки** — закрытие только через Back. Нулевой риск случайной платной подписки.
- 0 регрессий в существующих тестах switcher'а; happy-path и IG/TT не затронуты (recovery живёт только в ветке промаха при `strict_verify`).

## 3. Архитектура

Зеркалит проверенный паттерн WP #106 / WP #67 Layer 2: **чистый детектор-функция + instance-метод recovery**, всё под kill-switch. Точечная врезка в `_tap_plus_and_verify`, файл `account_switcher.py`.

### 3.1. Kill-switch helper (module-level, рядом с `_guard_enabled`, ~line 217)

```python
def _premium_dismiss_enabled() -> bool:
    """[WP #132] Kill-switch для снятия промо YouTube Premium на yt_6.
    Default ON. YT_PREMIUM_DISMISS_ENABLED=0 → откат к legacy (fail сразу).
    """
    return os.environ.get('YT_PREMIUM_DISMISS_ENABLED', '1') != '0'
```

### 3.2. Whitelist-маркеры (module-level constant)

```python
# [WP #132 — 2026-05-22] Маркеры интерстишла YouTube Premium на шаге create-меню.
# Match требует ОБА: бренд-маркер И специфичный апселл-CTA — защита от ложного
# срабатывания (одно слово «Premium» где-то в дереве не пройдёт без CTA).
# Расширяется по evidence. Сверяется case-insensitive по сырому XML dump'а.
#
# Бренд = одно слово 'premium' (а НЕ непрерывное 'youtube premium'): в dump'е
# «YouTube» и «Premium» могут оказаться в разных узлах с XML-тегами между ними,
# и непрерывная подстрока не сматчится. Точность обеспечивает не бренд, а
# специфичный апселл-CTA из второго списка (эти строки уникальны для промо).
_YT_PREMIUM_BRAND_MARKERS: tuple[str, ...] = (
    'premium',
)
_YT_PREMIUM_UPSELL_MARKERS: tuple[str, ...] = (
    'попробуйте на 1 месяц',
    'месяца за 0',
    'за 0 kzt',
    'без рекламы',
    'семейную подписку',
    'оформить youtube premium',
    'пробных месяца',
)
```

> **Риск/валидация:** маркеры выведены из скринкастов (визуальный текст), а
> не из реального XML-dump'а. План **обязан** включить захват одного живого
> dump'а интерстишла Premium (с прод-устройства или из сохранённого артефакта
> упавшей задачи) ДО финализации списков — подтвердить, что строки реально
> присутствуют в `text`/`content-desc` узлов в ожидаемом виде, и при
> необходимости уточнить. Синтетический XML в юнит-тестах не валидирует это
> допущение.

### 3.3. Чистый детектор (module-level function)

```python
def _yt_is_premium_promo(xml: str) -> bool:
    """True если dump похож на полноэкранный интерстишл YouTube Premium.
    Требует И бренд-маркер И апселл-CTA (см. константы). Pure-функция над
    строкой dump'а — тестируется в изоляции.
    """
    if not xml:
        return False
    low = xml.lower()
    has_brand = any(m in low for m in _YT_PREMIUM_BRAND_MARKERS)
    has_upsell = any(m in low for m in _YT_PREMIUM_UPSELL_MARKERS)
    return has_brand and has_upsell
```

> Примечание: детектор смотрит на сырой XML (как существующий `strict_verify` legacy-substring-путь), что устойчиво к мелким различиям в структуре узлов. Точность обеспечивается требованием двух независимых маркеров.

### 3.4. Recovery-метод (instance-метод AccountSwitcher)

```python
def _yt_dismiss_premium_promo_and_retap(self, cfg: dict, final_step: str) -> bool:
    """[WP #132] Закрыть промо Premium через Back, переоткрыть «+», re-verify.
    Возвращает True если после recovery editor_triggers найдены.
    Безопасно: только Back, без тапов по экрану (нет риска подписки).
    """
    self.p.log_event('account_switch', 'yt_premium_promo_detected',
        meta={'category': 'yt_premium_promo_detected', 'step': final_step})

    # 1) До 2 Back чтобы снять промо. Отслеживаем, что промо реально ушло.
    MAX_BACK = 2
    promo_gone = False
    for i in range(MAX_BACK):
        self.p.adb('input keyevent 4')
        time.sleep(POST_TAP_WAIT_S + 0.5)
        xml = self.p.dump_ui(retries=1)
        # [codex P1] Пустой/неудачный dump НЕ доказывает, что промо ушло
        # (transient ADB / FLAG_SECURE) — промо могло остаться на экране.
        # promo_gone=True только при ВАЛИДНОМ dump'е без промо. Иначе —
        # следующий Back, а после бюджета сработает fail-fast ниже (без тапа).
        if xml and not _yt_is_premium_promo(xml):
            promo_gone = True
            break

    # [codex P1] КРИТИЧНО: если промо всё ещё на экране после бюджета Back —
    # НЕ тапаем (фолбэк-coords «+» = (540,2137) попадёт по видимому промо и
    # может нажать CTA подписки). Fail-fast ДО любого тапа.
    if not promo_gone:
        self.p.log_event('warning', 'yt_premium_promo_dismiss_failed',
            meta={'category': 'yt_premium_promo_dismiss_failed', 'step': final_step,
                  'reason': 'promo_still_visible_after_back_budget'})
        return False

    # [codex P2] Промо ушло, но Back мог увести foreground в launcher/другой app.
    # Перед ре-тапом убедиться, что foreground всё ещё YouTube — иначе фолбэк-coords
    # «+» ударит по чужому экрану (непреднамеренный тап). Если drift — попытка
    # вернуть YouTube через существующий Layer C recovery; не вышло → fail-fast без тапа.
    fg = self._detect_foreground_pkg()
    if fg and fg != cfg['package']:
        if not self._yt_ensure_foreground(
                cfg, f'{final_step}_premium_post_back_fg_recovery'):
            self.p.log_event('warning', 'yt_premium_promo_dismiss_failed',
                meta={'category': 'yt_premium_promo_dismiss_failed', 'step': final_step,
                      'reason': 'foreground_drift_after_back', 'foreground_pkg': fg})
            return False

    # 2) Промо ушло и YouTube в foreground → безопасно ре-тапнуть «+».
    plus = cfg['plus_button']
    ui = self.p.dump_ui(retries=1)
    tapped = self.p.tap_element(ui, plus['desc'], clickable_only=True) if ui else False
    if not tapped:
        self.p.adb_tap(*plus['coords'])
    time.sleep(POST_TAP_WAIT_S + 1.0)

    # 3) Ре-проверка editor_triggers (exact-match, как strict_verify в основном пути).
    ui2 = self.p.dump_ui(retries=1)
    hits = self._exact_match_triggers(ui2, cfg['editor_triggers'])  # см. 3.6
    if hits:
        self.p.log_event('account_switch', 'yt_premium_promo_dismissed',
            meta={'category': 'yt_premium_promo_dismissed', 'step': final_step,
                  'hits': hits})
        return True
    self.p.log_event('warning', 'yt_premium_promo_dismiss_failed',
        meta={'category': 'yt_premium_promo_dismiss_failed', 'step': final_step})
    return False
```

### 3.5. Врезка в `_tap_plus_and_verify` (ветка `if strict_verify and not hits:`, ~line 4566)

```python
if strict_verify and not hits:
    # [WP #132] До fail — попытка снять промо YouTube Premium и довести.
    if _premium_dismiss_enabled() and _yt_is_premium_promo(ui2):
        if self._yt_dismiss_premium_promo_and_retap(cfg, final_step):
            return self._ok(final_step, already_matched=already_matched)
        # промо распознано, но снять не удалось → отдельный код
        fail_step = f'{final_step}_premium_blocking'
        self.p.log_event('warning', f'{fail_step}: Premium promo not dismissable',
            meta={'category': 'yt_create_menu_premium_blocking', 'step': fail_step})
        return self._fail(
            f'{final_step}: интерстишл YouTube Premium не снялся (Back ×{2})',
            step=fail_step)
    # не промо → существующий путь (yt_create_menu_not_reached, в т.ч. подсигнатура B)
    fail_step = f'{final_step}_no_triggers'
    ...  # без изменений
```

### 3.6. Рефактор exact-match (минимальный, по необходимости)

Текущая exact-match-логика (WP #88) встроена inline в `_tap_plus_and_verify` (account_switcher.py:4545-4557). Чтобы переиспользовать её в recovery-методе без дублирования, вынести в маленький приватный helper `_exact_match_triggers(xml, triggers) -> list` и вызвать из обоих мест. Это единственное изменение существующего кода вне ветки промаха; поведение основного пути не меняется (та же логика, просто извлечена).

## 4. Безопасность

- **Закрытие только Back** — ни одного `adb_tap` по содержимому промо → невозможно случайно оформить платную подписку.
- **Ре-тап только при подтверждённо безопасном состоянии.** Перед любым тапом «+» выполняются ТРИ гарда (никаких тапов, если хоть один не пройден):
  1. *(codex P1)* промо реально ушло — подтверждено **валидным** dump'ом; промо ещё на экране после бюджета Back → `return False` без тапа;
  2. *(codex P1)* пустой/неудачный dump НЕ считается доказательством снятия (transient ADB / FLAG_SECURE) → трактуется как «промо может быть на экране» → без тапа;
  3. *(codex P2)* foreground всё ещё YouTube — Back мог увести в launcher; при drift'е попытка `_yt_ensure_foreground`, не вышло → `return False` без тапа.
- **Бюджет**: ≤2 Back + 1 ре-тап «+» + 1 ре-проверка. Нет бесконечного цикла, если YouTube жёстко гейтит «+».
- **Детектор требует 2 независимых маркера** (бренд + апселл) → низкий риск ложного срабатывания на легитимном контенте.
- Recovery живёт **только** в ветке `strict_verify and not hits` → нулевое влияние на happy-path и на IG/TT (там `strict_verify=False`).

## 5. Наблюдаемость

Новые события (`meta.category`): `yt_premium_promo_detected`, `yt_premium_promo_dismissed`, `yt_premium_promo_dismiss_failed`.
Новый `error_code`: **`yt_create_menu_premium_blocking`** (промо распознано, recovery не удался).

## 6. Тесты (TDD)

Файл: новый `tests/test_yt_premium_promo_dismiss.py` (+ при необходимости дополнить `tests/test_yt_create_menu_strict_verify.py`).

**Юнит — `_yt_is_premium_promo`:**
- позитив: синтетический XML по мотивам 9084 («Оформить YouTube Premium» + «2 пробных месяца за 0 KZT» + «без рекламы») и 9253 («YouTube Premium» + «Попробуйте на 1 месяц» + «семейную подписку»);
- негатив: реальный create-menu dump с `editor_triggers`; узел с «Premium» в названии видео без апселл-CTA; пустой/FLAG_SECURE dump.

**Метод — `_yt_dismiss_premium_promo_and_retap`** с фейк-прокси (имена методов 1-в-1 как у `DevicePublisher`: `adb`, `dump_ui`, `tap_element`, `adb_tap`, `log_event` — урок mock-proxy-drift):
- сценарий recovery: dump#1 промо → после Back dump#2 не промо → ре-тап → dump#3 с триггерами → возвращает True, зафиксирован ровно 1 ре-тап «+», событие `yt_premium_promo_dismissed`;
- сценарий «промо не уходит» (жёсткий гейт): все dump'ы промо → возвращает False, событие `yt_premium_promo_dismiss_failed` с `reason='promo_still_visible_after_back_budget'`, и **строго 0 вызовов `adb_tap`/`tap_element`** (гард codex P1 — никаких тапов по видимому промо).
- сценарий «пустой dump после Back» (transient ADB / FLAG_SECURE): `dump_ui` возвращает None/'' на всех попытках → `promo_gone` остаётся False → возвращает False, **0 вызовов `adb_tap`/`tap_element`** (пустой dump не считается доказательством снятия — гард codex P1).
- сценарий «foreground-drift после Back» (стаб `_detect_foreground_pkg` → launcher/другой app, `_yt_ensure_foreground` → False): промо ушло, но foreground не YouTube → возвращает False, событие с `reason='foreground_drift_after_back'`, **0 вызовов `adb_tap`/`tap_element`** (гард codex P2 — не тапаем по чужому экрану).

**Интеграция — `_tap_plus_and_verify`:**
- промо + recovery успешен → `_ok`;
- промо + recovery провалился → `_fail` со step `*_premium_blocking` (код `yt_create_menu_premium_blocking`);
- не промо → существующий `*_no_triggers` (`yt_create_menu_not_reached`) без изменений;
- kill-switch `YT_PREMIUM_DISMISS_ENABLED=0` → recovery не запускается, поведение legacy.

Цель — pytest зелёный, 0 регрессий в существующих switcher-тестах.

## 7. Деплой

Изменения в одном файле `account_switcher.py` (autowarm-репо). Разработка — НЕ напрямую в `/root/.openclaw/workspace-genri/autowarm` (там post-commit auto-push в прод): вести в изолированном клоне/worktree autowarm-репо или testbench; деплой — копией файла, подхват per-task spawn (без PM2 restart, как недавние YT-фиксы #113/#73). Kill-switch `YT_PREMIUM_DISMISS_ENABLED` наготове. pytest зелёный до коммита.

## 8. Вне scope

Подсигнатура B (всплытие камеры TikTok на шаге «+», задачи 9025/9092/9108) — отдельная разведка/задача. Здесь не трогаем.
