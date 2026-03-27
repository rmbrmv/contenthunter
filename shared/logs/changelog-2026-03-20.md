## 2026-03-20 — Видеозапись экрана для фарминга (Генри)

**warmer.py** теперь записывает видео экрана телефона при фарминге (аналогично publisher.py для публикаций).

- Запись стартует перед фазами фарминга, останавливается при любом завершении
- Видео загружается в S3: `autowarm/screenrecords/farming/{platform}/...`
- URL сохраняется в `autowarm_tasks.screen_record_url`
- В UI: ссылка «🎬 Запись экрана фарминга» в логе задачи (📋)
- Отключить: `FARM_SCREEN_RECORD=false` env var
- Коммит: `e9731e6` → GenGo2/delivery-contenthunter
