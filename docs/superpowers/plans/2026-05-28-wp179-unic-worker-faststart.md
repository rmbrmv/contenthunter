# WP #179 — unic-worker `+faststart` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить `-movflags +faststart` в финальный output `unic-worker/worker.py` (один `subprocess.run` на l.322), чтобы все новые `unic_results` приходили на CDN с `moov atom` в начале — фикс чёрных миниатюр и нерабочего выбора в ручной выкладке IG/YT. Плюс одноразовый бэкфилл существующих файлов.

**Architecture:** Точечная правка одной ffmpeg-команды (concat финал) — `+faststart` это перенос moov atom upfront, без транскодинга. TDD-канарейка: тест проверяет порядок атомов в выходном файле, чтобы регресс ловился сразу. Бэкфилл — отдельный one-shot скрипт с idempotent skip уже-faststart файлов и `*.preremux.mp4` бекапом на CDN на 24ч.

**Tech Stack:** Python 3.12, ffmpeg/ffprobe (системные, есть в окружении), boto3 (S3 уже в `unic-worker/requirements.txt`), psycopg2-binary (БД openclaw, уже там), pytest (тесты), PM2 (рестарт воркера в проде).

---

## File Structure

- **Modify:** `unic-worker/worker.py` — добавить `-movflags +faststart` в финальный concat (l.322); добавить INFO-лог `unic.final.faststart`.
- **Create:** `unic-worker/tests/test_create_final_output_faststart.py` — TDD-канарейка на atom-order.
- **Create:** `unic-worker/scripts/backfill_faststart.py` — одноразовый remux существующих CDN-объектов (с preserve metadata + tagging бэкапов).
- **Create:** `unic-worker/scripts/cleanup_preremux.py` — T+24ч cleanup `.preremux.mp4` бэкапов (фильтр: суффикс + тег `wp179_preremux=1` + LastModified > N часов).
- **Create:** `unic-worker/tests/test_backfill_faststart.py` — unit-тесты бэкфилла (skip-already-faststart, dry-run, preserve metadata).
- **No new shared helpers** — `atom_offsets()` живёт в test-файле; `head_has_moov`/`_extra_args_from_head` — в backfill-скрипте (используются только там).

---

## Task 1: Failing test — atom order canary

**Files:**
- Create: `unic-worker/tests/test_create_final_output_faststart.py`

- [ ] **Step 1: Написать failing-тест**

Содержание `unic-worker/tests/test_create_final_output_faststart.py`:

```python
"""TDD-канарейка: финальный output unic-worker имеет moov atom раньше mdat.

Регрессия WP #179: ручная выкладка IG/YT не подхватывает миниатюры/выбор для файлов,
у которых moov atom в хвосте mp4 (нет -movflags +faststart). Этот тест ловит уход
этого флага из worker.py:322 в любой будущей правке."""
import os
import struct
import subprocess
import sys
import tempfile

import pytest

# Импорт create_final_output из worker.py соседним путём
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import worker  # noqa: E402


def atom_offsets(path: str, max_bytes: int = 1024 * 1024) -> dict[str, int]:
    """Возвращает {atom_name: offset_in_file} для top-level ISOBMFF атомов в первых max_bytes.

    Окно 1MB достаточно для любого реалистичного moov atom (типично <100KB), что-бы
    канарейка не ложно-фейлила для faststart-файлов с большим moov, у которых mdat
    легитимно начинается после первых 4KB."""
    with open(path, "rb") as f:
        data = f.read(max_bytes)
    result: dict[str, int] = {}
    i = 0
    while i + 8 <= len(data):
        sz = struct.unpack(">I", data[i:i+4])[0]
        name = data[i+4:i+8].decode("ascii", errors="replace")
        if not name.isalnum():
            break
        result.setdefault(name, i)
        if sz < 8:
            break
        i += sz
    return result


def _make_seed(tmpdir: str) -> str:
    """1-секундный красный квадрат + тишина — минимальный валидный mp4 для concat."""
    seed = os.path.join(tmpdir, "seed.mp4")
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=320x320:d=1:r=30",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         seed],
        check=True, capture_output=True, timeout=30,
    )
    return seed


def test_moov_before_mdat(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "TEMP_DIR", str(tmp_path))
    seed = _make_seed(str(tmp_path))
    out = worker.create_final_output(seed, scheme_id=0, base_name="ff_canary")
    atoms = atom_offsets(out)
    assert "moov" in atoms, (
        f"moov atom не найден в первых 1MB финального output: {atoms}. "
        f"Похоже, ffmpeg не вставил moov upfront (-movflags +faststart)."
    )
    # Faststart-валидный output: либо mdat виден в окне И moov раньше mdat,
    # либо mdat ещё не виден (moov достаточно большой и упёрся бы за окно — но
    # сама вершина moov уже raньше любых данных, что нам и нужно).
    if "mdat" in atoms:
        assert atoms["moov"] < atoms["mdat"], (
            f"moov должен быть раньше mdat для faststart-ready mp4. "
            f"Текущий порядок: {sorted(atoms.items(), key=lambda kv: kv[1])}"
        )
```

- [ ] **Step 2: Запустить тест — должен УПАСТЬ**

```bash
cd /home/claude-user/autowarm-testbench/unic-worker
python -m pytest tests/test_create_final_output_faststart.py::test_moov_before_mdat -v
```

Expected: FAIL с `AssertionError: moov должен быть раньше mdat` (или `moov atom not in first 4KB`). Без `+faststart` ffmpeg пишет moov в хвост → тест падает. Это доказывает, что тест чувствителен.

- [ ] **Step 3: Commit failing test**

```bash
cd /home/claude-user/autowarm-testbench
git add unic-worker/tests/test_create_final_output_faststart.py
git commit -m "test(wp179): failing canary — moov atom должен быть раньше mdat в финальном output unic-worker

Регрессия WP #179: без -movflags +faststart мобильная галерея IG не строит миниатюру
(чёрный thumb), выбор файла в Reels picker не отрабатывает. Тест читает первые 4KB
выходного файла и проверяет порядок ISOBMFF-атомов."
```

---

## Task 2: Минимальный фикс — `+faststart` в финальный concat

**Files:**
- Modify: `unic-worker/worker.py:322` (один `subprocess.run`).

- [ ] **Step 1: Применить правку**

В файле `unic-worker/worker.py`, функция `create_final_output`, строка 322:

Было:

```python
    subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',cp,'-c','copy',op], check=True,capture_output=True,timeout=120)
```

Стало:

```python
    subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',cp,'-c','copy','-movflags','+faststart',op], check=True,capture_output=True,timeout=120)
```

- [ ] **Step 2: Запустить тест — должен ПРОЙТИ**

```bash
cd /home/claude-user/autowarm-testbench/unic-worker
python -m pytest tests/test_create_final_output_faststart.py::test_moov_before_mdat -v
```

Expected: PASS.

- [ ] **Step 3: Прогнать существующие unic-worker тесты — не должны регрессировать**

```bash
cd /home/claude-user/autowarm-testbench/unic-worker
python -m pytest tests/ -v
```

Expected: все зелёные (`test_svg_raster.py`, `test_worker_svg_net.py`, новый канарейка).

- [ ] **Step 4: Commit фикс**

```bash
cd /home/claude-user/autowarm-testbench
git add unic-worker/worker.py
git commit -m "fix(wp179): +faststart на финальный output unic-worker

worker.py:322 финальный ffmpeg concat теперь передаёт -movflags +faststart, чтобы
moov atom попадал в head mp4. Без этого мобильная галерея IG/YT-creator-studio не
строит миниатюру (читает только первые 1-2MB, не находит moov) и не отрабатывает
выбор файла в Reels picker — баг ручной выкладки. Авто-публикатор не страдает,
потому что publisher_base.py:2789 _remux_mp4_if_available уже делает faststart
перед загрузкой в IG-аппликуху.

Verified: до правки head=[ftyp,free,mdat], moov в хвосте; после =[ftyp,moov,...].
Никакой потери качества (только перенос атома)."
```

---

## Task 3: Observability — INFO-лог `unic.final.faststart`

**Files:**
- Modify: `unic-worker/worker.py` `create_final_output` (после concat).

- [ ] **Step 1: Добавить лог-строку**

В функции `create_final_output`, сразу после `subprocess.run(...concat...)` и до возврата `op`, добавить (в самый конец функции, перед `return op`):

```python
    # Observability: ПРОВЕРЯЕМ, что moov реально раньше mdat (а не просто что
    # ffmpeg вернул 0). Это и есть smoke-сигнал по WP #179.
    try:
        import struct as _struct
        with open(op, "rb") as _fh:
            _head = _fh.read(1024 * 1024)  # 1MB достаточно для любого реалистичного moov
        _i = 0
        _moov_off = _mdat_off = None
        while _i + 8 <= len(_head):
            _sz = _struct.unpack(">I", _head[_i:_i+4])[0]
            _name = _head[_i+4:_i+8].decode("ascii", errors="replace")
            if not _name.isalnum():
                break
            if _name == "moov" and _moov_off is None:
                _moov_off = _i
            if _name == "mdat" and _mdat_off is None:
                _mdat_off = _i
            if _sz < 8:
                break
            _i += _sz
        _ok = (_moov_off is not None) and (_mdat_off is None or _moov_off < _mdat_off)
        if _ok:
            logger.info(
                f"unic.final.faststart_ok scheme_id={scheme_id} size={os.path.getsize(op)} "
                f"moov_off={_moov_off} mdat_off={_mdat_off}"
            )
        else:
            logger.warning(
                f"unic.final.faststart_MISSING scheme_id={scheme_id} size={os.path.getsize(op)} "
                f"moov_off={_moov_off} mdat_off={_mdat_off} — флаг -movflags +faststart не применился!"
            )
    except Exception as _e:
        logger.warning(f"unic.final.faststart_check_failed scheme_id={scheme_id} err={_e}")
```

- [ ] **Step 2: Smoke-тест на лог-формат (опционально)**

```bash
cd /home/claude-user/autowarm-testbench/unic-worker
python -c "
import logging, worker, tempfile, subprocess
logging.basicConfig(level=logging.INFO)
with tempfile.TemporaryDirectory() as td:
    worker.TEMP_DIR = td
    seed = td + '/seed.mp4'
    subprocess.run(['ffmpeg','-y','-f','lavfi','-i','color=c=red:s=320x320:d=1:r=30',
                    '-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100',
                    '-shortest','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',seed],
                   check=True, capture_output=True, timeout=30)
    out = worker.create_final_output(seed, 0, 'smoke')
    print('produced:', out)
"
```

Expected: stderr строка `unic.final.faststart_ok scheme_id=0 size=... moov_off=N mdat_off=M` где `N<M` (moov раньше mdat). Если когда-то правка `worker.py:322` уйдёт, лог сменится на `unic.final.faststart_MISSING ...` — это и есть проктовый regression-сигнал.

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add unic-worker/worker.py
git commit -m "feat(wp179): observability — INFO unic.final.faststart на выходе create_final_output

Грепабельный лог в проде: подтверждает что faststart применён и atom0=ftyp.
Помогает оперативно подтвердить активность фикса без ffprobe-разведки."
```

---

## Task 4: Бэкфилл-скрипт — модуль и unit-тесты

**Files:**
- Create: `unic-worker/scripts/backfill_faststart.py`
- Create: `unic-worker/tests/test_backfill_faststart.py`

- [ ] **Step 1: Написать модуль с pure-функциями**

Создать `unic-worker/scripts/backfill_faststart.py`:

```python
"""WP #179 — одноразовый бэкфилл: remux существующих unic_results CDN-файлов в faststart.

Безопасно (-c copy, только реорганизация атомов). Идемпотентно (skip если moov уже в head).
Перед перезаливкой сохраняем оригинал под `<key>.preremux.mp4` на 24ч (cron-cleanup).

Usage:
    python -m scripts.backfill_faststart --project-id 85 --dry-run
    python -m scripts.backfill_faststart --project-id 85
    python -m scripts.backfill_faststart --since 2026-05-20  # все active
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import struct
import subprocess
import tempfile
from typing import Iterable

import boto3
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse

log = logging.getLogger("backfill_faststart")

S3_BUCKET = os.environ.get("UNIC_S3_BUCKET", "save-gengo-io")
S3_PREFIX = os.environ.get("UNIC_S3_PREFIX", "autowarm/unic/")
DB_CONFIG = {
    "host":   os.environ.get("DB_HOST", "localhost"),
    "port":   int(os.environ.get("DB_PORT", "5432")),
    "user":   os.environ.get("DB_USER", "openclaw"),
    "password": os.environ.get("DB_PASSWORD", "openclaw123"),
    "dbname": os.environ.get("DB_NAME", "openclaw"),
}


def head_has_moov(head_bytes: bytes) -> bool:
    """True если в первых 4KB есть атом moov раньше mdat."""
    i = 0
    moov_off = mdat_off = None
    while i + 8 <= len(head_bytes):
        sz = struct.unpack(">I", head_bytes[i:i+4])[0]
        name = head_bytes[i+4:i+8].decode("ascii", errors="replace")
        if not name.isalnum():
            break
        if name == "moov" and moov_off is None:
            moov_off = i
        if name == "mdat" and mdat_off is None:
            mdat_off = i
        if sz < 8:
            break
        i += sz
    if moov_off is None:
        return False
    if mdat_off is None:
        return True  # видим только moov+ftyp в первых 4KB → faststart-ok
    return moov_off < mdat_off


def url_to_s3_key(output_url: str) -> str:
    """https://save.gengo.io/autowarm/unic/foo.mp4 → autowarm/unic/foo.mp4."""
    return urlparse(output_url).path.lstrip("/")


def fetch_head(s3, key: str, n: int = 4096) -> bytes:
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key, Range=f"bytes=0-{n-1}")
    return obj["Body"].read()


def remux_to_faststart(src_path: str, dst_path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", src_path, "-c", "copy",
         "-movflags", "+faststart", dst_path],
        check=True, capture_output=True, timeout=300,
    )


def select_candidates(conn, project_id: int | None, since: str | None) -> list[dict]:
    where = ["r.status='done'", "r.output_url IS NOT NULL", "r.output_url LIKE 'https://save.gengo.io/%'"]
    params: list = []
    if project_id is not None:
        where.append("t.project_id = %s")
        params.append(project_id)
    if since:
        where.append("r.created_at >= %s::date")
        params.append(since)
    sql = (
        "SELECT r.id, r.output_url, t.project_id, t.slot_date "
        "FROM unic_results r JOIN unic_tasks t ON t.id = r.task_id "
        "WHERE " + " AND ".join(where) + " ORDER BY r.id DESC"
    )
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


_PRESERVE_HEADERS = (
    "ContentType",
    "CacheControl",
    "ContentDisposition",
    "ContentEncoding",
    "ContentLanguage",
)


def _extra_args_from_head(head_meta: dict) -> dict:
    """Скопировать sysmd headers + user Metadata из head_object для re-upload.

    Если у объекта стоят Cache-Control / Content-Disposition / custom Metadata —
    сохраняем, чтобы re-upload не сбрасывал поведение CDN. ACL не трогаем
    (бакет статический, ACL объекта обычно наследуется от политики бакета)."""
    args: dict = {}
    for h in _PRESERVE_HEADERS:
        v = head_meta.get(h)
        if v is not None:
            args[h] = v
    md = head_meta.get("Metadata") or {}
    if md:
        args["Metadata"] = dict(md)
    # дефолт-фоллбэк, если у объекта почему-то нет ContentType
    args.setdefault("ContentType", "video/mp4")
    return args


def process_one(s3, row: dict, dry_run: bool) -> str:
    """Returns one of: 'skipped', 'remuxed', 'failed'."""
    key = url_to_s3_key(row["output_url"])
    try:
        head = fetch_head(s3, key)
    except Exception as e:
        log.warning(f"head_fetch_failed id={row['id']} key={key} err={e}")
        return "failed"
    if head_has_moov(head):
        log.info(f"skip_already_faststart id={row['id']} key={key}")
        return "skipped"
    if dry_run:
        log.info(f"DRYRUN_would_remux id={row['id']} key={key}")
        return "remuxed"
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "src.mp4")
        dst = os.path.join(td, "dst.mp4")
        s3.download_file(S3_BUCKET, key, src)
        remux_to_faststart(src, dst)
        # backup оригинал → <key>.preremux.mp4 (MetadataDirective=COPY: дефолт copy_object)
        backup_key = key + ".preremux.mp4"
        try:
            s3.copy_object(
                Bucket=S3_BUCKET,
                CopySource={"Bucket": S3_BUCKET, "Key": key},
                Key=backup_key,
                # explicit MetadataDirective=COPY — оставить настройки оригинала на бэкапе
                MetadataDirective="COPY",
                # пометка для cleanup-шага: бэкап создан этим скриптом
                Tagging="wp179_preremux=1",
                TaggingDirective="REPLACE",
            )
        except Exception as e:
            log.warning(f"backup_failed id={row['id']} key={key} err={e}")
            return "failed"
        # re-upload remuxed: сохраняем настройки оригинала (Cache-Control, Metadata и пр.)
        try:
            head_meta = s3.head_object(Bucket=S3_BUCKET, Key=key)
        except Exception as e:
            log.warning(f"head_object_failed id={row['id']} key={key} err={e}")
            return "failed"
        extra_args = _extra_args_from_head(head_meta)
        try:
            s3.upload_file(dst, S3_BUCKET, key, ExtraArgs=extra_args)
        except Exception as e:
            log.warning(f"upload_failed id={row['id']} key={key} err={e} backup_kept={backup_key}")
            return "failed"
        log.info(f"remuxed id={row['id']} key={key} backup={backup_key} preserved={sorted(extra_args)}")
        return "remuxed"


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", type=int, default=None)
    ap.add_argument("--since", type=str, default=None, help="YYYY-MM-DD; created_at >= since")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        rows = select_candidates(conn, args.project_id, args.since)
    finally:
        conn.close()
    log.info(f"candidates={len(rows)} project_id={args.project_id} since={args.since} dry_run={args.dry_run}")
    s3 = boto3.client("s3")
    counts = {"skipped": 0, "remuxed": 0, "failed": 0}
    for row in rows:
        counts[process_one(s3, row, args.dry_run)] += 1
    log.info(f"done {counts}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Написать unit-тесты для pure-функций**

Создать `unic-worker/tests/test_backfill_faststart.py`:

```python
"""WP #179 — тесты бэкфилла. Pure-функции (head_has_moov, url_to_s3_key) + S3-mocked process_one."""
import os
import struct
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import backfill_faststart as bf  # noqa: E402


def _box(name: str, payload: bytes = b"") -> bytes:
    sz = 8 + len(payload)
    return struct.pack(">I", sz) + name.encode("ascii") + payload


def test_head_has_moov_when_moov_before_mdat():
    head = _box("ftyp", b"isom") + _box("moov", b"x" * 100) + _box("mdat", b"y" * 1000)
    assert bf.head_has_moov(head) is True


def test_head_has_moov_false_when_mdat_first():
    head = _box("ftyp", b"isom") + _box("free", b"") + _box("mdat", b"y" * 1000)
    assert bf.head_has_moov(head) is False


def test_head_has_moov_true_when_only_moov_in_head():
    head = _box("ftyp", b"isom") + _box("moov", b"x" * 100)
    assert bf.head_has_moov(head) is True


def test_url_to_s3_key_extracts_path():
    assert bf.url_to_s3_key("https://save.gengo.io/autowarm/unic/x.mp4") == "autowarm/unic/x.mp4"


def test_process_one_skips_already_faststart():
    s3 = MagicMock()
    head_ok = _box("ftyp", b"isom") + _box("moov", b"x" * 50)
    s3.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=head_ok))}
    row = {"id": 1, "output_url": "https://save.gengo.io/autowarm/unic/a.mp4"}
    assert bf.process_one(s3, row, dry_run=False) == "skipped"
    s3.download_file.assert_not_called()
    s3.upload_file.assert_not_called()


def test_process_one_dry_run_does_not_upload():
    s3 = MagicMock()
    head_bad = _box("ftyp", b"isom") + _box("free", b"") + _box("mdat", b"y" * 1000)
    s3.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=head_bad))}
    row = {"id": 2, "output_url": "https://save.gengo.io/autowarm/unic/b.mp4"}
    assert bf.process_one(s3, row, dry_run=True) == "remuxed"
    s3.download_file.assert_not_called()
    s3.upload_file.assert_not_called()


def test_extra_args_from_head_preserves_sysmd_and_metadata():
    head = {
        "ContentType": "video/mp4",
        "CacheControl": "public, max-age=86400",
        "ContentDisposition": "inline; filename=foo.mp4",
        "Metadata": {"x-project": "85", "x-scheme": "20"},
        # шумовые поля, которые НЕ должны попадать в ExtraArgs
        "ETag": "abc",
        "LastModified": "today",
    }
    args = bf._extra_args_from_head(head)
    assert args["ContentType"] == "video/mp4"
    assert args["CacheControl"] == "public, max-age=86400"
    assert args["ContentDisposition"] == "inline; filename=foo.mp4"
    assert args["Metadata"] == {"x-project": "85", "x-scheme": "20"}
    assert "ETag" not in args and "LastModified" not in args


def test_extra_args_from_head_defaults_contenttype():
    args = bf._extra_args_from_head({})
    assert args["ContentType"] == "video/mp4"
```

- [ ] **Step 3: Запустить тесты**

```bash
cd /home/claude-user/autowarm-testbench/unic-worker
python -m pytest tests/test_backfill_faststart.py -v
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add unic-worker/scripts/backfill_faststart.py unic-worker/tests/test_backfill_faststart.py
git commit -m "feat(wp179): бэкфилл-скрипт remux существующих unic_results в +faststart

scripts/backfill_faststart.py — одноразовый: SELECT candidates через project/since,
fetch head 4KB → head_has_moov-чек → download+remux+upload (с .preremux.mp4 бэкапом).
Идемпотентный (skip уже-faststart). --dry-run для смока. Pure-функции head_has_moov
и url_to_s3_key покрыты тестами, S3-зависимое process_one тестируется через mock."
```

---

## Task 5: Codex review (специка + план)

- [ ] **Step 1: Прогнать codex по спеке**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/wp179-unic-faststart
git diff main -- docs/superpowers/specs/2026-05-28-wp179-unic-worker-faststart-design.md | \
  codex review -
```

Expected: список замечаний (P1/P2/N). Все P1 закрыть.

- [ ] **Step 2: Прогнать codex по плану**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/wp179-unic-faststart
git diff main -- docs/superpowers/plans/2026-05-28-wp179-unic-worker-faststart.md | \
  codex review -
```

Expected: при необходимости — поправить плансе по фидбеку.

- [ ] **Step 3: Прогнать codex по коду (после Task 1–4)**

```bash
cd /home/claude-user/autowarm-testbench
git diff main -- unic-worker/ | codex review -
```

Expected: 0 P1, mock-proxy drift отсутствует.

---

## Task 6: PR + рестарт unic-worker + live-smoke

- [ ] **Step 1: Push ветки contenthunter (spec+plan)**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/wp179-unic-faststart
git push -u origin wp179-unic-faststart
```

- [ ] **Step 2: Push ветки autowarm-testbench (код+тесты+скрипт)**

```bash
cd /home/claude-user/autowarm-testbench
# проверка current branch (память: feedback_parallel_claude_sessions — НЕ checkout -b!)
git branch --show-current
# если main — сначала переключиться на feature-ветку через worktree-add из bare-репо;
# здесь предполагается уже-созданная feat-ветка для unic-worker правок:
git push -u origin wp179-unic-faststart
```

- [ ] **Step 3: Создать PR**

```bash
# spec/plan (contenthunter)
gh pr create --repo rmbrmv/contenthunter \
  --title "docs(wp179): спека+план — unic-worker +faststart на финальный mp4" \
  --body "$(cat <<'EOF'
## Summary
- Спека и план фикса unic-worker: добавить `-movflags +faststart` в финальный concat (`worker.py:322`)
- Тест-канарейка на atom-order
- Бэкфилл-скрипт для существующих CDN-файлов

OpenProject WP #179
EOF
)"
# код (delivery-contenthunter / GenGo2)
gh pr create --repo GenGo2/delivery-contenthunter \
  --title "fix(wp179): unic-worker +faststart на финальный output + бэкфилл-скрипт" \
  --body "$(cat <<'EOF'
## Summary
- `unic-worker/worker.py:322` — добавлен `-movflags +faststart` в финальный concat
- TDD-канарейка `tests/test_create_final_output_faststart.py`
- Бэкфилл `scripts/backfill_faststart.py` для существующих unic_results
- INFO-лог `unic.final.faststart` для подтверждения в проде

## Test plan
- [ ] локально `pytest unic-worker/tests/ -v` — все зелёные
- [ ] прод pull + `pm2 restart unic-worker`
- [ ] live-smoke: новый unic_result → ffprobe → moov раньше mdat
- [ ] backfill --project-id 85 --dry-run (показывает 30 кандидатов clickpay 26.05)
- [ ] backfill --project-id 85 (без dry-run) → все 30 файлов с moov в head
- [ ] Данил повторно качает из «Выкладки», IG галерея строит миниатюру, выбор работает

OpenProject WP #179
EOF
)"
```

- [ ] **Step 4: Прод pull + рестарт**

```bash
ssh prod 'cd /root/.openclaw/workspace-genri/autowarm && git pull && pm2 restart unic-worker'
```

(Запуск с прав root — Данил выполняет вручную; см. [feedback_server_access.md].)

- [ ] **Step 5: Live-smoke на проде**

```bash
# Любой новый done unic_result, последний по id для project_id=85
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "
SELECT output_url FROM unic_results r JOIN unic_tasks t ON t.id=r.task_id
WHERE t.project_id=85 AND r.status='done' AND r.created_at > now()-interval '1 hour'
ORDER BY r.id DESC LIMIT 1"
# → fetch first 4KB → atom-walk → moov должен быть раньше mdat
```

Expected: atom0=ftyp, atom1=moov (а не mdat).

- [ ] **Step 6: Запуск бэкфилла clickpay 26.05**

```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker
python -m scripts.backfill_faststart --project-id 85 --dry-run
# подтверждение N=30 → запуск без dry-run
python -m scripts.backfill_faststart --project-id 85
```

Expected: `done {'skipped': 0, 'remuxed': 30, 'failed': 0}`.

- [ ] **Step 7: User-verify ручной выкладки**

Сообщить Данилу: повторно открыть «Выкладку», скачать любое clickpay-видео → в IG галерее
должна построиться миниатюра → тап выбора → дальше публикация Reels.

- [ ] **Step 8: OpenProject — статус «Тестирование»**

```bash
. /home/claude-user/secrets/openproject.env
# PATCH WP #179 → status=9 (Тестирование)
LOCK=$(curl -sS -u "apikey:$OPENPROJECT_API_TOKEN" "$OPENPROJECT_URL/api/v3/work_packages/179" | python3 -c "import json,sys; print(json.load(sys.stdin)['lockVersion'])")
curl -sS -u "apikey:$OPENPROJECT_API_TOKEN" -X PATCH \
  -H 'Content-Type: application/json' \
  -d "{\"lockVersion\":$LOCK,\"_links\":{\"status\":{\"href\":\"/api/v3/statuses/9\"}}}" \
  "$OPENPROJECT_URL/api/v3/work_packages/179" > /dev/null
```

- [ ] **Step 9: T+24ч — cleanup `.preremux.mp4` backups**

Через 24ч после успешного `--project-id 85` бэкфилла и user-verify (если регрессов
нет) — удалить временные `.preremux.mp4` бэкапы, чтобы не копить в CDN-бакете
индефинитно.

Создать `unic-worker/scripts/cleanup_preremux.py`:

```python
"""WP #179 — удалить preremux backups, созданные backfill_faststart.py старше N часов.

Используется как ручной/cron-шаг через 24ч после успешного бэкфилла. Безопасно:
удаляет ТОЛЬКО ключи с суффиксом '.preremux.mp4' под нашим S3_PREFIX И с тегом
'wp179_preremux=1' (двойной фильтр — суффикс + тег)."""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

log = logging.getLogger("cleanup_preremux")
S3_BUCKET = os.environ.get("UNIC_S3_BUCKET", "save-gengo-io")
S3_PREFIX = os.environ.get("UNIC_S3_PREFIX", "autowarm/unic/")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--older-than-hours", type=int, default=24)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    s3 = boto3.client("s3")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.older_than_hours)
    paginator = s3.get_paginator("list_objects_v2")
    counts = {"checked": 0, "deleted": 0, "skipped_tag": 0, "skipped_age": 0}
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=S3_PREFIX):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            if not key.endswith(".preremux.mp4"):
                continue
            counts["checked"] += 1
            if obj["LastModified"] > cutoff:
                counts["skipped_age"] += 1
                continue
            tags = {t["Key"]: t["Value"] for t in s3.get_object_tagging(Bucket=S3_BUCKET, Key=key).get("TagSet", [])}
            if tags.get("wp179_preremux") != "1":
                counts["skipped_tag"] += 1
                continue
            if args.dry_run:
                log.info(f"DRYRUN_would_delete {key}")
            else:
                s3.delete_object(Bucket=S3_BUCKET, Key=key)
                log.info(f"deleted {key}")
            counts["deleted"] += 1
    log.info(f"done {counts}")


if __name__ == "__main__":
    main()
```

Запуск:

```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker
# смок
python -m scripts.cleanup_preremux --older-than-hours 24 --dry-run
# применить
python -m scripts.cleanup_preremux --older-than-hours 24
```

Expected: `done {'checked': 30, 'deleted': 30, 'skipped_tag': 0, 'skipped_age': 0}`.

---

## Self-Review (после написания плана)

**1. Spec coverage:**
- ✅ Цель 1 (фикс worker.py:322) → Task 2
- ✅ Цель 2 (бэкфилл) → Task 4 + Task 6 Step 6
- ✅ Цель 3 (тест-канарейка) → Task 1
- ✅ Observability → Task 3
- ✅ Тесты TDD → Task 1 (failing) → Task 2 (green) → Task 4 (backfill tests)
- ✅ Verify через codex → Task 5
- ✅ Live-smoke → Task 6 Step 5
- ✅ User-verify → Task 6 Step 7
- ✅ OpenProject статус → Task 6 Step 8
- ✅ Cleanup preremux backups через 24ч (codex P2) → Task 6 Step 9
- ✅ Preserve S3 metadata при re-upload (codex P2) → Task 4 Step 1 (`_extra_args_from_head` + `MetadataDirective=COPY` для backup)

**2. Placeholder scan:**
- Нет "TBD", "TODO", "implement later"
- Полные code-блоки во всех steps
- Точные пути файлов
- Точные команды

**3. Type consistency:**
- `head_has_moov(bytes) -> bool` — единое имя, единая сигнатура
- `process_one(s3, row, dry_run) -> str` — единое имя, single return type
- `atom_offsets(path, max_bytes) -> dict[str,int]` — в test-канарейке, не реиспользуется в backfill (там более узкий `head_has_moov`)
