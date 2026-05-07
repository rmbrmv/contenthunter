# Feminista YT-gmail — deploy evidence (2026-05-07)

## Scope
Sub-project B (YT-only). IG/TT failures — отдельные sub-tasks.

## Артефакты
- Spec: `docs/superpowers/specs/2026-05-07-feminista-yt-gmail-design.md`
- Plan: `docs/superpowers/plans/2026-05-07-feminista-yt-gmail-plan.md`
- Branch: `feature/feminista-yt-gmail-2026-05-07` (in `autowarm-testbench`)
- Worktree: `/home/claude-user/work-trees/feminista-yt-gmail`
- Repo: `GenGo2/delivery-contenthunter` (testbench → main)

## Commits (19)
```
4dc4ca8 feat(packages-ui): gmail render+edit on YT account rows with clear-protection
ca2321d feat(packages-ui): gmail input in add-account row (required for YT)
1c55406 feat(packages): GET endpoints return gmail field
ddda174 fix(packages): add console.log on PUT /accounts for parity with POST
2101718 feat(packages): PUT /accounts accepts gmail with clear-to-NULL protection
dabd7f6 feat(packages): POST /accounts validates+persists gmail (YT required)
200873e fix(revision): use pairs directly instead of reconstructing from result
1e3859e feat(revision): backfill NULL gmail for registered YT accounts on device
c4d2d97 fix(revision): docstring update + gmails_pairs in result initializer
d414b32 refactor(revision): discover_gmails via yt_gmail_probe + backward-compat result.gmails
8b9f149 fix(yt-gmail): consolidate adb_shell + deleted_pairs returns gmail
6b8378b fix(yt-gmail): restore deleted-channel auto-deactivation in backfill
c0b612e refactor(yt-gmail): migrate backfill_yt_gmails.py onto shared probe module
5215ca5 fix(yt-gmail): catch TimeoutExpired in adb wrappers + makedirs in try
0372125 feat(yt-gmail): add probe_yt_gmails_live ADB wrapper (thin)
0099c8f fix(yt-gmail): empty-handle guard + docstring + test import position
e103152 feat(yt-gmail): add match_gmail_to_handle with ambiguity handling
70baca9 fix(yt-gmail): NODE_RE order-independent + GMAIL_RE narrowed to @gmail.com
34329b2 feat(yt-gmail): add yt_gmail_probe.extract_yt_picker_pairs
```

## File diff stats
```
 account_revision.py                              |  97 +++-
 backfill_yt_gmails.py                            | 660 +++--------------------
 public/index.html                                |  46 +-
 server.js                                        |  67 ++-
 tests/fixtures/yt_picker_attr_order_reversed.xml |   5 +
 tests/fixtures/yt_picker_empty.xml               |   4 +
 tests/fixtures/yt_picker_two_rows.xml            |   6 +
 tests/fixtures/yt_picker_with_deleted.xml        |   5 +
 tests/test_yt_gmail_probe.py                     |  92 ++++
 yt_gmail_probe.py                                | 531 ++++++++++++++++++
 10 files changed, 873 insertions(+), 640 deletions(-)
```

`backfill_yt_gmails.py` сократился на 660 строк (вынесли parsing/nav в `yt_gmail_probe.py`); чистый прирост код-базы — 233 строки.

## Pre-deploy smoke
- `tests/test_yt_gmail_probe.py`: **11/11 passed** (0.05s)
- Полный `tests/`: 753 passed, 12 failed, 4 skipped — все 12 failures pre-existing (`test_testbench_orchestrator.py`, не связано с этим спеком; verified via stash check в Task 5).
- `node --check server.js`: **syntax-ok**
- HTML grep `new-acc-gmail|acc-gmail-input|acc-gmail-display` в `public/index.html`: **8 references** (new-row input + 2 lookups; existing-row input + edit-toggle + display span + clear-protection check + ...).

## Deploy выполнен ✅ 2026-05-07 17:19 UTC

1. ✅ Feature branch merged → main `bb7c140` (no-ff merge commit), pushed to GenGo2/delivery-contenthunter.
2. ✅ `git pull --ff-only` в `/root/.openclaw/workspace-genri/autowarm/` (claude-user может писать в этот path без sudo, см. `reference_vps_fs_access.md`).
3. ✅ `sudo pm2 reload autowarm` — uptime 10s post-reload, exec cwd корректный, лог чист (только pre-existing infra noise — Pi #4/#6 unreachable, dispatch-queue pq=766 type-error — НЕ от наших правок).
4. ✅ Deployed code verified: `extract_yt_picker_pairs` в `yt_gmail_probe.py`, "gmail обязателен для YouTube" в `server.js`, `new-acc-gmail` в `public/index.html`.

## Gmail filled для Feminista ✅ 2026-05-07

`backfill_yt_gmails.py` НЕ нашёл Feminista accounts в picker'е (см. ниже «Critical finding»). Заполнено через прямой SQL UPDATE на основе скринов picker'а от пользователя:

| acc_id | username | gmail |
|---|---|---|
| 1852 | feminista.beauty | `veronikamavrikeva@gmail.com` |
| 1855 | feminista_patches | `avdodyaderevenskaya@gmail.com` |
| 1860 | feminista_glow | `glafirakuznechnaya@gmail.com` |

Re-queued: `publish_queue.id IN (1136, 1148, 1156)` → `status='pending', publish_task_id=NULL`. dispatchPublishQueue (5 мин cycle) подхватит.

## Critical finding — YT picker структура изменилась ⚠️

При попытке `backfill_yt_gmails.py --device-number 154/155/156` всплыло, что `extract_yt_picker_pairs` ловит только **legacy-формат** rows (`text="X@gmail.com" content-desc="X@gmail.com"`). Реальный picker сейчас иерархичный:

- **Google account header**: `<text="DisplayName"/>` + `<text="user@gmail.com"/>` (отдельные ноды)
- **Channels под аккаунтом**: `<text="ChannelName"/>` + `<text="@channel-handle"/>` (отдельные ноды, gmail канала = gmail Google-родителя)
- **Separator**: `<text="Другие аккаунты"/>` между группами

Пример с phone #154:
- `Veronikamavrikeva` + `veronikamavrikeva@gmail.com` (Google account)
  - `Feminista` + `@feminista.beauty` (channel — gmail = veronikamavrikeva)
- `Другие аккаунты`
- `zxclesya154@gmail.com` (Google account, just gmail)
  - `WellFresh_1` + `5 подписчиков` (channel)

**Implication для production:**
1. `backfill_yt_gmails.py` пропускает каналы в современных picker'ах → старые NULL gmail не восполнятся автоматом.
2. **`account_switcher.find_yt_row_by_gmail`** скорее всего использует тот же regex-формат → может не находить inactive каналы по gmail (нужно проверить и переписать).
3. Revision auto-backfill из Task 6 имеет ту же ограниченность парсера.

Дамп для отладки сохранён: `/tmp/yt_debug_154/round_*.xml` (18KB каждый). Скрин phone 154: см. `reference_yt_picker_structure_2026_05_07.md` (если будет создан).

## Follow-ups в backlog

- **B-YT-parser** — переписать `extract_yt_picker_pairs` + `extract_yt_picker_deleted_pairs` под иерархичный picker (stream-state-machine: gmail nodes открывают Google section, @handle-nodes ассоциируются с последним open gmail).
- **B-YT-switcher** — проверить и обновить `account_switcher.find_yt_row_by_gmail` для современного picker'а (если использует ту же логику).
- **B-IG** — `ig_target_not_in_picker` для feminista_*.
- **B-TT** — `tt_target_not_on_device` для feminista_*.
- 100+ legacy YT NULL gmails — после fix B-YT-parser.

## Memory updates применены
- `project_session_2026_05_07_shipped.md` — B-YT в Отгружено; B-YT-parser, B-YT-switcher, B-IG, B-TT в Backlog.
- `project_yt_gmail_switcher.md` — заметка про shared probe + caveat про парсер.
