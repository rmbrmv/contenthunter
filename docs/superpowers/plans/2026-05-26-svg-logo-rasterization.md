# SVG-логотипы → PNG: гард + сеть воркера — Implementation Plan

> **СТАТУС: ✅ SHIPPED+DEPLOYED 2026-05-26.** Реализовано subagent-driven (impl+спек-ревью+код-ревью+codex по каждой задаче), оба PR смержены и выкачены в прод:
> - Worker (③ сеть + ① скрипт): GenGo2/delivery-contenthunter **#105** → прод autowarm `@1af91ce`; воркер поднят под root-PM2 `unic-worker` (deploy впредь: `sudo pm2 restart unic-worker`), живость подтверждена.
> - Validator (② гард): GenGo2/validator-contenthunter **#22** → прод validator `@deceb19`, рестарт PM2 `validator` id24, старт чистый.
> - codex P1=0, P2 закрыты. Kill-switches: `UNIC_SVG_RASTERIZE_ENABLED`, `BRAND_SVG_RASTERIZE_ENABLED`. WP #151 → Готово.
> - Tasks 6–8 (рантайм воркера + деплой) выполнены по ходу; пред-деплой загадка рантайма разрешена (был unmanaged persistent-процесс, отвалился; теперь PM2).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Не дать SVG-логотипу ронять видеоконвейер уникализации — гард при загрузке (validator) + сеть на стороне воркера (autowarm), плюс закоммитить разовый скрипт ремедиации.

**Architecture:** Общий хелпер растеризации (`cairosvg`, 1024px, RGBA) в каждом из двух репо. Validator `brand.py /upload-image` конвертирует SVG→PNG до выгрузки. Воркер `worker.py` нюхает скачанный логотип/паттерн и конвертирует на лету до FFmpeg. Обе ветки за env-kill-switch.

**Tech Stack:** Python 3, cairosvg 2.8.2, boto3 (Beget S3, `when_required`-чексаммы), FastAPI (validator), asyncpg/psycopg2, pytest.

**Спека:** `docs/superpowers/specs/2026-05-26-svg-logo-rasterization-design.md`

**Статус на момент написания:** компонент ① (скрипт `fix_svg_logos.py`) уже написан и прогнан ad-hoc 2026-05-26 — логотипы Pimble(79) и Бест Клиник(113) починены, бэклог Pimble перезапущен. Этот план оформляет ① как артефакт репо и добавляет ②③.

---

## Репозитории и пути

- **Воркер:** репо `GenGo2/delivery-contenthunter`. Dev-ворктри: `/home/claude-user/wp108-autowarm/unic-worker`. Прод: `/root/.openclaw/workspace-genri/autowarm/unic-worker` (на коммит в проде — авто-пуш-хук). Тесты гонять в dev-ворктри.
- **Validator:** репо validator-contenthunter. Dev: `/home/claude-user/validator-contenthunter` (ветка main). Прод-бэкенд под PM2 `validator` (id=24).

> ⚠️ Перед стартом: `git fetch` в обоих ворктри и работа в отдельной ветке (параллельные сессии + авто-пуш-хук в проде). Не оставлять half-broken state.

---

## File Structure

**Воркер (`unic-worker/`):**
- Create `svg_raster.py` — общий хелпер: `looks_like_svg(head)`, `rasterize_svg_to_png(bytes,width)`, `ensure_png_raster(path)`.
- Modify `worker.py` — компонент ③: после `download_file` логотипа/паттерна вызвать `ensure_png_raster` (за `UNIC_SVG_RASTERIZE_ENABLED`).
- Modify `requirements.txt` — добавить `cairosvg`.
- Modify `scripts/fix_svg_logos.py` — импортировать хелпер вместо локальных копий (DRY).
- Create `tests/test_svg_raster.py` — юнит на хелпер.

**Validator (`backend/`):**
- Create `src/services/svg_raster.py` — зеркальный хелпер (`looks_like_svg`, `rasterize_svg_to_png`).
- Modify `src/routers/brand.py` — компонент ②: в `upload_brand_image` SVG→PNG (за `BRAND_SVG_RASTERIZE_ENABLED`).
- Modify зависимости (`requirements.txt`/`pyproject.toml`) — `cairosvg`.
- Create `tests/test_brand_svg_guard.py` — тест эндпоинта.

---

## Task 1: Общий хелпер растеризации (воркер)

**Files:**
- Create: `/home/claude-user/wp108-autowarm/unic-worker/svg_raster.py`
- Test: `/home/claude-user/wp108-autowarm/unic-worker/tests/test_svg_raster.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_svg_raster.py
import os, tempfile
from svg_raster import looks_like_svg, rasterize_svg_to_png, ensure_png_raster

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
PNG_SIG = b"\x89PNG\r\n\x1a\n"

def test_looks_like_svg_true():
    assert looks_like_svg(SVG[:64])
    assert looks_like_svg(b'   <?xml version="1.0"?><svg></svg>'[:64])
    assert looks_like_svg(b'\xef\xbb\xbf<svg>'[:64])  # BOM

def test_looks_like_svg_false():
    assert not looks_like_svg(PNG_SIG)
    assert not looks_like_svg(b'\xff\xd8\xff\xe0JFIF')  # jpeg

def test_rasterize_returns_png():
    out = rasterize_svg_to_png(SVG, width=64)
    assert out.startswith(PNG_SIG)

def test_ensure_png_raster_converts_svg_file():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(SVG); path = f.name
    changed = ensure_png_raster(path)
    assert changed is True
    with open(path, "rb") as fh:
        assert fh.read(8) == PNG_SIG
    os.unlink(path)

def test_ensure_png_raster_leaves_png_untouched():
    payload = PNG_SIG + b"rest-of-file"
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(payload); path = f.name
    changed = ensure_png_raster(path)
    assert changed is False
    with open(path, "rb") as fh:
        assert fh.read() == payload
    os.unlink(path)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/wp108-autowarm/unic-worker && python3 -m pytest tests/test_svg_raster.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'svg_raster'`

- [ ] **Step 3: Реализовать хелпер**

```python
# svg_raster.py
"""Растеризация SVG→PNG (cairosvg) + детекция. Общий код для воркера и скрипта ремедиации."""
import cairosvg

RASTER_WIDTH = 1024
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def looks_like_svg(head: bytes) -> bool:
    s = head.lstrip(b"\xef\xbb\xbf").lstrip()
    return s.startswith(b"<svg") or s.startswith(b"<?xml")


def rasterize_svg_to_png(svg_bytes: bytes, width: int = RASTER_WIDTH) -> bytes:
    png = cairosvg.svg2png(bytestring=svg_bytes, output_width=width)
    if not png.startswith(PNG_SIG):
        raise ValueError("cairosvg вернул не-PNG")
    return png


def ensure_png_raster(path: str) -> bool:
    """Если файл по пути — SVG, перезаписать его растром PNG. Возвращает True если конвертировал."""
    with open(path, "rb") as f:
        data = f.read()
    if not looks_like_svg(data[:64]):
        return False
    png = rasterize_svg_to_png(data)
    with open(path, "wb") as f:
        f.write(png)
    return True
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python3 -m pytest tests/test_svg_raster.py -v`
Expected: PASS (5 тестов)

- [ ] **Step 5: Коммит**

```bash
# из /home/claude-user/wp108-autowarm/unic-worker (куда вёл cd в Step 4)
git add svg_raster.py tests/test_svg_raster.py
git commit -m "feat(unic-worker): svg_raster helper (looks_like_svg/rasterize/ensure_png_raster) + tests"
```

---

## Task 2: Оформить скрипт ремедиации ① + cairosvg в requirements

**Files:**
- Modify: `/home/claude-user/wp108-autowarm/unic-worker/scripts/fix_svg_logos.py` (уже существует, прогнан ad-hoc)
- Modify: `/home/claude-user/wp108-autowarm/unic-worker/requirements.txt`

- [ ] **Step 1: Перевести скрипт на общий хелпер (DRY)**

В `scripts/fix_svg_logos.py` удалить локальные `looks_like_svg`/`rasterize_svg_to_png` и импортировать из пакета воркера:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # unic-worker/ в path
from svg_raster import looks_like_svg, rasterize_svg_to_png
```

Остальная логика (find_targets/main/s3_client с `when_required`-чексаммами + `region_name='ru1'`, upload через временный файл `upload_file`) — без изменений.

- [ ] **Step 2: Проверить dry-run (smoke, без изменений в БД)**

```bash
cd /home/claude-user/wp108-autowarm/unic-worker
eval "$(node -e "const c=require('./ecosystem.config.js').apps[0].env; for(const k of ['DATABASE_URL','S3_ENDPOINT','S3_ACCESS_KEY','S3_SECRET_KEY','S3_BUCKET']) console.log('export '+k+'='+JSON.stringify(c[k]))")"
python3 scripts/fix_svg_logos.py --dry-run
```
Expected: «SVG-логотипов не найдено» (уже починены 26.05) ИЛИ корректный список, если появились новые. Идемпотентность подтверждена.

- [ ] **Step 3: Добавить cairosvg в requirements**

`requirements.txt` — добавить строку:
```
cairosvg
```

- [ ] **Step 4: Коммит**

```bash
# из /home/claude-user/wp108-autowarm/unic-worker
git add scripts/fix_svg_logos.py requirements.txt
git commit -m "feat(unic-worker): fix_svg_logos remediation script (DRY via svg_raster) + cairosvg dep"
```

---

## Task 3: Компонент ③ — сеть воркера (SVG до FFmpeg)

**Files:**
- Modify: `/home/claude-user/wp108-autowarm/unic-worker/worker.py` (блок скачивания ассетов, ~стр. 405–415)
- Test: `/home/claude-user/wp108-autowarm/unic-worker/tests/test_worker_svg_net.py`

- [ ] **Step 1: Написать падающий тест на нормализацию ассета**

```python
# tests/test_worker_svg_net.py — тестируем функцию-обёртку normalize_asset (см. Step 3)
import os, tempfile
from worker import normalize_asset

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8"/></svg>'
PNG_SIG = b"\x89PNG\r\n\x1a\n"

def _tmp(data):
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False); f.write(data); f.close(); return f.name

def test_normalize_converts_svg(monkeypatch):
    monkeypatch.setenv("UNIC_SVG_RASTERIZE_ENABLED", "1")
    p = _tmp(SVG)
    normalize_asset(p)
    assert open(p, "rb").read(8) == PNG_SIG
    os.unlink(p)

def test_normalize_disabled_leaves_svg(monkeypatch):
    monkeypatch.setenv("UNIC_SVG_RASTERIZE_ENABLED", "0")
    p = _tmp(SVG)
    normalize_asset(p)
    assert open(p, "rb").read(4) == b"<svg"
    os.unlink(p)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 -m pytest tests/test_worker_svg_net.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_asset' from 'worker'`

- [ ] **Step 3: Добавить `normalize_asset` в worker.py + вызвать после скачивания**

Рядом с импортами worker.py:
```python
from svg_raster import ensure_png_raster
```

Добавить функцию (рядом с `download_file`):
```python
def normalize_asset(path):
    """Сеть-защита: если скачанный ассет — SVG, растеризовать до FFmpeg.
    Kill-switch UNIC_SVG_RASTERIZE_ENABLED=0 отключает (вернёт старое поведение)."""
    if os.environ.get('UNIC_SVG_RASTERIZE_ENABLED', '1') != '1':
        return
    try:
        if ensure_png_raster(path):
            logger.info(f'[svg-net] растеризовал SVG-ассет в PNG: {path}')
    except Exception as e:
        logger.warning(f'[svg-net] не смог конвертировать {path}: {e}')
```

В блоке скачивания (текущие строки ~408–415) добавить вызов `normalize_asset` сразу после каждого `download_file` логотипа и паттерна:
```python
                if content['logo']:
                    p=os.path.join(TEMP_DIR,f'{base_name}_s{sid}_a{attempt}_logo.png')
                    await asyncio.to_thread(download_file, content['logo']['file_path'], p)
                    await asyncio.to_thread(normalize_asset, p)
                    files['logo']=p; asset_paths.append(p)
                if content['pattern']:
                    p=os.path.join(TEMP_DIR,f'{base_name}_s{sid}_a{attempt}_pat.png')
                    await asyncio.to_thread(download_file, content['pattern']['file_path'], p)
                    await asyncio.to_thread(normalize_asset, p)
                    files['pattern']=p; asset_paths.append(p)
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python3 -m pytest tests/test_worker_svg_net.py -v`
Expected: PASS (2 теста)

- [ ] **Step 5: Коммит**

```bash
# из /home/claude-user/wp108-autowarm/unic-worker
git add worker.py tests/test_worker_svg_net.py
git commit -m "feat(unic-worker): SVG safety-net before FFmpeg + UNIC_SVG_RASTERIZE_ENABLED kill-switch (WP #151)"
```

---

## Task 4: Хелпер растеризации (validator)

**Files:**
- Create: `/home/claude-user/validator-contenthunter/backend/src/services/svg_raster.py`
- Test: `/home/claude-user/validator-contenthunter/backend/tests/test_svg_raster.py`

- [ ] **Step 1: Написать падающий тест**

```python
# backend/tests/test_svg_raster.py
from src.services.svg_raster import looks_like_svg, rasterize_svg_to_png

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
PNG_SIG = b"\x89PNG\r\n\x1a\n"

def test_looks_like_svg():
    assert looks_like_svg(SVG[:64])
    assert not looks_like_svg(PNG_SIG)

def test_rasterize():
    assert rasterize_svg_to_png(SVG, width=64).startswith(PNG_SIG)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python3 -m pytest tests/test_svg_raster.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Реализовать (зеркало воркерного хелпера, без ensure_png_raster — он там не нужен)**

```python
# backend/src/services/svg_raster.py
"""Растеризация SVG→PNG для гарда загрузки логотипа."""
import cairosvg

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def looks_like_svg(head: bytes) -> bool:
    s = head.lstrip(b"\xef\xbb\xbf").lstrip()
    return s.startswith(b"<svg") or s.startswith(b"<?xml")


def rasterize_svg_to_png(svg_bytes: bytes, width: int = 1024) -> bytes:
    png = cairosvg.svg2png(bytestring=svg_bytes, output_width=width)
    if not png.startswith(PNG_SIG):
        raise ValueError("cairosvg вернул не-PNG")
    return png
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python3 -m pytest tests/test_svg_raster.py -v`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
# из /home/claude-user/validator-contenthunter/backend (куда вёл cd в Step 2/4)
git add src/services/svg_raster.py tests/test_svg_raster.py
git commit -m "feat(validator): svg_raster service helper + tests"
```

---

## Task 5: Компонент ② — гард при загрузке логотипа

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/backend/src/routers/brand.py` (`upload_brand_image`, ~стр. 133–161)
- Modify: `/home/claude-user/validator-contenthunter/backend/requirements.txt` (или pyproject) — `cairosvg`
- Test: `/home/claude-user/validator-contenthunter/backend/tests/test_brand_svg_guard.py`

- [ ] **Step 1: Написать падающий тест (с переопределением зависимостей и моком S3)**

```python
# backend/tests/test_brand_svg_guard.py
import io
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.deps import get_db, get_current_user  # пути зависимостей — сверить с реальными импортами brand.py

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
PNG_SIG = b"\x89PNG\r\n\x1a\n"

@pytest.fixture
def client(monkeypatch):
    captured = {}
    async def fake_upload(data, key, mime, context=""):
        captured["data"], captured["key"], captured["mime"] = data, key, mime
    monkeypatch.setattr("src.routers.brand._upload_bytes_to_s3", fake_upload)
    monkeypatch.setattr("src.routers.brand.get_public_url", lambda key: f"https://save.gengo.io/{key}")
    monkeypatch.setenv("BRAND_SVG_RASTERIZE_ENABLED", "1")
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"id": 1})()
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), captured
    app.dependency_overrides.clear()

@pytest.mark.anyio
async def test_svg_upload_rasterized_to_png(client):
    ac, captured = client
    r = await ac.post("/api/brand/upload-image",
                      files={"file": ("logo.svg", io.BytesIO(SVG), "image/svg+xml")},
                      data={"field": "logo"}, headers={"X-Project-Id": "79"})
    assert r.status_code == 200
    assert r.json()["url"].endswith(".png")
    assert captured["mime"] == "image/png"
    assert captured["data"][:8] == PNG_SIG
    assert captured["key"].endswith(".png")
```

> Примечание для исполнителя: точные пути импортов зависимостей (`get_db`, `get_current_user`, `_resolve_brand_project_id`) и URL-префикс роутера сверить в `brand.py`/`main.py` перед запуском. Учесть autouse `engine.dispose` fixture из `conftest.py` (см. [[feedback_validator_test_engine_dispose]]) — если тест задевает живой engine.

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python3 -m pytest tests/test_brand_svg_guard.py -v`
Expected: FAIL — ответ оканчивается на `.svg`, mime `image/svg+xml` (гарда ещё нет)

- [ ] **Step 3: Добавить гард в upload_brand_image**

В начало `brand.py`:
```python
import os
from ..services.svg_raster import looks_like_svg, rasterize_svg_to_png
```

В `upload_brand_image` после `data = await file.read()` и проверки размера, перед вычислением `ext`/`key`:
```python
    # Гард: SVG-логотип роняет FFmpeg в уникализации (Invalid PNG signature).
    # Конвертируем в PNG до выгрузки. Kill-switch BRAND_SVG_RASTERIZE_ENABLED=0.
    is_svg = mime == "image/svg+xml" or looks_like_svg(data[:64])
    if is_svg and os.environ.get("BRAND_SVG_RASTERIZE_ENABLED", "1") == "1":
        try:
            data = rasterize_svg_to_png(data)
            mime = "image/png"
            log.info("[svg-guard] pid=%s field=%s rasterized svg->png bytes=%s", pid, field, len(data))
        except Exception as e:
            raise HTTPException(status_code=400, detail="Не удалось обработать SVG; загрузите PNG/JPEG") from e
```

И заменить вычисление `ext` так, чтобы для сконвертированного SVG было `png`:
```python
    ext = "png" if mime == "image/png" else (file.filename or "image.jpg").rsplit(".", 1)[-1].lower()
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python3 -m pytest tests/test_brand_svg_guard.py -v`
Expected: PASS

- [ ] **Step 5: Добавить cairosvg в зависимости**

`backend/requirements.txt` (или раздел deps в pyproject) — добавить `cairosvg`.

- [ ] **Step 6: Коммит**

```bash
# из /home/claude-user/validator-contenthunter/backend
git add src/routers/brand.py requirements.txt tests/test_brand_svg_guard.py
git commit -m "feat(validator): rasterize SVG brand logo on upload + BRAND_SVG_RASTERIZE_ENABLED kill-switch (WP #151)"
```

---

## Task 6: Найти рантайм воркера и процедуру рестарта (ПРЕД-ДЕПЛОЙ, блокер для ③)

**Контекст:** при перезапуске бэклога 26.05 воркер мгновенно забирал задачи из `pending`, но его НЕ видно ни в root-PM2, ни в claude-user-PM2, ни в cron/systemd, ни как процесс `worker.py`. Деплой ③ (правка `worker.py`) требует рестарта — сначала нужно понять, чем воркер запущен.

- [ ] **Step 1: Локализовать процесс-консьюмер**

```bash
# найти процесс, держащий соединение к unic_tasks / запускающий ffmpeg
sudo ps -ef | grep -iE "worker.py|unic|ffmpeg" | grep -v grep
ss -tnp 2>/dev/null | grep 5432 | head        # кто коннектится к postgres
ls -la /root/.openclaw/workspace-genri/autowarm/unic-worker/   # есть ли nohup.out/лог
sudo journalctl -n0 2>/dev/null; pm2 logs --nostream 2>/dev/null | head
```
Цель: определить — отдельный процесс/screen/tmux, другой PM2-home, или запуск на другой машине (БД общая).

- [ ] **Step 2: Зафиксировать процедуру рестарта**

Записать найденное в спеку §6 (как запускается и как рестартить). Если воркер на другой машине — деплой ③ синхронизировать туда; если локальный без супервайзера — оформить как PM2-app из `ecosystem.config.js` (`pm2 start ecosystem.config.js && pm2 save`). Без этого шага ③ не деплоить.

---

## Task 7: Деплой воркера (① скрипт + ③ сеть) + smoke

**Files:** прод `/root/.openclaw/workspace-genri/autowarm/unic-worker`

- [ ] **Step 1: Смёрджить ветку воркера в прод-репо**

Влить изменения (Tasks 1–3) в прод-чекаут autowarm (через merge/cherry-pick по принятому в проекте процессу). НЕ force-push. Авто-пуш-хук отправит в GenGo2/delivery-contenthunter.

- [ ] **Step 2: Установить cairosvg в окружении воркера**

```bash
# в том же python, которым запускается worker.py (см. Task 6)
python3 -c "import cairosvg; print(cairosvg.__version__)"   # уже 2.8.2 в системном python3
```
Если воркер использует venv — `pip install cairosvg` в него.

- [ ] **Step 3: Рестарт воркера по процедуре из Task 6**

- [ ] **Step 4: Smoke — внешний SVG-логотип конвертируется на лету**

```bash
# временно вернуть тестовому проекту SVG-логотип в БД, сбросить 1 его задачу в pending,
# убедиться что задача проходит (schemes_done растёт, err=0), затем вернуть PNG.
# ЛИБО прогнать через проект 113 (внешний SVG) когда у него появится контент.
```
Expected: задача `done`, `[svg-net]`-лог в выводе воркера.

---

## Task 8: Деплой validator (② гард) + smoke

- [ ] **Step 1: Влить ветку validator (Tasks 4–5) в main, собрать бэкенд**

(Фронт не затрагивается — postbuild-автодеплой не нужен.)

- [ ] **Step 2: Установить cairosvg в окружении бэкенда**

```bash
python3 -c "import cairosvg; print(cairosvg.__version__)"
```

- [ ] **Step 3: Рестарт PM2 validator**

```bash
sudo pm2 restart validator && sudo pm2 logs validator --lines 30 --nostream
```
Проверить отсутствие порт-конфликта с systemd `validator-backend.service` (должен быть disabled — см. [[feedback_systemd_pm2_validator_port_conflict]]).

- [ ] **Step 4: Smoke — загрузка SVG через UI/API даёт PNG**

```bash
# через curl с тестовым токеном: POST /api/brand/upload-image c .svg → url оканчивается на .png
```
Expected: `url` оканчивается на `.png`, объект — валидный PNG.

---

## Task 9: Финальная верификация + трекер

- [ ] **Step 1: Подтвердить отсутствие SVG-логотипов и отсутствие SVG-фейлов**

```sql
-- активных SVG-логотипов нет
SELECT b.project_id FROM validator_brand_profiles b JOIN validator_projects p ON p.id=b.project_id
WHERE b.logo_url ILIKE '%.svg' AND p.active;
-- новых unic_tasks с Invalid PNG signature нет (после деплоя)
SELECT count(*) FROM unic_tasks WHERE task_type='unic' AND current_status='error'
  AND updated_at > now() - interval '1 day' AND error_message ILIKE '%Invalid PNG signature%';
```
Expected: обе пустые/ноль.

- [ ] **Step 2: Прогнать все новые тесты обоих репо зелёными**

```bash
cd /home/claude-user/wp108-autowarm/unic-worker && python3 -m pytest tests/test_svg_raster.py tests/test_worker_svg_net.py -v
cd /home/claude-user/validator-contenthunter/backend && python3 -m pytest tests/test_svg_raster.py tests/test_brand_svg_guard.py -v
```

- [ ] **Step 3: codex review итогового диффа обоих репо** ([[feedback_codex_review_specs]])

```bash
git diff origin/main...HEAD | ~/.local/bin/codex review -
```
Применить P1/P2, дожать до 0 P1.

- [ ] **Step 4: Обновить #151** — статус «Готово» с комментарием (что сделано: гард при загрузке + сеть воркера, kill-switch'и, тесты; деплой). Отметить в #149 завершение по логотипам.

---

## Self-Review (выполнено при написании)

- **Покрытие спеки:** ① Task 2/7 (скрипт+деплой), ② Task 4/5/8 (хелпер+гард+деплой), ③ Task 1/3/7 (хелпер+сеть+деплой), kill-switch'и (Task 3/5), тесты (Task 1/3/4/5), деплой PM2 (Task 7/8), верификация (Task 9). Пред-деплой неизвестность рантайма воркера вынесена в Task 6.
- **Плейсхолдеры:** код приведён во всех code-шагах; два явных «сверить с реальными импортами» помечены как действия исполнителя (пути зависимостей validator), не как пропуски логики.
- **Консистентность типов:** `looks_like_svg`/`rasterize_svg_to_png`/`ensure_png_raster` — единые сигнатуры в Task 1, переиспользуются в 2/3; `normalize_asset` определена в Task 3 и там же тестируется; `PNG_SIG` единая константа.
