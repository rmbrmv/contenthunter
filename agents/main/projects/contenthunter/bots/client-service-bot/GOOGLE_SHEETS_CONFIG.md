# Google Sheets Configuration

## Таблица "Оплаты и контракты"

**Spreadsheet ID:** `1kMKgKgJKspoSny9rjZ5cKIyhXYe8IrD2Tstal4ZmpzY`

**URL:** https://docs.google.com/spreadsheets/d/1kMKgKgJKspoSny9rjZ5cKIyhXYe8IrD2Tstal4ZmpzY/

### Листы:

#### 1. Лист "Оплаты"
Используется для записи фактических поступлений денег от клиентов.

**Триггер:** Скриншот/файл платёжки в чате "Счета / оплаты / поступления" → топик "Поступления"

**Действия бота:**
- OCR распознавание (Google Vision API)
- Извлечение: Дата, Клиент, Сумма, Валюта
- Запись новой строки
- Выделение строки синим цветом
- Ответ на сообщение с номером строки

**Структура (предположительно):**
- A: Дата
- B: Клиент
- C: Сумма
- D: Валюта (RUB/AED/USD)
- E: Примечания
- ...

#### 2. Лист "Контракты"
Используется для записи условий контракта с клиентом.

**Триггер:** Сообщение Олега с условиями в топике чата "Заказы"

**Действия бота:**
- Парсинг условий из сообщения
- Извлечение сумм для:
  - Setup (сетап)
  - Delivery lab
  - Content lab
  - Upsell
- Определение типа сетапа (Setup-1/2/3)
- Запись в таблицу

**Структура (предположительно):**
- A: Дата
- B: Клиент
- C: Setup (сумма)
- D: Delivery lab (сумма)
- E: Content lab (сумма)
- F: Upsell (сумма)
- G: Тип сетапа (1/2/3)
- ...

---

## Шаблоны дорожных карт

### Setup-1
**Spreadsheet ID:** `1IICCBatKGsTVziFFXxNA5UnCrkiXsc3LePuimzWQqCU`

**URL:** https://docs.google.com/spreadsheets/d/1IICCBatKGsTVziFFXxNA5UnCrkiXsc3LePuimzWQqCU/

**Когда использовать:** В сообщении Олега указано "Setup-1"

### Setup-2
**Spreadsheet ID:** `1Yi555J92_DP2rj554pOB6RzoEZXPTnmgkXPiyEP4Lgo`

**URL:** https://docs.google.com/spreadsheets/d/1Yi555J92_DP2rj554pOB6RzoEZXPTnmgkXPiyEP4Lgo/

**Когда использовать:** В сообщении Олега указано "Setup-2"

### Setup-3
**Spreadsheet ID:** `1CUbXnk_jfGLpj0Sodn3xuupcCldRGUWDB4Xef1dyIQg`

**URL:** https://docs.google.com/spreadsheets/d/1CUbXnk_jfGLpj0Sodn3xuupcCldRGUWDB4Xef1dyIQg/

**Когда использовать:** В сообщении Олега указано "Setup-3"

---

## Папка для дорожных карт

**Folder ID:** `1HKp_cZ4Xy96iSIx0f9dlyCBP3AfB_SOm`

**URL:** https://drive.google.com/drive/folders/1HKp_cZ4Xy96iSIx0f9dlyCBP3AfB_SOm

**Действия бота при создании топика:**
1. Определить тип сетапа из сообщения Олега
2. Выбрать соответствующий шаблон (Setup-1/2/3)
3. Создать копию шаблона
4. Переименовать: `[Название клиента] - Дорожная карта`
5. Поместить в эту папку
6. Заполнить дату (если требуется)
7. Сохранить ссылку на дорожную карту

---

## Пример сообщения Олега с условиями (ожидается)

```
Клиент: Content Hunter
Setup-2
Setup: 50,000₽
Delivery lab: 120,000₽
Content lab: 80,000₽
Upsell: 30,000₽
```

Бот должен:
- Распознать "Setup-2"
- Извлечь суммы
- Записать в лист "Контракты"
- Создать копию шаблона "Setup-2"
- Поместить в папку дорожных карт
