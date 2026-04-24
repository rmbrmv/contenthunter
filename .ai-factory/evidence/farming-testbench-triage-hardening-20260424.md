# farming-testbench — triage hardening (follow-ups после T24)

**Session:** farming-testbench-phone171-20260423 (продолжение 2026-04-24, follow-ups)
**Commits в autowarm (branch testbench):**
- `9eed838` — type=status terminal marker support + RU launch-fail regex
- `836b414` — canonical dedup mismatch vs read_fail + is_auto_fixable flip

## 1. `app_launch_failed` ловится из `type=status` events

**Проблема:** warmer.py:2535 при `initialize()` failure эмитит **только** `update_status('failed', 'Не удалось запустить приложение')` — никакого `log_event('error', ...)`. Triage смотрел только на `type=error` events и пропускал эти 10 task'ов.

**Фикс:** `classify_events` теперь принимает `type=status` events, но только если msg начинается с маркера `→ failed` (терминальная причина, не running/completed). Regex `farming_app_launch_failed` расширен русским alt `не удалось запустить приложение`.

```python
if etype == 'error':
    pass
elif etype == 'status' and (e.get('msg') or '').startswith('→ failed'):
    pass
else:
    continue
```

Dedup на `codes_found` защищает от дублей, если при failed task и error-event и terminal status одновременно дают один код.

**Результат:** `--scan-recent --window-min 720` создал новое investigation `farming_app_launch_failed` с 12 fixture tasks.

## 2. `account_mismatch_after_switch` — canonical dedup

**Проблема:** msg `"Аккаунт @X не совпадает с активным — задача прервана"` эмитится в warmer.py:2547 **всегда** когда `verify_and_switch_account()` возвращает False. Это покрывает **два разных** cases:

- **Case A (read failed):** `get_current_X_account()` вернул None 3 раза → warmer сначала эмитит `wa_account_read_fail` + RU msg, затем возвращает False → warmer эмитит финальный terminal event с mismatch msg.
- **Case B (switch failed):** read OK, но `switch_X_account()` не смог переключить → verify возвращает False → warmer эмитит mismatch msg (без read_fail event).

Regex `account_mismatch_after_switch` ловил оба case'а, поэтому investigation раздувалась дубликатами case A (которые уже покрыты `tt/yt/ig_account_read_fail`).

**Breakdown 42 task'ов с mismatch code:**

| has_read_fail | has_mismatch | count | тип |
|---|---|---|---|
| t | t | 36 | case A (дубликаты) |
| f | t | 6 | **case B** (настоящий switch failed) |

**Фикс:** `classify_events` после сбора codes убирает `account_mismatch_after_switch` если в codes есть любой из `{tt,yt,ig}_account_read_fail` (canonical cause wins):

```python
read_fail_codes = {'tt_account_read_fail', 'yt_account_read_fail', 'ig_account_read_fail'}
if any(c in read_fail_codes for c in codes_found):
    codes_found = [c for c in codes_found if c != 'account_mismatch_after_switch']
```

**Investigation пересоздано:** старое (42 task_ids, раздутое) закрыто через `UPDATE status='closed_fixed'`. После `--scan-recent` новое investigation имеет ровно **6 fixture tasks**, все **Instagram**:
- ivana.world.class × 4
- born.trip90 × 2

Это конкретный, actionable bug: `switch_instagram_account()` в `account_switcher.py` иногда читает правильно active account, видит mismatch, пытается переключиться и возвращает False. **Следующая сессия** может погрузиться в switch_instagram_account и посмотреть retry-loop / UI navigation.

## 3. `is_auto_fixable` flip

```sql
UPDATE farming_error_codes SET
  is_auto_fixable = TRUE,
  description = 'switch_<platform>_account() вернул False: switcher прочитал активный аккаунт, но не смог переключиться на нужный. Кандидат на patch switcher. Diagnose может предложить fix, apply работает в review-mode (safe).'
WHERE code='account_mismatch_after_switch';
```

**Rationale:** After dedup, код identifies чистый case B — actionable bug в switcher.switch_X_account. Diagnose может сгенерить `## Proposed Fix` секцию, apply ставит её в `farming_fixes` с `enabled=FALSE` для review (это MVP mode — никакие файлы не правятся автоматически, оператор вручную enable через UI). Safe.

## Final investigations state

```
          error_code           |    status    | occurrences | n_tasks
-------------------------------+--------------+-------------+---------
 account_mismatch_after_switch | closed_fixed |          79 |      42  (stale — до dedup)
 account_mismatch_after_switch | open         |           6 |       6  (чистые case B, все IG)
 farming_app_launch_failed     | open         |          23 |      12  (новое)
 ig_account_read_fail          | open         |           3 |       1
 tt_account_read_fail          | open         |          47 |      17
 yt_account_read_fail          | open         |          50 |      18
```

## Follow-ups для будущих сессий

1. **switch_instagram_account() investigation** — 6 чистых case B. Смотреть retry-loop, UI-navigation в `account_switcher.py`.
2. **switcher read_active_{tt,yt}** — 17+18 case A. Главный источник false-fails (по-прежнему).
3. **apply logic upgrade** — сейчас review-only. После накопления confident proposals (≥7/10) имеет смысл добавить opt-in auto-apply с git commit + rollback.
