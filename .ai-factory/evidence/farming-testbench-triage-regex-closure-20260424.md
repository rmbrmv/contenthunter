# farming-testbench — T24 completion: regex gap closure

**Session:** farming-testbench-phone171-20260423 (продолжение 2026-04-24)
**Branch:** `feature/farming-testbench-phone171` / `testbench` (autowarm)
**Previous handoff:** `farming-testbench-SESSION-RESUME-20260423.md`

## Контекст

Сессия остановилась после T23 prod deploy. Orchestrator работал с cadence 15 мин ~14 часов для smoke-verify. Задача T24 — проверить что накопленные fail'ы классифицируются, и закрыть regex gap для `wa_account_read_fail`, найденный в session end.

## Что было в DB на старте продолжения

Накопилось `98 failed` testbench-tasks за ночь. Агрегаты по events:

| msg | count |
|---|---|
| `Не удалось прочитать аккаунт YouTube после 3 попыток` | 42 |
| `Не удалось прочитать аккаунт TikTok после 3 попыток` | 40 |
| `Аккаунт @Ivana-o3j не совпадает с активным` | 21 |
| `Аккаунт @Born-i6i3n не совпадает с активным` | 21 |
| `Аккаунт @user899847418 не совпадает с активным` | 20 |
| `Аккаунт @born7499 не совпадает с активным` | 20 |
| `Аккаунт @ivana.world.class не совпадает с активным` | 4 |
| `Аккаунт @born.trip90 не совпадает с активным` | 2 |
| `Не удалось прочитать аккаунт Instagram после 3 попыток` | 1 |

Две категории событий не имели triage-правил:
1. **`wa_account_read_fail`** (83 events, meta.category set) — switcher не смог прочитать активный аккаунт после 3 cold-restart попыток.
2. **Account mismatch** (88 events, meta.category = NULL) — switcher вернул success, но активный аккаунт оказался другим.

## Изменения

### 1. `farming_error_codes` — 4 новых строки

```sql
INSERT INTO farming_error_codes (code, severity, retry_strategy, is_known, is_auto_fixable, description) VALUES
  ('tt_account_read_fail', 'error', 'backoff', TRUE, TRUE,  '...TT switcher read_active_tt...'),
  ('yt_account_read_fail', 'error', 'backoff', TRUE, TRUE,  '...YT bottom-nav/Settings-activity fallback...'),
  ('ig_account_read_fail', 'error', 'backoff', TRUE, TRUE,  '...IG read_active_ig...'),
  ('account_mismatch_after_switch', 'error', 'backoff', TRUE, FALSE,
    'Switcher success, но активный аккаунт другой. Возможен зависший чужой профиль или sticky pm package state.');
```

### 2. `farming_triage_classifier.py::MSG_REGEX_RULES` — 4 новых правила

```python
# account-read failures (switcher cold-restart exhausted) — по-платформенные.
(re.compile(r'прочитать аккаунт\s*tiktok|wa_account_read_fail[^}]*tiktok', re.I),
 'tt_account_read_fail'),
(re.compile(r'прочитать аккаунт\s*youtube|wa_account_read_fail[^}]*youtube', re.I),
 'yt_account_read_fail'),
(re.compile(r'прочитать аккаунт\s*instagram|wa_account_read_fail[^}]*instagram', re.I),
 'ig_account_read_fail'),
# switcher вернул success, но активный аккаунт оказался другим
(re.compile(r'не совпадает с активным|account.*mismatch.*after.*switch|@\S+\s+не активен.*не удалось переключиться', re.I),
 'account_mismatch_after_switch'),
```

**Nuance:** первая попытка regex (`tt.*account.*read.*fail`) давала false-positive — слово `a**tt**empts` в meta-string матчилось. Заменил на anchored `прочитать аккаунт\s*tiktok` и `wa_account_read_fail[^}]*tiktok` (не выходим за пределы dict-repr).

### 3. `--scan-recent --window-min 720` результаты

Из 40 tasks в окне 12 часов classify_task вернул коды для **всех** failed → создано **4 investigations** (dedup per-code via `emit_farming_error`):

```
          error_code           | status | count
-------------------------------+--------+-------
 account_mismatch_after_switch | open   |     1
 ig_account_read_fail          | open   |     1
 tt_account_read_fail          | open   |     1
 yt_account_read_fail          | open   |     1
```

### 4. Восстановление cadence

```sql
UPDATE system_flags SET value='240' WHERE key='farming_orchestrator_cadence_min';
```

```bash
sudo pm2 restart autowarm-farming-orchestrator
# → "next tick in 4800 sec (cadence 240 min / 3 platforms)"
```

Стенд оставлен **running** с prod-default cadence (не останавливал) — пусть продолжает мониторить, fail'ы будут классифицироваться автоматически.

## Deploy

- Commit `6747a19` в `/root/.openclaw/workspace-genri/autowarm/` (branch `testbench`).
- git-hook auto-push → `GenGo2/delivery-contenthunter`.
- Скрипт ad-hoc (не service) — restart не требовался.

## Follow-ups (не блокеры T24)

1. **app_launch_failed (10 events)** — событие эмитится как `type=status` не `type=error`, triage их не видит. Если нужно классифицировать — расширить classify_events: при `task.status='failed'` и финальном status-event с msg "Не удалось запустить" эмитить `farming_app_launch_failed`. Отложено.
2. **account_mismatch_after_switch is_auto_fixable=FALSE** — требует switcher-side fix, agent_diagnose может дать hint но apply не будет пытаться автоматом. Ожидается ручной разбор investigation.
3. **Почему YT/TT account read fails массовые** — 83 фэйла за 14 часов, это ~1 каждые 10 мин при cadence 15. Нужна отдельная сессия для починки switcher.py (read_active_{tt,yt}) — регистрация в memory `project_revision_phone171_backlog.md`.

## Итог T24 ✅

- Live-verify ✅ (98 failed прогонов на реальном phone #171).
- Regex gap закрыт ✅ (4 новых кода + 4 regex правила).
- Investigations создаются ✅ (4 штуки, dedup).
- Cadence = 240 ✅ (prod default).
- Orchestrator running ✅ (`pid 1634671`).

**T24 переведён в ✅ completed в плане** (`.ai-factory/plans/farming-testbench-phone171-20260423.md:385`).
