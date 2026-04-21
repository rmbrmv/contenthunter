# Evidence — Эль-косметик: жалоба о загрузке контента в планировщике

**Дата:** 2026-04-20
**Источник:** жалоба клиента Danil → «не смог загрузить контент в планировщике https://client.contenthunter.ru/dashboard»
**Автор анализа:** Claude (sonnet/opus), agent workspace `/home/claude-user/contenthunter`
**Связанный план:** `.ai-factory/PLAN.md` (Fast)

## 1. Контекст клиента

`PGPASSWORD=openclaw123 psql -h localhost -U openclaw -d openclaw`:

```sql
SELECT id, login, role, project_id, last_login_at, created_at
FROM validator_users
WHERE login ILIKE '%el%';
```

```
 id |               login               |  role  | project_id |         last_login_at         |          created_at
----+-----------------------------------+--------+------------+-------------------------------+-------------------------------
 71 | client_el_kosmetik_content_       | client |         82 |                               | 2026-03-30 09:52:49
 50 | client_el_kosmetik_content_hunter | client |         82 | 2026-04-20 06:30:40           | 2026-03-24 08:16:39
```

- **Активный логин:** `client_el_kosmetik_content_hunter` (id=50). `id=71` — дубль с обрезанным логином, `last_login_at=NULL` (тестовый/устаревший).
- **Проект:** `validator_projects.id=82` → `project='Эль-косметик'`, `api_name='el_kosmetik_content_hunter'`, `active=true`.

## 2. Загрузки клиента в БД

```sql
SELECT id, uploader_id, content_type, original_filename, file_size_bytes, status, created_at
FROM validator_content
WHERE uploader_id IN (50, 71)
ORDER BY created_at DESC;
```

```
  id  | uploader_id | content_type | original_filename                          | file_size_bytes | status   | created_at
------+-------------+--------------+--------------------------------------------+-----------------+----------+-------------------------------
 1850 |          50 | video        | AQOfT1Kl_...mp4                            |         2943996 | approved | 2026-04-18 04:33:43
 1849 |          50 | video        | AQNMeK8b...(1).mp4                         |        13053425 | approved | 2026-04-18 04:31:59
 1848 |          50 | video        | AQMhNc1W...mp4                             |         2951629 | approved | 2026-04-18 04:28:46
 1847 |          50 | video        | AQM89oTn...mp4                             |         2798140 | approved | 2026-04-18 04:27:18
```

- **4 успешных видео-загрузки 2026-04-18.** Все 4 файла `moderation_status=passed`, `status=approved`.
- **2026-04-20: 0 записей** за клиентом, хотя он залогинен в 06:30 UTC. → Сегодня загрузить не удалось.

## 3. Что клиент делал сегодня — access-лог

`/root/.pm2/logs/validator-out.log`, IP `101.51.168.248` (сегодняшняя сессия клиента):

```
19490 POST /api/auth/login                              200 OK
19566 POST /api/auth/login                              200 OK   (повторные входы)
19622 POST /api/auth/login                              200 OK
19642 POST /api/auth/login                              200 OK
...
19760 POST /api/upload/generate-description             502 Bad Gateway
19761 POST /api/upload/images                           422 Unprocessable Entity
19763 POST /api/upload/images                           422 Unprocessable Entity
19765 POST /api/upload/images                           422 Unprocessable Entity
19767 POST /api/upload/images                           422 Unprocessable Entity
19769 POST /api/upload/images                           422 Unprocessable Entity
19771 POST /api/upload/images                           422 Unprocessable Entity
...
104598 POST /api/auth/login                             200 OK   (клиент вернулся позже)
104658+ POST /api/schedule/move-unpublished             200 OK   (только двигал слоты, загружать уже не пробовал)
```

**Вывод:** сегодня клиент попытался сгенерировать автоописание (получил 502) и загрузить карусель/пост (6× подряд 422), затем сдался.

## 4. Корневые причины

### R1 — 422 на `/api/upload/images` (главная причина жалобы)

**Файлы:**
- `/root/.openclaw/workspace-genri/validator/backend/src/services/image_metadata.py:59-139` (`check_image_blockers`)
- `/root/.openclaw/workspace-genri/validator/backend/src/routers/upload.py:390-586` (`upload_images`)

Требования:
- 9:16: `1080×1920` или `768×1376` (±5% разрешения, ±2% аспекта)
- 1:1: `1080×1080` (те же допуски)

Любой другой размер → `HTTPException(422, {"blockers": [...], "message": "... не прошёл техническую проверку"})`. Логируется только `log.info("image blockers: %s", [b.code for b in blockers])` — без `filename`, `width`, `height`, `user_id`, что делает diagnose пост-фактум невозможным без воспроизведения.

Фронт (`UploadModal.vue::startImagesUpload`, строки 1214-1290) **не делает preflight** размеров до отправки — клиент узнаёт о провале по факту 422.

### R2 — 502 на `/api/upload/generate-description`

**Прямая проверка ключа:**
```bash
curl -X POST https://api.anthropic.com/v1/messages \
  -H "x-api-key: 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" \
  -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5","max_tokens":50,"messages":[{"role":"user","content":"ping"}]}'

→ {"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"},"request_id":"req_011CaEeRy9CrE2rEQMEM1uAU"}
```

**Место:** `/root/.openclaw/workspace-genri/validator/backend/.env`
```
ANTHROPIC_API_KEY=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
```

Префикс `sk-ant-oat01-` — это OAuth-issued token, не API key. Вероятно отозван или срок истёк. Обработчик в `src/routers/upload.py:238-253`:

```python
try:
    client = _anthropic.AsyncAnthropic(api_key=anthropic_key)
    message = await client.messages.create(...)
    description = message.content[0].text
except Exception as e:
    raise HTTPException(status_code=502, detail=f"Failed to generate description: {str(e)}")
```

Голый `except Exception` → все ошибки (auth, rate limit, network) уходят в 502.

### R3 — 500 на `/api/analytics/client/publications`

**Traceback из `/root/.pm2/logs/validator-error.log`:**
```
File "src/routers/analytics.py", line 551, in client_publications
asyncpg.exceptions.DataError: invalid input for query argument $3: '2026-03-31'
(expected a datetime.date or datetime.datetime instance, got 'str')
```

**Место:** `src/routers/analytics.py:443-489`
```python
@router.get("/client/publications")
async def client_publications(
    ...
    date_from: Optional[str] = Query(None),   # ← str, asyncpg ждёт date
    date_to:   Optional[str] = Query(None),   # ← str
    ...
):
    if date_from:
        params["date_from"] = date_from       # ← bind как str → DataError
    if date_to:
        params["date_to"] = date_to
```

Не ломает upload, но ломает «Журнал публикаций» на дашборде, когда клиент выбирает диапазон дат → общее ощущение «сайт не работает».

### R4 — 401 login с ведущим пробелом

**Место:** `src/routers/auth.py:18-40`

В error-log множественные:
```
[FIX] Login failed: user ' client_el_kosmetik_content_hunter' not found or inactive
```

Клиент копировал логин с пробелом (менеджер паролей / автодополнение). Нет `.strip()`, поэтому запрос `WHERE login = ' client_el_kosmetik_content_hunter'` не находит запись → 401.

## 5. Что **не** причина (отсеяно)

- **`[upload/file] S3 put failed (network): WriteTimeout`** в error-log ссылается на `_put_bytes_to_s3` (`upload.py:63`). Этой функции больше нет в текущем коде — миграция на boto3 multipart была в commit `60547bd fix(upload): boto3 multipart (Signature v2) вместо sync requests.put`. Стэйл-лог от старого процесса до рестарта (validator uptime 2D на момент анализа).
- **Video-аплоад `/upload/file`** — у клиента 4 успешные загрузки 2026-04-18; путь рабочий.
- **БД-пул исчерпан** — видим `QueuePool timeout` только на строке 107765 (давно); свежих нет.

## 6. Затрагиваемые файлы для фикса

| Файл | Задача |
|---|---|
| `/root/.openclaw/workspace-genri/validator/backend/.env` | Task 2 — новый `ANTHROPIC_API_KEY` |
| `/root/.openclaw/workspace-genri/validator/backend/src/routers/upload.py:199-255` | Task 3 — graceful Anthropic errors |
| `/root/.openclaw/workspace-genri/validator/backend/src/routers/analytics.py:443-489` | Task 4 — `date_from/date_to` как `datetime.date` |
| `/root/.openclaw/workspace-genri/validator/backend/src/routers/auth.py:18-40` | Task 5 — strip login |
| `/root/.openclaw/workspace-genri/validator/backend/src/services/image_metadata.py:59-139` | Task 6 — расширенные логи блокеров |
| `/root/.openclaw/workspace-genri/validator/backend/src/routers/upload.py:390-586` | Task 6 — log.warning с контекстом |
| `/root/.openclaw/workspace-genri/validator/frontend/src/components/UploadModal.vue:1214-1290` | Task 6 — preflight аспекта |

## 7. Следующий шаг

Детали и чекпоинты — в `/home/claude-user/contenthunter/.ai-factory/PLAN.md`.
