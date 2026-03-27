---
name: Social Archiver
slug: social-archiver
version: 1.1.0
description: Архивация публикаций Instagram, TikTok и YouTube через ADB. Находит посты ровно 3 дня назад с < 50 просмотров и архивирует их (скрывает от публики).
metadata: {"clawdbot":{"emoji":"📦","requires":{"bins":["python3","adb"]},"os":["linux"]}}
---

## Назначение

Ежедневная автоматическая архивация «провальных» публикаций в соцсетях:
- **Instagram** — Archive (⋮ → Archive)
- **TikTok** — Only me (⋮ → Privacy settings → Only me)
- **YouTube** — Private (⋮ → Edit video → Visibility → Private / Make private)

**Критерии архивации:** пост опубликован ровно **3 дня назад** И просмотров **< 50**

## Архитектура

```
scripts/
├── archiver_base.py       # ADB-хелпер, парсеры дат/просмотров, BaseArchiver
├── instagram_archiver.py  # Instagram-специфичный архиватор
├── tiktok_archiver.py     # TikTok-специфичный архиватор
├── youtube_archiver.py    # YouTube Studio-архиватор
└── archive_scheduler.py   # Планировщик: берёт аккаунты из Factory БД и запускает все 3 платформы
```

## БД

| Источник | Назначение |
|----------|-----------|
| `openclaw@localhost:5432` | `archive_tasks` — задачи, `archive_log` — лог архивированных постов |
| `factory@193.124.112.222:49002` | `factory_inst_accounts`, `pack_accounts`, `device_numbers`, `raspberry_port` |

Таблицы в openclaw DB:
```sql
archive_tasks  (id, device_serial, account, platform, status, videos_checked, videos_archived, started_at, finished_at, error_msg)
archive_log    (id, task_id, account, platform, post_shortcode, views, published_at, archived_at)
```

## API (autowarm на localhost:3848)

| Метод | Путь | Описание |
|-------|------|----------|
| POST  | `/api/archive/run` | Запустить задачу `{account, device_serial, platform}` |
| GET   | `/api/archive/tasks` | Список задач (фильтр по platform, status) |
| GET   | `/api/archive/stats` | Статистика по платформам |
| GET   | `/api/archive/tasks/:id/log` | Детальный лог конкретной задачи |

## Запуск вручную

### Один аккаунт (по task_id из БД)
```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 instagram_archiver.py <task_id>
python3 tiktok_archiver.py <task_id>
python3 youtube_archiver.py <task_id>
```

### Один аккаунт (прямо по параметрам, без task_id)
```bash
python3 instagram_archiver.py --device RF8YA09SNNT --account my_account --adb-host 147.45.251.85 --adb-port 15037
```

### Через API
```bash
curl -X POST http://localhost:3848/api/archive/run \
  -H "Content-Type: application/json" \
  -d '{"account":"lavka_radosti_store","device_serial":"RF8YA09SNNT","platform":"instagram"}'
```

### Запустить планировщик (все аккаунты)
```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 archive_scheduler.py
```

## Cron

Ежедневно 06:00 UTC (09:00 МСК):
- Job ID: `fb3423ba-0f01-417b-a86f-62dd6dbe2eb6`
- Запускает `archive_scheduler.py` → POST на `/api/archive/run` для каждого аккаунта

## Параметры архиватора (BaseArchiver)

| Константа | Значение | Описание |
|-----------|----------|----------|
| `TARGET_DAYS` | 3 | Возраст поста в днях |
| `MAX_VIEWS` | 50 | Максимум просмотров |
| `MAX_POSTS_CHECK` | 20 | Проверяем за один прогон |
| `MAX_POSTS_ARCHIVE` | 10 | Архивируем за один прогон |

## Масштаб

- Instagram: ~233 активных аккаунта
- TikTok: ~182 аккаунта
- YouTube: ~180 аккаунтов

## ADB-логика

Все скрипты работают через ADB поверх сети:
```
adb -H <raspberry_host> -P <raspberry_port> -s <device_serial>
```

Хост и порт берутся из Factory БД (`raspberry_port.host`, `raspberry_port.adb`).

Антидетект: рандомизация координат тапов (±4px), случайные паузы между действиями, человекоподобный свайп.

## Когда использовать этот скилл

- Запустить архивацию вручную для конкретного аккаунта
- Проверить статус задач (`/api/archive/tasks`)
- Отладить почему пост не архивируется (включить подробный лог)
- Изменить критерии (TARGET_DAYS, MAX_VIEWS) — редактируй в `archiver_base.py`
- Добавить новую платформу — создай класс-наследник от `BaseArchiver`

---

## Диагностика проблем

| Проблема | Причина | Решение |
|---------|---------|---------|
| `ADB timeout` | Устройство офлайн или медленный ответ | Проверить ADB: `adb -H host -P port devices` |
| Пост не найден | UI изменился, новый resource-id | Сделать `uiautomator dump`, изучить дерево |
| `Кнопка Archive не найдена` | Открыт не рилс/пост, или другое приложение | Проверить `dump_ui()`, добавить fallback |
| `Устройство для аккаунта не найдено` | Аккаунт неактивен в Factory | `SELECT * FROM factory_inst_accounts WHERE username='...'` |
| Дата не распознана | Нестандартный формат | Расширить `parse_days_ago()` в `archiver_base.py` |

## Пример вывода

```
10:00:01 🚀 Archiver: device=RF8YA09SNNT account=lavka_radosti_store
10:00:02 📱 Открываем Instagram...
10:00:08 👤 Переходим в профиль...
10:00:11   📌 Открываем пост 1...
10:00:16     Дата: '3d' (3d) | Просмотры: 47
10:00:16     📦 Архивируем пост...
10:00:20     ✅ Архивировано
10:00:26   📌 Открываем пост 2...
10:00:31     Дата: '4d' (4d) | Просмотры: 110
10:00:31     ⏭ Пост старше 3д — дальше не смотрим
10:00:33 ✅ Готово: проверено 2, заархивировано 1
```
