---
name: rizz-campaign
description: Создание и управление бартерными кампаниями на rizz.market для RELISME/RELIZME. Используй когда нужно создать, обновить, запустить, остановить или архивировать кампанию на rizz.market. Содержит GraphQL API, правила оформления, правила оплаты, маппинг топиков и алгоритм публикации.
---

# rizz-campaign — публикация кампаний на rizz.market

## Авторизация

```
POST https://api.rizz.market/api/graphql
mutation { signIn(input: {phone:"79872820884",password:"LsE-w44-qF8-tmz"}) { token } }
```
→ Bearer токен. Передавать в заголовке `Authorization: Bearer <token>`.

## Алгоритм публикации кампании

1. Авторизоваться → получить токен
2. Убедиться что для этого товара нет активных/stopped кампаний (иначе ошибка «уже заведена кампания»). Если есть Finished — архивировать их через `archiveCampaign`
3. Создать кампанию через `createCampaign`
4. Сразу остановить через `stopCampaign` (если нужна проверка перед запуском)
5. После одобрения — запустить через `resumeCampaign`

## Создание кампании (createCampaign)

```graphql
mutation CreateCampaign($input: CreateCampaignInput!) {
  createCampaign(input: $input) { id title status }
}
```

**Обязательные поля:**
- `title` String
- `description` String — **plain text без markdown** (### ** --- не отображаются корректно)
- `amountOfCreators` Float — кол-во интеграций
- `types` [CampaignType!] — см. ниже
- `productId` String — UUID продукта на rizz.market
- `topicIds` [String!] — см. таблицу топиков
- `payTaxForCreators` Boolean — обычно false
- `requiresMarking` Boolean — обычно false
- `rewardStrategy` — `"Barter"` для бартера
- `maxReward` Float — цена товара × 1.15 (запас 15% на скачки цены)
- `minReach` Float — минимальный охват блогера (обычно 1000)

## Обновление кампании (updateCampaign)

```graphql
mutation ($input: UpdateCampaignInput!) { updateCampaign(input: $input) }
```

**Обязательные поля UpdateCampaignInput:**
- `id`, `title`, `description`, `amountOfCreators`, `types`, `topicIds`, `maxReward`
- НЕТ полей: `requiresMarking`, `payTaxForCreators` (не определены в UpdateCampaignInput)
- Возвращает `Boolean!` — не добавлять selection set

## Управление статусами

```graphql
# Остановить (Stopped)
mutation ($input: IdInput!) { stopCampaign(input: $input) { id status } }

# Завершить (Finished)
mutation ($input: IdInput!) { finishCampaign(input: $input) { id status } }

# Архивировать (Archived) — только из Finished
mutation ($input: IdInput!) { archiveCampaign(input: $input) { id status } }

# Возобновить
mutation ($input: IdInput!) { resumeCampaign(input: $input) { id status } }
```

Цепочка удаления: `stopCampaign` → `finishCampaign` → `archiveCampaign`

## CampaignType (типы контента)

| Значение | Платформа |
|----------|-----------|
| `InstagramReels` | Instagram Reels |
| `InstagramStories` | Instagram Stories |
| `InstagramPost` | Instagram пост |
| `TiktokReels` | TikTok |
| `YoutubeShorts` | YouTube Shorts |
| `LikeeVideo` | Likee |
| `OkPost` | Одноклассники |
| `VkPost` | ВКонтакте |

Для одежды/аксессуаров: `["InstagramReels", "TiktokReels", "YoutubeShorts"]`

## Топики (topicIds)

| ID | Название |
|----|----------|
| 1 | Авто и мото |
| 4 | Дети и родители |
| 6 | Здоровье и медицина |
| 8 | Личные блоги и образ жизни |
| 10 | Фотография и кино |
| 12 | Красота и уход |
| 14 | Мода и стиль |
| 24 | Спорт и отдых |
| 26 | Хобби и увлечения |
| 27 | Юмор и развлечения |
| 29 | Игры и консоли |
| 30 | Другое |

Для одежды: `["14", "8"]` (Мода и стиль + Личные блоги)
Для аксессуаров: `["14", "12"]` (Мода и стиль + Красота и уход)

## Правила оформления описания

- **Только plain text** — markdown не рендерится на платформе
- Эмодзи как разделители разделов: 🎨 💡 🎬 🗣 ✅ ⛔️ 📝
- Тире через — (не `-`)
- Структура описания: согласование цвета → идея → сценарий → озвучка → обязательно → запрещено → отзыв → дедлайн

## Дедлайн и процесс

- Дедлайн черновика: **5–7 дней** с момента получения товара
- Процесс: черновик → согласование → публикация (блогер не публикует без одобрения)

## Продукты RELISME на rizz.market

| Товар | rizz product ID | WB артикул | Цена | Топики |
|-------|----------------|-----------|------|--------|
| Свитшот базовый оверсайз | 9839be06-6e9f-41a0-b9e3-1efaaa4ff0f0 | 803481280 | 3490₽ | 14, 8 |
| Кроп-свитшот | 96c666c5-85df-403e-b576-4fda7be553a1 | 803449879 | 3290₽ | 14, 8 |
| Футболка-трансформер | b58727d8-24f4-4ab2-a9a2-e4aa90d462a0 | 713610318 | 1800₽ | 14, 8 |
| Сумка комбо трансформер | 2b1cdb91-17d6-4689-bc32-7ce3ccc53733 | 621920765 | 1200₽ | 14, 12 |
| Картхолдер складной | 0dfe1c7f-a837-4f85-b3f5-24ff3d64c89c | 680927226 | 530₽ | 14, 12 |
| Сумка-кошелёк 2в1 | dda27774-32b4-48cc-8477-7186299a7cf7 | 732959403 | 1200₽ | 14, 12 |

## Целевое кол-во интеграций

| Товар | amountOfCreators |
|-------|-----------------|
| Свитшот базовый | 10 |
| Кроп-свитшот | 5 |
| Футболка-трансформер | 5 |
| Сумка комбо | 10 |
| Картхолдер | 10 |
| Сумка-кошелёк | 10 |

## Частые ошибки

- `updateCampaign` возвращает `Boolean!` — не добавлять `{ id title }` в ответ
- `createCampaign` — нельзя создать две активные/stopped кампании на один товар; сначала архивировать старые
- `archiveCampaign` — работает только из статуса Finished, не из Stopped
- Топики 6 (Здоровье) и 4 (Дети) — не для одежды/аксессуаров
- `minReach` — корректное поле (не `minFollowers`, не `followersFrom`)
- ТЗ в описании — хранится в `/root/.openclaw/workspace-yan/relisme-barter-tz.md`
