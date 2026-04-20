# Brief: LLM screen-recovery port из `auto_public/services/llm_manager.py` (farming Candidate D)

**Создан:** 2026-04-20
**Статус:** brief (input для следующего `/aif-plan full`, кодинг НЕ в scope brief'а)
**Источник:** план-потомок `contenthunter/.ai-factory/plans/open-followups-20260420.md` T5
**Baseline:** `.ai-factory/evidence/farming-reuse-matrix-20260419.md` §Top-3 Candidate D (score mid, effort M)
**Целевой репо-объект:** `/tmp/auto_public` (last commit `2aa9b4c`) — `services/llm_manager.py` + `llm_providers/{anthropic,open_router}.py`

## 0. TL;DR для следующего Клода

Портируем LLM-классификатор экрана из auto_public в наш autowarm как **опциональный fallback** для unknown-screen recovery в `publisher.py` camera-wait/editor loop'ах (и возможно `warmer.verify_and_switch_account`). Контракт минимальный: screenshot + XML-snippet → предложение действия. Должен быть **feature-flagged** и иметь hard fallback на текущий flow (не регрессировать). Ожидаемая нагрузка — менее $5/месяц на инференс при текущем volume.

## 1. Что есть в чужом коде

### `auto_public/services/llm_manager.py` (136 строк)

```python
class LLMManager:
    def handle_step(self, description: str, do_retry: bool = True) -> bool:
        # 1. snapshot() через Airtest → temp{id}.png
        # 2. Формируется prompt: system_rare.txt + description
        # 3. LLM отвечает списком команд, по строке:
        #      touch(x_percent, y_percent)
        #      alert("message")
        #      confirm()            ← успех
        # 4. Выполняются команды; если retry — уточняющий prompt + повтор
```

**Команды LLM:**
- `touch(x, y)` — x/y как доли экрана (0.0-1.0)
- `alert(msg)` — эскалация в Telegram (не наш use case, заменим на log_event)
- `confirm()` — проблема решена, return True

### `auto_public/llm_providers/anthropic.py` (58 строк)

```python
class AnthropicAPI:
    # модель по умолчанию: claude-sonnet-4-6
    # max_tokens: 1024
    # контент: image (base64) + text prompt
    # system_prompt (optional)
```

Тонкая обёртка над `anthropic.Anthropic(api_key).messages.create(model, messages=[{image, text}])`. Никаких token-stream'ов, batch'ей, tool-use.

### `auto_public/llm_providers/open_router.py` (не читал, предполагаем аналог для OpenRouter proxy)

## 2. Интеграционные точки в нашем коде

### А. `publisher.py` camera-wait loop (:2020-2050)

**Текущий flow (пост-fix IG T1):**
1. `dump_ui()` → XML
2. Сработал детектор highlights empty-state? → recovery
3. Сработал детектор gallery-picker? → recovery
4. Достиг 3-й попытки без детекторов? → full-reset app
5. Получил camera? → продолжить

**С LLM-recovery (Option-A, минимальный overhead):**
- **ПЕРЕД full-reset на 3-й попытке** (шаг 4) — вызов LLM с XML + screenshot.
- LLM возвращает: (а) `tap:x%,y%` чтобы продвинуться к камере; (б) `restart_app`; (в) `unknown` (тогда fallback на full-reset).
- Если LLM подсказал tap и после этого появились camera-маркеры → `continue`, камера открыта без force-stop.
- Метрика: сколько full-reset'ов спасли (economy) vs сколько раз LLM привёл в ещё более сломанный state (regression).

### B. `warmer.py::verify_and_switch_account` (если уже задеплоен force-reset fix — `fix-warmer-force-reset-app.md` ✅)

**Использование:** LLM ПОСЛЕ 3-го неудачного account-read, ПЕРЕД выбросом exception. Экраны, где account-switcher мог бы помочь, но не хватило паттерна. Если LLM говорит `confirm()` после своих действий — повторить account-read один раз.

### C. `publisher.py` editor-loop (post camera-open)

Следующий этап сложности: unknown screens в редакторе (текст caption, fields, выборы sound). Сейчас там много hand-coded детекторов. Хороший кандидат для LLM assist, но **не в MVP**.

## 3. Контракт port'а

```python
class ScreenRecoveryLLM:
    """
    Fallback-классификатор экрана для unknown-state recovery.

    Feature-flagged через autowarm_settings:
        screen_recovery_llm_enabled (default: false)
        screen_recovery_llm_provider (default: 'anthropic'; 'openrouter' как fallback)
        screen_recovery_llm_model (default: 'claude-sonnet-4-6')
        screen_recovery_llm_daily_budget_usd (default: 5.0)
    """
    def classify_and_act(
        self,
        *,
        ui_xml: str,                    # DumpUI output (может быть truncated >4KB)
        screenshot_path: str,           # local path, созданный через adb exec-out screencap -p
        step: str,                      # 'open_camera' | 'switch_account' | 'editor_caption' | ...
        platform: str,                  # 'Instagram' | 'TikTok' | 'YouTube'
        last_action: str,               # что мы попробовали перед этим (e.g. "tapped +, waited 5s")
        attempt: int,                   # номер попытки в текущем loop'е
        task_id: int,                   # для log_event корреляции
    ) -> dict:
        """
        Returns dict с полями:
            action: 'tap' | 'restart_app' | 'back' | 'wait' | 'unknown'
            coords: tuple[int, int] | None  — только для action='tap', абсолютные px
            confidence: float 0.0-1.0
            rationale: str — короткое объяснение от LLM (для log_event meta)
            tokens_input: int
            tokens_output: int
            cost_usd: float
        """
```

**Обязательные свойства:**
1. **Hard fallback:** если confidence < 0.7 → возвращает `action='unknown'` → caller продолжает существующий flow (full-reset/error).
2. **Timeout:** 15s на одну call (LLM API + network); по timeout → `action='unknown'`.
3. **Rate-limit:** максимум 1 LLM call на задачу по умолчанию; через настройку можно поднять до 3 (retry на unknown-state).
4. **Daily budget guard:** сохранение `cost_usd` в `autowarm_llm_spend` таблицу, при превышении `daily_budget_usd` — автоматическое отключение на день.
5. **Observability:** каждый call → `log_event('info', meta={'category':'llm_recovery_call', 'action':..., 'confidence':..., 'tokens_input':..., 'cost_usd':...})` для SQL-аналитики.

## 4. Оценка стоимости (per-call)

**Input:**
- Screenshot 1080×2340 (Android phones) → ~2000-3000 tokens для Claude Sonnet 4.6
- XML-snippet 4KB → ~1000 tokens (truncated)
- System-prompt + step description + last_action → ~500 tokens
- **Total input: ~4000 tokens**

**Output:** ~200-500 tokens (action + rationale)

**Стоимость на Sonnet 4.6 (Anthropic):**
- $3/1M input → $0.012 per call
- $15/1M output → $0.0075 per call
- **~$0.02 per call**

**Volume oценка:** 
- baseline unknown-state events в farming/publish: ~10-20/day (evidence farming-baseline-20260419.md)
- С LLM recovery: при 1 call/событие → **~$0.20-0.40/day**
- Месяц: **~$6-12**

Daily budget $5 = безопасный guard, никогда не должен триггериться.

## 5. Prompt design (первая итерация)

System prompt (~500 tokens, в отдельном файле `autowarm/prompts/screen_recovery_system.md`):
```
Ты — агент-помощник UI-автоматизации для мобильных приложений (Instagram/TikTok/YouTube).
Твоя задача — по скриншоту экрана и XML UI-tree определить, что пошло не так,
и предложить ровно одно действие для продвижения к цели.

Цели по platform/step:
  open_camera: открыть камеру для записи/выкладки контента.
  switch_account: переключить аккаунт на указанный в параметре `target_account`.
  editor_caption: перейти к полю ввода caption.

Формат ответа (строго JSON, одна строка):
  {"action": "tap", "coords_pct": [0.5, 0.9], "confidence": 0.85, "rationale": "..."}
  {"action": "restart_app", "confidence": 0.9, "rationale": "..."}
  {"action": "back", "confidence": 0.8, "rationale": "..."}
  {"action": "unknown", "confidence": 0.0, "rationale": "..."}

Правила:
- Предлагай tap с coords_pct (0.0-1.0 от экрана).
- Если confidence < 0.7 — обязательно `"action": "unknown"`.
- Никаких пояснений вне JSON.
```

User prompt (на каждый call):
```
platform: {platform}
step: {step}
last_action: {last_action}
attempt: {attempt}

UI XML (truncated):
{ui_xml[:4096]}

[image: screenshot attached]
```

## 6. Acceptance для полного plan'а (следующая итерация)

Когда будем писать полноценный `/aif-plan full "LLM screen-recovery ..."`:

1. MVP scope: **только** IG camera-wait loop (3-й попытки, до full-reset). TT/YT/editor-loop — out of scope MVP.
2. Testing: unit-тесты на parse-LLM-response + feature-flag + budget-guard + timeout-fallback. Integration-тест через mocked AnthropicAPI.
3. Deploy: `autowarm_settings.screen_recovery_llm_enabled=false` по умолчанию → включается **руками** на 1-2 устройства для pilot.
4. Pilot-критерий (1 неделя, 2 устройства): ≥5 случаев где `action != 'unknown'` + `ig_camera_open_failed` count не вырос. Если хотя бы один случай где LLM "сломал" иначе рабочий flow — rollback.
5. Observability SQL: `scripts/llm_recovery_48h.sql` — calls/day, action distribution, confidence histogram, cost per day.

## 7. Зависимости и блокеры

- **API key Anthropic** — уже используется (validator сервис, memory `project_contenthunter_server` + Эль-косметик PLAN.md upcoming Anthropic calls). Можно reuse.
- **`anthropic` Python SDK** — версия в requirements уточнить; auto_public использует 0.57.x (из импортов).
- **Screenshot capture** в autowarm: проверить через `grep -n 'screencap\|screenshot' publisher.py` что есть helper типа `_capture_screenshot(path)`; если нет — добавить 10-строчный `adb exec-out screencap -p > file.png`.
- **Feature-flag таблица** `autowarm_settings` — существует per memory `project_autowarm_code`. Добавить 4 строки (enabled/provider/model/daily_budget).
- **НЕ зависит от:** fix-warmer-force-reset-app (он самостоятельный), chunked-push (ортогонально).

## 8. Риски

| Риск | Вероятность | Митигация |
|---|---|---|
| LLM выдаёт плохие координаты → нажали не туда → сломали state | med | confidence threshold 0.7, 1 retry max, feature-flag |
| Задержка LLM call >15s тормозит pipeline | med | hard timeout → unknown → fallback на существующий flow |
| Cost overruns | low | daily_budget_usd guard + per-call cost logging |
| Anthropic API outage | low | OpenRouter как secondary provider в Phase 2 |
| Privacy (screenshots уходят в облако) | — | Уже делаем screen_record_url в S3; прецедент есть |

## 9. Готовые команды для следующей сессии

```bash
# 1. Обновить клон (если потребуется свежий код)
git -C /tmp/auto_public pull

# 2. Запустить полный план (следующий /aif-plan full):
/aif-plan full "LLM screen-recovery (port auto_public/llm_manager) для IG camera-wait loop unknown-state в publisher.py — feature-flagged, Anthropic-only MVP, daily budget guard"
```

## 10. Что НЕ брать из auto_public

- **Airtest-зависимость** (`from airtest.core.api import snapshot, touch`) — у нас ADB, не используем
- **Telegram alert с draw_touch_circles_on_image** — log_event достаточно; alert'ы в Telegram у нас в другом месте
- **prompts/system_rare.txt** (их оригинальный prompt) — пишем свой с нуля, потому что их auto_public prompt предположительно затюнен под uploader-flow, не screen-recovery
- **OpenRouter** в MVP — добавим во второй итерации, если понадобится fallback на другие модели

## Метаданные

- `/tmp/auto_public` commit `2aa9b4c` (last 2026-04-17)
- Связанные evidence: `farming-reuse-matrix-20260419.md`, `farming-t7-auto-public-audit-20260419.md`, `farming-t9-reuse-matrix-20260419.md` §Candidate D.
- Model knowledge cutoff: 2026-01, target model `claude-sonnet-4-6` (production Anthropic family).
