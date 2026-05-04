# IG caption_fill — ROOT CAUSE FIXED ✅ — 2026-05-03

## TL;DR

`ig_caption_fill_failed` (доминирующая prod категория, 100+/36h) — shell escape bug в `adb_text` wrapper. Fix через переход на ADB_INPUT_B64.

**Validation:** caption_fill_failed rate **50 → 0** за 45 мин. 13 успешных публикаций впервые за длительное время.

## Root cause

`_adb_shell` обёртка: `f'adb -H ... shell "{cmd}"'`. Когда cmd содержит свои `"..."` (для `am --es msg "Russian text"`):

```
shell "am broadcast --es msg "Хотите начать..."
                                ^
                       bash quote закрывается → "Хотите" concat'ится
                       "начать" parsed как extra arg → pkg=начать
```

Прод evidence task 2819:
```
Broadcasting: Intent { ... pkg=начать (has extras) }
Broadcast completed: result=0  ← no receiver matched filter
```

ADBKeyBoard не получал → wrapper падал на dead clipboard fallback (clipper APK не установлен на устройствах + Android 14+ blocks background clipboard) → текст silently не доставлялся.

**Manual работал случайно** — short test captions ("TEST_CAPTION_2026") без spaces в quoted msg.

## Fix (PR#15 / commit eaf724c)

`adb_text` теперь использует `ADB_INPUT_B64`:
```python
b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
result = _adb_shell(serial, port, host,
    f'am broadcast -a ADB_INPUT_B64 --es msg {b64}', timeout=10)
```

Base64 alphabet `[A-Za-z0-9+/=]` без quotes/spaces — shell escape bypass.

Cleanup в том же commit:
- Drop dead `clipper.SET` fallback
- Drop ASCII `input text` fallback (NPE на Android 15)
- Fix `result=0 → raise` логика (ADBKeyBoard не вызывает setResultCode)

## Caption fill rate progression (2026-05-03)

| Time | Window | caption_fails | published | total |
|---|---|---:|---:|---:|
| 14:00-15:13 | до PR#12 | 52 | — | — |
| 15:13-17:01 | PR#12 (instrumentation) | 23 | 1 | 31 |
| 17:01-18:21 | PR#13 (720s recording) | 19 | 0 | 29 |
| 18:21-18:51 | PR#14 (tight retry) | 8 | 0 | 9 |
| 18:51-20:00 | **PR#15 (ADB_INPUT_B64) ✅** | **0** | **13** | 28 |

## Каскад diagnoses (chronological)

1. **CRLF в caption** — INVALIDATED (manual phone 19 принимал CRLF)
2. **Anti-bot detection** — INVALIDATED (manual работал на проде с flagged accounts)
3. **AutoCompleteTextView intercept / Samsung Pass autofill** — INVALIDATED (autofill включён везде)
4. **Timing race / stale InputConnection** — INVALIDATED (tight retry с re-focus всё равно фейлил)
5. **Shell escape в adb_text wrapper** ✅ **CONFIRMED**

Lesson: `adb_text: clipboard OK` log line был ключевой signal — ADBKeyBoard fail'ил silently и wrapper переходил на clipboard. Эту строку видели много раз но не recogized как red flag — она выглядела как "успех".

## Все PRs сессии 2026-05-03 (chronological)

| PR | SHA | Описание | Status |
|---|---|---|---|
| #12 | e36ea50 | instrumentation: enriched verify_failed meta | shipped 15:13 |
| #13 | a2a35bb | bump screenrecord time-limit 300→720 | shipped 17:01 |
| #14 | 8303047 | tight retry loop, drop dead clipboard_paste IG-helper | shipped 18:21 |
| #15 | eaf724c | **adb_text → ADB_INPUT_B64 (root cause fix)** | **shipped 18:51, validated 19:14, confirmed 20:00** |

## Артефакты

- `adb_utils.py:127-178` — обновлённый `adb_text` (B64 path)
- `tests/test_adb_text_b64_path.py` — 7 unit tests
- `publisher_instagram.py:2168-2230` — упрощённый caption retry loop (3x adb_text, без dead clipboard)
- `tests/test_caption_tight_retry.py` — 5 integration tests
- `tests/test_caption_diagnostics_helpers.py` — 17 instrumentation tests

## Что НЕ закрыто

- **switch_failed_unspecified**: 5 fails post-PR#15 — другая категория (silent hang в `ig_2_profile_tab_fg_guard`). 181 подобных за 7 дней. Отдельный track.
- **ig_upload_confirmation_timeout**: 3 fails post-PR#15 — upload-stage, не caption.
- **42 orphan caption_fail задачи** (без pq row) не были re-queued — pq был cleaned.
