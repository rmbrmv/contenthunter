# WP #146 — Фильтр максимального разрешения видео при загрузке — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При загрузке видео в планировщик validator отклонять разрешение выше 1080×1920 (±5%) — зеркало уже работающей проверки размеров для картинок.

**Architecture:** Один блокер `resolution_too_high` в backend-функции `check_technical_blockers` (покрывает оба пути загрузки `/complete` и `/file`, т.к. оба её вызывают) + зеркальный пункт `max_resolution` во frontend-preflight `analyzeVideo` (агрегируется существующим `videoChecksPass`). Уникализацию (`unic-worker`) не трогаем.

**Tech Stack:** Python/FastAPI + pytest (backend), Vue 3 + TypeScript + Vitest (frontend). Спека: `docs/superpowers/specs/2026-05-25-wp146-resolution-filter-design.md`.

---

## Подготовка (выполнить один раз перед Task 1)

Код меняется в репозитории **`/home/claude-user/validator-contenthunter`** (отдельный git-репо, НЕ в agent-workspace `contenthunter`, где лежит этот план).

- [ ] **Step 0: Ветка изоляции в validator-contenthunter**

```bash
cd /home/claude-user/validator-contenthunter
git fetch --quiet
git checkout -b wp146-resolution-filter
git branch --show-current   # ожидаем: wp146-resolution-filter
```

> ⚠️ **Авто-деплой фронта:** `npm run build` во `frontend/` через postbuild-хук СРАЗУ копирует `dist/*` в `/var/www/validator/` (прод). На этапе разработки `build` НЕ запускать — только `npm run test` и `npx vue-tsc --noEmit`. Деплой — отдельный финальный шаг с согласия пользователя.

## Структура файлов

| Файл | Что делаем |
|---|---|
| `backend/src/services/video_metadata.py` | + константы `MAX_WIDTH/MAX_HEIGHT/RESOLUTION_TOLERANCE`, + блокер в `check_technical_blockers` |
| `backend/tests/test_video_metadata.py` | **Создать**: unit-тесты блокера (зеркало `test_image_metadata.py`) |
| `frontend/src/components/UploadModal.vue` | + константы + пункт `max_resolution` в `analyzeVideo` |

---

## Task 1: Backend — блокер `resolution_too_high` (TDD)

**Files:**
- Create: `backend/tests/test_video_metadata.py`
- Modify: `backend/src/services/video_metadata.py` (константы ~строки 127-131; блокер в `check_technical_blockers` после проверки аспекта ~строка 177)

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_video_metadata.py`:

```python
"""Unit-тесты для services/video_metadata.py — максимальное разрешение (WP #146)."""
from src.services.video_metadata import (
    check_technical_blockers,
    VideoMetadata,
    MAX_WIDTH,
    MAX_HEIGHT,
)


def _valid_video_meta(width, height) -> VideoMetadata:
    """VideoMetadata, проходящая ВСЕ блокеры кроме (возможно) разрешения."""
    m = VideoMetadata()
    m.width = width
    m.height = height
    m.has_video = True
    m.has_audio = True
    m.mean_volume_db = -20.0
    m.duration_seconds = 25.0
    m.codec = "h264"
    return m


def _codes(meta) -> list:
    return [b["code"] for b in check_technical_blockers(meta, 10 * 1024 * 1024, "video/mp4")]


def test_1080x1920_passes_no_blockers():
    assert _codes(_valid_video_meta(1080, 1920)) == []


def test_2160x3840_rejected():
    assert "resolution_too_high" in _codes(_valid_video_meta(2160, 3840))


def test_1440x2560_rejected():
    assert "resolution_too_high" in _codes(_valid_video_meta(1440, 2560))


def test_1210x2050_rejected_width_over_tolerance():
    # 1210 > 1080*1.05 = 1134
    assert "resolution_too_high" in _codes(_valid_video_meta(1210, 2050))


def test_1088x1920_passes_macroblock_padding():
    # h264 выравнивает 1080→1088; 1088 ≤ 1134 (±5%)
    assert "resolution_too_high" not in _codes(_valid_video_meta(1088, 1920))


def test_768x1376_passes():
    assert "resolution_too_high" not in _codes(_valid_video_meta(768, 1376))


def test_1080x2400_rejected_too_tall():
    # 2400 > 1920*1.05 = 2016; аспект 0.45 ≤ 0.6 → именно resolution_too_high
    codes = _codes(_valid_video_meta(1080, 2400))
    assert "resolution_too_high" in codes
    assert "wrong_aspect" not in codes


def test_none_dims_no_resolution_blocker():
    m = _valid_video_meta(1080, 1920)
    m.width = None
    m.height = None
    assert "resolution_too_high" not in _codes(m)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_video_metadata.py -v`
Expected: **ImportError / collection error** — `cannot import name 'MAX_WIDTH'` (константы ещё не добавлены). После добавления констант, но до блокера, упадут `test_2160x3840_rejected`/`test_1440x2560_rejected`/`test_1210x2050_*`/`test_1080x2400_*` (блокер ещё не возвращается).

- [ ] **Step 3: Добавить константы**

В `backend/src/services/video_metadata.py`, в блок констант (рядом с `MIN_HEIGHT = 720`, ~строка 127), добавить:

```python
MAX_WIDTH            = 1080
MAX_HEIGHT           = 1920
RESOLUTION_TOLERANCE = 0.05            # ±5% (как у картинок); гасит h264-паддинг 1080→1088
```

- [ ] **Step 4: Добавить блокер в `check_technical_blockers`**

В `backend/src/services/video_metadata.py`, в функции `check_technical_blockers`, СРАЗУ ПОСЛЕ блока проверки аспекта (после `blockers.append({... "wrong_aspect" ...})`, ~строка 177) и ПЕРЕД проверкой кодека, вставить:

```python
    if meta.width and meta.height:
        if (meta.width  > MAX_WIDTH  * (1 + RESOLUTION_TOLERANCE) or
                meta.height > MAX_HEIGHT * (1 + RESOLUTION_TOLERANCE)):
            blockers.append({
                "code": "resolution_too_high",
                "message": (
                    f"Разрешение {meta.width}×{meta.height} превышает максимум "
                    f"{MAX_WIDTH}×{MAX_HEIGHT}. Уменьшите разрешение видео до {MAX_WIDTH}×{MAX_HEIGHT}."
                ),
            })
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_video_metadata.py -v`
Expected: **8 passed**.

- [ ] **Step 6: Регрессия — существующие тесты блокеров не сломаны**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_image_metadata.py tests/test_video_metadata.py -v`
Expected: всё **passed** (картиночная валидация не затронута, видео-блокеры расширены).

- [ ] **Step 7: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/services/video_metadata.py backend/tests/test_video_metadata.py
git commit -m "feat(upload): блокер resolution_too_high — видео >1080×1920 (±5%) не пускаем в планировщик (WP #146)"
```

---

## Task 2: Frontend — пункт `max_resolution` в preflight (`analyzeVideo`)

**Files:**
- Modify: `frontend/src/components/UploadModal.vue` (константы рядом с `VERTICAL_TARGETS` ~строка 775; новый блок в `analyzeVideo` после существующей проверки `resolution` ≥720p ~строки 941-951)

- [ ] **Step 1: Добавить константы**

В `frontend/src/components/UploadModal.vue`, в `<script setup>`, рядом с `const VERTICAL_TARGETS ...` (~строка 775), добавить:

```ts
const MAX_VIDEO_W = 1080
const MAX_VIDEO_H = 1920
const RES_TOL = 1.05   // ±5%, синхронно с бэком (resolution_too_high)
```

- [ ] **Step 2: Добавить пункт `max_resolution` в `analyzeVideo`**

В функции `analyzeVideo`, СРАЗУ ПОСЛЕ блока, заполняющего `checks.resolution` (проверка ≥720p, заканчивается на ~строке 951), вставить:

```ts
  if (videoLoaded && width > 0 && height > 0) {
    const overMax = width > MAX_VIDEO_W * RES_TOL || height > MAX_VIDEO_H * RES_TOL
    checks.max_resolution = {
      ok: !overMax,
      label: `Разрешение ≤ ${MAX_VIDEO_W}×${MAX_VIDEO_H}`,
      detail: `${width}×${height}`,
      hint: overMax ? `Видео ${width}×${height} слишком большое. Загрузите в ${MAX_VIDEO_W}×${MAX_VIDEO_H}.` : undefined,
    }
  } else {
    checks.max_resolution = { ok: false, label: `Разрешение ≤ ${MAX_VIDEO_W}×${MAX_VIDEO_H}`, detail: 'Не определено', hint: 'Не удалось прочитать метаданные видео' }
  }
```

> `videoChecksPass = Object.values(videoChecks).every(c => c.ok)` подхватит новый пункт автоматически → кнопка «Загрузить» заблокируется (текст «🚫 Устраните ошибки»), красный badge покажется до отправки. `VideoCheck` уже имеет поля `{ok, label, detail, hint}` — новых типов не нужно.

- [ ] **Step 3: Типизация — vue-tsc без ошибок**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vue-tsc --noEmit`
Expected: без ошибок типов (новый пункт `checks.max_resolution` соответствует `Record<string, VideoCheck>`).

> НЕ запускать `npm run build` — postbuild авто-деплоит в `/var/www/validator/`.

- [ ] **Step 4: Frontend-тесты не сломаны**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npm run test`
Expected: существующий набор **passed** (если есть тест на `UploadModal`/`analyzeVideo` — он по-прежнему зелёный; нового unit-теста не пишем, т.к. `analyzeVideo` — внутренняя функция компонента с DOM-video API, проверяется вручную на деплое).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/components/UploadModal.vue
git commit -m "feat(upload-ui): preflight max_resolution ≤1080×1920 для видео (WP #146)"
```

---

## Task 3: Сквозная проверка и заметки по деплою

**Files:** нет изменений кода — только верификация.

- [ ] **Step 1: Полный прогон затронутых тестов backend**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_video_metadata.py tests/test_image_metadata.py -v`
Expected: всё **passed**.

- [ ] **Step 2: Ручная проверка логики API (без HTTP)**

Run:
```bash
cd /home/claude-user/validator-contenthunter/backend && python -c "
from src.services.video_metadata import check_technical_blockers, VideoMetadata
def mk(w,h):
    m=VideoMetadata(); m.width=w; m.height=h; m.has_video=True; m.has_audio=True
    m.mean_volume_db=-20; m.duration_seconds=25; m.codec='h264'; return m
for w,h in [(2160,3840),(1440,2560),(1080,1920),(1088,1920),(768,1376)]:
    print(w,h,'->',[b['code'] for b in check_technical_blockers(mk(w,h),10*1024*1024,'video/mp4')])
"
```
Expected:
```
2160 3840 -> ['resolution_too_high']
1440 2560 -> ['resolution_too_high']
1080 1920 -> []
1088 1920 -> []
768 1376 -> []
```

- [ ] **Step 3: Заметки по деплою (выполняется ОТДЕЛЬНО, с согласия пользователя)**

> Деплой — внешнее необратимое действие, требует явного «го» от пользователя. Не выполнять автоматически в рамках реализации.

- Backend: PM2-процесс `validator` (id=24) рестартнуть после мерджа изменений в прод-checkout. Прод-расположение бэка — уточнить (`pm2 describe validator | grep "exec cwd"`), т.к. возможен dump-path drift.
- Frontend: `cd frontend && npm run build` (postbuild сам скопирует в `/var/www/validator/`). Это и есть деплой фронта — запускать только когда готовы выкатывать.
- Пользователям с открытыми вкладками может потребоваться hard reload (stale chunk-loader после смены ассетов).

- [ ] **Step 4: OpenProject + память (после деплоя/верификации)**

- Обновить WP #146 в OpenProject: статус-комментарий в house-style (Что было не так → Что сделано → Что осталось), при необходимости перевести статус в «Тестирование» (id 9).
- Записать в память факт о shipped-фиксе (по аналогии с прочими `project_*_shipped`).

---

## Self-Review (выполнено автором плана)

- **Spec coverage:** §3.1 backend → Task 1; §3.2 frontend → Task 2; §4 граничные случаи → тесты Task 1 Step 1 (все 8 строк таблицы покрыты); §6 тестирование → Task 1/2/3; §5 «вне рамок» → ничего лишнего не добавляем (unic-worker/ретро-чистка/авто-даунскейл отсутствуют в задачах). ✅
- **Placeholder scan:** нет TBD/«добавить обработку ошибок» — весь код приведён дословно. ✅
- **Type consistency:** backend константы `MAX_WIDTH/MAX_HEIGHT/RESOLUTION_TOLERANCE` определены в Task 1 Step 3 и импортируются в тесте Step 1; код блокера использует именно их. Frontend `MAX_VIDEO_W/MAX_VIDEO_H/RES_TOL` определены в Task 2 Step 1 и используются в Step 2; `checks.max_resolution` соответствует `VideoCheck {ok,label,detail,hint}`. ✅
- **Допуск синхронен:** бэк `RESOLUTION_TOLERANCE=0.05` (множитель 1.05) ≡ фронт `RES_TOL=1.05`. ✅
