# rizz.market API

## Авторизация

```bash
# Получить токен
TOKEN=$(node -e "
const fetch=require('node-fetch');
fetch('https://api.rizz.market/api/graphql',{
  method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({query:'mutation{signIn(input:{phone:\"PHONE\",password:\"PASS\"}){token}}'})
}).then(r=>r.json()).then(d=>console.log(d.data.signIn.token))
")
```

## Ключевые мутации

```graphql
# Принять отклик
mutation { acceptOffer(input: { id: "OFFER_ID" }) }

# Отклонить отклик
mutation { declineOffer(input: { id: "OFFER_ID" }) }
```

## Запросы

```graphql
# Список откликов кампании
query CampaignOffers($input: CampaignOffersInput!, $pagination: PaginationInput!) {
  CampaignOffers(input: $input, pagination: $pagination) {
    items { id status blogger { username followers } }
    total
  }
}
```

## Скрипты

- `scripts/collect_offers.js` — собрать все отклики (GraphQL API, pagination)
- `scripts/scrape_offer_metrics.js` — Puppeteer-скрапинг метрик (просмотры, ER, боты)
- `scripts/accept_decline.js <accept|decline> <offer-id>` — принять/отклонить

## Важно

- `SocialNetworkStatistics` GraphQL возвращает нули — использовать Puppeteer для метрик
- Метрики: лейбл приходит первым, значение на следующей строке (`"Подписчики\n73,7 тыс."`)
- Перед скроллом в Puppeteer: `pointer-events: none` на кнопках чтобы не кликнуть случайно
