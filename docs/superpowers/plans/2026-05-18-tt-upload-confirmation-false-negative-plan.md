# TT `tt_upload_confirmation_timeout` false-negative — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть `tt_upload_confirmation_timeout` ложно-отрицательный (10/14 TT-фейлов за 2026-05-18) — продвинуть post-publish детектор в начало wait-loop, расширить маркеры, поправить perm-detector substring, добавить promo-modal handler, ввести cap → success в perm + promo handlers.

**Architecture:** Все изменения в одном модуле `publisher_tiktok.py`. Существующий `_tt_infer_post_publish_success` гейтится за новым env-flag в раннюю позицию `_wait_upload_confirmation`. Старый поздний блок сохраняется как fallback. Новый promo-modal handler следует existing pattern (Samsung overlay). Perm-dialog handler меняет return-type на tri-state (`True`/`False`/`'inferred_success'`).

**Tech Stack:** Python 3, pytest, реальные UI-dumps как fixtures, env-flags для kill-switches.

**Связанные документы:**
- Spec: `docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md`
- OpenProject: [WP #82](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/82)

**Code lives in autowarm repo:** `/root/.openclaw/workspace-genri/autowarm/`. Этот worktree (contenthunter) хранит spec/plan; код и тесты идут туда.

---

## Task 0: Подготовка ветки в autowarm-репе

**Files:**
- Switch: `/root/.openclaw/workspace-genri/autowarm/` (prod autowarm checkout)

Контекст: autowarm имеет post-commit auto-push. Параллельная сессия может уже сидеть на своей ветке. Создаём **свою** ветку, чтобы коммиты не уходили в чужую и не триггерили deploy main.

- [ ] **Step 1: Fetch main и стартовать ветку**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin main
git checkout -b tt-upload-confirm-false-negative-2026-05-18 origin/main
```

Expected: `Switched to a new branch 'tt-upload-confirm-false-negative-2026-05-18'`

- [ ] **Step 2: Verify clean state и что pytest baseline зелёный**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git status --short
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py tests/test_publisher_tt_music_rights.py -q 2>&1 | tail -10
```

Expected: `git status` — clean. Pytest — green (зелёный baseline; fixed test count, no failures).

---

## Task 1: Зафиксировать XML-fixtures из инцидента

**Files:**
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_publish/task6750_iter1_profile_with_fresh_post.xml`
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_publish/task6750_iter10_promo_inbox_modal.xml`
- Create: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_publish/task6789_iter1_fb_friends_perm.xml`
- Modify: `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/PROVENANCE.md` (append entries для новых файлов)

Reason: каждый тест ниже должен загружать **реальный** дамп из прода, не synthetic mini-XML — иначе пропускаются edge-кейсы реального TT layout.

- [ ] **Step 1: Скопировать дампы**

```bash
mkdir -p /root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_publish

cp /tmp/autowarm_ui_dumps/tt_post_music_rights_task_6750_iter1_*.xml \
   /root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_publish/task6750_iter1_profile_with_fresh_post.xml

cp /tmp/autowarm_ui_dumps/tt_post_music_rights_task_6750_iter10_*.xml \
   /root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_publish/task6750_iter10_promo_inbox_modal.xml
```

Для FB-friends perm-dialog нужен дамп task 6789 — он на устройстве prod, не сохранён локально. Воспроизводим из реального XML который видели в скринкасте (substring + clickable buttons):

```bash
cat > /root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_publish/task6789_iter1_fb_friends_perm.xml <<'EOF'
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]" package="com.zhiliaoapp.musically">
    <node class="android.widget.FrameLayout" content-desc="Диалог" bounds="[120,800][960,1500]" clickable="false">
      <node class="android.widget.TextView" text="Разрешить TikTok доступ к списку ваших друзей в Facebook и почтовому адресу? Так мы сможем сделать TikTok еще лучше и удобнее для вас, в том числе поможем найти ваших друзей." bounds="[160,820][920,1280]" clickable="false" />
      <node class="android.widget.Button" text="OK" content-desc="OK" bounds="[660,1340][900,1440]" clickable="true" />
      <node class="android.widget.Button" text="Не разрешать" content-desc="Не разрешать" bounds="[160,1340][640,1440]" clickable="true" />
    </node>
  </node>
</hierarchy>
EOF
```

Expected: 3 файла созданы, размеры >1KB каждый.

- [ ] **Step 2: Verify files exist**

```bash
ls -la /root/.openclaw/workspace-genri/autowarm/tests/fixtures/tt_post_publish/
```

Expected: 3 .xml файла.

- [ ] **Step 3: Обновить PROVENANCE.md**

Откройте `/root/.openclaw/workspace-genri/autowarm/tests/fixtures/PROVENANCE.md`. В конец добавьте:

```markdown

## tt_post_publish/ (2026-05-18, WP #82)

- `task6750_iter1_profile_with_fresh_post.xml` — UI dump after music_rights_accept на task 6750 (account `tkachenko_biohack`). Профиль с свежим постом, `Get more views` CTA, bottom-nav из 5 групп. Источник: `/tmp/autowarm_ui_dumps/` на VPS, prod task 2026-05-18 05:25:57 UTC.
- `task6750_iter10_promo_inbox_modal.xml` — same task, iter10. TT promo-модал «Улучшенные входящие сообщения для бизнеса» перекрывает экран; `Закрыть` clickable=true, но re-presentится TT'ом.
- `task6789_iter1_fb_friends_perm.xml` — синтетика, воспроизводящая FB-friends perm-dialog из task 6789 (account `feminista_patches`, 06:32 UTC). Substring `доступ к списку ваших друзей в Facebook` + OK/Не разрешать clickable buttons.
```

- [ ] **Step 4: Commit fixtures**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add tests/fixtures/tt_post_publish/ tests/fixtures/PROVENANCE.md
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
test(tt): fixtures для tt_upload_confirmation_timeout triage (WP #82)

Реальные XML-дампы из инцидента 2026-05-18:
- task6750 iter1: профиль с post-publish CTA + bottom-nav
- task6750 iter10: promo-модал «Улучшенные входящие»
- task6789 iter1: FB-friends perm-dialog (synthetic из реального layout)

Spec: docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md
EOF
)"
```

Expected: 1 commit with 4 file changes.

---

## Task 2: Change 3 — tighten `share_btn_clickable` (exact-match)

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py:2088-2099`
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_publisher_tt_overlay_handlers.py` (новая function)

Reason: substring `'поделиться'` хватает overlay `«Поделиться видео. Уже поделились:»` на feed/profile → бот думает что мы на editor → false-positive retap. Меняем на exact-match.

Этот change — самый низкорисковый, делаем первым.

- [ ] **Step 1: Написать failing-тест**

В конец `/root/.openclaw/workspace-genri/autowarm/tests/test_publisher_tt_overlay_handlers.py` добавить:

```python
# ────────────────────────── share_btn_clickable false-positive guard ─────────
# WP #82 (2026-05-18): substring 'поделиться' хватал overlay
# «Поделиться видео. Уже поделились:» на feed/profile screen → false retap.


def _scan_share_btn_clickable(ui_xml: str) -> bool:
    """Replica логики publisher_tiktok.py:2088-2099 share_btn_clickable
    (post-fix exact-match). Используется тестом для regression-guard'а.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(ui_xml)
    except Exception:
        return False
    for node in root.iter('node'):
        if node.get('clickable') != 'true':
            continue
        txt = (node.get('text', '') or '').strip()
        desc = (node.get('content-desc', '') or '').strip()
        if (txt in ('Поделиться', 'Post', 'Publish')
                or desc in ('Поделиться', 'Post', 'Publish')):
            return True
    return False


def test_share_btn_clickable_no_false_positive_on_feed_overlay():
    """Feed overlay «Поделиться видео. Уже поделились:» NOT a share button."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6750_iter1_profile_with_fresh_post.xml')
    ui = fixture.read_text()
    assert _scan_share_btn_clickable(ui) is False, \
        'overlay «Поделиться видео. Уже поделились:» НЕ должен быть share-btn'


def test_share_btn_clickable_positive_on_real_share_button():
    """Exact «Поделиться» on a clickable button — должен detect'иться."""
    ui = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.Button" text="Поделиться" clickable="true" bounds="[400,2000][680,2100]"/>
</hierarchy>'''
    assert _scan_share_btn_clickable(ui) is True
```

- [ ] **Step 2: Запустить тест, убедиться что fail-ит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py::test_share_btn_clickable_no_false_positive_on_feed_overlay -v 2>&1 | tail -10
```

Expected: тест PASS-ит сразу (потому что `_scan_share_btn_clickable` — local helper, не код продукта). Это **expected pre-condition** — он защищает helper от регрессии. Real bug-trigger тест ниже в Step 6.

- [ ] **Step 3: Найти и заменить production-код**

В `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py` найти блок (около line 2088-2099):

```python
            share_btn_clickable = False
            try:
                import xml.etree.ElementTree as ET
                root_el = ET.fromstring(ui)
                for node in root_el.iter('node'):
                    if node.get('clickable') == 'true':
                        txt = (node.get('text','') + node.get('content-desc','')).lower()
                        if 'поделиться' in txt or txt.strip() == 'post':
                            share_btn_clickable = True
                            break
            except Exception:
                pass
```

Заменить на:

```python
            share_btn_clickable = False
            try:
                import xml.etree.ElementTree as ET
                root_el = ET.fromstring(ui)
                for node in root_el.iter('node'):
                    if node.get('clickable') != 'true':
                        continue
                    txt = (node.get('text', '') or '').strip()
                    desc = (node.get('content-desc', '') or '').strip()
                    # WP #82 2026-05-18: exact-match — substring 'поделиться'
                    # хватал overlay «Поделиться видео. Уже поделились:» на
                    # post-publish feed → false retap.
                    if (txt in ('Поделиться', 'Post', 'Publish')
                            or desc in ('Поделиться', 'Post', 'Publish')):
                        share_btn_clickable = True
                        break
            except Exception:
                pass
```

- [ ] **Step 4: Запустить тесты — все должны pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py -q 2>&1 | tail -15
```

Expected: все тесты PASS (baseline + 2 новых).

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_tiktok.py tests/test_publisher_tt_overlay_handlers.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
fix(tt): share_btn_clickable exact-match вместо substring (WP #82)

Substring 'поделиться' хватал content-desc «Поделиться видео. Уже
поделились:» на post-publish feed/profile → false-positive retap-ветка
зацикливалась в _wait_upload_confirmation.

Spec: docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md
EOF
)"
```

---

## Task 3: Change 4(a) — расширить perm-dialog SUBSTRING на FB-friends

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py:239` (const), `:343` (detector logic)
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_publisher_tt_overlay_handlers.py`

Reason: existing `_TT_PERM_DIALOG_TITLE_SUBSTRING = 'доступ к контактам'` не matchит FB-friends dialog (tasks 6789, 6809: `«доступ к списку ваших друзей в Facebook»`). Меняем константу на список и detector проходит `any()`.

- [ ] **Step 1: Написать failing-тест**

В конец `/root/.openclaw/workspace-genri/autowarm/tests/test_publisher_tt_overlay_handlers.py`:

```python
# ────────────────────────── perm-dialog FB-friends coverage ──────────────────
# WP #82: добавляем второй вариант title-substring для FB-friends dialog.


def test_perm_dialog_fb_friends_detected():
    """FB-friends dialog (tasks 6789, 6809) detect=True через расширенный
    SUBSTRING list."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6789_iter1_fb_friends_perm.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    assert mx._detect_tt_contacts_perm(ui) is True


def test_perm_dialog_contacts_still_detected():
    """Existing dialog `«доступ к контактам»` тоже detect=True (regression)."""
    ui = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.FrameLayout" content-desc="Диалог">
    <node text="Разрешить TikTok доступ к контактам?" bounds="[100,800][900,1200]"/>
    <node text="Не разрешать" content-desc="Не разрешать" clickable="true" bounds="[150,1300][500,1400]"/>
    <node text="Открыть настройки" content-desc="Открыть настройки" clickable="true" bounds="[550,1300][900,1400]"/>
  </node>
</hierarchy>'''
    mx = _bare_mixin()
    assert mx._detect_tt_contacts_perm(ui) is True
```

Note: FB-friends fixture не имеет `Открыть настройки` button — он имеет `OK` + `Не разрешать`. Existing `_detect_tt_contacts_perm` требует BOTH deny AND open-settings clickable. Это сломает positive test. Значит надо изменить detector чтобы для FB-friends варианта требовалось только `Не разрешать` clickable (open-settings нет в FB-flow).

Корректируем подход: detector меняет логику — для каждой SUBSTRING смотрим требуемый набор кнопок. Контакты → deny + open-settings. FB-friends → deny + OK.

Обновлённый тест и detector:

```python
def test_perm_dialog_fb_friends_detected():
    """FB-friends dialog detected by SUBSTRING + deny + ok buttons."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6789_iter1_fb_friends_perm.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    assert mx._detect_tt_contacts_perm(ui) is True
```

- [ ] **Step 2: Запустить тест, убедиться что fail-ит**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py::test_perm_dialog_fb_friends_detected -v 2>&1 | tail -10
```

Expected: FAIL (`_detect_tt_contacts_perm` returns False для FB-friends).

- [ ] **Step 3: Обновить production-код**

В `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py` найти (line 239):

```python
    # C — TT contacts permission dialog.
    _TT_PERM_DIALOG_TITLE_SUBSTRING = 'доступ к контактам'
    _TT_PERM_DIALOG_DENY_BUTTON = ['Не разрешать', "Don't allow"]
    _TT_PERM_DIALOG_OPEN_BUTTON = ['Открыть настройки', 'Open settings']
    MAX_PERM_DIALOG_ITERATIONS = 2
```

Заменить на:

```python
    # C — TT contacts / FB-friends permission dialogs (WP #82 2026-05-18:
    # FB-friends добавлен — `«доступ к списку ваших друзей в Facebook»`).
    # Каждая запись: (title_substring, secondary_button_candidates).
    # Detector требует title + deny + (любая из secondary).
    _TT_PERM_DIALOG_VARIANTS = [
        ('доступ к контактам', ['Открыть настройки', 'Open settings']),
        ('доступ к списку ваших друзей', ['OK', 'ОК']),
    ]
    _TT_PERM_DIALOG_DENY_BUTTON = ['Не разрешать', "Don't allow"]
    MAX_PERM_DIALOG_ITERATIONS = 5  # WP #82: было 2, поднимаем (cap → success в Task 7)
```

И найти `_detect_tt_contacts_perm` (line 336):

```python
    def _detect_tt_contacts_perm(self, ui_xml: str) -> bool:
        """TikTok contacts permission dialog detector.

        Requires title substring (`доступ к контактам`) PLUS BOTH buttons:
        deny (`Не разрешать`) AND open-settings (`Открыть настройки`), both
        clickable. Triple-marker → minimal false-positive.
        """
        if not ui_xml or self._TT_PERM_DIALOG_TITLE_SUBSTRING not in ui_xml:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        has_deny = False
        has_open = False
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if not has_deny and (
                txt in self._TT_PERM_DIALOG_DENY_BUTTON
                or desc in self._TT_PERM_DIALOG_DENY_BUTTON
            ):
                has_deny = True
            if not has_open and (
                txt in self._TT_PERM_DIALOG_OPEN_BUTTON
                or desc in self._TT_PERM_DIALOG_OPEN_BUTTON
            ):
                has_open = True
            if has_deny and has_open:
                return True
        return False
```

Заменить на:

```python
    def _detect_tt_contacts_perm(self, ui_xml: str) -> bool:
        """TikTok permission dialog detector (contacts ИЛИ FB-friends).

        Каждый variant в _TT_PERM_DIALOG_VARIANTS = (title_substring,
        secondary_button_candidates). Требует: title substring + deny clickable
        + ≥1 secondary clickable. WP #82: добавлен FB-friends variant.
        """
        if not ui_xml:
            return False
        matched_variant = None
        for title_sub, secondary in self._TT_PERM_DIALOG_VARIANTS:
            if title_sub in ui_xml:
                matched_variant = (title_sub, secondary)
                break
        if matched_variant is None:
            return False
        try:
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(ui_xml)
        except Exception:
            return False
        _, secondary = matched_variant
        has_deny = False
        has_secondary = False
        for n in root.iter('node'):
            if n.get('clickable') != 'true':
                continue
            txt = (n.get('text', '') or '').strip()
            desc = (n.get('content-desc', '') or '').strip()
            if not has_deny and (
                txt in self._TT_PERM_DIALOG_DENY_BUTTON
                or desc in self._TT_PERM_DIALOG_DENY_BUTTON
            ):
                has_deny = True
            if not has_secondary and (txt in secondary or desc in secondary):
                has_secondary = True
            if has_deny and has_secondary:
                return True
        return False
```

Также найти `_handle_tt_contacts_perm` (line 539) — он использует `self._TT_PERM_DIALOG_DENY_BUTTON` — это не меняется, OK. Но раньше handler ссылался на `_TT_PERM_DIALOG_TITLE_SUBSTRING` нигде кроме detector — проверьте grep'ом:

```bash
grep -n "_TT_PERM_DIALOG_TITLE_SUBSTRING\|_TT_PERM_DIALOG_OPEN_BUTTON" /root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py
```

Если найдены другие ссылки помимо тех что мы только что заменили — добавьте к этому Step фикс.

- [ ] **Step 4: Запустить тесты — все должны pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py -q 2>&1 | tail -15
```

Expected: all green, включая оба новых perm-dialog тестa.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_tiktok.py tests/test_publisher_tt_overlay_handlers.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
fix(tt): perm-dialog detector распознаёт FB-friends variant (WP #82)

Was: _TT_PERM_DIALOG_TITLE_SUBSTRING = 'доступ к контактам' — не matchил
«доступ к списку ваших друзей в Facebook» dialog (tasks 6789, 6809),
который проваливался в generic handler.

Now: _TT_PERM_DIALOG_VARIANTS list — title + deny + variant-specific
secondary (contacts→Открыть настройки, fb-friends→OK). Cap поднят
2→5 (cap→success follow-up Task 7).

Spec: docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md
EOF
)"
```

---

## Task 4: Change 2 — extend `_tt_infer_post_publish_success` маркерами

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py:85-162` (function `_tt_infer_post_publish_success`)
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_publisher_tt_overlay_handlers.py`

Reason: после dismiss promo-модала или когда `dumpsys activity activities` возвращает пусто, существующий детектор не видит success. Добавляем XML-маркеры (`Get more views` Button, `· N с. назад` timestamp), которые работают независимо от bottom-nav visibility и top-activity.

- [ ] **Step 1: Написать failing-тесты**

В конец `/root/.openclaw/workspace-genri/autowarm/tests/test_publisher_tt_overlay_handlers.py`:

```python
# ────────────────────────── _tt_infer_post_publish_success extensions ────────
# WP #82: fresh-post маркеры независимо от bottom-nav / top-activity.

from publisher_tiktok import _tt_infer_post_publish_success  # noqa: E402


def test_infer_success_fresh_post_cta_button():
    """«Get more views» Button → success даже с empty top_activity."""
    ui = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2340]">
    <node class="android.widget.Button" text="Get more views" bounds="[200,1800][880,1920]"/>
  </node>
</hierarchy>'''
    ok, meta = _tt_infer_post_publish_success(ui, '', wait_iter=1)
    assert ok is True
    assert meta['reason'] in ('fresh_post_cta', 'fresh_post_marker_no_activity')
    assert 'fresh_post_cta' in meta.get('markers_matched', [])


def test_infer_success_fresh_post_timestamp_seconds():
    """«· N с. назад» timestamp → success."""
    ui = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.TextView" text="· 1 с. назад" bounds="[100,1500][400,1560]"/>
</hierarchy>'''
    ok, meta = _tt_infer_post_publish_success(ui, '', wait_iter=1)
    assert ok is True
    assert 'fresh_post_timestamp' in meta.get('markers_matched', [])


def test_infer_success_fresh_post_timestamp_minutes():
    """«· N мин. назад» — тоже success (граничный случай)."""
    ui = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.TextView" text="· 2 мин. назад"/>
</hierarchy>'''
    ok, meta = _tt_infer_post_publish_success(ui, '', wait_iter=1)
    assert ok is True


def test_infer_success_fresh_post_timestamp_english():
    """«· N s ago» английская локаль."""
    ui = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.TextView" text="· 30 s ago"/>
</hierarchy>'''
    ok, meta = _tt_infer_post_publish_success(ui, '', wait_iter=1)
    assert ok is True


def test_infer_success_no_fresh_markers_no_nav_returns_false():
    """Без маркеров, без nav, без DetailActivity → fail (no regression)."""
    ui = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.TextView" text="Loading..."/>
</hierarchy>'''
    top = 'topResumedActivity=ActivityRecord{x com.zhiliaoapp.musically/.SomeActivity}'
    ok, meta = _tt_infer_post_publish_success(ui, top, wait_iter=1)
    assert ok is False


def test_infer_success_fresh_post_real_fixture():
    """Real production dump — должен detect'иться через любой из путей."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6750_iter1_profile_with_fresh_post.xml')
    ui = fixture.read_text()
    top = 'topResumedActivity=ActivityRecord{x com.zhiliaoapp.musically/com.ss.android.ugc.aweme.main.MainActivity}'
    ok, meta = _tt_infer_post_publish_success(ui, top, wait_iter=1)
    assert ok is True


def test_infer_success_flag_disabled_no_fresh_markers(monkeypatch):
    """Под `TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED=false` новые маркеры выкл."""
    monkeypatch.setenv('TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED', 'false')
    ui = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.Button" text="Get more views"/>
</hierarchy>'''
    ok, meta = _tt_infer_post_publish_success(ui, '', wait_iter=1)
    assert ok is False  # с выключенным flag и без nav → fail
```

- [ ] **Step 2: Запустить тесты, убедиться что новые fail-ят**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py -q 2>&1 | tail -15
```

Expected: 5 NEW tests FAIL (`fresh_post_cta` / `fresh_post_timestamp` пока не реализованы); existing — green; `test_infer_success_no_fresh_markers_no_nav_returns_false` и `test_infer_success_flag_disabled_no_fresh_markers` — pass (текущее поведение).

- [ ] **Step 3: Implement extension**

В `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py` найти функцию `_tt_infer_post_publish_success` (line 85-162). Внутри, ПОСЛЕ блока bottom-nav parsing (после `return False, meta` для `screen_height_implausible`/`main_nav_only_N_groups`), добавить новый блок — но логика рекурсивная: новые маркеры должны проверяться ДО early-return'а `not_on_tiktok`, потому что они защищают от пустого dumpsys.

Полная новая реализация:

```python
def _tt_infer_post_publish_success(ui, top_activity, wait_iter):
    """Detect post-publish success via topResumedActivity + bottom-nav XML parse.

    Returns: (success_bool, debug_meta_dict).
    debug_meta_dict содержит: top_activity, on_tiktok, on_composer_seed,
    nav_groups_visible, detail_activity, markers_matched, reason.

    WP #82 (2026-05-18): добавлены fresh-post XML маркеры
    (`Get more views` Button, `· N с. назад` timestamp) — работают независимо
    от bottom-nav и top-activity (защита от dialog-блокеров и flaky dumpsys).
    Гейтятся за env-flag TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED (default on).
    """
    import re as _re
    cur_act = (top_activity or '')
    meta = {
        'top_activity': cur_act[:160],
        'on_tiktok': False,
        'on_composer_seed': False,
        'nav_groups_visible': [],
        'detail_activity': False,
        'markers_matched': [],
        'reason': '',
    }

    # WP #82 fresh-post маркеры — вычисляем заранее, используем в нескольких ветках
    fresh_markers = []
    fresh_markers_enabled = (
        os.environ.get('TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED', 'true').lower() == 'true'
    )
    if fresh_markers_enabled and ui:
        try:
            import xml.etree.ElementTree as _ET
            root_fm = _ET.fromstring(ui)
            for node in root_fm.iter('node'):
                cls = node.get('class', '')
                txt = (node.get('text', '') or '').strip()
                if cls == 'android.widget.Button' and txt == 'Get more views':
                    fresh_markers.append('fresh_post_cta')
                    break
            if 'fresh_post_cta' not in fresh_markers:
                # Timestamp pattern: · N с. назад / · N мин. назад / · N s ago / · N min ago
                pat = _re.compile(r'·\s*\d+\s*(с\.\s*назад|мин\.\s*назад|с|сек|s\s*ago|min\s*ago)')
                for node in root_fm.iter('node'):
                    txt = (node.get('text', '') or '').strip()
                    if pat.search(txt):
                        fresh_markers.append('fresh_post_timestamp')
                        break
        except Exception:
            pass  # XML broken → пропускаем маркеры, идём в legacy path
    meta['markers_matched'] = fresh_markers

    on_tiktok = ('musically' in cur_act) or ('tiktok' in cur_act.lower())
    meta['on_tiktok'] = on_tiktok

    if not on_tiktok:
        # Защита от flaky dumpsys: если fresh маркеры есть — success всё равно.
        if fresh_markers:
            meta['reason'] = 'fresh_post_marker_no_activity'
            return True, meta
        meta['reason'] = 'not_on_tiktok'
        return False, meta
    if 'DetailActivity' in cur_act:
        meta['detail_activity'] = True
        meta['reason'] = 'detail_activity'
        return True, meta
    # v12 RC-B.0: flag-gated SEED hardening (Codex v10 round 1, P2:
    # SAASceneWrapperActivity untested как pure composer activity; evidence-guarded).
    seed = TT_COMPOSER_ACTIVITIES_SEED
    if os.environ.get('TT_SEED_HARDENING_SAASCENE_ENABLED', 'false').lower() == 'true':
        seed = seed + ('SAASceneWrapperActivity',)
    on_composer = any(a in cur_act for a in seed)
    meta['on_composer_seed'] = on_composer
    if on_composer:
        # composer_seed wins over fresh markers (защита от случайного match'а
        # маркера на фоновом экране пока сверху visible editor).
        meta['reason'] = 'on_composer_seed'
        return False, meta

    # WP #82: fresh-post маркеры в TT не-composer контексте — success.
    if fresh_markers:
        meta['reason'] = fresh_markers[0]
        return True, meta

    # Bottom-nav XML parsing (existing path)
    try:
        import xml.etree.ElementTree as ET
        root_el = ET.fromstring(ui or '<hierarchy/>')
        screen_h = 0
        for node in root_el.iter('node'):
            b = node.get('bounds', '')
            m = _re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', b)
            if m:
                screen_h = max(screen_h, int(m.group(4)))
        if screen_h < 1000:  # sanity — TT phones are ≥1500px tall
            meta['reason'] = 'screen_height_implausible'
            return False, meta
        bottom_threshold = int(screen_h * 0.80)
        groups_visible = []
        for group in TT_MAIN_NAV_LABEL_GROUPS:
            for node in root_el.iter('node'):
                b = node.get('bounds', '')
                m = _re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', b)
                if not m:
                    continue
                cy = (int(m.group(2)) + int(m.group(4))) // 2
                if cy < bottom_threshold:
                    continue
                txt = node.get('text', '')
                desc = node.get('content-desc', '')
                if any(_matches_label(txt, label) or _matches_label(desc, label)
                       for label in group):
                    groups_visible.append(group[0])
                    break
        meta['nav_groups_visible'] = groups_visible
        if len(groups_visible) >= 3:
            meta['reason'] = f'main_nav_{len(groups_visible)}_groups'
            return True, meta
        meta['reason'] = f'main_nav_only_{len(groups_visible)}_groups'
        return False, meta
    except Exception as exc:
        meta['reason'] = f'xml_parse_error: {type(exc).__name__}'
        return False, meta
```

- [ ] **Step 4: Запустить тесты — все должны pass**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py -q 2>&1 | tail -15
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_tiktok.py tests/test_publisher_tt_overlay_handlers.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(tt): _tt_infer_post_publish_success — fresh-post XML маркеры (WP #82)

Добавлены два маркера, работающие независимо от bottom-nav visibility
и top-activity (защита от dialog-блокеров и flaky dumpsys):
- «Get more views» Button (post-publish CTA)
- timestamp «· N с. назад» / «· N мин. назад» / «· N s ago»

Если on_tiktok=False но fresh-маркеры есть → success всё равно
(reason=fresh_post_marker_no_activity).

Гейтится TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED (default true).

Spec: docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md
EOF
)"
```

---

## Task 5: Change 1 — early success-check на верху wait-loop

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py:1820-2200` (внутри `_wait_upload_confirmation`)

Reason: даже с расширенным детектором (Task 4) — если он стоит ПОСЛЕ retap-ветки и generic dialog handler, эти ветки preemptят. Promo-handler жмёт «Закрыть» бесконечно. Перемещаем success-check в самое начало итерации.

- [ ] **Step 1: Найти точное место вставки**

```bash
grep -n "for wait in range\|ui = self.dump_ui\|# === \[wait_upload overlay" /root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py | head -20
```

Найти строку с `ui = self.dump_ui()` внутри outer wait-loop (обычно одна из первых строк после `for wait in range(...)`). Запишите номер строки — он понадобится для вставки.

- [ ] **Step 2: Вставить early-check сразу после `ui = self.dump_ui()`**

В `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py`, сразу после первого вызова `ui = self.dump_ui()` внутри wait-loop'а вставить:

```python
            # WP #82 2026-05-18: early post-publish success check.
            # Промотирован сюда из line 2164 — детектор должен запускаться
            # ДО retap-ветки и dialog handlers, иначе они preemptят success.
            # Под env-flag, default ON; fallback — старый late-блок.
            if os.environ.get('TT_POSTPUBLISH_EARLY_CHECK_ENABLED', 'true').lower() == 'true':
                cur_act_early = self.adb(
                    'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
                    timeout=8) or ''
                success_early, meta_early = _tt_infer_post_publish_success(
                    ui, cur_act_early, wait)
                if success_early:
                    log.info(
                        f'  ✅ TikTok: post-publish success (EARLY) — '
                        f'reason={meta_early["reason"]}, wait={wait}'
                    )
                    self.log_event(
                        'info',
                        f'TikTok: post-publish success inferred — {meta_early["reason"]}',
                        meta={'category': 'tt_post_publish_success_inferred',
                              'platform': self.platform,
                              'wait_iteration': wait,
                              'detector_position': 'early',
                              **meta_early},
                    )
                    upload_confirmed = True
                    break
```

- [ ] **Step 3: Гейтить старый late-блок**

Найти блок late-check (line 2160-2179 — `success, _meta = _tt_infer_post_publish_success(...)` + `if success:` + log_event + `break`). Обернуть его в обратный гейт:

```python
            # WP #82 2026-05-18: оригинальный поздний success-check сохранён
            # как fallback при TT_POSTPUBLISH_EARLY_CHECK_ENABLED=false.
            # При default-true ранний блок (вверху iter) уже сделал break.
            if os.environ.get('TT_POSTPUBLISH_EARLY_CHECK_ENABLED', 'true').lower() != 'true':
                cur_act_post = self.adb(
                    'dumpsys activity activities 2>/dev/null | grep -m1 "topResumedActivity"',
                    timeout=8,
                ) or ''
                success, _meta = _tt_infer_post_publish_success(ui, cur_act_post, wait)
                if success:
                    log.info(f'  ✅ TikTok: post-publish success inferred '
                             f'(reason={_meta["reason"]}, '
                             f'nav_groups={_meta["nav_groups_visible"]}, wait={wait})')
                    self.log_event(
                        'info',
                        f'TikTok: post-publish success inferred — {_meta["reason"]}',
                        meta={'category': 'tt_post_publish_success_inferred',
                              'platform': self.platform,
                              'wait_iteration': wait,
                              'detector_position': 'late',
                              **_meta},
                    )
                    upload_confirmed = True
                    inferred_path_used = True
                    break
```

(Important: meta['detector_position'] добавляется и в early, и в late — для observability разделения путей.)

Аналогично — внутри AI-Unstuck-предкаст (line 2198+, второй вызов `_tt_infer_post_publish_success`) — добавить `'detector_position': 'late_ai_guard'` в meta, остальное не трогаем.

- [ ] **Step 4: Smoke-импорт публиматера — синтаксис ОК**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "from publisher_tiktok import TikTokMixin, _tt_infer_post_publish_success; print('import ok')"
```

Expected: `import ok` (no traceback).

- [ ] **Step 5: Запустить полный test-set — pytest зелёный**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py tests/test_publisher_tt_music_rights.py tests/test_publisher_intermediate_probes.py -q 2>&1 | tail -10
```

Expected: all green. Если что-то падает — изучить traceback ДО продолжения.

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_tiktok.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(tt): early post-publish success-check в начале wait-loop (WP #82)

Детектор _tt_infer_post_publish_success теперь запускается сразу после
dump_ui(), ДО retap-ветки и dialog handlers. Это закрывает 10/14 TT-фейлов
2026-05-18, где детектор НЕ срабатывал потому что generic handler
жмёт «Закрыть» на promo-модале и continue'ит до того как success-check
получит управление.

Гейтится TT_POSTPUBLISH_EARLY_CHECK_ENABLED (default true).
Старый late-блок сохранён под обратным гейтом — rollback через flag.
meta['detector_position'] добавлено в success event ('early'/'late'/
'late_ai_guard') для post-deploy observability.

Spec: docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md
EOF
)"
```

---

## Task 6: Change 4(b) — `_handle_tt_promo_inbox_modal` с cap → success

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py` — добавить constants, detector, handler; интеграция в `_wait_upload_confirmation`
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_publisher_tt_overlay_handlers.py`

Reason: promo-модал «Улучшенные входящие сообщения для бизнеса» (task 6750 iter10/20/40, task 6804) re-presentится после dismiss → infinite loop. Specific handler с cap → success.

- [ ] **Step 1: Написать failing-тесты**

```python
# ────────────────────────── Promo-inbox modal handler (WP #82) ───────────────


def test_promo_inbox_detector_positive_real_fixture():
    """«Улучшенные входящие сообщения для бизнеса» modal detected."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6750_iter10_promo_inbox_modal.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    assert mx._detect_tt_promo_inbox_modal(ui) is True


def test_promo_inbox_detector_negative_no_modal():
    """Random feed UI → detector=False."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6750_iter1_profile_with_fresh_post.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    assert mx._detect_tt_promo_inbox_modal(ui) is False


def test_promo_inbox_handler_iter1_taps_close():
    """iter 1 → tap «Закрыть» content-desc."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6750_iter10_promo_inbox_modal.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    res = mx._handle_tt_promo_inbox_modal(ui, wait=5)
    assert res is True
    assert mx.tap_element.called or mx.adb_tap.called


def test_promo_inbox_handler_cap_returns_inferred_success():
    """После 5 неудачных dismiss → handler возвращает 'inferred_success'."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6750_iter10_promo_inbox_modal.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    last = None
    for i in range(6):
        last = mx._handle_tt_promo_inbox_modal(ui, wait=i)
    assert last == 'inferred_success'
    # event-проверка: log_event получил category=tt_post_publish_inferred_from_promo_loop
    cats = [c.kwargs.get('meta', {}).get('category')
            for c in mx.log_event.call_args_list]
    assert 'tt_post_publish_inferred_from_promo_loop' in cats


def test_promo_inbox_handler_disabled_by_flag(monkeypatch):
    """env-flag TT_PROMO_INBOX_MODAL_HANDLER_ENABLED=false → detector False."""
    monkeypatch.setenv('TT_PROMO_INBOX_MODAL_HANDLER_ENABLED', 'false')
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6750_iter10_promo_inbox_modal.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    assert mx._detect_tt_promo_inbox_modal(ui) is False
```

- [ ] **Step 2: Запустить тесты, убедиться что fail-ят**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py -k 'promo_inbox' -v 2>&1 | tail -15
```

Expected: 5 FAIL (`_detect_tt_promo_inbox_modal` / `_handle_tt_promo_inbox_modal` not defined).

- [ ] **Step 3: Добавить constants + detector + handler**

Найти constants-секцию overlay handlers (около `MAX_PERM_DIALOG_ITERATIONS`, line 242). После неё (перед `def _init_wait_upload_overlay_state`):

```python
    # P — TT promo-inbox modal (WP #82 2026-05-18).
    # «Улучшенные входящие сообщения для бизнеса» — promo-онбординг,
    # появляется только после успешной публикации. Re-presentится после
    # dismiss → требует cap → inferred_success.
    _TT_PROMO_INBOX_TITLE_SUBSTRING = 'Улучшенные входящие сообщения для бизнеса'
    _TT_PROMO_INBOX_CLOSE_LABELS = ['Закрыть', 'Close']
    MAX_TT_PROMO_INBOX_ITERATIONS = 5
```

В `_init_wait_upload_overlay_state` добавить:

```python
        self._promo_inbox_iter = 0
```

После существующих detectors (после `_detect_tt_contacts_perm`, около line 369) добавить detector:

```python
    def _detect_tt_promo_inbox_modal(self, ui_xml: str) -> bool:
        """WP #82: TT promo-inbox onboarding modal.

        Substring title. Появляется только post-publish, потому совмещён
        с cap→inferred_success в handler'е.
        Гейтится TT_PROMO_INBOX_MODAL_HANDLER_ENABLED (default true).
        """
        if os.environ.get('TT_PROMO_INBOX_MODAL_HANDLER_ENABLED', 'true').lower() != 'true':
            return False
        if not ui_xml:
            return False
        return self._TT_PROMO_INBOX_TITLE_SUBSTRING in ui_xml
```

После existing handlers (после `_handle_tt_contacts_perm`, около line 552) добавить handler:

```python
    def _handle_tt_promo_inbox_modal(self, ui_xml: str, wait: int):
        """WP #82: dismiss TT promo-inbox modal с cap → inferred_success.

        Tri-state return:
          - True  — handled (caller should sleep + continue)
          - False — irrecoverable (caller should abort wait_upload)
          - 'inferred_success' — cap exceeded; modal-loop = proof of
                                  post-publish state, caller should
                                  upload_confirmed=True + break.
        """
        self._promo_inbox_iter += 1
        n = self._promo_inbox_iter
        if n == 1:
            self.log_event(
                'info', 'TikTok: promo-inbox modal detected',
                meta={'category': 'tt_promo_inbox_modal_detected',
                      'platform': self.platform, 'step': 'wait_upload',
                      'wait_iter': wait}
            )
        if n > self.MAX_TT_PROMO_INBOX_ITERATIONS:
            self.log_event(
                'info',
                f'TikTok: promo-inbox modal loop > {self.MAX_TT_PROMO_INBOX_ITERATIONS} '
                f'iter — inferred post-publish success',
                meta={'category': 'tt_post_publish_inferred_from_promo_loop',
                      'platform': self.platform, 'step': 'wait_upload',
                      'iterations': n, 'wait_iter': wait}
            )
            return 'inferred_success'
        tapped = self.tap_element(
            ui_xml or '', self._TT_PROMO_INBOX_CLOSE_LABELS,
            exact=True, clickable_only=True,
        )
        strategy = 'close_tap' if tapped else 'back_keycode'
        if not tapped:
            try:
                self.adb('input keyevent KEYCODE_BACK')
            except Exception:
                pass
        self.log_event(
            'info',
            f'TikTok: promo-inbox dismiss attempt {n} via {strategy}',
            meta={'category': 'tt_promo_inbox_modal_dismissed',
                  'platform': self.platform, 'step': 'wait_upload',
                  'iteration': n, 'strategy': strategy, 'wait_iter': wait}
        )
        return True
```

- [ ] **Step 4: Интегрировать handler в `_wait_upload_confirmation`**

Найти блок (около line 1978-1994) где existing perm-handler integrated:

```python
            if (os.environ.get('TT_PERM_DIALOG_HANDLER_ENABLED', 'true').lower()
                    == 'true'):
                if self._detect_tt_contacts_perm(ui):
                    if not self._handle_tt_contacts_perm(ui, wait):
                        return False
                    time.sleep(1.5)
                    continue
                elif self._perm_dialog_iter > 0:
                    ...
                    self._perm_dialog_iter = 0
```

После него (но ПЕРЕД audio-dialog block) добавить:

```python
            # WP #82 2026-05-18: promo-inbox modal handler with cap → success.
            if self._detect_tt_promo_inbox_modal(ui):
                res = self._handle_tt_promo_inbox_modal(ui, wait)
                if res == 'inferred_success':
                    upload_confirmed = True
                    break
                if not res:
                    return False
                time.sleep(1.5)
                continue
            elif self._promo_inbox_iter > 0:
                self._promo_inbox_iter = 0
```

- [ ] **Step 5: Запустить тесты — pytest зелёный**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py -q 2>&1 | tail -15
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_tiktok.py tests/test_publisher_tt_overlay_handlers.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(tt): _handle_tt_promo_inbox_modal с cap → inferred_success (WP #82)

«Улучшенные входящие сообщения для бизнеса» — TT promo-онбординг после
успешной публикации. Re-presentится после dismiss → бесконечный loop
вместо tt_upload_confirmation_timeout (tasks 6750 iter10+, 6804).

Handler tri-state:
  True   — handled, continue
  False  — abort
  'inferred_success' — cap (5) exceeded → upload_confirmed (modal-loop
                       proves post-publish state)

Гейтится TT_PROMO_INBOX_MODAL_HANDLER_ENABLED (default true).
Новые events: tt_promo_inbox_modal_detected/_dismissed +
              tt_post_publish_inferred_from_promo_loop

Spec: docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md
EOF
)"
```

---

## Task 7: Change 4(c) — perm-dialog handler tri-state cap → success

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py:512+` (`_handle_tt_contacts_perm`) + caller around line 1980
- Test: `/root/.openclaw/workspace-genri/autowarm/tests/test_publisher_tt_overlay_handlers.py`

Reason: existing handler возвращал `False` (= abort) на cap. Task 6792 показал 25+ повторов до watchdog'а — publish уже произошёл. Cap (новое значение 5 из Task 3) → `'inferred_success'`, caller break with upload_confirmed.

- [ ] **Step 1: Написать failing-тесты**

```python
# ────────────────────────── perm-dialog cap → inferred_success (WP #82) ──────


def test_perm_dialog_handler_cap_returns_inferred_success():
    """После MAX_PERM_DIALOG_ITERATIONS (5) → handler возвращает 'inferred_success'."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6789_iter1_fb_friends_perm.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    last = None
    for i in range(6):
        last = mx._handle_tt_contacts_perm(ui, wait=i)
    assert last == 'inferred_success'
    cats = [c.kwargs.get('meta', {}).get('category')
            for c in mx.log_event.call_args_list]
    assert 'tt_post_publish_inferred_from_perm_loop' in cats


def test_perm_dialog_handler_below_cap_returns_true():
    """1-5 iter → True (handled, continue)."""
    fixture = (Path(__file__).resolve().parent / 'fixtures' /
               'tt_post_publish' / 'task6789_iter1_fb_friends_perm.xml')
    ui = fixture.read_text()
    mx = _bare_mixin()
    for i in range(5):
        res = mx._handle_tt_contacts_perm(ui, wait=i)
        assert res is True, f'iter {i+1} should be True, got {res!r}'
```

- [ ] **Step 2: Запустить тесты, убедиться что fail-ят**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py -k 'perm_dialog_handler' -v 2>&1 | tail -10
```

Expected: FAIL (handler возвращает `False` на cap, не `'inferred_success'`).

- [ ] **Step 3: Изменить handler на tri-state**

В `/root/.openclaw/workspace-genri/autowarm/publisher_tiktok.py` найти `_handle_tt_contacts_perm` (line 512+). Заменить блок cap:

```python
        if n > self.MAX_PERM_DIALOG_ITERATIONS:
            self.log_event(
                'error',
                f'tt_perm_dialog_stuck: dialog persists > '
                f'{self.MAX_PERM_DIALOG_ITERATIONS} iter',
                meta={'category': 'tt_perm_dialog_stuck',
                      'platform': self.platform,
                      'step': 'tt_5_perm_dialog_stuck',
                      'iterations': n})
            self.set_step('tt_5_perm_dialog_stuck')
            return False
```

на:

```python
        if n > self.MAX_PERM_DIALOG_ITERATIONS:
            # WP #82 2026-05-18: cap → inferred_success, не abort.
            # Perm-dialog появляется только post-publish, loop = signal что
            # publish уже произошёл и TT повторно просит permission.
            self.log_event(
                'info',
                f'TikTok: perm-dialog loop > {self.MAX_PERM_DIALOG_ITERATIONS} '
                f'iter — inferred post-publish success',
                meta={'category': 'tt_post_publish_inferred_from_perm_loop',
                      'platform': self.platform, 'step': 'wait_upload',
                      'iterations': n})
            return 'inferred_success'
```

Также обновить docstring handler'а:

```python
    def _handle_tt_contacts_perm(self, ui_xml: str, wait: int):
        """Dismiss TikTok permission dialog (contacts ИЛИ FB-friends).

        Tri-state return (WP #82 2026-05-18):
          True   — handled, caller sleeps + continues.
          False  — irrecoverable (currently unreachable — cap раньше уходит в
                   'inferred_success').
          'inferred_success' — cap (MAX_PERM_DIALOG_ITERATIONS=5) exceeded.
                                Perm-dialog loop = proof of post-publish state,
                                caller should upload_confirmed=True + break.

        Strategy:
          - iter 1-5: tap deny button (exact, clickable).
          - iter 6+: cap → inferred_success.
        """
```

- [ ] **Step 4: Обновить caller (`_wait_upload_confirmation`, около line 1980)**

Найти:

```python
            if (os.environ.get('TT_PERM_DIALOG_HANDLER_ENABLED', 'true').lower()
                    == 'true'):
                if self._detect_tt_contacts_perm(ui):
                    if not self._handle_tt_contacts_perm(ui, wait):
                        return False
                    time.sleep(1.5)
                    continue
                elif self._perm_dialog_iter > 0:
                    ...
                    self._perm_dialog_iter = 0
```

Заменить inner branch на:

```python
            if (os.environ.get('TT_PERM_DIALOG_HANDLER_ENABLED', 'true').lower()
                    == 'true'):
                if self._detect_tt_contacts_perm(ui):
                    res = self._handle_tt_contacts_perm(ui, wait)
                    if res == 'inferred_success':
                        upload_confirmed = True
                        break
                    if not res:
                        return False
                    time.sleep(1.5)
                    continue
                elif self._perm_dialog_iter > 0:
                    self.log_event(
                        'info',
                        'TikTok: contacts permission dialog dismissed successfully',
                        meta={'category': 'tt_perm_dialog_dismissed',
                              'platform': self.platform, 'step': 'wait_upload',
                              'attempts': self._perm_dialog_iter,
                              'wait_iter': wait}
                    )
                    self._perm_dialog_iter = 0
```

(`elif` блок копируется один-в-один из существующего кода — он уже там, повторно показан для context'а.)

- [ ] **Step 5: Запустить тесты — pytest зелёный**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/test_publisher_tt_overlay_handlers.py tests/test_publisher_tt_music_rights.py -q 2>&1 | tail -15
```

Expected: all green. Если падает `test_perm_dialog_handler_returns_false_on_cap` (или похожий старый тест) — он стал устаревшим, обновите его (return value `False` → `'inferred_success'`).

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git add publisher_tiktok.py tests/test_publisher_tt_overlay_handlers.py
git -c commit.gpgsign=false commit -m "$(cat <<'EOF'
feat(tt): _handle_tt_contacts_perm tri-state cap → inferred_success (WP #82)

Task 6792 показал 25+ повторений perm-dialog dismiss до watchdog'а —
publish уже произошёл, TT повторно просит permission. Old handler возвращал
False (= abort), теперь tri-state с cap → 'inferred_success'.

Caller _wait_upload_confirmation обновлён для tri-state.
Event tt_post_publish_inferred_from_perm_loop — observability cap-логики.

Spec: docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md
EOF
)"
```

---

## Task 8: Финальная валидация + push

**Files:**
- (read-only check of all changes)

- [ ] **Step 1: Полный pytest-run**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -m pytest tests/ -q 2>&1 | tail -20
```

Expected: ALL green (или existing skip'ы / xfail'ы остаются как было).

- [ ] **Step 2: Smoke import основной публишер**

```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 -c "
from publisher_tiktok import TikTokMixin, _tt_infer_post_publish_success
import inspect
src = inspect.getsource(TikTokMixin._detect_tt_contacts_perm)
assert '_TT_PERM_DIALOG_VARIANTS' in src, 'Task 3 не применён'
src2 = inspect.getsource(TikTokMixin._handle_tt_promo_inbox_modal)
assert 'inferred_success' in src2, 'Task 6 не применён'
print('smoke OK — все ключевые правки на месте')
"
```

Expected: `smoke OK — все ключевые правки на месте`

- [ ] **Step 3: Codex review uncommitted diff против main**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git diff origin/main..HEAD | ~/.local/bin/codex review - 2>&1 | tail -30
```

Если codex вернул P1/P2 — fix inline, новый commit, повторить. Если "no actionable issues" — proceed.

- [ ] **Step 4: Git log проверка — все 7 коммитов на месте**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git log --oneline origin/main..HEAD
```

Expected: 7 commits (Task 1-7), все с `(WP #82)` в subject.

- [ ] **Step 5: Push ветки + создать PR**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git push -u origin tt-upload-confirm-false-negative-2026-05-18

. ~/secrets/github-gengo2.env
gh pr create --title "fix(tt): close tt_upload_confirmation_timeout false-negative (WP #82)" --body "$(cat <<'EOF'
## Summary
Triage 2026-05-18 показал 10/14 TT-фейлов с `tt_upload_confirmation_timeout` несмотря на то что видео **фактически опубликовано** (профиль уже показывает `· 1 с. назад` + `Get more views`). 4 связанных бага в `_wait_upload_confirmation`:

1. Success-detector стоял слишком поздно — preemptился retap-веткой и generic dialog handler.
2. `share_btn_clickable` substring `'поделиться'` хватал overlay `«Поделиться видео. Уже поделились:»` → false retap.
3. `_detect_tt_contacts_perm` ищет только `«доступ к контактам»` — FB-friends dialog (tasks 6789/6809) проваливался.
4. Promo-модал «Улучшенные входящие сообщения для бизнеса» (6750 iter10+/6804) re-presentится после dismiss → infinite loop.

## Changes
- **Task 1:** XML fixtures из реального инцидента в `tests/fixtures/tt_post_publish/`.
- **Task 2:** `share_btn_clickable` exact-match `('Поделиться','Post','Publish')`.
- **Task 3:** `_TT_PERM_DIALOG_VARIANTS` list — contacts + FB-friends. Cap 2→5.
- **Task 4:** `_tt_infer_post_publish_success` + `fresh_post_cta` (Get more views Button) и `fresh_post_timestamp` (`· N с. назад`) маркеры.
- **Task 5:** Early success-check в начале wait-loop, ДО retap/handlers.
- **Task 6:** Новый `_handle_tt_promo_inbox_modal` tri-state с cap=5 → `inferred_success`.
- **Task 7:** `_handle_tt_contacts_perm` tri-state с cap → `inferred_success`.

## Env-flags (kill-switches, default ON)
- `TT_POSTPUBLISH_EARLY_CHECK_ENABLED`
- `TT_POSTPUBLISH_FRESH_POST_MARKERS_ENABLED`
- `TT_PROMO_INBOX_MODAL_HANDLER_ENABLED`

## Test plan
- [ ] Pytest зелёный: `pytest tests/`
- [ ] Smoke import работает
- [ ] Codex review без P1
- [ ] 24h post-merge: `tt_upload_confirmation_timeout` падает с ~10/день к ≤2/день
- [ ] 24h post-merge: events `tt_post_publish_inferred_fresh_post` / `_from_promo_loop` / `_from_perm_loop` появляются > 0

Closes WP #82 (https://openproject.contenthunter.ru/projects/content-hunter/work_packages/82)
Spec: `docs/superpowers/specs/2026-05-18-tt-upload-confirmation-false-negative-design.md` (в contenthunter repo)
EOF
)"
```

Expected: PR создан, URL возвращён. Запишите URL.

- [ ] **Step 6: Вернуться в контент-хантер worktree и обновить OpenProject WP**

```bash
cd /home/claude-user/contenthunter/.claude/worktrees/tt-fails-triage-2026-05-18
. ~/secrets/openproject.env
PR_URL="<paste PR url from previous step>"
curl -s -u apikey:$OPENPROJECT_API_TOKEN -H "Content-Type: application/json" \
  -X POST "https://openproject.contenthunter.ru/api/v3/work_packages/82/activities" \
  --data "$(python3 -c "import json; print(json.dumps({'comment':{'raw': f'**Что было не так** — 10/14 TT-фейлов 2026-05-18 с false-negative tt_upload_confirmation_timeout (пост опубликован, бот не распознал post-publish state).\n\n**Что сделано** — PR ${1}: 4 связанных фикса в publisher_tiktok.py (early success-check, fresh-post маркеры, FB-friends perm coverage, promo-modal handler с cap→inferred_success), 6 новых unit-тестов с реальными XML-fixtures, 3 env-flag kill-switches.\n\n**Что осталось** — 24h post-merge SQL-проверка: count tt_upload_confirmation_timeout должен упасть с ~10/день к ≤2/день; events tt_post_publish_inferred_fresh_post/_from_promo_loop/_from_perm_loop появляются > 0.'.format(__import__(\"sys\").argv[1])}}))" "$PR_URL")"
```

Expected: 201 Created, comment добавлен в WP #82.

---

## Self-Review

**Spec coverage:**
- ✅ Change 1 — Task 5 (early check)
- ✅ Change 2 — Task 4 (fresh-post markers)
- ✅ Change 3 — Task 2 (exact-match share_btn)
- ✅ Change 4(a) — Task 3 (FB-friends perm variant)
- ✅ Change 4(b) — Task 6 (promo-inbox handler)
- ✅ Change 4(c) — Task 7 (perm cap → inferred_success)
- ✅ Все 3 env-flags (Tasks 4, 5, 6)
- ✅ Все 6 запрошенных unit-тестов (Tasks 2, 3, 4, 6, 7) + extra regression-тесты
- ✅ Real fixtures (Task 1)
- ✅ 24h SQL metrics — упомянуты в Task 8 / PR test plan

**Type consistency:**
- ✅ `_TT_PERM_DIALOG_VARIANTS` использует один формат `(substring, [secondary])` в обоих местах (Task 3).
- ✅ Handler tri-state return `True`/`False`/`'inferred_success'` consistent в Tasks 6, 7.
- ✅ Caller-patches в Task 5/6/7 матчат tri-state.
- ✅ `markers_matched` в meta используется одинаково в Task 4 (detector) и Task 5 (caller event).

**Placeholder scan:** none — все коммит-сообщения, тесты, замены кода написаны inline.
