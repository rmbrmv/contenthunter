# Backlog tickets

## 2026-05-15 — TT commercial-music modal handler (WP #75)

### `tt_upload_confirmation_timeout` (новая сигнатура «Коммерческие треки → TikBiz playlist») — ✅ SHIPPED 2026-05-15 PR #66

Триаж TT-фейлов за день: 175 fails, 166 = сетевая `adb_devices_unreachable` (исключена, network уже починен), top non-network = 3 явных `tt_upload_confirmation_timeout` (tasks 6495/6510/6512) + 1 orphan (5202) с той же сигнатурой = 4/9 ≈ 44% non-network падений из одной корневой. На всех 3 screencast'ах TT застрял на одной и той же странице **«Коммерческие треки → TikBiz playlist»** (треки PONCHET, Yang Salah, Beat Automotivo, Happy/Vide..., Countless...) — публикатор не закрывает модал, AI vision возвращает `{x:null,y:null}` для кнопки «Опубликовать», 3-мин `wait_upload` timeout. Разные аккаунты (axilor_prive/brand, clickpay_under), разные устройства (RF8Y80ZTVFZ/RF8YA09S90H/RFGYC31P94Z), разные raspberry (#1/#9) — баг воспроизводим, не device-state. Это **НЕ** music-rights confirmation (диалог *согласия*, закрыт PR #28/#32), а новый **selector с принудительным выбором** коммерческого трека.

PR GenGo2/delivery-contenthunter#66 (squash `2dd53ff`): **3-level detector** (strict + fallback + evidence-only, аналог music-rights) → **cancel-select ladder** (`iter ≤ 2` → tap X, `iter > 2` → выбор 1-го трека через ✓, MAX=4 → `tt_commercial_music_stuck`) → wired в 2 hook'а (`_publish_share_loop` Шаг 5 — основной перед XML-сканом «Опубликовать», `_wait_upload_confirmation` outer loop — defensive). Env kill-switches `TT_COMMERCIAL_MUSIC_HANDLER_ENABLED` (default ON) + `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED` (default OFF). 9 новых event categories для триажа. 40 unit + 1 integration smoke + 305 passed в TT regression. Subagent-driven-development через 15 plan tasks, codex-review round 2 = 0 findings, final reviewer = ready to merge. PM2 `restart 34 autowarm` + `restart 33 autowarm-testbench` 18:22 UTC.

**24h live verify deadline ~2026-05-16 18:22 UTC** — acceptance:
1. 0 fails `tt_upload_confirmation_timeout` с сигнатурой `ai_find_tap_no_coords` на Publish-кнопке.
2. Распределение `tt_commercial_music_cancelled` vs `_track_selected` за 24h. Если 100% → select, cancel-X не закрывает модал, нужен switch policy на select-первым (iter2).
3. Нет `tt_commercial_music_stuck` events.
4. Если `tt_commercial_music_unhandled_suspect` (evidence-only) сработает — включить `TT_COMMERCIAL_MUSIC_FALLBACK_ENABLED=true` и собрать XML dumps в `/tmp/autowarm_ui_dumps/`.

Memory: [[project_tt_commercial_music_modal_wip]]. Spec/plan/evidence: `docs/superpowers/specs/2026-05-15-tt-commercial-music-modal-handler-design.md` + `docs/superpowers/plans/2026-05-15-tt-commercial-music-modal-handler.md` + `docs/evidence/2026-05-15-tt-publish-fails-triage.md`.

### Открытые runner-up'ы из триажа 2026-05-15 (не затикечены, малый объём)

- **`tt_account_sheet_closed_before_parse` (2/день)** — bottomsheet со списком аккаунтов не открылся, target не добавлен на устройство. По msg выглядит как data-issue (онбординг аккаунта), не код-баг. Если повторится 7+ дней — взять в discovery.
- **`tt_profile_tab_broken` (2/день)** — tap «Я» не открывает профиль. Memory `project_tt_post_switch_renav_shipped` упоминает recovery PR #34. 2/день — приемлемый шум, не takeaction. Если вырастет — взять.
- **`tt_post_switch_verify_unrecoverable` (1/день)** — `tt_post_switch_handle_unknown` без recovery success. PR #34 (post-switch verify recovery) должен покрывать; пристальнее посмотреть если повторится 5+/день.

## 2026-05-15 — YT post-switch upload state normalization (WP #74)

### `yt_gallery_no_video_candidate` — ✅ SHIPPED 2026-05-15 PR #64

Триаж YT-фейлов за день: 166 fails, 164 = сетевая `adb_devices_unreachable` (исключена, network уже починен), 2 = `yt_gallery_no_video_candidate` (task 6513 oracle_spacee + 6515 oraclevisionn, raspberry 8, проект «Эзотерика Oleg»). На скринкастах оба раза YT после успешного `_ensure_correct_account` остаётся не в upload-state: 6513 завис на системном permission-диалоге «Откройте YouTube доступ к камере и микрофону», 6515 — на Shorts feed с открытой `Описание` bottom-sheet. Watchdog «post-account-switch» бил через 120s, picker фейлился с `all_clickable_count=0`.

PR #64 (3 коммита, squash `4722b81`): **A** `_normalize_yt_state_pre_upload` — `am force-stop` + `am start LAUNCHER` + 2 итерации permission-tap'ов перед probe'ом меню создания; **B** в `_select_gallery_video` parse loop добавлены 'При использовании приложения', 'Только в этот раз', 'Allow', 'Понятно'; **C** meta при fail-fast обогащена `top_resumed_activity` + `current_package` (категория `yt_gallery_no_video_candidate` сохранена — dashboards). 23 теста зелёные, codex без замечаний, prod `pm2 restart 34 autowarm` 16:42 UTC.

**24h live verify deadline ~2026-05-16 16:42 UTC** — acceptance: 0 fails `yt_gallery_no_video_candidate` за 24h при ненулевом потоке YT-задач. Memory: [[project_yt_post_switch_state_normalize_shipped]]. Spec/plan: `docs/superpowers/specs/2026-05-15-yt-post-switch-upload-state-normalization-design.md` + `docs/superpowers/plans/2026-05-15-yt-post-switch-upload-state-normalization.md`.

## 2026-05-15 — WP 63 scheduler status sync — ✅ SHIPPED

`fix(scheduler)` PR GenGo2/validator-contenthunter#12 (merged `520aaec`) — клиентский планировщик показывал «✅ Одобрено» уже когда `moderation_status=passed`, не учитывая `content_status`. Для контента с дублем (`passed + needs_review`) автовыкладка не запускалась (вебхук гейтит на `ContentStatus.approved` в `validation.py:132`), но UI рисовал готовность. Чистый классификатор в `frontend/src/utils/slotStatus.ts` + 23 unit-теста + согласованные цвет рамки/пилюли. WP 63 → `Тестирование`, ждём визуального подтверждения Анастасии. Evidence: `docs/evidence/2026-05-15-wp63-scheduler-status-fix-shipped.md`. Memory: [[project_wp63_scheduler_status_shipped]].

**Follow-up (low):** унификация manager-side `frontend/src/components/calendar/SlotCard.vue` на тот же `slotStatusInfo` — бага сейчас нет (manager уже смотрит на `content.status` напрямую), но единый классификатор уменьшит риск регрессии в будущем (из памяти `feedback_validator_two_slot_renderers` — два места рендеринга).

## 2026-05-14 — TT post-switch verify `@handle`-priority (WP #67)

### `tt_post_switch_verify_unrecoverable` — ✅ SHIPPED 2026-05-14 PR #62

Крупнейший незатикеченный баг дня (16/58 TT-падений, 16 устройств). `get_current_account_from_profile` брала верхний токен, прошедший `_looks_like_username` — на экране профиля TikTok это имя профиля / badge-счётчик НАД `@handle`. Свитч проходил, verify давал ложный mismatch. Фикс: ведущий разряд сортировки `is_bare` (`@`-токены приоритетнее). PR GenGo2/delivery-contenthunter#62 (squash `433c5b2`), в проде. Live smoke: 3/3 ре-выкладок распознали аккаунт через fast-path, 0 `tt_post_switch_verify_unrecoverable`. Memory: [[project-tt-post-switch-verify-handle-fix]]. Evidence: `docs/evidence/2026-05-14-tt-publish-failures-triage-eod.md`.

**24h soak deadline ~2026-05-15 16:00 UTC** — acceptance: `tt_post_switch_verify_unrecoverable` 16/24h → ~0. Query — в evidence-доке § «Запросы».

### Открытые runner-up'ы из триажа 2026-05-14 (не затикечены)

- **`tt_upload_confirmation_timeout` (7/день)** — свитч+verify проходят, видео заливается, экран подтверждения не детектится в таймаут (стадия `wait_upload`, не switcher). **Surfaced снова в smoke этого фикса** (tasks 5998/5999 дошли до publish-фазы и упали тут) — следующий кандидат на фикс по объёму.
- **`tt_profile_tab_broken` (5/день)** — tap «Я» не открывает профиль. PR #50 (TT security prompt dismiss) целился сюда с acceptance `< 2/24h` — 5/день на 2026-05-14 говорит, что PR #50 закрыл не всё; проверить на 24h-verify PR #50, возможно нужен отдельный заход.
- **retry-suffix gap мэппера** — триаж переподтвердил: `_SWITCHER_STEP_TO_CATEGORY` не матчит `_retry_N` шаги → реальная категория теряется в `publish_failed_generic` / `switch_failed_unspecified`. Уже описан ниже (секция «`switch_failed_unspecified` mapper retry-suffix gap»). 4 задачи 2026-05-14 замаскированы так.

## 2026-05-14 — WP 53 phantom schemes follow-up

### Router-level `unic_schemes` reads unfiltered (low priority)

WP 53 fix (PR #10) filtered `id > 0` in `schemes_service.get_schemes_with_preferences` + `get_summary` — the client-facing schemes screen. Three router-level reads in `backend/src/routers/schemes.py` still read `unic_schemes` unfiltered:

- `check_readiness` (`:141`) — `SELECT COUNT(*) FROM unic_schemes` → `total_schemes` (gates `previews_ready`)
- `generate_previews` (`:349`) — `SELECT * FROM unic_schemes ORDER BY id` → schemes sent to the render worker
- `approved_scheme_ids` (`:450`) — fallback `SELECT id FROM unic_schemes ORDER BY id`

Not urgent: the leak source is closed (`test_schemes_deficits._cleanup_project` now deletes `id <= -1`), so phantoms won't recur. But these are a latent inconsistency if a service row ever reappears via another path. Add `WHERE id > 0` for defense-in-depth when next touching that file. Evidence: `docs/evidence/2026-05-14-wp53-phantom-schemes-fix-shipped.md`.

## 2026-05-13 session follow-ups

### 24h verify (next day morning)

Четыре shipped PR в один день требуют 24h-verify SQL:

| PR | Topic | Deadline (UTC) | Acceptance |
|---|---|---|---|
| #48 | Watchdog ping regression | 2026-05-14 08:40 | Pi 3+5 `switch_failed_unspecified` < 5 / 24h |
| #49 | IG share OK fallback (Tier 1.5) | 2026-05-14 11:45 | `ok_rescued_24h / ok_attempted_24h ≥ 30%` |
| #50 | TT security prompt dismiss | 2026-05-14 13:25 | `tt_profile_tab_broken < 2/24h` AND `tt_security_prompt_dismissed > 0` |
| #52 | TT Pattern B (probe-and-pivot) | 2026-05-14 17:30 | `tt_account_sheet_closed_before_parse` ≤ 5/24h AND new codes ≤ 3/24h combined |

SQL pack в `docs/evidence/2026-05-13-*.md § "24h verify"` для каждого PR. PR #52 SQL — `jsonb_array_elements WITH ORDINALITY` (terminal `failed` event без category, нужно сканировать назад). После прогона — обновить evidence docs + memory entries (close OR iterate).

### TT Pattern B — `tt_account_sheet_closed_before_parse` ✅ SHIPPED 2026-05-13 PR #52

12-commit branch (`be62872..69a2dea`) squash-merged как `76ecd4f`. Probe-and-pivot orchestrator закрывает 19/24h root cause (TT app update — username tap открывает Stories/LIVE viewer вместо account-switcher bottomsheet). Memory: [[project_tt_pattern_b_shipped]]. Evidence: `docs/evidence/2026-05-13-tt-pattern-b-shipped.md`. Smoke pq 2149 live; 24h verify deadline 2026-05-14 17:30 UTC.

**Iteration #2 — 2-step settings-nested account switcher (HIGH priority, evidence in hand)**

Live smoke task 5572 (clickpay_go) post-hotfix: orchestrator successfully reached drawer search but `_find_tt_account_switcher_anchor_in_drawer` returned None. `drawer_labels[]` payload reveals new TT requires 2-step navigation: «Меню профиля» → «Настройки и конфиденциальность» → settings page → «Управление аккаунтами». Spec for iter#2 needed: add a settings-nested lookup pass to the orchestrator when first drawer search returns None. Anchors: `['настройки и конфиденциальность', 'настройки', 'settings and privacy', 'settings']`. Cap nesting at 1 level. See `docs/evidence/2026-05-13-tt-pattern-b-shipped.md` § Second smoke for the full drawer label list.

**Open follow-ups (Minor, from final holistic opus review):**
1. Inline-vs-helper asymmetry on `tt_account_sheet_closed_before_parse` emission (functionally fine).
2. `menu_dump` redundancy with `back_dump` (~1-2s extra).
3. `_tap_profile_header` internal `_save_dump` overwritten by orchestrator under same step name (pre-existing).
4. End-to-end test of menu-path through `_switch_tiktok` missing — smoke is only true verification. **CAUGHT BY THIS — smoke caught `adb_shell→adb` regression (hotfix PR #54) that 6 codex rounds + 48 unit tests missed.**

### `switch_failed_unspecified` mapper retry-suffix gap (new, 2026-05-13)

24h фон 25 fails, после декомпозиции:
- 17 pre-PR-#48 watchdog-killed — закроется по 24h verify PR #48
- 6 pre-PR-#48 other (вероятно тоже watchdog или race)
- **2 post-PR-#48 non-watchdog** — реальный остаток после сегодняшних deploy'ов

Корень: `_SWITCHER_STEP_TO_CATEGORY` в `publisher_kernel.py:76` НЕ знает retry-суффиксы (`tt_1_feed_retry_1`, `tt_3_open_list_retry_1` и пр.) → Pass-2 fallback resolver'а дефолтится на `switch_failed_unspecified`.

Sample failing steps post-PR-#48:
- task 5326 (TT, datj2k5): fail step `tt_1_feed_retry_1` — TT не запустился после post-switch retry restart. Должен мэппиться на `tt_app_launch_failed`.
- task 5296 (TT, relisme_co): fail step `tt_3_open_list_retry_1` — switcher's retry. Должен мэппиться на `tt_account_sheet_closed_before_parse`.

Fix варианты:
1. Strip `_retry_N` suffix в resolver Pass-2 перед lookup (1 line in `publisher_base._set_error_code_from_events`).
2. Явные entries для каждой retry-suffixed step в `_SWITCHER_STEP_TO_CATEGORY` (явнее, шире diff).

**Не блокер сегодня:** 2/24h, и часть «25» исчезнет после PR #48 verify. Чинить завтра после 24h-verifies (2026-05-14 morning UTC).

### AI Unstuck не firing — possibly self-resolved by PR #48

До PR #48 (08:40 UTC): AI Unstuck не firing 0/22 в TT timeout кейсах. Hypothesis: watchdog regression обрывал AI Unstuck до того, как он успевал что-то сделать. Per memory `project_watchdog_ping_regression_shipped` — теперь watchdog продлевается активностью. Проверить 24h: возвращается ли AI Unstuck к нормальной частоте.

### YT `yt_editor_upload_timeout` — ✅ ROOT-CAUSED + FIXED 2026-05-14 PR #56

**НЕ self-resolved PR #48.** Триаж 2026-05-14 (OpenProject #59) нашёл 3 свежих `yt_editor_upload_timeout` (tasks 5685/5717/5724) — топ-причина YT-падений за день (3/6), #3 за 7д (14). Root cause: post-switch verify возвращает `'unknown'` → degrade-to-pass всегда, даже когда YouTube не на переднем плане → publisher уходит в 5-мин editor poll вслепую. Скринкасты: device на рабочем столе / Google voice search / Facebook prompt. 14/15 за 7д имеют precursor `yt_post_switch_handle_unknown`.

Фикс — `_switch_youtube` post-switch loop: degrade-to-pass на `'unknown'` теперь gated проверкой foreground-пакета; чужой app в foreground → fail fast с `yt_post_switch_app_not_foregrounded`. PR #56 squash-merge `348d495`, в проде 2026-05-14. Evidence: `docs/evidence/2026-05-14-yt-publish-triage.md`. Memory: [[project_yt_post_switch_foreground_guard]].

**24h verify deadline 2026-05-15 ~13:00 UTC** — SQL в evidence doc § "24h verify". Acceptance: `yt_editor_upload_timeout` после `yt_post_switch_handle_unknown` резко падает, вместо зависаний — быстрый `yt_post_switch_app_not_foregrounded`. Residual ~1/15 (editor genuinely stuck при YT в foreground) остаётся под item ниже.

---

## YT stabilization follow-ups (2026-05-12 session)

### Шаг D — yt_editor_upload_timeout (после AI Unstuck)

**STATUS 2026-05-14:** дублирующий precursor-вариант (`yt_post_switch_handle_unknown` → editor poll вслепую) закрыт PR #56 — см. item «YT `yt_editor_upload_timeout` — ✅ ROOT-CAUSED + FIXED» выше. ОСТАЁТСЯ residual: ~1/15 за 7д имели `yt_editor_stuck_detected` БЕЗ precursor'а — YouTube был в foreground, но редактор реально завис. Вот этот случай — то, что не покрыто PR #56 и описано ниже.

13 fails/week pre-2026-05-13, single-pattern `YouTube: редактор timeout — Загрузить не найдено (после AI)` в `publisher_youtube.py:1199-1205`. AI Unstuck вызывается (`ai_unstuck_result=True`), что-то делает, но кнопка «Загрузить» не появляется. Screen recordings analysis на task'ах 4892/4444/4441. Hypothesis: editor в caption-screen с задержанной generation animation; AI не дожидается. Fix варианты: лучший detection caption-screen + skip AI, или post-AI wait+retry с другими criteria.

### Port `device_tz` to `publisher_helpers.parse_picker_thumbnail_date`

PR #45 (IG-only device-tz fix для phone #9 / Asia/Almaty) live в `publisher_instagram._ig_parse_thumbnail_date(desc, device_tz=None)`. После PR #43 (YT cross-project leak) IG имеет own copy с device_tz, YT использует `publisher_helpers.parse_picker_thumbnail_date` БЕЗ device_tz. Если YT начнут публиковать на не-MSK phones — будет False-mismatch. Port `device_tz` parameter в shared helper и rewire IG обратно на shared.

### Lead_Content_1 (и похожие) data-drift cleanup

Аккаунт в `factory_inst_accounts` с `gmail=NULL`, на phone в YT picker отсутствует (display name `Lead_Content `, suffix `_1` отсутствует, handle row отсутствует). Backfill no-match. Sticky 3 fails / 7d. Опции: (a) manual deactivation в БД; (b) automated `account_revision` post-scroll detector + auto-deactivate; (c) periodic backfill no-match log → daily TG bot notification.

**NB 2026-05-14:** не все `yt_picker_target_absent` / `yt_target_not_in_picker_after_scroll` — реальные отсутствия. Триаж iter2 (task 5856) доказал false-negative: аккаунт *присутствует* в picker'е, но matcher его не находит — см. item «YT picker — matcher игнорирует имя канала» ниже (#66). Этот data-drift item остаётся валиден только для *реально* отсутствующих аккаунтов; перед deactivation проверять, что аккаунта правда нет (matcher-баг сначала фиксится).

### YT picker — matcher игнорирует имя канала — ✅ SHIPPED 2026-05-14 PR #63 (OpenProject #66)

**✅ SHIPPED 2026-05-14** — PR GenGo2/delivery-contenthunter#63 (squash `6189cd6`), в проде через `git pull --ff-only`. OpenProject #66 → Тестирование. Memory: [[project_yt_picker_channel_name_match_shipped]].

Корень: `_find_and_tap_account` (`account_switcher.py`) для YT — gmail-fast-path работает только при заполненном `_yt_target_gmail` (нет у ~19% аккаунтов); fallback `find_account_in_list` — handle/username-ориентирован и НЕ матчит target против имени канала YT, которое для *неактивных* строк picker'а единственное видимое поле (`"<ChannelName>,,<subs>"`, без `@handle`). Dump usable + target не сматчен → терминальный FAIL без vision. Подтверждено task 5856 (`relismee` → канал «Relisme»). Семейство (`yt_target_not_in_picker_after_scroll` 23 + `yt_picker_target_absent` 4 = 27/7д) — крупнейшая actionable категория YT-падений за неделю.

Фикс: новые `_alnum_norm` + `find_yt_channel_name_matches` (консервативный матч по имени канала — точное совпадение или префикс с разницей длины ровно 1, `min(len)>=4`; ambiguity-guard: при 2+ кандидатах честный fail, не угадываем). 12 тестов TDD, 0 регрессий, codex + 3 раунда subagent-review.

**Открытые follow-up'ы (отдельные тикеты, вне #66):** добить `factory_inst_accounts.gmail` backfill для непокрытых ~19%; разобрать 11/27 за неделю где gmail в БД есть, но публикация всё равно не находит аккаунт. Evidence: `docs/evidence/2026-05-14-yt-publish-triage-iter2.md`.

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
