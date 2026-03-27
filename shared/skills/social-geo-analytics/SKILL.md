---
name: Social Geo Analytics
description: Сбор демографических данных аудитории Instagram и TikTok (гео/возраст/пол) через ADB. Навигирует через UI dump+tap (без фиксированных координат), скроллит по карточкам и сохраняет результат в БД. Использовать когда нужно собрать или обновить аудиторию аккаунта Instagram или TikTok.
---

## Назначение

Сбор демографики аудитории Instagram и TikTok через ADB:

| Поле | Пример |
|------|--------|
| `geo` | `[{"city": "Москва", "pct": 9.2}, {"country": "РФ", "pct": 44}]` |
| `age_groups` | `[{"range": "25-34", "pct": 67.3}]` |
| `gender` | `{"male_pct": 56.3, "female_pct": 43.8}` |
| `followers` | `152` |

## Файлы

`/root/.openclaw/workspace-genri/autowarm/analytics_collector.py`  
Функции: `collect_audience_instagram(serial, port, account)` / `collect_audience_tiktok(serial, port, account)`

## Маршрут навигации — Instagram

```
1. am force-stop → am start deep link → профиль @account
2. Проверяем залогиненный аккаунт (instagram_get_current_account)
   → если не тот: tap заголовок → switcher (instagram_switch_account)
3. tap "Профессиональная панель"
4. tap "Просмотры"
5. swipe вниз до появления "Аудитория" (до 6 итераций)
6. Проверяем наличие данных в секции "Аудитория":
   a. Если данные есть (фильтр 14 дней) → переходим к сбору (шаг 7)
   b. Если "Демографические данные отсутствуют. Выберите последние 7 или 30 дней":
      → tap текущий фильтр → tap "Последние 30 дней" → tap "Обновить"
7. Горизонтальный скролл вправо (swipe 900→180 по Y≈1244) до 8 итераций
   Карточки: города → страны → возрастной диапазон → пол
8. dump_ui на каждом шаге → collect texts → парсинг
9. Если текстовый парсинг не дал результата → скриншот → Groq AI fallback
```

## Маршрут навигации — TikTok

```
1. am start deep link → tiktok.com/@account (com.zhiliaoapp.musically)
2. dump_ui → читаем followers из профиля
3. tap_ui меню профиля (≡ / More options / More / Меню / Настройки)
   → fallback координаты (1040, 120) если tap_ui не нашёл
4. tap_ui "Creator tools" / "Инструменты автора" / "Инструменты"
5. tap_ui "Analytics" / "Аналитика"
6. tap_ui вкладку "Followers" / "Подписчики"
7. swipe вниз 3 раза (пропуск графика подписчиков)
8. Поиск scrollable RecyclerView в dump_ui → определение Y-координаты свайпа
   fallback: y=1200
9. Сброс к первой карточке (3 свайпа вправо)
10. Горизонтальные свайпы влево (swipe 900→120) до 12 итераций
    Карточки: Top territories → Gender → Age groups
    Ранняя остановка: нашли все три блока
11. Текстовый парсинг из all_texts_seq:
    - Top territories / Топ территорий → geo[]
    - Men/Women / Мужчины/Женщины → gender{}
    - Age groups / Возрастной диапазон → age_groups[]
12. AI fallback (скриншоты 4 позиций карточек) если парсинг неполный
    → Groq → LaoZhang/Anthropic
13. am force-stop com.zhiliaoapp.musically
```

### Поддерживаемые текстовые метки (EN/RU)

| Блок | EN | RU |
|------|----|----|
| Меню | More options, More, Menu | Меню, Настройки, Ещё |
| Инструменты | Creator tools, Creator Tools | Инструменты автора, Инструменты |
| Аналитика | Analytics | Аналитика, Статистика |
| Подписчики | Followers, Follower | Подписчики |
| Гео-секция | Top territories, Top countries, Countries | Топ территорий, Страны |
| Пол | Men, Male, Women, Female | Мужчины, Мужской, Женщины, Женский |
| Возраст | Age groups, Age range | Возрастной диапазон, Возрастные группы |

## Критические особенности свайпов

| Ситуация | Свайп | Причина |
|----------|-------|---------|
| Скролл вниз к Аудитории | `540 1800 → 540 600` (вертикаль) | Стандартный скролл страницы |
| Скролл между карточками | `900 1244 → 180 1244` (горизонталь) | RecyclerView carousel внутри секции |
| **НЕ тапать `>`** у Аудитории | — | Это переход на отдельную страницу, ломает фильтр |

## Запуск вручную

```python
from analytics_collector import collect_audience_instagram, collect_audience_tiktok

# Instagram
result = collect_audience_instagram('RF8Y80ZV8NW', 15017, 'my_account')

# TikTok
result = collect_audience_tiktok('RF8Y80ZV8NW', 15017, 'my_tiktok_account')
```

## БД

Результат сохраняется через `save_audience_snapshot()` в таблицу `account_audience_snapshots` (openclaw@localhost:5432).

## API

```bash
# Запуск через autowarm API (localhost:3848)
# Аудитория собирается автоматически в рамках collect_account → process_account
```

## Диагностика — Instagram

| Проблема | Причина | Решение |
|---------|---------|---------|
| `geo=[]` после парсинга | Горизонтальный свайп не в той зоне | Проверить Y-координату RecyclerView через dump_ui |
| `no_views_button` | Instagram открылся не на профиле | Увеличить `time.sleep` после deep link |
| `no_audience_section` | Мало данных или не бизнес-аккаунт | Проверить тип аккаунта |
| `Groq OK` но `geo=[]` | Скриншот сделан в неправильный момент | Секция Аудитория не видна на экране |
| `данные отсутствуют` при 14 днях | Мало активности за период | Переключить фильтр на 30 дней → Обновить |

## Диагностика — TikTok

| Проблема | Причина | Решение |
|---------|---------|---------|
| `no_creator_tools` | Меню открылось, но Creator tools не найден | Аккаунт не является Creator — проверить тип |
| `no_analytics` | Creator tools открыт, Analytics не виден | Подождать загрузки, увеличить sleep после tap |
| `geo=[]` после парсинга | swipe_y промахнулся мимо карточек | В dump_ui нет scrollable="true" — fallback y=1200 |
| AI fallback всегда | dump_ui не видит текста в карточках | TikTok рисует через WebView/Canvas — только AI работает |
| Меню не открывается | tap_ui не нашёл кнопку + коорд. устарели | Проверить dump_ui вручную: `adb shell uiautomator dump` |
| Карточки не листаются | stuck_count=3 сразу | Возможно, Followers tab не открылась — проверить `tap_ui Followers` |
