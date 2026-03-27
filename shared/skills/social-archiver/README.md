# Social Archiver — Скилл архивации публикаций

Автоматическая архивация «провальных» постов в Instagram, TikTok и YouTube через ADB.

## Что делает

Ежедневно (06:00 UTC) проходится по всем активным аккаунтам в Factory БД и скрывает публикации, которые:
- **Опубликованы ровно 3 дня назад**
- **Набрали менее 50 просмотров**

| Платформа | Действие |
|-----------|---------|
| Instagram | Archive (⋮ → Archive) |
| TikTok | Only me (⋮ → Privacy → Only me) |
| YouTube | Private (⋮ → Edit → Visibility → Private) |

## Использование

Читай `SKILL.md` для полной документации.

### Быстрый старт

```bash
# Статус задач
curl http://localhost:3848/api/archive/tasks

# Запустить вручную
curl -X POST http://localhost:3848/api/archive/run \
  -H "Content-Type: application/json" \
  -d '{"account":"USERNAME","device_serial":"SERIAL","platform":"instagram"}'
```

## Файлы

| Файл | Описание |
|------|---------|
| `scripts/archiver_base.py` | Базовый класс + ADB-хелпер + парсеры |
| `scripts/instagram_archiver.py` | Instagram: Archive |
| `scripts/tiktok_archiver.py` | TikTok: Only me |
| `scripts/youtube_archiver.py` | YouTube Studio: Private |
| `scripts/archive_scheduler.py` | Планировщик (запускает все платформы) |

## Живые скрипты

Актуальный код живёт в:
```
/root/.openclaw/workspace-genri/autowarm/
```
Скрипты в `scripts/` — копия на момент создания скилла. При обновлении синкай обратно.
