# WP #137 — Уникализация лого клиента: SHIPPED + DEPLOYED (inert)

**Дата:** 2026-06-03 · **OpenProject:** [#137](https://openproject.contenthunter.ru/work_packages/137)
**Репо кода:** `validator-contenthunter` (GenGo2) · **Репо доков:** `rmbrmv/contenthunter`
**Спека/план:** `docs/superpowers/specs/2026-06-03-wp137-client-logo-uniqualization-design.md`, `docs/superpowers/plans/2026-06-03-wp137-client-logo-uniqualization.md`

## Что

Новый Шаг 1/2 в клиентской «Уникализации»: клиент выбирает N AI-сгенерированных вариантов лого (Laozhang gpt-image-1) перед выбором схем (Шаг 2/2, существующий мастер `SchemesPage`). Снимает ручной флоу Ани; защита от shadow-ban (разнообразие лого).

## Решения (с Данилом)

- Движок: генеративная модель **Laozhang gpt-image-1** (image-edit: обрезанный лого WP#136 + промт).
- Триггер: **по кнопке** (Сценарий А) — платим только когда клиент дошёл.
- Кол-во: генерим **pack_count + 5**, выбрать **pack_count** (fallback 10/5, если паков нет; `pack_count` = `COUNT(*) FROM factory_pack_accounts`, как `min_required` у схем).
- Размещение: gate ПЕРЕД мастером схем в `SchemesPage.vue` (отдельный `LogoVariantStep.vue`/`LogoVariantCard.vue`; тиндер-грид схем НЕ переиспользуем — другая модель взаимодействия).

## Реализация (subagent-driven TDD, 16 коммитов `ffcc513`..`9a362ee`, merge `7879568`)

- **Миграция 010**: `logo_variants` / `logo_selections` / `logo_generation_tasks` (отдельная таблица задач, не `unic_tasks` — чистые границы). Дедуп-ключ `(project_id, logo_source_hash, prompt_template_version, variant_index)`.
- **config**: kill-switch'и `LOGO_VARIANTS_GENERATION_ENABLED` / `LOGO_VARIANT_GATE_ENABLED` (default OFF) + `LOGO_IMAGE_API_URL`, `LOGO_IMAGE_MODEL=gpt-image-1`, `LOGO_PROMPT_TEMPLATE_VERSION`, `LOGO_VARIANT_TTL_DAYS=30`.
- **logo_prompts.py**: версионир. промты (база — промт Ани + 10 тем фона).
- **logo_image.py**: Pillow-постобработка → 900×900, скруглённые углы → прозрачные поля, ≤500 КБ.
- **logo_variant_service.py**: sha256-хеш источника, fetch, вызов Laozhang gpt-image-1 (изолировано для тестов).
- **logo_generation_queue.py**: `compute_counts`/`enqueue` (advisory-lock + dedup) / `read_status` / `claim_next_pending` (SKIP LOCKED).
- **logo_variant_processor.py**: генерация недостающих индексов → S3 → инкрементальная запись, partial-tolerant, резюмируемый.
- **logo_background.py**: фоновый loop в FastAPI lifespan — воркер генерации (за kill-switch) + суточная TTL-очистка + реклейм зависших `processing` (анти-хэнг).
- **routers/logo_variants.py**: `GET /readiness`, `POST /generate|select|retry|reset`; admin-on-behalf (US-3); select валидирует ровно `required`, обнуляет ttl у выбранных.
- **Фронт**: `api/logoVariants.ts`, `LogoVariantCard.vue`, `LogoVariantStep.vue` (idle/generating/error/ready, гейт, polling, fail-soft load, retry при недогенерации), gate-интеграция в `SchemesPage.vue` (существующий мастер не тронут, ушёл под `v-else`).

## Тесты / ревью

- Backend **21** тестов (live `openclaw`, PID 100137-100142), frontend **13**. Регрессия чистая: 9 backend + 1 frontend пре-существующих падений подтверждены на `main` (внешние gateway/S3-зависимости, `node:test`-бандл).
- Каждая задача: implementer → spec-review → code-quality-review + финальное holistic-ревью (opus): **READY TO MERGE с kill-switch'ами OFF**; перед включением закрыты 2 dead-end (зависший `processing` → реклейм; недогенерация `< required` → кнопка «Повторить» в ready).

## Деплой (2026-06-03)

- `origin/main` ← merge `7879568` (push `61ff4be..7879568`).
- **Прод backend**: `/root/.openclaw/workspace-genri/validator` `git pull --ff-only` → `7879568`; `sudo pm2 restart 24` (validator). Проверено: `/openapi.json` содержит `logo-variants`, старт чистый, лог 200.
- **Прод frontend**: `npm run build` из main-чекаута → postbuild `cp` в `/var/www/validator` (бандл `index-DcDSV-sL.js`).
- **Миграция 010** уже применена к живой `openclaw` (alembic_version=`010`, 3 таблицы есть). Таблицы пустые.

## Состояние: задеплоено, но ВЫКЛЮЧЕНО (inert)

Оба kill-switch'а **OFF**. SchemesPage ведёт себя как раньше (gate fail-open: `gate_enabled=false` + catch в `loadLogoGate`). `/generate` отдаёт 503. Безопасно для прода.

### Чтобы включить (ops, отдельным шагом — НЕ сделано)

1. Задать в прод-`.env` валидатора `LOGO_IMAGE_API_URL` = Laozhang images/edits endpoint (+ убедиться, что `LAOZHANG_API_KEY` задан).
2. **Проверить, что gpt-image-1 image-edit реально работает через Laozhang** (вернёт `data[0].b64_json`). Если edits-путь недоступен — реализовать фолбэк (см. бэклог).
3. Включить `LOGO_VARIANTS_GENERATION_ENABLED=true`, прогнать смок (один проект: generate → дождаться вариантов → select). **Только после успеха** включать `LOGO_VARIANT_GATE_ENABLED=true` (иначе гейт заблокирует клиентам переход к схемам при нерабочей генерации).
4. `sudo pm2 restart 24`.

⚠️ Гейт включать ТОЛЬКО после подтверждённой рабочей генерации — иначе клиенты застрянут на Шаге 1/2.

---

## Пост-шип апдейт (2026-06-03, тот же день) — фича включена в проде, гейт OFF

После первичного inert-деплоя провели верификацию и доведение до рабочего состояния:

### Смок image-провайдера
- Старый прод `LAOZHANG_API_KEY` оказался **невалиден** (`401 «无效的令牌»` — тот же ответ, что на заведомо левый ключ → не баланс, а отозван). Подтверждено сравнительным тестом + эндпоинт баланса тоже 401.
- Данил выдал новый рабочий ключ. Смок `gpt-image-1` edit через `api.laozhang.ai/v1/images/edits`: OK.

### 2 бага найдены и исправлены (main `88c7ca0`)
- Лого читалось из **пустой** `validator_projects.logo_url` (0/63 заполнено) вместо `validator_brand_profiles` (там реально 63 лого) — **и в роутере, и в фоновом воркере** → `/generate` всегда давал бы 400. Вынесен единый `resolve_project_logo_url` (bp + fallback vp, зеркало `schemes.py`) + тесты.

### Параллелизация генерации (main `d31ef7f`)
- Было ~58 c/вариант последовательно. Распараллелено (`asyncio.as_completed` + `Semaphore`, по `AsyncSessionLocal` на корутину; прогресс последовательно в переданной сессии).
- ⚠️ Тюнинг: при concurrency=5 Laozhang queue'ит запросы на своей стороне → `ReadTimeout` (НЕ rate-limit). Подобрано **concurrency=3 + timeout=180с** (дефолты в config) → 5/5 за ~128с.
- Live E2E через прод-API: generate 5/5 + `/select` + `reset` — всё OK. Код-ревью пройдено.

### Текущее прод-состояние
- `validator-contenthunter` main `d31ef7f`, pm2 id24 перезапущен, фронт пересобран (`index-BPg9bzy6`, текст «1–2 минуты»).
- `.env`: рабочий `LAOZHANG_API_KEY` + `LOGO_IMAGE_API_URL=https://api.laozhang.ai/v1/images/edits` + `LOGO_IMAGE_MODEL=gpt-image-1` + **`LOGO_VARIANTS_GENERATION_ENABLED=true`** (бэкап `.env.bak.wp137.*`).
- **`LOGO_VARIANT_GATE_ENABLED=false`** (по решению Данила оставлен OFF) → клиенты фичу пока не видят; SchemesPage работает как раньше. Включение = щёлкнуть флаг + `pm2 restart 24`; затрагивает всех клиентов (US-2: принудительный выбор лого перед схемами).

### Оценка времени для клиента (при включённом гейте)
- Набор из 5 ≈ 2 мин; из 10 (проект без паков) ≈ 3.5–4 мин (4 батча по 3).
