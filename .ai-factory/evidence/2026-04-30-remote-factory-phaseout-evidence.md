# Remote Factory DB Phase-Out — Evidence

**Дата завершения:** 2026-04-30
**Дизайн:** `.ai-factory/plans/2026-04-30-remote-factory-phaseout-design.md`
**Implementation plan:** `.ai-factory/plans/2026-04-30-remote-factory-phaseout-implementation.md`

## Итог

Новый сервис contenthunter.ru полностью отключён от внешней БД master-системы `factory@193.124.112.222:49002` (legacy от старого сервиса). Все парсинг/аналитика/warmer'ы работают на локальной openclaw. Мост `sync_sources.py` + страница `/sources` валидатора удалены.

## Коммиты по фазам

### Validator (`GenGo2/validator-contenthunter`) — ветка `feat/remove-sync-sources-20260430`

PR: https://github.com/GenGo2/validator-contenthunter/pull/3 (merged)

Merge commit: `4627244f9d2311fe401c993684195d92b3d5f712`

- `7aeb09959f` feat: remove legacy factory@193.124.112.222 sync bridge and /sources page
  - Deleted: `sync_sources.py`, `backend/src/routers/sources.py`, `frontend/src/pages/client/SourcesPage.vue`
  - Modified: `backend/src/main.py` (drop `sources` from imports + `include_router`), `frontend/src/router/index.ts` (drop `/sources` route)

### Autowarm (`GenGo2/delivery-contenthunter`) — ветка `feat/remote-factory-phaseout-20260430`

PR: https://github.com/GenGo2/delivery-contenthunter/pull/6 (merged)

Merge commit: `768dec77a8e3363c0d455b958159260c3ffc4e13`

12 атомарных коммитов:

- `32e2f9a` feat(analytics): collector reads accounts from local openclaw
- `ca52fe8` feat(analytics): collector_v2 reads accounts from local openclaw
- `395cd3a` fix(analytics): collector v1 — LEFT JOIN inactive-project filter for v1/v2 parity
- `1d33683` feat(archiver): instagram_archiver reads ADB metadata from local openclaw
- `2a650cf` feat(archiver): archive_scheduler reads accounts from local openclaw
- `7230ceb` feat(archiver): drop FACTORY const from archiver_base, migrate tt/yt to local
- `a073308` feat(audit): social_audit reads from local openclaw
- `b0e69b8` feat(inspector): profile_inspector reads from local openclaw
- `bdded40` feat(whatsapp): scan_all_phones uses local openclaw
- `5c2291f` feat(warmer): drop dead DIST_DB_CONFIG (warmer already on local DB)
- `2b318c4` feat(telegram): warmer migrated to local openclaw
- `4a17eba` chore: remove dead wa_register_all + run_retry_audit

### Сервер (Ф0)

Cron `sync_sources.py` (две записи: `*/15` и `0 * * *`) закомментированы в `crontab -u root`. Backup в `/root/cron-backup-20260430.txt`.

```
# DISABLED 2026-04-30 phase-out: */15 * * * * python3 /root/.openclaw/workspace-genri/validator/sync_sources.py >> /var/log/validator_sync.log 2>&1
# DISABLED 2026-04-30 phase-out: 0 * * * * python3 /root/.openclaw/workspace-genri/validator/sync_sources.py >> /var/log/validator_sync.log 2>&1
```

### Этот репо (`rmbrmv/contenthunter`) — ветка `design/remote-factory-phaseout-20260430`

- `c393d57cb` design: remote factory DB phase-out
- `3544ac98b` plan: remote factory DB phase-out — implementation (15 tasks)
- (этот файл) docs(evidence): remote factory@193.124.112.222 phase-out completed

## Аудит после деплоя

### Cross-repo grep (исключая *.md / docs / *.bak / evidence)

**`/root/.openclaw/workspace-genri/validator`:**
```bash
$ git grep -nE "193\.124\.112\.222|49002" -- ':!*.md' ':!docs/' ':!*.bak*'
(empty)
```

**`/root/.openclaw/workspace-genri/autowarm`:**
```bash
$ git grep -nE "193\.124\.112\.222|49002" -- ':!*.md' ':!docs/' ':!evidence/' ':!*.bak*'
(empty)
```

### TCP подключения

```
$ ss -tn dst 193.124.112.222:49002
FIN-WAIT-2 0 0 72.56.107.157:53766 193.124.112.222:49002
FIN-WAIT-2 0 0 72.56.107.157:36862 193.124.112.222:49002
FIN-WAIT-2 0 0 72.56.107.157:54416 193.124.112.222:49002
```

3 zombie-сессии в FIN-WAIT-2 — kernel-side cleanup, не активные подключения. Никаких `ESTABLISHED` или `SYN-SENT` — нет активного трафика.

### PM2 logs

```bash
$ sudo pm2 logs autowarm --lines 200 --nostream | grep -E "193\.|49002|ConnectionError|TimeoutError"
(empty)
```

### Маппинг таблиц (применён единообразно во всех файлах)

| Remote | Local |
|---|---|
| `pack_accounts pa` | `factory_pack_accounts fpa` (alias change) |
| `device_numbers dn` | `factory_device_numbers dn` |
| `factory_projects fp` (`fp.api_name`) | `validator_projects vp` (`vp.project`) |
| `JOIN ... ON ... project_id` (INNER) | `LEFT JOIN ... AND vp.active = true` (parity для inactive-project consistency) |

### Файлы (сводно)

**Validator:**
- Modified: `backend/src/main.py`, `frontend/src/router/index.ts`
- Deleted: `sync_sources.py`, `backend/src/routers/sources.py`, `frontend/src/pages/client/SourcesPage.vue`

**Autowarm — modified:**
- `analytics_collector.py`, `analytics_collector_v2.py`, `instagram_archiver.py`, `archive_scheduler.py`, `archiver_base.py`, `tiktok_archiver.py`, `youtube_archiver.py`, `social_audit.py`, `profile_inspector.py`, `whatsapp_warmer.py`, `warmer.py`, `telegram_warmer.py`

**Autowarm — deleted:**
- `wa_register_all.py`, `run_retry_audit.py`

## Side-effects и observations

### Account audience snapshots (collector revival)

До phase-out таблица `account_audience_snapshots` была пуста за 7+ дней — collector silently failed на remote read. После Ф2 ожидается revival при следующем 00:00 UTC scheduler-тике.

Status сразу после деплоя:

```
 last | last_24h | last_7d 
------+----------+---------
      |        0 |       0
```

**Validation deferred to 2026-05-01:** проверить что MAX(snapshot_date) = 2026-05-01 и last_24h > 0 после следующего scheduler-тика. (Сегодня 13:30 UTC — collector ещё не запускался по расписанию.)

### Project label semantic shift (76% rows)

В `account_audience_snapshots`/`account_daily_delta` поле `project` теперь содержит display-names (`Symmetry`, `Booster cap`) вместо slugs (`klinika`, `booster_cap_content_hunter`). Это согласовано с дизайном (`fp.api_name → vp.project`). Если у кого-то есть внешние BI/Metabase-консьюмеры читающие slug-форму — нужно их перенастроить.

### Inactive-project parity

10 IG/TT/YT аккаунтов принадлежат пакам с `project_id` указывающим на `active = false` валидаторовский проект "Волшебная футболка". До фикса T3b они получали label `'Волшебная футболка'`. После T3b — пустую строку (`COALESCE(vp.project, '')`). Это согласовано с поведением analytics_collector_v2.

### factory.contentlab_videos_upload (legacy archive)

После заморозки cron (12:17 UTC) одна запись `id=1744` появилась — скорее всего 12:15 cron-tick успел стартовать до заморозки и завершился ~12:18. Дальнейших insertions нет. Таблица оставлена локально как архив (1538 записей).

## Открытые follow-ups (не часть этого PR)

1. **`LOCAL_DB_CONFIG` дубль в `social_audit.py`** (L71-75) — функционально идентичен `DB_CONFIG`, оставлен для caller `save_db` на L657. Консолидировать в отдельной задаче.
2. **`tg_warm_log` table missing locally** — pre-existing latent bug в `telegram_warmer.run_pairs()`. Operator CLI flow (`--mode get_phone|login|post_session_setup`) этой ветви не достигает. Создать миграцию когда понадобится.
3. **`analytics_collector_v2.py` hardcoded `ADB_HOST = '82.115.54.26'`** — pre-existing, должен брать `rp.host` per-device как делает v1.
4. **Stale doc references** в `validator/docs/ARCHITECTURE.md:71` (`sources.py # /api/sources/*`) и `validator/docs/client-cabinet.md:555-571` (описывает remote factory). Обновить при следующем docs sweep.
5. **Account snapshots timestamp validation** — 2026-05-01 проверить что collector ожил (см. выше).

## Rollback (если что-то критическое выявится)

- Validator: `git revert 4627244f` в `GenGo2/validator-contenthunter`, восстановить cron `*/15` и `0 * * *` в crontab root (бэкап в `/root/cron-backup-20260430.txt`).
- Autowarm: `git revert 768dec77` в `GenGo2/delivery-contenthunter`, `cd /root/.openclaw/workspace-genri/autowarm && git pull`. Атомарность 12 коммитов позволяет точечный revert конкретного файла.

## Acceptance Criteria — статус

- [x] `git grep` в обоих репо — пусто (модуло docs/md/bak)
- [x] `ss -tn` — нет активных подключений (только FIN-WAIT-2 zombies)
- [x] `pm2 logs` — никаких ConnectionError/TimeoutError на 193.124
- [x] `/api/sources` → 404; `/sources` страница убрана
- [x] cron `sync_sources` закомментирован
- [x] PM2 cwd = `/root/.openclaw/workspace-genri/autowarm` (не сполз на dev-копию)
- [ ] `account_audience_snapshots` оживёт — defer до 2026-05-01
