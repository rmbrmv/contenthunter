# Реальные логотипы платформ (OP#92) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить эмодзи платформ реальными официальными логотипами (SVG) во всех innerHTML-местах дашборда, сведя источник иконок к единому реестру. В `<option>`/`textContent`/`esc()`-контекстах (где браузер не рендерит SVG) — оставить эмодзи + текст.

**Architecture:** Новый pure-модуль `public/platform_registry_pure.js` (UMD, как `search_select_pure.js`) — единый реестр **12 платформ** + хелперы. Логотипы — встроенный SVG-`<symbol>` спрайт в `index.html`; `platformLogo(key,size)` рендерит `<svg><use href="#logo-…"/></svg>` для innerHTML. Существующий канонический эмодзи-слой (`PLATFORM_ICONS`/`platformIcon`/`platformLabel`, ~стр.4103, добавлен прошлым OP#92-батчем) **остаётся** и обслуживает текстовые контексты. 11 легаси-словарей (`platformIcons`/`PLATFORM_ICON`/`_platformIcons`/`_platformColors`/`LC_PLAT`/`_ptPlatformIcon`/`PQ_PLATFORM_ICON`/`UP_PLATFORM_ICON`) — удаляются, их call-site'ы маршрутизируются ПО КОНТЕКСТУ: innerHTML → `platformLogo()`, option/text → канонический `platformIcon()`.

**Tech Stack:** Статичный `public/index.html` (Tailwind CDN), pure-JS модули `public/*_pure.js`, тесты `node --test`.

**Worktree кода:** `/home/claude-user/op92-platform-logos` (ветка `op92-platform-logos` от `origin/main`). Все пути ниже — относительно него.

**Спека:** `docs/superpowers/specs/2026-06-05-platform-logos-design.md` (docs-репо).

> ⚠️ **Контекстное правило (важнейшее):** SVG (`platformLogo`) ТОЛЬКО туда, где строка попадает в `innerHTML` как разметка. В нативный `<option>`, в `element.textContent`/`.textContent =`, и в `${esc(...)}` — ВСЕГДА эмодзи (канонический `platformIcon(x)`), иначе SVG отрендерится как пустота/текст. Полная классификация — в Task 4/5.

---

## Файловая структура

- **Create** `public/platform_registry_pure.js` — реестр 12 платформ + хелперы (источник истины для SVG).
- **Create** `tests/test_platform_registry_pure.test.js` — юнит-тесты хелперов + консистентность реестр↔спрайт.
- **Modify** `public/index.html` — (а) SVG-спрайт; (б) `<script src>`; (в) удалить 11 легаси-словарей + маршрутизировать их call-site'ы; (г) канонические innerHTML-консьюмеры → `platformLogo`; (д) статичные эмодзи (сайдбар/`<h1>`/бейджи) → SVG; (е) крупное место — явный размер.

---

### Task 1: Pure-модуль реестра платформ (12 платформ)

**Status:** реализован (commit `f8cb11a`) на 10 платформах — РАСШИРИТЬ до 12 (добавить telegram/whatsapp).

**Files:**
- Modify: `public/platform_registry_pure.js`
- Modify: `tests/test_platform_registry_pure.test.js`

- [ ] **Step 1: Обновить тест полноты (10 → 12)**

В `tests/test_platform_registry_pure.test.js` заменить тест полноты:

```js
test('реестр содержит все 12 платформ', () => {
  const expected = ['instagram','youtube','tiktok','pinterest','likee','vk','rutube','dzen','threads','wibes','telegram','whatsapp'];
  assert.deepEqual(Object.keys(PLATFORMS).sort(), expected.slice().sort());
});
```

Добавить проверку новых:
```js
test('telegram/whatsapp: имя, sym, эмодзи', () => {
  assert.equal(platformName('telegram'), 'Telegram');
  assert.match(platformLogo('telegram'), /href="#logo-telegram"/);
  assert.equal(platformEmoji('telegram'), '✈️');
  assert.equal(platformName('whatsapp'), 'WhatsApp');
  assert.match(platformLogo('whatsapp'), /href="#logo-whatsapp"/);
  assert.equal(platformEmoji('whatsapp'), '💬');
});
```

- [ ] **Step 2: Запустить — упадёт на полноте**

Run: `cd /home/claude-user/op92-platform-logos && node --test --test-force-exit tests/test_platform_registry_pure.test.js`
Expected: FAIL (реестр на 10).

- [ ] **Step 3: Добавить 2 записи в реестр**

В `public/platform_registry_pure.js` в объект `PLATFORMS`, после `wibes:`, добавить:

```js
    telegram:  { name: 'Telegram', sym: 'logo-telegram', emoji: '✈️', badge: 'bg-sky-50 text-sky-700' },
    whatsapp:  { name: 'WhatsApp', sym: 'logo-whatsapp', emoji: '💬', badge: 'bg-green-50 text-green-700' },
```

(`Object.freeze(PLATFORMS)` уже стоит после литерала — оставить там же, ниже добавленных строк.)

- [ ] **Step 4: Запустить — проходит**

Run: `node --test --test-force-exit tests/test_platform_registry_pure.test.js`
Expected: PASS (8 тестов).

- [ ] **Step 5: Commit**

```bash
git add public/platform_registry_pure.js tests/test_platform_registry_pure.test.js
git commit -m "feat(op92): расширить реестр платформ до 12 (telegram, whatsapp)"
```

---

### Task 2: SVG-спрайт логотипов (12) + подключение модуля

**Files:**
- Modify: `public/index.html`

- [ ] **Step 1: Подключить модуль**

После строки `<script src="/search_select.js"></script>` (~24) добавить:

```html
  <script src="/platform_registry_pure.js"></script>
```

- [ ] **Step 2: Вставить спрайт сразу после открывающего `<body…>`**

12 `<symbol>` + `logo-generic`. Пути 8 лого — simple-icons (фирменные `fill`); rutube/dzen/likee/wibes — фирменно-цветной леттермарк.

```html
  <!-- OP#92: спрайт логотипов платформ. Источник: simple-icons (фирменные цвета). -->
  <svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">
    <defs>
      <radialGradient id="ig-grad" cx="0.3" cy="1" r="1.1">
        <stop offset="0" stop-color="#FED576"/>
        <stop offset="0.26" stop-color="#F47133"/>
        <stop offset="0.61" stop-color="#BC3081"/>
        <stop offset="1" stop-color="#4C63D2"/>
      </radialGradient>
    </defs>

    <symbol id="logo-instagram" viewBox="0 0 24 24"><path fill="url(#ig-grad)" d="M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077"/></symbol>

    <symbol id="logo-youtube" viewBox="0 0 24 24"><path fill="#FF0000" d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></symbol>

    <symbol id="logo-tiktok" viewBox="0 0 24 24"><path fill="#000000" d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/></symbol>

    <symbol id="logo-pinterest" viewBox="0 0 24 24"><path fill="#BD081C" d="M12.017 0C5.396 0 .029 5.367.029 11.987c0 5.079 3.158 9.417 7.618 11.162-.105-.949-.199-2.403.041-3.439.219-.937 1.406-5.957 1.406-5.957s-.359-.72-.359-1.781c0-1.663.967-2.911 2.168-2.911 1.024 0 1.518.769 1.518 1.688 0 1.029-.653 2.567-.992 3.992-.285 1.193.6 2.165 1.775 2.165 2.128 0 3.768-2.245 3.768-5.487 0-2.861-2.063-4.869-5.008-4.869-3.41 0-5.409 2.562-5.409 5.199 0 1.033.394 2.143.889 2.741.099.12.112.225.085.345-.09.375-.293 1.199-.334 1.363-.053.225-.172.271-.401.165-1.495-.69-2.433-2.878-2.433-4.646 0-3.776 2.748-7.252 7.92-7.252 4.158 0 7.392 2.967 7.392 6.923 0 4.135-2.607 7.462-6.233 7.462-1.214 0-2.354-.629-2.758-1.379l-.749 2.848c-.269 1.045-1.004 2.352-1.498 3.146 1.123.345 2.306.535 3.55.535 6.607 0 11.985-5.365 11.985-11.987C23.97 5.39 18.592.026 11.985.026L12.017 0z"/></symbol>

    <symbol id="logo-vk" viewBox="0 0 24 24"><path fill="#0077FF" d="m9.489.004.729-.003h3.564l.73.003.914.01.433.007.418.011.403.014.388.016.374.021.36.025.345.03.333.033c1.74.196 2.933.616 3.833 1.516.9.9 1.32 2.092 1.516 3.833l.034.333.029.346.025.36.02.373.025.588.012.41.013.644.009.915.004.98-.001 3.313-.003.73-.01.914-.007.433-.011.418-.014.403-.016.388-.021.374-.025.36-.03.345-.033.333c-.196 1.74-.616 2.933-1.516 3.833-.9.9-2.092 1.32-3.833 1.516l-.333.034-.346.029-.36.025-.373.02-.588.025-.41.012-.644.013-.915.009-.98.004-3.313-.001-.73-.003-.914-.01-.433-.007-.418-.011-.403-.014-.388-.016-.374-.021-.36-.025-.345-.03-.333-.033c-1.74-.196-2.933-.616-3.833-1.516-.9-.9-1.32-2.092-1.516-3.833l-.034-.333-.029-.346-.025-.36-.02-.373-.025-.588-.012-.41-.013-.644-.009-.915-.004-.98.001-3.313.003-.73.01-.914.007-.433.011-.418.014-.403.016-.388.021-.374.025-.36.03-.345.033-.333c.196-1.74.616-2.933 1.516-3.833.9-.9 2.092-1.32 3.833-1.516l.333-.034.346-.029.36-.025.373-.02.588-.025.41-.012.644-.013.915-.009ZM6.79 7.3H4.05c.13 6.24 3.25 9.99 8.72 9.99h.31v-3.57c2.01.2 3.53 1.67 4.14 3.57h2.84c-.78-2.84-2.83-4.41-4.11-5.01 1.28-.74 3.08-2.54 3.51-4.98h-2.58c-.56 1.98-2.22 3.78-3.8 3.95V7.3H10.5v6.92c-1.6-.4-3.62-2.34-3.71-6.92Z"/></symbol>

    <symbol id="logo-threads" viewBox="0 0 24 24"><path fill="#000000" d="M12.186 24h-.007c-3.581-.024-6.334-1.205-8.184-3.509C2.35 18.44 1.5 15.586 1.472 12.01v-.017c.03-3.579.879-6.43 2.525-8.482C5.845 1.205 8.6.024 12.18 0h.014c2.746.02 5.043.725 6.826 2.098 1.677 1.29 2.858 3.13 3.509 5.467l-2.04.569c-1.104-3.96-3.898-5.984-8.304-6.015-2.91.022-5.11.936-6.54 2.717C4.307 6.504 3.616 8.914 3.589 12c.027 3.086.718 5.496 2.057 7.164 1.43 1.783 3.631 2.698 6.54 2.717 2.623-.02 4.358-.631 5.8-2.045 1.647-1.613 1.618-3.593 1.09-4.798-.31-.71-.873-1.3-1.634-1.75-.192 1.352-.622 2.446-1.284 3.272-.886 1.102-2.14 1.704-3.73 1.79-1.202.065-2.361-.218-3.259-.801-1.063-.689-1.685-1.74-1.752-2.964-.065-1.19.408-2.285 1.33-3.082.88-.76 2.119-1.207 3.583-1.291a13.853 13.853 0 0 1 3.02.142c-.126-.742-.375-1.332-.75-1.757-.513-.586-1.308-.883-2.359-.89h-.029c-.844 0-1.992.232-2.721 1.32L7.734 7.847c.98-1.454 2.568-2.256 4.478-2.256h.044c3.194.02 5.097 1.975 5.287 5.388.108.046.216.094.321.142 1.49.7 2.58 1.761 3.154 3.07.797 1.82.871 4.79-1.548 7.158-1.85 1.81-4.094 2.628-7.277 2.65Zm1.003-11.69c-.242 0-.487.007-.739.021-1.836.103-2.98.946-2.916 2.143.067 1.256 1.452 1.839 2.784 1.767 1.224-.065 2.818-.543 3.086-3.71a10.5 10.5 0 0 0-2.215-.221z"/></symbol>

    <symbol id="logo-telegram" viewBox="0 0 24 24"><path fill="#26A5E4" d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></symbol>

    <symbol id="logo-whatsapp" viewBox="0 0 24 24"><path fill="#25D366" d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"/></symbol>

    <!-- Вне simple-icons: фирменно-цветные леттермарки. -->
    <symbol id="logo-rutube" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#000000"/><path fill="#ffffff" d="M9 7.5v9l8-4.5z"/></symbol>
    <symbol id="logo-dzen" viewBox="0 0 24 24"><circle cx="12" cy="12" r="12" fill="#000000"/><text x="12" y="12" text-anchor="middle" dominant-baseline="central" fill="#ffffff" font-family="Arial, sans-serif" font-weight="700" font-size="13">Д</text></symbol>
    <symbol id="logo-likee" viewBox="0 0 24 24"><circle cx="12" cy="12" r="12" fill="#1EC8C8"/><text x="12" y="12" text-anchor="middle" dominant-baseline="central" fill="#ffffff" font-family="Arial, sans-serif" font-weight="700" font-size="13">L</text></symbol>
    <symbol id="logo-wibes" viewBox="0 0 24 24"><circle cx="12" cy="12" r="12" fill="#00A0E9"/><text x="12" y="12" text-anchor="middle" dominant-baseline="central" fill="#ffffff" font-family="Arial, sans-serif" font-weight="700" font-size="13">W</text></symbol>
    <symbol id="logo-generic" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#9CA3AF"/><circle cx="12" cy="12" r="4.5" fill="#ffffff"/></symbol>
  </svg>
```

- [ ] **Step 3: Смоук парсинга**

```bash
node -e "require('fs').readFileSync('public/index.html','utf8'); console.log('html readable')"
node --check server.js && echo "server.js OK"
```

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "feat(op92): SVG-спрайт логотипов 12 платформ + подключение реестра"
```

---

### Task 3: Тест консистентности реестр ↔ спрайт

**Files:**
- Modify: `tests/test_platform_registry_pure.test.js`

- [ ] **Step 1: Дописать тесты**

В конец файла:

```js
const fs = require('node:fs');
const path = require('node:path');

test('каждый sym реестра (+logo-generic) имеет <symbol id> в спрайте index.html', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  const ids = new Set([...html.matchAll(/<symbol\s+id="([^"]+)"/g)].map(m => m[1]));
  for (const k of Object.keys(PLATFORMS)) {
    assert.ok(ids.has(PLATFORMS[k].sym), `нет <symbol id="${PLATFORMS[k].sym}"> для ${k}`);
  }
  assert.ok(ids.has('logo-generic'), 'нет <symbol id="logo-generic">');
});

test('подключён скрипт platform_registry_pure.js', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  assert.match(html, /<script src="\/platform_registry_pure\.js">/);
});
```

- [ ] **Step 2: Запустить — проходит**

Run: `node --test --test-force-exit tests/test_platform_registry_pure.test.js`
Expected: PASS (10 тестов). Падает на отсутствии `<symbol>` → вернуться к Task 2.

- [ ] **Step 3: Commit**

```bash
git add tests/test_platform_registry_pure.test.js
git commit -m "test(op92): консистентность реестр↔спрайт + подключение скрипта"
```

---

### Task 4: Удалить 11 легаси-словарей и маршрутизировать их call-site'ы

**Files:**
- Modify: `public/index.html`

**Принцип маршрутизации (по контексту вставки):**
- **innerHTML** (значение идёт в HTML-разметку через `${...}` в template literal, который присваивается `innerHTML`/возвращается для рендера) → `platformLogo(x)` (SVG).
- **option / textContent / esc** → канонический `platformIcon(x)` (эмодзи). `platformIcon` уже определён в index.html (~стр.4117) и покрывает 12 платформ.

Полная классификация (значения иконки на этих строках; ОСТАВЛЯЕМ текст имени/`row.platform` рядом как есть):

| Строка | Текущее | Контекст | Замена иконки |
|--------|---------|----------|---------------|
| 4569 | `${platformIcons[t.platform] \|\| '—'}` | `<td>` innerHTML | `${platformLogo(t.platform)}` |
| 4589 | `${platformIcons[p.platform] \|\| p.platform \|\| '—'}` | `<td>` innerHTML | `${platformLogo(p.platform)}` |
| 4946→4948 | `PLATFORM_ICON[a.platform?.toLowerCase()] \|\| '👤'` → `${icon}` в `<option>` | OPTION | `platformIcon(a.platform) \|\| '👤'` |
| 5957→5962 | `platformIcons[t.platform] \|\| '📱'` → `${pIcon}` в `<td><span>` | innerHTML | `platformLogo(t.platform)` (см. примечание ниже) |
| 6837 | `${_platformColors[p] ...}">${_platformIcons[p] \|\| ''} ${p}` | innerHTML | цвет → `${platformBadge(p)}`; иконка → `${platformLogo(p)}` |
| 6868 | `${_platformColors[acc.platform] ...}">${_platformIcons[acc.platform] \|\| ''} ${acc.platform}` | innerHTML | `${platformBadge(acc.platform)}` + `${platformLogo(acc.platform)}` |
| 6887 | `${_platformIcons[a.platform] \|\| ''} ${a.platform}` | innerHTML | `${platformLogo(a.platform)}` |
| 6902 | `${_platformIcons[a.platform] \|\| ''} ${a.platform}` | innerHTML | `${platformLogo(a.platform)}` |
| 7157 | `${platformIcons[t.platform] \|\| ''} ${platformNames[...]...}` | `<td>` innerHTML | `${platformLogo(t.platform)}` |
| 7392 | `${LC_PLAT[(a.platform\|\|'').toLowerCase()]\|\|''} ${esc(a.platform\|\|'')}` | innerHTML (только `a.platform` esc'нут, иконка — нет) | `${platformLogo(a.platform)}` |
| 7886 | `${_ptPlatformIcon[t.platform]\|\|''} ${t.platform\|\|'—'}` | `<td>` innerHTML | `${platformLogo(t.platform)}` |
| 7944 | `v => \`${_ptPlatformIcon[v]\|\|''} ${v}\`` (ptPopulateSelect → `<option>`) | OPTION | `v => \`${platformIcon(v)?platformIcon(v)+' ':''}${v}\`` |
| 11323→11339 | `PQ_PLATFORM_ICON[...] \|\| '📱'` → `${icon}` в `<td>` | innerHTML | `platformLogo(row.platform)` |
| 11772→11820 | `UP_PLATFORM_ICON[...] \|\| '📱'` → `${icon}` в `<td>` | innerHTML | `platformLogo(row.platform)` |
| 11925→11961 | `UP_PLATFORM_ICON[...] \|\| '📱'` → `${icon}` в `<td>` | innerHTML | `platformLogo(row.platform)` |

**Примечание по `const icon/pIcon = …`-местам (5957, 11323, 11772, 11925):** там значение присваивается переменной, а ПОТОМ вставляется в шаблон. Заменить инициализатор переменной на `platformLogo(<platformExpr>)` (не на dict-lookup). Для `|| '👤'`/`|| '📱'` фолбэк убирается — `platformLogo` сам отдаёт `logo-generic` для неизвестной платформы. Для OPTION-места 4946 фолбэк `|| '👤'` сохранить (эмодзи).

- [ ] **Step 1: Применить маршрутизацию call-site'ов (таблица выше)**

Точечно для каждой строки. Примеры точных замен:

```
// 4569
${platformIcons[t.platform] || '—'}
${platformLogo(t.platform)}

// 4946 (внутри функции, инициализатор)
const icon = PLATFORM_ICON[a.platform?.toLowerCase()] || '👤';
const icon = platformIcon(a.platform) || '👤';

// 5957
const pIcon = platformIcons[t.platform] || '📱';
const pIcon = platformLogo(t.platform);

// 6837 (две правки в одной строке)
... ${_platformColors[p] || 'bg-gray-100 text-gray-700'}">${_platformIcons[p] || ''} ${p}</span>
... ${platformBadge(p)}">${platformLogo(p)} ${p}</span>

// 6868
... ${_platformColors[acc.platform] || 'bg-gray-100'}">${_platformIcons[acc.platform] || ''} ${acc.platform}</span>
... ${platformBadge(acc.platform)}">${platformLogo(acc.platform)} ${acc.platform}</span>

// 6887
${_platformIcons[a.platform] || ''} ${a.platform}: ${statusLabels[a.status] || a.status}
${platformLogo(a.platform)} ${a.platform}: ${statusLabels[a.status] || a.status}

// 6902
${_platformIcons[a.platform] || ''} ${a.platform}: @${a.username}
${platformLogo(a.platform)} ${a.platform}: @${a.username}

// 7157
${platformIcons[t.platform] || ''} ${platformNames[t.platform] || t.platform || '—'}
${platformLogo(t.platform)} ${platformNames[t.platform] || t.platform || '—'}

// 7392
${LC_PLAT[(a.platform||'').toLowerCase()]||''} ${esc(a.platform||'')}
${platformLogo(a.platform)} ${esc(a.platform||'')}

// 7886
${_ptPlatformIcon[t.platform]||''} ${t.platform||'—'}
${platformLogo(t.platform)} ${t.platform||'—'}

// 7944 (ptPopulateSelect labelFn → option, ЭМОДЗИ)
v => `${_ptPlatformIcon[v]||''} ${v}`
v => `${platformIcon(v) ? platformIcon(v)+' ' : ''}${v}`

// 11323
const icon = PQ_PLATFORM_ICON[row.platform?.toLowerCase()] || '📱';
const icon = platformLogo(row.platform);

// 11772 и 11925 (оба)
const icon = UP_PLATFORM_ICON[row.platform?.toLowerCase()] || '📱';
const icon = platformLogo(row.platform);
```

- [ ] **Step 2: Удалить 11 определений словарей**

Удалить строки-определения (после того как call-site'ы больше на них не ссылаются):
`platformIcons` (4 шт: ~4400, 4636, 5956, 7112), `PLATFORM_ICON` (~4924), `_platformIcons` (~6821), `_platformColors` (~6822), `LC_PLAT` (~7373), `_ptPlatformIcon` (~7813), `PQ_PLATFORM_ICON` (~11247), `UP_PLATFORM_ICON` (~11415).

ВНИМАНИЕ: `platformNames`, `PLAT_SHORT`, канонические `PLATFORM_ICONS`/`platformIcon`/`platformLabel` — НЕ трогать.

- [ ] **Step 3: Проверка**

```bash
grep -nE "(platformIcons|PLATFORM_ICON|_platformIcons|_platformColors|LC_PLAT|_ptPlatformIcon|PQ_PLATFORM_ICON|UP_PLATFORM_ICON)\b" public/index.html
```
Ожидаемо: НЕ должно быть ни определений, ни ссылок на эти 11 идентификаторов (канонический `PLATFORM_ICONS` с финальной `S` — остаётся; не путать). Если grep что-то находит — это `PLATFORM_ICONS`/`platformIcon`/`platformLabel` (ок) либо пропущенный call-site (исправить).

```bash
node -e "require('fs').readFileSync('public/index.html','utf8')" && echo "readable"
```

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "feat(op92): удалить 11 легаси-словарей; innerHTML→platformLogo, option→platformIcon"
```

---

### Task 5: Статичные эмодзи + канонические innerHTML-консьюмеры → SVG

**Files:**
- Modify: `public/index.html`

**5a. Статичные эмодзи платформ** (сайдбар-нав, бейдж-спаны, `<h1>`):

- [ ] **Step 1: Сайдбар-навигация (≈311/314/317)**

```
<span>📸</span> Instagram   →  <span class="inline-flex"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-instagram"></use></svg></span> Instagram
<span>🎵</span> TikTok       →  <span class="inline-flex"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-tiktok"></use></svg></span> TikTok
<span>▶️</span> YouTube      →  <span class="inline-flex"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-youtube"></use></svg></span> YouTube
```

- [ ] **Step 2: Бейдж-спаны выбора аккаунта (≈2851/2855/2859)**

```
<span class="text-sm text-gray-700">📸 Instagram</span>  →  <span class="text-sm text-gray-700"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-instagram"></use></svg> Instagram</span>
<span class="text-sm text-gray-700">🎵 TikTok</span>      →  <span class="text-sm text-gray-700"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-tiktok"></use></svg> TikTok</span>
<span class="text-sm text-gray-700">▶️ YouTube</span>     →  <span class="text-sm text-gray-700"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-youtube"></use></svg> YouTube</span>
```

- [ ] **Step 3: Заголовки `<h1>` (≈3544/3635/3726), крупно (`w-7 h-7`)**

```
<h1 class="text-2xl font-bold text-gray-900">📸 Instagram</h1>  →  <h1 class="text-2xl font-bold text-gray-900"><svg class="w-7 h-7 inline-block align-[-0.15em]" aria-hidden="true"><use href="#logo-instagram"></use></svg> Instagram</h1>
<h1 class="text-2xl font-bold text-gray-900">🎵 TikTok</h1>      →  <h1 class="text-2xl font-bold text-gray-900"><svg class="w-7 h-7 inline-block align-[-0.15em]" aria-hidden="true"><use href="#logo-tiktok"></use></svg> TikTok</h1>
<h1 class="text-2xl font-bold text-gray-900">▶️ YouTube</h1>     →  <h1 class="text-2xl font-bold text-gray-900"><svg class="w-7 h-7 inline-block align-[-0.15em]" aria-hidden="true"><use href="#logo-youtube"></use></svg> YouTube</h1>
```

**5b. Канонические innerHTML-консьюмеры** `platformIcon`/`platformLabel` → SVG (ТОЛЬКО эти три; остальные канонические места — option/textContent/esc — НЕ трогать):

- [ ] **Step 4: 4656, 7484, 15100**

```
// 4656 (span innerHTML)
<span class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-indigo-50 text-indigo-700">${platformLabel(p.platform)}</span>
<span class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-indigo-50 text-indigo-700">${platformLogo(p.platform)} ${platformName(p.platform)}</span>

// 7484 (td innerHTML)
<td class="px-3 py-2 text-gray-400 text-xs">${platformIcon(row.platform)} ${row.platform}</td>
<td class="px-3 py-2 text-gray-400 text-xs">${platformLogo(row.platform)} ${row.platform}</td>

// 15100 (p innerHTML)
<p class="text-xs text-gray-400">${r.project_name || 'Проект не указан'} · ${platformIcon(r.platform)} ${r.platform}</p>
<p class="text-xs text-gray-400">${r.project_name || 'Проект не указан'} · ${platformLogo(r.platform)} ${r.platform}</p>
```

- [ ] **Step 5: Проверка**

```bash
grep -nE "<span>(📸|🎵|▶️)</span>" public/index.html || echo "OK сайдбар"
grep -nE "text-sm text-gray-700\">(📸|🎵|▶️)" public/index.html || echo "OK бейджи"
grep -nE "<h1[^>]*>(📸|🎵|▶️)" public/index.html || echo "OK h1"
```
Expected: три «OK». Визуально: сайдбар, страницы IG/TikTok/YouTube, модалка аккаунтов, таблицы 7484/15100/4656.

- [ ] **Step 6: Commit**

```bash
git add public/index.html
git commit -m "feat(op92): статичные эмодзи + канонические innerHTML-места → SVG-логотипы"
```

---

### Task 6: Крупное место + проверка текстовых контекстов

**Files:**
- Modify: `public/index.html`

- [ ] **Step 1: Крупная иконка карточки (≈4653)**

```
<span class="text-2xl">${platformIcons[p.platform] || '📋'}</span>
<span class="inline-flex">${PLATFORMS[String(p.platform||'').toLowerCase()] ? platformLogo(p.platform,'w-6 h-6') : '📋'}</span>
```
(После Task 4 `platformIcons` удалён; здесь даём явный размер w-6, фолбэк 📋 для неизвестной платформы. `PLATFORMS` доступен глобально из реестра.)

- [ ] **Step 2: Подтвердить, что текстовые контексты остались на эмодзи**

Эти места НЕ должны содержать `platformLogo` (там SVG не отрендерится): 4979 (`<option>`), 7989/8450 (`.textContent`), 13090 (`esc(...)`), 13334 (компактный short-label). Проверка:

```bash
for ln in 4979 7989 8450 13090 13334; do echo -n "$ln: "; sed -n "${ln}p" public/index.html | grep -o "platformLogo" && echo "!!! SVG в текстовом контексте — ОШИБКА" || echo "ok (эмодзи)"; done
```
Expected: все «ok (эмодзи)».

- [ ] **Step 3: Проверить, что в `<option>` есть текст имени**

```bash
grep -nE "<option value=\"[^\"]+\">(📸|🎵|▶️|📌|❤️|🔵|🎬|🟡|🧵|🌊|📷|✈️|💬) *</option>" public/index.html || echo "OK: все option с текстом"
```
Expected: «OK: все option с текстом».

- [ ] **Step 4: Commit (если были правки)**

```bash
git add public/index.html
git commit -m "feat(op92): крупная иконка карточки через platformLogo + проверка текстовых мест"
```

---

### Task 7: Финальная проверка и интеграция

- [ ] **Step 1: Полный прогон тестов модуля**

Run: `node --test --test-force-exit tests/test_platform_registry_pure.test.js`
Expected: PASS (10 тестов).

- [ ] **Step 2: Регрессия смежных pure-тестов + platform_icons**

Run: `node --test --test-force-exit tests/test_search_select_pure.test.js tests/test_platform_icons.test.js 2>&1 | tail -6`
Expected: без новых падений (канонический `platform_icons.js` мы не меняли).

- [ ] **Step 3: Нет остаточных легаси-идентификаторов и платформенных эмодзи в innerHTML**

```bash
grep -nE "\b(platformIcons|PLATFORM_ICON|_platformIcons|_platformColors|LC_PLAT|_ptPlatformIcon|PQ_PLATFORM_ICON|UP_PLATFORM_ICON)\b" public/index.html || echo "OK: легаси-словари вычищены"
grep -nE "<span>(📸|🎵|▶️)</span>" public/index.html || echo "OK: сайдбар чист"
```
Expected: оба «OK».

- [ ] **Step 4: Ручная визуальная приёмка (Данил)**

Реальные логотипы (не эмодзи) на: сайдбар-нав (IG/TikTok/YouTube), заголовки IG/TikTok/YouTube, таблицы «Контент»/«Аккаунты»/«Очередь публикаций»/«Ручная выкладка» (платформа + бейджи), карточка задачи (крупная иконка), модалка выбора аккаунта, аудит-аккаунты (telegram/whatsapp логотипы). Выпадашки/`.textContent`-места — эмодзи + текст (ожидаемо).

- [ ] **Step 5: Push + интеграция**

`superpowers:finishing-a-development-branch`. Ветка `op92-platform-logos` → PR/мердж в `main` (delivery-contenthunter). Деплой: прод-autowarm `git pull` (статика; PM2-restart не нужен). Доки-PR (спека+план) — в docs-репо (rmbrmv/contenthunter).

---

## Self-Review (выполнено автором плана, ревизия 2)

- **Покрытие спеки:** реестр+хелперы (T1, 12 платформ), спрайт+подключение (T2), консистентность (T3), легаси-словари по контексту (T4), статичные+канонические innerHTML (T5), крупное место + защита текстовых контекстов (T6). ✔
- **Ключевая правка ревизии 2:** обнаружено, что иконки используются в СМЕШАННЫХ контекстах (innerHTML vs `<option>`/`textContent`/`esc`), и существует канонический эмодзи-слой `PLATFORM_ICONS`/`platformIcon`/`platformLabel` (12 платформ, вкл. telegram/whatsapp). Blanket «rebuild словарей через platformIconMap» из ревизии 1 СЛОМАЛ бы `<option>`-места (7944, 4946) и textContent (7989/8450). Заменено на per-site маршрутизацию; реестр расширен до 12, чтобы telegram/whatsapp не регрессировали в innerHTML-местах. `platformIconMap`/`platformColorMap` остаются в модуле (покрыты тестами), но в index.html не используются — это ок (часть публичного API реестра).
- **Плейсхолдеры:** реальные `path d` для 8 simple-icons лого вшиты; 4 леттермарка конкретны. ✔
- **Консистентность типов:** `platformLogo/platformName/platformBadge/platformEmoji/PLATFORMS` — имена совпадают между T1 и заменами T4–T6. Канонический `platformIcon` (эмодзи) — существующая функция index.html, не из модуля. ✔
- **Защита от регрессий:** T6 Step 2 проверяет, что `platformLogo` НЕ просочился в текстовые контексты; T7 — что легаси-идентификаторы вычищены, а `platform_icons.js`-тесты зелёные.
