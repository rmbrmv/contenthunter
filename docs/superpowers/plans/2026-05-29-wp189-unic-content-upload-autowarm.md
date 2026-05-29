# WP#189 (autowarm) — Механика загрузки контента уникализации — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Добавить кнопку «Загрузить контент» + модалку в раздел «Уникализация → Контент» РЕАЛЬНОГО приложения (autowarm, delivery.contenthunter.ru), которая грузит файлы в S3 и создаёт строки `validator_unic_content` в таксономии воркера.

**Контекст / почему переделка:** первая реализация (WP#189) была сделана в `validator-contenthunter` — там `UnicContentPage.vue` оказался осиротевшим (не подключён в роутер, tree-shake'ится). Живая страница `delivery.contenthunter.ru/#uniqualization/unic-content` обслуживается **autowarm** (Caddy → `localhost:3848` → `/root/.openclaw/workspace-genri/autowarm/server.js`, PM2 id35; фронт = `public/index.html`). Дизайн и маппинг — те же (см. spec `2026-05-29-wp189-unic-content-upload-design.md`); меняется только стек.

**Architecture:** autowarm = Node/Express `server.js` + статический `public/index.html` (vanilla JS, без сборки). У сервера НЕТ multer/aws-sdk и нельзя легко добавлять npm-зависимости в root-owned прод. Поэтому:
- **Приём файлов**: base64-в-JSON на отдельном `express.json({limit})` ТОЛЬКО на роуте upload (глобальный лимит 100KB не трогаем).
- **S3-загрузка**: переиспользуем boto3 (уже есть в `publisher_kernel.py`) через маленький Python-хелпер `unic_s3_upload.py`, в который `server.js` шеллит через `execFile`. Ноль новых npm-зависимостей.
- **Маппинг** «тип контента»→S3-папка/`content_type`/`label` вынесен в чистый JS-модуль `unic_upload_map.js` (юнит-тестируется через `node --test`, как принято в репо).

**Tech Stack:** Node 18+ (Express, pg `pool`, `child_process.execFile`, `crypto.randomUUID`), Python 3 + boto3 (S3), vanilla JS + Tailwind (index.html). Тесты: `node --test`.

**Репозиторий реализации:** `/home/claude-user/autowarm-wp189` (worktree, ветка `wp189-unic-content-upload`, origin = GenGo2/delivery-contenthunter). НЕ трогать `/home/claude-user/autowarm-testbench` (там чужая ветка).

**⚠️ Деплой-гоча:** прод autowarm = root-owned `/root/.openclaw/workspace-genri/autowarm` (PM2 id35 `autowarm`). Деплой = push origin/main → прод `git pull` (root) → `sudo pm2 restart autowarm`. `index.html` статичен (без сборки). Новых npm-зависимостей НЕТ — `npm install` на проде не требуется.

---

## File Structure

- **Create** `unic_upload_map.js` — чистый маппинг + helpers (resolveKind/validateExt/buildS3Key/nextSeq/buildLabel/DEFAULT_CHROMAKEY). Без БД/сети.
- **Create** `tests/test_unic_upload_map.test.js` — юнит-тесты модуля (`node --test`).
- **Create** `unic_s3_upload.py` — boto3-хелпер: локальный файл → `factory/<folder>/<uuid>.<ext>` на Beget S3 → печатает публичный URL.
- **Modify** `server.js` — `POST /api/unic-content/upload` (requireAuth, base64-JSON, decode→tmp→python→INSERT).
- **Modify** `public/index.html` — кнопка «Загрузить контент» + модалка `#unic-upload-modal` + JS (`openUnicUpload`/`submitUnicUpload`).

---

## Task 1: Чистый JS-модуль маппинга + юнит-тесты

**Files:**
- Create: `unic_upload_map.js`
- Test: `tests/test_unic_upload_map.test.js`

- [ ] **Step 1: Написать падающий тест** — `tests/test_unic_upload_map.test.js`:
```javascript
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const m = require('../unic_upload_map.js');

test('resolveKind maps to worker taxonomy', () => {
  const s = m.resolveKind('overlay_sounds');
  assert.strictEqual(s.folder, 'overlay_sounds');
  assert.strictEqual(s.contentType, 'audio');
  assert.strictEqual(s.labelPrefix, 'sounds');
  assert.deepStrictEqual(s.allowed, ['mp3']);
  assert.strictEqual(s.s3Mime, 'audio/mpeg');
  assert.strictEqual(m.resolveKind('overlay_video').contentType, 'video');
  assert.strictEqual(m.resolveKind('overlay_logo').contentType, 'image');
  assert.strictEqual(m.resolveKind('overlay_logo').labelPrefix, 'logo');
});

test('resolveKind throws on unknown', () => {
  assert.throws(() => m.resolveKind('nope'), /Неизвестный тип/);
});

test('validateExt ok and bad', () => {
  assert.strictEqual(m.validateExt('overlay_sounds', 'track.MP3'), 'mp3');
  assert.throws(() => m.validateExt('overlay_sounds', 'track.wav'), /не поддерживается/);
  assert.throws(() => m.validateExt('overlay_sounds', 'noext'), /без расширения/);
});

test('validateExt blocks svg for logo and pattern', () => {
  for (const k of ['overlay_logo', 'overlay_pattern']) {
    assert.throws(() => m.validateExt(k, 'icon.svg'), /SVG/);
  }
});

test('validateExt system allows any', () => {
  assert.strictEqual(m.validateExt('system', 'Status_Success_Icon.svg'), 'svg');
  assert.strictEqual(m.validateExt('system', 'thing.bin'), 'bin');
});

test('nextSeq and buildLabel', () => {
  const labels = ['sounds_0_1', 'sounds_0_2', 'sounds_0_10', 'other_0_5'];
  assert.strictEqual(m.nextSeq(labels, 'sounds', 0), 11);
  assert.strictEqual(m.nextSeq([], 'sounds', 0), 1);
  assert.strictEqual(m.buildLabel('sounds', 0, 11), 'sounds_0_11');
  assert.strictEqual(m.buildLabel('system', 0, 1), 'system');
});

test('nextSeq does not match shorter prefix', () => {
  assert.strictEqual(m.nextSeq(['sounds_0_3'], 'sound', 0), 1);
});

test('buildS3Key shape', () => {
  const k = m.buildS3Key('overlay_video', 'mp4');
  assert.ok(k.startsWith('factory/overlay_video/'));
  assert.ok(k.endsWith('.mp4'));
});
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd /home/claude-user/autowarm-wp189 && node --test --test-force-exit tests/test_unic_upload_map.test.js`
Expected: FAIL (Cannot find module '../unic_upload_map.js').

- [ ] **Step 3: Реализовать** — `unic_upload_map.js`:
```javascript
'use strict';
/**
 * Маппинг «тип контента» (UI) → S3-папка / БД-таксономия для validator_unic_content.
 * Значения content_kind (overlay_sounds/...) — это имена S3-папок factory/<kind>/, НЕ
 * значения колонки content_type. Воркер unic-worker фильтрует по content_type
 * (audio/application/image/video) + label LIKE 'logo%'/'pattern%'. Чтобы файл встроился
 * в уникализацию, строка пишется в правильной таксономии через этот модуль.
 */
const crypto = require('crypto');

// content_kind -> { folder, contentType, labelPrefix, allowed[], s3Mime }
const CONTENT_KIND_MAP = {
  overlay_sounds:  { folder: 'overlay_sounds',  contentType: 'audio',       labelPrefix: 'sounds',  allowed: ['mp3'],         s3Mime: 'audio/mpeg' },
  overlay_fonts:   { folder: 'overlay_fonts',   contentType: 'application', labelPrefix: 'fonts',   allowed: ['ttf', 'otf'],  s3Mime: 'application/octet-stream' },
  overlay_pattern: { folder: 'overlay_pattern', contentType: 'image',       labelPrefix: 'pattern', allowed: ['png'],         s3Mime: 'image/png' },
  overlay_logo:    { folder: 'overlay_logo',    contentType: 'image',       labelPrefix: 'logo',    allowed: ['png'],         s3Mime: 'image/png' },
  overlay_video:   { folder: 'overlay_video',   contentType: 'video',       labelPrefix: 'video',   allowed: ['mp4'],         s3Mime: 'video/mp4' },
  system:          { folder: 'system',          contentType: 'image',       labelPrefix: 'system',  allowed: [],              s3Mime: null }, // любой формат
};

const DEFAULT_CHROMAKEY = '0x00ff30';

function getExt(filename) {
  const f = String(filename || '');
  const i = f.lastIndexOf('.');
  return i >= 0 ? f.slice(i + 1).toLowerCase() : '';
}

function resolveKind(kind) {
  const c = CONTENT_KIND_MAP[kind];
  if (!c) throw new Error('Неизвестный тип контента: ' + kind);
  return c;
}

function validateExt(kind, filename) {
  const c = resolveKind(kind);
  const ext = getExt(filename);
  if (!ext) throw new Error(`Файл «${filename}» без расширения`);
  // SVG роняет FFmpeg в уникализации (Invalid PNG) — прод-воркер его не растеризует.
  if ((kind === 'overlay_logo' || kind === 'overlay_pattern') && ext === 'svg') {
    throw new Error('SVG не поддерживается для логотипов/паттернов. Загрузите PNG.');
  }
  if (c.allowed.length && !c.allowed.includes(ext)) {
    throw new Error(`Файл «${filename}»: формат .${ext} не поддерживается для ${kind}. Разрешено: ${c.allowed.join(', ')}`);
  }
  return ext;
}

function buildS3Key(folder, ext) {
  return `factory/${folder}/${crypto.randomUUID().replace(/-/g, '')}.${ext}`;
}

function nextSeq(labels, prefix, projectId) {
  const esc = String(prefix).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp('^' + esc + '_' + projectId + '_(\\d+)$');
  let max = 0;
  for (const l of labels) {
    const mm = re.exec(l || '');
    if (mm) { const n = parseInt(mm[1], 10); if (n > max) max = n; }
  }
  return max + 1;
}

function buildLabel(prefix, projectId, seq) {
  return prefix === 'system' ? 'system' : `${prefix}_${projectId}_${seq}`;
}

module.exports = { CONTENT_KIND_MAP, DEFAULT_CHROMAKEY, getExt, resolveKind, validateExt, buildS3Key, nextSeq, buildLabel };
```

- [ ] **Step 4: Запустить — зелёное**

Run: `cd /home/claude-user/autowarm-wp189 && node --test --test-force-exit tests/test_unic_upload_map.test.js`
Expected: PASS (8 tests).

- [ ] **Step 5: Коммит**
```bash
cd /home/claude-user/autowarm-wp189
git add unic_upload_map.js tests/test_unic_upload_map.test.js
git commit -m "feat(wp189-autowarm): unic_upload_map module + node:test unit tests"
```

---

## Task 2: Python S3-хелпер

**Files:**
- Create: `unic_s3_upload.py`

- [ ] **Step 1: Реализовать** `unic_s3_upload.py`.

**Креды S3 берутся ТОЛЬКО из окружения** (никаких секретов в файле — codex P1). На рантайме `server.js` делает `require('dotenv').config()` (стр.4), а прод `.env` autowarm уже содержит `S3_ENDPOINT/S3_BUCKET/S3_ACCESS_KEY/S3_SECRET_KEY/S3_PUBLIC_URL`. Python-child запускается через `execFile` без опции `env`, поэтому наследует `process.env` родителя → получает эти переменные. Не-секретные значения (endpoint/bucket/public) имеют дефолты; секреты (access/secret) — обязательны из env.

```python
#!/usr/bin/env python3
"""Залить локальный файл на Beget S3 в произвольный key, напечатать публичный URL в stdout.

Использование: python3 unic_s3_upload.py <local_path> <s3_key> <content_type>
Креды/настройки S3 берутся ИЗ ОКРУЖЕНИЯ (autowarm .env → dotenv → process.env → наследуется
этим дочерним процессом). Секретов в файле нет. На ошибке — stderr + ненулевой exit.
"""
import os
import sys

S3_ENDPOINT = os.environ.get('S3_ENDPOINT', 'https://s3.ru1.storage.beget.cloud')
S3_BUCKET = os.environ.get('S3_BUCKET', '1cabe906ea6e-gengo')
S3_PUBLIC_URL = os.environ.get('S3_PUBLIC_URL', 'https://save.gengo.io')
S3_ACCESS_KEY = os.environ.get('S3_ACCESS_KEY')
S3_SECRET_KEY = os.environ.get('S3_SECRET_KEY')


def main():
    if len(sys.argv) != 4:
        print('usage: unic_s3_upload.py <local_path> <s3_key> <content_type>', file=sys.stderr)
        sys.exit(2)
    if not (S3_ACCESS_KEY and S3_SECRET_KEY):
        print('S3 credentials missing in env (S3_ACCESS_KEY/S3_SECRET_KEY)', file=sys.stderr)
        sys.exit(3)
    local_path, s3_key, content_type = sys.argv[1], sys.argv[2], sys.argv[3]
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(
            signature_version='s3v4',
            request_checksum_calculation='when_required',
            response_checksum_validation='when_required',
        ),
    )
    s3.upload_file(local_path, S3_BUCKET, s3_key, ExtraArgs={'ContentType': content_type})
    print(f'{S3_PUBLIC_URL}/{s3_key}')


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Smoke — синтаксис + usage-guard (без реальной заливки)**

Run: `cd /home/claude-user/autowarm-wp189 && python3 -c "import ast; ast.parse(open('unic_s3_upload.py').read()); print('syntax ok')" && python3 unic_s3_upload.py 2>&1 | head -1`
Expected: `syntax ok` затем `usage: unic_s3_upload.py <local_path> <s3_key> <content_type>` (exit 2). (Реальная заливка проверяется вручную на деплое — боевые креды.)

- [ ] **Step 3: Коммит**
```bash
cd /home/claude-user/autowarm-wp189
git add unic_s3_upload.py
git commit -m "feat(wp189-autowarm): unic_s3_upload.py — boto3 helper (factory/<folder>/<uuid>)"
```

---

## Task 3: Эндпоинт POST /api/unic-content/upload в server.js

**Files:**
- Modify: `server.js`

- [ ] **Step 1: Убедиться в наличии require'ов**

Прочитать начало `server.js`. Уже есть: `fs` (стр.3), `path` (стр.8), `{ exec, execFile }` (стр.12). Если НЕТ `os` и/или `crypto` среди top-level require — добавить рядом с ними:
```javascript
const os = require('os');
const crypto = require('crypto');
```
(Проверить grep: `grep -nE "require\('(os|crypto)'\)" server.js`. Добавлять только отсутствующие.)

- [ ] **Step 2: Добавить require модуля маппинга** рядом с другими `require('./...')` в server.js:
```javascript
const unicMap = require('./unic_upload_map');
```

- [ ] **Step 2b: Обойти глобальный лимит `express.json()` для upload-пути** (codex P1)

Глобальный парсер `app.use(express.json())` на **стр. 53** имеет дефолтный лимит 100KB и срабатывает РАНЬШЕ роута → любой base64 >100KB получил бы 413 до нашего хендлера. Делаем так, чтобы глобальный json-парсер ПРОПУСКАЛ `/api/unic-content/upload` (его распарсит route-local парсер с поднятым лимитом). Заменить стр. 53 `app.use(express.json());` на:
```javascript
const _globalJson = express.json();
app.use((req, res, next) => {
  // upload-роут парсится локальным express.json с поднятым лимитом (см. /api/unic-content/upload)
  if (req.path === '/api/unic-content/upload') return next();
  return _globalJson(req, res, next);
});
```
(`express.urlencoded` на стр. 54 не трогаем — он не парсит `application/json`, для upload это no-op.)

- [ ] **Step 3: Добавить эндпоинт** сразу ПОСЛЕ блока `app.delete('/api/unic-content/:id', ...)` (около стр. 3700, перед `app.get('/api/projects-list'...)`). Обрати внимание: route-local `express.json({ limit: '200mb' })` в сигнатуре обязателен (глобальный парсер этот путь пропускает — см. Step 2b):
```javascript
// ===== UNIC CONTENT: загрузка файлов в S3 + строки (WP#189) =====
// Приём через base64-JSON (без multer): отдельный express.json с поднятым лимитом
// ТОЛЬКО на этом роуте (глобальный лимит не трогаем). S3-заливка — через python-хелпер
// (boto3, без новых npm-зависимостей). content_kind задаёт S3-папку и БД-таксономию.
function _uploadUnicToS3(localPath, s3Key, contentType) {
  return new Promise((resolve, reject) => {
    execFile('python3', [path.join(__dirname, 'unic_s3_upload.py'), localPath, s3Key, contentType],
      { timeout: 300000 }, (err, stdout, stderr) => {
        if (err) return reject(new Error('S3 upload failed: ' + ((stderr && stderr.trim()) || err.message)));
        const url = (stdout || '').trim();
        if (!url.startsWith('http')) return reject(new Error('S3 upload: bad url: ' + url));
        resolve(url);
      });
  });
}

// Лимит парсера (180mb) — это потолок ВСЕГО запроса (base64 всех файлов ~×1.34 + overhead).
// Per-file decoded cap ниже = 100 МБ, поэтому одиночный файл у потолка (~134mb base64) проходит
// парсер с запасом до 180mb (codex P2: парсер должен быть выше декодированного cap).
app.post('/api/unic-content/upload', requireAuth, express.json({ limit: '180mb' }), async (req, res) => {
  const { content_kind, usage_type, project_id, chromakey_color, files } = req.body || {};
  let cfg;
  try { cfg = unicMap.resolveKind(content_kind); }
  catch (e) { return res.status(400).json({ error: e.message }); }
  if (!Array.isArray(files) || files.length === 0) return res.status(400).json({ error: 'Нет файлов' });
  const pid = parseInt(project_id, 10) || 0;

  // seq по существующим label того же (prefix, project_id). LIKE с '_' матчит шире,
  // но nextSeq строго фильтрует регуляркой — лишние строки просто отбрасываются.
  const { rows: existing } = await pool.query(
    'SELECT label FROM validator_unic_content WHERE label LIKE $1',
    [`${cfg.labelPrefix}_${pid}_%`]
  );
  let seq = unicMap.nextSeq(existing.map(r => r.label), cfg.labelPrefix, pid);

  const created = [];
  const errors = [];
  for (const f of files) {
    let tmp = null;
    try {
      const ext = unicMap.validateExt(content_kind, (f && f.filename) || '');
      const b64 = String((f && f.data_b64) || '').replace(/^data:[^;]*;base64,/, '');
      const buf = Buffer.from(b64, 'base64');
      if (buf.length === 0) throw new Error(`Файл «${f.filename}» пустой или не прочитан`);
      if (buf.length > 100 * 1024 * 1024) throw new Error(`Файл «${f.filename}» больше 100 МБ`);
      tmp = path.join(os.tmpdir(), `unic_${crypto.randomUUID()}.${ext}`);
      fs.writeFileSync(tmp, buf);
      const key = unicMap.buildS3Key(cfg.folder, ext);
      const mime = cfg.s3Mime || 'application/octet-stream';
      const url = await _uploadUnicToS3(tmp, key, mime);
      const label = unicMap.buildLabel(cfg.labelPrefix, pid, seq);
      const ck = content_kind === 'overlay_video' ? (chromakey_color || unicMap.DEFAULT_CHROMAKEY) : null;
      const sizeMb = Math.round((buf.length / 1024 / 1024) * 100) / 100;
      const { rows } = await pool.query(
        `INSERT INTO validator_unic_content
           (content_type, label, usage_type, project_id, duration, size, file_path, chromakey_color)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id`,
        [cfg.contentType, label, usage_type, pid, null, sizeMb, url, ck]
      );
      created.push({ id: rows[0].id, content_type: cfg.contentType, label, usage_type,
                     project_id: pid, size: sizeMb, file_path: url, chromakey_color: ck });
      seq++;
    } catch (e) {
      errors.push({ file: (f && f.filename) || '—', detail: e.message });
    } finally {
      if (tmp) { try { fs.unlinkSync(tmp); } catch (_) {} }
    }
  }
  res.json({ created, errors });
});
```

- [ ] **Step 4: Проверить, что сервер парсится и роут зарегистрирован (без запуска listen)**

Run: `cd /home/claude-user/autowarm-wp189 && node -e "require('./unic_upload_map.js'); console.log('map ok')" && node --check server.js && echo "server.js syntax ok"`
Expected: `map ok` и `server.js syntax ok`. (Полный запуск server.js не делаем — он слушает порт; проверяем синтаксис через node --check.)

- [ ] **Step 5: Коммит**
```bash
cd /home/claude-user/autowarm-wp189
git add server.js
git commit -m "feat(wp189-autowarm): POST /api/unic-content/upload (base64 -> python boto3 -> validator_unic_content)"
```

---

## Task 4: Фронт — кнопка и модалка в public/index.html

**Files:**
- Modify: `public/index.html`

Паттерны (из разведки): модалки = `<div class="hidden fixed inset-0 ...">` + `classList.add/remove('hidden')`; fetch same-origin; проекты в `unicProjects` (из `/api/projects-list`); таблица перезагружается `loadUnicContent()`.

- [ ] **Step 1: Кнопка в шапке раздела**

Найти заголовок секции (около стр. 1170-1177):
```html
<div id="section-unic-content" class="section px-4 py-6 fade-in">
  <div class="flex items-center justify-between mb-4">
    <div>
      <h1 class="text-2xl font-bold text-gray-900">🎬 Контент</h1>
      <p class="text-sm text-gray-500 mt-1">Медиафайлы для уникализации контента</p>
    </div>
    <!-- ВСТАВИТЬ кнопку в правый (пустой) div этого flex-контейнера -->
  </div>
```
Вставить кнопку в правую часть flex-контейнера (после внутреннего `</div>` с заголовком, перед закрытием `flex`-контейнера):
```html
    <button onclick="openUnicUpload()"
      class="flex items-center gap-2 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-xl shadow-sm transition-colors text-sm">
      <span class="text-base">⬆</span> Загрузить контент
    </button>
```

- [ ] **Step 2: Модалка** — добавить рядом с существующей `#unic-modal` (после её закрывающего `</div>`, около стр. 1291):
```html
<!-- Модалка: Загрузка контента (WP#189) -->
<div id="unic-upload-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center p-4">
  <div class="absolute inset-0 bg-black/40" onclick="closeUnicUpload()"></div>
  <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6">
    <h3 class="text-lg font-bold text-gray-800 mb-5">Загрузить контент</h3>
    <div class="space-y-4">
      <div>
        <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Файлы *</label>
        <input id="uu-files" type="file" multiple
          class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
        <p id="uu-files-count" class="text-xs text-gray-500 mt-1 hidden"></p>
      </div>
      <div>
        <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Тип контента *</label>
        <select id="uu-content_kind" onchange="unicUploadOnKindChange()"
          class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
          <option value="overlay_sounds">Звуки (overlay_sounds)</option>
          <option value="overlay_fonts">Шрифты (overlay_fonts)</option>
          <option value="overlay_pattern">Паттерны (overlay_pattern)</option>
          <option value="overlay_logo">Логотипы (overlay_logo)</option>
          <option value="overlay_video">Видео (overlay_video)</option>
          <option value="system">Служебные (system)</option>
        </select>
      </div>
      <div>
        <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Тип использования *</label>
        <select id="uu-usage_type" onchange="unicUploadOnUsageChange()"
          class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
          <option value="Универсально (любой проект)">Универсально (любой проект)</option>
          <option value="Под проект (один конкретный проект)">Под проект (один конкретный проект)</option>
        </select>
      </div>
      <div id="uu-project-wrap" class="hidden">
        <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Проект *</label>
        <select id="uu-project_id" class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
          <option value="0" disabled selected>— выберите проект —</option>
        </select>
      </div>
      <div id="uu-chromakey-wrap" class="hidden">
        <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Chromakey цвет</label>
        <input id="uu-chromakey_color" type="text" value="0x00ff30"
          class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
      </div>
      <div id="uu-errors" class="text-xs text-red-600 space-y-1 hidden"></div>
    </div>
    <div class="flex gap-3 mt-6">
      <button id="uu-submit" onclick="submitUnicUpload()"
        class="flex-1 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white font-medium rounded-lg text-sm">Загрузить</button>
      <button onclick="closeUnicUpload()"
        class="flex-1 px-4 py-2.5 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg text-sm">Отмена</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: JS** — добавить рядом с `saveUnicItem`/`closeUnicModal` (около стр. 10320). Использует существующий глобал `unicProjects` и функцию `loadUnicContent()`:
```javascript
function unicUploadOnUsageChange() {
  const perProject = document.getElementById('uu-usage_type').value.includes('Под проект');
  document.getElementById('uu-project-wrap').classList.toggle('hidden', !perProject);
}
function unicUploadOnKindChange() {
  const isVideo = document.getElementById('uu-content_kind').value === 'overlay_video';
  document.getElementById('uu-chromakey-wrap').classList.toggle('hidden', !isVideo);
}
function openUnicUpload() {
  // заполнить дропдаун проектов из уже загруженного unicProjects
  const sel = document.getElementById('uu-project_id');
  sel.innerHTML = '<option value="0" disabled selected>— выберите проект —</option>';
  (unicProjects || []).forEach(p => {
    const o = document.createElement('option');
    o.value = p.id; o.textContent = p.project;
    sel.appendChild(o);
  });
  document.getElementById('uu-files').value = '';
  document.getElementById('uu-files-count').classList.add('hidden');
  document.getElementById('uu-content_kind').value = 'overlay_sounds';
  document.getElementById('uu-usage_type').value = 'Универсально (любой проект)';
  document.getElementById('uu-chromakey_color').value = '0x00ff30';
  const errBox = document.getElementById('uu-errors');
  errBox.classList.add('hidden'); errBox.innerHTML = '';
  unicUploadOnUsageChange();
  unicUploadOnKindChange();
  document.getElementById('unic-upload-modal').classList.remove('hidden');
}
function closeUnicUpload() {
  document.getElementById('unic-upload-modal').classList.add('hidden');
}
function _readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] || '');
    r.onerror = () => reject(new Error('Не удалось прочитать файл ' + file.name));
    r.readAsDataURL(file);
  });
}
async function submitUnicUpload() {
  const filesInput = document.getElementById('uu-files');
  const fileList = Array.from(filesInput.files || []);
  const usage = document.getElementById('uu-usage_type').value;
  const perProject = usage.includes('Под проект');
  const pid = parseInt(document.getElementById('uu-project_id').value, 10) || 0;
  const kind = document.getElementById('uu-content_kind').value;
  const errBox = document.getElementById('uu-errors');
  errBox.classList.add('hidden'); errBox.innerHTML = '';
  if (fileList.length === 0) { errBox.classList.remove('hidden'); errBox.textContent = 'Выберите файлы'; return; }
  if (perProject && pid <= 0) { errBox.classList.remove('hidden'); errBox.textContent = 'Выберите проект'; return; }

  const btn = document.getElementById('uu-submit');
  btn.disabled = true; btn.textContent = 'Загрузка...';
  try {
    const files = [];
    for (const f of fileList) files.push({ filename: f.name, data_b64: await _readFileAsBase64(f) });
    const payload = {
      content_kind: kind,
      usage_type: usage,
      project_id: perProject ? pid : 0,
      files,
    };
    if (kind === 'overlay_video') payload.chromakey_color = document.getElementById('uu-chromakey_color').value;
    const res = await fetch('/api/unic-content/upload', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    const out = await res.json();
    const errs = out.errors || [];
    await loadUnicContent();
    if (errs.length) {
      errBox.classList.remove('hidden');
      // textContent (не innerHTML) — имя файла/detail может содержать HTML (XSS). codex P2.
      errBox.innerHTML = '';
      errs.forEach(e => {
        const row = document.createElement('div');
        row.textContent = `⚠️ ${e.file}: ${e.detail}`;
        errBox.appendChild(row);
      });
      // очищаем выбор, чтобы повторный сабмит не залил уже загруженные повторно
      filesInput.value = '';
    } else {
      closeUnicUpload();
    }
  } catch (e) {
    errBox.classList.remove('hidden');
    errBox.textContent = 'Ошибка: ' + e.message;
  } finally {
    btn.disabled = false; btn.textContent = 'Загрузить';
  }
}
```

- [ ] **Step 4: Файл-каунтер (мелочь, UX)** — повесить обработчик на инпут в `openUnicUpload` уже не нужно; вместо этого добавить inline `onchange` в инпут из Step 2? — НЕ требуется (необязательно). Пропустить.

- [ ] **Step 5: Smoke — HTML валиден, функции определены**

Run: `cd /home/claude-user/autowarm-wp189 && node -e "const h=require('fs').readFileSync('public/index.html','utf8'); for (const id of ['unic-upload-modal','uu-files','uu-content_kind','uu-project_id','uu-chromakey_color']) if(!h.includes(id)) throw new Error('missing '+id); for (const fn of ['function openUnicUpload','function submitUnicUpload','function closeUnicUpload']) if(!h.includes(fn)) throw new Error('missing '+fn); console.log('index.html markers ok')"`
Expected: `index.html markers ok`.

- [ ] **Step 6: Коммит**
```bash
cd /home/claude-user/autowarm-wp189
git add public/index.html
git commit -m "feat(wp189-autowarm): кнопка и модалка загрузки контента в #section-unic-content"
```

---

## Task 5: Финальная проверка

- [ ] **Step 1: Все юнит-тесты модуля**

Run: `cd /home/claude-user/autowarm-wp189 && node --test --test-force-exit tests/test_unic_upload_map.test.js`
Expected: PASS (8).

- [ ] **Step 2: Регресс — весь набор тестов репо парсится/проходит (smoke)**

Run: `cd /home/claude-user/autowarm-wp189 && node --check server.js && echo "server ok"`
Expected: `server ok` (полный `npm test` опционально — он бьёт live-DB; достаточно syntax + новый модуль).

- [ ] **Step 3: Сводка** — что реализовано, результаты тестов, deploy-runbook (push → прод git pull → `sudo pm2 restart autowarm`).

---

## Self-Review (выполнено автором плана)

- **Покрытие spec:** маппинг (T1) ✓; S3-заливка boto3 без новых npm-deps (T2) ✓; эндпоинт upload + partial-success + seq + chromakey + размер + запрет SVG (T3) ✓; фронт кнопка+модалка+условные поля+проекты+сброс инпута (T4) ✓.
- **Плейсхолдеры:** нет — весь код приведён.
- **Согласованность:** `unicMap.{resolveKind,validateExt,buildS3Key,nextSeq,buildLabel,DEFAULT_CHROMAKEY}` одинаковы в T1/T3; `_uploadUnicToS3` шеллит ровно в `unic_s3_upload.py` из T2 с (local,key,content_type); фронт шлёт `{content_kind,usage_type,project_id,chromakey_color,files:[{filename,data_b64}]}` — ровно то, что читает T3.
- **Отличия от валидатора:** `/api/projects-list` (не `/api/projects`); requireAuth = session (не JWT); приём base64-JSON (не multipart); S3 через python-хелпер (не boto3 в процессе). Логика маппинга/таксономии идентична.

## Out of scope / после плана
- Деплой: push origin/main → прод (root) `cd /root/.openclaw/workspace-genri/autowarm && git pull` → `sudo pm2 restart autowarm`. index.html статичен (без сборки).
- Валидаторские правки WP#189 (PR-merged) — мёртвый код (страница осиротевшая); откат опционально, не блокер.
- `codex review` плана и диффа перед мержем.
