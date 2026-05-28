# WP #185 — unic-worker финальный transcode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить финальный `-c copy +faststart` в `unic-worker/worker.py:322` (наследие [WP #179](2026-05-27-wp179-unic-worker-faststart.md)) на полноценный transcode в **H.264 Main / Level 4.1 / 1080×1920 / faststart**. Расширить бэкфилл флагом `--transcode`. Доказательство: тест-канарейка проверяет width=1080, height=1920, profile=Main, level=41.

**Architecture:** Точечная замена одной ffmpeg-команды (concat финал). lossy transcode (~+30с на файл) — необходимая стоимость mobile-decoder совместимости (агрессивные схемы уникализации генерируют bitstream вне ожиданий Android HW-decoder). Pad-режим (`scale-to-fit + чёрные полосы`) сохраняет всё содержимое. observability `unic.final.transcode_ok`/`unic.final.transcode_DEVIANT` через ffprobe-постпроверку. Backfill — расширение существующего `scripts/backfill_faststart.py` флагом, tag `wp185_transcoded=1` для idempotent skip.

**Tech Stack:** Python 3.12, ffmpeg/ffprobe (libx264 уже в окружении), boto3 (Beget S3, конфиг уже наследуется от WP #179), psycopg2-binary (БД), pytest.

---

## File Structure

- **Modify:** `unic-worker/worker.py:322` (`create_final_output`) — concat-команда + расширение observability-блока.
- **Modify:** `unic-worker/scripts/backfill_faststart.py` — добавить флаг `--transcode`, `is_already_mobile_safe()`, `transcode_to_mobile_safe()`, путь с `process_one(transcode=True)`, tag `wp185_transcoded=1`.
- **Modify:** `unic-worker/tests/test_create_final_output_faststart.py` — расширить assertions на width/height/profile/level.
- **Modify:** `unic-worker/tests/test_backfill_faststart.py` — добавить тесты `is_already_mobile_safe` (via tag, via params) + `process_one(transcode=True)`.

---

## Task 1: Расширить failing test — output 1080×1920 Main/4.1

**Files:**
- Modify: `unic-worker/tests/test_create_final_output_faststart.py`

- [ ] **Step 1: Расширить test_moov_before_mdat ассертами на params**

В файле `unic-worker/tests/test_create_final_output_faststart.py`, в самом конце функции `test_moov_before_mdat` (после `if "mdat" in atoms: assert atoms["moov"] < atoms["mdat"]`) добавить:

```python
    # WP #185: финальный output должен быть mobile-safe (1080×1920 Main/Level 4.1)
    import subprocess as _sp, json as _json
    probe = _sp.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,profile,level,codec_name",
         "-of", "json", out],
        capture_output=True, text=True, timeout=15, check=True,
    )
    stream = _json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"] == "h264", f"codec: {stream}"
    assert stream["width"] == 1080, f"width: {stream}"
    assert stream["height"] == 1920, f"height: {stream}"
    assert stream["profile"] == "Main", f"profile: {stream}"
    assert stream["level"] == 41, f"level: {stream}"
```

- [ ] **Step 2: Запустить — должен УПАСТЬ**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode/unic-worker
python -m pytest tests/test_create_final_output_faststart.py::test_moov_before_mdat -v
```

Expected: FAIL на одном из ассертов (профиль/level/width/height). Текущий код (с WP #179, до WP #185) делает `-c copy` — параметры сохраняются от seed (320×320 H.264 High Level <something>), а не 1080×1920 Main 4.1.

- [ ] **Step 3: Commit failing test**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode
git add unic-worker/tests/test_create_final_output_faststart.py
git commit -m "test(wp185): расширить canary — output должен быть 1080×1920 Main/Level 4.1

Регрессия из WP #185: faststart недостаточен — мобильный HW-decoder Samsung A17
фейлит на агрессивно-уникализированных файлах (High/Level 5.0/нестандартный размер).
Расширяем canary — после create_final_output ffprobe проверяет width=1080,
height=1920, profile=Main, level=41. Без transcode-фикса в worker.py:322 тест падает."
```

---

## Task 2: Минимальный фикс — transcode в worker.py:322

**Files:**
- Modify: `unic-worker/worker.py:322` (`create_final_output`)

- [ ] **Step 1: Применить правку**

В файле `unic-worker/worker.py`, функция `create_final_output`, строка 322 (после WP #179 — `ffmpeg ... -c copy -movflags +faststart op`):

Было:

```python
    subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',cp,'-c','copy','-movflags','+faststart',op], check=True,capture_output=True,timeout=120)
```

Стало (одной строкой, чтобы соответствовать tight-стилю окружения):

```python
    subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',cp,'-vf','scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,fps=30','-c:v','libx264','-profile:v','main','-level','4.1','-preset','medium','-crf','23','-c:a','aac','-b:a','128k','-movflags','+faststart',op], check=True,capture_output=True,timeout=300)
```

(Timeout увеличен 120→300с — lossy transcode медленнее remux.)

- [ ] **Step 2: Запустить тест — должен ПРОЙТИ**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode/unic-worker
python -m pytest tests/test_create_final_output_faststart.py::test_moov_before_mdat -v
```

Expected: PASS (все ассерты — faststart, width, height, profile, level).

- [ ] **Step 3: Прогнать ВСЕ unic-worker тесты — не должны регрессировать**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode/unic-worker
python -m pytest tests/ -v
```

Expected: 16+ зелёных, 0 регрессий.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode
git add unic-worker/worker.py
git commit -m "fix(wp185): финальный transcode unic-worker в 1080×1920 Main/Level 4.1/faststart

worker.py:322 финальный concat: -c copy → libx264 -profile:v main -level 4.1 +
scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920... + fps=30 +
crf=23 + aac 128k + faststart.

Закрывает фолбэк WP #179 (faststart-only недостаточен): Samsung A17 HW-decoder
фейлит на агрессивно-уникализированных файлах (схема #4 rotate -2.15° speed 1.20
crop 430 vs working схема #30 rotate +1.1 speed 1.07 crop 260). Verified
manually: transcoded test файл воспроизводится плеером + виден в IG-галерее +
выбирается в Reels picker.

Стоимость: ~+30с на файл (lossy encode). Timeout 120→300с."
```

---

## Task 3: Расширить observability — transcode_ok / transcode_DEVIANT

**Files:**
- Modify: `unic-worker/worker.py` `create_final_output` (после concat-transcode, заменить существующий блок WP #179).

- [ ] **Step 1: Заменить observability-блок**

В функции `create_final_output`, существующий блок (после `subprocess.run(...concat...)` и до `for p in [processed_path,fp,sp,cp]: ...`) — заменить целиком:

Было (после WP #179):

```python
    # Observability: ПРОВЕРЯЕМ, что moov реально раньше mdat (а не просто что
    # ffmpeg вернул 0). Это и есть smoke-сигнал по WP #179.
    try:
        with open(op, "rb") as _fh:
            _head = _fh.read(1024 * 1024)
        ...
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

Стало (расширение под WP #185 — добавлена проверка width/height/profile/level через ffprobe):

```python
    # Observability: проверяем faststart + mobile-safe параметры (WP #179 + WP #185).
    try:
        with open(op, "rb") as _fh:
            _head = _fh.read(1024 * 1024)
        _i = 0
        _moov_off = _mdat_off = None
        while _i + 8 <= len(_head):
            _sz = struct.unpack(">I", _head[_i:_i+4])[0]
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
        _faststart_ok = (_moov_off is not None) and (_mdat_off is None or _moov_off < _mdat_off)
        _probe = subprocess.run(
            ['ffprobe','-v','error','-select_streams','v:0',
             '-show_entries','stream=width,height,profile,level',
             '-of','default=nw=1', op],
            capture_output=True, text=True, timeout=15,
        ).stdout
        _params_ok = ('width=1080' in _probe and 'height=1920' in _probe
                      and 'profile=Main' in _probe and 'level=41' in _probe)
        if _faststart_ok and _params_ok:
            logger.info(
                f"unic.final.transcode_ok scheme_id={scheme_id} size={os.path.getsize(op)} "
                f"moov_off={_moov_off} mdat_off={_mdat_off}"
            )
        else:
            logger.warning(
                f"unic.final.transcode_DEVIANT scheme_id={scheme_id} size={os.path.getsize(op)} "
                f"faststart={_faststart_ok} params={_params_ok} "
                f"moov_off={_moov_off} mdat_off={_mdat_off} probe={_probe.replace(chr(10), ' ')}"
            )
    except Exception as _e:
        logger.warning(f"unic.final.transcode_check_failed scheme_id={scheme_id} err={_e}")
```

- [ ] **Step 2: Запустить — тест зелёный, наблюдаем формат лога**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode/unic-worker
python -m pytest tests/test_create_final_output_faststart.py -v -o log_cli=true -o log_cli_level=INFO 2>&1 | grep -E 'transcode_ok|transcode_DEVIANT' | head -3
```

Expected: одна строка `unic.final.transcode_ok scheme_id=0 size=... moov_off=N mdat_off=M`.

- [ ] **Step 3: Прогнать ВСЕ тесты**

```bash
python -m pytest tests/ -v
```

Expected: всё GREEN.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode
git add unic-worker/worker.py
git commit -m "feat(wp185): observability — transcode_ok / transcode_DEVIANT с ffprobe-чеком

Расширяем observability-блок WP #179: помимо faststart (moov<mdat) проверяем
через ffprobe что output реально 1080×1920 Main/Level 4.1. Лог-маркеры:
- unic.final.transcode_ok — оба ОК
- unic.final.transcode_DEVIANT — что-то не соответствует ожиданиям
- unic.final.transcode_check_failed — exception при проверке

Грепабельные сигналы регрессии без необходимости ffprobe-разведки в проде."
```

---

## Task 4: Расширить backfill_faststart.py — флаг `--transcode`

**Files:**
- Modify: `unic-worker/scripts/backfill_faststart.py`
- Modify: `unic-worker/tests/test_backfill_faststart.py`

- [ ] **Step 1: Добавить helpers и логику transcode**

В `unic-worker/scripts/backfill_faststart.py`:

После функции `remux_to_faststart` (~l.128) добавить:

```python
def transcode_to_mobile_safe(src_path: str, dst_path: str) -> None:
    """WP #185: lossy transcode в 1080×1920 Main/Level 4.1 + faststart.

    Mirror of worker.py:322 — тот же набор флагов, чтобы backfill производил
    bit-equivalent (с точностью до encoder-вариаций) output."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", src_path,
         "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,fps=30",
         "-c:v", "libx264", "-profile:v", "main", "-level", "4.1",
         "-preset", "medium", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart",
         dst_path],
        check=True, capture_output=True, timeout=600,
    )


def is_already_mobile_safe(s3, key: str, head_meta: dict | None = None) -> bool:
    """True если файл уже transcoded в 1080×1920 Main/Level 4.1.

    Быстрый путь — тег `wp185_transcoded=1` (если backfill оставил его). Медленный —
    download первых 256KB и ffprobe-проверка params (тяжелее, но точнее)."""
    try:
        tags = {t["Key"]: t["Value"]
                for t in s3.get_object_tagging(Bucket=S3_BUCKET, Key=key).get("TagSet", [])}
        if tags.get("wp185_transcoded") == "1":
            return True
    except Exception:
        pass
    # fallback: тяжёлая проверка через ffprobe (download первых ~256KB)
    try:
        head_bytes = fetch_head(s3, key, n=256 * 1024)
    except Exception:
        return False
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
        tmp.write(head_bytes)
        tmp.flush()
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,profile,level",
                 "-of", "default=nw=1", tmp.name],
                capture_output=True, text=True, timeout=15,
            ).stdout
        except Exception:
            return False
    return ("width=1080" in probe and "height=1920" in probe
            and "profile=Main" in probe and "level=41" in probe)
```

Найти существующую `process_one(s3, row, dry_run)` и изменить сигнатуру + поведение:

Было:

```python
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
        backup_key = key + ".preremux.mp4"
        try:
            s3.copy_object(
                Bucket=S3_BUCKET,
                CopySource={"Bucket": S3_BUCKET, "Key": key},
                Key=backup_key,
                MetadataDirective="COPY",
                Tagging="wp179_preremux=1",
                TaggingDirective="REPLACE",
            )
        except Exception as e:
            log.warning(f"backup_failed id={row['id']} key={key} err={e}")
            return "failed"
        try:
            head_meta = s3.head_object(Bucket=S3_BUCKET, Key=key)
        except Exception as e:
            log.warning(f"head_object_failed id={row['id']} key={key} err={e}")
            return "failed"
        extra_args = _extra_args_from_head(head_meta)
        try:
            _put_object_file(s3, dst, key, extra_args)
        except Exception as e:
            log.warning(f"upload_failed id={row['id']} key={key} err={e} backup_kept={backup_key}")
            return "failed"
        log.info(f"remuxed id={row['id']} key={key} backup={backup_key} preserved={sorted(extra_args)}")
        return "remuxed"
```

Стало:

```python
def process_one(s3, row: dict, dry_run: bool, transcode: bool = False) -> str:
    """Returns one of: 'skipped', 'remuxed', 'transcoded', 'failed'.

    transcode=False — старое поведение (faststart-only remux, WP #179).
    transcode=True — full transcode в 1080×1920 Main/Level 4.1/faststart (WP #185).
    """
    key = url_to_s3_key(row["output_url"])
    if transcode:
        if is_already_mobile_safe(s3, key):
            log.info(f"skip_already_mobile_safe id={row['id']} key={key}")
            return "skipped"
    else:
        try:
            head = fetch_head(s3, key)
        except Exception as e:
            log.warning(f"head_fetch_failed id={row['id']} key={key} err={e}")
            return "failed"
        if head_has_moov(head):
            log.info(f"skip_already_faststart id={row['id']} key={key}")
            return "skipped"
    op_label = "transcode" if transcode else "remux"
    if dry_run:
        log.info(f"DRYRUN_would_{op_label} id={row['id']} key={key}")
        return "transcoded" if transcode else "remuxed"
    backup_suffix = ".pretranscode.mp4" if transcode else ".preremux.mp4"
    backup_tag = "wp185_pretranscode=1" if transcode else "wp179_preremux=1"
    upload_tag = "wp185_transcoded=1" if transcode else None
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "src.mp4")
        dst = os.path.join(td, "dst.mp4")
        s3.download_file(S3_BUCKET, key, src)
        if transcode:
            transcode_to_mobile_safe(src, dst)
        else:
            remux_to_faststart(src, dst)
        backup_key = key + backup_suffix
        try:
            s3.copy_object(
                Bucket=S3_BUCKET,
                CopySource={"Bucket": S3_BUCKET, "Key": key},
                Key=backup_key,
                MetadataDirective="COPY",
                Tagging=backup_tag,
                TaggingDirective="REPLACE",
            )
        except Exception as e:
            log.warning(f"backup_failed id={row['id']} key={key} err={e}")
            return "failed"
        try:
            head_meta = s3.head_object(Bucket=S3_BUCKET, Key=key)
        except Exception as e:
            log.warning(f"head_object_failed id={row['id']} key={key} err={e}")
            return "failed"
        extra_args = _extra_args_from_head(head_meta)
        if upload_tag:
            # boto3 put_object принимает Tagging как 'k1=v1&k2=v2' строку
            extra_args = {**extra_args, "Tagging": upload_tag}
        try:
            _put_object_file(s3, dst, key, extra_args)
        except Exception as e:
            log.warning(f"upload_failed id={row['id']} key={key} err={e} backup_kept={backup_key}")
            return "failed"
        result = "transcoded" if transcode else "remuxed"
        log.info(f"{result} id={row['id']} key={key} backup={backup_key} preserved={sorted(extra_args)}")
        return result
```

В функции `main` добавить флаг `--transcode` и счётчик `transcoded`:

Было (фрагмент main):

```python
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", type=int, default=None)
    ap.add_argument("--since", type=str, default=None, help="YYYY-MM-DD; created_at >= since")
    ap.add_argument(
        "--queue-only", action="store_true",
        help="Только unic_results, прямо сейчас в активной очереди ручной выкладки "
             "(validator_manual_publish_queue: published_at IS NULL AND cancelled_at IS NULL)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        rows = select_candidates(conn, args.project_id, args.since, queue_only=args.queue_only)
    finally:
        conn.close()
    log.info(
        f"candidates={len(rows)} project_id={args.project_id} since={args.since} "
        f"queue_only={args.queue_only} dry_run={args.dry_run}"
    )
    s3 = make_s3_client()
    counts = {"skipped": 0, "remuxed": 0, "failed": 0}
    for row in rows:
        counts[process_one(s3, row, args.dry_run)] += 1
    log.info(f"done {counts}")
    return 0 if counts["failed"] == 0 else 1
```

Стало:

```python
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", type=int, default=None)
    ap.add_argument("--since", type=str, default=None, help="YYYY-MM-DD; created_at >= since")
    ap.add_argument(
        "--queue-only", action="store_true",
        help="Только unic_results, прямо сейчас в активной очереди ручной выкладки "
             "(validator_manual_publish_queue: published_at IS NULL AND cancelled_at IS NULL)",
    )
    ap.add_argument(
        "--transcode", action="store_true",
        help="WP #185: full transcode в 1080×1920 Main/Level 4.1/faststart (mobile-decoder safety). "
             "Без флага — старое WP #179 поведение (remux+faststart only).",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        rows = select_candidates(conn, args.project_id, args.since, queue_only=args.queue_only)
    finally:
        conn.close()
    log.info(
        f"candidates={len(rows)} project_id={args.project_id} since={args.since} "
        f"queue_only={args.queue_only} transcode={args.transcode} dry_run={args.dry_run}"
    )
    s3 = make_s3_client()
    counts = {"skipped": 0, "remuxed": 0, "transcoded": 0, "failed": 0}
    for row in rows:
        counts[process_one(s3, row, args.dry_run, transcode=args.transcode)] += 1
    log.info(f"done {counts}")
    return 0 if counts["failed"] == 0 else 1
```

- [ ] **Step 2: Добавить unit-тесты**

В `unic-worker/tests/test_backfill_faststart.py`, в конец файла:

```python
def test_is_already_mobile_safe_via_tag():
    s3 = MagicMock()
    s3.get_object_tagging.return_value = {"TagSet": [{"Key": "wp185_transcoded", "Value": "1"}]}
    assert bf.is_already_mobile_safe(s3, "autowarm/unic/foo.mp4") is True
    # fast-path: ffprobe не вызывается
    s3.get_object.assert_not_called()


def test_is_already_mobile_safe_when_no_tag_and_get_tagging_raises():
    s3 = MagicMock()
    s3.get_object_tagging.side_effect = Exception("S3 error")
    # get_object для head bytes — но без валидного mp4 ffprobe fail → False
    s3.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"not a video"))}
    assert bf.is_already_mobile_safe(s3, "autowarm/unic/foo.mp4") is False


def test_process_one_transcode_skips_when_tag_present():
    s3 = MagicMock()
    s3.get_object_tagging.return_value = {"TagSet": [{"Key": "wp185_transcoded", "Value": "1"}]}
    row = {"id": 42, "output_url": "https://save.gengo.io/autowarm/unic/x.mp4"}
    assert bf.process_one(s3, row, dry_run=False, transcode=True) == "skipped"
    s3.download_file.assert_not_called()
    s3.put_object.assert_not_called()


def test_process_one_transcode_dry_run_returns_transcoded():
    s3 = MagicMock()
    # no tag, ffprobe will fail on invalid bytes → not mobile_safe → would transcode
    s3.get_object_tagging.return_value = {"TagSet": []}
    s3.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"not a video"))}
    row = {"id": 43, "output_url": "https://save.gengo.io/autowarm/unic/y.mp4"}
    assert bf.process_one(s3, row, dry_run=True, transcode=True) == "transcoded"
    s3.download_file.assert_not_called()
    s3.put_object.assert_not_called()
```

- [ ] **Step 3: Запустить тесты**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode/unic-worker
python -m pytest tests/test_backfill_faststart.py -v
```

Expected: все старые 8 + новые 4 = 12 зелёных.

- [ ] **Step 4: Прогон всех тестов**

```bash
python -m pytest tests/ -v
```

Expected: всё GREEN (~20 тестов).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode
git add unic-worker/scripts/backfill_faststart.py unic-worker/tests/test_backfill_faststart.py
git commit -m "feat(wp185): backfill --transcode + is_already_mobile_safe + transcode_to_mobile_safe

scripts/backfill_faststart.py — новый флаг --transcode переключает с remux+faststart
(WP #179) на full transcode в 1080×1920 Main/Level 4.1/faststart (WP #185).
is_already_mobile_safe — fast-path tag wp185_transcoded=1, fallback ffprobe head 256KB.
process_one(transcode=True) использует .pretranscode.mp4 backup + Tagging
wp185_transcoded=1 на upload. Старое --remux поведение не изменяется (без флага).

Новые тесты: 4 шт — is_already_mobile_safe (via tag, via fail), process_one (skip when tag,
dry-run when no tag)."
```

---

## Task 5: Codex review + PR + merge

- [ ] **Step 1: Codex по коду**

```bash
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode
git diff main -- unic-worker/ | codex review -
```

Expected: 0 P1, P2 закрываем по ходу. Если код будет менять backfill_faststart структурно — внимательно к idempotency.

- [ ] **Step 2: Codex по спеке/плану (опционально, если нужны iтерации)**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/wp185-unic-transcode
git diff main -- docs/superpowers/ | codex review -
```

- [ ] **Step 3: Push веток и PR**

```bash
# spec/plan
cd /home/claude-user/contenthunter/.claude/worktrees/wp185-unic-transcode
git push -u origin wp185-unic-transcode
GH_TOKEN=$(grep GITHUB_TOKEN= /home/claude-user/secrets/github.env | cut -d= -f2) \
  gh pr create --repo rmbrmv/contenthunter --base main --head wp185-unic-transcode \
    --title "docs(wp185): спека+план — unic-worker финальный transcode 1080×1920 Main/4.1" \
    --body "WP #185 (follow-up к WP #179)"

# code
cd /home/claude-user/autowarm-testbench-feat-wp185-unic-transcode
git push -u origin feat/wp185-unic-transcode
GH_TOKEN=$(grep GITHUB_TOKEN_GENGO2= /home/claude-user/secrets/github-gengo2.env | cut -d= -f2) \
  gh pr create --repo GenGo2/delivery-contenthunter --base main --head feat/wp185-unic-transcode \
    --title "fix(wp185): unic-worker финальный transcode 1080×1920 Main/4.1 + backfill --transcode" \
    --body "..."
```

- [ ] **Step 4: Merge оба PR**

```bash
GH_TOKEN=... gh pr merge --repo GenGo2/delivery-contenthunter <N> --merge --delete-branch
GH_TOKEN=... gh pr merge --repo rmbrmv/contenthunter <M> --merge --delete-branch
```

---

## Task 6: Прод pull + restart + live-smoke + backfill + verify

- [ ] **Step 1: Прод pull + restart**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git pull origin main --ff-only
sudo pm2 restart unic-worker
sudo pm2 logs unic-worker --lines 5 --nostream | tail -5
```

- [ ] **Step 2: Live-smoke — следующая live задача**

Дождаться следующего unic_task → проверить ffprobe на новом output:

```bash
# Latest done unic_result после рестарта
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -tAc "
SELECT output_url FROM unic_results 
WHERE status='done' AND created_at > now() - interval '5 minutes'
ORDER BY id DESC LIMIT 1"
# → curl + ffprobe → width=1080 height=1920 profile=Main level=41 + moov в head
```

И поискать в логах:

```bash
sudo pm2 logs unic-worker --lines 100 --nostream | grep 'unic.final.transcode' | tail -5
```

Expected: `unic.final.transcode_ok scheme_id=... size=... moov_off=... mdat_off=...`

- [ ] **Step 3: Backfill priority — active manual queue**

```bash
cd /root/.openclaw/workspace-genri/autowarm/unic-worker
set -a; . /root/.openclaw/workspace-genri/autowarm/.env; set +a
# dry-run сначала
python3 -m scripts.backfill_faststart --queue-only --transcode --dry-run
# боевой (займёт ~1.5ч на ~154 файлов × 30с)
nohup python3 -m scripts.backfill_faststart --queue-only --transcode \
  > /tmp/backfill_transcode_queue.log 2>&1 &
```

Контроль: `tail -f /tmp/backfill_transcode_queue.log | grep -E 'transcoded|failed'`.

- [ ] **Step 4: User-verify**

После завершения queue-backfill: Данил повторно скачивает clickpay/feminista/ambassadori
из «Выкладки» делевери → IG-галерея видит миниатюру + выбирается в Reels picker.

- [ ] **Step 5: Превентивный backfill (фон)**

```bash
nohup python3 -m scripts.backfill_faststart --since 2026-05-21 --transcode \
  > /tmp/backfill_transcode_week.log 2>&1 &
```

~1000 файлов × 30с = ~8-10ч. Запускаем после успешного queue-теста, оставляем на ночь.

- [ ] **Step 6: OpenProject — статус «Тестирование»**

```bash
. /home/claude-user/secrets/openproject.env
LOCK=$(curl -sS -u "apikey:$OPENPROJECT_API_TOKEN" "$OPENPROJECT_URL/api/v3/work_packages/185" | python3 -c "import json,sys; print(json.load(sys.stdin)['lockVersion'])")
curl -sS -u "apikey:$OPENPROJECT_API_TOKEN" -X PATCH \
  -H 'Content-Type: application/json' \
  -d "{\"lockVersion\":$LOCK,\"_links\":{\"status\":{\"href\":\"/api/v3/statuses/9\"}}}" \
  "$OPENPROJECT_URL/api/v3/work_packages/185" > /dev/null
```

---

## Self-Review

**1. Spec coverage:**
- ✅ Цель 1 (transcode в worker.py:322) → Task 2
- ✅ Цель 2 (backfill --transcode) → Task 4
- ✅ Цель 3 (тест-канарейка на params) → Task 1
- ✅ Observability `transcode_ok/DEVIANT` → Task 3
- ✅ TDD: failing test → green → backfill tests → Task 1, 2, 4
- ✅ Verify через codex → Task 5
- ✅ Live-smoke + user-verify → Task 6
- ✅ OpenProject статус → Task 6 Step 6
- ✅ Tagging wp185_transcoded для idempotency → Task 4 (is_already_mobile_safe)
- ✅ Pad-режим для aspect mismatch → Task 2 (scale=...:force_original_aspect_ratio=decrease,pad=...)

**2. Placeholder scan:**
- Нет TBD/TODO/implement-later
- Полные code-блоки во всех steps
- Точные пути файлов и команды

**3. Type consistency:**
- `transcode_to_mobile_safe(src, dst) -> None` — одно имя
- `is_already_mobile_safe(s3, key, head_meta=None) -> bool` — один сигнатура
- `process_one(s3, row, dry_run, transcode=False) -> str` — расширение существующей; обратно совместимое (default False)
- Counts dict в main: `{'skipped', 'remuxed', 'transcoded', 'failed'}` — все ключи учтены в обоих режимах
