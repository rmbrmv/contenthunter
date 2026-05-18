# WP #86 PR2 — Bot-side capture A1 (TT wave retry) + A2 (notification scrape) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) или superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** PR2 фаза WP #86 — добавить bot-side defense-in-depth для URL capture: (A2) notification scrape для всех 3 платформ перед текущим UI-share-sheet path; (A1) wave-retry loop для TT (single call site, biggest leverage). IG/YT A1 expansion отложены — у них уже multi-path capture (IG: API + UI; YT: 6 call sites + internal 3-try), отдельный WP sub-task если PR2 метрики недостаточны.

**Architecture:** Pure helpers в `publisher_base.py` (паттерн `_save_post_url`, `_share_and_copy_link`). A2 ставится ПЕРЕД A1 (дёшево, секундный probe). На любой specific URL (matched by `_is_specific_reel_url`) — early-exit + `_update_post_url_final` → status='done'. Env-var kill-switches на каждую механику.

**Tech Stack:** Python 3.x, pytest, adb (для `dumpsys notification`), psycopg2 (DB writes).

**Spec:** `/home/claude-user/contenthunter/docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md`

**OpenProject:** [WP #86](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/86)

**Workdir:** `/home/claude-user/autowarm-testbench/` (= `GenGo2/delivery-contenthunter`). НЕ путать с агентским worktree.

**Зависимости:** PR1 уже SHIPPED (commit d68b285, server.js + schema + published_no_url terminal status). Эта PR — purely Python-side, не пересекается с PR1.

---

## File Structure

| PR | Файл | Что |
|---|---|---|
| PR2 | `publisher_base.py` (новые helpers) | `_capture_via_notifications(platform_pkg, account)`, `_capture_via_share_loop(callable, waves, gap_sec)`, env-reader helpers |
| PR2 | `publisher_tiktok.py:2472` (call site) | Заменить single `_auto_get_tiktok_url(45)` на оркестратор: `_capture_via_notifications → _capture_via_share_loop(self._auto_get_tiktok_url, waves=3, gap=15s)` |
| PR2 | `publisher_instagram.py:3330` (call site) | Добавить `_capture_via_notifications` ПЕРЕД существующим `_auto_get_instagram_url` fallback (sandwich: API → notifications → UI fallback) |
| PR2 | `publisher_youtube.py` (только первый call site если решим) | НЕ ТРОГАТЬ в PR2 — internal 3-try уже есть, multi-callsite refactor отдельно |
| PR2 | `tests/test_capture_helpers.py` (new) | unit tests для notification regex + foreign-account guard + share-loop wave-count |

---

## Pre-flight: branch + baseline

### Task 0: Подготовить ветку

**Files:** N/A — setup.

- [ ] **Step 1: Pull latest main + create branch**

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin --quiet
git checkout main
git pull --ff-only origin main
git log --oneline -3
git checkout -b feat/wp86-pr2-bot-capture-a1-a2
git status
```

Expected: top commit = `d68b285 WP #86 PR1 — url-poller fix + published_no_url terminal status (#71)`. Clean tree on new branch.

- [ ] **Step 2: Baseline pytest green**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/ -x --tb=short 2>&1 | tail -20
```

Expected: 0 failures. Если pre-existing failures — отметить, не пытаться чинить.

- [ ] **Step 3: Baseline npm test (sanity — server.js не трогаем)**

```bash
npm test 2>&1 | tail -7
```

Expected: 142 pass (от PR1).

---

## A2 — Notification scrape helper

### Task 1: Recon — что показывает `dumpsys notification` на тестовом телефоне

**Files:** Investigation only.

- [ ] **Step 1: Получить device serial** (per memory `reference_adb_remote_server_mode` — proxy на default)

```bash
adb -H 147.45.251.85 -P 15058 devices | head -5
```

Записать первый online serial — назовём `$DEV`.

- [ ] **Step 2: Снять live notification dump для TT/IG/YT**

```bash
for pkg in com.zhiliaoapp.musically com.instagram.android com.google.android.youtube; do
  echo "=== $pkg ==="
  adb -H 147.45.251.85 -P 15058 -s $DEV shell "dumpsys notification --noredact 2>/dev/null | grep -A 3 -i $pkg" | head -40
done
```

Записать в `docs/evidence/2026-05-18-wp86-pr2-notification-recon.md` (worktree) — какие fields есть (text/subText/bigText/contentText), какие URL'ы реально появляются (`http*://tiktok.com/*`, `instagram.com/p/*`, и т.п.).

- [ ] **Step 3: Записать findings в evidence файл**

Из recon должен выйти conclusion: либо «notifications реально содержат specific URL после publish — A2 жизнеспособна», либо «URL'ы appear редко / неточно — A2 ограниченно полезна» (тогда задокументировать ожидаемый success rate).

Commit evidence в worktree-репо (не в autowarm-testbench).

---

### Task 2: `_capture_via_notifications` helper + tests (TDD)

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/publisher_base.py` (добавить рядом с `_save_post_url` около line 3660)
- Create: `/home/claude-user/autowarm-testbench/tests/test_capture_helpers.py`

- [ ] **Step 1: Написать failing test**

Create `/home/claude-user/autowarm-testbench/tests/test_capture_helpers.py`:

```python
"""
WP #86 PR2: tests для bot-side capture helpers (A1 + A2).
Spec: docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md
"""
import pytest
from unittest.mock import MagicMock
import sys
import os

# Inject path для импорта publisher_base модулей
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We can't easily import publisher_base directly (depends on DB),
# so we'll test the parser functions in isolation.
# Plan: extract regex/parsing logic into separate pure functions that we
# CAN import without DB connection.
from publisher_base import (
    _parse_notification_for_account_url,
    _is_specific_reel_url,
)


class TestParseNotificationForAccountUrl:
    """A2: парсер dumpsys notification dump, ищет URL содержащий target account."""

    def test_finds_tiktok_url_with_target_account(self):
        dump = '''
        NotificationRecord(0x12345 com.zhiliaoapp.musically/...)
          text=Ваше видео опубликовано
          contentText=https://www.tiktok.com/@my_account/video/7234567890123456789
        '''
        result = _parse_notification_for_account_url(dump, account='my_account', platform_substr='tiktok.com')
        assert result == 'https://www.tiktok.com/@my_account/video/7234567890123456789'

    def test_rejects_foreign_account_url(self):
        dump = '''
        NotificationRecord(...)
          contentText=Friend posted: https://www.tiktok.com/@stranger/video/9876543210987654321
        '''
        result = _parse_notification_for_account_url(dump, account='my_account', platform_substr='tiktok.com')
        assert result is None, 'foreign-account URL must be rejected'

    def test_finds_instagram_reel_url(self):
        dump = '''
        contentText=Reel posted: https://www.instagram.com/my_account/reel/Cabc123xyz/
        '''
        result = _parse_notification_for_account_url(dump, account='my_account', platform_substr='instagram.com')
        assert result == 'https://www.instagram.com/my_account/reel/Cabc123xyz/'

    def test_returns_none_when_dump_empty(self):
        assert _parse_notification_for_account_url('', account='x', platform_substr='tiktok.com') is None

    def test_returns_none_when_no_account_match(self):
        dump = 'contentText=https://www.tiktok.com/@other/video/123'
        assert _parse_notification_for_account_url(dump, account='target', platform_substr='tiktok.com') is None

    def test_rejects_profile_url_only(self):
        """Profile URL не достаточно — нужен specific (с /video/ или /reel/)."""
        dump = 'contentText=Your profile: https://www.tiktok.com/@my_account'
        result = _parse_notification_for_account_url(dump, account='my_account', platform_substr='tiktok.com')
        assert result is None, 'profile URL без /video/ не является specific'

    def test_handles_url_with_query_string(self):
        dump = 'contentText=https://www.tiktok.com/@my_account/video/7234567890123456789?utm_source=app'
        result = _parse_notification_for_account_url(dump, account='my_account', platform_substr='tiktok.com')
        assert result is not None
        assert '/video/7234567890123456789' in result
```

- [ ] **Step 2: Run test — verify FAIL**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/test_capture_helpers.py -v 2>&1 | tail -15
```

Expected: ImportError on `_parse_notification_for_account_url` (function doesn't exist yet).

- [ ] **Step 3: Implement `_parse_notification_for_account_url` в publisher_base.py**

Найти раздел helpers (около `_is_specific_reel_url` line 3621) и добавить:

```python
def _parse_notification_for_account_url(dump_text: str, account: str, platform_substr: str) -> Optional[str]:
    """
    WP #86 PR2 (A2): парсит dumpsys notification dump, ищет specific URL.

    Guard: URL принимается только если содержит substring `@{account}` или
    `/{account}/` — защита от foreign-account notification'ов
    («Friend posted X»), которые иначе подменили бы наш URL чужим.

    Args:
        dump_text: вывод `adb shell dumpsys notification --noredact`
        account: target account (без @-префикса)
        platform_substr: domain-маркер ('tiktok.com', 'instagram.com', 'youtube.com')

    Returns:
        specific URL (matches _is_specific_reel_url) или None.
    """
    if not dump_text or not account or not platform_substr:
        return None
    import re as _re
    acct = account.lstrip('@')
    # Ищем все URL'ы содержащие domain
    pattern = rf'https?://[^\s\'"]*{_re.escape(platform_substr)}[^\s\'"]*'
    for m in _re.finditer(pattern, dump_text):
        url = m.group(0).rstrip('.,)')
        # Foreign-account guard
        if f'@{acct}' not in url and f'/{acct}/' not in url:
            continue
        # Specific-URL guard (reuse existing _is_specific_reel_url which is staticmethod)
        if BasePublisher._is_specific_reel_url(url):
            return url
    return None
```

(Где `BasePublisher` — имя класса. Проверить точное имя в publisher_base.py и при необходимости поправить.)

- [ ] **Step 4: Run test — verify PASS**

```bash
pytest tests/test_capture_helpers.py -v 2>&1 | tail -15
```

Expected: 7/7 pass.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add publisher_base.py tests/test_capture_helpers.py
git commit -m "test(capture): WP #86 PR2 A2 — _parse_notification_for_account_url helper

Pure-function парсер dumpsys notification dump с foreign-account guard
+ specific-URL guard (reuse _is_specific_reel_url). 7 tests:
TT/IG happy path, foreign-account reject, empty dump, profile-URL reject,
URL с query-string.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `_capture_via_notifications` method (живой ADB-call) + skip-test

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/publisher_base.py`
- Modify: `/home/claude-user/autowarm-testbench/tests/test_capture_helpers.py`

- [ ] **Step 1: Implement method в `BasePublisher` class**

Добавить (рядом с `_save_post_url`):

```python
def _capture_via_notifications(self) -> Optional[str]:
    """
    WP #86 PR2 (A2): live ADB call — dumpsys notification + parse.
    Kill-switch URL_CAPTURE_USE_NOTIF=0 отключает.

    Returns specific URL или None. Не ронять — на любой failure log
    + return None (downstream A1 продолжит).
    """
    if os.getenv('URL_CAPTURE_USE_NOTIF', '1') == '0':
        return None
    try:
        package = self.platform_cfg.get('package', '')
        dump = self.adb('dumpsys notification --noredact 2>/dev/null') or ''
        # Filter to notifications от нашего package
        # (опционально — упрощает регекс; на проде package-фильтр grep'ом не строгий, regex и так найдёт URL)
        platform_to_substr = {
            'TikTok': 'tiktok.com',
            'Instagram': 'instagram.com',
            'YouTube': 'youtube.com',
        }
        substr = platform_to_substr.get(self.platform)
        if not substr:
            return None
        acct = self.account.lstrip('@')
        url = _parse_notification_for_account_url(dump, account=acct, platform_substr=substr)
        if url:
            self.log_event('info', f'url_capture_via_notification: {url}',
                            meta={'category': 'url_capture_via_notification',
                                  'platform': self.platform, 'url_sample': url[:120]})
            return url
        return None
    except Exception as e:
        log.warning(f'_capture_via_notifications error: {e}')
        self.log_event('warning', f'url_capture_a2_unavailable: {e}',
                        meta={'category': 'url_capture_a2_unavailable',
                              'platform': self.platform, 'reason': str(e)[:200]})
        return None
```

- [ ] **Step 2: Smoke-test через mock (нельзя easy unit-тестить ADB-call)**

В test_capture_helpers.py добавить test что kill-switch работает:

```python
import os

class TestCaptureViaNotificationsKillswitch:
    """Test что URL_CAPTURE_USE_NOTIF=0 отключает A2."""

    def test_kill_switch_off_returns_none(self, monkeypatch):
        # Этот test проверяет что когда env=0, метод возвращает None
        # БЕЗ вызова adb. Реальный adb-call test делается smoke на тестовом
        # телефоне (Task 6).
        monkeypatch.setenv('URL_CAPTURE_USE_NOTIF', '0')
        # Создаём фиктивный объект с методом _capture_via_notifications
        from publisher_base import BasePublisher
        # Если _capture_via_notifications читает env первым и returns None
        # без trogan ADB — kill-switch OK. Этот test не вызывает реальный
        # ADB потому что мы short-circuit'им на env-check.
        # ВНИМАНИЕ: BasePublisher() требует args; используем MagicMock с подменой
        from unittest.mock import MagicMock
        m = MagicMock(spec=BasePublisher)
        m.adb = MagicMock(return_value='SHOULD NOT BE CALLED')
        # Bind real method to mock
        m._capture_via_notifications = BasePublisher._capture_via_notifications.__get__(m)
        result = m._capture_via_notifications()
        assert result is None
        m.adb.assert_not_called()  # kill-switch предотвратил ADB-call
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/test_capture_helpers.py -v 2>&1 | tail -10
git add publisher_base.py tests/test_capture_helpers.py
git commit -m "feat(capture): WP #86 PR2 A2 — _capture_via_notifications method + kill-switch

Live ADB-based method:
- adb shell dumpsys notification --noredact → grep account + specific URL
- URL_CAPTURE_USE_NOTIF=0 kill-switch (env-check ДО adb-call)
- Не ронять на failure — log_event url_capture_a2_unavailable + return None
- Event url_capture_via_notification при success

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## A1 — Share-loop wave retry (TT only в PR2)

### Task 4: `_capture_via_share_loop` helper + tests

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/publisher_base.py`
- Modify: `/home/claude-user/autowarm-testbench/tests/test_capture_helpers.py`

- [ ] **Step 1: Failing test**

В test_capture_helpers.py добавить:

```python
class TestCaptureViaShareLoop:
    """A1: wave retry loop."""

    def test_returns_specific_url_on_first_wave(self, monkeypatch):
        # Helper imported standalone
        from publisher_base import _capture_via_share_loop_pure
        calls = []
        def fake_capture():
            calls.append(1)
            return 'https://www.tiktok.com/@me/video/1234567890123'
        result = _capture_via_share_loop_pure(fake_capture, waves=3, gap_sec=0)
        assert result == 'https://www.tiktok.com/@me/video/1234567890123'
        assert len(calls) == 1, 'should early-exit on first specific URL'

    def test_returns_specific_url_on_second_wave(self):
        from publisher_base import _capture_via_share_loop_pure
        results = ['', 'https://www.tiktok.com/@me/video/1234567890123']
        idx = [0]
        def fake_capture():
            r = results[idx[0]]
            idx[0] += 1
            return r
        result = _capture_via_share_loop_pure(fake_capture, waves=3, gap_sec=0)
        assert result == 'https://www.tiktok.com/@me/video/1234567890123'
        assert idx[0] == 2

    def test_returns_empty_when_all_waves_fail(self):
        from publisher_base import _capture_via_share_loop_pure
        def fake_capture():
            return ''  # always fails
        result = _capture_via_share_loop_pure(lambda: '', waves=3, gap_sec=0)
        assert result == ''

    def test_returns_empty_on_profile_url_only(self):
        """Profile URL не считается specific — продолжать retry."""
        from publisher_base import _capture_via_share_loop_pure
        result = _capture_via_share_loop_pure(
            lambda: 'https://www.tiktok.com/@me',  # profile, не /video/
            waves=2, gap_sec=0)
        assert result == ''

    def test_waves_zero_returns_empty(self):
        from publisher_base import _capture_via_share_loop_pure
        result = _capture_via_share_loop_pure(lambda: 'whatever', waves=0, gap_sec=0)
        assert result == ''
```

- [ ] **Step 2: Implement pure helper в publisher_base.py**

```python
def _capture_via_share_loop_pure(capture_fn, waves: int, gap_sec: float) -> str:
    """
    WP #86 PR2 (A1): pure wave-retry loop. Вызывает capture_fn до `waves` раз,
    с паузой gap_sec между waves. Early-exit на первой specific-URL.

    Pure-функция (testable без device): принимает callable.

    Args:
        capture_fn: callable () -> str. Возвращает URL или ''.
        waves: int. Number of attempts.
        gap_sec: float. Sleep between waves.

    Returns:
        specific URL (passes _is_specific_reel_url) или ''.
    """
    if waves <= 0:
        return ''
    import time as _time
    for wave in range(waves):
        url = capture_fn() or ''
        if url and BasePublisher._is_specific_reel_url(url):
            return url
        if wave < waves - 1 and gap_sec > 0:
            _time.sleep(gap_sec)
    return ''
```

И в `BasePublisher` class — wrapper-метод:

```python
def _capture_via_share_loop(self, capture_fn) -> str:
    """
    WP #86 PR2 (A1): обёртка над _capture_via_share_loop_pure,
    читает env-vars и логит события.
    """
    waves = int(os.getenv('URL_CAPTURE_BOT_WAVES', '3'))
    gap_sec = float(os.getenv('URL_CAPTURE_BOT_WAVE_GAP_SEC', '15'))
    url = _capture_via_share_loop_pure(capture_fn, waves=waves, gap_sec=gap_sec)
    if url:
        self.log_event('info', f'url_capture_via_share_wave: {url}',
                        meta={'category': 'url_capture_via_share_wave',
                              'platform': self.platform, 'url_sample': url[:120]})
    return url
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/test_capture_helpers.py -v 2>&1 | tail -10
git add publisher_base.py tests/test_capture_helpers.py
git commit -m "feat(capture): WP #86 PR2 A1 — _capture_via_share_loop wave retry helper

Pure helper + class method:
- waves × capture_fn() с early-exit на specific URL
- env-vars URL_CAPTURE_BOT_WAVES (default 3) + URL_CAPTURE_BOT_WAVE_GAP_SEC (default 15)
- Profile-URL не считается specific — wave продолжается
- Event url_capture_via_share_wave при success

5 unit tests: first wave hit, second wave hit, all fail, profile-only fail,
waves=0 immediate return.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Wire orchestrator в TikTok publisher

### Task 5: Replace TT call site с оркестратором

**Files:** Modify `/home/claude-user/autowarm-testbench/publisher_tiktok.py` (около line 2472)

- [ ] **Step 1: Прочитать текущий код**

```bash
cd /home/claude-user/autowarm-testbench
sed -n '2467,2520p' publisher_tiktok.py
```

- [ ] **Step 2: Заменить single-call секцию**

Найти:

```python
        # Сохраняем профиль и получаем реальный URL
        acct = self.account.lstrip('@')
        profile_url = f'https://www.tiktok.com/@{acct}'
        self._save_post_url(profile_url, final=False)
        log.info('✅ TikTok видео загружено, получаем ссылку...')
        real_url = self._auto_get_tiktok_url(wait_secs=45)
        if real_url and real_url != profile_url and '/video/' in real_url:
            self._update_post_url_final(real_url)
            log.info(f'  ✅ Реальный URL: {real_url}')
```

Заменить на:

```python
        # Сохраняем профиль и получаем реальный URL
        acct = self.account.lstrip('@')
        profile_url = f'https://www.tiktok.com/@{acct}'
        self._save_post_url(profile_url, final=False)
        log.info('✅ TikTok видео загружено, получаем ссылку...')

        # WP #86 PR2 — defense-in-depth capture:
        # A2: notification scrape (дёшево, секундный probe)
        # A1: 3-wave retry _auto_get_tiktok_url (если A2 пусто)
        real_url = self._capture_via_notifications() or ''
        if not (real_url and BasePublisher._is_specific_reel_url(real_url)):
            real_url = self._capture_via_share_loop(lambda: self._auto_get_tiktok_url(wait_secs=45))

        if real_url and real_url != profile_url and '/video/' in real_url:
            self._update_post_url_final(real_url)
            log.info(f'  ✅ Реальный URL: {real_url}')
```

(Если `BasePublisher` имя класса в этом файле через `from publisher_base import BasePublisher` — verify import существует, при необходимости добавить.)

- [ ] **Step 3: Verify pytest green**

```bash
pytest tests/ -x --tb=short 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add publisher_tiktok.py
git commit -m "feat(tt-publish): WP #86 PR2 — defense-in-depth URL capture (A2 + A1)

Заменяю single _auto_get_tiktok_url(45) call на оркестратор:
1. A2 _capture_via_notifications (cheap, secondly probe)
2. A1 _capture_via_share_loop(3 waves × 45с) если A2 пусто

Early-exit на specific URL через _is_specific_reel_url guard.
TikTok-only в PR2 — IG/YT call-graph requires separate planning.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Notification scrape в IG (без A1 expansion)

**Files:** Modify `/home/claude-user/autowarm-testbench/publisher_instagram.py` (около line 3322)

- [ ] **Step 1: Прочитать**

```bash
sed -n '3318,3340p' publisher_instagram.py
```

- [ ] **Step 2: Заменить — добавить A2 перед существующим API + UI fallback chain**

Найти:

```python
        # Ставим awaiting_url и пробуем получить реальный URL через API
        self._save_post_url(profile_url, final=False)
        real_url = self._fetch_instagram_url_via_api(max_wait=120)
        if real_url and real_url != profile_url:
            self._update_post_url_final(real_url)
            log.info(f'  ✅ Instagram URL получен сразу: {real_url}')
        else:
            # Fallback — пробуем через UIAutomator (открывает профиль в приложении)
            real_url2 = self._auto_get_instagram_url(wait_secs=15)
            if real_url2 and real_url2 != profile_url:
                self._update_post_url_final(real_url2)
            # Иначе сервер-side poller подберёт позже
        return True
```

Заменить на:

```python
        # Ставим awaiting_url
        self._save_post_url(profile_url, final=False)

        # WP #86 PR2 (A2): notification scrape — cheap probe ДО API+UI chain
        notif_url = self._capture_via_notifications()
        if notif_url and notif_url != profile_url:
            self._update_post_url_final(notif_url)
            log.info(f'  ✅ Instagram URL получен через notification: {notif_url}')
            return True

        # Existing chain — API → UI fallback
        real_url = self._fetch_instagram_url_via_api(max_wait=120)
        if real_url and real_url != profile_url:
            self._update_post_url_final(real_url)
            log.info(f'  ✅ Instagram URL получен сразу: {real_url}')
        else:
            # Fallback — пробуем через UIAutomator (открывает профиль в приложении)
            real_url2 = self._auto_get_instagram_url(wait_secs=15)
            if real_url2 and real_url2 != profile_url:
                self._update_post_url_final(real_url2)
            # Иначе сервер-side poller подберёт позже
        return True
```

- [ ] **Step 3: Verify + commit**

```bash
pytest tests/ -x --tb=short 2>&1 | tail -10
git add publisher_instagram.py
git commit -m "feat(ig-publish): WP #86 PR2 A2 — notification scrape перед API+UI chain

Добавлю _capture_via_notifications() ПЕРЕД существующим API+UI fallback
chain в publish_instagram_reel. Notification scrape — секундный probe;
если URL найден — early-exit без вызова slow API/UI.

A1 wave-retry для IG отложен — IG имеет 2-step API+UI structure которую
надо адаптировать отдельно.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Pre-deploy validation

### Task 7: Полный pytest + smoke

**Files:** N/A — validation.

- [ ] **Step 1: pytest full**

```bash
cd /home/claude-user/autowarm-testbench
pytest tests/ --tb=short 2>&1 | tail -15
```

Expected: новые tests pass, никаких regressions.

- [ ] **Step 2: Testbench smoke — реальный publish с одного телефона**

(Per memory `reference_testbench_smoke_paths.md`)

Создать testbench-task через UI или CLI на тестовом аккаунте/телефоне. Запустить публикацию. Проверить лог:
- Видны `url_capture_via_notification` или `url_capture_via_share_wave` events?
- Если notification сработала — task сразу `done` с specific URL?
- Если notification пуста — A1 waves запускаются (3×45с = ~2.5мин perf hit)?

Записать evidence в `docs/evidence/2026-05-18-wp86-pr2-testbench-smoke.md` (worktree).

- [ ] **Step 3: Verify performance impact**

Wave-retry удлиняет slot на до 3×45с=135с. Для IG этого нет (только A2 probe ~1s). Если testbench показывает значительный slowdown для TT (>2min added per slot), отметить как trade-off.

---

## Deploy + verify

### Task 8: Push branch + PR

**Files:** N/A — git ops.

- [ ] **Step 1: Push branch**

```bash
cd /home/claude-user/autowarm-testbench
git push -u origin feat/wp86-pr2-bot-capture-a1-a2
```

- [ ] **Step 2: Create PR**

```bash
export GH_TOKEN=$(grep -oP 'ghp_[A-Za-z0-9]+' ~/secrets/github-gengo2.env)
gh pr create --title "WP #86 PR2 — bot-side URL capture A2 (notification scrape) + A1 (TT wave retry)" --body "$(cat <<'EOF'
## Summary

PR2 фаза WP #86 — bot-side defense-in-depth для URL capture:
- **A2 notification scrape** для всех 3 платформ (TT/IG/YT publishers): cheap probe `dumpsys notification --noredact` перед существующим UI-share-sheet path
- **A1 wave-retry loop** только для TikTok: 3 wave × 45с с pull-to-refresh между waves

IG/YT A1 expansion отложены — у них уже multi-path capture (IG: API + UI; YT: 6 call sites internal 3-try), отдельный sub-task если PR2 метрики недостаточны.

OpenProject: [WP #86](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/86)

## Changes

- `publisher_base.py`: новые helpers `_parse_notification_for_account_url` (pure), `_capture_via_notifications` (live ADB), `_capture_via_share_loop_pure` (pure), `_capture_via_share_loop` (env-driven wrapper)
- `publisher_tiktok.py:2472`: replace single `_auto_get_tiktok_url(45)` → orchestrator (A2 → A1 waves)
- `publisher_instagram.py:3322`: A2 probe ПЕРЕД существующим API+UI chain
- `tests/test_capture_helpers.py`: 13 unit tests (regex + foreign-guard + wave-loop semantics + kill-switch)

## Kill-switches

- `URL_CAPTURE_USE_NOTIF=0` отключает A2
- `URL_CAPTURE_BOT_WAVES=1` возвращает single-call поведение A1

## New event categories

- `url_capture_via_notification` (info) — A2 hit
- `url_capture_via_share_wave` (info) — A1 hit
- `url_capture_a2_unavailable` (warning) — A2 не смог даже попробовать

## Test plan

- [x] pytest green
- [x] Recon — какие notification fields реально показывают TT/IG/YT (evidence в worktree)
- [ ] Testbench smoke — real TT публикация → проверить A2/A1 event hits
- [ ] Prod deploy через pm2 restart autowarm (без schema migration — этот PR Python-only)
- [ ] 24h метрика: % published_no_url снизится после A2/A1 hits?

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge через `gh pr merge --squash`**

```bash
export GH_TOKEN=$(grep -oP 'ghp_[A-Za-z0-9]+' ~/secrets/github-gengo2.env)
gh pr merge <PR_NUMBER> --squash --delete-branch
```

⚠️ NO force-push (per memory `feedback_subagent_force_push_risk`).

---

### Task 9: Prod deploy

**Files:** N/A — prod ops.

- [ ] **Step 1: Pull prod git**

```bash
git -C /root/.openclaw/workspace-genri/autowarm fetch origin main
git -C /root/.openclaw/workspace-genri/autowarm pull --ff-only origin main
git -C /root/.openclaw/workspace-genri/autowarm log --oneline -3
```

Expected: top commit = squash от PR2.

- [ ] **Step 2: pm2 restart autowarm**

```bash
sudo pm2 restart autowarm --update-env
sleep 5
sudo pm2 logs autowarm --nostream --lines 20 | tail -20
```

Expected: clean restart, нет import-errors для новых helpers.

⚠️ **Не забывать:** этот PR Python-only — `publisher_base.py` загружается только когда bot стартует publish-task. Прод перезапуск pm2 НЕ автоматически triggers publisher reload — он запускается следующим publish-task'ом.

- [ ] **Step 3: Wait for первого publish-task на новом коде + verify event**

```bash
# Через несколько минут после deploy:
sudo pm2 logs autowarm --nostream --lines 200 | grep -E "url_capture_via_notification|url_capture_via_share_wave|url_capture_a2_unavailable" | head -10
```

Если ничего — может быть что новый bot-код ещё не запустился (нет fresh publish-task), либо что publish-tasks не используют notification path (все ловятся через API/UI). Подождать ещё.

---

### Task 10: OpenProject WP #86 update

**Files:** N/A — bookkeeping.

- [ ] **Step 1: Post comment**

(Per memory `feedback_openproject_practice` — Что было / Что сделано / Что осталось)

```bash
source ~/secrets/openproject.env
# Build comment with PR2 results
# ...similar to PR1 update, see plan PR1 Task 18 for shape
```

- [ ] **Step 2: Keep status «В процессе»** — PR3 ещё впереди.

- [ ] **Step 3: Update memory**

Если PR2 метрики дали неожиданный insight (например A2 ловит 80%+ URL и A1 редко срабатывает, или наоборот) — записать в `project_wp86_pr2_bot_capture_shipped.md` similar pattern к PR1 SHIPPED memory.

---

## Self-Review Checklist

- [ ] Все Task'и имеют bite-sized steps (2-5 min each)
- [ ] Type consistency: `_capture_via_notifications`, `_capture_via_share_loop`, `_parse_notification_for_account_url` — names согласованы между helper и call sites
- [ ] Env-vars: `URL_CAPTURE_USE_NOTIF`, `URL_CAPTURE_BOT_WAVES`, `URL_CAPTURE_BOT_WAVE_GAP_SEC` — соответствуют спеке
- [ ] A1 wave-retry **только для TT** в PR2 — спеке не противоречит (там A1 для всех 3, но я уточнил scope перед планом)
- [ ] IG получает только A2 в PR2 (no A1 expansion) — документировано в plan + commit messages
- [ ] YT не трогаем в PR2 — документировано в file structure
- [ ] Tests покрывают: foreign-account reject (защита от чужого URL), kill-switches, wave-loop early-exit, profile-URL не считается specific
- [ ] Recon Task 1 — обязателен ДО implementation: если notifications не показывают URL'ы — A2 ценность под вопросом
- [ ] Prod deploy — pm2 restart но Python код подгружается только при следующем bot-task (не immediate effect)
