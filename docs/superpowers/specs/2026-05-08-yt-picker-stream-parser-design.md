# YT picker stream-state-machine parser — design spec

**Дата:** 2026-05-08
**Sub-project:** YT (продолжение sub-project B от 2026-05-07 — Feminista YT-gmail)
**Репо:** `autowarm-testbench` (же auto-pushed в `GenGo2/delivery-contenthunter`)
**Триггер:** memory `project_session_2026_05_07_shipped.md` — следствие deploy `bb7c140`. Современный YT picker иерархичный (Google account header → каналы под ним), а `yt_gmail_probe.extract_yt_picker_pairs` ловит только legacy-формат (`text=desc=gmail` на одной ноде). Backfill / revision не дозаполняют gmail для современного picker'а.

---

## 1. Контекст и сегодняшнее поведение

### 1.1. Текущая реализация

`yt_gmail_probe.py:111` — `extract_yt_picker_pairs(xml) -> list[tuple[str, str]]`:

```python
for node_match in NODE_TAG_RE.finditer(xml):
    text = TEXT_ATTR_RE.search(node_str).group(1).strip()
    desc = DESC_ATTR_RE.search(node_str).group(1).strip()
    if not text or not desc:        # фильтр (a) — отбрасывает gmail-header (text=gmail, desc='')
        continue
    if DELETED_LABEL_RE.search(desc):
        continue
    gm = GMAIL_RE.search(desc)      # фильтр (b) — gmail обязан быть в desc
    if not gm:
        continue
    pair = (text, gm.group(0).lower())
```

Это ловит ровно одну форму: ноду где `text=display_name` И `content-desc` содержит gmail. На практике в современном picker'е таких нод нет — gmail хранится в отдельной standalone ноде.

`extract_yt_picker_deleted_pairs` — зеркальная логика для rows с «Канал удалён».

### 1.2. Реальная структура иерархичного picker'а (phone 154, dump `/tmp/yt_debug_154/round_0.xml`)

Сортировка по `y_top`:

| y-coord | text | content-desc | clickable | Роль |
|---|---|---|---|---|
| 452-535 | `Veronikamavrikeva` | `''` | false | Google-account display |
| 535-627 | `veronikamavrikeva@gmail.com` | `''` | false | gmail header (text-only) |
| 644-904 | `''` | `Вы выбрали аккаунт Feminista,@feminista.beauty,Нет подписчиков` | **true** | currently-selected channel container |
| 663-712 | `Feminista` | `''` | false | вложенный display |
| 724-770 | `@feminista.beauty` | `''` | false | вложенный handle |
| 1073-1160 | `zxclesya154@gmail.com` | `zxclesya154@gmail.com` | false | gmail header (legacy: text=desc) |
| 1160-1305 | `''` | `WellFresh_1,,5 подписчиков` | **true** | inactive channel container |
| 1183-1236 | `WellFresh_1` | `''` | false | вложенный display (без handle) |

Один picker может содержать **обе** формы: новую (`Veronikamavrikeva` group) и legacy (`zxclesya154` group). Каналы могут быть **с handle** (Feminista) ИЛИ **без handle** (WellFresh_1).

### 1.3. Эффект сегодня

`extract_yt_picker_pairs(round_0.xml)` → `[]` для иерархичных rows; единственная legacy gmail-нода `zxclesya154@gmail.com` (text=desc=gmail) фильтр (a) пропускает, фильтр (b) проходит → возвращает бесполезную пару `('zxclesya154@gmail.com', 'zxclesya154@gmail.com')` (text=gmail, не handle).

Caller'ы:
- `backfill_yt_gmails.py:191-235` — собирает `pairs` через `extract_yt_picker_pairs`, потом `match_gmail_to_handle(handle, pairs)`. С пустым/мусорным списком — 0 кандидатов.
- `account_revision.py.discover_gmails` — то же.
- `match_gmail_to_handle` сама не меняется и работает корректно: дай ей правильные пары — она найдёт gmail для handle.

100+ legacy NULL-gmail rows и все новые (post-2026-05-07) Google-account-style каналы не дозаполняются автоматом; revision вынуждена работать в pessimistic-fallback flow.

---

## 2. Approach

### 2.1. Recommended — extend existing function

Сохраняем существующий legacy code-path (rename internally, тесты остаются) и добавляем новый hierarchical path. Объединяем результаты + dedup.

```python
def extract_yt_picker_pairs(xml: str) -> list[tuple[str, str]]:
    legacy = _extract_legacy_format_pairs(xml)
    hierarchical = _extract_hierarchical_pairs(xml)
    return _finalize_pairs(legacy + hierarchical)
```

То же для `extract_yt_picker_deleted_pairs`.

### 2.2. Альтернатива (rejected)

**Replace полностью.** Чище код, но риск регрессии на legacy формате. Существующие 11 тестов в `tests/test_yt_gmail_probe.py` валидируют конкретные fixtures — переписывать их без бизнес-причины не нужно.

---

## 3. Детальный алгоритм `_extract_hierarchical_pairs`

### 3.1. Ввод

XML uiautomator dump'а picker'а (string).

### 3.2. Шаги

1. **Парсим все ноды.** Для каждой `<node …>` — извлекаем `text`, `content-desc`, `bounds=(x1,y1,x2,y2)`, `clickable: bool`.
   - Реализация — через regex (как в существующей функции) ИЛИ через `xml.etree.ElementTree.fromstring` (как `parse_ui_dump` в `account_switcher.py`). Выбираем **regex** для консистентности с существующим модулем и устойчивости к broken XML (live dumps часто malformed).

2. **Сортируем ноды по `y_top` ASCENDING.**

3. **Iterate с состоянием `current_gmail: Optional[str] = None`:**

   **(a) Skip deleted:**
   ```
   if DELETED_LABEL_RE.search(text + ' ' + desc):
       continue
   ```

   **(b) Detect gmail header — обновляем `current_gmail`:**
   Условие: gmail найден в `text` (через `GMAIL_RE.search`) И **хотя бы одно** из:
   - `desc == ''` (новый формат: `text=gmail, desc=''`), ИЛИ
   - `desc == text` (legacy: `text=desc=gmail`).

   (text=desc=gmail удовлетворяет обоим условиям — это OK, единая ветка обработки.)

   Действие: `current_gmail = match.group(0).lower()`. Continue (не emit'им).

   **(c) Detect channel handle from clickable container:**
   Условие: `clickable=True` И `desc` содержит `@handle` через `HANDLE_RE` (после `GMAIL_RE.sub('', desc)` — гарантия что не зацепим email типа `@gmail.com`).

   Действие: emit `(handle, current_gmail)` если `current_gmail` set, где `handle = HANDLE_RE.search(...).group(1)` (без `@`-префикса, для чистого exact-match через `_normalize` в `match_gmail_to_handle`).

   **(d) Display-only fallback (channels без handle):**
   Условие: `clickable=True` И из (c) handle не извлечён И `desc` содержит запятую (channel rows всегда имеют comma-separated metadata типа `Display,handle?,N подписчиков`) И первая comma-segment после strip prefix `'Вы выбрали аккаунт '` непустая.

   Действие: emit `(display, current_gmail)` если `current_gmail` set.

4. Return list.

### 3.3. Финализация (dedup + cleanup)

`_finalize_pairs(pairs)`:
1. **Drop bogus `(gmail, gmail)` tuples** — если `_normalize(identifier) == _normalize(gmail)` ИЛИ identifier при lower равен gmail при lower, пропускаем. Это фильтрует legacy false-positive где старая логика возвращала `('zxclesya154@gmail.com', 'zxclesya154@gmail.com')` из text=desc=gmail-only нод (без последующего channel display row под ней). Применяется ПОСЛЕ merge legacy+hierarchical, чтобы legacy-output без полезной handle-инфо не загрязнял contract функции.
2. **Dedup** — set на tuple `(identifier_lower, gmail_lower)`, сохранение первого вхождения.

> **Side-effect:** существующие тесты `test_extract_two_rows` / similar legacy-fixtures, которые ожидали `(gmail, gmail)` пары, могут стать жёлтыми. Mitigation в Section 5.3 — пройдёмся по существующим тестам и переопределим ожидания, если найдём `assert ... in [..., (gmail, gmail), ...]`. Это легитимное усиление контракта (`(gmail, gmail)` никогда не использовалось caller'ами полезно — `match_gmail_to_handle('WellFresh_1', [('zxclesya154@gmail.com', 'zxclesya154@gmail.com')])` всё равно None).

---

## 4. Edge cases (полная таблица)

| # | Входной кейс | Ожидаемое поведение |
|---|---|---|
| 1 | Veronikamavrikeva → Feminista (один канал, handle есть) | emit `('feminista.beauty', 'veronikamavrikeva@gmail.com')` через шаг 3.c (handle без `@`) |
| 2 | Один gmail header, два канала под ним | emit обе пары с одним `current_gmail` |
| 3 | Legacy zxclesya154 → WellFresh_1 (text=desc=gmail + display row под) | emit `('WellFresh_1', 'zxclesya154@gmail.com')` через шаг 3.d (новое поведение vs ранее `(gmail, gmail)`) |
| 4 | Mixed picker: Veronikamavrikeva + zxclesya154 в одном dump'е | emit обе пары |
| 5 | Канал помечен «Канал удалён» / «Channel deleted/removed» | `extract_yt_picker_pairs` skip; `extract_yt_picker_deleted_pairs` emit |
| 6 | `xml=''` или malformed | `[]` |
| 7 | Picker без gmail header'а (например частично прокручен) | пары не emit'ятся (current_gmail None) |
| 8 | Кнопка `'Добавить аккаунт'` clickable, desc='Добавить аккаунт' (нет запятой, нет handle) | НЕ emit (фильтр шага 3.d по запятой) |
| 9 | Кнопка `'Параметры канала'` clickable, desc='Параметры канала' | НЕ emit (нет запятой) |
| 10 | gmail header `text='X@gmail.com', desc=''` без последующего clickable channel в gap | current_gmail set, потом сбросится следующим gmail header'ом — пар не emit |
| 11 | Picker с handle в text='@handle' но БЕЗ clickable container (теоретический edge case) | НЕ emit (требуем clickable container) |

---

## 5. Тестирование (TDD)

### 5.1. Test corpus

Новые fixtures в `tests/fixtures/`:

- `yt_picker_hierarchical_154.xml` — копия `/tmp/yt_debug_154/round_0.xml` (real-world иерархичный + legacy mix).
- `yt_picker_legacy_only.xml` — synthetic minimal: один gmail-header (legacy text=desc) + один channel display row под ним.
- `yt_picker_hierarchical_deleted.xml` — synthetic: иерархичный с одним каналом в state «Канал удалён».
- `yt_picker_multi_channel_per_gmail.xml` — synthetic: один gmail header + два clickable channel-row'а под ним.

### 5.2. Новые test cases

В `tests/test_yt_gmail_probe.py`:

1. `test_hierarchical_extracts_handle_with_gmail_from_header` — на `yt_picker_hierarchical_154.xml`, ожидание `('feminista.beauty', 'veronikamavrikeva@gmail.com')` среди возвращённых пар.
2. `test_hierarchical_legacy_mix_returns_both_pairs` — то же fixture, ожидание содержит и `('feminista.beauty', 'veronikamavrikeva@gmail.com')` и `('WellFresh_1', 'zxclesya154@gmail.com')` (после dedup, в порядке появления).
3. `test_hierarchical_skips_deleted_channels` — `yt_picker_hierarchical_deleted.xml`, ожидание deleted-канал не в `extract_yt_picker_pairs` результате.
4. `test_extract_deleted_pairs_hierarchical` — `yt_picker_hierarchical_deleted.xml`, ожидание `('deleted_handle', 'gmail')` через `extract_yt_picker_deleted_pairs` (handle без `@`).
5. `test_hierarchical_multiple_channels_per_gmail` — `yt_picker_multi_channel_per_gmail.xml`, ожидание обе пары с одним gmail.
6. `test_hierarchical_returns_empty_on_empty_xml` — `xml=''` → `[]`.
7. `test_hierarchical_returns_empty_on_malformed_xml` — `xml='<not-xml'` → `[]`.
8. `test_hierarchical_skips_non_channel_buttons` — synthetic с кнопкой 'Добавить аккаунт' / 'Параметры канала' clickable → НЕ emit.

### 5.3. Регрессия legacy

Существующие 11 тестов (`test_extract_two_rows`, `test_extract_skips_deleted_channels`, и т.д.) остаются как есть. По построению (legacy logic в `_extract_legacy_format_pairs` неизменна) они зелёные.

`test_match_*` тесты не затрагиваются — `match_gmail_to_handle` не меняется.

### 5.4. Гейт зелёности

`pytest tests/test_yt_gmail_probe.py -v` — **все** тесты (existing 11 + new 8) green.

---

## 6. Out of scope

- **Switcher fix (P0.1)** — не меняем. Offline analysis (Раздел 1.2 evidence) показал что `find_yt_row_by_gmail` находит `(540, 774)` внутри clickable Feminista row на современном picker'е. Empirical validation — re-queue 3243/3246/3247 после deploy parser fix.
- **«Другие аккаунты» / «Other accounts» separator** — не парсим, не нужно для backfill (за separator'ом обычно sign-out / add-account кнопки, не каналы).
- **Multi-channel ranking** — caller (`match_gmail_to_handle`) сам выбирает по handle matching.
- **Bulk migration NULL gmail** — не делаем массовый UPDATE; revision/backfill сами дозаполнят при следующих прогонах теперь, когда парсер работает.
- **Frontend display обновлений** — не трогаем, results format `list[tuple[str, str]]` не меняется.

---

## 7. Risks и mitigations

| ID | Риск | Mitigation |
|---|---|---|
| R1 | Display-only fallback (шаг 3.d) ловит мусор от UI кнопок («Управлять Google аккаунтом», «Параметры»). | Фильтр требует **запятую** в desc — channel rows гарантированно имеют `Display,@handle?,N подписчиков` формат, кнопки имеют one-segment desc. Test #8 покрывает. |
| R2 | gmail-header в `text` смешивается с какой-то системной нодой (например debug-log overlay показывает email пользователя). | На практике `desc` всегда либо пуст, либо равен text для legacy формата. Filter в шаге 3.b строгий `desc=='' OR desc==text`. |
| R3 | Регрессия в существующем legacy path при extract внутрь helper'а. | `_extract_legacy_format_pairs` — буквальная копия текущей логики; existing fixtures + 11 тестов охраняют. |
| R4 | `current_gmail` ошибочно живёт между несвязанными picker-секциями (например после «Другие аккаунты» separator gmail предыдущей секции остаётся). | На практике reset не нужен — следующий gmail header перезапишет. Риск минимальный — separator'ом обычно sign-out/add-account кнопки без gmail. Если станет проблемой — добавим reset на specific separator label'ы (out of scope сейчас). |
| R5 | Caller backfill ожидает определённый порядок пар. | `_finalize_pairs` сохраняет порядок первого вхождения. `match_gmail_to_handle` сейчас делает unique-candidate check (возвращает None при `len(candidates) > 1`) — порядок не важен. |
| R6 | i18n: prefix-strip в шаге 3.d работает только для русской локали (`'Вы выбрали аккаунт '`). На английской UI desc=`'You selected account ...'` пройдёт без strip и emit'нет с мусорным префиксом в display. | Тестбенч сейчас на русском (factory_inst_accounts только русские). Если появится англоязычный rig — добавим английский pattern. Помечено как known limitation. |

---

## 8. Definition of Done

- `extract_yt_picker_pairs(round_0.xml)` возвращает (как минимум) `('feminista.beauty', 'veronikamavrikeva@gmail.com')` и `('WellFresh_1', 'zxclesya154@gmail.com')`.
- `extract_yt_picker_deleted_pairs` симметрично работает на иерархичный formatlat для deleted.
- 8 новых tests + 11 existing tests все зелёные.
- Deploy в prod main → auto-push → восстановлены `/root/.openclaw/workspace-genri/autowarm/`.
- Re-queue 3243/3246/3247 (через `publish_queue → pending + publish_task_id=NULL` per memory `reference_publish_requeue_path`) → наблюдаем результат.
  - Если прошли публикацию — P0.1 closed empirically, sub-project complete.
  - Если упали с `yt_target_not_in_picker_after_scroll` — открываем switcher fix как follow-up sub-project (с evidence из новых dump'ов).

---

## 9. Связанные памяти и evidence

- `project_session_2026_05_07_shipped.md` — backlog raised B-YT-parser/B-YT-switcher.
- `reference_yt_picker_structure_2026_05_07.md` — иерархичная структура picker'а.
- `project_yt_gmail_switcher.md` — gmail column миграция + backfill_yt_gmails.py logic.
- `reference_publish_requeue_path.md` — re-queue flow.
- `feedback_codex_review_specs.md` — этот spec будет прогнан через `codex review`.

