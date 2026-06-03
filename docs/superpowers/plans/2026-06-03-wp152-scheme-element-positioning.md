# WP#152 — корректировка расположения элементов схем 35–70: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поставить аватарку-лицо и лого клиента в схемах 35–70 только в верхние углы (лого напротив лица), устранив «лого слева» и перекрытие оверлея.

**Architecture:** Источник истины расположения — чистая функция `element_positions(scheme_id)` (одна на генератор и на скрипт-фикс, DRY). Данные правит идемпотентный `UPDATE`-скрипт по openclaw БД; генератор обновляется для консистентности будущих пересозданий; воркер получает защитную правку NULL-дефолта логотипа. Низ и центр кадра запрещены (субтитры исходника + UI приложений).

**Tech Stack:** Python 3, psycopg2, pytest; FFmpeg-фильтрграф воркера `unic-worker/worker.py`; PostgreSQL `openclaw@72.56.107.157:5432/openclaw`, таблица `unic_schemes`.

---

## Репозитории и подготовка

Три репозитория, у каждого — отдельная рабочая ветка (не мешать параллельным сессиям):

- **Docs** (`rmbrmv/contenthunter`) — этот план и спека. Ветка `wp152-scheme-element-positioning` уже создана.
- **Delivery** (`GenGo2/delivery-contenthunter`) — `unic-worker/scripts/*` + `unic-worker/worker.py`. Завести свежий worktree/ветку `wp152-element-positions` от `origin/main`.
- **Standalone** (`GenGo2/unic-worker`) — только `worker.py`. Завести свежий worktree/ветку `wp152-element-positions` от `origin/main`.

Канонический scheme_preview-воркер = standalone (PM2 id0, 91.98.180.103). Delivery-копия = PM2 id36 (72.56.107.157). Защитную правку воркера применяем в ОБОИХ (зеркало триаж-фикса PR#151/PR#2).

## Целевая раскладка (источник истины)

`element_positions(scheme_id)` возвращает позиции. Множества по стороне лица:

- **Лицо top_right, лого top_left** (16 схем): 36, 38, 41, 43, 45, 48, 50, 52, 53, 55, 57, 60, 62, 65, 67, 69
- **Лицо top_left, лого top_right** (20 схем, всё остальное из 35–70): 35, 37, 39, 40, 42, 44, 46, 47, 49, 51, 54, 56, 58, 59, 61, 63, 64, 66, 68, 70

`logo_offset_x = logo_offset_y = 20` для всех. Оверлей-offset не трогаем (flush к углу).

## File Structure

- `unic-worker/scripts/wp152_element_positions.py` (NEW, delivery) — чистая `element_positions(sid)`. Единственный источник раскладки.
- `unic-worker/scripts/fix_wp152_element_positions.py` (NEW, delivery) — идемпотентный `UPDATE` 35–70 по openclaw БД, использует `element_positions`.
- `unic-worker/scripts/gen_wp152_schemes.py` (MODIFY, delivery) — берёт overlay/logo-позиции из `element_positions`, чтобы свежая генерация совпадала с пропатченной БД.
- `unic-worker/worker.py` (MODIFY, delivery + standalone) — `scheme.get('logo_position') or 'top_right'`.
- `unic-worker/tests/test_wp152_element_positions.py` (NEW, delivery) — юнит на `element_positions`.
- `unic-worker/tests/test_logo_position_null_default.py` (NEW, delivery + standalone) — защитная правка воркера.

---

## Task 1: Чистая функция раскладки `element_positions` (delivery)

**Files:**
- Create: `unic-worker/scripts/wp152_element_positions.py`
- Test: `unic-worker/tests/test_wp152_element_positions.py`

- [ ] **Step 1: Написать падающий тест**

`unic-worker/tests/test_wp152_element_positions.py`:
```python
"""WP#152 — element_positions: лицо и лого только в верхних углах, лого напротив лица."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from wp152_element_positions import element_positions  # noqa: E402

FACE_TOP_RIGHT = {36, 38, 41, 43, 45, 48, 50, 52, 53, 55, 57, 60, 62, 65, 67, 69}


def test_all_36_schemes_covered():
    ids = [sid for sid in range(35, 71)]
    for sid in ids:
        p = element_positions(sid)
        assert set(p) == {"overlay_video_position", "logo_position",
                          "logo_offset_x", "logo_offset_y"}


def test_only_top_corners_no_bottom_no_center():
    for sid in range(35, 71):
        p = element_positions(sid)
        assert p["overlay_video_position"] in ("top_left", "top_right")
        assert p["logo_position"] in ("top_left", "top_right")


def test_logo_always_opposite_face():
    for sid in range(35, 71):
        p = element_positions(sid)
        assert p["overlay_video_position"] != p["logo_position"]


def test_face_top_right_set_matches_spec():
    for sid in range(35, 71):
        p = element_positions(sid)
        if sid in FACE_TOP_RIGHT:
            assert p["overlay_video_position"] == "top_right"
            assert p["logo_position"] == "top_left"
        else:
            assert p["overlay_video_position"] == "top_left"
            assert p["logo_position"] == "top_right"


def test_logo_offsets_are_20():
    p = element_positions(40)
    assert p["logo_offset_x"] == 20 and p["logo_offset_y"] == 20
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd unic-worker && python -m pytest tests/test_wp152_element_positions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wp152_element_positions'`

- [ ] **Step 3: Реализовать функцию**

`unic-worker/scripts/wp152_element_positions.py`:
```python
"""WP#152 — источник истины расположения элементов в схемах 35-70.

Правило: лицо (overlay) и лого только в верхних углах; лого в углу напротив лица.
Низ и центр запрещены (субтитры исходника + элементы интерфейса приложений).
Используется и скриптом-фиксом БД, и генератором схем — чтобы свежая генерация
совпадала с пропатченной БД.
"""

# Схемы, у которых лицо в правом верхнем углу (лого — в левом).
# Остальные из диапазона 35-70 — лицо слева, лого справа.
FACE_TOP_RIGHT = {36, 38, 41, 43, 45, 48, 50, 52, 53, 55, 57, 60, 62, 65, 67, 69}

LOGO_OFFSET = 20


def element_positions(scheme_id):
    """Вернуть позиции элементов для схемы 35-70."""
    if scheme_id in FACE_TOP_RIGHT:
        overlay, logo = "top_right", "top_left"
    else:
        overlay, logo = "top_left", "top_right"
    return {
        "overlay_video_position": overlay,
        "logo_position": logo,
        "logo_offset_x": LOGO_OFFSET,
        "logo_offset_y": LOGO_OFFSET,
    }
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `cd unic-worker && python -m pytest tests/test_wp152_element_positions.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Коммит**

```bash
git add unic-worker/scripts/wp152_element_positions.py unic-worker/tests/test_wp152_element_positions.py
git commit -m "feat(wp152): element_positions — лицо/лого только в верхних углах"
```

---

## Task 2: Идемпотентный скрипт-фикс БД (delivery)

**Files:**
- Create: `unic-worker/scripts/fix_wp152_element_positions.py`

- [ ] **Step 1: Реализовать скрипт**

`unic-worker/scripts/fix_wp152_element_positions.py`:
```python
"""WP#152 — выставить overlay/logo-позиции схем 35-70 (только верхние углы).

Запуск:
  python scripts/fix_wp152_element_positions.py            # dry-run: печатает UPDATE
  python scripts/fix_wp152_element_positions.py --apply     # применяет
Идемпотентно: повторный прогон выставит те же значения.
"""
import argparse
import os
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(__file__))
from wp152_element_positions import element_positions

DATABASE_URL = os.environ["DATABASE_URL"]
SCHEME_IDS = list(range(35, 71))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            for sid in SCHEME_IDS:
                p = element_positions(sid)
                sql = (
                    "UPDATE unic_schemes SET overlay_video_position=%s, "
                    "logo_position=%s, logo_offset_x=%s, logo_offset_y=%s WHERE id=%s"
                )
                vals = [p["overlay_video_position"], p["logo_position"],
                        p["logo_offset_x"], p["logo_offset_y"], sid]
                if args.apply:
                    cur.execute(sql, vals)
                else:
                    print(sql, vals)
            if args.apply:
                conn.commit()
                print(f"Обновлено {len(SCHEME_IDS)} схем (id 35-70)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Проверить dry-run (без БД-записи)**

Run (с реальным DATABASE_URL openclaw):
```bash
cd unic-worker && DATABASE_URL='postgresql://openclaw:openclaw123@72.56.107.157:5432/openclaw' \
  python scripts/fix_wp152_element_positions.py | head -40
```
Expected: 36 строк `UPDATE unic_schemes SET ... WHERE id=35 ... 70`, где у id из FACE_TOP_RIGHT — `top_right/top_left`, у остальных — `top_left/top_right`. БД не меняется (нет `--apply`).

- [ ] **Step 3: Коммит**

```bash
git add unic-worker/scripts/fix_wp152_element_positions.py
git commit -m "feat(wp152): идемпотентный скрипт-фикс позиций элементов схем 35-70"
```

---

## Task 3: Защитная правка воркера — NULL logo_position → top_right (standalone)

**Files:**
- Modify: `unic-worker/worker.py` (строка с `_xy(scheme.get('logo_position','top_right')...`)
- Test: `unic-worker/tests/test_logo_position_null_default.py`

В standalone-репо путь `worker.py` и `tests/`. Импорт в тестах: `from worker import generate_ffmpeg` (см. tests/test_null_safe_scheme_params.py — паттерн `_filter_complex`).

- [ ] **Step 1: Написать падающий тест**

`tests/test_logo_position_null_default.py`:
```python
"""WP#152 — NULL logo_position не должен молча уезжать в левый верхний угол.

Из БД logo_position приходит как None (ключ есть, значение NULL). dict.get(k, default)
default НЕ подставляет → _xy(None) падал в (ox,oy) = левый верхний угол. Должно быть
top_right (как у схем 1-34), пока БД-фикс не задал явный угол.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import worker  # noqa: E402

LOGO_FILES = {"original": "in.mp4", "logo": "logo.png"}


def _filter_complex(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_logo_position_null_defaults_to_top_right():
    scheme = {"logo_position": None}
    fc = _filter_complex(worker.generate_ffmpeg(scheme, LOGO_FILES, None, "out.mp4"))
    # top_right => x = main_w-overlay_w-<offset>
    assert "[lgp] overlay=main_w-overlay_w-" in fc


def test_logo_position_explicit_left_is_respected():
    scheme = {"logo_position": "top_left", "logo_offset_x": 20, "logo_offset_y": 20}
    fc = _filter_complex(worker.generate_ffmpeg(scheme, LOGO_FILES, None, "out.mp4"))
    assert "[lgp] overlay=20:20" in fc
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/<standalone-worktree> && python -m pytest tests/test_logo_position_null_default.py -v`
Expected: FAIL на `test_logo_position_null_defaults_to_top_right` — текущий код даёт `overlay=10:10` (левый угол), подстроки `main_w-overlay_w-` нет.

- [ ] **Step 3: Применить правку воркера**

В `worker.py` заменить точную строку:
```python
        px,py=_xy(scheme.get('logo_position','top_right'),scheme.get('logo_offset_x',10),scheme.get('logo_offset_y',10))
```
на:
```python
        px,py=_xy(scheme.get('logo_position') or 'top_right',scheme.get('logo_offset_x') or 10,scheme.get('logo_offset_y') or 10)
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `python -m pytest tests/test_logo_position_null_default.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Регрессия воркера standalone**

Run: `python -m pytest tests/ -q`
Expected: всё зелёное (включая test_null_safe_scheme_params.py).

- [ ] **Step 6: Коммит**

```bash
git add worker.py tests/test_logo_position_null_default.py
git commit -m "fix(wp152): NULL logo_position -> top_right (а не молча top_left)"
```

---

## Task 4: Защитная правка воркера (delivery, зеркало Task 3)

**Files:**
- Modify: `unic-worker/worker.py`
- Test: `unic-worker/tests/test_logo_position_null_default.py`

Идентичный код воркера, отличаются только номера строк. Цель — паритет standalone/delivery.

- [ ] **Step 1: Создать тест** — тот же файл, что в Task 3 Step 1, по пути `unic-worker/tests/test_logo_position_null_default.py`.

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd unic-worker && python -m pytest tests/test_logo_position_null_default.py -v`
Expected: FAIL (`overlay=10:10`, нет `main_w-overlay_w-`).

- [ ] **Step 3: Применить ту же правку** в `unic-worker/worker.py`: заменить
```python
        px,py=_xy(scheme.get('logo_position','top_right'),scheme.get('logo_offset_x',10),scheme.get('logo_offset_y',10))
```
на
```python
        px,py=_xy(scheme.get('logo_position') or 'top_right',scheme.get('logo_offset_x') or 10,scheme.get('logo_offset_y') or 10)
```

- [ ] **Step 4: Запустить тест — PASS**

Run: `python -m pytest tests/test_logo_position_null_default.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Регрессия unic-worker delivery**

Run: `cd unic-worker && python -m pytest tests/ -q`
Expected: зелёное.

- [ ] **Step 6: Коммит**

```bash
git add unic-worker/worker.py unic-worker/tests/test_logo_position_null_default.py
git commit -m "fix(wp152): NULL logo_position -> top_right (delivery-зеркало)"
```

---

## Task 5: Обновить генератор схем под верхние углы (delivery)

**Files:**
- Modify: `unic-worker/scripts/gen_wp152_schemes.py`

Цель: свежая генерация пула даёт те же позиции, что и пропатченная БД (через `element_positions`). Генератор идемпотентен (`max(id)>=70` → не вставляет), правка для будущих пересозданий/документации.

- [ ] **Step 1: Подключить `element_positions` и добавить колонки**

В шапке `gen_wp152_schemes.py` после `import psycopg2` добавить:
```python
import sys as _sys
_sys.path.insert(0, os.path.dirname(__file__))
from wp152_element_positions import element_positions
```

В списке `COLS` добавить новые колонки в конец:
```python
COLS = ["scale_add","pad_add","rotate_deg","crop_reduce","crop_offset_x","crop_offset_y",
        "speed","audio_atempo","audio_volume","audio_highpass","audio_lowpass",
        "overlay_video_scale_w","overlay_video_scale_h","overlay_video_position",
        "shake_amp","shake_freq","shake_axis",
        "logo_position","logo_offset_x","logo_offset_y"]
```

- [ ] **Step 2: Переопределить позиции в `build_rows`**

В `build_rows()` внутри цикла, ПОСЛЕ `r = RECIPES[(k - 1) % len(RECIPES)]`, наложить позиции из `element_positions` на копию рецепта:
```python
    for k in range(1, 37):                       # 36 схем
        r = dict(RECIPES[(k - 1) % len(RECIPES)])
        sid = 34 + k                             # id 35..70
        pos = element_positions(sid)
        r["overlay_video_position"] = pos["overlay_video_position"]
        r["logo_position"] = pos["logo_position"]
        r["logo_offset_x"] = pos["logo_offset_x"]
        r["logo_offset_y"] = pos["logo_offset_y"]
        cvi = 15 + ((k - 1) % 10)                # лица 15..24
        label = f"WP152 hybrid #{k:02d}"
        rows.append((sid, cvi, label, r))
```
(Остальное тело `build_rows`/`main` без изменений — `[r[c] for c in COLS]` теперь подхватит новые ключи.)

- [ ] **Step 3: Проверить dry-run генератора**

Run:
```bash
cd unic-worker && DATABASE_URL='postgresql://openclaw:openclaw123@72.56.107.157:5432/openclaw' \
  python scripts/gen_wp152_schemes.py | head -3
```
Expected: либо строка идемпотентности `max(id)=70 >= 70 — уже вставлено` (если БД с 70 схемами), либо `INSERT ...` с `logo_position` в списке колонок и значениями top_left/top_right. Ошибок нет, импорт `element_positions` резолвится.

- [ ] **Step 4: Коммит**

```bash
git add unic-worker/scripts/gen_wp152_schemes.py
git commit -m "feat(wp152): генератор берёт позиции из element_positions (верхние углы)"
```

---

## Task 6: Применить фикс на БД и верифицировать

**Files:** нет правок кода — деплой данных + проверка.

- [ ] **Step 1: Снять бэкап текущих позиций 35-70 (для отката)**

Run:
```bash
PGPASSWORD=openclaw123 psql -h 72.56.107.157 -U openclaw -d openclaw -A -F'|' -c \
"SELECT id, overlay_video_position, logo_position, logo_offset_x, logo_offset_y \
 FROM unic_schemes WHERE id BETWEEN 35 AND 70 ORDER BY id" > /tmp/wp152_positions_backup.txt
wc -l /tmp/wp152_positions_backup.txt
```
Expected: 37 строк (заголовок + 36).

- [ ] **Step 2: Применить фикс**

Run:
```bash
cd unic-worker && DATABASE_URL='postgresql://openclaw:openclaw123@72.56.107.157:5432/openclaw' \
  python scripts/fix_wp152_element_positions.py --apply
```
Expected: `Обновлено 36 схем (id 35-70)`

- [ ] **Step 3: Верифицировать данные — ни одного низа/центра, лого напротив лица**

Run:
```bash
PGPASSWORD=openclaw123 psql -h 72.56.107.157 -U openclaw -d openclaw -t -A -c \
"SELECT count(*) FROM unic_schemes WHERE id BETWEEN 35 AND 70 \
 AND (overlay_video_position NOT IN ('top_left','top_right') \
      OR logo_position NOT IN ('top_left','top_right') \
      OR logo_position = overlay_video_position OR logo_position IS NULL)"
```
Expected: `0`

- [ ] **Step 4: Перезапустить воркеры с защитной правкой**

Применить ветку standalone на 91.98.180.103 (PM2 id0) и delivery на 72.56.107.157 (PM2 id36), `sudo pm2 restart` соответствующих процессов. (Если защитная правка воркера деплоится отдельно — согласовать с Данилом; для самих превью достаточно фикса данных, т.к. позиции теперь заданы явно.)

- [ ] **Step 5: Перегенерировать превью по тестовому проекту и снять визуальную приёмку**

Запустить штатную `scheme_preview`-очередь по тестовому проекту → дождаться 36/36 без ошибок → визуально подтвердить: у схем 35–70 лицо и лого в верхних углах, не пересекаются; «хорошие» 36,41,45,48,53,57,60,65,69 без изменений. Зафиксировать результат в OP#152.

---

## Завершение

- [ ] Запушить ветки во всех трёх репозиториях, открыть PR (delivery + standalone — код; docs — спека/план/evidence).
- [ ] OP#152 → «Тестирование» с описанием фикса; verify после первой реальной выкладки клиента (старт 10 июня).
- [ ] Обновить память: дополнить [[project_wp152_unic_schemes_expansion]] фактом о фиксе позиций.

## Self-Review (выполнено при написании)

- **Покрытие спеки:** данные (Task 2/6), генератор (Task 5), защита воркера оба репо (Task 3/4), верификация превью (Task 6) — все 4 компонента спеки покрыты.
- **Плейсхолдеры:** нет — весь код приведён целиком.
- **Консистентность типов:** `element_positions(sid)` возвращает один и тот же dict-контракт, используется в Task 1/2/5; ключи совпадают везде.
