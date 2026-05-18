# WP #86 PR1 — local smoke evidence (2026-05-18)

## Setup

Synthetic task в локальном openclaw:

```sql
INSERT INTO publish_tasks (platform, account, status, started_at, updated_at, url_capture_attempts, post_url, log)
VALUES ('TikTok', '__wp86_test_acct', 'awaiting_url',
        NOW() - INTERVAL '30 minutes',
        NOW() - INTERVAL '10 minutes',  -- 10мин stale → проходит WHERE updated_at < NOW() - 1min
        29,                              -- attempts на грани MAX=30
        'https://www.tiktok.com/@__wp86_test_acct',
        '[wp86-smoke] synthetic task for PR1 verification');
```

Сервер на ветке `feat/wp86-pr1-poller-published-no-url`:

```bash
URL_CAPTURE_MAX_ATTEMPTS=30 URL_POLLER_LIMIT=100 PORT=4849 node server.js
```

Прод `autowarm` (pm2 id 34) был кратко остановлен на ~90s чтобы исключить
гонку (оба сервера poll'или ту же таблицу синхронно в HH:XX:15).

## Observed behaviour

```
[url-poller] task#7462 TikTok: url_capture_exhausted (30 attempts) → published_no_url ⚠️
```

DB state после promotion:

```
  id  |      status      | url_capture_attempts | url_capture_last_attempt_at |   wp86_log
------+------------------+----------------------+-----------------------------+-------------------------------------------------------------------------------------------
 7462 | published_no_url |                   30 | 2026-05-18 16:14:19.299205  | [url-poller WP#86] url_capture_exhausted after 30 attempts — promoted to published_no_url
```

## Verification

| Acceptance criterion | Status |
|---|---|
| Synthetic `awaiting_url` task с attempts=29 ловится поллером | ✅ |
| Поллер инкрементит attempts (29 → 30) | ✅ |
| При attempts >= MAX вызывается `shouldPromoteToPublishedNoUrl` → true | ✅ |
| UPDATE статуса в `published_no_url` | ✅ |
| Лог-маркер `url_capture_exhausted ... promoted to published_no_url` в `publish_tasks.log` | ✅ |
| `url_capture_last_attempt_at` устанавливается на NOW() | ✅ |
| Console.log `⚠️` warning эмитится | ✅ |

## Side observations

Поллер также подобрал реальных zombies на первом тике:

- `task#961 Instagram @makiavelli485` — NULL `started_at`, теперь attempts=1
- `task#3077 YouTube @Ivana-o3j` — NULL `started_at`, теперь attempts=1

После Task 5 (NULL coalesce) + Task 6 (attempts++) — оба будут промоутиться
в `published_no_url` через ~1 час прод-выкатки (при условии что прод pollер 
будет инкрементить — это произойдёт после schema migration + deploy кода).

Эти 2 zombies — кандидаты #1 на post-deploy verification (Task 16).

## Cleanup

```bash
DELETE FROM publish_tasks WHERE account='__wp86_test_acct';  -- DELETE 1
kill <local_server_pid>
sudo pm2 start autowarm  # restored prod
```

Prod `autowarm` restarted, status: online (exec cwd `/root/.openclaw/workspace-genri/autowarm`).
