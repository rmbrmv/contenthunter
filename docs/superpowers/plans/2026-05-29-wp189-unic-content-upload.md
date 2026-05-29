# WP#189 — Механика загрузки контента уникализации — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить кнопку «Загрузить контент» в раздел «Уникализация → Контент», которая грузит файлы в S3 и создаёт строки `validator_unic_content` в правильной таксономии, чтобы файлы встроились в уникализацию.

**Architecture:** Серверная multipart-загрузка (Вариант A). Фронт шлёт `multipart/form-data` (файлы + метаданные) на новый `POST /api/unic-content/upload`. Бэкенд через серверную константу-маппинг определяет S3-папку, `content_type`, `label`-префикс и допустимые форматы, грузит каждый файл через существующий `_upload_bytes_to_s3`, вставляет строку. Чистая логика маппинга вынесена в отдельный модуль для юнит-тестов.

**Tech Stack:** Python/FastAPI (async SQLAlchemy `text()`), boto3 multipart, pytest + httpx ASGITransport; Vue 3 `<script setup>` + axios + Tailwind.

**Репозиторий реализации:** `/home/claude-user/validator-contenthunter` (НЕ `contenthunter` — там только spec/plan).
**Спека:** `contenthunter:docs/superpowers/specs/2026-05-29-wp189-unic-content-upload-design.md`.

**⚠️ Деплой-гоча:** `npm run build` во фронте авто-копирует сборку в `/var/www/validator/` (= прод). При реализации/верификации НЕ запускать `npm run build` — только `npx vue-tsc --noEmit` (type-check) и ручная проверка через dev-сервер. Деплой — отдельным шагом по готовности.

---

## File Structure

- **Create** `backend/src/services/unic_upload.py` — чистый маппинг `content_kind` → (S3-папка, `content_type`, label-префикс, форматы, mime) + helpers (`validate_ext`, `build_s3_key`, `next_seq`, `build_label`). Без БД/S3 — целиком юнит-тестируемо.
- **Create** `backend/tests/test_unic_upload_mapping.py` — юнит-тесты модуля маппинга.
- **Modify** `backend/src/main.py` — подключить `unic_content.router` (сейчас НЕ подключён).
- **Modify** `backend/src/routers/unic_content.py` — добавить `POST /upload` (admin-only, multipart).
- **Create** `backend/tests/test_unic_content_upload.py` — тесты эндпоинта (S3+БД замоканы).
- **Modify** `frontend/src/pages/admin/UnicContentPage.vue` — кнопка «⬆ Загрузить контент» + модалка загрузки.

---

## Task 1: Модуль маппинга и helpers

**Files:**
- Create: `backend/src/services/unic_upload.py`
- Test: `backend/tests/test_unic_upload_mapping.py`

- [ ] **Step 1: Написать падающий тест**

`backend/tests/test_unic_upload_mapping.py`:
```python
"""Юнит-тесты маппинга content_kind → БД-таксономия (без БД/S3)."""
import pytest
from fastapi import HTTPException

from src.services import unic_upload as u


def test_resolve_kind_maps_to_db_taxonomy():
    folder, ct, prefix, allowed, mime = u.resolve_kind("overlay_sounds")
    assert (folder, ct, prefix) == ("overlay_sounds", "audio", "sounds")
    assert allowed == {"mp3"} and mime == "audio/mpeg"
    assert u.resolve_kind("overlay_video")[1] == "video"
    assert u.resolve_kind("overlay_logo")[1] == "image"
    assert u.resolve_kind("overlay_logo")[2] == "logo"


def test_resolve_kind_unknown_raises():
    with pytest.raises(HTTPException) as e:
        u.resolve_kind("nope")
    assert e.value.status_code == 400


def test_validate_ext_ok_and_bad():
    assert u.validate_ext("overlay_sounds", "track.MP3") == "mp3"
    with pytest.raises(HTTPException):
        u.validate_ext("overlay_sounds", "track.wav")
    with pytest.raises(HTTPException):
        u.validate_ext("overlay_sounds", "noext")


def test_validate_ext_blocks_svg_for_logo_and_pattern():
    for kind in ("overlay_logo", "overlay_pattern"):
        with pytest.raises(HTTPException) as e:
            u.validate_ext(kind, "icon.svg")
        assert "SVG" in e.value.detail


def test_validate_ext_system_allows_any():
    assert u.validate_ext("system", "Status_Success_Icon.svg") == "svg"
    assert u.validate_ext("system", "thing.bin") == "bin"


def test_next_seq_and_build_label():
    labels = ["sounds_0_1", "sounds_0_2", "sounds_0_10", "other_0_5"]
    assert u.next_seq(labels, "sounds", 0) == 11
    assert u.next_seq([], "sounds", 0) == 1
    assert u.build_label("sounds", 0, 11) == "sounds_0_11"
    assert u.build_label("system", 0, 1) == "system"


def test_build_s3_key_shape():
    key = u.build_s3_key("overlay_video", "mp4")
    assert key.startswith("factory/overlay_video/") and key.endswith(".mp4")
```

- [ ] **Step 2: Запустить тест — убедиться что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_unic_upload_mapping.py -v`
Expected: FAIL (`ModuleNotFoundError: src.services.unic_upload`).

- [ ] **Step 3: Реализовать модуль**

`backend/src/services/unic_upload.py`:
```python
"""Маппинг «тип контента» (UI) → S3-папка / БД-таксономия для validator_unic_content.

Значения content_kind из UI (overlay_sounds/...) — это имена S3-папок, НЕ значения
колонки content_type. Воркер уникализации (unic-worker) фильтрует строки по
content_type (audio/application/image/video) + label LIKE 'logo%'/'pattern%'.
Чтобы загруженный файл встроился в уникализацию, строка пишется в правильной таксономии.
"""
from __future__ import annotations

import re
import uuid

from fastapi import HTTPException

# content_kind -> (s3_folder, db_content_type, label_prefix, allowed_exts, s3_mime)
CONTENT_KIND_MAP: dict[str, tuple[str, str, str, set[str], str | None]] = {
    "overlay_sounds":  ("overlay_sounds",  "audio",       "sounds",  {"mp3"},        "audio/mpeg"),
    "overlay_fonts":   ("overlay_fonts",   "application", "fonts",   {"ttf", "otf"}, "application/octet-stream"),
    "overlay_pattern": ("overlay_pattern", "image",       "pattern", {"png"},        "image/png"),
    "overlay_logo":    ("overlay_logo",    "image",       "logo",    {"png"},        "image/png"),
    "overlay_video":   ("overlay_video",   "video",       "video",   {"mp4"},        "video/mp4"),
    "system":          ("system",          "image",       "system",  set(),          None),  # любой формат
}

DEFAULT_CHROMAKEY = "0x00ff30"


def get_ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def resolve_kind(content_kind: str):
    cfg = CONTENT_KIND_MAP.get(content_kind)
    if cfg is None:
        raise HTTPException(status_code=400, detail=f"Неизвестный тип контента: {content_kind}")
    return cfg


def validate_ext(content_kind: str, filename: str) -> str:
    """Возвращает расширение или кидает HTTPException(400). 'system' допускает любое непустое."""
    _folder, _ct, _prefix, allowed, _mime = resolve_kind(content_kind)
    ext = get_ext(filename)
    if not ext:
        raise HTTPException(status_code=400, detail=f"Файл «{filename}» без расширения")
    # SVG роняет FFmpeg в уникализации (Invalid PNG) — прод-воркер его не растеризует.
    if content_kind in ("overlay_logo", "overlay_pattern") and ext == "svg":
        raise HTTPException(status_code=400, detail="SVG не поддерживается для логотипов/паттернов. Загрузите PNG.")
    if allowed and ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Файл «{filename}»: формат .{ext} не поддерживается для {content_kind}. "
                   f"Разрешено: {', '.join(sorted(allowed))}",
        )
    return ext


def build_s3_key(folder: str, ext: str) -> str:
    return f"factory/{folder}/{uuid.uuid4().hex}.{ext}"


def next_seq(existing_labels: list[str], prefix: str, project_id: int) -> int:
    """Следующий порядковый номер для label '<prefix>_<project_id>_<n>'."""
    pat = re.compile(rf"^{re.escape(prefix)}_{project_id}_(\d+)$")
    nums = [int(m.group(1)) for lbl in existing_labels if (m := pat.match(lbl or ""))]
    return (max(nums) + 1) if nums else 1


def build_label(prefix: str, project_id: int, seq: int) -> str:
    if prefix == "system":
        return "system"
    return f"{prefix}_{project_id}_{seq}"
```

- [ ] **Step 4: Запустить тест — убедиться что зелёный**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_unic_upload_mapping.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/services/unic_upload.py backend/tests/test_unic_upload_mapping.py
git commit -m "feat(wp189): unic_upload mapping module + unit tests"
```

---

## Task 2: Подключить роутер unic_content в main.py

**Files:**
- Modify: `backend/src/main.py` (import-блок строк 11-18; include-блок строк 128-144)

Роутер `unic_content` существует, но НЕ подключён — GET/POST/PUT/DELETE и новый `/upload` недоступны без include.

- [ ] **Step 1: Написать падающий тест**

Добавить в новый файл `backend/tests/test_unic_content_upload.py` (он же расширится в Task 3) временную проверку маршрута:
```python
def test_upload_route_registered():
    from src.main import app
    paths = {r.path for r in app.routes}
    assert "/api/unic-content/upload" in paths
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_unic_content_upload.py::test_upload_route_registered -v`
Expected: FAIL (маршрут отсутствует — роутер не подключён и эндпоинта ещё нет).

> Примечание: этот тест станет зелёным только после Task 2 + Task 3 (нужен и include, и сам эндпоинт). После Step 3 ниже он всё ещё красный (нет эндпоинта) — это ожидаемо; финально зеленеет в Task 3.

- [ ] **Step 3: Подключить роутер**

В `backend/src/main.py` в импорт-блоке (рядом со строкой `from .routers import contract`) добавить:
```python
from .routers import unic_content
```
В include-блоке (после `app.include_router(clients.router)`, строка ~144) добавить:
```python
app.include_router(unic_content.router)
```

- [ ] **Step 4: Проверить что приложение импортируется**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -c "from src.main import app; print('ok', any(r.path=='/api/unic-content' for r in app.routes))"`
Expected: `ok True` (GET/POST/PUT/DELETE подключились; `/upload` появится в Task 3).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/main.py backend/tests/test_unic_content_upload.py
git commit -m "feat(wp189): register unic_content router in main.py"
```

---

## Task 3: Эндпоинт POST /api/unic-content/upload

**Files:**
- Modify: `backend/src/routers/unic_content.py`
- Test: `backend/tests/test_unic_content_upload.py`

- [ ] **Step 1: Дописать падающие тесты эндпоинта**

Заменить содержимое `backend/tests/test_unic_content_upload.py` на:
```python
"""Тесты POST /api/unic-content/upload (S3 и БД замоканы)."""
import io
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.main import app
from src.dependencies import get_current_user
from src.database import get_db
from src.models.user import UserRole
import src.routers.unic_content as uc


def test_upload_route_registered():
    paths = {r.path for r in app.routes}
    assert "/api/unic-content/upload" in paths


def _fake_user(role=UserRole.admin):
    return SimpleNamespace(id=1, role=role, project_id=0, is_active=True)


class _Result:
    """Универсальный результат: .all()->[] (SELECT label), .mappings().first()->{'id':1} (INSERT)."""
    def all(self):
        return []
    def mappings(self):
        return self
    def first(self):
        return {"id": 1}


def _fake_db():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result())
    db.commit = AsyncMock()
    return db


def _setup(monkeypatch, role=UserRole.admin):
    captured = {}

    async def _mock_upload(data, key, mime, context=""):
        captured["key"] = key
        captured["mime"] = mime

    monkeypatch.setattr(uc, "_upload_bytes_to_s3", _mock_upload)
    monkeypatch.setattr(uc, "get_public_url", lambda key: f"https://cdn.example/{key}")
    app.dependency_overrides[get_current_user] = lambda: _fake_user(role)
    app.dependency_overrides[get_db] = lambda: _gen_db()
    return captured


_db_singleton = {}
def _gen_db():
    db = _db_singleton.get("db") or _fake_db()
    _db_singleton["db"] = db
    yield db


def _teardown():
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    _db_singleton.clear()


@pytest.mark.asyncio
async def test_upload_sounds_creates_audio_row(monkeypatch):
    _setup(monkeypatch)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/unic-content/upload",
                files={"files": ("track.mp3", io.BytesIO(b"ID3data"), "audio/mpeg")},
                data={"content_kind": "overlay_sounds", "usage_type": "Универсально (любой проект)", "project_id": "0"},
            )
    finally:
        _teardown()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["errors"] == []
    row = body["created"][0]
    assert row["content_type"] == "audio"
    assert row["label"] == "sounds_0_1"
    assert row["file_path"].startswith("https://cdn.example/factory/overlay_sounds/")
    assert row["chromakey_color"] is None


@pytest.mark.asyncio
async def test_upload_video_sets_default_chromakey(monkeypatch):
    _setup(monkeypatch)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/unic-content/upload",
                files={"files": ("clip.mp4", io.BytesIO(b"\x00\x00\x00\x18ftyp"), "video/mp4")},
                data={"content_kind": "overlay_video", "usage_type": "Универсально (любой проект)", "project_id": "0"},
            )
    finally:
        _teardown()
    assert r.status_code == 200, r.text
    row = r.json()["created"][0]
    assert row["content_type"] == "video"
    assert row["chromakey_color"] == "0x00ff30"


@pytest.mark.asyncio
async def test_upload_logo_rejects_svg(monkeypatch):
    _setup(monkeypatch)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/unic-content/upload",
                files={"files": ("logo.svg", io.BytesIO(b"<svg/>"), "image/svg+xml")},
                data={"content_kind": "overlay_logo", "usage_type": "Под проект (один конкретный проект)", "project_id": "54"},
            )
    finally:
        _teardown()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == []
    assert body["errors"] and "SVG" in body["errors"][0]["detail"]


@pytest.mark.asyncio
async def test_upload_non_admin_forbidden(monkeypatch):
    _setup(monkeypatch, role=UserRole.client)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/unic-content/upload",
                files={"files": ("track.mp3", io.BytesIO(b"x"), "audio/mpeg")},
                data={"content_kind": "overlay_sounds", "usage_type": "Универсально (любой проект)", "project_id": "0"},
            )
    finally:
        _teardown()
    assert r.status_code == 403
```

- [ ] **Step 2: Запустить — убедиться что падают**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_unic_content_upload.py -v`
Expected: FAIL (эндпоинта `/upload` ещё нет → 404 / route assert падает).

- [ ] **Step 3: Реализовать эндпоинт**

В начало `backend/src/routers/unic_content.py` добавить импорты (к существующей строке `from fastapi import ...`):
```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from ..services.s3_upload import _upload_bytes_to_s3
from ..services.s3_service import get_public_url
from ..services import unic_upload
```

В конец файла добавить:
```python
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 МБ на файл — предохранитель


@router.post("/upload")
async def upload_unic_content(
    files: list[UploadFile] = File(...),
    content_kind: str = Form(...),
    usage_type: str = Form(...),
    project_id: int = Form(0),
    chromakey_color: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: ValidatorUser = Depends(get_current_user),
):
    """Загрузка одного/нескольких файлов в S3 + строки в validator_unic_content.

    content_kind задаёт S3-папку и БД-таксономию (см. services/unic_upload).
    usage_type/project_id пишутся как есть (свобода без проверок — решение по WP#189).
    Частичный успех: валидные файлы грузятся, по невалидным — запись в errors.
    """
    if current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    folder, db_content_type, label_prefix, _allowed, s3_mime = unic_upload.resolve_kind(content_kind)

    res = await db.execute(
        text("SELECT label FROM validator_unic_content WHERE label LIKE :pat"),
        {"pat": f"{label_prefix}_{project_id}_%"},
    )
    existing = [r[0] for r in res.all()]
    seq = unic_upload.next_seq(existing, label_prefix, project_id)

    created: list[dict] = []
    errors: list[dict] = []
    for f in files:
        try:
            ext = unic_upload.validate_ext(content_kind, f.filename or "")
            data = await f.read()
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=400, detail=f"Файл «{f.filename}» больше 200 МБ")
            key = unic_upload.build_s3_key(folder, ext)
            mime = s3_mime or (f.content_type or "application/octet-stream")
            await _upload_bytes_to_s3(data, key, mime, context="unic-content/upload")
            row = {
                "content_type": db_content_type,
                "label": unic_upload.build_label(label_prefix, project_id, seq),
                "usage_type": usage_type,
                "project_id": project_id,
                "duration": None,
                "size": round(len(data) / 1024 / 1024, 2),
                "file_path": get_public_url(key),
                "chromakey_color": (chromakey_color or unic_upload.DEFAULT_CHROMAKEY) if content_kind == "overlay_video" else None,
            }
            ins = await db.execute(text("""
                INSERT INTO validator_unic_content
                  (content_type, label, usage_type, project_id, duration, size, file_path, chromakey_color)
                VALUES (:content_type,:label,:usage_type,:project_id,:duration,:size,:file_path,:chromakey_color)
                RETURNING id
            """), row)
            row["id"] = ins.mappings().first()["id"]
            row["project_name"] = None
            created.append(row)
            seq += 1
        except HTTPException as e:
            errors.append({"file": f.filename, "detail": e.detail})
    await db.commit()
    return {"created": created, "errors": errors}
```

- [ ] **Step 4: Запустить — убедиться что зелёные**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_unic_content_upload.py tests/test_unic_upload_mapping.py -v`
Expected: PASS (все тесты — route + 4 сценария + 7 юнит-тестов).

- [ ] **Step 5: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add backend/src/routers/unic_content.py backend/tests/test_unic_content_upload.py
git commit -m "feat(wp189): POST /api/unic-content/upload — S3 multipart + row insert"
```

---

## Task 4: Фронт — кнопка и модалка загрузки

**Files:**
- Modify: `frontend/src/pages/admin/UnicContentPage.vue`

Паттерн: существующие `Teleport`-модалки, стили `.input-field`/`.field-label`, axios `api` из `@/api/client`.

- [ ] **Step 1: Кнопка «Загрузить контент» в шапке**

В `<template>`, в блоке шапки (строки 3-9), рядом с кнопкой «Добавить контент» добавить ВТОРУЮ кнопку (обернуть обе в `<div class="flex gap-2">`):
```html
<button @click="openUpload"
  class="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-medium rounded-lg shadow-sm transition-colors text-sm">
  <span class="text-base">⬆</span> Загрузить контент
</button>
```

- [ ] **Step 2: Модалка загрузки в `<template>`**

Перед закрывающим `</div>` корня (после блока «Модал: Удаление», строка ~199) добавить:
```html
<!-- Модал: Загрузка контента -->
<Teleport to="body">
  <div v-if="uploadModal.show" class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <div class="absolute inset-0 bg-black/40" @click="uploadModal.show = false"></div>
    <div class="relative bg-white rounded-2xl shadow-xl w-full max-w-lg p-6">
      <h3 class="text-lg font-bold text-gray-800 mb-5">Загрузить контент</h3>
      <div class="space-y-4">
        <div>
          <label class="field-label">Файлы *</label>
          <input type="file" multiple @change="onFilesPicked" class="input-field" />
          <p v-if="uploadForm.files.length" class="text-xs text-gray-500 mt-1">Выбрано: {{ uploadForm.files.length }}</p>
        </div>
        <div>
          <label class="field-label">Тип контента *</label>
          <select v-model="uploadForm.content_kind" class="input-field">
            <option v-for="o in kindOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </div>
        <div>
          <label class="field-label">Тип использования *</label>
          <select v-model="uploadForm.usage_type" class="input-field">
            <option value="Универсально (любой проект)">Универсально (любой проект)</option>
            <option value="Под проект (один конкретный проект)">Под проект (один конкретный проект)</option>
          </select>
        </div>
        <div v-if="showProject">
          <label class="field-label">Проект *</label>
          <select v-model.number="uploadForm.project_id" class="input-field">
            <option :value="0" disabled>— выберите проект —</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.project }}</option>
          </select>
        </div>
        <div v-if="showChromakey">
          <label class="field-label">Chromakey цвет</label>
          <input v-model="uploadForm.chromakey_color" type="text" class="input-field" placeholder="0x00ff30" />
        </div>
        <div v-if="uploadErrors.length" class="text-xs text-red-600 space-y-1">
          <p v-for="(e, i) in uploadErrors" :key="i">⚠️ {{ e.file }}: {{ e.detail }}</p>
        </div>
      </div>
      <div class="flex gap-3 mt-6">
        <button @click="submitUpload" :disabled="uploading || !canUpload"
          class="flex-1 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white font-medium rounded-lg transition-colors text-sm">
          {{ uploading ? 'Загрузка...' : 'Загрузить' }}
        </button>
        <button @click="uploadModal.show = false"
          class="flex-1 px-4 py-2.5 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-colors text-sm">
          Отмена
        </button>
      </div>
    </div>
  </div>
</Teleport>
```

- [ ] **Step 3: Логика в `<script setup>`**

После строки `const deleteModal = reactive(...)` (строка ~281) добавить:
```typescript
interface ProjectOpt { id: number; project: string }

const kindOptions = [
  { value: 'overlay_sounds', label: 'Звуки (overlay_sounds)' },
  { value: 'overlay_fonts', label: 'Шрифты (overlay_fonts)' },
  { value: 'overlay_pattern', label: 'Паттерны (overlay_pattern)' },
  { value: 'overlay_logo', label: 'Логотипы (overlay_logo)' },
  { value: 'overlay_video', label: 'Видео (overlay_video)' },
  { value: 'system', label: 'Служебные (system)' },
]

const projects = ref<ProjectOpt[]>([])
const uploading = ref(false)
const uploadErrors = ref<{ file: string; detail: string }[]>([])
const uploadModal = reactive({ show: false })
const uploadForm = reactive({
  content_kind: 'overlay_sounds',
  usage_type: 'Универсально (любой проект)',
  project_id: 0,
  chromakey_color: '0x00ff30',
  files: [] as File[],
})

const showProject = computed(() => uploadForm.usage_type.includes('Под проект'))
const showChromakey = computed(() => uploadForm.content_kind === 'overlay_video')
const canUpload = computed(() =>
  uploadForm.files.length > 0 && (!showProject.value || uploadForm.project_id > 0)
)

function openUpload() {
  Object.assign(uploadForm, {
    content_kind: 'overlay_sounds',
    usage_type: 'Универсально (любой проект)',
    project_id: 0,
    chromakey_color: '0x00ff30',
    files: [],
  })
  uploadErrors.value = []
  uploadModal.show = true
}

function onFilesPicked(e: Event) {
  const input = e.target as HTMLInputElement
  uploadForm.files = input.files ? Array.from(input.files) : []
}

async function submitUpload() {
  if (!canUpload.value) return
  uploading.value = true
  uploadErrors.value = []
  try {
    const fd = new FormData()
    uploadForm.files.forEach(f => fd.append('files', f))
    fd.append('content_kind', uploadForm.content_kind)
    fd.append('usage_type', uploadForm.usage_type)
    fd.append('project_id', String(showProject.value ? uploadForm.project_id : 0))
    if (showChromakey.value) fd.append('chromakey_color', uploadForm.chromakey_color)

    const res = await api.post('/unic-content/upload', fd, { timeout: 300000 })
    uploadErrors.value = res.data.errors || []
    const list = await api.get('/unic-content')
    items.value = list.data
    if (uploadErrors.value.length === 0) uploadModal.show = false
  } finally {
    uploading.value = false
  }
}
```

- [ ] **Step 4: Загрузить проекты в onMounted**

Заменить существующий `onMounted` (строки ~324-327) на:
```typescript
onMounted(async () => {
  const [res, pr] = await Promise.allSettled([api.get('/unic-content'), api.get('/projects')])
  if (res.status === 'fulfilled') items.value = res.value.data
  if (pr.status === 'fulfilled') projects.value = pr.value.data
})
```

- [ ] **Step 5: Type-check (БЕЗ `npm run build` — он авто-деплоит!)**

Run: `cd /home/claude-user/validator-contenthunter/frontend && npx vue-tsc --noEmit`
Expected: без новых ошибок в `UnicContentPage.vue`.
(Если `vue-tsc` отсутствует — `npx tsc --noEmit -p tsconfig.json`. Запуск `npm run build` запрещён до этапа деплоя.)

- [ ] **Step 6: Коммит**

```bash
cd /home/claude-user/validator-contenthunter
git add frontend/src/pages/admin/UnicContentPage.vue
git commit -m "feat(wp189): UnicContentPage — кнопка и модалка загрузки контента"
```

---

## Task 5: Финальная проверка и сводка

- [ ] **Step 1: Прогон всего нового бэкенд-набора**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_unic_upload_mapping.py tests/test_unic_content_upload.py -v`
Expected: все PASS.

- [ ] **Step 2: Регресс смежных тестов (роутеры/загрузка)**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_brand_svg_guard.py tests/test_upload_complete.py -v`
Expected: без новых падений (подключение роутера не задело существующее).

- [ ] **Step 3: Ручная проверка (dev)**

Поднять dev-фронт (`npm run dev`) + бэкенд, открыть «Уникализация → Контент» под admin, нажать «Загрузить контент»:
- загрузить 1-2 mp3 как `overlay_sounds`/универсально → строки появились (`content_type=audio`, `label=sounds_0_N`);
- `overlay_video` → видно поле chromakey;
- `overlay_logo` + «Под проект» → появляется селект проекта; svg → ошибка.

- [ ] **Step 4: Сводка**

Отчёт: что реализовано, результаты тестов, что осталось (деплой, codex review, обновление OpenProject #189).

---

## Self-Review (выполнено автором плана)

- **Покрытие спеки:** маппинг (Task 1) ✓; серверный эндпоинт A + валидация + label/seq + chromakey + размер + частичный успех (Task 3) ✓; регистрация роутера — риск из спеки (Task 2) ✓; фронт-кнопка+модалка+проекты+условные поля (Task 4) ✓; запрет SVG logo/pattern (Task 1 тест + Task 3 тест) ✓; свобода usage без проверок (эндпоинт пишет как есть) ✓; миграция не нужна (явно) ✓; тесты TDD (Task 1/3) ✓.
- **Плейсхолдеры:** нет — весь код приведён.
- **Согласованность типов:** `unic_upload.resolve_kind/validate_ext/build_s3_key/next_seq/build_label/DEFAULT_CHROMAKEY` используются одинаково в Task 1 и Task 3; имена монкипатчей (`uc._upload_bytes_to_s3`, `uc.get_public_url`) соответствуют импортам в роутере.
- **Гочи зафиксированы:** `npm run build` авто-деплой (Task 4 Step 5); S3 `file_path` через `get_public_url` (= beget-бакет, качаемо воркером) — проверить, что прод `settings.s3_public_url` сконфигурирован.

## Out of scope / после плана

- Деплой (бэкенд PM2-рестарт + фронт-сборка в `/var/www/validator/`) — отдельным шагом.
- `codex review` плана и диффа (практика репозитория) перед мержем.
- Доработка воркера под per-project sounds/fonts/pattern/video и SVG-растеризация — не входит.
