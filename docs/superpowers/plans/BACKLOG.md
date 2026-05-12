# Backlog tickets

## YT stabilization follow-ups (2026-05-12 session)

### Шаг D — yt_editor_upload_timeout (после AI Unstuck)

13 fails/week, single-pattern `YouTube: редактор timeout — Загрузить не найдено (после AI)` в `publisher_youtube.py:1199-1205`. AI Unstuck вызывается (`ai_unstuck_result=True`), что-то делает, но кнопка «Загрузить» не появляется. Screen recordings analysis на task'ах 4892/4444/4441. Hypothesis: editor в caption-screen с задержанной generation animation; AI не дожидается. Fix варианты: лучший detection caption-screen + skip AI, или post-AI wait+retry с другими criteria.

### Port `device_tz` to `publisher_helpers.parse_picker_thumbnail_date`

PR #45 (IG-only device-tz fix для phone #9 / Asia/Almaty) live в `publisher_instagram._ig_parse_thumbnail_date(desc, device_tz=None)`. После PR #43 (YT cross-project leak) IG имеет own copy с device_tz, YT использует `publisher_helpers.parse_picker_thumbnail_date` БЕЗ device_tz. Если YT начнут публиковать на не-MSK phones — будет False-mismatch. Port `device_tz` parameter в shared helper и rewire IG обратно на shared.

### Lead_Content_1 (и похожие) data-drift cleanup

Аккаунт в `factory_inst_accounts` с `gmail=NULL`, на phone в YT picker отсутствует (display name `Lead_Content `, suffix `_1` отсутствует, handle row отсутствует). Backfill no-match. Sticky 3 fails / 7d. Опции: (a) manual deactivation в БД; (b) automated `account_revision` post-scroll detector + auto-deactivate; (c) periodic backfill no-match log → daily TG bot notification.

### 24h soak — new YT RC counts

После Шагов B+C ждать 24h, затем:
```sql
SELECT events->-1->'meta'->>'category', COUNT(*)
FROM publish_tasks
WHERE platform='YouTube'
  AND created_at >= '2026-05-12 20:30:00+00'
  AND status='failed'
GROUP BY 1 ORDER BY 2 DESC;
```
Expected: `yt_target_not_in_picker_after_scroll` падает, `yt_picker_dismissed` + `yt_picker_target_absent` + `yt_picker_wrong_candidate` + `yt_gallery_no_video_candidate` появляются. Если `yt_gallery_no_video_candidate > 5/24h` — investigate device-state (не код).

### Real RC of 23-sec dead-time (race в task 3970)

Что dismisses YT picker между tap'ом и parse'ом (Шаг C показал: video player через 23s после picker shown). Hypothesis: spurious adb_tap из background / launcher / system notification. Defensive guard в Шаге C достаточно для observability и recovery; deeper investigation deferred до evidence accumulates.

## После 2026-05-12-scheme-preview-remote-worker

### Other ffmpeg tasks → unic-worker (same pattern)

После успешной миграции scheme preview по unic-worker queue pattern, следующие validator-side ffmpeg-задачи можно мигрировать тем же способом:

- **OCR** (`backend/src/services/ocr_service.py`)
- **Transcription** (`backend/src/services/transcription_service.py`)
- **Video metadata extraction** (`backend/src/services/video_metadata.py`)

Подход: alembic 005 расширяет `ck_unic_tasks_task_type` на новый `task_type`. Worker добавляет `process_<type>_task` функцию + dispatcher branch. Validator endpoint пишет в `unic_tasks` с соответствующим `task_type`. payload_hash и last_task_id guards переиспользуются.

### Heartbeat для legacy unic-pipeline

Сейчас `stale_task_recovery_loop` watchdog не трогает `task_type='unic'` потому что `process_task` может рендерить одну тяжёлую схему >15 мин без обновления `updated_at`. Решение: heartbeat_loop в legacy pipeline тоже (тот же helper, просто wrap). После этого расширить watchdog WHERE на оба task_type.

### Async cancellation orphan ffmpeg при PM2 restart

Codex P2 backlog из PR validator#6: `asyncio.to_thread + subprocess.run` не отменяют ffmpeg при SIGTERM. Перейти на `asyncio.create_subprocess_exec` с явным `process.kill()` в finally. Сейчас не релевантно для scheme preview (рендер на worker'е), но legacy unic-pipeline в worker.py остаётся sync subprocess.run.

### TG-notification при watchdog 3-revert

Сейчас только `logger.warning` идёт в `pm2 logs unic-worker`. Подключить через bugs-bot infrastructure (см. memory `project_bugs_bot`) — TG-нотификация в чат когда задача стоит в processing с `watchdog_revert_count >= 3`.

### Frontend timeout-aware error display

`UsersManagement.vue:348` паттерн `e.response?.data?.detail || 'Ошибка'` оставляет axios timeout кейсы немыми (generic «Ошибка»). Заменить на:

```js
catch (e: any) {
  formError.value = e.response?.data?.detail
    || (e.code === 'ECONNABORTED' ? 'Превышено время ожидания, попробуйте ещё раз' : null)
    || e.message
    || 'Ошибка'
}
```

Применить ко всем catch-блокам где `e.response?.data?.detail` ловится — есть в нескольких компонентах validator frontend.

### Multi-worker horizontal scale

Архитектурно разрешено через `FOR UPDATE SKIP LOCKED` в `get_pending_task`. Поднимать второй unic-worker на другом IP если queue depth растёт (нужно сначала enforce'ить heartbeat для legacy unic + monitoring queue depth).

### Cleanup duplicated phase→status mapping

Маппинг DB phase → legacy frontend status field дублируется в:
- `backend/src/routers/schemes.py` (внутри `check_readiness`)
- `backend/src/services/scheme_preview_queue.py` (внутри `read_scheme_preview_status`)

Когда фронт перейдёт на унифицированный shape (только `phase`, без `status`) — убрать дублирование. Сейчас оставлено для backward compat.

### Cancel-on-supersede для processing scheme_preview

Сейчас supersede mark'ает только `pending` строки. Если первая task уже в processing — она доработает (3-5 минут на схему × ~15 схем = до 75 минут), а новый payload встаёт рядом в pending. Можно добавить cancellation механизм:

```python
current_status='cancel_requested'
```

Worker check'ает между схемами и stops. Не критично пока, потому что новая task в любом случае перепишет результаты последней.
