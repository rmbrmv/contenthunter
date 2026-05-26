# Evidence — WP #135 SHIPPED+DEPLOYED 2026-05-26

**Что:** IG `_current_foreground_package` всегда возвращал `'unknown'` (двойной `shell` в `adb()`) → 2 fail-fast-защиты IG спали. Пришло как вопрос автоворкера (`contenthunter_autoexec/briefs/135`).

**Цикл:** brainstorm → spec → plan (оба codex-clean) → subagent-driven (implementer + spec-review ✅ + quality-review Approved после I1 DRY-фикса) → live-smoke → deploy.

## Решение
- `_current_foreground_package` делегирует в проверенный `_ig_probe_foreground_pkg` (WP #129, bare-dumpsys, тот же regex).
- Обе ожившие ветки (Play-Store-hijack + `external_app` pre-picker) через wrapper `_ig_pre_picker_guard_pkg()` под единым kill-switch `IG_PRE_PICKER_FG_GUARD_ENABLED` (default ON).
- Логирование пакета не гейтится (observability).

## Корректировка посылки (важно)
И OpenProject-описание, и бриф автоворкера утверждали, что guard стр.~2251 = «домен #119» и фикс создаст дубль. **По коду неверно:** guard публикатора = picker ГАЛЕРЕИ (Шаг 5, выбор видео, `publisher_instagram.py`); guard #119 (`_ig_guard_picker_foreground` в `account_switcher.py`, корректный `_detect_foreground_pkg`) = picker АККАУНТОВ (`ig_4_pick_account`). Разные шаги/файлы → пересечения нет, консолидировать нечего.

## Тесты
68 passed. Старые `TestCurrentForegroundPackage` баг не ловили (мокают `adb`, игнорят команду) → добавлен `test_does_not_double_wrap_shell` (ассерт на саму команду) + `TestPrePickerFgGuardKillSwitch` (4) + playstore-off.

## Live-smoke (БД общая прод/стенд → без publish-задачи, только чтение foreground)
Устройство `RF8Y80ZTVFZ` / raspberry 1 (host 147.45.251.85, порт 15037):

| Проверка | Результат |
|---|---|
| OLD-команда (`shell "shell dumpsys…"`) | `sh: shell: inaccessible or not found` — баг воспроизведён на железе |
| NEW-команда (bare dumpsys) | реальный `topResumedActivity` |
| Python `_current_foreground_package()` (worktree, IG foreground) | `com.instagram.android` |
| Python из **прод-пути** (после деплоя) | реальный пакет (не `'unknown'`) |

## Деплой
- Merge ветки `feat/wp135-ig-fg-double-shell` → main → push: delivery-contenthunter `2d994db`.
- Прод `/root/.openclaw/workspace-genri/autowarm` ff-merge до `2d994db`; PM2 autowarm id=35 exec cwd = прод-путь (drift проверен).
- Python-публикатор спавнится свежим на задачу → **PM2 restart не нужен**.
- Kill-switch `IG_PRE_PICKER_FG_GUARD_ENABLED=0` — аварийный откат.

## Осталось (verify 24ч)
Динамика `ig_external_app_foreground` + `ig_edits_promo_playstore_hijack` (ждём единичные, не всплеск) + IG publish success-rate (не должен просесть = нет false-positive) → затем OpenProject «Тестирование» → «Готово».

Спека/план: `docs/superpowers/specs|plans/2026-05-26-wp135-*`.
