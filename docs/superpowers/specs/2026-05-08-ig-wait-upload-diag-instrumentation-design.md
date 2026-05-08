# IG `_wait_instagram_upload` diagnostic instrumentation — design spec

**Дата:** 2026-05-08
**Sub-project:** P1.1 IG post-switch regressions (Phase 1 verification)
**Репо:** `autowarm-testbench` (auto-pushed в `GenGo2/delivery-contenthunter`)
**Цель:** Собрать diagnostic evidence про `ig_upload_confirmation_timeout` fails (15/24h spike сегодня), чтобы distinguish 3 кандидата root cause:

- **A** — IG app version drift (новые версии используют `InstagramMainActivity` как post-publish destination, наш code знает только `MainTabActivity`)
- **B** — Share button tap не доставлен (substring `'Поделиться' exact=False` matches wrong element); editor never progresses
- **C** — Share fired, IG показал transient dialog (rate limit / guideline) и auto-dismissed back в editor

---

## 1. Phase 1 evidence — recap

`publisher_instagram.py:1659-1967` — `_wait_instagram_upload`. Главный success-detect path:

```python
act_check = self.adb('dumpsys activity activities ... | grep -m1 "topResumedActivity"', timeout=8) or ''
if 'MainTabActivity' in act_check:
    log.info('✅ MainTabActivity — публикация прошла')
    published = True; break
```

Из 24-часового sample: 95 wait events, status-разбивка:

| status | MainTabActivity | InstagramMainActivity | GrantPermission | total |
|---|---|---|---|---|
| `done` | 28 (97%) | 1 | 0 | 29 |
| `failed` (timeout) | **0** | **40 (69%)** | 14 (24%) | 58 |
| `awaiting_url` | 4 | 4 | 0 | 8 |

Pattern абсолютно binary — done всегда лендится в MainTabActivity, fail всегда нет. **`InstagramMainActivity` не упомянута нигде в кодовой базе** (`grep` show 0 references).

Per-device: bimodal distribution — некоторые phones 0/2 success (100% fail), другие 2/2 success.

Текущие `wait` events лог truncated `act_diag.strip()[-50:]` — последние 50 символов; полный пакет `topResumedActivity` urлен. UI dump не сохраняется. Share button candidates не залогированы.

---

## 2. Approach (recommended из 3)

### 2.1. Recommended — add 2 structured events с full data

В `_wait_instagram_upload` добавить:

1. **`iter0` event** — сразу после `set_step('Instagram: ожидание загрузки (upload)')`, перед `for wait in range(30)`. Capture full `topResumedActivity`, S3 ui_dump_url, share-button candidates list.

2. **`timeout` event** — внутри `if not published:` block, перед существующим `_save_debug_artifacts('instagram_upload_timeout')`. Те же 3 поля.

Both использует существующий `_save_debug_artifacts(label)` для S3 upload (тот же путь что existing screenshots/ui_dumps).

**Plus:** Расширить existing wait-event meta (line 1900) — добавить `topResumedActivity_full` (без truncation) и `ui_brief` чтобы каждые 5 итераций были usable for forensics.

### 2.2. Альтернатива (rejected) — replay logs

Парсить existing pm2 logs after-the-fact. Rejected: log volume огромный, S3 UI dumps не там, не гарантировано retention.

### 2.3. Альтернатива (rejected) — packet capture

Захватить network traffic IG ↔ servers. Rejected: outside scope, MITM настройка слишком инвазивна.

---

## 3. Архитектура — отдельные events на boundaries

### 3.1. Iter0 event (post-Share, pre-loop)

**Location:** `publisher_instagram.py:1664-1665` (между `set_step` и `for wait in range(30)`).

**Capture:**
- `act_full` — full `topResumedActivity` line из dumpsys (без truncate)
- `ui_dump_url` — S3 URL через `self._save_debug_ui_dump('wait_upload_iter0')` (returns URL directly; existing helper at `publisher_base.py:779`)
- `ui_xml_local` — забираем UI XML напрямую через `self.dump_ui()` для извлечения `share_candidates` (helper не возвращает path к saved file сам по себе)
- `share_candidates` — list[dict] всех `<node>` где `text` или `content-desc` содержит любой из `('Поделиться', 'Share', 'Опубликовать')`. Per-candidate: `text`, `content_desc`, `bounds`, `resource_id`, `clickable`. Limit 10 candidates (если больше — обрезать без warning).

**Event:**

```python
self.log_event('info', 'Instagram: wait_upload iter0 diag',
               meta={'category': 'wait_upload_iter0_diag',
                     'platform': self.platform,
                     'topResumedActivity': act_full[:300],
                     'ui_dump_url': ui_url,
                     'share_candidates': share_candidates})
```

### 3.2. Timeout event (post-loop, на exhaustion)

**Location:** `publisher_instagram.py:1958-1965` (после `if not published:` test, перед существующим error log_event).

**Capture:** те же 3 поля что iter0.

**Event:**

```python
self.log_event('info', 'Instagram: wait_upload timeout diag',
               meta={'category': 'wait_upload_timeout_diag',
                     'platform': self.platform,
                     'topResumedActivity': act_final[:300],
                     'ui_dump_url': ui_url_final,
                     'share_candidates': share_candidates_final})
```

### 3.3. Wait-event meta enrichment (incremental)

**Location:** `publisher_instagram.py:1900` (existing `Instagram: wait {wait}` log_event).

**Change:** добавить в meta `topResumedActivity_full` (full string, не `[-50:]`). Existing `act` field остаётся (back-compat для anyone глядевшего на эту truncated версию).

```python
self.log_event('info', f'Instagram: wait {wait} — act={act_diag.strip()[-50:]}, ui={str(_ig_texts)[:150]}',
               meta={'category': 'wait_upload_iter_diag',
                     'iteration': wait,
                     'topResumedActivity_full': act_diag.strip()[:300],
                     'ui_brief': _ig_texts[:8]})
```

---

## 4. Helpers — share-candidates extraction

Pure function в `publisher_instagram.py` рядом с другими helpers (например после `_build_ig_editor_timeout_meta`, ~line 1655):

```python
def _collect_share_candidates(self, ui_xml: str) -> list[dict]:
    """Найти все ноды UI XML где text/desc содержит Share-keyword.

    Возвращает list[dict] (≤10) с per-candidate: text, content_desc, bounds,
    resource_id, clickable. Используется wait_upload diag instrumentation для
    отладки 'Share button tapped wrong element' гипотезы.
    """
    SHARE_KW = ('Поделиться', 'Share', 'Опубликовать')
    out: list[dict] = []
    if not ui_xml:
        return out
    try:
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(ui_xml)
    except Exception:
        return out
    for node in root.iter('node'):
        text = (node.get('text') or '').strip()
        desc = (node.get('content-desc') or '').strip()
        if not any(kw in text or kw in desc for kw in SHARE_KW):
            continue
        out.append({
            'text': text[:80],
            'content_desc': desc[:80],
            'bounds': node.get('bounds', ''),
            'resource_id': node.get('resource-id', ''),
            'clickable': node.get('clickable') == 'true',
        })
        if len(out) >= 10:
            break
    return out
```

---

## 5. Тестирование

**Pure-function helper `_collect_share_candidates` testable:**

`tests/test_ig_share_candidates.py` (новый):

1. `test_collect_share_candidates_finds_button_in_text` — synthetic XML с `<node text="Поделиться" clickable="true">` → возвращает 1 candidate.
2. `test_collect_share_candidates_filters_non_matching` — XML без share-text → `[]`.
3. `test_collect_share_candidates_caps_at_10` — XML с 15 matching nodes → return 10.
4. `test_collect_share_candidates_handles_malformed_xml` — `xml=''` → `[]`. `xml='<not>'` → `[]`.
5. `test_collect_share_candidates_includes_clickable_flag` — clickable=true и clickable=false ноды distinguished correctly.

**Behavior tests для diag events:** существующий test framework для publisher_instagram уже инструментирует через mock `dumpsys activity` и `dump_ui` calls. Расширим:

`tests/test_publisher_instagram_wait_upload_diag.py` (новый):

1. `test_wait_upload_iter0_event_logged` — invoke `_wait_instagram_upload` с successful first-iteration MainTabActivity, ожидание `iter0_diag` event present (verifies instrumentation runs always, not only on fail).
2. `test_wait_upload_timeout_event_logged` — invoke с InstagramMainActivity-stuck mock, ожидание `timeout_diag` event present.

---

## 6. Out of scope

- **Fix самой проблемы.** Этот PR — instrumentation only. Fix откладывается до получения evidence (Phase 2-4 systematic-debugging skill).
- **Wait-event meta extension вне line 1900.** Только existing diagnostic event.
- **Permission dialog handler** для GrantPermissionsActivity (Mode 2 — 14/58 hits). Отдельная сессия с separate spec.
- **Caption_fill_failed track.** Это отдельный residual baseline (4/24h vs peak 66 fixed 2026-05-04). Отдельная сессия.

---

## 7. Risks

| ID | Risk | Mitigation |
|---|---|---|
| R1 | `_save_debug_artifacts` может failить (S3 down, kill-switch enabled) → instrumentation event с `ui_dump_url=None` | Existing helper уже graceful (returns None при failure). `log_event` с None URL допустим. Кнопка `AUTOWARM_S3_ARTIFACTS_DISABLE=1` остаётся как kill-switch. |
| R2 | Iter0 dump_ui adds ~1 сек latency перед wait loop | Acceptable — wait_upload sets max 30 iterations × 10s = 5 min, +1 sec startup negligible. |
| R3 | `_collect_share_candidates` ловит false-positive matches (на ноды далеко от editor area) | OK для diag — caller анализирует bounds + clickable, false-positives просто шум. Limit 10 protects log volume. |
| R4 | Timeout event может не записаться если subprocess killed (BaseException) до log_event call | Protected: `_wait_instagram_upload` не perekodит BaseException, но обёртка `run_publish_task` ловит BaseException (per memory `project_ig_switch_silent_hang_backlog.md` Layer 3). На случай разрыва — timeout event внутри `if not published:` block, до `return False`, до выхода в caller. |
| R5 | Расширение wait-event meta с full topResumedActivity увеличит размер events JSONB | На задачу +30×~300B = ~9KB max добавляется per-task. Существующие events JSONB уже ~100KB+ для 30+ events. Pad в 10% — приемлемо. |

---

## 8. Definition of Done

- `_collect_share_candidates(ui_xml)` pure function added.
- `_wait_instagram_upload` emits `wait_upload_iter0_diag` event на старте (always, не только fail).
- `_wait_instagram_upload` emits `wait_upload_timeout_diag` event на timeout-exhaustion path.
- Existing wait events на line 1900 carry `meta.topResumedActivity_full` (full string).
- 5 + 2 unit tests green.
- Все existing publisher_instagram tests остаются зелёными (no behavior change для happy path).
- Deploy в prod main → naturally accumulate evidence next 1-2h.
- После 5+ fail-задач с iter0_diag/timeout_diag — analyze events, determine A/B/C root cause.

---

## 9. Связанные памяти

- `project_ig_post_switch_regressions_2026_05_08.md` — этот sub-project's investigation memory (Phase 1 findings).
- `project_ig_caption_fill_persistent_bug.md` — predecessor IG-fix memory.
- `feedback_silent_crash_layered.md` — discovery pattern reference.
- `feedback_codex_review_specs.md` — spec будет прогнан через `codex review` перед approval.
