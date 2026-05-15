# YT `yt_gallery_no_video_candidate` — нормализация состояния перед upload-flow

**Дата:** 2026-05-15
**Баг:** OpenProject WP [#74](https://openproject.contenthunter.ru/work_packages/74)
**Триаж:** инлайн в чате (2 фейла за 2026-05-15: task 6513, 6515)
**Ветка:** `worktree-yt-fail-triage-2026-05-15`

## Проблема

После успешного account_switch (`final=yt_sa_fastpath`, `matched=True`) две YT-задачи
сегодня упали с `yt_gallery_no_video_candidate` (`all_clickable_count: 0`).
На скринкастах YT остановился на состояниях, в которых upload-flow не запускается:

- **task 6513** (oracle_spacee) — системный диалог разрешений
  «Откройте YouTube доступ к камере и микрофону / Разрешить приложению YouTube
  снимать фото и видео?» с кнопками «При использовании приложения» / «Только в этот
  раз» / «Запретить». Диалог не дисмиссится, gallery не открывается.
- **task 6515** (oraclevisionn) — открытая bottom-sheet «Описание / Богатенький Ричи
  (1994) / 75 476 Просмотры». YT в режиме просмотра Shorts-фида со шторкой;
  upload-flow никогда не достигается.

Через 120s от установки `set_step('post-account-switch')` бьёт `watchdog_fired`,
ещё через ~46s `_select_gallery_video` ловит `all_clickable_count: 0` и
фейлит fail-fast'ом — финальная категория `yt_gallery_no_video_candidate`
маскирует то, что мы вообще не вышли на upload-экран.

## Root cause

`publish_youtube_short` (publisher_youtube.py:735+) исходит из того, что после
`_ensure_correct_account()` YT находится в pred-известном состоянии — либо на
home-feed (откуда можно открыть меню создания), либо может быть запущен через
`Shell_UploadActivity` напрямую к галерее. На свежо-онбордящихся / залипших
аккаунтах ни одно из этих допущений не выполняется:

1. `_ensure_correct_account()` может оставить YT в Shorts-плеере с открытой
   bottom-sheet «Описание» (task 6515) — switcher проходит через Shorts при
   `shorts_detected → shorts_escaped`, но bottom-sheet не закрывается всегда.
2. Меню создания (Шаг 1) не находится → fallback на Shell_UploadActivity, но
   `am force-stop` + Shell_UploadActivity на свежем аккаунте может приземлить на
   YT Shorts camera с системным диалогом камеры/мика (task 6513).
3. Диалог-хендлеры в Шагах 2-5 (publisher_youtube.py:1335, :1366, :1380, :1410)
   делают конечное число итераций (4-6) и `break` при первом дампе без
   распознанного диалога — если разрешительный диалог появляется ПОЗЖЕ, его
   некому закрыть.
4. `_select_gallery_video` (publisher_youtube.py:617) сам не вызывает
   permission-tap'ы (только `dismiss_location_dialog` и `tap_element(['ОК','OK','Разрешить'])`
   — без 'При использовании приложения' / 'Только в этот раз') и фейлится
   при пустом дампе.

## Рассмотренные варианты

### A. State reset в начале `publish_youtube_short` (выбрано)

В начале метода — до probe'а меню создания — принудительно перевести YT в
home-feed: `am force-stop com.google.android.youtube` → `am start ... LAUNCHER` →
дождаться `topResumedActivity = com.google.android.youtube/...HomeActivity`
(или подобной). Это убивает Shorts-shroud (6515) и любой shorts-camera state.

Pro: одна правка, лечит оба наблюдаемых сценария.
Cons: +5-10s к каждой публикации, потенциально triggers home-feed advertising
overlay (но это уже обрабатывается существующими handler'ами).

### B. Расширить permission-dialog handler в `_select_gallery_video`

Добавить в Layer A проверку `'При использовании приложения' / 'Только в этот раз'`
и циклить дольше, пока 'gallery items' не появятся ИЛИ не отстреляет timeout
(не break на пустом dump'е).

Pro: точечная защита у самой точки фейла.
Cons: лечит только camera-permission кейс (6513), не помогает Shorts-shroud (6515).

### C. Только улучшить fail-fast meta

В `_select_gallery_video` логировать `topResumedActivity` + `package` + добавить
новую категорию `yt_upload_not_started` при `clickable_count == 0`.

Pro: лучший триаж в будущем, минимальный риск.
Cons: не фиксит баг — только переименовывает.

## Решение

**Делаем A + B + C** — все три дополняют друг друга, scope маленький:

1. **A**: в начале `publish_youtube_short` (после `_ensure_correct_account`),
   до Шага 1 (probe меню создания), добавить блок `_normalize_yt_state_pre_upload`:
   - `set_step('YouTube: нормализация состояния перед upload')`
   - `am force-stop com.google.android.youtube`
   - `sleep 1.5`
   - `ensure_unlocked()`
   - `am start -p com.google.android.youtube -a android.intent.action.MAIN
     -c android.intent.category.LAUNCHER`
   - `sleep 3` + 2-iteration tap'и системных диалогов
     (`['При использовании приложения','Только в этот раз','ОК','OK','Разрешить','Allow','Понятно']`)
     для «свежо-открытый YT» onboarding.
   - log_event `yt_pre_upload_state_normalized` (meta: пакет, флаг force_stop_done).

2. **B**: внутри `_select_gallery_video` (loop `for parse_attempt in range(4)`)
   добавить tap для `'При использовании приложения','Только в этот раз'` на каждой
   итерации до парсинга XML (рядом с уже существующим
   `tap_element(ui, ['ОК', 'OK', 'Разрешить'])` на :652). Это безопасно — кнопки
   нейтральные, false-positive только на YT permission-dialog'ах.

3. **C**: в fail-fast блоке `_select_gallery_video` (:712-731) дополнить `meta`
   полями `top_resumed_activity` (через `dumpsys activity activities`) и
   `current_package`. Категорию оставить `yt_gallery_no_video_candidate` чтобы не
   сломать существующие dashboards, но добавить `meta.recovery_attempted = bool`.

## Тестирование

- **Unit** в `tests/test_publisher_youtube_picker.py`: добавить тест для
  permission-tap в _select_gallery_video (mock'нуть `tap_element` чтобы видеть
  список patterns).
- **New unit** `tests/test_publisher_youtube_state_normalize.py`: проверить, что
  `publish_youtube_short` вызывает force-stop + LAUNCHER до probe'а меню
  создания + tap'ит permission-кнопки. Mock'нуть `adb`, `dump_ui`, `tap_element`,
  `_ensure_correct_account`, `_get_mediastore_content_uri` (последние два чтобы
  не уходить дальше).
- **Live verify**: после деплоя — следующий task с любого свежеинсталлированного
  YT-аккаунта (или manually trigger Shorts camera state на тестбенче) должен
  пройти. Метрика: 0 fails `yt_gallery_no_video_candidate` за 24h при ненулевом
  объёме YT-задач.

## Out of scope / followups

- Универсальный «state-normalizer» для IG/TT (можно добавить параметризованно,
  но scope IG/TT не входит — отложить до evidence).
- Канарейка / feature-flag — не делаем; правка идемпотентна (force-stop YT
  безопасно) и риска регрессии немного.
- Удалить `set_step('post-account-switch')` artifact как stale step name —
  заменим на set_step('YouTube: нормализация…'), что сразу видно в watchdog'ах.
