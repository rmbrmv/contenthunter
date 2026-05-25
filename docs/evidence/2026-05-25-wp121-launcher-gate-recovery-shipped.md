# WP #121 — Launcher-hijack на foreground-гейте: SHIPPED + DEPLOYED 2026-05-25

**Итерация 1 (вариант A1).** Спека: `docs/superpowers/specs/2026-05-25-wp121-launcher-hijack-gate-recovery-design.md`. План: `docs/superpowers/plans/2026-05-25-wp121-launcher-hijack-gate-recovery.md`.

## Триаж (прод, последние 3 дня на 2026-05-25)

- Всего падений: 114 (testbench/canary исключены).
- **Лаунчер как ТЕРМИНАЛЬНАЯ причина: 30 — все 30 = YouTube `yt_app_not_foregrounded`.**
  Сигнатура (task 9442): `yt_foreground_recovery` attempt 1 → фокус `com.sec.android.app.launcher`; attempt 2 → `com.sec.android.app.sbrowser` (рекламный CustomTab); → `yt_app_not_foregrounded: failed after 2 retries`; fail на `yt_0_foreground_guard`.
- IG `ig_target_not_in_picker` (8) и TT `tt_account_not_in_list` (20): лаунчер транзиентный (recovery срабатывает задолго до терминальной ошибки) → ВНЕ scope (методологический caveat WP подтверждён: «в events есть launcher» сильно завышает).

## Корень

Все три гейта (IG/YT/TT) зовут общий слабый `_ensure_app_foregrounded` (`account_switcher.py:3897`): `am start`/`monkey` ×2, без force-stop, без overlay-dismiss. Launcher и sbrowser CustomTab им не вытягиваются. Рядом `_open_app` (`:5537`) уже умеет всё нужное (force-stop sbrowser/launcher через `_dismiss_blocking_overlays`, ретраи `am start`, WP#105 cross-source) — гейт его не использовал.

## Фикс (A1)

При не-целевом foreground гейт делегирует подъём в `_open_app`. Один файл. Kill-switch `SWITCHER_GATE_STRONG_RECOVERY_ENABLED` (default ON; `=0` → старое поведение, сохранено байт-в-байт). Контракт функции и `*_app_not_foregrounded` error_code не изменены, call-sites не тронуты. Кроссплатформенно по построению.

## Тесты

- 4 новых strong-теста: `tests/test_account_switcher_gate_strong_recovery.py` (launcher→target, sbrowser→target, kill-switch off → legacy, финальный fail → `yt_app_not_foregrounded`).
- 2 legacy гейт-теста (`test_switcher_youtube.py`) переведены на kill-switch OFF; happy-path тест не тронут.
- Полный switcher-набор: **181/181 passed**.
- spec-compliance review ✅, code-quality review **Approved** (0 Critical/Important), codex review 0 P1.

## Деплой

- PR **#101** (GenGo2/delivery-contenthunter) squash-merged → `origin/main` `cf8e4cb`.
- Прод `/root/.openclaw/workspace-genri/autowarm`: fast-forward на `cf8e4cb` (без коммита → post-commit auto-push hook не сработал; дифф от базы = ровно 3 моих файла). Публикатор спавнится per-task → новый код без PM2-restart.

## Verify (ожидается)

Через сутки (26.05): динамика `yt_app_not_foregrounded` (терминальный launcher-чанк) — спад с ~10/день к околонулю. Группировка по финальной `meta.category`, исключая `adb_devices_unreachable`/`process_interrupted`.

**Откат:** `SWITCHER_GATE_STRONG_RECOVERY_ENABLED=0` (env) либо revert одного файла.

## Backlog (следующие итерации, если останется хвост)

- **A2 / mid-flow recovery:** «переснять экран + повторить текущий шаг» в НЕ-гейтовых recovery-точках (не только при старте switch) — для чужих приложений вне known-overlay списка.
- **Gesture-strip аудит:** координатные тапы с y≥2205 (Samsung home-strip) выкидывают app в launcher; в публикаторах прямых тапов нет, но `publisher_instagram.py:_dismiss_ig_edits_promo` свайпает до y=2300 — проверить отдельно.
- **IG/TT picker-фейлы:** `ig_target_not_in_picker` (IG — переоткрытый WP #119, wrong-screen-внутри-IG), `tt_account_not_in_list` — отдельные механизмы, не launcher-терминальные.
