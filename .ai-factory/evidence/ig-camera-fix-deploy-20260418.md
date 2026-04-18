# IG camera-open recovery — deploy smoke 2026-04-18

**Scope:** T6 из `.ai-factory/PLAN.md` — deploy + live smoke rerun для `ig_camera_open_failed` regression fix.

## Commits (GenGo2/delivery-contenthunter, branch `main`)

| hash | subject | stat |
|---|---|---|
| `d4fa943` | `fix(publisher): recover IG camera open on highlights/gallery screens` | +143 / -3 in publisher.py |
| `4086d82` | `test(publisher): unit coverage for IG camera recovery paths` | +239 (3 new files) |

Оба push'нуты git-hook'ом на GitHub.

## Pre-deploy unit tests

```
tests/test_publisher_ig_camera_recovery.py
  14 passed in 0.19s
tests/test_publisher_ig_editor.py (existing)
  7 passed in 0.06s
```

## pm2 restart autowarm

```
pid:     771666 → 1269978 (new)
status:  online
uptime:  20h → 0s (fresh)
restart: 155 → 156
port:    3848
```

Последние 10 строк логов при старте — clean, без import-ошибок:

```
[dotenv@17.3.1] injecting env (17) from .env
✅ БД инициализирована
🚀 Autowarm запущен на порту 3848
📡 Device mapping sync job запланирован (каждый час, add_unknown=true)
📅 Scheduler запущен
[assign-queue] Обрабатываем 5 результатов уникализации...
```

## Smoke strategy

**Метод:** scheduler-based (без ручного вставления в очередь).

**Почему:** aneco/anecole кластер имел 6 IG-fails за последние 48h — scheduler
естественно поставит задачу на эти аккаунты в следующий slot (обычно ≤1ч).

**Что мониторим (через 1-3 часа):**

```sql
-- Новые event-категории должны появиться (recovery triggered)
SELECT meta->>'category' AS category,
       COUNT(*) AS n
  FROM task_events
 WHERE created_at > '2026-04-18 10:50:00'
   AND meta->>'category' IN (
       'ig_highlights_empty_state_seen',
       'ig_gallery_picker_in_camera_loop',
       'ig_camera_open_reset_attempted'
   )
 GROUP BY category
 ORDER BY n DESC;
```

```sql
-- Fail-события теперь должны содержать detected_state для триажа
SELECT meta->>'category' AS cat,
       meta->>'detected_state' AS state,
       COUNT(*) AS n,
       MAX(created_at) AS latest
  FROM task_events
 WHERE meta->>'category' = 'ig_camera_open_failed'
   AND created_at > '2026-04-18 10:50:00'
 GROUP BY cat, state
 ORDER BY latest DESC;
```

## Success criteria (T7, 24ч spot-check)

- [ ] `ig_camera_open_failed` на 3-х aneco/anecole устройствах (RF8Y80ZT14T,
      RF8Y90LBX3L, RF8Y90LBZPJ) < 1/24h (было 6/48h).
- [ ] `ig_highlights_empty_state_seen` ≥ 3 events с последующим `done` статусом
      задачи (доказательство что recovery работает).
- [ ] Нет event'ов `ig_camera_open_reset_attempted` без последующего `done`
      или `ig_camera_open_failed` в той же задаче (признак бесконечного
      reset-loop'а — **не должен появиться**).

## Rollback (если регрессия усилится)

```bash
cd /root/.openclaw/workspace-genri/autowarm
git revert d4fa943 4086d82
sudo pm2 restart autowarm
```

Риск низкий — все изменения аддитивные (новые ветки в loop), старые handler'ы
нетронуты. `_dismiss_ig_edits_promo` / `_ig_tap_action_bar_done` /
`_ig_find_camera_icon_in_options` работают как раньше.

## Next step

Через 24ч — evidence-commit с post-deploy-verification в
`.ai-factory/evidence/ig-camera-fix-24h-20260419.md`.
