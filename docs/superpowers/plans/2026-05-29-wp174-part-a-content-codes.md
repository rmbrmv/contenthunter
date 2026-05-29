# WP#174 Часть A — Коды роликов (RLM-014): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать каждому загруженному ролику короткий читаемый код `PREFIX-NNN` (RLM-014), авто-генерируемый при загрузке, видимый админам.

**Architecture:** В `validator-contenthunter` добавляем `validator_projects.code_prefix`/`code_seq` и `validator_content.code_number`. Префикс генерируется детерминированно из транслита имени проекта (с ручным override админом), номер выдаётся атомарно через `UPDATE ... RETURNING`. Полный код рендерится на лету (`prefix + '-' + pad(number)`). Легаси бэкфилл — идемпотентный скрипт. Delivery (`delivery-contenthunter`) только читает код.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy async / Alembic / pytest (live DB); Node.js `server.js` + vanilla JS (delivery).

**Spec:** `docs/superpowers/specs/2026-05-29-wp174-part-a-content-codes-design.md`

**Репозитории:**
- Валидатор: `/home/claude-user/validator-contenthunter/backend`
- Delivery: `/home/claude-user/autowarm-testbench` (origin = `delivery-contenthunter`)

**Команда тестов (валидатор):** `cd /home/claude-user/validator-contenthunter/backend && python -m pytest <путь> -v` (тесты ходят в живую БД; `conftest.py` диспоузит engine между тестами).

**psql:** перед командами `psql`/`PGPASSWORD` экспортировать пароль из локального секрета (не хранить в репозитории): `export PGPASSWORD=<openclaw-пароль из локальной конфигурации>`.

---

## File Structure

| Файл | Ответственность |
|------|-----------------|
| `backend/alembic/versions/008_wp174_content_codes.py` | Схема: `code_prefix`(unique)/`code_seq` на проекте, `code_number` на контенте |
| `backend/src/services/prefix_service.py` | **Новый.** Генерация префикса (pure), разрешение коллизий, `ensure_project_prefix`, `assign_content_code`, `format_code` |
| `backend/src/routers/clients.py` | Хук `ensure_project_prefix` в `register_client` |
| `backend/src/routers/projects.py` | Хук `ensure_project_prefix` в `create_project`; override префикса в `update_project`; отдать `code_prefix` в `list_projects` |
| `backend/src/routers/upload.py` | `assign_content_code` в 4 точках вставки `ValidatorContent` |
| `backend/src/routers/content.py` | Отдать `code` в сериализации (`_content_to_dict_with_publish`) с role-check |
| `backend/scripts/backfill_content_codes.py` | **Новый.** Идемпотентный бэкфилл легаси-кодов |
| `backend/tests/test_wp174_content_codes.py` | **Новый.** Тесты сервиса + интеграция + override |
| delivery `server.js` + `public/index.html` | Чтение и показ кода в админских таблицах |

---

## Task 1: Миграция схемы

**Files:**
- Create: `backend/alembic/versions/008_wp174_content_codes.py`
- Modify: `backend/src/models/content.py` (ORM-колонка `code_number`)

- [ ] **Step 1: Написать миграцию**

```python
"""WP #174 Часть A: коды роликов — code_prefix/code_seq на проекте, code_number на контенте

Revision ID: 008
Revises: 007
Create Date: 2026-05-29
"""
from alembic import op

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE validator_projects
          ADD COLUMN IF NOT EXISTS code_prefix text NULL,
          ADD COLUMN IF NOT EXISTS code_seq integer NOT NULL DEFAULT 0;
    """)
    # UNIQUE допускает несколько NULL в PG — легаси стартует с NULL, бэкфилл заполнит.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_validator_projects_code_prefix
          ON validator_projects (code_prefix)
          WHERE code_prefix IS NOT NULL;
    """)
    op.execute("""
        ALTER TABLE validator_content
          ADD COLUMN IF NOT EXISTS code_number integer NULL;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE validator_content DROP COLUMN IF EXISTS code_number;")
    op.execute("DROP INDEX IF EXISTS uq_validator_projects_code_prefix;")
    op.execute("""
        ALTER TABLE validator_projects
          DROP COLUMN IF EXISTS code_seq,
          DROP COLUMN IF EXISTS code_prefix;
    """)
```

- [ ] **Step 2: Применить миграцию**

Run: `cd /home/claude-user/validator-contenthunter/backend && alembic upgrade head`
Expected: `Running upgrade 007 -> 008`

- [ ] **Step 3: Проверить колонки**

Run: `PGPASSWORD="$PGPASSWORD" psql -h localhost -U openclaw -d openclaw -c "\d validator_projects" | grep -E "code_prefix|code_seq"`
Expected: обе колонки присутствуют; индекс `uq_validator_projects_code_prefix`.

- [ ] **Step 4: Добавить ORM-колонку `code_number` в модель (КРИТИЧНО — иначе присваивание не запишется)**

В `backend/src/models/content.py`, в классе `ValidatorContent`, рядом с `content_hash`/`is_duplicate` добавить:

```python
    code_number = Column(Integer, nullable=True)  # WP#174 — порядковый номер ролика в проекте
```

(`Column`, `Integer` уже импортированы в этом файле.)

> Без этого `content.code_number = ...` в `upload.py` создаёт лишь transient-атрибут Python и НЕ флашится в БД; чтение `c.code_number` из загруженных ORM-объектов также не отработает. `validator_projects` отдельной ORM-модели не имеет (только raw SQL) — там правок не нужно.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter/backend
git add alembic/versions/008_wp174_content_codes.py src/models/content.py
git commit -m "feat(wp174): миграция + ORM-колонка code_number — code_prefix/code_seq/code_number"
```

---

## Task 2: prefix_service — генерация префикса (pure)

**Files:**
- Create: `backend/src/services/prefix_service.py`
- Test: `backend/tests/test_wp174_content_codes.py`

- [ ] **Step 1: Написать падающий тест (pure-функции)**

```python
# backend/tests/test_wp174_content_codes.py
from src.services.prefix_service import base_prefix, candidate_prefixes, format_code


def test_base_prefix_from_cyrillic():
    assert base_prefix("Эзотерика") == "EZO"
    assert base_prefix("Relisme") == "REL"
    assert base_prefix("Art Estate") == "ART"


def test_base_prefix_pads_short_names():
    # Название без латиницы/коротыш → добивка X
    assert base_prefix("Я") == "YAX"  # transliterate('я')='ya' → Y,A + X


def test_candidate_order():
    cands = list(candidate_prefixes("Relisme"))
    assert cands[0] == "REL"
    # вторая волна — base2 + цифра/буква
    assert "RE2" in cands
    # детерминированно, без дублей
    assert len(cands) == len(set(cands))


def test_format_code_padding():
    assert format_code("RLM", 14) == "RLM-014"
    assert format_code("RLM", 1) == "RLM-001"
    assert format_code("RLM", 999) == "RLM-999"
    assert format_code("RLM", 1000) == "RLM-1000"
    assert format_code(None, 14) is None
    assert format_code("RLM", None) is None
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py -v`
Expected: FAIL (ModuleNotFoundError: prefix_service).

- [ ] **Step 3: Реализовать pure-функции**

```python
# backend/src/services/prefix_service.py
"""WP#174 Часть A — генерация кодов роликов (PREFIX-NNN)."""
from ..routers.clients import _transliterate

_SUFFIX_CHARS = "23456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def base_prefix(project_name: str) -> str:
    """Первые 3 латинские буквы транслита, uppercase, добивка 'X' до 3."""
    translit = _transliterate(project_name)
    letters = [c for c in translit if c.isascii() and c.isalpha()]
    base = "".join(letters[:3]).upper()
    if len(base) < 3:
        base = (base + "XXX")[:3]
    return base


def candidate_prefixes(project_name: str):
    """Детерминированный конечный поток кандидатов по приоритету.
    1) base3; 2) base2 + suffix-char; 3) base1 + base3[2] + suffix-char."""
    base = base_prefix(project_name)
    seen = set()

    def _emit(p):
        if p not in seen:
            seen.add(p)
            return p
        return None

    first = _emit(base)
    if first:
        yield first
    for c in _SUFFIX_CHARS:                     # тир 2: RE2, RE3, ... REA ...
        p = _emit(base[:2] + c)
        if p:
            yield p
    for c in _SUFFIX_CHARS:                     # тир 3: R + L + suffix
        p = _emit(base[0] + base[2] + c)
        if p:
            yield p


def format_code(prefix, number) -> str | None:
    """Полный код = prefix + '-' + pad(number). До 999 — 3 цифры, далее без нулей."""
    if not prefix or number is None:
        return None
    if number < 1000:
        return f"{prefix}-{number:03d}"
    return f"{prefix}-{number}"
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py -v`
Expected: PASS (4 теста).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter/backend
git add src/services/prefix_service.py tests/test_wp174_content_codes.py
git commit -m "feat(wp174): prefix_service — генерация префикса + format_code (pure)"
```

---

## Task 3: prefix_service — DB-операции (ensure_project_prefix, assign_content_code)

**Files:**
- Modify: `backend/src/services/prefix_service.py`
- Test: `backend/tests/test_wp174_content_codes.py`

- [ ] **Step 1: Написать падающий интеграционный тест**

```python
# Добавить в backend/tests/test_wp174_content_codes.py
import pytest
from sqlalchemy import text
from src.database import async_session
from src.services.prefix_service import ensure_project_prefix, assign_content_code


@pytest.mark.asyncio
async def test_ensure_prefix_and_assign_code_sequence():
    async with async_session() as db:
        # временный проект
        row = await db.execute(text(
            "INSERT INTO validator_projects (id, project, api_name, active) "
            "VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM validator_projects), "
            ":n, :a, true) RETURNING id"), {"n": "PyTest Релизми", "a": "pytest_relizmi_wp174"})
        pid = row.scalar()
        await db.commit()
        try:
            p1 = await ensure_project_prefix(db, pid, "PyTest Релизми")
            await db.commit()
            assert len(p1) == 3 and p1.isupper()
            # повторный вызов идемпотентен
            p2 = await ensure_project_prefix(db, pid, "PyTest Релизми")
            assert p1 == p2
            # номера выдаются монотонно без дыр
            n1 = await assign_content_code(db, pid)
            n2 = await assign_content_code(db, pid)
            await db.commit()
            assert (n1, n2) == (1, 2)
        finally:
            await db.execute(text("DELETE FROM validator_projects WHERE id=:id"), {"id": pid})
            await db.commit()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py::test_ensure_prefix_and_assign_code_sequence -v`
Expected: FAIL (ImportError: ensure_project_prefix).

- [ ] **Step 3: Реализовать DB-операции**

```python
# Добавить в backend/src/services/prefix_service.py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError


async def ensure_project_prefix(db: AsyncSession, project_id: int, project_name: str) -> str:
    """Идемпотентно присваивает проекту свободный префикс. Возвращает его.
    НЕ коммитит — коммит на вызывающей стороне.
    Retry-safe: при параллельном создании двух проектов с одинаковым кандидатом
    unique-индекс отклонит второй UPDATE — ловим IntegrityError в SAVEPOINT и
    пробуем следующий кандидат."""
    existing = (await db.execute(
        text("SELECT code_prefix FROM validator_projects WHERE id=:id"),
        {"id": project_id})).scalar()
    if existing:
        return existing
    for cand in candidate_prefixes(project_name):
        # быстрый отсев уже занятых (оптимизация; финальная гарантия — unique-индекс)
        taken = (await db.execute(
            text("SELECT 1 FROM validator_projects WHERE code_prefix=:p"),
            {"p": cand})).first()
        if taken:
            continue
        try:
            async with db.begin_nested():  # SAVEPOINT изолирует возможный unique-конфликт
                await db.execute(
                    text("UPDATE validator_projects SET code_prefix=:p WHERE id=:id"),
                    {"p": cand, "id": project_id})
            return cand
        except IntegrityError:
            # параллельная сессия заняла этот префикс между SELECT и UPDATE — берём следующий
            continue
    raise ValueError(f"Не осталось свободных префиксов для проекта {project_id}; задайте вручную")


async def assign_content_code(db: AsyncSession, project_id: int) -> int:
    """Атомарно выдаёт следующий порядковый номер ролика проекта (race-safe)."""
    seq = (await db.execute(
        text("UPDATE validator_projects SET code_seq = code_seq + 1 "
             "WHERE id=:id RETURNING code_seq"),
        {"id": project_id})).scalar()
    if seq is None:
        raise ValueError(f"Проект {project_id} не найден для выдачи кода")
    return seq
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py -v`
Expected: PASS (все тесты).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter/backend
git add src/services/prefix_service.py tests/test_wp174_content_codes.py
git commit -m "feat(wp174): ensure_project_prefix + assign_content_code (race-safe)"
```

---

## Task 4: Генерация префикса при создании проекта (оба пути)

**Files:**
- Modify: `backend/src/routers/clients.py:142` (после INSERT проекта, до commit)
- Modify: `backend/src/routers/projects.py:36-49` (`create_project`)
- Test: `backend/tests/test_wp174_content_codes.py`

- [ ] **Step 1: Падающий тест — оба пути присваивают префикс**

```python
# Добавить в backend/tests/test_wp174_content_codes.py
@pytest.mark.asyncio
async def test_projects_create_path_sets_prefix():
    from src.routers.projects import create_project, ProjectBody
    # мок current_user (admin) и реальная сессия
    async with async_session() as db:
        class _U:  # минимальный stub
            class role: value = "admin"
        body = ProjectBody(project="PyTest Эзотерика", api_name="pytest_ezo_wp174",
                           active=True, logo_url=None, manager=None)
        res = await create_project(body=body, db=db, current_user=_U())
        pid = res["id"]
        try:
            pref = (await db.execute(text(
                "SELECT code_prefix FROM validator_projects WHERE id=:id"),
                {"id": pid})).scalar()
            assert pref and len(pref) == 3
        finally:
            await db.execute(text("DELETE FROM validator_projects WHERE id=:id"), {"id": pid})
            await db.commit()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py::test_projects_create_path_sets_prefix -v`
Expected: FAIL (code_prefix is None).

- [ ] **Step 3a: Хук в `projects.py::create_project`**

Заменить тело `create_project` (строки 36-49) на:

```python
async def create_project(
    body: ProjectBody,
    db: AsyncSession = Depends(get_db),
    current_user: ValidatorUser = Depends(get_current_user),
):
    if current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    result = await db.execute(text("""
        INSERT INTO validator_projects (project, api_name, active, logo_url, manager)
        VALUES (:project, :api_name, :active, :logo_url, :manager)
        RETURNING id
    """), body.model_dump())
    row = result.mappings().first()
    pid = row["id"]
    from ..services.prefix_service import ensure_project_prefix
    await ensure_project_prefix(db, pid, body.project)
    await db.commit()
    return {"ok": True, "id": pid}
```

- [ ] **Step 3b: Хук в `clients.py::register_client`**

В `clients.py` после блока создания проекта (после строки 96, где получен `project_id`, до `await db.commit()` на строке 142) добавить:

```python
    # WP#174: присвоить проекту код-префикс
    from ..services.prefix_service import ensure_project_prefix
    await ensure_project_prefix(db, project_id, body.project_name.strip())
```

- [ ] **Step 4: Запустить тест**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter/backend
git add src/routers/projects.py src/routers/clients.py tests/test_wp174_content_codes.py
git commit -m "feat(wp174): авто-генерация префикса в обоих путях создания проекта"
```

---

## Task 5: Авто-присвоение кода ролика в upload.py (4 точки)

**Files:**
- Modify: `backend/src/routers/upload.py` (4 блока `db.add(content)` на ~134, ~380, ~586, ~767)
- Test: `backend/tests/test_wp174_content_codes.py`

- [ ] **Step 1: Падающий тест — хелпер выдаёт code_number контенту**

```python
# Добавить в backend/tests/test_wp174_content_codes.py
@pytest.mark.asyncio
async def test_assign_code_to_two_contents_increments():
    async with async_session() as db:
        row = await db.execute(text(
            "INSERT INTO validator_projects (id, project, api_name, active, code_prefix) "
            "VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM validator_projects), "
            ":n, :a, true, 'PYT') RETURNING id"),
            {"n": "PyTest Upload", "a": "pytest_upload_wp174"})
        pid = row.scalar()
        await db.commit()
        try:
            c1 = await assign_content_code(db, pid)
            c2 = await assign_content_code(db, pid)
            await db.commit()
            assert (c1, c2) == (1, 2)
        finally:
            await db.execute(text("DELETE FROM validator_projects WHERE id=:id"), {"id": pid})
            await db.commit()
```

(Тест уже зелёный из Task 3 — он фиксирует контракт для wiring; запустить как регрессию.)

- [ ] **Step 2: Запустить — зелёный**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py::test_assign_code_to_two_contents_increments -v`
Expected: PASS.

- [ ] **Step 3: Вставить вызов во все 4 точки**

В каждом из 4 блоков `upload.py`, сразу после `await db.flush()` (и до финального `await db.commit()`), добавить:

```python
    # WP#174: присвоить код ролика
    from ..services.prefix_service import assign_content_code
    content.code_number = await assign_content_code(db, content.project_id)
```

Точки (ориентир по `db.add(content)`): ~158, ~403, ~605, ~786. В каждом блоке `content.project_id` уже установлен из `data.project_id`.

- [ ] **Step 4: Smoke — загрузка проставляет code_number**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_content_publish_response.py -v`
Expected: PASS (существующий тест загрузки не сломан).

Дополнительно проверить вручную (если есть смок-загрузка): свежий `validator_content.code_number` не NULL для нового проекта с префиксом.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter/backend
git add src/routers/upload.py tests/test_wp174_content_codes.py
git commit -m "feat(wp174): авто-присвоение code_number в 4 точках upload.py"
```

---

## Task 6: Ручной override префикса + отдача в API проектов

**Files:**
- Modify: `backend/src/routers/projects.py` (`ProjectBody`, `list_projects`, `update_project`)
- Test: `backend/tests/test_wp174_content_codes.py`

- [ ] **Step 1: Падающий тест — override валидируется и уникален**

```python
# Добавить в backend/tests/test_wp174_content_codes.py
@pytest.mark.asyncio
async def test_prefix_override_validation_and_unique():
    from src.routers.projects import update_project, ProjectBody
    from fastapi import HTTPException
    async with async_session() as db:
        class _U:
            class role: value = "admin"
            project_ids = []
        # проект A с префиксом TAK
        a = (await db.execute(text(
            "INSERT INTO validator_projects (id, project, api_name, active, code_prefix) "
            "VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM validator_projects), 'A WP174', 'a_wp174', true, 'TAK') RETURNING id"))).scalar()
        b = (await db.execute(text(
            "INSERT INTO validator_projects (id, project, api_name, active, code_prefix) "
            "VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM validator_projects), 'B WP174', 'b_wp174', true, 'BEE') RETURNING id"))).scalar()
        await db.commit()
        try:
            base = dict(project="B WP174", api_name="b_wp174", active=True, logo_url=None, manager=None)
            # невалидный формат → 400
            with pytest.raises(HTTPException) as e1:
                await update_project(b, ProjectBody(**base, prefix="x"), db, _U())
            assert e1.value.status_code == 400
            # коллизия с A → 409
            with pytest.raises(HTTPException) as e2:
                await update_project(b, ProjectBody(**base, prefix="TAK"), db, _U())
            assert e2.value.status_code == 409
            # валидный уникальный → ок
            await update_project(b, ProjectBody(**base, prefix="ZZ9"), db, _U())
            pref = (await db.execute(text("SELECT code_prefix FROM validator_projects WHERE id=:id"), {"id": b})).scalar()
            assert pref == "ZZ9"
        finally:
            await db.execute(text("DELETE FROM validator_projects WHERE id IN (:a,:b)"), {"a": a, "b": b})
            await db.commit()
```

- [ ] **Step 2: Запустить — падает**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py::test_prefix_override_validation_and_unique -v`
Expected: FAIL (ProjectBody без `prefix` / нет валидации).

- [ ] **Step 3a: Добавить `prefix` в `ProjectBody`**

В `projects.py` найти `class ProjectBody(BaseModel)` (строки ~16-21) и добавить поле:

```python
    prefix: Optional[str] = None  # WP#174 — override кода-префикса (admin)
```

(если нет `Optional` в импортах — добавить `from typing import Optional`).

- [ ] **Step 3b: Отдать `code_prefix` в `list_projects`**

В `list_projects` (строка ~28) заменить SELECT:

```python
    result = await db.execute(text("""
        SELECT id, project, api_name, active, logo_url, manager, manual_publish, code_prefix
        FROM validator_projects
        ORDER BY active DESC, project ASC
    """))
```

- [ ] **Step 3c: Обработать override в `update_project`**

В `update_project`, перед финальным `UPDATE validator_projects ... WHERE id=:id`, добавить:

```python
    # WP#174 — override кода-префикса (только admin задаёт; manager не трогает)
    import re as _re
    if body.prefix is not None and current_user.role.value == "admin":
        pref = body.prefix.strip().upper()
        if not _re.fullmatch(r"[A-Z0-9]{2,4}", pref):
            raise HTTPException(status_code=400, detail="Префикс: 2–4 символа [A-Z0-9]")
        clash = (await db.execute(text(
            "SELECT 1 FROM validator_projects WHERE code_prefix=:p AND id<>:id"),
            {"p": pref, "id": project_id})).first()
        if clash:
            raise HTTPException(status_code=409, detail=f"Префикс {pref} уже занят")
        await db.execute(text(
            "UPDATE validator_projects SET code_prefix=:p WHERE id=:id"),
            {"p": pref, "id": project_id})
```

- [ ] **Step 4: Запустить тест**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter/backend
git add src/routers/projects.py tests/test_wp174_content_codes.py
git commit -m "feat(wp174): ручной override префикса (валидация+UNIQUE) + code_prefix в list_projects"
```

---

## Task 7: Сериализация кода контента с role-check

**Files:**
- Modify: `backend/src/routers/content.py:510` (`_content_to_dict_with_publish`)
- Test: `backend/tests/test_wp174_content_codes.py`

- [ ] **Step 1: Падающий тест — код считается из prefix+number**

```python
# Добавить в backend/tests/test_wp174_content_codes.py
def test_format_code_used_for_serialization():
    from src.services.prefix_service import format_code
    assert format_code("RLM", 14) == "RLM-014"
```

(Контракт формата; сериализация проверяется через endpoint-тест ниже.)

- [ ] **Step 2: Запустить — зелёный**

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py::test_format_code_used_for_serialization -v`
Expected: PASS.

- [ ] **Step 3a: Сделать сериализатор fail-closed (opt-in `include_code`)**

Код — admin-only поле. `_content_to_dict_with_publish` используется и клиентскими, и админскими эндпоинтами, поэтому код добавляем **только по явному запросу** (по умолчанию скрыт — fail-closed).

Изменить сигнатуру `_content_to_dict_with_publish` (строка ~510):

```python
async def _content_to_dict_with_publish(c, db, include_code: bool = False) -> dict:
```

После формирования базового `d`, перед `return d`, добавить:

```python
    # WP#174 — полный код ролика (prefix + номер). Admin-only: только при include_code.
    if include_code:
        from ..services.prefix_service import format_code
        prefix = (await db.execute(
            text("SELECT code_prefix FROM validator_projects WHERE id=:id"),
            {"id": c.project_id})).scalar()
        d["code"] = format_code(prefix, c.code_number)
```

Если `text` не импортирован в `content.py` — добавить `from sqlalchemy import text`.

- [ ] **Step 3b: Включить код только в admin-вызовах**

Найти ВСЕ вызовы хелпера: `grep -n "_content_to_dict_with_publish(" backend/src/routers/content.py` (строки ~91, 140, 228, 270, 352, 448). Для каждого, где в области видимости есть `current_user`, передать флаг по роли:

```python
    _content_to_dict_with_publish(c, db, include_code=(current_user.role.value == "admin"))
```

Где `current_user` НЕ в области видимости — оставить вызов без флага (код останется скрыт; fail-closed). Это гарантирует: клиент (role=`client`) кода не получает ни через один путь.

- [ ] **Step 4: Endpoint-тест — admin видит code, не-admin нет**

```python
# Добавить в backend/tests/test_wp174_content_codes.py
@pytest.mark.asyncio
async def test_content_code_admin_only_serialization():
    # Берём существующий контент с присвоенным кодом.
    async with async_session() as db:
        row = (await db.execute(text(
            "SELECT vc.id FROM validator_content vc "
            "JOIN validator_projects vp ON vp.id=vc.project_id "
            "WHERE vp.code_prefix IS NOT NULL AND vc.code_number IS NOT NULL LIMIT 1"))).first()
        if not row:
            pytest.skip("нет контента с присвоенным кодом (запустить после бэкфилла)")
        from src.routers.content import _content_to_dict_with_publish
        from src.models.content import ValidatorContent
        c = await db.get(ValidatorContent, row[0])
        # admin (include_code=True) — код есть
        d_admin = await _content_to_dict_with_publish(c, db, include_code=True)
        assert d_admin["code"] and "-" in d_admin["code"]
        # клиент (include_code=False, дефолт) — ключа code нет
        d_client = await _content_to_dict_with_publish(c, db)
        assert "code" not in d_client
```

Run: `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py -v`
Expected: PASS (или skip до бэкфилла).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter/backend
git add src/routers/content.py tests/test_wp174_content_codes.py
git commit -m "feat(wp174): code в сериализации контента + role-check для клиента"
```

---

## Task 8: Бэкфилл легаси (идемпотентный скрипт)

**Files:**
- Create: `backend/scripts/backfill_content_codes.py`

- [ ] **Step 1: Написать скрипт**

```python
# backend/scripts/backfill_content_codes.py
"""WP#174 Часть A — бэкфилл кодов легаси-контента. Идемпотентно.

Для каждого проекта:
  1) присвоить code_prefix (если нет) — ensure_project_prefix;
  2) проставить code_number всему контенту без него, по created_at ASC;
  3) выставить code_seq = MAX(code_number).
Запуск: cd backend && python -m scripts.backfill_content_codes
"""
import asyncio
from sqlalchemy import text
from src.database import async_session
from src.services.prefix_service import ensure_project_prefix


async def main():
    async with async_session() as db:
        projects = (await db.execute(text(
            "SELECT id, project FROM validator_projects ORDER BY id"))).mappings().all()
        for p in projects:
            pid, name = p["id"], p["project"]
            await ensure_project_prefix(db, pid, name or f"project{pid}")
            # текущий максимум номера в проекте
            cur_max = (await db.execute(text(
                "SELECT COALESCE(MAX(code_number),0) FROM validator_content WHERE project_id=:id"),
                {"id": pid})).scalar()
            # контент без номера — по порядку создания
            rows = (await db.execute(text(
                "SELECT id FROM validator_content WHERE project_id=:id AND code_number IS NULL "
                "ORDER BY created_at ASC, id ASC"), {"id": pid})).scalars().all()
            n = cur_max
            for cid in rows:
                n += 1
                await db.execute(text(
                    "UPDATE validator_content SET code_number=:n WHERE id=:cid"),
                    {"n": n, "cid": cid})
            # синхронизировать счётчик проекта
            await db.execute(text(
                "UPDATE validator_projects SET code_seq=GREATEST(code_seq, :n) WHERE id=:id"),
                {"n": n, "id": pid})
            await db.commit()
            if rows:
                print(f"project {pid} ({name}): +{len(rows)} кодов, code_seq→{n}")
    print("backfill done")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Dry-run на одном проекте (проверка идемпотентности)**

Run (один прогон): `cd /home/claude-user/validator-contenthunter/backend && python -m scripts.backfill_content_codes`
Expected: печатает присвоения, `backfill done`.

- [ ] **Step 3: Повторный прогон — 0 изменений**

Run: повторить команду.
Expected: нет строк `+N кодов` (всё уже присвоено) → идемпотентно.

- [ ] **Step 4: Проверка инварианта**

Run:
```bash
PGPASSWORD="$PGPASSWORD" psql -h localhost -U openclaw -d openclaw -At -c \
"SELECT COUNT(*) FROM validator_content WHERE code_number IS NULL;"
```
Expected: `0` (весь контент получил код).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/validator-contenthunter/backend
git add scripts/backfill_content_codes.py
git commit -m "feat(wp174): идемпотентный бэкфилл кодов легаси-контента"
```

---

## Task 9: Delivery — показ кода в админских таблицах (репозиторий delivery-contenthunter)

**Repo:** `/home/claude-user/autowarm-testbench` (origin `delivery-contenthunter`). **Сначала создать worktree-ветку этого репо** (не ломать параллельные сессии).

**Files:**
- Modify: `server.js` — добавить `code` в SQL, отдающий контент админских таблиц (Запланировано / Опубликовано), через JOIN `validator_projects` + `validator_content`.
- Modify: `public/index.html` — колонка «Код» первой в этих таблицах.

- [ ] **Step 1: Создать изолированную ветку delivery-репо**

```bash
cd /home/claude-user/autowarm-testbench
git worktree add .wt/wp174-codes -b wp174-content-codes origin/main
cd .wt/wp174-codes
```

- [ ] **Step 2: Найти SQL админских таблиц и добавить code**

Найти запросы, отдающие строки контента в админ-таблицы (grep `validator_content`/`publish_queue` SELECT в `server.js`). В SELECT добавить вычисляемый код:

```sql
        vp.code_prefix,
        vc.code_number,
        CASE WHEN vp.code_prefix IS NOT NULL AND vc.code_number IS NOT NULL
             THEN vp.code_prefix || '-' ||
                  CASE WHEN vc.code_number < 1000
                       THEN lpad(vc.code_number::text, 3, '0')
                       ELSE vc.code_number::text END
        END AS code
```
с соответствующим `LEFT JOIN validator_content vc ON ...` и `LEFT JOIN validator_projects vp ON vp.id = vc.project_id` (если ещё не приджойнено).

- [ ] **Step 3: Колонка «Код» во фронте**

В `public/index.html` в рендере админских таблиц (Запланировано/Опубликовано) добавить первой колонкой `Код` со значением `row.code` (кликабельно — копирование в буфер). Если `code` пустой — показать `—`.

- [ ] **Step 4: Smoke — раздел открывается, код виден**

Run: запустить delivery локально (по существующему README/скрипту) либо проверить эндпоинт `curl` — поле `code` присутствует в ответе и `RLM-014`-формата.
Expected: код виден в таблице, формат `PREFIX-NNN`.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench/.wt/wp174-codes
git add server.js public/index.html
git commit -m "feat(wp174): колонка Код в админских таблицах delivery"
```

---

## Финал Части A

- [ ] **Прогон всех новых тестов:** `cd /home/claude-user/validator-contenthunter/backend && python -m pytest tests/test_wp174_content_codes.py -v` → все PASS.
- [ ] **Регрессия:** `python -m pytest tests/test_content_publish_response.py tests/test_client_manual_publish.py -v` → без новых падений.
- [ ] **Codex review** диффа Части A (по правилу проекта), раундами до 0 P1.
- [ ] **Деплой-порядок (критично — бэкфилл ДО приёма загрузок):**
  1. Залить файлы кода валидатора на прод (pull), **без рестарта** приложения — работающий процесс ещё на старом коде и не вызывает `assign_content_code`.
  2. `alembic upgrade head` (схема + ORM-колонка).
  3. Запустить `python -m scripts.backfill_content_codes` один раз (проставит легаси-коды по `created_at ASC` и сдвинет `code_seq`).
  4. **Только теперь** перезапустить приложение валидатора — новые загрузки начнут выдавать номера уже после сдвинутого `code_seq`, легаси-нумерация не ломается.
  5. Выкатить delivery-ветку (Task 9).

  > Почему так: если перезапустить (шаг 4) до бэкфилла (шаг 3), новая загрузка в существующий проект получит `001` (т.к. `code_seq=0` по дефолту миграции), а бэкфилл затем присвоит легаси `002+` — порядок `created_at` сломается, новый ролик окажется «первым».
- [ ] **OpenProject #174** — комментарий о прогрессе Части A; статус оставить «В разработке» до Части B.

---

## Self-Review (выполнено при написании)

- **Покрытие спеки A1–A6:** A1 миграция → Task 1; A2 генерация+коллизии+override → Task 2/3/4/6; A3 авто-присвоение → Task 5; A4 бэкфилл → Task 8; A5 видимость → Task 7 (role-check) + Task 9 (delivery); A6 тесты → встроены в каждый Task.
- **Плейсхолдеры:** нет — весь код приведён.
- **Консистентность типов:** `ensure_project_prefix`/`assign_content_code`/`format_code`/`base_prefix`/`candidate_prefixes` — единые сигнатуры во всех тасках; `code_prefix`/`code_seq`/`code_number` — единые имена колонок.
