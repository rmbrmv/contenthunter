# Реальные логотипы платформ (OP#92) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить эмодзи платформ в дашборде на реальные официальные логотипы (SVG), сведя 9 дублирующихся словарей иконок к единому реестру.

**Architecture:** Новый pure-модуль `public/platform_registry_pure.js` (UMD, как `search_select_pure.js`) — единый реестр 10 платформ + хелперы. Логотипы — встроенный SVG-`<symbol>` спрайт в `index.html`; хелпер `platformLogo()` рендерит `<svg><use href="#logo-…"/></svg>`. Существующие словари иконок переопределяются через `platformIconMap()` из реестра (минимальный диff, единый источник истины), call-site'ы не трогаем. В `<option>` остаётся эмодзи + текст.

**Tech Stack:** Статичный `public/index.html` (Tailwind CDN), pure-JS модули `public/*_pure.js`, тесты `node --test`.

**Worktree кода:** `/home/claude-user/op92-platform-logos` (ветка `op92-platform-logos` от `origin/main`). Все пути ниже — относительно него.

**Спека:** `docs/superpowers/specs/2026-06-05-platform-logos-design.md` (docs-репо).

---

## Файловая структура

- **Create** `public/platform_registry_pure.js` — реестр + хелперы (единственный источник истины).
- **Create** `tests/test_platform_registry_pure.test.js` — юнит-тесты хелперов + тест консистентности реестр↔спрайт.
- **Modify** `public/index.html` — (а) SVG-спрайт в начале `<body>`; (б) `<script src="/platform_registry_pure.js">`; (в) 9 определений словарей → `platformIconMap()`/`platformColorMap()`; (г) статичные эмодзи платформ (сайдбар, `<h1>`, бейдж-спаны) → `<svg><use>`; (д) 1 крупное место — явный размер.

---

### Task 1: Pure-модуль реестра платформ

**Files:**
- Create: `public/platform_registry_pure.js`
- Test: `tests/test_platform_registry_pure.test.js`

- [ ] **Step 1: Написать падающий тест хелперов**

Create `tests/test_platform_registry_pure.test.js`:

```js
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  PLATFORMS, platformLogo, platformName, platformBadge, platformEmoji,
  platformIconMap, platformColorMap,
} = require('../public/platform_registry_pure');

test('реестр содержит все 10 платформ', () => {
  const expected = ['instagram','youtube','tiktok','pinterest','likee','vk','rutube','dzen','threads','wibes'];
  assert.deepEqual(Object.keys(PLATFORMS).sort(), expected.slice().sort());
});

test('platformLogo: даёт <use href="#logo-…"> по нормализованному ключу', () => {
  assert.match(platformLogo('instagram'), /href="#logo-instagram"/);
  assert.match(platformLogo('Instagram'), /href="#logo-instagram"/); // регистронезависимо
  assert.match(platformLogo('  YouTube '), /href="#logo-youtube"/);  // trim
  assert.match(platformLogo('tiktok'), /class="w-4 h-4/);             // дефолтный размер
  assert.match(platformLogo('tiktok', 'w-6 h-6'), /class="w-6 h-6/); // кастомный размер
});

test('platformLogo: неизвестный ключ → logo-generic', () => {
  assert.match(platformLogo('myspace'), /href="#logo-generic"/);
  assert.match(platformLogo(''), /href="#logo-generic"/);
  assert.match(platformLogo(null), /href="#logo-generic"/);
});

test('platformName / platformBadge / platformEmoji: значения и фолбэки', () => {
  assert.equal(platformName('vk'), 'VK');
  assert.equal(platformName('unknownnet'), 'unknownnet'); // сырой ключ как фолбэк
  assert.equal(platformBadge('instagram'), 'bg-pink-50 text-pink-700');
  assert.equal(platformBadge('nope'), 'bg-gray-100 text-gray-700');
  assert.equal(platformEmoji('tiktok'), '🎵');
  assert.equal(platformEmoji('nope'), '');
});

test('platformIconMap: оба регистра ключей → одинаковый SVG; неизвестный отсутствует', () => {
  const m = platformIconMap();
  assert.match(m['instagram'], /href="#logo-instagram"/);
  assert.match(m['Instagram'], /href="#logo-instagram"/);
  assert.equal(m['myspace'], undefined); // фолбэк `|| '—'` на call-site сохраняется
});

test('platformColorMap: оба регистра ключей', () => {
  const c = platformColorMap();
  assert.equal(c['youtube'], 'bg-red-50 text-red-700');
  assert.equal(c['YouTube'], 'bg-red-50 text-red-700');
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd /home/claude-user/op92-platform-logos && node --test --test-force-exit tests/test_platform_registry_pure.test.js`
Expected: FAIL — `Cannot find module '../public/platform_registry_pure'`.

- [ ] **Step 3: Написать модуль**

Create `public/platform_registry_pure.js`:

```js
'use strict';
(function (root) {
  // Единый источник истины по платформам. sym = id <symbol> в SVG-спрайте index.html.
  const PLATFORMS = {
    instagram: { name: 'Instagram', sym: 'logo-instagram', emoji: '📸', badge: 'bg-pink-50 text-pink-700' },
    youtube:   { name: 'YouTube',   sym: 'logo-youtube',   emoji: '▶️', badge: 'bg-red-50 text-red-700' },
    tiktok:    { name: 'TikTok',    sym: 'logo-tiktok',    emoji: '🎵', badge: 'bg-gray-100 text-gray-700' },
    pinterest: { name: 'Pinterest', sym: 'logo-pinterest', emoji: '📌', badge: 'bg-red-50 text-red-700' },
    likee:     { name: 'Likee',     sym: 'logo-likee',     emoji: '❤️', badge: 'bg-cyan-50 text-cyan-700' },
    vk:        { name: 'VK',        sym: 'logo-vk',        emoji: '🔵', badge: 'bg-blue-50 text-blue-700' },
    rutube:    { name: 'Rutube',    sym: 'logo-rutube',    emoji: '🎬', badge: 'bg-gray-100 text-gray-700' },
    dzen:      { name: 'Dzen',      sym: 'logo-dzen',      emoji: '🟡', badge: 'bg-gray-100 text-gray-700' },
    threads:   { name: 'Threads',   sym: 'logo-threads',   emoji: '🧵', badge: 'bg-gray-100 text-gray-700' },
    wibes:     { name: 'Wibes',     sym: 'logo-wibes',     emoji: '🌊', badge: 'bg-cyan-50 text-cyan-700' },
  };
  const GENERIC_SYM = 'logo-generic';

  function _key(k) { return String(k == null ? '' : k).trim().toLowerCase(); }
  function _entry(k) { return PLATFORMS[_key(k)] || null; }

  function platformLogo(key, sizeClass) {
    const cls = sizeClass || 'w-4 h-4';
    const e = _entry(key);
    const sym = e ? e.sym : GENERIC_SYM;
    return `<svg class="${cls} inline-block align-[-0.125em]" aria-hidden="true"><use href="#${sym}"></use></svg>`;
  }
  function platformName(key) {
    const e = _entry(key);
    return e ? e.name : (key == null ? '' : String(key));
  }
  function platformBadge(key) {
    const e = _entry(key);
    return e ? e.badge : 'bg-gray-100 text-gray-700';
  }
  function platformEmoji(key) {
    const e = _entry(key);
    return e ? e.emoji : '';
  }
  function platformLogoLabel(key, sizeClass) {
    return `${platformLogo(key, sizeClass)} ${platformName(key)}`;
  }
  // Совместимость: легаси-словари в index.html переопределяются через эти билдеры,
  // чтобы единственным источником истины оставался реестр. Ключи в ОБОИХ регистрах —
  // call-site'ы передают и 'instagram', и 'Instagram'.
  function platformIconMap(sizeClass) {
    const m = {};
    for (const k of Object.keys(PLATFORMS)) {
      const svg = platformLogo(k, sizeClass);
      m[k] = svg;
      m[PLATFORMS[k].name] = svg;
    }
    return m;
  }
  function platformColorMap() {
    const m = {};
    for (const k of Object.keys(PLATFORMS)) {
      m[k] = PLATFORMS[k].badge;
      m[PLATFORMS[k].name] = PLATFORMS[k].badge;
    }
    return m;
  }

  const api = {
    PLATFORMS, platformLogo, platformName, platformBadge, platformEmoji,
    platformLogoLabel, platformIconMap, platformColorMap,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') Object.assign(window, api);
})(typeof globalThis !== 'undefined' ? globalThis : this);
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `node --test --test-force-exit tests/test_platform_registry_pure.test.js`
Expected: PASS (6 тестов).

- [ ] **Step 5: Commit**

```bash
cd /home/claude-user/op92-platform-logos
git add public/platform_registry_pure.js tests/test_platform_registry_pure.test.js
git commit -m "feat(op92): единый реестр платформ platform_registry_pure.js + тесты"
```

---

### Task 2: SVG-спрайт логотипов в index.html + подключение модуля

**Files:**
- Modify: `public/index.html` (вставка спрайта после открывающего `<body>`; добавить `<script src>` рядом с другими `/*.js` ~строка 24)

- [ ] **Step 1: Подключить модуль**

Найти блок локальных скриптов (рядом со строкой `<script src="/search_select.js"></script>`, ~24) и добавить после него:

```html
  <script src="/platform_registry_pure.js"></script>
```

- [ ] **Step 2: Вставить SVG-спрайт сразу после `<body…>`**

Найти открывающий `<body …>` и вставить первым дочерним элементом скрытый спрайт. Пути логотипов — официальные бренд-SVG (simple-icons) с фирменными `fill`; для платформ вне simple-icons (rutube/dzen/likee/wibes) — фирменно-цветной леттермарк; `logo-generic` — нейтральный фолбэк.

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

    <symbol id="logo-instagram" viewBox="0 0 24 24">
      <path fill="url(#ig-grad)" d="M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077"/>
    </symbol>

    <symbol id="logo-youtube" viewBox="0 0 24 24">
      <path fill="#FF0000" d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
    </symbol>

    <symbol id="logo-tiktok" viewBox="0 0 24 24">
      <path fill="#000000" d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/>
    </symbol>

    <symbol id="logo-pinterest" viewBox="0 0 24 24">
      <path fill="#BD081C" d="M12.017 0C5.396 0 .029 5.367.029 11.987c0 5.079 3.158 9.417 7.618 11.162-.105-.949-.199-2.403.041-3.439.219-.937 1.406-5.957 1.406-5.957s-.359-.72-.359-1.781c0-1.663.967-2.911 2.168-2.911 1.024 0 1.518.769 1.518 1.688 0 1.029-.653 2.567-.992 3.992-.285 1.193.6 2.165 1.775 2.165 2.128 0 3.768-2.245 3.768-5.487 0-2.861-2.063-4.869-5.008-4.869-3.41 0-5.409 2.562-5.409 5.199 0 1.033.394 2.143.889 2.741.099.12.112.225.085.345-.09.375-.293 1.199-.334 1.363-.053.225-.172.271-.401.165-1.495-.69-2.433-2.878-2.433-4.646 0-3.776 2.748-7.252 7.92-7.252 4.158 0 7.392 2.967 7.392 6.923 0 4.135-2.607 7.462-6.233 7.462-1.214 0-2.354-.629-2.758-1.379l-.749 2.848c-.269 1.045-1.004 2.352-1.498 3.146 1.123.345 2.306.535 3.55.535 6.607 0 11.985-5.365 11.985-11.987C23.97 5.39 18.592.026 11.985.026L12.017 0z"/>
    </symbol>

    <symbol id="logo-vk" viewBox="0 0 24 24">
      <path fill="#0077FF" d="m9.489.004.729-.003h3.564l.73.003.914.01.433.007.418.011.403.014.388.016.374.021.36.025.345.03.333.033c1.74.196 2.933.616 3.833 1.516.9.9 1.32 2.092 1.516 3.833l.034.333.029.346.025.36.02.373.025.588.012.41.013.644.009.915.004.98-.001 3.313-.003.73-.01.914-.007.433-.011.418-.014.403-.016.388-.021.374-.025.36-.03.345-.033.333c-.196 1.74-.616 2.933-1.516 3.833-.9.9-2.092 1.32-3.833 1.516l-.333.034-.346.029-.36.025-.373.02-.588.025-.41.012-.644.013-.915.009-.98.004-3.313-.001-.73-.003-.914-.01-.433-.007-.418-.011-.403-.014-.388-.016-.374-.021-.36-.025-.345-.03-.333-.033c-1.74-.196-2.933-.616-3.833-1.516-.9-.9-1.32-2.092-1.516-3.833l-.034-.333-.029-.346-.025-.36-.02-.373-.025-.588-.012-.41-.013-.644-.009-.915-.004-.98.001-3.313.003-.73.01-.914.007-.433.011-.418.014-.403.016-.388.021-.374.025-.36.03-.345.033-.333c.196-1.74.616-2.933 1.516-3.833.9-.9 2.092-1.32 3.833-1.516l.333-.034.346-.029.36-.025.373-.02.588-.025.41-.012.644-.013.915-.009ZM6.79 7.3H4.05c.13 6.24 3.25 9.99 8.72 9.99h.31v-3.57c2.01.2 3.53 1.67 4.14 3.57h2.84c-.78-2.84-2.83-4.41-4.11-5.01 1.28-.74 3.08-2.54 3.51-4.98h-2.58c-.56 1.98-2.22 3.78-3.8 3.95V7.3H10.5v6.92c-1.6-.4-3.62-2.34-3.71-6.92Z"/>
    </symbol>

    <symbol id="logo-threads" viewBox="0 0 24 24">
      <path fill="#000000" d="M12.186 24h-.007c-3.581-.024-6.334-1.205-8.184-3.509C2.35 18.44 1.5 15.586 1.472 12.01v-.017c.03-3.579.879-6.43 2.525-8.482C5.845 1.205 8.6.024 12.18 0h.014c2.746.02 5.043.725 6.826 2.098 1.677 1.29 2.858 3.13 3.509 5.467l-2.04.569c-1.104-3.96-3.898-5.984-8.304-6.015-2.91.022-5.11.936-6.54 2.717C4.307 6.504 3.616 8.914 3.589 12c.027 3.086.718 5.496 2.057 7.164 1.43 1.783 3.631 2.698 6.54 2.717 2.623-.02 4.358-.631 5.8-2.045 1.647-1.613 1.618-3.593 1.09-4.798-.31-.71-.873-1.3-1.634-1.75-.192 1.352-.622 2.446-1.284 3.272-.886 1.102-2.14 1.704-3.73 1.79-1.202.065-2.361-.218-3.259-.801-1.063-.689-1.685-1.74-1.752-2.964-.065-1.19.408-2.285 1.33-3.082.88-.76 2.119-1.207 3.583-1.291a13.853 13.853 0 0 1 3.02.142c-.126-.742-.375-1.332-.75-1.757-.513-.586-1.308-.883-2.359-.89h-.029c-.844 0-1.992.232-2.721 1.32L7.734 7.847c.98-1.454 2.568-2.256 4.478-2.256h.044c3.194.02 5.097 1.975 5.287 5.388.108.046.216.094.321.142 1.49.7 2.58 1.761 3.154 3.07.797 1.82.871 4.79-1.548 7.158-1.85 1.81-4.094 2.628-7.277 2.65Zm1.003-11.69c-.242 0-.487.007-.739.021-1.836.103-2.98.946-2.916 2.143.067 1.256 1.452 1.839 2.784 1.767 1.224-.065 2.818-.543 3.086-3.71a10.5 10.5 0 0 0-2.215-.221z"/>
    </symbol>

    <!-- Вне simple-icons: фирменно-цветные леттермарки/глифы. -->
    <symbol id="logo-rutube" viewBox="0 0 24 24">
      <rect width="24" height="24" rx="6" fill="#000000"/>
      <path fill="#ffffff" d="M9 7.5v9l8-4.5z"/>
    </symbol>
    <symbol id="logo-dzen" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="12" fill="#000000"/>
      <text x="12" y="12" text-anchor="middle" dominant-baseline="central" fill="#ffffff" font-family="Arial, sans-serif" font-weight="700" font-size="13">Д</text>
    </symbol>
    <symbol id="logo-likee" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="12" fill="#1EC8C8"/>
      <text x="12" y="12" text-anchor="middle" dominant-baseline="central" fill="#ffffff" font-family="Arial, sans-serif" font-weight="700" font-size="13">L</text>
    </symbol>
    <symbol id="logo-wibes" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="12" fill="#00A0E9"/>
      <text x="12" y="12" text-anchor="middle" dominant-baseline="central" fill="#ffffff" font-family="Arial, sans-serif" font-weight="700" font-size="13">W</text>
    </symbol>
    <symbol id="logo-generic" viewBox="0 0 24 24">
      <rect width="24" height="24" rx="6" fill="#9CA3AF"/>
      <circle cx="12" cy="12" r="4.5" fill="#ffffff"/>
    </symbol>
  </svg>
```

- [ ] **Step 3: Проверить, что страница парсится и спрайт виден браузеру (визуальный смоук)**

Run (синтаксис/сервер не падает):
```bash
node -e "require('fs').readFileSync('public/index.html','utf8'); console.log('html readable')"
node --check server.js && echo "server.js OK"
```
Затем визуально: открыть дашборд (или локально `node server.js` если окружение позволяет) и убедиться, что в DevTools есть `#logo-instagram`. На этом шаге UI ещё показывает эмодзи — спрайт лишь подготовлен.

- [ ] **Step 4: Commit**

```bash
git add public/index.html
git commit -m "feat(op92): SVG-спрайт логотипов платформ + подключение реестра"
```

---

### Task 3: Тест консистентности реестр ↔ спрайт

**Files:**
- Modify: `tests/test_platform_registry_pure.test.js` (добавить тест в конец)

- [ ] **Step 1: Дописать падающий тест**

Добавить в конец `tests/test_platform_registry_pure.test.js`:

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

- [ ] **Step 2: Запустить — проходит (спрайт уже добавлен в Task 2)**

Run: `node --test --test-force-exit tests/test_platform_registry_pure.test.js`
Expected: PASS (8 тестов). Если падает на отсутствии `<symbol>` — вернуться к Task 2 Step 2.

- [ ] **Step 3: Commit**

```bash
git add tests/test_platform_registry_pure.test.js
git commit -m "test(op92): консистентность реестр↔спрайт + подключение скрипта"
```

---

### Task 4: Переопределить словари иконок через реестр

**Files:**
- Modify: `public/index.html` — 9 определений словарей (строки приблизительны, искать по содержимому):
  - `platformIcons = { … }` ×4 (≈4400, 4636, 7112 — Capitalized; ≈5956 — lowercase)
  - `PLATFORM_ICON = { … }` (≈4924)
  - `_platformIcons = { … }` (≈6821) и `_platformColors = { … }` (≈6822)
  - `LC_PLAT = { … }` (≈7373)
  - `_ptPlatformIcon = { … }` (≈7813)
  - `PQ_PLATFORM_ICON = { … }` (≈11247)
  - `UP_PLATFORM_ICON = { … }` (≈11415)

Принцип: значение словаря (эмодзи) → результат `platformIconMap()` (SVG, оба регистра ключей). Call-site'ы (`${map[x] || '—'}`) НЕ трогаем — для известных платформ вернётся SVG, для неизвестных `undefined` → старый фолбэк сохранится. `_platformColors` → `platformColorMap()`.

- [ ] **Step 1: Заменить каждое определение**

Применить замены (сохраняя `const`/отступы и `let`-vs-`const` как в оригинале):

```
// было →  стало
const platformIcons = { Instagram: '📸', TikTok: '🎵', YouTube: '▶️' };
const platformIcons = platformIconMap();

const platformIcons = { instagram: '📸', tiktok: '🎵', youtube: '▶️' };
const platformIcons = platformIconMap();

const PLATFORM_ICON = { instagram: '📸', tiktok: '🎵', youtube: '▶️' };
const PLATFORM_ICON = platformIconMap();

const _platformIcons = { instagram: '📸', tiktok: '🎵', youtube: '▶️' };
const _platformIcons = platformIconMap();

const _platformColors = { instagram: 'bg-pink-50 text-pink-700', tiktok: 'bg-gray-100 text-gray-700', youtube: 'bg-red-50 text-red-700' };
const _platformColors = platformColorMap();

const LC_PLAT = { tiktok:'🎵', instagram:'📸', youtube:'▶️' };
const LC_PLAT = platformIconMap();

const _ptPlatformIcon = { Instagram:'📸', TikTok:'🎵', YouTube:'▶️' };
const _ptPlatformIcon = platformIconMap();

const PQ_PLATFORM_ICON = { instagram: '📸', tiktok: '🎵', youtube: '▶️' };
const PQ_PLATFORM_ICON = platformIconMap();

const UP_PLATFORM_ICON = { instagram:'📸', tiktok:'🎵', youtube:'▶️' };
const UP_PLATFORM_ICON = platformIconMap();
```

Для 3 локальных дублей `const platformIcons = …` (внутри функций) — те же замены; глобальные/локальные не конфликтуют (как и раньше — локальный шадоуит глобальный).

ВНИМАНИЕ: `platformIconMap` вызывается в момент инициализации каждого `const`. Поскольку `<script src="/platform_registry_pure.js">` подключён ДО inline-скрипта (он в `<head>`/верх `<body>`, см. Task 2 Step 1), функции уже определены. Глобальные `const platformIcons` на верхнем уровне inline-скрипта тоже выполнятся после загрузки внешнего скрипта (тот же порядок DOM). Проверка — в Step 2.

- [ ] **Step 2: Проверить, что не осталось эмодзи-литералов в словарях и приложение грузится**

Run:
```bash
grep -nE "(platformIcons|PLATFORM_ICON|_platformIcons|LC_PLAT|_ptPlatformIcon|PQ_PLATFORM_ICON|UP_PLATFORM_ICON) *= *\{ *[A-Za-z]" public/index.html || echo "OK: словарей-литералов не осталось"
node --check server.js && echo "server.js OK"
```
Expected: «OK: словарей-литералов не осталось».
Визуально: открыть таблицы (Контент, Аккаунты, Очередь публикаций, Ручная выкладка) — в колонке «Платформа»/бейджах должны быть реальные логотипы, не эмодзи.

- [ ] **Step 3: Commit**

```bash
git add public/index.html
git commit -m "feat(op92): словари иконок платформ → реестр platformIconMap/platformColorMap"
```

---

### Task 5: Статичные эмодзи платформ → SVG (сайдбар, заголовки, бейдж-спаны)

**Files:**
- Modify: `public/index.html` — сайдбар-нав (≈311/314/317), бейдж-спаны (≈2851/2855/2859), `<h1>` страниц (≈3544/3635/3726)

Заменяем ТОЛЬКО эмодзи, идентифицирующие конкретную платформу. `<option>`, `📸 Соцсети` (заголовок секции, ≈309), `📸 По дням` (≈4071) — НЕ трогаем (см. Task 6 / спека «Что НЕ трогаем»).

- [ ] **Step 1: Сайдбар-навигация**

```
// было → стало
      <span>📸</span> Instagram
      <span class="inline-flex"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-instagram"></use></svg></span> Instagram

      <span>🎵</span> TikTok
      <span class="inline-flex"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-tiktok"></use></svg></span> TikTok

      <span>▶️</span> YouTube
      <span class="inline-flex"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-youtube"></use></svg></span> YouTube
```

- [ ] **Step 2: Бейдж-спаны выбора аккаунта (≈2851/2855/2859)**

```
// было → стало
              <span class="text-sm text-gray-700">📸 Instagram</span>
              <span class="text-sm text-gray-700"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-instagram"></use></svg> Instagram</span>

              <span class="text-sm text-gray-700">🎵 TikTok</span>
              <span class="text-sm text-gray-700"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-tiktok"></use></svg> TikTok</span>

              <span class="text-sm text-gray-700">▶️ YouTube</span>
              <span class="text-sm text-gray-700"><svg class="w-4 h-4 inline-block align-[-0.125em]" aria-hidden="true"><use href="#logo-youtube"></use></svg> YouTube</span>
```

- [ ] **Step 3: Заголовки страниц `<h1>` (≈3544/3635/3726)** — крупный размер (`w-7 h-7`)

```
// было → стало
      <h1 class="text-2xl font-bold text-gray-900">📸 Instagram</h1>
      <h1 class="text-2xl font-bold text-gray-900"><svg class="w-7 h-7 inline-block align-[-0.15em]" aria-hidden="true"><use href="#logo-instagram"></use></svg> Instagram</h1>

      <h1 class="text-2xl font-bold text-gray-900">🎵 TikTok</h1>
      <h1 class="text-2xl font-bold text-gray-900"><svg class="w-7 h-7 inline-block align-[-0.15em]" aria-hidden="true"><use href="#logo-tiktok"></use></svg> TikTok</h1>

      <h1 class="text-2xl font-bold text-gray-900">▶️ YouTube</h1>
      <h1 class="text-2xl font-bold text-gray-900"><svg class="w-7 h-7 inline-block align-[-0.15em]" aria-hidden="true"><use href="#logo-youtube"></use></svg> YouTube</h1>
```

- [ ] **Step 4: Проверить, что не осталось целевых статичных эмодзи**

Run:
```bash
grep -nE "<span>(📸|🎵|▶️)</span>" public/index.html || echo "OK: сайдбар чист"
grep -nE "text-sm text-gray-700\">(📸|🎵|▶️)" public/index.html || echo "OK: бейдж-спаны чисты"
grep -nE "<h1[^>]*>(📸|🎵|▶️)" public/index.html || echo "OK: h1 чисты"
```
Expected: три «OK». Визуально: сайдбар + страницы IG/TikTok/YouTube + модалка выбора аккаунта.

- [ ] **Step 5: Commit**

```bash
git add public/index.html
git commit -m "feat(op92): статичные эмодзи платформ (сайдбар/h1/бейджи) → SVG-логотипы"
```

---

### Task 6: Крупное место + проверка текста в `<option>`

**Files:**
- Modify: `public/index.html` — крупный спан (≈4653); `<option>`-списки (проверка)

- [ ] **Step 1: Крупная иконка в карточке (≈4653)**

```
// было → стало
        <span class="text-2xl">${platformIcons[p.platform] || '📋'}</span>
        <span class="inline-flex">${(typeof platformLogo==='function' && PLATFORMS[String(p.platform||'').toLowerCase()]) ? platformLogo(p.platform, 'w-6 h-6') : '📋'}</span>
```
(Иначе `platformIcons[p.platform]` вернёт SVG дефолтного размера w-4 в `text-2xl`-спане — иконка будет мелкой.)

- [ ] **Step 2: Убедиться, что во всех `<option>` есть текст имени платформы**

`<option>` оставляем с эмодзи (браузер не рендерит SVG внутри option), но текст имени обязателен. Проверка, что нет option только с эмодзи без названия:

Run:
```bash
grep -nE "<option value=\"[^\"]+\">(📸|🎵|▶️|📌|❤️|🔵|🎬|🟡|🧵|🌊|📷) *</option>" public/index.html || echo "OK: все option с текстом"
```
Expected: «OK: все option с текстом» (в текущем коде все option уже содержат название — это подтверждающая проверка; если что-то найдено — дописать текст имени после эмодзи).

- [ ] **Step 3: Commit (если были правки)**

```bash
git add public/index.html
git commit -m "feat(op92): крупная иконка карточки через platformLogo + проверка текста option"
```

---

### Task 7: Финальная проверка и интеграция

- [ ] **Step 1: Полный прогон тестов модуля**

Run: `node --test --test-force-exit tests/test_platform_registry_pure.test.js`
Expected: PASS (8 тестов).

- [ ] **Step 2: Регрессия — смежные pure-тесты не сломаны**

Run: `node --test --test-force-exit tests/test_search_select_pure.test.js tests/test_publish_limits.test.js 2>&1 | tail -5` (либо доступный курируемый non-live набор; полный сьют требует живую БД).
Expected: без новых падений.

- [ ] **Step 3: Не осталось эмодзи-логотипов платформ в целевых местах**

Run:
```bash
grep -nE "= *\{ *(Instagram|instagram|tiktok|TikTok)['\"]?: *['\"](📸|🎵|▶️)" public/index.html || echo "OK: словари переведены"
grep -nE "<span>(📸|🎵|▶️)</span>" public/index.html || echo "OK: сайдбар"
```
Expected: оба «OK».

- [ ] **Step 4: Ручная визуальная приёмка (чеклист для Данила)**

Открыть прод/локально и проверить реальные логотипы (не эмодзи) на: сайдбар-нав (IG/TikTok/YouTube), заголовки страниц IG/TikTok/YouTube, таблицы «Контент»/«Аккаунты»/«Очередь публикаций»/«Ручная выкладка» (колонка платформа + бейджи), карточка задачи (крупная иконка), модалка выбора аккаунта. Выпадашки — эмодзи + текст (ожидаемо).

- [ ] **Step 5: Push + интеграция**

Использовать `superpowers:finishing-a-development-branch`. Ветка `op92-platform-logos` → PR/мердж в `main` (delivery-contenthunter). Деплой: прод-autowarm `git pull` (статика; PM2-restart не требуется). Доки-PR (спека+план) — в docs-репо (rmbrmv/contenthunter).

---

## Self-Review (выполнено автором плана)

- **Покрытие спеки:** реестр+хелперы (T1), спрайт+подключение (T2), тест консистентности (T3), 9 словарей (T4), статичные эмодзи (T5), крупное место + текст option (T6), не-платформенные эмодзи/Telegram/server.js — явно вне скоупа. ✔
- **Плейсхолдеры:** реальные `path d` для 6 simple-icons лого вшиты; для 4 без simple-icons — конкретные леттермарк-`<symbol>`. ✔
- **Консистентность типов:** `platformLogo/platformName/platformBadge/platformIconMap/platformColorMap/PLATFORMS` — имена совпадают между модулем (T1), тестами (T1/T3) и заменами (T4/T6). ✔
- **Отклонение от спеки (осознанное):** спека предполагала удаление словарей и правку call-site'ов; план переопределяет словари через `platformIconMap()` — тот же единый источник истины (реестр), но ~9 правок вместо ~16 call-site'ов → ниже риск регрессий в 12k-строчном файле. Поведение фолбэков сохранено.
