# Design — WP #105 ig_app_launch_failed: stale uiautomator dump vs fresh dumpsys

**WP:** https://openproject.contenthunter.ru/wp/105
**Категория:** `ig_app_launch_failed`
**Объём:** 14 fails за 7 дней (2026-05-13…2026-05-19), 3 fails сегодня (2026-05-19). 13 уникальных устройств на raspberries 2/3/5/7/9/10.

## 1. Симптом

`step=ig_1_feed` падает с `Instagram не запустился`, при этом скриншот через секунду после fail показывает что Instagram реально на переднем плане.

Примеры:
- task 7821 (clickpay_now / Pi #7, 2026-05-19 09:09) — ui dump `package="com.sec.android.app.launcher"`, screenshot +1s = IG feed
- task 7692 (contentexpert_ / Pi #3, 2026-05-19 04:52) — то же
- task 7756 (mysticluxaroma / Pi #10) — то же

## 2. Root cause

Два метода в `account_switcher.py` определяют foreground-пакет ПО-РАЗНОМУ:

### `_ensure_app_foregrounded` (account_switcher.py:3398-3464)

```python
focus_out = self.p.adb('dumpsys activity activities | grep -m1 topResumedActivity') or ''
if expected_pkg in focus_out:
    return True
```

Источник: **только `dumpsys topResumedActivity`**. Это live ActivityManager state, обновляется сразу при `am start` callback'е.

### `_open_app._foreground_pkg` (account_switcher.py:4696-4705)

```python
xml = self.p.dump_ui(retries=1) or ''
m = re.search(r'package="([^"]+)"', xml)
if m:
    return m.group(1)              # ← если regex нашёл — возвращаем БЕЗ проверки dumpsys
top = self.p.adb("dumpsys activity activities | grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
m2 = re.search(r'\s([\w\.]+)/[\w\.]+', top)
return m2.group(1) if m2 else ''
```

Источник: **`uiautomator dump`** (package= в корне иерархии); fallback на dumpsys ТОЛЬКО если regex не нашёл атрибут.

### Расхождение

На Samsung устройствах (S21, raspberries 2/3/5/7/9/10) после `am start -n com.instagram.android/.activity.MainTabActivity`:

- ActivityManager **сразу** регистрирует IG как `topResumedActivity` → `_ensure_app_foregrounded` видит IG
- UIAutomator продолжает возвращать дамп **прежнего окна** (launcher) ещё ~60-90 секунд, пока Window Manager не закончит transition анимацию + ContentObserver не пересоберёт иерархию
- `_open_app._foreground_pkg` читает uiautomator → видит `package="com.sec.android.app.launcher"`
- 3 `am start` ретрая ничего не меняют (IG уже запущен, второй start — no-op; uiautomator всё ещё stale)
- В конце loop'а `cur != package` → `return False` → `_fail('Instagram не запустился')`

13/13 фейлов имеют **одинаковую evidence-сигнатуру**: pre-check фиксирует `ig_app_foregrounded_after_recovery: attempt=2`, через 80-90s `_open_app` падает.

## 3. Design — defense in depth

### Layer 1 (primary): cross-source foreground check

Переписать `_foreground_pkg` так, чтобы он спрашивал **обоих источников** и возвращал target package если **хотя бы один** подтверждает foreground == target.

```python
def _foreground_pkg(target_pkg: Optional[str] = None) -> str:
    # Источник A — dumpsys (fresh ActivityManager state)
    top = self.p.adb("dumpsys activity activities | grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
    m_dump = re.search(r'\s([\w\.]+)/[\w\.]+', top)
    pkg_dump = m_dump.group(1) if m_dump else ''
    
    # Источник B — uiautomator (могут отставать на Samsung)
    xml = self.p.dump_ui(retries=1) or ''
    m_ui = re.search(r'package="([^"]+)"', xml)
    pkg_ui = m_ui.group(1) if m_ui else ''
    
    # Если target известен и хотя бы один источник его видит — trust target
    if target_pkg and (pkg_dump == target_pkg or pkg_ui == target_pkg):
        return target_pkg
    
    # Иначе вернуть наиболее доверенный источник (dumpsys приоритет — fresh)
    return pkg_dump or pkg_ui
```

Изменение:
- Параметр `target_pkg` опционален → backward-compatible для прочих call-sites
- Внутри `_open_app` всегда передаётся `package` (target)
- При расхождении dumpsys vs uiautomator — побеждает источник, согласный с target
- Логируется событие `ig_foreground_pkg_disagree` при `pkg_dump != pkg_ui` с обоими значениями — observability для будущей проверки гипотезы

### Layer 2 (defense): settle-wait перед финальным fail

В `_open_app` после трёх `am start` ретраев, перед `return False`, добавить дополнительный «settle wait» — до 15s polling _foreground_pkg каждую секунду. Catches случай когда IG отстаёт на 1-5 секунд (как видно в скриншотах — IG появляется сразу после dump'а).

```python
# После цикла из 3 attempts, до save_dump:
if cur != package:
    settle_deadline = time.monotonic() + 15.0
    while time.monotonic() < settle_deadline:
        if _deadline_exceeded():
            break
        time.sleep(1.0)
        cur = _foreground_pkg(target_pkg=package)
        if cur == package:
            self.p.log_event('info',
                f'{step_name}: settled foreground after extended wait',
                meta={'category': 'switcher_settle_wait_recovered',
                      'package': package, 'step': step_name})
            break
```

Это buffers против race'а в обе стороны:
- uiautomator stale ↦ dumpsys догонит → settle поймает
- IG launching slowly ↦ оба источника постепенно сходятся

### Layer 3 (observability): расширить лог при fail

При final fail (`cur != package` после settle-wait):
- залогировать ОБА источника отдельно (pkg_dump + pkg_ui) в meta события `account_switch`
- залогировать длительность от первого am start до final check
- помечать category=`ig_app_launch_failed` (как сейчас)

Это даёт грейс на будущее: если фикс не закроет 100% случаев, evidence сразу покажет какой источник как себя ведёт.

## 4. Что НЕ трогать

- `_ensure_app_foregrounded` не меняем — оно уже использует dumpsys и работает корректно. Pre-check возвращает True правильно; проблема в `_open_app`.
- `am start` retry-логику не трогаем — IG реально запущен после 1-го старта, дополнительные старты безвредны.
- `_dismiss_blocking_overlays` не трогаем — он отрабатывает корректно (или no-op) в evidence.

## 5. Риски

| Риск | Митигация |
|---|---|
| Cross-source check возвращает target когда реально target не запущен (false positive) | Использовать `target_pkg` параметр — оба источника должны видеть либо target, либо мы возвращаем уверенно-известный foreground. Не возвращаем target если ОБА источника говорят "не target". |
| Settle-wait 15s удлиняет среднее время `_open_app` для real fails | False positives `_open_app` редки на pin-up аккаунтах. Healthy launch заканчивается в первом attempt (`cur == package` early return). Settle-wait триггерится только когда 3 am start не помогли → реальный fail случай, +15s не критично vs текущий 86s wasted. |
| `_foreground_pkg_disagree` event spam | Логировать только когда target_pkg указан и расхождение реальное (pkg_dump != pkg_ui). Healthy случай — оба согласны, нет события. |
| Параллельные сессии редактируют `_foreground_pkg` | Использовать atomic commits + worktree (per [[feedback_parallel_claude_sessions]]); тестировать перед merge. |

## 6. Smoke test plan

После имплементации:
1. Unit-тесты: mock-based — _foreground_pkg возвращает target при (dumpsys=target, uiautomator=launcher); при (dumpsys=launcher, uiautomator=target); при (both=launcher → returns launcher); при (both=target → returns target).
2. Smoke на phone #19 testbench: симулировать stale uiautomator (если возможно) либо просто проверить что healthy IG-switch не сломался.
3. Observability: после деплоя в prod 24h, query events для `ig_foreground_pkg_disagree` — если случается часто, фикс работает (factual evidence для гипотезы).

## 7. Связанные сущности

- WP #74 Round 2 — YT foreign-foreground guard SHIPPED (PR #72) — концептуально близко (recovery + guard pattern)
- WP #73 — `ig_share_tap_no_progress` — другой IG-bug, не дублируется
- `_ensure_app_foregrounded` — корректный, не меняем
- `_open_app` — затрагиваем `_foreground_pkg` и финальный fail-path

## 8. Out of scope

- Не оптимизируем `dump_ui` (его задача — UI hierarchy для tap-decision, не foreground detection)
- Не меняем `OPEN_APP_WAIT_S=4.0` (per-attempt sleep), потому что фикс не про длину sleep между am start, а про источник foreground signal'а
- Не трогаем launcher detection / overlay dismissal — отдельный путь
