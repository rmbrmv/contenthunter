# WP #173 — Воронка пайплайна: сведение подачи — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать видимую воронку дашборда/TG сводимой (Авто + вся Ручная + Потеряно = План) и развести две метрики SR, не меняя расчётных формул #153 — чтобы закрыть 6 пунктов приёмки Анастасии (#173).

**Architecture:** Все правки — слой подачи. Единый модуль `pipeline_funnel.js` остаётся источником правды; добавляем наружу ровно одно производное поле (`proactive_manual_notdispatched`), остальное поверхности выводят из уже отдаваемых полей. Дашборд: вариант A (бокс «Ручная выложено» = вся ручная с разбивкой) + строка-сверка + обогащённые слепые-зоны + новая сноска + тултипы SR. TG: разбивка ручной + строка SR итоговый + штамп снимка. Миграций БД нет, нового kill-switch нет (живём под `PIPELINE_FUNNEL_ENABLED`).

**Tech Stack:** Node.js (`node:test` + `assert/strict`), Express (`server.js`), ванильный JS во `public/index.html`. Репо кода — `GenGo2/delivery-contenthunter` (локальный чекаут `~/autowarm-testbench`, git-worktrees).

**Spec:** `docs/superpowers/specs/2026-05-27-wp173-funnel-reconciliation-presentation-design.md`

---

## Файлы (что трогаем)

| Файл (в autowarm-testbench) | Ответственность | Изменение |
|---|---|---|
| `pipeline_funnel.js` | расчёт воронки (источник правды) | +1 поле в `assembleFunnel` (`proactive_manual_notdispatched`) |
| `tests/test_pipeline_funnel_pure.test.js` | юнит модуля | +фикстура 26.05, +инвариант, +новое поле |
| `daily_publish_report.js` | TG-отчёт (`formatMessage`) | разбивка ручной + строка SR итоговый + штамп снимка |
| `tests/test_daily_publish_report.test.js` | юнит TG | +тест блока воронки |
| `public/index.html` | дашборд (`renderDashboardFunnel`, `renderDashboardOverall`) | вариант A + сверка + зоны + сноска + тултипы |

Реальные числа эталона 26.05 (из скриншота, проверены в спеке): `plan 307 · uniq 307 · autotask 277 · auto 228 · handoff 29 · handoff_published 25 · manual_total 64 · proactive_published 39 · proactive_notdispatched 10 · lost 15`.

---

## Task 0: Preflight — worktree автоварма, базовый зелёный прогон

**Files:**
- Создать worktree: `~/autowarm-testbench-wp173-funnel-presentation`

- [ ] **Step 1: Создать изолированный worktree автоварма** (autowarm — общий чекаут, как и contenthunter; работаем в отдельной ветке)

```bash
cd ~/autowarm-testbench
git worktree add ../autowarm-testbench-wp173-funnel-presentation -b feat/wp173-funnel-presentation
cd ../autowarm-testbench-wp173-funnel-presentation
git branch --show-current   # ожидаем feat/wp173-funnel-presentation
```

- [ ] **Step 2: ⚠️ Проверить post-commit auto-push hook** (у автоварма есть хук, пушащий в прод — нельзя случайно задеплоить недотестированное)

```bash
cat .git/hooks/post-commit 2>/dev/null || echo "no post-commit hook"
```
Expected: либо хука нет, либо он пушит ТОЛЬКО ветку `main`/прод-ремоут. Если хук деплоит ЛЮБОЙ коммит — временно отключить на время работы: `chmod -x .git/hooks/post-commit` (вернуть `+x` перед финальным мержем в main). Деплой делаем осознанно в фазе finishing-a-development-branch, не на каждый коммит фичеветки.

- [ ] **Step 3: Базовый прогон тестов — зелёные ДО изменений** (фиксируем исходную точку)

```bash
node --test tests/test_pipeline_funnel_pure.test.js tests/test_daily_publish_report.test.js 2>&1 | tail -15
```
Expected: все тесты pass (модульный pure-набор + TG-набор). Если что-то красное ДО правок — разобраться прежде чем продолжать.

---

## Task 1: Модуль — отдать наружу `proactive_manual_notdispatched` + инвариант сведения

**Files:**
- Modify: `pipeline_funnel.js:23-37` (return из `assembleFunnel`)
- Test: `tests/test_pipeline_funnel_pure.test.js`

- [ ] **Step 1: Написать падающие тесты** (добавить в конец `tests/test_pipeline_funnel_pure.test.js`)

```js
const COHORT_2605 = {
  plan: 307, uniqualized: 307, autotask: 277, auto_published: 228,
  manual_handoff: 29, manual_handoff_published: 25,
  proactive_manual_notdispatched: 10, manual_published_total: 64,
  slots_planned: 2, slots_with_queue: 0,
};

test('assembleFunnel: эталон когорты 26.05 (подача #173)', () => {
  const f = assembleFunnel(COHORT_2605);
  assert.equal(f.lost_count, 15);
  assert.equal(f.sr_total, 0.951);                       // (228+64)/307
  assert.equal(f.proactive_manual_published, 39);        // 64-25
  assert.equal(f.proactive_manual_notdispatched, 10);    // НОВОЕ поле наружу
  assert.equal(f.manual_handoff, 29);
  assert.equal(f.blind_zones.after_uniq, 20);            // 307-277-10
  assert.equal(f.blind_zones.auto_errors, 20);           // 277-228-29
});

test('assembleFunnel: инвариант сведения auto + manual_total + lost = plan', () => {
  const f = assembleFunnel(COHORT_2605);
  assert.equal(f.auto_published + f.manual_published_total + f.lost_count, f.plan);
});
```

- [ ] **Step 2: Прогнать — упадёт на новом поле**

Run: `node --test tests/test_pipeline_funnel_pure.test.js 2>&1 | tail -20`
Expected: FAIL — `f.proactive_manual_notdispatched` === `undefined` (≠ 10); остальные ассерты в этих двух тестах могут пройти (поля уже считаются), но новый тест по полю красный.

- [ ] **Step 3: Добавить поле в return `assembleFunnel`** (`pipeline_funnel.js`, в объект возврата после `proactive_manual_published`, строка ~30)

```js
    sr_total: plan > 0 ? round3((auto_published + manual_published_total) / plan) : null,
    proactive_manual_published: clamp0(manual_published_total - manual_handoff_published),
    proactive_manual_notdispatched: proactive_nd,
    blind_zones: {
```
(вставляем ровно строку `proactive_manual_notdispatched: proactive_nd,` — `proactive_nd` уже объявлен строкой 18; формулы и существующие поля не трогаем)

- [ ] **Step 4: Прогнать — зелёный + регрессия 25.05 цела**

Run: `node --test tests/test_pipeline_funnel_pure.test.js 2>&1 | tail -20`
Expected: PASS все тесты, включая исходный «эталон когорты 25.05» (поле аддитивно, ничего не сломано).

- [ ] **Step 5: Commit**

```bash
git add pipeline_funnel.js tests/test_pipeline_funnel_pure.test.js
git commit -m "feat(funnel): отдать proactive_manual_notdispatched + инвариант сведения (WP #173)"
```

---

## Task 2: TG-отчёт — разбивка ручной + строка SR итоговый + штамп снимка (TDD)

**Files:**
- Modify: `daily_publish_report.js:189` (сигнатура `formatMessage`), `:219-227` (блок воронки), `:326` (вызов в `run`)
- Test: `tests/test_daily_publish_report.test.js`

- [ ] **Step 1: Написать падающий тест** (добавить внутри `describe('formatMessage', …)` в `tests/test_daily_publish_report.test.js`, рядом с прочими)

```js
  test('блок воронки: разбивка ручной + SR итоговый + штамп снимка (#173)', () => {
    const funnel = {
      plan: 307, auto_published: 228, manual_published_total: 64,
      manual_handoff_published: 25, proactive_manual_published: 39,
      lost_count: 15, lost_pct: 0.049, manual_share_pct: 0.105, sr_total: 0.951,
    };
    const m = rep.formatMessage(report, { dateLabel: '26.05.2026', mentions: '@a', comments: {}, funnel, snapshotMsk: '09:50' });
    assert.match(m, /Воронка за 26\.05\.2026 \(снимок 09:50 МСК\)/);
    assert.match(m, /Выложено вручную: 64 \(реактив 25 \+ проактив 39\)/);
    assert.match(m, /SR итоговый: 95%/);
  });
```

- [ ] **Step 2: Прогнать — упадёт** (нет штампа/разбивки/SR-строки)

Run: `node --test tests/test_daily_publish_report.test.js 2>&1 | tail -20`
Expected: FAIL — нет совпадений по новым строкам.

- [ ] **Step 3: Расширить сигнатуру `formatMessage`** (`daily_publish_report.js:189`)

```js
function formatMessage(report, { dateLabel, mentions, comments = {}, funnel = null, snapshotMsk = null }) {
```

- [ ] **Step 4: Обновить блок воронки** (`daily_publish_report.js:219-227`) — заменить блок целиком на:

```js
  if (funnel && funnel.plan > 0) {
    const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
    const head = snapshotMsk ? `Воронка за ${dateLabel} (снимок ${snapshotMsk} МСК)` : `Воронка за ${dateLabel}`;
    lines.push('', `——— <b>${head}</b> ———`);
    lines.push(`Запланировано: ${funnel.plan}`);
    lines.push(`Выложено авто: ${funnel.auto_published}`);
    lines.push(`Выложено вручную: ${funnel.manual_published_total} (реактив ${funnel.manual_handoff_published} + проактив ${funnel.proactive_manual_published})`);
    lines.push(`Потеряно: ${funnel.lost_count} (${pct(funnel.lost_pct)})`);
    lines.push(`Ручная выкладка: ${pct(funnel.manual_share_pct)} от авто-задач`);
    lines.push(`SR итоговый: ${pct(funnel.sr_total)}`);
  }
```

- [ ] **Step 5: Передать `snapshotMsk` из `run`** (`daily_publish_report.js:326`) — заменить вызов:

```js
  const snapshotMsk = new Date().toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit' });
  const text = formatMessage(report, { dateLabel, mentions, comments, funnel, snapshotMsk });
```

- [ ] **Step 6: Прогнать — зелёный (новый тест + старые)**

Run: `node --test tests/test_daily_publish_report.test.js 2>&1 | tail -20`
Expected: PASS все, включая существующие тесты `formatMessage` (они не передают `funnel`/`snapshotMsk` → блок воронки скипается как раньше).

- [ ] **Step 7: Commit**

```bash
git add daily_publish_report.js tests/test_daily_publish_report.test.js
git commit -m "feat(daily-report): разбивка ручной + SR итоговый + штамп снимка в воронке (WP #173)"
```

---

## Task 3: Дашборд — вариант A, строка-сверка, обогащённые слепые-зоны, новая сноска

**Files:**
- Modify: `public/index.html:11937-11968` (функция `renderDashboardFunnel`)

> Юнит-харнесса для `index.html` в репо нет — верификация визуальная + проверка арифметики сверки. Логика чисел уже покрыта Task 1.

- [ ] **Step 1: Заменить массив шагов + рендер ячеек** (`public/index.html:11937-11949`)

Заменить блок (steps + stepCells) на:
```js
  const steps = [
    ['План', funnel.plan, 'text-violet-600'],
    ['Уникали-зировано', funnel.uniqualized, 'text-sky-500'],
    ['Авто-задача', funnel.autotask, 'text-blue-500'],
    ['Авто выложено', funnel.auto_published, 'text-green-600'],
    ['В ручную', funnel.manual_handoff, 'text-yellow-500'],
    ['Ручная выложено', funnel.manual_published_total, 'text-green-600',
      `реактив ${funnel.manual_handoff_published} + проактив ${funnel.proactive_manual_published}`],
  ];
  const stepCells = steps.map(([label, val, cls, sub]) => `
    <td class="text-center px-3 py-2 align-top">
      <div class="text-[10px] text-gray-400 uppercase leading-tight mb-1">${label}</div>
      <div class="text-2xl font-bold ${cls}">${val}</div>
      ${sub ? `<div class="text-[9px] text-gray-400 leading-tight mt-0.5">${sub}</div>` : ''}
    </td>`).join('');
```

- [ ] **Step 2: Заменить блок сносок целиком** (`public/index.html:11963-11968`) — добавить строку-сверку, диверсии в слепых-зонах, новую сноску, штамп:

```js
  const bz = funnel.blind_zones || {};
  const gapUniq = funnel.uniqualized - funnel.autotask;
  const gapAuto = funnel.autotask - funnel.auto_published;
  const recOk = (funnel.auto_published + funnel.manual_published_total + funnel.lost_count) === funnel.plan;
  const stamp = new Date().toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit' });
  notes.innerHTML =
    `<div class="mb-1 font-semibold ${recOk ? 'text-green-700' : 'text-red-600'}">` +
      `Сверка: Авто ${funnel.auto_published} + Ручная ${funnel.manual_published_total} + Потеряно ${funnel.lost_count} = План ${funnel.plan} ${recOk ? '✓' : '✗'}</div>` +
    `<b>Слепые зоны:</b> до постановки в очередь — ${bz.before_uniq} (оценка по слотам) │ ` +
    `после уник. → авто-задача — ${bz.after_uniq} (из ${gapUniq}: ${funnel.proactive_manual_notdispatched} → проактив-ручная) │ ` +
    `ошибки авто — ${bz.auto_errors} (из ${gapAuto}: ${funnel.manual_handoff} → хэндофф в ручную) │ ` +
    `зависло вручную — ${bz.manual_stuck}` +
    `<br>Проактивная ручная (${funnel.proactive_manual_published}) — слоты, опубликованные оператором без авто-задачи: ` +
    `засчитаны как выполненные (вошли в «Ручная выложено» и вычтены из «Потеряно»), но идут мимо реактивной ветки. ` +
    `«Потеряно» за «Сегодня» включает незавершённые публикации; число прошедшего дня уточняется по мере поздней ручной.` +
    `<br><span class="text-gray-400">Снимок на ${stamp} МСК.</span>`;
```

- [ ] **Step 3: Синтаксическая проверка JS-блока** (вырезать `<script>` и прогнать через node --check нельзя из-за HTML; вместо этого — быстрый grep на парность шаблонных литералов в правке)

Run: `node -e "require('fs').readFileSync('public/index.html','utf8'); console.log('read ok')"`
Expected: `read ok` (файл цел). Глазами сверить, что бэктики/`${}` в правке сбалансированы.

- [ ] **Step 4: Визуальная проверка на тест-дашборде** (delivery «Выкладка» → блок «Воронка пайплайна», диапазон = 26.05; деплой на тест по конвенции проекта — `cp` в тестовую раздачу)

Expected (на данных 26.05):
- бокс «Ручная выложено» = 64, подпись «реактив 25 + проактив 39»;
- строка «Сверка: Авто 228 + Ручная 64 + Потеряно 15 = План 307 ✓» (зелёная);
- слепые-зоны: «после уник. → авто-задача — 20 (из 30: 10 → проактив-ручная)», «ошибки авто — 20 (из 49: 29 → хэндофф в ручную)»;
- новая сноска без «учтена в Потеряно»; внизу «Снимок на HH:MM МСК».

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(dashboard): воронка вариант A — сверка + проактив-ручная + диверсии + новая сноска (WP #173)"
```

---

## Task 4: Дашборд — тултипы на двух метриках SR

**Files:**
- Modify: `public/index.html:11878-11885` (`_fmtBucketCell` соседство — добавить tip-карту), `:11890-11894` (тайлы из `DASH_BUCKET_LABELS`), `:11899-11904` (плашка «SR итоговый»)

> «SR авто» (`success_rate`) и «SR итоговый» уже отображаются (решение B по сути выполнено #153). Добавляем только пояснительные тултипы, чтобы их не путали.

- [ ] **Step 1: Добавить tip-карту** (`public/index.html`, перед `function renderDashboardOverall`, ~строка 11886)

```js
const DASH_TILE_TIP = { success_rate: 'SR авто = Готово / (Готово + Ошибки) — успешность авто-попыток' };
```

- [ ] **Step 2: Прокинуть `title` в generic-тайлы** (`public/index.html:11890-11894`) — заменить map на:

```js
  const tiles = DASH_BUCKET_LABELS.map(([key, label, textCls, borderCls]) => `
    <div class="flex flex-col items-center gap-0.5 bg-white border ${borderCls} rounded-lg px-2 py-2" title="${DASH_TILE_TIP[key] || ''}">
      <span class="text-xl font-bold ${textCls}">${_fmtBucketCell(key, overall[key])}</span>
      <span class="text-[10px] text-gray-400 uppercase">${label}</span>
    </div>
  `);
```

- [ ] **Step 3: Добавить `title` на плашку «SR итоговый»** (`public/index.html:11899-11904`) — заменить на:

```js
    tiles.push(`
      <div class="flex flex-col items-center gap-0.5 bg-violet-50 border border-violet-300 rounded-lg px-2 py-2" title="SR итоговый = (Авто выложено + вся Ручная) / План">
        <span class="text-xl font-bold text-violet-700">${Math.round(overall.sr_total*100)}%</span>
        <span class="text-[10px] text-violet-600 uppercase font-semibold">SR итоговый</span>
      </div>
    `);
```

- [ ] **Step 4: Визуальная проверка** — навести курсор на «SR авто» и «SR итоговый»: всплывают пояснения формул. Числа не изменились.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(dashboard): тултипы формул SR авто / SR итоговый (WP #173)"
```

---

## Task 5: Полный прогон + сводка

- [ ] **Step 1: Прогнать оба юнит-набора целиком**

Run: `node --test tests/test_pipeline_funnel_pure.test.js tests/test_daily_publish_report.test.js 2>&1 | tail -20`
Expected: все pass, 0 fail.

- [ ] **Step 2: (если доступна тест-БД) live-набор воронки** — иначе пропустить и отметить как пропущенный

Run: `node --test tests/test_pipeline_funnel_live.test.js 2>&1 | tail -20`
Expected: pass, либо честно зафиксировать «пропущен (нет тест-БД)».

- [ ] **Step 3: `codex review` диффа реализации** (правило проекта — раундами до 0 P1)

Run: `git diff main...HEAD | ~/.local/bin/codex review -  2>&1 | tail -40`
Expected: 0 P1. P2/P3 — оценить и закрыть либо обосновать.

- [ ] **Step 4: Сводка ветки** — список коммитов, готовность к финишу (см. finishing-a-development-branch для деплоя: `cp` index.html в прод-раздачу / cherry-pick в main; модуль+TG деплоятся pull'ом автоварма).

```bash
git log --oneline main..HEAD
```

---

## Task 6: OpenProject — комментарий Анастасии (ПОСЛЕ деплоя/приёмки)

> Делать в самом конце, когда фикс на проде. House style: Что было не так → Что сделано → Что осталось, без футера (см. feedback-openproject-practice).

- [ ] **Step 1: Сформировать и отправить комментарий в WP #173** через OpenProject API (токен `~/secrets/openproject.env`, `POST /api/v3/work_packages/173/activities`, тело `{"comment":{"raw":"<markdown>"}}`).

Содержание: по каждому из 6 пунктов — что стало видно/исправлено и что by-design; явно: «**95% — это наша же плашка SR итоговый** (и совпавшая в этот день авто-метрика), **82% — пересчёт по реактивному боксу**. Теперь воронка сходится строкой-сверкой: 228 + 64 + 15 = 307. П.5: Телега и дашборд показывают одну «всю ручную», разница 52↔64 — дрейф снимка (поздняя ручная докатывается), окна идентичны». Приложить пример сверки за 26.05.

- [ ] **Step 2: Перевести #173 в «Тестирование»** (id 9) — PATCH `/api/v3/work_packages/173` c актуальным `lockVersion`.

---

## Self-review (выполнено при написании)

- **Покрытие спеки:** п.1/6 → Task 1 (поле) + Task 3 (сверка/бокс A); п.2/3 → Task 3 (диверсии в зонах) + Task 1 (поле proactive_nd); п.4 → Task 3 (сноска); п.5 ярлык → Task 3 (бокс A = total, совпал с TG) + Task 2 (разбивка TG), дрейф → сноска + штамп (Task 2/3) + Task 6 (пояснение); решение B (две SR) → Task 4 (тултипы; тайлы уже есть). ✔
- **Плейсхолдеры:** нет TBD; весь код приведён. ✔
- **Согласованность имён:** `proactive_manual_notdispatched`, `proactive_manual_published`, `manual_handoff`, `manual_handoff_published`, `manual_published_total`, `sr_total` — едины во всех тасках и совпадают с текущим `pipeline_funnel.js`. ✔
- **Отклонение от спеки (осознанное, YAGNI):** не добавляем `diversions`/`stage_gaps`/алиасы в модуль — поверхности выводят их из уже отдаваемых полей; наружу нужно лишь `proactive_manual_notdispatched`. Это уменьшает поверхность изменения модуля, выходные требования подачи закрыты полностью.
