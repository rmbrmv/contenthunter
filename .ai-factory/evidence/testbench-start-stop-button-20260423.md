# Evidence — Кнопка Start/Stop на testbench.html

**План:** `.ai-factory/PLAN.md` (fast-mode)
**Ветка autowarm (prod):** `feature/testbench-iter-4-publish-polish` → commit `616421a`
**Ветка autowarm-testbench:** `testbench` → commit `a907914`
**Дата:** 2026-04-23

## Что отгружено

- `POST /api/publish/testbench/start` и `POST /api/publish/testbench/stop` в `server.js` (после существующих testbench-read-only эндпоинтов, ~строка 2030).
- Обёрнуты через `child_process.execFile('/usr/local/bin/testbench-start.sh' | 'testbench-stop.sh', ['--force']?, { timeout: 60000 })`. Логика остаётся в shell-скриптах (DRY).
- Лог-формат: `[testbench-ui] start|stop requested/done/failed user=<id> ip=<ip> elapsed_ms=<n>`.
- UI-кнопка в карточке «🚦 Kill-switches» на `public/testbench.html`. Лейбл/цвет перерисовываются в `render()` по `data.flags[testbench_paused]`:
  - `paused=false` → «🛑 Остановить стенд» (red)
  - `paused=true` → «▶ Запустить стенд» (green)
- `handleToggle(action)` с `confirm()`, дисабл+⏳ на время запроса, `loadAll()` после для освежения данных.

## Smoke

| Проверка | Результат |
|---|---|
| `sudo pm2 restart autowarm` — сервер не крашнулся | ✅ (uptime 0s → online, логи показывают штатную работу publisher/warmer) |
| `node --check server.js` | ✅ SYNTAX_OK |
| JS-парсинг в `testbench.html` | ✅ `new Function(js)` проходит |
| `curl -X POST /api/publish/testbench/start` без cookie | ✅ HTTP 401 `{"error":"Unauthorized"}` |
| `curl -X POST /api/publish/testbench/stop` без cookie | ✅ HTTP 401 |
| `/usr/local/bin/testbench-start.sh` → flag=false | ✅ `updated_by=testbench-start` |
| `/usr/local/bin/testbench-stop.sh --force` → flag=true | ✅ `updated_by=testbench-stop` (исходное состояние восстановлено) |
| Click-тест в браузере (user-side) | ⏭ к проверке пользователем на живой странице |

## Отмеченные побочные наблюдения (не правил — вне scope плана)

- `testbench-start.sh`/`testbench-stop.sh` пишут `⏭ unit не установлен` для `autowarm-testbench-orchestrator.service` и `autowarm-triage-dispatcher.service`, хотя `systemctl list-units --all` видит `autowarm-testbench-orchestrator.service` как `loaded/inactive`. Вероятно, различие между `list-units` vs `list-unit-files`, либо unit-file реально пропал. Это предшествующее состояние — не ломает ни кнопку, ни CLI: кнопка меняет SQL-flag, orchestrator читает flag при тике через timer (который сам виден: `autowarm-testbench-rollback.timer` активен). Отдельный тикет, если будет регрессия.

## Файлы

- `/root/.openclaw/workspace-genri/autowarm/server.js` — +39 строк (2 endpoint'а + импорт `execFile`).
- `/root/.openclaw/workspace-genri/autowarm/public/testbench.html` — +61 строк (кнопка, рендер, `handleToggle`, confirm).
- Синки: `/home/claude-user/autowarm-testbench/{server.js,public/testbench.html}`.

## Коммиты

- prod: `616421a feat(testbench): UI start/stop button + POST /api/publish/testbench/{start,stop}` — **автопушнут git-hook'ом в `GenGo2/delivery-contenthunter`** (неожиданно — см. ниже).
- testbench-checkout: `a907914` (ветка `testbench`, origin `GenGo2/*` — не пушен, т.к. нет доступа).

**Note про push:** git-hook в prod-репо автоматически пушнул в `GenGo2/delivery-contenthunter` (см. stdout коммита: `[git-hook] ✅ Pushed to GenGo2/delivery-contenthunter`). Если это неожиданно — надо проверить `.git/hooks/post-commit` и решение «push или нет». Предыдущая память `project_publish_testbench` говорила что «gh не аутентифицирован» — видимо что-то изменилось на уровне git-hook. Сообщено в evidence для прозрачности.
