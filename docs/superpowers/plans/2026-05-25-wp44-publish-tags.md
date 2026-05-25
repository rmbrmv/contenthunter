# WP #44 — Добивка тегов в описание публикаций — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При сборке текста публикации обогащать набор тегов — клиентские теги плюс случайная добивка из `keywords` бренд-профиля (распаковки) до 5, когда у контента меньше 5 тегов. Едино для Instagram / TikTok / YouTube.

**Architecture:** Новый чистый модуль `hashtag_enrich.js` (autowarm) с функцией `enrichHashtags()` (нормализация + дедуп + рандомная добивка) и DB-хелпером `getBrandKeywords()`. В `server.js` обогащённый массив подставляется в двух местах сборки caption — `assignUnicResultsToQueue` (авто-очередь) и ручной endpoint постановки. Дальше существующий код раскладывает теги правильно: IG/TT — в строку `#теги` внутри caption; YouTube — массив `hashtags` доезжает до публикатора, который дописывает `#теги` в поле описания. Поведение под env-флагами (kill-switch).

**Tech Stack:** Node.js (CommonJS), `node:test` + `node:assert/strict`, PostgreSQL (`pg` pool), общая БД `openclaw`.

**Рабочая директория (код):** `/home/claude-user/autowarm-testbench`
**Spec:** `docs/superpowers/specs/2026-05-25-wp44-publish-tags-design.md`

---

## Аудит producer'ов publish_queue (зафиксировано на этапе дизайна)

В `server.js` четыре `INSERT INTO publish_queue`:
- **`assignUnicResultsToQueue` (~6463)** — реальная публикация, строит caption → **обогащаем** (Task 4).
- **ручной endpoint (~2397)** — реальная публикация, строит caption → **обогащаем** (Task 5).
- **`clampPastSlot` (~6172)** и **legacy-clamp (~6259)** — audit-строки `status='past_slot_dropped'` без caption/hashtags → **исключены** (нечего обогащать).

GET-эндпоинты `/api/publish/videos` (~2171) и `/api/unic/results` (~5367) — read-only листинг, не producer'ы. Других модулей-producer'ов нет (`grep -rln "INSERT INTO publish_queue" *.js` → только `server.js`).

## File Structure

- **Create:** `hashtag_enrich.js` — модуль: `enrichHashtags()` (чистая) + `getBrandKeywords()` (DB).
- **Create:** `hashtag_enrich.test.js` — юнит-тесты `node --test`.
- **Modify:** `server.js` — require модуля + env-константы (Task 3); врезка в `assignUnicResultsToQueue` (Task 4); врезка в ручной endpoint (Task 5).

---

### Task 1: Чистая функция `enrichHashtags`

**Files:**
- Create: `/home/claude-user/autowarm-testbench/hashtag_enrich.js`
- Test: `/home/claude-user/autowarm-testbench/hashtag_enrich.test.js`

- [ ] **Step 1: Написать падающие тесты**

Создать `hashtag_enrich.test.js`:

```js
// hashtag_enrich.test.js — node --test hashtag_enrich.test.js
//
// Тесты обогащения тегов (WP#44): нормализация, дедуп, рандомная добивка.

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { enrichHashtags } = require('./hashtag_enrich');

// детерминированный shuffle для тестов — порядок не меняем
const idShuffle = (arr) => arr.slice();

test('добивает до 5 из keywords, когда клиентских тегов меньше 5', () => {
  const out = enrichHashtags(['покер', 'еноты'], ['обучение', 'стратегия', 'казино'], { shuffle: idShuffle });
  assert.deepEqual(out, ['покер', 'еноты', 'обучение', 'стратегия', 'казино']);
});

test('не трогает теги, если их уже 5 (в БД за keywords не лезем)', () => {
  const out = enrichHashtags(['a', 'b', 'c', 'd', 'e'], ['x', 'y'], { shuffle: idShuffle });
  assert.deepEqual(out, ['a', 'b', 'c', 'd', 'e']);
});

test('многословный keyword склеивается без пробелов и lowercase', () => {
  const out = enrichHashtags([], ['Уход За Кожей'], { shuffle: idShuffle });
  assert.deepEqual(out, ['уходзакожей']);
});

test('дедуп: keyword, совпадающий с клиентским тегом (разный регистр), пропускается', () => {
  const out = enrichHashtags(['Покер'], ['покер', 'стратегия'], { shuffle: idShuffle, target: 3 });
  assert.deepEqual(out, ['Покер', 'стратегия']);
});

test('пустой/отсутствующий пул keywords → клиентские теги как есть', () => {
  assert.deepEqual(enrichHashtags(['покер'], [], { shuffle: idShuffle }), ['покер']);
  assert.deepEqual(enrichHashtags(['покер'], null, { shuffle: idShuffle }), ['покер']);
});

test('keywords меньше потребности → частичная добивка', () => {
  const out = enrichHashtags(['a', 'b', 'c'], ['x'], { shuffle: idShuffle });
  assert.deepEqual(out, ['a', 'b', 'c', 'x']);
});

test('ведущий # у клиентских тегов снимается, дубли убираются', () => {
  const out = enrichHashtags(['#покер', '##покер', 'еноты'], [], { shuffle: idShuffle });
  assert.deepEqual(out, ['покер', 'еноты']);
});

test('слишком длинный keyword (> maxLen) отбрасывается', () => {
  const longKw = 'оченьдлинноеключевоесловокотороепревышаетлимитдлины';
  const out = enrichHashtags([], [longKw, 'кратко'], { shuffle: idShuffle, maxLen: 30 });
  assert.deepEqual(out, ['кратко']);
});

test('keyword из одной пунктуации нормализуется в пустоту и пропускается', () => {
  const out = enrichHashtags([], ['!!!', '---', 'тег'], { shuffle: idShuffle });
  assert.deepEqual(out, ['тег']);
});

test('kill-switch enabled=false → добивки нет, но клиентские теги нормализуются', () => {
  const out = enrichHashtags(['#покер'], ['стратегия'], { enabled: false, shuffle: idShuffle });
  assert.deepEqual(out, ['покер']);
});
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `cd /home/claude-user/autowarm-testbench && node --test hashtag_enrich.test.js`
Expected: FAIL — `Cannot find module './hashtag_enrich'`.

- [ ] **Step 3: Реализовать модуль**

Создать `hashtag_enrich.js`:

```js
// hashtag_enrich.js — WP#44
//
// Обогащение набора тегов публикации: клиентские теги + рандомная добивка
// из keywords бренд-профиля (распаковки) до целевого числа (по умолчанию 5).
// enrichHashtags — чистая функция (тестируется без БД).
// getBrandKeywords — лёгкий запрос keywords распаковки по project_id.

// Fisher-Yates shuffle (по умолчанию)
function defaultShuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/**
 * @param {string[]} clientTags    теги из планировщика (validator_content.hashtags)
 * @param {string[]} brandKeywords keywords распаковки (validator_brand_profiles.keywords)
 * @param {object}   opts          { enabled=true, target=5, maxLen=30, shuffle=defaultShuffle }
 * @returns {string[]} итоговый набор тегов (без ведущего '#')
 */
function enrichHashtags(clientTags, brandKeywords, opts = {}) {
  const {
    enabled = true,
    target = 5,
    maxLen = 30,
    shuffle = defaultShuffle,
  } = opts;

  // 1. Нормализуем клиентские теги: снять ведущий '#', обрезать, дедуп (без учёта регистра).
  //    Текст самого тега сохраняем как ввёл клиент.
  const result = [];
  const seen = new Set();
  for (const raw of (Array.isArray(clientTags) ? clientTags : [])) {
    const t = String(raw == null ? '' : raw).trim().replace(/^#+/, '').trim();
    if (!t) continue;
    const key = t.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(t);
  }

  if (!enabled) return result;
  if (result.length >= target) return result;

  // 2. Пул кандидатов из keywords: lowercase, убрать всё кроме букв/цифр/'_',
  //    отбросить пустые/длинные/дубли.
  const pool = [];
  const poolSeen = new Set();
  for (const raw of (Array.isArray(brandKeywords) ? brandKeywords : [])) {
    const norm = String(raw == null ? '' : raw)
      .trim()
      .replace(/^#+/, '')
      .toLowerCase()
      .replace(/[^\p{L}\p{N}_]/gu, '');
    if (!norm) continue;
    if (norm.length > maxLen) continue;
    if (seen.has(norm) || poolSeen.has(norm)) continue;
    poolSeen.add(norm);
    pool.push(norm);
  }

  // 3. Перемешать пул и добрать недостающее.
  const need = target - result.length;
  const picked = shuffle(pool).slice(0, need);
  return result.concat(picked);
}

module.exports = { enrichHashtags, defaultShuffle };
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd /home/claude-user/autowarm-testbench && node --test hashtag_enrich.test.js`
Expected: PASS — все тесты зелёные.

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add hashtag_enrich.js hashtag_enrich.test.js
git commit -m "feat(wp44): enrichHashtags — добивка тегов из распаковки (чистая функция)"
```

---

### Task 2: DB-хелпер `getBrandKeywords`

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/hashtag_enrich.js`
- Test: `/home/claude-user/autowarm-testbench/hashtag_enrich.test.js`

- [ ] **Step 1: Дописать падающие тесты**

Добавить в конец `hashtag_enrich.test.js`:

```js
const { getBrandKeywords } = require('./hashtag_enrich');

test('getBrandKeywords возвращает массив keywords из строки БД', async () => {
  const fakePool = { query: async () => ({ rows: [{ keywords: ['зож', 'витамины'] }] }) };
  assert.deepEqual(await getBrandKeywords(fakePool, 107), ['зож', 'витамины']);
});

test('getBrandKeywords: нет projectId → [] без запроса', async () => {
  let called = false;
  const fakePool = { query: async () => { called = true; return { rows: [] }; } };
  assert.deepEqual(await getBrandKeywords(fakePool, null), []);
  assert.equal(called, false);
});

test('getBrandKeywords: нет профиля → []', async () => {
  const fakePool = { query: async () => ({ rows: [] }) };
  assert.deepEqual(await getBrandKeywords(fakePool, 999), []);
});

test('getBrandKeywords: keywords не массив (null/строка) → []', async () => {
  const fakePool = { query: async () => ({ rows: [{ keywords: null }] }) };
  assert.deepEqual(await getBrandKeywords(fakePool, 5), []);
});

test('getBrandKeywords: ошибка запроса → [] (не падаем)', async () => {
  const fakePool = { query: async () => { throw new Error('db down'); } };
  assert.deepEqual(await getBrandKeywords(fakePool, 5), []);
});
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `cd /home/claude-user/autowarm-testbench && node --test hashtag_enrich.test.js`
Expected: FAIL — `getBrandKeywords is not a function`.

- [ ] **Step 3: Реализовать `getBrandKeywords`**

В `hashtag_enrich.js` добавить функцию ПЕРЕД `module.exports` и расширить экспорт:

```js
/**
 * Достаёт keywords распаковки (validator_brand_profiles.keywords) по project_id.
 * Любая проблема (нет id / нет профиля / не массив / ошибка БД) → [].
 * @param {import('pg').Pool} pool
 * @param {number|null} projectId
 * @returns {Promise<string[]>}
 */
async function getBrandKeywords(pool, projectId) {
  if (!projectId) return [];
  try {
    const { rows } = await pool.query(
      'SELECT keywords FROM validator_brand_profiles WHERE project_id = $1 LIMIT 1',
      [projectId]
    );
    const kw = rows[0] && rows[0].keywords;
    return Array.isArray(kw) ? kw : [];
  } catch (e) {
    console.warn(`[tag-fill] getBrandKeywords failed for project=${projectId}: ${e.message}`);
    return [];
  }
}
```

И заменить строку экспорта на:

```js
module.exports = { enrichHashtags, getBrandKeywords, defaultShuffle };
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `cd /home/claude-user/autowarm-testbench && node --test hashtag_enrich.test.js`
Expected: PASS — все тесты зелёные (15 штук).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add hashtag_enrich.js hashtag_enrich.test.js
git commit -m "feat(wp44): getBrandKeywords — чтение keywords распаковки по project_id"
```

---

### Task 3: Подключить модуль и env-флаги в server.js

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/server.js` (вверху, рядом с другими флагами ~16-17)

- [ ] **Step 1: Добавить require и env-константы**

Найти строку 17:

```js
const QUEUE_TRANSFER_COLUMNS_ENABLED = process.env.QUEUE_TRANSFER_COLUMNS_ENABLED !== 'false';
```

Добавить сразу ПОСЛЕ неё:

```js
// WP#44: добивка тегов в описание из keywords распаковки
const { enrichHashtags, getBrandKeywords } = require('./hashtag_enrich');
const PUBLISH_TAG_FILL_ENABLED = process.env.PUBLISH_TAG_FILL_ENABLED !== '0';
const PUBLISH_TAG_FILL_TARGET  = parseInt(process.env.PUBLISH_TAG_FILL_TARGET || '5', 10);
const PUBLISH_TAG_FILL_MAXLEN  = parseInt(process.env.PUBLISH_TAG_FILL_MAXLEN || '30', 10);
```

- [ ] **Step 2: Проверить, что сервер парсится без ошибок**

Run: `cd /home/claude-user/autowarm-testbench && node --check server.js && echo OK`
Expected: `OK` (синтаксис валиден, require резолвится).

- [ ] **Step 3: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add server.js
git commit -m "feat(wp44): подключить hashtag_enrich + env-флаги в server.js"
```

---

### Task 4: Врезка в `assignUnicResultsToQueue` (авто-очередь)

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/server.js:6413` (добавить fetch keywords)
- Modify: `/home/claude-user/autowarm-testbench/server.js:6446-6460` (использовать обогащённые теги)

- [ ] **Step 1: Достать keywords распаковки один раз на результат**

Найти блок (около 6410-6413):

```js
        const contentTitle       = (res.content_title || '').slice(0, 100);
        const contentDescription = res.content_description || '';
        const contentHashtags    = Array.isArray(res.content_hashtags) ? res.content_hashtags : [];
        const contentGeo         = res.content_geo || '';
```

Добавить сразу ПОСЛЕ него:

```js
        // WP#44: keywords распаковки для добивки тегов (один запрос на результат)
        const brandKeywords = await getBrandKeywords(pool, res.project_id);
```

- [ ] **Step 2: Использовать обогащённые теги в сборке caption/hashtags**

Найти блок внутри `for (const acc of accounts)` (около 6446-6460):

```js
          if (platformLower === 'youtube') {
            // YouTube Shorts:
            // - caption = title (≤100 символов) — используется как заголовок видео
            // - hashtags передаются в publish_queue для использования publisher.py в описании
            // - content_description = описание контента (если есть) — publisher вставит в поле "Описание"
            caption   = contentTitle;
            hashtags  = contentHashtags;
            geo       = '';
          } else {
            // Instagram / TikTok: description + hashtags в одном поле caption
            const hashtagStr = contentHashtags.map(t => `#${t.replace(/^#/, '')}`).join(' ');
            caption   = [contentDescription, hashtagStr].filter(Boolean).join('\n\n').trim();
            hashtags  = contentHashtags;
            geo       = contentGeo;
          }
```

Заменить целиком на:

```js
          // WP#44: обогащаем теги (клиентские + рандомная добивка из распаковки до 5).
          // Считаем на каждый аккаунт → набор отличается у разных публикаций/дней.
          const finalHashtags = enrichHashtags(contentHashtags, brandKeywords, {
            enabled: PUBLISH_TAG_FILL_ENABLED,
            target: PUBLISH_TAG_FILL_TARGET,
            maxLen: PUBLISH_TAG_FILL_MAXLEN,
          });

          if (platformLower === 'youtube') {
            // YouTube Shorts:
            // - caption = title (≤100 символов) — используется как заголовок видео
            // - hashtags передаются в publish_queue для использования publisher.py в описании
            // - content_description = описание контента (если есть) — publisher вставит в поле "Описание"
            caption   = contentTitle;
            hashtags  = finalHashtags;
            geo       = '';
          } else {
            // Instagram / TikTok: description + hashtags в одном поле caption
            const hashtagStr = finalHashtags.map(t => `#${t.replace(/^#/, '')}`).join(' ');
            caption   = [contentDescription, hashtagStr].filter(Boolean).join('\n\n').trim();
            hashtags  = finalHashtags;
            geo       = contentGeo;
          }
```

- [ ] **Step 3: Проверить синтаксис**

Run: `cd /home/claude-user/autowarm-testbench && node --check server.js && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add server.js
git commit -m "feat(wp44): добивка тегов в авто-очереди (assignUnicResultsToQueue)"
```

---

### Task 5: Врезка в ручной endpoint постановки в очередь

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/server.js:2373` (добавить вычисление обогащённых тегов)
- Modify: `/home/claude-user/autowarm-testbench/server.js:2375-2394` (заменить `contentHashtags` → `finalHashtagsManual`)

- [ ] **Step 1: Вычислить обогащённые теги перед сборкой**

Найти строку 2373:

```js
    let resolvedGeo = geo || '';
```

Добавить сразу ПОСЛЕ неё:

```js
    // WP#44: финальные теги (клиентские + рандомная добивка из распаковки до 5)
    const brandKeywordsManual = unic_result_id ? await getBrandKeywords(pool, resolvedProjectId) : [];
    const finalHashtagsManual = enrichHashtags(contentHashtags, brandKeywordsManual, {
      enabled: PUBLISH_TAG_FILL_ENABLED,
      target: PUBLISH_TAG_FILL_TARGET,
      maxLen: PUBLISH_TAG_FILL_MAXLEN,
    });
```

- [ ] **Step 2: Заменить `contentHashtags` на `finalHashtagsManual` в блоке сборки**

Найти блок (около 2375-2394):

```js
    if (unic_result_id && !caption) {
      // Пользователь не передал caption вручную — формируем из контента
      if (platformLowerManual === 'youtube') {
        resolvedCaption = contentTitle;  // title → заголовок YouTube
        resolvedContentDescription = contentDescription;  // description → поле "Описание"
        resolvedHashtags = contentHashtags;
      } else {
        // Instagram / TikTok: description + hashtags в одном поле caption
        const hashtagStr = contentHashtags.map(t => `#${t.replace(/^#/, '')}`).join(' ');
        resolvedCaption = [contentDescription, hashtagStr].filter(Boolean).join('\n\n').trim();
        resolvedHashtags = contentHashtags;
        resolvedGeo = contentGeo || geo || '';
      }
    } else if (unic_result_id && caption) {
      // Пользователь передал caption вручную, но content_description всё равно нужен для YouTube
      if (platformLowerManual === 'youtube') {
        resolvedContentDescription = contentDescription;
        resolvedHashtags = contentHashtags;
      }
    }
```

Заменить целиком на (4 замены `contentHashtags` → `finalHashtagsManual`):

```js
    if (unic_result_id && !caption) {
      // Пользователь не передал caption вручную — формируем из контента
      if (platformLowerManual === 'youtube') {
        resolvedCaption = contentTitle;  // title → заголовок YouTube
        resolvedContentDescription = contentDescription;  // description → поле "Описание"
        resolvedHashtags = finalHashtagsManual;
      } else {
        // Instagram / TikTok: description + hashtags в одном поле caption
        const hashtagStr = finalHashtagsManual.map(t => `#${t.replace(/^#/, '')}`).join(' ');
        resolvedCaption = [contentDescription, hashtagStr].filter(Boolean).join('\n\n').trim();
        resolvedHashtags = finalHashtagsManual;
        resolvedGeo = contentGeo || geo || '';
      }
    } else if (unic_result_id && caption) {
      // Пользователь передал caption вручную, но content_description всё равно нужен для YouTube
      if (platformLowerManual === 'youtube') {
        resolvedContentDescription = contentDescription;
        resolvedHashtags = finalHashtagsManual;
      }
    }
```

- [ ] **Step 3: Проверить синтаксис**

Run: `cd /home/claude-user/autowarm-testbench && node --check server.js && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
cd /home/claude-user/autowarm-testbench
git add server.js
git commit -m "feat(wp44): добивка тегов в ручной постановке в очередь"
```

---

### Task 6: Регресс-прогон тестов + проверка отсутствия пропущенных producer'ов

**Files:** нет правок кода — верификация.

- [ ] **Step 1: Прогнать тесты модуля**

Run: `cd /home/claude-user/autowarm-testbench && node --test hashtag_enrich.test.js`
Expected: PASS — 15/15.

- [ ] **Step 2: Подтвердить, что все producer'ы publish_queue учтены**

Run:
```bash
cd /home/claude-user/autowarm-testbench
grep -n "INSERT INTO publish_queue" server.js
grep -rln "INSERT INTO publish_queue" *.js | grep -v test
```
Expected: ровно 4 `INSERT` в `server.js` (строки в районе ~2397 и ~6463 — обогащены через `finalHashtags*`; ~6172 и ~6259 — audit-строки `past_slot_dropped` без caption, обогащение не нужно). Других файлов-producer'ов нет.

- [ ] **Step 3: Грубый smoke `enrichHashtags` на реальных данных (без записи в БД)**

Run (вставит реальные keywords проекта 107 и покажет результат добивки для контента с <5 тегами):
```bash
cd /home/claude-user/autowarm-testbench
node -e '
const { Pool } = require("pg");
const { enrichHashtags, getBrandKeywords } = require("./hashtag_enrich");
const pool = new Pool({ connectionString: "postgresql://openclaw:openclaw123@localhost:5432/openclaw" });
(async () => {
  const kw = await getBrandKeywords(pool, 107);
  console.log("keywords распаковки (проект 107):", kw.length, "шт");
  console.log("добивка к [покер, еноты]:", enrichHashtags(["покер", "еноты"], kw));
  console.log("добивка к 5 тегам (без изменений):", enrichHashtags(["a","b","c","d","e"], kw));
  await pool.end();
})();
'
```
Expected: для проекта 107 keywords найдены; первый вызов вернул 5 тегов (2 клиентских + 3 рандомных из распаковки, без пробелов/в нижнем регистре); второй — ровно исходные 5.

- [ ] **Step 4: Финальный commit (если нужны мелкие правки) — иначе пропустить**

Если правок не было — переходить к хендоффу.

---

## Self-Review (проверка плана против spec)

- **Пункт 1 (теги в описание):** обогащённый массив используется при сборке caption для IG/TT и как `hashtags` для YT (Task 4, 5). ✅
- **Пункт 2 (добивка <5 из распаковки, рандом):** `enrichHashtags` (Task 1) + `getBrandKeywords` (Task 2), рандом на публикацию (per-acc, Task 4). ✅
- **Пункт 3 (ugly «Теги:»):** снят по решению заказчика — задач нет. ✅
- **Все платформы:** IG/TT (caption) и YT (поле описания через публикатор) покрыты. ✅
- **Нормализация (склейка/lowercase/без пунктуации/>30 отбросить):** Task 1, Step 3 + тесты. ✅
- **Kill-switch + конфиг (`PUBLISH_TAG_FILL_ENABLED/_TARGET/_MAXLEN`):** Task 3 + тест enabled=false. ✅
- **Аудит producer'ов:** зафиксирован в шапке + Task 6 Step 2. ✅
- **Placeholder-скан:** заглушек нет — весь код приведён. ✅
- **Согласованность имён:** `enrichHashtags`, `getBrandKeywords`, `finalHashtags` (assign), `finalHashtagsManual` (manual), `brandKeywords`/`brandKeywordsManual` — консистентны между задачами. ✅

## Деплой (после ревью и мерджа — отдельно, НЕ часть TDD-цикла)

Prod-autowarm: `/root/.openclaw/workspace-genri/autowarm` (auto-push git-hook на `GenGo2/delivery-contenthunter`). При деплое:
- Никакого force-push в чужую ветку/main.
- Новый файл `hashtag_enrich.js` должен попасть в prod-checkout (не только server.js).
- Проверить `pm2 describe <app> | grep "exec cwd"` — что PM2 читает нужный путь, не stale dev.
- Включено по умолчанию; быстрый откат — `PUBLISH_TAG_FILL_ENABLED=0` без релиза кода.
