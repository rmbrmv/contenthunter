# Spec — IG Gallery Mode C+D Hardening (2026-05-12)

**Дата:** 2026-05-12
**Branch:** `fix-ig-gallery-mode-c-d-20260512` (code: GenGo2/delivery-contenthunter; docs: rmbrmv/contenthunter)
**Trigger:** 9 IG fails / 24ч с `error_code='ig_gallery_no_video_candidate'`, скрывающие 4 разных upstream state'а

---

## 1. Background

### Что наблюдается

За 24 часа (2026-05-12) 9 IG публикаций упали с `error_code='ig_gallery_no_video_candidate'`. Распределение по визуальному state'у (через `screenshot_url` + `events[].meta.first_clickables`):

| Visual mode | Кол-во | Описание | Samples |
|---|---:|---|---|
| **D — Play Store overlay** | 4/9 | Google Play Store страница TikTok Studio (Установить, 4,7★, скриншоты, bottom-nav Игры/Приложения/Поиск/Книги) | 5031, 5026, 4937, 4857 |
| **F — IG Story mode** | 3/9 | IG Stories preview с emoji-row + sticker «Задайте вопрос…» — НЕ Reels | 4869, 4930, 4861 |
| **E — Editor с нашим клипом** | 1/9 | Reels editor preloaded с правильным клипом (Property «Мечта №24», 0:03/0:10) | 4932 |
| **G — Editor с чужим клипом** | 1/9 | Reels editor с не нашим контентом (estate_m.ivanov, мужчина в очках, 0:09/0:57) | 4938 |

`error_code='ig_gallery_no_video_candidate'` — это **observability code smell**: 4 разных причины поверх одного fail-fast.

### Root cause анализ

Дамп `task5031_dump_after.xml` (`after step4_initial`, 12:26:04 UTC) содержит:
- `com.instagram.android:id/clips_action_bar` (editor action bar)
- `com.instagram.android:id/clips_action_bar_add_clips_button` (editor «Добавить клипы»)
- `com.instagram.android:id/clips_template_browser_fragment_holder` (Templates browser)
- `com.instagram.android:id/clips_post_capture_controls`

Это значит: на момент **после `Шаг 4 blind-tap (95, 1995)`** экран = **Templates browser / Reels editor**, не gallery picker.

Screenshot post-task (Play Store) сделан 65 секунд позже — за это время **Шаг 5 retry-loop** дополнительно тапает `(95, 1995)` **до 5 раз** (`publisher_instagram.py:1629`), и каждый промахнутый tap уводит state дальше: IG camera → Templates → ... → Play Store (через handler share-intent с предыдущего TT flow / Recents button proximity).

#### Точные code paths

`/root/.openclaw/workspace-genri/autowarm/publisher_instagram.py`:

- **Шаг 4 line 1596-1605**: `tap_element(['Галерея','Gallery','галерея'])` text-based — если не нашёл, **`self.adb_tap(95, 1995)` blind-tap**. Hardcoded координата.
- **Шаг 5 break-loop line 1613-1630**: 5 attempts; break-condition `'Добавление' or 'Выбрать' or 'Недавние' or 'gallery' or 'Миниатюра' in ui` (overly permissive substring matching); если не break — **снова `adb_tap(95, 1995)`** (line 1629).
- **Шаг 5 video parse line 1642-1693**: 5 attempts искать `'видео' in content-desc.lower()`.
- **fail-fast line 1695-1714**: `ig_gallery_no_video_candidate`.

В сумме до **6 blind-tap'ов** `(95, 1995)` на task, каждый из которых может hijack foreground.

#### Почему предыдущие фиксы (Mode A 2026-05-10, PR #36 2026-05-12) не закрыли

- **Mode A (`_dismiss_camera_permission_dialog`)** — закрывает только Android permission overlay. Здесь permission уже granted (sticky).
- **PR #36 Layer A** — pre-tap verify «candidate == our push» — срабатывает ПОСЛЕ нахождения video_candidates. Здесь video_candidates = пусто, Layer A не достигнут.
- **PR #36 Layer B** — editor-loop branch detection (`cam_dest_template` / `clips_action_bar_add_clips_button`) — внутри editor-loop (line 1750-1788, 1885-1930). На path `ig_gallery_no_video_candidate` (line 1695, **первичный** picker fail) ещё не доходим до editor-loop.
- **PR #36 Layer C** — diag dump перед picker tap — добавляется ПОСЛЕ Layer A passes.
- **PR #36 Layer D** — multi-clip detect перед Share — после editor.

Так что все 4 layer'а PR #36 защищают **другую** часть pipeline (picker → editor → caption → share), а Mode C/D/E/F/G происходят **до** picker'а — на этапе Шаг 4 (gallery opening).

---

## 2. Goals

1. **Удалить hardcoded blind-tap `(95, 1995)`** из Шаг 4 (line 1603) и Шаг 5 retry (line 1629).
2. **Заменить на resource-id-based bounds lookup** gallery preview thumbnail на camera screen.
3. **Добавить pre-Шаг-5 state guard** с distinct `error_code` под каждый actual mode:
   - `ig_external_app_foreground` (Mode D — Play Store / launcher / etc)
   - `ig_camera_mode_drift_to_story` (Mode F)
   - `ig_editor_preloaded_pre_picker` (Mode E + G)
   - `ig_gallery_button_not_found` (Шаг 4 не нашёл gallery anchor)
4. **Заменить overly-permissive `any(kw in ui)` break-condition** на resource-id-based predicate (`gallery_grid_item_thumbnail` / `gallery_destination_item`).
5. **Observability win:** аналитика error-code distribution показывает реальный upstream state, не сваленный в один bucket.

**Non-goals (PR2):**
- Recovery actions (force-stop Play Store, switch Reels-mode, skip-picker-when-editor-preloaded).
- IG version drift detection.
- Phone-state preflight (raspberry=9 Play Store overlay частота).

---

## 3. Design

### 3.1 Шаг 4 — gallery anchor lookup (заменяет blind-tap)

**Текущий код** (`publisher_instagram.py:1592-1607`):

```python
gallery_tapped = self.tap_element(ui, ['Галерея', 'Gallery', 'галерея'])
if not gallery_tapped:
    log.info('  Галерея через текст не найдена — тапаем (95,1995)')
    self._log_blind_tap_diag('before', 'step4_initial', ui_xml=ui)
    self.adb_tap(95, 1995)
    time.sleep(4)
    self._log_blind_tap_diag('after', 'step4_initial')
else:
    time.sleep(4)
```

**Новый код:**

```python
gallery_tapped = self.tap_element(ui, ['Галерея', 'Gallery', 'галерея'])
if not gallery_tapped:
    # Bounds lookup gallery preview thumbnail on Reels camera screen.
    # resource-id known IG markers in priority order.
    gallery_coord = self._find_gallery_anchor_coord(ui)
    if gallery_coord is None:
        # Structured fail-fast: blind-tap (95, 1995) removed
        # (Mode C+D hardening 2026-05-12). Каждый blind-tap имел
        # шанс hijack foreground на Play Store / Templates / etc.
        self._save_debug_artifacts('ig_gallery_button_not_found')
        self._safe_kb_probe(ui, step='ig_gallery_button_not_found')
        self.log_event(
            'error',
            'IG: gallery anchor не найден на camera screen — fail-fast',
            meta={'category': 'ig_gallery_button_not_found',
                  'platform': self.platform,
                  'step': 'gallery_open',
                  'foreground_package': self._current_foreground_package(),
                  'visible_markers': self._collect_state_markers(ui)},
        )
        return False
    cx, cy = gallery_coord
    self.adb_tap(cx, cy)
    time.sleep(4)
else:
    time.sleep(4)
```

#### `_find_gallery_anchor_coord` helper

Возвращает `(cx, cy)` или `None`. Ищет в этом порядке:

1. Node с `resource-id` matching одного из:
   - `gallery_grid_camera_item_icon`
   - `gallery_destination_item`
   - `media_thumbnail_tray_preview_image`
   - `preview_thumbnail_button` (legacy)
2. Если ни одно не найдено — `None`.

`bounds` атрибут парсится в `(cx, cy)`; clickable=true required.

Why: эти resource-id — стабильные IG identifiers gallery preview thumbnail в Reels camera (post-mortem `project_ig_publish_cross_project_leak_2026_05_12.md` уже использует `gallery_grid_item_thumbnail` и `gallery_destination_item`).

#### `_collect_state_markers(ui)` helper

Возвращает list[str] visible IG state markers (для evidence в meta при fail-fast). Markers:

| Marker substring (resource-id) | State |
|---|---|
| `clips_action_bar` | editor |
| `clips_template_browser_fragment_holder` | templates browser |
| `cam_dest_template` | templates tab |
| `cam_dest_clips` | reels tab |
| `cam_dest_story` | story tab |
| `gallery_grid_item_thumbnail` | gallery picker open |
| `gallery_destination_item` | gallery destinations visible |
| `share_button` | caption screen |

### 3.2 Pre-Шаг-5 state guard

**Вставляется ДО** `for attempt in range(5)` break-loop (между line 1607 и 1609).

```python
# === Pre-Шаг-5 state guard (Mode C+D hardening 2026-05-12) ===
ui = self.dump_ui()
guard_result = self._classify_pre_picker_state(ui)
if guard_result['mode'] != 'ok':
    self._save_debug_artifacts(f'ig_{guard_result["error_code"]}')
    self._safe_kb_probe(ui, step=guard_result['error_code'])
    self.log_event(
        'error',
        guard_result['log_message'],
        meta={'category': guard_result['error_code'],
              'platform': self.platform,
              'step': 'gallery_open',
              'foreground_package': self._current_foreground_package(),
              'visible_markers': self._collect_state_markers(ui)},
    )
    return False
```

#### `_classify_pre_picker_state(ui)` decision tree

Returns dict `{'mode': str, 'error_code': str, 'log_message': str}`.

| Detection (in order) | mode | error_code |
|---|---|---|
| foreground package != `com.instagram.android` | `external_app` | `ig_external_app_foreground` |
| `clips_template_browser_fragment_holder` in UI OR `cam_dest_template` matched as selected | `templates_browser` | `ig_camera_mode_drift_to_templates` |
| `cam_dest_story` matched as selected (Story tab) | `story_mode` | `ig_camera_mode_drift_to_story` |
| `clips_editor_video_track_recyclerview` OR `share_button` OR `clips_action_bar_add_clips_button` in UI | `editor_preloaded` | `ig_editor_preloaded_pre_picker` |
| `gallery_grid_item_thumbnail` in UI | `ok` (gallery already open) | — |
| Other (clean camera, gallery not yet open) | `ok` | — |

#### `_current_foreground_package()` helper

Возвращает str package name. Реализация:

```python
out = self.adb('dumpsys activity activities | grep topResumedActivity').strip()
# 'topResumedActivity=ActivityRecord{... com.instagram.android/...'
m = re.search(r'ActivityRecord\{[^ ]+\s+\S+\s+([\w.]+)/', out)
return m.group(1) if m else 'unknown'
```

### 3.3 Шаг 5 break-loop — заменить permissive substring

**Текущий** (`publisher_instagram.py:1624`):

```python
if any(kw in ui for kw in ['Добавление', 'Выбрать', 'Недавние', 'gallery', 'Миниатюра']):
    log.info('✅ Галерея открыта')
    break
```

**Новый:**

```python
if 'gallery_grid_item_thumbnail' in ui or 'gallery_destination_item' in ui:
    log.info('✅ Галерея открыта (resource-id match)')
    break
```

`gallery_grid_item_thumbnail` — стабильный IG resource-id thumbnail в picker grid. Substring match по resource-id безопаснее, чем по visible-text labels, которые могут пересекаться с editor markers.

### 3.4 Шаг 5 retry blind-tap — удалить

**Текущий** (`publisher_instagram.py:1627-1630`):

```python
log.info(f'  Галерея не открыта (попытка {attempt}), ui: {ui[:100]}')
self.adb_tap(95, 1995)
time.sleep(2)
```

**Новый:**

```python
log.info(f'  Галерея не открыта (попытка {attempt})')
time.sleep(2)
```

Удалена `adb_tap(95, 1995)`. Если Шаг 4 не открыл gallery, retry blind-tap ещё хуже — может довести state до Play Store / editor. Лучше дать IG время через `time.sleep(2)` (на случай slow UI).

Если за 5 attempt'ов gallery так и не открылась → попадаем в video parse loop → 0 candidates → existing fail-fast (line 1695). НО уже с meaningful meta из pre-guard.

---

## 4. Data model — error_code naming

Все новые error_code идут в существующую `publish_tasks.error_code` колонку. Triage analytics (memory `feedback_publisher_error_code_misleading`) группирует по `events[-1].meta.category`.

| Новый error_code | Описание | Заменяет какие случаи |
|---|---|---|
| `ig_gallery_button_not_found` | Шаг 4: ни text 'Галерея', ни resource-id gallery anchor не найден | Часть `ig_gallery_no_video_candidate` где Шаг 4 промахнулся |
| `ig_external_app_foreground` | Mode D: foreground package != `com.instagram.android` | 4/9 samples 2026-05-12 |
| `ig_camera_mode_drift_to_templates` | Mode D-templates: cam_dest_template selected | (новый) |
| `ig_camera_mode_drift_to_story` | Mode F: cam_dest_story selected | 3/9 samples 2026-05-12 |
| `ig_editor_preloaded_pre_picker` | Mode E+G: editor открыт до того как Шаг 5 начался | 2/9 samples 2026-05-12 |

После деплоя ожидаем `ig_gallery_no_video_candidate` упадёт до ~0 (если все samples реально классифицируются под новые коды), либо останется только для случаев когда gallery picker реально открыт но video не парсится (это другая природа — IG version drift / unusual content).

---

## 5. Тестирование (TDD)

### 5.1 Unit tests (новые helper'ы)

`tests/test_ig_gallery_anchor_lookup.py`:

1. `_find_gallery_anchor_coord` — fixture XML с `gallery_grid_camera_item_icon` bounds=[80,1950][120,2010] → returns (100, 1980)
2. `_find_gallery_anchor_coord` — fixture без gallery resource-id → returns None
3. `_find_gallery_anchor_coord` — fixture с `gallery_destination_item` (fallback resource-id) → returns valid coords
4. `_find_gallery_anchor_coord` — fixture с `clickable=false` gallery node → returns None

`tests/test_ig_pre_picker_state_classifier.py`:

1. Clean Reels camera UI → `mode='ok'`
2. Play Store dump → `mode='external_app'`, `error_code='ig_external_app_foreground'` (mocked `_current_foreground_package` → `com.android.vending`)
3. Templates browser (`clips_template_browser_fragment_holder` present) → `mode='templates_browser'`
4. Story mode (`cam_dest_story` selected=true) → `mode='story_mode'`
5. Editor preloaded (`clips_editor_video_track_recyclerview`) → `mode='editor_preloaded'`
6. Gallery already open (`gallery_grid_item_thumbnail`) → `mode='ok'`

`tests/test_ig_state_markers_collector.py`:

1. UI с `clips_action_bar` + `cam_dest_clips` → returns `['clips_action_bar', 'cam_dest_clips']` (sorted)
2. UI без markers → returns `[]`

### 5.2 Integration check (manual)

После деплоя:
1. Re-queue task 5031 (clickpay_under, raspberry=9) через `UPDATE publish_queue SET status='pending'` → ожидаем `error_code='ig_external_app_foreground'` ИЛИ успех (если Play Store ad не воспроизводится).
2. Re-queue 4869 (clickpay_life Story mode) → ожидаем `ig_camera_mode_drift_to_story`.
3. SQL верификация через 24ч после deploy:
   ```sql
   SELECT error_code, COUNT(*)
   FROM publish_tasks
   WHERE platform='Instagram' AND status='failed' AND testbench=false
     AND created_at > '<deploy_ts>'
   GROUP BY error_code ORDER BY count(*) DESC;
   ```
   Ожидаемое distribution: `ig_gallery_no_video_candidate` падает до 0-2 / 24ч; новые коды покрывают остальное.

### 5.3 Pre-existing tests

`pytest tests/` должен оставаться green. Pre-existing fails (validator anthropic mocks per memory `project_validator_stale_generate_description_tests`) — не блокеры.

---

## 6. Roll-out

1. **Branch:** `fix-ig-gallery-mode-c-d-20260512` (GenGo2/delivery-contenthunter).
2. **PR target:** `main` (auto-pull на prod через `/root/.openclaw/workspace-genri/autowarm/` post-commit hook).
3. **PM2 restart:** не требуется — `publisher.py` запускается subprocess per-task через server.js, новые spawn'ы автоматически читают свежий код (per memory `project_ig_publish_cross_project_leak_2026_05_12.md`).
4. **Smoke validate:** unit tests + поиск нового error_code в DB через 1-2 IG slot'а (01:50 / 05:57 МСК).
5. **Live verify deadline:** 7d post-merge — SQL count'ы по новым error_code в evidence-файле.

---

## 7. Codex review checklist

Per memory `feedback_codex_review_specs`:
- Spec round 1: ожидать P1 вокруг foreground package detection (timing race?), tests (mocking ADB output), `_collect_state_markers` дедупликации, helper visibility (mixin vs base).
- Implementation round 1: ожидать P1 вокруг exact resource-id strings (typos), `tap_element` integration, save_debug_artifacts naming.

Цель: 0 P1 на обоих раундах перед user review.

---

## 8. Связанные

- `project_ig_publish_cross_project_leak_2026_05_12.md` — PR #36 Layer A/B/C/D (другая часть pipeline, не overlap)
- `project_ig_gallery_no_video_2026_05_10.md` — Mode A shipped, Mode B closed pending re-occurrence (now Mode B = Play Store overlay re-confirmed)
- `feedback_publisher_error_code_misleading` — error_code в publish_tasks нужно группировать по последнему meta.category
- `feedback_publish_fail_analysis_video_first` — screencast first для триажа (применено: 9 screenshots проанализированы)
- `feedback_codex_review_specs` — codex review до 0 P1 перед user review
- `feedback_parallel_claude_sessions` — atomic commits, не оставлять half-broken state
