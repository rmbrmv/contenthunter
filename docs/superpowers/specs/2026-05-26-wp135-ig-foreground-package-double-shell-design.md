# Design — WP #135: IG `_current_foreground_package` всегда `'unknown'` (двойной `shell` в `adb`)

**WP:** https://openproject.contenthunter.ru/wp/135
**Тип:** Ошибка
**Категория:** общий хелпер публикатора IG (`publisher_instagram.py`)
**Статус:** разведка по коду завершена 2026-05-26 (прод+стенд на `2b57fee`). Решение по раскатке — kill-switch default ON + live-smoke (выбор пользователя 2026-05-26).
**Связанные спеки:** WP #129 (`_ig_probe_foreground_pkg`), WP #119 (`_ig_guard_picker_foreground` — **другой** шаг, см. §2).

## 1. Баг (подтверждён по коду)

`adb()` (`publisher_base.py:602`) оборачивает аргумент:
```python
full = f'adb -H {host} -P {port} -s {serial} shell "{cmd}"'
```
`_current_foreground_package` (`publisher_instagram.py:856`) передаёт `cmd`, **сам начинающийся со `shell`**:
```python
out = self.adb('shell dumpsys activity activities | grep topResumedActivity')
# → на устройстве выполняется:  shell "shell dumpsys ... | grep ..."
# → sh: shell: not found  → returncode≠0 → adb() возвращает None → метод → 'unknown'
```
Метод **всегда** возвращает `'unknown'`. Тот же класс ошибки исторически был в `publisher_base.py:3053` (cleanup no-op из-за `adb('shell rm ...')`). Regex-парсер метода (`r'ActivityRecord\{[^}]*?\s([\w.]+)/'`, стр. 870) **идентичен** проверенному в бою `_ig_probe_foreground_pkg` (WP #129, стр. 904) — значит после исправления команды парсинг уже валидирован.

## 2. Что НЕ так в исходной формулировке задачи (важно)

И OpenProject-описание WP #135, и бриф автоворкера утверждают: *«стр. 2251 — pre-picker guard перед выбором аккаунта (`ig_external_app_foreground`) — это домен #119»*. **Это неверно.** Разведка по фактическому коду:

| | Guard в publisher (стр. 2269) | Guard WP #119 (account_switcher.py:1717) |
|---|---|---|
| Файл/класс | `publisher_instagram.py` / DevicePublisher | `account_switcher.py` / AccountSwitcher |
| Шаг | **Шаг 5 — галерея, выбор видео** (pre-picker = picker *галереи*) | **`ig_4_pick_account` — выбор аккаунта** (picker *аккаунтов*) |
| Метод fg | `_current_foreground_package` (битый) | `_detect_foreground_pkg` (стр. 3747, **корректный** — `dump_ui` `package="..."` + fallback bare-dumpsys, без двойного shell) |
| Поведение на чужом fg | fail-fast (`return False`, `ig_external_app_foreground`) | relaunch IG + ре-навигация (`_ensure_app_foregrounded`) |
| Kill-switch | нет (добавляется этой WP) | `IG_PICKER_SHEET_GUARD_ENABLED` (default ON) |

Это **разные шаги в разных файлах, последовательно разнесённые** (выбор аккаунта в свитчере → затем флоу публикации в публикаторе). Двойного foreground-guard'а на одном шаге нет; двойного force-stop / двойной ре-навигации быть не может. **Пересечения нет — убирать/консолидировать нечего.** WP #119 фикс не затрагивает.

Слова «picker» в обоих местах (галерейный picker vs picker аккаунтов) и спровоцировали путаницу. Фиксируем это комментарием в коде (§4.4), чтобы не повторилось.

## 3. Что разбудит фикс

Три потребителя битого хелпера в `publisher_instagram.py`:

| Точка | Назначение | Сейчас (`'unknown'`) | После фикса |
|---|---|---|---|
| **стр. 1438** `_ig_handle_edits_promo_at_picker` (вызов в 4 точках: gallery_open / gallery_select / editor_loop_1/2) | fail-fast при перехвате Google Play | мёртв (`'unknown'≠'com.android.vending'`) | честный fail-fast `ig_edits_promo_playstore_hijack` строго на `com.android.vending` |
| **стр. 2269** `_ig_classify_pre_picker_state` | guard перед Шагом 5 | ветка `external_app` мертва (стр. 479 явно исключает `'unknown'`); ветки templates/story/editor **уже работают** (по UI-маркерам) | оживает только ветка `external_app` → fail-fast `ig_external_app_foreground` |
| **стр. 2252** | логирование пакета в meta `ig_gallery_button_not_found` | пишет `'unknown'` | пишет реальный пакет (**чистая observability, поведение не меняется**) |

**Ключевое уточнение к оценке риска:** обе оживающие *поведенческие* ветки — это **fail-fast (`return False` + честный error_code)**, без force-stop и без relaunch (relaunch живёт только в уже работающем switcher-guard'е WP #119). Худший случай: задача, которая всё равно падала бы ниже по флоу, теперь падает раньше с точным кодом вместо размытого downstream. Главный остаточный риск — **false-positive**: код этих веток ни разу не исполнялся в проде, поэтому реальные значения fg-пакета на gallery/edits-шагах в happy-path неизвестны (теоретически — транзиентный системный пакет/диалог в момент пробы → ложный `external_app` fail). Это и закрывает kill-switch + live-smoke.

## 4. Design

### 4.1 Фикс хелпера — делегирование в проверенный probe (безусловно)

`_current_foreground_package` и `_ig_probe_foreground_pkg` после фикса функционально идентичны (тот же regex, тот же контракт `'unknown'` при ошибке). Делаем `_current_foreground_package` тонким алиасом проверенного в бою (WP #129, live-smoked) `_ig_probe_foreground_pkg` — единый источник истины, исключаем повторный дрейф:

```python
def _current_foreground_package(self) -> str:
    """Foreground package (e.g. 'com.instagram.android'); 'unknown' при ошибке.

    [WP #135] Раньше слал 'shell dumpsys ...' в adb(), который сам оборачивает
    в shell "..." → двойной shell → всегда 'unknown'. Делегируем в проверенный
    _ig_probe_foreground_pkg (WP #129, bare-dumpsys, тот же regex).
    """
    return self._ig_probe_foreground_pkg()
```
И снимаем из docstring `_ig_probe_foreground_pkg` устаревшее предупреждение «НЕ используем _current_foreground_package» (теперь это его канонический бэкенд).

*Альтернатива (если ревью предпочтёт минимальный дифф):* заменить только команду на стр. 866 на `'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"'`. Делегирование предпочтительнее — убирает дубль.

### 4.2 Kill-switch на оживающее fail-fast-поведение

Module-level helper (паттерн `account_switcher.py:277`):
```python
def _ig_pre_picker_fg_guard_enabled() -> bool:
    return os.environ.get('IG_PRE_PICKER_FG_GUARD_ENABLED', '1') != '0'
```
Default ON. `=0` → мгновенный откат к старому (бездействующему) поведению, без передеплоя.

### 4.3 Точки врезки kill-switch (селективно — только оживающие ветки)

**(a) Pre-picker guard, стр. 2269** — при выключенном kill-switch передаём в классификатор `'unknown'`, что воспроизводит ровно старое поведение (ветка `external_app` молчит, т.к. стр. 479 исключает `'unknown'`), а UI-маркерные ветки templates/story/editor продолжают работать (они не зависят от пакета):
```python
guard_ui = self.dump_ui()
guard_pkg = (self._current_foreground_package()
             if _ig_pre_picker_fg_guard_enabled() else 'unknown')
guard_result = _ig_classify_pre_picker_state(guard_ui, guard_pkg)
```

**(b) Play-Store-hijack, стр. 1438** — gate всей fail-fast-ветки:
```python
if _ig_pre_picker_fg_guard_enabled() and \
        self._current_foreground_package() == 'com.android.vending':
    ... fail-fast ig_edits_promo_playstore_hijack ...
```
При выключенном — переходим к обычному dismiss-баннеру (старое поведение).

**(c) Логирование, стр. 2252** — **НЕ** гейтим: пусть всегда пишет реальный пакет. Это observability, поведение флоу не меняет, и именно эти логи валидируют парсер на смоуке/проде.

`_ig_classify_pre_picker_state` остаётся чистой функцией (не читает env) — тестируемость сохранена, kill-switch применяется только на стороне вызова.

### 4.4 Cross-ref комментарий (закрывает путаницу из §2)

У pre-picker guard (стр. ~2263) добавить:
```python
# NB: это picker ГАЛЕРЕИ (Шаг 5, выбор видео) в публикаторе, НЕ account-picker
# WP #119 (_ig_guard_picker_foreground в account_switcher.py, шаг ig_4_pick_account).
# Разные шаги/файлы — guard'ы не дублируют и не конфликтуют (WP #135 §2).
```

### 4.5 Что НЕ трогаем

- `_ig_guard_picker_foreground` / `_detect_foreground_pkg` (WP #119, account_switcher.py) — корректны, другой шаг.
- `_ig_probe_foreground_pkg` (WP #129) — становится канонической реализацией, логику не меняем.
- UI-маркерные ветки `_ig_classify_pre_picker_state` (templates/story/editor) — работают, не гейтим.
- `_ig_wait_upload_fg_step` (WP #129 wait-loop) — отдельный kill-switch `IG_WAIT_UPLOAD_FG_GUARD_ENABLED`, не затрагивается.

## 5. Тесты (`test_*`, fake-proxy)

| Сценарий | Ожидание |
|---|---|
| `adb` отдаёт валидный dumpsys с IG | `_current_foreground_package() == 'com.instagram.android'` (баг исправлен) |
| `adb` → None / мусор | `'unknown'` (контракт сохранён) |
| Play Store fg + guard ON | `_ig_handle_edits_promo_at_picker` → `'failed'`, эмит `ig_edits_promo_playstore_hijack` |
| Play Store fg + guard OFF | НЕ fail-fast → путь dismiss-баннера (старое поведение) |
| fg=`com.google.android.youtube` + guard ON | pre-picker → `external_app` → `return False`, `ig_external_app_foreground` |
| fg=YouTube + guard OFF | guard_pkg='unknown' → mode='ok' → флоу продолжается (старое поведение) |
| UI-маркер templates/story (любой kill-switch) | fail-fast `ig_camera_mode_drift_to_*` — не зависит от kill-switch |
| fg=IG + guard ON | mode='ok', продолжаем |

Анти-дрейф (урок PR #52): перед тестами сверить имена методов fake-proxy с реальным `DevicePublisher` — `adb`, `dump_ui`, `log_event`, `_save_debug_artifacts`, `_safe_kb_probe`. Ключевые тесты — kill-switch ON↔OFF на обеих оживающих ветках.

## 6. Live-smoke (обязателен, §выбор пользователя)

Код этих веток **ни разу не исполнялся** в проде → смоук на стенде до прод-деплоя:
1. Реальные IG-публикации на стенде (phone #19 / #171), kill-switch ON.
2. По логам (стр. 2252 + meta guard'а) подтвердить, что `_current_foreground_package` на gallery/edits-шагах в happy-path возвращает `com.instagram.android` — **нет ложного `external_app` fail-fast**, success-rate публикаций не просел.
3. Опционально форсировать Play-Store-перехват (открыть `com.android.vending` перед шагом) → подтвердить, что fail-fast `ig_edits_promo_playstore_hijack` срабатывает корректно.

## 7. Деплой

- Python-публикатор спавнится свежим на каждую задачу → **PM2 restart не нужен**.
- Worktree + atomic commit + зелёный pytest перед merge (parallel-sessions practice).
- `codex review` спека → плана → диффа, раундами до 0 P1/P2 (стандартная практика).
- Раскатка: cherry-pick в prod autowarm (`/root/.openclaw/workspace-genri/autowarm/`), auto-push hook → GenGo2/delivery-contenthunter.
- Kill-switch `IG_PRE_PICKER_FG_GUARD_ENABLED=0` — аварийный откат.
- Прод-мониторинг 24ч: частота `ig_external_app_foreground` + `ig_edits_promo_playstore_hijack` (ожидаем единичные, не всплеск) + IG publish success-rate (не должен просесть = нет false-positive).

## 8. Риски

| Риск | Митигация |
|---|---|
| **False-positive** `external_app` (транзиентный системный пакет/диалог на пробе → ложный fail публикации, которая бы прошла) | Live-smoke валидирует реальные fg-пакеты до прода; kill-switch = мгновенный откат; парсер тот же, что у проверенного WP #129 probe |
| Play-Store fail-fast ложно срабатывает | Матч строго на `com.android.vending` (узкий), под kill-switch |
| Регрессия успешных публикаций | Смоук на стенде + 24ч success-rate мониторинг; default ON оставляет escape-hatch |
| Параллельные сессии правят `publisher_instagram.py` | Worktree + atomic commit + зелёный pytest перед merge |
| docstring `_ig_probe_foreground_pkg` устареет (предупреждение про баг) | Обновляется в §4.1 в том же диффе |

## 9. Связанные сущности

- WP #129 — `_ig_probe_foreground_pkg` (bare-dumpsys probe), становится канонической реализацией.
- WP #119 (PR #102/#104) — `_ig_guard_picker_foreground` (account_switcher.py, шаг `ig_4_pick_account`). **Другой шаг, не затрагивается** (§2).
- `publisher_base.py:3053` — исторический тот же класс бага (двойной shell в cleanup).
