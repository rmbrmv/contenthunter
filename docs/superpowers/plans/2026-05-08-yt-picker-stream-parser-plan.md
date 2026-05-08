# YT picker stream-state-machine parser — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Восстановить функциональность `extract_yt_picker_pairs` / `extract_yt_picker_deleted_pairs` на современном иерархичном YT account picker'е, чтобы `backfill_yt_gmails.py` + `account_revision.py.discover_gmails` снова дозаполняли NULL gmail для Google-account-style каналов.

**Architecture:** Расширяем существующую функцию вторым code-path'ом через stream state-machine: ноды сортируются по y_top ASC, итерируются с состоянием `current_gmail`, channels извлекаются из clickable container'ов (handle через `HANDLE_RE.search(desc)` или display fallback по comma-separated metadata). Legacy + hierarchical результаты мержатся через `_finalize_pairs` который дропает bogus `(gmail, gmail)` tuples и dedup'ит. Existing 11 тестов остаются зелёными по построению.

**Tech Stack:** Python 3 (stdlib `re` only), pytest. Repo: `autowarm-testbench` (auto-pushed в `GenGo2/delivery-contenthunter`). Test corpus: `/tmp/yt_debug_154/round_0.xml` + 3 synthetic XML.

**Spec:** `docs/superpowers/specs/2026-05-08-yt-picker-stream-parser-design.md`

---

## Task 1: Изоляция — feature branch + worktree, copy fixture

**Files:**
- Create: `/home/claude-user/autowarm-testbench-yt-parser/` (worktree)
- Create: `tests/fixtures/yt_picker_hierarchical_154.xml`
- Create: `tests/fixtures/yt_picker_legacy_only.xml`
- Create: `tests/fixtures/yt_picker_hierarchical_deleted.xml`
- Create: `tests/fixtures/yt_picker_multi_channel_per_gmail.xml`

- [ ] **Step 1: Сделать `git fetch` чтобы убедиться что свежий main**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git log --oneline origin/main -5
```

Expected: видим последние commits (например `bb7c140 merge feature/feminista-yt-gmail-2026-05-07 — Feminista YT-gmail`). Если HEAD далеко позади — обновить через `git pull --ff-only origin main` ПЕРЕД созданием worktree.

- [ ] **Step 2: Создать worktree на новой feature-ветке от свежего origin/main**

```bash
cd /home/claude-user/autowarm-testbench
git worktree add -b feature/yt-picker-hierarchical-parser-2026-05-08 \
  /home/claude-user/autowarm-testbench-yt-parser origin/main
cd /home/claude-user/autowarm-testbench-yt-parser
git status
```

Expected: на новой ветке `feature/yt-picker-hierarchical-parser-2026-05-08`, ahead of origin/main by 0, working tree clean.

- [ ] **Step 3: Скопировать real-world dump в test fixtures**

```bash
cp /tmp/yt_debug_154/round_0.xml \
   /home/claude-user/autowarm-testbench-yt-parser/tests/fixtures/yt_picker_hierarchical_154.xml
wc -c /home/claude-user/autowarm-testbench-yt-parser/tests/fixtures/yt_picker_hierarchical_154.xml
```

Expected: ~18173 bytes (или близко).

- [ ] **Step 4: Создать `yt_picker_legacy_only.xml`**

Write to `/home/claude-user/autowarm-testbench-yt-parser/tests/fixtures/yt_picker_legacy_only.xml`:

```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" bounds="[0,0][1080,2400]">
    <node index="0" text="legacy_user@gmail.com" content-desc="legacy_user@gmail.com" bounds="[100,500][800,600]" clickable="false"/>
    <node index="0" text="" content-desc="LegacyChannel,,5 подписчиков" bounds="[100,650][900,800]" clickable="true">
      <node index="0" text="LegacyChannel" content-desc="" bounds="[150,670][400,720]" clickable="false"/>
    </node>
  </node>
</hierarchy>
```

- [ ] **Step 5: Создать `yt_picker_hierarchical_deleted.xml`**

Write:

```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" bounds="[0,0][1080,2400]">
    <node index="0" text="Deleteduser" content-desc="" bounds="[200,400][500,500]" clickable="false"/>
    <node index="0" text="deleteduser@gmail.com" content-desc="" bounds="[200,500][800,600]" clickable="false"/>
    <node index="0" text="" content-desc="ИмяКанала,@deleted_handle,Канал удалён" bounds="[100,650][900,800]" clickable="true">
      <node index="0" text="ИмяКанала" content-desc="" bounds="[150,670][400,720]" clickable="false"/>
      <node index="0" text="@deleted_handle" content-desc="" bounds="[150,730][400,780]" clickable="false"/>
    </node>
  </node>
</hierarchy>
```

- [ ] **Step 6: Создать `yt_picker_multi_channel_per_gmail.xml`**

Write:

```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" bounds="[0,0][1080,2400]">
    <node index="0" text="Owner Display" content-desc="" bounds="[200,400][500,500]" clickable="false"/>
    <node index="0" text="owner123@gmail.com" content-desc="" bounds="[200,500][800,600]" clickable="false"/>
    <node index="0" text="" content-desc="ChannelOne,@channel_one,12 подписчиков" bounds="[100,650][900,800]" clickable="true">
      <node index="0" text="ChannelOne" content-desc="" bounds="[150,670][400,720]" clickable="false"/>
      <node index="0" text="@channel_one" content-desc="" bounds="[150,730][400,780]" clickable="false"/>
    </node>
    <node index="0" text="" content-desc="ChannelTwo,@channel_two,3 подписчика" bounds="[100,820][900,970]" clickable="true">
      <node index="0" text="ChannelTwo" content-desc="" bounds="[150,840][400,890]" clickable="false"/>
      <node index="0" text="@channel_two" content-desc="" bounds="[150,900][400,950]" clickable="false"/>
    </node>
  </node>
</hierarchy>
```

- [ ] **Step 7: Baseline — existing 11 тестов всё ещё green**

```bash
cd /home/claude-user/autowarm-testbench-yt-parser
python3 -m pytest tests/test_yt_gmail_probe.py -v
```

Expected: 11 passed (`test_extract_two_rows`, `test_extract_empty_picker`, …, `test_extract_deleted_pairs_empty_when_no_deleted`).

- [ ] **Step 8: Commit fixtures**

```bash
cd /home/claude-user/autowarm-testbench-yt-parser
git add tests/fixtures/yt_picker_hierarchical_154.xml \
        tests/fixtures/yt_picker_legacy_only.xml \
        tests/fixtures/yt_picker_hierarchical_deleted.xml \
        tests/fixtures/yt_picker_multi_channel_per_gmail.xml
git commit -m "test(yt-gmail): add fixtures for hierarchical picker parser

- yt_picker_hierarchical_154.xml: real-world dump from phone 154
- yt_picker_legacy_only.xml: synthetic minimal legacy
- yt_picker_hierarchical_deleted.xml: synthetic with «Канал удалён»
- yt_picker_multi_channel_per_gmail.xml: synthetic two channels under one gmail"
```

---

## Task 2: Refactor — extract legacy logic в helper'ы

**Files:**
- Modify: `yt_gmail_probe.py:77-141` (existing `extract_yt_picker_deleted_pairs` + `extract_yt_picker_pairs`)

**Цель:** Вынуть существующее тело двух функций в `_extract_legacy_format_pairs` / `_extract_legacy_format_deleted_pairs` без изменения поведения. Public wrapper'ы остаются с теми же сигнатурами; пока вызывают только legacy. Это no-op рефакторинг — все 11 тестов остаются зелёными.

- [ ] **Step 1: Добавить `_extract_legacy_format_pairs` (тело текущего `extract_yt_picker_pairs`)**

В `yt_gmail_probe.py`, вставить ПЕРЕД `def extract_yt_picker_deleted_pairs`:

```python
def _extract_legacy_format_pairs(xml: str) -> list[tuple[str, str]]:
    """Парс XML — пары (text, gmail) из нод формата text+desc-with-gmail.

    Legacy формат: одна нода имеет text=display_name (или text=gmail) И
    content-desc содержит gmail. Не работает для иерархичного picker'а
    где gmail и handle на разных нодах — для этого см. `_extract_hierarchical_pairs`.
    """
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for node_match in NODE_TAG_RE.finditer(xml):
        node_str = node_match.group(0)
        text_m = TEXT_ATTR_RE.search(node_str)
        desc_m = DESC_ATTR_RE.search(node_str)
        if not text_m or not desc_m:
            continue
        text = text_m.group(1).strip()
        desc = desc_m.group(1).strip()
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

- [ ] **Step 2: Добавить `_extract_legacy_format_deleted_pairs` (тело текущего `extract_yt_picker_deleted_pairs`)**

Также вставить рядом:

```python
def _extract_legacy_format_deleted_pairs(xml: str) -> list[tuple[str, str]]:
    """Legacy зеркало для deleted-каналов. См. _extract_legacy_format_pairs."""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for tag_match in NODE_TAG_RE.finditer(xml):
        node_str = tag_match.group(0)
        text_m = TEXT_ATTR_RE.search(node_str)
        desc_m = DESC_ATTR_RE.search(node_str)
        if not text_m or not desc_m:
            continue
        text = text_m.group(1).strip()
        desc = desc_m.group(1).strip()
        if not text or not desc:
            continue
        if not DELETED_LABEL_RE.search(desc):
            continue
        gm = GMAIL_RE.search(desc)
        if not gm:
            pair = (text, '')
        else:
            pair = (text, gm.group(0).lower())
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return pairs
```

- [ ] **Step 3: Заменить тело публичных функций на вызов helper'ов**

Найти `def extract_yt_picker_pairs(xml: str) -> list[tuple[str, str]]:` (~ строка 111) и заменить тело:

```python
def extract_yt_picker_pairs(xml: str) -> list[tuple[str, str]]:
    """Парс XML uiautomator dump'а YT account picker'а в (display_name, gmail) пары.

    Поддерживает два формата:
      - legacy: одна нода с text+desc, gmail в desc
      - hierarchical: gmail header + clickable channel container под ним
    Игнорирует rows с «Канал удалён» (см. extract_yt_picker_deleted_pairs).
    """
    return _extract_legacy_format_pairs(xml)
```

И `def extract_yt_picker_deleted_pairs`:

```python
def extract_yt_picker_deleted_pairs(xml: str) -> list[tuple[str, str]]:
    """Парс XML — возвращает (display_name, gmail) пары rows с «Канал удалён».

    Поддерживает legacy и hierarchical формат. Зеркало extract_yt_picker_pairs
    для deleted rows.
    """
    return _extract_legacy_format_deleted_pairs(xml)
```

- [ ] **Step 4: Прогон существующих тестов — должны остаться зелёными**

```bash
cd /home/claude-user/autowarm-testbench-yt-parser
python3 -m pytest tests/test_yt_gmail_probe.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add yt_gmail_probe.py
git commit -m "refactor(yt-gmail): extract legacy parser logic into helpers

No behavior change. Prepares for hierarchical parser code-path.
- _extract_legacy_format_pairs: legacy text+desc-with-gmail rows
- _extract_legacy_format_deleted_pairs: same for «Канал удалён»
- public extract_yt_picker_pairs / extract_yt_picker_deleted_pairs
  now thin wrappers that delegate to legacy helpers.

Existing 11 tests pass unchanged."
```

---

## Task 3: Add `_finalize_pairs` (dedup + drop bogus)

**Files:**
- Modify: `yt_gmail_probe.py` (add helper after `_normalize`, wire into public wrappers)

- [ ] **Step 1: Добавить `_finalize_pairs` ПОСЛЕ `_normalize`**

После `def _normalize(s: str)` (~строка 42) вставить:

```python
def _finalize_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Финализировать список пар: dedup + drop bogus (identifier == gmail).

    Bogus tuples появляются когда legacy парсер встречает text=desc=gmail-only
    ноду без последующего channel display row под ней — возвращает (gmail, gmail)
    которая бесполезна для match_gmail_to_handle. Filter dropит такие пары.
    Dedup делается по (lowercase identifier, lowercase gmail), сохраняя порядок
    первого вхождения.
    """
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for ident, gmail in pairs:
        if _normalize(ident) == _normalize(gmail):
            continue
        key = (ident.lower(), gmail.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append((ident, gmail))
    return result
```

- [ ] **Step 2: Wire `_finalize_pairs` в публичные wrapper'ы**

`extract_yt_picker_pairs`:

```python
def extract_yt_picker_pairs(xml: str) -> list[tuple[str, str]]:
    """Парс XML uiautomator dump'а YT account picker'а в (display_name, gmail) пары.

    Поддерживает два формата:
      - legacy: одна нода с text+desc, gmail в desc
      - hierarchical: gmail header + clickable channel container под ним
    Игнорирует rows с «Канал удалён» (см. extract_yt_picker_deleted_pairs).
    Bogus (gmail, gmail) tuples из legacy формата фильтруются _finalize_pairs.
    """
    return _finalize_pairs(_extract_legacy_format_pairs(xml))
```

`extract_yt_picker_deleted_pairs`:

```python
def extract_yt_picker_deleted_pairs(xml: str) -> list[tuple[str, str]]:
    """Парс XML — возвращает (display_name, gmail) пары rows с «Канал удалён».

    Поддерживает legacy и hierarchical формат. Зеркало extract_yt_picker_pairs
    для deleted rows. Bogus (gmail, gmail) фильтруются _finalize_pairs.
    """
    return _finalize_pairs(_extract_legacy_format_deleted_pairs(xml))
```

- [ ] **Step 3: Существующие тесты — green**

```bash
python3 -m pytest tests/test_yt_gmail_probe.py -v
```

Expected: 11 passed. (Existing fixtures emit display ≠ gmail, finalize не меняет результат для них.)

- [ ] **Step 4: Commit**

```bash
git add yt_gmail_probe.py
git commit -m "feat(yt-gmail): add _finalize_pairs (dedup + drop bogus)

_finalize_pairs дропает (gmail, gmail) tuples и dedup'ит по
normalized (identifier, gmail) tuple. Wired в публичные wrapper'ы.
Готовит infrastructure для merge legacy + hierarchical в Task 5.

Existing 11 tests pass."
```

---

## Task 4: TDD red — 8 failing tests

**Files:**
- Modify: `tests/test_yt_gmail_probe.py`

- [ ] **Step 1: Дописать 8 новых test functions в конец `tests/test_yt_gmail_probe.py`**

Append:

```python


# ============================================================
# Hierarchical YT picker parser tests (Task 5+)
# ============================================================

HIERARCHICAL_PAIR = ('feminista.beauty', 'veronikamavrikeva@gmail.com')
LEGACY_DISPLAY_PAIR = ('WellFresh_1', 'zxclesya154@gmail.com')


def test_hierarchical_extracts_handle_with_gmail_from_header():
    """Real-world dump: Veronikamavrikeva → Feminista @feminista.beauty."""
    xml = _load('yt_picker_hierarchical_154.xml')
    pairs = extract_yt_picker_pairs(xml)
    assert HIERARCHICAL_PAIR in pairs


def test_hierarchical_legacy_mix_returns_both_pairs():
    """Real-world dump содержит и hierarchical (Feminista) и legacy (WellFresh_1).

    Также проверяет что bogus (gmail, gmail) tuple от legacy zxclesya154 row
    отфильтрован _finalize_pairs.
    """
    xml = _load('yt_picker_hierarchical_154.xml')
    pairs = extract_yt_picker_pairs(xml)
    assert HIERARCHICAL_PAIR in pairs
    assert LEGACY_DISPLAY_PAIR in pairs
    assert ('zxclesya154@gmail.com', 'zxclesya154@gmail.com') not in pairs


def test_hierarchical_skips_deleted_channels():
    """Иерархичный fixture с deleted каналом — extract_yt_picker_pairs его skip'ит."""
    xml = _load('yt_picker_hierarchical_deleted.xml')
    pairs = extract_yt_picker_pairs(xml)
    handles = [h.lower() for h, _ in pairs]
    assert 'deleted_handle' not in handles


def test_extract_deleted_pairs_hierarchical():
    """Иерархичный fixture deleted — extract_yt_picker_deleted_pairs возвращает пару."""
    xml = _load('yt_picker_hierarchical_deleted.xml')
    deleted = extract_yt_picker_deleted_pairs(xml)
    assert ('deleted_handle', 'deleteduser@gmail.com') in deleted


def test_hierarchical_multiple_channels_per_gmail():
    """Один gmail header → две clickable channel rows под ним."""
    xml = _load('yt_picker_multi_channel_per_gmail.xml')
    pairs = extract_yt_picker_pairs(xml)
    assert ('channel_one', 'owner123@gmail.com') in pairs
    assert ('channel_two', 'owner123@gmail.com') in pairs


def test_hierarchical_returns_empty_on_empty_xml():
    """Empty input → []."""
    assert extract_yt_picker_pairs('') == []


def test_hierarchical_returns_empty_on_malformed_xml():
    """Malformed XML → [] (gracefully)."""
    assert extract_yt_picker_pairs('<not-xml') == []


def test_hierarchical_skips_non_channel_buttons():
    """gmail-header + 'Добавить аккаунт' button (no comma in desc) → not emit."""
    xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        '<hierarchy rotation="0">'
        '<node index="0" text="x@gmail.com" content-desc="" bounds="[100,100][800,200]" clickable="false"/>'
        '<node index="0" text="" content-desc="Добавить аккаунт" bounds="[100,300][800,400]" clickable="true"/>'
        '</hierarchy>'
    )
    assert extract_yt_picker_pairs(xml) == []
```

- [ ] **Step 2: Проверить что новые тесты падают**

```bash
python3 -m pytest tests/test_yt_gmail_probe.py -v
```

Expected:
- 11 passed (existing)
- 8 failed (new): tests ожидают hierarchical pairs/handle, но `_extract_legacy_format_pairs` их не emit'ит. `test_hierarchical_returns_empty_on_*` могут случайно пройти, но MUST быть в списке fail (e.g. malformed может вернуть пустой список и тест зеленеет — нормально, оставляем).

Уточнение: проверь что **минимум 5** из 8 hierarchical-тестов падают (#1, #2, #4, #5, #8). Тесты #3, #6, #7 могут случайно пройти (они проверяют отсутствие → empty/malformed XML возвращает [] изначально).

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_yt_gmail_probe.py
git commit -m "test(yt-gmail): add 8 hierarchical parser tests (red)

Tests expect _extract_hierarchical_pairs functionality:
- handle extraction via clickable container content-desc
- display-only fallback for channels без custom URL
- deleted-channels skipping in extract_yt_picker_pairs
- deleted-channels emission in extract_yt_picker_deleted_pairs
- multi-channel-per-gmail
- empty/malformed XML handling
- non-channel button filtering

Currently 5+ failing — implementation в Task 5 закроет."
```

---

## Task 5: Implement `_extract_hierarchical_pairs` + wire

**Files:**
- Modify: `yt_gmail_probe.py`

- [ ] **Step 1: Добавить `_extract_hierarchical_pairs` ПОСЛЕ `_extract_legacy_format_deleted_pairs`**

```python
# Bounds parsing — same as account_switcher.parse_ui_dump.
BOUNDS_RE = re.compile(r'\bbounds="\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]"')
CLICKABLE_RE = re.compile(r'\bclickable="(true|false)"')
SELECTED_PREFIX_RE = re.compile(r'^Вы выбрали аккаунт\s+', re.IGNORECASE)


def _extract_hierarchical_pairs(xml: str, deleted_only: bool = False) -> list[tuple[str, str]]:
    """Stream state-machine парсер для иерархичного YT picker'а.

    Iterate ноды по y_top ASC. Держим current_gmail. На gmail-header
    (text содержит gmail И desc='' либо desc==text) обновляем; на clickable
    channel container с @handle в desc — emit (handle, current_gmail);
    на display-only fallback (clickable с comma-separated desc, без handle) —
    emit (display, current_gmail).

    Args:
        xml: uiautomator dump
        deleted_only: если True — emit только rows с «Канал удалён»; иначе skip
            deleted (для extract_yt_picker_pairs vs extract_yt_picker_deleted_pairs).
    """
    if not xml:
        return []

    nodes: list[tuple[int, str, str, bool]] = []  # (y_top, text, desc, clickable)
    for tag_match in NODE_TAG_RE.finditer(xml):
        node_str = tag_match.group(0)
        bounds_m = BOUNDS_RE.search(node_str)
        if not bounds_m:
            continue
        try:
            y_top = int(bounds_m.group(2))
        except (ValueError, IndexError):
            continue
        text_m = TEXT_ATTR_RE.search(node_str)
        desc_m = DESC_ATTR_RE.search(node_str)
        text = (text_m.group(1).strip() if text_m else '')
        desc = (desc_m.group(1).strip() if desc_m else '')
        clickable_m = CLICKABLE_RE.search(node_str)
        clickable = (clickable_m.group(1) == 'true') if clickable_m else False
        nodes.append((y_top, text, desc, clickable))

    nodes.sort(key=lambda n: n[0])

    pairs: list[tuple[str, str]] = []
    current_gmail: Optional[str] = None
    for _y_top, text, desc, clickable in nodes:
        is_deleted = bool(DELETED_LABEL_RE.search(text + ' ' + desc))
        # Filter по deleted_only — invariant: skip deleted кроме как когда хотим именно deleted.
        if deleted_only and not is_deleted:
            continue
        if not deleted_only and is_deleted:
            continue

        # Шаг 3.b — gmail header detect
        gm_text = GMAIL_RE.search(text)
        if gm_text and (desc == '' or desc == text):
            current_gmail = gm_text.group(0).lower()
            continue

        # Channel rows должны быть clickable И иметь current_gmail в scope.
        if not clickable or not current_gmail:
            continue

        # Шаг 3.c — handle через HANDLE_RE на desc БЕЗ email-substring
        desc_no_email = GMAIL_RE.sub('', desc)
        handle_m = HANDLE_RE.search(desc_no_email)
        if handle_m:
            handle = handle_m.group(1)
            pairs.append((handle, current_gmail))
            continue

        # Шаг 3.d — display-only fallback (channels без handle, e.g. WellFresh_1)
        # Channel rows ВСЕГДА имеют comma-separated desc (Display,handle?,N подписчиков).
        # Кнопки типа 'Добавить аккаунт' — one-segment, отсеиваются.
        if ',' in desc:
            first_seg = desc.split(',', 1)[0].strip()
            first_seg = SELECTED_PREFIX_RE.sub('', first_seg).strip()
            if first_seg:
                pairs.append((first_seg, current_gmail))

    return pairs
```

- [ ] **Step 2: Wire hierarchical в публичные wrapper'ы**

`extract_yt_picker_pairs`:

```python
def extract_yt_picker_pairs(xml: str) -> list[tuple[str, str]]:
    """Парс XML uiautomator dump'а YT account picker'а в (display_name, gmail) пары.

    Поддерживает два формата:
      - legacy: одна нода с text+desc, gmail в desc
      - hierarchical: gmail header + clickable channel container под ним
    Игнорирует rows с «Канал удалён» (см. extract_yt_picker_deleted_pairs).
    Bogus (gmail, gmail) tuples из legacy формата фильтруются _finalize_pairs.
    """
    legacy = _extract_legacy_format_pairs(xml)
    hierarchical = _extract_hierarchical_pairs(xml, deleted_only=False)
    return _finalize_pairs(legacy + hierarchical)
```

`extract_yt_picker_deleted_pairs`:

```python
def extract_yt_picker_deleted_pairs(xml: str) -> list[tuple[str, str]]:
    """Парс XML — возвращает (display_name, gmail) пары rows с «Канал удалён».

    Поддерживает legacy и hierarchical формат. Зеркало extract_yt_picker_pairs
    для deleted rows. Bogus (gmail, gmail) фильтруются _finalize_pairs.
    """
    legacy = _extract_legacy_format_deleted_pairs(xml)
    hierarchical = _extract_hierarchical_pairs(xml, deleted_only=True)
    return _finalize_pairs(legacy + hierarchical)
```

- [ ] **Step 3: Запустить весь test файл — все 19 должны быть green**

```bash
python3 -m pytest tests/test_yt_gmail_probe.py -v
```

Expected: 19 passed. (11 existing + 8 new hierarchical.)

Если падает один из 8 — анализировать output:
- Если `test_hierarchical_extracts_handle_with_gmail_from_header` fails — проверить шаг 3.b detect gmail header (text vs desc condition).
- Если `test_hierarchical_legacy_mix_returns_both_pairs` НЕ нашёл `LEGACY_DISPLAY_PAIR` — display fallback (шаг 3.d) не сработал, проверить что desc содержит запятую и first_seg непустой.
- Если bogus `(zxclesya154@gmail.com, zxclesya154@gmail.com)` остаётся — `_finalize_pairs` не вызывается ИЛИ `_normalize(gmail)` отличается от `_normalize(text)` из-за точки в gmail. Smoke: `_normalize('zxclesya154@gmail.com')` должно быть `'zxclesya154@gmailcom'` (точки strip'нуты), `_normalize('zxclesya154@gmail.com')` то же самое — match.
- Если deleted test fails — проверить что `_extract_hierarchical_pairs(xml, deleted_only=True)` правильно реверсит filter.

- [ ] **Step 4: Commit hierarchical implementation**

```bash
git add yt_gmail_probe.py
git commit -m "feat(yt-gmail): hierarchical picker parser

_extract_hierarchical_pairs реализован stream-state-machine'ом:
- ноды сортируются по y_top ASC
- current_gmail обновляется на gmail header (text=gmail + desc='' или desc=text)
- handle emit через HANDLE_RE.search(desc без email-substring)
- display-only fallback для каналов без handle (comma-required, button filter)
- deleted_only flag для extract_yt_picker_deleted_pairs

Public wrapper'ы _finalize_pairs(legacy + hierarchical).
19/19 tests green (11 existing + 8 new)."
```

---

## Task 6: Self-validate offline + push branch

**Files:**
- Read: `tests/fixtures/yt_picker_hierarchical_154.xml` (existing)

- [ ] **Step 1: Smoke offline analysis на real fixture (sanity)**

```bash
cd /home/claude-user/autowarm-testbench-yt-parser
python3 -c "
from yt_gmail_probe import extract_yt_picker_pairs, extract_yt_picker_deleted_pairs
xml = open('tests/fixtures/yt_picker_hierarchical_154.xml').read()
print('pairs:', extract_yt_picker_pairs(xml))
print('deleted:', extract_yt_picker_deleted_pairs(xml))
"
```

Expected:
```
pairs: [('feminista.beauty', 'veronikamavrikeva@gmail.com'), ('WellFresh_1', 'zxclesya154@gmail.com')]
deleted: []
```

(Может быть в другом порядке из-за legacy + hierarchical merge — это OK; главное что обе пары присутствуют и `(gmail, gmail)` отсутствует.)

- [ ] **Step 2: Push feature branch на remote**

```bash
cd /home/claude-user/autowarm-testbench-yt-parser
git push -u origin feature/yt-picker-hierarchical-parser-2026-05-08
```

Expected: `Branch 'feature/yt-picker-hierarchical-parser-2026-05-08' set up to track 'origin/feature/yt-picker-hierarchical-parser-2026-05-08'`.

- [ ] **Step 3: Merge feature → autowarm-testbench main**

```bash
cd /home/claude-user/autowarm-testbench
git checkout main
git pull --ff-only origin main
git merge --no-ff feature/yt-picker-hierarchical-parser-2026-05-08 \
  -m "merge feature/yt-picker-hierarchical-parser-2026-05-08 — иерархичный YT picker"
git push origin main
```

Expected: merge commit pushed; auto-push hook отгружает в `GenGo2/delivery-contenthunter`.

- [ ] **Step 4: Cleanup worktree**

```bash
git worktree remove /home/claude-user/autowarm-testbench-yt-parser
git branch -d feature/yt-picker-hierarchical-parser-2026-05-08  # local
git push origin --delete feature/yt-picker-hierarchical-parser-2026-05-08  # remote, optional
```

Expected: worktree removed, branch deleted (после merge'а).

---

## Task 7: Deploy в prod + collect evidence

**Files:**
- Read/modify: `/root/.openclaw/workspace-genri/autowarm/` (prod checkout)

- [ ] **Step 1: Pull в prod checkout**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git pull --ff-only origin main
git log --oneline -3
```

Expected: видим последний merge commit `merge feature/yt-picker-hierarchical-parser-...`.

Note (per memory `feedback_pm2_dump_path_drift.md`): после pull проверить exec cwd:
```bash
sudo -n pm2 describe autowarm | grep "exec cwd"
```
Expected: cwd = `/root/.openclaw/workspace-genri/autowarm`. Если другая — `pm2 delete autowarm && pm2 start ecosystem.config.js && pm2 save`.

- [ ] **Step 2: PM2 reload (parser — pure Python helper, не требует hot-restart, но автодеплой принят)**

```bash
sudo -n pm2 reload autowarm
sudo -n pm2 status autowarm
```

Expected: status=online, restart counter +1, no errors в первые 30 секунд.

- [ ] **Step 3: Smoke offline на prod fixture**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "
from yt_gmail_probe import extract_yt_picker_pairs
xml = open('tests/fixtures/yt_picker_hierarchical_154.xml').read()
print(extract_yt_picker_pairs(xml))
"
```

Expected: содержит `('feminista.beauty', 'veronikamavrikeva@gmail.com')` и `('WellFresh_1', 'zxclesya154@gmail.com')`.

- [ ] **Step 4: Re-queue 3 Feminista YT publish_tasks per memory `reference_publish_requeue_path`**

```sql
UPDATE publish_queue
SET status = 'pending',
    publish_task_id = NULL,
    updated_at = NOW()
WHERE publish_task_id IN (3243, 3246, 3247);
```

Через `psql`:
```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
UPDATE publish_queue
SET status='pending', publish_task_id=NULL, updated_at=NOW()
WHERE publish_task_id IN (3243, 3246, 3247)
RETURNING id, publish_task_id, status;
"
```

Expected: 3 rows updated.

- [ ] **Step 5: Дождаться `dispatchPublishQueue` тика (≤5 минут) и наблюдать новые publish_tasks**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "
SELECT pt.id, pt.account, pt.platform, pt.status, pt.error_code, pt.started_at, pt.updated_at
FROM publish_tasks pt
WHERE pt.account IN ('feminista.beauty', 'feminista_patches', 'feminista_glow')
  AND pt.platform='YouTube'
  AND pt.started_at > NOW() - INTERVAL '30 minutes'
ORDER BY pt.id DESC LIMIT 10;
"
```

Через 5–15 минут видим новые task_id. Окончательный статус (через ~10 минут после старта):

- **Если status='done'** — публикация прошла → P0.1 closed empirically. Sub-project complete. Записать evidence.
- **Если status='failed' с error_code='yt_target_not_in_picker_after_scroll'** — switcher fix нужен как follow-up sub-project. Собрать `/tmp/autowarm_ui_dumps/` дамп текущего picker'а, открыть отдельный sub-project под switcher.
- **Если другая ошибка** (например `yt_target_not_logged_in`) — phone-state issue, эскалировать в operations (re-login на phone).

- [ ] **Step 6: Записать evidence**

Создать `/home/claude-user/contenthunter/docs/evidence/2026-05-08-yt-picker-stream-parser-deploy.md` с:
- Список тестов (19/19 green)
- Smoke output из шага 3
- Список re-queued publish_tasks (3243/3246/3247)
- Финальный статус новых publish_tasks (done / failed + причина)
- Решение по P0.1 (closed / open follow-up)

```bash
cd /home/claude-user/contenthunter
git add docs/evidence/2026-05-08-yt-picker-stream-parser-deploy.md
git commit -m "docs(evidence): YT picker hierarchical parser — deploy + re-queue results"
```

---

## Self-review checklist (для агента до начала работы)

1. **Spec coverage:**
   - ✅ Section 2.1 (extend, not replace) → Task 2-5 структура.
   - ✅ Section 3.2 шаг 3.a (skip deleted) → `_extract_hierarchical_pairs` invariant.
   - ✅ Section 3.2 шаг 3.b (gmail header detect) → step 1 of Task 5.
   - ✅ Section 3.2 шаг 3.c (handle через HANDLE_RE) → step 1 of Task 5.
   - ✅ Section 3.2 шаг 3.d (display-only fallback с comma-filter) → step 1 of Task 5.
   - ✅ Section 3.3 (`_finalize_pairs` drop bogus + dedup) → Task 3.
   - ✅ Section 4 edge cases #1–11 → Task 4 tests + Task 5 implementation.
   - ✅ Section 5.1 fixtures (4 файла) → Task 1.
   - ✅ Section 5.2 8 новых tests → Task 4.
   - ✅ Section 5.3 регрессия legacy (existing 11) → Task 1 step 7 + Task 2 step 4 + Task 3 step 3.
   - ✅ Section 8 DoD финальные асерты → Task 6 step 1 + Task 7 step 5.
   - ✅ Section 9 связанные памяти → Task 7 шаги re-queue + evidence.

2. **Placeholder scan:** все code blocks полные, exact paths, exact commands.

3. **Type consistency:**
   - `_extract_legacy_format_pairs(xml: str) -> list[tuple[str, str]]` ✅
   - `_extract_legacy_format_deleted_pairs(xml: str) -> list[tuple[str, str]]` ✅
   - `_extract_hierarchical_pairs(xml: str, deleted_only: bool = False) -> list[tuple[str, str]]` ✅
   - `_finalize_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]` ✅
   - Public `extract_yt_picker_pairs(xml: str) -> list[tuple[str, str]]` неизменна ✅
   - Public `extract_yt_picker_deleted_pairs(xml: str) -> list[tuple[str, str]]` неизменна ✅

4. **Branch isolation:** Task 1 явно использует `git worktree add` в `/home/claude-user/autowarm-testbench-yt-parser/` — не stомпает на other claude sessions работающие в `/home/claude-user/autowarm-testbench/`.
