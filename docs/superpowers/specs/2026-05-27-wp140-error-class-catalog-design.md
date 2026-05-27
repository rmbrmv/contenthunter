# WP #140 — Классификатор error-кодов: добить недостающие коды в `publish_error_codes`

**Дата:** 2026-05-27
**Статус:** дизайн утверждён (Данил), переход к плану реализации
**Репозиторий кода:** `GenGo2/delivery-contenthunter` (autowarm). Testbench: `/home/claude-user/autowarm-testbench/`. Прод: `/root/.openclaw/workspace-genri/autowarm/` (ветка `main`, pm2 id=1).
**Спавн:** OpenProject #166 — оптимизация таксономии/нейминга кодов ошибок (вынесено из открытых заметок ниже).

---

## 1. Контекст и проблема

Авто-движок ретраев (WP #108, в «Тестировании» с 22.05) решает «ретраить падение или отдать в ручную выкладку» по полю `publish_tasks.error_class`. Класс резолвится из справочника `publish_error_codes` по `code = error_code` с фолбэком `COALESCE(..., 'unknown')` (`publisher_base.py:2168-2174`).

Ряд **реальных** прод-кодов отсутствует в справочнике → дефолтятся в `unknown` → трактуются как transient → ретраятся в пределах лимита (3/сутки/класс × окно 2 дня) вместо ухода в ручную. Пример: `pq#5069` с `yt_picker_target_absent` крутился как `unknown`.

## 2. Факты движка (сверено по коду, не по памяти)

`retry_decision.js` (`decideRetry`, чистая функция):

```
STRUCTURAL = {banned, ui_changed}  → action 'handoff' СРАЗУ, в любое время, не тратя ретраи
                                      (исключение: fixed_at реанимирует баг → не структурная)
TRANSIENT  = {network, rate_limited, unknown} → ретраи в пределах лимитов;
             окно 2 дня исчерпано      → handoff (window_exhausted)
             дневной лимит по классу   → wait (до завтра)
```

**Следствия:**
- `network` и `unknown` ведут себя в движке **идентично** (оба TRANSIENT). Реальная развилка — STRUCTURAL vs TRANSIENT; конкретный лейбл внутри группы — семантика/отчётность.
- `severity` и `retry_strategy` — описательные колонки (существуют ДО WP #108), движок их **не читает**. Доказательство: `ig_editor_timeout` имеет `retry_strategy='immediate'`, но как `ui_changed` уходит в handoff сразу.
- `unknown` ≠ «вечно»: ретраит 2 дня, потом handoff. Формулировка спеки «после лимита» для `ui_changed` неверна — он хэндофится на первом падении.

## 3. Состояние справочника (факт)

`publish_error_codes`: PRIMARY KEY (`code`), 9 колонок, 63 строки.
CHECK-констрейнты:
- `error_class ∈ {network, ui_changed, banned, rate_limited, unknown}`
- `severity ∈ {info, warn, error, critical}`
- `retry_strategy ∈ {none, immediate, backoff, manual}`

Распределение: `ui_changed` 28, `unknown` 20, `network` 14, `banned` 1.
Уже 28 `ui_changed`-кодов работают по схеме «сразу в ручную», включая потерю фокуса (`tt_fg_lost`, `tt_fg_drift_unrecoverable`) и запуск (`*_app_launch_failed`). Паттерн метаданных `ui_changed`: `severity='error'`, `retry_strategy='manual'`.

## 4. Утверждённые решения

- **Q1 — UI-нав коды (экран/пикер/фокус/anchor) → `ui_changed`** (сразу в ручную). Согласуется с 28 существующими `ui_changed`-кодами и со смыслом спеки «не крутиться впустую».
- **Q2 — `switch_failed_unspecified` → `unknown`** (transient). Это catch-all «переключение упало, шаг неизвестен» (`publisher_base.py:2160`), по факту микс (часть = adb_push timeout/сеть, часть = UI). Сохраняем ретраи для сетевой части; всё равно уходит в handoff после окна 2д. Помечаем `is_known=true` + описание → перестаёт быть «дырой».

## 5. Классификация — все 35 кодов (выгрузка прод, 30 дней, status failed/preflight_failed, без `process_interrupted`, NOT IN справочнике)

### → `ui_changed` (severity=error, retry_strategy=manual) — STRUCTURAL, сразу в ручную

| код | n/30д | заметка |
|---|---:|---|
| yt_editor_not_reached | 156 | редактор YT не достигнут (WP#113) |
| ig_share_tap_no_progress | 140 | тап Share без прогресса (WP#73) |
| ig_account_switcher_wrong_foreground | 95 | чужой foreground на переключении |
| tt_account_not_in_list | 62 | ⚠️ шаг `tt_3_pick_account` (пикер). Двоякая причина: аккаунт удалён с устройства vs список не отрендерился. Кладём `ui_changed` по правилу; флажок на ревью |
| yt_app_not_foregrounded | 45 | YT не на переднем плане |
| ig_gallery_no_video_candidate | 43 | в галерее нет кандидата-видео |
| tt_post_switch_verify_unrecoverable | 34 | пост-switch verify невосстановим |
| yt_picker_dismissed | 32 | пикер закрылся |
| ig_caption_screen_not_reached | 31 | экран подписи не достигнут |
| tt_account_menu_unknown_layout | 18 | неизвестный layout меню аккаунта |
| yt_picker_target_absent | 11 | целевой аккаунт не в пикере |
| ig_app_not_foregrounded | 8 | IG не на переднем плане |
| anchor_not_found | 8 | UI-anchor не найден (`account_switcher.py`) |
| ig_gallery_button_not_found | 7 | кнопка галереи не найдена |
| tt_drawer_tap_did_not_open_sheet | 6 | тап drawer не открыл sheet |
| tt_stories_back_failed | 5 | возврат из Stories не удался |
| ig_editor_falsely_detected_as_gallery | 5 | редактор ошибочно принят за галерею |
| yt_gallery_no_video_candidate | 5 | в галерее нет кандидата-видео |
| tt_app_not_foregrounded | 5 | TT не на переднем плане |
| tt_post_switch_renav_failed | 2 | пост-switch ренавигация не удалась |
| ig_external_app_foreground | 2 | сторонее приложение на переднем плане |
| yt_post_switch_app_not_foregrounded | 2 | YT не на переднем плане после switch |
| yt_foreign_foreground_unrecoverable | 1 | чужой foreground невосстановим |
| tt_perm_dialog_stuck | 1 | диалог разрешений завис |

### → `banned` (severity=critical, retry_strategy=manual) — STRUCTURAL, аккаунт требует ручного вмешательства

| код | n | заметка |
|---|---:|---|
| phone_or_email_link_required | 54 | модалка «Необходимо обновить аккаунт» (`account_switcher.py:432`, WP#93) — ретрай не поможет |
| tt_logged_out | 1 | шаг `tt_2_logged_out` — вышел из аккаунта (WP#160) — нужен ручной вход |

### → `network` (transient, ретраи) — инфра/таймаут

| код | n | severity / retry_strategy | заметка |
|---|---:|---|---|
| watchdog_subprocess_hang | 613 | warn / none | инфра-инцидент; зеркало `watchdog_fired` (тоже network/warn/none) |
| timeout | 2 | error / backoff | дженерик-таймаут |

### → `unknown` (transient, ретраи → handoff после окна 2д) — микс / контент-верификация

| код | n | severity / retry_strategy | заметка |
|---|---:|---|---|
| switch_failed_unspecified | 738 | error / backoff | catch-all (решение Q2) |
| media_store_unreadable_pre_publish | 98 | error / backoff | preflight медиа; re-push при ретрае может починить (`publisher_base.py:3589`) |
| date_mismatch | 30 | error / backoff | дата thumbnail расходится с push >60с (`publisher_helpers.py:182`); re-push чинит |
| mediastore_top_mismatch | 3 | error / backoff | top-1 MediaStore ≠ ожидаемый basename; re-push чинит |
| not_first_in_video | 2 | error / backoff | порядок видео (`publisher_base.py:3675`); re-push чинит |
| manual_smoke_abort | 2 | info / none | артефакт смок-теста, в текущем коде не эмитится; `is_known=true` |
| orphaned_no_events | 1 | info / none | артефакт (задача без событий), в текущем коде не эмитится; `is_known=true` |

**Итого:** 35 кодов → `ui_changed` 24, `banned` 2, `network` 2, `unknown` 7. Все `is_known=true`, `is_auto_fixable=false`.

## 6. Миграция

Правило: «код на таблицу = версионированный DDL в `<repo>/migrations/`» (урок 41-дневного outage `factory_parsing_logs`).

**`migrations/20260527_wp140_error_class_catalog.sql`:**
1. `INSERT INTO publish_error_codes (code, error_class, severity, retry_strategy, is_known, is_auto_fixable, description) VALUES (...) ON CONFLICT (code) DO UPDATE SET error_class=EXCLUDED.error_class, severity=EXCLUDED.severity, retry_strategy=EXCLUDED.retry_strategy, is_known=EXCLUDED.is_known, description=EXCLUDED.description;` — все 35 кодов, идемпотентно.
2. **Scoped backfill in-flight задач** (зеркало backfill из `20260521_wp108_error_class_seed.sql`). Одним атомарным `UPDATE` с join на `publish_queue` (фильтр `manual_handoff_at IS NULL` — НЕ трогать уже отданные в ручную, иначе перепишем леджер завершённых хэндофов):
   ```sql
   UPDATE publish_tasks pt
   SET error_class = m.cls
   FROM (VALUES ('ig_share_tap_no_progress','ui_changed'), /* …все 35… */) AS m(code, cls),
        publish_queue pq
   WHERE pt.error_code = m.code
     AND pq.publish_task_id = pt.id
     AND pt.status IN ('failed','preflight_failed')
     AND pq.manual_handoff_at IS NULL
     AND pt.error_class IS DISTINCT FROM m.cls;
   ```
   Перекласует ~23 задачи, упавшие после деплоя WP#108 (05-22) и ещё в полёте (контроллер берёт только `pq.status='failed' AND pq.manual_handoff_at IS NULL`), чтобы фикс заработал немедленно — например 10× `ig_share_tap_no_progress` (сейчас `unknown`) → `ui_changed` → сразу handoff. Без backfill фикс действует только для будущих падений.
3. Всё в `BEGIN; ... COMMIT;`.

**`migrations/20260527_wp140_error_class_catalog__rollback.sql`:**
- `DELETE FROM publish_error_codes WHERE code IN (<35 кодов>);` — удаляет только добавленные строки.
- Backfill `publish_tasks.error_class` необратим по дизайну (правка денормализованной копии-леджера; так же необратим backfill WP#108). Отметить это комментарием в rollback.

**Kill-switch:** новый не нужен. Изменение — данные справочника + перекласовка, поведением управляет существующий `RETRY_ENGINE_ENABLED`. Откат — через rollback-миграцию.

## 7. Acceptance (с переформулировкой №3 по решению Q1)

1. ✅ Каждый код, реально встречающийся в проде (выгрузка 30 дней), присутствует в `publish_error_codes` с осмысленным `error_class`.
2. ✅ Ни один прод-код не дефолтится в `unknown` из-за отсутствия в каталоге (фолбэк остаётся только для действительно новых/неизвестных кодов).
3. 🔄 **Было:** «UI-фейлы после исчерпания лимита уходят в handoff, а не ретраятся бесконечно.»
   **Стало:** «UI-фейлы (`ui_changed`) уходят в handoff **сразу**, без холостых ретраев; транзиентные (`network`/`unknown`) ретраятся и уходят в handoff после исчерпания окна (2 дня). Система нигде не ретраит бесконечно.»

## 8. План верификации

- **Юнит** (`test_retry_decision.test.js` — уже есть): кейс на каждый класс → `ui_changed`/`banned` дают `{action:'handoff', reason:'structural_error'}`; `network`/`unknown` в пределах лимита → `requeue`; за окном → `{handoff, window_exhausted}`.
- **Миграционный смок на testbench-БД:** применить миграцию → `SELECT count(*) FROM publish_error_codes` вырос на число реально новых кодов; нет строк с прод-кодами вне каталога:
  `SELECT DISTINCT pt.error_code FROM publish_tasks pt WHERE pt.status IN ('failed','preflight_failed') AND pt.created_at >= now()-interval '30 days' AND COALESCE(error_code,'') NOT IN ('','process_interrupted') AND NOT EXISTS (SELECT 1 FROM publish_error_codes ec WHERE ec.code=pt.error_code);` → пусто.
- **Rollback-смок:** применить rollback → новые коды удалены, исходные 63 на месте.
- **Прод-наблюдение:** после деплоя — `pq#5069`-подобные `yt_*`/`ig_*` UI-падения уходят в ручную сразу (лог `[retry-controller] ... structural_error`), а не requeue.

## 9. Открытые заметки (вынесены в OpenProject #166, не блокируют WP #140)

- Таксономия из 5 классов не имеет «permanent/logic» класса: `date_mismatch`/`not_first_in_video` логически неретраебельны, но временно кладутся в `unknown` (ретраятся 2 дня, потом handoff). Допустимо как временное; долгосрочно — отдельный класс или маршрут «сразу в ручную».
- Дубли/межплатформенный дрейф имён: `yt_picker_target_absent` vs `yt_target_not_in_picker_after_scroll`; `*_app_not_foregrounded` размножен по платформам без единой схемы.
- `tt_account_not_in_list` классифицирован `ui_changed` по правилу, но причина двоякая — кандидат на покодовый разбор в #166.
