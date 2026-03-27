---
name: social-audit
description: "Аудит оформления соцсетей клиентов (Instagram, TikTok, YouTube) через ADB. Открывает профили на реальных телефонах фермы, делает скриншоты шапки, извлекает данные через Groq AI, сравнивает с брифом из Airtable, выставляет оценку 0–100. Результаты хранятся в БД и видны в Delivery → Аналитика → Оформление. Триггеры: 'проверь оформление', 'аудит аккаунтов', 'как оформлены наши соцсети', 'соответствие брифу'."
---

# Social Audit — Аудит оформления соцсетей

## Что делает скилл

1. Берёт аккаунты проекта из factory DB (193.124.112.222:49002)
2. Находит свободное устройство на ферме через ADB (82.115.54.26)
3. Открывает профиль в приложении (Instagram / TikTok / YouTube)
4. Делает скриншот шапки (без скролла — только header)
5. Проверяет что скриншот не чёрный (ffmpeg avg < 10 = пропуск)
6. Сохраняет скриншот в `public/screenshots/` (доступно по HTTP)
7. Groq AI (vision) извлекает: username, display_name, bio, ссылка, аватар
8. Groq AI (text) выставляет оценку 0–100 по критериям vs бриф из Airtable
9. Сохраняет в `social_audit_snapshots` (openclaw DB, localhost:5432)

## Ключевые файлы

```
/root/.openclaw/workspace-genri/autowarm/social_audit.py   # основной скрипт
/root/.openclaw/workspace-genri/autowarm/public/screenshots/ # скриншоты шапок
```

## AI провайдер

- **Groq** (не LaoZhang — токены кончились, не Anthropic — возвращает 404)
- Vision: `meta-llama/llama-4-scout-17b-16e-instruct`
- Text: `llama-3.3-70b-versatile`
- API key: `[REDACTED-GROQ-KEY]`

## Запуск

### Батч по проекту (основной режим)
```bash
cd /root/.openclaw/workspace-genri/autowarm
python3 social_audit.py --batch --project booster_cap --platforms instagram,tiktok,youtube
```
> `--project` принимает имя из factory DB (snake_case), нормализуется для поиска в Airtable

### Один аккаунт
```bash
python3 social_audit.py --account @username --platform instagram --project booster_cap
python3 social_audit.py --account @username --platform tiktok --serial RF8YXXXXX --port 15068
```

### Список проектов
```bash
python3 social_audit.py --list-projects
```

## Критерии оценки 0–100

| Критерий | Вес | Что проверяет |
|----------|-----|---------------|
| `bio` | 30% | Есть ссылка на WB/Ozon или артикул → если нет = max 30 баллов |
| `visual` | 25% | Аватар профессиональный, соответствует бренду |
| `username` | 25% | Читаемый, соответствует нише |
| `display_name` | 20% | Понятное имя, ключевые слова |

**Бизнес-правило**: товарные аккаунты без ссылки на маркетплейс или артикула в bio = score_bio ≤ 30/100.

## Airtable (брифы)

- База: `app7fFym01YjkYHB8`
- Токен: `[REDACTED-AIRTABLE-TOKEN]`
- Нормализация: `booster_cap` (factory DB) → находит `Booster cap✅` (Airtable) через `_normalize()`

## БД

```sql
-- Последние аудиты (по одному на аккаунт)
SELECT account, platform, score_total, display_name, score_bio, score_visual, verdict
FROM social_audit_snapshots
WHERE project_name = 'Booster cap✅'
  AND id IN (SELECT MAX(id) FROM social_audit_snapshots GROUP BY account, platform)
ORDER BY platform, score_total DESC;

-- Сводка по критериям
SELECT ROUND(AVG(score_bio),1) as bio, ROUND(AVG(score_visual),1) as visual,
       ROUND(AVG(score_username),1) as username, ROUND(AVG(score_total),1) as total
FROM social_audit_snapshots WHERE project_name = 'Booster cap✅';
```

## API Delivery (порт 3848)

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/social-audit/list` | Список с фильтрами: platform, project, sort, dir, limit |
| GET | `/api/social-audit/:id` | Детали записи |
| GET | `/api/social-audit/stats` | Сводка по проектам |
| GET | `/api/social-audit/projects` | Проекты из БД |
| GET | `/api/social-audit/criteria-avg` | Средние по критериям (param: project) |
| POST | `/api/social-audit/run-batch` | Батч по проекту + платформам (async) |
| POST | `/api/social-audit/run` | Один аккаунт (async) |
| POST | `/api/social-audit/run-sync` | Один аккаунт (sync, ждёт результат) |

⚠️ `/api/social-audit/projects` и `/api/social-audit/stats` должны стоять **до** `/api/social-audit/:id` в server.js — иначе Express перехватывает их как id.

## UI в Delivery

Delivery → **Аналитика** → **🎨 Оформление**

### Подвкладки:
- **📊 Дашборд** — общая оценка, прогрессбары по критериям, строки по проектам
- **📋 Все аудиты** — таблица с фильтрами (платформа, проект) и сортировкой по любой колонке

### Модалка деталей:
- Скриншот шапки профиля (если не чёрный)
- Разбивка оценок по критериям
- Bio, ссылка, подписчики
- Сильные/слабые стороны, вердикт

### Запуск аудита:
- Кнопка `+ Запустить аудит` → модалка
- Выбор проекта (дропдаун из БД) + чекбоксы платформ
- Запускает `/api/social-audit/run-batch` в фоне

## Известные проблемы

- Устройство `RF8YA0VDZ3X` (порт 15068) возвращает чёрные/маленькие скриншоты
- Скриншоты старых аудитов не сохранялись в `public/screenshots/` — только новые
- factory DB: таблицы `pack_accounts`, `device_numbers`, `raspberry_port`, `factory_projects`
