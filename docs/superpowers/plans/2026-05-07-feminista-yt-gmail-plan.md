# Feminista YT-gmail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть NULL gmail gap для YT-аккаунтов в `factory_inst_accounts`: gmail обязателен на создании в UI/backend, Ревизия дозаполняет NULL для зарегистрированных строк.

**Architecture:** Новый shared-модуль `yt_gmail_probe.py` (pure-функции + ADB-обёртка), переиспользуется `backfill_yt_gmails.py` и `account_revision.py`. UI/backend в `public/index.html` + `server.js` принимают/отдают gmail. Backfill пишет только когда gmail IS NULL (никогда не перезаписывает ручной ввод).

**Tech Stack:** Python 3 (psycopg2, regex parsing UI dump), Node.js Express + pg, vanilla JS frontend, pytest.

**Spec:** `docs/superpowers/specs/2026-05-07-feminista-yt-gmail-design.md`

**Repo:** `/home/claude-user/autowarm-testbench/` (branch `testbench` → prod main, `GenGo2/delivery-contenthunter`)

---

## File Structure

**Создаётся:**
- `yt_gmail_probe.py` — shared YT picker probe (root репы)
- `tests/test_yt_gmail_probe.py` — pytest tests for probe
- `tests/fixtures/yt_picker_*.xml` — XML фикстуры (3-4 штуки для разных кейсов)

**Модифицируется:**
- `backfill_yt_gmails.py` — рефактор поверх `yt_gmail_probe`
- `account_revision.py` — `discover_gmails` через probe + backfill NULL шаг в `run()`
- `server.js` — 4 endpoint'а (POST/PUT/GET/GET packages/accounts)
- `public/index.html` — gmail input в форме + render + edit
- `tests/test_revision_real_adb.py` — добавить gmail-backfill assertion

**Backend smoke:** `scripts/test_packages_gmail.js` (новый, по образцу `scripts/test_revision_adb.js`)

---

## Task 1: `yt_gmail_probe.extract_yt_picker_pairs` (pure XML parser)

**Files:**
- Create: `yt_gmail_probe.py`
- Create: `tests/test_yt_gmail_probe.py`
- Create: `tests/fixtures/yt_picker_two_rows.xml`
- Create: `tests/fixtures/yt_picker_empty.xml`
- Create: `tests/fixtures/yt_picker_with_deleted.xml`

- [ ] **Step 1: Write fixture `yt_picker_two_rows.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node text="Makiavelli Inakent" content-desc="Makiavelli Inakent makiavelli485@gmail.com 5 тыс. подписчиков" clickable="true" bounds="[0,400][1080,600]"/>
  <node text="Feminista patches" content-desc="Feminista patches feminista155@gmail.com Нет подписчиков" clickable="true" bounds="[0,600][1080,800]"/>
  <node text="Добавить аккаунт" content-desc="" clickable="true" bounds="[0,900][1080,1080]"/>
</hierarchy>
```

- [ ] **Step 2: Write fixture `yt_picker_empty.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node text="Добавить аккаунт" content-desc="" clickable="true" bounds="[0,900][1080,1080]"/>
</hierarchy>
```

- [ ] **Step 3: Write fixture `yt_picker_with_deleted.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node text="Born Trip" content-desc="Born Trip born.trip90@gmail.com Канал удалён" clickable="true" bounds="[0,400][1080,600]"/>
  <node text="Active Channel" content-desc="Active Channel active@gmail.com 100 подписчиков" clickable="true" bounds="[0,600][1080,800]"/>
</hierarchy>
```

- [ ] **Step 4: Write failing test `test_extract_yt_picker_pairs`**

```python
# tests/test_yt_gmail_probe.py
import os
from pathlib import Path

import pytest

from yt_gmail_probe import extract_yt_picker_pairs

FIXTURES = Path(__file__).parent / 'fixtures'


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


def test_extract_two_rows():
    xml = _load('yt_picker_two_rows.xml')
    pairs = extract_yt_picker_pairs(xml)
    assert ('Makiavelli Inakent', 'makiavelli485@gmail.com') in pairs
    assert ('Feminista patches', 'feminista155@gmail.com') in pairs
    assert len(pairs) == 2


def test_extract_empty_picker():
    xml = _load('yt_picker_empty.xml')
    pairs = extract_yt_picker_pairs(xml)
    assert pairs == []


def test_extract_skips_deleted_channels():
    xml = _load('yt_picker_with_deleted.xml')
    pairs = extract_yt_picker_pairs(xml)
    # «Канал удалён» row should NOT be included
    gmails = [g for _, g in pairs]
    assert 'born.trip90@gmail.com' not in gmails
    assert 'active@gmail.com' in gmails
```

- [ ] **Step 5: Run failing test**

```bash
cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_gmail_probe.py::test_extract_two_rows -v
```

Expected: `ImportError` или `ModuleNotFoundError: No module named 'yt_gmail_probe'`

- [ ] **Step 6: Implement `extract_yt_picker_pairs`**

Скопировать regex-логику из `backfill_yt_gmails.py:50-110` (constants `GMAIL_RE`, `HANDLE_RE`, `DELETED_LABEL_RE`) и парсинг row-XML — выделить в чистую функцию. Создать `/home/claude-user/autowarm-testbench/yt_gmail_probe.py`:

```python
"""yt_gmail_probe.py — общий модуль для парсинга YT account picker'а.

Используется:
- backfill_yt_gmails.py — bulk-обновление gmail для существующих YT-аккаунтов
- account_revision.py — auto-fill NULL gmail для зарегистрированных YT-строк
"""
import logging
import re
import subprocess
import time
from typing import Optional

log = logging.getLogger('yt_gmail_probe')

# Constants (заимствуются из backfill_yt_gmails.py — должны быть identical).
YT_PACKAGE = 'com.google.android.youtube'
YT_LAUNCH_ACTIVITY = (
    'com.google.android.youtube/'
    'com.google.android.apps.youtube.app.WatchWhileActivity'
)
PROFILE_TAB_COORDS = (972, 2320)

GMAIL_RE = re.compile(r'[a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.IGNORECASE)
DELETED_LABEL_RE = re.compile(
    r'канал\s+удал[её]н|channel\s+(?:deleted|removed)', re.IGNORECASE,
)

# XML node-text+content-desc parsing (uiautomator dump format).
NODE_RE = re.compile(
    r'<node\s+[^>]*?text="(?P<text>[^"]*)"[^>]*?content-desc="(?P<desc>[^"]*)"[^>]*?/?>'
)


def extract_yt_picker_pairs(xml: str) -> list[tuple[str, str]]:
    """Парс XML uiautomator dump'а YT account picker'а в (display_name, gmail) пары.

    Игнорирует rows с «Канал удалён» (DELETED_LABEL_RE).
    Возвращает [] если picker пустой / не загружен.
    """
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in NODE_RE.finditer(xml):
        text = match.group('text').strip()
        desc = match.group('desc').strip()
        if not text or not desc:
            continue
        if DELETED_LABEL_RE.search(desc):
            log.debug('skip deleted channel row: text=%r', text)
            continue
        gm = GMAIL_RE.search(desc)
        if not gm:
            continue
        gmail = gm.group(0).lower()
        pair = (text, gmail)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return pairs
```

- [ ] **Step 7: Run tests, verify pass**

```bash
cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_gmail_probe.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add yt_gmail_probe.py tests/test_yt_gmail_probe.py tests/fixtures/yt_picker_*.xml && \
  git commit -m "feat(yt-gmail): add yt_gmail_probe.extract_yt_picker_pairs"
```

---

## Task 2: `yt_gmail_probe.match_gmail_to_handle`

**Files:**
- Modify: `yt_gmail_probe.py`
- Modify: `tests/test_yt_gmail_probe.py`

- [ ] **Step 1: Write failing tests for `match_gmail_to_handle`**

Append to `tests/test_yt_gmail_probe.py`:

```python
from yt_gmail_probe import match_gmail_to_handle


def test_match_exact_display_name():
    pairs = [('makiavelli485', 'makiavelli485@gmail.com')]
    assert match_gmail_to_handle('makiavelli485', pairs) == 'makiavelli485@gmail.com'


def test_match_handle_matches_gmail_prefix():
    pairs = [('Feminista patches', 'feminista155@gmail.com')]
    # handle (snake_case) should match gmail prefix when display has spaces/case differences
    # (Display 'Feminista patches' тэг handle 'feminista_patches' — gmail prefix 'feminista155'
    #  не совпадает; этот случай вернёт None и оператор введёт руками.)
    # Реалистичный hit: handle совпадает с gmail-prefix.
    pairs2 = [('Some Channel', 'feminista_patches@gmail.com')]
    assert match_gmail_to_handle('feminista_patches', pairs2) == 'feminista_patches@gmail.com'


def test_match_handle_in_display_name_normalized():
    # 'feminista_patches' ↔ display 'Feminista Patches' (lower+strip spaces+underscores)
    pairs = [('Feminista Patches', 'fem155@gmail.com')]
    assert match_gmail_to_handle('feminista_patches', pairs) == 'fem155@gmail.com'


def test_match_no_candidates():
    pairs = [('OtherChannel', 'other@gmail.com')]
    assert match_gmail_to_handle('feminista_patches', pairs) is None


def test_match_ambiguous_returns_none():
    # Если 2 пары матчат — None (caller логирует).
    pairs = [
        ('Feminista A', 'fem_a@gmail.com'),
        ('Feminista B', 'fem_b@gmail.com'),
    ]
    # Handle 'feminista' матчит обоим display'ам
    assert match_gmail_to_handle('feminista', pairs) is None
```

- [ ] **Step 2: Run failing test**

```bash
cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_gmail_probe.py::test_match_exact_display_name -v
```

Expected: `ImportError` (function not yet defined).

- [ ] **Step 3: Implement `match_gmail_to_handle`**

Append to `yt_gmail_probe.py`:

```python
def _normalize(s: str) -> str:
    """lowercase, удалить пробелы/точки/подчёркивания/тире для сравнения."""
    return re.sub(r'[\s._-]+', '', s).lower()


def match_gmail_to_handle(
    handle: str,
    pairs: list[tuple[str, str]],
) -> Optional[str]:
    """Найти gmail для @handle в списке пар (display_name, gmail).

    Стратегия (порядок попыток):
      1. exact match: normalize(display_name) == normalize(handle)
      2. gmail-prefix match: gmail.split('@')[0] (нормализованный) == normalize(handle)
      3. substring: normalize(handle) in normalize(display_name)

    Если найдено 0 → None.
    Если найдено >1 (ambiguous) → None.
    Если 1 → gmail.
    """
    if not handle or not pairs:
        return None
    h = _normalize(handle)
    candidates: list[str] = []
    for display, gmail in pairs:
        d = _normalize(display)
        gprefix = _normalize(gmail.split('@', 1)[0])
        if d == h or gprefix == h or h in d:
            if gmail not in candidates:
                candidates.append(gmail)
    if len(candidates) == 1:
        return candidates[0]
    return None
```

- [ ] **Step 4: Run all tests, verify pass**

```bash
cd /home/claude-user/autowarm-testbench && python -m pytest tests/test_yt_gmail_probe.py -v
```

Expected: 8 passed (3 from Task 1 + 5 new).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add yt_gmail_probe.py tests/test_yt_gmail_probe.py && \
  git commit -m "feat(yt-gmail): add match_gmail_to_handle with ambiguity handling"
```

---

## Task 3: `yt_gmail_probe.probe_yt_gmails_live` (ADB обёртка)

**Files:**
- Modify: `yt_gmail_probe.py`

- [ ] **Step 1: Изучить ADB-логику в `backfill_yt_gmails.py`**

Прочитать `backfill_yt_gmails.py:140-260` (функции `adb_shell`, `process_device`, открытие YT picker'а). Скопировать минимум: launch YT → tap profile → tap account-switch → uiautomator dump → pull XML. Это будет ядро `probe_yt_gmails_live`.

```bash
cd /home/claude-user/autowarm-testbench && nl -ba backfill_yt_gmails.py | sed -n '140,260p'
```

- [ ] **Step 2: Реализовать `probe_yt_gmails_live`**

Append to `yt_gmail_probe.py`:

```python
def adb_shell(host: str, port: int, serial: str, cmd: str, timeout: int = 30) -> str:
    """Запустить shell-команду через remote ADB server."""
    full = ['adb', '-H', host, '-P', str(port), '-s', serial, 'shell', cmd]
    result = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        log.warning('adb_shell failed: %s stderr=%r', cmd, result.stderr.strip())
    return result.stdout


def adb_pull_dump(host: str, port: int, serial: str, dest_local: str) -> str:
    """uiautomator dump → pull → return XML string."""
    adb_shell(host, port, serial, 'rm -f /sdcard/window_dump.xml')
    adb_shell(host, port, serial, 'uiautomator dump /sdcard/window_dump.xml', timeout=20)
    pull = subprocess.run(
        ['adb', '-H', host, '-P', str(port), '-s', serial,
         'pull', '/sdcard/window_dump.xml', dest_local],
        capture_output=True, text=True, timeout=20,
    )
    if pull.returncode != 0:
        log.warning('adb pull window_dump failed: %s', pull.stderr.strip())
        return ''
    try:
        with open(dest_local, encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        log.warning('read window_dump failed: %s', e)
        return ''


def probe_yt_gmails_live(
    adb_host: str,
    adb_port: int,
    serial: str,
    dump_dir: str = '/tmp/autowarm_ui_dumps',
) -> list[tuple[str, str]]:
    """Открыть YT, тапнуть picker, дампнуть UI, вернуть пары.

    Side effects: am force-stop YT → launch → tap profile-tab → tap account-row →
    uiautomator dump. Не закрывает YT.
    Возвращает [] при любой ошибке (caller продолжает основной flow).
    """
    import os
    os.makedirs(dump_dir, exist_ok=True)
    try:
        adb_shell(adb_host, adb_port, serial, f'am force-stop {YT_PACKAGE}')
        time.sleep(1)
        adb_shell(adb_host, adb_port, serial, f'am start -n {YT_LAUNCH_ACTIVITY}')
        time.sleep(4)
        # Тап profile tab
        adb_shell(adb_host, adb_port, serial,
                  f'input tap {PROFILE_TAB_COORDS[0]} {PROFILE_TAB_COORDS[1]}')
        time.sleep(2)
        # Дампим текущий экран — должен быть профиль с строкой "Сменить аккаунт".
        # Здесь упрощение: тапаем по фиксированным координатам account-switch row,
        # которые `backfill_yt_gmails.py` использует. Если фейлим — pairs=[].
        # Picker откроется bottom-sheet'ом.
        # NB: при реальной проблеме UI дрейфа — caller увидит pairs=[] и no-op.
        # TODO в импле: переиспользовать selector-based logic из backfill_yt_gmails
        # вместо hardcoded coords. Это перенесёт всю «open picker» логику в общий слой.
        # Здесь оставляем тонкий wrapper — реальную navigation-логику переносим
        # на refactor этапе Task 4.
        dest = f'{dump_dir}/yt_gmail_probe_{serial}_{int(time.time())}.xml'
        xml = adb_pull_dump(adb_host, adb_port, serial, dest)
        if not xml:
            return []
        return extract_yt_picker_pairs(xml)
    except Exception as e:
        log.warning('probe_yt_gmails_live failed: %s', e)
        return []
```

> **Уточнение:** Эта реализация — placeholder для thin-обёртки. Полная navigation-логика (открытие account-switch row через selector, не coords) переносится из `backfill_yt_gmails.py.process_device` в Task 4 при рефакторинге. Тогда `probe_yt_gmails_live` станет полноценным.

- [ ] **Step 3: Smoke-проверка импорта**

```bash
cd /home/claude-user/autowarm-testbench && python -c "from yt_gmail_probe import probe_yt_gmails_live; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add yt_gmail_probe.py && \
  git commit -m "feat(yt-gmail): add probe_yt_gmails_live ADB wrapper (thin)"
```

---

## Task 4: Refactor `backfill_yt_gmails.py` to use `yt_gmail_probe`

**Files:**
- Modify: `backfill_yt_gmails.py`

**Цель:** Заменить inline regex/parsing/navigation в `backfill_yt_gmails.py` на вызовы `yt_gmail_probe`. CLI поведение не меняется. Перенести полную navigation-логику (selector-based) в `yt_gmail_probe.probe_yt_gmails_live`, чтобы `account_revision.py` тоже её получил.

- [ ] **Step 1: Прочитать `backfill_yt_gmails.py.process_device` целиком**

```bash
cd /home/claude-user/autowarm-testbench && grep -n "def process_device\|def open_picker\|def parse_picker\|def main" backfill_yt_gmails.py
```

Найти функции `process_device` (или эквивалент), которые: open YT, navigate to account picker, dump UI, parse pairs, match handles.

- [ ] **Step 2: Перенести navigation-логику (open YT picker через selector) в `yt_gmail_probe.probe_yt_gmails_live`**

Заменить TODO-placeholder из Task 3 на реальный код из `backfill_yt_gmails.py`. Ключевая логика — `selector-based open` account-switch row (не hardcoded coords). Структура итоговой функции:

```python
def probe_yt_gmails_live(...) -> list[tuple[str, str]]:
    # 1. force-stop + launch YT
    # 2. dump-and-find profile-tab → tap (selector через uiautomator dump)
    # 3. dump-and-find account-switch row → tap
    # 4. wait for picker bottom-sheet
    # 5. dump → extract_yt_picker_pairs
    # 6. return pairs
```

(Точный код берётся из `backfill_yt_gmails.py` 1-в-1 без изменения логики.)

- [ ] **Step 3: Заменить inline parsing в `backfill_yt_gmails.py` на импорт**

В начале `backfill_yt_gmails.py` добавить:

```python
from yt_gmail_probe import (
    GMAIL_RE,
    DELETED_LABEL_RE,
    extract_yt_picker_pairs,
    match_gmail_to_handle,
    probe_yt_gmails_live,
)
```

Удалить дубликаты констант (GMAIL_RE, DELETED_LABEL_RE) и parsing-функций. `process_device` теперь вызывает `probe_yt_gmails_live(...)`, получает пары, итерирует с `match_gmail_to_handle` для каждого username.

- [ ] **Step 4: Smoke-test CLI остался работающим (offline mode)**

Убедиться, что `--dump <path>` вариант работает на существующем фикстуре:

```bash
cd /home/claude-user/autowarm-testbench && python3 backfill_yt_gmails.py --device-number 9999 --dump tests/fixtures/yt_picker_two_rows.xml --dry-run 2>&1 | head -20
```

Expected: вывод вида `[dry-run] UPDATE factory_inst_accounts SET gmail=...` либо `device_number=9999 не найден` (если 9999 не в БД — ОК, проверяем что сам парсинг отработал до DB-step).

- [ ] **Step 5: Run pytest всей tests/ — регрессии не должно быть**

```bash
cd /home/claude-user/autowarm-testbench && python -m pytest tests/ -q --ignore=tests/test_revision_real_adb.py --ignore=tests/test_revision_tiktok_virtual.py 2>&1 | tail -30
```

Expected: все ранее зелёные тесты остались зелёными (не считая helper-тесты что требуют ADB).

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add backfill_yt_gmails.py yt_gmail_probe.py && \
  git commit -m "refactor(yt-gmail): migrate backfill_yt_gmails.py onto shared probe module"
```

---

## Task 5: `account_revision.py.discover_gmails` refactor + backward compat

**Files:**
- Modify: `account_revision.py`

- [ ] **Step 1: Прочитать текущую `discover_gmails` и место вызова в `run()`**

```bash
cd /home/claude-user/autowarm-testbench && sed -n '275,315p' account_revision.py && echo "---" && sed -n '500,605p' account_revision.py
```

- [ ] **Step 2: Заменить `discover_gmails` на тонкую обёртку над `yt_gmail_probe.probe_yt_gmails_live`**

В `account_revision.py`:

```python
# В imports добавить:
from yt_gmail_probe import probe_yt_gmails_live, match_gmail_to_handle


# Заменить тело discover_gmails (≈275-310):
def discover_gmails(self) -> list[tuple[str, str]]:
    """Открывает YT picker устройства и возвращает (display_name, gmail) пары.

    Возвращает [] при любой ошибке (revision продолжается без gmail-сведений).
    """
    return probe_yt_gmails_live(
        adb_host=self.adb_host,
        adb_port=self.adb_port,
        serial=self.device_serial,
    )
```

- [ ] **Step 3: Обновить вызов в `run()` — backward compat для frontend**

В `run()` найти строку `result['gmails'] = self.discover_gmails()` (≈510). Заменить на:

```python
self._progress('gmails', 'Поиск Gmail аккаунтов...', 15)
pairs = self.discover_gmails()
result['gmails_pairs'] = [
    {'display_name': d, 'gmail': g} for d, g in pairs
]
result['gmails'] = [g for _, g in pairs]  # backward-compat для frontend chip-render
```

- [ ] **Step 4: Проверить, что строки 550, 585, 599 (которые читают `result['gmails']`) продолжают работать**

```bash
cd /home/claude-user/autowarm-testbench && sed -n '545,600p' account_revision.py
```

Verify: 
- строка ~550 `gmail = result['gmails'][0] if len(...) == 1 else None` — продолжает работать (list[str]).
- строка ~585 `for gmail in result['gmails']:` — итерирует по str.
- строка ~599 `len(result['gmails']) > 0` — int.

Никаких code-changes здесь не нужно.

- [ ] **Step 5: Smoke import test**

```bash
cd /home/claude-user/autowarm-testbench && python -c "from account_revision import AccountRevision; print('OK')"
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add account_revision.py && \
  git commit -m "refactor(revision): discover_gmails via yt_gmail_probe + backward-compat result.gmails"
```

---

## Task 6: `account_revision.py.run()` — NULL gmail backfill step

**Files:**
- Modify: `account_revision.py`

- [ ] **Step 1: Найти точку вставки в `run()`**

Backfill step должен идти ПОСЛЕ `per_platform_status` цикла (≈582) и ДО финального `result['errors']` (≈597). 

```bash
cd /home/claude-user/autowarm-testbench && sed -n '575,605p' account_revision.py
```

- [ ] **Step 2: Добавить backfill step**

Вставить блок после строки `logger.info('[revision] summary: %s', per_platform_status)`:

```python
        # === Backfill NULL gmails для зарегистрированных YT-строк device'а ===
        self._progress('gmails_backfill', 'Дозаполнение gmail для YouTube...', 80)
        backfilled: list[dict] = []
        if pairs:  # pairs из discover_gmails в Task 5
            try:
                with psycopg2.connect(DB_DSN) as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT fia.id, fia.username
                          FROM factory_inst_accounts fia
                          JOIN factory_pack_accounts fpa ON fpa.id = fia.pack_id
                         WHERE fpa.device_num_id = %s
                           AND fia.platform = 'youtube'
                           AND fia.active = TRUE
                           AND fia.gmail IS NULL
                        """,
                        (self.device_num_id,),
                    )
                    rows = cur.fetchall()
            except Exception as e:
                logger.warning('[revision] gmail_backfill_select_failed: %s', e)
                rows = []
            for acc_id, username in rows:
                gmail = match_gmail_to_handle(username, pairs)
                if not gmail:
                    logger.info('[revision] gmail_no_match handle=%s', username)
                    continue
                try:
                    with psycopg2.connect(DB_DSN) as conn, conn.cursor() as cur:
                        cur.execute(
                            'UPDATE factory_inst_accounts SET gmail=%s '
                            'WHERE id=%s AND gmail IS NULL',
                            (gmail.lower(), acc_id),
                        )
                        conn.commit()
                        if cur.rowcount == 1:
                            backfilled.append({
                                'account_id': acc_id,
                                'username': username,
                                'gmail': gmail.lower(),
                            })
                            logger.info(
                                '[revision] gmail_backfilled handle=%s gmail=%s',
                                username, gmail,
                            )
                except Exception as e:
                    logger.warning(
                        '[revision] gmail_backfill_update_failed handle=%s err=%s',
                        username, e,
                    )
                    continue
        result['gmails_backfilled'] = backfilled
```

> **Note:** `pairs` нужно сохранить в локальную переменную в Task 5 — `pairs = self.discover_gmails()` уже это делает. Если переменная вне scope здесь, дополнить: преобразовать обратно из `result['gmails_pairs']`:
>
> ```python
> pairs = [(p['display_name'], p['gmail']) for p in result['gmails_pairs']]
> ```

- [ ] **Step 3: Smoke import test**

```bash
cd /home/claude-user/autowarm-testbench && python -c "from account_revision import AccountRevision; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Live ADB integration test (опционально, требует phone #19 testbench)**

```bash
cd /home/claude-user/autowarm-testbench && \
  PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
    UPDATE factory_inst_accounts SET gmail=NULL WHERE id=(
      SELECT fia.id FROM factory_inst_accounts fia
      JOIN factory_pack_accounts fpa ON fpa.id=fia.pack_id
      JOIN factory_device_numbers fdn ON fdn.id=fpa.device_num_id
      WHERE fdn.device_number=19 AND fia.platform='youtube' AND fia.active=true LIMIT 1
    );
  " && \
  REV_DEVICE_SERIAL=<serial> REV_ADB_HOST=82.115.54.26 REV_ADB_PORT=<port> \
  REV_DEVICE_NUM_ID=<id> python3 account_revision.py --device-serial <serial> \
  --adb-host 82.115.54.26 --adb-port <port> --device-num-id <id> | jq .gmails_backfilled
```

Expected: `gmails_backfilled` содержит ту YT-строку с восстановленным gmail.

(Если testbench недоступен — пропустить этот step, валидация в Task 12 при deploy.)

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add account_revision.py && \
  git commit -m "feat(revision): backfill NULL gmail for registered YT accounts on device"
```

---

## Task 7: Backend POST `/api/packages/:id/accounts` — accept gmail

**Files:**
- Modify: `server.js` (line ≈3802)

- [ ] **Step 1: Прочитать текущий handler**

```bash
cd /home/claude-user/autowarm-testbench && sed -n '3800,3845p' server.js
```

- [ ] **Step 2: Изменить handler — принимать и валидировать gmail**

Найти `app.post('/api/packages/:id/accounts', requireAuth, async (req, res) => {` (строка ≈3803). Заменить тело handler'а:

```javascript
app.post('/api/packages/:id/accounts', requireAuth, async (req, res) => {
  try {
    const packId = parseInt(req.params.id);
    const { platform, username, user_id, active, gmail } = req.body;
    if (!platform || !username) {
      return res.status(400).json({ error: 'platform и username обязательны' });
    }
    // Gmail validation (только для YouTube)
    let gmailNorm = null;
    if (platform === 'youtube') {
      if (!gmail || !String(gmail).trim()) {
        return res.status(400).json({ error: 'gmail обязателен для YouTube' });
      }
      gmailNorm = String(gmail).trim().toLowerCase();
      if (!gmailNorm.includes('@')) {
        return res.status(400).json({ error: 'gmail должен содержать @' });
      }
    }
    // Проверяем дубль по username+platform
    const dupUser = await pool.query(
      'SELECT id, username, active FROM factory_inst_accounts WHERE pack_id=$1 AND platform=$2 AND LOWER(username)=LOWER($3)',
      [packId, platform, username]
    );
    if (dupUser.rows.length > 0) {
      return res.status(409).json({ error: `Аккаунт @${username} уже есть в этом паке`, duplicate_username: true });
    }
    // Проверяем активный дубль по платформе
    const dupActive = await pool.query(
      'SELECT id, username FROM factory_inst_accounts WHERE pack_id=$1 AND platform=$2 AND active=true',
      [packId, platform]
    );
    if (dupActive.rows.length > 0) {
      return res.status(409).json({
        error: `В паке уже есть активный аккаунт ${platform}: @${dupActive.rows[0].username}`,
        duplicate_active: true,
        existing_username: dupActive.rows[0].username
      });
    }
    const { rows } = await pool.query(
      `INSERT INTO factory_inst_accounts (pack_id, platform, username, instagram_id, active, gmail, synced_at)
       VALUES ($1,$2,$3,$4,$5,$6,NOW()) RETURNING id, username, instagram_id AS user_id, platform, active, gmail, date_last_parsing`,
      [packId, platform, username, user_id || null, active !== false, gmailNorm]
    );
    const newAcc = rows[0];
    console.log(`[api/packages/accounts] insert pack=${packId} platform=${platform} acc=${username} gmail=${gmailNorm || 'null'} → factory_inst_accounts.id=${newAcc.id} user_id=${newAcc.user_id || 'pending'}`);
    if (!newAcc.user_id) triggerIdParsing(newAcc.id, platform, username);
    res.json(newAcc);
  } catch(e) { res.status(500).json({ error: e.message }); }
});
```

- [ ] **Step 3: Сделать `node --check` для синтаксиса**

```bash
cd /home/claude-user/autowarm-testbench && node --check server.js && echo "syntax-ok"
```

Expected: `syntax-ok`.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add server.js && \
  git commit -m "feat(packages): POST /accounts validates+persists gmail (YT required)"
```

---

## Task 8: Backend PUT `/api/packages/accounts/:accountId` — accept gmail with clear-protection

**Files:**
- Modify: `server.js` (line ≈3841)

- [ ] **Step 1: Прочитать текущий handler**

```bash
cd /home/claude-user/autowarm-testbench && sed -n '3841,3860p' server.js
```

- [ ] **Step 2: Изменить handler**

Заменить тело PUT handler'а:

```javascript
app.put('/api/packages/accounts/:accountId', requireAuth, async (req, res) => {
  try {
    const accId = req.params.accountId;
    const { username, active, gmail } = req.body;
    // Прочитать current row для проверки clear-to-NULL и платформы
    const { rows: [cur] } = await pool.query(
      'SELECT platform, gmail FROM factory_inst_accounts WHERE id=$1', [accId]
    );
    if (!cur) return res.status(404).json({ error: 'Аккаунт не найден' });
    let gmailUpdate = cur.gmail;  // default: оставить как есть (для не-YT всегда NULL)
    if (gmail !== undefined) {
      const trimmed = gmail === null ? '' : String(gmail).trim();
      if (cur.platform === 'youtube' && cur.gmail && !trimmed) {
        return res.status(400).json({ error: 'нельзя очистить gmail у существующего аккаунта' });
      }
      if (trimmed) {
        const g = trimmed.toLowerCase();
        if (!g.includes('@')) {
          return res.status(400).json({ error: 'gmail должен содержать @' });
        }
        gmailUpdate = g;
      } else if (cur.platform !== 'youtube') {
        // не-YT может очистить (gmail для них не имеет смысла)
        gmailUpdate = null;
      }
    }
    const { rows } = await pool.query(
      `UPDATE factory_inst_accounts SET username=$1, active=$2, gmail=$3
       WHERE id=$4 RETURNING id, username, instagram_id AS user_id, platform, active, gmail, date_last_parsing`,
      [username, active !== false, gmailUpdate, accId]
    );
    if (!rows.length) return res.status(404).json({ error: 'Аккаунт не найден' });
    const acc = rows[0];
    if (!acc.user_id) triggerIdParsing(acc.id, acc.platform, acc.username);
    res.json(acc);
  } catch(e) { res.status(500).json({ error: e.message }); }
});
```

- [ ] **Step 3: Syntax check**

```bash
cd /home/claude-user/autowarm-testbench && node --check server.js && echo "syntax-ok"
```

Expected: `syntax-ok`.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add server.js && \
  git commit -m "feat(packages): PUT /accounts accepts gmail with clear-to-NULL protection"
```

---

## Task 9: Backend GET endpoints return gmail

**Files:**
- Modify: `server.js` (lines ≈3793 + ≈3328-3350)

- [ ] **Step 1: GET `/api/packages/:id/accounts` — добавить gmail в SELECT**

Найти handler GET `/api/packages/:id/accounts` (строка ≈3789). Заменить SQL:

```javascript
// Было:
// SELECT id, username, instagram_id AS user_id, platform, active, date_last_parsing
// Стало:
const { rows } = await pool.query(
  `SELECT id, username, instagram_id AS user_id, platform, active, gmail, date_last_parsing
   FROM factory_inst_accounts WHERE pack_id=$1 ORDER BY platform`,
  [req.params.id]
);
```

- [ ] **Step 2: GET `/api/packages` — добавить gmail в JSON_AGG**

Найти handler `app.get('/api/packages', ...)` (строка ≈3316). В JSON_BUILD_OBJECT добавить gmail:

```javascript
// Было:
// JSON_BUILD_OBJECT('platform', fia.platform, 'username', fia.username, 'active', fia.active, 'user_id', fia.instagram_id)
// Стало:
JSON_BUILD_OBJECT(
  'platform', fia.platform,
  'username', fia.username,
  'active', fia.active,
  'user_id', fia.instagram_id,
  'gmail', fia.gmail
)
```

- [ ] **Step 3: Syntax + smoke**

```bash
cd /home/claude-user/autowarm-testbench && node --check server.js && echo "syntax-ok"
```

Smoke smoke (если PM2 server запущен на dev/test endpoint):

```bash
curl -s -b "session=<test-session>" http://localhost:3000/api/packages?project=Feminista | jq '.[0].accounts'
```

Expected: каждый объект содержит ключ `gmail` (`null` для существующих, заполненный для будущих YT).

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add server.js && \
  git commit -m "feat(packages): GET endpoints return gmail field"
```

---

## Task 10: Frontend — gmail input в `pkgShowAddAccountRow`

**Files:**
- Modify: `public/index.html` (line ≈8941)

- [ ] **Step 1: Прочитать текущий `pkgShowAddAccountRow`**

```bash
cd /home/claude-user/autowarm-testbench && sed -n '8941,8990p' public/index.html
```

- [ ] **Step 2: Добавить gmail-cell в новую строку (после username, до user_id)**

Найти ячейку с `<input id="new-acc-username">`. После неё добавить:

```html
    <td class="px-3 py-2">
      <input id="new-acc-gmail" type="text" placeholder="gmail (для YT)"
        class="w-full border border-indigo-300 rounded-lg px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-indigo-400"
        style="display:none;">
    </td>
```

И добавить onChange-handler на selector platform — найти `<select id="new-acc-platform" ...>` в `pkgShowAddAccountRow`. После того, как `tbody.appendChild(newRow)` выполнен, добавить:

```javascript
  // Toggle gmail visibility based on platform
  const platformSel = document.getElementById('new-acc-platform');
  const gmailInp = document.getElementById('new-acc-gmail');
  const togglePlatform = () => {
    gmailInp.style.display = (platformSel.value === 'youtube') ? '' : 'none';
    if (platformSel.value !== 'youtube') gmailInp.value = '';
  };
  platformSel.addEventListener('change', togglePlatform);
  togglePlatform();  // initial
```

- [ ] **Step 3: Обновить `pkgSaveNewAccount` — read+validate gmail**

Найти `async function pkgSaveNewAccount(forceInactive = false)` (строка ≈8988). После строки `const active = forceInactive ? false : ...`:

```javascript
  const gmail = (document.getElementById('new-acc-gmail')?.value || '').trim();
  if (platform === 'youtube') {
    if (!gmail) { toast('Для YouTube gmail обязателен', 'error'); return; }
    if (!gmail.includes('@')) { toast('gmail должен содержать @', 'error'); return; }
  }
```

И в payload `body: JSON.stringify({...})` добавить `gmail`:

```javascript
    body: JSON.stringify({ platform, username, user_id, active, gmail: platform === 'youtube' ? gmail : null })
```

- [ ] **Step 4: Manual smoke (на dev VPS)**

Открыть testbench UI → Паки → создать тестовый пак на test-устройстве → добавить YT-аккаунт без gmail → toast об ошибке. Снова с gmail → success.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add public/index.html && \
  git commit -m "feat(packages-ui): gmail input in add-account row (required for YT)"
```

---

## Task 11: Frontend — gmail в account-row (display + edit)

**Files:**
- Modify: `public/index.html` (line ≈8822 — `pkgLoadAccounts`, ≈8893 — `pkgSaveAccount`)

- [ ] **Step 1: Найти render существующих account-rows**

```bash
cd /home/claude-user/autowarm-testbench && sed -n '8820,8895p' public/index.html
```

Идентифицировать template-string (или DOM-construction) для отображения существующих аккаунтов в pack-modal'е.

- [ ] **Step 2: Добавить gmail-cell в render**

В template-string для account-row добавить ячейку (рядом с username), показывающую `${a.gmail || '—'}` для YT и пустое для остальных. Если используется input `.acc-username-input`, рядом добавить `.acc-gmail-input`:

```html
<input class="acc-gmail-input" type="text" placeholder="gmail" value="${a.gmail || ''}"
  style="display:${a.platform === 'youtube' ? '' : 'none'};">
```

(Конкретный markup — в стиле существующего render'а, по соседству с `.acc-username-input`.)

- [ ] **Step 3: Обновить `pkgSaveAccount` — read+send gmail, validate clear-to-null**

Найти `async function pkgSaveAccount(...)` (строка ≈8890). После чтения `username` и `active`:

```javascript
  const gmailInp = row.querySelector('.acc-gmail-input');
  const gmail = (gmailInp?.value || '').trim();
  const platform = row.dataset.platform || row.querySelector('[data-platform]')?.dataset.platform;
  if (platform === 'youtube') {
    // Если row имеет current-gmail (data-attr) и он непустой, а field пустой — clear-to-null reject:
    const currentGmail = row.dataset.currentGmail || '';
    if (currentGmail && !gmail) {
      toast('Нельзя очистить gmail у существующего аккаунта', 'error');
      return;
    }
    if (gmail && !gmail.includes('@')) {
      toast('gmail должен содержать @', 'error');
      return;
    }
  }
```

В payload PUT'a добавить `gmail`:

```javascript
    body: JSON.stringify({ username, active, gmail: gmail || null })
```

> **Note:** `data-current-gmail` attribute должен быть установлен на row при render'е (Step 2): `<tr data-current-gmail="${a.gmail || ''}">...`. Иначе frontend не может различить «было пусто и осталось пусто» от «было заполнено и стало пусто».

- [ ] **Step 4: Manual smoke на dev VPS**

Создать YT-row через предыдущий task → редактировать → попытка очистить gmail → toast. Изменить gmail на новый → success.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench && \
  git add public/index.html && \
  git commit -m "feat(packages-ui): gmail render+edit on YT account rows with clear-protection"
```

---

## Task 12: Final integration smoke + deploy notes + evidence

**Files:**
- Create: `docs/evidence/2026-05-07-feminista-yt-gmail-deploy.md` (in `contenthunter` repo, не в autowarm-testbench)

- [ ] **Step 1: Final pytest run**

```bash
cd /home/claude-user/autowarm-testbench && python -m pytest tests/ -q --ignore=tests/test_revision_real_adb.py --ignore=tests/test_revision_tiktok_virtual.py 2>&1 | tail -10
```

Expected: все зелёные (включая 8 новых из tests/test_yt_gmail_probe.py).

- [ ] **Step 2: Final node syntax check**

```bash
cd /home/claude-user/autowarm-testbench && node --check server.js && echo "syntax-ok"
```

- [ ] **Step 3: Wait for prod-merge auto-push hook → PM2 reload**

После merge в `testbench` (auto-push hook отправит в `GenGo2/delivery-contenthunter` testbench branch). Затем:

```bash
sudo pm2 reload autowarm  # перезапустить server.js с новыми endpoints
```

(Frontend — `public/index.html` — отдаётся nginx'ом из `/var/www/autowarm/`; либо PM2 worker сам serve'ит. Уточнить деплой через `pm2 describe autowarm | grep "exec cwd"` — см. `feedback_pm2_dump_path_drift.md`.)

- [ ] **Step 4: Восстановить gmail для Feminista (one-off, manual)**

Открыть Паки → найти 3 пака `Феминиста_154 / 155 / 156` → для YT-row каждого ввести gmail (оператор знает gmail из логина устройства). 

ИЛИ — если YT-аккаунты уже залогинены на phone'ах #154/155/156, прогнать backfill:

```bash
cd /home/claude-user/autowarm-testbench && \
  python3 backfill_yt_gmails.py --device-number 154 --device-number 155 --device-number 156 --dry-run
# Если dry-run показывает корректные UPDATE — без --dry-run apply.
```

- [ ] **Step 5: Re-queue 9 failing publish_tasks**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
  UPDATE publish_queue SET status='pending', publish_task_id=NULL
   WHERE publish_task_id IN (3222, 3226, 3229, 3233, 3237, 3239, 3243, 3246, 3247);
"
```

(Только YT часть — IG и TT failures отдельные sub-tasks. По-хорошему, re-queue только YT три задачи #3243/3246/3247 пока.)

Корректнее — фильтровать по platform:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
  UPDATE publish_queue pq SET status='pending', publish_task_id=NULL
   FROM publish_tasks pt
   WHERE pq.publish_task_id = pt.id
     AND pt.id IN (3243, 3246, 3247);
"
```

- [ ] **Step 6: Smoke validation (T+30 min)**

После следующего dispatchPublishQueue cycle проверить:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
  SELECT id, account, platform, status, error_code,
    to_char(created_at AT TIME ZONE 'Europe/Moscow', 'MM-DD HH24:MI') ts
  FROM publish_tasks
  WHERE account ILIKE 'feminista%' AND platform='YouTube'
  ORDER BY created_at DESC LIMIT 5;
"
```

Expected: новые YT задачи без `yt_target_not_in_picker_after_scroll: gmail=None` ошибки.

- [ ] **Step 7: Записать evidence**

В `/home/claude-user/contenthunter/` (не в autowarm-testbench):

```bash
cd /home/claude-user/contenthunter && \
  cat > docs/evidence/2026-05-07-feminista-yt-gmail-deploy.md <<'EOF'
# Feminista YT-gmail — deploy evidence (2026-05-07)

## Деплой
- Spec: docs/superpowers/specs/2026-05-07-feminista-yt-gmail-design.md
- Plan: docs/superpowers/plans/2026-05-07-feminista-yt-gmail-plan.md
- Repo: GenGo2/delivery-contenthunter (testbench → main auto-push)
- PM2: pm2 reload autowarm (cwd=<resolved>)

## Smoke
- Pytest: <N>/<N> passed
- Backend syntax: ok
- Manual UI smoke: добавление YT с gmail / без gmail / edit gmail / clear-gmail
- Feminista one-off backfill: <manual UI или backfill_yt_gmails.py>
- Re-queued tasks: 3243, 3246, 3247
- Validation T+30min: <ok / fail>

## Известные follow-ups
- IG failures (B-IG): отдельная сессия
- TT failures (B-TT): отдельная сессия
- 100+ legacy NULL gmails: backfill_yt_gmails.py --all позже
EOF
git add docs/evidence/2026-05-07-feminista-yt-gmail-deploy.md && \
git commit -m "docs(evidence): Feminista YT-gmail deploy"
```

- [ ] **Step 8: Memory updates**

Обновить `project_session_2026_05_07_shipped.md` — добавить запись «B (YT-gmail)» в Отгружено. Снять B-YT из Backlog.

---

## Out of scope (отдельные планы)

- **B-IG:** `ig_target_not_in_picker` для feminista_glow / feminista_patches — нужно diagnose phone-state, не код.
- **B-TT:** `tt_target_not_on_device` foreign-profile — нужно diagnose phone-state.
- **Legacy backfill:** `backfill_yt_gmails.py --all --parallel 8` для остальных ~100 NULL gmail'ов post-deploy.

## Self-review результаты

**Spec coverage:** все цели спека покрыты — yt_gmail_probe (T1-3), backfill_yt_gmails refactor (T4), revision discover_gmails (T5), revision NULL backfill step (T6), backend POST/PUT/GET (T7-9), frontend add+edit (T10-11), deploy+smoke (T12). ✅

**Placeholder scan:** Task 3 содержит `# TODO в импле:` placeholder, но он явно помечен как переходный (полная логика в Task 4). Допустимо в плане. Других placeholder'ов нет.

**Type consistency:** `extract_yt_picker_pairs -> list[tuple[str, str]]` ✅ во всех вызывающих местах. `match_gmail_to_handle(handle, pairs) -> Optional[str]` ✅. `result['gmails_pairs']` — list[dict] (display_name+gmail), `result['gmails']` — list[str], `result['gmails_backfilled']` — list[dict] (account_id, username, gmail). ✅
