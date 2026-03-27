# WB Seller API — справочник

## Токен

Путь: `/root/.openclaw/workspace/integrations/wildberries/config.json`

```python
import json
token = json.load(open('/root/.openclaw/workspace/integrations/wildberries/config.json'))['token']
headers = {"Authorization": f"Bearer {token}"}
```

## Эндпоинты

| Данные | URL |
|--------|-----|
| Заказы | `https://statistics-api.wildberries.ru/api/v1/supplier/orders?dateFrom=YYYY-MM-DD` |
| Продажи (выкупы) | `https://statistics-api.wildberries.ru/api/v1/supplier/sales?dateFrom=YYYY-MM-DD` |
| Карточки товаров | `https://content-api.wildberries.ru/content/v2/get/cards/list` |
| Остатки | `https://statistics-api.wildberries.ru/api/v1/supplier/stocks?dateFrom=YYYY-MM-DD` |

## Правила подсчёта заказов

### ✅ Правильный метод (совпадает с WB Partners ~±1 заказ)

1. **Считать ВСЕ заказы** — включая `isCancel: true`
2. **Выручка = `priceWithDisc`** — цена после скидки продавца, до SPP
3. **Время = МСК (UTC+3)** — API отдаёт UTC, прибавлять +3ч при фильтрации по дням

```python
from datetime import datetime, timedelta
MSK = timedelta(hours=3)

orders = [o for o in data
          if start_msk <= datetime.fromisoformat(o['date']) + MSK < end_msk]

revenue = sum(o['priceWithDisc'] for o in orders)
count   = len(orders)
```

### ❌ Не использовать
- `finishedPrice` для выручки — занижает (после SPP)
- `forPay` для выручки — это выплата продавцу, не выручка
- Фильтр `isCancel: False` для подсчёта заказов — занижает ~30-40%

## Поля заказа (orders)

| Поле | Описание |
|------|----------|
| `date` | Дата заказа (UTC) |
| `supplierArticle` | Артикул продавца |
| `nmId` | Артикул WB |
| `subject` | Категория товара |
| `brand` | Бренд |
| `totalPrice` | Цена до скидок |
| `discountPercent` | Скидка WB (%) |
| `priceWithDisc` | Цена после скидки WB ✅ выручка |
| `spp` | СПП скидка (%) |
| `finishedPrice` | Цена после СПП (покупатель заплатил) |
| `forPay` | К выплате продавцу |
| `isCancel` | Отменён ли заказ |
| `warehouseName` | Склад WB |
| `regionName` | Регион доставки |

## Поля продажи/выкупа (sales)

| Поле | Описание |
|------|----------|
| `saleID` | Начинается с S = продажа, R = возврат |
| `totalPrice` | > 0 продажа, < 0 возврат |
| `forPay` | К выплате продавцу |

## Период — неделя (пн–вс)

```python
# Неделя 02.03–08.03 в МСК
start = datetime(2026, 3, 2, 0, 0, 0)   # пн 00:00 МСК
end   = datetime(2026, 3, 9, 0, 0, 0)   # пн 00:00 МСК (не включительно)

orders = [o for o in data
          if start <= datetime.fromisoformat(o['date']) + MSK < end]
```
