# BACKLOG — Генри

## 🟢 WP #162 — канарейка кросс-репо контракта `skip_reason='moved_from_slot%'` (follow-up WP #154) — SHIPPED+DEPLOYED 2026-05-27 (OpenProject #162)
**Приоритет:** низкий (хардинг)
**Статус:** **2 PR** merged — `GenGo2/validator-contenthunter`#23 (`26e056c`) + `GenGo2/delivery-contenthunter`#113 (`3797aea`); прод-деревья синхронизированы `git pull --ff-only` (autowarm `3797aea`, validator `26e056c`); OpenProject #162 → **«Готово»**.

Негласный кросс-репо контракт (follow-up WP #154 re-queue после переноса слота): валидатор отменяет старые pending-строки `publish_queue` со `skip_reason='moved_from_slot_<src>_to_<dst>'` (`schedule.py move_unpublished` — источник литерала → `pipeline_reversal.update_downstream_dates_for_content` — write-site), delivery `assign_candidates.js` re-queue перенесённый контент по `LIKE 'moved_from_slot%'`. Смена текста без координации → delivery МОЛЧА перестаёт re-queue (тихий регресс, как до #154). Ноль UI/рантайма — чисто тест+комментарии.

**Сделано:** (1) канарейка validator `test_schedule_pipeline_reversal.py::test_move_unpublished_updates_dates_not_cancels` — `in`→`startswith('moved_from_slot')` (зеркалит LIKE-префикс, не подстрока); (2) контракт-комменты validator `schedule.py`+`pipeline_reversal.py` + delivery `assign_candidates.js` (обратная ссылка); (3) починен пред-существующий красный delivery `tests/test_pipeline_guards.test.js` (mock-десинк `slotIsEffectivelyManual` в `checkDispatchQueueSlotLineage`, красный с 21.05/WP#125 — добавлена недостающая mock-строка).

**Деплой:** прод-деревья `/root/.openclaw/workspace-genri/{autowarm,validator}` (writable claude-user), fast-forward pull. **PM2 restart НЕ нужен** — правки не-рантаймные.

**Проверки:** validator канарейка 1 passed (мокнутая БД), delivery `test_pipeline_guards` 11/11 (после merge свежего origin/main в отстававшую на 24 ветку, конфликтов нет), codex 0 находок обоих диффов.

**Контекст процесса:** дизайн+реализация автоворкером (бриф `contenthunter_autoexec/briefs/162/`, спека одобрена Данилом, codex-clean) остановились до PR/merge/deploy → доведено до отгрузки другой сессией (обнаружено `git log --all | grep wp162` + воркдеревья → сверка с пользователем → verify→codex→push→PR→merge→ff-pull). Чужие чекауты/воркдеревья не тронуты.

Evidence: `docs/evidence/2026-05-27-wp162-skip-reason-canary-shipped.md`. Spec: `docs/superpowers/specs/2026-05-27-wp162-skip-reason-contract-canary-design.md`. План: `docs/superpowers/plans/2026-05-27-wp162-skip-reason-contract-canary.md`. Память: `project_wp162_skip_reason_contract_canary`.

---

## 🟢 IG `ig_target_not_in_picker` — foreground-hijack на шаге выбора аккаунта — SHIPPED+DEPLOYED 2026-05-21 (OpenProject #119)
**Приоритет:** высокий
**Статус:** merged squash `700e50c` (PR #90) в `GenGo2/delivery-contenthunter` main, прод-дерево обновлено `git pull --ff-only`; OpenProject #119 → Тестирование, investigation #102 → Готово.

Топ-2 IG-фейл за 7д (18, размазано по аккаунтам/устройствам = код, не конфиг). `ig_target_not_in_picker` («аккаунт не привязан к устройству») — **вводящий в заблуждение** код. Реально на шаге `ig_4_pick_account` на переднем плане оказывается ЧУЖОЕ приложение, и `parse_account_list` скребёт его экран → мусор → ложный «не найден». Доказано пакетом UI-дампа: task 8696 → YouTube (`com.google.android.youtube`), 8657 → TikTok (`com.zhiliaoapp.musically`), 8623 → лаунчер Samsung (`com.sec.android.app.launcher`); 8696 подтверждён скринкастом (bottom-sheet аккаунтов YouTube).

Фикс: guard `_ig_guard_picker_foreground(cfg, header_y_max)` перед `_find_and_tap_account` — `_detect_foreground_pkg()` читает тот же uiautomator-дамп, что и парсер; IG (или не определилось) → no-op; чужой пакет → `_ensure_app_foregrounded('Instagram')` + re-navigate в список; при неудаче fail с честным `ig_account_switcher_wrong_foreground` вместо `ig_target_not_in_picker`. Kill-switch `IG_PICKER_FG_GUARD_ENABLED` (default ON). 8 новых тестов (`tests/test_account_switcher_ig_picker_fg_guard.py`), весь набор переключателя 143 passed, codex 0 находок.

**Деплой:** path-scoped `account_switcher.py` в `/root/.openclaw/workspace-genri/autowarm/`, fast-forward (дерево чистое). PM2 restart не нужен — публишер спавнится per-task (`publisher.py <task_id>`).

**Verify (утренняя IG-пачка 22.05):** часть кейсов восстанавливается (IG возвращается на передний план, аккаунт находится); остаток → честный `ig_account_switcher_wrong_foreground` вместо `ig_target_not_in_picker`. Откат: `IG_PICKER_FG_GUARD_ENABLED=0`.

**Не покрыто (отдельно при появлении):** подслучай «IG на переднем плане, но не тот экран» (по данным редкий).

Evidence: `docs/evidence/2026-05-21-ig-publish-fails-triage.md`. Память: `project_ig_target_not_in_picker_foreground_hijack`.

---

## 🟢 YT `yt_editor_upload_timeout` — ловушка экрана «Добавьте описание» — SHIPPED+DEPLOYED 2026-05-21 (OpenProject #117)
**Приоритет:** высокий
**Статус:** merged `97f4b5d` (fix `9857cee`) в `GenGo2/delivery-contenthunter` main, прод-дерево обновлено; OpenProject #117 → Тестирование.

Топ-1 кодовый YT-фейл за 21.05 (2 из 3 падений: #8814 `elcosmetics`, #8821 `elcosmo_beauty`). После заполнения заголовка бот проваливался на полноэкранный редактор «Добавьте описание» (в ui-dump только `content-desc` «Назад»/«Хештеги» + пустой `EditText`, кнопки «Загрузить» нет) и зависал 20+ итераций → `yt_editor_upload_timeout`. Корень: stuck-counter строит ключ из `re.findall(r'text="..."')`, а тут все подписи в `content-desc` + `EditText` пустой → ключ `[]` → `if _yt_cur and ...` falsy → счётчик сбрасывается, авто-BACK не срабатывал. Новая сигнатура (16.05=9, 18.05=15, 19–20.05=0 после WP #80/#113, 21.05=3 — все desc-trap; вероятно всплыло после WP #113).

Фикс: `_yt_on_bare_description_screen(ui)` (детект: есть «Хештеги»/«Hashtags», нет «Добавьте информацию», нет «Загрузить») + guard в editor-loop → `KEYCODE_BACK` на metadata. Kill-switch `YT_DESC_TRAP_GUARD_ENABLED` (default on). 8 unit-тестов (`tests/test_yt_desc_trap_detection.py`), проверено на реальном ui-dump #8814. Codex 0 находок.

**Verify (утренняя YT-пачка 22.05):** `yt_editor_upload_timeout` (desc-trap) → 0 + появляются события `yt_desc_trap_escape` → #117 в «Готово». Откат: env `YT_DESC_TRAP_GUARD_ENABLED=0`. SQL — в evidence-доке.

**Не код (отдельно):** третье падение 21.05 #8809 `axilor.brand@gmail.com` — `yt_app_not_foregrounded` из-за блокировки аккаунта Google («Нет доступа к продукту»). Account-health, кандидат на `account_blocks`.

Evidence: `docs/evidence/2026-05-21-yt-publish-fails-triage.md`.

---

## 🟢 IG Edits-баннер dismissal — SHIPPED 2026-05-14 (OpenProject #61)
**Приоритет:** высокий
**Статус:** merged в `GenGo2/delivery-contenthunter` main `5372d18`, deployed на prod tree; OpenProject #61 → Тестирование

Instagram-баннер «Edits» (промо bottom-sheet) перекрывал picker / уводил в Google Play — ~34 IG-падения/нед (20 устройств, 27 акков). Фикс: детектор `_is_ig_edits_promo` + переписанный `_dismiss_ig_edits_promo` (3-state ladder «Закрыть панель»→swipe→back, без force-stop) + оркестратор `_ig_handle_edits_promo_at_picker` (честные коды `ig_edits_promo_playstore_hijack` / `ig_edits_promo_undismissable`), wired в 4 точки `publish_instagram_reel`. 17 тестов.

**Open для пользователя:**
- 24h live-verify (≈ 2026-05-15): `ig_picker_wrong_candidate` + `ig_gallery_no_video_candidate` (Play-Store mode) должны упасть до ≤20% от baseline (~4.9/день); должны появиться `ig_edits_promo_dismissed` events. Точный SQL — в evidence-доке. Если ок — #61 → Готово.

Evidence: `docs/evidence/2026-05-14-ig-publish-failure-triage.md` + `docs/evidence/2026-05-14-ig-edits-banner-dismiss-shipped.md`.

---

## 🟢 IG `ig_gallery_no_video_candidate` — Шаг-4 промах по чипу «Черновики» (OpenProject #68, GitHub PR #61 merged 2026-05-14)
**Приоритет:** высокий
**Статус:** SHIPPED — squash `c0f781b` merged в `main`, прод-дерево обновлено `git pull --ff-only`. OpenProject #68 → Тестирование.

Крупнейшая активная причина IG-падений (~29 из 39/нед). Root cause подтверждён детерминированно по фикстуре `ig_picker_clean.xml`: к Шагу 4 пикер «Новое видео Reels» уже открыт → `_ig_find_gallery_anchor_coord` проваливается на priority-2 `gallery_destination_item` → первый кликабельный матч = чип «Черновики» → tap `(276,332)` → пустой экран «Черновики Reels» → RC-8. Фикс: фильтр Drafts/Templates-чипов в anchor-lookup + `_ig_is_gallery_picker_open` (Шаг 4 пропускает open-gallery tap если пикер открыт) + `_ig_is_reels_drafts_screen` + guard-код `ig_landed_on_reels_drafts`. 15 TDD-тестов, 458 passed 0 регрессий, Codex 0 находок.

**24h live-verify (дедлайн ≈ 2026-05-15 16:00 UTC):**
- `SELECT created_at::date, count(*) FROM publish_tasks WHERE platform='Instagram' AND status='failed' AND NOT testbench AND error_code='ig_gallery_no_video_candidate' AND created_at > '2026-05-14' GROUP BY 1;` — счётчик должен заметно упасть (baseline ~17/3д).
- `ig_gallery_already_open` events появляются в логах IG-задач (success-сигнал фикса).
- `ig_landed_on_reels_drafts` — если ненулевой, значит Drafts достигается другим путём → новый раунд.

Evidence: `docs/evidence/2026-05-14-ig-publish-failures-triage.md`.

---

## 🟡 IG publish — остальные находки триажа 2026-05-14
**Приоритет:** средний
**Статус:** не заведены в OpenProject; ждут решения, брать ли в работу

Из того же 7-дневного IG-триажа (229 prod-падений) — категории, не входящие в #61/#68:
- `ig_gallery_no_video_candidate` остаточный не-баннерный мод «экран редактора/playback» (~11/нед) — отдельный nav-баг, ещё не заведён. (Доминирующий мод «пустой экран Черновики Reels» — закрыт: #68 выше, SHIPPED.)
- `ig_app_launch_failed` (~14–15/нед) — похоже на состояние устройств (IG не выходит на передний план), не код; нужна device-side разведка.
- `ig_target_not_in_picker` (~13–14/нед) — **ЗАКРЫТО WP #119 (SHIPPED+DEPLOYED 2026-05-21):** не «аккаунт не привязан», а foreground-hijack (на шаге выбора аккаунта на переднем плане чужое приложение, парсер скребёт чужой экран → мусор типа «устройстве.»). См. верхнюю секцию.
- `ig_share_tap_no_progress` — закрыт: false-negative, фикс `52f9285` (pre-Tier-1 probe), проверен 0 рецидивов 05-14. Не WP.
- Cleanup (не блокер): `_ig_handle_edits_promo_at_picker` зовёт `_current_foreground_package()` (один dumpsys) на каждой итерации даже без баннера — можно загейтить за `_is_ig_edits_promo`.

Evidence: `docs/evidence/2026-05-14-ig-publish-failure-triage.md` + `docs/evidence/2026-05-14-ig-publish-failures-triage.md`.

---

## 🟢 Spec D — slot move обновляет publish date (validator PR #9 merged 2026-05-13)
**Приоритет:** высокий
**Статус:** merged в main `eab5791`, prod deploy заблокирован uncommitted hot-patch (schemes.py)

**Open для пользователя:**
- Resolve prod hot-patch: `cd /root/.openclaw/workspace-genri/validator && git stash && git pull origin main && git stash pop` (или commit hot-patch если нужен) — потом `sudo pm2 restart validator-backend` + `cd frontend && npm run build`.
- Manual smoke на testbench phone #19 (см. evidence doc): drag pq.pending в другой день → assert pq cancelled + unic переадресован; drag во время `pq.running` → UI ⏳ badge + backend 409.
- 24h SQL canary: `count(*) WHERE DATE(pt.started_at) != vss.slot_date` ≈0.
- 409 rate в pm2 logs validator-backend — guard срабатывает редко.

**Backlog (next iteration):**
- Race-detect для `update_slot` (class A) — Spec B `cancel_downstream_for_content` имеет тот же TOCTOU изъян, scope Spec D не покрывает; пока никто не жаловался.
- Kill protocol для running publisher — не закрываем started publishers (риск drafts/screen recordings); если pain нарастёт — отдельный design.

Evidence: `docs/evidence/2026-05-13-spec-d-slot-move-update-publish-date-shipped.md`.

---

## 🔴 TT 24h verify — PRs #32, #33, #34 (2026-05-12)
**Приоритет:** высокий
**Статус:** ожидает 24ч окно (≈ 2026-05-12 18:00 UTC)

3 TT-PR'а merged 2026-05-11; SQL для проверки готовы в evidence-доках.

**PR #32 (music-rights coverage, flags активированы 14:21 UTC):**
- `tt_music_rights_fallback_match` events за 24ч → expect ≥1 (RC-A win)
- `tt_music_rights_unhandled_suspect` → 0 followed by `publish_failed_generic` (FP guard)
- ≥5 `tt_post_music_rights_dump` XML для evidence RC-B следующего раунда
- `TT_SEED_HARDENING_SAASCENE_ENABLED` activation решение: ≥1 dump с `SAASceneWrapperActivity` в top_activity → активировать; иначе wait

**PR #33 (switch_failed_unspecified, prod с 13:50 UTC):**
- `switch_failed_unspecified` count 2026-05-12 vs baseline 8/24ч — expect drop
- Если 0 — fully verified
- Если non-zero — копать новый pattern (другой root cause unmasked)

**PR #34 (post-switch renav, prod с 17:45 UTC):**
- `tt_post_switch_recovered_via_renav` ≥1 → recovery работает на real traffic
- `tt_post_switch_verify_unrecoverable` baseline measured
- `tt_upload_confirmation_timeout` count 2026-05-12 vs 2026-05-11 (~26/48ч pre-deploy)
- TT `done` count 2026-05-12 vs baseline (1/7д)

Все SQL — `docs/evidence/2026-05-11-tt-{music-rights-coverage,switch-failed-unspecified,post-publish-success-detection,post-switch-renav}-shipped.md`

---

## 🔴 TT followups (после 24ч verify)
**Приоритет:** средний
**Статус:** discovery → spec → impl

**Известные открытые TT проблемы:**

1. ~~**`tt_fg_lost` downstream music-rights accept**~~ — ✅ SHIPPED PR #35 (`a5bbd30`, merged 2026-05-11 19:11 UTC). Discovery скорректирован: на самом деле НЕ downstream music-rights, а downstream AI Unstuck → app-switch (Samsung Launcher/Camera). Fix: `_attempt_tt_fg_recovery` (pm list + monkey reorder-to-front) + outer `tiktok_active` trill recognition.

2. **AI Unstuck `tiktok_active_for_ai` trill recognition** (followup из final review PR #35) — `publisher_tiktok.py:~1421` использует pre-trill check `'musically' in X or 'tiktok' in X.lower()`. One-liner: add `or 'ugc.trill' in X`. Caveat — не блок (trill-only devices редко), bundle с next nearby TT PR.

3. **RC-B (60% music-rights post-accept timeouts)** — `_tt_infer_post_publish_success` возвращает False для post-music-rights state. Ждёт ≥5 XML dump'ов от активированного `TT_DUMP_POST_MUSIC_RIGHTS_XML` (с 2026-05-11 14:21 UTC). После evidence — design positive-path detector.

4. **`TT_SEED_HARDENING_SAASCENE_ENABLED` activation** — flag-gated SAASceneWrapperActivity SEED ext в `_tt_infer_post_publish_success`. Activation conditional: ≥1 XML dump с `SAASceneWrapperActivity` в top_activity meta (PR #32).

5. **`was_feed` structured meta field** на `tt_post_switch_verify_unrecoverable` events — сейчас implicit в reason string. Structured field нужен только если automated triage parsing появится. Note из final code review PR #34.

6. **Approach B/C для tt_fg_lost prevention** (после 24ч verify recovery rate):
   - **B:** clamp blind FALLBACK coords + AI Unstuck taps от edge zones (y<100, y>2270, x<30, x>1050)
   - **C:** AI Unstuck post-tap topResumedActivity check + abort если не TikTok
   - **Cold-restart fallback** в `_attempt_tt_fg_recovery` если recovery_rate <30% observed

7. **IG/YT same pick→feed pattern check** — если когда-то возникнет на других платформах, Approach A generalized в Approach B candidate (shared `_post_switch_verify_handle` recovery вместо TT-specific dispatcher).

---

## 🟢 Publish dup incident 2026-05-08 — Phase 2 (через 2-4 нед observation)
**Приоритет:** средний
**Статус:** waiting for verification window

**Контекст:** Phase 1 (Spec C+B+A) shipped 2026-05-08 — closed RC-1..5, RC-7, RC-8.
- autowarm origin/main: `fab52dc` (B 2 + A 3 + C 4 commits)
- validator origin/main: `cdda4a5` (B 2 + A 1 commits)
- Stop-gap: sweep отключён `UNIC_SWEEP_DISABLED=1`, после prod pull нужно `pm2 unset` обратно

**Phase 2 — D4 sweep window narrow (RC-5 finishing):**
- В `unic_sweep.js:28-33` `computeBusinessDateWindow` вернуть `[today]` (убрать `yesterday`)
- Pre-condition: 2-4 нед observation что `past_slot_dropped` events падают к 0 (= trigger-immediate ловит все cases)
- Worktree-prep: `feat/sweep-window-narrow-today-only-20260601` (от main)
- Test: `tests/test_sweep_window.test.js` уже scaffold'ed в Spec A plan
- 2 теста + 1 commit + cherry-pick

**Verification queries:**
```sql
-- Phase 2 trigger: should be 0 daily for 2-4 weeks
SELECT count(*) FROM publish_queue WHERE status='past_slot_dropped' AND created_at::date = CURRENT_DATE;

-- если sweep не вставляет yesterday — D4 безопасно
SELECT count(*) FROM unic_tasks
WHERE created_at > now() - interval '24 hours'
  AND content_id IS NOT NULL AND slot_date = (CURRENT_DATE - 1);
```

**Related followups (low priority):**
- D1.5 в Spec C: проверить call chain `return None` → `publish_task.status='failed'` (T5 GREEN, но в проде проверить через `media_store_pollution_pre_publish` event count)
- RC-3 morning batch reliability (отдельный design, не критичен после D1+sweep)
- IG локализация без 'видео' в content-desc — если spike `ig_gallery_no_video_candidate` → расширить video selector

---

## 🔵 Zoom Voice Agent — Кира на звонках (2026-03-01)
**Приоритет:** средний (после presence)
**Статус:** ожидает ресёрча

**Цель:** Кира автоматически заходит в Zoom, слушает клиента, отвечает голосом по базе знаний.

**Нужен ресёрч:**
1. Zoom API/SDK — двустороннее аудио (не чат)
2. Real-time STT — Deepgram, AssemblyAI, Whisper streaming (latency + цена)
3. Voice cloning — ElevenLabs, PlayHT, LMNT (качество, цена, русский)
4. Архитектура: микрофон → STT → Кира RAG (PG 14к сообщений) → TTS → динамик
5. Бюджет: помесячные расходы на API
6. Сроки разработки

**Результат:** Документ с архитектурой, сравнением, бюджетом и планом (не код).

---

## 🟡 Proxy + Geo Intelligence — полная система (2026-03-01)

### Часть 1: Автораздача прокси по всем иностранным клиентам
- Источник гео: Airtable «Брифы по проектам» → поле «География»
- Маппинг: Дубай/Эмираты → UAE, Грузия → GE, Германия → DE, США → US и т.д.
- Factory DB: project_id → device_serials (через pack_accounts + device_numbers)
- Провайдеры: IPRoyal (статичные) + Decodo (endpoint-based), ключи даёт Роман
- Скрипт готов: `autowarm/proxy_manager.py`
- После получения ключей: одна команда → все телефоны всех иностранных клиентов получают прокси
- Текущие проекты с иностранным гео: Celebration Station (UAE), Content Hunter Дубай (UAE), Symmety (UAE), Ambassadori (GE/UAE), LaserCube (US/UK/DE/IT), Trend Clone (US/EU)

### Часть 2: Geo-верификация аудитории в Autowarm
- При запуске задачи: сверять целевое гео (из Airtable) с реальной аудиторией аккаунта
- Instagram: audience_city / audience_country из аналитики
- TikTok: viewer_geo из ADB
- Результат: ✅ совпадает / ⚠️ несоответствие (с процентами)
- Пример алерта: "Аудитория RU 68%, ожидается UAE — прокси подключён 3 дня назад"
- Отображение в UI Autowarm: колонка «Гео» у каждого аккаунта

**Статус:** ожидает ключей IPRoyal + Decodo от Романа

---

## 🟡 Прокси по регионам для телефонов (2026-03-01)

**Задача:** подключить резидентные прокси на телефоны под клиентов с нужным GEO (UAE, DE, GE и др.)

**Архитектура:**
- Тип прокси: резидентные SOCKS5 (~$3-8/IP/мес)
- Приложение на телефоне: Hiddify (без root, работает с мобильным интернетом)
- Управление: ADB автоматизация (включить перед задачей / или 24/7)
- В Autowarm: поле «Прокси» у устройства, привязка к клиенту/региону

**Пилот:** Celebration Station — 6 телефонов, регион UAE

**Инструкция по покупке (Роман делает сам):**
1. Зайти на **proxy-cheap.com** или **proxyscrape.com**
2. Раздел: Residential Proxies → Static Residential
3. Выбрать страну: United Arab Emirates
4. Купить 6 штук (план с оплатой за IP, не за трафик)
5. Получить: ip:port:login:password для каждого
6. Передать Генри — дальше всё автоматически

**Что делает Генри:**
- Устанавливает Hiddify APK на 6 телефонов через ADB
- Импортирует конфиги прокси
- Добавляет в Autowarm: поле прокси у устройства + логику вкл/выкл

**Стоимость пилота:** ~$18-48/мес за Celebration Station

**Статус:** ожидает покупки прокси Романом



## 🟡 Autowarm: перенос ADB relay на EU сервер (2026-03-01)

**Задача:** убрать Москву из цепочки DE→RU→KZ, стабилизировать ADB соединения

**Проблема:** ADB relay сервер (`147.45.251.85`) находится в Москве (Timeweb RU).
РКН периодически роняет каналы → ADB timeout → телефоны "зависают" → analytics/farming падают.

**Решение:**
1. Роман покупает VPS Timeweb Germany (~€3-5/мес, аналог текущего сервера)
2. Генри переносит ADB relay на новый EU IP
3. Меняет `ADB_HOST` в `/root/.openclaw/workspace-genri/autowarm/.env`
4. `pm2 restart autowarm`

**Ждём:** новый VPS от Романа → он скидывает IP → Генри настраивает за ~30 минут

---

## 🔴 Задача от Володи (2026-02-27)

### Участники встреч не заполняются в mymeet.meetings

**Проблема:** в `/root/.openclaw/workspace/shared/scripts/load_mymeet_fast.py` участники захардкожены как `[]`. Поле `participants` (text[]) пустое у всех встреч.

**Данные есть в транскрипте** — формат реплик:
```
Олег, Content Hunter: текст...
Michael (Embassy Alliance): текст...
Сахавет Сафаров: текст...
```

**Что сделать:**
1. Написать парсер участников из `content_text` (всё до `:` в начале строки = имя участника)
2. Обновить `load_mymeet_fast.py` — заполнять `participants` при загрузке новых встреч
3. Ретроактивно обновить все записи в БД где `participants = '{}'`

**DB:**
```
PGPASSWORD=openclaw123 psql -U openclaw -h localhost -p 5432 -d openclaw
Таблица: mymeet.meetings, поле: participants (text[])
```

После выполнения — сообщить Роману (tg:295230564) результат.
