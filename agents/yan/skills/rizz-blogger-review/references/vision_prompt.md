# Vision-анализ блогеров

## Batch-формат

Анализировать по 3 блогера за один вызов `image` tool.
Для каждого блогера загружать 4-6 обложек постов/видео.

### Откуда брать изображения

**Instagram** — Apify KV store:
```
https://api.apify.com/v2/key-value-stores/{KV_ID}/records/{username}_{0..5}
```
KV store для RELISME: `OSNixuaPizWbhq07j`

**TikTok** — поле `image_urls` из профиля (список URL обложек), первые 4-6.
Если URL 404 → взять из `/tmp/tt_30posts.json` по `authorMeta.name`.

### Промпт для vision

```
Анализирую [N] блогеров для [БРЕНД] ([описание бренда, ЦА]).

Фото 1-N: @username (Instagram/TikTok, Xк подп, bio: "...")
[следующие фото] @username2 ...

Для каждого ОДНОЙ строкой:
@username | ✅⚠️❌ | content_fit 0-25 | вывод до 70 символов
```

### Критерии verdict

- **✅** — Fashion-фокус, эстетика бренда, ЦА совпадает
- **⚠️** — Частичное совпадение: стиль есть, но не главная тема
- **❌** — Нерелевантно (мамский контент, бьюти-услуги, юмор, спорт, нет охвата)

### Сохранение результатов

```python
import json
with open('/tmp/vision_results_full.json') as f: r = json.load(f)
r += [
    {'username': 'user1', 'verdict': '✅', 'content_fit': 22, 'summary': 'Fashion-фокус...'},
    ...
]
with open('/tmp/vision_results_full.json', 'w') as f: json.dump(r, f, ensure_ascii=False)
```

### Оптимизация

- Блогеров с явно нерелевантным bio (мамский блог, ЗОЖ, бьюти-услуги) можно оценивать **без vision** (экономия):
  `{'verdict': '❌', 'content_fit': 2, 'summary': 'Описание из bio — не ЦА'}` 
- Vision нужен только когда bio неоднозначное или блогер потенциально подходит
