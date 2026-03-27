# rizz.market GraphQL API Reference

## Authentication

```graphql
mutation SignIn($input: SignInInput!) {
  signIn(input: $input) {
    token
  }
}
# variables: {"input": {"phone": "79872820884", "password": "LsE-w44-qF8-tmz"}}
```

Header: `Authorization: Bearer <token>`

---

## CampaignOffers — список откликов по кампании (без scroll!)

```graphql
query CampaignOffers($input: CampaignOffersInput!, $pagination: PaginationInput!) {
  campaignOffers(input: $input, pagination: $pagination) {
    items {
      id status reward
      creator { firstName city }
      socialNetwork { username type }
    }
    meta { total }
  }
}
# variables: {"input": {"campaignId": "<campaign-uuid>"}, "pagination": {"page": 1, "perPage": 100}}
```

✅ Используй этот query вместо scroll — быстрее и надёжнее.

---

## GetOffer — полные данные по одному офферу

```graphql
query GetOffer($input: IdInput!) {
  offer(input: $input) {
    id reward description createdAt status processingStatus
    work { id __typename }
    creator {
      id firstName city about birthDate isVerified
      image { id link __typename }
      __typename
    }
    hidden
    socialNetwork {
      id username
      topics { id label __typename }
      type __typename
    }
    campaign {
      id title reward createdAt types
      product { id title price __typename }
      __typename
    }
    __typename
  }
}
# variables: {"input": {"id": "<offer-uuid>"}}
```

**Поля socialNetwork.type:** `Instagram`, `Youtube`, `Tiktok`, `Vk`, `Telegram`

---

## AcceptOffer — принять оффер

```graphql
mutation AcceptOffer($input: IdInput!) {
  acceptOffer(input: $input)
}
# variables: {"input": {"id": "<offer-uuid>"}}
```

---

## DeclineOffer — отклонить оффер

```graphql
mutation DeclineOffer($input: IdInput!) {
  declineOffer(input: $input)
}
# variables: {"input": {"id": "<offer-uuid>"}}
```

---

## SocialNetworkStatistics

```graphql
query SocialNetworkStatistics($input: IdInput!) {
  socialNetworkStatistics(input: $input) {
    followersCount
    totalContent
    engagementRate
    averageViews
  }
}
# variables: {"input": {"id": "<socialNetwork-uuid>"}}
```

---

## Статусы офферов

- `Pending` — ожидает решения
- `Accepted` — принят
- `Declined` — отклонён

## Известные изменения статусов (ручные)

| Дата | Кампания | Блогер | Действие |
|------|----------|--------|----------|
| 2026-03-04 | Сумка-кошелёк 2в1 | Анна @lallasl67 (Instagram) | ✅ Принят (Ян, разведка) |
| 2026-03-04 | Сумка-кошелёк 2в1 | Анна @annacherkasova_off (TikTok) | ❌ Отклонён (Ян, разведка) |
