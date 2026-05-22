# WP #108 — Деплой движка ретраев: runbook варианта C1 «Старт с чистого листа»

- **Дата:** 2026-05-22
- **OpenProject:** WP #108 «Ретраи для выкладок» (assignee Данил, статус «В разработке», приоритет «Немедленно»)
- **Решение (созвон 2026-05-22):** запускаем по **варианту C1** + включаем движок сразу + простой маркер + МСК-старт 05:00 в этот же деплой.
- **Связано:** дизайн `2026-05-21-wp108-publish-retry-engine-design.md`, план `2026-05-21-wp108-publish-retry-engine.md`, варианты `2026-05-21-wp108-deploy-options.md`.

## 1. Что уже готово (НЕ переделываем)

| Артефакт | Состояние |
|---|---|
| Код движка (классификатор, `decideRetry`, крон `retryFailedPublishes`, хук идемпотентности) | Написан, **19 тестов зелёные**, ревью READY-WITH-NOTES. Клон `/home/claude-user/wp108-autowarm`, ветка `wp108-publish-retries` (8 коммитов, **не запушена**) |
| Схема БД (6 колонок + индексы/CHECK) | **Применена** к общей `openclaw` (инертна без кода) |
| Сид `error_class` + backfill `publish_tasks` | **Применены** (ui_changed=28, unknown=19, network=14, banned=1) |
| Прод-чекаут `/root/.openclaw/workspace-genri/autowarm` | На `main` (не на чужой ветке) |

**Деплой = только код** (миграции/сид уже в БД). Ветка кода на 2026-05-22 — **8 коммитов позади `origin/main`** → перед деплоем ребейз.

## 2. Cross-repo взаимодействие (найдено 2026-05-22)

`publish_planner.js` (WP #109, в проде) читает `manual_handoff_at`:
- `attachQueueTransferColumns` (эндпоинт `/api/publish/queue`, флаг `QUEUE_TRANSFER_COLUMNS_ENABLED`, дефолт вкл) → `deriveTransferColumns` ставит `transferred_to = manual_handoff_at` **безусловно**.
- `getPlannerCards` (`/api/publish/planner`) `manual_handoff_at` **не** использует в карточках (переносы считаются по датам попыток).

**Следствие:** пометка бэклога `manual_handoff_at=now()` покажет свежие строки бэклога в **списке очереди** как «перенесено в ручную 22.05» (всплеск на одну дату). Это **косметика**, на работу движка не влияет, обратимо. По решению — берём простой маркер, всплеск приемлем (бэклог действительно уходит из авто в ручную).

## 3. Решения этого деплоя

| Вопрос | Решение |
|---|---|
| Бэклог (~2152 упавших) | **C1 «чистый лист»**: пометить как обработанный → движок управляет только новыми падениями с сегодняшнего дня |
| Включение движка | **Сразу** (дефолты). Крон работает с первого тика, но только по новым падениям (бэклог помечен). Классификатор + идемпотентность активны сразу (безопасны, за рубильниками). Мониторим первый день |
| Маркер C1 | `manual_handoff_at=now()` + `skip_reason='retry_clean_slate_20260522'` (простой, обратимый по skip_reason) |
| МСК-старт 05:00 | **В этот же деплой** (`unic_settings → Europe/Moscow / 05:00:00`). `slot_date` = PG `DATE` → сдвига слотов нет; прод знает `Europe/Moscow` (tzOffsets=3, computeBusinessDate OK) |
| Параллелизм малинок | **Не трогаем**: `MAX_CONCURRENT_PUBLISHES_PER_RASPBERRY=3` (дефолт). Поднимать постепенно отдельно |

## 4. Pre-flight (без записи в прод)

1. **Ребейз** ветки `wp108-publish-retries` на актуальный `origin/main` в клоне → разрешить конфликты (вероятны в `server.js`: планировщик #109 vs регистрация крона) → `node --test` зелёные.
2. **Cross-repo grep** `client_publish_id`/`error_class`/`manual_handoff_at` по delivery+validator — выполнено; коллизий схемы нет, единственное взаимодействие = планировщик (§2).
3. Подтвердить, что миграции/сид уже в `openclaw` (no-op на деплое).

## 5. 🚦 PROD-GATE

Перед **любой** записью в прод (push / merge в прод-main / `UPDATE` / restart) — стоп, ждём явного «go» от Данила.

## 6. Деплой (после «go»)

Порядок строгий; **без force-push**.

1. **Push** ребейзнутой `wp108-publish-retries` в delivery `origin`.
2. **Код в прод:** в `/root/.openclaw/workspace-genri/autowarm` (на `main`): `git fetch` → fast-forward merge `origin/wp108-publish-retries` в `main` (триггерит post-commit auto-push hook). Проверить `pm2 describe autowarm | grep "exec cwd"` (drift!).
3. **Миграции:** подтвердить, что 6 колонок + сид уже на месте (no-op). Если БД пересоздавалась — применять **поимённо** forward-файлы: `20260521_wp108_retry_engine.sql` → потом `20260521_wp108_error_class_seed.sql` (НЕ glob, НЕ `*__rollback.sql`).
4. **МСК-старт:** после проверки `slot_date::date` и tzOffsets —
   ```sql
   UPDATE unic_settings SET timezone='Europe/Moscow', publish_start='05:00:00' WHERE id=1
   RETURNING timezone, publish_start;
   ```
5. **C1 «чистый лист»** (ДО рестарта, пока крон ещё не в рантайме). `now()` в одном `UPDATE` одинаков для всех строк — **зафиксировать это значение `manual_handoff_at` (и count) для отката**. `COALESCE` сохраняет уже осмысленный `skip_reason` (на 2026-05-22 такой 1 — «orphaned pt 4548…»), не затирая его:
   ```sql
   UPDATE publish_queue
      SET manual_handoff_at = now(),
          skip_reason = COALESCE(skip_reason, 'retry_clean_slate_20260522')
    WHERE status='failed' AND manual_handoff_at IS NULL
   RETURNING id, manual_handoff_at, skip_reason;   -- ~2155
   ```
6. **Рестарт:** `pm2 restart autowarm` — регистрируется крон. Флаги по дефолту вкл (`RETRY_ENGINE_ENABLED`, `RETRY_MANUAL_HANDOFF_ENABLED`, `IDEMPOTENCY_CHECK_ENABLED`). Publisher запускается per-task (spawn) — подхватит Python без отдельного рестарта.
7. **Smoke (первый день):**
   - лог `[retry-controller]`: новые падения → requeue/handoff, нет циклов;
   - нет ложных handoff (помеченные `manual_publish` слоты действительно исчерпали лимиты/структурные);
   - утренний прогон партии 05:00 МСК состоялся;
   - идемпотентность: нет дублей в реальных аккаунтах после requeue;
   - бэклог (skip_reason='retry_clean_slate_20260522') движок НЕ трогает.

## 7. Рубильники

| Флаг | Дефолт | Назначение |
|---|---|---|
| `RETRY_ENGINE_ENABLED` | вкл | Весь крон ретраев (жёсткий стоп) |
| `RETRY_MANUAL_HANDOFF_ENABLED` | вкл | Передача в ручную (выкл = только requeue) |
| `IDEMPOTENCY_CHECK_ENABLED` | вкл | Проверка «уже выложено» перед Share |
| `RETRY_INTERVAL_MINUTES` | 5 | Период тика |
| `RETRY_MAX_PER_CLASS_PER_DAY` | 3 | Лимит повторов/сутки/класс |
| `RETRY_WINDOW_DAYS` | 2 | Окно авто-попыток |
| `RETRY_CUTOFF_HOUR_MSK` | 23 | Отсечка ретраев |

## 8. Откат

- **Движок:** `RETRY_ENGINE_ENABLED=false` + restart (мгновенно, без передеплоя).
- **C1-пометка:** откат по зафиксированному timestamp пачки (`<TS>` = `manual_handoff_at` из RETURNING), чтобы не задеть будущие реальные handoff'ы и сохранить чужие `skip_reason`:
  ```sql
  UPDATE publish_queue
     SET manual_handoff_at = NULL,
         skip_reason = CASE WHEN skip_reason='retry_clean_slate_20260522' THEN NULL ELSE skip_reason END
   WHERE manual_handoff_at = '<TS>';
  ```
- **МСК:** вернуть `unic_settings` на `Asia/Dubai`/`09:00:00`.
- **Код:** прод-чекаут на предыдущий коммит + restart. Схема аддитивна — откат не требуется.

## 9. Открытые операционные вопросы

- Поднимать ли параллелизм малинок (3→до 8) — отдельный тюнинг с мониторингом fail-rate, не блокер.
- Разовая «зачистка» старого бэклога (вариант C2/C3) — позже, отдельным осознанным заходом; сейчас бэклог остаётся за операторами.

## 10. Фактический исход деплоя (2026-05-22)

Выполнено по runbook: код → прод-main delivery `bd8c6a5` (ff-merge + push, без force); МСК `Europe/Moscow/05:00`; C1-пометка 2156 строк (timestamp пачки `2026-05-22 09:48:28.533923+00`, COALESCE сохранил 1 чужой skip_reason); рестарт.

**Снаг (учтён в [[feedback-stale-node-test]] / [[feedback-pm2-dump-path-drift]]):** после деплоя новые publish_tasks не получали `client_publish_id` → контроллер их молча пропускал. Корень двойной:
1. **Зомби-процессы WP #125** (`test_dispatch_manual_guard.test.js`, ~20ч, удалённый worktree) импортировали `server.js` → теневой autowarm диспатчил боевую очередь старым кодом. Лечение: `pkill -f test_dispatch_manual_guard` (⚠️ зацепит свой shell — проверять по PID через `kill -0`).
2. **`pm2 restart` грузил stale-код** (хотя `script path`/`exec cwd` верны). Лечение: `pm2 delete autowarm` + `pm2 start ecosystem.production.config.js` + `pm2 save`. autowarm стал id=35.

После фикса: cpid у новых задач 5/5. **Верификация вживую:** `11:21 [retry-controller] requeue pq#5005 (unknown, transient_within_limits)`.

**Диагностический приём (опознать реального диспатчера):** postgres в контейнере (`172.17.0.3:5432`), клиенты-host видны как `172.17.0.1`; `sudo ss -tnpH | grep 5432 → pid → /proc/$pid/{cmdline,cwd}` (нужен root-терминал, не `!`-сессия и не sudo-NOPASSWD-scope claude-user). Контролируемый тест «кто диспатчит»: остановить pm2-autowarm на один интервал, смотреть, появляются ли новые задачи, привязанные к очереди.

**Остаток:** наблюдать handoff-ветку (передача в ручную при исчерпании окна/лимита) 1-2 дня. Зомби node server.js с марта → WP #133.
