---
name: rizz-market-offers
description: >
  Collect, review, and accept/reject blogger applications (offers) on rizz.market for RELISME
  barter campaigns. Use when gathering blogger applications across campaigns, viewing blogger
  profiles with social media links, accepting or rejecting specific offers, or generating
  summaries of applicants and their social media profiles.
---

# rizz-market-offers

Сбор откликов блогеров и управление ими на rizz.market через GraphQL API.

## Credentials

- Phone: `79872820884`
- Password: `LsE-w44-qF8-tmz`
- API endpoint: `https://api.rizz.market/api/graphql`
- Auth: Bearer JWT (получить через `mutation SignIn`)

## Campaigns (RELISME)

| Кампания | ID |
|----------|-----|
| Свитшот-трансформер | `a8659d2d-ffd7-4e3f-996f-5987f1ba2039` |
| Кроп-свитшот | `dbfbdd42-d463-425e-aa10-41505fc0f2a1` |
| Футболка-трансформер | `738e3650-dca3-4344-b5f6-d34055999526` |
| Сумка-конструктор | `a7445758-0f43-44aa-9f31-6f13daa45f26` |
| Картхолдер | `b8642ec1-b000-46fa-965b-ebdc4dbe59b3` |
| Сумка-кошелёк 2в1 | `015bf839-09f6-4906-b974-c51ffa377106` |

## Workflows

### 1. Collect all offers

Запусти готовый скрипт:
```bash
node skills/rizz-market-offers/scripts/collect_offers.js
```
Результат → `rizz_offers_final.json` (110+ записей с именами, городами, биографиями, ссылками на соцсети).

### 2. View offer data structure

Каждый оффер содержит:
- `firstName`, `city`, `about` — данные блогера
- `socialType` (Instagram/Youtube/Tiktok/Vk), `socialUsername`, `socialUrl` — прямая ссылка
- `reward` (₽), `status`, `createdAt`, `offerUrl` — ссылка на карточку оффера

### 3. Accept / Reject

GraphQL мутации (см. `references/api.md`):

**Принять оффер:**
```graphql
mutation AcceptOffer($input: IdInput!) { acceptOffer(input: $input) }
# variables: {"input": {"id": "<offer-uuid>"}}
```

**Отклонить оффер:**
```graphql
mutation DeclineOffer($input: IdInput!) { declineOffer(input: $input) }
# variables: {"input": {"id": "<offer-uuid>"}}
```

**Workflow (Ян делает сам):**
1. Берёшь offer ID из `rizz_offers_final.json`
2. Получаешь токен: `node scripts/get_token.js`
3. Вызываешь мутацию через `scripts/accept_decline.js <accept|decline> <offer-id>`

---

## Правило развития скилла (для Эдварда)

Если Ян столкнулся с чем-то неизвестным («хочу X, не знаю как»):
1. Ян ставит задачу Эдварду
2. Эдвард разбирается и реализует
3. Эдвард **обязательно кладёт решение в скилл** (скрипт / reference)
4. Ян теперь умеет делать это сам

Цель: каждый раз когда Эдвард что-то разведал — скилл становится богаче.

### 4. Auth — получение JWT

```bash
node scripts/get_token.js  # выводит Bearer token
```

Или через GraphQL напрямую:
```bash
curl -s -X POST https://api.rizz.market/api/graphql \
  -H "Content-Type: application/json" \
  -d '{"operationName":"SignIn","variables":{"input":{"phone":"79872820884","password":"LsE-w44-qF8-tmz"}},"query":"mutation SignIn($input: SignInInput!) { signIn(input: $input) { token } }"}' \
  | jq '.data.signIn.token'
```

## Social URL Builder

```js
function buildSocialUrl(type, username) {
  return {
    Instagram: `https://www.instagram.com/${username}`,
    Youtube:   `https://www.youtube.com/@${username}`,
    Tiktok:    `https://www.tiktok.com/@${username}`,
    Vk:        `https://vk.com/${username}`,
    Telegram:  `https://t.me/${username}`,
  }[type] || `https://${type.toLowerCase()}.com/${username}`;
}
```

## Notes

- Offer IDs получаются через infinite scroll страницы `/app/advertiser/campaigns/{id}/offers` (не через API — отдельного query списка нет)
- Повторно запускать скрипт безопасно — он только читает, не изменяет статусы
- `campaignApplications` query НЕ существует на этой платформе — правильный путь: `GetOffer` по ID
- Полная API документация: `references/api.md`
