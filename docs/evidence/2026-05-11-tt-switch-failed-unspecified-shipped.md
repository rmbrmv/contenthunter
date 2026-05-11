# TT switch_failed_unspecified Root Cause — Shipped 2026-05-11

**PR:** [GenGo2/delivery-contenthunter#33](https://github.com/GenGo2/delivery-contenthunter/pull/33)
**Merge commit:** `d33719a` (squash; branch `fix/tt-grid-cell-staticmethod-20260511` deleted)
**Prod state:** `/root/.openclaw/workspace-genri/autowarm` @ `d33719a`; PM2 autowarm (id=34) restarted

## Context

P0 разведка 2026-05-11 нашла root cause `switch_failed_unspecified` 8/24h на TT (top нерешённый TT error_code после PR #32 ship).

5 свежих task'ов (4632, 4633, 4640, 4646, 4649) — все на raspberry=9, разные аккаунты (`my_clickpay`, `clickpay_express`, `just_clickpay`, `clickpay_team`, `clickpay_life`), все падают на post-publish этапе с одним и тем же event'ом:

```json
{
  "type": "error",
  "msg": "Критическая ошибка: TikTokMixin._find_tiktok_first_grid_cell() missing 1 required positional argument: 'self'",
  "meta": {"category": "critical_exception", "platform": "TikTok", "error": "..."}
}
```

## Two bugs

### Bug #1: `@staticmethod` decorator on instance method

`publisher_tiktok.py:1542-1544`:
```python
    @staticmethod

    def _find_tiktok_first_grid_cell(self) -> Optional[tuple]:
        ...
        raw = self.dump_ui()  # line 1549 — uses self!
```

Метод использует `self.dump_ui()` — это instance method, не static. Вызов `self._find_tiktok_first_grid_cell()` (line 1608, `_auto_get_tiktok_url`) raises `TypeError: missing 1 required positional argument: 'self'`. Каждая попытка получить post URL после публикации падала.

**Fix:** удалён `@staticmethod` decorator (+ blank line).

### Bug #2: Exception handler ordering — error_code mask

`publisher_base.py:4266-4272`:
```python
except Exception as e:
    log.error(f'Критическая ошибка: {e}')
    self.update_status('failed', ...)  # ← Triggers _set_error_code_from_events()
    self.log_event('error', ..., meta={'category': 'critical_exception', ...})  # ← Runs AFTER
```

`update_status('failed')` триггерит `_set_error_code_from_events()` (publisher_base.py:1900+), который сканирует events JSONB за первым event с `type='error'` и extract'ит `meta.reason` или `meta.category`. На этот момент error event ещё не logged → fallback на `'switch_failed_unspecified'` (line 1927), маскируя реальный `critical_exception`.

**Fix:** swap order — `log_event` ПЕРЕД `update_status`. Теперь mapping находит correct category.

## Combined impact

Bug #1 alone — 8/24h crashes (real failures). Bug #2 alone — masks future critical_exceptions с любого code path (диагностика становится невозможной).

После fix: bug #1 устранён полностью; bug #2 гарантирует что любые future critical_exception surface с правильным `error_code='critical_exception'` (или whatever meta.category был emitted) вместо generic mask.

## Test plan

`tests/test_publisher_tt_grid_cell_method.py` — 3 regression tests:
1. `test_find_tiktok_first_grid_cell_not_staticmethod` — class dict check
2. `test_find_tiktok_first_grid_cell_callable_with_self` — actual call с mocked `dump_ui`, no TypeError
3. `test_critical_exception_logs_event_before_update_status` — source-grep anchored на `'critical_exception'`, verifies log_event position before update_status

46/46 music-rights tests regression unchanged.

## Audit

`grep` через все publisher_*.py + account_switcher.py: НЕТ других `@staticmethod` + self mismatches.

## Success metric

- `switch_failed_unspecified` count за 24h после merge → ожидание dramatic drop (was 8/24h)
- `critical_exception` events начнут появляться в error_code distribution для legit crashes (вместо generic mask)
- Если новые crashes — теперь видим конкретную error.category в события вместо guessing

## Related

- Spec: нет (small concrete bug fix, не нужен)
- Plan: нет
- Discovery: P0 Explore subagent 2026-05-11 (task_id 24 в session task list)
- Memory updates: `project_tt_switch_failed_unspecified_fixed.md` (this PR + diagnostics)
