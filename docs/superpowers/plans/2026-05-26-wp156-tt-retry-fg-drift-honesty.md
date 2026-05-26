# WP #156 — TT retry tt_3_open_list honest fg-drift code: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** На retry-ветке TikTok-свитчера (`tt_3_open_list_retry_{attempt}`) при потере переднего плана эмитить честный `tt_fg_drift_unrecoverable` вместо `publish_failed_generic`.

**Architecture:** Реактивная проверка foreground в двух существующих `_fail`-сайтах retry-ветки метода `_switch_tiktok`, через новый helper `_tt_retry_fg_drift_or_none`. Helper зеркалит честный эмит первичного пути (WP #130): `foreground_pkg` + `probe_top_labels` в meta, `final_step='tt_fg_drift_unrecoverable'`. Гейт — существующий kill-switch `TT_SWITCH_FG_GUARD_ENABLED`. Без нового recovery (только honesty). Happy-path не трогается — helper вызывается лишь в уже-падающих ветках.

**Tech Stack:** Python 3, pytest, `unittest.mock.MagicMock`. Репозиторий `GenGo2/delivery-contenthunter` (autowarm), файл `account_switcher.py`. Спека: `docs/superpowers/specs/2026-05-26-wp156-tt-retry-fg-drift-honesty-design.md`.

---

## Контекст для исполнителя

- **Где живёт код:** прод-путь `/root/.openclaw/workspace-genri/autowarm/` = репозиторий `GenGo2/delivery-contenthunter`. PM2 запускает живой код из этого working-tree — **НЕ чекаутить feature-ветку прямо здесь** (подменит прод). Работать в git-worktree.
- **Деплой:** правка одного python-файла подхватывается per-task spawn'ом без `pm2 restart` (как WP #112/#130/#106). После merge — `git pull` на `main` в прод-дире.
- **Имена методов fake-proxy:** сверять 1-в-1 с `DevicePublisher` (риск mock-proxy drift). В тестах используется `MagicMock`-публишер из образца WP #130 (`tests/test_account_switcher_tt_switch_fg_guard.py`).

---

## File Structure

- **Modify:** `account_switcher.py`
  - Вставить helper `_tt_retry_fg_drift_or_none` между `_tt_guard_switcher_foreground` (заканчивается ~строка 2711, `return 'recovered'`) и `def _switch_tiktok` (~строка 2713).
  - Заменить два `_fail`-сайта retry-ветки в `_switch_tiktok` (~строки 3152-3159 и 3166-3170).
- **Create:** `tests/test_account_switcher_tt_retry_fg_drift.py` — unit + integration на новую инструментовку.

---

## Task 0: Worktree setup

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees, чтобы создать изолированный worktree autowarm-репозитория для ветки `wp156-tt-retry-fg-drift-honesty`.

- [ ] **Step 1: Создать worktree из autowarm-репозитория**

```bash
cd /root/.openclaw/workspace-genri/autowarm
git fetch origin -q
git worktree add -b wp156-tt-retry-fg-drift-honesty /tmp/wp156-autowarm origin/main
cd /tmp/wp156-autowarm
git branch --show-current   # → wp156-tt-retry-fg-drift-honesty
```

Expected: новый worktree в `/tmp/wp156-autowarm` на ветке `wp156-tt-retry-fg-drift-honesty`. Все дальнейшие пути в плане — относительно корня worktree.

- [ ] **Step 2: Smoke — тесты на месте и зелёные до правок**

Run: `cd /tmp/wp156-autowarm && python -m pytest tests/test_account_switcher_tt_switch_fg_guard.py -q`
Expected: PASS (образец WP #130 проходит — fake-proxy и импорты валидны).

---

## Task 1: Helper `_tt_retry_fg_drift_or_none` (TDD)

**Files:**
- Create: `tests/test_account_switcher_tt_retry_fg_drift.py`
- Modify: `account_switcher.py` (вставка helper перед `def _switch_tiktok`)

- [ ] **Step 1: Написать падающие unit-тесты на helper**

Создать `tests/test_account_switcher_tt_retry_fg_drift.py`:

```python
"""WP #156 — TikTok retry-ветка tt_3_open_list: честный tt_fg_drift_unrecoverable.

Корень: на ретрае (_switch_tiktok, ветка tt_3_open_list_retry_{attempt}) панель
аккаунтов открывается прямым тапом _tap_profile_header, минуя первичный fg-guard
WP #130. При потере переднего плана два _fail-сайта возвращают generic
publish_failed_generic вместо честного tt_fg_drift_unrecoverable.

Фикс (observability-only, без recovery): helper _tt_retry_fg_drift_or_none
проверяет foreground в точках падения и эмитит честный код. Гейт —
TT_SWITCH_FG_GUARD_ENABLED. Зеркало честного эмита первичного пути (WP #130).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import account_switcher as _asw  # noqa: E402
from account_switcher import AccountSwitcher, UI_CONSTANTS  # noqa: E402

import pytest  # noqa: E402

TT_PKG = 'com.zhiliaoapp.musically'
IG_PKG = 'com.instagram.android'
LAUNCHER_PKG = 'com.sec.android.app.launcher'


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(_asw.time, 'sleep', lambda *_a, **_kw: None)


def _make_switcher():
    publisher = MagicMock()
    publisher.platform = 'TikTok'
    publisher.adb = MagicMock(return_value='')
    publisher.dump_ui = MagicMock(return_value='')
    log_calls: list[dict] = []

    def _capture_log(event_type, message, meta=None):
        log_calls.append({'event_type': event_type, 'message': message,
                          'meta': meta or {}})

    publisher.log_event.side_effect = _capture_log
    publisher.set_step = MagicMock()
    publisher.ensure_unlocked = MagicMock()
    publisher.adb_tap = MagicMock()
    publisher.tap_element = MagicMock(return_value=False)

    sw = AccountSwitcher(publisher)
    sw._save_dump = MagicMock(return_value=None)
    sw._maybe_screenshot = MagicMock()
    sw._single_account_mode = False
    return sw, log_calls


def _error_events(log_calls):
    return [c for c in log_calls if c['event_type'] == 'error']


def _has_category(log_calls, category):
    return any(c['meta'].get('category') == category for c in log_calls)


CFG = UI_CONSTANTS['TikTok']  # cfg['package'] == TT_PKG


# ─── helper: _tt_retry_fg_drift_or_none ─────────────────────────────────────

def test_retry_helper_emits_honest_code_on_foreign_foreground(monkeypatch):
    monkeypatch.delenv('TT_SWITCH_FG_GUARD_ENABLED', raising=False)  # default ON
    sw, log_calls = _make_switcher()
    sw._detect_foreground_pkg = MagicMock(return_value=IG_PKG)

    result = sw._tt_retry_fg_drift_or_none(
        'axilor_woman', CFG, 'tt_3_open_list_retry_1')

    assert result is not None
    assert result.success is False
    assert result.final_step == 'tt_fg_drift_unrecoverable', result.final_step
    errs = _error_events(log_calls)
    assert _has_category(log_calls, 'tt_fg_drift_unrecoverable'), \
        f'expected honest code, got: {[e["meta"] for e in errs]}'
    meta = next(e['meta'] for e in errs
                if e['meta'].get('category') == 'tt_fg_drift_unrecoverable')
    assert meta['foreground_pkg'] == IG_PKG
    assert meta['step'] == 'tt_3_open_list_retry_1'   # retry step сохранён для триажа
    assert meta['platform'] == 'TikTok'
    assert 'probe_top_labels' in meta


def test_retry_helper_returns_none_when_killswitch_off(monkeypatch):
    monkeypatch.setenv('TT_SWITCH_FG_GUARD_ENABLED', '0')
    sw, log_calls = _make_switcher()
    sw._detect_foreground_pkg = MagicMock(return_value=IG_PKG)

    result = sw._tt_retry_fg_drift_or_none(
        'axilor_woman', CFG, 'tt_3_open_list_retry_1')

    assert result is None
    sw._detect_foreground_pkg.assert_not_called()
    assert not _has_category(log_calls, 'tt_fg_drift_unrecoverable')


def test_retry_helper_returns_none_when_foreground_is_tiktok(monkeypatch):
    monkeypatch.delenv('TT_SWITCH_FG_GUARD_ENABLED', raising=False)
    sw, log_calls = _make_switcher()
    sw._detect_foreground_pkg = MagicMock(return_value=TT_PKG)

    result = sw._tt_retry_fg_drift_or_none(
        'axilor_woman', CFG, 'tt_3_open_list_retry_1')

    assert result is None
    assert not _has_category(log_calls, 'tt_fg_drift_unrecoverable')


def test_retry_helper_returns_none_when_foreground_undetermined(monkeypatch):
    monkeypatch.delenv('TT_SWITCH_FG_GUARD_ENABLED', raising=False)
    sw, _log = _make_switcher()
    sw._detect_foreground_pkg = MagicMock(return_value='')

    assert sw._tt_retry_fg_drift_or_none(
        'axilor_woman', CFG, 'tt_3_open_list_retry_1') is None
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают (helper не существует)**

Run: `cd /tmp/wp156-autowarm && python -m pytest tests/test_account_switcher_tt_retry_fg_drift.py -q`
Expected: FAIL — `AttributeError: 'AccountSwitcher' object has no attribute '_tt_retry_fg_drift_or_none'`.

- [ ] **Step 3: Реализовать helper**

В `account_switcher.py` вставить метод **сразу после** `_tt_guard_switcher_foreground` (заканчивается строкой `        return 'recovered'`) и **перед** `def _switch_tiktok(self, target: str, cfg: dict) -> SwitchResult:`:

```python
    def _tt_retry_fg_drift_or_none(self, target: str, cfg: dict, step: str,
                                   probe_elements: list = None):
        """[WP #156] На retry-ветке tt_3_open_list: если foreground ушёл с TikTok —
        эмитим честный tt_fg_drift_unrecoverable вместо generic publish_failed_generic
        и возвращаем SwitchResult (caller обязан его вернуть). Иначе None.

        Observability-only, БЕЗ recovery (восстановление при drift на ретрае —
        отдельный вопрос, см. WP #156). Зеркало честного эмита первичного пути
        (_tt_guard_switcher_foreground / _open_tt_account_switcher, WP #130).
        Гейт — TT_SWITCH_FG_GUARD_ENABLED. `meta['step']` хранит retry-шаг (для
        триажа), а _fail's final_step='tt_fg_drift_unrecoverable' даёт честную
        категорию через _SWITCHER_STEP_TO_CATEGORY.
        """
        if not _tt_switch_fg_guard_enabled():
            return None
        fg_pkg = self._detect_foreground_pkg()
        if not fg_pkg or fg_pkg == cfg['package']:
            return None
        self.p.log_event(
            'error',
            f'tt_fg_drift_unrecoverable (retry): foreground={fg_pkg!r} на {step}',
            meta={'category': 'tt_fg_drift_unrecoverable',
                  'reason': 'tt_account_switcher_wrong_foreground',
                  'foreground_pkg': fg_pkg,
                  'target': target,
                  'step': step,
                  'platform': 'TikTok',
                  'probe_top_labels': _top_labels(probe_elements or [], 30)},
        )
        return self._fail(
            'TikTok не на переднем плане на retry-ветке открытия панели аккаунтов '
            '(foreground drift)',
            step='tt_fg_drift_unrecoverable',
        )
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd /tmp/wp156-autowarm && python -m pytest tests/test_account_switcher_tt_retry_fg_drift.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd /tmp/wp156-autowarm
git add account_switcher.py tests/test_account_switcher_tt_retry_fg_drift.py
git commit -m "feat(wp156): helper _tt_retry_fg_drift_or_none — честный fg-drift код на retry

Зеркало честного эмита первичного пути (WP #130) для retry-ветки
tt_3_open_list: foreground != TikTok → tt_fg_drift_unrecoverable вместо
generic. Observability-only, под TT_SWITCH_FG_GUARD_ENABLED.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire helper в два `_fail`-сайта retry-ветки (TDD)

**Files:**
- Modify: `account_switcher.py` (метод `_switch_tiktok`, ~строки 3152-3159 и 3166-3170)
- Modify: `tests/test_account_switcher_tt_retry_fg_drift.py` (добавить integration-тест)

- [ ] **Step 1: Написать падающий integration-тест на retry-сайт (bottomsheet not opened)**

Дописать в `tests/test_account_switcher_tt_retry_fg_drift.py`:

```python
# ─── integration: retry bottomsheet-сайт эмитит честный код ─────────────────

def test_switch_tiktok_retry_bottomsheet_emits_honest_fg_drift(monkeypatch):
    """attempt 0 mismatch → retry attempt 1: _tap_profile_header ок, но bottomsheet
    не открылся (anchor пуст) И foreground ушёл в Instagram → честный
    tt_fg_drift_unrecoverable, НЕ generic. Доказывает проводку helper'а в сайт."""
    monkeypatch.delenv('TT_SWITCH_FG_GUARD_ENABLED', raising=False)  # default ON
    # module-level helpers, вызываемые в retry-ветке как bare names
    monkeypatch.setattr(_asw, 'parse_ui_dump', lambda xml: [])
    monkeypatch.setattr(_asw, 'find_anchor_bounds', lambda elements, anchors: None)

    sw, log_calls = _make_switcher()
    # шаги 0-2 (foreground + profile-tab + retap-loop) — как в образце WP #130
    sw._ensure_app_foregrounded = MagicMock(return_value=True)
    sw._ensure_foreground = MagicMock(return_value=True)
    sw._go_to_profile_tab = MagicMock()
    sw._tt_dismiss_security_prompt = MagicMock(return_value=False)
    sw._tt_dismiss_profile_promo_dialog = MagicMock(return_value=False)
    sw._tt_is_own_profile = MagicMock(return_value=True)
    sw._read_screen_hybrid = MagicMock(return_value=([], 'vision', None))
    sw._vision_read_current_account = MagicMock(return_value=None)
    # первичный fg-guard проходит ('ok'); первичный open панели успешен
    sw._tt_guard_switcher_foreground = MagicMock(return_value='ok')
    sw._open_tt_account_switcher = MagicMock(return_value=((540, 900), None))
    sw._find_and_tap_account = MagicMock(return_value=True)
    sw._tt_early_banner_confirm = MagicMock(return_value=False)
    sw._maybe_handle_switch_blocking_modal = MagicMock(return_value=None)
    # attempt 0 verify → mismatch (не match/unknown) → цикл уходит на attempt 1
    sw._tt_post_switch_confirm = MagicMock(return_value=('mismatch', 'other_acct'))
    # retry attempt 1 навигация
    sw._force_clean_restart_via_recents = MagicMock(return_value=True)
    sw._open_app = MagicMock(return_value=True)
    sw._tap_profile_header = MagicMock(return_value=True)  # тап ок → доходим до bottomsheet-сайта
    # foreground ушёл в Instagram именно на retry-сайте
    sw._detect_foreground_pkg = MagicMock(return_value=IG_PKG)
    sw.p.dump_ui = MagicMock(
        return_value='<hierarchy rotation="0"><node text="x"/></hierarchy>')

    result = sw._switch_tiktok('axilor_woman', CFG)

    assert not result.success
    assert result.final_step == 'tt_fg_drift_unrecoverable', result.final_step
    assert _has_category(log_calls, 'tt_fg_drift_unrecoverable'), \
        f'expected honest code on retry, got: {[e["meta"] for e in _error_events(log_calls)]}'
    # на retry-сайте честный код несёт retry-шаг в meta
    meta = next(e['meta'] for e in _error_events(log_calls)
                if e['meta'].get('category') == 'tt_fg_drift_unrecoverable')
    assert meta['step'] == 'tt_3_open_list_retry_1', meta['step']
```

- [ ] **Step 2: Запустить — убедиться, что падает (сайт ещё возвращает generic)**

Run: `cd /tmp/wp156-autowarm && python -m pytest "tests/test_account_switcher_tt_retry_fg_drift.py::test_switch_tiktok_retry_bottomsheet_emits_honest_fg_drift" -q`
Expected: FAIL — `result.final_step == 'tt_3_open_list_retry_1'` (generic-сайт), честный код не эмитится.

- [ ] **Step 3: Вписать helper в сайт «header tap failed»**

В `account_switcher.py`, метод `_switch_tiktok`, заменить блок:

```python
                if not self._tap_profile_header(
                        elements_retry, header_y_max,
                        f'tt_3_open_list_retry_{attempt}',
                        fallback_coords=(540, 180)):
                    return self._fail(
                        'header tap failed после TT post-switch retry',
                        step=f'tt_3_open_list_retry_{attempt}',
                    )
```

на:

```python
                if not self._tap_profile_header(
                        elements_retry, header_y_max,
                        f'tt_3_open_list_retry_{attempt}',
                        fallback_coords=(540, 180)):
                    # [WP #156] foreground мог уйти с TikTok на ретрае — честная
                    # классификация вместо generic publish_failed_generic.
                    _drift = self._tt_retry_fg_drift_or_none(
                        target, cfg, f'tt_3_open_list_retry_{attempt}')
                    if _drift is not None:
                        return _drift
                    return self._fail(
                        'header tap failed после TT post-switch retry',
                        step=f'tt_3_open_list_retry_{attempt}',
                    )
```

- [ ] **Step 4: Вписать helper в сайт «bottomsheet не открылся»**

В том же методе заменить блок:

```python
                if not anchor_bounds_retry:
                    return self._fail(
                        'bottomsheet не открылся после TT post-switch retry',
                        step=f'tt_3_open_list_retry_{attempt}',
                    )
```

на:

```python
                if not anchor_bounds_retry:
                    # [WP #156] foreground-drift на ретрае → честный код
                    # tt_fg_drift_unrecoverable вместо generic. probe_elements —
                    # уже распарсенный пост-тап дамп для probe_top_labels.
                    _drift = self._tt_retry_fg_drift_or_none(
                        target, cfg, f'tt_3_open_list_retry_{attempt}',
                        probe_elements=post_elements_retry)
                    if _drift is not None:
                        return _drift
                    return self._fail(
                        'bottomsheet не открылся после TT post-switch retry',
                        step=f'tt_3_open_list_retry_{attempt}',
                    )
```

- [ ] **Step 5: Запустить integration-тест — убедиться, что проходит**

Run: `cd /tmp/wp156-autowarm && python -m pytest "tests/test_account_switcher_tt_retry_fg_drift.py::test_switch_tiktok_retry_bottomsheet_emits_honest_fg_drift" -q`
Expected: PASS.

- [ ] **Step 6: Прогнать весь новый файл + образец WP #130 (регрессия)**

Run: `cd /tmp/wp156-autowarm && python -m pytest tests/test_account_switcher_tt_retry_fg_drift.py tests/test_account_switcher_tt_switch_fg_guard.py -q`
Expected: PASS (5 + 11 = 16 passed; WP #130 не сломан).

- [ ] **Step 7: Commit**

```bash
cd /tmp/wp156-autowarm
git add account_switcher.py tests/test_account_switcher_tt_retry_fg_drift.py
git commit -m "feat(wp156): wire _tt_retry_fg_drift_or_none в два _fail-сайта retry-ветки

tt_3_open_list_retry: header-tap-fail и bottomsheet-not-opened теперь
проверяют foreground и эмитят честный tt_fg_drift_unrecoverable вместо
generic. + integration-тест на retry-путь _switch_tiktok.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Регрессия + codex review + PR

- [ ] **Step 1: Прогнать релевантный TT-switcher тест-сьют**

Run:
```bash
cd /tmp/wp156-autowarm && python -m pytest \
  tests/test_account_switcher_tt_retry_fg_drift.py \
  tests/test_account_switcher_tt_switch_fg_guard.py \
  tests/test_account_switcher_tt.py \
  tests/test_tt_account_switcher_open.py \
  tests/test_canonical_error_codes.py -q
```
Expected: все PASS (новый код аддитивен, generic-сайты сохраняют поведение при fg==TikTok). Если что-то красное — разбирать через superpowers:systematic-debugging, не подгонять тест.

- [ ] **Step 2: codex review uncommitted-диффа против main**

Run: `cd /tmp/wp156-autowarm && git diff origin/main | ~/.local/bin/codex review -`
Применить фидбэк раундами до 0 P1 (per стоячее правило). Если codex флагует ложноположительное (cross-class-boundary факт он не ловит) — задокументировать почему, не менять код вслепую.

- [ ] **Step 3: Push + PR (хук уже пушит ветку; PR через gh)**

```bash
cd /tmp/wp156-autowarm && git push origin wp156-tt-retry-fg-drift-honesty
GH_TOKEN=$(grep -m1 token ~/secrets/github-gengo2.env | cut -d= -f2) \
  gh pr create --repo GenGo2/delivery-contenthunter \
  --base main --head wp156-tt-retry-fg-drift-honesty \
  --title "WP#156: честный tt_fg_drift_unrecoverable на retry-ветке TT-свитчера" \
  --body "..."
```
(Тело PR: коротко — что было не так / что сделано / kill-switch / тесты. Сверить точную форму github-токена/CLI с reference_github_tokens.)

---

## Task 4: Deploy + WP update

- [ ] **Step 1: После merge — pull на main в прод-дире (без pm2 restart)**

```bash
cd /root/.openclaw/workspace-genri/autowarm && git checkout main && git pull origin main
grep -n "_tt_retry_fg_drift_or_none" account_switcher.py | head   # подтвердить, что код в проде
```
Expected: helper и оба call-сайта присутствуют. per-task spawn подхватит новый файл на следующей публикации — pm2 restart не нужен (см. feedback_deploy_scope_constraints, project_svg_logo_rasterization deploy-нюансы).

- [ ] **Step 2: Удалить worktree**

```bash
git worktree remove /tmp/wp156-autowarm
```

- [ ] **Step 3: Обновить WP #156 в OpenProject**

Комментарий в house-стиле (Что было не так → Что сделано → Что осталось), перевести статус в «Тестирование» (id 9). Осталось: verify реальной доли retry-fg-drift в `tt_fg_drift_unrecoverable` vs generic за 24ч (SQL по publish_tasks/events).

- [ ] **Step 4: Обновить память**

Создать `project_wp156_tt_retry_fg_drift.md` (SHIPPED+DEPLOYED, kill-switch, что осталось verify) + строка в MEMORY.md. Связать с [[project_wp131_tt_profile_tab_stale_ui]] и WP #130.

---

## Self-Review (выполнено автором плана)

**Spec coverage:**
- ✅ Helper с foreground-проверкой + честный код → Task 1.
- ✅ Оба `_fail`-сайта retry-ветки (header-tap, bottomsheet) → Task 2 Steps 3-4.
- ✅ `foreground_pkg` + `probe_top_labels` в meta; `meta.step`=retry-шаг, `final_step`=честный код → helper-код + тесты Task 1 Step 1 / Task 2 Step 1.
- ✅ Kill-switch `TT_SWITCH_FG_GUARD_ENABLED` → helper + тест `..._killswitch_off`.
- ✅ Happy-path не трогается → тест `..._foreground_is_tiktok` + generic-`_fail` сохранён в else-ветке.
- ✅ Без нового recovery → helper только эмитит + `_fail`, никаких relaunch.
- ✅ Деплой per-task spawn → Task 4.
- ✅ Не-в-скоупе (tt_4_target_profile_retry, первичный путь) → не трогаются.

**Placeholder scan:** код полный во всех шагах; «...» только в теле PR (Task 3 Step 3) и `_tap_profile_header(...)` ссылается на существующий вызов — оба намеренны.

**Type consistency:** `_tt_retry_fg_drift_or_none(self, target, cfg, step, probe_elements=None)` — одинаковая сигнатура в реализации (Task 1) и всех вызовах (Task 2). Возврат `SwitchResult | None`. `final_step='tt_fg_drift_unrecoverable'` совпадает с ключом `_SWITCHER_STEP_TO_CATEGORY` (publisher_kernel.py:105).
