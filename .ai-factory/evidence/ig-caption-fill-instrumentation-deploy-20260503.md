# IG caption fill — instrumentation + IME-wait + retry handler — deployed 2026-05-03 15:13 UTC

## Что отгружено

PR #12 → main `13d4863`. Auto-pushed → `/root/.openclaw/workspace-genri/autowarm/`. PM2 autowarm restart #237 чистый (0 unstable, no NameError/ImportError).

3 commits:
- `e36ea50` — instrumentation: enriched `caption_verify_failed` event meta (`actual_text`, `caption_input_focused`, `ime_input_shown`) + `_save_debug_artifacts('caption_verify_fail_{N}_{method}')` per attempt
- `78a8133` — defensive: `_wait_for_ime_shown(3.0)` после focus + `_normalize_caption_for_input` (CRLF→LF) перед adb_text. Новый event `caption_ime_not_shown` warning
- `1ffd0cb` — `obstacle_actions.apply_action` dispatcher + `retry_caption_fill` handler + `observe_only` no-op (W3 Task 21, **НЕ wired в hot path**)

## Empirical evidence (phone 19 — 2026-05-03 14:30 UTC)

- ADBKeyBoard доставляет CRLF caption (233 chars из task 2689) в `caption_input_text_view` (`AutoCompleteTextView`) ✅
- ADBKeyBoard доставляет в IG Bio EditText ✅
- ADBKeyBoard доставляет в Samsung Messages с CRLF ✅
- `clipper` APK не установлен на устройствах + Android 14 background access blocked → `_caption_clipboard_paste` через `clipper.SET` мёртв с момента написания
- На prod устройстве RFGYA19DNGZ (identical IG version 422.0.0.44.64 + identical IME setup) — caption_fill_failed 100/36h. Дельта phone19↔prod не уточнена (timing race / stale IME / anti-bot rate-limit — 3 кандидата)

## Baseline (последние 36h до deploy)

| Category | Count |
|---|---|
| ig_caption_fill_failed | 52 (из ~66 IG fails) |

## Verification SQL (выполнить через 4-6h после deploy)

```sql
-- 1. Появилось ли обогащённое meta в новых caption_verify_failed events?
SELECT
  e->'meta'->>'method' AS method,
  e->'meta'->>'ime_input_shown' AS ime_shown,
  e->'meta'->>'caption_input_focused' AS focus,
  count(*) AS hits
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.platform='Instagram'
  AND pt.started_at >= '2026-05-03 15:13:00'
  AND e->'meta'->>'category' = 'caption_verify_failed'
GROUP BY 1,2,3 ORDER BY 4 DESC;

-- 2. Сколько новый caption_ime_not_shown warning fires (timing race indicator)?
SELECT count(*), min(pt.started_at), max(pt.started_at)
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE e->'meta'->>'category' = 'caption_ime_not_shown'
  AND pt.started_at >= '2026-05-03 15:13:00';

-- 3. Caption fill rate vs baseline
SELECT
  date_trunc('hour', started_at) AS hour,
  count(*) FILTER (WHERE error_code = 'ig_caption_fill_failed') AS caption_fails,
  count(*) FILTER (WHERE status = 'done') AS successes,
  count(*) AS total
FROM publish_tasks
WHERE platform = 'Instagram'
  AND started_at >= NOW() - INTERVAL '24 hours'
GROUP BY 1
ORDER BY 1 DESC;

-- 4. Конкретные actual_text / focused snapshots для post-mortem
SELECT pt.id, pt.account, e->'meta'->>'method' AS m,
  e->'meta'->>'actual_text' AS actual,
  e->'meta'->>'caption_input_focused' AS focused,
  e->'meta'->>'ime_input_shown' AS ime
FROM publish_tasks pt, jsonb_array_elements(pt.events::jsonb) e
WHERE pt.platform='Instagram'
  AND pt.started_at >= '2026-05-03 15:13:00'
  AND e->'meta'->>'category' = 'caption_verify_failed'
ORDER BY pt.id DESC LIMIT 20;
```

## Decision tree после verification

| Сигнал | Интерпретация | Next action |
|---|---|---|
| `ime_input_shown=false` дает значимую долю verify_failed | Timing race подтверждён — Commit 2 `_wait_for_ime_shown` уже это закрывает | Наблюдать снижение caption_fill_failed rate; если после 24h <50% baseline — успех |
| `ime_input_shown=true` стабильно но verify_failed сохраняется | НЕ timing — другая причина (anti-bot, stale IME state, что-то на window-token уровне) | Анализ `actual_text` snapshots → если field полностью пустой → input drop'ается; если partial → broadcast truncate. Дальнейшая разведка. |
| `caption_ime_not_shown` warning fires часто | IME action не активна — может быть default IME сменился (Honeyboard) | Добавить ime re-set step в `_wait_for_ime_shown` |
| caption_fill_failed существенно упал (≥50%) | Win — Commit 1+2 решили | Двигаться к W3 apply mode flip (отдельной волной) |

## NOT в этом deploy

- Apply mode flip (`obstacle_kb_lookup_only=false`) — отдельной волной после 24h soak
- 6 остальных action handlers (escalate, tap_text, keycode_back, force_stop, force_clean_recents, tap_resource_id) — последующие commits
- Anthropic switch (W3 Tasks 19-20)
- AI Unstuck shim (W3 Task 22)

## Worktree

`/tmp/wt-caption-fix` ветка `feature/ig-caption-fill-instrumentation-20260503` — оставлена для возможной правки follow-up. После 24h verify можно `git worktree remove`.
