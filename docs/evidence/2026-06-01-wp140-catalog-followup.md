# WP#140 followup — 6 дрейфнувших кодов в каталог — 2026-06-01

## Проблема

Тест `test_wp140_error_class_catalog` (check #2: ни один прод-код за 30д не отсутствует
в `publish_error_codes`) падал — каталог дрейфует: поздние WP добавляют новые `error_code`,
а каталог не пополняется. Найдено 6 некаталогизированных:

| код | error_class | обоснование |
|---|---|---|
| tt_open_list_probe_stale_ui | ui_changed | stale uiautomator при открытии списка аккаунтов TT (зеркало WP#131) |
| ig_upload_foreground_lost_foreign | ui_changed | передний план IG перехвачен сторонним приложением при загрузке |
| tt_account_switcher_wrong_foreground | ui_changed | чужой foreground при переключении TT (зеркало ig_account_switcher_wrong_foreground) |
| rc_nonzero | network | подпроцесс chunked adb push вернул rc≠0 (рядом с sibling `timeout`) |
| cat_merge_failed | network | сборка (cat) частей медиа на устройстве при chunked-push не удалась |
| superseded_requeue | unknown | задача вытеснена повторной постановкой (benign внутренний статус) |

## Фикс (delivery-contenthunter PR#140 → main f06c31a)

- Followup-миграция `20260601_wp140_catalog_followup.sql` (+rollback): INSERT 6 кодов
  (idempotent `ON CONFLICT (code) DO UPDATE`) + scoped backfill in-flight `publish_tasks`
  (как в базовой 20260527).
- Тест обновлён: `applyAllMigrations` применяет базовую + followup; rollback-тест
  откатывает обе. EXPECTED расширен 6 кодами (35 → 41).

## Верификация

- Полный прогон (последовательно): **224 теста, 222 pass, 0 fail** (был 1 fail = эти коды).
- codex review: 0 регрессий.
- Миграция применена к проду (6 кодов в каталоге); прод pull → f06c31a; PM2-restart НЕ
  нужен (чистая data-миграция, runtime читает error_class из БД).

Дрейф каталога — хроническая природа; долгоиграющая таксономия/нейминг = WP#166 (Бэклог).
