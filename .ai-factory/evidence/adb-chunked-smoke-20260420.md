# ADB chunked-push — post-deploy smoke (48h)

**Сборка:** 2026-04-20 ~05:30 UTC (≈33h после deploy commit `c654e74` 2026-04-19 ~20:04 UTC).
**Контекст:** T15 из `autowarm/.ai-factory/plans/infra-adb-chunked-push.md:170`.
**Источник:** план-потомок `contenthunter/.ai-factory/plans/open-followups-20260420.md` T3.

## TL;DR — 🔴 **FAIL, критично**

**Chunked-push полностью сломан в проде.** Все 30 попыток chunked push за 48h падают с `TypeError: DevicePublisher.adb() got an unexpected keyword argument 'shell'`. Причина — новые callers в `publisher.py:743/768/784/804` передают `shell=True` в `self.adb()`, но `DevicePublisher.adb(self, cmd, timeout=15)` **не принимает** такой kwarg (см. `publisher.py:453`). Тесты (`test_adb_push_chunked.py` — 10 passed) **не ловят баг**, так как мокают `self.adb` целиком.

**Регрессия ограниченная:** канари-probe и fast-path работают корректно (их не трогали). Проблема активизируется только когда canary детектит медленный канал ИЛИ размер файла >threshold → тогда fallback на chunked → TypeError → failed push. До коммита `c654e74` в этих условиях просто долго таймаутился direct push (iff вообще доходил до timeout).

## Факты

### A. Event distribution — 48h, `adb_push_%`

```
            cat             | n
----------------------------+-----
 adb_push_chunked_started   | 17  (4 canary_slow + 13 size_gt_threshold)
 adb_push_chunked_exception | 30  (все — TypeError)
```

Ни одного `adb_push_chunked_success` / `adb_push_chunked_done` / `adb_push_chunked_failed` за 48h. **17 сессий стартовали, 30 exception-событий записано** (multiplier = каждый push роняется на первом же chunk + дубли от разных call-points).

### B. Сэмпл exception-сообщения (task 444, Instagram, RFGYB07Y5TJ)

```
adb_push_chunked_exception: DevicePublisher.adb() got an unexpected keyword argument 'shell'
```

Затронутые задачи: #444 (IG), #423 (YT), + ещё 13 разных. Платформы — все три (IG/YT/TT), т.е. баг платформонезависим.

### C. Root cause — signature mismatch

```python
# publisher.py:453
def adb(self, cmd: str, timeout: int = 15) -> Optional[str]:
    ...
```

**Нет `shell=` параметра.** Но в chunked-push helper'ах:
- `publisher.py:743` — `cat_out = self.adb(cat_cmd, shell=True, timeout=60)`
- `publisher.py:768` — `self.adb(append_cmd, shell=True, timeout=30) is None`
- `publisher.py:784` — `remote_md5_out = self.adb(f'md5sum "{remote_path}"', shell=True, timeout=30)`
- `publisher.py:804` — `self.adb(f'rm -f "{remote_path}"', shell=True, timeout=15)`

Правильный convention в остальном коде — префикс `'shell '` прямо в команде (см. `publisher.py:3835/3909/4630` и т.д.):
```python
self.adb('shell input keyevent KEYCODE_BACK')  # works
```

### D. Тесты — 10 passed локально, ложно-зелёные

```
tests/test_adb_push_chunked.py: 10 passed in 1.01s
```

Все 10 тестов мокают `self.adb` через `unittest.mock.patch`, и mock принимает любые kwargs → баг в вызовах `shell=True` невидим. **Нужен тест, который проверяет, что вызовы проходят через реальный `DevicePublisher.adb` signature** — например через `inspect.signature` assertion или через частичный mock без `spec=`.

### E. Наблюдаемость — SQL-скрипт сам ломается

```
psql: scripts/adb_push_chunked_48h.sql
  ERROR: column pt.raspberry_number does not exist (lines 65, 111, 148)
```

Три секции скрипта ссылаются на несуществующую колонку `pt.raspberry_number`. В таблице есть `raspberry` (integer) без суффикса `_number` (см. `\d publish_tasks:27`). Acceptance criterion «observability SQL создан» **формально PASS (файл есть)**, но 4/9 секций не отрабатывают.

## Impact

- **Все media >5MB** (13 case'ов size_gt_threshold) + **4 случая canary_slow** в окне 48h → 17 задач провалили push_media. Реальное влияние: часть из них могла доехать direct-путём с длинным timeout'ом, но любая задача, которая реально уперлась в сетевой лосс → хардфейл.
- Основная цель деплоя T1-T14 (обход packet loss на hop 4 до 82.115.54.26, память `project_adb_push_network_issue`) — **не достигнута**.

## Рекомендуемый фикс (scope — НЕ в T3, отдельный fix-plan)

**Вариант 1 (минимальный):** заменить `self.adb(cmd, shell=True, timeout=T)` → `self.adb(f'shell {cmd}', timeout=T)` в 4 точках. Простой 4-line refactor.

**Вариант 2 (архитектурный):** добавить в `DevicePublisher.adb()` опциональный kwarg `shell: bool = False`; при `shell=True` префиксовать команду `'shell '`. Изменяет signature, требует осторожности.

**Тест:** добавить в `tests/test_adb_push_chunked.py` проверку через `mock.create_autospec(DevicePublisher.adb)` или `assert_called_with` без wildcard kwargs.

**SQL-fix:** `pt.raspberry_number` → `pt.raspberry` в `scripts/adb_push_chunked_48h.sql` lines 65/111/148.

## Action items

1. **Заводить отдельный fix-plan:** `/aif-fix "adb_push chunked TypeError: shell kwarg не поддерживается DevicePublisher.adb() (publisher.py:743/768/784/804)"`
2. **НЕ помечать T15 ✅** в `autowarm/.ai-factory/plans/infra-adb-chunked-push.md:170` — остаётся ⏳ до фикса.
3. **Memory:** `project_adb_push_network_issue.md` оставить без изменений (проблема сети остаётся, просто наш workaround не работает).
4. **Rollback-вариант** на случай, если fix задержится: revert commit `c654e74` — fast-path остаётся прежним direct push'ом как раньше.
5. **Acceptance Criteria умбрелла-плана T3** — отметить как FAIL с cross-ref на этот evidence.

## Метаданные

- Deploy commit: `c654e74` (autowarm, feat chunked-push) + `1165dbf` (observability SQL) — оба 2026-04-19 ~20:04 UTC.
- DB: `openclaw@localhost/openclaw`.
- Связанные evidence: `farming-baseline-20260419.md` (baseline fails), память `project_adb_push_network_issue`.
