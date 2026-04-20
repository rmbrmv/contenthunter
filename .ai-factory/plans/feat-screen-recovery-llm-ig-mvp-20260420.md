# План: LLM screen-recovery MVP для IG camera-wait loop

**Создан:** 2026-04-20
**Режим:** Full (new feature, 11 задач в 5 фазах)
**Slug:** `feat-screen-recovery-llm-ig-mvp`
**Ветка в contenthunter:** нет (plan & evidence only, code в autowarm)
**Ветка в autowarm:** без feature-ветки (convention: pre-commit hook auto-push в main)
**Brief:** `contenthunter/.ai-factory/plans/llm-screen-recovery-brief-20260420.md`
**Источник:** umbrella `contenthunter/.ai-factory/plans/open-followups-20260420.md` T5 + farming-reuse-matrix Candidate D

## Settings

| | |
|---|---|
| Testing | **yes** — unit-тесты на parse/confidence/budget/timeout + mocked integration test |
| Logging | **verbose** — DEBUG на каждый вызов/ответ LLM, meta в `log_event` для каждого outcome |
| Docs | **yes** — новая фича с runtime-toggle, docs-чекпоинт обязателен (секция про feature flag + observability SQL + rollback steps) |
| Roadmap linkage | skipped — `paths.roadmap` отсутствует |

## Контекст / уже проверено

- **anthropic** 0.84.0 установлен (`python3 -c "import anthropic"`)
- **autowarm layout** — flat (per memory `project_autowarm_code`); сервис будет `autowarm/screen_recovery.py` (новый flat-модуль), а не `services/screen_recovery/...`
- **Screenshot helper** — `publisher.py:1878 _save_debug_artifacts` уже делает `screencap + pull + S3 upload`. MVP использует локальный путь до S3, без upload шаги.
- **`autowarm_settings`** schema = `(id, key, value text)`. Flag-convention: `value='true'|'false'`. Новые row'ы добавляются SQL INSERT.
- **Модель:** default = `claude-sonnet-4-6` (latest Claude 4.X). NB: не `claude-3-5-sonnet` (устаревшая).
- **System prompt** — инлайнится как module-level константа `SCREEN_RECOVERY_SYSTEM_PROMPT` в `screen_recovery.py` (не отдельный файл — proще).

## Scope MVP

**ВХОДИТ:**
- Только IG camera-wait loop (`publisher.py:2020-2050`, ветка «unknown screen после 3-х попыток»)
- Feature-flag (default OFF) + daily budget guard
- Anthropic-only provider (без OpenRouter)
- Screenshot + XML snippet как LLM input; ответ = `{action, coords_pct, confidence, rationale}`
- 1 LLM call per publish task (rate-limit)
- Fallback на текущий full-reset при confidence<0.7 / timeout / budget / exception

**НЕ ВХОДИТ:**
- TikTok/YouTube camera-loop (extensions после pilot review)
- IG/TT/YT editor-loop
- `warmer.verify_and_switch_account` integration
- OpenRouter provider
- Реальный pilot >2 устройств
- UI для feature-flag toggle

## Граф зависимостей

```
T1 (DB setup) ─┐
                ├─► T3 (service core) ─┐
T2 (no-op)     ─┘                      ├─► T6 (integration) ─► T10 (deploy/pilot) ─► T11 (week-1 review)
                T4 (budget) ──────────►┤
                T5 (screenshot helper) ┘
                                       │
                T7 (unit tests) ───────┤
                T8 (integration test) ─┤
                                       │
                T9 (observability SQL)─┘
```

## Tasks (11)

### Phase 1 — DB Foundations (T1-T2)

#### T1 — Schema + feature-flag seeding ✅ (2026-04-20)

**Что сделать:**

1. Добавить 4 row'а в `autowarm_settings` (idempotent INSERT ON CONFLICT):
   ```sql
   INSERT INTO autowarm_settings (key, value) VALUES
     ('screen_recovery_llm_enabled', 'false'),
     ('screen_recovery_llm_provider', 'anthropic'),
     ('screen_recovery_llm_model', 'claude-sonnet-4-6'),
     ('screen_recovery_llm_daily_budget_usd', '5.0')
   ON CONFLICT (key) DO NOTHING;
   ```
2. CREATE TABLE `autowarm_llm_spend` для cost-tracking:
   ```sql
   CREATE TABLE IF NOT EXISTS autowarm_llm_spend (
     id SERIAL PRIMARY KEY,
     spend_date DATE NOT NULL DEFAULT CURRENT_DATE,
     task_id INT,
     platform TEXT,
     device_serial TEXT,
     tokens_input INT NOT NULL,
     tokens_output INT NOT NULL,
     cost_usd NUMERIC(10, 6) NOT NULL,
     outcome TEXT NOT NULL,       -- action returned by LLM
     created_at TIMESTAMP NOT NULL DEFAULT NOW()
   );
   CREATE INDEX IF NOT EXISTS idx_autowarm_llm_spend_date
     ON autowarm_llm_spend (spend_date);
   ```
3. Сохранить skrit `autowarm/scripts/llm_recovery_schema.sql` для повторного применения.

**Файлы:**
- `/root/.openclaw/workspace-genri/autowarm/scripts/llm_recovery_schema.sql` (новый)

**Acceptance:**
- `psql -f scripts/llm_recovery_schema.sql` — exit 0, таблица создана, 4 row'а добавлены.
- `SELECT key FROM autowarm_settings WHERE key LIKE 'screen_recovery_%'` — 4 rows.

**Логирование:** standard — SQL вывод в evidence.

---

#### T2 — System prompt draft ✅ (2026-04-20; inline const в screen_recovery.py)

**Что сделать:**

Не создаём отдельный файл; prompt будет как module-level const в `screen_recovery.py`. Содержимое prompt'а (см. brief §5) — финализировать здесь:

```
Ты — агент-помощник UI-автоматизации Instagram для Android.
Задача — по скриншоту и XML-UI-tree определить, что не так, и предложить ровно
одно действие для продвижения к цели open_camera (открыть Reels-камеру).

Типичные знакомые экраны Reels-flow (не блокеры):
  - Reels-камера (кнопка записи, карусель Create/Story/Reel)
  - bottomsheet "New post" (Post/Reel/Story)

Блокеры (нужен recovery):
  - Highlights empty-state ("Добавление в актуальное")
  - Gallery picker (feed_gallery_app_bar, gallery_folder_menu_container)
  - Profile stuck (Редактировать профиль)
  - Logged-out state (Войти/Sign up)
  - Unknown — если confidence меньше 0.7

Формат ответа — строго JSON, одна строка, без обёрток markdown:
  {"action":"tap","coords_pct":[0.5,0.9],"confidence":0.85,"rationale":"..."}
  {"action":"restart_app","confidence":0.9,"rationale":"..."}
  {"action":"back","confidence":0.8,"rationale":"..."}
  {"action":"unknown","confidence":0.0,"rationale":"..."}

Правила:
- coords_pct только с action="tap", числа 0.0-1.0 от размеров экрана.
- confidence < 0.7 → обязательно "action":"unknown".
- Никаких пояснений вне JSON. Вывод — ровно одна строка.
```

**Файлы:**
- Черновик prompt'а в конце T2, финал встроится в `screen_recovery.py` при T3.

**Acceptance:** prompt-text прописан в T3 как `SCREEN_RECOVERY_SYSTEM_PROMPT`.

**Логирование:** N/A (текст, не код).

---

### Phase 2 — Service (T3-T5)

#### T3 — `screen_recovery.py` — ScreenRecoveryLLM class core ✅ (2026-04-20; import OK, settings load)

**Что сделать:**

Новый модуль `autowarm/screen_recovery.py` с классом `ScreenRecoveryLLM` по контракту из brief §3:

```python
# autowarm/screen_recovery.py
from __future__ import annotations
import base64, json, logging, os, time
from typing import Optional
import psycopg2
import anthropic

from publisher import DB_CONFIG   # reuse существующую connection config

log = logging.getLogger('autowarm.screen_recovery')

SCREEN_RECOVERY_SYSTEM_PROMPT = """..."""  # из T2

class ScreenRecoveryLLM:
    """Fallback-классификатор экрана. Feature-flagged через autowarm_settings."""

    DEFAULT_MODEL = 'claude-sonnet-4-6'
    DEFAULT_TIMEOUT_S = 15
    CONFIDENCE_THRESHOLD = 0.7

    # Claude Sonnet 4.6 pricing (per 1M tokens, USD):
    PRICE_INPUT_PER_M = 3.0
    PRICE_OUTPUT_PER_M = 15.0

    def __init__(self, settings: Optional[dict] = None):
        self._settings = settings or self._load_settings()
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise RuntimeError('ANTHROPIC_API_KEY not set')
        self._client = anthropic.Anthropic(api_key=api_key)

    @staticmethod
    def _load_settings() -> dict:
        """Читает screen_recovery_llm_* ключи из autowarm_settings."""
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM autowarm_settings "
                    "WHERE key LIKE 'screen_recovery_llm_%%'")
        rows = {k: v for k, v in cur.fetchall()}
        conn.close()
        return rows

    @property
    def enabled(self) -> bool:
        return self._settings.get('screen_recovery_llm_enabled', 'false').lower() == 'true'

    def classify_and_act(self, *, ui_xml: str, screenshot_path: str,
                         step: str, platform: str, last_action: str,
                         attempt: int, task_id: int) -> dict:
        """..."""
        log.debug(f'[screen-recovery] classify_and_act task={task_id} '
                  f'platform={platform} step={step} attempt={attempt} '
                  f'screenshot={screenshot_path}')
        if not self.enabled:
            return {'action': 'unknown', 'confidence': 0.0,
                    'rationale': 'feature_disabled', 'cost_usd': 0.0,
                    'tokens_input': 0, 'tokens_output': 0}
        # ... (budget check в T4, call в T3)
```

**Компоненты T3 (без budget/screenshot — они в T4/T5):**
- `__init__`, `_load_settings()`, `enabled` property.
- `classify_and_act()` skeleton — читает `screenshot_path` (ожидает PNG на диске), формирует user-prompt, вызывает `self._client.messages.create`, парсит JSON.
- `_parse_response(raw: str) -> dict` — валидатор JSON, accept/reject по confidence.
- `_compute_cost(msg) -> float` — из `msg.usage.input_tokens/output_tokens`.

**Verbose логирование:**
- `log.debug` на каждый вызов `messages.create` (model, max_tokens, input-hash).
- `log.info` на финальный result (action, confidence, cost_usd).
- `log.warning` если JSON parse failed или confidence<0.7 → возвращаем unknown.
- `log.error` на исключения от API.

**Файлы:**
- `/root/.openclaw/workspace-genri/autowarm/screen_recovery.py` (новый)

**Acceptance:**
- `python3 -c "from screen_recovery import ScreenRecoveryLLM"` — import без ошибок.
- `ScreenRecoveryLLM().enabled == False` (флаг OFF по умолчанию).

**Блокируется:** T1 (DB rows для `_load_settings`).

---

#### T4 — Budget guard + spend tracking ✅ (2026-04-20; _check_budget + _record_spend в screen_recovery.py)

**Что сделать:**

В том же `screen_recovery.py` добавить:

```python
def _check_budget(self) -> bool:
    """Возвращает True если в пределах daily_budget_usd, False иначе."""
    budget = float(self._settings.get('screen_recovery_llm_daily_budget_usd', '5.0'))
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(cost_usd), 0)::numeric(10,6)
          FROM autowarm_llm_spend
         WHERE spend_date = CURRENT_DATE
    """)
    spent_today = float(cur.fetchone()[0])
    conn.close()
    remaining = budget - spent_today
    log.debug(f'[screen-recovery] budget: spent={spent_today:.4f} '
              f'budget={budget:.2f} remaining={remaining:.4f}')
    return remaining > 0

def _record_spend(self, *, task_id: int, platform: str, device_serial: str,
                  tokens_input: int, tokens_output: int, cost_usd: float,
                  outcome: str) -> None:
    """..."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO autowarm_llm_spend "
        "  (task_id, platform, device_serial, tokens_input, "
        "   tokens_output, cost_usd, outcome) "
        "  VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (task_id, platform, device_serial, tokens_input,
         tokens_output, cost_usd, outcome),
    )
    conn.commit()
    conn.close()
```

Интегрировать в `classify_and_act`:
1. **Перед LLM call**: `if not self._check_budget(): return action=unknown, rationale='daily_budget_exhausted'`.
2. **После успешного LLM call**: `self._record_spend(...)` с реальным cost.
3. **При exception/timeout**: записать spend с `cost_usd=0, outcome='exception'` для trace.

**Логирование:**
- `log.warning('[screen-recovery] daily budget exhausted...')` при budget fail.
- `log.info(...)` с computed cost после записи.

**Блокируется:** T1 (таблица `autowarm_llm_spend` должна существовать).

**Acceptance:**
- Unit-тест `test_budget_guard_blocks_when_exhausted` (в T7) проходит.

---

#### T5 — Screenshot capture helper ✅ (2026-04-20; `_capture_screenshot_for_llm` в publisher.py)

**Что сделать:**

Добавить в `publisher.py` новый helper `_capture_screenshot_for_llm(self, label: str) -> Optional[str]`:

```python
def _capture_screenshot_for_llm(self, label: str) -> Optional[str]:
    """Snap screenshot в /tmp (без S3 upload — для LLM-recovery call).

    Отличается от `_save_debug_artifacts` тем, что:
    - не делает S3 upload (мы кормим локальный PNG в Anthropic);
    - не сохраняет UI XML (он уже в отдельной переменной у caller);
    - не логирует в events.

    Returns: локальный путь к PNG или None при ошибке.
    """
    import time, os
    ts = int(time.time())
    local = f'/tmp/screen_recovery_{self.task_id}_{label}_{ts}.png'
    remote = f'/sdcard/{os.path.basename(local)}'
    try:
        self.adb(f'screencap -p {remote}', timeout=10)
        pull = subprocess.run(
            ['adb', '-H', self.adb_host, '-P', str(self.adb_port),
             '-s', self.device_serial, 'pull', remote, local],
            capture_output=True, timeout=15,
        )
        self.adb(f'rm -f {remote}', timeout=5)
        if pull.returncode == 0 and os.path.exists(local) and os.path.getsize(local) > 0:
            log.debug(f'[screen-recovery] screenshot captured: {local} '
                      f'({os.path.getsize(local)/1024:.1f}KB)')
            return local
        log.warning(f'[screen-recovery] screenshot pull failed: rc={pull.returncode}')
        return None
    except Exception as e:
        log.warning(f'[screen-recovery] screenshot exception: {e}')
        return None
```

**Файлы:**
- `publisher.py` — добавить метод после `_save_debug_artifacts` (landmark ~:1878).

**Логирование:** уже указано выше (DEBUG на success, WARNING на failure).

**Acceptance:** метод есть в классе, возвращает путь или None; никогда не raise.

---

### Phase 3 — Integration (T6)

#### T6 — Wire in IG camera-wait loop ✅ (2026-04-20; 21 IG regression tests passed)

**Что сделать:**

Модифицировать `publisher.py::publish_instagram_reel` camera-wait loop (landmark :2020-2050) чтобы на 3-й неуспешной попытке (перед full-reset — существующим fallback) вызвать LLM recovery:

```python
# ... внутри camera-wait loop, после existing highlights/gallery detectors,
#     перед full-reset (`tried_full_reset` ветка) ...

if attempt == 3 and not tried_full_reset:
    try:
        from screen_recovery import ScreenRecoveryLLM
        recovery = ScreenRecoveryLLM()
        if recovery.enabled:
            self.log_event('info',
                'LLM screen-recovery попытка',
                meta={'category': 'llm_recovery_attempt',
                      'platform': self.platform, 'step': 'open_camera',
                      'attempt': attempt})
            screenshot = self._capture_screenshot_for_llm('ig_camera_wait_3rd')
            if screenshot:
                result = recovery.classify_and_act(
                    ui_xml=ui[:4096],
                    screenshot_path=screenshot,
                    step='open_camera', platform=self.platform,
                    last_action=f'camera_wait_attempt_{attempt}',
                    attempt=attempt, task_id=self.task_id,
                )
                self.log_event(
                    'info',
                    f"LLM recovery: action={result['action']} "
                    f"confidence={result.get('confidence', 0):.2f}",
                    meta={'category': 'llm_recovery_result', **result,
                          'platform': self.platform, 'step': 'open_camera'},
                )
                # Применяем action
                if result['action'] == 'tap' and result.get('coords_pct'):
                    x_pct, y_pct = result['coords_pct']
                    x, y = int(x_pct * SCREEN_W), int(y_pct * SCREEN_H)
                    log.info(f'  [LLM] tap ({x},{y}) confidence={result["confidence"]:.2f}')
                    self.adb_tap(x, y)
                    time.sleep(3)
                    continue  # заново проверим UI на следующей итерации
                elif result['action'] == 'back':
                    self.adb('shell input keyevent KEYCODE_BACK')
                    time.sleep(2)
                    continue
                elif result['action'] == 'restart_app':
                    # Fallthrough — пусть существующий full-reset сработает
                    log.info('  [LLM] suggested restart_app → fallthrough to full-reset')
                # action == 'unknown' — молча fallthrough
    except Exception as e:
        log.warning(f'[screen-recovery] failed, fallthrough to full-reset: {e}')

# ... existing full-reset код (tried_full_reset = True; am force-stop; ...)
```

**Где берутся SCREEN_W/SCREEN_H:** определены в `publisher.py` на module level (проверить — memory в `project_autowarm_code`). Если нет — добавить как `SCREEN_W, SCREEN_H = 1080, 2340` const (дефолт для Samsung S21-class).

**Логирование:**
- `log.info` на каждый принятый action.
- `log_event` с категорией `llm_recovery_attempt` / `llm_recovery_result` — для SQL-наблюдаемости.

**Файлы:** `publisher.py` (одно место правки).

**Блокируется:** T3, T4, T5.

**Acceptance:**
- Код компилируется (`python -c "import publisher"`).
- С `screen_recovery_llm_enabled=false` (default): поведение **идентично** текущему (ранний return `action=unknown` → fallthrough).
- `pytest tests/test_publisher_ig_camera_recovery.py` — зелёный (регрессия-guard для существующих детекторов).

---

### Phase 4 — Tests (T7-T8)

#### T7 — Unit tests `tests/test_screen_recovery.py` ✅ (2026-04-20; 9 unit passed)

**Что сделать:**

Новый файл `autowarm/tests/test_screen_recovery.py`:

```python
# 5-6 unit-тестов:
def test_parse_response_accepts_valid_tap():
    """JSON с tap+coords+confidence>=0.7 → action=tap."""

def test_parse_response_rejects_low_confidence():
    """confidence<0.7 → auto-downgrade to action=unknown."""

def test_parse_response_handles_malformed_json():
    """Ответ не-JSON → action=unknown с rationale='parse_error'."""

def test_budget_guard_blocks_when_exhausted():
    """Mock spend=6.0 USD, budget=5.0 → classify_and_act возвращает
    action=unknown, rationale='daily_budget_exhausted', без Anthropic-вызова."""

def test_disabled_flag_skips_api_call():
    """screen_recovery_llm_enabled=false → action=unknown мгновенно,
    Anthropic client.messages.create НЕ вызывается (mock.assert_not_called)."""

def test_record_spend_inserts_row():
    """После успешного call — row в autowarm_llm_spend добавлен с корректным cost."""

def test_timeout_fallback_returns_unknown():
    """Mock Anthropic raising anthropic.APITimeoutError → action=unknown,
    cost_usd=0, outcome='timeout'."""
```

Все тесты — mocked psycopg2 + anthropic.Anthropic. Используем `monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test')`.

**Файлы:**
- `autowarm/tests/test_screen_recovery.py` (новый)

**Acceptance:** `pytest tests/test_screen_recovery.py -v` → 7 passed.

---

#### T8 — Integration test (mocked Anthropic) ✅ (2026-04-20; 2 integration passed, total 11)

**Что сделать:**

В том же `test_screen_recovery.py` добавить 1-2 integration-теста (end-to-end через `classify_and_act`):

```python
def test_integration_tap_response_end_to_end(monkeypatch, tmp_path):
    """
    Mock Anthropic.messages.create возвращает корректный tap-response.
    Проверяем full chain: settings → enabled check → budget check →
    screenshot read → API call → parse → spend record → return.
    """
    # 1. Mock settings: enabled=true, budget=100.0.
    # 2. Mock autowarm_llm_spend (empty → budget OK).
    # 3. Create dummy 1KB PNG в tmp_path.
    # 4. Mock Anthropic response:
    #    Message(content=[TextBlock(text='{"action":"tap",...}')],
    #            usage=Usage(input_tokens=3000, output_tokens=200))
    # 5. Call classify_and_act — assert action='tap', cost≈$0.012.
    # 6. Assert _record_spend INSERT был вызван с корректными args.
```

Second integration test: unknown path — response='{"action":"unknown",...}' → no further actions triggered.

**Файлы:** тот же `test_screen_recovery.py`.

**Acceptance:** `pytest tests/test_screen_recovery.py -v` → 9-10 passed (T7+T8).

---

### Phase 5 — Observability + Deploy (T9-T11)

#### T9 — Observability SQL `scripts/llm_recovery_48h.sql` ✅ (2026-04-20; 5 секций выполняются чисто)

**Что сделать:**

Новый SQL-скрипт для ежедневного мониторинга:

```sql
\echo '=== 1. LLM recovery calls (48h) — volume + cost ==='
SELECT spend_date,
       COUNT(*)              AS calls,
       ROUND(SUM(cost_usd)::numeric, 4) AS total_cost_usd,
       ROUND(AVG(cost_usd)::numeric, 4) AS avg_cost_per_call,
       COUNT(*) FILTER (WHERE outcome='tap')        AS tap_count,
       COUNT(*) FILTER (WHERE outcome='unknown')    AS unknown_count,
       COUNT(*) FILTER (WHERE outcome='timeout')    AS timeout_count,
       COUNT(*) FILTER (WHERE outcome='exception')  AS exception_count
  FROM autowarm_llm_spend
 WHERE spend_date >= CURRENT_DATE - INTERVAL '2 days'
 GROUP BY spend_date ORDER BY spend_date DESC;

\echo '=== 2. LLM recovery outcomes → task final status (48h) ==='
SELECT ev->'meta'->>'action' AS llm_action,
       pt.status              AS task_final_status,
       COUNT(*) AS n
  FROM publish_tasks pt,
       LATERAL jsonb_array_elements(pt.events) ev
 WHERE COALESCE(pt.started_at, pt.updated_at) > NOW() - INTERVAL '48 hours'
   AND ev->'meta'->>'category' = 'llm_recovery_result'
 GROUP BY 1, 2 ORDER BY n DESC;

\echo '=== 3. Budget headroom (today) ==='
SELECT (SELECT value FROM autowarm_settings
         WHERE key='screen_recovery_llm_daily_budget_usd')::numeric AS budget,
       COALESCE(SUM(cost_usd), 0)::numeric(10,4)                    AS spent_today,
       (SELECT value FROM autowarm_settings
         WHERE key='screen_recovery_llm_enabled')                   AS enabled
  FROM autowarm_llm_spend
 WHERE spend_date = CURRENT_DATE;

\echo '=== 4. Camera-open outcome до/после LLM recovery (48h IG) ==='
-- PASS: % задач где llm_recovery_result был followed by camera-open success
SELECT
    COUNT(*) FILTER (WHERE had_llm AND task_done)                   AS llm_then_done,
    COUNT(*) FILTER (WHERE had_llm AND NOT task_done)               AS llm_then_failed,
    ROUND(100.0 * COUNT(*) FILTER (WHERE had_llm AND task_done) /
                  NULLIF(COUNT(*) FILTER (WHERE had_llm), 0), 1)    AS llm_success_rate_pct
FROM (
  SELECT pt.id,
         pt.status = 'done'                                         AS task_done,
         EXISTS (SELECT 1 FROM jsonb_array_elements(pt.events) ev
                  WHERE ev->'meta'->>'category' = 'llm_recovery_result'
                    AND ev->'meta'->>'action' != 'unknown')         AS had_llm
    FROM publish_tasks pt
   WHERE pt.platform = 'Instagram'
     AND COALESCE(pt.started_at, pt.updated_at) > NOW() - INTERVAL '48 hours'
) sub;
```

**Файлы:**
- `autowarm/scripts/llm_recovery_48h.sql` (новый)

**Acceptance:** `psql -f scripts/llm_recovery_48h.sql` — все 4 секции выполняются без ошибок (даже при пустых данных).

---

#### T10 — Deploy (commits + pm2 restart) + enable на 1 устройстве ⚠️ (2026-04-20; 4 commits + pm2 restart ✅; flag ON blocked — .env ANTHROPIC_API_KEY это OAuth token `sk-ant-oat...`, нужен service API key `sk-ant-api...`)

**Что сделать:**

1. **3 коммита в autowarm** (commit plan ниже):
   - `feat(screen-recovery): add DB schema + llm_recovery_schema.sql` (T1)
   - `feat(screen-recovery): ScreenRecoveryLLM service + IG camera-wait integration` (T2-T6)
   - `test(screen-recovery): unit + integration coverage (7 cases)` (T7-T8)
   - `chore(scripts): llm_recovery_48h.sql observability` (T9)

2. **Apply schema:** `psql -f scripts/llm_recovery_schema.sql`.

3. **pm2 restart:** `sudo -n pm2 restart autowarm`. Проверить `pm2 logs autowarm --lines 30` — import errors должны отсутствовать (0 новых exception).

4. **Pilot activation (manual, 1 устройство):**
   - Выбрать pilot device из фарминг-кластера (предложение: `RF8YA0V7LEH` — активное IG-устройство из tt_audit). Подтверждение у пользователя ОБЯЗАТЕЛЬНО перед включением.
   - `UPDATE autowarm_settings SET value='true' WHERE key='screen_recovery_llm_enabled';`
   - **Важно:** flag — глобальный. После установки **любая IG task с attempt==3** будет использовать LLM. Это приемлемо потому что:
     - (a) budget-guard ограничивает $5/day,
     - (b) без fallthrough на full-reset мы ничего не ломаем (всегда есть путь отката).

5. **Verify pm2-live:** первая публикация IG под этим флагом должна породить либо `llm_recovery_result` event (если попала в attempt==3), либо вообще ничего (task прошла успешно без camera-wait проблем).

**Rollback (в случае проблем):**
```sql
UPDATE autowarm_settings SET value='false' WHERE key='screen_recovery_llm_enabled';
```
Эффект — мгновенный (следующий task уже не идёт в LLM call).

**Подтверждение у пользователя:** ОБЯЗАТЕЛЬНО перед Step 4 и 5, так как это shared-state (prod autowarm).

**Файлы:** никаких новых, только commits + psql + pm2.

**Acceptance:**
- 4 коммита, auto-push OK.
- pm2 status: online, 0 новых exceptions в logs.
- 1 реальный `llm_recovery_attempt` event в `publish_tasks.events` в течение 1-2h после включения (либо опционально — 0, если задач с attempt==3 не было).

**Блокируется:** T1-T9.

---

#### T11 — Week-1 pilot review

**Что сделать (через 7 дней, ≈2026-04-27):**

1. Прогнать `scripts/llm_recovery_48h.sql` (или расширить на 7d window).
2. Собрать evidence в `contenthunter/.ai-factory/evidence/llm-recovery-pilot-week1-20260427.md`:
   - `calls_total`, `total_cost_usd` — в пределах ли budget'а.
   - `llm_success_rate_pct` — % задач где LLM suggestion → eventual `task.status=done`. Target: ≥30% (если confidence≥0.7 — должно быть осмысленно).
   - Сравнение с baseline (до включения): `ig_camera_open_failed` events/day — должны либо снизиться, либо хотя бы не вырасти.
   - **Red flags:**
     - `exception_count` > `tap_count` → API/integration проблема.
     - `timeout_count` > 30% — мы тормозим pipeline, надо уменьшить timeout или вообще откатить.
     - `cost_usd > $5/day` несколько дней подряд → пересмотреть budget.

3. Решение: **continue pilot / expand scope / rollback**.
   - Continue → оставить flag ON ещё неделю, review на неделе 2.
   - Expand → новый `/aif-plan full "LLM recovery — port на TT/YT camera-loop"`.
   - Rollback → `UPDATE autowarm_settings SET value='false' WHERE key='screen_recovery_llm_enabled';` + memory-заметка о том почему не пошло.

**Файлы:**
- `contenthunter/.ai-factory/evidence/llm-recovery-pilot-week1-20260427.md` (новый)

**Acceptance:** evidence-файл заполнен, decision point документирован.

---

## Commit Plan

### Checkpoint 1 — T1 (autowarm)
```
feat(screen-recovery): add autowarm_settings rows + autowarm_llm_spend table

- 4 settings keys (enabled, provider, model, daily_budget_usd)
- autowarm_llm_spend table for per-call cost tracking
- scripts/llm_recovery_schema.sql for idempotent re-apply
```

### Checkpoint 2 — T2-T6 (autowarm)
```
feat(screen-recovery): ScreenRecoveryLLM service + IG camera-wait integration

- autowarm/screen_recovery.py (new module)
- SCREEN_RECOVERY_SYSTEM_PROMPT inline const
- classify_and_act: budget guard, timeout, confidence threshold 0.7
- publisher.py: _capture_screenshot_for_llm helper
- publisher.py: wire into IG camera-wait loop at attempt==3 pre-reset

Feature flag OFF by default — no behavior change post-deploy until
screen_recovery_llm_enabled=true.
```

### Checkpoint 3 — T7-T8 (autowarm)
```
test(screen-recovery): unit + integration coverage (9 cases)

- parse/confidence/budget/timeout/disabled-flag paths
- end-to-end mocked Anthropic response (tap + unknown)
```

### Checkpoint 4 — T9 (autowarm)
```
chore(scripts): llm_recovery_48h.sql observability

Volume/cost/outcome by day, budget headroom, llm_success_rate_pct.
```

### Checkpoint 5 — T10-T11 (contenthunter evidence)
```
docs(evidence): LLM screen-recovery deploy notes + pilot week-1 review
```

## Риски и контр-меры

| Риск | Вероятность | Митигация |
|---|---|---|
| LLM выдаёт плохие coords → тап не туда → state хуже | med | `confidence≥0.7`, feature-flag rollback мгновенно |
| Anthropic API медленный → pipeline тормозится | med | 15s hard timeout → fallthrough на full-reset |
| Cost спайк из-за багов | low | `daily_budget_usd` guard + `autowarm_llm_spend` audit |
| Import `anthropic` ломает pm2 после deploy | low | `python -c "import anthropic"` перед deploy; SDK уже установлен (0.84.0 ✓) |
| Privacy (скриншоты уходят в Anthropic cloud) | — | Уже делаем screen_record S3 upload; прецедент есть. OK. |
| Regression для существующих IG тестов | low | `test_publisher_ig_camera_recovery.py` остаётся как regression-guard |
| Global flag влияет на все IG задачи | med | Pilot — 1 день ON → review; если OK — неделя; если нет — instant rollback |

## Что НАМЕРЕННО не делаем в MVP

- TikTok/YouTube camera-loop integration (только IG).
- Editor-loop integration.
- Warmer account-switch integration.
- OpenRouter provider (только Anthropic).
- Per-device feature-flag (пока глобальный; budget-guard страхует).
- UI для toggle (только SQL UPDATE).
- Кэш LLM-ответов для одинаковых UI states (может быть Phase 2, не MVP).
- Retry LLM на malformed JSON (один shot, fallback на unknown).

## Next step

После review — `/aif-implement` пойдёт T1→T2→T3-T5 (последовательно, T2 inline в T3) → T6 → T7-T8 (параллельно по смыслу) → T9. Deploy (T10) и pilot (T11) **требуют явного подтверждения** пользователя перед применением.

Оценка времени:
- T1-T9 (coding + tests + observability): ~2-3h
- T10 (deploy, manual pilot activation): 15 мин + monitoring
- T11 (неделя пилота): passive wait + 30 мин evidence
