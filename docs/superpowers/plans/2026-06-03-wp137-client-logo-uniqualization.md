# WP#137 — Уникализация лого клиента — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в клиентский мастер «Схемы» новый Шаг 1/2 — генерацию N вариантов лого (Laozhang gpt-image-1) и выбор клиентом нужного числа перед переходом к выбору схем.

**Architecture:** Бэкенд (validator-contenthunter, FastAPI): 3 новые таблицы (`logo_variants`, `logo_selections`, `logo_generation_tasks`), сервисы генерации (Laozhang + Pillow), очередь+воркер в lifespan-loop (генерация = лёгкие HTTP-вызовы, исполняется в backend), роутер `/api/logo-variants/*`. Фронтенд (Vue): `LogoVariantStep.vue` рендерится как gate ПЕРЕД существующим мастером схем (не трогаем сложную логику `SchemesPage` step-машины). TTL-очистка вшита в тот же фоновый loop (отдельной cron-инфры в backend нет).

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy(async) / Alembic / Pillow / httpx / boto3(S3) · Vue 3 / TypeScript / axios / Tailwind · PostgreSQL `openclaw`.

**Отклонения от спеки (осознанные, для изоляции):**
- Вместо переиспользования `unic_tasks` (его колонки и CHECK-констрейнты заточены под scheme_preview + удалённый FFmpeg-воркер) — **отдельная таблица `logo_generation_tasks`**. Чище границы, без миграции чужих констрейнтов.
- TTL-очистка — не отдельный cron, а ветка в lifespan-loop (запуск раз в ~24ч).

**Переиспользуемые символы кодовой базы:**
- S3: `from src.services.s3_upload import _upload_bytes_to_s3`, `from src.services.s3_service import get_public_url`
- Авторизация в тестах: `from src.services.auth_service import create_access_token` → `create_access_token({'sub': str(uid), 'role': role})`
- БД: `from src.database import get_db, AsyncSessionLocal`; `from src.dependencies import get_current_user`; `from src.models.user import ValidatorUser, UserRole`
- Кол-во паков: `from src.services.schemes_service import get_min_required_schemes` (= `COUNT(*) FROM factory_pack_accounts WHERE project_id`)
- In-process тест-клиент: `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')`

**Запуск тестов:** из `backend/`: `pytest tests/<file>::<test> -v`. Фронт из `frontend/`: `npx vitest run <file>`.

---

## Phase 1 — Данные

### Task 1: Миграция 010 — таблицы logo_variants / logo_selections / logo_generation_tasks

**Files:**
- Create: `backend/alembic/versions/010_wp137_logo_variants.py`
- Test: `backend/tests/test_wp137_logo_variants_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_logo_variants_migration.py
"""Smoke: таблицы WP#137 существуют и принимают вставку (миграция 010 применена)."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal

PID = 100137


@pytest_asyncio.fixture
async def _cleanup():
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM logo_selections WHERE project_id=:p"), {"p": PID})
        await db.execute(text("DELETE FROM logo_variants WHERE project_id=:p"), {"p": PID})
        await db.execute(text("DELETE FROM logo_generation_tasks WHERE project_id=:p"), {"p": PID})
        await db.commit()


@pytest.mark.asyncio
async def test_logo_tables_exist_and_insert(_cleanup):
    async with AsyncSessionLocal() as db:
        vid = (await db.execute(text("""
            INSERT INTO logo_variants
              (project_id, logo_source_hash, prompt_template_version, variant_index, status, ttl_at)
            VALUES (:p, 'h1', 1, 0, 'done', NOW() + INTERVAL '30 days')
            RETURNING id
        """), {"p": PID})).scalar_one()
        await db.execute(text("""
            INSERT INTO logo_selections (project_id, variant_id, selected_by)
            VALUES (:p, :v, 1)
        """), {"p": PID, "v": vid})
        await db.execute(text("""
            INSERT INTO logo_generation_tasks
              (project_id, logo_source_hash, prompt_template_version, status, total)
            VALUES (:p, 'h1', 1, 'pending', 10)
        """), {"p": PID})
        await db.commit()

        # дедуп-констрейнт на variant
        with pytest.raises(Exception):
            await db.execute(text("""
                INSERT INTO logo_variants
                  (project_id, logo_source_hash, prompt_template_version, variant_index, status)
                VALUES (:p, 'h1', 1, 0, 'pending')
            """), {"p": PID})
            await db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_logo_variants_migration.py -v`
Expected: FAIL — `relation "logo_variants" does not exist`.

- [ ] **Step 3: Write the migration**

```python
# backend/alembic/versions/010_wp137_logo_variants.py
"""WP #137: таблицы уникализации лого — logo_variants / logo_selections / logo_generation_tasks

Revision ID: 010
Revises: 009
Create Date: 2026-06-03
"""
from alembic import op

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS logo_variants (
            id                       bigserial PRIMARY KEY,
            project_id               integer     NOT NULL,
            logo_source_hash         text        NOT NULL,
            prompt_template_version  integer     NOT NULL,
            variant_index            integer     NOT NULL,
            s3_url                   text,
            status                   text        NOT NULL DEFAULT 'pending',
            model_used               text,
            created_at               timestamptz NOT NULL DEFAULT now(),
            ttl_at                   timestamptz
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_logo_variants_dedup
            ON logo_variants (project_id, logo_source_hash, prompt_template_version, variant_index);
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_logo_variants_project ON logo_variants (project_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_logo_variants_ttl ON logo_variants (ttl_at) WHERE ttl_at IS NOT NULL;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS logo_selections (
            id           bigserial PRIMARY KEY,
            project_id   integer     NOT NULL,
            variant_id   bigint      NOT NULL REFERENCES logo_variants(id) ON DELETE CASCADE,
            selected_at  timestamptz NOT NULL DEFAULT now(),
            selected_by  integer
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_logo_selections_project_variant
            ON logo_selections (project_id, variant_id);
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_logo_selections_project ON logo_selections (project_id);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS logo_generation_tasks (
            id                       bigserial PRIMARY KEY,
            project_id               integer     NOT NULL,
            logo_source_hash         text        NOT NULL,
            prompt_template_version  integer     NOT NULL,
            status                   text        NOT NULL DEFAULT 'pending',
            total                    integer     NOT NULL,
            done                     integer     NOT NULL DEFAULT 0,
            error_count              integer     NOT NULL DEFAULT 0,
            error_message            text,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_logo_gen_tasks_polling ON logo_generation_tasks (status, id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_logo_gen_tasks_project ON logo_generation_tasks (project_id, id DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS logo_selections;")
    op.execute("DROP TABLE IF EXISTS logo_generation_tasks;")
    op.execute("DROP TABLE IF EXISTS logo_variants;")
```

- [ ] **Step 4: Apply migration and run test**

Run: `cd backend && alembic upgrade head && pytest tests/test_wp137_logo_variants_migration.py -v`
Expected: PASS (3 таблицы, дедуп-констрейнт срабатывает).

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/010_wp137_logo_variants.py backend/tests/test_wp137_logo_variants_migration.py
git commit -m "feat(wp137): миграция 010 — таблицы logo_variants/logo_selections/logo_generation_tasks"
```

---

## Phase 2 — Конфиг и промты

### Task 2: Настройки (kill-switch'и, провайдер, TTL)

**Files:**
- Modify: `backend/src/config.py` (добавить поля в класс `Settings`, после блока `scheme_preview_progress_clamp_enabled`)
- Test: `backend/tests/test_wp137_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_settings.py
from src.config import settings


def test_wp137_settings_defaults():
    assert settings.logo_variants_generation_enabled is False  # kill-switch default OFF
    assert settings.logo_variant_gate_enabled is False
    assert settings.logo_prompt_template_version == 1
    assert settings.logo_image_model == "gpt-image-1"
    assert settings.logo_variant_ttl_days == 30
    assert settings.logo_card_size == 900
    # тип/наличие
    assert isinstance(settings.logo_image_timeout_s, float)
    assert hasattr(settings, "logo_image_api_url")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'logo_variants_generation_enabled'`.

- [ ] **Step 3: Add settings**

В `backend/src/config.py`, внутри класса `Settings`, сразу после строк про `scheme_preview_progress_clamp_enabled` (перед `class Config:`):

```python
    # WP#137: уникализация лого клиента
    logo_variants_generation_enabled: bool = False   # master kill-switch генерации
    logo_variant_gate_enabled: bool = False           # гейт перехода к схемам (читается фронтом)
    logo_prompt_template_version: int = 1
    logo_image_model: str = "gpt-image-1"
    logo_image_api_url: str = ""                       # Laozhang images/edits endpoint (HTTPS)
    logo_image_timeout_s: float = 60.0
    logo_variant_ttl_days: int = 30
    logo_card_size: int = 900                          # px, квадрат карточки
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_wp137_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/config.py backend/tests/test_wp137_settings.py
git commit -m "feat(wp137): настройки генерации лого + kill-switch'и"
```

---

### Task 3: Версионированные промты

**Files:**
- Create: `backend/src/services/logo_prompts.py`
- Test: `backend/tests/test_wp137_logo_prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_logo_prompts.py
from src.services.logo_prompts import build_prompts, LOGO_PROMPT_VERSION


def test_build_prompts_returns_requested_count_and_unique():
    prompts = build_prompts(version=LOGO_PROMPT_VERSION, count=10)
    assert len(prompts) == 10
    assert len(set(prompts)) == 10          # все варианты разные (разный фон/оформление)
    assert all("900" in p for p in prompts)  # размер из промта Ани
    assert all("прозрач" in p.lower() for p in prompts)


def test_build_prompts_count_more_than_themes_cycles_with_suffix():
    prompts = build_prompts(version=LOGO_PROMPT_VERSION, count=15)
    assert len(prompts) == 15
    assert len(set(prompts)) == 15           # уникальность держится даже при cycle


def test_unknown_version_raises():
    import pytest
    with pytest.raises(ValueError):
        build_prompts(version=999, count=5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_logo_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.logo_prompts'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/services/logo_prompts.py
"""Версионированные промты для генерации вариантов лого (WP#137).

Базовый промт — тот, что вручную использует Аня. Варьируем фон/оформление
между вариантами. Версия пишется в logo_variants.prompt_template_version и
участвует в дедуп-ключе: смена версии → новая генерация.
"""
from __future__ import annotations

LOGO_PROMPT_VERSION = 1

_BASE = (
    "Вот логотип. Сделай маленькую PNG-карточку 900x900: логотип по центру "
    "без лишнего увеличения, со скруглёнными углами подложки, прозрачный фон "
    "вокруг карточки. Вес 200-500 КБ. "
)

# Темы фона/оформления — каждая даёт визуально отличный вариант.
_THEMES_V1 = [
    "Фон: мягкий вертикальный градиент в фирменных тонах логотипа.",
    "Фон: однотонный пастельный, лёгкая тень под логотипом.",
    "Фон: тёмный благородный с деликатным свечением вокруг логотипа.",
    "Фон: светлый с тонким геометрическим паттерном.",
    "Фон: диагональный двухцветный градиент.",
    "Фон: матовый бумажный текстурный, нейтральный.",
    "Фон: яркий контрастный акцентный цвет, минимализм.",
    "Фон: размытое боке в тёплых тонах.",
    "Фон: холодный градиент сине-фиолетовый.",
    "Фон: чистый белый, аккуратная тонкая рамка карточки.",
]

_THEMES_BY_VERSION = {1: _THEMES_V1}


def build_prompts(version: int, count: int) -> list[str]:
    """Вернуть `count` уникальных промтов для указанной версии.

    Если count > числа тем — циклически повторяем темы с числовым суффиксом
    («вариация N»), сохраняя уникальность строк.
    """
    themes = _THEMES_BY_VERSION.get(version)
    if themes is None:
        raise ValueError(f"Неизвестная версия промтов: {version}")
    out: list[str] = []
    for i in range(count):
        theme = themes[i % len(themes)]
        cycle = i // len(themes)
        suffix = "" if cycle == 0 else f" Вариация {cycle + 1}."
        out.append(_BASE + theme + suffix)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_wp137_logo_prompts.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/logo_prompts.py backend/tests/test_wp137_logo_prompts.py
git commit -m "feat(wp137): версионированные промты вариантов лого"
```

---

## Phase 3 — Сервис генерации изображений

### Task 4: Пост-обработка карточки (Pillow)

**Files:**
- Create: `backend/src/services/logo_image.py`
- Test: `backend/tests/test_wp137_logo_image.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_logo_image.py
import io
from PIL import Image
from src.services.logo_image import postprocess_to_card


def _solid_png(w=512, h=300, color=(120, 40, 200, 255)) -> bytes:
    img = Image.new("RGBA", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_postprocess_outputs_square_rgba_900():
    out = postprocess_to_card(_solid_png(), size=900)
    img = Image.open(io.BytesIO(out))
    assert img.size == (900, 900)
    assert img.mode == "RGBA"


def test_corners_are_transparent():
    out = postprocess_to_card(_solid_png(), size=900)
    img = Image.open(io.BytesIO(out)).convert("RGBA")
    # угловой пиксель (поле вокруг скруглённой карточки) должен быть прозрачным
    assert img.getpixel((0, 0))[3] == 0
    # центр — непрозрачный
    assert img.getpixel((450, 450))[3] == 255


def test_weight_within_budget():
    out = postprocess_to_card(_solid_png(), size=900)
    assert len(out) <= 500 * 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_logo_image.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.logo_image'`.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/services/logo_image.py
"""Пост-обработка сгенерированной картинки в карточку-вариант лого (WP#137).

Приводит вывод image-модели к требованиям ТЗ независимо от того, что вернула
модель: квадрат size×size, скруглённые углы → прозрачные поля вокруг карточки,
вес в диапазоне 200-500 КБ.
"""
from __future__ import annotations

import io
from PIL import Image, ImageDraw

_MAX_BYTES = 500 * 1024
_MARGIN_RATIO = 0.04   # прозрачное поле вокруг карточки
_RADIUS_RATIO = 0.10   # радиус скругления относительно стороны карточки


def _rounded_mask(side: int, radius: int) -> Image.Image:
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, side - 1, side - 1), radius=radius, fill=255)
    return mask


def postprocess_to_card(png_bytes: bytes, size: int = 900) -> bytes:
    """Вернуть PNG size×size RGBA: карточка со скруглёнными углами, прозрачные поля, ≤500КБ."""
    src = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

    # 1) Вписать в квадрат card_side (с учётом прозрачного поля) по центру (cover-crop).
    margin = int(size * _MARGIN_RATIO)
    card_side = size - 2 * margin
    sw, sh = src.size
    scale = max(card_side / sw, card_side / sh)
    new = src.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)
    left = (new.width - card_side) // 2
    top = (new.height - card_side) // 2
    card = new.crop((left, top, left + card_side, top + card_side))

    # 2) Скруглить углы карточки (вне радиуса → прозрачно).
    radius = int(card_side * _RADIUS_RATIO)
    card.putalpha(_rounded_mask(card_side, radius))

    # 3) Положить на полностью прозрачный холст size×size с полем.
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(card, (margin, margin), card)

    # 4) Сериализовать в PNG; если вес >500КБ — даунскейлить и пере-сохранять.
    out_side = size
    while True:
        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        if len(data) <= _MAX_BYTES or out_side <= 400:
            return data
        out_side = int(out_side * 0.85)
        canvas = canvas.resize((out_side, out_side), Image.LANCZOS)
```

> Примечание: Pillow уже в зависимостях (используется в `svg_raster`). Если нет — добавить `Pillow` в `backend/requirements.txt` в этом же коммите.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_wp137_logo_image.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/logo_image.py backend/tests/test_wp137_logo_image.py
git commit -m "feat(wp137): пост-обработка карточки лого (900x900, скругление, прозрачность, ≤500КБ)"
```

---

### Task 5: Хеш источника + генерация одного варианта (Laozhang)

**Files:**
- Create: `backend/src/services/logo_variant_service.py`
- Test: `backend/tests/test_wp137_logo_variant_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_logo_variant_service.py
import io
import pytest
from PIL import Image
from src.services import logo_variant_service as svc


def _png(color=(10, 20, 30, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (300, 300), color).save(buf, format="PNG")
    return buf.getvalue()


def test_source_hash_stable_and_distinct():
    a = svc.compute_logo_source_hash(b"abc")
    assert a == svc.compute_logo_source_hash(b"abc")
    assert a != svc.compute_logo_source_hash(b"abd")


@pytest.mark.asyncio
async def test_generate_one_variant_calls_model_and_postprocesses(monkeypatch):
    # модель возвращает «сырой» PNG, сервис должен прогнать через postprocess
    async def fake_call(logo_bytes, prompt):
        return _png()
    monkeypatch.setattr(svc, "_call_image_model", fake_call)

    out = await svc.generate_one_variant(_png(), "prompt", size=900)
    img = Image.open(io.BytesIO(out))
    assert img.size == (900, 900)
    assert img.getpixel((0, 0))[3] == 0   # прозрачный угол (postprocess применён)


@pytest.mark.asyncio
async def test_fetch_logo_bytes_http(monkeypatch):
    async def fake_get(url):
        return _png()
    monkeypatch.setattr(svc, "_http_get_bytes", fake_get)
    data = await svc.fetch_logo_bytes("http://example/logo.png")
    assert data and isinstance(data, bytes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_logo_variant_service.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/services/logo_variant_service.py
"""Генерация одного варианта лого: хеш источника, вызов image-модели, пост-обработка.

Провайдер — Laozhang (OpenAI-совместимый images/edits), модель gpt-image-1:
вход = байты лого + промт. Ответ (b64) → PNG → postprocess_to_card.
Сетевые/модельные детали изолированы в _call_image_model / _http_get_bytes,
чтобы их мокать в тестах.
"""
from __future__ import annotations

import base64
import hashlib
import logging

import httpx

from ..config import settings
from .logo_image import postprocess_to_card

log = logging.getLogger(__name__)


def compute_logo_source_hash(logo_bytes: bytes) -> str:
    return hashlib.sha256(logo_bytes).hexdigest()


async def _http_get_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=settings.logo_image_timeout_s) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def fetch_logo_bytes(logo_url: str) -> bytes:
    if not logo_url:
        raise ValueError("logo_url пуст")
    return await _http_get_bytes(logo_url)


async def _call_image_model(logo_bytes: bytes, prompt: str) -> bytes:
    """Вызов Laozhang images/edits (gpt-image-1). Возвращает сырые PNG-байты.

    Фолбэк: если edits недоступен (404/400) — пробуем generations с тем же
    промтом (без image-edit). На этапе реализации проверить точный путь edits
    у Laozhang; logo_image_api_url задаёт endpoint.
    """
    if not (settings.laozhang_api_key and settings.logo_image_api_url):
        raise RuntimeError("Laozhang не сконфигурирован (laozhang_api_key / logo_image_api_url)")

    headers = {"Authorization": f"Bearer {settings.laozhang_api_key}"}
    async with httpx.AsyncClient(timeout=settings.logo_image_timeout_s) as client:
        resp = await client.post(
            settings.logo_image_api_url,
            headers=headers,
            data={"model": settings.logo_image_model, "prompt": prompt, "size": "1024x1024"},
            files={"image": ("logo.png", logo_bytes, "image/png")},
        )
        resp.raise_for_status()
        payload = resp.json()
    b64 = payload["data"][0]["b64_json"]
    return base64.b64decode(b64)


async def generate_one_variant(logo_bytes: bytes, prompt: str, size: int | None = None) -> bytes:
    """Сгенерировать один вариант: модель → постобработка в карточку. Вернуть PNG-байты."""
    size = size or settings.logo_card_size
    raw = await _call_image_model(logo_bytes, prompt)
    return postprocess_to_card(raw, size=size)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_wp137_logo_variant_service.py -v`
Expected: PASS (4 теста).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/logo_variant_service.py backend/tests/test_wp137_logo_variant_service.py
git commit -m "feat(wp137): сервис генерации варианта лого (Laozhang gpt-image-1 + postprocess)"
```

---

## Phase 4 — Очередь и воркер

### Task 6: Очередь генерации (enqueue/status/required-counts)

**Files:**
- Create: `backend/src/services/logo_generation_queue.py`
- Test: `backend/tests/test_wp137_logo_queue.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_logo_queue.py
import pytest
import pytest_asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal
from src.services import logo_generation_queue as q

PID = 100138


@pytest_asyncio.fixture
async def _clean():
    async def wipe():
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM logo_selections WHERE project_id=:p"), {"p": PID})
            await db.execute(text("DELETE FROM logo_variants WHERE project_id=:p"), {"p": PID})
            await db.execute(text("DELETE FROM logo_generation_tasks WHERE project_id=:p"), {"p": PID})
            await db.commit()
    await wipe(); yield; await wipe()


@pytest.mark.asyncio
async def test_compute_counts_fallback_when_no_packs(_clean):
    async with AsyncSessionLocal() as db:
        counts = await q.compute_counts(PID, db)   # у тестового проекта нет паков
    assert counts == {"required": 5, "total_to_generate": 10}


@pytest.mark.asyncio
async def test_enqueue_is_idempotent(_clean):
    async with AsyncSessionLocal() as db:
        r1 = await q.enqueue(db, PID, logo_source_hash="h", version=1, total=10)
        await db.commit()
    async with AsyncSessionLocal() as db:
        r2 = await q.enqueue(db, PID, logo_source_hash="h", version=1, total=10)
        await db.commit()
    assert r1["task_id"] == r2["task_id"]
    assert r2["joined_existing"] is True


@pytest.mark.asyncio
async def test_read_status_maps_progress(_clean):
    async with AsyncSessionLocal() as db:
        await q.enqueue(db, PID, logo_source_hash="h", version=1, total=10)
        await db.commit()
    async with AsyncSessionLocal() as db:
        st = await q.read_status(db, PID)
    assert st["status"] in ("running", "pending")
    assert st["total"] == 10
    assert st["done"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_logo_queue.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/services/logo_generation_queue.py
"""Очередь генерации вариантов лого (WP#137): подсчёт required/total, enqueue с дедупом,
чтение статуса, atomic claim для воркера.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .schemes_service import get_min_required_schemes

_ACTIVE = ("pending", "processing")


async def compute_counts(project_id: int, db: AsyncSession) -> dict:
    """required = число паков; total = required + 5. Fallback (нет паков): 5 / 10."""
    pack_count = await get_min_required_schemes(project_id, db)
    if pack_count and pack_count > 0:
        return {"required": int(pack_count), "total_to_generate": int(pack_count) + 5}
    return {"required": 5, "total_to_generate": 10}


async def enqueue(db: AsyncSession, project_id: int, logo_source_hash: str,
                  version: int, total: int) -> dict:
    """Idempotent enqueue. Дедуп: активная задача с тем же (project, hash, version).

    Возвращает {task_id, status:'queued', joined_existing: bool, total}.
    """
    await db.execute(text(
        "SELECT pg_advisory_xact_lock(hashtext('logo_gen_enqueue:' || :p))"
    ), {"p": str(project_id)})

    existing = (await db.execute(text("""
        SELECT id, total FROM logo_generation_tasks
         WHERE project_id=:p AND logo_source_hash=:h AND prompt_template_version=:v
           AND status = ANY(:active)
         ORDER BY id DESC LIMIT 1
    """), {"p": project_id, "h": logo_source_hash, "v": version, "active": list(_ACTIVE)})).mappings().first()
    if existing:
        return {"task_id": int(existing["id"]), "status": "queued",
                "joined_existing": True, "total": int(existing["total"])}

    row = (await db.execute(text("""
        INSERT INTO logo_generation_tasks
          (project_id, logo_source_hash, prompt_template_version, status, total, done, created_at, updated_at)
        VALUES (:p, :h, :v, 'pending', :total, 0, NOW(), NOW())
        RETURNING id
    """), {"p": project_id, "h": logo_source_hash, "v": version, "total": total})).mappings().first()
    return {"task_id": int(row["id"]), "status": "queued", "joined_existing": False, "total": total}


async def read_status(db: AsyncSession, project_id: int) -> dict | None:
    """Свежайшая задача проекта. status: running|done|error (legacy alias для фронта)."""
    row = (await db.execute(text("""
        SELECT id, status, total, done, error_count, error_message
          FROM logo_generation_tasks
         WHERE project_id=:p ORDER BY id DESC LIMIT 1
    """), {"p": project_id})).mappings().first()
    if not row:
        return None
    db_status = row["status"]
    if db_status in ("pending", "processing"):
        legacy = "running"
    elif db_status in ("done", "partial"):
        legacy = "done"
    else:
        legacy = "error"
    return {"task_id": int(row["id"]), "status": legacy, "db_status": db_status,
            "total": int(row["total"]), "done": int(row["done"]),
            "errors": int(row["error_count"]), "error": row["error_message"]}


async def claim_next_pending(db: AsyncSession) -> dict | None:
    """Атомарно взять одну pending-задачу → processing (SKIP LOCKED). Для воркера."""
    row = (await db.execute(text("""
        UPDATE logo_generation_tasks SET status='processing', updated_at=NOW()
         WHERE id = (
            SELECT id FROM logo_generation_tasks
             WHERE status='pending'
             ORDER BY id ASC FOR UPDATE SKIP LOCKED LIMIT 1
         )
        RETURNING id, project_id, logo_source_hash, prompt_template_version, total, done
    """))).mappings().first()
    return dict(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_wp137_logo_queue.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/logo_generation_queue.py backend/tests/test_wp137_logo_queue.py
git commit -m "feat(wp137): очередь генерации лого (counts/enqueue/status/claim)"
```

---

### Task 7: Процессор задачи (генерация → S3 → строки вариантов)

**Files:**
- Create: `backend/src/services/logo_variant_processor.py`
- Test: `backend/tests/test_wp137_logo_processor.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_logo_processor.py
import io
import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import text
from src.database import AsyncSessionLocal
from src.services import logo_variant_processor as proc
from src.services import logo_variant_service as svc
from src.services import logo_generation_queue as q

PID = 100139


def _png():
    buf = io.BytesIO(); Image.new("RGBA", (300, 300), (1, 2, 3, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest_asyncio.fixture
async def _clean():
    async def wipe():
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM logo_selections WHERE project_id=:p"), {"p": PID})
            await db.execute(text("DELETE FROM logo_variants WHERE project_id=:p"), {"p": PID})
            await db.execute(text("DELETE FROM logo_generation_tasks WHERE project_id=:p"), {"p": PID})
            await db.commit()
    await wipe(); yield; await wipe()


@pytest.mark.asyncio
async def test_process_task_creates_variants_and_marks_done(_clean, monkeypatch):
    # мок модели и S3
    async def _png_async(*a, **k): return _png()
    monkeypatch.setattr(svc, "_call_image_model", _png_async)
    monkeypatch.setattr(svc, "fetch_logo_bytes", _png_async)
    uploaded = []
    async def fake_upload(data, key, ctype, *, context): uploaded.append(key)
    monkeypatch.setattr(proc, "_upload_bytes_to_s3", fake_upload)
    monkeypatch.setattr(proc, "get_public_url", lambda key: f"https://s3/{key}")

    async with AsyncSessionLocal() as db:
        r = await q.enqueue(db, PID, logo_source_hash="h", version=1, total=3)
        await db.commit()
        task = await q.claim_next_pending(db)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await proc.process_task(db, task, logo_url="http://x/logo.png")
        await db.commit()

    async with AsyncSessionLocal() as db:
        cnt = (await db.execute(text(
            "SELECT COUNT(*) FROM logo_variants WHERE project_id=:p AND status='done'"
        ), {"p": PID})).scalar_one()
        st = await q.read_status(db, PID)
    assert cnt == 3
    assert len(uploaded) == 3
    assert st["db_status"] == "done"
    assert st["done"] == 3


@pytest.mark.asyncio
async def test_process_task_partial_on_model_error(_clean, monkeypatch):
    calls = {"n": 0}
    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("model boom")
        return _png()
    async def png_async(*a, **k): return _png()
    monkeypatch.setattr(svc, "_call_image_model", flaky)
    monkeypatch.setattr(svc, "fetch_logo_bytes", png_async)
    async def fake_upload(data, key, ctype, *, context): return None
    monkeypatch.setattr(proc, "_upload_bytes_to_s3", fake_upload)
    monkeypatch.setattr(proc, "get_public_url", lambda key: f"https://s3/{key}")

    async with AsyncSessionLocal() as db:
        await q.enqueue(db, PID, logo_source_hash="h", version=1, total=3)
        await db.commit()
        task = await q.claim_next_pending(db); await db.commit()
    async with AsyncSessionLocal() as db:
        await proc.process_task(db, task, logo_url="http://x/logo.png"); await db.commit()
    async with AsyncSessionLocal() as db:
        st = await q.read_status(db, PID)
    assert st["db_status"] == "partial"
    assert st["done"] == 2
    assert st["errors"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_logo_processor.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/services/logo_variant_processor.py
"""Обработка одной logo_generation_task: генерируем недостающие variant_index,
грузим в S3, пишем logo_variants инкрементально, ставим финальный статус.

Резюмируемость: уже существующие done-варианты (project, hash, version, index)
пропускаются (ON CONFLICT DO NOTHING + проверка). Частичный успех → 'partial'.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from .s3_upload import _upload_bytes_to_s3
from .s3_service import get_public_url
from .logo_prompts import build_prompts
from . import logo_variant_service as svc

log = logging.getLogger(__name__)


async def _existing_done_indexes(db: AsyncSession, project_id: int, h: str, v: int) -> set[int]:
    rows = (await db.execute(text("""
        SELECT variant_index FROM logo_variants
         WHERE project_id=:p AND logo_source_hash=:h AND prompt_template_version=:v AND status='done'
    """), {"p": project_id, "h": h, "v": v})).scalars().all()
    return set(int(x) for x in rows)


async def process_task(db: AsyncSession, task: dict, logo_url: str) -> None:
    pid = int(task["project_id"]); h = task["logo_source_hash"]
    v = int(task["prompt_template_version"]); total = int(task["total"])

    prompts = build_prompts(version=v, count=total)
    logo_bytes = await svc.fetch_logo_bytes(logo_url)
    done_idx = await _existing_done_indexes(db, pid, h, v)
    done = len(done_idx)
    errors = 0
    ttl_days = settings.logo_variant_ttl_days

    for i in range(total):
        if i in done_idx:
            continue
        try:
            png = await svc.generate_one_variant(logo_bytes, prompts[i])
            key = f"logo-variants/{pid}/{h}/{v}/{i}_{uuid.uuid4().hex}.png"
            await _upload_bytes_to_s3(png, key, "image/png", context="wp137/logo-variant")
            url = get_public_url(key)
            await db.execute(text("""
                INSERT INTO logo_variants
                  (project_id, logo_source_hash, prompt_template_version, variant_index,
                   s3_url, status, model_used, created_at, ttl_at)
                VALUES (:p, :h, :v, :i, :url, 'done', :model, NOW(), NOW() + (:days || ' days')::interval)
                ON CONFLICT (project_id, logo_source_hash, prompt_template_version, variant_index)
                DO UPDATE SET s3_url=EXCLUDED.s3_url, status='done', model_used=EXCLUDED.model_used,
                              ttl_at=EXCLUDED.ttl_at
            """), {"p": pid, "h": h, "v": v, "i": i, "url": url,
                   "model": settings.logo_image_model, "days": str(ttl_days)})
            done += 1
        except Exception as e:  # частичный успех допустим
            errors += 1
            log.warning("[wp137] variant gen failed project_id=%s idx=%s model=%s reason=%s",
                        pid, i, settings.logo_image_model, e)
        await db.execute(text("""
            UPDATE logo_generation_tasks SET done=:d, error_count=:e, updated_at=NOW() WHERE id=:tid
        """), {"d": done, "e": errors, "tid": int(task["id"])})
        await db.commit()

    final = "done" if done >= total else ("partial" if done > 0 else "failed")
    await db.execute(text("""
        UPDATE logo_generation_tasks SET status=:s, done=:d, error_count=:e, updated_at=NOW(),
               error_message = CASE WHEN :s='failed' THEN 'all variants failed' ELSE NULL END
         WHERE id=:tid
    """), {"s": final, "d": done, "e": errors, "tid": int(task["id"])})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_wp137_logo_processor.py -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/logo_variant_processor.py backend/tests/test_wp137_logo_processor.py
git commit -m "feat(wp137): процессор задачи генерации (генерация→S3→logo_variants, partial-tolerant)"
```

---

### Task 8: Фоновый loop в lifespan (воркер + TTL-очистка)

**Files:**
- Create: `backend/src/services/logo_background.py`
- Modify: `backend/src/main.py` (старт/стоп таски в `lifespan`)
- Test: `backend/tests/test_wp137_logo_background.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_logo_background.py
import pytest
import pytest_asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal
from src.services import logo_background as bg

PID = 100140


@pytest_asyncio.fixture
async def _clean():
    async def wipe():
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM logo_selections WHERE project_id=:p"), {"p": PID})
            await db.execute(text("DELETE FROM logo_variants WHERE project_id=:p"), {"p": PID})
            await db.commit()
    await wipe(); yield; await wipe()


@pytest.mark.asyncio
async def test_ttl_cleanup_deletes_expired_unselected_keeps_selected(_clean):
    async with AsyncSessionLocal() as db:
        # истёкший невыбранный — удалить
        await db.execute(text("""
            INSERT INTO logo_variants (project_id, logo_source_hash, prompt_template_version,
                variant_index, status, ttl_at)
            VALUES (:p,'h',1,0,'done', NOW() - INTERVAL '1 day')
        """), {"p": PID})
        # истёкший, но ВЫБРАННЫЙ (ttl_at NULL) — оставить
        sel_id = (await db.execute(text("""
            INSERT INTO logo_variants (project_id, logo_source_hash, prompt_template_version,
                variant_index, status, ttl_at)
            VALUES (:p,'h',1,1,'done', NULL) RETURNING id
        """), {"p": PID})).scalar_one()
        await db.execute(text(
            "INSERT INTO logo_selections (project_id, variant_id, selected_by) VALUES (:p,:v,1)"
        ), {"p": PID, "v": sel_id})
        await db.commit()

    async with AsyncSessionLocal() as db:
        deleted = await bg.run_ttl_cleanup(db)
        await db.commit()

    async with AsyncSessionLocal() as db:
        remaining = (await db.execute(text(
            "SELECT COUNT(*) FROM logo_variants WHERE project_id=:p"
        ), {"p": PID})).scalar_one()
    assert deleted >= 1
    assert remaining == 1   # выбранный остался
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_logo_background.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/services/logo_background.py
"""Фоновый loop WP#137: обработка очереди генерации + суточная TTL-очистка.

Запускается в FastAPI lifespan как asyncio.Task. Гейтится kill-switch'ем
logo_variants_generation_enabled (генерация). TTL-очистка идёт всегда.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import AsyncSessionLocal
from . import logo_generation_queue as q
from . import logo_variant_processor as proc

log = logging.getLogger(__name__)

_POLL_INTERVAL_S = 5
_TTL_INTERVAL_S = 24 * 3600


async def run_ttl_cleanup(db: AsyncSession) -> int:
    """Удалить истёкшие невыбранные варианты. Вернуть число удалённых."""
    res = await db.execute(text("""
        DELETE FROM logo_variants lv
         WHERE lv.ttl_at IS NOT NULL AND lv.ttl_at < NOW()
           AND NOT EXISTS (SELECT 1 FROM logo_selections ls WHERE ls.variant_id = lv.id)
    """))
    return res.rowcount or 0


async def _process_one_pending() -> bool:
    """Взять одну pending-задачу и обработать. Вернуть True если что-то взяли."""
    async with AsyncSessionLocal() as db:
        task = await q.claim_next_pending(db)
        await db.commit()
        if not task:
            return False
        # logo_url проекта
        logo_url = (await db.execute(text(
            "SELECT logo_url FROM validator_projects WHERE id=:p"
        ), {"p": task["project_id"]})).scalar_one_or_none()
    async with AsyncSessionLocal() as db2:
        try:
            await proc.process_task(db2, task, logo_url=logo_url or "")
            await db2.commit()
        except Exception as e:
            log.warning("[wp137] task %s crashed: %s", task["id"], e)
            await db2.execute(text(
                "UPDATE logo_generation_tasks SET status='failed', error_message=:m, updated_at=NOW() WHERE id=:t"
            ), {"m": str(e)[:500], "t": task["id"]})
            await db2.commit()
    return True


async def loop(stop: asyncio.Event) -> None:
    last_ttl = 0.0
    elapsed = 0.0
    while not stop.is_set():
        try:
            if settings.logo_variants_generation_enabled:
                # дренируем все pending за тик
                while await _process_one_pending():
                    pass
            if elapsed - last_ttl >= _TTL_INTERVAL_S or last_ttl == 0.0:
                async with AsyncSessionLocal() as db:
                    n = await run_ttl_cleanup(db)
                    await db.commit()
                if n:
                    log.info("[wp137] TTL cleanup удалил %s вариантов", n)
                last_ttl = elapsed
        except Exception as e:
            log.warning("[wp137] background loop error: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=_POLL_INTERVAL_S)
        except asyncio.TimeoutError:
            pass
        elapsed += _POLL_INTERVAL_S
```

- [ ] **Step 4: Wire into lifespan**

В `backend/src/main.py`: вверху добавить `import asyncio` (если нет). Внутри `lifespan`, перед `yield`, добавить:

```python
    # WP#137: фоновый воркер генерации лого + TTL
    from .services import logo_background
    _logo_stop = asyncio.Event()
    _logo_task = asyncio.create_task(logo_background.loop(_logo_stop))
```

После `yield` (перед `await engine.dispose()`):

```python
    _logo_stop.set()
    try:
        await asyncio.wait_for(_logo_task, timeout=10)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        _logo_task.cancel()
```

- [ ] **Step 5: Run test + import-smoke**

Run: `cd backend && pytest tests/test_wp137_logo_background.py -v && python -c "import src.main"`
Expected: PASS + импорт без ошибок.

- [ ] **Step 6: Commit**

```bash
git add backend/src/services/logo_background.py backend/src/main.py backend/tests/test_wp137_logo_background.py
git commit -m "feat(wp137): фоновый loop генерации лого + TTL-очистка в lifespan"
```

---

## Phase 5 — Роутер

### Task 9: Роутер /api/logo-variants/* (readiness/generate/select/retry/reset)

**Files:**
- Create: `backend/src/routers/logo_variants.py`
- Modify: `backend/src/main.py` (импорт + `include_router`)
- Test: `backend/tests/test_wp137_logo_router.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wp137_logo_router.py
import pytest
import pytest_asyncio
import httpx
from sqlalchemy import text
from src.main import app
from src.database import AsyncSessionLocal
from src.services.auth_service import create_access_token

PID = 100141


@pytest_asyncio.fixture
async def admin_token():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT id, role FROM validator_users WHERE login='admin' AND is_active LIMIT 1"
        ))).mappings().first()
        if not row:
            pytest.skip("admin не найден")
        return f"Bearer {create_access_token({'sub': str(row['id']), 'role': row['role']})}"


@pytest_asyncio.fixture
async def _clean():
    async def wipe():
        async with AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM logo_selections WHERE project_id=:p"), {"p": PID})
            await db.execute(text("DELETE FROM logo_variants WHERE project_id=:p"), {"p": PID})
            await db.execute(text("DELETE FROM logo_generation_tasks WHERE project_id=:p"), {"p": PID})
            await db.commit()
    await wipe(); yield; await wipe()


@pytest.mark.asyncio
async def test_readiness_shape(admin_token, _clean):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/logo-variants/readiness?project_id={PID}",
                        headers={"Authorization": admin_token})
    assert r.status_code == 200
    data = r.json()
    for k in ("has_logo", "required", "total_to_generate", "generation", "variants", "selected_ids", "gate_enabled"):
        assert k in data
    assert data["required"] == 5 and data["total_to_generate"] == 10  # нет паков → fallback


@pytest.mark.asyncio
async def test_select_validates_count(admin_token, _clean):
    # подложим 6 готовых вариантов, required=5 → выбор 3 должен упасть, 5 — пройти
    async with AsyncSessionLocal() as db:
        ids = []
        for i in range(6):
            vid = (await db.execute(text("""
                INSERT INTO logo_variants (project_id, logo_source_hash, prompt_template_version,
                    variant_index, status, s3_url, ttl_at)
                VALUES (:p,'h',1,:i,'done',:u, NOW()+INTERVAL '30 days') RETURNING id
            """), {"p": PID, "i": i, "u": f"https://s3/v{i}.png"})).scalar_one()
            ids.append(vid)
        await db.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        bad = await c.post("/api/logo-variants/select",
                           headers={"Authorization": admin_token},
                           json={"project_id": PID, "variant_ids": ids[:3]})
        assert bad.status_code == 400
        ok = await c.post("/api/logo-variants/select",
                          headers={"Authorization": admin_token},
                          json={"project_id": PID, "variant_ids": ids[:5]})
        assert ok.status_code == 200

    async with AsyncSessionLocal() as db:
        cnt = (await db.execute(text(
            "SELECT COUNT(*) FROM logo_selections WHERE project_id=:p"
        ), {"p": PID})).scalar_one()
        # выбранные обнулили ttl_at
        nulls = (await db.execute(text(
            "SELECT COUNT(*) FROM logo_variants WHERE id = ANY(:ids) AND ttl_at IS NULL"
        ), {"ids": ids[:5]})).scalar_one()
    assert cnt == 5 and nulls == 5


@pytest.mark.asyncio
async def test_generate_killswitch_off_returns_503(admin_token, _clean, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "logo_variants_generation_enabled", False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/api/logo-variants/generate?project_id={PID}",
                         headers={"Authorization": admin_token})
    assert r.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_wp137_logo_router.py -v`
Expected: FAIL — 404 (роутер не подключён).

- [ ] **Step 3: Write the router**

```python
# backend/src/routers/logo_variants.py
"""WP#137: API уникализации лого клиента.

GET  /api/logo-variants/readiness  — состояние шага (лого/генерация/варианты/выбор)
POST /api/logo-variants/generate   — Сценарий А: запустить генерацию (kill-switch)
POST /api/logo-variants/select     — атомарно сохранить выбор (валидация по required)
POST /api/logo-variants/retry      — повтор после ошибки
POST /api/logo-variants/reset      — admin/manager: снести варианты+выбор
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..dependencies import get_current_user
from ..models.user import ValidatorUser, UserRole
from ..services import logo_generation_queue as q
from ..services.logo_variant_service import compute_logo_source_hash, fetch_logo_bytes

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/logo-variants", tags=["logo-variants"])


def _resolve_pid(user: ValidatorUser, project_id: int | None) -> int:
    """Клиент — свой project_id; admin/manager — переданный (US-3)."""
    if user.role in (UserRole.admin, UserRole.manager):
        if not project_id:
            raise HTTPException(400, "project_id обязателен для admin/manager")
        return int(project_id)
    if not user.project_id:
        raise HTTPException(400, "У пользователя нет project_id")
    return int(user.project_id)


async def _project_logo_url(db: AsyncSession, pid: int) -> str | None:
    return (await db.execute(text(
        "SELECT logo_url FROM validator_projects WHERE id=:p"
    ), {"p": pid})).scalar_one_or_none()


@router.get("/readiness")
async def readiness(project_id: int | None = None,
                    db: AsyncSession = Depends(get_db),
                    user: ValidatorUser = Depends(get_current_user)):
    pid = _resolve_pid(user, project_id)
    logo_url = await _project_logo_url(db, pid)
    counts = await q.compute_counts(pid, db)
    gen = await q.read_status(db, pid)

    variants = [dict(r) for r in (await db.execute(text("""
        SELECT id, variant_index, s3_url, status FROM logo_variants
         WHERE project_id=:p AND status='done' ORDER BY variant_index
    """), {"p": pid})).mappings().all()]
    selected = (await db.execute(text(
        "SELECT variant_id FROM logo_selections WHERE project_id=:p"
    ), {"p": pid})).scalars().all()

    return {
        "has_logo": bool(logo_url),
        "logo_url": logo_url,
        "required": counts["required"],
        "total_to_generate": counts["total_to_generate"],
        "generation": gen or {"status": "idle", "total": 0, "done": 0, "errors": 0},
        "variants": variants,
        "selected_ids": [int(x) for x in selected],
        "gate_enabled": settings.logo_variant_gate_enabled,
    }


@router.post("/generate")
async def generate(project_id: int | None = None,
                   db: AsyncSession = Depends(get_db),
                   user: ValidatorUser = Depends(get_current_user)):
    if not settings.logo_variants_generation_enabled:
        raise HTTPException(503, "Генерация вариантов лого временно недоступна")
    pid = _resolve_pid(user, project_id)
    logo_url = await _project_logo_url(db, pid)
    if not logo_url:
        raise HTTPException(400, "Сначала загрузите логотип")

    logo_bytes = await fetch_logo_bytes(logo_url)
    source_hash = compute_logo_source_hash(logo_bytes)
    counts = await q.compute_counts(pid, db)
    res = await q.enqueue(db, pid, logo_source_hash=source_hash,
                          version=settings.logo_prompt_template_version,
                          total=counts["total_to_generate"])
    await db.commit()
    return {**res, "required": counts["required"], "total": counts["total_to_generate"]}


class SelectBody(BaseModel):
    project_id: int | None = None
    variant_ids: list[int] = []


@router.post("/select")
async def select(body: SelectBody,
                 db: AsyncSession = Depends(get_db),
                 user: ValidatorUser = Depends(get_current_user)):
    pid = _resolve_pid(user, body.project_id)
    counts = await q.compute_counts(pid, db)
    required = counts["required"]
    ids = list(dict.fromkeys(body.variant_ids))  # dedup, keep order
    if len(ids) != required:
        raise HTTPException(400, f"Нужно выбрать ровно {required} вариантов (выбрано {len(ids)})")

    # все variant_id принадлежат проекту и done
    valid = (await db.execute(text("""
        SELECT id FROM logo_variants WHERE id = ANY(:ids) AND project_id=:p AND status='done'
    """), {"ids": ids, "p": pid})).scalars().all()
    if set(int(x) for x in valid) != set(ids):
        raise HTTPException(400, "Некоторые варианты не найдены или не принадлежат проекту")

    # атомарная перезапись выбора + обнуление ttl у выбранных
    await db.execute(text("DELETE FROM logo_selections WHERE project_id=:p"), {"p": pid})
    for vid in ids:
        await db.execute(text("""
            INSERT INTO logo_selections (project_id, variant_id, selected_by) VALUES (:p,:v,:u)
        """), {"p": pid, "v": vid, "u": user.id})
    await db.execute(text(
        "UPDATE logo_variants SET ttl_at=NULL WHERE id = ANY(:ids)"
    ), {"ids": ids})
    # вернуть ttl ранее выбранным, но снятым сейчас
    await db.execute(text("""
        UPDATE logo_variants SET ttl_at = NOW() + (:days || ' days')::interval
         WHERE project_id=:p AND ttl_at IS NULL AND id <> ALL(:ids)
           AND id NOT IN (SELECT variant_id FROM logo_selections WHERE project_id=:p)
    """), {"p": pid, "days": str(settings.logo_variant_ttl_days), "ids": ids})
    await db.commit()
    return {"ok": True, "selected": ids}


@router.post("/retry")
async def retry(project_id: int | None = None,
                db: AsyncSession = Depends(get_db),
                user: ValidatorUser = Depends(get_current_user)):
    if not settings.logo_variants_generation_enabled:
        raise HTTPException(503, "Генерация недоступна")
    pid = _resolve_pid(user, project_id)
    # сбросить failed/partial → позволить новый enqueue
    await db.execute(text("""
        UPDATE logo_generation_tasks SET status='cancelled', updated_at=NOW()
         WHERE project_id=:p AND status IN ('failed','partial','processing')
    """), {"p": pid})
    await db.commit()
    return await generate(project_id=project_id, db=db, user=user)


@router.post("/reset")
async def reset(project_id: int | None = None,
                db: AsyncSession = Depends(get_db),
                user: ValidatorUser = Depends(get_current_user)):
    if user.role not in (UserRole.admin, UserRole.manager):
        raise HTTPException(403, "Только admin/manager")
    pid = _resolve_pid(user, project_id)
    await db.execute(text("DELETE FROM logo_selections WHERE project_id=:p"), {"p": pid})
    await db.execute(text("DELETE FROM logo_variants WHERE project_id=:p"), {"p": pid})
    await db.execute(text("DELETE FROM logo_generation_tasks WHERE project_id=:p"), {"p": pid})
    await db.commit()
    return {"ok": True}
```

> Примечание по S3: `reset` не чистит объекты в S3 (TTL-объекты остаются, но строки удалены). Для MVP достаточно; уборку S3 можно вынести в follow-up (как у scheme reset, который чистит S3 — при желании зеркалить позже).

- [ ] **Step 4: Register router in main.py**

В `backend/src/main.py`: к строке импортов роутеров добавить `from .routers import logo_variants`; после `app.include_router(unic_content.router)` добавить `app.include_router(logo_variants.router)`.

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_wp137_logo_router.py -v`
Expected: PASS (4 теста).

- [ ] **Step 6: Commit**

```bash
git add backend/src/routers/logo_variants.py backend/src/main.py backend/tests/test_wp137_logo_router.py
git commit -m "feat(wp137): роутер /api/logo-variants (readiness/generate/select/retry/reset)"
```

---

### Task 10: Регрессия бэкенда

- [ ] **Step 1: Прогнать весь backend-набор**

Run: `cd backend && pytest -q`
Expected: все прежние тесты зелёные + новые WP#137. Если что-то красное из-за фонового loop в lifespan — убедиться, что тесты не стартуют lifespan (in-process ASGITransport не вызывает lifespan по умолчанию у httpx; loop там не запускается). Зафиксировать вывод.

- [ ] **Step 2: Commit (если были правки)**

```bash
git commit -am "test(wp137): зелёная регрессия backend" || echo "нет изменений"
```

---

## Phase 6 — Фронтенд

### Task 11: API-обёртки

**Files:**
- Create: `frontend/src/api/logoVariants.ts`
- Test: `frontend/src/api/__tests__/logoVariants.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/api/__tests__/logoVariants.spec.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import api from '@/api/client'
import { logoReadiness, logoGenerate, logoSelect } from '@/api/logoVariants'

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('logoVariants api', () => {
  beforeEach(() => vi.clearAllMocks())

  it('readiness GET с project_id', async () => {
    ;(api.get as any).mockResolvedValue({ data: { has_logo: true } })
    const r = await logoReadiness(7)
    expect(api.get).toHaveBeenCalledWith('/logo-variants/readiness', { params: { project_id: 7 } })
    expect(r.has_logo).toBe(true)
  })

  it('generate POST', async () => {
    ;(api.post as any).mockResolvedValue({ data: { task_id: 1 } })
    await logoGenerate(7)
    expect(api.post).toHaveBeenCalledWith('/logo-variants/generate', null, { params: { project_id: 7 } })
  })

  it('select POST с телом', async () => {
    ;(api.post as any).mockResolvedValue({ data: { ok: true } })
    await logoSelect(7, [1, 2, 3])
    expect(api.post).toHaveBeenCalledWith('/logo-variants/select', { project_id: 7, variant_ids: [1, 2, 3] })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/__tests__/logoVariants.spec.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the implementation**

```ts
// frontend/src/api/logoVariants.ts
import api from '@/api/client'

export interface LogoVariant { id: number; variant_index: number; s3_url: string; status: string }
export interface LogoReadiness {
  has_logo: boolean
  logo_url: string | null
  required: number
  total_to_generate: number
  generation: { status: string; total: number; done: number; errors: number; error?: string | null }
  variants: LogoVariant[]
  selected_ids: number[]
  gate_enabled: boolean
}

export async function logoReadiness(projectId?: number): Promise<LogoReadiness> {
  const params = projectId ? { project_id: projectId } : {}
  const res = await api.get('/logo-variants/readiness', { params })
  return res.data
}

export async function logoGenerate(projectId?: number) {
  const params = projectId ? { project_id: projectId } : {}
  const res = await api.post('/logo-variants/generate', null, { params })
  return res.data
}

export async function logoRetry(projectId?: number) {
  const params = projectId ? { project_id: projectId } : {}
  const res = await api.post('/logo-variants/retry', null, { params })
  return res.data
}

export async function logoSelect(projectId: number | undefined, variantIds: number[]) {
  const res = await api.post('/logo-variants/select', { project_id: projectId, variant_ids: variantIds })
  return res.data
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/__tests__/logoVariants.spec.ts`
Expected: PASS (3 теста).

> Если тест `generate` падает на `null` vs `undefined` body — axios `post(url, null, {params})` корректен; привести ожидание к фактическому вызову.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/logoVariants.ts frontend/src/api/__tests__/logoVariants.spec.ts
git commit -m "feat(wp137): фронт API-обёртки logo-variants"
```

---

### Task 12: Компонент карточки `LogoVariantCard.vue`

**Files:**
- Create: `frontend/src/components/logo/LogoVariantCard.vue`
- Test: `frontend/src/components/__tests__/LogoVariantCard.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/__tests__/LogoVariantCard.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import LogoVariantCard from '@/components/logo/LogoVariantCard.vue'

const variant = { id: 1, variant_index: 0, s3_url: 'https://s3/v0.png', status: 'done' }

describe('LogoVariantCard', () => {
  it('рендерит картинку и чекбокс', () => {
    const w = mount(LogoVariantCard, { props: { variant, selected: false } })
    expect(w.find('img').attributes('src')).toBe('https://s3/v0.png')
  })

  it('клик по карточке эмитит toggle с id', async () => {
    const w = mount(LogoVariantCard, { props: { variant, selected: false } })
    await w.trigger('click')
    expect(w.emitted('toggle')?.[0]).toEqual([1])
  })

  it('selected=true показывает отмеченное состояние', () => {
    const w = mount(LogoVariantCard, { props: { variant, selected: true } })
    expect(w.html()).toContain('aria-checked="true"')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/LogoVariantCard.spec.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

```vue
<!-- frontend/src/components/logo/LogoVariantCard.vue -->
<template>
  <div
    class="relative rounded-2xl border bg-gray-50 overflow-hidden cursor-pointer transition-all aspect-square hover:shadow-lg hover:scale-[1.05]"
    :class="selected ? 'border-indigo-500 ring-2 ring-indigo-300' : 'border-gray-200'"
    role="checkbox"
    :aria-checked="selected ? 'true' : 'false'"
    @click="$emit('toggle', variant.id)"
  >
    <img :src="variant.s3_url" class="w-full h-full object-contain p-3" :alt="`Вариант ${variant.variant_index + 1}`" />
    <div
      class="absolute top-2 right-2 w-6 h-6 rounded-md flex items-center justify-center text-xs font-bold border-2 transition-colors"
      :class="selected ? 'bg-indigo-600 border-indigo-600 text-white' : 'bg-white/80 border-gray-300 text-transparent'"
    >✓</div>
  </div>
</template>

<script setup lang="ts">
import type { LogoVariant } from '@/api/logoVariants'
defineProps<{ variant: LogoVariant; selected: boolean }>()
defineEmits<{ (e: 'toggle', id: number): void }>()
</script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/LogoVariantCard.spec.ts`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/logo/LogoVariantCard.vue frontend/src/components/__tests__/LogoVariantCard.spec.ts
git commit -m "feat(wp137): компонент LogoVariantCard (чекбокс, hover, toggle)"
```

---

### Task 13: Шаг `LogoVariantStep.vue` (состояния, грид, счётчик, гейт)

**Files:**
- Create: `frontend/src/components/logo/LogoVariantStep.vue`
- Test: `frontend/src/components/__tests__/LogoVariantStep.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/__tests__/LogoVariantStep.spec.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import LogoVariantStep from '@/components/logo/LogoVariantStep.vue'
import * as apiMod from '@/api/logoVariants'

vi.mock('@/api/logoVariants')

const ready = (over = {}) => ({
  has_logo: true, logo_url: 'https://s3/logo.png', required: 5, total_to_generate: 10,
  generation: { status: 'idle', total: 0, done: 0, errors: 0 },
  variants: Array.from({ length: 6 }, (_, i) => ({ id: i + 1, variant_index: i, s3_url: `https://s3/v${i}.png`, status: 'done' })),
  selected_ids: [], gate_enabled: true, ...over,
})

describe('LogoVariantStep', () => {
  beforeEach(() => vi.clearAllMocks())

  it('no-logo state показывает заглушку', async () => {
    ;(apiMod.logoReadiness as any).mockResolvedValue(ready({ has_logo: false, logo_url: null, variants: [] }))
    const w = mount(LogoVariantStep, { props: { projectId: 7 } })
    await flushPromises()
    expect(w.text()).toContain('Сначала загрузите логотип')
  })

  it('кнопка Далее disabled пока выбрано < required', async () => {
    ;(apiMod.logoReadiness as any).mockResolvedValue(ready())
    const w = mount(LogoVariantStep, { props: { projectId: 7 } })
    await flushPromises()
    const next = w.find('[data-test="next-btn"]')
    expect(next.attributes('disabled')).toBeDefined()
  })

  it('выбор required вариантов активирует Далее, клик зовёт logoSelect и эмитит done', async () => {
    ;(apiMod.logoReadiness as any).mockResolvedValue(ready())
    ;(apiMod.logoSelect as any).mockResolvedValue({ ok: true })
    const w = mount(LogoVariantStep, { props: { projectId: 7 } })
    await flushPromises()
    const cards = w.findAllComponents({ name: 'LogoVariantCard' })
    for (let i = 0; i < 5; i++) await cards[i].trigger('click')
    const next = w.find('[data-test="next-btn"]')
    expect(next.attributes('disabled')).toBeUndefined()
    await next.trigger('click')
    await flushPromises()
    expect(apiMod.logoSelect).toHaveBeenCalledWith(7, [1, 2, 3, 4, 5])
    expect(w.emitted('done')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/LogoVariantStep.spec.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

```vue
<!-- frontend/src/components/logo/LogoVariantStep.vue -->
<template>
  <div class="max-w-4xl mx-auto">
    <!-- Заголовок + индикатор шагов -->
    <h2 class="text-xl font-bold text-gray-800 mb-1">Шаг 1/2 — Выберите уникализированные лого</h2>
    <div class="flex items-center gap-2 text-sm mb-4">
      <span class="font-semibold text-indigo-600">● Лого</span>
      <span class="text-gray-400">○ Схемы</span>
    </div>

    <!-- Блок-объяснение -->
    <div class="bg-indigo-50 border border-indigo-200 rounded-xl p-4 mb-5 text-sm text-indigo-800">
      <div class="font-semibold mb-1">Зачем выбирать варианты лого?</div>
      Разнообразные варианты лого позволяют каждому ролику выглядеть уникально и получать больше охватов.
    </div>

    <!-- Загрузка readiness -->
    <div v-if="loading" class="text-center py-12 text-gray-400">Загрузка…</div>

    <!-- Нет лого -->
    <div v-else-if="!data?.has_logo" class="bg-white rounded-2xl border border-gray-200 p-8 text-center">
      <div class="text-5xl mb-4">⚠️</div>
      <h3 class="text-lg font-bold text-gray-800 mb-2">Логотип не загружен</h3>
      <p class="text-sm text-gray-500 mb-6">Сначала загрузите логотип на шаге распаковки.</p>
      <button class="px-5 py-2.5 bg-indigo-600 text-white rounded-lg text-sm" @click="goBrand">Перейти к распаковке</button>
    </div>

    <!-- Idle: кнопка генерации (Сценарий А) -->
    <div v-else-if="phase === 'idle'" class="bg-white rounded-2xl border border-gray-200 p-8 text-center">
      <img :src="data.logo_url || ''" class="h-20 mx-auto object-contain mb-4 rounded-lg border border-gray-200" />
      <button :disabled="busy" class="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium rounded-lg text-sm"
        @click="onGenerate">{{ busy ? 'Запускаем…' : 'Сгенерировать варианты' }}</button>
    </div>

    <!-- Генерация: skeletons -->
    <div v-else-if="phase === 'generating'">
      <p class="text-sm text-gray-500 mb-4 text-center">Готовим варианты лого, это занимает 8–15 секунд… ({{ data.generation.done }}/{{ data.generation.total }})</p>
      <div class="grid grid-cols-5 gap-3">
        <div v-for="i in (data.total_to_generate || 10)" :key="i" class="aspect-square rounded-2xl bg-gray-200 animate-pulse"></div>
      </div>
    </div>

    <!-- Ошибка -->
    <div v-else-if="phase === 'error'" class="bg-white rounded-2xl border border-red-200 p-8 text-center">
      <div class="text-5xl mb-4">😕</div>
      <h3 class="text-lg font-bold text-gray-800 mb-2">Не удалось сгенерировать варианты</h3>
      <button :disabled="busy" class="px-5 py-2.5 bg-indigo-600 disabled:opacity-50 text-white rounded-lg text-sm" @click="onRetry">Повторить</button>
    </div>

    <!-- Готово: грид -->
    <template v-else>
      <div class="grid grid-cols-5 gap-3">
        <LogoVariantCard
          v-for="v in data.variants" :key="v.id"
          :variant="v" :selected="selected.has(v.id)" @toggle="toggle"
        />
      </div>
      <div class="text-center mt-5">
        <div class="text-lg font-bold" :class="selected.size === data.required ? 'text-green-600' : 'text-gray-400'">
          Выбрано {{ selected.size }} из {{ data.required }}
        </div>
        <button
          data-test="next-btn"
          :disabled="selected.size !== data.required || busy"
          class="mt-3 px-8 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm"
          @click="onNext"
        >Далее</button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import LogoVariantCard from './LogoVariantCard.vue'
import { logoReadiness, logoGenerate, logoRetry, logoSelect, type LogoReadiness } from '@/api/logoVariants'

const props = defineProps<{ projectId?: number }>()
const emit = defineEmits<{ (e: 'done'): void }>()
const router = useRouter()

const loading = ref(true)
const busy = ref(false)
const data = ref<LogoReadiness | null>(null)
const selected = reactive(new Set<number>())
let pollTimer: ReturnType<typeof setInterval> | null = null

const phase = computed(() => {
  if (!data.value) return 'idle'
  const g = data.value.generation
  if (g.status === 'running') return 'generating'
  if (g.status === 'error') return 'error'
  if (data.value.variants.length > 0) return 'ready'
  return 'idle'
})

async function load() {
  data.value = await logoReadiness(props.projectId)
  // подхватываем уже сохранённый выбор
  selected.clear()
  for (const id of data.value.selected_ids) selected.add(id)
  loading.value = false
  managePolling()
}

function managePolling() {
  const running = data.value?.generation.status === 'running'
  if (running && !pollTimer) {
    pollTimer = setInterval(load, 2500)
  } else if (!running && pollTimer) {
    clearInterval(pollTimer); pollTimer = null
  }
}

function toggle(id: number) {
  if (selected.has(id)) selected.delete(id)
  else {
    if (data.value && selected.size >= data.value.required) return  // не больше required
    selected.add(id)
  }
}

async function onGenerate() {
  busy.value = true
  try { await logoGenerate(props.projectId); await load() } finally { busy.value = false }
}
async function onRetry() {
  busy.value = true
  try { await logoRetry(props.projectId); await load() } finally { busy.value = false }
}
async function onNext() {
  if (!data.value || selected.size !== data.value.required) return
  busy.value = true
  try {
    await logoSelect(props.projectId, Array.from(selected))
    emit('done')
  } finally { busy.value = false }
}
function goBrand() { router.push('/client/brand') }

onMounted(load)
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/LogoVariantStep.spec.ts`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/logo/LogoVariantStep.vue frontend/src/components/__tests__/LogoVariantStep.spec.ts
git commit -m "feat(wp137): шаг LogoVariantStep (idle/generating/error/ready, гейт, polling)"
```

---

### Task 14: Встроить шаг-гейт в `SchemesPage.vue`

**Files:**
- Modify: `frontend/src/pages/client/SchemesPage.vue`
- Test: `frontend/src/components/__tests__/SchemesPageLogoGate.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/__tests__/SchemesPageLogoGate.spec.ts
import { describe, it, expect } from 'vitest'
import { computeLogoGateDone } from '@/pages/client/schemesLogoGate'

describe('логика гейта лого в мастере схем', () => {
  it('гейт не пройден если выбрано меньше required', () => {
    expect(computeLogoGateDone({ required: 5, selected_ids: [1, 2] }, true)).toBe(false)
  })
  it('гейт пройден при required выборах', () => {
    expect(computeLogoGateDone({ required: 5, selected_ids: [1, 2, 3, 4, 5] }, true)).toBe(true)
  })
  it('гейт отключён kill-switch → всегда пройден', () => {
    expect(computeLogoGateDone({ required: 5, selected_ids: [] }, false)).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/SchemesPageLogoGate.spec.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Extract gate helper + integrate**

Создать `frontend/src/pages/client/schemesLogoGate.ts`:

```ts
// frontend/src/pages/client/schemesLogoGate.ts
export interface LogoGateState { required: number; selected_ids: number[] }

/** Гейт лого пройден, если выключен kill-switch ИЛИ выбрано >= required. */
export function computeLogoGateDone(state: LogoGateState, gateEnabled: boolean): boolean {
  if (!gateEnabled) return true
  return state.selected_ids.length >= state.required
}
```

В `frontend/src/pages/client/SchemesPage.vue` (script): импортировать шаг и хелпер, добавить состояние гейта и загрузку readiness лого при выборе проекта.

```ts
// добавить к импортам
import LogoVariantStep from '@/components/logo/LogoVariantStep.vue'
import { logoReadiness } from '@/api/logoVariants'
import { computeLogoGateDone } from './schemesLogoGate'
```

```ts
// рядом с остальными ref/reactive
const logoGateDone = ref(true)
const logoGateLoading = ref(true)

async function loadLogoGate() {
  logoGateLoading.value = true
  try {
    const pid = needsProjectSelector.value ? activeProjectId.value : undefined
    const r = await logoReadiness(pid)
    logoGateDone.value = computeLogoGateDone(
      { required: r.required, selected_ids: r.selected_ids }, r.gate_enabled
    )
  } catch { logoGateDone.value = true /* fail-open: не блокируем при ошибке */ }
  finally { logoGateLoading.value = false }
}
function onLogoStepDone() { logoGateDone.value = true }
```

Вызвать `loadLogoGate()` там же, где грузится `checkReadiness`/при `onProjectChange` и в `onMounted` (после установки активного проекта).

В `<template>` `SchemesPage.vue` — обернуть существующий мастер. Сразу после `<template v-if="hasProject">` добавить ветку гейта (а существующее содержимое — в `v-else`):

```vue
      <!-- WP#137: Шаг 1/2 — выбор лого (гейт перед схемами) -->
      <div v-if="logoGateLoading" class="text-center py-12 text-gray-400">Загрузка…</div>
      <LogoVariantStep
        v-else-if="!logoGateDone"
        :project-id="needsProjectSelector ? activeProjectId : undefined"
        @done="onLogoStepDone"
      />
      <template v-else>
        <!-- ↓↓↓ существующий мастер схем (Шаг 2/2) без изменений ↓↓↓ -->
```

И закрыть добавленный `<template v-else>` перед закрывающим `</template>` блока `v-if="hasProject"`.

> Важно: существующую step-машину схем НЕ трогаем — она целиком уезжает под `v-else` гейта. Это сохраняет всю логику видео/превью/тиндера.

- [ ] **Step 4: Run helper test + build**

Run: `cd frontend && npx vitest run src/components/__tests__/SchemesPageLogoGate.spec.ts && npx vue-tsc --noEmit`
Expected: тест PASS; типы без ошибок (или те же предупреждения, что были до правки).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/client/SchemesPage.vue frontend/src/pages/client/schemesLogoGate.ts frontend/src/components/__tests__/SchemesPageLogoGate.spec.ts
git commit -m "feat(wp137): встроить шаг-гейт выбора лого перед мастером схем"
```

---

### Task 15: Регрессия фронтенда

- [ ] **Step 1: Прогнать весь фронт-набор**

Run: `cd frontend && npx vitest run`
Expected: все тесты зелёные (новые WP#137 + прежние).

- [ ] **Step 2: Сборка**

Run: `cd frontend && npm run build`
Expected: успешная сборка.

- [ ] **Step 3: Commit (если правки)**

```bash
git commit -am "test(wp137): зелёная регрессия frontend" || echo "нет изменений"
```

---

## Self-review карта покрытия спеки → задачи

- §3 Модель данных → Task 1
- §2 Конфиг/kill-switch, провайдер → Task 2; промты §5 → Task 3
- §5 Пост-обработка Pillow → Task 4; генерация Laozhang → Task 5
- §4 enqueue/idempotent/status, required=pack+5/fallback → Task 6; исполнение/partial → Task 7; фоновый воркер + restart-resume → Task 8
- §4 эндпоинты readiness/generate(Сценарий А)/select(гейт-валидация)/retry/reset, US-3 admin → Task 9
- §6 фронт: API → 11, карточка (чекбокс/hover) → 12, состояния/счётчик/гейт/no-logo/polling/возврат-выбора → 13, встраивание Шаг 1/2 + URL/гейт → 14
- §7 TTL cron (вшит в loop) → Task 8
- §8 kill-switch'и → Task 2 (+ чтение фронтом через readiness.gate_enabled) Task 14

## Deferred / follow-up (не блокеры релиза)
- **Онбординг-тур** (ТЗ «если надо»): добавить `data-tour` к новому шагу + запись тура в существующий механизм `useSeenTours`/`OnboardingFlow`. Вынесено отдельно — текущий механизм определения шагов тура требует уточнения; не блокирует функционал.
- **Чистка S3 в reset** (зеркало scheme reset, который чистит объекты) — сейчас reset чистит только строки БД; объекты подберёт TTL. Можно дозеркалить позже.
- **Деплой**: миграция `alembic upgrade head` на проде; включить kill-switch'и `LOGO_VARIANTS_GENERATION_ENABLED`/`LOGO_VARIANT_GATE_ENABLED` + задать `LOGO_IMAGE_API_URL` (Laozhang images/edits). Прод-выкладка валидатора: backend pull + `pm2 restart id24`, frontend build → `/var/www/validator` (см. memory WP#136).
