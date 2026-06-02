-- WP#222: разовый бэкфилл уже залипших scheme_preview-строк, где счётчик
-- перевалил за total (косметика истории; строки уже done, на новые генерации
-- не влияют). Запускать на openclaw PG (контейнер 172.17.0.3).
UPDATE unic_tasks
   SET schemes_done = LEAST(schemes_done, schemes_total),
       updated_at = NOW()
 WHERE task_type = 'scheme_preview'
   AND schemes_done > schemes_total;
