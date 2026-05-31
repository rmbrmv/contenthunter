# WP#44 iter3 — обвал TikTok publish: срыв в Samsung «Добавить в историю»

**Дата:** 2026-05-31 · **OpenProject:** #44 (+ follow-up #203) · **Деплой:** prod autowarm main `71f4aa4`

## Симптом
Обвал TikTok success ~24% (24ч). Топ-причина `tt_caption_field_not_focused` = **119/207 (57%)** фейлов TT; вторая — `adb_device_not_ready` 59/28% (#195, инфра). 119 распределены по 42 устройствам / 65 аккаунтам — системно, не device-specific.

## Корень (доказан)
3/3 скринкаста (task 12744/12750/12739) + живой дамп RF8YA0W57EP (TikTok 44.4.3):
- В share-флоу всплывает **Samsung OneUI оверлей «Добавить в историю»** (`com.samsung.storyservice`, маркеры Аа/Текст/Флип/Недавнее/«Выберите несколько вариантов») поверх листа **«Поделиться в TikTok»** (Видео/Сообщение).
- Подстрока **`'Поделиться'`** в детекте caption-экрана (`publisher_tiktok.py` стр.1738 caption-fill + 1934 editor-loop) ложно матчила «**Поделиться** в TikTok» → ложный `desc_screen_found=true` (119/119 в проде) → слепые тапы фикс-координат (540,250-400) мимо → WP#44 honest abort `tt_caption_field_not_focused` **до** существующего дисмиссера оверлея (тот был только в `share_loop`, ниже по флоу).
- На share-листе ДВА clickable-«Видео»: таб-фильтр медиа (Все/Фото/Видео) и кнопка нижней шторки → `tap_element` тапал первый (фильтр) → залип.

## Фикс (`publisher_tiktok.py`, all kill-switched)
1. `_is_tt_caption_screen` — единый детект caption-экрана **без `'Поделиться'`** (RU+EN маркеры).
2. `_tt_share_sheet_video_target` — тап кнопки «Видео» нижней шторки (парной к «Сообщение»), не таб-фильтра.
3. `_tt_handle_stories_derail` — ранний дисмисс Samsung/in-app Stories в Шагах 2/3/4 (переиспользует WP#122/#82 детекторы); `'stuck'` → честный abort.

Kill-switch `TT_STORIES_DERAIL_EARLY_DISMISS_ENABLED` (default ON); focus-gate `TT_CAPTION_FOCUS_GATE_ENABLED` остаётся ON. 18 тестов, codex 5 раундов → 0 P1/P2.

## Testbench-смок (#12775/#12776, RF8YA0W57EP) — НЕ дал чистого success
Подтвердил: ложный `'Поделиться'` устранён (desc_found=false, регрессии нет), Шаг 2/3 проходят. Вскрыл более глубокую флаки флоу:
- `«+»` открывает **камеру** (SAASceneWrapperActivity), не редактор → fallback SEND-intent.
- Samsung-оверлей **недампируем uiautomator** (дамп = лаунчер при визуальном оверлее) → детект по XML невозможен.
- Иногда TikTok **вылетает на лаунчер** до стадии описания.

Фикс корректен и бьёт в прод-доминанту (share-лист в дампе), но end-to-end success на устройстве не доказан → **verify только утренней прод-пачкой** (падение `tt_caption_field_not_focused`). Откат: `TT_STORIES_DERAIL_EARLY_DISMISS_ENABLED=0`.

## Ops-трек
`com.samsung.storyservice` (источник оверлея) ВКЛЮЧЕН на флоте. На тест-устр. RF8YA0W57EP **отключён** (`pm disable-user --user 0 com.samsung.storyservice`, обратимо `pm enable`) — валидация следующей testbench-пачкой; при успехе раскатать на флот. Follow-up: **WP#203** (надёжный «+»→редактор / детерминированный share→Видео; координатный дисмисс недампируемого оверлея).
