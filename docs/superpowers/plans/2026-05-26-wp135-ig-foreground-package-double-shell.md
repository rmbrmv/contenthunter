# WP #135 — IG `_current_foreground_package` двойной shell: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Починить `_current_foreground_package` (двойной shell → всегда `'unknown'`), завести три спящих IG-foreground-ветки безопасно под единым kill-switch (default ON) и валидировать live-smoke'ом.

**Architecture:** Делегируем битый хелпер в проверенный `_ig_probe_foreground_pkg` (WP #129). Оживающее fail-fast-поведение (Play-Store-hijack + `external_app`) ставим под `IG_PRE_PICKER_FG_GUARD_ENABLED` (default ON); логирование пакета — всегда живое. Тесты — pytest + bare `InstagramMixin` stub (без `__init__`).

**Tech Stack:** Python 3, pytest, `unittest.mock`. Репозиторий: `GenGo2/delivery-contenthunter` (autowarm). Файлы: `publisher_instagram.py`, `tests/test_ig_gallery_mode_c_d_hardening.py`, `tests/test_ig_edits_banner_dismiss.py`.

**Spec:** `docs/superpowers/specs/2026-05-26-wp135-ig-foreground-package-double-shell-design.md` (в репо `contenthunter`).

---

## File Structure

- **Modify** `publisher_instagram.py`:
  - `_current_foreground_package` (стр. ~856) → делегирование в `_ig_probe_foreground_pkg`.
  - `_ig_probe_foreground_pkg` (стр. ~889) → обновить docstring (снять предупреждение про баг).
  - **+ module-level** `_ig_pre_picker_fg_guard_enabled()` (рядом со стр. ~460).
  - **+ instance** `_ig_pre_picker_guard_pkg()` (рядом со стр. ~872).
  - `_ig_handle_edits_promo_at_picker` Play-Store-ветка (стр. ~1438) → gate под kill-switch.
  - pre-picker guard (стр. ~2269) → `self._ig_pre_picker_guard_pkg()` + cross-ref комментарий.
- **Modify** `tests/test_ig_gallery_mode_c_d_hardening.py` → регрессионный тест на команду + тесты kill-switch helper'ов.
- **Modify** `tests/test_ig_edits_banner_dismiss.py` → тест Play-Store-ветки при выключенном kill-switch.

> **Примечание по строкам:** номера ориентировочные (прод/стенд на `2b57fee`). Перед правкой найти якоря через grep, не доверять номеру вслепую (проект едет быстрее памяти).

---

### Task 0: Изолированный worktree + зелёный baseline

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees.

- [ ] **Step 1: Создать worktree от свежего main стенда**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add -b wp135-ig-fg-double-shell ../wt-wp135 origin/main
cd ../wt-wp135
```

- [ ] **Step 2: Зафиксировать зелёный baseline затрагиваемых тестов**

Run:
```bash
cd /home/claude-user/wt-wp135
python -m pytest tests/test_ig_gallery_mode_c_d_hardening.py tests/test_ig_edits_banner_dismiss.py tests/test_ig_wait_upload_fg_guard.py -q
```
Expected: PASS (зелёный). Это baseline — все правки сохраняют его зелёным.

> Не оставлять half-broken state между задачами (parallel-sessions practice). Каждая Task — atomic commit на зелёном pytest.

---

### Task 1: Регрессионный тест на двойной shell (RED) → фикс делегированием (GREEN)

**Files:**
- Test: `tests/test_ig_gallery_mode_c_d_hardening.py` (класс `TestCurrentForegroundPackage`, после стр. ~287)
- Modify: `publisher_instagram.py:856-871` (`_current_foreground_package`), docstring `_ig_probe_foreground_pkg` (~889-896)

- [ ] **Step 1: Написать падающий тест (ловит двойной shell)**

Существующие тесты мокают `adb` и игнорируют команду — баг не ловят. Добавляем тест на саму команду. В конец класса `TestCurrentForegroundPackage`:

```python
    def test_does_not_double_wrap_shell(self):
        """[WP #135] adb() сам оборачивает cmd в shell "..."; передаваемая
        команда НЕ должна начинаться со 'shell' — иначе двойной shell
        (sh: shell: not found) → метод всегда 'unknown'."""
        stub = _make_ig_stub()
        stub.adb.return_value = (
            'topResumedActivity=ActivityRecord{x u0 '
            'com.instagram.android/.Foo t1}'
        )
        result = stub._current_foreground_package()
        assert result == 'com.instagram.android'
        assert stub.adb.called
        cmd = stub.adb.call_args[0][0]
        assert not cmd.lstrip().startswith('shell'), \
            f'двойной shell — команда не должна начинаться со shell: {cmd!r}'
        assert 'dumpsys activity activities' in cmd
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `python -m pytest tests/test_ig_gallery_mode_c_d_hardening.py::TestCurrentForegroundPackage::test_does_not_double_wrap_shell -v`
Expected: FAIL на `assert not cmd.lstrip().startswith('shell')` — текущая команда `'shell dumpsys ...'`.

- [ ] **Step 3: Фикс — делегировать в проверенный probe**

В `publisher_instagram.py` заменить тело `_current_foreground_package` (стр. ~856-871) на:

```python
    def _current_foreground_package(self) -> str:
        """Foreground package (e.g. 'com.instagram.android'); 'unknown' при ошибке.

        [WP #135] Раньше слал 'shell dumpsys ...' в adb(), который сам оборачивает
        cmd в shell "..." → двойной shell (sh: shell: not found) → всегда 'unknown'.
        Делегируем в проверенный _ig_probe_foreground_pkg (WP #129, bare-dumpsys,
        тот же regex). Используется в _ig_handle_edits_promo_at_picker (Play-Store
        fail-fast) и _ig_classify_pre_picker_state (pre-Шаг-5 guard).
        """
        return self._ig_probe_foreground_pkg()
```

И в docstring `_ig_probe_foreground_pkg` (стр. ~890-896) снять устаревшее предупреждение — заменить абзац «НЕ используем _current_foreground_package — там команда с лишним префиксом 'shell'...» на:

```python
        """Foreground package via bare dumpsys (WP #129).

        Канонический probe foreground-пакета (WP #135: _current_foreground_package
        делегирует сюда). Команда без 'shell' — adb() сам оборачивает в shell "...".
        Возвращает пакет или 'unknown' при ошибке/непарсе.
        """
```

- [ ] **Step 4: Прогнать — зелёный (новый + 5 существующих)**

Run: `python -m pytest tests/test_ig_gallery_mode_c_d_hardening.py::TestCurrentForegroundPackage -v`
Expected: PASS — все 6 (новый + `test_extracts_package_from_top_resumed_activity`, `test_extracts_play_store_package`, `test_returns_unknown_on_empty_dumpsys`, `test_returns_unknown_on_unparseable_output`, `test_returns_unknown_on_adb_exception`). Существующие проходят, т.к. `_ig_probe_foreground_pkg` использует тот же regex и контракт `'unknown'`.

- [ ] **Step 5: Commit**

```bash
git add publisher_instagram.py tests/test_ig_gallery_mode_c_d_hardening.py
git commit -m "fix(wp135): _current_foreground_package делегирует в _ig_probe_foreground_pkg (двойной shell → всегда unknown)"
```

---

### Task 2: Kill-switch helper + `_ig_pre_picker_guard_pkg` (TDD)

**Files:**
- Test: `tests/test_ig_gallery_mode_c_d_hardening.py` (новый класс в конце файла)
- Modify: `publisher_instagram.py` (+ module-level helper ~460, + instance method ~872)

- [ ] **Step 1: Написать падающие тесты**

В конец `tests/test_ig_gallery_mode_c_d_hardening.py` (импорт `_ig_pre_picker_fg_guard_enabled` добавить в блок import из `publisher_instagram` на стр. ~27):

```python
# ─── WP #135: kill-switch IG_PRE_PICKER_FG_GUARD_ENABLED ─────────────────────
from publisher_instagram import _ig_pre_picker_fg_guard_enabled  # noqa: E402


class TestPrePickerFgGuardKillSwitch:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv('IG_PRE_PICKER_FG_GUARD_ENABLED', raising=False)
        assert _ig_pre_picker_fg_guard_enabled() is True

    def test_disabled_when_env_zero(self, monkeypatch):
        monkeypatch.setenv('IG_PRE_PICKER_FG_GUARD_ENABLED', '0')
        assert _ig_pre_picker_fg_guard_enabled() is False

    def test_guard_pkg_returns_real_when_enabled(self, monkeypatch):
        monkeypatch.delenv('IG_PRE_PICKER_FG_GUARD_ENABLED', raising=False)
        stub = _make_ig_stub()
        stub._current_foreground_package = MagicMock(
            return_value='com.google.android.youtube')
        assert stub._ig_pre_picker_guard_pkg() == 'com.google.android.youtube'

    def test_guard_pkg_returns_unknown_when_disabled(self, monkeypatch):
        monkeypatch.setenv('IG_PRE_PICKER_FG_GUARD_ENABLED', '0')
        stub = _make_ig_stub()
        stub._current_foreground_package = MagicMock(
            return_value='com.google.android.youtube')
        # выключенный guard → 'unknown' → классификатор трактует как IG (старое поведение)
        assert stub._ig_pre_picker_guard_pkg() == 'unknown'
        stub._current_foreground_package.assert_not_called()
```

- [ ] **Step 2: Прогнать — упадёт на импорте/атрибуте**

Run: `python -m pytest tests/test_ig_gallery_mode_c_d_hardening.py::TestPrePickerFgGuardKillSwitch -v`
Expected: FAIL — `ImportError: cannot import name '_ig_pre_picker_fg_guard_enabled'` (или `AttributeError` на `_ig_pre_picker_guard_pkg`).

- [ ] **Step 3: Реализовать оба helper'а**

Module-level, в `publisher_instagram.py` перед `def _ig_classify_pre_picker_state` (стр. ~462):

```python
def _ig_pre_picker_fg_guard_enabled() -> bool:
    """[WP #135] Kill-switch оживающих foreground-fail-fast веток IG
    (Play-Store-hijack + external_app pre-picker). Default ON;
    IG_PRE_PICKER_FG_GUARD_ENABLED=0 → откат к старому поведению без передеплоя."""
    return os.environ.get('IG_PRE_PICKER_FG_GUARD_ENABLED', '1') != '0'
```

Instance method, сразу после `_current_foreground_package` (стр. ~872):

```python
    def _ig_pre_picker_guard_pkg(self) -> str:
        """[WP #135] foreground-пакет для pre-Шаг-5 guard под kill-switch.
        Выключенный guard → 'unknown': классификатор трактует как IG (старое
        поведение), а UI-маркерные ветки (templates/story/editor) продолжают
        работать — они от пакета не зависят."""
        if not _ig_pre_picker_fg_guard_enabled():
            return 'unknown'
        return self._current_foreground_package()
```

- [ ] **Step 4: Прогнать — зелёный**

Run: `python -m pytest tests/test_ig_gallery_mode_c_d_hardening.py::TestPrePickerFgGuardKillSwitch -v`
Expected: PASS (4 теста).

- [ ] **Step 5: Commit**

```bash
git add publisher_instagram.py tests/test_ig_gallery_mode_c_d_hardening.py
git commit -m "feat(wp135): kill-switch IG_PRE_PICKER_FG_GUARD_ENABLED + _ig_pre_picker_guard_pkg"
```

---

### Task 3: Врезка kill-switch в две оживающие ветки + cross-ref комментарий

**Files:**
- Test: `tests/test_ig_edits_banner_dismiss.py` (после `test_handle_playstore_hijack_fails_fast`, стр. ~235)
- Modify: `publisher_instagram.py` Play-Store-ветка (~1438) + pre-picker guard (~2269)

- [ ] **Step 1: Написать падающий тест (Play-Store при выключенном guard НЕ fail-fast)**

В `tests/test_ig_edits_banner_dismiss.py` после `test_handle_playstore_hijack_fails_fast`:

```python
def test_handle_playstore_hijack_skipped_when_guard_disabled(monkeypatch):
    """[WP #135] При IG_PRE_PICKER_FG_GUARD_ENABLED=0 Play-Store-ветка не
    срабатывает — идём обычным путём dismiss (старое поведение)."""
    monkeypatch.setenv('IG_PRE_PICKER_FG_GUARD_ENABLED', '0')
    stub = _make_ig_stub()
    stub._current_foreground_package = MagicMock(return_value='com.android.vending')
    # plain picker без баннера → _dismiss_ig_edits_promo вернёт 'absent' → 'clear'
    result = stub._ig_handle_edits_promo_at_picker(_ui_plain_picker(), 'gallery_select')
    assert result == 'clear'
    cats = [c.kwargs.get('meta', {}).get('category')
            for c in stub.log_event.call_args_list]
    assert 'ig_edits_promo_playstore_hijack' not in cats
```

> Сверить, что `_make_ig_stub` (стр. ~75) и `_ui_plain_picker` существуют в этом файле; имя категории `ig_edits_promo_playstore_hijack` совпадает с `test_handle_playstore_hijack_fails_fast`.

- [ ] **Step 2: Прогнать — упадёт**

Run: `python -m pytest tests/test_ig_edits_banner_dismiss.py::test_handle_playstore_hijack_skipped_when_guard_disabled -v`
Expected: FAIL — сейчас ветка не под kill-switch, fail-fast срабатывает всегда → `result == 'failed'`.

- [ ] **Step 3a: Gate Play-Store-ветки (`_ig_handle_edits_promo_at_picker`, ~1438)**

Заменить:
```python
        # Play Store takeover — honest fail-fast, no recovery (spec decision).
        fg = self._current_foreground_package()
        if fg == 'com.android.vending':
```
на:
```python
        # Play Store takeover — honest fail-fast, no recovery (spec decision).
        # [WP #135] gated: ветка ожила после фикса _current_foreground_package
        # (раньше fg всегда 'unknown'). Kill-switch IG_PRE_PICKER_FG_GUARD_ENABLED.
        fg = (self._current_foreground_package()
              if _ig_pre_picker_fg_guard_enabled() else None)
        if fg == 'com.android.vending':
```
(`fg` используется только внутри if-блока для `meta={'foreground_package': fg}` — при выключенном guard блок не входится, `None` безопасен.)

- [ ] **Step 3b: Pre-picker guard (~2269) → helper + cross-ref комментарий**

Заменить:
```python
        guard_ui = self.dump_ui()
        guard_pkg = self._current_foreground_package()
        guard_result = _ig_classify_pre_picker_state(guard_ui, guard_pkg)
```
на:
```python
        guard_ui = self.dump_ui()
        # [WP #135] под kill-switch: выключенный guard → 'unknown' = старое
        # поведение (ветка external_app молчит; UI-маркерные ветки работают).
        # NB: это picker ГАЛЕРЕИ (Шаг 5, выбор видео), НЕ account-picker WP #119
        # (_ig_guard_picker_foreground в account_switcher.py, шаг ig_4_pick_account).
        # Разные шаги/файлы — guard'ы не дублируют и не конфликтуют.
        guard_pkg = self._ig_pre_picker_guard_pkg()
        guard_result = _ig_classify_pre_picker_state(guard_ui, guard_pkg)
```
(Логирование на стр. ~2252 `'foreground_package': self._current_foreground_package()` НЕ трогаем — observability всегда живое.)

- [ ] **Step 4: Прогнать — зелёный (новый + существующий fail-fast)**

Run: `python -m pytest tests/test_ig_edits_banner_dismiss.py -k playstore -v`
Expected: PASS — `test_handle_playstore_hijack_fails_fast` (default ON → 'failed') И `test_handle_playstore_hijack_skipped_when_guard_disabled` (OFF → 'clear').

- [ ] **Step 5: Commit**

```bash
git add publisher_instagram.py tests/test_ig_edits_banner_dismiss.py
git commit -m "feat(wp135): kill-switch на Play-Store + external_app fail-fast ветки + cross-ref #119"
```

---

### Task 4: Полный прогон затронутых тестов + sanity

**Files:** нет правок (только проверка); при падении — фикс в соответствующем файле.

- [ ] **Step 1: Прогнать все затронутые + смежные IG-тесты**

Run:
```bash
cd /home/claude-user/wt-wp135
python -m pytest tests/test_ig_gallery_mode_c_d_hardening.py tests/test_ig_edits_banner_dismiss.py tests/test_ig_wait_upload_fg_guard.py -q
```
Expected: PASS, 0 failed. (Если есть pre-existing fails вне scope — зафиксировать, что они были на baseline в Task 0, не чинить здесь.)

- [ ] **Step 2: Grep-проверка отсутствия других `'shell '`-префиксов в adb-вызовах IG**

Run: `grep -nE "self\.adb\(\s*['\"]shell " publisher_instagram.py`
Expected: пусто (наш был единственным; если найдётся ещё — отдельная находка, отметить, не расширять scope без согласования).

- [ ] **Step 3: Commit (если были правки; иначе пропустить)**

```bash
git commit -am "test(wp135): зелёный прогон IG foreground-тестов" --allow-empty
```

---

### Task 5: Live-smoke на стенде (операционная, ОБЯЗАТЕЛЬНА перед прод)

Код этих веток ни разу не исполнялся в проде — смоук до деплоя обязателен (выбор пользователя).

- [ ] **Step 1: Развернуть фикс на стенд** — скопировать изменённый `publisher_instagram.py` в активный путь стенда (publisher спавнится свежим на задачу → PM2 restart не нужен; сверить актуальный `exec cwd` autowarm в pm2 во избежание stale-dev-кода).

- [ ] **Step 2: Реальные IG-публикации** на phone #19 / #171, kill-switch ON (default). 2-3 happy-path задачи.

- [ ] **Step 3: Проверить логи** — на gallery/edits-шагах `foreground_package` в meta = `com.instagram.android` (не 'unknown', не чужой пакет); **нет ложного `ig_external_app_foreground`**; success-rate публикаций не просел.
```sql
-- события foreground за смоук-окно
SELECT meta->>'category', meta->>'foreground_package', COUNT(*)
FROM events WHERE type='error' AND created_at > now()-interval '1 hour'
  AND meta->>'category' IN ('ig_external_app_foreground','ig_edits_promo_playstore_hijack','ig_gallery_button_not_found')
GROUP BY 1,2 ORDER BY 3 DESC;
```

- [ ] **Step 4 (опц.): Форс Play-Store-сценария** — открыть `com.android.vending` перед шагом → подтвердить корректный fail-fast `ig_edits_promo_playstore_hijack`.

---

### Task 6: Деплой в прод + мониторинг + апдейт WP (операционная)

- [ ] **Step 1: Зелёный pytest + merge worktree-ветки** в main стенда (atomic, no force-push).

- [ ] **Step 2: Cherry-pick в prod autowarm** `/root/.openclaw/workspace-genri/autowarm/` (auto-push hook → GenGo2/delivery-contenthunter). Сверить `pm2 describe autowarm | grep "exec cwd"` (dump-path drift).

- [ ] **Step 3: codex review диффа** (`git diff | codex review -`), раундами до 0 P1/P2.

- [ ] **Step 4: 24ч прод-мониторинг** — частота `ig_external_app_foreground` + `ig_edits_promo_playstore_hijack` (ожидаем единичные, не всплеск) + IG publish success-rate (не должен просесть = нет false-positive). Kill-switch `IG_PRE_PICKER_FG_GUARD_ENABLED=0` — аварийный откат.

- [ ] **Step 5: Апдейт WP #135 в OpenProject** — house-стиль (Что было не так → Что сделано → Что осталось), включить корректировку посылки про #119 (пересечения нет). Снять с автоворкер-вопроса.

- [ ] **Step 6: Cleanup worktree** — `git worktree remove ../wt-wp135` после merge.

---

## Self-Review

**Spec coverage:** §1 баг → Task 1. §3 три потребителя → Task 1 (фикс) + Task 3 (gate Play-Store/external_app) + логирование не гейтится (Task 3 Step 3b note). §4.1 делегирование → Task 1. §4.2 kill-switch → Task 2. §4.3 врезка → Task 3. §4.4 cross-ref → Task 3 Step 3b. §5 тесты → Task 1/2/3. §6 smoke → Task 5. §7 деплой → Task 6. §8 риски (false-positive) → Task 5 Step 3 + Task 6 Step 4. ✓ §2 (нет пересечения с #119) — отражено в cross-ref комментарии и WP-апдейте.

**Placeholder scan:** код приведён полностью в каждом шаге; команды и ожидаемый результат указаны. ✓

**Type consistency:** `_ig_pre_picker_fg_guard_enabled()` (module, bool) и `_ig_pre_picker_guard_pkg()` (instance, str) — имена согласованы между Task 2 (определение), Task 3 (использование на 1438/2269) и тестами. `_current_foreground_package`/`_ig_probe_foreground_pkg` контракт `'unknown'` сохранён. ✓
