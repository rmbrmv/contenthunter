# Evidence — Frontend factory rollout (unic) + testbench backport (2026-04-29)

**Status:** ✅ **SHIPPED**
- Frontend factory rollout for `/api/unic/tasks` — commit `ad81dcd` in prod main
- Testbench backport — merge commit `f49ed27` in `feat/packages-modal-redesign-20260428`

## Phase 1 — Testbench backport (Path A: merge with -X theirs)

### Pre-state

```
testbench branches:
- feat/packages-modal-redesign-20260428 (current checkout, HEAD 7641d48)
  └─ 1 unique commit (packages-modal UI work)
  └─ 5 commits cherry-picked into prod (1bf05f3, 5a165f8, 74095b8, 80f6afa, 9b382d4)
- testbench (older, HEAD 96c1c39)
- prod-main (older, HEAD 224b4e8)

prod main: d880a3f (27+ commits ahead)
```

### Merge attempt

```
$ git merge origin/main --no-edit
CONFLICT (content): Merge conflict in account_switcher.py
CONFLICT (content): Merge conflict in tests/test_switcher_youtube.py
```

Conflicts ожидаемые — testbench cherry-picks vs prod cherry-picks с патч-id различиями.

### Resolution: -X theirs

```
$ git merge --abort
$ git merge -X theirs origin/main --no-edit
Merge made by recursive.
[merge OK — авто-prefer prod's сторону для конфликтных чанков]
```

Result: `f49ed27` merge commit. testbench filesystem now contains:
- Все prod коммиты (включая IG bundle, AI Unstuck, paginated etap2/3)
- Single WIP commit `7641d48` (packages-modal UI redesign) на топе

### Smoke

```
$ python -c "from publisher_base import _is_action_loop, _validate_tap_coords; print('OK')"
OK

$ node -c server.js
(no errors)

$ node --test paginate.test.js
19/19 passed
```

### node_modules

```
$ ls -la node_modules
lrwxrwxrwx  → /root/.openclaw/workspace-genri/autowarm/node_modules
```

Symlink целый (как и было). Per memory `feedback_autowarm_testbench_deploy.md` —
после merge symlink risk; в этом merge'е не сломался (никто не трогал
node_modules в коммитах).

### PM2 cwd drift — pre-existing issue (not blocking)

```
$ sudo pm2 describe autowarm-testbench
exec cwd = /root/.openclaw/workspace-genri/autowarm  ← prod path, NOT testbench
```

PM2 process для autowarm-testbench запущен с cwd = prod path. Testbench process
реально читает PROD код, не testbench. Это pre-existing PM2 dump path drift
(см. memory `feedback_pm2_dump_path_drift.md`).

**Эффект backport'а:**
- Filesystem testbench branch обновлён → manual smoke testing / scripts из
  `/home/claude-user/autowarm-testbench/` теперь видят свежий код
- Git history aligned — последующие cherry-picks / merges работают предсказуемо
- PM2 process остаётся на prod коде (это OK, прод и есть «правильный» источник)

Fix PM2 cwd drift — отдельная задача (per memory: «delete+start из ecosystem
config»).

### Push

```
$ git push origin HEAD
  7641d48..f49ed27  HEAD -> feat/packages-modal-redesign-20260428
```

## Phase 2 — Frontend factory rollout for `/api/unic/tasks`

### Server changes

`/api/unic/tasks/by-ids` endpoint добавлен (для liveRefresh поллинга через
factory). Использует существующий `buildByIdsQuery` helper и
`buildUnicTasksFilters`. Defensive parsing (max 500 ids, integer-only filter).

```
GET /api/unic/tasks/by-ids?ids=1,2,3
→ { "rows": [...] }  // только те, что matching фильтрам, остальные drops'ятся
                     // (factory использует это для merge-update + cleanup строк
                     // которые перестали соответствовать active filter)
```

Route declared **ДО** `/api/unic/tasks` (важно для Express matching order).

### Factory enhancement: `emptyHtml` config

`paginated-table.js` had hardcoded:
```js
tbody.innerHTML = `<tr><td colspan="${cfg.emptyColspan}" ...>${msg}</td></tr>`;
```

Это работало только для tbody-shaped containers. Для unic (`<div id="unic-tasks-list">`)
это рендерит broken HTML (`<tr><td>` внутри `<div>`).

Add config option:
```js
if (typeof cfg.emptyHtml === 'function') {
  tbody.innerHTML = cfg.emptyHtml(msg);
} else {
  // существующий fallback для tbody consumers
  tbody.innerHTML = `<tr><td colspan>...`;
}
```

Backwards-compat: existing consumers (publish_tasks, queue, archive) не имеют
emptyHtml → используют fallback. Zero behavior change для них.

### unic UI wiring

```javascript
let _unicTable = null;
function _ensureUnicTable() {
  if (_unicTable) return _unicTable;
  _unicTable = createPaginatedTable({
    tableId: 'unic',
    isActiveTab: () => currentSection === 'unic',
    endpoints: {
      list: '/api/unic/tasks',
      byIds: '/api/unic/tasks/by-ids',
      // stats: deferred — top-of-page stats идут через legacy /api/unic/stats,
      //        factory's /tasks/stats не привязан к UI
    },
    tbodyId: 'unic-tasks-list',
    sentinelId: 'unic-sentinel',
    defaultSort: { col: 'id', order: 'desc' },
    pageSize: 100,
    liveRefresh: true,
    refreshPollMs: 5000,
    emptyMessage: 'Задач пока нет. Создайте первую!',
    renderRow: _unicRenderRow,
    emptyHtml: (msg) => `<div class="text-center text-gray-400 py-12 text-sm">${msg}</div>`,
    filtersToServer: (f) => f,
  });
  return _unicTable;
}

async function unicLoadTasks() {
  try {
    const tbl = _ensureUnicTable();
    await tbl.reset();
    tbl.onTabActivate();
  } catch (e) {
    if (e instanceof ReferenceError) { setTimeout(() => unicLoadTasks(), 0); return; }
    console.error('unicLoadTasks:', e);
  }
}
```

Key changes:
- `_unicRenderRow(t)` extracted из inline (testability + reuse в factory)
- Sentinel `<div id="unic-sentinel">` добавлен после `unic-tasks-list`
- TDZ guard через try/catch ReferenceError + setTimeout(0) defer
- Удалён `unicLoadTasks` из `setInterval` в `unicInit` — factory сам поллит
  /by-ids каждые 5s через built-in mechanism (preserves scroll position)

### Smoke

```
$ node -c server.js  → OK
$ node --test paginate.test.js  → 19/19 passed
$ pm2 restart autowarm  → restart #215, online, no unstable, exec cwd correct
$ pm2 logs autowarm --lines 20  → no errors
$ curl https://delivery.contenthunter.ru/ | grep -cE "_unicTable|_ensureUnicTable|unic-sentinel|emptyHtml"
9   ← live page has new code
```

### What's NOT migrated (5 endpoints — намеренный skip)

- `/api/factory/tasks` (44 rows): factory rollout = busy-work, 0 user-visible value
- `/api/factory/accounts` (44 rows): то же
- `/api/whatsapp/tasks` (0 rows): пусто, нечего паджинировать
- `/api/telegram/tasks` (0 rows): то же
- `/api/phone-warm/tasks` (1 row): 1 строка
- `/api/tasks` (315 rows): имеет рабочий custom `tasks-pagination` div, переписывание = регрессия risk

BC layer на server-side гарантирует existing UI работает без изменений.

## Memory updates

- `MEMORY.md` — bump entry: «etap 3 + frontend для archive/unic + testbench backport ✅».
- `project_paginated_tables_pilot.md` — обновить status и pattern notes.

## Commits

| Repo | SHA | Message |
|---|---|---|
| `delivery-contenthunter` (testbench, branch feat/packages-modal-redesign-20260428) | `f49ed27` | `Merge remote-tracking branch 'origin/main' into feat/packages-modal-redesign-20260428` |
| `delivery-contenthunter` (prod main) | `ad81dcd` | `feat: paginated-table factory rollout for /api/unic/tasks (etap 3 #2)` |
| `contenthunter` | (pending) | `docs(plans+evidence): unic factory rollout + testbench backport` |
