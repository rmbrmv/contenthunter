# YT Publish Stabilization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** За сегодня поднять success-rate YT publish-задач на phone #19 testbench до **≥8/10 подряд** + сделать так, чтобы любая ошибка свитчера на IG/TT/YT отображалась в `/publishing/publishing` UI понятным `error_code`, по которому оператор сразу видит что чинить.

**Architecture:** 4 атомарных трека в `account_switcher.py` + `publisher_base.py`: (B1) YT modal-dismiss + picker-scroll на `yt_3_open_accounts` blocked, (B2) detection «Требуется действие» rows → `yt_block` JSONB на `factory_reg_accounts`, (B3) canonical error_code namespace + UI status display, (B4) 2 atomic side-fixes (`_vision_read_current_account` HTTPS bug, `_resolve_single_account_mode` import-path). 5 commits в testbench → cherry-pick в prod → docs commit в contenthunter. Spec: `.ai-factory/specs/2026-04-27-yt-publish-stabilization-design.md`.

**Tech Stack:** Python (autowarm), pytest, psycopg2, ADB, PM2, Postgres (`openclaw:openclaw123@localhost:5432`), Node.js (`server.js`), vanilla JS/HTML (`public/index.html`).

---

## Settings

- **Testing:** yes — TDD (red-green-commit) для B1/B2/B4. B3 — pre-flight grep + параллельная правка тестов и кода. Smoke на phone #19 после каждого фикса.
- **Logging:** verbose — каждая failure-ветка свитчера пишет `_record_event(type='error', reason=<canonical>)`. INFO-логи для modal-dismissed / picker-scrolled.
- **Docs:** evidence обязательный (`.ai-factory/evidence/yt-publish-stabilization-20260427.md`).
- **Branch:** уже на `fix/testbench-publisher-base-imports-20260427` (feature branch с закоммиченным spec'ом). Новой ветки не создаём.

## Контекст

Spec уже описывает root cause полностью (см. `.ai-factory/specs/2026-04-27-yt-publish-stabilization-design.md` секции 2.1-2.3). Краткая выжимка для исполнителя:

- Phone #19 testbench, 2 YT-аккаунта: `makiavelli-o2u` (4/4 done) и `Инакент-т2щ` (4/4 failed `publish_failed_generic`).
- UI dump на failed Инакент содержит `text="Не удалось войти в аккаунт"` + button `text="Войдите в аккаунт"` — модалка от **другого** разлогиненного аккаунта `vera.smith8872...`.
- По bug-report'у пользователя (`sources/bugs/inbox/2026-04-27T160030Z-...`) workflow: back-press → wait modal gone → scroll picker → tap target.
- В picker есть row с indicator `«Требуется действие. Нажмите, чтобы войти»` рядом с разлогиненными gmail'ами — это маркер для авто-detection.

## File Structure

| Файл | Изменение | Размер | Задача |
|---|---|---|---|
| `account_switcher.py` | modify (~80 строк) | YT modal-dismiss + scroll + «Требуется действие» detect + canonical reason rename + vision HTTPS fix | T2-T6, T7 |
| `publisher_base.py` | modify (~10 строк) | error_code mapping + import _resolve_single_account_mode | T6, T7 |
| `tests/test_switcher_youtube.py` | modify (~150 строк новых) | unit-тесты B1+B2+B3-YT | T2, T3, T6 |
| `tests/test_account_switcher.py` | modify (~80 строк новых) | unit-тесты B3 IG/TT + B4.1 vision | T6, T7 |
| `tests/test_publisher_imports.py` | modify (~10 строк) | runtime-flavor test для B4.2 | T7 |
| `triage_classifier.py` | modify (~10 строк) | reason читатели после rename | T6 |
| `agent_diagnose.py` | modify (~10 строк) | reason читатели после rename | T6 |
| `server.js` (autowarm) | проверить, при необходимости modify | error_code в payload (уже есть в schema) | T6 |
| `public/index.html` | modify (~15 строк) | error_code в task-list + task-page header | T6 |

## Корневые причины (одной фразой каждая)

| Bug | Где |
|---|---|
| YT modal blocks picker | `account_switcher.py` YT path — нет `_dismiss_login_modal_if_present()` хелпера |
| Логированный аккаунт молча роняет публикации других на этом устройстве | `parse_account_list` YT-mode не детектит `«Требуется действие»` маркер |
| Оператор не понимает причину failed-task | reason names неконсистентны, UI не показывает `error_code` явно |
| `vision_current_account` падает с HTTPS path | `account_switcher.py:3079` пытается открыть S3 URL как локальный файл |
| `_resolve_single_account_mode is not defined` log noise | `publisher_base.py:1324` — отсутствующий import после publisher.py split |

## Scope

**В scope:** B1, B2, B3, B4.1, B4.2 + acceptance smoke + prod sync + docs.

**НЕ в scope:**
- Re-auth `vera.smith8872...@gmail.com` (физическое действие пользователя).
- Расширение vision-detection на каждый hang-point (отдельная сессия).
- Prod gmail-coverage backfill для оставшихся 51 аккаунта.
- TT/IG specific switcher баги (B1132, B1330) — только error_code rename (B3), не root-cause fix.

---

## Tasks

### Task 1: Pre-flight — verify environment

**Files:**
- Read-only: pm2 list, env, БД connection, phone #19 ADB.

- [ ] **Step 1: Verify pm2 processes online**

```bash
sudo pm2 list | grep -E 'autowarm|autowarm-testbench'
```

Expected: обе записи `online`, `autowarm-testbench` пид > 0.

- [ ] **Step 2: Verify ANTHROPIC_API_KEY available для autowarm-testbench process**

```bash
sudo cat /proc/$(sudo pm2 jlist | python3 -c 'import json,sys; print([p["pid"] for p in json.load(sys.stdin) if p["name"]=="autowarm-testbench"][0])')/environ | tr '\0' '\n' | grep -E 'ANTHROPIC|GROQ|LAOZHANG' | head -5
```

Expected: либо `ANTHROPIC_API_KEY=sk-ant-...` уже есть, либо его нет — в любом случае фиксируем результат.

Если **нет** → добавить в ecosystem config:
```bash
sudo grep -l 'autowarm-testbench' /root/.openclaw/workspace-genri/autowarm/ecosystem*.js /root/.pm2/dump.pm2 2>/dev/null
```

Решение принять в Step 5: добавить env через `sudo pm2 set autowarm-testbench:ANTHROPIC_API_KEY <value>` или через ecosystem.

- [ ] **Step 3: Verify Postgres reachable + schema**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "SELECT count(*) FROM publish_tasks WHERE device_serial='RF8YA0W57EP' AND platform='YouTube' AND updated_at > NOW() - INTERVAL '24 hours';"
```

Expected: numeric output (count за 24h).

- [ ] **Step 4: Verify phone #19 ADB reachable**

Phone #19 = `device_serial=RF8YA0W57EP` через raspberry 7 (см. spec 2.1). Per memory `reference_adb_remote_server_mode.md` доступ через remote adb-server:

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -t -A -F'|' -c "SELECT rp.host, rp.port FROM raspberry_port rp WHERE rp.raspberry_number=7;"
```

Затем:
```bash
adb -H <host> -P <port> -s RF8YA0W57EP shell echo OK
```

Expected: `OK`. Если timeout — fallback phone #171 (raspberry 8, `RF8Y90GCWWL`) и пометить в evidence.

- [ ] **Step 5: Sync ANTHROPIC_API_KEY in pm2 env if missing**

Если Step 2 показал, что ключа нет в env autowarm-testbench:

```bash
sudo cp ~/secrets/anthropic.env /tmp/anthropic.env.tmp
sudo bash -c '. /tmp/anthropic.env.tmp && pm2 restart autowarm-testbench --update-env --env ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY'
sudo rm /tmp/anthropic.env.tmp
```

Если ключ уже есть → Step 5 skip.

Verify ещё раз:
```bash
sudo cat /proc/$(sudo pm2 jlist | python3 -c 'import json,sys; print([p["pid"] for p in json.load(sys.stdin) if p["name"]=="autowarm-testbench"][0])')/environ | tr '\0' '\n' | grep ANTHROPIC_API_KEY
```

Expected: видим `ANTHROPIC_API_KEY=sk-ant-api03-...`.

- [ ] **Step 6: Snapshot baseline metrics**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw <<'SQL' > /tmp/yt-baseline-$(date +%Y%m%dT%H%M%S).txt
SELECT id, account, status, error_code,
       screen_record_url IS NOT NULL AS has_url,
       to_char(updated_at,'HH24:MI') AS hh
FROM publish_tasks
WHERE device_serial='RF8YA0W57EP' AND platform='YouTube'
  AND updated_at > NOW() - INTERVAL '24 hours'
ORDER BY id DESC LIMIT 30;
SQL
```

Сохранить путь файла для evidence T9.

**Commit (preflight):** ничего, только evidence-снимок.

---

### Task 2: B1 — YT modal-dismiss helper (TDD)

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/account_switcher.py` (добавить `_detect_login_modal()` + `_dismiss_login_modal_if_present()` хелперы; ничего пока не звать).
- Test: `/home/claude-user/autowarm-testbench/tests/test_switcher_youtube.py` (новый кейс).

- [ ] **Step 1: Add failing test `test_yt_login_modal_detection`**

В конец `tests/test_switcher_youtube.py` добавить:

```python
def test_yt_login_modal_detection_positive(parse_ui_dump):
    """Modal с текстом 'Не удалось войти в аккаунт' должен детектиться."""
    # UI dump из task1244 — точный фрагмент модалки
    xml = '''<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" package="com.google.android.youtube" bounds="[133,951][947,1350]">
    <node text="Не удалось войти в аккаунт" class="android.widget.TextView" bounds="[178,1047][902,1108]" />
    <node text="Войдите в аккаунт" class="android.widget.Button" clickable="true" bounds="[460,1142][868,1294]" />
  </node>
</hierarchy>'''
    elements = parse_ui_dump(xml)
    from account_switcher import _detect_login_modal
    assert _detect_login_modal(elements) is True


def test_yt_login_modal_detection_negative(parse_ui_dump):
    """Открытый picker без модалки → False."""
    xml = '''<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node text="Аккаунты" class="android.widget.TextView" />
  <node text="makiavelli" class="android.widget.TextView" />
  <node text="makiavelli206@gmail.com" class="android.widget.TextView" />
</hierarchy>'''
    elements = parse_ui_dump(xml)
    from account_switcher import _detect_login_modal
    assert _detect_login_modal(elements) is False
```

- [ ] **Step 2: Run tests — should fail with ImportError**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py::test_yt_login_modal_detection_positive tests/test_switcher_youtube.py::test_yt_login_modal_detection_negative -v
```

Expected: FAIL — `ImportError: cannot import name '_detect_login_modal'`.

- [ ] **Step 3: Implement `_detect_login_modal()` in account_switcher.py**

Найти место где живут другие top-level helper'ы (рядом с `get_current_account_from_profile`, ~`account_switcher.py:416`). Добавить:

```python
import re

_LOGIN_MODAL_TEXTS = (
    'не удалось войти в аккаунт',
    "couldn't sign in",
    'sign in to your account',
)
_LOGIN_MODAL_BUTTONS = (
    'войдите в аккаунт',
    'sign in',
)


def _detect_login_modal(elements: list) -> bool:
    """Возвращает True если на экране модалка YT 'Не удалось войти в аккаунт'.

    Признаки (любой из):
      - Element с text матчащим _LOGIN_MODAL_TEXTS (TextView).
      - Кликабельная Button с text матчащим _LOGIN_MODAL_BUTTONS.
    """
    for el in elements:
        text = (el.get('text') or '').strip().lower()
        if not text:
            continue
        if any(t in text for t in _LOGIN_MODAL_TEXTS):
            return True
        if el.get('clickable') and any(b in text for b in _LOGIN_MODAL_BUTTONS):
            return True
    return False
```

- [ ] **Step 4: Run tests — should pass**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py::test_yt_login_modal_detection_positive tests/test_switcher_youtube.py::test_yt_login_modal_detection_negative -v
```

Expected: 2 passed.

- [ ] **Step 5: Add failing test `test_dismiss_login_modal_with_back_press`**

```python
def test_dismiss_login_modal_calls_back_then_polls(monkeypatch):
    """Когда modal detected — отправить KEYCODE_BACK и опрашивать UI до тех пор пока модалки нет."""
    from account_switcher import AccountSwitcher
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.serial = 'RF8YA0W57EP'
    sw.adb_host = '127.0.0.1'
    sw.adb_port = 5037
    sw.task_id = 9999
    sw.events_logged = []
    sw._record_event = lambda **kw: sw.events_logged.append(kw)

    back_calls = []
    def fake_run_adb_shell(serial, cmd, **_):
        back_calls.append(cmd)
        return ('', 0)
    monkeypatch.setattr('account_switcher._run_adb_shell', fake_run_adb_shell)

    # 1-я попытка: модалка, 2-я: чисто
    dump_attempts = iter([
        ('<root><node text="Войдите в аккаунт" clickable="true"/></root>', True),
        ('<root><node text="Аккаунты"/><node text="makiavelli"/></root>', True),
    ])
    monkeypatch.setattr('account_switcher._dump_ui',
                        lambda *_a, **_kw: next(dump_attempts))

    result = sw._dismiss_login_modal_if_present(step_name='yt_3_open_accounts')
    assert result is True
    assert back_calls == ['input keyevent KEYCODE_BACK']
    reasons = [e['reason'] for e in sw.events_logged]
    assert 'yt_login_modal_detected' in reasons
    assert 'yt_login_modal_dismissed' in reasons
```

- [ ] **Step 6: Run test — should fail**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py::test_dismiss_login_modal_calls_back_then_polls -v
```

Expected: FAIL — `AttributeError: ...has no attribute '_dismiss_login_modal_if_present'`.

- [ ] **Step 7: Implement `_dismiss_login_modal_if_present` method**

В классе `AccountSwitcher` (рядом с другими private методами, например после `_vision_read_current_account` ~`:3077`):

```python
def _dismiss_login_modal_if_present(self, step_name: str,
                                     max_attempts: int = 5,
                                     poll_delay: float = 0.5) -> bool:
    """Если на экране модалка 'Не удалось войти в аккаунт' — отправить BACK
    и поллить UI пока модалка не уйдёт.

    Returns True если modal был detected И dismissed.
    Returns False если модалки не было (no-op).
    """
    import time
    xml, ok = _dump_ui(self.serial, self.adb_host, self.adb_port)
    if not ok:
        return False
    elements = parse_ui_dump(xml)
    if not _detect_login_modal(elements):
        return False

    self._record_event(type='info', reason='yt_login_modal_detected',
                       message=f'login modal at {step_name}')

    # Pre-back guard: убедимся что мы всё ещё в YouTube
    focus = _run_adb_shell(self.serial,
                           'dumpsys window windows | grep -E "mCurrentFocus|mFocusedApp"',
                           host=self.adb_host, port=self.adb_port)[0]
    if 'com.google.android.youtube' not in focus:
        log.warning(f'[switcher] login modal detected but YT not focused; '
                    f'focus={focus!r} — skipping dismiss to avoid leaving app')
        return False

    _run_adb_shell(self.serial, 'input keyevent KEYCODE_BACK',
                   host=self.adb_host, port=self.adb_port)

    for attempt in range(1, max_attempts + 1):
        time.sleep(poll_delay)
        xml, ok = _dump_ui(self.serial, self.adb_host, self.adb_port)
        if not ok:
            continue
        elements = parse_ui_dump(xml)
        if not _detect_login_modal(elements):
            self._record_event(type='info', reason='yt_login_modal_dismissed',
                               message=f'attempts={attempt}')
            return True

    self._record_event(type='warning', reason='yt_login_modal_persisted',
                       message=f'still present after {max_attempts} polls')
    return False
```

- [ ] **Step 8: Run test — should pass**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py::test_dismiss_login_modal_calls_back_then_polls -v
```

Expected: 1 passed.

- [ ] **Step 9: Verify full test_switcher_youtube.py still green**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py -v
```

Expected: ВСЕ pass (17 предыдущих + 3 новых = 20).

- [ ] **Step 10: Commit (B1 helpers — еще не вызываются, не ломает прод)**

```bash
cd /home/claude-user/autowarm-testbench && git add account_switcher.py tests/test_switcher_youtube.py
git commit -m "feat(switch): _detect_login_modal + _dismiss_login_modal_if_present helpers"
```

---

### Task 3: B1 — Wire modal-dismiss into YT switch flow + scroll-loop

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/account_switcher.py` (`_switch_yt` или эквивалент — место после `yt_3_open_accounts` UI dump).
- Test: `/home/claude-user/autowarm-testbench/tests/test_switcher_youtube.py`.

- [ ] **Step 1: Locate the current YT switch flow + verify ADB helpers**

```bash
cd /home/claude-user/autowarm-testbench && grep -n "yt_3_open_accounts\|yt_4_pick_account\|_switch_yt\|def parse_account_list\|def _dump_ui\|def _run_adb_shell" account_switcher.py | head -20
```

Зафиксировать **точные** имена и line numbers следующих хелперов (Step 7 ниже использует их):
- `_dump_ui(serial, host, port)` — возвращает `(xml_str, ok_bool)` или подобное.
- `_run_adb_shell(serial, cmd, host, port)` — выполняет ADB shell command.
- `parse_ui_dump(xml_str)` — XML → list of element dicts.

Если имена отличаются — adapt'нуть код в Step 7 и тесты в Steps 2/5 под реальные. Тестовые `monkeypatch.setattr('account_switcher.<name>', ...)` должны использовать те же имена.

- [ ] **Step 2: Add failing test `test_yt_picker_scroll_finds_target_below_viewport`**

В `tests/test_switcher_youtube.py`:

```python
def test_yt_picker_scroll_finds_target_below_viewport(monkeypatch, parse_ui_dump):
    """Если target не виден в первом scan'е picker'а, scroll-loop должен
    свайпать пока target не появится (max 3 stale rounds)."""
    from account_switcher import AccountSwitcher
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.serial = 'X'
    sw.adb_host = '127.0.0.1'
    sw.adb_port = 5037
    sw.task_id = 1
    sw.events_logged = []
    sw._record_event = lambda **kw: sw.events_logged.append(kw)
    sw._yt_gmail_hint = 'inakent06@gmail.com'

    # 3 свайпа подряд — target в 3-м.
    dump_seq = iter([
        '<root><node text="makiavelli"/><node text="makiavelli206@gmail.com"/></root>',
        '<root><node text="other"/><node text="other@gmail.com"/></root>',
        '<root><node text="Инакент"/><node text="inakent06@gmail.com" '
        'bounds="[100,800][900,860]"/></root>',
    ])
    monkeypatch.setattr('account_switcher._dump_ui',
                        lambda *_a, **_kw: (next(dump_seq), True))
    swipes = []
    monkeypatch.setattr('account_switcher._run_adb_shell',
                        lambda s, c, **kw: (swipes.append(c), ('', 0))[1])

    found = sw._scroll_picker_for_target('инакент-т2щ', max_stale=3)
    assert found is True
    # Должно быть >=2 swipe'а до того как target нашёлся
    assert sum(1 for c in swipes if 'swipe' in c) >= 2
    assert any(e['reason'] == 'yt_picker_scrolled' for e in sw.events_logged)
```

- [ ] **Step 3: Run test — should fail**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py::test_yt_picker_scroll_finds_target_below_viewport -v
```

Expected: FAIL — `AttributeError: ...no attribute '_scroll_picker_for_target'`.

- [ ] **Step 4: Implement `_scroll_picker_for_target`**

В классе `AccountSwitcher`:

```python
def _scroll_picker_for_target(self, target_handle: str,
                               max_stale: int = 3,
                               swipe_y_start: int = 900,
                               swipe_y_end: int = 400) -> bool:
    """Scroll picker (swipe up) пока target_handle не появится в UI.

    Args:
        target_handle: lowercase handle (or gmail prefix) который ищем.
        max_stale: сколько раз подряд скроллить без новой info до выхода.

    Returns True если target найден, False если scroll-budget exhausted.
    """
    import time
    seen_keys = set()
    stale_rounds = 0
    target_lc = target_handle.lower().strip()

    for attempt in range(1, max_stale * 3 + 1):
        xml, ok = _dump_ui(self.serial, self.adb_host, self.adb_port)
        if not ok:
            continue
        elements = parse_ui_dump(xml)

        # Нашли target?
        for el in elements:
            text = (el.get('text') or '').lower()
            if not text:
                continue
            # Match по handle ИЛИ по gmail prefix
            if target_lc in text or (
                self._yt_gmail_hint and self._yt_gmail_hint.lower() in text
            ):
                self._record_event(type='info', reason='yt_picker_target_found',
                                   message=f'attempt={attempt}')
                return True

        # Зафиксировать новые row'ы по их text-сигнатуре
        round_keys = frozenset(
            (el.get('text') or '').lower() for el in elements
            if el.get('text')
        )
        if round_keys.issubset(seen_keys):
            stale_rounds += 1
        else:
            stale_rounds = 0
            seen_keys |= round_keys

        if stale_rounds >= max_stale:
            self._record_event(type='warning', reason='yt_picker_scroll_exhausted',
                               message=f'rounds={attempt} stale={stale_rounds}')
            return False

        # Свайп вверх
        _run_adb_shell(self.serial,
                       f'input swipe 540 {swipe_y_start} 540 {swipe_y_end} 300',
                       host=self.adb_host, port=self.adb_port)
        self._record_event(type='info', reason='yt_picker_scrolled',
                           message=f'attempt={attempt}')
        time.sleep(0.4)

    return False
```

- [ ] **Step 5: Run test — should pass**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py::test_yt_picker_scroll_finds_target_below_viewport -v
```

Expected: 1 passed.

- [ ] **Step 6: Wire `_dismiss_login_modal_if_present` and `_scroll_picker_for_target` into YT switch flow**

Найти текущее место где происходит `yt_3_open_accounts` UI dump и проверка перехода в picker (определено в Step 1). Псевдокод изменения:

```python
# ДО:
xml, _ = _dump_ui(...)
self._log_ui_dump(xml, 'yt_3_open_accounts', usable=is_usable(xml))
# ... сразу tap на target

# ПОСЛЕ:
xml, _ = _dump_ui(...)
usable = is_usable(xml)
self._log_ui_dump(xml, 'yt_3_open_accounts', usable=usable)
if not usable:
    if self._dismiss_login_modal_if_present('yt_3_open_accounts'):
        # модалка ушла — заново снять dump
        xml, _ = _dump_ui(...)
        usable = is_usable(xml)
        self._log_ui_dump(xml, 'yt_3_open_accounts_after_modal', usable=usable)
if not usable:
    # picker всё равно не открылся — старая логика fail
    self._record_event(type='error', reason='yt_picker_failed_to_open',
                       message='UI dump unusable after modal dismiss attempts')
    return SwitchResult(success=False, final_step='yt_3_open_accounts', ...)

# scroll если target не виден сразу
if not self._target_visible_in_picker(target):
    if not self._scroll_picker_for_target(target):
        self._record_event(type='error',
                           reason='yt_target_not_in_picker_after_scroll',
                           message=f'target={target} gmail={self._yt_gmail_hint}')
        return SwitchResult(success=False,
                            final_step='yt_4_pick_account', ...)
```

Использовать **точные** имена методов и lines из Step 1; псевдокод выше — структура.

- [ ] **Step 7: Run full switcher tests**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py tests/test_account_switcher.py -v
```

Expected: всё green. Если что-то упало — это регрессия от Step 6, fix перед commit.

- [ ] **Step 8: Smoke-trigger fail на phone #19 (Инакент-т2щ)**

Через testbench UI на `https://delivery.contenthunter.ru/` инжектировать testbench publish-task для `Инакент-т2щ` на phone #19, ИЛИ напрямую SQL:

```sql
INSERT INTO publish_tasks (device_serial, adb_port, raspberry, platform,
                           account, project, media_path, media_type,
                           caption, status, testbench, created_at, updated_at)
VALUES ('RF8YA0W57EP', <port>, 7, 'YouTube', 'Инакент-т2щ', '<project>',
        '/test_media/dummy_short.mp4', 'video', 'smoke', 'pending', true,
        NOW(), NOW())
RETURNING id;
```

Дождаться `status` ∈ {`done`, `failed`} (≤ 5 минут). Проверить:

```sql
SELECT id, status, error_code, jsonb_array_length(events) AS n
FROM publish_tasks WHERE id=<X>;
```

Expected: `status=done` ИЛИ `status=failed AND error_code IN ('yt_target_not_in_picker_after_scroll', 'yt_picker_failed_to_open')` (НЕ `publish_failed_generic`, НЕ `unknown`).

В events должны быть видны: `yt_login_modal_detected` → `yt_login_modal_dismissed`.

- [ ] **Step 9: Commit**

```bash
cd /home/claude-user/autowarm-testbench && git add account_switcher.py tests/test_switcher_youtube.py
git commit -m "fix(switch): YT modal-dismiss + picker-scroll on yt_3_open_accounts blocked"
```

---

### Task 4: B2 — Detect "Требуется действие" rows + write `yt_block`

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/account_switcher.py` (`parse_account_list` YT-mode + new `_mark_yt_logout_in_factory`).
- Test: `/home/claude-user/autowarm-testbench/tests/test_switcher_youtube.py`.

- [ ] **Step 1: Verify `factory_reg_accounts.yt_block` column exists**

```bash
PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -c "\d factory_reg_accounts" | grep -E 'gmail|yt_block|ig_block|tt_block'
```

Expected: `yt_block | jsonb` (per memory `project_account_blocks.md`). Если нет — STOP и сообщить (миграция вне scope).

- [ ] **Step 2: Add failing test `test_parse_account_list_marks_logout_account`**

```python
def test_parse_account_list_marks_logout_account(monkeypatch, parse_ui_dump):
    """В picker'е row с indicator 'Требуется действие' и gmail 'vera.smith...'
    должна вызвать UPDATE factory_reg_accounts.yt_block."""
    from account_switcher import AccountSwitcher
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.task_id = 7777

    # 3 row'а, один с indicator
    xml = '''<?xml version='1.0'?>
<hierarchy>
  <node clickable="true" bounds="[0,200][1080,400]">
    <node text="makiavelli" bounds="[100,210][900,260]" />
    <node text="makiavelli206@gmail.com" bounds="[100,260][900,320]" />
  </node>
  <node clickable="true" bounds="[0,400][1080,600]">
    <node text="Инакент" bounds="[100,410][900,460]" />
    <node text="inakent06@gmail.com" bounds="[100,460][900,520]" />
  </node>
  <node clickable="true" bounds="[0,600][1080,800]">
    <node text="vera.smith8872@gmail.com" bounds="[100,610][900,660]" />
    <node text="Требуется действие. Нажмите, чтобы войти" bounds="[100,660][900,720]" />
  </node>
</hierarchy>'''

    marked = []
    monkeypatch.setattr(
        'account_switcher._mark_yt_logout_in_factory',
        lambda gmail, task_id: marked.append((gmail, task_id))
    )

    rows = sw._parse_account_list(parse_ui_dump(xml), platform='YouTube')

    assert len(rows) == 3  # все 3 row'а возвращены
    assert marked == [('vera.smith8872@gmail.com', 7777)]
```

- [ ] **Step 3: Run test — should fail**

Expected: FAIL — отсутствие `_mark_yt_logout_in_factory` или `_parse_account_list` сигнатуры.

- [ ] **Step 4: Implement `_mark_yt_logout_in_factory` (top-level helper)**

```python
import psycopg2

_LOGOUT_MARKERS = re.compile(
    r'требуется\s+действие|нажмите.*чтобы\s+войти|tap\s+to\s+sign\s+in',
    re.IGNORECASE,
)


def _mark_yt_logout_in_factory(gmail: str, task_id: int | None) -> None:
    """UPDATE factory_reg_accounts.yt_block для gmail с пометкой logout.

    Idempotent — повторный call для того же gmail обновит detected_at и task_id.
    """
    if not gmail or '@' not in gmail:
        return
    sql = """
        UPDATE factory_reg_accounts
        SET yt_block = jsonb_set(
            COALESCE(yt_block, '{}'::jsonb),
            '{logout}',
            jsonb_build_object(
                'detected_at', NOW(),
                'reason', 'yt_login_required_in_picker',
                'evidence_task_id', %s
            ),
            true
        )
        WHERE gmail = %s
    """
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (task_id, gmail))
                conn.commit()
        log.info(f'[switcher] yt_block marked for gmail={gmail} task={task_id}')
    except Exception as e:
        log.warning(f'[switcher] _mark_yt_logout_in_factory failed: {e}')
```

(Используется существующий `_db_conn` хелпер — найти его рядом с другими db helper'ами в `account_switcher.py`. Если такого нет — позаимствовать паттерн из `parse_account_list`.)

- [ ] **Step 5: Modify `_parse_account_list` (YT-mode) to detect logout rows**

Найти текущую реализацию `parse_account_list` или эквивалент (`account_switcher.py:459-492` per spec). Добавить guard'ы:

```python
def _parse_account_list(self, elements, platform: str) -> list:
    rows = []
    # ... существующая логика построения rows ...

    if platform == 'YouTube':
        # Triple-guard для anti-false-positive (per spec R2):
        # text внутри picker-row bounds + clickable=true ancestor + handle/gmail
        for row in rows:
            row_y_min, row_y_max = row['bounds_y']  # tuple from parse
            for el in elements:
                text = (el.get('text') or '').strip()
                if not text or not _LOGOUT_MARKERS.search(text):
                    continue
                el_y = _center_y(el)
                if not (row_y_min - 120 <= el_y <= row_y_max + 120):
                    continue
                # Найден маркер в bounds row'а
                gmail = row.get('gmail')
                if gmail:
                    _mark_yt_logout_in_factory(gmail, self.task_id)
                    self._record_event(
                        type='warning', reason='yt_account_logout_marked',
                        message=f'gmail={gmail}',
                        meta={'gmail': gmail, 'target_unaffected': True},
                    )
                break

    return rows
```

(Adapt to actual signature/structure of `parse_account_list`.)

- [ ] **Step 6: Run test — should pass**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py::test_parse_account_list_marks_logout_account -v
```

Expected: 1 passed.

- [ ] **Step 7: Add anti-false-positive test `test_logout_text_outside_picker_row_does_not_mark`**

```python
def test_logout_text_outside_picker_row_does_not_mark(monkeypatch, parse_ui_dump):
    """Текст 'Требуется действие' где-то в notification, а не в picker-row, —
    НЕ должен помечать никакой gmail."""
    from account_switcher import AccountSwitcher
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.task_id = 1

    xml = '''<?xml version='1.0'?>
<hierarchy>
  <node text="Требуется действие в notification!" bounds="[100,50][900,100]" />
  <node clickable="true" bounds="[0,400][1080,600]">
    <node text="Инакент" bounds="[100,410][900,460]" />
    <node text="inakent06@gmail.com" bounds="[100,460][900,520]" />
  </node>
</hierarchy>'''

    marked = []
    monkeypatch.setattr('account_switcher._mark_yt_logout_in_factory',
                        lambda *a: marked.append(a))
    sw._parse_account_list(parse_ui_dump(xml), platform='YouTube')
    assert marked == []
```

- [ ] **Step 8: Run all switcher tests**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_switcher_youtube.py -v
```

Expected: всё green. (Existing 17 + B1 new 3 + B2 new 2 = 22.)

- [ ] **Step 9: Smoke на phone #19 — наблюдать `yt_block`**

Запустить ещё одну Инакент-задачу (как в Task 3 Step 8). После её завершения:

```sql
SELECT gmail, yt_block FROM factory_reg_accounts
WHERE gmail = 'vera.smith8872@gmail.com'  -- замените на реальный gmail из picker'а
   OR yt_block ? 'logout';
```

Expected: видим row с `yt_block.logout = {"detected_at": ..., "reason": "yt_login_required_in_picker", "evidence_task_id": <id>}`.

- [ ] **Step 10: Commit**

```bash
cd /home/claude-user/autowarm-testbench && git add account_switcher.py tests/test_switcher_youtube.py
git commit -m "feat(switch): mark yt_block on Требуется действие rows in YT picker"
```

---

### Task 5: B4.1 — `_vision_read_current_account` HTTPS-URL fix

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/account_switcher.py:3079` — внутри `_vision_read_current_account`.
- Test: `/home/claude-user/autowarm-testbench/tests/test_account_switcher.py`.

(Делаем перед B3 namespace, потому что atomic and isolated — снимает шум в логах что мешает B3 audit'у.)

- [ ] **Step 1: Add failing test `test_vision_read_current_account_downloads_https_shot`**

В `tests/test_account_switcher.py`:

```python
def test_vision_read_current_account_downloads_https_shot(monkeypatch):
    """Если _maybe_screenshot вернул HTTPS URL, _vision_read_current_account
    должен скачать shot через urllib.request.urlopen с timeout=10 и сохранить
    в /tmp/autowarm_vision_cache/ перед использованием.

    Тест проверяет ТОЛЬКО шаг скачивания (downstream vision API call мокается
    через прерывание исключением, чтобы не зависеть от его точной сигнатуры)."""
    from account_switcher import AccountSwitcher
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.task_id = 1
    sw._record_event = lambda **kw: None
    sw._maybe_screenshot = lambda step: 'https://save.gengo.io/x.png'

    download_calls = []

    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            pass
        def read(self, *_a):
            return b'fake png data'

    def fake_urlopen(url, timeout):
        download_calls.append((url, timeout))
        return _FakeResp()

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    # shutil.copyfileobj(resp, file) → пишем «fake png» в локальный файл
    import shutil as _shutil
    monkeypatch.setattr(_shutil, 'copyfileobj',
                        lambda src, dst: dst.write(b'fake png data'))

    # Вызвать. Если downstream vision API упадёт после успешного скачивания —
    # это всё равно докажет что HTTPS-handling case прошёл (urlopen вызван).
    try:
        sw._vision_read_current_account('yt_2_profile_screen')
    except Exception:
        pass

    assert download_calls, 'urllib.request.urlopen НЕ был вызван для HTTPS shot'
    assert download_calls[0][0] == 'https://save.gengo.io/x.png'
    assert download_calls[0][1] == 10  # timeout
```

- [ ] **Step 2: Run test — should fail (or actually fail with HTTPS error)**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_account_switcher.py::test_vision_read_current_account_downloads_https_shot -v
```

Expected: FAIL — текущий код пытается открыть URL как файл и/или вообще не маршрутизирует через `_vision_extract_username`.

- [ ] **Step 3: Implement HTTPS handling in `_vision_read_current_account`**

В `account_switcher.py`, в начале `_vision_read_current_account` (`:3079` после `shot = self._maybe_screenshot(...)`):

```python
# Если screenshot уже залит на S3 — скачать обратно во временный файл
# для vision API. Локальный кэш в /tmp/autowarm_vision_cache.
if isinstance(shot, str) and shot.startswith(('http://', 'https://')):
    import hashlib
    import shutil
    import urllib.request
    from pathlib import Path

    cache_dir = Path('/tmp/autowarm_vision_cache')
    cache_dir.mkdir(exist_ok=True)
    local_path = cache_dir / f'{hashlib.md5(shot.encode()).hexdigest()}.png'
    if not local_path.exists():
        try:
            with urllib.request.urlopen(shot, timeout=10) as resp, \
                 open(local_path, 'wb') as f:
                shutil.copyfileobj(resp, f)
        except Exception as e:
            log.warning(f'[switcher] vision shot download failed: {e}')
            return None
    shot = str(local_path)
```

- [ ] **Step 4: Run test — should pass**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_account_switcher.py::test_vision_read_current_account_downloads_https_shot -v
```

Expected: 1 passed.

- [ ] **Step 5: Run full switcher test suite**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_account_switcher.py tests/test_switcher_youtube.py -v
```

Expected: всё green.

- [ ] **Step 6: Commit**

```bash
cd /home/claude-user/autowarm-testbench && git add account_switcher.py tests/test_account_switcher.py
git commit -m "fix(switch): vision current_account handles HTTPS shot path"
```

---

### Task 6: B4.2 — `_resolve_single_account_mode` import-path noise

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/publisher_base.py:1324` — добавить top-level import.
- Test: `/home/claude-user/autowarm-testbench/tests/test_publisher_imports.py`.

- [ ] **Step 1: Pre-fix diagnostic**

```bash
cd /home/claude-user/autowarm-testbench && python3 -c "from publisher_base import _resolve_single_account_mode" 2>&1
```

Если: `ImportError: cannot import name '_resolve_single_account_mode' from 'publisher_base'` → top-level import отсутствует, simple fix.

Если: SUCCESS, но pm2 logs всё равно показывают `name '_resolve_single_account_mode' is not defined` → искать lazy-import / circular в runtime path. Зафиксировать diagnostic в evidence перед фиксом.

- [ ] **Step 2: Add runtime-flavor failing test**

В `tests/test_publisher_imports.py` добавить:

```python
def test_publisher_base_can_resolve_sa_mode_at_runtime():
    """publisher_base.py:1324 должен мочь вызвать _resolve_single_account_mode
    без NameError в runtime-flow (не только в test fixture)."""
    import publisher_base
    assert hasattr(publisher_base, '_resolve_single_account_mode'), (
        'publisher_base lacks _resolve_single_account_mode in module scope'
    )
    # Smoke call с safe args (функция должна вернуть tuple (sa_mode, sa_known))
    result = publisher_base._resolve_single_account_mode(
        task_id=0, serial='X', platform='YouTube', account='dummy'
    )
    assert isinstance(result, tuple) and len(result) == 2
```

- [ ] **Step 3: Run test — should fail**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_publisher_imports.py::test_publisher_base_can_resolve_sa_mode_at_runtime -v
```

Expected: FAIL.

- [ ] **Step 4: Apply fix in `publisher_base.py`**

В top-of-file imports добавить (или поднять existing import):

```python
from publisher import _resolve_single_account_mode
```

Если возникает `ImportError` из-за circular import (`publisher` импортирует `publisher_base`), то extract function в новый модуль `publisher_helpers.py`:

1. Создать `publisher_helpers.py` с переносом `_resolve_single_account_mode`.
2. В `publisher.py`: `from publisher_helpers import _resolve_single_account_mode`.
3. В `publisher_base.py`: `from publisher_helpers import _resolve_single_account_mode`.

- [ ] **Step 5: Run test — should pass**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_publisher_imports.py -v
```

Expected: всё green.

- [ ] **Step 6: Run full unit suite to catch regressions**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/ -v --timeout=30 2>&1 | tail -30
```

Expected: всё green (или предсуществующие fail'ы остались такими же, не новые).

- [ ] **Step 7: Commit**

```bash
cd /home/claude-user/autowarm-testbench && git add publisher_base.py publisher.py publisher_helpers.py tests/test_publisher_imports.py 2>/dev/null
git commit -m "fix(publisher): _resolve_single_account_mode import-path"
```

(Если `publisher_helpers.py` не создавался — просто `git add publisher_base.py tests/test_publisher_imports.py`.)

---

### Task 7: B3 — Cross-platform error_code namespace + UI status display

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/account_switcher.py` (rename'ы reason'ов в IG/TT/YT switch fail-ветках).
- Modify: `/home/claude-user/autowarm-testbench/publisher_base.py:1380-1390` (mapping reason → `task.error_code`).
- Modify: `/home/claude-user/autowarm-testbench/triage_classifier.py`, `agent_diagnose.py` (читатели старых reason'ов).
- Modify: `/home/claude-user/autowarm-testbench/server.js` — проверить, при необходимости добавить `error_code` в payload.
- Modify: `/home/claude-user/autowarm-testbench/public/index.html` — task-list строка + task-page header.
- Test: `tests/test_account_switcher.py`, `tests/test_switcher_youtube.py`.

- [ ] **Step 1: Audit — собрать все switch fail-paths**

```bash
cd /home/claude-user/autowarm-testbench && grep -nE "_record_event\(.*type=['\"]error['\"]|success=False|reason=['\"]" account_switcher.py | head -80
```

В новый файл `/tmp/yt-stab-audit-reasons.txt` сохранить таблицу:

```
file:line | platform | step | current_reason | proposed_canonical
account_switcher.py:1059 | IG | ig_3_pick      | switch_fail   | ig_target_not_in_picker
account_switcher.py:1457 | TT | tt_3_open_list | (none)        | tt_account_sheet_closed_before_parse
... и т.д. ...
```

Использовать таблицу из `.ai-factory/specs/2026-04-27-yt-publish-stabilization-design.md` секция 3.3 как источник canonical names.

- [ ] **Step 2: Audit downstream readers**

```bash
cd /home/claude-user/autowarm-testbench && grep -nE "reason\s*[=!]=|'<old_reason>'" triage_classifier.py agent_diagnose.py 2>&1 | head -40
```

Записать список **всех** старых reason'ов которые читатели упоминают. Это критический список — каждый из них должен либо остаться, либо быть обновлён в этом же commit'е (memory `feedback_cross_repo_schema_changes.md`).

- [ ] **Step 3: Add 7 failing tests, по одному на каждый canonical reason**

Для каждой из 7 строк таблицы 3.3 спека добавить unit-тест в `tests/test_account_switcher.py` (или `tests/test_switcher_youtube.py` для YT-specific). Шаблон:

```python
def test_<canonical_reason>_emitted_when_<scenario>(monkeypatch):
    """Когда <конкретное условие fail-ветки>, switcher должен emit-нуть
    _record_event(type='error', reason='<canonical_reason>') и вернуть
    SwitchResult с success=False, fail_reason='<canonical_reason>'."""
    from account_switcher import AccountSwitcher
    sw = AccountSwitcher.__new__(AccountSwitcher)
    sw.task_id = 1
    sw.serial = 'X'
    sw.adb_host = '127.0.0.1'
    sw.adb_port = 5037
    sw.events_logged = []
    sw._record_event = lambda **kw: sw.events_logged.append(kw)
    # ... setup для конкретного scenario (моки _dump_ui, _switch_yt branches, etc.) ...

    result = sw._switch_<platform>('target_handle')
    assert not result.success
    assert result.fail_reason == '<canonical_reason>'
    error_events = [e for e in sw.events_logged if e.get('type') == 'error']
    assert any(e['reason'] == '<canonical_reason>' for e in error_events)
```

7 кейсов (по одному):

| # | reason | platform | scenario для setup |
|---|---|---|---|
| 1 | `yt_picker_failed_to_open` | YT | `_dump_ui` всегда unusable, modal-dismiss возвращает False |
| 2 | `yt_target_not_in_picker_after_scroll` | YT | picker ok, scroll-loop возвращает False (target не найден) |
| 3 | `tt_account_sheet_closed_before_parse` | TT | первый dump показывает sheet, второй — sheet закрыт |
| 4 | `tt_target_not_on_device` | TT | parse_account_list не находит target в списке (account отсутствует) |
| 5 | `ig_target_not_in_picker` | IG | parse возвращает rows без target |
| 6 | `ig_picker_scroll_exhausted` | IG | scroll-loop возвращает False для IG path |
| 7 | `switch_failed_unspecified` | (любая) | force unhandled exception → fallback reason |

Для каждого — выписать конкретный setup в самом тесте (НЕ ссылаться на «аналогично Task N»). Если в существующем `tests/` есть helper типа `_make_test_switcher()` — использовать его; если нет — inline `AccountSwitcher.__new__(...)` как в шаблоне выше.

- [ ] **Step 4: Run tests — все 7 should fail**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/test_account_switcher.py -k "canonical_reason" -v
```

Expected: 7 failed.

- [ ] **Step 5: Apply rename'ы в `account_switcher.py`**

Для каждой строки из аудит-таблицы: заменить старый `reason='<old>'` на canonical, БЕЗ изменения других полей. Точечные правки.

Также убедиться что:
- В каждой fail-ветке вызывается `_record_event(type='error', reason=<canonical>, message=<descriptive>)`.
- `SwitchResult(success=False, final_step=<step>, fail_reason=<canonical>)` — canonical имя пробрасывается до результата.

- [ ] **Step 6: Update `publisher_base.py:1380-1390` — mapping в task.error_code**

Найти где `result.fail_reason` (или эквивалент) маппится в `task.error_code`. Гарантировать:

```python
# В success-ветке после _ensure_account:
task.error_code = result.fail_reason if not result.success else None
# Если fail_reason пустой — fallback:
if not result.success and not task.error_code:
    task.error_code = 'switch_failed_unspecified'
```

- [ ] **Step 7: Update downstream readers**

В `triage_classifier.py` и `agent_diagnose.py` — для каждого старого reason'а из Step 2 audit:
- Если читатель использует старое имя в logic (e.g. `if reason == 'switch_fail': ...`) → обновить на canonical.
- Если читатель собирает stats by reason → добавить mapping старое→новое для backward-compatibility ВНУТРИ читателя (на 1 неделю), затем cleanup. Пометить TODO с датой 2026-05-04.

- [ ] **Step 8: Update `index.html` — task-list error_code badge**

В `public/index.html`, найти block рендеринга task-list строки (`/api/publish/tasks` consumer). Добавить рядом со status:

```html
<span class="status-badge status-${task.status}">${task.status}</span>
${task.status === 'failed' && task.error_code
  ? `<small class="error-code">${task.error_code}</small>`
  : ''}
```

CSS (~5 строк, добавить в существующий style block):
```css
.error-code {
  display: inline-block;
  padding: 2px 6px;
  margin-left: 6px;
  background: #fee;
  border: 1px solid #fbb;
  border-radius: 3px;
  color: #c00;
  font-family: monospace;
  font-size: 11px;
}
```

- [ ] **Step 9: Update `index.html` — task-page error block**

Найти `pub-events` рендеринг в task-page modal (сейчас отображает `screen_record_url` и события). Добавить выше списка events:

```html
${data.error_code ? `
  <div class="task-error-banner" style="background:#fee;border-left:3px solid #c00;
                                        padding:10px;margin:10px 0;">
    <strong>Error:</strong> <code>${data.error_code}</code>
    ${firstErrorEvent ? ` — ${firstErrorEvent.message || firstErrorEvent.reason}` : ''}
  </div>
` : ''}
```

Где `firstErrorEvent = data.events.find(e => e.type === 'error')`.

- [ ] **Step 10: Verify `server.js` payload includes error_code**

```bash
grep -n "error_code\|pt\.\*" /home/claude-user/autowarm-testbench/server.js | head -20
```

Expected: `pt.*` в SELECT (что уже включает `error_code`). Если только конкретные колонки select'ятся — добавить `error_code` явно.

- [ ] **Step 11: Run всех тестов**

```bash
cd /home/claude-user/autowarm-testbench && pytest tests/ -v --timeout=30 2>&1 | tail -40
```

Expected: всё green (новые 7 + B1/B2/B4 = всё PASS, no regressions).

- [ ] **Step 12: Manual UI smoke**

Открыть https://delivery.contenthunter.ru/#publishing/publishing в браузере. Найти failed-task с новым error_code → удостовериться что:
- В строке списка виден badge с error_code (красный).
- При клике в task-page видно красный banner с error_code + message первого error event'а.

Если UI кэшируется — hard-refresh (Ctrl+Shift+R), Caddy раздаёт static с no-cache по конфигу (memory).

- [ ] **Step 13: Commit**

```bash
cd /home/claude-user/autowarm-testbench && git add account_switcher.py publisher_base.py triage_classifier.py agent_diagnose.py server.js public/index.html tests/
git commit -m "refactor(switch): canonical error_code namespace + UI status display"
```

---

### Task 8: Acceptance smoke — 10 testbench YT задач на phone #19

**Files:**
- Read-only: pm2 logs, БД.

- [ ] **Step 1: Restart autowarm-testbench для подтягивания всех фиксов**

```bash
sudo pm2 restart autowarm-testbench
sudo pm2 describe autowarm-testbench | grep -E "exec cwd|status|uptime"
```

Expected: `status=online`, `exec cwd=/home/claude-user/autowarm-testbench`.

- [ ] **Step 2: Inject 10 testbench YT-задач на phone #19**

Через testbench UI («Запустить публикацию» × 10 для phone #19, mix Инакент+makiavelli) ИЛИ напрямую:

```sql
INSERT INTO publish_tasks (device_serial, adb_port, raspberry, platform,
                           account, project, media_path, media_type,
                           caption, status, testbench, created_at, updated_at)
SELECT 'RF8YA0W57EP', 5037, 7, 'YouTube', acc, 'smoke',
       '/test_media/dummy_short.mp4', 'video', 'smoke-' || acc, 'pending',
       true, NOW(), NOW()
FROM (
    SELECT 'makiavelli-o2u' AS acc UNION ALL
    SELECT 'Инакент-т2щ' UNION ALL
    SELECT 'makiavelli-o2u' UNION ALL
    SELECT 'Инакент-т2щ' UNION ALL
    SELECT 'makiavelli-o2u' UNION ALL
    SELECT 'Инакент-т2щ' UNION ALL
    SELECT 'makiavelli-o2u' UNION ALL
    SELECT 'Инакент-т2щ' UNION ALL
    SELECT 'makiavelli-o2u' UNION ALL
    SELECT 'Инакент-т2щ'
) src
RETURNING id;
```

Сохранить 10 returning id'шек.

- [ ] **Step 3: Wait for all 10 to terminate (≤ 25 минут — 2.5 мин/задача)**

```bash
while true; do
  PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw -t -A <<SQL
SELECT count(*) FILTER (WHERE status IN ('done','failed')) AS terminal,
       count(*) FILTER (WHERE status='done') AS done_count
FROM publish_tasks WHERE id IN (<10 ids>);
SQL
  sleep 60
done
```

Loop пока terminal=10. Сохранить timestamps первого и последнего terminal'а.

- [ ] **Step 4: Compute pass-rate**

```sql
SELECT account, status, error_code, count(*)
FROM publish_tasks WHERE id IN (<10 ids>)
GROUP BY account, status, error_code
ORDER BY account, status;
```

Acceptance: **`status='done'` count ≥ 8**.

Если **<8** done:
- Проанализировать failed: какие error_code? Совпадают с canonical namespace?
- Если новые failure modes — фиксировать в evidence T8 как deferred follow-up'ы для следующей сессии (не блокировать поставку B1+B2+B3+B4).
- Если регрессия от наших правок — `git revert` соответствующего commit'а + повторить smoke.

- [ ] **Step 5: Verify yt_block recorded**

```sql
SELECT gmail, yt_block FROM factory_reg_accounts WHERE yt_block ? 'logout';
```

Expected: ≥1 row (gmail разлогиненного other-account, который генерирует модалку на phone #19).

- [ ] **Step 6: Save smoke evidence**

В новый файл `.ai-factory/evidence/yt-publish-stabilization-20260427.md`:

```markdown
# Evidence — YT Publish Stabilization (2026-04-27)

## T8 — Acceptance smoke

**Window:** <start_ts> → <end_ts>
**Tasks injected:** <10 ids>

### Pass-rate

| account | done | failed | error_codes |
|---|---|---|---|
| makiavelli-o2u | <X> | <Y> | <list> |
| Инакент-т2щ | <X> | <Y> | <list> |
| **Total** | <Z> | <10-Z> | |

**Acceptance ≥8/10:** ✅ / ❌

### yt_block detection

<SELECT gmail, yt_block FROM factory_reg_accounts WHERE yt_block ? 'logout' output>

### error_code distribution

<no publish_failed_generic / unknown — all canonical>
```

(Заполнить реальными данными.)

---

### Task 9: Prod sync + final docs commit

**Files:**
- Modify: `/root/.openclaw/workspace-genri/autowarm/` (prod copy).
- Modify: `/home/claude-user/contenthunter/.ai-factory/{plans,evidence}/yt-publish-stabilization-20260427.md` + memory updates.

- [ ] **Step 1: Pre-flight prod state**

```bash
sudo bash -c 'cd /root/.openclaw/workspace-genri/autowarm && git log -1 --oneline'
sudo pm2 describe autowarm | grep -E 'exec cwd|status'
```

Expected: `exec cwd=/root/.openclaw/workspace-genri/autowarm`. Если что-то другое — STOP, починить cwd сначала (memory `feedback_pm2_dump_path_drift.md`).

- [ ] **Step 2: Cherry-pick all 5 testbench commits в prod**

В testbench:

```bash
cd /home/claude-user/autowarm-testbench && git log --oneline origin/testbench..HEAD | head -10
```

Записать 5 SHA'шек: B1 helpers, B1 wire, B2, B4.1, B4.2, B3 (в реальном порядке коммитов).

В prod:

```bash
sudo bash -c 'cd /root/.openclaw/workspace-genri/autowarm && \
  git fetch && \
  git cherry-pick <sha1> <sha2> <sha3> <sha4> <sha5>'
```

Если конфликт — это значит соседняя сессия changed файл. STOP, разобрать конфликт вручную, скорее всего merge не наша.

- [ ] **Step 3: Restart prod autowarm**

```bash
sudo pm2 restart autowarm
sudo pm2 describe autowarm | grep -E 'status|uptime|exec cwd'
sudo pm2 logs autowarm --lines 30 --nostream
```

Expected: `status=online`, в логах нет `_resolve_single_account_mode is not defined`, нет `vision current_account error: [Errno 2]`.

- [ ] **Step 4: Verify post-commit hook auto-pushed в delivery-contenthunter**

```bash
sudo bash -c 'cd /root/.openclaw/workspace-genri/autowarm && git log -1 origin/main --oneline'
```

Expected: совпадает с локальным HEAD после cherry-pick (memory `reference_autowarm_git_hook.md`).

- [ ] **Step 5: Write final evidence + docs commit в contenthunter**

В `.ai-factory/evidence/yt-publish-stabilization-20260427.md` — дополнить раздел T8 (Step 6 of Task 8) + добавить:

```markdown
## T1 — Pre-flight (Task 1 evidence)
<baseline snapshot from /tmp/yt-baseline-*.txt>

## T2-T7 — Implementation (commit shas)
| Task | SHA | Tests | Notes |
|---|---|---|---|
| T2 B1 helpers | <sha> | 3 PASS | _detect_login_modal + _dismiss_login_modal_if_present |
| T3 B1 wire | <sha> | 4 PASS | scroll-loop + flow integration |
| T4 B2 yt_block | <sha> | 2 PASS | + 1 anti-false-positive guard |
| T5 B4.1 vision | <sha> | 1 PASS | HTTPS shot download |
| T6 B4.2 SA-mode | <sha> | 1 PASS | import-path fix |
| T7 B3 namespace | <sha> | 7 PASS | + UI status |

## T9 — Prod sync
- Cherry-pick: 5 SHA'шек
- pm2 restart autowarm: pid=<X> status=online
- post-commit hook → delivery-contenthunter: ✅
```

- [ ] **Step 6: Memory updates**

Изменения в `/home/claude-user/.claude/projects/-home-claude-user-contenthunter/memory/`:

1. **Update** `project_publish_guard_schema.md` — реальные имена колонок: `device_serial` (не phone_number_id), `updated_at` (не finished_at), events JSONB на publish_tasks (нет отдельной таблицы publish_events).
2. **Update** `project_publisher_modularization_wip.md` — добавить факт «yt modal-dismiss + yt_block detection + error namespace отгружено 2026-04-27».
3. **Create** `reference_anthropic_api_key.md` — путь `~/secrets/anthropic.env`, чтецы в коде (5 модулей), формат `sk-ant-api03-...`.
4. **Create** `feedback_switcher_error_namespace.md` — canonical map `<platform>_<phase>_<terminal-state>`, ссылка на `.ai-factory/specs/2026-04-27-yt-publish-stabilization-design.md` секция 3.3.

Затем:

```bash
cd /home/claude-user/contenthunter && git add .ai-factory/plans/yt-publish-stabilization-20260427.md \
                                              .ai-factory/evidence/yt-publish-stabilization-20260427.md
git commit -m "docs(plans+evidence): yt-publish-stabilization-20260427 — executed T1-T9"
```

(Memory файлы — отдельным track'ом, они в `~/.claude/...` не в репе.)

- [ ] **Step 7: Final summary**

Распечатать в evidence:
- Acceptance hit (≥8/10): ✅/❌
- error_code coverage: 0% `publish_failed_generic` / `unknown` среди новых задач?
- yt_block записан для real other-account: ✅/❌
- pm2 logs чистые от 2 follow-up'ов: ✅/❌

---

## Commit Plan

9 задач → 7 коммитов (5 testbench + 1 prod cherry-pick + 1 contenthunter docs):

| # | Repo | Task | Commit msg |
|---|---|---|---|
| 1 | testbench | T2 | `feat(switch): _detect_login_modal + _dismiss_login_modal_if_present helpers` |
| 2 | testbench | T3 | `fix(switch): YT modal-dismiss + picker-scroll on yt_3_open_accounts blocked` |
| 3 | testbench | T4 | `feat(switch): mark yt_block on Требуется действие rows in YT picker` |
| 4 | testbench | T5 | `fix(switch): vision current_account handles HTTPS shot path` |
| 5 | testbench | T6 | `fix(publisher): _resolve_single_account_mode import-path` |
| 6 | testbench | T7 | `refactor(switch): canonical error_code namespace + UI status display` |
| 7 | prod | T9 | (cherry-pick из testbench) `sync(switch+publisher): YT modal + yt_block + error namespace + 2 atomic fixes` |
| 8 | contenthunter | T9 | `docs(plans+evidence): yt-publish-stabilization-20260427 — executed T1-T9` |

T1, T8 — без commit'ов (T1 только evidence-снимок, T8 — только evidence).

---

## Риски (см. spec секция 5 для деталей)

- **R1** — B1 back-press уносит из YT в launcher → pre-back guard через dumpsys window.
- **R2** — B2 ложный yt_block → triple-guard (bounds + clickable + handle/gmail in same row).
- **R3** — B3 rename'ы ломают triage_classifier/agent_diagnose → pre-flight grep + обновление в **том же** commit'е (T7).
- **R4** — B4.1 urllib hangs main loop → timeout=10s + try/except.
- **R5** — Commit-storm в prod → один pm2 restart в конце (T9 Step 3), не после каждого cherry-pick.
- **R6** — phone #19 unavailable → fallback phone #171 (T1 Step 4).
- **R7** — testbench/prod код-баз расхождение к моменту cherry-pick → T9 Step 1 pre-flight `git log -1`.

## Rollback

- T2/T3/T4/T5/T6/T7 commit'ы изолированы → `git revert <sha>` в обоих repo + `pm2 restart`.
- B2 `yt_block` записи — idempotent, revert не уносит уже сохранённые JSONB (новые перестают писаться).
- B3 rename'ы → revert возвращает старые имена + UI правки.

## Дальше

После approval — выполняем через `superpowers:subagent-driven-development` (рекомендуется — fresh subagent per task, review между ними) ИЛИ `superpowers:executing-plans` (inline, batch с checkpoints).

Ожидаемое время: ~4-5 часов wall-clock (50% времени — smoke ожидания + ADB on phone #19).
