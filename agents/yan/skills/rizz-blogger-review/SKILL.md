---
name: rizz-blogger-review
description: >
  Полный цикл обработки откликов блогеров с rizz.market — сбор заявок, парсинг метрик через
  Puppeteer, Apify-анализ профилей (Instagram/TikTok), vision-анализ контента, scoring и
  генерация HTML-отчёта с карточками. Использовать когда нужно собрать и проанализировать
  отклики на бартер-кампанию, сформировать отчёт с рекомендациями, принять или отклонить
  отклики на rizz.market.
---

# rizz-blogger-review

Универсальный воркфлоу: от откликов на rizz.market до финального HTML-отчёта и решений по каждому блогеру.

## Воркфлоу

### 1. Сбор откликов

```bash
cd /root/.openclaw/workspace-yan/skills/rizz-blogger-review
node scripts/collect_offers.js
# → offers_collected.json (все отклики с базовыми данными)
```

Скрипт требует: `RIZZ_PHONE`, `RIZZ_PASS`, список Campaign IDs в файле.

### 2. Парсинг метрик (Puppeteer)

```bash
node scripts/scrape_offer_metrics.js
# → обновляет offers_collected.json с метриками (просмотры, ER, бот-риск)
```

Занимает ~3-5 мин на 100 блогеров. Метрики берутся только из UI (GraphQL API даёт нули).

### 3. Apify-парсинг профилей

⚠️ **Только по явному запросу от Романа** — платный шаг (~$0.095/профиль).

В Lobster-пайплайне отключён по умолчанию. Запускать вручную:
```bash
APIFY_TOKEN="[REDACTED-APIFY-TOKEN]" \
  node scripts/apify_profiles.js
```
Или через пайплайн с флагом: `lobster run rizz-review --apify`

Профили кэшируются в `data/profiles_cache.json` — повторно не скачиваются.

Акторы:
- Instagram posts: `apify~instagram-scraper` (~$0.095/запуск, лимит 9 постов)
- TikTok: `clockworks~free-tiktok-scraper`

### 4. Vision-анализ

Батчи по 3 блогера за вызов `image` tool. Подробный промпт и критерии — в **references/vision_prompt.md**.

Экономия: блогеров с явно нерелевантным bio (мамский, бьюти-услуги, спорт) оценивать без vision.

Результаты сохранять инкрементально в `/tmp/vision_results_full.json`.

### 5. Генерация HTML-отчёта

```bash
python3 scripts/gen_report.py \
  --profiles /tmp/profiles_enriched.json \
  --vision /tmp/vision_results_full.json \
  --output reports/bloggers_cards_final.html \
  --brand "НазваниеБренда" \
  --template skills/rizz-blogger-review/assets/report_template.html
```

Отчёт — интерактивные карточки с фильтрами (платформа, рекомендация, score, поиск).

**Важно**: после генерации проверить количество `<script>` тегов — должен быть 1 открывающий и 1 закрывающий.

### 6. Принятие/отклонение

**ТОЛЬКО после явного одобрения от Романа ("делай"):**

```bash
node scripts/accept_decline.js accept OFFER_ID
node scripts/accept_decline.js decline OFFER_ID
```

Никогда не принимать/отклонять без явного «да, делай» от пользователя.

## 🦞 Lobster Pipeline (автоматизация)

Весь воркфлоу доступен как Lobster-пайплайн с approval gate:

```bash
# Запуск полного цикла
lobster run rizz-review.lobster

# С чистого листа (игнорировать checkpoint)
lobster run rizz-review.lobster --args-json '{"fresh": "--fresh"}'

# Другой бренд
lobster run rizz-review.lobster --args-json '{"brand": "НазваниеБренда"}'
```

Или через OpenClaw tool call:
```json
{
  "action": "run",
  "pipeline": "/root/.openclaw/workspace-yan/skills/rizz-blogger-review/rizz-review.lobster",
  "timeoutMs": 600000
}
```

**Шаги пайплайна:**
1. `collect` → сбор откликов (2 мин)
2. `scrape` → парсинг метрик Puppeteer (5 мин)
3. `apify` → парсинг профилей Instagram/TikTok через Apify (10 мин)
4. `report` → генерация HTML-отчёта
5. `approve` → ⏸️ ПАУЗА — ждёт одобрения от пользователя
6. `execute` → после одобрения, ручные accept/decline

Vision-анализ (шаг 4 в мануальном воркфлоу) пока остаётся вне пайплайна — требует `image` tool с батчами.

## Scoring

Подробная формула — **references/scoring.md**.

Краткая: просмотры (30) + content_fit (25) + ER (20) + платформа (15) + тренд (10) − боты.

## API rizz.market

Детали авторизации и GraphQL-запросы — **references/rizz_api.md**.

## Файлы воркфлоу

| Файл | Описание |
|---|---|
| `offers_collected.json` | Все отклики с метриками |
| `offers_table.csv` | CSV для передачи заказчику |
| `/tmp/profiles_enriched.json` | 161 профиль с метриками |
| `/tmp/vision_results_full.json` | Результаты vision-анализа |
| `reports/bloggers_cards_final.html` | Финальный HTML-отчёт |
