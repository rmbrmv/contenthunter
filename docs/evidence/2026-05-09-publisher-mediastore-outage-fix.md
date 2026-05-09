# Publisher 19h outage 2026-05-09 — MediaStore _ms_query 2-layer fix

**Дата:** 2026-05-09
**Outage:** 2026-05-08 12:50 UTC → 2026-05-09 06:32 UTC (~18ч), 54/54 publishes failed с `media_store_unreadable_pre_publish`. 0 done после 12:50 May 8.
**RC:** Two latent bugs в commit `e59825c` (MediaStore double-query check, deploy 2026-05-08 12:20 UTC).
**Fix:** 2 atomic commits в prod main. Live verified.

---

## TL;DR

Commit `e59825c` (2026-05-08 12:20 UTC) добавил MediaStore double-query check `_ms_query` для anti-pollution detection. Check содержал 2 латентных бага:

1. **Layer 1** — Android 15 cmd shape: лишний `'shell '` префикс + `--limit 1` (Android 15 удалил поддержку) + `,`-separated projection (Android 15 требует `:`)
2. **Layer 2** — name comparison: push идёт в `/sdcard/DCIM/autowarm_<filename>`, MediaStore display_name = `'autowarm_<filename>'`, но check сравнивал `video_name == filename` (без префикса) → всегда False для реальных pq_*.mp4

PM2 рестарт 2026-05-08 12:24:45 UTC подхватил новый код → следующие 18ч все publishes fell on layer 1 → fail-fast. Layer 2 был masked.

**Fix:** commits `2a2ebb8` (cmd shape) + `14570a1` (basename compare). PM2 reload. YT task #4408 → done в проде. IG/TT progressed past MediaStore до chronic issues (downstream, separate triage).

---

## 1. Discovery

### 1.1. Симптом

```sql
SELECT status, COUNT(*) FROM publish_tasks
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status;
-- failed | 54
-- (нет других строк — 0 done)
```

100% failure rate за 24h. Все 54 — `error_code='media_store_unreadable_pre_publish'`. Все 3 платформы (IG/TT/YT). 7 проектов, 5 raspberries (#9 = 41 fails, остальные распределены), ~24 разных устройств. Не локализовано на одном проекте/devices/raspberry → системный.

Файлы локально на VPS существуют и свежие (`/tmp/publish_media/pq_*.mp4`). Push на устройство в логах = success (`adb_push_chunked_success: pq_X.mp4 7.8MB 8 chunks за 22.2s`).

### 1.2. Code path

`publisher_base.py::push_media_to_device` (line 3318+):
1. `_cleanup_device_artifacts(scope='pre_push')` — стирает stale-glob'ы
2. `adb_push(upload_path, '/sdcard/DCIM/autowarm_<filename>')`
3. `am broadcast MEDIA_SCANNER_SCAN_FILE` на новый файл
4. **`for ms_attempt in range(5)`**:
   - `_ms_query(content://media/external/video/media)` — должен вернуть свежий display_name + ts
   - if `not video_ok or video_ts == 0`: retry; после 5 попыток — `media_store_unreadable_pre_publish`

Все failed tasks хитили fail на шаге 4 (events JSONB подтверждает).

### 1.3. Live test на phone RFGYC31P94Z (Samsung SM-A175F, Android 15 SDK 35, raspberry 9)

```bash
ADB="adb -H 82.115.54.26 -P 15098"  # raspberry 9 adb port (15098, not 27840 = scrcpy)
DEV="RFGYC31P94Z"

# Воспроизвели cmd как в self.adb('shell content query ...'):
INNER='shell content query --uri content://media/external/video/media --sort "date_added DESC" --projection "_id,_display_name,date_added" --limit 1 2>/dev/null'
$ADB -s $DEV shell "$INNER"
# /system/bin/sh: shell: inaccessible or not found, rc=127
```

`self.adb()` уже добавляет `shell` wrapper (line 460). Cmd начинался с `'shell '` → итоговый адресован устройству как `shell shell content query ...`. Внутренний `shell` — попытка вызвать бинарник `shell`, которого на Android нет.

После убирания префикса:
```bash
$ADB -s $DEV shell "content query --uri content://media/external/video/media --sort \"date_added DESC\" --projection \"_id,_display_name,date_added\" --limit 1"
# usage: adb shell content [subcommand] [options] ...
# (Android 15 не воспринимает команду)
```

Через `--limit` отдельно:
```bash
$ADB -s $DEV shell "content query --uri ... --limit 1"
# [ERROR] Unsupported argument: --limit
```

Через `--projection`:
```bash
$ADB -s $DEV shell "content query --uri ... --projection _id,_display_name,date_added"
# java.lang.IllegalArgumentException: Invalid column _id,_display_name,date_added
```

Working call:
```bash
$ADB -s $DEV shell "content query --uri ... --sort 'date_added DESC' --projection _id:_display_name:date_added"
# Row: 0 _id=453, _display_name=20260508021003_ClickPay_a6352371_scheme16.mp4, date_added=1778242657
# Row: 1 _id=452, ...
```

→ Layer 1 RC подтверждён: 3 bugs в одной строке.

---

## 2. Layer 1 fix — cmd shape (commit `2a2ebb8`)

### 2.1. Изменение

`publisher_base.py:1265-1270` — было:
```python
out = self.adb(
    f'shell content query --uri {uri} '
    f'--sort "date_added DESC" '
    f'--projection "_id,_display_name,date_added" '
    f'--limit 1 2>/dev/null'
) or ''
```

Стало:
```python
out = self.adb(
    f"content query --uri {uri} "
    f"--sort 'date_added DESC' "
    f"--projection _id:_display_name:date_added "
    f"2>/dev/null"
) or ''
```

3 изменения:
1. Убран `'shell '` префикс (self.adb добавляет сам)
2. Убран `--limit 1` (Android 15 не поддерживает; берём первую строку через `re.search` который и так находит первое совпадение)
3. `--projection "_id,_display_name,date_added"` → `--projection _id:_display_name:date_added` (Android 15 требует `:`-separator)

### 2.2. Test добавлен

`tests/test_ig_gallery_picker_hardening.py::test_ms_query_command_shape_compatible_android_15` — assert sent_cmd:
- НЕ начинается с `'shell '`
- НЕ содержит `--limit`
- `--projection` не использует `,`

### 2.3. Verification post-restart

Re-queue `publish_queue.id=1758` → task #4406 → status `failed` с error_code `not_first_in_video` (не media_store_unreadable). Layer 1 closed; новый layer 2 surface'ит.

---

## 3. Layer 2 fix — basename mismatch (commit `14570a1`)

### 3.1. Discovery

Events #4406:
```
top_video='autowarm_pq_1758_1778338678204_tc.mp4'  (что MediaStore видит)
expected='pq_1758_1778338678204_tc.mp4'             (что check сравнивает)
```

Push в `/sdcard/DCIM/autowarm_<filename>` (line 3286), `os.path.basename` для display_name = `autowarm_<filename>`. Check `if video_name == filename:` всегда False для реальных pq_*.mp4 → всегда `not_first_in_video`.

### 3.2. Изменение

```python
filename = os.path.basename(upload_path)
remote_path = f'/sdcard/DCIM/autowarm_{filename}'
expected_basename = os.path.basename(remote_path)  # 'autowarm_<filename>'
...
# Strict equality на basename файла как он лежит на устройстве
if video_name == expected_basename:
```

Plus `expected_filename: expected_basename` в meta (через sed bulk replace) и в log f-strings для consistency.

### 3.3. Test masking discovered

Existing tests использовали `_make_push_stub('autowarm_test.mp4')` — filename уже с `'autowarm_'` префиксом, mock возвращал то же → старый `==` случайно проходил. Переведён stub на default `'pq_test.mp4'`, mock возвращает `f'autowarm_{filename}'`. Новый regression test `test_ms_check_compares_against_on_device_basename_not_local_filename`.

### 3.4. Verification post-restart

3 cross-platform probes (re-queued failed publishes):
- **YT 4408 (clickpay_easy)** → `done` в 15:37:24 UTC. Первый успешный publish после 19h outage.
- **TT 4409 (clickpay_life)** → `failed: tt_upload_confirmation_timeout` (chronic, в backlog session 2026-05-08)
- **IG 4407 (clickpay_under)** → `failed: ig_gallery_no_video_candidate` (downstream, был masked outage'ем)
- **IG 4410 (clickpay_me)** → `failed: ig_share_tap_no_progress` (Tier 1 fail-fast — fresh evidence для Tier 2 design)

Все 4 task'a прошли через MediaStore-гейт. Outage closed.

---

## 4. Pre-fix дополнительно

VPS disk 89% → 81% (+11G):
- `/tmp/publish_media >2д` → -8G
- `/tmp/autowarm_screenshots >2д` → -1.7G
- `/tmp/vision_postmortem_*.mp4` (5 debug files) → -260M
- workflow: `sudo chown -R claude-user:claude-user /tmp/<dir>` (NOPASSWD), `find -delete`

---

## 5. Follow-ups (out of scope этого fix'а)

| # | Что | Priority | Где |
|---|---|---|---|
| 1 | `server.js:6190` SQL bug `WHERE id=$2` с одним параметром → `could not determine data type of parameter $1`. Затрагивает skip-path для inactive accounts. | P3 | `/root/.openclaw/workspace-genri/autowarm/server.js:6190` |
| 2 | IG Tier 2 long-press escalation | P1 (design ready) | spec `2026-05-09-ig-share-retry-tier2-design.md` |
| 3 | `ig_gallery_no_video_candidate` triage | P2 (был masked) | новый top-fail post-MediaStore |
| 4 | `tt_upload_confirmation_timeout` chronic | P2 | известный backlog item |
| 5 | Cron auto-cleanup `/tmp/publish_media` старше N дней | P3 (operational) | предотвратить повтор disk pressure |

---

## 6. Что нового узнали

1. **Android 15 (SDK 35) ломает `content query` 3 способами одновременно** — это новая платформенная регрессия, не индивидуальный баг. Любой ADB-shell код с `content query` нужно audit-ить на этом наборе.
2. **`self.adb` уже добавляет `shell` wrapper** — внутренний cmd НЕ должен начинаться с `shell `. Класс ошибки тот же что `project_ig_caption_fill_persistent_bug 2026-05-03` — escape regression.
3. **Layered silent crashes** — один RC может маскировать другой. Memory `feedback_silent_crash_layered` reaffirmed: apply layer 1 → smoke → discover layer 2. Не пиши все фиксы из desk-think.
4. **Test mask via default arg coincidence** — `_make_push_stub('autowarm_test.mp4')` случайно match'ил production-transformation. Generic тест-имена (без production-prefix) гораздо безопаснее.
5. **Memory drift** — мой первоначальный prio-список включал B-YT-switcher (closed 2026-05-08). Memory `feedback_plan_staleness` validated. Cross-check с git/session memories до prio.

---

## 7. Связанные

- Memory: `~/.claude/projects/.../memory/project_publisher_outage_2026_05_09.md`
- Tier 2 design (downstream finding): `docs/superpowers/specs/2026-05-09-ig-share-retry-tier2-design.md`
- Old class того же бага: `project_ig_caption_fill_persistent_bug.md` (shell escape, fixed 2026-05-03)
- Layered debugging discipline: memory `feedback_silent_crash_layered.md`
