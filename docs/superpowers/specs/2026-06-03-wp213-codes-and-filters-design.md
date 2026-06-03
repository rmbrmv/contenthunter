# WP#213 — Коды роликов и фильтры (под-проект B)

**Дата:** 2026-06-03
**Тикет:** OpenProject WP#213 «проверить логи событий», пункты 2, 3, 5
**Статус:** дизайн утверждён, готов к плану
**Репо кода:** `delivery-contenthunter` (локально `autowarm-testbench`). Файлы: `manual_publish_queue.js`, `publish_planner.js`, `public/index.html`, новый `content_code.js`
**Связанный под-проект:** A «Правдивость лога» (п.1/4/6) — SHIPPED+DEPLOYED 03.06 (PR #153, main 3b4b538)

---

## 1. Контекст и постановка

Под-проект B закрывает оставшиеся пункты WP#213 — сделать **код ролика** видимым/искомым по всему пайплайну выкладки и улучшить фильтры:

- **п.2:** код ролика + поиск по коду в ручной выкладке.
- **п.3:** код ролика в планировщике (показывать только админам — сопоставить исходно загруженное клиентом с тем, что у нас дальше).
- **п.5:** фильтр периодом (диапазон дат) в «Логе событий».

Код ролика введён в WP#174: `validator_projects.code_prefix` + `validator_content.code_number`, формат `PREFIX-NNN` (number<1000 → `lpad(…,3,'0')`, иначе как есть). Уже отображается в «Логе событий».

### Решения владельца (зафиксированы)
1. **п.2:** код-колонка + текстовый поиск по коду в ручной. Статус-фильтр (queued/in_progress/published) уже есть — не трогаем. «Искать везде» = код виден в ручной/планировщике/логе.
2. **п.5:** диапазон только в «Логе событий» (`date_from`–`date_to`). В ручной диапазон уже есть.
3. **п.3:** гейт показа кода — на фронте по `currentUser.role==='admin'`.
4. B — одним спеком/планом/PR.

### Текущее состояние кода (проверено)
- **Ручная:** `manual_publish_queue.js` — `JOINED_SELECT` уже джойнит `validator_projects vp` и `validator_content vc`, но НЕ селектит `code_prefix`/`code_number`; `rowToDict` не отдаёт `code`. Фронт `public/index.html`: `MPQ_COLS`, статус-фильтр чекбоксами, текстовые/daterange фильтры по колонкам.
- **Планировщик:** `publish_planner.js` `getPlannerCards` строит intents тремя SQL-ветками (full `qrows`, legacy, slot-only); `buildPlannerCards` (чистая) тащит `project_id/project_name/video_title` из `meta`. Кода нет. Фронт `plannerCardHtml`. Гейт admin на фронте есть (`currentUser.role==='admin'`).
- **Лог событий:** `lcFilterRow` имеет только `<input type="date" date_from>`. Бэкенд УЖЕ поддерживает `date_to` (`lifecycle.js applyClientSideFilters` обрабатывает `f.date_to`; эндпоинт `/api/lifecycle` пробрасывает `req.query.date_to`). → п.5 = чистый фронт.

---

## 2. Подход

**Общий JS-хелпер `formatContentCode(prefix, number)`** в новом `content_code.js`, используемый ручной (`rowToDict`) и планировщиком (маппинг intent'ов). SQL отдаёт сырые `code_prefix`+`code_number`, форматирование — в одном JS-месте (DRY).

Отклонено: дублировать SQL-CASE формата кода в каждой ветке планировщика и в ручной (повтор). `lifecycle.js` оставляем как есть — он форматирует код в SQL на своём слое; переписывать не в области B.

Радиус: чисто аддитивный UI + два места, отдающих новое поле `code`. Поведение публикации/диспетчеризации не меняется. Без миграции БД (колонки кода уже есть из WP#174).

---

## 3. Детальный дизайн

### 3.1. `content_code.js` (новый модуль)
```js
function formatContentCode(prefix, number) {
  if (!prefix || number == null) return null;
  const n = Number(number);
  return prefix + '-' + (n < 1000 ? String(n).padStart(3, '0') : String(n));
}
module.exports = { formatContentCode };
```
Pure-тест: `('RLM',14)→'RLM-014'`, `('LEX',12)→'LEX-012'`, `('WAN',1234)→'WAN-1234'`, `(null,5)→null`, `('X',null)→null`.

### 3.2. п.2 — код в ручной выкладке
**Backend (`manual_publish_queue.js`):**
- В `JOINED_SELECT` добавить в список колонок: `vp.code_prefix, vc.code_number` (vp и vc уже в JOIN).
- В `rowToDict`: `code: formatContentCode(m.code_prefix, m.code_number)` (require `content_code`).

**Frontend (`public/index.html`):**
- В `MPQ_COLS` добавить колонку `{ key: 'code', label: 'Код', filter: 'text' }` (первой или после телефона — уточнить расположение при реализации; по умолчанию первой).
- В `mpqCardRowHtml` вывести `card.code` (копируемая кнопка как в `lcRenderRows`); группировка по телефону сохраняется. Текстовый фильтр колонки уже даёт поиск по коду через `mpqMatch` (substring).
- Карточка группируется по телефону, но код — атрибут контента (один на строку). Для группы-карточки показываем код(ы) строк (обычно один контент). Деталь рендера — в плане.

### 3.3. п.3 — код в планировщике (только админам)
**Backend (`publish_planner.js`):**
- В каждой из 3 SQL-веток `getPlannerCards` добавить `vc.code_number` (join `validator_content vc ON vc.id = <content_id>` — content_id берётся из `ut.content_id`/`pq`/`s.content_id` соответственно) и `vp.code_prefix` (vp уже джойнится; где нет — добавить).
- В маппинге intent'ов добавить `code: formatContentCode(r.code_prefix, r.code_number)`.
- `buildPlannerCards`: в `cards.push({...})` добавить `code: meta.code` (из `meta = group[0]`).

**Frontend (`public/index.html`):**
- В `plannerCardHtml(c)` показать `c.code` **только если `currentUser?.role === 'admin'`** (иначе не рендерить).

### 3.4. п.5 — период в «Логе событий»
**Frontend only (`public/index.html`):**
- В `lcFilterRow` в ячейке «План.дата» добавить второй `<input type="date">` для `date_to` рядом с `date_from`: `onchange="lcSetFilter('date_to', this.value)"`, значение `f.date_to`.
- Бэкенд (`applyClientSideFilters`, эндпоинт) уже обрабатывает `date_to` — менять не нужно.

---

## 4. Тестирование (TDD)
- **Pure:**
  - `content_code.js`: формат (lpad<1000, raw≥1000, null-кейсы).
  - `buildPlannerCards`: карточка несёт `code` из `meta.code` (новый кейс в planner-тестах).
  - `rowToDict` (ручная): отдаёт `code` из `code_prefix`+`code_number` (в `test_manual_publish_queue.test.js`).
- **Live (RUN_LIVE_DB):**
  - `JOINED_SELECT` (ручная) возвращает `code_prefix`/`code_number` (smoke).
  - `getPlannerCards` отдаёт карточки с `code` для контента, у которого есть код.
- **Фронт:** sanity-проверки (date_to input присутствует; код-колонка в MPQ_COLS; admin-гейт в plannerCardHtml) — grep/`node -e` как в под-проекте A.

## 5. Деплой
- Один PR в `delivery-contenthunter` → merge main.
- Прод: `git pull` в `/root/.openclaw/workspace-genri/autowarm` (owned claude-user, без sudo) + `sudo pm2 restart 35`. Без миграции.
- Verify: ручная выкладка — колонка «Код» + поиск; планировщик (под админом) — код в карточке; «Лог событий» — фильтр диапазоном дат.

## 6. Вне области
- Без kill-switch (аддитивный UI, поведение не меняется, легко откатывается). Если по конвенции потребуется — env-флаг показа кода в планировщике добавляется тривиально.
- Глобальный кросс-вью поиск по коду (одно поле → где ролик сейчас) — не делаем (владелец выбрал «код виден в каждом разделе»).
