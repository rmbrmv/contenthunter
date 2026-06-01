# WP#136 — Кроп лого 1:1 + ML-удаление фона: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Клиент в распаковке кропает логотип в квадрат 1:1 с прозрачным фоном (опц. ML-удаление фона), на выходе всегда PNG 1024×1024 RGBA, который без искажений идёт в уникализацию.

**Architecture:** Вариант A — кроп на фронте (Vue/Canvas экспортирует финальный PNG), удаление фона через синхронный прокси `POST /api/brand/remove-bg` на валидатор-бэкенде, который форвардит на rembg-микросервис на сервере уникализации `91.98.180.103`. Сохранение — существующим `/api/brand/upload-image`.

**Tech Stack:** Vue 3 + TS + Canvas API + vitest (frontend); FastAPI + httpx + pytest (backend, `validator-contenthunter`); новый FastAPI-сервис + rembg/onnxruntime/Pillow (микросервис на 91.98.180.103).

**Спека:** `docs/superpowers/specs/2026-06-01-wp136-client-logo-crop-design.md`

---

## Репозитории и ветки

Три места изменений (создать ветку `wp136-client-logo-crop` в каждом code-репо):

| # | Что | Репо / путь | Деплой |
|---|-----|-------------|--------|
| A | docs (этот план + спека) | `/home/claude-user/contenthunter` (ветка уже создана) | — |
| B | frontend + backend + код микросервиса | `/home/claude-user/validator-contenthunter` | валидатор: pull на 72.56.107.157 |
| C | сам микросервис (тот же код из B, папка `logo-bg-service/`) | rsync на `91.98.180.103:/root/logo-bg-service` | PM2 на 91.98.180.103 |

> Код микросервиса живёт в репо `validator-contenthunter` (папка `logo-bg-service/`) для целостности фичи и единого код-ревью; деплоится rsync-ом на сервер уникализации.

## File Structure

**Микросервис (новое, `validator-contenthunter/logo-bg-service/`):**
- `app.py` — FastAPI: `GET /health`, `POST /remove-bg` (token-auth, rembg).
- `requirements.txt` — `fastapi`, `uvicorn[standard]`, `python-multipart`, `rembg`, `onnxruntime`, `pillow`.
- `ecosystem.config.js` — PM2-юнит (1 воркер uvicorn, порт 8077).
- `tests/test_app.py` — pytest: health, auth-reject, remove-bg добавляет alpha.
- `README.md` — деплой + firewall.

**Backend (`validator-contenthunter/backend/`):**
- Modify `src/config.py` — поля `logo_bg_removal_*`.
- Modify `src/routers/brand.py` — эндпоинт `POST /api/brand/remove-bg`.
- Create `tests/test_brand_remove_bg.py` — pytest для прокси.

**Frontend (`validator-contenthunter/frontend/`):**
- Create `src/utils/logoSquareDetect.ts` — чистая функция detect-skip.
- Create `src/utils/__tests__/logoSquareDetect.spec.ts` — vitest.
- Create `src/components/LogoCropModal.vue` — окно кропа.
- Modify `src/pages/client/BrandPage.vue` — интеграция модалки в `uploadFile`.

---

## Task 1: Микросервис — каркас FastAPI + `/health`

**Files:**
- Create: `validator-contenthunter/logo-bg-service/app.py`
- Create: `validator-contenthunter/logo-bg-service/requirements.txt`
- Test: `validator-contenthunter/logo-bg-service/tests/test_app.py`

- [ ] **Step 1: requirements.txt**

```
fastapi==0.115.5
uvicorn[standard]==0.32.1
python-multipart==0.0.12
pillow==10.4.0
rembg==2.0.59
onnxruntime==1.19.2
```

- [ ] **Step 2: Write the failing test (health)**

`tests/test_app.py`:
```python
import os
os.environ.setdefault("LOGO_BG_REMOVAL_TOKEN", "test-token")

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

- [ ] **Step 3: Run test — verify it fails**

Run: `cd validator-contenthunter/logo-bg-service && python -m pytest tests/test_app.py::test_health_ok -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 4: Minimal app.py (health only)**

`app.py`:
```python
"""Logo background-removal microservice (rembg) — deploy on uniqueness host 91.98.180.103.

Synchronous HTTP, token-protected, firewalled to the validator backend IP only.
Separate from the unic_tasks queue — this path serves live crop-modal preview.
"""
import os

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Response

app = FastAPI(title="logo-bg-service")

TOKEN = os.environ.get("LOGO_BG_REMOVAL_TOKEN", "")


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run test — verify it passes**

Run: `cd validator-contenthunter/logo-bg-service && python -m pytest tests/test_app.py::test_health_ok -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd validator-contenthunter
git add logo-bg-service/app.py logo-bg-service/requirements.txt logo-bg-service/tests/test_app.py
git commit -m "feat(wp136): logo-bg-service skeleton + /health"
```

---

## Task 2: Микросервис — `POST /remove-bg` с token-auth и rembg

**Files:**
- Modify: `validator-contenthunter/logo-bg-service/app.py`
- Test: `validator-contenthunter/logo-bg-service/tests/test_app.py`

- [ ] **Step 1: Write failing tests (auth + alpha)**

Добавить в `tests/test_app.py`:
```python
import io
from PIL import Image


def _opaque_png(color=(10, 200, 30)) -> bytes:
    """64×64 полностью непрозрачный квадрат на ровном фоне."""
    img = Image.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_remove_bg_rejects_without_token():
    r = client.post("/remove-bg", files={"file": ("l.png", _opaque_png(), "image/png")})
    assert r.status_code == 401


def test_remove_bg_adds_alpha():
    r = client.post(
        "/remove-bg",
        files={"file": ("l.png", _opaque_png(), "image/png")},
        headers={"X-Internal-Token": "test-token"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    out = Image.open(io.BytesIO(r.content))
    assert out.mode == "RGBA"
    # хотя бы один полностью прозрачный пиксель появился (фон срезан)
    alphas = out.getchannel("A").getdata()
    assert min(alphas) == 0
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `cd validator-contenthunter/logo-bg-service && python -m pytest tests/test_app.py -v -k remove_bg`
Expected: FAIL — 404 (эндпоинта нет).

- [ ] **Step 3: Implement /remove-bg**

Добавить в `app.py`:
```python
import io
from functools import lru_cache

from PIL import Image


@lru_cache(maxsize=1)
def _session():
    # Ленивая инициализация модели: первый запрос прогревает (~170MB u2net).
    from rembg import new_session
    return new_session("u2net")


def _check_token(x_internal_token: str | None):
    if not TOKEN or x_internal_token != TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/remove-bg")
async def remove_bg(
    file: UploadFile = File(...),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _check_token(x_internal_token)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    from rembg import remove
    try:
        src = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as e:
        raise HTTPException(status_code=400, detail="bad image") from e
    out = remove(src, session=_session())  # PIL.Image -> PIL.Image (RGBA)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `cd validator-contenthunter/logo-bg-service && python -m pytest tests/test_app.py -v`
Expected: PASS (3 теста). Первый прогон скачивает модель u2net — может занять ~1 мин.

- [ ] **Step 5: Commit**

```bash
cd validator-contenthunter
git add logo-bg-service/app.py logo-bg-service/tests/test_app.py
git commit -m "feat(wp136): logo-bg-service /remove-bg (rembg u2net + token auth)"
```

---

## Task 3: Микросервис — PM2-юнит + README деплоя (ops, без теста)

**Files:**
- Create: `validator-contenthunter/logo-bg-service/ecosystem.config.js`
- Create: `validator-contenthunter/logo-bg-service/README.md`

- [ ] **Step 1: ecosystem.config.js**

```javascript
module.exports = {
  apps: [{
    name: 'logo-bg-service',
    cwd: '/root/logo-bg-service',
    script: 'uvicorn',
    args: 'app:app --host 0.0.0.0 --port 8077 --workers 1',
    interpreter: 'python3',
    env: {
      LOGO_BG_REMOVAL_TOKEN: 'REPLACE_WITH_SHARED_SECRET',
    },
    max_memory_restart: '2G',
  }],
};
```

- [ ] **Step 2: README.md (деплой + firewall)**

```markdown
# logo-bg-service

rembg-микросервис удаления фона логотипа. Деплой на сервер уникализации 91.98.180.103,
рядом с unic-worker. Синхронный путь (не очередь unic_tasks), обслуживает живой превью
в окне кропа лого.

## Деплой
1. rsync кода на хост:
   rsync -az --exclude tests --exclude __pycache__ ./ root@91.98.180.103:/root/logo-bg-service/
2. На хосте:
   cd /root/logo-bg-service && python3 -m pip install -r requirements.txt
3. Прогрев модели (скачивает ~170MB u2net в ~/.u2net):
   python3 -c "from rembg import new_session; new_session('u2net')"
4. Задать общий секрет в ecosystem.config.js (LOGO_BG_REMOVAL_TOKEN) — он же в backend .env.
5. Запуск: pm2 start ecosystem.config.js && pm2 save

## Firewall (ufw) — входящие на 8077 ТОLьКО с валидатора:
   ufw allow from 72.56.107.157 to any port 8077 proto tcp
   ufw deny 8077
Наружу домен не вешаем.

## Проверка
   curl -s http://91.98.180.103:8077/health     # с валидатора
```

- [ ] **Step 3: Commit**

```bash
cd validator-contenthunter
git add logo-bg-service/ecosystem.config.js logo-bg-service/README.md
git commit -m "ops(wp136): logo-bg-service PM2 unit + deploy/firewall README"
```

---

## Task 4: Backend — конфиг для прокси

**Files:**
- Modify: `validator-contenthunter/backend/src/config.py`

- [ ] **Step 1: Добавить поля в Settings**

В `src/config.py` после блока `# Anthropic` добавить:
```python
    # Logo background-removal microservice (WP#136, host 91.98.180.103)
    logo_bg_removal_enabled: bool = False          # kill-switch (default off до прогрева сервиса)
    logo_bg_removal_url: str = "http://91.98.180.103:8077"
    logo_bg_removal_token: str = ""
    logo_bg_removal_timeout_s: float = 15.0
```

- [ ] **Step 2: Проверка импорта (без отдельного теста — покрывается Task 5)**

Run: `cd validator-contenthunter/backend && python -c "from src.config import settings; print(settings.logo_bg_removal_enabled, settings.logo_bg_removal_url)"`
Expected: `False http://91.98.180.103:8077`

- [ ] **Step 3: Commit**

```bash
cd validator-contenthunter
git add backend/src/config.py
git commit -m "feat(wp136): backend config for logo bg-removal proxy"
```

---

## Task 5: Backend — прокси `POST /api/brand/remove-bg`

**Files:**
- Modify: `validator-contenthunter/backend/src/routers/brand.py`
- Test: `validator-contenthunter/backend/tests/test_brand_remove_bg.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/test_brand_remove_bg.py`:
```python
"""Прокси POST /api/brand/remove-bg → rembg-микросервис. БД/S3 не нужны — всё мокается."""
import io
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.main import app
from src.dependencies import get_current_user
from src.database import get_db
from src.models.user import UserRole
import src.routers.brand as brand_mod

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


def _fake_admin(project_id: int = 42):
    return SimpleNamespace(id=1, role=UserRole.admin, project_id=project_id, is_active=True)


def _fake_db():
    db = MagicMock(); db.execute = AsyncMock(); db.commit = AsyncMock()
    return db


async def _ovr_user(): return _fake_admin()
async def _ovr_db(): yield _fake_db()


def _setup():
    app.dependency_overrides[get_current_user] = _ovr_user
    app.dependency_overrides[get_db] = _ovr_db


def _teardown():
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_remove_bg_disabled_returns_503(monkeypatch):
    monkeypatch.setattr(brand_mod.settings, "logo_bg_removal_enabled", False, raising=False)
    _setup()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/brand/remove-bg",
                             files={"file": ("l.png", PNG, "image/png")},
                             headers={"X-Project-Id": "42"})
        assert r.status_code == 503
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_remove_bg_happy_path(monkeypatch):
    monkeypatch.setattr(brand_mod.settings, "logo_bg_removal_enabled", True, raising=False)
    monkeypatch.setattr(brand_mod.settings, "logo_bg_removal_token", "tok", raising=False)
    out_png = b"\x89PNG\r\n\x1a\n" + b"\xAA" * 16
    captured = {}

    class _MockResp:
        status_code = 200
        content = out_png
        headers = {"content-type": "image/png"}

    class _MockClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, content=None, files=None, headers=None):
            captured["url"] = url; captured["headers"] = headers
            return _MockResp()

    monkeypatch.setattr(brand_mod.httpx, "AsyncClient", _MockClient)
    _setup()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/brand/remove-bg",
                             files={"file": ("l.png", PNG, "image/png")},
                             headers={"X-Project-Id": "42"})
        assert r.status_code == 200
        assert r.content == out_png
        assert captured["headers"]["X-Internal-Token"] == "tok"
        assert captured["url"].endswith("/remove-bg")
    finally:
        _teardown()


@pytest.mark.asyncio
async def test_remove_bg_upstream_timeout_returns_502(monkeypatch):
    monkeypatch.setattr(brand_mod.settings, "logo_bg_removal_enabled", True, raising=False)

    class _MockClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(brand_mod.httpx, "AsyncClient", _MockClient)
    _setup()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/brand/remove-bg",
                             files={"file": ("l.png", PNG, "image/png")},
                             headers={"X-Project-Id": "42"})
        assert r.status_code == 502
    finally:
        _teardown()
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `cd validator-contenthunter/backend && python -m pytest tests/test_brand_remove_bg.py -v`
Expected: FAIL — 404 (эндпоинта нет) / нет `brand_mod.httpx`.

- [ ] **Step 3: Implement endpoint**

В `backend/src/routers/brand.py` добавить `import httpx` к импортам, затем после функции `upload_brand_image` вставить:
```python
@router.post("/remove-bg")
async def remove_logo_background(
    file: UploadFile = File(...),
    current_user: ValidatorUser = Depends(get_current_user),
    x_project_id: int | None = Header(None, alias="X-Project-Id"),
):
    """Прокси удаления фона лого на rembg-микросервис (WP#136).

    Синхронно форвардит картинку на сервис уникализации, возвращает transparent PNG.
    Kill-switch settings.logo_bg_removal_enabled. Ошибки апстрима не ломают кроп —
    фронт продолжает без удаления фона.
    """
    _resolve_brand_project_id(current_user, x_project_id)  # проверка доступа к проекту

    if not settings.logo_bg_removal_enabled:
        raise HTTPException(status_code=503, detail="Удаление фона временно недоступно")

    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимум 10 МБ")
    mime = file.content_type or "image/png"
    if mime not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(status_code=400, detail=f"Формат {mime} не поддерживается")

    # SVG растеризуем до отправки в сервис (rembg ждёт растр).
    is_svg = mime == "image/svg+xml" or looks_like_svg(data[:64])
    if is_svg and os.environ.get("BRAND_SVG_RASTERIZE_ENABLED", "1") == "1":
        try:
            data = rasterize_svg_to_png(data)
        except Exception as e:
            raise HTTPException(status_code=400, detail="Не удалось обработать SVG") from e

    url = settings.logo_bg_removal_url.rstrip("/") + "/remove-bg"
    headers = {"X-Internal-Token": settings.logo_bg_removal_token}
    try:
        async with httpx.AsyncClient(timeout=settings.logo_bg_removal_timeout_s) as client:
            resp = await client.post(
                url, headers=headers,
                files={"file": ("logo.png", data, "image/png")},
            )
    except httpx.HTTPError as e:
        log.warning("[wp136 remove-bg] upstream error: %s", e)
        raise HTTPException(status_code=502, detail="Сервис удаления фона недоступен") from e

    if resp.status_code != 200:
        log.warning("[wp136 remove-bg] upstream status=%s", resp.status_code)
        raise HTTPException(status_code=502, detail="Не удалось убрать фон, попробуйте позже")

    from fastapi import Response
    return Response(content=resp.content, media_type="image/png")
```

> Примечание: тест `test_remove_bg_happy_path` мокает `AsyncClient.post` с сигнатурой `(url, content=None, files=None, headers=None)` — реальный вызов использует `files=`/`headers=`, мок их принимает; проверяется заголовок токена и суффикс URL.

- [ ] **Step 4: Run tests — verify they pass**

Run: `cd validator-contenthunter/backend && python -m pytest tests/test_brand_remove_bg.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Регресс svg-guard теста**

Run: `cd validator-contenthunter/backend && python -m pytest tests/test_brand_svg_guard.py -v`
Expected: PASS (без регрессий).

- [ ] **Step 6: Commit**

```bash
cd validator-contenthunter
git add backend/src/routers/brand.py backend/tests/test_brand_remove_bg.py
git commit -m "feat(wp136): backend proxy POST /api/brand/remove-bg (kill-switch + fail-soft)"
```

---

## Task 6: Frontend — чистая функция detect-skip

**Files:**
- Create: `validator-contenthunter/frontend/src/utils/logoSquareDetect.ts`
- Test: `validator-contenthunter/frontend/src/utils/__tests__/logoSquareDetect.spec.ts`

- [ ] **Step 1: Write failing test**

`src/utils/__tests__/logoSquareDetect.spec.ts`:
```typescript
import { describe, it, expect } from 'vitest'
import { isSquareWithTransparency } from '../logoSquareDetect'

function pixels(w: number, h: number, alpha: number): Uint8ClampedArray {
  const arr = new Uint8ClampedArray(w * h * 4)
  for (let i = 0; i < w * h; i++) { arr[i * 4 + 3] = alpha }
  return arr
}

describe('isSquareWithTransparency', () => {
  it('квадрат с прозрачными пикселями → true (skip кроп)', () => {
    const w = 8, h = 8
    const px = pixels(w, h, 255)
    px[3] = 0 // один прозрачный пиксель
    expect(isSquareWithTransparency(w, h, px)).toBe(true)
  })

  it('квадрат без прозрачности → false (нужен кроп/фон)', () => {
    const w = 8, h = 8
    expect(isSquareWithTransparency(w, h, pixels(w, h, 255))).toBe(false)
  })

  it('прямоугольник → false (нужен кроп) даже с прозрачностью', () => {
    const w = 16, h = 8
    const px = pixels(w, h, 255); px[3] = 0
    expect(isSquareWithTransparency(w, h, px)).toBe(false)
  })
})
```

- [ ] **Step 2: Run test — verify it fails**

Run: `cd validator-contenthunter/frontend && npx vitest run src/utils/__tests__/logoSquareDetect.spec.ts`
Expected: FAIL — модуль не найден.

- [ ] **Step 3: Implement**

`src/utils/logoSquareDetect.ts`:
```typescript
/**
 * WP#136: решает, можно ли пропустить окно кропа.
 * Пропускаем только если лого уже квадратное (w===h) И имеет реальную прозрачность
 * (хотя бы один пиксель с alpha===0). Иначе открываем кроп.
 *
 * Чистая функция — принимает готовые пиксели (RGBA), легко тестируется без DOM.
 */
export function isSquareWithTransparency(
  width: number,
  height: number,
  rgba: Uint8ClampedArray,
): boolean {
  if (width !== height || width === 0) return false
  for (let i = 3; i < rgba.length; i += 4) {
    if (rgba[i] === 0) return true
  }
  return false
}
```

- [ ] **Step 4: Run test — verify it passes**

Run: `cd validator-contenthunter/frontend && npx vitest run src/utils/__tests__/logoSquareDetect.spec.ts`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
cd validator-contenthunter
git add frontend/src/utils/logoSquareDetect.ts frontend/src/utils/__tests__/logoSquareDetect.spec.ts
git commit -m "feat(wp136): frontend logo square+transparency detect util"
```

---

## Task 7: Frontend — компонент `LogoCropModal.vue`

**Files:**
- Create: `validator-contenthunter/frontend/src/components/LogoCropModal.vue`

> Компонент тестируем вручную (canvas + getImageData в jsdom ненадёжны). Логика
> detect вынесена в Task 6 (юнит-тест). Здесь — DOM-glue.

- [ ] **Step 1: Создать компонент**

`src/components/LogoCropModal.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import api from '../api/client'

const props = defineProps<{ file: File; projectHeaders: Record<string, string>; bgRemovalAvailable: boolean }>()
const emit = defineEmits<{ (e: 'done', blob: Blob): void; (e: 'cancel'): void }>()

const OUT = 1024
const canvasRef = ref<HTMLCanvasElement | null>(null)
const zoom = ref(1)           // 1 = fit
const offset = ref({ x: 0, y: 0 })
const removeBg = ref(false)
const processing = ref(false)
const errorMsg = ref('')

let baseImg: HTMLImageElement | null = null   // оригинал (объект Image)
let cleanImg: HTMLImageElement | null = null  // результат удаления фона (кэш)
let dragging = false
let last = { x: 0, y: 0 }

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const im = new Image()
    im.onload = () => res(im)
    im.onerror = rej
    im.src = src
  })
}

function activeImg(): HTMLImageElement | null {
  return removeBg.value && cleanImg ? cleanImg : baseImg
}

function fitScale(im: HTMLImageElement): number {
  return Math.min(OUT / im.width, OUT / im.height)
}

function draw() {
  const cv = canvasRef.value, im = activeImg()
  if (!cv || !im) return
  const ctx = cv.getContext('2d')!
  ctx.clearRect(0, 0, OUT, OUT)
  const s = fitScale(im) * zoom.value
  const w = im.width * s, h = im.height * s
  const x = (OUT - w) / 2 + offset.value.x
  const y = (OUT - h) / 2 + offset.value.y
  ctx.drawImage(im, x, y, w, h)
}

onMounted(async () => {
  baseImg = await loadImage(URL.createObjectURL(props.file))
  draw()
})

watch([zoom, removeBg], draw)

async function onToggleBg() {
  errorMsg.value = ''
  if (!removeBg.value) { draw(); return }
  if (cleanImg) { draw(); return }       // уже есть в кэше
  processing.value = true
  try {
    const fd = new FormData()
    fd.append('file', props.file)
    const res = await api.post('/brand/remove-bg', fd, {
      responseType: 'blob',
      headers: { 'Content-Type': 'multipart/form-data', ...props.projectHeaders },
    })
    cleanImg = await loadImage(URL.createObjectURL(res.data as Blob))
    draw()
  } catch (e: any) {
    removeBg.value = false
    errorMsg.value = 'Не удалось убрать фон, попробуйте позже'
  } finally {
    processing.value = false
  }
}

function onDown(e: MouseEvent) { dragging = true; last = { x: e.clientX, y: e.clientY } }
function onMove(e: MouseEvent) {
  if (!dragging) return
  offset.value.x += e.clientX - last.x
  offset.value.y += e.clientY - last.y
  last = { x: e.clientX, y: e.clientY }
  draw()
}
function onUp() { dragging = false }

function onDone() {
  const cv = canvasRef.value
  if (!cv) return
  cv.toBlob((blob) => { if (blob) emit('done', blob) }, 'image/png')
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div class="bg-white rounded-2xl p-5 w-[420px] shadow-xl">
        <h3 class="text-lg font-semibold mb-3">Подгоните логотип</h3>
        <div class="relative w-[360px] h-[360px] mx-auto bg-[repeating-conic-gradient(#eee_0_25%,#fff_0_50%)] bg-[length:20px_20px] rounded-xl overflow-hidden">
          <canvas ref="canvasRef" :width="1024" :height="1024"
                  class="w-full h-full cursor-move"
                  @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp" />
          <div class="pointer-events-none absolute inset-0 border-2 border-indigo-400 rounded-xl" />
          <div v-if="processing" class="absolute inset-0 flex items-center justify-center bg-white/60">
            <span class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          </div>
        </div>

        <div class="mt-4 space-y-3">
          <label class="flex items-center gap-2 text-sm">
            Зум
            <input type="range" min="1" max="2" step="0.01" v-model.number="zoom" class="flex-1" />
          </label>
          <label v-if="bgRemovalAvailable" class="flex items-center gap-2 text-sm">
            <input type="checkbox" v-model="removeBg" @change="onToggleBg" />
            Удалить фон
          </label>
          <p v-if="errorMsg" class="text-xs text-red-500">{{ errorMsg }}</p>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <button class="px-4 py-2 text-sm rounded-lg border" @click="emit('cancel')">Отмена</button>
          <button class="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white" @click="onDone">Готово</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
```

- [ ] **Step 2: Type-check**

Run: `cd validator-contenthunter/frontend && npx vue-tsc --noEmit`
Expected: без ошибок по `LogoCropModal.vue`.

- [ ] **Step 3: Commit**

```bash
cd validator-contenthunter
git add frontend/src/components/LogoCropModal.vue
git commit -m "feat(wp136): LogoCropModal (fit-кроп, зум, drag, удалить фон live-preview)"
```

---

## Task 8: Frontend — интеграция модалки в `BrandPage.vue`

**Files:**
- Modify: `validator-contenthunter/frontend/src/pages/client/BrandPage.vue`

- [ ] **Step 1: Импорт + state**

В `<script setup>` `BrandPage.vue` добавить импорты и detect-утиль:
```typescript
import LogoCropModal from '../../components/LogoCropModal.vue'
import { isSquareWithTransparency } from '../../utils/logoSquareDetect'

const cropFile = ref<File | null>(null)
const bgRemovalAvailable = ref(true)  // если /remove-bg отдаст 503 — спрячем чекбокс
```

- [ ] **Step 2: Хелпер анализа файла + ветвление в uploadFile**

Добавить хелпер и заменить ветку `field === 'logo'`. Новый код:
```typescript
function analyzeFile(file: File): Promise<{ w: number; h: number; rgba: Uint8ClampedArray } | null> {
  return new Promise((resolve) => {
    const im = new Image()
    im.onload = () => {
      const cv = document.createElement('canvas')
      cv.width = im.naturalWidth; cv.height = im.naturalHeight
      const ctx = cv.getContext('2d')
      if (!ctx) return resolve(null)
      ctx.drawImage(im, 0, 0)
      try {
        const d = ctx.getImageData(0, 0, cv.width, cv.height)
        resolve({ w: cv.width, h: cv.height, rgba: d.data })
      } catch { resolve(null) }
    }
    im.onerror = () => resolve(null)
    im.src = URL.createObjectURL(file)
  })
}

async function uploadLogoBlob(blob: Blob) {
  uploading['logo'] = true
  try {
    const fd = new FormData()
    fd.append('file', blob, 'logo.png')
    fd.append('field', 'logo')
    const res = await api.post('/brand/upload-image', fd, {
      headers: { 'Content-Type': 'multipart/form-data', ...projectHeaders() },
    })
    form.logo_url = res.data.url
    scheduleAutoSave()
  } catch (e: any) {
    alert(e?.response?.data?.detail || 'Ошибка загрузки')
  } finally {
    uploading['logo'] = false
  }
}
```

В существующей `uploadFile` заменить ТОЛЬКО ветку логотипа: для `field === 'logo'`
не грузим сразу, а решаем skip/кроп. Минимальная правка — в начале `uploadFile`:
```typescript
async function uploadFile(event: Event, field: string) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return

  if (field === 'logo') {
    const info = await analyzeFile(file)
    if (info && isSquareWithTransparency(info.w, info.h, info.rgba)) {
      await uploadLogoBlob(file)      // уже квадрат+прозрачный → грузим как есть
    } else {
      cropFile.value = file           // открыть модалку кропа
    }
    return
  }

  // ... существующая логика для остальных полей (media и т.п.) без изменений
  uploading[field] = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('field', field)
    const res = await api.post('/brand/upload-image', fd, {
      headers: { 'Content-Type': 'multipart/form-data', ...projectHeaders() }
    })
  } catch(e: any) {
    alert(e?.response?.data?.detail || 'Ошибка загрузки')
  } finally {
    uploading[field] = false
  }
}
```
> Прим.: прежняя ветка `if (field === 'logo')` внутри try удаляется (логотип теперь
> обрабатывается выше и выходит через `return`).

- [ ] **Step 3: Разметка модалки**

В `<template>` `BrandPage.vue` перед закрывающим корневым тегом добавить:
```vue
    <LogoCropModal
      v-if="cropFile"
      :file="cropFile"
      :project-headers="projectHeaders()"
      :bg-removal-available="bgRemovalAvailable"
      @cancel="cropFile = null"
      @done="(blob) => { cropFile = null; uploadLogoBlob(blob) }"
    />
```

- [ ] **Step 4: Type-check + полный прогон vitest**

Run: `cd validator-contenthunter/frontend && npx vue-tsc --noEmit && npx vitest run`
Expected: без ошибок типов; все существующие тесты + `logoSquareDetect` зелёные.

- [ ] **Step 5: Commit**

```bash
cd validator-contenthunter
git add frontend/src/pages/client/BrandPage.vue
git commit -m "feat(wp136): integrate LogoCropModal into BrandPage logo upload"
```

---

## Task 9: Полный регресс + ручная проверка + codex

**Files:** —

- [ ] **Step 1: Backend полный прогон**

Run: `cd validator-contenthunter/backend && python -m pytest -q`
Expected: без новых падений (зелёные `test_brand_remove_bg`, `test_brand_svg_guard`).

- [ ] **Step 2: Frontend полный прогон**

Run: `cd validator-contenthunter/frontend && npx vitest run && npx vue-tsc --noEmit`
Expected: всё зелёное.

- [ ] **Step 3: codex review кода**

Run: `~/.local/bin/codex review --uncommitted` (или по диапазону веток).
Действие: разобрать P1, при необходимости — итерация.

- [ ] **Step 4: Ручная проверка (после деплоя dev/прод)**

Чек-лист:
- Прямоугольный JPEG-лого → открывается модалка, лого вписано целиком (fit), зум/drag работают.
- «Готово» → в карточке появляется квадратное лого (1:1), не сплющенное.
- Квадратный PNG с прозрачностью → модалка НЕ открывается, грузится сразу.
- Чекбокс «удалить фон» (при `LOGO_BG_REMOVAL_ENABLED=1` и живом сервисе) → фон уходит, превью обновляется; при выключенном флаге/недоступном сервисе — чекбокс скрыт или мягкая ошибка, кроп продолжает работать.
- Проверить итоговый объект в S3: PNG 1024×1024 RGBA.

- [ ] **Step 5: Финал — деплой-заметки**

Зафиксировать в evidence: rsync микросервиса на 91.98.180.103, `pip install`, прогрев модели, ufw-правило, `pm2 start`, выставить общий `LOGO_BG_REMOVAL_TOKEN` в backend `.env` и в ecosystem, выставить `LOGO_BG_REMOVAL_ENABLED=true` после прогрева, рестарт валидатор-бэка.

---

## Self-Review

**Spec coverage:**
- Detect-skip (квадрат+прозрачность) → Task 6 + Task 8 (`analyzeFile`).
- Окно кропа (fit-по-умолчанию, зум, drag) → Task 7.
- Чекбокс «удалить фон» live-preview → Task 7 (`onToggleBg`) + Task 5 (прокси) + Task 2 (rembg).
- Микросервис rembg на 91.98.180.103, token+firewall → Tasks 1-3.
- Прокси с kill-switch + fail-soft → Task 5.
- Выход PNG 1024×1024 RGBA, хранение через upload-image, потребитель не меняется → Task 7 (`OUT=1024`, `toBlob`) + Task 8 (`uploadLogoBlob`).
- Тесты (backend/микросервис/frontend) → Tasks 1,2,5,6 + Task 9.
- Вне scope (прочие поля, переобработка существующих, FFmpeg) → не затрагиваются.

**Placeholder scan:** код приведён полностью в каждом шаге; `REPLACE_WITH_SHARED_SECRET` — намеренный ops-плейсхолдер секрета (не код-заглушка).

**Type/имена consistency:** `isSquareWithTransparency(width,height,rgba)` — едина в Tasks 6/8; `uploadLogoBlob`, `analyzeFile`, `cropFile`, `bgRemovalAvailable` — согласованы между Tasks 7/8; эндпоинт `/api/brand/remove-bg` и заголовок `X-Internal-Token` — едины в Tasks 2/5; `settings.logo_bg_removal_*` — едины в Tasks 4/5.
