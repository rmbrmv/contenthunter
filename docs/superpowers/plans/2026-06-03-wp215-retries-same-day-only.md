# WP#215 — Ретраи «день в день» + UI-настройки (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Авто-ретраи упавших публикаций — только в течение текущих суток; после настраиваемого часа отсечки (дефолт 14:00 МСК) и при исчерпании дневного капа всё ещё-упавшее уходит операторам в ручную выкладку. Час отсечки и глубину окна выносим в UI «Глобальные настройки».

**Architecture:** Хирургические правки в чистой функции `decideRetry` (две ветки `wait → handoff` под флагом `sameDayHandoff`) + контроллер читает две UI-настройки (`retry_cutoff_hour_msk`, `retry_extra_days`) из таблицы `autowarm_settings` каждый тик с фолбэком на env/дефолт. UI получает два поля в `section-global-settings`. Хендофф переиспользует существующий `handoffToManual`. Поведение под kill-switch `RETRY_SAME_DAY_ONLY_ENABLED` (дефолт ON).

**Tech Stack:** Node.js + node:test, PostgreSQL (`pg`), статический `public/index.html` (vanilla JS), all in repo `delivery-contenthunter` (рабочая копия `/home/claude-user/autowarm-testbench`).

**Спека:** `docs/superpowers/specs/2026-06-03-wp215-retries-same-day-only-design.md` (репо `contenthunter`).

---

## Рабочая копия и изоляция

Весь код — в репозитории **`delivery-contenthunter`**. Локальный чекаут:
`/home/claude-user/autowarm-testbench` (remote `origin` = `delivery-contenthunter`).

⚠️ Этот чекаут **общий с параллельными сессиями** (сейчас на чужой ветке
`wp216-inactive-project-gate`). Перед реализацией создать изолированную ветку от
`origin/main`:

```bash
cd /home/claude-user
git -C autowarm-testbench fetch origin
git -C autowarm-testbench worktree add --detach /home/claude-user/wp215-autowarm origin/main
cd /home/claude-user/wp215-autowarm
git switch -c wp215-retries-same-day-only
```

Все пути в задачах ниже — **относительно корня этой рабочей копии**
(`/home/claude-user/wp215-autowarm`).

Локальная тест-БД (как в существующих тестах): Postgres `localhost`,
user/password `openclaw`/`openclaw123`, db `openclaw`. Тесты `test_retry_*`
гоняются `node --test`.

---

## Структура файлов

| Файл | Ответственность | Действие |
|---|---|---|
| `retry_decision.js` | чистое решение по упавшей строке | Modify: 2 ветки + новый факт `sameDayHandoff` |
| `test_retry_decision.test.js` | юнит-тесты решения | Modify: новые кейсы + `sameDayHandoff` в `base` |
| `retry_labels.js` | тексты событий retry/handoff | Modify: 2 новых reason + нейтрализовать `window_exhausted` |
| `test_retry_labels.test.js` | юнит-тесты текстов | Modify: обновить тест `window_exhausted`, добавить 2 |
| `retry_controller.js` | оркестрация тика, чтение настроек | Modify: чтение `autowarm_settings`, маппинг окна, проброс флага |
| `test_retry_controller.test.js` | live-DB интеграция | Modify: тесты cutoff/extra_days из БД |
| `server.js` | seed дефолтов настроек | Modify: 2 ключа в `INSERT ... ON CONFLICT DO NOTHING` (≈ строка 372) |
| `public/index.html` | UI глобальных настроек | Modify: 2 поля + `loadGlobalSettings`/`saveGlobalSettings` |

Порядок реализации: чистое ядро (Task 1) → тексты (Task 2) → контроллер (Task 3)
→ seed (Task 4) → UI (Task 5). Каждая задача самодостаточна и коммитится.

---

## Task 1: `decideRetry` — ветки `wait → handoff` под `sameDayHandoff`

**Files:**
- Modify: `retry_decision.js` (ветка после отсечки; ветка дневного капа)
- Test: `test_retry_decision.test.js`

- [ ] **Step 1: Обновить `base`, починить конфликтующие старые кейсы, написать падающие тесты**

В `test_retry_decision.test.js` добавить `sameDayHandoff: true` в объект `base`:

```js
const base = { maxPerClassPerDay: 3, windowDays: 2, beforeCutoff: true,
               fixedAtAfterLastFail: false, daysSinceFirstAttempt: 0,
               sameDayHandoff: true };
```

`base.sameDayHandoff=true` ломает два существующих кейса (они ждут `wait` после
отсечки и при исчерпании капа). Найти и заменить их так, чтобы они явно
проверяли откат `sameDayHandoff:false`:

- кейс `network, после отсечки 23:00 → wait (ни requeue, ни handoff)` →

```js
test('network, после отсечки, sameDayHandoff=false → wait', () => {
  assert.equal(decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:0,
                             beforeCutoff:false, sameDayHandoff:false }).action, 'wait');
});
```

- кейс `network, дневной лимит = 3 → wait (...)` →

```js
test('network, дневной лимит = 3, sameDayHandoff=false → wait', () => {
  assert.equal(decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:3,
                             sameDayHandoff:false }).action, 'wait');
});
```

Добавить новые кейсы в конец файла:

```js
test('WP#215: кап исчерпан, sameDayHandoff=true → handoff (daily_cap_exhausted)', () => {
  const d = decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:3 });
  assert.equal(d.action, 'handoff');
  assert.equal(d.reason, 'daily_cap_exhausted');
});
test('WP#215: кап исчерпан, sameDayHandoff=false → wait (старое)', () => {
  const d = decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:3, sameDayHandoff:false });
  assert.equal(d.action, 'wait');
});
test('WP#215: после отсечки, sameDayHandoff=true → handoff (after_cutoff_manual)', () => {
  const d = decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:0, beforeCutoff:false });
  assert.equal(d.action, 'handoff');
  assert.equal(d.reason, 'after_cutoff_manual');
});
test('WP#215: после отсечки, sameDayHandoff=false → wait (старое)', () => {
  const d = decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:0, beforeCutoff:false, sameDayHandoff:false });
  assert.equal(d.action, 'wait');
});
test('WP#215: device_unreachable после отсечки → handoff (ветка отсечки перехватывает)', () => {
  const d = decideRetry({ ...base, errorClass:'device_unreachable', attemptsTodayThisClass:9,
                          beforeCutoff:false, deviceHealthThrottle:true, maxDeviceHealthPerDay:2 });
  assert.equal(d.action, 'handoff');
  assert.equal(d.reason, 'after_cutoff_manual');
});
test('WP#215: device_unreachable до отсечки сверх капа → wait (WP#210 цел)', () => {
  const d = decideRetry({ ...base, errorClass:'device_unreachable', attemptsTodayThisClass:2,
                          beforeCutoff:true, deviceHealthThrottle:true, maxDeviceHealthPerDay:2 });
  assert.equal(d.action, 'wait');
  assert.equal(d.reason, 'device_health_wait_tomorrow');
});
test('WP#215: fixed_at после отсечки → handoff (отсечка выше реанимации)', () => {
  const d = decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:0,
                          beforeCutoff:false, fixedAtAfterLastFail:true });
  assert.equal(d.action, 'handoff');
  assert.equal(d.reason, 'after_cutoff_manual');
});
test('WP#215: окно 1 день (windowDays=1), days=1 → handoff', () => {
  const d = decideRetry({ ...base, errorClass:'network', attemptsTodayThisClass:0,
                          windowDays:1, daysSinceFirstAttempt:1 });
  assert.equal(d.action, 'handoff');
  assert.equal(d.reason, 'window_exhausted');
});
```

- [ ] **Step 2: Запустить тесты — убедиться, что новые падают**

Run: `node --test test_retry_decision.test.js`
Expected: FAIL — `daily_cap_exhausted`/`after_cutoff_manual` кейсы возвращают `wait` (старое поведение), а тест ждёт `handoff`.

- [ ] **Step 3: Изменить две ветки в `decideRetry`**

В `retry_decision.js`. Заменить ветку после отсечки:

```js
  // 2) Вне активного окна дня (после часа отсечки МСК) — WP#215: в ручную операторам
  //    (sameDayHandoff). При выключенном флаге — старое поведение (ничего не делаем).
  if (!f.beforeCutoff)
    return f.sameDayHandoff
      ? { action: 'handoff', reason: 'after_cutoff_manual' }
      : { action: 'wait', reason: 'after_cutoff' };
```

Заменить ветку дневного капа:

```js
  // 6) Дневной лимит по классу исчерпан — WP#215: same-day ретраи кончились → в ручную
  //    (sameDayHandoff). При выключенном флаге — старое «ждём завтра».
  if (f.attemptsTodayThisClass >= f.maxPerClassPerDay)
    return f.sameDayHandoff
      ? { action: 'handoff', reason: 'daily_cap_exhausted' }
      : { action: 'wait', reason: 'daily_limit_wait_tomorrow' };
```

(Остальные ветки и `module.exports` — без изменений.)

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `node --test test_retry_decision.test.js`
Expected: PASS — все кейсы зелёные (новые WP#215 + починенные откат-кейсы + остальные существующие).

- [ ] **Step 5: Commit**

```bash
git add retry_decision.js test_retry_decision.test.js
git commit -m "feat(wp215): decideRetry — wait→handoff после отсечки и при исчерпании капа (sameDayHandoff)"
```

---

## Task 2: `retry_labels.js` — тексты новых reason'ов

**Files:**
- Modify: `retry_labels.js` (`HANDOFF_MSG_BY_RULE`)
- Test: `test_retry_labels.test.js`

- [ ] **Step 1: Обновить падающий тест + добавить новые**

В `test_retry_labels.test.js` заменить тест `handoffMessage: window_exhausted → про 2 дня` (он зашит на `/2 дня/`, а текст становится нейтральным):

```js
test('handoffMessage: window_exhausted → нейтрально про ручную', () => {
  assert.match(handoffMessage('window_exhausted', 'network'), /ручную/);
  assert.doesNotMatch(handoffMessage('window_exhausted', 'network'), /2 дня/);
});
test('handoffMessage: after_cutoff_manual → про время ретраев и ручную', () => {
  assert.match(handoffMessage('after_cutoff_manual', 'network'), /ручную/);
});
test('handoffMessage: daily_cap_exhausted → про лимит и ручную', () => {
  assert.match(handoffMessage('daily_cap_exhausted', 'network'), /лимит/);
  assert.match(handoffMessage('daily_cap_exhausted', 'network'), /ручную/);
});
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `node --test test_retry_labels.test.js`
Expected: FAIL — `after_cutoff_manual`/`daily_cap_exhausted` дают дефолтный текст (нет `/лимит/`), а `window_exhausted` всё ещё содержит «2 дня».

- [ ] **Step 3: Обновить `HANDOFF_MSG_BY_RULE`**

В `retry_labels.js` заменить объект `HANDOFF_MSG_BY_RULE`:

```js
const HANDOFF_MSG_BY_RULE = {
  // WP#215: текст нейтрален к числу дней (окно настраивается из UI).
  window_exhausted: 'Автоматически опубликовать не удалось — задача передана на ручную выкладку.',
  // WP#215: после часа отсечки авто-ретраи на сегодня завершены.
  after_cutoff_manual: 'Время авто-ретраев на сегодня истекло — задача передана на ручную выкладку операторам.',
  // WP#215: исчерпан дневной кап авто-перезапусков по классу ошибки.
  daily_cap_exhausted: 'Исчерпан дневной лимит авто-перезапусков — задача передана на ручную выкладку.',
};
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `node --test test_retry_labels.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add retry_labels.js test_retry_labels.test.js
git commit -m "feat(wp215): тексты событий after_cutoff_manual/daily_cap_exhausted + нейтральный window_exhausted"
```

---

## Task 3: `retry_controller.js` — чтение UI-настроек из БД + проброс флага

**Files:**
- Modify: `retry_controller.js` (блок констант в начале `retryFailedPublishes`; объект фактов в вызове `decideRetry`)
- Test: `test_retry_controller.test.js`

- [ ] **Step 1: Написать падающие интеграционные тесты**

В `test_retry_controller.test.js` добавить два хелпера (после `seedFailed`):

```js
async function setSetting(k,v){
  await pool.query(`INSERT INTO autowarm_settings (key,value) VALUES ($1,$2)
                    ON CONFLICT (key) DO UPDATE SET value=$2`,[k,v]);
}
async function clearRetrySettings(){
  await pool.query(`DELETE FROM autowarm_settings WHERE key IN ('retry_cutoff_hour_msk','retry_extra_days')`).catch(()=>{});
}
```

Добавить тесты в конец файла:

```js
test('WP#215: час отсечки из БД (cutoff=10, now=12:00) → handoff after_cutoff_manual', async()=>{
  const NOW = new Date('2026-06-15T12:00:00+03:00');
  await seedFailed('some_net','network');
  // первая попытка = сегодня (относительно NOW), чтобы окно/кап не сработали сами
  await pool.query(`UPDATE publish_tasks SET created_at=$2 WHERE id=$1`,[PT, '2026-06-15T09:00:00+03:00']);
  await setSetting('retry_cutoff_hour_msk','10');
  await setSetting('retry_extra_days','5');         // широкое окно, чтобы не мешало
  await retryFailedPublishes(pool, { nowMsk: NOW, onlyClientPublishId: CPID });
  const q = (await pool.query('SELECT status, skip_reason FROM publish_queue WHERE id=$1',[PQ])).rows[0];
  assert.ok(['cancelled','skipped'].includes(q.status), 'строка погашена');
  assert.equal(q.skip_reason, 'retry_handoff:after_cutoff_manual');
  await clearRetrySettings();
});

test('WP#215: extra_days=0 (окно 1 день), задача со вчера → handoff window_exhausted', async()=>{
  const NOW = new Date('2026-06-15T08:00:00+03:00');     // до отсечки
  await seedFailed('some_net','network');
  await pool.query(`UPDATE publish_tasks SET created_at=$2 WHERE id=$1`,[PT, '2026-06-14T20:00:00+03:00']); // вчера
  await setSetting('retry_cutoff_hour_msk','14');
  await setSetting('retry_extra_days','0');               // windowDays=1
  await retryFailedPublishes(pool, { nowMsk: NOW, onlyClientPublishId: CPID });
  const q = (await pool.query('SELECT status, skip_reason FROM publish_queue WHERE id=$1',[PQ])).rows[0];
  assert.ok(['cancelled','skipped'].includes(q.status), 'строка погашена');
  assert.equal(q.skip_reason, 'retry_handoff:window_exhausted');
  await clearRetrySettings();
});

test('WP#215: extra_days=1 (окно 2 дня), задача со вчера, до отсечки → requeue (pending)', async()=>{
  const NOW = new Date('2026-06-15T08:00:00+03:00');
  await seedFailed('some_net','network');
  await pool.query(`UPDATE publish_tasks SET created_at=$2 WHERE id=$1`,[PT, '2026-06-14T20:00:00+03:00']); // вчера, days=1
  await setSetting('retry_cutoff_hour_msk','14');
  await setSetting('retry_extra_days','1');               // windowDays=2 → days=1 < 2 → ретраим
  await retryFailedPublishes(pool, { nowMsk: NOW, onlyClientPublishId: CPID });
  const q = (await pool.query('SELECT status FROM publish_queue WHERE id=$1',[PQ])).rows[0];
  assert.equal(q.status, 'pending');
  await clearRetrySettings();
});
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: FAIL — контроллер ещё читает `RETRY_WINDOW_DAYS`/`RETRY_CUTOFF_HOUR_MSK` из env с дефолтами 2/23 и не знает про `sameDayHandoff` → cutoff из БД не применяется, skip_reason не совпадёт.

- [ ] **Step 3: Заменить блок констант в `retryFailedPublishes`**

В `retry_controller.js` заменить четыре строки:

```js
  const maxPerClassPerDay = num(process.env.RETRY_MAX_PER_CLASS_PER_DAY, 3);
  const windowDays        = num(process.env.RETRY_WINDOW_DAYS, 2);
  const cutoffHourMsk     = num(process.env.RETRY_CUTOFF_HOUR_MSK, 23);
  const handoffEnabled    = process.env.RETRY_MANUAL_HANDOFF_ENABLED !== 'false';
```

на:

```js
  const maxPerClassPerDay = num(process.env.RETRY_MAX_PER_CLASS_PER_DAY, 3);
  const handoffEnabled    = process.env.RETRY_MANUAL_HANDOFF_ENABLED !== 'false';
  // WP#215: same-day хендофф под kill-switch (дефолт ON). =false → старое «ждём завтра».
  const sameDayHandoff    = process.env.RETRY_SAME_DAY_ONLY_ENABLED !== 'false';

  // WP#215: час отсечки и глубина окна — UI-настройки (autowarm_settings), читаются
  // каждый тик. Приоритет: БД → env → дефолт. Невалидное значение → фолбэк.
  const cfg = {};
  for (const row of (await pool.query(
    `SELECT key, value FROM autowarm_settings
     WHERE key IN ('retry_cutoff_hour_msk','retry_extra_days')`)).rows) cfg[row.key] = row.value;
  const hDb = parseInt(cfg.retry_cutoff_hour_msk, 10);
  const cutoffHourMsk = (Number.isInteger(hDb) && hDb >= 0 && hDb <= 23)
    ? hDb : num(process.env.RETRY_CUTOFF_HOUR_MSK, 14);
  const dDb = parseInt(cfg.retry_extra_days, 10);
  const extraDays  = (Number.isInteger(dDb) && dDb >= 0) ? dDb : num(process.env.RETRY_EXTRA_DAYS, 0);
  const windowDays = extraDays + 1;   // 0 доп. дней = только текущие сутки
```

- [ ] **Step 4: Пробросить `sameDayHandoff` в `decideRetry`**

В том же файле, в объекте фактов вызова `decideRetry`, заменить строку:

```js
      beforeCutoff, maxPerClassPerDay, windowDays,
```

на:

```js
      beforeCutoff, maxPerClassPerDay, windowDays, sameDayHandoff,
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `node --test --test-force-exit test_retry_controller.test.js`
Expected: PASS (новые WP#215-кейсы + существующие; старые кейсы используют `nowMsk` 2026-05-21 с дефолтами настроек из фолбэка 14/0 и не регрессируют).

- [ ] **Step 6: Commit**

```bash
git add retry_controller.js test_retry_controller.test.js
git commit -m "feat(wp215): контроллер читает retry_cutoff_hour_msk/retry_extra_days из autowarm_settings + проброс sameDayHandoff"
```

---

## Task 4: `server.js` — seed дефолтов настроек

**Files:**
- Modify: `server.js` (блок `INSERT INTO autowarm_settings ... ON CONFLICT DO NOTHING`, ≈ строка 372)

- [ ] **Step 1: Добавить два ключа в seed**

В `server.js` найти блок:

```js
      INSERT INTO autowarm_settings (key, value) VALUES
      ('detection_model', 'claude-3-haiku-20240307'),
      ('comment_model', 'claude-3-5-sonnet-20241022'),
      ('keyword_threshold', '70'),
      ('skip_like_probability', '20'),
      ('auto_sync_device_mapping', 'false')
      ON CONFLICT (key) DO NOTHING
```

Заменить на (добавлены две строки + запятая после `auto_sync_device_mapping`):

```js
      INSERT INTO autowarm_settings (key, value) VALUES
      ('detection_model', 'claude-3-haiku-20240307'),
      ('comment_model', 'claude-3-5-sonnet-20241022'),
      ('keyword_threshold', '70'),
      ('skip_like_probability', '20'),
      ('auto_sync_device_mapping', 'false'),
      ('retry_cutoff_hour_msk', '14'),
      ('retry_extra_days', '0')
      ON CONFLICT (key) DO NOTHING
```

- [ ] **Step 2: Проверить синтаксис**

Run: `node -e "require('./server.js')" 2>&1 | head -5 || true`
Expected: процесс может попытаться слушать порт/коннектиться к БД — нас интересует **отсутствие SyntaxError**. Если видно `SyntaxError` — исправить запятые. Иначе (любой рантайм-вывод/ошибка соединения) — синтаксис ок. Прервать `Ctrl-C`/таймаут.

Альтернатива без запуска побочных эффектов:
Run: `node --check server.js`
Expected: без вывода (синтаксис валиден).

- [ ] **Step 3: Commit**

```bash
git add server.js
git commit -m "feat(wp215): seed retry_cutoff_hour_msk=14 и retry_extra_days=0 в autowarm_settings"
```

---

## Task 5: `public/index.html` — два поля в «Глобальные настройки»

**Files:**
- Modify: `public/index.html` (`section-global-settings` разметка; `loadGlobalSettings`; `saveGlobalSettings`)

- [ ] **Step 1: Добавить разметку двух полей**

В `public/index.html`, в `section-global-settings`, перед кнопкой
`<button onclick="saveGlobalSettings()" ...>` вставить:

```html
    <!-- WP#215: час отсечки авто-ретраев -->
    <div>
      <label class="block text-xs font-semibold text-gray-500 mb-1">🕑 Час прекращения авто-ретраев (МСК)</label>
      <input id="global-setting-retry-cutoff-hour" type="number" min="0" max="23"
             class="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400">
      <p class="text-xs text-gray-400 mt-1">После этого часа упавшие публикации передаются операторам в ручную выкладку. По умолчанию 14.</p>
    </div>

    <!-- WP#215: глубина окна ретраев в днях -->
    <div>
      <label class="block text-xs font-semibold text-gray-500 mb-1">🔁 Кол-во дней ретраев</label>
      <input id="global-setting-retry-extra-days" type="number" min="0"
             class="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400">
      <p class="text-xs text-gray-400 mt-1">Сколько дополнительных суток ретраить после дня первой попытки. 0 = только текущие сутки (день в день).</p>
    </div>
```

- [ ] **Step 2: Заполнять поля в `loadGlobalSettings`**

Найти функцию `loadGlobalSettings` и заменить её тело на:

```js
async function loadGlobalSettings() {
  try {
    const res = await fetch('/api/settings');
    const s = await res.json();
    const tz = s.farm_timezone || 'Asia/Dubai';
    const sel = document.getElementById('global-setting-timezone');
    if (sel) sel.value = tz;
    // WP#215
    const cutoff = document.getElementById('global-setting-retry-cutoff-hour');
    if (cutoff) cutoff.value = s.retry_cutoff_hour_msk ?? '14';
    const days = document.getElementById('global-setting-retry-extra-days');
    if (days) days.value = s.retry_extra_days ?? '0';
  } catch(e) { console.warn('loadGlobalSettings error', e); }
}
```

- [ ] **Step 3: Сохранять поля в `saveGlobalSettings` с валидацией**

Найти функцию `saveGlobalSettings` и заменить её тело на:

```js
async function saveGlobalSettings() {
  const tz = document.getElementById('global-setting-timezone').value;
  // WP#215: валидация час 0..23, дни >=0
  const cutoff = parseInt(document.getElementById('global-setting-retry-cutoff-hour').value, 10);
  const days   = parseInt(document.getElementById('global-setting-retry-extra-days').value, 10);
  if (!Number.isInteger(cutoff) || cutoff < 0 || cutoff > 23) { toast('Час отсечки: целое 0..23', 'error'); return; }
  if (!Number.isInteger(days) || days < 0) { toast('Кол-во дней: целое ≥ 0', 'error'); return; }
  const res = await fetch('/api/settings', {
    method: 'PUT',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      farm_timezone: tz,
      retry_cutoff_hour_msk: String(cutoff),
      retry_extra_days: String(days),
    })
  });
  if (res.ok) {
    _farmTimezone = tz; // обновляем кэш
    toast('Настройки сохранены ✓');
  } else {
    toast('Ошибка сохранения', 'error');
  }
}
```

- [ ] **Step 4: Ручная проверка в браузере**

Run: открыть `https://delivery.contenthunter.ru/#global-settings/global-settings` (после деплоя) или локально поднятый `server.js`.
Expected:
- поля «Час прекращения авто-ретраев» = `14`, «Кол-во дней ретраев» = `0` при первой загрузке;
- сохранение с часом `25` или днями `-1` → тост-ошибка, PUT не уходит;
- сохранение валидных значений → тост «Настройки сохранены», перезагрузка страницы показывает сохранённое.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(wp215): UI «Глобальные настройки» — час отсечки и кол-во дней ретраев"
```

---

## Финальная проверка (после всех задач)

- [ ] **Регрессия всего набора ретраев и ручной очереди**

Run: `node --test --test-force-exit test_retry_decision.test.js test_retry_labels.test.js test_retry_controller.test.js test_manual_publish_queue.test.js test_manual_queue_assign_live.test.js`
Expected: все PASS, 0 падений.

- [ ] **Сводка изменений**

Run: `git log --oneline origin/main..HEAD`
Expected: 5 коммитов (Task 1–5).

---

## Деплой (выполняется отдельно, не в рамках кодинга)

1. Смержить ветку в `main` репо `delivery-contenthunter` (PR).
2. Прод: `git pull` в `/root/.openclaw/workspace-genri/autowarm`, затем
   `sudo pm2 restart` id35 (контроллер и статический фронт — в долгоиграющем `server.js`).
3. Проверить, что seed создал ключи (или операторы выставили их в UI). Дефолты
   14 / 0 работают через фолбэк даже без строк в БД.
4. Verify: после деплоя по событиям в «Лог событий» — появление `handoff` с
   правилами `after_cutoff_manual` / `daily_cap_exhausted` после часа отсечки.

**Откат:** `RETRY_SAME_DAY_ONLY_ENABLED=false` (env) — мгновенно, без передеплоя.
Час/дни также правятся в UI без передеплоя.
