# WP#134 — yt_6 «камера TikTok» = камера YouTube Shorts — evidence

**Date:** 2026-05-26
**WP:** OpenProject #134 (подсигнатура B триажа #132)
**Repo фикса:** `GenGo2/delivery-contenthunter` (PR #107, прод `1b8c677`)
**Статус:** SHIPPED+DEPLOYED, OpenProject → «Тестирование», ждёт 24ч verify

## TL;DR

Премиса задачи («после «+» всплывает камера TikTok») **опровергнута разведкой**: на записях экрана это нативная **камера YouTube Shorts**, а не TikTok. Шаг свича `yt_6` фатально падал (`yt_create_menu_not_reached`) до устойчивого пути загрузки `Shell_UploadActivity`. Фикс — soft-pass `yt_6`, когда после «+» foreground всё ещё YouTube.

## Разведка (что было на самом деле)

3 падения-доказательства из задачи (разные устройства/аккаунты):

| task | raspberry | account | error_code |
|---|---|---|---|
| 9025 | 1 | SmartEstateSpb | yt_create_menu_not_reached |
| 9092 | 5 | DriveSAndDeliver | yt_create_menu_not_reached |
| 9108 | 10 | AromaLuxCollection | yt_create_menu_not_reached |

Просмотр записей экрана (`save.gengo.io/.../task{9025,9092,9108}_fail_*.mp4`) — на всех трёх финальный экран это **камера YouTube Shorts**: вкладки «Видео \| Shorts \| Эфир \| Запись», «♪ Добавить трек», таймер «15», красная кнопка записи, иконка ▷ YouTube. **Никакого TikTok.** У 9092 в статус-баре висели уведомления TikTok (фон) — вероятно, это и сбило исходный триаж.

Телеметрия была слепа: события `yt_create_menu_app_not_foregrounded` нет, `foreground_pkg` на fail-событии пустой. Layer C (WP#87) при своей проверке не увидел чужого пакета — потому что это **и есть YouTube**, просто другой его экран. Распознать можно было только из видео.

## Корневая причина

Тап «+» («Создание видео») у этих аккаунтов открывает **камеру Shorts напрямую**, минуя bottom-sheet «меню создания». `yt_6` зовёт `_tap_plus_and_verify(strict_verify=True)`; поверхность камеры даёт пустой/разреженный uiautomator-dump → exact-match `editor_triggers` = `[]` → фатальный `_fail('yt_create_menu_not_reached')` в `_ensure_correct_account` (`publisher_base.py`), **до** реального пути загрузки.

Загрузка же идёт через прямой интент **`Shell_UploadActivity`** (`publisher_youtube.py`), который **минует камеру и галерею**; `_normalize_yt_state_pre_upload` всё равно `force-stop`'ает YouTube → home-feed перед загрузкой. Значит строгая проверка create-menu на `yt_6` — **рудиментарный гейт**, который роняет задачу раньше, чем отрабатывает устойчивый upload.

Исключены: «навигация камера→галерея» (галерея не используется) и «force-stop TikTok» (TikTok ни при чём).

## Фикс (Подход A)

`account_switcher.py`, `_tap_plus_and_verify`, ветка `if strict_verify and not hits:` — перед фейлом `yt_create_menu_not_reached`, после premium-promo (WP#132):

```python
if _yt6_accept_nonmenu_foreground_enabled():
    fg = self._detect_foreground_pkg()
    if fg and fg == cfg['package']:               # остались внутри YouTube
        self.p.log_event('warning', 'yt_create_menu_camera_direct',
            meta={'category': 'yt_create_menu_camera_direct', 'step': final_step,
                  'foreground_pkg': fg, 'shorts_camera_markers': _yt_is_shorts_camera(ui2)})
        return self._ok(final_step, already_matched=already_matched)
```

- Гейт по `fg == cfg['package']` (а не по тексту вкладок — dump камеры разреженный). Drift (fg≠YT) по-прежнему падает.
- `_yt_is_shorts_camera()` — только телеметрия. Kill-switch `YT6_ACCEPT_NONMENU_FOREGROUND` (default ON). Только YT-ветка (`strict_verify=True`).
- 2 module-level хелпера + фикстура `tests/fixtures/yt_create_menu/shorts_camera.xml` + 11 тестов.

## Качество / ревью

- 11 WP#134-тестов зелёные. Pre-existing fails (6 `test_ig_*` + `test_strict_verify_falls_back_safely_on_malformed_xml`) воспроизводятся на чистом origin/main (MagicMock `_detect_foreground_pkg` TypeError) — не регрессия.
- Двухстадийное ревью (spec-compliance ✅ + code-quality ✅).
- codex P1 («soft-pass для IG/TT») — **ложноположительный**: блок под `strict_verify`, который ставится только для YouTube (соседний premium-блок WP#132 — тот же паттерн). Закреплено инвариант-тестом `test_soft_pass_never_fires_for_ig_tt_strict_verify_false`.

## Деплой

PR #107 merged → прод autowarm `1b8c677` (ff-only pull). Рестарт PM2 НЕ нужен: `server.js` спавнит `python3 publisher.py` per-task из прод-пути. Integrity-смоук на проде ОК (импорт чистый, kill-switch ON, `_yt_is_shorts_camera` работает).

## Живой тест на phone #19 (RF8YA0W57EP, raspberry 7, makiavelli-o2u)

Задача 10089, запущена вручную `python3 publisher.py 10089` из прод-чекаута:

- **Камера-direct воспроизвелась:** после «+» foreground = `com.google.android.youtube/...CreationModesActivity` (нативная камера Shorts, не TikTok). Скриншот yt_6 = та же камера, что в прод-падениях.
- **Гейт soft-pass доказан:** `dumpsys` на камере → foreground = `com.google.android.youtube` (значит `fg==package` сработает).
- **Телеметрия:** `_yt_is_shorts_camera()` на реальном dump камеры = `True`.
- **Регрессии нет:** в этом прогоне dump камеры был полным (110 nodes, вкладка «Видео» в XML) → yt_6 прошёл нормальным путём `verified by triggers ['Видео']`, soft-pass не понадобился.
- **End-to-end успех:** публикация прошла (`awaiting_url` через Shell_UploadActivity, «✅ Публикация успешна»).

**Нюанс:** soft-pass срабатывает только на ПУСТОМ dump камеры (как в прод 9025/9092/9108). В сессии тестирования dump стабильно отдавался полным, поэтому live-срабатывание soft-pass не наблюдалось — это стохастика захвата GL-вкладок uiautomator'ом. Гейт и телеметрия доказаны напрямую; ветка покрыта юнит-тестами; пустой-dump кейс задокументирован в проде.

## Осталось / backlog

- **24ч verify** (acceptance): динамика `yt_create_menu_not_reached` ↓ (baseline 5/сутки до деплоя) + появление `yt_create_menu_camera_direct` с последующим `done`/`awaiting_url`, без всплеска downstream-фейлов. Затем #134 → «Готово». Откат: `YT6_ACCEPT_NONMENU_FOREGROUND=0` + restart.
- **Backlog (отдельная WP):** `yt_6` тап «+» — рудиментарный для загрузки (normalize всё равно закрывает меню, грузим через Shell_UploadActivity). Кандидат на упрощение/удаление шага. В этой WP сознательно не трогали (минимальный риск).

## Артефакты

- Spec: `docs/superpowers/specs/2026-05-26-wp134-yt-shorts-camera-design.md`
- Plan: `docs/superpowers/plans/2026-05-26-wp134-yt-shorts-camera.md`
- PR: https://github.com/GenGo2/delivery-contenthunter/pull/107
- OpenProject: #134 (комменты act.616 correction, act.633 deploy)
- Связь: WP#87 (Layer A–D, `_tap_plus_and_verify`), WP#132 (premium-promo, приоритетная ветка), WP#74 (`_dismiss_foreign_foreground`, другой call-site).
