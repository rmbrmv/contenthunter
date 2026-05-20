# YouTube publish-fails triage — 2026-05-20

**Scope:** все YouTube-задачи на публикацию, упавшие за сегодня (`platform='YouTube'`,
`status='failed'`, `started_at::date = 2026-05-20`). БД `openclaw@localhost`.

## Итог за день

- **74 failed**, 2 done. Success-rate ≈ **2.6%** (катастрофа).
- Доминирующая ошибка — `yt_editor_not_reached`: **62 из 74 (84%)**.

### Разбивка по терминальной категории (resolved из события «Публикация завершилась с ошибкой»)

| Терминальная категория | Кол-во | Доля | Примечание |
|---|---:|---:|---|
| **yt_editor_not_reached** | **62** | 84% | ← выбрано для фикса |
| yt_create_menu_not_reached | 5 | 7% | территория WP #87 (FAB/create-menu) |
| yt_target_not_in_picker_after_scroll | 3 | 4% | account-switch picker, целевой акк не найден |
| publish_failed_generic | 2 | 3% | **игнор**: 8553=`adb_device_not_ready` (сеть), 8672=единичный switch-mismatch |
| yt_accounts_btn_missing | 1 | — | account-switch |
| yt_app_not_foregrounded / no-final | 1 | — | foreground |

`switch_failed_unspecified` (ADB preflight `adb_devices_unreachable`) — по указанию исключён
как уже починенная сетевая проблема.

## Регрессия, а не давняя проблема

Динамика по дням (`editor_not_reached` появился ровно когда WP #80 ввёл этот error_code):

| День | failed | editor_not_reached | done |
|---|---:|---:|---:|
| ≤ 2026-05-17 | разное | **0** | здоровое (18–55/день) |
| 2026-05-18 | 60 | 6 | 13 |
| 2026-05-19 | 215 | **85** | 1 |
| 2026-05-20 | 74 | **62** | 2 |

Окно совпадает с серией YT-правок: WP #80 (PR #68), WP #87 (PR #79 + hotfix #83), WP #88 (PR #81).
Релевантные коммиты в `publisher_youtube.py`:
- `40ab802` fix(yt-publisher): `_is_create_menu_open` detector защищает tap_element
- `0c01f7e` fix(yt-publisher): `_verify_yt_editor_reached` guard перед editor loop
- `50f 1cce` fix(yt-publisher): `_verify_yt_editor_reached` kb-probe + regression test

## Сигнатура (100% по всем 62)

Единый кодовый путь:
```
done matched (account switched) → on profile screen
→ yt_pre_upload_state_normalized
→ yt_create_menu_absent_skip_tap        # _is_create_menu_open()==False → Path B fallback
→ (Shell_UploadActivity intent: am force-stop + am start -n …Shell_UploadActivity SEND video/mp4)
→ yt_editor_not_reached
```
- `top_activity` на момент фейла — **всегда** `…creationmodes.main.CreationModesActivity` (62/62).
- `edit_fields_count` — **всегда 0**.
- разброс: 62 фейла на **51 устройстве**, 8 raspberry, 62 разных аккаунта/проекта → системно (код), не девайс/аккаунт.

## Визуальный анализ (скринкаст task 8551, @oraclevisionn)

Кадры (device-time):
- 10:42 — лаунчер;
- 10:43–10:44 — экран профиля YT (аккаунт `@oraclevisionn` переключён успешно, нижний навбар «+»);
- 10:45 — **экран обрезки Shorts**: сверху «← Кадрировать», снизу ползунок «16.5s» +
  «Перетащите ползунок в нужное место», справа внизу кнопка **«Далее»**;
- 10:45 → 10:47 (конец записи) — **завис на экране обрезки, «Далее» так и не нажата**.

Аномалия дампа: видимый экран = тримминг, но `all_texts` uiautomator-дампа = домашняя лента
YouTube (реклама/рекомендации). `CreationModesActivity` воспроизводит видео → uiautomator не
получает idle-state → отдаёт XML другого слоя. Из 62: «Далее» в дампе видна лишь у 18, «Кадрировать»
у 12 — uiautomator на этом экране ненадёжен.

Скринкасты-примеры: `…/screenrecords/youtube/task8551…`, `task8552…`, `task8554…` (есть у 8/62).

## Корень

`publisher_youtube.py`, `publish_youtube_short()`:

1. `_ensure_correct_account()` теперь оставляет бота на **экране профиля**, а не на create-menu →
   `_is_create_menu_open()` == False → ветка **Path B**: `yt_create_menu_absent_skip_tap` →
   fallback `am start -n …Shell_UploadActivity -a SEND video/mp4 …` (строки ~1269–1300).
2. Интент `Shell_UploadActivity` для Shorts приземляется на **`CreationModesActivity`** (экран обрезки
   «Кадрировать»/«Далее») — это легитимный промежуточный шаг.
3. Перед editor-loop стоит fail-fast guard **`_verify_yt_editor_reached()`** (WP #80 Layer 3, строки
   1133–1224, вызов 1334–1340). Он распознаёт редактор только по:
   - EditText `resource-id` ∈ {title, description, caption, compose};
   - тексту ∈ {«Добавьте название», «Добавьте описание», «Загрузить», …};
   - `topResumedActivity` ∈ {`uploadactivity`, `shareactivity`, `composeactivity`}.
4. Экран обрезки `CreationModesActivity` **не подходит ни под одно**: активити нет в allowlist,
   uiautomator не читает видео-поверхность (стейл-лента → `edit_fields_count=0`, нет текст-маркеров).
   → `_verify_yt_editor_reached()` возвращает `(False, …)` → caller делает `return False` →
   `yt_editor_not_reached`.
5. **При этом** editor-loop (строки 1348–1369) уже умеет обрабатывать `CreationModesActivity`:
   детектит активити и тапает «Далее» (UIAutomator → fallback coord `933,2103`).
   **Но до него управление не доходит** — verify-guard бьёт раньше.

**Суть: guard `_verify_yt_editor_reached()` не считает `CreationModesActivity` (экран обрезки)
валидным «по пути к редактору» состоянием и фейлит до того, как сработает уже существующая
логика прохода «Далее».**

## Направление фикса (для WP, не реализовано)

- В `_verify_yt_editor_reached()` трактовать `CreationModesActivity` как «on track»: не фейлить, а
  прогонять экран обрезки через тап «Далее» (повтор существующей логики строк 1348–1369), и только
  потом проверять editor-маркеры; ИЛИ
- Перенести проход `CreationModesActivity → Далее` ПЕРЕД verify-guard, чтобы тримминг гасился до
  проверки editor-маркеров.
- Учесть, что uiautomator на `CreationModesActivity` слеп → опираться на `topResumedActivity` +
  coord-тап «Далее» (933,2103), не на текстовый дамп.
- Kill-switch env-флагом по паттерну прошлых YT-WP.

## Запросы (воспроизведение)

```sql
-- дневной разбор
SELECT status, count(*) FROM publish_tasks
WHERE platform='YouTube' AND started_at::date=current_date GROUP BY status;

-- терминальная категория
WITH t AS (SELECT id, error_code, events FROM publish_tasks
  WHERE platform='YouTube' AND status='failed' AND started_at::date=current_date)
SELECT (SELECT e->'meta'->>'category' FROM jsonb_array_elements(t.events) e
  WHERE e->>'msg'='Публикация завершилась с ошибкой' ORDER BY e->>'ts' DESC LIMIT 1) AS cat,
  count(*) FROM t GROUP BY cat ORDER BY count DESC;
```
