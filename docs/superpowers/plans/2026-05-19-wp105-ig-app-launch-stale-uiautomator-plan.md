# Implementation Plan — WP #105 ig_app_launch_failed: cross-source foreground check + settle-wait

**Design:** [2026-05-19-wp105-ig-app-launch-stale-uiautomator-design.md](../specs/2026-05-19-wp105-ig-app-launch-stale-uiautomator-design.md)
**WP:** https://openproject.contenthunter.ru/wp/105
**Branch:** `worktree-wp105-ig-app-launch-failed` (создан 2026-05-19)
**Target repo:** `/home/claude-user/autowarm-testbench` (dev), cherry-pick в `/root/.openclaw/workspace-genri/autowarm/` для prod через [[reference_autowarm_git_hook]]

## Pre-flight

- [ ] `git fetch origin && git log -3 origin/main` в `/home/claude-user/autowarm-testbench` — убедиться что нет свежих коммитов от параллельных сессий
- [ ] `pytest tests/test_account_switcher.py -x -q` — baseline green перед изменениями
- [ ] Read `account_switcher.py:4696-4705` (`_foreground_pkg`), `:4667-4782` (`_open_app`), `:3398-3464` (`_ensure_app_foregrounded` — НЕ ТРОГАЕМ, только reference)

## Task 1 — `_foreground_pkg` cross-source check

**File:** `/home/claude-user/autowarm-testbench/account_switcher.py`
**Lines:** 4696-4705 (внутри `_open_app`)

**Изменения:**

1. Поднять `_foreground_pkg` из inner-функции `_open_app` в method класса (или оставить inner, но принять `target_pkg`). Решение: оставить inner — минимизирует blast radius (только `_open_app` использует).

2. Расширить сигнатуру: `def _foreground_pkg(target_pkg: Optional[str] = None) -> str:`

3. Изменить логику:
   ```python
   def _foreground_pkg(target_pkg: Optional[str] = None) -> str:
       # Источник A — dumpsys
       top = self.p.adb("dumpsys activity activities | grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
       m_dump = re.search(r'\s([\w\.]+)/[\w\.]+', top)
       pkg_dump = m_dump.group(1) if m_dump else ''
       # Источник B — uiautomator
       xml = self.p.dump_ui(retries=1) or ''
       m_ui = re.search(r'package="([^"]+)"', xml)
       pkg_ui = m_ui.group(1) if m_ui else ''
       # Disagreement event (только когда target указан и есть расхождение)
       if target_pkg and pkg_dump and pkg_ui and pkg_dump != pkg_ui:
           self.p.log_event('info',
               f'foreground_pkg_disagree: dumpsys={pkg_dump} uiautomator={pkg_ui}',
               meta={'category': 'switcher_foreground_pkg_disagree',
                     'pkg_dumpsys': pkg_dump,
                     'pkg_uiautomator': pkg_ui,
                     'target_pkg': target_pkg})
       # Trust target if EITHER source confirms
       if target_pkg and (pkg_dump == target_pkg or pkg_ui == target_pkg):
           return target_pkg
       # Default: dumpsys приоритет (fresh state)
       return pkg_dump or pkg_ui
   ```

4. Все вызовы внутри `_open_app` поменять на `_foreground_pkg(target_pkg=package)`:
   - Строка 4712: `cur = _foreground_pkg()` → `cur = _foreground_pkg(target_pkg=package)`
   - Строка 4726: `cur = _foreground_pkg()` → `cur = _foreground_pkg(target_pkg=package)`
   - Строка 4747: `cur = _foreground_pkg()` → `cur = _foreground_pkg(target_pkg=package)`

## Task 2 — settle-wait перед final fail

**File:** `/home/claude-user/autowarm-testbench/account_switcher.py`
**Lines:** между 4757 (`# конец цикла 3 am-start attempts`) и 4758 (`self._save_dump(...)`)

**Вставить:**

```python
# [WP #105 settle-wait 2026-05-19] uiautomator dump может отставать
# от dumpsys на 1-15s на Samsung устройствах. Если 3 am-start attempts
# не помогли — даём IG/dumpsys времени синхронизироваться. См. spec
# docs/superpowers/specs/2026-05-19-wp105-ig-app-launch-stale-uiautomator-design.md
if cur != package:
    settle_deadline = time.monotonic() + 15.0
    settle_start = time.monotonic()
    while time.monotonic() < settle_deadline:
        if _deadline_exceeded():
            break
        time.sleep(1.0)
        cur = _foreground_pkg(target_pkg=package)
        if cur == package:
            self.p.log_event('info',
                f'{step_name}: settled foreground after extended wait',
                meta={'category': 'switcher_settle_wait_recovered',
                      'package': package,
                      'step': step_name,
                      'settle_duration_s': round(time.monotonic() - settle_start, 1)})
            break
```

## Task 3 — расширенный лог при final fail

**File:** `/home/claude-user/autowarm-testbench/account_switcher.py`
**Lines:** 4769-4781 (где сейчас `'не удалось запустить приложение'`)

**Изменения:**

Заменить существующее `account_switch` event на версию с обоими источниками:

```python
# Capture both sources напоследок для evidence
fallback_top = self.p.adb("dumpsys activity activities | grep -m1 -E 'topResumedActivity|ResumedActivity'") or ''
m_fallback = re.search(r'\s([\w\.]+)/[\w\.]+', fallback_top)
pkg_dump_at_fail = m_fallback.group(1) if m_fallback else ''
self.p.log_event('account_switch',
    f'не удалось запустить приложение step={step_name} '
    f'package={package} текущий={cur!r}',
    meta={'package': package,
          'current_pkg': cur,
          'current_pkg_dumpsys': pkg_dump_at_fail,
          'step': step_name})
```

Это backward-compatible — message строка та же, добавлено meta.

## Task 4 — Unit-тесты

**File:** `/home/claude-user/autowarm-testbench/tests/test_account_switcher.py`

**Новый тест-класс или функции:**

```python
def test_open_app_dumpsys_target_uiautomator_stale_returns_true(...):
    """Layer 1: dumpsys видит target, uiautomator stale (launcher) — должен вернуть True."""

def test_open_app_uiautomator_target_dumpsys_launcher_returns_true(...):
    """Layer 1: uiautomator видит target, dumpsys stale — должен вернуть True (симметрия)."""

def test_open_app_both_sources_launcher_returns_false(...):
    """Layer 1: оба источника видят launcher — должен вернуть False (реальный fail)."""

def test_open_app_settle_wait_catches_late_arrival(...):
    """Layer 2: после 3 am-start attempts оба source видят launcher, но через 3s появляется target — settle-wait должен поймать."""

def test_open_app_settle_wait_respects_deadline(...):
    """Layer 2: deadline_s передан и истёк — settle-wait не запускается."""

def test_foreground_pkg_disagree_event_emitted_only_on_mismatch(...):
    """Layer 3: disagree event эмитится при pkg_dump != pkg_ui && target указан."""

def test_open_app_final_fail_logs_both_sources(...):
    """Layer 3: при final fail в meta есть current_pkg_dumpsys."""
```

Mock-стратегия: `_foreground_pkg` остаётся inner-функцией, тестируем через `_open_app` целиком. Mock'аем `self.p.adb` (для dumpsys и am start), `self.p.dump_ui` (для uiautomator XML), `self.p.log_event` (для проверки emits).

## Task 5 — Smoke test на testbench

Скрипт `/tmp/wp105_smoke.py` (одноразовый, не commit'ить):
- Подключиться к phone #19 (testbench, [[reference_adb_remote_server_mode]])
- Force-stop IG: `am force-stop com.instagram.android`
- Закрыть recents: `input keyevent KEYCODE_HOME`
- Запустить _open_app('com.instagram.android', '<launch_activity>', 'wp105_smoke')
- Проверить: `cur == package` returns True, не залип в am-start retry loop
- Также: триггерить искусственное stale (sleep + check) — может не получиться, но смотрим что healthy путь не сломан

## Task 6 — Commit + push в testbench

В `/home/claude-user/autowarm-testbench/`:
1. `git diff --stat` — убедиться что трогаем только `account_switcher.py` + `tests/test_account_switcher.py`
2. `pytest tests/test_account_switcher.py -x -q` — все green
3. `git add account_switcher.py tests/test_account_switcher.py`
4. Commit message:
   ```
   wp105: cross-source foreground check + settle-wait для _open_app

   Layer 1: _foreground_pkg теперь принимает target_pkg и возвращает target
   если EITHER dumpsys OR uiautomator его подтверждает (Samsung uiautomator
   stale до 90s — evidence: 13/13 ig_app_launch_failed имеют ig_foreground
   _recovery success затем _open_app fail через 86s).

   Layer 2: после 3 am-start attempts settle-wait 15s polling — IG arrives
   1-5s после ui dump в screenshot evidence.

   Layer 3: disagree event + dumpsys в meta при final fail для observability.

   WP #105 https://openproject.contenthunter.ru/wp/105
   ```

## Task 7 — Cherry-pick в prod

В `/root/.openclaw/workspace-genri/autowarm/`:
1. `git fetch && git log -5 origin/main` — sanity check
2. Только если нет конфликтов: `git cherry-pick <sha-из-testbench>`
3. PM2 restart: `pm2 restart autowarm` (или соответствующий app per [[feedback_pm2_dump_path_drift]])
4. Auto-push hook отправит в `GenGo2/delivery-contenthunter` ([[reference_autowarm_git_hook]])
5. **NO force-push** ([[feedback_subagent_force_push_risk]])

## Task 8 — Verification window 24h

После prod-деплоя:
1. T+1h: проверить что фейлы `ig_app_launch_failed` не растут (новые таски с этим error_code)
2. T+6h: query events для `switcher_settle_wait_recovered` — сколько раз поймал
3. T+24h: финальная метрика: `SELECT COUNT(*) FROM publish_tasks WHERE error_code='ig_app_launch_failed' AND started_at > deploy_ts`. Если ≥3 fails в 24h после деплоя — фикс неполный, return to Phase 1.
4. Update WP #105 status: Тестирование → Готово после positive verification

## Roll-back

Если в первые 6h после деплоя:
- Резкий рост других IG fails (`ig_target_not_in_picker`, `ig_caption_fill_failed`) — может быть из-за false-positive return из `_open_app` пускающего broken state дальше
- Health-check спам на `switcher_foreground_pkg_disagree`

Rollback: `git revert <sha>` в prod, PM2 restart. Безопасно — нет миграций БД/state.

## Зависимости

- `_ensure_app_foregrounded` — НЕ модифицируется (зависимость не меняется)
- `_dismiss_blocking_overlays` — НЕ модифицируется
- `dump_ui` (publisher_base.py:654) — НЕ модифицируется
- `_open_app_aggressive` (account_switcher.py:1337) — НЕ модифицируется (отдельный путь)

## Out of scope

- Не трогаем YT/TT (yt_app_launch_failed/tt_*) — отдельные категории, fail rate сейчас ниже IG
- Не делаем общий рефакторинг foreground detection (отдельный technical debt)
- Не меняем `OPEN_APP_WAIT_S=4.0` — спроектировано вокруг am-start latency, не stale uiautomator

## Acceptance criteria

- [ ] Все 6 unit-тестов из Task 4 passing
- [ ] Healthy IG-switch на testbench не регрессирует (smoke Task 5)
- [ ] Cherry-pick в prod без конфликтов
- [ ] 24h после prod-деплоя: `ig_app_launch_failed` fails < 2 (vs текущие ~2/день)
- [ ] `switcher_settle_wait_recovered` event фиксируется минимум 1 раз — proof что layer 2 работает
- [ ] WP #105 status → Готово, добавить shipped-комментарий в стиле «Что было не так → Что сделано → Что осталось»
