# WP#203 — Детерминированный in-app upload для TikTok — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить флаки SEND-intent fallback на детерминированный внутренний аплоад TikTok (камера→галерея→свежее видео с верификацией длительности→редактор), уйдя от системного share и Samsung-оверлея.

**Architecture:** Новая ветка в `publish_tiktok`: при `«+»`→камера вместо `SystemShareActivity` SEND-intent открываем внутреннюю галерею TikTok тайлом-миниатюрой, фильтруем «Видео», выбираем тайл с совпадающей длительностью, входим в редактор. Samsung-оверлей детектим по foreground-пакету (XML слеп) и снимаем escalating BACK. Сбой → честный `tt_*` код → ручная. Всё под kill-switch (OFF = legacy SEND-intent).

**Tech Stack:** Python 3, `publisher_tiktok.py` (`TikTokMixin`), `publisher_base.py` (`BasePublisher`), pytest, ffprobe (subprocess), Postgres-миграция для каталога error-кодов.

**Спека:** `docs/superpowers/specs/2026-05-31-wp203-tt-inapp-upload-design.md`
**Разведка/координаты:** `docs/evidence/2026-05-31-wp203-tt-inapp-upload-recon.md`

**Репозиторий кода:** `autowarm-testbench` (НЕ contenthunter). На этапе исполнения создать worktree off `origin/main` (skill `using-git-worktrees`), НИКОГДА `checkout -b` в общем чекауте.

**Тест-харнес (существующий, `tests/test_publisher_tt_overlay_handlers.py`):**
- `_xml(nodes_attrs)` — собирает минимальный UI-XML из списка dict-нод.
- `_bare_mixin()` — `TikTokMixin.__new__`, выставляет `platform='TikTok'`, `_init_wait_upload_overlay_state()`, моки `log_event/adb/adb_tap/set_step/tap_element`, `dump_ui` НЕ замокан по умолчанию (мокать в тесте через `MagicMock`).

---

## File Structure

- **Modify** `publisher_tiktok.py`:
  - класс-константы WP#203 (рядом с `_TT_*` ~строка 302);
  - `_init_wait_upload_overlay_state` (+counter `_storyservice_fg_iter`);
  - новые методы: `_tt_foreground_pkg`, `_tt_detect_camera_screen`, `_tt_in_gallery_picker`, `_tt_parse_gallery_video_tiles`, `_tt_tap_gallery_video_tab`, `_tt_tap_gallery_next`, `_tt_select_newest_gallery_video`, `_tt_enter_upload_from_camera`, `_tt_recover_from_storyservice_fg`, `_tt_inapp_upload_from_camera`;
  - врезка в `publish_tiktok` (блок `if not in_editor:`, строки 1963-1991 origin/main).
- **Modify** `publisher_base.py`: `_probe_duration_s` (рядом с `_probe_mp4` ~строка 2818).
- **Create** `tests/test_publisher_tt_inapp_upload.py` — unit-тесты всех новых юнитов.
- **Create** `migrations/20260531_wp203_tt_inapp_upload_codes.sql` (+ `__rollback.sql`).

---

## Task 1: Класс-константы WP#203

**Files:**
- Modify: `publisher_tiktok.py` (после строки 301, в блоке класс-констант `TikTokMixin`)

- [ ] **Step 1: Добавить константы**

В `publisher_tiktok.py` сразу после существующих `MAX_INAPP_STORIES_ITERATIONS = 3` (стр. 301) добавить:

```python
    # ─── WP#203: детерминированный in-app upload через камеру ──────────
    _TT_CAMERA_MODE_TABS = ('ФОТО', 'ТЕКСТ', 'ЭФИР', 'ПУБЛИКАЦИЯ', 'ТВОРЧЕСТВО')
    _TT_GALLERY_TAB_LABELS = ('Все', 'Видео', 'Фото')
    _TT_GALLERY_VIDEO_TAB = ('Видео', 'Videos')
    _TT_GALLERY_NEXT_LABELS = ('Далее', 'Next')
    _TT_GALLERY_THUMB_COORD = (112, 2126)   # fallback вход в галерею (низ-лево, 1080×2340)
    _TT_STORYSERVICE_PKG = 'com.samsung.storyservice'
    _TT_LAUNCHER_PKG_SUBSTRINGS = ('launcher',)
    MAX_INAPP_UPLOAD_ITERATIONS = 8
    MAX_STORYSERVICE_FG_ITERATIONS = 4
    _TT_DURATION_TOLERANCE_S = 1
    _TT_EDITOR_PROGRESS_MARKERS = ('Далее', 'Next', 'Звуки', 'Эффекты', 'Автомонтаж')
```

- [ ] **Step 2: Smoke-импорт**

Run: `cd autowarm-testbench && python -c "from publisher_tiktok import TikTokMixin; print(TikTokMixin.MAX_INAPP_UPLOAD_ITERATIONS)"`
Expected: `8`

- [ ] **Step 3: Commit**

```bash
git add publisher_tiktok.py
git commit -m "feat(wp203): класс-константы in-app upload TikTok"
```

---

## Task 2: counter `_storyservice_fg_iter` в init-state

**Files:**
- Modify: `publisher_tiktok.py` (`_init_wait_upload_overlay_state`, ~стр. 337-341)

- [ ] **Step 1: Тест — counter сбрасывается**

В новый файл `tests/test_publisher_tt_inapp_upload.py` (шапку взять из `test_publisher_tt_overlay_handlers.py`: импорты, `_xml`, `_bare_mixin`) добавить:

```python
def test_init_resets_storyservice_fg_iter():
    mx = _bare_mixin()
    mx._storyservice_fg_iter = 7
    mx._init_wait_upload_overlay_state()
    assert mx._storyservice_fg_iter == 0
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py::test_init_resets_storyservice_fg_iter -v`
Expected: FAIL (AttributeError или AssertionError — counter не сбрасывается)

- [ ] **Step 3: Реализация**

В `_init_wait_upload_overlay_state` после `self._amplify_iter = 0` добавить:

```python
        self._storyservice_fg_iter = 0  # WP#203 foreground overlay guard
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py::test_init_resets_storyservice_fg_iter -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): сброс _storyservice_fg_iter в init-state + тест"
```

---

## Task 3: `_tt_foreground_pkg` — foreground-пакет (не-XML сигнал)

**Files:**
- Modify: `publisher_tiktok.py` (новый метод после детекторов, ~после стр. 423)
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты**

```python
def test_foreground_pkg_musically():
    mx = _bare_mixin()
    mx.adb = MagicMock(return_value=(
        '      topResumedActivity=ActivityRecord{2396e73 u0 '
        'com.zhiliaoapp.musically/com.ss.android.ugc.aweme.adaptation.saa.'
        'SAASceneWrapperActivity t2360}'))
    assert mx._tt_foreground_pkg() == 'com.zhiliaoapp.musically'

def test_foreground_pkg_storyservice():
    mx = _bare_mixin()
    mx.adb = MagicMock(return_value=(
        'topResumedActivity=ActivityRecord{abc u0 '
        'com.samsung.storyservice/.SomeActivity t99}'))
    assert mx._tt_foreground_pkg() == 'com.samsung.storyservice'

def test_foreground_pkg_unparseable():
    mx = _bare_mixin()
    mx.adb = MagicMock(return_value='')
    assert mx._tt_foreground_pkg() == ''
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k foreground_pkg -v`
Expected: FAIL (AttributeError: метод не определён)

- [ ] **Step 3: Реализация**

```python
    def _tt_foreground_pkg(self) -> str:
        """Package of the resumed activity (non-XML signal).

        The Samsung «Добавить в историю» overlay is a system window that
        uiautomator can't dump (returns the launcher), so the foreground
        package is the only reliable detection signal for it. Returns '' if
        unparseable.
        """
        import re
        out = self.adb(
            'dumpsys activity activities 2>/dev/null '
            '| grep -m1 topResumedActivity', timeout=8) or ''
        m = re.search(r'u0\s+([\w.]+)/', out)
        return m.group(1) if m else ''
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k foreground_pkg -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_foreground_pkg + тесты"
```

---

## Task 4: `_tt_detect_camera_screen` — детект камеры (чистая)

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты**

```python
def test_detect_camera_two_mode_tabs():
    mx = _bare_mixin()
    ui = _xml([{'text': 'ФОТО'}, {'text': 'ПУБЛИКАЦИЯ'}, {'text': 'ТВОРЧЕСТВО'}])
    assert mx._tt_detect_camera_screen(ui) is True

def test_detect_camera_one_tab_is_not_enough():
    mx = _bare_mixin()
    ui = _xml([{'text': 'ПУБЛИКАЦИЯ'}])
    assert mx._tt_detect_camera_screen(ui) is False

def test_detect_camera_negative_on_gallery():
    mx = _bare_mixin()
    ui = _xml([{'text': 'Все'}, {'text': 'Видео'}, {'text': 'Фото'}])
    assert mx._tt_detect_camera_screen(ui) is False
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k detect_camera -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Реализация**

```python
    def _tt_detect_camera_screen(self, ui_xml: str) -> bool:
        """TikTok create camera (SAASceneWrapperActivity) — positive when the
        dump shows ≥2 distinct mode tabs (ФОТО/ТЕКСТ/ЭФИР/ПУБЛИКАЦИЯ/ТВОРЧЕСТВО).
        Камера дампится нормально (разведка №19); XML-слепота касается только
        Samsung-оверлея (см. _tt_recover_from_storyservice_fg)."""
        if not ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        seen = set()
        for n in root.iter('node'):
            t = (n.get('text', '') or '').strip()
            if t in self._TT_CAMERA_MODE_TABS:
                seen.add(t)
        return len(seen) >= 2
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k detect_camera -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_detect_camera_screen + тесты"
```

---

## Task 5: `_tt_in_gallery_picker` — детект галереи (чистая)

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты**

```python
def test_in_gallery_positive():
    mx = _bare_mixin()
    ui = _xml([{'text': 'Все'}, {'content-desc': 'Видео'}, {'text': 'Фото'},
               {'text': 'Далее'}])
    assert mx._tt_in_gallery_picker(ui) is True

def test_in_gallery_negative_camera():
    mx = _bare_mixin()
    ui = _xml([{'text': 'ФОТО'}, {'text': 'ПУБЛИКАЦИЯ'}])
    assert mx._tt_in_gallery_picker(ui) is False

def test_in_gallery_negative_no_next():
    mx = _bare_mixin()
    ui = _xml([{'text': 'Все'}, {'text': 'Видео'}, {'text': 'Фото'}])
    assert mx._tt_in_gallery_picker(ui) is False
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k in_gallery -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Реализация**

```python
    def _tt_in_gallery_picker(self, ui_xml: str) -> bool:
        """TikTok internal gallery picker — hosted in the same SAAScene activity
        (foreground unchanged), so detect by UI markers: ≥2 album tabs
        (Все/Видео/Фото) AND a «Далее» button (present, разведка №19)."""
        if not ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        tabs = set()
        has_next = False
        for n in root.iter('node'):
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            for tab in self._TT_GALLERY_TAB_LABELS:
                if tab == txt or tab == desc:
                    tabs.add(tab)
            if not has_next and (txt in self._TT_GALLERY_NEXT_LABELS
                                 or desc in self._TT_GALLERY_NEXT_LABELS):
                has_next = True
        return len(tabs) >= 2 and has_next
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k in_gallery -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_in_gallery_picker + тесты"
```

---

## Task 6: `_probe_duration_s` — длительность видео (ffprobe)

**Files:**
- Modify: `publisher_base.py` (после `_probe_mp4`, ~стр. 2840)
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты** (патчим `subprocess.run` и `os.path.exists` в модуле `publisher_base`)

```python
import publisher_base
from publisher_base import BasePublisher
from unittest.mock import patch

def _bare_base():
    return BasePublisher.__new__(BasePublisher)

def test_probe_duration_ok():
    b = _bare_base()
    fake = MagicMock(returncode=0, stdout='39.2\n', stderr='')
    with patch.object(publisher_base.os.path, 'exists', return_value=True), \
         patch.object(publisher_base.subprocess, 'run', return_value=fake):
        assert b._probe_duration_s('/tmp/v.mp4') == 39.2

def test_probe_duration_url_returns_none():
    b = _bare_base()
    assert b._probe_duration_s('https://x/v.mp4') is None

def test_probe_duration_missing_returns_none():
    b = _bare_base()
    with patch.object(publisher_base.os.path, 'exists', return_value=False):
        assert b._probe_duration_s('/tmp/missing.mp4') is None

def test_probe_duration_ffprobe_error_returns_none():
    b = _bare_base()
    fake = MagicMock(returncode=1, stdout='', stderr='boom')
    with patch.object(publisher_base.os.path, 'exists', return_value=True), \
         patch.object(publisher_base.subprocess, 'run', return_value=fake):
        assert b._probe_duration_s('/tmp/v.mp4') is None
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k probe_duration -v`
Expected: FAIL (AttributeError: `_probe_duration_s`)

- [ ] **Step 3: Реализация** (в `publisher_base.py`, сразу после метода `_probe_mp4`)

```python
    def _probe_duration_s(self, path: str):
        """Длительность видео в секундах через ffprobe, или None если путь —
        URL / файла нет / ошибка ffprobe. Переиспользует паттерн `_probe_mp4`.
        WP#203: вторичная верификация выбора видео в галерее по длительности."""
        if not path or path.startswith('http://') or path.startswith('https://'):
            return None
        if not os.path.exists(path):
            return None
        try:
            cmd = (f'ffprobe -v error -show_entries format=duration '
                   f'-of default=nw=1:nk=1 "{path}"')
            r = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=15)
            if r.returncode != 0:
                return None
            s = (r.stdout or '').strip()
            return float(s) if s else None
        except Exception:
            return None
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k probe_duration -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_base.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _probe_duration_s (ffprobe) + тесты"
```

---

## Task 7: `_tt_parse_gallery_video_tiles` — тайлы+длительность (чистая)

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты**

```python
def _tile(x1, y1, x2, y2, clickable='true'):
    return {'clickable': clickable, 'bounds': f'[{x1},{y1}][{x2},{y2}]'}

def test_parse_tiles_with_durations_sorted_newest_first():
    mx = _bare_mixin()
    # 2 тайла (строка y=364..721) + оверлеи MM:SS внутри них
    ui = _xml([
        _tile(6, 364, 358, 721),     # tile A (left)  -> 00:39
        _tile(364, 364, 716, 721),   # tile B (right) -> 00:56
        {'text': '00:39', 'bounds': '[223,656][300,700]'},
        {'text': '00:56', 'bounds': '[581,656][658,700]'},
    ])
    tiles = mx._tt_parse_gallery_video_tiles(ui)
    assert [t['dur'] for t in tiles] == [39, 56]      # newest-first: A then B
    assert tiles[0]['center'] == (182, 542)

def test_parse_tiles_tile_without_overlay_has_none_dur():
    mx = _bare_mixin()
    ui = _xml([_tile(6, 364, 358, 721)])
    tiles = mx._tt_parse_gallery_video_tiles(ui)
    assert tiles[0]['dur'] is None

def test_parse_tiles_ignores_small_or_top_nodes():
    mx = _bare_mixin()
    ui = _xml([_tile(45, 231, 355, 358)])   # вкладка-зона (y1<300) — не тайл
    assert mx._tt_parse_gallery_video_tiles(ui) == []
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k parse_tiles -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Реализация**

```python
    def _tt_parse_gallery_video_tiles(self, ui_xml: str):
        """Видео-тайлы галереи → [{'center':(x,y),'bounds':(x1,y1,x2,y2),
        'dur':int|None}], отсортированы newest-first (верхняя строка, слева
        направо). 'dur' — из оверлея MM:SS, чей центр попадает в bounds тайла.
        Тайлы без content-desc (голые ImageView, разведка №19) → выбор по
        позиции + верификация по длительности."""
        import re
        if not ui_xml:
            return []
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return []

        def _b(s):
            m = re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', s or '')
            return tuple(int(m.group(i)) for i in (1, 2, 3, 4)) if m else None

        tiles = []
        durations = []  # (cx, cy, seconds)
        for n in root.iter('node'):
            b = _b(n.get('bounds', ''))
            if not b:
                continue
            x1, y1, x2, y2 = b
            t = (n.get('text', '') or '').strip()
            mm = re.match(r'^(\d{1,2}):(\d{2})$', t)
            if mm:
                durations.append(((x1 + x2) // 2, (y1 + y2) // 2,
                                  int(mm.group(1)) * 60 + int(mm.group(2))))
                continue
            if (n.get('clickable') == 'true'
                    and (x2 - x1) > 200 and (y2 - y1) > 200 and y1 > 300):
                tiles.append((x1, y1, x2, y2))

        result = []
        for x1, y1, x2, y2 in tiles:
            dur = None
            for cx, cy, d in durations:
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    dur = d
                    break
            result.append({'center': ((x1 + x2) // 2, (y1 + y2) // 2),
                           'bounds': (x1, y1, x2, y2), 'dur': dur})
        result.sort(key=lambda r: (r['bounds'][1], r['bounds'][0]))
        return result
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k parse_tiles -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_parse_gallery_video_tiles + тесты"
```

---

## Task 8: `_tt_tap_gallery_video_tab` + `_tt_tap_gallery_next` (действия)

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты**

```python
def test_tap_video_tab_taps_center():
    mx = _bare_mixin()
    ui = _xml([{'content-desc': 'Видео', 'clickable': 'true',
                'bounds': '[355,231][707,358]'}])
    assert mx._tt_tap_gallery_video_tab(ui) is True
    mx.adb_tap.assert_called_once_with(531, 294)

def test_tap_video_tab_absent():
    mx = _bare_mixin()
    ui = _xml([{'text': 'ФОТО', 'clickable': 'true', 'bounds': '[0,0][100,100]'}])
    assert mx._tt_tap_gallery_video_tab(ui) is False
    mx.adb_tap.assert_not_called()

def test_tap_gallery_next_taps_center():
    mx = _bare_mixin()
    ui = _xml([{'text': 'Далее', 'clickable': 'true',
                'bounds': '[551,2036][1046,2160]'}])
    assert mx._tt_tap_gallery_next(ui) is True
    mx.adb_tap.assert_called_once_with(798, 2098)
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k "video_tab or gallery_next" -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Реализация**

```python
    def _tt_tap_gallery_video_tab(self, ui_xml: str) -> bool:
        """Тап вкладки «Видео» галереи (фильтр от фото/скриншотов). True если тапнули."""
        return self._tt_tap_label(ui_xml, self._TT_GALLERY_VIDEO_TAB)

    def _tt_tap_gallery_next(self, ui_xml: str) -> bool:
        """Тап кнопки «Далее» галереи (для multi-select режима). True если тапнули."""
        return self._tt_tap_label(ui_xml, self._TT_GALLERY_NEXT_LABELS)

    def _tt_tap_label(self, ui_xml: str, labels) -> bool:
        """Тап центра первого clickable-узла с точным text/content-desc из labels."""
        import re
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml or '')
        except Exception:
            return False
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if txt in labels or desc in labels:
                m = re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', n.get('bounds', ''))
                if m:
                    self.adb_tap((int(m.group(1)) + int(m.group(3))) // 2,
                                 (int(m.group(2)) + int(m.group(4))) // 2)
                    return True
        return False
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k "video_tab or gallery_next" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_tap_gallery_video_tab/_next + _tt_tap_label + тесты"
```

---

## Task 9: `_tt_select_newest_gallery_video` — выбор с верификацией длительности

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты** (мокаем `dump_ui` на пост-фильтровый дамп)

```python
def _gallery_two_videos_xml():
    return _xml([
        {'content-desc': 'Видео', 'clickable': 'true', 'bounds': '[355,231][707,358]'},
        {'text': 'Все', 'bounds': '[73,231][327,358]'},
        {'text': 'Фото', 'bounds': '[735,231][1007,358]'},
        {'text': 'Далее', 'clickable': 'true', 'bounds': '[551,2036][1046,2160]'},
        {'clickable': 'true', 'bounds': '[6,364][358,721]'},      # tile A (newest) 00:39
        {'clickable': 'true', 'bounds': '[364,364][716,721]'},    # tile B 00:56
        {'text': '00:39', 'bounds': '[223,656][300,700]'},
        {'text': '00:56', 'bounds': '[581,656][658,700]'},
    ])

def test_select_matches_expected_duration_picks_that_tile():
    mx = _bare_mixin()
    mx.dump_ui = MagicMock(return_value=_gallery_two_videos_xml())
    # expected ~56s → должен выбрать tile B (center 540,542), не первый
    res = mx._tt_select_newest_gallery_video(_gallery_two_videos_xml(), 56.0)
    assert res == 'tapped'
    mx.adb_tap.assert_any_call(540, 542)

def test_select_prefers_newest_among_matches():
    mx = _bare_mixin()
    mx.dump_ui = MagicMock(return_value=_gallery_two_videos_xml())
    res = mx._tt_select_newest_gallery_video(_gallery_two_videos_xml(), 39.4)
    assert res == 'tapped'
    mx.adb_tap.assert_any_call(182, 542)     # tile A (newest, 00:39)

def test_select_no_match_returns_no_match():
    mx = _bare_mixin()
    mx.dump_ui = MagicMock(return_value=_gallery_two_videos_xml())
    res = mx._tt_select_newest_gallery_video(_gallery_two_videos_xml(), 120.0)
    assert res == 'no_match'

def test_select_expected_none_taps_first_and_warns():
    mx = _bare_mixin()
    mx.dump_ui = MagicMock(return_value=_gallery_two_videos_xml())
    res = mx._tt_select_newest_gallery_video(_gallery_two_videos_xml(), None)
    assert res == 'tapped'
    mx.adb_tap.assert_any_call(182, 542)     # первый тайл
    assert any('tt_gallery_duration_unverified' in str(c)
               for c in mx.log_event.call_args_list)

def test_select_no_tiles_returns_no_tiles():
    mx = _bare_mixin()
    empty = _xml([{'content-desc': 'Видео', 'clickable': 'true',
                   'bounds': '[355,231][707,358]'},
                  {'text': 'Все', 'bounds': '[73,231][327,358]'},
                  {'text': 'Фото', 'bounds': '[735,231][1007,358]'},
                  {'text': 'Далее', 'clickable': 'true', 'bounds': '[551,2036][1046,2160]'}])
    mx.dump_ui = MagicMock(return_value=empty)
    assert mx._tt_select_newest_gallery_video(empty, 39.0) == 'no_tiles'
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k "select_" -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Реализация**

```python
    def _tt_select_newest_gallery_video(self, ui_xml: str, expected_dur) -> str:
        """Выбрать видео в галерее: вкладка «Видео» → тайл с верификацией по
        длительности. Возврат 'tapped' / 'no_match' / 'no_tiles'.

        Политика (WP#203): первый тайл (новейший) почти наверняка наш (пуш перед
        публикацией); длительность — вторичный гард против «новейший≠наш».
          - expected известна, совпало (±tol) → первый совпавший (новейший);
          - известна, не совпало → 'no_match' (НЕ публикуем чужое видео);
          - expected is None → первый тайл + warning;
          - тайлов нет → 'no_tiles'.
        """
        import time as _t
        if self._tt_tap_gallery_video_tab(ui_xml):
            _t.sleep(2)
            ui_xml = self.dump_ui()
        tiles = self._tt_parse_gallery_video_tiles(ui_xml)
        if not tiles:
            return 'no_tiles'
        if expected_dur is None:
            self.log_event(
                'warning',
                'TikTok: длительность не верифицирована (ffprobe N/A) — берём новейший тайл',
                meta={'category': 'tt_gallery_duration_unverified',
                      'platform': self.platform})
            self.adb_tap(*tiles[0]['center'])
            return 'tapped'
        tol = self._TT_DURATION_TOLERANCE_S
        for t in tiles:  # newest-first
            if t['dur'] is not None and abs(t['dur'] - expected_dur) <= tol:
                self.adb_tap(*t['center'])
                self.log_event(
                    'info',
                    f'TikTok: выбран видео-тайл dur={t["dur"]}s '
                    f'(ожидалось {expected_dur:.1f}s)',
                    meta={'category': 'tt_gallery_video_selected',
                          'platform': self.platform})
                return 'tapped'
        return 'no_match'
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k "select_" -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_select_newest_gallery_video (верификация длительности) + тесты"
```

---

## Task 10: `_tt_enter_upload_from_camera` — вход в галерею (действие)

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты**

```python
def test_enter_upload_taps_bottom_left_thumb():
    mx = _bare_mixin()
    ui = _xml([{'clickable': 'true', 'bounds': '[0,2047][225,2205]'}])  # id/zne
    assert mx._tt_enter_upload_from_camera(ui) is True
    mx.adb_tap.assert_called_once_with(112, 2126)

def test_enter_upload_fallback_fixed_coord():
    mx = _bare_mixin()
    ui = _xml([{'clickable': 'true', 'bounds': '[400,400][600,600]'}])  # нет угл. тайла
    assert mx._tt_enter_upload_from_camera(ui) is True
    mx.adb_tap.assert_called_once_with(112, 2126)   # fallback coord
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k enter_upload -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Реализация**

```python
    def _tt_enter_upload_from_camera(self, ui_xml: str) -> bool:
        """Открыть внутреннюю галерею из камеры тапом тайла-миниатюры внизу-слева
        (НЕ текста «ПУБЛИКАЦИЯ» — это уже выбранный режим, тап по нему бездействует,
        разведка №19). Узел — clickable в нижне-левом углу; иначе fallback на
        фикс-координату. Всегда True (тапнули кандидата)."""
        import re
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml or '')
        except Exception:
            root = None
        if root is not None:
            for n in root.iter('node'):
                if n.get('clickable') != 'true':
                    continue
                m = re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', n.get('bounds', ''))
                if not m:
                    continue
                x1, y1, x2, y2 = (int(m.group(i)) for i in (1, 2, 3, 4))
                if x1 < 250 and y1 > 1900:
                    self.adb_tap((x1 + x2) // 2, (y1 + y2) // 2)
                    return True
        self.adb_tap(*self._TT_GALLERY_THUMB_COORD)
        return True
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k enter_upload -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_enter_upload_from_camera + тесты"
```

---

## Task 11: `_tt_recover_from_storyservice_fg` — foreground-дисмисс оверлея

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты**

```python
def test_storyservice_fg_handled_back():
    mx = _bare_mixin()
    res = mx._tt_recover_from_storyservice_fg('com.samsung.storyservice', 0)
    assert res == 'handled'
    mx.adb.assert_called_with('input keyevent KEYCODE_BACK')

def test_storyservice_fg_launcher_handled():
    mx = _bare_mixin()
    res = mx._tt_recover_from_storyservice_fg('com.sec.android.app.launcher', 0)
    assert res == 'handled'

def test_storyservice_fg_clean_on_musically():
    mx = _bare_mixin()
    assert mx._tt_recover_from_storyservice_fg('com.zhiliaoapp.musically', 0) == 'clean'

def test_storyservice_fg_stuck_after_cap():
    mx = _bare_mixin()
    last = None
    for _ in range(mx.MAX_STORYSERVICE_FG_ITERATIONS + 1):
        last = mx._tt_recover_from_storyservice_fg('com.samsung.storyservice', 0)
    assert last == 'stuck'

def test_storyservice_fg_killswitch_off(monkeypatch):
    monkeypatch.setenv('TT_STORYSERVICE_FG_DISMISS_ENABLED', 'false')
    mx = _bare_mixin()
    assert mx._tt_recover_from_storyservice_fg('com.samsung.storyservice', 0) == 'clean'
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k storyservice_fg -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Реализация** (требует `import os` в модуле — уже есть, используется другими kill-switch)

```python
    def _tt_recover_from_storyservice_fg(self, fg_pkg: str, wait: int) -> str:
        """FM-B: дисмисс НЕДАМПИРУЕМОГО Samsung «Добавить в историю» оверлея,
        детектируемого по FOREGROUND-пакету (uiautomator возвращает лаунчер →
        XML-детект невозможен). Escalating KEYCODE_BACK с cap.
        Kill-switch TT_STORYSERVICE_FG_DISMISS_ENABLED (default ON).
        Возврат 'handled' / 'stuck' / 'clean'."""
        if (os.environ.get('TT_STORYSERVICE_FG_DISMISS_ENABLED',
                           'true').lower() != 'true'):
            return 'clean'
        is_overlay = self._TT_STORYSERVICE_PKG in (fg_pkg or '')
        is_launcher = any(s in (fg_pkg or '')
                          for s in self._TT_LAUNCHER_PKG_SUBSTRINGS)
        if not (is_overlay or is_launcher):
            return 'clean'
        self._storyservice_fg_iter += 1
        n = self._storyservice_fg_iter
        if n == 1:
            self.log_event(
                'info', 'TikTok: storyservice/launcher в TT-фазе (foreground-детект)',
                meta={'category': 'tt_storyservice_fg_detected',
                      'platform': self.platform, 'fg_pkg': fg_pkg, 'wait_iter': wait})
        if n > self.MAX_STORYSERVICE_FG_ITERATIONS:
            self.log_event(
                'error', 'tt_storyservice_fg_stuck: overlay persists',
                meta={'category': 'tt_storyservice_fg_stuck',
                      'platform': self.platform, 'iterations': n})
            self.set_step('tt_storyservice_fg_stuck')
            return 'stuck'
        self.adb('input keyevent KEYCODE_BACK')
        return 'handled'
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k storyservice_fg -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_recover_from_storyservice_fg (foreground-дисмисс) + тесты"
```

---

## Task 12: `_tt_inapp_upload_from_camera` — оркестратор

**Files:**
- Modify: `publisher_tiktok.py`
- Test: `tests/test_publisher_tt_inapp_upload.py`

- [ ] **Step 1: Тесты** (последовательности дампов через `side_effect`)

```python
def _editor_xml():
    return _xml([{'text': 'Далее', 'clickable': 'true', 'bounds': '[700,2143][890,2200]'}])

def test_orchestrator_happy_camera_to_editor():
    mx = _bare_mixin()
    mx._probe_duration_s = MagicMock(return_value=39.0)
    cam = _xml([{'text': 'ФОТО'}, {'text': 'ПУБЛИКАЦИЯ'},
                {'clickable': 'true', 'bounds': '[0,2047][225,2205]'}])
    gallery = _gallery_two_videos_xml()
    editor = _editor_xml()
    # fg всегда musically (нет оверлея); dump: camera → gallery → (select re-dump gallery) → editor
    mx._tt_foreground_pkg = MagicMock(return_value='com.zhiliaoapp.musically')
    mx.dump_ui = MagicMock(side_effect=[cam, gallery, gallery, editor, editor])
    assert mx._tt_inapp_upload_from_camera() is True

def test_orchestrator_no_match_honest_fail():
    mx = _bare_mixin()
    mx._probe_duration_s = MagicMock(return_value=120.0)   # нет совпадения
    gallery = _gallery_two_videos_xml()
    mx._tt_foreground_pkg = MagicMock(return_value='com.zhiliaoapp.musically')
    mx.dump_ui = MagicMock(side_effect=[gallery, gallery])
    assert mx._tt_inapp_upload_from_camera() is False
    assert any('tt_gallery_video_match_failed' in str(c)
               for c in mx.log_event.call_args_list)

def test_orchestrator_storyservice_stuck_honest_fail():
    mx = _bare_mixin()
    mx._probe_duration_s = MagicMock(return_value=39.0)
    mx._tt_foreground_pkg = MagicMock(return_value='com.samsung.storyservice')
    mx.dump_ui = MagicMock(return_value=_xml([]))
    assert mx._tt_inapp_upload_from_camera() is False
    assert any('tt_inapp_upload_unreached' in str(c)
               for c in mx.log_event.call_args_list)
```

- [ ] **Step 2: Запустить — падает**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k orchestrator -v`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Реализация** (требует `import time` — в модуле уже есть)

```python
    def _tt_inapp_upload_from_camera(self) -> bool:
        """WP#203: детерминированный in-app upload. Камера → галерея (тайл-миниатюра)
        → вкладка «Видео» → тайл с верификацией длительности → редактор. True при
        достижении редактора/trim; иначе честный tt_* код и False (caller прерывает
        → ручная). Kill-switch TT_INAPP_UPLOAD_VIA_CAMERA_ENABLED проверяет caller."""
        self.set_step('TikTok: in-app upload (камера→галерея)')
        expected_dur = self._probe_duration_s(self.media_path)
        entered_gallery = False
        for it in range(self.MAX_INAPP_UPLOAD_ITERATIONS):
            fg = self._tt_foreground_pkg()
            rec = self._tt_recover_from_storyservice_fg(fg, it)
            if rec == 'stuck':
                self.log_event(
                    'error', 'TikTok: in-app upload не достиг редактора (storyservice stuck)',
                    meta={'category': 'tt_inapp_upload_unreached',
                          'platform': self.platform, 'reason': 'storyservice_fg_stuck'})
                return False
            if rec == 'handled':
                time.sleep(1.5)
                continue
            ui = self.dump_ui()
            if self._is_tt_caption_screen(ui) or any(
                    kw in ui for kw in self._TT_EDITOR_PROGRESS_MARKERS):
                return True
            if self._tt_in_gallery_picker(ui):
                entered_gallery = True
                res = self._tt_select_newest_gallery_video(ui, expected_dur)
                if res == 'tapped':
                    time.sleep(2)
                    nui = self.dump_ui()
                    if self._tt_in_gallery_picker(nui):
                        self._tt_tap_gallery_next(nui)
                    time.sleep(3)
                    continue
                if res == 'no_match':
                    self.log_event(
                        'error', 'TikTok: видео по длительности не найдено в галерее',
                        meta={'category': 'tt_gallery_video_match_failed',
                              'platform': self.platform,
                              'expected_dur_s': round(expected_dur, 1)
                              if expected_dur else None})
                    return False
                if res == 'no_tiles':
                    self.log_event(
                        'error', 'TikTok: галерея пуста (нет видео-тайлов)',
                        meta={'category': 'tt_gallery_no_tiles', 'platform': self.platform})
                    return False
            if self._tt_detect_camera_screen(ui):
                self._tt_enter_upload_from_camera(ui)
                time.sleep(3)
                continue
            time.sleep(2)
        self.log_event(
            'error', 'TikTok: in-app upload не достиг редактора за лимит',
            meta={'category': 'tt_inapp_upload_unreached', 'platform': self.platform,
                  'entered_gallery': entered_gallery})
        self.set_step('tt_inapp_upload_unreached')
        try:
            self._save_debug_artifacts('tt_inapp_upload_unreached')
        except Exception:
            pass
        return False
```

- [ ] **Step 4: Зелёный**

Run: `pytest tests/test_publisher_tt_inapp_upload.py -k orchestrator -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add publisher_tiktok.py tests/test_publisher_tt_inapp_upload.py
git commit -m "feat(wp203): _tt_inapp_upload_from_camera оркестратор + тесты"
```

---

## Task 13: Врезка в `publish_tiktok` (kill-switch)

**Files:**
- Modify: `publisher_tiktok.py` (блок `if not in_editor:`, строки 1963-1991 origin/main)

- [ ] **Step 1: Заменить блок**

Найти блок (начинается со строки `if not in_editor:` на ~1963) и заменить ВЕСЬ блок `if not in_editor: … return False` (заканчивается на `return False` перед `log.info('  ✅ TikTok готов к редактированию')`) на:

```python
        if not in_editor:
            if (os.environ.get('TT_INAPP_UPLOAD_VIA_CAMERA_ENABLED',
                               'true').lower() == 'true'):
                # WP#203: детерминированный in-app upload (камера→галерея→редактор)
                # вместо флаки SEND-intent. Honest tt_* + abort при сбое.
                log.info('TikTok: редактор не детектирован — in-app upload (WP#203)')
                if not self._tt_inapp_upload_from_camera():
                    return False  # honest tt_* уже залогирован → ручная
                # in-app upload довёл до редактора — проваливаемся в editor-loop
            else:
                # Legacy SEND-intent fallback (kill-switch OFF) — мгновенный откат.
                log.info('TikTok: редактор не детектирован после switch — fallback intent')
                TIKTOK_SHARE_ACTIVITY = (
                    'com.zhiliaoapp.musically/'
                    'com.ss.android.ugc.aweme.share.SystemShareActivity'
                )
                self.adb(
                    f'am start -n {TIKTOK_SHARE_ACTIVITY} '
                    f'-a android.intent.action.SEND -t "video/mp4" '
                    f'--eu android.intent.extra.STREAM "{content_uri}" '
                    f'--grant-read-uri-permission'
                )
                time.sleep(5)
                self.adb('input keyevent KEYCODE_WAKEUP')
                time.sleep(1)
                act = self.adb(
                    'dumpsys activity activities 2>/dev/null '
                    '| grep -m1 "topResumedActivity"', timeout=8) or ''
                log.info(f'  После fallback intent: {act.strip()[:120]}')
                if 'musically' not in act and 'tiktok' not in act.lower():
                    log.error(f'TikTok не запустился! activity={act.strip()[:80]}')
                    self._safe_kb_probe(self.dump_ui(), step='tt_share_activity_not_opened')
                    self.log_event('error', 'TikTok SystemShareActivity не открылась',
                                    meta={'category': 'tt_share_activity_not_opened',
                                          'platform': self.platform, 'step': 'tt_open_share'})
                    return False
        log.info('  ✅ TikTok готов к редактированию')
```

- [ ] **Step 2: Полный прогон тестов TT + smoke-импорт**

Run: `cd autowarm-testbench && python -c "import publisher_tiktok" && pytest tests/test_publisher_tt_inapp_upload.py tests/test_publisher_tt_overlay_handlers.py -q`
Expected: все PASS, 0 регрессий в существующих overlay-тестах.

- [ ] **Step 3: Commit**

```bash
git add publisher_tiktok.py
git commit -m "feat(wp203): врезка in-app upload в publish_tiktok (kill-switch TT_INAPP_UPLOAD_VIA_CAMERA_ENABLED, OFF=legacy SEND-intent)"
```

---

## Task 14: Миграция error-кодов

**Files:**
- Create: `migrations/20260531_wp203_tt_inapp_upload_codes.sql`
- Create: `migrations/20260531_wp203_tt_inapp_upload_codes__rollback.sql`

- [ ] **Step 1: Миграция** (`20260531_wp203_tt_inapp_upload_codes.sql`)

```sql
-- WP#203: honest error codes для детерминированного in-app upload TikTok.
-- Все три = ui_changed → retry-engine уводит в ручную (оператор постит вручную).
-- Зеркало tt_caption_field_not_focused (WP#44) / ig_caption_screen_not_reached (WP#140).
-- Idempotent: ON CONFLICT (code) DO UPDATE.
BEGIN;
INSERT INTO publish_error_codes
  (code, error_class, severity, retry_strategy, is_known, is_auto_fixable, description)
VALUES
  ('tt_inapp_upload_unreached','ui_changed','error','manual',true,false,
   'TikTok in-app upload не достиг редактора (камера/галерея/foreground-оверлей) — честный фейл вместо SEND-intent'),
  ('tt_gallery_video_match_failed','ui_changed','error','manual',true,false,
   'TikTok: видео с ожидаемой длительностью не найдено в галерее — не публикуем чужое видео'),
  ('tt_gallery_no_tiles','ui_changed','error','manual',true,false,
   'TikTok: внутренняя галерея пуста (нет видео-тайлов)')
ON CONFLICT (code) DO UPDATE
  SET error_class = EXCLUDED.error_class,
      severity = EXCLUDED.severity,
      retry_strategy = EXCLUDED.retry_strategy,
      is_known = EXCLUDED.is_known,
      is_auto_fixable = EXCLUDED.is_auto_fixable,
      description = EXCLUDED.description;
COMMIT;
```

- [ ] **Step 2: Rollback** (`20260531_wp203_tt_inapp_upload_codes__rollback.sql`)

```sql
-- Rollback WP#203 in-app upload error codes.
BEGIN;
DELETE FROM publish_error_codes
 WHERE code IN ('tt_inapp_upload_unreached','tt_gallery_video_match_failed','tt_gallery_no_tiles');
COMMIT;
```

- [ ] **Step 3: Применить на прод-БД** (openclaw в Docker-контейнере — см. memory `reference_openclaw_postgres_docker`)

Run: `PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -f migrations/20260531_wp203_tt_inapp_upload_codes.sql`
Expected: `INSERT 0 3` (или `COMMIT`).

Verify: `PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tA -c "SELECT code,error_class,retry_strategy FROM publish_error_codes WHERE code LIKE 'tt_inapp%' OR code LIKE 'tt_gallery%';"`
Expected: 3 строки, все `ui_changed|manual`.

- [ ] **Step 4: Commit**

```bash
git add migrations/20260531_wp203_tt_inapp_upload_codes.sql migrations/20260531_wp203_tt_inapp_upload_codes__rollback.sql
git commit -m "feat(wp203): миграция error-кодов tt_inapp_upload_unreached/gallery_video_match_failed/gallery_no_tiles"
```

---

## Task 15: codex review + ops-чеклист storyservice

**Files:**
- Create/Modify: `docs/evidence/2026-05-31-wp203-tt-inapp-upload-recon.md` (дополнить ops-чеклистом — в repo `contenthunter`, ветка `wp203-tt-share-editor`)

- [ ] **Step 1: `codex review`** изменений (конвенция, memory `feedback_codex_review_specs`)

Run: `cd autowarm-testbench && ~/.local/bin/codex review`
Действие: отработать P1/P2 замечания (если есть), зелёные тесты после правок.

- [ ] **Step 2: Ops-чеклист отключения storyservice** (для Данила) — добавить раздел в evidence-док:

```markdown
## Ops: отключение com.samsung.storyservice на флоте (FM-B, слой 1)

Команда (на каждое устройство, обратимо): 
`adb -s <serial> shell pm disable-user --user 0 com.samsung.storyservice`
Откат: `adb -s <serial> shell pm enable com.samsung.storyservice`
Проверка персистентности: после reboot/OTA повторно `pm list packages -d | grep storyservice`.
На RF8YA0W57EP (№19) уже отключён. Код (`_tt_recover_from_storyservice_fg`) — страховка для
устройств, где disable не применился/слетел.
```

- [ ] **Step 3: Commit ops-чеклиста** (в contenthunter-ветке `wp203-tt-share-editor`)

```bash
git add docs/evidence/2026-05-31-wp203-tt-inapp-upload-recon.md
git commit -m "docs(wp203): ops-чеклист отключения storyservice на флоте"
```

---

## Task 16: testbench-смок на №19 + деплой

**Files:** —

- [ ] **Step 1: Полный прогон тестов** (нет регрессий)

Run: `cd autowarm-testbench && pytest tests/ -q -k "tt_" `
Expected: все зелёные.

- [ ] **Step 2: testbench-смок** на RF8YA0W57EP (№19) — диспатч одной TT-задачи через testbench (см. memory `reference_testbench_smoke_paths`); флаги `TT_INAPP_UPLOAD_VIA_CAMERA_ENABLED=true`, `TT_STORYSERVICE_FG_DISMISS_ENABLED=true`.
Expected: чистый success по in-app пути (камера→галерея→«Видео»→тайл→редактор→описание→публикация), без SEND-intent и без `tt_caption_field_not_focused`.

- [ ] **Step 3: Деплой в прод** (memory `feedback_deploy_scope_constraints`): merge в `autowarm` main → прод pull → `pm2 restart` id35 (если требуется; kill-switch читается через load_dotenv). Зафиксировать прод-commit в evidence.

- [ ] **Step 4: OpenProject** #203 → «Тестирование», комментарий по house-style (Что было не так → Что сделано → Что осталось).

---

## Self-Review

**Spec coverage:**
- Approach A (in-app upload) → Tasks 4,5,7-10,12,13 ✅
- Верификация длительности → Tasks 6,9 ✅
- FM-B foreground-дисмисс → Task 11; ops-чеклист → Task 15 ✅
- Честный фейл/коды → Tasks 12,14 ✅
- Kill-switches `TT_INAPP_UPLOAD_VIA_CAMERA_ENABLED`/`TT_STORYSERVICE_FG_DISMISS_ENABLED` → Tasks 11,13 ✅
- Тесты/смок/codex → Tasks 2-12,15,16 ✅
- Корректировка «галерея = тайл, не ПУБЛИКАЦИЯ» → Task 10 ✅

**Placeholder scan:** код полный во всех шагах; плейсхолдеров нет.

**Type consistency:** `_tt_select_newest_gallery_video` → str ('tapped'/'no_match'/'no_tiles') согласован между Task 9 и оркестратором Task 12; `_probe_duration_s` → float|None согласован (Task 6 ↔ 9,12); `_tt_recover_from_storyservice_fg` → 'handled'/'stuck'/'clean' согласован (Task 11 ↔ 12); счётчик `_storyservice_fg_iter` (Task 2 ↔ 11). Константы (Task 1) используются в Tasks 4,5,8,9,10,11,12.
