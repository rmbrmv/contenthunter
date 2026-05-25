# WP #121 — Launcher-hijack на foreground-гейте: укрепление recovery (итерация 1)

- **Дата:** 2026-05-25
- **WP:** #121 (Ошибка, content-hunter) — «Публикации: приложение улетает на рабочий стол (Samsung launcher) при переключении — сквозные провалы IG/YT/TT»
- **Репозиторий кода:** `autowarm-testbench` (GenGo2/delivery-contenthunter)
- **Файл:** `account_switcher.py`
- **Ветка:** `wp121-launcher-gate-recovery`

## 1. Проблема

Каждый `_switch_<platform>` начинается с гейта `_ensure_app_foregrounded(platform_key)`
(`account_switcher.py:3897`) — лёгкого pre-check'а: проверяет `topResumedActivity`,
и если на переднем плане не целевое приложение, делает `am start -W` / `monkey`,
максимум 2 попытки, без force-stop и без разбора overlay.

Когда передний план занят Samsung launcher (`com.sec.android.app.launcher`) или
рекламным sbrowser CustomTab (`com.sec.android.app.sbrowser/.customtabs...`), два
«вежливых» `am start` не вытягивают приложение. Результат — ошибка
`<prefix>_app_not_foregrounded` и падение на шаге `*_0_foreground_guard` ещё до
начала переключения аккаунта.

### Триаж (прод, последние 3 дня на 2026-05-25)

- Всего падений: 114.
- Лаунчер как **терминальная** причина: **30 — и все 30 это YouTube
  `yt_app_not_foregrounded`**. Типичная сигнатура (task 9442): recovery attempt 1 →
  фокус `com.sec.android.app.launcher`; attempt 2 → `com.sec.android.app.sbrowser`
  (выскочил рекламный CustomTab); затем `yt_app_not_foregrounded: failed after 2 retries`.
- IG `ig_target_not_in_picker` (8) и TT `tt_account_not_in_list` (20): лаунчер
  **транзиентный** (recovery срабатывает задолго до терминальной ошибки, приложение
  возвращается), терминальная причина — шаг выбора аккаунта. **Вне scope этой
  итерации** (IG-часть пересекается с переоткрытым WP #119, ведётся отдельно).

### Корень

Все три гейта (IG/YT/TT) зовут один и тот же слабый `_ensure_app_foregrounded`.
Дыра общая для трёх платформ; сегодня бьёт по YouTube из-за объёма и паттерна
с рекламным sbrowser. Сильное восстановление в коде уже **есть и протестировано** —
гейт его просто не использует.

## 2. Решение (вариант A1)

Гейт `_ensure_app_foregrounded` при обнаружении не-целевого переднего плана
делегирует подъём приложения существующему проверенному `_open_app`
(`account_switcher.py:5537`) вместо собственного `am start` ×2.

`_open_app` уже умеет всё нужное для этого кейса:

- `_dismiss_blocking_overlays` **до** первого `am start` (`:5667`): гасит sbrowser
  CustomTab (`KEYCODE_BACK` + force-stop sbrowser) и launcher foreground
  (force-stop целевого приложения → чистый cold-start);
- повторный разбор overlay на каждом из 3 ретраев `am start` (`:5686`);
- WP #105 cross-source dumpsys/uiautomator + settle-wait (`:5605`, `:5705`).

### Поведение гейта после изменения

```
_ensure_app_foregrounded(platform_key):
    expected_pkg     = _PLATFORM_PACKAGES[platform_key]
    launch_activity  = UI_CONSTANTS[platform_key]['launch_activity']
    prefix           = _PLATFORM_REASON_PREFIX[platform_key]

    # быстрый путь без изменений: уже foreground → True
    если topResumedActivity содержит expected_pkg: return True

    если SWITCHER_GATE_STRONG_RECOVERY_ENABLED (default ON):
        emit warning '<prefix>_foreground_recovery' (как сейчас, для триажа)
        ok = _open_app(expected_pkg, launch_activity, step='<prefix>_0_foreground_guard')
        если ok: return True
        # _open_app исчерпал overlay-dismiss + ретраи
    иначе:
        <старое поведение: am start ×2>

    # финал без изменений — стабильный error_code
    emit error '<prefix>_app_not_foregrounded'
    return False
```

### Сохраняем

- Финальный error-emit `<prefix>_app_not_foregrounded` при провале — чтобы не
  сломать триаж и метрики; `error_code` остаётся стабильным.
- Стартовый warning `<prefix>_foreground_recovery` — продолжает помечать кейсы
  ухода в чужой foreground.
- Сигнатура и контракт `_ensure_app_foregrounded(platform_key) -> bool` —
  без изменений (call-sites IG `:1753`, TT `:2599`, YT `:3236` не трогаем).

## 3. Kill-switch

Новый env-var по домашнему паттерну (как `IG_PICKER_FG_GUARD_ENABLED`,
`TT_SWITCH_FG_GUARD_ENABLED`):

```python
os.getenv('SWITCHER_GATE_STRONG_RECOVERY_ENABLED', '1') != '0'
```

- Default **ON**.
- `=0` → откат к старому `am start` ×2, без передеплоя.

## 4. Кросс-платформенность

Поскольку IG/YT/TT гейты используют общий `_ensure_app_foregrounded`, одно
изменение закрывает дыру на всех трёх платформах. Сегодня терминальный объём —
только YT; для IG/TT это профилактика рецидива того же механизма на гейте.

## 5. Тесты (TDD, до реализации)

Новые тесты — отдельный файл `tests/test_account_switcher_gate_strong_recovery.py`
(по конвенции, как `test_account_switcher_tt_switch_fg_guard.py`). Паттерн мока
overlay-dismiss подсмотреть в `tests/test_overlay_dismiss.py`. Существующие ассерты
на `app_not_foregrounded` живут в `tests/test_switcher_youtube.py` и
`tests/test_yt_post_switch_verify.py` — проверить, что не ломаются (контракт гейта
сохранён).

Кейсы:

1. **launcher → target.** Fake proxy: первый `topResumedActivity` = launcher, далее
   target. Ожидание: гейт вернул `True` (через `_open_app`/overlay-dismiss), не упал.
2. **sbrowser CustomTab → target.** Fake proxy отдаёт sbrowser CustomTab, затем
   target. Ожидание: `True`, в событиях есть `launch_env_cleanup`/force-stop sbrowser.
3. **kill-switch OFF.** `SWITCHER_GATE_STRONG_RECOVERY_ENABLED=0` → старая ветка
   (`am start` ×2), `_open_app` не вызывается.
4. **финальный fail.** Foreground всё время чужой → возвращает `False` и эмитит
   `<prefix>_app_not_foregrounded` (стабильность error_code).
5. **обновить** существующие тесты гейта, если они ассертят старую `am start`-логику.

Mock-proxy: имена методов 1-в-1 с `DevicePublisher` (`adb`, `log_event`, `dump_ui`,
`adb_tap`) — иначе drift проходит unit-тесты, но падает live (урок PR #52).

## 6. Деплой

- Один файл `account_switcher.py`.
- Публикатор спавнится per-task (`publisher.py <id>`) из прод-чекаута → деплой =
  обновление `.py`, **без** PM2-restart.
- Прод: path-scoped cherry-pick в `/root/.openclaw/workspace-genri/autowarm`
  (грязное parallel-tree — чужие файлы не трогаем; проверить
  `git diff base..HEAD -- account_switcher.py` на отсутствие постороннего).
- Перед отдачей пользователю — `codex review` раундами до 0 P1.

## 7. Verify

Через сутки после деплоя — динамика `yt_app_not_foregrounded` (терминальный
launcher-чанк): ожидаем спад с ~10/день к околонулю. Группировка по финальной
`meta.category` (не по `error_code`), исключая `adb_devices_unreachable` /
`process_interrupted`.

## 8. Откат

`SWITCHER_GATE_STRONG_RECOVERY_ENABLED=0`, либо при ложно-позитиве (если
`_open_app` на гейте окажется слишком тяжёлым / даст регрессию) — revert одного файла.

## 9. Out of scope (итерация 1)

- IG/TT picker-фейлы (`ig_target_not_in_picker`, `tt_account_not_in_list`) — лаунчер
  там транзиентный; отдельные механизмы (IG — переоткрытый #119).
- Mid-flow recovery-точки (не гейт) и «переснять экран + повторить текущий шаг» —
  вариант A2/«шире»; держим как следующую итерацию, если на soak останется хвост
  чужих приложений вне known-overlay списка.
- Аудит координатных тапов в gesture-strip (y≥2205) — отдельно, не пересекается
  с гейтом.
```
