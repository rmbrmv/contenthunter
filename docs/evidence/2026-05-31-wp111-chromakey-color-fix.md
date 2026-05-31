# WP#111 — фикс хромакея новых оверлеев (31.05, follow-up)

## Что было не так
Данил прислал скрин: на оверлей-видео схем 31-34 **зелёный фон не вырезался** — торчал зелёным квадратом в углу. Реальное продакшн-превью 103/31 подтвердило баг.

**Root cause:** в `validator_unic_content.chromakey_color` для оверлеев 498-501 было записано `0x00ff30` (rgb 0,255,48), а фактический зелёный фон видео — другой. При `chromakey` similarity 0.12 (хардкод-дефолт; колонок chromakey_similarity/blend в `unic_schemes` нет) такой разброс цвета не вычищается.

## Точные пробы цвета (мода чистого фона по верхней кромке, стабильна на 2 кадрах)
| overlay (validator_unic_content.id) | было | стало (реальный фон) |
|---|---|---|
| 498 (video_0_1) | 0x00ff30 | **0x78ff54** (120,255,84) |
| 499 (video_0_2) | 0x00ff30 | **0x77ff55** (119,255,85) |
| 500 (video_0_3) | 0x00ff30 | **0x78ff54** (120,255,84) |
| 501 (video_0_4) | 0x00ff30 | **0x2dff32** (45,255,50) |

```sql
UPDATE validator_unic_content SET chromakey_color='0x78ff54' WHERE id IN (498,500);
UPDATE validator_unic_content SET chromakey_color='0x77ff55' WHERE id=499;
UPDATE validator_unic_content SET chromakey_color='0x2dff32' WHERE id=501;
```

## Верификация
- Локальный рендер всех 4 схем через пайплайн воркера (`get_content_for_scheme`+`generate_ffmpeg`, читает chromakey из БД) на семпле Ирбиса: зелёный фон вырезан чисто, дизайн оверлеев (белые круги/звезда/ракета — не зелёный) сохранён. similarity 0.12 достаточно.
- Превью в тиндере перегенерированы и **залиты в S3** (scheme-previews/103/{31..34}/preview.mp4 + thumb.jpg), `validator_scheme_previews` обновлён. Проверено: новый MD5 ≠ старый, `save.gengo.io` отдаёт новые файлы, зелёного нет.

## Гоча (на будущее)
- Перегенерация превью через постановку scheme_preview в `unic_tasks` **не сработала надёжно**: задача 3955 отрапортовала `done` (даже schemes_done=7 > total=4 — похоже на гонку воркеров), но S3-объекты НЕ перезаписала. Для точечного re-render надёжнее рендерить+грузить в S3 напрямую (креды в `autowarm-testbench/.env`), что и сделано.
- Живой автопаблиш Ирбиса теперь тоже вычищает зелёный — `worker.py process_task` читает `chromakey_color` из той же таблицы на лету.
