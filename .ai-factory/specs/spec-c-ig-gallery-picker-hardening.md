# Spec C — IG Gallery Picker Hardening (RC-8)

**Дата:** 2026-05-08
**Инцидент:** publish task 3805 (`@clickpay_now`, content 2022) — pipeline опубликовал документ-screenshot как Reel вместо нашего видео
**Сегодняшний impact:** 8 IG `awaiting_url` за день (раньше 0 за 13 дней подряд)
**Codex review:** прошёл (см. `/tmp/codex-review-2026-05-08/incident-brief-v2.md` секция RC-8)

---

## 1. Background

### Что случилось
Скрин pipeline'а в момент cleanup task 3805 показывает экран **«Черновики Reels»** на телефоне. В черновиках — Reel длительностью 5 секунд, превью = **белый документ**. Это и есть «карусель» в feed @clickpay_now: pipeline сделал Reel из статической картинки документа.

Все события pipeline идут «штатно»:
- `ig_create_reels_tile_strict_match` ✅
- `ig_draft_continuation_dismissed` ✅
- gallery select (gap 1m23s — без диагностики)
- `caption_filled_verified` ✅
- Share + URL captured (partial: `/<account>/reels/`)
- L3 handle assertion: `ig_post_publish_handle_skipped_not_on_profile` (×2) → status='awaiting_url'

L3 assertion не виновник — это ДЕТЕКТОР (commit `013adf6`). До его деплоя те же broken-publication writeback'или `done`. Сегодняшние 8 awaiting_url подсветили скрытую проблему.

### Где код шарашит не то

#### A. MediaStore-проверка только для video MediaStore
**`autowarm-testbench/publisher_base.py:3267-3290`**
```python
self.adb(f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file://{remote_path}"')
time.sleep(2)
for _ms_attempt in range(4):
    _ms_out = self.adb(
        'shell content query --uri content://media/external/video/media '
        '--sort "date_added DESC" --projection "_id,display_name,date_added" '
        '--limit 1 2>/dev/null'
    ) or ''
    if filename in _ms_out or os.path.splitext(filename)[0] in _ms_out:
        _ms_ok = True; break
    ...
if not _ms_ok:
    log.warning(...)  # только warning, push считается успешным
```
- Запрашивается **только `external/video/media`**. IG-галерея в Recents — mixed media (video+image), отсортированных по общему `date_added DESC`.
- Свежий image (debug-screenshot, чужая фотка с камеры) окажется выше нашего видео.
- Если check не прошёл после 4 попыток — только warning, push считается успешным.

#### B. Gallery picker фолбэк слишком толерантный
**`autowarm-testbench/publisher_instagram.py:1248-1262`**
```python
if video_candidates:
    cx, cy, d = video_candidates[0]    # OK
elif all_clickable:
    cx, cy, d = all_clickable[0]       # ← BUG: первый кликабельный = может быть фото/screenshot
    self.adb_tap(cx, cy); video_tapped = True; break
```
**`autowarm-testbench/publisher_instagram.py:1273-1281`**
```python
if not video_tapped:
    self.adb_tap(540, 721)             # ← BUG: blind tap fallback
```

Если в Recents выше нашего видео лежит свежая картинка (debug-скриншот, чужая фотка) — у неё content-desc обычно «Фотография ...», без «видео». `video_candidates` пусто → `all_clickable[0]` → тапается картинка → IG-Reels-редактор делает 5-сек клип из неё → публикуется.

Тот же фолбэк есть в editor-loop **`publisher_instagram.py:1539-1556`** (re-select при возврате в галерею).

#### C. Screen recordings polluted MediaStore
Pipeline сам делает screen-recording для evidence (`/sdcard/Movies/Screenrecorder/...` или подобное) — оно индексируется в `external/video/media`. Может стать «первым видео» в Recents и обмануть даже video-only check.

`_cleanup_device_artifacts(scope='pre_push')` (`publisher_base.py:2795-2810`) сейчас покрывает:
- `/sdcard/Pictures/Screenshots/*.png`, `/sdcard/Screenshots/*.png`, `/sdcard/DCIM/Screenshots/*.png` ✅
- `/sdcard/DCIM/autowarm_*.mp4` ✅
- НЕ покрывает: `/sdcard/Movies/Screenrecorder/*` и другие video-pollution каталоги

---

## 2. Goals

1. **Никогда не публиковать НЕ наш файл.** Если pipeline не уверен, какой media в gallery первый — abort с явным error_code, а не публикация наугад.
2. **Удалить unsafe blind-tap фолбэки** (`all_clickable[0]`, `(540, 721)`). Заменить на fail-fast с диагностикой.
3. **Расширить cleanup на video-pollution** (screen recordings, чужие mp4 в DCIM/Camera).
4. **Двойная MediaStore-проверка** (video + images), сравнивать max(date_added) с нашим pushed file.
5. **Sanity-check после выбора, перед Share** — duration в editor должна совпадать с длительностью pushed video.

## Non-Goals

- Не переписываем gallery picker архитектуру. Минимальные точечные правки.
- Не трогаем Reels-tile detection / draft dismiss / caption fill — они работают.
- Не трогаем L3 post-publish assertion (commit `013adf6`) — он работает корректно как детектор.
- Не реализуем UI для оператора «approve manually» (отдельный backlog).

---

## 3. Design

### D1. Двойная MediaStore-проверка (video + images) с retry-loop
**Файл:** `publisher_base.py:3270-3290` (заменить логику)

```python
def _ms_query(uri: str) -> tuple[str, int, bool]:
    """Возвращает (display_name, date_added, ok). ok=False если parse failed."""
    out = self.adb(
        f'shell content query --uri {uri} '
        f'--sort "date_added DESC" '
        f'--projection "_id,_display_name,date_added" '
        f'--limit 1 2>/dev/null'
    ) or ''
    # Codex: парсить ОБА варианта — _display_name И display_name
    # Codex: regexp ([^,]+) ломается если имя файла содержит запятую
    name_m = re.search(r'(?:_display_name|display_name)=(.*?)(?:,\s*date_added=|$)', out)
    date_m = re.search(r'date_added=(\d+)', out)
    if not name_m or not date_m:
        return ('', 0, False)
    return (name_m.group(1).strip(), int(date_m.group(1)), True)

# Codex: retry loop 4-6 попыток, hard fail только если стабильно
MS_CHECK_RETRIES = 5
MS_CHECK_DELAY = 1.5  # сек между попытками
last_video_name, last_video_ts, last_image_name, last_image_ts = '', 0, '', 0

for ms_attempt in range(MS_CHECK_RETRIES):
    video_name, video_ts, video_ok = _ms_query('content://media/external/video/media')
    image_name, image_ts, image_ok = _ms_query('content://media/external/images/media')
    last_video_name, last_video_ts = video_name, video_ts
    last_image_name, last_image_ts = image_name, image_ts

    # Codex: если ts=0 / parse failed — это отдельная категория, не pollution
    if not video_ok or video_ts == 0:
        if ms_attempt < MS_CHECK_RETRIES - 1:
            time.sleep(MS_CHECK_DELAY); continue
        self.log_event('error',
            f'media_store_unreadable_pre_publish: video query failed/empty after {MS_CHECK_RETRIES} попыток',
            meta={'category': 'media_store_unreadable_pre_publish',
                  'attempts': MS_CHECK_RETRIES, 'expected_filename': filename})
        self._cleanup()
        return None

    # Codex: strict equality, не stem-match (stem может совпасть с thumbnail)
    if video_name == filename:
        # Наш файл — первый в video MediaStore. Теперь проверяем что image не новее.
        if image_ok and image_ts > video_ts:
            # Возможно скоро scanner догонит — retry
            if ms_attempt < MS_CHECK_RETRIES - 1:
                # повторный broadcast чтобы догнать scanner
                self.adb(f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE '
                         f'-d "file://{remote_path}"')
                time.sleep(MS_CHECK_DELAY); continue
            # Стабильно: image старше → fail
            self.log_event('error',
                f'media_store_pollution_pre_publish: image newer than our video '
                f'(image={image_name!r}@{image_ts} > video@{video_ts})',
                meta={'category': 'media_store_pollution_pre_publish',
                      'reason': 'image_newer_than_video',
                      'top_image': image_name, 'top_video': video_name,
                      'video_ts': video_ts, 'image_ts': image_ts,
                      'expected_filename': filename})
            self._cleanup()
            return None
        # OK: наш видео первое + нет более свежей картинки
        log.info(f'  ✅ MediaStore: {filename} первое (video_ts={video_ts}, '
                 f'image_top={image_name!r}@{image_ts})')
        break

    # Не наш файл — retry (scanner может ещё не догнать)
    if ms_attempt < MS_CHECK_RETRIES - 1:
        self.adb(f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE '
                 f'-d "file://{remote_path}"')
        time.sleep(MS_CHECK_DELAY); continue

    # Стабильно не первый — pollution
    self.log_event('error',
        f'media_store_pollution_pre_publish: not first after {MS_CHECK_RETRIES} попыток '
        f'(top_video={video_name!r}, expected={filename!r})',
        meta={'category': 'media_store_pollution_pre_publish',
              'reason': 'not_first_in_video',
              'top_video': video_name, 'top_image': image_name,
              'video_ts': video_ts, 'image_ts': image_ts,
              'expected_filename': filename, 'attempts': MS_CHECK_RETRIES})
    self._cleanup()
    return None
```

**Behaviour:**
- Раньше: warning + продолжаем
- Теперь: hard fail с одной из 2 категорий:
  - `media_store_pollution_pre_publish` — стабильно не первый или image newer (после 5 попыток)
  - `media_store_unreadable_pre_publish` — query сломалась / parse failed
- Retry внутри (5×1.5с = ~7.5с) даёт scanner догнать. Snapshot timing: typical scanner latency 200-800мс.
- Outer retry — стандартный publish_queue dispatcher (5 мин) подберёт заново после следующего pre_push cleanup.

**Codex flags applied:**
- ✅ парсить `_display_name|display_name`
- ✅ robust regexp с lookahead до `, date_added=`
- ✅ strict equality `==`, не stem-match
- ✅ retry-loop вместо однократной проверки
- ✅ отдельная категория `media_store_unreadable_pre_publish` для parse failures

**Edge case:** `external/file` portable but iffy → отдельные запросы безопаснее. Принято.

### D1.5. CRITICAL: проверка call chain `return None`
**Codex rollout blocker:** убедиться что `return None` из `_push_media_with_check` (или wherever) корректно эскалируется в `publish_task.status='failed'` с `error_code='media_store_pollution_pre_publish'`, а НЕ в silent retry / accidental success в верхнем слое run_publish_task.

Перед PR — добавить тест:
```python
def test_media_store_pollution_sets_publish_task_failed():
    """assert полная цепочка: pollution → return None → run_publish_task → status='failed' + error_code"""
```

### D2. Удалить unsafe фолбэки в gallery picker
**Файл:** `publisher_instagram.py:1248-1281` (рефактор)

```python
# Было:
if video_candidates:
    cx, cy, d = video_candidates[0]
    self.adb_tap(cx, cy); video_tapped = True; break
elif all_clickable:                              # ← УДАЛИТЬ
    cx, cy, d = all_clickable[0]
    self.adb_tap(cx, cy); video_tapped = True; break
...
if not video_tapped:
    self.adb_tap(540, 721)                       # ← УДАЛИТЬ
    video_tapped = True

# Станет:
if video_candidates:
    cx, cy, d = video_candidates[0]
    log.info(f'  Тапаем видео ({cx},{cy}): {d[:60]}')
    self.adb_tap(cx, cy)
    video_tapped = True
    time.sleep(4)
    break
# нет фолбэка — после цикла парсинга проверяем video_tapped

if not video_tapped:
    log.error('Видео не найдено в gallery picker — abort')
    self._save_debug_artifacts('instagram_gallery_no_video')  # screenshot + UI dump
    self._safe_kb_probe(raw_ui, step='ig_gallery_no_video_candidate')
    # Codex: 5-10 first clickable desc + bounds для диагностики локализационных edge cases
    diag_clickables = [
        {'cx': c[0], 'cy': c[1], 'desc': c[2][:120]}
        for c in all_clickable[:10]
    ]
    self.log_event('error',
        'IG: видео не найдено в gallery picker — fail-fast (RC-8)',
        meta={'category': 'ig_gallery_no_video_candidate',
              'platform': self.platform,
              'step': 'gallery_select',
              'all_clickable_count': len(all_clickable),
              'first_clickables': diag_clickables})
    return False
```

### D3. Удалить unsafe фолбэки в editor-loop re-select
**Файл:** `publisher_instagram.py:1539-1556` (тот же рефактор)

```python
# Было: на dgallery в editor-loop fallback на (540, 721) если 'видео' не нашли
# Станет: тот же fail-fast с category='ig_gallery_no_video_candidate' (reason='editor_loop')
```

### D4. Расширить cleanup на screen recordings
**Файл:** `publisher_base.py:2795-2810` (extend `_CLEANUP_PRE_PUSH_GLOBS`)

```python
_CLEANUP_PRE_PUSH_GLOBS = (
    # ... existing entries ...
    # NEW: screen recordings — индексируются в external/video/media (Codex)
    '/sdcard/Movies/Screenrecorder/*.mp4',
    '/sdcard/Movies/ScreenRecorder/*.mp4',         # case variant
    '/sdcard/Movies/Screen Recorder/*.mp4',        # space variant
    '/sdcard/DCIM/Screen recordings/*.mp4',
    '/sdcard/DCIM/Screen recordings/*.mkv',
    '/sdcard/Pictures/ScreenRecorder/*.mp4',
    '/sdcard/Pictures/Screen recordings/*.mp4',
    '/sdcard/Recordings/*.mp4',
    # NEW: pending Camera files (Samsung Camera2 артефакты)
    '/sdcard/DCIM/Camera/*.pending-*.mp4',
    # NOT included: /sdcard/DCIM/Camera/*.mp4 — может быть legitimate camera output (Codex flag)
)
```

И sleep после MEDIA_SCAN broadcast в pre_push, чтобы scanner снял deleted entries:
```python
self.adb('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/')
time.sleep(2)  # MediaStore переиндексация
```

**Codex caveat:** `MEDIA_SCANNER_SCAN_FILE` на директорию не всегда удаляет stale entries для удалённых файлов. Если pollution не уходит — fallback на explicit per-path scan для удалённых.

### D5. Pre-Share duration sanity check
**Файл:** `publisher_instagram.py` — в editor-loop после `caption_filled_verified`, перед Share

```python
# editor показывает duration на тайл, и в editor controls (например HH:MM:SS на seek bar)
# UI dump парсим, ищем '0:0X' или 'X:XX' формат. Если не равно ожидаемому — abort.

expected_dur = self.duration_seconds  # из validator_content
actual_dur = self._extract_editor_duration(ui_editor)  # new helper
if actual_dur is not None and expected_dur is not None:
    if abs(actual_dur - expected_dur) > 2:  # tolerance 2s
        self.log_event('error',
            f'ig_editor_duration_mismatch: expected={expected_dur:.1f}s actual={actual_dur:.1f}s',
            meta={'category': 'ig_editor_duration_mismatch',
                  'expected_seconds': expected_dur,
                  'actual_seconds': actual_dur})
        return False
```

**Caveat:** duration в editor может быть на разных контролах в разных версиях IG. Это «soft» защита (вернуть `actual_dur=None` → skip check). Цель — поймать случай 5s document-as-Reel при 15-30s expected.

**Codex flag:** «лучше — duration badge, MIME/filename correlation, grid position после MediaStore proof, либо очистка Recents до push» — duration check + cleanup expansion + MediaStore проверка вместе закрывают это.

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| Удаление all_clickable[0] фолбэка сломает legitimate edge case (локализация без «видео» в content-desc) | Логируем 5-10 first clickables (desc+bounds) в error event — будет видно какие случаи всплывают, и можно расширить video_candidates regexp по факту |
| MediaStore double-query даст false positive если image MediaStore содержит наш video thumbnail | Strict equality `video_name == filename` — thumbnail обычно `<original>_thumb.jpg`, не пройдёт. Stem-match убран (Codex) |
| Screen recording cleanup глобам — может стереть operator-recordings (legitimate) | Глобы конкретные. Если оператор использует custom screen recorder с другим путём — не затрагиваем. В случае жалобы сужаем. **DCIM/Camera/*.mp4 НЕ чистим** (Codex: рискованно, чужие camera videos legitimate) |
| Duration mismatch check ложный — IG editor показывает duration в разных местах разных версий | Возвращаем `None` если parse не удался → check skipped. Не fail-fast на отсутствии данных. Codex: добавить тесты на `0:05`, `00:05`, `5 сек.` форматы и multiple markers |
| Hard fail на media_store_pollution оставит publish_queue rows в pending forever | dispatcher имеет retry mechanism — задача попробует снова после следующего cleanup; если опять fail — финальный fail после N попыток (стандартное поведение). **CRITICAL (Codex):** проверить что `return None` корректно эскалируется в publish_task.status='failed' (см. D1.5) |
| **NEW (Codex):** MediaStore proof не гарантирует что IG Recents сортирует точно так же | IG может иметь свою кэш-сортировку. Если live-проверка после деплоя покажет `media_store_pollution_pre_publish=0` но `ig_gallery_no_video_candidate>0` — нужен дополнительный selector (D5 duration check + grid position детекция) |
| **NEW (Codex):** Hard fail spike может остановить публикации при локализационном selector gap | Monitor `ig_gallery_no_video_candidate` count за первые 24ч. Если spike — быстрый rollback или расширение video_candidates regexp по фактическим content-desc из event meta |
| **NEW (Codex):** Parse failure / status mapping может маскировать ошибку | Отдельная категория `media_store_unreadable_pre_publish` (D1) для parse fails. Тест D1.5 закрывает status mapping |

---

## 5. Test plan

### Unit (pytest, новые тесты)

**MediaStore (D1):**
1. `test_media_store_pollution_detected_when_image_newer` — мок ADB → image newer than video стабильно после 5 попыток → assert hard fail с `media_store_pollution_pre_publish`
2. `test_media_store_pollution_detected_when_video_not_first` — мок → наш файл НЕ в первой строке video MediaStore стабильно → assert hard fail
3. `test_media_store_check_passes_when_our_video_first` — мок → наш файл первый → assert push completes
4. **NEW (Codex):** `test_ms_query_parses_both_display_name_variants` — `_display_name=foo.mp4` И `display_name=foo.mp4`
5. **NEW (Codex):** `test_ms_query_parses_filename_with_special_chars` — имя с пробелами, скобками, запятыми
6. **NEW (Codex):** `test_ms_query_returns_ok_false_on_empty_output` — empty stdout → ok=False → category `media_store_unreadable_pre_publish`
7. **NEW (Codex):** `test_ms_query_returns_ok_false_on_malformed_date_added` — корректный display_name но битый date_added
8. **NEW (Codex):** `test_media_store_retry_succeeds_after_scanner_catches_up` — first 2 попытки image_newer, then succeeds → assert push completes (NO fail)
9. **NEW (Codex):** `test_media_store_equal_timestamps_passes` — `image_ts == video_ts` → not pollution (только > строго)
10. **NEW (D1.5 / Codex rollout blocker):** `test_media_store_pollution_sets_publish_task_failed` — full call chain: pollution → return None → run_publish_task → status='failed' + error_code='media_store_pollution_pre_publish'

**Gallery picker (D2/D3):**
11. `test_gallery_picker_fail_fast_when_no_video_candidate` — мок UI без 'видео' content-desc, есть all_clickable → assert no tap, return False, error event с category и `first_clickables` array
12. `test_editor_loop_fail_fast_when_no_video_in_re_select` — тот же для editor loop
13. **NEW (Codex):** `test_gallery_picker_no_blind_tap_on_fail` — при fail-fast НЕ должен быть adb_tap(540, 721) или любой blind coord
14. **NEW (Codex):** `test_gallery_picker_artifacts_saved_on_fail` — при fail-fast `_save_debug_artifacts` И `_safe_kb_probe` вызваны

**Cleanup (D4):**
15. `test_cleanup_pre_push_includes_screen_recorder` — assert glob включает все варианты Screenrecorder/Screen Recorder/etc

**Duration (D5):**
16. `test_duration_mismatch_aborts_before_share` — мок editor UI с длительностью X, ожидание Y, |X-Y|>2 → return False
17. `test_duration_mismatch_skipped_when_unparsable` — UI без duration markers → check skipped, продолжает
18. **NEW (Codex):** `test_duration_parses_localized_formats` — `0:05`, `00:05`, `5 сек.`, `5 sec` — все возвращают 5
19. **NEW (Codex):** `test_duration_handles_multiple_markers` — UI с несколькими time strings → выбираем правильный (max или специфический контейнер?), не первый попавшийся

### Integration (опционально, если есть testbench access)
9. На testbench (phone #19): задать публикацию с pre-pollution screenshot в /sdcard/Pictures/Screenshots/ → expect fail с media_store_pollution
10. На testbench: задать публикацию с pre-pollution video в /sdcard/Movies/Screenrecorder/ → expect cleanup + successful publish

### Smoke (manual после деплоя)
11. Live phone 142 / clickpay_app: задать одну тестовую публикацию → проверить что не воспроизводится

---

## 6. Rollout

1. Implement в worktree (`spec-c-ig-gallery-hardening-20260508`)
2. Все 8 unit-тестов зелёные
3. Pre-flight на testbench (phone #19) — если возможно
4. Cherry-pick в prod main → auto-push hook деплоит на VPS
5. Monitor: `awaiting_url` count за следующие 24 часа должен упасть к 0; `media_store_pollution_pre_publish` events должны появиться (как метрика поллюции, для доделки cleanup)

---

## 7. Open questions для проверки в проде

- Где IG editor показывает duration? Парсить content-desc на seek-bar / на тайле / в title?
- Есть ли content-desc с «видео» во всех IG-локализациях, которые мы используем (рус, англ, прочие)?
- Какие еще media-pollution каталоги существуют на наших Samsung-моделях?
