# PLAN — IG publish follow-ups #1-#4 (Important items)

**Тип:** fix (hardening + tests)
**Создан:** 2026-04-29
**Режим:** Full
**Источник:** memory `project_ig_publish_fixes_followups_backlog.md` (backlog после shipment `4b8ad20` 2026-04-28)

**Репо:**
- Код: `/root/.openclaw/workspace-genri/autowarm/` (post-commit hook auto-push в `GenGo2/delivery-contenthunter`).
- Plan/evidence: `/home/claude-user/contenthunter/` (текущая ветка `fix/testbench-publisher-base-imports-20260427`).

## Settings

- **Testing:** yes — T2/T3 — новые unit-тесты, pytest должен быть green перед каждым commit'ом.
- **Logging:** warn-only — strict-selector miss-case пишет `category='ig_create_tile_strict_miss'` warning event для последующего мониторинга.
- **Docs:** warn-only — evidence обязателен (`.ai-factory/evidence/ig-publish-followups-1-4-20260429.md`), отдельный docs-коммит не требую.
- **Roadmap linkage:** none.

## Контекст

Bundle 4 коммитов (`fa8570f`, `87c203a`, `39d60eb`, `faf91ea`) merged 2026-04-28 как `4b8ad20`. Финальный code-reviewer одобрил «as shipped» и идентифицировал 8 follow-ups. Этот план — 4 Important (#1-#4):

- **#1 Strict-selector раскатка** — T2 helper `_tap_create_reels_tile_strict()` сейчас вызывается ТОЛЬКО в `[FIX: IG-stuck-on-profile]` recovery branch (line 727). Permissive `tap_element(['Reels','Reel','ВИДЕО REELS'])` остался в `:410` (FIX-IG-reopen-via-home) и `:581` (main happy-path bottomsheet — самый частый код-путь).
- **#2 Unit-тесты `_verify_reels_camera_mode`** — pure helper с 5 mode-ветками без тестов. Plan не требовал, но markers list — потенциальный источник регрессий (см. #4).
- **#3 Unit-тесты T4 enrichment** — try/except в error block proглатывает все ошибки → silent break possible. Без теста следующая регрессия маскируется.
- **#4 False-positive guard** — текущая реализация `_verify_reels_camera_mode` делает raw substring scan по всему UI XML (`if 'Близкие друзья' in ui:` и др.). False-positive если post-camera state когда-нибудь включит этот helper'а. Mitigation: attribute-scoped matching (`text="..."` / `content-desc="..."` через ET.fromstring, паттерн уже использован в `_ig_tap_action_bar_done:153`).

## Корневые причины (быстрая проверка)

- `:410` — `if ui_post and self.tap_element(ui_post, ['Reels', 'Reel', 'ВИДЕО REELS'], clickable_only=True):` — fallback при miss = log.debug + camera-wait loop доделает.
- `:581` — `if self.tap_element(ui, ['Reels', 'Reel', 'ВИДЕО REELS'], clickable_only=True):` — fallback при miss = deeplink-retry через `instagram://reels-camera`.
- Strict miss НЕ должна блокировать — оба fallback'а валидны, просто warning event для трейсинга.

## Scope

**В scope:**
1. **T0 — pre-check:** SQL-проверка свежих failed-задач после deploy bundle (это #5 в memory backlog).
2. **T1 — strict-selector раскатка** на `:410, :581` + warning event на miss.
3. **T2 — unit-тесты** `_verify_reels_camera_mode` (5 mode-веток + empty UI + edge case audience-picker).
4. **T3 — unit-тесты** T4 enrichment (`ig_editor_timeout` meta).
5. **T4 — attribute-scoped matching** в `_verify_reels_camera_mode` через ET.fromstring.
6. **T5 — smoke + restart + 30-min SQL verify.**
7. **T6 — evidence + memory + commits.**

**НЕ в scope (deferred):**
- #6 `last_action='no_action'` cleanup в meta — отдельный mini-PR.
- #7 `range(30)` vs `max_steps: 20` рассинхрон — janitorial.
- #8 testbench backport бандла (4 коммитов) — отдельная сессия.

## Задачи

### T0. Pre-check — live SQL verify

```sql
SELECT id, platform, status, error_code, started_at, updated_at
FROM publish_tasks
WHERE updated_at >= '2026-04-28 18:50:00'
  AND status='failed'
ORDER BY id DESC LIMIT 20;
```

**Ожидание:** все новые failed-задачи имеют непустой `error_code` (T1 bundle применился). Если массово NULL → диагностировать (PM2 cwd drift / orchestrator stale) **ПЕРЕД** другими changes.

**Блокер:** если ≥50% NULL в свежих failed → остановить, разобраться. Пример stop-condition: cwd `pm2 describe autowarm | grep "exec cwd"` показывает stale path вместо `/root/.openclaw/workspace-genri/autowarm/`.

**Логирование:** результат SQL в evidence, секция «T0 pre-check».

### T1. Strict-selector раскатка на :410 + :581

Файл: `/root/.openclaw/workspace-genri/autowarm/publisher_instagram.py`.

**`:410` (FIX-IG-reopen-via-home post-launch path):**

```python
# Было:
if ui_post and self.tap_element(ui_post, ['Reels', 'Reel', 'ВИДЕО REELS'],
                                clickable_only=True):
    log.info('[FIX: IG-reopen-via-home] ✅ Reels выбран после reset')
    time.sleep(3)

# Стало:
if ui_post:
    if self._tap_create_reels_tile_strict(ui_post):
        log.info('[FIX: IG-reopen-via-home] ✅ Reels выбран после reset (strict)')
        time.sleep(3)
    else:
        self._record_event(type='warning',
                           category='ig_create_tile_strict_miss',
                           message='strict matcher missed at IG-reopen-via-home (line 410)')
        log.debug('[FIX: IG-reopen-via-home] strict-miss — camera-wait loop доделает')
```

**`:581` (main happy-path bottomsheet):**

```python
# Было:
if self.tap_element(ui, ['Reels', 'Reel', 'ВИДЕО REELS'],
                    clickable_only=True):
    log.info('  ✅ Reels выбран из bottomsheet')
    time.sleep(3)
else:
    # Fallback: bottomsheet не появился → старый deeplink-путь
    log.warning('  Reels не найден в bottomsheet → fallback deeplink')
    ...

# Стало:
if self._tap_create_reels_tile_strict(ui):
    log.info('  ✅ Reels выбран из bottomsheet (strict)')
    time.sleep(3)
else:
    self._record_event(type='warning',
                       category='ig_create_tile_strict_miss',
                       message='strict matcher missed at happy-path bottomsheet (line 581) → deeplink fallback')
    log.warning('  Reels не найден strict matcher → fallback deeplink')
    self.adb(f'am force-stop {package}')
    ...
```

**Существующий тест-файл `tests/test_ig_create_tile_selector.py`** (3 теста) автоматически покрывает helper'ом, дополнительные тесты под этот раскат не нужны.

**Логирование:** `[FIX: IG-reopen-via-home] strict-miss …`, `ig_create_tile_strict_miss` events в `publish_events`.

### T2. Unit-тесты `_verify_reels_camera_mode`

Новый файл: `/root/.openclaw/workspace-genri/autowarm/tests/test_ig_camera_mode_verifier.py`.

5 fixture XML (либо как inline-multiline-strings в тесте, либо в `tests/fixtures/`):

| Fixture | Markers | Expected |
|---|---|---|
| reels_mode | `clips_tab` selected/active | `(True, 'reels')` |
| reels_proxy | `REELS` без clips_tab (camera tab bar) | `(True, 'reels_proxy')` |
| stories_mode | text=«Ваша история» / «Дополнить историю» / `story_camera` | `(False, 'stories')` |
| photo_mode | `feed_camera` resource-id или text=«Опубликовать в ленту» | `(False, 'photo')` |
| live_mode | text=«Выйти в эфир» / `live_camera` | `(False, 'live')` |
| empty | `''` или whitespace | `(False, 'empty_ui')` |
| unknown | минимальный XML без markers | `(False, 'unknown')` |

```python
def test_reels_mode_correctly_detected():
    helper = make_publisher_stub()
    fixture = '<hierarchy>...clips_tab...</hierarchy>'
    in_reels, mode = helper._verify_reels_camera_mode(fixture)
    assert (in_reels, mode) == (True, 'reels')

def test_stories_mode_correctly_detected():
    ...

def test_photo_mode_correctly_detected():
    ...

def test_live_mode_correctly_detected():
    ...

def test_empty_ui_returns_empty_ui():
    helper = make_publisher_stub()
    assert helper._verify_reels_camera_mode('') == (False, 'empty_ui')

def test_unknown_ui_returns_unknown():
    ...
```

Helper `make_publisher_stub()` — минимальный класс, наследник `InstagramMixin` с моками для зависимостей (если нужны). По факту `_verify_reels_camera_mode` — pure function, можно вызвать как `InstagramMixin._verify_reels_camera_mode(None, xml)` (но осторожно с `self.method` vs `Class.method` — см. `feedback_class_vs_instance_test_calls.md`).

**Pytest:** `python -m pytest tests/test_ig_camera_mode_verifier.py -v` → 6+ passed.

**Логирование:** счётчик passed в evidence.

### T3. Refactor T4 enrichment в helper + unit-тесты

**Где живёт T4:** `publisher_instagram.py:1448-1477` (inline в editor-watcher методе после `for step in range(...)`-цикла). Для testability — extract в helper.

**T3a — extract helper (small refactor):**

```python
def _build_ig_editor_timeout_meta(self, ui: str, last_action: str) -> dict:
    """T4 enrichment: post-mortem context для ig_editor_timeout event.
    
    Извлекает top-12 текстов из UI dump'а, screenshot URL из _collected_screenshots,
    ui_snippet (300 chars). Все exceptions проглатываются — meta всегда возвращается.
    """
    try:
        _shots = getattr(self, '_collected_screenshots', None) or []
        screenshot_url = _shots[-1] if _shots else None
    except Exception:
        screenshot_url = None
    last_ui_texts = []
    try:
        import xml.etree.ElementTree as _ETet
        for n in _ETet.fromstring(ui or '').iter('node'):
            t = (n.get('text', '') or n.get('content-desc', '')).strip()
            if t and len(t) > 1:
                last_ui_texts.append(t)
        last_ui_texts = last_ui_texts[:12]
    except Exception:
        pass
    return {
        'category': 'ig_editor_timeout',
        'platform': self.platform,
        'step': 'editor_watcher',
        'max_steps': 20,
        'last_action': last_action,
        'last_ui_texts': last_ui_texts,
        'screenshot_url': screenshot_url,
        'ui_snippet': (ui or '')[:300],
    }
```

Заменить блок `1448-1477` на:

```python
log.warning('Редактор Reels: не дошёл до экрана подписи за 20 шагов')
self._save_debug_artifacts('instagram_editor_timeout')
meta = self._build_ig_editor_timeout_meta(ui, last_action)
self.log_event('error',
               'Instagram: редактор не дошёл до подписи (timeout 20 шагов)',
               meta=meta)
return False
```

**T3b — unit-тесты:** новый файл `tests/test_ig_editor_timeout_meta.py`.

```python
def test_meta_enrichment_happy_path():
    """meta содержит все 8 ключей с правильными значениями."""
    pub = make_ig_publisher_stub(platform='Instagram')
    pub._collected_screenshots = ['https://save.gengo.io/autowarm/screenshots/abc.jpg']
    ui = '<hierarchy><node text="Далее" content-desc=""/><node text="Поделиться" content-desc=""/></hierarchy>'
    
    meta = pub._build_ig_editor_timeout_meta(ui, last_action='no_action')
    
    assert meta['category'] == 'ig_editor_timeout'
    assert meta['platform'] == 'Instagram'
    assert meta['step'] == 'editor_watcher'
    assert meta['max_steps'] == 20
    assert meta['last_action'] == 'no_action'
    assert isinstance(meta['last_ui_texts'], list) and len(meta['last_ui_texts']) <= 12
    assert 'Далее' in meta['last_ui_texts']
    assert meta['screenshot_url'] == 'https://save.gengo.io/autowarm/screenshots/abc.jpg'
    assert meta['ui_snippet'].startswith('<') and len(meta['ui_snippet']) <= 300

def test_meta_no_screenshots_fallback_to_none():
    pub = make_ig_publisher_stub()
    pub._collected_screenshots = []
    meta = pub._build_ig_editor_timeout_meta('<hierarchy/>', last_action='x')
    assert meta['screenshot_url'] is None

def test_meta_invalid_xml_does_not_break():
    pub = make_ig_publisher_stub()
    pub._collected_screenshots = ['https://...']
    meta = pub._build_ig_editor_timeout_meta('<malformed', last_action='x')
    assert meta['last_ui_texts'] == []  # parse error swallowed
    assert meta['screenshot_url'] == 'https://...'  # screenshot still present

def test_meta_filters_empty_texts():
    pub = make_ig_publisher_stub()
    ui = '<hierarchy><node text=""/><node text="A"/><node text="Поделиться"/></hierarchy>'
    meta = pub._build_ig_editor_timeout_meta(ui, last_action='x')
    # text='' и text='A' (length<=1) фильтруются
    assert meta['last_ui_texts'] == ['Поделиться']
```

**Stub helper:** минимальный класс с `platform` атрибутом — `_build_ig_editor_timeout_meta` использует только `self.platform` и `self._collected_screenshots`.

**Pytest:** 3+ passed.

### T4. Attribute-scoped matching в `_verify_reels_camera_mode`

Файл: `/root/.openclaw/workspace-genri/autowarm/publisher_instagram.py:106-148`.

**Что меняется:** raw `if 'marker' in ui:` → парсинг XML через `ET.fromstring(ui)` + проверка элементов по атрибутам `text`/`content-desc`/`resource-id`. resource-id остаётся substring-friendly (`'story_camera' in rid`), text/content-desc — exact match по element.get('text').

```python
def _verify_reels_camera_mode(self, ui: str) -> tuple:
    """Verify камера в Reels-mode (НЕ Stories/Photo/Live).
    
    Returns: (in_reels: bool, detected_mode: str)
    
    ⚠️  ONLY вызывать ДО camera-step (post-tap-Reels-tile).
    После audience-picker'а появляется text='Близкие друзья' как валидная Reels-share
    опция → false-positive 'stories' detection.
    """
    if not ui or not ui.strip():
        return (False, 'empty_ui')
    
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(ui)
    except ET.ParseError:
        return (False, 'parse_error')
    
    # Сбираем text + content-desc + resource-id со всех элементов
    texts = set()
    descs = set()
    rids = set()
    for node in root.iter('node'):
        t = node.get('text', '')
        d = node.get('content-desc', '')
        r = node.get('resource-id', '')
        if t:
            texts.add(t)
        if d:
            descs.add(d)
        if r:
            rids.add(r)
    
    text_or_desc = texts | descs
    
    # Stories markers (priority — самая частая wrong-landing)
    stories_text_markers = {'Дополнить историю', 'Ваша история', 'Близкие друзья'}
    stories_rid_substrings = ('story_camera', 'reels_creation_story')
    if text_or_desc & stories_text_markers:
        return (False, 'stories')
    if any(any(s in r for s in stories_rid_substrings) for r in rids):
        return (False, 'stories')
    
    # Photo
    if 'Опубликовать в ленту' in text_or_desc:
        return (False, 'photo')
    if any('feed_camera' in r for r in rids):
        return (False, 'photo')
    
    # Live
    if 'Выйти в эфир' in text_or_desc:
        return (False, 'live')
    if any('live_camera' in r for r in rids):
        return (False, 'live')
    
    # Reels positive
    if any('clips_tab' in r for r in rids):
        return (True, 'reels')
    if 'REELS' in text_or_desc or 'Reels camera' in text_or_desc:
        return (True, 'reels_proxy')
    
    return (False, 'unknown')
```

**Регрессионная защита:** T2-фикстуры обновить так чтобы fixtures имели `text="..."` / `content-desc="..."` / `resource-id="..."` атрибуты, а не raw строки в произвольных местах.

**Edge-case test (добавить в `test_ig_camera_mode_verifier.py`):**

```python
def test_close_friends_in_audience_picker_does_not_false_positive():
    """T4 защита: 'Близкие друзья' в audience-picker (text атрибут) — это POST-camera,
    helper не должен возвращать stories. Но если он туда всё-таки попадёт, наш new code
    всё ещё вернёт stories (это by-design — helper НЕ должен вызываться post-camera).
    Тест документирует ЭТО поведение."""
    # Этот тест utilities documenter'ом — фиксирует, что helper применим только pre-camera.
    fixture = '<hierarchy><node text="Близкие друзья" resource-id="audience_option"/></hierarchy>'
    helper = make_publisher_stub()
    in_reels, mode = helper._verify_reels_camera_mode(fixture)
    assert (in_reels, mode) == (False, 'stories')  # by-design
```

**Логирование:** ничего нового; функция тихая.

### T5. Smoke + restart + 30-min SQL verify

1. **Pytest** в prod dir:
   ```
   cd /root/.openclaw/workspace-genri/autowarm
   python -m pytest tests/test_ig_create_tile_selector.py tests/test_ig_camera_mode_verifier.py tests/test_ig_editor_timeout_meta.py -v
   ```
   Все green.

2. **Pre-restart check** — очередь почти пустая:
   ```sql
   SELECT count(*) FILTER (WHERE status='running') AS running,
          count(*) FILTER (WHERE status='claimed') AS claimed
   FROM publish_tasks
   WHERE platform='Instagram';
   ```
   Если `running + claimed > 1` — подождать или постановить deferred restart.

3. **Restart:** `sudo pm2 restart autowarm` → `pm2 logs autowarm --lines 30` чисто (нет ImportError/NameError).

4. **30-min live SQL verify:**
   ```sql
   SELECT id, account, status, error_code, started_at, updated_at,
          jsonb_path_exists(events::jsonb, '$[*].category ? (@ == "ig_create_tile_strict_miss")') AS strict_miss
   FROM publish_tasks
   WHERE platform='Instagram'
     AND updated_at >= NOW() - INTERVAL '30 minutes'
   ORDER BY id DESC LIMIT 20;
   ```
   
   Ожидание: все failed имеют непустой `error_code`. Если `strict_miss=true` встречается часто (>30% failed) — strict-helper отвергает валидные плитки, нужно расширить candidate list или вернуться на permissive в одной из веток.

**Логирование:** SQL output + pm2 restart line в evidence.

### T6. Evidence + memory + commits

**Evidence:** `.ai-factory/evidence/ig-publish-followups-1-4-20260429.md`:
- T0 pre-check SQL output
- T1 diff snippet (2 места)
- T2 pytest счётчик и список тест-кейсов
- T3 pytest счётчик
- T4 diff snippet
- T5 pytest + restart + 30-min SQL результат
- Open follow-ups update в `project_ig_publish_fixes_followups_backlog.md`

**Memory:**
- Update `project_ig_publish_fixes_followups_backlog.md`: вычеркнуть #1, #2, #3, #4 как closed by commits (с SHA).
- Update `project_publisher_modularization_wip.md` параграф «IG publish hardening — 2026-04-29».

**Коммит-цепочка:**

| # | Repo/branch | Сообщение | Содержание |
|---|---|---|---|
| 1 | prod autowarm (auto-push) | `fix(ig-publisher): rollout strict Reels-tile selector to 2 more bottomsheets` | T1 |
| 2 | prod autowarm | `test(ig-publisher): unit tests for _verify_reels_camera_mode (5 modes)` | T2 |
| 3 | prod autowarm | `test(ig-publisher): unit tests for ig_editor_timeout meta enrichment` | T3 |
| 4 | prod autowarm | `fix(ig-publisher): attribute-scoped markers in _verify_reels_camera_mode` | T4 |
| 5 | contenthunter (current branch) | `docs(plans+evidence): IG publish follow-ups #1-#4 — executed T0-T6` | план + evidence + memory bumps |

Каждый prod commit auto-pushится hook'ом в `GenGo2/delivery-contenthunter`.

## Commit Plan

5 коммитов = 4 atomic prod + 1 docs. Pytest должен быть green ПЕРЕД каждым из commits 1-4 (правило `feedback_parallel_claude_sessions.md` — atomic commits, no half-broken state).

## Риски

- **R1 — strict helper отвергает валидную плитку в edge-UI** (на :410 или :581). Mitigation: `ig_create_tile_strict_miss` warning event + сохранение существующих fallback'ов (camera-wait loop / deeplink). Не block. Live SQL verify в T5 поймает high miss-rate.
- **R2 — pm2 restart прерывает running publish_tasks.** Mitigation: pre-check `running+claimed ≤ 1` перед restart'ом.
- **R3 — attribute-scoped matching ломает существующий fixture** `tests/fixtures/ig_create_bottom_sheet.xml` от bundle. Mitigation: проверить fixture структуру, убедиться `text`/`content-desc`/`resource-id` атрибуты есть на нужных нодах.
- **R4 — параллельная сессия paginated этап-3** в `autowarm-paginated-etap3` worktree. Файлы: `server.js`/`public/`/`paginate.js` — НЕ пересекаются с `publisher_instagram.py`. PM2 restart пересекается — координировать (одна сессия рестартит, другая ждёт).
- **R5 — testbench отстаёт от prod на 4 коммита bundle** + 4 коммита этого плана. Backport (#8) — отдельная сессия, риск регрессий в testbench пока не закрыт.

## Rollback

- Commit 1 (T1 strict raskatka): `git revert` возвращает permissive `tap_element` на :410, :581. Безопасно, единственный side-effect — возвращается риск 1532-каскада в Stories.
- Commit 2 (T2 tests): чистый additive, revert редко нужен.
- Commit 3 (T3 tests): то же.
- Commit 4 (T4 attribute-scoped): `git revert` возвращает raw substring matching. Тесты T2 могут упасть после revert — нужно одновременно revert'нуть 2+4 если откатываем матчинг.
- Commit 5 (docs): не нуждается в revert.

## Дальше

Исполнять прямым порядком T0 → T1 → T2 → T3 → T4 → T5 → T6.

**Stop-conditions:**
- T0 показал ≥50% NULL error_code в свежих failed — остановиться, диагностировать prod.
- T5 показал strict_miss >30% failed IG — откатить T1, расширить strict candidate list.

После всех 5 commits: memory bump + сообщение пользователю «#1-#4 закрыто, остаются Minor #6/#7 + #8 testbench backport».
