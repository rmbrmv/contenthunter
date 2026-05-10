# IG `ig_gallery_no_video_candidate` post-mortem — Mode A shipped, Mode B open

**Дата:** 2026-05-10
**Статус:** Mode A ✅ shipped (PR #26 merged `4643c7d`), Mode B ⏳ backlog
**Trigger:** triage 24h IG fails показал 14 шт `ig_gallery_no_video_candidate` (новая категория, не было в memory от 2-3 дней назад)

---

## TL;DR

`ig_gallery_no_video_candidate` появился впервые 2026-05-09 (1 fail) и взлетел 2026-05-10 (13 fails на 3 разных raspberry). Под одним error_code оказались **два distinct fail-mode**:

| Mode | ~% fails | Что | Status |
|---|---|---|---|
| **A** | ~30% | Android camera permission dialog overlay над IG gallery picker | ✅ shipped |
| **B** | ~70% | Google Play Store на странице TikTok Studio в foreground вместо IG | ⏳ backlog |

Error code сам по себе — **observability win** от commit `6815c3b` (2026-05-08 RC-8 D2/D3): убрал blind-tap fallback `(540, 721)` и сделал fail-fast. Эти fails существовали ДО, маскированные под другие error_codes.

---

## Phase 1 — Root Cause Investigation

### Hypothesis chain (eliminated)

| # | Hypothesis | Verdict |
|---|---|---|
| H1 | Device-localized на phone #19 | ❌ опровергнуто — fails на raspberry 1, 2, 9 |
| H2 | Switcher matched=False | ❌ опровергнуто — есть 2 done с matched=False, 4 fails с matched=True |
| H3 | Регрессия от MediaStore-fix `2a2ebb8`/`14570a1` (2026-05-09) | ❌ опровергнуто — `_ms_query` не вызывается в gallery picker code path |

### Confirmed root cause

Multi-modal по физическому состоянию устройства в момент `_save_debug_artifacts('instagram_gallery_no_video')`:

**Mode A — task 4477 (clickpay_team @ raspberry=9, 11:27 UTC):**
- Скриншот: реальный IG gallery picker с ClickPay видео-thumbnails
- Поверх — Android system permission dialog: «Разрешить приложению Instagram снимать фото и видео?» с 3 кнопками cy=1764 («При использовании приложения» / «Только в этот раз» / «Запретить»)
- `first_clickables`: 3 элемента (540, 1764), (540, 1764), (540, 1761) с empty desc — соответствует кнопкам диалога
- Парсер не находит «видео»/«video» в content-desc → fail-fast RC-8

**Mode B — tasks 4419/4425/4474 (3 разных raspberry, 3 разных времени):**
- Все 3 скриншота показывают **Google Play Store на странице TikTok Studio**: rating 4.7, "443 тыс отзывов", "скриншот 1 из 6", кнопка «Установить» 
- 3 разных md5 → не S3 collision, реально воспроизводится на разных устройствах
- `first_clickables` task 4419: 11 elements включая «средняя оценка 4,7», «возрастные ограничения 12+», «скриншот 1-4 из 6», «подробнее описание» — это Play Store UI, не IG
- Publisher проходит шаги IG (camera→REELS→gallery→select) формально, но устройство уже в Play Store

### Evidence-Mechanism gap для Mode B

Между шагом 3 (REELS mode) и шагом 4 (открытие галереи), publisher блайнд-тапает `(95, 1995)` если 'Галерея' / 'Gallery' / 'галерея' не нашлась в UI:

```python
# publisher_instagram.py:1252
gallery_tapped = self.tap_element(ui, ['Галерея', 'Gallery', 'галерея'])
if not gallery_tapped:
    log.info('  Галерея через текст не найдена — тапаем (95,1995)')
    self.adb_tap(95, 1995)
```

**Гипотеза Mode B:** на Samsung 1080×2340 координата `(95, 1995)` ≈ bottom-left, ~85% screen height. Если IG показывает permission re-request screen (не camera/Reels), эта координата может попасть на system nav button (Recents) → открывает Recents → выбирает предыдущий app (Play Store на TT Studio). **Не подтверждено** — нужна diag instrumentation.

---

## Phase 4 — Implementation (Mode A only)

### Files changed

`publisher_instagram.py` (+52 lines):

1. Class const `_IG_CAMERA_PERMISSION_TRIGGERS` — markers для detection.
2. Method `_dismiss_camera_permission_dialog(ui) -> bool`:
   - Case-insensitive substring match триггеров (`ui.lower()` per memory `feedback_python_in_op_case_sensitive.md`)
   - `tap_element(['При использовании приложения', 'While using the app'], exact=True, clickable_only=True)` — exact для anti-substring-match с заголовком диалога, clickable_only для anti-non-clickable TextView
   - **НИКОГДА не тапает «Запретить»** — задано тестом
   - log_event `category=ig_camera_permission_granted` для KB analytics
3. Wired в Шаг 5 attempt-loop ДО `tap_element(['ОК','OK','Понятно','Разрешить'])` и ДО gallery-open break-check

`tests/test_dismiss_camera_permission.py` (+109 lines, новый файл):

1. `test_dismiss_camera_permission_taps_while_using_when_dialog_present` — позитив + anti-«Запретить» guard
2. `test_dismiss_camera_permission_uses_exact_clickable_only` — assert kwargs.exact + clickable_only True
3. `test_dismiss_camera_permission_no_dialog_returns_false` — idempotency
4. `test_dismiss_camera_permission_logs_event_on_grant` — observability assert
5. `test_dismiss_camera_permission_returns_false_when_tap_fails` — outer-loop retry contract

TDD: red (5 fails по `AttributeError: ... has no attribute '_dismiss_camera_permission_dialog'`) → green (все 5 pass).

### Adjacent test impact

71 IG-adjacent тест зелёный. 2 pre-existing fails на main (TT switcher `account_switcher.py:2024 AttributeError`, IG camera recovery counter mismatch) — подтверждены на prod main `14570a1`, не моя регрессия.

### Deploy

- PR #26 → merge via gh API (`gh api -X PUT .../pulls/26/merge`) — обходит локальный checkout (main был занят prod worktree)
- merge SHA `4643c7d`
- `git pull origin main` на /root/.openclaw/workspace-genri/autowarm/ — fast-forward
- PM2 autowarm (id 34) — Node.js server.js spawn'ит Python per-task → no pm2 reload needed
- Verified `_dismiss_camera_permission_dialog` в prod publisher_instagram.py:146

---

## Live verification ✅ — task 4521 (re-queue 4477)

**Same task, was failing yesterday, published successfully today.**

Re-queue path (memory `reference_publish_requeue_path.md`): `UPDATE publish_queue SET status='pending', publish_task_id=NULL WHERE id=1824` → dispatchPublishQueue 5min cycle создал pt 4521 (raspberry=9, clickpay_team).

### Flow подтвердил Mode A fix (2026-05-10 15:55-16:09 UTC)

| ts | event | meaning |
|---|---|---|
| 16:02:07 | Шаг 4 — открытие галереи | gallery navigation start |
| 16:02:15 | blind-tap diag before/step4_initial | Mode B diag fired (см. ниже) |
| 16:02:31 | blind-tap diag after/step4_initial | dialog persisted, blind-tap не помог |
| **16:02:56** | **camera permission granted (while-in-use)** | **Mode A fix fired** |
| **16:03:01** | **camera permission granted (while-in-use)** | **Mode A fix fired (2nd dialog instance, 5s later)** |
| 16:05:25 | Шаг 6 — редактор Reels | gallery selected, video loaded |
| 16:06:20 | caption ВЕРИФИЦИРОВАН (235 символов) | caption fill OK |
| 16:06:31 | кнопка Поделиться нажата | Share triggered |
| 16:06:50 | загрузка подтверждена — MainTabActivity | upload OK |
| 16:07:09 | post_url_captured: clickpay_team/reels | URL captured ✅ |

`status=awaiting_url`, `error_code=NULL`, `post_url=https://www.instagram.com/clickpay_team/reels/`.

**Mode A fix confirmed working in production.** Re-queue test предсказательно подтвердил root cause.

### Mode B — hijack hypothesis ❌ refuted (at blind-tap moment)

`_log_blind_tap_diag` поймал topResumedActivity до и после blind-tap (95, 1995):

```
before: com.instagram.android/com.instagram.modal.ModalActivity t407
after:  com.instagram.android/com.instagram.modal.ModalActivity t407
```

**Same activity, same task ID.** blind-tap (95, 1995) НЕ вызывает foreground hijack. ModalActivity — это IG's собственный screen (camera/composer + permission dialog overlay), не Play Store.

**Что это значит:**
- Гипотеза «blind-tap → Recents → Play Store» опровергнута для этого task'а.
- Play Store-скриншоты в task'ах 4419/4425/4474 (вчера) появились не в момент blind-tap, а позже — скорее всего в момент `_save_debug_artifacts` ПОСЛЕ fail-fast (строка 1322 publisher_instagram.py).
- Mechanism Play Store hijack пока неясен — возможно драйвится anti-bot, ad-deeplink или drift'ом во время parser-loop'а.
- Followup diag: расширить capture на fail-moment (line 1322) и в parser-loop iteration'ах.

## Sample 2 — task 4522 (re-queue 4474 click_and_pay) ✅

**Контекст:** task 4474 yesterday показывал Play Store TT Studio screenshot. Re-queue UPDATE pq 1806.

**Result:** `awaiting_url`, post_url=`https://www.instagram.com/click_and_pay/reels/`, error_code=NULL.

**Mode A grants: 0** (helper НЕ зафайрил).
**Mode B diag:** `before` + `after` = `com.instagram.android/com.instagram.modal.ModalActivity t326` (stays IG, hijack refuted).

### Cascade effect — permission sticky после первого grant

Sample 1 (4521) granted «При использовании приложения» в 16:02:56. Permanent grant within app → IG больше не показывает dialog на этом телефоне.

Sample 2 (4522) на **том же raspberry=9** через 22 минуты — dialog не появился, gallery открылась напрямую через blind-tap. Mode A helper не сработал потому что **не было что dismissing**.

**Implication для fleet:** После того как каждый из 19 телефонов получит хотя бы одну успешную публикацию IG через Mode A fix, camera permission осядет permanently. Текущая волна fails 2026-05-10 — one-off (видимо после OS update / IG app update / permission reset). Без regression-проблем permission не сбросится.

### Mode B Play Store screenshots — transient device state

Yesterday's tasks 4419/4425/4474 (Play Store TT Studio) — НЕ reproducible после Mode A fix. Возможные causes (не критично):
- Recents stack contained Play Store from previous task / autonomous app activity
- Anti-bot redirect (rare, transient)
- IG app crash during gallery navigation → fell through to launcher → Recents → Play Store

После Mode A fix gallery открывается чисто, blind-tap (95, 1995) не triggers state drift. Mode B как отдельный issue **closed pending re-occurrence** — если в next 24-48h `ig_gallery_no_video_candidate` count drop'ится >50%, считаем fixed. Если Play Store продолжает плодиться — extended diag (capture в parser-loop iterations + at fail-moment).

---

### Outstanding query for fleet-wide Mode A confirmation

```sql
SELECT id, account, raspberry, status, error_code, updated_at
FROM publish_tasks
WHERE events @> '[{"meta": {"category": "ig_camera_permission_granted"}}]'::jsonb
  AND updated_at >= '2026-05-10 14:00'
ORDER BY updated_at DESC;
```

---

## Mode B — Diag deployed ⏳ awaiting live evidence

### Status 2026-05-10

PR #27 merged `4be50f5` в prod main. Helper `_log_blind_tap_diag(stage, label, ui_xml)` добавлен в `publisher_instagram.py:180` и wired в Шаг 4 line 1342+1345 (before/after blind-tap (95, 1995) initial). Behavior preserved.

Helper эмитит `log_event(category='ig_gallery_blind_tap_diag', stage, label, topResumedActivity, ui_dump_url)`. Best-effort — dumpsys/S3 exceptions swallow'аются.

### Evidence query

```sql
SELECT id, account, raspberry, status, error_code,
  jsonb_path_query_array(events,
    '$[*] ? (@.meta.category == "ig_gallery_blind_tap_diag")'
  ) AS diag_events
FROM publish_tasks
WHERE updated_at >= '2026-05-10 15:00'
  AND events @> '[{"meta": {"category": "ig_gallery_blind_tap_diag"}}]'::jsonb
ORDER BY updated_at DESC LIMIT 10;
```

### Decision tree после 3-5 samples

- topResumedActivity stays `com.instagram.android` before/after → hijack гипотеза **опровергнута**, копать дальше (IG internal screen drift, permission re-prompt, etc.)
- topResumedActivity drift'ит на `com.android.vending` (Play Store) / `com.android.systemui` (Recents) / `com.sec.android.app.launcher` → hijack **confirmed**

### Followup PR (если hijack confirmed)

1. **Удалить blind-tap** — заменить на coord lookup gallery-button через bounds (как `_tap_create_reels_tile_strict`). Если 'Галерея' не нашлась через tap_element, fail-fast с structured error_code (e.g., `ig_gallery_button_not_found`) — не оставлять рандомный tap.
2. **Pre-Шаг-5 foreground guard** — проверять `topResumedActivity` startswith `com.instagram.android` перед каждым шагом. Раннее abort если drift.
3. **Recents-overlay dismiss helper** — если recents открылся, нажать KEYCODE_BACK + force-stop foreign packages.

### Followup PR (если hijack опровергнут)

- Удалить diag (helper остаётся как infra), копать в IG internal state — возможно camera permission dialog, возможно draft continuation, возможно highlights empty state.

---

## Связанные

- commit `6815c3b` (2026-05-08 RC-8 D2/D3) — родитель fail-fast logic
- commit `018ac260c` (2026-05-09 evidence MediaStore outage) — несвязано
- memory `feedback_silent_crash_layered.md` — RC-8 series тоже layered discovery
- memory `feedback_user_diagnosis_is_signal.md` — пользователь сказал «локально на phone 19», но проверка опровергла
