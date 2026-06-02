# WP#152 — Расширение пула схем уникализации (34 → ~70) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Довести глобальный пул схем уникализации с 34 до ~70 схем (+36, id 35–70), добавив 10 круглых лиц-оверлеев и деликатный эффект «тряска», к выкладке клиента 10 июня.

**Architecture:** Существующие 34 схемы и 14 оверлеев не меняются — только добавление. Три кода-юнита (alembic-миграция колонок тряски, ветка фильтра «тряска» в локальном FFmpeg-воркере, prep-скрипт обрезки лиц в круг) + чистые данные (оверлеи в S3+БД, 36 схем прямым SQL, превью). Круглые лица композятся на зелёный `0x00ff00` и вырезаются штатным хромакеем воркера — правка воркера нужна только для тряски.

**Tech Stack:** Python 3 + FFmpeg + boto3 (S3 Beget), PostgreSQL (openclaw, localhost:5432), alembic, pytest. Репозитории: `validator` (`/root/.openclaw/workspace-genri/validator`), `autowarm` (`/root/.openclaw/workspace-genri/autowarm`), `contenthunter` (доки).

---

## Предусловия (окружение)

- БД: `source /tmp/pg.sh` экспортирует `PGHOST=localhost PGPORT=5432 PGUSER=openclaw PGDATABASE=openclaw` + пароль. Если файла нет — пересоздать из `validator/backend/.env` (`DATABASE_URL`).
- S3-креды: `autowarm/unic-worker/.env` (`S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET=1cabe906ea6e-gengo`, `S3_PUBLIC_URL=https://save.gengo.io`).
- 10 лиц уже скачаны в `/tmp/faces_152/*.mp4` (10 квадратных видео 768²–1440², H.264/HEVC, 24fps). Если их нет — `gdown --folder "https://drive.google.com/drive/folders/1vYBVAhHfS9PhS4vfLhCJpEjOMcpl9Wgp" -O /tmp/faces_152`.
- Воркер деплоится: `cd /root/.openclaw/workspace-genri/autowarm && git pull` + `sudo pm2 restart unic-worker`. Прод-каталог autowarm = пользователь `claude-user` (git pull без sudo), pm2 под root (sudo pm2).
- `unic_schemes` сейчас: 34 строки (id 1–34), все `status=true`. Оверлеи: `validator_unic_content` content_type=video, project_id=0, 14 строк (id 466–501), content_video_index 1–14.

---

## Task 1: Alembic-миграция — колонки тряски в unic_schemes

**Files:**
- Create: `/root/.openclaw/workspace-genri/validator/backend/alembic/versions/wp152_shake_columns.py`

- [ ] **Step 1: Узнать текущую head-ревизию alembic**

Run:
```bash
cd /root/.openclaw/workspace-genri/validator/backend && alembic heads
```
Записать выведенный revision id (обозначим `<HEAD_REV>`) — он пойдёт в `down_revision`.

- [ ] **Step 2: Создать файл миграции**

Создать `/root/.openclaw/workspace-genri/validator/backend/alembic/versions/wp152_shake_columns.py`:

```python
"""WP#152 — колонки эффекта 'тряска' для unic_schemes

Revision ID: wp152_shake_columns
Revises: <HEAD_REV>
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "wp152_shake_columns"
down_revision = "<HEAD_REV>"   # подставить из Step 1
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("unic_schemes", sa.Column("shake_amp", sa.Integer(), nullable=True))
    op.add_column("unic_schemes", sa.Column("shake_freq", sa.Numeric(), nullable=True, server_default="1.0"))
    op.add_column("unic_schemes", sa.Column("shake_axis", sa.Text(), nullable=True, server_default="xy"))


def downgrade():
    op.drop_column("unic_schemes", "shake_axis")
    op.drop_column("unic_schemes", "shake_freq")
    op.drop_column("unic_schemes", "shake_amp")
```

- [ ] **Step 3: Применить миграцию**

Run:
```bash
cd /root/.openclaw/workspace-genri/validator/backend && alembic upgrade head
```
Expected: `Running upgrade <HEAD_REV> -> wp152_shake_columns`.

- [ ] **Step 4: Проверить колонки в БД**

Run:
```bash
source /tmp/pg.sh && psql -c "SELECT column_name FROM information_schema.columns WHERE table_name='unic_schemes' AND column_name IN ('shake_amp','shake_freq','shake_axis') ORDER BY 1;"
```
Expected: три строки — `shake_amp`, `shake_axis`, `shake_freq`. Существующие 34 схемы имеют `shake_amp IS NULL` (тряска выкл).

- [ ] **Step 5: Commit (в validator-репо)**

```bash
cd /root/.openclaw/workspace-genri/validator && git add backend/alembic/versions/wp152_shake_columns.py && git commit -m "feat(wp152): unic_schemes shake_amp/shake_freq/shake_axis columns"
```

---

## Task 2: Ветка фильтра «тряска» в воркере (TDD)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/unic-worker/worker.py` (функция `generate_ffmpeg`, после блока `crop` ~строка 221)
- Test: `/root/.openclaw/workspace-genri/autowarm/unic-worker/tests/test_shake_filter.py`

Контекст: `generate_ffmpeg(scheme, files, chromakey_color, output_path)` возвращает список `cmd`; `'-filter_complex'` идёт сразу перед своим значением. Тряска = лёгкий зум `+2A` и `crop` обратно к исходному размеру с синусоидальным смещением окна (диапазон `[0,2A]`, всегда внутри кадра). Ось задаётся `shake_axis` (`'xy'|'x'|'y'`).

- [ ] **Step 1: Написать падающий тест**

Создать `/root/.openclaw/workspace-genri/autowarm/unic-worker/tests/test_shake_filter.py`:

```python
"""WP#152 — тесты ветки фильтра 'тряска' в generate_ffmpeg."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import worker  # noqa: E402


def _filter_complex(cmd):
    """Достаёт строку filter_complex из списка аргументов ffmpeg."""
    i = cmd.index("-filter_complex")
    return cmd[i + 1]


BASE_FILES = {"original": "in.mp4"}


def test_shake_off_when_amp_null():
    scheme = {"shake_amp": None}
    fc = _filter_complex(worker.generate_ffmpeg(scheme, BASE_FILES, None, "out.mp4"))
    assert "sin(2*PI" not in fc


def test_shake_off_when_amp_zero():
    scheme = {"shake_amp": 0}
    fc = _filter_complex(worker.generate_ffmpeg(scheme, BASE_FILES, None, "out.mp4"))
    assert "sin(2*PI" not in fc


def test_shake_xy_injects_scale_and_oscillating_crop():
    scheme = {"shake_amp": 4, "shake_freq": 1.0, "shake_axis": "xy"}
    fc = _filter_complex(worker.generate_ffmpeg(scheme, BASE_FILES, None, "out.mp4"))
    # зум на 2A=8 по обеим сторонам
    assert "scale=iw+8:ih+8" in fc
    # crop обратно к исходному размеру (iw-8) с осцилляцией по обеим осям
    assert "crop=iw-8:ih-8" in fc
    assert "4+4*sin(2*PI*1.0*t)" in fc
    assert "4+4*cos(2*PI*1.0*t)" in fc


def test_shake_x_axis_only_x_oscillates():
    scheme = {"shake_amp": 3, "shake_freq": 0.8, "shake_axis": "x"}
    fc = _filter_complex(worker.generate_ffmpeg(scheme, BASE_FILES, None, "out.mp4"))
    assert "3+3*sin(2*PI*0.8*t)" in fc   # X осциллирует
    # Y зафиксирован по центру (=A), без cos
    assert "cos(" not in fc.split("crop=")[1].split(" ")[0]


def test_shake_y_axis_only_y_oscillates():
    scheme = {"shake_amp": 5, "shake_freq": 1.2, "shake_axis": "y"}
    fc = _filter_complex(worker.generate_ffmpeg(scheme, BASE_FILES, None, "out.mp4"))
    assert "5+5*cos(2*PI*1.2*t)" in fc   # Y осциллирует
    assert "sin(" not in fc.split("crop=")[1].split(" ")[0]
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker && python -m pytest tests/test_shake_filter.py -v
```
Expected: FAIL (тряска ещё не реализована — `sin(2*PI...` отсутствует в filter_complex).

- [ ] **Step 3: Добавить ветку тряски в `generate_ffmpeg`**

В `/root/.openclaw/workspace-genri/autowarm/unic-worker/worker.py` найти блок `crop` (заканчивается строкой `l=lbl('cr'); fc.append(f'{cv} crop=iw-{int(cr)}:ih-{int(cr)}:{cx}:{cy} {l}'); cv=l`). Сразу ПОСЛЕ него (перед блоком `sp = scheme.get('speed')`) вставить:

```python
    sk = scheme.get('shake_amp')
    if sk and int(sk) > 0:
        A = int(sk)
        F = float(scheme.get('shake_freq') or 1.0)
        axis = (scheme.get('shake_axis') or 'xy').lower()
        ox = f'{A}+{A}*sin(2*PI*{F}*t)' if 'x' in axis else f'{A}'
        oy = f'{A}+{A}*cos(2*PI*{F}*t)' if 'y' in axis else f'{A}'
        lz = lbl('skz'); fc.append(f'{cv} scale=iw+{2*A}:ih+{2*A} {lz}'); cv = lz
        lc = lbl('skc'); fc.append(f"{cv} crop=iw-{2*A}:ih-{2*A}:'{ox}':'{oy}' {lc}"); cv = lc
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker && python -m pytest tests/test_shake_filter.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Регрессия — все тесты воркера зелёные**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker && python -m pytest tests/ -v
```
Expected: все passed (включая faststart/svg-тесты).

- [ ] **Step 6: Смок-рендер реальной тряски (визуальная проверка)**

Run:
```bash
cd /tmp && python3 - <<'PY'
import sys; sys.path.insert(0,'/root/.openclaw/workspace-genri/autowarm/unic-worker')
import worker, subprocess
scheme={'shake_amp':4,'shake_freq':1.0,'shake_axis':'xy'}
# нужен любой исходник; берём один из лиц как заглушку контента
cmd=worker.generate_ffmpeg(scheme, {'original':'/tmp/faces_152/vidu-video-3310076685166269.mp4'}, None, '/tmp/_shake_smoke.mp4')
print(' '.join(cmd))
subprocess.run(cmd, check=True, capture_output=True)
# проверка: нет чёрных полос
r=subprocess.run(['ffmpeg','-ss','1','-i','/tmp/_shake_smoke.mp4','-vframes','1','-vf','blackdetect=d=0:pic_th=0.98','-f','null','-'],capture_output=True,text=True)
print('BLACKDETECT:', 'black_start' in (r.stderr or ''))
PY
```
Expected: команда отрендерилась без ошибки; `BLACKDETECT: False` (нет чёрных полос от смещения).

- [ ] **Step 7: Commit (в autowarm-репо)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git add unic-worker/worker.py unic-worker/tests/test_shake_filter.py && git commit -m "feat(wp152): subtle shake filter branch (shake_amp/freq/axis) in unic-worker"
```

---

## Task 3: Prep-скрипт обрезки лиц в круг + загрузка оверлеев (TDD-функция + прогон)

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/unic-worker/scripts/prep_circle_overlays.py`
- Test: `/root/.openclaw/workspace-genri/autowarm/unic-worker/tests/test_prep_circle_overlays.py`

Принцип (прототип проверен): scale 720² → круглая альфа (`geq`, радиус 356 от центра 360,360) → композит на зелёный `0x00ff00` → H.264/yuv420p/faststart. Зелёный задаём сами → `chromakey_color='0x00ff00'`.

- [ ] **Step 1: Написать падающий тест на чистую функцию построения ffmpeg-команды**

Создать `/root/.openclaw/workspace-genri/autowarm/unic-worker/tests/test_prep_circle_overlays.py`:

```python
"""WP#152 — тест построителя ffmpeg-команды обрезки лица в круг."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import prep_circle_overlays as p  # noqa: E402


def test_build_circle_cmd_structure():
    cmd = p.build_circle_cmd("in.mp4", "out.mp4", size=720)
    j = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "in.mp4" in cmd
    assert cmd[-1] == "out.mp4"
    # зелёный фон-холст
    assert "color=c=0x00ff00:s=720x720" in j
    # круглая альфа: радиус 356 от центра 360,360
    assert "(X-360)*(X-360)+(Y-360)*(Y-360)" in j
    assert "356*356" in j
    # mobile-safe выход
    assert "libx264" in cmd and "yuv420p" in cmd
    assert "+faststart" in j


def test_build_circle_cmd_scales_to_size():
    cmd = p.build_circle_cmd("in.mp4", "out.mp4", size=720)
    assert "scale=720:720" in " ".join(cmd)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker && python -m pytest tests/test_prep_circle_overlays.py -v
```
Expected: FAIL (`ModuleNotFoundError: prep_circle_overlays`).

- [ ] **Step 3: Написать скрипт**

Создать `/root/.openclaw/workspace-genri/autowarm/unic-worker/scripts/prep_circle_overlays.py`:

```python
"""WP#152 — обрезка квадратных видео-лиц в круг на зелёном фоне + загрузка в S3
и регистрация в validator_unic_content как универсальный оверлей.

Запуск:  python scripts/prep_circle_overlays.py --src /tmp/faces_152 --apply
Без --apply делает только локальный рендер (dry-run, без S3/БД).
"""
import argparse
import glob
import os
import subprocess
import sys
import uuid

import boto3
import psycopg2

SIZE = 720
RADIUS = 356            # чуть меньше половины (360) — мягкий зазор от края
CENTER = SIZE // 2      # 360
GREEN = "0x00ff00"

S3_ENDPOINT = os.environ["S3_ENDPOINT"]
S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]
S3_BUCKET = os.environ["S3_BUCKET"]
S3_PUBLIC_URL = os.environ["S3_PUBLIC_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]


def build_circle_cmd(src, dst, size=SIZE):
    r, c = RADIUS, CENTER
    alpha = f"a='if(lte((X-{c})*(X-{c})+(Y-{c})*(Y-{c}),{r}*{r}),255,0)'"
    fc = (
        f"[0:v]scale={size}:{size},format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':{alpha}[circ];"
        f"[1:v][circ]overlay=0:0:shortest=1,format=yuv420p[out]"
    )
    return [
        "ffmpeg", "-y", "-i", src,
        "-f", "lavfi", "-i", f"color=c={GREEN}:s={size}x{size}:r=24",
        "-filter_complex", fc, "-map", "[out]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
        "-crf", "20", "-movflags", "+faststart", dst,
    ]


def s3_client():
    return boto3.client(
        "s3", endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY, aws_secret_access_key=S3_SECRET_KEY,
        config=boto3.session.Config(signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/faces_152")
    ap.add_argument("--apply", action="store_true", help="загрузить в S3 и записать в БД")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.src, "*.mp4")))
    files = [f for f in files if not os.path.basename(f).startswith("_")]
    print(f"Найдено {len(files)} файлов")
    if len(files) != 10:
        print("ВНИМАНИЕ: ожидалось 10 лиц"); 

    s3 = s3_client() if args.apply else None
    conn = psycopg2.connect(DATABASE_URL) if args.apply else None

    # стартовый content_video_index для новых оверлеев
    next_label_n = 15
    for i, src in enumerate(files):
        # validate
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", src],
            capture_output=True, text=True)
        if probe.returncode != 0 or "," not in probe.stdout:
            print(f"SKIP битый: {src}"); continue
        out = f"/tmp/_circle_{i:02d}.mp4"
        subprocess.run(build_circle_cmd(src, out), check=True, capture_output=True)
        print(f"OK круг: {out}")
        if not args.apply:
            continue
        key = f"factory/overlay_video/{uuid.uuid4().hex}.mp4"
        s3.upload_file(out, S3_BUCKET, key, ExtraArgs={"ContentType": "video/mp4"})
        url = f"{S3_ENDPOINT}/{S3_BUCKET}/{key}"
        label = f"video_0_{next_label_n}"; next_label_n += 1
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO validator_unic_content
                    (content_type, label, usage_type, project_id, file_path, chromakey_color)
                VALUES ('video', %s, 'Универсально (любой проект)', 0, %s, '0x00ff00')
                RETURNING id
            """, (label, url))
            new_id = cur.fetchone()[0]
        conn.commit()
        print(f"  → validator_unic_content id={new_id} label={label} url={url}")
    if conn:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker && python -m pytest tests/test_prep_circle_overlays.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Dry-run (локальный рендер 10 кругов, без S3/БД)**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker
set -a; . ./.env; set +a
python scripts/prep_circle_overlays.py --src /tmp/faces_152
```
Expected: `Найдено 10 файлов`, 10 строк `OK круг: /tmp/_circle_NN.mp4`.

- [ ] **Step 6: Визуальная проверка одного круга**

Run:
```bash
ffmpeg -y -ss 1 -i /tmp/_circle_00.mp4 -vframes 1 /tmp/_circle_00.png 2>/dev/null && echo "кадр готов /tmp/_circle_00.png"
```
Открыть `/tmp/_circle_00.png` (Read-инструментом) — убедиться: чистый круг с лицом, зелёный вне круга, без артефактов по кромке.

- [ ] **Step 7: Применить — залить 10 оверлеев в S3 + БД**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker
set -a; . ./.env; set +a
python scripts/prep_circle_overlays.py --src /tmp/faces_152 --apply
```
Expected: 10 строк `→ validator_unic_content id=… label=video_0_15..24 url=…`.

- [ ] **Step 8: Проверить, что оверлеев стало 24**

Run:
```bash
source /tmp/pg.sh && psql -c "SELECT count(*) FROM validator_unic_content WHERE content_type='video' AND project_id=0;"
```
Expected: `24`.

- [ ] **Step 9: Commit (в autowarm-репо)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git add unic-worker/scripts/prep_circle_overlays.py unic-worker/tests/test_prep_circle_overlays.py && git commit -m "feat(wp152): circle-crop overlay prep script + S3/DB registration"
```

---

## Task 4: Сгенерировать 36 схем (гибрид рецепт × лицо) прямым SQL

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/unic-worker/scripts/gen_wp152_schemes.py`

Принцип: 12 рецептов параметров × циклическая привязка к новым оверлеям (content_video_index 15–24). Схема k (k=1..36): `recipe = RECIPES[(k-1) % 12]`, `content_video_index = 15 + ((k-1) % 10)`. LCM(12,10)=60>36 → все пары (рецепт, лицо) в пределах 36 уникальны. Половина рецептов — с деликатной тряской (amp 2–6px, freq 0.5–1.2, разные оси). Значения в безопасных диапазонах существующих схем (scale_add 100–290, crop_reduce 200–430, rotate ±2°, speed 0.98–1.32).

- [ ] **Step 1: Написать генератор-скрипт**

Создать `/root/.openclaw/workspace-genri/autowarm/unic-worker/scripts/gen_wp152_schemes.py`:

```python
"""WP#152 — вставка 36 новых схем уникализации (id 35–70) гибридом рецепт × лицо.

Запуск: python scripts/gen_wp152_schemes.py --apply   (без --apply печатает SQL, не пишет)
Идемпотентность: вставляет только если max(id) < 70 (защита от повторного прогона).
"""
import argparse
import os

import psycopg2

DATABASE_URL = os.environ["DATABASE_URL"]

# 12 рецептов; shake_* = None означает тряска выкл.
RECIPES = [
    dict(scale_add=120, pad_add=200, rotate_deg=0.4,  crop_reduce=220, crop_offset_x=110, crop_offset_y=100, speed=1.03, audio_atempo=1.03, audio_volume=0.85, audio_highpass=180, audio_lowpass=8500, overlay_video_scale_w=220, overlay_video_scale_h=200, overlay_video_position="top_left",     shake_amp=None, shake_freq=None, shake_axis=None),
    dict(scale_add=150, pad_add=200, rotate_deg=-0.6, crop_reduce=260, crop_offset_x=120, crop_offset_y=130, speed=1.06, audio_atempo=1.06, audio_volume=0.90, audio_highpass=150, audio_lowpass=9000, overlay_video_scale_w=240, overlay_video_scale_h=220, overlay_video_position="top_right",    shake_amp=3,    shake_freq=0.8,  shake_axis="xy"),
    dict(scale_add=100, pad_add=200, rotate_deg=0.8,  crop_reduce=300, crop_offset_x=150, crop_offset_y=120, speed=0.99, audio_atempo=0.99, audio_volume=0.80, audio_highpass=200, audio_lowpass=8000, overlay_video_scale_w=200, overlay_video_scale_h=190, overlay_video_position="bottom_left",  shake_amp=None, shake_freq=None, shake_axis=None),
    dict(scale_add=200, pad_add=200, rotate_deg=-1.0, crop_reduce=240, crop_offset_x=100, crop_offset_y=100, speed=1.10, audio_atempo=1.10, audio_volume=0.95, audio_highpass=170, audio_lowpass=8800, overlay_video_scale_w=260, overlay_video_scale_h=240, overlay_video_position="bottom_right", shake_amp=4,    shake_freq=1.0,  shake_axis="x"),
    dict(scale_add=130, pad_add=200, rotate_deg=1.2,  crop_reduce=280, crop_offset_x=130, crop_offset_y=110, speed=1.02, audio_atempo=1.02, audio_volume=0.88, audio_highpass=160, audio_lowpass=8600, overlay_video_scale_w=230, overlay_video_scale_h=210, overlay_video_position="top_left",     shake_amp=None, shake_freq=None, shake_axis=None),
    dict(scale_add=170, pad_add=200, rotate_deg=-0.4, crop_reduce=320, crop_offset_x=140, crop_offset_y=140, speed=1.08, audio_atempo=1.08, audio_volume=0.92, audio_highpass=190, audio_lowpass=8200, overlay_video_scale_w=250, overlay_video_scale_h=230, overlay_video_position="center",       shake_amp=5,    shake_freq=1.2,  shake_axis="xy"),
    dict(scale_add=110, pad_add=200, rotate_deg=0.6,  crop_reduce=210, crop_offset_x=100, crop_offset_y=120, speed=1.04, audio_atempo=1.04, audio_volume=0.83, audio_highpass=175, audio_lowpass=8700, overlay_video_scale_w=215, overlay_video_scale_h=200, overlay_video_position="top_right",    shake_amp=2,    shake_freq=0.6,  shake_axis="y"),
    dict(scale_add=220, pad_add=200, rotate_deg=-1.5, crop_reduce=350, crop_offset_x=160, crop_offset_y=150, speed=1.12, audio_atempo=1.12, audio_volume=0.97, audio_highpass=165, audio_lowpass=9200, overlay_video_scale_w=270, overlay_video_scale_h=250, overlay_video_position="bottom_left",  shake_amp=None, shake_freq=None, shake_axis=None),
    dict(scale_add=140, pad_add=200, rotate_deg=1.0,  crop_reduce=250, crop_offset_x=120, crop_offset_y=100, speed=1.01, audio_atempo=1.01, audio_volume=0.86, audio_highpass=185, audio_lowpass=8400, overlay_video_scale_w=235, overlay_video_scale_h=215, overlay_video_position="bottom_right", shake_amp=6,    shake_freq=1.0,  shake_axis="xy"),
    dict(scale_add=160, pad_add=200, rotate_deg=-0.8, crop_reduce=290, crop_offset_x=135, crop_offset_y=125, speed=1.07, audio_atempo=1.07, audio_volume=0.90, audio_highpass=155, audio_lowpass=8900, overlay_video_scale_w=245, overlay_video_scale_h=225, overlay_video_position="top_left",     shake_amp=None, shake_freq=None, shake_axis=None),
    dict(scale_add=120, pad_add=200, rotate_deg=0.3,  crop_reduce=230, crop_offset_x=110, crop_offset_y=115, speed=1.05, audio_atempo=1.05, audio_volume=0.84, audio_highpass=180, audio_lowpass=8500, overlay_video_scale_w=225, overlay_video_scale_h=205, overlay_video_position="center",       shake_amp=3,    shake_freq=0.9,  shake_axis="x"),
    dict(scale_add=190, pad_add=200, rotate_deg=-1.2, crop_reduce=310, crop_offset_x=145, crop_offset_y=135, speed=1.09, audio_atempo=1.09, audio_volume=0.94, audio_highpass=168, audio_lowpass=8300, overlay_video_scale_w=255, overlay_video_scale_h=235, overlay_video_position="top_right",    shake_amp=4,    shake_freq=1.1,  shake_axis="xy"),
    dict(scale_add=135, pad_add=200, rotate_deg=0.9,  crop_reduce=270, crop_offset_x=125, crop_offset_y=120, speed=1.00, audio_atempo=1.00, audio_volume=0.87, audio_highpass=178, audio_lowpass=8600, overlay_video_scale_w=238, overlay_video_scale_h=218, overlay_video_position="bottom_left",  shake_amp=None, shake_freq=None, shake_axis=None),
]

COLS = ["scale_add","pad_add","rotate_deg","crop_reduce","crop_offset_x","crop_offset_y",
        "speed","audio_atempo","audio_volume","audio_highpass","audio_lowpass",
        "overlay_video_scale_w","overlay_video_scale_h","overlay_video_position",
        "shake_amp","shake_freq","shake_axis"]


def build_rows():
    rows = []
    for k in range(1, 37):                       # 36 схем
        r = RECIPES[(k - 1) % len(RECIPES)]
        cvi = 15 + ((k - 1) % 10)                # лица 15..24
        sid = 34 + k                             # id 35..70
        label = f"WP152 hybrid #{k:02d}"
        rows.append((sid, cvi, label, r))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(max(id),0) FROM unic_schemes")
        mx = cur.fetchone()[0]
        if mx >= 70:
            print(f"max(id)={mx} ≥ 70 — уже вставлено, выходим (идемпотентность)"); return
        rows = build_rows()
        for sid, cvi, label, r in rows:
            collist = ", ".join(["id","label","status","content_video_index","content_logo_index"] + COLS)
            vals = [sid, label, True, cvi, 1] + [r[c] for c in COLS]
            ph = ", ".join(["%s"] * len(vals))
            sql = f"INSERT INTO unic_schemes ({collist}) VALUES ({ph})"
            if args.apply:
                cur.execute(sql, vals)
            else:
                print(sql, vals)
        if args.apply:
            conn.commit()
            print(f"Вставлено {len(rows)} схем (id 35–70)")
    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run — посмотреть SQL без записи**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker
set -a; . ./.env; set +a
python scripts/gen_wp152_schemes.py | head -5
```
Expected: 36 строк `INSERT INTO unic_schemes ...` с id 35–70.

- [ ] **Step 3: Применить — вставить 36 схем**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker
set -a; . ./.env; set +a
python scripts/gen_wp152_schemes.py --apply
```
Expected: `Вставлено 36 схем (id 35–70)`.

- [ ] **Step 4: Проверить пул и уникальность пар**

Run:
```bash
source /tmp/pg.sh && psql -c "SELECT count(*) total FROM unic_schemes;" \
  -c "SELECT count(*) FILTER (WHERE shake_amp>0) AS with_shake FROM unic_schemes WHERE id BETWEEN 35 AND 70;" \
  -c "SELECT count(DISTINCT (scale_add,crop_reduce,rotate_deg,speed,content_video_index)) AS distinct_combos FROM unic_schemes WHERE id BETWEEN 35 AND 70;"
```
Expected: `total = 70`; `with_shake = 21` (7 из 12 рецептов со тряской × 3 копии); `distinct_combos = 36` (все уникальны).

- [ ] **Step 5: Commit (в autowarm-репо)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git add unic-worker/scripts/gen_wp152_schemes.py && git commit -m "feat(wp152): generate 36 hybrid schemes (recipe x face), ids 35-70"
```

---

## Task 5: Деплой воркера + рендер-тест всех новых схем + превью

**Files:** нет новых; используется воркерный пайплайн.

- [ ] **Step 1: Задеплоить воркер (тряска должна быть в проде до рендера shake-схем)**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm && git pull --ff-only && sudo pm2 restart unic-worker && sudo pm2 status unic-worker
```
Expected: pull без конфликтов; `unic-worker` online.

- [ ] **Step 2: Рендер-тест каждой новой схемы (35–70) через пайплайн воркера**

Run:
```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker
set -a; . ./.env; set +a
python3 - <<'PY'
import os, sys, subprocess, tempfile, urllib.request
sys.path.insert(0,'.')
import worker, psycopg2
conn=psycopg2.connect(os.environ['DATABASE_URL']); conn.autocommit=True
cur=conn.cursor()
cur.execute("SELECT * FROM unic_schemes WHERE id BETWEEN 35 AND 70 ORDER BY id")
cols=[d[0] for d in cur.description]; schemes=[dict(zip(cols,r)) for r in cur.fetchall()]
# подобрать оверлей по content_video_index
cur.execute("SELECT id,file_path,chromakey_color FROM validator_unic_content WHERE content_type='video' AND project_id=0 ORDER BY id")
ovs=cur.fetchall()
src='/tmp/faces_152/vidu-video-3310076685166269.mp4'  # любой валидный контент-исходник
bad=[]
for s in schemes:
    cvi=s['content_video_index']; ov=ovs[(cvi-1)%len(ovs)]
    # скачать оверлей локально
    op=f"/tmp/_ov_{ov[0]}.mp4"
    if not os.path.exists(op): urllib.request.urlretrieve(ov[1].replace('s3.ru1.storage.beget.cloud/'+os.environ['S3_BUCKET'], 'save.gengo.io') if False else ov[1], op)
    out=f"/tmp/_rt_{s['id']}.mp4"
    cmd=worker.generate_ffmpeg(s, {'original':src,'overlay_video':op}, ov[2], out)
    r=subprocess.run(cmd, capture_output=True)
    if r.returncode!=0 or not os.path.exists(out) or os.path.getsize(out)<10000:
        bad.append((s['id'], r.stderr.decode()[-200:]))
    else:
        os.remove(out)
print('FAILED:', bad if bad else 'НЕТ — все 36 отрендерились')
assert not bad, bad
PY
```
Expected: `FAILED: НЕТ — все 36 отрендерились`.

- [ ] **Step 3: Превью — НЕ пре-рендерим вручную (исправление по факту реализации)**

**Корректировка модели (обнаружено при реализации):** превью в `validator_scheme_previews` хранятся **по-проектно** (пара scheme_id+project_id), генерируются при заведении проекта клиента через штатную `scheme_preview`-очередь (`scheme_preview_queue.py` → воркер рендерит ПОЛНЫМ пайплайном, с лицом+тряской). Универсальных (project_id=0) превью у существующих схем 1–34 **нет** (проверено: count=0). Поэтому ручной пре-рендер project_0-превью противоречит модели и создал бы строки-сироты.

Действие: ничего не пре-рендерим. Когда заведут проект нового клиента и сгенерят превью штатно (UI/эндпоинт «генерировать превью»), все 70 схем (вкл. 36 новых) получат корректные превью автоматически — потому что воркер задеплоен (Step 1), новые оверлеи и схемы уже в БД. Рендер-тест (Step 2) — и есть доказательство, что превью/боевой рендер этих 36 схем отработают (тот же код-путь воркера).

- [ ] **Step 4: Подтвердить, что новый пул валиден end-to-end**

Render-test из Step 2 = 36/36 PASS — достаточное доказательство. Дополнительно зафиксировать в evidence: превью генерируются per-project при настройке клиента; ручной project_0 пре-рендер не требуется.

---

## Task 6: Финализация — OpenProject, evidence, мерж ветки

**Files:**
- Create: `docs/evidence/2026-06-02-wp152-unic-schemes-expansion-shipped.md` (в contenthunter-репо)

- [ ] **Step 1: Написать evidence-доку** (что сделано, числа: 70 схем, 24 оверлея, 18 со тряской, рендер-тест PASS).

- [ ] **Step 2: Commit + push ветки contenthunter, открыть PR в main.**

```bash
git add docs/ && git commit -m "docs(wp152): evidence — пул схем 34→70 задеплоен" && git push -u origin worktree-wp152-unic-schemes
```

- [ ] **Step 3: Прокомментировать OpenProject #152 и перевести в «Тестирование» (id 9).**

Стиль комментария — простой язык (Что было не так → Что сделано → Что осталось), без жаргона/PR/хэшей, без подписи. PATCH статуса: получить `lockVersion`, затем `{"lockVersion":N,"_links":{"status":{"href":"/api/v3/statuses/9"}}}`. Механика: memory `reference-openproject-access`.

- [ ] **Step 4: Verify-чек после первого реального слота** клиента (схема подобралась, ролик отрендерился, выложился) → перевести #152 в «Готово» (id 12).

---

## Self-Review (выполнено автором плана)

- **Покрытие спеки:** Компонент 1 (круглые оверлеи) → Task 3; Компонент 2 (тряска) → Task 1+2; Компонент 3 (36 схем) → Task 4; Компонент 4 (превью+валидация) → Task 5; деплой/откат → Task 5/6. ✓
- **Заглушки:** код приведён полностью во всех code-шагах; Task 5 Step 3 содержит ветвление (готовый скрипт vs ручной upsert) — это осознанная развилка, требующая чтения `generate_scheme_previews.py` (команда дана). Допустимо как «проверить и выбрать», не заглушка-логики.
- **Согласованность типов:** функция `generate_ffmpeg` — единое имя; колонки `shake_amp/shake_freq/shake_axis` одинаковы в Task 1 (миграция), Task 2 (воркер читает), Task 4 (генератор пишет). `build_circle_cmd` — одно имя в скрипте и тесте. ✓
- **Числовая сверка:** 12 рецептов, формула k→recipe/cvi даёт 36 уникальных пар; with_shake: рецепты с shake в позициях 2,4,6,7,9,10,12 (7 из 12) → по 3 копии, но 36/12=3 → 7×3=21? Перепроверить в Task 4 Step 4: фактическое число shake-схем = (кол-во рецептов со shake среди индексов, попавших в 36 слотов). 36 слотов = рецепты [0..11] по 3 раза каждый → shake-рецептов 7 → 21 со тряской. **Исправлено в Task 4 Step 4: `with_shake = 21`.**
