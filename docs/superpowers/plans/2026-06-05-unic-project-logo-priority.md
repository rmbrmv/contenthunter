# Приоритет проектных логотипов в уникализации — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Логотипы, загруженные под конкретный проект (`validator_unic_content`), используются в уникализации в первую очередь; логотип из распаковки (`validator_brand_profiles.logo_url`) — только fallback, когда проектных логотипов нет.

**Architecture:** Инверсия приоритета источника логотипа в двух независимых местах: (1) финальный рендер — `resolve_logo` в `unic-worker/worker.py`; (2) превью схем — резолв `logo_url` в `validator-contenthunter` `schemes.py`, вынесенный в тестируемый хелпер. Оба за общим kill-switch `UNIC_PROJECT_LOGO_PRIORITY_ENABLED` (default ON). Без миграций — используем существующие таблицы.

**Tech Stack:** Python 3 / asyncpg (unic-worker), FastAPI / SQLAlchemy async (validator), pytest / pytest-asyncio.

**Дизайн-спека:** `docs/superpowers/specs/2026-06-05-unic-project-logo-priority-design.md`

---

## Контекст для исполнителя (прочитать до начала)

Логотип в уникализации берётся из двух таблиц общей БД `openclaw`:

- **`validator_unic_content`** — загруженный контент. Логотипы: `content_type='image'`, `label LIKE 'logo%'`, `project_id` = id проекта (или `0` для универсальных). Колонки: `id, content_type, label, usage_type, project_id, file_path, ...`. Все колонки кроме `id` nullable.
- **`validator_brand_profiles`** — бриф/распаковка клиента. Логотип в колонке `logo_url`. Уникальный `project_id`.

**Сейчас** оба источника отдают приоритет `brand_profiles.logo_url`. **Нужно** — наоборот: сначала проектные `validator_unic_content` логотипы (с ротацией по `content_logo_index` в рендере), потом распаковка.

Универсальные логотипы (`project_id=0`) распаковку НЕ перебивают — запросы фильтруют по конкретному `project_id`, поэтому строки с `project_id=0` естественно не попадают.

## Структура файлов

| Файл | Что делаем |
|------|-----------|
| `unic-worker/worker.py` | Флаг `PROJECT_LOGO_PRIORITY_ENABLED`; переписать `resolve_logo` (инверсия + фильтр пустых `file_path` + ротация); обновить docstring |
| `unic-worker/tests/test_resolve_logo_priority.py` | Создать: unit-тесты `resolve_logo` на FakeConn |
| `validator-contenthunter/backend/src/routers/schemes.py` | Добавить `import os`; новый хелпер `resolve_preview_logo_url`; заменить inline-резолв `logo_url` вызовом хелпера |
| `validator-contenthunter/backend/tests/test_scheme_preview_logo_priority.py` | Создать: тесты хелпера на live-DB |

---

## Task 1: Финальный рендер — `resolve_logo` инверсия приоритета (unic-worker)

**Files:**
- Modify: `/home/claude-user/unic-worker/worker.py` (флаг рядом со стр. 33; функция `resolve_logo` стр. 266-291)
- Test: `/home/claude-user/unic-worker/tests/test_resolve_logo_priority.py`

Тесты — чистые unit на фейковом соединении (`resolve_logo` зовёт только `conn.fetchval` для brand_profile и `conn.fetch` для unic_content). Это детерминированно и не трогает БД.

- [ ] **Step 1: Написать падающий тест-файл**

Create `/home/claude-user/unic-worker/tests/test_resolve_logo_priority.py`:

```python
"""resolve_logo: проектные логотипы (validator_unic_content) приоритетнее
распаковки (validator_brand_profiles.logo_url). Kill-switch
UNIC_PROJECT_LOGO_PRIORITY_ENABLED возвращает старый порядок.

Unit-тесты на FakeConn: resolve_logo зовёт conn.fetchval (brand_profile.logo_url)
и conn.fetch (validator_unic_content project logos)."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import worker  # noqa: E402


class FakeConn:
    """conn.fetchval -> brand_profile.logo_url ; conn.fetch -> project logos."""
    def __init__(self, brand_logo=None, project_logos=None):
        self._brand = brand_logo
        self._project = project_logos or []

    async def fetchval(self, query, *args):
        return self._brand

    async def fetch(self, query, *args):
        return list(self._project)


def _logo(i, path):
    return {"id": i, "content_type": "image", "label": f"logo_5_{i}",
            "project_id": 5, "file_path": path}


@pytest.mark.asyncio
async def test_project_logo_takes_priority_over_brand():
    conn = FakeConn(brand_logo="brand.png", project_logos=[_logo(1, "proj1.png")])
    res = await worker.resolve_logo(conn, 5, 1)
    assert res["file_path"] == "proj1.png"


@pytest.mark.asyncio
async def test_falls_back_to_brand_when_no_project_logos():
    conn = FakeConn(brand_logo="brand.png", project_logos=[])
    res = await worker.resolve_logo(conn, 5, 1)
    assert res == {"file_path": "brand.png", "source": "brand_profile"}


@pytest.mark.asyncio
async def test_returns_none_when_neither_source():
    conn = FakeConn(brand_logo=None, project_logos=[])
    assert await worker.resolve_logo(conn, 5, 1) is None


@pytest.mark.asyncio
async def test_returns_none_when_no_project_id():
    conn = FakeConn(brand_logo="brand.png", project_logos=[_logo(1, "p.png")])
    assert await worker.resolve_logo(conn, 0, 1) is None


@pytest.mark.asyncio
async def test_rotation_by_logo_idx():
    logos = [_logo(1, "a.png"), _logo(2, "b.png"), _logo(3, "c.png")]
    conn = FakeConn(project_logos=logos)
    assert (await worker.resolve_logo(conn, 5, 2))["file_path"] == "b.png"
    # modulo wrap: idx=4 -> (4-1)%3=0 -> first
    assert (await worker.resolve_logo(conn, 5, 4))["file_path"] == "a.png"


@pytest.mark.asyncio
async def test_skips_empty_file_path():
    logos = [_logo(1, ""), _logo(2, "real.png")]
    conn = FakeConn(project_logos=logos)
    # пустой отфильтрован -> idx=1 берёт первый непустой
    assert (await worker.resolve_logo(conn, 5, 1))["file_path"] == "real.png"


@pytest.mark.asyncio
async def test_kill_switch_off_uses_brand_first(monkeypatch):
    monkeypatch.setattr(worker, "PROJECT_LOGO_PRIORITY_ENABLED", False)
    conn = FakeConn(brand_logo="brand.png", project_logos=[_logo(1, "proj1.png")])
    res = await worker.resolve_logo(conn, 5, 1)
    assert res == {"file_path": "brand.png", "source": "brand_profile"}
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/unic-worker && python -m pytest tests/test_resolve_logo_priority.py -v`
Expected: FAIL — `test_project_logo_takes_priority_over_brand` падает (сейчас возвращается brand.png), плюс `AttributeError`/несоответствие в kill-switch тесте (атрибут `PROJECT_LOGO_PRIORITY_ENABLED` ещё не существует).

- [ ] **Step 3: Добавить флаг рядом с остальными env (после стр. 33 `OWNER_GUARD_ENABLED`)**

```python
PROJECT_LOGO_PRIORITY_ENABLED = os.environ.get('UNIC_PROJECT_LOGO_PRIORITY_ENABLED', '1') != '0'
```

- [ ] **Step 4: Переписать `resolve_logo` (заменить целиком стр. 266-291)**

```python
async def resolve_logo(conn, project_id, logo_idx):
    """Resolve the logo asset for a unic task.

    Priority (UNIC_PROJECT_LOGO_PRIORITY_ENABLED=1, default):
      1. validator_unic_content project-specific logos (content_type='image',
         label LIKE 'logo%', project_id=<this project>), rotated by logo_idx
         (1-based content_logo_index). Rows with empty file_path are skipped.
      2. Fallback: validator_brand_profiles.logo_url (client brief / распаковка).
      3. None when neither exists, or when project_id is missing.

    With UNIC_PROJECT_LOGO_PRIORITY_ENABLED=0 the legacy order is used
    (brand_profile first, then unic_content pool).
    """
    if not project_id:
        return None

    async def _project_logos():
        rows = await conn.fetch(
            "SELECT * FROM validator_unic_content "
            "WHERE content_type='image' AND label LIKE 'logo%' AND project_id=$1 "
            "ORDER BY id",
            project_id,
        )
        return [r for r in rows if (r['file_path'] or '').strip()]

    async def _brand_profile():
        bp_url = await conn.fetchval(
            "SELECT logo_url FROM validator_brand_profiles WHERE project_id=$1",
            project_id,
        )
        return {'file_path': bp_url, 'source': 'brand_profile'} if bp_url else None

    if PROJECT_LOGO_PRIORITY_ENABLED:
        logos = await _project_logos()
        if logos:
            return dict(logos[(int(logo_idx or 1) - 1) % len(logos)])
        return await _brand_profile()

    bp = await _brand_profile()
    if bp:
        return bp
    logos = await _project_logos()
    if not logos:
        return None
    return dict(logos[(int(logo_idx or 1) - 1) % len(logos)])
```

- [ ] **Step 5: Запустить тест — убедиться, что проходит**

Run: `cd /home/claude-user/unic-worker && python -m pytest tests/test_resolve_logo_priority.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Регрессия worker — null-safe + per-project + dispatch**

Run: `cd /home/claude-user/unic-worker && python -m pytest tests/test_null_safe_scheme_params.py tests/test_dispatch_by_task_type.py -v`
Expected: PASS (никаких регрессий в построении ffmpeg/диспатче).

- [ ] **Step 7: Commit**

```bash
cd /home/claude-user/unic-worker
git checkout -b feat-project-logo-priority-2026-06-05
git add worker.py tests/test_resolve_logo_priority.py
git commit -m "feat(logo): проектные логотипы приоритетнее распаковки в resolve_logo

Инверсия приоритета: validator_unic_content (project_id) → brand_profile.
Ротация по content_logo_index активна; пустые file_path пропускаются.
Kill-switch UNIC_PROJECT_LOGO_PRIORITY_ENABLED (default ON).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Превью схем — хелпер `resolve_preview_logo_url` (validator)

**Files:**
- Modify: `/home/claude-user/validator-contenthunter/backend/src/routers/schemes.py` (добавить `import os` к стр. 1-2; хелпер на уровне модуля; заменить inline-резолв стр. 357-367)
- Test: `/home/claude-user/validator-contenthunter/backend/tests/test_scheme_preview_logo_priority.py`

Тесты — live-DB (как `test_scheme_preview_endpoint.py`): вставляем строки, зовём хелпер напрямую, ассертим, чистим.

- [ ] **Step 1: Написать падающий тест-файл**

Create `/home/claude-user/validator-contenthunter/backend/tests/test_scheme_preview_logo_priority.py`:

```python
"""resolve_preview_logo_url: проектный логотип (validator_unic_content)
приоритетнее распаковки (validator_brand_profiles.logo_url) и legacy
validator_projects.logo_url. Универсальные (project_id=0) не учитываются.
Kill-switch UNIC_PROJECT_LOGO_PRIORITY_ENABLED=0 -> старый порядок."""
import os
import pytest
import pytest_asyncio
from sqlalchemy import text

from src.database import AsyncSessionLocal
from src.routers.schemes import resolve_preview_logo_url

PID = 100777


async def _cleanup(db):
    await db.execute(text("DELETE FROM validator_unic_content WHERE project_id IN (:pid, 0) AND label LIKE 'logo_test_%'"), {"pid": PID})
    await db.execute(text("DELETE FROM validator_brand_profiles WHERE project_id=:pid"), {"pid": PID})
    await db.execute(text("DELETE FROM validator_projects WHERE id=:pid"), {"pid": PID})


@pytest_asyncio.fixture
async def base_project():
    async with AsyncSessionLocal() as db:
        await _cleanup(db)
        await db.execute(text(
            "INSERT INTO validator_projects (id, project) VALUES (:pid, 'test-logo-prio')"
        ), {"pid": PID})
        await db.commit()
    yield PID
    async with AsyncSessionLocal() as db:
        await _cleanup(db)
        await db.commit()


@pytest.mark.asyncio
async def test_project_logo_wins_over_brand(base_project):
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO validator_brand_profiles (project_id, logo_url) VALUES (:pid, 'brand.png')"
        ), {"pid": PID})
        await db.execute(text(
            "INSERT INTO validator_unic_content (content_type, label, project_id, file_path) "
            "VALUES ('image', 'logo_test_1', :pid, 'proj1.png')"
        ), {"pid": PID})
        await db.commit()
        assert await resolve_preview_logo_url(db, PID) == "proj1.png"


@pytest.mark.asyncio
async def test_first_project_logo_by_id(base_project):
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO validator_unic_content (content_type, label, project_id, file_path) "
            "VALUES ('image', 'logo_test_a', :pid, 'first.png'), "
            "('image', 'logo_test_b', :pid, 'second.png')"
        ), {"pid": PID})
        await db.commit()
        assert await resolve_preview_logo_url(db, PID) == "first.png"


@pytest.mark.asyncio
async def test_fallback_to_brand_when_no_project_logo(base_project):
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO validator_brand_profiles (project_id, logo_url) VALUES (:pid, 'brand.png')"
        ), {"pid": PID})
        await db.commit()
        assert await resolve_preview_logo_url(db, PID) == "brand.png"


@pytest.mark.asyncio
async def test_universal_logo_ignored(base_project):
    async with AsyncSessionLocal() as db:
        # универсальный (project_id=0) логотип НЕ должен перебивать распаковку
        await db.execute(text(
            "INSERT INTO validator_unic_content (content_type, label, project_id, file_path) "
            "VALUES ('image', 'logo_test_univ', 0, 'universal.png')"
        ))
        await db.execute(text(
            "INSERT INTO validator_brand_profiles (project_id, logo_url) VALUES (:pid, 'brand.png')"
        ), {"pid": PID})
        await db.commit()
        assert await resolve_preview_logo_url(db, PID) == "brand.png"


@pytest.mark.asyncio
async def test_empty_file_path_skipped(base_project):
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO validator_unic_content (content_type, label, project_id, file_path) "
            "VALUES ('image', 'logo_test_empty', :pid, '')"
        ), {"pid": PID})
        await db.execute(text(
            "INSERT INTO validator_brand_profiles (project_id, logo_url) VALUES (:pid, 'brand.png')"
        ), {"pid": PID})
        await db.commit()
        # пустой file_path игнорируется -> fallback на распаковку
        assert await resolve_preview_logo_url(db, PID) == "brand.png"


@pytest.mark.asyncio
async def test_kill_switch_off_uses_brand_first(base_project, monkeypatch):
    monkeypatch.setenv("UNIC_PROJECT_LOGO_PRIORITY_ENABLED", "0")
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO validator_brand_profiles (project_id, logo_url) VALUES (:pid, 'brand.png')"
        ), {"pid": PID})
        await db.execute(text(
            "INSERT INTO validator_unic_content (content_type, label, project_id, file_path) "
            "VALUES ('image', 'logo_test_ks', :pid, 'proj1.png')"
        ), {"pid": PID})
        await db.commit()
        assert await resolve_preview_logo_url(db, PID) == "brand.png"
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_scheme_preview_logo_priority.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_preview_logo_url'` (хелпера ещё нет).

- [ ] **Step 3: Добавить `import os` в шапку schemes.py**

Изменить стр. 1-2 с:
```python
import logging
import uuid
```
на:
```python
import logging
import os
import uuid
```

- [ ] **Step 4: Добавить хелпер на уровне модуля (перед функцией эндпоинта generate-previews)**

```python
async def resolve_preview_logo_url(db, project_id):
    """Logo URL для payload превью схем.

    Priority (UNIC_PROJECT_LOGO_PRIORITY_ENABLED=1, default):
      1. Первый проектный логотип в validator_unic_content
         (content_type='image', label LIKE 'logo%', project_id=<this>),
         ORDER BY id, с непустым file_path.
      2. validator_brand_profiles.logo_url (распаковка).
      3. validator_projects.logo_url (legacy).
    UNIC_PROJECT_LOGO_PRIORITY_ENABLED=0 -> пропускает шаг 1 (старый порядок).
    """
    if os.environ.get("UNIC_PROJECT_LOGO_PRIORITY_ENABLED", "1") == "1":
        row = (await db.execute(text(
            "SELECT file_path FROM validator_unic_content "
            "WHERE content_type='image' AND label LIKE 'logo%%' AND project_id=:pid "
            "AND file_path IS NOT NULL AND file_path <> '' "
            "ORDER BY id LIMIT 1"
        ), {"pid": project_id})).mappings().first()
        if row and row["file_path"]:
            return row["file_path"]

    logo_result = await db.execute(text("""
        SELECT bp.logo_url, vp.logo_url AS project_logo
        FROM validator_projects vp
        LEFT JOIN validator_brand_profiles bp ON bp.project_id = vp.id
        WHERE vp.id = :pid
    """), {"pid": project_id})
    logo_row = logo_result.mappings().first()
    if logo_row:
        return logo_row["logo_url"] or logo_row["project_logo"]
    return None
```

- [ ] **Step 5: Заменить inline-резолв в эндпоинте (стр. 357-367)**

Заменить блок:
```python
    # 3) Logo URL — brand_profile, fallback на validator_projects.logo_url
    logo_result = await db.execute(text("""
        SELECT bp.logo_url, vp.logo_url AS project_logo
        FROM validator_projects vp
        LEFT JOIN validator_brand_profiles bp ON bp.project_id = vp.id
        WHERE vp.id = :pid
    """), {"pid": project_id})
    logo_row = logo_result.mappings().first()
    logo_url = None
    if logo_row:
        logo_url = logo_row["logo_url"] or logo_row["project_logo"]
```
на:
```python
    # 3) Logo URL — проектные логотипы (validator_unic_content) → brand_profile → projects (legacy)
    logo_url = await resolve_preview_logo_url(db, project_id)
```

- [ ] **Step 6: Запустить тест — убедиться, что проходит**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_scheme_preview_logo_priority.py -v`
Expected: PASS (6 passed). Если pytest сообщает "admin user не найден"/пустая БД — это другой тест-файл; здесь зависимости от admin нет.

- [ ] **Step 7: Регрессия превью-эндпоинта и очереди**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_scheme_preview_endpoint.py tests/test_scheme_preview_queue.py -v`
Expected: PASS (эндпоинт по-прежнему собирает payload и кладёт задачу; смена резолва логотипа меняет только значение `logo_url`).

- [ ] **Step 8: Commit**

```bash
cd /home/claude-user/validator-contenthunter
git checkout -b feat-project-logo-priority-2026-06-05
git add backend/src/routers/schemes.py backend/tests/test_scheme_preview_logo_priority.py
git commit -m "feat(logo): проектные логотипы приоритетнее распаковки в превью схем

resolve_preview_logo_url: validator_unic_content (project_id) → brand_profile
→ projects (legacy). Универсальные project_id=0 не учитываются.
Kill-switch UNIC_PROJECT_LOGO_PRIORITY_ENABLED (default ON).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Итоговая верификация (оба репозитория)

**Files:** нет (только запуск).

- [ ] **Step 1: Полный таргетный прогон unic-worker**

Run: `cd /home/claude-user/unic-worker && python -m pytest tests/test_resolve_logo_priority.py tests/test_null_safe_scheme_params.py tests/test_dispatch_by_task_type.py tests/test_payload_processing.py -v`
Expected: всё PASS. (Полный `pytest tests/` может требовать живую БД для guard/heartbeat/watchdog — запускать их при наличии БД; иначе ограничиться перечисленными.)

- [ ] **Step 2: Полный таргетный прогон validator**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_scheme_preview_logo_priority.py tests/test_scheme_preview_endpoint.py tests/test_scheme_preview_queue.py tests/test_schemes_excludes_service_rows.py -v`
Expected: всё PASS (отдельные тесты могут `skip` при пустых `unic_schemes`/отсутствии admin — это норма).

- [ ] **Step 3: Sanity — kill-switch off возвращает старое поведение**

Run: `cd /home/claude-user/unic-worker && UNIC_PROJECT_LOGO_PRIORITY_ENABLED=0 python -m pytest tests/test_resolve_logo_priority.py -v`
Expected: `test_kill_switch_off_uses_brand_first` PASS; остальные тесты этого файла, ожидающие проектного приоритета, ПАДУТ (они проверяют ON-поведение) — это ожидаемо и подтверждает, что флаг реально переключает логику. Для зелёного прогона флаг не выставлять (default ON).

> Примечание step 3: можно пропустить, если не хочется видеть «ожидаемые падения». Главная проверка kill-switch — `test_kill_switch_off_uses_brand_first` через monkeypatch внутри обычного прогона (Task 1 step 5, Task 2 step 6).

---

## Деплой (после ревью; не часть TDD-цикла)

Справочно из памяти проекта — уточнить актуальность перед выполнением:

- **unic-worker** — реальный прод-воркер: standalone PM2 `id0` на `91.98.180.103`, каталог НЕ под git → деплой = `scp worker.py` + `pm2 restart`, ключ `~/.ssh/wp136_logo_bg_deploy`. Тест-файл на прод не нужен.
- **validator** — backend pull + `pm2 restart` (id24 на `72.56.107.157`); фронтенд не затрагивается (билд не требуется).
- **Kill-switch** обоих сервисов — переменная `UNIC_PROJECT_LOGO_PRIORITY_ENABLED` в `.env` соответствующего сервиса. Default ON в коде; для отката выставить `=0` и перезапустить.
- Превью схем перегенерируются автоматически (смена `logo_url` меняет `payload_hash`).
- Документация по итогу — PR в `rmbrmv/contenthunter` (docs-репо).
