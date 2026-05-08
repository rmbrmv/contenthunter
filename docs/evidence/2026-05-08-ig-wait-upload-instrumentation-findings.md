# IG `_wait_instagram_upload` instrumentation — root cause findings

**Дата:** 2026-05-08
**Sub-project:** P1.1 IG post-switch regressions — Phase 1.7 verification
**Spec:** `docs/superpowers/specs/2026-05-08-ig-wait-upload-diag-instrumentation-design.md`
**Plan:** `docs/superpowers/plans/2026-05-08-ig-wait-upload-diag-instrumentation-plan.md`
**Deploy:** prod merge `2443160` 2026-05-08 11:42:27 UTC

---

## TL;DR

Mode **B** (Share tap не вызывает IG progression) подтверждён на post-deploy fail task 4123. **Editor screen остаётся visible 10 минут после tap'а Share button** — caption text, "Новое видео Reels" header, clickable Share button all unchanged. `tap_element(['Поделиться'], clickable_only=True)` нашёл правильный element (`com.instagram.android:id/share_button`, bounds `[563,2025][1035,2149]`, center 799,2087) и `adb_tap` выполнился, но IG никак не отреагировал.

Mode A (IG version drift) опровергнут — `MainTabActivity` корректно достигается на success path (4098 — 28 sec post-Share транзишн через `Создать видео Reels` SUCCESS_KW match).

Mode C (post-share transient dialog) не observed на 4123.

GrantPermissionsActivity subset (24% of Phase 1 wait events) — отдельный track для permission dialog handler.

---

## Live evidence (post-deploy 2026-05-08 11:42:27 UTC)

За 75 минут после deploy получено 2 IG задачи с iter0_diag events:

### Task 4098 `click_and_pay` — SUCCESS path (awaiting_url)

| Time | Event |
|---|---|
| 12:38:05 | caption ВЕРИФИЦИРОВАН (113 chars) |
| 12:38:13 | `кнопка Поделиться нажата` |
| 12:38:22 | **iter0_diag**: activity=`ModalActivity t279`, share_candidates=**1** (`direct_share_button` desc=`Поделиться` bounds=`[919,1412][1043,1536]`) |
| 12:38:40 | wait 0: activity=`InstagramMainActivity t279`, ui=`'Видео Reels от ...'` (post-publish Reels list) |
| 12:38:41 | **`загрузка подтверждена — Создать видео Reels`** (SUCCESS_KW match!) |

Между Share tap и iter0_diag прошло **9 sec**. К моменту iter0 IG уже **за editor** (post-publish Reels confirmation screen). share_candidates показывает только 1 элемент — `direct_share_button` (DM-share secondary action). Это **не editor screen**.

### Task 4123 `just_clickpay` — FAIL path (`ig_upload_confirmation_timeout`)

| Time | Event |
|---|---|
| 12:45:01 | caption ВЕРИФИЦИРОВАН (113 chars) |
| 12:45:09 | `кнопка Поделиться нажата` |
| 12:45:35 | **iter0_diag**: activity=`ModalActivity t341`, share_candidates=**3** |
| 12:45:53 | wait 0: activity=`InstagramMainActivity t341`, ui=editor caption text |
| 12:46:39 | watchdog 90s |
| 12:55:05 | **timeout_diag**: activity=`InstagramMainActivity t341`, share_candidates=**3** (identical to iter0) |

Между Share tap и iter0_diag — **26 sec**. К моменту iter0 IG **STILL on editor**. share_candidates 3 entries:

```json
[
  {"text": "Поделиться также в...", "rid": "id/title",        "clickable": false, "bounds": "[147,1694][647,1751]"},
  {"text": "",                       "rid": "id/share_button", "clickable": true,  "bounds": "[563,2025][1035,2149]", "content_desc": "Поделиться"},
  {"text": "Поделиться",              "rid": "",               "clickable": false, "bounds": "[688,2062][910,2112]"}
]
```

Главный publish Share button (#2) — `id/share_button`, clickable=true, center (799, 2087). Этот element и есть target для `tap_element(['Поделиться'], clickable_only=True)`.

UI dump на iter0 и на timeout (10 минут спустя!) **идентичны** — те же 111 nodes, та же caption text, тот же Share button. **Editor НЕ меняется** despite 30 polling iterations.

---

## Code analysis

`publisher_base.py:1526` `tap_element(ui, patterns, exact=False, clickable_only=True)`:
```python
for node in root.iter('node'):
    t = node.get('text','').strip()
    d = node.get('content-desc','').strip()
    cl = node.get('clickable','')
    label = (t + ' ' + d).lower()
    if clickable_only and cl != 'true': continue
    for p in patterns:
        if p.lower() in label:
            cx,cy = center of bounds
            self.adb_tap(cx, cy)
            return True
```

С `clickable_only=True` отфильтровывает не-clickable nodes. На 4123 editor screen только ОДНА clickable node содержит "Поделиться" — main `share_button` (verified offline parse). Tap_element returns True, log "Поделиться нажата" emit'ится. ADB `input tap 799 2087` shell command fired.

**И в этом момент IG ничего не делает.** 26 секунд спустя editor unchanged. 10 минут спустя editor unchanged.

---

## Hypothesis (refined)

`adb_tap(799, 2087)` физически отправляет touch event на правильную координату. IG **получает** touch event но не интерпретирует его как click on Share button. Возможные первопричины:

**B.1 — Race condition: editor layout не финализирован.** После caption fill IG может анимировать layout (keyboard hide, soft layout shift). Share button bounds correct in dump, но в момент tap button может быть в transient state (alpha < 1, или TouchInterceptor другого view, или re-layout in progress). `dump_ui` snapshot не отражает touch-target actual state.

**B.2 — IG anti-bot heuristic.** IG detects synthetic taps (no preceding finger-down/up motion events, no accelerometer signal, identical timing patterns) и silently игнорирует. Это known concern для automation на newer IG versions.

**B.3 — Long caption layout shift.** 113-char caption может вызвать caption_input_text_view auto-expand, layout reshuffle, и Share button bounds в snapshot уже stale by tap time.

Из 3 sub-causes наиболее вероятна **B.1** (race) — supported observation что 4098 (success) и 4123 (fail) одинаковые caption length (113 chars), same timing path, but different outcome → suggests stochastic timing-dependent failure.

---

## Fix direction (out of scope этого PR — отдельный sub-project)

**Минимальный fix (Tier 1):** post-Share verification + retry.

В `_wait_instagram_upload`, после iter0 capture, проверить:
- если activity == `ModalActivity` И ui всё ещё содержит `id/caption_input_text_view` И clickable `id/share_button` visible
- → editor НЕ progressed → **re-tap Share button** (1-2 retry с 2-3 sec sleep)
- если после retries editor visible — fail-fast с error_code `ig_share_tap_no_progress` (отдельный новый код, отличный от `ig_upload_confirmation_timeout`)

Это даёт:
1. Recovery path для transient B.1 race condition
2. Distinct error code для триажа vs general timeout
3. Existing 30-iter timeout остаётся as final fallback

**Расширенный fix (Tier 2 — если Tier 1 не покрывает):** detect editor-stuck condition и попробовать `am start` Share intent или alternative tap method (long-press, multi-finger, hardware key combo).

**Дополнительный track:** GrantPermissionsActivity handler (24% of Phase 1 wait events) — separate spec.

---

## Decisions

- ✅ Mode B confirmed via iter0+timeout instrumentation. Sub-cause B.1/B.2/B.3 — нужен Tier 1 fix чтобы наблюдать residual rate per cause.
- ✅ Mode A disproven: MainTabActivity reachable (success path 4098).
- ⏭️ **Next sub-project:** Tier 1 fix spec — post-Share editor-stuck retry + new error_code `ig_share_tap_no_progress`.
- ⏭️ **Operational track:** GrantPermissionsActivity handler — separate sub-project.
- ⚠️ **Sample size:** 1 fail + 1 success post-deploy — limited evidence. Larger sample (3-5 fails) укрепил бы B.1/B.2/B.3 distribution. Diagnostic instrumentation остаётся в prod, более данные накопятся за следующие 6-12 часов.

---

## Связанные памяти

- `project_ig_post_switch_regressions_2026_05_08.md` — investigation memory
- `project_ig_caption_fill_persistent_bug.md` — predecessor IG-fix
- `feedback_subagent_force_push_risk.md` — incident от Task 8 deploy
- `feedback_user_diagnosis_is_signal.md` — гипотеза = средний вес
