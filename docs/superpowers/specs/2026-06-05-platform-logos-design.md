# OP#92 — Реальные логотипы платформ в дашборде

**Дата:** 2026-06-05
**OpenProject:** WP#92 «Обновить иконки платформ»
**Репозиторий кода:** `delivery-contenthunter` (ветка `op92-platform-logos`)
**Файлы:** `public/index.html`, `public/platform_registry_pure.js` (новый), `tests/test_platform_registry_pure.test.js` (новый)

## Проблема

В интерфейсе дашборда платформы (Instagram, TikTok, YouTube, …) обозначены **эмодзи** (`📸 🎵 ▶️`). Данил просит **реальные официальные логотипы** платформ.

Текущее состояние:
- Эмодзи платформ разбросаны по ~30+ местам `public/index.html`.
- **7 дублирующихся JS-словарей** иконок: `platformIcons` (несколько определений), `PLATFORM_ICON`, `_platformIcons`, `_ptPlatformIcon`, `LC_PLAT`, `PQ_PLATFORM_ICON`, `UP_PLATFORM_ICON`. Часть с заглавными ключами (`Instagram`), часть со строчными + `.toLowerCase()`.
- Рядом `_platformColors` — цветовые классы бейджей.
- Три контекста вставки: (а) JS-шаблоны `${map[x]}` → в `<td>/<span>`; (б) статичный HTML (`<h1>`, сайдбар-нав, `<th>`, одиночные `<span>`); (в) `<option>` в `<select>`.

## Решения (утверждено Данилом)

1. **Стиль:** официальные **цветные** логотипы (IG-градиент, красный YouTube и т.д.).
2. **Охват:** все 10 платформ из описания — Instagram, YouTube, TikTok, Pinterest, Likee, VK, Rutube, Dzen, Threads, Wibes — единым реестром (на будущее, даже если часть пока не отображается в UI).
3. **Подход:** встроенный SVG-спрайт + единый реестр (вариант A).
4. **`<option>`:** оставляем эмодзи (браузер не рендерит SVG/img внутри нативного `<option>`), но **обязательно** с текстовой подписью названия платформы рядом (`📸 Instagram`).

## Архитектура

### 1. Единый реестр: `public/platform_registry_pure.js`

Новый pure-модуль по конвенции репо (UMD-IIFE, как `search_select_pure.js` / `mpq_pure.js`): экспорт в `module.exports` для node-тестов и в `window` для браузера.

```js
const PLATFORMS = {
  instagram: { name:'Instagram', sym:'logo-instagram', emoji:'📸', badge:'bg-pink-50 text-pink-700' },
  youtube:   { name:'YouTube',   sym:'logo-youtube',   emoji:'▶️', badge:'bg-red-50 text-red-700' },
  tiktok:    { name:'TikTok',    sym:'logo-tiktok',    emoji:'🎵', badge:'bg-gray-100 text-gray-700' },
  pinterest: { name:'Pinterest', sym:'logo-pinterest', emoji:'📌', badge:'bg-red-50 text-red-700' },
  likee:     { name:'Likee',     sym:'logo-likee',     emoji:'❤️', badge:'bg-yellow-50 text-yellow-700' },
  vk:        { name:'VK',        sym:'logo-vk',        emoji:'🔵', badge:'bg-blue-50 text-blue-700' },
  rutube:    { name:'Rutube',    sym:'logo-rutube',    emoji:'🎬', badge:'bg-gray-100 text-gray-700' },
  dzen:      { name:'Dzen',      sym:'logo-dzen',      emoji:'🟡', badge:'bg-yellow-50 text-yellow-700' },
  threads:   { name:'Threads',   sym:'logo-threads',   emoji:'🧵', badge:'bg-gray-100 text-gray-700' },
  wibes:     { name:'Wibes',     sym:'logo-wibes',     emoji:'🌊', badge:'bg-cyan-50 text-cyan-700' },
};
```

Хелперы (нормализуют ключ через `String(k||'').trim().toLowerCase()`):

- `platformLogo(key, sizeClass='w-4 h-4')` → строка `<svg class="${sizeClass} inline-block align-middle" aria-hidden="true"><use href="#logo-…"/></svg>`; неизвестный ключ → `logo-generic` (нейтральный значок).
- `platformName(key)` → отображаемое имя (или сырой ключ как фолбэк).
- `platformBadge(key)` → классы бейджа (или `bg-gray-100 text-gray-700`).
- `platformLogoLabel(key)` → `platformLogo(key) + ' ' + platformName(key)` для удобства частых мест «иконка + имя».

`emoji` хранится в реестре, чтобы `<option>`-места и Telegram-словари при желании брали значок из одного источника.

### 2. SVG-спрайт в `public/index.html`

Один скрытый блок в начале `<body>`:

```html
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <linearGradient id="ig-gradient" ...>...</linearGradient>
  </defs>
  <symbol id="logo-instagram" viewBox="0 0 24 24">…</symbol>
  <symbol id="logo-youtube"   viewBox="0 0 24 24">…</symbol>
  …все 10 + logo-generic…
</svg>
```

Источник путей — официальные бренд-SVG (simple-icons в фирменных цветах; полноцвет/градиент для Instagram). Каждый `<symbol>` self-contained со своими `fill`.

Подключение модуля: `<script src="/platform_registry_pure.js">` рядом с прочими `/*.js`.

### 3. Миграция существующих мест

| Контекст | Было | Стало |
|----------|------|-------|
| 7 JS-словарей | `${platformIcons[x] \|\| '—'}` | удалить словари; `${platformLogo(x)}` (фолбэк внутри хелпера) |
| Бейджи `${_platformIcons[x]} ${x}` | эмодзи + имя | `${platformLogo(x)} ${platformName(x)}`, классы через `platformBadge` |
| Статичный HTML (`<h1>`, сайдбар, `<th>`, `<span>`) | `📸 Instagram` | `<svg><use href="#logo-instagram"/></svg> Instagram` |
| `<option>` в `<select>` | `📸 Instagram` / только `📸` | эмодзи **+ гарантированный текст** имени: `📸 Instagram` |

`_platformColors` сводится в `platformBadge`.

### 4. Что НЕ трогаем

- Не-платформенные эмодзи: `❤️` (лайки), `🎬` (контент/запись), `🚀` (старт), `📊` (аудитория), `⚠️`/`❌`/`ℹ️` (статусы), `🎲`, `💬`, `➕`, `🏁`, `📋`, `📱`, `👤` и т.п. — это не логотипы платформ.
- Telegram-отчёты (`daily_publish_report.js`) — текстовый канал, SVG невозможен; эмодзи там уместны → вне скоупа.
- `server.js`, БД — без изменений.

### 5. Kill-switch

Не нужен — чисто презентационное изменение в статичных ассетах. Откат = `git revert`. Соответствует норме репо для UI-only задач (WP#239, коды роликов — без флага).

## Тестирование

`tests/test_platform_registry_pure.test.js` (node --test, без jsdom):

1. **Хелперы:** `platformLogo('instagram')` → содержит `href="#logo-instagram"`; регистронезависимость (`'Instagram'` == `'instagram'`); неизвестный ключ → `logo-generic`; `platformName`/`platformBadge` фолбэки.
2. **Полнота реестра:** присутствуют все 10 платформ.
3. **Консистентность реестр ↔ спрайт** (главный риск): читаем `public/index.html` как строку, regex-извлекаем все `id="logo-…"` из `<symbol>`; для каждого `sym` в `PLATFORMS` (+`logo-generic`) проверяем наличие соответствующего `<symbol>`.

Плюс ручная визуальная приёмка Данила по страницам (сайдбар, заголовки IG/TT/YT, таблицы, карточки дашборда, бейджи аккаунтов).

## Объём

- Новый файл: `public/platform_registry_pure.js`
- Новый тест: `tests/test_platform_registry_pure.test.js`
- Правки: `public/index.html` (спрайт + подключение скрипта + замена ~7 словарей и статичных эмодзи платформ)
- Без `server.js`, без миграций, без kill-switch.

## Деплой

`delivery-contenthunter` main → прод-autowarm `git pull` статики; PM2-restart не требуется (статичный ассет отдаётся express.static). Доки — отдельным PR в docs-репо (rmbrmv/contenthunter).
