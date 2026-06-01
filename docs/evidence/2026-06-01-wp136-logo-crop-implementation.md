# WP#136 — Кроп лого 1:1 + ML-удаление фона: реализация (evidence)

**Дата:** 2026-06-01 · **Статус:** реализовано, ветка готова к мержу · OpenProject WP#136 «В разработке»
**Спека:** `docs/superpowers/specs/2026-06-01-wp136-client-logo-crop-design.md`
**План:** `docs/superpowers/plans/2026-06-01-wp136-client-logo-crop.md`

## Что сделано

Subagent-driven исполнение плана (свежий имплементер на задачу + двухстадийное ревью: spec-compliance → code-quality на каждой). Все изменения кода — в репо **`validator-contenthunter`**, ветка `wp136-client-logo-crop` (на свежем main). Финальное интеграционное ревью: **Ready to merge**.

### Три слоя
1. **rembg-микросервис** `logo-bg-service/` (новый): FastAPI, `POST /remove-bg` (rembg u2net, token-auth `X-Internal-Token`, sync-эндпоинт в threadpool), `GET /health`, PM2-юнит, README с деплоем/firewall. Деплой на сервер уникализации `91.98.180.103:8077`.
2. **Backend** (`validator-contenthunter/backend`): config-поля `logo_bg_removal_*` + прокси `POST /api/brand/remove-bg` (kill-switch `logo_bg_removal_enabled` default **OFF**, fail-soft 502/503, SVG-растеризация до форварда) + `GET /api/brand/bg-removal-available` (capability-гейт).
3. **Frontend** (`validator-contenthunter/frontend`): чистая утиль `isSquareWithTransparency`, `LogoCropModal.vue` (canvas 1024² fit-кроп, зум, pointer-events drag с тач, живой превью удаления фона, экспорт PNG-blob), интеграция в `BrandPage.vue` (анализ при выборе → skip если квадрат+прозрачность, иначе модалка; чекбокс прячется, если kill-switch выключен).

### Тесты (все зелёные)
- Микросервис: **3/3** pytest (включая реальный прогон rembg u2net — alpha появляется).
- Backend: **10/10** (`test_brand_remove_bg.py` 6 + `test_brand_svg_guard.py` 4, без регрессий).
- Frontend: **35/35** vitest (единственный «failed file» `slotStatus.test.ts` — пред-существующий на main, бандлит `node:test`, моей веткой не тронут).
- Type-check `vue-tsc` чист по `BrandPage.vue`/`LogoCropModal.vue`.

### Коммиты (validator-contenthunter, ветка wp136-client-logo-crop)
```
7bf1ad3 feat: bg-removal capability endpoint — hide checkbox when kill-switch off
8a84536 fix: revoke objectURL in analyzeFile + bgRemovalAvailable plain const
9f50baf feat: integrate LogoCropModal into BrandPage logo upload
500a7f1 fix: pointer-events drag (touch) + scale delta to canvas + revoke objectURLs
b54f413 feat: LogoCropModal (fit-кроп, зум, drag, удалить фон live-preview)
3646f68 feat: frontend logo square+transparency detect util
2af67f0 refactor: hoist Response import + test upstream non-200 -> 502
3bae152 feat: backend proxy POST /api/brand/remove-bg (kill-switch + fail-soft)
116ce66 feat: backend config for logo bg-removal proxy
a7832a4 ops: logo-bg-service PM2 unit + deploy/firewall README
3f57c8c fix: run rembg in threadpool (sync endpoint) to not block event loop
c9bf2b9 feat: logo-bg-service /remove-bg (rembg u2net + token auth)
324df1d test: logo-bg-service pytest pythonpath + clarify token env-set
23d5315 feat: logo-bg-service skeleton + /health
```
13 файлов, +660/−3.

> Примечание: `codex review` в этом окружении не запускается (vendored bubblewrap падает на loopback). Вместо него использовано многоагентное ревью (spec + code-quality на каждой задаче + финальное интеграционное) — покрытие эквивалентно/глубже.

## Архитектурный контракт (проверен интеграционным ревью)
Фронт `POST /brand/remove-bg` (blob) → бэк-прокси (`image/png` Response, токен server-side) → микросервис `POST /remove-bg` (`X-Internal-Token`). Токен/URL микросервиса **в браузер не утекают**. Выход — 1024² PNG через существующий `/upload-image` → `logo_url`; **потребитель `unic-worker` не меняется** (1024² PNG — подмножество принимаемого).

---

## ДЕПЛОЙ-ЧЕКЛИСТ (за Данилом — нужны ops-доступы)

### A. Микросервис на сервере уникализации `91.98.180.103`
1. Влить ветку (или забрать код `logo-bg-service/`), затем на хосте уникализации:
   ```
   rsync -az --exclude tests --exclude __pycache__ logo-bg-service/ root@91.98.180.103:/root/logo-bg-service/
   ```
2. На `91.98.180.103`:
   ```
   cd /root/logo-bg-service && python3 -m pip install -r requirements.txt
   python3 -c "from rembg import new_session; new_session('u2net')"   # прогрев ~170MB
   ```
3. Сгенерировать общий секрет, вписать в `ecosystem.config.js` → `LOGO_BG_REMOVAL_TOKEN` (заменить `REPLACE_WITH_SHARED_SECRET`).
4. Firewall — входящие на 8077 только с валидатора:
   ```
   ufw allow from 72.56.107.157 to any port 8077 proto tcp
   ufw deny 8077
   ```
5. Запуск: `pm2 start ecosystem.config.js && pm2 save`
6. Проверка с валидатора: `curl -s http://91.98.180.103:8077/health` → `{"status":"ok"}`

### B. Backend (валидатор `72.56.107.157`)
1. Влить ветку в main, прод pull.
2. В backend `.env` валидатора:
   ```
   LOGO_BG_REMOVAL_TOKEN=<тот же секрет, что в ecosystem>
   LOGO_BG_REMOVAL_URL=http://91.98.180.103:8077      # дефолт уже такой
   LOGO_BG_REMOVAL_ENABLED=true                        # ВКЛючить ПОСЛЕ прогрева сервиса (шаг A2)
   ```
3. Рестарт валидатор-бэка (uvicorn/PM2), фронт пересобрать/задеплоить.

### C. Ручная проверка в UI (после деплоя)
- Прямоугольный JPEG-лого → открывается модалка, лого вписано целиком (fit), зум/drag работают, «Готово» → в карточке квадратное 1:1 лого (не сплющено).
- Квадратный PNG с прозрачностью → модалка НЕ открывается, грузится сразу.
- Чекбокс «удалить фон»: виден только при `LOGO_BG_REMOVAL_ENABLED=true` (capability-гейт); клик → фон уходит, превью обновляется; при недоступном сервисе — мягкая ошибка, кроп продолжает работать.
- Итоговый объект в S3: PNG 1024×1024 RGBA.

## Остаток
- Деплой (A/B) + ручная проверка (C) — за Данилом (ops-доступы к `91.98.180.103` ufw/pm2 и валидатор-`.env`).
- После verify → OP#136 «Тестирование» → «Готово».
