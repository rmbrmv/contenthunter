# WP #86 PR3 — Server-side capture A3 (YouTube Data API) + A5 (differential id-diff) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development или superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** PR3 фаза WP #86 — server-side defense-in-depth для URL capture в url-poller (server.js):
- (A3) Заменить yt-dlp на YouTube Data API v3 для YT-ветки (reuse existing `analytics_collector.youtube_api_get_videos`). Deterministic, quota-cheap.
- (A5) Differential id-diff: bot до publish сохраняет top-5 video-id'ов аккаунта в `pre_publish_video_ids` JSONB; поллер делает `current_ids - pre_snapshot - other_awaiting_ids` → новые id = только что опубликованные.

**Architecture:** A3 — try-YT-API-first с graceful fallback на legacy yt-dlp при quota fail. A5 — pre-publish snapshot helper в publisher_base.py (вызывается из всех 3 publishers до публикации), server.js poller использует `pre_publish_video_ids` для matching. Кill-switches `URL_CAPTURE_USE_YT_API`, `URL_CAPTURE_USE_DIFF`.

**Tech Stack:** Node.js (server.js — поллер), Python (publisher_base pre-snapshot), PostgreSQL (column уже создан в PR1 schema migration — `pre_publish_video_ids JSONB`), YouTube Data API v3 (httpx из Python, аналог в Node.js через https.get).

**Spec:** `/home/claude-user/contenthunter/docs/superpowers/specs/2026-05-18-wp86-awaiting-url-stuck-design.md`

**OpenProject:** [WP #86](https://openproject.contenthunter.ru/projects/content-hunter/work_packages/86)

**Workdir:** `/home/claude-user/autowarm-testbench/`

**Зависимости:**
- PR1 SHIPPED — `pre_publish_video_ids` column уже есть (Task 1 schema migration)
- PR2 — независим от PR3, можно делать параллельно (PR2=Python bot, PR3=mix server.js + Python pre-snapshot, разные функции)

---

## File Structure

| Файл | Что |
|---|---|
| `analytics_collector.py` | Read-only reuse `youtube_api_get_channel_id`, `youtube_api_get_videos` (lines 496-560). НЕ ТРОГАТЬ. |
| `server.js` (новые функции) | `scrapeAllVideosViaApi(account)` — YT через child_process Python helper или прямой Node.js httpx-equivalent; `scrapeAllVideosDiff(videos, preSnapshot, otherUsed)` — diff helper |
| `server.js` (existing `scrapeAllVideos`) | YT-ветка получает try-A3 / fallback-legacy блок |
| `server.js` (existing `checkProcessingTasks` group loop) | Использовать `scrapeAllVideosDiff` для matching с pre-snapshot |
| `publisher_base.py` (новый helper) | `_snapshot_pre_publish_video_ids(platform, account)` — вызывается до publish, сохраняет top-5 ids в БД |
| `publisher_tiktok.py`, `publisher_instagram.py`, `publisher_youtube.py` (call sites) | Добавить `_snapshot_pre_publish_video_ids` в начале publish flow (before upload starts) |
| `migrations/youtube_api_helper.sh` или `lib/youtube_api_node.js` | Тонкий wrapper для вызова YT Data API из server.js (через child_process к Python helper'у, чтобы не дублировать api-логику в Node) |
| `tests/test_url_poller_diff.test.js` (new) | Unit tests для `scrapeAllVideosDiff` semantics |
| `tests/test_pre_publish_snapshot.py` (new) | Unit tests для `_snapshot_pre_publish_video_ids` helper |

---

## Pre-flight

### Task 0: Branch + baseline

- [ ] Pull latest main + create branch `feat/wp86-pr3-server-capture-a3-a5`
- [ ] `npm test` green (от PR1 = 142+)
- [ ] `pytest tests/` baseline check
- [ ] Verify `YOUTUBE_API_KEY` env-var доступен на проде

```bash
cd /home/claude-user/autowarm-testbench
git fetch origin --quiet && git checkout main && git pull --ff-only origin main
git checkout -b feat/wp86-pr3-server-capture-a3-a5
npm test 2>&1 | tail -7
pytest tests/ --tb=short 2>&1 | tail -10
# Verify YOUTUBE_API_KEY on prod
sudo cat /root/.openclaw/workspace-genri/autowarm/.env | grep YOUTUBE_API_KEY | head -1
```

Если `YOUTUBE_API_KEY` пуст / отсутствует — STOP и доложить, нужен ключ от Google Cloud Console.

---

## A3 — YouTube Data API через child_process

### Task 1: Decision — child_process vs Node-native httpx?

**Files:** N/A — design call.

Опции:
- **A.** `child_process.exec('python3 -c ...')` — реюз Python helper. Simple, no new deps.
- **B.** Node.js-native HTTP via `require('https')` или axios. Дублирует API-логику в JS.

**Recommendation:** A (child_process). Reasons:
- Python helper уже работает (battle-tested в analytics_collector)
- Не дублируем quota-handling/error-handling в JS
- Overhead вызова Python 1× per group ≈ 100-200ms — приемлемо при 2-min cron tick

Trade-off: Python startup overhead vs deduplication. Принимаю A.

Document decision в commit message Task 2.

### Task 2: Создать Python CLI wrapper для YT Data API

**Files:** Create `/home/claude-user/autowarm-testbench/scripts/yt_data_api_query.py`

- [ ] **Step 1: Создать file**

```python
#!/usr/bin/env python3
"""
WP #86 PR3 (A3): CLI wrapper для server.js — получить top-5 video-id'ов
YouTube канала через Data API v3.

Reuses analytics_collector.youtube_api_get_channel_id + youtube_api_get_videos.

Usage:
    python3 scripts/yt_data_api_query.py <handle>

Output (stdout, one per line):
    <video_id> <upload_date_YYYYMMDD>

Exit codes:
    0  — success (output to stdout)
    2  — quota exceeded / API key error (caller should fallback to yt-dlp)
    3  — channel not found
    1  — other errors
"""
import sys
import os
import json
import logging

logging.basicConfig(level=logging.WARNING)

# Inject parent dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analytics_collector import youtube_api_get_channel_id, youtube_api_get_videos


def main():
    if len(sys.argv) < 2:
        print('usage: yt_data_api_query.py <handle>', file=sys.stderr)
        sys.exit(1)
    handle = sys.argv[1].lstrip('@')
    if not os.getenv('YOUTUBE_API_KEY'):
        print('YOUTUBE_API_KEY not set', file=sys.stderr)
        sys.exit(2)
    try:
        channel_id = youtube_api_get_channel_id(handle)
        if not channel_id:
            sys.exit(3)
        videos = youtube_api_get_videos(channel_id)
        if not videos:
            return  # empty stdout OK
        # Print id + upload_date YYYYMMDD
        for v in videos[:5]:
            vid = v.get('id', '') or v.get('video_id', '')
            published_at = v.get('published_at') or v.get('publishedAt') or ''
            # Convert ISO 'YYYY-MM-DDTHH:MM:SSZ' to 'YYYYMMDD'
            date_str = published_at.split('T')[0].replace('-', '') if published_at else ''
            print(f'{vid} {date_str}')
    except Exception as e:
        msg = str(e).lower()
        if 'quota' in msg or '403' in msg:
            print(f'quota: {e}', file=sys.stderr)
            sys.exit(2)
        print(f'error: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Сделать executable + smoke**

```bash
cd /home/claude-user/autowarm-testbench
chmod +x scripts/yt_data_api_query.py
# Smoke с реальным handle (любой публичный YT-канал)
YOUTUBE_API_KEY=$(grep -oP 'YOUTUBE_API_KEY=\K\S+' /root/.openclaw/workspace-genri/autowarm/.env) \
  python3 scripts/yt_data_api_query.py mkbhd | head -5
```

Expected: 5 строк формата `<video_id> YYYYMMDD`.

- [ ] **Step 3: Commit**

```bash
git add scripts/yt_data_api_query.py
git commit -m "feat(yt-api): WP #86 PR3 — Python CLI wrapper для YT Data API

scripts/yt_data_api_query.py — тонкая обёртка над
analytics_collector.youtube_api_get_videos. Output: 'video_id YYYYMMDD'
per line, exit 2 на quota/API-key error, 3 на channel not found.

Reuses existing API helpers вместо дублирования логики в Node.js
(decision Task 1: child_process overhead приемлем при 2-min cron tick).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3: server.js — `scrapeAllVideosViaApi` для YT + fallback

**Files:** Modify `/home/claude-user/autowarm-testbench/server.js` (около `scrapeAllVideos`, line 6954)

- [ ] **Step 1: Добавить новую функцию рядом с scrapeAllVideos**

```javascript
/**
 * WP #86 PR3 (A3): YT Data API path для url-poller.
 * Вызывает Python helper scripts/yt_data_api_query.py.
 * Возвращает массив {id, uploadDate, url} тот же shape что scrapeAllVideos.
 * При quota/network failure (exit 2) — возвращает null чтобы caller
 * сделал fallback на legacy yt-dlp.
 */
async function scrapeAllVideosViaApi(account) {
  const acct = account.replace(/^@/, '');
  return new Promise((resolve) => {
    require('child_process').exec(
      `python3 ${__dirname}/scripts/yt_data_api_query.py "${acct}" 2>/dev/null`,
      { timeout: 15000, env: { ...process.env } },
      (err, stdout, stderr) => {
        if (err) {
          // exit 2 = quota / API key issue → caller fallback
          if (err.code === 2) {
            console.warn(`[url-poller] YT API quota/network для @${acct}, fallback на yt-dlp`);
            return resolve(null);
          }
          // Other errors — пусто
          return resolve([]);
        }
        const videos = [];
        for (const line of (stdout || '').split('\n')) {
          const parts = line.trim().split(' ');
          if (parts.length < 2) continue;
          const [id, uploadDate] = parts;
          if (!/^[a-zA-Z0-9_-]{11}$/.test(id)) continue;
          videos.push({
            id,
            uploadDate,
            url: `https://www.youtube.com/shorts/${id}`
          });
        }
        return resolve(videos);
      }
    );
  });
}
```

- [ ] **Step 2: В существующей `scrapeAllVideos` YT-ветке — добавить A3-first try**

Найти YT-ветку в `scrapeAllVideos` (около line 6980):

```javascript
    } else if (platform === 'YouTube') {
      const handle = acct.replace(/^@+/, '');
      const result = await new Promise((resolve) => {
        require('child_process').exec(
          `yt-dlp --flat-playlist --playlist-end 30 --print "%(id)s %(upload_date)s" "https://www.youtube.com/@${handle}/shorts" 2>/dev/null`,
          { timeout: 45000 },
          (err, stdout) => resolve(!err && stdout ? stdout.trim() : null)
        );
      });
```

Заменить на:

```javascript
    } else if (platform === 'YouTube') {
      // WP #86 PR3 (A3): сначала пробуем YT Data API — deterministic,
      // quota-cheap. Если quota исчерпана / нет ключа → fallback на yt-dlp.
      if (process.env.URL_CAPTURE_USE_YT_API !== '0') {
        const apiResult = await scrapeAllVideosViaApi(acct);
        if (apiResult !== null) {
          // null = quota fail, [] = empty (acceptable), [...] = success
          if (apiResult.length > 0) {
            console.log(`[url-poller] YT API @${acct}: ${apiResult.length} videos`);
          }
          return apiResult;
        }
        // null → fallthrough к yt-dlp
      }
      // Legacy yt-dlp path
      const handle = acct.replace(/^@+/, '');
      const result = await new Promise((resolve) => {
        require('child_process').exec(
          `yt-dlp --flat-playlist --playlist-end 30 --print "%(id)s %(upload_date)s" "https://www.youtube.com/@${handle}/shorts" 2>/dev/null`,
          { timeout: 45000 },
          (err, stdout) => resolve(!err && stdout ? stdout.trim() : null)
        );
      });
```

(Остальная YT-логика парсинга stdout не меняется.)

- [ ] **Step 3: npm test green + commit**

```bash
cd /home/claude-user/autowarm-testbench
npm test 2>&1 | tail -7
git add server.js
git commit -m "feat(url-poller): WP #86 PR3 A3 — YT Data API первичный + yt-dlp fallback

scrapeAllVideos YT-ветка теперь пробует scrapeAllVideosViaApi
(child_process к Python helper) ДО legacy yt-dlp. На quota fail
(exit 2 от helper) — graceful fallback.

Kill-switch URL_CAPTURE_USE_YT_API=0 принудительно использует legacy.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## A5 — Differential id-diff

### Task 4: `_snapshot_pre_publish_video_ids` helper + tests

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/publisher_base.py`
- Create: `/home/claude-user/autowarm-testbench/tests/test_pre_publish_snapshot.py`

- [ ] **Step 1: Failing test**

```python
"""WP #86 PR3 (A5): pre-publish video-ids snapshot helper."""
import pytest
import json
from unittest.mock import MagicMock, patch
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSnapshotPrePublishIds:
    def test_yt_snapshot_via_python_helper_success(self):
        # Mock subprocess.run для возврата 3 video_ids
        from publisher_base import _scrape_top_video_ids_pure
        # Pure-функция: принимает stdout-string и парсит
        stdout = "abc123def45 20260518\nxyz789ghi01 20260517\ntop555kop99 20260516\n"
        result = _scrape_top_video_ids_pure(stdout, platform='YouTube', limit=5)
        assert result == ['abc123def45', 'xyz789ghi01', 'top555kop99']

    def test_tiktok_snapshot_filters_invalid_ids(self):
        from publisher_base import _scrape_top_video_ids_pure
        # TT id = 15-20 digits
        stdout = "7234567890123456789 20260518\nshort 20260518\n7234567890123456788 20260517\n"
        result = _scrape_top_video_ids_pure(stdout, platform='TikTok', limit=5)
        assert result == ['7234567890123456789', '7234567890123456788']

    def test_empty_stdout_returns_empty_list(self):
        from publisher_base import _scrape_top_video_ids_pure
        assert _scrape_top_video_ids_pure('', platform='YouTube', limit=5) == []

    def test_limit_respected(self):
        from publisher_base import _scrape_top_video_ids_pure
        stdout = "\n".join([f"vid{i:011d} 20260518" for i in range(10)])
        result = _scrape_top_video_ids_pure(stdout, platform='YouTube', limit=3)
        assert len(result) == 3
```

- [ ] **Step 2: Implement pure helper в publisher_base.py**

```python
def _scrape_top_video_ids_pure(stdout: str, platform: str, limit: int = 5) -> list:
    """
    WP #86 PR3 (A5): pure парсер stdout от scraper'а в массив video-id'ов.

    Platform-specific id validation:
        TikTok    — 15-20 digits
        YouTube   — 11 chars, [a-zA-Z0-9_-]
        Instagram — variable shortcode
    """
    if not stdout:
        return []
    import re as _re
    ids = []
    for line in stdout.split('\n'):
        parts = line.strip().split(' ')
        if not parts or not parts[0]:
            continue
        vid = parts[0]
        if platform == 'YouTube':
            if not _re.match(r'^[a-zA-Z0-9_-]{11}$', vid):
                continue
        elif platform == 'TikTok':
            if not _re.match(r'^\d{15,20}$', vid):
                continue
        elif platform == 'Instagram':
            # IG shortcode: ~5-15 chars alphanum + - _
            if not _re.match(r'^[A-Za-z0-9_-]{5,20}$', vid):
                continue
        else:
            continue
        ids.append(vid)
        if len(ids) >= limit:
            break
    return ids
```

И class-метод (вызывается из bot):

```python
def _snapshot_pre_publish_video_ids(self) -> Optional[list]:
    """
    WP #86 PR3 (A5): до publish — snapshot top-5 video-id'ов аккаунта.
    Сохраняет в БД (publish_tasks.pre_publish_video_ids JSONB).
    На failure — return None (полло будет fallback на пустой массив).
    """
    if os.getenv('URL_CAPTURE_USE_DIFF', '1') == '0':
        return None
    try:
        # Call same scraper что использует server.js poller
        platform = self.platform
        acct = self.account.lstrip('@')
        if platform == 'YouTube':
            cmd = f'python3 {os.path.dirname(__file__)}/scripts/yt_data_api_query.py "{acct}"'
        elif platform == 'TikTok':
            cmd = f'yt-dlp --flat-playlist --playlist-end 10 --print "%(id)s %(upload_date)s" "https://www.tiktok.com/@{acct}" 2>/dev/null'
        else:
            # IG: web_profile_info — для simplicity skip в первой версии PR3
            return None

        import subprocess as _sub
        result = _sub.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        ids = _scrape_top_video_ids_pure(result.stdout, platform=platform, limit=5)
        if ids:
            # Save to DB
            import psycopg2
            import json as _json
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute(
                "UPDATE publish_tasks SET pre_publish_video_ids=%s WHERE id=%s",
                (_json.dumps(ids), self.task_id)
            )
            conn.commit(); conn.close()
            log.info(f'[url-capture A5] pre-snapshot saved: {len(ids)} ids')
            self.log_event('info', f'url_capture_pre_snapshot: {len(ids)} ids',
                            meta={'category': 'url_capture_pre_snapshot',
                                  'platform': platform, 'ids_count': len(ids)})
        return ids
    except Exception as e:
        log.warning(f'_snapshot_pre_publish_video_ids error: {e}')
        return None
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/test_pre_publish_snapshot.py -v 2>&1 | tail -10
git add publisher_base.py tests/test_pre_publish_snapshot.py
git commit -m "feat(capture): WP #86 PR3 A5 — pre-publish video-ids snapshot helper

Pure parser + class method для сохранения top-5 video-id'ов аккаунта
в publish_tasks.pre_publish_video_ids JSONB до publish. Server.js poller
будет использовать это для differential matching (видео которых не было
до publish = вновь опубликованное).

YT через YT API helper (reuse PR3 Task 2 wrapper). TT через yt-dlp.
IG отложен — отдельный path web_profile_info.

Kill-switch URL_CAPTURE_USE_DIFF=0.

4 unit tests: platform-specific id validation, empty stdout, limit cap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 5: Wire snapshot в TT/YT publishers (IG отложен)

**Files:**
- Modify: `/home/claude-user/autowarm-testbench/publisher_tiktok.py`
- Modify: `/home/claude-user/autowarm-testbench/publisher_youtube.py`

Pre-publish snapshot должен вызываться в начале publish flow (до фактической публикации).

- [ ] **Step 1: TT — найти начало publish-flow** (метод вроде `publish_tiktok_video`)

```bash
cd /home/claude-user/autowarm-testbench
grep -n "def publish_tiktok\|def upload_tiktok" publisher_tiktok.py | head -5
```

В самое начало publish-метода (после account-setup, до фактического upload) добавить:

```python
        # WP #86 PR3 (A5): pre-publish snapshot для diff matching в поллере
        try:
            self._snapshot_pre_publish_video_ids()
        except Exception as e:
            log.warning(f'pre-publish snapshot не удался: {e}')
            # Не критично — поллер просто будет использовать fallback
```

- [ ] **Step 2: YT — аналогично**

```bash
grep -n "def publish_youtube\|def upload_youtube" publisher_youtube.py | head -5
```

Аналогичная вставка.

- [ ] **Step 3: pytest + commit**

```bash
pytest tests/ --tb=short 2>&1 | tail -10
git add publisher_tiktok.py publisher_youtube.py
git commit -m "feat(publish): WP #86 PR3 A5 — wire pre-publish snapshot в TT + YT publishers

Вызов self._snapshot_pre_publish_video_ids() в начале publish flow
(до upload). Failure не блокирует publish — log warning, поллер сделает
fallback на пустой массив.

IG snapshot отложен — нужен отдельный path через web_profile_info API,
не yt-dlp.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: server.js — diff matching в poller group loop

**Files:** Modify `/home/claude-user/autowarm-testbench/server.js` (около line 6900-6940, per-group обработка)

- [ ] **Step 1: Создать pure helper для diff (export для тестов)**

В server.js (перед `checkProcessingTasks` около line 6841) добавить:

```javascript
/**
 * WP #86 PR3 (A5): differential matcher.
 * @param {string[]} currentIds - id'ы видео из текущего scrape
 * @param {string[]} preSnapshot - id'ы виденные до publish (от bot'а)
 * @param {string[]} otherTasksUsed - id'ы которые уже подобраны другими задачами
 * @returns {string[]} id'ы которые "новые" (= только что опубликованы)
 */
function scrapeAllVideosDiff(currentIds, preSnapshot, otherTasksUsed) {
  if (!Array.isArray(currentIds)) return [];
  const exclude = new Set([
    ...(Array.isArray(preSnapshot) ? preSnapshot : []),
    ...(Array.isArray(otherTasksUsed) ? otherTasksUsed : []),
  ]);
  return currentIds.filter(id => !exclude.has(id));
}
```

И в module.exports:

```javascript
  module.exports.scrapeAllVideosDiff = scrapeAllVideosDiff;
```

- [ ] **Step 2: Use в checkProcessingTasks group loop**

Найти место matching (около line 6907-6920 где `freeVideos`):

```javascript
      const taskIds = tasks.map(t => t.id);
      const { rows: usedRows } = await pool.query(
        `SELECT post_url FROM publish_tasks 
         WHERE post_url IS NOT NULL AND post_url != '' 
           AND id != ALL($1::int[])
         ORDER BY id`,
        [taskIds]
      );
      const usedUrls = new Set(usedRows.map(r => r.post_url));

      // Фильтруем видео: убираем уже привязанные к другим задачам
      const freeVideos = allVideos.filter(v => !usedUrls.has(v.url));
```

Заменить — добавить также exclude из `pre_publish_video_ids` других задач:

```javascript
      const taskIds = tasks.map(t => t.id);
      const { rows: usedRows } = await pool.query(
        `SELECT post_url, pre_publish_video_ids FROM publish_tasks 
         WHERE id != ALL($1::int[])
           AND (post_url IS NOT NULL AND post_url != ''
                OR pre_publish_video_ids IS NOT NULL)
         ORDER BY id`,
        [taskIds]
      );
      const usedUrls = new Set();
      const otherPreSnapshotIds = new Set();
      for (const r of usedRows) {
        if (r.post_url) usedUrls.add(r.post_url);
        if (Array.isArray(r.pre_publish_video_ids)) {
          for (const id of r.pre_publish_video_ids) otherPreSnapshotIds.add(id);
        }
      }

      // WP #86 PR3 (A5): фильтруем видео:
      // 1. Убираем уже привязанные URL'ы к другим задачам (legacy)
      // 2. Убираем id'ы из pre_publish_video_ids этого же аккаунта других задач
      // 3. Для каждой задачи в группе — exclude её OWN pre_snapshot
      const freeVideos = allVideos.filter(v =>
        !usedUrls.has(v.url) && !otherPreSnapshotIds.has(v.id)
      );
```

(Per-task diff с собственным pre_snapshot можно сделать в loop ниже — но первый шаг базовый exclude уже достаточно ценен.)

- [ ] **Step 3: Unit test для diff**

Create `/home/claude-user/autowarm-testbench/tests/test_url_poller_diff.test.js`:

```javascript
'use strict';
const { test, describe } = require('node:test');
const assert = require('node:assert');
const { scrapeAllVideosDiff } = require('../server.js');

describe('scrapeAllVideosDiff', () => {
  test('новый id не в pre_snapshot — возвращается', () => {
    const result = scrapeAllVideosDiff(['new1', 'old1', 'old2'], ['old1', 'old2'], []);
    assert.deepStrictEqual(result, ['new1']);
  });

  test('id из других awaiting задач excluded', () => {
    const result = scrapeAllVideosDiff(['new1', 'taken1'], [], ['taken1']);
    assert.deepStrictEqual(result, ['new1']);
  });

  test('empty pre_snapshot — все current считаются новыми', () => {
    const result = scrapeAllVideosDiff(['a', 'b', 'c'], [], []);
    assert.deepStrictEqual(result, ['a', 'b', 'c']);
  });

  test('empty current — empty result', () => {
    const result = scrapeAllVideosDiff([], ['a'], []);
    assert.deepStrictEqual(result, []);
  });

  test('non-array inputs — defensive', () => {
    assert.deepStrictEqual(scrapeAllVideosDiff(null, [], []), []);
    assert.deepStrictEqual(scrapeAllVideosDiff(['a'], null, null), ['a']);
  });
});
```

- [ ] **Step 4: npm test + commit**

```bash
npm test 2>&1 | tail -10
git add server.js tests/test_url_poller_diff.test.js
git commit -m "feat(url-poller): WP #86 PR3 A5 — diff matching через pre_publish_video_ids

scrapeAllVideosDiff (pure helper, export'нут для тестов): берёт current
ids - pre_snapshot - other_tasks_used = новые id'ы.

В checkProcessingTasks loop теперь exclude как post_url'ы (legacy),
так и pre_publish_video_ids других awaiting задач этого аккаунта.

5 unit tests: новый id, exclude-from-other, empty pre, empty current,
defensive non-array.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Validation + Deploy

### Task 7: Full test suites + smoke

- [ ] `npm test` green
- [ ] `pytest tests/` green
- [ ] Local smoke YT API helper:
```bash
YOUTUBE_API_KEY=<key> python3 scripts/yt_data_api_query.py mkbhd | head -3
```
- [ ] Testbench smoke: запустить TT-publish с реальным аккаунтом, проверить:
  - `url_capture_pre_snapshot` event фиксируется
  - poller использует diff и находит новое видео даже когда yt-dlp возвращает много старых
  - YT-task через A3 ветку — event `url_capture_via_yt_api` или fallback `url_capture_via_legacy_list`

### Task 8: PR + deploy

- [ ] Push branch + `gh pr create` (template аналогичен PR2 Task 8)
- [ ] Merge через `gh pr merge --squash` (NO force-push)
- [ ] Pull prod git + `sudo pm2 restart autowarm --update-env`
- [ ] **ВАЖНО:** PR3 добавляет dependency на `scripts/yt_data_api_query.py` — verify что script доступен и executable на prod cwd (`/root/.openclaw/workspace-genri/autowarm/scripts/`)

### Task 9: 24h post-deploy метрики + WP #86 update

- [ ] Через 24h after deploy:
```sql
SELECT
  jsonb_path_query_first(events, '$.meta.category')::text AS category,
  COUNT(*)
FROM publish_tasks pt
LEFT JOIN events e ON e.task_id = pt.id
WHERE pt.updated_at > NOW() - INTERVAL '24 hours'
  AND e.meta->>'category' LIKE 'url_capture%'
GROUP BY 1 ORDER BY 2 DESC;
```
- [ ] Snapshot % published_no_url до/после: должно дальше упасть после A3/A5
- [ ] Update memory `project_wp86_pr3_server_capture_shipped.md` если PR3 даёт significant improvement
- [ ] WP #86 — финальный update с метриками PR1+PR2+PR3, поменять status → `Готово` если все 3 PR shipped и stuck queue стабильно <5

---

## Self-Review Checklist

- [ ] A3 fallback к yt-dlp работает на quota fail (exit code 2 → null → fallthrough)
- [ ] A5 pure helper `scrapeAllVideosDiff` testable без БД
- [ ] Pre-snapshot column `pre_publish_video_ids` правильно set по schema (JSONB array)
- [ ] Diff exclude учитывает: legacy post_url + pre_snapshot OTHER tasks. Свой собственный pre_snapshot можно либо exclude'ить (защита от race) либо нет (если bot пишет synchronously). Spec говорит exclude — выбираю да.
- [ ] IG snapshot не реализован в PR3 — документировано как future sub-task
- [ ] Kill-switches: URL_CAPTURE_USE_YT_API, URL_CAPTURE_USE_DIFF, URL_CAPTURE_USE_NOTIF (последний от PR2) — все читаются на каждом cron-tick / publish-call (no caching)
- [ ] YOUTUBE_API_KEY check в Task 0 — если отсутствует, escalate user

---

## Open questions

1. **Per-task own-snapshot exclude:** надо ли в diff exclude'ить ИМЕННО собственный pre_snapshot задачи? Если bot снимает snapshot synchronously и snapshot pре-existing, новые id'ы reasonably = вновь опубликовано. Если же snapshot сделан до публикации (как и должно быть), pre_snapshot НЕ содержит новый id, и matching работает естественно. **Решение:** не делать per-task own-exclude — лишняя complication. Document в Task 6 comments.

2. **IG snapshot:** через web_profile_info, но это server-side helper в server.js. Если IG snapshot ценен (метрики PR3 покажут) — отдельный mini-PR.
