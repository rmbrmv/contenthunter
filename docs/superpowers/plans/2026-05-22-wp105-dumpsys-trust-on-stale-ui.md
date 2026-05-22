# WP #105 Round 2 — Trust dumpsys on stale uiautomator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Когда `dumpsys` стабильно подтверждает, что целевое приложение на переднем плане, а `uiautomator`-дамп залип на launcher/пусто, доверять dumpsys и считать приложение поднятым — закрыть рецидив `ig_app_launch_failed`.

**Architecture:** Точечная правка вложенной функции `_foreground_pkg` внутри `_open_app` (`account_switcher.py`). Существующий catch-up uiautomator сохраняется; после него добавляется проверка стабильности dumpsys (3 чтения подряд) под env-kill-switch + observability-событие. Защиты от реальных overlay не трогаются.

**Tech Stack:** Python 3, pytest, `unittest.mock` (fake-proxy), ADB (`dumpsys`/`uiautomator dump`), Postgres event-log.

**Спек:** `docs/superpowers/specs/2026-05-22-wp105-dumpsys-trust-on-stale-ui-design.md`

---

## Репозиторий и изоляция

Код живёт в **отдельном репозитории** `autowarm-testbench` (НЕ в `contenthunter`, где лежат спек/план).

- Код: `/home/claude-user/autowarm-testbench/account_switcher.py`
- Тесты: `/home/claude-user/autowarm-testbench/tests/test_account_switcher.py`
- Прод: `/root/.openclaw/workspace-genri/autowarm/account_switcher.py`

**Перед реализацией** (superpowers:using-git-worktrees) создать worktree autowarm-testbench от свежего `main`:

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin
git worktree add -b feat/wp105-dumpsys-trust .worktrees/wp105-dumpsys-trust origin/main
cd .worktrees/wp105-dumpsys-trust
```

Все шаги ниже выполняются в этом worktree. Запуск тестов:

```bash
cd /home/claude-user/autowarm-testbench/.worktrees/wp105-dumpsys-trust
python3 -m pytest tests/test_account_switcher.py -q
```

---

## File Structure

| Файл | Ответственность | Изменение |
|---|---|---|
| `account_switcher.py` | `_foreground_pkg` внутри `_open_app` (~5156–5208): резолв разногласия dumpsys↔uiautomator | Modify: заменить блок `return pkg_ui or pkg_dump` (хвост ветки persistent-launcher, строки ~5203–5204) на stability-check + trust |
| `tests/test_account_switcher.py` | unit-покрытие `_open_app` foreground-логики (блок «WP #105», строки 841–1054) | Modify 1 тест (инверсия) + Create 2 теста |

Новых файлов нет. Все изменения — в двух существующих файлах.

---

## Текущий код (точка вставки)

`account_switcher.py`, внутри `_foreground_pkg`, ветка для залипшего uiautomator (строки ~5195–5204):

```python
                if pkg_dump == target_pkg and pkg_ui in ('', 'com.sec.android.app.launcher'):
                    for _ in range(3):
                        time.sleep(0.8)
                        xml2 = self.p.dump_ui(retries=1) or ''
                        m_ui2 = re.search(r'package="([^"]+)"', xml2)
                        pkg_ui2 = m_ui2.group(1) if m_ui2 else ''
                        if pkg_ui2 == target_pkg:
                            return target_pkg
                    # uiautomator не догнал — возвращаем launcher
                    return pkg_ui or pkg_dump
```

Меняется ТОЛЬКО хвост (`# uiautomator не догнал` + `return pkg_ui or pkg_dump`). Catch-up loop остаётся как есть.

---

## Task 1: Trust stable dumpsys when uiautomator is stuck on launcher

**Files:**
- Modify: `account_switcher.py` (`_foreground_pkg`, ветка persistent-launcher, ~5203–5204)
- Test: `tests/test_account_switcher.py` (инверсия `test_open_app_dumpsys_target_uiautomator_persistent_launcher_does_not_shortcut`, строки 921–938)

- [ ] **Step 1: Инвертировать существующий behavior-тест на новое поведение**

В `tests/test_account_switcher.py` заменить тест целиком (старое тело строки 921–938) на:

```python
def test_open_app_dumpsys_stable_uiautomator_persistent_launcher_trusts_dumpsys(monkeypatch):
    """[WP #105 Round 2] dumpsys стабильно=target, uiautomator упорно=launcher
    (залипший Samsung uiautomator) → доверяем dumpsys → _open_app True.

    Заменяет прежнее поведение (_does_not_shortcut → False): в проде uiautomator
    не догоняет dumpsys минутами (task 9227), confirming-poll давал ложный fail.
    """
    from unittest.mock import MagicMock
    switcher, stub = _make_open_app_stub(monkeypatch)
    target = 'com.instagram.android'
    stub.adb = MagicMock(return_value=_adb_dumpsys_response(target))
    stub.dump_ui = MagicMock(return_value=_ui_dump_response('com.sec.android.app.launcher'))
    ok = switcher._open_app(target, f'{target}/.MainActivity', 'ig_1_feed_test')
    assert ok is True
    cats = _extract_log_meta_categories(stub)
    assert 'switcher_foreground_trusted_dumpsys' in cats
    # ранний return на первом _foreground_pkg → dismiss/am-start ladder не нужны
    assert not switcher._dismiss_blocking_overlays.called
```

- [ ] **Step 2: Запустить тест — убедиться что падает**

Run:
```bash
python3 -m pytest tests/test_account_switcher.py::test_open_app_dumpsys_stable_uiautomator_persistent_launcher_trusts_dumpsys -q
```
Expected: FAIL — текущий код возвращает launcher (нет `switcher_foreground_trusted_dumpsys`, `ok is False`, `_dismiss_blocking_overlays` вызван).

- [ ] **Step 3: Реализовать stability-trust в `_foreground_pkg`**

В `account_switcher.py` заменить хвост ветки persistent-launcher:

```python
                    # uiautomator не догнал — возвращаем launcher
                    return pkg_ui or pkg_dump
```

на:

```python
                    # [WP #105 Round 2 2026-05-22] uiautomator залип на launcher.
                    # В проде dumpsys И скриншот стабильно показывают target (evidence
                    # task 9227): сломан именно uiautomator XML-дамп. Если dumpsys
                    # СТАБИЛЕН (3 чтения подряд == target) — доверяем ему.
                    # Kill-switch: SWITCHER_TRUST_DUMPSYS_ON_STALE_UI=0 → старое поведение.
                    if os.getenv('SWITCHER_TRUST_DUMPSYS_ON_STALE_UI', '1') != '0':
                        stable = True
                        for _ in range(3):
                            time.sleep(0.5)
                            top_n = self.p.adb(
                                "dumpsys activity activities | "
                                "grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
                            m_n = re.search(r'\s([\w\.]+)/[\w\.]+', top_n)
                            if (m_n.group(1) if m_n else '') != target_pkg:
                                stable = False
                                break
                        if stable:
                            self.p.log_event(
                                'info',
                                f'foreground_trusted_dumpsys: dumpsys={pkg_dump} '
                                f'uiautomator={pkg_ui} (stale UI, dumpsys stable)',
                                meta={'category': 'switcher_foreground_trusted_dumpsys',
                                      'pkg_dumpsys': pkg_dump,
                                      'pkg_uiautomator': pkg_ui,
                                      'target_pkg': target_pkg,
                                      'step': step_name,
                                      'stable_reads': 3},
                            )
                            return target_pkg
                    # dumpsys нестабилен или kill-switch off — честный launcher
                    return pkg_ui or pkg_dump
```

- [ ] **Step 4: Запустить тест — убедиться что проходит**

Run:
```bash
python3 -m pytest tests/test_account_switcher.py::test_open_app_dumpsys_stable_uiautomator_persistent_launcher_trusts_dumpsys -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add account_switcher.py tests/test_account_switcher.py
git commit -m "fix(ig): trust stable dumpsys when uiautomator stuck on launcher (WP #105 R2)"
```

---

## Task 2: Edge-case lock — flapping dumpsys is NOT trusted

**Files:**
- Test: `tests/test_account_switcher.py` (новый тест после Task 1 теста)

- [ ] **Step 1: Написать тест на «плавающий» dumpsys**

Добавить в `tests/test_account_switcher.py`:

```python
def test_open_app_dumpsys_flapping_not_trusted_returns_false(monkeypatch):
    """[WP #105 Round 2] dumpsys «плавает» (target↔launcher), uiautomator всегда
    launcher → стабильность не подтверждается → НЕ доверяем → _open_app False."""
    from unittest.mock import MagicMock
    import itertools
    switcher, stub = _make_open_app_stub(monkeypatch)
    target = 'com.instagram.android'
    launcher = 'com.sec.android.app.launcher'
    # dumpsys чередует target/launcher → в любом окне из 4 чтений есть launcher,
    # поэтому stability-check (3 подряд == target) никогда не проходит.
    flap = itertools.cycle([target, launcher])
    def adb_router(cmd, *args, **kwargs):
        if 'dumpsys' in cmd:
            return _adb_dumpsys_response(next(flap))
        return ''  # am start и прочее
    stub.adb = MagicMock(side_effect=adb_router)
    stub.dump_ui = MagicMock(return_value=_ui_dump_response(launcher))
    ok = switcher._open_app(target, f'{target}/.MainActivity', 'ig_1_feed_test')
    assert ok is False
    assert 'switcher_foreground_trusted_dumpsys' not in _extract_log_meta_categories(stub)
```

- [ ] **Step 2: Запустить тест — убедиться что проходит**

Run:
```bash
python3 -m pytest tests/test_account_switcher.py::test_open_app_dumpsys_flapping_not_trusted_returns_false -q
```
Expected: PASS (поведение уже реализовано в Task 1; тест фиксирует, что нестабильный dumpsys не доверяется).

- [ ] **Step 3: Commit**

```bash
git add tests/test_account_switcher.py
git commit -m "test(ig): lock — flapping dumpsys not trusted (WP #105 R2)"
```

---

## Task 3: Edge-case lock — kill-switch disables trust

**Files:**
- Test: `tests/test_account_switcher.py` (новый тест)

- [ ] **Step 1: Написать тест на kill-switch off**

Добавить в `tests/test_account_switcher.py`:

```python
def test_open_app_trust_dumpsys_killswitch_off_returns_false(monkeypatch):
    """[WP #105 Round 2] При SWITCHER_TRUST_DUMPSYS_ON_STALE_UI=0 даже стабильный
    dumpsys=target + uiautomator=launcher НЕ доверяется → старое поведение (False)."""
    from unittest.mock import MagicMock
    monkeypatch.setenv('SWITCHER_TRUST_DUMPSYS_ON_STALE_UI', '0')
    switcher, stub = _make_open_app_stub(monkeypatch)
    target = 'com.instagram.android'
    stub.adb = MagicMock(return_value=_adb_dumpsys_response(target))
    stub.dump_ui = MagicMock(return_value=_ui_dump_response('com.sec.android.app.launcher'))
    ok = switcher._open_app(target, f'{target}/.MainActivity', 'ig_1_feed_test')
    assert ok is False
    assert 'switcher_foreground_trusted_dumpsys' not in _extract_log_meta_categories(stub)
```

- [ ] **Step 2: Запустить тест — убедиться что проходит**

Run:
```bash
python3 -m pytest tests/test_account_switcher.py::test_open_app_trust_dumpsys_killswitch_off_returns_false -q
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_account_switcher.py
git commit -m "test(ig): lock — kill-switch disables dumpsys trust (WP #105 R2)"
```

---

## Task 4: Full suite green + anti-drift check

**Files:** нет изменений кода — верификация.

- [ ] **Step 1: Прогнать весь файл тестов account_switcher**

Run:
```bash
python3 -m pytest tests/test_account_switcher.py -q
```
Expected: PASS, 0 failed. Особое внимание — что НЕ сломались:
`test_open_app_uiautomator_target_dumpsys_launcher_returns_true`,
`test_open_app_both_sources_launcher_returns_false`,
`test_open_app_both_sources_target_returns_true_no_disagree`,
`test_open_app_settle_wait_catches_late_arrival`,
`test_open_app_dumpsys_target_uiautomator_permissioncontroller_does_not_shortcut`,
`test_open_app_settle_wait_respects_deadline`.

- [ ] **Step 2: Anti-drift — сверить fake-proxy с реальным DevicePublisher**

Проверить, что методы, которые дёргает новый код через `self.p`, существуют у реального публикатора (урок PR #52 — mock-proxy drift):

Run:
```bash
grep -n "def adb\b\|def log_event\|def dump_ui\|def set_step\|def ensure_unlocked" publisher_base.py publisher.py
```
Expected: `adb`, `log_event`, `dump_ui` (publisher_base.py) присутствуют. Новый код использует только `self.p.adb` и `self.p.log_event` (оба реальны). Никаких новых методов прокси не вводится — дрейф невозможен.

- [ ] **Step 3: Codex review диффа (стандартная практика, до 0 P1/P2)**

Run:
```bash
git diff origin/main...HEAD | ~/.local/bin/codex review -
```
Применить фидбэк P1/P2 раундами, перезапуская тесты после правок. (Bubblewrap-warning benign; `--base` сломан — только stdin.)

- [ ] **Step 4: Commit (если codex-правки были)**

```bash
git add -A
git commit -m "fix(ig): codex review nits (WP #105 R2)"
```

---

## Task 5: PR → merge в autowarm-testbench main

**Files:** нет изменений — git/PR.

- [ ] **Step 1: Push ветки**

```bash
cd /home/claude-user/autowarm-testbench/.worktrees/wp105-dumpsys-trust
git push -u origin feat/wp105-dumpsys-trust
```

- [ ] **Step 2: Открыть PR в main**

```bash
gh pr create --base main --head feat/wp105-dumpsys-trust \
  --title "fix(ig): trust stable dumpsys when uiautomator stuck on launcher (WP #105 R2)" \
  --body "Рецидив ig_app_launch_failed (пик 6–7/день 22.05). uiautomator залипает на launcher минутами, dumpsys+скриншот корректны. Доверяем стабильному dumpsys (3 чтения) при залипшем uiautomator, под kill-switch SWITCHER_TRUST_DUMPSYS_ON_STALE_UI + событие switcher_foreground_trusted_dumpsys. Спек/план в contenthunter docs/superpowers."
```

- [ ] **Step 2.5: STOP — подтверждение пользователя перед merge/деплоем**

Деплой в прод — outward-facing действие. Дождаться явного «мержим/деплоим» от пользователя перед Step 3 и Task 6.

- [ ] **Step 3: Merge после ревью**

```bash
gh pr merge feat/wp105-dumpsys-trust --squash
```

---

## Task 6: Деплой в прод + verify (после подтверждения пользователя)

**Files:** prod `/root/.openclaw/workspace-genri/autowarm/account_switcher.py`

- [ ] **Step 1: Cherry-pick фикса в prod autowarm**

> ВНИМАНИЕ: prod-checkout может быть на чужой ветке/иметь чужой uncommitted WIP. Перед действиями — `git -C /root/.openclaw/workspace-genri/autowarm status`. НЕ делать force-push (урок subagent force-push). Применять хирургически.

Применить изменённый блок `_foreground_pkg` в prod-файле (тот же дифф, что в Task 1 Step 3). Деплой Python = правка файла; **PM2 restart НЕ нужен** — публикатор спавнится свежим на каждую задачу.

- [ ] **Step 2: Smoke — синтаксис prod-файла**

Run:
```bash
python3 -c "import ast; ast.parse(open('/root/.openclaw/workspace-genri/autowarm/account_switcher.py').read()); print('OK')"
```
Expected: `OK`.

- [ ] **Step 3: Verify на проде (за 24ч)**

Утром следующего дня:
```bash
export PGPASSWORD=openclaw123
psql -h localhost -U openclaw -d openclaw -c "
SELECT date(updated_at) d, error_code, count(*)
FROM publish_tasks
WHERE platform='Instagram' AND error_code='ig_app_launch_failed' AND testbench=false
  AND updated_at > now() - interval '24 hours' GROUP BY 1,2;"
psql -h localhost -U openclaw -d openclaw -c "
SELECT count(*) trusted_events
FROM publish_tasks WHERE platform='Instagram' AND testbench=false
  AND updated_at > now() - interval '24 hours'
  AND events::text ILIKE '%switcher_foreground_trusted_dumpsys%';"
```
Expected: `ig_app_launch_failed` стремится к 0; `trusted_events` > 0 (новый путь срабатывает). Кросс-сверить task'и с trusted-событием против их финального статуса — подтвердить, что они доходят до успеха.

- [ ] **Step 4: Обновить OpenProject WP #105**

Комментарий в house-style (Что было не так → Что сделано → Что осталось, без жаргона), статус → `Тестирование` (id 9) до подтверждения динамики, затем `Готово` (id 12) после verify. Обновить память WP #105.

---

## Self-Review (выполнено автором плана)

**1. Покрытие спека:**
- §3 логика разрешения (catch-up → stability → trust/launcher) → Task 1 Step 3 ✓
- §3 kill-switch → Task 1 Step 3 (`os.getenv`) + Task 3 (тест) ✓
- §3 сохранённые защиты (overlay, pkg_ui==target) → не трогаются; регресс-тест permissioncontroller в Task 4 Step 1 ✓
- §4 observability `switcher_foreground_trusted_dumpsys` → Task 1 Step 3 + Task 1/2/3 проверки ✓
- §6 матрица тестов → Task 1 (главный + ловит существующие catch-up/symmetry/both/settle) + Task 2 (flapping) + Task 3 (kill-switch) ✓
- §7 деплой (PM2 не нужен, cherry-pick, codex, verify) → Task 4 Step 3 + Task 6 ✓
- §8 риски (анти-дрейф, no force-push, параллельные сессии) → Task 4 Step 2, Task 6 Step 1, worktree ✓

**2. Плейсхолдеры:** нет TBD/«handle edge cases»/«similar to». Весь код приведён дословно.

**3. Согласованность типов/имён:** env-переменная `SWITCHER_TRUST_DUMPSYS_ON_STALE_UI` и категория события `switcher_foreground_trusted_dumpsys` едины во всех тасках и совпадают со спеком. Имена helper'ов тестов (`_make_open_app_stub`, `_adb_dumpsys_response`, `_ui_dump_response`, `_extract_log_meta_categories`) — из существующего файла.

> Примечание о деривации от спека: спек §3 показывал kill-switch как переменную `_TRUST_DUMPSYS_ON_STALE_UI`; план реализует тот же env `SWITCHER_TRUST_DUMPSYS_ON_STALE_UI` через inline `os.getenv` (паттерн codebase, account_switcher.py:1033) — функционально эквивалентно, удобнее для `monkeypatch.setenv` в тестах. Catch-up loop остаётся 3×0.8с (минимальный дифф); спек писал «~0.7с» в пределах допуска.
