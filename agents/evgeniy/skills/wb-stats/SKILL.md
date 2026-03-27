---
name: wb-stats
description: Сбор и анализ данных из Wildberries Seller API для проекта MP Brands. Используй когда нужно получить статистику заказов, выручки, выкупов, топ артикулов или категорий за любой период. Умеет считать недельные срезы, сравнивать периоды, строить сводки по дням. Правильный метод подсчёта уже зашит в скрипт — совпадает с WB Partners кабинетом.
---

# WB Stats

## Быстрый старт

Для большинства задач используй готовый скрипт `scripts/wb_orders.py`:

```bash
# Прошлая неделя
python3 skills/wb-stats/scripts/wb_orders.py --week prev

# Текущая неделя
python3 skills/wb-stats/scripts/wb_orders.py --week current

# Произвольный период
python3 skills/wb-stats/scripts/wb_orders.py --from 2026-03-02 --to 2026-03-08

# JSON для дальнейшей обработки
python3 skills/wb-stats/scripts/wb_orders.py --week prev --json
```

## Метод подсчёта (важно!)

Детали в `references/api-notes.md`. Ключевые правила:

- **Считать ВСЕ заказы** — включая `isCancel: true`
- **Выручка = `priceWithDisc`**
- **Время в МСК (UTC+3)** — API отдаёт UTC

Этот метод даёт совпадение с WB Partners ±1 заказ.

## Токен

`/root/.openclaw/workspace/integrations/wildberries/config.json`

## Кастомные запросы

Если нужно что-то, чего нет в скрипте (остатки, продажи/выкупы, реклама) — читай `references/api-notes.md` с эндпоинтами и полями.
