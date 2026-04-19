# T9 — Reuse-matrix с оценкой Gain × Risk × Effort

## Методология scoring

Каждому кандидату назначается:

- **Gain (1-5):** ожидаемое снижение фейлов / расширение capability (5 = прямой фикс доминирующего failure mode)
- **Risk (1-5):** вероятность регрессии при внедрении (5 = трогает критические hot paths без изолируемости)
- **Effort (1-5):** оценка трудозатрат (1 = <1 день, 5 = 1+ неделя)
- **Fit (1-5):** совпадение со стеком (5 = zero new deps; 1 = требует big framework migration)

**Score formula:** `score = (Gain × Fit) / (Risk × Effort)`

Cut-off: score ≥ 0.5 → «реюзать»; 0.2-0.5 → «рассмотреть»; <0.2 → «отклонить».

## Таблица кандидатов

| # | Кандидат | Источник | Gain | Risk | Effort | Fit | Score | Решение |
|---|---|---|---:|---:|---:|---:|---:|---|
| A | **force-stop + start + 8s settle перед account-verify** (`_cleanup_device` / `connect_and_restart_app`) | autowarm_worker + auto_public | 5 | 1 | 1 | 5 | **25.0** | **PORT** |
| B | **`pid` column + `process.kill(SIGTERM/SIGKILL)` watchdog** | автомаргинально из server.js:3547 + Celery pattern | 4 | 2 | 2 | 5 | **5.0** | **PORT** |
| C | **`meta.category` везде в warmer.log_event** | наш технический долг (из publisher.py pattern) | 3 | 1 | 1 | 5 | **15.0** | **PORT** |
| D | **LLM-based screen-recovery (LLMManager + system_rare.txt prompt)** | auto_public/services/llm_manager.py | 4 | 3 | 3 | 4 | **1.78** | **PORT** (но отдельный план) |
| E | In-process SIGTERM handler для warmer.py (Celery SoftTimeLimitExceeded аналог) | autowarm_worker/app/entrypoints/worker.py | 3 | 2 | 3 | 4 | 2.0 | consider |
| F | Yosemite IME для type_text (русский broadcast) | autowarm_worker/humanize_with_coords.py | 2 | 2 | 2 | 4 | 2.0 | consider (если есть баг с RU-текстом) |
| G | Декларативные daily modules для TT/YT (починить 0%-success протоколы 2/3) | autowarm_worker/app/modules/{tt,yt}/dayN.py | 4 | 3 | 4 | 3 | 1.0 | consider (L-эффорт) |
| H | Secure DB creds (вынести DB_CONFIG из publisher.py:41 в .env) | auto_public/utils/database.py (dotenv + urllib.parse.quote) | 3 | 2 | 1 | 5 | **7.5** | **PORT** (быстрый security win) |
| I | Structured JSON logging (logging_setup.py) | autowarm_worker/app/logging_setup.py | 2 | 2 | 2 | 4 | 2.0 | consider |
| J | Template method pattern для publisher.py (_perform_platform_upload_steps) | auto_public/uploader/base.py | 2 | 5 | 5 | 4 | 0.32 | reject (ломает hot-path, мало выигрыша) |
| K | pm2 max_memory_restart + max_restarts config | Celery worker_max_memory/tasks | 3 | 1 | 1 | 5 | **15.0** | **PORT** (config-only) |
| L | image-based tap `Template(image, zone_percentage)` | humanize_with_coords.py::tap | 2 | 3 | 4 | 2 | 0.33 | reject (Airtest dependency) |
| M | Poco + _restart_uiautomator | auto_public/uploader/base.py | 2 | 4 | 5 | 1 | 0.10 | reject |
| N | first-frame-as-template трюк (cv2 VideoCapture + Template) | auto_public/by_images.py | 1 | 2 | 3 | 3 | 0.5 | reject (нишевый) |
| O | cv2 touch overlay для Telegram alert screenshots | auto_public/utils/draw.py | 2 | 1 | 2 | 4 | 4.0 | consider (если порт D) |
| P | Celery migration (всей инфры на Redis+Celery) | оба репо | 2 | 5 | 5 | 1 | 0.08 | reject |
| Q | DAO/SQLAlchemy рефактор warmer.py/scheduler.js | autowarm_worker/app/repositories/ | 1 | 4 | 5 | 3 | 0.15 | reject |

## Cut-off sorted

| Score | Кандидат | Решение |
|---:|---|---|
| **25.0** | A — force-stop + 8s settle | **PORT** |
| **15.0** | C — meta.category в warmer | **PORT** |
| **15.0** | K — pm2 max_memory/restarts config | **PORT** |
| **7.5** | H — secure DB creds (.env) | **PORT** |
| **5.0** | B — pid column + SIGTERM watchdog | **PORT** |
| **4.0** | O — cv2 touch overlay (if porting D) | consider |
| **2.0** | E/F/I — SIGTERM handler / Yosemite / structured logs | consider |
| **1.78** | D — LLM screen-recovery | **PORT (separate plan)** |
| **1.0** | G — декларативные TT/YT daily modules | consider |
| **0.5** | N | reject |
| **0.33** | L — image-based tap | reject |
| **0.32** | J — Template method refactor | reject |
| **0.15** | Q | reject |
| **0.10** | M | reject |
| **0.08** | P | reject |

## Итог: Top-5 кандидатов (**PORT**)

1. **A** — **force-stop + start + 8s settle** перед account-verify (warmer.py) — эффективность 25.0
2. **C** — `meta.category` во всех warmer.log_event — 15.0
3. **K** — pm2 config `max_memory_restart` + `max_restarts` для farming worker — 15.0
4. **H** — вынести DB creds из кода в .env — 7.5
5. **B** — `pid` column в autowarm_tasks + реальный `process.kill` в watchdog — 5.0
6. **D** — LLM-based screen-state recovery (отдельным планом из-за нового зависимости — Anthropic SDK) — 1.78

## Порядок внедрения (зависимости)

Фазы:

1. **Phase A (quick wins, 1-3 дня):** A, C, K, H, B — все независимые друг от друга, S-эффорт
2. **Phase B (architectural, 1-2 недели):** D — LLM screen-recovery, отдельный план с pilot на publisher.py IG highlights empty-state
3. **Phase C (optional, если будут сигналы):** E/F/I/G — смотреть по результатам live-метрик после Phase A

## Мапинг на baseline-проблемы (T1-T5 → fixes)

| Baseline issue | Count | Fixing candidate |
|---|---:|---|
| Account read fail (77) | 77 | **A** (force-stop reset) + **D** (LLM fallback) |
| Watchdog hang (19) | 19 | **B** (real process.kill) + **K** (pm2 recycling) |
| meta.category пустая (178/178) | 178 | **C** (добавить везде) |
| DB password в коде | 1 | **H** (.env) |
| TT/YT 0% success (протоколы 2/3) | ≈76 | Phase C: **G** (декларативные daily modules) |

Сумма Phase A-addressable failures: **275 error-events из 178 unique events + 19 watchdog + 77 account** (с перекрытием). Грубо: фазой A можно покрыть ≈80 % известных fail-mode'ов.
