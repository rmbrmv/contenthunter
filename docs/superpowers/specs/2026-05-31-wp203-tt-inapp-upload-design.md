# WP#203 — Детерминированный in-app upload для TikTok

**Дата:** 2026-05-31
**Тип:** Ошибка (follow-up WP#44 iter3, deploy 31.05 prod 71f4aa4)
**OpenProject:** #203, статус «В разработке», assignee Данил
**Репозиторий кода:** `autowarm-testbench` (`publisher_tiktok.py`); docs/evidence — `contenthunter`

## Что было не так

Смок #12775/#12776 на RF8YA0W57EP вскрыл, что фикс маркеров iter3 недостаточен.
Два **независимых** драйвера обвала TT (остаточный код `tt_caption_field_not_focused`):

| | Драйвер | Природа |
|---|---|---|
| **FM-A** | После account-switch тап `«+»` открывает **камеру** (`SAASceneWrapperActivity`: ФОТО/ТЕКСТ/ЭФИР/ПУБЛИКАЦИЯ), а не редактор → `in_editor=false` → fallback на флаки `SystemShareActivity` SEND-intent | **остаточный, главный для кода** |
| **FM-B** | Samsung OneUI оверлей «Добавить в историю» (`com.samsung.storyservice`) — системное окно, `uiautomator dump` его **не дампит** (возвращает лаунчер) → XML-детект структурно невозможен | снимается ops-отключением пакета |
| **FM-C** | TikTok вылетает на лаунчер до стадии описания | редкий длиннохвост |

**Почему iter3 «не лечит» (net-neutral, canary 9-10/10 fail):**
`_detect_samsung_stories_overlay()` ищет маркеры в XML-дампе. Когда оверлей висит, дамп
возвращает **лаунчер** — детектор никогда не матчит оверлей, хендлер не срабатывает.
Плюс смок показал, что даже с **отключённым** storyservice на RF8YA0W57EP `«+»`→камера
сохраняется → FM-A остаётся главной причиной.

**Ключевой инсайт:** именно системный **SEND-intent share-путь порождает** Samsung-оверлей
(системный share триггерит «Добавить в историю»). Уход на чисто внутренний аплоад TikTok
решает FM-A и FM-B одним движением.

## Что делаем

Заменяем ветку «редактор не детектирован → SEND-intent» на детерминированный **in-app upload
через камеру**. Решения брейншторма (зафиксированы с Данилом 31.05):

- **Approach A** — in-app upload через вкладку ПУБЛИКАЦИЯ камеры (не SEND-intent, не «оба пути»).
- **FM-B** — защита в глубину: ops-disable `com.samsung.storyservice` на флоте **+** foreground-based
  (не-XML) дисмисс в коде.
- **Fallback при сбое in-app** — честный фейл `tt_*` → ручная очередь. **Без** SEND-intent
  в основном пути (как focus-gate iter2: никогда не публикуем вслепую).

### Целевой флоу (замена ветки `in_editor` в `publish_tiktok`)

```
switch + «+»  →  читаем topResumedActivity (fg_pkg) + dump_ui
   ├─ редактор (маркеры Далее / Добавьте описание / Публично)  → существующий editor-loop (Шаг 3+)
   ├─ КАМЕРА (fg=SAASceneWrapperActivity + вкладки)            → [НОВОЕ] in-app upload:
   │      tap ПУБЛИКАЦИЯ → внутр. галерея TikTok
   │      → выбрать СВЕЖЕЕ видео → редактор → editor-loop
   ├─ storyservice / лаунчер (fg-сигнал, не XML) в TT-фазе     → [НОВОЕ] foreground-дисмисс (escalating BACK, cap)
   └─ не дошли до редактора за cap                             → честный фейл tt_inapp_upload_unreached → ручная
```

## Новые юниты (маленькие, изолированно тестируемые)

Все — методы класса TikTok-publisher в `publisher_tiktok.py`, рядом с существующими
`_detect_*` / `_handle_*`. Чистые детекторы принимают `ui_xml`/`fg_pkg` и не трогают adb
(тестируются на статичных XML-фикстурах, как существующие TT-тесты).

| Юнит | Сигнатура | Что делает | Возврат |
|---|---|---|---|
| `_tt_foreground_pkg` | `() -> str` | парсит пакет из `dumpsys activity activities … topResumedActivity` (не-XML сигнал, единственный для FM-B) | имя пакета (`''` если не прочитан) |
| `_tt_detect_camera_screen` | `(ui_xml, fg_pkg) -> bool` | камера? fg содержит `SAASceneWrapperActivity` **или** UI содержит ≥2 вкладок из {ФОТО, ТЕКСТ, ЭФИР, ПУБЛИКАЦИЯ} | bool |
| `_tt_enter_upload_from_camera` | `(ui_xml) -> bool` | тап **тайла-миниатюры галереи внизу-слева** (clickable `id/zne`, НЕ текста «ПУБЛИКАЦИЯ» — это уже выбранный режим) → ждёт галерею | True если галерея появилась |
| `_tt_in_gallery_picker` | `(ui_xml) -> bool` | детект галереи по UI-маркерам (вкладки Все/Видео/Фото + «Далее») — foreground НЕ меняется (та же SAAScene) | bool |
| `_probe_duration_s` | `(path) -> float\|None` | длительность видео через ffprobe (переиспользует паттерн `_probe_mp4`); `None` если path=URL/недоступен/ошибка | сек |
| `_tt_select_newest_gallery_video` | `(ui_xml, expected_dur) -> str` | tap «Видео» → выбрать тайл с **верификацией по длительности** (см. ниже) | `'tapped'`/`'no_match'`/`'no_tiles'` |

### Верификация выбора видео по длительности (обязательная)

Первый тайл (новейший) почти наверняка наш — пуш идёт прямо перед публикацией. Длительность —
**вторичный гард** против редкого «новейший ≠ наш» (лаг пуша, кэш галереи). Никогда не публикуем
чужое видео.

1. `expected_dur = _probe_duration_s(self.media_path)` (локальный файл-источник, до пуша).
2. Из дампа «Видео»-сетки: тайлы (grid-bounds, clickable) + оверлеи `MM:SS`; каждому тайлу
   сопоставляем длительность по оверлею, чей центр лежит в bounds тайла.
3. Политика выбора:
   - `expected_dur` известна → совпадение `|tile − expected| ≤ 1с` (учёт floor/round TikTok).
     Среди совпавших — **первый (новейший, верх-лево)** → tap, `'tapped'`.
   - известна, но **ни один тайл не совпал** → `'no_match'` → честный фейл
     `tt_gallery_video_match_failed` → ручная (не тапаем наугад).
   - `expected_dur is None` (ffprobe не смог / `media_path`=URL) → первый тайл + `log warning`
     `tt_gallery_duration_unverified` → `'tapped'` (деградация, как раньше «новейший»).
   - тайлов нет вовсе → `'no_tiles'` → честный фейл.
| `_tt_recover_from_storyservice_fg` | `(fg_pkg, wait) -> str` | fg==`com.samsung.storyservice`/лаунчер в TT-фазе → escalating BACK с cap | `'handled'`/`'stuck'`/`'clean'` |

Оркестратор `_tt_inapp_upload_from_camera(content)`: enter→gallery→select→ждать editor-маркеры
с cap-циклом; на каждой итерации зовёт `_tt_recover_from_storyservice_fg`; при превышении cap —
честный фейл.

## FM-B — два слоя

1. **Ops (исполняет Данил):** раскатать `pm disable-user --user 0 com.samsung.storyservice` на
   флот (обратимо `pm enable`). Чеклист + проверка персистентности после reboot/OTA — в evidence.
   На RF8YA0W57EP уже отключён.
2. **Код:** `_tt_recover_from_storyservice_fg` — детект **по foreground-пакету**, не по XML
   (XML слеп к оверлею). Покрывает устройства, где disable не применился/слетел.

## Kill-switches и честность

- `TT_INAPP_UPLOAD_VIA_CAMERA_ENABLED` (default **ON**): ON = новый in-app путь;
  **OFF = legacy SEND-intent** (мгновенный откат к текущему поведению).
- `TT_STORYSERVICE_FG_DISMISS_ENABLED` (default **ON**): foreground-дисмисс оверлея.
- При недостижении редактора за cap — новый честный код `tt_inapp_upload_unreached`
  (+ под-степ для камеры/галереи/fg-stuck в телеметрии) → задача в ручную. Вслепую не печатаем.
- Существующий focus-gate (`_fill_tiktok_caption`) сохраняется как последний рубеж.
- Новые коды `tt_inapp_upload_unreached` и `tt_gallery_video_match_failed` регистрируются в
  каталоге `publish_error_codes` (WP#140) и классифицируются как UI-коды → `ui_changed` → ручная
  очередь. `tt_gallery_duration_unverified` — warning-событие (не терминальный код), для мониторинга
  деградации ffprobe.

## Error handling / edge cases

- **Галерея не открылась** после тапа ПУБЛИКАЦИЯ (cap N попыток) → честный фейл.
- **Видео-тайл не найден** → честный фейл (не тапаем случайный тайл).
- **storyservice/лаунчер залип** после cap BACK → `..._fg_stuck` → честный фейл.
- **Разрешения галереи** (диалог доступа к медиа при первом upload) → переиспользуем
  существующий `_handle_tt_contacts_perm`-паттерн / tap «Разрешить».
- **Геолокация / commercial-music / amplify** в editor-loop — без изменений (уже обрабатываются).

## Тестирование

- **TDD**: unit на каждый чистый юнит — детект камеры (fg и UI-варианты), `_tt_in_gallery_picker`,
  **верификация по длительности** (совпадение в пределах ±1с; floor vs round; no_match→честный фейл;
  expected=None→первый тайл+warning; сопоставление оверлея `MM:SS` ↔ bounds тайла), fg-recover
  cap→stuck, оркестратор happy-path и fail-path. Моки `dump_ui`/`adb`/`_tt_foreground_pkg`/
  `_probe_duration_s` как в `tests/test_publisher_tt_*`. Фикстуры XML — из реальных дампов №19
  (`docs/evidence/2026-05-31-wp203-tt-inapp-upload-recon.md`).
- **testbench-смок** на RF8YA0W57EP (storyservice там disabled) — валидация чистого success
  по in-app пути end-to-end.
- **`codex review`** спеки/плана и кода (конвенция).

## Эмпирическая разведка флоу (РЕШЕНО — дамп на №19 RF8YA0W57EP, TikTok 44.x, 1080×2340, 31.05)

Живой проход `«+»`→камера→галерея на телефоне №19 (логин-аккаунты TikTok есть). Подтверждено
и зафиксировано (детали — `docs/evidence/2026-05-31-wp203-tt-inapp-upload-recon.md`):

1. **`«+»` (центр навбара ≈540,2180) → камера `SAASceneWrapperActivity`** — FM-A воспроизведён.
   Камера **дампится** нормально (`com.zhiliaoapp.musically`, ~56KB); вкладки ФОТО/ТЕКСТ и
   ЭФИР/ПУБЛИКАЦИЯ/ТВОРЧЕСТВО присутствуют как text-ноды.
2. **Галерея открывается тайлом-миниатюрой внизу-слева** (clickable `id/zne`, центр ≈112,2126),
   **НЕ** тапом текста «ПУБЛИКАЦИЯ» (это уже выбранный режим — тап по тексту бездействует).
   → корректировка `_tt_enter_upload_from_camera`.
3. **Галерея — в той же activity** (foreground остаётся `SAASceneWrapperActivity`) → «мы в галерее»
   детектим **по UI-маркерам** (вкладки Все/Видео/Фото + кнопка «Далее» `id/vst`), не по foreground
   → отсюда юнит `_tt_in_gallery_picker`.
4. **Селектор (главный вывод):** вкладка **«Все»** по умолчанию мешает фото/скриншоты — «первый
   тайл» = свежий скриншот, **ненадёжно** (подтвердило интуицию Данила). Вкладка **«Видео»**
   (clickable `desc=Видео`, центр ≈531,294) фильтрует видео по свежести → **первый тайл
   (верх-лево, центр ≈182,542) = свежезалитое видео**.
5. **Тайлы без `content-desc`** (голые ImageView) → матч по имени файла из XML невозможен. Но у
   каждого видео-тайла есть **оверлей длительности `MM:SS`** (text-нода в нижней части тайла) →
   опциональная верификация: предпочесть первый тайл, чьё `MM:SS` совпадает с длительностью
   `remote_media_path` (ffprobe). Координаты device-specific — в коде искать ноды по структуре
   (вкладка по text/desc, тайлы по grid-bounds), не хардкодить пиксели.

**Итоговая стратегия `_tt_select_newest_gallery_video`:** tap вкладку «Видео» → выбрать первый
видео-тайл; если передан `expected_dur` — предпочесть первый тайл с совпадающим оверлеем `MM:SS`,
иначе первый. Стратегия локализована в одном методе, заменяема без изменения оркестратора.

## Out of scope

- Изменения switcher (`account_switcher.py`) и логики account-switch — не трогаем.
- VK/FB/X — вне scope autowarm.
- Рефактор существующих overlay-хендлеров (`_handle_samsung_stories_overlay` и т.п.) — оставляем
  как есть; они продолжают работать в `wait_upload`/`share_loop` фазах.
