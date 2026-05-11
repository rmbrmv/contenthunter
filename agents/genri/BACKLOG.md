# BACKLOG — Генри

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
