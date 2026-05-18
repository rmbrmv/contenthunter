# YT publish: устранение `yt_editor_upload_timeout` (3 слоя защиты)

**Date:** 2026-05-18
**OpenProject:** WP #80
**Worktree branch:** `worktree-yt-fails-triage-2026-05-18`
**Target repo:** `/root/.openclaw/workspace-genri/autowarm` (GenGo2/delivery-contenthunter)

## Проблема

За 2026-05-18 на YouTube из 8 упавших публикаций **6 (75%)** свалились с `yt_editor_upload_timeout`. Все 6 — разные устройства и аккаунты:

| task_id | account | пакет на step=0 |
|---|---|---|
| 6761 | clickpay_app | YT Shorts player + реклама |
| 6764 | tkachenko_biohacking | YT Shorts player (@Medet_zhanabay) |
| 6815 | maksim_estate-o6x | YT Shorts video player overlay |
| 6817 | nofomo-c9m | **Chrome browser (flirtstudio.online)** |
| 6816 | my_clickpay | **Chrome browser (temu.com)** |
| 6823 | EliteCornersSpb | YT Shorts player (@RankZilla23) |

## Root cause

Sequence одинаковый для всех 6:

1. `account_switcher.switch_yt_account` дошёл до `yt_4_pick_account` с правильным `yt_gmail_match`.
2. На `yt_5_target_profile` сработал `yt_post_switch_handle_unknown` — switcher не распознал нужный screen.
3. Попытка дойти до `yt_6_create_menu` дала `ok matched=False`, `done matched=False` — и switcher **молча отдал управление publisher'у**.
4. Publisher вызвал `_normalize_yt_state_pre_upload` (force-stop YT → `am start LAUNCHER`).
5. Через ~26с YT открылся на home feed (или другой post-launch state).
6. Publisher выполнил `tap_element(ui_menu, ['Shorts', 'Short', 'Видео', 'Video'], clickable_only=True)` — **попал в bottom-nav `Shorts`** (тот же label, что и Create-menu Shorts), а не в Create-menu. Открылся Shorts feed чужих видео.
7. `direct_upload=True` (потому что `'youtube' in topResumedActivity`), publisher прыгнул в editor loop (25 шагов).
8. Для 2/6 задач (6816, 6817): из Shorts feed prompted рекламная карточка → handler диалогов в editor loop тапнул «Allow»/«Открыть сайт» → переход в Chrome.
9. AI Unstuck (5 попыток) — выходил в Search/Voice, не восстановил editor.
10. `yt_editor_upload_timeout` через ~5 минут.

## Дизайн фикса — 3 слоя защиты

### Слой 1 — Switcher fail-fast при отсутствии Create-menu

**Файл:** `account_switcher.py`

**Сейчас (`_tap_plus_and_verify` — `account_switcher.py:4110-4134`):**

```python
if hits:
    log.info(f'[switcher] {final_step}: verified by triggers {hits}')
else:
    log.warning(f'[switcher] {final_step}: no expected triggers — '
                f'continuing (FLAG_SECURE/unknown layout)')
return self._ok(final_step, already_matched=already_matched)
```

То есть метод **возвращает `_ok` даже если triggers не найдены** — только warning в лог. Дополнительно `editor_triggers` для YT (`account_switcher.py:101`) содержит `'Short'`, что слишком общий: `'short' in ui.lower()` срабатывает на `Shorts` в bottom-nav → false-positive verify даже если на самом деле мы на YT home feed.

**Меняем (минимальные изменения, только для YT):**

1. В YT cfg (`account_switcher.py:101`) убрать `'Short'` из `editor_triggers` (двусмысленно с bottom-nav). Оставить `['Добавить описание', 'Add description', 'Опубликовать', 'Upload']` + добавить более точные `'Видео', 'Video', 'Прямой эфир', 'Live'` (это специфичные Create-menu varианты, которых нет на home feed YT).
2. В `_tap_plus_and_verify` добавить optional параметр `strict_verify: bool = False`. Если `strict_verify=True` и `hits` пустые → возвращать `self._fail(...)` со step `<final_step>_no_triggers`, иначе текущее поведение (warning + success — IG/TT остаются как есть).
3. В `_switch_youtube` (`account_switcher.py:3150-3154`) передавать `strict_verify=True`.
4. В `publisher_kernel._SWITCHER_STEP_TO_CATEGORY` (после `'yt_5_editor'`) добавить:
   `'yt_6_create_menu_no_triggers': 'yt_create_menu_not_reached'`.

**Эффект:**
- При сегодняшнем сценарии (открыт home feed YT без Create-menu) switcher вернёт `success=False`, `reason='yt_6_create_menu_no_triggers'`, `final_step='yt_6_create_menu_no_triggers'`.
- `publisher_base._ensure_correct_account` (`publisher_base.py:1869-1875`) вызовет `_fail_task(...)`. Mapper (`_set_error_code_from_events`, `publisher_base.py:1975-1985`) подберёт `error_code='yt_create_menu_not_reached'` через step→category mapping.
- IG/TT не затрагиваем (`strict_verify=False` по умолчанию).

### Слой 2 — Безопасный тап Create-menu Shorts

**Файл:** `publisher_youtube.py`, функция `publish_youtube_short`, строки ~846-854.

**Сейчас:**
```python
ui_menu = self.dump_ui()
shorts_picked = bool(ui_menu) and self.tap_element(
    ui_menu, ['Shorts', 'Short', 'Shorts', 'Видео', 'Video'],
    clickable_only=True)
```

`tap_element` берёт первый matching узел по labels. Bottom-nav YT содержит элемент `Shorts` с тем же текстом → false-positive в 4/6 фейлов сегодня.

**Меняем:**

1. Новый helper `_is_create_menu_open(ui_xml) -> bool` — проверяет наличие ≥3 кнопок из set `{'Shorts', 'Short', 'Видео', 'Video', 'Прямой эфир', 'Live', 'Опрос', 'Пост', 'Post'}`.
2. В `publish_youtube_short`:
   - Если `_is_create_menu_open(ui_menu)` → разрешаем `tap_element(['Shorts', ...])` (текущее поведение).
   - Иначе → пропускаем shorts_picked, сразу идём в Shell_UploadActivity fallback (он надёжнее — intent на конкретную activity, а не угадывание по тексту).

**Эффект:** убирает первопричину захода в Shorts feed чужих видео.

### Слой 3 — Editor screen verify перед editor loop

**Файл:** `publisher_youtube.py`, функция `publish_youtube_short`, перед `for step in range(25):` (строка ~904).

**Меняем:**

Добавить guard `_verify_yt_editor_reached() -> tuple[bool, dict]`:

- 3 итерации `dump_ui` с паузой 2с (всего ~6с).
- Editor markers (любой = pass):
  - EditText с `resource-id`, содержащим `title` / `description` / `caption` / `compose`.
  - Текст в any node: `'Добавьте название'`, `'Add title'`, `'Загрузить'`, `'Upload'`, рядом с EditText.
  - `topResumedActivity` содержит `UploadActivity` или `ShareActivity` или `ComposeActivity`.
- Если ни один маркер не нашёлся за 3 итерации:
  - `log_event('error', 'yt_editor_not_reached', meta={'category':'yt_editor_not_reached', 'foreground_pkg':..., 'top_activity':..., 'all_texts':all_texts[:10], 'edit_fields_count':len(edit_fields)})`
  - return `(False, summary_dict)` → caller возвращает False → error_code `yt_editor_not_reached`.
- Если маркер найден — продолжаем editor loop как сейчас.

**Эффект:** убирает 5-минутный timeout + ошибочные AI Unstuck попытки + Chrome переходы.

## Тестирование

**Unit-тесты (pytest, без устройств):**

1. `test_switcher_create_menu_signature_present` — фикстура UI dump с 4 Create-menu кнопками → switcher проходит.
2. `test_switcher_create_menu_signature_absent` — фикстура UI home feed (только bottom-nav) → switcher возвращает False + `yt_create_menu_not_reached`.
3. `test_publisher_create_menu_open_detector` — `_is_create_menu_open` True/False на фикстурах.
4. `test_publisher_editor_verify_pass` — фикстура реального editor (resource-id title) → pass.
5. `test_publisher_editor_verify_fail_shorts_feed` — фикстура task 6815 dump (Shorts player overlay) → fail.
6. `test_publisher_editor_verify_fail_chrome` — фикстура task 6816 dump (Chrome temu.com) → fail.

**Фикстуры:** реальные UI dump XML с production задач 6815, 6816 (доступны через `ui_dump_url` events; скачиваем в `tests/fixtures/yt_editor_verify/`).

**Live verify (после merge):**

- Re-queue 2-3 свежих failed YT tasks через `publish_queue` → `UPDATE publish_queue → pending + publish_task_id=NULL`.
- Сравнить error_code distribution за 24ч до/после: должно появиться `yt_create_menu_not_reached` и `yt_editor_not_reached`, `yt_editor_upload_timeout` — упасть до 0 (или почти).

## Риски и rollout

- **Все 3 слоя fail-safe:** false-negative = ранний выход с точным `_not_reached` вместо 5-минутного `_timeout`. Регрессия = не хуже сегодняшнего.
- **Откат:** обычный git revert одного PR. Feature flag НЕ нужен.
- **Тестбенч smoke:** перед prod merge — 1-2 публикации на phone #19 testbench (через farming-testbench scheduler) с включённым PR.
- **Cross-platform:** изменения только в `account_switcher.py` (метод `switch_yt_account`) и `publisher_youtube.py`. IG/TT не затрагиваем.

## Out of scope

- AI Unstuck guard для YT editor flow (не давать тапать в Search/Voice) — backlog, отдельная задача.
- Regression corpus для publisher_youtube (фикстуры in-tree pytest достаточно для текущего scope).
- Recovery flow «вернуться в editor если зашли в Shorts feed» — отдельная задача, нужны живые данные о feasibility (back-кнопки могут ломать другие потоки).
