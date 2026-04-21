# Evidence — Publish testbench + agent fix-loop, отгружено 2026-04-21

**План-источник:** `.ai-factory/plans/publish-testbench-agent-20260421.md`
**Сессия:** одна, ~3 часа
**Итог:** 18 из 19 задач (T16 CI-gate отложен с обоснованием)
**Статус эксплуатации:** стенд работает 24/7, autofix включён

## Что отгружено

### На VPS fra-1-vm-y49r

| Слой | Компонент | Где |
|---|---|---|
| DB | 5 новых таблиц + 3 колонки в `publish_tasks` + 1 trigger | применено на прод (openclaw DB) |
| Scheduler split | prod `scheduler.js` игнорит `testbench=TRUE`; thin `testbench_scheduler.js` в user-space | `/home/claude-user/autowarm-testbench/` |
| Orchestrator 24/7 | systemd `autowarm-testbench-orchestrator.service` | ротация IG/TT/YT per 10 мин на phone #19 |
| Fixture dump | hook в `publisher.py::_dump_testbench_fixture` | `/home/claude-user/testbench-fixtures/*.tar.gz` |
| Triage (Phase B) | `triage_classifier.py` + `agent_diagnose.py` (Groq llama-3.3-70b) | отчёты в `evidence/publish-triage/` |
| Autofix (Phase C) | `agent_apply.py` + `fixes/{timeout_bump,retry_transient,selector_drift}.py` | за двойным gate'ом AUTO_FIX_ENABLED |
| Auto-rollback | systemd timer 15 мин `autowarm-testbench-rollback.timer` | revert'ит фиксы без +10pp улучшения |
| Dashboard | `delivery.contenthunter.ru/testbench.html` | live мониторинг |
| Telegram | `@ffmpeg_notificator_gengo_bot` (chat_id 242574724) | failure/success/escalation |

### Кнопки пользователя

- `testbench-status.sh` / `testbench-start.sh` / `testbench-stop.sh` в `/usr/local/bin/`
- `https://delivery.contenthunter.ru/testbench.html` (auth как autowarm)
- SQL flags: `testbench_paused`, `auto_fix_enabled`, `triage_enabled`, `orchestrator_cadence_min` в таблице `system_flags`

## Первые метрики (на 2026-04-21 11:10 UTC, ~1.5ч работы стенда)

```
completed_tasks            |    12
failed                     |    12
success                    |     0
open_investigations        |     4
agent_diagnose_runs        |     4
agent_apply_runs           |     0
total_agent_cost_usd_cents |     1
```

Zero success rate подтверждает жалобу заказчика «публикация совсем не работает». Стенд выявил это не теоретически, а фактически за 90 минут работы.

## Открытые кластеры (4)

| error_code | Повторов | Auto-fixable | Класс |
|---|---|---|---|
| `adb_push_chunked_md5_mismatch` | ~7 | FALSE (физический) | **Главный бренд** — chunks передались, cat merge дал 0 байт |
| `adb_push_chunked_failed` | 2 | FALSE | Симптом того же бага (cat merge failed) |
| `yt_accounts_btn_missing` | 1 | FALSE | UI-кандидат на `selector_drift` |
| `adb_push_chunked` | 1 | FALSE | Общая адб-категория |

## Главная техническая находка

**`remote_md5 = d41d8cd98f00b204e9800998ecf8427e`** — это md5 **пустой строки**. Т.е. после успешного `adb push` всех 9 chunks, `cat chunk_0..chunk_8 > final` на устройстве создаёт файл **0 байт**. Воспроизводится на всех 3 платформах на phone #19. Это НОВЫЙ баг поверх известного ADB packet loss (memory `project_adb_push_network_issue`) — **сам `adb_push_chunked` workaround сломан**.

Диагноз LLM: `evidence/publish-triage/adb_push_chunked_md5_mismatch-20260421-094405-task523.md`. Confidence 6/10, human_review_required. Гипотезы: race в cat, SE Linux label mismatch, tmpfs-ограничение, firmware-update.

## Что сделано сверх плана

- **Колонка «Старт»** на `#publishing/publishing?sub=up:tasks` теперь показывает `created_at` с иконкой 🧪 для testbench-задач (у них `started_at=NULL` т.к. падают до старта publisher'а).
- **`testbench-status.sh`** даёт snapshot: flags, PM2 state, systemd units, investigations, 1h activity, прод-autowarm health.
- **Auto-register unknown error_codes** в `publish_error_codes` — новые `meta.category` из events больше не теряются, автоматически регистрируются `is_known=FALSE`.

## Отложено

- **T16 CI-gate** — требует XML-replay harness для прогона публикатора против корпуса без реального устройства. Нетривиальная задача. Текущий корпус использовать для manual debugging до реализации harness'а.
- **`selector_drift` полная реализация** — сейчас scaffolded. Активируется при первом воспроизводимом UI-drift кейсе. `yt_accounts_btn_missing` — первый кандидат для отработки.
- **Permanent Anthropic API key** — сейчас Groq. Когда появится `sk-ant-api03-...` из console.anthropic.com → смена одного env var `AGENT_DIAGNOSE_PROVIDER=anthropic`.

## Куда дальше

1. **Первый autofix** ждём когда появится реальный `ig_editor_timeout` / `tt_upload_confirmation_timeout` / аналог — тогда `timeout_bump` сработает. Прод стенда сейчас обламывается ДО editor phase (ADB push не доходит), так что autofixable кейс появится только после фикса `adb_push_chunked_md5_mismatch`.
2. **Решение по `adb_push_chunked_md5_mismatch`** — требует human debugging на устройстве (SSH в Raspberry, проверка tmpfs, SE Linux, firmware). Вне auto-loop scope.
3. **После фикса главного бага** — стенд начнёт выходить дальше publisher-этапов и обнаружит следующий слой классов (UI-драйфты Instagram/TikTok/YouTube). Вот тогда `selector_drift` и реальные `timeout_bump` станут на поток.
