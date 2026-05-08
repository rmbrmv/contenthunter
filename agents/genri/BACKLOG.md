# BACKLOG — Генри

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
