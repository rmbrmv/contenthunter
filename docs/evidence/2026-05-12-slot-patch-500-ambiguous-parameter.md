# 2026-05-12 — Hotfix: PATCH /api/schedule/slots/{id} 500 (AmbiguousParameterError)

Жалоба операторов: https://client.contenthunter.ru/dashboard — «не загружается контент», «слоты невозможно передвинуть на другой день».

## Симптомы

В логах `pm2 logs validator`:
- `INFO: 212.15.61.79:0 - "PATCH /api/schedule/slots/2712 HTTP/1.1" 500 Internal Server Error`
- Traceback: `sqlalchemy.exc.ProgrammingError: <class 'asyncpg.exceptions.AmbiguousParameterError'>: could not determine data type of parameter $3`
- Source: `/root/.openclaw/workspace-genri/validator/backend/src/services/pipeline_reversal.py:68` in `cancel_downstream_for_content`

Оба симптома — **один RC**. Frontend `ClientDashboard.vue:692-694` делает 2 PATCH'а подряд для DnD; первый PATCH падает 500 → catch → `loadSlots()` возвращает UI к старому состоянию → оператор видит "контент не подгружается" и слот не переместился.

## Root Cause

3 SQL-запроса в `cancel_downstream_for_content` имели:

```sql
:keep_slot_id IS NULL
OR (ut.meta->>'slot_id')::int IS DISTINCT FROM :keep_slot_id
```

asyncpg не может infer тип bind-параметра `$N`, который появляется ТОЛЬКО в `IS NULL` / `IS DISTINCT FROM` контексте — оба паттерна не propagate type information обратно к параметру. Результат: `AmbiguousParameterError` на каждом запросе.

**Когда regression попал:** Spec B pipeline_reversal — commits `57d78a1` + `bab23cb` (свежий фича-код). Existing unit-тесты в `test_pipeline_reversal.py` использовали `AsyncMock`/`MagicMock` для `db.execute` — поэтому asyncpg type inference не проверялся, и баг прошёл CI.

## Repro (Phase 3 hypothesis verification)

`/tmp/repro_amb.py`:
```python
async def main():
    conn = await asyncpg.connect("postgresql://openclaw:openclaw123@localhost:5432/openclaw")
    sql_broken = "SELECT 1 ... WHERE ut.content_id = $1 AND ($2 IS NULL OR ...)"
    sql_fixed = "SELECT 1 ... WHERE ut.content_id = $1 AND ($2::integer IS NULL OR ...)"
```

Результат:
- `BROKEN sql: AmbiguousParameterError: could not determine data type of parameter $2`
- `FIXED sql: OK, rows=0`
- `FIXED sql with NULL: OK, rows=0`

## Fix

Commit `71000af → 2280edf` (validator-contenthunter main). Обернуть `:keep_slot_id` в `CAST(... AS INTEGER)` в обоих местах в каждом из 3 SQL'ей:

```sql
CAST(:keep_slot_id AS INTEGER) IS NULL
OR (ut.meta->>'slot_id')::int IS DISTINCT FROM CAST(:keep_slot_id AS INTEGER)
```

## Tests

2 новых live-DB regression теста в `backend/tests/test_pipeline_reversal.py`:
- `test_cancel_downstream_live_db_with_keep_slot_id_int` — keep_slot_id=int → no AmbiguousParameterError
- `test_cancel_downstream_live_db_with_keep_slot_id_none` — keep_slot_id=None → no AmbiguousParameterError

Используют `AsyncSessionLocal` + `content_id=-1` (zero rows touched в prod), rollback after. Без cast оба теста воспроизводят prod error; pytest 6/6 PASS после фикса.

## Deploy

- `git commit 71000af` в `/root/.openclaw/workspace-genri/validator/` (prod-checkout репа GenGo2/validator-contenthunter)
- `git pull --rebase origin main` (remote был ahead `cdda4a5..40230a5`)
- `git push origin main` → `40230a5..2280edf`
- `sudo pm2 restart validator` → process 24 restart=19, online, Application startup complete

## Verify

3 уровня:
1. `/tmp/repro_amb.py` без cast → error, с cast → OK
2. `pytest test_pipeline_reversal.py -v` → 6/6 PASS (2 новых live-DB регрессии + 4 mocked)
3. Validator stderr post-restart чистый, новых `AmbiguousParameterError` за 3 min monitor — нет

## Lessons

- **MagicMock-based тесты не ловят asyncpg type inference bugs.** Если SQL содержит bind-vars в контекстах со слабой типизацией (`IS NULL`, `IS DISTINCT FROM`, `IN ()`), regression тест ДОЛЖЕН компилироваться против реального asyncpg. Mock'и проходят, prod падает.
- **Аналогично [[feedback_validator_test_engine_dispose]]** — live-DB тесты в validator backend требуют `engine.dispose` fixture (autouse в conftest.py); pattern уже есть, надо ему следовать.
- **Codex review этого диффа** должен был поймать (`:keep_slot_id IS NULL` без cast — known asyncpg anti-pattern), но в commits `57d78a1` + `bab23cb` похоже не прогонялся через Codex. Перепроверить процесс для backend Python кода.
