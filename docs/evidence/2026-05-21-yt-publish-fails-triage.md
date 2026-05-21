# Триаж упавших YouTube-публикаций — 2026-05-21

**Скоуп:** только платформа YouTube, упавшие задачи за сегодня (2026-05-21, утренняя пачка 08–10 МСК).
**Источник:** БД `openclaw` (autowarm), таблицы `publish_tasks` / `publish_queue`; скринкасты + ui-dumps `save.gengo.io`; код `publisher_youtube.py` (prod `main`).
**Исключено по указанию:** `switch_failed_unspecified` / `adb_devices_unreachable` (сетевая проблема, уже починена) — сегодня в выборке не встречалась.

> ⚠️ Регистр платформы различается: `publish_tasks.platform = 'YouTube'`, `publish_queue.platform = 'youtube'`.

## Сводка падений (publish_tasks, status='failed')

Утренняя пачка по сути отработана: **22 done / 3 failed** / 2 running / 1 awaiting_url.

| # | Реальная причина | error_code | Кол-во | Тип |
|---|------------------|-----------|:------:|:----|
| 1 | Бот проваливается на полноэкранный экран **«Добавьте описание»** и не возвращается; цикл редактора ищет «Загрузить», не находит → таймаут на 30-й итерации | `yt_editor_upload_timeout` | **2** | **код** |
| 2 | Аккаунт `axilor.brand@gmail.com` заблокирован Google («Нет доступа к продукту») → YT-приложение не выходит на передний план | `yt_app_not_foregrounded` | 1 | account-health, не код |

Задачи: #8814 (`elcosmetics`), #8821 (`elcosmo_beauty`) — editor-timeout; #8809 (`axilor_brand`) — блок аккаунта.

**Вывод: топ-1 кодовый баг — `yt_editor_upload_timeout` (2 из 3).** Выбран для фикса (WP #117).

## Разбор `yt_editor_upload_timeout` (2 задачи) — анализ логов + скринкаста

Сигнатура (по events + ui-dump + скринкасту обоих задач):
1. Редактор YouTube Shorts достигнут, заголовок заполнен (`title_filled: true`), на экране «Добавьте информацию» видна кнопка «Загрузить».
2. Дальше бот проваливается на **полноэкранный редактор «Добавьте описание»**: в UI-dump остаются только `content-desc` `["Назад", "Хештеги"]` + сфокусированный пустой `EditText`. Кнопки «Загрузить» здесь нет.
3. Бот зависает на этом экране на 20+ итераций цикла (`yt_editor_diag` step 3→24), `ai_unstuck` 3–5 раз бесполезно тапает («to find and tap the Upload/Publish button»), `ai_unstuck_result: true` врёт.
4. На 30-й итерации → `yt_editor_upload_timeout`, задача падает.

Скринкаст подтверждает визуально: главный экран «Добавьте информацию» (заголовок «бокс ELLEVELLE», кнопка «Загрузить») сменяется на пустой экран «Добавьте описание» с «←» сверху и «Хештеги» внизу, на котором бот и зависает до конца.

### Новизна сигнатуры (тренд)

`yt_editor_upload_timeout` за неделю (MSK-день): 16.05=9, 18.05=15, **19–20.05=0** (после WP #80 + WP #113), 21.05=3. **Все 3 случая 21.05 — именно ловушка «Добавьте описание»** (сигнатура с «Хештеги»), которой не было ни 16-го, ни 18-го. Вероятно всплыло после деплоя WP #113 (изменился путь входа в редактор).

### Корневая причина (код)

В editor-loop `publisher_youtube.py` уже есть stuck-counter, который при 4 одинаковых UI делает `KEYCODE_BACK`. Но он строит ключ из `re.findall(r'text="([^"]{2,25})"', ui)` — а на экране «Добавьте описание» все подписи лежат в `content-desc` («Назад»/«Хештеги»), а `EditText` пустой → ключ `[]` → условие `if _yt_cur and _yt_cur == _yt_prev_texts` falsy → счётчик каждую итерацию сбрасывается, авто-BACK **никогда не срабатывает**. Recovery через BACK с этого экрана был только внутри ветки «Добавьте информацию», но если итерация стартует уже на голом desc-редакторе — ни один handler его не распознаёт → провал в generic-фоллбэк «тап Загрузить (791,2051)» по пустоте → таймаут.

## Третье падение (#8809, `axilor.brand@gmail.com`) — не код

`error_code=yt_app_not_foregrounded`. На скринкасте — браузер с формой Google **«Нет доступа к продукту Google»** для `axilor.brand@gmail.com` («доступ к продукту был заблокирован»). Аккаунт ограничен Google → YT-приложение не выходит на передний план. Это account-health, под кодовый фикс не попадает (кандидат на `account_blocks`).

## Фикс — WP #117 (SHIPPED + DEPLOYED 2026-05-21)

- `_yt_on_bare_description_screen(ui)` (staticmethod): детект сигнатуры по text/content-desc нодам — есть «Хештеги»/«Hashtags», нет «Добавьте информацию»/«Add details», нет «Загрузить»/«Upload»/«Опубликовать»/«Publish».
- Guard в начале editor-loop (после диага): на детекте → `KEYCODE_BACK` на metadata-форму, где доступна «Загрузить».
- Kill-switch `YT_DESC_TRAP_GUARD_ENABLED` (default on).
- 8 unit-тестов (`tests/test_yt_desc_trap_detection.py`), RU/EN позитивы + негативы; проверено на реальном ui-dump задачи #8814. Codex-review без замечаний.
- Прод: merge `97f4b5d` (fix `9857cee`) в `GenGo2/delivery-contenthunter` main. Диспетчер `autowarm` (PM2 id=34) работает из `/root/.openclaw/workspace-genri/autowarm`, спавнит свежий python per-task → подхват без рестарта PM2. Прод-smoke: свежий импорт детектит реальный dump #8814.

## Приёмка (verify — утренняя YT-пачка 22.05)

```sql
-- падения yt_editor_upload_timeout с desc-trap сигнатурой должны уйти в 0
SELECT (started_at + interval '3 hours')::date AS msk_day, count(*)
FROM publish_tasks
WHERE platform='YouTube' AND error_code='yt_editor_upload_timeout'
  AND started_at > '2026-05-21 21:00'
GROUP BY 1 ORDER BY 1;

-- success-сигнал фикса: событие escape
SELECT count(DISTINCT pt.id)
FROM publish_tasks pt, jsonb_array_elements(pt.events) e
WHERE pt.platform='YouTube'
  AND (e->'meta'->>'category')='yt_desc_trap_escape'
  AND pt.started_at > '2026-05-21 21:00';
```

Если `yt_editor_upload_timeout` (desc-trap) → 0 и появляются события `yt_desc_trap_escape` → WP #117 в «Готово». Аварийный откат без правки кода: env `YT_DESC_TRAP_GUARD_ENABLED=0`.
