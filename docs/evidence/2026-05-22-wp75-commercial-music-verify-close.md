# WP #75 — TT-модал «Коммерческие треки → TikBiz»: верификация и закрытие

**Дата:** 2026-05-22
**Вердикт:** handler модала работает; сигнатура, ради которой заведена задача, не рецидивирует → закрытие в «Готово».
**Скоуп:** только TikTok, prod (`testbench=false`), окно 7–8 дней.

## Что проверяли

WP #75 завели 2026-05-15: TikTok начал показывать в композере окно «Коммерческие треки» (подборка TikBiz), кнопка «Опубликовать» не находилась → 3-мин таймаут `tt_upload_confirmation_timeout` (~4 одинаковых падения/сутки). 2026-05-15 выкачен handler (cancel-X крестиком, fallback — выбор первого трека). Задачу вернули в работу 19.05 для разбора остаточных падений (task 7722).

## Доказательство 1 — handler срабатывает и гасит окно (7 дней)

```
tt_commercial_music_cancelled | 27
tt_commercial_music_dismissed | 27
tt_commercial_music_stuck         | 0
tt_commercial_music_track_selected | 0
```

Окно возникало 27 раз — все 27 закрыты крестиком, 0 застреваний, ни разу не пришлось принудительно выбирать трек. Сигнатура `commercial-music modal → AI null Publish → timeout` не воспроизводится: handler закрывает окно до того, как оно блокирует Publish.

## Доказательство 2 — остаточные падения НЕ из-за модала

Из 27 задач, где окно было погашено: **16 → опубликовано**, **11 → упали** позже по флоу (`tt_upload_confirmation_timeout` ×10, `screencast_stop_failed` ×1). Разбор показал: это отдельный класс (кнопка «Опубликовать» не находится / `wait_upload` false-negative), не модал. Подтверждение — task 8765 в этом списке прямо назван в WP #118 как пример sub-mode A (цвет кнопки Publish в AI-промпте).

Тренд по дням (модал погашен → done/failed):

| Дата | done | failed | контекст |
|---|:--:|:--:|---|
| 17.05 | 1 | 1 | |
| 18.05 | 3 | 6 | до PR #69 (WP #82) |
| 19.05 | 5 | 0 | после PR #69 |
| 20.05 | 1 | 0 | |
| 21.05 | 4 | 4 | 4 падения 04:54–06:43 UTC — до деплоя PR #89 (WP #118) |
| **22.05** | **2** | **0** | после PR #89 |

Все 11 post-dismiss падений предшествуют соответствующим фиксам (#82 PR #69 от 18.05, #118 PR #89 от 21.05). После них — 0.

## Доказательство 3 — свежие таймауты не связаны с модалом

Сегодняшние `tt_upload_confirmation_timeout` (9171, 9175) и task 7722 (ради которого WP #75 вернули 19.05): у всех `commercial_seen = 0` — окно «Коммерческие треки» не замешано. Триаж 22.05 (`docs/evidence/2026-05-22-tt-publish-fails-triage.md`) относит остаток `tt_upload_confirmation_timeout` к WP #118 / WP #122.

## Передача остатка

- **WP #82** (false-negative success-detection в `wait_upload`) — SHIPPED 18.05 (PR #69).
- **WP #118** (цвет кнопки Publish в AI-промпте + модал «Подтвердите видимость») — SHIPPED 21.05 (PR #89).
- **WP #122** (оверлей «Добавить в историю» в share-loop) — BACKLOG.

Все три — не модал «Коммерческие треки». Доп. handler под WP #75 писать не нужно (риск дублирования PR #69/#89).

## SQL для воспроизведения

```sql
-- handler outcomes за 7д
SELECT e->'meta'->>'category', count(*)
FROM publish_tasks, jsonb_array_elements(events) e
WHERE platform='TikTok' AND created_at >= now() - interval '7 days'
  AND COALESCE(testbench,false)=false
  AND e->'meta'->>'category' LIKE 'tt_commercial_music%'
GROUP BY 1;

-- финальный статус задач, где модал был погашен (8д тренд)
WITH cm AS (
  SELECT DISTINCT pt.id, pt.created_at::date d, pt.status
  FROM publish_tasks pt, jsonb_array_elements(pt.events) e
  WHERE pt.platform='TikTok' AND pt.created_at >= now() - interval '8 days'
    AND COALESCE(pt.testbench,false)=false
    AND e->'meta'->>'category' = 'tt_commercial_music_dismissed')
SELECT d,
  count(*) FILTER (WHERE status='done')   AS done,
  count(*) FILTER (WHERE status='failed') AS failed
FROM cm GROUP BY d ORDER BY d;
```
