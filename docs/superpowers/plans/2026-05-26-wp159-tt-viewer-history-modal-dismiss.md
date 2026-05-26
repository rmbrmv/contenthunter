# WP #159 — TT viewer-history modal dismiss — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Авто-закрывать TikTok-шторку «История просмотров» на профиль-табе, чтобы свитч аккаунта не падал `tt_profile_tab_broken`.

**Architecture:** Добавить одну запись `('История просмотров', 'Сохранить')` в существующий вайтлист `_TT_PROFILE_PROMO_DISMISSIBLE_MODALS`. Отлаженный механизм WP #106 (детектор `_tt_try_dismiss_profile_promo` + метод `_tt_dismiss_profile_promo_dialog` + интеграция в retap-петлю `_switch_tiktok`) сам закроет шторку тапом по тексту кнопки. Новой логики/error_code/схемы нет; kill-switch `TT_PROFILE_PROMO_DISMISS_DISABLED` уже покрывает запись.

**Tech Stack:** Python 3, pytest, unittest.mock; репозиторий `GenGo2/delivery-contenthunter` (autowarm), файл `account_switcher.py`.

**Spec:** `docs/superpowers/specs/2026-05-26-wp159-tt-viewer-history-modal-dismiss-design.md`

---

## Setup (перед Task 1)

Реализация идёт в **autowarm-репо** (`GenGo2/delivery-contenthunter`), НЕ в docs-репо.
Прод-чекаут: `/root/.openclaw/workspace-genri/autowarm/` (на `main`, активный, auto-push hook).

Создать изолированный git worktree, чтобы не трогать прод main во время разработки
(параллельные сессии). Из прод-чекаута:

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin --quiet
git worktree add -b wp159-tt-viewer-history ../autowarm-wp159 origin/main
cd ../autowarm-wp159
```

Все пути в задачах ниже — относительно корня этого worktree.

**Заземление (уже проверено при планировании, можно перепровериить):** на дампе task 9648
`parse_ui_dump` читает лейблы `'История просмотров включена'`, `'История просмотров'`,
clickable `'Сохранить'`; детектор с новой записью даёт MATCH, без неё — `None`;
`_tt_dismiss_security_prompt` и `_tt_is_own_profile` на этом дампе → `False`.

---

## Task 1: Фикстур + запись вайтлиста (unit-уровень: детектор + метод)

**Files:**
- Create: `tests/fixtures/tt_profile_promo_viewer_history_9648.xml`
- Modify: `account_switcher.py` (вайтлист `_TT_PROFILE_PROMO_DISMISSIBLE_MODALS`, ~строки 370–374)
- Test: `tests/test_account_switcher_profile_promo_dismiss.py`

- [ ] **Step 1: Сохранить реальный дамп task 9648 как фикстур**

Публичный URL дампа (профиль-таб с модалкой):

```bash
curl -s -o tests/fixtures/tt_profile_promo_viewer_history_9648.xml \
  "https://save.gengo.io/autowarm/ui_dumps/tiktok/task9648_switch_9648_tt_2_profile_tab_1779701395.xml"
# Проверка: ~13.8KB, содержит «История просмотров» и кнопку «Сохранить»
grep -c "История просмотров" tests/fixtures/tt_profile_promo_viewer_history_9648.xml   # ожидаем >=2
grep -c "Сохранить" tests/fixtures/tt_profile_promo_viewer_history_9648.xml            # ожидаем >=1
```

Fallback, если URL недоступен — локальная копия: `/tmp/d9648_profile.xml`.

- [ ] **Step 2: Написать падающие unit-тесты + ассерт seed**

В `tests/test_account_switcher_profile_promo_dismiss.py` добавить детекторный тест
(после `test_match_fb_friends_promo_7870`):

```python
def test_match_viewer_history_promo_9648():
    """task 9648 dump → ('История просмотров', 'Сохранить')."""
    xml = _read_fixture('tt_profile_promo_viewer_history_9648.xml')
    result = _tt_try_dismiss_profile_promo(xml)
    assert result is not None
    title, button = result
    assert title == 'История просмотров'
    assert button == 'Сохранить'
```

Расширить seed-тест `test_whitelist_seeded_with_two_entries` (добавить строку, имя
теста не менять):

```python
    assert any('История просмотров' in t for t in titles)
```

Добавить метод-unit тест (после `test_method_match_emits_event_and_taps`):

```python
def test_method_match_viewer_history_emits_event_and_taps():
    """Match viewer-history promo → _attempted event + tap_element(['Сохранить']) → True."""
    sw = _make_switcher()
    xml = _read_fixture('tt_profile_promo_viewer_history_9648.xml')

    result = sw._tt_dismiss_profile_promo_dialog(xml, retap=0)

    assert result is True
    attempted = _events_with_name(sw, 'tt_profile_promo_dismiss_attempted')
    assert len(attempted) == 1
    meta = attempted[0].kwargs['meta']
    assert meta['title_substr'] == 'История просмотров'
    assert meta['button_text'] == 'Сохранить'
    assert meta['platform'] == 'TikTok'
    sw.p.tap_element.assert_called_once()
    call_args = sw.p.tap_element.call_args
    assert call_args.args[0] == xml
    assert call_args.args[1] == ['Сохранить']
    assert call_args.kwargs.get('clickable_only') is True
```

- [ ] **Step 3: Прогнать — убедиться, что падают**

Run:
```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py -k "viewer_history or seeded" -v
```
Expected: `test_match_viewer_history_promo_9648` и `test_method_match_viewer_history_emits_event_and_taps` — **FAIL** (детектор возвращает `None`, метод → `False`); `test_whitelist_seeded_with_two_entries` — **FAIL** на новом ассерте.

- [ ] **Step 4: Добавить запись в вайтлист**

В `account_switcher.py`, в кортеж `_TT_PROFILE_PROMO_DISMISSIBLE_MODALS` (после записи
FB-friends), добавить:

```python
    ('Разрешить TikTok доступ к списку ваших друзей', 'Не разрешать'),
    ('История просмотров', 'Сохранить'),  # [WP #159] task 9648 — viewer-history consent (единственная кнопка = «Сохранить», тоггл ВКЛ по умолчанию)
)
```

(Первые две строки — контекст для точного якоря; добавляется только строка с
`'История просмотров'`.)

- [ ] **Step 5: Прогнать — убедиться, что проходят**

Run:
```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py -k "viewer_history or seeded" -v
```
Expected: все три — **PASS**.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/tt_profile_promo_viewer_history_9648.xml \
        tests/test_account_switcher_profile_promo_dismiss.py \
        account_switcher.py
git commit -m "feat(wp159): авто-закрытие TT-модалки «История просмотров» на профиль-табе

Добавлена запись ('История просмотров','Сохранить') в вайтлист
_TT_PROFILE_PROMO_DISMISSIBLE_MODALS. Тап по тексту кнопки, device-agnostic;
детектор/метод/kill-switch переиспользованы (паттерн WP #106). Фикстур — реальный
дамп task 9648 (komilfo_vibe).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Интеграционный тест через retap-петлю `_switch_tiktok`

**Files:**
- Test: `tests/test_account_switcher_profile_promo_dismiss.py`

- [ ] **Step 1: Написать интеграционный тест**

Добавить после `test_all_3_retaps_promo_persists_then_fail` (использует существующие
хелперы `_make_switcher_for_switch_test`, `_read_fixture`, `_events_with_name`):

```python
def test_retap1_viewer_history_dismissed_then_own_profile(monkeypatch):
    """retap1 = viewer-history шторка → dismiss → re-dump = own_profile → break (success)."""
    sw = _make_switcher_for_switch_test()
    xml_promo = _read_fixture('tt_profile_promo_viewer_history_9648.xml')
    xml_own = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="" clickable="false" bounds="[0,100][1080,200]" content-desc="Меню профиля" />
  <node text="Создать историю" clickable="true" bounds="[0,300][200,400]" content-desc="" />
  <node text="Редактировать профиль" clickable="true" bounds="[200,400][800,500]" content-desc="" />
</hierarchy>'''

    monkeypatch.setattr(sw, '_ensure_app_foregrounded', MagicMock(return_value=True))
    monkeypatch.setattr(sw, '_ensure_foreground', MagicMock(return_value=True))
    monkeypatch.setattr(sw, '_go_to_profile_tab', MagicMock())
    monkeypatch.setattr(sw, '_tap_plus_and_verify',
                        MagicMock(return_value=MagicMock(success=True)))
    monkeypatch.setattr(sw, '_read_screen_hybrid',
                        MagicMock(return_value=([], 'empty', None)))
    monkeypatch.setattr(sw, '_single_account_mode', True)

    # 1st dump = retap0 probe (viewer-history); 2nd = после dismiss (own_profile).
    sw.p.dump_ui.side_effect = [xml_promo, xml_own]

    cfg = {
        'package': 'com.zhiliaoapp.musically',
        'launch_activity': 'com.zhiliaoapp.musically/.MainActivity',
        'editor_triggers': ['Опубликовать'],
        'profile_title_header_y_range': (0, 700),
    }
    sw._switch_tiktok(target='clickpay_app', cfg=cfg)

    attempted = _events_with_name(sw, 'tt_profile_promo_dismiss_attempted')
    assert len(attempted) == 1
    assert attempted[0].kwargs['meta']['retap'] == 1
    assert attempted[0].kwargs['meta']['title_substr'] == 'История просмотров'
    sw._fail.assert_not_called()
    sw._tap_plus_and_verify.assert_called_once()
```

- [ ] **Step 2: Прогнать новый тест**

Run:
```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py::test_retap1_viewer_history_dismissed_then_own_profile -v
```
Expected: **PASS** (запись вайтлиста из Task 1 уже есть; шторка детектится → dismiss →
re-dump = own_profile → `break`).

- [ ] **Step 3: Прогнать весь тест-файл**

Run:
```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py -v
```
Expected: все тесты **PASS** (старые 14 + новые: детектор, метод, seed-ассерт, интеграция).

- [ ] **Step 4: Commit**

```bash
git add tests/test_account_switcher_profile_promo_dismiss.py
git commit -m "test(wp159): интеграционный тест retap1 viewer-history → dismiss → own_profile

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Регресс, codex review, мердж, деплой и трекинг

**Files:** нет правок кода (если codex не потребует).

- [ ] **Step 1: Регресс-прогон смежных тестов**

Run (как в WP #131 — проверить, что соседние switcher-тесты целы):
```bash
pytest tests/test_account_switcher_profile_promo_dismiss.py \
       tests/test_yt_premium_promo_dismiss.py -v
```
Expected: всё зелёное, регрессий нет.

- [ ] **Step 2: codex review на дифф**

Run (stdin-обход sandbox-warning, см. практику проекта):
```bash
git diff origin/main..HEAD | ~/.local/bin/codex review -
```
Expected: 0 P1. Если есть P1 — применить фидбэк, перекоммитить, повторить до 0 P1
(false-positive — задокументировать причину отклонения).

- [ ] **Step 3: Мердж в autowarm main + пуш (деплой)**

> ⚠️ Перед мерджем убедиться, что прод-чекаут `/root/.openclaw/workspace-genri/autowarm`
> на ветке `main` (не на чужой ветке — риск ошибочного push, инцидент 2026-05-08).
> НЕ использовать `--force`/`--force-with-lease`.

```bash
cd /root/.openclaw/workspace-genri/autowarm
git branch --show-current   # должно быть main; если нет — git checkout main
git merge --no-ff wp159-tt-viewer-history -m "Merge wp159: авто-закрытие TT-модалки «История просмотров» (WP #159)"
git push origin main
```

Деплой: Python спавнится per-task → **PM2 restart не требуется** (как в WP #131).
Auto-push hook доставит в прод. Очистить worktree:
```bash
git worktree remove ../autowarm-wp159
git branch -d wp159-tt-viewer-history
```

- [ ] **Step 4: OpenProject WP #159 → «Тестирование» + комментарий**

Статус id=9 («Тестирование»). Сначала прочитать `lockVersion`:
```bash
set -a; . ~/secrets/openproject.env; set +a
LV=$(curl -s -u apikey:$OPENPROJECT_API_TOKEN \
  "https://openproject.contenthunter.ru/api/v3/work_packages/159" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['lockVersion'])")
curl -s -u apikey:$OPENPROJECT_API_TOKEN -X PATCH \
  -H "Content-Type: application/json" \
  "https://openproject.contenthunter.ru/api/v3/work_packages/159" \
  -d "{\"lockVersion\":$LV,\"_links\":{\"status\":{\"href\":\"/api/v3/statuses/9\"}}}" >/dev/null
```
Комментарий в house-стиле (Что было не так → Что сделано → Что осталось, без жаргона,
без футера) через `POST /api/v3/work_packages/159/activities`.

- [ ] **Step 5: Docs-evidence + спек/план в docs-репо**

В docs-репо (`rmbrmv/contenthunter`, worktree `wp159-tt-viewer-history-spec`) спек и план
уже закоммичены. Добавить evidence-файл
`docs/evidence/2026-05-26-wp159-tt-viewer-history-shipped.md` (дифф, тесты, codex,
merge-хэш, ссылка на дамп 9648), закоммитить, мерджнуть docs-ветку в docs main
(проверив `git branch` перед коммитом — инцидент 2026-05-26).

- [ ] **Step 6: Обновить память**

Создать topic-файл `project_wp159_tt_viewer_history_modal.md` + строку в `MEMORY.md`.
Линк на `[[project_wp131_tt_profile_tab_stale_ui]]` (родитель) и
`[[project_tt_profile_promo_dismiss_shipped]]` (паттерн WP #106).

- [ ] **Step 7: Verify (после деплоя, ~24ч)**

- Новые события `tt_profile_promo_dismiss_attempted` с `title_substr='История просмотров'`
  → закрытие срабатывает в проде.
- viewer-history-bucket уходит из `tt_profile_tab_broken`.
- При подтверждении WP #159 → «Готово». Откат при регрессии:
  `TT_PROFILE_PROMO_DISMISS_DISABLED=1`.

---

## Self-Review (выполнено при написании)

- **Spec coverage:** вайтлист-запись (Task 1 Step 4), тап «Сохранить» (Task 1 — метод-тест
  проверяет `tap_element(['Сохранить'])`), фикстур из дампа 9648 (Task 1 Step 1), unit
  детектор/метод (Task 1), seed-ассерт (Task 1), интеграция (Task 2), регресс+codex
  (Task 3 Step 1–2), kill-switch — без изменений (покрыт существующим
  `test_method_kill_switch_disabled`), деплой/verify (Task 3). Все разделы спека покрыты.
- **Placeholder scan:** плейсхолдеров нет; весь код тестов и diff-якоря приведены целиком.
- **Type consistency:** имена `_TT_PROFILE_PROMO_DISMISSIBLE_MODALS`,
  `_tt_try_dismiss_profile_promo`, `_tt_dismiss_profile_promo_dialog`,
  `tt_profile_promo_dismiss_attempted`, хелперы `_read_fixture`/`_make_switcher`/
  `_events_with_name`/`_make_switcher_for_switch_test` — сверены с существующим
  `account_switcher.py` и тест-файлом.
