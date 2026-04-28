# Evidence — `_is_specific_reel_url` @staticmethod fix (2026-04-28)

**Branch (prod copy):** `feature/paginated-tables-etap2-20260428` (соседняя сессия)
**Commit (prod, auto-pushed → GenGo2/delivery-contenthunter):** `3dcaf6e`
**Diff:** `publisher_base.py` +1 line (`@staticmethod`)

---

## Симптом

Задача `1534` (YT, `EleonoraDemidova`, phone #19) завершилась со `status='done'` и **пустым `post_url`**. Аналогично могла бы упасть любая публикация, начатая после prod-деплоя `bcb5a2d` (2026-04-26 18:56 UTC).

## Корень

Refactor `bcb5a2d` (publisher.py split) вынес `_is_specific_reel_url` из module-level в `BasePublisher` как метод класса, но **`self` к сигнатуре не добавили**:

```python
def _is_specific_reel_url(url: str) -> bool:   # publisher_base.py:2402 — НЕТ self
```

Реальный вызов в `_save_post_url:2451` через `self._is_specific_reel_url(url)` → Python подставляет `self` первым аргументом → `TypeError: takes 1 positional argument but 2 were given`. Исключение проглатывается общим `except Exception` на строке 2476 (`log.error`, без `log_event`), `UPDATE post_url` не доходит до БД, завершение `run_publish_task` ставит `status='done'` с пустым URL.

Тесты не поймали (`test_account_switcher_tt.py:387` etc.), потому что вызывают через класс: `DevicePublisher._is_specific_reel_url(url)` — там 1 аргумент, проходит даже без `self` в сигнатуре.

## Окно регрессии

| От | До | Длительность |
|----|----|----|
| `bcb5a2d` (2026-04-26 18:56 UTC) | `3dcaf6e` (2026-04-28 17:13 UTC) | ~46 ч |

Все задачи, у которых `_save_post_url` пытался отработать (включая partial-URL fallback на IG/TT/YT), теряли запись `post_url` в БД. Visible side-effect: `awaiting_url`-задачи становились `done` с пустым URL → yt-dlp поллер не подбирал.

## Фикс

```diff
+    @staticmethod
     def _is_specific_reel_url(url: str) -> bool:
```

Тело метода `self` нигде не использует. Тесты вызывают через класс — для `@staticmethod` это легитимно (вызов `Cls.method(url)` и `instance.method(url)` оба передают только `url`).

## Smoke

```
1) class.method(url):     True
2) self.method(url):      True
3) profile fallback:      False  ← partial → status='awaiting_url'
```

Targeted tests: `pytest tests/test_account_switcher_tt.py -k is_specific_reel_url` → **6/6 passed**.

## Validation на проде

| task | platform | account | до фикса | после фикса |
|------|----------|---------|----------|-------------|
| 1534 | YouTube | EleonoraDemidova | `done` / `post_url=''` | recovery via UPDATE: `awaiting_url` / `…@EleonoraDemidova/shorts` |
| 1511 | YouTube | ane_cole | (до этого fail на `random` — починен `fcfa851`) | `awaiting_url` / `…@ane_cole/shorts` ← ✅ автоматом |

Контраст 1534 vs 1511 — тот же flow (clipboard пуст 3 раза → profile fallback), но 1511 уже отработал корректно: `_save_post_url` дошёл до `UPDATE`, статус правильный `awaiting_url`, yt-dlp поллер подберёт.

## Recovery 1534

```sql
UPDATE publish_tasks
SET post_url='https://www.youtube.com/@EleonoraDemidova/shorts',
    status='awaiting_url',
    updated_at=NOW()
WHERE id=1534;
```

Финальный shortcode `/shorts/<id>` подгрузил yt-dlp поллер автоматом (подтверждено пользователем).

## Lessons

1. **Class-level test calls маскируют instance-call регрессии.** Тесты вызывали `Cls.method(url)` — без `self` в сигнатуре это работает; реальный код через `self.method(url)` падает. При рефакторе module-fn → method тестировать через инстанс.
2. **Silent `except Exception` в save-helpers слепит триаж.** `_save_post_url` ловит всё и пишет только `log.error` — нет `log_event`, нет следа в `events` JSONB. 46 часов регрессии прошли без алёрта. Любое "save" должно эмитить `log_event` ДО swallow.
3. **Prod-копия может бежать с feature-ветки.** `/root/.openclaw/workspace-genri/autowarm` checkout = `feature/paginated-tables-etap2-20260428`, не main. Перед commit'ом — `git status -sb` обязательно, чтобы не задеть соседа и понять, какая ветка попадёт в auto-push.
